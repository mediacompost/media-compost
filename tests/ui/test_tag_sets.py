"""Tag sets over the API: the router, the autocomplete merge and the rows.

The autocomplete is the one place the two sources meet, and the rules it has
to keep are stated here one by one: a library name wins its row and wears the
set's capsule; a set-only name ranks after every USED library row at its
match position; an alias answers as its canonical; a disabled set vanishes;
the library's own set decorates nothing. `tests/ui/test_tag_names.py` holds
the library half to its reference implementation; this file is about what the
sets add.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from media_compost.ops import tagsets as ops
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

DOC = {
    "format": "media-compost-tag-set", "format_version": 1,
    "name": "Booru mini", "description": "a few",
    "entries": [
        {"name": "ball_gag", "description": "from the set", "count": 900,
         "category": ["people", "count"], "aliases": ["ballgag"]},
        {"name": "balloon_animal", "count": 50},
        {"name": "ball", "description": "the set's words for ball",
         "count": 5000},
        {"name": "zebra", "count": 1, "aliases": ["zeb"]},
    ],
}


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


def _names(c, q, limit=50):
    r = c.get(f"/api/tags/names?q={q}&limit={limit}")
    assert r.status_code == 200, r.text
    return r.json()


def _import(c) -> dict:
    r = c.post("/api/tag-sets/import", json={"document": DOC, "mode": "create"})
    assert r.status_code == 200, r.text
    return r.json()["set"]


def test_the_router_round_trips_a_file_and_lists_it(client):
    c = client
    ts = _import(c)
    rows = c.get("/api/tag-sets").json()
    keys = {r["key"]: r for r in rows}
    # The LIBRARY leads every listing — it is the first pill in the Tags tab,
    # synthesized where its (lazy) row does not exist yet.
    assert set(keys) == {"library", "booru-mini"}
    assert rows[0]["key"] == "library" and rows[0]["library"] is True
    # SIX names, not four: `ballgag` and `zeb` are rows of the list like
    # any other name, so the number the pill shows counts them.
    assert keys["booru-mini"]["entries"] == 6 and keys["booru-mini"]["categories"] == 2
    exported = c.get(f"/api/tag-sets/{ts['id']}/export")
    assert exported.status_code == 200
    assert exported.headers["content-disposition"].endswith('"booru-mini.json"')
    assert json.loads(exported.text) == DOC
    detail = c.get(f"/api/tag-sets/{ts['id']}").json()
    assert [r["trail"] for r in detail["category_rows"]] == [["people"],
                                                             ["people", "count"]]
    page = c.get(f"/api/tag-sets/{ts['id']}/entries?q=ball").json()
    # AND THE SPELLING IS SEARCHED LIKE A NAME, because it is one.
    assert page["total"] == 4
    assert {r["name"] for r in page["rows"]} == {"ball_gag", "balloon_animal",
                                                 "ball", "ballgag"}
    assert next(r for r in page["rows"] if r["name"] == "ball_gag")["aliases"] == ["ballgag"]
    alias = next(r for r in page["rows"] if r["name"] == "ballgag")
    assert alias["alias_of"] == "ball_gag" and alias["aliases"] == []
    # A second import of the same file is REFUSED by name — a set's name is
    # unique — and the same file under another name is a second set with a
    # fresh key.
    r = c.post("/api/tag-sets/import", json={"document": DOC, "mode": "create"})
    assert r.status_code == 409, r.text
    r = c.post("/api/tag-sets/import",
               json={"document": {**DOC, "name": "Booru mini 2"}, "mode": "create"})
    assert r.status_code == 200, r.text
    assert r.json()["set"]["key"] == "booru-mini-2"
    # Rename and create refuse a taken name too, whatever its case.
    assert c.post("/api/tag-sets", json={"name": "BOORU MINI"}).status_code == 409
    assert c.patch(f"/api/tag-sets/{ts['id']}", json={"name": "booru mini 2"}).status_code == 409
    # A duplicate numbers its copy past a clash rather than refusing.
    a = c.post(f"/api/tag-sets/{ts['id']}/duplicate", json={}).json()
    b = c.post(f"/api/tag-sets/{ts['id']}/duplicate", json={}).json()
    assert (a["name"], b["name"]) == ("Booru mini (copy)", "Booru mini (copy) 2")


def test_a_template_makes_an_ordinary_set(client):
    c = client
    # Only the library's own pill, which is always there.
    assert [r["key"] for r in c.get("/api/tag-sets").json()] == ["library"]
    # The shipped list is a TEMPLATE, offered by the API and made into a set
    # on request — one the person then owns.
    tpls = c.get("/api/tag-sets/templates").json()
    assert [t["key"] for t in tpls] == ["booru", "characters", "cinematography",
                                        "documents", "photography"]
    assert tpls[0]["entries"] > 50 and tpls[0]["name"] == "Booru"
    made = c.post("/api/tag-sets/from-template", json={"template": "booru"})
    assert made.status_code == 200, made.text
    ts = made.json()["set"]
    assert ts["key"] == "booru" and ts["builtin"] is False and ts["enabled"]
    assert c.post(f"/api/tag-sets/{ts['id']}/entries",
                  json={"name": "not_a_booru_tag"}).status_code == 200
    assert c.delete(f"/api/tag-sets/{ts['id']}").status_code == 200
    assert c.post("/api/tag-sets/from-template", json={"template": "nope"}).status_code == 404
    # An unknown field on a body is a 422, not a silently different request.
    assert c.post("/api/tag-sets", json={"name": "x", "colour": "red"}).status_code == 422


def test_a_set_only_name_is_offered_after_the_library_and_creates_on_assignment(client):
    c = client
    # Library tags: `ball` (used twice), `ballroom` (unused).
    c.post("/api/tags", json={"name": "ball"})
    c.post("/api/tags", json={"name": "ballroom"})
    item = c.post("/api/items/from-bytes", json={}) if False else None  # noqa: F841
    _import(c)
    rows = _names(c, "ball")
    names = [r["name"] for r in rows]
    # Exact first (a library row that also wears the set's capsule), then the
    # prefix bucket: the unused library `ballroom` and the set's `ball_gag` /
    # `balloon_animal` / `ballgag`, positive 0 apiece, ordered by the set's
    # count — and the library alias-free rows have no count at all, so the
    # set's counted rows come first among the unused.
    assert names[0] == "ball"
    assert rows[0]["tag_sets"] == [{"key": "booru-mini", "name": "Booru mini", "count": 5000}]
    assert rows[0]["descriptions"] == [
        {"key": "booru-mini", "text": "the set's words for ball", "trail": [],
         "count": 5000, "aliases": [], "implies": [], "implied_by": [],
         # …what it LABELS the name with (none here), and — empty, since
         # `ball` is the set's own entry rather than a spelling of one —
         # the entry the answer really came from.
         "meta": [], "alias_of": "",
         # …and what the set says the TAG is, which this one does not.
         "comment": "", "subject": None, "place": None, "event": None}]
    assert set(names) == {"ball", "ballroom", "ball_gag", "balloon_animal", "ballgag"}
    gag = next(r for r in rows if r["name"] == "ball_gag")
    assert gag["positive"] == 0 and gag["tag_sets"][0]["count"] == 900
    alias = next(r for r in rows if r["name"] == "ballgag")
    assert alias["alias_of"] == "ball_gag"
    # Set-only rows sort by their count among the unused: 900 before 50.
    assert names.index("ball_gag") < names.index("balloon_animal")
    # The tags table has NOT grown.
    assert {t["name"] for t in c.get("/api/tags").json()} == {"ball", "ballroom"}


def test_a_used_library_row_outranks_a_busier_set_row(client):
    c = client
    _import(c)
    c.post("/api/tags", json={"name": "ball_pit"})
    # One assignment makes it USED; the set's ball_gag has a count of 900 and
    # no library use at all.
    from media_compost.db import Item
    from sqlalchemy import insert, select
    with c.lib.db.session() as s:
        s.execute(insert(Item), [{"uid": "u1", "name": "i1", "kind": "image"}])
        s.commit()
        iid = s.execute(select(Item.id)).scalars().first()
    c.post(f"/api/tags/assign/item/{iid}", json={"tag": "ball_pit", "negative": False})
    names = [r["name"] for r in _names(c, "ball_")]
    assert names.index("ball_pit") < names.index("ball_gag")


def test_assigning_a_set_only_name_mints_it_and_a_set_alias_redirects(client):
    c = client
    _import(c)
    from media_compost.db import Item
    from sqlalchemy import insert, select
    with c.lib.db.session() as s:
        s.execute(insert(Item), [{"uid": "u1", "name": "i1", "kind": "image"}])
        s.commit()
        iid = s.execute(select(Item.id)).scalars().first()
    c.post(f"/api/tags/assign/item/{iid}", json={"tag": "zeb", "negative": False})
    tags = {t["name"]: t for t in c.get("/api/tags").json()}
    # The alias created the CANONICAL — and nothing else, since this entry
    # says nothing about what it entails.
    assert set(tags) == {"zebra"}
    assert tags["zebra"]["implies"] == []
    assert tags["zebra"]["tag_sets"] == [{"key": "booru-mini", "name": "Booru mini", "count": 1}]
    detail = c.get(f"/api/items/{iid}").json()
    assert "zebra" in {t["name"] for t in detail["tags"]}
    # The rows endpoint carries the set's claim and its texts.
    row = c.post("/api/tags/rows", json={"ids": [tags["zebra"]["id"]]}).json()[0]
    assert row["tag_sets"] == [{"key": "booru-mini", "name": "Booru mini", "count": 1}]
    # A SET ANSWERS FOR A NAME IT KNOWS, described or not: the popover shows
    # its count and its other spellings either way, and a `?` that appeared
    # only where somebody had written prose hid the rest of what a set knows.
    assert row["descriptions"] == [
        {"key": "booru-mini", "text": "", "trail": [], "count": 1,
         "aliases": ["zeb"], "implies": [], "implied_by": [],
         "meta": [], "alias_of": "",
         "comment": "", "subject": None, "place": None, "event": None}]


def test_a_spelling_answers_with_its_entry_and_says_which(client):
    """`/describe` resolves a SPELLING to its entry's row — and the frame has
    to name that entry, or the popover shows a description for something it
    never mentions: ask about `zeb`, read a sentence about zebras, with
    nothing saying the set files both under one name.

    `alias_of` is empty on the entry's own row, so the line is drawn only
    where the two really differ.
    """
    c = client
    _import(c)
    got = c.get("/api/tag-sets/describe?names=zeb,zebra").json()
    spelling = got["zeb"]["descriptions"][0]
    entry = got["zebra"]["descriptions"][0]
    assert spelling["alias_of"] == "zebra"
    assert entry["alias_of"] == ""
    # It is the SAME row either way — that is why the name has to be said.
    assert spelling["aliases"] == entry["aliases"] == ["zeb"]
    assert spelling["count"] == entry["count"]


def test_what_a_set_labels_a_name_with_reaches_the_popover(client):
    """A meta tag is as much what a set says about a name as its spellings
    and its entailments are, and the `?` drew every one of those but not
    these — which for a bulk import is often the whole of what it knows."""
    c = client
    _import_meta(c)
    said = c.get("/api/tag-sets/describe?names=hatsune_miku").json()
    frames = said["hatsune_miku"]["descriptions"]
    assert frames, said
    assert any(f["meta"] for f in frames), frames


def test_a_tag_one_set_knows_beats_an_alias_another_set_has_for_it(client):
    """Two tag sets disagreeing about one word is ordinary: `ball` is a
    tag in one set and a spelling of `ball_gag` in another. THE TAG WINS —
    the autocomplete offers it once, as itself, and assigning it mints
    `ball` rather than redirecting to somebody else's canonical."""
    c = client
    # The first set has `ball` as an ENTRY; a second has it as an ALIAS of
    # something else, and sorts FIRST, so position cannot be what decides.
    _import(c)
    other = c.post("/api/tag-sets/import", json={"document": {
        "format": "media-compost-tag-set", "format_version": 1,
        "name": "Other", "entries": [
            {"name": "ball_gag_2", "aliases": ["ball", "zebra"]},
            {"name": "only_aliased_here", "aliases": ["nowhere_a_tag"]},
        ]}, "mode": "create"}).json()["set"]
    c.patch(f"/api/tag-sets/{other['id']}", json={"position": -1})

    rows = {r["name"]: r for r in _names(c, "ball")}
    assert rows["ball"]["alias_of"] is None, "the entry wins over the alias"
    # …and it is offered ONCE, not once per set that has an opinion.
    assert [r["name"] for r in _names(c, "ball")].count("ball") == 1
    # A name NO set has as an entry is still an alias, and its target comes
    # from the first set that says so.
    only = {r["name"]: r for r in _names(c, "nowhere_a_tag")}
    assert only["nowhere_a_tag"]["alias_of"] == "only_aliased_here"
    # THE DOOR AGREES, which is the half that writes: assigning `ball` mints
    # `ball` rather than redirecting to somebody else's canonical.
    from media_compost.db import Item
    from sqlalchemy import insert, select
    with c.lib.db.session() as s:
        s.execute(insert(Item), [{"uid": "u1", "name": "i1", "kind": "image"}])
        s.commit()
        iid = s.execute(select(Item.id)).scalars().first()
    c.post(f"/api/tags/assign/item/{iid}", json={"tag": "ball", "negative": False})
    have = {t["name"] for t in c.get(f"/api/items/{iid}").json()["tags"]}
    assert "ball" in have and "ball_gag_2" not in have
    # But a name NO set has as an entry still redirects.
    c.post(f"/api/tags/assign/item/{iid}",
           json={"tag": "nowhere_a_tag", "negative": False})
    have = {t["name"] for t in c.get(f"/api/items/{iid}").json()["tags"]}
    assert "only_aliased_here" in have and "nowhere_a_tag" not in have


def test_a_disabled_set_vanishes_from_every_read(client):
    c = client
    ts = _import(c)
    c.post("/api/tags", json={"name": "ball"})
    assert "ball_gag" in {r["name"] for r in _names(c, "ball")}
    assert c.get("/api/tags").json()[0]["tag_sets"]
    c.put(f"/api/tag-sets/{ts['id']}/enabled", json={"enabled": False})
    assert "ball_gag" not in {r["name"] for r in _names(c, "ball")}
    assert c.get("/api/tags").json()[0]["tag_sets"] == []
    assert _names(c, "ball")[0]["tag_sets"] == []


def test_the_preferred_order_is_per_user_and_names_every_enabled_set(client):
    c = client
    _import(c)
    order = c.get("/api/settings/tag-set-order").json()["keys"]
    assert order == ["booru-mini"]
    r = c.put("/api/settings/tag-set-order", json={"keys": ["booru-mini", "nope"]})
    assert r.status_code == 200
    assert r.json()["keys"] == ["booru-mini"]


def test_bulk_entries_and_category_edits_over_the_api(client):
    c = client
    ts = _import(c)
    r = c.post(f"/api/tag-sets/{ts['id']}/entries/bulk", json={
        "rows": [{"name": "new_tag", "category": ["people", "new"], "count": 3},
                 {"name": "bad name"}],
        "existing": "keep"})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1 and body["errors"][0]["name"] == "bad name"
    detail = c.get(f"/api/tag-sets/{ts['id']}").json()
    trails = {tuple(row["trail"]): row for row in detail["category_rows"]}
    assert ("people", "new") in trails
    new_cat = trails[("people", "new")]
    r = c.patch(f"/api/tag-sets/{ts['id']}/categories/{new_cat['id']}",
                json={"name": "newer"})
    assert r.status_code == 200 and r.json()["trail"] == ["people", "newer"]
    r = c.patch(f"/api/tag-sets/{ts['id']}/categories/{new_cat['id']}",
                json={"clear_parent": True})
    assert r.json()["trail"] == ["newer"]
    entry = next(e for e in c.get(f"/api/tag-sets/{ts['id']}/entries?q=new_tag").json()["rows"])
    r = c.patch(f"/api/tag-sets/{ts['id']}/entries/{entry['id']}",
                json={"clear_count": True, "aliases": ["nt"]})
    assert r.json()["count"] is None and r.json()["aliases"] == ["nt"]
    assert c.delete(f"/api/tag-sets/{ts['id']}/entries/{entry['id']}").json() == {"ok": True}
    assert c.delete(f"/api/tag-sets/{ts['id']}/categories/{new_cat['id']}").json() == {"ok": True}
    assert c.delete(f"/api/tag-sets/{ts['id']}").json() == {"ok": True}
    assert c.get(f"/api/tag-sets/{ts['id']}").status_code == 404


def test_the_tree_lists_the_enabled_sets_with_per_node_counts(client):
    c = client
    ts = _import(c)
    tree = c.get("/api/tag-sets/tree").json()["sets"]
    assert [t["key"] for t in tree] == ["booru-mini"]
    me = tree[0]
    assert me["entries"] == 6 and me["uncategorized"] == 4
    by = {tuple(r["trail"]): r for r in me["categories"]}
    assert by[("people", "count")]["entries"] == 2   # `ball_gag` and `ballgag`
    assert by[("people",)]["entries"] == 0
    # Disabled, it is gone from the tree; the library's own set never shows.
    c.put(f"/api/tag-sets/{ts['id']}/enabled", json={"enabled": False})
    assert c.get("/api/tag-sets/tree").json()["sets"] == []
    # And the entries of one node are the paged endpoint's, by category.
    c.put(f"/api/tag-sets/{ts['id']}/enabled", json={"enabled": True})
    cid = by[("people", "count")]["id"]
    rows = c.get(f"/api/tag-sets/{ts['id']}/entries?category_id={cid}").json()["rows"]
    assert [r["name"] for r in rows] == ["ball_gag", "ballgag"]
    loose = c.get(f"/api/tag-sets/{ts['id']}/entries?uncategorized=true").json()
    assert loose["total"] == 4


def test_a_category_implicitly_holds_its_subcategories_entries(client):
    """The Sets tab reads a category as its own entries AND everything under
    it: `subtree=true` on the entries page, and the detail's per-category
    count is the same figure — where the browse tree keeps the direct one."""
    c = client
    ts = c.post("/api/tag-sets", json={"name": "Nested"}).json()
    top = c.post(f"/api/tag-sets/{ts['id']}/categories", json={"name": "clothing"}).json()
    sub = c.post(f"/api/tag-sets/{ts['id']}/categories",
                 json={"name": "tops", "parent_id": top["id"]}).json()
    for name, cid in [("dress", top["id"]), ("shirt", sub["id"]), ("hoodie", sub["id"])]:
        c.post(f"/api/tag-sets/{ts['id']}/entries", json={"name": name, "category_id": cid})
    direct = c.get(f"/api/tag-sets/{ts['id']}/entries?category_id={top['id']}").json()
    whole = c.get(f"/api/tag-sets/{ts['id']}/entries?category_id={top['id']}&subtree=true").json()
    assert [r["name"] for r in direct["rows"]] == ["dress"]
    assert sorted(r["name"] for r in whole["rows"]) == ["dress", "hoodie", "shirt"]
    assert whole["total"] == 3
    by = {tuple(r["trail"]): r["count"]
          for r in c.get(f"/api/tag-sets/{ts['id']}").json()["category_rows"]}
    assert by == {("clothing",): 3, ("clothing", "tops"): 2}
    tree = {t["key"]: t for t in c.get("/api/tag-sets/tree").json()["sets"]}["nested"]
    assert {tuple(r["trail"]): r["entries"] for r in tree["categories"]} == {
        ("clothing",): 1, ("clothing", "tops"): 2}


def test_a_hidden_category_stops_offering_its_names_and_keeps_everything_else(client):
    """HIDING IS ABOUT WHAT IS OFFERED — the category, everything under it and
    every name in that subtree leave the autocomplete and the browse tree.

    What it is NOT: a deletion. The Sets tab still lists and edits the
    entries, an export still carries them, and a name the LIBRARY already has
    goes on being offered by its own row — those come from `tags`, which no
    set has ever had a say in.
    """
    c = client
    ts = c.post("/api/tag-sets", json={"name": "Nested"}).json()
    top = c.post(f"/api/tag-sets/{ts['id']}/categories", json={"name": "clothing"}).json()
    sub = c.post(f"/api/tag-sets/{ts['id']}/categories",
                 json={"name": "tops", "parent_id": top["id"]}).json()
    for name, cid, aliases in [("dressy", top["id"], []),
                               ("shirty", sub["id"], ["shirtish"]),
                               ("loosey", None, [])]:
        r = c.post(f"/api/tag-sets/{ts['id']}/entries",
                   json={"name": name, "category_id": cid, "aliases": aliases})
        assert r.status_code == 200, r.text
    # The library HAS one of the hidden names already.
    assert c.post("/api/tags", json={"name": "dressy"}).status_code in (200, 201)

    offered = lambda q: {r["name"] for r in _names(c, q)}
    assert offered("y") >= {"dressy", "shirty", "loosey"}
    assert "shirtish" in offered("shirt")

    r = c.patch(f"/api/tag-sets/{ts['id']}/categories/{top['id']}", json={"hidden": True})
    assert r.status_code == 200 and r.json()["hidden"] is True

    after = offered("y")
    # The sub-category's entry and its ALIAS go with the parent…
    assert "shirty" not in after and "shirtish" not in offered("shirt")
    # …an entry in NO category is untouched (a NULL is not "in" anything)…
    assert "loosey" in after
    # …and the name the library has is still offered, by the library's row.
    assert "dressy" in after

    # The browse tree carries neither the category nor its child, and the
    # set's own figure drops the names it no longer offers.
    tree = {t["key"]: t for t in c.get("/api/tag-sets/tree").json()["sets"]}["nested"]
    assert [r["trail"] for r in tree["categories"]] == []
    assert tree["entries"] == 1 and tree["uncategorized"] == 1
    # (`shirty` and its spelling are both under the hidden branch.)

    # The Sets tab is unchanged: the rows are there, marked.
    detail = c.get(f"/api/tag-sets/{ts['id']}").json()
    assert {tuple(r["trail"]): r["hidden"] for r in detail["category_rows"]} == {
        ("clothing",): True, ("clothing", "tops"): False}
    rows = c.get(f"/api/tag-sets/{ts['id']}/entries?category_id={sub['id']}").json()
    assert [r["name"] for r in rows["rows"]] == ["shirty", "shirtish"]

    # The FILE carries it, and an import reads it back.
    doc = json.loads(c.get(f"/api/tag-sets/{ts['id']}/export").text)
    # ONE ROW, for the one category that says something: the tree itself is
    # what the entries imply, and the child inherits by carrying nothing.
    assert doc["categories"] == [{"path": ["clothing"], "hidden": True}]
    again = c.post("/api/tag-sets/import",
                   json={"document": {**doc, "key": "nested2", "name": "Nested 2"},
                         "mode": "create"}).json()["set"]
    assert {tuple(r["trail"]): r["hidden"]
            for r in c.get(f"/api/tag-sets/{again['id']}").json()["category_rows"]} == {
        ("clothing",): True, ("clothing", "tops"): False}

    # And showing it again brings every name back.
    c.patch(f"/api/tag-sets/{ts['id']}/categories/{top['id']}", json={"hidden": False})
    assert "shirty" in offered("y")


def test_hiding_a_category_reverts(client):
    """The flag is an ordinary edit: one event, and the revert puts it back
    — with the icon and the name it also carries."""
    c = client
    ts = c.post("/api/tag-sets", json={"name": "Nested"}).json()
    cat = c.post(f"/api/tag-sets/{ts['id']}/categories", json={"name": "clothing"}).json()
    c.patch(f"/api/tag-sets/{ts['id']}/categories/{cat['id']}", json={"hidden": True})
    ev = c.get("/api/history?limit=1").json()["events"][0]
    assert ev["action"] == "edit_tag_set_category"
    r = c.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.status_code == 200 and r.json()["reverted"] == [ev["id"]], r.text
    rows = {tuple(r["trail"]): r["hidden"]
            for r in c.get(f"/api/tag-sets/{ts['id']}").json()["category_rows"]}
    assert rows == {("clothing",): False}


def test_an_entry_says_what_it_implies_and_the_door_mints_it(client):
    """A set's `implies` is advice like everything else it holds, and the
    ASSIGNMENT is what acts on it: the first time the entry's name is made
    into a tag, the names it entails are minted and linked as ordinary
    library implications — each its own logged event, so the log says what
    happened and the undo takes it back.

    A library that already HAS the tag is left alone: the set never
    re-describes an answer the library has already given."""
    c = client
    ts = _import(c)
    # `ball_gag` entails `bondage`, which the library has never heard of.
    entry = next(r for r in c.get(f"/api/tag-sets/{ts['id']}/entries?q=ball_gag")
                 .json()["rows"])
    r = c.patch(f"/api/tag-sets/{ts['id']}/entries/{entry['id']}",
                json={"implies": ["bondage", "ball_gag"]})
    assert r.status_code == 200, r.text
    # An entry never implies ITSELF; the rest rides.
    assert r.json()["implies"] == ["bondage"]

    from media_compost.db import Item
    from sqlalchemy import insert, select
    with c.lib.db.session() as s:
        s.execute(insert(Item), [{"uid": "u1", "name": "i1", "kind": "image"}])
        s.commit()
        iid = s.execute(select(Item.id)).scalars().first()
    c.post(f"/api/tags/assign/item/{iid}", json={"tag": "ball_gag", "negative": False})
    tags = {t["name"]: t for t in c.get("/api/tags").json()}
    assert set(tags) == {"ball_gag", "bondage"}
    assert tags["ball_gag"]["implies"] == ["bondage"]
    # The link is an ordinary logged implication, and reverting it takes it
    # back without touching the tags themselves.
    ev = next(e for e in c.get("/api/history?limit=10").json()["events"]
              if e["action"] == "add_tag_implication")
    assert c.post("/api/history/revert", json={"event_ids": [ev["id"]]}).json()["reverted"]
    assert {t["name"]: t["implies"] for t in c.get("/api/tags").json()}["ball_gag"] == []

    # A tag the library ALREADY has is never re-described: `balloon_animal`
    # is made by hand first, and assigning it afterwards adds nothing.
    balloon = c.get(f"/api/tag-sets/{ts['id']}/entries?q=balloon").json()["rows"][0]
    c.patch(f"/api/tag-sets/{ts['id']}/entries/{balloon['id']}",
            json={"implies": ["party"]})
    c.post("/api/tags", json={"name": "balloon_animal"})
    c.post(f"/api/tags/assign/item/{iid}", json={"tag": "balloon_animal", "negative": False})
    after = {t["name"]: t for t in c.get("/api/tags").json()}
    assert "party" not in after and after["balloon_animal"]["implies"] == []

    # And the file carries it, both ways.
    doc = json.loads(c.get(f"/api/tag-sets/{ts['id']}/export").text)
    by = {e["name"]: e for e in doc["entries"]}
    assert by["ball_gag"]["implies"] == ["bondage"]
    assert "implies" not in by["zebra"]
    again = c.post("/api/tag-sets/import",
                   json={"document": {**doc, "key": "mini2", "name": "Mini 2"},
                         "mode": "create"}).json()["set"]
    rows = c.get(f"/api/tag-sets/{again['id']}/entries?q=ball_gag").json()["rows"]
    assert rows[0]["implies"] == ["bondage"]


def test_a_ring_of_implications_breaks_at_the_edge_furthest_from_the_assignment(client):
    """`a → b → c → a` cannot be a library implication, so one edge of a
    set's ring has to go — and it must not be the one the assignment was
    about. The walk is BREADTH FIRST from the assigned name: `a` implies `b`,
    `b` implies `c`, and the edge back to `a` is the one that finds the loop
    already there and is dropped.

    (Recursing through the door instead reached `c → a` first and left the
    person's own `a → b` as the refused one.)"""
    c = client
    ts = c.post("/api/tag-sets", json={"name": "Ring"}).json()
    for name, implies in [("zza", ["zzb"]), ("zzb", ["zzc"]), ("zzc", ["zza"])]:
        r = c.post(f"/api/tag-sets/{ts['id']}/entries",
                   json={"name": name, "implies": implies})
        assert r.status_code == 200, r.text

    from media_compost.db import Item
    from sqlalchemy import insert, select
    with c.lib.db.session() as s:
        s.execute(insert(Item), [{"uid": "u1", "name": "i1", "kind": "image"}])
        s.commit()
        iid = s.execute(select(Item.id)).scalars().first()
    assert c.post(f"/api/tags/assign/item/{iid}",
                  json={"tag": "zza", "negative": False}).status_code == 200
    tags = {t["name"]: t["implies"] for t in c.get("/api/tags").json()}
    assert tags == {"zza": ["zzb"], "zzb": ["zzc"], "zzc": []}
    # And the item carries all three, the ring's own point.
    on = {t["name"] for t in c.get(f"/api/items/{iid}").json()["tags"]}
    assert {"zza", "zzb", "zzc"} <= on


def test_an_entry_never_implies_itself_under_another_spelling(client):
    """Its own name and its own ALIASES assign this very tag, so implying one
    would be the tag implying itself. Dropped where it is written — the
    dialog, the file, the CSV — and the door skips it besides, since a set
    alias resolves to its canonical before anything is linked."""
    c = client
    ts = c.post("/api/tag-sets", json={"name": "Self"}).json()
    r = c.post(f"/api/tag-sets/{ts['id']}/entries",
               json={"name": "zzx", "aliases": ["zzx_alias"],
                     "implies": ["zzx", "zzx_alias", "zzreal"]})
    assert r.status_code == 200, r.text
    assert r.json()["implies"] == ["zzreal"]
    # The same through the file, and through an edit.
    doc = json.loads(c.get(f"/api/tag-sets/{ts['id']}/export").text)
    doc["entries"][0]["implies"] = ["zzx_alias", "zzreal"]
    made = c.post("/api/tag-sets/import",
                  json={"document": {**doc, "key": "self2", "name": "Self 2"},
                        "mode": "create"}).json()["set"]
    rows = c.get(f"/api/tag-sets/{made['id']}/entries").json()["rows"]
    assert rows[0]["implies"] == ["zzreal"]
    eid = c.get(f"/api/tag-sets/{ts['id']}/entries").json()["rows"][0]["id"]
    back = c.patch(f"/api/tag-sets/{ts['id']}/entries/{eid}",
                   json={"implies": ["zzx_alias"]}).json()
    assert back["implies"] == []


def test_a_spelling_is_a_row_of_the_list_like_any_other(client):
    """AN ALIAS IS A ROW (owner 2026-09), exactly as it is in the library's
    own list: its own id, its own checkbox, its own place in every order,
    and `alias_of` naming what it spells. It used to be drawn inside its
    entry's row, which is the one thing the two lists said differently
    about the same fact.

    What it does NOT carry is anything that belongs to a tag: no other
    spellings of its own, no description, no count. Deleting one takes the
    spelling and leaves the tag — and the revert puts it back AS a spelling
    rather than as an entry of its own.
    """
    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = {r["name"]: r for r in
            c.get(f"/api/tag-sets/{sid}/entries?limit=200").json()["rows"]}
    al = rows["ballgag"]
    assert al["alias_of"] == "ball_gag" and al["aliases"] == []
    assert rows["ball_gag"]["alias_of"] is None
    # It is FILED WHERE ITS ENTRY IS, so the tree's counts hold it.
    assert al["category_trail"] == ["people", "count"]
    # And it stands directly under the name it spells in EVERY order — the
    # list draws it indented there, the way a namespace's names are drawn
    # under their parent row.
    for sort in ("position", "count", "category", "name"):
        names = c.get(
            f"/api/tags/index?set_id={sid}&sort={sort}").json()["names"]
        assert names.index("ballgag") == names.index("ball_gag") + 1, sort

    # Deleting the ROW takes the spelling; the entry keeps everything else.
    assert c.delete(f"/api/tag-sets/{sid}/entries/{al['id']}").status_code == 200
    left = {r["name"]: r for r in
            c.get(f"/api/tag-sets/{sid}/entries?limit=200").json()["rows"]}
    assert "ballgag" not in left and left["ball_gag"]["aliases"] == []
    # …and the revert puts it back as a SPELLING, not as an entry.
    ev = next(e for e in c.get("/api/history").json()["events"]
              if e["action"] == "delete_tag_set_entry")
    assert c.post("/api/history/revert", json={"event_ids": [ev["id"]]}).json()["reverted"]
    back = {r["name"]: r for r in
            c.get(f"/api/tag-sets/{sid}/entries?limit=200").json()["rows"]}
    assert back["ballgag"]["alias_of"] == "ball_gag"
    assert back["ball_gag"]["aliases"] == ["ballgag"]


def test_a_set_alias_of_a_tag_is_never_implied_by_it(client):
    """The door's own half of the rule: an entry implying a name that ANOTHER
    entry of the set calls an alias links to that entry's canonical (what
    assigning the name would do), and one that resolves back to the tag being
    created is skipped rather than becoming a self-implication."""
    c = client
    ts = c.post("/api/tag-sets", json={"name": "Aliased"}).json()
    c.post(f"/api/tag-sets/{ts['id']}/entries",
           json={"name": "zzcanon", "aliases": ["zzsecond"]})
    c.post(f"/api/tag-sets/{ts['id']}/entries",
           json={"name": "zzother", "implies": ["zzsecond"]})

    from media_compost.db import Item
    from sqlalchemy import insert, select
    with c.lib.db.session() as s:
        s.execute(insert(Item), [{"uid": "u1", "name": "i1", "kind": "image"}])
        s.commit()
        iid = s.execute(select(Item.id)).scalars().first()
    c.post(f"/api/tags/assign/item/{iid}", json={"tag": "zzother", "negative": False})
    tags = {t["name"]: t["implies"] for t in c.get("/api/tags").json()}
    # The alias was never made a tag; the canonical is what is implied.
    assert "zzsecond" not in tags
    assert tags["zzother"] == ["zzcanon"]


def test_several_categories_list_as_one_page(client):
    """The Sets tab picks several categories at once, and their entries are
    ONE page: the union, each expanded through its own subtree, deduped where
    the picks overlap — with the total and the sort the endpoint's own."""
    c = client
    ts = c.post("/api/tag-sets", json={"name": "Nested"}).json()
    top = c.post(f"/api/tag-sets/{ts['id']}/categories", json={"name": "clothing"}).json()
    sub = c.post(f"/api/tag-sets/{ts['id']}/categories",
                 json={"name": "tops", "parent_id": top["id"]}).json()
    other = c.post(f"/api/tag-sets/{ts['id']}/categories", json={"name": "hair"}).json()
    for name, cid in [("dress", top["id"]), ("shirt", sub["id"]),
                      ("bob_cut", other["id"]), ("loose_one", None)]:
        c.post(f"/api/tag-sets/{ts['id']}/entries", json={"name": name, "category_id": cid})

    def page(*cids, subtree=True):
        qs = "".join(f"&category_id={i}" for i in cids)
        r = c.get(f"/api/tag-sets/{ts['id']}/entries?sort=name{qs}"
                  f"&subtree={'true' if subtree else 'false'}").json()
        return [x["name"] for x in r["rows"]], r["total"]

    # One category is what it always was: its own entries and its children's.
    assert page(top["id"]) == (["dress", "shirt"], 2)
    # Two are the union…
    assert page(top["id"], other["id"]) == (["bob_cut", "dress", "shirt"], 3)
    # …and a category picked WITH one inside it lists each entry once.
    assert page(top["id"], sub["id"]) == (["dress", "shirt"], 2)
    # `subtree=false` is the browse tree's reading, per category.
    assert page(top["id"], subtree=False) == (["dress"], 1)
    # Nothing picked is still the whole set.
    assert page() == (["bob_cut", "dress", "loose_one", "shirt"], 4)


def _item(c) -> int:
    from media_compost.db import Item
    from sqlalchemy import insert, select
    with c.lib.db.session() as s:
        s.execute(insert(Item), [{"uid": "sy1", "name": "i1", "kind": "image"}])
        s.commit()
        return s.execute(select(Item.id)).scalars().first()


def test_a_row_says_which_of_its_implications_the_library_has_not_acted_on(client):
    """The door mints a set's implications once, when it CREATES the tag —
    so a tag the library already had, and an entry edited after its tag was
    in use, both say something the library never hears. The list shows the
    difference rather than drawing advice as though it were fact."""
    c = client
    ts = _import(c)
    sid = ts["id"]
    entry = c.get(f"/api/tag-sets/{sid}/entries?q=ball_gag").json()["rows"][0]

    # NOTHING IS MISSING WHILE THE LIBRARY HAS NEVER HEARD OF THE TAG: an
    # unassigned name is not behind, it is unassigned.
    c.patch(f"/api/tag-sets/{sid}/entries/{entry['id']}", json={"implies": ["bondage"]})
    row = c.get(f"/api/tag-sets/{sid}/entries?q=ball_gag").json()["rows"][0]
    assert row["implies"] == ["bondage"] and row["missing_implies"] == []

    # Made by hand, so the door never spoke for it — now it is behind.
    c.post("/api/tags", json={"name": "ball_gag"})
    row = c.get(f"/api/tag-sets/{sid}/entries?q=ball_gag").json()["rows"][0]
    assert row["missing_implies"] == ["bondage"]

    # A CHAIN COUNTS: the library entails it, and how is not the set's
    # business. `ball_gag → rope → bondage` answers the entry's `bondage`.
    c.post("/api/tags", json={"name": "bondage"})
    c.post("/api/tags", json={"name": "rope", "implies": "bondage"})
    tag = {t["name"]: t for t in c.get("/api/tags").json()}["ball_gag"]
    c.post(f"/api/tags/{tag['id']}/implies", json={"name": "rope"})
    row = c.get(f"/api/tag-sets/{sid}/entries?q=ball_gag").json()["rows"][0]
    assert row["implies"] == ["bondage"] and row["missing_implies"] == []


def test_syncing_implications_appends_or_replaces_and_reverts(client):
    """The verb the door does not have. APPEND adds what the sets say and
    leaves the rest of a tag's implications alone; REPLACE makes them exactly
    what the sets say. Both are the ordinary logged primitives, so a sync
    undoes."""
    c = client
    ts = _import(c)
    sid = ts["id"]
    entry = c.get(f"/api/tag-sets/{sid}/entries?q=ball_gag").json()["rows"][0]
    c.patch(f"/api/tag-sets/{sid}/entries/{entry['id']}", json={"implies": ["bondage"]})
    # By hand, so the set never got its say — and with an implication of its
    # own that is nobody's business but the person's.
    c.post("/api/tags", json={"name": "leather"})
    c.post("/api/tags", json={"name": "ball_gag", "implies": "leather"})

    r = c.post(f"/api/tag-sets/{sid}/entries/sync",
               json={"entry_ids": [entry["id"]], "mode": "append"})
    assert r.status_code == 200, r.text
    assert r.json() == {"tags": 1, "added": 1, "removed": 0, "skipped": 0}
    by = {t["name"]: t for t in c.get("/api/tags").json()}
    assert sorted(by["ball_gag"]["implies"]) == ["bondage", "leather"]
    row = c.get(f"/api/tag-sets/{sid}/entries?q=ball_gag").json()["rows"][0]
    assert row["missing_implies"] == []

    # REPLACE drops what the sets do not name.
    r = c.post(f"/api/tag-sets/{sid}/entries/sync",
               json={"entry_ids": [entry["id"]], "mode": "replace"})
    assert r.json() == {"tags": 1, "added": 0, "removed": 1, "skipped": 0}
    by = {t["name"]: t for t in c.get("/api/tags").json()}
    assert by["ball_gag"]["implies"] == ["bondage"]

    # Every edge it wrote is an ordinary event, and reverting takes it back.
    ev = next(e for e in c.get("/api/history?limit=20").json()["events"]
              if e["action"] == "remove_tag_implication")
    assert c.post("/api/history/revert", json={"event_ids": [ev["id"]]}).json()["reverted"]
    by = {t["name"]: t for t in c.get("/api/tags").json()}
    assert sorted(by["ball_gag"]["implies"]) == ["bondage", "leather"]


def test_a_sync_skips_a_name_the_library_does_not_have(client):
    """A sync never MINTS the tag: an unassigned entry is not out of sync
    with anything, and a set of 17,000 names would otherwise be a way to
    fill the catalog by accident. Nor does an entry the sets say nothing
    about, which under REPLACE would read as "remove everything"."""
    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]
    # THE ENTRIES, not the spellings beside them: a spelling has no advice
    # of its own — it is a name for the tag its entry is about — so a sync
    # over a selection holding one simply passes it by.
    ids = [r["id"] for r in rows if not r["alias_of"]]
    entry = next(r for r in rows if r["name"] == "ball_gag")
    c.patch(f"/api/tag-sets/{sid}/entries/{entry['id']}", json={"implies": ["bondage"]})

    r = c.post(f"/api/tag-sets/{sid}/entries/sync",
               json={"entry_ids": ids, "mode": "replace"}).json()
    assert r == {"tags": 0, "added": 0, "removed": 0, "skipped": len(ids)}
    assert c.get("/api/tags").json() == []

    # `zebra` has a hand-made tag and no `implies` in the set: REPLACE must
    # not read the set's silence as an instruction to empty it.
    c.post("/api/tags", json={"name": "stripes"})
    c.post("/api/tags", json={"name": "zebra", "implies": "stripes"})
    r = c.post(f"/api/tag-sets/{sid}/entries/sync",
               json={"entry_ids": ids, "mode": "replace"}).json()
    assert r["tags"] == 0 and r["removed"] == 0
    assert {t["name"]: t["implies"] for t in c.get("/api/tags").json()}["zebra"] \
        == ["stripes"]


def test_an_id_from_another_set_is_not_synced(client):
    """The path names the set, so a stale selection cannot reach across it."""
    c = client
    ts = _import(c)
    other = c.post("/api/tag-sets", json={"name": "Other", "key": "other"}).json()
    entry = c.get(f"/api/tag-sets/{ts['id']}/entries?q=ball_gag").json()["rows"][0]
    r = c.post(f"/api/tag-sets/{other['id']}/entries/sync",
               json={"entry_ids": [entry["id"]], "mode": "append"}).json()
    assert r == {"tags": 0, "added": 0, "removed": 0, "skipped": 0}


def test_the_filter_lists_only_what_the_library_is_behind_on(client):
    """One narrowing here is a question about the LIBRARY, not the set: which
    entries say something it has not acted on. In a 17,000-entry dump the
    eleven rows out of step are unfindable without it."""
    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = {r["name"]: r for r in c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]}
    c.patch(f"/api/tag-sets/{sid}/entries/{rows['ball_gag']['id']}",
            json={"implies": ["bondage"]})
    c.patch(f"/api/tag-sets/{sid}/entries/{rows['zebra']['id']}",
            json={"implies": ["stripes"]})

    def behind():
        return [r["name"] for r in c.get(
            f"/api/tag-sets/{sid}/entries?behind=true").json()["rows"]]

    # Nothing is behind while the library has neither tag.
    assert behind() == []
    # NOR WITH ONLY ONE OF THEM (owner decision, 2026-09): an entry whose
    # implied name the library has never heard of is saying something about
    # a tag nobody uses, and syncing it mints that tag — a way to fill the
    # catalog from a 17,000-entry dump rather than a repair. The ROW still
    # strikes the name through, since the library really does not entail it.
    c.post("/api/tags", json={"name": "ball_gag"})
    assert behind() == []
    row = c.get(f"/api/tag-sets/{sid}/entries?q=ball_gag").json()["rows"][0]
    assert row["missing_implies"] == ["bondage"]

    c.post("/api/tags", json={"name": "bondage"})
    assert behind() == ["ball_gag"]

    # Syncing it takes it out of the list; the entry with no library tag was
    # never in it.
    c.post(f"/api/tag-sets/{sid}/entries/sync",
           json={"entry_ids": [rows["ball_gag"]["id"]], "mode": "append"})
    assert behind() == []

    # The narrowing is the page's, so `locate` answers about the same list.
    c.post("/api/tags", json={"name": "stripes"})
    c.post("/api/tags", json={"name": "zebra"})
    assert behind() == ["zebra"]
    hit = c.get(f"/api/tag-sets/{sid}/entries/locate?name=zebra&behind=true").json()
    assert hit["index"] == 0
    assert c.get(f"/api/tag-sets/{sid}/entries/locate"
                 "?name=ball_gag&behind=true").json()["index"] is None


# ---- what the Sets tab COSTS ------------------------------------------------
#
# Two bugs in one week, both of the same kind: a read the tab makes on every
# page grew with the LIBRARY rather than with the page. Neither showed on a
# small library and neither was wrong — only slow — so the tripwires here are
# the two things that CAN see them, statement COUNT and query PLAN, and they
# run in the ordinary suite rather than behind `-m perf`.


def _statements(lib, f):
    """Every SQL statement `f()` issues, as (sql, parameters) — the text so a
    plan can be asked for it, the parameters because EXPLAIN needs them
    bound like any other execution."""
    from sqlalchemy import event

    seen: list[tuple[str, object]] = []

    def note(_conn, _cur, sql, params, *_a):
        seen.append((sql, params))

    event.listen(lib.db.engine, "before_cursor_execute", note)
    try:
        f()
    finally:
        event.remove(lib.db.engine, "before_cursor_execute", note)
    return seen


def _noise(c, tags: int, edges: int) -> None:
    """A library that has grown behind the page's back: tags the set never
    mentions, and implications between them."""
    from sqlalchemy import insert, select

    from media_compost.db import Tag, TagImplication

    with c.lib.db.session() as s:
        base = s.execute(select(Tag.id)).scalars().all()
        s.execute(insert(Tag), [{"name": f"noise_{len(base)}_{i}"}
                                for i in range(tags)])
        s.commit()
        ids = [t for (t,) in s.execute(
            select(Tag.id).where(Tag.name.like("noise_%"))).all()]
        s.execute(insert(TagImplication),
                  [{"tag_id": ids[i * 2], "implies_id": ids[i * 2 + 1]}
                   for i in range(min(edges, len(ids) // 2))])
        s.commit()


def test_a_page_costs_the_page_not_the_library(client):
    """LISTING COSTS A PAGE, NEVER THE LIBRARY. `missing_implications` used
    to close the WHOLE implication table transitively — 530 ms of a 615 ms
    page on a library of 200,000 tags, every millisecond of it about tags the
    page does not mention. The walk starts at the page's own tags now, so the
    statement count is flat in everything the page did not ask about."""
    from media_compost.ops import tagsets as ops

    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]
    c.patch(f"/api/tag-sets/{sid}/entries/{rows[0]['id']}", json={"implies": ["bondage"]})
    c.post("/api/tags", json={"name": rows[0]["name"]})

    def page_cost() -> int:
        with c.lib.db.session() as s:
            page, _ = ops.entries_page(s, sid, limit=200)
            return len(_statements(c.lib, lambda: ops.missing_implications(s, page)))

    small = page_cost()
    _noise(c, 800, 400)
    assert page_cost() == small


def test_the_filter_costs_the_candidates_not_the_set(client):
    """The "behind the library" filter is the one read here that is about the
    whole set, and even it must not walk the whole set: what it refines is
    the entries the library HAS NAMES FOR, which on a booru dump is a few
    hundred of seventeen thousand."""
    from media_compost.ops import tagsets as ops

    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]
    c.patch(f"/api/tag-sets/{sid}/entries/{rows[0]['id']}", json={"implies": ["bondage"]})
    c.post("/api/tags", json={"name": rows[0]["name"]})
    c.post("/api/tags", json={"name": "bondage"})

    def filter_cost() -> int:
        with c.lib.db.session() as s:
            return len(_statements(c.lib, lambda: ops.behind_entry_ids(s, sid)))

    small = filter_cost()
    # Two hundred more entries, none of them a name the library has.
    c.post(f"/api/tag-sets/{sid}/entries/bulk", json={
        "rows": [{"name": f"unheard_of_{i}", "implies": ["bondage"]}
                 for i in range(200)]})
    assert filter_cost() == small


def test_nothing_the_sets_tab_reads_scans_the_tags_table(client):
    """The plan, which is the only thing that can see the second bug: the
    filter's candidate clause was `lname IN (SELECT lower(name) FROM tags)`,
    and SQLite has no index to match a column against another table's
    computed column — 8.4 of 8.5 seconds on 17,000 entries against 6,000
    tags, answering correctly the whole time. Every statement either path
    issues against `tags` or `tag_implications` has to be a SEARCH."""
    from media_compost.ops import tagsets as ops

    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]
    for r in rows:
        c.patch(f"/api/tag-sets/{sid}/entries/{r['id']}", json={"implies": ["bondage"]})
        c.post("/api/tags", json={"name": r["name"]})
    c.post("/api/tags", json={"name": "bondage"})

    with c.lib.db.session() as s:
        page, _ = ops.entries_page(s, sid, limit=200)
        sql = _statements(c.lib, lambda: ops.missing_implications(s, page))
        sql += _statements(c.lib, lambda: ops.behind_entry_ids(s, sid))
    conn = c.lib.db.engine.raw_connection()
    try:
        cur = conn.cursor()
        for q, params in sql:
            if not q.lstrip().upper().startswith("SELECT"):
                continue
            cur.execute("EXPLAIN QUERY PLAN " + q, params)
            for step in [r[-1] for r in cur.fetchall()]:
                assert not step.startswith("SCAN tags"), (step, q)
                assert not step.startswith("SCAN tag_implications"), (step, q)
    finally:
        conn.close()


def test_a_row_can_put_its_tag_in_the_library_through_the_door(client):
    """A set is advice ABOUT tags, and until the tag exists there is nothing
    for the advice to be about — so a row the library has never heard of
    offers to make it real rather than offering to do anything about its
    implications.

    Through the DOOR, which is the whole point: the tag arrives with what its
    set says about it. Adding it any other way would produce a bare tag the
    same row then reports as behind.
    """
    from sqlalchemy import select

    from media_compost.db import Tag

    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = {r["name"]: r for r in c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]}
    assert all(not r["in_library"] for r in rows.values())
    c.patch(f"/api/tag-sets/{sid}/entries/{rows['ball_gag']['id']}",
            json={"implies": ["bondage"]})

    r = c.post(f"/api/tag-sets/{sid}/entries/add-to-library",
               json={"entry_ids": [rows["ball_gag"]["id"]]})
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 1, "skipped": 0}

    # The row now says the library has it — and the implication came WITH it,
    # so there is nothing to sync.
    back = {x["name"]: x for x in
            c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]}
    assert back["ball_gag"]["in_library"] is True
    assert back["ball_gag"]["missing_implies"] == []
    with c.lib.db.session() as s:
        names = {t for (t,) in s.execute(select(Tag.name)).all()}
    assert {"ball_gag", "bondage"} <= names

    # Asking again is not an error: over a selection, "some are already
    # there" is the ordinary case.
    again = c.post(f"/api/tag-sets/{sid}/entries/add-to-library",
                   json={"entry_ids": [rows["ball_gag"]["id"]]})
    assert again.json() == {"added": 0, "skipped": 1}

    # And it is in History, unlike the door's usual implicit creation: here
    # the creation IS the action.
    events = c.get("/api/history").json()["events"]
    assert any(e["action"] == "create_tag" for e in events[:4])


def test_an_alias_name_adds_the_canonical_tag(client):
    """The door's own redirect: a name an enabled set calls an alias creates
    the tag it points at, never the alias itself."""
    from sqlalchemy import select

    from media_compost.db import Tag

    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = {r["name"]: r for r in c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]}
    c.post(f"/api/tag-sets/{sid}/entries/add-to-library",
           json={"entry_ids": [rows["ball_gag"]["id"]]})
    with c.lib.db.session() as s:
        names = {t for (t,) in s.execute(select(Tag.name)).all()}
    assert "ball_gag" in names and "ballgag" not in names
    # …and asking for the ALIAS by name lands on the same tag, never on a
    # second one under the alias's spelling.
    from media_compost.ops import Ctx, tagcatalog
    with c.lib.db.session() as s:
        tag = tagcatalog.get_or_create(Ctx(session=s, source="test"), "ballgag")
        s.commit()
        assert tag.name == "ball_gag"


def test_select_all_is_every_row_the_list_holds(client):
    """The header's checkbox means every row in the LIST, not every row that
    happens to be loaded — the list is server-paged and windowed, so on a set
    of seventeen thousand it was picking the two hundred in hand. The client
    needs the id list to say that, and it is the page's own narrowing and
    order with one column selected."""
    c = client
    ts = _import(c)
    sid = ts["id"]

    def ids(**q):
        p = "&".join(f"{k}={v}" for k, v in q.items())
        return c.get(f"/api/tag-sets/{sid}/entries/ids?{p}").json()["ids"]

    page = c.get(f"/api/tag-sets/{sid}/entries?limit=2").json()
    # SIX rows: four entries and the two spellings, which are rows of the
    # list and are picked, ranged over and acted on like any other.
    assert page["total"] == 6 and len(page["rows"]) == 2
    # …and the ids are ALL of them, not the page's.
    assert len(ids()) == 6

    # The SAME order the page reads in, so a shift-range between two rows
    # means the run the eye saw.
    by_name = ids(sort="name")
    rows = c.get(f"/api/tag-sets/{sid}/entries?sort=name&limit=200").json()["rows"]
    assert by_name == [r["id"] for r in rows]

    # And the same narrowing: what the list is showing is what "all" is.
    # ball_gag, balloon_animal, ball
    assert len(ids(q="ball")) == 4   # …and `ballgag`, a name like any other
    assert ids(q="zebra") == [r["id"] for r in rows if r["name"] == "zebra"]


RECORD_DOC = {
    "format": "media-compost-tag-set", "format_version": 1,
    "name": "Who and where",
    "entries": [
        {"name": "alice", "comment": "the protagonist",
         "subject": {"name": "Alice", "since": 19990715}},
        {"name": "tokyo", "place": {"name": "Tokyo, Japan"}},
        {"name": "shibuya", "place": {"name": "Shibuya, Tokyo",
                                      "lat": 35.66, "lon": 139.7,
                                      "parent": "tokyo"}},
        {"name": "c101", "event": {"name": "Comiket 101", "start": 20221230,
                                   "end": 20221231}},
        {"name": "bob", "subject": {}},
    ],
}


def _records(c) -> dict:
    r = c.post("/api/tag-sets/import",
               json={"document": RECORD_DOC, "mode": "create"})
    assert r.status_code == 200, r.text
    return r.json()["set"]


def test_a_set_says_what_the_tag_IS_and_the_file_round_trips_it(client):
    """A tag set knows things the library has to be told twice otherwise:
    that this name is a person, that one a place inside another. It travels
    in the file, and an EMPTY record is a record — "somebody" is the whole
    of what a set often knows."""
    c = client
    ts = _records(c)
    assert json.loads(c.get(f"/api/tag-sets/{ts['id']}/export").text) == RECORD_DOC
    rows = {r["name"]: r for r in
            c.get(f"/api/tag-sets/{ts['id']}/entries").json()["rows"]}
    assert rows["alice"]["comment"] == "the protagonist"
    assert rows["alice"]["subject"] == {"name": "Alice", "since": 19990715}
    assert rows["bob"]["subject"] == {"name": "", "since": None}, \
        "an empty record still says the kind"
    assert rows["tokyo"]["place"]["name"] == "Tokyo, Japan"
    assert rows["c101"]["event"]["end"] == 20221231
    assert rows["tokyo"]["subject"] is None


def test_the_door_writes_the_record_the_first_time_the_name_is_assigned(client):
    """The set's one moment: `get_or_create` CREATES the tag, and what the
    set says the tag IS goes in with it — as ordinary records, each logged
    and each revertible."""
    c = client
    _records(c)
    lib = c.lib
    from media_compost.db import Location, Occasion, Subject, Tag
    from media_compost.ops import Ctx, tagcatalog
    from sqlalchemy import select

    with lib.db.session() as s:
        ctx = Ctx(session=s, _store=lib.store, _config=lib.config, source="cli")
        tagcatalog.get_or_create(ctx, "alice")
        tagcatalog.get_or_create(ctx, "tokyo")
        tagcatalog.get_or_create(ctx, "shibuya")
        tagcatalog.get_or_create(ctx, "c101")
        s.commit()
        sub = s.execute(select(Subject)).scalars().one()
        assert sub.display_name == "Alice" and sub.since_date == 19990715
        assert s.execute(select(Tag).where(Tag.name == "alice")
                         ).scalars().one().comment == "the protagonist"
        places = {p.name: p for p in s.execute(select(Location)).scalars()}
        assert set(places) == {"Tokyo, Japan", "Shibuya, Tokyo"}
        # THE PARENT IS THE OTHER PLACE'S ROW — and containment is an
        # implication between the identity tags, so assigning the child
        # assigns the parent.
        assert places["Shibuya, Tokyo"].parent_id == places["Tokyo, Japan"].id
        assert places["Shibuya, Tokyo"].lat == 35.66
        occ = s.execute(select(Occasion)).scalars().one()
        assert occ.display_name == "Comiket 101" and occ.start_date == 20221230


def test_a_tag_the_library_already_had_is_behind_until_the_sync(client):
    """The door speaks ONCE. A tag that was there first says nothing the set
    says — the row says so, the filter finds it, and the verb writes it."""
    c = client
    ts = _records(c)
    sid = ts["id"]
    lib = c.lib
    from media_compost.db import Subject
    from media_compost.ops import Ctx, tagcatalog
    from sqlalchemy import select

    with lib.db.session() as s:
        ctx = Ctx(session=s, _store=lib.store, _config=lib.config, source="cli")
        tagcatalog.create(ctx, "alice")      # the explicit Create takes no advice
        s.commit()
    rows = {r["name"]: r for r in
            c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]}
    assert rows["alice"]["in_library"] is True
    assert set(rows["alice"]["missing_records"]) == {"comment", "subject"}
    # A name the library has never heard of is UNASSIGNED, not behind.
    assert rows["tokyo"]["missing_records"] == []

    # The filter narrows to exactly that row.
    got = c.get(f"/api/tag-sets/{sid}/entries?behind_records=true").json()
    assert [r["name"] for r in got["rows"]] == ["alice"]

    # …and the verb closes it.
    r = c.post(f"/api/tag-sets/{sid}/entries/sync",
               json={"entry_ids": [rows["alice"]["id"]], "mode": "append"})
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == 1 and r.json()["added"] == 2
    with lib.db.session() as s:
        assert s.execute(select(Subject)).scalars().one().display_name == "Alice"
    after = {r["name"]: r for r in
             c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]}
    assert after["alice"]["missing_records"] == []
    assert c.get(f"/api/tag-sets/{sid}/entries?behind_records=true"
                 ).json()["total"] == 0


def test_what_the_library_already_says_wins(client):
    """A set is advice. A tag that carries a comment is not re-described,
    and one that is already somebody is not made into a second person."""
    c = client
    ts = _records(c)
    lib = c.lib
    from media_compost.db import Subject, Tag
    from media_compost.ops import Ctx, tagcatalog
    from sqlalchemy import select

    with lib.db.session() as s:
        ctx = Ctx(session=s, _store=lib.store, _config=lib.config, source="cli")
        tag, _alias, _imp = tagcatalog.create(ctx, "alice", comment="mine")
        s.commit()
        n = tagcatalog.sync_set_records(ctx, ["alice"])
        s.commit()
        assert n["written"] == 1, "the subject only — the comment stood"
        assert s.get(Tag, tag.id).comment == "mine"
        # …and REPLACE is the override, spelled out.
        tagcatalog.sync_set_records(ctx, ["alice"], replace=True)
        s.commit()
        assert s.get(Tag, tag.id).comment == "the protagonist"
        assert s.execute(select(Subject)).scalars().one().display_name == "Alice"


def test_a_record_and_its_edit_revert(client):
    """Every write here is an ordinary logged event, records included — the
    entry editor's, so an edit that added a place takes it back."""
    c = client
    ts = _records(c)
    sid = ts["id"]
    eid = next(r["id"] for r in
               c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]
               if r["name"] == "bob")
    r = c.patch(f"/api/tag-sets/{sid}/entries/{eid}", json={
        "records": {"kinds": ["subject", "place"], "subject": None,
                    "place": {"name": "Bob's house"}}})
    assert r.status_code == 200, r.text
    assert r.json()["subject"] is None
    assert r.json()["place"]["name"] == "Bob's house"
    ev = c.get("/api/history?limit=5").json()
    events = ev["events"] if isinstance(ev, dict) else ev
    last = events[0]
    assert c.post("/api/history/revert",
                  json={"event_ids": [last["id"]]}).status_code == 200
    back = next(x for x in c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]
                if x["id"] == eid)
    assert back["place"] is None and back["subject"] == {"name": "", "since": None}


def test_the_door_builds_the_whole_hierarchy_above_a_place(client):
    """Shibuya is in Tokyo. Assigning `shibuya` for the first time makes the
    place AND the one it is inside — a place standing in nothing is not what
    the set said — and the containment is the ordinary implication between
    the identity tags, so assigning the child assigns the parent."""
    c = client
    _records(c)
    lib = c.lib
    from media_compost.db import Location, Tag
    from media_compost.ops import Ctx, tagcatalog
    from sqlalchemy import select

    with lib.db.session() as s:
        ctx = Ctx(session=s, _store=lib.store, _config=lib.config, source="cli")
        tagcatalog.get_or_create(ctx, "shibuya")
        s.commit()
        places = {p.name: p for p in s.execute(select(Location)).scalars()}
        assert set(places) == {"Shibuya, Tokyo", "Tokyo, Japan"}, \
            "the parent was minted with the child"
        assert places["Shibuya, Tokyo"].parent_id == places["Tokyo, Japan"].id
        assert s.execute(select(Tag).where(Tag.name == "tokyo")
                         ).scalars().first() is not None


def test_a_BULK_sync_leaves_the_hierarchy_to_its_own_verb(client):
    """Following a parent MINTS that tag and its own parent above it, which
    over a selection of four hundred rows fills the catalog rather than
    describing what was picked. So the ordinary sync writes the record and
    stops; the parent is a second, separately chosen verb."""
    c = client
    ts = _records(c)
    sid = ts["id"]
    lib = c.lib
    from media_compost.db import Location
    from media_compost.ops import Ctx, tagcatalog
    from sqlalchemy import select

    with lib.db.session() as s:
        ctx = Ctx(session=s, _store=lib.store, _config=lib.config, source="cli")
        tagcatalog.create(ctx, "shibuya")   # the tag was there FIRST
        s.commit()
    eid = next(r["id"] for r in
               c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]
               if r["name"] == "shibuya")
    assert c.post(f"/api/tag-sets/{sid}/entries/sync",
                  json={"entry_ids": [eid], "mode": "append"}
                  ).status_code == 200
    with lib.db.session() as s:
        places = {p.name: p for p in s.execute(select(Location)).scalars()}
        assert set(places) == {"Shibuya, Tokyo"}, "no tokyo yet"
        assert places["Shibuya, Tokyo"].parent_id is None
    # …and the verb that DOES build it.
    r = c.post(f"/api/tag-sets/{sid}/entries/sync-parents",
               json={"entry_ids": [eid], "mode": "append"})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1
    with lib.db.session() as s:
        places = {p.name: p for p in s.execute(select(Location)).scalars()}
        assert set(places) == {"Shibuya, Tokyo", "Tokyo, Japan"}
        assert places["Shibuya, Tokyo"].parent_id == places["Tokyo, Japan"].id


def test_a_ring_of_parents_loses_the_edge_furthest_from_the_ask(client):
    """A set that says a is in b and b is in a cannot be followed all the
    way round. The walk starts at the name that was assigned and drops the
    edge back to it — the implication minting's rule, one kind of advice
    along, and the reason it does not simply recurse for ever."""
    c = client
    r = c.post("/api/tag-sets/import", json={"mode": "create", "document": {
        "format": "media-compost-tag-set", "name": "Ring",
        "entries": [
            {"name": "aa", "place": {"name": "A", "parent": "bb"}},
            {"name": "bb", "place": {"name": "B", "parent": "aa"}},
        ]}})
    assert r.status_code == 200, r.text
    lib = c.lib
    from media_compost.db import Location
    from media_compost.ops import Ctx, tagcatalog
    from sqlalchemy import select

    with lib.db.session() as s:
        ctx = Ctx(session=s, _store=lib.store, _config=lib.config, source="cli")
        tagcatalog.get_or_create(ctx, "aa")
        s.commit()
        places = {p.name: p for p in s.execute(select(Location)).scalars()}
        assert set(places) == {"A", "B"}
        assert places["A"].parent_id == places["B"].id
        assert places["B"].parent_id is None, "the edge back to the ask"


def test_the_list_narrows_to_a_KIND_and_the_sidebar_counts_them(client):
    """A tag set of people is read as people. The set says how many of
    its names are a subject, a place, an event — which is what decides
    whether the sidebar draws a row for each — and the list narrows to any
    combination of them, several being the UNION."""
    c = client
    ts = _records(c)
    sid = ts["id"]
    assert c.get(f"/api/tag-sets/{sid}").json()["record_counts"] == {
        "subject": 2, "place": 2, "event": 1}

    def names(**q):
        p = "&".join(f"{k}={v}" for k, v in q.items())
        return sorted(r["name"] for r in
                      c.get(f"/api/tag-sets/{sid}/entries?{p}").json()["rows"])

    assert names(record="subject") == ["alice", "bob"]
    assert names(record="place") == ["shibuya", "tokyo"]
    assert names(record="event") == ["c101"]
    # SEVERAL IS THE UNION — "subjects and events", not the empty list of
    # entries that are both.
    r = c.get(f"/api/tag-sets/{sid}/entries?record=subject&record=event")
    assert sorted(x["name"] for x in r.json()["rows"]) == ["alice", "bob", "c101"]
    # …and it composes with the other narrowings, like every one of them.
    assert names(record="place", q="shib") == ["shibuya"]


def test_the_popover_is_told_what_the_tag_IS(client):
    """The `?` is often the only place a name is met — a half-typed word in
    a field, a row in an autocomplete — so what the set says the tag IS
    travels with what it says ABOUT it. One shaper (`SetSays.as_dict`), so
    the tags list, the autocomplete and `/describe` cannot disagree."""
    c = client
    _records(c)
    got = c.get("/api/tag-sets/describe?names=alice,tokyo,bob").json()
    alice = got["alice"]["descriptions"][0]
    assert alice["comment"] == "the protagonist"
    assert alice["subject"] == {"name": "Alice", "since": 19990715}
    assert alice["place"] is None
    assert got["tokyo"]["descriptions"][0]["place"]["name"] == "Tokyo, Japan"
    # An EMPTY record still says the kind, which is the whole point of it.
    assert got["bob"]["descriptions"][0]["subject"] == {"name": "",
                                                        "since": None}


def test_a_sets_names_are_in_the_tags_table_and_out_of_every_library_read(client):
    """ONE TABLE, TWO TAG SETS (owner 2026-09).

    A set's entries are `tags` rows now — with `tag_set_id` filled in and the
    `kind` discriminator the three mapped classes are keyed on — and the
    whole point of that discriminator is that nothing had to be told: the
    catalog, the counts, the search and the autocomplete's library half all
    mean the LIBRARY's own names, in queries that say nothing about sets.

    So this asks it from both ends: the rows are really there, and none of
    them shows up anywhere a library tag is listed.
    """
    from sqlalchemy import func, select

    from media_compost.db import Tag, TagRow, TagSetEntry

    c = client
    _import(c)
    c.post("/api/tags", json={"name": "ball"})   # the library has one too

    with c.lib.db.session() as s:
        # ONE TABLE: the set's four entries and its two aliases are rows of
        # `tags`, and the library's one name is the only row with no set.
        assert s.execute(select(func.count()).select_from(TagRow)).scalar() == 7
        assert s.execute(select(func.count()).select_from(TagSetEntry)).scalar() == 6
        # …and `select(Tag)` — every read in the app — sees the library's.
        assert [t.name for t in s.execute(select(Tag)).scalars()] == ["ball"]
        assert s.execute(select(func.count()).select_from(Tag)).scalar() == 1

    # The Tags tab's own list: one row, and its count says one.
    index = c.get("/api/tags/index").json()
    assert index["names"] == ["ball"] and index["total"] == 1
    assert c.get("/api/library/stats").json()["tags"] == 1

    # The autocomplete offers both, and says which is which: the library's
    # row is the library's, `zebra` is the set's and creates on assignment.
    rows = {r["name"]: r for r in _names(c, "z")}
    assert rows["zebra"]["tag_sets"] and rows["zebra"]["positive"] == 0

    # And the set's own list holds its entries and not the library's.
    ts = [r for r in c.get("/api/tag-sets").json() if not r["library"]][0]
    got = c.get(f"/api/tag-sets/{ts['id']}/entries").json()
    assert sorted(r["name"] for r in got["rows"]) == [
        "ball", "ball_gag", "ballgag", "balloon_animal", "zeb", "zebra"]
    assert got["total"] == 6


# ---------------------------------------------------------------------------
# A TAG SET'S OWN META TAGS
# ---------------------------------------------------------------------------

META_DOC = {
    "format": "media-compost-tag-set", "format_version": 1,
    "name": "Labelled", "description": "a set that labels its names",
    "meta_tags": [{"name": "character", "comment": "this name is somebody",
                   "description": "…at length"}],
    "entries": [
        {"name": "hatsune_miku", "meta": ["character", "vocaloid"]},
        {"name": "solo"},
    ],
}


def _import_meta(c) -> dict:
    r = c.post("/api/tag-sets/import",
               json={"document": META_DOC, "mode": "create"})
    assert r.status_code == 200, r.text
    return r.json()["set"]


def test_a_sets_meta_tags_are_its_own_and_the_librarys_are_the_librarys(client):
    """ONE TABLE, AND THE KIND IS NOT THE TAG SET.

    `select(Tag)` and `select(TagSetEntry)` scope themselves — their
    discriminator IS the tag set — but a meta tag's does not: a set
    carries the labels it puts on its names, and the LIBRARY's meta
    namespace is what the four carriers read. So the set's label is a row
    with the set's id, and nothing that means the library's own sees it.
    """
    c = client
    ts = _import_meta(c)
    rows = c.get(f"/api/tag-sets/{ts['id']}/meta-tags").json()
    # The file's row carries the words; the entry-only name was MADE, as a
    # category trail an entry names is made.
    assert [(r["name"], r["comment"], r["uses"]) for r in rows] == [
        ("character", "this name is somebody", 1), ("vocaloid", "", 1)]
    assert rows[0]["description"] == "…at length"
    # …and the library's namespace has heard nothing.
    assert c.get("/api/link-tags/rows").json() == []
    assert c.get("/api/link-tags").json() == []


def test_a_sets_meta_tags_are_not_entries_of_it(client):
    """A LABEL IS NOT A NAME THE SET OFFERS. The rows are `tags` rows of the
    set like its entries, so the one thing that had to be true is that every
    read of the entries says which kind it means — which the discriminator
    does by itself."""
    c = client
    ts = _import_meta(c)
    page = c.get(f"/api/tag-sets/{ts['id']}/entries?per=100").json()
    assert [r["name"] for r in page["rows"]] == ["hatsune_miku", "solo"]
    assert page["total"] == 2
    assert c.get("/api/tag-sets").json()
    detail = c.get(f"/api/tag-sets/{ts['id']}").json()
    assert detail["entries"] == 2
    # And they are not offered as tags either.
    assert not [r for r in _names(c, "charact") if r["name"] == "character"]


def test_the_door_puts_what_the_set_says_the_name_is_labelled_with(client):
    """A set that knows `hatsune_miku` is a `character` is saying something
    about the NAME — so the door says it once, when it CREATES the tag, and
    the label arrives in the LIBRARY's meta namespace with the set's words
    for it."""
    c = client
    ts = _import_meta(c)
    rows = c.get(f"/api/tag-sets/{ts['id']}/entries?per=100").json()["rows"]
    # "Add to library" goes through the DOOR, unlike the Tags tab's explicit
    # Create, which is exactly what the two verbs mean.
    r = c.post(f"/api/tag-sets/{ts['id']}/entries/add-to-library",
               json={"entry_ids": [rows[0]["id"]]})
    assert r.status_code == 200, r.text
    miku = [t for t in c.get("/api/tags").json()
            if t["name"] == "hatsune_miku"][0]
    assert sorted(miku["meta_tags"]) == ["character", "vocaloid"]
    lib_meta = {m["name"]: m for m in c.get("/api/link-tags/rows").json()}
    assert lib_meta["character"]["comment"] == "this name is somebody"
    assert lib_meta["character"]["description"] == "…at length"
    # A tag the library ALREADY had hears nothing — the rule everywhere a
    # set meets an answer that is already there.
    c.post("/api/tags", json={"name": "solo"})
    solo = [t for t in c.get("/api/tags").json() if t["name"] == "solo"][0]
    assert solo["meta_tags"] == []


def test_a_label_travels_in_the_file_both_ways(client):
    c = client
    ts = _import_meta(c)
    doc = c.get(f"/api/tag-sets/{ts['id']}/export").json()
    assert doc["meta_tags"] == [{"name": "character",
                                 "comment": "this name is somebody",
                                 "description": "…at length"}]
    assert doc["entries"][0]["meta"] == ["character", "vocaloid"]
    # A label with nothing to say rides on the entries alone — writing a row
    # for it as well would be the file saying the same thing twice.
    assert "vocaloid" not in [m["name"] for m in doc["meta_tags"]]
    again = c.post("/api/tag-sets/import",
                   json={"document": doc | {"name": "Labelled again"},
                         "mode": "create"})
    assert again.status_code == 200, again.text
    copy = again.json()["set"]["id"]
    assert c.get(f"/api/tag-sets/{copy}/export").json() \
        == doc | {"name": "Labelled again"}


def test_renaming_a_label_carries_the_entries_that_wear_it(client):
    c = client
    ts = _import_meta(c)
    mid = c.get(f"/api/tag-sets/{ts['id']}/meta-tags").json()[0]["id"]
    r = c.patch(f"/api/tag-sets/{ts['id']}/meta-tags/{mid}",
                json={"name": "person"})
    assert r.status_code == 200, r.text
    page = c.get(f"/api/tag-sets/{ts['id']}/entries?per=100").json()
    assert page["rows"][0]["meta"] == ["person", "vocaloid"]
    assert [m["name"] for m in r.json()] == ["person", "vocaloid"]
    # …and the undo puts both back.
    ev = c.get("/api/history?limit=1").json()["events"][0]
    back = c.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert back.status_code == 200 and back.json()["reverted"] == [ev["id"]], back.text
    page = c.get(f"/api/tag-sets/{ts['id']}/entries?per=100").json()
    assert page["rows"][0]["meta"] == ["character", "vocaloid"]


def test_deleting_a_label_takes_every_claim_to_it_and_the_undo_restores(client):
    """A name nothing in the tag set knows is not advice, it is a typo —
    so the entries' claims go with the row, and the snapshot is what puts
    them back."""
    c = client
    ts = _import_meta(c)
    mid = c.get(f"/api/tag-sets/{ts['id']}/meta-tags").json()[0]["id"]
    r = c.delete(f"/api/tag-sets/{ts['id']}/meta-tags/{mid}")
    assert r.status_code == 200, r.text
    assert [m["name"] for m in r.json()] == ["vocaloid"]
    page = c.get(f"/api/tag-sets/{ts['id']}/entries?per=100").json()
    assert page["rows"][0]["meta"] == ["vocaloid"]
    ev = c.get("/api/history?limit=1").json()["events"][0]
    back = c.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert back.status_code == 200 and back.json()["reverted"] == [ev["id"]], back.text
    page = c.get(f"/api/tag-sets/{ts['id']}/entries?per=100").json()
    # The claims come back as fresh rows, so they land after the ones that
    # stayed — the label is on the entry again, at the end of its list.
    assert sorted(page["rows"][0]["meta"]) == ["character", "vocaloid"]
    assert [m["name"] for m in
            c.get(f"/api/tag-sets/{ts['id']}/meta-tags").json()] \
        == ["character", "vocaloid"]


def test_an_entry_naming_a_label_is_what_makes_it(client):
    """The category trail's rule: what an entry says the tag set knows,
    the tag set knows."""
    c = client
    ts = _import_meta(c)
    eid = c.get(f"/api/tag-sets/{ts['id']}/entries?per=100").json()["rows"][1]["id"]
    r = c.patch(f"/api/tag-sets/{ts['id']}/entries/{eid}",
                json={"meta": ["noflip"]})
    assert r.status_code == 200, r.text
    assert r.json()["meta"] == ["noflip"]
    assert [m["name"] for m in
            c.get(f"/api/tag-sets/{ts['id']}/meta-tags").json()] \
        == ["character", "vocaloid", "noflip"]


def test_the_librarys_own_set_cannot_be_deleted(client):
    """Its rows ARE the library's tags. `TagSetOut.library` has said "not
    deletable" on the wire since the row was invented, and until 2026-09
    nothing under it refused: the Settings list never read the flag, so it
    drew a Delete on that row like any other."""
    # Making a CATEGORY is what brings the lazy library row into being —
    # until then the pill is synthesized at id 0 and there is nothing to ask
    # about.
    client.post("/api/tags", json={"name": "cat"})
    client.post("/api/tags/categories", json={"name": "Animals"})
    rows = client.get("/api/tag-sets").json()
    lib = next(r for r in rows if r.get("library"))
    assert lib["id"] > 0, "the library's row has to exist for this to mean anything"

    r = client.delete(f"/api/tag-sets/{lib['id']}")
    assert r.status_code == 400
    assert r.json()["detail"] == "the library's own tag set cannot be deleted"

    # And it is still there, with its tag.
    assert any(x.get("library") for x in client.get("/api/tag-sets").json())
    assert [t["name"] for t in client.get("/api/tags").json()] == ["cat"]


def _name_seeks(lib, f) -> list[tuple[str, str]]:
    """Every plan step `f()` produces over the two tables a window's reads
    probe BY NAME, as (step, sql).

    `_statements` plus `EXPLAIN QUERY PLAN`, the shape
    `test_nothing_the_sets_tab_reads_scans_the_tags_table` uses — but asking
    a sharper question than "is it a SCAN", because the regression this
    catches was not one. See the test below.
    """
    out: list[tuple[str, str]] = []
    conn = lib.db.engine.raw_connection()
    try:
        cur = conn.cursor()
        for q, params in _statements(lib, f):
            if not q.lstrip().upper().startswith("SELECT"):
                continue
            cur.execute("EXPLAIN QUERY PLAN " + q, params)
            for step in [r[-1] for r in cur.fetchall()]:
                if " tags" in step or " tag_set_implications" in step:
                    out.append((step, q))
    finally:
        conn.close()
    return out


def test_a_window_of_rows_is_sought_by_name_never_by_tag_set(client):
    """WHAT A WINDOW ASKS OF A NAME IS ASKED OF THE NAME.

    Three of the detail band's reads named the tag set beside the names they
    were probing for — `implied_by_for` and `records_for_many` joined
    `tag_sets` and put the enabled ids in the WHERE. SQLite has no
    statistics here and never will, so it took the equality on `tag_set_id`,
    drove from `ix_tags_set` and tested the name per row: on the 132,255-
    entry Characters set that is 1.36 s and 23 ms for two reads a scroll
    step repeats. It is the `_index_rows` category lesson one table along.

    A SCAN is not the tell — the bad plan was a SEARCH, of the whole set,
    with only the FIRST column of a composite index bound
    (`ix_tags_set_lname (tag_set_id=?)`, the name checked per row). So what
    this forbids is the tag set as the only thing sought: a step over these
    two tables may seek a name or an id, and may not seek `tag_set_id`
    alone — nor scan them, which is the coarser failure beside it.
    """
    from media_compost.ops import tagsets as ops

    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]
    names = [r["name"] for r in rows]
    for n in names:
        c.post("/api/tags", json={"name": n})

    with c.lib.db.session() as s:
        lnames = [n.lower() for n in names]
        steps = _name_seeks(c.lib, lambda: ops.descriptions_for(s, lnames))
        steps += _name_seeks(c.lib, lambda: ops.records_for_many(s, names))
        steps += _name_seeks(c.lib,
                             lambda: ops.implied_by_for(s, [sid], lnames))
    assert steps, "the reads issued nothing over the tables they are about"
    for step, sql in steps:
        assert "(tag_set_id=?)" not in step, (step, sql)
        assert not step.startswith("SCAN tags"), (step, sql)
        assert not step.startswith("SCAN tag_set_implications"), (step, sql)


def test_the_popover_says_what_else_in_the_set_entails_the_name(client):
    """`implied_by` — the implication table read BACKWARDS, which is the half
    of "what does this set say about this name" that the name's own entry
    cannot carry.

    Pinned because nothing pinned it: every assertion on a description had an
    empty `implied_by`, so the read could have answered nothing at all and
    the suite would have agreed. It is asked of the names, and the tag set is
    settled afterwards — see
    `test_a_window_of_rows_is_sought_by_name_never_by_tag_set`.
    """
    from media_compost.ops import tagsets as ops

    c = client
    ts = _import(c)
    sid = ts["id"]
    rows = {r["name"]: r for r in c.get(f"/api/tag-sets/{sid}/entries").json()["rows"]}
    c.patch(f"/api/tag-sets/{sid}/entries/{rows['ball_gag']['id']}",
            json={"implies": ["ball"]})
    c.patch(f"/api/tag-sets/{sid}/entries/{rows['balloon_animal']['id']}",
            json={"implies": ["ball"]})

    with c.lib.db.session() as s:
        # Both entries, in the entries' own name order, under the one name.
        assert ops.implied_by_for(s, [sid], ["ball", "zebra"]) == {
            (sid, "ball"): ["ball_gag", "balloon_animal"]}
        # A set nobody asked about answers nothing, even though its rows are
        # the ones the name probe found.
        assert ops.implied_by_for(s, [sid + 99], ["ball"]) == {}
        said = ops.descriptions_for(s, ["ball"])
    assert said["ball"][0].implied_by == ["ball_gag", "balloon_animal"]
