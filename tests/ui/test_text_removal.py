"""Removing text paints out WHAT THE LIBRARY HAS READ, and nothing else.

The plugin detects nothing any more (it used to run EasyOCR's CRAFT, a
second and invisible idea of where the text on a page is); the mask comes
from the item's own `TextRegion` tree, which is the one you can see, correct
and dismiss beforehand. Two rules carry that and both fail SILENTLY when
broken — a coarse mask repaints the art inside a speech bubble, and a mask
over a dismissed region paints out what somebody said was not text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from media_compost.db import File, Item, Job, TextRegion
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def lib_client(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    src = tmp_path / "page.png"
    Image.new("RGB", (300, 300), (255, 255, 255)).save(src, "PNG")
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _item_id(lib) -> int:
    with lib.db.session() as s:
        return s.execute(select(Item.id)).scalars().first()


class _ScriptedHost:
    """A ModelHost stand-in answering per KIND, and recording what it was
    handed — the options are the whole point here."""

    def __init__(self, by_kind: dict):
        self.by_kind = by_kind
        self.calls: list[tuple[str, str, dict]] = []

    def run(self, kind, model, image, ctx, options=None):
        self.calls.append((kind, model, dict(options or {})))
        return self.by_kind.get(kind)


def test_the_mask_takes_the_smallest_boxes_and_skips_the_dismissed(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    # A block broken into two words, one of them dismissed…
    blk = client.post("/api/ocr", json={
        "item_id": iid, "x": 0.1, "y": 0.1, "w": 0.6, "h": 0.2,
        "text": "hello world"}).json()[0]["id"]
    client.post("/api/ocr", json={
        "item_id": iid, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1,
        "text": "hello", "level": "word", "parent_id": blk})
    dud = client.post("/api/ocr", json={
        "item_id": iid, "x": 0.4, "y": 0.1, "w": 0.2, "h": 0.1,
        "text": "world", "level": "word", "parent_id": blk}).json()
    dud_id = next(c["id"] for r in dud for c in r["children"]
                  if c["text"] == "world")
    client.patch(f"/api/ocr/{dud_id}", json={"dismissed": True})
    # …a block with NO breakdown, which contributes itself…
    client.post("/api/ocr", json={
        "item_id": iid, "x": 0.1, "y": 0.5, "w": 0.5, "h": 0.1,
        "text": "a bubble"})
    # …a whole block that was dismissed, which contributes nothing…
    gone = client.post("/api/ocr", json={
        "item_id": iid, "x": 0.7, "y": 0.7, "w": 0.2, "h": 0.1}).json()
    gone_id = next(r["id"] for r in gone if r["x"] == 0.7)
    client.patch(f"/api/ocr/{gone_id}", json={"dismissed": True})
    # …and a slanted line, whose QUAD is the shape rather than its box.
    client.post("/api/ocr", json={
        "item_id": iid, "x": 0.1, "y": 0.8, "w": 0.4, "h": 0.1,
        "text": "slanted"})
    slant = [r for r in client.get(f"/api/ocr/item/{iid}").json()
             if r["text"] == "slanted"][0]
    client.patch(f"/api/ocr/{slant['id']}", json={
        "quad": [[0.1, 0.82], [0.5, 0.8], [0.5, 0.9], [0.1, 0.92]]})

    with lib.db.session() as s:
        quads = lib.jobs._text_region_quads(s, s.get(Item, iid))

    assert len(quads) == 3, quads
    # The surviving WORD, not the block that holds it: a block box is the
    # whole bubble and inpainting it repaints the art inside.
    rounded = [[[round(x, 6), round(y, 6)] for x, y in q] for q in quads]
    assert [[0.1, 0.1], [0.3, 0.1], [0.3, 0.2], [0.1, 0.2]] in rounded
    # The un-broken-down block, as its own rectangle.
    assert any(q[0] == [0.1, 0.5] for q in quads)
    # The slanted line as the engine drew it, not as an upright rectangle.
    assert [[0.1, 0.82], [0.5, 0.8], [0.5, 0.9], [0.1, 0.92]] in quads


def test_two_engines_do_not_union_into_a_coarse_mask(lib_client):
    """The finest reading wins, and hand-drawn boxes ride along.

    Found live: a page read by both engines had Magi's block boxes over the
    very lines RapidOCR had broken into words, so a union threw the word
    boxes away in all but name — the mask was as coarse as the coarser
    engine, which is what this whole change exists to avoid.
    """
    client, lib = lib_client
    iid = _item_id(lib)
    with lib.db.session() as s:
        item = s.get(Item, iid)
        # A coarse reading: one block, no breakdown.
        lib.jobs._apply_ocr(s, item, [
            {"level": "block", "box": [0.1, 0.1, 0.8, 0.1], "text": "a line"},
        ], "magiv3_ocr")
        # …and a fine one over the same line, from another engine.
        lib.jobs._apply_ocr(s, item, [
            {"level": "line", "box": [0.1, 0.1, 0.8, 0.1], "text": "a line",
             "children": [
                 {"level": "word", "box": [0.1, 0.1, 0.2, 0.1], "text": "a"},
                 {"level": "word", "box": [0.5, 0.1, 0.3, 0.1], "text": "line"},
             ]},
        ], "rapidocr_multi")
        s.commit()
    # A box somebody drew is not an engine's answer and is never dropped.
    client.post("/api/ocr", json={
        "item_id": iid, "x": 0.05, "y": 0.7, "w": 0.2, "h": 0.05,
        "text": "by hand"})

    with lib.db.session() as s:
        quads = lib.jobs._text_region_quads(s, s.get(Item, iid))
    assert len(quads) == 3, quads          # two words + the hand-drawn box
    widths = sorted(round(q[1][0] - q[0][0], 3) for q in quads)
    assert widths == [0.2, 0.2, 0.3], "the coarse block survived the union"


def test_the_job_hands_the_plugin_those_quads(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    client.post("/api/ocr", json={
        "item_id": iid, "x": 0.1, "y": 0.1, "w": 0.4, "h": 0.1,
        "text": "paint me out"})
    host = _ScriptedHost({"text_removal": Image.new("RGB", (300, 300),
                                                    (10, 10, 10))})
    lib._model_host = host
    with lib.db.session() as s:
        job = Job(kind="text_removal", model="lama_regions", item_id=iid,
                  status="queued")
        s.add(job)
        s.commit()
        jid = job.id
    assert lib.jobs.run_one(jid) == "text removed"
    kind, model, options = host.calls[-1]
    assert (kind, model) == ("text_removal", "lama_regions")
    assert options["quads"] == [[[0.1, 0.1], [0.5, 0.1],
                                 [0.5, 0.2], [0.1, 0.2]]]


def test_nothing_read_means_nothing_painted(lib_client):
    client, lib = lib_client
    iid = _item_id(lib)
    lib._model_host = _ScriptedHost({"text_removal": None})
    with lib.db.session() as s:
        job = Job(kind="text_removal", model="lama_regions", item_id=iid,
                  status="queued")
        s.add(job)
        s.commit()
        jid = job.id
    assert lib.jobs.run_one(jid) == "no text found to remove"
    with lib.db.session() as s:
        assert len(s.execute(
            select(File).where(File.item_id == iid)).scalars().all()) == 1


def test_detect_and_remove_reads_first_and_KEEPS_the_reading(lib_client):
    """One job, two model runs — and the reading it makes is stored like any
    other, which is the whole reason the removal has no detector of its own:
    what was painted out is afterwards visible, correctable and revertible in
    the Text tab."""
    client, lib = lib_client
    iid = _item_id(lib)
    host = _ScriptedHost({
        "ocr": [{"level": "block", "box": [0.2, 0.2, 0.3, 0.1],
                 "text": "found by the engine", "score": 0.97,
                 "children": [{"level": "word", "box": [0.2, 0.2, 0.1, 0.1],
                               "text": "found"}]}],
        "text_removal": Image.new("RGB", (300, 300), (10, 10, 10)),
    })
    lib._model_host = host
    with lib.db.session() as s:
        job = Job(kind="text_removal", model="lama_regions", item_id=iid,
                  status="queued",
                  options=json.dumps({"detect_with": "rapidocr_multi"}))
        s.add(job)
        s.commit()
        jid = job.id
    assert lib.jobs.run_one(jid) == "text removed"

    assert [c[0] for c in host.calls] == ["ocr", "text_removal"]
    # The mask used the WORD the engine broke the block into.
    assert host.calls[-1][2]["quads"] == [[[0.2, 0.2], [0.30000000000000004, 0.2],
                                           [0.30000000000000004, 0.30000000000000004],
                                           [0.2, 0.30000000000000004]]]
    # The reading is in the library, credited to the engine that made it —
    # on the file it read, which is no longer the active one (the removal
    # made a new source), exactly as an artifact of that file would be.
    with lib.db.session() as s:
        rows = s.execute(select(TextRegion)).scalars().all()
        assert [r.text for r in rows if r.parent_id is None] == \
            ["found by the engine"]
        assert rows[0].model == "rapidocr_multi"
