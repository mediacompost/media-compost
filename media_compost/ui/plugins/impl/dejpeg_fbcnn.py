"""JPEG / compression-artifact removal with FBCNN, via spandrel.

FBCNN — "Towards Flexible Blind JPEG Artifacts Removal" (ICCV 2021) — restores a
compressed image *at its original resolution*, smoothing out block/ringing
artifacts while keeping detail. Unlike upscaling, the output size matches the
input, so this is a distinct "Remove artifacts" action.

The weights are a bare ``.pth`` (no transformers config), so they load with
**spandrel** (which recognises the FBCNN architecture from the state dict) —
exactly like the anime upscaler (``upscale_esrgan.py``). Declared as an optional
dependency, so the model shows as needing **Set up** until ``spandrel`` is
installed. The restored result is added as a new source file (or a linked new
item with the toggle).
"""

from __future__ import annotations

import os

# The weights live in a large multi-model comfyui mirror; fetch just this file.
_REPO_PATH = "fbcnn/fbcnn_color.pth"

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id="fbcnn_color", task="restore",
                      name="FBCNN (JPEG artifact removal)",
                      family="FBCNN (JPEG artifact removal)",
                      note="Removes JPEG block/ringing artifacts at the original size."),
        ],
        sources=[
            # `fofr/comfyui` is a grab-bag of ComfyUI checkpoints rather than
            # anything of FBCNN's — the file it holds is the standard
            # `fbcnn_color.pth`, and this is simply where a copy is reachable.
            # If it ever goes away, the local-path override takes your own.
            ModelSource(key="fbcnn_color",
                        label="FBCNN color (JPEG artifact removal)",
                        repo="fofr/comfyui",
                        url="https://github.com/jiaxi-jiang/FBCNN",
                        probe=_REPO_PATH,
                        allow_patterns=(_REPO_PATH,)),
        ],
        deps=("spandrel",),
        url="https://github.com/jiaxi-jiang/FBCNN",
        source_for_model={"fbcnn_color": "fbcnn_color"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def _weights(ctx):  # pragma: no cover - heavy optional dep
    p = ctx["sources"]["fbcnn_color"]
    if p and os.path.isfile(p):
        return p
    if p and os.path.isdir(p):
        cand = os.path.join(p, os.path.basename(_REPO_PATH))
        if os.path.isfile(cand):
            return cand
        raise RuntimeError(f"{os.path.basename(_REPO_PATH)} not found in {p}")
    from huggingface_hub import hf_hub_download
    return hf_hub_download(p, _REPO_PATH,
                           local_files_only=bool(ctx.get("local_files_only", True)),
                           token=ctx.get("token") or None)


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch
    from spandrel import ImageModelDescriptor, ModelLoader

    if ctx.get("local_files_only", True):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    model = ModelLoader().load_from_file(_weights(ctx))
    if not isinstance(model, ImageModelDescriptor):
        raise RuntimeError("not a single-image restoration model")
    model.eval()
    if torch.cuda.is_available():
        model.cuda()
    return model


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import numpy as np
    import torch
    from PIL import Image

    model = handle
    rgb = image.convert("RGB")
    arr = np.asarray(rgb).astype("float32") / 255.0
    t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)   # 1,3,H,W
    if torch.cuda.is_available():
        t = t.cuda()
    with torch.no_grad():
        out = model(t)
    out = out.squeeze(0).permute(1, 2, 0).clamp(0, 1).cpu().numpy()
    return {"image": Image.fromarray((out * 255.0).round().astype("uint8"))}
