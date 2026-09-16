"""Every mutation the Text tab can make logs an event, and every one reverts.

The same sweep `test_faces_history_audit.py` runs over the faces, for the
same reason: the gaps would be invisible. Three of its cases are the ones the
reverts were designed around — an edit's revert restores `edited` as well as
the string (a machine's reading restored as an edited one is immune to the
next run; an edit restored as un-edited is silently overwritten by one), a
move's revert restores the QUAD (or a moved rotated line comes back as an
upright rectangle), and a delete's revert restores the whole SUBTREE (the
CASCADE took the children down with the row).

Add an action to a text region, add a case here.
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
        c.lib = lib  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


# ---- helpers ---------------------------------------------------------------

def _items(client) -> list[int]:
    return [it["id"] for it in client.get("/api/items").json()["items"]]


def _read(client, item_id: int, found: list[dict],
          model: str = "rapidocr_multi"):
    """Apply a fake run's payload straight through `_apply_ocr` — the trick
    `test_faces_history_audit._detect` uses, so no model is needed."""
    from media_compost.db import Item
    from media_compost.ui.jobs import JobQueue

    lib = client.lib
    queue = JobQueue.__new__(JobQueue)
    queue.lib = lib
    with lib.db.session() as s:
        item = s.get(Item, item_id)
        queue._apply_ocr(s, item, found, model)
        s.commit()


def latest(client, action: str) -> dict:
    events = [e for e in client.get("/api/history?limit=200").json()["events"]
              if e["action"] == action]
    assert events, f"no {action} event was logged"
    return events[0]


def revert(client, event_id: int) -> None:
    r = client.post("/api/history/revert",
                    json={"event_ids": [event_id]}).json()
    assert r["failed"] == [], f"event {event_id} refused to revert"


def tree_of(client, item_id: int) -> list[dict]:
    return client.get(f"/api/ocr/item/{item_id}").json()


# ---- the six revertible actions --------------------------------------------

def test_drawing_a_text_box_round_trips(client):
    item = _items(client)[0]
    client.post("/api/ocr", json={"item_id": item, "x": 0.1, "y": 0.1,
                                  "w": 0.4, "h": 0.1, "text": "typed"})
    assert len(tree_of(client, item)) == 1
    revert(client, latest(client, "add_text")["id"])
    assert tree_of(client, item) == []


def test_correcting_text_round_trips_with_its_edited_flag(client):
    item = _items(client)[0]
    _read(client, item, [{"level": "block", "box": [0.1, 0.1, 0.4, 0.1],
                          "text": "machine read"}])
    rid = tree_of(client, item)[0]["id"]
    client.patch(f"/api/ocr/{rid}", json={"text": "person fixed"})
    row = tree_of(client, item)[0]
    assert (row["text"], row["edited"]) == ("person fixed", True)

    revert(client, latest(client, "edit_text")["id"])
    row = tree_of(client, item)[0]
    # `edited` comes back FALSE — the machine's reading restored as an edited
    # one would be immune to the next run that reads it better.
    assert (row["text"], row["edited"]) == ("machine read", False)


def test_dismissing_and_restoring_round_trip(client):
    item = _items(client)[0]
    _read(client, item, [{"level": "block", "box": [0.1, 0.1, 0.4, 0.1],
                          "text": "noise"}])
    rid = tree_of(client, item)[0]["id"]
    client.patch(f"/api/ocr/{rid}", json={"dismissed": True})
    assert tree_of(client, item)[0]["dismissed"]
    revert(client, latest(client, "dismiss_text")["id"])
    assert not tree_of(client, item)[0]["dismissed"]


def test_moving_a_box_round_trips_with_its_quad(client):
    item = _items(client)[0]
    client.post("/api/ocr", json={"item_id": item, "x": 0.1, "y": 0.1,
                                  "w": 0.4, "h": 0.1, "text": "slanted"})
    rid = tree_of(client, item)[0]["id"]
    client.patch(f"/api/ocr/{rid}",
                 json={"quad": [[0.1, 0.1], [0.5, 0.12],
                                [0.5, 0.2], [0.1, 0.18]]})
    client.patch(f"/api/ocr/{rid}",
                 json={"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.1, "quad": []})
    assert tree_of(client, item)[0]["quad"] == []

    revert(client, latest(client, "move_text")["id"])
    row = tree_of(client, item)[0]
    # The quad travels on the event, or undoing the move puts back an
    # upright rectangle where a rotated shape was.
    assert row["x"] == pytest.approx(0.1)
    assert row["quad"] == [[0.1, 0.1], [0.5, 0.12], [0.5, 0.2], [0.1, 0.18]]


def test_deleting_a_block_restores_the_whole_subtree(client):
    item = _items(client)[0]
    _read(client, item, [
        {"level": "line", "box": [0.1, 0.1, 0.4, 0.1], "text": "hello world",
         "score": 0.97,
         "children": [
             {"level": "word", "box": [0.1, 0.1, 0.15, 0.1], "text": "hello",
              "score": 0.99},
             {"level": "word", "box": [0.3, 0.1, 0.15, 0.1], "text": "world",
              "score": 0.98},
         ]},
    ])
    rid = tree_of(client, item)[0]["id"]
    client.request("DELETE", f"/api/ocr/{rid}")
    assert tree_of(client, item) == []

    revert(client, latest(client, "delete_text")["id"])
    rows = tree_of(client, item)
    assert len(rows) == 1
    # The CASCADE took the words down with the line; the event carried the
    # tree, so the revert brings them back — text, scores and order.
    kids = rows[0]["children"]
    assert [k["text"] for k in kids] == ["hello", "world"]
    assert rows[0]["models"] == ["rapidocr_multi"]


def test_reordering_round_trips(client):
    item = _items(client)[0]
    _read(client, item, [
        {"level": "block", "box": [0.1, 0.1, 0.4, 0.1], "text": "one"},
        {"level": "block", "box": [0.1, 0.5, 0.4, 0.1], "text": "two"},
    ])
    ids = [r["id"] for r in tree_of(client, item)]
    client.post(f"/api/ocr/item/{item}/order",
                json={"region_ids": list(reversed(ids))})
    assert [r["text"] for r in tree_of(client, item)] == ["two", "one"]
    revert(client, latest(client, "reorder_text")["id"])
    assert [r["text"] for r in tree_of(client, item)] == ["one", "two"]


# ---- the applier's own promises --------------------------------------------

def test_a_rerun_keeps_a_correction_and_a_dismissal(client):
    """The whole point of the feature: reconciliation makes re-running free.
    (The pure rules are `tests/core/test_ocr_reconcile.py`; this is the same
    promise through the real applier and DB.)"""
    item = _items(client)[0]
    _read(client, item, [
        {"level": "block", "box": [0.1, 0.1, 0.4, 0.1], "text": "misread"},
        {"level": "block", "box": [0.1, 0.5, 0.4, 0.1], "text": "noise"},
    ])
    rows = tree_of(client, item)
    client.patch(f"/api/ocr/{rows[0]['id']}", json={"text": "fixed"})
    client.patch(f"/api/ocr/{rows[1]['id']}", json={"dismissed": True})

    _read(client, item, [
        {"level": "block", "box": [0.11, 0.1, 0.4, 0.1], "text": "reread"},
        {"level": "block", "box": [0.1, 0.5, 0.4, 0.1], "text": "noise"},
    ])
    rows = tree_of(client, item)
    live = [r for r in rows if not r["dismissed"]]
    hidden = [r for r in rows if r["dismissed"]]
    assert len(live) == 1 and len(hidden) == 1
    # The correction survives; the geometry follows the engine.
    assert live[0]["text"] == "fixed"
    assert live[0]["x"] == pytest.approx(0.11)
    # The dismissal ABSORBED its detection rather than gaining a twin.
    assert hidden[0]["text"] == "noise"


def test_a_run_records_itself_even_when_it_finds_nothing(client):
    """An item an engine read NOTHING in is exactly the item `skip_done`
    must not run again — `ItemFaceRun`'s reasoning, on `ItemTextRun`."""
    item = _items(client)[0]
    _read(client, item, [])
    detail = client.get(f"/api/items/{item}").json()
    assert detail["text_models"] == ["rapidocr_multi"]
    assert detail["text_count"] == 0


def test_skip_done_leaves_out_the_items_a_model_already_read(client):
    items = _items(client)[:2]
    _read(client, items[0], [])
    r = client.post("/api/ml/jobs", json={
        "kind": "ocr", "model": "rapidocr_multi", "item_ids": items,
        "skip_done": True}).json()
    assert r["skipped"] == 1
    # The queued job covers only the unread item. A batch kind makes ONE job.
    jobs = client.get("/api/ml/jobs").json()["jobs"]
    mine = [j for j in jobs if j["kind"] == "ocr"]
    assert mine and mine[0]["item_count"] == 1
