"""OpenPose control image with hands and face (via controlnet_aux).

The canonical OpenPose preprocessor from ``controlnet_aux`` (weights in the
shared ``lllyasviel/Annotators`` repo) — a colored body skeleton plus optional
hand and face keypoints on a black background, the higher-fidelity input for a
pose ControlNet. Stored as an auxiliary artifact nested under the source file.

For a dependency-free pose (body only, rendered from YOLO11 keypoints) see the
``yolo_pose`` plugin.
"""

from __future__ import annotations

import os

_PROBE = "body_pose_model.pth"    # an OpenPose weight file in lllyasviel/Annotators

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id="openpose_full", task="pose",
                      name="OpenPose (body + hands + face)",
                      family="OpenPose (body + hands + face)",
                      note="Canonical OpenPose control image (controlnet_aux)."),
        ],
        sources=[
            ModelSource(key="cn_annotators_openpose",
                        label="ControlNet annotators (OpenPose)",
                        repo="lllyasviel/Annotators",
                        url="https://huggingface.co/lllyasviel/Annotators",
                        probe=_PROBE,
                        # OpenposeDetector.from_pretrained loads a body, a
                        # hand and a face model — all three, always.
                        allow_patterns=(_PROBE, "hand_pose_model.pth",
                                        "facenet.pth")),
        ],
        deps=("controlnet_aux",),
        url="https://huggingface.co/lllyasviel/Annotators",
        source_for_model={"openpose_full": "cn_annotators_openpose"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from controlnet_aux import OpenposeDetector

    if ctx.get("local_files_only", True):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from . import _accel

    det = OpenposeDetector.from_pretrained(
        ctx["sources"]["cn_annotators_openpose"],
        # controlnet_aux defaults this to False and downloads each of
        # its files itself, so without it a job goes to the network —
        # and a wrong `allow_patterns` would be quietly repaired there
        # rather than failing where it can be seen.
        local_files_only=bool(ctx.get("local_files_only", True)))
    # Never named a device before: the cores, everywhere.
    dev = _accel.device("MEDIA_COMPOST_POSE_DEVICE")
    try:
        det = det.to(dev)
    except Exception as exc:  # noqa: BLE001 - the CPU always works
        print(f"pose: OpenPose cannot run on {dev} ({str(exc)[:100]}); using the CPU", flush=True)
        dev = "cpu"
    print(f"pose: OpenPose on {dev}", flush=True)
    return det


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    # include_body defaults on; hands + face add the extra keypoints.
    out = handle(image.convert("RGB"), hand_and_face=True)
    if out is None:
        return {"image": None}
    return {"image": out.convert("RGB") if out.mode != "RGB" else out}
