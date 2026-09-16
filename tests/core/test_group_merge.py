"""Merging one group into another — the sidebar's own destructive verb."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from media_compost.db import Group, GroupParent, ItemGroup, Item
from media_compost.ops import ctx_for, groups as ops_groups
from media_compost.ops.errors import Refused


def _mk(s, name, parent=None, smart=None):
    g = Group(name=name, smart_query=smart)
    s.add(g)
    s.flush()
    if parent is not None:
        s.add(GroupParent(group_id=g.id, parent_group_id=parent))
    s.flush()
    return g


def _item(s, uid, *gids):
    it = Item(uid=uid, name=uid, kind="image")
    s.add(it)
    s.flush()
    for g in gids:
        s.add(ItemGroup(item_id=it.id, group_id=g))
    s.flush()
    return it


def test_merge_moves_the_items_and_the_children_then_deletes_the_source(lib):
    cfg, db, store = lib
    with db.session() as s:
        dest = _mk(s, "Keep")
        src = _mk(s, "Fold")
        child = _mk(s, "Inside", parent=src.id)
        a = _item(s, "a", src.id)
        b = _item(s, "b", src.id, dest.id)   # already there: no second row
        moved, emptied = ops_groups.merge(ctx_for(s), dest.id, [src.id])
        s.commit()
        assert (moved, emptied) == (1, 1)
    with db.session() as s:
        names = {g.name for g in s.execute(select(Group)).scalars()}
        assert "Fold" not in names and {"Keep", "Inside"} <= names
        dest_id = s.execute(select(Group.id).where(
            Group.name == "Keep")).scalar_one()
        inside = s.execute(select(Group.id).where(
            Group.name == "Inside")).scalar_one()
        # The child moved under the destination rather than going with the
        # group it was in.
        assert s.execute(select(GroupParent.parent_group_id).where(
            GroupParent.group_id == inside)).scalar_one() == dest_id
        members = set(s.execute(select(ItemGroup.item_id).where(
            ItemGroup.group_id == dest_id)).scalars().all())
        assert len(members) == 2
        # And nothing is a member twice.
        rows = s.execute(select(ItemGroup.item_id).where(
            ItemGroup.group_id == dest_id)).scalars().all()
        assert len(rows) == len(set(rows))


def test_merge_keeps_the_DESTINATIONS_own_identity(lib):
    """The surviving group's name, icon and colour are its own — merging must
    not quietly change what it says about the items already in it."""
    cfg, db, store = lib
    with db.session() as s:
        dest = _mk(s, "Keep")
        dest.icon, dest.color = "star", "#123456"
        src = _mk(s, "Fold")
        src.icon, src.color = "movie", "#abcdef"
        s.flush()
        ops_groups.merge(ctx_for(s), dest.id, [src.id])
        s.commit()
    with db.session() as s:
        g = s.execute(select(Group).where(Group.name == "Keep")).scalar_one()
        assert (g.icon, g.color) == ("star", "#123456")


def test_every_step_of_a_merge_is_a_logged_event(lib):
    """Built out of the logged primitives, so the whole thing reverts through
    History with no action string of its own."""
    from media_compost.db import Event

    cfg, db, store = lib
    with db.session() as s:
        dest = _mk(s, "Keep")
        src = _mk(s, "Fold")
        _item(s, "a", src.id)
        ops_groups.merge(ctx_for(s), dest.id, [src.id])
        s.commit()
    with db.session() as s:
        got = [e.action for e in s.execute(select(Event)).scalars()]
        assert "add_to_group" in got and "delete_group" in got


def test_a_group_cannot_be_merged_into_its_own_descendant(lib):
    cfg, db, store = lib
    with db.session() as s:
        outer = _mk(s, "Outer")
        inner = _mk(s, "Inner", parent=outer.id)
        with pytest.raises(Refused):
            ops_groups.merge(ctx_for(s), inner.id, [outer.id])


def test_a_smart_group_is_refused_at_either_end(lib):
    """Its membership is DERIVED: merging into one is manual membership,
    which it refuses, and merging one away would copy a rule's answer into a
    hand-made list — a different claim, made silently."""
    cfg, db, store = lib
    with db.session() as s:
        plain = _mk(s, "Plain")
        smart = _mk(s, "Smart", smart="portrait")
        with pytest.raises(Refused):
            ops_groups.merge(ctx_for(s), smart.id, [plain.id])
        with pytest.raises(Refused):
            ops_groups.merge(ctx_for(s), plain.id, [smart.id])


def test_merging_a_group_into_itself_is_refused(lib):
    cfg, db, store = lib
    with db.session() as s:
        g = _mk(s, "One")
        with pytest.raises(Refused):
            ops_groups.merge(ctx_for(s), g.id, [g.id])
