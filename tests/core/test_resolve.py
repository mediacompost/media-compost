"""Effective-tag resolution over the group DAG."""

from __future__ import annotations

from media_compost.db import (
    Group,
    GroupParent,
    GroupTag,
    Item,
    ItemGroup,
    ItemTag,
    Tag,
    TagImplication,
)
from media_compost.resolve import effective_for_item


def _setup(s):
    tags = {n: Tag(name=n) for n in ["portrait", "person", "indoor", "blurred"]}
    s.add_all(tags.values())
    parent = Group(name="Portraits")
    child = Group(name="Studio")
    s.add_all([parent, child])
    s.flush()
    s.add(GroupParent(group_id=child.id, parent_group_id=parent.id))
    item = Item(name="x.jpg")
    s.add(item)
    s.flush()
    s.add(ItemGroup(item_id=item.id, group_id=child.id))
    s.flush()
    return tags, parent, child, item


def test_inherited_from_ancestor(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        tags, parent, child, item = _setup(s)
        # Parent assigns 'portrait' (+) and 'person' (+); inherited by item.
        s.add(GroupTag(group_id=parent.id, tag_id=tags["portrait"].id))
        s.add(GroupTag(group_id=parent.id, tag_id=tags["person"].id))
        s.commit()
        eff = effective_for_item(s, item.id)
        assert eff.positive == {"portrait", "person"}
        assert parent.id in eff.indirect_by_group


def test_negative_removes_inherited(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        tags, parent, child, item = _setup(s)
        s.add(GroupTag(group_id=parent.id, tag_id=tags["portrait"].id))
        # Item directly negates the inherited 'portrait'.
        s.add(ItemTag(item_id=item.id, tag_id=tags["portrait"].id, negative=True))
        s.commit()
        eff = effective_for_item(s, item.id)
        assert "portrait" not in eff.positive
        assert "portrait" in eff.negative


def test_direct_positive_adds(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        tags, parent, child, item = _setup(s)
        s.add(ItemTag(item_id=item.id, tag_id=tags["indoor"].id))
        s.commit()
        eff = effective_for_item(s, item.id)
        assert "indoor" in eff.positive
        assert "indoor" in eff.direct_positive


def test_an_implied_tag_is_entailed(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        tags, parent, child, item = _setup(s)
        # 'portrait' implies 'person' -> assigning portrait entails person.
        s.add(TagImplication(tag_id=tags["portrait"].id, implies_id=tags["person"].id))
        s.add(ItemTag(item_id=item.id, tag_id=tags["portrait"].id))
        s.commit()
        eff = effective_for_item(s, item.id)
        assert {"portrait", "person"} <= eff.positive
        assert "person" in eff.indirect_by_parent  # displayed as implied
        assert "person" not in eff.direct_positive  # not a direct assignment


def test_an_implication_chain_is_transitive(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        tags, parent, child, item = _setup(s)
        # blurred -> portrait -> person: assigning blurred entails both ancestors.
        s.add(TagImplication(tag_id=tags["blurred"].id, implies_id=tags["portrait"].id))
        s.add(TagImplication(tag_id=tags["portrait"].id, implies_id=tags["person"].id))
        s.add(ItemTag(item_id=item.id, tag_id=tags["blurred"].id))
        s.commit()
        eff = effective_for_item(s, item.id)
        assert {"blurred", "portrait", "person"} <= eff.positive


def test_implication_sources_record_the_reason(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        tags, parent, child, item = _setup(s)
        # blurred -> portrait -> person; assigning blurred entails both ancestors,
        # and both record 'blurred' as the reason.
        s.add(TagImplication(tag_id=tags["blurred"].id, implies_id=tags["portrait"].id))
        s.add(TagImplication(tag_id=tags["portrait"].id, implies_id=tags["person"].id))
        s.add(ItemTag(item_id=item.id, tag_id=tags["blurred"].id))
        s.commit()
        eff = effective_for_item(s, item.id)
        assert eff.parent_sources.get("portrait") == {"blurred"}
        assert eff.parent_sources.get("person") == {"blurred"}


def test_direct_negative_overrides_an_implied_tag(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        tags, parent, child, item = _setup(s)
        s.add(TagImplication(tag_id=tags["portrait"].id, implies_id=tags["person"].id))
        s.add(ItemTag(item_id=item.id, tag_id=tags["portrait"].id))
        # Explicitly negate the implied parent.
        s.add(ItemTag(item_id=item.id, tag_id=tags["person"].id, negative=True))
        s.commit()
        eff = effective_for_item(s, item.id)
        assert "person" not in eff.positive
        assert "person" in eff.negative
        # Still reported as parent-implied so the sidebar can grey it out.
        assert "person" in eff.indirect_by_parent
