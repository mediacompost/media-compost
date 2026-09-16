"""A LoRA added by hand on the Models tab is offered in Evaluate.

`available_loras` used to walk training jobs only, so a user LoRA was listed
on the Models tab and nowhere else — the request model even required a
`job_uid`. It rides in with `user_key` instead of a job now, and resolves
through `user_lora_path`, which holds it to the base model it was added for.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from media_compost.train import usermodels
from media_compost.train.evaluate import EvalManager
from media_compost.train.manager import TrainingConflict, TrainingError


def _manager(tmp_path: Path) -> EvalManager:
    fake = SimpleNamespace(dir=tmp_path, jobs=SimpleNamespace(list_jobs=lambda: []))
    return EvalManager(fake)


def test_a_hand_added_lora_is_offered_and_resolves(tmp_path: Path):
    weights = tmp_path / "mine.safetensors"
    weights.write_bytes(b"\0")
    usermodels.write_loras(tmp_path, [usermodels.UserLora(
        key="mine", label="Mine", model="sd15", path=str(weights))])
    em = _manager(tmp_path)
    offered = em.available_loras()
    assert offered == [{"job_uid": "", "user_key": "mine", "name": "Mine",
                        "model": "sd15", "step": None, "final_step": 0}]
    assert em.user_lora_path("mine", "sd15") == str(weights)
    # Held to the base model it was added for, like a job's LoRA is.
    with pytest.raises(TrainingConflict):
        em.user_lora_path("mine", "sdxl")
    with pytest.raises(TrainingError):
        em.user_lora_path("nobody", "sd15")


def test_a_hand_added_lora_whose_file_is_gone_is_refused(tmp_path: Path):
    usermodels.write_loras(tmp_path, [usermodels.UserLora(
        key="gone", label="Gone", model="sd15",
        path=str(tmp_path / "missing.safetensors"))])
    with pytest.raises(TrainingConflict):
        _manager(tmp_path).user_lora_path("gone", "sd15")


# ---- which weights fit which model -------------------------------------------
#
# An adapter is a set of deltas on a base model's layers, so it fits that
# model AND every model built on it — a custom SDXL added on the Models tab is
# SDXL's layers with different numbers in them. Matching the model KEY meant
# an adapter trained on a custom model could be used with that one entry and
# nothing else, which is the whole of what these cover.


def _custom(store: Path, key: str = "mine", base: str = "sdxl") -> None:
    """A user model based on `base`, published so `model_spec` answers."""
    usermodels.write(store, [usermodels.UserModel(
        key=f"user:{key}", label=key, base=base,
        repo=str(store / f"{key}.safetensors"), local=True)])
    usermodels.refresh(store)


def test_an_adapter_reaches_every_model_built_on_its_own(tmp_path: Path):
    weights = tmp_path / "mine.safetensors"
    weights.write_bytes(b"\0")
    _custom(tmp_path)
    usermodels.write_loras(tmp_path, [usermodels.UserLora(
        key="plain", label="Plain", model="sdxl", path=str(weights))])
    em = _manager(tmp_path)
    try:
        # Trained on plain SDXL, applied to a finetune of it…
        assert em.user_lora_path("plain", "user:mine") == str(weights)
        # …and the other way round, which is the same statement.
        usermodels.write_loras(tmp_path, [usermodels.UserLora(
            key="custom", label="Custom", model="user:mine",
            path=str(weights))])
        assert em.user_lora_path("custom", "sdxl") == str(weights)
        # A different network is still refused, which is what the rule is for.
        with pytest.raises(TrainingConflict):
            em.user_lora_path("custom", "sd15")
    finally:
        from media_compost.train.models import set_user_specs
        set_user_specs({})


def test_a_job_s_adapter_follows_the_same_rule(tmp_path: Path):
    _custom(tmp_path)
    rec = {"uid": "j1", "name": "Job", "model": "sdxl", "method": "lora",
           "status": "completed", "total_steps": 100}
    fake = SimpleNamespace(
        dir=tmp_path,
        jobs=SimpleNamespace(list_jobs=lambda: [rec], get=lambda uid: rec))
    em = EvalManager(fake)
    out = tmp_path / "j1" / "output"
    out.mkdir(parents=True)
    (out / "pytorch_lora_weights.safetensors").write_bytes(b"\0")
    try:
        assert em.lora_path("j1", "user:mine", None) == str(out)
        with pytest.raises(TrainingConflict):
            em.lora_path("j1", "sd15", None)
    finally:
        from media_compost.train.models import set_user_specs
        set_user_specs({})


# ---- full finetunes ----------------------------------------------------------
#
# A finetune is not an adapter: it IS the network, so it stands in for the
# base model's own weights rather than stacking on them. It is listed apart
# for that reason, and it was listed nowhere at all before — a full finetune
# could be trained and never looked at.


def _full_job(store: Path, uid: str = "f1", model: str = "sdxl",
              steps=(200,)) -> dict:
    """A finished full-finetune job on disk: a backbone in its output, and
    one in each checkpoint it kept."""
    rec = {"uid": uid, "name": "Finetune", "model": model, "method": "full",
           "status": "completed", "total_steps": 1000}
    for folder in [store / uid / "output"] + [
            store / uid / "checkpoints" / f"step-{s:06d}" for s in steps]:
        (folder / "unet").mkdir(parents=True)
        (folder / "unet" / "config.json").write_text("{}", encoding="utf-8")
    return rec


def test_a_full_finetune_is_listed_with_its_checkpoints(tmp_path: Path):
    rec = _full_job(tmp_path, steps=(200, 400))
    lora = {"uid": "l1", "name": "Adapter", "model": "sdxl", "method": "lora",
            "status": "completed", "total_steps": 100}
    fake = SimpleNamespace(dir=tmp_path, jobs=SimpleNamespace(
        list_jobs=lambda: [rec, lora], get=lambda uid: rec))
    em = EvalManager(fake)
    got = em.available_finetunes()
    assert [(f["job_uid"], f["step"]) for f in got] == [
        ("f1", None), ("f1", 400), ("f1", 200)]
    assert got[0]["final_step"] == 1000
    # An ADAPTER job is not a finetune, whatever it left on disk.
    assert all(f["job_uid"] == "f1" for f in got)
    # And the paths resolve, for the family rather than the one key.
    assert em.finetune_path("f1", "sdxl", None) == str(tmp_path / "f1" / "output")
    assert em.finetune_path("f1", "sdxl", 400) == \
        str(tmp_path / "f1" / "checkpoints" / "step-000400")


def test_a_finetune_stands_in_only_for_its_own_network(tmp_path: Path):
    rec = _full_job(tmp_path)
    fake = SimpleNamespace(dir=tmp_path, jobs=SimpleNamespace(
        list_jobs=lambda: [rec], get=lambda uid: rec))
    em = EvalManager(fake)
    _custom(tmp_path)
    try:
        # A finetune of SDXL for a custom SDXL: the same layers.
        assert em.finetune_path("f1", "user:mine", None)
        with pytest.raises(TrainingConflict):
            em.finetune_path("f1", "sd15", None)
    finally:
        from media_compost.train.models import set_user_specs
        set_user_specs({})


def test_a_step_with_no_weights_in_it_is_not_offered(tmp_path: Path):
    """A checkpoint folder that holds no backbone is a LoRA-shaped one (or a
    half-written one), and offering it would fail at load with nothing on
    screen having said so."""
    rec = _full_job(tmp_path)
    empty = tmp_path / "f1" / "checkpoints" / "step-000900"
    empty.mkdir(parents=True)
    (empty / "adapter_weights.safetensors").write_bytes(b"\0")
    fake = SimpleNamespace(dir=tmp_path, jobs=SimpleNamespace(
        list_jobs=lambda: [rec], get=lambda uid: rec))
    em = EvalManager(fake)
    assert [f["step"] for f in em.available_finetunes()] == [None, 200]
    with pytest.raises(TrainingConflict):
        em.finetune_path("f1", "sdxl", 900)
