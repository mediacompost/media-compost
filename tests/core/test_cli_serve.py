"""`media-compost serve`'s startup manners.

The browser opens only once THIS server answers its own health check — a
one-second timer used to open a tab onto whatever the port held, which on a
cold start (the whole backend imports before uvicorn binds) was a dead port
the browser dressed up as the stale cache of whichever app last lived there.
And a port already in use is refused up front, before any browser thread
starts, instead of opening a tab over the other application.

Stdlib only: serve's helpers deliberately import nothing from `[full]`, so the
core suite covers them on a base-only install.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from media_compost import cli


def _handler(payload: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's spelling
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # quiet
            pass

    return Handler


def _health_server(payload: dict) -> tuple[HTTPServer, str]:
    srv = HTTPServer(("127.0.0.1", 0), _handler(payload))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_browser_opens_once_our_health_answers(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    srv, url = _health_server({"ok": True, "training": False,
                               "schema_version": 4})
    try:
        cli._open_when_ready(url, threading.Event())
    finally:
        srv.shutdown()
    assert opened == [url]


def test_a_server_that_takes_its_time_still_gets_its_tab(monkeypatch):
    """A schema upgrade runs INSIDE the server's startup, and uvicorn accepts
    nothing until it is over — so the poller meets refused connections for
    as long as the backup and the rungs take. It used to give up after sixty
    seconds, which on a real library is exactly the case: `serve --open` ran
    a migration and no tab appeared. The server here binds only after the
    poller has been refused for a while; the property that it waits
    INDEFINITELY has no clock to test against, so it is pinned by reading the
    function — no deadline, no `monotonic` — beside this behavioural half."""
    import inspect
    import time

    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    srv_box: list[HTTPServer] = []

    def bind_late():
        time.sleep(1.0)   # several refused polls' worth
        srv = HTTPServer(("127.0.0.1", port),
                         _handler({"ok": True, "schema_version": 4}))
        srv_box.append(srv)
        srv.serve_forever()

    threading.Thread(target=bind_late, daemon=True).start()
    try:
        cli._open_when_ready(url, threading.Event())
    finally:
        for srv in srv_box:
            srv.shutdown()
    assert opened == [url]

    src = inspect.getsource(cli._open_when_ready)
    body = src.split('"""', 2)[2]          # past the docstring
    assert "monotonic" not in body and "deadline" not in body, \
        "the poller grew a deadline back"


def test_a_stranger_on_the_port_gets_no_tab(monkeypatch):
    """An answering server that is NOT this app — the taken-port case the
    old timer opened a tab over — is left alone."""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    srv, url = _health_server({"projects": []})
    try:
        cli._open_when_ready(url, threading.Event())
    finally:
        srv.shutdown()
    assert opened == []


def test_no_tab_once_the_server_has_already_exited(monkeypatch):
    """serve sets the stop event the moment uvicorn returns — a startup that
    died must not keep polling toward a browser tab."""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    stop = threading.Event()
    stop.set()
    cli._open_when_ready("http://127.0.0.1:9", stop)   # 9: nothing listens
    assert opened == []


def test_port_probe_sees_a_taken_port():
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert cli._port_free("127.0.0.1", port) is False
    assert cli._port_free("127.0.0.1", port) is True


def test_a_base_install_is_told_the_install_line_IT_CAN_RUN(capsys,
                                                            monkeypatch):
    """The refusal is printed through rich, which reads `[full]` as a STYLE.

    `media-compost serve` exists on a base-only install (entry points come
    with the distribution whatever the extras), and the right answer there is
    the install line. It was written as an ordinary string, so rich ate the
    extra and printed `pip install 'media-compost'` — the command that
    installs what the person already has, and the one CI greps for. This
    asserts what reaches the TERMINAL, not what the source says: the source
    always did say `media-compost[full]`, which is why
    `test_ci_greps_for_the_install_line_the_cli_actually_prints` passed
    throughout.

    `None` in `sys.modules` is how an import is made to fail: the import
    system raises ImportError on it, which is the state of a base install.
    """
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    with pytest.raises(SystemExit) as exc:
        cli._cmd_serve(argparse.Namespace())   # refused before an arg is read
    assert exc.value.code != 0
    assert "media-compost[full]" in capsys.readouterr().out


def test_the_trainer_says_the_same_thing_the_same_way(capsys, monkeypatch):
    """`media-compost-train` refuses without `[train]` for the same reason,
    through a console of its own — so it is the same bug in a second place."""
    from media_compost.train import cli as tcli

    monkeypatch.setattr(tcli, "available", lambda: False)
    monkeypatch.setattr(tcli, "requirements", lambda: ("huggingface_hub",))
    with pytest.raises(SystemExit):
        tcli._trainer(None)
    assert "media-compost[train]" in capsys.readouterr().out
