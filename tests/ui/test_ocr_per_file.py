"""A text reading belongs to the FILE it was read from.

The rule the artifacts already follow, applied to text: an edited image —
a new source file made active — has no reading and reads as never-read, so
the Detect menu offers it fresh and `skip_done` does not skip it; switching
back to the old file brings its reading back untouched. Everything here is
a BEHAVIOUR check, because the binding is a WHERE clause repeated in seven
readers (the router, the badge, the run ticks, `skip_done`, the search
count, the reconcile partition, the Python API) and dropping it from any
one of them fails silently — the tab simply shows another file's text.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.db import File, Item, ItemTextRun, TextRegion
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.config import UiConfig
from media_compost.ui.editor import EditOps, apply_edit
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([images], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib          # the tests reach past the API for the edit
        yield c
    app.dependency_overrides.clear()


def _item(client) -> int:
    return client.get("/api/items").json()["items"][0]["id"]


def _read(client, item_id: int, model: str = "rapidocr_multi") -> None:
    """Pretend `model` has read the item's active file, finding nothing."""
    with client.lib.db.session() as s:
        item = s.get(Item, item_id)
        s.add(ItemTextRun(item_id=item_id, file_id=item.active_file_id,
                          model=model))
        s.commit()


def _edit(client, item_id: int) -> None:
    """Rotate the item in place — a NEW source file, made active."""
    with client.lib.db.session() as s:
        item = s.get(Item, item_id)
        apply_edit(s, client.lib.store, client.lib.config, item.id,
                   item.active_file_id, EditOps(rotate=90, crop=None),
                   "overwrite")
        s.commit()


def test_an_edited_file_starts_with_no_reading_and_the_old_one_keeps_its(
        client):
    a = _item(client)
    rid = client.post("/api/ocr", json={
        "item_id": a, "x": 0.1, "y": 0.1, "w": 0.4, "h": 0.1,
        "text": "on the original"}).json()[0]["id"]
    _read(client, a)
    with client.lib.db.session() as s:
        first_file = s.get(Item, a).active_file_id

    _edit(client, a)

    # The tab, its badge and the run ticks all answer for the NEW file.
    assert client.get(f"/api/ocr/item/{a}").json() == []
    detail = client.get(f"/api/items/{a}").json()
    assert detail["text_count"] == 0 and detail["text_models"] == []
    # …and the search count with them (the SQL path and the Python one must
    # agree, so both are asked).
    for cond in ({"type": "meta", "name": "text_blocks", "op": ">", "value": 0},):
        found = client.post("/api/items/query", json={
            "query": {"type": "group", "op": "and", "children": [cond]}}).json()
        assert a not in [i["id"] for i in found["items"]]

    # Nothing was DELETED — the old file's reading is still there, and
    # making that file active again brings it back whole.
    with client.lib.db.session() as s:
        assert s.get(TextRegion, rid).file_id == first_file
        s.get(Item, a).active_file_id = first_file
        s.commit()
    tree = client.get(f"/api/ocr/item/{a}").json()
    assert [r["text"] for r in tree] == ["on the original"]
    assert client.get(f"/api/items/{a}").json()["text_models"] \
        == ["rapidocr_multi"]


def test_skip_done_re_runs_an_edited_file(client):
    """`skip_done` counts a run over the ACTIVE file only. Without that an
    edited page would be skipped forever by the one sweep meant to catch
    exactly the pages nobody has read."""
    from media_compost.ui.server.routers.ml import _without_done

    a = _item(client)
    _read(client, a)
    assert _without_done(client.lib, "ocr", "rapidocr_multi", [a]) == []
    _edit(client, a)
    assert _without_done(client.lib, "ocr", "rapidocr_multi", [a]) == [a]


def test_a_hand_drawn_box_lands_on_the_active_file(client):
    a = _item(client)
    _edit(client, a)
    rid = client.post("/api/ocr", json={
        "item_id": a, "x": 0.2, "y": 0.2, "w": 0.3, "h": 0.1,
        "text": "on the new one"}).json()[0]["id"]
    with client.lib.db.session() as s:
        assert s.get(TextRegion, rid).file_id == s.get(Item, a).active_file_id


def test_deleting_a_file_takes_its_reading_with_it(client):
    """CASCADE, not SET NULL: a reading of pixels that no longer exist
    describes nothing, and left behind with a null file it would surface on
    whichever file happened to be active."""
    a = _item(client)
    rid = client.post("/api/ocr", json={
        "item_id": a, "x": 0.1, "y": 0.1, "w": 0.4, "h": 0.1,
        "text": "doomed"}).json()[0]["id"]
    with client.lib.db.session() as s:
        item = s.get(Item, a)
        fid = item.active_file_id
        item.active_file_id = None
        s.flush()
        s.delete(s.get(File, fid))
        s.commit()
        assert s.get(TextRegion, rid) is None


def test_a_re_run_never_reconciles_across_files(client):
    """The reconcile partition is per file too: the same box on the new file
    is a NEW region, not a match refreshing the old file's one."""
    a = _item(client)
    box = {"box": [0.1, 0.1, 0.4, 0.1], "text": "read", "level": "block"}
    jobs = client.lib.jobs
    with client.lib.db.session() as s:
        item = s.get(Item, a)
        jobs._apply_ocr(s, item, [dict(box)], "rapidocr_multi")
        s.commit()
        first = s.execute(
            TextRegion.__table__.select()).fetchall()
        assert len(first) == 1
    _edit(client, a)
    with client.lib.db.session() as s:
        item = s.get(Item, a)
        jobs._apply_ocr(s, item, [dict(box)], "rapidocr_multi")
        s.commit()
        rows = s.execute(TextRegion.__table__.select()).fetchall()
        assert len(rows) == 2, "the new file's reading merged into the old"
        assert len({r.file_id for r in rows}) == 2
