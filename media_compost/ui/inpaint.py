"""LaMa inpainting, shared by the watermark plugin (out-of-process worker) and
the editor's interactive inpaint tool (in-process, models kept warm).

`run_lama` is pure inference given a loaded model + a PIL image and mask; it only
changes the masked pixels (unmasked pixels are preserved exactly). `get_lama`
keeps the models resident in the current process for the interactive endpoint.

THE MASK IS AN ALPHA, NOT A YES/NO. A partly-selected pixel is partly
replaced, which is what the editor's **Blur selection** verb is for: a hard
mask edge leaves the seam of whatever was done visible as a line. The mask was
binarised on its way in and the same binary mask used to composite, so the
feather — the app's own answer to a visible seam — was thrown away and the
inpaint stopped dead at the 50% contour. What the MODEL is told is still
binary (LaMa fills holes, it has no notion of a half-hole), and that hole is
every pixel the composite will touch however faintly, so nothing is blended in
that the model was not asked to generate.

Two TorchScript checkpoints share the identical calling convention (image in
[0,1] NCHW + hole mask): the photographic **big-lama**, and an **anime/manga
fine-tune** (dreMaz's AnimeMangaInpainting, traced) that reconstructs line art
and screentones much better on illustrations.
"""

from __future__ import annotations

import threading

# The TorchScript big-lama weights (a single .pt in this HF repo).
LAMA_REPO = "JosephCatrambone/big-lama-torchscript"
LAMA_FILE = "lama.pt"
# key -> (HF repo, filename). Keys are the Settings download-source keys.
LAMA_MODELS: dict[str, tuple[str, str]] = {
    "big_lama": (LAMA_REPO, LAMA_FILE),
    "anime_lama": ("s9roll74/tracing_dreMaz_AnimeMangaInpainting", "model.jit.pt"),
}
# Longest edge fed to LaMa; larger images are inpainted downscaled and the
# masked region composited back at full resolution (bounds memory).
MAX_SIDE = 2048
# How far out the model's own tone bias is measured (see `_match_tone`), and
# the most it may be corrected by. The cap is what keeps this a CORRECTION: a
# ring that is unrepresentative — a hole sitting on the edge of something the
# model rebuilt badly — can pull the estimate, and at eight levels the worst
# it can do is smaller than the biases actually measured (median 0.9, max 2.4
# over thirty photographs).
TONE_RING_PX = 16
TONE_CAP = 8.0

_lock = threading.Lock()
_cached: dict[str, tuple[str, object]] = {}  # key -> (weights path, model)


def lama_weights_path(local_files_only: bool = True, key: str = "big_lama") -> str:
    from huggingface_hub import hf_hub_download

    repo, fn = LAMA_MODELS[key]
    return hf_hub_download(repo, fn, local_files_only=local_files_only)


def device() -> str:  # pragma: no cover - heavy optional dep
    """The accelerator this machine has, or the CPU. LaMa used to be loaded
    with `map_location="cpu"` and left there by both plugins and the
    editor's tool: 2.3 s a 1024 px picture on an M4 Max's cores against
    0.46 on its GPU, four seconds a 2048 px picture on the 5090 box's cores
    with the card at 1%. `MEDIA_COMPOST_INPAINT_DEVICE` pins one by hand."""
    import os

    import torch

    forced = (os.environ.get("MEDIA_COMPOST_INPAINT_DEVICE") or "").strip()
    if forced:
        return forced
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None \
            and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_lama(path: str):  # pragma: no cover - heavy optional dep
    """The TorchScript model, on the accelerator where one runs it — proven
    by a small forward at load, so a device that cannot (an MPS without an
    operator the fast Fourier convolutions need, on an older torch) is
    found here, once, and the CPU stands in with a line in the log. The
    output is the same to the last bit on MPS (measured) and the pixels are
    float32 on every device."""
    import torch

    dev = device()
    # NO PROFILING EXECUTOR — except on MPS. TorchScript's default executor
    # profiles the first two calls of every new INPUT SHAPE and
    # re-specialises the graph — 500–650 ms each on the 5090 box against
    # 150 for the forward — and a job never sees the same shape twice, so
    # every picture paid it (measured: 654 523 153 ms for one shape, 159
    # 156 157 with it off). The legacy executor's graph fuser does not know
    # MPS ("Unknown device for graph fuser", with the fusers switched off
    # too), so MPS keeps the default and pays the first call per shape:
    # 847 then 341 ms for a 1024 px picture on an M4 Max, against 2 300 on
    # its cores. Process-wide flags; the only TorchScript here is this model.
    if dev != "mps":
        try:
            torch._C._jit_set_profiling_executor(False)
            torch._C._jit_set_profiling_mode(False)
        except Exception:  # noqa: BLE001 - an older or newer torch without them
            pass
    model = torch.jit.load(path, map_location="cpu")
    model.eval()
    if dev != "cpu":
        try:
            model = model.to(dev)
            with torch.no_grad():
                model(torch.zeros(1, 3, 64, 64, device=dev),
                      torch.zeros(1, 1, 64, 64, device=dev))
        except Exception as exc:  # noqa: BLE001 - the CPU always works
            print(f"inpaint: LaMa cannot run on {dev} ({str(exc)[:120]}); "
                  f"using the CPU", flush=True)
            model = torch.jit.load(path, map_location="cpu").eval()
            dev = "cpu"
    print(f"inpaint: LaMa on {dev}", flush=True)
    return model


def model_device(lama):  # pragma: no cover - heavy optional dep
    try:
        return next(lama.parameters()).device
    except Exception:  # noqa: BLE001 - a script with no parameters
        import torch
        return torch.device("cpu")


def get_lama(local_files_only: bool = True, key: str = "big_lama"):  # pragma: no cover - heavy optional dep
    """The process-cached LaMa model for ``key`` (loaded once per model for the
    interactive endpoint; both variants can stay warm side by side)."""
    with _lock:
        path = lama_weights_path(local_files_only, key)
        cur = _cached.get(key)
        if cur is None or cur[0] != path:
            cur = (path, load_lama(path))
            _cached[key] = cur
        return cur[1]


def _ring_around(hole, px):
    """The band of NOT-hole pixels within ``px`` of the hole, as a bool array.

    Cropped to the hole's neighbourhood before dilating: a window-by-window
    maximum over a whole picture costs hundreds of milliseconds a megapixel
    (the note in `text_removal._mask_from_quads` says it about the same
    operation), and this one is only ever asked about the rim.
    """
    import numpy as np
    from PIL import Image

    h, w = hole.shape
    ys, xs = np.where(hole)
    if ys.size == 0:
        return np.zeros_like(hole)
    y0, y1 = max(0, ys.min() - px - 1), min(h, ys.max() + px + 2)
    x0, x1 = max(0, xs.min() - px - 1), min(w, xs.max() + px + 2)
    sub = hole[y0:y1, x0:x1]
    k = 2 * px + 1
    try:
        import cv2
        grown = cv2.dilate(sub.astype("uint8"),
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    except Exception:  # noqa: BLE001 - cv2 optional, as everywhere else here
        from PIL import ImageFilter
        grown = np.asarray(Image.fromarray((sub * 255).astype("uint8"))
                           .filter(ImageFilter.MaxFilter(k))) > 127
    out = np.zeros_like(hole)
    out[y0:y1, x0:x1] = grown & ~sub
    return out


def _match_tone(painted, orig, hole):  # pragma: no cover - heavy optional dep
    """Take the model's own tone bias off the fill.

    LaMa regenerates the WHOLE picture, not just the hole, and its rendering
    of the part it was not asked to invent is not the original: measured on
    flat colour it comes back 1.5 to 3 levels off, differently per channel, so
    a fill dropped into a smooth area — a sky, a wall, a screentone — sits at a
    slightly different tone and the seam is the giveaway. The pixels AROUND the
    hole are the measurement: there we have both the model's answer and the
    truth, and the bias is smooth across the frame, so what it is on the ring is
    what it is inside. The MEDIAN, because the model's local reconstruction
    errors are large (mean 6.9 levels, max 149 over a photograph) while its
    tone offset is small and systematic — a mean would be dragged by the
    former and miss the latter.

    MEASURED through `run_lama` itself, as the step in mean tone between a
    band just inside the hole and one just outside it — which is what "I can
    see the seam" means. On flat colour: mean 1.70 levels down to 0.41, worst
    2.10 down to 0.69, better on all six tones tried. On smooth areas of
    twenty-five photographs: mean 1.29 down to 0.76, p90 2.63 down to 1.36,
    better on eighteen and worse by more than 0.3 on five — the bias is not
    perfectly uniform across a frame, which is what the cap is for.
    """
    import numpy as np

    ring = _ring_around(hole, TONE_RING_PX)
    # Too little to measure from (a hole filling the frame, or hard against
    # its edge): leave the model's answer alone rather than guess.
    if ring.sum() < 200:
        return painted
    bias = np.median((orig - painted)[ring].reshape(-1, orig.shape[2]), axis=0)
    return painted + np.clip(bias, -TONE_CAP, TONE_CAP)


def _inpaint_full(lama, rgb, hole):  # pragma: no cover - heavy optional dep
    """Run LaMa on a whole RGB image + L hole mask (hole=255). Pad to a multiple
    of 8, image in [0,1] NCHW, mask hole=1; returns the full RGB output."""
    import numpy as np
    import torch
    from PIL import Image

    w, h = rgb.size
    pw, ph = (8 - w % 8) % 8, (8 - h % 8) % 8
    img = np.asarray(rgb, dtype=np.float32) / 255.0
    msk = (np.asarray(hole, dtype=np.float32) / 255.0 > 0.5).astype(np.float32)
    if pw or ph:
        img = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="reflect")
        msk = np.pad(msk, ((0, ph), (0, pw)), mode="reflect")
    dev = model_device(lama)
    # UPLOAD FIRST, PERMUTE ON THE DEVICE. `.permute(...).to(dev)` hands the
    # copy a strided view, and a strided host-to-device copy goes element by
    # element: 370 ms of a 481 ms call for a 2.4 MP picture on the 5090 box,
    # against 87 for the forward itself. A contiguous HWC array uploads as
    # one memcpy and the permute is a view on the card.
    it = torch.from_numpy(np.ascontiguousarray(img)).to(dev).permute(2, 0, 1).unsqueeze(0).contiguous()
    mt = torch.from_numpy(np.ascontiguousarray(msk)).to(dev).unsqueeze(0).unsqueeze(0)
    with torch.no_grad():
        out = lama(it, mt)
    # The model answers in [0,1] (there was a guard here asking whether it had
    # answered in [0,255] instead — it sat after the clamp, so it could only
    # ever be true).
    arr = out[0].permute(1, 2, 0).clamp(0, 1).cpu().numpy()[:h, :w] * 255.0
    arr = _match_tone(arr, np.asarray(rgb, dtype=np.float32),
                      np.asarray(hole) > 127)
    # ROUND, DO NOT TRUNCATE. `.astype("uint8")` throws the fraction away, so
    # every inpainted pixel came back half a level dark — a bias in one
    # direction over the whole fill, which on a flat tone is exactly the kind
    # of thing that draws the eye to a seam.
    return Image.fromarray(np.rint(arr).clip(0, 255).astype("uint8"), "RGB")


def run_lama(lama, rgb, mask, max_side: int = MAX_SIDE):  # pragma: no cover - heavy optional dep
    """Inpaint the masked region of ``rgb`` (PIL RGB) using ``mask`` (PIL L).

    ``mask`` is an ALPHA: 255 replaces outright, 0 leaves alone, and the values
    between fade the fill in — a feathered selection is blended, not cut off at
    its 50% contour. Returns an RGB image with **only masked pixels changed**.
    A plain 0/255 mask (what both removal plugins draw) behaves exactly as it
    always did.
    """
    from PIL import Image

    w, h = rgb.size
    if mask.mode != "L":
        mask = mask.convert("L")
    # WHAT THE MODEL IS TOLD IS A SUPERSET OF WHAT THE COMPOSITE TOUCHES. Any
    # pixel with alpha at all is a hole, because a pixel blended from the
    # model's answer where the model was told "this one is already right" is
    # blended from its RECONSTRUCTION of the original — off by a mean of 6.9
    # levels and as much as 149 — rather than from a fill.
    hole = mask.point(lambda v: 255 if v > 0 else 0).convert("L")
    if max(w, h) <= max_side:
        painted = _inpaint_full(lama, rgb, hole)
    else:
        scale = max_side / max(w, h)
        sw, sh = max(1, round(w * scale)), max(1, round(h * scale))
        # BOX then "anything at all", not NEAREST: a nearest-neighbour
        # downscale SAMPLES the mask, so a block straddling the boundary can
        # come back empty and leave a rim of real hole the model was never
        # asked to fill (601 px along one edge of a 4096 px picture, hugging
        # the seam — the one place a wrong pixel shows). A box filter answers
        # with the block's coverage, and any coverage is a hole.
        small = hole.resize((sw, sh), Image.BOX).point(lambda v: 255 if v > 0 else 0)
        painted = _inpaint_full(
            lama, rgb.resize((sw, sh), Image.LANCZOS), small.convert("L"),
        ).resize((w, h), Image.LANCZOS)
    out = rgb.copy()
    out.paste(painted, (0, 0), mask)  # the SOFT mask as alpha
    return out
