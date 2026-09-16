"""Importing in-memory bytes: the same pipeline a path gets, plus the web-URL
source that says where the bytes came from."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from media_compost import ImportBytes, ImportOptions, open_library
from media_compost.db import File, FileName, Item, ItemMetadata
from media_compost.importer import Importer, _stage_name
from media_compost.media import sniff_ext
from tests.core.conftest import make_image, make_jpeg_with_exif


def _bytes_of(tmp_path: Path, seed: int, fmt: str = "PNG") -> bytes:
    p = make_image(tmp_path / f"seed{seed}.png", seed=seed)
    with Image.open(p) as im:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, fmt)
    return buf.getvalue()


def _sources(s, item_id: int) -> list[FileName]:
    fids = [f.id for f in s.query(File).filter(File.item_id == item_id)]
    return s.query(FileName).filter(FileName.file_id.in_(fids)).all()


def test_bytes_land_in_the_library_as_a_real_file(tmp_path: Path):
    lib = open_library(tmp_path / "data")
    with lib:
        data = _bytes_of(tmp_path, 1)
        got = lib.import_bytes(data, "cat.png")
        assert got and got.status == "imported"
        assert got.stats.imported == 1 and not got.stats.errors

        items = list(lib.query())
        assert len(items) == 1
        v = items[0]
        assert v == got.item
        assert v.name == "cat.png"
        # Written into the item's own folder, and readable from there.
        assert v.path is not None and v.path.exists()
        assert v.path.read_bytes() == data
        assert lib.config.items_dir in v.path.parents


def test_the_url_and_its_access_time_are_recorded_on_the_result(tmp_path: Path):
    """Provenance is the CALLER's line, on the result: the import itself takes
    no url — `got.file` names the stored file, and `add_url` is the record."""
    lib = open_library(tmp_path / "data")
    when = datetime(2026, 3, 4, 5, 6, 7)
    with lib:
        got = lib.import_bytes(_bytes_of(tmp_path, 2), "cat.png")
        got.file.add_url("https://example.test/cat.png", accessed_at=when)
        # The handle says it too, which is what a script reads.
        assert [s.name for s in got.file.sources] == [
            "cat.png", "https://example.test/cat.png"]
        rows = _sources(lib._session, got.item.id)
        url_row = next(r for r in rows if r.is_url)
        assert url_row.accessed_at == when


def test_a_duplicate_still_records_where_it_came_from(tmp_path: Path):
    """The same picture found at a second URL is one item with two sources —
    which is the case the recording is FOR."""
    lib = open_library(tmp_path / "data")
    data = _bytes_of(tmp_path, 3)
    with lib:
        with lib.importing() as run:
            for name, url, when in (
                ("a.png", "https://example.test/a.png", datetime(2026, 1, 1)),
                ("b.png", "https://example.test/b.png", datetime(2026, 1, 2)),
            ):
                got = run.add(ImportBytes(data=data, name=name))
                # `got.file` is the EXISTING file for the duplicate — which is
                # what makes the second URL attachable at all.
                got.file.add_url(url, accessed_at=when)
        assert run.stats.imported == 1 and run.stats.skipped_duplicate == 1
        item_id = lib.query().first().id
        urls = sorted(r.name for r in _sources(lib._session, item_id)
                      if r.is_url)
        assert urls == ["https://example.test/a.png",
                        "https://example.test/b.png"]


def test_the_same_url_at_the_same_time_is_recorded_once(tmp_path: Path):
    """Re-importing one download is not a second sighting; re-fetching it later
    is (the uniqueness rule the Source list applies by hand)."""
    lib = open_library(tmp_path / "data")
    data = _bytes_of(tmp_path, 4)
    url = "https://example.test/x.png"
    with lib:
        with lib.importing() as run:
            for when in (datetime(2026, 1, 1), datetime(2026, 1, 1),
                         datetime(2026, 6, 1)):
                run.add(ImportBytes(data=data, name="x.png")) \
                   .file.add_url(url, accessed_at=when)
        item_id = lib.query().first().id
        times = sorted(r.accessed_at for r in _sources(lib._session, item_id)
                       if r.is_url)
        assert times == [datetime(2026, 1, 1), datetime(2026, 6, 1)]


def test_an_offset_aware_access_time_is_stored_as_utc(tmp_path: Path):
    """SQLite's DATETIME formats the fields it is handed, so an offset passed
    through unchanged would record the fetch at the wrong moment."""
    lib = open_library(tmp_path / "data")
    berlin = timezone(timedelta(hours=2))
    with lib:
        got = lib.import_bytes(_bytes_of(tmp_path, 5), "a.png")
        got.file.add_url("https://example.test/a.png",
                         accessed_at=datetime(2026, 8, 1, 10, 0,
                                              tzinfo=berlin))
        row = next(r for r in _sources(lib._session, got.item.id) if r.is_url)
        assert row.accessed_at == datetime(2026, 8, 1, 8, 0)


def test_bytes_get_the_same_dedup_and_metadata_a_path_gets(tmp_path: Path):
    """Not a separate ingest: the EXIF index and the exact-duplicate rule are
    the file pipeline's, reached by staging the bytes as a file."""
    src = make_jpeg_with_exif(tmp_path / "photo.jpg", seed=7)
    lib = open_library(tmp_path / "data")
    with lib:
        first = lib.import_file(src, folders_as_groups=False)
        got = lib.import_bytes(src.read_bytes(), "photo-again.jpg")
        assert got.stats.imported == 0 and got.stats.skipped_duplicate == 1
        # A duplicate reports the EXISTING item, which is what lets a caller
        # go on to record where this copy came from.
        assert got.status == "duplicate" and got.item == first.item
        v = lib.query().first()
        assert v.metadata["camera_make"] == "TestMake"
        s = lib._session
        assert s.query(Item).count() == 1
        # The second name is recorded against the one stored file.
        assert sorted(r.name for r in _sources(s, v.id)) == [
            "photo-again.jpg", "photo.jpg"]
        assert s.query(ItemMetadata).filter(
            ItemMetadata.item_id == v.id,
            ItemMetadata.name == "camera_make").count() == 1


def test_a_name_without_an_extension_is_read_from_the_bytes(tmp_path: Path):
    lib = open_library(tmp_path / "data")
    with lib:
        lib.import_all([
            ImportBytes(data=_bytes_of(tmp_path, 8, "JPEG"), name="download"),
            ImportBytes(data=_bytes_of(tmp_path, 9), name=""),
        ])
        names = sorted(v.name for v in lib.query())
        assert names == ["download.jpg", "image.png"]


def test_unrecognized_bytes_are_an_error_not_a_crash(tmp_path: Path):
    lib = open_library(tmp_path / "data")
    with lib:
        got = lib.import_bytes(b"not an image", "x")
        # An error is the one result that is falsey, so `if got:` is the
        # check a script writes.
        assert not got and got.status == "error"
        assert got.item is None and "unrecognized file type" in got.error
        assert got.stats.imported == 0 and got.stats.processed == 1
        assert list(lib.query()) == []


def test_paths_and_bytes_mix_in_one_run(tmp_path: Path):
    src = make_image(tmp_path / "on-disk.png", seed=11)
    lib = open_library(tmp_path / "data")
    with lib:
        got = lib.import_all(
            [src, ImportBytes(data=_bytes_of(tmp_path, 12), name="in-mem.png")],
            folders_as_groups=False,
        )
        assert got.stats.imported == 2
        assert len(got.entries) == 2 and got.status == "multi"
        assert sorted(v.name for v in lib.query()) == ["in-mem.png",
                                                       "on-disk.png"]


def test_nothing_is_left_behind_in_the_stage(tmp_path: Path):
    lib = open_library(tmp_path / "data")
    with lib:
        lib.import_bytes(_bytes_of(tmp_path, 13), "a.png")
        stage = lib.config.import_stage_dir
        assert not stage.exists() or not list(stage.iterdir())


def test_an_import_run_is_revertible_from_the_history(tmp_path: Path):
    lib = open_library(tmp_path / "data")
    with lib:
        lib.import_bytes(_bytes_of(tmp_path, 14), "a.png")
        from media_compost.db import Event

        ev = lib._session.query(Event).filter(Event.action == "import").one()
        assert ev.source == "cli"
        assert '"imported_item_ids"' in ev.data
        # And it is revertible the way the History view offers it.
        change = lib.history[0]
        assert change.action == "import" and change.revertible
        change.revert()
        assert list(lib.query()) == []


def test_a_hostile_name_cannot_escape_the_stage(tmp_path: Path):
    assert _stage_name("../../etc/passwd.png") == "passwd.png"
    assert _stage_name("a/b\\c:d.png") == "c_d.png"
    assert _stage_name("") == "image"
    assert _stage_name("...") == "image"
    assert _stage_name("no-extension") == "no-extension"


def test_sniffing_only_answers_for_formats_the_import_accepts(tmp_path: Path):
    assert sniff_ext(_bytes_of(tmp_path, 15, "JPEG")) == "jpg"
    assert sniff_ext(_bytes_of(tmp_path, 16, "PNG")) == "png"
    assert sniff_ext(b"PK\x03\x04rest of a zip") == "zip"
    assert sniff_ext(b"") == ""
    assert sniff_ext(b"<html>not an image</html>") == ""


def test_the_importer_takes_bytes_directly_too(tmp_path: Path):
    """The library API is a convenience; `import_paths` itself accepts the
    mix, so the CLI and the web import could hand it either."""
    lib = open_library(tmp_path / "data")
    with lib:
        s = lib._session
        stats = Importer(s, lib._store, lib.config).import_paths(
            [ImportBytes(data=_bytes_of(tmp_path, 17), name="a.png")],
            ImportOptions(),
        )
        s.commit()
        assert stats.imported == 1


# ---- the run API: statuses, per-source items, add_many ----------------------


def test_status_is_an_enum_and_still_a_string(tmp_path: Path):
    """`ImportStatus` is a `str` subclass, so everything written against the
    old plain strings — equality, f-strings, dict keys — keeps working."""
    from media_compost import ImportStatus

    lib = open_library(tmp_path / "data")
    with lib:
        got = lib.import_bytes(_bytes_of(tmp_path, 70), "a.png")
        assert got.status is ImportStatus.IMPORTED
        assert got.status == "imported"
        assert f"{got.status}" == "imported"
        dup = lib.import_bytes(_bytes_of(tmp_path, 70), "b.png")
        assert dup.status is ImportStatus.DUPLICATE


def test_a_result_lists_only_its_own_items(tmp_path: Path):
    """`ImportResult.items` is what THIS source produced. It used to be every
    item of the whole run so far — wrong for the reader, and quadratic for a
    long crawl (the Nth add built N handles)."""
    lib = open_library(tmp_path / "data")
    with lib:
        with lib.importing() as run:
            first = run.add(ImportBytes(data=_bytes_of(tmp_path, 71), name="a.png"))
            second = run.add(ImportBytes(data=_bytes_of(tmp_path, 72), name="b.png"))
        assert [e.item.name for e in first.entries] == ["a.png"]
        assert [e.item.name for e in second.entries] == ["b.png"]
        assert len(run.items) == 2


def _animated_gif(seed: int, frames: int = 3) -> bytes:
    """An animated GIF, so the importer answers `multi` rather than with one
    item: it is the smallest source that is a BOOK of pictures."""
    # STRUCTURE, not a flat fill: a solid patch's pHash is degenerate, so
    # three plain colours fold into one item and the source stops being a
    # book of pictures at all.
    pics = []
    for i in range(frames):
        im = Image.new("RGB", (160, 120))
        px = im.load()
        for y in range(120):
            for x in range(160):
                px[x, y] = ((x * (i + 2) + seed) % 256, (y * (i + 3)) % 256,
                            (x * y + i * 97) % 256)
        pics.append(im)
    buf = io.BytesIO()
    pics[0].save(buf, "GIF", save_all=True, append_images=pics[1:],
                 duration=80, loop=0)
    return buf.getvalue()


def test_a_book_of_pictures_is_one_entry_with_its_pages_as_children(
        tmp_path: Path):
    """`multi` has no single landing; the ENTRY is the book — its item the
    sequence CONTAINER, the thing the library shows for a GIF — and its
    children are the pages, each with an outcome of its own. The result's
    `item` convenience mirrors the lone entry, so `got.item` answers with
    the container (the thing the old flat lists made unreachable enough
    that every imported GIF's own item went untagged once).
    """
    lib = open_library(tmp_path / "data")
    with lib:
        with lib.importing(folders_as_groups=False) as run:
            got = run.add(ImportBytes(data=_animated_gif(1), name="loop.gif"))
        assert got.status == "multi"
        assert len(got.entries) == 1
        book = got.entries[0]
        assert book.status == "multi" and book.name == "loop.gif"
        assert book.item is not None and book.item.kind == "sequence"
        assert got.item == book.item, "the convenience mirrors the lone entry"
        assert got.file is None and book.file is None
        assert len(book.children) == 3, "one child per distinct frame"
        assert all(c.status == "imported" for c in book.children)
        assert all(c.item.kind == "image" for c in book.children)
        assert all(c.file is not None for c in book.children)
        assert book.item not in [c.item for c in book.children]


def test_a_reimported_book_reports_the_existing_things_it_landed_on(
        tmp_path: Path):
    """A second crawl of one address finds every frame already stored: the
    children are `duplicate` landings on the EXISTING items and files, and
    the entry's container is the existing sequence item (the sequence
    re-import dedup), so `all_items` still names everything a statement
    about this address applies to."""
    lib = open_library(tmp_path / "data")
    body = _animated_gif(2)
    with lib:
        with lib.importing(folders_as_groups=False) as run:
            first = run.add(ImportBytes(data=body, name="loop.gif"))
        with lib.importing(folders_as_groups=False) as run:
            again = run.add(ImportBytes(data=body, name="loop.gif"))
        book, again_book = first.entries[0], again.entries[0]
        assert all(c.status == "duplicate" for c in again_book.children)
        assert ([c.item for c in again_book.children]
                == [c.item for c in book.children])
        assert ([c.file for c in again_book.children]
                == [c.file for c in book.children])
        assert again_book.item == book.item, "the existing container"
        assert set(first.all_items) == set(again.all_items)


def test_the_documented_provenance_walks_reach_a_book_of_pictures(
        tmp_path: Path):
    """`docs/python-api.md`'s crawl recipe, run over the source it exists
    for. The split is the point: a URL is about the BYTES, so it goes on
    `files` — every stored file they were written to — and a tag is about
    the ITEM, so it goes on `all_items`, the container included. A container
    owns no file, so it is tagged and carries no URL.
    """
    url, when = "https://example.test/loop.gif", datetime(2026, 5, 6, 7, 8, 9)
    lib = open_library(tmp_path / "data")
    with lib:
        with lib.importing(folders_as_groups=False) as run:
            got = run.add(ImportBytes(data=_animated_gif(3), name="loop.gif"))
        for stored in got.files:
            stored.add_url(url, accessed_at=when)
        for item in got.all_items:
            item.tags.add("example.test")

        book = got.entries[0]
        assert len(got.files) == len(book.children) > 1
        for frame in book.children:
            assert [s.name for s in frame.item.active_file.sources
                    if s.is_url] == [url]
        assert "example.test" in book.item.tags
        assert all("example.test" in c.item.tags for c in book.children)
        # The container is TAGGED and skipped by the URL half, and this is
        # why: it owns no file, so its `active_file` is a MEMBER's — writing
        # through it would record the same fetch on that frame twice.
        assert list(book.item.files) == []
        rows = lib._session.query(FileName).filter(FileName.is_url).all()
        assert len(rows) == len(book.children)


def test_a_result_names_every_file_its_bytes_landed_on(tmp_path: Path):
    """`files` is `file` in the plural, and it is the one a `multi` source
    can answer. A still picture reports exactly the one `file` names; a book
    of pictures reports one per page, which `file` cannot."""
    lib = open_library(tmp_path / "data")
    with lib:
        with lib.importing(folders_as_groups=False) as run:
            one = run.add(ImportBytes(data=_bytes_of(tmp_path, 95),
                                      name="one.png"))
            book = run.add(ImportBytes(data=_animated_gif(4), name="b.gif"))
        assert one.files == (one.file,)
        assert book.file is None, "a book's one entry is its container"
        kids = book.entries[0].children
        assert len(book.files) == len(kids) > 1
        assert set(book.files) == {c.file for c in kids}


def test_a_duplicate_reports_the_existing_file_its_bytes_landed_on(
        tmp_path: Path):
    """The case provenance exists for: nothing was stored, and the file the
    URL belongs on is the one that was already there."""
    lib = open_library(tmp_path / "data")
    with lib:
        data = _bytes_of(tmp_path, 96)
        with lib.importing(folders_as_groups=False) as run:
            made = run.add(ImportBytes(data=data, name="a.png"))
            dup = run.add(ImportBytes(data=data, name="b.png"))
        assert dup.status == "duplicate"
        assert dup.files == (made.file,) == (dup.file,)


def test_a_retried_file_reports_only_the_attempt_that_stuck(tmp_path: Path):
    """A transient "database is locked" re-runs the file on a fresh snapshot,
    and what comes back names the attempt that stuck — once, and existing.

    This is the one path where a rolled-back file id could surface at all:
    the source SUCCEEDS, so nothing else flags it. An error is not that path
    — `add_source` reports the whole source as an error and a failed result
    names no files. The importer truncates the list with the savepoint;
    SQLite also hands the retry the rowid the rollback freed, so the two
    attempts coincide and this passes either way. Both are wanted: the
    assertion is that a retried source reports one live file, not that the
    id happened to be recycled.
    """
    from sqlalchemy.exc import OperationalError

    lib = open_library(tmp_path / "data")
    with lib:
        with lib.importing(folders_as_groups=False) as run:
            imp = run._imp
            real = imp._ingest_image
            tries = {"n": 0}

            def flaky(*a, **kw):
                tries["n"] += 1
                got = real(*a, **kw)          # the file IS written, and the
                if tries["n"] == 1:           # savepoint then unwinds it
                    raise OperationalError("INSERT", {},
                                           Exception("database is locked"))
                return got

            imp._ingest_image = flaky
            got = run.add(ImportBytes(data=_bytes_of(tmp_path, 99),
                                      name="retried.png"))

        assert tries["n"] == 2, "the first attempt really was retried"
        assert got.status == "imported"
        assert got.files == (got.file,)
        assert all(f.exists for f in got.files)


def test_a_duplicate_names_the_existing_item_and_file(tmp_path: Path):
    """A still picture's answer is one entry: the EXISTING item and file the
    bytes landed on — which is what lets a caller record a second address."""
    lib = open_library(tmp_path / "data")
    with lib:
        data = _bytes_of(tmp_path, 91)
        with lib.importing(folders_as_groups=False) as run:
            made = run.add(ImportBytes(data=data, name="a.png"))
            dup = run.add(ImportBytes(data=data, name="b.png"))
        assert made.status == "imported"
        assert dup.status == "duplicate"
        assert dup.item == made.item and dup.file == made.file
        assert len(dup.entries) == 1
        assert dup.entries[0].status == "duplicate"
        assert dup.all_items == (made.item,)


def test_add_many_matches_a_loop_of_add(tmp_path: Path):
    """The prefetched pipeline is the same import: same statuses in the same
    order, same stored identity (sha256, pHash, color) — only the arithmetic
    moved onto worker threads."""
    bodies = [_bytes_of(tmp_path, 80), _bytes_of(tmp_path, 81),
              _bytes_of(tmp_path, 80),               # a duplicate, mid-run
              b"not an image at all"]                # an error, in order
    on_disk = make_image(tmp_path / "disk.png", seed=82)

    def sources():
        for i, b in enumerate(bodies):
            yield ImportBytes(data=b, name=f"m{i}.png")
        yield on_disk

    lib_a = open_library(tmp_path / "loop")
    with lib_a:
        with lib_a.importing(folders_as_groups=False) as run:
            loop = [run.add(s) for s in sources()]
    lib_b = open_library(tmp_path / "many")
    with lib_b:
        with lib_b.importing(folders_as_groups=False) as run:
            many = list(run.add_many(sources(), prefetch=3))

    assert [r.status for r in loop] == [r.status for r in many]
    assert [len(r.entries) for r in loop] == [len(r.entries) for r in many]
    with lib_a, lib_b:
        a = {(f.sha256, f.phash, f.color_key, f.color_sig)
             for f in lib_a._session.query(File)}
        b = {(f.sha256, f.phash, f.color_key, f.color_sig)
             for f in lib_b._session.query(File)}
        assert a == b and len(a) == 3


def test_the_pool_shape_separates_the_window_from_the_workers():
    """`prefetch` used to be BOTH numbers, so asking the process pool for a
    deeper in-flight window spawned that many interpreters — measured, a
    window of 64 took 2.0 s of import to 4.7 s. The window is about
    smoothing in-order consumption; the workers cap at min(8, CPUs)."""
    from media_compost.library.importing import _pool_shape

    # Defaults: threads keep window == workers (each slot holds decoded
    # pixels), processes widen it (a slim bundle is kilobytes).
    assert _pool_shape(None, False, 14) == (8, 8)
    assert _pool_shape(None, True, 14) == (8, 32)
    # An explicit prefetch is the window, and never spawns past the cap.
    assert _pool_shape(64, True, 14) == (8, 64)
    assert _pool_shape(64, False, 14) == (8, 64)
    # A small prefetch still bounds the workers, as it always did.
    assert _pool_shape(2, True, 14) == (2, 2)
    # A small machine caps below 8 either way.
    assert _pool_shape(None, True, 4) == (4, 16)
    assert _pool_shape(0, False, 4) == (4, 4), "0 means default, like None"


def test_a_body_the_name_rules_out_is_never_handed_to_the_pool():
    """Submitting an `ImportBytes` to a PROCESS pool pickles its whole body
    across a pipe — so a video (which `prepare_source` can only ever answer
    None for) must be ruled out in the parent, by its name. Nameless bytes
    still go: the worker's sniff is the only thing that can identify them.
    A path always goes — it pickles as a string, and classifying it in the
    parent would read the file on the serial thread."""
    from media_compost.importer import worth_prefetching

    assert not worth_prefetching(ImportBytes(data=b"x", name="clip.mp4"))
    assert not worth_prefetching(ImportBytes(data=b"x", name="book.cbz"))
    assert worth_prefetching(ImportBytes(data=b"x", name="pic.jpg"))
    assert worth_prefetching(ImportBytes(data=b"x", name=""))
    assert worth_prefetching("/nowhere/clip.mp4")


def test_add_many_in_worker_processes_matches_the_thread_pool(tmp_path: Path):
    """`processes=True` end to end, through a real spawned pool.

    The bundles cross a pipe without their pixels, so this is the one place
    the whole chain — pickling an ImportBytes out, a slim `PreparedImage`
    back, the serial half filling the gaps — runs for real rather than by
    calling `prepare_source(with_image=False)` in-process. prefetch=2 keeps
    it to two spawned interpreters.
    """
    bodies = [_bytes_of(tmp_path, 85), _bytes_of(tmp_path, 86),
              _bytes_of(tmp_path, 85),               # a duplicate, mid-run
              b"not an image at all"]                # an error, in order
    on_disk = make_image(tmp_path / "disk2.png", seed=87)

    def sources():
        for i, b in enumerate(bodies):
            yield ImportBytes(data=b, name=f"p{i}.png")
        yield on_disk

    lib_a = open_library(tmp_path / "threads")
    with lib_a:
        with lib_a.importing(folders_as_groups=False) as run:
            threads = list(run.add_many(sources(), prefetch=2))
    lib_b = open_library(tmp_path / "procs")
    with lib_b:
        with lib_b.importing(folders_as_groups=False) as run:
            procs = list(run.add_many(sources(), prefetch=2, processes=True))

    assert [r.status for r in threads] == [r.status for r in procs]
    with lib_a, lib_b:
        a = {(f.sha256, f.phash, f.color_key, f.color_sig)
             for f in lib_a._session.query(File)}
        b = {(f.sha256, f.phash, f.color_key, f.color_sig)
             for f in lib_b._session.query(File)}
        assert a == b and len(a) == 3


def test_avif_imports_as_an_ordinary_image(tmp_path: Path):
    """AVIF was missing from IMAGE_EXTS, so `classify` answered "other" and
    every .avif import was skipped — on every platform, not a Linux quirk.
    Pillow >= 11.2 bundles libavif, so decoding needs nothing extra."""
    import pytest
    from PIL import features

    if not features.check("avif"):
        pytest.skip("this Pillow build lacks AVIF")
    img = Image.open(io.BytesIO(_bytes_of(tmp_path, 90)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "AVIF")
    lib = open_library(tmp_path / "data")
    with lib:
        got = lib.import_bytes(buf.getvalue(), "pic.avif")
        assert got.status == "imported"
        assert got.file.format == "avif"
        # Nameless AVIF bytes are sniffed to their type (and dedup to it).
        assert lib.import_bytes(buf.getvalue(), "").status == "duplicate"


# ---- the bulk provenance ops: the crawl batch --------------------------------


def test_bulk_url_recording_is_idempotent_and_reverts(tmp_path: Path):
    """`lib.add_file_urls` is `add_url` at batch grain: idempotent per
    (file, url, access time), a missing file skipped, one revertible History
    entry for the lot."""
    lib = open_library(tmp_path / "data")
    when = datetime(2026, 1, 2, 3, 4, 5)
    with lib:
        a = lib.import_bytes(_bytes_of(tmp_path, 40), "a.png")
        b = lib.import_bytes(_bytes_of(tmp_path, 41), "b.png")
        made = lib.add_file_urls([
            (a.file, "https://x.test/a.png", when),
            (a.file, "https://x.test/a.png", when),      # same row twice
            (b.file, "https://x.test/b.png", "2026-01-02T05:04:05+02:00"),
            (999999, "https://x.test/gone.png", when),   # no such file
        ])
        assert made == 2
        assert lib.add_file_urls(
            [(a.file, "https://x.test/a.png", when)]) == 0, "re-recording"
        urls = {(r.name, r.accessed_at)
                for r in lib._session.query(FileName).filter(FileName.is_url)}
        # The offset-aware string landed as the naive-UTC moment it names.
        assert urls == {("https://x.test/a.png", when),
                        ("https://x.test/b.png", datetime(2026, 1, 2, 3, 4, 5))}

        change = lib.history[0]
        assert change.action == "add_sources_bulk" and change.revertible
        change.revert()
        assert lib._session.query(FileName).filter(
            FileName.is_url).count() == 0


def test_bulk_tag_assignment_is_one_event_and_reverts_exactly(tmp_path: Path):
    """`lib.assign_tags` is the import-tags machinery at batch grain: names
    through the ordinary door, a leading `-` the negative sign, pairs the
    item already carries left alone — and the revert removes exactly what
    the batch created, never the assignment that was already there."""
    from media_compost.db import Event

    lib = open_library(tmp_path / "data")
    with lib:
        a = lib.import_bytes(_bytes_of(tmp_path, 42), "a.png")
        b = lib.import_bytes(_bytes_of(tmp_path, 43), "b.png")
        a.item.tags.add("kept")                    # pre-existing assignment
        events_before = lib._session.query(Event).count()
        made = lib.assign_tags([
            (a.item, "site:x.test"),
            (a.item, "kept"),                      # already carried: skipped
            (b.item, "site:x.test"),
            (b.item, "-blurry"),
        ])
        assert made == 3
        assert lib._session.query(Event).count() == events_before + 1, \
            "one event for the batch (plus none per item)"
        assert "site:x.test" in a.item.tags and "site:x.test" in b.item.tags
        assert b.item.tags["blurry"].negative

        change = lib.history[0]
        assert change.action == "add_tags_bulk" and change.revertible
        change.revert()
        assert "site:x.test" not in a.item.tags
        assert "blurry" not in b.item.tags
        assert "kept" in a.item.tags, "what the batch did not create survives"


def test_the_crawl_batch_recipe_over_a_book(tmp_path: Path):
    """The documented crawl loop: walk `got.files` for the URL batch and
    `got.all_items` for the tag batch — the container tagged, every page's
    file addressed, nothing read off the result shape by hand."""
    url, when = "https://example.test/loop.gif", datetime(2026, 5, 6)
    lib = open_library(tmp_path / "data")
    with lib:
        with lib.importing(folders_as_groups=False) as run:
            got = run.add(ImportBytes(data=_animated_gif(6), name="loop.gif"))
        lib.add_file_urls((f, url, when) for f in got.files)
        lib.assign_tags((it, "site:example.test") for it in got.all_items)
        book = got.entries[0]
        assert "site:example.test" in book.item.tags
        assert all("site:example.test" in c.item.tags for c in book.children)
        rows = lib._session.query(FileName).filter(FileName.is_url).all()
        assert len(rows) == len(book.children)
