"""Editor transforms: rotate/crop, overwrite vs derived."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from media_compost.db import File, Item
from media_compost.ui.editor import EditOps, apply_edit
from media_compost.importer import Importer, ImportOptions


def _seed(lib, images: Path):
    cfg, db, store = lib
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=False)
        )
    return cfg, db, store


def test_overwrite_keeps_original_and_activates_new(lib, images: Path):
    cfg, db, store = _seed(lib, images)
    with db.session() as s:
        item = s.execute(select(Item).limit(1)).scalars().first()
        src = s.get(File, item.active_file_id)
        before = src.width, src.height
        res = apply_edit(
            s, store, cfg, item.id, src.id,
            EditOps(rotate=90, crop=None), "overwrite",
        )
        s.commit()
    with db.session() as s:
        item = s.get(Item, res["item_id"])
        new = s.get(File, item.active_file_id)
        old = s.get(File, res["file_id"]).derived_from_file_id
        # Rotated 90°: dimensions swapped.
        assert (new.width, new.height) == (before[1], before[0])
        assert new.is_derived and new.derived_from_file_id == old
        # Original retained for reference.
        kept = s.execute(
            select(func.count()).select_from(File).where(File.is_kept_original)
        ).scalar_one()
        assert kept == 1


def test_derived_creates_linked_item(lib, images: Path):
    cfg, db, store = _seed(lib, images)
    with db.session() as s:
        item = s.execute(select(Item).limit(1)).scalars().first()
        src = s.get(File, item.active_file_id)
        n_before = s.execute(select(func.count()).select_from(Item)).scalar_one()
        res = apply_edit(
            s, store, cfg, item.id, src.id,
            EditOps(crop=(0, 0, 100, 80)), "derived",
        )
        s.commit()
    with db.session() as s:
        n_after = s.execute(select(func.count()).select_from(Item)).scalar_one()
        assert n_after == n_before + 1
        derived = s.get(Item, res["item_id"])
        assert derived.link_item_id == item.id
        f = s.get(File, derived.active_file_id)
        assert (f.width, f.height) == (100, 80)


def test_save_raster_creates_version(lib, images: Path):
    import io
    from PIL import Image
    from media_compost.ui.editor import save_raster

    cfg, db, store = _seed(lib, images)
    # A client-rendered raster (e.g. after brush/fill), 120x90 solid.
    buf = io.BytesIO()
    Image.new("RGB", (120, 90), (200, 40, 40)).save(buf, "PNG")
    with db.session() as s:
        item = s.execute(select(Item).limit(1)).scalars().first()
        src = s.get(File, item.active_file_id)
        res = save_raster(
            s, store, cfg, item.id, src.id, buf.getvalue(), "overwrite",
        )
        s.commit()
    with db.session() as s:
        item = s.get(Item, res["item_id"])
        f = s.get(File, item.active_file_id)
        assert (f.width, f.height) == (120, 90) and f.is_derived


def test_crop_to_new_item_links_back_with_box(lib, images: Path):
    """Crop-to-new-item makes a standalone item (own full frame) linked back to
    the original, carrying the crop region as a bounding box on the link."""
    import io
    import json

    from PIL import Image

    from media_compost.db import Relationship
    from media_compost.ui.editor import crop_to_new_item

    cfg, db, store = _seed(lib, images)
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "PNG")
    png = buf.getvalue()
    with db.session() as s:
        item = s.execute(select(Item).limit(1)).scalars().first()
        src = s.get(File, item.active_file_id)
        n_before = s.execute(select(func.count()).select_from(Item)).scalar_one()
        res = crop_to_new_item(
            s, store, cfg, item.id, src.id, png, crop_norm=(0.25, 0.1, 0.5, 0.4)
        )
        s.commit()
    with db.session() as s:
        n_after = s.execute(select(func.count()).select_from(Item)).scalar_one()
        assert n_after == n_before + 1
        new_item = s.get(Item, res["item_id"])
        assert "_crop" in new_item.name
        nf = s.get(File, new_item.active_file_id)
        # Standalone item: its file spans its own full reference frame.
        assert (nf.crop_x, nf.crop_y, nf.crop_w, nf.crop_h) == (0.0, 0.0, 1.0, 1.0)
        assert nf.is_derived and nf.derived_from_file_id == src.id
        # The link goes from the crop *back* to the original, with the crop box.
        rel = s.execute(
            select(Relationship).where(
                Relationship.from_item_id == new_item.id,
                Relationship.to_item_id == item.id,
            )
        ).scalar_one()
        meta = json.loads(rel.meta)
        assert meta["boxes"] == [[0.25, 0.1, 0.5, 0.4]]


def test_crop_to_new_item_without_box(lib, images: Path):
    """A rotated crop passes no box; the link is created carrying none."""
    import io
    import json

    from PIL import Image

    from media_compost.db import Relationship
    from media_compost.ui.editor import crop_to_new_item

    cfg, db, store = _seed(lib, images)
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buf, "PNG")
    with db.session() as s:
        item = s.execute(select(Item).limit(1)).scalars().first()
        src = s.get(File, item.active_file_id)
        res = crop_to_new_item(s, store, cfg, item.id, src.id, buf.getvalue(), None)
        s.commit()
    with db.session() as s:
        rel = s.execute(
            select(Relationship).where(Relationship.from_item_id == res["item_id"])
        ).scalar_one()
        assert "boxes" not in json.loads(rel.meta)


def test_edit_does_not_mark_artifacts_stale(lib, images: Path):
    """A save (overwrite or derived) *adds* a new file and keeps the source
    intact, so the source's artifacts still match it — they are not staled."""
    from media_compost.db import FileArtifact

    cfg, db, store = _seed(lib, images)
    with db.session() as s:
        item = s.execute(select(Item).limit(1)).scalars().first()
        src = s.get(File, item.active_file_id)
        art = FileArtifact(file_id=src.id, item_id=item.id, kind="depth",
                           sha256="x", path="p", width=1, height=1, bytes=1)
        s.add(art)
        s.commit()
        art_id, src_id, item_id = art.id, src.id, item.id

    with db.session() as s:
        apply_edit(s, store, cfg, item_id, src_id,
                   EditOps(crop=(0, 0, 50, 50)), "derived")
        s.commit()
    with db.session() as s:
        assert s.get(FileArtifact, art_id).stale is False

    with db.session() as s:
        apply_edit(s, store, cfg, item_id, src_id, EditOps(rotate=90), "overwrite")
        s.commit()
    with db.session() as s:
        assert s.get(FileArtifact, art_id).stale is False


def test_edit_lineage_numbering_chain_and_delete(tmp_path: Path, images: Path):
    """Edited files get stable numbers (#1,#2,#3), record which file/action they
    came from plus the full chain, and deleting a middle file re-parents its
    children to the grandparent while keeping the historical chain."""
    from fastapi.testclient import TestClient

    from media_compost.ui.config import UiConfig
    from media_compost.importer import Importer, ImportOptions
    from media_compost.ui.server import deps
    from media_compost.ui.server.app import app
    from media_compost.ui.server.deps import Library, get_library

    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [images / "b.png"], ImportOptions(folders_as_groups=False)
        )
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    try:
        with TestClient(app) as c:
            iid = c.get("/api/items").json()["items"][0]["id"]
            f1 = c.get(f"/api/items/{iid}").json()["active_file_id"]
            f2 = c.post(f"/api/items/{iid}/edit", json={
                "source_file_id": f1, "rotate": 90, "save_mode": "overwrite"}).json()["file_id"]
            f3 = c.post(f"/api/items/{iid}/edit", json={
                "source_file_id": f2, "rotate": 90, "save_mode": "overwrite"}).json()["file_id"]

            byid = {f["id"]: f for f in c.get(f"/api/items/{iid}").json()["files"]}
            assert byid[f1]["number"] == 1 and byid[f1]["based_on"] is None
            assert byid[f2]["number"] == 2
            assert byid[f2]["based_on"] == 1 and byid[f2]["edit_action"] == "edit"
            assert byid[f3]["number"] == 3 and byid[f3]["based_on"] == 2
            assert byid[f3]["edit_chain"] == [
                {"from": 1, "to": 2, "action": "edit"},
                {"from": 2, "to": 3, "action": "edit"},
            ]

            # Delete the middle file → #3 re-parents to #1; number and full chain
            # (referencing the now-gone #2) are preserved.
            assert c.delete(f"/api/files/{f2}").status_code == 200
            byid = {f["id"]: f for f in c.get(f"/api/items/{iid}").json()["files"]}
            assert f2 not in byid
            assert byid[f3]["number"] == 3
            assert byid[f3]["based_on"] == 1
            assert byid[f3]["edit_chain"] == [
                {"from": 1, "to": 2, "action": "edit"},
                {"from": 2, "to": 3, "action": "edit"},
            ]

            # An irreversible file delete leaves a trace in the log.
            events = c.get("/api/history?limit=20").json()["events"]
            gone = [e for e in events if e["action"] == "delete_file"]
            assert len(gone) == 1 and gone[0]["revertible"] is False
    finally:
        app.dependency_overrides.clear()
        deps.reset_library()


def test_crop_link_kind_keeps_import_edit_chain_clean(lib, images: Path, tmp_path: Path):
    """A crop links derived -> source under its own kind="crop" (the panel
    convention, boxes on the source's frame). It used to ride on kind="edit"
    BACKWARDS, which the importer's chain walk reads as original -> derived —
    so the crop was adopted as its source's "original" and a rotated re-import
    of the original folded into the crop."""
    import io

    from PIL import Image
    from media_compost.db import Relationship
    from media_compost.ui.editor import crop_to_new_item

    cfg, db, store = _seed(lib, images)
    with db.session() as s:
        item = s.execute(select(Item).order_by(Item.id).limit(1)).scalars().first()
        iid, uid = item.id, item.uid
        src = s.get(File, item.active_file_id)
        src_path = store.file_path(uid, src.path)
        with Image.open(src_path) as im:
            crop = im.crop((0, 0, max(2, im.width // 2), max(2, im.height // 2)))
            buf = io.BytesIO()
            crop.save(buf, "PNG")
        res = crop_to_new_item(s, store, cfg, iid, src.id, buf.getvalue(),
                               crop_norm=(0.0, 0.0, 0.5, 0.5))
        crop_iid = res["item_id"]
        rel = s.execute(select(Relationship).where(
            Relationship.from_item_id == crop_iid)).scalars().one()
        assert rel.kind == "crop" and rel.to_item_id == iid

        with Image.open(src_path) as im:
            rot = im.transpose(Image.Transpose.ROTATE_90)
        rot_path = tmp_path / "rotated.png"
        rot.save(rot_path, "PNG")
        Importer(s, store, cfg).import_paths([rot_path], ImportOptions())
        s.commit()

    with db.session() as s:
        files_orig = s.execute(select(func.count()).select_from(File)
                               .where(File.item_id == iid)).scalar_one()
        files_crop = s.execute(select(func.count()).select_from(File)
                               .where(File.item_id == crop_iid)).scalar_one()
        assert files_orig >= 2, "the rotation folds into the ORIGINAL item"
        assert files_crop == 1, "…and nothing lands on the crop"
