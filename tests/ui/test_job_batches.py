"""One batch job for a whole import, and the pause that holds it there.

The queue used to make a job per enqueue call, and an import calls it once
per uploaded batch — so a folder of 4000 pictures produced twenty "Detecting
faces" rows, each with a progress bar covering a two-hundredth of the run.
`enqueue(merge=True)` folds them into the one job already doing it, which is
also what makes a single cursor (`Job.done_count`) mean something: how far
the whole run has got, what a pause resumes from, and what the per-item list
reads each item's state off.
"""

from __future__ import annotations

import json

from PIL import Image
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost.db import Item, Job
from media_compost.importer import Importer, ImportOptions
from media_compost.testing import make_image
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

MODEL = "insightface_buffalo_l"


class _Host:
    """A model host that finds nothing, and can be told to do something at
    the moment a chunk is handed to it (which is how a mid-run pause and a
    mid-run append are tested)."""

    def __init__(self):
        self.calls = 0
        self.on_chunk = None

    def run_batch(self, kind, model, images, ctx=None, options=None):
        self.calls += 1
        if self.on_chunk is not None:
            self.on_chunk(self.calls)
        return [[] for _ in images]

    def run(self, kind, model, image, ctx=None, options=None):
        return []


@pytest.fixture
def lib_client(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    # `make_image` and not a flat fill: a solid colour is exactly the
    # spectrally featureless case the perceptual hash degenerates on, so ten
    # of them fold into one item and the batch under test is one row long.
    for n in range(10):
        make_image(tmp_path / f"p{n}.png", seed=n)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            sorted(tmp_path.glob("p*.png")), ImportOptions(folders_as_groups=False))
    # No worker thread: these tests drive `run_one` themselves so the chunk
    # boundaries are theirs to stand on. Left running, the queue's own thread
    # picks the same job up and the two race — which shows up as the second
    # run tripping over the first's per-item run records.
    lib.jobs._ensure_worker = lambda: None
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _ids(lib) -> list[int]:
    with lib.db.session() as s:
        return list(s.execute(select(Item.id).order_by(Item.id)).scalars().all())


def _job(lib, jid: int) -> Job:
    with lib.db.session() as s:
        job = s.get(Job, jid)
        s.expunge(job)
        return job


def _chunk(lib, n: int) -> None:
    """Chunks of ``n`` for the faces job under test: `faces` has its own
    entry beside the generic `_TAG_BATCH` (`_KIND_BATCH`), and the
    progress endpoint reads the same `_batch_for`."""
    lib.jobs._TAG_BATCH = n
    lib.jobs._KIND_BATCH = {**lib.jobs._KIND_BATCH, "faces": n}


def _run(lib, jid: int) -> str:
    """Run one job the way the worker does, minus the thread."""
    with lib.db.session() as s:
        job = s.get(Job, jid)
        job.status = "running"
        s.commit()
    out = lib.jobs.run_one(jid)
    with lib.db.session() as s:
        job = s.get(Job, jid)
        job.status = ("paused" if out.startswith("paused")
                      else "canceled" if out.startswith("canceled") else "done")
        s.commit()
    lib.jobs._paused.discard(jid)
    return out


def test_merge_folds_every_import_batch_into_one_job(lib_client):
    _, lib = lib_client
    ids = _ids(lib)
    first = lib.jobs.enqueue("faces", MODEL, ids[:4], merge=True)
    second = lib.jobs.enqueue("faces", MODEL, ids[4:8], merge=True)
    assert first == second, "the second batch made a job of its own"
    with lib.db.session() as s:
        job = s.get(Job, first[0])
        assert json.loads(job.item_ids) == ids[:8]
        assert s.execute(select(Job)).scalars().all() == [job]

    # An item already in the list is not queued twice — an import re-offers
    # what it matched, and a job that ran a picture again would report a
    # total nobody could reconcile with the library.
    lib.jobs.enqueue("faces", MODEL, ids[:6], merge=True)
    with lib.db.session() as s:
        assert json.loads(s.get(Job, first[0]).item_ids) == ids[:8]


def test_without_merge_a_second_request_is_a_second_job(lib_client):
    """Off by default: a person pressing Detect faces twice means two tasks,
    and one silently swallowing the other would be a request with nowhere to
    watch it."""
    _, lib = lib_client
    ids = _ids(lib)
    a = lib.jobs.enqueue("faces", MODEL, ids[:4])
    b = lib.jobs.enqueue("faces", MODEL, ids[4:8])
    assert a != b


def test_a_running_job_picks_up_what_is_appended_to_it(lib_client):
    """The list can GROW under the loop — that is the whole point of merging
    an import's batches — so "how many are there" is asked again at every
    chunk boundary rather than counted once at the start."""
    _, lib = lib_client
    ids = _ids(lib)
    host = _Host()
    lib._model_host = host
    _chunk(lib, 2)
    jid = lib.jobs.enqueue("faces", MODEL, ids[:4], merge=True)[0]

    def append_once(call):
        if call == 1:
            lib.jobs.enqueue("faces", MODEL, ids[4:], merge=True)

    host.on_chunk = append_once
    msg = _run(lib, jid)
    assert msg.endswith(f"of {len(ids)} items"), msg
    assert _job(lib, jid).done_count == len(ids)


def test_a_pause_stops_at_a_boundary_and_a_resume_finishes_the_rest(lib_client):
    client, lib = lib_client
    ids = _ids(lib)
    host = _Host()
    lib._model_host = host
    _chunk(lib, 2)
    jid = lib.jobs.enqueue("faces", MODEL, ids, merge=True)[0]

    host.on_chunk = lambda call: (client.post(f"/api/ml/jobs/{jid}/pause")
                                  if call == 2 else None)
    msg = _run(lib, jid)
    assert msg.startswith("paused"), msg
    job = _job(lib, jid)
    # Two chunks of two are committed; the run stopped before the third.
    assert job.done_count == 4
    assert job.status == "paused"
    assert job.finished_at is None, "a paused job has not finished"

    # It is still in the list, and it is not the queue's next job.
    rows = client.get("/api/ml/jobs").json()["jobs"]
    row = next(r for r in rows if r["id"] == jid)
    assert row["status"] == "paused" and row["done_count"] == 4
    assert lib.jobs._next_queued_id() is None

    assert client.post(f"/api/ml/jobs/{jid}/resume").status_code == 200
    assert lib.jobs._next_queued_id() == jid
    host.on_chunk = None
    assert _run(lib, jid).endswith(f"of {len(ids)} items")
    assert _job(lib, jid).done_count == len(ids)


def test_a_running_single_item_job_is_not_pausable(lib_client):
    """There is no boundary inside one model run to stop at, and stopping
    between "the model answered" and "the answer was applied" would throw the
    expensive half away."""
    client, lib = lib_client
    iid = _ids(lib)[0]
    with lib.db.session() as s:
        job = Job(kind="depth", model="depth_anything_v2_small", item_id=iid,
                  status="running")
        s.add(job); s.commit(); jid = job.id
    assert client.post(f"/api/ml/jobs/{jid}/pause").status_code == 400
    rows = client.get("/api/ml/jobs").json()["jobs"]
    assert next(r for r in rows if r["id"] == jid)["pausable"] is False


def test_the_progress_list_says_what_happened_to_each_item(lib_client):
    client, lib = lib_client
    ids = _ids(lib)
    _chunk(lib, 2)
    with lib.db.session() as s:
        job = Job(kind="faces", model=MODEL, item_id=ids[0],
                  item_ids=json.dumps(ids), status="running", done_count=3)
        s.add(job); s.commit(); jid = job.id
    body = client.get(f"/api/ml/jobs/{jid}/progress").json()
    assert body["total"] == len(ids) and body["done"] == 3
    states = [i["status"] for i in body["items"]]
    assert states[:3] == ["done"] * 3
    # The chunk being worked on right now, and everything after it waiting.
    assert states[3:5] == ["running", "running"]
    assert set(states[5:]) == {"pending"}
    assert all(i["name"] for i in body["items"]), "names come with the ids"

    # Windowed: a batch can cover a whole library.
    page = client.get(f"/api/ml/jobs/{jid}/progress?offset=8&limit=2").json()
    assert page["offset"] == 8 and [i["id"] for i in page["items"]] == ids[8:10]


def test_ONE_job_for_a_selection_whatever_the_kind(lib_client):
    """A selection is one task to watch, pause and cancel — for captioning
    and for every other model kind, not only for the five whose model call
    can take a chunk of pictures at once.

    It used to be a job PER ITEM for those kinds, so captioning a hundred
    pictures was a hundred rows in the task list, each with a progress bar
    covering a hundredth of the run.
    """
    _, lib = lib_client
    ids = _ids(lib)
    for kind, model in (("caption", "florence2_base"),
                        ("upscale", "swin2sr_x2"),
                        ("depth", "depth_anything_v2_small")):
        jobs = lib.jobs.enqueue(kind, model, ids[:4])
        assert len(jobs) == 1, f"{kind} made {len(jobs)} jobs for one selection"
        with lib.db.session() as s:
            row = s.get(Job, jobs[0])
            assert json.loads(row.item_ids) == ids[:4]
        # And pressing the same action again is a SECOND task, never an
        # append: two requests mean two things to watch.
        again = lib.jobs.enqueue(kind, model, ids[4:8])
        assert again != jobs


def test_a_multi_item_job_of_any_kind_is_pausable(lib_client):
    """The boundary a pause stops at is between two ITEMS, which every
    multi-item job now has — where `pausable` used to be false for anything
    outside the five model-batch kinds."""
    client, lib = lib_client
    jid = lib.jobs.enqueue("caption", "florence2_base", _ids(lib)[:4])[0]
    with lib.db.session() as s:
        s.get(Job, jid).status = "running"
        s.commit()
    rows = client.get("/api/ml/jobs").json()["jobs"]
    assert next(r for r in rows if r["id"] == jid)["pausable"] is True
    assert client.post(f"/api/ml/jobs/{jid}/pause").status_code == 200


def test_one_item_that_fails_does_not_sink_the_rest_of_the_run(lib_client):
    """A selection of two hundred must not end on the one picture something
    could not open — the rule the panels page walk already followed."""
    _, lib = lib_client
    ids = _ids(lib)[:4]
    seen: list[int] = []

    class _Flaky:
        def run(self, kind, model, image, ctx=None, options=None):
            seen.append(len(seen))
            if len(seen) == 2:
                raise RuntimeError("cannot read this one")
            return "a caption"

    lib._model_host = _Flaky()
    jid = lib.jobs.enqueue("caption", "florence2_base", ids)[0]
    msg = _run(lib, jid)
    assert len(seen) == 4, "the run stopped at the failure"
    assert msg == "captioned 3 of 4 items", msg


class _PathsHost:
    """A stand-in with the real host's batch door: `submit_paths` returns a
    handle, and the CALL ORDER is recorded — what the pipeline is."""

    def __init__(self, fail_index=None):
        self.log: list[str] = []
        self.fail_index = fail_index
        self.n = 0

    def submit_paths(self, task, model_id, paths, ctx=None, max_dim=0,
                     prefetch=(), options=None):
        self.n += 1
        n = self.n
        self.log.append(f"submit{n}")
        assert all(isinstance(p, str) for p in paths), paths
        assert max_dim == 2048, "faces decode at their own cap, on both paths"
        host = self

        class _H:
            errors = []

            def result(_):
                host.log.append(f"result{n}")
                out = [[] for _ in paths]
                if host.fail_index is not None and n == 1:
                    out[host.fail_index] = None
                    _.errors = [(host.fail_index, "cannot read this one")]
                return out
        return _H()

    def run(self, kind, model, image, ctx=None, options=None):
        return []


def test_the_next_chunk_is_on_its_way_before_the_last_one_is_written(lib_client, monkeypatch):
    """The pipeline: chunk N+1 is submitted BEFORE chunk N's answer is
    collected and applied, so the host's writes overlap the worker's
    forward; and every few chunks the loop drains, giving the host's lock
    back to anyone else wanting a model."""
    _, lib = lib_client
    ids = _ids(lib)
    host = _PathsHost()
    lib._model_host = host
    _chunk(lib, 2)
    monkeypatch.setattr(lib.jobs, "_PIPELINE_WINDOW", 3)
    jid = lib.jobs.enqueue("faces", MODEL, ids, merge=True)[0]
    msg = _run(lib, jid)
    assert msg.endswith(f"of {len(ids)} items"), msg
    assert _job(lib, jid).done_count == len(ids)
    chunks = (len(ids) + 1) // 2
    assert host.n == chunks
    # Two on the wire at most, and the second is out before the first is in.
    assert host.log[:3] == ["submit1", "submit2", "result1"]
    # The window's end drains: chunk 3 is collected before chunk 4 is sent.
    assert host.log.index("result3") < host.log.index("submit4")
    # Every chunk's answer is collected exactly once, in order.
    results = [e for e in host.log if e.startswith("result")]
    assert results == [f"result{k}" for k in range(1, chunks + 1)]


def test_a_slot_the_worker_could_not_read_does_not_sink_the_chunk(lib_client, capsys):
    _, lib = lib_client
    ids = _ids(lib)
    lib._model_host = _PathsHost(fail_index=1)
    _chunk(lib, 4)
    jid = lib.jobs.enqueue("faces", MODEL, ids, merge=True)[0]
    msg = _run(lib, jid)
    assert msg.endswith(f"of {len(ids)} items"), msg
    assert _job(lib, jid).done_count == len(ids)
    assert f"faces failed for item {ids[1]}: cannot read this one" in capsys.readouterr().err


class _PictureHost:
    """A stand-in with the real host's batch door for a PICTURE kind: each
    `submit_paths(images=True)` answers a small image, and the call order
    is recorded."""

    def __init__(self):
        self.log: list[str] = []
        self.n = 0
        self.options: list[dict] = []

    def submit_paths(self, task, model_id, paths, ctx=None, max_dim=0,
                     prefetch=(), options=None, images=False):
        self.n += 1
        n = self.n
        assert images and len(paths) == 1, "a per-item kind sends one picture and wants one back"
        self.log.append(f"submit{n}")
        self.options.append(dict(options or {}))
        host = self

        class _H:
            errors = []

            def result(_):
                host.log.append(f"result{n}")
                return [Image.new("RGB", (16, 16), (n * 10 % 255, 0, 0))]
        return _H()

    def run(self, kind, model, image, ctx=None, options=None):
        raise AssertionError("the per-item pipeline must not fall back to run()")


def test_a_per_item_kind_rides_the_pipeline_and_lands_its_pictures(lib_client, monkeypatch):
    """A depth map per picture: the next item is submitted BEFORE the last
    one's map is stored, and every map lands as a control artifact."""
    from sqlalchemy import select as _select

    from media_compost.db import FileArtifact

    _, lib = lib_client
    ids = _ids(lib)[:5]
    host = _PictureHost()
    lib._model_host = host
    monkeypatch.setattr(lib.jobs, "_PIPELINE_WINDOW", 3)
    jid = lib.jobs.enqueue("depth", "depth_anything_v2_small", ids)[0]
    msg = _run(lib, jid)
    assert msg == f"estimated depth for {len(ids)} of {len(ids)} items", msg
    assert host.log[:3] == ["submit1", "submit2", "result1"]
    assert host.log.index("result3") < host.log.index("submit4"), "the window drains"
    with lib.db.session() as s:
        made = s.execute(_select(FileArtifact.item_id).where(
            FileArtifact.kind == "depth")).scalars().all()
    assert sorted(made) == sorted(ids)
    assert _job(lib, jid).done_count == len(ids)


def test_a_cancel_drops_the_answer_that_was_in_flight(lib_client):
    """The rule `_run_one_item` keeps: a cancel that arrives while the model
    is running drops that answer rather than landing it and then claiming
    "canceled" over a freshly written file."""
    from sqlalchemy import select as _select

    from media_compost.db import FileArtifact

    client, lib = lib_client
    ids = _ids(lib)[:4]
    host = _PictureHost()
    lib._model_host = host
    jid = lib.jobs.enqueue("depth", "depth_anything_v2_small", ids)[0]

    real_submit = host.submit_paths

    def cancel_on_second(*a, **kw):
        h = real_submit(*a, **kw)
        if host.n == 2:
            client.post(f"/api/ml/jobs/{jid}/cancel")
        return h
    host.submit_paths = cancel_on_second
    msg = _run(lib, jid)
    assert msg.startswith("canceled"), msg
    with lib.db.session() as s:
        made = s.execute(_select(FileArtifact.item_id).where(
            FileArtifact.kind == "depth")).scalars().all()
    # The first item's map landed before the cancel; the second's answer was
    # in flight and is dropped; nothing after it is asked for.
    assert made == [ids[0]]
    assert host.n == 2
