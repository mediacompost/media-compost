"""Stage-5 API contracts: paged/searchable catalogs, bulk membership, bulk
slim item details, and enqueue-by-scope.

The backward-compatibility rule under test everywhere: every listing endpoint
called WITHOUT paging params answers with exactly the old bare-list shape;
``limit`` opts in to the ``{"rows": [...], "total": N}`` envelope.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost.ui.config import UiConfig
from media_compost.db import Event, Item, ItemFaceRun, ItemGroup, Job
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from media_compost.testing import make_image


@pytest.fixture
def client_lib(tmp_path: Path):
    """A client plus its library, seeded with four distinct image items."""
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    src = tmp_path / "src"
    src.mkdir()
    paths = [make_image(src / f"img{i}.png", seed=i * 13 + 1)
             for i in range(4)]
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            paths, ImportOptions(folders_as_groups=False))
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _item_ids(lib) -> list[int]:
    with lib.db.session() as s:
        return sorted(s.execute(select(Item.id)).scalars().all())


# ---- envelope pagination ----------------------------------------------------


def test_tags_list_bare_and_envelope(client_lib):
    client, lib = client_lib
    ids = _item_ids(lib)
    for name in ("aa", "bb", "cc"):
        assert client.post("/api/tags", json={"name": name}).status_code == 200
    # aa on two items, bb on one — for the positive sort below.
    for iid in ids[:2]:
        client.post(f"/api/tags/assign/item/{iid}",
                    json={"tag": "aa", "negative": False})
    client.post(f"/api/tags/assign/item/{ids[0]}",
                json={"tag": "bb", "negative": False})

    # No params → the old bare list, name-ascending.
    bare = client.get("/api/tags").json()
    assert isinstance(bare, list)
    assert [r["name"] for r in bare] == ["aa", "bb", "cc"]

    # limit → the envelope; total is the FILTERED count.
    page = client.get("/api/tags?limit=2").json()
    assert set(page) == {"rows", "total"}
    assert page["total"] == 3 and len(page["rows"]) == 2
    assert [r["name"] for r in page["rows"]] == ["aa", "bb"]
    page2 = client.get("/api/tags?limit=2&offset=2").json()
    assert [r["name"] for r in page2["rows"]] == ["cc"]

    # q filters (case-insensitive substring), still a bare list without limit.
    assert [r["name"] for r in client.get("/api/tags?q=B").json()] == ["bb"]
    filt = client.get("/api/tags?q=b&limit=10").json()
    assert filt["total"] == 1 and filt["rows"][0]["name"] == "bb"

    # sort=positive desc ranks by the effective count.
    by_pos = client.get("/api/tags?sort=positive&dir=desc").json()
    assert [r["name"] for r in by_pos][:2] == ["aa", "bb"]
    assert by_pos[0]["positive"] == 2


def test_tag_names_autocomplete(client_lib):
    client, lib = client_lib
    ids = _item_ids(lib)
    for name in ("ba", "bb", "ab"):
        client.post("/api/tags", json={"name": name})
    for iid in ids[:2]:
        client.post(f"/api/tags/assign/item/{iid}",
                    json={"tag": "bb", "negative": False})
    client.post(f"/api/tags/assign/item/{ids[0]}",
                json={"tag": "ba", "negative": False})
    # A negative assignment is NOT a direct positive count.
    client.post(f"/api/tags/assign/item/{ids[2]}",
                json={"tag": "ab", "negative": True})

    rows = client.get("/api/tags/names?q=b").json()
    assert [(r["name"], r["positive"]) for r in rows] == [
        ("bb", 2), ("ba", 1), ("ab", 0)]
    # limit slices the ranked list.
    assert [r["name"] for r in
            client.get("/api/tags/names?q=b&limit=2").json()] == ["bb", "ba"]
    # An alias row carries its TARGET's direct count.
    client.post("/api/tags", json={"name": "second_b", "alias_of": "bb"})
    row = next(r for r in client.get("/api/tags/names?q=second").json()
               if r["name"] == "second_b")
    assert row["positive"] == 2
    # A LIKE wildcard in q is escaped, not interpreted.
    assert client.get("/api/tags/names?q=%25").json() == []


def test_value_namespaces_lists_value_tags_only(client_lib):
    """The VALUE row's namespace source: namespaces holding value-shaped
    tags, however low their counts — a count-ranked `/names` sample never
    surfaces them on a big library, which is why this is its own endpoint."""
    client, lib = client_lib
    for name in ("height:172cm", "height:1.9m", "people:3",
                 "costume:tiger", "plain"):
        client.post("/api/tags", json={"name": name})
    rows = client.get("/api/tags/value-namespaces").json()
    assert {(r["name"], r["count"]) for r in rows} == {
        ("height", 2), ("people", 1)}
    # The fragment narrows by namespace, case-insensitively.
    assert [r["name"] for r in
            client.get("/api/tags/value-namespaces?q=HEI").json()]         == ["height"]


def test_meta_counts_break_the_autocomplete_ties(client_lib):
    """The library's own count ranks first — a dump's numbers never outrank
    what is actually here — and EQUAL counts order by the highest per-meta
    count, which is the only order a freshly imported dump has. The rows
    carry the nonzero counts for the hover, never folded into `positive`."""
    client, lib = client_lib
    ids = _item_ids(lib)
    for name in ("earth", "elsewhere", "empty"):
        client.post("/api/tags", json={"name": name})
    for iid in ids[:2]:
        client.post(f"/api/tags/assign/item/{iid}",
                    json={"tag": "earth", "negative": False})
    tid = next(t2["id"] for t2 in client.get("/api/tags").json()
               if t2["name"] == "elsewhere")
    assert client.post(f"/api/tags/{tid}/meta-tags",
                       json={"name": "tumblr",
                             "count": 900}).status_code == 200
    rows = client.get("/api/tags/names?q=e").json()
    # The library's own two pictures still lead; the 900-elsewhere tag beats
    # only its equal-count sibling, and the hover payload says why.
    names = [r["name"] for r in rows]
    assert names.index("earth") < names.index("elsewhere") \
        < names.index("empty")
    by = {r["name"]: r for r in rows}
    assert by["elsewhere"]["positive"] == 0
    assert by["elsewhere"]["meta_counts"] == {"tumblr": 900}
    assert by["empty"]["meta_counts"] == {}
    assert by["earth"]["positive"] == 2


def test_the_autocomplete_ranks_exactness_and_position_over_counts(
        client_lib):
    """The tag called `ball` must beat `football` however their counts
    compare — the person has finished typing it — and `abc_123` beats
    `123_abc` for the fragment `abc`: a name that STARTS with what was typed
    is what was being reached for. Counts only break ties."""
    client, lib = client_lib
    ids = _item_ids(lib)
    for name in ("ball", "football", "abc_123", "123_abc"):
        client.post("/api/tags", json={"name": name})
    for iid in ids[:3]:
        client.post(f"/api/tags/assign/item/{iid}",
                    json={"tag": "football", "negative": False})
        client.post(f"/api/tags/assign/item/{iid}",
                    json={"tag": "123_abc", "negative": False})
    client.post(f"/api/tags/assign/item/{ids[0]}",
                json={"tag": "ball", "negative": False})

    assert [r["name"] for r in
            client.get("/api/tags/names?q=ball").json()] == [
        "ball", "football"]
    assert [r["name"] for r in
            client.get("/api/tags/names?q=abc").json()] == [
        "abc_123", "123_abc"]


def test_subjects_places_sequences_envelopes(client_lib):
    client, lib = client_lib
    ids = _item_ids(lib)

    client.post("/api/subjects", json={"display_name": "Alice"})
    client.post("/api/subjects", json={"display_name": "Bob"})
    bare = client.get("/api/subjects").json()
    assert isinstance(bare, list) and len(bare) == 2
    page = client.get("/api/subjects?limit=1").json()
    assert page["total"] == 2 and len(page["rows"]) == 1
    assert [r["display_name"] for r in
            client.get("/api/subjects?q=ali").json()] == ["Alice"]
    # q also matches the identity tag slug.
    assert [r["display_name"] for r in
            client.get("/api/subjects?q=subject:bob").json()] == ["Bob"]

    client.post("/api/places", json={"name": "Berlin, Germany"})
    client.post("/api/places", json={"name": "Tokyo, Japan"})
    bare = client.get("/api/places").json()
    assert isinstance(bare, list) and len(bare) == 2
    page = client.get("/api/places?limit=1").json()
    assert page["total"] == 2 and len(page["rows"]) == 1
    assert len(client.get("/api/places?q=berlin").json()) == 1
    assert client.get("/api/places?q=tokyo&limit=5").json()["total"] == 1

    client.post("/api/sequences",
                json={"name": "Chapter One", "item_ids": ids[:2]})
    bare = client.get("/api/sequences").json()
    assert isinstance(bare, list) and len(bare) == 1
    page = client.get("/api/sequences?limit=1").json()
    assert page["total"] == 1 and page["rows"][0]["name"] == "Chapter One"
    assert client.get("/api/sequences?q=zzz&limit=5").json() == {
        "rows": [], "total": 0}
    assert len(client.get("/api/sequences?q=chapter").json()) == 1


def test_named_faces_offset_opt_in(client_lib):
    client, _ = client_lib
    bare = client.get("/api/faces/named").json()
    assert set(bare) == {"clusters", "faces"}          # exactly the old shape
    paged = client.get("/api/faces/named?offset=0").json()
    assert set(paged) == {"clusters", "faces", "total"}
    assert paged["total"] == 0


# ---- metadata catalog -------------------------------------------------------


def test_metadata_names_only_and_values(client_lib):
    client, _ = client_lib
    full = client.get("/api/metadata/catalog").json()
    by_name = {e["name"]: e for e in full}
    # `mode` is indexed at import and enumerated (PNG imports → "RGB").
    assert by_name["mode"]["values"] == ["RGB"]
    assert by_name["type"]["values"] == ["image"]

    slim = client.get("/api/metadata/catalog?names_only=true").json()
    assert {e["name"] for e in slim} == {e["name"] for e in full}
    assert all(e["values"] is None for e in slim)
    # Everything else is unchanged.
    slim_mode = next(e for e in slim if e["name"] == "mode")
    assert slim_mode["count"] == by_name["mode"]["count"]
    assert slim_mode["mtype"] == by_name["mode"]["mtype"]

    assert client.get("/api/metadata/values?name=mode").json() == ["RGB"]
    assert client.get("/api/metadata/values?name=mode&q=rg").json() == ["RGB"]
    assert client.get("/api/metadata/values?name=mode&q=zz").json() == []
    assert client.get("/api/metadata/values?name=type").json() == ["image"]
    assert client.get("/api/metadata/values?name=format").json() == ["PNG"]
    assert client.get("/api/metadata/values?name=no_such").json() == []
    assert client.get("/api/metadata/values?name=").status_code == 400


# ---- bulk membership --------------------------------------------------------


def _events(lib, action: str) -> list[Event]:
    with lib.db.session() as s:
        rows = s.execute(select(Event).where(Event.action == action)
                         .order_by(Event.id)).scalars().all()
        s.expunge_all()
        return rows


def test_bulk_membership_mirrors_single_endpoints_and_reverts(client_lib):
    client, lib = client_lib
    ids = _item_ids(lib)
    gid = client.post("/api/groups", json={"name": "Bulk"}).json()["id"]

    # The reference: one single-endpoint add.
    client.post(f"/api/items/{ids[0]}/groups/{gid}")
    single = _events(lib, "add_to_group")[-1]
    single_data = json.loads(single.data)

    r = client.post("/api/groups/bulk-membership", json={
        "item_ids": ids[1:3], "add": [gid], "remove": []})
    body = r.json()
    assert {k: body[k] for k in ("ok", "added", "removed")} \
        == {"ok": True, "added": 2, "removed": 0}

    bulk = _events(lib, "add_to_group")[-2:]
    # …and the endpoint hands back the events it wrote, which is what a
    # caller with its own undo needs (the tag grid writes tags and groups
    # for one card and takes the lot back with one press).
    assert body["event_ids"] == [e.id for e in bulk]
    for ev, iid in zip(bulk, ids[1:3]):
        assert ev.action == single.action
        assert ev.entity_type == single.entity_type == "item"
        assert ev.entity_id == iid
        d = json.loads(ev.data)
        assert set(d) == set(single_data)               # same payload shape
        assert d == {"item_id": iid, "group_id": gid, "group_name": "Bulk"}
    with lib.db.session() as s:
        members = set(s.execute(select(ItemGroup.item_id).where(
            ItemGroup.group_id == gid)).scalars().all())
    assert members == set(ids[:3])

    # No-ops (already members) log nothing and count nothing.
    n_before = len(_events(lib, "add_to_group"))
    r = client.post("/api/groups/bulk-membership", json={
        "item_ids": ids[:3], "add": [gid], "remove": []})
    assert r.json()["added"] == 0
    assert len(_events(lib, "add_to_group")) == n_before

    # The EXISTING revert machinery undoes a bulk add.
    r = client.post("/api/history/revert",
                    json={"event_ids": [ev.id for ev in bulk]})
    assert r.status_code == 200
    with lib.db.session() as s:
        members = set(s.execute(select(ItemGroup.item_id).where(
            ItemGroup.group_id == gid)).scalars().all())
    assert members == {ids[0]}

    # Removal: same parity, and its revert restores the membership.
    client.post("/api/groups/bulk-membership", json={
        "item_ids": [ids[0], ids[3]], "add": [], "remove": [gid]})
    rem = _events(lib, "remove_from_group")
    assert len(rem) == 1                                # ids[3] was a no-op
    d = json.loads(rem[0].data)
    assert d == {"item_id": ids[0], "group_id": gid, "group_name": "Bulk"}
    client.post("/api/history/revert", json={"event_ids": [rem[0].id]})
    with lib.db.session() as s:
        assert set(s.execute(select(ItemGroup.item_id).where(
            ItemGroup.group_id == gid)).scalars().all()) == {ids[0]}


def test_group_assign_view_adds_the_whole_view(client_lib):
    """"A group from the current items" travels as a SCOPE, like the
    quick-assign view stamp: the server resolves it through the same search
    the grid pages through, and writes the same per-item events the single
    membership endpoints do."""
    client, lib = client_lib
    ids = _item_ids(lib)

    # Scope to aim at later: two of the four items in a source group.
    src = client.post("/api/groups", json={"name": "Src"}).json()["id"]
    client.post("/api/groups/bulk-membership", json={
        "item_ids": ids[:2], "add": [src], "remove": []})

    # The whole library: an unscoped view lands on every item.
    dst = client.post("/api/groups", json={"name": "Everything"}).json()["id"]
    r = client.post(f"/api/groups/{dst}/assign-view", json={})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "added": 4, "count": 4}
    with lib.db.session() as s:
        members = set(s.execute(select(ItemGroup.item_id).where(
            ItemGroup.group_id == dst)).scalars().all())
    assert members == set(ids)

    # A scoped view lands on exactly what the grid would show, and the events
    # are the single endpoint's (History and revert behave identically).
    dst2 = client.post("/api/groups", json={"name": "FromSrc"}).json()["id"]
    r = client.post(f"/api/groups/{dst2}/assign-view",
                    json={"groups": str(src)})
    assert r.json() == {"ok": True, "added": 2, "count": 2}
    with lib.db.session() as s:
        members = set(s.execute(select(ItemGroup.item_id).where(
            ItemGroup.group_id == dst2)).scalars().all())
    assert members == set(ids[:2])
    evs = _events(lib, "add_to_group")[-2:]
    assert {json.loads(e.data)["item_id"] for e in evs} == set(ids[:2])
    assert all(json.loads(e.data)["group_id"] == dst2 for e in evs)

    # Items already in the group are no-ops; an unknown group is a 404.
    assert client.post(f"/api/groups/{dst2}/assign-view",
                       json={"groups": str(src)}).json()["added"] == 0
    assert client.post("/api/groups/999999/assign-view",
                       json={}).status_code == 404


# ---- bulk slim details ------------------------------------------------------


def test_items_details_slim_shape_and_cap(client_lib):
    client, lib = client_lib
    ids = _item_ids(lib)
    i1, i2 = ids[0], ids[1]
    client.post(f"/api/tags/assign/item/{i1}",
                json={"tag": "cat", "negative": False})
    client.post(f"/api/items/{i1}/captions", json={"text": "a caption"})
    # A grouped placement on i1 so tag_groups/tag_instances carry the group.
    g = client.post(f"/api/tags/item/{i1}/groups",
                    json={"name": "Her"}).json()
    client.post(f"/api/tags/item/{i1}/group-tag",
                json={"tag": "hat", "group_id": g["id"], "negative": False})

    r = client.post("/api/items/details",
                    json={"item_ids": [i1, i2, 99999]})
    assert r.status_code == 200
    items = {e["id"]: e for e in r.json()["items"]}
    assert set(items) == {i1, i2}                       # unknown id absent
    d1 = items[i1]
    assert [c["text"] for c in d1["captions"]] == ["a caption"]
    assert d1["captions"][0]["pending"] is False
    assert d1["tags"] == ["cat", "hat"]
    assert [(t["id"], t["name"], t["system"]) for t in d1["tag_groups"]] == [
        (g["id"], "Her", False)]
    by_name = {t["name"]: t for t in d1["tag_instances"]}
    assert by_name["hat"]["group_id"] == g["id"]
    assert by_name["hat"]["placement_id"] is not None
    # The direct-but-unplaced tag shows as the implicit ungrouped instance.
    assert by_name["cat"]["group_id"] is None
    assert by_name["cat"]["pending"] is False
    d2 = items[i2]
    assert d2["captions"] == [] and d2["tags"] == []

    over = client.post("/api/items/details",
                       json={"item_ids": list(range(501))})
    assert over.status_code == 413


def test_items_details_carry_instruction_refs_and_links(client_lib):
    """An instruction's sources and the item's relationships travel too — the
    grid's copy actions rebuild both on another item, and neither is derivable
    from the tags."""
    client, lib = client_lib
    ids = _item_ids(lib)
    i1, i2, i3 = ids[0], ids[1], ids[2]
    cap = client.post(f"/api/items/{i1}/captions",
                      json={"text": "make it snow", "kind": "instruction"}).json()
    client.put(f"/api/items/{i1}/captions/{cap['id']}/refs",
               json={"item_ids": [i3, i2]})
    rel = client.post("/api/relationships", json={
        "from_item_id": i1, "to_item_id": i2, "kind": "manual"}).json()
    client.post(f"/api/relationships/{rel['id']}/tags", json={"name": "before"})

    items = {e["id"]: e for e in client.post(
        "/api/items/details", json={"item_ids": [i1, i2]}).json()["items"]}
    c = items[i1]["captions"][0]
    assert c["kind"] == "instruction"
    # In order, and bare ids — nothing here renders a reference strip.
    assert [r["item_id"] for r in c["refs"]] == [i3, i2]
    assert items[i1]["links"] == [
        {"other_item_id": i2, "outgoing": True, "kind": "manual",
         "tags": ["before"]}]
    # The same edge, from the other end.
    assert items[i2]["links"] == [
        {"other_item_id": i1, "outgoing": False, "kind": "manual",
         "tags": ["before"]}]


# ---- enqueue by scope -------------------------------------------------------


def test_enqueue_scope_resolves_subtree_minus_trashed_hidden(
        client_lib, monkeypatch):
    client, lib = client_lib
    ids = _item_ids(lib)
    i1, i2, i3, i4 = ids
    parent = client.post("/api/groups", json={"name": "Scope"}).json()["id"]
    child = client.post("/api/groups",
                        json={"name": "Sub", "parent_id": parent}).json()["id"]
    for iid in (i1, i2, i3):
        client.post(f"/api/items/{iid}/groups/{parent}")
    client.post(f"/api/items/{i4}/groups/{child}")     # via the subtree
    client.post("/api/items/hide", json={"item_ids": [i2], "hidden": True})
    client.post("/api/items/trash", json={"item_ids": [i3]})
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    r = client.post("/api/ml/enqueue-scope", json={
        "kind": "faces", "model": "anime_face_magi", "groups": [parent]})
    assert r.json() == {"queued": 2, "skipped": 0}     # i1 + i4
    with lib.db.session() as s:
        job = s.execute(select(Job).order_by(Job.id.desc())).scalars().first()
        assert job.kind == "faces"
        assert sorted(json.loads(job.item_ids)) == sorted([i1, i4])

    # skip_done leaves out what this model already ran over (ItemFaceRun).
    with lib.db.session() as s:
        s.add(ItemFaceRun(item_id=i1, model="anime_face_magi"))
        s.commit()
    r = client.post("/api/ml/enqueue-scope", json={
        "kind": "faces", "model": "anime_face_magi", "groups": [parent],
        "skip_done": True})
    assert r.json() == {"queued": 1, "skipped": 1}
    with lib.db.session() as s:
        job = s.execute(select(Job).order_by(Job.id.desc())).scalars().first()
        # One item → a plain per-item job (no batched item_ids marker).
        assert job.item_id == i4 and job.item_ids is None

    assert client.post("/api/ml/enqueue-scope", json={
        "kind": "nope", "model": "", "groups": [parent]}).status_code == 400
    assert client.post("/api/ml/enqueue-scope", json={
        "kind": "faces", "model": "m", "groups": []}).json() == {
            "queued": 0, "skipped": 0}


def test_enqueue_scope_carries_the_extra_output_choice(client_lib, monkeypatch):
    """`EnqueueScope.into_sequence`: the context menu's "place panels in a
    sequence" switch, over a whole group.

    It is silent when wrong — the field would be dropped and every run made
    with the switch ON would quietly leave the panels loose. Both directions
    are asserted, because a hardcoded False passes the off case; the flag
    rides in the job's `options`, where the extras a single kind asks for
    live (a reference image, an OCR engine).
    """
    client, lib = client_lib
    ids = _item_ids(lib)
    parent = client.post("/api/groups", json={"name": "Extra"}).json()["id"]
    client.post(f"/api/items/{ids[0]}/groups/{parent}")
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    def last_options() -> dict:
        with lib.db.session() as s:
            job = s.execute(
                select(Job).order_by(Job.id.desc())).scalars().first()
            return json.loads(job.options) if job.options else {}

    for want in (True, False):
        r = client.post("/api/ml/enqueue-scope", json={
            "kind": "panels", "model": "magi_panels", "groups": [parent],
            "into_sequence": want})
        assert r.json() == {"queued": 1, "skipped": 0}
        assert last_options().get("into_sequence", False) is want

    # Unmentioned is OFF, so every caller written before the field enqueues
    # exactly what it always did.
    client.post("/api/ml/enqueue-scope", json={
        "kind": "panels", "model": "magi_panels", "groups": [parent]})
    assert last_options().get("into_sequence", False) is False

    # And a kind that offers no such switch never carries it, however loudly
    # a caller asks — the task declaration is the one list.
    client.post("/api/ml/enqueue-scope", json={
        "kind": "bg_removal", "model": "withoutbg", "groups": [parent],
        "into_sequence": True})
    assert "into_sequence" not in last_options()


def test_enqueue_scope_resolves_a_fixed_sidebar_view(client_lib, monkeypatch):
    """`EnqueueScope.view`: a FIXED entry's scope, resolved through
    `search_filtered` — the grid's own semantics, so a Hidden run reaches
    hidden items, an Untagged run only the untagged, and the trash stays out
    everywhere."""
    client, lib = client_lib
    ids = _item_ids(lib)
    i1, i2, i3, i4 = ids
    client.post(f"/api/tags/assign/item/{i1}", json={"tag": "tagged_one"})
    client.post("/api/items/hide", json={"item_ids": [i2], "hidden": True})
    client.post("/api/items/trash", json={"item_ids": [i3]})
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    def queued_items(view: str) -> list[int]:
        r = client.post("/api/ml/enqueue-scope", json={
            "kind": "faces", "model": "anime_face_magi", "view": view})
        assert r.status_code == 200, r.text
        if not r.json()["queued"]:
            return []
        with lib.db.session() as s:
            job = s.execute(
                select(Job).order_by(Job.id.desc())).scalars().first()
            return sorted(json.loads(job.item_ids)
                          if job.item_ids else [job.item_id])

    # "all": everything visible — no hidden, no trash.
    assert queued_items("all") == sorted([i1, i4])
    # "untagged": the tagged one drops out too.
    assert queued_items("untagged") == [i4]
    # "hidden": exactly the hidden item.
    assert queued_items("hidden") == [i2]
    # An unknown view is refused by name, never resolved as something else.
    assert client.post("/api/ml/enqueue-scope", json={
        "kind": "faces", "model": "m", "view": "nope"}).status_code == 400


def test_enqueue_scope_carries_detect_with_into_the_job_options(
        client_lib, monkeypatch):
    """The context menus' "read it, then remove" over a scope: `detect_with`
    rides the scope enqueue exactly as it rides the per-item one — into each
    queued job's options — and a non-OCR model is refused by name rather
    than queuing a removal that silently paints out nothing."""
    client, lib = client_lib
    ids = _item_ids(lib)
    parent = client.post("/api/groups", json={"name": "Read"}).json()["id"]
    for iid in ids[:2]:
        client.post(f"/api/items/{iid}/groups/{parent}")
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    r = client.post("/api/ml/enqueue-scope", json={
        "kind": "text_removal", "model": "lama_regions", "groups": [parent],
        "detect_with": "rapidocr_multi"})
    assert r.json() == {"queued": 2, "skipped": 0}
    with lib.db.session() as s:
        jobs = s.execute(select(Job).order_by(Job.id.desc())
                         .limit(2)).scalars().all()
        for job in jobs:
            assert job.kind == "text_removal"
            assert json.loads(job.options) == {"detect_with": "rapidocr_multi"}

    assert client.post("/api/ml/enqueue-scope", json={
        "kind": "text_removal", "model": "lama_regions", "groups": [parent],
        "detect_with": "not_an_ocr_model"}).status_code == 400


# ---- quick-assign over a whole VIEW ------------------------------------------
#
# `POST /api/tags/quick-assign/view` had no test at all, which is worth saying
# out loud: it is a write across every item a scope resolves to — the whole
# library when the grid is unfiltered — and it is the one endpoint here whose
# blast radius is unbounded. Its sibling `POST /api/groups/{id}/assign-view`
# was covered above and its docstring names this one as the analogue, so the
# analogy was being asserted about the endpoint that HAD coverage.


def _tags_on(client, iid: int) -> set[str]:
    return {t["name"] for t in client.get(f"/api/items/{iid}").json()["tags"]}


def test_quick_assign_view_stamps_every_item_the_grid_is_showing(client_lib):
    client, lib = client_lib
    ids = _item_ids(lib)
    r = client.post("/api/tags/quick-assign/view",
                    json={"positive": ["sweep"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "count": 4}
    for iid in ids:
        assert "sweep" in _tags_on(client, iid)


def test_the_scope_it_takes_is_the_one_the_grid_pages_through(client_lib):
    """The body INHERITS `ItemSearchRequest`, so "everything here" is
    resolved through the same `search_filtered` the grid uses — the two
    cannot drift into meaning different views."""
    client, lib = client_lib
    ids = _item_ids(lib)
    gid = client.post("/api/groups", json={"name": "Half"}).json()["id"]
    client.post("/api/groups/bulk-membership", json={
        "item_ids": ids[:2], "add": [gid], "remove": []})

    r = client.post("/api/tags/quick-assign/view",
                    json={"positive": ["ingroup"], "groups": str(gid)})
    assert r.json() == {"ok": True, "count": 2}
    assert all("ingroup" in _tags_on(client, i) for i in ids[:2])
    assert not any("ingroup" in _tags_on(client, i) for i in ids[2:])

    # …and a search TREE narrows it the same way, since that is the same
    # field `POST /api/items/query` takes.
    body = {"positive": ["searched"],
            "query": {"type": "group", "op": "and",
                      "children": [{"type": "tag", "name": "ingroup"}]}}
    assert client.post("/api/tags/quick-assign/view",
                       json=body).json()["count"] == 2
    assert all("searched" in _tags_on(client, i) for i in ids[:2])


def test_a_set_may_carry_group_memberships_beside_its_tags(client_lib):
    """`assign_groups` stamps membership with the tags — one gesture, one
    request — removes it with `remove`, and refuses a smart group exactly
    as any manual membership is refused."""
    client, lib = client_lib
    ids = _item_ids(lib)
    gid = client.post("/api/groups", json={"name": "Stamped"}).json()["id"]
    r = client.post("/api/tags/quick-assign", json={
        "item_ids": ids[:2], "positive": ["boxed"], "negative": [],
        "assign_groups": [gid]})
    assert r.status_code == 200, r.text
    in_group = lambda i: gid in client.get(f"/api/items/{i}").json()["group_ids"]
    assert in_group(ids[0]) and in_group(ids[1]) and not in_group(ids[2])
    # Remove takes the membership back with the tags.
    client.post("/api/tags/quick-assign", json={
        "item_ids": ids[:1], "positive": ["boxed"], "negative": [],
        "assign_groups": [gid], "remove": True})
    assert not in_group(ids[0]) and in_group(ids[1])
    # The view stamp assigns them too.
    client.post("/api/tags/quick-assign/view", json={
        "positive": ["boxed2"], "assign_groups": [gid]})
    assert all(in_group(i) for i in ids)
    # A smart group refuses, like every manual membership.
    smart = client.post("/api/groups", json={
        "name": "Auto", "smart_query": "boxed2"}).json()["id"]
    r = client.post("/api/tags/quick-assign", json={
        "item_ids": ids[:1], "positive": [], "negative": [],
        "assign_groups": [smart]})
    assert r.status_code == 400


def test_a_negative_tag_and_a_removal_travel_the_same_way(client_lib):
    client, lib = client_lib
    ids = _item_ids(lib)
    client.post("/api/tags/quick-assign/view",
                json={"positive": ["yes"], "negative": ["no"]})
    detail = client.get(f"/api/items/{ids[0]}").json()
    signs = {t["name"]: t.get("negative", False) for t in detail["tags"]}
    assert signs.get("yes") is False and signs.get("no") is True

    # `remove` deletes the assignment whatever its sign, and the LISTS are
    # what say which tags it is about — so a removal names them in `positive`
    # too. (`positive: []` with `remove: true` means nothing and answers 200,
    # which is what a Remove button that does nothing looks like.)
    r = client.post("/api/tags/quick-assign/view",
                    json={"positive": ["yes", "no"], "remove": True})
    assert r.json()["ok"] is True
    for iid in ids:
        assert {"yes", "no"}.isdisjoint(_tags_on(client, iid))


def test_it_writes_one_event_per_item_and_they_revert(client_lib):
    """The contract that makes the chunking necessary: a stamp over a view
    logs per (item, tag), which is also what makes it undoable."""
    client, lib = client_lib
    ids = _item_ids(lib)
    client.post("/api/tags/quick-assign/view", json={"positive": ["logged"]})
    with lib.db.session() as s:
        evs = [e for e in s.execute(select(Event)).scalars().all()
               if e.action == "add_tag"
               and json.loads(e.data).get("tag") == "logged"]
    assert len(evs) == 4
    assert {json.loads(e.data)["item_id"] for e in evs} == set(ids)

    client.post("/api/history/revert",
                json={"event_ids": [e.id for e in evs]})
    for iid in ids:
        assert "logged" not in _tags_on(client, iid)


def test_the_chunked_commit_is_per_transaction_not_per_item(client_lib,
                                                            monkeypatch):
    """`stamp` stays ONE bulk pass; what is chunked is the transaction around
    it. Rewriting the chunk loop as a loop over the single-item op would be
    observably identical and a large silent perf regression — the same trap
    `tests/test_perf_smoke.py` guards for the other bulk ops."""
    from media_compost.ui.server import viewscope
    from media_compost.ui.server.routers import tags as tags_router

    client, _lib = client_lib
    calls: list[int] = []
    real = tags_router.tagassign.stamp

    def counting(ctx, item_ids, *a, **kw):
        calls.append(len(item_ids))
        return real(ctx, item_ids, *a, **kw)

    monkeypatch.setattr(tags_router.tagassign, "stamp", counting)
    monkeypatch.setattr(viewscope, "VIEW_CHUNK", 3)
    assert client.post("/api/tags/quick-assign/view",
                       json={"positive": ["chunked"]}).json()["count"] == 4
    # Four items at a chunk size of three: two passes, sized 3 and 1 — not
    # four passes of one.
    assert calls == [3, 1]


def test_an_empty_view_is_a_no_op_rather_than_the_whole_library(client_lib):
    """The failure that would matter most: a scope resolving to nothing must
    stamp nothing, not fall back to 'everything'."""
    client, lib = client_lib
    gid = client.post("/api/groups", json={"name": "Empty"}).json()["id"]
    r = client.post("/api/tags/quick-assign/view",
                    json={"positive": ["nope"], "groups": str(gid)})
    assert r.json() == {"ok": True, "count": 0}
    for iid in _item_ids(lib):
        assert "nope" not in _tags_on(client, iid)


def test_the_trash_is_its_own_view(client_lib):
    """A scope flag the grid has and the stamp must honour — tagging "here"
    while looking at the Trash must not reach the live library."""
    client, lib = client_lib
    ids = _item_ids(lib)
    client.post("/api/items/trash", json={"item_ids": [ids[0]]})
    r = client.post("/api/tags/quick-assign/view",
                    json={"positive": ["binned"], "trash": True})
    assert r.json() == {"ok": True, "count": 1}
    assert "binned" in _tags_on(client, ids[0])
    for iid in ids[1:]:
        assert "binned" not in _tags_on(client, iid)


def test_item_pages_carry_a_library_rev_that_moves_on_external_writes(
        client_lib):
    """Offset pages assembled from two library states overlap under a
    newest-first sort, and a SCRIPT importing in another process sends no
    invalidation — `rev` is what lets the grid notice the mix and re-sync
    (the reported symptom: duplicate cards and a selection aimed at a layout
    that no longer exists, until a reload)."""
    client, lib = client_lib
    page = client.post("/api/items/query", json={}).json()
    assert page["rev"]
    runs = client.post("/api/items/groups",
                       json={"group_by": "day", "sort": "recent_desc"}).json()
    assert runs["rev"] == page["rev"], "pages and layout describe one state"
    # An EXTERNAL writer moves it — the Python API in another session, which
    # is exactly the crawler scenario the mechanism exists for. (An import
    # moves the item pk; a script's run event lands only at its END, so the
    # event pk alone would sit still through one.)
    import tempfile
    from pathlib import Path
    from media_compost import open_library
    from tests.core.conftest import make_image
    with tempfile.TemporaryDirectory() as tmp:
        data = make_image(Path(tmp) / "new.png", seed=77).read_bytes()
    with open_library(lib.config.data_dir) as ext:
        assert ext.import_bytes(data, "new.png")
    moved = client.post("/api/items/query", json={}).json()["rev"]
    assert moved != page["rev"]
    # A re-import TOUCH is the harder half: an exact duplicate creates no
    # item and `_touch_imported` logs no event, yet it floats the matched
    # item to the top of the default Imported ↓ sort — so the pk pair alone
    # sat still through exactly the write that reorders the view (a crawler
    # re-run over already-imported content). `last_imported_at` is what has
    # to move the rev.
    with open_library(lib.config.data_dir) as ext:
        got = ext.import_bytes(data, "new.png")
        assert got.item is not None
    touched = client.post("/api/items/query", json={}).json()["rev"]
    assert touched != moved
