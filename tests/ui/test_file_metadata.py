"""Per-file metadata: every stored file says what it says, and keeps saying it.

The headline here is `test_every_stored_file_carries_its_own_metadata`, and it
is deliberately a BEHAVIOURAL sweep rather than a grep over the source. A grep
("a module that mentions compute_phash_image mentions index_file_metadata")
cannot see the two branches in `fileops` that rewrite an existing file's bytes
IN PLACE — no `File` row is constructed there at all — and it passes on a module
that remembers the call at one of its three sites. So this drives every path
that can put bytes under a `File` row and then asks the library.

The exemption list is empty and is meant to stay empty.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ExifTags

from media_compost import media
from media_compost.db import (
    Database, File, FileMetadata, Item, ItemMetadata, ItemMetaMute,
)
from media_compost.importer import Importer, ImportOptions
from media_compost.itemmeta import index_file_metadata, rebuild_item_metadata
from media_compost.storage import ItemStore
from media_compost.ui.config import UiConfig


def _exif_jpeg(path: Path, *, iso: int, make: str = "TestMake",
               seed: int = 1) -> Path:
    """A picture with camera EXIF. `seed` decides the pixels, `iso`/`make` what
    the file says about itself — so two files can be the SAME picture and
    disagree about their metadata, which is the whole case under test."""
    im = Image.new("RGB", (320, 240), (10, 20, 30))
    for x in range(320):
        for y in range(0, 240, 40):
            im.putpixel((x, y + (seed * 7 + x // 8) % 40),
                        ((x * 3) % 256, (seed * 47) % 256, (x * 11) % 256))
    exif = im.getexif()
    exif[271] = make
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    sub[34855] = iso
    im.save(path, "JPEG", quality=95, exif=exif)
    return path


@pytest.fixture
def libdirs(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    return cfg, Database(cfg), ItemStore(cfg)


def _fmeta(s, file_id: int) -> dict[str, str]:
    return {m.name: m.raw for m in s.query(FileMetadata)
            .filter(FileMetadata.file_id == file_id).all()}


def _imeta(s, item_id: int) -> dict[str, str]:
    return {m.name: m.raw for m in s.query(ItemMetadata)
            .filter(ItemMetadata.item_id == item_id).all()}


# ---- the reported bug ------------------------------------------------------

def test_a_near_dup_alternative_keeps_its_own_metadata(libdirs, tmp_path):
    """THE BUG THIS WHOLE FEATURE EXISTS FOR.

    Re-saving a picture with different EXIF gives it a different sha256 and the
    same pixels, so it folds in as an "alternative" source file. Its bytes were
    stored and everything they said about themselves was thrown away — read only
    if the file happened to be promoted to active, which is the case this is
    NOT.
    """
    cfg, db, store = libdirs
    a = _exif_jpeg(tmp_path / "a.jpg", iso=400, make="Canon", seed=3)
    # The same picture, re-saved: same pixels, different bytes, richer EXIF.
    b = tmp_path / "b.jpg"
    with Image.open(a) as im:
        px = im.copy()
    exif = px.getexif()
    exif[271] = "Nikon"
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    sub[34855] = 1600
    sub[36867] = "2020:01:15 14:30:00"
    px.save(b, "JPEG", quality=95, exif=exif)

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [a, b], ImportOptions(folders_as_groups=False))
        s.commit()
    with db.session() as s:
        items = s.query(Item).all()
        assert len(items) == 1, "the re-save should fold in as an alternative"
        item = items[0]
        files = sorted(s.query(File).filter(File.item_id == item.id).all(),
                       key=lambda f: f.number)
        assert len(files) == 2
        active, other = ((files[0], files[1])
                         if item.active_file_id == files[0].id
                         else (files[1], files[0]))
        # BOTH files' answers are kept, each on the file that gives it.
        assert _fmeta(s, active.id)["camera_make"] in ("Canon", "Nikon")
        assert _fmeta(s, other.id)["camera_make"] in ("Canon", "Nikon")
        assert (_fmeta(s, active.id)["camera_make"]
                != _fmeta(s, other.id)["camera_make"])
        # And the item answers for its ACTIVE file, not for whichever was last.
        assert _imeta(s, item.id)["camera_make"] == \
            _fmeta(s, active.id)["camera_make"]


def test_a_rotated_fold_keeps_its_own_metadata(libdirs, tmp_path):
    """The other branch that read nothing at all: a rotation of a picture
    already in the library folds in as a source file, and used to be stored
    with no metadata under any condition."""
    cfg, db, store = libdirs
    a = _exif_jpeg(tmp_path / "a.jpg", iso=100, make="Canon", seed=5)
    b = tmp_path / "b.jpg"
    with Image.open(a) as im:
        turned = im.rotate(-90, expand=True)
    exif = turned.getexif()
    exif[271] = "Rotated"
    turned.save(b, "JPEG", quality=95, exif=exif)

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [a, b], ImportOptions(folders_as_groups=False))
        s.commit()
    with db.session() as s:
        for f in s.query(File).all():
            assert _fmeta(s, f.id), f"file {f.number} carries no metadata"


# ---- the sweep -------------------------------------------------------------

def test_every_stored_file_carries_its_own_metadata(libdirs, tmp_path):
    """Drive every path that puts bytes under a `File` row, then ask the
    library. A file with no rows contributes NOTHING the moment it becomes the
    active one, which reads as an item that has lost its metadata."""
    from media_compost import fileops
    from media_compost.ui import editor as editor_ops

    cfg, db, store = libdirs
    src = _exif_jpeg(tmp_path / "one.jpg", iso=200, seed=11)
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.commit()

    with db.session() as s:
        item = s.query(Item).one()
        active = s.get(File, item.active_file_id)
        # a derived rotated file, and the same call rewriting one in place
        turned = fileops.make_oriented_file(s, store, active, 90, False)
        fileops.make_oriented_file(s, store, active, 180, False, replace=turned)
        # rotate_active_file, both branches — the second rewrites bytes under
        # an existing row, which is the case no flush listener could see.
        derived = fileops.rotate_active_file(s, store, active, 90,
                                             in_place=False)
        s.flush()
        fileops.rotate_active_file(s, store, derived, 90, in_place=True)
        s.commit()

    with db.session() as s:
        item = s.query(Item).order_by(Item.id).first()
        active = s.get(File, item.active_file_id)
        buf = Image.new("RGB", (64, 48), (9, 9, 9))
        import io as _io
        raw = _io.BytesIO()
        buf.save(raw, "PNG")
        # editor: overwrite, derived, and crop-to-new-item
        editor_ops.save_raster(s, store, cfg, item.id, active.id,
                               raw.getvalue(), "overwrite")
        editor_ops.save_raster(s, store, cfg, item.id, active.id,
                               raw.getvalue(), "derived")
        editor_ops.crop_to_new_item(s, store, cfg, item.id, active.id,
                                    raw.getvalue(), None)
        s.commit()

    with db.session() as s:
        missing = [
            (f.item_id, f.number, f.format)
            for f in s.query(File).all()
            if not s.query(FileMetadata)
                    .filter(FileMetadata.file_id == f.id).first()
        ]
        assert missing == [], (
            "every stored file must carry its own metadata; these do not: "
            f"{missing}"
        )
        assert s.query(File).count() >= 6, "the sweep drove too few paths"


# ---- the derivation --------------------------------------------------------

def test_the_item_index_follows_the_active_file(libdirs, tmp_path):
    cfg, db, store = libdirs
    with db.session() as s:
        item = Item(name="x")
        s.add(item)
        s.flush()
        files = []
        for n, iso in ((1, "100"), (2, "800")):
            f = File(item_id=item.id, sha256=str(n) * 64, number=n,
                     width=4, height=4, bytes=1, format="png")
            s.add(f)
            s.flush()
            index_file_metadata(s, store, f, values=[
                media.MetaValue("iso", "numeric", float(iso), None, iso)])
            files.append(f)
        item.active_file_id = files[0].id
        s.flush()
        rebuild_item_metadata(s, item.id)
        assert _imeta(s, item.id) == {"iso": "100"}
        item.active_file_id = files[1].id
        rebuild_item_metadata(s, item.id)
        assert _imeta(s, item.id) == {"iso": "800"}
        # a mute takes the active file's answer away and survives the swap
        s.add(ItemMetaMute(item_id=item.id, name="iso"))
        s.flush()
        rebuild_item_metadata(s, item.id)
        assert _imeta(s, item.id) == {}
        item.active_file_id = files[0].id
        rebuild_item_metadata(s, item.id)
        assert _imeta(s, item.id) == {}


def test_the_swap_listener_rebuilds_without_touching_the_disk(libdirs):
    """The active-file listener is what covers the dozen writers that change
    `Item.active_file_id`. It reads `file_metadata` now, so it needs no file on
    disk at all — which is also what makes it work for videos."""
    cfg, db, store = libdirs
    with db.session() as s:
        item = Item(name="x")
        s.add(item)
        s.flush()
        f1 = File(item_id=item.id, sha256="1" * 64, number=1, width=4,
                  height=4, bytes=1, format="png")
        f2 = File(item_id=item.id, sha256="2" * 64, number=2, width=4,
                  height=4, bytes=1, format="png")
        s.add_all([f1, f2])
        s.flush()
        # Active file FIRST, then index — the order every writer uses, and the
        # one `index_file_metadata`'s docstring insists on.
        item.active_file_id = f1.id
        for f, v in ((f1, "RGB"), (f2, "RGBA")):
            index_file_metadata(s, store, f, values=[
                media.MetaValue("mode", "text", None, v, v)])
        s.commit()
    with db.session() as s:
        item = s.query(Item).one()
        assert _imeta(s, item.id) == {"mode": "RGB"}
        # No file exists on disk for either of these rows.
        item.active_file_id = s.query(File).filter(File.number == 2).one().id
        s.commit()
    with db.session() as s:
        item = s.query(Item).one()
        assert _imeta(s, item.id) == {"mode": "RGBA"}

