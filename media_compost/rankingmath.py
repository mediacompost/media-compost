"""The pairwise-ranking math, pure and separately testable.

Judgments in, standings out. ``fit`` is Bradley–Terry by minorization-
maximization with a weak virtual-opponent prior, which is the smallest model
that does what the feature needs: it turns "A beat B" pairs into one strength
per item, it copes with the sparse, incrementally grown comparison graphs a
rating session produces (the prior anchors items and components the graph
does not connect, instead of letting their strengths run away), and it is
deterministic — the same judgments always fit to the same standings, which is
what makes the standings reproducible.

``buckets`` turns strengths into the 0–9 rank buckets a person reads:
equal-population percentiles over the scored items, ties broken by item id so
the answer cannot depend on dict order. Percentile rather than absolute
thresholds deliberately — a preference axis has no units, so "the top tenth"
is the only claim the numbers support.

``pick_pair`` chooses what to ask next: the least-judged items first, partners
near them in the current standings (uncertain, close pairs are the
informative ones), skipped and recently shown pairs avoided. It takes its
randomness as a ``random.Random`` like every seeded routine in this codebase.
"""

from __future__ import annotations

import math
import random

#: How many rank buckets a ranking has. The score-tag names are derived from
#: it (`<prefix>:0` … `<prefix>:9`), so it is a constant, not a setting.
BUCKETS = 10

#: HOW MANY of the nearest standings the partner is drawn from. The pick is
#: the LEAST-JUDGED of them (see `pick_pair`), so this is the width of the
#: band inside which "who has been asked about least" gets to decide.
PARTNER_WINDOW = 8

#: The virtual-opponent prior: every item is given this many wins AND losses
#: against a fixed strength-1.0 opponent. Small against even a handful of real
#: judgments, decisive for an item with none — its strength stays at the
#: middle instead of diverging, and disconnected components stay comparable.
PRIOR = 0.5


def fit(pairs: list[tuple[int, int]],
        items: list[int] | None = None,
        iters: int = 200, tol: float = 1e-9,
        ties: list[tuple[int, int]] | None = None) -> dict[int, float]:
    """Bradley–Terry strengths from decisive ``(winner, loser)`` pairs and
    ``ties`` — "about equal" answers, the standard half-win-each treatment:
    one game between the two, half a win to each side, which is evidence
    pulling the pair TOGETHER exactly as strongly as a decisive answer pulls
    it apart (fractional wins are fine for the MM update).

    Returns log-strengths keyed by item id, mean-centred so the numbers are
    comparable run to run. ``items`` may name ids beyond the pairs (they sit
    at the prior's centre); ids only ever mentioned in pairs are included
    automatically.
    """
    ids: set[int] = set(items or [])
    for w, loser in pairs:
        ids.add(w)
        ids.add(loser)
    for a, b in ties or []:
        ids.add(a)
        ids.add(b)
    if not ids:
        return {}
    wins: dict[int, float] = {i: PRIOR for i in ids}
    games: dict[int, list[int]] = {i: [] for i in ids}
    for w, loser in pairs:
        wins[w] += 1.0
        games[w].append(loser)
        games[loser].append(w)
    for a, b in ties or []:
        wins[a] += 0.5
        wins[b] += 0.5
        games[a].append(b)
        games[b].append(a)
    p = {i: 1.0 for i in ids}
    for _ in range(iters):
        moved = 0.0
        # Jacobi-style update from a snapshot, so the result cannot depend on
        # the iteration order of a set of ids.
        prev = dict(p)
        for i in ids:
            denom = 2.0 * PRIOR / (prev[i] + 1.0)
            for j in games[i]:
                denom += 1.0 / (prev[i] + prev[j])
            new = wins[i] / denom if denom > 0 else prev[i]
            moved = max(moved, abs(new - prev[i]))
            p[i] = new
        if moved < tol:
            break
    logs = {i: math.log(v) for i, v in p.items() if v > 0}
    mean = sum(logs.values()) / len(logs)
    return {i: v - mean for i, v in logs.items()}


def buckets(scores: dict[int, float], n: int = BUCKETS) -> dict[int, int]:
    """Rank buckets, 0 (worst) … n-1 (best), by position in the ordering.

    Endpoint-INCLUSIVE: an untied best item is always n-1 and an untied worst
    always 0, however few items are scored — plain equal-population
    percentiles never hand out the top bucket below n items, and "my best
    picture is an 8" is the arithmetic showing through. For large sets the
    two agree to within a bucket.

    ITEMS WITH EQUAL SCORES SHARE A BUCKET — the one their mean position
    lands on. The old rule split them by item id, which was harmless while
    equal scores only arose by accident and wrong the moment "about equal"
    became an answer: two pictures whose ONLY evidence is a tie fit to
    identical strengths, and by-id splitting filed one at 0 and one at 9 —
    the loudest possible way to say the opposite of what was judged."""
    if not scores:
        return {}
    ordered = sorted(scores, key=lambda i: (scores[i], i))
    total = len(ordered)
    if total == 1:
        return {ordered[0]: n - 1}
    out: dict[int, int] = {}
    i = 0
    while i < total:
        j = i
        while (j + 1 < total
               and abs(scores[ordered[j + 1]] - scores[ordered[i]]) < 1e-9):
            j += 1
        bucket = round((i + j) / 2 * (n - 1) / (total - 1))
        for k in range(i, j + 1):
            out[ordered[k]] = bucket
        i = j + 1
    return out


def enough_comparisons(judgments: int, scored: int) -> bool:
    """Whether this many comparisons can ORDER this many pictures at all.

    A fit is only as meaningful as the comparison GRAPH behind it: strengths
    are relative, so two pictures are comparable only through a chain of
    real judgments between them. Connecting ``n`` pictures takes at least
    ``n - 1`` comparisons — fewer, and the graph is necessarily in pieces,
    whose order relative to each other is `PRIOR` speaking rather than
    anything anybody judged. `buckets` cannot know that: it spreads whatever
    it is handed across the whole 0…9 range, endpoint-inclusive, so two
    pictures and one click produce the loudest claim the scale can make.

    So this is what a pool is asked before its standings are spent on
    anything. It is a NECESSARY condition and deliberately not a
    sufficient one — a graph with ``n - 1`` edges can still be disconnected,
    and the sufficient test (actual connectivity) has a failure mode nobody
    would want: one stray unconnected pair would silently take every score
    in the pool away. This one only ever withholds tags from evidence that
    could not have ordered the pictures however it was arranged, which is
    the case worth withholding them from.

    A deliberate chain — "A beats B beats C beats D", three comparisons over
    four pictures — is exactly the boundary, and it scores.
    """
    return judgments >= max(0, scored - 1)


def judged_counts(pairs: list[tuple[int, int]]) -> dict[int, int]:
    """Judgments per item — what "least judged" means to the selector.
    Callers pass decisive pairs and ties concatenated: a tie answered the
    question just as much as a pick did."""
    out: dict[int, int] = {}
    for w, loser in pairs:
        out[w] = out.get(w, 0) + 1
        out[loser] = out.get(loser, 0) + 1
    return out


def _key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def pick_pair(pool: list[int], counts: dict[int, int],
              scores: dict[int, float],
              avoid: set[tuple[int, int]],
              rng: random.Random,
              priority: set[int] | None = None) -> tuple[int, int] | None:
    """The next pair to ask about, or None when nothing pairable is left.

    ``avoid`` holds normalized (lo, hi) pairs — skipped ones, and the ones the
    session has just shown. The first side is drawn from the least-judged
    items (random among near-ties, so a fresh ranking does not walk the pool
    in id order); the partner is the LEAST-JUDGED of the `PARTNER_WINDOW`
    nearest standings that are not avoided — except for a first side nobody
    has judged at all, whose partner is the least-judged picture ALREADY IN
    the comparison graph.

    THAT EXCEPTION IS WHAT MAKES STOPPING EARLY WORTH ANYTHING. Strengths
    are relative, so a fit says something only about pictures a chain of
    real comparisons connects. Without it, both sides of every pair on a
    big pool were brand-new — the least-judged item of ten thousand is
    always one nobody has touched — so 100 answers produced 100 disjoint
    PAIRS: 200 pictures compared and not one of them orderable against
    another, which `enough_comparisons` then correctly refuses to score.
    Pairing a newcomer with someone already placed makes every answer
    EXTEND the order instead of starting another island: 100 answers, 101
    pictures, one order. Its own standing is 0.0 — a placeholder, not a
    measurement — so "nearest" means nothing for it anyway, and spending
    the choice on the least-judged of the graph is what keeps the
    inserters from becoming the repetition this rule's sibling exists to
    prevent.

    Measured, 5 seeds, at the point somebody gives up:

    ====================  ==================  =============  ==========
    pool / comparisons    largest orderable   scores at all   Spearman
    ====================  ==================  =============  ==========
    10000 / 200           2 -> 201            no -> yes       — -> .743
    400 / 300             18 -> 301           no -> yes       — -> .742
    150 / 150             106 -> 150          yes             .796 -> .765
    60 / 90               60 -> 60            yes             .892 -> .869
    ====================  ==================  =============  ==========

    The last two rows are what it costs: on a pool small enough to connect
    by itself, a couple of hundredths of Spearman and one more appearance
    in a twelve-pair window. The first two are what it buys, and they are
    the difference between an answer and none.

    THAT SECOND RULE USED TO BE A COIN TOSS AMONG THE FOUR NEAREST, and
    "least judged" applied to the first side only — which is how one picture
    came to sit in pair after pair while the other side changed. Nothing
    pushed a partner away: ``avoid`` holds PAIRS, so an item can be asked
    about against a different partner every single time, and an item near
    the middle of the standings is the nearest neighbour of very many first
    sides. (Early on it is worse than that: every unjudged item scores 0.0
    by default, so the whole pool is equidistant and the same few keep
    coming back.) Counting the partner's own judgments is what breaks it,
    and it costs nothing: inside a band of near-equal standings the choice
    was arbitrary anyway, so spending it on the item nobody has asked about
    is free.

    MEASURED over simulated sessions against a known order, 12 seeds, at
    the point a session is actually in the middle of (before -> after):

    ====================  ==============  ================  ===========
    pool / comparisons    busiest picture  worst in any 12   Spearman
    ====================  ==============  ================  ===========
    60 / 90               5.0 -> 3.9       2.50 -> 2.00      .867 -> .884
    150 / 150             3.9 -> 3.0       2.33 -> 1.83      .757 -> .780
    400 / 300             2.1 -> 2.0       1.67 -> 1.42      .685 -> .682
    ====================  ==============  ================  ===========

    At 60 pictures and three comparisons each, the busiest was shown five
    times against a mean of three — 67% above it, which is what "that one
    keeps coming back" is — and is now 30% above. The ORDER arrives sooner
    with it on the pools where there is enough evidence to have an order at
    all, which is the same effect from the other side: evenly spread
    comparisons are what a fit has to work with. On a big sparse pool the
    order is unchanged and only the repetition improves.

    ``priority`` items lead the first-side order outright — a session opened
    over a selection places THOSE pictures first, each against partners from
    the whole pool, and the ordinary rule takes over once they run out of
    pairs worth asking.
    """
    if len(pool) < 2:
        return None
    prio = priority or set()
    by_count = sorted(pool, key=lambda i: (0 if i in prio else 1,
                                           counts.get(i, 0), rng.random()))
    # The scan window covers the whole priority set plus the ordinary
    # allowance: a large exhausted selection at the front must not eat the
    # window and answer None while ordinary items still pair fine.
    for a in by_count[: max(8, len(pool) // 8) + len(prio)]:
        sa = scores.get(a, 0.0)
        partners = [i for i in pool if i != a
                    and _key(a, i) not in avoid]
        if not partners:
            continue
        if not counts.get(a, 0):
            # A NEWCOMER JOINS THE ORDER rather than starting an island.
            placed = [i for i in partners if counts.get(i, 0)]
            if placed:
                b = min(placed, key=lambda i: (counts.get(i, 0), rng.random()))
                return (a, b) if rng.random() < 0.5 else (b, a)
        partners.sort(key=lambda i: (abs(scores.get(i, 0.0) - sa),
                                     rng.random()))
        b = min(partners[:PARTNER_WINDOW],
                key=lambda i: (counts.get(i, 0), rng.random()))
        return (a, b) if rng.random() < 0.5 else (b, a)
    return None
