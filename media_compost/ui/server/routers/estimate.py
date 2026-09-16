"""Estimating a ranking's scale over pictures nobody rated, and tagging on it.

A rating session places pictures on an axis a pair at a time; past a few
hundred answers the standings say what the axis IS, and the same embedding
spaces the tag batch orders by can carry that answer to the pictures nobody
has been shown. This is that: fit the ranking's own numbers over its rated
pictures, predict them for a scope, and write the tags a person asked for at
the thresholds they set.

**WHAT IT WRITES IS AN ORDINARY TAG.** It always was: a guess from pixels
is not evidence of the kind a rating session gathers, so it could never be
one of the derived score rows a `rebuild` refit. There are no derived rows
at all any more (rung v31 — a ranking orders pictures and tags none of
them), which makes this the ONLY thing that writes anything onto a picture
on a ranking's account: what was asked for in so many words, through the
quick-assign stamp, logged and revertible one by one, plus the group
memberships the rules name.

**TWO PATHS, one body.** `/estimate` previews — a bounded scrambled sample,
the counts exact over what it looked at, nothing written; it is a read-only
POST by pattern, since a stale tab reading numbers harms nobody.
`/estimate/apply` queues the write as a background JOB and answers with its
id: the scope is the library, so a write can be minutes of walking and
hundreds of thousands of tag rows, which is not something to hold a request
open for. It is NOT read-only and so is default-denied to a stale tab, which
is the right answer for the press that stamps the tags.

The flag that used to choose between them lived in the BODY, and that is
what makes two paths the better shape: the stale-tab check is keyed by
path, so one path meaning both would have had to deny the harmless half too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from media_compost import estimatemath, rankingmath, tagsortmath
from media_compost.db import Item, chunked
from media_compost.ops import (
    Ctx, groups as ops_groups, rankings as ops_rankings, tagassign)
from media_compost.ops.errors import Invalid

from ... import jobs
from ...itemvec import load_matrix
from ..deps import Library, get_ctx, get_library
from ..schemas import (
    EstimateRuleOut,
    RankingEstimateJobOut,
    RankingEstimateOut,
    RankingEstimateRequest,
)
from .rankings import _refs
from .tagsort import _pool_ids, _pool_select, _spaces_of

router = APIRouter(prefix="/api/rankings", tags=["rankings"])

#: The embedder a request that names none is scored in — the space
#: every library indexes first.
DEFAULT_EMBEDDER = "dinov2_small"

#: How many pictures the sample shows — the dialog's "does this look right
#: at all" strip, the ends of the estimate rather than a listing.
SAMPLE = 12

#: How many candidates are scored at a time — the width of one vector load,
#: one matmul and one pass of the rules. The scope is the library, so this
#: is what keeps a million-item estimate a bounded amount of memory at any
#: moment rather than a list of a million ids and a dict of a million
#: floats.
CANDIDATE_PAGE = 4_000

#: How many pictures a PREVIEW looks at. The counts it shows are exact over
#: what it scanned and it says which that was — a preview runs on every edit
#: of a rule, and reading every vector in a million-item library for a
#: number nobody has committed to yet is minutes of work per keystroke. The
#: draw is scrambled, not the first N by id.
PREVIEW_SCAN = 20_000

#: How much of the job's progress bar the SCAN owns. The write is the rest:
#: two phases of one job, so a bar that reached 100% and then went on
#: writing for a minute would be a lie about the half that matters.
_SCAN_SHARE = 70

#: Items stamped (and committed) at a time — the quick-assign view write's
#: figure, for the same reason: a long stamp holds the write lease.
CHUNK = 500


def _rated_scores(s: Session, ranking, pool_ids: list[int],
                  ) -> dict[int, float]:
    """The ranking's own number per RATED picture: its standings, bucketed
    the way `rebuild` buckets them, on the range the tags are named for.

    The pools are fitted TOGETHER — one scale is being estimated, and a
    per-pool fit would answer three different numbers for one picture.
    Disabled pools are in it: they are rated in, and what the switch
    withholds is the TAGGING, which this does not do.
    """
    ids = [int(i) for i in pool_ids] or None
    _comparisons, strengths = ops_rankings._fitted(s, ranking, ids)
    if not strengths:
        return {}
    n = ranking.bucket_hi - ranking.bucket_lo + 1
    got = rankingmath.buckets(strengths, n)
    return {i: float(ranking.bucket_lo + b) for i, b in got.items()}


def _fit_spaces(s: Session, spaces: list[str], rated: dict[int, float],
                ) -> list[tuple[np.ndarray, np.ndarray, float]]:
    """Per space that can answer: (mu, w, b), fitted ONCE from the rated
    rows.

    Once, because the walk below crosses the whole scope: refitting per page
    would redo the same solve over the same few hundred rated pictures for
    every four thousand candidates.

    The rows are CENTERED on the mean of the RATED pictures, `tagsortmath`'s
    rule and for its reason: a ViT's rows share a large common direction, and
    a fit on raw rows spends its capacity on it. `mu` travels with the fit
    because the candidates have to be centered the same way.
    """
    out: list[tuple[np.ndarray, np.ndarray, float]] = []
    rated_ids = sorted(rated)
    for space in spaces:
        lids, LX = load_matrix(s, rated_ids, space)
        if len(lids) < estimatemath.MIN_RATED:
            continue
        mu = LX.mean(axis=0)
        y = np.asarray([rated[i] for i in lids], dtype=np.float32)
        got = estimatemath.fit(tagsortmath.center(LX, mu), y)
        if got is None:
            continue
        w, b = got
        out.append((mu, w, b))
    return out


def _page_scores(s: Session, spaces: list[str],
                 fits: list[tuple[np.ndarray, np.ndarray, float]],
                 ids: list[int], lo: float, hi: float) -> dict[int, float]:
    """One estimate per candidate on this page that the spaces can answer
    for — each space predicted on its own, then fused (the mean of the
    spaces that had a vector for it)."""
    per_space: list[dict[int, float]] = []
    for space, (mu, w, b) in zip(spaces, fits):
        cids, CX = load_matrix(s, ids, space)
        if not cids:
            continue
        vals = estimatemath.predict(tagsortmath.center(CX, mu), w, b, lo, hi)
        per_space.append({int(i): float(v) for i, v in zip(cids, vals)})
    return estimatemath.fuse(per_space)


def _scramble():
    """The deterministic pseudo-random order a SAMPLE is drawn in — the
    session feed's own (`tagsort._label_ids`), so the preview looks at a
    spread of the scope rather than its oldest corner, and looks at the SAME
    spread every time it is asked."""
    return (Item.id * 2654435761) % 4294967291


def _walk(s: Session, lib: Library, body, limit: Optional[int]):
    """The candidates, PAGE BY PAGE.

    A page at a time because the scope is the library: at a million items the
    old shape — every id into a Python list, every score into a dict — was
    tens of megabytes before a single tag was written, which is why there was
    a cap refusing anything past 200,000. There is no cap now; what is
    bounded is how much is in hand at once.

    ``limit`` is the PREVIEW's sample: a bounded, scrambled draw rather than
    the first N by id, since "the oldest 20,000" is not what the rest of the
    library looks like. It is drawn BEFORE the rated pictures are dropped
    (that set can be a hundred thousand ids, which is not something to put
    in an ``IN``), so a scope that is mostly rated yields a smaller sample —
    which is what ``scanned`` says.
    """
    if body.items:
        ids = [int(i) for i in body.items]
        for k in range(0, len(ids), CANDIDATE_PAGE):
            yield ids[k:k + CANDIDATE_PAGE]
        return
    sel = _pool_select(s, lib, body)
    if sel is None:
        # A search SQL cannot describe exactly is decided in Python, so its
        # pool is materialized as it always was — and then paged like any
        # other.
        ids = _pool_ids(s, lib, body)
        if limit is not None and len(ids) > limit:
            ids = sorted(ids, key=lambda i: (i * 2654435761) % 4294967291)
            ids = ids[:limit]
        for k in range(0, len(ids), CANDIDATE_PAGE):
            yield ids[k:k + CANDIDATE_PAGE]
        return
    if limit is not None:
        ids = [int(i) for i in s.execute(
            sel.order_by(_scramble()).limit(limit)).scalars().all()]
        for k in range(0, len(ids), CANDIDATE_PAGE):
            yield ids[k:k + CANDIDATE_PAGE]
        return
    # KEYSET, not OFFSET: an offset past a million rows re-walks them.
    last = 0
    while True:
        page = [int(i) for i in s.execute(
            sel.where(Item.id > last).order_by(Item.id)
            .limit(CANDIDATE_PAGE)).scalars().all()]
        if not page:
            return
        yield page
        last = page[-1]


def _scope_total(s: Session, lib: Library, body) -> Optional[int]:
    """How many pictures the scope holds — for the preview to say whether it
    looked at all of them. None where it cannot be had cheaply."""
    if body.items:
        return len({int(i) for i in body.items})
    sel = _pool_select(s, lib, body)
    if sel is None:
        return len(_pool_ids(s, lib, body))
    return int(s.execute(
        select(func.count()).select_from(sel.subquery())).scalar_one())


def _split(names: list[str]) -> tuple[list[str], list[str]]:
    """A rule's tag list into (positive, negative) — the importer's leading
    `-`, so one field says both."""
    pos: list[str] = []
    neg: list[str] = []
    for raw in names:
        name = str(raw).strip()
        if not name:
            continue
        if name.startswith("-"):
            rest = name[1:].strip()
            if rest:
                neg.append(rest)
        else:
            pos.append(name)
    return pos, neg


@dataclass
class _Fitted:
    """What the ranking's own evidence says, ready to score with: the rated
    pictures' numbers, the spaces, one fit per space, and the range the
    scale runs on. Built once per request (and once per job run), because
    the walk that follows crosses the whole scope and refitting per page
    would redo the same solve over the same few hundred pictures."""
    rated: dict[int, float]
    spaces: list[str]
    fits: list[tuple[np.ndarray, np.ndarray, float]]
    lo: float
    hi: float


def _prepare(ctx: Ctx, ranking, body: RankingEstimateRequest) -> _Fitted:
    """Validate the request and fit — everything both paths do first.

    The apply path runs it too, before it queues anything: a rule that runs
    downward and a ranking with too little evidence are answers a person
    should get from the press, not from a job row that failed a minute later.
    """
    s = ctx.session
    pool_ids = list(body.pool_ids)
    if not pool_ids:
        pool_ids = [lg.id for lg in ops_rankings.pools_of(s, ranking)]
    rated = _rated_scores(s, ranking, pool_ids)
    if len(rated) < estimatemath.MIN_RATED:
        raise Invalid(
            "the ranking needs at least {n} rated pictures before its scale "
            "can be estimated",
            {"n": estimatemath.MIN_RATED}, code="estimate_too_few_rated")
    # NO EMBEDDER NAMED is the default space, not a refusal: only the page
    # knows which models are set up (that is what its picker reads), so a
    # script that says nothing gets the one every library indexes first.
    spaces, _by_space = _spaces_of(
        body.embedders[0] if body.embedders else DEFAULT_EMBEDDER,
        body.embedders)
    return _Fitted(rated=rated, spaces=spaces,
                   fits=_fit_spaces(s, spaces, rated),
                   lo=float(ranking.bucket_lo), hi=float(ranking.bucket_hi))


def _bands(body: RankingEstimateRequest
           ) -> list[tuple[Optional[float], Optional[float]]]:
    """The request's rules as CONTIGUOUS BANDS, in the order the request
    lists them.

    `estimatemath.bands` sorts and pairs them up; this puts the answers back
    beside the rules that asked, since every count, sample and write is
    reported per rule at the position it arrived in. A rule with no number
    at all takes nothing — a half-typed row in the dialog is not a claim.
    """
    lows = [r.min for r in body.rules]
    have = sorted(x for x in lows if x is not None)
    top = {low: high for low, high in estimatemath.bands(have)}
    return [(x, top.get(x)) if x is not None else (None, None) for x in lows]


@dataclass
class _Scan:
    """What one pass over the scope found."""
    estimated: int = 0
    unindexed: int = 0
    scanned: int = 0
    #: What the walk HANDED OVER, rated pictures included — the limit is
    #: about the draw, so whether it cut anything off is a question about
    #: this and not about what survived the filter.
    drawn: int = 0
    #: Per rule: how many pictures it claims.
    matched: list[int] = field(default_factory=list)
    #: Per rule: WHICH ones, where the caller asked to collect them (the
    #: write does; a preview wants the count and a handful, not a million
    #: ids).
    ids: Optional[list[list[int]]] = None
    #: Per rule: the highest few, kept as the walk goes.
    best: list[list[tuple[float, int]]] = field(default_factory=list)
    #: Whether a cancel cut the walk short.
    stopped: bool = False


def _scan(s: Session, lib: Library, body: RankingEstimateRequest,
          fit: _Fitted, *, limit: Optional[int], collect: bool,
          on_page=None, stopped=None) -> _Scan:
    """Walk the scope a page at a time, scoring and testing the rules.

    ``on_page(drawn)`` is called after every page (the job's progress bar);
    ``stopped()`` is asked before every one (its cancel). Neither is set on
    the preview path, which is one bounded pass.
    """
    ranges = _bands(body)
    out = _Scan(matched=[0] * len(body.rules),
                ids=[[] for _ in body.rules] if collect else None,
                best=[[] for _ in body.rules])
    rated = fit.rated
    for page in _walk(s, lib, body, limit):
        if stopped is not None and stopped():
            out.stopped = True
            break
        out.drawn += len(page)
        if on_page is not None:
            on_page(out.drawn)
        # THE PICTURES THE RANKING HAS PLACED ARE ALWAYS COVERED; the
        # switch is whether the rest are GUESSED AT as well.
        if not body.estimate_unranked:
            page = [i for i in page if i in rated]
        if not page:
            continue
        out.scanned += len(page)
        scores = _page_scores(s, fit.spaces, fit.fits, page, fit.lo, fit.hi)
        # A RATED PICTURE KEEPS ITS OWN NUMBER. Where they are covered at
        # all the fit would answer something NEAR their standing rather than
        # it — a guess laid over an answer, and one that could put a picture
        # the ranking placed at 9 in a different band depending on the
        # noise. The standings win.
        for i in page:
            if i in rated:
                scores[i] = rated[i]
        out.estimated += len(scores)
        out.unindexed += len(page) - len(scores)
        for k, (low, high) in enumerate(ranges):
            if low is None:
                continue          # a rule with no number claims nothing
            for i, v in scores.items():
                if not estimatemath.in_range(low, high, v):
                    continue
                out.matched[k] += 1
                if out.ids is not None:
                    out.ids[k].append(i)
                out.best[k].append((v, i))
            if len(out.best[k]) > SAMPLE:
                # BY SCORE, THEN BY ID: ties are the common case at the top
                # of a range, and an order that fell back to the walk's own
                # would make the strip depend on the page size.
                out.best[k].sort(key=lambda t: (-t[0], t[1]))
                del out.best[k][SAMPLE:]
    for k in range(len(out.best)):
        out.best[k].sort(key=lambda t: (-t[0], t[1]))
        del out.best[k][SAMPLE:]
    return out


def _write(ctx: Ctx, rules, per_rule_ids: list[list[int]], *,
           on_chunk=None, stopped=None) -> tuple[int, int]:
    """Stamp each rule's tags and join its groups. Returns
    (assignments changed, pictures touched).

    WRITTEN IN COMMITTED CHUNKS, the whole-view stamp's shape and for its
    reason: `stamp` is one bulk pass, and what is chunked is the transaction
    around it. That is also what makes the cancel mean the useful thing —
    what has been written STAYS, because a tag somebody asked for is not a
    partial artifact like a half-rendered video.
    """
    s = ctx.session
    written = 0
    touched = 0
    for rule, ids in zip(rules, per_rule_ids):
        pos, neg = _split(rule.tags)
        gids = [int(g) for g in rule.groups]
        if not ids or (not pos and not neg and not gids):
            continue
        for start in range(0, len(ids), CHUNK):
            if stopped is not None and stopped():
                return written, touched
            part = ids[start:start + CHUNK]
            if pos or neg:
                written += tagassign.stamp(ctx, part, pos, neg)
            if gids:
                # An estimate only ever ADDS: it never unsays what somebody
                # filed by hand.
                ops_groups.bulk_membership(ctx, part, add=gids, remove=[])
            s.commit()
            touched += len(part)
            if on_chunk is not None:
                on_chunk(touched)
    return written, touched


@router.post("/{ranking_id}/estimate", response_model=RankingEstimateOut)
def estimate_ranking(ranking_id: int, body: RankingEstimateRequest,
                     ctx: Ctx = Depends(get_ctx),
                     lib: Library = Depends(get_library)):
    """What the rules WOULD claim, over a bounded sample of the scope."""
    s = ctx.session
    ranking = ops_rankings.by_id(ctx, ranking_id)
    fit = _prepare(ctx, ranking, body)
    got = _scan(s, lib, body, fit, limit=PREVIEW_SCAN, collect=False)
    # THE DRAW WAS CUT SHORT, or it was not. Asked of what the walk handed
    # over rather than of what was scored: dropping the rated pictures is
    # not the sample stopping early. The scope's own size is counted only
    # where there is something to say about it — a `count(*)` at a million
    # items is not something to do on every keystroke for a line nobody
    # would then read.
    partial = got.drawn >= PREVIEW_SCAN
    total = _scope_total(s, lib, body) if partial else None

    # A SAMPLE PER RULE — a rule is a claim about pictures, and the only way
    # to see whether the claim travelled is to look at what THAT rule takes.
    # Highest first inside each, and the refs fetched for all of them at
    # once so a dialog full of rules is still two reads.
    per_rule = [[i for _v, i in rows] for rows in got.best]
    refs = _refs(s, sorted({i for ids in per_rule for i in ids}),
                 members=False)
    score_of = {i: v for rows in got.best for v, i in rows}
    return RankingEstimateOut(
        rated=len(fit.rated),
        estimated=got.estimated,
        # NOT INDEXED is what the estimate could not answer for — a rated
        # picture is answered by its own standing, vector or no vector.
        unindexed=got.unindexed,
        # A PREVIEW SAYS WHETHER IT SAW EVERYTHING. Where it did not, its
        # numbers are exact over what it scanned and nothing more.
        scanned=got.scanned,
        partial=partial,
        total=total,
        rules=[EstimateRuleOut(
            matched=n, tags=list(rule.tags), groups=list(rule.groups),
            sample=[refs[i] for i in shown if i in refs],
            sample_scores=[round(score_of[i], 2) for i in shown if i in refs])
            for rule, n, shown in zip(body.rules, got.matched, per_rule)],
    )


@router.post("/{ranking_id}/estimate/apply",
             response_model=RankingEstimateJobOut)
def apply_estimate(ranking_id: int, body: RankingEstimateRequest,
                   ctx: Ctx = Depends(get_ctx),
                   lib: Library = Depends(get_library)):
    """Queue the write. Answers with the job, not with what it will write."""
    ranking = ops_rankings.by_id(ctx, ranking_id)
    # FIT BEFORE QUEUEING: a refusal belongs to the press.
    _prepare(ctx, ranking, body)
    jid = lib.jobs.enqueue_estimate(
        {"ranking_id": ranking.id, "body": body.model_dump(mode="json")},
        username=ctx.username or "")
    return RankingEstimateJobOut(job_id=jid)


def run_estimate_job(ctx: Ctx, lib: Library, options: dict, *,
                     progress=None, stopped=None) -> str:
    """THE JOB.

    It lives here, beside the preview, because the two must answer the same
    thing: a person reads the preview's counts and presses the button, and a
    second copy of the fit or of the walk would be a second answer to argue
    with. What the job adds is a progress figure, a cancel and the write.

    ``progress(pct, message)`` and ``stopped()`` are the queue's; the
    returned string is the job's summary message.
    """
    s = ctx.session
    body = RankingEstimateRequest.model_validate(options.get("body") or {})
    ranking = ops_rankings.by_id(ctx, int(options["ranking_id"]))
    fit = _prepare(ctx, ranking, body)
    # THE DENOMINATOR IS ASKED ONCE. A `count(*)` over the scope is one
    # index walk; doing it per page would make the progress bar cost more
    # than the estimate.
    total = _scope_total(s, lib, body) or 0

    def on_page(drawn: int) -> None:
        if progress is None:
            return
        # The scan is the long half at a million items, but the write is not
        # free either, so the bar is split rather than run twice from zero.
        pct = int(drawn * _SCAN_SHARE / total) if total else 0
        progress(pct, f"Estimating — {drawn} / {total}")

    got = _scan(s, lib, body, fit, limit=None, collect=True,
                on_page=on_page, stopped=stopped)
    claimed = got.ids or [[] for _ in body.rules]
    want = sum(len(ids) for ids in claimed)

    def on_chunk(done: int) -> None:
        if progress is None:
            return
        pct = _SCAN_SHARE + int(done * (100 - _SCAN_SHARE) / want) if want else 100
        progress(pct, f"Writing tags — {done} / {want}")

    written, touched = _write(ctx, body.rules, claimed,
                              on_chunk=on_chunk, stopped=stopped)
    if got.stopped or (stopped is not None and stopped()):
        return f"canceled — {written} tags on {touched} pictures"
    return f"{written} tags on {touched} pictures"


# REGISTERED RATHER THAN IMPORTED: the layering runs server → jobs and never
# back, so the queue cannot reach in here — it is handed the work instead,
# the way the trainer hands the app its `release_models`. What it gets is
# the work alone; the `Ctx`, the progress and the cancel are the queue's.
jobs.register_runner("estimate", run_estimate_job)
