"""The thumbnail cache's sharded layout, and prune sweeping both layouts.

Thumbs live in ``thumbs/<xx>/<file_id>-<sha16>.webp`` with ``xx`` the id's low
byte — one flat folder of every thumbnail made each ``drop_thumb`` glob (and
every cache-miss stat) walk the whole library. The shard key is the ID, so a
file's thumbs all live in one subfolder whatever their content hash.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from sqlalchemy import select

from media_compost.config import Config
from media_compost.db import Database, File
from media_compost.importer import ImportOptions, Importer
from media_compost.storage import ItemStore


def test_thumb_path_is_sharded_by_the_id_s_low_byte(tmp_path: Path):
    store = ItemStore(Config(data_dir=tmp_path / "data"))
    sha = "deadbeef" * 8
    p = store.thumb_path(300, sha)
    assert p.parent == store.config.thumbs_dir / "2c"          # 300 % 256
    assert p.name == f"300-{sha[:16]}.webp"
    # Two content hashes of one id share the shard — drop_thumb's contract.
    assert store.thumb_path(300, "ab" * 32).parent == p.parent
    # Different low byte, different shard.
    assert store.thumb_path(301, sha).parent.name == "2d"


def test_ensure_and_drop_thumb_use_the_shard(tmp_path: Path):
    store = ItemStore(Config(data_dir=tmp_path / "data"))
    src = tmp_path / "img.png"
    Image.new("RGB", (64, 48), (200, 10, 10)).save(src, "PNG")

    out = store.ensure_thumb(7, "aa" * 32, src)
    assert out.exists()
    assert out.parent.name == f"{7 % 256:02x}"
    # A second content hash of the same id (an in-place edit) sits beside it.
    store.ensure_thumb(7, "bb" * 32, src)
    assert len(list(out.parent.glob("7-*.webp"))) == 2

    store.drop_thumb(7)
    assert list(out.parent.glob("7-*.webp")) == []
    # Dropping an id with no shard folder yet is a quiet no-op.
    store.drop_thumb(123456)


def test_prune_keeps_live_thumbs_and_sweeps_stale_and_flat(lib, images):
    cfg, db, store = lib
    with db.session() as s:
        Importer(s, store, cfg).import_paths([images], ImportOptions())
        s.commit()
        rows = s.execute(select(File)).scalars().all()
        assert rows
        live = store.ensure_thumb(rows[0].id, rows[0].sha256,
                                  store.path_of(s, rows[0]))
        assert live.exists()

        # A stale sharded thumb (no such file id), and two old-flat-layout
        # files directly under thumbs/ — one with a live-looking name, which
        # still goes: nothing looks the flat layout up any more.
        stale = cfg.thumbs_dir / "aa" / "999999-cafecafecafecafe.webp"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_bytes(b"x")
        flat_dead = cfg.thumbs_dir / "5-abcdefabcdefabcd.webp"
        flat_dead.write_bytes(b"x")
        flat_live_name = cfg.thumbs_dir / live.name
        flat_live_name.write_bytes(b"x")

        removed = store.prune_all(s)

    assert live.exists(), "the referenced thumb survives"
    assert not stale.exists(), "a thumb of a deleted file goes"
    assert not stale.parent.exists(), "an emptied shard folder goes too"
    assert not flat_dead.exists() and not flat_live_name.exists(), \
        "old flat-layout files are swept whatever their name"
    assert removed >= 3
