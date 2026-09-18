"""FOLD SEQUENCES — hide a member where its own sequence is in this view.

A chapter and its pages are two items in the library, and in a view holding
both the pages are already on screen: they are what the chapter's card is a
picture of. So the grid's fold drops a member exactly where a sequence
holding it has its CONTAINER in the same view — and nowhere else. That
"nowhere else" is the whole point and is what these tests are about: a group
holding the pages but not the chapter shows the pages; a media-kind filter
with sequences unticked shows them; a search matching only the pages shows
them.

It is the one scope field that is not a fact about the item alone, so it is
asked as the view's OWN where list, put again to the containers
(`prefilter.fold_sequenced_clause`) — and where the search does not compile
exactly, as the same question over the evaluated answer
(`ops/search._drop_folded_members`). The two paths are asserted to agree,
because a superset of containers would hide pages the search never really
matched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.db import Group, Item, ItemGroup, Sequence, SequenceItem
from media_compost.importer import Importer, ImportOptions
from media_compost.testing import make_image, search_items
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


def q_tag_count(op: str, value) -> dict:
    """An INEXACT condition — `tag_count` needs effective resolution, so
    whatever it is OR'd with stays RESIDUE and the answer comes from the
    Python evaluator."""
    return {"type": "meta", "name": "tag_count", "mtype": "numeric",
            "op": op, "value": value}


def q_or(*children) -> dict:
    return {"type": "group", "op": "or", "neg": False,
            "children": list(children)}


@pytest.fixture
def client(tmp_path: Path):
    """Three pages in a chapter, plus one loose picture.

    The pages are ordinary items; the chapter is the container item every
    sequence has, borrowing its first page's file the way the importer
    builds one.
    """
    src = tmp_path / "src"
    src.mkdir()
    for i in range(4):
        make_image(src / f"p{i}.png", seed=100 + i)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.flush()
        items = s.query(Item).order_by(Item.id).all()
        pages, loose = items[:3], items[3]
        cont = Item(uid="fold-cont", name="Chapter", kind="sequence",
                    active_file_id=pages[0].active_file_id)
        s.add(cont)
        s.flush()
        seq = Sequence(uid="fold-seq", name="Chapter", kind="comic",
                       item_id=cont.id)
        s.add(seq)
        s.flush()
        for pos, p in enumerate(pages):
            s.add(SequenceItem(sequence_id=seq.id, item_id=p.id,
                               position=pos))
        s.commit()
        ids = {"pages": [p.id for p in pages], "loose": loose.id,
               "container": cont.id, "sequence": seq.id}
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib
        c.ids = ids
        yield c
    app.dependency_overrides.clear()


def _ids(page) -> list[int]:
    return sorted(i["id"] for i in page["items"])


def _group(client, name: str, item_ids: list[int]) -> int:
    with client.lib.db.session() as s:
        g = Group(name=name)
        s.add(g)
        s.flush()
        for iid in item_ids:
            s.add(ItemGroup(item_id=iid, group_id=g.id))
        s.commit()
        return g.id


def test_off_the_view_holds_the_chapter_and_its_pages(client):
    ids = client.ids
    assert _ids(search_items(client)) == sorted(
        ids["pages"] + [ids["loose"], ids["container"]])


def test_on_the_pages_give_way_to_their_chapter(client):
    ids = client.ids
    assert _ids(search_items(client, fold_sequenced=True)) == sorted(
        [ids["loose"], ids["container"]])


def test_a_group_holding_the_pages_but_not_the_chapter_still_shows_them(client):
    """The fold is about THIS view: the chapter is not in the group, so
    nothing on screen stands for the pages and they stay."""
    ids = client.ids
    gid = _group(client, "Pages", ids["pages"])
    assert _ids(search_items(client, groups=str(gid),
                             fold_sequenced=True)) == sorted(ids["pages"])


def test_a_group_holding_both_folds(client):
    ids = client.ids
    gid = _group(client, "Everything", ids["pages"] + [ids["container"]])
    assert _ids(search_items(client, groups=str(gid),
                             fold_sequenced=True)) == [ids["container"]]


def test_narrowing_to_images_takes_the_chapter_out_and_the_pages_stay(client):
    """A media-kind filter with sequences unticked shows no container at
    all, so there is nothing for a page to give way to."""
    ids = client.ids
    assert _ids(search_items(client, kind="image",
                             fold_sequenced=True)) == sorted(
        ids["pages"] + [ids["loose"]])


def test_a_search_the_chapter_does_not_match_keeps_its_pages(client):
    """The container is judged by the WHOLE view, the search included.

    `INFO:file_count=1` is the condition to say it with: a container owns no
    file of its own (it borrows a member's), so it answers 0 and is out of
    this view — where a TAG would not do, a container carrying its members'
    tags being exactly what the compiler's own sequence fold is for.
    """
    ids = client.ids
    one_file = {"type": "meta", "name": "file_count", "mtype": "numeric",
                "op": "=", "value": 1}
    assert _ids(search_items(client, one_file, fold_sequenced=True)) == \
        sorted(ids["pages"] + [ids["loose"]])


def test_the_residue_path_answers_the_same(client):
    """Forced through the evaluator by an OR with an inexact condition.

    A compiled clause is only a SUPERSET there, so a fold built from it
    could hide pages whose chapter the search does not really match — which
    is why that path waits for the evaluated answer instead.
    """
    ids = client.ids
    never = q_tag_count(">=", 999)  # matches nothing: the OR is its left half
    everything = q_or({"type": "meta", "name": "file_count",
                       "mtype": "numeric", "op": ">=", "value": 0}, never)
    assert _ids(search_items(client, everything, fold_sequenced=True)) == \
        sorted([ids["loose"], ids["container"]])
    assert _ids(search_items(client, everything)) == sorted(
        ids["pages"] + [ids["loose"], ids["container"]])


def test_inside_a_sequence_view_the_fold_does_nothing(client):
    """Every item there is a member of the one sequence and its container is
    not in the view at all — a fold that emptied the page would be the
    chapter refusing to open."""
    ids = client.ids
    page = search_items(client, sequence=ids["sequence"], fold_sequenced=True)
    assert _ids(page) == sorted(ids["pages"])


def test_a_view_with_no_sequence_in_it_builds_no_clause(client, tmp_path: Path):
    """The fold's cost is a probe per item, so the two cheap halves of "is
    there anything to fold" are asked first — and a view that shows no
    container skips the clause outright.

    The count is what to watch: `search_filtered` is called for the page,
    the count, the facets, the group runs and the id range alike, and a
    clause none of them can act on is a probe per row, five times over.
    """
    from media_compost import ops, prefilter
    from media_compost.ops import search as ops_search

    with client.lib.db.session() as s:
        whole = ops_search.search_filtered(s, "", False, fold_sequenced=True)
        assert any("sequence_items" in str(c) for c in whole.where), (
            "the library's own view holds a chapter, so it must fold")
        # Sequences unticked in the media kinds: no container can be shown.
        images = ops_search.search_filtered(s, "", False, kind="image",
                                            fold_sequenced=True)
        assert not any("sequence_items" in str(c) for c in images.where)
        # And a group holding no container answers the same way.
        gid = _group(client, "Loose", [client.ids["loose"]])
        loose = ops_search.search_filtered(s, str(gid), False,
                                           fold_sequenced=True)
        assert not any("sequence_items" in str(c) for c in loose.where)
        assert prefilter.view_shows_a_container(s, []) is True


def test_a_library_of_loose_pictures_never_folds(tmp_path: Path):
    """The probe is an indexed `kind = 'sequence'` seek, so a library with
    no sequence in it answers no for every view."""
    from media_compost.ops import search as ops_search

    src = tmp_path / "loose"
    src.mkdir()
    make_image(src / "a.png", seed=7)
    cfg = UiConfig(data_dir=tmp_path / "loose-data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False))
        s.commit()
    with lib.db.session() as s:
        cands = ops_search.search_filtered(s, "", False, fold_sequenced=True)
        assert not any("sequence_items" in str(c) for c in cands.where)
        assert cands.fold_sequenced is False


def test_the_plan_reads_the_containers_once_and_probes_by_index(client):
    """WHAT THE FOLD COSTS IS A SHAPE, and only the plan can see it.

    The answer is right whichever way SQLite runs this, so nothing else
    here would notice the container select being re-run per row, or the
    containers being found by a scan of every item. Measured on a
    1,020,000-item library with 400,000 of them in books (the page query
    is unmoved at 0.1 -> 0.2 ms; the count, which is memoized on the
    revision, goes 217 -> 446 ms, and 862 without the `kind` narrowing
    below):

        all items                    count 217 -> 446 ms
        media kinds without sequences      160 -> 158 ms  (no clause)
        a group holding no chapter          42 ->  41 ms  (no clause)
        a tag search                       222 -> 268 ms

    The old "hide sequenced" toggle, which asks a covering index whether
    the item is a member at all, is 254 ms on that library — the floor for
    any per-row membership test.
    """
    from sqlalchemy import text

    from media_compost import prefilter
    from media_compost.ops import search as ops_search

    with client.lib.db.session() as s:
        cands = ops_search.search_filtered(s, "", False, fold_sequenced=True)
        sel = prefilter.base_select([Item.id], None, list(cands.where)).limit(60)
        sql = str(sel.compile(client.lib.db.engine,
                              compile_kwargs={"literal_binds": True}))
        plan = [row[-1] for row in s.execute(text("EXPLAIN QUERY PLAN " + sql))]

    # The view's containers are read ONCE into a list, not per row.
    lists = [i for i, ln in enumerate(plan) if "LIST SUBQUERY" in ln]
    assert lists, plan
    # …and found through the kind index rather than by reading every item.
    assert any("ix_items_kind" in ln for ln in plan), plan
    assert not any("SCAN items" in ln for ln in plan), plan
    # The membership itself is an indexed probe per item.
    members = [ln for ln in plan if "sequence_items" in ln]
    assert members and all("SEARCH" in ln and "INDEX" in ln for ln in members), \
        plan
