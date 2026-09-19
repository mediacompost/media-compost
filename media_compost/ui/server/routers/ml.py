"""AI actions: enqueue/track background jobs (background removal, captioning,
tagging), list available models, and approve pending machine results."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

import io

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi import Form as FastForm
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from media_compost.db import (
    Item, ItemFaceRun, ItemGroup, Job,
)
from media_compost.ops import Ctx, captions as ops_captions, tagassign
from media_compost.hub.download import ERROR, RUNNING, Download as ModelDownload
from ...plugin_fetch import ChainedFetch, PluginFetch
from ...plugins import framework as fw
from ...jobs import JobQueue
from ...plugins import registry, tasks
from .. import viewscope
from ..deps import Library, get_ctx, get_current_user, get_library, get_session
from ..schemas import (
    EnqueueJobs, EnqueueScope, EnqueueView, JobItemOut, JobOut, JobProgressOut,
    JobsOut, MlRefOut, MlRefsOut,
    ModelCacheInfo, ModelCacheOut, ModelInfo, ModelsOut, TaskInfo,
)
from . import settings as settings_router

router = APIRouter(prefix="/api/ml", tags=["ml"])


def _snippet(text: str, limit: int = 60) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[: limit - 1] + "…"

# In-flight / recently-finished model downloads, keyed by family id. Each runs in
# its own subprocess (see media_compost.hub.download) so its CPU/IO can't stall
# the server. Guarded because request threads read/mutate the map.
_dl_lock = threading.Lock()
_downloads: dict[str, ModelDownload] = {}


# ---- runnable model setup ---------------------------------------------------
# One setup run per plugin at a time. Commands come from the plugin MANIFEST
# (never from the request); see media_compost/hub/setup.py for the run-then-re-exec
# machinery (shared with the training-env setup in routers/train.py).

from media_compost.hub.setup import SetupRun as _SetupRun  # noqa: E402

_setup_lock = threading.Lock()
_setups: dict[str, _SetupRun] = {}


@router.post("/setup/{plugin_key}")
def run_setup(plugin_key: str):
    """Set an action up completely: packages, environment AND weights.

    ONE command — `-m media_compost.ui.plugins.setup_action <key>` — so this
    button and a terminal do exactly the same thing, and the panel behind the
    button is a Run and a log rather than a list of steps to follow by hand.
    Named as a module rather than a file under `scripts/` because a wheel
    install has no checkout: the module resolves wherever the package is
    installed. What it does, and why the weights come last, is in its own
    docstring.

    The reserved key ``all`` runs every plugin that still needs setting up
    (its packages or dedicated env missing), one script after another in ONE
    run — and therefore one restart at the end, since the restart lives at
    the end of a run's command list.

    One setup at a time, whichever key: on success the server restarts
    itself (two concurrent runs meant the first restart killed the second
    mid-pip), and the client should poll /api/health, then reload.
    """
    keys: list[str]
    if plugin_key == "all":
        keys = [p.key for p in registry.plugins()
                if not fw.deps_ok(p.manifest)]
        if not keys:
            raise HTTPException(400, "nothing needs setting up")
    else:
        plugin = registry.plugin_by_key(plugin_key)
        if plugin is None:
            raise HTTPException(404, "unknown plugin")
        keys = [plugin_key]
    with _setup_lock:
        if any(r.running for r in _setups.values()):
            raise HTTPException(409, "setup already running")
        _setups[plugin_key] = _SetupRun(
            plugin_key,
            ["{python} -m media_compost.ui.plugins.setup_action " + k
             for k in keys],
            fw.repo_root())
    return {"ok": True, "count": len(keys)}


@router.get("/setup/{plugin_key}")
def setup_status(plugin_key: str):
    with _setup_lock:
        run = _setups.get(plugin_key)
    if run is None:
        return {"running": False, "ok": False, "error": "", "log": ""}
    return {"running": run.running, "ok": run.ok, "error": run.error,
            "log": run.log}


# Environment variables that force Hugging Face into offline mode. Captured once
# at import (server start), before any job mutates the process environment, so
# the Settings warning reflects the *launch* environment. Mutable: the
# clear-offline endpoint resets it after unsetting the vars.
_OFFLINE_ENV_VARS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE")


def _detect_env_offline() -> str:
    for name in _OFFLINE_ENV_VARS:
        v = os.environ.get(name)
        if v is not None and v.strip().lower() not in ("", "0", "false", "no", "off"):
            return f"{name}={v}"
    return ""


_env_offline = _detect_env_offline()


def env_offline() -> str:
    """The offline env var forcing Hugging Face offline mode, or "".

    Read through a function rather than importing `_env_offline`: the
    clear-offline endpoint rebinds it, and a module-level import elsewhere
    would keep the stale value.
    """
    return _env_offline


def _token_available() -> bool:
    return bool(settings_router.env_token())


def _iso_utc(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _models(kind: str) -> list[ModelInfo]:
    out: list[ModelInfo] = []
    for spec in registry.models_for(kind):
        plugin = registry.plugin_for(spec.id)
        man = plugin.manifest if plugin is not None else None
        keys = registry.source_keys_for_model(spec.id)
        # Unconditional: setup is one script and it always has something to do
        # (see `registry.setup_key_for_source`).
        setup_key = plugin.key if plugin is not None else ""
        out.append(ModelInfo(
            id=spec.id, name=spec.name, available=registry.available(spec.id),
            note=spec.note, url=man.url if man else "", family=spec.family, variant=spec.variant,
            family_key=keys[0] if keys else "", family_keys=keys,
            setup_key=setup_key, needs_reference=spec.needs_reference))
    return out


@router.get("/models", response_model=ModelsOut)
def list_models(s: Session = Depends(get_session)):
    """The AI actions and their models, with availability, for the UI."""
    # Reflect the selected Florence checkpoint (only the active one is listed).
    settings_router.apply_runtime_prefs(s)
    return ModelsOut(tasks=[
        TaskInfo(kind=t.kind, label=t.label, icon=t.icon, result=t.result,
                 sequence_option=t.sequence_option, models=_models(t.kind))
        for t in tasks.TASKS
    ], job_kinds=[
        # Not an AI action and not offered as one; here so the background-task
        # list can name a video render instead of printing its kind.
        TaskInfo(kind=t.kind, label=t.label, icon=t.icon, result=t.result,
                 sequence_option=False, models=[])
        for t in tasks.OTHER_JOB_KINDS
    ])


def _download_snapshot(key: str):
    """(downloading, progress, error, done_bytes, total_bytes, queued) for
    family ``key`` from its subprocess download, cleaning up finished
    (done/canceled) entries. Guard with _dl_lock."""
    d = _downloads.get(key)
    if d is None:
        return False, -1, "", 0, 0, False
    st = d.status()
    if st == RUNNING:
        # A PluginFetch has no queue of its own; only a hub download does.
        return True, d.progress, "", d.done_bytes, d.total_bytes, \
            bool(getattr(d, "queued", False))
    if st == ERROR:
        return False, -1, d.error, 0, 0, False   # keep the entry, keep the error
    _downloads.pop(key, None)                    # done/canceled -> forget
    return False, -1, "", 0, 0, False


@router.get("/model-cache", response_model=ModelCacheOut)
def model_cache(s: Session = Depends(get_session)):
    """Per-model download/cache status for the Settings overlay."""
    paths = settings_router.read_model_paths(s)
    sizes = fw.cache_sizes()
    models: list[ModelCacheInfo] = []
    for m in registry.all_sources():
        local_path = paths.get(m.key, "")
        with _dl_lock:
            downloading, progress, err, done_b, total_b, queued = \
                _download_snapshot(m.key)
        # While downloading, skip the on-disk cache probe (the cache dir is being
        # written); the card shows progress anyway.
        deps_ok = registry.source_deps_ok(m.key)
        # A source is not always the whole of a model's weights (RAM++ also
        # needs a tokenizer repo the `ram` package fetches itself), so the
        # plugin's own answer is ANDed in — for a local-path override too: the
        # path replaces the source, not the rest.
        cached = False if downloading else (
            fw.source_cached(m, local_path) and registry.source_weights_ready(m.key))
        # On-disk size of the downloaded weights (0 for a local-path override, or
        # when not fetched from the hub) — shown next to "Delete download".
        size = int(sizes.get(m.repo, 0)) if cached and not local_path else 0
        models.append(ModelCacheInfo(
            key=m.key, label=m.label, repo=m.repo, url=m.url, gated=m.gated,
            deps_ok=deps_ok, cached=cached, downloading=downloading,
            queued=queued, download_error=err, local_path=local_path,
            progress=progress if downloading else -1,
            done_bytes=done_b, total_bytes=total_b,
            setup_key=registry.setup_key_for_source(m.key),
            category=registry.category_for_source(m.key),
            vram=registry.vram_for_source(m.key),
            size=size,
        ))
    # Plugins with nothing to fetch but something to install (InsightFace pulls
    # its own pack; the OpenComic descreeners want ncnn). They have no source,
    # so the loop above never saw them — and the page that answers "what models
    # are there, and are they ready" left them out entirely.
    for plug in registry.setup_only_plugins():
        first = plug.models()[0]
        with _dl_lock:
            downloading, _p, err, _d, _t, _q = _download_snapshot(plug.key)
        deps_ok = fw.deps_ok(plug.manifest)
        # Weights that come from somewhere other than Hugging Face still have to
        # BE there: the plugin says so itself. Without that, a row whose packages
        # were installed read "Ready" while the pack it needs was still a
        # multi-minute download waiting to ambush the first detection run.
        ready = deps_ok and not downloading and registry.plugin_weights_ready(plug.key)
        models.append(ModelCacheInfo(
            key=plug.key, label=first.family or first.name, repo="",
            url=plug.manifest.url, gated=False,
            deps_ok=deps_ok, cached=ready,
            downloading=downloading, download_error=err, local_path="",
            progress=-1, done_bytes=0, total_bytes=0,
            fetchable=registry.plugin_can_fetch(plug.key),
            setup_key=plug.key,
            category=registry._SOURCE_CATEGORY.get(first.task, ""),
            # By PLUGIN key: these rows have no source, which is why they were
            # the ones showing no VRAM badge. "" still means "nothing to size"
            # (canny, descreen) rather than "nobody filled it in".
            vram=registry.vram_for_source(plug.key), size=0,
        ))
    return ModelCacheOut(
        models=models, token_available=_token_available(), env_offline=_env_offline,
    )


@router.post("/clear-offline")
def clear_offline():
    """Unset the Hugging Face offline env vars for the running process so
    downloads work without restarting, and clear the Settings warning."""
    global _env_offline
    for name in _OFFLINE_ENV_VARS:
        os.environ[name] = "0"
    # huggingface_hub caches HF_HUB_OFFLINE at import; patch the live constant too.
    try:
        import huggingface_hub.constants as _hc
        _hc.HF_HUB_OFFLINE = False
    except Exception:  # noqa: BLE001 - best effort
        pass
    _env_offline = ""
    return {"env_offline": ""}


@router.post("/model-cache/{key}/download")
def download_model(key: str):
    """Start (or report an in-progress) download of a model family's weights."""
    src = registry.source_for(key)
    if src is None:
        # Not a Hugging Face family — a plugin that fetches its own weights
        # (InsightFace's pack, the OpenComic graphs). Offline mode and tokens
        # are Hugging Face's concerns and do not apply to it.
        plug = registry.plugin_by_key(key)
        if plug is None or not registry.plugin_can_fetch(key):
            raise HTTPException(404, f"unknown model {key!r}")
        if not fw.deps_ok(plug.manifest):
            raise HTTPException(400, "install this model's packages first — "
                                     "its downloader is one of them")
        with _dl_lock:
            d = _downloads.get(key)
            if d is not None and d.status() == RUNNING:
                return {"ok": True, "status": "downloading"}
            _downloads[key] = d = PluginFetch(
                plug.module.__name__, fw.interpreter_for(plug.env))
        d.start()
        return {"ok": True, "status": "downloading"}
    # The launch environment forces Hugging Face offline — refuse until the user
    # clears it via /clear-offline ("Enable downloads"), so the offline setting
    # isn't silently bypassed (the download subprocess otherwise forces online).
    if _env_offline:
        raise HTTPException(400, "downloads are disabled — your environment forces "
                            "Hugging Face offline; enable downloads first")
    token = settings_router.env_token()
    if src.gated and not token:
        raise HTTPException(400, "this model is gated — set a Hugging Face token first")
    with _dl_lock:
        d = _downloads.get(key)
        if d is not None and d.status() == RUNNING:
            return {"ok": True, "status": "downloading"}
        d = ModelDownload(src.repo, token, src.allow_patterns)
        # …and then whatever the plugin fetches for itself, or a model whose
        # readiness counts both would sit on a Download button that can never
        # finish the job — the dead end `_has_incomplete_blobs` documents in a
        # different shape.
        plug = registry.plugin_for_source(key)
        if plug is not None and registry.plugin_can_fetch(plug.key):
            d = ChainedFetch(d, PluginFetch(plug.module.__name__,
                                            fw.interpreter_for(plug.env)))
        _downloads[key] = d
    d.start()
    return {"ok": True, "status": "downloading"}


@router.post("/model-cache/{key}/cancel-download")
def cancel_download(key: str):
    """Cancel an in-progress download by terminating its subprocess, then delete
    the partially-downloaded files so the model doesn't wrongly read as cached
    (the probe file downloads early). The UI reflects it immediately."""
    src = registry.source_for(key)
    # A self-fetching plugin (InsightFace's pack, the OpenComic graphs) is
    # keyed by its PLUGIN and has no source — `download_model` already knows
    # that shape, and answering 404 here left its fetch running behind a
    # Cancel button that said "ok".
    setup_only = any(p.key == key for p in registry.setup_only_plugins())
    if src is None and not setup_only:
        raise HTTPException(404, f"unknown model {key!r}")
    with _dl_lock:
        d = _downloads.pop(key, None)
    if d is not None:
        d.cancel()
    # Drop the incomplete cache (best effort — the cache may be empty).
    if src is not None:
        fw.delete_cached(src)
    return {"ok": True}


@router.post("/model-cache/{key}/delete-cache")
def delete_cache(key: str):
    """Delete a model family's downloaded weights from the Hugging Face cache."""
    src = registry.source_for(key)
    if src is None:
        raise HTTPException(404, f"unknown model {key!r}")
    with _dl_lock:
        d = _downloads.get(key)
        if d is not None and d.status() == RUNNING:
            raise HTTPException(400, "cannot delete while downloading")
        _downloads.pop(key, None)
    deleted = fw.delete_cached(src)
    return {"ok": True, "deleted": deleted}


@router.post("/inpaint")
async def inpaint(image: UploadFile, mask: UploadFile,
                  model: str = FastForm("big_lama")):
    """Inpaint the masked region of an image with LaMa (the editor's inpaint
    tool). ``mask`` marks the region to fill (its alpha, or luminance if opaque);
    only masked pixels change, and a partly-selected one changes partly.
    ``model`` picks the checkpoint: ``big_lama`` (photographic) or
    ``anime_lama`` (illustrations/line art). Returns a PNG. Synchronous + kept
    warm — this is an interactive editor operation, not a queued job."""
    from ... import inpaint as inpaint_mod
    from PIL import Image

    src = Image.open(io.BytesIO(await image.read()))
    mk = Image.open(io.BytesIO(await mask.read()))
    # Selection mask: prefer the alpha channel (the editor paints opaque white on
    # a transparent canvas), else luminance.
    m = mk.getchannel("A") if mk.mode in ("RGBA", "LA") else mk.convert("L")
    # IT IS NOT BINARISED. It used to be — `>= 128` — which threw away every
    # soft edge the editor can produce: a feathered selection (**Blur
    # selection**, whose whole purpose is to stop an inpaint ending in a
    # visible line) was cut off dead at its 50% contour, and an anti-aliased
    # ellipse or lasso got a stepped one. `run_lama` reads it as an alpha and
    # decides for itself what to tell the model.
    if m.size != src.size:
        m = m.resize(src.size, Image.BILINEAR)
    rgb = src.convert("RGB")
    if model not in inpaint_mod.LAMA_MODELS:
        raise HTTPException(400, f"unknown inpainting model {model!r}")
    try:
        lama = inpaint_mod.get_lama(local_files_only=True, key=model)
    except Exception as exc:  # noqa: BLE001 - deps or weights missing
        raise HTTPException(400, "inpainting needs torch and the model's weights — "
                            "download them in Settings → Models (Inpainting)") from exc
    result = inpaint_mod.run_lama(lama, rgb, m)
    # Inpainting doesn't change transparency — keep the source's alpha, if any.
    if src.mode in ("RGBA", "LA"):
        result = result.convert("RGBA")
        result.putalpha(src.convert("RGBA").getchannel("A"))
    buf = io.BytesIO()
    result.save(buf, "PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


# ---- interactive editor actions (synchronous, not queued jobs) ---------------
# The image editor works on an unsaved pixel buffer in its own window, so its
# AI actions can't go through the item job queue — they upload the buffer, run
# the model via the shared warm ModelHost, and return the result directly.

# Editor-appliable action kinds (image-in → image-out).
_APPLY_KINDS = {"upscale", "restore", "colorize", "descreen", "bg_removal"}


def _editor_ctx(s: Session) -> dict:
    return {"local_files_only": True,
            "model_paths": settings_router.read_model_paths(s), "token": ""}


async def _read_upload_image(image: UploadFile):
    from PIL import Image, UnidentifiedImageError

    data = await image.read()
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(400, "not a readable image") from exc
    return img


@router.post("/apply")
async def apply_model(image: UploadFile, kind: str = FastForm(...),
                      model: str = FastForm(""),
                      reference: str = FastForm(""),
                      s: Session = Depends(get_session),
                      lib: Library = Depends(get_library)):
    """Run an image-to-image model on an uploaded buffer (the editor's Image
    menu) and return the resulting PNG. A reference-guided model (example-based
    colorization) additionally takes the id of a refs-store image."""
    if kind not in _APPLY_KINDS:
        raise HTTPException(400, f"kind {kind!r} cannot be applied in the editor")
    model = registry.resolve_model(kind, model)
    spec = registry.spec_for(model)
    if spec is None or not registry.available(model):
        raise HTTPException(409, "model is not available — set it up first")
    options: dict = {}
    if spec.needs_reference:
        ref = _ref_path(lib, reference) if reference else None
        if ref is None or not ref.is_file():
            raise HTTPException(400, "this model needs a color reference image")
        options["reference"] = str(ref)
    img = await _read_upload_image(image)
    try:
        out = lib.model_host.run(kind, model, img, _editor_ctx(s), options)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)[:400]) from exc
    if out is None:
        raise HTTPException(422, "the model produced no result")
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.post("/detect-regions")
async def detect_regions(image: UploadFile, kind: str = FastForm(...),
                         s: Session = Depends(get_session),
                         lib: Library = Depends(get_library)):
    """Detect text or watermark regions on an uploaded buffer (the editor's
    "select text / watermark") — normalized polygons, no inpainting.

    TEXT is read by an OCR ENGINE, the same ones the Text tab uses, and its
    quads come back as the selection. It used to be EasyOCR's CRAFT detector,
    riding on the text-removal plugin — a second, invisible idea of where the
    text on a page is, which is exactly what removal stopped having. The
    reading here is NOT stored: the editor is working on a buffer that may
    never be saved, so there is no file for a region to belong to.
    """
    task_kind = {"text": "ocr", "watermark": "watermark_removal"}.get(kind)
    if task_kind is None:
        raise HTTPException(400, f"unknown detection kind {kind!r}")
    model = registry.default_model(task_kind)
    if not model or not registry.available(model):
        raise HTTPException(409, "the detector model is not available — set it up first")
    img = await _read_upload_image(image)
    try:
        out = lib.model_host.run(task_kind, model, img, _editor_ctx(s),
                                 {"detect_only": True})
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)[:400]) from exc
    if task_kind == "ocr":
        # An OCR result is a TREE of regions carrying `box` and (for slanted
        # text) `quad`; the selection wants the leaves' polygons, smallest
        # first, for `jobs._text_region_quads`' reason — a block box is a
        # whole bubble.
        return {"regions": _ocr_polygons(out or [])}
    regions = out.get("regions", []) if isinstance(out, dict) else []
    return {"regions": regions}


def _ocr_polygons(found) -> list:
    """An OCR payload's leaf regions as normalized polygons."""
    out: list = []

    def walk(rec) -> None:
        if not isinstance(rec, dict):
            return
        kids = [c for c in (rec.get("children") or []) if isinstance(c, dict)]
        if kids:
            for c in kids:
                walk(c)
            return
        quad = rec.get("quad")
        if quad and len(quad) >= 3:
            out.append([[float(p[0]), float(p[1])] for p in quad])
            return
        box = rec.get("box") or []
        if len(box) == 4:
            x, y, w, h = (float(v) for v in box)
            out.append([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])

    for rec in (found or []):
        walk(rec)
    return out


def _without_done(lib: Library, kind: str, model: str,
                  items: list[int]) -> list[int]:
    """``items`` minus the ones ``model`` has already been run over — for the
    kinds that record a per-item run (`ItemFaceRun` / `ItemTextRun`; a table
    per kind, so a run that found nothing is still remembered).

    Filtered HERE rather than in the browser: the client would have to fetch
    every item's detail to know, and a group can hold thousands — which is
    also why the IN is chunked (SQLite caps bind parameters).
    """
    from media_compost.db import Caption, Item, ItemTextRun, chunked

    if kind == "caption":
        # A CAPTION IS ITS OWN RUN MARKER. There is no per-item run table for
        # it and there does not need to be: this kind always produces a row,
        # and the row records which model wrote it — so "has this model
        # already described this picture" is one indexed read. A run that
        # produced nothing leaves nothing behind and will simply be tried
        # again, which for a description is the right answer (unlike a
        # detector, where "found nothing" is a finding worth remembering).
        #
        # By MODEL, not by "has any caption": several models describing one
        # picture differently is the ordinary case here, and a hand-written
        # caption must never stop a model from writing its own. An EDITED
        # generated caption keeps counting — `Caption.model` survives the
        # edit, and re-generating over somebody's correction is exactly what
        # this is for. The KIND is not read: `caption` writes captions and
        # nothing else, so an instruction on the item is a different
        # statement and no reason to skip.
        done_c: set[int] = set()
        with lib.db.session() as s:
            for chunk in chunked(items):
                done_c.update(s.execute(select(Caption.item_id).where(
                    Caption.item_id.in_(chunk),
                    Caption.model == model)).scalars().all())
        return [i for i in items if i not in done_c]

    if kind == "embed":
        # An embed always produces a row, so the row IS the run marker — and
        # like a text run it is per FILE: only a vector computed from the
        # item's ACTIVE file counts, so an edited picture re-indexes. Per
        # SPACE, since dinov2 and clip index independently.
        from ...itemvec import EMBEDDERS, SPACE as DEFAULT_SPACE, indexed_ids

        e_space = EMBEDDERS.get(model, (DEFAULT_SPACE, 0))[0]
        with lib.db.session() as s:
            done_e = indexed_ids(s, items, e_space)
        return [i for i in items if i not in done_e]

    run_table = {"faces": ItemFaceRun, "ocr": ItemTextRun}.get(kind)
    if run_table is None or not model:
        return items

    done: set[int] = set()
    with lib.db.session() as s:
        for chunk in chunked(items):
            stmt = select(run_table.item_id).where(
                run_table.item_id.in_(chunk),
                run_table.model == model)
            if kind == "ocr":
                # A text run is per FILE: only a run over the item's ACTIVE
                # file counts as done, so an edited file re-runs.
                stmt = stmt.join(Item, Item.id == run_table.item_id).where(
                    run_table.file_id == Item.active_file_id)
            done.update(s.execute(stmt).scalars().all())
    return [i for i in items if i not in done]


@router.post("/jobs")
def enqueue_jobs(body: EnqueueJobs, lib: Library = Depends(get_library),
                 user: str = Depends(get_current_user)):
    """Queue one job per item for the given action + model."""
    if body.kind not in tasks.task_kinds():
        raise HTTPException(400, f"unknown job kind {body.kind!r}")
    options: dict = {}
    if body.reference:
        ref = _ref_path(lib, body.reference)
        if ref is None:
            raise HTTPException(400, "unknown reference image")
        options["reference"] = ref.name
    if body.detect_with:
        # "Detect and remove": the OCR engine to read the page with first.
        # Refused rather than ignored if it is not an OCR model — a typo
        # would otherwise queue a removal that silently paints out nothing.
        if body.detect_with not in [m.id for m in registry.models_for("ocr")]:
            raise HTTPException(400, f"unknown OCR model {body.detect_with!r}")
        options["detect_with"] = body.detect_with
    items = body.item_ids
    if body.skip_done:
        items = _without_done(lib, body.kind, body.model, items)
        if not items:
            return {"job_ids": [], "skipped": len(body.item_ids)}
    ids = lib.jobs.enqueue(body.kind, body.model, items, body.into_sequence,
                           username=user, options=options or None)
    return {"job_ids": ids, "skipped": len(body.item_ids) - len(items)}


@router.post("/enqueue-scope")
def enqueue_scope(body: EnqueueScope, lib: Library = Depends(get_library),
                  user: str = Depends(get_current_user)):
    """Enqueue ``kind``/``model`` over every item in the given groups'
    SUBTREES, resolved server-side (`resolve.descendant_groups` + chunked
    membership selects) — the browser cannot cheaply know a big group's
    members. Trashed and hidden items are excluded, mirroring what the grid
    shows. ``skip_done`` has exactly `EnqueueJobs.skip_done`'s semantics
    (faces only). Returns ``{"queued": n, "skipped": n}`` — items handed to
    the queue, and items left out by ``skip_done``.
    """
    from sqlalchemy import exists, literal

    from media_compost.db import TrashedItem, chunked
    from media_compost.resolve import descendant_groups

    from media_compost.ops import search
    from media_compost.resolve import Resolver

    if body.kind not in tasks.task_kinds():
        raise HTTPException(400, f"unknown job kind {body.kind!r}")
    options: dict = {}
    if body.detect_with:
        # "Detect and remove": the OCR engine to read each page with first —
        # refused rather than ignored if it is not an OCR model, exactly as
        # the per-item enqueue refuses it.
        if body.detect_with not in [m.id for m in registry.models_for("ocr")]:
            raise HTTPException(400, f"unknown OCR model {body.detect_with!r}")
        options["detect_with"] = body.detect_with
    _VIEWS = {"all", "image", "video", "sequence", "untagged", "ungrouped",
              "pending", "hidden"}
    if body.view and body.view not in _VIEWS:
        raise HTTPException(400, f"unknown view {body.view!r}")
    group_ids = [int(g) for g in body.groups]
    if not group_ids and not body.view:
        return {"queued": 0, "skipped": 0}
    items: list[int] = []
    with lib.db.session() as s:
        trashed = exists(select(literal(1)).where(
            TrashedItem.item_id == Item.id))
        if body.view:
            # A FIXED sidebar entry's scope, resolved through the one search
            # there is — so the run covers exactly what the row shows.
            base = search.search_filtered(
                s, "", body.view == "ungrouped", False,
                kind=(body.view if body.view in ("image", "video", "sequence")
                      else ""),
                hidden=body.view == "hidden",
                show_hidden=body.view == "hidden",
                pending=body.view == "pending",
                untagged=body.view == "untagged",
                query=None,
                resolver=Resolver(s),
            )
            if base.residue is None:
                items = sorted(s.execute(base.ids_select()).scalars().all())
            else:
                items = sorted(base.matched_ids(s, Resolver(s)))
        else:
            wanted = descendant_groups(s, group_ids)
            seen: set[int] = set()
            for chunk in chunked(sorted(wanted)):
                for iid in s.execute(
                    select(Item.id).distinct()
                    .join(ItemGroup, ItemGroup.item_id == Item.id)
                    .where(ItemGroup.group_id.in_(chunk),
                           Item.hidden.is_(False), ~trashed)
                    .order_by(Item.id)
                ).scalars().all():
                    if iid not in seen:
                        seen.add(iid)
                        items.append(iid)
    total = len(items)
    if body.skip_done:
        items = _without_done(lib, body.kind, body.model, items)
    if items:
        lib.jobs.enqueue(body.kind, body.model, items, body.into_sequence,
                         username=user, options=options or None)
    return {"queued": len(items), "skipped": total - len(items)}


@router.post("/enqueue-view")
def enqueue_view(body: EnqueueView, s: Session = Depends(get_session),
                 lib: Library = Depends(get_library),
                 user: str = Depends(get_current_user)):
    """Enqueue ``kind``/``model`` over everything the VIEW is showing.

    `enqueue_scope` answers the narrower question — a group subtree, or one
    of the sidebar's fixed rows — and stays, because those scopes have no
    search body to send. This one takes the grid's own request, so "every
    action in the sidebar with nothing selected" covers exactly what is on
    screen and cannot drift from it.

    The ids never reach the browser: a view can be the whole library.
    """
    if body.task_kind not in tasks.task_kinds():
        raise HTTPException(400, f"unknown job kind {body.task_kind!r}")
    options: dict = {}
    if body.reference:
        ref = _ref_path(lib, body.reference)
        if ref is None:
            raise HTTPException(400, "unknown reference image")
        options["reference"] = ref.name
    if body.detect_with:
        if body.detect_with not in [m.id for m in registry.models_for("ocr")]:
            raise HTTPException(400, f"unknown OCR model {body.detect_with!r}")
        options["detect_with"] = body.detect_with
    items = viewscope.view_ids(s, lib, body)
    total = len(items)
    if body.skip_done:
        items = _without_done(lib, body.task_kind, body.model, items)
    if items:
        lib.jobs.enqueue(body.task_kind, body.model, items, body.into_sequence,
                         username=user, options=options or None)
    return {"queued": len(items), "skipped": total - len(items)}


# ---- color-reference images (a small rolling temp store) --------------------
# Reference-guided actions (example-based colorization) need a color image to
# copy from. Uploads / snapshots of items land in ``<data>/tmp/refs`` as
# normalized PNGs; only the newest few are kept. Not library data — never
# imported, no DB rows.

_REFS_KEEP = 12


def _ref_path(lib: Library, ref_id: str):
    """The refs-store path for ``ref_id`` (basename-only, so no traversal), or
    None when it doesn't exist."""
    name = os.path.basename(ref_id.strip())
    if not name or not name.endswith(".png"):
        return None
    p = lib.config.refs_dir / name
    return p if p.is_file() else None


def _store_ref(lib: Library, img) -> str:
    """Normalize ``img`` (PIL) to a capped-size PNG in the refs store, prune the
    store to the newest few, and return the new ref id."""
    import uuid

    img = img.convert("RGB")
    img.thumbnail((1024, 1024))
    d = lib.config.refs_dir
    d.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex[:12] + ".png"
    img.save(d / name, "PNG")
    entries = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime,
                     reverse=True)
    for old in entries[_REFS_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass
    return name


@router.get("/refs", response_model=MlRefsOut)
def list_refs(lib: Library = Depends(get_library)):
    """The stored reference images, newest first."""
    d = lib.config.refs_dir
    if not d.is_dir():
        return MlRefsOut(refs=[])
    entries = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime,
                     reverse=True)
    return MlRefsOut(refs=[MlRefOut(id=p.name) for p in entries[:_REFS_KEEP]])


@router.post("/refs", response_model=MlRefOut)
async def upload_ref(image: UploadFile, lib: Library = Depends(get_library)):
    """Store an uploaded image as a temporary color reference."""
    from PIL import Image, UnidentifiedImageError

    data = await image.read()
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(400, "not a readable image") from exc
    return MlRefOut(id=_store_ref(lib, img))


@router.post("/refs/from-item/{item_id}", response_model=MlRefOut)
def ref_from_item(item_id: int, s: Session = Depends(get_session),
                  lib: Library = Depends(get_library)):
    """Snapshot an item's active image into the reference store, so it can be
    picked as the color reference when colorizing other items."""
    from PIL import Image

    item = s.get(Item, item_id)
    if item is None or item.active_file_id is None:
        raise HTTPException(404, "item has no active image")
    from media_compost.db import File

    f = s.get(File, item.active_file_id)
    if f is None or not f.path:
        raise HTTPException(404, "item has no stored image")
    path = lib.store.path_of(s, f)
    if not path.exists():
        raise HTTPException(404, "image file missing")
    with Image.open(path) as img:
        img.load()
        return MlRefOut(id=_store_ref(lib, img))


@router.get("/refs/{ref_id}")
def get_ref(ref_id: str, lib: Library = Depends(get_library)):
    """Serve a stored reference image (for the picker's thumbnails)."""
    p = _ref_path(lib, ref_id)
    if p is None:
        raise HTTPException(404, "reference not found")
    return Response(content=p.read_bytes(), media_type="image/png")


@router.delete("/refs/{ref_id}")
def delete_ref(ref_id: str, lib: Library = Depends(get_library)):
    """Remove a stored reference image from the rolling store."""
    p = _ref_path(lib, ref_id)
    if p is None:
        raise HTTPException(404, "reference not found")
    try:
        p.unlink()
    except OSError as exc:
        raise HTTPException(500, "could not delete reference") from exc
    return {"ok": True}


@router.get("/jobs", response_model=JobsOut)
def list_jobs(s: Session = Depends(get_session)):
    """Active (queued/running) jobs first, then the most recent finished ones.

    Cleanly-successful jobs are omitted — a plain "done" is auto-cleared from the
    list; only active, failed, warning (empty output) and canceled jobs remain."""
    rows = s.execute(
        select(Job, Item.name)
        .join(Item, Item.id == Job.item_id, isouter=True)
        .where(Job.status != "done")
        .order_by(Job.id.desc())
        .limit(60)
    ).all()
    # Sort so still-active jobs float to the top of the list. A PAUSED job is
    # among them — it is waiting for an answer, not finished.
    order = {"running": 0, "queued": 1, "paused": 2,
             "failed": 3, "warning": 4, "canceled": 5}
    rows.sort(key=lambda r: (order.get(r[0].status, 9), -r[0].id))
    def _item_count(j: Job) -> int:
        if not j.item_ids:
            return 1
        try:
            return len(json.loads(j.item_ids)) or 1
        except ValueError:
            return 1
    jobs = [
        JobOut(
            id=j.id, kind=j.kind, model=j.model, item_id=j.item_id,
            item_name=name or "", item_count=_item_count(j),
            status=j.status, message=j.message or "",
            progress=j.progress or 0, done_count=j.done_count or 0,
            pausable=_pausable(j), created_at=_iso_utc(j.created_at),
        )
        for j, name in rows
    ]
    return JobsOut(jobs=jobs)


def _pausable(j: Job) -> bool:
    """Can this job be held? A queued one always (it simply stops being
    next); a running one only where it has a boundary between items to stop
    at, which is what a multi-item job is."""
    if j.status == "queued":
        return True
    if j.status != "running":
        return False
    return bool(j.item_ids or j.kind in JobQueue._BATCH_ONLY_KINDS)


@router.post("/jobs/{job_id}/pause")
def pause_job(job_id: int, lib: Library = Depends(get_library)):
    """Hold a job where it is. A running batch stops at its next chunk, with
    everything it has already done kept."""
    if not lib.jobs.pause(job_id):
        raise HTTPException(400, "job cannot be paused")
    return {"ok": True}


@router.post("/jobs/{job_id}/resume")
def resume_job(job_id: int, lib: Library = Depends(get_library)):
    """Put a paused job back in the queue, at the place its id gives it."""
    if not lib.jobs.resume(job_id):
        raise HTTPException(400, "job is not paused")
    return {"ok": True}


@router.get("/jobs/{job_id}/progress", response_model=JobProgressOut)
def job_progress(job_id: int, offset: int = 0, limit: int = 200,
                 lib: Library = Depends(get_library),
                 s: Session = Depends(get_session)):
    """A window of a job's items, each with what has happened to it.

    Per-item state is DERIVED from the one cursor the job keeps rather than
    stored per item: a batch runs its list from the front, so everything
    before `done_count` is finished and the chunk at it is what is being
    worked on now. That is what makes this list free — no second table, and
    nothing to keep in step with the run.

    Windowed because a batch can cover a whole library and the overlay only
    ever draws a screenful.
    """
    job = s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    try:
        ids = [int(x) for x in json.loads(job.item_ids or "[]")]
    except ValueError:
        ids = []
    # `or []` for the job that is about no picture: an estimate walks a
    # scope it never holds the ids of, so there is nothing to list.
    ids = ids or ([job.item_id] if job.item_id is not None else [])
    done = max(0, min(int(job.done_count or 0), len(ids)))
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    window = ids[offset:offset + limit]
    names = dict(s.execute(
        select(Item.id, Item.name).where(Item.id.in_(window))
    ).all()) if window else {}
    running = job.status == "running"
    out = []
    for k, iid in enumerate(window, start=offset):
        if k < done:
            state = "done"
        elif running and k < done + lib.jobs._batch_for(job.kind):
            state = "running"
        else:
            state = "pending"
        out.append(JobItemOut(id=iid, name=names.get(iid) or "", status=state))
    return JobProgressOut(total=len(ids), done=done, status=job.status,
                          offset=offset, items=out)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, lib: Library = Depends(get_library)):
    ok = lib.jobs.cancel(job_id)
    if not ok:
        raise HTTPException(404, "job not found or already finished")
    return {"ok": True}


@router.post("/jobs/cancel-all")
def cancel_all_jobs(lib: Library = Depends(get_library)):
    """Cancel every queued and running AI job in one call."""
    return {"ok": True, "count": lib.jobs.cancel_all()}


@router.post("/jobs/clear-finished")
def clear_finished(s: Session = Depends(get_session)):
    """Remove finished jobs from the list (keeps active ones)."""
    s.execute(delete(Job).where(
        Job.status.in_(["done", "failed", "canceled", "warning"])
    ))
    return {"ok": True}


@router.get("/jobs/{job_id}/items")
def job_items(job_id: int, s: Session = Depends(get_session)):
    """The item ids a job covers — the recorded batch list when there is one,
    else the single item. On demand rather than on ``JobOut``: a batch job
    can hold thousands of ids and the list view never needs them. This is
    what lets a failed job's row select its items in the library."""
    job = s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    try:
        ids = [int(x) for x in json.loads(job.item_ids or "[]")]
    except ValueError:
        ids = []
    return {"item_ids": ids or (
        [job.item_id] if job.item_id is not None else [])}


@router.get("/jobs/{job_id}/log")
def job_log(job_id: int, s: Session = Depends(get_session)):
    """The full captured output (stdout/stderr + logging) of a task's run."""
    job = s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return {"log": job.log or "", "message": job.message or "", "status": job.status}


@router.post("/jobs/{job_id}/clear")
def clear_job(job_id: int, s: Session = Depends(get_session)):
    """Remove one finished (done/failed/canceled) job from the list."""
    job = s.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    if job.status in ("queued", "running"):
        raise HTTPException(400, "cannot clear an active job — cancel it first")
    s.delete(job)
    return {"ok": True}


# ---- approving pending results -------------------------------------------

@router.post("/captions/{caption_id}/approve")
def approve_caption(caption_id: int, ctx: Ctx = Depends(get_ctx)):
    ops_captions.approve(ctx, caption_id)
    return {"ok": True}


@router.post("/placements/{placement_id}/approve")
def approve_placement(placement_id: int, ctx: Ctx = Depends(get_ctx)):
    """Accept a pending tag: clear its pending flag and move it out of the
    auto-managed Pending group into the ungrouped default."""
    tagassign.approve_placement(ctx, placement_id)
    return {"ok": True}
