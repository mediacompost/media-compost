"""The pairing rules, which no API test can see.

`pick_pair` is where a rating session's whole experience comes from, and
what is wrong with a bad one is statistical rather than a raised error: the
same picture keeps coming back, or the order takes far more answers than it
should. So it is exercised as a SESSION — seeded, so the numbers below are
facts about the algorithm rather than a flaky sample.
"""
from __future__ import annotations

import random

from media_compost import rankingmath as rm


def _key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def _session(n_items: int, rounds: int, seed: int):
    """Run a session against a known quality order, exactly as the app does:
    judge, refit, recount, avoid the pair just shown."""
    rng = random.Random(seed)
    pool = list(range(1, n_items + 1))
    truth = {i: rng.gauss(0.0, 1.0) for i in pool}
    pairs: list[tuple[int, int]] = []
    avoid: set[tuple[int, int]] = set()
    shown: list[tuple[int, int]] = []
    counts: dict[int, int] = {}
    scores: dict[int, float] = {}
    for _ in range(rounds):
        got = rm.pick_pair(pool, counts, scores, avoid, rng)
        if got is None:
            break
        a, b = got
        shown.append((a, b))
        avoid.add(_key(a, b))
        pairs.append((a, b) if truth[a] >= truth[b] else (b, a))
        counts = rm.judged_counts(pairs)
        scores = rm.fit(pairs)
    return truth, shown, scores


def _appearances(shown) -> dict[int, int]:
    out: dict[int, int] = {}
    for a, b in shown:
        out[a] = out.get(a, 0) + 1
        out[b] = out.get(b, 0) + 1
    return out


def _worst_window(shown, width: int = 12) -> int:
    """The most times one picture appears in `width` consecutive pairs."""
    worst = 0
    for start in range(max(1, len(shown) - width + 1)):
        worst = max(worst, max(_appearances(shown[start:start + width]).values()))
    return worst


def test_no_picture_is_asked_about_far_more_often_than_the_rest():
    """The reported symptom: "one image often stayed a long time as one of
    the two being compared". It came from the PARTNER rule — `avoid` holds
    pairs, so an item can come back against a different partner every time,
    and an item near the middle of the standings is the nearest neighbour of
    very many first sides. Nothing counted the partner's own judgments.

    Every picture is compared three times on average here; the bound is what
    the least-judged partner rule holds it to, and the old coin-toss among
    the four nearest exceeded it on most of these seeds.

    The twelve-pair window is THREE rather than the two this reached before
    newcomers started joining the order (`test_the_evidence_connects...`),
    and that is the accepted price: on a pool small enough to connect by
    itself, insertion clusters the early answers a little. Three
    appearances in twelve pairs, on a pool where a picture averages three
    across ninety, is not one picture staying in comparison after
    comparison — which the old rule, at five, was.
    """
    for seed in range(1, 9):
        _, shown, _ = _session(60, 90, seed)
        app = _appearances(shown)
        assert max(app.values()) <= 5, (seed, max(app.values()))
        assert _worst_window(shown) <= 3, (seed, _worst_window(shown))
    # And on a pool big enough that a session only scratches it, the spread
    # is at the floor: nothing is asked about more than twice.
    for seed in range(1, 5):
        _, shown, _ = _session(400, 300, seed)
        assert max(_appearances(shown).values()) <= 3
        assert _worst_window(shown) <= 2


def test_the_evidence_connects_so_stopping_early_still_orders_something():
    """A session over ten thousand pictures, abandoned after a hundred
    answers, has to have said something.

    Strengths are relative, so a fit means something only about pictures a
    chain of real comparisons connects. Both sides used to be brand-new —
    the least-judged of ten thousand is always one nobody has touched — so
    a hundred answers made a hundred disjoint PAIRS: two hundred pictures
    compared and not one orderable against another, which
    `enough_comparisons` then refuses to score. Pairing a newcomer with
    someone already placed makes every answer extend the order.
    """
    for seed in range(1, 4):
        _, shown, scores = _session(10000, 100, seed)
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b in shown:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
        placed = list(scores)
        roots = {find(i) for i in placed}
        # ONE order, not a hundred pairs — and enough of it to be worth
        # having: a hundred answers place a hundred and one pictures.
        assert len(roots) == 1, (seed, len(roots))
        assert len(placed) >= 100, (seed, len(placed))
        assert rm.enough_comparisons(len(shown), len(placed)), (
            seed, len(shown), len(placed))


def test_every_picture_is_asked_about_and_the_order_comes_out_right():
    """Coverage and correctness together: an even spread is only worth
    having if the fit it feeds is the true order."""
    for seed in range(1, 5):
        truth, shown, scores = _session(40, 120, seed)
        assert len(_appearances(shown)) == 40, "every picture compared"
        placed = sorted(scores, key=lambda i: scores[i])
        want = sorted(scores, key=lambda i: truth[i])
        # Spearman over the whole pool.
        rank = {i: k for k, i in enumerate(placed)}
        real = {i: k for k, i in enumerate(want)}
        n = len(placed)
        rho = 1 - 6 * sum((rank[i] - real[i]) ** 2 for i in placed) \
            / (n * (n * n - 1))
        assert rho > 0.9, (seed, rho)


def test_the_partner_is_the_least_judged_of_the_nearest():
    """The rule itself, stated over a rigged pool: five items sit at the
    same standing, so the whole `PARTNER_WINDOW` is equidistant from the
    first side and the judged counts alone decide."""
    rng = random.Random(7)
    pool = [1, 2, 3, 4, 5, 6]
    scores = {i: 0.0 for i in pool}
    counts = {1: 0, 2: 9, 3: 9, 4: 9, 5: 9, 6: 9}
    # Item 1 is the least judged, so it leads the first side; every partner
    # is equally near, so the least judged among THEM is the answer — and
    # with 2 the only one at a lower count, it is 2 every time.
    counts[2] = 1
    for _ in range(20):
        a, b = rm.pick_pair(pool, counts, scores, avoid=set(), rng=rng)
        assert {a, b} == {1, 2}, (a, b)


def test_enough_comparisons_is_the_chain_that_could_order_them():
    # A deliberate chain is the boundary and passes: four pictures, three
    # comparisons.
    assert rm.enough_comparisons(3, 4)
    assert not rm.enough_comparisons(2, 4)
    # Two pictures and one answer is the whole truth about those two.
    assert rm.enough_comparisons(1, 2)
    assert not rm.enough_comparisons(0, 2)
    # Nothing to order, nothing to refuse.
    assert rm.enough_comparisons(0, 0)
    assert rm.enough_comparisons(0, 1)
