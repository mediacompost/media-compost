"""The unnamed-faces view after its SQL-side partition + cache rewrite.

`_unnamed` now excludes named faces in SQL, cuts the cluster list to `limit`
before hydrating a single Face row, and clusters through the library's
FaceCache. The RESPONSE is a contract — the frontend keys rows off it — so
this file pins the payload structurally: exact cluster order, exact face
rows (deep-equal to the per-item face listing, which shares the hydrator),
exact totals, and the exact fields.
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

from media_compost.testing import make_image


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(4):
        make_image(src / f"p{i}.png", seed=40 + i, size=(400, 300))
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([src], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


def _detect(client, item_id: int, found: list[dict],
            model: str = "insightface_buffalo_l"):
    from media_compost.db import Item
    from media_compost.ui.jobs import JobQueue

    queue = JobQueue.__new__(JobQueue)
    queue.lib = client.lib
    with client.lib.db.session() as s:
        item = s.get(Item, item_id)
        queue._apply_faces(s, item, found, model)
        s.commit()


def _face(x, y, w=0.2, h=0.2, score=0.9, embedding=None):
    d = {"box": [x, y, w, h], "score": score}
    if embedding is not None:
        d["embedding"] = embedding
    return d


def _seed(client):
    """A merged pair, an embedding-clustered pair, a descriptorless single,
    and one NAMED face that must never appear in the unnamed view."""
    items = [it["id"] for it in client.get("/api/items").json()["items"]]
    merged_item, near_item, single_item, named_item = items[:4]

    # Two descriptorless faces, merged BY HAND (sizes differ: order matters).
    _detect(client, merged_item, [_face(0.05, 0.05, 0.30, 0.30),
                                  _face(0.60, 0.60, 0.20, 0.20)],
            model="anime_face")
    merged_ids = [f["id"] for f in
                  client.get(f"/api/faces/item/{merged_item}").json()]
    client.post("/api/faces/merge-clusters", json={"face_ids": merged_ids})

    # Two faces the descriptors agree about.
    _detect(client, near_item, [_face(0.05, 0.05, 0.25, 0.25,
                                      embedding=[0.9, 0.1, 0.0]),
                                _face(0.60, 0.60, 0.15, 0.15,
                                      embedding=[0.88, 0.14, 0.0])])

    # One face nothing describes.
    _detect(client, single_item, [_face(0.4, 0.4, 0.10, 0.10)],
            model="anime_face")

    # A named face — the SQL partition must keep it (and only it) out.
    _detect(client, named_item, [_face(0.2, 0.2)])
    named_face = client.get(f"/api/faces/item/{named_item}").json()[0]
    subject = client.post("/api/subjects",
                          json={"display_name": "Alice"}).json()[0]
    client.post(f"/api/faces/{named_face['id']}/subject",
                json={"subject_id": subject["id"]})
    return merged_item, near_item, single_item, named_item


def test_unnamed_payload_is_structurally_stable(client):
    merged_item, near_item, single_item, named_item = _seed(client)

    def faces_of(item_id):
        return client.get(f"/api/faces/item/{item_id}").json()

    merged_faces = faces_of(merged_item)      # already biggest-first
    held_by = merged_faces[0]["subjects"][0]["subject_id"]
    expected = [
        {"faces": merged_faces, "total": 2, "grouped": True,
         "subject_id": held_by, "guesses": 0},
        {"faces": faces_of(near_item), "total": 2, "grouped": True,
         "subject_id": None, "guesses": 0},
        {"faces": faces_of(single_item), "total": 1, "grouped": False,
         "subject_id": None, "guesses": 0},
    ]
    got = client.get("/api/faces/unnamed?limit=40").json()
    assert got == expected, "the payload is a contract, field for field"
    # And the named face is nowhere in it.
    named_ids = {f["id"] for f in faces_of(named_item)}
    assert not named_ids & {f["id"] for c in got for f in c["faces"]}


def test_unnamed_limit_cuts_the_cluster_list(client):
    _seed(client)
    assert len(client.get("/api/faces/unnamed?limit=40").json()) == 3
    cut = client.get("/api/faces/unnamed?limit=2").json()
    assert len(cut) == 2
    # The order survives the cut: merged first, then the biggest loose group.
    assert [c["total"] for c in cut] == [2, 2]
    assert cut[0]["subject_id"] is not None
    assert len(client.get("/api/faces/unnamed?limit=1").json()) == 1


def test_unnamed_is_stable_across_repeat_reads(client):
    """The cache answers the second read; the payload must not shift."""
    _seed(client)
    first = client.get("/api/faces/unnamed?limit=40").json()
    assert client.get("/api/faces/unnamed?limit=40").json() == first

    # A change invalidates: dismissing the single face removes its cluster.
    single = first[-1]["faces"][0]["id"]
    client.patch(f"/api/faces/{single}", json={"dismissed": True})
    after = client.get("/api/faces/unnamed?limit=40").json()
    assert len(after) == 2
    assert single not in {f["id"] for c in after for f in c["faces"]}
