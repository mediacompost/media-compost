"""Smart groups — membership DERIVED from a stored search string.

What these pin: the rebuild (query in, `item_groups` rows out, diffed — and
refreshed by the Database-level sweeper after ORDINARY writes, so a tag edit
moves membership with no manual step), the granted tags flowing to derived
members exactly as they do to manual ones, the REFUSALS (no manual
assignment, no children, no becoming smart while holding children), the way
back (clearing the query keeps the members as ordinary ones), and the folder
round trip (the query travels on `groups.json`, the memberships deliberately
do not and are refit on restore).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost.db import Group, ItemGroup
from media_compost.testing import make_image
from media_compost.ui.config import UiConfig
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(6):
        make_image(src / f"p{i}.png", seed=i, size=(200, 150))
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([src], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib
        yield c
    app.dependency_overrides.clear()


def _items(client) -> list[int]:
    return sorted(it["id"] for it in client.get("/api/items").json()["items"])


def _tag(client, item_id: int, name: str, on: bool = True) -> None:
    if on:
        r = client.post(f"/api/tags/assign/item/{item_id}",
                        json={"tag": name, "negative": False})
    else:
        r = client.delete(f"/api/tags/assign/item/{item_id}/{name}")
    assert r.status_code == 200, r.text


def _node(client, gid: int) -> dict:
    def walk(nodes):
        for n in nodes:
            if n["id"] == gid:
                return n
            got = walk(n["children"])
            if got:
                return got
    return walk(client.get("/api/groups").json())


def _members(lib, gid: int) -> set[int]:
    with lib.db.session() as s:
        return set(s.execute(select(ItemGroup.item_id).where(
            ItemGroup.group_id == gid)).scalars().all())


def test_membership_follows_the_query_with_no_manual_step(client):
    """Created smart → members materialize at once; a tag edit later moves
    membership through the commit-hook sweeper (synchronous under the test
    suite's determinism knob), with nobody calling a rebuild."""
    ids = _items(client)
    _tag(client, ids[0], "cat")
    _tag(client, ids[1], "cat")
    g = client.post("/api/groups", json={"name": "Cats",
                                         "smart_query": "cat"}).json()
    assert g["smart"] is True
    assert _members(client.lib, g["id"]) == {ids[0], ids[1]}
    assert _node(client, g["id"])["count"] == 2

    # An ordinary write moves membership by itself.
    _tag(client, ids[2], "cat")
    assert _members(client.lib, g["id"]) == {ids[0], ids[1], ids[2]}
    _tag(client, ids[0], "cat", on=False)
    assert _members(client.lib, g["id"]) == {ids[1], ids[2]}


def test_granted_tags_flow_to_derived_members(client):
    """A smart group's tags grant to its members exactly as a manual group's
    do — membership rows are ordinary rows, which is the whole point of
    materializing them."""
    ids = _items(client)
    _tag(client, ids[0], "cat")
    g = client.post("/api/groups", json={"name": "Cats",
                                         "smart_query": "cat"}).json()
    r = client.post(f"/api/tags/assign/group/{g['id']}",
                    json={"tag": "pet", "negative": False})
    assert r.status_code == 200, r.text
    found = client.post("/api/items/query", json={
        "query": {"type": "group", "op": "and", "children": [
            {"type": "tag", "name": "pet", "sign": "pos", "have": True}]},
    }).json()
    assert [i["id"] for i in found["items"]] == [ids[0]]


def test_manual_assignment_and_children_are_refused(client):
    ids = _items(client)
    g = client.post("/api/groups", json={"name": "Smart",
                                         "smart_query": "cat"}).json()
    # No manual membership, single or bulk, in or out.
    r = client.post(f"/api/items/{ids[0]}/groups/{g['id']}")
    assert r.status_code == 400, r.text
    r = client.post("/api/groups/bulk-membership", json={
        "item_ids": [ids[0]], "add": [g["id"]], "remove": []})
    assert r.status_code == 400
    # No children: neither created under it nor moved under it.
    assert client.post("/api/groups", json={
        "name": "Kid", "parent_id": g["id"]}).status_code == 400
    other = client.post("/api/groups", json={"name": "Plain"}).json()
    assert client.post(f"/api/groups/{other['id']}/move", json={
        "new_parent_id": g["id"]}).status_code == 400
    # An ordinary group — children or not — never becomes smart (identity).
    parent = client.post("/api/groups", json={"name": "Parent"}).json()
    client.post("/api/groups", json={"name": "Child",
                                     "parent_id": parent["id"]})
    assert client.patch(f"/api/groups/{parent['id']}", json={
        "smart_query": "cat"}).status_code == 400


def test_smart_is_an_identity_fixed_at_creation(client):
    """A group is created smart or ordinary and never converts: giving an
    ordinary group a query is refused, and emptying a smart group's rule
    leaves it smart — holding nothing, since an empty rule has not said
    which items yet (never "everything")."""
    ids = _items(client)
    _tag(client, ids[0], "cat")
    plain = client.post("/api/groups", json={"name": "Plain"}).json()
    assert client.patch(f"/api/groups/{plain['id']}", json={
        "smart_query": "cat"}).status_code == 400
    g = client.post("/api/groups", json={"name": "Cats",
                                         "smart_query": "cat"}).json()
    assert _members(client.lib, g["id"]) == {ids[0]}
    assert client.patch(f"/api/groups/{g['id']}", json={
        "smart_query": ""}).status_code == 200
    detail = client.get(f"/api/groups/{g['id']}").json()
    assert detail["smart_query"] == ""
    assert _node(client, g["id"])["smart"] is True
    assert _members(client.lib, g["id"]) == set()
    # Still smart: manual membership stays refused.
    r = client.post("/api/groups/bulk-membership", json={
        "item_ids": [ids[1]], "add": [g["id"]], "remove": []})
    assert r.status_code == 400


def test_a_smart_group_can_be_created_with_an_empty_rule(client):
    """The menu's "Smart group" with no active search: smart from birth,
    holding nothing until the rule is written."""
    g = client.post("/api/groups", json={"name": "Later",
                                         "smart_query": ""}).json()
    assert g["smart"] is True and g["icon"] == "folder"
    assert _members(client.lib, g["id"]) == set()


def test_an_unparseable_query_is_refused(client):
    # The grammar reads almost anything as tag terms; an unbalanced paren is
    # what genuinely fails to parse.
    assert client.post("/api/groups", json={
        "name": "Broken", "smart_query": "("}).status_code == 400


def test_editing_the_query_refits_on_the_spot(client):
    ids = _items(client)
    _tag(client, ids[0], "cat")
    _tag(client, ids[1], "dog")
    g = client.post("/api/groups", json={"name": "Pets",
                                         "smart_query": "cat"}).json()
    assert _members(client.lib, g["id"]) == {ids[0]}
    assert client.patch(f"/api/groups/{g['id']}", json={
        "smart_query": "dog"}).status_code == 200
    assert _members(client.lib, g["id"]) == {ids[1]}


def test_the_query_round_trips_and_membership_is_refit_on_restore(
        client, tmp_path):
    ids = _items(client)
    _tag(client, ids[0], "cat")
    g = client.post("/api/groups", json={"name": "Cats",
                                         "smart_query": "cat"}).json()
    from media_compost import open_library

    with open_library(tmp_path / "restored", source="cli") as fresh:
        stats = fresh.merge_library(tmp_path / "data")
        assert not stats.errors, stats.errors
        got = fresh.groups["Cats"]
        assert got.smart and got.smart_query == "cat"
        # Membership never travels (item.json holds no smart memberships);
        # the end-of-run refit is what filled it.
        names = [i.name for i in got.items]
        assert len(names) == 1 and names[0].endswith("p0.png")


def _tree_row(client, gid: int) -> dict:
    def walk(nodes):
        for n in nodes:
            if n["id"] == gid:
                return n
            hit = walk(n["children"])
            if hit:
                return hit
        return None

    row = walk(client.get("/api/groups").json())
    assert row is not None, f"group {gid} not in the tree"
    return row


def test_a_duplicate_of_an_ordinary_group_is_ordinary(client):
    """The clone passed ``smart_query or ""`` — and the empty string IS a
    smart group, so every duplicate of an ordinary group came out smart with
    an empty rule: it held nothing (the membership copy was skipped) and
    refused child groups, which is exactly what a duplicate is not."""
    ids = _items(client)
    g = client.post("/api/groups", json={"name": "Originals"}).json()
    for iid in ids[:3]:
        assert client.post(
            f"/api/items/{iid}/groups/{g['id']}").status_code == 200
    dup_id = client.post(f"/api/groups/{g['id']}/duplicate",
                         json={}).json()["id"]
    row = _tree_row(client, dup_id)
    assert row["smart"] is False
    # The items assigned to the original are on the duplicate too.
    assert _members(client.lib, dup_id) == set(ids[:3])
    # And it parents like any ordinary group.
    other = client.post("/api/groups", json={"name": "Child"}).json()
    assert client.post(f"/api/groups/{other['id']}/move", json={
        "new_parent_id": dup_id}).status_code == 200


def test_a_duplicate_of_a_smart_group_stays_smart(client):
    ids = _items(client)
    _tag(client, ids[0], "cat")
    g = client.post("/api/groups", json={"name": "Cats",
                                         "smart_query": "cat"}).json()
    dup_id = client.post(f"/api/groups/{g['id']}/duplicate",
                         json={}).json()["id"]
    assert _tree_row(client, dup_id)["smart"] is True
    assert _members(client.lib, dup_id) == {ids[0]}


# ---- what a sweep COSTS -----------------------------------------------------
#
# Both of these guard a failure that is silent by construction: the answer
# stays right and only the price moves. What that price bought on a real
# library was a web import getting slower with every batch — the sweeper runs
# after every commit burst, so during an import it was reading the whole
# library, releasing, and starting again, continuously.


def test_a_rebuild_does_not_read_the_membership_into_python(client):
    """The exact path diffs IN SQLITE, in a fixed number of statements.

    It used to come back as two Python sets — every matching id and every
    current member — which on a 1.1M-item library measured 5.8 s and 309 MB
    of peak allocation per sweep, against 0.83 s and 0.1 MB for the same
    answer as two statements. The STATEMENT COUNT is what is asserted rather
    than the clock: the clock is the symptom, and the chunked Python path
    this replaced issues one statement per chunk, so its count grows with the
    group while this one cannot.
    """
    from sqlalchemy import delete, event, select as sa_select, text as sa_text

    from media_compost.db import File, Group, Item, ItemTag, Tag
    from media_compost.ops import smartgroups
    from media_compost.ops.context import Ctx

    lib = client.lib
    for iid in _items(client):
        _tag(client, iid, "bulky")
    gid = client.post("/api/groups", json={
        "name": "Everything", "smart_query": "bulky"}).json()["id"]

    def rebuild_from_scratch() -> tuple[list[str], int]:
        """The statements a fill-from-EMPTY issues, and what it ends holding.

        From empty, so the rebuild has every member to write — a no-op sweep
        writes nothing on any path and would say nothing about how.
        """
        seen: list[str] = []

        def before(conn, cursor, statement, params, context, many):
            seen.append(" ".join(statement.split()))

        with lib.db.session() as s:
            s.execute(delete(ItemGroup).where(ItemGroup.group_id == gid))
            s.commit()
            event.listen(s.bind, "before_cursor_execute", before)
            try:
                out = smartgroups.rebuild(Ctx(session=s), s.get(Group, gid))
            finally:
                event.remove(s.bind, "before_cursor_execute", before)
            s.rollback()
        return seen, out["members"]

    first, small = rebuild_from_scratch()
    # Members enough to cross several chunk boundaries on the old path.
    with lib.db.session() as s:
        tid = s.execute(sa_select(Tag.id).where(Tag.name == "bulky")).scalar()
        s.execute(Item.__table__.insert(), [
            {"uid": f"extra{i}", "name": f"extra {i}", "kind": "image"}
            for i in range(1200)])
        fresh = s.execute(sa_select(Item.id).where(
            Item.uid.like("extra%"))).scalars().all()
        # With a file each, and active — a search joins the active file, so
        # file-less rows match nothing and the group would stay at six.
        s.execute(File.__table__.insert(), [
            {"item_id": iid, "number": 1, "path": "files/1.png",
             "sha256": f"x{iid}", "width": 10, "height": 10, "bytes": 1,
             "format": "png"} for iid in fresh])
        s.execute(sa_text(
            "UPDATE items SET active_file_id = (SELECT id FROM files "
            "WHERE files.item_id = items.id) WHERE active_file_id IS NULL"))
        s.execute(ItemTag.__table__.insert(), [
            {"item_id": iid, "tag_id": tid, "negative": False,
             "pending": False} for iid in fresh])
        s.commit()
    again, big = rebuild_from_scratch()

    assert big >= small + 1200, "the extra items are not in the group at all"
    # THE SHAPE, not the count: `session.execute(insert, [rows])` is ONE
    # cursor call however many rows it carries, so counting statements cannot
    # tell the two paths apart. What can is that the ids never become
    # parameters — the insert SELECTS them and the delete excludes them with
    # a subquery, which is the whole of "the diff stays in SQLite".
    inserts = [q for q in again if q.startswith("INSERT INTO item_groups")]
    deletes = [q for q in again if q.startswith("DELETE FROM item_groups")]
    assert inserts and all("SELECT" in q for q in inserts), (
        f"the insert carries rows rather than a query: {inserts[:1]}")
    assert deletes and all("SELECT" in q for q in deletes), (
        f"the delete carries ids rather than a query: {deletes[:1]}")
    # …and the same holds for a group of six, so this is about the shape
    # rather than about having crossed some size.
    assert all("SELECT" in q for q in first
               if q.startswith(("INSERT INTO item_groups",
                                "DELETE FROM item_groups")))


def test_the_sweeper_holds_off_by_what_the_LAST_sweep_COST():
    """A debounce says how long to wait for a burst to end. It says nothing
    about what a sweep itself costs, and the two only compose while that cost
    is small — at 5.8 s a sweep against a 0.75 s debounce, this thread never
    stops reading the library."""
    from media_compost.smartsweep import SmartGroupSweeper as S

    # Cheap sweep: the debounce still decides, so a small library is exactly
    # as live as it was.
    assert S.wait_after(0.0) == S.DEBOUNCE
    assert S.wait_after(0.01) == S.DEBOUNCE
    # Expensive sweep: bounded at 1/DUTY of the time, whatever it cost.
    for cost in (1.0, 5.8, 60.0):
        wait = S.wait_after(cost)
        assert cost / (cost + wait) <= 1.0 / S.DUTY + 1e-9, (
            f"a {cost}s sweep waiting {wait}s is "
            f"{cost / (cost + wait):.0%} of the time")
