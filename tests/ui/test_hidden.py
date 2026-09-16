"""Hidden items: excluded from the grid and counts, shown only in Hidden view."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=True)
        )
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_hide_excludes_from_grid_counts_and_shows_in_hidden_view(client):
    page = client.get("/api/items").json()
    total_before = page["total"]
    assert total_before >= 2
    victim = page["items"][0]["id"]

    stats_before = client.get("/api/library/stats").json()
    client.post("/api/items/hide", json={"item_ids": [victim], "hidden": True})

    # Dropped from the normal grid and its total.
    page = client.get("/api/items").json()
    assert page["total"] == total_before - 1
    assert all(i["id"] != victim for i in page["items"])

    # Library counts exclude it; hidden count reflects it.
    stats = client.get("/api/library/stats").json()
    assert stats["items"] == stats_before["items"] - 1
    assert stats["hidden"] == 1

    # Visible only in the Hidden view.
    hv = client.get("/api/items", params={"hidden": True}).json()
    assert [i["id"] for i in hv["items"]] == [victim]
    assert hv["items"][0]["hidden"] is True

    # Still reachable directly (e.g. via a link).
    assert client.get(f"/api/items/{victim}").json()["hidden"] is True

    # Unhide restores it to the grid.
    client.post("/api/items/hide", json={"item_ids": [victim], "hidden": False})
    page = client.get("/api/items").json()
    assert page["total"] == total_before
    assert client.get("/api/library/stats").json()["hidden"] == 0


def test_hide_is_logged_and_revertible(client):
    victim = client.get("/api/items").json()["items"][0]["id"]
    client.post("/api/items/hide", json={"item_ids": [victim], "hidden": True})
    # Hide/show is logged under one combined "set_hidden" action carrying the
    # resulting state.
    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "set_hidden")
    assert ev["revertible"] is True and ev["entity_id"] == victim
    assert ev["data"]["hidden"] is True
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert client.get(f"/api/items/{victim}").json()["hidden"] is False
    # Reverting appends a new revert entry to the log.
    assert any(e["action"] == "revert" for e in
               client.get("/api/history").json()["events"])


def test_TRASHING_A_HIDDEN_ITEM_UNHIDES_IT(client):
    """Hidden and trashed are two different answers to "why is this not in
    the grid", and an item that was both said both: the sidebar's Hidden
    badge went on counting a picture the Hidden view no longer showed — a
    number nothing could make agree with the list under it.
    """
    victim = client.get("/api/items").json()["items"][0]["id"]
    client.post("/api/items/hide", json={"item_ids": [victim], "hidden": True})
    assert client.get("/api/library/stats").json()["hidden"] == 1

    client.post("/api/items/trash", json={"item_ids": [victim]})
    assert client.get("/api/library/stats").json()["hidden"] == 0
    assert client.get("/api/items", params={"hidden": True}).json()["items"] == []
    # …and it IS in the Trash, which is the one thing it now says.
    trash = client.get("/api/items", params={"trash": True}).json()
    assert [i["id"] for i in trash["items"]] == [victim]
    assert client.get(f"/api/items/{victim}").json()["hidden"] is False


def test_RESTORING_IT_PUTS_IT_BACK_THE_WAY_IT_WAS(client):
    """Trashing is what took the flag off, and a restore that left it off
    would put a picture somebody had deliberately put away back in the middle
    of the grid. The flag rides on the trash row beside the groups, which is
    already the record of what the item was before."""
    page = client.get("/api/items").json()
    victim, other = page["items"][0]["id"], page["items"][1]["id"]
    client.post("/api/items/hide",
                json={"item_ids": [victim, other], "hidden": True})
    client.post("/api/items/hide", json={"item_ids": [other], "hidden": False})
    client.post("/api/items/trash", json={"item_ids": [victim, other]})
    assert client.get("/api/library/stats").json()["hidden"] == 0

    client.post("/api/items/restore", json={"item_ids": [victim, other]})
    assert client.get(f"/api/items/{victim}").json()["hidden"] is True
    assert client.get(f"/api/items/{other}").json()["hidden"] is False
    assert client.get("/api/library/stats").json()["hidden"] == 1
    assert [i["id"] for i in
            client.get("/api/items", params={"hidden": True}).json()["items"]] \
        == [victim]
