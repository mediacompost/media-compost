"""The tag-grid overlay's feed: a pre-sorted BATCH of pictures for one tag.

The tag grid is the tag-batch session's sibling for the mouse — a batch of
sixteen (or however many) pictures pre-sorted into three bands (fits /
undecided / doesn't fit) that the person corrects and confirms in one go,
rather than answering one picture at a time. It is deliberately its OWN
action with its own feed, not a mode of `/api/tagsort/next`: the two ask the
classifier different questions (a ranked queue against a mixed batch with
per-item scores and calibrated cuts), and a second endpoint keeps the first
one's contract — and its tests — exactly where they are. What it SHARES is
what must not drift: the pool rules (`_pool_select`, `_undecided`,
`_without`, `_residue_candidates`), the label sampling (`_label_ids`), the
vector loading (`itemvec.load_matrix`) and the fit (`tagsortmath.fit`), all
imported from the session's own modules.

Stateless like the session feed: every answer is an ordinary tag assignment
through the assign endpoint, so the fit's labels ARE the tag's current
assignments and each batch refits from the library as it stands — which is
what makes "the bands get better with every batch" true without a model
living anywhere.

WITH ONE EXCEPTION, and it is the tag batch's: a set of several tags has an
ASYMMETRIC pair of answers. "Fits" decomposes — the picture carries every
tag of the set, and each conjunct is written. "Doesn't fit" does not: it
says `NOT a OR NOT b`, and a disjunction is the one thing an assignment
cannot spell. Writing it on each tag separately claims far more than
anybody said (the picture may well be `a`, just not `a` and `b`), so past
one tag the answer writes NOTHING and rides back as `session_negatives` —
labels the fit learns from and the library is never told, the way
`tagsort`'s own untoggled tags do. Existing negatives are unaffected: one
`NOT a` in the library really is evidence against the whole conjunction,
which is what `_neg_evidence` has always read.

FUSION: a request may name TWO embedders. Each space gets its own fit and
its own scores, and an item's fused score is the mean of the spaces it is
indexed in (`taggridmath.fuse`); the cuts are then calibrated on the FUSED
scale from the labeled rows' fused scores, so no baseline threshold is
needed for the combination either.

`/next` is a read-only POST named in `build.READ_ONLY_POSTS`.
"""

from __future__ import annotations

import random
from typing import Optional

import numpy as np
import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from media_compost import taggridmath, tagsortmath
from media_compost.db import Item, ItemTag, chunked
from media_compost.ops.errors import Invalid
from media_compost.prefilter import admitted

from ...itemvec import LABEL_CAP, SCORE_CAP, indexed_ids, load_matrix
from ..deps import Library, get_library, get_session
from ..schemas import TagGridItem, TagGridNextOut, TagGridNextRequest
from .rankings import _refs
from .tagsort import (
    _cap,
    _counts_by_space,
    _has_vector,
    _LABEL_OVERSAMPLE,
    _pick_split,
    _pool_select,
    _pool_ids,
    _space_of,
    _tag_ids,
    _without,
)

router = APIRouter(prefix="/api/taggrid", tags=["taggrid"])


# ---- the QUESTION is a conjunction ------------------------------------------
#
# A session's question is a SET of tags now, not one: "white_shirt and
# blue_pants" asks about pictures that are both. That makes three membership
# rules, and every reader below is one of them.
#
#   POSITIVE  — carries EVERY tag of the set positively, and nothing against.
#   NEGATIVE  — carries evidence against ANY ONE of them: that tag assigned
#               negatively, or the counter tag somebody paired with it
#               assigned positively (`big` / `small`: a picture called small
#               is evidence against big, and the pairing is the only thing
#               that says so).
#   UNDECIDED — neither, which is most of the library and the whole pool.
#
# The negative side is ANY rather than ALL because the question is a
# conjunction: a picture failing one conjunct is not an example of the
# conjunction, whatever the others say. (ALL would have made a negative
# example almost unreachable — every tag of the set would have to have been
# answered no separately.)


def _neg_evidence(tag_ids: list[int], counter_ids: list[int]):
    """Items carrying evidence against the set — as an UNCORRELATED select,
    so it is one indexed scan of these tags' assignments rather than a
    lookup per candidate row."""
    parts = []
    if tag_ids:
        parts.append(sa.and_(ItemTag.tag_id.in_(tag_ids),
                             ItemTag.negative.is_(True)))
    if counter_ids:
        parts.append(sa.and_(ItemTag.tag_id.in_(counter_ids),
                             ItemTag.negative.is_(False)))
    if not parts:
        return None
    return (select(ItemTag.item_id)
            .where(ItemTag.pending.is_(False), sa.or_(*parts)))


def _all_positive(tag_ids: list[int]):
    """Items carrying EVERY tag of the set positively. One grouped scan of
    those tags' assignments; `count(distinct tag_id)` is what makes it "all"
    rather than "any"."""
    if not tag_ids:
        return None
    return (select(ItemTag.item_id)
            .where(ItemTag.tag_id.in_(tag_ids), ItemTag.negative.is_(False),
                   ItemTag.pending.is_(False))
            .group_by(ItemTag.item_id)
            .having(func.count(sa.distinct(ItemTag.tag_id)) == len(tag_ids)))


def _undecided_set(sel, tag_ids: list[int], counter_ids: list[int]):
    """The candidates, less the ones the set has already ANSWERED — the two
    rules above. A picture carrying ONE of two tags is NOT answered: that is
    exactly the picture the session exists to ask about."""
    counter_ids = [c for c in counter_ids if c not in set(tag_ids)]
    neg = _neg_evidence(tag_ids, counter_ids)
    if neg is not None:
        sel = sel.where(Item.id.notin_(neg))
    allpos = _all_positive(tag_ids)
    if allpos is not None:
        sel = sel.where(Item.id.notin_(allpos))
    return sel


def _label_sets(s: Session, tag_ids: list[int], counter_ids: list[int],
                cap: int, space: str, session_neg: set[int] = frozenset(),
                ) -> tuple[list[int], list[int]]:
    """(positives, negatives) for the fit in one space, up to `cap` each.

    The two-stage shape and the scramble are `tagsort._label_ids`', for its
    reason: the vector test is the expensive half, so the first
    `_LABEL_OVERSAMPLE` x cap by scramble are read off the assignment index
    alone and filtered for vectors afterwards.

    A picture that is BOTH — every tag positive AND evidence against one of
    them, which is what the "both" answer writes — teaches neither side and
    is left out of both lists, as it always was for the single tag.

    `session_neg` is what THIS session answered "doesn't fit" and the
    library was never told (a conjunction's "no" names no tag to write it
    on). Those come first on the negative side and are taken off the
    positive one: somebody has just said this picture is not an example of
    the set, which outranks the assignments that made it look like one.
    """
    counter_ids = [c for c in counter_ids if c not in set(tag_ids)]
    scramble = (ItemTag.item_id * 2654435761) % 4294967291
    # EACH SIDE LESS THE OTHER, in SQL rather than over the samples: the two
    # lists are capped, so intersecting them would only find the overlap
    # that happened to be sampled twice.
    neg_sel = _neg_evidence(tag_ids, counter_ids)
    pos_sel = _all_positive(tag_ids)
    if neg_sel is not None and pos_sel is not None:
        pos_sel = pos_sel.where(ItemTag.item_id.notin_(
            _neg_evidence(tag_ids, counter_ids)))
        neg_sel = neg_sel.where(ItemTag.item_id.notin_(
            _all_positive(tag_ids)))

    def take(base) -> list[int]:
        if base is None:
            return []
        head = [int(i) for i in s.execute(
            base.order_by(scramble).limit(cap * _LABEL_OVERSAMPLE)
        ).scalars().all()]
        with_vec = indexed_ids(s, head, space)
        picked = [i for i in head if i in with_vec][:cap]
        if len(picked) >= cap or len(head) < cap * _LABEL_OVERSAMPLE:
            return picked
        return [int(i) for i in s.execute(
            base.join(Item, Item.id == ItemTag.item_id)
            .where(_has_vector(space)).order_by(scramble).limit(cap)
        ).scalars().all()]

    # The session's own answers are labels in THIS space only where they
    # have a vector in it — the same test every sampled label passes.
    sess = sorted(indexed_ids(s, sorted(session_neg), space)) if session_neg \
        else []
    pos = sorted(set(take(pos_sel)) - set(sess))
    neg = sess + sorted(set(take(neg_sel)) - set(sess))
    return pos, neg


def _residue_set(s: Session, lib: Library, body, tag_ids: list[int],
                 counter_ids: list[int], shown: list[int]) -> list[int]:
    """The candidates for a search SQL cannot describe exactly, less the ones
    the SET has answered — `_undecided_set`'s two rules over a materialized
    pool, since a residue is evaluated in Python and its pool has to be."""
    pool = _pool_ids(s, lib, body)
    counter_ids = [c for c in counter_ids if c not in set(tag_ids)]
    want = set(tag_ids)
    counters = set(counter_ids)
    seen: dict[int, set[int]] = {}
    against: set[int] = set()
    if (want or counters) and pool:
        for chunk in chunked(pool):
            for iid, tag_id, negative in s.execute(
                    select(ItemTag.item_id, ItemTag.tag_id, ItemTag.negative)
                    .where(ItemTag.item_id.in_(chunk),
                           ItemTag.pending.is_(False),
                           ItemTag.tag_id.in_(list(want | counters)))).all():
                iid = int(iid)
                if tag_id in want and not negative:
                    seen.setdefault(iid, set()).add(int(tag_id))
                elif (tag_id in want and negative) or (tag_id in counters
                                                       and not negative):
                    against.add(iid)
    skip = set(shown)
    return [i for i in pool
            if i not in skip and i not in against
            and len(seen.get(i, ())) < len(want)]


def _cap_keeping(keep: list[int], rest: list[int], cap: int,
                 seed: int) -> list[int]:
    """`_cap` with a list that must survive it. The session's own answers
    are the freshest thing said about the set, so the sampler may not drop
    one of them for a row somebody tagged a year ago; past the cap they are
    all there is room for."""
    kept = sorted(set(keep))[:cap]
    room = max(0, cap - len(kept))
    return kept + _cap(sorted(set(rest) - set(kept)), room, seed)


def _score(s: Session, tag_ids: list[int], counter_ids: list[int],
           cand: list[int], spaces: list[str],
           session_neg: set[int] = frozenset(),
           ) -> tuple[dict[int, float], list[float], list[float]]:
    """Fused scores for `cand`, plus the labeled rows' own fused scores per
    side (what the cuts are calibrated on). Empty when nothing can be fit —
    no tag yet, no positives, or no vectors."""
    per_item: dict[int, list[float]] = {}
    per_label: dict[int, list[float]] = {}
    label_sign: dict[int, float] = {}
    if not tag_ids or not cand:
        return {}, [], []
    for space in spaces:
        cids, X = load_matrix(s, cand, space)
        if not len(cids):
            continue
        # Centered on this space's candidate mean, labels included — the
        # session feed's rule (`tagsortmath.center`).
        mu = X.mean(axis=0)
        X = tagsortmath.center(X, mu)
        pos, neg = _label_sets(s, tag_ids, counter_ids, LABEL_CAP, space,
                               session_neg)
        pos = _cap(pos, LABEL_CAP, 11)
        rest = [i for i in neg if i not in set(pos)]
        neg = _cap_keeping([i for i in rest if i in session_neg],
                           [i for i in rest if i not in session_neg],
                           LABEL_CAP, 12)
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
            per_item.setdefault(int(iid), []).append(float(sc))
        # The labeled rows' scores are LEAVE-ONE-OUT (`calibration_scores`),
        # never the fit's own in-sample answers — those sit near ±1
        # whatever a fresh row scores, and cuts read off them put "fits"
        # out of a real positive's reach.
        for iid, sc, sign in zip(lids, taggridmath.calibration_scores(LX, y),
                                 y):
            per_label.setdefault(int(iid), []).append(float(sc))
            label_sign[int(iid)] = float(sign)
    fused = taggridmath.fuse(per_item)
    lab = taggridmath.fuse(per_label)
    pos_scores = [v for i, v in lab.items() if label_sign.get(i, 0) > 0]
    neg_scores = [v for i, v in lab.items() if label_sign.get(i, 0) < 0]
    return fused, pos_scores, neg_scores


def _existing(s: Session, ids: list[int], tag_ids: list[int],
              counter_ids: list[int]) -> dict[int, str]:
    """What each of `ids` already carries of the SET — "positive" (every tag
    of it), "negative" (evidence against one), "both" (both at once, which
    is what the "both" answer writes)."""
    if not ids or not tag_ids:
        return {}
    counter_ids = [c for c in counter_ids if c not in set(tag_ids)]
    want = set(tag_ids)
    counters = set(counter_ids)
    seen: dict[int, set[int]] = {}
    against: set[int] = set()
    for chunk in chunked(ids):
        for iid, tag_id, negative in s.execute(
                select(ItemTag.item_id, ItemTag.tag_id, ItemTag.negative)
                .where(ItemTag.item_id.in_(chunk),
                       ItemTag.pending.is_(False),
                       ItemTag.tag_id.in_(list(want | counters)))).all():
            iid = int(iid)
            if tag_id in want and not negative:
                seen.setdefault(iid, set()).add(int(tag_id))
            elif (tag_id in want and negative) or (tag_id in counters
                                                   and not negative):
                against.add(iid)
    out: dict[int, str] = {}
    for iid in ids:
        full = len(seen.get(iid, ())) == len(want)
        if full and iid in against:
            out[iid] = "both"
        elif full:
            out[iid] = "positive"
        elif iid in against:
            out[iid] = "negative"
    return out


def _labeled(s: Session, tag_ids: list[int], counter_ids: list[int],
             session_neg: set[int] = frozenset()) -> tuple[int, int]:
    """(positives, negatives) the fit can learn from — counted the way the
    labels are chosen, so the chooser's figures and the fit agree. The
    session's own "doesn't fit" answers are among them: they are labels the
    library does not hold, and a line saying otherwise would report the
    session getting no better as it goes."""
    if not tag_ids:
        return (0, 0)
    counter_ids = [c for c in counter_ids if c not in set(tag_ids)]
    neg_sel = _neg_evidence(tag_ids, counter_ids)
    pos_sel = _all_positive(tag_ids)
    neg = set() if neg_sel is None else {
        int(i) for i in s.execute(neg_sel).scalars().all()}
    pos = set() if pos_sel is None else {
        int(i) for i in s.execute(pos_sel).scalars().all()}
    # A picture that is BOTH teaches neither side, so it counts on neither.
    return (len(pos - neg - session_neg),
            len((neg - pos) | session_neg))


@router.post("/next", response_model=TagGridNextOut)
def next_batch(body: TagGridNextRequest,
               s: Session = Depends(get_session),
               lib: Library = Depends(get_library)):
    # THE QUESTION IS A SET, and an answer writes the whole of it.
    rows = [(str(t.name).strip(), str(t.negative or "").strip())
            for t in body.tags if str(t.name).strip()]
    names: list[str] = []
    counters: list[str] = []
    for nm, ctr in rows:
        if nm in names:
            continue
        names.append(nm)
        if ctr and ctr != nm:
            counters.append(ctr)
    if not names:
        raise Invalid("a tag grid session needs a tag",
                      code="taggrid_no_tag")
    if not body.embedders:
        raise Invalid("a tag grid session needs an embedder",
                      code="taggrid_no_embedder")
    # Refused by NAME, each of them (the session feed's rule), and deduped so
    # a client naming one space twice does not count it twice.
    spaces: list[str] = []
    for emb in body.embedders:
        sp = _space_of(emb)
        if sp not in spaces:
            spaces.append(sp)
    by_space = {_space_of(emb): emb for emb in body.embedders}

    for nm, ctr in rows:
        if ctr and ctr == nm:
            raise Invalid("the “doesn't fit” tag must be a different tag",
                          code="taggrid_same_tag")
    ids_by_name = _tag_ids(s, names + counters)
    tag_ids = [i for i in (ids_by_name[n] for n in names) if i is not None]
    counter_ids = [i for i in (ids_by_name[c] for c in counters)
                   if i is not None]
    # THE SESSION'S OWN NEGATIVES: answers it made and the library was never
    # told, because a conjunction's "no" names no tag to write it on. They
    # are labels for the fit (`_label_sets`) and, like everything else this
    # session has answered, out of its pool — the client keeps them in
    # `recent` too, and merging here means a page that forgets to cannot be
    # served a picture it has already said no to.
    session_neg = {int(i) for i in body.session_negatives}
    shown = [int(i) for i in body.recent]
    shown += sorted(session_neg.difference(shown))
    prio_ids = [int(i) for i in body.items]
    count = max(0, int(body.count))

    total: Optional[int] = None
    embedded_n = 0
    coverage: dict[str, int] = {}
    # INCLUDING THE TAGGED: the decided pictures stay in the pool and come
    # back saying what they carry (`existing`), so the session shows the
    # tags already given rather than the classifier's guess.
    keep_all = body.include_tagged
    sel = _pool_select(s, lib, body)
    if sel is not None:
        cand_sel = _without(
            sel if keep_all else _undecided_set(sel, tag_ids, counter_ids),
            shown)
        if count <= 0 or body.want_pool:
            total, embedded_n, per = _counts_by_space(s, cand_sel, spaces)
            coverage = {by_space[sp]: n for sp, n in per.items()}
        if count <= 0:
            return TagGridNextOut(
                pool=total, total=total, embedded=embedded_n,
                coverage=coverage,
                labeled=_labeled(s, tag_ids, counter_ids, session_neg))
        # Through `admitted` (the session feed's rule): a selection against
        # a group scope is otherwise SQLite's cross product of the two lists.
        prio = admitted(s, cand_sel, prio_ids) if prio_ids else []
        rest_sel = _without(cand_sel, prio)
        scored_pool, tail = _pick_split(s, rest_sel, spaces, SCORE_CAP)
    else:
        residue_ids = (
            [i for i in _pool_ids(s, lib, body) if i not in set(shown)]
            if keep_all else
            _residue_set(s, lib, body, tag_ids, counter_ids, shown))
        prio_set = set(prio_ids)
        prio = [i for i in residue_ids if i in prio_set]
        rest = [i for i in residue_ids if i not in prio_set]
        per = {sp: indexed_ids(s, residue_ids, sp) for sp in spaces}
        any_set: set[int] = set().union(*per.values()) if per else set()
        if count <= 0 or body.want_pool:
            total = len(residue_ids)
            embedded_n = len(any_set)
            coverage = {by_space[sp]: len(ids) for sp, ids in per.items()}
        if count <= 0:
            return TagGridNextOut(
                pool=total, total=total, embedded=embedded_n,
                coverage=coverage,
                labeled=_labeled(s, tag_ids, counter_ids, session_neg))
        scored_pool = _cap([i for i in rest if i in any_set], SCORE_CAP,
                           len(shown) // max(1, count))
        tail = [i for i in rest if i not in any_set]
        # Materialized in id order — shuffled for `_pick_split`'s reason.
        rng = random.Random()
        rng.shuffle(scored_pool)
        rng.shuffle(tail)

    # The priority items are always SERVED (a selection leads the batch, the
    # rankings' rule) — and scored beside the rest, so they land in a band
    # rather than always in "undecided". Only the ones THIS batch shows:
    # a selection of sixty thousand scored whole was 2.4 s a press, loading
    # sixty thousand vectors to place twenty-four cards.
    served = prio[:count]
    prio_set = set(prio)
    fused: dict[int, float] = {}
    hi = lo = None
    ordered = False
    if body.smart:
        fused, pos_scores, neg_scores = _score(
            s, tag_ids, counter_ids, served + scored_pool, spaces,
            session_neg)
        if fused:
            ordered = True
            hi, lo = taggridmath.cutoffs(pos_scores, neg_scores)

    queue_ids: list[int] = list(served)
    if ordered:
        # A SET: `i not in prio` over a list is quadratic, and with a large
        # selection it was most of a press.
        rest_ids = [i for i in scored_pool
                    if i in fused and i not in prio_set]
        if rest_ids and len(queue_ids) < count:
            sc = np.array([fused[i] for i in rest_ids], dtype=np.float64)
            idx = taggridmath.compose(sc, count - len(queue_ids), hi, lo,
                                      boundary=body.boundary)
            queue_ids += [rest_ids[int(i)] for i in idx]
    if len(queue_ids) < count:
        # Short of a batch: the unscored trail the scored (and with no fit at
        # all the draw comes as it came, scorable first).
        for i in (scored_pool if not ordered else []) + tail:
            if len(queue_ids) >= count:
                break
            if i not in queue_ids:
                queue_ids.append(i)

    refs = _refs(s, queue_ids)
    existing = (_existing(s, queue_ids, tag_ids, counter_ids)
                if body.include_tagged else {})
    out: list[TagGridItem] = []
    for iid in queue_ids:
        ref = refs.get(iid)
        if ref is None:
            continue
        sc = fused.get(iid)
        b = 0
        if sc is not None:
            b = int(taggridmath.bucket(np.array([sc]), hi, lo)[0])
        out.append(TagGridItem(
            **ref.model_dump(),
            score=sc,
            bucket="positive" if b > 0 else "negative" if b < 0 else "none",
            existing=existing.get(iid),
        ))
    return TagGridNextOut(
        queue=out, pool=total, total=total, embedded=embedded_n,
        coverage=coverage, ordered=ordered,
        labeled=_labeled(s, tag_ids, counter_ids, session_neg),
        cut_hi=hi, cut_lo=lo)
