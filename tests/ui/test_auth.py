"""Multi-user identity: username resolution, require-auth gating, history
attribution, and per-user isolation of saved searches + UI prefs.

Authentication is done by an upstream layer; the app only reads the caller's
identity (from an ``Authorization: Basic`` header or a configured trusted
header) and attributes/scopes accordingly. Anonymous access is allowed unless
``require_auth`` is on.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.auth import resolve_username
from media_compost.ui.server.deps import Library, get_library


def _basic(user: str, pw: str = "x") -> dict[str, str]:
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _fake_request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw})


# ---- resolve_username (unit) ------------------------------------------------

def test_resolve_from_basic_auth():
    cfg = UiConfig(data_dir=Path("/tmp/unused"))
    assert resolve_username(_fake_request(_basic("alice")), cfg) == "alice"


def test_resolve_anonymous_when_no_header():
    cfg = UiConfig(data_dir=Path("/tmp/unused"))
    assert resolve_username(_fake_request({}), cfg) == ""


def test_resolve_ignores_malformed_basic():
    cfg = UiConfig(data_dir=Path("/tmp/unused"))
    # Not base64, and a token without a colon, both yield anonymous.
    assert resolve_username(_fake_request({"Authorization": "Basic !!!"}), cfg) == ""
    nocolon = base64.b64encode(b"alice").decode()
    assert resolve_username(
        _fake_request({"Authorization": f"Basic {nocolon}"}), cfg
    ) == ""


def test_trusted_header_wins_over_basic():
    cfg = UiConfig(data_dir=Path("/tmp/unused"), user_header="X-Remote-User")
    req = _fake_request({**_basic("alice"), "X-Remote-User": "bob"})
    assert resolve_username(req, cfg) == "bob"
    # Falls back to Basic when the trusted header is absent.
    assert resolve_username(_fake_request(_basic("alice")), cfg) == "alice"


# ---- require_auth gating (integration) --------------------------------------

def _make_client(tmp_path: Path, **cfg_kw) -> TestClient:
    lib = Library(UiConfig(data_dir=tmp_path / "data", **cfg_kw))
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    return TestClient(app)


@pytest.fixture
def anon_client(tmp_path: Path):
    with _make_client(tmp_path) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(tmp_path: Path):
    with _make_client(tmp_path, require_auth=True) as c:
        yield c
    app.dependency_overrides.clear()


def test_anonymous_allowed_by_default(anon_client):
    r = anon_client.get("/api/whoami")
    assert r.status_code == 200
    assert r.json() == {"username": "", "require_auth": False}


def test_require_auth_rejects_anonymous(auth_client):
    r = auth_client.get("/api/whoami")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Basic"


def test_require_auth_allows_identified(auth_client):
    r = auth_client.get("/api/whoami", headers=_basic("alice"))
    assert r.status_code == 200
    assert r.json() == {"username": "alice", "require_auth": True}


# ---- history attribution ----------------------------------------------------

def test_history_records_username(anon_client):
    # Create a tag as alice; the event is attributed to her.
    anon_client.post("/api/tags", json={"name": "sunset"}, headers=_basic("alice"))
    ev = next(e for e in anon_client.get("/api/history").json()["events"]
              if e["action"] == "create_tag")
    assert ev["username"] == "alice"


def test_history_username_blank_when_anonymous(anon_client):
    anon_client.post("/api/tags", json={"name": "beach"})
    ev = next(e for e in anon_client.get("/api/history").json()["events"]
              if e["action"] == "create_tag")
    assert ev["username"] == ""


# ---- per-user isolation: saved searches -------------------------------------

def test_saved_searches_isolated_per_user(anon_client):
    anon_client.put("/api/settings/saved-searches",
                    json=[{"name": "A", "query": "cat"}], headers=_basic("alice"))
    anon_client.put("/api/settings/saved-searches",
                    json=[{"name": "B", "query": "dog"}], headers=_basic("bob"))
    alice = anon_client.get("/api/settings/saved-searches", headers=_basic("alice")).json()
    bob = anon_client.get("/api/settings/saved-searches", headers=_basic("bob")).json()
    assert alice == [{"name": "A", "query": "cat"}]
    assert bob == [{"name": "B", "query": "dog"}]
    # Anonymous has its own (empty) list — no leakage from named users.
    assert anon_client.get("/api/settings/saved-searches").json() == []


def test_legacy_saved_searches_visible_to_anonymous(anon_client):
    # Pre-multi-user data lives under the un-suffixed key; anonymous still sees it.
    anon_client.put("/api/settings/saved-searches",
                    json=[{"name": "Legacy", "query": "old"}])
    assert anon_client.get("/api/settings/saved-searches").json() == [
        {"name": "Legacy", "query": "old"}
    ]


# ---- per-user isolation: UI prefs -------------------------------------------

# (There is no ALTER-based migration mechanism anymore — schema changes mean a
# fresh library, so the old username-column migration test was removed.)


def test_prefs_isolated_per_user_florence_stays_global(anon_client):
    # Alice picks German + a Florence checkpoint; Bob is unaffected on language,
    # but the Florence checkpoint is a shared/global setting.
    base = anon_client.get("/api/settings", headers=_basic("alice")).json()
    body = {**base, "language": "de", "florence_model": "florence2_large"}
    anon_client.put("/api/settings", json=body, headers=_basic("alice"))

    alice = anon_client.get("/api/settings", headers=_basic("alice")).json()
    bob = anon_client.get("/api/settings", headers=_basic("bob")).json()
    assert alice["language"] == "de"
    assert bob["language"] == "en"                       # personal → unchanged
    assert bob["florence_model"] == "florence2_large"    # global → shared
