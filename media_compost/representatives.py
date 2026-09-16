"""REPRESENTATIVE ITEMS — a handful of pictures that stand for a tag.

The Tags tab can show, under each tag, a strip of items carrying it — the
Subjects list's face strips, for tags. Which items is DERIVED state with
one memory in it: ``tag_representatives`` holds, per tag, up to
`MAX_REPRESENTATIVES` live rows (``refused = 0``) and any number of REFUSED
ones (``refused = 1``, "not this one" — remembered so the pick never comes
back). Every row hangs off the ASSIGNMENT it stands for
(``item_tag_id`` → ``item_tags.id``, ON DELETE CASCADE), which is what makes
"until the tag is removed from the item" true for every writer there is:
an assignment deleted by the ORM, by a Core statement, by a tag's or an
item's own cascade takes its representative row with it, and no call site
has to remember.

THE RULES, each cheap by construction:

* AUTOMATICALLY PICKED WHEN FIRST ASSIGNED (`adopt`): a new ELIGIBLE
  assignment — positive, not pending, not a ranking's score row — becomes a
  representative while its tag has fewer than the cap; with enough already
  there, nothing happens. That is one count per tag per flush, over an
  index on ``(tag_id, refused)``.
* A GAP IS FILLED BY A RANDOM PICK (`settle`): a representative losing the
  tag (its row cascades away), or being refused, leaves the tag short, and
  another random item carrying it is chosen. The pick is an INDEX SEEK, not
  ``ORDER BY random()`` over a 200,000-row tag: a random item id between the
  tag's smallest and largest (two seeks on the covering
  ``(tag_id, negative, item_id)`` index), then the first eligible row at or
  past it (one more seek, a few rows of scan), wrapping to the front when the
  draw lands past the end. Items after a wide gap in the id space are drawn a
  little more often, which is a fine meaning of "random" here.
* THE READ TOPS UP (`for_tags`): the Tags tab's request for a window's
  strips settles those tags first. It is the safety net for the writers the
  flush listener cannot see — a Core delete, a library merged in, a tag
  created by an older build — and it costs nothing on a settled library: a
  tag at the cap is one indexed count, a tag with fewer items than the cap
  one EXISTS that stops after those items.

The flush listener (`Database._collect_representatives` /
`_apply_representatives`) is the ORM half: new eligible rows are adopted,
rows deleted or flipped ineligible (negative, pending) have their tags
settled, rows flipped eligible again are adopted. It runs on every
`Database` session — the API, the importer, the jobs worker, the CLI, a
script — so nothing above has to call anything.

Nothing here is logged: which items stand for a tag is a display choice
about derived data, and a refusal is the same kind of statement as a
dismissed suggestion. The refusal is the one thing a person says, and it
lives until the assignment it is about does.
"""

from __future__ import annotations

import random
from typing import Iterable, Optional

import sqlalchemy as sa
from sqlalchemy import delete, exists, func, insert, select
from sqlalchemy.orm import Session

#: How many items stand for a tag at most.
MAX_REPRESENTATIVES = 8


def _tables():
    """The two tables, imported late — `db` imports this module's caller
    (the flush listeners live on `Database`), so a top-level import the
    other way round would be a cycle."""
    from .db import ItemTag, TagRepresentative
    return ItemTag, TagRepresentative


def _eligible(ItemTag):
    """An assignment that may stand for its tag: positive and agreed on (not
    a machine's pending guess).

    There was a third clause — not a RANKING's derived score row — for as
    long as a ranking wrote rows of its own (rung v31 ended that, v32 took
    the column)."""
    return sa.and_(ItemTag.negative.is_(False), ItemTag.pending.is_(False))


def is_eligible_row(row) -> bool:
    """The same rule read off an ORM object (the flush listener's side)."""
    return not row.negative and not row.pending


def live_counts(s: Session, tag_ids: Iterable[int]) -> dict[int, int]:
    """Per tag, how many LIVE representatives it has now."""
    _ItemTag, Rep = _tables()
    ids = list(dict.fromkeys(int(t) for t in tag_ids))
    if not ids:
        return {}
    out: dict[int, int] = {}
    from .db import chunked
    for chunk in chunked(ids):
        for tid, n in s.execute(
            select(Rep.tag_id, func.count())
            .where(Rep.tag_id.in_(chunk), Rep.refused.is_(False))
            .group_by(Rep.tag_id)
        ).all():
            out[int(tid)] = int(n)
    return out


def adopt(s: Session, rows: Iterable[tuple[int, int, int]]) -> int:
    """New eligible assignments as ``(item_tag_id, tag_id, item_id)``: each
    becomes a representative while its tag is short of the cap and the item
    is not refused for it. One count per tag; nothing random. Returns how
    many were adopted."""
    _ItemTag, Rep = _tables()
    by_tag: dict[int, list[tuple[int, int]]] = {}
    for it_id, tid, iid in rows:
        by_tag.setdefault(int(tid), []).append((int(it_id), int(iid)))
    if not by_tag:
        return 0
    counts = live_counts(s, by_tag)
    added = 0
    for tid, cands in by_tag.items():
        room = MAX_REPRESENTATIVES - counts.get(tid, 0)
        if room <= 0:
            continue
        # A row that is already there (refused, or live from an earlier
        # adopt in this very flush) is not adopted twice.
        have = {int(x) for x in s.execute(
            select(Rep.item_tag_id).where(
                Rep.item_tag_id.in_([c[0] for c in cands]))).scalars().all()}
        take = [c for c in cands if c[0] not in have][:room]
        if take:
            s.execute(insert(Rep), [
                {"item_tag_id": it_id, "tag_id": tid, "item_id": iid,
                 "refused": False} for it_id, iid in take])
            added += len(take)
    return added


def _bounds(s: Session, ItemTag, tag_id: int) -> Optional[tuple[int, int]]:
    """The smallest and largest item id carrying the tag positively — two
    seeks on the covering index."""
    lo = s.execute(select(func.min(ItemTag.item_id)).where(
        ItemTag.tag_id == tag_id, ItemTag.negative.is_(False))).scalar()
    if lo is None:
        return None
    hi = s.execute(select(func.max(ItemTag.item_id)).where(
        ItemTag.tag_id == tag_id, ItemTag.negative.is_(False))).scalar()
    return int(lo), int(hi)


def _pick_one(s: Session, tag_id: int, bounds: tuple[int, int],
              rng: random.Random) -> Optional[tuple[int, int]]:
    """One random eligible assignment of the tag that has no representative
    row (live or refused), as ``(item_tag_id, item_id)`` — the first at or
    past a random item id, wrapping to the front. None when there is none
    left to pick."""
    ItemTag, Rep = _tables()
    lo, hi = bounds
    start = rng.randint(lo, hi)
    for floor in (start, lo):
        row = s.execute(
            select(ItemTag.id, ItemTag.item_id)
            .where(ItemTag.tag_id == tag_id, _eligible(ItemTag),
                   ItemTag.item_id >= floor,
                   ~exists(select(sa.literal(1)).where(
                       Rep.item_tag_id == ItemTag.id)))
            .order_by(ItemTag.item_id)
            .limit(1)
        ).first()
        if row is not None:
            return int(row[0]), int(row[1])
        if floor == lo:
            break
    return None


def claim(s: Session, item_tag_id: int, tag_id: int, item_id: int) -> bool:
    """Make this assignment stand for the tag. True when the row is ours.

    IDEMPOTENT, because two readers can pick the same assignment. Topping
    up happens on the READ path and scrolling a list of tags fires several
    of those at once; each session's `_pick_one` filters against the rows
    it can SEE, so two of them settling the same tag choose the same free
    assignment, and whichever writes second used to break the primary key
    — `UNIQUE constraint failed: tag_representatives.item_tag_id`, a
    traceback in the log per row, for a read that was only meant to fill a
    gap. A row already there is the answer we wanted anyway; it is just
    somebody else's pick. False says exactly that, so nothing counts it as
    gained twice.
    """
    _ItemTag, Rep = _tables()
    done = s.execute(insert(Rep).prefix_with("OR IGNORE").values(
        item_tag_id=int(item_tag_id), tag_id=int(tag_id),
        item_id=int(item_id), refused=False))
    return bool(done.rowcount)


def settle(s: Session, tag_ids: Iterable[int],
           rng: Optional[random.Random] = None) -> dict[int, list[int]]:
    """Fill each tag's representatives up to the cap with random picks.
    Returns, per tag that gained any, the item ids picked. Cheap for a tag
    that is full (one count) or that has nothing more to offer (one seek
    that comes back empty)."""
    ItemTag, Rep = _tables()
    ids = list(dict.fromkeys(int(t) for t in tag_ids))
    if not ids:
        return {}
    rng = rng or random.Random()
    counts = live_counts(s, ids)
    picked: dict[int, list[int]] = {}
    for tid in ids:
        room = MAX_REPRESENTATIVES - counts.get(tid, 0)
        if room <= 0:
            continue
        bounds = _bounds(s, ItemTag, tid)
        if bounds is None:
            continue
        for _ in range(room):
            got = _pick_one(s, tid, bounds, rng)
            if got is None:
                break
            it_id, iid = got
            if claim(s, it_id, tid, iid):
                picked.setdefault(tid, []).append(iid)
    return picked


def drop_live(s: Session, pairs: Iterable[tuple[int, int]]) -> set[int]:
    """Take the LIVE representative row off these ``(tag_id, item_id)``
    pairs — an assignment that stopped being eligible without being
    deleted (flipped negative, or back to pending). A refusal stays: it is
    about the assignment, which is still there. Returns the tags that lost
    one, for `settle`."""
    _ItemTag, Rep = _tables()
    touched: set[int] = set()
    for tid, iid in pairs:
        n = s.execute(delete(Rep).where(
            Rep.tag_id == int(tid), Rep.item_id == int(iid),
            Rep.refused.is_(False))).rowcount
        if n:
            touched.add(int(tid))
    return touched


def refuse(s: Session, tag_id: int, item_id: int) -> bool:
    """"Not this one": the item stops standing for the tag and is never
    picked for it again while it carries the tag. Returns False when the
    item does not carry the tag (nothing to refuse)."""
    ItemTag, Rep = _tables()
    it_id = s.execute(select(ItemTag.id).where(
        ItemTag.tag_id == int(tag_id), ItemTag.item_id == int(item_id)
    )).scalar()
    if it_id is None:
        return False
    s.execute(delete(Rep).where(Rep.item_tag_id == it_id))
    s.execute(insert(Rep).values(item_tag_id=int(it_id), tag_id=int(tag_id),
                                 item_id=int(item_id), refused=True))
    return True


def for_tags(s: Session, tag_ids: Iterable[int],
             top_up: bool = True) -> dict[int, list[int]]:
    """Per tag, its live representatives' item ids (oldest pick first) —
    after topping the short ones up, unless told not to."""
    _ItemTag, Rep = _tables()
    ids = list(dict.fromkeys(int(t) for t in tag_ids))
    if not ids:
        return {}
    if top_up:
        settle(s, ids)
    out: dict[int, list[int]] = {tid: [] for tid in ids}
    from .db import chunked
    for chunk in chunked(ids):
        for tid, iid in s.execute(
            select(Rep.tag_id, Rep.item_id)
            .where(Rep.tag_id.in_(chunk), Rep.refused.is_(False))
            .order_by(Rep.tag_id, Rep.item_tag_id)
        ).all():
            out[int(tid)].append(int(iid))
    return out
