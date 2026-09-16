"""Detected text: the geometry, and the rule that re-running OCR loses nothing.

The shape of :mod:`~media_compost.faces`, for the same reason — reading text is
cheap and repeatable, correcting it is not — with the whole embedding half
absent: a face's identity has to be inferred, so faces need a vector space, a
threshold and a rejection table, while a text region's identity IS its string.
Nothing is inferred, so nothing needs a veto, a cluster or a match score.

Two structural differences from faces, both load-bearing:

* **Regions form a TREE** (a block holds lines, a line holds words), so
  reconciliation recurses — and the "a detector is not evidence of absence"
  rule INVERTS for children of a matched parent: a block's line breakdown is
  *this run's reading of that block*, not an independent finding, so the
  unanswered children a re-run did not produce are deleted rather than kept
  beside the new ones (which would show the same sentence twice).

* **Identity is a column of the same row** (``text``), so the protection "a
  match refreshes geometry but never what a person said" has to be explicit:
  a region whose text somebody EDITED keeps that text forever, while its box
  still follows the engine (the machine goes on saying *where*; only a person
  says *what*, once a person has said it).

Everything here is pure functions over plain tuples so the rules can be
tested without a database, a model, or an image.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from .faces import Box, crop_box as _face_crop_box, iou

# How much two boxes must overlap to be called the same region. Its own
# constant rather than faces' 0.45: two faces side by side barely overlap,
# while two LINES in a dense paragraph overlap a great deal, and the sibling
# that must not merge here is the line above — which is also why matching is
# partitioned by (parent, level, engine) before IoU is ever consulted.
IOU_SAME_TEXT = 0.5

# Breathing room around a text crop. NOT faces' 0.25 — a face crop wants head
# and shoulders, a text crop only wants its glyphs not shaved at the edge.
CROP_MARGIN = 0.05


# ---- quads ------------------------------------------------------------------
#
# An OCR engine reads rotated and perspective text and says so with four
# points; a face detector never does, which is why `Face` has no analogue.
# The stored form is eight comma-joined fractions (`FaceRejection.box`'s
# precedent: opaque to SQL, only ever rendered, never compared) and "" means
# "the AABB is the shape" — so an upright region never carries a second copy
# of its own box to drift from. Pack/unpack live here, beside the geometry
# that consumes them, so no router splits the string by hand.

Point = tuple[float, float]


def pack_quad(points: Optional[Iterable[Sequence[float]]]) -> str:
    """Eight comma-joined fractions — or ``""`` for anything that is not four
    points, which reads as "the box is the shape"."""
    pts = [(float(p[0]), float(p[1])) for p in (points or ())]
    if len(pts) != 4:
        return ""
    return ",".join(f"{v:.6f}" for xy in pts for v in xy)


def unpack_quad(raw: str) -> list[Point]:
    """The four points back, or ``[]`` for ``""`` and anything malformed —
    a sidecar restored from an old build can hold anything."""
    if not raw:
        return []
    try:
        vals = [float(v) for v in raw.split(",")]
    except ValueError:
        return []
    if len(vals) != 8:
        return []
    return [(vals[i], vals[i + 1]) for i in range(0, 8, 2)]


def aabb_of(points: Sequence[Sequence[float]]) -> Box:
    """The axis-aligned bounding box of a quad — what every generic reader
    (crops, IoU, counts, hit-testing) consumes."""
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    x, y = min(xs), min(ys)
    return (x, y, max(xs) - x, max(ys) - y)


def crop_box(box: Box, width: int, height: int,
             margin: float = CROP_MARGIN) -> tuple[int, int, int, int]:
    """Pixel crop rectangle for a text region — faces' arithmetic at text's
    margin."""
    return _face_crop_box(box, width, height, margin=margin)


# ---- reconciliation ---------------------------------------------------------


@dataclass(frozen=True)
class Detected:
    """One region a run read, subtree and all.

    ``score`` is None when the engine has no confidence to give (Magi is
    generative) — NEVER a provenance signal, unlike ``Face.det_score``.
    ``quad`` is already packed (:func:`pack_quad`); ``""`` = upright.
    The order of ``children`` is the engine's own reading order.
    """

    box: Box
    text: str = ""
    score: Optional[float] = None
    quad: str = ""
    lang: str = ""
    level: str = "block"
    children: tuple["Detected", ...] = ()


@dataclass(frozen=True)
class Known:
    """One region already on record, as far as reconciliation cares.

    ``models`` is the set of engines that have read it — empty for a region
    somebody drew by hand. Provenance is read off THAT, never off the score
    (see :class:`Detected`).
    """

    id: int
    box: Box
    level: str = "block"
    parent_id: Optional[int] = None
    models: frozenset[str] = field(default_factory=frozenset)
    text: str = ""
    score: Optional[float] = None
    dismissed: bool = False
    edited: bool = False

    @property
    def answered(self) -> bool:
        """Whether somebody has answered for this region — corrected it,
        dismissed it, or drawn it by hand. Such a region is never dropped as
        a duplicate and its text is never rewritten."""
        return self.dismissed or self.edited or not self.models


@dataclass
class Reconciled:
    """What a run should do to the record.

    ``updated`` maps an existing region id to the detection that refreshes
    it — geometry, quad, score, lang and the model credit ALWAYS; the TEXT
    only when ``retext`` holds the id (i.e. nobody has edited or dismissed
    it). ``added`` are detections nothing on record accounts for, as
    ``(parent region id or None, subtree)``. ``orphaned`` are the unanswered
    children of a MATCHED parent that this run did not produce — this run's
    reading of the block replaces the breakdown it wrote last time.

    Top-level regions the run did not find are in none of these lists, and
    that is deliberate: they may have been drawn by hand, and they may be in
    a script this pass's recogniser does not know — running a Japanese pass
    after a Latin one is the normal workflow here.
    """

    updated: dict[int, Detected]
    retext: frozenset[int]
    added: list[tuple[Optional[int], Detected]]
    orphaned: list[int]


def merge_detections(found: Iterable[Detected]) -> list[Detected]:
    """One detection per region, from a run that said the same stretch twice.

    RapidOCR really does return overlapping quads for stacked vertical text.
    List order is the engine's reading order and the EARLIER box wins — for
    text, where the run's order is the one meaningful priority, that beats
    faces' by-score rule (half the engines here have no score at all).
    Levels never collapse into each other.
    """
    kept: list[Detected] = []
    for d in found:
        if any(d.level == k.level and iou(d.box, k.box) >= IOU_SAME_TEXT
               for k in kept):
            continue
        kept.append(d)
    return kept


def _participates(k: Known, model: str) -> bool:
    # A known region joins a run's matching only when that engine already
    # read it, or when it is hand-drawn (which any engine may then claim).
    # This is what makes "each engine's reading is its own" true by
    # construction: two engines never merge their readings, and re-running
    # one reconciles against exactly its own previous one.
    return model in k.models or not k.models


def reconcile(known: Sequence[Known], found: Iterable[Detected], *,
              model: str) -> Reconciled:
    """Match a run's regions against what is already on record.

    Greedy by overlap within each ``(parent, level)`` partition, restricted
    to regions this engine may claim (:func:`_participates`) — cross-level
    and cross-engine matching are forbidden outright. A **dismissed** region
    can be matched: the detection is absorbed instead of re-added for the
    user to dismiss again, nothing under it changes, and its text stays.
    An **edited** region takes the new geometry and keeps its text.

    Children reconcile INSIDE their matched parent, recursively; a block
    that matched nothing is added whole, subtree and all.
    """
    updated: dict[int, Detected] = {}
    retext: set[int] = set()
    added: list[tuple[Optional[int], Detected]] = []
    orphaned: list[int] = []

    by_parent: dict[Optional[int], list[Known]] = {}
    for k in known:
        by_parent.setdefault(k.parent_id, []).append(k)

    def visit(parent_id: Optional[int],
              found_here: Sequence[Detected]) -> None:
        dets = merge_detections(found_here)
        siblings = by_parent.get(parent_id, [])
        for level in sorted({d.level for d in dets}):
            level_dets = [d for d in dets if d.level == level]
            pool = [k for k in siblings
                    if k.level == level and _participates(k, model)]
            # Strongest overlaps first, so a detection between two known
            # regions goes to the one it really is.
            pairs = sorted(
                ((iou(d.box, k.box), i, j)
                 for i, d in enumerate(level_dets)
                 for j, k in enumerate(pool)),
                key=lambda p: -p[0],
            )
            taken: set[int] = set()
            claimed: set[int] = set()
            matches: list[tuple[Known, Detected]] = []
            for score, i, j in pairs:
                if score < IOU_SAME_TEXT:
                    break
                if i in taken or j in claimed:
                    continue
                taken.add(i)
                claimed.add(j)
                matches.append((pool[j], level_dets[i]))
            for k, d in matches:
                updated[k.id] = d
                if k.dismissed:
                    # Absorbed. Recursing would resurface the text below a
                    # region somebody said is not text.
                    continue
                if not k.answered:
                    # …which also covers the hand-drawn case (models empty):
                    # an engine may claim the box, never rewrite what was
                    # typed into it.
                    retext.add(k.id)
                visit(k.id, list(d.children))
                # Rule 6's inversion: the breakdown this engine wrote last
                # time and did not re-produce is deleted — unless somebody
                # answered for a child, which survives everything.
                for c in by_parent.get(k.id, []):
                    if c.id in updated or c.answered:
                        continue
                    if model in c.models:
                        orphaned.append(c.id)
            for i, d in enumerate(level_dets):
                if i not in taken:
                    added.append((parent_id, d))

    visit(None, list(found))
    return Reconciled(updated=updated, retext=frozenset(retext),
                      added=added, orphaned=orphaned)


def duplicates(known: Sequence[Known]) -> list[int]:
    """Ids of regions another region on record already accounts for.

    ``merge_detections``' collapse applied to what is stored, scoped per
    ``(parent, level)`` and — unlike faces — only within a shared engine (or
    between two hand-drawn boxes): two engines reading one stretch each keep
    their own row, because "grouped by engine" is the display contract. A
    region somebody has ANSWERED for is never dropped.
    """
    extra: list[int] = []
    groups: dict[tuple[Optional[int], str], list[Known]] = {}
    for k in known:
        groups.setdefault((k.parent_id, k.level), []).append(k)
    for group in groups.values():
        order = sorted(group,
                       key=lambda k: (not k.answered, -(k.score or 0.0)))
        kept: list[Known] = []
        for k in order:
            clash = any(
                iou(k.box, o.box) >= IOU_SAME_TEXT
                and (bool(k.models & o.models)
                     or (not k.models and not o.models))
                for o in kept)
            if clash and not k.answered:
                extra.append(k.id)
                continue
            kept.append(k)
    return extra
