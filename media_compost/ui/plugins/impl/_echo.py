"""A dependency-free fake plugin used only by the host/worker tests.

It offers two trivial "caption" models so tests can exercise the ModelHost's
warm-reuse, evict-on-switch and idle-TTL behaviour without any heavy model. Not
listed in the production registry.
"""

from __future__ import annotations

import os

try:  # importable both as a package module (host) and by file path (worker)
    from ..framework import ModelSpec, PluginManifest
    MANIFEST = PluginManifest(models=[
        ModelSpec(id="echo_a", task="caption", name="Echo A", family="Echo"),
        ModelSpec(id="echo_b", task="caption", name="Echo B", family="Echo"),
    ])
except (ImportError, ValueError):  # loaded standalone in a worker
    MANIFEST = None


def load(load_key, ctx):
    # The pid identifies the worker process, so tests can tell a reused warm
    # worker (same pid) from a fresh one after an evict/switch (new pid).
    return {"key": load_key, "pid": os.getpid()}


def load_prep(load_key, ctx):
    # The light handle `prepare` takes — built in every decode process. A
    # pid again, so a test can see the work was done somewhere else.
    return {"prep_pid": os.getpid()}


def prepare(prep_handle, image):
    # The compact per-picture result the batch path hands `run` in place of
    # the picture — a numpy array, as the contract says (it travels through
    # shared memory): the RGBA pixels, plus one trailing row whose first
    # pixel holds the pid of the process that decoded it, so a test can see
    # the work was done somewhere else.
    import numpy as np

    pixels = np.asarray(image.convert("RGBA"))
    tail = np.zeros((1, pixels.shape[1], 4), dtype=np.uint8)
    tail[0, 0] = np.frombuffer(int(prep_handle["prep_pid"]).to_bytes(4, "little"),
                               dtype=np.uint8)
    return np.vstack([pixels, tail])


def _unpack(arr):
    """`prepare`'s array -> (RGBA picture, pid of the decoding process)."""
    from PIL import Image

    pid = int.from_bytes(arr[-1, 0].tobytes(), "little")
    return Image.fromarray(arr[:-1].copy(), "RGBA"), pid


def run(task, model_id, handle, image, options):
    # `bg_removal` hands the IMAGE back, which is the other direction across
    # the wire — the one where a format that cannot hold what it was given
    # loses it silently. Everything else answers with text.
    decoded_in = None
    if not hasattr(image, "convert"):   # `prepare`'s result, on the batch path
        image, decoded_in = _unpack(image)
    if task == "bg_removal":
        return {"image": image}
    if task == "tag":
        return {"tags": [{"name": "echo", "score": 0.9}]}
    if decoded_in is not None:
        w, h = image.size
        return {"text": f"{model_id}|pid={handle['pid']}|{w}x{h}"
                        f"|decoded_in={decoded_in}"}
    return {"text": f"{model_id}|pid={handle['pid']}"}


def run_batch(task, model_id, handle, images, options):
    return [run(task, model_id, handle, im, options) for im in images]
