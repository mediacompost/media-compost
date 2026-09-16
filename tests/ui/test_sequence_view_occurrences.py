"""A sequence view shows a repeated page ONCE PER POSITION.

A book's blank pages all dedup onto one item, and the sequence keeps the
book's structure — so a chapter of 24 pages is 24 cards, whatever the
pictures are. The grid used to fold them (one card per distinct item),
which quietly showed the wrong book: 22 cards, a "/ 24" beside them, and
no way to tell which pages were missing.

The three things that have to hold together are the COUNT (the grid
reserves cards from it), the KEYS (`member_id`, or React collapses the
copies back into one) and the CHIP (each card's own position). Everything
else in the app keeps counting distinct items, which is why
`prefilter.base_select` takes the choice as an argument.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.importer import ImportOptions, Importer
from media_compost.ui.config import UiConfig
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
        yield c
    app.dependency_overrides.clear()


def _book(client) -> tuple[int, list[int]]:
    """A three-position sequence over two items: [a, b, a]."""
    ids = [i["id"] for i in client.get("/api/items").json()["items"][:2]]
    a, b = ids
    seq = client.post("/api/sequences", json={
        "name": "book", "item_ids": [a, b, a]}).json()
    return seq["id"], [a, b, a]


def test_the_view_pages_occurrences_not_items(client):
    seq_id, order = _book(client)
    page = client.get(f"/api/items?sequence={seq_id}").json()
    assert page["total"] == 3, "the count folded the repeated page away"
    assert [i["id"] for i in page["items"]] == order
    # Each card is its OWN occurrence, and says which one it is.
    assert [i["seq_index"] for i in page["items"]] == [1, 2, 3]
    assert all(i["seq_total"] == 3 for i in page["items"])
    member_ids = [i["member_id"] for i in page["items"]]
    assert len(set(member_ids)) == 3, "the two copies share a React key"
    assert all(m is not None for m in member_ids)


def test_a_search_inside_the_view_still_pages_occurrences(client):
    """The POST path is the one the grid actually uses."""
    seq_id, order = _book(client)
    page = client.post("/api/items/query", json={"sequence": seq_id}).json()
    assert page["total"] == 3
    assert [i["id"] for i in page["items"]] == order


def test_everything_else_still_counts_distinct_items(client):
    """Only the GRID wants occurrences. The facets — the width/height/MP
    ranges and the item count behind them — are about the pictures in view,
    and a repeated page is one picture however many times the book turns to
    it. This is what `occurrences=False` keeps, and the two numbers
    disagreeing (3 cards, 2 items) is the point rather than a bug."""
    seq_id, order = _book(client)
    assert client.get(f"/api/items?sequence={seq_id}").json()["total"] == 3
    facets = client.get(f"/api/items/facets?sequence={seq_id}").json()
    assert facets["count"] == len(set(order)) == 2


def test_outside_a_sequence_view_a_card_is_an_item(client):
    seq_id, order = _book(client)
    del seq_id
    page = client.get("/api/items").json()
    rows = [i for i in page["items"] if i["id"] == order[0]]
    assert len(rows) == 1
    assert rows[0]["member_id"] is None
    # The item's own badge still names its FIRST position — one card
    # standing for every copy is the right answer when the card is the item.
    assert rows[0]["seq_index"] == 1 and rows[0]["seq_total"] == 3
