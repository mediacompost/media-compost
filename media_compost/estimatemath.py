"""Estimating a ranking's own scale over pictures nobody has rated — pure.

A ranking's standings are a number per RATED picture: fit from the pairwise
judgments, spread over the ranking's bucket range. This module answers the
next question — what would that number be for a picture the ranking has
never been shown — from the pictures it HAS, in an embedding space.

``fit`` is the tag batch's ridge (``tagsortmath``) with two differences, and
they are the whole reason this is its own module rather than a flag over
there: the targets are CONTINUOUS (a bucket number, not ±1), so the
one-class and no-positive shortcuts have no meaning here; and the answer
carries an INTERCEPT, because a score has a scale — a direction alone says
"more like the 9s than the 0s" where what is wanted is a number on the same
0…9 the person reads. Everything else is deliberately the same: dual form
(the solve is over the RATED rows, a few hundred at most), no learning rate,
nothing to diverge, deterministic.

An estimate is NEVER evidence. A ranking's standings are fitted from its
judgments and from nothing else, and a number guessed from pixels is not an
answer anybody gave. What an estimate writes is what the person asked for
in so many words: ordinary tags, under thresholds they set.

numpy only, like its sibling.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np

#: L2 regularization. The rows are L2-normalized and centered as they are for
#: the tag batch, but the targets here are a 0…9-sized scale rather than ±1,
#: so the same penalty bites about a tenth as hard per unit of target — which
#: is why this is its own constant and not `tagsortmath.LAMBDA` imported.
LAMBDA = 1.0

#: The comparisons a ranking's own tagging waits for is
#: `rankingmath.enough_comparisons`; an ESTIMATE additionally needs enough
#: RATED PICTURES to fit anything at all. Below this the answer is refused
#: rather than guessed: a line through four points in 384 dimensions is a
#: line through four points.
MIN_RATED = 12


def fit(X: np.ndarray, y: np.ndarray,
        lam: float = LAMBDA) -> Optional[tuple[np.ndarray, float]]:
    """A (direction, intercept) from rated rows: ``X`` is (n, d) float32,
    centered and L2-normalized as ``tagsortmath.center`` leaves them, ``y``
    is (n,) of their scores. None when there is nothing to fit — no rows, a
    mismatch, or every picture at the same score (a constant is not a
    direction, and the intercept alone already says it).

    Dual-form ridge on the CENTERED targets, so the intercept is the rated
    mean and the direction only has to explain the spread around it.
    """
    if X.ndim != 2 or X.shape[0] == 0 or X.shape[0] != y.shape[0]:
        return None
    Xf = np.asarray(X, dtype=np.float32)
    yf = np.asarray(y, dtype=np.float32)
    b = float(yf.mean())
    resid = yf - b
    if not bool(np.any(np.abs(resid) > 1e-6)):
        # Every rated picture at the same score: the honest estimate for
        # everything else is that score, and no direction says more.
        return np.zeros(Xf.shape[1], dtype=np.float32), b
    G = Xf @ Xf.T
    G[np.diag_indices_from(G)] += float(lam)
    try:
        alpha = np.linalg.solve(G, resid)
    except np.linalg.LinAlgError:
        return None
    w = Xf.T @ alpha
    # CALIBRATED ON THE RATED PICTURES. A ridge fit is deliberately shrunk
    # towards the mean, which is right for an ORDER and wrong for a scale: on
    # a 0…9 ranking the raw fit answered 6.8 for pictures the same evidence
    # placed at 9, so a threshold of "≥ 8" fired on nothing and the feature
    # was a slider nobody could set. The gain is the least-squares slope of
    # the rated targets against the fit's own answers for them — one number,
    # no second penalty to choose — folded into the direction, so the numbers
    # come back spread the way the standings are. The shrinkage still did its
    # job: it decided the DIRECTION out of a few hundred rows, and this only
    # says how far along it a picture is.
    inb = Xf @ w
    denom = float(inb @ inb)
    if denom > 0:
        w = w * (float(resid @ inb) / denom)
    return w.astype(np.float32), b


def predict(X: np.ndarray, w: np.ndarray, b: float,
            lo: float, hi: float) -> np.ndarray:
    """The estimated scores for ``X``, CLAMPED to the ranking's own range.

    Clamped because the range is what the scale MEANS: a ridge fit answers
    11.4 for a picture more extreme than anything rated, and "11" is not a
    number this ranking has — every threshold the person can set is inside
    the range, so the clamp changes no answer and every number shown is one
    they recognise.
    """
    raw = (np.asarray(X, dtype=np.float32) @ w) + float(b)
    return np.clip(raw, float(lo), float(hi))


def in_range(low: Optional[float], high: Optional[float],
             value: float) -> bool:
    """Whether ``value`` falls in ``[low, high)`` — the low end INCLUSIVE,
    the high end EXCLUSIVE, either optional.

    HALF-OPEN because the rules are BANDS OF ONE SCALE (owner 2026-09), not
    independent ranges: a row says where its band starts and the next row's
    start is where it ends, so every score belongs to exactly one of them
    and no picture is claimed twice. Both ends were inclusive while a rule
    was "8 and up" or "between 4 and 6" — two fields somebody had to keep
    from overlapping by hand.
    """
    if low is not None and value < low:
        return False
    if high is not None and value >= high:
        return False
    return True


def bands(lows: Sequence[float]) -> list[tuple[float, Optional[float]]]:
    """The lower bounds as CONTIGUOUS BANDS, sorted: each runs from its own
    number up to the next one, and the last has no top.

    One definition, because the answer has to be the same in the preview,
    in the write and in whatever reads the numbers back. Sorted here rather
    than trusted from the caller: the dialog re-sorts as somebody types, and
    an out-of-order list would otherwise make a band that holds nothing.
    """
    xs = sorted(float(x) for x in lows)
    return [(x, xs[i + 1] if i + 1 < len(xs) else None)
            for i, x in enumerate(xs)]


def apply_rules(scores: dict[int, float],
                rules: Sequence[tuple[Optional[float], Optional[float]]],
                ) -> list[list[int]]:
    """Per rule, the item ids it claims — in the ids' sorted order, so the
    answer does not depend on dict order. With `bands`' half-open ranges
    every score lands in exactly one of them.
    """
    ids = sorted(scores)
    return [[i for i in ids if in_range(low, high, scores[i])]
            for low, high in rules]


def fuse(per_space: Iterable[dict[int, float]]) -> dict[int, float]:
    """One estimate per item from several spaces: the MEAN of the spaces that
    have one for it. Each space was fitted and predicted on its own, so each
    already answers on the ranking's scale and the mean is on it too —
    unlike the tag batch's fusion, which averages scores with no units.
    """
    total: dict[int, float] = {}
    count: dict[int, int] = {}
    for got in per_space:
        for iid, v in got.items():
            total[iid] = total.get(iid, 0.0) + float(v)
            count[iid] = count.get(iid, 0) + 1
    return {i: total[i] / count[i] for i in total}
