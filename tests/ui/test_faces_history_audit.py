"""Every mutation the faces UI can make logs an event, and every one reverts.

The same sweep `test_tags_history_audit.py` runs over the Tags tab, for the
same reason: the gaps were invisible. Taking a name off a face, moving its
box, merging two clusters and splitting one all changed the library with
nothing in the log and nothing to undo — and the right-click menu that reaches
them can do it to nine crops at once.

Add an action to a face, add a case here.
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


# ---- helpers ---------------------------------------------------------------

def _items(client) -> list[int]:
    return [it["id"] for it in client.get("/api/items").json()["items"]]


def _detect(client, item_id: int, found: list[dict], model: str = "anime_face"):
    from media_compost.db import Item
    from media_compost.ui.jobs import JobQueue

    lib = client.lib
    queue = JobQueue.__new__(JobQueue)
    queue.lib = lib
    with lib.db.session() as s:
        item = s.get(Item, item_id)
        queue._apply_faces(s, item, found, model)
        s.commit()


def _face(x, y, w=0.2, h=0.2, score=0.9, embedding=None):
    d = {"box": [x, y, w, h], "score": score}
    if embedding is not None:
        d["embedding"] = embedding
    return d


def latest(client, action: str) -> dict:
    """The newest event of an action — and proof that one was written at all."""
    events = [e for e in client.get("/api/history?limit=200").json()["events"]
              if e["action"] == action]
    assert events, f"no {action} event was logged"
    return events[0]


def revert(client, event_id: int) -> None:
    r = client.post("/api/history/revert", json={"event_ids": [event_id]}).json()
    assert r["failed"] == [], f"event {event_id} refused to revert"


def faces_of(client, item_id: int) -> list[dict]:
    return client.get(f"/api/faces/item/{item_id}").json()


def one_face(client, item_id: int) -> dict:
    return faces_of(client, item_id)[0]


# ---- one face at a time ----------------------------------------------------

def test_drawing_a_face_by_hand_round_trips(client):
    item = _items(client)[0]
    client.post("/api/faces", json={"item_id": item, "x": 0.1, "y": 0.1,
                                    "w": 0.2, "h": 0.2})
    assert len(faces_of(client, item)) == 1
    revert(client, latest(client, "add_face")["id"])
    assert faces_of(client, item) == []


def test_naming_a_face_round_trips(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = one_face(client, item)
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]

    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})
    assert _name(one_face(client, item)) == "Alice"
    # Naming assigns the subject's tag, so the revert has to take it back off.
    assert "subject:alice" in {t["name"] for t in
                       client.get(f"/api/items/{item}").json()["tags"]}

    revert(client, latest(client, "name_face")["id"])
    assert _name(one_face(client, item)) == ""
    assert "subject:alice" not in {t["name"] for t in
                           client.get(f"/api/items/{item}").json()["tags"]}


def test_taking_a_name_off_a_face_round_trips(client):
    """The gap this file was written for: "not this person" changed the
    library and left nothing behind to undo it."""
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = one_face(client, item)
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{face['id']}" + "/subject", json={"subject_id": subject["id"]})

    client.delete(f"/api/faces/{face['id']}/subject/{subject['id']}")
    assert _name(one_face(client, item)) == ""

    revert(client, latest(client, "unname_face")["id"])
    back = one_face(client, item)
    assert _name(back) == "Alice"
    # The SHAPE, not just the id: a hand-named face must come back as an
    # answer, or the next detection run would overwrite it.
    assert _by(back) == "user"


def test_a_rejected_guess_comes_back_as_a_guess(client):
    """And with its pending tag, since the reason it was pending has not
    changed. Restored as a `user` answer it would be immune to the next run."""
    a, b = _items(client)[:2]
    _detect(client, a, [_face(0.1, 0.1, embedding=[0.9, 0.1, 0.0])],
            model="insightface_buffalo_l")
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{one_face(client, a)['id']}" + "/subject", json={"subject_id": subject["id"]})

    _detect(client, b, [_face(0.2, 0.2, embedding=[0.88, 0.14, 0.0])],
            model="insightface_buffalo_l")
    guess = one_face(client, b)
    assert _by(guess) == "suggested"

    client.delete(f"/api/faces/{guess['id']}/subject/{subject['id']}")
    assert "subject:alice" not in {t["name"] for t in
                           client.get(f"/api/items/{b}").json()["tags"]}

    revert(client, latest(client, "unname_face")["id"])
    back = one_face(client, b)
    assert _by(back) == "suggested" and _name(back) == "Alice"
    tags = {t["name"]: t for t in
            client.get(f"/api/items/{b}").json()["tag_instances"]}
    assert tags["subject:alice"]["pending"] is True


def test_dismissing_a_face_round_trips(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = one_face(client, item)

    client.patch(f"/api/faces/{face['id']}", json={"dismissed": True})
    assert one_face(client, item)["dismissed"] is True
    revert(client, latest(client, "dismiss_face")["id"])
    assert one_face(client, item)["dismissed"] is False


def test_moving_a_faces_box_round_trips(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = one_face(client, item)

    client.patch(f"/api/faces/{face['id']}",
                 json={"x": 0.5, "y": 0.5, "w": 0.3, "h": 0.3})
    moved = one_face(client, item)
    assert (moved["x"], moved["w"]) == (0.5, 0.3)

    revert(client, latest(client, "move_face")["id"])
    back = one_face(client, item)
    assert round(back["x"], 3) == 0.1 and round(back["w"], 3) == 0.2


def test_editing_a_detected_box_records_the_original_and_resets(client):
    """A hand edit of a DETECTED face's box keeps the detector's rectangle
    aside: the row reads `edited`, a re-run refreshes the RECORD rather than
    the row (the edit survives), and Reset restores the newest detection —
    all of it logged, and the reset's revert restores the edit AND the
    record."""
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = one_face(client, item)
    assert face["edited"] is False

    client.patch(f"/api/faces/{face['id']}",
                 json={"x": 0.5, "y": 0.5, "w": 0.3, "h": 0.3})
    assert one_face(client, item)["edited"] is True

    # A re-run finds the face slightly elsewhere (overlapping the edited
    # box, so it reconciles): the EDIT survives, and the fresh rectangle
    # lands in the reset record instead.
    _detect(client, item, [_face(0.48, 0.52, 0.3, 0.3, score=0.8)])
    kept = one_face(client, item)
    assert (kept["x"], kept["w"]) == (0.5, 0.3)
    assert kept["edited"] is True

    rows = client.post(f"/api/faces/{face['id']}/reset-box").json()
    back = next(f for f in rows if f["id"] == face["id"])
    # The newest detection's rectangle, not the first one's.
    assert round(back["x"], 3) == 0.48 and back["edited"] is False

    revert(client, latest(client, "reset_face_box")["id"])
    again = one_face(client, item)
    assert (again["x"], again["w"]) == (0.5, 0.3)
    assert again["edited"] is True


def test_reverting_the_first_edit_takes_the_record_with_it(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = one_face(client, item)
    client.patch(f"/api/faces/{face['id']}",
                 json={"x": 0.5, "y": 0.5, "w": 0.3, "h": 0.3})
    assert one_face(client, item)["edited"] is True
    revert(client, latest(client, "move_face")["id"])
    back = one_face(client, item)
    assert round(back["x"], 3) == 0.1
    # Undone, the box is the detector's again — not "hand-edited to it".
    assert back["edited"] is False


def test_a_hand_drawn_face_never_reads_edited(client):
    """There is no detector's rectangle to go back to."""
    item = _items(client)[0]
    client.post("/api/faces", json={"item_id": item,
                                    "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2})
    face = one_face(client, item)
    client.patch(f"/api/faces/{face['id']}", json={"x": 0.4})
    assert one_face(client, item)["edited"] is False
    r = client.post(f"/api/faces/{face['id']}/reset-box")
    assert r.status_code == 400


def test_a_patch_that_moves_nothing_logs_nothing(client):
    """An event per no-op would bury the log — and a revert of one would
    promise to undo something that never happened."""
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = one_face(client, item)
    client.patch(f"/api/faces/{face['id']}", json={"x": face["x"]})
    assert not [e for e in client.get("/api/history?limit=200").json()["events"]
                if e["action"] == "move_face"]


def test_deleting_a_face_round_trips(client):
    item = _items(client)[0]
    _detect(client, item, [_face(0.1, 0.1)])
    face = one_face(client, item)

    client.delete(f"/api/faces/{face['id']}")
    assert faces_of(client, item) == []

    revert(client, latest(client, "delete_face")["id"])
    back = one_face(client, item)
    assert round(back["x"], 3) == 0.1 and back["det_score"] == pytest.approx(0.9)


# ---- a set of faces at a time ----------------------------------------------

def test_naming_a_whole_cluster_round_trips(client):
    a, b = _items(client)[:2]
    for i in (a, b):
        _detect(client, i, [_face(0.1, 0.1)])
    ids = [one_face(client, i)["id"] for i in (a, b)]

    client.post("/api/faces/name-cluster",
                json={"face_ids": ids, "display_name": "Alice"})
    assert _name(one_face(client, a)) == "Alice"
    assert "subject:alice" in {t["name"] for t in
                       client.get(f"/api/items/{b}").json()["tags"]}

    revert(client, latest(client, "name_faces")["id"])
    assert _name(one_face(client, a)) == ""
    assert "subject:alice" not in {t["name"] for t in
                           client.get(f"/api/items/{b}").json()["tags"]}
    # The naming minted the subject, so undoing it takes that away too.
    assert "Alice" not in {r["display_name"]
                           for r in client.get("/api/subjects").json()}


def test_moving_faces_to_another_person_puts_them_back(client):
    """Dragging crops onto somebody else's row is `name-cluster` over faces
    that already had a name — so undoing it must return them to the person
    they came from, not to nobody."""
    a, b = _items(client)[:2]
    for i in (a, b):
        _detect(client, i, [_face(0.1, 0.1)])
    client.post("/api/faces/name-cluster",
                json={"face_ids": [one_face(client, a)["id"],
                                   one_face(client, b)["id"]],
                      "display_name": "Alice"})
    alice = next(r for r in client.get("/api/subjects").json()
                 if r["display_name"] == "Alice")
    client.post("/api/faces/name-cluster",
                json={"face_ids": [one_face(client, b)["id"]],
                      "display_name": "Bob"})
    assert _name(one_face(client, b)) == "Bob"

    revert(client, latest(client, "name_faces")["id"])
    back = one_face(client, b)
    assert _sid(back) == alice["id"]
    assert _by(back) == "user"


def test_merging_two_clusters_round_trips(client):
    a, b = _items(client)[:2]
    for i in (a, b):
        _detect(client, i, [_face(0.1, 0.1)])
    ids = [one_face(client, i)["id"] for i in (a, b)]

    client.post("/api/faces/merge-clusters", json={"face_ids": ids})
    merged = _sid(one_face(client, a))
    assert merged is not None and _sid(one_face(client, b)) == merged

    revert(client, latest(client, "merge_faces")["id"])
    assert _sid(one_face(client, a)) is None
    assert _sid(one_face(client, b)) is None
    # The identity the merge invented goes with it.
    assert merged not in {r["id"] for r in client.get("/api/subjects").json()}


def test_splitting_faces_off_round_trips(client):
    a, b = _items(client)[:2]
    for i in (a, b):
        _detect(client, i, [_face(0.1, 0.1)])
    ids = [one_face(client, i)["id"] for i in (a, b)]
    client.post("/api/faces/name-cluster",
                json={"face_ids": ids, "display_name": "Alice"})
    alice = next(r for r in client.get("/api/subjects").json()
                 if r["display_name"] == "Alice")

    stray = one_face(client, b)["id"]
    client.post("/api/faces/split", json={"face_ids": [stray]})
    assert _sid(one_face(client, b)) != alice["id"]

    revert(client, latest(client, "split_faces")["id"])
    back = one_face(client, b)
    assert _sid(back) == alice["id"]
    # Back as the answer it was, not as a nameless leftover.
    assert _by(back) == "user"
