"""Splitting an edited file out of an item re-links it as a derived version."""

from __future__ import annotations

from sqlalchemy import select

from media_compost.db import File, Item, Relationship
from media_compost.ops import ctx_for, files as ops_files


def _ctx(s, store):
    return ctx_for(s, _store=store)


def test_split_edited_file_creates_edit_relationship(lib):
    cfg, db, store = lib
    with db.session() as s:
        item = Item(name="orig")
        s.add(item)
        s.flush()
        base = File(item_id=item.id, sha256="a" * 64, width=100, height=100,
                    bytes=10, format="png", source_kind="stored", path="x")
        edited = File(item_id=item.id, sha256="b" * 64, width=100, height=100,
                      bytes=10, format="png", source_kind="stored", path="y",
                      is_derived=True)
        s.add_all([base, edited])
        s.flush()
        item.active_file_id = base.id
        s.flush()

        new_id = ops_files.split(_ctx(s, store), edited.id)
        s.flush()

        rel = s.execute(select(Relationship).where(
            Relationship.kind == "edit"
        )).scalars().one()
        assert rel.from_item_id == item.id
        assert rel.to_item_id == new_id


def test_split_non_derived_file_links_back_to_original(lib):
    cfg, db, store = lib
    with db.session() as s:
        item = Item(name="orig")
        s.add(item)
        s.flush()
        f1 = File(item_id=item.id, sha256="c" * 64, width=100, height=100,
                  bytes=10, format="png", source_kind="stored", path="p")
        f2 = File(item_id=item.id, sha256="d" * 64, width=100, height=100,
                  bytes=10, format="png", source_kind="stored", path="q")
        s.add_all([f1, f2])
        s.flush()
        item.active_file_id = f1.id
        s.flush()

        new_id = ops_files.split(_ctx(s, store), f2.id)
        s.flush()
        # A plain (non-edited) split still links the new item back to its origin.
        rel = s.execute(select(Relationship)).scalars().one()
        assert rel.kind == "manual"
        assert rel.from_item_id == item.id
        assert rel.to_item_id == new_id
