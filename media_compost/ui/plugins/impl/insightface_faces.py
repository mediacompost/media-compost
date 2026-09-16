"""Face detection and recognition for photographs (InsightFace buffalo_l).

SCRFD finds the faces, ArcFace describes them. The descriptor is what makes the
rest of the feature work: suggestions ("Alice? · 87%") and the unnamed-faces
clustering that lets one click name fourteen pictures. Descriptors never leave
the machine — they are stored as bytes on the face row and compared locally.

Runs on **onnxruntime**, not torch, so it installs small and stays out of the
way of the training environment.

For drawn art use the ``anime_face_magi`` plugin instead: a photographic model finds
almost nothing in illustrations, and this library is mostly illustrations.
"""

from __future__ import annotations


try:
    from ..framework import ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(
                id="insightface_buffalo_l", task="faces",
                name="Photographic faces (InsightFace)",
                family="Face detection",
                note="Finds faces in photographs and describes them, which is "
                     "what powers name suggestions and clustering."),
        ],
        # No HF source: the pack downloads itself from InsightFace's own release
        # on first load, so readiness is just "are the packages importable".
        sources=[],
        deps=("insightface", "onnxruntime"),
        url="https://github.com/deepinsight/insightface",
    )
except (ImportError, ValueError):
    MANIFEST = None


# The buffalo_l pack is a zip on InsightFace's own GitHub release, not a HF
# repo — the library fetches it into ~/.insightface on first use. That is a
# multi-minute surprise in the middle of the first detection run, so the two
# hooks below let the Settings page report it and fetch it up front.
_PACK = "buffalo_l"


def weights_dir():
    from pathlib import Path

    return Path.home() / ".insightface" / "models" / _PACK


def weights_ready() -> bool:
    """Whether the pack is already unpacked on disk. Import-free: the Settings
    page asks this on every poll, long before the packages are installed."""
    d = weights_dir()
    return d.is_dir() and any(d.glob("*.onnx"))


def fetch_weights() -> None:  # pragma: no cover - network
    """Download and unpack buffalo_l, using InsightFace's own downloader so the
    layout is exactly what `FaceAnalysis` expects to find."""
    from insightface.utils import storage

    storage.ensure_available("models", _PACK)
    if not weights_ready():
        raise RuntimeError(f"{_PACK} did not land in {weights_dir()}")


def _providers():  # pragma: no cover - heavy optional dep
    """(providers, ctx_id) for this machine — `_ort.providers`, shared with
    the tagger. BOTH halves are needed: insightface forwards `providers` to
    every session it opens, and then `prepare(ctx_id)` RESETS them to the
    CPU provider whenever `ctx_id < 0` — so the id alone, or the list alone,
    silently leaves the run on the CPU."""
    from . import _ort

    return _ort.providers()


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from insightface.app import FaceAnalysis

    providers, ctx_id = _providers()
    # DETECTION AND RECOGNITION ONLY. The pack holds five models and
    # `FaceAnalysis` runs every one of them on every face `get()` finds —
    # 2D and 3D landmarks and gender/age among them — and nothing here reads
    # those three: the descriptor is aligned on the DETECTOR's five keypoints
    # (`ArcFaceONNX.get` uses `face.kps`), so leaving them out changes no
    # vector and no box. Measured in-process on this machine: identical
    # embeddings, and the per-image `get()` about a third faster on the CPU.
    app = FaceAnalysis(name="buffalo_l", providers=providers,
                       allowed_modules=["detection", "recognition"])
    # det_size is the detector's working resolution, not the image's; 640 is the
    # pack's own default and finds faces down to a few dozen pixels.
    app.prepare(ctx_id=ctx_id, det_size=(640, 640))
    # Say which one, in the job log: "is it on the GPU" is exactly the
    # question this plugin could not answer before — and say what the
    # SESSIONS got, not what was asked for: a provider that fails to load
    # (its CUDA libraries missing from the loader path) leaves the session
    # on the CPU with the requested list still reading "CUDA".
    from . import _ort

    got = _ort.session_providers(
        getattr(m, "session", None) for m in app.models.values())
    print(f"faces: onnxruntime providers {providers}; sessions run on "
          f"{got or ['?']}", flush=True)
    if ctx_id < 0 or got == ["CPUExecutionProvider"]:
        _ort.say_cpu_only("faces")
    return app


def prepare(handle, image):  # pragma: no cover - heavy dep
    """The worker's per-picture hook, beside the decode: the contiguous BGR
    array `_detect` works on. A 2048 px conversion is ~3 ms of the worker's
    one thread per picture; on the decode threads it is nobody's."""
    import cv2
    import numpy as np

    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def wants_decode_processes(handle):  # pragma: no cover - heavy dep
    """Threads: the conversion releases the GIL, and a 12 MB array per
    picture is not worth a pool of interpreters importing onnxruntime."""
    return False


def _detect(handle, image, minimum: float):  # pragma: no cover - heavy dep
    """One picture's faces, boxes as fractions of the frame, plus the
    ALIGNED 112 px crop of each for the descriptor — `FaceAnalysis.get`
    taken apart so the chunk's descriptors can go through the recognition
    model in ONE call (`run_batch`).

    A CONTIGUOUS BGR array, not the `[:, :, ::-1]` view: every OpenCV call
    downstream (the detector's letterbox resize, one `warpAffine` per face)
    copies a non-contiguous 2048 px picture first, and that copy was most
    of what a face cost — 15 ms a picture in alignment alone, measured on
    the 5090 box, against 1 ms with the array laid out once here.
    """
    import cv2
    import numpy as np
    from insightface.utils import face_align

    arr = image if isinstance(image, np.ndarray) else prepare(handle, image)
    h, w = arr.shape[:2]
    if not w or not h:
        return []
    det = handle.models["detection"]
    rec = handle.models.get("recognition")
    bboxes, kpss = det.detect(arr, max_num=0, metric="default")
    out = []
    for k in range(bboxes.shape[0]):
        x1, y1, x2, y2, score = (float(v) for v in bboxes[k])
        if score < minimum:
            continue
        crop = None
        if rec is not None and kpss is not None:
            crop = face_align.norm_crop(arr, landmark=kpss[k],
                                        image_size=rec.input_size[0])
        out.append({
            "box": [max(0.0, x1 / w), max(0.0, y1 / h),
                    min(1.0, (x2 - x1) / w), min(1.0, (y2 - y1) / h)],
            "score": round(score, 4),
            "embedding": None,
            "_crop": crop,
        })
    out.sort(key=lambda f: -(f["box"][2] * f["box"][3]))
    return out


def _describe(handle, faces: list) -> None:  # pragma: no cover - heavy dep
    """The descriptors for every face of a chunk in ONE recognition call,
    unit-normalized (what `Face.normed_embedding` is: the raw feature over
    its norm). `get()` ran the recognition session once per face — 36 ms
    for 19 faces against 19 batched, measured on the 5090 box — and a
    session run's overhead is the same on a card whether it holds one crop
    or forty."""
    import numpy as np

    rec = handle.models.get("recognition")
    with_crop = [f for f in faces if f.get("_crop") is not None]
    if rec is not None and with_crop:
        feats = np.asarray(rec.get_feat([f["_crop"] for f in with_crop]),
                           dtype=np.float32)
        feats = feats.reshape(len(with_crop), -1)
        for f, feat in zip(with_crop, feats):
            norm = float(np.linalg.norm(feat))
            f["embedding"] = [float(v) for v in (feat / norm if norm else feat)]
    for f in faces:
        f.pop("_crop", None)


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy dep
    """Faces as ``[{"box": [x, y, w, h], "score": float, "embedding": [...]}]``,
    boxes as fractions of the frame."""
    return run_batch(task, model_id, handle, [image], options)[0]


def run_batch(task, model_id, handle, images, options):  # pragma: no cover - heavy dep
    """Every picture's faces, detected one picture at a time (SCRFD takes
    one letterboxed frame), described together (`_describe`)."""
    minimum = float((options or {}).get("min_confidence") or 0.0)
    per_image = [_detect(handle, im, minimum) for im in images]
    _describe(handle, [f for faces in per_image for f in faces])
    return per_image
