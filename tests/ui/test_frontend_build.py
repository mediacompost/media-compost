"""A tab left open across an update, and what the server does about it.

Two halves. The server names its build on every API reply, so a page learns it
has been superseded from the first response it gets — that is the half that
does the work. And it refuses a WRITE from a mismatched build, which is the
backstop for the write that races that discovery: a field that still exists but
has changed meaning would otherwise be accepted, validated and stored as
something else, the one failure `extra="forbid"` cannot see.

Reads stay allowed on purpose. A stale tab goes on rendering rather than
turning into a wall of errors, which is also what gives the banner something to
be a banner over.

Everything fails OPEN. The check exists to stop one confusing request; it must
never be the reason a working library cannot be written to.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import build as build_info
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

OURS = "index-SERVERBUILD.js"


@pytest.fixture
def client(tmp_path: Path, images: Path, monkeypatch):
    # Pin the server's build so the test does not depend on the checked-in
    # bundle's hash, which changes on every frontend build.
    monkeypatch.setattr(build_info, "build_id", lambda _p: OURS)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([images], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _item(client) -> int:
    return client.get("/api/items").json()["items"][0]["id"]


# ---- reading the build out of the built page -------------------------------


def test_the_build_is_the_entry_bundle_index_html_names(tmp_path: Path):
    (tmp_path / "index.html").write_text(
        '<!DOCTYPE html><html><head>'
        '<script type="module" crossorigin src="/assets/index-BGxEQlGY.js">'
        '</script></head><body></body></html>')
    assert build_info.read_build_id(tmp_path) == "index-BGxEQlGY.js"


def test_a_hash_containing_a_hyphen_survives(tmp_path: Path):
    """Vite really does emit these (`index-B-wWBlGs.js`), and a character class
    stops at the second hyphen."""
    (tmp_path / "index.html").write_text(
        '<script type="module" src="/assets/index-B-wWBlGs.js"></script>')
    assert build_info.read_build_id(tmp_path) == "index-B-wWBlGs.js"


@pytest.mark.parametrize("html", [
    "",                                            # nothing there
    "<html><body>no script at all</body></html>",  # a page with no bundle
    '<script src="/assets/vendor-abc.js"></script>',  # not the entry
])
def test_an_unreadable_page_names_no_build(tmp_path: Path, html: str):
    (tmp_path / "index.html").write_text(html)
    assert build_info.read_build_id(tmp_path) == ""


def test_a_missing_web_dist_names_no_build(tmp_path: Path):
    assert build_info.read_build_id(tmp_path / "nope") == ""


# ---- the rule --------------------------------------------------------------


@pytest.mark.parametrize("theirs,ours,stale", [
    ("index-A.js", "index-B.js", True),    # a tab from before the update
    ("index-A.js", "index-A.js", False),   # the current page
    ("", "index-A.js", False),             # the CLI, a script, curl
    ("index-A.js", "", False),             # a server with no bundle to serve
    ("", "", False),
])
def test_only_two_present_and_different_builds_are_stale(theirs, ours, stale):
    assert build_info.is_stale(theirs, ours) is stale


# ---- what the server does --------------------------------------------------


def test_every_api_reply_names_the_build(client):
    for path in ("/api/health", "/api/items", "/api/tags"):
        assert client.get(path).headers[build_info.HEADER] == OURS


def test_a_stale_page_can_still_read(client):
    """It goes on rendering instead of becoming a wall of errors — and that is
    what the banner needs in order to be a banner over something."""
    got = client.get("/api/items", headers={build_info.HEADER: "index-OLD.js"})
    assert got.status_code == 200
    # …and the reply still tells it what the current build is.
    assert got.headers[build_info.HEADER] == OURS


def test_every_read_only_post_is_named_and_really_is_a_read(client):
    """The allowlist is default-DENY, so a read-only POST left out of it is
    refused for a stale page — and the feature it serves silently never
    happens. That has cost three of them now: the search, the grid's section
    runs, and the job editor's query preview (which 409'd on the first live
    run, exactly as this comment predicts).

    So: every entry names a route that EXISTS, and every one of them answers a
    stale page rather than refusing it.
    """
    checked = 0
    for path in build_info.READ_ONLY_POSTS:
        got = client.post(path, json={},
                          headers={build_info.HEADER: "index-OLD.js"})
        # 404 is "this install does not mount it" — training is optional, and
        # whether the path EXISTS is the test above. Anything else means the
        # route answered, and what it must not answer is 409.
        if got.status_code == 404:
            continue
        assert got.status_code != 409, (
            f"{path} is in READ_ONLY_POSTS and still refused a stale page")
        checked += 1
    assert checked, "no exempt path answered — the check proved nothing"


def test_a_stale_page_cannot_write(client):
    item = _item(client)
    got = client.post(f"/api/tags/assign/item/{item}",
                      json={"tag": "from_a_stale_tab", "negative": False},
                      headers={build_info.HEADER: "index-OLD.js"})
    assert got.status_code == 409
    assert "Reload" in got.json()["detail"]
    # The refusal names the current build too, so the page that just failed
    # learns why from the same response.
    assert got.headers[build_info.HEADER] == OURS
    # Nothing was written.
    names = {t["name"] for t in client.get(f"/api/items/{item}").json()["tags"]}
    assert "from_a_stale_tab" not in names


def test_the_current_page_writes_normally(client):
    item = _item(client)
    got = client.post(f"/api/tags/assign/item/{item}",
                      json={"tag": "from_the_current_page", "negative": False},
                      headers={build_info.HEADER: OURS})
    assert got.status_code == 200


def test_a_caller_sending_no_build_is_never_refused(client):
    """The CLI, a script and `curl` have no bundle to be stale. So does the
    frontend under the Vite dev server, where there is no hash to send and a
    refused write on every rebuild would be intolerable."""
    item = _item(client)
    got = client.post(f"/api/tags/assign/item/{item}",
                      json={"tag": "from_a_script", "negative": False})
    assert got.status_code == 200


@pytest.mark.parametrize("method,path,body", [
    ("PATCH", "/api/items/{item}", {"name": "renamed"}),
    ("POST", "/api/items/hide", {"item_ids": [0], "hidden": True}),
    ("POST", "/api/groups", {"name": "g"}),
])
def test_every_mutating_verb_is_covered(client, method, path, body):
    item = _item(client)
    body = {k: ([item] if v == [0] else v) for k, v in body.items()}
    got = client.request(method, path.format(item=item), json=body,
                         headers={build_info.HEADER: "index-OLD.js"})
    assert got.status_code == 409


def test_a_server_that_cannot_name_its_build_enforces_nothing(
    client, monkeypatch,
):
    """FAIL OPEN. A source checkout with no `_web_dist`, or a packaging quirk,
    must not lock a working library out of every write it has."""
    monkeypatch.setattr(build_info, "build_id", lambda _p: "")
    item = _item(client)
    got = client.post(f"/api/tags/assign/item/{item}",
                      json={"tag": "still_fine", "negative": False},
                      headers={build_info.HEADER: "index-ANYTHING.js"})
    assert got.status_code == 200
    # And with nothing to say, it says nothing rather than an empty header.
    assert build_info.HEADER not in client.get("/api/items").headers


def test_the_check_is_scoped_to_the_api(client):
    """The page itself must always load — it is how you get the new build."""
    got = client.get("/", headers={build_info.HEADER: "index-OLD.js"})
    assert got.status_code == 200


# ---- what a stale page may still do ----------------------------------------


def test_a_stale_page_can_still_SEARCH(client):
    """The one that live testing caught and no unit test would have: this app's
    search is a POST — the condition tree is a body — so "reads are allowed"
    cannot mean "GETs are allowed". Blocking it left the grid stuck on
    "Loading…" behind the banner telling you to reload."""
    got = client.post("/api/items/query",
                      json={"query": {"type": "group", "op": "and",
                                      "neg": False, "children": []}},
                      headers={build_info.HEADER: "index-OLD.js"})
    assert got.status_code == 200
    assert got.json()["items"]


def test_a_stale_page_can_still_read_item_details(client):
    item = _item(client)
    got = client.post("/api/items/details", json={"item_ids": [item]},
                      headers={build_info.HEADER: "index-OLD.js"})
    assert got.status_code == 200


def test_a_stale_page_can_still_parse_a_query(client):
    got = client.post("/api/query/parse", json={"q": "portrait"},
                      headers={build_info.HEADER: "index-OLD.js"})
    assert got.status_code == 200


def test_a_stale_page_can_still_ask_for_the_grids_sections(client):
    """The grid asks for its section runs with a POST — the body is the same
    condition tree the search sends — so default-deny refuses it unless it is
    named. It was not, and the symptom was the exact one `/api/items/query`
    already cost once: the grid stuck with no sections behind a banner telling
    you to reload, found only by running it."""
    got = client.post("/api/items/groups",
                      json={"sort": "taken_asc", "group_by": "year"},
                      headers={build_info.HEADER: "index-OLD.js"})
    assert got.status_code != 409


def test_every_exempt_path_still_exists(client):
    """A rename must re-arm the block LOUDLY. An exemption naming a path that
    is gone is silently useless — the endpoint it meant to spare is refused
    again, and the list still reads as though it were handled."""
    from fastapi.routing import APIRoute

    from media_compost.train.web import routes as train_routes
    from media_compost.ui.server.routers import (
        faces, items, query as query_router, stats, taggrid,
        tags as tags_router, tagsort,
    )

    # The trainer's routes count even though they are MOUNTED conditionally
    # (`_mount_training`): an exemption is about a path's meaning, not about
    # whether this particular install serves it. The module always imports —
    # everything ships in one wheel — so its routes can always be read.
    live = {r.path for m in (faces, items, query_router, stats, train_routes,
                             taggrid, tags_router, tagsort)
            for r in m.router.routes
            if isinstance(r, APIRoute) and "POST" in r.methods}
    missing = build_info.READ_ONLY_POSTS - live
    assert not missing, f"exempted paths that no longer exist: {sorted(missing)}"


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/import/paths"),        # writes items
    ("POST", "/api/ml/jobs"),             # starts work
    ("PUT", "/api/settings"),             # changes the library's own settings
    ("POST", "/api/history/revert"),      # undoes things
])
def test_a_write_without_a_ctx_is_still_a_write(client, method, path):
    """Default-DENY is what makes the exemption list safe. Plenty of mutating
    routes take no `Ctx` — training, jobs, settings, import — so "no Ctx" is
    not a read, and only the paths named in `READ_ONLY_POSTS` are spared."""
    got = client.request(method, path, json={},
                         headers={build_info.HEADER: "index-OLD.js"})
    assert got.status_code == 409


# ---------------------------------------------------------------------------
# WHICH UPDATE IS THIS — and can a reload finish it?
#
# The banner used to say "reload" for both, and for one of them that is the
# one action that cannot work: a package update replaces the files under a
# running process, so the tab comes back new and the server is still old.
# These pin the server's half of telling them apart.


def _disk(monkeypatch, name: str) -> None:
    """What `index.html` would hand a browser RIGHT NOW."""
    monkeypatch.setattr(build_info, "disk_build_id", lambda _p: name)


def test_a_reload_is_enough_while_the_files_match_the_process(client, monkeypatch):
    _disk(monkeypatch, OURS)
    body = client.get("/api/build").json()
    assert body["build"] == body["disk"] == OURS
    assert body["restart_required"] is False


def test_files_newer_than_the_process_need_a_restart(client, monkeypatch):
    _disk(monkeypatch, "index-NEWERONDISK.js")
    body = client.get("/api/build").json()
    assert body["restart_required"] is True
    assert body["disk"] == "index-NEWERONDISK.js"


def test_no_bundle_on_disk_asks_nobody_to_restart(client, monkeypatch):
    # Fails CLOSED on "no answer": a dev server, a source checkout and an
    # unreadable file all read "" and none of them is evidence of an update.
    _disk(monkeypatch, "")
    assert client.get("/api/build").json()["restart_required"] is False


def test_the_restart_is_refused_while_there_is_nothing_to_restart_for(
        client, monkeypatch):
    _disk(monkeypatch, OURS)
    r = client.post("/api/restart")
    assert r.status_code == 409
    assert "already running" in r.json()["detail"]


def test_the_restart_reports_what_it_would_interrupt(client, monkeypatch):
    """A re-exec takes running jobs and imports with it, so it says so and
    waits for `force`. Training is deliberately not counted — a run is its own
    process and the manager adopts it again on the way back up."""
    _disk(monkeypatch, "index-NEWERONDISK.js")
    monkeypatch.setattr("media_compost.ui.server.app._restart_would_interrupt",
                        lambda: {"jobs": 2, "imports": 0})
    r = client.post("/api/restart")
    assert r.status_code == 409
    assert r.json()["detail"]["busy"] == {"jobs": 2, "imports": 0}

    started: list[bool] = []
    monkeypatch.setattr("media_compost.hub.setup.restart_process",
                        lambda: started.append(True))
    assert client.post("/api/restart?force=true").json() == {"restarting": True}


def test_the_restart_is_the_one_write_a_stale_page_may_make(client, monkeypatch):
    """It is how the page stops being stale: after a package update no reload
    can help, so the button has to reach the server it is asking to restart."""
    _disk(monkeypatch, "index-NEWERONDISK.js")
    monkeypatch.setattr("media_compost.hub.setup.restart_process", lambda: None)
    r = client.post("/api/restart", headers={build_info.HEADER: "index-OLDPAGE.js"})
    assert r.status_code == 200
    # ... and it is the ONLY one: an ordinary write from the same page is not.
    assert client.post("/api/groups", json={"name": "x"},
                       headers={build_info.HEADER: "index-OLDPAGE.js"}
                       ).status_code == 409


# ---- the SPA catch-all is a bundle server, not a file server ---------------
#
# `GET /<anything>` falls through to the built page so a deep link reloads,
# and the handler joins that path onto `_web_dist` to see whether it names a
# real asset first. The path is UNTRUSTED, and the join is not a suffix: it
# served `/etc/passwd` to anyone who could reach the port, by two separate
# routes (`..` segments, and an absolute path replacing the left operand).
# Percent-encoding arrives decoded, so these are driven as raw ASGI scopes —
# an HTTP client normalises the URL away before the server ever sees it, which
# is exactly why the hole survived every test written through one.

def _web_dist_present() -> bool:
    """The catch-all route only exists when a bundle was built beside the
    package — a fresh clone has none, and `test_packaging` skips for the same
    reason."""
    from media_compost.ui.server.app import _FRONTEND

    return (_FRONTEND / "index.html").is_file()


def _raw_get(path: str) -> tuple[int, bytes]:
    """One GET through the real ASGI app, with `path` passed through verbatim."""
    import asyncio
    import urllib.parse

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "server": ("127.0.0.1", 80), "client": ("1.2.3.4", 9999),
        "root_path": "", "query_string": b"", "headers": [],
        "path": urllib.parse.unquote(path), "raw_path": path.encode(),
    }
    status: list[int] = []
    body: list[bytes] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            status.append(msg["status"])
        elif msg["type"] == "http.response.body":
            body.append(msg.get("body", b""))

    asyncio.run(app(scope, receive, send))
    return status[0], b"".join(body)


@pytest.mark.skipif(not _web_dist_present(), reason="no built bundle to serve")
@pytest.mark.parametrize("path", [
    "/../../../../../../../../../etc/passwd",          # plain dot-dot
    "/..%2f..%2f..%2f..%2f..%2f..%2f..%2f..%2f..%2fetc/passwd",  # encoded
    "/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd",
    "//etc/passwd",          # absolute right operand: pathlib drops the left
    "/assets/../../../../../../../../../etc/passwd",
])
def test_a_path_outside_the_bundle_is_never_served(path: str):
    status, body = _raw_get(path)
    assert b"root:" not in body, f"{path} escaped the bundle"
    # It is not an error — an unknown path is a deep link, and the SPA is the
    # answer to those. What must not happen is the file coming back.
    assert status in (200, 404)
    if status == 200:
        assert b"<!DOCTYPE html>" in body or b"<!doctype html>" in body


@pytest.mark.skipif(not _web_dist_present(), reason="no built bundle to serve")
def test_a_real_asset_inside_the_bundle_is_still_served():
    """The guard must not be a refusal of everything: the whole point of the
    branch is that a genuine file under `_web_dist` comes back as itself."""
    status, body = _raw_get("/index.html")
    assert status == 200
    assert b"<!DOCTYPE html>" in body or b"<!doctype html>" in body
