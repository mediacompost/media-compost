"""Automatic manga/comic colorization (Manga Colorization v2).

qweasdd's manga-colorization-v2 — the de-facto standard local manga
colorizer (an AlacGAN-style generator with a SEResNeXt sketch encoder,
trained on manga) — colors a page fully automatically, no reference needed,
and handles screentones/hatching far better than exemplar transfer. An
FFDNet pass denoises scan grain first (that's what the weights were trained
on). The network runs at ~576 px; this plugin then merges the predicted
*colors* (Lab a/b) back onto the page's original-resolution lightness, so no
line-art detail is lost.

The upstream repo is code-only (weights were on Google Drive) and publishes
**no licence**, so neither half is redistributed here: the weights come from
the Hugging Face mirror ``vergil1000/manga-colorization-v2`` like any other
model, and the network SOURCE is fetched at setup time from a pinned commit
(see ``_build_modules``). It was vendored into this file until 2026-08; with
no grant from the author, copying it into the wheel was not ours to do.
"""

from __future__ import annotations

import os

_GENERATOR_FILE = "generator.zip"   # a regular torch checkpoint, despite .zip
_DENOISER_FILE = "net_rgb.pth"      # FFDNet (rgb) weights
_REPO = "vergil1000/manga-colorization-v2"
_SIZE = 576                          # network working width (multiple of 32)

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(
                id="manga_colorization_v2", task="colorize",
                name="Manga Colorization v2",
                family="Manga Colorization v2",
                note="Automatic manga/comic page colorization — no reference "
                     "needed (AlacGAN-style, trained on manga)."),
        ],
        sources=[
            ModelSource(
                key="manga_colorization_v2", label="Manga Colorization v2",
                repo=_REPO,
                url="https://github.com/qweasdd/manga-colorization-v2",
                probe=_GENERATOR_FILE,
                allow_patterns=(_GENERATOR_FILE, _DENOISER_FILE)),
        ],
        deps=("torch", "torchvision", "cv2", "numpy"),
        url="https://github.com/qweasdd/manga-colorization-v2",
        source_for_model={"manga_colorization_v2": "manga_colorization_v2"},
    )
except (ImportError, ValueError):
    MANIFEST = None


# ---- upstream networks, FETCHED rather than vendored ----------------------
#
# These used to be copied into this file — ~240 lines of AlacGAN generator and
# FFDNet, transcribed layer for layer so the published checkpoint loaded. They
# are gone because qweasdd/manga-colorization-v2 publishes NO LICENCE: with no
# grant, this repository has no right to redistribute that code, and a wheel
# carrying it would be shipping somebody's work without permission.
#
# So the code is fetched at setup time, exactly as the weights are, and the
# person who runs the setup is the one who obtains it. Nothing about the model
# changes; what changes is who copies it.
#
# It is pinned to a COMMIT rather than to `master`: an architecture that
# changed under a cached checkpoint would fail deep in `load_state_dict`, and
# a moving URL is not something to hand a `torch.load`.

_UPSTREAM_SHA = "a0d0e4482e5e86ddbd49958475f3e95f282a1915"
_UPSTREAM_ZIP = ("https://codeload.github.com/qweasdd/manga-colorization-v2/"
                 f"zip/{_UPSTREAM_SHA}")
# What `_build_modules` imports, and therefore what "is it here?" means.
_UPSTREAM_FILES = ("networks/models.py", "networks/extractor.py",
                   "denoising/models.py", "denoising/functions.py")


def _code_dir():
    from pathlib import Path

    return (Path.home() / ".cache" / "media-compost"
            / "manga-colorization-v2" / _UPSTREAM_SHA)


def weights_ready() -> bool:
    """Whether the upstream source is already on disk. Import-free — the
    Settings page may ask before torch is installed."""
    root = _code_dir()
    return all((root / f).is_file() for f in _UPSTREAM_FILES)


def fetch_weights() -> None:  # pragma: no cover - network
    """Pull the upstream source. Called by the `setup_action` module, so the
    download happens during setup rather than ambushing the first run."""
    import io
    import shutil
    import urllib.request
    import zipfile

    root = _code_dir()
    if weights_ready():
        return
    with urllib.request.urlopen(_UPSTREAM_ZIP) as r:  # noqa: S310 - pinned https
        blob = r.read()
    tmp = root.with_name(root.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(tmp)
    # A GitHub zipball wraps everything in one `<repo>-<sha>/` directory.
    inner = next(d for d in tmp.iterdir() if d.is_dir())
    shutil.rmtree(root, ignore_errors=True)
    root.parent.mkdir(parents=True, exist_ok=True)
    inner.replace(root)
    shutil.rmtree(tmp, ignore_errors=True)


def _build_modules():  # pragma: no cover - heavy optional dep
    """`(Generator, FFDNet)` from the upstream checkout, fetching it if needed.

    The fetch is a few hundred KB of source, so doing it lazily costs a moment
    rather than the multi-minute stall a weights pack would — and `load()` is
    already the slow step. `denoising/models.py` imports
    `denoising.functions` ABSOLUTELY, so the repository ROOT is what goes on
    `sys.path`, and it comes off again once the modules are bound: the names
    up there (`networks`, `denoising`, `utils`) are generic enough that
    leaving them in front of everything else is asking for a collision.
    """
    import sys

    if not weights_ready():
        fetch_weights()
    root = str(_code_dir())
    sys.path.insert(0, root)
    try:
        from denoising.models import FFDNet
        from networks.models import Generator
    finally:
        try:
            sys.path.remove(root)
        except ValueError:
            pass
    return Generator, FFDNet


def _fetch(ctx, filename: str) -> str:  # pragma: no cover - heavy optional dep
    p = ctx["sources"]["manga_colorization_v2"]
    if p and os.path.isdir(p):
        cand = os.path.join(p, filename)
        if os.path.isfile(cand):
            return cand
        raise RuntimeError(f"{filename} not found in {p}")
    from huggingface_hub import hf_hub_download

    return hf_hub_download(p, filename,
                           local_files_only=bool(ctx.get("local_files_only", True)),
                           token=ctx.get("token") or None)


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch

    Generator, FFDNet = _build_modules()
    from . import _accel

    device = _accel.device("MEDIA_COMPOST_COLORIZE_DEVICE")   # was CUDA or the CPU: never MPS
    gen = Generator()
    # The published checkpoint was saved from the wrapping Colorizer's
    # ``generator`` submodule — plain tensors, so weights-only loads fine.
    gen.load_state_dict(torch.load(_fetch(ctx, _GENERATOR_FILE),
                                   map_location="cpu"))
    # Upstream's FFDNet is parameterised; `net_rgb.pth` is the 3-channel one.
    denoiser = FFDNet(num_input_channels=3)
    sd = torch.load(_fetch(ctx, _DENOISER_FILE), map_location="cpu")
    # The FFDNet release was saved under DataParallel ("module." prefix).
    sd = {(k[7:] if k.startswith("module.") else k): v for k, v in sd.items()}
    denoiser.load_state_dict(sd)
    # THE DENOISER STAYS ON THE CPU UNDER MPS: upstream FFDNet builds its
    # noise map with `torch.FloatTensor` / `torch.cuda.FloatTensor` inside
    # its forward — CUDA or the CPU, nothing else — and on MPS every page
    # failed with "Passed CPU tensor to MPS op". It is small; the generator
    # is the cost, and that one runs on the device.
    den_device = "cpu" if device == "mps" else device
    print(f"colorize: manga v2 generator on {device}, denoiser on {den_device}", flush=True)
    return gen.to(device).eval(), denoiser.to(den_device).eval(), device, den_device


def _denoise(denoiser, device, gray_u8, sigma=25.0):  # pragma: no cover
    """FFDNet pass over the (3-channel-repeated) page, like upstream — the
    generator was trained on denoised input. Capped at 1200 px like upstream."""
    import cv2
    import numpy as np
    import torch

    img = np.repeat(gray_u8[:, :, None], 3, 2).astype(np.float32) / 255.0
    if max(img.shape[0], img.shape[1]) > 1200:
        r = max(img.shape[0], img.shape[1]) / 1200
        img = cv2.resize(img, (int(img.shape[1] / r), int(img.shape[0] / r)),
                         interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    pad_h, pad_w = h % 2, w % 2
    if pad_h or pad_w:
        img = np.pad(img, ((0, pad_h), (0, pad_w), (0, 0)), "edge")
    t = torch.from_numpy(img.transpose(2, 0, 1))[None].to(device)
    with torch.no_grad():
        noise = denoiser(t, torch.tensor([sigma / 255.0], device=device))
        out = torch.clamp(t - noise, 0.0, 1.0)
    out = out[0].cpu().numpy().transpose(1, 2, 0)[:h, :w]
    return (out[:, :, 0] * 255).clip(0, 255).astype(np.uint8)


def _resize_pad(gray_u8, size):  # pragma: no cover - heavy optional dep
    """Upstream resize_pad: fit the page to the working size (multiple of 32),
    padding the short side with the maximum (white) value."""
    import cv2
    import numpy as np

    img = gray_u8
    if img.shape[0] < img.shape[1]:
        ratio = img.shape[0] / (size * 1.5)
        width = int(np.ceil(img.shape[1] / ratio))
        img = cv2.resize(img, (width, int(size * 1.5)),
                         interpolation=cv2.INTER_AREA)
        pad = (0, width + (32 - width % 32) - width)
        img = np.pad(img, ((0, 0), (0, pad[1])), "maximum")
    else:
        ratio = img.shape[1] / size
        height = int(np.ceil(img.shape[0] / ratio))
        img = cv2.resize(img, (size, height), interpolation=cv2.INTER_AREA)
        pad = (height + (32 - height % 32) - height, 0)
        img = np.pad(img, ((0, pad[0]), (0, 0)), "maximum")
    return img, pad


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import cv2
    import numpy as np
    import torch
    from PIL import Image

    gen, denoiser, device, den_device = handle
    rgb = np.asarray(image.convert("RGB"))
    orig_gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    page = _denoise(denoiser, den_device, orig_gray)
    page, pad = _resize_pad(page, _SIZE)
    t = torch.from_numpy(page.astype(np.float32) / 255.0)[None, None]
    hint = torch.zeros(1, 4, t.shape[2], t.shape[3])
    with torch.no_grad():
        out = gen(torch.cat([t, hint], 1).to(device))
    # The generator answers (fake, guide) on this code version — indexing
    # the TUPLE took the whole batch and the permute below failed on every
    # page ("permute(sparse_coo): input.dim() = 4"), on the CPU and on a
    # card alike; the first tensor's first row is the picture.
    if isinstance(out, (tuple, list)):
        out = out[0]
    fake = out[0].cpu()
    small = (fake.permute(1, 2, 0).numpy() * 0.5 + 0.5).clip(0, 1)
    if pad[0]:
        small = small[:-pad[0]]
    if pad[1]:
        small = small[:, :-pad[1]]

    # Merge the predicted colors onto the ORIGINAL-resolution lightness: the
    # network output is ~576 px, so keep its Lab a/b but the page's own L —
    # full line-art detail, new colors.
    h, w = orig_gray.shape
    small_lab = cv2.cvtColor(small.astype(np.float32), cv2.COLOR_RGB2Lab)
    ab = cv2.resize(small_lab[:, :, 1:], (w, h),
                    interpolation=cv2.INTER_LINEAR)
    out_lab = np.dstack([orig_gray.astype(np.float32) * (100.0 / 255.0), ab])
    out = cv2.cvtColor(out_lab, cv2.COLOR_Lab2RGB)
    out = (np.clip(out, 0, 1) * 255).astype(np.uint8)
    return {"image": Image.fromarray(out)}
