"""What the spandrel-loaded plugins share: finding the one weight file, and
a tiled forward over the loaded descriptor.

A leading underscore, like `_tile.py`: not a plugin, never in
`registry.PLUGIN_MODULES`. spandrel recognises an architecture from a bare
``.pth`` state dict and hands back a descriptor that knows its own scale,
its input size rules (it pads on call and crops the answer back) and
whether half precision is safe — so one loader and one forward serve the
Real-ESRGAN upscalers (`upscale_esrgan.py`) and the SCUNet cleaner
(`restore_scunet.py`) alike; the plugin keeps only what differs (device
variable, precision rule, the printed line).
"""

from __future__ import annotations

import os


def weights_path(ctx: dict, key: str, filename: str) -> str:  # pragma: no cover - heavy optional dep
    """The local path of ``filename`` for source ``key``: a local-path
    override (a file, or a folder holding the file), else the Hugging Face
    cache (offline unless setup says otherwise)."""
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


def load_descriptor(path: str):  # pragma: no cover - heavy optional dep
    """The spandrel descriptor for a single-image model at ``path``, in eval
    mode; refuses anything that is not one picture in, one picture out."""
    from spandrel import ImageModelDescriptor, ModelLoader

    model = ModelLoader().load_from_file(path)
    if not isinstance(model, ImageModelDescriptor):
        raise RuntimeError("not a single-image model")
    model.eval()
    return model


def forward_fn(model, dev: str, half: bool, lazy=None):  # pragma: no cover - heavy optional dep
    """``(forward, scale)`` for `_tile.run_on_device`: a list of same-shaped
    H x W x 3 uint8 tiles ON THE DEVICE -> uint8 H' x W' x 3 there
    (`_tile.to_uint8`: quantized per tile, so the result buffer is bytes,
    not floats), one model call for the list. ``half`` runs the call under fp16
    autocast; ``lazy`` (a `_tile.LazyCompiled`) may substitute the compiled
    network for a full-tile batch, falling back to eager on any failure."""
    import torch

    from . import _tile

    scale = int(getattr(model, "scale", 1) or 1)

    def forward(tiles):
        with torch.inference_mode():
            t = torch.stack(list(tiles)).permute(0, 3, 1, 2).float().div(255.0)
            t = t.contiguous()
            net = lazy.pick(tiles) if lazy is not None else model
            with torch.autocast(device_type=dev.split(":")[0],
                                dtype=torch.float16, enabled=half):
                try:
                    out = net(t)
                except Exception as exc:  # noqa: BLE001
                    if net is model:
                        raise
                    lazy.give_up(exc)
                    out = model(t)
            out = _tile.to_uint8(out)
        return [out[i] for i in range(out.shape[0])]

    return forward, scale
