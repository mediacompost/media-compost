"""The tag-batch classifier math — the rules a session's ordering stands on.

Everything here is pure numpy in, indexes out: separability, the
positives-only fallback, determinism, the exploration cadence, stability at
tiny label counts, and the multi-tag mode split (exclusive folds other tags'
positives into negatives, toggling must NOT — blue_shirt and red_shirt
co-exist).
"""

from __future__ import annotations

import numpy as np
import pytest

from media_compost import tagsortmath as tsm


def _unit(rows) -> np.ndarray:
    X = np.asarray(rows, dtype=np.float32)
    return X / np.linalg.norm(X, axis=1, keepdims=True)


def _cluster(center, n, spread=0.05, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    c = np.asarray(center, dtype=np.float32)
    return _unit(c[None, :] + spread * rng.standard_normal((n, c.shape[0])))


A = np.array([1.0, 0.0, 0.0, 0.0])
B = np.array([0.0, 1.0, 0.0, 0.0])
C = np.array([0.0, 0.0, 1.0, 0.0])


def test_fit_separates_two_clusters():
    Xa, Xb = _cluster(A, 8, seed=1), _cluster(B, 8, seed=2)
    X = np.vstack([Xa, Xb])
    y = np.array([1.0] * 8 + [-1.0] * 8)
    w = tsm.fit(X, y)
    assert w is not None
    cand = np.vstack([_cluster(A, 5, seed=3), _cluster(B, 5, seed=4)])
    s = tsm.scores(cand, w)
    assert s[:5].min() > s[5:].max(), "an A candidate scored below a B one"


def test_fit_is_sane_at_three_positives_and_two_negatives():
    X = np.vstack([_cluster(A, 3, seed=5), _cluster(B, 2, seed=6)])
    y = np.array([1.0, 1.0, 1.0, -1.0, -1.0])
    w = tsm.fit(X, y)
    cand = np.vstack([_cluster(A, 4, seed=7), _cluster(B, 4, seed=8)])
    s = tsm.scores(cand, w)
    assert s[:4].min() > s[4:].max()
    assert np.isfinite(s).all()


def test_positives_only_falls_back_to_the_centroid():
    X = _cluster(A, 4, seed=9)
    w = tsm.fit(X, np.ones(4))
    assert w is not None
    assert abs(float(np.linalg.norm(w)) - 1.0) < 1e-5
    cand = np.vstack([_cluster(A, 3, seed=10), _cluster(B, 3, seed=11)])
    s = tsm.scores(cand, w)
    assert s[:3].min() > s[3:].max()


def test_no_positives_means_no_ordering():
    assert tsm.fit(_cluster(B, 4, seed=12), -np.ones(4)) is None
    assert tsm.fit(np.empty((0, 4), dtype=np.float32), np.empty(0)) is None


def test_fit_is_deterministic():
    X = np.vstack([_cluster(A, 6, seed=13), _cluster(B, 6, seed=14)])
    y = np.array([1.0] * 6 + [-1.0] * 6)
    w1, w2 = tsm.fit(X, y), tsm.fit(X, y)
    assert np.array_equal(w1, w2)


def test_order_is_a_plain_descending_argsort():
    s = np.array([0.1, 0.9, -0.5, 0.4])
    assert list(tsm.order(s, 4)) == [1, 3, 0, 2]
    # No exploration slot any more: the overlay only ever shows the head of
    # a refetched queue, so a slot deeper in it never reached the screen.
    s = np.linspace(0.99, 0.01, 50)
    assert list(tsm.order(s, 10)) == list(range(10))


def test_order_caps_at_the_pool():
    assert len(tsm.order(np.array([0.5, 0.1]), 10)) == 2
    assert len(tsm.order(np.empty(0), 10)) == 0


def test_center_takes_the_common_direction_out():
    # Every row shares a big common component; centered on the pool mean
    # the two clusters are on opposite sides instead of all near 1.
    common = np.array([1.0, 1.0, 1.0, 1.0]) * 3
    X = _unit(np.vstack([_cluster(A, 5, seed=50) + common,
                         _cluster(B, 5, seed=51) + common]))
    assert float((X @ X.T).mean()) > 0.9
    Xc = tsm.center(X, X.mean(axis=0))
    assert np.allclose(np.linalg.norm(Xc, axis=1), 1.0, atol=1e-5)
    assert float((Xc[:5] @ Xc[5:].T).mean()) < 0
    # A row that IS the mean stays a zero rather than becoming NaN.
    Z = tsm.center(X.mean(axis=0, keepdims=True), X.mean(axis=0))
    assert np.all(Z == 0)


def _two_tag_labels():
    return {
        "a": (np.vstack([_cluster(A, 5, seed=30), _cluster(C, 5, seed=31)]),
              np.array([1.0] * 5 + [-1.0] * 5)),
        "b": (np.vstack([_cluster(B, 5, seed=32), _cluster(C, 5, seed=33)]),
              np.array([1.0] * 5 + [-1.0] * 5)),
    }


def test_score_tags_is_one_classifier_per_tag():
    cand = np.vstack([_cluster(A, 2, seed=60), _cluster(B, 2, seed=61)])
    per = tsm.score_tags(cand, _two_tag_labels())
    assert set(per) == {"a", "b"}
    assert per["a"][:2].min() > per["a"][2:].max()
    assert per["b"][2:].min() > per["b"][:2].max()
    # A tag with nothing usable is simply absent.
    empty = {"t": (np.empty((0, 4), dtype=np.float32), np.empty(0))}
    assert tsm.score_tags(cand, empty) == {}


def test_order_by_tag_serves_the_tags_in_turn():
    # Candidates: two clear B's, two clear A's, one claimed by nobody.
    S = np.array([[-0.5, -0.6, 0.9, 0.8, -0.2],    # tag a's scores
                  [0.7, 0.9, -0.5, -0.4, -0.3]])   # tag b's scores
    idx = tsm.order_by_tag(S, [0.0, 0.0], 5, exclusive=True)
    # a's stretch first, best first; then b's; then the unclaimed one.
    assert list(idx) == [2, 3, 1, 0, 4]
    assert list(tsm.order_by_tag(S, [0.0, 0.0], 3, exclusive=True)) == [2, 3, 1]


def test_a_candidate_claimed_twice_joins_one_stretch_per_mode():
    S = np.array([[0.6, 0.2],     # candidate 0 passes both cuts, b likelier
                  [0.8, 0.1]])
    # Exclusive: it can only be one tag — the likelier, b.
    assert list(tsm.order_by_tag(S, [0.0, 0.0], 2, exclusive=True)) == [1, 0]
    # Toggling: it may be both, and the list's order is the order asked — a.
    assert list(tsm.order_by_tag(S, [0.0, 0.0], 2, exclusive=False)) == [0, 1]


def test_order_by_tag_takes_one_exclusivity_key_per_tag():
    """The session's GROUPS: tags sharing a key compete for a candidate
    claimed by both (the likelier wins), tags in different groups — or in
    none — go by the list's order."""
    S = np.array([[0.6, 0.2],     # candidate 0 passes every cut; b likelier
                  [0.8, 0.1],
                  [0.9, 0.3]])    # c likelier still, but in no group
    # a and b one exclusive group, c alone: the earliest claimant is a, so
    # a's group decides — candidate 0 is b's (0.8 over 0.6) and candidate 1
    # a's (0.2 over 0.1); never c's, which comes after a in the list. a's
    # stretch is first, so candidate 1 leads.
    assert list(tsm.order_by_tag(S, [0, 0, 0], 2, exclusive=[1, 1, None])) == [1, 0]
    # Every tag alone: both are the earliest claimant's, a, best first.
    assert list(tsm.order_by_tag(S, [0, 0, 0], 2, exclusive=[None] * 3)) == [0, 1]
    # ...and the stretch it joins says which tag asks first: with a's cut
    # out of reach, an all-alone set files candidate 0 under b and an
    # all-one-group set under c.
    assert list(tsm.order_by_tag(S, [0.95, 0, 0], 2, exclusive=[None] * 3)) == [0, 1]
    assert list(tsm.order_by_tag(S, [0.95, 0, 0], 2, exclusive=True)) == [0, 1]
    with pytest.raises(ValueError):
        tsm.order_by_tag(S, [0, 0, 0], 2, exclusive=[1, 1])


def test_order_by_tag_honours_each_tags_own_cut():
    S = np.array([[0.3, 0.9], [0.5, 0.1]])
    # With a's cut above its scores, nothing is a's; candidate 0 is b's and
    # candidate 1 trails unclaimed by its best score.
    assert list(tsm.order_by_tag(S, [0.95, 0.4], 2, exclusive=True)) == [0, 1]
    assert len(tsm.order_by_tag(np.empty((2, 0)), [0, 0], 3, True)) == 0


def test_multi_toggling_keeps_other_tags_positives_positive():
    """blue_shirt and red_shirt: an item positive for BOTH must lead, which
    the exclusive fold (other positives = my negatives) would ruin."""
    both = _unit((A + B)[None, :])[0]
    labels = {
        "blue_shirt": (np.vstack([_cluster(A, 5, seed=20),
                                  _cluster(C, 5, seed=21)]),
                       np.array([1.0] * 5 + [-1.0] * 5)),
        "red_shirt": (np.vstack([_cluster(B, 5, seed=22),
                                 _cluster(C, 5, seed=23)]),
                      np.array([1.0] * 5 + [-1.0] * 5)),
    }
    cand = np.vstack([both[None, :], _cluster(C, 3, seed=24)])
    per = tsm.score_tags(cand, labels)
    S = np.stack([per["blue_shirt"], per["red_shirt"]])
    idx = tsm.order_by_tag(S, [0.0, 0.0], 4, exclusive=False)
    assert idx[0] == 0, "the fits-both item did not lead the queue"


def test_pack_unpack_round_trip_and_refusals():
    from media_compost.ui import itemvec

    v = np.random.default_rng(1).standard_normal(itemvec.DIM)
    raw = itemvec.pack(v)
    assert len(raw) == itemvec.DIM * 2  # float16
    back = itemvec.unpack(raw, itemvec.DIM)
    assert back is not None
    assert abs(float(np.linalg.norm(back)) - 1.0) < 1e-3
    cos = float(back @ (v / np.linalg.norm(v)))
    assert cos > 0.999, "fp16 storage moved the direction"
    # Refusals: wrong length, empty, zeros.
    assert itemvec.unpack(raw[:-2], itemvec.DIM) is None
    assert itemvec.unpack(b"", itemvec.DIM) is None
    assert itemvec.unpack(itemvec.pack(np.zeros(itemvec.DIM)),
                          itemvec.DIM) is None
