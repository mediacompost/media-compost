"""An `OpError` must reach the client as the status `HTTPException` gave, and
the half-done write must not survive.

Both halves are load-bearing and neither is obvious.

The STATUS half is what makes the extraction invisible to the frontend: 208
`raise HTTPException(…)` calls across the routers become `OpError` subclasses,
and the only thing standing between that and a wall of 500s is the handler in
`server/app.py`. `HTTPException` already serialized to `{"detail": …}`, so the
wire shape is unchanged — this pins it.

The ROLLBACK half is about ordering. `get_session` is a generator dependency
that commits on the way out and rolls back in an `except`; the exception
handler runs in the middleware stack, further out. If those two ever swapped —
if the handler answered while the session's teardown had already committed —
a refused operation would leave its partial writes behind. That is a
data-corruption bug with no symptom at the call site, so it gets a test rather
than an argument.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from media_compost.ui.config import UiConfig
from media_compost.db import Tag
from media_compost.ops import Conflict, Ctx, Invalid, NotFound, OpError, Refused
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_ctx, get_library, get_session

# Routes mounted only for this module. Registering them on the REAL app is the
# point: a fresh FastAPI would test this file's wiring rather than app.py's.
_PREFIX = "/api/__opstest"


def _install_routes() -> list:
    @app.post(_PREFIX + "/raise/{kind}")
    def _raise(kind: str, s: Session = Depends(get_session)):
        """Write a row, then refuse. Both must be undone."""
        s.add(Tag(name=f"ops-test-{kind}"))
        s.flush()
        cls = {"invalid": Invalid, "refused": Refused,
               "notfound": NotFound, "conflict": Conflict}[kind]
        raise cls(f"refused: {kind}", code=f"test_{kind}")

    @app.post(_PREFIX + "/ok")
    def _ok(s: Session = Depends(get_session)):
        s.add(Tag(name="ops-test-ok"))
        return {"ok": True}

    @app.post(_PREFIX + "/ctx")
    def _ctx(ctx: Ctx = Depends(get_ctx), s: Session = Depends(get_session)):
        """The Ctx and a directly-requested Session must be the same session,
        or an op would write into a transaction the request never commits."""
        return {"same_session": ctx.session is s, "source": ctx.source,
                "username": ctx.username,
                "info_user": s.info.get("username")}

    added = app.router.routes[-3:]
    return added


@pytest.fixture
def client(tmp_path: Path):
    routes = _install_routes()
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    for r in routes:
        app.router.routes.remove(r)


def _tags(lib_client) -> int:
    lib = app.dependency_overrides[get_library]()
    with lib.db.session() as s:
        return s.execute(select(func.count(Tag.id))).scalar_one()


@pytest.mark.parametrize("kind,status", [
    ("invalid", 400), ("refused", 400), ("notfound", 404), ("conflict", 409),
])
def test_status_and_body_match_what_HTTPException_produced(client, kind, status):
    r = client.post(f"{_PREFIX}/raise/{kind}")
    assert r.status_code == status
    assert r.json() == {"detail": f"refused: {kind}"}


@pytest.mark.parametrize("kind", ["invalid", "refused", "notfound", "conflict"])
def test_a_refused_operation_leaves_nothing_behind(client, kind):
    """The row written before the raise must be rolled back, not committed by
    the session dependency's teardown."""
    assert _tags(client) == 0
    client.post(f"{_PREFIX}/raise/{kind}")
    assert _tags(client) == 0, (
        "a refused operation committed its partial write — the exception "
        "handler is answering before/instead of get_session's rollback"
    )


def test_the_happy_path_still_commits(client):
    """The mirror image: proving rollback happens is worthless if the test
    would also pass with nothing ever committing."""
    assert client.post(f"{_PREFIX}/ok").status_code == 200
    assert _tags(client) == 1


def test_get_ctx_shares_the_request_session(client):
    body = client.post(f"{_PREFIX}/ctx").json()
    assert body["same_session"] is True
    assert body["source"] == "web"


def test_op_error_carries_a_machine_readable_code():
    """Message text is for people and may be reworded; `code` is what a script
    branches on."""
    e = NotFound("no tag named “x”", code="tag_not_found")
    assert e.code == "tag_not_found"
    assert str(e) == "no tag named “x”"
    assert isinstance(e, OpError)


def test_every_subclass_declares_a_status():
    for cls in (Invalid, Refused, NotFound, Conflict):
        assert isinstance(cls.status, int) and 400 <= cls.status < 500
