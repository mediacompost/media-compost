"""Watermark removal: detect with YOLO11x, inpaint with LaMa.

Pipeline: a purpose-trained YOLO11x detector (corzent/yolo11x_watermark_detection,
via ultralytics) finds watermark/logo boxes; they become a dilated binary mask;
LaMa (JosephCatrambone/big-lama-torchscript, loaded with torch.jit.load) inpaints
the masked region. Large images are inpainted at a bounded size and composited
back at full resolution, so untouched areas stay pixel-perfect.
"""

from __future__ import annotations

import os

# Disable ALL ultralytics network activity before it is ever imported (its import
# runs an `is_online()` DNS probe and it POSTs anonymized usage events to Google
# Analytics on predict). `YOLO_OFFLINE=true` makes `is_online()` return without
# connecting, which also gates the analytics off (they require ONLINE). Set at
# module import — the worker imports this file before calling load(), which is
# where ultralytics is first imported. Nothing here needs the network: model
# weights are fetched separately via huggingface_hub.
os.environ.setdefault("YOLO_OFFLINE", "true")

# Detection confidence, mask dilation (px) and the max long-edge fed to LaMa.
_CONF = 0.25
_DILATE = 15
_LAMA_MAX_SIDE = 2048

_YOLO_FILE = "best.pt"
_LAMA_FILE = "lama.pt"

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(
                id="yolo11x_lama", task="watermark_removal",
                name="Watermark removal (YOLO11x + LaMa)", family="Watermark removal",
                note="Detect watermarks (YOLO11x) and inpaint them (LaMa)."),
            # Detection only: the found regions land as boxes on the
            # configured watermark tag (Settings → Tagging) — what the
            # box-driven removal below consumes. Needs no LaMa download.
            ModelSpec(
                id="yolo11x_detect", task="watermark_detect",
                name="Watermark detection (YOLO11x)",
                family="Watermark detection",
                note="Find watermarks and record them as tag boxes."),
            # Only shown by the UI when the item has the configured watermark
            # tag with boxes.
            ModelSpec(
                id="yolo11x_lama:boxes", task="watermark_removal",
                name="Use tagged boxes (skip detection)", family="Watermark removal",
                variant="Use tagged boxes",
                note="Inpaint the boxes on the tag configured for watermarks "
                     "(Settings → Tagging), with no detector."),
        ],
        sources=[
            ModelSource(key="wm_yolo11x", label="YOLO11x watermark detector",
                        repo="corzent/yolo11x_watermark_detection",
                        url="https://huggingface.co/corzent/yolo11x_watermark_detection",
                        probe=_YOLO_FILE,
                        # …not the example jpegs beside it.
                        allow_patterns=(_YOLO_FILE,)),
            # Declared identically in text_removal.py — same key, so the
            # registry keeps whichever plugin loads first and drops the other.
            # The two must therefore AGREE, patterns included, or which files
            # get fetched depends on registry order.
            ModelSource(key="big_lama", label="big-lama (inpainting)",
                        repo="JosephCatrambone/big-lama-torchscript",
                        url="https://huggingface.co/JosephCatrambone/big-lama-torchscript",
                        probe=_LAMA_FILE, allow_patterns=(_LAMA_FILE,)),
        ],
        deps=("ultralytics",),
        url="https://huggingface.co/corzent/yolo11x_watermark_detection",
        # (source_for_model is a function below — the boxes variant needs only LaMa.)
    )
except (ImportError, ValueError):
    MANIFEST = None


def load_key(model_id):
    # The boxes variant loads only LaMa (no detector), the detect variant only
    # YOLO (no inpainter) — separate warm workers, and neither demands the
    # other's download.
    if model_id.endswith(":boxes"):
        return "lama_boxes"
    if model_id == "yolo11x_detect":
        return "yolo11x_only"
    return "yolo11x_lama"


def source_for_model(model_id):
    # The action menu stays "needs download" until every required source is cached.
    if model_id.endswith(":boxes"):
        return ["big_lama"]
    if model_id == "yolo11x_detect":
        return ["wm_yolo11x"]
    return ["wm_yolo11x", "big_lama"]


def _weight(ctx, key, filename):  # pragma: no cover - heavy optional dep
    p = ctx["sources"][key]
    if p and os.path.isfile(p):
        return p
    if p and os.path.isdir(p):
        cand = os.path.join(p, filename)
        if os.path.isfile(cand):
            return cand
        raise RuntimeError(f"{filename} not found in {p}")
    from huggingface_hub import hf_hub_download
    return hf_hub_download(p, filename,
                           local_files_only=bool(ctx.get("local_files_only", True)),
                           token=ctx.get("token") or None)


def _load_yolo(ctx):  # pragma: no cover - heavy optional dep
    from ultralytics import YOLO

    # Belt-and-suspenders: also switch off the analytics event singleton directly
    # (in case a future ultralytics changes how the env var gates it).
    try:
        from ultralytics.utils.events import events as _ul_events
        _ul_events.enabled = False
    except Exception:  # noqa: BLE001
        pass
    return YOLO(_weight(ctx, "wm_yolo11x", _YOLO_FILE))


def _device():  # pragma: no cover - heavy optional dep
    """Where the detector predicts. Ultralytics picks CUDA by itself and
    NOTHING else: on a Mac `predict` ran YOLO11x on the cores, 420 ms a
    picture, with MPS idle. `MEDIA_COMPOST_WATERMARK_DEVICE` pins one."""
    import torch

    forced = (os.environ.get("MEDIA_COMPOST_WATERMARK_DEVICE") or "").strip()
    if forced:
        return forced
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None \
            and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def prepare(handle, image):  # pragma: no cover - heavy optional dep
    """The worker's per-picture hook, beside the decode: the RGB picture the
    detector reads (a full-size `convert` on the worker's one thread
    otherwise)."""
    return image.convert("RGB")


def wants_decode_processes(handle):  # pragma: no cover - heavy optional dep
    return False   # threads: the result is a picture, and Pillow's convert releases the GIL


def _detect(yolo, rgb, dev):  # pragma: no cover - heavy optional dep
    """xyxy pixel boxes of ONE picture. One predict per picture on purpose:
    a list of pictures of different sizes is letterboxed to the batch's
    largest, which moved the boxes on 10 of 32 pictures and took three
    times as long (measured, 5090 box)."""
    out = []
    for r in yolo.predict(rgb, conf=_CONF, verbose=False, device=dev):
        b = getattr(r, "boxes", None)
        if b is not None and b.xyxy is not None:
            out.extend(tuple(float(v) for v in row) for row in b.xyxy.tolist())
    return out


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from media_compost.ui.inpaint import load_lama

    dev = _device()
    if load_key == "yolo11x_only":
        yolo = _load_yolo(ctx)
        print(f"watermark: detector on {dev}", flush=True)
        return (yolo, None, dev)  # detect mode: no inpainter needed
    try:
        lama = load_lama(_weight(ctx, "big_lama", _LAMA_FILE))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "the LaMa inpainting model isn't available — download 'big-lama "
            "(inpainting)' in Settings → Models"
        ) from exc
    if load_key == "lama_boxes":
        return (None, lama, dev)  # boxes mode: no detector needed
    print(f"watermark: detector on {dev}", flush=True)
    return (_load_yolo(ctx), lama, dev)


def _mask_from_boxes(size, boxes, dilate):  # pragma: no cover - heavy optional dep
    """A binary L mask (255 in watermark regions) from xyxy boxes, dilated."""
    import numpy as np
    from PIL import Image

    w, h = size
    mask = np.zeros((h, w), dtype=np.uint8)
    for x0, y0, x1, y1 in boxes:
        xi0, yi0 = max(0, int(x0)), max(0, int(y0))
        xi1, yi1 = min(w, int(round(x1))), min(h, int(round(y1)))
        if xi1 > xi0 and yi1 > yi0:
            mask[yi0:yi1, xi0:xi1] = 255
    if dilate > 0:
        try:
            import cv2
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate * 2 + 1,) * 2)
            mask = cv2.dilate(mask, k)
        except Exception:  # noqa: BLE001 - cv2 optional; PIL fallback
            from PIL import ImageFilter
            mask = np.asarray(
                Image.fromarray(mask).filter(ImageFilter.MaxFilter(dilate * 2 + 1)))
    return Image.fromarray(mask, "L")


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    from media_compost.ui.inpaint import run_lama

    # The detect task is the detect_only path with no inpainter loaded.
    if task == "watermark_detect":
        options = {**(options or {}), "detect_only": True}
    yolo, lama, dev = handle
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    w, h = rgb.size
    if model_id.endswith(":boxes"):
        # Use the item's tagged boxes (fractions x,y,w,h) as the mask — no detector.
        frac = options.get("boxes") or []
        boxes = [(x * w, y * h, (x + bw) * w, (y + bh) * h) for x, y, bw, bh in frac]
        if not boxes:
            return {"image": None}  # no watermark-tag boxes on the item
    else:
        boxes = _detect(yolo, rgb, dev)
        if not boxes:
            if (options or {}).get("detect_only"):
                return {"regions": []}
            return {"image": None}  # nothing detected
    if (options or {}).get("detect_only"):
        # Detection only (the editor's "select watermark"): the found boxes as
        # normalized polygons, no inpainting.
        return {"regions": [[[x0 / w, y0 / h], [x1 / w, y0 / h],
                             [x1 / w, y1 / h], [x0 / w, y1 / h]]
                            for x0, y0, x1, y1 in boxes]}
    mask = _mask_from_boxes(rgb.size, boxes, _DILATE)
    return {"image": run_lama(lama, rgb, mask, max_side=_LAMA_MAX_SIDE)}
