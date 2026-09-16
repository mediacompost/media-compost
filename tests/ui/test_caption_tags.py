"""Meta tags on captions: the caption side of the link-tag namespace.

The same names power both (``LinkTag`` is the catalog; ``RelationshipTag`` and
``CaptionTag`` are the uses), so these tests check the shared parts too —
autocomplete, the Tags-tab rows' counts, rename and delete.
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
from media_compost.testing import search_items


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


def _add_caption(client, item_id: int, text: str) -> int:
    client.post(f"/api/items/{item_id}/captions", json={"text": text})
    caps = client.get(f"/api/items/{item_id}").json()["captions"]
    return [c for c in caps if c["text"] == text][0]["id"]


def q_caption(mode="has", tags=()):
    return {"type": "caption", "mode": mode,
            "caption_tags": [{"name": n, "exclude": x} for n, x in tags]}


def test_add_remove_caption_tag(client):
    item = _first_item(client)
    cap = _add_caption(client, item, "a red car")

    r = client.post(f"/api/items/{item}/captions/{cap}/tags",
                    json={"name": "alt text"})
    assert r.status_code == 200 and r.json() == ["alt text"]
    # Idempotent.
    assert client.post(f"/api/items/{item}/captions/{cap}/tags",
                       json={"name": "alt text"}).json() == ["alt text"]
    client.post(f"/api/items/{item}/captions/{cap}/tags",
                json={"name": "German"})

    caps = client.get(f"/api/items/{item}").json()["captions"]
    assert [c for c in caps if c["id"] == cap][0]["tags"] == ["German", "alt text"]

    r = client.delete(f"/api/items/{item}/captions/{cap}/tags/German")
    assert r.json() == ["alt text"]


def test_caption_tags_share_the_link_tag_namespace(client):
    """One catalog: a caption tag suggests itself for links and vice versa,
    and the Tags tab's rows count both uses under one name."""
    item = _first_item(client)
    cap = _add_caption(client, item, "a red car")
    client.post(f"/api/items/{item}/captions/{cap}/tags", json={"name": "source"})

    assert "source" in client.get("/api/link-tags").json()
    rows = {r["name"]: r for r in client.get("/api/link-tags/rows").json()}
    assert rows["source"]["count"] == 1

    # A second caption carrying it counts twice under the one name.
    cap2 = _add_caption(client, item, "another caption")
    client.post(f"/api/items/{item}/captions/{cap2}/tags", json={"name": "source"})
    rows = {r["name"]: r for r in client.get("/api/link-tags/rows").json()}
    assert rows["source"]["count"] == 2


def test_rename_and_delete_reach_captions(client):
    item = _first_item(client)
    cap = _add_caption(client, item, "a red car")
    client.post(f"/api/items/{item}/captions/{cap}/tags", json={"name": "draft"})

    client.post("/api/link-tags/update", json={"name": "draft",
                                               "new_name": "provisional"})
    caps = client.get(f"/api/items/{item}").json()["captions"]
    assert [c for c in caps if c["id"] == cap][0]["tags"] == ["provisional"]

    client.post("/api/link-tags/delete", json={"name": "provisional"})
    caps = client.get(f"/api/items/{item}").json()["captions"]
    assert [c for c in caps if c["id"] == cap][0]["tags"] == []


def test_query_caption_has_and_hasnot(client):
    items = client.get("/api/items").json()["items"]
    a, b = items[0]["id"], items[1]["id"]
    cap = _add_caption(client, a, "a red car")
    client.post(f"/api/items/{a}/captions/{cap}/tags", json={"name": "alt text"})
    _add_caption(client, b, "an untagged caption")

    # Any caption at all: both items.
    got = {i["id"] for i in search_items(client, q_caption("has"))["items"]}
    assert {a, b} <= got

    # Narrowed by a required tag: only the tagged one.
    got = {i["id"] for i in search_items(
        client, q_caption("has", [("alt text", False)]))["items"]}
    assert got == {a}

    # "has not" is its negation — b has a caption, but not that tag.
    got = {i["id"] for i in search_items(
        client, q_caption("hasnot", [("alt text", False)]))["items"]}
    assert a not in got and b in got

    # An excluded tag: a caption WITHOUT it satisfies the condition.
    got = {i["id"] for i in search_items(
        client, q_caption("has", [("alt text", True)]))["items"]}
    assert b in got and a not in got


def test_caption_tags_ride_in_the_item_dict(client):
    """`item_to_dict` (the merge transfer format) carries a caption's meta
    tags by NAME — the shape the retired item.json sidecar held."""
    from media_compost.db import Item
    from media_compost.itemdict import item_to_dict

    item = _first_item(client)
    cap = _add_caption(client, item, "a red car")
    client.post(f"/api/items/{item}/captions/{cap}/tags", json={"name": "alt text"})

    with client.lib.db.session() as s:
        payload = item_to_dict(s, s.get(Item, item))
    entry = [c for c in payload["captions"] if c["text"] == "a red car"][0]
    assert entry["tags"] == ["alt text"]


def test_one_caption_onto_every_item_named(client):
    """The sidebar's multi-selection Add: one request, one caption per item,
    and one ordinary `add_caption` entry each — so each reverts on its own
    exactly as a caption typed into a single item does."""
    ids = [it["id"] for it in client.get("/api/items").json()["items"]][:3]
    r = client.post("/api/items/captions/bulk",
                    json={"item_ids": ids, "text": "a shared line"})
    assert r.status_code == 200, r.text
    assert len(r.json()["ids"]) == len(ids)
    for iid in ids:
        caps = client.get(f"/api/items/{iid}").json()["captions"]
        assert [c["text"] for c in caps] == ["a shared line"]

    # One entry per item, each revertible on its own.
    evs = [e for e in client.get("/api/history").json()["events"]
           if e["action"] == "add_caption"]
    assert len(evs) == len(ids)
    assert client.post("/api/history/revert",
                       json={"event_ids": [evs[0]["id"]]}).status_code == 200
    left = sum(1 for iid in ids
               if client.get(f"/api/items/{iid}").json()["captions"])
    assert left == len(ids) - 1

    # Instructions go through the same door, and a repeated id is one item.
    r = client.post("/api/items/captions/bulk",
                    json={"item_ids": [ids[0], ids[0]], "text": "make it blue",
                          "kind": "instruction"})
    assert r.status_code == 200 and len(r.json()["ids"]) == 1
    caps = client.get(f"/api/items/{ids[0]}").json()["captions"]
    assert [c["kind"] for c in caps if c["text"] == "make it blue"] \
        == ["instruction"]

    # And the cap is a fact about the request.
    assert client.post("/api/items/captions/bulk",
                       json={"item_ids": list(range(1, 502)),
                             "text": "x"}).status_code == 413


def test_the_bulk_details_count_an_items_live_text(client):
    """The sidebar's Text tab over a multi-selection reads `text_count` from
    the bulk details, so it must be there and must be the ACTIVE file's live
    top-level regions — the single-item detail's own number."""
    ids = [it["id"] for it in client.get("/api/items").json()["items"]][:2]
    got = client.post("/api/items/details",
                      json={"item_ids": ids}).json()["items"]
    assert [it["text_count"] for it in got] == [0, 0]

    r = client.post("/api/ocr",
                    json={"item_id": ids[0], "text": "hello",
                          "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1})
    assert r.status_code == 200, r.text
    got = {it["id"]: it["text_count"] for it in client.post(
        "/api/items/details", json={"item_ids": ids}).json()["items"]}
    assert got[ids[0]] == 1 and got[ids[1]] == 0
    # The same number the single-item detail reports.
    assert client.get(f"/api/items/{ids[0]}").json()["text_count"] == 1


def _model_caption(client, item_id: int, text: str, model: str) -> None:
    """A caption as a MODEL would have left it — the row is the run marker,
    so what matters is `Caption.model`, which no HTTP route sets (a person
    typing one is not a model)."""
    from media_compost.db import Caption

    client.post(f"/api/items/{item_id}/captions", json={"text": text})
    with client.lib.db.session() as s:
        row = s.query(Caption).filter(Caption.item_id == item_id,
                                      Caption.text == text).one()
        row.model = model
        s.commit()


def test_generating_captions_skips_what_this_model_already_wrote(client):
    """A caption is its own run marker: the row records the model that wrote
    it, so "has this model already described this picture" needs no per-item
    run table. Re-running would leave a second, nearly identical description
    beside the first with nothing to tell them apart."""
    items = [i["id"] for i in client.get("/api/items").json()["items"]][:3]
    _model_caption(client, items[0], "a cat on a mat", "florence2_base")
    r = client.post("/api/ml/jobs", json={
        "kind": "caption", "model": "florence2_base", "item_ids": items,
        "skip_done": True}).json()
    assert r["skipped"] == 1


def test_it_is_per_MODEL_and_a_hand_written_caption_stops_nothing(client):
    """Several models describing one picture differently is the ordinary
    case, and a caption somebody TYPED must never keep a model from writing
    its own — a typed one carries no model at all."""
    items = [i["id"] for i in client.get("/api/items").json()["items"]][:2]
    _model_caption(client, items[0], "by another model", "joycaption")
    client.post(f"/api/items/{items[1]}/captions", json={"text": "by hand"})
    r = client.post("/api/ml/jobs", json={
        "kind": "caption", "model": "florence2_base", "item_ids": items,
        "skip_done": True}).json()
    assert r["skipped"] == 0
