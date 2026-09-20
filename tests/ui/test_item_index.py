"""`POST /api/items/index` — where ONE item sits in the view's order.

What a bookmark needs in order to scroll to what it points at: the view has
been restored and the picture is selected, and the only thing missing is
which row it is on. The grid cannot answer it — it holds the pages it has
drawn, and the answer is usually not among them.

The contract is that the answer is an index into the SAME ORDER the grid
pages through, so these hold it to the pages rather than to a list written
out by hand: an index that disagreed with the grid by one would scroll to
the wrong picture and look exactly like scrolling to the right one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from media_compost.db import File, Item
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        s.execute(insert(Item), [
            {"uid": f"r{i:04d}", "name": f"item {i:03d}",
             "kind": "video" if i % 7 == 0 else "image"}
            for i in range(60)])
        ids = list(s.execute(select(Item.id).order_by(Item.id)).scalars())
        s.execute(insert(File), [
            {"item_id": i, "number": 1, "path": "files/1.png",
             "sha256": f"h{i}", "width": 10, "height": 10, "bytes": 1,
             "format": "png"} for i in ids])
        for i, f in zip(ids, s.execute(select(File.id).order_by(File.id))
                        .scalars()):
            s.get(Item, i).active_file_id = f
        s.commit()
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    deps.reset_library()


def _paged(client, **scope) -> list[int]:
    """Every id of the view, walked the way the grid walks it."""
    out: list[int] = []
    page = 1
    while True:
        got = client.post("/api/items/query",
                          json={**scope, "page": page, "page_size": 25}).json()
        out += [i["id"] for i in got["items"]]
        if len(out) >= got["total"] or not got["items"]:
            return out
        page += 1


def _index(client, item_id: int, **scope):
    return _indices(client, [item_id], **scope)[0]


def _indices(client, item_ids: list[int], **scope):
    r = client.post("/api/items/index",
                    json={**scope, "item_ids": item_ids})
    assert r.status_code == 200, r.text
    return r.json()["indices"]


def test_the_index_is_the_position_the_pages_put_it_at(client):
    for sort in ("recent_desc", "name_asc", "name_desc"):
        order = _paged(client, sort=sort)
        assert len(order) == 60
        # Every tenth, and both ends: a window function that was off by one
        # would be off everywhere, and one that ignored the sort would only
        # show on the ends.
        for at in (0, 1, 10, 30, 59):
            assert _index(client, order[at], sort=sort) == at, (sort, at)


def test_a_narrower_view_is_a_different_answer(client):
    """The index is into THIS view, not into the library."""
    all_ids = _paged(client, sort="name_asc")
    videos = _paged(client, sort="name_asc", kind="video")
    assert 0 < len(videos) < len(all_ids)
    for at, iid in enumerate(videos):
        assert _index(client, iid, sort="name_asc", kind="video") == at
        # The same picture sits somewhere else in the whole library.
        assert _index(client, iid, sort="name_asc") == all_ids.index(iid)


def test_an_item_the_view_does_not_hold_answers_null(client):
    """Null is an ANSWER — the caller stops rather than scrolling
    somewhere arbitrary."""
    images = _paged(client, sort="name_asc", kind="image")
    videos = _paged(client, sort="name_asc", kind="video")
    assert _index(client, videos[0], sort="name_asc", kind="image") is None
    assert _index(client, images[0], sort="name_asc", kind="video") is None
    assert _index(client, 999_999, sort="name_asc") is None
    assert _index(client, 0, sort="name_asc") is None


def test_the_answers_come_back_in_the_order_they_were_asked(client):
    """One request for every bookmark at once — a walk of the view per
    bookmark is what the batch exists not to be."""
    order = _paged(client, sort="name_asc")
    want = [order[9], order[0], 999_999, order[40]]
    assert _indices(client, want, sort="name_asc") == [9, 0, None, 40]
    assert _indices(client, [], sort="name_asc") == []


def test_a_searched_view_counts_only_what_it_matches(client):
    """The RESIDUE path — `TAKEN:` is decided in Python, so the view is
    paged through a temp table and the positions have to come from there.
    Inverted (`have: false`), it holds every one of these undated items."""
    q = {"type": "group", "op": "and",
         "children": [{"type": "taken", "have": False}]}
    order = _paged(client, sort="name_asc", query=q)
    assert len(order) == 60
    for at in (0, 7, 59):
        assert _index(client, order[at], sort="name_asc", query=q) == at
