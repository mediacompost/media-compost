"""End-to-end structured search via POST /api/items/query."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.db import (
    Item, ItemTag, Relationship, RelationshipTag, Tag,
)
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from media_compost.testing import make_jpeg_with_exif


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    make_jpeg_with_exif(src / "a.jpg", seed=1)
    make_jpeg_with_exif(src / "b.jpg", seed=2)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False)
        )
        s.commit()
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _query(c: TestClient, tree, **scope):
    r = c.post("/api/items/query", json={"query": tree, **scope})
    assert r.status_code == 200, r.text
    return r.json()


def _ids(page):
    return {it["id"] for it in page["items"]}


def test_empty_query_returns_all(client):
    c, _lib = client
    page = _query(c, None)
    assert page["total"] == 2


def test_tag_condition(client):
    c, lib = client
    with lib.db.session() as s:
        item = s.query(Item).order_by(Item.id).first()
        tag = Tag(name="portrait")
        s.add(tag)
        s.flush()
        s.add(ItemTag(item_id=item.id, tag_id=tag.id))
        s.commit()
        target = item.id
    tree = {"type": "group", "op": "and", "children": [
        {"type": "tag", "name": "portrait", "have": True, "sign": "pos"},
    ]}
    page = _query(c, tree)
    assert _ids(page) == {target}
    # has-not inverts it.
    tree["children"][0]["have"] = False
    page = _query(c, tree)
    assert target not in _ids(page) and page["total"] == 1


def test_intrinsic_metadata_condition(client):
    c, _lib = client
    wide = {"type": "group", "op": "and", "children": [
        {"type": "meta", "name": "width", "mtype": "numeric", "op": ">=", "value": 640},
    ]}
    assert _query(c, wide)["total"] == 2
    huge = {"type": "group", "op": "and", "children": [
        {"type": "meta", "name": "width", "mtype": "numeric", "op": ">=", "value": 5000},
    ]}
    assert _query(c, huge)["total"] == 0


def test_indexed_metadata_condition(client):
    c, _lib = client
    # Both images carry Make=TestMake; contains "testmake" (case-insensitive).
    contains = {"type": "group", "op": "and", "children": [
        {"type": "meta", "name": "camera_make", "mtype": "text", "op": "~", "value": "testmake"},
    ]}
    assert _query(c, contains)["total"] == 2
    # Only b.jpg has Model2.
    model = {"type": "group", "op": "and", "children": [
        {"type": "meta", "name": "camera_model", "mtype": "text", "op": "=", "value": "Model2"},
    ]}
    assert _query(c, model)["total"] == 1


def test_link_condition(client):
    c, lib = client
    with lib.db.session() as s:
        a, b = s.query(Item).order_by(Item.id).all()
        rel = Relationship(from_item_id=a.id, to_item_id=b.id, kind="manual")
        s.add(rel)
        s.flush()
        s.add(RelationshipTag(relationship_id=rel.id, name="crop"))
        s.commit()
        a_id, b_id = a.id, b.id
    # Outgoing link with tag crop -> only a.
    out = {"type": "group", "op": "and", "children": [
        {"type": "link", "direction": "has",
         "link_tags": [{"name": "crop", "exclude": False}]},
    ]}
    assert _ids(_query(c, out)) == {a_id}
    # Incoming link -> only b.
    inc = {"type": "group", "op": "and", "children": [
        {"type": "link", "direction": "linkedby", "link_tags": []},
    ]}
    assert _ids(_query(c, inc)) == {b_id}
    # Excluded tag: outgoing link that must NOT have crop -> none.
    excl = {"type": "group", "op": "and", "children": [
        {"type": "link", "direction": "has",
         "link_tags": [{"name": "crop", "exclude": True}]},
    ]}
    assert _query(c, excl)["total"] == 0
