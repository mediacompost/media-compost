"""History log: events are recorded on mutations, listed, and revertible."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.db import Event
from media_compost.history import log_event
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=True)
        )
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _first_item_id(client) -> int:
    return client.get("/api/items").json()["items"][0]["id"]


def test_add_tag_logs_revertible_event(client):
    iid = _first_item_id(client)
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "sunset", "negative": False})

    hist = client.get("/api/history").json()
    ev = next(e for e in hist["events"] if e["action"] == "add_tag")
    assert ev["source"] == "web"
    assert ev["entity_id"] == iid
    assert ev["data"]["tag"] == "sunset"
    assert ev["revertible"] is True and ev["reverted"] is False

    # The tag is really on the item.
    detail = client.get(f"/api/items/{iid}").json()
    assert any(t["name"] == "sunset" for t in detail["direct_tags"])

    # Revert removes it and marks the event reverted.
    res = client.post("/api/history/revert", json={"event_ids": [ev["id"]]}).json()
    assert res["reverted"] == [ev["id"]] and res["failed"] == []
    detail = client.get(f"/api/items/{iid}").json()
    assert not any(t["name"] == "sunset" for t in detail["direct_tags"])
    ev2 = next(e for e in client.get("/api/history").json()["events"]
               if e["id"] == ev["id"])
    assert ev2["reverted"] is True and ev2["revertible"] is False


def _events(client):
    return client.get("/api/history").json()["events"]


def _latest(client, action):
    return next(e for e in _events(client) if e["action"] == action)


def _by_id(client, eid):
    return next(e for e in _events(client) if e["id"] == eid)


def test_a_revert_can_itself_be_reverted_back_and_forth(client):
    """Undoing a revert does the original action again — and that revert can be
    undone in turn, so the chain alternates for as long as anyone keeps
    clicking. Each step strikes through the one it took back."""
    iid = _first_item_id(client)
    has = lambda: any(  # noqa: E731
        t["name"] == "storm" for t in client.get(f"/api/items/{iid}").json()["direct_tags"])
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "storm", "negative": False})
    add = _latest(client, "add_tag")
    assert has()

    # 1. Revert the tagging: the tag goes, the add is struck through.
    client.post("/api/history/revert", json={"event_ids": [add["id"]]})
    assert not has()
    r1 = _latest(client, "revert")
    assert _by_id(client, add["id"])["reverted"] is True
    assert r1["revertible"] is True  # a revert can be taken back

    # 2. Revert the revert: the tag is back, the revert is struck through, and
    #    the original add is no longer marked reverted.
    client.post("/api/history/revert", json={"event_ids": [r1["id"]]})
    assert has()
    assert _by_id(client, r1["id"])["reverted"] is True
    assert _by_id(client, add["id"])["reverted"] is False
    r2 = _latest(client, "revert")
    assert r2["id"] != r1["id"] and r2["revertible"] is True

    # 3. And back again — the direction flips every time, it does not repeat.
    client.post("/api/history/revert", json={"event_ids": [r2["id"]]})
    assert not has()
    assert _by_id(client, add["id"])["reverted"] is True


def test_deleting_a_tag_logs_each_items_removal_and_reverts_them(client):
    """Deleting a tag takes it off every item it was on, and each of those is a
    change of its own: they show in the History view (as one grouped row) and
    reverting the deletion brings the ASSIGNMENTS back, not just the empty tag."""
    ids = [e["id"] for e in client.get("/api/items").json()["items"][:2]]
    for iid in ids:
        client.post(f"/api/tags/assign/item/{iid}", json={"tag": "doomed", "negative": False})
    tag_id = next(t["id"] for t in client.get("/api/tags").json() if t["name"] == "doomed")

    res = client.delete(f"/api/tags/{tag_id}").json()
    assert len(res["event_ids"]) == 3  # one removal per item, plus the deletion
    removals = [e for e in _events(client) if e["action"] == "remove_tag"
                and e["data"].get("tag") == "doomed"]
    assert {e["data"]["item_id"] for e in removals} == set(ids)
    assert not any(t["name"] == "doomed" for t in client.get("/api/tags").json())

    # Reverting the whole deletion restores the tag AND both assignments.
    client.post("/api/history/revert", json={"event_ids": res["event_ids"]})
    assert any(t["name"] == "doomed" for t in client.get("/api/tags").json())
    for iid in ids:
        detail = client.get(f"/api/items/{iid}").json()
        assert any(t["name"] == "doomed" for t in detail["direct_tags"])


def test_undoing_a_tag_deletion_restores_everything_that_went_with_it(client):
    """A tag takes a lot with it: what it entailed and what entailed IT, the
    library groups that assigned it, its aliases (whose foreign key deletes them
    outright), and — per item — the sign, the tag group and every box or time
    range of the assignment. Undo has to bring all of that back, or the counts
    come back wrong and a film's ranges are simply gone."""
    iid = _first_item_id(client)
    gid = client.post("/api/groups", json={"name": "Shelf", "icon": "folder"}).json()["id"]
    client.post("/api/tags", json={"name": "dog"})
    client.post("/api/tags", json={"name": "pet"})
    client.post("/api/tags", json={"name": "poodle", "implies": "doomed"})
    client.post("/api/tags", json={"name": "hound", "alias_of": "doomed"})
    tid = next(t["id"] for t in client.get("/api/tags").json() if t["name"] == "doomed")
    client.post(f"/api/tags/{tid}/implies", json={"name": "dog"})
    client.post(f"/api/tags/{tid}/implies", json={"name": "pet"})
    client.post(f"/api/tags/assign/group/{gid}", json={"tag": "doomed", "negative": False})
    # An assignment with shape: a named tag group and a time range with a sign.
    client.post(f"/api/tags/item/{iid}/group-tag",
                json={"tag": "doomed", "group_id": None})
    grp = client.post(f"/api/tags/item/{iid}/groups", json={"name": "Cast"}).json()
    client.post(f"/api/tags/item/{iid}/group-tag",
                json={"tag": "doomed", "group_id": grp["id"]})
    client.post(f"/api/tags/assign/item/{iid}/box", json={
        "tag": "doomed", "group_id": grp["id"],
        "box": {"x": None, "y": None, "w": None, "h": None,
                "time_start": 4.0, "time_end": 9.0, "negative": True},
    })

    res = client.delete(f"/api/tags/{tid}").json()
    names = {t["name"] for t in client.get("/api/tags").json()}
    assert "doomed" not in names and "hound" not in names  # the alias went too

    client.post("/api/history/revert", json={"event_ids": res["event_ids"]})
    rows = {t["name"]: t for t in client.get("/api/tags").json()}
    assert set(rows["doomed"]["implies"]) == {"dog", "pet"}   # what it entailed
    assert rows["poodle"]["implies"] == ["doomed"]            # and what entailed it
    assert rows["hound"]["alias_of"] == "doomed"              # its alias is back
    tree = client.get("/api/groups").json()
    shelf = next(g for g in tree if g["id"] == gid)
    assert [t["name"] for t in shelf["tags"]] == ["doomed"]   # the group assigns it again

    detail = client.get(f"/api/items/{iid}").json()
    inst = [i for i in detail["tag_instances"] if i["name"] == "doomed"]
    assert {i["group_id"] for i in inst} == {None, grp["id"]}  # both placements
    box = next(b for i in inst for b in i["boxes"])
    assert (box["time_start"], box["time_end"], box["negative"]) == (4.0, 9.0, True)


def test_a_revert_of_something_unreplayable_stays_final(client):
    """Only actions that can be honestly replayed offer the button. Creating a
    tag is not one: doing it again would hand out a new id, and the log would
    quietly stop matching the library."""
    client.post("/api/tags", json={"name": "unrepeatable"})
    ev = _latest(client, "create_tag")
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    rev = _latest(client, "revert")
    assert rev["revertible"] is False
    res = client.post("/api/history/revert", json={"event_ids": [rev["id"]]}).json()
    assert res["failed"] == [rev["id"]] and res["reverted"] == []


def test_reverting_a_revert_restores_a_setter_to_its_new_value(client):
    """A setter event records both sides, which is what lets the redo re-apply
    it: reverting the revert of a comment edit puts the NEW comment back."""
    tid = client.post("/api/tags", json={"name": "weather"}).json()["id"]
    client.patch(f"/api/tags/{tid}", json={"comment": "sky and rain"})
    ev = _latest(client, "comment_tag")
    comment = lambda: next(  # noqa: E731
        t["comment"] for t in client.get("/api/tags").json() if t["id"] == tid)

    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert comment() == ""
    rev = _latest(client, "revert")
    client.post("/api/history/revert", json={"event_ids": [rev["id"]]})
    assert comment() == "sky and rain"


def test_remove_tag_revert_restores_it(client):
    iid = _first_item_id(client)
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "cat", "negative": True})
    client.delete(f"/api/tags/assign/item/{iid}/cat")

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "remove_tag")
    # Reverting a removal restores the tag with its original polarity.
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    detail = client.get(f"/api/items/{iid}").json()
    tag = next(t for t in detail["direct_tags"] if t["name"] == "cat")
    assert tag["negative"] is True


def test_create_group_event_and_revert(client):
    gid = client.post("/api/groups", json={"name": "Trip", "icon": "folder"}).json()["id"]
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "create_group")
    assert ev["data"]["group_id"] == gid and ev["revertible"] is True

    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    tree = client.get("/api/groups").json()

    def _ids(nodes):
        for n in nodes:
            yield n["id"]
            yield from _ids(n["children"])

    assert gid not in set(_ids(tree))


def test_group_tag_add_and_single_click_removal(client):
    """A tag added to the ungrouped group is logged and removed in ONE click
    (deleting its last placement fully unassigns it — the two-click bug)."""
    iid = _first_item_id(client)
    # Add via the sidebar path (creates an ItemTag + a placement).
    client.post(f"/api/tags/item/{iid}/group-tag", json={"tag": "test", "group_id": None})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "add_tag")
    assert ev["data"]["tag"] == "test"
    detail = client.get(f"/api/items/{iid}").json()
    inst = next(i for i in detail["tag_instances"] if i["name"] == "test")

    # Removing the single placement unassigns the tag entirely — one click.
    client.delete(f"/api/tags/placements/{inst['placement_id']}")
    detail = client.get(f"/api/items/{iid}").json()
    assert not any(i["name"] == "test" for i in detail["tag_instances"])
    assert not any(t["name"] == "test" for t in detail["direct_tags"])
    # And that removal is logged.
    assert any(e["action"] == "remove_tag" and e["data"]["tag"] == "test"
               for e in client.get("/api/history").json()["events"])


def test_caption_add_edit_remove_logged_and_revertible(client):
    iid = _first_item_id(client)
    cid = client.post(f"/api/items/{iid}/captions", json={"text": "a lake"}).json()["id"]
    client.patch(f"/api/items/{iid}/captions/{cid}", json={"text": "a blue lake"})
    events = client.get("/api/history").json()["events"]
    assert any(e["action"] == "add_caption" for e in events)
    assert any(e["action"] == "edit_caption" for e in events)

    # Revert the add_caption -> the caption is deleted.
    add_ev = next(e for e in events if e["action"] == "add_caption")
    assert add_ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [add_ev["id"]]})
    assert client.get(f"/api/items/{iid}").json()["captions"] == []


def test_adding_an_implication_is_revertible(client):
    """"A implies B" is logged and reverting removes the edge again."""
    poodle = client.post("/api/tags", json={"name": "poodle"}).json()
    client.post("/api/tags", json={"name": "dog"})

    def implies_of(name):
        rows = client.get("/api/tags").json()
        return next(r["implies"] for r in rows if r["name"] == name)

    client.post(f"/api/tags/{poodle['id']}/implies", json={"name": "dog"})
    assert implies_of("poodle") == ["dog"]

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "add_tag_implication")
    assert ev["revertible"] is True
    res = client.post("/api/history/revert",
                      json={"event_ids": [ev["id"]]}).json()
    assert res["reverted"] == [ev["id"]]
    assert implies_of("poodle") == []


def test_removing_an_implication_is_revertible(client):
    """And the other direction: undoing a removal puts the edge back."""
    kitten = client.post("/api/tags", json={"name": "kitten"}).json()
    client.post("/api/tags", json={"name": "cat"})
    client.post(f"/api/tags/{kitten['id']}/implies", json={"name": "cat"})
    client.delete(f"/api/tags/{kitten['id']}/implies/cat")

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "remove_tag_implication")
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    rows = client.get("/api/tags").json()
    assert next(r["implies"] for r in rows if r["name"] == "kitten") == ["cat"]


def test_comment_tag_is_revertible(client):
    """Editing a tag comment is logged and reverting restores the prior text."""
    t = client.post("/api/tags", json={"name": "beach", "comment": "sandy"}).json()
    client.patch(f"/api/tags/{t['id']}", json={"comment": "sunny shore"})

    def comment_of(name):
        rows = client.get("/api/tags").json()
        return next(r["comment"] for r in rows if r["name"] == name)

    assert comment_of("beach") == "sunny shore"
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "comment_tag")
    assert ev["revertible"] is True and ev["data"]["old_comment"] == "sandy"
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert comment_of("beach") == "sandy"


def test_merge_item_shows_in_history_and_reverts(client):
    """Merging two items is logged and reverting recreates the source item with
    its file, tag and group put back."""
    items = client.get("/api/items").json()["items"]
    a, b = items[0]["id"], items[1]["id"]
    total = client.get("/api/items").json()["total"]
    b_name = client.get(f"/api/items/{b}").json()["name"]
    b_created = client.get(f"/api/items/{b}").json()["created_at"]
    client.post(f"/api/tags/assign/item/{b}", json={"tag": "mergecheck", "negative": False})

    client.post("/api/items/merge", json={"source_id": b, "target_id": a})
    after = client.get("/api/items").json()
    assert after["total"] == total - 1
    assert not any(it["id"] == b for it in after["items"])
    assert any(t["name"] == "mergecheck"
               for t in client.get(f"/api/items/{a}").json()["direct_tags"])

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "merge_item")
    assert ev["revertible"] is True
    res = client.post("/api/history/revert", json={"event_ids": [ev["id"]]}).json()
    assert res["reverted"] == [ev["id"]]
    # The source item is back (count restored) and its tag left the target.
    listing = client.get("/api/items").json()
    assert listing["total"] == total
    assert not any(t["name"] == "mergecheck"
                   for t in client.get(f"/api/items/{a}").json()["direct_tags"])
    # The recreated item keeps the source's original import date (so it doesn't
    # float to the top of the recently-imported sort as if brand new).
    restored = next(it for it in listing["items"]
                    if it["name"] == b_name and it["id"] != a)
    assert client.get(f"/api/items/{restored['id']}").json()["created_at"] == b_created


def test_split_item_shows_in_history_and_reverts(client):
    """Splitting a file into its own item is logged; reverting removes the new
    item and moves the file back."""
    items = client.get("/api/items").json()["items"]
    a, b = items[0]["id"], items[1]["id"]
    # Merge first so item ``a`` has two files to split apart.
    client.post("/api/items/merge", json={"source_id": b, "target_id": a})
    detail = client.get(f"/api/items/{a}").json()
    assert len(detail["files"]) >= 2
    total = client.get("/api/items").json()["total"]
    fid = next(f["id"] for f in detail["files"] if not f["active"])

    new_id = client.post(f"/api/files/{fid}/split").json()["item_id"]
    assert client.get("/api/items").json()["total"] == total + 1
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "split_item")
    assert ev["revertible"] is True

    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    listing = client.get("/api/items").json()
    assert listing["total"] == total
    assert not any(it["id"] == new_id for it in listing["items"])
    # The file is back on the original item.
    assert any(f["id"] == fid for f in client.get(f"/api/items/{a}").json()["files"])


def test_splitting_several_files_reverts_them_all(client):
    """A split of several logs one event, and reverting it puts every file back
    and takes the split-off item away."""
    ids = [i["id"] for i in client.get("/api/items").json()["items"]]
    host = ids[0]
    for other in ids[1:3]:
        client.post("/api/items/merge", json={"source_id": other, "target_id": host})
    files = client.get(f"/api/items/{host}").json()["files"]
    assert len(files) >= 3
    picked = [f["id"] for f in files[:2]]
    total = client.get("/api/items").json()["total"]

    new_id = client.post("/api/files/split", json={"file_ids": picked}).json()["item_id"]
    assert client.get("/api/items").json()["total"] == total + 1
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "split_item")
    assert ev["revertible"] is True

    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    listing = client.get("/api/items").json()
    assert listing["total"] == total
    assert not any(it["id"] == new_id for it in listing["items"])
    back = {f["id"] for f in client.get(f"/api/items/{host}").json()["files"]}
    assert set(picked) <= back


def test_set_active_file_is_revertible(client):
    """Switching the active source file is logged and reverting restores the
    previous one."""
    items = client.get("/api/items").json()["items"]
    a, b = items[0]["id"], items[1]["id"]
    # Merge so item ``a`` has two source files to switch between.
    client.post("/api/items/merge", json={"source_id": b, "target_id": a})
    detail = client.get(f"/api/items/{a}").json()
    prev_active = detail["active_file_id"]
    other = next(f["id"] for f in detail["files"] if f["id"] != prev_active)

    client.patch(f"/api/items/{a}", json={"active_file_id": other})
    assert client.get(f"/api/items/{a}").json()["active_file_id"] == other
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "set_active_file")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert client.get(f"/api/items/{a}").json()["active_file_id"] == prev_active


def test_add_link_is_revertible(client):
    """Adding a link is logged; reverting removes the relationship."""
    items = client.get("/api/items").json()["items"]
    a, b = items[0]["id"], items[1]["id"]
    client.post("/api/relationships", json={"from_item_id": a, "to_item_id": b, "kind": "manual"})
    assert len(client.get(f"/api/items/{a}/relationships").json()) == 1

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "add_link")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert client.get(f"/api/items/{a}/relationships").json() == []


def test_remove_link_is_revertible(client):
    """Removing a link is logged; reverting recreates it (with its link tags)."""
    items = client.get("/api/items").json()["items"]
    a, b = items[0]["id"], items[1]["id"]
    rid = client.post("/api/relationships", json={"from_item_id": a, "to_item_id": b, "kind": "manual"}).json()["id"]
    client.post(f"/api/relationships/{rid}/tags", json={"name": "similar"})

    client.delete(f"/api/relationships/{rid}")
    assert client.get(f"/api/items/{a}/relationships").json() == []
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "remove_link")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    rels = client.get(f"/api/items/{a}/relationships").json()
    assert len(rels) == 1 and rels[0]["tags"] == ["similar"]


def test_link_meta_tags_are_logged_and_revert(client):
    """A link's meta tags are the same namespace as a caption's and a tag
    group's, and both of those have always been logged. These two wrote
    nothing at all, so the History said the edit had not happened and the
    sidebar's Undo had no event to offer."""
    items = client.get("/api/items").json()["items"]
    a, b = items[0]["id"], items[1]["id"]
    rid = client.post("/api/relationships", json={
        "from_item_id": a, "to_item_id": b, "kind": "manual"}).json()["id"]

    client.post(f"/api/relationships/{rid}/tags", json={"name": "same_scene"})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "add_link_tag")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert client.get(f"/api/items/{a}/relationships").json()[0]["tags"] == []

    # …and the other direction, including the redo the revert's own entry is.
    client.post(f"/api/relationships/{rid}/tags", json={"name": "same_scene"})
    client.delete(f"/api/relationships/{rid}/tags/same_scene")
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "remove_link_tag")
    assert ev["revertible"] is True
    res = client.post("/api/history/revert",
                      json={"event_ids": [ev["id"]]}).json()
    rels = client.get(f"/api/items/{a}/relationships").json()
    assert rels[0]["tags"] == ["same_scene"]
    # Reverting the revert replays the removal — that is what the sidebar's
    # one Undo/Redo button is.
    assert res["events"]
    client.post("/api/history/revert", json={"event_ids": res["events"]})
    assert client.get(f"/api/items/{a}/relationships").json()[0]["tags"] == []


def test_non_revertible_action_reports_false(client):
    iid = _first_item_id(client)
    client.post("/api/items/delete", json={"item_ids": [iid]})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "delete_item")
    assert ev["revertible"] is False
    res = client.post("/api/history/revert", json={"event_ids": [ev["id"]]}).json()
    assert res["failed"] == [ev["id"]] and res["reverted"] == []


def test_trash_and_restore_are_revertible(client):
    iid = _first_item_id(client)

    def in_trash():
        return any(it["id"] == iid for it in
                   client.get("/api/items?trash=true").json()["items"])

    def in_library():
        return any(it["id"] == iid for it in
                   client.get("/api/items").json()["items"])

    # Trash → revertible; reverting restores it out of the Trash.
    client.post("/api/items/trash", json={"item_ids": [iid]})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "trash_item")
    assert ev["revertible"] is True and in_trash()
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert not in_trash() and in_library()

    # Restore-from-trash → revertible; reverting puts it back in the Trash.
    client.post("/api/items/trash", json={"item_ids": [iid]})
    client.post("/api/items/restore", json={"item_ids": [iid]})
    rev = next(e for e in client.get("/api/history").json()["events"]
               if e["action"] == "restore_item")
    assert rev["revertible"] is True and in_library()
    client.post("/api/history/revert", json={"event_ids": [rev["id"]]})
    assert in_trash()


def test_import_is_revertible_trashes_new_items(client, tmp_path):
    from media_compost.testing import make_image

    # Import a brand-new image via the endpoint (logs an "import" event).
    import time

    src = tmp_path / "extra"
    src.mkdir()
    make_image(src / "z.png", seed=1234, size=(640, 480))
    before = client.get("/api/items").json()["total"]
    job = client.post("/api/import/paths", json={"paths": [str(src)]}).json()
    # The import runs in a background thread; wait for it to finish.
    for _ in range(100):
        st = client.get(f"/api/import/{job['id']}").json()
        if st["status"] != "running":
            break
        time.sleep(0.05)
    assert st["status"] == "done"
    after = client.get("/api/items").json()["total"]
    assert after == before + 1

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "import")
    assert ev["revertible"] is True
    new_ids = ev["data"]["imported_item_ids"]
    assert len(new_ids) == 1

    # Reverting the import moves the created item(s) to the Trash.
    res = client.post("/api/history/revert", json={"event_ids": [ev["id"]]}).json()
    assert res["reverted"] == [ev["id"]]
    assert client.get("/api/items").json()["total"] == before
    trash = client.get("/api/items?trash=true").json()
    assert any(it["id"] == new_ids[0] for it in trash["items"])


def _latest(client, action: str) -> dict:
    """The newest event of one action."""
    evs = client.get("/api/history?limit=50").json()["events"]
    return [e for e in evs if e["action"] == action][0]


def _revert(client, ev: dict) -> None:
    r = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["reverted"] == [ev["id"]], r.json()


def test_meta_tags_on_a_caption_are_revertible(client):
    item = _first_item_id(client)
    client.post(f"/api/items/{item}/captions", json={"text": "a red car"})
    cap = client.get(f"/api/items/{item}").json()["captions"][0]["id"]

    client.post(f"/api/items/{item}/captions/{cap}/tags", json={"name": "draft"})
    _revert(client, _latest(client, "add_caption_tag"))
    caps = client.get(f"/api/items/{item}").json()["captions"]
    assert caps[0]["tags"] == []

    # …and removing one undoes back to having it.
    client.post(f"/api/items/{item}/captions/{cap}/tags", json={"name": "draft"})
    client.delete(f"/api/items/{item}/captions/{cap}/tags/draft")
    _revert(client, _latest(client, "remove_caption_tag"))
    caps = client.get(f"/api/items/{item}").json()["captions"]
    assert caps[0]["tags"] == ["draft"]


def test_meta_tags_on_a_tag_group_are_revertible(client):
    item = _first_item_id(client)
    gid = client.post(f"/api/tags/item/{item}/groups",
                      json={"name": "Person A"}).json()["id"]

    client.post(f"/api/tags/groups/{gid}/tags", json={"name": "main"})
    _revert(client, _latest(client, "add_tag_group_tag"))
    groups = client.get(f"/api/items/{item}").json()["tag_groups"]
    assert groups[0]["tags"] == []

    client.post(f"/api/tags/groups/{gid}/tags", json={"name": "main"})
    client.delete(f"/api/tags/groups/{gid}/tags/main")
    _revert(client, _latest(client, "remove_tag_group_tag"))
    groups = client.get(f"/api/items/{item}").json()["tag_groups"]
    assert groups[0]["tags"] == ["main"]


def test_moving_a_tag_between_groups_is_revertible(client):
    item = _first_item_id(client)
    a = client.post(f"/api/tags/item/{item}/groups", json={"name": "A"}).json()["id"]
    b = client.post(f"/api/tags/item/{item}/groups", json={"name": "B"}).json()["id"]
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "poodle", "group_id": a})

    def group_of(name: str):
        for i in client.get(f"/api/items/{item}").json()["tag_instances"]:
            if i["name"] == name:
                return i["group_id"]
        return "absent"

    assert group_of("poodle") == a
    client.post(f"/api/tags/item/{item}/move-instance",
                json={"name": "poodle", "from_group_id": a, "to_group_id": b})
    assert group_of("poodle") == b

    _revert(client, _latest(client, "move_tag_group"))
    assert group_of("poodle") == a, "the tag did not go back to its group"


def test_renaming_a_tag_is_logged_and_revertible(client):
    """A rename is a change like any other — it was silently absent from the
    log, so there was nothing to see and nothing to undo."""
    iid = _first_item_id(client)
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "sunst", "negative": False})
    tid = next(t["id"] for t in client.get("/api/tags").json() if t["name"] == "sunst")
    client.patch(f"/api/tags/{tid}", json={"name": "sunset"})

    ev = _latest(client, "rename_tag")
    assert ev["data"]["old_name"] == "sunst" and ev["data"]["name"] == "sunset"
    assert ev["revertible"] is True
    names = lambda: {t["name"] for t in client.get("/api/tags").json()}  # noqa: E731
    assert "sunset" in names() and "sunst" not in names()

    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert "sunst" in names() and "sunset" not in names()
    # …and back again, since a revert can be taken back.
    client.post("/api/history/revert", json={"event_ids": [_latest(client, "revert")["id"]]})
    assert "sunset" in names()


def test_merging_a_tag_moves_everything_and_can_be_undone(client):
    """A merge is a rename onto a name that is taken: everything the tag
    carries moves across, each item's change is logged as its own event, and
    reverting the set puts both tags back the way they were."""
    a, b = [e["id"] for e in client.get("/api/items").json()["items"][:2]]
    client.post("/api/tags", json={"name": "cat"})
    client.post("/api/tags", json={"name": "animal"})
    client.post("/api/tags", json={"name": "kitten"})
    kid = next(t["id"] for t in client.get("/api/tags").json() if t["name"] == "kitten")
    client.post(f"/api/tags/{kid}/implies", json={"name": "animal"})
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "kitten", "negative": False})
    client.post(f"/api/tags/assign/item/{b}", json={"tag": "kitten", "negative": False})
    client.post(f"/api/tags/assign/item/{b}", json={"tag": "cat", "negative": False})

    res = client.post(f"/api/tags/{kid}/merge", json={"into": "cat"}).json()
    rows = {t["name"]: t for t in client.get("/api/tags").json()}
    # The tag is gone as a tag and survives as an alias; the target inherited
    # its implication and both of its items.
    assert rows["kitten"]["alias_of"] == "cat"
    assert rows["cat"]["implies"] == ["animal"]
    assert rows["cat"]["positive"] == 2
    for iid in (a, b):
        assert any(t["name"] == "cat"
                   for t in client.get(f"/api/items/{iid}").json()["direct_tags"])

    # Each item's change is its own event, so History shows what happened.
    kinds = [e["action"] for e in _events(client)[:6]]
    assert {"delete_tag", "remove_tag", "add_tag", "add_tag_implication"} <= set(kinds)

    # Undo: kitten is a tag again, with its implication and its items; the
    # target keeps only what it had before.
    client.post("/api/history/revert", json={"event_ids": res["event_ids"]})
    rows = {t["name"]: t for t in client.get("/api/tags").json()}
    assert rows["kitten"]["alias_of"] in (None, "")
    assert rows["kitten"]["implies"] == ["animal"]
    assert rows["kitten"]["positive"] == 2
    assert rows["cat"]["positive"] == 1
    assert rows["cat"]["implies"] == []


def test_history_can_be_asked_what_happened_since(client):
    """`after_id` is how a caller finds out what the thing it just did wrote.

    The sidebar's undo bar takes a watermark before a removal and reads the
    answer back afterwards, rather than ten endpoints each learning to return
    their own event ids. Ids are the watermark and not a timestamp because two
    events written inside one request share a clock reading to the second.
    """
    iid = _first_item_id(client)
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "before"})
    mark = client.get("/api/history?limit=1").json()["events"][0]["id"]

    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "after_one"})
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "after_two"})

    since = client.get(f"/api/history?limit=50&after_id={mark}").json()
    ids = [e["id"] for e in since["events"]]
    assert len(ids) == 2, "only what happened after the watermark"
    assert all(i > mark for i in ids)
    # Newest first, like the unfiltered page.
    assert ids == sorted(ids, reverse=True)
    # And the total still describes the whole log, not the filtered slice.
    assert since["total"] > len(ids)

    # Nothing since the newest event.
    newest = client.get("/api/history?limit=1").json()["events"][0]["id"]
    assert client.get(f"/api/history?after_id={newest}").json()["events"] == []


def test_undoing_a_move_out_of_pending_makes_it_pending_again(lib):
    """The move endpoint recomputes `pending` from where the placements are;
    its undo has to as well.

    Without it, moving a machine-suggested tag out of its Pending group and
    then undoing leaves the tag back inside that group but no longer flagged —
    a state nothing else can produce, and one where search, training and export
    read it as approved while the box around it says it is still waiting.
    """
    from sqlalchemy import select

    from media_compost.db import (
        Item, ItemTag, ItemTagGroup, ItemTagPlacement, Tag,
    )
    from media_compost.history import revert_event
    from media_compost.ops import ctx_for, tagassign

    _cfg, db, _store = lib
    with db.session() as s:
        item = Item(name="page")
        tag = Tag(name="guessed")
        s.add_all([item, tag])
        s.flush()
        # What a tag-generation run leaves behind: a SYSTEM group, the tag in
        # it, and the assignment flagged pending.
        grp = ItemTagGroup(item_id=item.id, name="Pending: test", system=True)
        it_tag = ItemTag(item_id=item.id, tag_id=tag.id, pending=True)
        s.add_all([grp, it_tag])
        s.flush()
        s.add(ItemTagPlacement(item_tag_id=it_tag.id, group_id=grp.id))
        s.commit()
        item_id, it_tag_id, gid = item.id, it_tag.id, grp.id

    # Move it OUT — which accepts it, exactly as dragging it to a real group
    # does — and log the move the way the endpoint does.
    with db.session() as s:
        src = tagassign.ensure_placement(ctx_for(s), it_tag_id, gid)
        tagassign.merge_placement_into_group(ctx_for(s), src, None)
        tagassign.recompute_pending(ctx_for(s), it_tag_id)
        ev = log_event(
            s, source="web", action="move_tag_group", entity_type="item",
            entity_id=item_id,
            summary="Moved tag guessed out of Pending",
            data={"item_id": item_id, "tag": "guessed",
                  "from_group": "Pending: test", "to_group": "Ungrouped",
                  "from_group_id": gid, "to_group_id": None})
        s.commit()
        assert s.get(ItemTag, it_tag_id).pending is False, "moving out accepts it"
        ev_id = ev.id

    # Undoing puts it back in the Pending group — and pending WITH it.
    with db.session() as s:
        revert_event(s, s.get(Event, ev_id))
        s.commit()
    with db.session() as s:
        back = s.execute(select(ItemTagPlacement.group_id).where(
            ItemTagPlacement.item_tag_id == it_tag_id)).scalars().all()
        assert back == [gid], "the placement went back to the Pending group"
        assert s.get(ItemTag, it_tag_id).pending is True, \
            "and the flag came back with it"


# ---- clearing the log ------------------------------------------------------


def test_clearing_the_history_empties_it_but_says_it_happened(client):
    """The log is append-only by design, and this is the one way out of that.

    It leaves ONE entry behind, deliberately: a log that is simply empty
    cannot be told from a library nobody has ever edited, and somebody coming
    back to find no history at all deserves the sentence rather than the
    doubt.
    """
    item_id = _first_item_id(client)
    client.post(f"/api/tags/assign/item/{item_id}", json={"tag": "one"})
    client.post(f"/api/tags/assign/item/{item_id}", json={"tag": "two"})
    before = client.get("/api/history", params={"limit": 500}).json()
    assert before["total"] >= 2

    r = client.delete("/api/history")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == before["total"]

    after = client.get("/api/history", params={"limit": 500}).json()
    assert after["total"] == 1
    only = after["events"][0]
    assert only["action"] == "clear_history"
    assert str(before["total"]) in only["summary"]
    # Nothing to put back, and it says so rather than offering a button that
    # cannot work.
    assert only["revertible"] is False


def test_clearing_the_history_leaves_the_library_alone(client):
    """It changes what the library REMEMBERS having done, not what it holds."""
    item_id = _first_item_id(client)
    client.post(f"/api/tags/assign/item/{item_id}", json={"tag": "kept"})
    tags_before = client.get(f"/api/items/{item_id}").json()["direct_tags"]
    assert tags_before

    client.delete("/api/history")
    assert client.get(f"/api/items/{item_id}").json()["direct_tags"] == tags_before
    assert client.get("/api/items").json()["items"]


def test_a_cleared_history_cannot_be_reverted_through(client):
    """A revert reads the entry it is undoing, so clearing makes everything
    that has already happened permanent. That is the cost the UI warns about."""
    item_id = _first_item_id(client)
    client.post(f"/api/tags/assign/item/{item_id}", json={"tag": "gone_for_good"})
    ev_id = client.get("/api/history", params={"limit": 5}).json()["events"][0]["id"]

    client.delete("/api/history")
    r = client.post("/api/history/revert", json={"event_ids": [ev_id]})
    assert r.status_code == 200, r.text
    assert r.json()["reverted"] == []          # the entry is not there to read
    assert client.get(f"/api/items/{item_id}").json()["direct_tags"]
