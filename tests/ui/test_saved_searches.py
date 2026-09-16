"""Saved-search persistence in the settings key/value store."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path):
    lib = Library(UiConfig(data_dir=tmp_path / "data"))
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_saved_searches_roundtrip(client):
    assert client.get("/api/settings/saved-searches").json() == []
    payload = [
        {"name": "Training set A", "query": "portrait|landscape !blurred"},
        {"name": "High-res", "query": "meta:width>=2000 !anime"},
    ]
    r = client.put("/api/settings/saved-searches", json=payload)
    assert r.status_code == 200
    assert r.json() == payload
    # Persisted for the next request.
    assert client.get("/api/settings/saved-searches").json() == payload
    # Blank-named entries are dropped; order preserved.
    r = client.put("/api/settings/saved-searches", json=[
        {"name": "", "query": "x"},
        {"name": "Keep", "query": "y"},
    ])
    assert r.json() == [{"name": "Keep", "query": "y"}]
