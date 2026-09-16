"""Text removal: inpaint the text THIS LIBRARY HAS ALREADY READ, with LaMa.

**It detects nothing itself, deliberately.** It used to: EasyOCR's CRAFT
detector found the boxes and LaMa painted them out, which meant the app had
two unrelated ideas of where the text on a page is — the one in the Text tab,
correctable by hand and reconciled across runs, and this one, invisible,
unreviewable and thrown away after every job. The regions now come from
:class:`~media_compost.db.TextRegion`, so what is painted over is exactly what
you can see, correct and dismiss beforehand; ``jobs.run_one`` gathers them
(and runs an OCR engine first when the job asks for one), and hands them here
as ``options["quads"]`` — normalized polygons in the active file's frame.

**The SMALLEST level available is what arrives.** A char box hugs a glyph, a
word box a word, a block box a whole speech bubble — and inpainting a bubble
repaints the art inside it. The choosing is the caller's
(``jobs._text_region_quads``), because only it can see the tree.

LaMa is the same big-lama checkpoint the watermark plugin and the editor's
inpaint tool use, so this plugin has no weights of its own; the two sources
below are declared here only so the Settings page offers them (the registry
de-duplicates by key).
"""

from __future__ import annotations

import os

_DILATE = 6              # px of mask dilation around the regions
_LAMA_MAX_SIDE = 2048    # max long-edge fed to LaMa (composited back full-res)

_LAMA_FILE = "lama.pt"

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(
                id="lama_regions", task="text_removal",
                name="Remove the text found in the picture",
                family="Text removal",
                note="Paint out the text regions this item already has "
                     "(the Text tab), smallest boxes first."),
            # The watermark plugin's boxes variant, one subject along: paint
            # out the boxes on the tag Settings → Tagging names for text —
            # which is the tag an OCR run writes its regions onto when that
            # setting is filled in, so the two halves of "detect, then
            # remove" meet on a tag exactly as the watermark pair do.
            #
            # NOT a duplicate of the reading above: the regions are ONE
            # engine's answer and are edited in the Text tab, while the tag's
            # boxes are ordinary tag boxes — drawn by hand in the annotator,
            # moved, added to, and searchable. Which of the two you mean is a
            # real choice, and it is the one thing the model list can say.
            ModelSpec(
                id="lama_regions:boxes", task="text_removal",
                name="Use tagged boxes (skip the reading)",
                family="Text removal", variant="Use tagged boxes",
                note="Inpaint the boxes on the tag configured for text "
                     "(Settings → Tagging), ignoring the Text tab."),
        ],
        sources=[
            # Same key/repo as the watermark plugin's LaMa source — the registry
            # de-duplicates by key, so it appears once in Settings and a single
            # download serves both plugins.
            ModelSource(key="big_lama", label="big-lama (inpainting)",
                        repo="JosephCatrambone/big-lama-torchscript",
                        url="https://huggingface.co/JosephCatrambone/big-lama-torchscript",
                        probe=_LAMA_FILE, allow_patterns=(_LAMA_FILE,)),
            # Anime/manga LaMa fine-tune (dreMaz, traced to TorchScript) — the
            # editor's illustration-grade inpaint variant. Not used by the
            # removal jobs; it only rides on this plugin for Settings download.
            ModelSource(key="anime_lama", label="Anime LaMa (illustration inpainting)",
                        repo="s9roll74/tracing_dreMaz_AnimeMangaInpainting",
                        url="https://huggingface.co/dreMaz/AnimeMangaInpainting",
                        probe="model.jit.pt",
                        allow_patterns=("model.jit.pt",)),
        ],
        # TORCH, and torch alone — the detector package is gone, but LaMa is
        # a TorchScript checkpoint and `load()` starts with `import torch`.
        # Declared rather than assumed: without it a machine with no torch
        # showed a ready-looking action that died inside the model host with
        # "No module named 'torch'", where the whole point of `deps` is that
        # the menu says "Set up" instead. `framework.setup_commands` turns
        # this one dep into `setup_env.py torch`, which is what picks the
        # right wheel — PyPI's Windows build is CPU-only and Linux's is CUDA
        # rather than ROCm, so a plain `pip install torch` is how a GPU box
        # ends up inpainting on its CPU with nothing saying why.
        deps=("torch",),
        url="https://github.com/advimman/lama",
    )
except (ImportError, ValueError):
    MANIFEST = None


def load_key(model_id):
    # The same warm worker the watermark plugin's boxes variant uses would be
    # ideal, but a load key is per plugin; this one holds LaMa and nothing else.
    return "lama_regions"


def source_for_model(model_id):
    return ["big_lama"]


def _lama_weight(ctx):  # pragma: no cover - heavy optional dep
    p = ctx["sources"]["big_lama"]
    if p and os.path.isfile(p):
        return p
    if p and os.path.isdir(p):
        cand = os.path.join(p, _LAMA_FILE)
        if os.path.isfile(cand):
            return cand
        raise RuntimeError(f"{_LAMA_FILE} not found in {p}")
    from huggingface_hub import hf_hub_download
    return hf_hub_download(p, _LAMA_FILE,
                           local_files_only=bool(ctx.get("local_files_only", True)),
                           token=ctx.get("token") or None)


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from media_compost.ui.inpaint import load_lama

    try:
        lama = load_lama(_lama_weight(ctx))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "the LaMa inpainting model isn't available — download 'big-lama "
            "(inpainting)' in Settings → Models"
        ) from exc
    return lama


def _mask_from_quads(size, quads, dilate):  # pragma: no cover - heavy optional dep
    """A binary L mask (255 over text) from NORMALIZED polygons, dilated a few
    pixels so LaMa gets a little context around each glyph.

    Polygons, not rectangles: an engine reads slanted and perspective text as
    a quad, and an axis-aligned box over it paints out the art either side of
    the words (`ocr.pack_quad` is where that shape comes from).
    """
    from PIL import Image, ImageDraw

    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    for quad in quads:
        pts = [(float(x) * w, float(y) * h) for x, y in quad]
        if len(pts) >= 3:
            draw.polygon(pts, fill=255)
    if dilate > 0:
        # OpenCV's dilation with the same square window, not PIL's
        # `MaxFilter`: PIL's is a window-by-window maximum over the whole
        # picture — hundreds of milliseconds a megapixel, more than the
        # inpainting itself once that ran on a card (measured: the model leg
        # of a text removal was 310 ms median on the 5090 box with the LaMa
        # forward 90 of it). The watermark plugin dilates the same way.
        try:
            import cv2
            import numpy as np
            k = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate * 2 + 1,) * 2)
            mask = Image.fromarray(cv2.dilate(np.asarray(mask), k), "L")
        except Exception:  # noqa: BLE001 - cv2 optional; PIL fallback
            from PIL import ImageFilter
            mask = mask.filter(ImageFilter.MaxFilter(dilate * 2 + 1))
    return mask


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    from media_compost.ui.inpaint import run_lama

    lama = handle
    rgb = image.convert("RGB")
    quads = (options or {}).get("quads") or []
    if not quads:
        # Nothing has been read here — say so by changing nothing, the same
        # answer a watermark-free image gets from the watermark plugin.
        return {"image": None}
    mask = _mask_from_quads(rgb.size, quads, _DILATE)
    return {"image": run_lama(lama, rgb, mask, max_side=_LAMA_MAX_SIDE)}
