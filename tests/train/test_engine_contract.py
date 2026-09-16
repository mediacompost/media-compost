"""What every training engine has to DECLARE, read off the source.

The engines are the one part of this tree with no execution coverage at all —
they import torch and diffusers, which live in `.venv-training` and are in no
CI job, so `train/scripts/engines/*` measures 0%. The answer to that is a
tiny random-weight pipeline built from the real repo's configs — which is
`test_engine_smoke.py`, still the right smoke test, and still needing a
machine with the training venv.

What can be checked from here — from the app's torch-free venv, parsing rather
than importing, exactly as `test_training.py`'s registry checks already do —
is the DECLARATIONS. That matters more than it sounds, because every one of
these is a class attribute with a `BaseEngine` default that is wrong for a
DiT, and inheriting the default is silent in the worst way: the run trains,
the loss curve looks ordinary, and the result is a model that learned the
wrong thing or a file nothing else can load.

Each rule below is one that has already cost something to learn.
"""

from __future__ import annotations

import ast

import pytest

from media_compost.train.models import REGISTRY
from media_compost.train.paths import TRAIN_SCRIPTS

ENGINES_DIR = TRAIN_SCRIPTS / "engines"

#: Every engine module a registry entry names, deduplicated.
ENGINES = sorted({m.engine for m in REGISTRY})


def _engine_class(name: str) -> ast.ClassDef:
    tree = ast.parse((ENGINES_DIR / f"{name}.py").read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "Engine")


def _declared(name: str) -> dict[str, ast.expr]:
    """The engine class's own class-level assignments, by name."""
    out: dict[str, ast.expr] = {}
    for node in _engine_class(name).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            if node.value is not None:
                out[node.target.id] = node.value
    return out


def _base_defaults() -> dict[str, object]:
    """`BaseEngine`'s class-level defaults, for the same attributes."""
    tree = ast.parse((ENGINES_DIR / "common.py").read_text(encoding="utf-8"))
    base = next(n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "BaseEngine")
    out: dict[str, object] = {}
    for node in base.body:
        target = None
        if isinstance(node, ast.Assign) and isinstance(node.targets[0],
                                                      ast.Name):
            target = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            target = node.target.id
        if target and isinstance(getattr(node, "value", None), ast.Constant):
            out[target] = node.value.value
    return out


def _is_dit(name: str) -> bool:
    """Whether the engine trains a TRANSFORMER rather than a UNet.

    Derived from what its own `load()` takes off the pipeline — the same
    derivation `test_training.py` uses for `backbone_component`, and for the
    same reason: a hardcoded list of which engines are DiT is the second table
    those checks exist to prevent.
    """
    return "transformer" in {
        n.value.attr for n in ast.walk(_engine_class(name))
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Attribute)
        and isinstance(n.value.value, ast.Name) and n.value.value.id == "pipe"
        and n.value.attr in ("unet", "transformer")}


def test_the_engine_modules_are_all_there_to_parse():
    """Non-vacuous: every check below is a loop over `ENGINES`, so an empty
    or mis-resolved list would pass the lot."""
    assert len(ENGINES) >= 5, ENGINES
    for name in ENGINES:
        assert (ENGINES_DIR / f"{name}.py").is_file(), name
    assert any(_is_dit(n) for n in ENGINES), "no DiT engine found"
    assert any(not _is_dit(n) for n in ENGINES), "no UNet engine found"


@pytest.mark.parametrize("name", ENGINES)
def test_a_flow_matching_engine_says_so(name):
    """`flow_matching` is DECLARED rather than sniffed, because "the model's
    own noise schedule" means different things to the two families and
    nothing else distinguishes them structurally.

    Left at the default a DiT trains against the epsilon path: it gets the
    wrong timesteps and regresses on the wrong target, and the loss curve is
    entirely ordinary while it does.
    """
    declared = _declared(name)
    if not _is_dit(name):
        return
    assert "flow_matching" in declared, (
        f"{name}.py trains a transformer but does not declare "
        f"`flow_matching`, so it inherits BaseEngine's False and takes the "
        f"epsilon path")
    assert declared["flow_matching"].value is True, f"{name}.py"


@pytest.mark.parametrize("name", ENGINES)
def test_a_patchifying_engine_declares_the_step_its_pictures_round_to(name):
    """`latent_scale` is 8 wherever the VAE is the only downsampler; a DiT
    patchifies 2x2 on top, so a reference rounded to 8 comes out 88x48 and
    fails several frames down inside a reshape with nothing but a shape in
    the message. `image_step` (or a widened `latent_scale`) is what says so —
    and a real run is what found this, not inspection.
    """
    if not _is_dit(name):
        return
    declared = _declared(name)
    base = _base_defaults()
    step = declared.get("image_step") or declared.get("latent_scale")
    assert step is not None, (
        f"{name}.py patchifies but declares neither `image_step` nor a wider "
        f"`latent_scale`, so it rounds references to BaseEngine's "
        f"{base.get('latent_scale')}")
    assert isinstance(step, ast.Constant) and step.value % 16 == 0, (
        f"{name}.py rounds to {getattr(step, 'value', step)}, which a 2x2 "
        f"patchify cannot divide evenly")


@pytest.mark.parametrize("name", ENGINES)
def test_every_engine_names_the_layers_its_adapter_attaches_to(name):
    """`attach_adapter` is the ONE attachment path and each engine says only
    which module names its architecture exposes. An engine inheriting the
    UNet targets onto a transformer matches NOTHING — and `layer_filter`
    raises only when a FILTER matches nothing, so an empty base match is an
    adapter over no layers that trains happily."""
    declared = _declared(name)
    if _is_dit(name):
        assert "adapter_targets" in declared, (
            f"{name}.py trains a transformer and inherits BaseEngine's UNet "
            f"targets, which its modules are not named after")


@pytest.mark.parametrize("name", ENGINES)
def test_the_pipeline_family_is_declared_consistently(name):
    """`PIPELINES` is the family an engine accepts and `PIPELINE` its
    fallback for a source with no `model_index.json` cached yet. Reading that
    file ourselves was wrong in the one case that matters — a not-yet-fetched
    model has none on disk, so every such repo loaded as the DEFAULT, and
    FLUX.2 dev trained through Klein's prompt path with an ordinary loss
    curve."""
    tree = ast.parse((ENGINES_DIR / f"{name}.py").read_text(encoding="utf-8"))
    assigned = {n.targets[0].id: n.value for n in tree.body
                if isinstance(n, ast.Assign)
                and isinstance(n.targets[0], ast.Name)}
    assert "PIPELINE" in assigned, f"{name}.py declares no PIPELINE"
    if "PIPELINES" in assigned:
        family = [e.value for e in assigned["PIPELINES"].elts]
        assert len(set(family)) == len(family), f"{name}.py repeats a pipeline"
        assert assigned["PIPELINE"].value in family, (
            f"{name}.py's fallback is outside its own family")


def test_a_lycoris_named_engine_is_one_ComfyUI_maps_that_way(name=None):
    """`lycoris_named` says ComfyUI builds its `lycoris_` module map for this
    architecture — true for the diffusers-named transformers (`comfy/lora.py`'s
    Flux and QwenImage branches), false for the SD/SDXL UNet, which it maps as
    `lora_unet_` over ldm names this app does not reproduce.

    Claiming it wrongly costs a file whose every key is rejected, which reads
    as a broken adapter rather than a wrong prefix — so only a DiT may.
    """
    for engine in ENGINES:
        declared = _declared(engine)
        if "lycoris_named" not in declared:
            continue
        value = declared["lycoris_named"]
        assert isinstance(value, ast.Constant), engine
        if value.value:
            assert _is_dit(engine), (
                f"{engine}.py claims ComfyUI's `lycoris_` naming, but it "
                f"trains a UNet — ComfyUI maps those as `lora_unet_` over ldm "
                f"names, so every key in the exported file would be rejected")


@pytest.mark.parametrize("name", ENGINES)
def test_train_step_runs_the_backbone_under_the_engines_autocast(name):
    """A FULL finetune upcasts the trainable weights to fp32 masters, so
    without `self.autocast()` the forward dies on "expected mat1 and mat2 to
    have the same dtype". `chroma.py` was the one that did not, and it is the
    exact bug that surfaces the first time somebody picks the method."""
    cls = _engine_class(name)
    step = next((n for n in ast.walk(cls)
                 if isinstance(n, ast.FunctionDef) and n.name == "train_step"),
                None)
    assert step is not None, f"{name}.py has no train_step"
    used = any(isinstance(n, ast.Attribute) and n.attr == "autocast"
               for n in ast.walk(step))
    assert used, (
        f"{name}.py's train_step never enters `self.autocast()`, so a full "
        f"finetune dies on a dtype mismatch the first time it is picked")


def _names(expr) -> tuple[str, ...]:
    """A class-level tuple of string constants, or () for anything else."""
    if isinstance(expr, ast.Tuple):
        return tuple(e.value for e in expr.elts if isinstance(e, ast.Constant))
    return ()


@pytest.mark.parametrize("name", ENGINES)
def test_the_text_encoders_an_engine_trains_are_ones_it_has_and_the_registry_agrees(name):
    """`train_text_encoder` on a DiT is three declarations that have to agree
    with each other and with the registry, and every disagreement is silent:

    * the encoders an adapter may be laid over (`trainable_text_encoders`),
      the LARGE ones among them (`large_text_encoders`) and the per-component
      target lists must all name components the engine actually takes off
      the pipeline (`text_encoder_components`) — a name outside that set is
      an adapter attached to nothing, which trains happily;
    * the registry's `te_act_gb` is ALSO the "does this model train an
      encoder" signal the editor reads (0 disables the toggle), so it must be
      non-zero exactly for the engines that declare a trainable encoder or
      override `trained_text_encoders` (SD, SDXL);
    * and `te_pooled_act_gb` is the "does the large-encoder switch apply"
      signal, so it must be non-zero exactly where an engine has BOTH a large
      encoder and a small one beside it — FLUX.1, and nothing else today.
    """
    cls = _engine_class(name)
    declared = _declared(name)
    comps = (_names(declared["text_encoder_components"])
             if "text_encoder_components" in declared else ("text_encoder",))
    trainable = _names(declared.get("trainable_text_encoders"))
    large = _names(declared.get("large_text_encoders"))
    targets = declared.get("text_encoder_targets")
    target_keys = tuple(k.value for k in targets.keys) \
        if isinstance(targets, ast.Dict) else ()
    assert set(large) <= set(trainable) <= set(comps), (
        f"{name}: large={large} trainable={trainable} components={comps}")
    assert set(target_keys) <= set(trainable), (
        f"{name}: targets named for {target_keys}, trains {trainable}")
    overrides = any(isinstance(n, ast.FunctionDef)
                    and n.name == "trained_text_encoders" for n in cls.body)
    trains = bool(trainable) or overrides
    pooled = bool(large) and bool(set(trainable) - set(large))
    for m in REGISTRY:
        if m.engine != name:
            continue
        assert (m.te_act_gb > 0) == trains, (
            f"{m.key}: te_act_gb={m.te_act_gb} but the {name} engine "
            f"{'trains' if trains else 'trains no'} text encoder — the "
            f"editor reads 0 as 'this model has none'")
        assert (m.te_pooled_act_gb > 0) == pooled, (
            f"{m.key}: te_pooled_act_gb={m.te_pooled_act_gb} but the engine "
            f"{'has' if pooled else 'has no'} small encoder beside a large one")
        if trains:
            assert m.te_params_m_per_rank > 0, (
                f"{m.key}: trains an encoder with no adapter parameter count")
        if pooled:
            assert 0 < m.te_pooled_params_m_per_rank < m.te_params_m_per_rank, m.key


@pytest.mark.parametrize("name", ENGINES)
def test_what_save_portable_writes_is_what_portable_parts_claims(name):
    """`portable_parts` is what the checkpoint's metadata TELLS a loader,
    and `save_portable` is what actually goes in the file. They have to be
    the same set.

    SDXL's were not: its `save_portable` writes
    `text_encoder_2_lora_layers` while `portable_text_encoders` was left at
    the base default naming `text_encoder` alone — so the metadata said the
    second encoder lived only in the trainer's own file, and loading such an
    adapter attached it TWICE (once by diffusers out of the portable file,
    once by `generate._attach_parts` coming back for it). PEFT refuses that
    outright: "Adapter with name l0 already exists". Nothing else could see
    it — the file is right, the metadata is right-shaped, and the run that
    wrote them is unaffected; only a LOAD fails, and only for a LoRA that
    trained the text encoder.

    Read off the `<component>_lora_layers` keys the override writes, which
    is the one place the truth is stated in code.
    """
    src = _engine_class(name)
    keys = {n.value[: -len("_lora_layers")]
            for n in ast.walk(src)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.endswith("_lora_layers")
            and n.value != "_lora_layers"}
    if not keys:
        pytest.skip("takes the base `save_portable`, which IS portable_parts")
    declared = _declared(name)
    base = _base_defaults()
    node = declared.get("portable_text_encoders")
    if node is not None:
        encoders = {e.value for e in node.elts}
    else:
        encoders = set(base.get("portable_text_encoders") or ("text_encoder",))
    backbone = "transformer" if _is_dit(name) else "unet"
    assert keys - {backbone} == encoders, (
        f"{name}: save_portable writes {sorted(keys - {backbone})} but "
        f"portable_text_encoders declares {sorted(encoders)} — the metadata "
        f"would send a loader back for a part the file already carries")
