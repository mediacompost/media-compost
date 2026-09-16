"""Faces: the geometry, and the rule that re-running a detector loses nothing.

Detection is cheap and repeatable; naming faces is not. So the only interesting
logic here is reconciliation — matching a fresh run's boxes against what is
already on record — and it is written as a pure function over plain tuples so
the rule can be tested without a database, a model, or an image.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, NamedTuple, Optional, Sequence

from sqlalchemy import delete, select

# How much two boxes must overlap to be called the same face. Detectors jitter
# a few pixels between runs and crop slightly differently between versions;
# 0.45 is loose enough to survive that and tight enough that two faces side by
# side in a group photo never merge.
IOU_SAME_FACE = 0.45

Box = tuple[float, float, float, float]  # x, y, w, h — fractions of the frame


def iou(a: Box, b: Box) -> float:
    """Intersection over union of two boxes. 0 when they do not overlap."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left, right = max(ax, bx), min(ax + aw, bx + bw)
    top, bottom = max(ay, by), min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    union = aw * ah + bw * bh - overlap
    return overlap / union if union > 0 else 0.0


@dataclass(frozen=True)
class Detected:
    """One face a run found.

    ``embedding`` is a descriptor in ONE space, named by the run's ``embedder``
    rather than carried here: a run uses one model, so the space belongs to the
    run and not to each box.
    """

    box: Box
    score: float
    embedding: Optional[bytes] = None


@dataclass(frozen=True)
class Known:
    """One face already on record, as far as reconciliation cares."""

    id: int
    box: Box
    dismissed: bool = False
    score: float = 0.0
    #: Whether somebody has answered for this face — named it, dismissed it or
    #: drawn it by hand. Such a face is never dropped as a duplicate.
    answered: bool = False


@dataclass
class Reconciled:
    """What a run should do to the record.

    ``updated`` maps an existing face id to the detection that refreshes it —
    box, score and embedding only. Everything about WHO it is stays untouched,
    which is the whole point.

    ``added`` are detections nothing on record accounts for.

    Faces the run did not find are in neither list, and that is deliberate:
    they may have been drawn by hand, or the model may simply have got worse.
    A detector is not evidence of absence.
    """

    updated: dict[int, Detected]
    added: list[Detected]


def merge_detections(found: Iterable[Detected]) -> list[Detected]:
    """One detection per face, from a run that returned several for one.

    A detector's own suppression is not always enough — the anime detector in
    particular hands back a confident box and a weaker one a few pixels inside
    it, which reconciliation would faithfully record as two faces because it
    only ever compares a detection with what is already on file, never with the
    rest of its own run. The strongest box wins; anything that overlaps it as
    much as a re-run would is the same face said twice.
    """
    kept: list[Detected] = []
    for d in sorted(found, key=lambda d: -d.score):
        if any(iou(d.box, k.box) >= IOU_SAME_FACE for k in kept):
            continue
        kept.append(d)
    return kept


def duplicates(known: Sequence[Known]) -> list[int]:
    """Ids of faces that another face on record already accounts for.

    The same collapse as ``merge_detections``, applied to what is already
    stored — so a library that collected a duplicate before that rule existed
    (or from two runs whose boxes drifted apart and back) heals on the next
    detection rather than keeping the extra row forever.

    A face somebody has ANSWERED for — named, dismissed, or drawn by hand — is
    never dropped, and never loses out to a stronger detection: the answer is
    the thing worth keeping, and the box it is attached to is only how it was
    found.
    """
    # Answered faces first, then the confident ones: whatever is kept first
    # decides what counts as a duplicate of it.
    order = sorted(known, key=lambda k: (not k.answered, -k.score))
    kept: list[Known] = []
    extra: list[int] = []
    for k in order:
        if any(iou(k.box, o.box) >= IOU_SAME_FACE for o in kept):
            if not k.answered:
                extra.append(k.id)
                continue
        kept.append(k)
    return extra


def reconcile(known: Sequence[Known], found: Iterable[Detected]) -> Reconciled:
    """Match a run's detections against the faces already on record.

    Greedy by overlap: each detection takes the best unclaimed match above the
    threshold. A **dismissed** face can be matched — that is what makes the
    dismissal stick, because the detection is absorbed instead of re-added as a
    new face for the user to dismiss again.

    The run's own overlapping boxes are collapsed first (``merge_detections``);
    without that, a second box over a face already claimed by a stronger one
    would be added as a new face.
    """
    detections = merge_detections(found)
    updated: dict[int, Detected] = {}
    added: list[Detected] = []
    claimed: set[int] = set()

    # Strongest overlaps first, so a detection between two known faces goes to
    # the one it really is rather than whichever comes first in the list.
    pairs = sorted(
        ((iou(d.box, k.box), i, k.id)
         for i, d in enumerate(detections) for k in known),
        key=lambda p: -p[0],
    )
    taken: set[int] = set()
    for score, i, face_id in pairs:
        if score < IOU_SAME_FACE:
            break
        if i in taken or face_id in claimed:
            continue
        taken.add(i)
        claimed.add(face_id)
        updated[face_id] = detections[i]
    for i, d in enumerate(detections):
        if i not in taken:
            added.append(d)
    return Reconciled(updated=updated, added=added)


def crop_box(box: Box, width: int, height: int, margin: float = 0.25
             ) -> tuple[int, int, int, int]:
    """Pixel crop rectangle for a face, with breathing room around it.

    A detector's box is the face alone, which reads as a smear at thumbnail
    size; a quarter of the box added on each side gives it a head and shoulders.
    Clamped to the image, so a face at the edge is not shifted inwards — it just
    gets less margin on that side.
    """
    x, y, w, h = box
    dx, dy = w * margin, h * margin
    left = max(0, int(round((x - dx) * width)))
    top = max(0, int(round((y - dy) * height)))
    right = min(width, int(round((x + w + dx) * width)))
    bottom = min(height, int(round((y + h + dy) * height)))
    if right <= left:
        right = min(width, left + 1)
    if bottom <= top:
        bottom = min(height, top + 1)
    return left, top, right, bottom


# ---- embeddings ------------------------------------------------------------
#
# A descriptor is stored as raw float32 bytes. The main venv is torch-free and
# these are short vectors compared in bulk, so the arithmetic is done here with
# `array` and plain floats rather than pulling in a numeric stack.

def pack_embedding(values: Sequence[float]) -> bytes:
    from array import array

    return array("f", [float(v) for v in values]).tobytes()


def unpack_embedding(raw: Optional[bytes]) -> list[float]:
    from array import array

    if not raw:
        return []
    out = array("f")
    out.frombytes(raw)
    return list(out)


def similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, 0 when either side is missing or degenerate.

    Face descriptors are compared by angle, not distance — that is what the
    models are trained to produce — and every recogniser in this space quotes
    its thresholds that way.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---- storage: one descriptor per (face, space) -----------------------------
#
# These are the ONLY way a descriptor is read or written. Keeping them here,
# beside the maths that consumes them, is what stops a caller reaching for
# `Face.embedding` again and comparing two spaces by accident.


def store_embedding(session, face_id: int, model: str, vector: bytes) -> None:
    """Record a face's descriptor in one model's space, replacing that model's
    previous one and leaving every other space alone."""
    from .db import FaceEmbedding

    row = session.execute(
        select(FaceEmbedding).where(FaceEmbedding.face_id == face_id,
                                    FaceEmbedding.model == model)
    ).scalars().first()
    if row is None:
        session.add(FaceEmbedding(face_id=face_id, model=model, vector=vector))
    else:
        row.vector = vector


def embedding_models_of(session, face_ids: Sequence[int]) -> dict[int, list[str]]:
    """``{face_id: [model, …]}`` — WHICH spaces hold a vector, without reading
    a single one. The face listings only report `has_embedding`/`embedded_by`,
    and loading a 2 KB blob per face to answer a boolean was most of a large
    listing's payload work."""
    from .db import FaceEmbedding, chunked

    if not face_ids:
        return {}
    out: dict[int, list[str]] = {}
    for chunk in chunked(list(face_ids)):
        for fid, model in session.execute(
            select(FaceEmbedding.face_id, FaceEmbedding.model)
            .where(FaceEmbedding.face_id.in_(chunk))
            .order_by(FaceEmbedding.model)
        ).all():
            out.setdefault(fid, []).append(model)
    return out


def embeddings_of(session, face_ids: Sequence[int]) -> dict[int, dict[str, bytes]]:
    """``{face_id: {model: vector}}`` for the faces asked about (chunked — the
    unnamed view asks about every face in the library at once)."""
    from .db import FaceEmbedding, chunked

    if not face_ids:
        return {}
    out: dict[int, dict[str, bytes]] = {}
    for chunk in chunked(list(face_ids)):
        for row in session.execute(
            select(FaceEmbedding).where(FaceEmbedding.face_id.in_(chunk))
        ).scalars().all():
            out.setdefault(row.face_id, {})[row.model] = row.vector
    return out


def rejections_for(session, face_ids: Sequence[int]) -> dict[int, frozenset[int]]:
    """``{face_id: {subject_id refused}}`` — the veto, read in bulk (chunked)."""
    from .db import FaceRejection, chunked

    if not face_ids:
        return {}
    out: dict[int, set[int]] = {}
    for chunk in chunked(list(face_ids)):
        for row in session.execute(
            select(FaceRejection).where(FaceRejection.face_id.in_(chunk))
        ).scalars().all():
            out.setdefault(row.face_id, set()).add(row.subject_id)
    return {k: frozenset(v) for k, v in out.items()}


def refuse(session, face, subject_id: int, *, model: str = "",
           score: Optional[float] = None, exemplar_face_id: Optional[int] = None,
           username: str = "") -> None:
    """Record that this face is NOT that person, once.

    Idempotent: refusing twice is one fact, and the unique constraint says so.
    """
    from .db import FaceRejection, Item

    if not subject_id:
        return
    existing = session.execute(
        select(FaceRejection).where(FaceRejection.face_id == face.id,
                                    FaceRejection.subject_id == subject_id)
    ).scalars().first()
    if existing is not None:
        return
    item = session.get(Item, face.item_id)
    session.add(FaceRejection(
        face_id=face.id, subject_id=subject_id, model=model, score=score,
        exemplar_face_id=exemplar_face_id, username=username,
        item_uid=(item.uid if item is not None else ""),
        box=",".join(f"{v:.6f}" for v in (face.x, face.y, face.w, face.h)),
    ))


def declare_different(session, a: int, b: int) -> None:
    """Record that two identities are not one person (from a split)."""
    from .db import SubjectCannotLink

    lo, hi = sorted((a, b))
    if lo == hi:
        return
    if session.execute(
        select(SubjectCannotLink).where(SubjectCannotLink.a_subject_id == lo,
                                        SubjectCannotLink.b_subject_id == hi)
    ).scalars().first() is None:
        session.add(SubjectCannotLink(a_subject_id=lo, b_subject_id=hi))


def allow_same(session, a: int, b: int) -> None:
    """Take that back — a merge is the newer statement."""
    from .db import SubjectCannotLink

    lo, hi = sorted((a, b))
    session.execute(delete(SubjectCannotLink).where(
        SubjectCannotLink.a_subject_id == lo,
        SubjectCannotLink.b_subject_id == hi))


# Two faces are called the same person above this. Deliberately cautious: the
# cost of a wrong merge is a cluster the user has to pull apart by hand, while
# the cost of a split is one extra "name all 6" click.
#
# This is the MAGI number, and it was measured on drawn faces (a separating band
# of 0.538…0.632). It is the default because a manga library is what this app is
# mostly for — but it is not a universal constant, which `SPACE_BANDS` is about.
SAME_PERSON = 0.62

# Where each embedder's separating band actually sits, measured on this
# library's own hand-labelled faces:
#
#   insightface_buffalo_l (512-d)  within 0.412…0.742   between −0.077…0.155
#   anime_face_magi       (768-d)  within 0.708…0.984   between  0.222…0.529
#
# One number cannot serve both. At 0.62 — tuned for Magi — **14 of 22
# same-person ArcFace pairs were missed**, a 64% miss rate on photographs, with
# no false matches to show for it. The bands do not overlap in either space, so
# each gets the middle of its own gap.
#
# A space nobody has measured falls back to the SETTING itself, which is the
# honest answer: cautious, and visibly so.
SPACE_BANDS: dict[str, tuple[float, float]] = {
    # (between-people ceiling, within-person floor)
    "insightface_buffalo_l": (0.155, 0.412),
    "anime_face_magi": (0.529, 0.708),
}

# What the LIBRARY SETTING defaults to — a different question from
# `SAME_PERSON`, which is a MEASUREMENT (where Magi's own separating band
# sits) and is what the mapping below reads a setting against. They were one
# number and could not stay one: moving the default is a preference somebody
# states, while moving the anchor would silently re-scale every space.
#
# 0.90 rather than the measured 0.62: a wrong merge is a cluster somebody has
# to pull apart by hand and a missed one is an extra "name all 6" click, so
# the default sits well above the band Magi's own faces separate in. It was
# 0.80 until 2026-09, and 0.80 was still guessing too freely — a drawn
# character's cluster arrived with hundreds of guesses to reject one at a
# time, which is the expensive half of the trade in the wrong direction.
MATCH_DEFAULT = 0.90


def threshold_for(space: str, setting: float = SAME_PERSON) -> float:
    """The cutoff for one embedder, given the library's single setting.

    The setting stays ONE knob — asking somebody to calibrate a cosine per
    model is asking them to do the measurement above. It is read as a position
    in `SAME_PERSON`'s own band and carried to the same position in the target
    space, so "stricter" means stricter everywhere.

    **Outside that band it EXTRAPOLATES rather than clamping.** The band is
    0.529…0.708 wide, so a clamp made every setting from 71% up mean exactly
    the same thing — the whole top third of the slider, the default among
    them, inert with nothing saying so. Linear either way keeps a stricter
    number strictly stricter; the result is only held inside (0, 1), which is
    the range a cosine of two unit vectors can be compared at.
    """
    band = SPACE_BANDS.get(space)
    if band is None:
        return setting
    lo, hi = band
    ref = SPACE_BANDS.get("anime_face_magi", (lo, hi))
    span = ref[1] - ref[0]
    pos = 0.5 if span <= 0 else (setting - ref[0]) / span
    return min(max(lo + pos * (hi - lo), 0.0), 0.999)


def comparable(space: str, score: float) -> float:
    """One space's cosine, carried onto the SETTING's own scale.

    `threshold_for` read backwards: a 0.55 from InsightFace and a 0.55 from
    Magi are not the same claim — the two bands do not even overlap — so a
    number shown to somebody, or compared between two clusters embedded by
    different detectors, has to be said in one language. This is that
    language, and it is the one the library's single setting is already in.
    """
    band = SPACE_BANDS.get(space)
    if band is None:
        return score
    lo, hi = band
    ref = SPACE_BANDS.get("anime_face_magi", (lo, hi))
    span = hi - lo
    pos = 0.5 if span <= 0 else (score - lo) / span
    return min(max(ref[0] + pos * (ref[1] - ref[0]), 0.0), 1.0)


# HOW ALIKE TWO GROUPS ARE IS `group_likeness` ABOVE, AND ONLY THAT (owner
# 2026-09). There were two answers here: the mean of every cross pair, which
# the clustering asks, and the angle between the two groups' CENTROIDS, which
# the "might be the same person" strip asked. They are not the same number —
# on the demo library the centroids read about twenty points high and ranked a
# 297-crop cluster above a 3-crop one that was the better match, because an
# embedder handed pictures outside its domain answers with vectors that all
# lean one way and a group's average IS that lean. One number has to mean one
# thing wherever it is shown, so `centroids` and `cluster_likeness` are gone
# and the strip asks `facevec.pair_likeness`, the matrix twin of the rule the
# clustering keeps.


def cluster(faces: Sequence[tuple[int, Optional[bytes]]],
            threshold: float = SAME_PERSON) -> list[list[int]]:
    """Group face ids by descriptor similarity.

    Single-link agglomeration, which is the right shape for this: a face that
    is clearly the same person as one member belongs with the group, even when
    it is a poor match for another member photographed from the other side.

    Faces with no descriptor cannot be grouped and each come back alone, so a
    detection-only model (the anime detector) still fills this view — just
    ungrouped, which is what the UI expects.
    """
    return cluster_spaces(
        [fid for fid, _ in faces],
        {fid: {"": raw} for fid, raw in faces if raw is not None},
        threshold,
    )


#: A group's own vectors, per (space, dimension) — the key the app's matrices
#: are blocked by, because two vectors of different lengths can never be
#: compared and must not be averaged into one another.
Block = dict[tuple[str, int], list[list[float]]]

#: How big a component the refinement will take on — the app's own cap
#: (`facevec.SPLIT_MAX`), so the two implementations answer the same thing.
#: Past it a component is a library-wide problem rather than a person, and is
#: left as reachability found it.
SPLIT_MAX = 2000


def group_blocks(unpacked: dict[int, dict[str, list[float]]],
                 members: Sequence[int]) -> Block:
    """One group's descriptors, gathered per (space, dimension)."""
    out: Block = {}
    for fid in members:
        for space, vec in (unpacked.get(fid) or {}).items():
            if vec:
                out.setdefault((space, len(vec)), []).append(list(vec))
    return out


def group_likeness(a: Block, b: Block) -> Optional[float]:
    """How alike two groups are, on the SETTING's own scale — the BEST of the
    spaces they share, None where they share none.

    **THE MEAN OF EVERY CROSS PAIR, not the angle between their averages.**
    An embedder handed pictures outside its domain — a photograph to a manga
    model, a drawing to a face recogniser — answers with vectors that all lean
    one way, and the average of a dozen of those IS that lean: two groups'
    means then agree almost perfectly while no two of their faces do. The mean
    of the pairs keeps saying what the pairs say.
    """
    best: Optional[float] = None
    for key, va in a.items():
        vb = b.get(key)
        if not vb:
            continue
        total = 0.0
        for x in va:
            for y in vb:
                total += similarity(x, y)
        got = comparable(key[0], total / (len(va) * len(vb)))
        if best is None or got > best:
            best = got
    return best


def split_by_likeness(members: Sequence[int],
                      unpacked: dict[int, dict[str, list[float]]],
                      setting: float = SAME_PERSON) -> list[list[int]]:
    """Cut one reachable component into groups that each look like ONE person.

    **SINGLE LINK CHAINS, AND A PAGE OF MANGA IS A CHAIN.** Reachability alone
    — A is B, B is C, therefore A, B and C are one person — put 660 of a demo
    library's 927 unanswered faces in one cluster, where only 8% of the pairs
    inside it were a match at all and the median pair scored 0.52 against a
    threshold of 0.80: dozens of characters drawn in one hand, each linked to
    the next by a single lookalike crop. Average linkage over the same
    component gives 87, 62, 52, 34, 32, 27… — which is what a cast looks like.

    Greedy: merge the two groups that look most alike, while they still look
    like one person. Ties go to the earliest pair, so the answer does not
    depend on how a dictionary happened to be ordered.
    """
    # UNDER THREE THERE IS NOTHING TO CUT — a pair is in one component
    # because a pair agreed, which is the same thing average linkage would
    # ask. Past the cap the component is left exactly as reachability found
    # it, which is what it always was.
    if len(members) < 3 or len(members) > SPLIT_MAX:
        return [list(members)]
    parts = [[fid] for fid in members]
    blocks = [group_blocks(unpacked, p) for p in parts]
    while len(parts) > 1:
        best: Optional[tuple[float, int, int]] = None
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                got = group_likeness(blocks[i], blocks[j])
                if got is None or got < setting:
                    continue
                if best is None or got > best[0]:
                    best = (got, i, j)
        if best is None:
            break
        _, i, j = best
        parts[i] = parts[i] + parts[j]
        blocks[i] = group_blocks(unpacked, parts[i])
        parts.pop(j)
        blocks.pop(j)
    return parts


def cluster_spaces(ids: Sequence[int],
                   vectors: dict[int, dict[str, bytes]],
                   setting: float = SAME_PERSON) -> list[list[int]]:
    """Group face ids, comparing only within each embedding space.

    **One union-find, fed each space's agreements separately** — not one
    clustering per space concatenated. Clustering per space and appending the
    results is not a PARTITION: a face described by two models lands in two
    groups, and the unnamed view then shows it twice, double-counts the header
    and hands two rows the same React key.

    Two faces are REACHABLE when *any* space says they are the same person,
    each space judged at its own threshold (`threshold_for`). That is the right
    reading of "any space says so": the spaces disagree about scale, not about
    people.

    **AND REACHABILITY IS NOT THE ANSWER, ONLY THE QUESTION** (owner 2026-09):
    a component is then cut into groups that each look like one person as a
    WHOLE (`split_by_likeness`) — a face joins a group when it looks like what
    the group looks like, not merely like one member of it. Two stages rather
    than one rule, because the first is what makes the second affordable: the
    edges are found with an index over the whole library, and the greedy
    agglomeration then runs inside components that are usually tiny.
    """
    unpacked = {fid: {m: unpack_embedding(v) for m, v in spaces.items()}
                for fid, spaces in vectors.items()}
    parent = {fid: fid for fid in ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ids = list(ids)
    for i, a in enumerate(ids):
        mine = unpacked.get(a) or {}
        if not mine:
            continue
        for b in ids[i + 1:]:
            theirs = unpacked.get(b) or {}
            if not theirs or find(a) == find(b):
                continue
            shared = mine.keys() & theirs.keys()
            if any(similarity(mine[m], theirs[m]) >= threshold_for(m, setting)
                   for m in shared):
                parent[find(b)] = find(a)

    groups: dict[int, list[int]] = {}
    for fid in ids:
        groups.setdefault(find(fid), []).append(fid)
    out: list[list[int]] = []
    for members in groups.values():
        out.extend(split_by_likeness(members, unpacked, setting))
    # Biggest first — the cluster worth naming is the one that saves most work.
    return sorted(out, key=lambda g: (-len(g), g[0]))


#: How far the winner must beat the best score belonging to somebody ELSE.
#:
#: Lowe's ratio test, in the form this problem takes: an absolute score says
#: how alike two faces are, and says nothing about whether a second person is
#: just as good a match. When two people are equally close the honest answer is
#: to ask rather than to pick, so nothing is suggested at all.
RUNNER_UP_MARGIN = 0.05


class Match(NamedTuple):
    """Who a face looks like, how sure, and which face said so.

    A NamedTuple so `hit[0]` still reads as it always did, while the exemplar
    has somewhere to live.
    """

    subject_id: int
    score: float
    exemplar_face_id: Optional[int] = None


def best_match(embedding: Optional[bytes],
               candidates: Sequence[tuple[int, Optional[bytes]]],
               threshold: float = SAME_PERSON,
               margin: float = RUNNER_UP_MARGIN,
               exclude: Iterable[int] = (),
               ) -> Optional[Match]:
    """The subject a face most resembles — or None.

    ``candidates`` are (subject_id, embedding) pairs, one per known face of a
    named subject; the best single face wins, since a subject photographed
    across twenty years has no meaningful average. A third element may carry
    that face's id, which is what lets a refusal name the exemplar that fired.

    ``exclude`` are subjects this face has already been refused for. They are
    dropped before the comparison rather than after, so a rejected person
    cannot even be the runner-up that suppresses somebody else.
    """
    vector = unpack_embedding(embedding)
    if not vector:
        return None
    refused = set(exclude)
    best: Optional[Match] = None
    runner_up = 0.0
    for entry in candidates:
        subject_id, raw = entry[0], entry[1]
        face_id = entry[2] if len(entry) > 2 else None
        if subject_id in refused:
            continue
        score = similarity(vector, unpack_embedding(raw))
        if score < threshold:
            continue
        if best is None or score > best.score:
            if best is not None and best.subject_id != subject_id:
                runner_up = max(runner_up, best.score)
            best = Match(subject_id, score, face_id)
        elif subject_id != best.subject_id:
            runner_up = max(runner_up, score)
    if best is None or best.score < runner_up + margin:
        return None
    return best
