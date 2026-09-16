"""POLYGON outlines on tag boxes and subject boxes (`ItemTagBox.points`).

The invariant this file pins from every side: while `points` is set, the four
rectangle columns HOLD the polygon's bounding box — the server derives it, so
every rectangle reader (training crops, indicators, QuickLook) stays correct
without knowing polygons exist. A rect-only edit of a polygon box transforms
the vertices with the rectangle (the annotator's box-mode bbox handles), the
polygon rides the history snapshots and the sidecar, and the manifest's box
rows carry it as a conditional fifth element.
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

TRI = [[0.2, 0.2], [0.6, 0.2], [0.4, 0.5]]


def near(pts, want, tol=1e-4):
    """Nested pair lists, compared value-wise (pytest.approx cannot nest)."""
    assert pts is not None and len(pts) == len(want), (pts, want)
    for got, exp in zip(pts, want):
        for g, e in zip(got, exp):
            assert abs(g - e) <= tol, (pts, want)


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(2):
        make_image(src / f"p{i}.png", seed=i, size=(220, 160))
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


def _item(client) -> int:
    return sorted(i["id"] for i in client.get("/api/items").json()["items"])[0]


def _boxes(client, item: int, name: str) -> list[dict]:
    detail = client.get(f"/api/items/{item}").json()
    return [b for t in detail["tags"] if t["name"] == name
            for b in t["boxes"]]


def _revert_last(client, action: str):
    ev = client.get("/api/history").json()["events"][0]
    assert ev["action"] == action, ev
    r = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.status_code == 200, r.text


def test_a_polygon_box_derives_its_bbox_and_serves_its_points(client):
    item = _item(client)
    r = client.post(f"/api/tags/assign/item/{item}/box", json={
        "tag": "logo", "box": {"x": 0.9, "y": 0.9, "w": 0.01, "h": 0.01,
                               "points": TRI}})
    assert r.status_code == 200, r.text
    (box,) = _boxes(client, item, "logo")
    # The rectangle IS the polygon's bounding box — whatever the client sent
    # beside it.
    assert (box["x"], box["y"]) == pytest.approx((0.2, 0.2))
    assert (box["w"], box["h"]) == pytest.approx((0.4, 0.3))
    near(box["points"], TRI)


def test_a_rect_update_of_a_polygon_box_scales_the_vertices(client):
    """The annotator's box-mode transform: dragging the bounding box of a
    polygon scales the shape rather than silently losing it."""
    item = _item(client)
    client.post(f"/api/tags/assign/item/{item}/box", json={
        "tag": "logo", "box": {"points": TRI}})
    (box,) = _boxes(client, item, "logo")
    # Double the width, keep the origin: bbox (0.2, 0.2, 0.4, 0.3) becomes
    # (0.2, 0.2, 0.8, 0.3).
    r = client.patch(f"/api/tags/box/{box['id']}",
                     json={"x": 0.2, "y": 0.2, "w": 0.8, "h": 0.3})
    assert r.status_code == 200, r.text
    (box,) = _boxes(client, item, "logo")
    near(box["points"], [[0.2, 0.2], [1.0, 0.2], [0.6, 0.5]])
    assert (box["w"], box["h"]) == pytest.approx((0.8, 0.3))


def test_points_replace_and_clear_points_returns_the_rectangle(client):
    item = _item(client)
    client.post(f"/api/tags/assign/item/{item}/box", json={
        "tag": "logo", "box": {"points": TRI}})
    (box,) = _boxes(client, item, "logo")
    quad = [[0.1, 0.1], [0.5, 0.1], [0.5, 0.3], [0.1, 0.3]]
    client.patch(f"/api/tags/box/{box['id']}", json={"points": quad})
    (box,) = _boxes(client, item, "logo")
    near(box["points"], quad)
    assert (box["x"], box["w"]) == pytest.approx((0.1, 0.4))
    # Back to a plain rectangle: the bbox stays, the polygon goes.
    client.patch(f"/api/tags/box/{box['id']}", json={"clear_points": True})
    (box,) = _boxes(client, item, "logo")
    assert box["points"] is None
    assert (box["x"], box["w"]) == pytest.approx((0.1, 0.4))


def test_deleting_the_tag_and_reverting_restores_the_polygon(client):
    """A revert restores the SHAPE of an assignment — the polygon included.

    Through `delete_tag`, the path whose per-item `remove_tag` events carry
    the placements snapshot `_revert_remove_tag` recreates boxes from."""
    item = _item(client)
    client.post(f"/api/tags/assign/item/{item}/box", json={
        "tag": "logo", "box": {"points": TRI}})
    tag_id = next(t["id"] for t in client.get("/api/tags").json()
                  if t["name"] == "logo")
    r = client.delete(f"/api/tags/{tag_id}")
    assert r.status_code == 200, r.text
    assert _boxes(client, item, "logo") == []
    evs = client.get("/api/history").json()["events"][:2]
    assert {e["action"] for e in evs} == {"delete_tag", "remove_tag"}
    r = client.post("/api/history/revert",
                    json={"event_ids": [e["id"] for e in evs]})
    assert r.status_code == 200, r.text
    (box,) = _boxes(client, item, "logo")
    near(box["points"], TRI)


def test_the_polygon_rides_the_sidecar_and_restores(client, tmp_path):
    from media_compost import open_library

    item = _item(client)
    client.post(f"/api/tags/assign/item/{item}/box", json={
        "tag": "logo", "box": {"points": TRI}})

    with open_library(tmp_path / "restored", source="cli") as fresh:
        stats = fresh.merge_library(tmp_path / "data")
        assert not stats.errors, stats.errors
        pts = [b.points
               for it in fresh.query(None, show_hidden=True)
               if "logo" in it.tags
               for b in it.tags["logo"].boxes if b.points]
        assert len(pts) == 1
        near(pts[0], TRI)


# ---- the subject box's outline ----------------------------------------------


def _appearance(client) -> tuple[int, int]:
    item = _item(client)
    sub = client.post("/api/subjects",
                      json={"display_name": "Alice"}).json()[0]
    rows = client.post("/api/subjects/appearances",
                       json={"item_id": item, "subject_id": sub["id"]}).json()
    return item, rows[0]["appearances"][0]["id"]


def _sub_box(client, item: int):
    app_row = client.get(f"/api/items/{item}").json()[
        "subjects"][0]["appearances"][0]
    return app_row["box"], app_row.get("points")


def test_a_subject_outline_polygon_and_its_revert(client):
    item, apid = _appearance(client)
    r = client.put(f"/api/subjects/appearances/{apid}/box",
                   json={"x": 0, "y": 0, "w": 0, "h": 0, "points": TRI})
    assert r.status_code == 200, r.text
    box, pts = _sub_box(client, item)
    assert box == pytest.approx([0.2, 0.2, 0.4, 0.3])
    near(pts, TRI)
    # Replacing with a plain rectangle logs; its revert restores the polygon.
    client.put(f"/api/subjects/appearances/{apid}/box",
               json={"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2})
    box, pts = _sub_box(client, item)
    assert pts is None
    _revert_last(client, "set_appearance_box")
    box, pts = _sub_box(client, item)
    near(pts, TRI)
    assert box == pytest.approx([0.2, 0.2, 0.4, 0.3])


def test_the_subject_polygon_rides_the_sidecar(client, tmp_path):
    from media_compost import open_library

    item, apid = _appearance(client)
    client.put(f"/api/subjects/appearances/{apid}/box",
               json={"x": 0, "y": 0, "w": 0, "h": 0, "points": TRI})

    with open_library(tmp_path / "restored", source="cli") as fresh:
        stats = fresh.merge_library(tmp_path / "data")
        assert not stats.errors, stats.errors
        pts = [a.points
               for it in fresh.query(None, show_hidden=True)
               for a in it.appearances if a.points]
        assert len(pts) == 1
        near(pts[0], TRI)


def test_the_manifest_row_carries_the_polygon_fifth(client, tmp_path):
    """Training: a polygon box's manifest row is [x, y, w, h, points] — bbox
    first (crop steering reads nothing else), the shape behind it for the
    loss-mask rasterizer."""
    from media_compost import open_library
    from media_compost.train.dataset import build_manifest
    from media_compost.train.spec import DatasetQuery, TrainingConfig

    item = _item(client)
    client.post(f"/api/tags/assign/item/{item}/box", json={
        "tag": "logo", "box": {"points": TRI}})
    cfg = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)])
    config = cfg.model_dump(mode="json")
    config["buckets"]["skip_upscale"] = False
    lib = client.lib
    with open_library(lib.config.data_dir, source="cli") as handle:
        m = build_manifest(handle, config, tmp_path / "job")
    entry = next(e for e in m["items"] if e.get("boxes", {}).get("logo"))
    (row,) = entry["boxes"]["logo"]
    assert row[:4] == pytest.approx([0.2, 0.2, 0.4, 0.3], abs=1e-4)
    near(row[4], TRI)
