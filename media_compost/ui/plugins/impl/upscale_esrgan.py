"""Real-ESRGAN upscaling, via spandrel: a 2× for photographs and a 4× for
line art.

Real-ESRGAN (Wang et al. 2021) is trained on a second-order degradation
pipeline — blur, resizing, noise and JPEG, applied twice — so a soft,
noisy or over-compressed picture is its home case, and it sharpens such a
picture rather than enlarging its faults, which the classical Swin2SR
checkpoints (``upscale_swin2sr.py``) do. It is a GAN: the output is
visibly sharper than the source and carries INVENTED texture, so skin can
turn waxy, small text can be rewritten and a low-resolution face comes
out a different face. Two checkpoints:

- ``RealESRGAN_x2plus`` — the 23-block RRDBNet at 2×, for photographs.
  The one sharpener whose output size is sane for a large photo (the 4×
  real-world Swin2SR turns 12 MP into 192 MP).
- ``RealESRGAN_x4plus_anime_6B`` — a 6-block RRDBNet at 4× tuned for anime
  and illustration; keeps clean edges and flat colour where a photo model
  smears a drawing. Four times cheaper than the 2× above.

The weights are bare ``.pth`` files (no transformers config), so they load
with **spandrel**, which recognises the architecture from the state dict.
Declared as an optional dependency, so the models show as needing **Set
up** until ``spandrel`` is installed. The upscaled result is added as a new
source file (or a linked new item with the toggle). Tiled, on the device,
through `_tile` — with the overlap each net needs (below).
"""

from __future__ import annotations

import os

# model id -> (HF repo, weight file, display name, note, tiling).
#
# TILING is per net because the receptive field is: MEASURED (M4 Max,
# against the untiled forward) the 6-block anime net is within the
# tiler's noise at the default 512 px tiles and 96 px overlap (at most
# 0.16% of the pixels more than one 8-bit step off, max 4-5; `_tile.py`),
# where the 23-block x2plus at 512/96 still had 0.8% off by up to 17 —
# its dense blocks stack sixty-nine 3x3 convolutions — and, unlike
# SCUNet's, the differences sat ONLY within 128 px of a seam (0.000%
# beyond), the mark of missing context rather than of a non-local net.
# See `_X2PLUS`.
#
# The x2plus mirror: `2kpr/Real-ESRGAN` is a third party's copy, not the
# authors' (who publish on GitHub releases, which the app's fetch does not
# read). Its file's SHA-256 was compared against the authors' v0.2.1
# release (49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb)
# and is the same file; the repo states BSD-3-Clause, the project's
# licence. The anime mirror likewise. If either goes away, the local-path
# override takes your own copy.
_MODELS = {
    "realesrgan_x2plus": (
        "2kpr/Real-ESRGAN", "RealESRGAN_x2plus.pth",
        "Real-ESRGAN 2× (photos)",
        "2× for photographs: sharpens soft, noisy or compressed pictures; "
        "invents texture.",
        "_X2PLUS"),
    "realesrgan_anime_x4": (
        "ximso/RealESRGAN_x4plus_anime_6B", "RealESRGAN_x4plus_anime_6B.pth",
        "Real-ESRGAN 4× (anime / line art)",
        "4× upscaling tuned for line art and illustrations.",
        None),
}

#: The x2plus net's ``(tile, overlap)`` in source pixels (`_MODELS`).
#: MEASURED (M4 Max, MPS, fp32, a 2400 x 1800 crop; fraction of pixels
#: more than one 8-bit step from the untiled forward, and the time
#: against 9.4 s untiled): 512/256 0.039% (max 11) 39 s; 768/192 0.42%
#: (max 29) 13 s; 768/256 0.015% (max 11) 22 s; 1024/192 0.062% (max 9)
#: 12 s; 1024/256 0.0038% (max 6) 17 s at 3.0 GB a tile. The overlap
#: buys exactness, the tile buys time (a 1024 tile processes 1.8x the
#: picture at 256, a 512 one 4x); 1024/256 is within the noise the other
#: nets are held to, and a pair of tiles fits a 20 GB card as Swin2SR's
#: does. The 1200 x 900 sweep is in `research/performance-work.md`
#: (eleventh pass).
_X2PLUS = (1024, 256)

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id=mid, task="upscale", name=name, family=name, note=note)
            for mid, (_repo, _file, name, note, _ov) in _MODELS.items()
        ],
        sources=[
            ModelSource(key=mid, label=name, repo=repo,
                        url=f"https://huggingface.co/{repo}",
                        probe=file, allow_patterns=(file,))
            for mid, (repo, file, name, _note, _ov) in _MODELS.items()
        ],
        deps=("spandrel",),
        url="https://github.com/xinntao/Real-ESRGAN",
        source_for_model={mid: mid for mid in _MODELS},
    )
except (ImportError, ValueError):
    MANIFEST = None


def _tiling_for(model_id: str) -> tuple[int | None, int | None]:
    """The net's own ``(tile, overlap)``, Nones for the tiler's defaults."""
    name = _MODELS[model_id][4]
    return globals()[name] if name else (None, None)


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from . import _accel, _spandrel, _tile

    if ctx.get("local_files_only", True):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    repo_file = _MODELS[load_key][1]      # source key == model id == load_key
    model = _spandrel.load_descriptor(
        _spandrel.weights_path(ctx, load_key, repo_file))
    dev = _accel.device("MEDIA_COMPOST_UPSCALE_DEVICE")
    model.to(dev)
    own_tile, own_overlap = _tiling_for(load_key)
    tile, overlap, batch = _tile.settings(dev, tile=own_tile, overlap=own_overlap)
    half = _half(dev) and bool(getattr(model, "supports_half", True))
    # spandrel's descriptor wraps the torch module as `.model`; that is
    # what compiles.
    lazy = _tile.LazyCompiled(model.model, dev, tile)
    print(f"upscale: {_MODELS[load_key][2]} on {dev}, tiles of {tile} px "
          f"(overlap {overlap}, batch {batch}){', fp16' if half else ''}"
          f"{', compiled after warm-up' if lazy.enabled else ''}", flush=True)
    return (model, dev, (tile, overlap, batch), half, lazy)


def _half(dev: str) -> bool:  # pragma: no cover - heavy optional dep
    """Half precision on a card. MEASURED (5090 box): the fp16 forward of
    the RRDB net is 1.7x the fp32 one and its output within the tiling's
    own noise of it (mean |diff| 0.08 of 255 against 0.04 for tiling
    alone, same max) — unlike Swin2SR (`upscale_swin2sr._half`), whose
    attention overflows fp16. The x2plus net agrees (M4 Max, MPS: 0.002%
    of the pixels more than one step off, max 3). `MEDIA_COMPOST_UPSCALE_
    HALF=0` keeps fp32."""
    raw = (os.environ.get("MEDIA_COMPOST_UPSCALE_HALF") or "").strip()
    if raw:
        return raw not in ("0", "false", "no")
    return dev.startswith(("cuda", "mps"))


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    from . import _spandrel, _tile

    model, dev, (tile, overlap, batch), half, lazy = handle
    forward, scale = _spandrel.forward_fn(model, dev, half, lazy)
    return {"image": _tile.run_on_device(image, dev, scale, forward,
                                         tile, overlap, batch)}
