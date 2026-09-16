"""Blind noise and compression clean-up at the original size with SCUNet,
via spandrel.

SCUNet — "Practical Blind Denoising via Swin-Conv-UNet and Data Synthesis"
(Zhang et al. 2022, KAIR) — is a Swin-transformer UNet trained on a
"practical" degradation pipeline: Gaussian, Poisson, speckle and
camera-sensor noise, JPEG at random quality and up-and-down resizing, in
random order. So it is the one to run on a noisy phone photograph, a
scanned print or a re-saved JPEG WITHOUT changing its size — FBCNN
(``dejpeg_fbcnn.py``) handles the JPEG blocks but not sensor grain, and
the real-world Swin2SR handles both but quadruples the picture. It does
not sharpen an out-of-focus picture (the only blur in its training is
resize blur) and it is trained on photographs, so a drawing's clean edges
soften. The ``real_gan`` checkpoint: perceptual, a touch sharper than the
``real_psnr`` one, with a published report of a brightness shift on some
pictures.

Weights are a bare ``.pth`` (no transformers config), loaded with
**spandrel** like the Real-ESRGAN models. Declared as an optional
dependency, so the model shows as needing **Set up** until ``spandrel`` is
installed. The cleaned result is added as a new source file (or a linked
new item with the toggle).

THE WHOLE PICTURE GOES THROUGH AT ONCE — NO TILING (owner decision,
2026-09: a model spandrel marks "tiling discouraged" is not tiled). What
the measurements found, for the record (M4 Max; `research/performance-
work.md`, eleventh pass): the upscalers' tiling (512 px, 96 overlap) was
wrong for this net over the WHOLE tile, not at the seams — one pixel in
ten more than one 8-bit step off, max 29 — and no overlap or tile size
changed that, because a Swin block partitions its input into windows
anchored at the input's origin and this UNet's deepest stage sees 8 px
windows at 1/8 resolution: a tile starting off the 64 px grid is
partitioned differently from the whole picture. Tiles STARTED ON that
grid (origins multiples of 64, overlap 128) reproduced the CPU's untiled
forward to 0.002-0.008% of the pixels (max 3) at every size tried, 1.1 to
4.3 MP, on CPU and MPS alike; the alignment was fifteen lines in
`_tile._cuts` and is not kept.

Untiled costs memory — `_BYTES_PER_PIXEL` a source pixel, ~5 GB a
megapixel in fp32 — and ON APPLE SILICON IT COSTS CORRECTNESS PAST A
SIZE: measured against the CPU's forward, the untiled MPS forward is
exact (max 1) up to a padded input of 2^22 pixels (2560 x 1600) and wrong
past it (2560 x 1664: 5.5% of the pixels off, max 164; 2400 x 1800:
13.5%, max 126, and max 255 in fp16), while the same pictures through
aligned tiles were exact. 2^22 pixels times the first stage's 64 channels
is 2^28 elements, the mark of a Metal kernel indexing with 32 bits. So on
MPS a picture past `_MPS_MAX_PADDED` runs on the CPU instead — correct,
and 28 s for 4.3 MP on an M4 Max against 7 on MPS — and on a card a
picture past `max_pixels` is refused per picture with a line naming the
room the device has; the job logs it and goes on.
`MEDIA_COMPOST_RESTORE_MAX_PIXELS` overrides the memory cap (0 = none).
"""

from __future__ import annotations

import os

_FILE = "scunet_color_real_gan.pth"

#: Device bytes the untiled forward takes per source pixel, by half
#: precision, MEASURED (M4 Max, MPS, driver-allocated over the resident
#: model): fp32 5.7 GB for 1.08 MP, 9.4 for 1.9, 13.9 for 3.0, 22.1 for
#: 4.3, 60.7 for 12 — up to 5.1 GB a megapixel; fp16 (autocast) 5.0 GB
#: for 1.9 MP, 8.2 for 3.0 — 2.7 GB a megapixel, output within one 8-bit
#: step of fp32 everywhere. So a 16 GB card cleans a picture of about 5
#: MP, a 32 GB one 11, and a Mac whatever its unified memory allows.
_BYTES_PER_PIXEL = {False: 5.1 * 2**30 / 1e6, True: 2.8 * 2**30 / 1e6}
#: Device memory kept back for the model, the picture and the driver.
_RESERVE = 1.5 * 2**30
#: The padded input (SCUNet pads to a multiple of 64 on each side) past
#: which the MPS forward computes wrong pixels (module docstring): 2^22.
_MPS_MAX_PADDED = 2**22
_PAD = 64

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id="scunet_real_gan", task="restore",
                      name="SCUNet (noise and compression)",
                      family="SCUNet (noise and compression)",
                      note="Removes sensor noise and JPEG artifacts at the "
                           "original size; photographs, not drawings. Runs "
                           "untiled: a big picture needs a big card."),
        ],
        sources=[
            # `krnl/ScuNET` is a third party's copy of the standard
            # `scunet_color_real_gan.pth` from the KAIR v1.0 GitHub release
            # (which the app's fetch does not read). Its SHA-256 was compared
            # against the release file
            # (892c83f812c59173273b74f4f34a14ecaf57a2fdb68df056664589beb55c966e)
            # and is the same file; the licence is SCUNet's, Apache-2.0
            # (the mirror states none of its own — THIRD-PARTY-NOTICES.md).
            # If it goes away, the local-path override takes your own copy.
            ModelSource(key="scunet_real_gan",
                        label="SCUNet real-image (GAN)",
                        repo="krnl/ScuNET",
                        url="https://github.com/cszn/SCUNet",
                        probe=_FILE, allow_patterns=(_FILE,)),
        ],
        deps=("spandrel",),
        url="https://github.com/cszn/SCUNet",
        source_for_model={"scunet_real_gan": "scunet_real_gan"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def max_pixels(memory: int | None, half: bool) -> int | None:
    """Source pixels the untiled forward fits into ``memory`` device bytes;
    None for no bound (the CPU, whose memory is the machine's, or
    `MEDIA_COMPOST_RESTORE_MAX_PIXELS=0`). Pure — the memory is the
    caller's (`_tile.device_memory`)."""
    raw = (os.environ.get("MEDIA_COMPOST_RESTORE_MAX_PIXELS") or "").strip()
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = 0
        return n if n > 0 else None
    if memory is None:
        return None
    return max(0, int((memory - _RESERVE) / _BYTES_PER_PIXEL[half]))


def padded_pixels(w: int, h: int) -> int:
    """Pixels of the input SCUNet actually sees: each side padded up to a
    multiple of 64 (its own replication pad)."""
    return (-(-w // _PAD) * _PAD) * (-(-h // _PAD) * _PAD)


def needs_cpu(dev: str, w: int, h: int) -> bool:
    """Whether a ``w`` x ``h`` picture must leave ``dev`` for the CPU to
    be computed correctly — MPS past `_MPS_MAX_PADDED` (module docstring)."""
    return dev.startswith("mps") and padded_pixels(w, h) > _MPS_MAX_PADDED


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from . import _accel, _spandrel, _tile

    if ctx.get("local_files_only", True):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    model = _spandrel.load_descriptor(
        _spandrel.weights_path(ctx, "scunet_real_gan", _FILE))
    if int(getattr(model, "scale", 1) or 1) != 1:
        raise RuntimeError("not a same-size restoration model")
    dev = _accel.device("MEDIA_COMPOST_RESTORE_DEVICE")
    model.to(dev)
    half = _half(dev) and bool(getattr(model, "supports_half", True))
    cap = max_pixels(_tile.device_memory(dev), half)
    room = "no size limit" if cap is None else f"up to {cap / 1e6:.1f} MP a picture"
    print(f"restore: SCUNet on {dev}, untiled, {room}"
          f"{', fp16' if half else ''}"
          f"{f', past {_MPS_MAX_PADDED / 1e6:.1f} MP on the CPU' if dev.startswith('mps') else ''}",
          flush=True)
    return (model, dev, half, cap, {})


def _half(dev: str) -> bool:  # pragma: no cover - heavy optional dep
    """Half precision on a card. MEASURED (M4 Max, MPS, 1200 x 900): the
    fp16 forward's output is within one 8-bit step of the fp32 one on
    EVERY pixel (max 1). `MEDIA_COMPOST_RESTORE_HALF=0` keeps fp32."""
    raw = (os.environ.get("MEDIA_COMPOST_RESTORE_HALF") or "").strip()
    if raw:
        return raw not in ("0", "false", "no")
    return dev.startswith(("cuda", "mps"))


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    from . import _spandrel, _tile

    model, dev, half, cap, spare = handle
    w, h = image.size
    if cap is not None and w * h > cap:
        raise RuntimeError(
            f"picture is {w} x {h} ({w * h / 1e6:.1f} MP); SCUNet runs untiled "
            f"and {dev} has room for about {cap / 1e6:.1f} MP "
            "(MEDIA_COMPOST_RESTORE_MAX_PIXELS overrides)")
    if needs_cpu(dev, w, h):
        # A CPU copy of the net, made once (the weights are 72 MB); the
        # Mac's memory is unified, so the memory cap above already speaks
        # for this path too.
        if "cpu" not in spare:
            import copy

            spare["cpu"] = copy.deepcopy(model).to("cpu")
        print(f"restore: {w} x {h} is past what MPS computes correctly "
              f"({_MPS_MAX_PADDED / 1e6:.1f} MP padded); running it on the CPU",
              flush=True)
        model, dev, half = spare["cpu"], "cpu", False
    forward, scale = _spandrel.forward_fn(model, dev, half)
    return {"image": _tile.run_on_device(image, dev, scale, forward,
                                         tile=0, overlap=0, batch=1)}
