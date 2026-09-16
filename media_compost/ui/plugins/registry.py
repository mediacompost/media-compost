"""The enabled-plugins registry.

Adding a model = create its file under ``impl/`` and add its module name to
:data:`PLUGIN_MODULES`. Removing a model = delete the file and the line. Nothing
else references individual plugins — the rest of the app goes through the
accessors here (``models_for``, ``all_sources``, ``plugin_for`` …).
"""

from __future__ import annotations

import importlib

from .framework import ModelSource, ModelSpec, PluginManifest


# Enabled plugin modules, by their ``impl.<name>`` module name. Order sets the
# catalog order within each task.
PLUGIN_MODULES: list[str] = [
    "withoutbg",
    "watermark",
    "text_removal",
    "upscale_swin2sr",
    "upscale_esrgan",
    "dejpeg_fbcnn",
    "restore_scunet",
    "colorize_photo",
    "colorize_mangav2",
    "colorize_manga",
    "descreen",
    "descreen_opencomic",
    "joycaption",
    "florence",
    "blip2",
    "qwen2_5_vl",
    "joytag",
    "wd_tagger",
    "ram_plus",
    "depth_transformers",
    "leres",
    "yolo_pose",
    "openpose",
    "canny",
    "lineart",
    # BEFORE magi_panels, so RapidOCR's multilingual model is the OCR task's
    # default: Magi v3's OCR reads ENGLISH only (measured — a Japanese page
    # returns nothing, see its docstring), and a default that answers empty
    # on most of a Japanese library is the wrong default. Order only sets
    # the catalog within each task, so panels are untouched.
    "rapid_ocr",
    "magi_panels",
    "anime_face_magi",
    "insightface_faces",
    "dinov2_embed",
    "clip_embed",
]


class LoadedPlugin:
    """A plugin module paired with its manifest, resolved once."""

    def __init__(self, module):
        self.module = module
        self.manifest: PluginManifest = module.MANIFEST
        self.file: str = module.__file__
        # Short module name ("watermark", "text_removal", …) — the key the
        # setup-runner endpoints use.
        self.key: str = module.__name__.rsplit(".", 1)[-1]

    @property
    def env(self) -> str:
        return self.manifest.env

    def models(self) -> list[ModelSpec]:
        """The selectable models this plugin offers. Static from the manifest by
        default; a plugin may define a ``models()`` function for a runtime list
        (e.g. Florence exposing only the active checkpoint)."""
        fn = getattr(self.module, "models", None)
        return fn() if callable(fn) else self.manifest.models

    def owns(self, model_id: str) -> bool:
        fn = getattr(self.module, "owns", None)
        if callable(fn):
            return fn(model_id)
        return any(m.id == model_id for m in self.models())

    def source_keys_for(self, model_id: str) -> list[str]:
        """All downloadable-source keys ``model_id`` needs (for the UI cache
        join). A plugin's ``source_for_model`` value may be a single key or a list
        (e.g. watermark removal needs a detector + an inpainter)."""
        fn = getattr(self.module, "source_for_model", None)
        val = fn(model_id) if callable(fn) else self.manifest.source_for_model.get(model_id, "")
        if not val:
            return []
        return list(val) if isinstance(val, (list, tuple)) else [val]

    def source_key_for(self, model_id: str) -> str:
        """The primary source key for ``model_id`` (the first of source_keys_for)."""
        keys = self.source_keys_for(model_id)
        return keys[0] if keys else ""

    def load_key(self, model_id: str) -> str:
        """Identity of the weights to load for ``model_id``. Several menu models
        can share one (e.g. prompt variants), so the host reuses a warm worker
        across them. Defaults to the model id; a plugin may define its own."""
        fn = getattr(self.module, "load_key", None)
        return fn(model_id) if callable(fn) else model_id


_cache: list[LoadedPlugin] | None = None


def _load(name: str) -> LoadedPlugin:
    return LoadedPlugin(importlib.import_module(f"{__package__}.impl.{name}"))


def plugins() -> list[LoadedPlugin]:
    global _cache
    if _cache is None:
        _cache = [_load(n) for n in PLUGIN_MODULES]
    return _cache


def reset() -> None:
    """Drop the cached plugin list (tests that mutate PLUGIN_MODULES)."""
    global _cache
    _cache = None


def models_for(kind: str) -> list[ModelSpec]:
    out: list[ModelSpec] = []
    for p in plugins():
        out.extend(m for m in p.models() if m.task == kind)
    return out


def plugin_for(model_id: str) -> LoadedPlugin | None:
    for p in plugins():
        if p.owns(model_id):
            return p
    return None


def spec_for(model_id: str) -> ModelSpec | None:
    for p in plugins():
        for m in p.models():
            if m.id == model_id:
                return m
    return None


def source_key_for_model(model_id: str) -> str:
    p = plugin_for(model_id)
    return p.source_key_for(model_id) if p is not None else ""


def source_keys_for_model(model_id: str) -> list[str]:
    p = plugin_for(model_id)
    return p.source_keys_for(model_id) if p is not None else []


def resolve_model(kind: str, model_id: str) -> str:
    """Fall back to the first model of ``kind`` when the id is empty/unknown."""
    ids = [m.id for m in models_for(kind)]
    return model_id if model_id in ids else (ids[0] if ids else "")


def default_model(kind: str) -> str:
    return resolve_model(kind, "")


def model_label(model_id: str) -> str:
    sp = spec_for(model_id)
    return sp.name if sp is not None else (model_id or "AI")


def available(model_id: str) -> bool:
    """Whether ``model_id`` can run (its plugin's deps/env are satisfied)."""
    from .framework import deps_ok
    p = plugin_for(model_id)
    return deps_ok(p.manifest) if p is not None else False


def source_deps_ok(key: str) -> bool:
    """Whether the packages/env needed to run the plugin owning source ``key``
    are satisfied (drives the Settings 'needs setup' badge)."""
    from .framework import deps_ok
    for p in plugins():
        if any(s.key == key for s in p.manifest.sources):
            return deps_ok(p.manifest)
    return False


def plugin_for_source(key: str) -> "LoadedPlugin | None":
    """The plugin owning source ``key``."""
    for p in plugins():
        if any(s.key == key for s in p.manifest.sources):
            return p
    return None


def source_weights_ready(key: str) -> bool:
    """Whether the plugin owning source ``key`` has the weights that do NOT
    come from that source.

    A plugin's sources are not always the whole story: RAM++ pulls a BERT
    tokenizer from a second repo, from inside the `ram` package, and a
    readiness answer built from the declared source alone said "Downloaded"
    over a model whose first run still had to go to the network. Asked for
    EVERY source row, not just for the sourceless plugins `plugin_weights_ready`
    was written for — that gap is what let this one through.
    """
    p = plugin_for_source(key)
    return plugin_weights_ready(p.key) if p is not None else True


def setup_only_plugins() -> list["LoadedPlugin"]:
    """Plugins with NOTHING to download but something to install.

    The Settings model list is built from downloadable sources, so a plugin
    whose weights arrive some other way — InsightFace fetches its own pack on
    first use — was invisible there: the page that answers "what models are
    there, and are they ready" simply did not mention it. A plugin with neither
    sources nor deps (Canny) has nothing to say and stays out.
    """
    return [p for p in plugins()
            if not p.manifest.sources and p.manifest.deps and p.models()]


def plugin_by_key(key: str) -> "LoadedPlugin | None":
    """A plugin by its own key (not a source key). Setup-only plugins are keyed
    on the plugin in the Settings list, so the download/status endpoints have to
    be able to find them again."""
    for p in plugins():
        if p.key == key:
            return p
    return None


def plugin_weights_ready(key: str) -> bool:
    """Whether a plugin's own weights are on disk.

    Weights that do not come from Hugging Face have no cache probe, so a plugin
    that fetches its own (InsightFace's pack, the OpenComic graphs) says so
    itself. A plugin with nothing to fetch is always ready.
    """
    p = plugin_by_key(key)
    fn = getattr(p.module, "weights_ready", None) if p else None
    if fn is None:
        return True
    try:
        return bool(fn())
    except Exception:  # noqa: BLE001 - a probe must never break the page
        return False


def plugin_can_fetch(key: str) -> bool:
    """Whether a plugin knows how to download its own weights."""
    p = plugin_by_key(key)
    return p is not None and callable(getattr(p.module, "fetch_weights", None))


def all_sources() -> list[ModelSource]:
    """Every downloadable source across all plugins, de-duplicated by key,
    preserving registry order."""
    seen: dict[str, ModelSource] = {}
    for p in plugins():
        for s in p.manifest.sources:
            seen.setdefault(s.key, s)
    return list(seen.values())


def source_for(key: str) -> ModelSource | None:
    return next((s for s in all_sources() if s.key == key), None)


def setup_key_for_source(key: str) -> str:
    """The plugin key whose setup covers a downloadable source (for the
    Settings/help "Run setup" button), or "" if no plugin owns it.

    Unconditional now: setup is `-m media_compost.ui.plugins.setup_action
    <key>`, which always
    has something to do — the packages, the weights, or both. It used to be
    gated on `setup_commands` being non-empty, from when setup meant packages
    ONLY and a plugin whose dependencies were already satisfied had nothing to
    offer but a page of instructions.
    """
    for p in plugins():
        if any(s.key == key for s in p.manifest.sources):
            return p.key
    return ""


# Per-source-key overrides: sources that provide a shared *capability* get
# their own Settings section instead of the owning plugin's task category —
# big-lama serves watermark/text removal AND the editor's inpaint tool, and
# the detectors also drive the editor's "Select text / watermark".
_SOURCE_CATEGORY_BY_KEY: dict[str, str] = {
    "big_lama": "Inpainting",
    "anime_lama": "Inpainting",
    "wm_yolo11x": "Text",
}

# A downloadable source's *type* — a coarse grouping for the Settings model list,
# keyed off the task the source's models serve. Several tasks fold into one
# category (the four ControlNet annotators become "Control images").
_SOURCE_CATEGORY: dict[str, str] = {
    "bg_removal": "Background removal",
    "watermark_removal": "Watermark removal",
    "text_removal": "Text removal",
    "upscale": "Upscaling",
    "restore": "Artifact removal",
    "colorize": "Colorization",
    "descreen": "Screen-tone removal",
    "caption": "Captioning",
    "tag": "Tagging",
    "depth": "Control images",
    "pose": "Control images",
    "canny": "Control images",
    "lineart": "Control images",
    # TWO detection sections, not one. They were all "find a thing in the
    # picture and tell me where", which is true and is not how anybody shops
    # for a model: reading a page and finding the people in it are different
    # jobs, wanted at different times, and one section mixed six rows so that
    # neither could be scanned. Panels and the watermark detector go with TEXT
    # because that is what they are read alongside — a page's panels, its
    # speech, and the logo stamped over it are all things found on the page
    # itself, and the same Magi weights serve panels and OCR.
    "panels": "Text",
    "watermark_detect": "Text",
    "ocr": "Text",
    "faces": "Face detection",
    # The embedder's vectors feed the tag batch classifier — without an entry
    # here the one model of its kind fell into the frontend's anonymous
    # "Other" bucket, which is no answer to "what is this for".
    "embed": "Classification",
}


def category_for_source(key: str) -> str:
    """The Settings-page group label for a downloadable source, derived from the
    task of its owning plugin's models. A plugin's sources all share one type, so
    the first model's task drives the whole plugin (this is checkpoint-independent
    for Florence, whose non-active checkpoints aren't in ``models()``). "" if
    unknown."""
    if key in _SOURCE_CATEGORY_BY_KEY:
        return _SOURCE_CATEGORY_BY_KEY[key]
    for p in plugins():
        if any(s.key == key for s in p.manifest.sources):
            for m in p.models():
                return _SOURCE_CATEGORY.get(m.task, "")
    return ""


# Rough per-model GPU memory needed to *run* the model at inference (fp16 where
# applicable). These are ballpark estimates for the Settings badge, not hard
# limits — CPU-only (ONNX/NCNN) models still list a figure as a rough sizing
# guide. The badge says "2 GB VRAM": the tilde these carried made every chip
# read "~2 GB VRAM", which is a squiggle on every row to say what the tooltip
# already says. They are no more exact for having lost it.
#
# Keyed by downloadable-source key AND, for a plugin that has no source of its
# own (it fetches its own weights, or ships none), by PLUGIN key — that is what
# the model-cache row is keyed on, and those rows had no badge at all until
# they were listed here. Keep in sync when adding either.
#
# A plugin with NO MODEL is deliberately absent: `canny` and `descreen` are
# OpenCV/NumPy arithmetic over the picture, so their memory is a function of
# the image and there is no model to size. An empty answer is the honest one
# there, not a number chosen to fill the column.
_SOURCE_VRAM: dict[str, str] = {
    "withoutbg": "1 GB",
    "wm_yolo11x": "2 GB",
    "big_lama": "2 GB",
    # The other LaMa checkpoint, same architecture and calling convention.
    "anime_lama": "2 GB",
    "swin2sr_realworld_x4": "3 GB",
    "realesrgan_anime_x4": "2 GB",
    # The 23-block RRDBNet: nearly four times the anime net's work per
    # pixel, tiled like Swin2SR.
    "realesrgan_x2plus": "3 GB",
    "fbcnn_color": "2 GB",
    # Runs UNTILED (owner decision; see the plugin): the figure is PER
    # MEGAPIXEL of the picture, and the plugin refuses what the device
    # cannot hold.
    "scunet_real_gan": "5 GB",
    "color2manga": "2 GB",
    "manga_colorization_v2": "2 GB",
    "joycaption": "16 GB",
    "florence2_base": "2 GB",
    "florence2_large": "4 GB",
    "florence2_base_plain": "2 GB",
    "florence2_large_plain": "4 GB",
    "blip2": "8 GB",
    "qwen2_5_vl": "12 GB",
    "joytag": "2 GB",
    "wd_tagger": "2 GB",
    "ram_plus": "4 GB",
    "depth_anything_v2_small": "1 GB",
    "dpt_hybrid_midas": "2 GB",
    "zoedepth_nyu_kitti": "4 GB",
    "cn_annotators_leres": "2 GB",
    "yolo11n_pose": "1 GB",
    "cn_annotators_openpose": "2 GB",
    "cn_annotators_lineart": "1 GB",
    "magiv3": "4 GB",
    # A YOLOv8 detector, between `yolo11n_pose` (1 GB) and `wm_yolo11x` (2 GB)
    # in weight size and sized with the smaller.
    "anime_face": "1 GB",
    # 86M params, the size band `depth_anything_v2_small` sits in.
    "magi_crop_embedder": "1 GB",
    # Keyed by PLUGIN — these have no downloadable source of their own.
    "colorize_photo": "1 GB",       # a ~130 MB generator on the venv's torch
    "insightface_faces": "1 GB",    # buffalo_l on onnxruntime, no torch
    "rapid_ocr": "1 GB",            # PP-OCR on onnxruntime, no torch
    "descreen_opencomic": "1 GB",   # few-MB NCNN graphs
}


def vram_for_source(key: str) -> str:
    """A rough VRAM estimate (e.g. "4 GB") to run the model, or "" when there is
    nothing to size — shown as a badge in the Settings model list.

    Takes a source key or, for a plugin with no source of its own, a plugin key.
    """
    return _SOURCE_VRAM.get(key, "")

