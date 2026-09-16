"""Orientation helpers: detection recovers what application produced."""

from __future__ import annotations

import numpy as np
from PIL import Image

from media_compost import orient
from media_compost.dedup import canon_thumb


def _thumb(im: Image.Image) -> np.ndarray:
    return canon_thumb(im)


def test_apply_then_detect_round_trips_all_orientations():
    # An asymmetric image so every orientation is distinguishable.
    base = Image.new("RGB", (60, 40), (10, 10, 10))
    base.paste((240, 30, 30), (0, 0, 20, 12))       # corner marker
    base.paste((30, 30, 240), (48, 30, 60, 40))     # opposite corner marker
    bt = _thumb(base)
    for rotation, mirrored in orient.ORIENTATIONS:
        other = orient.apply_orientation(base, rotation, mirrored)
        found = orient.detect_orientation(bt, _thumb(other), 0.02)
        assert found == (rotation, mirrored), f"{rotation},{mirrored} -> {found}"


def test_detect_returns_none_for_unrelated_images():
    a = Image.new("RGB", (40, 40), (0, 0, 0))
    a.paste((255, 255, 255), (0, 0, 20, 40))
    b = Image.new("RGB", (40, 40), (120, 120, 120))
    b.paste((0, 0, 0), (10, 10, 30, 30))
    assert orient.detect_orientation(_thumb(a), _thumb(b), 0.02) is None
