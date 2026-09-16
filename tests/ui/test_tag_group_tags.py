"""Meta tags on per-item tag groups: the third user of the link-tag namespace.

A tag group says which tags belong together ("Person A"); its meta tags say
something about that grouping. They must behave exactly like a caption's or a
link's — one catalog, one rename, one delete — and must never leak into the
item's own tags, which are what search and training see.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.importer import Importer, ImportOptions
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
        c.lib = lib          # for the sidecar check
        yield c
    app.dependency_overrides.clear()


def _first_item(client) -> int:
    return client.get("/api/items").json()["items"][0]["id"]


def _group(client, item_id: int, name: str) -> int:
    return client.post(f"/api/tags/item/{item_id}/groups",
                       json={"name": name}).json()["id"]


def _groups_of(client, item_id: int) -> dict[str, list[str]]:
    detail = client.get(f"/api/items/{item_id}").json()
    return {g["name"]: g["tags"] for g in detail["tag_groups"]}


def test_add_remove_tag_group_tag(client):
    item = _first_item(client)
    gid = _group(client, item, "Person A")

    r = client.post(f"/api/tags/groups/{gid}/tags", json={"name": "main character"})
    assert r.status_code == 200 and r.json() == ["main character"]
    # Idempotent.
    assert client.post(f"/api/tags/groups/{gid}/tags",
                       json={"name": "main character"}).json() == ["main character"]
    client.post(f"/api/tags/groups/{gid}/tags", json={"name": "to redraw"})

    assert _groups_of(client, item)["Person A"] == ["main character", "to redraw"]

    r = client.delete(f"/api/tags/groups/{gid}/tags/to%20redraw")
    assert r.json() == ["main character"]
    assert _groups_of(client, item)["Person A"] == ["main character"]


def test_a_group_meta_tag_is_not_an_item_tag(client):
    """The whole point of the separate namespace: labelling the grouping must
    not put a word on the picture, where search and training would see it."""
    item = _first_item(client)
    gid = _group(client, item, "Person A")
    client.post(f"/api/tags/groups/{gid}/tags", json={"name": "main character"})

    detail = client.get(f"/api/items/{item}").json()
    assert "main character" not in detail["eff_tags"]
    assert all(i["name"] != "main character" for i in detail["tag_instances"])
    assert "main character" not in {
        t["name"] for t in client.get("/api/tags").json()
    }


def test_group_tags_share_the_link_tag_namespace(client):
    """One catalog: a tag-group meta tag suggests itself for links and
    captions, and the Tags tab's rows count all three uses under one name."""
    item = _first_item(client)
    gid = _group(client, item, "Person A")
    client.post(f"/api/tags/groups/{gid}/tags", json={"name": "source"})

    assert "source" in client.get("/api/link-tags").json()
    rows = {r["name"]: r for r in client.get("/api/link-tags/rows").json()}
    assert rows["source"]["count"] == 1

    # A caption carrying the same name counts under the one name.
    client.post(f"/api/items/{item}/captions", json={"text": "a red car"})
    cap = client.get(f"/api/items/{item}").json()["captions"][0]["id"]
    client.post(f"/api/items/{item}/captions/{cap}/tags", json={"name": "source"})
    rows = {r["name"]: r for r in client.get("/api/link-tags/rows").json()}
    assert rows["source"]["count"] == 2


def test_rename_and_delete_reach_tag_groups(client):
    item = _first_item(client)
    gid = _group(client, item, "Person A")
    client.post(f"/api/tags/groups/{gid}/tags", json={"name": "draft"})

    client.post("/api/link-tags/update", json={"name": "draft",
                                               "new_name": "provisional"})
    assert _groups_of(client, item)["Person A"] == ["provisional"]

    client.post("/api/link-tags/delete", json={"name": "provisional"})
    assert _groups_of(client, item)["Person A"] == []


def test_rename_merges_onto_an_existing_group_tag(client):
    """A group carrying both the old and the new name keeps a single tag."""
    item = _first_item(client)
    gid = _group(client, item, "Person A")
    client.post(f"/api/tags/groups/{gid}/tags", json={"name": "draft"})
    client.post(f"/api/tags/groups/{gid}/tags", json={"name": "provisional"})

    client.post("/api/link-tags/update", json={"name": "draft",
                                               "new_name": "provisional"})
    assert _groups_of(client, item)["Person A"] == ["provisional"]


def _item_dict(client, item_id: int) -> dict:
    from media_compost.db import Item
    from media_compost.itemdict import item_to_dict

    with client.lib.db.session() as s:
        return item_to_dict(s, s.get(Item, item_id))


def test_group_tags_ride_in_the_item_dict(client):
    item = _first_item(client)
    gid = _group(client, item, "Person A")
    client.post(f"/api/tags/groups/{gid}/tags", json={"name": "main character"})

    payload = _item_dict(client, item)
    entry = [g for g in payload["tag_groups"] if g["name"] == "Person A"][0]
    assert entry["tags"] == ["main character"]

    # A rename shows through — the dict spells names out, never ids.
    client.post("/api/link-tags/update", json={"name": "main character",
                                               "new_name": "protagonist"})
    payload = _item_dict(client, item)
    entry = [g for g in payload["tag_groups"] if g["name"] == "Person A"][0]
    assert entry["tags"] == ["protagonist"]
