"""The tag-batch overlay's endpoints: a session feed and an index trigger.

The session itself is stateless server-side — every answer is an ordinary
(revertible) tag assignment written through the assign endpoint, so the
classifier's labels are simply the tags' current assignments and `/next` can
re-derive everything per fetch. What travels with a request is only the
SESSION-LOCAL signal: the scope captured at open (the search body, or an
explicit selection — the rating overlay's rule), the items already shown
(`recent`, the skip memory), the set's SHAPE (`tag_groups`: which tags are
mutually exclusive, so another's positive is evidence against this one;
`counter_tags`: the tag written positively in place of a negative), and the
implicit negatives — a tag whose "unlit" writes nothing — that are
deliberately never written.

`/next` is a read-only POST and is named in `build.READ_ONLY_POSTS`; left
out, the stale-page guard would 409 a session's first fetch. `/index` is a
WRITE (it enqueues the embed batch job) and is deliberately not listed.
"""

from __future__ import annotations

import random
from typing import Optional

import numpy as np
import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session

from media_compost import taggridmath, tagsortmath
from media_compost.db import Item, ItemEmbedding, ItemTag, Tag, chunked
from media_compost.ops import search
from media_compost.ops.errors import Invalid
from media_compost.prefilter import admitted
from media_compost.resolve import Resolver

from ...itemvec import EMBEDDERS, LABEL_CAP, SCORE_CAP, indexed_ids, load_matrix
from .. import viewscope
from ..deps import Library, get_current_user, get_library, get_session
from ..schemas import (
    ItemSearchRequest,
    TagSortIndexRequest,
    TagSortNextOut,
    TagSortNextRequest,
)
from .rankings import _refs

router = APIRouter(prefix="/api/tagsort", tags=["tagsort"])


def _space_of(embedder: str) -> str:
    """The embedding space a request's chosen model writes and reads —
    refused by NAME for anything `itemvec.EMBEDDERS` does not know, so a
    stale client cannot silently score in the default space."""
    entry = EMBEDDERS.get(embedder)
    if entry is None:
        raise Invalid("unknown embedder “{name}”", {"name": embedder},
                      code="tagsort_unknown_embedder")
    return entry[0]


def _pool_select(s: Session, lib: Library, body: ItemSearchRequest):
    """The session scope, as SQL — the search body through the one search
    there is. A selection deliberately does NOT narrow it: `items` is the
    session's PRIORITY (those pictures are asked about first), the rankings'
    rule.

    A SELECT rather than a list of ids, for the reason the rating pool is
    one: `/next` runs once per answer, and what it needs of a pool that size
    is counts and a sample. Returns None where the search has a RESIDUE —
    those matches are decided in Python, so that pool is materialized as it
    always was.
    """
    # The trash is never a tag-batch pool, whatever the grid's body says —
    # so the flag is overridden rather than passed on, which is the one
    # difference from an ordinary whole-view resolution.
    scoped = body.model_copy(update={"trash": False})
    res = Resolver(s)
    # The session's own scope, less the TRASH — a session never deals from
    # it, whatever the view behind the overlay was showing.
    base = search.search_filtered(
        s, **{**search.scope_of(scoped), "trash": False},
        query=scoped.query, resolver=res)
    return base.ids_select() if base.residue is None else None


def _pool_ids(s: Session, lib: Library,
              body: ItemSearchRequest) -> list[int]:
    """The session scope as a LIST — the exact answer, for the residue path
    and for `/index`, which enqueues a job over every item it names."""
    return sorted(viewscope.view_ids(
        s, lib, body.model_copy(update={"trash": False})))


def _has_vector(space: str):
    """`EXISTS a CURRENT vector in this space` — the same rule
    `itemvec.indexed_ids` reads (the row must be the ACTIVE file's), as a
    correlated clause so it can narrow a select instead of filtering a list
    of a million ids in Python."""
    return exists(
        select(sa.literal(1)).where(
            ItemEmbedding.item_id == Item.id,
            ItemEmbedding.model == space,
            ItemEmbedding.file_id.is_not(None),
            ItemEmbedding.file_id == Item.active_file_id,
        )
    )


def _undecided(sel, tag_ids: list[int], single: bool,
               counter_ids: list[int] = ()):
    """The candidates, less the items the session has already ANSWERED —
    single mode drops the tag either sign, multi drops a positive of any set
    tag (an item with only negatives may yet belong to another tag of the
    set) — and, either mode, a POSITIVE of any counter tag: "doesn't fit"
    written as a tag of its own is as much an answer as the negative it
    stands in for. Pending rows stay: deciding a machine's suggestion is
    the most valuable answer a session gives.

    A NOT EXISTS rather than a hundred chunked `item_id IN (10k ids)`
    queries and a Python set difference, which is what it was — 0.58 s of
    every press on a million-item pool.
    """
    counter_ids = [c for c in counter_ids if c not in set(tag_ids)]
    if not tag_ids and not counter_ids:
        return sel
    parts = []
    if tag_ids:
        where = [ItemTag.tag_id.in_(tag_ids)]
        if not single:
            where.append(ItemTag.negative.is_(False))
        parts.append(sa.and_(*where))
    if counter_ids:
        parts.append(sa.and_(ItemTag.tag_id.in_(counter_ids),
                             ItemTag.negative.is_(False)))
    return sel.where(~exists(select(sa.literal(1)).where(
        ItemTag.item_id == Item.id, ItemTag.pending.is_(False),
        sa.or_(*parts))))


def _without(sel, ids):
    """`sel` minus these ids — chunked, since a session's skip memory is
    every item it has shown."""
    for chunk in chunked([int(i) for i in ids]):
        sel = sel.where(Item.id.notin_(chunk))
    return sel


def _count(s: Session, sel) -> int:
    return int(s.execute(
        select(func.count()).select_from(sel.subquery())).scalar_one())


#: What fraction of a probe has to land for it to count as a sample of the
#: pool — a twentieth. The rating side asks for a quarter; here the probe is
#: `SCORE_CAP` wide, so a twentieth of it is still ~1,000 scored candidates
#: to order twelve pictures by, and below the threshold the fallback is a
#: scan of the scope with a per-row EXISTS — 0.35 s a press on a 60,000-item
#: group in a 600,000-item library, where the probe (now that it is driven
#: from the ids) is ~0.1 s. A quarter sent every scope between 5% and 25% of
#: the id space down the scan for no gain in the answer.
_PROBE_YIELD = 20


def _probe(s: Session, sel, k: int, extra=None):
    """`k` random ids, kept where they are in the pool — or None when too few
    landed to be a sample of it.

    THE SAME TRICK THE RATING POOL USES, and the same reasoning. `ORDER BY
    random() LIMIT k` builds no Python objects but it is a SCAN of everything
    the scope admits, and here it carries a per-row `EXISTS` over the
    embeddings as well: measured on a million-item library, **2954 ms per
    press**. Ids are handed out sequentially, so a random id is a random
    position in the library and the yield is the pool's DENSITY in the id
    space — `k` primary-key seeks for the same uniform sample of a dense
    pool. Below a quarter it answers None and the caller scans, so a narrow
    pool is sampled exactly as well as it always was.

    `extra` are columns to bring back beside the id (the vector flag).

    THE MEMBERSHIP QUESTION GOES THROUGH `prefilter.admitted`, never
    `sel.where(Item.id.in_(chunk))`: on a group scope under a kind filter
    that spelling is SQLite's cross product of the two id lists — 12.8 s a
    chunk on a 600,000-item library, i.e. the first picture of a session
    over a 60,000-item group took minutes to arrive. The extra columns are
    read afterwards over the HITS alone, a plain primary-key list with no
    scope on it.
    """
    if k <= 0:
        return []
    top = s.execute(select(func.max(Item.id))).scalar()
    if not top:
        return None
    rng = random.Random()
    want = {rng.randint(1, int(top)) for _ in range(k)}
    hits = admitted(s, sel, want)
    if len(hits) < max(1, k // _PROBE_YIELD):
        return None
    if not extra:
        return [(i,) for i in hits]
    rows: list = []
    for chunk in chunked(hits):
        rows += s.execute(
            select(Item.id, *extra).where(Item.id.in_(chunk))).all()
    return rows


#: How many ids `_pick` throws at the scope for a queue-sized draw. A probe
#: of twelve ids at a tenth's density lands one, and one accepted hit was a
#: session handed a queue of ONE picture (seen at `_PROBE_YIELD = 20`,
#: where 12 // 20 rounds to nothing); the yield rule only says anything
#: over a draw wide enough to have a yield.
_PICK_PROBE = 2000


def _pick(s: Session, sel, k: int) -> list[int]:
    """At most `k` of a select, at random — by id probe, else by scan."""
    if k <= 0:
        return []
    rows = _probe(s, sel, max(k, _PICK_PROBE))
    if rows is not None:
        hits = [int(r[0]) for r in rows]
        return random.sample(hits, k) if len(hits) > k else hits
    return [int(i) for i in s.execute(
        sel.order_by(func.random()).limit(k)).scalars().all()]


def _has_any_vector(spaces: list[str]):
    """`EXISTS a current vector in ANY of these spaces` — what "scorable"
    means under fusion, and the single-space rule when there is one."""
    return sa.or_(*[_has_vector(sp) for sp in spaces])


def _counts_by_space(s: Session, sel, spaces: list[str],
                     ) -> tuple[int, int, dict[str, int]]:
    """(candidates, scorable in any space, {space: indexed}) — ONE scan:
    the count is already visiting every row, and a per-space column costs
    it nothing. Both session feeds' coverage probe."""
    cols = [case((_has_vector(sp), 1), else_=0).label(f"e{k}")
            for k, sp in enumerate(spaces)]
    any_col = case((_has_any_vector(spaces), 1), else_=0).label("any")
    sub = sel.add_columns(*cols, any_col).subquery()
    row = s.execute(
        select(func.count(),
               func.coalesce(func.sum(sub.c["any"]), 0),
               *[func.coalesce(func.sum(sub.c[f"e{k}"]), 0)
                 for k in range(len(spaces))])
        .select_from(sub)).one()
    total = int(row[0])
    any_n = int(row[1])
    per = {sp: int(row[2 + k]) for k, sp in enumerate(spaces)}
    return total, any_n, per


def _pick_split(s: Session, sel, spaces: list[str], k: int,
                ) -> tuple[list[int], list[int]]:
    """At most `k` candidates at random, split into (scorable in ANY of
    `spaces`, not).

    ONE draw for both, and the split is what the queue wants anyway
    (vectorless items trail, but appear). Asked as two samples it was two
    passes over the same million rows, and on a pool with nothing indexed
    the first pass returned nothing at all.

    By ID PROBE where the pool is dense enough for one (`_probe`), else by
    the scan — which additionally SORTS by "has a vector", filling the
    sample with what the classifier can score. The probe cannot do that: it
    returns the pool's own embedded fraction rather than as many embedded
    rows as exist. That is the honest trade and it is affordable at this
    `k` (20,000 against a queue of a dozen): a tenth-indexed pool still
    yields ~2,000 scored candidates to order twelve pictures by.

    BOTH LISTS COME BACK SHUFFLED. The probe's hits arrive ASCENDING BY ID
    (`admitted` sorts them), and the scan's are random only past the vector
    sort — and whatever nothing can score is served in exactly this order:
    the queue before a session's first "yes", and the vectorless tail after
    it. Un-shuffled, a brand-new tag's session walked the library oldest
    picture first, every session, which on a library imported crawl by
    crawl is one site's oldest pictures for hundreds of answers (seen live:
    a fresh session answered 1, 4, 6, 7, 8, … and its next fetch 2, 14, 15,
    …; a fresh grid opened on items 1 to 16). The ordered path does not care
    what order it is handed.
    """
    if k <= 0:
        return [], []
    emb_col = case((_has_any_vector(spaces), 1), else_=0).label("emb")
    rows = _probe(s, sel, k, extra=[emb_col])
    if rows is None:
        rows = s.execute(
            sel.add_columns(emb_col)
            .order_by(sa.desc("emb"), func.random()).limit(k)).all()
    scored = [int(i) for i, emb in rows if emb]
    tail = [int(i) for i, emb in rows if not emb]
    rng = random.Random()
    rng.shuffle(scored)
    rng.shuffle(tail)
    return scored, tail


#: How many assignments `_label_ids` reads by scramble before asking which
#: carry a vector — see there.
_LABEL_OVERSAMPLE = 4


def _label_ids(s: Session, tag_id: Optional[int], negative: bool,
               cap: int, space: str) -> list[int]:
    """Up to `cap` items carrying this tag with this sign, PREFERRING the
    ones the fit can actually use (a label with no vector is dropped by
    `load_matrix` anyway).

    STABLE across fetches, like the seeded sample it replaces: the order is
    a multiplicative scramble of the item id — deterministic, spread over
    the whole tag rather than the oldest rows, and computed inside the scan
    so a tag on half the library never reaches Python.
    """
    if tag_id is None:
        return []
    scramble = (ItemTag.item_id * 2654435761) % 4294967291
    base = (select(ItemTag.item_id)
            .where(ItemTag.tag_id == tag_id,
                   ItemTag.pending.is_(False),
                   ItemTag.negative.is_(negative) if negative
                   else ItemTag.negative.is_(False))
            .order_by(scramble))
    # TWO STAGES, because the vector test is the expensive half. Asked in
    # one statement, "the first `cap` by scramble that carry a vector" is a
    # per-row lookup into two tables for EVERY assignment of the tag before
    # the sort — on a tag over 200,000 items, ~0.2 s of a press, twice
    # (both signs), per tag. So the first `_LABEL_OVERSAMPLE` x cap by
    # scramble are read off the assignment index alone (a top-k over a
    # covering index, no lookups) and filtered for vectors AFTERWARDS; only
    # where too few of those carry one — a thinly indexed library — does
    # the exact statement run. Same scramble, same answer where the head
    # holds enough: the order is the same in both.
    head = [int(i) for i in s.execute(
        base.limit(cap * _LABEL_OVERSAMPLE)).scalars().all()]
    with_vec = indexed_ids(s, head, space)
    picked = [i for i in head if i in with_vec][:cap]
    if len(picked) >= cap or len(head) < cap * _LABEL_OVERSAMPLE:
        # Enough — or the head IS the whole tag, so nothing else is there.
        return picked
    return [int(i) for i in s.execute(
        base.join(Item, Item.id == ItemTag.item_id)
        .where(_has_vector(space)).limit(cap)).scalars().all()]


def _label_count(s: Session, tag_id: Optional[int], negative: bool) -> int:
    if tag_id is None:
        return 0
    return int(s.execute(
        select(func.count()).select_from(ItemTag).where(
            ItemTag.tag_id == tag_id,
            ItemTag.pending.is_(False),
            ItemTag.negative.is_(negative))).scalar_one())


def _session_groups(names: list[str], body: TagSortNextRequest,
                    ) -> tuple[dict[str, Optional[int]], dict[str, list[str]]]:
    """The session's exclusivity, two ways: per tag the key of the mutually
    exclusive group it is in (None alone — `order_by_tag`'s per-tag keys),
    and per tag its RIVALS, the other tags of that group. A group naming a
    tag the session does not list is trimmed to the ones it does; a tag in
    several groups takes the first. With no `tag_groups` at all the old
    one-switch shape applies: `exclusive` makes every tag one group."""
    key: dict[str, Optional[int]] = {n: None for n in names}
    rivals: dict[str, list[str]] = {n: [] for n in names}
    groups = [[n for n in g.tags if n in key] for g in body.tag_groups
              if g.exclusive]
    for gi, members in enumerate(groups):
        members = [n for n in members if key[n] is None]
        if len(members) < 2:
            continue
        for n in members:
            key[n] = gi
            rivals[n] = [m for m in members if m != n]
    return key, rivals


def _tag_ids(s: Session, names: list[str]) -> dict[str, Optional[int]]:
    """Each session tag's resolved id — alias-redirected, None when the tag
    does not exist yet (a session may well be about a brand-new tag; it
    simply has no labels and no exclusions until the first answer mints
    it)."""
    out: dict[str, Optional[int]] = {}
    for name in names:
        tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
        if tag is not None and tag.alias_of_id is not None:
            tag = s.get(Tag, tag.alias_of_id) or tag
        out[name] = tag.id if tag is not None else None
    return out


def _residue_candidates(s: Session, lib: Library, body: ItemSearchRequest,
                        tag_ids: list[int], single: bool,
                        shown: list[int],
                        counter_ids: list[int] = ()) -> list[int]:
    """The candidates for a search SQL cannot describe exactly.

    A residue is evaluated in Python, so its pool has to be materialized —
    and then the session's exclusions are applied to the list, which is the
    same rule `_undecided` and `_without` state in SQL.
    """
    pool = _pool_ids(s, lib, body)
    decided: set[int] = set()
    counter_ids = [c for c in counter_ids if c not in set(tag_ids)]
    if (tag_ids or counter_ids) and pool:
        for chunk in chunked(pool):
            stmt = select(ItemTag.item_id).where(
                ItemTag.item_id.in_(chunk),
                ItemTag.pending.is_(False))
            parts = []
            if tag_ids:
                own = [ItemTag.tag_id.in_(tag_ids)]
                if not single:
                    own.append(ItemTag.negative.is_(False))
                parts.append(sa.and_(*own))
            if counter_ids:
                parts.append(sa.and_(ItemTag.tag_id.in_(counter_ids),
                                     ItemTag.negative.is_(False)))
            stmt = stmt.where(sa.or_(*parts))
            decided.update(int(i) for i in s.execute(stmt).scalars().all())
    skip = set(shown)
    return [i for i in pool if i not in decided and i not in skip]


def _with_carry(s: Session, carry: list[int], scored_pool: list[int],
                tail: list[int], spaces: list[str]) -> tuple[list[int], list[int]]:
    """The carried ids AHEAD of the draw, each in the half its vectors put
    it in — the scored pool where it has a current one in any space, the
    tail where it has none — and deduplicated against the draw, which may
    well have sampled some of them again."""
    if not carry:
        return scored_pool, tail
    with_vec: set[int] = set()
    for sp in spaces:
        with_vec |= indexed_ids(s, carry, sp)
    cset = set(carry)
    return ([i for i in carry if i in with_vec]
            + [i for i in scored_pool if i not in cset],
            [i for i in carry if i not in with_vec]
            + [i for i in tail if i not in cset])


def _spaces_of(embedder: str, embedders: list[str],
               ) -> tuple[list[str], dict[str, str]]:
    """The spaces a request scores in — `embedders` (the grid's list), else
    `embedder` alone — each refused by NAME (`_space_of`) and deduplicated,
    with the embedder id each space answers under in the coverage map."""
    spaces: list[str] = []
    by_space: dict[str, str] = {}
    for emb in (list(embedders) or [embedder]):
        sp = _space_of(emb)
        if sp not in spaces:
            spaces.append(sp)
            by_space[sp] = emb
    return spaces, by_space


def _cut_of(pos_scores, neg_scores) -> float:
    """Where a tag's classifier CLAIMS a candidate, for the tags-in-turn
    order: the grid's calibrated positive cut (leave-one-out, so a fresh
    row's score is what is measured) once each side has enough labels, and
    the ±1 midpoint before that — which on centered rows reads "more like
    the positives than the average picture"."""
    hi, _lo = taggridmath.cutoffs(pos_scores, neg_scores)
    return float(hi) if hi is not None else 0.0


#: What a candidate scores under a tag whose fit could not reach it (no
#: vector in any space that tag was fit in) — below every real score, so it
#: is never claimed and trails the unclaimed by its best real one.
_UNSCORED = -2.0


def _fused_scores(s: Session, cand: list[int], names: list[str],
                  ids_by_name: dict, spaces: list[str], single: bool,
                  body: TagSortNextRequest, rivals: dict[str, list[str]],
                  counters: dict[str, Optional[int]],
                  ) -> tuple[dict[str, dict[int, float]], dict[str, float]]:
    """Per tag, each candidate's FUSED score — one classifier per (tag,
    space), fit on that space's labels and scored in it, an item's score
    the MEAN of the spaces it is indexed in (`taggridmath.fuse`, the grid's
    rule: late fusion, because an item indexed in one space and not the
    other still gets a score and each space's fit is regularised on its own
    scale) — plus per tag the cut its stretch starts at, calibrated on the
    labeled rows' fused leave-one-out scores. Rows are CENTERED per space
    on that space's candidate mean, labels included.

    `rivals` names, per tag, the OTHER tags of its mutually exclusive group
    — their positives are evidence against it, and only there (blue_shirt
    and red_shirt co-exist) — and `counters` the counter tag's id, whose
    positives are negatives too (the grid's rule: a picture carrying BOTH
    is mixed evidence and teaches neither side).

    A tag with nothing to fit (no positive yet, no vectors) has an empty
    map and claims nothing.
    """
    per_item: dict[str, dict[int, list[float]]] = {n: {} for n in names}
    per_label: dict[str, dict[int, list[float]]] = {n: {} for n in names}
    sign: dict[str, dict[int, float]] = {n: {} for n in names}
    session_neg = {k: set(int(i) for i in v)
                   for k, v in (body.session_negatives or {}).items()}
    for space in spaces:
        cids, X = load_matrix(s, cand, space)
        if not len(cids):
            continue
        mu = X.mean(axis=0)
        X = tagsortmath.center(X, mu)
        for name in names:
            tid = ids_by_name[name]
            # THE LABELS ARE SAMPLED IN SQL, capped per side — the fit reads
            # at most `LABEL_CAP` of each anyway, and a tag on half the
            # library used to arrive in Python entire to be thrown away
            # down to 512.
            pos = _label_ids(s, tid, False, LABEL_CAP, space)
            neg = _label_ids(s, tid, True, LABEL_CAP, space)
            # Valid only under the exclusivity declaration: another
            # tag's positive IS evidence against this one there — and
            # only there (blue_shirt and red_shirt co-exist).
            for other in rivals.get(name, []):
                otid = ids_by_name.get(other)
                if otid is not None:
                    neg = neg + _label_ids(s, otid, False, LABEL_CAP, space)
            ctid = counters.get(name)
            if ctid is not None:
                cpos = _label_ids(s, ctid, False, LABEL_CAP, space)
                both = set(pos) & set(cpos)
                pos = [i for i in pos if i not in both]
                neg = neg + [i for i in cpos if i not in both]
            neg = neg + sorted(session_neg.get(name, set()))
            pos = _cap(sorted(set(pos)), LABEL_CAP, 11)
            neg = _cap(sorted(set(neg) - set(pos)), LABEL_CAP, 12)
            lids, LX = load_matrix(s, pos + neg, space)
            if not len(lids):
                continue
            LX = tagsortmath.center(LX, mu)
            pos_set = set(pos)
            y = np.array([1.0 if i in pos_set else -1.0 for i in lids],
                         dtype=np.float32)
            w = tagsortmath.fit(LX, y)
            if w is None:
                continue
            for iid, sc in zip(cids, tagsortmath.scores(X, w)):
                per_item[name].setdefault(int(iid), []).append(float(sc))
            for iid, sc, sg in zip(lids,
                                   taggridmath.calibration_scores(LX, y), y):
                per_label[name].setdefault(int(iid), []).append(float(sc))
                sign[name][int(iid)] = float(sg)
    fused = {n: taggridmath.fuse(per_item[n]) for n in names}
    cuts: dict[str, float] = {}
    for n in names:
        lab = taggridmath.fuse(per_label[n])
        cuts[n] = _cut_of([v for i, v in lab.items() if sign[n].get(i, 0) > 0],
                          [v for i, v in lab.items() if sign[n].get(i, 0) < 0])
    return fused, cuts


def _cap(ids: list[int], cap: int, seed: int) -> list[int]:
    """A deterministic sample past ``cap`` — seeded, so successive fetches
    with the same labels agree with themselves."""
    if len(ids) <= cap:
        return ids
    rng = random.Random(seed)
    return sorted(rng.sample(ids, cap))


@router.post("/next", response_model=TagSortNextOut)
def next_items(body: TagSortNextRequest,
               s: Session = Depends(get_session),
               lib: Library = Depends(get_library)):
    names = [str(n) for n in body.tags if str(n).strip()]
    if not names:
        raise Invalid("a tag session needs at least one tag",
                      code="tagsort_no_tags")
    ids_by_name = _tag_ids(s, names)
    single = len(names) == 1
    tag_ids = [t for t in ids_by_name.values() if t is not None]
    group_key, rivals = _session_groups(names, body)
    counter_names = {n: c.strip() for n, c in body.counter_tags.items()
                     if n in ids_by_name and c and c.strip()
                     and c.strip() != n}
    counter_ids_by = _tag_ids(s, sorted(set(counter_names.values())))
    counters = {n: counter_ids_by[c] for n, c in counter_names.items()}
    counter_ids = sorted({c for c in counters.values() if c is not None})
    spaces, by_space = _spaces_of(body.embedder, body.embedders)
    shown = [int(i) for i in body.recent]
    prio_ids = [int(i) for i in body.items]

    # THE CANDIDATES STAY IN SQL. What a session asks of its pool is a count,
    # a coverage figure and a few items to show — each one statement. The
    # pool used to be fetched whole and then filtered in Python: on a
    # million-item library that was ~0.9 s to fetch the ids, ~0.6 s of
    # chunked `item_tags` reads to drop the decided ones and ~0.5 s more to
    # ask which carry a vector, every press, to put twelve pictures on
    # screen.
    #
    # A search with a RESIDUE is decided in Python, so that pool is
    # materialized and the same clauses are applied to the list — the same
    # answer by the only route there is.
    sel = _pool_select(s, lib, body)
    residue_ids: Optional[list[int]] = None
    if sel is None:
        residue_ids = _residue_candidates(s, lib, body, tag_ids, single, shown,
                                          counter_ids)

    probe = body.count <= 0
    coverage: dict[str, int] = {}
    if residue_ids is None:
        cand_sel = _without(_undecided(sel, tag_ids, single, counter_ids),
                            shown)
        # THE COVERAGE FIGURE IS THE CHOOSER'S QUESTION, and a scan of its
        # own: the session header shows how many are left (and stops the
        # session when that reaches zero), and reads `embedded` nowhere. So
        # a press pays for the count and the probe pays for both, in one
        # scan either way.
        if probe:
            total, embedded_n, per = _counts_by_space(s, cand_sel, spaces)
            coverage = {by_space[sp]: n for sp, n in per.items()}
        elif body.want_pool:
            total, embedded_n = _count(s, cand_sel), 0
        else:
            # The overlay works it out: every item the session is handed
            # leaves the candidate set exactly once (answered it is decided,
            # skipped it is in `recent`), so what is left is the chooser's
            # own figure minus how many have been shown. A scan of the
            # library per keypress for a number it already has.
            total, embedded_n = None, 0
    else:
        cand_sel = None
        total = len(residue_ids) if (probe or body.want_pool) else None
        embedded_n = 0
        if probe:
            per_ids = {sp: indexed_ids(s, residue_ids, sp) for sp in spaces}
            any_set: set[int] = set().union(*per_ids.values()) if per_ids else set()
            embedded_n = len(any_set)
            coverage = {by_space[sp]: len(v) for sp, v in per_ids.items()}

    labeled = {name: (_label_count(s, ids_by_name[name], False),
                      _label_count(s, ids_by_name[name], True))
               for name in names}

    if probe:
        # The chooser's coverage probe: counts only.
        return TagSortNextOut(pool=total, embedded=embedded_n,
                              total=total, labeled=labeled,
                              coverage=coverage)

    # The selection LEADS the queue and never fences the pool (the rankings'
    # rule): priority items are asked about first, and the classifier orders
    # what comes after them. Exclusions and the skip memory still apply — a
    # decided or already-shown selected item is not re-asked.
    carry_ids = [int(i) for i in body.carry if int(i) not in set(prio_ids)]
    if residue_ids is None:
        # Through `admitted`, for `_probe`'s reason: a selection of sixty
        # thousand against a group scope is the same cross product.
        prio = admitted(s, cand_sel, prio_ids) if prio_ids else []
        rest_sel = _without(cand_sel, prio)
        # Score what can be scored — over the NON-priority remainder (the
        # priority items are served regardless of score). A fresh random
        # sample per fetch, so a pool past the cap is covered across a
        # session rather than the same slice being scored every time —
        # PLUS whatever the overlay still holds from the last fetch
        # (`carry`): the candidates the last fit ranked highest, which a
        # fresh sample would drop and re-find only by luck, so the ordering
        # accumulates across answers instead of re-rolling on each.
        if body.smart:
            scored_pool, tail = _pick_split(s, rest_sel, spaces, SCORE_CAP)
            carry = admitted(s, rest_sel, carry_ids) if carry_ids else []
            scored_pool, tail = _with_carry(s, carry, scored_pool, tail,
                                            spaces)
            rest = scored_pool + tail
        else:
            # Nothing to score: the queue is a random draw, and only a
            # queue's worth of it.
            scored_pool = []
            rest = tail = _pick(s, rest_sel, body.count)
    else:
        prio_set = set(prio_ids)
        prio = [i for i in residue_ids if i in prio_set]
        rest = [i for i in residue_ids if i not in prio_set]
        embedded: set[int] = set()
        for sp in spaces:
            embedded |= indexed_ids(s, rest, sp) if rest else set()
        scored_pool = _cap([i for i in rest if i in embedded], SCORE_CAP,
                           hash((tuple(sorted(names)),
                                 len(shown) // max(1, body.count))))
        tail = [i for i in rest if i not in embedded]
        # The residue pool is materialized in id order — shuffled for the
        # same reason `_pick_split` shuffles its draw.
        rng = random.Random()
        rng.shuffle(scored_pool)
        rng.shuffle(tail)
        rest_set = set(rest)
        carry = [i for i in carry_ids if i in rest_set]
        scored_pool, tail = _with_carry(s, carry, scored_pool, tail, spaces)

    ordered_ids: list[int] = []
    ordered = False
    if body.smart and scored_pool:
        fused, cuts = _fused_scores(s, scored_pool, names, ids_by_name,
                                    spaces, single, body, rivals, counters)
        if single:
            sc = fused.get(names[0]) or {}
            if sc:
                items = list(sc)
                arr = np.array([sc[i] for i in items], dtype=np.float32)
                idx = tagsortmath.order(arr, body.count)
                ordered_ids = [items[int(i)] for i in idx]
                ordered = True
        else:
            # THE TAGS IN TURN: the first tag's claimed pictures, then the
            # second's, … (`tagsortmath.order_by_tag`), each tag's claim
            # its own calibrated cut. A tag nothing can be fit for yet
            # claims nothing and its stretch is empty.
            fitted = [n for n in names if fused.get(n)]
            if fitted:
                items = sorted(set().union(*(fused[n].keys() for n in fitted)))
                S = np.array([[fused[n].get(i, _UNSCORED) for i in items]
                              for n in fitted], dtype=np.float32)
                idx = tagsortmath.order_by_tag(
                    S, [cuts[n] for n in fitted], body.count,
                    exclusive=[group_key[n] for n in fitted])
                ordered_ids = [items[int(i)] for i in idx]
                ordered = True

    # The queue: priority first, then the ordered picks, then the unscored
    # tail (and, unordered, the remainder as-is).
    queue_ids = prio[: body.count]
    for i in ordered_ids:
        if len(queue_ids) >= body.count:
            break
        if i not in queue_ids:
            queue_ids.append(i)
    if len(queue_ids) < body.count:
        # Short of a queue: the unscored trail the scored ones, and with no
        # ordering at all the remainder is simply the draw as it came.
        for i in (tail if ordered else rest):
            if len(queue_ids) >= body.count:
                break
            if i not in queue_ids:
                queue_ids.append(i)
    refs = _refs(s, queue_ids)
    return TagSortNextOut(
        queue=[refs[i] for i in queue_ids if i in refs],
        pool=total, embedded=embedded_n,
        total=total, ordered=ordered, labeled=labeled)


@router.post("/index")
def index_scope(body: TagSortIndexRequest,
                s: Session = Depends(get_session),
                lib: Library = Depends(get_library),
                user: str = Depends(get_current_user)):
    """Queue the embed batch job over the scope's unindexed items — a background
    task like any model run. Refused up front when the embedder is not set up,
    rather than enqueueing a job doomed to fail."""
    from ...plugins import registry

    space = _space_of(body.embedder)
    if not registry.available(body.embedder):
        raise Invalid(
            "the DINOv2 embedder is not set up — install it under "
            "Settings → Models first", code="tagsort_no_embedder")
    # ONE statement for what to queue: the scope's pictures without a
    # current vector. It used to fetch the whole pool, ask in chunks which
    # of them were pictures and then ask again which carried a vector —
    # three passes over a million ids to end up with the list the job
    # needs. Only pictures embed (the job would drop the rest anyway); a
    # row that matches the active file is done, anything else re-indexes.
    sel = _pool_select(s, lib, body)
    if sel is None:
        pool = _pool_ids(s, lib, body)
        stills: list[int] = []
        for chunk in chunked(pool):
            stills.extend(int(i) for i in s.execute(
                select(Item.id).where(Item.id.in_(chunk),
                                      Item.kind.in_(("image", "sequence")))
            ).scalars().all())
        done = indexed_ids(s, stills, space)
        todo = [i for i in stills if i not in done]
        total = len(pool)
    else:
        todo = [int(i) for i in s.execute(
            sel.where(Item.kind.in_(("image", "sequence")),
                      ~_has_vector(space))).scalars().all()]
        total = _count(s, sel)
    if not todo:
        return {"queued": 0, "skipped": total}
    ids = lib.jobs.enqueue("embed", body.embedder, todo, username=user)
    return {"queued": len(todo), "skipped": total - len(todo),
            "job_ids": ids}
