"""Which files of a diffusers repo a pipeline actually loads.

Both "is this base model downloaded?" and "download this base model" used to
be measured against the WHOLE Hugging Face repo, which is wrong in both
directions: SDXL generated images happily from cache while the UI called it
"Partly downloaded", and pressing Download on Stable Diffusion 1.5 — a row
labelled 1.7 GB — would have fetched 43 GB, because a repo carries every
variant (fp16 and fp32, `.bin` beside `.safetensors`) plus the root
single-file checkpoints that `from_pretrained` never looks at.

The rule lives here so readiness and downloading mean the same set of files.
It is expressed purely in `model_index.json` + filename terms: the main venv
is torch-free and must not import diffusers, so we cannot ask
diffusers what it would fetch — we reproduce its choice instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Components a pipeline can run without, and that our trainer/generator do run
# without (both pass `safety_checker=None`). Requiring their weights would
# report Stable Diffusion 1.5 as incomplete forever — its cached
# `safety_checker/` holds a config and no weights, which is exactly right.
OPTIONAL_COMPONENTS = frozenset({
    "safety_checker", "feature_extractor", "image_encoder", "watermarker",
    "safety_feature_extractor",
})

# Class-name endings that mean "this component is configuration, not weights"
# — tokenizers, schedulers and processors are a few JSON/TXT files.
_WEIGHTLESS_SUFFIXES = (
    "Tokenizer", "TokenizerFast", "Scheduler", "FeatureExtractor",
    "ImageProcessor", "Processor",
)

# Weight containers, best first: a component is satisfied by ONE of these
# formats, and safetensors is what diffusers reaches for first.
_WEIGHT_EXTS = (".safetensors", ".bin")

# `diffusion_pytorch_model.fp16.safetensors` and friends — a variant of the
# plain file, which `from_pretrained(repo)` (no `variant=`) does not load.
_VARIANT_RE = re.compile(r"\.(fp16|bf16|fp32|non_ema|ema|openvino|flax)\.")

# `diffusion_pytorch_model-00001-of-00002.safetensors` — the second number is
# how many there are, which is what makes a shard set's completeness readable
# from the file names alone.
_SHARD_RE = re.compile(
    r"^(?P<stem>.+)-\d{5}-of-(?P<total>\d{5})(?P<ext>\.[a-z]+)$")


def required_components(index: dict) -> list[tuple[str, bool]]:
    """`(folder, needs_weights)` for each component `model_index.json` names.

    Keys starting with `_` are metadata, and a plain value (not a
    `[library, class]` pair) is a pipeline argument rather than a component.
    Optional components are dropped entirely — they are not fetched and not
    required.
    """
    out: list[tuple[str, bool]] = []
    for name, value in index.items():
        if name.startswith("_") or name in OPTIONAL_COMPONENTS:
            continue
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            continue
        library, cls = value
        if not library or not cls:
            continue        # e.g. ["null", null] for a disabled component
        needs_weights = not str(cls).endswith(_WEIGHTLESS_SUFFIXES)
        out.append((name, needs_weights))
    return out


def _is_variant(name: str) -> bool:
    return bool(_VARIANT_RE.search(name))


def pick_weights(names: list[str]) -> list[str]:
    """The weight file(s) of one component folder, or [] if none qualify.

    Given the plain file names in a component directory, returns the single
    file `from_pretrained` would read — or, for a sharded checkpoint, its
    index plus every shard. Variants are ignored, and safetensors wins over
    `.bin` so we never fetch both.

    **AN INCOMPLETE SHARD SET IS NOT A CHECKPOINT, and answering with the
    shards that happen to be present is how a half-downloaded model came to
    report itself Downloaded.** The two callers hand this two different
    listings: `download_patterns` passes the HUB's, which is complete by
    construction, while `local_state` passes what is in the CACHE, where a
    cancelled or failed fetch leaves some of the shards behind. A shard names
    the total in its own file name (`-00005-of-00005`), so the set can be
    counted — and a short one returns [] here, which `_wanted_files` reads as
    "not complete". Without that, `Qwen/Qwen-Image-Edit-2509` with one of its
    five transformer shards on disk answered "ready": the Models page called
    it Downloaded, the Download button thought there was nothing left to
    fetch, and `snapshot_dir_for` handed diffusers a directory missing four
    fifths of the model — so the training run died at load rather than at the
    point anybody could have acted on it.
    """
    for ext in _WEIGHT_EXTS:
        cands = [n for n in names if n.endswith(ext) and not _is_variant(n)]
        if not cands:
            continue
        shards = [n for n in cands if _SHARD_RE.match(n)]
        if shards:
            stems = {_SHARD_RE.match(n).group("stem") for n in shards}  # type: ignore[union-attr]
            stem = sorted(stems)[0]
            picked = sorted(n for n in shards
                            if _SHARD_RE.match(n).group("stem") == stem)  # type: ignore[union-attr]
            expected = int(_SHARD_RE.match(picked[0]).group("total"))  # type: ignore[union-attr]
            if len(picked) != expected:
                return []
            index = f"{stem}{ext}.index.json"
            if index in names:
                picked.append(index)
            return picked
        # Unsharded: prefer the conventional name, else the only candidate.
        for conventional in (f"diffusion_pytorch_model{ext}", f"model{ext}",
                             f"pytorch_model{ext}"):
            if conventional in cands:
                return [conventional]
        return [sorted(cands)[0]]
    return []


def _wanted_files(index: dict, files_by_dir: dict[str, list[str]]) -> tuple[list[str], bool]:
    """(repo-relative paths the pipeline needs, everything_available).

    `files_by_dir` maps a component folder to the plain file names in it (as
    listed on the hub, or as present in the cache).
    """
    wanted = ["model_index.json"]
    complete = True
    for folder, needs_weights in required_components(index):
        names = files_by_dir.get(folder) or []
        if not names:
            complete = False
            continue
        # Config/tokenizer files are small and all needed. `.jinja` is in
        # the list because a chat template IS one of them: FLUX.2's text
        # encoder is an instruct LLM and its pipeline calls
        # `apply_chat_template`, so a snapshot without it loads and then
        # fails at the first prompt.
        wanted += [f"{folder}/{n}" for n in names
                   if n.endswith((".json", ".txt", ".model", ".jinja"))
                   and not n.endswith(".index.json")]
        if needs_weights:
            picked = pick_weights(names)
            if not picked:
                complete = False
            wanted += [f"{folder}/{n}" for n in picked]
    return wanted, complete


def _read_json(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - a probe must never raise
        return None


def cached_index(repo: str) -> tuple[dict, Path] | None:
    """The repo's cached `model_index.json` and its snapshot dir, or None."""
    try:
        from huggingface_hub.file_download import try_to_load_from_cache

        hit = try_to_load_from_cache(repo, "model_index.json")
        if not isinstance(hit, str):
            return None
        path = Path(hit)
        index = _read_json(path)
        return (index, path.parent) if index else None
    except Exception:  # noqa: BLE001
        return None


def local_state(repo: str) -> str | None:
    """``"ready"`` | ``"partial"`` | ``"none"`` for a pipeline repo, else None.

    None means "this isn't a diffusers pipeline repo we can judge" (no cached
    `model_index.json`) — the caller falls back to its own standard. A file is
    only linked into the snapshot directory once it is complete, so presence
    there is proof, not a guess.
    """
    got = cached_index(repo)
    if got is None:
        return None
    index, snapshot = got
    files_by_dir: dict[str, list[str]] = {}
    for folder, _ in required_components(index):
        d = snapshot / folder
        if d.is_dir():
            files_by_dir[folder] = [p.name for p in d.iterdir() if p.is_file()]
    if not files_by_dir:
        # Only the manifest is here — which is all `download_patterns` fetches
        # to work out what to ask for. Nothing of the model has arrived, so
        # this is "not downloaded", not "half downloaded".
        return "none"
    _, complete = _wanted_files(index, files_by_dir)
    return "ready" if complete else "partial"


def snapshot_dir_for(repo: str) -> str:
    """The local snapshot directory to load `repo` from, or "".

    Loading by repo id makes diffusers ask the hub what the revision contains.
    With no network it cannot, so it falls back to demanding the WHOLE
    revision from the cache — including the multi-GB single-file checkpoints a
    pipeline never opens — and fails with "model is not cached locally" even
    though every file it would load is right there. Handing it the directory
    skips hub resolution entirely.

    Only returned when the pipeline's own files are complete (`local_state`),
    so an incomplete cache still goes through the hub and can finish itself.
    """
    got = cached_index(repo)
    if got is None or local_state(repo) != "ready":
        return ""
    return str(got[1])


def download_patterns(repo: str, token: str = "") -> tuple[str, ...]:
    """Exact repo-relative paths to fetch for `repo`, or () if unknown.

    Empty means "no idea" — the caller should fall back to downloading the
    whole repo rather than fetching a guessed subset.
    """
    try:
        from huggingface_hub import HfApi, hf_hub_download

        api = HfApi()
        info = api.model_info(repo, token=token or None)
        names = [s.rfilename for s in (info.siblings or [])]
        if "model_index.json" not in names:
            return ()
        index_path = hf_hub_download(repo, "model_index.json",
                                     token=token or None)
        index = _read_json(Path(index_path))
        if not index:
            return ()
        files_by_dir: dict[str, list[str]] = {}
        for name in names:
            folder, sep, plain = name.partition("/")
            if sep and "/" not in plain:
                files_by_dir.setdefault(folder, []).append(plain)
        wanted, _ = _wanted_files(index, files_by_dir)
        return tuple(wanted)
    except Exception:  # noqa: BLE001 - never block a download over this
        return ()


__all__ = [
    "OPTIONAL_COMPONENTS", "required_components", "pick_weights",
    "cached_index", "local_state", "download_patterns",
]