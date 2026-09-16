"""The torch-free halves of validation and masked-region training.

The trainer-side pieces that can be tested from the main venv: the cell
arithmetic `loop.LatentSource._box_mask` builds its weight map from
(`compose.box_mask_cells`), and the metrics record a validation round appends
(`JobIO.append_eval`) — the wire the endpoint's merge rule reads. The
torch-dependent composition on top of them is deliberately thin: a ones
tensor with rectangles written into it, and a mean over `train_step` losses.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from media_compost.train.dataset import compose_module
from media_compost.train.paths import TRAIN_SCRIPTS


# ---- box_mask_cells ----------------------------------------------------------


def test_cells_cover_the_box_rounded_outward():
    compose = compose_module()
    # A 64x64-cell frame, no crop: a box in cell terms from (16, 8) to
    # (32, 24). Fractions that land exactly on cell edges stay exact.
    cells = compose.box_mask_cells([[0.25, 0.125, 0.25, 0.25]],
                                   0, 0, 64, 64, 64, 64, 64, 64)
    assert cells == [(16, 8, 32, 24)]
    # A box that half-covers its border cells takes them WHOLE — the mask
    # exists to hide something, and the half-covered cell is where a
    # watermark is most legible.
    cells = compose.box_mask_cells([[0.24, 0.12, 0.25, 0.25]],
                                   0, 0, 64, 64, 64, 64, 64, 64)
    (x0, y0, x1, y1) = cells[0]
    assert x0 <= 15 and x1 >= 32 and y0 <= 7 and y1 >= 24


def test_cells_follow_the_crop():
    compose = compose_module()
    # The cover frame is 96x64 cells and the crop is the right 64x64 window:
    # a box at the frame's centre lands left of the crop's centre.
    cells = compose.box_mask_cells([[0.5, 0.5, 0.25, 0.25]],
                                   32, 0, 64, 64, 96, 64, 64, 64)
    assert cells == [(16, 32, 40, 48)]


def test_a_rectangular_polygon_covers_what_the_rectangle_does():
    """A box row may carry a POLYGON as a conditional fifth element; a
    4-vertex axis-aligned one must claim exactly the cells the plain
    rectangle path claims."""
    compose = compose_module()
    rect = [0.25, 0.125, 0.25, 0.25]
    quad = [[0.25, 0.125], [0.5, 0.125], [0.5, 0.375], [0.25, 0.375]]
    want = compose.box_mask_cells([rect], 0, 0, 64, 64, 64, 64, 64, 64)
    got = compose.box_mask_cells([rect + [quad]],
                                 0, 0, 64, 64, 64, 64, 64, 64)
    covered = {(cx, cy) for (x0, y0, x1, y1) in got
               for cy in range(y0, y1) for cx in range(x0, x1)}
    expect = {(cx, cy) for (x0, y0, x1, y1) in want
              for cy in range(y0, y1) for cx in range(x0, x1)}
    assert covered == expect


def test_a_triangle_masks_the_shape_not_its_bbox():
    compose = compose_module()
    tri = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    cells = compose.box_mask_cells([[0.0, 0.0, 1.0, 1.0, tri]],
                                   0, 0, 16, 16, 16, 16, 16, 16)
    covered = {(cx, cy) for (x0, y0, x1, y1) in cells
               for cy in range(y0, y1) for cx in range(x0, x1)}
    # The whole hypotenuse edge counts (outward rounding) but the far corner
    # does not: the shape, not its bounding box.
    assert (0, 0) in covered and (15, 15) not in covered
    # Roughly half the grid plus the diagonal band of edge cells.
    assert 16 * 16 / 2 <= len(covered) <= 16 * 16 / 2 + 16


def test_flip_boxes_mirrors_the_polygon_with_the_box():
    compose = compose_module()
    tri = [[0.2, 0.2], [0.6, 0.2], [0.4, 0.5]]
    (flipped,) = compose.flip_boxes([[0.2, 0.2, 0.4, 0.3, tri]])
    assert flipped[:4] == [pytest.approx(1.0 - 0.2 - 0.4), 0.2, 0.4, 0.3]
    assert flipped[4] == [[pytest.approx(0.8), 0.2],
                          [pytest.approx(0.4), 0.2],
                          [pytest.approx(0.6), 0.5]]
    # A plain rectangle row stays the bare 4-list it always was.
    (plain,) = compose.flip_boxes([[0.2, 0.2, 0.4, 0.3]])
    assert len(plain) == 4


def test_a_box_the_crop_excludes_yields_nothing():
    compose = compose_module()
    assert compose.box_mask_cells([[0.0, 0.0, 0.2, 0.2]],
                                  60, 60, 64, 64, 128, 128, 64, 64) == []
    # Degenerate crop: nothing rather than a division error.
    assert compose.box_mask_cells([[0.1, 0.1, 0.5, 0.5]],
                                  0, 0, 0, 0, 64, 64, 64, 64) == []


def test_cells_are_clamped_to_the_grid():
    compose = compose_module()
    cells = compose.box_mask_cells([[0.9, 0.9, 0.5, 0.5]],
                                   0, 0, 64, 64, 64, 64, 64, 64)
    assert cells == [(57, 57, 64, 64)]


def test_a_flipped_visit_mirrors_the_boxes_first():
    """The same `flip_boxes` the crop-steering boxes go through — one
    mirroring rule, not a second one."""
    compose = compose_module()
    flipped = compose.flip_boxes([[0.25, 0.125, 0.25, 0.25]])
    cells = compose.box_mask_cells(flipped, 0, 0, 64, 64, 64, 64, 64, 64)
    assert cells == [(32, 8, 48, 24)]


# ---- append_eval -------------------------------------------------------------


def _job_io(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "train_for_eval", TRAIN_SCRIPTS / "train.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.JobIO(tmp_path)


def test_append_eval_writes_a_record_without_a_loss_key(tmp_path: Path):
    """The absence of "loss" is the whole protocol: it is what tells the
    metrics endpoint this is a merge record for the step's training point
    rather than a diverged training step (which writes `"loss": null`)."""
    io = _job_io(tmp_path)
    io.append_metric(2, 0.5, 1e-4)
    io.append_eval(2, {"val": 0.71234567, "stable": 0.3})
    io.append_eval(4, {"val": float("nan")})
    lines = [json.loads(line) for line in
             (tmp_path / "metrics.jsonl").read_text().splitlines()]
    assert "loss" in lines[0]
    assert lines[1]["step"] == 2 and "loss" not in lines[1]
    assert lines[1]["val"] == 0.712346 and lines[1]["stable"] == 0.3
    # Non-finite is null, never a bare NaN token — `append_metric`'s rule.
    assert lines[2]["val"] is None
    text = (tmp_path / "metrics.jsonl").read_text()
    assert "NaN" not in text
