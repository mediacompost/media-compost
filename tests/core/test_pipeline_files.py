"""The rule that decides which files of a diffusers repo we care about.

Everything here is offline and pure: `pipeline_files` reads a
`model_index.json` and a list of file names, and nothing else.
"""

import json

from media_compost.hub import pipeline_files as pf
from tests.core.conftest import TRAINING_SCRIPTS

# A Stable-Diffusion-1.5-shaped manifest: the safety checker and its feature
# extractor are the optional pair the trainer always passes as None.
SD15_INDEX = {
    "_class_name": "StableDiffusionPipeline",
    "_diffusers_version": "0.6.0",
    "requires_safety_checker": True,
    "feature_extractor": ["transformers", "CLIPImageProcessor"],
    "safety_checker": ["stable_diffusion", "StableDiffusionSafetyChecker"],
    "scheduler": ["diffusers", "PNDMScheduler"],
    "text_encoder": ["transformers", "CLIPTextModel"],
    "tokenizer": ["transformers", "CLIPTokenizer"],
    "unet": ["diffusers", "UNet2DConditionModel"],
    "vae": ["diffusers", "AutoencoderKL"],
}


def test_components_skip_metadata_and_optional_parts():
    comps = dict(pf.required_components(SD15_INDEX))
    # `_class_name` is metadata and `requires_safety_checker` is a plain
    # argument; neither is a folder.
    assert "_class_name" not in comps and "requires_safety_checker" not in comps
    # Optional: requiring these reported SD 1.5 incomplete forever, because
    # its cached safety_checker/ holds a config and no weights.
    assert "safety_checker" not in comps and "feature_extractor" not in comps
    # Weights vs configuration.
    assert comps["unet"] is True and comps["text_encoder"] is True
    assert comps["tokenizer"] is False and comps["scheduler"] is False


def test_pick_weights_prefers_one_plain_safetensors():
    assert pf.pick_weights(["diffusion_pytorch_model.safetensors",
                            "diffusion_pytorch_model.fp16.safetensors",
                            "diffusion_pytorch_model.bin",
                            "config.json"]) == ["diffusion_pytorch_model.safetensors"]
    # `.bin` only when there is nothing better.
    assert pf.pick_weights(["diffusion_pytorch_model.bin"]) == \
        ["diffusion_pytorch_model.bin"]
    # A variant alone is not the file `from_pretrained(repo)` would open.
    assert pf.pick_weights(["diffusion_pytorch_model.fp16.safetensors"]) == []
    assert pf.pick_weights(["config.json"]) == []


def test_pick_weights_keeps_every_shard_and_its_index():
    picked = pf.pick_weights([
        "config.json",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
        "model.safetensors.index.json",
    ])
    assert picked == ["model-00001-of-00002.safetensors",
                      "model-00002-of-00002.safetensors",
                      "model.safetensors.index.json"]


def test_a_short_shard_set_is_no_checkpoint_at_all():
    """A cancelled download leaves SOME of the shards, and answering with the
    ones that arrived is how a model reports itself Downloaded while four
    fifths of it is missing.

    Measured on a real cache: `Qwen/Qwen-Image-Edit-2509` held one of its five
    transformer shards and `local_state` said "ready" — so the Models page
    called it Downloaded, the Download button had nothing left to do, and
    `snapshot_dir_for` handed diffusers a directory without the weights, which
    fails minutes into a training run instead of before it.
    """
    assert pf.pick_weights([
        "config.json",
        "model-00005-of-00005.safetensors",
        "model.safetensors.index.json",
    ]) == []
    # …and one shard short of the full set is still short.
    assert pf.pick_weights([
        "model-00001-of-00003.safetensors",
        "model-00002-of-00003.safetensors",
    ]) == []


def test_a_partial_shard_set_reads_as_partial(tmp_path, monkeypatch):
    """The same fact one level up: what `local_state` answers is what the
    Models page shows and what `snapshot_dir_for` gates the local load on."""
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "model_index.json").write_text(json.dumps(SD15_INDEX))
    for folder, names in _files(False).items():
        (snap / folder).mkdir()
        for n in names:
            (snap / folder / n).write_text("x")
    monkeypatch.setattr(pf, "cached_index", lambda repo: (SD15_INDEX, snap))

    unet = snap / "unet"
    (unet / "diffusion_pytorch_model-00002-of-00002.safetensors").write_text("x")
    (unet / "diffusion_pytorch_model.safetensors.index.json").write_text("{}")
    assert pf.local_state("repo") == "partial"

    (unet / "diffusion_pytorch_model-00001-of-00002.safetensors").write_text("x")
    assert pf.local_state("repo") == "ready"


def _files(with_unet_weights: bool) -> dict[str, list[str]]:
    return {
        "scheduler": ["scheduler_config.json"],
        "text_encoder": ["config.json", "model.safetensors"],
        "tokenizer": ["vocab.json", "merges.txt"],
        "unet": ["config.json"] + (["diffusion_pytorch_model.safetensors"]
                                   if with_unet_weights else []),
        "vae": ["config.json", "diffusion_pytorch_model.safetensors"],
    }


def test_wanted_files_is_complete_without_the_safety_checker():
    wanted, complete = pf._wanted_files(SD15_INDEX, _files(True))
    assert complete
    assert "model_index.json" in wanted
    assert "unet/diffusion_pytorch_model.safetensors" in wanted
    # The 43 GB of extras a whole-repo download would have pulled.
    assert not any(w.startswith("safety_checker/") for w in wanted)
    assert not any(".fp16." in w or w.endswith(".ckpt") for w in wanted)


def test_a_chat_template_counts_as_a_tokenizer_file():
    """FLUX.2's text encoder is an instruct LLM and its pipeline calls
    `apply_chat_template`, so `tokenizer/chat_template.jinja` is as required as
    `vocab.json`. Without it the snapshot loads and then fails at the first
    prompt — the kind of missing file that looks like a model bug."""
    files = _files(True)
    files["tokenizer"] = ["vocab.json", "merges.txt", "chat_template.jinja"]
    wanted, complete = pf._wanted_files(SD15_INDEX, files)
    assert complete
    assert "tokenizer/chat_template.jinja" in wanted


def test_missing_weights_are_incomplete():
    _, complete = pf._wanted_files(SD15_INDEX, _files(False))
    assert not complete


def test_local_state_reads_a_cached_snapshot(tmp_path, monkeypatch):
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "model_index.json").write_text(json.dumps(SD15_INDEX))
    for folder, names in _files(False).items():
        (snap / folder).mkdir()
        for n in names:
            (snap / folder / n).write_text("x")
    monkeypatch.setattr(pf, "cached_index",
                        lambda repo: (SD15_INDEX, snap))
    assert pf.local_state("repo") == "partial"

    (snap / "unet" / "diffusion_pytorch_model.safetensors").write_text("x")
    assert pf.local_state("repo") == "ready"


def test_only_the_manifest_is_not_a_partial_download(tmp_path, monkeypatch):
    """`download_patterns` fetches model_index.json to work out what to ask
    for; that alone must not make the row read "partly downloaded"."""
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "model_index.json").write_text(json.dumps(SD15_INDEX))
    monkeypatch.setattr(pf, "cached_index", lambda repo: (SD15_INDEX, snap))
    assert pf.local_state("repo") == "none"


def test_unknown_repo_shape_defers_to_the_caller(monkeypatch):
    monkeypatch.setattr(pf, "cached_index", lambda repo: None)
    assert pf.local_state("repo") is None


def _pipeline_opts():
    """`train/scripts/` (the trainer) is standalone (its own venv, no media_compost), so
    it carries its own copy of the optional-component set and is imported here
    by PATH — the same way `compose.py` is tested."""
    import importlib.util
    import pathlib

    path = TRAINING_SCRIPTS / "pipeline_opts.py"
    spec = importlib.util.spec_from_file_location("pipeline_opts", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_trainer_disables_exactly_what_the_download_skips():
    """Two halves of one contract. `pipeline_files` drops these components
    from the download; the trainer and the generator must therefore pass each
    of them as None, or diffusers builds one and looks for files that were
    never fetched.

    Only `safety_checker` used to be passed, so a FRESHLY downloaded SD 1.5
    died in `from_pretrained` with "Can't load image processor ... containing
    a preprocessor_config.json" — invisible on any machine whose cache had
    once held the full snapshot.
    """
    assert _pipeline_opts().OPTIONAL_COMPONENTS == pf.OPTIONAL_COMPONENTS


def test_disabled_kwargs_names_only_declared_components():
    opts = _pipeline_opts()
    kw = opts.disabled_kwargs(SD15_INDEX)
    assert kw == {"safety_checker": None, "feature_extractor": None}
    assert all(v is None for v in opts.disabled_kwargs().values())
    assert set(opts.disabled_kwargs()) == pf.OPTIONAL_COMPONENTS
