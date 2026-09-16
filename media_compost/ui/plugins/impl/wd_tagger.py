"""WD Tagger (SmilingWolf) — a Danbooru-style tagger exported to ONNX."""

from __future__ import annotations

import os

_THRESHOLD = 0.35

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[ModelSpec(id="wd_tagger", task="tag", name="WD Tagger",
                          family="WD Tagger", note="SmilingWolf's Danbooru-style tagger.")],
        sources=[ModelSource(key="wd_tagger", label="WD Tagger (ONNX)",
                             repo="SmilingWolf/wd-vit-large-tagger-v3",
                             url="https://huggingface.co/SmilingWolf/wd-vit-large-tagger-v3",
                             onnx=True, probe="model.onnx",
                             # onnxruntime opens model.onnx; the repo also
                             # carries a .safetensors and a .msgpack of the
                             # same weights, which nothing here reads.
                             allow_patterns=("model.onnx", "selected_tags.csv"))],
        deps=("onnxruntime", "numpy"),
        url="https://huggingface.co/SmilingWolf/wd-vit-large-tagger-v3",
        source_for_model={"wd_tagger": "wd_tagger"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import csv
    import onnxruntime as ort

    from . import _ort

    from ..framework import repo_files

    # The two files by name (`repo_files`): a narrowed download is not a
    # snapshot huggingface_hub will hand back offline.
    repo_dir = repo_files(ctx["sources"]["wd_tagger"],
                          ("model.onnx", "selected_tags.csv"), ctx)
    model_path = os.path.join(repo_dir, "model.onnx")
    tags_path = os.path.join(repo_dir, "selected_tags.csv")
    # THE GPU WHERE THERE IS ONE. This used to be `["CPUExecutionProvider"]`,
    # hardcoded: a ViT-L over every picture on the cores of a box with a
    # 5090 in it, 2 items/s with the card at 0%, and nothing anywhere saying
    # why. `_ort.providers` is the face detector's answer, shared.
    providers, _ = _ort.providers()
    sess = ort.InferenceSession(model_path, providers=providers)
    got = _ort.session_providers([sess])
    print(f"tagger: onnxruntime providers {providers}; session runs on "
          f"{got or ['?']}", flush=True)
    if got == ["CPUExecutionProvider"]:
        _ort.say_cpu_only("tagger")
    names: list[str] = []
    cats: list[int] = []
    with open(tags_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            names.append(row["name"])
            cats.append(int(row["category"]))
    return (sess, names, cats)


def _input_size(sess) -> int:  # pragma: no cover - heavy optional dep
    _, size, _, _ = sess.get_inputs()[0].shape
    return int(size) if isinstance(size, int) or str(size).isdigit() else 448


def prepare(handle, image):  # pragma: no cover - heavy optional dep
    """The model's input for ONE picture — padded to a white square,
    resized to its 448, BGR float32 (448, 448, 3) — the worker's
    per-picture hook, beside the decode. It was the plugin's own first
    step on the worker's one thread; a chunk of 32 is 32 pad-and-resizes
    of full-size pictures, and the decode threads (or processes, on CUDA)
    already have the picture in hand."""
    import numpy as np
    from PIL import Image

    size = _input_size(handle[0])
    rgb = image.convert("RGB")
    dim = max(rgb.size)
    canvas = Image.new("RGB", (dim, dim), (255, 255, 255))
    canvas.paste(rgb, ((dim - rgb.width) // 2, (dim - rgb.height) // 2))
    if dim != size:
        canvas = canvas.resize((size, size), Image.BICUBIC)
    return np.ascontiguousarray(
        np.asarray(canvas, dtype=np.float32)[:, :, ::-1])  # RGB -> BGR


def load_prep(load_key, ctx):  # pragma: no cover - heavy optional dep
    """`prepare` needs only the input size; a decode process gets a stand-in
    handle that answers it without loading the 1.2 GB session."""
    class _Input:
        def get_inputs(self):
            class _I:
                shape = ["batch_size", 448, 448, 3]
            return [_I()]
    return (_Input(), [], [])


def wants_decode_processes(handle):  # pragma: no cover - heavy optional dep
    """Processes on a card: the forward is milliseconds a picture batched,
    and the pad-and-resize of a full-size picture is the CPU half — the
    embed plugins' shape. Threads where the forward is the bound."""
    try:
        return handle is None or "CPUExecutionProvider" != (
            handle[0].get_providers() or ["CPUExecutionProvider"])[0]
    except Exception:  # noqa: BLE001
        return False


def _tags_of(handle, preds) -> dict:  # pragma: no cover - heavy optional dep
    _, names, cats = handle
    tags = [{"name": name.replace("_", " "), "box": None}
            for i, name in enumerate(names)
            if cats[i] != 9 and float(preds[i]) >= _THRESHOLD]
    return {"tags": tags}


def run_batch(task, model_id, handle, images, options):  # pragma: no cover - heavy optional dep
    """ONE session run for the chunk: the model takes a batch, and a run's
    overhead on a card is the same for one picture or thirty-two."""
    import numpy as np

    sess = handle[0]
    arr = np.stack([im if isinstance(im, np.ndarray) else prepare(handle, im)
                    for im in images])
    name_in = sess.get_inputs()[0].name
    name_out = sess.get_outputs()[0].name
    preds = sess.run([name_out], {name_in: arr})[0]
    return [_tags_of(handle, p) for p in preds]


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    return run_batch(task, model_id, handle, [image], options)[0]
