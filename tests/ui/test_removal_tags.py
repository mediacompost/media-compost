"""The two box-driven removals read the tag names Settings → Tagging holds.

Watermark removal and text removal each have a variant that paints out the
boxes on a TAG rather than the result of a detector — and which tag is a
setting, so a library that calls its watermarks `logo` and its text `speech`
must have both variants follow. What these hold is that the CONFIGURED name
is what is read (not the default spelled out somewhere), that a blank text
tag — which is the shipped state — offers nothing rather than matching the
tag whose name is the empty string, and that a slanted box travels as the
polygon it was drawn as.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from media_compost.db import Item, ItemTag, ItemTagBox, ItemTagPlacement, Tag
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def lib_client(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    im = Image.new("RGB", (300, 300), (255, 255, 255))
    ImageDraw.Draw(im).ellipse([80, 80, 220, 220], fill=(200, 30, 30))
    src = tmp_path / "disc.png"
    im.save(src, "PNG")
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _item_id(lib) -> int:
    with lib.db.session() as s:
        return s.execute(select(Item.id)).scalars().first()


def _box(lib, iid: int, tag: str, rect, points=None) -> None:
    """Give the item a box on ``tag`` — through the DB, because what is under
    test is the READER and the shape it gets back."""
    with lib.db.session() as s:
        t = s.execute(select(Tag).where(Tag.name == tag)).scalars().first()
        if t is None:
            t = Tag(name=tag)
            s.add(t)
            s.flush()
        it = s.execute(select(ItemTag).where(
            ItemTag.item_id == iid, ItemTag.tag_id == t.id)).scalars().first()
        if it is None:
            it = ItemTag(item_id=iid, tag_id=t.id, negative=False)
            s.add(it)
            s.flush()
        p = ItemTagPlacement(item_tag_id=it.id)
        s.add(p)
        s.flush()
        x, y, w, h = rect
        s.add(ItemTagBox(placement_id=p.id, x=x, y=y, w=w, h=h,
                         points=json.dumps(points) if points else None))
        s.commit()


def _set_tags(client, **over) -> None:
    cur = client.get("/api/settings").json()
    cur.update(over)
    assert client.put("/api/settings", json=cur).status_code == 200


def test_the_watermark_variant_reads_the_CONFIGURED_name(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    _set_tags(client, watermark_tag="logo")
    _box(lib, iid, "watermark", (0.1, 0.1, 0.2, 0.2))
    _box(lib, iid, "logo", (0.5, 0.5, 0.3, 0.3))

    with lib.db.session() as s:
        boxes = lib.jobs._watermark_boxes(s, s.get(Item, iid))
    assert boxes == [[0.5, 0.5, 0.3, 0.3]], "the setting, not the default"


def test_the_text_variant_reads_the_CONFIGURED_name(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    _set_tags(client, text_tag="speech")
    _box(lib, iid, "speech", (0.25, 0.5, 0.5, 0.25))

    with lib.db.session() as s:
        item = s.get(Item, iid)
        quads = lib.jobs._tag_box_quads(s, item, "speech")
        assert lib.jobs._tag_box_quads(s, item, "text") == []
    assert quads == [[[0.25, 0.5], [0.75, 0.5], [0.75, 0.75], [0.25, 0.75]]]


def test_a_slanted_box_travels_as_the_POLYGON_it_was_drawn_as(lib_client):
    """An upright rectangle over slanted text paints out the art either side
    of the words — the very reason the region path carries quads."""
    client, lib = lib_client
    iid = _item_id(lib)
    poly = [[0.1, 0.2], [0.6, 0.1], [0.65, 0.3], [0.15, 0.4]]
    _box(lib, iid, "text", (0.1, 0.1, 0.55, 0.3), points=poly)

    with lib.db.session() as s:
        quads = lib.jobs._tag_box_quads(s, s.get(Item, iid), "text")
    assert quads == [poly]


def test_a_BLANK_text_tag_reads_nothing(lib_client):
    """The shipped state — the text tag is optional, and "" must not fall
    through to matching the tag whose name is the empty string."""
    client, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        s.add(Tag(name=""))
        s.commit()
    _box(lib, iid, "", (0.0, 0.0, 1.0, 1.0))

    with lib.db.session() as s:
        assert lib.jobs._tag_box_quads(s, s.get(Item, iid), "") == []
        assert lib.jobs._boxes_on_tag(s, s.get(Item, iid), "") == []


def test_both_removals_offer_a_tag_driven_variant(lib_client):
    """Symmetry is the point: each of the two things the app can paint out
    has a reading-driven way in and a tag-driven one, and the tag is named in
    the same place for both."""
    client, _ = lib_client
    tasks = {t["kind"]: t for t in client.get("/api/ml/models").json()["tasks"]}
    for kind, model_id in (("watermark_removal", "yolo11x_lama:boxes"),
                           ("text_removal", "lama_regions:boxes")):
        ids = [m["id"] for m in tasks[kind]["models"]]
        assert model_id in ids, (kind, ids)


def test_no_model_note_spells_a_tag_name_out(lib_client):
    """A note reading "the item's 'watermark' tag boxes" is a lie the moment
    the setting says `logo` — and the menu is where somebody reads it."""
    client, _ = lib_client
    tasks = client.get("/api/ml/models").json()["tasks"]
    for task in tasks:
        for m in task["models"]:
            if not m["id"].endswith(":boxes"):
                continue
            note = (m.get("note") or "").lower()
            assert "'watermark'" not in note and '"watermark"' not in note
            assert "settings" in note, m["id"]
