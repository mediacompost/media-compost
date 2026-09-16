"""Rankings: pairwise-comparison axes and the rating overlay's endpoints.

The judgments and the axes are `ops/rankings`'s; what this router owns is the
POOL — which pictures a rating session draws its pairs from. That is the
intersection of the session's own scope (the search request the overlay
sends, exactly as every whole-view write sends one, or an explicit
selection) with the ranking's stored scope, resolved through the same
`search_filtered` the grid pages through so "the pictures you were looking
at" cannot drift from what the grid showed.

`/pair` is a read-only POST and is named in `build.READ_ONLY_POSTS` — left
out, the stale-page guard would 409 it and the overlay would sit on a
spinner, the exact failure `/api/items/query` already cost once.
"""

from __future__ import annotations

import random
from typing import Optional

from dataclasses import dataclass, field

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from media_compost.db import (
    File, Item, Ranking, RankingPool, Sequence, SequenceItem)
from media_compost.ops import Ctx, rankings as ops_rankings, search
from media_compost.prefilter import admitted
from media_compost.ops.errors import Invalid, NotFound
from media_compost.querystring import try_parse
from media_compost.resolve import Resolver

from .. import viewscope
from ..deps import Library, get_ctx, get_library, get_session
from ..schemas import (
    ItemSearchRequest,
    RankingBucketOut,
    RankingCreate,
    RankingDetailOut,
    RankingItemStanding,
    RankingDismissIn,
    RankingItemRef,
    RankingItemsIn,
    RankingItemsOut,
    RankingJudgeIn,
    RankingPoolCreate,
    RankingPoolDetailOut,
    RankingPoolOrder,
    RankingPoolRow,
    RankingPoolUpdate,
    RankingPairOut,
    RankingPairRequest,
    RankingSummaryOut,
    RankingRow,
    RankingUpdate,
)
from .items import _thumb_token

router = APIRouter(prefix="/api/rankings", tags=["rankings"])

#: How many sample thumbnails a detail bucket carries.
_BUCKET_SAMPLES = 8


def _member_refs(s: Session, containers: list[Item]) -> dict[int, list[RankingItemRef]]:
    """For sequence containers, light refs for every member in reading order —
    what lets a rating card flip through the book it is judging."""
    if not containers:
        return {}
    seq_by_item = {iid: sid for sid, iid in s.execute(
        select(Sequence.id, Sequence.item_id).where(
            Sequence.item_id.in_([c.id for c in containers]))).all()
        if iid is not None}
    if not seq_by_item:
        return {}
    rows = s.execute(
        select(SequenceItem.sequence_id, SequenceItem.item_id,
               SequenceItem.position)
        .where(SequenceItem.sequence_id.in_(list(seq_by_item.values())))
    ).all()
    order: dict[int, list[int]] = {}
    for sid, iid, pos in sorted(rows, key=lambda r: (r[0], r[2])):
        # Distinct items in first-occurrence order (a repeated member is one
        # page), the mosaic's own rule.
        lst = order.setdefault(sid, [])
        if iid not in lst:
            lst.append(iid)
    needed = sorted({iid for lst in order.values() for iid in lst})
    refs = _refs(s, needed, members=False)
    return {c.id: [refs[iid] for iid in order.get(seq_by_item.get(c.id, -1), [])
                   if iid in refs]
            for c in containers}


def _refs(s: Session, item_ids: list[int], *,
          members: bool = True) -> dict[int, RankingItemRef]:
    """Card/strip references for a set of items, in two bulk reads."""
    if not item_ids:
        return {}
    items = {i.id: i for i in s.execute(
        select(Item).where(Item.id.in_(item_ids))).scalars().all()}
    files = {f.id: f for f in s.execute(
        select(File).where(File.id.in_(
            [i.active_file_id for i in items.values() if i.active_file_id]
        ))).scalars().all()}
    by_container = _member_refs(
        s, [i for i in items.values() if i.kind == "sequence"]
    ) if members else {}
    out: dict[int, RankingItemRef] = {}
    for iid, item in items.items():
        active = files.get(item.active_file_id)
        out[iid] = RankingItemRef(
            item_id=iid, uid=item.uid, name=item.name or "",
            kind=item.kind,
            file_id=item.active_file_id,
            thumb_token=_thumb_token(active),
            width=active.width or 0 if active else 0,
            height=active.height or 0 if active else 0,
            # On the FILE, like every other display fact about the picture.
            rotation=int(active.rotation or 0) if active else 0,
            members=by_container.get(iid, []),
        )
    return out


def _search(s: Session, lib: Library, query,
            extra: Optional[ItemSearchRequest], res: Resolver):
    """One search, described as SQL — `search_filtered` with this router's
    arguments filled in. Nothing is materialized here; what the caller does
    with the `CandidateSet` decides whether anything is."""
    scope = search.scope_of(extra) if extra else dict(groups="", ungrouped=False)
    # NEVER THE TRASH, whatever the view behind the session was showing.
    #
    # AND NEVER A RANKING SCOPE, which matters here more than the trash does:
    # a session started from a view scoped to a ranking would take as its pool
    # exactly the items that ranking has ALREADY PLACED, so it could never
    # offer an unplaced picture and would simply run out of pairs with the
    # library full of them. The ranking's own scope is the pool; the view's
    # narrowing of it is a narrowing, not a replacement.
    scope = {**scope, "trash": False, "ranking": None, "ranking_pool": None}
    return search.search_filtered(s, **scope, query=query, resolver=res)


def _scope_ids(s: Session, lib: Library, ranking: Ranking,
               body: Optional[ItemSearchRequest]) -> list[int]:
    """The pool: the ranking's own scope, cut down by the session's.

    Everything resolves through `search_filtered` — the one search there is.
    Any kind rates (a film and a chapter answer a quality question as well as
    a picture does); the session's own kind filter is honoured, so rating
    from the Videos category rates videos.

    THE WHOLE LIST, which is what the summary reads and what an exhausted
    pick falls back to. The pair endpoint does not go through here — see
    `_Pool`, which answers "how many" and "a few at random" in SQL.
    """
    res = Resolver(s)

    def resolve(query, extra: Optional[ItemSearchRequest]) -> set[int]:
        base = _search(s, lib, query, extra, res)
        if base.residue is None:
            return set(s.execute(base.ids_select()).scalars().all())
        return set(base.matched_ids(s, res))

    ids = resolve(body.query if body else None, body)
    # `body.items` deliberately does NOT narrow here any more: a selection is
    # the session's PRIORITY (those pictures are compared first), never a
    # fence around the pool — two selected items used to make a one-pair
    # session that ended immediately.
    if ranking.scope:
        tree = try_parse(ranking.scope)
        if tree is not None:
            ids &= resolve(tree, None)
    return sorted(ids)


#: How many of the pool the pair pick actually looks at. The first side is
#: "the least judged, at random among ties" and the partner is "the nearest
#: standing" — over a million items where all but a few hundred are tied at
#: zero, both are answered just as well by a random couple of thousand of
#: them, and the items that DO carry evidence are added to the sample by
#: name (`keep`) so the ordering and the partner search stay exact about
#: them. Small enough that `pick_pair`'s sorts are microseconds.
_PICK_SAMPLE = 2000

#: What fraction of a probe has to land for it to count as a sample —
#: a quarter. Below that the pool is thin enough in the id space that the
#: draw is mostly misses, and the scan gives a better sample for the same
#: order of time.
_PROBE_YIELD = 4


@dataclass
class _Pool:
    """The session's pool: how big it is, which of some ids are in it, and a
    few of its items at random — each one SQL statement.

    `/pair` runs once per press, and MATERIALIZING the pool there is what
    made a judgement take seconds on a large library: measured at a million
    items, fetching the ids cost ~1.0 s and `pick_pair`'s two sorts over
    them another ~1.4 s, per press, to choose two pictures. Nothing about
    the answer needed them: the header wants a count and the pick wants a
    handful of candidates.

    `ids()` is still the exact list — the summary reads it, and a pick that
    the sample could not answer falls back to it, so "nothing left to
    compare" stays an answer about the POOL rather than about a sample.
    It is also the whole of this object on the two paths a sample cannot
    describe: a search with a RESIDUE (its matches are decided in Python)
    and a ranking with a stored scope (two searches intersected).
    """

    s: Session
    lib: Library
    ranking: Ranking
    body: Optional[ItemSearchRequest]
    res: Resolver
    cands: object = None
    #: Set when the pool has to be materialized to be answered at all.
    exact_only: bool = False
    #: True once a sample turned out to BE the whole pool (the LIMIT was
    #: never reached), which is what says a pick that found nothing has
    #: nothing to find — no fallback needed.
    sampled_all: bool = False
    _ids: Optional[list[int]] = field(default=None, repr=False)
    _count: Optional[int] = field(default=None, repr=False)

    def ids(self) -> list[int]:
        if self._ids is None:
            self._ids = _scope_ids(self.s, self.lib, self.ranking, self.body)
        return self._ids

    @property
    def count(self) -> int:
        if self._ids is not None:
            return len(self._ids)
        if self.exact_only:
            return len(self.ids())
        if self._count is None:
            # Through the grid's own memo: the pool's size is asked once per
            # KEYPRESS and is constant for the session, so on a million-item
            # library it was ~200 ms a judgement spent recounting a number
            # that could not have changed (`routers/items.scope_count`).
            from .items import scope_count

            self._count = scope_count(self.s, self.lib.db,
                                      self.cands.ids_select())
        return self._count

    def contains(self, ids) -> set[int]:
        """Which of `ids` are in the pool. Chunked, like every other
        Python-side id list that parameterizes an `IN (...)`."""
        want = [int(i) for i in ids]
        if not want:
            return set()
        if self.exact_only or self._ids is not None:
            return set(want) & set(self.ids())
        # Driven from the ids (`prefilter.admitted`), never
        # `ids_select().where(Item.id.in_(chunk))`: on a group scope under a
        # kind filter that is SQLite's cross product of the two id lists —
        # 12.8 s a chunk at 600,000 items.
        return set(admitted(self.s, self.cands.ids_select(), want))

    def sample(self, k: int, keep) -> list[int]:
        """At most `k` of the pool at random, plus whichever of `keep` are in
        it — or None when the pool cannot be sampled and the caller should
        use `ids()`.

        TWO WAYS TO DRAW IT, and the cheap one is tried first.

        `ORDER BY random() LIMIT k` builds no Python objects but it is still
        a SCAN of everything the scope admits — 231 ms at a million items,
        once per keypress, to choose two pictures. `_probe` instead throws
        `k` RANDOM IDS at the scope and keeps the ones that land: the same
        uniform sample of a dense pool, out of `k` primary-key seeks rather
        than a million rows — **6 ms**. Where too few land (a scope holding a
        small fraction of the id space) it answers None and the scan runs, so
        a narrow pool is sampled exactly as well as it always was.
        """
        if self.exact_only:
            return None
        rows = self._probe(k)
        if rows is None:
            rows = self.s.execute(
                self.cands.ids_select().order_by(func.random()).limit(k)
            ).scalars().all()
            # Short of the limit means the pool IS these rows — which is what
            # tells the caller a pick that found nothing has nothing to find,
            # without asking for the count. Only the SCAN can say that; a
            # probe that came back thin says nothing about the pool's size,
            # so it leaves the flag alone and a failed pick falls back to
            # `ids()`.
            self.sampled_all = len(rows) < k
        return sorted(set(rows) | self.contains(keep))

    def _probe(self, k: int) -> Optional[list[int]]:
        """`k` random ids, kept where they are in the pool — or None when too
        few landed to be a sample of it.

        Ids are handed out sequentially, so a random id is a random position
        in the library and the yield is the pool's DENSITY in the id space.
        A pool holding most of the library yields nearly `k`; one holding 2%
        of it yields 2% of `k`, which is not a sample anybody should pick
        from — hence the floor, and the scan behind it.
        """
        top = self.s.execute(select(func.max(Item.id))).scalar()
        if not top:
            return None
        rng = random.Random()
        want = {rng.randint(1, int(top)) for _ in range(k)}
        rows = admitted(self.s, self.cands.ids_select(), want)
        return rows if len(rows) >= k // _PROBE_YIELD else None


def _pool_for(s: Session, lib: Library, ranking: Ranking,
              body: Optional[ItemSearchRequest]) -> _Pool:
    res = Resolver(s)
    cands = _search(s, lib, body.query if body else None, body, res)
    # A residue is decided in Python and a stored scope is a second search
    # to intersect with; neither is a set SQL can sample, so those pools are
    # materialized exactly as they always were.
    exact = cands.residue is not None or bool(ranking.scope)
    return _Pool(s=s, lib=lib, ranking=ranking, body=body, res=res,
                 cands=cands, exact_only=exact)


def _cover_thumbs(s: Session, rankings, want: int) -> dict[int, list[int]]:
    """The FILE ids behind each ranking's cover — its best few pictures.

    The grid draws a ranking as a card with a 2x2 mosaic, the way it draws a
    sequence, and what belongs in a ranking's mosaic is the top of its
    standings rather than a sample: the card is the answer to "what is this
    axis about", and its best pictures say it.

    Asked for ONLY when a caller wants covers (`?thumbs=`), because it costs
    a fit per ranking — memoized on `db.cached` like every other reader of
    `placed_in_order`, so the sidebar's own poll, which asks for none, is
    unchanged.
    """
    out: dict[int, list[int]] = {}
    if want <= 0:
        return out
    lib_db = (s.info or {}).get("mc_db")
    for rk in rankings:
        placed = (lib_db.cached(s, ("ranking-order", rk.id, None),
                                lambda rk=rk: ops_rankings.placed_in_order(s, rk, None))
                  if lib_db is not None
                  else ops_rankings.placed_in_order(s, rk, None))
        ids = [iid for iid, _bucket in placed[:want]]
        if not ids:
            continue
        # The ACTIVE file of each, in the standings' own order — a dict lookup
        # rather than a query per picture.
        files = {int(i): int(f) for i, f in s.execute(
            select(Item.id, Item.active_file_id)
            .where(Item.id.in_(ids), Item.active_file_id.is_not(None))).all()}
        out[rk.id] = [files[i] for i in ids if i in files]
    return out


def _rows(s: Session, lib: Library, thumbs: int = 0) -> list[RankingRow]:
    rankings = s.execute(
        select(Ranking).order_by(Ranking.name, Ranking.id)
    ).scalars().all()
    ids = [r.id for r in rankings]
    counts = ops_rankings.counts_of(s, ids)
    item_counts = ops_rankings.item_counts_of(s, ids)
    dismissed = ops_rankings.dismissed_counts_of(s, ids)
    pool_counts = ops_rankings.pool_counts_of(s, ids)
    settled = ops_rankings.settled_pools(s, ids)
    # Every pool in ONE read, grouped here, rather than a query per row.
    pools: dict[int, list[RankingPool]] = {}
    if ids:
        for lg in s.execute(select(RankingPool)
                            .where(RankingPool.ranking_id.in_(ids))
                            .order_by(RankingPool.position,
                                      RankingPool.id)).scalars().all():
            pools.setdefault(lg.ranking_id, []).append(lg)
    covers = _cover_thumbs(s, rankings, thumbs)
    out = []
    for r in rankings:
        out.append(RankingRow(
            id=r.id, name=r.name, thumbs=covers.get(r.id, []),
            scope=r.scope, bucket_lo=r.bucket_lo, bucket_hi=r.bucket_hi,
            judgments=counts.get(r.id, 0),
            items=item_counts.get(r.id, 0),
            dismissed=dismissed.get(r.id, 0),
            pools=[RankingPoolRow(
                id=lg.id, name=lg.name,
                settled=settled.get(lg.id, False),
                judgments=pool_counts.get(lg.id, (0, 0))[0],
                items=pool_counts.get(lg.id, (0, 0))[1],
            ) for lg in pools.get(r.id, [])],
        ))
    return out


@router.get("", response_model=list[RankingRow])
def list_rankings(thumbs: int = 0, s: Session = Depends(get_session),
                  lib: Library = Depends(get_library)):
    """Every ranking. ``thumbs`` asks for that many COVER pictures per row
    (the grid's cards want four); the sidebar asks for none and pays for
    none."""
    return _rows(s, lib, max(0, min(8, int(thumbs))))


@router.post("", response_model=list[RankingRow])
def create_ranking(body: RankingCreate, ctx: Ctx = Depends(get_ctx),
                   lib: Library = Depends(get_library)):
    _check_scope(body.scope)
    ops_rankings.create(ctx, name=body.name,
                        scope=body.scope,
                        bucket_lo=body.bucket_lo, bucket_hi=body.bucket_hi)
    return _rows(ctx.session, lib)


@router.patch("/{ranking_id}", response_model=list[RankingRow])
def update_ranking(ranking_id: int, body: RankingUpdate,
                   ctx: Ctx = Depends(get_ctx),
                   lib: Library = Depends(get_library)):
    if body.scope is not None:
        _check_scope(body.scope)
    ops_rankings.update(ctx, ranking_id, name=body.name,
                        scope=body.scope,
                        bucket_lo=body.bucket_lo, bucket_hi=body.bucket_hi,
                        )
    return _rows(ctx.session, lib)


@router.delete("/{ranking_id}", response_model=list[RankingRow])
def delete_ranking(ranking_id: int, ctx: Ctx = Depends(get_ctx),
                   lib: Library = Depends(get_library)):
    ops_rankings.delete_ranking(ctx, ranking_id)
    return _rows(ctx.session, lib)


@router.post("/{ranking_id}/pools", response_model=list[RankingRow])
def create_pool(ranking_id: int, body: RankingPoolCreate,
                  ctx: Ctx = Depends(get_ctx),
                  lib: Library = Depends(get_library)):
    ops_rankings.create_pool(ctx, ranking_id, body.name)
    return _rows(ctx.session, lib)


@router.post("/{ranking_id}/pools/order", response_model=list[RankingRow])
def reorder_pools(ranking_id: int, body: RankingPoolOrder,
                    ctx: Ctx = Depends(get_ctx),
                    lib: Library = Depends(get_library)):
    ops_rankings.reorder_pools(ctx, ranking_id, body.pool_ids)
    return _rows(ctx.session, lib)


@router.patch("/{ranking_id}/pools/{pool_id}",
              response_model=list[RankingRow])
def update_pool(ranking_id: int, pool_id: int, body: RankingPoolUpdate,
                  ctx: Ctx = Depends(get_ctx),
                  lib: Library = Depends(get_library)):
    """Rename a pool. It had a second half — showing or hiding its scores
    — until a ranking stopped writing any (rung v31)."""
    if body.name is not None:
        ops_rankings.rename_pool(ctx, ranking_id, pool_id, body.name)
    return _rows(ctx.session, lib)


@router.delete("/{ranking_id}/pools/{pool_id}",
               response_model=list[RankingRow])
def delete_pool(ranking_id: int, pool_id: int,
                  ctx: Ctx = Depends(get_ctx),
                  lib: Library = Depends(get_library)):
    """Not revertible — its judgments cascade (`delete_ranking`'s rule)."""
    ops_rankings.delete_pool(ctx, ranking_id, pool_id)
    return _rows(ctx.session, lib)


def _check_scope(scope: str) -> None:
    """A scope must PARSE when set — stored unparseable, it would silently
    mean "everything", the one thing a scope exists not to mean."""
    scope = (scope or "").strip()
    if scope and try_parse(scope) is None:
        raise Invalid("the scope is not a valid search",
                      code="ranking_scope_invalid")


@router.post("/{ranking_id}/pair", response_model=RankingPairOut)
def next_pair(ranking_id: int, body: RankingPairRequest,
              s: Session = Depends(get_session),
              lib: Library = Depends(get_library)):
    """The next pair to ask about. Read-only — see the module docstring."""
    from media_compost import rankingmath

    ctx = Ctx(session=s)
    ranking = ops_rankings.by_id(ctx, ranking_id)
    # WHOSE evidence: the session's picked pools (the default one when
    # the request names none). Resolved once, read by the pick, the sample's
    # keep-set and the summary alike.
    pool_ids = ops_rankings.resolve_pool_ids(ctx, ranking, body.pool_ids)
    pool = _pool_for(s, lib, ranking, body)
    judgments = ops_rankings.counts_of(s, [ranking.id]).get(ranking.id, 0)
    # The pool's SIZE is a `count(*)` over the whole scope and it cannot
    # change while a session runs — judging changes what is KNOWN about the
    # pool, never what is in it — so the overlay asks for it once and the
    # rest of the presses do not pay for it.
    size = pool.count if body.want_pool else None
    if body.summary_only:
        # The MID-SESSION summary — the overlay's Esc and its header button
        # ask for the standings without spending a pair pick.
        return RankingPairOut(reason="summary", pool=size,
                              judgments=judgments,
                              summary=_summary(s, ranking, pool, pool_ids))
    # THE PICK LOOKS AT A SAMPLE, and only the sample: a couple of thousand
    # of the pool plus everything the ranking has evidence about (which is
    # what the least-judged ordering and the nearest-standing partner are
    # actually about) and whatever the session put first. A sample that
    # cannot answer falls back to the whole pool, so an ended session is
    # still an exact answer rather than a guess.
    keep = (ops_rankings.judged_ids(s, ranking, pool_ids)
            | {int(i) for i in body.items})
    sample = pool.sample(_PICK_SAMPLE, keep)
    pair = None
    if sample is not None:
        pair = ops_rankings.next_pair(s, ranking, sample, recent=body.recent,
                                      priority=body.items,
                                      pool_ids=pool_ids)
    if pair is None and not pool.sampled_all:
        pair = ops_rankings.next_pair(s, ranking, pool.ids(),
                                      recent=body.recent, priority=body.items,
                                      pool_ids=pool_ids)
    if pair is None:
        # NOTHING LEFT TO COMPARE. With something judged, the reply carries
        # how the pool stands right now, best first — computed on read (the
        # standings and buckets are pure), never written: the session's
        # close is still what stamps the tags.
        return RankingPairOut(reason="small_pool", pool=size,
                              judgments=judgments,
                              summary=_summary(s, ranking, pool, pool_ids))
    refs = _refs(s, list(pair))
    return RankingPairOut(a=refs.get(pair[0]), b=refs.get(pair[1]),
                          pool=size, judgments=judgments)


def _summary(s: Session, ranking: Ranking, pool: "_Pool",
             pool_ids: list[int]) -> list[RankingSummaryOut]:
    """The pool's standings, best first, each with the score tag it lands on
    — computed on read (the standings and buckets are pure), never written:
    the session's close is still what stamps the tags. PER POOL, in the
    request's order (one item may appear once per pool); the pool
    membership and the refs are asked once over the union.

    Asked of the SCORES rather than of the pool: only a judged item can be
    placed, and there are two of those per judgment against a pool of any
    size, so the question is "which of these few are still in scope" and not
    "which of a million have a score". Same rows, either way round.
    """
    from media_compost import rankingmath

    summary: list[RankingSummaryOut] = []
    names = {lg.id: lg.name for lg in ops_rankings.pools_of(s, ranking)}
    by_pool = {lid: ops_rankings.standings(s, ranking, [lid])
                 for lid in pool_ids}
    union: set[int] = set()
    for scores in by_pool.values():
        union |= set(scores.keys())
    in_pool = pool.contains(union) if union else set()
    refs = _refs(s, sorted(in_pool)) if in_pool else {}
    lo, hi = ranking.bucket_lo, ranking.bucket_hi
    for lid in pool_ids:
        scores = by_pool[lid]
        placed = [u for u in scores if u in in_pool]
        if not placed:
            continue
        want = rankingmath.buckets(scores, hi - lo + 1)
        # The SAME total order buckets() ranks by (score, then id), or a
        # score tie lists its units in another order than the one their
        # buckets were dealt in — poise:3, poise:2, poise:3 down the page.
        placed.sort(key=lambda u: (-scores.get(u, 0.0), -u))
        for u in placed:
            if u in refs and u in want:
                summary.append(RankingSummaryOut(
                    ref=refs[u],
                    bucket=lo + want[u],
                    pool_id=lid, pool=names.get(lid, "")))
    return summary


@router.post("/{ranking_id}/judge")
def judge(ranking_id: int, body: RankingJudgeIn, ctx: Ctx = Depends(get_ctx)):
    rows = ops_rankings.judge(ctx, ranking_id, body.a_item_id, body.b_item_id,
                              body.outcome, body.pool_ids)
    # `event_ids` is what the overlay's U reverts — one per pool written,
    # through the ordinary history machinery, which also refits the scores.
    # The singular pair is the first row, for a caller that knows only it.
    return {"ok": True, "judgment_id": rows[0].id,
            "event_id": getattr(rows[0], "event_id", None),
            "judgment_ids": [j.id for j in rows],
            "event_ids": [getattr(j, "event_id", None) for j in rows]}


@router.post("/{ranking_id}/dismiss")
def dismiss(ranking_id: int, body: RankingDismissIn,
            ctx: Ctx = Depends(get_ctx)):
    """A dismissed picture leaves the standings — which are fitted on the
    way out, so there is nothing to materialize and nothing to refresh."""
    ops_rankings.dismiss(ctx, ranking_id, [body.item_id])
    return {"ok": True}


@router.post("/{ranking_id}/undismiss")
def undismiss(ranking_id: int, body: RankingDismissIn,
              ctx: Ctx = Depends(get_ctx)):
    ops_rankings.undismiss(ctx, ranking_id, [body.item_id])
    return {"ok": True}


# ---- the same three verbs over a SELECTION or a whole VIEW --------------------
#
# The sidebar offers them wherever it offers anything: on the picked picture,
# on a selection of them, and — with nothing picked — on everything the view
# is showing. The ids travel for a selection and the SCOPE travels for a view
# (`viewscope`, the one resolution), and the write lands in committed chunks
# the way every other whole-view write does.


def _target_ids(body: RankingItemsIn, s: Session, lib: Library) -> list[int]:
    """The pictures this call is about — the named ones, or the view's."""
    if body.items:
        return [int(i) for i in dict.fromkeys(body.items)]
    if not body.view:
        raise Invalid("name the pictures, or ask for the view",
                      code="ranking_no_items")
    return viewscope.view_ids(s, lib, body)


@router.post("/{ranking_id}/items/dismiss", response_model=RankingItemsOut)
def dismiss_items(ranking_id: int, body: RankingItemsIn,
                  ctx: Ctx = Depends(get_ctx),
                  s: Session = Depends(get_session),
                  lib: Library = Depends(get_library)):
    """Set aside every named picture (or every picture in the view)."""
    ids = _target_ids(body, s, lib)
    count = 0
    for chunk in viewscope.chunks(ids):
        count += ops_rankings.dismiss(ctx, ranking_id, chunk)
        s.commit()
    return RankingItemsOut(count=count, total=len(ids))


@router.post("/{ranking_id}/items/undismiss", response_model=RankingItemsOut)
def undismiss_items(ranking_id: int, body: RankingItemsIn,
                    ctx: Ctx = Depends(get_ctx),
                    s: Session = Depends(get_session),
                    lib: Library = Depends(get_library)):
    """Put every named picture (or the whole view) back in the fit."""
    ids = _target_ids(body, s, lib)
    count = 0
    for chunk in viewscope.chunks(ids):
        count += ops_rankings.undismiss(ctx, ranking_id, chunk)
        s.commit()
    return RankingItemsOut(count=count, total=len(ids))


@router.post("/{ranking_id}/items/remove", response_model=RankingItemsOut)
def remove_items(ranking_id: int, body: RankingItemsIn,
                 ctx: Ctx = Depends(get_ctx),
                 s: Session = Depends(get_session),
                 lib: Library = Depends(get_library)):
    """Take every named picture (or the whole view) out of the ranking, which
    means deleting the comparisons they were part of. ``judgments`` is how
    many went — the number the question asked about before it ran."""
    ids = _target_ids(body, s, lib)
    judgments = 0
    for chunk in viewscope.chunks(ids):
        judgments += ops_rankings.remove_item(ctx, ranking_id, chunk)
        s.commit()
    return RankingItemsOut(count=len(ids), total=len(ids),
                           judgments=judgments)


@router.get("/{ranking_id}/items/{item_id}", response_model=RankingItemStanding)
def item_standing(ranking_id: int, item_id: int,
                  s: Session = Depends(get_session)):
    """Where one picture stands on this axis — the Ranking TAB of the item
    sidebar, offered while a ranking's own view is what you are standing in.

    Per POOL, because the fit is: two pools of one ranking place the same
    picture on the same scale by different evidence, and which one you are
    looking at is a thing the view chose."""
    rk = s.get(Ranking, ranking_id)
    if rk is None:
        raise NotFound("ranking not found", code="ranking_not_found")
    placed: list[tuple[int, str, int]] = []
    for lg in ops_rankings.pools_of(s, rk):
        for iid, bucket in ops_rankings.placed_in_order(s, rk, [lg.id]):
            if iid == item_id:
                placed.append((lg.id, lg.name, bucket))
                break
    return RankingItemStanding(
        placed=placed,
        judgments=ops_rankings.item_judgment_count(s, rk, item_id),
        dismissed=ops_rankings.is_dismissed(s, rk, item_id),
        bucket_lo=rk.bucket_lo, bucket_hi=rk.bucket_hi,
    )


@router.delete("/{ranking_id}/items/{item_id}")
def remove_item(ranking_id: int, item_id: int, ctx: Ctx = Depends(get_ctx)):
    """The score-tag chip's ✕: take the item out of the ranking by deleting
    every judgment it was part of, and refit. Logged with a snapshot, so the
    sidebar's undo bar can offer it back."""
    n = ops_rankings.remove_item(ctx, ranking_id, [item_id])
    return {"ok": True, "removed": n}


@router.get("/{ranking_id}/detail", response_model=RankingDetailOut)
def detail(ranking_id: int, s: Session = Depends(get_session)):
    """The histogram the Rankings list's detail draws: bucket populations with
    sample thumbnails, plus the not-applicable list with its way back."""
    from media_compost import rankingmath

    ranking = ops_rankings.by_id(Ctx(session=s), ranking_id)
    lo, hi = ranking.bucket_lo, ranking.bucket_hi
    n = hi - lo + 1
    # ONE histogram PER POOL, the refs fetched once over every sample.
    per_pool: list[tuple[RankingPool, dict[int, list[int]], int]] = []
    sample_ids: list[int] = []
    for pool in ops_rankings.pools_of(s, ranking):
        scores = ops_rankings.standings(s, ranking, [pool.id])
        want = rankingmath.buckets(scores, n)
        by_bucket: dict[int, list[int]] = {}
        for uid_, bucket in want.items():
            by_bucket.setdefault(bucket, []).append(uid_)
        # Best-first inside a bucket, so the samples are its top of the top.
        for members in by_bucket.values():
            members.sort(key=lambda i: -scores.get(i, 0.0))
        sample_ids += [i for members in by_bucket.values()
                       for i in members[:_BUCKET_SAMPLES]]
        per_pool.append((pool, by_bucket, len(want)))
    na_ids = sorted(ops_rankings.dismissed_ids(s, ranking))
    refs = _refs(s, sorted(set(sample_ids)) + na_ids)
    pool_counts = ops_rankings.pool_counts_of(s, [ranking.id])
    settled = ops_rankings.settled_pools(s, [ranking.id])

    def _buckets(by_bucket: dict[int, list[int]]) -> list[RankingBucketOut]:
        # The API's bucket numbers are the TAG numbers (`lo`…`hi`), so the
        # histogram's axis reads as the tags it stands for.
        return [RankingBucketOut(
            bucket=lo + b, count=len(by_bucket.get(b, [])),
            samples=[refs[i] for i in by_bucket.get(b, [])[:_BUCKET_SAMPLES]
                     if i in refs],
        ) for b in range(n)]

    pools_out = [RankingPoolDetailOut(
        id=pool.id, name=pool.name,
        settled=settled.get(pool.id, False),
        judgments=pool_counts.get(pool.id, (0, 0))[0],
        scored=scored, buckets=_buckets(by_bucket),
    ) for pool, by_bucket, scored in per_pool]
    return RankingDetailOut(
        id=ranking.id,
        buckets=pools_out[0].buckets if pools_out else _buckets({}),
        not_applicable=[refs[i] for i in na_ids if i in refs],
        judgments=ops_rankings.counts_of(s, [ranking.id]).get(ranking.id, 0),
        scored=pools_out[0].scored if pools_out else 0,
        pools=pools_out,
    )
