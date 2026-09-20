"""What a COMPLETED training run leaves behind.

A cadence is arithmetic — 250 steps every 100 checkpoints at 100 and 200 —
so the last step, the one state anybody actually wants, had no checkpoint
and no sample round of its own unless the numbers happened to divide. Both
are written at the end now, and `loop._finish_run` is the whole of it: the
result first, then the two things the cadences may have missed.

Driven with a stand-in engine and a real `JobIO`. `torch` is stubbed — the
resume point's `torch.save` is the only thing here that wants it, the
weights themselves are the engine's business, and the main venv is
torch-free by contract.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from tests.train.conftest import loop_module as _loop_module
from tests.train.conftest import train_module as _train_module


class _Engine:
    """Writes a file per directory it is asked to save into, so a test can
    see WHICH copies a finish made."""

    def __init__(self):
        self.saved: list[Path] = []
        self.rounds: list[int] = []
        self.saved_when_sampling: list[Path] = []
        self.raise_on_sample: BaseException | None = None

    def save_weights(self, d) -> None:
        d = Path(d)
        d.mkdir(parents=True, exist_ok=True)
        (d / "model.safetensors").write_bytes(b"weights")
        self.saved.append(d)

    def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                         on_image=None, check=None):
        # What was already on disk when the round started — the ordering is
        # the point of the last test here.
        self.saved_when_sampling = list(self.saved)
        if self.raise_on_sample is not None:
            raise self.raise_on_sample
        self.rounds.append(len(prompts))
        return [None] * len(prompts)


class _Optimizer:
    def state_dict(self) -> dict:
        return {}


@pytest.fixture
def io(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        save=lambda blob, path: Path(path).write_bytes(b"state"),
        get_rng_state=lambda: b""))
    return _train_module().JobIO(tmp_path)


SAMPLING = {"prompts": [{"prompt": "a cat", "negative": ""}], "seed": 1}


def _finish(io, engine, **over):
    loop = _loop_module()
    args = dict(final=250, ckpt_every=100, ckpt_keep=2, ckpt_keep_every=0,
                snap_at=200, sample_every=0, sampling={}, sampled_at=-1)
    args.update(over)
    loop._finish_run(io, engine, _Optimizer(), None, **args)


def _snapshots(io) -> list[str]:
    return sorted(p.name for p in (io.dir / "checkpoints").iterdir()
                  if p.is_dir() and p.name.startswith("step-"))


def test_the_last_step_gets_a_checkpoint_the_cadence_never_reached(io):
    engine = _Engine()
    _finish(io, engine)
    assert _snapshots(io) == ["step-000250"]
    # And the run's own result, and the resume point, as ever.
    assert (io.dir / "output" / "model.safetensors").is_file()
    assert json.loads((io.dir / "checkpoints" / "last" / "step.json")
                      .read_text(encoding="utf-8"))["step"] == 250


def test_a_cadence_that_landed_on_the_last_step_is_not_repeated(io):
    engine = _Engine()
    _finish(io, engine, snap_at=250)
    assert _snapshots(io) == []
    assert (io.dir / "output" / "model.safetensors").is_file()


def test_checkpointing_switched_off_leaves_the_result_as_the_only_copy(io):
    """`output/` is that copy byte for byte; a snapshot beside it would be a
    second copy of a full finetune for somebody who asked for none."""
    engine = _Engine()
    _finish(io, engine, ckpt_every=0)
    assert _snapshots(io) == []


def test_the_last_step_gets_its_sample_round(io):
    engine = _Engine()
    _finish(io, engine, sample_every=100, sampling=SAMPLING)
    assert engine.rounds == [1]
    assert (io.dir / "samples" / "step-000250" / "meta.json").is_file()


def test_a_round_the_cadence_already_rendered_is_not_rendered_again(io):
    engine = _Engine()
    _finish(io, engine, sample_every=50, sampling=SAMPLING, sampled_at=250)
    assert engine.rounds == []


def test_sampling_switched_off_renders_nothing(io):
    engine = _Engine()
    _finish(io, engine, sample_every=0, sampling=SAMPLING)
    _finish(io, engine, sample_every=100, sampling={"prompts": []})
    assert engine.rounds == []


def test_the_result_is_on_disk_before_the_closing_round_runs(io):
    """A stop arriving mid-round must not cost the run its hours: the output
    and the final checkpoint are written first, and the interrupted round is
    the end of it — the job is finished, not paused."""
    loop = _loop_module()
    engine = _Engine()
    for stop in (loop.PauseRequested(), loop.Cancelled()):
        engine.raise_on_sample = stop
        _finish(io, engine, sample_every=100, sampling=SAMPLING)
        assert (io.dir / "output" / "model.safetensors").is_file()
        assert _snapshots(io) == ["step-000250"]
        # Written BEFORE the round, not merely surviving it.
        assert io.dir / "output" in engine.saved_when_sampling
