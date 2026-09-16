"""Reverting a file split puts the files back the way they were.

The rows were never the whole of it. A file's NUMBER names it on disk
(``files/<number>.<ext>``), the split renumbers the files it moves from #1 and
carries their bytes into the new item's folder, and a revert that only
reassigned ``item_id`` left each file claiming a number the old item might
already be using, with its bytes still in a folder about to be deleted.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from media_compost import history
from media_compost.db import Event, File, FileArtifact, Item
from media_compost.importer import ImportOptions, Importer
from media_compost.ops import files as ops_files
from media_compost.ops.context import Ctx
from media_compost.testing import make_image


@pytest.fixture
def three_files(lib, tmp_path: Path):
    """One item with four source files, from four pictures merged together."""
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    for i, seed in enumerate([1, 7, 23, 42], start=1):
        make_image(src / f"p{i}.png", seed=seed, size=(400 + 20 * i, 300 + 15 * i))
    with db.session() as s:
        Importer(s, store, cfg).import_paths([src], ImportOptions())
        s.commit()
    from media_compost.ops import items as ops_items

    with db.session() as s:
        ctx = Ctx(session=s, source="cli", _store=store, _config=cfg)
        ids = [i.id for i in s.execute(select(Item)).scalars().all()]
        for other in ids[1:]:
            ops_items.merge(ctx, other, ids[0])
        s.commit()
    return cfg, db, store, ids[0]


def _snapshot(s, item_id: int):
    """(number, path, edit_chain, derived_from) per file, and what is on disk."""
    return {
        f.id: (f.number, f.path, f.edit_chain, f.derived_from_file_id)
        for f in s.execute(
            select(File).where(File.item_id == item_id)
        ).scalars().all()
    }


def _revert_last_split(db, store):
    with db.session() as s:
        ev = s.execute(
            select(Event).where(Event.action == "split_item")
            .order_by(Event.id.desc())
        ).scalars().first()
        assert ev is not None
        out = history.revert_event(s, ev, source="cli", store=store)
        s.commit()
        return out


def test_a_reverted_split_puts_the_numbers_and_the_bytes_back(three_files):
    cfg, db, store, item_id = three_files
    with db.session() as s:
        before = _snapshot(s, item_id)
        item_uid = s.get(Item, item_id).uid
    assert len(before) == 4
    picked = sorted(before)[1:3]

    with db.session() as s:
        ctx = Ctx(session=s, source="cli", _store=store, _config=cfg)
        new_id = ops_files.split_files(ctx, picked)
        s.commit()
    with db.session() as s:
        # The split really did renumber and move them.
        moved = _snapshot(s, new_id)
        assert sorted(n for n, *_ in moved.values()) == [1, 2]
        new_uid = s.get(Item, new_id).uid
    for fid in picked:
        assert not store.file_path(item_uid, before[fid][1]).exists()

    assert _revert_last_split(db, store) is not None

    with db.session() as s:
        after = _snapshot(s, item_id)
        assert s.get(Item, new_id) is None
    assert after == before, "every file is back exactly as it was"
    for fid, (_num, path, _chain, _from) in before.items():
        assert store.file_path(item_uid, path).exists()
    # And nothing of theirs is left in the folder the split-off item had.
    for fid in picked:
        assert not store.file_path(new_uid, moved[fid][1]).exists()


def test_a_reverted_split_restores_the_lineage_and_the_artifacts(three_files):
    cfg, db, store, item_id = three_files
    with db.session() as s:
        ids = sorted(_snapshot(s, item_id))
        # Make one file an edit of another, with a control image hanging off it.
        child, parent = s.get(File, ids[2]), s.get(File, ids[0])
        child.is_derived = True
        child.derived_from_file_id = parent.id
        child.edit_chain = (
            f'[{{"from": {parent.number}, "to": {child.number}, "action": "edit"}}]'
        )
        art_rel = store.write_artifact(
            s.get(Item, item_id).uid, child.number, "depth", "png", b"x" * 8, "m"
        )
        s.add(FileArtifact(item_id=item_id, file_id=child.id, kind="depth",
                           model="m", path=art_rel, width=4, height=4,
                           sha256="a" * 8, bytes=8, format="png"))
        s.commit()
        before = _snapshot(s, item_id)
        item_uid = s.get(Item, item_id).uid
        child_id, parent_id = child.id, parent.id

    # Split the child WITHOUT its parent: the lineage is cleared on the way out.
    with db.session() as s:
        ctx = Ctx(session=s, source="cli", _store=store, _config=cfg)
        new_id = ops_files.split_files(ctx, [child_id])
        s.commit()
    with db.session() as s:
        f = s.get(File, child_id)
        assert f.edit_chain == "" and f.derived_from_file_id is None

    assert _revert_last_split(db, store) is not None

    with db.session() as s:
        assert _snapshot(s, item_id) == before
        f = s.get(File, child_id)
        assert f.derived_from_file_id == parent_id
        assert '"action": "edit"' in f.edit_chain
        art = s.execute(select(FileArtifact).where(
            FileArtifact.file_id == child_id)).scalars().one()
        assert art.item_id == item_id
        assert art.path == art_rel
        assert store.file_path(item_uid, art.path).read_bytes() == b"x" * 8


def test_a_recorded_number_the_item_has_reissued_falls_back_to_a_fresh_one(
        three_files):
    """`next_file_number` continues past the maximum, so a number the split
    freed can be handed out again once the survivors' maximum drops below it.
    The revert must notice rather than write a duplicate."""
    cfg, db, store, item_id = three_files
    with db.session() as s:
        ids = sorted(_snapshot(s, item_id))
    # Split #2, #3 and #4 out, leaving only #1 behind.
    with db.session() as s:
        ctx = Ctx(session=s, source="cli", _store=store, _config=cfg)
        ops_files.split_files(ctx, ids[1:])
        s.commit()
    # A new file on the original now takes #2 — the number #2 used to have.
    with db.session() as s:
        from media_compost.db import next_file_number

        n = next_file_number(s, item_id)
        assert n == 2
        s.add(File(item_id=item_id, path="files/2.png", format="png",
                   width=4, height=4, bytes=8, sha256="z" * 8, number=n))
        s.commit()

    assert _revert_last_split(db, store) is not None

    with db.session() as s:
        numbers = [f.number for f in s.execute(
            select(File).where(File.item_id == item_id)).scalars().all()]
    assert len(numbers) == 5
    assert len(set(numbers)) == 5, f"numbers collided: {sorted(numbers)}"


def test_a_split_revert_without_a_store_is_refused(three_files):
    """It moves BYTES, so a caller that hands over no store is told no rather
    than left with the rows moved and the files in the wrong folder."""
    cfg, db, store, item_id = three_files
    with db.session() as s:
        ids = sorted(_snapshot(s, item_id))
    with db.session() as s:
        ctx = Ctx(session=s, source="cli", _store=store, _config=cfg)
        ops_files.split_files(ctx, ids[:2])
        s.commit()
    with db.session() as s:
        ev = s.execute(
            select(Event).where(Event.action == "split_item")
            .order_by(Event.id.desc())).scalars().first()
        assert history.revert_event(s, ev, source="cli") is None
        assert ev.reverted_at is None
