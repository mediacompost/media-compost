"""A training job meets a library that keeps changing under it.

Two halves of one bug. A manifest is a list of stored library paths, built
once; merge two files of an item, delete one, or trash the picture outright
and the file the run was told to train on is not there any more. The job met
that as a FileNotFoundError from `Image.open` — at the first encode of a
resume, or partway through the caching pass of a run that was already going.

So: a resume ASKS THE QUERY AGAIN (and says in the timeline what came and
went), and the trainer treats a picture that is not there as one picture it
does not have rather than as the end of the run.
"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

import pytest

from media_compost.db import Item as _Item
from media_compost.importer import ImportOptions, Importer
from media_compost.ops import Ctx, items as ops_items, tagassign
from media_compost.testing import make_image
from media_compost.train import manager as manager_mod
from media_compost.train import paths as tp
from media_compost.train.spec import BucketConfig, DatasetQuery, TrainingConfig
from media_compost.ui.config import UiConfig
from media_compost.ui.server.deps import Library
from tests.train.conftest import loop_module as _loop_module


# ---- the trainer's side: a file that is not there any more ------------------


def _manifest(paths: list[Path]) -> dict:
    return {
        "items": [{"path": str(p), "bucket": 0} for p in paths],
        "groups": [{"weight": 1.0, "items": list(range(len(paths)))}],
        "val_items": [2],
        "stable_items": [1, 2],
        "buckets": [[64, 64]],
    }


def test_a_vanished_file_leaves_the_run_and_takes_nothing_with_it(tmp_path):
    """The entry stays where it is — every pool and both validation lists
    name it by POSITION — and is simply in nothing any more."""
    loop = _loop_module()
    files = [tmp_path / f"{i}.png" for i in range(3)]
    for f in files:
        make_image(f, 1, (64, 64))
    files[1].unlink()

    m = _manifest(files)
    pool, val, stable = m["groups"][0]["items"], m["val_items"], m["stable_items"]
    assert loop.vanished_entries(m) == [1]

    loop.drop_entries(m, {1})
    assert m["groups"][0]["items"] == [0, 2]
    assert m["val_items"] == [2] and m["stable_items"] == [2]
    assert m["items"][1]["missing"] is True
    # The run reads the pools and the two validation lists into locals of its
    # own before this is called, so the lists have to be the same objects.
    assert m["groups"][0]["items"] is pool
    assert m["val_items"] is val and m["stable_items"] is stable


def test_a_pool_left_empty_is_dropped_and_the_entries_stay_numbered(tmp_path):
    loop = _loop_module()
    files = [tmp_path / f"{i}.png" for i in range(3)]
    for f in files:
        make_image(f, 2, (64, 64))
    files[0].unlink()
    m = _manifest(files)
    m["groups"] = [{"weight": 1.0, "items": [0]}, {"weight": 1.0, "items": [1, 2]}]

    loop.drop_entries(m, set(loop.vanished_entries(m)))
    assert [g["items"] for g in m["groups"]] == [[1, 2]]
    assert len(m["items"]) == 3, "positions are the index every pool names"


def test_the_cache_pass_reports_an_unreadable_picture_instead_of_raising(
        tmp_path, monkeypatch):
    """The window the up-front sweep cannot cover: encoding a few hundred
    images takes minutes, and the library is in use throughout, so a picture
    can go WHILE the cache is being filled. One picture, and the run has the
    rest of them.

    `torch` is stubbed rather than imported: the encoding itself is not what
    is under test, and the main venv is torch-free by contract.
    """
    loop = _loop_module()
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        save=lambda blob, path: Path(path).write_bytes(b"latent")))

    class _IO:
        dir = tmp_path

        def check_control(self):
            pass

    src = loop.LatentSource.__new__(loop.LatentSource)
    src.items = [{"path": "/gone/a.png", "bucket": 0},
                 {"path": "/still/here.png", "bucket": 0},
                 {"path": "/gone/b.png", "bucket": 0, "missing": True}]
    src.io, src.dir = _IO(), tmp_path / "latents"
    src.cache, src.flip_p, src.alpha_mask = True, 0.0, False
    src.no_flip_tags = set()
    asked: list[str] = []

    def _encode(it, flipped):
        asked.append(it["path"])
        if it["path"].startswith("/gone"):
            raise FileNotFoundError(it["path"])
        return object(), None

    src._encode = _encode
    src._blob = lambda lat, mask: {}

    missing: list[int] = []
    src.prepare(on_missing=missing.append)
    assert missing == [0], "the one that could not be read, and only it"
    # The entry already marked was never opened, and the readable one was
    # cached as usual — the pass finished.
    assert asked == ["/gone/a.png", "/still/here.png"]
    assert (tmp_path / "latents" / "i00001.pt").is_file()


def test_the_run_sweeps_before_it_builds_anything_from_the_manifest(
        tmp_path, monkeypatch):
    """The sweep is wired into `run` itself, not only available beside it —
    and a run that has lost EVERY picture says so rather than starting on
    nothing.

    Driven with torch HIDDEN, which is the point of the test as much as the
    refusal is: `run` opened with `import torch`, so a refusal about the
    manifest — a dict, checked in microseconds — waited on several seconds of
    loading a library it does not need, and this test could only ever run on
    a machine that happened to have one. The main venv is torch-free by
    contract and CI's is torch-free in fact, so it failed there and nowhere
    else. `None` in `sys.modules` is how an import is refused without
    unloading anything a neighbouring test may be holding.
    """
    loop = _loop_module()
    monkeypatch.setitem(sys.modules, "torch", None)

    class _IO:
        dir = tmp_path

        def load_manifest(self):
            return _manifest([tmp_path / "gone.png"])

    with pytest.raises(ValueError, match="in the library any more"):
        loop.run(_IO(), {})


# ---- the manager's side: a resume asks the query again ----------------------


@pytest.fixture
def mgr(tmp_path: Path, monkeypatch):
    """A manager whose jobs never spawn anything: `_launch` is recorded.

    These tests are about the DATASET a run is handed, which is settled
    before the trainer is started — so the trainer is exactly the part that
    does not need to be there, and leaving it out is what keeps them off the
    `slow` mark that every other lifecycle test carries.
    """
    monkeypatch.setattr(manager_mod, "_TICK_SECONDS", 0.05)
    monkeypatch.setattr(manager_mod, "interpreter", lambda: sys.executable)
    launched: list[tuple[str, bool]] = []

    def _launch(self, uid, device, resume):
        launched.append((uid, resume))
        return True

    monkeypatch.setattr(manager_mod.TrainingManager, "_launch", _launch)

    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    src = tmp_path / "src"
    src.mkdir()
    for i in range(3):
        make_image(src / f"p{i}.png", i + 1, (96, 96))
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([src], ImportOptions())
    with lib.db.session() as s:
        for item in s.query(_Item).all():
            tagassign.stamp(Ctx(s, source="cli"), [item.id], ["photo"], [])
        s.commit()
    m = lib.training
    m.launched = launched
    m.lib = lib
    m.cfg = cfg
    return m


def _cfg() -> TrainingConfig:
    return TrainingConfig(
        model="sd15",
        hyper={"steps": 10, "checkpoint_every": 0},
        queries=[DatasetQuery(weight=1.0)],
        buckets=BucketConfig(skip_upscale=False),
    )


def _run_once(mgr, uid: str) -> None:
    """Queue the job and wait for the dataset thread to hand over."""
    before = len(mgr.launched)
    mgr.queue_run()
    end = time.time() + 30
    while time.time() < end and len(mgr.launched) == before:
        time.sleep(0.05)
    assert len(mgr.launched) > before, "the dataset thread never finished"


def _items_in(jd: Path) -> set[int]:
    data = json.loads(tp.manifest_path(jd).read_text(encoding="utf-8"))
    return {it["item_id"] for it in data["items"]}


def _events(jd: Path) -> list[dict]:
    text = tp.events_path(jd).read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def _interrupt(mgr, uid: str) -> None:
    """Put the job back in the queue with a resume point, as a pause does."""
    jd = tp.job_dir(mgr.dir, uid)
    (tp.checkpoints_dir(jd) / "last").mkdir(parents=True, exist_ok=True)
    with mgr._lock:
        rec = mgr._read(uid)
        rec["status"] = "queued"
        rec["step"] = 5
        mgr._write(uid, rec)
        # What `_finalize` does when a real run ends: the device is free
        # again, or the queue reads it as busy and starts nothing.
        mgr._on_device.pop(uid, None)


def test_a_resume_asks_the_query_again_and_says_what_moved(mgr, tmp_path):
    uid = mgr.create("run", _cfg(), "tester")
    mgr.enqueue(uid)
    _run_once(mgr, uid)
    jd = tp.job_dir(mgr.dir, uid)
    started_with = _items_in(jd)
    assert len(started_with) == 3

    _interrupt(mgr, uid)
    # The library moves on while the job waits: one picture goes, one arrives.
    gone = sorted(started_with)[0]
    with mgr.lib.db.session() as s:
        ops_items.trash(Ctx(s, source="cli"), [gone])
        s.commit()
    fresh = tmp_path / "later"
    fresh.mkdir()
    make_image(fresh / "new.png", 41, (96, 96))
    with mgr.lib.db.session() as s:
        Importer(s, mgr.lib.store, mgr.cfg).import_paths(
            [fresh], ImportOptions())
    with mgr.lib.db.session() as s:
        for item in s.query(_Item).filter(_Item.id.notin_(started_with)).all():
            tagassign.stamp(Ctx(s, source="cli"), [item.id], ["photo"], [])
        s.commit()

    _run_once(mgr, uid)
    assert mgr.launched[-1][1] is True, "it resumed"
    now = _items_in(jd)
    assert gone not in now and len(now) == 3

    marks = [e for e in _events(jd) if e["kind"] == "dataset"]
    assert len(marks) == 1
    assert marks[0]["data"] == {"added": 1, "removed": 1}
    assert marks[0]["step"] == 5


def test_a_resume_over_an_unchanged_library_says_nothing(mgr):
    """An event per resume reading "nothing changed" is a timeline nobody
    reads — and a first run has nothing to compare against at all."""
    uid = mgr.create("run", _cfg(), "tester")
    mgr.enqueue(uid)
    _run_once(mgr, uid)
    jd = tp.job_dir(mgr.dir, uid)
    assert not [e for e in _events(jd) if e["kind"] == "dataset"]

    _interrupt(mgr, uid)
    _run_once(mgr, uid)
    assert mgr.launched[-1][1] is True
    assert not [e for e in _events(jd) if e["kind"] == "dataset"]


def test_a_resume_does_not_hand_the_trainer_a_file_that_has_gone(mgr):
    """The reported failure: the manifest names a stored file, the file is
    merged or deleted away, and the resume opens it."""
    uid = mgr.create("run", _cfg(), "tester")
    mgr.enqueue(uid)
    _run_once(mgr, uid)
    jd = tp.job_dir(mgr.dir, uid)
    before = json.loads(tp.manifest_path(jd).read_text(encoding="utf-8"))
    doomed = Path(before["items"][0]["path"])
    assert doomed.is_file()

    _interrupt(mgr, uid)
    with mgr.lib.db.session() as s:
        ops_items.delete_items(Ctx(s, source="cli", _store=mgr.lib.store),
                               [before["items"][0]["item_id"]])
        s.commit()
    assert not doomed.exists(), "the stored file the manifest names is gone"
    _run_once(mgr, uid)

    after = json.loads(tp.manifest_path(jd).read_text(encoding="utf-8"))
    assert all(Path(it["path"]).exists() for it in after["items"])
    assert str(doomed) not in {it["path"] for it in after["items"]}
