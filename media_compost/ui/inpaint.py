"""LaMa inpainting, shared by the watermark plugin (out-of-process worker) and
the editor's interactive inpaint tool (in-process, models kept warm).

`run_lama` is pure inference given a loaded model + a PIL image and mask; it only
changes the masked pixels (unmasked pixels are preserved exactly). `get_lama`
keeps the models resident in the current process for the interactive endpoint.

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


def _inpaint_full(lama, rgb, mask):  # pragma: no cover - heavy optional dep
    """Run LaMa on a whole RGB image + L mask (hole=255). Pad to a multiple of 8,
    image in [0,1] NCHW, mask hole=1; returns the full RGB output."""
    import numpy as np
    import torch
    from PIL import Image

    w, h = rgb.size
    pw, ph = (8 - w % 8) % 8, (8 - h % 8) % 8
    img = np.asarray(rgb, dtype=np.float32) / 255.0
    msk = (np.asarray(mask, dtype=np.float32) / 255.0 > 0.5).astype(np.float32)
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
    arr = out[0].permute(1, 2, 0).clamp(0, 1).cpu().numpy()
    if arr.max() <= 1.0 + 1e-4:
        arr = arr * 255.0
    return Image.fromarray(arr[:h, :w].astype("uint8"), "RGB")


def run_lama(lama, rgb, mask, max_side: int = MAX_SIDE):  # pragma: no cover - heavy optional dep
    """Inpaint the masked region of ``rgb`` (PIL RGB) using ``mask`` (PIL L,
    255=inpaint). Returns an RGB image with **only the masked pixels changed**."""
    from PIL import Image

    w, h = rgb.size
    if max(w, h) <= max_side:
        painted = _inpaint_full(lama, rgb, mask)
    else:
        scale = max_side / max(w, h)
        sw, sh = max(1, round(w * scale)), max(1, round(h * scale))
        painted = _inpaint_full(
            lama, rgb.resize((sw, sh), Image.LANCZOS),
            mask.resize((sw, sh), Image.NEAREST),
        ).resize((w, h), Image.LANCZOS)
    out = rgb.copy()
    out.paste(painted, (0, 0), mask)  # L mask as alpha: replace only masked pixels
    return out
