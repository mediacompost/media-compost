"""The step profiler's wall-clock half, from the torch-free venv.

`profiling.StepProfiler` is what answers "where do a step's seconds go" for
a run whose card reads busy half the time. The torch trace needs a device;
the split does not, and its bookkeeping is where a mistake would be silent —
a phase charged to its neighbour reads as a perfectly plausible table.
"""

from __future__ import annotations

import importlib.util
import sys
import time

import pytest

from media_compost.train.paths import TRAIN_SCRIPTS


@pytest.fixture
def profiling():
    spec = importlib.util.spec_from_file_location(
        "profiling", TRAIN_SCRIPTS / "profiling.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_off_unless_asked_for(profiling, tmp_path, monkeypatch):
    monkeypatch.delenv(profiling.ENV, raising=False)
    p = profiling.StepProfiler(tmp_path, "cpu")
    assert not p.enabled
    p.begin_step(1); p.mark("forward"); p.mark("after"); p.close()
    assert p.times == {}


def test_each_phase_is_charged_until_the_next_mark(profiling, tmp_path,
                                                   monkeypatch, capsys):
    monkeypatch.setenv(profiling.ENV, "2")
    p = profiling.StepProfiler(tmp_path, "cpu")
    assert p.enabled and p.last == profiling.FIRST_STEP + 1
    # Steps before the window are not measured at all.
    for step in range(1, profiling.FIRST_STEP):
        p.begin_step(step); p.mark("forward"); p.mark("after")
    assert p.times == {}
    for step in (profiling.FIRST_STEP, profiling.FIRST_STEP + 1):
        p.begin_step(step)             # compose begins
        time.sleep(0.02)
        p.mark("latents"); time.sleep(0.01)
        p.mark("forward"); time.sleep(0.03)
        p.mark("backward"); time.sleep(0.01)
        p.mark("bookkeeping")
        p.mark("update"); time.sleep(0.01)
        p.mark("after"); time.sleep(0.02)
    # The step after the window closes it and reports.
    p.begin_step(profiling.FIRST_STEP + 2)
    t = p.times[profiling.FIRST_STEP]
    assert set(t) == set(profiling.PHASES)
    assert t["forward"] > t["compose"] > t["latents"] > 0
    assert t["after"] >= 0.02 and t["bookkeeping"] < 0.005
    out = capsys.readouterr().out
    assert "2 step(s) measured" in out
    for phase in profiling.PHASES:
        assert f"profiler:   {phase}" in out
    # And closing again reports nothing twice.
    p.close()
    assert out.count("measured") == 1


def test_a_run_ending_inside_the_window_still_reports(profiling, tmp_path,
                                                      monkeypatch, capsys):
    monkeypatch.setenv(profiling.ENV, "5")
    p = profiling.StepProfiler(tmp_path, "cpu")
    p.begin_step(profiling.FIRST_STEP)
    p.mark("forward"); p.mark("after")
    p.close()
    assert "1 step(s) measured" in capsys.readouterr().out
