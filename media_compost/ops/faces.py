"""Faces: the crops a detector found (or a hand drew), and who they are.

A face is **evidence, not an edit**. It keeps its box, its score and its
descriptor forever, named or not, and a re-run never loses work — the
reconciliation rule lives in the core :mod:`media_compost.faces` module, which
is pure and knows nothing about a session. This module is the writing half:
naming, unnaming, moving, dismissing, deleting, and the two cluster operations.

Three asymmetries here are the whole model and none is guessable:

* **Naming ADDS, the cluster actions MOVE.** A face may be two people at once
  (a character and the actor playing them), so `name_face` appends a claim.
  `name_cluster` replaces, because that is what dropping crops on somebody's
  row means, and `split` takes every claim off, because being in the wrong
  cluster is what a split fixes.
* **A correction is REMEMBERED, a change of mind is not.** Taking off a name
  the machine guessed writes a `FaceRejection` so the next run does not offer
  it again; taking off a name somebody typed says they changed their mind.
* **An age travels with the face, not with the name.** A face said to be
  twelve stays twelve whoever it turns out to be.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from .. import faces as facelib
from ..db import (
    Face, FaceBoxEdit, FaceOutline, Item, ItemSubject, ItemTag, Subject,
    chunked,
    touch_items,
)
from . import actions, naming, subjects as ops_subjects, tagcatalog
from .context import Ctx
from .errors import Invalid, NotFound

# ---- reads the writers need -------------------------------------------------


def appearances_of(session, face_ids: list[int]) -> dict[int, list[ItemSubject]]:
    """``{face_id: [appearance, ...]}`` — who each face has been said to be.

    Chunked: the unnamed view asks about every face in the library at once,
    and SQLite caps bind parameters per statement.

    Takes a Session rather than a `Ctx` — it is a pure read, and the router's
    list-building calls it without one.
    """
    out: dict[int, list[ItemSubject]] = {}
    if not face_ids:
        return out
    for chunk in chunked(face_ids):
        for row in session.execute(
            select(ItemSubject).where(ItemSubject.face_id.in_(chunk))
        ).scalars().all():
            out.setdefault(row.face_id, []).append(row)
    # The sidebar's own order, so the chip's "first claim" follows a
    # drag-reorder rather than the rowids.
    for rows in out.values():
        rows.sort(key=lambda r: (r.position, r.id))
    return out


def faces_of(ctx: Ctx, item_id: int) -> list[Face]:
    return list(ctx.session.execute(
        select(Face).where(Face.item_id == item_id).order_by(Face.id)
    ).scalars().all())


def nameless_subject_ids(session) -> set[int]:
    """Identities with neither a tag nor a name — what a merged cluster is
    held together by.

    Takes a Session, like `appearances_of`: the unnamed-cluster VIEW needs it
    as much as the writers do.
    """
    return set(session.execute(
        select(Subject.id).where(Subject.tag_id.is_(None),
                                 Subject.display_name == "")
    ).scalars().all())


def label(ctx: Ctx, subject: Optional[Subject]) -> str:
    if subject is None:
        return "somebody"
    return subject.display_name or f"unnamed subject #{subject.id}"


def snapshot(ctx: Ctx, face_ids: list[int]) -> list[dict]:
    """Every appearance on these faces, as plain data — what a revert needs.

    An assignment is more than its subject id: a guess restored as an answer
    would be immune to the next run that disagrees with it, and an age typed by
    hand would be lost. The row's own id travels too, so a restore can put it
    back under the identity the other revert handlers look it up by (see
    `history._restore_appearance`).
    """
    out = []
    for face_id, rows in appearances_of(ctx.session, face_ids).items():
        for r in rows:
            out.append({"face_id": face_id, "item_id": r.item_id,
                        "subject_id": r.subject_id,
                        "appearance_id": r.id,
                        "when_date": r.when_date, "when_age": r.when_age,
                        "assigned_by": r.assigned_by or "user",
                        "match_score": r.match_score})
    return out


# ---- the tag a face's name puts on the picture ------------------------------


def assign_subject_tag(ctx: Ctx, item_id: int, subject: Subject) -> bool:
    """Put the subject's identity tag on the item. Returns whether it was new.

    A subject with no tag (an unnamed cluster) assigns nothing — there is
    nothing to assign, and that is exactly why naming it later back-fills.

    A tag a detector put there PENDING is confirmed rather than duplicated:
    saying who the face is BY HAND is the review the flag was waiting for.
    """
    s = ctx.session
    if subject.tag_id is None:
        return False
    exists = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == subject.tag_id
    )).scalars().first()
    if exists is not None:
        if exists.pending:
            exists.pending = False
            s.flush()
            touch_items(s, [item_id])
        return False
    s.add(ItemTag(item_id=item_id, tag_id=subject.tag_id, negative=False))
    s.flush()
    touch_items(s, [item_id])
    return True


def drop_unconfirmed_tag(ctx: Ctx, item_id: int, subject_id: Optional[int],
                         *, ignore: Optional[int] = None) -> bool:
    """Take back the PENDING tag a detector's guess put on this item.

    Only pending: a tag somebody has agreed to is theirs now, whatever the face
    it came in with turns out to be. And only when no other appearance on the
    item still claims that person — two detections of one person leave one tag,
    so the last one out takes it.
    """
    s = ctx.session
    subject = s.get(Subject, subject_id) if subject_id else None
    if subject is None or subject.tag_id is None:
        return False
    q = select(ItemSubject).where(ItemSubject.item_id == item_id,
                                  ItemSubject.subject_id == subject.id)
    if ignore is not None:
        q = q.where(ItemSubject.id != ignore)
    if s.execute(q).scalars().first() is not None:
        return False
    row = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == subject.tag_id,
        ItemTag.pending.is_(True),
    )).scalars().first()
    if row is None:
        return False
    s.delete(row)
    s.flush()
    touch_items(s, [item_id])
    return True


def appear(ctx: Ctx, item_id: int, subject: Subject, face_id: Optional[int],
           *, by: str = "user", score: Optional[float] = None) -> ItemSubject:
    """Say that a subject is in an item, once — at a face, or at none.

    Idempotent per (item, subject, FACE): saying twice that one crop is Alice
    is one appearance, and a second row would show her twice under one picture
    of her. An existing GUESS is upgraded to the answer being made; an answer
    is never downgraded by a guess.

    With NO face it always adds, because that is how "she is in this picture
    twice" is said at all — a page holding one character at two ages has two
    of these and one tag.
    """
    s = ctx.session
    row = None if face_id is None else s.execute(select(ItemSubject).where(
        ItemSubject.item_id == item_id,
        ItemSubject.subject_id == subject.id,
        ItemSubject.face_id == face_id,
    )).scalars().first()
    if row is None:
        row = ItemSubject(item_id=item_id, subject_id=subject.id,
                          face_id=face_id, assigned_by=by, match_score=score)
        s.add(row)
    elif by == "user":
        row.assigned_by, row.match_score = "user", None
    s.flush()
    assign_subject_tag(ctx, item_id, subject)
    touch_items(s, [item_id])
    return row


def _mint_subject(ctx: Ctx, display_name: str, comment: str = "") -> Subject:
    """A brand-new named identity, with its tag."""
    s = ctx.session
    subject = Subject(display_name=display_name.strip())
    s.add(subject)
    s.flush()
    ops_subjects.mint_tag(
        ctx, subject,
        naming.free_slug(s, naming.prefixed(s, "subject", display_name)))
    # The one-liner rides on the TAG (`tagcatalog.describe`), which the mint
    # above has just given this subject.
    tagcatalog.describe(ctx, subject.tag_id, comment=comment.strip() or None)
    return subject


# ---- one face ---------------------------------------------------------------


def create_face(ctx: Ctx, item_id: int, x: float, y: float, w: float, h: float,
                *, subject_id: Optional[int] = None) -> Face:
    """A face drawn by hand — no detector, so no score and no descriptor."""
    s = ctx.session
    item = s.get(Item, item_id)
    if item is None:
        raise NotFound("item not found", code="item_not_found")
    face = Face(item_id=item.id, file_id=item.active_file_id,
                x=x, y=y, w=w, h=h)
    s.add(face)
    s.flush()
    if subject_id:
        subject = s.get(Subject, subject_id)
        if subject is None:
            raise NotFound("subject not found", code="subject_not_found")
        appear(ctx, item.id, subject, face.id)
    ctx.log(action=actions.ADD_FACE, entity_type="item", entity_id=item.id,
            summary="Added a face by hand",
            data={"item_id": item.id, "face_id": face.id})
    return face


def update_face(ctx: Ctx, face_id: int, *, dismissed: Optional[bool] = None,
                x=None, y=None, w=None, h=None) -> Face:
    """Dismiss a face, or move its box. Who it is goes through `name_face`."""
    s = ctx.session
    face = s.get(Face, face_id)
    if face is None:
        raise NotFound("face not found", code="face_not_found")

    if dismissed is not None:
        # "Not a face" says the same as "not this person" about anything a
        # guess put on it.
        if dismissed:
            for row in appearances_of(ctx.session, [face.id]).get(face.id, []):
                if row.assigned_by == "suggested":
                    s.delete(row)
                    s.flush()
                    drop_unconfirmed_tag(ctx, face.item_id, row.subject_id)
        face.dismissed = dismissed
        ctx.log(action=actions.DISMISS_FACE, entity_type="item",
                entity_id=face.item_id,
                summary=("Dismissed a face" if dismissed
                         else "Restored a dismissed face"),
                data={"item_id": face.item_id, "face_id": face.id,
                      "dismissed": dismissed})
    old_box = [face.x, face.y, face.w, face.h]
    for name, value in (("x", x), ("y", y), ("w", w), ("h", h)):
        if value is not None:
            setattr(face, name, value)
    box = [face.x, face.y, face.w, face.h]
    if box != old_box:
        # A DETECTED face's first hand edit keeps the detector's rectangle
        # aside (`FaceBoxEdit`): it is what "Reset the box" goes back to, and
        # its presence is what stops the next run overwriting the edit
        # (`jobs._apply_faces` refreshes the record instead of the face).
        # A hand-drawn face has no detector's answer to keep.
        recorded = False
        if face.model and s.execute(select(FaceBoxEdit).where(
                FaceBoxEdit.face_id == face.id)).scalars().first() is None:
            s.add(FaceBoxEdit(face_id=face.id, x=old_box[0], y=old_box[1],
                              w=old_box[2], h=old_box[3]))
            recorded = True
        ctx.log(action=actions.MOVE_FACE, entity_type="item",
                entity_id=face.item_id, summary="Moved a face's box",
                data={"item_id": face.item_id, "face_id": face.id,
                      "old_box": old_box, "box": box,
                      "orig_recorded": recorded})
    s.flush()
    touch_items(s, [face.item_id])
    return face


def name_face(ctx: Ctx, face_id: int, *, subject_id: Optional[int] = None,
              display_name: str = "", comment: str = "") -> Face:
    """Say who a face is — ADDING a claim, not replacing one.

    A face may be several people at once, so this appends. Taking the wrong one
    off is `unname_face`, which is a different statement and is remembered
    differently.
    """
    s = ctx.session
    face = s.get(Face, face_id)
    if face is None:
        raise NotFound("face not found", code="face_not_found")
    subject = s.get(Subject, subject_id) if subject_id else None
    created = False
    if subject is None:
        if not display_name.strip():
            raise Invalid("name the subject or choose an existing one",
                          code="subject_unnamed")
        subject = _mint_subject(ctx, display_name, comment)
        created = True

    # Naming a face something OTHER than what was suggested is a correction:
    # two facts at once, and the refusal is the half that keeps the next run
    # from repeating itself.
    for row in appearances_of(ctx.session, [face.id]).get(face.id, []):
        if row.assigned_by == "suggested" and row.subject_id != subject.id:
            facelib.refuse(s, face, row.subject_id, score=row.match_score,
                           username=s.info.get("username", ""))
            s.delete(row)
            s.flush()
            drop_unconfirmed_tag(ctx, face.item_id, row.subject_id)

    before = [r.id for r in appearances_of(ctx.session, [face.id]).get(face.id, [])]
    row = appear(ctx, face.item_id, subject, face.id)
    ctx.log(action=actions.NAME_FACE, entity_type="item",
            entity_id=face.item_id,
            summary="Named a face {name}",
            summary_vars={"name": label(ctx, subject)},
            data={"item_id": face.item_id, "face_id": face.id,
                  "subject_id": subject.id, "appearance_id": row.id,
                  "was_new": row.id not in before, "created_subject": created})
    s.flush()
    return face


def unname_face(ctx: Ctx, face_id: int, subject_id: int) -> Face:
    """Take one name off a face. The face stays — it is evidence."""
    s = ctx.session
    face = s.get(Face, face_id)
    if face is None:
        raise NotFound("face not found", code="face_not_found")
    row = s.execute(select(ItemSubject).where(
        ItemSubject.face_id == face.id,
        ItemSubject.subject_id == subject_id,
    )).scalars().first()
    if row is None:
        raise NotFound("that face is not them", code="not_them")
    was_by, was_score = row.assigned_by or "user", row.match_score
    was_when = (row.when_date, row.when_age)
    was_id = row.id
    s.delete(row)
    s.flush()
    # Saying "not this person" to a guess takes its pending tag with it — the
    # tag was the guess, not a statement anybody made.
    dropped = (drop_unconfirmed_tag(ctx, face.item_id, subject_id)
               if was_by == "suggested" else False)
    # And it is remembered, so the next run does not offer it again. ONLY for a
    # guess: taking a name somebody gave by hand back off says they changed
    # their mind, not that the model was wrong.
    if was_by == "suggested":
        facelib.refuse(s, face, subject_id, score=was_score,
                       username=s.info.get("username", ""))
    ctx.log(
        action=actions.UNNAME_FACE, entity_type="item", entity_id=face.item_id,
        summary="Took {name} off a face",
        summary_vars={"name": label(ctx, s.get(Subject, subject_id))},
        # Everything the assignment was, since a revert has to put the SHAPE
        # back and not just the id: a suggestion restored as an answer would be
        # immune to the next run that disagrees.
        data={"item_id": face.item_id, "face_id": face.id,
              "old_subject_id": subject_id, "old_assigned_by": was_by,
              "old_match_score": was_score, "old_date": was_when[0],
              "old_age": was_when[1], "tag_removed": dropped,
              # So the restore can put the row back under its own id, which is
              # what the `name_face` revert behind this one looks it up by.
              "old_appearance_id": was_id},
    )
    touch_items(s, [face.item_id])
    return face


def set_face_outline(ctx: Ctx, face_id: int, *,
                     x: Optional[float] = None, y: Optional[float] = None,
                     w: Optional[float] = None, h: Optional[float] = None,
                     clear: bool = False, points=None) -> Face:
    """Draw, replace or clear one face's OUTLINE — the whole figure, where
    the face box is only the head.

    `subjects.set_appearance_box`'s shape, one level down: at most one per
    face, fractions of the item's reference frame, ``points`` refines it to a
    POLYGON with the four columns holding its bounding box (derived here, so
    the two cannot drift). A subject attached to the face uses this outline
    wherever it has no subject box of its own. Logged with the old shape, so
    the revert restores what it replaced — or the absence it replaced.
    """
    import json as _json

    from .tagassign import poly_bbox

    s = ctx.session
    face = s.get(Face, face_id)
    if face is None:
        raise NotFound("face not found", code="face_not_found")
    pts_json = _json.dumps([[float(p[0]), float(p[1])] for p in points]) \
        if points else None
    bb = poly_bbox(pts_json)
    if bb is not None:
        x, y, w, h = bb
    else:
        pts_json = None
    if not clear and None in (x, y, w, h):
        raise Invalid("an outline needs all four sides", code="box_incomplete")
    row = s.execute(select(FaceOutline).where(
        FaceOutline.face_id == face.id)).scalars().first()
    old = ({"x": row.x, "y": row.y, "w": row.w, "h": row.h,
            **({"points": row.points} if row.points else {})}
           if row is not None else None)
    if clear:
        if row is None:
            return face  # clearing nothing is nothing to log
        s.delete(row)
    elif row is not None:
        row.x, row.y, row.w, row.h = float(x), float(y), float(w), float(h)
        row.points = pts_json
    else:
        s.add(FaceOutline(face_id=face.id, x=float(x), y=float(y),
                          w=float(w), h=float(h), points=pts_json))
    s.flush()
    touch_items(s, [face.item_id])
    ctx.log(action=actions.SET_FACE_OUTLINE, entity_type="item",
            entity_id=face.item_id,
            summary=("Removed a face's outline" if clear
                     else "Outlined a face's figure"),
            data={"item_id": face.item_id, "face_id": face.id,
                  "old": old,
                  "new": (None if clear
                          else {"x": float(x), "y": float(y),
                                "w": float(w), "h": float(h),
                                **({"points": pts_json} if pts_json
                                   else {})})})
    return face


def outlines_of(s, face_ids: list[int]) -> dict[int, FaceOutline]:
    """Each face's outline row, for the listings — one query, not one per
    face."""
    out: dict[int, FaceOutline] = {}
    for chunk in chunked(face_ids):
        for row in s.execute(select(FaceOutline).where(
                FaceOutline.face_id.in_(chunk))).scalars().all():
            out[row.face_id] = row
    return out


def box_edits_of(s, face_ids: list[int]) -> dict[int, FaceBoxEdit]:
    """Each face's hand-edit record — the detector's rectangle, kept while
    the box on the row is a person's. One query, not one per face."""
    out: dict[int, FaceBoxEdit] = {}
    for chunk in chunked(face_ids):
        for row in s.execute(select(FaceBoxEdit).where(
                FaceBoxEdit.face_id.in_(chunk))).scalars().all():
            out[row.face_id] = row
    return out


def reset_face_box(ctx: Ctx, face_id: int) -> Face:
    """Put the detector's rectangle back and forget the hand edit."""
    s = ctx.session
    face = s.get(Face, face_id)
    if face is None:
        raise NotFound("face not found", code="face_not_found")
    rec = s.execute(select(FaceBoxEdit).where(
        FaceBoxEdit.face_id == face.id)).scalars().first()
    if rec is None:
        raise Invalid("this face’s box has not been edited",
                      code="face_box_unedited")
    old_box = [face.x, face.y, face.w, face.h]
    face.x, face.y, face.w, face.h = rec.x, rec.y, rec.w, rec.h
    s.delete(rec)
    s.flush()
    ctx.log(action=actions.RESET_FACE_BOX, entity_type="item",
            entity_id=face.item_id, summary="Reset a face’s box",
            data={"item_id": face.item_id, "face_id": face.id,
                  "old_box": old_box,
                  "box": [face.x, face.y, face.w, face.h]})
    touch_items(s, [face.item_id])
    return face


def delete_face(ctx: Ctx, face_id: int) -> int:
    """Remove a face outright; returns the item it was on.

    Prefer dismissing a false positive — a deleted face comes straight back on
    the next run."""
    s = ctx.session
    face = s.get(Face, face_id)
    if face is None:
        raise NotFound("face not found", code="face_not_found")
    item_id = face.item_id
    ctx.log(action=actions.DELETE_FACE, entity_type="item", entity_id=item_id,
            summary="Deleted a face",
            data={"item_id": item_id, "face_id": face.id,
                  "box": [face.x, face.y, face.w, face.h],
                  "det_score": face.det_score, "model": face.model,
                  "subjects": snapshot(ctx, [face.id]),
                  "dismissed": face.dismissed})
    s.delete(face)
    s.flush()
    touch_items(s, [item_id])
    return item_id


# ---- clusters ---------------------------------------------------------------


def name_cluster(ctx: Ctx, face_ids: list[int], *,
                 subject_id: Optional[int] = None, display_name: str = "",
                 comment: str = "", replace: bool = True) -> Subject:
    """Name every face in a cluster at once — the point of the unnamed view.

    Naming one picture at a time is what kills face tagging in other tools:
    this turns "this person, fourteen times" into a tag on fourteen items in
    one action, and one event, so it reverts as one action too.

    It is also what dropping crops onto somebody's row does, so it MOVES by
    default: every other claim on those faces goes. `replace=False` COPIES
    instead — the character-and-the-actor case, which shift-dropping asks for —
    and then what was already on the face stays.

    EITHER WAY THE AGE COMES WITH IT. A face said to be twelve stays twelve
    whoever it turns out to be: the age describes the picture, not the name on
    it, and losing it on a drop is losing something nobody could get back from
    the crop.
    """
    s = ctx.session
    rows = list(s.execute(
        select(Face).where(Face.id.in_(face_ids))
    ).scalars().all())
    if not rows:
        raise NotFound("no such faces", code="no_such_faces")

    nameless = nameless_subject_ids(s)
    who = appearances_of(ctx.session, [f.id for f in rows])
    subject = s.get(Subject, subject_id) if subject_id else None
    created = False
    if subject is None:
        if not display_name.strip():
            raise Invalid("name the subject or choose an existing one",
                          code="subject_unnamed")
        # A cluster somebody merged by hand ALREADY has an identity — the
        # nameless subject holding it together. Naming it is giving that one a
        # name, not minting a second and orphaning the first.
        held = next((s.get(Subject, r.subject_id)
                     for f in rows for r in who.get(f.id, [])
                     if r.subject_id in nameless), None)
        if held is not None:
            subject = held
            subject.display_name = display_name.strip()
        else:
            subject = Subject(display_name=display_name.strip())
            s.add(subject)
            created = True
        s.flush()
        ops_subjects.mint_tag(
            ctx, subject,
            naming.free_slug(s, naming.prefixed(s, "subject", display_name)))
    if comment.strip():
        tagcatalog.describe(ctx, subject.tag_id, comment=comment.strip())

    before = snapshot(ctx, [f.id for f in rows])
    touched: list[int] = []
    for face in rows:
        others = [r for r in who.get(face.id, []) if r.subject_id != subject.id]
        # The age travels. Taken from whatever was on the face already — on a
        # move that record is about to go, on a copy it stays and the new one
        # matches it; either way the fact is about the picture.
        when = next(((r.when_date, r.when_age) for r in others
                     if r.when_date is not None or r.when_age is not None),
                    (None, None))
        if replace:
            for r in others:
                # Moving a crop off a machine's guess is a correction, the
                # same one `name_face` makes: remember the refusal so the
                # next run cannot re-offer the wrong name, and take back the
                # pending tag the guess assigned. A name somebody GAVE is a
                # different statement and is simply removed.
                refused = r.assigned_by == "suggested"
                if refused:
                    facelib.refuse(s, face, r.subject_id, score=r.match_score,
                                   username=s.info.get("username", ""))
                old_subject_id = r.subject_id
                s.delete(r)
                s.flush()
                if refused:
                    drop_unconfirmed_tag(ctx, face.item_id, old_subject_id)
        had = s.execute(select(ItemTag).where(
            ItemTag.item_id == face.item_id,
            ItemTag.tag_id == subject.tag_id)).scalars().first() is not None
        made = appear(ctx, face.item_id, subject, face.id)
        if made.when_date is None and made.when_age is None:
            made.when_date, made.when_age = when
        if not had and face.item_id not in touched:
            touched.append(face.item_id)
    s.flush()
    ctx.log(action=actions.NAME_FACES, entity_type="subject",
            entity_id=subject.id,
            summary=(("Named 1 face {name}" if len(rows) == 1
                      else "Named {n} faces {name}")
                     + (", on {items} items" if touched else "")),
            summary_vars={"n": len(rows), "name": label(ctx, subject),
                          "items": len(touched)},
            data={"subject_id": subject.id, "face_ids": [f.id for f in rows],
                  "backfilled": touched, "created_subject": created,
                  "before": before})
    return subject


def _reseat(ctx: Ctx, rows: list[Face], subject: Subject,
            nameless: set[int], *, replace_all: bool = False) -> None:
    """Move a set of faces onto one nameless identity — the shared half of
    merging and splitting.

    A MERGE touches only the nameless claims: it says which unnamed faces are
    one person, and a face somebody has named is still that person afterwards.
    A SPLIT (`replace_all`) takes every claim off, because that is what pulling
    a stray out of somebody's cluster means — the face was wrongly theirs.
    Taking one of several names off a face is `unname_face`, which says
    something narrower.
    """
    s = ctx.session
    who = appearances_of(ctx.session, [f.id for f in rows])
    for f in rows:
        mine = [r for r in who.get(f.id, [])
                if replace_all or r.subject_id in nameless]
        # A claim a MACHINE made, taken off by a split, is a correction like
        # the one `unname_face` records: remember the refusal so the next run
        # cannot re-offer the wrong name, and take back the pending tag the
        # guess assigned — the row's subject changes, and without this the
        # tag stayed on the item with no appearance behind it.
        for r in mine:
            if r.subject_id != subject.id and r.assigned_by == "suggested":
                facelib.refuse(s, f, r.subject_id, score=r.match_score,
                               username=s.info.get("username", ""))
                drop_unconfirmed_tag(ctx, f.item_id, r.subject_id)
        for r in mine[1:]:
            s.delete(r)
        if mine:
            mine[0].subject_id = subject.id
            mine[0].assigned_by = "user"
            mine[0].match_score = None
        else:
            s.add(ItemSubject(item_id=f.item_id, subject_id=subject.id,
                              face_id=f.id, assigned_by="user"))
    s.flush()


def declare_clusters_different(ctx: Ctx, face_ids: list[int],
                               other_ids: list[int]) -> None:
    """"NOT THIS PERSON", said of two whole clusters.

    The strip of lookalikes beside an open cluster offers the nearest
    neighbours whatever their score, so most of what it shows is wrong —
    and saying so has to STICK, or the next fetch offers the same face
    again. It is `SubjectCannotLink`, the statement a split already writes.

    Both clusters are given a nameless identity if they have none: a
    statement about two clusters is a statement about two identities, and
    an algorithm's grouping is not one until something says it is. That is
    the same move merging makes, and it has the same consequence — the
    cluster stops being re-grouped by the next run, which is right, since
    somebody has now said something about it as it stands.
    """
    a = _hold_cluster(ctx, face_ids)
    b = _hold_cluster(ctx, other_ids)
    if a is None or b is None or a.id == b.id:
        raise Invalid("pick two different clusters",
                      code="not_matching_same_cluster")
    facelib.declare_different(ctx.session, a.id, b.id)
    ctx.session.flush()
    ctx.log(action=actions.CLUSTERS_DIFFER, entity_type="subject",
            entity_id=a.id,
            summary="Said two face clusters are not one person",
            data={"a_subject_id": a.id, "b_subject_id": b.id})


def _hold_cluster(ctx: Ctx, face_ids: list[int]) -> Optional[Subject]:
    """The nameless identity holding these faces, made if there is none.

    `merge_clusters`' own first move, minus the merge: a cluster the
    algorithm made has no row of its own, and anything said ABOUT it needs
    one to hang on.
    """
    s = ctx.session
    rows = list(s.execute(select(Face).where(Face.id.in_(face_ids)))
                .scalars().all())
    if not rows:
        return None
    nameless = nameless_subject_ids(s)
    who = appearances_of(s, [f.id for f in rows])
    subject = next((s.get(Subject, r.subject_id)
                    for f in rows for r in who.get(f.id, [])
                    if r.subject_id is not None), None)
    if subject is not None:
        return subject
    subject = Subject(display_name="")
    s.add(subject)
    s.flush()
    _reseat(ctx, rows, subject, nameless)
    s.flush()
    return subject


def set_cluster_unnamed(ctx: Ctx, face_ids: list[int], on: bool = True
                        ) -> Optional[Subject]:
    """SAY THIS CLUSTER IS SOMEBODY WITH NO NAME — a background character, an
    extra — or take that back.

    A face cluster nobody has answered is UNKNOWN: the Faces tab is asking
    who it is. Most of a television series is people the answer is "nobody in
    particular" for, and the only way out of that queue was to invent a name
    for each of them, which puts junk in the catalog and in every prompt an
    export writes.

    So this is the OTHER answer, and it is a flag on a nameless subject of
    the cluster's OWN (`db.Subject.unnamed`) — never one shared "Unnamed"
    identity. Two background characters are two people: on one subject their
    faces would fold together, and naming one later would name both.

    Marking one is `merge_clusters`' own move without the "at least two":
    the faces are reseated onto one nameless subject, made if there is none,
    and the flag goes on it. Taking the mark off leaves the subject holding
    them — the cluster stays one cluster, it is simply a question again.
    """
    s = ctx.session
    rows = list(s.execute(select(Face).where(Face.id.in_(face_ids)))
                .scalars().all())
    if not rows:
        raise Invalid("pick at least one face", code="unnamed_no_faces")
    nameless = nameless_subject_ids(s)
    who = appearances_of(s, [f.id for f in rows])
    subject = next((s.get(Subject, r.subject_id)
                    for f in rows for r in who.get(f.id, [])
                    if r.subject_id in nameless), None)
    if subject is None and not on:
        # Nothing holds them, so there is no mark to take off.
        return None
    created = subject is None
    if subject is None:
        subject = Subject(display_name="")
        s.add(subject)
        s.flush()
    before = snapshot(ctx, [f.id for f in rows])
    was = bool(subject.unnamed)
    for entry in before:
        prev = entry["subject_id"]
        if prev in nameless and prev != subject.id:
            facelib.allow_same(s, prev, subject.id)
    _reseat(ctx, rows, subject, nameless)
    subject.unnamed = bool(on)
    s.flush()
    ctx.log(action=actions.SET_CLUSTER_UNNAMED, entity_type="subject",
            entity_id=subject.id,
            summary=("Marked {n} faces as somebody unnamed" if on
                     else "Took the unnamed mark off {n} faces"),
            summary_vars={"n": str(len(rows))},
            data={"subject_id": subject.id, "created_subject": created,
                  "unnamed": bool(on), "was": was,
                  "face_ids": [f.id for f in rows], "before": before})
    return subject


def merge_clusters(ctx: Ctx, face_ids: list[int]) -> Subject:
    """Fold several unnamed clusters into one, still unnamed.

    A detector that produces no descriptors (the anime one, which is the one
    that matters here) hands back one cluster per face, so saying "these are
    all the same person" is the work — and it has to survive, or the next run
    would scatter them again. It is held by a NAMELESS subject, which is
    exactly the identity-without-a-name the model already has; naming it later
    is the ordinary naming path, and mints the tag onto every item at once.
    """
    s = ctx.session
    rows = list(s.execute(select(Face).where(Face.id.in_(face_ids)))
                .scalars().all())
    if len(rows) < 2:
        raise Invalid("pick at least two faces to merge", code="merge_too_few")

    nameless = nameless_subject_ids(s)
    who = appearances_of(ctx.session, [f.id for f in rows])
    # Reuse a nameless subject already among them rather than minting a second
    # one — merging A into B twice must not leave an orphan identity.
    subject = next((s.get(Subject, r.subject_id)
                    for f in rows for r in who.get(f.id, [])
                    if r.subject_id in nameless), None)
    created = subject is None
    if subject is None:
        subject = Subject(display_name="")
        s.add(subject)
        s.flush()

    before = snapshot(ctx, [f.id for f in rows])
    # A merge is the newer statement: whatever a past split said about these
    # identities, the user has just said the opposite.
    for entry in before:
        was = entry["subject_id"]
        if was in nameless and was != subject.id:
            facelib.allow_same(s, was, subject.id)
    _reseat(ctx, rows, subject, nameless)
    ctx.log(action=actions.MERGE_FACES, entity_type="subject",
            entity_id=subject.id,
            summary="Merged {n} faces into one unnamed person",
            summary_vars={"n": len(rows)},
            data={"subject_id": subject.id, "created_subject": created,
                  "face_ids": [f.id for f in rows], "before": before})
    return subject


def split_faces(ctx: Ctx, face_ids: list[int]) -> Subject:
    """Pull faces off whoever they are on, onto a NEW person with no name.

    The counterpart of merging: a cluster is nearly always one person plus a
    stray, and the stray needs somewhere to go that is not "nobody" — losing
    the grouping would only mean finding it again. One face is a legitimate
    split (that is the stray case), which is why this is not `merge_clusters`
    with a flag: that one refuses fewer than two and reuses an identity it
    finds, both wrong here.

    Every name on those faces goes with them — being in somebody's cluster
    wrongly is exactly what a split fixes. The item's TAGS are left alone: a
    face is evidence, the tag is a separate statement about the picture, and
    the person may well still be in it.
    """
    s = ctx.session
    rows = list(s.execute(select(Face).where(Face.id.in_(face_ids)))
                .scalars().all())
    if not rows:
        raise NotFound("no such faces", code="no_such_faces")

    nameless = nameless_subject_ids(s)
    before = snapshot(ctx, [f.id for f in rows])
    subject = Subject(display_name="")
    s.add(subject)
    s.flush()
    _reseat(ctx, rows, subject, nameless, replace_all=True)
    # "These are not the same person" is the whole point of a split, so it is
    # recorded rather than left implicit in where the rows ended up.
    for entry in before:
        was = entry["subject_id"]
        if was != subject.id:
            facelib.declare_different(s, was, subject.id)
    ctx.log(action=actions.SPLIT_FACES, entity_type="subject",
            entity_id=subject.id,
            summary=("Split 1 face onto a new unnamed person" if len(rows) == 1
                     else "Split {n} faces onto a new unnamed person"),
            summary_vars={"n": len(rows)},
            data={"subject_id": subject.id, "created_subject": True,
                  "face_ids": [f.id for f in rows], "before": before})
    return subject
