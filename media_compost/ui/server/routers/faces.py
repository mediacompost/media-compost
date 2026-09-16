"""Faces: what was detected, and who it is.

Detection itself is an AI job (``jobs._apply_faces``); this router owns
everything a person does with the result — saying who a face is, dismissing
one, drawing one by hand, and the clustering view that lets one click name a
person across every picture they appear in.

**Saying who a face is assigns that subject's tag to the item.** That
connection is the point of the whole feature: the face is the evidence, the tag
is what search, training and export actually read.

A face may be several people at once — a drawn character and the actor who
plays them, each with an age of its own — so who it is lives in ``ItemSubject``
rows rather than a column here. Everything below reads that list; nothing reads
"the" subject of a face, because there is no such thing.
"""

from __future__ import annotations

import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from media_compost import faces as facelib

from ...facevec import (cluster_spaces_fast, group_matrices,
                        odd_ones_out, pair_likeness)
from ...jobs import suggest_around_faces
from media_compost import partialdate
from media_compost import resolve
from media_compost.db import Face, Item, ItemSubject, Sequence, Subject, Tag, \
    chunked
from media_compost.storage import ItemStore
from media_compost.ops import Ctx, faces as ops_faces
from media_compost.ops.errors import Invalid
from ..deps import get_ctx, get_library, get_session
from ..schemas import ClustersDiffer, ClusterUnnamed, FaceCluster, \
    FaceCreate, FaceGrouping, FaceGroupingOut, FaceOut, FaceOutlineSet, \
    FaceSubjectIn, FaceSubjectOut, FaceUpdate, NameCluster, NamedFaces, \
    OddOnesOut, SimilarFace

router = APIRouter(prefix="/api/faces", tags=["faces"])

# The writers live in `ops.faces` now; these names are re-exported because the
# item detail, the jobs worker and the tests reach for them HERE, and this is a
# rename nobody outside needs to care about.
appearances_of = ops_faces.appearances_of
assign_subject_tag = ops_faces.assign_subject_tag
drop_unconfirmed_tag = ops_faces.drop_unconfirmed_tag
appear = ops_faces.appear
snapshot = ops_faces.snapshot
_nameless_subject_ids = ops_faces.nameless_subject_ids


def resolve_when(date: Optional[int], age: Optional[int],
                 since: Optional[int]) -> tuple[Optional[int], Optional[int], bool]:
    """A date and an age, with the missing half derived from the since-date.

    `derived` is True when anything here was worked out rather than typed, so
    the UI can show it as a hint instead of a value.
    """
    if date is None and age is None:
        return None, None, False
    derived = False
    if since:
        if age is None and date:
            age, derived = partialdate.age_at(since, date), True
        elif date is None and age is not None:
            date, derived = partialdate.date_from_age(since, age), True
    return date, age, derived


def _subject_catalog(s: Session, rows: list[ItemSubject]
                     ) -> tuple[dict[int, Subject], dict[int, str], dict[int, str]]:
    """The subjects (and their tag names) these appearances point at, loaded
    in TWO chunked queries however many faces are being hydrated — the per-face
    pair of lookups was an N+1 across every list of crops."""
    subjects: dict[int, Subject] = {}
    for chunk in chunked({r.subject_id for r in rows}):
        for sub in s.execute(
            select(Subject).where(Subject.id.in_(chunk))
        ).scalars().all():
            subjects[sub.id] = sub
    tags: dict[int, str] = {}
    # The identity tag's NAME and its one-liner: what a person is, in a line,
    # is the tag's (see `Subject`), so the face rows read it from here.
    comments: dict[int, str] = {}
    for chunk in chunked(
            {sub.tag_id for sub in subjects.values() if sub.tag_id}):
        for tid, name, comment in s.execute(
            select(Tag.id, Tag.name, Tag.comment).where(Tag.id.in_(chunk))
        ).all():
            tags[tid] = name
            comments[tid] = comment or ""
    return subjects, tags, comments


def _subject_out(rows: list[ItemSubject], subjects: dict[int, Subject],
                 tags: dict[int, str],
                 comments: dict[int, str] | None = None) -> list[FaceSubjectOut]:
    """Pure assembly of the appearance list from preloaded catalogs."""
    out = []
    for r in rows:
        sub = subjects.get(r.subject_id)
        when = resolve_when(r.when_date, r.when_age,
                            sub.since_date if sub else None)
        out.append(FaceSubjectOut(
            id=r.id, subject_id=r.subject_id,
            name=(sub.display_name if sub else ""),
            comment=((comments or {}).get(sub.tag_id, "")
                     if sub and sub.tag_id else ""),
            tag=(tags.get(sub.tag_id, "") if sub and sub.tag_id else ""),
            since_date=(sub.since_date if sub else None),
            assigned_by=r.assigned_by or "user", match_score=r.match_score,
            when_date=when[0], when_age=when[1], when_derived=when[2],
        ))
    # Named first: a nameless identity holding a merged cluster together is
    # machinery, and it must not head the list under a real person. STABLE,
    # and only on that flag — the callers hand rows in the sidebar's own
    # order (`appearances_of` sorts by position), and the chip's "first
    # claim" has to follow a drag-reorder rather than the alphabet.
    out.sort(key=lambda r: r.name == "" and r.tag == "")
    return out


def _rows(s: Session, rows: list[Face]) -> list[FaceOut]:
    who = appearances_of(s, [f.id for f in rows])
    # One catalog for every face's appearances, not a pair of queries per face.
    subjects, tags, comments = _subject_catalog(
        s, [r for f in rows for r in who.get(f.id, [])])
    uids: dict[int, str] = {}
    for chunk in chunked({f.item_id for f in rows}):
        for iid, uid in s.execute(
            select(Item.id, Item.uid).where(Item.id.in_(chunk))
        ).all():
            uids[iid] = uid
    # Model NAMES only — reading the vectors themselves to answer a boolean
    # was most of a large listing's query bytes.
    vectors = facelib.embedding_models_of(s, [f.id for f in rows])
    outlines = ops_faces.outlines_of(s, [f.id for f in rows])
    edits = ops_faces.box_edits_of(s, [f.id for f in rows])
    from media_compost.ops.tagassign import points_list

    def _outline(fid: int):
        row = outlines.get(fid)
        return [row.x, row.y, row.w, row.h] if row is not None else None

    return [
        FaceOut(
            id=f.id, item_id=f.item_id, item_uid=uids.get(f.item_id, ""),
            file_id=f.file_id,
            x=f.x, y=f.y, w=f.w, h=f.h,
            det_score=f.det_score,
            models=[m for m in f.model.split(",") if m],
            subjects=_subject_out(who.get(f.id, []), subjects, tags, comments),
            dismissed=f.dismissed,
            has_embedding=bool(vectors.get(f.id)),
            embedded_by=vectors.get(f.id) or [],
            outline=_outline(f.id),
            outline_points=(points_list(outlines[f.id].points)
                            if f.id in outlines else None),
            edited=f.id in edits,
        )
        for f in rows
    ]


def _faces_of(s: Session, item_id: int) -> list[Face]:
    """An item's faces, biggest first — the face a picture is about is usually
    the largest, and the sidebar reads top to bottom."""
    rows = s.execute(select(Face).where(Face.item_id == item_id)).scalars().all()
    return sorted(rows, key=lambda f: -(f.w * f.h))


def _label(s: Session, subject: Subject | None) -> str:
    if subject is None:
        return "nobody"
    if subject.display_name:
        return subject.display_name
    tag = s.get(Tag, subject.tag_id) if subject.tag_id else None
    return tag.name if tag is not None else f"subject #{subject.id}"


@router.get("/item/{item_id}", response_model=list[FaceOut])
def list_faces(item_id: int, s: Session = Depends(get_session)):
    return _rows(s, _faces_of(s, item_id))


def _unnamed_groups(s: Session, limit: int, cache=None
                    ) -> tuple[list[tuple[list[int], bool, Optional[int]]],
                               dict]:
    """Every face nobody has named, grouped into who they probably are —
    as ID LISTS, `(members, grouped, holding subject)`, plus the
    appearances read on the way. The strip's candidates want exactly this
    and nothing more; hydrating two hundred clusters' faces to read their
    ids was most of what an offer cost (2026-09).

    Faces with no descriptor (the anime detector produces none) come back one
    per group, which is what makes this view work for a detection-only model:
    ungrouped, but still the one place to go through them.

    A cluster somebody MERGED by hand is held together by a nameless subject,
    and those faces are grouped by it rather than re-clustered: an answered
    question must not be asked again by the next run of an algorithm.

    The named faces are excluded IN SQL (a face is named when any of its
    appearances points at a subject with a tag or a display name — the exact
    complement of the nameless-subject rule), so they are never loaded here;
    ``limit`` cuts the cluster list before any Face row is hydrated. ``cache``
    is the library's ``facevec.FaceCache`` — the clustering itself is reused
    until faces, embeddings, appearances or the threshold setting change.

    A plain function, not the endpoint: calling an endpoint from Python hands
    its `Query` defaults through as objects rather than values.
    """
    # A face somebody has ANSWERED: any appearance whose subject has a tag,
    # a display name — or the UNNAMED mark, which is the other answer ("a
    # background character"). The complement of what this queue is for: the
    # clusters nobody has said anything about yet.
    named_claim = (
        select(ItemSubject.id)
        .join(Subject, Subject.id == ItemSubject.subject_id)
        .where(ItemSubject.face_id == Face.id,
               (Subject.tag_id.is_not(None)) | (Subject.display_name != "")
               | (Subject.unnamed.is_(True)))
    ).exists()
    meta = s.execute(
        select(Face.id, Face.w, Face.h)
        .where(Face.dismissed.is_(False), ~named_claim)
    ).all()
    ids = [fid for fid, _w, _h in meta]
    who = appearances_of(s, ids)

    # Remaining appearances all point at nameless subjects (the SQL above took
    # out everything else); the first one is the hand-merged cluster's holder.
    merged: dict[int, list[int]] = {}
    loose: list[int] = []
    for fid in ids:
        subs = [r.subject_id for r in who.get(fid, [])]
        if subs:
            merged.setdefault(subs[0], []).append(fid)
        else:
            loose.append(fid)

    from media_compost.prefs import read_face_match_threshold

    threshold = read_face_match_threshold(s)
    if cache is not None:
        groups = cache.unnamed_clusters(s, loose, threshold)
    else:
        groups = cluster_spaces_fast(
            loose, facelib.embeddings_of(s, loose), threshold)

    # The cluster list, cut to `limit` BEFORE any Face row is hydrated.
    ordered: list[tuple[list[int], bool, Optional[int]]] = []
    for sub_id, members in sorted(merged.items(), key=lambda kv: -len(kv[1])):
        ordered.append((members, True, sub_id))
    for group in groups:
        ordered.append((group, len(group) > 1, None))
    return ordered[:limit], who


def _unnamed(s: Session, limit: int, cache=None) -> list[FaceCluster]:
    """`_unnamed_groups`, hydrated: the queue as the page draws it."""
    ordered, who = _unnamed_groups(s, limit, cache)
    by_id: dict[int, Face] = {}
    for chunk in chunked([fid for members, _g, _s in ordered
                          for fid in members]):
        for f in s.execute(select(Face).where(Face.id.in_(chunk))
                           ).scalars().all():
            by_id[f.id] = f
    guessed = {fid for fid, rows in who.items()
               if any(r.assigned_by == "suggested" for r in rows)}
    return [
        FaceCluster(
            faces=_rows(s, sorted((by_id[i] for i in members),
                                  key=lambda f: -(f.w * f.h))),
            total=len(members), grouped=grouped, subject_id=sub_id,
            # No slice here — a cluster of this queue carries every face it
            # has — but the field means the same thing on both lists.
            guesses=sum(1 for i in members if i in guessed),
        )
        for members, grouped, sub_id in ordered
    ]


@router.get("/subject/{subject_id}", response_model=list[FaceOut])
def subject_faces(subject_id: int, s: Session = Depends(get_session)):
    """Every face one subject appears at — the editor's face strip.

    Seeing them together is how a wrong one is caught: a face that does not
    belong is obvious next to twenty that do, and much less obvious one
    picture at a time.
    """
    ids = [
        fid for fid, in s.execute(
            select(ItemSubject.face_id)
            .where(ItemSubject.subject_id == subject_id,
                   ItemSubject.face_id.is_not(None))
        ).all()
    ]
    # Dismissed ones stay out, exactly as in `/named`: the drawer opens the
    # WHOLE of what the strip was showing a row of, and a face somebody said
    # was not one appearing only there would read as the drawer finding faces
    # the list had not.
    rows: list[Face] = []
    for chunk in chunked(ids):
        rows.extend(s.execute(
            select(Face).where(Face.id.in_(chunk), Face.dismissed.is_(False))
        ).scalars().all())
    return _rows(s, sorted(rows, key=lambda f: -(f.w * f.h)))


@router.get("/named", response_model=None)
def named_faces(limit: int = Query(default=200, le=1000),
                per: int = Query(default=0, ge=0, le=1000),
                offset: int | None = Query(default=None, ge=0),
                s: Session = Depends(get_session)):
    """Every face somebody has named, one cluster per subject.

    The counterpart of the unnamed list: the same view, from the other end.
    Seeing all of somebody's faces together is how a wrong one is caught —
    obvious next to twenty that belong, invisible one picture at a time.

    A face named twice over appears in BOTH people's clusters: under the
    character, where it reads beside the other actors who played them, and
    under the actor, where it reads beside the other parts they played.
    Neither view is complete without it, and it is one face either way — so the
    caller counts distinct ids rather than summing the clusters.

    A subject nobody has ANSWERED (a hand-merged or split-off cluster with no
    name and no unnamed mark) is skipped: those faces are what the UNKNOWN
    list is made of, and counting them in both halves made the header say the
    library had gained faces every time somebody sorted one. One that carries
    the UNNAMED mark is here, though — it has been answered, and the answer
    is that this person has no name.

    ``per`` caps how many faces each cluster carries (0 = all). The list shows
    ONE ROW per person, so somebody in three hundred pictures was three hundred
    crop URLs the page would never render; each cluster still reports its real
    ``total``, and the drawer asks for the whole set of the one subject it
    opens (``/faces/subject/{id}``).
    """
    # WHICH PEOPLE, AND HOW MANY EACH — in SQL. This used to load every
    # named face in the library as an ORM row before deciding which fifty
    # people to show: measured at 200,000 named faces, 1.22 s of a 1.70 s
    # request spent hydrating rows the page would never mention. The counts
    # and the ordering are one grouped pass (0.08 s), and only the page's own
    # crops are hydrated after it.
    #
    # A NAMED subject is one with a tag or a display name — the complement of
    # `_nameless_subject_ids`, said in SQL the way `_unnamed` says it, so the
    # two halves of this view cannot disagree about which faces they are for.
    # AN ANSWERED IDENTITY: one with a tag, a display name — or the UNNAMED
    # mark, which is an answer with no name in it. The same clause `_unnamed`
    # takes the complement of, so the two halves of this view cannot disagree
    # about which faces they are for.
    named = ((Subject.tag_id.is_not(None)) | (Subject.display_name != "")
             | (Subject.unnamed.is_(True)))
    per_subject = s.execute(
        select(ItemSubject.subject_id,
               func.count(func.distinct(ItemSubject.face_id)))
        .join(Face, Face.id == ItemSubject.face_id)
        .join(Subject, Subject.id == ItemSubject.subject_id)
        .where(Face.dismissed.is_(False), named)
        .group_by(ItemSubject.subject_id)
    ).all()
    # Biggest cluster first, and by subject id under a tie so the order is
    # the same answer twice running.
    per_subject.sort(key=lambda r: (-int(r[1]), int(r[0])))
    start = offset or 0
    cut = per_subject[start:start + limit]

    # The page's faces, biggest first — `per` cuts each cluster, so what is
    # hydrated is at most `limit * per` crops rather than the library's.
    shown_all: list[Face] = []
    spans: list[tuple[int, int, int]] = []  # (subject, real total, sent)
    for sub_id, total in cut:
        rows = s.execute(
            select(Face)
            .join(ItemSubject, ItemSubject.face_id == Face.id)
            .where(ItemSubject.subject_id == sub_id,
                   Face.dismissed.is_(False))
            .order_by((Face.w * Face.h).desc())
        ).scalars().unique().all()
        shown = list(rows[:per]) if per else list(rows)
        spans.append((int(sub_id), int(total), len(shown)))
        shown_all.extend(shown)
    hydrated = _rows(s, shown_all)
    # HOW MANY OF EACH PERSON'S FACES ARE STILL A GUESS, over the whole
    # cluster rather than over the slice that was hydrated: the card says the
    # number, and a cluster whose guesses all sit past `per` would otherwise
    # have said it had none. One grouped pass, the shape the counts above take.
    guess_counts = {
        int(sub): int(n) for sub, n in s.execute(
            select(ItemSubject.subject_id,
                   func.count(func.distinct(ItemSubject.face_id)))
            .join(Face, Face.id == ItemSubject.face_id)
            .join(Subject, Subject.id == ItemSubject.subject_id)
            .where(Face.dismissed.is_(False), named,
                   ItemSubject.assigned_by == "suggested")
            .group_by(ItemSubject.subject_id)
        ).all()
    }
    out: list[FaceCluster] = []
    at = 0
    for sub_id, total, sent in spans:
        out.append(FaceCluster(
            faces=hydrated[at:at + sent],
            total=total, grouped=True, subject_id=sub_id,
            guesses=guess_counts.get(sub_id, 0),
        ))
        at += sent
    # Counted over every named face, not over what was returned: a face
    # credited to a character AND to its actor is in both clusters and is
    # still ONE face, so this is a distinct count rather than a sum.
    named_faces = int(s.execute(
        select(func.count(func.distinct(ItemSubject.face_id)))
        .join(Face, Face.id == ItemSubject.face_id)
        .join(Subject, Subject.id == ItemSubject.subject_id)
        .where(Face.dismissed.is_(False), named)
    ).scalar_one())
    if offset is None:
        return NamedFaces(clusters=out, faces=named_faces)
    # Pre-dumped: FastAPI's `jsonable_encoder` walks every field of every
    # model in Python — measured as 0.9 s of a 3000-person page against
    # ~0.1 s for pydantic's own dump plus one json.dumps.
    from fastapi.responses import JSONResponse

    return JSONResponse({"clusters": [c.model_dump() for c in out],
                         "faces": named_faces,
                         "total": len(per_subject)})


@router.get("/unnamed", response_model=list[FaceCluster])
def unnamed_faces(limit: int = Query(default=40, le=200),
                  s: Session = Depends(get_session),
                  lib=Depends(get_library)):
    return _unnamed(s, limit, cache=lib.face_cache)


@router.post("", response_model=list[FaceOut])
def create_face(body: FaceCreate, ctx: Ctx = Depends(get_ctx)):
    """A face drawn by hand — no detector, so no score and no descriptor."""
    face = ops_faces.create_face(ctx, body.item_id, body.x, body.y, body.w,
                                 body.h, subject_id=body.subject_id)
    return _rows(ctx.session, _faces_of(ctx.session, face.item_id))


@router.patch("/{face_id}", response_model=list[FaceOut])
def update_face(face_id: int, body: FaceUpdate, ctx: Ctx = Depends(get_ctx)):
    """Dismiss a face, or move its box. Who it is goes through `/subject`."""
    face = ops_faces.update_face(ctx, face_id, dismissed=body.dismissed,
                                 x=body.x, y=body.y, w=body.w, h=body.h)
    return _rows(ctx.session, _faces_of(ctx.session, face.item_id))


@router.post("/{face_id}/reset-box", response_model=list[FaceOut])
def reset_face_box(face_id: int, ctx: Ctx = Depends(get_ctx)):
    """Put the detector's rectangle back and forget the hand edit."""
    face = ops_faces.reset_face_box(ctx, face_id)
    s = ctx.session
    return _rows(s, _faces_of(s, face.item_id))


@router.put("/{face_id}/outline", response_model=list[FaceOut])
def set_face_outline(face_id: int, body: FaceOutlineSet,
                     ctx: Ctx = Depends(get_ctx)):
    """Draw (or replace) the face's outline — the whole figure."""
    face = ops_faces.set_face_outline(
        ctx, face_id, x=body.x, y=body.y, w=body.w, h=body.h,
        points=body.points)
    return _rows(ctx.session, _faces_of(ctx.session, face.item_id))


@router.delete("/{face_id}/outline", response_model=list[FaceOut])
def clear_face_outline(face_id: int, ctx: Ctx = Depends(get_ctx)):
    """Take the face's outline down."""
    face = ops_faces.set_face_outline(ctx, face_id, clear=True)
    return _rows(ctx.session, _faces_of(ctx.session, face.item_id))


@router.post("/{face_id}/subject", response_model=list[FaceOut])
def name_face(face_id: int, body: FaceSubjectIn, ctx: Ctx = Depends(get_ctx)):
    """Say who a face is — ADDING a claim, not replacing one.

    A hand-naming also runs the ordinary suggestion pass over the unnamed
    faces that look like this one (`jobs.suggest_around_faces`): the answer
    just given is exactly what the clusters were waiting to be told, and
    without this it reached them only on the next detection run. Here in the
    ROUTER, not the op: the matcher is the app's (`ui.facevec`), which core
    ops may not import — and a suggestion is an app behaviour, like the
    detection pass that shares the code."""
    face = ops_faces.name_face(ctx, face_id, subject_id=body.subject_id,
                               display_name=body.display_name,
                               comment=body.comment)
    suggest_around_faces(ctx.session, [face.id])
    return _rows(ctx.session, _faces_of(ctx.session, face.item_id))


@router.delete("/{face_id}/subject/{subject_id}", response_model=list[FaceOut])
def unname_face(face_id: int, subject_id: int, ctx: Ctx = Depends(get_ctx)):
    """Take one name off a face. The face stays — it is evidence."""
    face = ops_faces.unname_face(ctx, face_id, subject_id)
    return _rows(ctx.session, _faces_of(ctx.session, face.item_id))


@router.post("/name-cluster", response_model=list[FaceCluster])
def name_cluster(body: NameCluster, ctx: Ctx = Depends(get_ctx),
                 lib=Depends(get_library)):
    """Name every face in a cluster at once — the point of the unnamed view.

    Also a hand-naming, so the same propagation as `name_face`: the pool is
    matched against EVERY face just named — they clustered together, but each
    carries its own descriptor and their unions differ at the margins."""
    sub = ops_faces.name_cluster(ctx, body.face_ids, subject_id=body.subject_id,
                                 display_name=body.display_name,
                                 comment=body.comment, replace=body.replace)
    # ONLY A NAME PROPAGATES. Crops put on a NAMELESS holder — the ✚ on an
    # offer, a carry onto an unanswered cluster — are a merge that has not
    # said who anybody is, so there is no answer to offer the lookalikes,
    # and the pass over the whole unnamed pool was a third of what such an
    # add cost (2026-09).
    if sub.tag_id is not None or sub.display_name:
        suggest_around_faces(ctx.session, body.face_ids)
    # THE PAGE'S OWN QUEUE, at the page's own size (200, what `unnamedFaces`
    # asks for): the client puts this answer straight into its cache rather
    # than asking for the same clustering again a round trip later.
    return _unnamed(ctx.session, 200, cache=lib.face_cache)


@router.post("/merge-clusters", response_model=list[FaceCluster])
def merge_clusters(body: NameCluster, ctx: Ctx = Depends(get_ctx),
                   lib=Depends(get_library)):
    """Fold several unnamed clusters into one, still unnamed."""
    ops_faces.merge_clusters(ctx, body.face_ids)
    return _unnamed(ctx.session, 200, cache=lib.face_cache)


def _cannot_link(s: Session) -> set[tuple[int, int]]:
    """The pairs of identities somebody has said are NOT one person."""
    from media_compost.db import SubjectCannotLink

    return {(int(a), int(b)) for a, b in s.execute(
        select(SubjectCannotLink.a_subject_id,
               SubjectCannotLink.b_subject_id)).all()}


#: How many of a cluster's faces the strip reads. A cluster's own look is
#: what its crops say together, and forty of them say it.
MAX_CLUSTER_FACES = 40


def _open_and_candidates(s: Session, subject: Optional[int], faces: str,
                         cache=None
                         ) -> tuple[list[int],
                                    list[tuple[Optional[int], list[int],
                                               str, bool, bool]]]:
    """The open cluster's face ids, and the clusters it may be compared with.

    Shared by the two things the strip has been: a row of CLUSTERS and a row
    of FACES. Which candidates there are is the same question either way —
    the answered identities from the subjects table, the unanswered ones from
    the queue's own clusters (which is what bounds this to the page rather
    than to the library), less anything a person has already ruled out.

    Each row is `(subject id, face ids, name, unnamed, whole)`: `whole` says
    the candidate is offered AS ONE — the unanswered queue's clusters and the
    "somebody with no name" ones — where a named person's crops are offered
    one by one.
    """
    ids = [int(x) for x in faces.replace(",", " ").split() if x.strip().isdigit()]
    if subject is not None:
        ids = [fid for fid, in s.execute(
            select(ItemSubject.face_id)
            .where(ItemSubject.subject_id == subject,
                   ItemSubject.face_id.is_not(None))).all()]
    ids = list(dict.fromkeys(ids))[:MAX_CLUSTER_FACES]
    if not ids:
        return [], []

    # WHAT THE OPEN CLUSTER IS, and which identities it already answers to.
    mine: set[int] = {r.subject_id for fid in ids
                      for r in appearances_of(s, ids).get(fid, [])}
    named_here = False
    for sid in mine:
        sub = s.get(Subject, sid)
        if sub is not None and (sub.tag_id is not None or sub.display_name):
            named_here = True

    # THE CANDIDATES. The answered identities come from the subjects table;
    # the unanswered ones are the queue's own clusters, which is what bounds
    # this to the page rather than to the library.
    unknown, _who = _unnamed_groups(s, 200, cache=cache)
    rows: list[tuple[Optional[int], list[int], str, bool, bool]] = []
    if not named_here:
        for sub in s.execute(select(Subject)).scalars().all():
            if sub.id in mine:
                continue
            if not (sub.tag_id is not None or sub.display_name):
                continue
            got = [fid for fid, in s.execute(
                select(ItemSubject.face_id)
                .where(ItemSubject.subject_id == sub.id,
                       ItemSubject.face_id.is_not(None))).all()]
            if got:
                tag = s.get(Tag, sub.tag_id) if sub.tag_id else None
                rows.append((sub.id, got[:MAX_CLUSTER_FACES],
                             sub.display_name or (tag.name if tag else ""),
                             False, False))
    open_set = set(ids)
    for got, _grouped, sub_id in unknown:
        if not got or open_set & set(got):
            continue
        if sub_id is not None and sub_id in mine:
            continue
        rows.append((sub_id, got, "", False, True))
    # …and the ones answered "somebody with no name", which are neither.
    for sub in s.execute(select(Subject).where(
            Subject.unnamed.is_(True))).scalars().all():
        if sub.id in mine:
            continue
        got = [fid for fid, in s.execute(
            select(ItemSubject.face_id)
            .where(ItemSubject.subject_id == sub.id,
                   ItemSubject.face_id.is_not(None))).all()]
        if got:
            rows.append((sub.id, got, "", True, True))

    # NOT THIS PERSON, said before: a pair somebody has ruled out stays out.
    denied = _cannot_link(s)
    rows = [r for r in rows
            if r[0] is None
            or not any(tuple(sorted((r[0], m))) in denied for m in mine)]

    return ids, rows


def _similar_faces(s: Session, *, subject: Optional[int] = None,
                   faces: str = "", limit: int = 12,
                   cache=None) -> list[SimilarFace]:
    """THE CROPS MOST LIKE THE OPEN CLUSTER, one by one.

    The strip beside an open cluster used to offer CLUSTERS — a cover crop
    standing for forty others, and a score about the two groups. The question
    being asked of it is "is this crop one of these?", which a cover crop
    cannot answer: the one that looks alike may be the one crop of that
    cluster that does. So the candidates are FACES, each scored against the
    open cluster on its own (the mean of its similarity to every crop there,
    per shared space, best space deciding — `pair_likeness`' rule for a group
    of one).

    AN UNANSWERED CLUSTER IS ONE OFFER (owner 2026-09): the queue's clusters
    and the "somebody with no name" ones are scored WHOLE — the mean of
    every cross pair, the clustering's own rule — and offered as one card
    carrying every crop, so the row says "this cluster of twelve might be
    them" once rather than twelve times. A cluster of one is simply a face.
    A NAMED person's crops stay one by one: they are answered, and the
    question about them is which of them is wrong.

    The candidates are the clusters' own (`_open_and_candidates`), so what is
    bounded is unchanged: the page's named identities plus the queue's 200,
    less whatever has been ruled out.
    """
    ids, rows = _open_and_candidates(s, subject, faces, cache)
    if not ids:
        return []
    # Every candidate as `(subject id, name, unnamed, member ids)`: a named
    # person's row splits into one entry per crop, a whole one stays one.
    offers: list[tuple[Optional[int], str, bool, list[int]]] = []
    seen: set[int] = set()
    for sub_id, face_ids, name, unnamed, whole in rows:
        fresh = [fid for fid in face_ids if fid not in seen]
        seen.update(fresh)
        if not fresh:
            continue
        if whole:
            offers.append((sub_id, name, unnamed, fresh))
        else:
            offers.extend((sub_id, name, unnamed, [fid]) for fid in fresh)
    wanted = list(dict.fromkeys(
        ids + [fid for _s, _n, _u, members in offers
               for fid in members[:MAX_CLUSTER_FACES]]))
    vectors = facelib.embeddings_of(s, wanted)
    here = group_matrices(vectors, ids)
    scored: list[tuple[float, int, int]] = []
    for i, (_sub, _name, _un, members) in enumerate(offers):
        got = pair_likeness(
            group_matrices(vectors, members[:MAX_CLUSTER_FACES]), here)
        if got is not None:
            scored.append((got, min(members), i))
    scored.sort(key=lambda r: (-r[0], r[1]))
    keep = scored[:limit]
    hydrated: dict[int, FaceOut] = {}
    for chunk in chunked([fid for _s, _c, i in keep for fid in offers[i][3]]):
        for row in _rows(s, s.execute(select(Face).where(Face.id.in_(chunk)))
                         .scalars().all()):
            hydrated[row.id] = row
    out: list[SimilarFace] = []
    for score, _cover, i in keep:
        sub_id, name, unnamed, members = offers[i]
        # BIGGEST FIRST, the queue's own order, so the cover is the crop
        # that says most about who this is.
        crops = sorted((hydrated[f] for f in members if f in hydrated),
                       key=lambda f: -(f.w * f.h))
        if not crops:
            continue
        out.append(SimilarFace(face=crops[0], faces=crops, count=len(crops),
                               score=round(score, 4), subject_id=sub_id,
                               name=name, unnamed=unnamed))
    return out


#: HOW MANY TAGS THE CAPSULE BAR MAY OFFER, and how few crops a tag may be
#  on and still be offered. A tag on ONE crop makes a group of one, which is
#  not a grouping; and a booru-tagged library puts tens of tags on a picture,
#  so a four-hundred-picture cluster would otherwise answer with a thousand
#  capsules of which most group nothing.
_GROUP_TAGS_MAX = 150
_GROUP_TAG_MIN_FACES = 2

#: The crops one answer may be about. A cluster is hundreds; this is the
#  ceiling that keeps a hand-written body from asking for the library.
_GROUP_FACES_MAX = 5000


@router.post("/grouping", response_model=FaceGroupingOut)
def face_grouping(body: FaceGrouping, s: Session = Depends(get_session)):
    """WHAT THE OPEN CLUSTER'S PICTURES SAY, so the grid can group its crops.

    Two facts per crop, in one request because they are one question — how
    should these be laid out: the SEQUENCE its picture belongs to, and the
    TAGS on that picture.

    The tags are EFFECTIVE (`resolve.effective_for_items`), so a picture
    tagged `grin` lands in the `smile` group where a tag set says one entails
    the other — which is what somebody means by "group by expression". The
    capsule's own count is over the same set, so the number on it is the size
    of the group it makes.
    """
    ids = list(dict.fromkeys(body.face_ids))[:_GROUP_FACES_MAX]
    if not ids:
        return FaceGroupingOut()
    of_item: dict[int, int] = {}
    for chunk in chunked(ids):
        for fid, iid in s.execute(
            select(Face.id, Face.item_id).where(Face.id.in_(chunk))
        ).all():
            of_item[fid] = iid
    ids = [f for f in ids if f in of_item]
    items = list(dict.fromkeys(of_item.values()))

    # WHICH SEQUENCE — the item's MAIN one, the same the grid's page badge
    # counts in. An item may sit in several; which of them a picture "is a
    # page of" is a question the library already answers, and answering it a
    # second way here would be a second answer.
    seq_of: dict[int, str] = {}
    for chunk in chunked(items):
        for iid, name in s.execute(
            select(Item.id, Sequence.name)
            .join(Sequence, Sequence.id == Item.main_sequence_id)
            .where(Item.id.in_(chunk))
        ).all():
            seq_of[iid] = name or ""

    eff = resolve.effective_for_items(s, items)
    # COUNTED IN CROPS, NOT PICTURES: the grid draws a card per crop, so two
    # faces in one tagged picture are two cards in that tag's group, and a
    # capsule saying "1" over a group of two would be the wrong number.
    counts: dict[str, int] = {}
    for fid in ids:
        for name in eff.get(of_item[fid], resolve.EffectiveTags()).positive:
            counts[name] = counts.get(name, 0) + 1
    # …AND A TAG ON EVERY CROP GROUPS NOTHING EITHER. It makes one section
    # holding the lot and an empty catch-all, which is the ungrouped grid
    # with a heading on it. The cluster's OWN subject tag is always such a
    # tag — naming a cluster is what puts it on every picture the crops sit
    # on — so it would otherwise lead the bar, being the most frequent tag
    # there is, and be the one thing on it that cannot do anything.
    keep = sorted(
        ((n, k) for n, k in counts.items()
         if _GROUP_TAG_MIN_FACES <= k < len(ids)),
        # Most crops first, then by name so equal counts have a fixed order
        # rather than the dict's.
        key=lambda kv: (-kv[1], kv[0]),
    )[:_GROUP_TAGS_MAX]
    index = {n: i for i, (n, _) in enumerate(keep)}
    return FaceGroupingOut(
        face_ids=ids,
        sequences=[seq_of.get(of_item[f], "") for f in ids],
        tag_names=[n for n, _ in keep],
        tag_faces=[k for _, k in keep],
        tags=[sorted(index[n]
                     for n in eff.get(of_item[f], resolve.EffectiveTags()).positive
                     if n in index)
              for f in ids],
    )


@router.get("/similar-faces", response_model=list[SimilarFace])
def similar_faces(subject: Optional[int] = None, faces: str = "",
                  limit: int = Query(default=12, ge=1, le=60),
                  s: Session = Depends(get_session),
                  lib=Depends(get_library)):
    """`_similar_faces`, as an endpoint — a plain function beside it for the
    `Query`-defaults reason `_unnamed` has."""
    return _similar_faces(s, subject=subject, faces=faces, limit=limit,
                          cache=lib.face_cache)


@router.post("/not-matching", response_model=list[SimilarFace])
def clusters_differ(body: ClustersDiffer, ctx: Ctx = Depends(get_ctx),
                    lib=Depends(get_library)):
    """"NOT THIS PERSON", said of the crops on either side — the row's ✕.

    It takes them out of the strip for good rather than until the next fetch,
    so the next one back-fills something else; the statement is
    `SubjectCannotLink`, which is what a split already writes, and saying it
    of a single crop holds that crop on its own (an identity per side is what
    the statement needs).

    Answers the strip as it now is, in the strip's own currency: CROPS.
    Several offers at once travel as `other_clusters`, each held on its own.
    """
    others = ([body.other_face_ids] if body.other_face_ids else []) \
        + [c for c in body.other_clusters if c]
    if not others:
        raise Invalid("pick two different clusters",
                      code="not_matching_same_cluster")
    for other in others:
        ops_faces.declare_clusters_different(ctx, body.face_ids, other)
    return _similar_faces(ctx.session,
                          faces=",".join(str(i) for i in body.face_ids),
                          cache=lib.face_cache)


@router.post("/odd-ones-out", response_model=list[int])
def odd_ones(body: OddOnesOut, s: Session = Depends(get_session)):
    """The crops a correction leaves behind.

    Somebody has just said that some of a cluster's faces are somebody else,
    and whatever was only in that cluster BECAUSE of them is still in it. This
    answers which — each remaining crop scored against the two sides by the
    rule any two groups are scored with — so the page can offer them together
    rather than leaving them to be found one at a time.

    A READ: it writes nothing and decides nothing, and the row it fills is an
    offer.
    """
    ids = [i for i in body.face_ids if i not in set(body.unlike)]
    if not ids or not body.unlike:
        return []
    vectors = facelib.embeddings_of(s, ids + list(body.unlike))
    return odd_ones_out(vectors, ids, body.unlike)


@router.post("/unnamed-cluster", response_model=list[FaceCluster])
def set_cluster_unnamed(body: ClusterUnnamed, ctx: Ctx = Depends(get_ctx),
                        lib=Depends(get_library)):
    """SOMEBODY WITH NO NAME — a background character — or the way back.

    The other answer to "who is this": it takes the cluster out of the
    UNKNOWN queue without inventing a name for it. Answers the queue as it
    now is, the way naming and merging do.
    """
    ops_faces.set_cluster_unnamed(ctx, body.face_ids, on=body.unnamed)
    return _unnamed(ctx.session, 200, cache=lib.face_cache)


@router.post("/split", response_model=list[FaceCluster])
def split_faces(body: NameCluster, ctx: Ctx = Depends(get_ctx),
                lib=Depends(get_library)):
    """Pull faces off whoever they are on, onto a NEW person with no name."""
    ops_faces.split_faces(ctx, body.face_ids)
    return _unnamed(ctx.session, 200, cache=lib.face_cache)


@router.delete("/{face_id}", response_model=list[FaceOut])
def delete_face(face_id: int, ctx: Ctx = Depends(get_ctx)):
    """Remove a face outright. Prefer dismissing a false positive."""
    item_id = ops_faces.delete_face(ctx, face_id)
    return _rows(ctx.session, _faces_of(ctx.session, item_id))


@router.get("/{face_id}/crop")
def face_crop(face_id: int, w: int = Query(default=96, ge=16, le=512),
              at: str = Query(default=""),
              s: Session = Depends(get_session),
              lib=Depends(get_library)):
    """The face as a small square-ish JPEG, cached beside the item's files.

    Cached because the sidebar and the clustering view ask for dozens at a
    time, and each one otherwise decodes a full-resolution page.

    `at` is the caller's copy of the box and is never read: a face id is a
    rowid, so it is handed to a different picture as soon as the row it named
    is deleted, and a day-long cache would then serve the old face under the
    new id. Putting the box in the URL makes the two different requests.
    """
    del at
    from PIL import Image

    face = s.get(Face, face_id)
    if face is None:
        raise HTTPException(404, "face not found")
    item = s.get(Item, face.item_id)
    file_id = face.file_id or (item.active_file_id if item else None)
    if item is None or file_id is None:
        raise HTTPException(404, "no image for this face")
    from media_compost.db import File

    row = s.get(File, file_id)
    if row is None:
        raise HTTPException(404, "no image for this face")
    path = lib.store.path_of(s, row)

    store: ItemStore = lib.store
    cache = store.item_dir(item.uid) / "thumbs"
    cache.mkdir(parents=True, exist_ok=True)
    # The box is part of the key: moving a face by hand must not serve the old
    # crop back.
    stamp = f"{face.x:.4f}-{face.y:.4f}-{face.w:.4f}-{face.h:.4f}"
    cached = cache / f"face-{face.id}-{stamp}-{w}.jpg"
    if not cached.exists():
        with Image.open(path) as im:
            im = im.convert("RGB")
            crop = im.crop(facelib.crop_box((face.x, face.y, face.w, face.h),
                                            im.width, im.height))
            crop.thumbnail((w, w))
            buf = io.BytesIO()
            crop.save(buf, "JPEG", quality=88)
            cached.write_bytes(buf.getvalue())
    return Response(cached.read_bytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})
