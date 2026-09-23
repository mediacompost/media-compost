"""Settings → Storage: the breakdown, and the one action on it.

The page answers "why is this library 200 GB", so what these hold is that the
numbers are the ones on disk and that deleting a TYPE deletes all of it —
rows and bytes — while a cache stays refusable while a trainer is reading it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import event as sa_event, select

from media_compost.db import File, FileArtifact, Item
from media_compost.importer import Importer, ImportOptions
from media_compost.ops import Ctx, artifacts as ops_artifacts
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def lib_client(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    im = Image.new("RGB", (300, 300), (255, 255, 255))
    ImageDraw.Draw(im).ellipse([80, 80, 220, 220], fill=(200, 30, 30))
    src = tmp_path / "disc.png"
    im.save(src, "PNG")
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _add_artifact(lib, kind: str, model: str, payload: bytes) -> int:
    """Store real bytes as an artifact — real, because the delete has to take
    the FILE with the row and a fabricated path would not prove that."""
    with lib.db.session() as s:
        item = s.get(Item, s.execute(select(Item.id)).scalars().first())
        fid = item.active_file_id
        number = s.get(File, fid).number
        path = lib.store.write_artifact(item.uid, number, kind, "bin", payload,
                                        model=model)
        ctx = Ctx(session=s, _store=lib.store, source="test")
        art = ops_artifacts.create_one(
            ctx, file_id=fid, kind=kind, path=path, model=model,
            bytes=len(payload))
        s.commit()
        return art.id


class _Busy:
    @staticmethod
    def running_uid():
        return "job-uid"


def _busy_trainer():
    """A stand-in `Trainer` whose job manager says a run is under way — the
    one thing the delete has to ask before touching a cache."""
    return type("T", (), {"jobs": _Busy()})()


def test_the_breakdown_reports_what_is_on_disk(lib_client):
    client, lib = lib_client
    _add_artifact(lib, "latent", "sd15", b"x" * 400)
    _add_artifact(lib, "latent", "sd15", b"y" * 600)
    _add_artifact(lib, "depth", "depth_anything_v2_small", b"z" * 100)

    out = client.get("/api/library/storage").json()
    assert [r["key"] for r in out["items"]] == ["image"]
    assert out["items"][0]["count"] == 1 and out["items"][0]["bytes"] > 0
    arts = {(r["kind"], r["model"]): r for r in out["artifacts"]}
    assert arts[("latent", "sd15")]["count"] == 2
    assert arts[("latent", "sd15")]["bytes"] == 1000
    # Sorted by size, biggest first — the page is read top-down.
    assert out["artifacts"][0]["bytes"] >= out["artifacts"][-1]["bytes"]
    # A cache says so: the question the UI asks about it is different.
    assert arts[("latent", "sd15")]["cache"] is True
    assert arts[("depth", "depth_anything_v2_small")]["cache"] is False
    # The library folder's own furniture is measured by walking.
    other = {r["key"]: r for r in out["other"]}
    assert other["database"]["bytes"] > 0
    # A directory with nothing in it gets NO row — "Thumbnails 0 B" is a line
    # of noise on a page about where the disk went. (Nothing has asked for a
    # thumbnail in this library yet; they are made on demand.)
    assert "thumbnails" not in other


def test_nothing_is_counted_under_two_names(lib_client):
    """`refs_dir` lives INSIDE `tmp`, and the first version of this page
    walked both — reporting the same five files twice, under two names, in a
    total that is supposed to add up."""
    client, lib = lib_client
    refs = lib.config.refs_dir
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "ref.png").write_bytes(b"p" * 5000)

    out = client.get("/api/library/storage").json()
    keys = [r["key"] for r in out["other"]]
    assert len(keys) == len(set(keys))
    scratch = next(r for r in out["other"] if r["key"] == "scratch")
    assert scratch["bytes"] >= 5000, "the refs are inside the scratch row"


def test_the_evaluate_pictures_are_their_own_row(lib_client):
    """They live inside the training folder, and were counted as "Training
    runs" — in a library that had never trained anything, all of that row."""
    client, lib = lib_client
    from media_compost.train import evaluate
    from media_compost.ui.server.routers import stats
    assert stats.EVAL_DIRNAME == evaluate._EVAL_DIRNAME

    training = lib.config.data_dir / "training"
    run = training / stats.EVAL_DIRNAME / "run1" / "images"
    run.mkdir(parents=True)
    (run / "p000.png").write_bytes(b"e" * 3000)
    (training / "job1").mkdir()
    (training / "job1" / "job.json").write_bytes(b"j" * 700)

    other = {r["key"]: r for r in
             client.get("/api/library/storage").json()["other"]}
    assert (other["evaluate"]["count"], other["evaluate"]["bytes"]) == (1, 3000)
    assert (other["training"]["count"], other["training"]["bytes"]) == (1, 700)


def test_deleting_a_type_takes_the_rows_AND_the_bytes(lib_client):
    client, lib = lib_client
    keep = _add_artifact(lib, "latent", "sdxl", b"k" * 50)
    _add_artifact(lib, "latent", "sd15", b"a" * 400)
    _add_artifact(lib, "latent", "sd15", b"b" * 600)
    with lib.db.session() as s:
        paths = [lib.store.path_of(s, a) for a in
                 s.execute(select(FileArtifact)
                           .where(FileArtifact.model == "sd15")).scalars()]
    assert all(p.exists() for p in paths)

    res = client.delete("/api/library/storage/artifacts",
                        params={"kind": "latent", "model": "sd15"}).json()
    assert res == {"ok": True, "deleted": 2, "bytes": 1000}
    assert not any(p.exists() for p in paths), "the files go with the rows"
    with lib.db.session() as s:
        left = s.execute(select(FileArtifact)).scalars().all()
        assert [a.id for a in left] == [keep], "another model is left alone"


def test_no_model_named_is_its_own_question(lib_client):
    """`model=""` means the rows naming none; the parameter absent means every
    model of the kind. Conflating them deletes four times what was asked."""
    client, lib = lib_client
    _add_artifact(lib, "canny", "", b"c" * 40)
    _add_artifact(lib, "canny", "canny", b"d" * 40)

    res = client.delete("/api/library/storage/artifacts",
                        params={"kind": "canny", "model": ""}).json()
    assert res["deleted"] == 1
    with lib.db.session() as s:
        assert [a.model for a in
                s.execute(select(FileArtifact)).scalars()] == ["canny"]

    res = client.delete("/api/library/storage/artifacts",
                        params={"kind": "canny"}).json()
    assert res["deleted"] == 1
    with lib.db.session() as s:
        assert s.execute(select(FileArtifact)).scalars().all() == []


def test_a_cache_is_refused_while_a_trainer_is_reading_it(lib_client):
    """The single-artifact delete has always refused this; the bulk one runs
    over the whole cache a run is stepping through, so it matters more."""
    client, lib = lib_client
    _add_artifact(lib, "latent", "sd15", b"a" * 400)

    lib._trainer = _busy_trainer()
    r = client.delete("/api/library/storage/artifacts",
                      params={"kind": "latent", "model": "sd15"})
    assert r.status_code == 409
    assert "training job is running" in r.json()["detail"]
    with lib.db.session() as s:
        assert len(s.execute(select(FileArtifact)).scalars().all()) == 1


def test_a_generated_artifact_is_NOT_refused_while_training(lib_client):
    """Only a CACHE is what a run reads every step. A depth map has nothing to
    do with training, and refusing it would be a rule nobody could explain."""
    client, lib = lib_client
    _add_artifact(lib, "depth", "depth_anything_v2_small", b"z" * 100)

    lib._trainer = _busy_trainer()
    r = client.delete("/api/library/storage/artifacts",
                      params={"kind": "depth"})
    assert r.status_code == 200 and r.json()["deleted"] == 1


def test_more_than_one_batch_is_deleted(lib_client):
    """`delete_kind` answers one bounded batch and says whether more remain —
    the endpoint loops. A cap read as "that was all" leaves most of a warmed
    latent cache on disk while reporting success."""
    client, lib = lib_client
    for i in range(7):
        _add_artifact(lib, "latent", "sd15", bytes([65 + i]) * 10)

    with lib.db.session() as s:
        ctx = Ctx(session=s, _store=lib.store, source="test")
        n, freed, more = ops_artifacts.delete_kind(ctx, "latent", "sd15",
                                                   limit=3)
        s.commit()
        assert (n, freed, more) == (3, 30, True)

    res = client.delete("/api/library/storage/artifacts",
                        params={"kind": "latent", "model": "sd15"}).json()
    assert res["deleted"] == 4
    with lib.db.session() as s:
        assert s.execute(select(FileArtifact)).scalars().all() == []


def test_the_library_and_the_train_tab_report_ONE_free_figure(lib_client,
                                                              monkeypatch):
    """Free space is `disk_usage().free`, on every surface that shows it.

    The Train tab used to report `total - used`, which is not the same number
    on Linux: `used` is derived from `f_bfree` (blocks nobody has written)
    while `free` is `f_bavail` (blocks THIS user may write), and the gap is
    the filesystem's root reserve — 5% by default, so ~200 GB on a 4 TB
    volume that the training box promised and no run could use. Reported from
    a real Linux install as the two tabs disagreeing; invisible on macOS,
    where APFS reports the two as equal, which is why this fakes a volume
    that does not.
    """
    from media_compost.train import gpu

    total = 4_000_000_000_000
    reserve = total // 20          # ext4's default 5%
    free = 300_000_000_000         # what this user may write
    used = total - (free + reserve)  # what disk_usage() derives from f_bfree

    usage = type("U", (), {"total": total, "used": used, "free": free})()
    monkeypatch.setattr("shutil.disk_usage", lambda _p: usage)
    # The sample is cached for a few seconds; both globals are patched so
    # teardown puts the real reading back rather than leaving this fake
    # volume in the cache for whatever runs next.
    monkeypatch.setattr(gpu, "_cached", [])
    monkeypatch.setattr(gpu, "_cached_at", 0.0)

    client, lib = lib_client
    stats = client.get("/api/library/stats").json()
    storage = client.get("/api/library/storage").json()
    assert stats["disk_free"] == storage["disk_free"] == free

    box = next(d for d in gpu.sample(lib.config.data_dir)
               if d["key"] == "system")
    row = {s["key"]: s["value"] for s in box["stats"]}
    assert row["disk_free"] == round(free / 2**30, 1)
    assert row["disk_total"] == round(total / 2**30, 1)
    # The trap the old spelling fell into: this is 200 GB more than free.
    assert row["disk_total"] - round(used / 2**30, 1) > row["disk_free"] + 150


# ---- backups from schema upgrades -------------------------------------------


def test_backups_are_reported_and_can_be_removed(lib_client):
    """The Storage page's one action on the "Everything else" list.

    It exists because the automatic pruning only runs after a SUCCESSFUL
    upgrade (`migrations.prune_backups`): a library that has not migrated
    since keeps every copy it ever made, and until this there was nothing in
    the app that could give the space back.
    """
    client, lib = lib_client
    backups = lib.config.backup_dir
    backups.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (backups / f"media-v1-2026010{i}-000000.db").write_bytes(b"x" * 1000)

    row = next(r for r in client.get("/api/library/storage").json()["other"]
               if r["key"] == "backups")
    assert row["count"] == 3 and row["bytes"] == 3000

    r = client.delete("/api/library/storage/backups")
    assert r.json() == {"ok": True, "deleted": 3, "bytes": 3000}
    assert not any(r["key"] == "backups"
                   for r in client.get("/api/library/storage").json()["other"])


def test_a_backup_sweep_takes_ONLY_what_it_recognises(lib_client):
    """The folder is the app's; what somebody put beside the backups is not.

    A sweep of the directory's contents is one line shorter and would take a
    note, a copy made by hand, or the `media.db` somebody parked there while
    debugging — and there is no way back from any of that.
    """
    client, lib = lib_client
    backups = lib.config.backup_dir
    backups.mkdir(parents=True, exist_ok=True)
    (backups / "media-v1-20260101-000000.db").write_bytes(b"x" * 10)
    stranger = backups / "my-own-copy.db"
    stranger.write_bytes(b"keep me")
    note = backups / "why.txt"
    note.write_text("the upgrade that went wrong", encoding="utf-8")

    assert client.delete("/api/library/storage/backups").json()["deleted"] == 1
    assert stranger.read_bytes() == b"keep me"
    assert note.exists()


# ---- the sidebar's own figures ---------------------------------------------


class _Statements:
    """Every SQL statement issued while the block runs."""

    def __init__(self, engine):
        self.engine, self.seen = engine, []

    def __enter__(self):
        sa_event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        sa_event.remove(self.engine, "before_cursor_execute", self._record)

    def _record(self, conn, cur, statement, params, context, many):
        self.seen.append(statement)

    def counted(self) -> list[str]:
        return [s for s in self.seen if "count(" in s.lower()]


def test_the_stats_are_cached_until_the_library_moves(lib_client):
    """Eight aggregates over the whole library — 0.6 s at a million items,
    asked on every load and after every write anything invalidates.

    The cache is not a TTL, so the assertions are about the TOKEN rather than
    about a clock: a repeat call counts nothing at all, and either kind of
    write — this process's own, or another connection's, which is what a CLI
    import beside the app is — makes the next call recount.
    """
    client, lib = lib_client
    first = client.get("/api/library/stats").json()

    with _Statements(lib.db.engine) as log:
        again = client.get("/api/library/stats").json()
    assert again == first
    assert log.counted() == [], log.counted()

    # A write through the app.
    assert client.post("/api/tags", json={"name": "fresh"}).status_code == 200
    with _Statements(lib.db.engine) as log:
        after = client.get("/api/library/stats").json()
    assert after["tags"] == first["tags"] + 1
    assert log.counted(), "a write must make the next call recount"

    # And a write from another connection entirely.
    with _Statements(lib.db.engine) as log:
        client.get("/api/library/stats")
    assert log.counted() == [], log.counted()
    raw = sqlite3.connect(str(lib.config.db_path))
    # `kind` says WHICH TAG SET the row belongs to (`db.TagRow`); the
    # lowercase name beside it is GENERATED, so nothing may write it.
    raw.execute("INSERT INTO tags (name, comment, kind) "
                "VALUES ('outside', '', 'lib')")
    raw.commit()
    raw.close()
    assert client.get("/api/library/stats").json()["tags"] == first["tags"] + 2


def test_a_READ_does_not_move_the_stats_token(lib_client):
    """Every request commits — the app commits before responding, whether or
    not the handler wrote — so a cache keyed on "how many commits" would be
    invalidated by the very browsing it exists to make cheap. `Database`
    counts only the commits that had something to flush.
    """
    client, lib = lib_client
    client.get("/api/library/stats")
    before = lib.db.commits
    for _ in range(3):
        client.get("/api/items?page=1&page_size=10")
        client.get("/api/groups")
    assert lib.db.commits == before
