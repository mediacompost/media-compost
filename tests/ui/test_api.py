"""API smoke tests via FastAPI TestClient with an isolated library."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.ui.plugins import registry
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from media_compost.db import File, Item
from media_compost.testing import q_meta, q_tag, search_items
from sqlalchemy import select


@pytest.fixture
def client(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    # Seed the library.
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=True)
        )
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(client):
    """Up, plus the one launch-time fact the UI has to know before it draws
    (whether this deployment trains at all) and which on-disk format the
    library it is serving is in."""
    from media_compost.db import SCHEMA_VERSION

    assert client.get("/api/health").json() == {
        "ok": True, "training": True, "schema_version": SCHEMA_VERSION,
    }


def test_library_stats_breakdown(client):
    s = client.get("/api/library/stats").json()
    # Two image items (a with an alternative, and b); no videos/sequences.
    assert s["items"] == 2
    assert s["images"] == 2
    assert s["videos"] == 0
    assert s["sequences"] == 0
    assert s["files"] >= 2
    assert s["bytes"] > 0
    assert "groups" in s and "tags" in s
    # The data directory path is surfaced for the sidebar footer.
    assert isinstance(s["data_dir"], str) and s["data_dir"]


def test_a_cached_total_is_still_THIS_library_s_total(client):
    """The view's total is remembered until the library moves (it is a scan
    of everything the scope admits, asked again for every page and every
    switch back to a category — see `routers/items.scope_count`).

    The perf tripwires assert that the second look does not COUNT; this is
    the other half, and the one that matters: what comes back must be the
    right number. A cache that could hand back yesterday's total would be
    worse than no cache at all.
    """
    def total(**scope) -> int:
        r = client.post("/api/items/query",
                        json={"page": 1, "page_size": 60, **scope})
        assert r.status_code == 200, r.text
        return r.json()["total"]

    before = total()
    assert before == total(), "the same question, twice"
    # A DIFFERENT scope is a different answer, not the remembered one.
    assert total(kind="video") == 0 and total() == before

    # An item straight into the library, the way a CLI import beside the app
    # would put one there — which is exactly the case the cache has to notice.
    lib = app.dependency_overrides[get_library]()
    with lib.db.session() as s2:
        it = Item(uid="freshly-added", name="fresh", kind="image")
        s2.add(it)
        s2.flush()
        s2.add(File(item_id=it.id, number=1, path="files/1.png",
                    sha256="fresh", width=8, height=8, bytes=1, format="png"))
        s2.flush()
        it.active_file_id = s2.execute(
            select(File.id).where(File.item_id == it.id)).scalar_one()
        s2.commit()
    assert total() == before + 1, "the library moved and the total did not"


def test_groups_and_items(client):
    tree = client.get("/api/groups").json()
    assert isinstance(tree, list) and tree, tree
    src = next(g for g in tree if g["name"] == "src")
    assert src["count"] >= 2

    page = client.get("/api/items").json()
    assert page["total"] == 2  # a (+alt) and b
    first = page["items"][0]
    assert "megapixels" in first and first["active_file_id"]

    # Thumbnail generation works.
    fid = first["active_file_id"]
    r = client.get(f"/api/files/{fid}/thumb")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"


def test_deleting_a_group_takes_what_is_INSIDE_it(client):
    """A deletion removes the shelf, not just the shelf's label.

    The children used to be REPARENTED onto the deleted group's own parent,
    which reads as tidiness and is a decision nobody asked for: deleting
    "2024" left its twelve months scattered across the root, and the way back
    was to make the parent again and drag each one home.

    ITEMS are the half that has not changed and must not: a group is a view
    of them, not a home, so they stay in the library.
    """
    p = client.post("/api/groups", json={"name": "P"}).json()
    g = client.post("/api/groups", json={"name": "G", "parent_id": p["id"]}).json()
    c = client.post("/api/groups", json={"name": "C", "parent_id": g["id"]}).json()
    item = client.get("/api/items").json()["items"][0]["id"]
    assert client.post(f"/api/items/{item}/groups/{c['id']}").status_code == 200

    assert client.delete(f"/api/groups/{g['id']}").status_code == 200

    tree = client.get("/api/groups").json()
    ids = set()

    def walk(nodes):
        for n in nodes:
            ids.add(n["id"])
            walk(n["children"])

    walk(tree)
    assert g["id"] not in ids and c["id"] not in ids, "the subtree survived"
    assert p["id"] in ids, "the PARENT is not part of what was deleted"
    # The picture is still in the library, just in no group.
    assert client.get(f"/api/items/{item}").status_code == 200


def test_merging_groups_moves_their_contents_and_deletes_them(client):
    """The DESTINATION is the path id — the row the context menu was opened
    on — so which group survives is the one that was pointed at."""
    keep = client.post("/api/groups", json={"name": "Keep"}).json()
    fold = client.post("/api/groups", json={"name": "Fold"}).json()
    inside = client.post("/api/groups",
                         json={"name": "Inside", "parent_id": fold["id"]}).json()
    item = client.get("/api/items").json()["items"][0]["id"]
    client.post(f"/api/items/{item}/groups/{fold['id']}")

    r = client.post(f"/api/groups/{keep['id']}/merge",
                    json={"source_ids": [fold["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["moved"] == 1

    tree = client.get("/api/groups").json()
    flat = {}

    def walk(nodes, parent=None):
        for n in nodes:
            flat[n["id"]] = parent
            walk(n["children"], n["id"])

    walk(tree)
    assert fold["id"] not in flat, "the source survived"
    assert flat.get(inside["id"]) == keep["id"], "the child did not move"
    assert keep["id"] in client.get(f"/api/items/{item}").json()["group_ids"]


def test_a_merge_into_a_descendant_is_refused_by_name(client):
    outer = client.post("/api/groups", json={"name": "Outer"}).json()
    inner = client.post("/api/groups",
                        json={"name": "Inner", "parent_id": outer["id"]}).json()
    r = client.post(f"/api/groups/{inner['id']}/merge",
                    json={"source_ids": [outer["id"]]})
    assert r.status_code == 400
    assert "descendant" in r.json()["detail"]


def test_a_deleted_group_comes_BACK(client):
    """…and brings its subtree, its shape, its tags and its items with it.

    Under the ORIGINAL ids, because every earlier event about these groups
    names them by id and fresh ones would leave all of those pointing at
    nothing.
    """
    p = client.post("/api/groups", json={"name": "P"}).json()
    g = client.post("/api/groups",
                    json={"name": "G", "parent_id": p["id"]}).json()
    c = client.post("/api/groups",
                    json={"name": "C", "parent_id": g["id"]}).json()
    item = client.get("/api/items").json()["items"][0]["id"]
    client.post(f"/api/items/{item}/groups/{c['id']}")

    client.delete(f"/api/groups/{g['id']}")
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "delete_group")
    assert ev["revertible"], "a deletion this size has to be undoable"
    r = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.status_code == 200 and r.json()["reverted"] == [ev["id"]], r.text

    tree = client.get("/api/groups").json()
    p_node = next(n for n in tree if n["id"] == p["id"])
    g_node = next(n for n in p_node["children"] if n["id"] == g["id"])
    assert [ch["id"] for ch in g_node["children"]] == [c["id"]], \
        "the subtree came back under the same parents"
    assert c["id"] in client.get(f"/api/items/{item}").json()["group_ids"], \
        "the membership came back with the group that held it"


def test_tag_assignment_and_search(client):
    page = client.get("/api/items").json()
    item_id = page["items"][0]["id"]
    # Assign a tag, then find the item by searching for it.
    r = client.post(f"/api/tags/assign/item/{item_id}",
                    json={"tag": "portrait", "negative": False})
    assert r.status_code == 200
    found = search_items(client, q_tag("portrait"))
    assert found["total"] == 1
    assert found["items"][0]["id"] == item_id
    # Exclusion (has-not).
    excluded = search_items(client, q_tag("portrait", have=False))
    assert item_id not in [i["id"] for i in excluded["items"]]

    tags = client.get("/api/tags").json()
    assert any(t["name"] == "portrait" and t["positive"] == 1 for t in tags)


def test_untagged_scope(client):
    all_items = client.get("/api/items").json()
    total = all_items["total"]
    assert total >= 2
    # Everything is untagged to start with.
    assert search_items(client, untagged=True)["total"] == total
    assert client.get("/api/items/facets?untagged=true").json()["count"] == total

    # Tag one item — it drops out of the Untagged scope.
    tagged = all_items["items"][0]["id"]
    assert client.post(f"/api/tags/assign/item/{tagged}", json={"tag": "portrait"}).status_code == 200
    untagged = search_items(client, untagged=True)
    assert untagged["total"] == total - 1
    assert tagged not in [i["id"] for i in untagged["items"]]
    assert client.get("/api/items/facets?untagged=true").json()["count"] == total - 1


def test_tag_groups_and_instances(client):
    item_id = client.get("/api/items").json()["items"][0]["id"]

    # Two named tag groups for this item.
    gA = client.post(f"/api/tags/item/{item_id}/groups",
                     json={"name": "Person A"}).json()
    gB = client.post(f"/api/tags/item/{item_id}/groups",
                     json={"name": "Person B"}).json()

    box = {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}
    # The same tag "face" placed in both groups, each with its own box.
    client.post(f"/api/tags/assign/item/{item_id}/box",
                json={"tag": "face", "box": box, "group_id": gA["id"]})
    client.post(f"/api/tags/assign/item/{item_id}/box",
                json={"tag": "face", "box": {**box, "x": 0.5}, "group_id": gB["id"]})

    detail = client.get(f"/api/items/{item_id}").json()
    assert {g["name"] for g in detail["tag_groups"]} == {"Person A", "Person B"}
    faces = [i for i in detail["tag_instances"] if i["name"] == "face"]
    # One instance per group, each carrying exactly one box.
    assert {i["group_id"] for i in faces} == {gA["id"], gB["id"]}
    assert all(len(i["boxes"]) == 1 for i in faces)
    # The tag still counts once for search (dedup by name).
    assert search_items(client, q_tag("face"))["total"] == 1

    # Move the group-A instance to ungrouped.
    r = client.post(f"/api/tags/item/{item_id}/move-instance",
                    json={"name": "face", "from_group_id": gA["id"],
                          "to_group_id": None})
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/items/{item_id}").json()
    faces = [i for i in detail["tag_instances"] if i["name"] == "face"]
    assert {i["group_id"] for i in faces} == {None, gB["id"]}

    # Deleting group B folds its instance back into the ungrouped default,
    # merging boxes (so the ungrouped "face" now has both boxes).
    assert client.delete(f"/api/tags/groups/{gB['id']}").status_code == 200
    detail = client.get(f"/api/items/{item_id}").json()
    assert [g["name"] for g in detail["tag_groups"]] == ["Person A"]
    faces = [i for i in detail["tag_instances"] if i["name"] == "face"]
    assert len(faces) == 1 and faces[0]["group_id"] is None
    assert len(faces[0]["boxes"]) == 2


def test_timed_box_update_and_track_id(client):
    """A video subject moves: a box carries a time range and a track id, both are
    editable in place, and two same-tag boxes on different tracks stay distinct."""
    item_id = client.get("/api/items").json()["items"][0]["id"]

    # Two "person" boxes on different tracks (two subjects sharing one tag).
    r1 = client.post(f"/api/tags/assign/item/{item_id}/box", json={
        "tag": "person",
        "box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2,
                "time_start": 0.0, "time_end": 1.0, "track_id": 1},
    })
    assert r1.status_code == 200, r1.text
    b1 = r1.json()["id"]
    client.post(f"/api/tags/assign/item/{item_id}/box", json={
        "tag": "person",
        "box": {"x": 0.6, "y": 0.6, "w": 0.2, "h": 0.2,
                "time_start": 0.0, "time_end": 1.0, "track_id": 2},
    })

    boxes = [b for i in client.get(f"/api/items/{item_id}").json()["tag_instances"]
             if i["name"] == "person" for b in i["boxes"]]
    assert {b["track_id"] for b in boxes} == {1, 2}
    assert all(b["time_start"] == 0.0 and b["time_end"] == 1.0 for b in boxes)

    # Move box 1's time range (subject moved to a later moment) and its track.
    r = client.patch(f"/api/tags/box/{b1}", json={
        "time_start": 2.5, "time_end": 3.5, "track_id": 5,
    })
    assert r.status_code == 200, r.text
    b1_after = next(
        b for i in client.get(f"/api/items/{item_id}").json()["tag_instances"]
        if i["name"] == "person" for b in i["boxes"] if b["id"] == b1
    )
    assert (b1_after["time_start"], b1_after["time_end"], b1_after["track_id"]) == (2.5, 3.5, 5)

    # Clearing the time range converts it back to a whole-duration box.
    client.patch(f"/api/tags/box/{b1}", json={"clear_time": True, "clear_track": True})
    b1_cleared = next(
        b for i in client.get(f"/api/items/{item_id}").json()["tag_instances"]
        if i["name"] == "person" for b in i["boxes"] if b["id"] == b1
    )
    assert b1_cleared["time_start"] is None and b1_cleared["time_end"] is None
    assert b1_cleared["track_id"] is None


def test_a_time_range_carries_its_own_sign(client):
    """A film's tag is present in some stretches and pointedly absent in others,
    so the sign rides on the RANGE. The item-level flag follows: negative only
    while every range is."""
    item_id = client.get("/api/items").json()["items"][0]["id"]
    add = lambda **b: client.post(  # noqa: E731
        f"/api/tags/assign/item/{item_id}/box",
        json={"tag": "rain", "box": {"x": None, "y": None, "w": None, "h": None, **b}},
    ).json()["id"]

    def ranges():
        inst = [i for i in client.get(f"/api/items/{item_id}").json()["tag_instances"]
                if i["name"] == "rain"]
        return sorted(((b["time_start"], b["time_end"], b["negative"])
                       for i in inst for b in i["boxes"]), key=lambda r: r[0])

    def item_negative():
        return next(t["negative"] for t in client.get(f"/api/items/{item_id}").json()["tags"]
                    if t["name"] == "rain")

    neg = add(time_start=0.0, time_end=10.0, negative=True)
    assert ranges() == [(0.0, 10.0, True)]
    assert item_negative() is True  # every range negative → negative for the item

    add(time_start=20.0, time_end=30.0)
    assert item_negative() is False  # one positive range is enough

    # Dropping the only positive range hands the item back to the negative one.
    pos_id = [b["id"] for i in client.get(f"/api/items/{item_id}").json()["tag_instances"]
              if i["name"] == "rain" for b in i["boxes"] if not b["negative"]][0]
    client.delete(f"/api/tags/box/{pos_id}")
    assert item_negative() is True

    # A new range makes room: the one it straddles keeps the pieces either side.
    add(time_start=3.0, time_end=5.0)
    assert ranges() == [(0.0, 3.0, True), (3.0, 5.0, False), (5.0, 10.0, True)]

    # Editing a range in place makes room the same way, swallowing what it covers.
    client.patch(f"/api/tags/box/{neg}", json={"time_start": 0.0, "time_end": 9.0})
    assert ranges() == [(0.0, 9.0, True), (9.0, 10.0, True)]


def test_two_subjects_can_share_a_tag_at_the_same_moment(client):
    """The non-overlap rule is about a film's own time ranges. A box WITH
    geometry is a subject's placement, and two subjects tagged `person` are on
    screen together all the time."""
    item_id = client.get("/api/items").json()["items"][0]["id"]
    for x, track in ((0.1, 1), (0.6, 2)):
        client.post(f"/api/tags/assign/item/{item_id}/box", json={
            "tag": "person",
            "box": {"x": x, "y": 0.1, "w": 0.2, "h": 0.2,
                    "time_start": 4.0, "time_end": 6.0, "track_id": track},
        })
    boxes = [b for i in client.get(f"/api/items/{item_id}").json()["tag_instances"]
             if i["name"] == "person" for b in i["boxes"]]
    assert {b["track_id"] for b in boxes} == {1, 2}


def test_add_same_tag_to_multiple_groups(client):
    """A tag can live in Ungrouped and several named groups at once, each as its
    own placement (task: per-group add field + multi-group membership)."""
    item_id = client.get("/api/items").json()["items"][1]["id"]
    g1 = client.post(f"/api/tags/item/{item_id}/groups", json={"name": "G1"}).json()
    g2 = client.post(f"/api/tags/item/{item_id}/groups", json={"name": "G2"}).json()

    # Add "hero" into the ungrouped default and both named groups.
    for gid in (None, g1["id"], g2["id"]):
        r = client.post(f"/api/tags/item/{item_id}/group-tag",
                        json={"tag": "hero", "group_id": gid})
        assert r.status_code == 200, r.text

    detail = client.get(f"/api/items/{item_id}").json()
    heroes = [i for i in detail["tag_instances"] if i["name"] == "hero"]
    assert {i["group_id"] for i in heroes} == {None, g1["id"], g2["id"]}
    # Still one tag for search (dedup by name).
    assert search_items(client, q_tag("hero"))["total"] == 1

    # Adding the same tag to the same group again is idempotent (no duplicate).
    client.post(f"/api/tags/item/{item_id}/group-tag",
                json={"tag": "hero", "group_id": g1["id"]})
    detail = client.get(f"/api/items/{item_id}").json()
    heroes = [i for i in detail["tag_instances"] if i["name"] == "hero"]
    assert len([i for i in heroes if i["group_id"] == g1["id"]]) == 1


def test_metadata_search(client):
    # The synthetic PNG test images are indexed with a format=PNG metadata value.
    got = search_items(client, q_meta("format", "text", "=", "PNG"))
    assert got["total"] >= 1
    none = search_items(client, q_meta("format", "text", "=", "GIF"))
    assert none["total"] == 0
    # Combined with a tag AND.
    item_id = got["items"][0]["id"]
    client.post(f"/api/tags/assign/item/{item_id}", json={"tag": "keep"})
    both = search_items(
        client, q_meta("format", "text", "=", "PNG"), q_tag("keep")
    )
    assert both["total"] == 1 and both["items"][0]["id"] == item_id


def test_sort_by_modified(client):
    ids = [i["id"] for i in client.get("/api/items").json()["items"]]
    target = ids[-1]
    # Editing an item's tags bumps its modification time, floating it to the top.
    client.post(f"/api/tags/assign/item/{target}", json={"tag": "touched"})
    got = client.get("/api/items", params={"sort": "modified"}).json()
    assert got["items"][0]["id"] == target


def test_sort_direction(client):
    asc = [i["id"] for i in client.get(
        "/api/items", params={"sort": "name_asc"}).json()["items"]]
    desc = [i["id"] for i in client.get(
        "/api/items", params={"sort": "name_desc"}).json()["items"]]
    assert len(asc) == len(desc) >= 2
    assert asc == list(reversed(desc))


def test_random_sort_is_one_shuffle_per_seed(client):
    """A shuffle has to be a PERMUTATION the pages agree on.

    `random()` would draw a fresh number per row per statement, so page 2
    would be a different order from page 1 — some items twice, others never.
    The seed rides in the token where a direction goes, and a different seed
    is a different order.
    """
    all_ids = [i["id"] for i in client.get("/api/items").json()["items"]]
    assert len(all_ids) >= 2
    one = [i["id"] for i in client.get(
        "/api/items", params={"sort": "random_1234"}).json()["items"]]
    again = [i["id"] for i in client.get(
        "/api/items", params={"sort": "random_1234"}).json()["items"]]
    assert sorted(one) == sorted(all_ids)      # every item, exactly once
    assert one == again                        # and the same order each time

    # Paged, the same seed hands back that order in slices — no gaps, no
    # repeats, which is the whole reason the shuffle is arithmetic.
    paged = []
    for page in range(1, len(all_ids) + 1):
        paged += [i["id"] for i in client.get("/api/items", params={
            "sort": "random_1234", "page": page, "page_size": 1}).json()["items"]]
    assert paged == one

    other = [i["id"] for i in client.get(
        "/api/items", params={"sort": "random_99"}).json()["items"]]
    assert sorted(other) == sorted(all_ids)


def test_random_sort_takes_no_grouping(client):
    """A section of a shuffle would hold whatever the shuffle put next to
    each other, so there is no coarsening to offer — and the endpoint refuses
    one rather than inventing an order for it."""
    r = client.post("/api/items/groups",
                    json={"sort": "random_5", "group_by": "year"})
    assert r.status_code == 400


def test_eff_tags_include_group_tags(client):
    tree = client.get("/api/groups").json()
    src = next(g for g in tree if g["name"] == "src")
    # A tag assigned to a group is inherited by its items' effective tags, which
    # drives the grid's tag-match highlight.
    client.post(f"/api/tags/assign/group/{src['id']}", json={"tag": "inherited"})
    page = client.get("/api/items").json()
    assert page["items"]
    assert all("inherited" in i["eff_tags"] for i in page["items"])


def test_item_carries_dates_not_filenames(client):
    """The item exposes created + last-imported dates; each file carries its own
    created_at (import/edit time), but the filenames under it carry none."""
    page = client.get("/api/items").json()
    detail = client.get(f"/api/items/{page['items'][0]['id']}").json()
    assert detail.get("created_at") and detail.get("last_imported_at")
    names = detail["files"][0]["names"]
    assert names and all("name" in n and "created_at" not in n for n in names)
    # A source file now surfaces when its bytes were added/edited.
    assert detail["files"][0]["created_at"]


def test_item_merge(client):
    page = client.get("/api/items").json()
    assert page["total"] == 2
    target, source = (i["id"] for i in page["items"][:2])
    client.post(f"/api/tags/assign/item/{source}", json={"tag": "keepme"})
    client.post(f"/api/items/{source}/captions", json={"text": "a caption"})
    src_files = client.get(f"/api/items/{source}").json()["file_count"]
    tgt_files = client.get(f"/api/items/{target}").json()["file_count"]

    r = client.post("/api/items/merge",
                    json={"source_id": source, "target_id": target})
    assert r.status_code == 200, r.text

    page = client.get("/api/items").json()
    assert page["total"] == 1 and page["items"][0]["id"] == target
    detail = client.get(f"/api/items/{target}").json()
    assert detail["file_count"] == src_files + tgt_files
    assert any(c["text"] == "a caption" for c in detail["captions"])
    assert any(t["name"] == "keepme" for t in detail["tags"])
    assert client.get(f"/api/items/{source}").status_code == 404


def test_file_split(client):
    page = client.get("/api/items").json()
    multi = next(i for i in page["items"] if i["file_count"] == 2)
    detail = client.get(f"/api/items/{multi['id']}").json()
    fid = next(f["id"] for f in detail["files"] if not f["active"])
    before = client.get("/api/items").json()["total"]

    r = client.post(f"/api/files/{fid}/split")
    assert r.status_code == 200, r.text
    new_id = r.json()["item_id"]

    assert client.get("/api/items").json()["total"] == before + 1
    assert client.get(f"/api/items/{multi['id']}").json()["file_count"] == 1
    new = client.get(f"/api/items/{new_id}").json()
    assert new["file_count"] == 1 and new["active_file_id"] == fid
    # The split-off item inherits the original's group memberships.
    assert new["group_ids"] == detail["group_ids"]


def test_several_files_split_into_ONE_new_item(client):
    """Picking three files and splitting them makes one item holding all three
    — not one item each, which is what the row's own Split repeated would do."""
    page = client.get("/api/items").json()
    ids = [i["id"] for i in page["items"]]
    # Merge two more items in so one item has three files to pick from.
    host = ids[0]
    for other in ids[1:3]:
        client.post("/api/items/merge", json={"source_id": other, "target_id": host})
    detail = client.get(f"/api/items/{host}").json()
    files = detail["files"]
    assert len(files) >= 3
    picked = [f["id"] for f in files[:2]]
    before = client.get("/api/items").json()["total"]

    r = client.post("/api/files/split", json={"file_ids": picked})
    assert r.status_code == 200, r.text
    new_id = r.json()["item_id"]

    assert client.get("/api/items").json()["total"] == before + 1
    new = client.get(f"/api/items/{new_id}").json()
    assert {f["id"] for f in new["files"]} == set(picked)
    # Numbering restarts at #1 in the order they were numbered here.
    assert sorted(f["number"] for f in new["files"]) == [1, 2]
    assert new["active_file_id"] in picked
    assert new["group_ids"] == detail["group_ids"]
    left = client.get(f"/api/items/{host}").json()
    assert not ({f["id"] for f in left["files"]} & set(picked))
    assert left["active_file_id"] not in picked


def test_a_split_cannot_take_every_file(client):
    """An item with no file at all is not a thing, so the whole set is refused
    — as is a set spanning two items, which has no one item to leave."""
    page = client.get("/api/items").json()["items"]
    # The seeded library is one item with two files and one with a single file.
    multi = next(i for i in page if i["file_count"] == 2)
    single = next(i for i in page if i["id"] != multi["id"])
    everything = [f["id"] for f in client.get(f"/api/items/{multi['id']}").json()["files"]]
    elsewhere = client.get(f"/api/items/{single['id']}").json()["files"][0]["id"]

    assert client.post("/api/files/split", json={"file_ids": everything}).status_code == 400
    assert client.post(
        "/api/files/split", json={"file_ids": [everything[0], elsewhere]}
    ).status_code == 400
    assert client.post("/api/files/split", json={"file_ids": []}).status_code == 400
    # And the single-file item's one file has nothing to be split from.
    assert client.post("/api/files/split", json={"file_ids": [elsewhere]}).status_code == 400


def test_empty_trash(client):
    ids = [i["id"] for i in client.get("/api/items").json()["items"]]
    client.post("/api/items/trash", json={"item_ids": ids})
    assert client.get("/api/items").json()["total"] == 0
    assert client.get("/api/items", params={"trash": True}).json()["total"] == len(ids)

    r = client.post("/api/items/empty-trash")
    assert r.status_code == 200 and r.json()["count"] == len(ids)
    assert client.get("/api/items", params={"trash": True}).json()["total"] == 0

    # The most destructive action in the app leaves a trace: one delete_item
    # event per item, same as the targeted delete endpoint.
    events = client.get("/api/history?limit=50").json()["events"]
    deletes = [e for e in events if e["action"] == "delete_item"]
    assert len(deletes) == len(ids)


def test_settings_default_and_update(client):
    # Empty by default: per-model paths + default double-click prefs (token is
    # env-only, no offline flags).
    defaults = {"model_paths": {}, "dblclick_image": "quicklook", "dblclick_video": "quicklook",
                "florence_model": "florence2_base", "language": "en",
                "date_format": "D MMM YYYY", "time_24h": False,
                "hide_unready_actions": False,
                "subject_tag_prefix": "subject:",
        "place_tag_prefix": "place:",
        "event_tag_prefix": "event:", "face_match_threshold": 0.90,
        "watermark_tag": "watermark", "text_tag": ""}
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    assert r.json() == defaults

    # A local model path persists; unknown families are dropped.
    r = client.put("/api/settings", json={
        "model_paths": {"withoutbg": "/models/withoutbg", "bogus": "/x"},
    })
    assert r.status_code == 200, r.text
    assert r.json()["model_paths"] == {"withoutbg": "/models/withoutbg"}
    assert client.get("/api/settings").json()["model_paths"] == \
        {"withoutbg": "/models/withoutbg"}

    # Double-click prefs persist; invalid values fall back to defaults
    # (dblclick_video's default is now "quicklook").
    client.put("/api/settings", json={"model_paths": {}, "dblclick_image": "editor",
                                      "dblclick_video": "bogus"})
    got = client.get("/api/settings").json()
    assert got["dblclick_image"] == "editor" and got["dblclick_video"] == "quicklook"

    # Date/time prefs persist; an unknown date format falls back to the default.
    client.put("/api/settings", json={"model_paths": {}, "date_format": "DD.MM.YYYY", "time_24h": True})
    got = client.get("/api/settings").json()
    assert got["date_format"] == "DD.MM.YYYY" and got["time_24h"] is True
    client.put("/api/settings", json={"model_paths": {}, "date_format": "bogus"})
    got = client.get("/api/settings").json()
    assert got["date_format"] == "D MMM YYYY" and got["time_24h"] is False

    # The hide-unready-actions switch persists (a per-user view preference).
    client.put("/api/settings", json={"model_paths": {}, "hide_unready_actions": True})
    assert client.get("/api/settings").json()["hide_unready_actions"] is True
    client.put("/api/settings", json={"model_paths": {}})
    assert client.get("/api/settings").json()["hide_unready_actions"] is False

    # Language persists; an unknown language falls back to English.
    client.put("/api/settings", json={"model_paths": {}, "language": "de"})
    assert client.get("/api/settings").json()["language"] == "de"
    client.put("/api/settings", json={"model_paths": {}, "language": "xx"})
    assert client.get("/api/settings").json()["language"] == "en"

    # And can be reset.
    client.put("/api/settings", json={"model_paths": {}})
    assert client.get("/api/settings").json() == defaults


def test_clear_offline(client):
    import os
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        r = client.post("/api/ml/clear-offline")
        assert r.status_code == 200, r.text
        assert r.json() == {"env_offline": ""}
        # The env var is now neutralized.
        assert os.environ.get("HF_HUB_OFFLINE") == "0"
    finally:
        os.environ.pop("HF_HUB_OFFLINE", None)


def _no_token_anywhere(monkeypatch):
    """No token from the environment AND none from disk.

    `hf.token()` deliberately falls back to `huggingface_hub.get_token()`,
    which reads what `hf auth login` saved — without that fallback the app
    claimed "no access token" while every real download had one. So clearing
    the two env vars is not enough to make "no token" true: on any machine
    whose owner has ever logged in, these assertions failed for a reason that
    had nothing to do with the code under test.
    """
    import huggingface_hub

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.setattr(huggingface_hub, "get_token", lambda *a, **k: None)


def test_hf_token_env_only(client, monkeypatch):
    _no_token_anywhere(monkeypatch)
    assert client.get("/api/settings/hf-token").json() == {"token_available": False}
    # Setting a token makes it available (in the process env, not the DB).
    r = client.put("/api/settings/hf-token", json={"token": "hf_abc"})
    assert r.json() == {"token_available": True}
    assert client.get("/api/settings/hf-token").json() == {"token_available": True}
    import os
    assert os.environ.get("HF_TOKEN") == "hf_abc"
    # Clearing it removes it from the environment.
    client.put("/api/settings/hf-token", json={"token": ""})
    assert client.get("/api/settings/hf-token").json() == {"token_available": False}
    assert "HF_TOKEN" not in os.environ


def test_model_cache_status(client, monkeypatch):
    _no_token_anywhere(monkeypatch)
    r = client.get("/api/ml/model-cache")
    assert r.status_code == 200, r.text
    body = r.json()
    keys = {m["key"] for m in body["models"]}
    assert keys == {"withoutbg", "wm_yolo11x", "big_lama", "anime_lama",
                    "joycaption", "joytag",
                    "wd_tagger", "ram_plus", "blip2", "qwen2_5_vl",
                    "florence2_base", "florence2_large",
                    "florence2_base_plain", "florence2_large_plain",
                    "depth_anything_v2_small", "dpt_hybrid_midas",
                    "zoedepth_nyu_kitti", "cn_annotators_leres", "yolo11n_pose",
                    "cn_annotators_openpose", "cn_annotators_lineart", "magiv3",
                    "swin2sr_realworld_x4", "realesrgan_anime_x4",
                    "realesrgan_x2plus", "fbcnn_color", "scunet_real_gan",
                    "color2manga", "manga_colorization_v2", "anime_face",
                    "magi_crop_embedder", "dinov2_small", "clip_vit_b32",
                    # Plugins with nothing to download but something to install
                    # are listed too, keyed on the PLUGIN — the models page has
                    # to say they exist, or a model that needs a pip install is
                    # invisible on the page that manages models.
                    "insightface_faces", "colorize_photo", "descreen",
                    "descreen_opencomic", "canny", "rapid_ocr"}
    hub_model = next(m for m in body["models"] if m["key"] == "withoutbg")
    assert hub_model["url"].startswith("https://huggingface.co/")
    assert body["token_available"] is False
    assert "env_offline" in body

    # A gated model can't be downloaded without a token. NOTHING here is gated
    # any more — RMBG-2.0 was the only one and was removed for being gated — so
    # the refusal is driven against a source made gated for the length of the
    # test. The alternative is deleting the assertion, which would leave a live
    # 400 uncovered until the day somebody adds a gated model back and finds
    # out the hard way that the refusal had rotted.
    assert not any(m["gated"] for m in body["models"]), \
        "nothing ships gated; see the note above before changing this"
    gated = replace(registry.source_for("withoutbg"), gated=True)
    monkeypatch.setattr(registry, "source_for",
                        lambda k: gated if k == "withoutbg" else None)
    assert client.post("/api/ml/model-cache/withoutbg/download").status_code == 400
    # Unknown model -> 404.
    assert client.post("/api/ml/model-cache/nope/download").status_code == 404


def test_download_blocked_while_env_offline(client, monkeypatch):
    """When the launch environment forces HF offline, downloads are refused until
    the user enables them (the offline setting isn't silently bypassed)."""
    from media_compost.ui.server.routers import ml as ml_router

    monkeypatch.setattr(ml_router, "_env_offline", "HF_HUB_OFFLINE=1")
    r = client.post("/api/ml/model-cache/withoutbg/download")
    assert r.status_code == 400 and "offline" in r.json()["detail"].lower()
    # Enabling downloads clears the block (so a later download would be allowed).
    assert client.post("/api/ml/clear-offline").status_code == 200
    assert ml_router._env_offline == ""


def test_tag_aliases(client):
    # Create a real tag, then an alias pointing to it.
    client.post("/api/tags", json={"name": "car"})
    r = client.post("/api/tags", json={"name": "automobile", "alias_of": "car"})
    assert r.status_code == 200, r.text
    assert r.json()["alias_of"] == "car"

    # Assigning the alias to an item actually assigns the linked tag.
    from sqlalchemy import select as _sel
    from media_compost.db import Item
    lib = client.app.dependency_overrides  # not used; get an item id via API
    items = client.get("/api/items").json()["items"]
    iid = items[0]["id"]
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "automobile", "negative": False})
    detail = client.get(f"/api/items/{iid}").json()
    names = {t["name"] for t in detail["tag_instances"]}
    assert "car" in names and "automobile" not in names

    # The tag list marks the alias and carries the linked tag's count.
    rows = client.get("/api/tags").json()
    alias = next(t for t in rows if t["name"] == "automobile")
    assert alias["alias_of"] == "car" and alias["positive"] == 1
    # …and says it in the `numbers` map too, which is the ONLY spelling the
    # frontend reads (`tags.ts: tagCount`): without it every count off this
    # listing — the training and evaluate prompt autocomplete among them —
    # read as zero.
    car = next(t for t in rows if t["name"] == "car")
    for row in (car, alias):
        assert row["numbers"] == {"positive": 1, "implicit": 0, "negative": 0}

    # A name already in use can't be added again — neither as a plain tag nor as
    # an alias shadowing an existing tag's name.
    assert client.post("/api/tags", json={"name": "car"}).status_code == 409
    assert client.post("/api/tags", json={"name": "automobile", "alias_of": "car"}).status_code == 409

    # An alias can be removed (deleting its tag row).
    assert client.delete(f"/api/tags/{alias['id']}").status_code == 200
    names = {t["name"] for t in client.get("/api/tags").json()}
    assert "automobile" not in names and "car" in names


def _find_event(client, action, **match):
    for e in client.get("/api/history").json()["events"]:
        if e["action"] == action and all(e["data"].get(k) == v for k, v in match.items()):
            return e
    raise AssertionError(f"no {action} event matching {match}")


def test_tag_create_alias_delete_are_revertible(client):
    # Creating an unassigned tag is revertible → reverting deletes it.
    client.post("/api/tags", json={"name": "sunset"})
    ev = _find_event(client, "create_tag", name="sunset")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert "sunset" not in {t["name"] for t in client.get("/api/tags").json()}

    # Alias target change is revertible → reverting restores the old target.
    client.post("/api/tags", json={"name": "auto"})
    client.post("/api/tags", json={"name": "truck"})
    a = client.post("/api/tags", json={"name": "carx", "alias_of": "auto"}).json()
    client.patch(f"/api/tags/{a['id']}", json={"alias_of": "truck"})
    ev = _find_event(client, "set_alias", name="carx")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    carx = next(t for t in client.get("/api/tags").json() if t["name"] == "carx")
    assert carx["alias_of"] == "auto"

    # Deleting a tag is revertible → reverting recreates it (as the alias it was).
    client.delete(f"/api/tags/{carx['id']}")
    ev = _find_event(client, "delete_tag", name="carx")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    carx = next(t for t in client.get("/api/tags").json() if t["name"] == "carx")
    assert carx["alias_of"] == "auto"


def test_rename_sequence_container_item_updates_members_belongs_to(client):
    """Renaming a sequence's *container item* (via PATCH /api/items) propagates to
    the Sequence row, so its members' "belongs to" panels show the new name — the
    reverse of rename_sequence (regression: nested-sequence stale parent name)."""
    ids = [it["id"] for it in client.get("/api/items").json()["items"]][:2]
    assert len(ids) == 2
    seq = client.post("/api/sequences", json={"name": "OrigName", "item_ids": ids}).json()
    cid = seq["item_id"]
    # Before: the member reports the original sequence name.
    before = [s["name"] for s in client.get(f"/api/items/{ids[0]}/sequences").json()]
    assert before == ["OrigName"]
    # Rename through the item endpoint (what the header name field uses).
    r = client.patch(f"/api/items/{cid}", json={"name": "RenamedViaItem"})
    assert r.status_code == 200, r.text
    after = [s["name"] for s in client.get(f"/api/items/{ids[0]}/sequences").json()]
    assert after == ["RenamedViaItem"]


def test_rename_and_delete_source_name(client):
    """A source file's imported-filename entries can be renamed and removed via
    the filenames endpoints; the stored file itself is untouched."""
    iid = client.get("/api/items").json()["items"][0]["id"]
    detail = client.get(f"/api/items/{iid}").json()
    f = next(f for f in detail["files"] if f["names"])
    fid, nid = f["id"], f["names"][0]["id"]

    # Rename.
    r = client.patch(f"/api/files/{fid}/names/{nid}", json={"name": "renamed/pic.png"})
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/items/{iid}").json()
    names = [n["name"] for ff in detail["files"] if ff["id"] == fid for n in ff["names"]]
    assert "renamed/pic.png" in names

    # Empty name is rejected; unknown ids 404.
    assert client.patch(f"/api/files/{fid}/names/{nid}", json={"name": "  "}).status_code == 400
    assert client.delete(f"/api/files/{fid}/names/999999").status_code == 404

    # Delete the name entry (the file stays, minus that alias).
    assert client.delete(f"/api/files/{fid}/names/{nid}").status_code == 200
    detail = client.get(f"/api/items/{iid}").json()
    ids = [n["id"] for ff in detail["files"] if ff["id"] == fid for n in ff["names"]]
    assert nid not in ids
    # The file version itself still exists.
    assert any(ff["id"] == fid for ff in detail["files"])


def test_add_filename_and_url_sources(client):
    """A file can gain an added filename source or a web-URL source (with an
    access date/time); URL sources carry accessed_at, filename sources don't."""
    iid = client.get("/api/items").json()["items"][0]["id"]
    fid = client.get(f"/api/items/{iid}").json()["files"][0]["id"]

    # Add a filename source.
    r = client.post(f"/api/files/{fid}/names", json={"name": "extra/copy.png"})
    assert r.status_code == 200, r.text
    # Add a web-URL source with an access date.
    r = client.post(f"/api/files/{fid}/names",
                    json={"url": "https://example.com/pic.png",
                          "accessed_at": "2026-07-17T10:00:00"})
    assert r.status_code == 200, r.text

    names = {n["name"]: n for ff in client.get(f"/api/items/{iid}").json()["files"]
             if ff["id"] == fid for n in ff["names"]}
    assert "extra/copy.png" in names and names["extra/copy.png"]["accessed_at"] is None
    url = names["https://example.com/pic.png"]
    assert url["accessed_at"] is not None and url["accessed_at"].startswith("2026-07-17")

    # Neither field → 400; a duplicate → 400.
    assert client.post(f"/api/files/{fid}/names", json={}).status_code == 400
    assert client.post(f"/api/files/{fid}/names",
                       json={"name": "extra/copy.png"}).status_code == 400


def test_url_source_without_access_time(client):
    """A web-URL source's access date/time is optional; it's still marked is_url."""
    iid = client.get("/api/items").json()["items"][0]["id"]
    fid = client.get(f"/api/items/{iid}").json()["files"][0]["id"]
    r = client.post(f"/api/files/{fid}/names",
                    json={"url": "https://example.com/no-date.png"})
    assert r.status_code == 200, r.text
    entry = next(n for ff in client.get(f"/api/items/{iid}").json()["files"]
                 if ff["id"] == fid for n in ff["names"]
                 if n["name"] == "https://example.com/no-date.png")
    assert entry["is_url"] is True and entry["accessed_at"] is None


def test_source_changes_are_revertible_in_history(client):
    """Adding and removing a source info logs revertible history events."""
    iid = client.get("/api/items").json()["items"][0]["id"]
    fid = client.get(f"/api/items/{iid}").json()["files"][0]["id"]

    # Add a source → a revertible "add_source" event; reverting removes it.
    nid = client.post(f"/api/files/{fid}/names", json={"name": "hist/src.png"}).json()["id"]
    ev = next(e for e in client.get(f"/api/history?limit=50").json()["events"]
              if e["action"] == "add_source")
    assert ev["revertible"] is True
    assert client.post("/api/history/revert", json={"event_ids": [ev["id"]]}).status_code == 200
    names = [n["name"] for ff in client.get(f"/api/items/{iid}").json()["files"]
             if ff["id"] == fid for n in ff["names"]]
    assert "hist/src.png" not in names

    # Remove an existing source → reverting re-adds it.
    fid2 = client.get(f"/api/items/{iid}").json()["files"][0]["id"]
    detail = client.get(f"/api/items/{iid}").json()
    victim = next(n for ff in detail["files"] if ff["id"] == fid2 for n in ff["names"])
    assert client.delete(f"/api/files/{fid2}/names/{victim['id']}").status_code == 200
    rev = next(e for e in client.get(f"/api/history?limit=50").json()["events"]
               if e["action"] == "remove_source")
    assert rev["revertible"] is True
    assert client.post("/api/history/revert", json={"event_ids": [rev["id"]]}).status_code == 200
    names = [n["name"] for ff in client.get(f"/api/items/{iid}").json()["files"]
             if ff["id"] == fid2 for n in ff["names"]]
    assert victim["name"] in names


def test_same_url_source_allowed_with_different_access_times(client):
    """The same URL may be recorded several times with *different* access
    times; only an identical (url, accessed_at) pair — or an identical
    filename — is rejected as a duplicate."""
    iid = client.get("/api/items").json()["items"][0]["id"]
    fid = client.get(f"/api/items/{iid}").json()["files"][0]["id"]
    url = "https://example.com/repeat.png"

    r = client.post(f"/api/files/{fid}/names",
                    json={"url": url, "accessed_at": "2026-07-01T08:00:00"})
    assert r.status_code == 200, r.text
    # Same URL + same time → duplicate.
    assert client.post(
        f"/api/files/{fid}/names",
        json={"url": url, "accessed_at": "2026-07-01T08:00:00"},
    ).status_code == 400
    # Same URL, different time → allowed.
    r = client.post(f"/api/files/{fid}/names",
                    json={"url": url, "accessed_at": "2026-07-02T09:30:00"})
    assert r.status_code == 200, r.text
    # Same URL with NO time → allowed once, then a duplicate.
    assert client.post(f"/api/files/{fid}/names",
                       json={"url": url}).status_code == 200
    assert client.post(f"/api/files/{fid}/names",
                       json={"url": url}).status_code == 400

    entries = [n for ff in client.get(f"/api/items/{iid}").json()["files"]
               if ff["id"] == fid for n in ff["names"] if n["name"] == url]
    assert len(entries) == 3
    times = {e["accessed_at"] and e["accessed_at"][:10] for e in entries}
    assert times == {"2026-07-01", "2026-07-02", None}


def test_sequence_item_metadata_has_count_and_dates(client):
    """A sequence container's Info fields: Type, member count (non-filterable),
    import + modification dates — and no borrowed member-file EXIF."""
    ids = [it["id"] for it in client.get("/api/items").json()["items"]]
    r = client.post("/api/sequences", json={"name": "Meta seq", "item_ids": ids})
    container = r.json()["item_id"]

    fields = {f["key"]: f for f in
              client.get(f"/api/items/{container}/metadata").json()["fields"]}
    assert fields["Type"]["value"] == "Sequence"
    assert fields["Items"]["value"] == str(len(ids))
    # "Is there anything to filter by" IS the row carrying a catalog name and
    # an atom — the `filterable` boolean beside them was a second copy of the
    # same fact and could drift from it.
    assert fields["Items"]["name"] is None
    assert fields["Type"]["name"] == "type"
    assert fields["Type"]["filter_value"] == "sequence"
    assert fields["Modified"]["name"] is None
    for key in ("First import", "Last import", "Modified"):
        assert key in fields
    # No EXIF of the borrowed member file leaks in.
    assert "Width" not in fields and "Make" not in fields


def test_the_face_match_threshold_persists_and_refuses_nonsense(client):
    """A 0 here would name every face after the first person in the library,
    so an out-of-range value falls back to the default rather than being
    clamped to whatever happens to be nearest."""
    from media_compost import faces as facelib

    base = client.get("/api/settings").json()
    # Not the default, so the read back proves the value was STORED.
    r = client.put("/api/settings", json={**base, "face_match_threshold": 0.55})
    assert r.status_code == 200, r.text
    assert client.get("/api/settings").json()["face_match_threshold"] == 0.55

    client.put("/api/settings", json={**base, "face_match_threshold": 0.0})
    assert (client.get("/api/settings").json()["face_match_threshold"]
            == facelib.MATCH_DEFAULT)


def test_training_can_be_turned_off_at_launch(tmp_path: Path):
    """A NAS or a laptop that could never finish a run says so once, and the
    routes go with the tabs — hiding a tab is not turning something off, and a
    stray bookmark or an old tab would otherwise still start a run.

    In a CHILD process, because this is decided when the app module is
    imported rather than per request: whether the training routes EXIST is a
    property of the install, not of one caller's library. That is the change
    from the middleware this replaced, which resolved the library through the
    dependency overrides — a hook only a test ever used, and the reason the
    routes had to be mounted-then-refused rather than simply absent.
    """
    import json
    import os
    import subprocess
    import sys
    import textwrap

    program = textwrap.dedent("""
        import json
        from fastapi.testclient import TestClient
        from media_compost.ui.server.app import app, TRAINING

        c = TestClient(app)
        paths = [p for p in app.openapi()["paths"] if p.startswith("/api/train")]
        print(json.dumps({
            "mounted": TRAINING,
            "train_paths": len(paths),
            "health": c.get("/api/health").json()["training"],
            "status": c.get("/api/train/status").status_code,
            "items": c.get("/api/items").status_code,
            "tags": c.get("/api/tags").status_code,
            "ml": c.get("/api/ml/models").status_code,
        }))
    """)
    env = {**os.environ, "MEDIA_COMPOST_TRAINING": "0",
           "MEDIA_COMPOST_DATA": str(tmp_path / "off")}
    got = subprocess.run([sys.executable, "-c", program], env=env,
                         capture_output=True, text=True)
    assert got.returncode == 0, got.stderr[-3000:]
    out = json.loads(got.stdout.strip().splitlines()[-1])
    assert out["mounted"] is False
    assert out["train_paths"] == 0
    assert out["health"] is False
    assert out["status"] == 404
    # Everything else is untouched: this is an organiser now, not a crippled
    # trainer.
    assert (out["items"], out["tags"], out["ml"]) == (200, 200, 200)


def test_trash_takes_an_item_out_of_its_sequences_and_restore_puts_it_back(client):
    """A trashed page must not go on holding a place in a chapter, so trash
    removes the item's membership rows (snapshotting them on the Trash row
    the way the groups always were) and restore re-adds each occurrence at
    its recorded position. The emptied-out sequence survives trash — restore
    needs somewhere to put the rows back."""
    ids = [it["id"] for it in client.get("/api/items").json()["items"]][:2]
    seq = client.post("/api/sequences",
                      json={"name": "TrashSeq", "item_ids": ids}).json()
    sid = seq["id"]
    members = client.get(f"/api/sequences/{sid}").json()["members"]
    assert [m["item_id"] for m in members] == ids

    r = client.post("/api/items/trash", json={"item_ids": [ids[0]]})
    assert r.status_code == 200, r.text
    members = client.get(f"/api/sequences/{sid}").json()["members"]
    assert [m["item_id"] for m in members] == [ids[1]]

    r = client.post("/api/items/restore", json={"item_ids": [ids[0]]})
    assert r.status_code == 200, r.text
    members = client.get(f"/api/sequences/{sid}").json()["members"]
    # Back at its original place — the survivors' positions were not
    # renumbered, so the recorded position still names the hole it left.
    assert [m["item_id"] for m in members] == ids

    # Trashing EVERY member leaves the sequence standing, empty: deleting it
    # would leave restore nothing to put the rows back into.
    client.post("/api/items/trash", json={"item_ids": ids})
    assert client.get(f"/api/sequences/{sid}").json()["members"] == []
    client.post("/api/items/restore", json={"item_ids": ids})
    members = client.get(f"/api/sequences/{sid}").json()["members"]
    assert [m["item_id"] for m in members] == ids


def test_reverting_a_trash_restores_sequence_membership_too(client):
    """The history revert calls the same primitive the Restore button does,
    and the snapshot lives on the Trash row — so undoing a trash brings the
    memberships back without the event learning anything new."""
    ids = [it["id"] for it in client.get("/api/items").json()["items"]][:2]
    sid = client.post("/api/sequences",
                      json={"name": "RevertSeq", "item_ids": ids}).json()["id"]
    client.post("/api/items/trash", json={"item_ids": [ids[0]]})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "trash_item")
    r = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.status_code == 200, r.text
    members = client.get(f"/api/sequences/{sid}").json()["members"]
    assert [m["item_id"] for m in members] == ids
