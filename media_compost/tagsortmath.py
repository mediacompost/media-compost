"""The tag-batch session's classifier math, pure and separately testable.

Labeled feature vectors in, a queue order out. ``fit`` is ridge regression on
±1 labels in DUAL form — ``w = Xᵀ (X Xᵀ + λI)⁻¹ y`` — which is the smallest
model that does what the session needs: it learns from a handful of answers
(the n×n solve is over the LABELED rows, a few hundred at most), it has no
learning rate, no iteration count and no way to diverge, and it is
deterministic — the same answers always order the queue the same way. With
only positives it degrades to a centroid cosine, and with no positives there
is nothing to order by and it says so.

**The rows are CENTERED on the pool before anything is fit** (``center``, on
the mean the caller measures over the scored candidates). A ViT's CLS and
CLIP's projected embeddings share a large common direction — measured on a
real crawl, the mean pairwise cosine is 0.30 for DINOv2 and 0.63 for CLIP,
and the mean vector's norm 0.55 and 0.79 — so on raw rows a centroid of two
positives points mostly at "an ordinary picture", and a ridge fit over one
positive and a stack of negatives spends its capacity on that same
direction. Taking it out is what makes the cosine to a centroid mean "more
like the positives than the average picture". Measured on a 19,625-item
crawl library, sessions from zero labels found 42.5 → 52.0 comic pages in
60 answers with centering and never fewer on any class; balancing the
labels or a tenth of the λ buys the same and costs a parameter.

``order`` is a plain descending top-k. It used to hold an EXPLORATION slot —
every fifth position drawn from the least-certain band, so the model kept
seeing its boundary — and the slot never reached the screen: the overlay
refetches after every answer and keeps only the head of each queue, so only
the top-scored item is ever shown. Simulated at scale, exploration also cost
about a tenth of the hits. It is gone rather than re-homed: a session is a
harvest, and the negatives it writes teach the boundary well enough.

``score_tags`` / ``order_by_tag`` are the multi-tag session, and they order
THE TAGS IN TURN rather than by "likely to be any of them": the queue is the
pictures the first tag's classifier claims (its score above that tag's cut),
best first, then the second tag's, and so on, with the pictures no tag claims
trailing by their best score. That is what a session over several tags is
for — answer all the A's, then all the B's — where a max over the tags
interleaved them. The scoring is MODE-AWARE, because the exclusivity switch
changes what a negative even is: with mutually exclusive tags another tag's
positive IS evidence against this one (the caller folds it in, since only
it knows the mode), while for independent (toggling) tags it is nothing of
the kind — ``blue_shirt`` and ``red_shirt`` co-exist on one picture. The
mode also decides WHOSE stretch a picture claimed by two tags joins:
exclusive, the likelier tag's (it can only be one of them); toggling, the
earlier tag's (it may well be both, and the list's order is the order asked).

numpy only, deliberately: sklearn is not a dependency of this app and must
not become one for a 20-line solve.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

#: L2 regularization for the ridge fit. On L2-normalized rows and ±1 labels,
#: 1.0 keeps a five-example fit sane without flattening a five-hundred-example
#: one — the weight it buys shrinks as real labels accumulate.
LAMBDA = 1.0


def center(X: np.ndarray, mu: np.ndarray) -> np.ndarray:
    """``X`` with the pool mean ``mu`` taken out of every row and each row
    re-normalized to unit length — the rows every fit and every score here
    expect. A row that IS the mean (a zero after centering) is left as a
    zero rather than divided by nothing; it scores 0 against everything,
    which is the honest answer for the average picture."""
    Xc = np.asarray(X, dtype=np.float32) - np.asarray(mu, dtype=np.float32)
    n = np.linalg.norm(Xc, axis=1, keepdims=True)
    return (Xc / np.where(n > 0, n, 1.0)).astype(np.float32)


def fit(X: np.ndarray, y: np.ndarray,
        lam: float = LAMBDA) -> Optional[np.ndarray]:
    """A scoring direction from labeled rows: ``X`` is (n, d) of L2-normalized
    float32 features, ``y`` is (n,) of ±1. Returns the weight vector, or the
    positive-centroid direction when every label is positive, or None when
    there is no positive at all (nothing to point at yet).

    Dual-form ridge — the (n, n) system, never the (d, d) one — because n is
    the LABELED count (a session's answers plus the tag's existing
    assignments, capped upstream) and stays tiny while d is fixed at the
    embedding width.
    """
    if X.shape[0] == 0 or X.shape[0] != y.shape[0]:
        return None
    pos = y > 0
    if not bool(pos.any()):
        return None
    if bool(pos.all()):
        # Centroid cosine: the mean of the positives, normalized. The dual
        # solve would answer a direction too, but with one class it is just
        # this with extra arithmetic.
        v = X.mean(axis=0)
        n = float(np.linalg.norm(v))
        return (v / n).astype(np.float32) if n > 0 else None
    Xf = X.astype(np.float32, copy=False)
    yf = y.astype(np.float32, copy=False)
    G = Xf @ Xf.T
    G[np.diag_indices_from(G)] += float(lam)
    alpha = np.linalg.solve(G, yf)
    return (Xf.T @ alpha).astype(np.float32)


def scores(X: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Candidate scores — a plain matmul, kept as a function so every reader
    sees the rows are expected L2-normalized (the fit was trained on such)."""
    return X @ w


def order(s: np.ndarray, count: int) -> np.ndarray:
    """Indices of the top ``count`` candidates, best first — a stable
    descending argsort, so equal scores keep the candidates' own order."""
    n = int(s.shape[0])
    if n == 0 or count <= 0:
        return np.empty(0, dtype=np.int64)
    return np.argsort(-s, kind="stable")[:min(count, n)]


def score_tags(X: np.ndarray,
               labels: dict[str, tuple[np.ndarray, np.ndarray]],
               lam: float = LAMBDA) -> dict[str, np.ndarray]:
    """One classifier per tag over its labeled ``(X_t, y_t)`` rows, scoring
    every candidate row of ``X``: tag name → (n,) scores. A tag with no usable
    fit (no positive yet, no rows) is simply absent from the answer."""
    out: dict[str, np.ndarray] = {}
    for name, (Xt, yt) in labels.items():
        w = fit(Xt, yt, lam)
        if w is not None:
            out[name] = scores(X, w)
    return out


def order_by_tag(S: np.ndarray, cuts, count: int,
                 exclusive) -> np.ndarray:
    """Indices of the ``count`` candidates to show, THE TAGS IN TURN.

    ``S`` is (tags, n) of per-tag scores in the session's tag order and
    ``cuts`` one threshold per tag: a candidate at or above a tag's cut is
    CLAIMED by it. Every candidate claimed by the first tag comes first
    (that tag's score descending), then the second tag's, and so on; a
    candidate claimed by none trails, by its best score. A candidate claimed
    by several tags joins ONE stretch: the EARLIEST claiming tag's — and,
    where that tag sits in a MUTUALLY EXCLUSIVE group, the likeliest of the
    group's claimants, since it can only be one of them. The list's order
    is the order the session asks in.

    ``exclusive`` is either a bool — True: every tag is one exclusive group,
    False: the tags are independent — or ONE KEY PER TAG: tags sharing a
    key (other than None) are an exclusive group, and a None-keyed tag
    stands alone. The session's groups travel that way.

    Deterministic: a lexsort on (stretch, -score).
    """
    S = np.asarray(S, dtype=np.float32)
    if S.ndim != 2 or S.shape[1] == 0 or count <= 0:
        return np.empty(0, dtype=np.int64)
    tags, n = S.shape
    if isinstance(exclusive, (bool, np.bool_)):
        keys = [0 if exclusive else None] * tags
    else:
        keys = list(exclusive)
        if len(keys) != tags:
            raise ValueError("one exclusivity key per tag")
    cut = np.asarray(list(cuts), dtype=np.float32).reshape(tags, 1)
    claimed = S >= cut
    any_claim = claimed.any(axis=0)
    which = claimed.argmax(axis=0)  # the FIRST True per column
    for key in {k for k in keys if k is not None}:
        member = np.array([k == key for k in keys]).reshape(tags, 1)
        masked = np.where(claimed & member, S, -np.inf)
        best = masked.argmax(axis=0)
        in_group = np.array([keys[int(w)] == key for w in which])
        which = np.where(in_group, best, which)
    stretch = np.where(any_claim, which, tags)
    within = np.where(any_claim, S[which, np.arange(n)], S.max(axis=0))
    idx = np.lexsort((-within, stretch))
    return idx[:min(count, n)].astype(np.int64)
