"""The library's own set: its categories, and the tags filed in them.

Two organisations sit over one list of names and they are deliberately not
the same thing. A CATEGORY is authored — somebody drags a row into it, it
survives a rename, it nests, it has an icon — and lives as an ordinary
`TagSetCategory` row belonging to the library's own set, so the tree the
Tags tab draws for an imported tag set draws for the library too. A
NAMESPACE is derived — the text before the first colon, no row, no column —
and answers whatever anybody files.

What this file holds: that the library's set is LAZY (no row until something
needs one) and reserved, that the counts come off the right table, that both
narrowings work and compose, and that filing undoes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from media_compost.ops import tagsets as ops
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    deps.reset_library()


def _tag(c: TestClient, name: str) -> int:
    return c.post("/api/tags", json={"name": name}).json()["id"]


def _item(c: TestClient) -> int:
    """One image, for a count to be about."""
    from sqlalchemy import insert, select

    from media_compost.db import Item
    with c.lib.db.session() as s:
        s.execute(insert(Item), [{"uid": "cat1", "name": "i1", "kind": "image"}])
        s.commit()
        return s.execute(select(Item.id)).scalars().first()


def _names(c: TestClient, **params) -> list[str]:
    return c.get("/api/tags/index", params=params).json()["names"]


def test_the_librarys_set_does_not_exist_until_something_needs_it(client):
    """A library that never files a tag never grows the ROW — but the pill is
    always drawn: the library is always there, so it is synthesized at id 0
    until something brings the row into being."""
    rows = client.get("/api/tag-sets").json()
    assert [(r["id"], r["key"], r["library"]) for r in rows] \
        == [(0, "library", True)]
    with client.lib.db.session() as s:
        assert ops.library_set(s) is None

    client.post("/api/tags/categories", json={"name": "Animals"})

    rows = client.get("/api/tag-sets").json()
    assert [r["library"] for r in rows] == [True]
    assert rows[0]["name"] == "Library"
    assert rows[0]["id"] > 0


def test_the_librarys_pill_leads_and_counts_tags_not_entries(client):
    """Its `entries` is the tag catalog — the library holds no entry rows at
    all — and it sits first however the imported sets are ordered."""
    _tag(client, "dog")
    _tag(client, "cat")
    client.post("/api/tags/categories", json={"name": "Animals"})
    client.post("/api/tag-sets", json={"name": "Booru mini"})

    rows = client.get("/api/tag-sets").json()
    assert [r["library"] for r in rows] == [True, False]
    assert rows[0]["entries"] == 2
    assert rows[0]["categories"] == 1


def test_the_library_key_is_reserved_even_before_the_row_exists(client):
    """It is lazy, so "nothing has it" is not "it is free" — an imported set
    called Library must not take the key the library will want."""
    made = client.post("/api/tag-sets", json={"name": "Library set"}).json()
    assert made["key"] != ops.LIBRARY_KEY

    # And the NAME is refused outright once the row is there, since two pills
    # reading "Library" is two things nobody can tell apart.
    client.post("/api/tags/categories", json={"name": "Animals"})
    assert client.post("/api/tag-sets", json={"name": "Library"}).status_code == 409


def test_a_category_counts_the_tags_filed_in_it_and_under_it(client):
    dog, puppy, car = (_tag(client, n) for n in ("dog", "puppy", "car"))
    top = client.post("/api/tags/categories", json={"name": "Animals"}).json()
    sub = client.post("/api/tags/categories",
                      json={"name": "Dogs", "parent_id": top["id"]}).json()
    client.post("/api/tags/category",
                json={"tag_ids": [dog], "category_id": top["id"]})
    client.post("/api/tags/category",
                json={"tag_ids": [puppy], "category_id": sub["id"]})

    detail = client.get(f"/api/tag-sets/{top['set_id']}").json()
    by_id = {c["id"]: c for c in detail["category_rows"]}
    # The subtree rolls up, exactly as an imported set's tree does.
    assert by_id[top["id"]]["count"] == 2
    assert by_id[sub["id"]]["count"] == 1
    assert detail["uncategorized"] == 1
    assert car not in (dog, puppy)


def test_the_index_narrows_by_category_taking_the_subtree(client):
    dog, puppy, car = (_tag(client, n) for n in ("dog", "puppy", "car"))
    top = client.post("/api/tags/categories", json={"name": "Animals"}).json()
    sub = client.post("/api/tags/categories",
                      json={"name": "Dogs", "parent_id": top["id"]}).json()
    client.post("/api/tags/category",
                json={"tag_ids": [dog], "category_id": top["id"]})
    client.post("/api/tags/category",
                json={"tag_ids": [puppy], "category_id": sub["id"]})

    assert _names(client, category=top["id"]) == ["dog", "puppy"]
    assert _names(client, category=sub["id"]) == ["puppy"]
    assert _names(client, uncategorized=True) == ["car"]
    # Several picked is the UNION, and Uncategorized joins it.
    assert _names(client, category=sub["id"], uncategorized=True) == ["car", "puppy"]


def test_the_index_narrows_by_namespace_which_no_row_carries(client):
    for n in ("artist:kantoku", "artist:mika", "character:miku", "red_skirt"):
        _tag(client, n)

    assert _names(client, namespace="artist") == ["artist:kantoku", "artist:mika"]
    # Written with or without the colon — the setting stores it without one
    # and a person types it with, and neither should be a different question.
    assert _names(client, namespace="artist:") == ["artist:kantoku", "artist:mika"]
    assert _names(client, namespace="character") == ["character:miku"]


def test_the_two_axes_are_one_union(client):
    """A NAMESPACE READS AS A CATEGORY holding the names made with it (owner
    2026-09): the sidebar picks both kinds of row in one selection, so
    picking a category and a namespace lists what is in EITHER. They
    intersected until then, which meant a plain click in the lower block
    usually emptied the list."""
    a, b = _tag(client, "artist:kantoku"), _tag(client, "artist:mika")
    _tag(client, "character:miku")
    skirt = _tag(client, "red_skirt")
    cat = client.post("/api/tags/categories", json={"name": "People"}).json()
    client.post("/api/tags/category",
                json={"tag_ids": [a, skirt], "category_id": cat["id"]})

    assert _names(client, category=cat["id"]) == ["artist:kantoku", "red_skirt"]
    assert _names(client, category=cat["id"], namespace="artist") \
        == ["artist:kantoku", "artist:mika", "red_skirt"]
    assert _names(client, category=cat["id"], namespace="character") \
        == ["artist:kantoku", "character:miku", "red_skirt"]
    # SEVERAL NAMESPACES ARE A UNION TOO, exactly as several categories are.
    assert _names(client, namespace=["artist", "character"]) \
        == ["artist:kantoku", "artist:mika", "character:miku"]
    assert b


def test_filing_is_authored_so_it_survives_a_rename(client):
    dog = _tag(client, "dog")
    cat = client.post("/api/tags/categories", json={"name": "Animals"}).json()
    client.post("/api/tags/category",
                json={"tag_ids": [dog], "category_id": cat["id"]})
    client.patch(f"/api/tags/{dog}", json={"name": "hound"})

    assert _names(client, category=cat["id"]) == ["hound"]


def test_a_category_of_an_imported_set_cannot_hold_a_library_tag(client):
    """One model, two tag sets. A tag filed in an imported set's category
    would read as filed somewhere the Tags tab cannot show it."""
    dog = _tag(client, "dog")
    other = client.post("/api/tag-sets", json={"name": "Booru mini"}).json()
    theirs = client.post(f"/api/tag-sets/{other['id']}/categories",
                         json={"name": "Animals"}).json()

    r = client.post("/api/tags/category",
                    json={"tag_ids": [dog], "category_id": theirs["id"]})
    assert r.status_code == 400


def test_filing_a_selection_undoes_to_where_each_row_came_from(client):
    """One gesture, one event — and a selection dragged onto a category need
    not have come from one place, so the revert is per row."""
    dog, cat_tag = _tag(client, "dog"), _tag(client, "cat")
    animals = client.post("/api/tags/categories", json={"name": "Animals"}).json()
    pets = client.post("/api/tags/categories", json={"name": "Pets"}).json()
    client.post("/api/tags/category",
                json={"tag_ids": [dog], "category_id": animals["id"]})
    # `cat` starts uncategorized, `dog` starts in Animals; both move to Pets.
    moved = client.post("/api/tags/category",
                        json={"tag_ids": [dog, cat_tag],
                              "category_id": pets["id"]}).json()
    assert sorted(moved) == sorted([dog, cat_tag])
    assert _names(client, category=pets["id"]) == ["cat", "dog"]

    ev = [e for e in client.get("/api/history").json()["events"]
          if e["action"] == "set_tag_category"][0]
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})

    assert _names(client, category=animals["id"]) == ["dog"]
    assert _names(client, uncategorized=True) == ["cat"]


def test_a_tag_carries_its_own_description_again(client):
    """The library is a set now, and one that cannot say what its own names
    mean exports to a template with no teaching in it."""
    dog = _tag(client, "dog")
    client.patch(f"/api/tags/{dog}", json={"description": "Dogs, any size."})
    rows = client.post("/api/tags/rows", json={"ids": [dog]}).json()
    assert rows[0]["description"] == "Dogs, any size."

    ev = [e for e in client.get("/api/history").json()["events"]
          if e["action"] == "describe_tag"][0]
    client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    rows = client.post("/api/tags/rows", json={"ids": [dog]}).json()
    assert rows[0]["description"] == ""


def test_the_sidebar_lists_only_namespaces_two_names_share(client):
    """A namespace is not a thing — no table, no id, just the text before the
    first colon — and a heading over ONE name says nothing, which is the rule
    the inline parent rows have always followed."""
    for n in ("artist:kantoku", "artist:mika", "character:miku", "red_skirt"):
        _tag(client, n)

    rows = client.get("/api/tags/namespaces").json()
    assert [(r["name"], r["count"]) for r in rows] == [("artist", 2)]

    _tag(client, "character:teto")
    rows = client.get("/api/tags/namespaces").json()
    assert [(r["name"], r["count"]) for r in rows] == [("artist", 2), ("character", 2)]


def test_a_hidden_namespace_says_so_on_its_row(client):
    """The row wears the mark, and pressing it is the way back — but the rule
    is a SETTING over a prefix, so it covers names made later too."""
    _tag(client, "artist:kantoku")
    _tag(client, "artist:mika")
    client.put("/api/tags/hidden-namespaces", json={"namespaces": ["artist"]})

    assert client.get("/api/tags/namespaces").json() == [
        {"name": "artist", "count": 2, "hidden": True}]


def test_an_imported_sets_namespaces_follow_the_same_rule(client):
    """The sidebar is the same sidebar for every pill; only where the names
    come from differs — `tags` for the library, its own entries for a set."""
    made = client.post("/api/tag-sets", json={"name": "Booru mini"}).json()
    for n in ("artist:kantoku", "artist:mika", "character:miku"):
        client.post(f"/api/tag-sets/{made['id']}/entries", json={"name": n})

    rows = client.get(f"/api/tag-sets/{made['id']}/namespaces").json()
    assert [(r["name"], r["count"]) for r in rows] == [("artist", 2)]
    # Hiding is the library's setting about its own autocomplete, answered on
    # the library's list; a set's row never claims to know.
    assert all(r["hidden"] is False for r in rows)


def test_the_library_exports_as_an_ordinary_tag_set(client):
    """The point of calling the library a set: what somebody built by hand
    is carried to the next library as advice, which the tag CSV could never
    do — it knows nothing about categories, descriptions or records."""
    dog = _tag(client, "dog")
    _tag(client, "puppy")
    client.patch(f"/api/tags/{dog}",
                 json={"comment": "any dog", "description": "Dogs, any size."})
    client.post(f"/api/tags/{dog}/implies", json={"name": "animal"})
    cat = client.post("/api/tags/categories", json={"name": "Animals"}).json()
    client.post("/api/tags/category",
                json={"tag_ids": [dog], "category_id": cat["id"]})
    client.post("/api/tags", json={"name": "doggy", "alias_of": "dog"})
    client.post("/api/subjects", json={"display_name": "Rex", "tag": "dog"})

    doc = client.get("/api/tags/export").json()
    assert doc["format_version"] == 1
    by = {e["name"]: e for e in doc["entries"]}

    # An ALIAS is a spelling of its target, never an entry of its own.
    assert "doggy" not in by
    assert by["dog"]["aliases"] == ["doggy"]

    assert by["dog"]["description"] == "Dogs, any size."
    assert by["dog"]["comment"] == "any dog"
    assert by["dog"]["implies"] == ["animal"]
    assert by["dog"]["category"] == ["Animals"]
    assert by["dog"]["subject"] == {"name": "Rex"}
    # A tag the library has and says nothing else about is still an entry.
    assert by["puppy"] == {"name": "puppy"}


def test_a_library_with_a_ranking_in_it_still_exports(client):
    """It did not, for as long as a ranking stopped minting tags.

    The walk used to drop a ranking's own `<prefix>:0`…`:9` rows — derived
    from judgments no file can carry, and noise in every library but the
    one that made them. Rung v31 took the namespace, the minting and
    `score_names_of` with it; the filter went on calling it, so every
    export of a library holding a ranking answered 500. The old test
    created its ranking with a `prefix`, which the request model had
    stopped accepting, so it asserted about a ranking that was never made.
    """
    _tag(client, "dog")
    made = client.post("/api/rankings",
                       json={"name": "Quality", "bucket_lo": 0, "bucket_hi": 3})
    assert made.status_code == 200, made.text

    r = client.get("/api/tags/export")
    assert r.status_code == 200, r.text
    names = {e["name"] for e in r.json()["entries"]}
    assert "dog" in names


def test_the_exported_file_imports_as_an_ordinary_set(client):
    """Round trip: what comes out is a set file, so it goes back in as one —
    advice, written into the library only when a name is assigned."""
    dog = _tag(client, "dog")
    client.patch(f"/api/tags/{dog}", json={"description": "Dogs, any size."})
    doc = client.get("/api/tags/export").json()

    made = client.post("/api/tag-sets/import",
                       json={"document": doc, "mode": "create"}).json()["set"]
    # It is NOT the library's own set: the key is reserved, so the import
    # takes the next one free.
    assert made["key"] != "library"
    assert made["library"] is False
    rows = client.get(f"/api/tag-sets/{made['id']}/entries").json()["rows"]
    assert [r["name"] for r in rows] == ["dog"]
    assert rows[0]["description"] == "Dogs, any size."


def test_a_sets_row_says_what_the_library_has_under_the_name(client):
    """The `Library` column: one number that says what the in-library mark
    used to, and says how much besides — a name the library has on nine
    hundred pictures and one it has on none read very differently when you
    are deciding what a tag set is worth."""
    made = client.post("/api/tag-sets", json={"name": "Booru mini"}).json()
    for n in ("dog", "cat", "zebra"):
        client.post(f"/api/tag-sets/{made['id']}/entries", json={"name": n})
    # `dog` is in the library and on a picture; `cat` is in it and on none;
    # `zebra` the library has never heard of.
    dog = _tag(client, "dog")
    _tag(client, "cat")
    client.post(f"/api/tags/assign/item/{_item(client)}", json={"tag": "dog"})

    rows = client.get(f"/api/tag-sets/{made['id']}/entries").json()["rows"]
    by = {r["name"]: r for r in rows}
    assert by["dog"]["library_count"] == 1
    # Zero is a tag that exists and is on nothing…
    assert by["cat"]["library_count"] == 0
    # …and blank is a name the library does not have at all.
    assert by["zebra"]["library_count"] is None
    assert dog


def test_a_sets_count_column_takes_a_range(client):
    """The Items list's control, on the column it is about — either end
    optional, so "at least 1000" and "at most 50" are one control with one
    end filled in."""
    made = client.post("/api/tag-sets", json={"name": "Booru mini"}).json()
    for n, c in (("common", 5000), ("middling", 500), ("rare", 5)):
        client.post(f"/api/tag-sets/{made['id']}/entries",
                    json={"name": n, "count": c})
    client.post(f"/api/tag-sets/{made['id']}/entries", json={"name": "uncounted"})

    def names(**q):
        return sorted(r["name"] for r in client.get(
            f"/api/tag-sets/{made['id']}/entries", params=q).json()["rows"])

    assert names(count_min=500) == ["common", "middling"]
    assert names(count_max=500) == ["middling", "rare"]
    assert names(count_min=100, count_max=1000) == ["middling"]
    # An entry with NO count is out of any bounded range: "how popular is
    # this" has no answer there.
    assert "uncounted" in names()
    assert "uncounted" not in names(count_min=0)


def test_a_sets_list_narrows_by_namespace_too(client):
    """The sidebar's derived block is the same block for both tag sets,
    so the narrowing behind it is too — the library reads `tags`, a set its
    own entries."""
    made = client.post("/api/tag-sets", json={"name": "Booru mini"}).json()
    for n in ("artist:kantoku", "artist:mika", "character:miku", "solo"):
        client.post(f"/api/tag-sets/{made['id']}/entries", json={"name": n})

    def names(**q):
        return sorted(r["name"] for r in client.get(
            f"/api/tag-sets/{made['id']}/entries", params=q).json()["rows"])

    assert names(namespace="artist") == ["artist:kantoku", "artist:mika"]
    # With or without the colon: a person types one, the setting stores
    # neither, and neither should be a different question.
    assert names(namespace="artist:") == ["artist:kantoku", "artist:mika"]
    assert names(namespace="character") == ["character:miku"]
    assert "solo" in names()


def test_the_index_answer_is_kept_and_a_write_drops_it(client):
    """The last few index answers are held as the bytes that went out
    (`routers/tags._INDEX_CACHE`), because every control in the tab asks for
    one: a sort, a filter, a keystroke, coming back to the tab.

    The cache is keyed on the library's REVISION, so the only thing that can
    go wrong with it is a write leaving a stale answer behind — which is
    what this asks. Byte-identical while nothing moves, and the new name the
    moment something does.
    """
    _tag(client, "alpha")
    first = client.get("/api/tags/index").content
    assert client.get("/api/tags/index").content == first

    _tag(client, "beta")
    after = client.get("/api/tags/index").content
    assert after != first
    assert client.get("/api/tags/index").json()["names"] == ["alpha", "beta"]


def test_two_libraries_in_one_process_do_not_share_an_index_answer(tmp_path):
    """The cache is per LIBRARY as well as per revision, which the revision
    cannot say on its own: a fresh `Database` starts at zero commits with
    `PRAGMA data_version` at 1, so two of them ask the same question with the
    same token — and every test module here builds several.

    The endpoint is called directly, since what is being asked about is the
    module-level cache and not the HTTP stack over it.
    """
    from media_compost.ops import tagcatalog
    from media_compost.ops.context import Ctx
    from media_compost.ui.server.routers import tags as router

    def one(name: str) -> list[str]:
        lib = Library(UiConfig(data_dir=tmp_path / name))
        with lib.db.session() as s:
            tagcatalog.create(Ctx(session=s, source="test"), name)
            s.commit()
            import json

            body = router.tag_index(s=s, lib=lib, namespace=[], rows=0).body
            return json.loads(body)["names"]

    assert (one("one"), one("two")) == (["one"], ["two"])


def test_the_index_carries_the_first_screenful_whole(client):
    """THE FIRST SCREENFUL RIDES WITH THE INDEX.

    The index answers names and counts; everything else about a row — the
    comment, the category trail, the capsules — was a second request for the
    band on screen, so a fresh listing drew twice and every row moved when
    the second landed. The leading rows travel with it now, and they are the
    same rows `POST /rows` answers, so the two cannot disagree.
    """
    made = client.post("/api/tags", json={"name": "kitten"}).json()
    client.patch(f"/api/tags/{made['id']}", json={"comment": "a small cat"})
    client.post("/api/tags", json={"name": "puppy"})

    plain = client.get("/api/tags/index").json()
    assert plain["names"] == ["kitten", "puppy"]
    # Not asked for, not answered: every caller that only wants the names —
    # the browse tree, anything counting — pays nothing for this.
    assert plain.get("rows") in (None, [])

    got = client.get("/api/tags/index?rows=1").json()
    assert [r["name"] for r in got["rows"]] == ["kitten"]
    assert got["rows"][0]["comment"] == "a small cat"
    # …and byte for byte what the band fetch would have said about it.
    band = client.post("/api/tags/rows", json={"ids": got["ids"][:1]}).json()
    assert got["rows"] == band
