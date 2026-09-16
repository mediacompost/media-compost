"""A failed run says what to DO about it.

`train/scripts/failure.py` is the shared explainer. It is shared because
the two things that fail this way used to word it differently: the trainer had
an out-of-memory paragraph and the Evaluate generator wrote a bare
`f"{type(exc).__name__}: {exc}"`, so the same overflow was advice in one place
and a torch dump in the other.

Imported by PATH: `train/scripts/` (the trainer) is standalone (it runs in the dedicated
torch venv and may not import `media_compost`), which is also why the module
under test is stdlib-only and testable from the app's venv.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = (Path(__file__).resolve().parents[2]
        / "media_compost" / "train" / "scripts")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


failure = _load("failure")


@pytest.mark.parametrize("text", [
    "torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 20 GiB",
    "RuntimeError: MPS backend out of memory (MPS allocated: 88.03 GiB)",
    "RuntimeError: CUDA error: out of memory",
])
def test_every_backend_spelling_of_running_out_is_recognised(text):
    """MPS and CUDA word it differently, and matching one of them is how half
    the cases fall through to the raw dump this module exists to replace."""
    assert failure.is_oom(text)
    assert "Memory is decided by" in failure.explain(text, {})


def test_a_self_imposed_cap_is_named_FIRST():
    """A run can carry `memory_budget_gb`, so an overflow may be the run
    obeying an instruction rather than the hardware running out — and no
    amount of advice about batch size helps with that one."""
    cfg = {"hyper": {"memory_budget_gb": 12, "batch_size": 8},
           "buckets": {"resolutions": [1024]}}
    out = failure.explain("CUDA out of memory", cfg)
    tips = out.split("kept: ", 1)[1]
    assert tips.startswith("this job caps itself at 12 GB"), tips[:80]


def test_the_advice_uses_the_jobs_own_numbers():
    cfg = {"hyper": {"batch_size": 4, "grad_accum": 2},
           "buckets": {"resolutions": [1024]}}
    out = failure.explain("CUDA out of memory", cfg)
    assert "it was 4" in out and "4x2" in out and "1x8" in out


def test_a_generation_is_not_told_to_change_the_batch_size():
    """The Evaluate tab has no batch size and no gradient checkpointing, so
    naming them would be advice its UI cannot act on."""
    out = failure.explain("CUDA out of memory",
                          {"hyper": {"batch_size": 4}}, training=False)
    assert "gradient checkpointing" not in out
    assert "batch size (it was" not in out


def test_a_poisoned_context_is_not_blamed_on_the_job():
    out = failure.explain("RuntimeError: CUDA error: an illegal memory access "
                          "was encountered", {})
    assert "driver" in out
    # The advice must name the module form: a wheel install has no checkout,
    # so a `scripts/` path is a command such a user cannot run.
    assert "-m media_compost.hub.setup_env torch" in out


def test_an_unrecognised_failure_is_passed_through_untouched():
    """Guessing at a cause we do not recognise would bury the real message."""
    assert failure.explain("ValueError: bad config", {}) == "ValueError: bad config"
