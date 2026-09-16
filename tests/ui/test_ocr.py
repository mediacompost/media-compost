"""The text router's own edges — what the history audit does not reach.

The mutation round trips live in `test_ocr_history_audit.py`; this file holds
the transport: the tree shape the list returns, the refusals, and the crop.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([images], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _item(client) -> int:
    return client.get("/api/items").json()["items"][0]["id"]


def test_the_list_is_a_tree_in_reading_order(client):
    a = _item(client)
    b1 = client.post("/api/ocr", json={"item_id": a, "x": 0.1, "y": 0.1,
                                       "w": 0.4, "h": 0.1,
                                       "text": "first"}).json()[0]["id"]
    client.post("/api/ocr", json={"item_id": a, "x": 0.1, "y": 0.5,
                                  "w": 0.4, "h": 0.1, "text": "second"})
    client.post("/api/ocr", json={"item_id": a, "x": 0.1, "y": 0.1,
                                  "w": 0.2, "h": 0.1, "text": "fir",
                                  "level": "word", "parent_id": b1})
    tree = client.get(f"/api/ocr/item/{a}").json()
    assert [r["text"] for r in tree] == ["first", "second"]
    assert [c["text"] for c in tree[0]["children"]] == ["fir"]
    assert tree[0]["children"][0]["parent_id"] == b1
    # Hand-drawn: no engine, no score — and `models == []` is what says so.
    assert tree[0]["models"] == [] and tree[0]["score"] is None


def test_refusals(client):
    a = _item(client)
    # A parent on another item is not a parent.
    other = client.get("/api/items").json()["items"][1]["id"]
    p = client.post("/api/ocr", json={"item_id": other, "x": 0.1, "y": 0.1,
                                      "w": 0.2, "h": 0.1}).json()[0]["id"]
    assert client.post("/api/ocr", json={
        "item_id": a, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1,
        "parent_id": p}).status_code == 404
    # A level outside the tag set.
    assert client.post("/api/ocr", json={
        "item_id": a, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1,
        "level": "paragraph"}).status_code == 400
    # A reorder must name each sibling exactly once.
    rid = client.post("/api/ocr", json={"item_id": a, "x": 0.1, "y": 0.1,
                                        "w": 0.2, "h": 0.1}).json()[0]["id"]
    assert client.post(f"/api/ocr/item/{a}/order", json={
        "region_ids": [rid, rid]}).status_code == 400
    # Unknown region: PATCH refuses, the crop 404s.
    assert client.patch("/api/ocr/999999",
                        json={"text": "x"}).status_code == 404
    assert client.get("/api/ocr/999999/crop").status_code == 404
    # A body with an unknown field is refused, not silently dropped.
    assert client.post("/api/ocr", json={
        "item_id": a, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1,
        "txt": "misspelled"}).status_code == 422


def test_the_crop_is_a_wide_jpeg_strip(client):
    """Sized by WIDTH with the height following — `face_crop`'s square fit
    would hand a 20:1 line back a few pixels tall."""
    from io import BytesIO

    from PIL import Image

    a = _item(client)
    rid = client.post("/api/ocr", json={"item_id": a, "x": 0.1, "y": 0.4,
                                        "w": 0.8, "h": 0.1,
                                        "text": "wide"}).json()[0]["id"]
    r = client.get(f"/api/ocr/{rid}/crop?w=160")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(r.content)) as im:
        assert im.width == 160
        assert im.height < im.width  # the strip kept its own aspect
