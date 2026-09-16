"""AI job queue: background removal, captioning, tagging, and the pending flow.

The real model backends (JoyCaption, Florence-2, withoutBG) need heavy
optional dependencies that aren't installed in CI, so they report as
``unavailable``. To exercise the enqueue → apply → pending → approve pipeline
end to end without them, these tests feed *synthetic* model results straight to
the ``JobQueue._apply_*`` methods (the same code the worker runs once a model
returns). A separate test confirms an unavailable model fails gracefully."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from media_compost.hub import cache as hubcache
from media_compost.ui.plugins import registry
from media_compost.ui.config import UiConfig
from media_compost.db import (
    File, Item, ItemTag, ItemTagBox, ItemTagGroup, ItemTagPlacement, Job, Tag,
)
from media_compost.importer import Importer, ImportOptions
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
            [src], ImportOptions(folders_as_groups=False)
        )
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _item_id(lib) -> int:
    with lib.db.session() as s:
        return s.execute(select(Item.id)).scalars().first()


def _all_item_ids(lib) -> list[int]:
    with lib.db.session() as s:
        return list(s.execute(select(Item.id)).scalars().all())


def _apply_bg(lib, iid: int) -> None:
    """Apply a synthetic transparent RGBA result (as a model would return)."""
    with lib.db.session() as s:
        item = s.get(Item, iid)
        out = Image.new("RGBA", (120, 120), (10, 10, 10, 0))
        ImageDraw.Draw(out).ellipse([30, 30, 90, 90], fill=(200, 30, 30, 255))
        lib.jobs._apply_bg(s, item, out)
        s.commit()


def _apply_caption(lib, iid: int, text: str, model: str = "") -> None:
    with lib.db.session() as s:
        item = s.get(Item, iid)
        lib.jobs._apply_caption(s, item, text, model)
        s.commit()


def _tag(name: str, box=None) -> dict:
    """A synthetic tag result as the model worker returns it (plain dict)."""
    return {"name": name, "box": list(box) if box is not None else None}


def _apply_tags(lib, iid: int, results, model: str = "florence2_base:od") -> str:
    with lib.db.session() as s:
        item = s.get(Item, iid)
        msg = lib.jobs._apply_tags(s, item, results, model)
        s.commit()
        return msg


def test_models_endpoint_lists_real_models_with_install_help(lib_client):
    client, _ = lib_client
    out = client.get("/api/ml/models").json()
    by_kind = {t["kind"]: t for t in out["tasks"]}
    # The fixed tasks are all present with UI metadata.
    assert set(by_kind) == {"bg_removal", "watermark_removal", "text_removal", "tag", "caption",
                            "depth", "pose", "canny", "lineart", "panels", "upscale",
                            "restore", "colorize", "descreen", "faces",
                            "ocr", "embed", "watermark_detect"}
    for t in out["tasks"]:
        assert t["label"] and t["icon"] and t["result"]
    for kind in ("bg_removal", "caption", "tag", "depth", "pose", "canny", "lineart"):
        assert by_kind[kind]["models"], f"no models for {kind}"
        for m in by_kind[kind]["models"]:
            # Real models carry a reference URL for the "set up" help overlay,
            # whether or not they're currently available. (It asserted on
            # `install` prose too, until that overlay stopped showing any.)
            assert m["url"]


def test_bg_removal_adds_transparent_active_file(lib_client):
    _, lib = lib_client
    iid = _item_id(lib)
    _apply_bg(lib, iid)
    with lib.db.session() as s:
        files = s.execute(select(File).where(File.item_id == iid)).scalars().all()
        assert len(files) == 2  # original + background-removed
        item = s.get(Item, iid)
        active = s.get(File, item.active_file_id)
        assert active.format == "webp" and active.is_derived
        # Action-generated files carry no imported-filename card (only imports do).
        from media_compost.db import FileName
        names = s.execute(
            select(FileName).where(FileName.file_id == active.id)
        ).scalars().all()
        assert names == []
        path = lib.store.path_of(s, active)
    with Image.open(path) as im:
        assert im.mode == "RGBA"
        assert im.getextrema()[3][0] == 0  # some fully-transparent pixels


def test_a_result_lands_on_the_item_and_makes_no_second_one(lib_client):
    """THE RESULT IS A SOURCE FILE ON THE ITEM THE ACTION RAN ON — always.

    There used to be a "Create new item for result" toggle that put it in an
    item of its own instead, linked back by an `edit` relationship and
    carrying a copy of the source's groups, tags and captions. It is gone
    (owner 2026-09), and this is the ratchet: an applier that started making
    items again would be inventing a second place to look for what an action
    did, which is the whole of why it went.
    """
    from media_compost.db import Relationship

    client, lib = lib_client
    iid = _item_id(lib)
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "dog", "negative": False})
    with lib.db.session() as s:
        before = s.execute(select(Item.id)).scalars().all()
        item = s.get(Item, iid)
        out = Image.new("RGBA", (120, 120), (10, 10, 10, 0))
        ImageDraw.Draw(out).ellipse([30, 30, 90, 90], fill=(200, 30, 30, 255))
        lib.jobs._apply_bg(s, item, out)
        s.commit()
    with lib.db.session() as s:
        assert s.execute(select(Item.id)).scalars().all() == before
        assert s.execute(select(Relationship)).scalars().all() == []
        files = s.execute(select(File).where(File.item_id == iid)).scalars().all()
        assert len(files) == 2
        active = s.get(File, s.get(Item, iid).active_file_id)
        assert active.is_derived and active.format == "webp"


def test_watermark_removal_adds_active_file_in_place(lib_client):
    _, lib = lib_client
    iid = _item_id(lib)
    out = Image.new("RGB", (120, 120), (40, 40, 40))
    with lib.db.session() as s:
        item = s.get(Item, iid)
        msg = lib.jobs._apply_watermark(s, item, out)
        s.commit()
    assert msg == "watermark removed"
    with lib.db.session() as s:
        files = s.execute(select(File).where(File.item_id == iid)).scalars().all()
        assert len(files) == 2  # original + cleaned
        active = s.get(File, s.get(Item, iid).active_file_id)
        assert active.format == "webp" and active.is_derived


def test_text_removal_applies_like_watermark(lib_client):
    """text_removal: a returned image becomes the new active source; a None
    result (nothing had been read, so nothing was painted out) is a warning
    and changes nothing."""
    _, lib = lib_client
    iid = _item_id(lib)
    out = Image.new("RGB", (120, 120), (40, 40, 40))
    with lib.db.session() as s:
        item = s.get(Item, iid)
        msg = lib.jobs._apply_text(s, item, out)
        s.commit()
    assert msg == "text removed"
    with lib.db.session() as s:
        files = s.execute(select(File).where(File.item_id == iid)).scalars().all()
        assert len(files) == 2  # original + cleaned
        active = s.get(File, s.get(Item, iid).active_file_id)
        assert active.format == "webp" and active.is_derived
    with lib.db.session() as s:
        item = s.get(Item, iid)
        assert lib.jobs._apply_text(s, item, None) == "no text found to remove"


def test_watermark_removal_none_leaves_item_untouched(lib_client):
    _, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        item = s.get(Item, iid)
        msg = lib.jobs._apply_watermark(s, item, None)   # detector found nothing
        s.commit()
    assert msg == "no watermark detected"
    with lib.db.session() as s:
        files = s.execute(select(File).where(File.item_id == iid)).scalars().all()
        assert len(files) == 1  # unchanged


def test_upscale_adds_higher_res_derived_file(lib_client):
    """Upscaling adds the (larger) result as a new active derived source file."""
    _, lib = lib_client
    iid = _item_id(lib)
    out = Image.new("RGB", (600, 600), (30, 30, 30))   # a 2x "upscaled" result
    with lib.db.session() as s:
        item = s.get(Item, iid)
        msg = lib.jobs._apply_upscale(s, item, out)
        s.commit()
    assert msg == "upscaled"
    with lib.db.session() as s:
        files = s.execute(select(File).where(File.item_id == iid)).scalars().all()
        assert len(files) == 2  # original (300) + upscaled (600)
        active = s.get(File, s.get(Item, iid).active_file_id)
        assert active.is_derived and active.width == 600 and active.format == "webp"


class _StubHost:
    """A ModelHost stand-in that returns a fixed image without loading a model."""
    def __init__(self, result):
        self._result = result

    def run(self, kind, model, image, ctx, options=None):
        return self._result


def _queue_watermark_job(lib, iid, model) -> int:
    with lib.db.session() as s:
        job = Job(kind="watermark_removal", model=model, item_id=iid,
                  status="queued")
        s.add(job)
        s.commit()
        return job.id


def _watermark_tag(lib, iid):
    with lib.db.session() as s:
        tag = s.execute(select(Tag).where(Tag.name == "watermark")).scalars().first()
        if tag is None:
            return None
        return s.execute(select(ItemTag).where(
            ItemTag.item_id == iid, ItemTag.tag_id == tag.id
        )).scalars().first()


def test_watermark_boxes_flips_watermark_tag_negative(lib_client):
    """A box-driven in-place removal flips the item's positive `watermark` tag to
    a negative assignment (the item is now watermark-free)."""
    client, lib = lib_client
    iid = _item_id(lib)
    # The item has a positive `watermark` tag (as the box variant requires).
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "watermark", "negative": False})
    assert _watermark_tag(lib, iid).negative is False

    lib._model_host = _StubHost(Image.new("RGB", (120, 120), (40, 40, 40)))
    jid = _queue_watermark_job(lib, iid, "yolo11x_lama:boxes")
    lib.jobs.run_one(jid)

    it = _watermark_tag(lib, iid)
    assert it is not None and it.negative is True          # flipped
    # The cleaned image was applied in place (original + cleaned).
    with lib.db.session() as s:
        assert len(s.execute(select(File).where(File.item_id == iid)).scalars().all()) == 2


def test_watermark_detector_variant_does_not_flip_tag(lib_client):
    """The auto-detector variant (not `:boxes`) doesn't touch the watermark tag."""
    client, lib = lib_client
    iid = _item_id(lib)
    client.post(f"/api/tags/assign/item/{iid}", json={"tag": "watermark", "negative": False})

    lib._model_host = _StubHost(Image.new("RGB", (120, 120), (40, 40, 40)))
    jid = _queue_watermark_job(lib, iid, "yolo11x_lama")     # detector, no :boxes
    lib.jobs.run_one(jid)

    assert _watermark_tag(lib, iid).negative is False       # unchanged


def _queue_artifact_job(lib, iid, kind, model) -> int:
    with lib.db.session() as s:
        job = Job(kind=kind, model=model, item_id=iid, status="queued")
        s.add(job)
        s.commit()
        return job.id


def test_cancel_all_cancels_queued_and_flags_running(lib_client):
    """cancel_all marks every queued job canceled and flags running ones for
    cooperative cancellation."""
    client, lib = lib_client
    iid = _item_id(lib)
    q1 = _queue_artifact_job(lib, iid, "depth", "depth_anything_v2_small")
    q2 = _queue_artifact_job(lib, iid, "canny", "canny")
    # A third job, forced to "running" to check it gets flagged (not touched in DB).
    with lib.db.session() as s:
        rj = Job(kind="pose", model="yolo11n_pose", item_id=iid, status="running")
        s.add(rj); s.commit(); rid = rj.id

    n = lib.jobs.cancel_all()
    assert n == 3
    with lib.db.session() as s:
        assert s.get(Job, q1).status == "canceled"
        assert s.get(Job, q2).status == "canceled"
        # Running job stays "running" in the DB but is flagged for cancellation.
        assert s.get(Job, rid).status == "running"
    assert rid in lib.jobs._canceled

    # The cancel-all endpoint works too.
    q3 = _queue_artifact_job(lib, iid, "lineart", "lineart")
    r = client.post("/api/ml/jobs/cancel-all")
    assert r.json()["ok"] is True and r.json()["count"] >= 1
    with lib.db.session() as s:
        assert s.get(Job, q3).status == "canceled"


def test_job_items_answers_the_batch_list_or_the_single_item(lib_client):
    """`GET /api/ml/jobs/{id}/items`: the recorded batch list when there is
    one, else the single item — what lets a failed job's ⋯ menu select the
    job's items in the library (JobOut deliberately carries only a batch's
    first item)."""
    client, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        batch = Job(kind="tag", model="wd_tagger", item_id=iid,
                    item_ids=json.dumps([iid, iid + 999]), status="failed")
        single = Job(kind="depth", model="depth_anything_v2_small",
                     item_id=iid, status="failed")
        s.add_all([batch, single]); s.commit()
        bid, sid = batch.id, single.id
    assert client.get(f"/api/ml/jobs/{bid}/items").json() == {
        "item_ids": [iid, iid + 999]}
    assert client.get(f"/api/ml/jobs/{sid}/items").json() == {
        "item_ids": [iid]}
    assert client.get("/api/ml/jobs/999999/items").status_code == 404


def test_colorize_job_applies_result_and_reference_flow(lib_client):
    """A colorize job stores the model's image like the other image actions,
    and a reference id round-trips: upload → list → job options carry it."""
    client, lib = lib_client
    iid = _item_id(lib)

    # Upload a reference image into the rolling refs store.
    import io as _io
    buf = _io.BytesIO()
    Image.new("RGB", (64, 64), (30, 160, 90)).save(buf, "PNG")
    r = client.post("/api/ml/refs",
                    files={"image": ("ref.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    ref_id = r.json()["id"]
    listed = client.get("/api/ml/refs").json()["refs"]
    assert any(e["id"] == ref_id for e in listed)
    assert client.get(f"/api/ml/refs/{ref_id}").status_code == 200
    # Unknown / non-PNG ids are rejected (ids are basename-only, so a
    # traversal-y id can never resolve outside the refs store).
    assert client.get("/api/ml/refs/zzzz.png").status_code == 404
    assert client.get("/api/ml/refs/media.db").status_code == 404

    # Snapshot an item as a reference too, then delete it again.
    r2 = client.post(f"/api/ml/refs/from-item/{iid}")
    assert r2.status_code == 200 and r2.json()["id"] != ref_id
    snap_id = r2.json()["id"]
    assert client.delete(f"/api/ml/refs/{snap_id}").json()["ok"] is True
    left = [e["id"] for e in client.get("/api/ml/refs").json()["refs"]]
    assert snap_id not in left and ref_id in left
    assert client.delete(f"/api/ml/refs/{snap_id}").status_code == 404

    # Enqueue with the reference; the job stores it in its options JSON.
    r3 = client.post("/api/ml/jobs", json={
        "kind": "colorize", "model": "color2manga_gray",
        "item_ids": [iid], "reference": ref_id,
    })
    assert r3.status_code == 200
    jid = r3.json()["job_ids"][0]
    with lib.db.session() as s:
        job = s.get(Job, jid)
        assert json.loads(job.options)["reference"] == ref_id
        # Keep the worker from racing this test; apply via run_one below.
        job.status = "running"
        s.commit()

    # The model result is applied like any other image action.
    lib._model_host = _StubHost(Image.new("RGB", (300, 300), (120, 80, 40)))
    msg = lib.jobs.run_one(jid)
    assert msg == "colorized"
    with lib.db.session() as s:
        item = s.get(Item, iid)
        active = s.get(File, item.active_file_id)
        assert active.is_derived and active.phash
    # An unknown reference id is rejected at enqueue.
    bad = client.post("/api/ml/jobs", json={
        "kind": "colorize", "model": "color2manga_gray",
        "item_ids": [iid], "reference": "nope.png",
    })
    assert bad.status_code == 400


def test_cancel_during_run_discards_result(lib_client):
    """A cancel that lands while the model is running must NOT apply the
    result: run_one drops it (no new items/files) and reports "canceled"
    (regression: panel detection used to add all its items and then show the
    job as canceled)."""
    client, lib = lib_client
    iid = _item_id(lib)
    lib._model_host = _StubHost([[0.0, 0.0, 0.5, 1.0], [0.5, 0.0, 0.5, 1.0]])
    with lib.db.session() as s:
        job = Job(kind="panels", model="magiv3_panels", item_id=iid,
                  status="running")
        s.add(job); s.commit(); jid = job.id
    n0 = len(_all_item_ids(lib))
    lib.jobs._canceled.add(jid)
    msg = lib.jobs.run_one(jid)
    assert msg == "canceled"
    assert len(_all_item_ids(lib)) == n0     # nothing was created


def test_job_progress_is_reported(lib_client):
    """A job's live progress is written in its own transaction and surfaces in the
    job list."""
    client, lib = lib_client
    iid = _item_id(lib)
    jid = _queue_artifact_job(lib, iid, "depth", "depth_anything_v2_small")
    lib.jobs._set_progress(jid, 40, "Detecting panels — page 2 / 5")
    with lib.db.session() as s:
        job = s.get(Job, jid)
        assert job.progress == 40 and "page 2 / 5" in job.message
    # And it's serialized in the /jobs list.
    with lib.db.session() as s:
        s.get(Job, jid).status = "running"; s.commit()
    row = next(j for j in client.get("/api/ml/jobs").json()["jobs"] if j["id"] == jid)
    assert row["progress"] == 40


class _TagStubHost:
    """A ModelHost stand-in that returns a fixed tag list for every image."""
    def __init__(self, tags):
        self._tags = tags

    def run(self, kind, model, image, ctx, options=None):
        return list(self._tags)


def test_multi_item_tag_runs_as_one_job_over_all_items(lib_client, tmp_path, monkeypatch):
    """Tagging a multi-item selection creates ONE job (not one per item) that runs
    the model over every item and reports progress; single items stay per-job."""
    client, lib = lib_client
    # The base fixture seeds one item; add two more so the batch spans several.
    for seed in (60, 120):
        im = Image.new("RGB", (300, 300), (seed, seed, seed))
        p = tmp_path / f"extra{seed}.png"
        im.save(p, "PNG")
        with lib.db.session() as s:
            Importer(s, lib.store, lib.config).import_paths(
                [p], ImportOptions(folders_as_groups=False))
    ids = _all_item_ids(lib)
    assert len(ids) >= 3
    # Don't let the background worker also pick the job up — run it explicitly.
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    job_ids = lib.jobs.enqueue("tag", "wd_tagger", ids)
    assert len(job_ids) == 1                      # consolidated into one task
    jid = job_ids[0]
    with lib.db.session() as s:
        assert json.loads(s.get(Job, jid).item_ids) == list(ids)

    # A single-item tag request stays a plain per-item job (no item_ids marker).
    single = lib.jobs.enqueue("tag", "wd_tagger", [ids[0]])
    assert len(single) == 1
    with lib.db.session() as s:
        assert s.get(Job, single[0]).item_ids is None

    lib._model_host = _TagStubHost([_tag("cat"), _tag("dog")])
    msg = lib.jobs.run_one(jid)
    assert msg == f"tagged {len(ids)} of {len(ids)} items"
    with lib.db.session() as s:
        for iid in ids:
            n = len(s.execute(
                select(ItemTag).where(ItemTag.item_id == iid)).scalars().all())
            assert n >= 2                         # both pending tags landed
        assert s.get(Job, jid).progress == 100


def test_multi_item_face_detection_runs_as_one_job_too(lib_client, tmp_path, monkeypatch):
    """Detecting faces across a selection (or a whole import) is one task with a
    progress bar, for the same reason tagging is: one model load, one small
    result per item."""
    from media_compost.db import Face

    client, lib = lib_client
    for seed in (70, 140):
        im = Image.new("RGB", (300, 300), (seed, seed, seed))
        p = tmp_path / f"face{seed}.png"
        im.save(p, "PNG")
        with lib.db.session() as s:
            Importer(s, lib.store, lib.config).import_paths(
                [p], ImportOptions(folders_as_groups=False))
    ids = _all_item_ids(lib)
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    job_ids = lib.jobs.enqueue("faces", "anime_face", ids)
    assert len(job_ids) == 1
    jid = job_ids[0]

    lib._model_host = _TagStubHost([{"box": [0.2, 0.2, 0.3, 0.3], "score": 0.9}])
    msg = lib.jobs.run_one(jid)
    assert msg == f"found faces in {len(ids)} of {len(ids)} items"
    with lib.db.session() as s:
        for iid in ids:
            assert len(s.execute(
                select(Face).where(Face.item_id == iid)).scalars().all()) == 1
        assert s.get(Job, jid).progress == 100


def test_depth_job_stores_artifact_nested_under_active_file(lib_client):
    """A depth job stores a FileArtifact attached to the item's active source
    file (not a new source file), and it surfaces in the item detail nested
    under that file."""
    from media_compost.db import FileArtifact

    client, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        item = s.get(Item, iid)
        active = item.active_file_id
        n_files_before = len(s.execute(select(File).where(File.item_id == iid)).scalars().all())

    lib._model_host = _StubHost(Image.new("RGB", (300, 300), (20, 20, 20)))
    jid = _queue_artifact_job(lib, iid, "depth", "depth_anything_v2_small")
    lib.jobs.run_one(jid)

    with lib.db.session() as s:
        arts = s.execute(select(FileArtifact).where(FileArtifact.item_id == iid)).scalars().all()
        assert len(arts) == 1
        assert arts[0].kind == "depth" and arts[0].file_id == active
        # No new *source* file was added — the artifact is separate.
        assert len(s.execute(select(File).where(File.item_id == iid)).scalars().all()) == n_files_before

    detail = client.get(f"/api/items/{iid}").json()
    active_fv = next(f for f in detail["files"] if f["id"] == active)
    assert len(active_fv["artifacts"]) == 1
    assert active_fv["artifacts"][0]["kind"] == "depth"
    aid = active_fv["artifacts"][0]["id"]

    # The artifact bytes are served, and it can be deleted.
    assert client.get(f"/api/artifacts/{aid}").status_code == 200
    assert client.delete(f"/api/artifacts/{aid}").json() == {"ok": True}
    with lib.db.session() as s:
        assert s.get(FileArtifact, aid) is None


def test_pose_job_with_no_result_stores_nothing(lib_client):
    """A pose run that detected no person (model returns None) is a warning and
    creates no artifact."""
    from media_compost.db import FileArtifact

    client, lib = lib_client
    iid = _item_id(lib)
    lib._model_host = _StubHost(None)
    jid = _queue_artifact_job(lib, iid, "pose", "yolo11n_pose")
    msg = lib.jobs.run_one(jid)
    assert msg == "no pose produced"
    with lib.db.session() as s:
        assert s.execute(select(FileArtifact).where(FileArtifact.item_id == iid)).scalars().all() == []


def test_artifact_file_survives_prune(lib_client):
    """An artifact's on-disk file is referenced by its FileArtifact row (not by
    any File), so a prune sweep must keep it."""
    from media_compost.db import FileArtifact

    client, lib = lib_client
    iid = _item_id(lib)
    lib._model_host = _StubHost(Image.new("RGB", (300, 300), (20, 20, 20)))
    lib.jobs.run_one(_queue_artifact_job(lib, iid, "depth", "depth_anything_v2_small"))
    with lib.db.session() as s:
        art = s.execute(select(FileArtifact).where(FileArtifact.item_id == iid)).scalars().first()
        obj = lib.store.path_of(s, art)
        assert obj.exists()
        removed = lib.store.prune_all(s)
        assert obj.exists(), "prune deleted the artifact file"
    assert removed == 0


def test_panels_create_linked_items_and_dedup(lib_client):
    """Panel detection crops each panel into a new item linked to the page; a
    re-run with the same crops links to the existing items (no duplicates)."""
    from media_compost.db import Relationship

    client, lib = lib_client
    iid = _item_id(lib)
    boxes = [[0.0, 0.0, 0.5, 1.0], [0.5, 0.0, 0.5, 1.0]]  # two non-overlapping halves
    n0 = len(_all_item_ids(lib))
    with lib.db.session() as s:
        msg = lib.jobs._apply_panels(s, s.get(Item, iid), boxes, "magiv3_panels")
        s.commit()
    assert msg == "2 panels linked"
    assert len(_all_item_ids(lib)) == n0 + 2
    with lib.db.session() as s:
        # Each panel item links *to* the originating page.
        rels = s.execute(select(Relationship).where(
            Relationship.to_item_id == iid, Relationship.kind == "panel")).scalars().all()
        assert len(rels) == 2

    # Re-run: identical crops resolve to the existing items (dedup by sha256).
    with lib.db.session() as s:
        lib.jobs._apply_panels(s, s.get(Item, iid), boxes, "magiv3_panels")
        s.commit()
    assert len(_all_item_ids(lib)) == n0 + 2   # no new items


def test_panels_into_sequence_single_page(lib_client):
    """With the sequence toggle, a single page's panels are grouped into their
    own new sequence that links back to the page."""
    from media_compost.db import Relationship, Sequence, SequenceItem

    client, lib = lib_client
    iid = _item_id(lib)
    boxes = [[0.0, 0.0, 0.5, 1.0], [0.5, 0.0, 0.5, 1.0]]
    with lib.db.session() as s:
        page = s.get(Item, iid)
        msg = lib.jobs._apply_panels(
            s, page, boxes, "magiv3_panels", into_sequence=True)
        s.commit()
    assert msg == "2 panels → new sequence"
    with lib.db.session() as s:
        page = s.get(Item, iid)
        seq = s.execute(select(Sequence).where(
            Sequence.name == f"{page.name} — panels")).scalars().first()
        assert seq is not None
        members = s.execute(select(SequenceItem).where(
            SequenceItem.sequence_id == seq.id)).scalars().all()
        assert len(members) == 2
        # The panel sequence links back to the page it came from.
        link = s.execute(select(Relationship).where(
            Relationship.from_item_id == seq.item_id,
            Relationship.to_item_id == iid,
            Relationship.kind == "panel")).scalars().first()
        assert link is not None


def test_overlapping_panels_are_masked_transparent(lib_client):
    """When two panels' boxes overlap (non-rectangular layout), each crop erases
    the part belonging to the neighbour — leaving transparent pixels."""
    from PIL import Image

    from media_compost.db import Relationship

    client, lib = lib_client
    iid = _item_id(lib)
    # Two big boxes with offset centres → their bounding boxes overlap.
    boxes = [[0.0, 0.0, 0.8, 0.8], [0.2, 0.2, 0.8, 0.8]]
    with lib.db.session() as s:
        lib.jobs._apply_panels(s, s.get(Item, iid), boxes, "magiv3_panels")
        s.commit()
    with lib.db.session() as s:
        rels = s.execute(select(Relationship).where(
            Relationship.to_item_id == iid, Relationship.kind == "panel")).scalars().all()
        assert len(rels) == 2
        any_transparent = False
        for r in rels:
            f = s.get(File, s.get(Item, r.from_item_id).active_file_id)
            im = Image.open(lib.store.path_of(s, f)).convert("RGBA")
            if im.getchannel("A").getextrema()[0] == 0:
                any_transparent = True
        assert any_transparent


def _make_page(lib, name, fill) -> int:
    """Create a distinct image item directly (no import/dedup); return its id."""
    import io

    from media_compost.db import FileName
    from media_compost.storage import sha256_bytes

    im = Image.new("RGB", (200, 300), fill)
    ImageDraw.Draw(im).text((20, 20), name, fill=(255, 255, 255))
    buf = io.BytesIO(); im.save(buf, "PNG"); data = buf.getvalue()
    digest = sha256_bytes(data)
    with lib.db.session() as s:
        it = Item(name=f"{name}.png"); s.add(it); s.flush()
        rel = lib.store.write_file(it.uid, 1, "png", data=data)
        f = File(item_id=it.id, sha256=digest, path=rel, number=1,
                 width=200, height=300, bytes=len(data), format="png")
        s.add(f); s.flush()
        it.active_file_id = f.id
        s.add(FileName(file_id=f.id, name=f"{name}.png"))
        s.commit()
        return it.id


def test_panels_on_sequence_collects_into_new_sequence(lib_client, tmp_path):
    """Panel detection on a sequence runs per page and gathers every page's
    panels into one new sequence, in reading order (page order, then panel)."""
    from media_compost.db import Relationship, Sequence, SequenceItem

    client, lib = lib_client
    p1 = _make_page(lib, "pageA", (200, 30, 30))
    p2 = _make_page(lib, "pageB", (30, 30, 200))
    # Make a sequence of the two pages; get its container item id.
    r = client.post("/api/sequences", json={"name": "Chapter", "item_ids": [p1, p2]})
    container_id = r.json()["item_id"]

    # Two non-overlapping panels per page.
    halves = [[0.0, 0.0, 1.0, 0.5], [0.0, 0.5, 1.0, 0.5]]
    with lib.db.session() as s:
        container = s.get(Item, container_id)
        per_page = [(s.get(Item, p1), halves), (s.get(Item, p2), halves)]
        msg = lib.jobs._apply_panels_sequence(s, container, per_page, "magiv3_panels")
        s.commit()
    assert "4 panels across 2 pages" in msg

    with lib.db.session() as s:
        seq = s.execute(select(Sequence).where(
            Sequence.name == "Chapter — panels")).scalars().first()
        assert seq is not None
        members = s.execute(select(SequenceItem).where(
            SequenceItem.sequence_id == seq.id).order_by(SequenceItem.position)).scalars().all()
        assert len(members) == 4
        # First two panels belong to page 1, last two to page 2 (reading order).
        page_of = {}
        for m in members:
            rel = s.execute(select(Relationship).where(
                Relationship.from_item_id == m.item_id,
                Relationship.kind == "panel")).scalars().first()
            page_of[m.position] = rel.to_item_id
        assert page_of[0] == p1 and page_of[1] == p1
        assert page_of[2] == p2 and page_of[3] == p2
        # The new panel sequence links back to the original sequence.
        seq_link = s.execute(select(Relationship).where(
            Relationship.from_item_id == seq.item_id,
            Relationship.to_item_id == container_id,
            Relationship.kind == "panel")).scalars().first()
        assert seq_link is not None


def test_caption_job_adds_a_pending_caption(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_caption(lib, iid, "A red disc on a white field.")
    detail = client.get(f"/api/items/{iid}").json()
    caps = detail["captions"]
    assert len(caps) == 1 and caps[0]["pending"] is True
    client.post(f"/api/ml/captions/{caps[0]['id']}/approve")
    detail = client.get(f"/api/items/{iid}").json()
    assert detail["captions"][0]["pending"] is False


def test_editing_a_pending_caption_approves_it(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_caption(lib, iid, "draft caption")
    cid = client.get(f"/api/items/{iid}").json()["captions"][0]["id"]
    client.patch(f"/api/items/{iid}/captions/{cid}", json={"text": "edited caption"})
    cap = client.get(f"/api/items/{iid}").json()["captions"][0]
    assert cap["text"] == "edited caption" and cap["pending"] is False


def test_tag_job_adds_pending_tags_in_system_group(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    msg = _apply_tags(lib, iid, [
        _tag("cat"),
        _tag("traffic light"),  # multi-word → underscored
        _tag("subject", (0.1, 0.1, 0.5, 0.5)),
    ])
    assert "pending" in msg
    with lib.db.session() as s:
        grp = s.execute(select(ItemTagGroup).where(
            ItemTagGroup.item_id == iid, ItemTagGroup.system.is_(True)
        )).scalars().first()
        # The pending group is named after the model/mode that produced it.
        assert grp is not None and grp.name == "Pending: Florence-2 (base-ft) — Object detection"
        pend = s.execute(select(ItemTag).where(
            ItemTag.item_id == iid, ItemTag.pending.is_(True)
        )).scalars().all()
        assert len(pend) == 3
    detail = client.get(f"/api/items/{iid}").json()
    pending_insts = [t for t in detail["tag_instances"] if t["pending"]]
    assert pending_insts
    names = {t["name"] for t in detail["tag_instances"]}
    assert "traffic_light" in names  # whitespace collapsed to underscore
    assert any(t["name"] == "subject" and t["boxes"] for t in detail["tag_instances"])


def test_tag_job_rerun_refreshes_boxes_instead_of_stacking(lib_client):
    """Re-running the same tagger must not append another identical set of
    boxes to the existing pending placement, and must not log a second
    add_tag event per already-present tag (those revert one by one)."""
    client, lib = lib_client
    iid = _item_id(lib)
    results = [_tag("subject", (0.1, 0.1, 0.5, 0.5)),
               _tag("subject", (0.6, 0.6, 0.2, 0.2))]
    _apply_tags(lib, iid, results)
    msg = _apply_tags(lib, iid, results)
    assert msg == "tags already present"
    with lib.db.session() as s:
        placements = s.execute(select(ItemTagPlacement).join(
            ItemTagGroup, ItemTagPlacement.group_id == ItemTagGroup.id
        ).where(ItemTagGroup.item_id == iid,
                ItemTagGroup.system.is_(True))).scalars().all()
        assert len(placements) == 1
        boxes = s.execute(select(ItemTagBox).where(
            ItemTagBox.placement_id == placements[0].id
        )).scalars().all()
        assert len(boxes) == 2  # one per detection, not per run
    events = client.get("/api/history?limit=50").json()["events"]
    adds = [e for e in events if e["action"] == "add_tag"]
    assert len(adds) == 1


def test_pending_category_lists_item_and_counts(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_tags(lib, iid, [_tag("cat")])
    listed = client.get("/api/items?pending=true").json()
    assert [it["id"] for it in listed["items"]] == [iid]
    assert client.get("/api/library/stats").json()["pending"] == 1


def test_approving_last_pending_tag_removes_the_group(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_tags(lib, iid, [_tag("cat"), _tag("dog")])
    detail = client.get(f"/api/items/{iid}").json()
    pending = [t for t in detail["tag_instances"] if t["pending"]]
    for t in pending:
        client.post(f"/api/ml/placements/{t['placement_id']}/approve")
    with lib.db.session() as s:
        assert s.execute(select(ItemTagGroup).where(
            ItemTagGroup.item_id == iid, ItemTagGroup.system.is_(True)
        )).scalars().first() is None
        assert not s.execute(select(ItemTag).where(
            ItemTag.item_id == iid, ItemTag.pending.is_(True)
        )).scalars().all()
    assert client.get("/api/library/stats").json()["pending"] == 0


def test_unassigning_the_last_pending_tag_removes_the_group(lib_client):
    """The dismissal paths that delete the whole ASSIGNMENT (unassign, the
    quick-assign remove) take the placements with it by FK cascade — so they
    must sweep the emptied Pending group themselves, or it strands as a box
    no control can remove (found live as an empty "Pending: WD Tagger")."""
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_tags(lib, iid, [_tag("cat")])
    r = client.delete(f"/api/tags/assign/item/{iid}/cat")
    assert r.status_code == 200
    with lib.db.session() as s:
        assert s.execute(select(ItemTagGroup).where(
            ItemTagGroup.item_id == iid, ItemTagGroup.system.is_(True)
        )).scalars().first() is None
    # The quick-assign remove is the other whole-assignment delete.
    _apply_tags(lib, iid, [_tag("dog")])
    r = client.post("/api/tags/quick-assign",
                    json={"item_ids": [iid], "positive": ["dog"],
                          "negative": [], "remove": True})
    assert r.status_code == 200, r.text
    with lib.db.session() as s:
        assert s.execute(select(ItemTagGroup).where(
            ItemTagGroup.item_id == iid, ItemTagGroup.system.is_(True)
        )).scalars().first() is None


def test_unavailable_model_fails_gracefully(lib_client):
    """A job for a model whose deps aren't installed ends 'failed' with a message
    rather than crashing the worker."""
    _, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        job = Job(kind="caption", model="florence2_base:caption", item_id=iid,
                  status="queued")
        s.add(job)
        s.commit()
        jid = job.id
    if registry.source_deps_ok("florence2_base"):
        # NOT "torch is installed": Florence runs in a dedicated env with no
        # `deps` of its own, so this is true whenever `.venv-florence` is set
        # up — on a machine whose main venv has no torch at all.
        pytest.skip("florence2_base can run here — the model would actually run")
    with pytest.raises(RuntimeError):
        lib.jobs.run_one(jid)


def test_cancel_queued_job(lib_client):
    _, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        job = Job(kind="caption", model="", item_id=iid, status="queued")
        s.add(job)
        s.commit()
        jid = job.id
    assert lib.jobs.cancel(jid) is True
    with lib.db.session() as s:
        assert s.get(Job, jid).status == "canceled"


def test_capture_log_collects_stdout_and_logging():
    """The log capture used per job records prints and standard logging."""
    import logging

    from media_compost.ui.jobs import _CaptureLog

    cap = _CaptureLog()
    with cap:
        print("package stdout line")
        logging.getLogger("pkg").warning("a package warning")
    txt = cap.text()
    assert "package stdout line" in txt
    assert "a package warning" in txt


def test_run_job_records_log_on_failure(lib_client):
    """A failed job stores its captured log (including the traceback)."""
    _, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        job = Job(kind="caption", model="florence2_base:caption", item_id=iid,
                  status="queued")
        s.add(job)
        s.commit()
        jid = job.id
    if registry.source_deps_ok("florence2_base"):
        # Same condition, and this is the one that keeps the suite offline:
        # a runnable Florence would fetch its weights if they are not cached.
        pytest.skip("florence2_base can run here — the model would hit the network")
    lib.jobs._run_job(jid)  # synchronous; the model raises immediately
    with lib.db.session() as s:
        job = s.get(Job, jid)
        assert job.status == "failed"
        assert job.log and "Traceback" in job.log


def test_repo_cached_requires_complete_download(tmp_path, monkeypatch):
    """A cancelled/interrupted download leaves the probe file but a half-fetched
    (.incomplete) blob; cache_status must report it as *not* cached so the UI
    doesn't wrongly show it as downloaded. A *0-byte* .incomplete is a spurious
    leftover and is ignored (the MiDaS symptom)."""
    import huggingface_hub.constants as hc
    monkeypatch.setattr(hc, "HF_HUB_CACHE", str(tmp_path))
    repo = "acme/demo"
    blobs = tmp_path / hubcache._repo_dirname(repo) / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "abc123").write_bytes(b"weights")
    assert hubcache._has_incomplete_blobs(repo) is False
    # A 0-byte incomplete leftover is ignored.
    (blobs / "empty.incomplete").write_bytes(b"")
    assert hubcache._has_incomplete_blobs(repo) is False
    # A genuine, non-empty partial download counts.
    (blobs / "def456.incomplete").write_bytes(b"half a blob")
    assert hubcache._has_incomplete_blobs(repo) is True
    assert hubcache._has_incomplete_blobs("no/such") is False


def test_tag_runs_use_separate_pending_groups_per_model(lib_client):
    """Tags from different models/modes land in separate pending groups."""
    _, lib = lib_client
    iid = _item_id(lib)
    _apply_tags(lib, iid, [_tag("cat")], model="florence2_base:od")
    _apply_tags(lib, iid, [_tag("dog")], model="joytag")
    with lib.db.session() as s:
        names = sorted(n for (n,) in s.execute(
            select(ItemTagGroup.name).where(
                ItemTagGroup.item_id == iid, ItemTagGroup.system.is_(True))
        ).all())
    assert names == [
        "Pending: Florence-2 (base-ft) — Object detection",
        "Pending: JoyTag",
    ]


def test_multiple_boxes_for_same_tag_all_kept(lib_client):
    """A model emitting the same label several times keeps every box on the one
    tag instance."""
    _, lib = lib_client
    iid = _item_id(lib)
    _apply_tags(lib, iid, [
        _tag("car", (0.0, 0.0, 0.2, 0.2)),
        _tag("car", (0.5, 0.5, 0.2, 0.2)),
    ])
    with lib.db.session() as s:
        tags = s.execute(select(ItemTag).where(ItemTag.item_id == iid)).scalars().all()
        assert len(tags) == 1                      # one "car" tag
        pls = s.execute(select(ItemTagPlacement).where(
            ItemTagPlacement.item_tag_id == tags[0].id)).scalars().all()
        assert len(pls) == 1
        boxes = s.execute(select(ItemTagBox).where(
            ItemTagBox.placement_id == pls[0].id)).scalars().all()
        assert len(boxes) == 2                      # both boxes kept


def test_a_bare_tag_the_item_already_has_is_left_exactly_where_it_is(lib_client):
    """A generated label the item already carries changes nothing at all.

    It used to be copied into the run's pending group AND have its assignment
    re-flagged pending, so agreeing with a tag somebody had placed demoted it
    to a machine's guess and showed it a second time under "Pending". With no
    box there is nothing to review and nothing approval could merge, so the
    rule is `_pending_subject_tag`'s, which a face guess has always followed.
    """
    client, lib = lib_client
    iid = _item_id(lib)
    grp = client.post(f"/api/tags/item/{iid}/groups",
                      json={"name": "Subject"}).json()
    client.post(f"/api/tags/item/{iid}/group-tag",
                json={"tag": "cat", "group_id": grp["id"], "negative": False})
    client.post(f"/api/tags/item/{iid}/group-tag",
                json={"tag": "dog", "group_id": None, "negative": False})
    msg = _apply_tags(lib, iid, [_tag("cat"), _tag("dog")])
    assert msg == "tags already present"
    with lib.db.session() as s:
        for it in s.execute(select(ItemTag).where(
                ItemTag.item_id == iid)).scalars().all():
            assert it.pending is False
        # Each keeps its ONE placement, in the group it was put in, and the
        # run's group is dropped for holding nothing.
        pls = s.execute(select(ItemTagPlacement).join(ItemTag).where(
            ItemTag.item_id == iid)).scalars().all()
        assert len(pls) == 2
        assert {p.group_id for p in pls} == {grp["id"], None}
        assert not s.execute(select(ItemTagGroup).where(
            ItemTagGroup.item_id == iid,
            ItemTagGroup.system.is_(True))).scalars().all()
    assert client.get("/api/library/stats").json()["pending"] == 0


def test_a_BOX_for_a_tag_the_item_has_is_a_pending_copy_BESIDE_it(lib_client):
    """A box is new information, so it gets a copy to review — and a COPY.

    An ordinary assignment carries NO placement row: the ungrouped instance
    the sidebar draws is implicit, the fallback for a direct tag with none.
    So a pending placement added on its own does not sit beside the tag — it
    becomes the tag's only instance, and the tag MOVES out of the ungrouped
    list into "Pending". That is what "existing tags are moved into the
    pending group" was. The ungrouped instance is materialized first.
    """
    client, lib = lib_client
    iid = _item_id(lib)
    client.post("/api/tags/quick-assign",
                json={"item_ids": [iid], "positive": ["cat"], "negative": []})
    with lib.db.session() as s:
        assert not s.execute(select(ItemTagPlacement).join(ItemTag).where(
            ItemTag.item_id == iid)).scalars().all()
    _apply_tags(lib, iid, [_tag("cat", (0.1, 0.1, 0.3, 0.3))])
    detail = client.get(f"/api/items/{iid}").json()
    inst = sorted([t for t in detail["tag_instances"] if t["name"] == "cat"],
                  key=lambda t: t["group_id"] or 0)
    assert len(inst) == 2
    # The one somebody placed is still ungrouped and carries no box; the
    # copy is in the run's system group with the detection on it.
    assert inst[0]["group_id"] is None and not inst[0].get("boxes")
    assert inst[1]["group_id"] is not None and len(inst[1]["boxes"]) == 1
    groups = {g["id"]: g for g in detail["tag_groups"]}
    assert groups[inst[1]["group_id"]]["system"] is True


def test_approving_the_copy_MERGES_its_box_into_the_tag_you_already_had(
        lib_client):
    """The whole point of offering the copy: end to end, through the real
    approve endpoint, the item ends with ONE instance of the tag — the one
    somebody placed — now carrying the box the model found."""
    client, lib = lib_client
    iid = _item_id(lib)
    client.post("/api/tags/quick-assign",
                json={"item_ids": [iid], "positive": ["cat"], "negative": []})
    _apply_tags(lib, iid, [_tag("cat", (0.1, 0.1, 0.3, 0.3))])
    detail = client.get(f"/api/items/{iid}").json()
    # NOTE `pending` is a fact about the (item, tag) PAIR, so both instances
    # report it — the copy is the one in the system group.
    system = {g["id"] for g in detail["tag_groups"] if g["system"]}
    copy = [t for t in detail["tag_instances"]
            if t["group_id"] in system][0]
    client.post(f"/api/ml/placements/{copy['placement_id']}/approve")
    detail = client.get(f"/api/items/{iid}").json()
    inst = [t for t in detail["tag_instances"] if t["name"] == "cat"]
    assert len(inst) == 1
    assert inst[0]["group_id"] is None and inst[0]["pending"] is False
    assert len(inst[0]["boxes"]) == 1
    assert not detail["tag_groups"]


def test_a_box_does_not_reopen_a_tag_the_user_said_NO_to(lib_client):
    """A negative assignment is an answer already given, and a rectangle does
    not reopen it — the old code re-flagged even that one pending."""
    client, lib = lib_client
    iid = _item_id(lib)
    client.post(f"/api/tags/item/{iid}/group-tag",
                json={"tag": "cat", "group_id": None, "negative": True})
    _apply_tags(lib, iid, [_tag("cat", (0.1, 0.1, 0.3, 0.3))])
    with lib.db.session() as s:
        it = s.execute(select(ItemTag).where(
            ItemTag.item_id == iid)).scalars().one()
        assert it.negative is True and it.pending is False
        assert not s.execute(select(ItemTagGroup).where(
            ItemTagGroup.item_id == iid,
            ItemTagGroup.system.is_(True))).scalars().all()


def test_move_merges_overlapping_boxes(lib_client):
    """Moving a tag instance into a group that already has that tag folds boxes:
    ≥50%-overlapping boxes combine into one; disjoint boxes are appended."""
    from media_compost.ops import ctx_for, tagassign
    _, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        tag = Tag(name="cat"); s.add(tag); s.flush()
        it = ItemTag(item_id=iid, tag_id=tag.id); s.add(it); s.flush()
        g = ItemTagGroup(item_id=iid, name="G"); s.add(g); s.flush()
        dst = ItemTagPlacement(item_tag_id=it.id, group_id=g.id); s.add(dst); s.flush()
        s.add(ItemTagBox(placement_id=dst.id, x=0.10, y=0.10, w=0.40, h=0.40))
        src = ItemTagPlacement(item_tag_id=it.id, group_id=None); s.add(src); s.flush()
        s.add(ItemTagBox(placement_id=src.id, x=0.12, y=0.12, w=0.40, h=0.40))  # overlaps dst
        s.add(ItemTagBox(placement_id=src.id, x=0.80, y=0.80, w=0.15, h=0.15))  # disjoint
        s.flush()
        tagassign.merge_placement_into_group(ctx_for(s), src, g.id)
        s.commit()
    with lib.db.session() as s:
        it = s.execute(select(ItemTag).where(ItemTag.item_id == iid)).scalars().first()
        pls = s.execute(select(ItemTagPlacement).where(
            ItemTagPlacement.item_tag_id == it.id)).scalars().all()
        assert len(pls) == 1                        # duplicate placement dropped
        boxes = s.execute(select(ItemTagBox).where(
            ItemTagBox.placement_id == pls[0].id)).scalars().all()
        assert len(boxes) == 2                      # 1 merged union + 1 appended


def test_caption_records_model_and_edit(lib_client):
    """A generated caption carries its model name; editing it keeps the model and
    marks it edited (and approves it)."""
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_caption(lib, iid, "a draft caption", model="joycaption:descriptive")
    cap = client.get(f"/api/items/{iid}").json()["captions"][0]
    assert cap["model"] == "JoyCaption — Descriptive" and cap["edited"] is False
    client.patch(f"/api/items/{iid}/captions/{cap['id']}", json={"text": "edited"})
    cap = client.get(f"/api/items/{iid}").json()["captions"][0]
    assert cap["pending"] is False and cap["edited"] is True
    assert cap["model"] == "JoyCaption — Descriptive"


def test_caption_edit_is_revertible(lib_client):
    """Editing a caption logs a revertible History event; reverting restores the
    previous text and pending/edited flags."""
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_caption(lib, iid, "original text", model="joycaption:descriptive")
    cid = client.get(f"/api/items/{iid}").json()["captions"][0]["id"]
    client.patch(f"/api/items/{iid}/captions/{cid}", json={"text": "new text"})
    cap = client.get(f"/api/items/{iid}").json()["captions"][0]
    assert cap["text"] == "new text" and cap["pending"] is False and cap["edited"] is True
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "edit_caption")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    cap = client.get(f"/api/items/{iid}").json()["captions"][0]
    assert cap["text"] == "original text" and cap["pending"] is True and cap["edited"] is False


def test_removing_a_caption_reverts_with_its_whole_shape(lib_client):
    """Undo restores the meta tags, provenance, flags and position — not a
    bare hand-written caption at the end of the list."""
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_caption(lib, iid, "a scene", model="joycaption:descriptive")
    cid = client.get(f"/api/items/{iid}").json()["captions"][0]["id"]
    client.post(f"/api/items/{iid}/captions/{cid}/tags",
                json={"name": "alt text"})
    client.post(f"/api/items/{iid}/captions", json={"text": "second"})

    client.delete(f"/api/items/{iid}/captions/{cid}")
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "remove_caption")
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})

    caps = client.get(f"/api/items/{iid}").json()["captions"]
    restored = next(c for c in caps if c["text"] == "a scene")
    assert restored["pending"] is True
    assert restored["model"] == "JoyCaption — Descriptive"
    assert restored["tags"] == ["alt text"]
    # Position travels too: the machine caption came first and comes back
    # first, ahead of the hand-written one added after it.
    assert [c["text"] for c in caps] == ["a scene", "second"]


def test_approve_caption_is_revertible(lib_client):
    """Approving a pending caption logs a revertible History event; reverting puts
    it back to pending."""
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_caption(lib, iid, "a scene", model="joycaption:descriptive")
    cid = client.get(f"/api/items/{iid}").json()["captions"][0]["id"]
    client.post(f"/api/ml/captions/{cid}/approve")
    assert client.get(f"/api/items/{iid}").json()["captions"][0]["pending"] is False
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "approve_caption")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert client.get(f"/api/items/{iid}").json()["captions"][0]["pending"] is True


def test_approve_tag_is_revertible(lib_client):
    """Approving a pending tag logs a revertible History event; reverting moves it
    back into a pending group."""
    client, lib = lib_client
    iid = _item_id(lib)
    _apply_tags(lib, iid, [_tag("cat")], model="florence2_base:od")
    inst = next(t for t in client.get(f"/api/items/{iid}").json()["tag_instances"]
                if t["name"] == "cat" and t["pending"])
    client.post(f"/api/ml/placements/{inst['placement_id']}/approve")
    inst = next(t for t in client.get(f"/api/items/{iid}").json()["tag_instances"]
                if t["name"] == "cat")
    assert inst["pending"] is False and inst["group_id"] is None
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "approve_tag")
    assert ev["revertible"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    inst = next(t for t in client.get(f"/api/items/{iid}").json()["tag_instances"]
                if t["name"] == "cat")
    assert inst["pending"] is True and inst["group_id"] is not None


def test_jobs_list_auto_clears_success_keeps_warning(lib_client):
    """A cleanly-successful (done) job is auto-removed from the list; a warning
    (empty output) and a failure stay visible."""
    client, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        for status in ("done", "warning", "failed", "canceled"):
            s.add(Job(kind="tag", model="florence2_base:od", item_id=iid,
                      status=status, message="" if status == "done" else status))
        s.commit()
    jobs = client.get("/api/ml/jobs").json()["jobs"]
    statuses = {j["status"] for j in jobs}
    assert "done" not in statuses               # success auto-cleared
    assert statuses == {"warning", "failed", "canceled"}
    # Clearing finished removes all of them (including the warning).
    client.post("/api/ml/jobs/clear-finished")
    assert client.get("/api/ml/jobs").json()["jobs"] == []


def test_ram_transformers_compat_backfills_symbols():
    """The RAM compat shim back-fills the transformers symbols the `ram` package
    imports from ``transformers.modeling_utils`` that newer transformers moved to
    ``pytorch_utils`` or removed — so ``import ram`` stops failing on 5.x."""
    pytest.importorskip("torch")          # optional AI deps (requirements-ai)
    pytest.importorskip("transformers")
    import transformers.modeling_utils as mu

    from media_compost.ui.plugins.impl import ram_plus
    ram_plus._transformers_compat()
    for name in ("apply_chunking_to_forward", "find_pruneable_heads_and_indices",
                 "prune_linear_layer"):
        assert hasattr(mu, name), name


def test_joytag_model_code_is_vendored():
    """JoyTag's model code (absent from the HF weights repo) is bundled so the
    downloaded weights load without a separate git clone."""
    pytest.importorskip("torch")
    pytest.importorskip("einops")
    from media_compost.ui.vendor import joytag_models
    assert hasattr(joytag_models, "VisionModel")
    # The published checkpoint's config uses the ViT subclass.
    assert hasattr(joytag_models, "ViT")


def test_new_model_families_are_registered():
    """WD/RAM++ show up as taggers and BLIP-2/Qwen2.5-VL as captioners, each with
    a cache probe, a runnable setup and family mapping."""
    tag_ids = {m.id for m in registry.models_for("tag")}
    cap_ids = {m.id for m in registry.models_for("caption")}
    assert {"wd_tagger", "ram_plus"} <= tag_ids
    assert {"blip2", "qwen2_5_vl"} <= cap_ids
    for key in ("wd_tagger", "ram_plus", "blip2", "qwen2_5_vl"):
        src = registry.source_for(key)
        assert src is not None and src.probe        # cache probe file
        # Was `install_for(key)` — prose for an overlay that no longer shows
        # any. What the UI offers instead is the Run setup button, so what
        # "this model is wired up" means is that something can run its setup.
        assert registry.setup_key_for_source(key)
        assert registry.source_key_for_model(key) == key


def test_prune_removes_orphans_and_keeps_referenced_files(lib_client):
    """A stray file inside an item folder (e.g. bytes orphaned by a rolled-back
    import savepoint) is pruned; the item's referenced files and its item.json
    are kept; a folder whose uid no longer exists in the DB is removed."""
    from media_compost.db import Item

    _, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        item = s.get(Item, iid)
        uid = item.uid
        active = s.get(File, item.active_file_id)
        kept = lib.store.path_of(s, active)
    orphan = lib.store.file_path(uid, "files/999.png")
    orphan.write_bytes(b"orphan bytes")
    # A leftover sidecar from before item.json was retired is a stray now.
    sidecar = lib.store.item_dir(uid) / "item.json"
    sidecar.write_text("{}")
    foreign = lib.store.item_dir("ff" + "0" * 30)
    foreign.mkdir(parents=True)
    (foreign / "junk.bin").write_bytes(b"x")
    with lib.db.session() as s:
        removed = lib.store.prune_all(s)
    assert removed == 3  # the orphan, the leftover sidecar, the foreign folder
    assert kept.exists()
    assert not orphan.exists() and not sidecar.exists()
    assert not foreign.exists()


def test_cached_latents_are_listed_with_their_variant(lib_client):
    """Latents are tensors rather than images, but they live in the item's
    folder and take up its disk — so the Source list shows them, with the
    variant that tells one cache entry from another."""
    from media_compost.db import FileArtifact

    client, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        fid = s.get(Item, iid).active_file_id
        for path in ("artifacts/1-latent-sdxl-1024x1024.pt",
                     "artifacts/1-latent-sdxl-1024x1024-f.pt",
                     "artifacts/1-latent-sd15-am-64x64-f.pt"):
            s.add(FileArtifact(item_id=iid, file_id=fid, kind="latent",
                               model="sdxl", path=path, width=64, height=64,
                               bytes=1234, format="pt", sha256=path))
        s.commit()

    files = client.get(f"/api/items/{iid}").json()["files"]
    arts = [a for f in files for a in f["artifacts"] if a["kind"] == "latent"]
    assert len(arts) == 3
    assert [a["variant"] for a in arts] == ["", "flipped", "flipped, masked"]
    # The model is the TRAINING key, not run through the plugin label map.
    assert arts[0]["model"] == "sdxl"


def test_a_latent_can_be_deleted_but_not_mid_training(lib_client):
    """A latent is a cache — the next run re-encodes what is missing — so it
    can be deleted to reclaim disk. Not while a trainer is reading it, though."""
    from media_compost.db import FileArtifact

    client, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        item = s.get(Item, iid)
        a = FileArtifact(item_id=iid, file_id=item.active_file_id, kind="latent",
                         model="sdxl", path="artifacts/1-latent-sdxl-64x64.pt",
                         width=64, height=64, bytes=99, format="pt",
                         sha256="lat1")
        s.add(a)
        s.commit()
        aid = a.id

    lib.training.running_uid = lambda: "abc123"
    r = client.delete(f"/api/artifacts/{aid}")
    assert r.status_code == 409
    assert "training job is running" in r.json()["detail"]

    lib.training.running_uid = lambda: None
    assert client.delete(f"/api/artifacts/{aid}").status_code == 200
    with lib.db.session() as s:
        assert s.get(FileArtifact, aid) is None


def test_every_detector_is_on_the_models_page_under_one_heading(lib_client):
    """The page that answers "what models are there, and are they ready" has to
    mention the ones that arrive with a pip install rather than a download.

    InsightFace fetches its own pack on first use, so it owns no downloadable
    source and the list — built from sources — left it out entirely: the human
    face detector existed and the models page said it did not.
    """
    client, _ = lib_client
    rows = {m["key"]: m for m in client.get("/api/ml/model-cache").json()["models"]}

    # Two detection sections: what is found ON the page (its panels, its
    # text, a logo stamped over it) and who is IN it.
    by_cat = lambda c: {k for k, m in rows.items() if m["category"] == c}
    assert {"magiv3", "rapid_ocr", "wm_yolo11x"} <= by_cat("Text"), \
        "panels, OCR and the watermark detector are all read off the page"
    assert {"anime_face", "insightface_faces", "magi_crop_embedder"} \
        <= by_cat("Face detection"), "both detectors and the embedder"

    face = rows["insightface_faces"]
    assert face["repo"] == "", "nothing to fetch from the hub"
    # It carried `install` prose before the overlay stopped showing any. What
    # makes the row actionable now is the Run setup button behind `setup_key`,
    # which is the whole reason a source-less plugin is listed at all.
    assert face["setup_key"], "so the row must offer a runnable setup instead"


def test_a_plugin_with_nothing_to_install_or_fetch_stays_off_the_page():
    """Canny needs OpenCV, which is a dependency — it is listed. A plugin with
    neither sources nor deps has nothing to manage and would be noise."""
    from media_compost.ui.plugins import registry

    keys = {p.key for p in registry.setup_only_plugins()}
    assert "canny" in keys, "OpenCV is a dependency worth reporting"
    for p in registry.setup_only_plugins():
        assert p.manifest.deps, "listed only because something must be installed"
        assert not p.manifest.sources, "anything downloadable is listed already"


def test_a_plugin_that_fetches_its_own_weights_offers_a_download(lib_client):
    """InsightFace's pack is a zip on its own GitHub release, not a hub repo.

    Without this the row had no repo, so the page offered nothing — and the
    first face detection anyone ran stalled for minutes on a silent download.
    """
    client, _ = lib_client
    row = {m["key"]: m
           for m in client.get("/api/ml/model-cache").json()["models"]}["insightface_faces"]
    assert row["repo"] == "" and row["fetchable"] is True

    from media_compost.ui.plugins import registry

    plug = registry.plugin_by_key("insightface_faces")
    assert callable(getattr(plug.module, "fetch_weights", None))
    assert callable(getattr(plug.module, "weights_ready", None))


def test_readiness_counts_the_weights_not_just_the_packages(lib_client, monkeypatch):
    """`cached` used to mean "the packages import", which read as Ready while
    the weights were still an unfetched download."""
    from media_compost.ui.plugins import registry

    client, _ = lib_client
    monkeypatch.setattr(registry, "plugin_weights_ready",
                        lambda key: key != "insightface_faces")
    row = {m["key"]: m
           for m in client.get("/api/ml/model-cache").json()["models"]}["insightface_faces"]
    assert row["deps_ok"] is True or row["deps_ok"] is False   # either is fine
    assert row["cached"] is False, "no weights, not ready — whatever the deps say"


def test_a_probe_that_raises_does_not_break_the_page(monkeypatch):
    """A weights probe runs on every poll; one bad plugin must not take the
    Settings page down with it."""
    from media_compost.ui.plugins import registry

    plug = registry.plugin_by_key("insightface_faces")
    monkeypatch.setattr(plug.module, "weights_ready",
                        lambda: (_ for _ in ()).throw(OSError("disk gone")))
    assert registry.plugin_weights_ready("insightface_faces") is False


def test_detecting_faces_on_a_sequence_runs_over_its_pages(lib_client, monkeypatch):
    """A sequence has no picture of its own, so asking for faces over one means
    asking page by page — the same as selecting every page by hand."""
    from media_compost.db import Face

    client, lib = lib_client
    p1 = _make_page(lib, "faceA", (200, 30, 30))
    p2 = _make_page(lib, "faceB", (30, 30, 200))
    container = client.post(
        "/api/sequences", json={"name": "Chapter", "item_ids": [p1, p2]}
    ).json()["item_id"]
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    job_ids = lib.jobs.enqueue("faces", "anime_face", [container])
    assert len(job_ids) == 1
    with lib.db.session() as s:
        # The job carries the PAGES, never the container.
        assert sorted(json.loads(s.get(Job, job_ids[0]).item_ids)) == sorted([p1, p2])

    lib._model_host = _TagStubHost([{"box": [0.2, 0.2, 0.3, 0.3], "score": 0.9}])
    assert lib.jobs.run_one(job_ids[0]) == "found faces in 2 of 2 items"
    with lib.db.session() as s:
        for iid in (p1, p2):
            assert len(s.execute(
                select(Face).where(Face.item_id == iid)).scalars().all()) == 1
        assert s.execute(
            select(Face).where(Face.item_id == container)).scalars().all() == []


def test_a_page_named_beside_its_sequence_is_not_detected_twice(lib_client, monkeypatch):
    """Selecting a sequence AND one of its pages asks one question, not two."""
    client, lib = lib_client
    p1 = _make_page(lib, "dupA", (200, 30, 30))
    p2 = _make_page(lib, "dupB", (30, 30, 200))
    container = client.post(
        "/api/sequences", json={"name": "Chapter", "item_ids": [p1, p2]}
    ).json()["item_id"]
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    job_ids = lib.jobs.enqueue("faces", "anime_face", [p2, container])
    with lib.db.session() as s:
        # p2 came first and keeps its place; the sequence adds only what is new.
        assert json.loads(s.get(Job, job_ids[0]).item_ids) == [p2, p1]


def test_panels_still_takes_the_sequence_itself(lib_client, monkeypatch):
    """Panels reads every page too, but collects the result into ONE new
    sequence — so it takes the container and does its own walking."""
    client, lib = lib_client
    p1 = _make_page(lib, "keepA", (200, 30, 30))
    p2 = _make_page(lib, "keepB", (30, 30, 200))
    container = client.post(
        "/api/sequences", json={"name": "Chapter", "item_ids": [p1, p2]}
    ).json()["item_id"]
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    job_ids = lib.jobs.enqueue("panels", "magiv3_panels", [container])
    with lib.db.session() as s:
        assert s.get(Job, job_ids[0]).item_id == container


def test_there_is_one_illustrated_face_detector(lib_client):
    """The detector-only `anime_face` plugin is gone.

    It was the same YOLOv8 detector as `anime_face_magi` without the character
    embedder, so its faces carried no descriptor and could never cluster or be
    suggested — a library detected with it had to be run again to become
    useful. Two entries a menu apart, one of which quietly wasted the run, is
    what the removal fixes; so nothing may offer it again.
    """
    client, _ = lib_client
    faces = next(t for t in client.get("/api/ml/models").json()["tasks"]
                 if t["kind"] == "faces")
    ids = {m["id"] for m in faces["models"]}
    assert "anime_face" not in ids
    assert "anime_face_magi" in ids
    # And it is named for the two models it runs, since there is no longer a
    # detector-only variant beside it for "with character ID" to contrast with.
    name = next(m["name"] for m in faces["models"] if m["id"] == "anime_face_magi")
    assert name == "Illustrated faces (YOLOv8 + Magi)"


def test_a_source_row_counts_the_weights_its_source_does_not_carry(lib_client,
                                                                   monkeypatch):
    """The twin of the test above, for a plugin that has BOTH kinds.

    RAM++ declares its checkpoint as a hub source and then pulls a BERT
    tokenizer from a second repo, from inside the `ram` package. Readiness for
    a source row was `source_cached` alone, so a fresh install read
    "Downloaded" over a model whose first tagging run still had to go to the
    network — and `jobs.py` promises a job never does. `weights_ready()` was
    the answer and was asked only of plugins with NO sources, which is
    precisely the set RAM++ is not in.
    """
    from media_compost.ui.plugins import framework as fw
    from media_compost.ui.plugins import registry

    client, _ = lib_client
    # Pretend the checkpoint is downloaded, so only the second half can move.
    monkeypatch.setattr(fw, "source_cached", lambda m, p="": True)

    monkeypatch.setattr(registry, "plugin_weights_ready", lambda key: True)
    rows = {m["key"]: m for m in client.get("/api/ml/model-cache").json()["models"]}
    assert rows["ram_plus"]["cached"] is True

    monkeypatch.setattr(registry, "plugin_weights_ready",
                        lambda key: key != "ram_plus")
    rows = {m["key"]: m for m in client.get("/api/ml/model-cache").json()["models"]}
    assert rows["ram_plus"]["cached"] is False, \
        "the tokenizer is missing — the row must not say Downloaded"
    # …and every other source row is unaffected by one plugin's answer.
    assert rows["wd_tagger"]["cached"] is True
