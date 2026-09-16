"""Deleting a tag-assigning group can bake its tags onto the items first."""

from __future__ import annotations

import json

from sqlalchemy import select

from media_compost.config import Config
from media_compost.db import (
    Database,
    Group,
    GroupParent,
    GroupTag,
    Item,
    ItemGroup,
    ItemTag,
    Tag,
)
from media_compost.resolve import effective_for_item
from media_compost.ops import ctx_for, groups as ops_groups


def _setup(s):
    dog = Tag(name="dog")
    s.add(dog)
    parent = Group(name="Parent")
    child = Group(name="Child")
    s.add_all([parent, child])
    s.flush()
    s.add(GroupParent(group_id=child.id, parent_group_id=parent.id))
    # Parent assigns 'dog'; item lives in the child (so it inherits 'dog').
    s.add(GroupTag(group_id=parent.id, tag_id=dog.id))
    item = Item(name="x")
    s.add(item)
    s.flush()
    s.add(ItemGroup(item_id=item.id, group_id=child.id))
    s.commit()
    return dog, parent, child, item


def test_delete_without_baking_loses_tag(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        _dog, parent, _child, item = _setup(s)
        assert "dog" in effective_for_item(s, item.id).positive
        ops_groups.delete_group(ctx_for(s), parent.id, assign_tags=False)
        s.commit()
        # No direct assignment was made, and the group is gone.
        assert s.execute(
            ItemTag.__table__.select().where(ItemTag.item_id == item.id)
        ).first() is None
        assert "dog" not in effective_for_item(s, item.id).positive


def test_delete_with_baking_keeps_tag(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        dog, parent, _child, item = _setup(s)
        ops_groups.delete_group(ctx_for(s), parent.id, assign_tags=True)
        s.commit()
        # The item now carries 'dog' as a direct assignment.
        row = s.execute(
            ItemTag.__table__.select().where(ItemTag.item_id == item.id)
        ).first()
        assert row is not None
        assert "dog" in effective_for_item(s, item.id).positive


def test_a_deletion_too_big_to_undo_says_so_rather_than_half_undoing(tmp_path):
    """Past `UNDO_MEMBERS_MAX` the event carries no snapshot, and
    `history.can_revert` declines it.

    The whole subtree goes into the event so a revert can put it back, and the
    history LIST sends every event's data to the browser — so one deletion of
    a group holding a million items would be an eight-megabyte row inside a
    five-hundred-event page. Offering an undo that brought the groups back
    EMPTY would be worse than not offering one, so the refusal is explicit and
    the count it could not keep is recorded.
    """
    from media_compost import history
    from media_compost.db import Event
    from media_compost.ops import groups as ops_groups

    cfg = Config(data_dir=tmp_path / "data")
    cfg.ensure_dirs()
    db = Database(cfg)
    try:
        with db.session() as s:
            g = Group(name="Huge")
            s.add(g)
            s.flush()
            items = [Item(uid=f"u{i}", name=f"i{i}", kind="image")
                     for i in range(5)]
            s.add_all(items)
            s.flush()
            s.add_all([ItemGroup(item_id=it.id, group_id=g.id)
                       for it in items])
            s.commit()
            gid = g.id

            # The cap, not the library: a real one is 20k and seeding that
            # would be a test about insert speed.
            before = ops_groups.UNDO_MEMBERS_MAX
            ops_groups.UNDO_MEMBERS_MAX = 3
            try:
                ops_groups.delete_group(ctx_for(s), gid)
            finally:
                ops_groups.UNDO_MEMBERS_MAX = before
            s.commit()

            ev = s.execute(select(Event).where(
                Event.action == "delete_group")).scalars().one()
            data = json.loads(ev.data or "{}")
            assert "undo" not in data, "it kept a snapshot it said it would not"
            assert data["members_dropped"] == 5, "…and did not say how many"
            assert not history.can_revert(s, ev), (
                "an undo that brings the groups back empty is worse than none")
    finally:
        db.engine.dispose()


# ---- deleting the shelf, or taking it out from over its contents -----------


def _tree(s):
    """`Top > Mid > (A, B)` with an item in A, so a promotion has something
    to be wrong about at every level."""
    top = Group(name="Top")
    mid = Group(name="Mid")
    a = Group(name="A")
    b = Group(name="B")
    s.add_all([top, mid, a, b])
    s.flush()
    s.add_all([GroupParent(group_id=mid.id, parent_group_id=top.id),
               GroupParent(group_id=a.id, parent_group_id=mid.id),
               GroupParent(group_id=b.id, parent_group_id=mid.id)])
    item = Item(name="x")
    s.add(item)
    s.flush()
    s.add(ItemGroup(item_id=item.id, group_id=a.id))
    s.commit()
    return top, mid, a, b, item


def _parent_of(s, gid):
    return s.execute(select(GroupParent.parent_group_id)
                     .where(GroupParent.group_id == gid)).scalar()


def test_deleting_a_group_still_takes_its_subtree(lib):
    """The default is unchanged, and this is the half that says so: a
    deletion removes the shelf rather than emptying it onto the floor."""
    _cfg, db, _store = lib
    with db.session() as s:
        _top, mid, a, b, item = _tree(s)
        ops_groups.delete_group(ctx_for(s), mid.id)
        s.commit()
        assert s.get(Group, a.id) is None and s.get(Group, b.id) is None
        # …and the ITEM stays in the library, which is the half that matters.
        assert s.get(Item, item.id) is not None


def test_KEEPING_the_children_moves_them_up_to_its_own_parent(lib):
    """`keep_children` is the reparenting back as a verb of its own — the
    group made only to hold three others, taken out from over them."""
    _cfg, db, _store = lib
    with db.session() as s:
        top, mid, a, b, _item = _tree(s)
        ops_groups.delete_group(ctx_for(s), mid.id, keep_children=True)
        s.commit()
        assert s.get(Group, mid.id) is None
        assert s.get(Group, a.id) is not None and s.get(Group, b.id) is not None
        assert _parent_of(s, a.id) == top.id
        assert _parent_of(s, b.id) == top.id


def test_a_promoted_child_of_a_ROOT_group_becomes_a_root(lib):
    """Up to the deleted group's own parent, and a root's own parent is
    nothing — which must be an absent edge rather than an edge to nothing."""
    _cfg, db, _store = lib
    with db.session() as s:
        _top, mid, a, _b, _item = _tree(s)
        # Make `mid` a root by taking it out from under Top first.
        ops_groups.move(ctx_for(s), mid.id, None)
        s.commit()
        ops_groups.delete_group(ctx_for(s), mid.id, keep_children=True)
        s.commit()
        assert _parent_of(s, a.id) is None
        assert s.get(Group, a.id) is not None


def test_the_revert_puts_the_promoted_children_BACK_under_it(lib):
    """Restoring an empty shelf while its contents stay scattered where the
    deletion left them is not an undo."""
    from media_compost import history
    from media_compost.db import Event

    _cfg, db, _store = lib
    with db.session() as s:
        top, mid, a, b, _item = _tree(s)
        ops_groups.delete_group(ctx_for(s), mid.id, keep_children=True)
        s.commit()
        ev = s.execute(select(Event)
                       .where(Event.action == "delete_group")).scalars().one()
        assert json.loads(ev.data or "{}")["promoted_group_ids"] \
            == sorted([a.id, b.id])
        assert history.can_revert(s, ev)
        history.revert_event(s, ev)
        s.commit()
        assert s.get(Group, mid.id) is not None
        assert _parent_of(s, mid.id) == top.id
        assert _parent_of(s, a.id) == mid.id
        assert _parent_of(s, b.id) == mid.id


def test_a_childless_group_writes_the_event_it_always_wrote(lib):
    """`keep_children` over a leaf is the ordinary deletion, byte for byte —
    the new keys ride only when they say something."""
    from media_compost.db import Event

    _cfg, db, _store = lib
    with db.session() as s:
        _top, _mid, a, _b, _item = _tree(s)
        ops_groups.delete_group(ctx_for(s), a.id, keep_children=True)
        s.commit()
        ev = s.execute(select(Event)
                       .where(Event.action == "delete_group")).scalars().one()
        assert ev.summary == "Deleted group “A”"
        data = json.loads(ev.data or "{}")
        assert "promoted_group_ids" not in data
        assert "deleted_group_ids" not in data


def test_keeping_the_children_still_bakes_only_THIS_group_s_tags(lib):
    """The survivors go on granting their own; only what was inherited from
    the group being removed has to be baked to survive."""
    _cfg, db, _store = lib
    with db.session() as s:
        dog = Tag(name="dog")
        cat = Tag(name="cat")
        s.add_all([dog, cat])
        top, mid, a, _b, item = _tree(s)
        s.add_all([GroupTag(group_id=mid.id, tag_id=dog.id),
                   GroupTag(group_id=a.id, tag_id=cat.id)])
        s.commit()
        assert {"dog", "cat"} <= effective_for_item(s, item.id).positive
        ops_groups.delete_group(ctx_for(s), mid.id, keep_children=True,
                                assign_tags=True)
        s.commit()
        eff = effective_for_item(s, item.id).positive
        assert "dog" in eff, "the tag the deleted group was granting"
        assert "cat" in eff, "and the one its surviving child still grants"
        # `cat` is still GRANTED, not baked: A is alive and goes on saying it.
        direct = {r for (r,) in s.execute(
            select(Tag.name).join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id == item.id))}
        assert direct == {"dog"}, direct
        assert _parent_of(s, a.id) == top.id
