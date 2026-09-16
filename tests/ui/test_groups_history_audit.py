"""Every mutation a group can undergo: is it in the log, and does undoing it
put the library back?

The Tags tab's sweep, one sidebar along, and written for the same reason —
three of these changed the library with nothing to show for it and nothing to
undo. A group could be RENAMED, re-styled, DRAGGED into another folder and
DUPLICATED, and History said nothing about any of it: `ops/groups.update`,
`move` and `duplicate` simply did not log. The rename was the one that bit,
because the tree's own "no two siblings share a name" rule renames the group
somebody drags — so a drop could change a group's name with no record of what
it had been.

Each case drives the API the sidebar calls, asserts an event, reverts it, and
asserts the state came back. The sequence ops are here for the same reason:
they were the one whole subsystem with no logging at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.importer import Importer, ImportOptions
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=False)
        )
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def latest(c, action: str) -> dict:
    rows = c.get("/api/history").json()["events"]
    hits = [e for e in rows if e["action"] == action]
    assert hits, f"no {action} event was logged"
    return hits[0]


def revert(c, event_id: int) -> None:
    res = c.post("/api/history/revert", json={"event_ids": [event_id]}).json()
    assert res["reverted"] == [event_id], f"revert failed: {res}"


def tree(c) -> list[dict]:
    return c.get("/api/groups").json()


def find(c, name: str) -> dict | None:
    def walk(rows):
        for r in rows:
            if r["name"] == name:
                return r
            got = walk(r.get("children") or [])
            if got:
                return got
        return None

    return walk(tree(c))


def make_group(c, name: str, **body) -> int:
    return c.post("/api/groups", json={"name": name, **body}).json()["id"]


def items(c) -> list[int]:
    return [i["id"] for i in c.get("/api/items").json()["items"]]


# ---- the group itself -------------------------------------------------------


def test_editing_a_group_is_logged_and_reverts(client):
    gid = make_group(client, "Trips", icon="folder")
    client.patch(f"/api/groups/{gid}",
                 json={"name": "Journeys", "icon": "map", "color": "#ff0000"})
    ev = latest(client, "edit_group")
    assert ev["data"]["old"] == {"name": "Trips", "icon": "folder",
                                 "color": None}
    assert find(client, "Journeys") is not None

    revert(client, ev["id"])
    row = find(client, "Trips")
    assert row is not None and row["icon"] == "folder"
    assert row.get("color") in (None, "")
    assert find(client, "Journeys") is None


def test_a_save_that_changes_nothing_writes_no_event(client):
    gid = make_group(client, "Trips", icon="folder")
    before = len(client.get("/api/history").json()["events"])
    client.patch(f"/api/groups/{gid}", json={"name": "Trips",
                                             "icon": "folder"})
    assert len(client.get("/api/history").json()["events"]) == before


def test_moving_a_group_is_logged_and_reverts(client):
    gid = make_group(client, "Trips")
    shelf = make_group(client, "Albums")
    client.post(f"/api/groups/{gid}/move", json={"new_parent_id": shelf})
    ev = latest(client, "move_group")
    assert ev["data"]["old_parent_id"] is None
    assert ev["data"]["parent_id"] == shelf
    assert [c["name"] for c in find(client, "Albums")["children"]] == ["Trips"]

    revert(client, ev["id"])
    assert find(client, "Albums")["children"] == []
    assert any(r["name"] == "Trips" for r in tree(client))


def test_the_rename_a_move_forces_reverts_with_it(client):
    """The one that made this test module worth writing.

    A level cannot hold two groups of one name, so dropping "Trips" into a
    shelf that already has one arrives as "Trips 2". That rename is part of
    the move, and undoing the move has to take it back off — otherwise the
    drop permanently renamed a group with nothing in the log saying so.
    """
    shelf = make_group(client, "Albums")
    make_group(client, "Trips", parent_id=shelf)
    gid = make_group(client, "Trips")
    client.post(f"/api/groups/{gid}/move", json={"new_parent_id": shelf})
    ev = latest(client, "move_group")
    assert ev["data"]["old_name"] == "Trips"
    assert ev["data"]["name"] == "Trips 2"

    revert(client, ev["id"])
    roots = [r["name"] for r in tree(client)]
    assert "Trips" in roots and "Trips 2" not in roots


def test_duplicating_a_group_is_logged_and_the_whole_copy_reverts(client):
    gid = make_group(client, "Trips")
    child = make_group(client, "Inner", parent_id=gid)
    assert child
    client.post(f"/api/groups/{gid}/duplicate", json={})
    ev = latest(client, "duplicate_group")
    assert find(client, "Trips 2") is not None
    assert find(client, "Trips 2")["children"], "the subtree came with it"

    revert(client, ev["id"])
    assert find(client, "Trips 2") is None
    # The ORIGINAL is untouched — an undo of a copy is not a delete.
    assert find(client, "Trips") is not None
    assert [c["name"] for c in find(client, "Trips")["children"]] == ["Inner"]


# ---- sequences --------------------------------------------------------------


def test_every_sequence_edit_is_logged_and_reverts(client):
    a, b = items(client)[:2]
    seq = client.post("/api/sequences",
                      json={"name": "Chapter", "item_ids": [a, b]}).json()["id"]
    created = latest(client, "create_sequence")

    members = [m["id"] for m
               in client.get(f"/api/sequences/{seq}").json()["members"]]
    client.post(f"/api/sequences/{seq}/reorder",
                json={"member_ids": list(reversed(members))})
    ev = latest(client, "reorder_sequence")
    after = [m["item_id"] for m
             in client.get(f"/api/sequences/{seq}").json()["members"]]
    assert after == [b, a]
    revert(client, ev["id"])
    assert [m["item_id"] for m
            in client.get(f"/api/sequences/{seq}").json()["members"]] == [a, b]

    client.patch(f"/api/sequences/{seq}", json={"name": "Chapter One"})
    ev = latest(client, "rename_sequence")
    revert(client, ev["id"])
    assert client.get(f"/api/sequences/{seq}").json()["name"] == "Chapter"

    # One member out — the sequence survives, and the member comes back in
    # its old place.
    client.post(f"/api/sequences/{seq}/remove", json={"member_ids": [members[0]]})
    ev = latest(client, "remove_sequence_members")
    assert client.get(f"/api/sequences/{seq}").json()["total"] == 1
    revert(client, ev["id"])
    assert [m["item_id"] for m
            in client.get(f"/api/sequences/{seq}").json()["members"]] == [a, b]

    revert(client, created["id"])
    assert client.get(f"/api/sequences/{seq}").status_code == 404


def test_removing_a_whole_sequence_reverts_to_the_same_members(client):
    a, b = items(client)[:2]
    seq = client.post("/api/sequences",
                      json={"name": "Chapter", "item_ids": [a, b]}).json()["id"]
    client.delete(f"/api/sequences/{seq}")
    ev = latest(client, "delete_sequence")
    assert client.get(f"/api/sequences/{seq}").status_code == 404

    revert(client, ev["id"])
    # A restored sequence is a NEW row (its container item is minted from it),
    # so it is found by what it holds rather than by its old id.
    rows = client.get("/api/sequences").json()
    rows = rows["rows"] if isinstance(rows, dict) else rows
    back = [r for r in rows if r["name"] == "Chapter"]
    assert len(back) == 1
    got = client.get(f"/api/sequences/{back[0]['id']}").json()
    assert [m["item_id"] for m in got["members"]] == [a, b]


# ---- tag boxes --------------------------------------------------------------


def test_drawing_a_box_is_logged_and_takes_its_tag_back(client):
    a = items(client)[0]
    box = client.post(f"/api/tags/assign/item/{a}/box",
                      json={"tag": "face",
                            "box": {"x": 0.1, "y": 0.1,
                                    "w": 0.2, "h": 0.2}}).json()
    ev = latest(client, "add_tag_box")
    detail = client.get(f"/api/items/{a}").json()
    assert "face" in [t["name"] for t in detail["tags"]]

    revert(client, ev["id"])
    detail = client.get(f"/api/items/{a}").json()
    assert "face" not in [t["name"] for t in detail["tags"]], (
        "drawing the box assigned the tag, so undoing it must unassign it")
    assert box["id"]


def test_moving_and_removing_a_box_revert(client):
    a = items(client)[0]
    box = client.post(f"/api/tags/assign/item/{a}/box",
                      json={"tag": "face",
                            "box": {"x": 0.1, "y": 0.1,
                                    "w": 0.2, "h": 0.2}}).json()["id"]
    client.patch(f"/api/tags/box/{box}",
                 json={"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2})
    ev = latest(client, "edit_tag_box")
    assert ev["data"]["old"]["x"] == pytest.approx(0.1)
    revert(client, ev["id"])
    got = [b for t in client.get(f"/api/items/{a}").json()["tags"]
           for b in (t.get("boxes") or [])]
    assert got and got[0]["x"] == pytest.approx(0.1)

    client.delete(f"/api/tags/box/{box}")
    ev = latest(client, "delete_tag_box")
    revert(client, ev["id"])
    got = [b for t in client.get(f"/api/items/{a}").json()["tags"]
           for b in (t.get("boxes") or [])]
    assert len(got) == 1 and got[0]["x"] == pytest.approx(0.1)
