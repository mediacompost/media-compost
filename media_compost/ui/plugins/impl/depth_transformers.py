"""Monocular depth estimation via the Hugging Face transformers pipeline.

Several depth models share one clean integration — a
``pipeline("depth-estimation")`` per model — since transformers handles Depth
Anything V2, DPT/**MiDaS** and **ZoeDepth** all through the same interface. Each
produces a grayscale depth map (near = bright, far = dark), i.e. exactly the
control image a depth ControlNet expects. Results are stored as an auxiliary
artifact nested under the source file — not a source of the item.

(LeReS lives in its own plugin; it needs the ``controlnet_aux`` preprocessors.)
"""

from __future__ import annotations

import os

# model id -> (HF repo, display name, note, weight file). The source key equals
# the model id. The weight file is per model: MiDaS ships only
# `pytorch_model.bin` where the other two carry `.safetensors`, so one glob
# for all three would either miss MiDaS or fetch both formats of the others.
_MODELS = {
    "depth_anything_v2_small": (
        "depth-anything/Depth-Anything-V2-Small-hf",
        "Depth Anything V2 (Small)",
        "Grayscale monocular depth map (near bright, far dark).",
        "model.safetensors"),
    "dpt_hybrid_midas": (
        "Intel/dpt-hybrid-midas",
        "MiDaS (DPT-Hybrid)",
        "MiDaS depth via the DPT-Hybrid transformer.", "pytorch_model.bin"),
    "zoedepth_nyu_kitti": (
        "Intel/zoedepth-nyu-kitti",
        "ZoeDepth (NYU + KITTI)",
        "Metric depth via ZoeDepth.", "model.safetensors"),
}

try:
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id=mid, task="depth", name=name, family=name, note=note)
            for mid, (_repo, name, note, _w) in _MODELS.items()
        ],
        sources=[
            ModelSource(key=mid, label=name, repo=repo,
                        url=f"https://huggingface.co/{repo}", probe=weights,
                        allow_patterns=TRANSFORMERS_CONFIG_FILES + (weights,))
            for mid, (repo, name, _note, weights) in _MODELS.items()
        ],
        deps=("transformers", "torch"),
        url="https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf",
        source_for_model={mid: mid for mid in _MODELS},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from transformers import pipeline

    # Jobs run offline (weights downloaded first); load only from the local HF
    # cache so a run never hits the network.
    if ctx.get("local_files_only", True):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    repo = ctx["sources"][load_key]      # source key == model id == load_key
    from . import _accel

    dev = _accel.device("MEDIA_COMPOST_DEPTH_DEVICE")   # was CUDA or the CPU: never MPS
    print(f"depth: {load_key} on {dev}", flush=True)
    return pipeline("depth-estimation", model=repo, device=dev)


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    rgb = image.convert("RGB")
    out = handle(rgb)
    # The pipeline returns {"predicted_depth": tensor, "depth": PIL grayscale}.
    depth = out.get("depth") if isinstance(out, dict) else out
    if depth is None:
        return {"image": None}
    return {"image": depth.convert("RGB") if depth.mode != "RGB" else depth}
