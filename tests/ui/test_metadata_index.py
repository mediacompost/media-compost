"""Import-time metadata index: typed extraction, indexing, and the catalog."""

from __future__ import annotations

from pathlib import Path

import math

from PIL import Image, ExifTags, ImageDraw

from media_compost import media
from media_compost.db import File, Item, ItemMetadata
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server.routers.metadata import _catalog


def _jpeg_with_exif(path: Path, seed: int = 1) -> Path:
    """A content-rich JPEG (distinct pHash per seed) carrying camera EXIF across
    the base + Exif sub-IFDs."""
    w, h = 640, 480
    im = Image.new("RGB", (w, h), (10 + seed * 7 % 200, 20, 30))
    d = ImageDraw.Draw(im)
    for i in range(6):
        x = (seed * 37 + i * 53) % w
        y = (seed * 61 + i * 29) % h
        r = 30 + (seed * 13 + i * 17) % 90
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=((seed * 41 + i * 90) % 256, (seed * 97) % 256, (i * 60) % 256))
    for x in range(w):
        v = int(255 * (0.5 + 0.5 * math.sin(x / 20 + seed)))
        d.line([(x, 0), (x, 16)], fill=(v, v, v))
    exif = im.getexif()
    exif[271] = "TestMake"                 # Make (base IFD)
    exif[272] = f"Model{seed}"             # Model (base IFD)
    exif[306] = "2026:07:11 09:44:03"      # DateTime (base IFD)
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    sub[36867] = "2020:01:15 14:30:00"     # DateTimeOriginal (sub-IFD)
    sub[34855] = 400                       # ISOSpeedRatings
    sub[33437] = 2.8                       # FNumber
    sub[37386] = 50.0                      # FocalLength
    im.save(path, "JPEG", exif=exif)
    return path


# ---- pure helpers ----------------------------------------------------------

def test_date_sortkey():
    assert media.date_sortkey("2026:07:11 09:44:03") == 20260711094403.0
    assert media.date_sortkey("2026:07:11") == 20260711000000.0
    assert media.date_sortkey("not a date") is None


def test_exif_num_handles_rational_and_tuple():
    assert media._exif_num(400) == 400.0
    assert media._exif_num((2, 1)) == 2.0
    assert media._exif_num("nope") is None


def test_typed_image_metadata_types(tmp_path: Path):
    p = _jpeg_with_exif(tmp_path / "cam.jpg")
    by_name = {mv.name: mv for mv in media.typed_image_metadata(p)}
    assert by_name["camera_make"].mtype == "text"
    assert by_name["camera_make"].text == "TestMake"
    assert by_name["iso"].mtype == "numeric" and by_name["iso"].num == 400.0
    assert by_name["aperture"].num == 2.8
    assert by_name["date_taken"].mtype == "date"
    assert by_name["date_taken"].num == 20200115143000.0
    # DateTime (base IFD) is the modified date.
    assert by_name["date_modified"].num == 20260711094403.0
    # Pixel mode is an enumerated text value present without any EXIF.
    assert by_name["mode"].text == "RGB"
    # The container format is deliberately NOT indexed: it belongs to the
    # active file (File.format), so it is served intrinsic and can't go stale
    # when an item is edited into another format.
    assert "format" not in by_name


# ---- indexing --------------------------------------------------------------

def test_reindexing_a_file_replaces_rows(lib):
    """Both writers REPLACE rather than accumulate, and each has to do it in
    two halves: the DELETE clears what the database holds, the expunge clears
    what this transaction has queued. Without the second, "replace" would not
    hold within one transaction and the two would collide on the unique key."""
    from media_compost.db import File, FileMetadata
    from media_compost.itemmeta import index_file_metadata, rebuild_item_metadata

    _cfg, db, store = lib
    with db.session() as s:
        item = Item(name="x")
        s.add(item)
        s.flush()
        f = File(item_id=item.id, sha256="a" * 64, number=1, width=4, height=4,
                 bytes=1, format="png")
        s.add(f)
        s.flush()
        item.active_file_id = f.id
        index_file_metadata(s, store, f, values=[
            media.MetaValue("camera_make", "text", None, "Canon", "Canon"),
            media.MetaValue("iso", "numeric", 800.0, None, "800"),
        ])
        s.commit()
        assert {r.name for r in s.query(FileMetadata)
                .filter_by(file_id=f.id).all()} == {"camera_make", "iso"}
        assert {r.name for r in s.query(ItemMetadata)
                .filter_by(item_id=item.id).all()} == {"camera_make", "iso"}

        index_file_metadata(s, store, f, values=[
            media.MetaValue("iso", "numeric", 100.0, None, "100"),
        ])
        s.commit()
        rows = s.query(FileMetadata).filter_by(file_id=f.id).all()
        assert len(rows) == 1 and rows[0].num_value == 100.0
        # …and the item's derived index followed it, because the file is the
        # active one.
        rows = s.query(ItemMetadata).filter_by(item_id=item.id).all()
        assert len(rows) == 1 and rows[0].num_value == 100.0

        # Twice in ONE transaction, which is what the expunge half is for.
        index_file_metadata(s, store, f, values=[
            media.MetaValue("iso", "numeric", 200.0, None, "200")])
        index_file_metadata(s, store, f, values=[
            media.MetaValue("iso", "numeric", 300.0, None, "300")])
        rebuild_item_metadata(s, item.id)
        s.commit()
        rows = s.query(ItemMetadata).filter_by(item_id=item.id).all()
        assert len(rows) == 1 and rows[0].num_value == 300.0


def test_import_populates_metadata_index(lib, tmp_path: Path):
    _cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    _jpeg_with_exif(src / "a.jpg", seed=1)
    with db.session() as s:
        Importer(s, store, _cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False)
        )
        s.commit()
        item = s.query(Item).filter_by(kind="image").one()
        names = {r.name for r in s.query(ItemMetadata).filter_by(item_id=item.id)}
        assert {"camera_make", "camera_model", "iso", "date_taken"} <= names


# ---- catalog ---------------------------------------------------------------

def test_catalog_merges_intrinsic_and_indexed(lib, tmp_path: Path):
    _cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    _jpeg_with_exif(src / "a.jpg", seed=1)
    _jpeg_with_exif(src / "b.jpg", seed=2)
    with db.session() as s:
        Importer(s, store, _cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False)
        )
        s.commit()
        entries = {e.name: e for e in _catalog(s, False)}
        # Intrinsic names present with counts.
        assert entries["width"].mtype == "numeric"
        assert entries["width"].count == 2
        assert entries["width"].num_min == 640.0
        assert "import_date" in entries
        assert "last_import_date" in entries
        assert entries["last_import_date"].mtype == "date"
        # Item type is an intrinsic text name with its kinds as dropdown values.
        assert entries["type"].mtype == "text"
        assert entries["type"].values == ["image"]
        # Indexed EXIF names present.
        assert entries["camera_make"].mtype == "text"
        assert entries["camera_make"].count == 2
        assert entries["iso"].num_min == 400.0
        # Enumerated text names (format / mode) expose their library values for a
        # value dropdown; the test JPEGs are RGB.
        assert entries["format"].values == ["JPEG"]
        assert entries["mode"].values == ["RGB"]
        # A high-cardinality text name is free-form (no value list).
        assert entries["camera_make"].values is None or "TestMake" in entries["camera_make"].values


# ---- every catalog name is actually searchable ------------------------------


def _ctx_for(s, item):
    """The QueryCtx the item grid builds for one item."""
    from media_compost.db import Caption
    from media_compost.metadata_catalog import intrinsic_nums, intrinsic_texts
    from media_compost.query import QueryCtx
    from media_compost.resolve import effective_for_items
    from media_compost.searchctx import load_indexed_meta

    af = s.get(File, item.active_file_id)
    eff = effective_for_items(s, [item.id]).get(item.id)
    nums = intrinsic_nums(af, item.last_imported_at, item.created_at)
    nums["tag_count"] = float(len(eff.positive)) if eff else 0.0
    nums["caption_count"] = float(
        s.query(Caption).filter_by(item_id=item.id, pending=False).count())
    return QueryCtx(
        tags=frozenset(eff.positive) if eff else frozenset(),
        nums=nums,
        texts=intrinsic_texts(item.kind, af, item.uid),
        meta=load_indexed_meta(s, [item.id]).get(item.id, {}),
    )


def _matches(s, item, name: str, value, mtype: str) -> bool:
    from media_compost.query import MetaCond, evaluate

    cond = MetaCond(name=name, mtype=mtype, op="=", value=value,
                    tol=0.0005 if mtype == "numeric" else 0.0)
    return evaluate(cond, _ctx_for(s, item))


def test_every_catalog_name_finds_the_item_that_shows_it(lib, tmp_path: Path):
    """The catalog is the list of names the UI offers; each one must actually
    match the item whose Metadata panel displays that value. This is the guard
    against a name being served for display but never evaluated (or evaluated
    against a stale index)."""
    _cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    _jpeg_with_exif(src / "a.jpg", seed=1)
    Image.new("RGBA", (120, 90), (10, 20, 30, 128)).save(src / "b.png")
    with db.session() as s:
        Importer(s, store, _cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.commit()
        items = s.query(Item).filter_by(kind="image").all()
        names = {e.name: e for e in _catalog(s, False)}
        # Anything the catalog advertises is either an intrinsic or an indexed
        # name; both must be reachable from a query.
        checked = set()
        for item in items:
            ctx = _ctx_for(s, item)
            for name, entry in names.items():
                if entry.mtype == "date":
                    continue          # covered by the date-window tests
                value = ctx.texts.get(name)
                if value in (None, ""):
                    # A name holds a LIST of values now — what the active file
                    # says plus anything pinned to the item — so take the first.
                    got = ctx.meta.get(name) or []
                    if got:
                        mv = got[0]
                        value = mv.text if mv.mtype == "text" else mv.num
                    elif name in ctx.nums:
                        value = ctx.nums[name]
                if value in (None, ""):
                    continue
                assert _matches(s, item, name, value, entry.mtype), \
                    f"{name}={value!r} does not match the item that shows it"
                checked.add(name)
        # The names this fixture can exercise all got checked.
        assert {"width", "height", "resolution", "aspect", "type", "format",
                "id", "mode", "camera_make", "iso"} <= checked


def test_format_and_mode_follow_the_active_file(lib, tmp_path: Path):
    """The reported bug: an item edited from one format to another kept
    answering for the file it was IMPORTED as, while the Metadata panel showed
    the new one. Both are properties of the active file.

    Note the two halves take different routes and the split is the point.
    ``format`` is INTRINSIC — read live off ``File.format`` — so it follows the
    active file whatever anything else does. ``mode`` is INDEXED, so it follows
    only because the new file's own metadata was read into ``file_metadata``,
    which is why this test goes through ``index_file_metadata`` rather than
    hand-building a row. It did hand-build one, and that is exactly the shape
    that would leave a real writer's file contributing nothing.
    """
    from media_compost.itemmeta import index_file_metadata
    from media_compost.storage import sha256_bytes

    _cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    _jpeg_with_exif(src / "a.jpg", seed=1)
    with db.session() as s:
        Importer(s, store, _cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.commit()
        item = s.query(Item).filter_by(kind="image").one()
        assert _matches(s, item, "format", "JPEG", "text")
        assert _matches(s, item, "mode", "RGB", "text")

        # Save a transparent PNG edit and make it the active file, the way the
        # image editor does.
        png = tmp_path / "edit.png"
        Image.new("RGBA", (64, 48), (1, 2, 3, 200)).save(png)
        data = png.read_bytes()
        rel = store.write_file(item.uid, 2, "png", data=data)
        f = File(item_id=item.id, sha256=sha256_bytes(data), path=rel, number=2,
                 width=64, height=48, bytes=len(data), format="png",
                 is_derived=True)
        s.add(f)
        s.flush()
        item.active_file_id = f.id
        index_file_metadata(s, store, f)
        s.commit()

        assert _matches(s, item, "format", "PNG", "text"), \
            "format still answers for the imported file"
        assert _matches(s, item, "mode", "RGBA", "text"), \
            "the metadata index was not refreshed when the active file changed"
        assert not _matches(s, item, "format", "JPEG", "text")
        assert not _matches(s, item, "mode", "RGB", "text")


def test_item_id_is_searchable_exactly_and_by_prefix(lib, tmp_path: Path):
    _cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    _jpeg_with_exif(src / "a.jpg", seed=1)
    with db.session() as s:
        Importer(s, store, _cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.commit()
        item = s.query(Item).filter_by(kind="image").one()
        from media_compost.query import MetaCond, evaluate

        ctx = _ctx_for(s, item)
        assert evaluate(MetaCond(name="id", mtype="text", op="=",
                                 value=item.uid), ctx)
        assert evaluate(MetaCond(name="id", mtype="text", op="~",
                                 value=item.uid[:8]), ctx)
        assert not evaluate(MetaCond(name="id", mtype="text", op="=",
                                     value="0" * 32), ctx)
