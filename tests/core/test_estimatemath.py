"""The estimate's math, pure: a ridge WITH an intercept, and the rules.

What these pin: the fit answers on the ranking's own SCALE (an intercept, so
"more like the 9s" becomes a number), the degenerate cases answer honestly
rather than raising, the prediction is clamped to the range that scale
means, the rules do not exclude each other, and fusing several spaces is a
mean over the spaces that had an answer.
"""

from __future__ import annotations

import numpy as np
import pytest

from media_compost import estimatemath as m


def _rows(vals: list[float], dim: int = 8) -> np.ndarray:
    """One row per value, pointing along axis 0 by that much — a space where
    the answer is a straight line, so the fit has a right answer to find."""
    X = np.zeros((len(vals), dim), dtype=np.float32)
    for i, v in enumerate(vals):
        X[i, 0] = v
        X[i, 1] = 1.0
    n = np.linalg.norm(X, axis=1, keepdims=True)
    return (X / n).astype(np.float32)


def test_the_fit_answers_on_the_rankings_own_scale():
    """A direction alone says "more like the 9s than the 0s"; a score has a
    scale, so the fit carries an intercept and the numbers come back where
    the person reads them."""
    vals = [-3, -2, -1, 0, 1, 2, 3] * 3
    X = _rows([float(v) for v in vals])
    y = np.asarray([4.5 + v for v in vals], dtype=np.float32)
    got = m.fit(X, y)
    assert got is not None
    w, b = got
    assert b == pytest.approx(4.5, abs=1e-4), "the intercept is the rated mean"
    out = m.predict(X, w, b, 0, 9)
    # Ridge shrinks, so the fit is not exact — but the ORDER is, and the
    # numbers sit on the scale rather than around zero.
    assert out.min() >= 0 and out.max() <= 9
    assert list(np.argsort(out)) == list(np.argsort(y))
    assert abs(float(out.mean()) - 4.5) < 0.2


def test_the_degenerate_cases_answer_rather_than_raise():
    # Every rated picture at the same score: that score, and no direction.
    got = m.fit(_rows([1.0, 2.0, 3.0]), np.asarray([7, 7, 7], dtype=np.float32))
    assert got is not None
    w, b = got
    assert b == pytest.approx(7.0)
    assert not w.any()
    assert list(m.predict(_rows([9.0]), w, b, 0, 9)) == [pytest.approx(7.0)]
    # Nothing to fit at all.
    assert m.fit(np.zeros((0, 8), dtype=np.float32),
                 np.zeros(0, dtype=np.float32)) is None
    assert m.fit(_rows([1.0, 2.0]), np.asarray([1.0], dtype=np.float32)) is None


def test_the_prediction_is_clamped_to_the_range_the_scale_means():
    """A ranking has no 11: every threshold a person can set is inside the
    range, so the clamp changes no answer and every number shown is one
    they recognise."""
    vals = [-3.0, 0.0, 3.0] * 6
    X = _rows(vals)
    y = np.asarray([4.5 + v * 1.5 for v in vals], dtype=np.float32)
    w, b = m.fit(X, y)
    out = m.predict(_rows([50.0, -50.0]), w, b, 0, 9)
    assert out.min() >= 0.0 and out.max() <= 9.0


def test_the_rules_are_bands_and_every_score_is_in_exactly_one():
    """A rule says where its band STARTS; the bands are the rules sorted by
    that, each running up to the next one's start. Half-open, so the seam
    belongs to the band ABOVE it and no picture is claimed twice."""
    assert m.in_range(8, None, 8.0)
    assert m.in_range(8, None, 9.5)
    assert not m.in_range(8, None, 7.9)
    assert m.in_range(None, 2, 1.9)
    assert not m.in_range(None, 2, 2.0), "the high end is EXCLUSIVE"
    assert m.in_range(4, 6, 4.0) and m.in_range(4, 6, 5.99)
    assert not m.in_range(4, 6, 6.0)
    # No ends at all takes everything — the caller decides whether that is
    # a rule worth sending.
    assert m.in_range(None, None, -3.0)

    # THE BANDS ARE SORTED, and the last has no top.
    assert m.bands([5, 0, 9]) == [(0.0, 5.0), (5.0, 9.0), (9.0, None)]
    assert m.bands([3]) == [(3.0, None)]
    assert m.bands([]) == []

    # …so every score lands in exactly one of them.
    got = m.apply_rules({1: 9.0, 2: 6.0, 3: 1.0}, m.bands([0, 5, 9]))
    assert got == [[3], [2], [1]]
    assert sum(len(x) for x in got) == 3
    assert m.apply_rules({}, m.bands([8])) == [[]]


def test_fusing_spaces_is_a_mean_over_the_spaces_that_answered():
    """Each space is fitted and predicted on its own, so each already answers
    on the ranking's scale — unlike the tag batch's fusion, which averages
    scores with no units."""
    assert m.fuse([{1: 8.0, 2: 2.0}, {1: 6.0}]) == {1: 7.0, 2: 2.0}
    assert m.fuse([]) == {}
