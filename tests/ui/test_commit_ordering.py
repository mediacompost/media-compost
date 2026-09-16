"""A write must be committed BEFORE its response goes out.

``get_session`` is a dependency with ``yield``, and FastAPI exits those only
once the response has been SENT — the same fact ``files.release`` exists for.
So while the commit lived there, every write endpoint answered ``200`` with
the new row's id and committed afterwards, and a client that read straight
back could beat it. Measured on loopback against the real server: of twelve
``POST /api/groups`` calls each followed at once by ``GET /api/groups``, five
did not list the group whose id the POST had just returned, and
create-then-delete answered ``404 group not found`` for its own new group in
about a third of runs. A 50 ms sleep between the two made both vanish, which
is what says it is the ordering and not the database — a second session on a
second connection sees a committed row every time.

These do NOT go through the TestClient, which runs each request to completion
and so cannot tell the two orderings apart; that is the same reason
``test_connection_release`` calls its handlers directly. What is pinned here
is the middleware's rule and the wiring it depends on — including the SHAPE of
the middleware, which is load-bearing for something else entirely (see the
last test).
"""

from __future__ import annotations

import asyncio

from media_compost.ui.server import app as app_module


class _FakeSession:
    def __init__(self, released: bool = False) -> None:
        self.info: dict = {"released": True} if released else {}
        self.commits = 0
        #: How many response messages had gone out when the commit ran — the
        #: whole point is that the answer is zero.
        self.sent_at_commit: list[int] = []
        self._watch = None

    def commit(self) -> None:
        self.commits += 1
        self.sent_at_commit.append(len(self._watch or ()))


def _run(session, status: int = 200):
    """Drive the middleware over one HTTP scope; return the messages sent."""
    sent: list[dict] = []
    if session is not None:
        session._watch = sent

    async def inner(scope, receive, send):
        if session is not None:
            scope.setdefault("state", {})["mc_session"] = session
        await send({"type": "http.response.start", "status": status,
                    "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def send(message):
        sent.append(message)

    mw = app_module._CommitBeforeResponding(inner)
    asyncio.run(mw({"type": "http", "method": "GET", "path": "/api/x",
                    "headers": []}, None, send))
    return sent


def test_a_successful_request_is_committed_before_it_answers():
    s = _FakeSession()
    sent = _run(s, 200)
    assert s.commits == 1
    # Nothing had been sent when the commit ran.
    assert s.sent_at_commit == [0]
    assert sent[0]["status"] == 200


def test_an_error_response_is_not_committed():
    """A handler that raised was already rolled back by the dependency, and an
    `OpError` mapped to 4xx must not commit whatever it wrote first."""
    for status in (400, 404, 409, 422, 500):
        s = _FakeSession()
        _run(s, status)
        assert s.commits == 0, f"committed a {status}"


def test_a_released_session_is_left_alone():
    """`files.release` hands the pool connection back before the bytes go out;
    committing would check one out again to write nothing."""
    s = _FakeSession(released=True)
    _run(s, 200)
    assert s.commits == 0


def test_a_request_with_no_session_is_fine():
    """Static files and the SPA fallback never open one."""
    sent = _run(None, 200)
    assert sent[0]["status"] == 200


def test_a_websocket_scope_passes_straight_through():
    """Only HTTP has a response to commit before."""
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    mw = app_module._CommitBeforeResponding(inner)
    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


def test_the_middleware_is_actually_registered():
    """The rule above is worth nothing if the middleware is not in the stack —
    and a middleware is easy to drop in a merge without a test noticing."""
    names = [getattr(m.cls, "__name__", "") for m in app_module.app.user_middleware]
    assert "_CommitBeforeResponding" in names, names


def test_get_session_stashes_the_session_where_the_middleware_looks():
    """The middleware finds the session on ``request.state.mc_session``; if the
    dependency stops putting it there, every commit silently moves back to
    after the response and nothing else fails."""
    import inspect

    from media_compost.ui.server.deps import get_session

    src = inspect.getsource(get_session)
    assert "request.state.mc_session" in src
    assert "request" in inspect.signature(get_session).parameters


def test_no_middleware_here_is_a_BaseHTTPMiddleware():
    """ONE of those anywhere in the stack blinds the whole application.

    `BaseHTTPMiddleware` — which is what ``@app.middleware("http")`` builds —
    proxies the request's receive channel through a stream of its own, and a
    proxied channel never delivers ``http.disconnect`` downstream. No endpoint
    below one can tell that its caller has hung up, and `server/dbgate.py`
    needs exactly that: measured on the 1M-item library, eight page queries
    the browser had already aborted left the server unusable for 652 seconds
    when it ran them anyway, and 0.65 s when it dropped them.

    Both of this app's middlewares are therefore written as plain ASGI
    classes. This is the ratchet: `@app.middleware("http")` is one line and
    reads like the obvious way to add the third.
    """
    from starlette.middleware.base import BaseHTTPMiddleware

    for m in app_module.app.user_middleware:
        assert not (isinstance(m.cls, type)
                    and issubclass(m.cls, BaseHTTPMiddleware)), m.cls
