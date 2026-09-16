"""The SUBJECT BOX — where in the picture one appearance is, as a rectangle.

The face is only the fallback for that question (a figure facing away, a
building), so an appearance can carry a hand-drawn box of its own: at most
one, replaced by drawing again, cleared by its DELETE. What this file pins:
every edit logs and reverts (the draw, the replace and the clear — the sweep
the history golden's UNCOVERED entry points at), the box rides the sidecar
and comes back from a folder restore, and crop-aware training prefers it
over the appearance's face.
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


def _appearance(client) -> tuple[int, int]:
    """An item with Alice in it — (item_id, appearance_id)."""
    item = sorted(i["id"] for i in client.get("/api/items").json()["items"])[0]
    sub = client.post("/api/subjects",
                      json={"display_name": "Alice"}).json()[0]
    rows = client.post("/api/subjects/appearances",
                       json={"item_id": item, "subject_id": sub["id"]}).json()
    apid = rows[0]["appearances"][0]["id"]
    return item, apid


def _box(client, item: int):
    detail = client.get(f"/api/items/{item}").json()
    return detail["subjects"][0]["appearances"][0]["box"]


def _revert_last(client, action: str):
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == action)
    r = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.status_code == 200, r.text


def test_draw_replace_clear_and_every_revert(client):
    item, apid = _appearance(client)
    assert _box(client, item) is None

    # DRAW. The revert takes down what was drawn over nothing.
    r = client.put(f"/api/subjects/appearances/{apid}/box",
                   json={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})
    assert r.status_code == 200
    assert _box(client, item) == [0.1, 0.2, 0.3, 0.4]
    _revert_last(client, "set_appearance_box")
    assert _box(client, item) is None

    # REPLACE. The revert puts the first rectangle back, not the absence.
    client.put(f"/api/subjects/appearances/{apid}/box",
               json={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})
    client.put(f"/api/subjects/appearances/{apid}/box",
               json={"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2})
    assert _box(client, item) == [0.5, 0.5, 0.2, 0.2]
    _revert_last(client, "set_appearance_box")
    assert _box(client, item) == [0.1, 0.2, 0.3, 0.4]

    # CLEAR. Its revert restores the rectangle it took down.
    r = client.delete(f"/api/subjects/appearances/{apid}/box")
    assert r.status_code == 200
    assert _box(client, item) is None
    _revert_last(client, "set_appearance_box")
    assert _box(client, item) == [0.1, 0.2, 0.3, 0.4]

    # Clearing nothing logs nothing (there is nothing to offer back).
    client.delete(f"/api/subjects/appearances/{apid}/box")
    before = [e["id"] for e in client.get("/api/history").json()["events"]]
    client.delete(f"/api/subjects/appearances/{apid}/box")
    after = [e["id"] for e in client.get("/api/history").json()["events"]]
    assert before == after


def test_the_box_rides_the_sidecar_and_restores(client, tmp_path):
    from media_compost import open_library

    item, apid = _appearance(client)
    client.put(f"/api/subjects/appearances/{apid}/box",
               json={"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5})

    with open_library(tmp_path / "restored", source="cli") as fresh:
        stats = fresh.merge_library(tmp_path / "data")
        assert not stats.errors, stats.errors
        items = list(fresh.query(None, show_hidden=True))
        apps = [a for it in items for a in it.appearances]
        rects = [a.rect for a in apps if a.rect is not None]
        assert len(rects) == 1
        assert (round(rects[0].x, 3), round(rects[0].w, 3)) == (0.25, 0.5)


def test_training_crops_prefer_the_subject_box_over_the_face(client, tmp_path):
    """`dataset._tag_boxes`' precedence: a tag's own box, then the subject
    box, then the face — and the box that wins is visible in the manifest."""
    from media_compost import open_library
    from media_compost.train.dataset import build_manifest
    from media_compost.train.spec import DatasetQuery, TrainingConfig

    item, apid = _appearance(client)
    # A face for the appearance, well away from where the subject box goes.
    face = client.post("/api/faces", json={
        "item_id": item, "x": 0.8, "y": 0.8, "w": 0.1, "h": 0.1}).json()
    rows = face["faces"] if isinstance(face, dict) else face
    fid = max(f["id"] for f in rows)
    client.patch(f"/api/subjects/appearances/{apid}", json={"face_id": fid})
    client.put(f"/api/subjects/appearances/{apid}/box",
               json={"x": 0.1, "y": 0.1, "w": 0.6, "h": 0.6})

    cfg = TrainingConfig(model="sd15", queries=[DatasetQuery(tree=None)])
    config = cfg.model_dump(mode="json")
    config["buckets"]["skip_upscale"] = False
    lib = client.lib
    with open_library(lib.config.data_dir, source="cli") as handle:
        m = build_manifest(handle, config, tmp_path / "job")
    tag = client.get(f"/api/items/{item}").json()["subjects"][0]["tag"]
    entry = next(e for e in m["items"] if e.get("boxes", {}).get(tag))
    (box,) = entry["boxes"][tag]
    assert box[2] == pytest.approx(0.6, abs=0.01), (
        "the face's 0.1-wide box won over the drawn subject box")
