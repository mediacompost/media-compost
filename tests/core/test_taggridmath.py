"""The tag-grid math — the calibrated cuts, the bands, the batch mix, and the
fusion of two spaces' scores.

Pure numpy in, numbers out. What these pin: the cuts are percentiles of the
LABELED rows' own scores and never a constant; a side below `MIN_LABELS`
does not pre-fill; overlapping classes still yield an ordered pair whose
band is the overlap; the batch mix really is half boundary; and fusion is
the mean of what exists rather than a claim about spaces an item is not in.
"""

from __future__ import annotations

import numpy as np

from media_compost import taggridmath as tgm


def test_separable_classes_cut_at_the_gaps_midpoint():
    pos = [0.9, 0.8, 0.85, 0.7, 0.95, 0.6]
    neg = [-0.9, -0.5, -0.7, -0.8, -0.6, -0.4]
    hi, lo = tgm.cutoffs(pos, neg)
    cp = float(np.percentile(pos, tgm.POS_PERCENTILE))
    cn = float(np.percentile(neg, tgm.NEG_PERCENTILE))
    assert cp > cn
    # One cut, both sides: nothing between the classes is "undecided".
    assert hi == lo == (cp + cn) / 2.0
    assert tgm.bucket(np.array([cp, cn, (cp + cn) / 2 + 1e-3]), hi, lo).tolist() == [1, -1, 1]


def test_a_side_below_the_minimum_does_not_prefill():
    hi, lo = tgm.cutoffs([0.9, 0.8, 0.7, 0.6], [-0.5])
    assert hi is not None and lo is None
    hi, lo = tgm.cutoffs([0.9], [-0.5, -0.6, -0.7, -0.8])
    assert hi is None and lo is not None
    assert tgm.cutoffs([], []) == (None, None)


def test_overlapping_classes_still_give_an_ordered_pair():
    # The positives' 15th percentile sits BELOW the negatives' 85th: the
    # overlap is the undecided band, and hi is still the larger.
    pos = [0.1, 0.2, 0.3, 0.4, 0.5]
    neg = [0.0, 0.1, 0.2, 0.3, 0.45]
    hi, lo = tgm.cutoffs(pos, neg)
    assert hi is not None and lo is not None
    assert hi >= lo
    assert hi == float(np.percentile(neg, tgm.NEG_PERCENTILE))
    assert lo == float(np.percentile(pos, tgm.POS_PERCENTILE))


def test_bucket_uses_only_the_cuts_it_has():
    s = np.array([0.9, 0.5, 0.0, -0.5, -0.9])
    assert tgm.bucket(s, 0.6, -0.6).tolist() == [1, 0, 0, 0, -1]
    assert tgm.bucket(s, 0.6, None).tolist() == [1, 0, 0, 0, 0]
    assert tgm.bucket(s, None, -0.6).tolist() == [0, 0, 0, 0, -1]
    assert tgm.bucket(s, None, None).tolist() == [0, 0, 0, 0, 0]


def test_midpoint_is_the_band_centre_else_the_one_cut_else_zero():
    assert abs(tgm.midpoint(0.6, -0.2) - 0.2) < 1e-12
    assert tgm.midpoint(0.6, None) == 0.6
    assert tgm.midpoint(None, -0.2) == -0.2
    assert tgm.midpoint(None, None) == 0.0


def test_compose_without_boundary_is_the_top_of_the_ranking():
    s = np.array([0.1, 0.9, 0.5, -0.3, 0.7])
    idx = tgm.compose(s, 3, 0.6, -0.1, boundary=False)
    assert idx.tolist() == [1, 4, 2]


def test_compose_with_boundary_is_half_band():
    # Scores spaced so the sources cannot coincide: a clear top, a clear
    # bottom, and a cluster sitting exactly on the band's midpoint.
    s = np.array([0.95, 0.9, 0.85,          # top
                  0.02, -0.01, 0.01, -0.02,  # the band, mid = 0
                  -0.85, -0.9, -0.95])       # bottom
    idx = tgm.compose(s, 8, 0.5, -0.5, boundary=True)
    picked = set(idx.tolist())
    band = {3, 4, 5, 6}
    # Eight slots cycle top/band/bottom/band: four from the band, two from
    # each end.
    assert picked & band == band
    assert len(picked & {0, 1, 2}) == 2
    assert len(picked & {7, 8, 9}) == 2
    # …and the answer is score-descending, whatever order it was drawn in.
    assert s[idx].tolist() == sorted(s[idx].tolist(), reverse=True)


def test_compose_exhausts_a_source_without_coming_up_short():
    s = np.array([0.3, 0.2, 0.1])
    idx = tgm.compose(s, 3, None, None, boundary=True)
    assert sorted(idx.tolist()) == [0, 1, 2]
    assert tgm.compose(s, 0, None, None).shape == (0,)
    assert tgm.compose(np.empty(0), 4, None, None).shape == (0,)


def test_compose_is_deterministic():
    rng = np.random.default_rng(3)
    s = rng.standard_normal(200)
    a = tgm.compose(s, 16, 0.4, -0.4)
    b = tgm.compose(s, 16, 0.4, -0.4)
    assert a.tolist() == b.tolist()


def test_fuse_is_the_mean_of_what_exists():
    fused = tgm.fuse({1: [0.8, 0.4], 2: [0.5], 3: []})
    assert abs(fused[1] - 0.6) < 1e-9
    assert fused[2] == 0.5
    assert 3 not in fused


def _cluster(center, n, spread=0.08, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    c = np.asarray(center, dtype=np.float32)
    X = c[None, :] + spread * rng.standard_normal((n, c.shape[0]))
    return (X / np.linalg.norm(X, axis=1, keepdims=True)).astype(np.float32)


def test_calibration_scores_are_leave_one_out():
    """The closed form agrees with an explicit refit without the row, and
    sits BELOW the in-sample score for a positive — which is the whole
    reason the cuts read it rather than the fit's own answers."""
    X = np.vstack([_cluster([1, 0, 0, 0], 6, seed=1),
                   _cluster([0, 1, 0, 0], 6, seed=2)])
    y = np.array([1.0] * 6 + [-1.0] * 6, dtype=np.float32)
    loo = tgm.calibration_scores(X, y)
    for i in range(X.shape[0]):
        keep = np.ones(X.shape[0], dtype=bool)
        keep[i] = False
        w = tgm.fit(X[keep], y[keep])
        assert abs(float(X[i] @ w) - float(loo[i])) < 1e-4, i
    w_all = tgm.fit(X, y)
    in_sample = tgm.scores(X, w_all)
    assert (loo[:6] < in_sample[:6] + 1e-6).all()


def test_calibration_scores_with_positives_only_is_the_others_centroid():
    X = _cluster([1, 0, 0, 0], 5, seed=3)
    y = np.ones(5, dtype=np.float32)
    loo = tgm.calibration_scores(X, y)
    for i in range(5):
        others = np.delete(X, i, axis=0).mean(axis=0)
        expect = float(X[i] @ others / np.linalg.norm(others))
        assert abs(expect - float(loo[i])) < 1e-5
    assert tgm.calibration_scores(X[:1], y[:1]).tolist() == [1.0]
    assert tgm.calibration_scores(np.empty((0, 4)), np.empty(0)).shape == (0,)
