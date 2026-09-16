"""One real training step per engine, in the TRAINING interpreter.

`test_engine_contract.py` reads the engines' declarations off the source,
which is what the app's torch-free venv can do. This RUNS them: `engine_smoke.
py` builds a tiny random-weight backbone, attaches the adapter (or unfreezes
the backbone), and takes one `train_step` with a backward — the procedure
for validating a new engine, which was a manual one until now, for all
SEVEN.

SKIPS where `.venv-training` is absent, which is every CI job — the torch
stack is gigabytes and no job installs it. That is not a reason to leave the
engines with no executable test at all: a developer with the training venv
runs the suite and gets one, and the failure it guards is the sort nobody
finds by reading.

Run in a CHILD process, and not only for the venv: a torch failure on MPS can
be a Metal assertion that calls `abort()`, which no `try` can catch and which
would take the whole pytest process down with it. `scripts/measure_vram.py`
runs each model in a child for exactly this reason.

The one test that deliberately provokes a failure runs on the **CPU**, where
the same mismatch is an ordinary `RuntimeError`. That is not a detail: aimed
at the default device it aborted a child twice per suite run and left two
crash reports in `~/Library/Logs/DiagnosticReports` each time — a test that
reports itself to the operating system as a bug in Python.
"""

from __future__ import annotations

import functools
import json
import subprocess
from pathlib import Path

import pytest

from media_compost.hub.venv import interpreter_for
from media_compost.train.models import REGISTRY
from media_compost.train.paths import TRAIN_SCRIPTS

REPO = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent / "engine_smoke.py"

#: MARKED `slow`, and it is the one file where the marker costs CI nothing:
#: every job here skips it for want of `.venv-training` (above), so the 79 s it
#: takes is paid only on a developer's machine — one torch interpreter spawned
#: per engine, which is the whole point of it. `pytest -m ""` runs it.
#:
#: Whole-file rather than per-case: the cost is the child process, and every
#: case pays it.
pytestmark = pytest.mark.slow

#: Every engine the registry names, so adding a model whose architecture this
#: harness cannot build FAILS here rather than quietly going unexercised.
ENGINES = sorted({m.engine for m in REGISTRY})

#: Weights that legitimately get no gradient, per engine: the module names
#: that are dead IN THE LAST BLOCK ONLY.
#:
#: QwenImage's transformer block hands its text-branch output to the NEXT
#: block, so the final one's text side is unused by construction — the text
#: stream is discarded after it. Verified by building two blocks: block 0's
#: get gradients and block 1's do not, and nothing image-side is ever
#: affected. Six tensors in a 60-layer model, and diffusers' architecture
#: rather than our attachment.
#:
#: Deliberately a LAST-BLOCK rule and not a substring one. `to_add_out`
#: missing a gradient in the middle of the stack would be a broken forward,
#: and a plain "names containing to_add_out are fine" would wave it through.
DEAD_IN_LAST_BLOCK = {"qwenimage": ("to_add_out", "txt_mlp")}


def _unexplained(engine: str, res: dict) -> list[str]:
    """The ungradiented parameters that the architecture does not account for."""
    allowed, last = DEAD_IN_LAST_BLOCK.get(engine, ()), res.get("last_block")
    out = []
    for name in res["without_grad"]:
        in_last = last is not None and name.startswith(
            f"transformer_blocks.{last}.")
        if in_last and any(a in name for a in allowed):
            continue
        out.append(name)
    return out


def _python() -> str:
    exe = interpreter_for("training", str(REPO))
    if not exe:
        pytest.skip("no .venv-training — the engines need torch and diffusers")
    return exe


@functools.lru_cache(maxsize=None)
def _run(engine: str, method: str, *extra: str) -> subprocess.CompletedProcess:
    """One harness run, CACHED for the module.

    Every spawn pays two to four seconds importing torch and diffusers, and
    the tests below ask for the same configurations repeatedly — the full-run
    dtype check, the zeroed-adapter check and the dead-weight check all want a
    run that another test has already made. Caching turns 37 spawns into 15
    and the file from ~2m30 into ~1m.

    Safe because the harness is deterministic by construction: both seeds are
    fixed and the model is built from constants, which is also what the
    LoRA-drift comparison below relies on.
    """
    return subprocess.run(
        [_python(), str(HARNESS), "--scripts", str(TRAIN_SCRIPTS),
         "--engine", engine, "--method", method, *extra],
        capture_output=True, text=True, timeout=900)


def _result(got: subprocess.CompletedProcess) -> dict:
    assert got.returncode == 0, (
        f"the engine did not survive one step (exit {got.returncode}):\n"
        f"{got.stdout[-3000:]}\n{got.stderr[-3000:]}")
    line = next((ln for ln in got.stdout.splitlines()
                 if ln.startswith("RESULT ")), None)
    assert line, f"no result line:\n{got.stdout[-2000:]}"
    return json.loads(line[len("RESULT "):])


def test_the_harness_covers_every_engine_in_the_registry():
    """Non-vacuous, and the thing that makes adding a model visible here.

    Every test below is parametrized over `ENGINES`, read from the registry —
    so a new architecture arrives with its own row and fails until the harness
    can build one. A hand-written list would simply not mention it.
    """
    assert len(ENGINES) >= 7, ENGINES
    assert {"sd", "sdxl"} <= set(ENGINES), "the UNet engines went missing"
    assert len(set(ENGINES) - {"sd", "sdxl"}) >= 5, "the DiT engines went missing"


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("method", ["lora", "full"])
def test_one_training_step_runs_and_produces_gradients(engine, method):
    """The whole point. A loss that is not finite, or a trainable parameter
    with no gradient, is a run that trains happily and learns nothing — and
    both look exactly like a working job from the outside."""
    res = _result(_run(engine, method))
    assert res["loss_finite"], res
    assert res["trainable"] > 0, res
    assert not res["non_finite_grad"], (
        f"{engine}/{method}: non-finite gradients: {res['non_finite_grad']}")

    unexplained = _unexplained(engine, res)
    assert not unexplained, (
        f"{engine}/{method}: trainable parameters got no gradient: "
        f"{unexplained[:5]}. Either the adapter is attached to modules the "
        f"forward does not reach, or the backbone is not actually training.")


@pytest.mark.parametrize("engine", sorted(DEAD_IN_LAST_BLOCK))
def test_the_dead_weights_really_are_only_the_last_blocks_text_side(engine):
    """The exemption above, held to its own reason.

    It exists because one architecture discards its text stream after the
    final block. If that ever stops being the shape of it — an earlier block
    going quiet, or the image side going quiet — the exemption must not
    absorb it, so the claim is checked rather than assumed.
    """
    res = _result(_run(engine, "full"))
    assert res["without_grad"], (
        f"{engine} no longer has dead weights — take it out of "
        f"DEAD_IN_LAST_BLOCK rather than leaving an exemption held open")
    last = res["last_block"]
    assert last and last > 0, "build more than one block, or this proves nothing"
    for name in res["without_grad"]:
        assert name.startswith(f"transformer_blocks.{last}."), (
            f"{name} is not in the last block — that is a broken forward, "
            f"not the architecture")
        assert any(a in name for a in DEAD_IN_LAST_BLOCK[engine]), (
            f"{name} is dead and is not text-side; the exemption does not "
            f"cover it")


@pytest.mark.parametrize("engine", ENGINES)
def test_a_full_finetune_holds_fp32_masters(engine):
    """The precondition for the autocast rule, asserted rather than assumed.

    `upcast_trainable()` takes every trainable weight to fp32 — for a full run
    that is the whole backbone. If this ever stops being true the test below
    is guarding nothing, and it would stop silently.
    """
    res = _result(_run(engine, "full"))
    assert res["dtype"] == "torch.bfloat16", "bf16 is what makes this mean something"
    assert res["weight_dtypes"] == ["torch.float32"], res


@pytest.mark.parametrize("engine", ENGINES)
def test_WITHOUT_the_autocast_wrap_a_full_finetune_DIES(engine):
    """The wrap is load-bearing in EVERY engine, which is worth pinning for
    all of them rather than only for the pair that had the bug.

    `sd.py` and `sdxl.py` were the two that did not wrap their backbone
    forward in `self.autocast()`, while the five DiT engines all did — and
    `load()` calls `upcast_trainable()` either way. Both are `lora_only:
    False`, so the editor offered the method and the run died at the first
    forward. Stripping the wrap from any of the seven reproduces it, which is
    what says the wrap is why the other five were fine rather than luck.

    **PINNED TO THE CPU**, and that is the whole subtlety. The mismatch is one
    bug with two deaths: on the CPU torch raises "mat1 and mat2 must have the
    same dtype", which is catchable and tidy; on MPS the same matmul trips a
    Metal assertion that calls `abort()`. Left on the default device this test
    SIGABRTed a child once per engine per run and left the crash reports to
    prove it.
    """
    got = _run(engine, "full", "--no-autocast", "--device", "cpu")
    assert got.returncode == 2, (
        f"{engine}: expected the dtype mismatch, got exit {got.returncode}."
        + ("\n\nA full finetune SURVIVED with no autocast wrap: either the "
           "fp32 upcast stopped happening (see the test above) or the "
           "mismatch is now tolerated, and the wrap is guarding nothing."
           if got.returncode == 0 else
           f"\n{got.stdout[-1500:]}\n{got.stderr[-1500:]}"))
    assert "MISMATCH" in got.stdout, got.stdout[-1500:]
    assert "dtype" in got.stdout, "the failure was not the dtype mismatch"


@pytest.mark.parametrize("engine", ["sd", "sdxl"])
def test_the_wrap_leaves_a_LoRA_run_where_it_was(engine):
    """The cost of the fix, measured rather than argued.

    Adding the wrap to these two changed a LoRA run as well — the adapter's
    fp32 masters do their matmuls in bf16 now, which is the standard
    mixed-precision recipe and what the five DiT engines have always done. It
    is a real change to the most-used path, so the size of it is pinned: bf16
    rounding, not a different answer. Measured at ~0.1% on both.

    Only the two that changed: the DiTs have always wrapped, so there is no
    before-and-after for them to have.
    """
    with_wrap = _result(_run(engine, "lora"))["loss"]
    without = _result(_run(engine, "lora", "--no-autocast"))["loss"]
    assert without != 0
    drift = abs(with_wrap - without) / abs(without)
    assert drift < 0.02, (
        f"{engine}: the wrap moved the LoRA loss by {drift:.1%} "
        f"({without} -> {with_wrap}), which is more than bf16 rounding — it "
        f"is a change in what the run computes")


@pytest.mark.parametrize("engine", sorted(set(ENGINES) - {"sd", "sdxl"}))
def test_a_flow_matching_engine_starts_from_a_zeroed_adapter(engine):
    """A sanity anchor that costs nothing and catches a real mistake.

    PEFT initialises `lora_B` to zeros, so at step 0 the adapter contributes
    exactly nothing and a LoRA run's loss must equal the frozen model's. An
    adapter seeded with noise — or attached to the wrong modules and silently
    changing the forward — breaks this while still training and still
    producing a plausible curve.
    """
    lora = _result(_run(engine, "lora"))["loss"]
    full = _result(_run(engine, "full"))["loss"]
    assert lora == pytest.approx(full, rel=2e-3), (
        f"{engine}: a freshly attached adapter moved the loss "
        f"({full} -> {lora}); `lora_B` should start at zero")


#: The engines that lay an adapter over a text encoder through the shared
#: `trainable_text_encoders` declaration. SD and SDXL train theirs too, but
#: through the pipeline's own tokenizer, which the harness does not build;
#: what is new and unproven is the T5 side, and FLUX's CLIP-L beside it.
TE_ENGINES = ("flux", "chroma")


@pytest.mark.parametrize("engine", TE_ENGINES)
def test_a_text_encoder_adapter_is_reached_by_the_backward_pass(engine):
    """`T5_LORA_TARGETS` names `q`/`k`/`v`/`o`, which is the T5 spelling and
    not CLIP's — get the list wrong and PEFT attaches to nothing, the switch
    reads as on, and the run trains the transformer alone with an ordinary
    loss curve. So: real (tiny) encoders, the adapter over them, gradient
    checkpointing on inside them (the reentrant default is exactly what
    silently drops an adapter's gradients in a checkpointed block), one
    step, and every encoder adapter parameter must have a gradient."""
    res = _result(_run(engine, "lora", "--text-encoder"))
    assert res["loss_finite"], res
    assert res["te_trainable"] > 0, res
    assert not res["te_without_grad"], (
        f"{engine}: text-encoder adapter parameters got no gradient: "
        f"{res['te_without_grad'][:5]}")
    # …and each encoder is its own optimizer group at the encoder rate.
    assert res["te_param_groups"] == len(res["te_parts"]), res
    # The backbone still trains beside it.
    assert res["trainable"] > 0 and not _unexplained(engine, res), res


def test_flux_trains_both_encoders_and_chroma_its_one():
    flux = _result(_run("flux", "lora", "--text-encoder"))
    assert flux["te_parts"] == ["text_encoder", "text_encoder_2"], flux
    chroma = _result(_run("chroma", "lora", "--text-encoder"))
    assert chroma["te_parts"] == ["text_encoder"], chroma
