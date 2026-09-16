"""LeReS depth estimation (via the controlnet_aux preprocessors).

LeReS isn't in transformers, so it comes from ``controlnet_aux`` — the standard
collection of ControlNet preprocessors — whose weights live in the shared
``lllyasviel/Annotators`` repo. Output is a grayscale depth map, ready as a depth
ControlNet's input. Stored as an auxiliary artifact nested under the source file.
"""

from __future__ import annotations

import os

_PROBE = "res101.pth"     # a LeReS weight file inside lllyasviel/Annotators

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id="leres", task="depth", name="LeReS", family="LeReS",
                      note="LeReS monocular depth (controlnet_aux)."),
        ],
        sources=[
            ModelSource(key="cn_annotators_leres", label="ControlNet annotators (LeReS)",
                        repo="lllyasviel/Annotators",
                        url="https://huggingface.co/lllyasviel/Annotators",
                        probe=_PROBE,
                        # LeresDetector.from_pretrained loads exactly these
                        # two; the repo around them is 10.6 GB of other
                        # people's annotators.
                        allow_patterns=(_PROBE, "latest_net_G.pth")),
        ],
        deps=("controlnet_aux",),
        url="https://huggingface.co/lllyasviel/Annotators",
        source_for_model={"leres": "cn_annotators_leres"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from controlnet_aux import LeresDetector

    if ctx.get("local_files_only", True):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from . import _accel

    det = LeresDetector.from_pretrained(
        ctx["sources"]["cn_annotators_leres"],
        # controlnet_aux defaults this to False and downloads each of
        # its files itself, so without it a job goes to the network —
        # and a wrong `allow_patterns` would be quietly repaired there
        # rather than failing where it can be seen.
        local_files_only=bool(ctx.get("local_files_only", True)))
    # Never named a device before: the cores, everywhere.
    dev = _accel.device("MEDIA_COMPOST_DEPTH_DEVICE")
    try:
        det = det.to(dev)
    except Exception as exc:  # noqa: BLE001 - the CPU always works
        print(f"depth: LeReS cannot run on {dev} ({str(exc)[:100]}); using the CPU", flush=True)
        dev = "cpu"
    print(f"depth: LeReS on {dev}", flush=True)
    return det


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    out = handle(image.convert("RGB"))
    if out is None:
        return {"image": None}
    return {"image": out.convert("RGB") if out.mode != "RGB" else out}
