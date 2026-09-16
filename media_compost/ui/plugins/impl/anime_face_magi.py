"""Anime/manga faces, with a character descriptor.

The anime-face YOLOv8 detector finds drawn faces well and says nothing about
who they are, so on its own every face comes back as its own cluster and
naming a character means naming them one picture at a time. This pairs that
detector with **Magi v2's crop embedder** (`ragavsachdeva/magiv2-crop-embedder`,
86M params), which was trained on manga character crops with identity
supervision — so faces of one character group together and the suggestion
machinery starts working for drawn art.

There was a detector-only plugin (`anime_face`) beside this one, offered while
the Magi weights were missing. It is gone: it produced no descriptors, so its
faces could never cluster or be suggested, and a library detected with it had
to be run again to become useful — a menu entry whose only outcome was work to
redo. This is the illustrated-face detector now.

Why this one, measured rather than assumed: on 23 hand-labelled faces from a
real manga library (two characters, 253 pairs), cosine similarity averaged
**0.88 within a character and 0.39 between** them, separating perfectly with a
single threshold. The alternatives are far behind — the Manga Whisperer paper
benchmarks generic CLIP at 0.105 AMI and DINOv2 at 0.070 on this exact task,
against 0.65 for Magi.

**The crop is EXPANDED before embedding.** Magi's own crops are whole
characters, not tight faces, and it reads hair and silhouette as much as
features; handing it the bare face box measured worse (96% vs 100% on the same
pairs). 1.6× around the box's centre is the factor used here, chosen because
the existing `faces.SAME_PERSON` threshold of 0.62 falls inside the separating
band it produces (0.538 … 0.632), so one clustering constant serves this
embedder and InsightFace alike.

It runs in the **magi** environment — the one Magi v3's panel detection already
uses, so the heavy dependency is shared — which is why that env now also
carries ultralytics for the detector half.
"""

from __future__ import annotations

import os

# Kill ultralytics' phone-home before it is ever imported (its import runs an
# is_online() probe and it POSTs analytics on predict). Same guard every other
# YOLO plugin here uses — keep it.
os.environ.setdefault("YOLO_OFFLINE", "true")

_WEIGHT_FILE = "model.pt"
_REPO_PATH = "face_detect_v1.4_s"
_EMBEDDER = "ragavsachdeva/magiv2-crop-embedder"

#: How much wider than the face box to cut before embedding. See the module
#: docstring — this is a measured choice, not a guess.
_CROP_EXPAND = 1.6

try:
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(
                id="anime_face_magi", task="faces",
                # Named for the two models it runs, not for what the second
                # one adds: there is no longer a detector-only variant beside
                # it to be "the one WITH character ID", so the contrast the
                # old name drew was with something that no longer exists.
                name="Illustrated faces (YOLOv8 + Magi)",
                family="Face detection",
                note="Finds faces in illustrated art AND describes who they "
                     "are, so one character's faces cluster together and can "
                     "be named in one go."),
        ],
        sources=[
            ModelSource(
                key="anime_face", label="Anime face detection",
                repo="deepghs/anime_face_detection",
                url="https://huggingface.co/deepghs/anime_face_detection",
                probe=f"{_REPO_PATH}/{_WEIGHT_FILE}",
                # Six detector versions, each in .pt and .onnx — 500 MB for
                # the one 22 MB file this loads.
                allow_patterns=(f"{_REPO_PATH}/{_WEIGHT_FILE}",)),
            ModelSource(
                key="magi_crop_embedder", label="Magi character embedder",
                repo=_EMBEDDER,
                url=f"https://huggingface.co/{_EMBEDDER}",
                probe="model.safetensors",
                allow_patterns=TRANSFORMERS_CONFIG_FILES + ("model.safetensors",)),
        ],
        deps=("torch", "transformers", "ultralytics"),
        env="magi",
        url=f"https://huggingface.co/{_EMBEDDER}",
        source_for_model={"anime_face_magi": "magi_crop_embedder"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def _detector_weight(ctx):  # pragma: no cover - heavy optional dep
    p = ctx["sources"]["anime_face"]
    if p and os.path.isfile(p):
        return p
    if p and os.path.isdir(p):
        cand = os.path.join(p, _REPO_PATH, _WEIGHT_FILE)
        if os.path.isfile(cand):
            return cand
        raise RuntimeError(f"{_REPO_PATH}/{_WEIGHT_FILE} not found in {p}")
    from huggingface_hub import hf_hub_download

    return hf_hub_download(p, f"{_REPO_PATH}/{_WEIGHT_FILE}",
                           local_files_only=bool(ctx.get("local_files_only", True)),
                           token=ctx.get("token") or None)


def _device():  # pragma: no cover - heavy optional dep
    """The accelerator this machine has, or the CPU.

    Both halves of this plugin used to be pinned to the CPU ("the embedder is
    small, the run is a handful of crops per page") — which is true of ONE
    page and false of the job that actually runs it: detecting faces over an
    import is thousands of pages, and on a box with a card in it that ran at
    a tenth of the speed with nothing saying why. The detector is a YOLOv8-s
    and the embedder 86M parameters, so neither is a real collision with a
    training run. `MEDIA_COMPOST_FACES_DEVICE` pins one by hand.
    """
    import torch

    forced = (os.environ.get("MEDIA_COMPOST_FACES_DEVICE") or "").strip()
    if forced:
        return forced
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None \
            and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch
    from transformers import AutoModel
    from ultralytics import YOLO

    try:
        from ultralytics.utils.events import events as _ul_events

        _ul_events.enabled = False
    except Exception:  # noqa: BLE001
        pass

    dev = _device()
    detector = YOLO(_detector_weight(ctx))
    embedder = AutoModel.from_pretrained(
        ctx["sources"].get("magi_crop_embedder") or _EMBEDDER,
        trust_remote_code=True,
        local_files_only=bool(ctx.get("local_files_only", True)),
        token=ctx.get("token") or None,
    ).eval()
    # The embedder's own forward moves its inputs to `self.device`, so this is
    # all it takes; the detector is told per predict (ultralytics resolves the
    # string itself and warns about one it cannot use).
    embedder = embedder.to(dev)
    print(f"faces: illustrated detector + embedder on {dev}", flush=True)
    return {"detector": detector, "embedder": embedder, "torch": torch,
            "device": dev}


def _expanded(image, box, expand=_CROP_EXPAND):
    """The face box widened around its centre, clipped to the picture."""
    W, H = image.size
    x, y, w, h = box
    cx, cy = (x + w / 2) * W, (y + h / 2) * H
    bw, bh = w * W * expand, h * H * expand
    return image.crop((
        int(max(0, cx - bw / 2)), int(max(0, cy - bh / 2)),
        int(min(W, cx + bw / 2)), int(min(H, cy + bh / 2)),
    ))


def _faces_of(res, w, h):  # pragma: no cover - heavy optional dep
    """One detection result -> the face dicts, biggest first (the face a
    picture is about is usually the largest, and the sidebar shows them in
    this order)."""
    out = []
    for box in getattr(res, "boxes", []) or []:
        x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
        out.append({
            "box": [max(0.0, x1 / w), max(0.0, y1 / h),
                    min(1.0, (x2 - x1) / w), min(1.0, (y2 - y1) / h)],
            "score": round(float(box.conf[0]), 4),
        })
    out.sort(key=lambda f: -(f["box"][2] * f["box"][3]))
    return out


def _pixel_values(processor, crops):  # pragma: no cover - heavy optional dep
    """The embedder's own preprocessing — greyscale, a 224 px bilinear
    resize, rescale, ImageNet normalize — done HERE, per crop on threads,
    instead of by its `forward`: that one hands the crops to a slow
    (PIL-backed) `ViTImageProcessor` one at a time on the worker's single
    thread, which was 114 ms of a 250 ms call for 149 crops on the 5090 box
    where the ViT forward itself was 48. Each step is the processor's own
    (PIL BILINEAR, float32 rescale then normalize), so the tensor matches
    its output to 7e-7 — the descriptors are unchanged. Pillow releases the
    GIL for the resize, so eight threads did the same 149 in 16 ms."""
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np
    from PIL import Image

    size = (int(processor.size["width"]), int(processor.size["height"]))
    mean = np.asarray(processor.image_mean, dtype=np.float32)
    std = np.asarray(processor.image_std, dtype=np.float32)
    scale = np.float32(processor.rescale_factor)
    resample = {2: Image.BILINEAR, 3: Image.BICUBIC}.get(
        int(processor.resample), Image.BILINEAR)

    def one(crop):
        im = crop.convert("L").convert("RGB").resize(size, resample)
        x = np.asarray(im).astype(np.float32) * scale
        return ((x - mean) / std).transpose(2, 0, 1)
    if len(crops) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(crops))) as ex:
            arrays = list(ex.map(one, crops))
    else:
        arrays = [one(c) for c in crops]
    return np.stack(arrays)


def _embed_crops(handle, crops):  # pragma: no cover - heavy optional dep
    """The Magi crop embedder over ``crops`` — its `forward`, with the
    preprocessing taken out to `_pixel_values` and the rest exactly as it
    does it (mask ratio 0 for the call, the CLS token of the last state)."""
    torch = handle["torch"]
    emb = handle["embedder"]
    inner = getattr(emb, "crop_embedding_model", None)
    proc = getattr(emb, "processor", None)
    if inner is None or proc is None:
        # A build of the embedder shaped differently: its own forward.
        return emb(crops)
    pixels = torch.from_numpy(_pixel_values(proc, crops))
    pixels = pixels.to(next(inner.parameters()).device).to(emb.dtype)
    cfg = inner.embeddings.config
    old_ratio = cfg.mask_ratio
    cfg.mask_ratio = 0.0
    try:
        out = []
        for i in range(0, len(pixels), 256):
            out.append(inner(pixels[i:i + 256]).last_hidden_state[:, 0])
        return torch.cat(out, dim=0)
    finally:
        cfg.mask_ratio = old_ratio


def prepare(handle, image):  # pragma: no cover - heavy optional dep
    """The worker's per-picture hook, beside the decode: the RGB picture the
    detector and the crops read. A 2048 px `convert` is ~3 ms of the
    worker's one thread per picture — 24 of a 68 ms chunk of eight."""
    return image.convert("RGB")


def wants_decode_processes(handle):  # pragma: no cover - heavy optional dep
    """Threads: Pillow's convert releases the GIL, and the result is a
    picture, not the array the process path carries."""
    return False


def _detect_and_embed(handle, images, options):  # pragma: no cover - heavy dep
    """Faces as ``[{"box", "score", "embedding"}]`` per image — the shape
    ``jobs._apply_faces`` reconciles, with the descriptor filled in.

    ONE detector call and ONE embedder call for the whole list, whatever it
    holds: both models are far more efficient over a batch than over a page
    at a time, and a batch job hands this eight pages at once.
    """
    torch = handle["torch"]
    conf = float((options or {}).get("min_confidence") or 0.25)
    # `prepare` handed over RGB already on the batch path; a picture from
    # the single-item path is converted here.
    rgbs = [im if im.mode == "RGB" else im.convert("RGB") for im in images]
    sizes = [im.size for im in rgbs]
    usable = [i for i, (w, h) in enumerate(sizes) if w and h]
    per_image: list[list] = [[] for _ in rgbs]
    if not usable:
        return per_image
    results = handle["detector"].predict(
        [rgbs[i] for i in usable], conf=conf, verbose=False,
        device=handle.get("device") or None)
    for i, res in zip(usable, results):
        per_image[i] = _faces_of(res, *sizes[i])

    # Every crop of every picture through the embedder together — it batches
    # internally, so the cost of asking once per page is the call, not the
    # forward.
    crops, owners = [], []
    for i, faces in enumerate(per_image):
        for face in faces:
            crops.append(_expanded(rgbs[i], face["box"]))
            owners.append(face)
    if crops:
        with torch.no_grad():
            vectors = _embed_crops(handle, crops)
            # Unit length, because everything downstream compares by cosine.
            vectors = torch.nn.functional.normalize(vectors, dim=-1)
        # Off the accelerator ONCE: `float(v)` on a live cuda tensor is a
        # synchronising copy per element.
        for face, vec in zip(owners, vectors.cpu().tolist()):
            face["embedding"] = [round(float(v), 6) for v in vec]
    return per_image


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy dep
    return _detect_and_embed(handle, [image], options)[0]


def run_batch(task, model_id, handle, images, options):  # pragma: no cover - heavy dep
    return _detect_and_embed(handle, list(images), options)
