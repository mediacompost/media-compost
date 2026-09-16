"""A LEVEL cannot hold two groups of a name.

The rule that makes a group PATH name one group: every writer — create, the
editor's rename, a drag that re-parents, a duplicate — goes through
`unique_sibling_name`, so a group arriving at a level that already has its
name takes a number instead of being refused. `Group.name` is still not
unique in the table: two BRANCHES may each hold a "2024", which is the whole
reason paths are worth having.
"""
from __future__ import annotations

from sqlalchemy import select

from media_compost.db import Group, GroupParent
from media_compost.ops import ctx_for, groups as ops_groups


def _name(s, gid: int) -> str:
    return s.get(Group, gid).name


def _parent(s, gid: int):
    return s.execute(select(GroupParent.parent_group_id)
                     .where(GroupParent.group_id == gid)).scalars().first()


def test_creating_a_second_group_of_a_name_numbers_it(lib):
    cfg, db, store = lib
    with db.session() as s:
        ctx = ctx_for(s)
        a = ops_groups.create(ctx, "Trips")
        b = ops_groups.create(ctx, "Trips")
        c = ops_groups.create(ctx, "Trips")
        s.commit()
        assert (_name(s, a.id), _name(s, b.id), _name(s, c.id)) == (
            "Trips", "Trips 2", "Trips 3")


def test_the_same_name_under_two_parents_is_fine(lib):
    """Which is what makes a PATH worth asking for: two branches, one name."""
    cfg, db, store = lib
    with db.session() as s:
        ctx = ctx_for(s)
        trips = ops_groups.create(ctx, "Trips")
        work = ops_groups.create(ctx, "Work")
        a = ops_groups.create(ctx, "2024", parent_id=trips.id)
        b = ops_groups.create(ctx, "2024", parent_id=work.id)
        s.commit()
        assert _name(s, a.id) == "2024" and _name(s, b.id) == "2024"


def test_a_move_onto_a_level_that_has_the_name_renames_the_group_moved(lib):
    """The drop is what the user just did — refusing it halfway through a
    gesture is worse than arriving as "2024 2", and the group that takes the
    number is the one being moved rather than the one already there."""
    cfg, db, store = lib
    with db.session() as s:
        ctx = ctx_for(s)
        trips = ops_groups.create(ctx, "Trips")
        work = ops_groups.create(ctx, "Work")
        settled = ops_groups.create(ctx, "2024", parent_id=trips.id)
        moving = ops_groups.create(ctx, "2024", parent_id=work.id)
        ops_groups.move(ctx, moving.id, trips.id)
        s.commit()
        assert _name(s, settled.id) == "2024"
        assert _name(s, moving.id) == "2024 2"
        assert _parent(s, moving.id) == trips.id


def test_a_rename_onto_a_sibling_s_name_is_numbered_too(lib):
    cfg, db, store = lib
    with db.session() as s:
        ctx = ctx_for(s)
        ops_groups.create(ctx, "Trips")
        other = ops_groups.create(ctx, "Work")
        ops_groups.update(ctx, other.id, name="Trips")
        s.commit()
        assert _name(s, other.id) == "Trips 2"
        # Renaming a group to what it is already called leaves it alone —
        # it must not number itself.
        ops_groups.update(ctx, other.id, name="Trips 2")
        s.commit()
        assert _name(s, other.id) == "Trips 2"


def test_a_duplicate_lands_beside_the_original_with_its_own_name(lib):
    """Only the clone's ROOT can collide: every cloned child is the only one
    of its name under a brand-new parent, so the subtree keeps its names."""
    cfg, db, store = lib
    with db.session() as s:
        ctx = ctx_for(s)
        trips = ops_groups.create(ctx, "Trips")
        inner = ops_groups.create(ctx, "2024", parent_id=trips.id)
        copy_id = ops_groups.duplicate(ctx, trips.id, None)
        s.commit()
        assert _name(s, copy_id) == "Trips 2"
        kids = s.execute(select(GroupParent.group_id)
                         .where(GroupParent.parent_group_id == copy_id)
                         ).scalars().all()
        assert [_name(s, k) for k in kids] == ["2024"]
        assert _name(s, inner.id) == "2024"
