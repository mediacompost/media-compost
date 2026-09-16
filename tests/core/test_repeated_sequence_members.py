"""A sequence may hold the same item at several positions.

A book's three blank pages all dedup onto ONE item — the importer being
right — and the sequence is what keeps the book's structure, so that item
has to be allowed to sit at each of the three positions. These tests pin the
whole story: the importer keeps the positions, the ops speak two
tag sets (membership rows address one occurrence, item ids mean every
occurrence), and a folder round trip brings the repeats back.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from media_compost.db import Item, Sequence, SequenceItem
from media_compost.importer import ImportOptions, Importer
from media_compost.ops import sequences as ops_sequences
from media_compost.ops.context import Ctx
from media_compost.ops.errors import Invalid
from media_compost.testing import make_image


def _seed_items(s, n: int) -> list[int]:
    items = [Item(name=f"i{i}") for i in range(n)]
    s.add_all(items)
    s.flush()
    return [it.id for it in items]


def _order(s, seq_id: int) -> list[int]:
    return list(s.execute(
        select(SequenceItem.item_id)
        .where(SequenceItem.sequence_id == seq_id)
        .order_by(SequenceItem.position, SequenceItem.id)
    ).scalars().all())


def test_create_keeps_a_repeated_item_at_each_position(lib):
    cfg, db, store = lib
    with db.session() as s:
        a, b = _seed_items(s, 2)
        seq_id, _container = ops_sequences.create(
            Ctx(session=s), [a, b, a], name="book")
        s.flush()
        assert _order(s, seq_id) == [a, b, a]
        positions = list(s.execute(
            select(SequenceItem.position)
            .where(SequenceItem.sequence_id == seq_id)
            .order_by(SequenceItem.position)
        ).scalars().all())
        assert positions == [0, 1, 2]


def test_reorder_speaks_in_rows_and_refuses_ambiguous_items(lib):
    cfg, db, store = lib
    with db.session() as s:
        a, b = _seed_items(s, 2)
        ctx = Ctx(session=s)
        seq_id, _ = ops_sequences.create(ctx, [a, b, a], name="book")
        s.flush()
        rows = list(s.execute(
            select(SequenceItem).where(SequenceItem.sequence_id == seq_id)
            .order_by(SequenceItem.position)
        ).scalars().all())
        # Move the SECOND copy of `a` to the front — only rows can say that.
        ops_sequences.reorder(ctx, seq_id,
                              member_ids=[rows[2].id, rows[0].id, rows[1].id])
        assert _order(s, seq_id) == [a, a, b]
        # An item-id order cannot say which copy goes where; the old
        # implementation silently left the extra rows at stale positions.
        with pytest.raises(Invalid):
            ops_sequences.reorder(ctx, seq_id, [b, a])


def test_removing_a_row_keeps_the_other_occurrences(lib):
    cfg, db, store = lib
    with db.session() as s:
        a, b = _seed_items(s, 2)
        ctx = Ctx(session=s)
        seq_id, _ = ops_sequences.create(ctx, [a, b, a], name="book")
        s.flush()
        rows = list(s.execute(
            select(SequenceItem).where(SequenceItem.sequence_id == seq_id)
            .order_by(SequenceItem.position)
        ).scalars().all())
        removed = ops_sequences.remove_members(ctx, seq_id,
                                               member_ids=[rows[0].id])
        assert removed == 1
        assert _order(s, seq_id) == [b, a]
        # Renumbered densely, and the item with a copy LEFT keeps its
        # main-sequence pointer.
        positions = list(s.execute(
            select(SequenceItem.position)
            .where(SequenceItem.sequence_id == seq_id)
            .order_by(SequenceItem.position)
        ).scalars().all())
        assert positions == [0, 1]
        assert s.get(Item, a).main_sequence_id == seq_id


def test_removing_by_item_takes_every_occurrence(lib):
    cfg, db, store = lib
    with db.session() as s:
        a, b = _seed_items(s, 2)
        ctx = Ctx(session=s)
        seq_id, _ = ops_sequences.create(ctx, [a, b, a], name="book")
        s.flush()
        removed = ops_sequences.remove_members(ctx, seq_id, [a])
        assert removed == 2
        assert _order(s, seq_id) == [b]
        assert s.get(Item, a).main_sequence_id is None


def test_an_archive_with_identical_pages_keeps_its_length(lib, tmp_path):
    """The user-visible half: the pages dedup onto one item (right), but the
    BOOK keeps all its pages (this was the bug — a 24-page book with two
    blank pages imported as a 22-page sequence)."""
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "a.png", 1)
    make_image(src / "c.png", 2)
    archive = tmp_path / "book.cbz"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(src / "a.png", "page-01.png")   # the "blank" page…
        z.write(src / "c.png", "page-02.png")
        z.write(src / "a.png", "page-03.png")   # …again, byte-identical
    with db.session() as s:
        Importer(s, store, cfg).import_paths([archive], ImportOptions())
        s.commit()
        seq = s.execute(select(Sequence)).scalars().one()
        order = _order(s, seq.id)
        assert len(order) == 3, "three pages, even though two share one item"
        assert order[0] == order[2], "the repeated page is ONE item twice"
        assert order[0] != order[1]

        # …and a RE-import of the same archive recognises its own sequence
        # rather than creating a second (the ordered-list comparison).
        Importer(s, store, cfg).import_paths([archive], ImportOptions())
        s.commit()
        assert len(s.execute(select(Sequence)).scalars().all()) == 1
        assert len(_order(s, seq.id)) == 3


def test_a_folder_round_trip_keeps_the_repeats(lib, tmp_path):
    from media_compost.config import Config
    from media_compost.db import Database
    from media_compost.libimport import merge_library
    from media_compost.storage import ItemStore

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "a.png", 3)
    make_image(src / "b.png", 4)
    with db.session() as s:
        Importer(s, store, cfg).import_paths([src], ImportOptions())
        ids = [it.id for it in s.execute(
            select(Item).order_by(Item.id)).scalars().all()]
        ops_sequences.create(Ctx(session=s), [ids[0], ids[1], ids[0]],
                             name="book")
        s.commit()

    cfg2 = Config(data_dir=tmp_path / "lib2")
    db2 = Database(cfg2)
    store2 = ItemStore(cfg2)
    with db2.session() as s2:
        merge_library(s2, store2, cfg2, cfg.data_dir)
        s2.commit()
        seq = s2.execute(select(Sequence).where(
            Sequence.kind == "manual")).scalars().one()
        order = _order(s2, seq.id)
        assert len(order) == 3, "the restore used to drop the second copy"
        assert order[0] == order[2] != order[1]
