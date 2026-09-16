"""``merge-library``: another library's items folded into this one.

The item-level round trips (boxes, pins, sequences, judgments, smart-group
refits) are covered where each feature lives; what THIS file pins is the
merge's own contract — the tag set travels at full fidelity because it is
read from the source's database, the source is never written to, and a source
this build cannot merge safely is refused by name.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from media_compost.config import Config
from media_compost.db import (
    Database, Group, GroupParent, GroupTag, Item, Location, Occasion,
    OccasionPlace, Ranking, Subject, Tag, TagImplication, TagMetaTag,
)
from media_compost.importer import ImportOptions, Importer
from media_compost.libimport import merge_library
from media_compost.storage import ItemStore
from tests.core.conftest import make_image


def _library(tmp_path: Path, name: str):
    cfg = Config(data_dir=tmp_path / name)
    db = Database(cfg)
    return cfg, db, ItemStore(cfg)


def _rich_source(tmp_path: Path):
    """A source library with one of everything the tag set can say."""
    cfg, db, store = _library(tmp_path, "src")
    img = make_image(tmp_path / "a.png", seed=5, size=(320, 240))
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [img], ImportOptions(folders_as_groups=False))
        # Tags: an implication chain, an alias, a comment, a meta tag with a
        # per-assignment count.
        dog = Tag(name="dog", comment="best friend")
        poodle = Tag(name="poodle")
        doggo = Tag(name="doggo")
        s.add_all([dog, poodle, doggo])
        s.flush()
        doggo.alias_of_id = dog.id
        s.add(TagImplication(tag_id=poodle.id, implies_id=dog.id))
        s.add(TagMetaTag(tag_id=dog.id, name="character", count=7))
        # A subject on its identity tag.
        alice = Tag(name="subject:alice")
        s.add(alice)
        s.flush()
        s.add(Subject(tag_id=alice.id, display_name="Alice",
                      since_date=19900000))
        # A place and an event naming it as a venue.
        ptag, etag = Tag(name="place:tokyo"), Tag(name="event:comiket")
        s.add_all([ptag, etag])
        s.flush()
        loc = Location(tag_id=ptag.id, name="Tokyo", lat=35.6, lon=139.7)
        s.add(loc)
        s.flush()
        occ = Occasion(tag_id=etag.id, display_name="Comiket",
                       start_date=20140815, end_date=20140817)
        s.add(occ)
        s.flush()
        s.add(OccasionPlace(occasion_id=occ.id, location_id=loc.id))
        # A group tree with an icon, a grant, and a smart group.
        parent = Group(name="Animals", icon="pets", color="#123456")
        child = Group(name="Dogs", icon="folder")
        smart = Group(name="Good ones", icon="filter_alt",
                      smart_query="dog")
        s.add_all([parent, child, smart])
        s.flush()
        s.add(GroupParent(group_id=child.id, parent_group_id=parent.id))
        s.add(GroupTag(group_id=child.id, tag_id=dog.id, negative=False))
        # A ranking axis.
        s.add(Ranking(name="Quality",
                      scope="", bucket_lo=0, bucket_hi=9))
        s.commit()
    db.engine.dispose()
    return cfg


def test_the_catalog_merges_at_full_fidelity(tmp_path):
    src_cfg = _rich_source(tmp_path)
    cfg, db, store = _library(tmp_path, "dst")
    with db.session() as s:
        stats = merge_library(s, store, cfg, src_cfg.data_dir)
        assert not stats.errors, stats.errors
        s.commit()

        tags = {t.name: t for t in s.execute(select(Tag)).scalars().all()}
        assert tags["dog"].comment == "best friend"
        assert tags["doggo"].alias_of_id == tags["dog"].id
        imp = s.execute(select(TagImplication)).scalars().all()
        assert [(i.tag_id, i.implies_id) for i in imp] == [
            (tags["poodle"].id, tags["dog"].id)]
        meta = s.execute(select(TagMetaTag)).scalars().one()
        assert (meta.tag_id, meta.name, meta.count) == (
            tags["dog"].id, "character", 7)

        sub = s.execute(select(Subject)).scalars().one()
        assert (sub.tag_id, sub.display_name, sub.since_date) == (
            tags["subject:alice"].id, "Alice", 19900000)
        loc = s.execute(select(Location)).scalars().one()
        assert (loc.tag_id, loc.name) == (tags["place:tokyo"].id, "Tokyo")
        occ = s.execute(select(Occasion)).scalars().one()
        assert (occ.tag_id, occ.start_date) == (
            tags["event:comiket"].id, 20140815)
        venue = s.execute(select(OccasionPlace)).scalars().one()
        assert (venue.occasion_id, venue.location_id) == (occ.id, loc.id)

        groups = {g.name: g for g in s.execute(select(Group)).scalars().all()}
        assert groups["Animals"].icon == "pets"
        assert groups["Animals"].color == "#123456"
        assert groups["Good ones"].smart_query == "dog"
        gp = s.execute(select(GroupParent)).scalars().one()
        assert (gp.group_id, gp.parent_group_id) == (
            groups["Dogs"].id, groups["Animals"].id)
        grant = s.execute(select(GroupTag)).scalars().one()
        assert (grant.group_id, grant.tag_id) == (
            groups["Dogs"].id, tags["dog"].id)

        rk = s.execute(select(Ranking)).scalars().one()
        assert (rk.name, rk.bucket_hi) == ("Quality", 9)
        # A ranking inserted bare (the source's own row has no pool) still
        # arrives with its unnamed pool — every judgment needs one.
        from media_compost.db import RankingPool
        assert [lg.name for lg in s.execute(select(RankingPool).where(
            RankingPool.ranking_id == rk.id)).scalars().all()] == [""]

        # The item and its bytes came across.
        item = s.execute(select(Item)).scalars().one()
        assert (store.item_dir(item.uid) / "files" / "1.png").is_file()
    db.engine.dispose()


def test_existing_definitions_win_and_reruns_are_no_ops(tmp_path):
    src_cfg = _rich_source(tmp_path)
    cfg, db, store = _library(tmp_path, "dst")
    with db.session() as s:
        # The target already knows what "dog" means, differently.
        s.add(Tag(name="dog", comment="MY definition"))
        s.commit()
        merge_library(s, store, cfg, src_cfg.data_dir)
        s.commit()
        dog = s.execute(select(Tag).where(Tag.name == "dog")).scalars().one()
        assert dog.comment == "MY definition", "the current library wins"

        before = s.execute(select(Item.id)).scalars().all()
        stats = merge_library(s, store, cfg, src_cfg.data_dir)
        s.commit()
        assert stats.skipped == stats.scanned, "a re-run skips every uid"
        assert s.execute(select(Item.id)).scalars().all() == before
    db.engine.dispose()


def test_the_source_is_not_written_to(tmp_path):
    """Content-untouched. (The WAL side files — ``-wal``/``-shm`` — do
    appear: ANY reader of a WAL database materializes them, the sqlite3 CLI
    included, and they carry no content here. What must hold is that the
    database's own bytes and the item folders are exactly as found.)"""
    def snapshot(cfg):
        return (cfg.db_path.read_bytes(),
                sorted(p.relative_to(cfg.data_dir).as_posix()
                       for p in cfg.data_dir.rglob("*")
                       if p.is_file()
                       and p.suffix not in (".db-wal", ".db-shm")
                       and not p.name.endswith(("-wal", "-shm"))))

    src_cfg = _rich_source(tmp_path)
    before = snapshot(src_cfg)
    cfg, db, store = _library(tmp_path, "dst")
    with db.session() as s:
        stats = merge_library(s, store, cfg, src_cfg.data_dir)
        assert not stats.errors, stats.errors
        s.commit()
    db.engine.dispose()
    assert snapshot(src_cfg) == before, "merging must not mutate what it reads"


def test_a_behind_source_is_refused_untouched(tmp_path):
    """A source below this build's format is refused with the reason and left
    exactly as found. (While the ladder is empty every older number is below
    the baseline, so the reason is "no upgrade path"; a source the ladder
    could climb is told to upgrade first — the branch after it.)"""
    src_cfg = _rich_source(tmp_path)
    con = sqlite3.connect(src_cfg.db_path)
    con.execute("PRAGMA user_version = 2")
    con.commit()
    con.close()
    stamp = src_cfg.db_path.read_bytes()

    cfg, db, store = _library(tmp_path, "dst")
    with db.session() as s:
        with pytest.raises(ValueError, match="cannot read"):
            merge_library(s, store, cfg, src_cfg.data_dir)
    db.engine.dispose()
    assert src_cfg.db_path.read_bytes() == stamp, "refused means untouched"


def test_a_folder_without_a_database_is_refused_by_name(tmp_path):
    cfg, db, store = _library(tmp_path, "dst")
    plain = tmp_path / "not-a-library"
    plain.mkdir()
    with db.session() as s:
        with pytest.raises(ValueError, match="no media.db"):
            merge_library(s, store, cfg, plain)
    db.engine.dispose()


def test_merging_a_library_into_itself_is_refused(tmp_path):
    cfg, db, store = _library(tmp_path, "dst")
    with db.session() as s:
        with pytest.raises(ValueError, match="IS this library"):
            merge_library(s, store, cfg, cfg.data_dir)
    db.engine.dispose()


def test_dry_run_counts_and_changes_nothing(tmp_path):
    src_cfg = _rich_source(tmp_path)
    cfg, db, store = _library(tmp_path, "dst")
    with db.session() as s:
        stats = merge_library(s, store, cfg, src_cfg.data_dir, dry_run=True)
        assert stats.scanned == 1 and stats.created == 1
        assert s.execute(select(Item.id)).first() is None
        assert s.execute(select(Tag.id)).first() is None
    db.engine.dispose()


def test_a_source_from_the_future_is_refused_by_name(tmp_path):
    """The version check covers BOTH directions: a source written by a newer
    build (user_version past this one's ladder) is refused with the reason,
    not misread — `classify`'s from-the-future refusal surfaces through
    `migrations.inspect` as the `problem` the resolver checks first."""
    src_cfg = _rich_source(tmp_path)
    con = sqlite3.connect(src_cfg.db_path)
    con.execute("PRAGMA user_version = 999")
    con.commit()
    con.close()

    cfg, db, store = _library(tmp_path, "dst")
    with db.session() as s:
        with pytest.raises(ValueError, match="cannot read"):
            merge_library(s, store, cfg, src_cfg.data_dir)
    db.engine.dispose()


def test_a_rerun_builds_no_transfer_dict_for_what_is_already_here(
        tmp_path, monkeypatch):
    """The second run of a merge skips every uid, and decides that in
    bulk BEFORE building any item's dict (`_already_here`): on a 200k
    library the re-run used to cost exactly the first run, 32 statements
    per skipped item."""
    from media_compost import libimport

    scfg, sdb, sstore = _library(tmp_path, "src")
    with sdb.session() as s:
        Importer(s, sstore, scfg).import_paths(
            [make_image(tmp_path / f"p{i}.png", seed=i, size=(80, 60))
             for i in range(3)], ImportOptions(folders_as_groups=False))
        s.commit()
    dcfg, ddb, dstore = _library(tmp_path, "dst")
    with ddb.session() as s:
        first = libimport.merge_library(s, dstore, dcfg, scfg.data_dir)
        s.commit()
    assert first.created == 3
    calls = []
    real = libimport.item_to_dict
    monkeypatch.setattr(libimport, "item_to_dict",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    with ddb.session() as s:
        again = libimport.merge_library(s, dstore, dcfg, scfg.data_dir)
        dry = libimport.merge_library(s, dstore, dcfg, scfg.data_dir,
                                      dry_run=True)
    assert again.skipped == 3 and again.created == 0 and again.merged == 0
    assert dry.skipped == 3 and dry.scanned == 3
    assert calls == []
