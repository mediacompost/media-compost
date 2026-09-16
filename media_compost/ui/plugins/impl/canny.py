"""Canny edge control image (OpenCV — no model download).

Classic Canny edge detection producing white edges on a black background: the
control image an edge/Canny ControlNet expects. Needs no weights, so it runs
immediately (OpenCV ships with the ultralytics dependency). Stored as an
auxiliary artifact nested under the source file.
"""

from __future__ import annotations

_LOW = 100
_HIGH = 200

try:
    from ..framework import ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id="canny", task="canny", name="Canny edges",
                      family="Canny edges",
                      note="White edges on black (Canny), for an edge ControlNet."),
        ],
        sources=[],            # no weights to download
        deps=("cv2",),
        url="https://docs.opencv.org/4.x/da/d22/tutorial_py_canny.html",
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - optional dep
    return None              # stateless — no model to hold


def run(task, model_id, handle, image, options):  # pragma: no cover - optional dep
    import cv2
    import numpy as np

    opts = options or {}
    low = int(opts.get("low", _LOW))
    high = int(opts.get("high", _HIGH))
    arr = np.asarray(image.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, low, high)
    from PIL import Image
    return {"image": Image.fromarray(edges).convert("RGB")}
