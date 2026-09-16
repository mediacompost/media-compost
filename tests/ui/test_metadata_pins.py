"""Pinning a value to the item, and muting one away — through the API.

The Info tab is TWO lists and the split is the feature: what the item answers
with, and what its other files merely say. A value from a non-active file is
never added to the first until somebody pins it, and search then finds the item
by BOTH values until the active file's is muted.

Covered here rather than in the golden history scenario deliberately, the way
`test_tags_history_audit.py` covers its own tab: extending that scenario would
move the `events` list, which is the one thing about it that must not move.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ExifTags

from media_compost.db import File, Item, ItemMetaMute, ItemMetaPin, ItemMetadata
from media_compost.importer import Importer, ImportOptions
from media_compost.testing import search_items
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


def _jpeg(path: Path, *, make: str, iso: int, seed: int = 1) -> Path:
    """A picture whose PIXELS depend on `seed` alone, so two files can be the
    same picture and disagree about what they say."""
    im = Image.new("RGB", (240, 180), (10, 20, 30))
    for x in range(240):
        for y in range(0, 180, 30):
            im.putpixel((x, y + (seed * 5 + x // 6) % 30),
                        ((x * 7) % 256, (seed * 53) % 256, (x * 3) % 256))
    exif = im.getexif()
    exif[271] = make
    exif.get_ifd(ExifTags.IFD.Exif)[34855] = iso
    im.save(path, "JPEG", quality=95, exif=exif)
    return path


@pytest.fixture
def client(tmp_path: Path):
    """One item with TWO files: the active one says Canon/400, the other
    Nikon/1600. That is the shape a re-saved copy folds into."""
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    a = _jpeg(tmp_path / "a.jpg", make="Canon", iso=400, seed=3)
    b = tmp_path / "b.jpg"
    with Image.open(a) as im:
        px = im.copy()
    exif = px.getexif()
    exif[271] = "Nikon"
    exif.get_ifd(ExifTags.IFD.Exif)[34855] = 1600
    px.save(b, "JPEG", quality=95, exif=exif)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [a, b], ImportOptions(folders_as_groups=False))
        s.commit()
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _info(c, iid) -> dict:
    return c.get(f"/api/items/{iid}/metadata").json()


def _row(block, key):
    return next((f for f in block if f["key"] == key), None)


def test_the_other_file_is_offered_and_not_applied(client):
    c, lib = client
    iid = c.get("/api/items").json()["items"][0]["id"]
    info = _info(c, iid)
    main_makes = [f["value"] for f in info["fields"] if f["key"] == "Make"]
    other_makes = [f["value"] for f in info["others"] if f["key"] == "Make"]
    assert len(main_makes) == 1, "only the active file's value is applied"
    assert len(other_makes) == 1, "the other file's value is offered"
    assert main_makes[0] != other_makes[0]
    # An offered value is SHOWN and is not what search would find the item by.
    assert _row(info["others"], "Make")["filter_value"] is None
    assert _row(info["others"], "Make")["sources"][0]["active"] is False
    # It says which file, by the number the Files tab names files by.
    assert _row(info["others"], "Make")["sources"][0]["number"] in (1, 2)


def test_pinning_adds_a_value_that_search_also_finds(client):
    c, lib = client
    iid = c.get("/api/items").json()["items"][0]["id"]
    info = _info(c, iid)
    mine = _row(info["fields"], "Make")["value"]
    theirs = _row(info["others"], "Make")["value"]
    fid = _row(info["others"], "Make")["sources"][0]["file_id"]

    def finds(value: str) -> bool:
        got = search_items(c, {"type": "meta", "name": "camera_make",
                               "mtype": "text", "op": "=", "value": value})
        return iid in [i["id"] for i in got["items"]]

    assert finds(mine) and not finds(theirs)

    r = c.post(f"/api/items/{iid}/metadata/pin",
               json={"name": "camera_make", "file_id": fid})
    assert r.status_code == 200, r.text

    # BOTH are true of the item now — a pin sits beside the file's answer
    # rather than replacing it.
    assert finds(mine) and finds(theirs)
    info = _info(c, iid)
    makes = {f["value"]: f for f in info["fields"] if f["key"] == "Make"}
    assert set(makes) == {mine, theirs}
    assert makes[theirs]["pinned"] is True
    assert makes[mine]["pinned"] is False
    # …and it is no longer repeated in the offer below.
    assert not [f for f in info["others"] if f["key"] == "Make"]

    # Muting the file's own value is what makes the pin an override.
    assert c.post(f"/api/items/{iid}/metadata/mute",
                  json={"name": "camera_make"}).status_code == 200
    assert finds(theirs) and not finds(mine)
    info = _info(c, iid)
    makes = {f["value"]: f for f in info["fields"] if f["key"] == "Make"}
    assert makes[mine]["muted"] is True, "still shown, with a way back"
    assert makes[mine]["filter_value"] is None, "and not searched"

    # Both ways back.
    assert c.post(f"/api/items/{iid}/metadata/unmute",
                  json={"name": "camera_make"}).status_code == 200
    assert c.post(f"/api/items/{iid}/metadata/unpin",
                  json={"name": "camera_make", "raw": theirs}).status_code == 200
    assert finds(mine) and not finds(theirs)


def test_a_pin_survives_the_active_file_changing(client):
    """The whole point of promoting a value to the item."""
    c, lib = client
    iid = c.get("/api/items").json()["items"][0]["id"]
    info = _info(c, iid)
    theirs = _row(info["others"], "Make")["value"]
    fid = _row(info["others"], "Make")["sources"][0]["file_id"]
    c.post(f"/api/items/{iid}/metadata/pin",
           json={"name": "camera_make", "file_id": fid})

    with lib.db.session() as s:
        item = s.get(Item, iid)
        other = s.execute(
            File.__table__.select().where(File.item_id == iid)
        ).all()
        assert len(other) == 2
        item.active_file_id = next(f.id for f in
                                   s.query(File).filter(File.item_id == iid)
                                   if f.id != item.active_file_id)
        s.commit()

    got = search_items(c, {"type": "meta", "name": "camera_make",
                           "mtype": "text", "op": "=", "value": theirs})
    assert iid in [i["id"] for i in got["items"]]


def test_every_action_is_logged_and_reverts(client):
    """The Tags tab's rule, applied here: each of the four writes an event, and
    each of those puts the state back."""
    c, lib = client
    iid = c.get("/api/items").json()["items"][0]["id"]
    fid = _row(_info(c, iid)["others"], "Make")["sources"][0]["file_id"]

    def latest() -> dict:
        return c.get("/api/history?limit=1").json()["events"][0]

    def revert(ev_id: int) -> None:
        r = c.post("/api/history/revert", json={"event_ids": [ev_id]})
        assert r.status_code == 200, r.text
        assert r.json()["reverted"] == [ev_id], r.text

    for call, action, check in (
        (lambda: c.post(f"/api/items/{iid}/metadata/pin",
                        json={"name": "camera_make", "file_id": fid}),
         "pin_metadata", ItemMetaPin),
        (lambda: c.post(f"/api/items/{iid}/metadata/mute",
                        json={"name": "camera_make"}),
         "mute_metadata", ItemMetaMute),
    ):
        before = c.post("/api/items/query", json={}).json()["total"]
        assert call().status_code == 200
        ev = latest()
        assert ev["action"] == action, ev
        with lib.db.session() as s:
            assert s.query(check).count() == 1
        revert(ev["id"])
        with lib.db.session() as s:
            assert s.query(check).count() == 0, f"{action} did not revert"
        assert c.post("/api/items/query", json={}).json()["total"] == before


def test_an_intrinsic_name_cannot_be_pinned(client):
    """Width is read live off whichever file is active, so a pin on it would
    show in the panel and change nothing any search could see."""
    c, lib = client
    iid = c.get("/api/items").json()["items"][0]["id"]
    fid = _info(c, iid)["fields"][0]  # any file will do; the name is refused
    with lib.db.session() as s:
        fid = s.query(File).filter(File.item_id == iid).first().id
    r = c.post(f"/api/items/{iid}/metadata/pin",
               json={"name": "width", "file_id": fid})
    assert r.status_code == 400
    assert "cannot be pinned" in r.json()["detail"]


def test_a_pin_and_a_mute_survive_a_folder_round_trip(client, tmp_path):
    """A pin and a mute are decisions somebody made about which of several
    files to believe, recoverable from no file's bytes — the class of thing the
    round-trip audit exists to protect (`Item.taken_at` is the other). And the
    NON-ACTIVE file's own metadata travels too, which is the half a re-import
    could not restore before, because it was never read in the first place."""
    from media_compost.db import Database
    from media_compost.libimport import merge_library
    from media_compost.storage import ItemStore

    c, lib = client
    iid = c.get("/api/items").json()["items"][0]["id"]
    info = _info(c, iid)
    theirs = _row(info["others"], "Make")["value"]
    fid = _row(info["others"], "Make")["sources"][0]["file_id"]
    c.post(f"/api/items/{iid}/metadata/pin",
           json={"name": "camera_make", "file_id": fid})
    c.post(f"/api/items/{iid}/metadata/mute", json={"name": "iso"})

    new_cfg = UiConfig(data_dir=tmp_path / "restored")
    new_db = Database(new_cfg)
    with new_db.session() as s:
        stats = merge_library(s, ItemStore(new_cfg), new_cfg,
                              lib.config.data_dir)
        assert not stats.errors, stats.errors
    with new_db.session() as s:
        item = s.query(Item).one()
        pins = s.query(ItemMetaPin).all()
        assert [(p.name, p.raw) for p in pins] == [("camera_make", theirs)]
        assert [m.name for m in s.query(ItemMetaMute).all()] == ["iso"]
        # BOTH files' own answers came back — including the one no build before
        # this ever read.
        makes = {f.id: None for f in s.query(File).all()}
        from media_compost.db import FileMetadata
        for fm in s.query(FileMetadata).filter(
                FileMetadata.name == "camera_make").all():
            makes[fm.file_id] = fm.raw
        assert sorted(v for v in makes.values() if v) == sorted(
            {"Canon", "Nikon"})
        # …and the derived index reflects the mute rather than the file.
        names = {m.name for m in s.query(ItemMetadata)
                 .filter(ItemMetadata.item_id == item.id).all()}
        assert "iso" not in names, "the mute survived and still applies"
    new_db.engine.dispose()


def test_the_pin_routes_reject_an_unknown_field(client):
    """A body inherits RequestModel, so a misspelling is a visible 422 rather
    than a silently different call."""
    c, _lib = client
    iid = c.get("/api/items").json()["items"][0]["id"]
    r = c.post(f"/api/items/{iid}/metadata/mute",
               json={"name": "camera_make", "nmae": "typo"})
    assert r.status_code == 422


def test_the_catalog_counts_an_item_once_when_it_is_both_indexed_and_pinned(
        client):
    """The metadata catalog has TWO query shapes and they must agree.

    A pin sits BESIDE the active file's answer, so one item can be in both
    halves of the union for one name — `count(distinct item_id)` over the
    union is deliberately not the sum of the halves. The catalog skips the
    union entirely while nothing is pinned, because a compound subquery is
    materialized as a co-routine and no index can reach through it; this is
    what says the branch it falls back to answers the same question.
    """
    c, lib = client
    iid = c.get("/api/items").json()["items"][0]["id"]
    info = _info(c, iid)
    fid = _row(info["others"], "Make")["sources"][0]["file_id"]

    def entry(name: str) -> dict | None:
        for e in c.get("/api/metadata/catalog").json():
            if e["name"] == name:
                return e
        return None

    before = entry("camera_make")
    assert before is not None and before["count"] >= 1

    r = c.post(f"/api/items/{iid}/metadata/pin",
               json={"name": "camera_make", "file_id": fid})
    assert r.status_code == 200, r.text

    after = entry("camera_make")
    assert after is not None
    # The item now answers TWO values for the name and is still ONE item.
    assert after["count"] == before["count"], (before, after)
    # …and the pinned value joined the enumerated dropdown.
    assert after["values"] is not None
    assert len(after["values"]) > len(before["values"] or [])
