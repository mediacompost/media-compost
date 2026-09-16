"""OpenComic AI descreen models (NCNN — screentone → smooth greys).

Neural screen-tone removal trained on comic/manga pages (OpenComic AI,
CC BY 4.0): halftone dots and hatching become smooth greyscale gradients while
line art stays crisp — markedly cleaner than the classical FFT filter. Two
variants: *Compact* (~1 MB, near-instant) and *Lite* (~10 MB, a touch cleaner).

The models ship as NCNN graphs (.param/.bin) on the project's GitHub releases,
so they run through the tiny pip-installable ``ncnn`` runtime — no torch. The
few-MB weights download automatically on first use into the local cache (like
the SIGGRAPH'17 colorizer's torch.hub weights, there is no HF source), so the
models read as ready once ``ncnn`` is installed.
"""

from __future__ import annotations

import os

_BASE = "https://github.com/ollm/opencomic-ai-training/releases/download/v1.0.1/"
_FILES = {
    "opencomic_descreen_compact": "opencomic-ai-descreen-hard-compact-450000",
    "opencomic_descreen_lite": "opencomic-ai-descreen-hard-lite-1000000",
}

# Tile very large pages to bound memory; overlap absorbs edge effects.
_TILE = 2048
_OVERLAP = 32

try:
    from ..framework import ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id="opencomic_descreen_compact", task="descreen",
                      name="OpenComic descreen (compact)",
                      family="OpenComic descreen", variant="Compact — near-instant",
                      note="Neural screentone → smooth grays; ~1 MB, auto-downloads."),
            ModelSpec(id="opencomic_descreen_lite", task="descreen",
                      name="OpenComic descreen (lite)",
                      family="OpenComic descreen", variant="Lite — higher quality",
                      note="Larger variant, a touch cleaner; ~10 MB, auto-downloads."),
        ],
        sources=[],            # GitHub-hosted, fetched at first load (no HF source)
        deps=("ncnn", "numpy"),
        url="https://github.com/ollm/opencomic-ai-training",
    )
except (ImportError, ValueError):
    MANIFEST = None


def _cache_dir():
    from pathlib import Path

    return Path.home() / ".cache" / "media-compost" / "opencomic"


def weights_ready() -> bool:
    """Whether every variant's graph is already on disk. Import-free — the
    Settings page asks on each poll, possibly before ncnn is installed."""
    cache = _cache_dir()
    return all((cache / (stem + ext)).is_file() and (cache / (stem + ext)).stat().st_size
               for stem in _FILES.values() for ext in (".param", ".bin"))


def fetch_weights() -> None:  # pragma: no cover - network
    """Pull every variant up front, so Settings can offer a Download rather than
    stalling the first run of whichever one is picked."""
    for model_id in _FILES:
        _weights(model_id)


def _weights(model_id: str):  # pragma: no cover - network + cache
    """Local .param/.bin paths for the model, downloading them on first use."""
    import urllib.request

    stem = _FILES[model_id]
    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in (".param", ".bin"):
        dst = cache / (stem + ext)
        if not dst.is_file() or dst.stat().st_size == 0:
            tmp = dst.with_suffix(dst.suffix + ".part")
            urllib.request.urlretrieve(_BASE + stem + ext, tmp)
            tmp.replace(dst)
        paths.append(dst)
    return paths


def load(load_key, ctx):  # pragma: no cover - via worker
    import ncnn

    param, binf = _weights(load_key)
    net = ncnn.Net()
    # VULKAN WHERE A DISCRETE GPU ANSWERS. ncnn's Vulkan path is off by
    # default and must be switched on BEFORE the model loads. Only a
    # discrete card (type 0) is taken: a software device (llvmpipe) is
    # slower than the cores, and so was the 5090 box's integrated Radeon
    # over a job — 6.1 s a page median against 5.3 on its sixteen cores
    # (one probe picture said otherwise; forty did not). A Mac has no
    # Vulkan loader and stays on the CPU. `MEDIA_COMPOST_DESCREEN_DEVICE=cpu`
    # pins it there anywhere.
    if (os.environ.get("MEDIA_COMPOST_DESCREEN_DEVICE") or "").strip().lower() != "cpu":
        try:
            picked = next((i for i in range(ncnn.get_gpu_count())
                           if ncnn.get_gpu_info(i).type() == 0
                           and "llvmpipe" not in ncnn.get_gpu_info(i).device_name().lower()), None)
        except Exception:  # noqa: BLE001 - no Vulkan loader at all
            picked = None
        if picked is not None:
            net.opt.use_vulkan_compute = True
            net.set_vulkan_device(picked)
            print(f"descreen: ncnn on Vulkan device {picked} "
                  f"({ncnn.get_gpu_info(picked).device_name()})", flush=True)
        else:
            print("descreen: ncnn on the CPU", flush=True)
    net.load_param(str(param))
    net.load_model(str(binf))
    return net


def _infer(net, arr):  # pragma: no cover - via worker
    """Run the 1x RGB→RGB net on a HxWx3 uint8 array."""
    import ncnn
    import numpy as np

    h, w = arr.shape[:2]
    mat = ncnn.Mat.from_pixels(arr.tobytes(), ncnn.Mat.PixelType.PIXEL_RGB, w, h)
    mat.substract_mean_normalize([], [1 / 255.0] * 3)
    ex = net.create_extractor()
    ex.input("data", mat)
    ret, out = ex.extract("output")
    if ret != 0:
        raise RuntimeError(f"ncnn inference failed (ret={ret})")
    return np.clip(np.array(out).transpose(1, 2, 0) * 255 + 0.5, 0, 255).astype(np.uint8)


def run(task, model_id, handle, image, options):  # pragma: no cover - via worker
    import numpy as np
    from PIL import Image

    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba)[:, :, 3]
    arr = np.asarray(rgba.convert("RGB"))
    h, w = arr.shape[:2]

    if max(h, w) <= _TILE:
        out = _infer(handle, arr)
    else:
        # Tile with overlap; each tile contributes only its core region.
        out = np.empty_like(arr)
        step = _TILE - 2 * _OVERLAP
        for ty in range(0, h, step):
            for tx in range(0, w, step):
                y0, x0 = max(0, ty - _OVERLAP), max(0, tx - _OVERLAP)
                y1, x1 = min(h, ty + step + _OVERLAP), min(w, tx + step + _OVERLAP)
                res = _infer(handle, np.ascontiguousarray(arr[y0:y1, x0:x1]))
                cy0, cx0 = ty, tx
                cy1, cx1 = min(h, ty + step), min(w, tx + step)
                out[cy0:cy1, cx0:cx1] = res[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]

    result = Image.fromarray(out).convert("RGBA")
    result.putalpha(Image.fromarray(alpha, mode="L"))
    if image.mode not in ("RGBA", "LA", "P"):
        result = result.convert("RGB")
    return {"image": result}
