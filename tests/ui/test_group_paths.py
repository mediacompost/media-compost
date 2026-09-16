"""Naming ONE of several same-named groups, by path.

`Group.name` is unique per LEVEL and not across the tree, so two branches may
each hold a "2024" and `GROUP:2024` means both. A path picks one:
`GROUP:Trips/2024`. The rule lives once (`grouppath`) and is read by the
compiled clause, by the evaluator's per-item sets, and by the query builder's
dropdown — this drives the first two through the real search endpoint.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from media_compost.testing import make_image
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import get_library
from media_compost.ui.config import UiConfig
from media_compost.ui.server.deps import Library


@pytest.fixture()
def client(tmp_path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    app.dependency_overrides[get_library] = lambda: lib
    with TestClient(app) as c:
        c.lib = lib
        c.cfg = cfg
        yield c
    app.dependency_overrides.clear()


def _group(c, name, parent=None):
    r = c.post("/api/groups", json={"name": name, "parent_id": parent})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _item(c, tmp_path, name, gid):
    src = tmp_path / f"{name}.png"
    # A DISTINCT seed per item: two identical pictures fold into one on
    # import, which is the dedup working and would leave this with one item.
    make_image(src, ord(name[0]), (32, 32))
    with c.lib.db.session() as s:
        from media_compost.importer import Importer, ImportOptions
        Importer(s, c.lib.store, c.cfg).import_paths([src], ImportOptions())
        s.commit()
    iid = [it["id"] for it in c.get("/api/items").json()["items"]
           if it["name"].startswith(name)][0]
    assert c.post("/api/groups/bulk-membership", json={
        "item_ids": [iid], "add": [gid], "remove": []}).status_code == 200
    return iid


def _found(c, value, mode="has"):
    r = c.post("/api/items/query", json={
        "query": {"type": "group", "op": "and", "children": [
            {"type": "ingroup", "name": value, "mode": mode}]},
        "page": 1, "page_size": 50})
    assert r.status_code == 200, r.text
    return {it["id"] for it in r.json()["items"]}


def test_a_path_says_which_of_two_same_named_groups(client, tmp_path):
    c = client
    trips = _group(c, "Trips")
    work = _group(c, "Work")
    t24 = _group(c, "2024", trips)
    w24 = _group(c, "2024", work)
    a = _item(c, tmp_path, "a", t24)
    b = _item(c, tmp_path, "b", w24)

    # The bare NAME is the ROOT-level group of that name (owner 2026-09) —
    # there is none here, so it finds nothing rather than both.
    assert _found(c, "2024") == set()
    # The path is the address: the full one from the root.
    assert _found(c, "Trips/2024") == {a}
    assert _found(c, "Work/2024") == {b}
    # Case and stray whitespace are ignored, like every other name match.
    assert _found(c, " trips / 2024 ") == {a}
    # A path nothing carries finds nothing rather than falling back to a name.
    assert _found(c, "Holidays/2024") == set()
    # ... and the negation is its exact complement.
    assert b in _found(c, "Trips/2024", mode="hasnot")
    assert a not in _found(c, "Trips/2024", mode="hasnot")


def test_GROUP_is_the_subtree_and_GROUPONLY_the_group_itself(client,
                                                            tmp_path):
    """`GROUP:c` finds what selecting `c` in the sidebar shows — the group
    and every group under it (owner 2026-09: it had missed `c/d`'s
    pictures); `GROUPONLY:c` is what is filed in `c` itself."""
    c = client
    top = _group(c, "c")
    sub = _group(c, "d", top)
    deep = _group(c, "e", sub)
    a = _item(c, tmp_path, "a", top)
    b = _item(c, tmp_path, "b", sub)
    e = _item(c, tmp_path, "e", deep)
    n = _item(c, tmp_path, "n", _group(c, "elsewhere"))

    assert _found(c, "c") == {a, b, e}
    assert _found(c, "c/d") == {b, e}
    assert _found(c, "c", mode="hasnot") == {n}
    assert _found(c, "c", mode="only") == {a}
    assert _found(c, "c/d", mode="only") == {b}
    assert _found(c, "c", mode="notonly") == {b, e, n}
    # The same answer as the sidebar's own scope.
    r = c.get(f"/api/items?groups={top}")
    assert {it["id"] for it in r.json()["items"]} == {a, b, e}


def test_a_group_whose_name_holds_a_slash_still_matches_by_name(client,
                                                                tmp_path):
    """There is no escape syntax, deliberately — so the WHOLE value is tried
    as a name as well, and a group really called "a/b" goes on matching."""
    c = client
    odd = _group(c, "a/b")
    x = _item(c, tmp_path, "x", odd)
    assert _found(c, "a/b") == {x}
