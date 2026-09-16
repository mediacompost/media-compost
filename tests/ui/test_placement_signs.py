"""A tag INSTANCE carries its own sign (`ItemTagPlacement.negative`).

The same tag may be positive in one of an item's tag groups and negative in
another; the ASSIGNMENT — what search, facets, counts and training read —
stays `ItemTag.negative`, derived by `sync_placement_sign`: negative only
when EVERY instance is, so any positive placement wins (the user's rule for
mixed signs). The flip is per row (`set_placement_sign`), logged and
revertible, and the sidecar carries the sign per instance entry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost.db import ItemTag, Tag
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
    make_image(src / "p0.png", seed=0, size=(220, 160))
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


def _item(client) -> int:
    return client.get("/api/items").json()["items"][0]["id"]


def _insts(client, item: int, name: str) -> list[dict]:
    detail = client.get(f"/api/items/{item}").json()
    return [i for i in detail["tag_instances"] if i["name"] == name]


def _assignment_negative(client, item: int, name: str) -> bool:
    with client.lib.db.session() as s:
        tag = s.execute(select(Tag).where(Tag.name == name)).scalars().one()
        it = s.execute(select(ItemTag).where(
            ItemTag.item_id == item, ItemTag.tag_id == tag.id
        )).scalars().one()
        return bool(it.negative)


def _two_groups(client, item: int) -> tuple[int, int]:
    gA = client.post(f"/api/tags/item/{item}/groups",
                     json={"name": "A"}).json()["id"]
    gB = client.post(f"/api/tags/item/{item}/groups",
                     json={"name": "B"}).json()["id"]
    return gA, gB


def test_mixed_signs_across_groups_and_any_positive_wins(client):
    item = _item(client)
    gA, gB = _two_groups(client, item)
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gA, "negative": False})
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gB, "negative": True})
    insts = {i["group_id"]: i["negative"] for i in _insts(client, item, "shirt")}
    assert insts == {gA: False, gB: True}
    # ANY positive instance makes the assignment positive — search finds it.
    assert _assignment_negative(client, item, "shirt") is False

    # Flip the positive one: every instance negative → the assignment too.
    pid = next(i["placement_id"] for i in _insts(client, item, "shirt")
               if i["group_id"] == gA)
    r = client.post(f"/api/tags/placement/{pid}/sign",
                    json={"negative": True})
    assert r.status_code == 200, r.text
    assert _assignment_negative(client, item, "shirt") is True

    # And back: one positive instance is enough.
    client.post(f"/api/tags/placement/{pid}/sign", json={"negative": False})
    assert _assignment_negative(client, item, "shirt") is False


def test_the_flip_is_logged_and_reverts_with_the_derived_sign(client):
    item = _item(client)
    gA, gB = _two_groups(client, item)
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gA, "negative": False})
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gB, "negative": True})
    pid = next(i["placement_id"] for i in _insts(client, item, "shirt")
               if i["group_id"] == gA)
    client.post(f"/api/tags/placement/{pid}/sign", json={"negative": True})
    assert _assignment_negative(client, item, "shirt") is True
    ev = client.get("/api/history").json()["events"][0]
    assert ev["action"] == "set_placement_sign", ev
    r = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.status_code == 200, r.text
    insts = {i["group_id"]: i["negative"] for i in _insts(client, item, "shirt")}
    assert insts[gA] is False
    assert _assignment_negative(client, item, "shirt") is False


def test_a_name_level_statement_covers_every_instance(client):
    """`assign_item_tag` (quick assign's write) says something about the
    NAME, so it sets every instance — or the derived sign would flip it
    straight back."""
    item = _item(client)
    gA, gB = _two_groups(client, item)
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gA, "negative": False})
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gB, "negative": False})
    client.post(f"/api/tags/assign/item/{item}",
                json={"tag": "shirt", "negative": True})
    assert all(i["negative"] for i in _insts(client, item, "shirt"))
    assert _assignment_negative(client, item, "shirt") is True


def test_removing_the_negative_instance_rederives(client):
    item = _item(client)
    gA, gB = _two_groups(client, item)
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gA, "negative": True})
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gB, "negative": True})
    assert _assignment_negative(client, item, "shirt") is True
    pid = next(i["placement_id"] for i in _insts(client, item, "shirt")
               if i["group_id"] == gA)
    client.post(f"/api/tags/placement/{pid}/sign", json={"negative": False})
    assert _assignment_negative(client, item, "shirt") is False
    # Deleting the one positive instance leaves only negatives.
    client.request("DELETE", f"/api/tags/placements/{pid}")
    assert _assignment_negative(client, item, "shirt") is True


def test_dragging_a_negative_tag_to_a_new_group_keeps_it_negative(client):
    """The reported bug: a negative tag dragged from Ungrouped into a fresh
    group came out POSITIVE. The drag materializes the implicit ungrouped
    instance (`move_instance` → `ensure_placement`), and the created
    placement's sign defaulted to False instead of inheriting the
    assignment's — materializing an instance must keep what it meant."""
    item = _item(client)
    client.post(f"/api/tags/assign/item/{item}",
                json={"tag": "shirt", "negative": True})
    assert _assignment_negative(client, item, "shirt") is True
    g = client.post(f"/api/tags/item/{item}/groups",
                    json={"name": "New group"}).json()["id"]
    r = client.post(f"/api/tags/item/{item}/move-instance", json={
        "name": "shirt", "from_group_id": None, "to_group_id": g})
    assert r.status_code == 200, r.text
    (inst,) = _insts(client, item, "shirt")
    assert inst["group_id"] == g
    assert inst["negative"] is True
    assert _assignment_negative(client, item, "shirt") is True


def test_a_move_that_folds_two_instances_rederives_the_sign(client):
    """Moving −shirt onto the group already holding +shirt folds the two
    into the target's instance, so only the positive one survives — and the
    assignment re-derives from what is left."""
    item = _item(client)
    gA, gB = _two_groups(client, item)
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gA, "negative": True})
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gB, "negative": False})
    # Any positive wins while both exist.
    assert _assignment_negative(client, item, "shirt") is False
    # Flip B negative too: all negative.
    pid = next(i["placement_id"] for i in _insts(client, item, "shirt")
               if i["group_id"] == gB)
    client.post(f"/api/tags/placement/{pid}/sign", json={"negative": True})
    assert _assignment_negative(client, item, "shirt") is True
    # Make A positive again, then fold A into B: B's own (negative) instance
    # survives the merge, so the assignment goes back to negative.
    pidA = next(i["placement_id"] for i in _insts(client, item, "shirt")
                if i["group_id"] == gA)
    client.post(f"/api/tags/placement/{pidA}/sign", json={"negative": False})
    assert _assignment_negative(client, item, "shirt") is False
    client.post(f"/api/tags/item/{item}/move-instance", json={
        "name": "shirt", "from_group_id": gA, "to_group_id": gB})
    (inst,) = _insts(client, item, "shirt")
    assert inst["group_id"] == gB and inst["negative"] is True
    assert _assignment_negative(client, item, "shirt") is True


def test_the_signs_ride_the_sidecar_per_instance(client, tmp_path):
    from media_compost import open_library

    item = _item(client)
    gA, gB = _two_groups(client, item)
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gA, "negative": False})
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "shirt", "group_id": gB, "negative": True})

    with open_library(tmp_path / "restored", source="cli") as fresh:
        stats = fresh.merge_library(tmp_path / "data")
        assert not stats.errors, stats.errors
    cfg2 = UiConfig(data_dir=tmp_path / "restored")
    lib2 = Library(cfg2)
    app.dependency_overrides[get_library] = lambda: lib2
    deps.reset_library()
    with TestClient(app) as c2:
        it2 = c2.get("/api/items").json()["items"][0]["id"]
        insts = {(i["group_id"] is not None, i["negative"])
                 for i in c2.get(f"/api/items/{it2}").json()["tag_instances"]
                 if i["name"] == "shirt"}
        signs = sorted(neg for _grouped, neg in insts)
        assert signs == [False, True]
        # The derived assignment: any positive wins.
        with lib2.db.session() as s:
            tag = s.execute(select(Tag).where(
                Tag.name == "shirt")).scalars().one()
            it = s.execute(select(ItemTag).where(
                ItemTag.item_id == it2, ItemTag.tag_id == tag.id
            )).scalars().one()
            assert bool(it.negative) is False
