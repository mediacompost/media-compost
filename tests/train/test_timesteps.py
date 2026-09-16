"""Which noise levels a run trains on.

Loaded by file path from the main backend venv — `timesteps.apply_shift`,
`resolve`, `is_family_default` and `describe` are arithmetic and strings, and
the torch draw is not covered here.

The load-bearing test is `is_family_default`: it is what makes an untouched
job keep the exact random stream it had before this setting existed. Get it
wrong and every job in the library quietly starts training on a different
sample of noise levels — which changes results without changing any setting,
and nothing anywhere would say so.
"""

from __future__ import annotations

import importlib.util

import pytest

from media_compost.train.paths import TRAIN_SCRIPTS


def _timesteps():
    p = TRAIN_SCRIPTS / "timesteps.py"
    spec = importlib.util.spec_from_file_location("timesteps_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ts = _timesteps()


# ---- not changing what existing jobs do -------------------------------------


@pytest.mark.parametrize("flow", [True, False])
def test_default_is_the_family_default(flow):
    assert ts.is_family_default("default", flow, 0.0, 1.0)
    assert ts.is_family_default("default", flow, 2.0, 0.5), (
        "the shaping settings mean nothing while the strategy is 'default', "
        "so they must not push it off the untouched path")


def test_naming_the_family_default_EXPLICITLY_is_still_the_same_draw():
    """Picking 'bell curve' at its default shape on a flow model, or 'evenly'
    on an epsilon one, is what the model already did — so it must not switch
    to the general path and change the stream for no reason."""
    assert ts.is_family_default("logit_normal", True, 0.0, 1.0)
    assert ts.is_family_default("uniform", False, 0.0, 1.0)


def test_a_REAL_change_leaves_the_untouched_path():
    assert not ts.is_family_default("logit_normal", True, 0.5, 1.0)
    assert not ts.is_family_default("logit_normal", True, 0.0, 1.5)
    assert not ts.is_family_default("uniform", True, 0.0, 1.0)
    assert not ts.is_family_default("cosmap", True, 0.0, 1.0)
    assert not ts.is_family_default("logit_normal", False, 0.0, 1.0)


def test_the_two_families_have_different_defaults():
    assert ts.resolve("default", flow=True) == "logit_normal"
    assert ts.resolve("default", flow=False) == "uniform"
    # …and naming one explicitly means the same on both.
    for flow in (True, False):
        assert ts.resolve("cosmap", flow=flow) == "cosmap"


# ---- the shift ---------------------------------------------------------------


def test_a_shift_of_one_changes_nothing():
    for t in (0.0, 0.25, 0.5, 0.99):
        assert ts.apply_shift(t, 1.0) == t


def test_a_shift_moves_every_interior_point_towards_MORE_noise():
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        assert ts.apply_shift(t, 3.0) > t


def test_the_ends_are_fixed_points():
    """0 is a clean picture and 1 is pure noise whatever the shift — a shift
    that moved them would be changing the range rather than the emphasis."""
    for shift in (1.0, 2.0, 3.0, 7.0):
        assert ts.apply_shift(0.0, shift) == pytest.approx(0.0)
        assert ts.apply_shift(1.0, shift) == pytest.approx(1.0)


def test_it_stays_inside_the_range_and_keeps_the_order():
    prev = -1.0
    for i in range(0, 101):
        got = ts.apply_shift(i / 100, 3.0)
        assert 0.0 <= got <= 1.0
        assert got > prev
        prev = got


def test_the_expression_is_the_one_the_engines_used():
    """Five engines wrote this inline, identically. Pinned so hoisting it can
    be shown to have changed nothing."""
    shift = 3.0
    for u in (0.0, 0.1, 0.42, 0.9, 1.0):
        assert ts.apply_shift(u, shift) == pytest.approx(
            (u * shift) / (1.0 + (shift - 1.0) * u))


# ---- what the log says --------------------------------------------------------


def test_the_summary_names_which_end_the_run_leans_towards():
    assert "detail" in ts.describe("logit_normal", True, -1.0, 1.0, 1.0)
    assert "composition" in ts.describe("logit_normal", True, 1.0, 1.0, 1.0)
    assert "evenly" in ts.describe("uniform", False, 0.0, 1.0, 1.0)
    assert "middle" in ts.describe("default", True, 0.0, 1.0, 1.0)


def test_the_summary_mentions_a_shift_only_when_there_is_one():
    assert "shifted" not in ts.describe("default", True, 0.0, 1.0, 1.0)
    assert "shifted 3x" in ts.describe("default", True, 0.0, 1.0, 3.0)
