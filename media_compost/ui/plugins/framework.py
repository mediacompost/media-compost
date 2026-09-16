"""Plugin metadata types and host-side helpers.

The dataclasses here describe a plugin to the *host* (the main server process):
what models it offers, its downloadable weight sources, its runtime deps and
environment. They import cleanly with no heavy ML deps, so the host can import
every plugin's manifest to build the catalog. The actual inference (a plugin's
``load``/``run``) happens out-of-process in a worker; see ``worker.py``/``host.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from media_compost.hub import cache as _cache, venv as _venv


# ---- metadata -------------------------------------------------------------

@dataclass
class ModelSource:
    """A downloadable model *family* — the unit the Settings model-cache,
    local-path overrides and per-model download work on."""

    key: str
    label: str
    repo: str            # default Hugging Face repo id
    url: str = ""        # model page (a link in Settings / help)
    gated: bool = False  # requires accepting a license + a token to download
    onnx: bool = False   # ONNX weights (needs onnxruntime, not torch)
    probe: str = "config.json"  # a repo file whose presence marks it downloaded
    # When set, only these path globs are fetched from ``repo`` (so a single file
    # can be pulled from a large multi-model repo instead of the whole snapshot).
    #
    # **UNSET MEANS THE WHOLE REPO.** `pipeline_files.download_patterns` only
    # narrows a diffusers pipeline (it reads `model_index.json`), so a plain
    # transformers or ONNX repo with none of these declared is fetched entire —
    # measured: `lllyasviel/Annotators` 10.6 GB for the ~850 MB one annotator
    # loads, `Salesforce/blip2-opt-2.7b` 30.5 GB because it carries `.bin`
    # beside `.safetensors`, `Ultralytics/YOLO11` 728 MB for a 6 MB pose model.
    #
    # **AND THE `probe` MUST NAME A FILE THESE FETCH — a WEIGHT file.** The two
    # fields are one statement: patterns say what to get and the probe says
    # whether it arrived, so a probe of `config.json` beside a weight glob that
    # matches nothing is a row that reads "Downloaded" over a model with no
    # weights, which is the RAM++ failure wearing a different hat. Naming the
    # weight makes a wrong glob read as "not downloaded" — loud, and in the
    # direction that can be acted on.
    allow_patterns: tuple[str, ...] = ()


#: The small files a `from_pretrained` repo needs beside its weights: config,
#: tokenizer, processor, generation config, and — for a `trust_remote_code`
#: model like Florence-2 — the `.py` that defines the architecture. Kilobytes
#: all of them, so this is deliberately a generous superset: the bytes worth
#: being careful about are the weights, and a config file left out is a load
#: that fails on a machine somebody has just told "this is downloaded".
TRANSFORMERS_CONFIG_FILES: tuple[str, ...] = ("*.json", "*.txt", "*.py", "*.model")


@dataclass
class ModelSpec:
    """One selectable entry in an action menu (a plugin may offer several)."""

    id: str              # stable id, keeps the "family:variant" convention
    task: str            # one of tasks.TASKS kinds
    name: str
    family: str = ""     # UI grouping header
    variant: str = ""    # UI sub-entry within a family
    note: str = ""
    # True when the model needs a user-picked color-reference image: the UI
    # opens the reference picker before enqueueing, and the job carries the
    # chosen image's path in its options.
    needs_reference: bool = False
    # (There was a `superseded_by` here: the id of a model that does everything
    # this one does and more, which hid this one from the action menus while
    # THAT one was ready. Its only user was `anime_face`, the detector-only
    # illustrated-face plugin, and that plugin is gone — a model worth hiding
    # whenever its successor is installed turned out to be a model not worth
    # offering at all. Bring it back when a second case actually appears; a
    # field with no declarer is a rule nobody can find the subject of.)


@dataclass
class PluginManifest:
    """Everything the host needs to know about a plugin without running it."""

    models: list[ModelSpec]
    sources: list[ModelSource] = field(default_factory=list)
    # Packages needed to *run* the model, for the availability check + help text
    # (only meaningful for env == "main"; a dedicated env is "ready" when its
    # interpreter resolves).
    deps: tuple[str, ...] = ()
    env: str = "main"    # "main" (backend venv) or a dedicated venv name
    url: str = ""        # reference URL
    # model id -> the ModelSource key that backs it (for the UI cache join).
    source_for_model: dict = field(default_factory=dict)
    # Shell commands the "Run setup" button executes (in order, from the repo
    # root; "{python}" expands to the backend venv's interpreter, "{pip}" to
    # how pip is driven for it — see ``hub/setup.pip_spec``). Empty =
    # synthesized from ``deps``/``env`` — see :func:`setup_commands`.
    setup: tuple[str, ...] = ()


# ---- environment / interpreter resolution ---------------------------------
#
# The rules themselves live in `media_compost.hub` — the trainer needs the same
# ones and cannot import the plugin system. What stays here is the part that is
# actually about plugins: where the worker script is, and what a MANIFEST means
# by "ready".

def repo_root() -> str:
    """The checkout: where ``scripts/`` lives and where the dedicated venvs sit.

    One notion, not two. It used to be ``backend_dir()`` — the parent of the
    ``media_compost`` package — which happened to be both. Splitting the tree
    into ``core/``, ``ui/`` and ``train/`` separated them, and the answer that
    survives is the checkout: a ``.venv-magi`` belongs to the working copy you
    ran the env setup from, not to whichever package imported it.

    ``MEDIA_COMPOST_<ENV>_PYTHON`` is the way out for a layout this cannot
    guess — an installed, non-editable deployment above all, where the package
    lives in site-packages and there is no checkout at all.
    """
    # media_compost/ui/plugins/framework.py -> ui -> media_compost -> repo
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def worker_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")


def interpreter_for(env: str) -> Optional[str]:
    """The Python executable that runs a plugin's worker."""
    return _venv.interpreter_for(env, repo_root())


# ---- dependency / cache status (host-side) --------------------------------

def deps_ok(manifest: PluginManifest) -> bool:
    """Whether a plugin's models can run: its dedicated env resolves, or (for
    the main env) every declared package imports."""
    if manifest.env != "main":
        return interpreter_for(manifest.env) is not None
    return all(_venv.has_module(m) for m in manifest.deps)


def source_cached(src: ModelSource, local_path: str = "") -> bool:
    """Whether ``src``'s weights are present — at a local-path override, or
    fully in the Hugging Face cache."""
    return _cache.repo_cached(src.repo, src.probe, local_path)


def delete_cached(src: ModelSource) -> bool:
    """Remove ``src``'s downloaded weights from the Hugging Face cache."""
    return _cache.delete_repo(src.repo)


def cache_sizes() -> dict:
    """``repo_id`` -> total on-disk bytes for everything in the HF cache."""
    return _cache.cache_sizes()


def resolve_sources(manifest: PluginManifest, model_paths: dict) -> dict:
    """The concrete path/repo to load each of a plugin's sources from: the user's
    local-path override if set, otherwise the default HF repo id. Passed to the
    worker in the run context so ``load`` need not know about settings."""
    out: dict = {}
    for s in manifest.sources:
        p = (model_paths or {}).get(s.key)
        out[s.key] = p.strip() if p and p.strip() else s.repo
    return out


# Import name -> pip package name, for the deps whose two names differ (the
# synthesized "pip install" setup command below uses pip names).
_PIP_NAME = {
    "cv2": "opencv-python-headless",
    "PIL": "pillow",
    "qwen_vl_utils": "qwen-vl-utils",
}


def repo_files(src: str, names: tuple[str, ...], ctx: dict) -> str:
    """The directory holding ``names`` for a plugin source that is either a
    local folder or a Hugging Face repo — THE FILES BY NAME, NEVER
    `snapshot_download`.

    The app's setup fetches a repo NARROWED to what the plugin reads
    (`ModelSource.allow_patterns`: the tagger's ONNX file and tag list,
    not the 1.2 GB of msgpack and safetensors beside them), and
    huggingface_hub 1.x's offline `snapshot_download` REFUSES a snapshot
    missing any file of the revision (`IncompleteSnapshotError`, "7 file(s)
    are missing") — so a machine whose weights came through Run setup could
    never load such a plugin, while a full copy of the cache (the dev Mac's)
    hid it. `hf_hub_download` answers per file, offline or not, and every
    file of one revision lands in one snapshot directory.
    """
    if os.path.isdir(src):
        return src
    from huggingface_hub import hf_hub_download

    local = bool(ctx.get("local_files_only", True))
    token = ctx.get("token") or None
    paths = [hf_hub_download(src, n, local_files_only=local, token=token)
             for n in names]
    return os.path.dirname(paths[0])


def setup_commands(manifest: PluginManifest) -> list[str]:
    """The shell commands the "Run setup" button executes for a plugin.

    An explicit ``manifest.setup`` wins; otherwise a dedicated-env plugin runs
    ``-m media_compost.hub.setup_env`` and a main-env plugin with missing deps
    gets a synthesized ``pip install``. The setup module is named with ``-m``
    rather than as a file under ``scripts/`` because a wheel install has no
    checkout — the module resolves wherever the package is installed, and the
    file did not exist there at all. ``{python}`` expands (in the runner) to the
    backend venv's interpreter and ``{pip}`` to how pip is driven for it —
    ``-m pip``, or ``uv pip`` where the venv was made by uv and carries no
    pip (``hub/setup.pip_spec``). Empty = nothing to run automatically.

    The env setup is invoked through ``{python}`` and not through ``bash``:
    the runner executes these with ``shell=True``, whose shell is ``cmd.exe``
    on Windows, where ``bash`` is whatever a Git install may or may not have
    put on PATH. ``{python}`` is the interpreter already running the server,
    so it exists by construction.

    torch is NOT a plain pip install: PyPI's Windows wheel is CPU-only (the
    CUDA builds live on download.pytorch.org, and a dependency specifier
    cannot name an index), so the torch pair goes through ``setup_env``'s
    torch mode — which owns the index decision — as the LAST command, after
    everything else, so no dependency of the rest (ultralytics →
    torchvision is the measured case) can drag a CPU build back in over it.
    An explicit ``manifest.setup`` that needs torch spells the same command
    itself (ram_plus). A plugin whose ONLY dep is torch (text_removal) needs
    no `setup` at all — this synthesizes exactly that one command.

    onnxruntime is the same trap on EVERY platform: PyPI's `onnxruntime` has
    no GPU execution provider, and the CUDA build is a different package
    (`onnxruntime-gpu`, with extras for the runtime libraries) that must
    replace it rather than sit beside it. So that dependency goes through
    `setup_env onnxruntime`, which owns the driver-or-not decision, after
    the plain pip line and before torch (a dependency of the rest could
    only pull the CPU wheel back in through `onnxruntime`, and rapidocr,
    insightface and withoutbg all name it — hence after).
    """
    if manifest.setup:
        return list(manifest.setup)
    if manifest.env != "main":
        return ["{python} -m media_compost.hub.setup_env " + manifest.env]
    if manifest.deps:
        pkgs = [_PIP_NAME.get(d, d) for d in manifest.deps]
        rest = [p for p in pkgs
                if p not in ("torch", "torchvision", "onnxruntime")]
        cmds = []
        if rest:
            cmds.append("{pip} install " + " ".join(rest))
        if "onnxruntime" in pkgs:
            cmds.append("{python} -m media_compost.hub.setup_env onnxruntime")
        if any(p in ("torch", "torchvision") for p in pkgs):
            cmds.append("{python} -m media_compost.hub.setup_env torch")
        return cmds
    return []
