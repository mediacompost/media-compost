"""Detection results landing as TAG BOXES (Settings → Tagging's tag names).

The watermark detector's regions become boxes on the CONFIGURED watermark tag
— exactly what the box-driven watermark removal consumes — and, when the
OPTIONAL text tag is set, every OCR run additionally records its top-level
regions as boxes on that tag (slanted quads as polygons). Both go through one
near-duplicate dedup, so a re-run piles nothing up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost import prefs
from media_compost.db import Item, set_setting
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


def _item_id(client) -> int:
    return client.get("/api/items").json()["items"][0]["id"]


def _boxes(client, item: int, name: str) -> list[dict]:
    detail = client.get(f"/api/items/{item}").json()
    return [b for t in detail["tags"] if t["name"] == name
            for b in t["boxes"]]


def _set_global(client, **kw):
    with client.lib.db.session() as s:
        cur = prefs.read_json(s, prefs.PREFS_GLOBAL)
        cur.update(kw)
        set_setting(s, prefs.PREFS_GLOBAL, json.dumps(cur))
        s.commit()


def test_the_tag_name_readers(client):
    with client.lib.db.session() as s:
        # Defaults: watermark falls back to a real name, text is off.
        assert prefs.read_watermark_tag(s) == "watermark"
        assert prefs.read_text_tag(s) == ""
    _set_global(client, watermark_tag="  Stamp  ", text_tag="Page_Text")
    with client.lib.db.session() as s:
        assert prefs.read_watermark_tag(s) == "stamp"
        assert prefs.read_text_tag(s) == "page_text"
    # Emptied by hand: watermark keeps a name, text switches off.
    _set_global(client, watermark_tag="", text_tag="")
    with client.lib.db.session() as s:
        assert prefs.read_watermark_tag(s) == "watermark"
        assert prefs.read_text_tag(s) == ""


def test_watermark_regions_become_boxes_and_a_rerun_adds_nothing(client):
    item = _item_id(client)
    lib = client.lib
    rect_poly = [[0.1, 0.1], [0.4, 0.1], [0.4, 0.3], [0.1, 0.3]]
    tri = [[0.6, 0.6], [0.9, 0.6], [0.7, 0.9]]
    with lib.db.session() as s:
        row = s.get(Item, item)
        n = lib.jobs._apply_watermark_tag(s, row, [rect_poly, tri])
        s.commit()
    assert n == 2
    boxes = _boxes(client, item, "watermark")
    assert len(boxes) == 2
    # An axis-aligned region stores as the plain rectangle it is; the slanted
    # one keeps its polygon (bbox derived server-side).
    rects = [b for b in boxes if not b["points"]]
    polys = [b for b in boxes if b["points"]]
    assert len(rects) == 1 and len(polys) == 1
    assert (rects[0]["x"], rects[0]["w"]) == pytest.approx((0.1, 0.3))
    assert (polys[0]["x"], polys[0]["w"]) == pytest.approx((0.6, 0.3))
    # The same detection again: near-duplicates are skipped whole.
    with lib.db.session() as s:
        row = s.get(Item, item)
        n = lib.jobs._apply_watermark_tag(s, row, [rect_poly, tri])
        s.commit()
    assert n == 0
    assert len(_boxes(client, item, "watermark")) == 2


def test_the_configured_name_is_the_one_that_gets_the_boxes(client):
    _set_global(client, watermark_tag="stamp")
    item = _item_id(client)
    lib = client.lib
    with lib.db.session() as s:
        row = s.get(Item, item)
        lib.jobs._apply_watermark_tag(
            s, row, [[[0.2, 0.2], [0.5, 0.2], [0.5, 0.4], [0.2, 0.4]]])
        s.commit()
    assert len(_boxes(client, item, "stamp")) == 1
    assert _boxes(client, item, "watermark") == []


def _ocr_result():
    return [{"box": [0.1, 0.1, 0.3, 0.1], "text": "hello", "level": "block"},
            {"box": [0.1, 0.4, 0.3, 0.1], "text": "slanted", "level": "block",
             "quad": [[0.1, 0.4], [0.4, 0.45], [0.4, 0.55], [0.1, 0.5]]}]


def test_ocr_writes_text_tag_boxes_only_when_the_name_is_set(client):
    item = _item_id(client)
    lib = client.lib
    with lib.db.session() as s:
        row = s.get(Item, item)
        lib.jobs._apply_ocr(s, row, _ocr_result(), "rapidocr_multi")
        s.commit()
    # No name configured: text regions only, no tag anywhere.
    assert client.get(f"/api/items/{item}").json()["text_count"] == 2
    assert all(t["name"] != "page_text"
               for t in client.get(f"/api/items/{item}").json()["tags"])

    _set_global(client, text_tag="page_text")
    with lib.db.session() as s:
        row = s.get(Item, item)
        lib.jobs._apply_ocr(s, row, _ocr_result(), "rapidocr_multi")
        s.commit()
    boxes = _boxes(client, item, "page_text")
    assert len(boxes) == 2
    # The slanted reading keeps its quad as a polygon.
    assert sum(1 for b in boxes if b["points"]) == 1
    # A third run adds nothing.
    with lib.db.session() as s:
        row = s.get(Item, item)
        lib.jobs._apply_ocr(s, row, _ocr_result(), "rapidocr_multi")
        s.commit()
    assert len(_boxes(client, item, "page_text")) == 2


def test_settings_round_trip_carries_both_names(client):
    got = client.get("/api/settings").json()
    assert got["watermark_tag"] == "watermark"
    assert got["text_tag"] == ""
    got["watermark_tag"] = "Stamp"
    got["text_tag"] = "page_text"
    r = client.put("/api/settings", json=got)
    assert r.status_code == 200, r.text
    back = client.get("/api/settings").json()
    assert back["watermark_tag"] == "stamp"
    assert back["text_tag"] == "page_text"


def test_the_box_driven_removal_reads_the_configured_name(client):
    """`_watermark_boxes` (what the :boxes removal inpaints) follows the
    setting rather than the literal word "watermark"."""
    _set_global(client, watermark_tag="stamp")
    item = _item_id(client)
    lib = client.lib
    with lib.db.session() as s:
        row = s.get(Item, item)
        lib.jobs._apply_watermark_tag(
            s, row, [[[0.2, 0.2], [0.5, 0.2], [0.5, 0.4], [0.2, 0.4]]])
        s.commit()
    with lib.db.session() as s:
        row = s.get(Item, item)
        boxes = lib.jobs._watermark_boxes(s, row)
    assert len(boxes) == 1
    assert boxes[0][0] == pytest.approx(0.2)
