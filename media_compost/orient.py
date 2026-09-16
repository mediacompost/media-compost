"""Whole-image orientation helpers (the dihedral group of a rectangle).

A file's orientation is described by two fields relative to its item's *first*
source file: ``rotation`` (clockwise degrees, one of 0/90/180/270) and
``mirrored`` (a horizontal flip applied *before* the rotation). Together they
span all eight dihedral orientations — the plain rotations, the horizontal /
vertical flips, and their combinations.

Unlike the old model, this orientation is *baked into the file's stored bytes*
(a rotated source file really holds rotated pixels); these helpers are used to
(a) produce those bytes when the user rotates, and (b) recover the transform
between two images on import so it can be recorded for display.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from PIL import Image, ImageOps

# All eight orientations as (rotation_degrees, mirrored) pairs.
ORIENTATIONS: list[tuple[int, bool]] = [
    (r, m) for m in (False, True) for r in (0, 90, 180, 270)
]


def apply_orientation(im: Image.Image, rotation: int, mirrored: bool) -> Image.Image:
    """Return ``im`` with the given orientation applied to its pixels.

    Mirror horizontally first (if ``mirrored``), then rotate clockwise by
    ``rotation`` degrees. This matches :func:`_apply_arr` used for detection.
    """
    rotation = int(rotation or 0) % 360
    if mirrored:
        im = ImageOps.mirror(im)
    if rotation:
        # PIL rotates counter-clockwise for positive angles; negate for clockwise.
        im = im.rotate(-rotation, expand=True)
    return im


def _apply_arr(a: "np.ndarray", rotation: int, mirrored: bool) -> "np.ndarray":
    if mirrored:
        a = np.fliplr(a)
    k = (-(rotation // 90)) % 4  # np.rot90 positive is CCW; negative k is CW
    if k:
        a = np.rot90(a, k)
    return a


def detect_orientation(
    base: "np.ndarray", other: "np.ndarray", mse_bound: float
) -> Optional[tuple[int, bool]]:
    """The ``(rotation, mirrored)`` that maps ``base`` onto ``other``, or None.

    Both are square grayscale thumbnails (see :func:`media_compost.dedup.canon_thumb`).
    Returns the best-fitting dihedral transform when its mean-squared error is
    within ``mse_bound``; otherwise ``None`` (the images aren't a reorientation
    of each other).
    """
    best: Optional[tuple[int, bool]] = None
    best_mse = float("inf")
    for mirrored in (False, True):
        for rotation in (0, 90, 180, 270):
            cand = _apply_arr(base, rotation, mirrored)
            if cand.shape != other.shape:
                continue
            diff = cand - other
            mse = float(np.mean(diff * diff))
            if mse < best_mse:
                best_mse = mse
                best = (rotation, mirrored)
    if best is None or best_mse > mse_bound:
        return None
    return best
