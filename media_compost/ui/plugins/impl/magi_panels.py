"""The Magi v3 plugin: comic/manga panel detection AND text reading (OCR).

The Magi model (ragavsachdeva/magiv3, https://github.com/ragavsachdeva/magi)
serves two tasks off ONE set of weights and one resident worker (both specs
share ``load_key`` — a ~4 GB generative model held warm twice would be a
worker per task for no reason):

* ``panels`` — the panel boxes (as ``[x, y, w, h]`` fractions of the page);
  the job runner crops each into its own item (``jobs._apply_panels``).
* ``ocr`` — ``predict_ocr``'s text blocks, ``[{"box", "text", "level"}, …]``
  in reading order; the job runner reconciles them into ``text_regions``
  (``jobs._apply_ocr``). Magi is generative, so a block carries no score and
  no sub-structure — the schema holds that without placeholders.

  **ENGLISH ONLY, and that is the model, not the wiring** — measured, because
  it looks exactly like a broken integration: on an English test image the
  generation reads every line with correct boxes, while on a Japanese manga
  page — and on the easiest possible Japanese, huge clean horizontal
  Hiragino — it answers with an immediate EOS (``'</s><s><s><s></s>'``),
  greedy and beamed alike, so the run honestly reports "no text detected".
  Its DETECTION pass has the same boundary (finds the page's panels, zero of
  its text boxes). Japanese and every other non-Latin script are RapidOCR's
  job, which reads the same page at ≥0.95 confidence per line.

Magi v3 is built on Florence-2, whose bundled ("trust_remote_code") model code is
incompatible with the app's transformers version (same reason Florence-2 runs in
its own env). So Magi runs out-of-process in a dedicated ``magi`` environment with
a pinned transformers plus Magi's own deps (built by
``python -m media_compost.hub.setup_env magi``).
Only the load/run functions execute there; the manifest runs in the main process.
"""

from __future__ import annotations

import os

try:
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id="magiv3_panels", task="panels", name="Magi v3",
                      family="Panel detection",
                      note="Detect comic/manga panels (Magi v3)."),
            # Named for the JOB it does, not the paper it comes from: what
            # decides whether to reach for this one is that the page is a
            # comic in English. The note says what it is FOR and stops —
            # what it cannot read is the other engines' business, and a menu
            # row that spends its line on a caveat says nothing about when
            # to pick it.
            ModelSpec(id="magiv3_ocr", task="ocr", name="Manga (English)",
                      family="Text detection",
                      note="Comic-aware: reads a page bubble by bubble."),
        ],
        sources=[
            ModelSource(key="magiv3", label="Magi v3 (panels + text)",
                        repo="ragavsachdeva/magiv3",
                        url="https://huggingface.co/ragavsachdeva/magiv3",
                        probe="model.safetensors",
                        # `trust_remote_code`: the architecture is the
                        # repo's own .py files, which TRANSFORMERS_CONFIG_FILES
                        # covers.
                        allow_patterns=TRANSFORMERS_CONFIG_FILES
                        + ("model.safetensors",)),
        ],
        deps=(),                # readiness = the dedicated env resolves
        env="magi",
        url="https://github.com/ragavsachdeva/magi",
        source_for_model={"magiv3_panels": "magiv3", "magiv3_ocr": "magiv3"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load_key(model_id):
    # Both tasks run the SAME weights: one resident worker serves panels and
    # OCR, instead of two copies of a ~4 GB model evicting each other.
    return "magiv3"


def _patch_compat() -> None:  # pragma: no cover - heavy optional dep
    """Best-effort shims so Magi's Florence-2 code loads on newer transformers."""
    try:
        from transformers import PretrainedConfig
        for attr in ("forced_bos_token_id", "forced_eos_token_id"):
            if not hasattr(PretrainedConfig, attr):
                setattr(PretrainedConfig, attr, None)
    except Exception:
        pass
    try:
        from transformers.tokenization_utils_base import PreTrainedTokenizerBase
        if not hasattr(PreTrainedTokenizerBase, "additional_special_tokens"):
            def _ast(self):
                m = getattr(self, "_special_tokens_map", None) or {}
                v = m.get("additional_special_tokens")
                return list(v) if v else []
            PreTrainedTokenizerBase.additional_special_tokens = property(_ast)
    except Exception:
        pass


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch
    from transformers import AutoModel, AutoProcessor

    _patch_compat()
    if ctx.get("local_files_only", True):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    repo = ctx["sources"]["magiv3"]
    local_only = bool(ctx.get("local_files_only", True))
    token = ctx.get("token") or None
    try:
        model = AutoModel.from_pretrained(
            repo, trust_remote_code=True, attn_implementation="eager",
            local_files_only=local_only, token=token)
    except (TypeError, ValueError):
        model = AutoModel.from_pretrained(
            repo, trust_remote_code=True, local_files_only=local_only, token=token)
    model = model.eval()
    # cuda, mps or the CPU (a dedicated env: the rule is copied here, as
    # `florence` and `anime_face_magi` do, since `_accel` is out of reach).
    # It was CUDA or the CPU — an M4 Max split panels at 8 s a page on its
    # cores with MPS idle. fp16 on a card, the checkpoint's own; float32 on
    # MPS and the CPU. `MEDIA_COMPOST_PANELS_DEVICE` pins one by hand.
    dev = (os.environ.get("MEDIA_COMPOST_PANELS_DEVICE") or "").strip() or (
        "cuda" if torch.cuda.is_available()
        else "mps" if getattr(torch.backends, "mps", None) is not None
        and torch.backends.mps.is_available() else "cpu")
    if dev == "cuda":
        model = model.cuda()
    else:
        model = model.to(torch.float32).to(dev)
    print(f"panels: Magi v3 on {dev}", flush=True)
    proc = AutoProcessor.from_pretrained(
        repo, trust_remote_code=True, local_files_only=local_only, token=token)
    return (model, proc)


def _panel_boxes(handle, image):  # pragma: no cover - heavy optional dep
    """Return panel boxes as pixel [x1, y1, x2, y2] for one page.

    Magi v3's ``predict_detections_and_associations(images, processor)`` returns,
    per image, a dict whose ``panels`` are ``[x1, y1, x2, y2]`` in image pixels."""
    import numpy as np
    import torch

    model, proc = handle
    arr = np.asarray(image.convert("RGB"))
    with torch.no_grad():
        results = model.predict_detections_and_associations([arr], proc)
    per = results[0] if results else {}
    panels = (per or {}).get("panels") or []
    return [list(map(float, b)) for b in panels]


def _ocr_blocks(handle, image):  # pragma: no cover - heavy optional dep
    """Magi v3's text blocks for one page, as (text, [x1, y1, x2, y2]) pixel
    pairs in the model's own reading order.

    ``predict_ocr(images, processor)`` returns, per image,
    ``{"ocr_texts": [...], "bboxes": [[x1, y1, x2, y2], ...]}`` — parallel by
    index but NOT guaranteed the same length (the texts are sliced out of the
    generated string, and a generation ending mid-grounding leaves them
    uneven), so ``zip`` and drop the tail; never index one by the other's
    length. Each slice runs from the end of the previous bubble, so the
    strings carry stray whitespace and need ``.strip()``.
    """
    import numpy as np
    import torch

    model, proc = handle
    arr = np.asarray(image.convert("RGB"))
    with torch.no_grad():
        results = model.predict_ocr([arr], proc)
    per = results[0] if results else {}
    texts = (per or {}).get("ocr_texts") or []
    boxes = (per or {}).get("bboxes") or []
    return [(str(t).strip(), list(map(float, b)))
            for t, b in zip(texts, boxes)]


def _fraction_box(x1, y1, x2, y2, w, h):
    """[x1, y1, x2, y2] pixels -> [x, y, w, h] fractions, clamped."""
    fx = max(0.0, min(1.0, x1 / w))
    fy = max(0.0, min(1.0, y1 / h))
    fw = max(0.0, min(1.0 - fx, (x2 - x1) / w))
    fh = max(0.0, min(1.0 - fy, (y2 - y1) / h))
    return [fx, fy, fw, fh]


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    # Both tasks return a BARE LIST — the worker marshals a plain value into
    # {"value": …}, which the host unwraps. Never a dict: `_marshal` would
    # read a top-level "text" key as a caption string.
    rgb = image.convert("RGB")
    w, h = rgb.size
    if w == 0 or h == 0:
        return []
    if task == "ocr":
        out = []
        for text, (x1, y1, x2, y2) in _ocr_blocks(handle, rgb):
            box = _fraction_box(x1, y1, x2, y2, w, h)
            if not text or box[2] <= 0.001 or box[3] <= 0.001:
                continue
            # List position is the reading order; Magi is generative, so no
            # score, no quad and no children — the schema holds that.
            out.append({"level": "block",
                        "box": [round(v, 6) for v in box],
                        "text": text})
        return out
    boxes = _panel_boxes(handle, rgb)
    if not boxes:
        return []
    out = []
    for x1, y1, x2, y2 in boxes:
        box = _fraction_box(x1, y1, x2, y2, w, h)
        if box[2] > 0.01 and box[3] > 0.01:
            out.append(box)
    return out
