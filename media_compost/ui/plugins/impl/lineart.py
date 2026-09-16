"""Line-art control image (via controlnet_aux).

A neural line-art estimator from ``controlnet_aux`` (weights in the shared
``lllyasviel/Annotators`` repo): clean line drawing extracted from the image, the
control input for a lineart ControlNet. Stored as an auxiliary artifact nested
under the source file.
"""

from __future__ import annotations

import os

_PROBE = "sk_model.pth"      # a lineart weight file inside lllyasviel/Annotators

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id="lineart", task="lineart", name="Line art",
                      family="Line art",
                      note="Neural line drawing, for a lineart ControlNet."),
        ],
        sources=[
            ModelSource(key="cn_annotators_lineart",
                        label="ControlNet annotators (line art)",
                        repo="lllyasviel/Annotators",
                        url="https://huggingface.co/lllyasviel/Annotators",
                        probe=_PROBE,
                        # LineartDetector.from_pretrained loads the fine
                        # model and the coarse one.
                        allow_patterns=(_PROBE, "sk_model2.pth")),
        ],
        deps=("controlnet_aux",),
        url="https://huggingface.co/lllyasviel/Annotators",
        source_for_model={"lineart": "cn_annotators_lineart"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from controlnet_aux import LineartDetector

    if ctx.get("local_files_only", True):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    return LineartDetector.from_pretrained(
        ctx["sources"]["cn_annotators_lineart"],
        # controlnet_aux defaults this to False and downloads each of
        # its files itself, so without it a job goes to the network —
        # and a wrong `allow_patterns` would be quietly repaired there
        # rather than failing where it can be seen.
        local_files_only=bool(ctx.get("local_files_only", True)))


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    out = handle(image.convert("RGB"))
    if out is None:
        return {"image": None}
    return {"image": out.convert("RGB") if out.mode != "RGB" else out}
