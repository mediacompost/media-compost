"""Subjects — who or what a picture is OF.

A subject is extra data on a TAG, and these tests pin the three things that
follow from that: assigning a subject is assigning its tag (so counts and
search need no new machinery), an identity can exist before it has a name, and
naming one back-fills the tag onto everything it was already known to be in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost import partialdate as pdate
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


def _subject(rows, name):
    return next(r for r in rows if r["display_name"] == name)


# ---- the identity is a tag -------------------------------------------------

def test_a_named_subject_owns_a_tag_and_its_count(client):
    rows = client.post("/api/subjects",
                       json={"display_name": "Albert Einstein"}).json()
    sub = _subject(rows, "Albert Einstein")
    assert sub["tag"] == "subject:albert_einstein", "the slug is derived from the name"
    assert sub["items"] == 0

    item = _items(client)[0]
    client.post(f"/api/tags/assign/item/{item}",
                json={"tag": "subject:albert_einstein", "negative": False})
    rows = client.get("/api/subjects").json()
    assert _subject(rows, "Albert Einstein")["items"] == 1, \
        "the subject's count IS the tag's count"
    # And the ordinary tag search finds it — no new condition needed.
    found = client.post("/api/items/query", json={
        "query": {"type": "group", "op": "and", "neg": False, "children": [
            {"type": "tag", "name": "subject:albert_einstein", "have": True, "sign": "pos"}]},
    }).json()["items"]
    assert [i["id"] for i in found] == [item]


def test_two_subjects_may_share_a_display_name(client):
    client.post("/api/subjects", json={"display_name": "Michael Jordan",
                                       "comment": "basketball"})
    rows = client.post("/api/subjects", json={"display_name": "Michael Jordan",
                                              "comment": "actor"}).json()
    same = [r for r in rows if r["display_name"] == "Michael Jordan"]
    assert len(same) == 2
    slugs = sorted(r["tag"] for r in same)
    assert slugs == ["subject:michael_jordan", "subject:michael_jordan_2"], \
        "the slugs differ quietly; the display names do not have to"
    assert sorted(r["comment"] for r in same) == ["actor", "basketball"]


def test_a_subject_can_exist_without_a_name(client):
    rows = client.post("/api/subjects", json={}).json()
    assert len(rows) == 1
    assert rows[0]["tag"] == "" and rows[0]["display_name"] == ""
    assert client.get("/api/tags").json() == [] or all(
        t["name"] != "" for t in client.get("/api/tags").json()), \
        "an unnamed subject mints no tag"


def test_naming_a_subject_mints_the_tag(client):
    sid = client.post("/api/subjects", json={}).json()[0]["id"]
    rows = client.patch(f"/api/subjects/{sid}", json={"display_name": "Alice",
                                                     "tag": "subject:alice"}).json()
    assert _subject(rows, "Alice")["tag"] == "subject:alice"
    assert any(t["name"] == "subject:alice" for t in client.get("/api/tags").json())


def test_naming_an_unnamed_subject_is_revertible(client):
    sid = client.post("/api/subjects", json={}).json()[0]["id"]
    client.patch(f"/api/subjects/{sid}", json={"tag": "subject:alice"})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "name_subject")
    assert client.post("/api/history/revert", json={"event_ids": [ev["id"]]}).status_code == 200
    assert client.get("/api/subjects").json()[0]["tag"] == ""


# ---- the identity's own data ----------------------------------------------

def test_since_date_keeps_its_precision(client):
    rows = client.post("/api/subjects", json={
        "display_name": "Reichstag", "since_date": 18940000}).json()
    assert _subject(rows, "Reichstag")["since_date"] == 18940000
    # July 1999 and a full day are the same field at other precisions.
    sid = _subject(rows, "Reichstag")["id"]
    assert client.patch(f"/api/subjects/{sid}",
                        json={"since_date": 19990700}).status_code == 200
    assert client.patch(f"/api/subjects/{sid}",
                        json={"since_date": 19991332}).status_code == 400


def test_rename_comment_and_date_each_revert(client):
    sid = client.post("/api/subjects", json={
        "display_name": "Alice", "comment": "school", "since_date": 20100000,
    }).json()[0]["id"]
    client.patch(f"/api/subjects/{sid}", json={
        "display_name": "Alicia", "comment": "college", "since_date": 20110000})
    # The NEWEST of each action. Creating the subject with a comment already
    # wrote a `comment_tag`, so a plain dict comprehension over the
    # newest-first log keeps the oldest and undoes the wrong one.
    events: dict[str, int] = {}
    for e in client.get("/api/history").json()["events"]:
        events.setdefault(e["action"], e["id"])
    # `comment_tag`, not `comment_subject`: what a person IS, in a line, is
    # their identity tag's — one field with one editor and one event.
    for action in ("rename_subject", "comment_tag", "date_subject"):
        assert action in events, action
        assert client.post("/api/history/revert",
                           json={"event_ids": [events[action]]}).status_code == 200
    row = client.get("/api/subjects").json()[0]
    assert (row["display_name"], row["comment"], row["since_date"]) \
        == ("Alice", "school", 20100000)


def test_deleting_a_subject_keeps_its_tag_by_default(client):
    sid = client.post("/api/subjects", json={"display_name": "Alice"}).json()[0]["id"]
    client.delete(f"/api/subjects/{sid}")
    assert client.get("/api/subjects").json() == []
    assert any(t["name"] == "subject:alice" for t in client.get("/api/tags").json()), \
        "the tag is an ordinary tag now — the pictures are still of something"
    client.post("/api/subjects", json={"display_name": "Bob"})
    bid = client.get("/api/subjects").json()[0]["id"]
    client.delete(f"/api/subjects/{bid}", params={"with_tag": True})
    assert not any(t["name"] == "subject:bob" for t in client.get("/api/tags").json())


def test_deleting_a_subject_reverts(client):
    sid = client.post("/api/subjects", json={"display_name": "Alice",
                                             "comment": "school"}).json()[0]["id"]
    client.delete(f"/api/subjects/{sid}")
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "delete_subject")
    assert client.post("/api/history/revert", json={"event_ids": [ev["id"]]}).status_code == 200
    rows = client.get("/api/subjects").json()
    assert (rows[0]["display_name"], rows[0]["comment"], rows[0]["tag"]) \
        == ("Alice", "school", "subject:alice")


# ---- merging ---------------------------------------------------------------

def test_merging_subjects_folds_the_tags_and_the_assignments(client):
    a, b = _items(client)[:2]
    rows = client.post("/api/subjects", json={"display_name": "Alice"}).json()
    rows = client.post("/api/subjects", json={"display_name": "Alice B"}).json()
    one = _subject(rows, "Alice")["id"]
    two = _subject(rows, "Alice B")["id"]
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "subject:alice", "negative": False})
    client.post(f"/api/tags/assign/item/{b}", json={"tag": "subject:alice_b", "negative": False})

    res = client.post(f"/api/subjects/{two}/merge",
                      json={"into_id": one, "keep_alias": True}).json()
    assert [r["display_name"] for r in res["subjects"]] == ["Alice"]
    # The event ids come back so the list view can offer an Undo, and the
    # subject's own event is last — reverting walks backwards, and the subject
    # has to exist again before its tag's assignments can come back.
    assert res["event_ids"], "a merge that cannot be undone is not offered one"
    assert _subject(res["subjects"], "Alice")["items"] == 2, \
        "both items carry the survivor"
    aliases = {t["name"]: t["alias_of"] for t in client.get("/api/tags").json()}
    assert aliases.get("subject:alice_b") == "subject:alice", "the old name still resolves"


# ---- when: the state of an assignment --------------------------------------

def test_an_appearance_round_trips_and_clears(client):
    item = _items(client)[0]
    sid = client.post("/api/subjects", json={"display_name": "Alice",
                                             "since_date": 20100000}
                      ).json()[0]["id"]
    aid = _appear(client, item, sid, date=20220000)

    detail = client.get(f"/api/items/{item}").json()
    on_item = {s["tag"]: s for s in detail["subjects"]}
    assert on_item["subject:alice"]["appearances"][0]["when"]["date"] == 20220000
    # Assigning the tag is part of being in the picture.
    assert "subject:alice" in [t["name"] for t in detail["tags"]]

    # Clearing both fields leaves the appearance, without a date.
    client.patch(f"/api/subjects/appearances/{aid}", json={"when": {}})
    detail = client.get(f"/api/items/{item}").json()
    assert detail["subjects"][0]["appearances"][0]["when"] is None


def test_one_person_can_be_in_a_picture_twice(client):
    """A page holding the same character at two ages: two appearances, one
    tag, and both ages findable."""
    item = _items(client)[0]
    sid = client.post("/api/subjects", json={"display_name": "Alice",
                                             "since_date": 20100000}
                      ).json()[0]["id"]
    _appear(client, item, sid, age=6)
    _appear(client, item, sid, age=12)
    detail = client.get(f"/api/items/{item}").json()
    ages = [a["when"]["age"] for a in detail["subjects"][0]["appearances"]]
    assert sorted(ages) == [6, 12]
    assert [t["name"] for t in detail["tags"]].count("subject:alice") == 1


def test_an_appearance_reverts(client):
    item = _items(client)[0]
    sid = client.post("/api/subjects",
                      json={"display_name": "Alice"}).json()[0]["id"]
    aid = _appear(client, item, sid, date=19210000)
    client.patch(f"/api/subjects/appearances/{aid}", json={"when": {"date": 19550000}})
    ids = [e["id"] for e in client.get("/api/history").json()["events"]
           if e["action"] == "edit_appearance"]
    assert client.post("/api/history/revert",
                       json={"event_ids": ids[:1]}).status_code == 200
    detail = client.get(f"/api/items/{item}").json()
    assert detail["subjects"][0]["appearances"][0]["when"]["date"] == 19210000


def test_removing_the_last_appearance_takes_the_tag(client):
    """"Not in this picture" is what removing the only appearance means, and
    leaving the tag would keep them in every search that found them here."""
    item = _items(client)[0]
    sid = client.post("/api/subjects",
                      json={"display_name": "Alice"}).json()[0]["id"]
    aid = _appear(client, item, sid)
    client.delete(f"/api/subjects/appearances/{aid}")
    detail = client.get(f"/api/items/{item}").json()
    assert detail["subjects"] == []
    assert "subject:alice" not in [t["name"] for t in detail["tags"]]


# ---- the date helpers ------------------------------------------------------

def test_partial_dates_cover_what_they_do_not_say():
    assert pdate.bounds(19750000) == (19750101, 19751231)
    assert pdate.bounds(19990700) == (19990701, 19990731)
    assert pdate.bounds(18790314) == (18790314, 18790314)


def test_age_never_overstates_itself():
    # Born 14 March 1879: still 20 in January 1900, 21 in April.
    assert pdate.age_at(18790314, 19000100) == 20
    assert pdate.age_at(18790314, 19000401) == 21
    # A year-only birth date is read as the start of the year.
    assert pdate.age_at(19750000, 19750000) == 0
    assert pdate.age_at(19750000, 20200000) == 45
    assert pdate.age_at(19750000, 19700000) is None, "not yet born"
    assert pdate.date_from_age(19750000, 12) == 19870000


def test_deleting_the_tag_takes_the_identity_with_it(client):
    """Deleting an identity tag deletes the SUBJECT too — the old SET NULL
    left a record stripped of its name and every assignment, the orphan
    state a select-all sweep once put a whole library in. The cascade is the
    record op's own delete, so it logs and reverts."""
    client.post("/api/subjects", json={"display_name": "Alice"})
    tag_id = next(t["id"] for t in client.get("/api/tags").json()
                  if t["name"] == "subject:alice")
    res = client.delete(f"/api/tags/{tag_id}")
    assert res.status_code == 200
    assert client.get("/api/subjects").json() == []
    # The one event batch brings both halves back, re-linked.
    assert client.post("/api/history/revert",
                       json={"event_ids": res.json()["event_ids"]}
                       ).status_code == 200
    rows = client.get("/api/subjects").json()
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Alice"
    assert rows[0]["tag"] == "subject:alice"


# ---- search ----------------------------------------------------------------

def _q(client, cond):
    body = {"query": {"type": "group", "op": "and", "neg": False,
                      "children": [cond]}}
    return [i["id"] for i in client.post("/api/items/query", json=body).json()["items"]]


def test_search_narrows_by_the_state_of_the_assignment(client):
    a, b = _items(client)[:2]
    client.post("/api/subjects", json={"display_name": "Alice",
                                       "since_date": 20100000})
    for item in (a, b):
        client.post(f"/api/tags/assign/item/{item}",
                    json={"tag": "subject:alice", "negative": False})
    sid = client.get("/api/subjects").json()[0]["id"]
    _appear(client, a, sid, date=20150000)
    _appear(client, b, sid, date=20220000, age=12)

    assert sorted(_q(client, {"type": "subject", "name": "subject:alice"})) == sorted([a, b])
    assert _q(client, {"type": "subject", "name": "subject:alice",
                       "date_from": 20200000}) == [b]
    assert _q(client, {"type": "subject", "name": "subject:alice",
                       "date_from": 20100000, "date_to": 20160000}) == [a]
    assert _q(client, {"type": "subject", "name": "subject:alice",
                       "age_from": 10, "age_to": 14}) == [b], \
        "an undated assignment cannot satisfy an age bound"
    # No name = any subject at all; negated = none.
    assert sorted(_q(client, {"type": "subject"})) == sorted([a, b])
    rest = _q(client, {"type": "subject", "have": False})
    assert a not in rest and b not in rest


def test_the_search_derives_the_half_you_did_not_type(client):
    """Typing the year of the picture says the age too, when the subject has a
    since-date. A search for an age range must find it — without the age being
    stored twice."""
    a, b = _items(client)[:2]
    client.post("/api/subjects", json={"display_name": "Alice",
                                       "since_date": 20100000})
    for item in (a, b):
        client.post(f"/api/tags/assign/item/{item}",
                    json={"tag": "subject:alice", "negative": False})
    sid = client.get("/api/subjects").json()[0]["id"]
    _appear(client, a, sid, date=20220000)   # age 12
    _appear(client, b, sid, age=5)           # in 2015

    assert _q(client, {"type": "subject", "name": "subject:alice",
                       "age_from": 11, "age_to": 13}) == [a]
    assert _q(client, {"type": "subject", "name": "subject:alice",
                       "date_from": 20150000, "date_to": 20150000}) == [b]


# ---- a tag group about a subject -------------------------------------------

def test_a_tag_group_can_be_about_a_subject(client):
    """A picture with two people wants two groups of tags. Binding the grouping
    to the identity survives a rename, which a group NAME does not."""
    item = _items(client)[0]
    sid = client.post("/api/subjects", json={"display_name": "Alice"}).json()[0]["id"]
    gid = client.post(f"/api/tags/item/{item}/groups",
                      json={"name": "New group"}).json()["id"]
    assert client.post(f"/api/tags/groups/{gid}/subjects",
                       json={"subject_id": sid}).json() == [sid]
    detail = client.get(f"/api/items/{item}").json()
    assert detail["tag_groups"][0]["subjects"] == [sid]

    # Renaming the subject does not touch the link.
    client.patch(f"/api/subjects/{sid}", json={"display_name": "Alicia"})
    detail = client.get(f"/api/items/{item}").json()
    assert detail["tag_groups"][0]["subjects"] == [sid]

    # And the grouped tags stay the ITEM's — a bound group is organizational.
    client.post(f"/api/tags/item/{item}/group-tag",
                json={"tag": "blonde_hair", "group_id": gid, "negative": False})
    detail = client.get(f"/api/items/{item}").json()
    assert "blonde_hair" in [t["name"] for t in detail["tags"]]


def test_removing_the_subjects_tag_drops_its_group_bindings(client):
    """A subject leaving the ITEM takes its tag-group bindings there with it —
    the binding is independent of the assignment, so without the cascade the
    group went on pointing at a subject the item no longer has (rendered as a
    "?" chip). Each dropped binding is its own revertible event."""
    item = _items(client)[0]
    made = client.post("/api/subjects",
                       json={"display_name": "Alice"}).json()[0]
    sid, tag = made["id"], made["tag"]
    client.post(f"/api/tags/assign/item/{item}",
                json={"tag": tag, "negative": False})
    gid = client.post(f"/api/tags/item/{item}/groups",
                      json={"name": "Hers"}).json()["id"]
    client.post(f"/api/tags/groups/{gid}/subjects", json={"subject_id": sid})

    r = client.delete(f"/api/tags/assign/item/{item}/{tag}")
    assert r.status_code == 200
    detail = client.get(f"/api/items/{item}").json()
    assert detail["tag_groups"][0]["subjects"] == []
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "remove_tag_group_subject")
    # The cascade's event reverts like the chip's own ✕ would.
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    detail = client.get(f"/api/items/{item}").json()
    assert detail["tag_groups"][0]["subjects"] == [sid]


def test_binding_a_group_to_a_subject_reverts(client):
    item = _items(client)[0]
    sid = client.post("/api/subjects", json={"display_name": "Alice"}).json()[0]["id"]
    gid = client.post(f"/api/tags/item/{item}/groups",
                      json={"name": "New group"}).json()["id"]
    client.post(f"/api/tags/groups/{gid}/subjects", json={"subject_id": sid})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "add_tag_group_subject")
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    detail = client.get(f"/api/items/{item}").json()
    assert detail["tag_groups"][0]["subjects"] == []


def test_the_library_can_keep_its_people_in_a_namespace(client):
    """A subject tag the app INVENTS takes the library's prefix, so a library
    that wants people apart from ordinary tags gets that without anyone typing
    it. A tag typed by hand is exactly what was typed."""
    client.put("/api/settings", json={"model_paths": {},
                                      "subject_tag_prefix": "subject:"})

    rows = client.post("/api/subjects", json={"display_name": "Albert Einstein"}).json()
    made = next(r for r in rows if r["display_name"] == "Albert Einstein")
    assert made["tag"] == "subject:albert_einstein"

    # An explicit tag is left alone — that one is what was asked for.
    rows = client.post("/api/subjects",
                       json={"display_name": "Marie Curie", "tag": "curie"}).json()
    assert next(r for r in rows if r["display_name"] == "Marie Curie")["tag"] == "curie"

    # And with no prefix set, nothing changes.
    client.put("/api/settings", json={"model_paths": {}, "subject_tag_prefix": ""})
    rows = client.post("/api/subjects", json={"display_name": "Ada Lovelace"}).json()
    assert next(r for r in rows if r["display_name"] == "Ada Lovelace")["tag"] == "ada_lovelace"


# ---- the search path, end to end ------------------------------------------
#
# `load_subject_sets` derives the missing half of a when on the way into the
# query, and nothing covered it. These run through the real POST /query so the
# derivation, the context loader and the evaluator are all in the loop.

def _query_ids(client, cond) -> set[int]:
    body = {"query": {"type": "group", "op": "and", "children": [cond]}}
    return {i["id"] for i in client.post("/api/items/query", json=body).json()["items"]}


def _appear(client, item, subject_id, **when):
    """Say somebody is in an item, once, and date that appearance.

    The tag is the assignment; an APPEARANCE is what carries the age, and a
    subject may have several in one picture."""
    rows = client.post("/api/subjects/appearances",
                       json={"item_id": item, "subject_id": subject_id}).json()
    row = next(r for r in rows if r["id"] == subject_id)
    aid = row["appearances"][-1]["id"]
    if when:
        client.patch(f"/api/subjects/appearances/{aid}", json={"when": when})
    return aid


def _dated(client, item, subject_id, **when):
    return _appear(client, item, subject_id, **when)


def _alice(client, since=20100000):
    """Alice, and her SUBJECT id — what an appearance points at."""
    rows = client.post("/api/subjects", json={"display_name": "Alice",
                                              "since_date": since}).json()
    return next(r["id"] for r in rows if r["display_name"] == "Alice")


def test_search_derives_the_age_from_the_date(client):
    """Somebody who typed the year of the picture has said the age too."""
    a, b = _items(client)[:2]
    sid = _alice(client)
    for i in (a, b):
        client.post(f"/api/tags/assign/item/{i}",
                    json={"tag": "subject:alice", "negative": False})
    _dated(client, a, sid, date=20220000)      # -> age 12
    _dated(client, b, sid, date=20180000)      # -> age 8

    assert _query_ids(client, {"type": "subject", "name": "subject:alice",
                               "age_from": 11, "age_to": 13}) == {a}
    assert _query_ids(client, {"type": "subject", "name": "subject:alice",
                               "age_from": 7, "age_to": 9}) == {b}


def test_search_derives_the_date_from_the_age(client):
    """And the other way: an age plus a since-date is a year."""
    item = _items(client)[0]
    sid = _alice(client)
    _dated(client, item, sid, age=12)

    assert _query_ids(client, {"type": "subject", "name": "subject:alice",
                               "date_from": 20220000,
                               "date_to": 20220000}) == {item}


def test_an_undated_assignment_is_found_but_never_by_a_state(client):
    item = _items(client)[0]
    _alice(client)
    client.post(f"/api/tags/assign/item/{item}",
                json={"tag": "subject:alice", "negative": False})
    assert _query_ids(client, {"type": "subject", "name": "subject:alice"}) == {item}
    assert _query_ids(client, {"type": "subject", "name": "subject:alice",
                               "age_from": 0, "age_to": 99}) == set()


def test_a_subject_with_no_since_date_derives_nothing(client):
    """Without a since-date an age and a date are unrelated, so a date-only
    assignment must not answer an age question."""
    item = _items(client)[0]
    sid = _alice(client, since=None)
    _dated(client, item, sid, date=20220000)
    assert _query_ids(client, {"type": "subject", "name": "subject:alice",
                               "date_from": 20220000}) == {item}
    assert _query_ids(client, {"type": "subject", "name": "subject:alice",
                               "age_from": 0, "age_to": 99}) == set()


def test_two_appearances_answer_two_ages(client):
    """One page, one character, two ages — which a single per-assignment date
    could not express at all."""
    item = _items(client)[0]
    sid = _alice(client)                       # since 2010
    _dated(client, item, sid, date=20220000)   # age 12
    _appear(client, item, sid, age=6)

    # Both answers are findable, and neither displaces the other.
    assert _query_ids(client, {"type": "subject", "name": "subject:alice",
                               "age_from": 11, "age_to": 13}) == {item}
    assert _query_ids(client, {"type": "subject", "name": "subject:alice",
                               "age_from": 5, "age_to": 7}) == {item}
    assert _query_ids(client, {"type": "subject", "name": "subject:alice",
                               "age_from": 30}) == set()


def test_reordering_appearances_round_trips(client):
    """The sidebar's drag-reorder: positions follow the given order, the
    detail lists appearances in it, one event logs the lot and its revert
    restores the old order — and an order that moved nothing logs nothing."""
    item = _items(client)[0]
    rows = client.post("/api/subjects/appearances",
                       json={"item_id": item, "display_name": "Ann"}).json()
    rows = client.post("/api/subjects/appearances",
                       json={"item_id": item, "display_name": "Ben"}).json()

    def order():
        detail = client.get(f"/api/items/{item}").json()
        pairs = [(a["position"], a["id"], s["display_name"])
                 for s in detail["subjects"] for a in s["appearances"]]
        return [name for _p, _i, name in sorted(pairs)[:2]] or                [name for _p, _i, name in sorted(pairs)]

    ids = {s["display_name"]: s["appearances"][0]["id"]
           for s in rows}
    assert order() == ["Ann", "Ben"]

    r = client.post("/api/subjects/appearances/order",
                    json={"item_id": item, "ids": [ids["Ben"], ids["Ann"]]})
    assert r.status_code == 200, r.text
    assert order() == ["Ben", "Ann"]

    events = client.get("/api/history?limit=5").json()["events"]
    ev = next(e for e in events if e["action"] == "reorder_appearances")
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert order() == ["Ann", "Ben"]

    # The same order again is a no-op and logs nothing new.
    client.post("/api/subjects/appearances/order",
                json={"item_id": item, "ids": [ids["Ann"], ids["Ben"]]})
    n = len([e for e in client.get("/api/history?limit=20").json()["events"]
             if e["action"] == "reorder_appearances"])
    assert n == 1


def test_merging_a_subject_and_its_tag_undoes_whole(client):
    """Renaming a subject's tag onto one that exists is a MERGE, and the undo
    has to put BOTH halves back — including the link between them.

    It did not: the tag comes back under a fresh rowid when its own deletion is
    reverted, so re-linking by the stored id left the identity pointing at
    nothing, which reads as a subject whose tag vanished.
    """
    items = _items(client)
    a = client.post("/api/subjects",
                    json={"display_name": "Miyuki", "tag": "miyuki"}).json()
    a = next(r for r in a if r["display_name"] == "Miyuki")
    b = client.post("/api/subjects",
                    json={"display_name": "Kaguya", "tag": "kaguya"}).json()
    b = next(r for r in b if r["display_name"] == "Kaguya")
    client.post(f"/api/tags/assign/item/{items[0]}",
                json={"tag": "miyuki", "negative": False})
    client.post(f"/api/tags/assign/item/{items[1]}",
                json={"tag": "kaguya", "negative": False})

    tags = {t["name"]: t["id"] for t in client.get("/api/tags").json()}
    # Everything from here on is the merge, and all of it has to come back.
    mark = client.get("/api/history").json()["events"][0]["id"]
    client.post(f"/api/tags/{tags['miyuki']}/merge", json={"into": "kaguya"})
    client.post(f"/api/subjects/{a['id']}/merge",
                json={"into_id": b["id"], "keep_alias": True})
    rows = client.get("/api/subjects").json()
    assert not any(r["display_name"] == "Miyuki" for r in rows)
    assert next(r for r in rows if r["display_name"] == "Kaguya")["items"] == 2

    ids = [e["id"] for e in client.get("/api/history").json()["events"]
           if e["id"] > mark]
    assert client.post("/api/history/revert",
                       json={"event_ids": ids}).json()["failed"] == []

    rows = client.get("/api/subjects").json()
    back = next((r for r in rows if r["display_name"] == "Miyuki"), None)
    assert back is not None, "the identity came back"
    assert back["tag"] == "miyuki", "and so did the link to its tag"
    assert back["items"] == 1, "with the picture that carried it"
