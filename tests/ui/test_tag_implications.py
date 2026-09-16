"""Tag implications (implicit assignment + effective, resolution-aware counts) and
link-tag management, exercised through the HTTP API."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from media_compost.testing import q_tag, search_items


@pytest.fixture
def client(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=True)
        )
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _item_ids(client) -> list[int]:
    return [it["id"] for it in client.get("/api/items").json()["items"]]


def _tag(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_the_catalog_reads_chunk_their_id_lists():
    """`implied_names` and `meta_names` are handed EVERY tag id by the tag
    list, and an `IN` of a whole catalog is not merely inelegant.

    SQLite's variable cap was 32,766 when the chunking rule was written and
    is 250,000 on the SQLite shipping here, so an unsplit list stopped
    raising "too many SQL variables" and started going QUADRATIC instead:
    measured on a 100,000-tag library, 0.05 s at 90,000 ids and 241 s at
    100,000 for the same two rows back — a listing that appears to hang.
    Counted rather than timed, because the timing is the symptom and the
    statement count is the rule.
    """
    from media_compost.db import Database, chunked
    from media_compost.ops import tagcatalog

    db = Database.in_memory()
    ids = list(range(1, 25_001))          # no rows need exist to be asked for
    want = len(list(chunked(ids)))
    assert want > 1, "the chunk size must be smaller than this list"
    with db.session() as s:
        seen = []
        real = s.execute

        def counting(stmt, *a, **kw):
            seen.append(stmt)
            return real(stmt, *a, **kw)

        s.execute = counting                  # type: ignore[method-assign]
        assert tagcatalog.implied_names(s, ids) == {}
        assert len(seen) == want, f"implied_names sent {len(seen)} statements"
        seen.clear()
        assert tagcatalog.meta_names(s, ids) == {}
        assert len(seen) == want, f"meta_names sent {len(seen)} statements"


def test_implication_column_and_entailed_counts(client):
    ids = _item_ids(client)
    assert len(ids) >= 2
    a, b = ids[0], ids[1]
    # poodle implies dog.
    assert client.post("/api/tags", json={"name": "poodle", "implies": "dog"}).status_code == 200
    # Assign poodle to a, dog directly to b.
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "poodle", "negative": False})
    client.post(f"/api/tags/assign/item/{b}", json={"tag": "dog", "negative": False})

    rows = client.get("/api/tags").json()
    poodle = _tag(rows, "poodle")
    dog = _tag(rows, "dog")
    assert poodle["implies"] == ["dog"]
    # Counts are effective (resolved): poodle is only on item a.
    assert poodle["positive"] == 1
    # dog: item b direct + item a implied by its child poodle -> 2 distinct items.
    assert dog["positive"] == 2

    # a effectively has dog (implied by poodle); searching dog finds it.
    found = search_items(client, q_tag("dog"))["items"]
    assert {i["id"] for i in found} == {a, b}


def test_a_negative_assignment_implies_nothing(client):
    """"Not a poodle" says nothing about dogs. Implication follows the POSITIVE
    assignment only — in both directions: the entailed tag is neither implied
    positively nor implied negatively by it."""
    ids = _item_ids(client)
    a, b = ids[0], ids[1]
    client.post("/api/tags", json={"name": "poodle", "implies": "dog"})
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "poodle", "negative": True})
    client.post(f"/api/tags/assign/item/{b}", json={"tag": "poodle", "negative": False})

    rows = client.get("/api/tags").json()
    # Only b (the positive one) counts towards dog, and nothing is negative.
    assert _tag(rows, "dog")["positive"] == 1
    assert _tag(rows, "dog")["negative"] == 0
    assert _tag(rows, "poodle")["negative"] == 1

    detail = client.get(f"/api/items/{a}").json()
    assert not any(t["name"] == "dog" for t in detail["tags"])
    assert {i["id"] for i in search_items(client, q_tag("dog"))["items"]} == {b}


def test_the_positive_count_says_how_much_of_it_is_implicit(client):
    """The green count is the effective one; the bracketed part of it is what no
    item assigns directly — implied by another tag, inherited from a group, or
    carried by a sequence member."""
    ids = _item_ids(client)
    a, b = ids[0], ids[1]
    client.post("/api/tags", json={"name": "poodle", "implies": "dog"})
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "poodle", "negative": False})
    client.post(f"/api/tags/assign/item/{b}", json={"tag": "dog", "negative": False})

    rows = client.get("/api/tags").json()
    dog = _tag(rows, "dog")
    assert (dog["positive"], dog["positive_indirect"]) == (2, 1)  # b direct, a implied
    poodle = _tag(rows, "poodle")
    assert (poodle["positive"], poodle["positive_indirect"]) == (1, 0)


def test_tag_count_matches_search_with_sequence(client):
    # A sequence container matches a tag search when any of its members carries
    # the tag; the Tags list count must reflect that too (count == search total).
    ids = _item_ids(client)
    a, b = ids[0], ids[1]
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "seqtag", "negative": False})
    # A sequence over member `a` (plus `b` so it's a real multi-item sequence).
    client.post("/api/sequences", json={"name": "S1", "item_ids": [a, b]})

    total = search_items(client, q_tag("seqtag"))["total"]
    rows = client.get("/api/tags").json()
    seqtag = _tag(rows, "seqtag")
    # Member `a` (1) + the sequence container that inherits it (1) = 2, and the
    # list count agrees with what the search returns.
    assert total == 2
    assert seqtag["positive"] == total


def test_a_containers_own_negative_vetoes_the_fold_everywhere(client):
    """A chapter marked `-seqtag` is not about seqtag, whatever a page
    carries: the item detail said so (the inherited tag shown overridden)
    while the search still found the container and the Tags list still
    counted it — pos 2, implicit 1 — which is the disagreement this pins
    shut. The count is the search's total, in both states."""
    ids = _item_ids(client)
    a, b = ids[0], ids[1]
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "seqtag", "negative": False})
    seq = client.post("/api/sequences", json={"name": "S1", "item_ids": [a, b]}).json()
    cont = seq["item_id"]
    client.post(f"/api/tags/assign/item/{cont}", json={"tag": "seqtag", "negative": True})

    total = search_items(client, q_tag("seqtag"))["total"]
    assert total == 1, "the member alone; the container said no"
    rows = client.get("/api/tags").json()
    seqtag = _tag(rows, "seqtag")
    assert (seqtag["positive"], seqtag["positive_indirect"], seqtag["negative"]) == (1, 0, 1)
    idx = client.get("/api/tags/index").json()
    i = idx["names"].index("seqtag")
    assert (idx["numbers"]["positive"][i],
            idx["numbers"]["implicit"][i]) == (1, 0)
    # Taking the negative off puts the fold back: count == search again.
    client.delete(f"/api/tags/assign/item/{cont}/seqtag")
    total = search_items(client, q_tag("seqtag"))["total"]
    seqtag = _tag(client.get("/api/tags").json(), "seqtag")
    assert total == 2 and seqtag["positive"] == 2


def test_item_detail_marks_implied_group_and_override(client):
    a = _item_ids(client)[0]
    client.post("/api/tags", json={"name": "poodle", "implies": "dog"})
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "poodle", "negative": False})

    detail = client.get(f"/api/items/{a}").json()
    parent_grp = next(g for g in detail["indirect"] if g["source"] == "parent")
    assert parent_grp["tags"] == ["dog"]
    assert parent_grp["overridden"] == []

    # Directly negating dog overrides the implied one (still listed, now flagged).
    client.post(f"/api/tags/assign/item/{a}", json={"tag": "dog", "negative": True})
    detail = client.get(f"/api/items/{a}").json()
    parent_grp = next(g for g in detail["indirect"] if g["source"] == "parent")
    assert parent_grp["overridden"] == ["dog"]


def test_an_alias_implies_nothing(client):
    client.post("/api/tags", json={"name": "dog"})
    client.post("/api/tags", json={"name": "hound", "alias_of": "dog"})
    rows = client.get("/api/tags").json()
    hound = _tag(rows, "hound")
    r = client.post(f"/api/tags/{hound['id']}/implies", json={"name": "animal"})
    assert r.status_code == 400


def test_implication_cycle_rejected(client):
    client.post("/api/tags", json={"name": "a"})
    client.post("/api/tags", json={"name": "b", "implies": "a"})
    rows = client.get("/api/tags").json()
    a_id = _tag(rows, "a")["id"]
    # Making a a child of b would close a cycle.
    assert client.post(f"/api/tags/{a_id}/implies",
                       json={"name": "b"}).status_code == 400


def test_link_tag_rows_comment_rename_delete(client):
    ids = _item_ids(client)
    a, b = ids[0], ids[1]
    rel = client.post("/api/relationships", json={
        "from_item_id": a, "to_item_id": b, "kind": "manual",
    }).json()
    rid = rel["id"]
    client.post(f"/api/relationships/{rid}/tags", json={"name": "cropped"})

    rows = client.get("/api/link-tags/rows").json()
    assert _tag(rows, "cropped")["count"] == 1

    # Comment persists on the link tag.
    client.post("/api/link-tags/update", json={"name": "cropped", "comment": "a crop"})
    rows = client.get("/api/link-tags/rows").json()
    assert _tag(rows, "cropped")["comment"] == "a crop"

    # Rename rewrites the relationship's tag.
    client.post("/api/link-tags/update", json={"name": "cropped", "new_name": "trimmed"})
    assert client.get(f"/api/items/{a}/relationships").json()  # relationship exists
    rows = client.get("/api/link-tags/rows").json()
    assert not any(r["name"] == "cropped" for r in rows)
    assert _tag(rows, "trimmed")["count"] == 1
    assert _tag(rows, "trimmed")["comment"] == "a crop"

    # Delete removes it everywhere.
    client.post("/api/link-tags/delete", json={"name": "trimmed"})
    rows = client.get("/api/link-tags/rows").json()
    assert not any(r["name"] == "trimmed" for r in rows)


def test_the_index_counts_over_any_subset_of_media_kinds(client):
    """`media=` is a comma list of kinds now — the Tags tab's media button
    ticks any subset — and none, or all three, is no narrowing at all."""
    ids = _item_ids(client)
    client.post(f"/api/tags/assign/item/{ids[0]}", json={"tag": "onimage", "negative": False})

    def positive(media: str) -> int:
        idx = client.get(f"/api/tags/index?media={media}").json()
        return idx["numbers"]["positive"][idx["names"].index("onimage")]

    assert positive("all") == 1
    assert positive("image") == 1
    assert positive("video") == 0
    assert positive("video,sequence") == 0
    assert positive("image,video") == 1
    assert positive("image,video,sequence") == 1


def test_a_ranking_puts_nothing_in_the_index(client):
    """The list had a "Hide score tags" narrowing, because a ranking minted
    a row per bucket and a 0-100 one was a hundred rows nobody wrote sitting
    between everything else. A ranking mints nothing (rung v31), so there is
    nothing to hide and the narrowing went with it."""
    ids = _item_ids(client)
    client.post(f"/api/tags/assign/item/{ids[0]}", json={"tag": "ordinary",
                                                         "negative": False})
    before = client.get("/api/tags/index").json()["names"]
    r = client.post("/api/rankings", json={"name": "Quality",
                                           "bucket_lo": 0, "bucket_hi": 5})
    assert r.status_code == 200, r.text
    assert client.get("/api/tags/index").json()["names"] == before


def test_the_index_can_be_narrowed_to_one_meta_tag(client):
    """A META TAG IS THE MARK A BULK IMPORT LEAVES, which makes it the one
    cut through a catalog of 200,000 names nobody has to type — and it is
    written on the row, so the capsule is the control."""
    ids = _item_ids(client)
    for name in ("fromsite", "byhand"):
        client.post(f"/api/tags/assign/item/{ids[0]}", json={"tag": name,
                                                            "negative": False})
    tid = next(t["id"] for t in client.get("/api/tags").json()
               if t["name"] == "fromsite")
    r = client.post(f"/api/tags/{tid}/meta-tags", json={"name": "danbooru"})
    assert r.status_code == 200, r.text

    all_names = client.get("/api/tags/index").json()["names"]
    assert {"fromsite", "byhand"} <= set(all_names)

    only = client.get("/api/tags/index?meta=danbooru").json()["names"]
    assert only == ["fromsite"]
    # Matched the way it is written on the capsule, case and all.
    assert client.get("/api/tags/index?meta=DanBooru").json()["names"] == only
    # A meta tag nothing carries narrows to nothing — not to everything.
    assert client.get("/api/tags/index?meta=nobody").json()["names"] == []


def test_a_hidden_tag_is_not_suggested_but_is_still_a_tag(client):
    """A booru dump puts a hundred thousand names in front of every field
    somebody types in, while most of a library's own work happens in a few
    hundred of them. Hiding is how the rest get out of the way — NOT a
    deletion and not a scope: the tag assigns, searches, counts and is listed
    exactly as before, it simply stops being suggested."""
    for name in ("keepme", "keepmeout"):
        client.post("/api/tags", json={"name": name})

    def suggested(q=""):
        return [r["name"] for r in
                client.get(f"/api/tags/names?q={q}").json()]

    assert {"keepme", "keepmeout"} <= set(suggested("keepme"))

    r = client.post("/api/tags/hidden", json={"names": ["keepmeout"]})
    assert r.status_code == 200, r.text
    assert r.json() == ["keepmeout"]
    assert suggested("keepme") == ["keepme"]
    # …and the empty needle, which is a different statement.
    assert "keepmeout" not in suggested()
    # The tag is still in the catalog, and says it is hidden.
    rows = {t["name"]: t for t in client.get("/api/tags").json()}
    assert rows["keepmeout"]["hidden"] is True
    assert rows["keepme"]["hidden"] is False

    # Hiding what is already hidden moves nothing, so it is not an event.
    assert client.post("/api/tags/hidden",
                       json={"names": ["keepmeout"]}).json() == []
    # And putting it back is the same verb the other way.
    assert client.post("/api/tags/hidden",
                       json={"names": ["keepmeout"], "hidden": False}
                       ).json() == ["keepmeout"]
    assert "keepmeout" in suggested("keepme")


def test_the_list_can_be_narrowed_to_what_the_fields_do_not_offer(client):
    """Hiding is neither a deletion nor a scope, so nothing else about the
    list says which names were taken out — the filter is how the decision is
    reviewed and undone. BOTH kinds count: a name in a hidden namespace is
    not offered any more than one taken out on its own, and a filter that
    could not find those answered a question nobody asked."""
    for name in ("keepme", "keepmeout", "artist:ann"):
        client.post("/api/tags", json={"name": name})
    client.post("/api/tags/hidden", json={"names": ["keepmeout"]})
    client.put("/api/tags/hidden-namespaces", json={"namespaces": ["artist"]})

    def index(**kw):
        q = "&".join(f"{k}={v}" for k, v in kw.items())
        return client.get(f"/api/tags/index?{q}").json()

    def listed(**kw):
        return set(index(**kw)["names"])

    every = listed()
    assert {"keepme", "keepmeout", "artist:ann"} <= every
    assert listed(suggest="hidden") == {"keepmeout", "artist:ann"}
    assert listed(suggest="shown") == every - {"keepmeout", "artist:ann"}
    # THE TWO ARE NOT ONE FACT, and the index says which is which: only the
    # row's own flag can be undone from the row.
    got = index()
    names = got["names"]
    assert [names[i] for i in got["hidden"]] == ["keepmeout"]
    assert [names[i] for i in got["hidden_ns"]] == ["artist:ann"]
    # Put both back and the filter follows.
    client.post("/api/tags/hidden",
                json={"names": ["keepmeout"], "hidden": False})
    client.put("/api/tags/hidden-namespaces", json={"namespaces": []})
    assert listed(suggest="hidden") == set()


def test_a_hidden_namespace_takes_every_name_made_with_it_out(client):
    """A namespace is the text before a tag's first colon and nothing else —
    no row to flag — so the hidden ones are a setting, and hiding one takes
    the tags made LATER with it as well as the ones there now."""
    for name in ("artist:ann", "artist:bob", "mood:calm"):
        client.post("/api/tags", json={"name": name})

    def suggested(q=""):
        return [r["name"] for r in client.get(f"/api/tags/names?q={q}").json()]

    assert "artist:ann" in suggested("a")
    r = client.put("/api/tags/hidden-namespaces",
                   json={"namespaces": ["artist:"]})
    assert r.status_code == 200, r.text
    # Stored WITHOUT the colon, the way `tagname.namespace` answers.
    assert r.json() == ["artist"]
    assert client.get("/api/tags/hidden-namespaces").json() == ["artist"]

    left = suggested("a")
    assert "artist:ann" not in left and "artist:bob" not in left
    assert "mood:calm" in suggested("mood")

    # A tag made AFTERWARDS in that namespace is out too — which is the point.
    client.post("/api/tags", json={"name": "artist:cyd"})
    assert "artist:cyd" not in suggested("artist")

    # Clearing the list puts them all back.
    assert client.put("/api/tags/hidden-namespaces",
                      json={"namespaces": []}).json() == []
    assert "artist:ann" in suggested("a")


def test_a_count_column_takes_a_range(client):
    """The columns are what the list is READ for, so they are what it should
    be narrowable by. A range reads the same tables the column draws from, so
    "positive between 2 and 3" is exactly the rows whose Positive cell says
    2 or 3 — an absent bound is no bound, which makes "at least" and "at
    most" the same control with one end filled in."""
    ids = _item_ids(client)
    for n, count in (("one", 1), ("two", 2), ("three", 3)):
        for iid in ids[:count]:
            client.post(f"/api/tags/assign/item/{iid}",
                        json={"tag": n, "negative": False})

    def names(**q):
        p = "&".join(f"{k}={v}" for k, v in q.items())
        return set(client.get(f"/api/tags/index?{p}").json()["names"])

    mine = {"one", "two", "three"}
    idx = client.get("/api/tags/index").json()
    count = {n: idx["numbers"]["positive"][i]
             for i, n in enumerate(idx["names"]) if n in mine}
    assert mine <= set(count)

    for lo in (2, 3):
        assert names(pos_min=lo) & mine == {n for n, c in count.items() if c >= lo}
    assert names(pos_max=1) & mine == {n for n, c in count.items() if c <= 1}
    assert names(pos_min=2, pos_max=2) & mine == \
        {n for n, c in count.items() if c == 2}
    # A negative range reads the negative column, not the positive one.
    client.post(f"/api/tags/assign/item/{ids[0]}",
                json={"tag": "one", "negative": True})
    assert "one" in names(neg_min=1)
    assert "two" not in names(neg_min=1)


def test_the_window_row_says_whether_a_tag_is_hidden(client):
    """The row's menu offers "Hide" or "Suggest again", so the row has to
    know which — and the WINDOW's rows are what the list draws, not the
    whole-catalog listing."""
    client.post("/api/tags", json={"name": "quiet"})
    tid = next(t["id"] for t in client.get("/api/tags").json()
               if t["name"] == "quiet")

    def row():
        return client.post("/api/tags/rows", json={"ids": [tid]}).json()[0]

    assert row()["hidden"] is False
    client.post("/api/tags/hidden", json={"names": ["quiet"]})
    assert row()["hidden"] is True


def test_equal_counts_are_broken_by_the_biggest_figure_anybody_has(client):
    """In a young library most names are unused, so `positive` is 0 for
    hundreds of candidates at once and the TIE-BREAK is what actually orders
    the autocomplete. It is the biggest figure anybody has for the name — a
    meta tag's count or a tag SET's — and reading only the meta counts left a
    name a booru set says is on 4.7M pictures ranked under one nobody has
    ever heard of."""
    for n in ("zzz_known", "zzz_unknown"):
        client.post("/api/tags", json={"name": n})
    doc = {"format": "media-compost-tag-set", "format_version": 1,
           "name": "Booru mini",
           "entries": [{"name": "zzz_known", "count": 4_700_000}]}
    r = client.post("/api/tag-sets/import", json={"document": doc, "mode": "create"})
    assert r.status_code == 200, r.text

    names = [x["name"] for x in client.get("/api/tags/names?q=zzz_").json()]
    assert names[:2] == ["zzz_known", "zzz_unknown"], names

    # A META count does the same job, and the bigger of the two wins.
    tid = next(t["id"] for t in client.get("/api/tags").json()
               if t["name"] == "zzz_unknown")
    client.post(f"/api/tags/{tid}/meta-tags",
                json={"name": "tumblr", "count": 9_000_000})
    names = [x["name"] for x in client.get("/api/tags/names?q=zzz_").json()]
    assert names[:2] == ["zzz_unknown", "zzz_known"], names
