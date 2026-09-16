"""Settings → Storage: removing files from items by RULE.

The unit is a file of an item, and the whole point is the files the rest of
the app cannot reach — an item carrying four versions of one picture because
the same folder was imported at four sizes, or a crawl that kept a thumbnail
beside every original. What these hold is that the matcher matches, the
guards spare, the bytes actually leave the disk, and an item left with
nothing goes with its last file rather than becoming an item with no picture.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, text

from media_compost.db import File, FileArtifact, Item
from media_compost.importer import Importer, ImportOptions
from media_compost.ops import Ctx, artifacts as ops_artifacts
from media_compost.storage import sha256_bytes
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def lib_client(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    src = tmp_path / "big.png"
    Image.new("RGB", (1200, 900), (200, 30, 30)).save(src)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _add_file(lib, item_id: int, number: int, w: int, h: int, *,
              derived: bool = False, active: bool = False) -> int:
    """A second (third, fourth) version of an item, with REAL bytes — real,
    because the prune has to take the file with the row and a fabricated path
    would not prove that."""
    with lib.db.session() as s:
        item = s.get(Item, item_id)
        buf = Path(str(lib.config.data_dir / f"_scratch{number}.png"))
        Image.new("RGB", (w, h), (10 * number % 255, 40, 90)).save(buf)
        data = buf.read_bytes()
        buf.unlink()
        rel = lib.store.write_file(item.uid, number, "png", data=data)
        f = File(item_id=item.id, sha256=sha256_bytes(data), path=rel,
                 number=number, width=w, height=h, bytes=len(data),
                 format="png", is_derived=derived)
        s.add(f)
        s.flush()
        if active:
            item.active_file_id = f.id
        s.commit()
        return f.id


def _rule(**over):
    rule = {"keep_active": True, "keep_edited": True,
            "min_megapixels": 0, "min_short_edge": 0}
    rule.update(over)
    return rule


def _preview(client, **over):
    r = client.post("/api/library/storage/file-prune/preview", json=_rule(**over))
    assert r.status_code == 200, r.text
    return r.json()


def _run(client, **over):
    """Start a prune and wait for it, answering the totals it ended on.

    The endpoint returns a RUN rather than a result — a prune over a large
    library is minutes of committed chunks, so it is a background task with a
    progress bar and a cancel. Every test below is about what a prune DOES,
    which is unchanged, so the waiting lives here rather than in each of them.
    """
    r = client.post("/api/library/storage/file-prune", json=_rule(**over))
    assert r.status_code == 200, r.text
    return _run_wait(client, r.json())


def _run_wait(client, job: dict, expect: str = "done") -> dict:
    """Poll a started run until it stops, and answer what it ended on."""
    deadline = time.monotonic() + 60
    while job["status"] == "running":
        assert time.monotonic() < deadline, f"prune did not finish: {job}"
        time.sleep(0.01)
        r = client.get(f"/api/library/storage/file-prune/{job['id']}")
        assert r.status_code == 200, r.text
        job = r.json()
    assert job["status"] == expect, job
    return job


def _totals(job: dict) -> dict:
    """The three figures a preview promises, out of whatever answered.

    A run reports them beside its own id and status, so the two shapes are
    compared through this rather than whole — the claim under test is that a
    prune does what the preview said, not that a run looks like a preview.
    """
    return {k: job[k] for k in ("files", "bytes", "items")}


def _only_item(lib) -> int:
    with lib.db.session() as s:
        return s.execute(select(Item.id)).scalars().first()


def test_the_preview_and_the_prune_agree(lib_client):
    """The preview is the whole safety story — the confirmation only repeats
    it — so what it promises has to be what happens."""
    client, lib = lib_client
    iid = _only_item(lib)
    _add_file(lib, iid, 2, 120, 90)
    _add_file(lib, iid, 3, 200, 150)

    seen = _preview(client, min_short_edge=200)
    assert (seen["files"], seen["items"]) == (2, 0)
    assert seen["bytes"] > 0
    assert _totals(_run(client, min_short_edge=200)) == seen


def test_the_active_file_is_spared_however_small_it_is(lib_client):
    client, lib = lib_client
    iid = _only_item(lib)
    small = _add_file(lib, iid, 2, 40, 30, active=True)

    assert _preview(client, min_short_edge=5000)["files"] == 1
    _run(client, min_short_edge=5000)
    with lib.db.session() as s:
        assert [f.id for f in s.execute(select(File)).scalars()] == [small]


def test_an_edited_file_is_spared_only_while_the_guard_is_on(lib_client):
    client, lib = lib_client
    iid = _only_item(lib)
    _add_file(lib, iid, 2, 40, 30, derived=True)

    assert _preview(client, min_short_edge=100)["files"] == 0
    assert _preview(client, min_short_edge=100, keep_edited=False)["files"] == 1


def test_both_thresholds_are_MINIMUMS_so_a_file_must_clear_BOTH(lib_client):
    """Each is a minimum, so the removal side is an OR: setting both is
    strictly more aggressive than setting either."""
    client, lib = lib_client
    iid = _only_item(lib)
    # Wide and thin: 0.4 MP, shortest edge 200. Clears a 100 px edge and
    # fails a 1 MP minimum.
    _add_file(lib, iid, 2, 2000, 200)

    assert _preview(client, min_short_edge=100)["files"] == 0
    assert _preview(client, min_megapixels=1)["files"] == 1
    assert _preview(client, min_short_edge=100, min_megapixels=1)["files"] == 1


def test_the_two_EDGE_thresholds_ask_different_questions(lib_client):
    """Neither implies the other, which is the whole reason for having both.

    A wide banner is huge along one edge and tiny across it; a small square
    is modest in both. A short-edge minimum catches the banner and spares the
    square, and a long-edge minimum does exactly the reverse.
    """
    client, lib = lib_client
    iid = _only_item(lib)
    _add_file(lib, iid, 2, 2000, 80)    # a banner: long edge 2000, short 80
    _add_file(lib, iid, 3, 300, 300)    # a small square: both edges 300

    assert _preview(client, min_short_edge=200)["files"] == 1, "the banner"
    assert _preview(client, min_long_edge=500)["files"] == 1, "the square"
    # OR'd, like every other pair of thresholds here.
    assert _preview(client, min_short_edge=200, min_long_edge=500)["files"] == 2


def test_a_long_edge_minimum_removes_what_it_matches(lib_client):
    client, lib = lib_client
    iid = _only_item(lib)
    small = _add_file(lib, iid, 2, 300, 200)

    assert _run(client, min_long_edge=500)["files"] == 1
    with lib.db.session() as s:
        assert small not in {f.id for f in s.execute(select(File)).scalars()}


def test_a_file_of_unknown_size_is_never_matched_by_a_threshold(lib_client):
    """0x0 is "nobody measured", not "small". The safe direction for a delete
    that cannot be undone is to leave what the rule cannot judge alone."""
    client, lib = lib_client
    iid = _only_item(lib)
    _add_file(lib, iid, 2, 100, 80)
    unknown = _add_file(lib, iid, 3, 100, 80)
    with lib.db.session() as s:
        f = s.get(File, unknown)
        f.width = f.height = 0
        s.commit()

    assert _preview(client, min_short_edge=5000)["files"] == 1
    _run(client, min_short_edge=5000)
    with lib.db.session() as s:
        assert unknown in {f.id for f in s.execute(select(File)).scalars()}


def test_the_bytes_and_the_artifacts_leave_the_disk(lib_client):
    client, lib = lib_client
    iid = _only_item(lib)
    fid = _add_file(lib, iid, 2, 100, 80)
    with lib.db.session() as s:
        item = s.get(Item, iid)
        path = lib.store.write_artifact(item.uid, 2, "depth", "bin", b"d" * 700)
        ctx = Ctx(session=s, _store=lib.store, source="test")
        ops_artifacts.create_one(ctx, file_id=fid, kind="depth", path=path,
                                 model="m", bytes=700)
        s.commit()
        on_disk = lib.store.path_of(s, s.get(File, fid))
        art_disk = lib.config.data_dir / "items" / item.uid[:2] / item.uid / path

    res = _run(client, min_short_edge=200)
    assert res["files"] == 1
    # The artifact's bytes are part of what the disk gives back — the row
    # cascades with the file, so leaving them out would understate it.
    assert res["bytes"] >= 700
    assert not on_disk.exists() and not art_disk.exists()
    with lib.db.session() as s:
        assert s.execute(select(FileArtifact)).scalars().all() == []


def test_an_item_left_with_nothing_goes_with_its_last_file(lib_client):
    """Its bytes are already gone, so a trashed copy could only be restored
    into a picture that no longer exists."""
    client, lib = lib_client
    iid = _only_item(lib)

    seen = _preview(client, min_short_edge=5000, keep_active=False)
    assert (seen["files"], seen["items"]) == (1, 1)
    assert _totals(_run(client, min_short_edge=5000, keep_active=False)) == seen
    with lib.db.session() as s:
        assert s.get(Item, iid) is None
        assert s.execute(select(File)).scalars().all() == []


def test_no_threshold_and_no_edited_guard_is_EVERY_file_but_the_active_one(
        lib_client):
    """The plainest rule there is: keep one version of each item, drop the
    rest. With no threshold the matcher takes everything, so what is left is
    exactly what the guards spare — and with only the active file spared,
    that includes the files an editor made."""
    client, lib = lib_client
    iid = _only_item(lib)
    active = _add_file(lib, iid, 2, 900, 700, active=True)
    _add_file(lib, iid, 3, 800, 600)
    _add_file(lib, iid, 4, 700, 500, derived=True)

    # The original from the fixture, the alternative, and the edited file.
    assert _preview(client, keep_edited=False)["files"] == 3
    assert _run(client, keep_edited=False)["files"] == 3
    with lib.db.session() as s:
        assert [f.id for f in s.execute(select(File)).scalars()] == [active]


def test_the_rule_that_matches_EVERYTHING_is_allowed(lib_client):
    """No threshold and no guard is the whole library, and that is a real
    thing to want: start over, keeping the groups, tags and captions.

    It was refused for a while — which also made an empty form the one state
    the page could not preview. What guards it is what guards every other
    rule: the preview says how many files and how many ITEMS go, and the
    dialog says it again before anything runs.
    """
    client, lib = lib_client
    iid = _only_item(lib)
    _add_file(lib, iid, 2, 100, 80, derived=True)

    both_off = dict(keep_active=False, keep_edited=False)
    seen = _preview(client, **both_off)
    assert (seen["files"], seen["items"]) == (2, 1)
    assert seen["bytes"] > 0
    assert _totals(_run(client, **both_off)) == seen
    with lib.db.session() as s:
        assert s.execute(select(File)).scalars().all() == []
        assert s.get(Item, iid) is None, "the item went with its last file"


def test_no_threshold_is_a_real_rule(lib_client):
    """"Everything that is not the active file" is exactly how a library full
    of near-duplicate alternatives is cleaned up."""
    client, lib = lib_client
    iid = _only_item(lib)
    _add_file(lib, iid, 2, 300, 200)
    _add_file(lib, iid, 3, 300, 200)

    assert _preview(client)["files"] == 2
    assert _run(client)["items"] == 0
    with lib.db.session() as s:
        left = s.execute(select(File)).scalars().all()
        assert [f.id for f in left] == [s.get(Item, iid).active_file_id]


def test_the_active_file_is_re_chosen_when_it_goes(lib_client):
    """With the guard off the active file is as droppable as any other, and
    the largest of what is left takes its place."""
    client, lib = lib_client
    iid = _only_item(lib)                       # the imported 1200x900
    _add_file(lib, iid, 2, 400, 300, active=True)   # 0.12 MP, and active
    _add_file(lib, iid, 3, 800, 600)                # 0.48 MP
    with lib.db.session() as s:
        original = min(f.id for f in s.execute(select(File)).scalars())

    assert _run(client, min_megapixels=0.3, keep_active=False)["files"] == 1
    with lib.db.session() as s:
        item = s.get(Item, iid)
        assert item is not None
        assert item.active_file_id == original, "the largest survivor"


def test_more_than_one_batch_is_removed(lib_client, monkeypatch):
    """The endpoint chunks its transaction, and a rule aimed at a crawl's
    thumbnails matches six figures of files."""
    from media_compost.ui.server.routers import stats

    client, lib = lib_client
    iid = _only_item(lib)
    for n in range(2, 8):
        _add_file(lib, iid, n, 60, 40)
    monkeypatch.setattr(stats, "_PRUNE_CHUNK", 2)

    assert _run(client, min_short_edge=100)["files"] == 6
    with lib.db.session() as s:
        assert len(s.execute(select(File)).scalars().all()) == 1


def test_a_sequence_container_is_not_an_item_left_with_nothing(lib_client,
                                                               tmp_path):
    """A container owns NO file — it borrows a member's — so "no files left"
    would delete every chapter in the library on any rule at all."""
    import zipfile

    client, lib = lib_client
    book = tmp_path / "book.cbz"
    with zipfile.ZipFile(book, "w") as z:
        for i in range(2):
            page = tmp_path / f"p{i}.png"
            Image.new("RGB", (600, 800), (i * 60, 90, 120)).save(page)
            z.write(page, f"p{i}.png")
    with lib.db.session() as s:
        Importer(s, lib.store, lib.config).import_paths(
            [book], ImportOptions(folders_as_groups=False))

    with lib.db.session() as s:
        containers = s.execute(
            select(Item.id).where(Item.kind == "sequence")).scalars().all()
    assert containers, "the archive imported as a sequence"

    assert _preview(client, min_short_edge=5000)["items"] == 0
    _run(client, min_short_edge=5000)
    with lib.db.session() as s:
        assert set(s.execute(
            select(Item.id).where(Item.kind == "sequence")).scalars()
        ) == set(containers)


def test_the_preview_is_a_read_only_POST(lib_client):
    """Default-deny: left out of `READ_ONLY_POSTS` it would 409 on a stale
    page for every keystroke, which is the third thing that list has cost."""
    from media_compost.ui.server.build import writes

    assert not writes("POST", "/api/library/storage/file-prune/preview")
    assert writes("POST", "/api/library/storage/file-prune")


# ---- the run ----------------------------------------------------------------
#
# A prune is a background task rather than a held-open request: removing a few
# gigabytes is minutes of committed chunks, and as one request that is
# indistinguishable from a hang — nothing to show, nothing to cancel, and a
# browser or proxy timeout loses the answer while the deletions carry on.


def test_the_run_reports_progress_against_what_the_preview_promised(
        lib_client, monkeypatch):
    """`total` is the preview's file count, fixed at the start.

    Fixed, because the rule matches fewer files with every committed chunk: a
    total recomputed as it goes would count down towards a moving number and
    the bar would never fill. What makes it honest is that the run ends with
    `files == total`.
    """
    from media_compost.ui.server.routers import stats

    client, lib = lib_client
    iid = _only_item(lib)
    for n in range(2, 8):
        _add_file(lib, iid, n, 60, 40)
    monkeypatch.setattr(stats, "_PRUNE_CHUNK", 2)

    r = client.post("/api/library/storage/file-prune",
                    json=_rule(min_short_edge=100))
    assert r.status_code == 200, r.text
    started = r.json()
    assert started["total"] == 6, "the preview's count, before anything ran"
    assert started["status"] == "running"
    assert started["files"] == 0, "answered before the work, not after it"

    done = _run_wait(client, started)
    assert (done["files"], done["total"]) == (6, 6), "the bar fills exactly"
    assert done["bytes"] > 0


def test_a_cancelled_run_keeps_what_it_had_already_committed(lib_client,
                                                            monkeypatch):
    """Those bytes are gone: a prune that undid its own finished chunks would
    have to put back files nothing holds any more. So cancel stops it after
    the chunk in flight and leaves the rest of the library alone."""
    from media_compost.ui.server.routers import stats

    client, lib = lib_client
    iid = _only_item(lib)
    for n in range(2, 8):
        _add_file(lib, iid, n, 60, 40)

    # One chunk at a time, and a handshake rather than a race: the worker
    # stops after its first chunk, THIS thread cancels, and only then is the
    # worker let go — so the run reaches the cancel check having committed
    # exactly one chunk, every time. (The test client is driven from one
    # thread throughout for the same reason.)
    monkeypatch.setattr(stats, "_PRUNE_CHUNK", 1)
    first_done, cancelled = threading.Event(), threading.Event()
    real = stats.ops_files.prune

    def counting(ctx, rule, **kw):
        out = real(ctx, rule, **kw)
        if not first_done.is_set():
            first_done.set()
            assert cancelled.wait(10)
        return out

    monkeypatch.setattr(stats.ops_files, "prune", counting)
    r = client.post("/api/library/storage/file-prune",
                    json=_rule(min_short_edge=100))
    job = r.json()
    assert first_done.wait(10)
    assert client.delete(
        f"/api/library/storage/file-prune/{job['id']}").status_code == 200
    cancelled.set()
    ended = _run_wait(client, job, expect="cancelled")

    assert ended["files"] == 1, "the chunk in flight finished"
    assert ended["total"] == 6, "and the rest was left alone"
    with lib.db.session() as s:
        assert len(s.execute(select(File)).scalars().all()) == 6


def test_a_second_start_joins_the_run_already_going(lib_client, monkeypatch):
    """Two prunes would race for the same rows, and the second would spend
    its chunks discovering what the first had already removed."""
    from media_compost.ui.server.routers import stats

    client, lib = lib_client
    iid = _only_item(lib)
    for n in range(2, 8):
        _add_file(lib, iid, n, 60, 40)

    gate = threading.Event()
    real = stats.ops_files.prune
    monkeypatch.setattr(stats.ops_files, "prune",
                        lambda ctx, rule, **kw: (gate.wait(10), real(ctx, rule, **kw))[1])
    monkeypatch.setattr(stats, "_PRUNE_CHUNK", 1)

    first = client.post("/api/library/storage/file-prune",
                        json=_rule(min_short_edge=100)).json()
    second = client.post("/api/library/storage/file-prune",
                         json=_rule(min_short_edge=100)).json()
    assert second["id"] == first["id"], "the same run, not a second one"
    gate.set()
    _run_wait(client, first)


def test_an_unknown_run_is_a_404_rather_than_an_empty_one(lib_client):
    """A run the server has never heard of — a page left open across a
    restart — must say so, or the bar sits at nothing for ever."""
    client, _ = lib_client
    assert client.get("/api/library/storage/file-prune/nope").status_code == 404
    assert client.delete("/api/library/storage/file-prune/nope").status_code == 404


def test_the_bulk_delete_LEAVES_NO_ORPHANS(lib_client):
    """The delete is one Core statement per chunk and the DATABASE cascades.

    That is only safe while every child of an item (or a file) is reachable
    by a foreign key the database itself acts on — so this builds an item
    with children in several of those tables, prunes it away, and asks SQLite
    whether anything is left pointing at a row that no longer exists.

    `PRAGMA foreign_key_check` is the general form of the question, which is
    the point: a table added later, with a child nobody remembered, fails
    here without this test having to name it.
    """
    from media_compost.db import Caption, FileName, ItemTag, Tag

    client, lib = lib_client
    iid = _only_item(lib)
    fid = _add_file(lib, iid, 2, 100, 80)
    with lib.db.session() as s:
        tag = Tag(name="orphan_check")
        s.add(tag)
        s.flush()
        s.add_all([
            ItemTag(item_id=iid, tag_id=tag.id),
            Caption(item_id=iid, text="a caption"),
            FileName(file_id=fid, name="somewhere.png"),
        ])
        item = s.get(Item, iid)
        path = lib.store.write_artifact(item.uid, 2, "depth", "bin", b"d" * 32)
        ctx = Ctx(session=s, _store=lib.store, source="test")
        ops_artifacts.create_one(ctx, file_id=fid, kind="depth", path=path,
                                 model="m", bytes=32)
        s.commit()

    # Everything of this item goes: no threshold, nothing kept.
    _run(client, keep_active=False, keep_edited=False)

    with lib.db.session() as s:
        assert s.get(Item, iid) is None
        assert s.execute(select(File)).scalars().all() == []
        for model in (ItemTag, Caption, FileName, FileArtifact):
            left = s.execute(select(model)).scalars().all()
            assert left == [], f"{model.__name__} rows outlived their item"
        # The tag itself is a CATALOG row and must NOT go with the item.
        assert s.execute(select(Tag)).scalars().first() is not None
        broken = s.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert broken == [], f"rows pointing at deleted parents: {broken}"


def test_the_rule_can_be_confined_to_IMAGES_or_to_VIDEOS(lib_client):
    """A SCOPE, not another threshold: it narrows what the rest of the rule is
    asked about rather than being one more reason to remove a file."""
    client, lib = lib_client
    iid = _only_item(lib)
    _add_file(lib, iid, 2, 100, 80)
    with lib.db.session() as s:
        film = Item(name="a film", kind="video")
        s.add(film)
        s.flush()
        vid = film.id
        s.commit()
    _add_file(lib, vid, 1, 100, 80)

    assert _preview(client, min_short_edge=5000)["files"] == 2
    assert _preview(client, min_short_edge=5000, kind="image")["files"] == 1
    assert _preview(client, min_short_edge=5000, kind="video")["files"] == 1

    _run(client, min_short_edge=5000, kind="video")
    with lib.db.session() as s:
        left = {f.item_id for f in s.execute(select(File)).scalars()}
        assert vid not in left, "the film's file went"
        assert iid in left, "the picture's did not"


def test_an_unknown_kind_is_refused_rather_than_matching_nothing(lib_client):
    client, _ = lib_client
    r = client.post("/api/library/storage/file-prune/preview",
                    json=_rule(kind="sequence"))
    assert r.status_code == 422, r.text
