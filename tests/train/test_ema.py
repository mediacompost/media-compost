"""The weight average's decay curve.

Loaded by file path from the main backend venv, like `compose.py` and
`latentio.py` — `ema.effective_decay` is arithmetic and needs no torch. The
tensor half does, and is not covered here.

This is the half worth pinning. The failure it guards is silent in every way a
failure can be: a run with a decay that never ramps in saves an average still
holding its own random starting point, the loss graph is unaffected (training
never reads the average), and the only symptom is a result that is worse than
not averaging at all.
"""

from __future__ import annotations

import importlib.util

import pytest

from media_compost.train.paths import TRAIN_SCRIPTS


def _ema():
    p = TRAIN_SCRIPTS / "ema.py"
    spec = importlib.util.spec_from_file_location("ema_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ema = _ema()


def test_the_average_starts_SHORT_and_lengthens():
    """At step 1 almost all of the average is the current weights, so the
    random initialisation is gone within a few steps rather than lingering
    for as long as the decay would otherwise imply."""
    assert ema.effective_decay(0.999, 1) == pytest.approx(2 / 11)
    assert ema.effective_decay(0.999, 10) == pytest.approx(11 / 20)
    assert ema.effective_decay(0.999, 100) == pytest.approx(101 / 110)


def test_it_settles_at_the_decay_that_was_asked_for():
    assert ema.effective_decay(0.999, 100_000) == pytest.approx(0.999)
    assert ema.effective_decay(0.99, 100_000) == pytest.approx(0.99)


def test_the_ramp_never_exceeds_the_requested_decay():
    """A low decay must stay low from the first step: the ramp is a CAP on how
    long the average may be, never a floor that overrides the setting."""
    for step in range(0, 5000):
        assert ema.effective_decay(0.9, step) <= 0.9


def test_the_curve_only_rises():
    prev = -1.0
    for step in range(0, 3000):
        cur = ema.effective_decay(0.999, step)
        assert cur >= prev
        prev = cur


def test_step_zero_is_not_negative_or_greater_than_one():
    assert 0.0 <= ema.effective_decay(0.999, 0) <= 1.0
    assert 0.0 <= ema.effective_decay(0.999, -5) <= 1.0


def test_a_SHORT_RUN_still_ends_up_averaging_the_run_and_not_its_noise():
    """The property that makes the ramp worth having, stated end to end: run
    the actual recurrence over a scalar going 0 → 1 and check the average has
    followed it. Without the ramp, an 800-step run at 0.999 keeps 45% of its
    starting value; with it, under 1%."""
    def simulate(ramped: bool, steps: int = 800, decay: float = 0.999):
        avg, start = 0.0, 0.0
        for step in range(1, steps + 1):
            d = ema.effective_decay(decay, step) if ramped else decay
            current = step / steps           # weights improving steadily
            avg = avg * d + current * (1.0 - d)
        # How much of the untrained starting point is still in there.
        return abs(avg - start)

    assert simulate(ramped=True) > 0.5       # tracking the trained weights
    assert simulate(ramped=False) < 0.5      # still mostly its own zero
