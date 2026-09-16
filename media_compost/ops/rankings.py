"""Rankings — pairwise-comparison axes, and nothing about tags.

**A RANKING ORDERS PICTURES AND TAGS NONE OF THEM** (owner 2026-09, rung
v31). It used to own a tag NAMESPACE (``quality`` → ``quality:0`` …
``quality:9``): the score tags were minted with it, locked against every
catalog verb, and their per-item assignments were DERIVED — a `rebuild`
that refitted the standings and diffed `ItemTag` rows into place. That is
gone, and so are the two switches that only ever gated it (a ranking's
`enabled` and a pool's) and the `prefix` the tags were named after.

What is left is what a ranking always WAS: the JUDGMENTS, which are the
logged, revertible record, and the standings fitted from them
(:func:`standings`, computed on the way out and stored nowhere). Nothing is
materialized, so nothing has to be rebuilt, and search, facets, counts,
training and export see exactly the tags somebody put there.

Writing something onto the pictures is the **Assign ratings** action's
business (`routers/estimate.py`): rules over the standings, written as
ORDINARY assignments through the ordinary door, which is what makes them
somebody's decision rather than a derived row that a refit would silently
rewrite.

A ranking is computed over one or more POOLS (`db.RankingPool`) —
populations with standings of their own under the one range. Membership is
derived from the judgments (a picture joins a pool by being rated in it)
and the first pool is born with the ranking, unnamed. Not-applicable
stays ranking-wide.
"""

from __future__ import annotations

import random
from typing import Optional

from sqlalchemy import delete, func, select, union_all

from .. import rankingmath, tagname
from ..db import (
    Item, Ranking, RankingDismissal, RankingJudgment, RankingPool,
    TrashedItem, chunked,
)
from . import actions
from .context import Ctx
from .errors import Conflict, Invalid, NotFound, Refused

#: "a"/"b" pick a winner, "tie" says the two are about equal (half a win
#: each in the fit), "skip" sets the pair aside without saying anything.
OUTCOMES = ("a", "b", "tie", "skip")


#: The widest range a ranking may mint. 0…100 is the user-facing promise
#: ("percent scores work"); the cap is what stops a typo minting ten
#: thousand tags.
BUCKET_MIN, BUCKET_MAX = 0, 100


def _check_bucket_range(lo: int, hi: int) -> None:
    if lo < BUCKET_MIN or hi > BUCKET_MAX or lo >= hi:
        raise Invalid(
            "the bucket range must run upward within {min}–{max}",
            {"min": BUCKET_MIN, "max": BUCKET_MAX},
            code="ranking_bucket_range",
        )


def by_id(ctx: Ctx, ranking_id: int) -> Ranking:
    row = ctx.session.get(Ranking, ranking_id)
    if row is None:
        raise NotFound("ranking not found", code="ranking_not_found")
    return row


# ---- the catalog --------------------------------------------------------------


def create(ctx: Ctx, *, name: str,
           scope: str = "",
           bucket_lo: int = 0,
           bucket_hi: int = rankingmath.BUCKETS - 1) -> Ranking:
    """Create a ranking. It mints nothing: an axis is judgments and the
    range they are spread over."""
    s = ctx.session
    name = (name or "").strip()
    if not name:
        raise Invalid("a ranking needs a name", code="ranking_name_missing")
    _check_bucket_range(bucket_lo, bucket_hi)
    row = Ranking(name=name,
                  scope=(scope or "").strip(),
                  bucket_lo=bucket_lo, bucket_hi=bucket_hi)
    s.add(row)
    s.flush()
    # Born with its unnamed pool — a ranking always has at least one.
    s.add(RankingPool(ranking_id=row.id, name=""))
    s.flush()
    ctx.log(action=actions.CREATE_RANKING, entity_type="ranking",
            entity_id=row.id, summary="Created the ranking {name}",
            summary_vars={"name": name},
            data={"ranking_id": row.id, "name": name,
                  "scope": row.scope,
                  "bucket_lo": bucket_lo, "bucket_hi": bucket_hi})
    return row


def update(ctx: Ctx, ranking_id: int, *, name: Optional[str] = None,
           scope: Optional[str] = None,
           bucket_lo: Optional[int] = None,
           bucket_hi: Optional[int] = None) -> Ranking:
    """Edit the display name, the scope and the bucket RANGE.

    A range edit costs nothing now: the judgments are untouched and the
    standings are fitted on the way out, so the same ordering simply reads
    against a different scale. It used to re-mint the score tags and refit
    every assignment, which is what made the range feel like a second axis.

    The `prefix` and `enabled` fields are gone with the score tags (rung
    v31); an old event carrying them reverts through what is left."""
    row = by_id(ctx, ranking_id)
    old = {"name": row.name, "scope": row.scope,
           "bucket_lo": row.bucket_lo, "bucket_hi": row.bucket_hi}
    if name is not None:
        name = name.strip()
        if not name:
            raise Invalid("a ranking needs a name", code="ranking_name_missing")
        row.name = name
    if scope is not None:
        row.scope = scope.strip()
    if bucket_lo is not None or bucket_hi is not None:
        lo = row.bucket_lo if bucket_lo is None else int(bucket_lo)
        hi = row.bucket_hi if bucket_hi is None else int(bucket_hi)
        if (lo, hi) != (row.bucket_lo, row.bucket_hi):
            _check_bucket_range(lo, hi)
            row.bucket_lo, row.bucket_hi = lo, hi
    ctx.session.flush()
    ctx.log(action=actions.EDIT_RANKING, entity_type="ranking",
            entity_id=row.id, summary="Edited the ranking {name}",
            summary_vars={"name": row.name},
            data={"ranking_id": row.id, "old": old,
                  "new": {"name": row.name,
                          "scope": row.scope,
                          "bucket_lo": row.bucket_lo,
                          "bucket_hi": row.bucket_hi}})
    return row


def delete_ranking(ctx: Ctx, ranking_id: int) -> None:
    """Delete a ranking, its judgments and its dismissals.

    NOT revertible (`actions.NOT_REVERTIBLE`): the judgments cascade with the
    row and a snapshot of thousands of them in one event is not a promise the
    log should make — which is why the UI confirms first. Tags are not
    involved any more: what a rating session was spent on is whatever the
    Assign-ratings action wrote, which is somebody's own assignment and
    stays exactly where it is."""
    s = ctx.session
    row = by_id(ctx, ranking_id)
    name = row.name
    ctx.log(action=actions.DELETE_RANKING, entity_type="ranking",
            entity_id=row.id, summary="Deleted the ranking {name}",
            summary_vars={"name": name},
            data={"ranking_id": row.id, "name": row.name})
    s.delete(row)
    s.flush()


# ---- pools ------------------------------------------------------------------


def pools_of(session, ranking) -> list[RankingPool]:
    """The ranking's pools in their ORDER (`position`, then id — a fresh
    library's unnamed one leads until somebody drags)."""
    ranking_id = ranking.id if isinstance(ranking, Ranking) else ranking
    return list(session.execute(
        select(RankingPool)
        .where(RankingPool.ranking_id == ranking_id)
        .order_by(RankingPool.position, RankingPool.id)).scalars().all())


def default_pool(session, ranking) -> Optional[RankingPool]:
    """The pool a caller that names none means: the unnamed one, else
    the oldest (somebody renamed it), else None — a `Ranking` row inserted
    directly (a test, a script) has none until something makes one."""
    rows = pools_of(session, ranking)
    for row in rows:
        if row.name == "":
            return row
    return rows[0] if rows else None


def pool_by_id(ctx: Ctx, ranking: Ranking, pool_id: int) -> RankingPool:
    """A pool of THIS ranking — one of another's is not found here."""
    row = ctx.session.get(RankingPool, pool_id)
    if row is None or row.ranking_id != ranking.id:
        raise NotFound("pool not found", code="ranking_pool_not_found")
    return row


def resolve_pool_ids(ctx: Ctx, ranking: Ranking,
                       pool_ids) -> list[int]:
    """What a request's ``pool_ids`` means: NOTHING named is the default
    pool (what every caller before pools existed meant), else each id
    checked to be the ranking's own, de-duplicated in the order given."""
    if not pool_ids:
        row = default_pool(ctx.session, ranking)
        return [row.id] if row is not None else []
    out: list[int] = []
    for lid in pool_ids:
        lid = int(lid)
        pool_by_id(ctx, ranking, lid)
        if lid not in out:
            out.append(lid)
    return out


def _check_pool_name(ctx: Ctx, row: Ranking, name: str,
                       exclude_id: Optional[int] = None) -> str:
    name = (name or "").strip()
    if not name:
        raise Invalid("a pool needs a name", code="ranking_pool_name_missing")
    dup = ctx.session.execute(select(RankingPool).where(
        RankingPool.ranking_id == row.id,
        RankingPool.name == name)).scalars().first()
    if dup is not None and dup.id != exclude_id:
        raise Conflict(
            "the ranking “{ranking}” already has a pool named “{name}”",
            {"ranking": row.name, "name": name},
            code="ranking_pool_name_taken")
    return name


def create_pool(ctx: Ctx, ranking_id: int, name: str) -> RankingPool:
    """Add a pool to a ranking. Empty until something is rated in it."""
    s = ctx.session
    row = by_id(ctx, ranking_id)
    name = _check_pool_name(ctx, row, name)
    # Appended: after every pool the ranking already lists.
    have = pools_of(s, row)
    pool = RankingPool(ranking_id=row.id, name=name,
                           position=(have[-1].position + 1) if have else 0)
    s.add(pool)
    s.flush()
    ctx.log(action=actions.CREATE_RANKING_POOL, entity_type="ranking",
            entity_id=row.id, summary="Added the pool {name} to {ranking}",
            summary_vars={"name": name, "ranking": row.name},
            data={"ranking_id": row.id, "pool_id": pool.id,
                  "name": name})
    return pool


def rename_pool(ctx: Ctx, ranking_id: int, pool_id: int,
                  name: str) -> RankingPool:
    s = ctx.session
    row = by_id(ctx, ranking_id)
    pool = pool_by_id(ctx, row, pool_id)
    name = _check_pool_name(ctx, row, name, exclude_id=pool.id)
    old = pool.name
    if name == old:
        return pool
    pool.name = name
    s.flush()
    ctx.log(action=actions.EDIT_RANKING_POOL, entity_type="ranking",
            entity_id=row.id,
            summary="Renamed a pool of {ranking} to {name}",
            summary_vars={"name": name, "ranking": row.name},
            data={"ranking_id": row.id, "pool_id": pool.id,
                  "old": old, "new": name})
    return pool


def delete_pool(ctx: Ctx, ranking_id: int, pool_id: int) -> int:
    """Delete a pool and every judgment made in it, then refit.

    NOT revertible (`actions.NOT_REVERTIBLE`), for `delete_ranking`'s
    reason: the judgments cascade with the row. Logged BEFORE the delete
    with how many go, so the UI can say so. The last pool stays — a
    ranking always has one; deleting the ranking is how that one goes."""
    s = ctx.session
    row = by_id(ctx, ranking_id)
    pool = pool_by_id(ctx, row, pool_id)
    if len(pools_of(s, row)) <= 1:
        raise Refused(
            "the ranking “{ranking}” keeps its last pool — delete the "
            "ranking instead",
            {"ranking": row.name}, code="ranking_pool_last")
    n = int(s.execute(
        select(func.count()).select_from(RankingJudgment)
        .where(RankingJudgment.pool_id == pool.id)).scalar_one())
    ctx.log(action=actions.DELETE_RANKING_POOL, entity_type="ranking",
            entity_id=row.id,
            summary="Deleted the pool {name} of {ranking} ({n} comparisons)",
            summary_vars={"name": pool.name, "n": str(n),
                          "ranking": row.name},
            data={"ranking_id": row.id, "pool_id": pool.id,
                  "name": pool.name, "judgments": n})
    s.delete(pool)
    # The judgments cascade at the DB (foreign keys are on per connection).
    s.flush()
    return n


def reorder_pools(ctx: Ctx, ranking_id: int, pool_ids) -> None:
    """The dialog's drag-reorder: the ranking's pools take positions in
    the order given — which must name EVERY pool of the ranking exactly
    once, or the list would hold an order nobody asked for. One event, and
    the revert restores every old position; an order that moved nothing
    logs nothing (the `reorder_appearances` shape)."""
    s = ctx.session
    row = by_id(ctx, ranking_id)
    rows = {lg.id: lg for lg in pools_of(s, row)}
    wanted = [int(i) for i in pool_ids]
    if sorted(wanted) != sorted(rows) or len(set(wanted)) != len(wanted):
        raise Invalid("the order must name each pool of the ranking once",
                      code="ranking_pool_order")
    old_order = [lg.id for lg in pools_of(s, row)]
    old_pos = {lg.id: lg.position for lg in rows.values()}
    for idx, lid in enumerate(wanted):
        rows[lid].position = idx
    s.flush()
    if [lg.id for lg in pools_of(s, row)] == old_order:
        return
    ctx.log(action=actions.REORDER_RANKING_POOLS, entity_type="ranking",
            entity_id=row.id, summary="Reordered the pools of {ranking}",
            summary_vars={"ranking": row.name},
            data={"ranking_id": row.id,
                  "old_positions": {str(k): v for k, v in old_pos.items()},
                  "ids": wanted})


def pool_counts_of(session, ranking_ids: list[int]
                     ) -> dict[int, tuple[int, int]]:
    """Per POOL: (judgments, distinct items either side) — the list's and
    the detail's per-pool figures, off the evidence like `counts_of`."""
    if not ranking_ids:
        return {}
    out: dict[int, tuple[int, int]] = {}
    for lid, n in session.execute(
            select(RankingJudgment.pool_id, func.count())
            .where(RankingJudgment.ranking_id.in_(ranking_ids))
            .group_by(RankingJudgment.pool_id)).all():
        out[lid] = (n, 0)
    sides = union_all(
        select(RankingJudgment.pool_id.label("lid"),
               RankingJudgment.a_item_id.label("iid"))
        .where(RankingJudgment.ranking_id.in_(ranking_ids)),
        select(RankingJudgment.pool_id, RankingJudgment.b_item_id)
        .where(RankingJudgment.ranking_id.in_(ranking_ids)),
    ).subquery()
    for lid, n in session.execute(
            select(sides.c.lid, func.count(func.distinct(sides.c.iid)))
            .group_by(sides.c.lid)).all():
        out[lid] = (out.get(lid, (0, 0))[0], n)
    return out


def pool_evidence_of(session, ranking_ids: list[int]
                       ) -> dict[int, tuple[int, int]]:
    """Per POOL: (comparisons the fit rests on, pictures they place) —
    exactly the two numbers `rankingmath.enough_comparisons` weighs, as two
    aggregates rather than a fit per pool.

    NOT `pool_counts_of`, which counts every judgment and every item
    either side of one: a SKIP recorded that the question was set aside and
    is evidence of nothing, and a NOT-APPLICABLE picture leaves the
    standings, so neither belongs in a sum that says how settled a pool
    is. That is also why the numbers are taken here rather than off a fit:
    the rankings LIST asks for every pool of every axis, and a fit per
    pool is exactly the shape that turns a list endpoint into a scan of
    the library (`prefilter`'s lesson, one subsystem along).
    `tests/ui/test_rankings.py` holds these counts to what the FIT sees,
    which is what keeps the two ways of gathering them one rule.
    """
    if not ranking_ids:
        return {}
    counted = RankingJudgment.outcome.in_(("a", "b", "tie"))
    out: dict[int, tuple[int, int]] = {}
    for lid, n in session.execute(
            select(RankingJudgment.pool_id, func.count())
            .where(RankingJudgment.ranking_id.in_(ranking_ids), counted)
            .group_by(RankingJudgment.pool_id)).all():
        out[lid] = (n, 0)
    sides = union_all(
        select(RankingJudgment.pool_id.label("lid"),
               RankingJudgment.ranking_id.label("rid"),
               RankingJudgment.a_item_id.label("iid"))
        .where(RankingJudgment.ranking_id.in_(ranking_ids), counted),
        select(RankingJudgment.pool_id, RankingJudgment.ranking_id,
               RankingJudgment.b_item_id)
        .where(RankingJudgment.ranking_id.in_(ranking_ids), counted),
    ).subquery()
    for lid, n in session.execute(
            select(sides.c.lid, func.count(func.distinct(sides.c.iid)))
            .where(~select(RankingDismissal.id).where(
                RankingDismissal.ranking_id == sides.c.rid,
                RankingDismissal.item_id == sides.c.iid).exists())
            .group_by(sides.c.lid)).all():
        out[lid] = (out.get(lid, (0, 0))[0], n)
    return out


def settled_pools(session, ranking_ids: list[int]) -> dict[int, bool]:
    """Which pools' comparisons can order their pictures at all — the API
    field the detail says "not enough comparisons yet" from. A pool nobody
    has judged is not settled: there is nothing to order."""
    return {lid: bool(scored)
            and rankingmath.enough_comparisons(comparisons, scored)
            for lid, (comparisons, scored)
            in pool_evidence_of(session, ranking_ids).items()}


# ---- judgments ----------------------------------------------------------------


def judge(ctx: Ctx, ranking_id: int, a_item_id: int, b_item_id: int,
          outcome: str, pool_ids=None) -> list[RankingJudgment]:
    """Record one comparison — in EVERY pool named (one row and one event
    per pool, so each reverts on its own and the overlay's U reverts the
    fan), or in the default pool when none is."""
    s = ctx.session
    row = by_id(ctx, ranking_id)
    if outcome not in OUTCOMES:
        raise Invalid("unknown outcome", code="ranking_outcome_unknown")
    if a_item_id == b_item_id:
        raise Invalid("a pair needs two different pictures",
                      code="ranking_pair_same")
    for iid in (a_item_id, b_item_id):
        if s.get(Item, iid) is None:
            raise NotFound("item not found", code="item_not_found")
    pools = resolve_pool_ids(ctx, row, pool_ids)
    if not pools:
        raise Refused("the ranking “{ranking}” has no pool to record into",
                      {"ranking": row.name},
                      code="ranking_pool_none")
    out: list[RankingJudgment] = []
    for lid in pools:
        j = RankingJudgment(ranking_id=row.id, pool_id=lid,
                            a_item_id=a_item_id, b_item_id=b_item_id,
                            outcome=outcome, username=ctx.username or "")
        s.add(j)
        s.flush()
        # The judgment rides item A's sidecar (the pair, said once).
        ev = ctx.log(action=actions.JUDGE_RANKING, entity_type="ranking",
                     entity_id=row.id,
                     summary=("Set a pair aside on {name}" if outcome == "skip"
                              else "Called two pictures about equal on {name}"
                              if outcome == "tie"
                              else "Compared two pictures on {name}"),
                     summary_vars={"name": row.name},
                     data={"judgment_id": j.id, "ranking_id": row.id,
                           "pool_id": lid,
                           "a_item_id": a_item_id, "b_item_id": b_item_id,
                           "outcome": outcome})
        s.flush()
        # The event id rides back so the rating overlay's U can revert
        # exactly this judgment through the ordinary history machinery —
        # which is also what refits the scores.
        j.event_id = ev.id  # a transient attribute, not a column
        out.append(j)
    return out


# ---- the three verbs about PICTURES, each over any number of them -------------
#
# One picture, a selection, or everything in a view: the sidebar offers all
# three of these at all three sizes, so they take a LIST. What is done once
# per batch is the LOOKING UP — which ids exist, which are already set aside,
# which judgments are about to go — and what stays one per picture is the
# EVENT: the undo bar puts back exactly what it took, and a revert written
# against a list would have to be a second kind of revert for the same fact.
# (`ops/items.hide` is the same shape for the same reason.)


def _known(s, item_ids: list[int]) -> list[int]:
    """The named ids, deduped and in order — raising on one the library does
    not have, as the single-item verbs always did. Over a view the ids come
    from the view, so this is a guard against a caller naming a picture that
    has been deleted since it read the grid."""
    ids = [int(i) for i in dict.fromkeys(item_ids)]
    if not ids:
        return []
    have = set()
    for chunk in chunked(ids):
        have.update(int(i) for i in s.execute(
            select(Item.id).where(Item.id.in_(chunk))).scalars().all())
    if len(have) != len(ids):
        raise NotFound("item not found", code="item_not_found")
    return ids


def dismiss(ctx: Ctx, ranking_id: int, item_ids: list[int]) -> int:
    """Set pictures aside on this ranking: their comparisons stay, they leave
    the fit. Answers how many CHANGED — one already set aside is skipped."""
    s = ctx.session
    row = by_id(ctx, ranking_id)
    ids = _known(s, item_ids)
    if not ids:
        return 0
    already: set[int] = set()
    for chunk in chunked(ids):
        already.update(int(i) for i in s.execute(
            select(RankingDismissal.item_id).where(
                RankingDismissal.ranking_id == row.id,
                RankingDismissal.item_id.in_(chunk))).scalars().all())
    wrote = [i for i in ids if i not in already]
    for iid in wrote:
        s.add(RankingDismissal(ranking_id=row.id, item_id=iid,
                               username=ctx.username or ""))
    if wrote:
        s.flush()
    for iid in wrote:
        ctx.log(action=actions.DISMISS_RANKING_ITEM, entity_type="ranking",
                entity_id=row.id,
                summary="Marked a picture as not applicable to {name}",
                summary_vars={"name": row.name},
                data={"ranking_id": row.id, "item_id": iid})
    return len(wrote)


def undismiss(ctx: Ctx, ranking_id: int, item_ids: list[int]) -> int:
    """Put set-aside pictures back in the fit. Answers how many CHANGED."""
    s = ctx.session
    row = by_id(ctx, ranking_id)
    ids = _known(s, item_ids)
    if not ids:
        return 0
    # WHICH ONES WERE ACTUALLY SET ASIDE, before the delete: the event is what
    # the undo bar reverts, and one for a picture that was never dismissed
    # would offer to take back something nobody did.
    held: set[int] = set()
    for chunk in chunked(ids):
        held.update(int(i) for i in s.execute(
            select(RankingDismissal.item_id).where(
                RankingDismissal.ranking_id == row.id,
                RankingDismissal.item_id.in_(chunk))).scalars().all())
    gone = [i for i in ids if i in held]
    for chunk in chunked(gone):
        s.execute(delete(RankingDismissal).where(
            RankingDismissal.ranking_id == row.id,
            RankingDismissal.item_id.in_(chunk)))
    if gone:
        s.flush()
    for iid in gone:
        ctx.log(action=actions.UNDISMISS_RANKING_ITEM, entity_type="ranking",
                entity_id=row.id,
                summary="Made a picture applicable to {name} again",
                summary_vars={"name": row.name},
                data={"ranking_id": row.id, "item_id": iid})
    return len(gone)


def remove_item(ctx: Ctx, ranking_id: int, item_ids: list[int]) -> int:
    """Take pictures out of a ranking: delete every judgment they were part
    of and refit — the standings are a fit on the evidence, so the only
    honest removal is removing the evidence.

    Logged with a snapshot of the deleted judgments, so the revert can put
    them back (and refit again) — which is what lets the sidebar's undo bar
    offer the removal back like any other. A judgment between two of the
    named pictures is deleted ONCE and rides the first of them.

    Answers how many JUDGMENTS went, not how many pictures: it is the number
    the question asks first ("its 12 comparisons are deleted")."""
    s = ctx.session
    row = by_id(ctx, ranking_id)
    ids = _known(s, item_ids)
    if not ids:
        return 0
    want = set(ids)
    rows: list = []
    for chunk in chunked(ids):
        rows.extend(s.execute(
            select(RankingJudgment)
            .where(RankingJudgment.ranking_id == row.id,
                   RankingJudgment.a_item_id.in_(chunk)
                   | RankingJudgment.b_item_id.in_(chunk))
            .order_by(RankingJudgment.id)).scalars().all())
    by_item: dict[int, list] = {}
    seen: set[int] = set()
    for j in rows:
        if j.id in seen:
            continue          # a pair of two named pictures, met twice
        seen.add(j.id)
        owner = j.a_item_id if j.a_item_id in want else j.b_item_id
        by_item.setdefault(int(owner), []).append(j)
    if not seen:
        return 0
    for iid in ids:
        gone = by_item.get(iid) or []
        if not gone:
            continue
        snapshot = [{"a_item_id": j.a_item_id, "b_item_id": j.b_item_id,
                     "outcome": j.outcome, "username": j.username,
                     "pool_id": j.pool_id}
                    for j in gone]
        for j in gone:
            s.delete(j)
        s.flush()
        ctx.log(action=actions.REMOVE_RANKING_ITEM, entity_type="ranking",
                entity_id=row.id,
                summary="Removed a picture from {name} ({n} comparisons)",
                summary_vars={"name": row.name,
                              "n": str(len(gone))},
                data={"ranking_id": row.id, "item_id": iid,
                      "judgments": snapshot})
    return len(seen)


# ---- the standings ------------------------------------------------------------


def _pool_clause(pool_ids):
    """The evidence of these pools only; None means the whole ranking."""
    if pool_ids is None:
        return True
    return RankingJudgment.pool_id.in_([int(i) for i in pool_ids])


def decisive_pairs(session, ranking,
                   pool_ids=None) -> list[tuple[int, int]]:
    """(winner, loser) item pairs — the fit's decisive half. Skips are
    pair-selector state, not evidence; ties are `tie_pairs`. ``pool_ids``
    narrows to those pools' judgments; None is every pool."""
    ranking_id = ranking.id if isinstance(ranking, Ranking) else ranking
    rows = session.execute(
        select(RankingJudgment.a_item_id, RankingJudgment.b_item_id,
               RankingJudgment.outcome)
        .where(RankingJudgment.ranking_id == ranking_id,
               _pool_clause(pool_ids),
               RankingJudgment.outcome.in_(("a", "b")))
        .order_by(RankingJudgment.id)
    ).all()
    return [(a, b) if outcome == "a" else (b, a)
            for a, b, outcome in rows]


def tie_pairs(session, ranking, pool_ids=None) -> list[tuple[int, int]]:
    """The "about equal" pairs — evidence pulling two items TOGETHER, which
    the fit weighs as half a win each."""
    ranking_id = ranking.id if isinstance(ranking, Ranking) else ranking
    return [tuple(r) for r in session.execute(
        select(RankingJudgment.a_item_id, RankingJudgment.b_item_id)
        .where(RankingJudgment.ranking_id == ranking_id,
               _pool_clause(pool_ids),
               RankingJudgment.outcome == "tie")
        .order_by(RankingJudgment.id)
    ).all()]


def dismissed_ids(session, ranking) -> set[int]:
    """The dismissed items."""
    ranking_id = ranking.id if isinstance(ranking, Ranking) else ranking
    return set(session.execute(
        select(RankingDismissal.item_id)
        .where(RankingDismissal.ranking_id == ranking_id)
    ).scalars().all())


def dismissed_counts_of(session, ranking_ids: list[int]) -> dict[int, int]:
    """How many pictures each ranking has set aside — for the sidebar's own
    "Not applicable" row, which is shown only where there is one.

    Counted like `item_counts_of` and for the same reason: a trashed or
    hidden picture is out of the ordinary listing, so a row promising three
    must not open a grid of one.
    """
    if not ranking_ids:
        return {}
    rows = session.execute(
        select(RankingDismissal.ranking_id, func.count())
        .join(Item, Item.id == RankingDismissal.item_id)
        .where(RankingDismissal.ranking_id.in_(ranking_ids),
               ~select(TrashedItem.item_id)
               .where(TrashedItem.item_id == RankingDismissal.item_id).exists(),
               Item.hidden.is_(False))
        .group_by(RankingDismissal.ranking_id)).all()
    return {rid: n for rid, n in rows}


def standings(session, ranking: Ranking,
              pool_ids=None) -> dict[int, float]:
    """The current fit over items, minus the not-applicable ones — of the
    named pools, or of every judgment the ranking holds."""
    return _fitted(session, ranking, pool_ids)[1]


def item_judgment_count(session, ranking: Ranking, item_id: int) -> int:
    """How many DECISIVE or tie judgments this picture has been part of on
    this axis — what its standing is made of. A skip says nothing, so it is
    not counted: the number is there to answer "why is this a 3", and a
    passed-over pair is not part of that answer."""
    return int(session.execute(
        select(func.count()).select_from(RankingJudgment).where(
            RankingJudgment.ranking_id == ranking.id,
            RankingJudgment.outcome.in_(("a", "b", "tie")),
            (RankingJudgment.a_item_id == item_id)
            | (RankingJudgment.b_item_id == item_id),
        )).scalar_one() or 0)


def is_dismissed(session, ranking: Ranking, item_id: int) -> bool:
    """Set aside as not applicable to this axis — ranking-wide, never per
    pool."""
    return session.execute(
        select(RankingDismissal.id).where(
            RankingDismissal.ranking_id == ranking.id,
            RankingDismissal.item_id == item_id,
        ).limit(1)).first() is not None


def placed_in_order(session, ranking: Ranking,
                    pool_ids=None) -> list[tuple[int, int]]:
    """``(item_id, bucket)`` for everything this ranking has placed, BEST
    FIRST — what the library view is scoped to and ordered by.

    Membership is what a judgment says: an item with at least one decisive or
    tie judgment in the named pools, less the ranking's dismissals (which
    are ranking-wide, not per pool). A "skip" is not evidence and places
    nothing, which is why this reads `standings` and not `judged_ids`.

    THE TIE-BREAK IS `_summary`'S, deliberately: `buckets()` ranks by
    (score, id) and the list somebody reads has to be dealt in the same total
    order, or a score tie shows 3, 2, 3 down the page. Two surfaces ordering
    one fit two ways is the same bug in two places.
    """
    from media_compost import rankingmath

    scores = standings(session, ranking, pool_ids)
    if not scores:
        return []
    lo, hi = ranking.bucket_lo, ranking.bucket_hi
    want = rankingmath.buckets(scores, hi - lo + 1)
    order = sorted(scores, key=lambda u: (-scores.get(u, 0.0), -u))
    return [(u, lo + want[u]) for u in order if u in want]


def _fitted(session, ranking: Ranking,
            pool_ids=None) -> tuple[int, dict[int, float]]:
    """(how many comparisons the fit rests on, the standings) — one pass, so
    a caller that has to weigh the evidence does not pay for the pairs
    twice. "Skip" answers are in neither list and count as neither: they
    recorded that the question was set aside."""
    pairs = decisive_pairs(session, ranking, pool_ids)
    ties = tie_pairs(session, ranking, pool_ids)
    scores = rankingmath.fit(pairs, ties=ties)
    gone = dismissed_ids(session, ranking)
    return (len(pairs) + len(ties),
            {i: v for i, v in scores.items() if i not in gone})


# ---- pair selection -----------------------------------------------------------


def next_pair(session, ranking: Ranking, pool: list[int],
              recent: list[list[int]] | None = None,
              priority: list[int] | None = None,
              pool_ids=None) -> Optional[tuple[int, int]]:
    """The next pair to show, from ``pool`` (the session's already-resolved
    scope), or None. ``recent`` is what the session just showed — avoided so
    the same two pictures do not bounce straight back. ``priority`` items
    (the grid selection a session was opened over) are compared FIRST, each
    against partners from the whole pool — never a narrowing of it.
    ``pool_ids`` says whose evidence the least-judged ordering and the
    standings read — the session's picked pools."""
    gone = dismissed_ids(session, ranking)
    candidates = [i for i in pool if i not in gone]
    prio = set(candidates) & set(int(i) for i in (priority or []))
    avoid: set[tuple[int, int]] = set()
    skips = session.execute(
        select(RankingJudgment.a_item_id, RankingJudgment.b_item_id)
        .where(RankingJudgment.ranking_id == ranking.id,
               _pool_clause(pool_ids),
               RankingJudgment.outcome == "skip")).all()
    for a, b in skips:
        avoid.add((a, b) if a <= b else (b, a))
    for pair in recent or []:
        if len(pair) == 2:
            a, b = int(pair[0]), int(pair[1])
            avoid.add((a, b) if a <= b else (b, a))
    pairs = decisive_pairs(session, ranking, pool_ids)
    ties = tie_pairs(session, ranking, pool_ids)
    # A tie answered the question as much as a pick did — it counts toward
    # "least judged" and feeds the fit; only skips stay non-evidence.
    return rankingmath.pick_pair(
        candidates, rankingmath.judged_counts(pairs + ties),
        rankingmath.fit(pairs, ties=ties), avoid, random.Random(),
        priority=prio)


def judged_ids(session, ranking: Ranking, pool_ids=None) -> set[int]:
    """Every item this ranking has a judgment about, either side (of the
    named pools, or of all).

    What the pair pick has to see whatever else it looks at: the items that
    carry the evidence are the ones the least-judged ordering and the
    nearest-standing partner are about, and there are two of them per
    judgment however big the pool is.
    """
    rows = session.execute(
        select(RankingJudgment.a_item_id, RankingJudgment.b_item_id)
        .where(RankingJudgment.ranking_id == ranking.id,
               _pool_clause(pool_ids))).all()
    out: set[int] = set()
    for a, b in rows:
        out.add(a)
        out.add(b)
    return out


def counts_of(session, ranking_ids: list[int]) -> dict[int, int]:
    """Judgments per ranking, for the list."""
    if not ranking_ids:
        return {}
    rows = session.execute(
        select(RankingJudgment.ranking_id, func.count())
        .where(RankingJudgment.ranking_id.in_(ranking_ids))
        .group_by(RankingJudgment.ranking_id)).all()
    return {rid: n for rid, n in rows}


def item_counts_of(session, ranking_ids: list[int]) -> dict[int, int]:
    """DISTINCT items each ranking has PLACED.

    Which is what the docstring always said and the query did not: it counted
    every item a judgment NAMED, and two kinds of judgment name an item
    without placing it — a "skip" is not evidence, and a dismissal ("not
    applicable") takes the item back out of the fit. So the number ran ahead
    of the standings, and once a ranking became a VIEW of the library the gap
    was on screen: a sidebar row saying 8 opening a grid of 5.

    Counted off the judgments rather than off any tags, which is what a
    ranking has instead of tags of its own (rung v31).
    """
    if not ranking_ids:
        return {}
    decisive = RankingJudgment.outcome.in_(("a", "b", "tie"))
    sides = union_all(
        select(RankingJudgment.ranking_id.label("rid"),
               RankingJudgment.a_item_id.label("iid"))
        .where(RankingJudgment.ranking_id.in_(ranking_ids), decisive),
        select(RankingJudgment.ranking_id, RankingJudgment.b_item_id)
        .where(RankingJudgment.ranking_id.in_(ranking_ids), decisive),
    ).subquery()
    gone = select(RankingDismissal.item_id).where(
        RankingDismissal.ranking_id == sides.c.rid)
    # AND NOT WHAT THE LIBRARY IS NOT SHOWING. This number is a sidebar
    # badge, and every other badge in that column counts the ordinary
    # listing — a trashed or hidden picture is out of All Items, out of
    # Untagged, out of Pending, and it is out of the ranking's own view too
    # (the scope carries the standard exclusions like any other). A badge
    # that counted them promised a grid it would not deliver.
    #
    # The judgments are UNTOUCHED by this: restore the picture and it is
    # placed again, at the standing its comparisons always said.
    from ..db import TrashedItem

    trashed = select(TrashedItem.item_id).where(
        TrashedItem.item_id == sides.c.iid)
    rows = session.execute(
        select(sides.c.rid, func.count(func.distinct(sides.c.iid)))
        .join(Item, Item.id == sides.c.iid)
        .where(~sides.c.iid.in_(gone), ~trashed.exists(),
               Item.hidden.is_(False))
        .group_by(sides.c.rid)).all()
    return {rid: n for rid, n in rows}
