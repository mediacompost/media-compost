"""Tag names and the namespace a colon reads out of one.

Mirrored by `frontend/src/tags.test.ts` — the two sides must agree on every
shape a field can emit, or the UI produces names the API refuses.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost import tagname
from media_compost.ui.config import UiConfig
from media_compost.importer import ImportOptions, Importer
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


@pytest.mark.parametrize("raw,want", [
    ("plain", "plain"),
    ("white shirt", "white_shirt"),
    ("  spaced  out ", "spaced_out"),
    ("costume:tiger", "costume:tiger"),
    # INTERIOR colons are kept, however many. Turning them into underscores
    # did not stop anybody thinking in hierarchies — it only stopped them
    # writing one down, and stored something else without saying so.
    ("a:b:c", "a:b:c"),
    ("a:b:c:d", "a:b:c:d"),
    ("costume:hat:straw", "costume:hat:straw"),
    ("a::b", "a::b"),
    # A leading colon is KEPT: `:o`, `:d`, `:3` are the booru tag set's
    # most-used expression tags. Such a name has no namespace.
    (":foo", ":foo"),
    ("::foo", "::foo"),
    (":o", ":o"),
    (":::a:b", ":::a:b"),
    # A TRAILING colon is kept too — Danbooru spells three of its expression
    # tags `d:`, `3:` and `c:`, and eating the colon turned each into a bare
    # letter the app had decided it meant.
    ("costume:", "costume:"),
    ("costume::", "costume::"),
    ("a:b:", "a:b:"),
    ("::", "::"),
    (":", ":"),
    ("d:", "d:"),
    ("3:", "3:"),
    ("c:", "c:"),
    # Whitespace is stripped at the ends and collapsed in the middle; the
    # colon it leaves behind is part of the name.
    ("costume: ", "costume:"),
])
def test_normalize(raw, want):
    assert tagname.normalize(raw) == want


def test_normalize_is_idempotent():
    """What the API refuses is anything `normalize` would change, so a name it
    has already produced must survive a second pass untouched."""
    for raw in ["costume:", ":x", "a:b:c", " a b ", "x", "a:", "::", "a::b",
                "costume:hat:straw", ":a:b:", "a:b:c:d:e"]:
        once = tagname.normalize(raw)
        assert tagname.normalize(once) == once
        assert tagname.is_normalized(once)


def test_reading_a_namespace_is_total():
    """A library restored from a sidecar written before these rules can hold
    anything, so reading never raises and never returns something surprising."""
    assert tagname.namespace("costume:tiger") == "costume"
    assert tagname.basename("costume:tiger") == "tiger"
    assert tagname.namespace("plain") == ""
    assert tagname.basename("plain") == "plain"
    # An old `a:b:c` simply reads as namespace `a`.
    assert tagname.namespace("a:b:c") == "a"
    assert tagname.basename("a:b:c") == "b:c"
    # A leading colon names no namespace — the emoticon tags are plain names.
    assert tagname.namespace(":foo") == ""
    assert tagname.basename(":foo") == ":foo"
    assert tagname.namespace(":o") == "" and tagname.basename(":o") == ":o"


def test_case_is_kept_so_two_spellings_stay_two_namespaces():
    # Folding them together would be this module deciding something the names
    # do not say.
    assert tagname.namespace("Costume:a") == "Costume"
    assert tagname.namespace("costume:b") == "costume"


def test_the_api_refuses_a_name_it_would_have_changed(client):
    """Refused rather than quietly stored: the field normalizes as you type, so
    a malformed name reaching the API came from a script, and storing something
    else is how a caller ends up with a tag it cannot find again."""
    assert client.post("/api/tags", json={"name": "costume:tiger"}).status_code == 200
    # …and a name with SEVERAL colons is one of the accepted shapes now.
    assert client.post("/api/tags",
                       json={"name": "costume:hat:straw"}).status_code == 200
    # A colon at EITHER end is a name, not a refusal: `:o` and `d:` are both
    # spellings the booru tag set uses, and the app does not get to decide
    # that one of them meant something shorter.
    assert client.post("/api/tags", json={"name": ":leading"}).status_code == 200
    assert client.post("/api/tags", json={"name": ":o"}).status_code == 200
    for good in ["trailing:", "both:ends:", "a:b:c:", "d:", "3:", "c:", ":"]:
        r = client.post("/api/tags", json={"name": good})
        assert r.status_code == 200, (good, r.text)
        assert r.json()["name"] == good
    # What is left to refuse is WHITESPACE. A space has its own, more specific
    # refusal (`check_name`); any other kind is named by the shape message.
    assert client.post("/api/tags", json={"name": "white shirt"}).status_code == 400
    for bad in ["tab\tinside", "line\nbreak", "nb\u00a0space"]:
        r = client.post("/api/tags", json={"name": bad})
        assert r.status_code == 400, bad
        # The message says what to type instead.
        assert tagname.normalize(bad) in r.json()["detail"]


def test_the_app_cannot_mint_a_name_its_own_rules_refuse(client):
    """Subject / place / event tags are namespaced by exactly this convention,
    and `slugify` strips punctuation — so the prefix's colon is always the only
    one, whatever somebody calls a person."""
    r = client.post("/api/subjects", json={"display_name": "Anna: the Second"})
    assert r.status_code == 200
    tag = r.json()[0]["tag"]
    assert tag == "subject:anna_the_second"
    assert tagname.is_normalized(tag)
    assert tagname.namespace(tag) == "subject"
