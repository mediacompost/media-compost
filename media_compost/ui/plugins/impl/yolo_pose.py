"""Human pose → an OpenPose control image (for pose ControlNets).

Ultralytics' pose model (``yolo11n-pose.pt``) detects people and their COCO-17
body keypoints; this plugin renders them in the canonical **OpenPose** style — a
colored 18-point skeleton on a black background — which is exactly the control
image a pose ControlNet expects for image generation. Ultralytics is already the
watermark plugin's dependency, so this runs locally with no extra setup. When no
person is found the run produces nothing (a warning, no artifact).

For the higher-fidelity OpenPose (with hands and face), see the separate
``openpose`` plugin (controlnet_aux).
"""

from __future__ import annotations

import os

# Disable ultralytics' network activity before it is ever imported (its import
# runs an is_online() probe and it POSTs anonymized analytics on predict). Same
# guard the watermark plugin uses — keep it.
os.environ.setdefault("YOLO_OFFLINE", "true")

_POSE_FILE = "yolo11n-pose.pt"

# OpenPose 18-keypoint skeleton (limb pairs, 0-indexed) and its canonical colors,
# matching controlnet_aux's draw_bodypose so the output looks like a standard
# OpenPose control image. Keypoint order: 0 nose, 1 neck, 2 R-shoulder, 3 R-elbow,
# 4 R-wrist, 5 L-shoulder, 6 L-elbow, 7 L-wrist, 8 R-hip, 9 R-knee, 10 R-ankle,
# 11 L-hip, 12 L-knee, 13 L-ankle, 14 R-eye, 15 L-eye, 16 R-ear, 17 L-ear.
_LIMBS = [
    (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10),
    (1, 11), (11, 12), (12, 13), (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
]
_COLORS = [
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0),
    (85, 255, 0), (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255),
    (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255),
    (255, 0, 255), (255, 0, 170), (255, 0, 85),
]
# COCO-17 (ultralytics) index for each of the 18 OpenPose keypoints; the neck
# (index 1) has no COCO keypoint and is synthesized from the two shoulders.
_COCO_FOR_OP = [0, None, 6, 8, 10, 5, 7, 9, 12, 14, 16, 11, 13, 15, 2, 1, 4, 3]

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(
                id="yolo11n_pose", task="pose",
                name="OpenPose (YOLO11)", family="OpenPose (YOLO11)",
                note="18-point OpenPose skeleton on black, for a pose ControlNet."),
        ],
        sources=[
            ModelSource(
                key="yolo11n_pose", label="YOLO11 pose",
                repo="Ultralytics/YOLO11",
                url="https://huggingface.co/Ultralytics/YOLO11",
                probe=_POSE_FILE,
                # The repo holds fifteen YOLO11 checkpoints (728 MB); this
                # plugin opens one of 6 MB.
                allow_patterns=(_POSE_FILE,)),
        ],
        deps=("ultralytics",),
        url="https://huggingface.co/Ultralytics/YOLO11",
        source_for_model={"yolo11n_pose": "yolo11n_pose"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def _weight(ctx):  # pragma: no cover - heavy optional dep
    p = ctx["sources"]["yolo11n_pose"]
    if p and os.path.isfile(p):
        return p
    if p and os.path.isdir(p):
        cand = os.path.join(p, _POSE_FILE)
        if os.path.isfile(cand):
            return cand
        raise RuntimeError(f"{_POSE_FILE} not found in {p}")
    from huggingface_hub import hf_hub_download
    return hf_hub_download(p, _POSE_FILE,
                           local_files_only=bool(ctx.get("local_files_only", True)),
                           token=ctx.get("token") or None)


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from ultralytics import YOLO

    try:
        from ultralytics.utils.events import events as _ul_events
        _ul_events.enabled = False
    except Exception:  # noqa: BLE001
        pass
    from . import _accel

    dev = _accel.device("MEDIA_COMPOST_POSE_DEVICE")   # ultralytics picks CUDA by itself, never MPS
    if dev == "mps" and not (os.environ.get("MEDIA_COMPOST_POSE_DEVICE") or "").strip():
        # NOT MPS FOR A NANO MODEL: YOLO11n-pose is a few milliseconds of
        # work, and MPS's dispatch costs more than that — 62 ms a picture
        # median against 43 on an M4 Max's cores, 2.8 items/s against 4.9
        # over a job (measured). A card is another matter; so is a pin.
        dev = "cpu"
    print(f"pose: YOLO11 on {dev}", flush=True)
    return (YOLO(_weight(ctx)), dev)


def _to_openpose(coco):
    """Map one person's COCO-17 (x, y, conf) rows to 18 OpenPose (x, y, conf)."""
    op = []
    for src in _COCO_FOR_OP:
        if src is None:  # neck = midpoint of the two shoulders (COCO 5 & 6)
            ls, rs = coco[5], coco[6]
            if ls[2] > 0.3 and rs[2] > 0.3:
                op.append(((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2, min(ls[2], rs[2])))
            else:
                op.append((0.0, 0.0, 0.0))
        else:
            op.append((coco[src][0], coco[src][1], coco[src][2]))
    return op


def _draw_openpose(size, people):  # pragma: no cover - heavy optional dep
    """Render an OpenPose skeleton (colored limbs + joints on black)."""
    from PIL import Image, ImageDraw

    w, h = size
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    stick = max(3, round(min(w, h) / 180))
    r = max(2, round(stick * 0.9))
    for person in people:
        op = _to_openpose(person)
        for i, (a, b) in enumerate(_LIMBS):
            pa, pb = op[a], op[b]
            if pa[2] > 0.3 and pb[2] > 0.3:
                draw.line([(pa[0], pa[1]), (pb[0], pb[1])], fill=_COLORS[i], width=stick)
        for i, (x, y, c) in enumerate(op):
            if c > 0.3:
                draw.ellipse([x - r, y - r, x + r, y + r], fill=_COLORS[i])
    return canvas


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    yolo, dev = handle
    rgb = image.convert("RGB")
    res = yolo.predict(rgb, verbose=False, device=dev)
    if not res:
        return {"image": None}
    r = res[0]
    kpts = getattr(r, "keypoints", None)
    data = getattr(kpts, "data", None) if kpts is not None else None
    if data is None or len(data) == 0:
        return {"image": None}  # no person detected
    people = [[tuple(float(v) for v in row) for row in person] for person in data.tolist()]
    # Keep only people that actually have some visible keypoints.
    people = [p for p in people if any(kp[2] > 0.3 for kp in p)]
    if not people:
        return {"image": None}
    return {"image": _draw_openpose(rgb.size, people)}
