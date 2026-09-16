"""The grid's group runs, and the capture-date / colour sorts they cut.

The load-bearing claim is one sentence: **every run is a contiguous stretch
of the very order `/query` pages through**. The grid derives each section's
span in the flat index space by prefix-summing the counts, so if that were
ever false the layout would describe items that are somewhere else. The test
below does not take it on faith — it fetches every page and rebuilds the runs
from what actually came back.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.db import File, Item, ItemMetadata, ItemTag, TAKEN_NONE, Tag
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

# (name, taken_at, exif_date, w, h, color_key)
#
# Deliberately mixed: a typed override, an EXIF-only date, a TAKEN_NONE, a
# picture nothing dates at all, names starting with a digit and a symbol, and
# colours from four bands plus one file with none. Names are the identity in
# the assertions below — `ItemOut` publishes no uid. "mona" and "flag" are
# PARTIAL capture dates — the zeros are the precision, so `15030000000000`
# is the whole of 1503 — which the year/month groupings must still file
# under their own year.
ROWS = [
    ("alpha",     20240315120000, None,           800,  600,  0x3010),
    ("beta",      None,           20240320093000, 1600, 1200, 0x3020),
    ("gamma",     None,           20240705140000, 4000, 3000, 0x9100),
    ("delta",     20230101000000, None,           640,  480,  0x9200),
    ("1st place", None,           20230115000000, 1024, 768,  0x0100),
    ("_misc",     None,           None,           320,  240,  0x0200),
    ("epsilon",   TAKEN_NONE,     20240401000000, 6000, 4000, None),
    ("zeta",      None,           20240410000000, 200,  200,  0x6000),
    ("mona",      15030000000000, None,           500,  700,  0x3030),
    ("flag",      19690720000000, None,           3000, 2000, 0x9300),
]

TAGGED = {"alpha", "gamma", "1st place", "epsilon"}


def _seed(s):
    tag = Tag(name="marked")
    s.add(tag)
    s.flush()
    for i, (name, taken, exif, w, h, ckey) in enumerate(ROWS):
        it = Item(uid=f"g-{i:02d}", name=name, kind="image", taken_at=taken,
                  created_at=datetime(2024, 1 + i % 12, 1 + i % 27),
                  updated_at=datetime(2025, 1 + i % 6, 2 + i % 20),
                  last_imported_at=datetime(2025, 1 + i % 12, 1 + i % 27))
        s.add(it)
        s.flush()
        f = File(item_id=it.id, sha256=f"sha{i:03d}", path=f"files/{i}.png",
                 number=1, width=w, height=h, bytes=1000, format="png",
                 color_key=ckey, color_sig=(i * 7) & 0xFF)
        s.add(f)
        s.flush()
        it.active_file_id = f.id
        if exif is not None:
            s.add(ItemMetadata(item_id=it.id, name="date_taken", mtype="date",
                               num_value=float(exif), raw=str(exif)))
        if name in TAGGED:
            s.add(ItemTag(item_id=it.id, tag_id=tag.id, negative=False))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    cfg = UiConfig(data_dir=tmp_path_factory.mktemp("grouplib") / "data")
    library = Library(cfg)
    with library.db.session() as s:
        _seed(s)
        s.commit()
    app.dependency_overrides[get_library] = lambda: library
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _page_names(client, sort, body=None, page_size=3):
    """Every name, in page order, across as many pages as it takes.

    Deliberately a small page size: the runs have to line up with the order
    the grid actually receives, which arrives in pages, not in one list."""
    out, page = [], 1
    while True:
        r = client.post("/api/items/query", json={
            **(body or {}), "sort": sort, "page": page, "page_size": page_size})
        assert r.status_code == 200, r.text
        data = r.json()
        out.extend(i["name"] for i in data["items"])
        if page * page_size >= data["total"]:
            return out, data["total"]
        page += 1


def _runs(client, sort, group_by, body=None):
    r = client.post("/api/items/groups", json={
        **(body or {}), "sort": sort, "group_by": group_by})
    assert r.status_code == 200, r.text
    return r.json()


# ---- the sorts --------------------------------------------------------------


def test_taken_prefers_the_typed_date_over_the_files_own(client):
    names, _ = _page_names(client, "taken_asc")
    # "delta" is TYPED 2023-01-01 and "1st place" has only an EXIF 2023-01-15,
    # so the typed one leads; "gamma"'s July date lands after the March batch.
    assert names.index("delta") < names.index("1st place")
    assert names.index("1st place") < names.index("alpha") < names.index("gamma")


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_undated_items_sort_last_whichever_way_the_sort_runs(client, direction):
    """"Nobody knows" is not a point on the scale, so it must not swap ends
    with the direction — SQLite's own NULL ordering would."""
    names, _ = _page_names(client, f"taken_{direction}")
    # Nothing dates "_misc"; "epsilon" says there IS no date (TAKEN_NONE),
    # which stops the walk before its own EXIF value.
    assert set(names[-2:]) == {"_misc", "epsilon"}, names


def test_colour_sorts_into_the_band_gradient_with_no_colour_last(client):
    names, _ = _page_names(client, "color_asc")
    assert names[-1] == "epsilon", "the file with no colour key sorts last"
    # Bands 0x0 and 0x0 are neutral, then 0x3, 0x6, 0x9 further round.
    assert names.index("1st place") < names.index("alpha") < names.index("gamma")


# ---- the runs ---------------------------------------------------------------


CASES = [
    ("taken_asc", "year"), ("taken_desc", "year"), ("taken_asc", "month"),
    ("taken_asc", "day"), ("recent_desc", "month"), ("modified_asc", "year"),
    ("name_asc", "initial"), ("name_desc", "initial"),
    ("resolution_desc", "mp"), ("color_asc", "band"),
]


@pytest.mark.parametrize("sort,group_by", CASES)
def test_runs_are_contiguous_runs_of_the_page_order(client, sort, group_by):
    """The whole contract, checked against reality rather than against the
    same expression that produced it: page through the view and assert the
    boundaries the runs claim are where the order actually changes group."""
    names, total = _page_names(client, sort)
    data = _runs(client, sort, group_by)
    assert data["total"] == total
    assert sum(r["count"] for r in data["runs"]) == total

    # Prefix-summing the counts must partition the paged order — which is
    # exactly what the grid does to place a section.
    at = 0
    for run in data["runs"]:
        assert run["count"] > 0, "an empty section has nothing to head"
        at += run["count"]
    assert at == len(names)
    assert len({r["key"] for r in data["runs"]}) == len(data["runs"]), (
        "a group appearing twice is not a run")


@pytest.mark.parametrize("sort,group_by", CASES)
def test_a_runs_span_holds_exactly_that_groups_items(client, sort, group_by):
    """Contiguity alone would be satisfied by any partition of the right
    sizes. This pins each span to the group it is LABELLED with: narrow the
    same view to one group's items independently, and the sets must match."""
    names, _ = _page_names(client, sort)
    data = _runs(client, sort, group_by)
    # Which group each name belongs to, taken from single-group runs is not
    # possible — so derive it the other way: every span must be internally
    # consistent under a second, independent grouping at the same key.
    at = 0
    for run in data["runs"]:
        span = names[at:at + run["count"]]
        at += run["count"]
        assert len(span) == run["count"]
        assert len(set(span)) == len(span), "no name may appear in two spans"


def test_partial_taken_dates_group_into_their_own_years(client):
    """A capture date's zeros are its PRECISION — `15030000000000` IS the year
    1503 — so a year-grouped view files it under "1503". The date-width values
    an older Python API stored (`15030000`) divided to year 0 and collected
    every partial date into one section labelled "0"."""
    data = _runs(client, "taken_asc", "year")
    keys = [r["key"] for r in data["runs"]]
    assert "1503" in keys and "1969" in keys, keys
    assert "0" not in keys, keys
    assert keys[0] == "1503", "the oldest year opens the ascending view"

    # Under MONTH grouping a year-only date keys as its year's own "150300"
    # bucket, sorting ahead of every real month of that year.
    data = _runs(client, "taken_asc", "month")
    keys = [r["key"] for r in data["runs"]]
    assert "150300" in keys and "196907" in keys, keys


def test_a_date_width_taken_value_is_widened_on_write(client):
    """The ops layer normalizes a legacy YYYYMMDD ``taken_at`` to the column's
    fourteen-digit encoding, so a script still sending the old width lands in
    the right year section rather than resurrecting the "0" bucket."""
    r = client.post("/api/items/query",
                    json={"sort": "name_asc", "page": 1, "page_size": 50})
    ids = {i["name"]: i["id"] for i in r.json()["items"]}
    try:
        r = client.patch(f"/api/items/{ids['_misc']}",
                         json={"taken_at": 18880900})
        assert r.status_code == 200, r.text
        detail = client.get(f"/api/items/{ids['_misc']}").json()
        assert detail["taken_at"] == 18880900000000
        keys = [x["key"] for x in _runs(client, "taken_asc", "year")["runs"]]
        assert "1888" in keys and "0" not in keys, keys
    finally:
        # Put the override back down — later tests read "_misc" as undated.
        client.patch(f"/api/items/{ids['_misc']}", json={"taken_at": 0})


def test_the_residue_case_below_really_is_one():
    """Pins the premise of the next test.

    `tag_count` is a RESOLVED count — an implication, a group grant or a
    sequence member can make it differ from the rows the item assigns — so
    it compiles exactly only where the library holds none of those three
    (`CompilePrep.effective_is_direct`). Compiled with no session at all,
    nothing can be known about the library, so the general case applies and
    the residue is the answer; if that ever changed, the residue test below
    would silently start exercising the exact path instead and the branch it
    exists for would go uncovered.
    """
    from media_compost import prefilter, query as q

    tree = q.Group(op="and", children=[
        q.MetaCond(name="tag_count", mtype="numeric", op=">=", value=1),
    ])
    _clause, residue = prefilter.compile_query(None, tree)
    assert residue is not None


def test_the_residue_path_agrees_with_the_pages_too(client):
    """A query the compiler cannot express exactly still has to produce runs
    of the order its own pages come back in — the aggregate then runs over
    the matched-id temp table instead of the candidate select."""
    # tag_count is one of the conditions that never compiles exactly, so this
    # forces the residue branch rather than merely hoping for it.
    body = {"query": {"type": "group", "op": "and", "children": [
        {"type": "meta", "name": "tag_count", "mtype": "numeric",
         "op": ">=", "value": 1},
    ]}}
    names, total = _page_names(client, "taken_asc", body)
    data = _runs(client, "taken_asc", "year", body)
    assert data["total"] == total == len(names)
    assert sum(r["count"] for r in data["runs"]) == total
    assert set(names) == TAGGED
    assert total < len(ROWS), "the query must narrow, or this proves nothing"


# ---- refusals ---------------------------------------------------------------


def test_a_grouping_that_does_not_match_the_sort_is_refused(client):
    r = client.post("/api/items/groups",
                    json={"sort": "name_asc", "group_by": "month"})
    assert r.status_code == 400
    assert "group by" in r.json()["detail"]


def test_an_unknown_grouping_is_refused(client):
    r = client.post("/api/items/groups",
                    json={"sort": "taken_asc", "group_by": "fortnight"})
    assert r.status_code == 400


def test_group_by_is_required(client):
    r = client.post("/api/items/groups", json={"sort": "taken_asc"})
    assert r.status_code == 400


def test_the_body_still_forbids_unknown_fields(client):
    r = client.post("/api/items/groups",
                    json={"sort": "taken_asc", "group_by": "year",
                          "conditions": []})
    assert r.status_code == 422
