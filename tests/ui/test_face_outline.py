"""The FACE OUTLINE — the whole figure, drawn by hand around a face.

`ItemSubjectBox`'s shape one level down (`FaceOutline`): at most one per
face, rectangle or polygon (the bbox invariant), logged and revertible, on
the sidecar, and standing in for the face box in crop-aware training's
fallback chain wherever a subject attached to the face has no subject box of
its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.testing import make_image
from media_compost.ui.config import UiConfig
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

TRI = [[0.2, 0.2], [0.6, 0.2], [0.4, 0.8]]


def near(pts, want, tol=1e-4):
    assert pts is not None and len(pts) == len(want), (pts, want)
    for got, exp in zip(pts, want):
        for g, e in zip(got, exp):
            assert abs(g - e) <= tol, (pts, want)


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "p0.png", seed=0, size=(220, 160))
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([src], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib
        yield c
    app.dependency_overrides.clear()


def _face(client) -> tuple[int, int]:
    """A hand-drawn, named face — (item_id, face_id)."""
    item = client.get("/api/items").json()["items"][0]["id"]
    rows = client.post("/api/faces", json={
        "item_id": item, "x": 0.3, "y": 0.3, "w": 0.1, "h": 0.1}).json()
    fid = rows[0]["id"]
    client.post(f"/api/faces/{fid}/subject",
                json={"display_name": "Alice"})
    return item, fid


def _out(client, item: int, fid: int):
    rows = client.get(f"/api/faces/item/{item}").json()
    row = next(r for r in rows if r["id"] == fid)
    return row.get("outline"), row.get("outline_points")


def _revert_last(client, action: str):
    ev = client.get("/api/history").json()["events"][0]
    assert ev["action"] == action, ev
    r = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.status_code == 200, r.text


def test_draw_replace_clear_and_every_revert(client):
    item, fid = _face(client)
    # DRAW a polygon: the rectangle is its bounding box, server-derived.
    r = client.put(f"/api/faces/{fid}/outline",
                   json={"x": 0, "y": 0, "w": 0, "h": 0, "points": TRI})
    assert r.status_code == 200, r.text
    box, pts = _out(client, item, fid)
    assert box == pytest.approx([0.2, 0.2, 0.4, 0.6])
    near(pts, TRI)
    # REPLACE with a plain rectangle; the revert restores the polygon.
    client.put(f"/api/faces/{fid}/outline",
               json={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5})
    box, pts = _out(client, item, fid)
    assert pts is None and box == pytest.approx([0.1, 0.1, 0.5, 0.5])
    _revert_last(client, "set_face_outline")
    box, pts = _out(client, item, fid)
    near(pts, TRI)
    # CLEAR; the revert restores the rectangle it took down.
    client.delete(f"/api/faces/{fid}/outline")
    box, pts = _out(client, item, fid)
    assert box is None
    _revert_last(client, "set_face_outline")
    box, pts = _out(client, item, fid)
    near(pts, TRI)
    # And reverting the original DRAW takes it down again.
    evs = client.get("/api/history").json()["events"]
    first = next(e for e in evs if e["action"] == "set_face_outline"
                 and e["data"].get("old") is None)
    client.post("/api/history/revert", json={"event_ids": [first["id"]]})
    box, pts = _out(client, item, fid)
    assert box is None


def test_the_outline_rides_the_sidecar(client, tmp_path):
    from media_compost import open_library

    item, fid = _face(client)
    client.put(f"/api/faces/{fid}/outline",
               json={"x": 0, "y": 0, "w": 0, "h": 0, "points": TRI})

    with open_library(tmp_path / "restored", source="cli") as fresh:
        stats = fresh.merge_library(tmp_path / "data")
        assert not stats.errors, stats.errors
        outlines = [(f.outline, f.outline_points)
                    for it in fresh.query(None, show_hidden=True)
                    for f in it.faces if f.outline is not None]
        assert len(outlines) == 1
        rect, pts = outlines[0]
        assert (round(rect.x, 3), round(rect.w, 3)) == (0.2, 0.4)
        near(pts, TRI)


def test_training_prefers_the_outline_over_the_face_box(client, tmp_path):
    """`dataset._tag_boxes`' fallback chain: a subject on the face with no
    subject box of its own uses the face's OUTLINE, not its head box — and
    the polygon rides the manifest row."""
    from media_compost import open_library
    from media_compost.train.dataset import build_manifest
    from media_compost.train.spec import DatasetQuery, TrainingConfig

    item, fid = _face(client)
    client.put(f"/api/faces/{fid}/outline",
               json={"x": 0, "y": 0, "w": 0, "h": 0, "points": TRI})
    cfg = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)])
    config = cfg.model_dump(mode="json")
    config["buckets"]["skip_upscale"] = False
    lib = client.lib
    with open_library(lib.config.data_dir, source="cli") as handle:
        m = build_manifest(handle, config, tmp_path / "job")
    tag = client.get(f"/api/items/{item}").json()["subjects"][0]["tag"]
    entry = next(e for e in m["items"] if e.get("boxes", {}).get(tag))
    (row,) = entry["boxes"][tag]
    # The outline's bbox, not the 0.1-wide face box.
    assert row[2] == pytest.approx(0.4, abs=0.01)
    assert len(row) == 5  # the polygon rides as the fifth element
