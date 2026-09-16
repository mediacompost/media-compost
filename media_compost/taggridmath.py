"""The tag-grid session's math, pure and separately testable.

The tag grid shows a BATCH of pictures pre-sorted into three bands — fits,
undecided, doesn't fit — and asks to be corrected rather than answered one
picture at a time. Two things distinguish it from the one-at-a-time session
whose classifier it borrows (`tagsortmath.fit` / `scores`), and both live
here:

**WHERE THE BANDS ARE CUT is calibrated from the labels, never fixed.** A
ridge score has no natural scale — it moves with how many labels there are,
with the space (a DINOv2 cosine sits far tighter than a CLIP one on this
library's content) and, fused, with how many spaces contributed — so a
constant threshold would be right for exactly one library on one day.
`cutoffs` reads the fit's own scores on the rows it was trained on: a
candidate scoring above what most of the known positives score is a likely
fit, one below what most of the known negatives score is a likely miss, and
everything between is the honest "undecided". Below a handful of labels a
side has no percentile worth trusting and that side simply does not
pre-fill, which is what makes the first batch all undecided by itself and
a positives-only session never pre-fill "doesn't fit". No baseline was
measured for this — there is not enough labeled data to measure one — and
the rule needs none: a percentile of the training rows is right on whatever
scale the fit produced.

**WHAT GOES IN A BATCH is a MIX, not the top of the ranking.** Sixteen top
scores fill the fits band and teach the model nothing about where it is
wrong; the grid learns fastest — and the three bands mean something — when a
batch carries some confident matches, some confident misses and a good
share from where the score sits nearest the cut. `compose` cycles
top / band / bottom / band, deterministically, so half of each batch is the
boundary. Off (`boundary=False`) it is the plain top of the ranking, which is
the harvest mode for a model already trusted.

numpy only, like `tagsortmath`.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .tagsortmath import LAMBDA, fit, scores  # noqa: F401  (re-exported)

#: How many labels a side needs before its percentile is trusted enough to
#: pre-fill a band. Below this the band stays empty and the pictures sit in
#: "undecided" — which is also what makes a fresh session start there.
MIN_LABELS = 4

#: The positive cut is this percentile of the KNOWN positives' own scores:
#: a candidate above it scores like most positives do.
POS_PERCENTILE = 15.0

#: …and the negative cut this percentile of the known negatives'.
NEG_PERCENTILE = 85.0


def cutoffs(pos_scores, neg_scores,
            min_labels: int = MIN_LABELS,
            ) -> tuple[Optional[float], Optional[float]]:
    """``(hi, lo)`` — above ``hi`` a candidate pre-fills "fits", below ``lo``
    it pre-fills "doesn't fit", between the two (or where a side is None) it
    is undecided.

    Each side is a percentile of its own labeled rows' scores, or None below
    ``min_labels``. With both present, the two shapes a fit takes get two
    answers. SEPARABLE classes — the positives' bottom ABOVE the negatives'
    top — leave a gap, and the cut is the gap's MIDPOINT, the same number
    on both sides: nothing is undecided, because nothing scores where the
    classes are not confidently apart. (It used to keep the whole gap as the
    band, and on a clean split that filed a third of a batch of correctly
    ranked positives as "undecided" — the pre-fill reading as a classifier
    that would not commit.) OVERLAPPING classes put the positives' bottom
    BELOW the negatives' top, and that overlap is the undecided band, with
    ``hi`` the larger of the pair.
    """
    pos = np.asarray(list(pos_scores), dtype=np.float64)
    neg = np.asarray(list(neg_scores), dtype=np.float64)
    cp = float(np.percentile(pos, POS_PERCENTILE)) \
        if pos.shape[0] >= min_labels else None
    cn = float(np.percentile(neg, NEG_PERCENTILE)) \
        if neg.shape[0] >= min_labels else None
    if cp is None or cn is None:
        return cp, cn
    if cp > cn:
        mid = (cp + cn) / 2.0
        return mid, mid
    return cn, cp


def calibration_scores(X: np.ndarray, y: np.ndarray,
                       lam: float = LAMBDA) -> np.ndarray:
    """What the LABELED rows score under a fit that did not see them —
    LEAVE-ONE-OUT, which is what `cutoffs` has to be fed.

    A ridge fit scores its own training rows near ±1 however fresh rows
    score, so a percentile of the in-sample scores puts the positive cut
    above what a real positive reaches and the "fits" band quietly
    under-fills. For dual ridge the leave-one-out prediction is closed-form:
    with ``M = (G + λI)⁻¹`` and ``α = M y``, row i's prediction from a fit
    on every OTHER row is ``y_i − α_i / M_ii`` (the in-sample residual is
    ``λ α_i`` and the hat matrix's diagonal ``λ M_ii``) — one solve for all
    n, the same (n, n) system `fit` already solves. With only positives (the
    centroid fallback) it is the cosine with the centroid of the OTHERS.
    Rows are expected L2-normalized, like `fit`'s.
    """
    n = int(X.shape[0])
    if n == 0:
        return np.empty(0, dtype=np.float32)
    Xf = X.astype(np.float32, copy=False)
    yf = y.astype(np.float32, copy=False)
    if bool((yf > 0).all()):
        if n == 1:
            return np.ones(1, dtype=np.float32)
        total = Xf.sum(axis=0)
        out = np.empty(n, dtype=np.float32)
        for i in range(n):
            c = total - Xf[i]
            norm = float(np.linalg.norm(c))
            out[i] = float(Xf[i] @ c / norm) if norm > 0 else 0.0
        return out
    G = Xf @ Xf.T
    G[np.diag_indices_from(G)] += float(lam)
    M = np.linalg.inv(G)
    alpha = M @ yf
    return (yf - alpha / np.diag(M)).astype(np.float32)


def midpoint(hi: Optional[float], lo: Optional[float]) -> float:
    """Where "least sure" is measured from: the middle of the band, else the
    one cut there is (the boundary of the one band that pre-fills), else 0 —
    the ±1 midpoint a ridge fit on ±1 labels is centred on."""
    if hi is not None and lo is not None:
        return (hi + lo) / 2.0
    if hi is not None:
        return hi
    if lo is not None:
        return lo
    return 0.0


def bucket(s: np.ndarray, hi: Optional[float],
           lo: Optional[float]) -> np.ndarray:
    """Per score: ``1`` (fits), ``-1`` (doesn't fit) or ``0`` (undecided)."""
    out = np.zeros(s.shape[0], dtype=np.int64)
    if hi is not None:
        out[s > hi] = 1
    if lo is not None:
        out[s < lo] = -1
    return out


def compose(s: np.ndarray, count: int, hi: Optional[float],
            lo: Optional[float], boundary: bool = True) -> np.ndarray:
    """Indices of the ``count`` candidates a batch shows, best score first.

    ``boundary`` on: a MIX — the cycle top / band / bottom / band, where
    "band" is the score nearest ``midpoint(hi, lo)``, so half of every batch
    is drawn from where the model is least sure and the other half confirms
    what it is surest of on both sides. Off: the top ``count`` by score.
    Deterministic — argsorts and a merge, no RNG — so a test can state the
    mix exactly.
    """
    n = int(s.shape[0])
    if n == 0 or count <= 0:
        return np.empty(0, dtype=np.int64)
    count = min(count, n)
    top = np.argsort(-s, kind="stable")
    if not boundary:
        return top[:count]
    bottom = np.argsort(s, kind="stable")
    mid = midpoint(hi, lo)
    band = np.argsort(np.abs(s - mid), kind="stable")
    sources = [top, band, bottom, band]
    cursors = [0, 0, 0, 0]
    taken: set[int] = set()
    chosen: list[int] = []
    slot = 0
    while len(chosen) < count:
        picked = False
        # Each turn tries its own source, then the others in order — a source
        # that is exhausted (everything it ranks is taken) hands the slot on
        # rather than ending the batch short.
        for k in range(4):
            j = (slot + k) % 4
            src = sources[j]
            at = cursors[j]
            while at < n and int(src[at]) in taken:
                at += 1
            cursors[j] = at
            if at < n:
                pick = int(src[at])
                taken.add(pick)
                chosen.append(pick)
                cursors[j] = at + 1
                picked = True
                break
        if not picked:
            break
        slot += 1
    idx = np.asarray(chosen, dtype=np.int64)
    return idx[np.argsort(-s[idx], kind="stable")]


def fuse(per_space: dict[int, list[float]]) -> dict[int, float]:
    """One score per item from its per-space scores — the MEAN of what
    exists. Late fusion rather than a concatenated vector, because an item
    indexed in one space and not the other still gets a score, and because
    each space's fit is regularised on its own scale (a DINOv2 Gram matrix
    on manga pages sits near all-ones, where CLIP's does not, so one lambda
    over a concatenation would let the looser space dominate)."""
    return {iid: float(np.mean(vals)) for iid, vals in per_space.items()
            if vals}
