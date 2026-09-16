"""Places — where a picture is.

A place is ONE address line, a coordinate pair and the place it is INSIDE.
Containment used to live in the address components — a record saying
city=Tokyo answered "in Tokyo" — which worked only while every place carried
a full structured address and could never say
that a venue is inside a park inside a city. It is a PARENT now, and the
parent is an ordinary tag implication, which is what these tests pin: the
child's items answer the parent's question because they carry the parent's
tag.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.importer import ImportOptions, Importer
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
        c.lib = lib  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


def _items(client) -> list[int]:
    return [it["id"] for it in client.get("/api/items").json()["items"]]


def _q(client, cond):
    body = {"query": {"type": "group", "op": "and", "neg": False,
                      "children": [cond]}}
    return [i["id"] for i in client.post("/api/items/query", json=body).json()["items"]]


def _place(client, **body):
    rows = client.post("/api/places", json=body).json()
    return rows


def _by_tag(client, tag: str) -> dict:
    """The row for one tag. The create/update endpoints answer with the WHOLE
    list (sorted), so indexing it names whichever place sorts first."""
    return next(r for r in client.get("/api/places").json() if r["tag"] == tag)


# ---- containment out of the data -------------------------------------------

def test_a_place_inside_another_answers_for_both(client):
    """The whole of the hierarchy: assigning the child assigns the parent,
    because setting the parent wrote the implication between their tags. The
    search learns nothing new — the item genuinely carries `tokyo`."""
    a, b = _items(client)[:2]
    _place(client, tag="tokyo", name="Tokyo, Japan")
    tokyo = _by_tag(client, "tokyo")["id"]
    _place(client, tag="shibuya_crossing", parent_id=tokyo,
           name="Shibuya Scramble, Shibuya, Tokyo")
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "tokyo", "negative": False})
    client.post(f"/api/tags/assign/item/{b}",
                json={"tag": "shibuya_crossing", "negative": False})

    assert sorted(_q(client, {"type": "place", "op": "=",
                              "value": "Tokyo, Japan"})) == sorted([a, b]), \
        "the specific place IMPLIES the broad one, so its items answer for it"
    assert _q(client, {"type": "place", "value": "scramble"}) == [b]
    # The CHILD has no "Japan" in its own address — it answers because it
    # carries the parent's tag, which is what the implication buys.
    assert sorted(_q(client, {"type": "place", "value": "Japan"})) == sorted([a, b])


def test_the_address_is_the_whole_of_what_a_place_says(client):
    """One free text line, matched as free text — no components, no country
    field, and no code table behind the search."""
    item = _items(client)[0]
    _place(client, tag="tokyo", name="Shibuya, Tokyo, Japan")
    client.post(f"/api/tags/assign/item/{item}", json={"tag": "tokyo", "negative": False})

    assert _q(client, {"type": "place", "op": "=",
                       "value": "Shibuya, Tokyo, Japan"}) == [item]
    assert _q(client, {"type": "place", "value": "japan"}) == [item]
    assert _q(client, {"type": "place", "op": "=", "value": "Germany"}) == []
    # The identity TAG is not searched here: `tokyo` is a tag, and the tag
    # condition is what answers for one — better, since it folds sequence
    # containers where this deliberately does not.
    assert _q(client, {"type": "place", "op": "=", "value": "tokyo"}) == []


def test_a_place_is_matched_on_its_one_line(client):
    """A place has ONE searchable field, and a component of it — the city —
    is simply part of that line."""
    item = _items(client)[0]
    _place(client, tag="tokyo", name="Shibuya, Tokyo")
    client.post(f"/api/tags/assign/item/{item}", json={"tag": "tokyo", "negative": False})
    assert _q(client, {"type": "place", "value": "Tokyo"}) == [item]


def test_a_bare_place_condition_asks_whether_there_is_one(client):
    a, b = _items(client)[:2]
    _place(client, tag="tokyo", name="Tokyo")
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "tokyo", "negative": False})
    assert _q(client, {"type": "place"}) == [a]
    rest = _q(client, {"type": "place", "have": False})
    assert a not in rest and b in rest


def test_an_abstract_place_is_still_a_place(client):
    """No address at all — just a tag. Assignable and searchable, only not
    placeable on a map."""
    item = _items(client)[0]
    _place(client, name="Bob's House")
    rows = client.get("/api/places").json()
    assert rows[0]["tag"] == "place:bob_s_house"
    client.post(f"/api/tags/assign/item/{item}",
                json={"tag": "place:bob_s_house", "negative": False})
    assert _q(client, {"type": "place", "value": "bob"}) == [item]


# ---- the value autocomplete ------------------------------------------------

def test_the_list_is_searched_by_the_address_and_the_tag(client):
    """The two things a place says. There is nothing else left to match on."""
    _place(client, tag="a", name="Invalidenstraße 43, Berlin")
    _place(client, tag="b", name="Torstraße 1, Berlin")
    _place(client, tag="d", name="Tokyo")

    rows = client.get("/api/places", params={"q": "berlin"}).json()
    assert sorted(r["tag"] for r in rows) == ["a", "b"]
    assert [r["tag"] for r in client.get("/api/places",
                                         params={"q": "tokyo"}).json()] == ["d"]


# ---- unnamed places --------------------------------------------------------

def test_naming_an_unnamed_place_moves_its_items_onto_the_tag(client):
    """A photo's bare GPS makes a place nobody can name — no geocoder here.
    Naming it later mints the tag and back-fills it, like naming a face."""
    from media_compost.db import ItemLocation, Location

    a, b = _items(client)[:2]
    rows = _place(client, lat=51.5194, lon=-0.127)
    pid = rows[0]["id"]
    assert rows[0]["tag"] == ""
    lib = app.dependency_overrides[get_library]()
    with lib.db.session() as s:
        for item in (a, b):
            s.add(ItemLocation(item_id=item, location_id=pid))
        s.commit()
    assert client.get("/api/places").json()[0]["items"] == 2

    client.patch(f"/api/places/{pid}", json={"tag": "the_british_museum"})
    detail = client.get(f"/api/items/{a}").json()
    assert "the_british_museum" in [t["name"] for t in detail["tags"]]
    with lib.db.session() as s:
        assert s.query(ItemLocation).count() == 0, "pinned rows move onto the tag"
    assert client.get("/api/places").json()[0]["items"] == 2


def test_naming_an_unnamed_place_reverts(client):
    from media_compost.db import ItemLocation

    a = _items(client)[0]
    pid = _place(client, lat=51.5194, lon=-0.127)[0]["id"]
    lib = app.dependency_overrides[get_library]()
    with lib.db.session() as s:
        s.add(ItemLocation(item_id=a, location_id=pid))
        s.commit()
    client.patch(f"/api/places/{pid}", json={"tag": "museum"})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "name_place")
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    detail = client.get(f"/api/items/{a}").json()
    assert "museum" not in [t["name"] for t in detail["tags"]]


# ---- editing ---------------------------------------------------------------

def test_a_place_can_be_taken_out_of_its_parent(client):
    """`parent_id: null` cannot say it — that is also what "the caller did not
    mention the parent" looks like — so there is a flag, and taking the place
    out takes the IMPLICATION with it."""
    _place(client, tag="japan", name="")
    japan = _by_tag(client, "japan")["id"]
    _place(client, tag="tokyo", parent_id=japan)
    pid = _by_tag(client, "tokyo")["id"]
    implies = {t["name"]: t.get("implies", [])
               for t in client.get("/api/tags").json()}
    assert implies["tokyo"] == ["japan"]

    client.patch(f"/api/places/{pid}", json={"clear_parent": True})
    assert client.get("/api/places").json()
    row = next(r for r in client.get("/api/places").json() if r["id"] == pid)
    assert row["parent_id"] is None
    implies = {t["name"]: t.get("implies", [])
               for t in client.get("/api/tags").json()}
    assert implies["tokyo"] == []


def test_a_place_cannot_be_inside_itself(client):
    _place(client, tag="japan", name="")
    japan = _by_tag(client, "japan")["id"]
    _place(client, tag="tokyo", parent_id=japan)
    tokyo = _by_tag(client, "tokyo")["id"]
    assert client.patch(f"/api/places/{tokyo}",
                        json={"parent_id": tokyo}).status_code == 400
    assert client.patch(f"/api/places/{japan}",
                        json={"parent_id": tokyo}).status_code == 400


def test_redoing_an_edit_restores_every_field_it_changed(client):
    """The redo mapper used to swap one field and nothing else, so a redo put
    that field back and left the address and the coordinates at the values the
    UNDO had restored — a redo that half-worked, silently."""
    pid = _place(client, tag="x", name="Berlin",
                 lat=52.52, lon=13.40)[0]["id"]
    client.patch(f"/api/places/{pid}", json={
        "name": "Tokyo", "lat": 35.68, "lon": 139.69})

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "edit_place")
    undo = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    row = client.get("/api/places").json()[0]
    assert row["name"] == "Berlin"
    assert row["lat"] == 52.52

    # Reverting the revert IS the redo — the whole of it, not a third of it.
    client.post("/api/history/revert",
                json={"event_ids": undo.json()["events"]})
    row = client.get("/api/places").json()[0]
    assert row["name"] == "Tokyo"
    assert row["lat"] == 35.68 and row["lon"] == 139.69


def test_deleting_a_place_keeps_its_tag_by_default(client):
    pid = _place(client, tag="berlin", name="Berlin")[0]["id"]
    client.delete(f"/api/places/{pid}")
    assert client.get("/api/places").json() == []
    assert any(t["name"] == "berlin" for t in client.get("/api/tags").json()), \
        "the pictures were still taken somewhere"


def test_a_place_and_a_subject_cannot_claim_one_tag_twice(client):
    _place(client, tag="berlin", name="Berlin")
    assert client.post("/api/places", json={
        "tag": "berlin"}).status_code == 409


def test_naming_an_unnamed_place_cannot_steal_another_places_tag(client):
    """The PATCH naming path makes the same refusal create does — two
    Location rows on one tag is a state the search map assumes away."""
    _place(client, tag="berlin", name="Berlin")
    rows = _place(client, lat=52.52, lon=13.405)
    pid = rows[0]["id"]
    assert rows[0]["tag"] == ""
    r = client.patch(f"/api/places/{pid}", json={"tag": "berlin"})
    assert r.status_code == 409
    assert client.get("/api/places").json()  # still one owner for the tag
    owners = [p for p in client.get("/api/places").json()
              if p["tag"] == "berlin"]
    assert len(owners) == 1


# ---- from the file itself, on import ---------------------------------------

def _photo(path: Path, colour: tuple[int, int, int], *, xmp: bytes | None = None,
           gps: tuple[str, int] | None = None) -> None:
    """A tiny JPEG carrying a location the way a camera or an editor writes it."""
    from fractions import Fraction

    from PIL import Image

    im = Image.new("RGB", (64, 64), colour)
    kwargs: dict = {}
    if xmp is not None:
        kwargs["xmp"] = xmp
    if gps is not None:
        hemisphere, seconds = gps
        exif = im.getexif()
        block = exif.get_ifd(0x8825)
        block[1] = hemisphere
        block[2] = (Fraction(51), Fraction(31), Fraction(seconds))
        block[3] = "W"
        block[4] = (Fraction(0), Fraction(7), Fraction(37))
        kwargs["exif"] = exif
    im.save(path, "JPEG", **kwargs)


TOKYO_XMP = (b'<x:xmpmeta><rdf:Description photoshop:City="Tokyo" '
             b'photoshop:State="Tokyo" photoshop:Country="Japan" '
             b'Iptc4xmpCore:Location="Shibuya"/></x:xmpmeta>')


@pytest.fixture
def photos(tmp_path: Path):
    """A folder of photos: two naming Tokyo, three with only coordinates (two of
    them at the same spot)."""
    src = tmp_path / "photos"
    src.mkdir()
    _photo(src / "a.jpg", (10, 200, 30), xmp=TOKYO_XMP)
    _photo(src / "b.jpg", (200, 10, 30), xmp=TOKYO_XMP)
    _photo(src / "c.jpg", (10, 30, 200), gps=("N", 1))
    _photo(src / "d.jpg", (90, 30, 200), gps=("N", 2))   # ~30 m away
    _photo(src / "e.jpg", (5, 90, 90), gps=("N", 40))    # ~1.2 km away
    return src


@pytest.fixture
def imported(tmp_path: Path, photos: Path):
    cfg = UiConfig(data_dir=tmp_path / "phdata")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([photos], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_import_creates_no_place_and_indexes_what_the_file_says(imported):
    """The importer used to MINT places — named ones from XMP/IPTC, unnamed
    ones from bare GPS — and a crawl of random web images filled the Places
    list with strangers' coordinates. Nothing is created now; what the file
    says is indexed as its own metadata, searchable and visible, and the
    Places section OFFERS the named claim instead."""
    assert imported.get("/api/places").json() == []
    # The facts survived, as metadata: the named claim...
    assert len(_q(imported, {"type": "meta", "name": "location", "op": "=",
                             "value": "Shibuya, Tokyo, Tokyo, Japan"})) == 2
    # ...and the bare coordinates.
    assert len(_q(imported, {"type": "meta", "name": "gps_lat", "op": ">=",
                             "value": 0})) == 3


def test_the_files_own_place_is_offered_and_accepting_creates_it(imported):
    """Accept = what the importer used to do silently, done deliberately —
    and WITH the configured place prefix, which the importer's minting
    always skipped."""
    items = _q(imported, {"type": "meta", "name": "location", "op": "=",
                          "value": "Shibuya, Tokyo, Tokyo, Japan"})
    first, second = items[0], items[1]

    got = imported.get(f"/api/events/suggestions/{first}").json()
    fp = got["file_place"]
    assert fp["name"] == "Shibuya, Tokyo, Tokyo, Japan"
    assert fp["place"] is None, "nothing exists until somebody accepts"

    after = imported.post("/api/events/adopt-file-place",
                          json={"item_id": first}).json()
    assert after["file_place"] is None, "answered — not offered again"
    named = [p for p in imported.get("/api/places").json() if p["tag"]]
    assert len(named) == 1
    assert named[0]["tag"] == "place:shibuya", \
        "the finest component, WITH the configured prefix"
    assert len(_q(imported, {"type": "tag", "name": "place:shibuya"})) == 1

    # The second photo's offer now names the EXISTING place, and accepting
    # reuses it rather than minting a twin.
    got2 = imported.get(f"/api/events/suggestions/{second}").json()
    assert got2["file_place"]["place"]["id"] == named[0]["id"]
    imported.post("/api/events/adopt-file-place", json={"item_id": second})
    assert len([p for p in imported.get("/api/places").json() if p["tag"]]) == 1
    assert len(_q(imported, {"type": "tag", "name": "place:shibuya"})) == 2


def test_dismissing_the_files_place_sticks_and_reverts(imported):
    items = _q(imported, {"type": "meta", "name": "location", "op": "=",
                          "value": "Shibuya, Tokyo, Tokyo, Japan"})
    iid = items[0]
    after = imported.post("/api/events/dismiss-file-place",
                          json={"item_id": iid}).json()
    assert after["file_place"] is None
    assert imported.get(f"/api/events/suggestions/{iid}").json()["file_place"] \
        is None, "saying no sticks"
    assert imported.get("/api/places").json() == []
    # And it is logged and revertible like every other answer.
    ev = imported.get("/api/history").json()["events"][0]
    assert ev["action"] == "dismiss_file_place"
    r = imported.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.status_code == 200, r.text
    assert imported.get(f"/api/events/suggestions/{iid}").json()["file_place"] \
        is not None, "the offer is back"


def test_bare_coordinates_are_the_items_own_and_mint_nothing(imported):
    """A coordinate pair is a fact about the PICTURE, not a place: the map
    reads it straight off the indexed metadata, and no unnamed Location row
    exists for anybody to have to tidy up."""
    from media_compost.db import ItemLocation, Location

    items = _q(imported, {"type": "meta", "name": "gps_lat", "op": ">=",
                          "value": 0})
    assert len(items) == 3
    detail = imported.get(f"/api/items/{items[0]}").json()
    assert detail["lat"] is not None and detail["lon"] is not None
    # No suggestion either: "create a place at 51.52, -0.13" is not a
    # question anybody can answer without a geocoder.
    got = imported.get(f"/api/events/suggestions/{items[0]}").json()
    assert got["file_place"] is None


