"""Events — what was happening when a picture was taken.

An event is extra data on a TAG, the third of the same kind as a subject and a
place, so these tests pin what falls out of that: assigning an event is
assigning its tag (counts and search need no new machinery), and an event's own
extras — its span of days and the places it was at — are only ever OFFERED to a
picture, never assigned to it.
"""

from __future__ import annotations

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


def _event(client, **body) -> dict:
    r = client.post("/api/events", json=body)
    assert r.status_code == 200, r.text
    name = body.get("display_name") or body.get("tag")
    return next(e for e in r.json()
                if e["display_name"] == name or e["tag"] == name)


def _place(client, **body) -> dict:
    rows = client.post("/api/places", json=body).json()
    return rows[-1] if len(rows) == 1 else next(
        p for p in rows if p["tag"] == body.get("tag"))


def _q(client, cond) -> list[int]:
    body = {"query": {"type": "group", "op": "and", "neg": False,
                      "children": [cond]}}
    return [i["id"] for i in
            client.post("/api/items/query", json=body).json()["items"]]


def _latest(client, action: str) -> dict:
    return next(e for e in client.get("/api/history?limit=50").json()["events"]
                if e["action"] == action)


# ---- the identity is a tag -------------------------------------------------

def test_a_named_event_owns_a_tag_and_its_count(client):
    """The whole design in one assertion: assigning the event is assigning its
    tag, so the count comes from the same resolver the tag list uses."""
    row = _event(client, display_name="San Diego Comic-Con 2014",
                 start_date=20140724, end_date=20140727)
    assert row["tag"] == "event:san_diego_comic_con_2014"
    assert row["items"] == 0

    a = _items(client)[0]
    client.post(f"/api/tags/assign/item/{a}", json={"tag": row["tag"]})
    assert client.get("/api/events").json()[0]["items"] == 1
    assert row["tag"] in [t["name"] for t in
                          client.get(f"/api/items/{a}").json()["tags"]]


def test_an_event_and_a_place_cannot_claim_one_tag(client):
    client.post("/api/places", json={"tag": "berlin"})
    _event(client, display_name="Berlin", tag="event:berlin_2014")
    assert client.post("/api/events", json={"tag": "berlin"}).status_code == 200, \
        "a place's tag is not an event's tag — no clash to detect"
    # But two events may not.
    assert client.post("/api/events",
                       json={"tag": "event:berlin_2014"}).status_code == 409


def test_deleting_an_event_keeps_its_tag_by_default(client):
    row = _event(client, display_name="Comic-Con")
    client.delete(f"/api/events/{row['id']}")
    assert client.get("/api/events").json() == []
    assert any(t["name"] == "event:comic_con" for t in client.get("/api/tags").json()), \
        "the tag is an ordinary tag now — the pictures are still of something"

    row = _event(client, display_name="Comic-Con 2")
    client.delete(f"/api/events/{row['id']}", params={"with_tag": True})
    assert not any(t["name"] == "event:comic_con_2"
                   for t in client.get("/api/tags").json())


# ---- the span --------------------------------------------------------------

def test_a_span_that_runs_backwards_is_refused(client):
    """Not just in the overlay: the API is reachable from scripting, and a
    backwards span makes every suggestion silently empty."""
    assert client.post("/api/events", json={
        "display_name": "Nope", "start_date": 20140727, "end_date": 20140724,
    }).status_code == 400
    assert client.post("/api/events", json={
        "display_name": "Nope", "start_date": 20141350}).status_code == 400
    # A year against a day inside it is fine — bounds, not raw comparison.
    assert client.post("/api/events", json={
        "display_name": "Fine", "start_date": 20140000, "end_date": 20140724,
    }).status_code == 200


def test_an_undated_event_sorts_last(client):
    _event(client, display_name="Whenever")
    _event(client, display_name="Comic-Con", start_date=20140724)
    assert [e["display_name"] for e in client.get("/api/events").json()] \
        == ["Comic-Con", "Whenever"]


# ---- the places ------------------------------------------------------------

def test_an_events_places_must_be_named(client):
    """A sidecar refers to other objects by tag NAME, never by row id, so an
    unnamed place could not be written down at all. Refusing it here is what
    makes the round-trip possible rather than lossy."""
    rows = client.post("/api/places", json={"lat": 32.7, "lon": -117.1}).json()
    # The endpoint answers with the whole list, sorted — the unnamed one is
    # the row with no tag, not whichever sorts first.
    bare = next(p for p in rows if not p["tag"])
    r = client.post("/api/events", json={"display_name": "SDCC",
                                         "place_ids": [bare["id"]]})
    assert r.status_code == 400 and "named" in r.text

    named = _place(client, tag="convention_center", name="San Diego")
    row = _event(client, display_name="SDCC", place_ids=[named["id"]])
    assert [p["tag"] for p in row["places"]] == ["convention_center"]


def test_the_place_list_is_replaced_whole(client):
    """Unlike a place's parts — a form of independent fields, where the kinds
    the caller did not name must survive — an event's places are a SET."""
    a = _place(client, tag="hall_h")
    b = _place(client, tag="hotel_bar")
    row = _event(client, display_name="SDCC", place_ids=[a["id"], b["id"]])
    assert len(row["places"]) == 2

    client.patch(f"/api/events/{row['id']}", json={"place_ids": [b["id"]]})
    assert [p["tag"] for p in client.get("/api/events").json()[0]["places"]] \
        == ["hotel_bar"]
    # None leaves them alone.
    client.patch(f"/api/events/{row['id']}", json={"comment": "hot"})
    assert len(client.get("/api/events").json()[0]["places"]) == 1


def test_deleting_a_place_takes_it_off_the_events_that_were_there(client):
    p = _place(client, tag="hall_h")
    row = _event(client, display_name="SDCC", place_ids=[p["id"]])
    client.delete(f"/api/places/{p['id']}")
    assert client.get("/api/events").json()[0]["places"] == []
    assert client.get("/api/events").json()[0]["id"] == row["id"], \
        "the event survives its venue"


# ---- editing ---------------------------------------------------------------

def test_editing_an_event_logs_one_event_carrying_every_field(client):
    row = _event(client, display_name="SDCC", start_date=20140724)
    client.patch(f"/api/events/{row['id']}", json={
        "display_name": "San Diego Comic-Con", "comment": "the big one",
        "end_date": 20140727})
    ev = _latest(client, "edit_event")
    assert ev["data"]["display_name"] == "San Diego Comic-Con"
    assert ev["data"]["old_display_name"] == "SDCC"
    assert ev["data"]["old_end_date"] is None


def test_redoing_an_edit_restores_every_field_it_changed(client):
    """One edit writes three fields and a place list, so the redo has to carry
    all four. A one-pair swap would put the name back and leave the span at
    whatever the undo restored. (The comment is the identity TAG's and travels
    as its own event — see `test_tags_history_audit`.)"""
    p = _place(client, tag="hall_h")
    row = _event(client, display_name="SDCC")
    client.patch(f"/api/events/{row['id']}", json={
        "display_name": "San Diego Comic-Con",
        "start_date": 20140724, "end_date": 20140727, "place_ids": [p["id"]]})

    undo = client.post("/api/history/revert",
                       json={"event_ids": [_latest(client, "edit_event")["id"]]})
    back = client.get("/api/events").json()[0]
    assert (back["display_name"], back["start_date"], back["places"]) \
        == ("SDCC", None, [])

    # Reverting the revert IS the redo — the whole of it.
    client.post("/api/history/revert",
                json={"event_ids": undo.json()["events"]})
    again = client.get("/api/events").json()[0]
    assert again["display_name"] == "San Diego Comic-Con"
    assert (again["start_date"], again["end_date"]) == (20140724, 20140727)
    assert [x["tag"] for x in again["places"]] == ["hall_h"]


def test_renaming_the_identity_tag_is_an_ordinary_tag_rename(client):
    row = _event(client, display_name="SDCC")
    client.patch(f"/api/events/{row['id']}", json={"tag": "sdcc_2014"})
    assert client.get("/api/events").json()[0]["tag"] == "sdcc_2014"
    assert any(e["action"] == "rename_tag"
               for e in client.get("/api/history").json()["events"])


# ---- searching -------------------------------------------------------------

def test_a_bare_event_condition_asks_whether_there_was_one(client):
    a, b = _items(client)[:2]
    row = _event(client, display_name="SDCC", start_date=20140724)
    client.post(f"/api/tags/assign/item/{a}", json={"tag": row["tag"]})

    assert _q(client, {"type": "event", "name": "", "have": True}) == [a]
    assert b in _q(client, {"type": "event", "name": "", "have": False})
    assert _q(client, {"type": "event", "name": row["tag"], "have": True}) == [a]


def test_a_year_matches_any_event_that_OVERLAPS_it(client):
    """An event running 30 December into 2 January answers both years, because
    it did. Overlap, not containment."""
    a, b = _items(client)[:2]
    ny = _event(client, display_name="New Year",
                start_date=20141230, end_date=20150102)
    sd = _event(client, display_name="SDCC",
                start_date=20140724, end_date=20140727)
    client.post(f"/api/tags/assign/item/{a}", json={"tag": ny["tag"]})
    client.post(f"/api/tags/assign/item/{b}", json={"tag": sd["tag"]})

    year = lambda y: {"type": "event", "name": "", "have": True,
                      "date_from": y, "date_to": y}
    assert sorted(_q(client, year(20140000))) == sorted([a, b])
    assert _q(client, year(20150000)) == [a]
    assert _q(client, year(20160000)) == []


def test_a_span_bound_only_ever_narrows(client):
    """An event nobody dated cannot satisfy one, the same rule a subject's age
    bound follows — the honest answer is that we do not know."""
    a = _items(client)[0]
    row = _event(client, display_name="Whenever")
    client.post(f"/api/tags/assign/item/{a}", json={"tag": row["tag"]})

    assert _q(client, {"type": "event", "name": "", "have": True}) == [a]
    assert _q(client, {"type": "event", "name": "", "have": True,
                       "date_from": 20140000}) == []


def test_a_negative_assignment_is_not_being_at_the_event(client):
    a = _items(client)[0]
    row = _event(client, display_name="SDCC")
    client.post(f"/api/tags/assign/item/{a}",
                json={"tag": row["tag"], "negative": True})
    assert _q(client, {"type": "event", "name": "", "have": True}) == []


# ---- suggestions -----------------------------------------------------------

def _sugg(client, item_id: int) -> dict:
    return client.get(f"/api/events/suggestions/{item_id}").json()


def test_an_events_venues_are_offered_never_assigned(client):
    """Half of a week's photographs were taken somewhere else, so the venue is
    a question rather than an answer."""
    a = _items(client)[0]
    hall = _place(client, tag="hall_h")
    bar = _place(client, tag="hotel_bar")
    ev = _event(client, display_name="SDCC",
                place_ids=[hall["id"], bar["id"]])
    client.post(f"/api/tags/assign/item/{a}", json={"tag": ev["tag"]})

    got = _sugg(client, a)
    assert sorted(p["place"]["tag"] for p in got["places"]) \
        == ["hall_h", "hotel_bar"]
    assert got["places"][0]["via_event_name"] == "SDCC"
    names = [t["name"] for t in client.get(f"/api/items/{a}").json()["tags"]]
    assert "hall_h" not in names and "hotel_bar" not in names


def test_a_place_already_on_the_picture_is_not_offered(client):
    a = _items(client)[0]
    hall = _place(client, tag="hall_h")
    ev = _event(client, display_name="SDCC", place_ids=[hall["id"]])
    client.post(f"/api/tags/assign/item/{a}", json={"tag": ev["tag"]})
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "hall_h"})
    assert _sugg(client, a)["places"] == []


def test_a_dismissal_survives_the_event_being_edited(client):
    """The whole reason it is keyed on (item, place) and not on the event that
    prompted it: editing the venue list must not resurrect a refusal."""
    a = _items(client)[0]
    hall = _place(client, tag="hall_h")
    bar = _place(client, tag="hotel_bar")
    ev = _event(client, display_name="SDCC", place_ids=[hall["id"]])
    client.post(f"/api/tags/assign/item/{a}", json={"tag": ev["tag"]})

    left = client.post("/api/events/dismiss-place", json={
        "item_id": a, "location_id": hall["id"], "via_occasion_id": ev["id"]}).json()
    assert left["places"] == []

    client.patch(f"/api/events/{ev['id']}",
                 json={"place_ids": [hall["id"], bar["id"]]})
    assert [p["place"]["tag"] for p in _sugg(client, a)["places"]] \
        == ["hotel_bar"], "the refused one stays refused"


def test_a_second_event_at_the_same_venue_does_not_re_ask(client):
    a = _items(client)[0]
    hall = _place(client, tag="hall_h")
    one = _event(client, display_name="SDCC 2014", place_ids=[hall["id"]])
    two = _event(client, display_name="SDCC 2015", place_ids=[hall["id"]])
    for ev in (one, two):
        client.post(f"/api/tags/assign/item/{a}", json={"tag": ev["tag"]})

    assert len(_sugg(client, a)["places"]) == 1, \
        "one venue, one offer, however many events were there"
    client.post("/api/events/dismiss-place",
                json={"item_id": a, "location_id": hall["id"]})
    assert _sugg(client, a)["places"] == []


def test_reverting_a_dismissal_offers_it_again(client):
    a = _items(client)[0]
    hall = _place(client, tag="hall_h")
    ev = _event(client, display_name="SDCC", place_ids=[hall["id"]])
    client.post(f"/api/tags/assign/item/{a}", json={"tag": ev["tag"]})
    client.post("/api/events/dismiss-place",
                json={"item_id": a, "location_id": hall["id"]})

    client.post("/api/history/revert",
                json={"event_ids": [_latest(client, "dismiss_place")["id"]]})
    assert [p["place"]["tag"] for p in _sugg(client, a)["places"]] == ["hall_h"]


def test_an_item_with_no_capture_date_says_so(client):
    """Silence is how "the feature doesn't work" gets reported for a library
    that only needs its metadata re-indexed."""
    a = _items(client)[0]
    _event(client, display_name="SDCC", start_date=20140724)
    got = _sugg(client, a)
    assert got["dated"] is False and got["events"] == []


@pytest.fixture
def dated(tmp_path: Path):
    """One photograph whose EXIF says 15 January 2020."""
    from media_compost.testing import make_jpeg_with_exif

    src = tmp_path / "shots"
    src.mkdir()
    make_jpeg_with_exif(src / "a.jpg", seed=3)
    cfg = UiConfig(data_dir=tmp_path / "d2")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([src], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


def test_an_event_whose_span_holds_the_capture_date_is_offered(dated):
    a = _items(dated)[0]
    hit = _event(dated, display_name="That January",
                 start_date=20200101, end_date=20200131)
    _event(dated, display_name="Some other year",
           start_date=20140724, end_date=20140727)

    got = _sugg(dated, a)
    assert got["dated"] is True
    assert [e["event"]["display_name"] for e in got["events"]] == ["That January"]
    assert got["events"][0]["date_taken"] == 20200115
    assert hit["tag"] not in [t["name"] for t in
                              dated.get(f"/api/items/{a}").json()["tags"]], \
        "offered, not assigned"


def test_an_event_already_on_the_picture_is_not_offered_again(dated):
    a = _items(dated)[0]
    ev = _event(dated, display_name="That January",
                start_date=20200101, end_date=20200131)
    dated.post(f"/api/tags/assign/item/{a}", json={"tag": ev["tag"]})
    assert _sugg(dated, a)["events"] == []


def test_saying_no_to_an_event_is_final(dated):
    a = _items(dated)[0]
    ev = _event(dated, display_name="That January",
                start_date=20200101, end_date=20200131)
    left = dated.post("/api/events/dismiss-event",
                      json={"item_id": a, "occasion_id": ev["id"]}).json()
    assert left["events"] == []
    assert _sugg(dated, a)["events"] == []

    dated.post("/api/history/revert",
               json={"event_ids": [_latest(dated, "dismiss_event")["id"]]})
    assert len(_sugg(dated, a)["events"]) == 1


def test_a_negatively_assigned_event_is_a_refusal_already(dated):
    """"Pointedly not from that" is a stronger statement than a dismissal, and
    offering it again would ask a question that has been answered twice."""
    a = _items(dated)[0]
    ev = _event(dated, display_name="That January",
                start_date=20200101, end_date=20200131)
    dated.post(f"/api/tags/assign/item/{a}",
               json={"tag": ev["tag"], "negative": True})
    assert _sugg(dated, a)["events"] == []


# ---- the tag namespace -----------------------------------------------------

def test_an_invented_event_tag_carries_the_library_namespace(client):
    """`event:` by default, so an event's tags live apart from the ordinary
    ones. A tag typed by hand is left exactly as typed — that one is what was
    asked for."""
    row = _event(client, display_name="San Diego Comic-Con 2014")
    assert row["tag"] == "event:san_diego_comic_con_2014"

    typed = _event(client, display_name="Wedding", tag="our_wedding")
    assert typed["tag"] == "our_wedding"


def test_the_namespace_is_a_setting(client):
    prefs = client.get("/api/settings").json()
    assert prefs["event_tag_prefix"] == "event:"
    assert prefs["place_tag_prefix"] == "place:"
    assert prefs["subject_tag_prefix"] == "subject:"

    client.put("/api/settings", json={**prefs, "event_tag_prefix": ""})
    assert _event(client, display_name="Plain")["tag"] == "plain"
    # An empty prefix is a CHOICE, not a missing key: it has to survive the
    # next read rather than falling back to the default.
    assert client.get("/api/settings").json()["event_tag_prefix"] == ""


# ---- when the picture was taken -------------------------------------------

def _taken_q(client, **bounds):
    body = {"query": {"type": "group", "op": "and", "children": [
        {"type": "taken", **bounds}]}}
    return {i["id"] for i in client.post("/api/items/query", json=body).json()["items"]}


def test_a_typed_date_wins_over_the_camera(client):
    """An override, not a second opinion: EXIF is left alone and this is what
    every reader takes."""
    item = _items(client)[0]
    client.patch(f"/api/items/{item}", json={"taken_at": 20200305143000})
    detail = client.get(f"/api/items/{item}").json()
    assert detail["taken_at"] == 20200305143000
    assert detail["taken_source"] == "set"

    assert _taken_q(client, date_from=20200301, date_to=20200310) >= {item}
    assert item not in _taken_q(client, date_from=20210101)

    # Clearing falls back to whatever the file said — here, nothing.
    client.patch(f"/api/items/{item}", json={"taken_at": 0})
    assert client.get(f"/api/items/{item}").json()["taken_at"] is None


def test_a_partial_date_is_a_window_not_a_point(client):
    """"2020" covers the year, so a search for one week in January finds it —
    the encoding carries its own precision."""
    item = _items(client)[0]
    client.patch(f"/api/items/{item}", json={"taken_at": 20200000000000})
    assert item in _taken_q(client, date_from=20200101, date_to=20200107)
    assert item not in _taken_q(client, date_from=20210101, date_to=20210107)


def test_an_undated_picture_is_taken_when_its_event_was(client):
    """The fallback, and the whole reason it exists: a photograph from a
    convention that ran 5–10 January was taken then."""
    a, b = _items(client)[:2]
    ev = client.post("/api/events", json={"display_name": "Comic-Con",
                                          "start_date": 20200105,
                                          "end_date": 20200110}).json()
    tag = next(e for e in ev if e["display_name"] == "Comic-Con")["tag"]
    for item in (a, b):
        client.post(f"/api/tags/assign/item/{item}",
                    json={"tag": tag, "negative": False})
    assert client.get(f"/api/items/{a}").json()["taken_source"] == "event"
    assert {a, b} <= _taken_q(client, date_from=20200101, date_to=20200107)

    # A date of its own beats the inherited one — the specific answer wins.
    client.patch(f"/api/items/{b}", json={"taken_at": 20200108000000})
    found = _taken_q(client, date_from=20200101, date_to=20200107)
    assert a in found and b not in found


def test_saying_a_picture_has_no_date_stops_the_fallbacks(client):
    """"There is no date" is an ANSWER, not the lack of one. Without it a wrong
    date the picture inherits could be replaced but never removed."""
    from media_compost.db import TAKEN_NONE

    a, b = _items(client)[:2]
    ev = client.post("/api/events", json={"display_name": "Comic-Con",
                                          "start_date": 20200105,
                                          "end_date": 20200110}).json()
    tag = next(e for e in ev if e["display_name"] == "Comic-Con")["tag"]
    for item in (a, b):
        client.post(f"/api/tags/assign/item/{item}",
                    json={"tag": tag, "negative": False})
    assert {a, b} <= _taken_q(client, date_from=20200101, date_to=20200107)

    client.patch(f"/api/items/{b}", json={"taken_at": TAKEN_NONE})
    detail = client.get(f"/api/items/{b}").json()
    assert detail["taken_at"] is None, "it has no date to report"
    assert detail["taken_source"] == "never", "and that is on purpose"

    found = _taken_q(client, date_from=20200101, date_to=20200107)
    assert a in found and b not in found
    assert b in _taken_q(client, have=False), "!TAKEN: finds it"

    # And it is undone by unsaying it, not by dating the picture.
    client.patch(f"/api/items/{b}", json={"taken_at": 0})
    assert client.get(f"/api/items/{b}").json()["taken_source"] == "event"


def test_no_date_stops_an_event_being_suggested(client):
    """The suggestion reads the same three answers; a picture said to have no
    date must not be offered the event whose span its EXIF happens to fall in."""
    from media_compost.db import TAKEN_NONE

    item = _items(client)[0]
    client.post("/api/events", json={"display_name": "Comic-Con",
                                     "start_date": 20200105,
                                     "end_date": 20200110})
    client.patch(f"/api/items/{item}", json={"taken_at": 20200106000000})
    out = client.get(f"/api/events/suggestions/{item}").json()
    assert [s["event"]["display_name"] for s in out["events"]] == ["Comic-Con"]

    client.patch(f"/api/items/{item}", json={"taken_at": TAKEN_NONE})
    out = client.get(f"/api/events/suggestions/{item}").json()
    assert out["events"] == [] and out["dated"] is False


def test_dating_a_picture_reverts(client):
    item = _items(client)[0]
    client.patch(f"/api/items/{item}", json={"taken_at": 19990000000000})
    client.patch(f"/api/items/{item}", json={"taken_at": 20200000000000})
    ids = [e["id"] for e in client.get("/api/history").json()["events"]
           if e["action"] == "set_taken"]
    assert client.post("/api/history/revert",
                       json={"event_ids": ids[:1]}).status_code == 200
    assert client.get(f"/api/items/{item}").json()["taken_at"] == 19990000000000


def test_a_day_query_finds_a_picture_taken_that_afternoon(client):
    """The bug this window rule exists for: a stored date is fourteen digits
    wide, so a query for the DAY must not be read as one second of it."""
    item = _items(client)[0]
    client.patch(f"/api/items/{item}", json={"taken_at": 20140320112922})
    assert item in _taken_q(client, date_from=20140320000000,
                            date_to=20140320000000)
    assert item in _taken_q(client, date_from=20140000000000,
                            date_to=20140000000000), "the whole year, too"
    assert item not in _taken_q(client, date_from=20140321000000,
                                date_to=20140321000000)
