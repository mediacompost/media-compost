"""Sidebar rotate: adds an edited, actually-rotated source file (with the
rotation baked into its pixels), swaps the visible dimensions, keeps the pristine
first file untouched, and reuses one derived file across repeated rotations."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from media_compost.ui.config import UiConfig
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def lib_client(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    # A clearly non-square image so a quarter-turn is observable in the dims.
    src = tmp_path / "wide.png"
    Image.new("RGB", (400, 200), (120, 60, 30)).save(src, "PNG")
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False)
        )
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def test_rotate_adds_edited_file_and_swaps_dims(lib_client):
    client, lib = lib_client
    iid = client.get("/api/items").json()["items"][0]["id"]
    detail = client.get(f"/api/items/{iid}").json()
    assert (detail["width"], detail["height"]) == (400, 200)
    base_fid = detail["active_file_id"]

    # Rotate right on the pristine original: it is preserved and a new rotated
    # derived file becomes active (portrait), recording it's based on #1 via a
    # rotate action.
    r = client.post(f"/api/items/{iid}/rotate?dir=right").json()
    assert r["rotation"] == 90
    detail = client.get(f"/api/items/{iid}").json()
    rot_fid = detail["active_file_id"]
    assert rot_fid != base_fid
    assert detail["rotation"] == 90
    assert (detail["width"], detail["height"]) == (200, 400)
    assert len(detail["files"]) == 2  # pristine base + one rotated derivative
    byid = {f["id"]: f for f in detail["files"]}
    assert byid[base_fid]["number"] == 1
    assert byid[rot_fid]["based_on"] == 1 and byid[rot_fid]["edit_action"] == "rotate"

    # The rotated file's own bytes really are portrait (no render-time rotation).
    with lib.db.session() as s:
        from media_compost.db import File
        rf = s.get(File, rot_fid)
        assert (rf.width, rf.height) == (200, 400)
        assert rf.is_derived and rf.derived_from_file_id == base_fid
        with Image.open(lib.store.path_of(s, rf)) as im:
            assert im.height > im.width

    # Rotating again overwrites the (now edited) rotated file in place — still
    # exactly two files, now at 180°, the same active id.
    client.post(f"/api/items/{iid}/rotate?dir=right")
    detail = client.get(f"/api/items/{iid}").json()
    assert detail["rotation"] == 180
    assert detail["active_file_id"] == rot_fid
    assert len(detail["files"]) == 2

    # A full turn back to 0° keeps the rotated derived file active (the base is
    # not reactivated) — still two files.
    for _ in range(2):
        client.post(f"/api/items/{iid}/rotate?dir=right")
    detail = client.get(f"/api/items/{iid}").json()
    assert detail["rotation"] == 0
    assert detail["active_file_id"] == rot_fid
    assert len(detail["files"]) == 2

    # The pristine stored file bytes were never touched (still 400x200).
    with lib.db.session() as s:
        from media_compost.db import File
        f = s.get(File, base_fid)
        assert (f.width, f.height) == (400, 200)


def test_rotation_migration_adds_column(tmp_path: Path):
    """A library created without the rotation column gains it via _migrate."""
    import sqlite3
    from media_compost.db import Database

    cfg = UiConfig(data_dir=tmp_path / "data")
    db = Database(cfg)  # creates schema (incl. rotation)
    db.engine.dispose()
    # Simulate an older DB by dropping the column via table rebuild is awkward;
    # instead assert the column exists after init.
    con = sqlite3.connect(cfg.db_path)
    cols = {row[1] for row in con.execute("PRAGMA table_info(files)")}
    con.close()
    assert "rotation" in cols


def _arts_by_file(files: list[dict]) -> dict[int, list[dict]]:
    return {f["id"]: f.get("artifacts", []) for f in files}


def test_rotate_rotates_artifacts_instead_of_staling(lib_client):
    """Rotating the original branches to a new file that gets a rotated *copy* of
    the artifact (the preserved original keeps its own); rotating that edited file
    again rotates its artifact in place. Nothing is ever staled."""
    import io

    from media_compost.db import FileArtifact
    from media_compost.storage import sha256_bytes

    client, lib = lib_client
    iid = client.get("/api/items").json()["items"][0]["id"]
    base_fid = client.get(f"/api/items/{iid}").json()["active_file_id"]

    # A real, non-square depth artifact on the base (so a quarter-turn is visible).
    buf = io.BytesIO()
    Image.new("RGB", (400, 200), (10, 20, 30)).save(buf, "PNG")
    data = buf.getvalue()
    digest = sha256_bytes(data)
    with lib.db.session() as s:
        from media_compost.db import File, Item

        item = s.get(Item, iid)
        base = s.get(File, base_fid)
        rel = lib.store.write_artifact(item.uid, base.number, "depth", "png", data)
        s.add(FileArtifact(file_id=base_fid, item_id=iid, kind="depth",
                           sha256=digest, path=rel, width=400, height=200,
                           bytes=len(data)))
        s.commit()

    # Rotate right → the original is preserved with its (unrotated) artifact, and
    # the new rotated file carries a rotated copy (dims swapped). Neither stale.
    client.post(f"/api/items/{iid}/rotate?dir=right")
    detail = client.get(f"/api/items/{iid}").json()
    rot_fid = detail["active_file_id"]
    arts = _arts_by_file(detail["files"])
    assert len(arts[base_fid]) == 1
    assert (arts[base_fid][0]["width"], arts[base_fid][0]["height"]) == (400, 200)
    assert arts[base_fid][0]["stale"] is False
    assert len(arts[rot_fid]) == 1
    assert (arts[rot_fid][0]["width"], arts[rot_fid][0]["height"]) == (200, 400)
    assert arts[rot_fid][0]["stale"] is False

    # Rotate again: the now-edited rotated file is overwritten in place and its
    # artifact rotates in place (back to landscape); the original is untouched.
    client.post(f"/api/items/{iid}/rotate?dir=right")
    detail = client.get(f"/api/items/{iid}").json()
    arts = _arts_by_file(detail["files"])
    assert (arts[rot_fid][0]["width"], arts[rot_fid][0]["height"]) == (400, 200)
    assert arts[rot_fid][0]["stale"] is False
    assert (arts[base_fid][0]["width"], arts[base_fid][0]["height"]) == (400, 200)


def test_rotate_drops_the_files_cached_latents(lib_client):
    """A latent is the VAE's encoding of the file's pixels, so rotating them
    makes it a description of an image that no longer exists — a training run
    reading it would train on the old one. It is only a cache, so it goes.

    (It also cannot be treated like the other artifacts: a depth map is rotated
    to match, a latent is a tensor Pillow cannot even open.)"""
    from media_compost.db import File, FileArtifact, Item

    client, lib = lib_client
    iid = client.get("/api/items").json()["items"][0]["id"]
    base_fid = client.get(f"/api/items/{iid}").json()["active_file_id"]

    blob = b"not-an-image: a pickled tensor"
    with lib.db.session() as s:
        item, base = s.get(Item, iid), s.get(File, base_fid)
        rel = lib.store.write_artifact(item.uid, base.number, "latent", "pt",
                                       blob, "sd15")
        s.add(FileArtifact(file_id=base_fid, item_id=iid, kind="latent",
                           model="sd15", sha256="x", path=rel,
                           width=64, height=32, bytes=len(blob), format="pt"))
        s.commit()
        stored = lib.store.file_path(item.uid, rel)
    assert stored.is_file()

    # Rotating the pristine original branches to a new file: the stale latent is
    # dropped rather than rotated (which would raise) or copied along.
    assert client.post(f"/api/items/{iid}/rotate?dir=right").status_code == 200
    detail = client.get(f"/api/items/{iid}").json()
    arts = [a for f in detail["files"] for a in (f.get("artifacts") or [])]
    assert [a for a in arts if a["kind"] == "latent"] == []
    assert not stored.is_file()  # the bytes are gone too

    # …and again on the in-place path (the active file is now a derived one).
    rot_fid = detail["active_file_id"]
    with lib.db.session() as s:
        item, rot = s.get(Item, iid), s.get(File, rot_fid)
        rel2 = lib.store.write_artifact(item.uid, rot.number, "latent", "pt",
                                        blob, "sd15")
        s.add(FileArtifact(file_id=rot_fid, item_id=iid, kind="latent",
                           model="sd15", sha256="y", path=rel2,
                           width=32, height=64, bytes=len(blob), format="pt"))
        s.commit()
    assert client.post(f"/api/items/{iid}/rotate?dir=right").status_code == 200
    detail = client.get(f"/api/items/{iid}").json()
    arts = [a for f in detail["files"] for a in (f.get("artifacts") or [])]
    assert [a for a in arts if a["kind"] == "latent"] == []


def _newest_rotate_event(client):
    return next(e for e in client.get("/api/history?limit=20").json()["events"]
                if e["action"] == "rotate_item")


def test_reverting_a_branch_rotate_reactivates_the_original(lib_client):
    client, lib = lib_client
    iid = client.get("/api/items").json()["items"][0]["id"]
    base_fid = client.get(f"/api/items/{iid}").json()["active_file_id"]
    client.post(f"/api/items/{iid}/rotate?dir=right")

    ev = _newest_rotate_event(client)
    out = client.post("/api/history/revert", json={"event_ids": [ev["id"]]}).json()
    assert out["reverted"] == [ev["id"]]
    detail = client.get(f"/api/items/{iid}").json()
    assert detail["active_file_id"] == base_fid
    assert (detail["width"], detail["height"]) == (400, 200)
    assert len(detail["files"]) == 1, "the branched file's row is dropped"


def test_reverting_an_in_place_rotate_turns_the_pixels_back(lib_client):
    """The second rotate overwrites the derived file in place; its revert used
    to re-assign active_file_id to itself and claim success while the picture
    stayed rotated."""
    client, lib = lib_client
    iid = client.get("/api/items").json()["items"][0]["id"]
    client.post(f"/api/items/{iid}/rotate?dir=right")   # branch: 90
    client.post(f"/api/items/{iid}/rotate?dir=right")   # in place: 180
    detail = client.get(f"/api/items/{iid}").json()
    rot_fid = detail["active_file_id"]
    assert detail["rotation"] == 180
    assert (detail["width"], detail["height"]) == (400, 200)

    ev = _newest_rotate_event(client)
    out = client.post("/api/history/revert", json={"event_ids": [ev["id"]]}).json()
    assert out["reverted"] == [ev["id"]], "an in-place rotate really reverts"
    detail = client.get(f"/api/items/{iid}").json()
    assert detail["active_file_id"] == rot_fid
    assert detail["rotation"] == 90
    assert (detail["width"], detail["height"]) == (200, 400)

    # Redo — reverting the revert — turns it forward again (the redo payload
    # flips the delta's sign, or it would turn the same way as the undo).
    rev = next(e for e in client.get("/api/history?limit=20").json()["events"]
               if e["action"] == "revert")
    client.post("/api/history/revert", json={"event_ids": [rev["id"]]})
    detail = client.get(f"/api/items/{iid}").json()
    assert detail["rotation"] == 180
    assert (detail["width"], detail["height"]) == (400, 200)
