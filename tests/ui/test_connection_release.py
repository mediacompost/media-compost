"""A file handler must not hold a database connection while it streams.

A dependency with ``yield`` is exited only once the response has been SENT, so
a ``Session`` opened for one of the byte-serving routes stays open — holding
one of the engine pool's connections — for the whole transfer. For a thumbnail
that is milliseconds; for a film it is the whole download, and a ``<video>``
being scrubbed abandons partial requests faster than they finish. The pool is 5
connections plus 10 overflow, so a couple of dozen seeks exhaust it and every
later request blocks for the 30 s pool timeout and then fails: the picture
stops updating and the whole server appears to freeze, which is exactly how it
was reported from the video editor.

These call the handlers DIRECTLY rather than through the TestClient, because
the client runs a request to completion — the very thing that hides the bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.requests import Request

from media_compost.db import File, Item
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.config import UiConfig
from media_compost.ui.server.deps import Library
from media_compost.ui.server.routers import files as files_router


def _request() -> Request:
    """The bare minimum a handler reads off one: its headers."""
    return Request({"type": "http", "method": "GET", "headers": []})


@pytest.fixture
def seeded(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([images], ImportOptions())
    return lib


def _a_file_id(lib: Library) -> int:
    with lib.db.session() as s:
        item = s.query(Item).first()
        assert item is not None
        f = s.query(File).filter(File.item_id == item.id).first()
        assert f is not None
        return f.id


@pytest.mark.parametrize("handler", ["get_file", "get_thumb"])
def test_a_byte_handler_lets_its_connection_go_before_it_answers(
    seeded: Library, handler: str
):
    lib = seeded
    file_id = _a_file_id(lib)
    pool = lib.db.engine.pool
    assert pool.checkedout() == 0, "the fixture left one out"

    s = lib.db.session()
    try:
        resp = getattr(files_router, handler)(
            file_id, request=_request(), s=s, lib=lib)
        assert resp.status_code == 200
        # The response is built but NOT yet sent — which is where a scrubbed
        # video spends its time.
        assert pool.checkedout() == 0, (
            f"{handler} still holds a connection while its bytes go out")
    finally:
        s.close()
