"""Image super-resolution (upscaling) with Swin2SR.

Swin2SR is a compact transformer super-resolution model served through
Hugging Face transformers, so — like the depth models — this is a clean,
small, fully-local integration. ONE checkpoint is offered: the 4× tuned
for real-world (noisy/compressed) photographs. The two "classical"
checkpoints (2× and 4×, trained on clean bicubic downscales) were REMOVED
by owner decision (2026-09) after a comparison grid over random crawl
photographs: they enlarge and sharpen every compression artifact in the
source, which the real-world checkpoint and Real-ESRGAN
(``upscale_esrgan.py``) remove instead. The upscaled result is added as a
new (higher-resolution) source file on the item — or, with the "new item"
toggle, its own linked item.
"""

from __future__ import annotations

import os

# model id -> (HF repo, display name, note, weight file). The weight file is
# in the table because Swin2SR repos differ: the removed classical
# checkpoints carried `.safetensors` beside a `.bin` of the same weights
# (fetching both doubled the download for nothing) and the real-world one
# ships only the `.bin` — a checkpoint added here must name its own.
_MODELS = {
    "swin2sr_realworld_x4": (
        "caidas/swin2SR-realworld-sr-x4-64-bsrgan-psnr",
        "Swin2SR 4× (real-world)",
        "4× tuned for real-world (noisy/compressed) photos.",
        "pytorch_model.bin"),
}

try:
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id=mid, task="upscale", name=name, family=name, note=note)
            for mid, (_repo, name, note, _w) in _MODELS.items()
        ],
        sources=[
            ModelSource(key=mid, label=name, repo=repo,
                        url=f"https://huggingface.co/{repo}", probe=weights,
                        allow_patterns=TRANSFORMERS_CONFIG_FILES + (weights,))
            for mid, (repo, name, _note, weights) in _MODELS.items()
        ],
        deps=("transformers", "torch"),
        url="https://huggingface.co/caidas/swin2SR-realworld-sr-x4-64-bsrgan-psnr",
        source_for_model={mid: mid for mid in _MODELS},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch
    from transformers import AutoImageProcessor, Swin2SRForImageSuperResolution

    # transformers 5.x dropped the "image-to-image" pipeline, so drive the Swin2SR
    # model + its image processor directly.
    if ctx.get("local_files_only", True):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    repo = ctx["sources"][load_key]      # source key == model id == load_key
    local_only = bool(ctx.get("local_files_only", True))
    proc = AutoImageProcessor.from_pretrained(repo, local_files_only=local_only)
    model = Swin2SRForImageSuperResolution.from_pretrained(repo, local_files_only=local_only)
    model = model.eval()
    from . import _accel, _tile

    dev = _accel.device("MEDIA_COMPOST_UPSCALE_DEVICE")
    model = model.to(dev)
    _cache_attention_masks(model)
    tile, overlap, batch = _tile.settings(dev)
    tile -= tile % _WINDOW      # a tile off the window grid cannot be exact
    half = _half(dev)
    lazy = _tile.LazyCompiled(model, dev, tile)
    print(f"upscale: Swin2SR on {dev}, tiles of {tile} px (overlap {overlap}, "
          f"batch {batch}){', bf16' if half else ''}"
          f"{', compiled after warm-up' if lazy.enabled else ''}", flush=True)
    return (model, proc, dev, (tile, overlap, batch), half, lazy)


#: The shifted-window masks, one per (window, shift, padded height, padded
#: width, dtype, device) — a handful of tile shapes per job. Cleared past
#: `_MASKS_MAX` entries.
_MASKS: dict = {}
_MASKS_MAX = 16


def _cache_attention_masks(model) -> None:  # pragma: no cover - heavy optional dep
    """THE MASK THAT TRANSFORMERS BUILDS ON THE CPU EVERY FORWARD, ONCE ON
    THE DEVICE INSTEAD.

    `Swin2SRLayer.get_attn_mask` builds the cyclic-shift attention mask
    with a device-less `torch.arange`, i.e. on the CPU, on EVERY forward
    of EVERY shifted layer, and the layer then `.to(device)`s it: for a
    520 px tile that is 4 225 windows x 64 x 64 floats = 69 MB, eighteen
    times a tile — over a gigabyte of host-to-device traffic per tile,
    for a mask that depends on nothing but the padded shape. MEASURED
    (5090 box): about a tenth of a 1200 x 900 picture's time at 512 px
    tiles. On an M4 Max it changes nothing — MPS is bound by its own
    kernels there (a profile with stacks put 96% of the forward in the
    device's linear, bmm and pad kernels: 43 s a megapixel, against 70 on
    the cores; neither SDPA attention nor skipping the no-op pad moved it
    by more than 3%, so Swin2SR on Apple silicon simply is slow, and the
    RRDB net at 3 s a megapixel is the upscaler to use there). The mask's
    VALUES are exactly transformers' (the arithmetic below is its own, on
    the device); the outputs were compared bit for bit on both.
    """
    import types

    import torch
    from transformers.models.swin2sr.modeling_swin2sr import (Swin2SRLayer,
                                                              window_partition)

    def get_attn_mask(self, height, width, dtype):
        if self.shift_size <= 0:
            return None
        dev = self.attention.self.query.weight.device
        key = (self.window_size, self.shift_size, height, width, dtype,
               str(dev))
        mask = _MASKS.get(key)
        if mask is None:
            h_idx = torch.arange(height, device=dev)
            w_idx = torch.arange(width, device=dev)
            h_region = ((h_idx >= height - self.window_size).long()
                        + (h_idx >= height - self.shift_size).long())
            w_region = ((w_idx >= width - self.window_size).long()
                        + (w_idx >= width - self.shift_size).long())
            img_mask = (h_region[None, :, None, None] * 3
                        + w_region[None, None, :, None]).to(dtype)
            mask_windows = window_partition(img_mask, self.window_size)
            mask_windows = mask_windows.view(-1, self.window_size * self.window_size)
            mask = mask_windows.unsqueeze(1) - mask_windows.unsqueeze(2)
            mask = mask.masked_fill(mask != 0, -100.0).masked_fill(mask == 0, 0.0)
            if len(_MASKS) >= _MASKS_MAX:
                _MASKS.clear()
            _MASKS[key] = mask
        return mask

    for layer in model.modules():
        if isinstance(layer, Swin2SRLayer):
            layer.get_attn_mask = types.MethodType(get_attn_mask, layer)


def _half(dev: str) -> bool:  # pragma: no cover - heavy optional dep
    """Reduced precision is OFF for Swin2SR, on every device. MEASURED
    (5090 box): float16 OVERFLOWS in the x2 checkpoint (NaN over the whole
    picture; the x4 ones happen not to), and bfloat16, which has the
    range, has not the mantissa — 13% of a textured picture's pixels move
    more than one 8-bit step (max 74) for a 10-15% speed-up. The model is
    compute-bound in its window attention, which reduced precision barely
    touches. `MEDIA_COMPOST_UPSCALE_HALF=1` forces bfloat16 for a
    measurement."""
    raw = (os.environ.get("MEDIA_COMPOST_UPSCALE_HALF") or "").strip()
    return bool(raw) and raw not in ("0", "false", "no")


#: Swin2SR's window: every tile origin sits on a multiple of it
#: (`_tile.plan`'s grid) and the picture is padded to it first.
_WINDOW = 8


def _pad_to_windows(t, size_divisor: int = _WINDOW):  # pragma: no cover - heavy optional dep
    """`Swin2SRImageProcessor.pad`, on the device: symmetric padding to the
    next multiple of the window size — ALWAYS at least one window, as the
    processor does (`(h // 8 + 1) * 8`), because the model's own reflect
    padding then adds nothing and the two paths stay bit-identical
    (`verify_upscale2.py` compared the tensors). ``t`` is N x 3 x H x W."""
    from torchvision.transforms.v2 import functional as tvF

    h, w = t.shape[-2:]
    ph = (h // size_divisor + 1) * size_divisor - h
    pw = (w // size_divisor + 1) * size_divisor - w
    return tvF.pad(t, [0, 0, pw, ph], padding_mode="symmetric")


def _pad_picture(hwc):  # pragma: no cover - heavy optional dep
    """The WHOLE picture padded as the processor pads it, before tiling
    (H x W x 3 uint8 on the device, in and out): so the picture the tiles
    are cut from — origins on the 8 px grid (`_tile.plan`) — is exactly
    the one the untiled forward sees, and no tile needs padding of its
    own. A tile padded on its own was the 12%-of-pixels defect `_tile.plan`
    describes: its windows started where the tile did, not where the
    picture's do."""
    return _pad_to_windows(hwc.permute(2, 0, 1).unsqueeze(0)).squeeze(0).permute(1, 2, 0)


def _forward(handle):  # pragma: no cover - heavy optional dep
    """A list of same-shaped H x W x 3 uint8 tiles ON THE DEVICE -> their
    upscaled counterparts as uint8 H' x W' x 3 there (`_tile.to_uint8`),
    ONE model call for the list. The processor's work (rescale, symmetric pad
    to a window multiple) is done on the device (`_pad_to_windows`); the
    padding's extra output pixels are cropped back to exactly scale x the
    tile. A full-tile batch may run the compiled network
    (`_tile.LazyCompiled`); a failure there falls back to eager."""
    import torch

    from . import _tile

    model, _proc, dev, _cfg, half = handle[:5]
    lazy = handle[5] if len(handle) > 5 else None
    scale = int(getattr(model.config, "upscale", 2) or 2)

    def forward(tiles):
        h, w = tiles[0].shape[:2]
        with torch.inference_mode():
            x = torch.stack(list(tiles)).permute(0, 3, 1, 2).float().div(255.0)
            if h % _WINDOW or w % _WINDOW:
                # Only a tile size forced off the grid by the environment
                # gets here (`_pad_picture` made the picture a multiple);
                # the model would pad it itself, but by reflection.
                x = _pad_to_windows(x)
            x = x.contiguous()
            net = lazy.pick(tiles) if lazy is not None else model
            with torch.autocast(device_type=dev.split(":")[0],
                                dtype=torch.bfloat16, enabled=half):
                try:
                    out = net(pixel_values=x).reconstruction
                except Exception as exc:  # noqa: BLE001
                    if net is model:
                        raise
                    lazy.give_up(exc)
                    out = model(pixel_values=x).reconstruction
            out = _tile.to_uint8(out[:, :, :h * scale, :w * scale])
        return [out[i] for i in range(out.shape[0])]

    return forward, scale


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    from . import _tile

    tile, overlap, batch = handle[3]
    forward, scale = _forward(handle)
    return {"image": _tile.run_on_device(image, handle[2], scale, forward,
                                         tile, overlap, batch,
                                         grid=_WINDOW, pad=_pad_picture)}
