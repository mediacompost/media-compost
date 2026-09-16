"""Every mutation the Tags tab can make: is it in the log, and does undoing it
put the library back?

This is a sweep, not a sample. The Tags tab has two modes and a dozen actions
between them, and several of them turned out to be invisible in History — a
rename, a group tag, and the entire meta-tag namespace changed the library with
nothing to show for it and nothing to undo. Each case below drives the same API
the UI calls, asserts an event was written, reverts it, and asserts the state
came back.
"""

from __future__ import annotations

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
        Importer(s, lib.store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=True)
        )
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def events(client, action: str | None = None):
    rows = client.get("/api/history").json()["events"]
    return [e for e in rows if action is None or e["action"] == action]


def latest(client, action: str):
    rows = events(client, action)
    assert rows, f"no {action} event was logged"
    return rows[0]


def revert(client, event_id: int):
    res = client.post("/api/history/revert", json={"event_ids": [event_id]}).json()
    assert res["reverted"] == [event_id], f"revert failed: {res}"


def tags(client):
    return {t["name"]: t for t in client.get("/api/tags").json()}


def metas(client):
    return {r["name"]: r for r in client.get("/api/link-tags/rows").json()}


def item_id(client) -> int:
    return client.get("/api/items").json()["items"][0]["id"]


# ---- item tags -------------------------------------------------------------

def test_creating_a_tag_round_trips(client):
    client.post("/api/tags", json={"name": "fresh"})
    ev = latest(client, "create_tag")
    assert "fresh" in tags(client)
    revert(client, ev["id"])
    assert "fresh" not in tags(client)


def test_creating_an_alias_round_trips(client):
    client.post("/api/tags", json={"name": "cat"})
    client.post("/api/tags", json={"name": "kitty", "alias_of": "cat"})
    assert tags(client)["kitty"]["alias_of"] == "cat"
    revert(client, latest(client, "create_tag")["id"])
    assert "kitty" not in tags(client)


def test_renaming_a_tag_round_trips(client):
    client.post("/api/tags", json={"name": "befor"})
    tid = tags(client)["befor"]["id"]
    client.patch(f"/api/tags/{tid}", json={"name": "after"})
    ev = latest(client, "rename_tag")
    assert "after" in tags(client)
    revert(client, ev["id"])
    assert "befor" in tags(client) and "after" not in tags(client)


def test_commenting_a_tag_round_trips(client):
    client.post("/api/tags", json={"name": "noted"})
    tid = tags(client)["noted"]["id"]
    client.patch(f"/api/tags/{tid}", json={"comment": "a note"})
    ev = latest(client, "comment_tag")
    assert tags(client)["noted"]["comment"] == "a note"
    revert(client, ev["id"])
    assert tags(client)["noted"]["comment"] == ""


def test_setting_a_meta_count_round_trips(client):
    """Pictures the tag has where a META TAG says (the per-site counts that
    replaced the tag-level offset): logged like every other Tags-tab edit,
    and revertible like every other one — in both shapes. A count set WITH a
    fresh assignment rides the `add_link_tag` event (the revert takes the
    assignment and its count down together); one set on an EXISTING
    assignment is its own `set_meta_count`, whose revert puts the old number
    back."""
    client.post("/api/tags", json={"name": "elsewhere"})
    tid = tags(client)["elsewhere"]["id"]
    # Fresh assignment, count riding along.
    client.post(f"/api/tags/{tid}/meta-tags",
                json={"name": "tumblr", "count": 900})
    ev = latest(client, "add_link_tag")
    assert tags(client)["elsewhere"]["meta_counts"] == {"tumblr": 900}
    # A second site beside it — per assignment, which is the point.
    client.post(f"/api/tags/{tid}/meta-tags",
                json={"name": "twitter", "count": 40})
    assert tags(client)["elsewhere"]["meta_counts"] == {
        "tumblr": 900, "twitter": 40}
    # A change on the existing assignment is its own event…
    client.post(f"/api/tags/{tid}/meta-tags",
                json={"name": "tumblr", "count": 950})
    ev2 = latest(client, "set_meta_count")
    assert tags(client)["elsewhere"]["meta_counts"]["tumblr"] == 950
    # …whose revert restores the number,
    revert(client, ev2["id"])
    assert tags(client)["elsewhere"]["meta_counts"]["tumblr"] == 900
    # and the assignment's own revert takes the count down with the row.
    revert(client, ev["id"])
    assert "tumblr" not in tags(client)["elsewhere"]["meta_counts"]
    assert tags(client)["elsewhere"]["meta_tags"] == ["twitter"]


def test_removing_a_counted_meta_tag_restores_the_count(client):
    """The remove event records the count it takes down (conditionally), and
    the revert restores the SHAPE — the assignment WITH its figure."""
    client.post("/api/tags", json={"name": "counted"})
    tid = tags(client)["counted"]["id"]
    client.post(f"/api/tags/{tid}/meta-tags",
                json={"name": "danbooru", "count": 123})
    client.delete(f"/api/tags/{tid}/meta-tags/danbooru")
    ev = latest(client, "remove_link_tag")
    assert tags(client)["counted"]["meta_counts"] == {}
    revert(client, ev["id"])
    assert tags(client)["counted"]["meta_counts"] == {"danbooru": 123}


def test_AN_ALIAS_CARRIES_NO_COMMENT_AND_NO_DESCRIPTION(client):
    """A second spelling says nothing of its own — what it means is the tag
    it stands for's to say. The rule lives in the OP rather than in the
    absence of a field: a comment cell that has since been removed put one on
    an alias in a real library, so "the UI offers no way to do it" was true
    and was not enough."""
    client.post("/api/tags", json={"name": "cat"})
    client.post("/api/tags", json={"name": "kitty", "alias_of": "cat"})
    kid = tags(client)["kitty"]["id"]
    r = client.patch(f"/api/tags/{kid}", json={"comment": "a note"})
    assert r.status_code == 400
    assert tags(client)["kitty"]["comment"] == ""

    # And MAKING one an alias clears the pair it had as a plain tag.
    client.post("/api/tags", json={"name": "moggy", "comment": "a note"})
    mid = tags(client)["moggy"]["id"]
    client.patch(f"/api/tags/{mid}", json={"alias_of": "cat"})
    assert tags(client)["moggy"]["comment"] == ""


def test_changing_an_alias_target_round_trips(client):
    for n in ("cat", "feline"):
        client.post("/api/tags", json={"name": n})
    client.post("/api/tags", json={"name": "kitty", "alias_of": "cat"})
    kid = tags(client)["kitty"]["id"]
    client.patch(f"/api/tags/{kid}", json={"alias_of": "feline"})
    ev = latest(client, "set_alias")
    assert tags(client)["kitty"]["alias_of"] == "feline"
    revert(client, ev["id"])
    assert tags(client)["kitty"]["alias_of"] == "cat"


def test_implications_round_trip_both_ways(client):
    client.post("/api/tags", json={"name": "poodle"})
    client.post("/api/tags", json={"name": "dog"})
    pid = tags(client)["poodle"]["id"]

    client.post(f"/api/tags/{pid}/implies", json={"name": "dog"})
    add = latest(client, "add_tag_implication")
    assert tags(client)["poodle"]["implies"] == ["dog"]
    revert(client, add["id"])
    assert tags(client)["poodle"]["implies"] == []

    client.post(f"/api/tags/{pid}/implies", json={"name": "dog"})
    client.delete(f"/api/tags/{pid}/implies/dog")
    rem = latest(client, "remove_tag_implication")
    assert tags(client)["poodle"]["implies"] == []
    revert(client, rem["id"])
    assert tags(client)["poodle"]["implies"] == ["dog"]


def test_tagging_a_library_group_round_trips(client):
    """A group's tags flow down to every item in its subtree — as much a change
    as tagging an item, and it was not in the log at all."""
    gid = client.post("/api/groups", json={"name": "Trip", "icon": "folder"}).json()["id"]
    client.post(f"/api/tags/assign/group/{gid}", json={"tag": "holiday", "negative": False})
    add = latest(client, "add_group_tag")
    in_group = lambda: [t["name"] for g in client.get("/api/groups").json()  # noqa: E731
                        if g["id"] == gid for t in g["tags"]]
    assert in_group() == ["holiday"]
    revert(client, add["id"])
    assert in_group() == []

    client.post(f"/api/tags/assign/group/{gid}", json={"tag": "holiday", "negative": False})
    client.delete(f"/api/tags/assign/group/{gid}/holiday")
    rem = latest(client, "remove_group_tag")
    assert in_group() == []
    revert(client, rem["id"])
    assert in_group() == ["holiday"]


def test_assigning_and_unassigning_an_item_tag_round_trips(client):
    iid = item_id(client)
    has = lambda: any(t["name"] == "beach" for t in  # noqa: E731
                      client.get(f"/api/items/{iid}").json()["direct_tags"])
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "beach", "negative": False})
    assert has()
    revert(client, latest(client, "add_tag")["id"])
    assert not has()

    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "beach", "negative": False})
    client.delete(f"/api/tags/assign/item/{iid}/beach")
    assert not has()
    revert(client, latest(client, "remove_tag")["id"])
    assert has()


# ---- meta tags (the Tags tab's second mode) --------------------------------

def test_creating_a_meta_tag_round_trips(client):
    client.post("/api/link-tags/create", json={"name": "to_redraw"})
    ev = latest(client, "create_meta_tag")
    assert "to_redraw" in metas(client)
    revert(client, ev["id"])
    assert "to_redraw" not in metas(client)


def test_renaming_a_meta_tag_round_trips(client):
    client.post("/api/link-tags/create", json={"name": "old_name"})
    client.post("/api/link-tags/update", json={"name": "old_name", "new_name": "new_name"})
    ev = latest(client, "rename_meta_tag")
    assert "new_name" in metas(client) and "old_name" not in metas(client)
    revert(client, ev["id"])
    assert "old_name" in metas(client) and "new_name" not in metas(client)


def test_commenting_a_meta_tag_round_trips(client):
    client.post("/api/link-tags/create", json={"name": "cropped"})
    client.post("/api/link-tags/update", json={"name": "cropped", "comment": "a crop"})
    ev = latest(client, "comment_meta_tag")
    assert metas(client)["cropped"]["comment"] == "a crop"
    revert(client, ev["id"])
    assert metas(client)["cropped"]["comment"] == ""


def test_deleting_a_meta_tag_restores_its_carriers(client):
    """A meta tag lives on links, captions and tag groups at once. Deleting it
    takes it off all three, so undoing has to put all three back."""
    ids = [e["id"] for e in client.get("/api/items").json()["items"][:2]]
    a, b = ids[0], ids[1]
    rel = client.post("/api/relationships", json={
        "from_item_id": a, "to_item_id": b, "kind": "manual"}).json()
    client.post(f"/api/relationships/{rel['id']}/tags", json={"name": "shared"})
    cap = client.post(f"/api/items/{a}/captions", json={"text": "a caption"}).json()
    client.post(f"/api/items/{a}/captions/{cap['id']}/tags", json={"name": "shared"})
    grp = client.post(f"/api/tags/item/{a}/groups", json={"name": "Cast"}).json()
    client.post(f"/api/tags/groups/{grp['id']}/tags", json={"name": "shared"})

    carriers = lambda: (  # noqa: E731
        client.get(f"/api/items/{a}/relationships").json()[0]["tags"],
        [c["tags"] for c in client.get(f"/api/items/{a}").json()["captions"]][0],
        [g["tags"] for g in client.get(f"/api/items/{a}").json()["tag_groups"]
         if g["id"] == grp["id"]][0],
    )
    assert carriers() == (["shared"], ["shared"], ["shared"])

    client.post("/api/link-tags/delete", json={"name": "shared"})
    ev = latest(client, "delete_meta_tag")
    assert carriers() == ([], [], [])
    assert "shared" not in metas(client)

    revert(client, ev["id"])
    assert carriers() == (["shared"], ["shared"], ["shared"])
    assert "shared" in metas(client)


def test_describing_a_tag_round_trips(client):
    """A tag carries its own LONG FORM again (rung v27).

    It had none for a while, on the rule that a description is a TAG SET's
    and the library's tags are described only by whatever set knows the
    name. The library IS a set now — the first pill in the Tags tab, and one
    that exports as a template — so a tag set that cannot say what its own
    names mean would export with no teaching in it.
    """
    client.post("/api/tags", json={"name": "poodle"})
    tid = tags(client)["poodle"]["id"]
    r = client.patch(f"/api/tags/{tid}", json={"description": "Small dogs."})
    assert r.status_code == 200
    assert tags(client)["poodle"]["description"] == "Small dogs."

    ev = latest(client, "describe_tag")
    revert(client, ev["id"])
    assert tags(client)["poodle"]["description"] == ""


def test_describing_a_meta_tag_round_trips(client):
    """A META tag keeps a description of its own, apart from a tag's: it
    names the app's own objects — links, captions, tag groups — which no tag
    set and no library tag set describes."""
    client.post("/api/link-tags/create", json={"name": "noflip"})
    client.post("/api/link-tags/update",
                json={"name": "noflip", "description": "Mirroring is wrong."})
    ev = latest(client, "describe_meta_tag")
    assert metas(client)["noflip"]["description"] == "Mirroring is wrong."
    revert(client, ev["id"])
    assert metas(client)["noflip"]["description"] == ""


def test_a_meta_tag_on_a_TAG_round_trips_both_ways(client):
    """The fourth carrier. It reaches no item — the annotation is about the
    TAG SET — so what has to come back is a catalog row, and the two
    actions share the handlers the other three carriers use."""
    client.post("/api/tags", json={"name": "text"})
    tid = tags(client)["text"]["id"]

    client.post(f"/api/tags/{tid}/meta-tags", json={"name": "noflip"})
    add = latest(client, "add_link_tag")
    assert tags(client)["text"]["meta_tags"] == ["noflip"]
    # And it registered the NAME, so a meta tag survives its last use.
    assert "noflip" in metas(client)
    revert(client, add["id"])
    assert tags(client)["text"]["meta_tags"] == []

    client.post(f"/api/tags/{tid}/meta-tags", json={"name": "noflip"})
    client.delete(f"/api/tags/{tid}/meta-tags/noflip")
    rem = latest(client, "remove_link_tag")
    assert tags(client)["text"]["meta_tags"] == []
    revert(client, rem["id"])
    assert tags(client)["text"]["meta_tags"] == ["noflip"]


def test_deleting_a_TAG_brings_its_meta_tags_back(client):
    """They cascade with the row and no other event records them, so the tag
    would otherwise come back stripped of what the tag set said."""
    client.post("/api/tags", json={"name": "logo"})
    tid = tags(client)["logo"]["id"]
    client.post(f"/api/tags/{tid}/meta-tags", json={"name": "noflip"})
    client.post(f"/api/tags/{tid}/meta-tags", json={"name": "brand"})

    client.delete(f"/api/tags/{tid}")
    assert "logo" not in tags(client)
    revert(client, latest(client, "delete_tag")["id"])
    assert tags(client)["logo"]["meta_tags"] == ["brand", "noflip"]


def test_merging_a_TAG_carries_its_meta_tags_across(client):
    """A merge is a rename onto a taken name, and what the tag set said
    about the source is still true of the tag it became."""
    for n in ("cat", "feline"):
        client.post("/api/tags", json={"name": n})
    cid = tags(client)["cat"]["id"]
    client.post(f"/api/tags/{cid}/meta-tags", json={"name": "animal_word"})
    client.post(f"/api/tags/{cid}/merge", json={"into": "feline"})
    assert tags(client)["feline"]["meta_tags"] == ["animal_word"]


# ---- events ----------------------------------------------------------------

def test_creating_an_event_reverts(client):
    rows = client.post("/api/events", json={
        "display_name": "San Diego Comic-Con 2014",
        "start_date": 20140724, "end_date": 20140727}).json()
    assert rows and rows[0]["tag"] == "event:san_diego_comic_con_2014"

    revert(client, latest(client, "create_event")["id"])
    assert client.get("/api/events").json() == []
    assert "event:san_diego_comic_con_2014" in tags(client), \
        "the tag is an ordinary tag now — undoing the event does not delete it"


def test_editing_an_event_reverts_every_field_at_once(client):
    """The span, the name and the places are one edit and one event, so the
    undo has to put all three back — the bug `_swap` left in the place editor,
    where a redo restored one field of four.

    The COMMENT is not among them: it is the identity tag's, and it logs its
    own `comment_tag` beside this event."""
    p = client.post("/api/places", json={"tag": "hall_h", "name": "Hall H"}
                    ).json()[0]
    eid = client.post("/api/events", json={"display_name": "SDCC"}).json()[0]["id"]
    client.patch(f"/api/events/{eid}", json={
        "display_name": "San Diego Comic-Con", "comment": "the big one",
        "start_date": 20140724, "end_date": 20140727,
        "place_ids": [p["id"]]})

    assert client.get("/api/events").json()[0]["comment"] == "the big one"
    revert(client, latest(client, "comment_tag")["id"])
    revert(client, latest(client, "edit_event")["id"])
    row = client.get("/api/events").json()[0]
    assert row["display_name"] == "SDCC" and row["comment"] == ""
    assert row["start_date"] is None and row["end_date"] is None
    assert row["places"] == []


def test_deleting_an_event_reverts_with_its_span_and_its_places(client):
    p = client.post("/api/places", json={"tag": "hall_h", "name": "Hall H"}
                    ).json()[0]
    eid = client.post("/api/events", json={
        "display_name": "SDCC", "start_date": 20140724,
        "place_ids": [p["id"]]}).json()[0]["id"]
    client.delete(f"/api/events/{eid}")
    assert client.get("/api/events").json() == []

    revert(client, latest(client, "delete_event")["id"])
    row = client.get("/api/events").json()[0]
    assert row["display_name"] == "SDCC" and row["start_date"] == 20140724
    assert [x["tag"] for x in row["places"]] == ["hall_h"]


# ---- the sweep -------------------------------------------------------------

def test_every_tags_tab_action_leaves_a_revertible_trace(client):
    """One pass over the whole tab: after each action there is an event, and it
    offers a Revert. A change nobody can see or undo is the bug this guards."""
    iid = item_id(client)
    gid = client.post("/api/groups", json={"name": "Box", "icon": "folder"}).json()["id"]
    client.post("/api/tags", json={"name": "one"})
    client.post("/api/tags", json={"name": "two"})
    one = tags(client)["one"]["id"]

    steps = [
        ("create_tag", lambda: client.post("/api/tags", json={"name": "three"})),
        ("rename_tag", lambda: client.patch(f"/api/tags/{one}", json={"name": "uno"})),
        ("comment_tag", lambda: client.patch(f"/api/tags/{one}", json={"comment": "hi"})),
        ("add_tag_implication",
         lambda: client.post(f"/api/tags/{one}/implies", json={"name": "two"})),
        ("remove_tag_implication",
         lambda: client.delete(f"/api/tags/{one}/implies/two")),
        ("add_group_tag", lambda: client.post(
            f"/api/tags/assign/group/{gid}", json={"tag": "two", "negative": False})),
        ("remove_group_tag",
         lambda: client.delete(f"/api/tags/assign/group/{gid}/two")),
        ("add_tag", lambda: client.post(
            f"/api/tags/assign/item/{iid}", json={"tag": "two", "negative": False})),
        ("remove_tag", lambda: client.delete(f"/api/tags/assign/item/{iid}/two")),
        ("create_meta_tag",
         lambda: client.post("/api/link-tags/create", json={"name": "meta_one"})),
        ("comment_meta_tag", lambda: client.post(
            "/api/link-tags/update", json={"name": "meta_one", "comment": "c"})),
        ("rename_meta_tag", lambda: client.post(
            "/api/link-tags/update", json={"name": "meta_one", "new_name": "meta_two"})),
        ("delete_meta_tag",
         lambda: client.post("/api/link-tags/delete", json={"name": "meta_two"})),
        ("create_event", lambda: client.post(
            "/api/events", json={"display_name": "Comic-Con"})),
        ("edit_event", lambda: client.patch(
            f"/api/events/{client.get('/api/events').json()[0]['id']}",
            json={"start_date": 20140724})),
        ("delete_event", lambda: client.delete(
            f"/api/events/{client.get('/api/events').json()[0]['id']}")),
        # KEPT OUT OF THE AUTOCOMPLETE, and put back — neither is a deletion,
        # and both undo.
        ("set_tag_hidden",
         lambda: client.post("/api/tags/hidden", json={"names": ["two"]})),
        ("set_hidden_namespaces", lambda: client.put(
            "/api/tags/hidden-namespaces", json={"namespaces": ["artist"]})),
        ("delete_tag", lambda: client.delete(f"/api/tags/{one}")),
    ]
    for action, run in steps:
        before = len(events(client))
        run()
        assert len(events(client)) > before, f"{action} logged nothing"
        ev = latest(client, action)
        assert ev["revertible"] is True, f"{action} is not revertible"


def test_an_alias_must_point_at_a_tag_that_exists(client):
    """An alias is a second name for a tag you HAVE. Conjuring the target from
    a typo leaves two useless rows — an empty tag and an alias pointing at
    it — where the user meant to point at something real."""
    r = client.post("/api/tags", json={"name": "kitty", "alias_of": "nosuchtag"})
    assert r.status_code == 404
    assert "kitty" not in tags(client) and "nosuchtag" not in tags(client)

    client.post("/api/tags", json={"name": "cat"})
    assert client.post("/api/tags", json={"name": "kitty", "alias_of": "cat"}).status_code == 200
    assert tags(client)["kitty"]["alias_of"] == "cat"

    # …and the same rule when re-pointing an existing alias.
    kid = tags(client)["kitty"]["id"]
    assert client.patch(f"/api/tags/{kid}", json={"alias_of": "ghost"}).status_code == 404
    assert tags(client)["kitty"]["alias_of"] == "cat"


def test_a_revert_reports_the_events_that_undo_it(client):
    """Redo is a revert of the revert, so the reversal has to say which log
    entries it wrote — without them a caller can only guess at ids."""
    tag = client.post("/api/tags", json={"name": "temporary"}).json()
    ev = client.delete(f"/api/tags/{tag['id']}").json()["event_ids"]

    undo = client.post("/api/history/revert", json={"event_ids": ev}).json()
    assert undo["failed"] == [] and len(undo["events"]) == len(undo["reverted"])
    assert "temporary" in {t["name"] for t in client.get("/api/tags").json()}

    # Reverting what the undo wrote deletes the tag again — that is redo.
    redo = client.post("/api/history/revert",
                       json={"event_ids": undo["events"]}).json()
    assert redo["failed"] == []
    assert "temporary" not in {t["name"] for t in client.get("/api/tags").json()}
    # And it says how to undo ITSELF, so the toast can keep flipping.
    again = client.post("/api/history/revert",
                        json={"event_ids": redo["events"]}).json()
    assert again["failed"] == []
    assert "temporary" in {t["name"] for t in client.get("/api/tags").json()}


def test_redo_of_a_deletion_takes_the_assignments_with_it(client):
    """The interesting case: the tag was ON pictures, so undo restored the
    assignments too and redo has to remove them again — in that order, or the
    tag row goes first and the assignment reverts have nothing to hang on."""
    iid = item_id(client)
    has = lambda: any(t["name"] == "seasonal" for t in  # noqa: E731
                      client.get(f"/api/items/{iid}").json()["direct_tags"])
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "seasonal", "negative": False})
    tag = next(t for t in client.get("/api/tags").json() if t["name"] == "seasonal")

    ev = client.delete(f"/api/tags/{tag['id']}").json()["event_ids"]
    undo = client.post("/api/history/revert", json={"event_ids": ev}).json()
    assert undo["failed"] == [] and has()

    redo = client.post("/api/history/revert",
                       json={"event_ids": undo["events"]}).json()
    assert redo["failed"] == [] and not has()
    assert "seasonal" not in {t["name"] for t in client.get("/api/tags").json()}
