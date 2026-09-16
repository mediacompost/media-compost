"""The Evaluate generator's warm-adoption rules, tested for real.

The eval-manager tests substitute `tests/fake_trainer/generate.py`, so the
REAL `_same_model` / `_next_queued` were never executed by any test — and a
bug there strands queued generations silently (a warm process either adopts
a run it must not, or exits when it could have served the queue). The
helpers are pure and generate.py's module top is stdlib-only, so it imports
by file path exactly the way compose.py already does.
"""
from __future__ import annotations

import importlib.util
import json

import pytest

from media_compost.train.paths import TRAIN_SCRIPTS


def _generate():
    p = TRAIN_SCRIPTS / "generate.py"
    spec = importlib.util.spec_from_file_location("generate_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _generate()


def _spec(repo="repo/a", engine="sd", loras=()):
    return {"model_info": {"repo": repo, "engine": engine},
            "loras": [{"path": p, "weight": w} for (p, w) in loras]}


def test_same_model_matches_repo_engine_and_lora_stack():
    a = _spec(loras=[("/j1/output", 1.0)])
    assert gen._same_model(a, _spec(loras=[("/j1/output", 1.0)]))
    assert not gen._same_model(a, _spec(repo="repo/b", loras=[("/j1/output", 1.0)]))
    assert not gen._same_model(a, _spec(engine="sdxl", loras=[("/j1/output", 1.0)]))
    # A different weight, a different checkpoint path, or an extra LoRA are
    # all a different pipeline.
    assert not gen._same_model(a, _spec(loras=[("/j1/output", 0.5)]))
    assert not gen._same_model(a, _spec(loras=[("/j1/checkpoints/step-000100", 1.0)]))
    assert not gen._same_model(a, _spec(loras=[("/j1/output", 1.0), ("/j2/output", 1.0)]))
    # Order matters the way the layering does.
    two = _spec(loras=[("/j1/output", 1.0), ("/j2/output", 1.0)])
    swapped = _spec(loras=[("/j2/output", 1.0), ("/j1/output", 1.0)])
    assert not gen._same_model(two, swapped)
    # No LoRAs at all is a valid, matchable stack.
    assert gen._same_model(_spec(), _spec())


def _run(root: Path, name: str, phase: str, created: float, spec_extra=None):
    d = root / name
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({"phase": phase}))
    (d / "spec.json").write_text(json.dumps(
        {"created_at": created, **(spec_extra or {})}))
    return d


def test_next_queued_picks_the_oldest_waiting_run(tmp_path: Path):
    root = tmp_path / "_eval"
    assert gen._next_queued(root) is None, "no dir yet"
    root.mkdir()
    assert gen._next_queued(root) is None, "nothing waiting"

    _run(root, "newer", "queued", 200.0)
    old = _run(root, "older", "queued", 100.0)
    _run(root, "done", "completed", 50.0)     # not waiting
    _run(root, "live", "generating", 10.0)    # not waiting either
    broken = root / "broken"                  # queued but no spec -> skipped
    broken.mkdir()
    (broken / "state.json").write_text(json.dumps({"phase": "queued"}))

    d, spec = gen._next_queued(root)
    assert d == old and spec["created_at"] == 100.0


def test_the_portable_lora_is_loaded_BY_NAME_and_never_as_a_bare_folder(
        tmp_path: Path):
    """A LoRA a training job produced is a local FOLDER, and diffusers hands
    a folder with no `weight_name` to `_best_guess_weight_name` — which is a
    hub operation and refuses outright while the hub is offline ("you must
    specify a `weight_name`"), which is what every run here is spawned into.
    So the whole feature failed on exactly the machines that need offline
    mode, and passed on the ones that do not. The name is what skips the
    guess; the folder also holds two other `.safetensors` that are not in
    this layout, so it is the more precise call either way.
    """
    import sys

    from media_compost.train.paths import TRAIN_SCRIPTS

    sys.path.insert(0, str(TRAIN_SCRIPTS))
    try:
        import adapters
    finally:
        sys.path.remove(str(TRAIN_SCRIPTS))

    ckpt = tmp_path / "output"
    ckpt.mkdir()
    for name in (adapters.PORTABLE_FILE, adapters.STATE_FILE,
                 "lycoris_weights.safetensors"):
        (ckpt / name).write_bytes(b"")
    (ckpt / adapters.STATE_META).write_text(json.dumps({"network": "lora"}))

    seen: dict = {}

    class Pipe:
        def load_lora_weights(self, where, **kw):
            seen["where"] = where
            seen["kw"] = kw

    gen._load_lora(Pipe(), ckpt, "a")
    assert seen["kw"].get("weight_name") == adapters.PORTABLE_FILE
    assert seen["kw"].get("adapter_name") == "a"
    assert seen["where"] == str(ckpt)


def test_a_part_the_loader_already_covered_is_not_attached_twice(
        tmp_path: Path):
    """`portable_parts` is a claim ABOUT a file, written by the build that
    saved it — and SDXL's said its second text encoder was not in the
    portable file while `save_portable` was putting it there. So diffusers
    attached the adapter out of the file and `_attach_parts` came back for
    it, which PEFT refuses: "Adapter with name l0 already exists". That was
    the first thing every SDXL text-encoder LoRA did on load.

    The engine declares it correctly now, but a metadata file cannot be
    re-read into the past: every checkpoint already on disk still holds the
    old claim. So the MODULE is asked — it knows what is attached to it —
    and re-attaching over an existing adapter is never right however the
    question arose.
    """
    import sys

    from media_compost.train.paths import TRAIN_SCRIPTS

    sys.path.insert(0, str(TRAIN_SCRIPTS))
    try:
        import adapters
    finally:
        sys.path.remove(str(TRAIN_SCRIPTS))

    ckpt = tmp_path / "output"
    ckpt.mkdir()
    # The metadata an older SDXL run wrote: the second encoder is claimed to
    # be outside the portable file, and it is not.
    meta = {"network": "lora", "rank": 4, "alpha": 4,
            "parts": ["text_encoder", "text_encoder_2", "unet"],
            "portable_parts": ["text_encoder", "unet"]}
    (ckpt / adapters.STATE_META).write_text(json.dumps(meta))

    class Module:
        def __init__(self, attached=()):
            self.peft_config = {a: object() for a in attached}
            self.added: list[str] = []

        def add_adapter(self, config, name):
            if name in self.peft_config:
                raise ValueError(f"Adapter with name {name} already exists")
            self.peft_config[name] = config
            self.added.append(name)

    class Pipe:
        def __init__(self):
            # What `load_lora_weights` left behind: every part the portable
            # file really carried.
            self.unet = Module(["l0"])
            self.text_encoder = Module(["l0"])
            self.text_encoder_2 = Module(["l0"])

    # `_attach_parts` resolves `adapters` off sys.path, which this test has
    # already imported — so it is the same module object and patching its
    # reader is enough. (Real weights would want torch; what is under test
    # is which parts get asked for, not what is in them.)
    import unittest.mock as mock

    state = {"unet": {}, "text_encoder": {}, "text_encoder_2": {}}
    with mock.patch.object(adapters, "load_state", lambda _p: state):
        pipe = Pipe()
        assert gen._attach_parts(pipe, ckpt, "l0", meta) == []
        assert pipe.text_encoder_2.added == []

        # And a part that really IS only in the trainer's own file must
        # still be attached — the guard must not swallow the case the
        # function exists for. (It needs PEFT, which the app's venv has
        # not got; that the import is reached at all is the assertion.)
        pipe2 = Pipe()
        pipe2.text_encoder_2 = Module()   # nothing attached to it
        with pytest.raises(ModuleNotFoundError, match="peft"):
            gen._attach_parts(pipe2, ckpt, "l0", meta)


# ---- full finetunes ----------------------------------------------------------


def test_a_warm_pipeline_is_not_reused_across_finetunes():
    """The warm process holds the LAST run's weights. A finetune replaces the
    backbone of the pipeline built from a repo, so two runs naming that repo
    and different finetunes are two different models — and adopting the
    second into the first's process would generate from the wrong weights
    with nothing saying so."""
    a = _spec()
    a["model_info"]["finetune"] = "/jobs/f1/output"
    b = _spec()
    b["model_info"]["finetune"] = "/jobs/f2/output"
    assert not gen._same_model(a, b)
    assert not gen._same_model(a, _spec())          # …and against none at all
    assert gen._same_model(a, {"model_info": dict(a["model_info"]), "loras": []})


def test_a_finetune_folder_says_which_component_it_holds(tmp_path):
    """`save_full` writes ONE subfolder named after the component, which is
    also that component's name on the pipeline — so the folder says both what
    it holds and where it goes, and the generator needs no engine to read it."""
    out = tmp_path / "output"
    (out / "unet").mkdir(parents=True)
    (out / "unet" / "config.json").write_text(
        '{"_class_name": "UNet2DConditionModel"}', encoding="utf-8")
    sub, name = gen._backbone_of(out)
    assert (sub.name, name) == ("unet", "UNet2DConditionModel")


def test_a_folder_that_is_not_one_backbone_is_refused(tmp_path):
    """Loudly, both ways: a run that quietly generated from the base model
    after being asked for a finetune looks exactly like a finetune that
    learned nothing."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="no finetuned weights"):
        gen._backbone_of(empty)
    with pytest.raises(RuntimeError, match="no finetuned weights"):
        gen._backbone_of(tmp_path / "gone")
    two = tmp_path / "two"
    for name in ("unet", "text_encoder"):
        (two / name).mkdir(parents=True)
        (two / name / "config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not one backbone"):
        gen._backbone_of(two)
