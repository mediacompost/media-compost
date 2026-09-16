"""`POST /api/items/ids` — the ids of one stretch of the view's order.

What a SHIFT+CLICK asks for when the other end has scrolled out of the loaded
pages: the grid holds only what it has drawn, so "which items are between
these two positions" is the one question it cannot answer about its own view.

The contract is that the answer is the SAME ORDER the grid pages through, so
these hold it to the pages rather than to a list written out by hand — a range
that disagreed with the grid by one would select the wrong pictures and look
exactly like selecting the right ones.
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
from media_compost.ui.server.routers.items import SELECT_RANGE_MAX


@pytest.fixture
def client(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        s.execute(insert(Item), [
            {"uid": f"r{i:04d}", "name": f"item {i:03d}",
             "kind": "video" if i % 7 == 0 else "image"}
            for i in range(120)])
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


def _ids(client, start, count, **scope) -> dict:
    r = client.post("/api/items/ids",
                    json={**scope, "start": start, "count": count})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("scope", [
    {},
    {"kind": "video"},
    {"sort": "name_asc"},
    {"sort": "name_desc"},
    {"query": {"type": "group", "op": "and", "children": []}},
])
def test_a_range_is_the_SAME_ORDER_the_grid_pages_through(client, scope):
    """Not a list written out here — the pages themselves, which is the only
    definition of "between these two" a shift+click can mean."""
    every = _paged(client, **scope)
    assert len(every) > 10, len(every)
    for start, count in [(0, 5), (3, 7), (10, 40), (len(every) - 3, 3)]:
        got = _ids(client, start, count, **scope)
        assert got["ids"] == every[start:start + count], (scope, start, count)
        assert got["total"] == count


def test_a_range_past_the_end_stops_at_the_end(client):
    every = _paged(client)
    got = _ids(client, len(every) - 2, 50)
    assert got["ids"] == every[-2:]
    # `total` is what was ASKED for, so a caller can tell a short answer from
    # a short range.
    assert got["total"] == 50


def test_an_empty_range_is_no_query_at_all(client):
    for count in (0, -5):
        assert _ids(client, 10, count)["ids"] == []


def test_the_range_is_CAPPED_and_says_so(client, monkeypatch):
    """A shift+click is bounded by the VIEW, which can be the whole library,
    and what comes back is a selection the browser holds and re-derives from
    on every render. The cap is far past any real gesture; what matters is
    that `total` still reports the range's true length, so a caller is never
    quietly handed a short answer as if it were the whole thing."""
    from media_compost.ui.server.routers import items as items_router

    monkeypatch.setattr(items_router, "SELECT_RANGE_MAX", 4)
    got = _ids(client, 0, 30)
    assert len(got["ids"]) == 4
    assert got["total"] == 30
    assert got["ids"] == _paged(client)[:4]
    assert SELECT_RANGE_MAX > 10_000, "the real cap is not a limit anybody meets"
