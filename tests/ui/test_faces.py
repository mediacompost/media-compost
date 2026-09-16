"""Faces end to end: naming one, naming fourteen, and re-running the detector.

The rule under all of it is that detection is disposable and human answers are
not. `test_faces_reconcile.py` pins the matching rule itself; this file pins
what the API does with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from media_compost import faces as facelib
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


def _detect(client, item_id: int, found: list[dict], model: str = "anime_face"):
    """Run the applier directly — the model itself is an optional heavy dep, and
    what is under test is what the applier does with its answer."""
    from media_compost.db import Item
    from media_compost.ui.jobs import JobQueue

    lib = client.lib
    queue = JobQueue.__new__(JobQueue)
    queue.lib = lib
    with lib.db.session() as s:
        item = s.get(Item, item_id)
        msg = queue._apply_faces(s, item, found, model)
        s.commit()
    return msg


def _face(x, y, w=0.2, h=0.2, score=0.9, embedding=None):
    d = {"box": [x, y, w, h], "score": score}
    if embedding is not None:
        d["embedding"] = embedding
    return d


# ---- detection -------------------------------------------------------------



# ---- reading an appearance -------------------------------------------------
#
# A face is a LIST of people now (a character and the actor at once), so these
# read the first claim — which is the only one in nearly every test.

def _who(face) -> list[str]:
    return [s["name"] or s["tag"] for s in face["subjects"]]


def _name(face) -> str:
    return face["subjects"][0]["name"] if face["subjects"] else ""


def _sid(face):
    return face["subjects"][0]["subject_id"] if face["subjects"] else None


def _by(face) -> str:
    return face["subjects"][0]["assigned_by"] if face["subjects"] else ""


def _score(face):
    return face["subjects"][0]["match_score"] if face["subjects"] else None


def test_detection_records_faces_and_a_rerun_finds_them_known(client):
    item = _items(client)[0]
    assert "2 new faces" in _detect(client, item,
                                    [_face(0.1, 0.1), _face(0.6, 0.1)])
    rows = client.get(f"/api/faces/item/{item}").json()
    assert len(rows) == 2
    assert all(_by(r) == "" for r in rows)

    # The same picture, the same faces, a slightly different box each.
    msg = _detect(client, item, [_face(0.11, 0.1), _face(0.61, 0.105)])
    assert "all known" in msg
    assert len(client.get(f"/api/faces/item/{item}").json()) == 2, \
        "a re-run must not double every face"


def test_a_rerun_never_takes_back_a_name(client):
    """The whole reason reconciliation exists."""
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    _detect(client, item, [_face(0.105, 0.102)], model="insightface_buffalo_l")
    after = client.get(f"/api/faces/item/{item}").json()[0]
    assert after["id"] == face["id"]
    assert _name(after) == "Alice"
    assert _by(after) == "user"
    # Both detectors are credited: the boxes merged, so neither found it alone.
    assert after["models"] == ["anime_face", "insightface_buffalo_l"]


def test_a_dismissed_face_stays_dismissed(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.4, 0.4)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    client.patch(f"/api/faces/{face['id']}", json={"dismissed": True})

    _detect(client, item, [_face(0.4, 0.4)])
    rows = client.get(f"/api/faces/item/{item}").json()
    assert len(rows) == 1, "the false positive is not offered again"
    assert rows[0]["dismissed"] is True


def test_a_face_the_run_missed_survives(client):
    """A hand-drawn face, or one a worse model stopped seeing."""
    item = _items(client)[0]
    client.post("/api/faces", json={"item_id": item, "x": 0.5, "y": 0.5,
                                    "w": 0.1, "h": 0.1})
    _detect(client, item, [_face(0.0, 0.0, 0.15, 0.15)])
    assert len(client.get(f"/api/faces/item/{item}").json()) == 2


# ---- naming ----------------------------------------------------------------

def test_naming_a_face_puts_the_subject_s_tag_on_the_item(client):
    """The connection is the point: the face is the evidence, the tag is what
    search and training read."""
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Albert Einstein"}).json()[0]

    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})
    names = [t["name"] for t in client.get(f"/api/items/{item}").json()["tags"]]
    assert "subject:albert_einstein" in names


def test_naming_a_cluster_names_every_picture_at_once(client):
    """Naming people one image at a time is what kills face tagging elsewhere."""
    ids = _items(client)
    alice = [0.9, 0.05, 0.0]
    for i in ids:
        _detect(client, i, [_face(0.1, 0.1, embedding=alice)],
                model="insightface_buffalo_l")

    clusters = client.get("/api/faces/unnamed").json()
    assert clusters[0]["grouped"] is True
    assert len(clusters[0]["faces"]) == len(ids), "one person, every picture"

    face_ids = [f["id"] for f in clusters[0]["faces"]]
    client.post("/api/faces/name-cluster",
                json={"face_ids": face_ids, "display_name": "Alice"})
    for i in ids:
        names = [t["name"] for t in client.get(f"/api/items/{i}").json()["tags"]]
        assert "subject:alice" in names, "one action, every item the cluster touched"
    assert client.get("/api/faces/unnamed").json() == []


def test_faces_with_no_descriptor_still_fill_the_view_ungrouped(client):
    """The anime detector produces none, and it is the detector that matters
    for this library."""
    ids = _items(client)
    for i in ids:
        _detect(client, i, [_face(0.1, 0.1)])
    clusters = client.get("/api/faces/unnamed").json()
    assert len(clusters) == len(ids)
    assert all(c["grouped"] is False for c in clusters)


def test_a_known_face_is_named_by_itself_and_waits_for_review(client):
    a, b = _items(client)[:2]
    alice = [0.9, 0.1, 0.0]
    _detect(client, a, [_face(0.1, 0.1, embedding=alice)],
            model="insightface_buffalo_l")
    face = client.get(f"/api/faces/item/{a}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    _detect(client, b, [_face(0.2, 0.2, embedding=[0.88, 0.14, 0.0])],
            model="insightface_buffalo_l")
    guess = client.get(f"/api/faces/item/{b}").json()[0]
    assert _by(guess) == "suggested"
    assert _name(guess) == "Alice"
    assert _score(guess) and _score(guess) > 0.6
    # The tag IS assigned — a name that read on nothing would be a label with
    # no consequence — but PENDING, which is what asks for the review.
    tags = {t["name"]: t for t in
            client.get(f"/api/items/{b}").json()["tag_instances"]}
    assert "subject:alice" in tags and tags["subject:alice"]["pending"] is True
    assert b in {i["id"] for i in client.get(
        "/api/items?pending=true&pending_kind=faces").json()["items"]}

    # Saying yes clears the flag; the item leaves the review list.
    client.post(f"/api/faces/{guess['id']}" + "/subject", json={"subject_id": subject["id"]})
    tags = {t["name"]: t for t in
            client.get(f"/api/items/{b}").json()["tag_instances"]}
    assert tags["subject:alice"]["pending"] is False
    assert b not in {i["id"] for i in client.get(
        "/api/items?pending=true&pending_kind=faces").json()["items"]}


def test_saying_not_this_person_takes_the_guessed_tag_away(client):
    """The tag was the guess, not a statement anybody made."""
    a, b = _items(client)[:2]
    _detect(client, a, [_face(0.1, 0.1, embedding=[0.9, 0.1, 0.0])],
            model="insightface_buffalo_l")
    face = client.get(f"/api/faces/item/{a}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    _detect(client, b, [_face(0.2, 0.2, embedding=[0.88, 0.14, 0.0])],
            model="insightface_buffalo_l")
    guess = client.get(f"/api/faces/item/{b}").json()[0]
    client.delete(f"/api/faces/{guess['id']}/subject/{_sid(guess)}")
    names = [t["name"] for t in client.get(f"/api/items/{b}").json()["tags"]]
    assert "subject:alice" not in names


def test_a_tag_somebody_agreed_to_survives_the_face_being_rejected(client):
    """Only the PENDING flag makes the tag the guess's to take back."""
    a, b = _items(client)[:2]
    _detect(client, a, [_face(0.1, 0.1, embedding=[0.9, 0.1, 0.0])],
            model="insightface_buffalo_l")
    face = client.get(f"/api/faces/item/{a}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    _detect(client, b, [_face(0.2, 0.2, embedding=[0.88, 0.14, 0.0])],
            model="insightface_buffalo_l")
    guess = client.get(f"/api/faces/item/{b}").json()[0]
    client.post(f"/api/faces/{guess['id']}" + "/subject", json={"subject_id": subject["id"]})
    client.delete(f"/api/faces/{guess['id']}/subject/{subject['id']}")
    names = [t["name"] for t in client.get(f"/api/items/{b}").json()["tags"]]
    assert "subject:alice" in names


def test_naming_an_unnamed_subject_backfills_through_its_faces(client):
    """A cluster named later must reach every item its faces sit on — the same
    flow as naming a place from bare GPS."""
    from media_compost.db import Face

    a, b = _items(client)[:2]
    subject = client.post("/api/subjects", json={}).json()[0]
    assert subject["tag"] == "", "created unnamed"
    for i in (a, b):
        _detect(client, i, [_face(0.1, 0.1)])
        face = client.get(f"/api/faces/item/{i}").json()[0]
        client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    client.patch(f"/api/subjects/{subject['id']}",
                 json={"display_name": "Bob", "tag": "subject:bob"})
    for i in (a, b):
        names = [t["name"] for t in client.get(f"/api/items/{i}").json()["tags"]]
        assert "subject:bob" in names


# ---- crops -----------------------------------------------------------------

def test_a_face_crop_is_served_and_cached(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.3, 0.3)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    r = client.get(f"/api/faces/{face['id']}/crop", params={"w": 64})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 100
    # Moving the box must not serve the old crop back.
    client.patch(f"/api/faces/{face['id']}", json={"x": 0.05, "y": 0.05})
    again = client.get(f"/api/faces/{face['id']}/crop", params={"w": 64})
    assert again.status_code == 200


# ---- history ---------------------------------------------------------------

def test_every_face_action_logs_an_event(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})
    client.patch(f"/api/faces/{face['id']}", json={"dismissed": True})
    client.delete(f"/api/faces/{face['id']}")

    actions = [e["action"] for e in client.get("/api/history").json()["events"]]
    for action in ("detect_faces", "name_face", "dismiss_face", "delete_face"):
        assert action in actions, action


def test_naming_a_face_reverts(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "name_face")
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    after = client.get(f"/api/faces/item/{item}").json()[0]
    assert _sid(after) is None
    names = [t["name"] for t in client.get(f"/api/items/{item}").json()["tags"]]
    assert "subject:alice" not in names, "the tag naming added comes off again"


def test_naming_a_cluster_reverts_whole(client):
    ids = _items(client)
    alice = [0.9, 0.05, 0.0]
    for i in ids:
        _detect(client, i, [_face(0.1, 0.1, embedding=alice)],
                model="insightface_buffalo_l")
    cluster = client.get("/api/faces/unnamed").json()[0]
    client.post("/api/faces/name-cluster",
                json={"face_ids": [f["id"] for f in cluster["faces"]],
                      "display_name": "Alice"})

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "name_faces")
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    for i in ids:
        names = [t["name"] for t in client.get(f"/api/items/{i}").json()["tags"]]
        assert "subject:alice" not in names
    assert len(client.get("/api/faces/unnamed").json()[0]["faces"]) == len(ids), \
        "the faces are unnamed again, and still clustered"
    assert client.get("/api/subjects").json() == [], \
        "the subject the naming created goes with it"


def test_dismissing_and_deleting_a_face_revert(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]

    client.patch(f"/api/faces/{face['id']}", json={"dismissed": True})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "dismiss_face")
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert client.get(f"/api/faces/item/{item}").json()[0]["dismissed"] is False

    client.delete(f"/api/faces/{face['id']}")
    assert client.get(f"/api/faces/item/{item}").json() == []
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "delete_face")
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    back = client.get(f"/api/faces/item/{item}").json()
    assert len(back) == 1 and round(back[0]["x"], 4) == 0.1


# ---- search ----------------------------------------------------------------

def test_face_counts_are_searchable_like_any_other_number(client):
    """`faces` and `unnamed_faces` are intrinsic metadata, so every operator and
    the whole query builder work on them with no new grammar."""
    a, b = _items(client)[:2]
    _detect(client, a, [_face(0.1, 0.1), _face(0.6, 0.1)])
    face = client.get(f"/api/faces/item/{a}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    def q(cond):
        body = {"query": {"type": "group", "op": "and", "neg": False,
                          "children": [cond]}}
        return [i["id"] for i in
                client.post("/api/items/query", json=body).json()["items"]]

    assert q({"type": "meta", "name": "faces", "op": ">=", "value": 2}) == [a]
    assert b in q({"type": "meta", "name": "faces", "op": "=", "value": 0})
    assert q({"type": "meta", "name": "unnamed_faces", "op": ">", "value": 0}) == [a]

    # Dismissing the unnamed one takes it out of both counts.
    other = next(f for f in client.get(f"/api/faces/item/{a}").json()
                 if _sid(f) is None)
    client.patch(f"/api/faces/{other['id']}", json={"dismissed": True})
    assert q({"type": "meta", "name": "faces", "op": "=", "value": 1}) == [a]
    assert q({"type": "meta", "name": "unnamed_faces", "op": ">", "value": 0}) == []


def test_faces_appear_in_the_item_dict(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.2, 0.2)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    from media_compost.db import Item
    from media_compost.itemdict import item_to_dict

    with client.lib.db.session() as s:
        doc = item_to_dict(s, s.get(Item, item))
    assert len(doc["faces"]) == 1
    assert doc["faces"][0]["subjects"][0]["subject"] == "subject:alice", "by NAME, never a database id"
    assert doc["faces"][0]["subjects"][0]["assigned_by"] == "user"


def test_two_detectors_on_one_head_leave_one_face(client):
    """Running both detectors is normal — one is for drawn art, one for
    photographs — and a picture that both understand must not end up with two
    rectangles around the same head."""
    item = _items(client)[0]
    _detect(client, item, [_face(0.30, 0.30, 0.20, 0.20)], model="anime_face")
    # The same head, framed a little differently, as a second detector would.
    _detect(client, item, [_face(0.28, 0.29, 0.22, 0.22)],
            model="insightface_buffalo_l")

    rows = client.get(f"/api/faces/item/{item}").json()
    assert len(rows) == 1, "one head, one face"
    assert rows[0]["models"] == ["anime_face", "insightface_buffalo_l"]


def test_a_second_run_of_the_same_model_credits_it_once(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.3, 0.3)], model="anime_face")
    _detect(client, item, [_face(0.31, 0.3)], model="anime_face")
    assert client.get(f"/api/faces/item/{item}").json()[0]["models"] == ["anime_face"]


def test_one_model_that_finds_a_head_twice_leaves_one_face(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.10, 0.70, 0.13, 0.07, score=0.50),
                           _face(0.10, 0.71, 0.10, 0.06, score=0.31)])
    rows = client.get(f"/api/faces/item/{item}").json()
    assert len(rows) == 1, "one head, one face"
    assert rows[0]["det_score"] == pytest.approx(0.50)


def test_a_duplicate_left_by_an_earlier_run_heals_on_the_next(client):
    """A library that collected the extra row before the rule existed."""
    from media_compost.db import Face

    item = _items(client)[0]
    _detect(client, item, [_face(0.10, 0.70, 0.13, 0.07, score=0.50)])
    with client.lib.db.session() as s:  # the row an old run would have added
        s.add(Face(item_id=item, x=0.10, y=0.71, w=0.10, h=0.06,
                   det_score=0.31, model="anime_face"))
        s.commit()
    assert len(client.get(f"/api/faces/item/{item}").json()) == 2

    _detect(client, item, [_face(0.10, 0.70, 0.13, 0.07, score=0.52)])
    assert len(client.get(f"/api/faces/item/{item}").json()) == 1


def test_healing_never_drops_a_face_somebody_answered_for(client):
    """The detected row is the redundant one, however confident it is."""
    item = _items(client)[0]
    _detect(client, item, [_face(0.10, 0.70, 0.13, 0.07, score=0.99)])
    client.post("/api/faces", json={"item_id": item, "x": 0.10, "y": 0.71,
                                    "w": 0.10, "h": 0.06})
    assert len(client.get(f"/api/faces/item/{item}").json()) == 2

    _detect(client, item, [_face(0.10, 0.70, 0.13, 0.07, score=0.99)])
    rows = client.get(f"/api/faces/item/{item}").json()
    assert len(rows) == 1
    assert rows[0]["models"] == [], "the hand-drawn one is the one that stayed"


def test_an_import_can_detect_faces_on_what_it_brought_in(client, tmp_path):
    """The detector runs as a job over the new items, not inside the import:
    reading a file and running a model are different kinds of slow."""
    import time

    from media_compost.testing import make_image

    queued: list[tuple] = []

    class FakeQueue:
        def enqueue(self, kind, model, item_ids, **kw):
            queued.append((kind, model, list(item_ids)))
            return [1]

    client.lib._jobs = FakeQueue()  # type: ignore[attr-defined]

    src = tmp_path / "incoming"
    src.mkdir()
    make_image(src / "face.png", seed=4242, size=(320, 240))

    def run(**extra):
        job = client.post("/api/import/paths",
                          json={"paths": [str(src)], **extra}).json()
        for _ in range(100):
            st = client.get(f"/api/import/{job['id']}").json()
            if st["status"] != "running":
                return st
            time.sleep(0.05)
        raise AssertionError("import never finished")

    assert run()["status"] == "done"
    assert queued == [], "nothing runs unless a model was chosen"

    make_image(src / "face2.png", seed=99, size=(320, 240))
    assert run(detect_faces="anime_face")["status"] == "done"
    assert len(queued) == 1
    kind, model, ids = queued[0]
    assert (kind, model) == ("faces", "anime_face")
    assert len(ids) == 1, "only the item this run created"

    # The embed-index option is the same shape one task along: a job over
    # the created images, queued after the import — and the two ride
    # together when both are asked for.
    queued.clear()
    make_image(src / "face3.png", seed=123, size=(320, 240))
    assert run(detect_faces="anime_face",
               index_embeddings="dinov2_small")["status"] == "done"
    assert [(k, m) for k, m, _ in queued] == [
        ("faces", "anime_face"), ("embed", "dinov2_small")]
    assert all(len(i) == 1 for _, _, i in queued)


def test_the_import_is_over_before_the_follow_up_runs_are_queued(client, tmp_path):
    """The import's own status must not depend on the model runs it starts.

    A browser uploads in batches of 200 and waits for each batch's job, so an
    import that reported "running" until the queue had taken its work — or
    until the previous batch's detector had let go of the writer — advanced at
    the detector's pace rather than the disk's. That is what the report
    "the import waits for the detection jobs in 200-image chunks" was.
    """
    import time

    from media_compost.testing import make_image
    from media_compost.ui.server.routers import imports as imports_router

    seen: list[tuple] = []

    class FakeQueue:
        def enqueue(self, kind, model, item_ids, **kw):
            # What the import says about ITSELF at the moment it queues this.
            # By label, not "any running row": the registry outlives one test.
            mine = [j["status"] for j in imports_router._JOBS.values()
                    if j.get("label") == "incoming2"]
            seen.append((kind, kw.get("merge"), mine))
            return [1]

    client.lib._jobs = FakeQueue()  # type: ignore[attr-defined]
    src = tmp_path / "incoming2"
    src.mkdir()
    make_image(src / "a.png", seed=771, size=(320, 240))

    job = client.post("/api/import/paths", json={
        "paths": [str(src)], "detect_faces": "anime_face",
        "index_embeddings": "dinov2_small"}).json()
    for _ in range(100):
        if client.get(f"/api/import/{job['id']}").json()["status"] != "running":
            break
        time.sleep(0.05)

    assert [k for k, _, _ in seen] == ["faces", "embed"]
    # This import is over by the time the queue is touched.
    assert [st for _, _, st in seen] == [["done"], ["done"]], seen
    # And each folds into the job already doing this, rather than making the
    # twentieth row of one import's worth of work.
    assert all(merge is True for _, merge, _ in seen)


def test_a_failed_import_stays_listed_until_it_is_cleared(client, tmp_path):
    """The browser owns the import it started — it holds the files — so a
    reload throws that task away. The server's own record is what is left,
    and a run that went wrong with nobody watching has to still be there."""
    import time

    from media_compost.testing import make_image

    src = tmp_path / "incoming3"
    src.mkdir()
    make_image(src / "a.png", seed=772, size=(320, 240))
    job = client.post("/api/import/paths", json={"paths": [str(src)]}).json()
    for _ in range(100):
        if client.get(f"/api/import/{job['id']}").json()["status"] != "running":
            break
        time.sleep(0.05)

    rows = client.get("/api/import/jobs").json()["jobs"]
    row = next(r for r in rows if r["id"] == job["id"])
    assert row["label"] == "incoming3", "named after what was dropped"
    assert row["status"] == "done"

    # It is cleared by hand, and only once it has stopped.
    assert client.post(f"/api/import/jobs/{job['id']}/clear").status_code == 200
    assert all(r["id"] != job["id"]
               for r in client.get("/api/import/jobs").json()["jobs"])
    assert client.post(f"/api/import/jobs/{job['id']}/clear").status_code == 404


def test_an_upload_that_dies_leaves_a_failed_row_and_no_staged_bytes(client):
    """The upload IS the request body, so a page reloaded mid-import dies
    inside the form parse — earlier than any job used to exist. A failure
    with no row to land on is a run that vanishes with the page."""
    import tempfile
    from pathlib import Path as _Path

    from media_compost.ui.server.routers import imports as imports_router

    before = set(_Path(tempfile.gettempdir()).glob("mc_upload_*"))

    async def _boom(*a, **kw):
        raise RuntimeError("client went away")

    real = imports_router.Request.form
    imports_router.Request.form = _boom  # type: ignore[method-assign]
    try:
        client.post("/api/import",
                    files={"files": ("a.png", b"x", "image/png")})
    except RuntimeError:
        pass                     # TestClient re-raises the handler's failure
    finally:
        imports_router.Request.form = real  # type: ignore[method-assign]

    rows = client.get("/api/import/jobs").json()["jobs"]
    failed = [r for r in rows if r["status"] == "error"]
    assert failed and "client went away" in failed[0]["message"]
    # And nothing is left staged: nobody owns those bytes until the import
    # thread is started.
    assert set(_Path(tempfile.gettempdir()).glob("mc_upload_*")) == before

    # A request that was merely REFUSED is not an import that failed.
    n_before = len(client.get("/api/import/jobs").json()["jobs"])
    assert client.post("/api/import", files={}).status_code in (400, 422)
    assert len(client.get("/api/import/jobs").json()["jobs"]) == n_before


def test_a_hand_drawn_face_credits_nobody(client):
    item = _items(client)[0]
    client.post("/api/faces", json={"item_id": item, "x": 0.1, "y": 0.1,
                                    "w": 0.2, "h": 0.2})
    assert client.get(f"/api/faces/item/{item}").json()[0]["models"] == []


def test_a_face_carries_the_picture_it_came_from(client):
    """The list needs the file (to show the whole picture behind a crop) and the
    item's uid (to send the Library to it) without a lookup per crop."""
    item = _items(client)[0]
    client.post("/api/faces", json={"item_id": item, "x": 0.1, "y": 0.1,
                                    "w": 0.2, "h": 0.2})
    row = client.get(f"/api/faces/item/{item}").json()[0]
    detail = client.get(f"/api/items/{item}").json()
    assert row["item_uid"] == detail["uid"]
    assert row["file_id"] == detail["active_file_id"]


def test_the_crop_ignores_the_box_the_caller_spells_out(client):
    """`at` is only in the URL so a reused face id cannot serve a cached crop of
    the picture the id used to mean; the server reads the row, not the query."""
    item = _items(client)[0]
    face = client.post("/api/faces", json={"item_id": item, "x": 0.1, "y": 0.1,
                                           "w": 0.2, "h": 0.2}).json()[0]["id"]
    plain = client.get(f"/api/faces/{face}/crop?w=96")
    tagged = client.get(f"/api/faces/{face}/crop?w=96&at=0.1000_0.1000_0.2000_0.2000")
    assert plain.status_code == tagged.status_code == 200
    assert plain.content == tagged.content


def _two_faces(client):
    """Two undismissed faces on the library's first item, nobody named."""
    item = _items(client)[0]
    a = client.post("/api/faces", json={"item_id": item, "x": 0.1, "y": 0.1,
                                        "w": 0.2, "h": 0.2}).json()
    b = client.post("/api/faces", json={"item_id": item, "x": 0.6, "y": 0.1,
                                        "w": 0.2, "h": 0.2}).json()
    ids = sorted(f["id"] for f in b)
    return item, ids


def test_two_unnamed_clusters_can_be_merged_into_one(client):
    """A detector with no descriptors hands back one cluster per face, so
    saying "these are the same person" IS the work — and it has to survive the
    next run, which a nameless subject is exactly the thing to do."""
    _, ids = _two_faces(client)
    assert len(client.get("/api/faces/unnamed").json()) == 2

    out = client.post("/api/faces/merge-clusters", json={"face_ids": ids}).json()
    assert len(out) == 1
    assert len(out[0]["faces"]) == 2
    assert out[0]["grouped"] is True
    # Held by a nameless subject — an identity, not a name.
    assert out[0]["subject_id"] is not None
    sub = next(r for r in client.get("/api/subjects").json()
               if r["id"] == out[0]["subject_id"])
    assert sub["display_name"] == "" and sub["tag"] == ""


def _embed(client, face_id: int, vector: list[float],
           model: str = "anime_face_magi") -> None:
    """Give a hand-drawn face a descriptor — what the detector would have
    left, said directly, since these faces were drawn rather than found."""
    with client.lib.db.session() as s:
        facelib.store_embedding(s, face_id, model,
                                facelib.pack_embedding(vector))
        s.commit()


def test_an_open_cluster_is_offered_the_crops_most_like_it(client):
    """A ROW OF LOOKALIKES, WITH NO THRESHOLD (owner 2026-09).

    "Is this the same person as that one" lives in the descriptors, and the
    only way to ask it was to scroll a grid of crops and remember. So an open
    cluster is offered the crops most like it — every one of them, however
    unlike, because a cutoff hides exactly the near-misses this is for.

    CROPS, NOT CLUSTERS (owner 2026-09): "is this crop one of these?" is the
    question, and a cover crop standing for forty others answered a different
    one. A NAMED cluster is offered the unanswered ones only: folding two
    named people together is a different verb in a different place.
    """
    _, ids = _two_faces(client)
    # Neither face has a descriptor (drawn by hand), so nothing is
    # comparable and the row is empty rather than wrong.
    assert client.get(f"/api/faces/similar-faces?faces={ids[0]}").json() == []

    # ALIKE, BUT NOT ALIKE ENOUGH TO BE ONE CLUSTER — which is exactly what
    # this row is for: the near-misses the clustering left apart.
    _embed(client, ids[0], [1.0, 0.0, 0.0])
    _embed(client, ids[1], [0.6, 0.8, 0.0])
    got = client.get(f"/api/faces/similar-faces?faces={ids[0]}").json()
    assert [c["face"]["id"] for c in got] == [ids[1]]
    assert 0 < got[0]["score"] <= 1

    # NOT THIS PERSON takes the pair out for good — the next fetch answers
    # without it rather than offering the same face again, and it answers in
    # the strip's own currency.
    left = client.post("/api/faces/not-matching",
                       json={"face_ids": [ids[0]],
                             "other_face_ids": [ids[1]]}).json()
    assert left == []
    assert client.get(f"/api/faces/similar-faces?faces={ids[0]}").json() == []
    # …and the revert takes that back.
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "clusters_differ")
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).json()["reverted"]
    assert len(
        client.get(f"/api/faces/similar-faces?faces={ids[0]}").json()) == 1


def test_an_unanswered_cluster_is_offered_whole(client):
    """A CLUSTER IS ONE OFFER (owner 2026-09). The queue's clusters are
    scored whole and offered as one card carrying every crop — "this cluster
    of twelve might be them" once, not twelve times — while a cluster of one
    is simply a face. "Not this person" takes several offers in one press,
    each held on its own."""
    item = _items(client)[0]
    ids = []
    for x in (0.1, 0.4, 0.7):
        ids.append(max(f["id"] for f in client.post(
            "/api/faces", json={"item_id": item, "x": x, "y": 0.1,
                                "w": 0.2, "h": 0.2}).json()))
    a, b, c = ids
    _embed(client, a, [1.0, 0.0, 0.0])
    # b and c are one cluster (alike), both near-misses of a.
    _embed(client, b, [0.6, 0.8, 0.0])
    _embed(client, c, [0.62, 0.78, 0.0])
    queue = client.get("/api/faces/unnamed").json()
    assert sorted(len(q["faces"]) for q in queue) == [1, 2]

    got = client.get(f"/api/faces/similar-faces?faces={a}").json()
    assert len(got) == 1
    assert got[0]["count"] == 2
    assert sorted(f["id"] for f in got[0]["faces"]) == [b, c]
    assert got[0]["face"]["id"] in (b, c)
    assert 0 < got[0]["score"] <= 1

    # …and a cluster of one is a face: count 1, faces of one.
    got = client.get(f"/api/faces/similar-faces?faces={b},{c}").json()
    assert [(o["count"], [f["id"] for f in o["faces"]]) for o in got] \
        == [(1, [a])]

    # Several offers refused in one press, each held on its own.
    d = max(f["id"] for f in client.post(
        "/api/faces", json={"item_id": item, "x": 0.1, "y": 0.6,
                            "w": 0.2, "h": 0.2}).json())
    _embed(client, d, [0.0, 1.0, 0.0])
    got = client.get(f"/api/faces/similar-faces?faces={a}").json()
    assert sorted(o["count"] for o in got) == [1, 2]
    left = client.post("/api/faces/not-matching",
                       json={"face_ids": [a],
                             "other_clusters": [[b, c], [d]]}).json()
    assert left == []
    subs = client.get("/api/subjects").json()
    # Three identities minted: the open cluster's, and one per refused
    # offer — never the two offers on one.
    assert len(subs) == 3


def test_a_cluster_can_be_answered_as_somebody_with_no_name(client):
    """UNKNOWN IS A QUESTION; UNNAMED IS AN ANSWER (owner 2026-09).

    A library of a television series is mostly background characters, and the
    only way out of the queue was to invent a name for each of them — junk in
    the catalog, and in every prompt an export writes. So a cluster can be
    answered "somebody, with no name": it leaves the queue, it joins the list
    of answered identities, and it stays ITS OWN person.
    """
    _, ids = _two_faces(client)
    assert len(client.get("/api/faces/unnamed").json()) == 2

    left = client.post("/api/faces/unnamed-cluster",
                       json={"face_ids": ids[:1]}).json()
    # The answered one is out of the queue; the other is still a question.
    assert len(left) == 1 and left[0]["faces"][0]["id"] == ids[1]
    held = [r for r in client.get("/api/subjects").json() if r["unnamed"]]
    assert len(held) == 1 and held[0]["display_name"] == ""

    # TWO OF THEM ARE TWO PEOPLE. On one shared "Unnamed" identity their
    # faces would fold together and naming one later would name both.
    client.post("/api/faces/unnamed-cluster", json={"face_ids": ids[1:]})
    marked = [r for r in client.get("/api/subjects").json() if r["unnamed"]]
    assert len(marked) == 2
    assert client.get("/api/faces/unnamed").json() == []
    # …and each is a cluster of the ANSWERED list, one face apiece.
    named = client.get("/api/faces/named").json()["clusters"]
    assert sorted(len(c["faces"]) for c in named) == [1, 1]

    # The way back is the same verb: it is a question again.
    client.post("/api/faces/unnamed-cluster",
                json={"face_ids": ids[:1], "unnamed": False})
    assert len(client.get("/api/faces/unnamed").json()) == 1


def test_answering_unnamed_reverts_whole(client):
    _, ids = _two_faces(client)
    client.post("/api/faces/unnamed-cluster", json={"face_ids": ids})
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "set_cluster_unnamed")
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).json()["reverted"]
    assert [r for r in client.get("/api/subjects").json() if r["unnamed"]] == []
    assert len(client.get("/api/faces/unnamed").json()) == 2


def test_merging_twice_reuses_the_identity_rather_than_minting_another(client):
    _, ids = _two_faces(client)
    first = client.post("/api/faces/merge-clusters", json={"face_ids": ids}).json()
    before = len(client.get("/api/subjects").json())
    again = client.post("/api/faces/merge-clusters", json={"face_ids": ids}).json()
    assert again[0]["subject_id"] == first[0]["subject_id"]
    assert len(client.get("/api/subjects").json()) == before


def test_naming_a_merged_cluster_names_the_identity_it_already_has(client):
    """Not a second subject beside it — that would leave the first orphaned."""
    item, ids = _two_faces(client)
    merged = client.post("/api/faces/merge-clusters", json={"face_ids": ids}).json()
    held = merged[0]["subject_id"]
    before = len(client.get("/api/subjects").json())

    client.post("/api/faces/name-cluster",
                json={"face_ids": ids, "display_name": "Alice"})
    subs = client.get("/api/subjects").json()
    assert len(subs) == before          # named in place
    alice = next(r for r in subs if r["id"] == held)
    assert alice["display_name"] == "Alice" and alice["tag"] == "subject:alice"
    # And her tag landed on the picture, which is the point of naming faces.
    tags = [t["name"] for t in client.get(f"/api/items/{item}").json()["tags"]]
    assert "subject:alice" in tags
    assert client.get("/api/faces/unnamed").json() == []


def test_a_merge_needs_at_least_two_faces(client):
    _, ids = _two_faces(client)
    assert client.post("/api/faces/merge-clusters",
                       json={"face_ids": ids[:1]}).status_code == 400


def test_a_stray_face_can_be_split_onto_a_new_person(client):
    """A cluster is nearly always one person plus a stray, and the stray needs
    somewhere to go that is not "nobody" — losing the grouping would only mean
    finding it again. One face is a legitimate split."""
    from media_compost.db import Face

    item, ids = _two_faces(client)
    client.post("/api/faces/name-cluster",
                json={"face_ids": ids, "display_name": "Alice"})
    subs = {r["display_name"]: r for r in client.get("/api/subjects").json()}
    assert "Alice" in subs

    out = client.post("/api/faces/split", json={"face_ids": [ids[0]]}).json()
    stray = next(c for c in out if any(f["id"] == ids[0] for f in c["faces"]))
    assert len(stray["faces"]) == 1
    assert stray["subject_id"] not in (None, subs["Alice"]["id"])
    # The other face stayed with Alice.
    assert [f["id"] for f in client.get(
        f"/api/faces/subject/{subs['Alice']['id']}").json()] == [ids[1]]
    # And the item keeps her tag: a face is evidence, the tag is a separate
    # statement, and she may well still be in the picture.
    tags = [t["name"] for t in client.get(f"/api/items/{item}").json()["tags"]]
    assert "subject:alice" in tags


def test_splitting_always_makes_a_NEW_person(client):
    """Never reuses a nameless identity that happens to be among them — that is
    what merging does, and it would put the stray back where it came from."""
    _, ids = _two_faces(client)
    client.post("/api/faces/merge-clusters", json={"face_ids": ids})
    first = client.post("/api/faces/split", json={"face_ids": [ids[0]]}).json()
    a = next(c for c in first if any(f["id"] == ids[0] for f in c["faces"]))
    second = client.post("/api/faces/split", json={"face_ids": [ids[0]]}).json()
    b = next(c for c in second if any(f["id"] == ids[0] for f in c["faces"]))
    assert a["subject_id"] != b["subject_id"]


def test_selected_faces_can_be_moved_onto_an_existing_subject(client):
    """"Merge into the selected subject" is the ordinary naming path with a
    subject that already exists — so the tag lands on the picture too."""
    item, ids = _two_faces(client)
    alice = client.post("/api/subjects", json={"display_name": "Alice"}).json()
    aid = next(r for r in alice if r["display_name"] == "Alice")["id"]

    client.post("/api/faces/name-cluster",
                json={"face_ids": ids, "subject_id": aid})
    got = [f["id"] for f in client.get(f"/api/faces/subject/{aid}").json()]
    assert sorted(got) == sorted(ids)
    tags = [t["name"] for t in client.get(f"/api/items/{item}").json()["tags"]]
    assert "subject:alice" in tags


def test_a_split_off_face_is_counted_once_not_twice(client):
    """A nameless subject is what an unnamed CLUSTER is made of, so its faces
    belong to that list and not to the named one as well. Counting them in
    both made the library read as if splitting a face created faces."""
    _, ids = _two_faces(client)
    client.post("/api/faces/name-cluster",
                json={"face_ids": ids, "display_name": "Alice"})
    # The named half reports its own distinct count: the clusters may each be
    # capped to a row, so they cannot be summed for it.
    total = lambda: (
        client.get("/api/faces/named").json()["faces"]
        + sum(len(c["faces"]) for c in client.get("/api/faces/unnamed").json()))
    before = total()
    client.post("/api/faces/split", json={"face_ids": [ids[0]]})
    assert total() == before
    # And the split-off face is in the unnamed half, not the named one.
    named = [f["id"] for c in client.get("/api/faces/named").json()["clusters"]
             for f in c["faces"]]
    assert ids[0] not in named and ids[1] in named


def test_the_unnamed_view_returns_each_face_exactly_once(client):
    """The clusters must PARTITION the unnamed faces.

    A face in two clusters gives the Subjects list two rows with the same
    React key and double-counts the header — and it is exactly what happens
    if the clustering is ever run per embedding space and concatenated
    instead of being fed into one union-find."""
    a, b = _items(client)[:2]
    # Two that belong together, one that does not, and one with no descriptor.
    _detect(client, a, [_face(0.1, 0.1, embedding=[0.9, 0.1, 0.0]),
                        _face(0.5, 0.5, embedding=[0.1, 0.9, 0.0]),
                        _face(0.8, 0.1)],
            model="insightface_buffalo_l")
    _detect(client, b, [_face(0.2, 0.2, embedding=[0.88, 0.14, 0.0])],
            model="insightface_buffalo_l")

    seen: list[int] = []
    for cluster in client.get("/api/faces/unnamed?limit=200").json():
        seen.extend(f["id"] for f in cluster["faces"])
    assert len(seen) == len(set(seen)), "a face appeared in two clusters"

    live = [f["id"] for i in (a, b)
            for f in client.get(f"/api/faces/item/{i}").json()]
    assert set(seen) == set(live), "every unnamed face is in exactly one cluster"


# ---- embedding spaces ------------------------------------------------------

def test_two_embedders_on_one_face_keep_two_descriptors(client):
    """The old single column let whichever model ran last overwrite the other,
    while `Face.model` recorded both — so a descriptor's space was unknowable
    from the row holding it."""
    from media_compost.db import Face
    from media_compost import faces as facelib

    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1, embedding=[0.9, 0.1, 0.0])],
            model="anime_face_magi")
    _detect(client, item, [_face(0.1, 0.1, embedding=[0.2, 0.3, 0.4])],
            model="insightface_buffalo_l")

    with client.lib.db.session() as s:
        face = s.execute(select(Face)).scalars().one()
        vectors = facelib.embeddings_of(s, [face.id])[face.id]
    assert set(vectors) == {"anime_face_magi", "insightface_buffalo_l"}
    assert vectors["anime_face_magi"] != vectors["insightface_buffalo_l"]
    # And the API says so.
    out = client.get(f"/api/faces/item/{item}").json()[0]
    assert out["embedded_by"] == ["anime_face_magi", "insightface_buffalo_l"]
    assert out["has_embedding"] is True


def test_a_suggestion_never_compares_across_spaces(client):
    """Two faces that are identical *as numbers* but described by different
    models are not evidence about each other."""
    a, b = _items(client)[:2]
    vec = [0.9, 0.1, 0.0]
    _detect(client, a, [_face(0.1, 0.1, embedding=vec)], model="anime_face_magi")
    face = client.get(f"/api/faces/item/{a}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    # The very same vector, from the OTHER model.
    _detect(client, b, [_face(0.2, 0.2, embedding=vec)],
            model="insightface_buffalo_l")
    assert _name(client.get(f"/api/faces/item/{b}").json()[0]) == ""


def test_each_space_is_judged_at_its_own_threshold(client):
    """0.62 was measured on drawn faces. Held against ArcFace it missed 14 of
    22 genuine pairs in this library — a 64% miss rate on photographs."""
    from media_compost import faces as facelib

    assert facelib.threshold_for("anime_face_magi") == facelib.SAME_PERSON
    arc = facelib.threshold_for("insightface_buffalo_l")
    assert 0.20 < arc < 0.40, arc          # the band measured as perfect
    # One knob still: asking for stricter moves every space the same way.
    assert facelib.threshold_for("insightface_buffalo_l", 0.70) > arc
    # A space nobody has measured falls back to the cautious default.
    assert facelib.threshold_for("brand_new_model", 0.5) == 0.5


def test_a_setting_outside_the_reference_band_still_means_something():
    """The map EXTRAPOLATES rather than clamping. Clamped, every setting from
    71% up was the same cutoff — the whole top of the slider, the default
    among them, inert with nothing saying so."""
    from media_compost import faces as facelib

    assert facelib.MATCH_DEFAULT > facelib.SAME_PERSON
    # A setting STRICTER than the default, whatever the default is. It was
    # the literal 0.9, which stopped being stricter than anything the day
    # the default moved there.
    stricter = (facelib.MATCH_DEFAULT + 0.99) / 2
    for space in ("anime_face_magi", "insightface_buffalo_l"):
        at_default = facelib.threshold_for(space, facelib.MATCH_DEFAULT)
        assert at_default > facelib.threshold_for(space, facelib.SAME_PERSON)
        assert at_default < facelib.threshold_for(space, stricter)
        # A cosine of two unit vectors: never asked to clear something no
        # pair can reach.
        assert 0.0 <= facelib.threshold_for(space, 0.99) < 1.0


# ---- rejections: the correction that sticks --------------------------------

def _guess_setup(client):
    """Alice named on one item, and a guess about her on another."""
    a, b = _items(client)[:2]
    _detect(client, a, [_face(0.1, 0.1, embedding=[0.9, 0.1, 0.0])],
            model="insightface_buffalo_l")
    face = client.get(f"/api/faces/item/{a}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})
    _detect(client, b, [_face(0.2, 0.2, embedding=[0.88, 0.14, 0.0])],
            model="insightface_buffalo_l")
    guess = client.get(f"/api/faces/item/{b}").json()[0]
    assert _by(guess) == "suggested"
    return b, subject, guess


def test_a_rejected_guess_is_not_offered_again(client):
    """The whole point: a re-run must not repeat a mistake somebody fixed."""
    item, _subject, guess = _guess_setup(client)
    client.delete(f"/api/faces/{guess['id']}/subject/{_sid(guess)}")

    _detect(client, item, [_face(0.2, 0.2, embedding=[0.88, 0.14, 0.0])],
            model="insightface_buffalo_l")
    again = client.get(f"/api/faces/item/{item}").json()[0]
    assert _name(again) == "", "the same wrong name came back"


def test_naming_a_guess_something_else_records_the_refusal(client):
    """A correction is two facts — "not Alice" and "is Bob" — and the first is
    what keeps the next run from repeating itself."""
    from media_compost.db import FaceRejection

    item, alice, guess = _guess_setup(client)
    bob = next(r for r in client.post(
        "/api/subjects", json={"display_name": "Bob"}).json()
        if r["display_name"] == "Bob")
    client.post(f"/api/faces/{guess['id']}" + "/subject", json={"subject_id": bob["id"]})

    with client.lib.db.session() as s:
        refused = s.execute(select(FaceRejection)).scalars().all()
    assert [(r.face_id, r.subject_id) for r in refused] == [
        (guess["id"], alice["id"])]


def test_moving_a_guessed_crop_onto_someone_records_the_refusal(client):
    """name-cluster's replace path is the drawer's "Move N → who": moving a
    crop off a machine's guess is the same correction `name_face` makes, so
    it records the refusal and takes back the pending tag the guess put on
    the item — and its undo clears the refusal again."""
    from media_compost.db import FaceRejection

    item, alice, guess = _guess_setup(client)
    bob = next(r for r in client.post(
        "/api/subjects", json={"display_name": "Bob"}).json()
        if r["display_name"] == "Bob")
    client.post("/api/faces/name-cluster",
                json={"face_ids": [guess["id"]], "subject_id": bob["id"]})

    with client.lib.db.session() as s:
        refused = s.execute(select(FaceRejection)).scalars().all()
    assert [(r.face_id, r.subject_id) for r in refused] == [
        (guess["id"], alice["id"])]
    names = [t["name"] for t in client.get(f"/api/items/{item}").json()["tags"]]
    assert "subject:alice" not in names, "the guess's pending tag went with it"

    ev = next(e for e in client.get("/api/history?limit=50").json()["events"]
              if e["action"] == "name_faces")
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    with client.lib.db.session() as s:
        assert s.execute(select(FaceRejection)).scalars().all() == []
    assert _name(client.get(f"/api/faces/item/{item}").json()[0]) == "Alice"


def test_taking_a_HAND_given_name_off_is_not_a_rejection(client):
    """Changing your mind is not the model being wrong."""
    from media_compost.db import FaceRejection

    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})
    client.delete(f"/api/faces/{face['id']}/subject/{subject['id']}")

    with client.lib.db.session() as s:
        assert s.execute(select(FaceRejection)).scalars().all() == []


def test_reverting_a_rejection_removes_it(client):
    """Otherwise the undo restores the name and the next run vetoes it — an
    undo that undoes itself."""
    from media_compost.db import FaceRejection

    item, _subject, guess = _guess_setup(client)
    client.delete(f"/api/faces/{guess['id']}/subject/{_sid(guess)}")
    ev = [e for e in client.get("/api/history?limit=50").json()["events"]
          if e["action"] == "unname_face"][0]
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})

    with client.lib.db.session() as s:
        assert s.execute(select(FaceRejection)).scalars().all() == []
    assert _name(client.get(f"/api/faces/item/{item}").json()[0]) == "Alice"


def test_a_split_says_the_two_are_different_and_a_merge_takes_it_back(client):
    from media_compost.db import SubjectCannotLink

    a, b = _items(client)[:2]
    for i in (a, b):
        _detect(client, i, [_face(0.1, 0.1)])
    ids = [client.get(f"/api/faces/item/{i}").json()[0]["id"] for i in (a, b)]
    client.post("/api/faces/merge-clusters", json={"face_ids": ids})
    merged = _sid(client.get(f"/api/faces/item/{a}").json()[0])

    client.post("/api/faces/split", json={"face_ids": [ids[1]]})
    with client.lib.db.session() as s:
        assert len(s.execute(select(SubjectCannotLink)).scalars().all()) == 1

    # Saying they are the same after all is the newer statement.
    client.post("/api/faces/merge-clusters", json={"face_ids": ids})
    with client.lib.db.session() as s:
        assert s.execute(select(SubjectCannotLink)).scalars().all() == []
    assert merged is not None


# ---- several people on one face, and their ages ---------------------------

def _named(client, name, **kw):
    rows = client.post("/api/subjects", json={"display_name": name, **kw}).json()
    return next(r for r in rows if r["display_name"] == name)


def _appearance(client, face, subject_id):
    return next(sub["id"] for sub in face["subjects"]
                if sub["subject_id"] == subject_id)


def test_one_face_can_be_two_people(client):
    """A drawn head is the character and the actor at once, and neither claim
    displaces the other — which is the whole reason "played by" is gone."""
    item = _items(client)[0]
    bond = _named(client, "James Bond")
    craig = _named(client, "Daniel Craig")
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    client.post(f"/api/faces/{face['id']}/subject", json={"subject_id": bond["id"]})
    client.post(f"/api/faces/{face['id']}/subject", json={"subject_id": craig["id"]})

    out = client.get(f"/api/faces/item/{item}").json()[0]
    assert sorted(_who(out)) == ["Daniel Craig", "James Bond"]
    # Both tags are on the picture: a name that assigns nothing is a label
    # with no consequence.
    names = {t["name"] for t in client.get(f"/api/items/{item}").json()["tags"]}
    assert {"subject:james_bond", "subject:daniel_craig"} <= names


def test_taking_one_name_off_leaves_the_other(client):
    item = _items(client)[0]
    bond = _named(client, "James Bond")
    craig = _named(client, "Daniel Craig")
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    for who in (bond, craig):
        client.post(f"/api/faces/{face['id']}/subject", json={"subject_id": who["id"]})
    client.delete(f"/api/faces/{face['id']}/subject/{craig['id']}")

    out = client.get(f"/api/faces/item/{item}").json()[0]
    assert _who(out) == ["James Bond"]


def test_one_frame_can_hold_three_actors_playing_one_character(client):
    """The multiverse case. A row keyed on (item, subject) cannot say this —
    which is why an appearance is per FACE."""
    item = _items(client)[0]
    hero = _named(client, "Spider-Man")
    actors = [_named(client, n) for n in ("Tobey", "Andrew", "Tom")]
    _detect(client, item, [_face(0.1, 0.1), _face(0.4, 0.1), _face(0.7, 0.1)])

    faces = client.get(f"/api/faces/item/{item}").json()
    for face, actor in zip(faces, actors):
        for who in (hero, actor):
            client.post(f"/api/faces/{face['id']}/subject",
                        json={"subject_id": who["id"]})

    out = client.get(f"/api/faces/item/{item}").json()
    assert all("Spider-Man" in _who(f) for f in out)
    assert {n for f in out for n in _who(f)} == {
        "Spider-Man", "Tobey", "Andrew", "Tom"}


def test_one_page_can_hold_one_character_at_two_ages(client):
    """A flashback panel beside a present-day one: one tag, two appearances,
    two ages — which a single date per assignment could not hold."""
    item = _items(client)[0]
    who = _named(client, "Kaguya", since_date=20100000)
    _detect(client, item, [_face(0.1, 0.1), _face(0.5, 0.5)])
    young, old = client.get(f"/api/faces/item/{item}").json()

    for face in (young, old):
        client.post(f"/api/faces/{face['id']}/subject", json={"subject_id": who["id"]})
    fresh = {f["id"]: f for f in client.get(f"/api/faces/item/{item}").json()}
    client.patch(f"/api/subjects/appearances/"
                 f"{_appearance(client, fresh[young['id']], who['id'])}",
                 json={"when": {"age": 6}})
    client.patch(f"/api/subjects/appearances/"
                 f"{_appearance(client, fresh[old['id']], who['id'])}",
                 json={"when": {"date": 20220000}})

    out = {f["id"]: f["subjects"][0] for f in
           client.get(f"/api/faces/item/{item}").json()}
    assert out[young["id"]]["when_age"] == 6
    # The other half is derived from the subject's since-date.
    assert out[young["id"]]["when_date"] == 20160000
    assert out[old["id"]]["when_age"] == 12
    assert out[old["id"]]["when_derived"] is True


def test_a_rerun_never_deletes_a_face_somebody_annotated(client):
    """`duplicates()` drops the unanswered box of an overlapping pair, so a
    name or a date has to count as an answer — otherwise the next detection
    run quietly throws the work away."""
    item = _items(client)[0]
    actor = _named(client, "Tom")
    _detect(client, item, [_face(0.1, 0.1, score=0.5)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    client.post(f"/api/faces/{face['id']}/subject", json={"subject_id": actor["id"]})

    # A stronger, overlapping detection of the same head.
    _detect(client, item, [_face(0.11, 0.11, score=0.99)])
    still = client.get(f"/api/faces/item/{item}").json()
    assert [f["id"] for f in still] == [face["id"]]
    assert _who(still[0]) == ["Tom"]


def test_the_named_list_carries_one_row_per_person_and_the_real_total(client):
    """The Subjects list draws ONE row of crops per person, so sending every
    face of somebody in three hundred pictures is three hundred crop URLs
    nothing will render. `per` caps what each cluster carries; `total` still
    says how many there are, or the "+N more" chip would report none left."""
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1), _face(0.4, 0.1), _face(0.7, 0.1)])
    ids = [f["id"] for f in client.get(f"/api/faces/item/{item}").json()]
    client.post("/api/faces/name-cluster",
                json={"face_ids": ids, "display_name": "Alice"})

    whole = client.get("/api/faces/named").json()
    assert [c["total"] for c in whole["clusters"]] == [3]
    assert len(whole["clusters"][0]["faces"]) == 3

    capped = client.get("/api/faces/named?per=2").json()
    assert len(capped["clusters"][0]["faces"]) == 2
    # What the chip counts, and what the header counts, both survive the cap.
    assert capped["clusters"][0]["total"] == 3
    assert capped["faces"] == 3
    # And the drawer can still ask for the whole set of the one it opens.
    who = capped["clusters"][0]["subject_id"]
    assert len(client.get(f"/api/faces/subject/{who}").json()) == 3


def test_a_run_is_recorded_even_when_it_finds_nothing(client):
    """`Face.model` says which detectors found a given face, which cannot
    answer "has this model looked here": an item it found nothing in has no
    face to carry the fact, and that is exactly the item a "skip what is
    already done" sweep must not run again."""
    empty, seen = _items(client)[0], _items(client)[1]
    _detect(client, empty, [], model="anime_face")
    _detect(client, seen, [_face(0.1, 0.1)], model="anime_face")

    assert client.get(f"/api/items/{empty}").json()["face_models"] == ["anime_face"]
    assert client.get(f"/api/items/{seen}").json()["face_models"] == ["anime_face"]
    # Nothing was found in the first, so there is no face to have read it off.
    assert client.get(f"/api/faces/item/{empty}").json() == []

    # A second detector adds itself rather than replacing the first.
    _detect(client, seen, [_face(0.5, 0.5)], model="insightface_faces")
    assert client.get(f"/api/items/{seen}").json()["face_models"] == [
        "anime_face", "insightface_faces"]
    # And running the same one again does not double the row.
    _detect(client, seen, [_face(0.5, 0.5)], model="insightface_faces")
    assert client.get(f"/api/items/{seen}").json()["face_models"] == [
        "anime_face", "insightface_faces"]


def test_a_run_can_skip_the_items_that_model_already_saw(client):
    """Over a whole group, re-running everything is the difference between
    minutes and hours — and the client cannot filter it, because knowing would
    mean fetching every item's detail."""
    a, b = _items(client)[0], _items(client)[1]
    _detect(client, a, [_face(0.1, 0.1)], model="anime_face")

    r = client.post("/api/ml/jobs", json={
        "kind": "faces", "model": "anime_face", "item_ids": [a, b],
        "skip_done": True})
    assert r.status_code == 200, r.text
    assert r.json()["skipped"] == 1
    # `faces` is a BATCH kind, so the remaining item is one job, not one each.
    assert r.json()["job_ids"]

    # Without the flag nothing is skipped — a re-run stays a choice.
    r = client.post("/api/ml/jobs", json={
        "kind": "faces", "model": "anime_face", "item_ids": [a, b]})
    assert r.json()["skipped"] == 0

    # A DIFFERENT model has seen neither, so nothing is skipped.
    r = client.post("/api/ml/jobs", json={
        "kind": "faces", "model": "insightface_faces", "item_ids": [a, b],
        "skip_done": True})
    assert r.json()["skipped"] == 0


def test_a_face_named_twice_is_listed_under_both(client):
    """Bond's strip holds every Bond face whoever played them; Craig's holds
    every face of Craig whatever he was playing. It is one face either way."""
    item = _items(client)[0]
    bond = _named(client, "James Bond")
    craig = _named(client, "Daniel Craig")
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    for who in (bond, craig):
        client.post(f"/api/faces/{face['id']}/subject", json={"subject_id": who["id"]})

    clusters = client.get("/api/faces/named").json()["clusters"]
    by_subject = {c["subject_id"]: c for c in clusters}
    assert face["id"] in [f["id"] for f in by_subject[bond["id"]]["faces"]]
    assert face["id"] in [f["id"] for f in by_subject[craig["id"]]["faces"]]


def test_dropping_crops_onto_somebody_moves_them_but_shift_copies(client):
    """Dropping says "these are hers and not his" — a MOVE. Shift says "these
    are hers AS WELL", which is the character-and-the-actor case and the whole
    reason a face can be several people."""
    item = _items(client)[0]
    bond = _named(client, "James Bond")
    craig = _named(client, "Daniel Craig")
    blofeld = _named(client, "Blofeld")
    _detect(client, item, [_face(0.1, 0.1), _face(0.5, 0.5)])
    a, b = client.get(f"/api/faces/item/{item}").json()
    client.post(f"/api/faces/{a['id']}/subject", json={"subject_id": bond["id"]})
    client.post(f"/api/faces/{b['id']}/subject", json={"subject_id": bond["id"]})

    # Copy: Bond stays, Craig joins him.
    client.post("/api/faces/name-cluster",
                json={"face_ids": [a["id"]], "subject_id": craig["id"],
                      "replace": False})
    face = next(f for f in client.get(f"/api/faces/item/{item}").json()
                if f["id"] == a["id"])
    assert sorted(_who(face)) == ["Daniel Craig", "James Bond"]

    # Move: Blofeld takes the other one over entirely.
    client.post("/api/faces/name-cluster",
                json={"face_ids": [b["id"]], "subject_id": blofeld["id"]})
    face = next(f for f in client.get(f"/api/faces/item/{item}").json()
                if f["id"] == b["id"])
    assert _who(face) == ["Blofeld"]


def test_an_age_travels_with_a_dropped_crop(client):
    """A face said to be twelve stays twelve whoever it turns out to be: the
    age describes the picture, not the name on it, and losing it on a drop is
    losing something nobody could get back from the crop."""
    item = _items(client)[0]
    alice = _named(client, "Alice", since_date=19900000)
    bob = _named(client, "Bob")
    _detect(client, item, [_face(0.1, 0.1)])
    face = client.get(f"/api/faces/item/{item}").json()[0]
    client.post(f"/api/faces/{face['id']}/subject", json={"subject_id": alice["id"]})
    face = client.get(f"/api/faces/item/{item}").json()[0]
    client.patch(f"/api/subjects/appearances/{_appearance(client, face, alice['id'])}",
                 json={"when": {"date": 20020000, "age": None}})

    client.post("/api/faces/name-cluster",
                json={"face_ids": [face["id"]], "subject_id": bob["id"]})
    moved = client.get(f"/api/faces/item/{item}").json()[0]
    assert _who(moved) == ["Bob"]
    assert moved["subjects"][0]["when_date"] == 20020000, "the age came with it"


# ---- naming propagates to the lookalikes ------------------------------------

def test_naming_a_face_suggests_it_to_the_unnamed_lookalikes(client):
    """The clusters are derived at read time and the ordinary suggestion pass
    runs only when a detection job applies — so naming one face of a cluster
    used to leave its lookalikes waiting for the next run to be told. A
    hand-naming now runs the same pass over the items whose unnamed faces
    agree with the face just named: same thresholds, same runner-up margin,
    same rejections, because it IS `suggest_subjects` with the fresh answer
    in the pool."""
    a, b = _items(client)[:2]
    # Both detections happen BEFORE anybody is named: the pool is empty, so
    # b's face starts with no suggestion — the state the propagation is for.
    _detect(client, a, [_face(0.1, 0.1, embedding=[0.9, 0.1, 0.0])],
            model="insightface_buffalo_l")
    _detect(client, b, [_face(0.2, 0.2, embedding=[0.88, 0.14, 0.0])],
            model="insightface_buffalo_l")
    assert _name(client.get(f"/api/faces/item/{b}").json()[0]) == ""

    face = client.get(f"/api/faces/item/{a}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}/subject",
                json={"subject_id": subject["id"]})

    other = client.get(f"/api/faces/item/{b}").json()[0]
    assert _by(other) == "suggested"
    assert _name(other) == "Alice"
    # The suggestion assigned the subject's tag PENDING, like a detection
    # run's would (there is one code path).
    tags = client.get(f"/api/items/{b}").json()["tag_instances"]
    assert any(t["pending"] for t in tags)


def test_propagation_respects_a_recorded_refusal(client):
    """A face somebody said is NOT this person is not re-offered by the
    propagation either — the veto rides the shared pass."""
    b, subject, guess = _guess_setup(client)
    # Refuse the guess on b's face...
    client.delete(f"/api/faces/{guess['id']}/subject/{subject['id']}")
    assert _name(client.get(f"/api/faces/item/{b}").json()[0]) == ""
    # ...then hand-name ANOTHER lookalike (a second face on the same item —
    # the fixture library has two items); the refused face stays unnamed.
    a = next(i for i in _items(client) if i != b)
    _detect(client, a, [_face(0.6, 0.6, embedding=[0.89, 0.12, 0.0])],
            model="insightface_buffalo_l")
    # The detection pass already SUGGESTED Alice for it (the pool has her);
    # hand-naming it is the confirmation gesture that triggers propagation.
    third = next(f for f in client.get(f"/api/faces/item/{a}").json()
                 if _by(f) == "suggested")
    # The detection itself may have suggested Alice here; hand-confirm by
    # naming it outright, which is the propagation trigger.
    client.post(f"/api/faces/{third['id']}/subject",
                json={"subject_id": subject["id"]})
    assert _name(client.get(f"/api/faces/item/{b}").json()[0]) == ""


# ---------------------------------------------------------------------------
# What the open cluster's pictures say, so its crops can be grouped by it.


def test_the_grouping_answer_counts_crops_and_follows_an_implication(client):
    """The capsule's number is CROPS, and `grin` lands under `smile`.

    Two facts in one answer: a picture with two faces in it puts two crops in
    its tags' groups (the grid draws a card per crop), and a tag set that says
    `grin` entails `smile` groups the grinning picture under `smile` — which
    is what somebody means by grouping on an expression.
    """
    items = _items(client)
    a, b = items[0], items[1]
    # TWO faces in the first picture, one in the second — which is what makes
    # "crops" and "pictures" different numbers, and what leaves a crop the
    # tags below are not on (a tag on every crop is not offered at all; see
    # the test after next).
    _detect(client, a, [{"box": [0.1, 0.1, 0.2, 0.2]},
                        {"box": [0.5, 0.5, 0.2, 0.2]}])
    _detect(client, b, [{"box": [0.1, 0.1, 0.2, 0.2]}])
    client.post("/api/tags/quick-assign",
                json={"item_ids": [a], "positive": ["grin"]}).raise_for_status()
    # …and `grin` implies `smile`, the library's own edge.
    grin = next(t for t in client.get("/api/tags").json()
                if t["name"] == "grin")
    r = client.post(f"/api/tags/{grin['id']}/implies", json={"name": "smile"})
    assert r.status_code == 200, r.text

    face_ids = [f["id"] for it in (a, b)
                for f in client.get(f"/api/faces/item/{it}").json()]
    assert len(face_ids) == 3
    out = client.post("/api/faces/grouping",
                      json={"face_ids": face_ids}).json()

    counts = dict(zip(out["tag_names"], out["tag_faces"]))
    # `smile` is on TWO CROPS and ONE PICTURE: the grinning picture holds two
    # faces, and the implication puts both of them under it.
    assert counts["smile"] == 2
    assert counts["grin"] == 2
    # And each face names its tags by index into that one list of names — the
    # grinning picture's two crops carry both names, the other picture's
    # carries neither.
    at = {f: set(out["tag_names"][i] for i in ts)
          for f, ts in zip(out["face_ids"], out["tags"])}
    assert sorted(sorted(v) for v in at.values()) == [
        [], ["grin", "smile"], ["grin", "smile"]]


def test_a_tag_on_one_crop_is_not_offered_as_a_grouping(client):
    """A group of one is not a grouping, so the bar does not offer it."""
    items = _items(client)
    a, b = items[0], items[1]
    _detect(client, a, [{"box": [0.1, 0.1, 0.2, 0.2]},
                        {"box": [0.5, 0.5, 0.2, 0.2]}])
    _detect(client, b, [{"box": [0.1, 0.1, 0.2, 0.2]}])
    client.post("/api/tags/quick-assign",
                json={"item_ids": [b], "positive": ["lonely"]}).raise_for_status()
    client.post("/api/tags/quick-assign",
                json={"item_ids": [a], "positive": ["shared"]}).raise_for_status()
    face_ids = [f["id"] for it in (a, b)
                for f in client.get(f"/api/faces/item/{it}").json()]
    out = client.post("/api/faces/grouping",
                      json={"face_ids": face_ids}).json()
    # `shared` is on the two crops of one picture; `lonely` on the single
    # crop of the other, which is a group of one.
    assert out["tag_names"] == ["shared"]


def test_a_tag_on_every_crop_is_not_offered_either(client):
    """It makes one section holding the lot — the ungrouped grid with a
    heading on it. The cluster's OWN subject tag is always one of these, and
    the most frequent tag there is, so it would lead the bar and be the one
    capsule on it that cannot do anything."""
    items = _items(client)
    a, b = items[0], items[1]
    _detect(client, a, [{"box": [0.1, 0.1, 0.2, 0.2]},
                        {"box": [0.5, 0.5, 0.2, 0.2]}])
    _detect(client, b, [{"box": [0.1, 0.1, 0.2, 0.2]}])
    client.post("/api/tags/quick-assign",
                json={"item_ids": [a, b],
                      "positive": ["everywhere"]}).raise_for_status()
    client.post("/api/tags/quick-assign",
                json={"item_ids": [a], "positive": ["somewhere"]}).raise_for_status()
    face_ids = [f["id"] for it in (a, b)
                for f in client.get(f"/api/faces/item/{it}").json()]
    out = client.post("/api/faces/grouping",
                      json={"face_ids": face_ids}).json()
    # `everywhere` is on all three crops and would make one section holding
    # the lot; `somewhere` is on two of them and is a real cut.
    assert out["tag_names"] == ["somewhere"]
    assert out["tag_faces"] == [2]


def test_the_grouping_answer_names_each_crop_s_sequence(client):
    """A crop's picture may be a page of a book, and that is a way to lay the
    grid out — so the answer carries the sequence's NAME per crop, "" for a
    picture that is a page of nothing."""
    from media_compost.db import Item, Sequence, SequenceItem

    items = _items(client)
    a, b = items[0], items[1]
    _detect(client, a, [{"box": [0.1, 0.1, 0.2, 0.2]}])
    _detect(client, b, [{"box": [0.1, 0.1, 0.2, 0.2]}])
    with client.lib.db.session() as s:
        seq = Sequence(name="Chapter one", kind="manual")
        s.add(seq)
        s.flush()
        s.add(SequenceItem(sequence_id=seq.id, item_id=a, position=0))
        s.get(Item, a).main_sequence_id = seq.id
        s.commit()

    face_ids = [f["id"] for it in (a, b)
                for f in client.get(f"/api/faces/item/{it}").json()]
    out = client.post("/api/faces/grouping",
                      json={"face_ids": face_ids}).json()
    by_face = dict(zip(out["face_ids"], out["sequences"]))
    a_face = client.get(f"/api/faces/item/{a}").json()[0]["id"]
    b_face = client.get(f"/api/faces/item/{b}").json()[0]["id"]
    assert by_face[a_face] == "Chapter one"
    assert by_face[b_face] == ""
