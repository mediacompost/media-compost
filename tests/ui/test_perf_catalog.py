"""The CATALOG axis: a booru-sized tag set over few items (``-m perf``).

Its own module because its library is its own. `test_perf_smoke.py` builds a
module-scoped 50,000-ITEM library and installs it as
``app.dependency_overrides[get_library]``; a second module-scoped fixture
beside it would be a second global installed over the first, and the tests
sharing that file would be served whichever library was built last — which
is exactly what happened, as a page-800 request answered out of a
2,000-item library. One library per module, and they cannot overlap.

What this axis is FOR: the tag list is the one read that materializes the
whole catalog, and nothing in the item-scaled file could see it. The bug
that prompted this measured 0.05 s at 90,000 tags and 241 s at 100,000.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from tests.ui.perfseed import perf_tags, seed_library, timed_runs
from tests.ui.test_perf_smoke import StatementLog

pytestmark = pytest.mark.perf

#: Six figures, and the digit matters — see the fixture.
N_TAGS = perf_tags(100_000)


@pytest.fixture(scope="module")
def big_catalog(tmp_path_factory):
    """A big TAG SET over few items — the other axis entirely.

    `big` is 50,000 items and 2,000 tags, which is why it could not see the
    tag list go quadratic in the CATALOG: `implied_names` was handed every
    tag id in one `IN`, and at 2,000 that is instant however it is spelled.
    Few items here on purpose, so the seed stays cheap and a failure can
    only be about the catalog.

    TWO META TAGS PER TAG, which is what a bulk-imported catalog looks like
    and is not decoration: the autocomplete's tie-break reads them, so a
    catalog carrying none cannot see that half of the query at all.

    SIX FIGURES, and the digit matters: the unchunked read this exists to
    catch was 0.05 s at 90,000 ids and 241 s at 100,000, so a catalog
    rounded down to a friendlier number would pass through the very bug it
    is here for. Verified by reverting the chunking with this fixture in
    place — the assertion below fails on the clock, not on a technicality.
    """
    data = tmp_path_factory.mktemp("perfcat") / "data"
    db = seed_library(data, items=2_000, tags=N_TAGS, tags_per_item=3,
                      meta_per_tag=2)
    library = Library(db.config)
    app.dependency_overrides[get_library] = lambda: library
    deps.reset_library()
    with TestClient(app) as c:
        yield c, library
    app.dependency_overrides.clear()
    deps.reset_library()


def test_the_tag_list_scales_with_a_BIG_CATALOG(big_catalog):
    """The whole catalog is one response, so it is linear in the catalog and
    must stay linear.

    The ceiling is generous and the point is the shape: this same request
    took 240 SECONDS at 100,000 tags, because one of the two id-list reads
    behind it was not chunked. A statement count bounded by the chunk
    arithmetic is what says it still is.
    """
    client, library = big_catalog
    with StatementLog(library.db.engine) as log:
        t0 = time.monotonic()
        r = client.get("/api/tags")
        dt = time.monotonic() - t0
    assert r.status_code == 200
    assert len(r.json()) == N_TAGS
    assert not timed_runs() or dt < 8.0, f"tags list took {dt:.2f}s over {N_TAGS:,} tags"
    # Two chunked reads over the catalog plus the counts' own handful —
    # never one statement per tag, and never one huge one.
    assert len(log.statements) < 60, len(log.statements)


def test_the_autocomplete_never_aggregates_the_assignment_table(big_catalog):
    """`/api/tags/names` runs once per KEYSTROKE, so nothing in it may be a
    read of the whole library.

    It was one statement whose count map was a `GROUP BY tag_id` over
    `item_tags` — materialized in full however few tags match, and growing
    with the ASSIGNMENT table, which is the part of a library with no bound
    at all. The counts are correlated per matched tag now, so the shape is
    the assertion: no statement here may aggregate that table without a
    WHERE naming a tag.
    """
    client, library = big_catalog
    with StatementLog(library.db.engine) as log:
        r = client.get("/api/tags/names?q=t1234&limit=50")
    assert r.status_code == 200
    assert r.json(), "the fragment must actually match something"
    for stmt in log.statements:
        if "GROUP BY item_tags.tag_id" in stmt:
            raise AssertionError(f"whole-table count map:\n{stmt}")
        if "GROUP BY tag_meta_tags.tag_id" in stmt:
            raise AssertionError(f"whole-table meta map:\n{stmt}")


def test_a_fragment_that_starts_a_name_is_answered_FROM_THE_INDEX(big_catalog):
    """Rule (2) puts every name STARTING with the fragment above every name
    merely containing it, so that bucket is a contiguous RANGE of the
    lowercase-name index — a seek, and where it fills the page the substring
    scan never runs at all. Measured on a 200,000-tag catalog: 120 ms → 0.6 ms.

    The plan is what says it, not the clock: this fixture's names are `t<n>`,
    so a scan of 100,000 of them is fast enough to hide the difference.

    WHAT IS ASSERTED IS THE SEEK, not one index's name. The regression this
    caught was no index being chosen at all — `Tag.hidden` arrived with its
    own `ix_tags_hidden` and, an equality looking more selective than a range
    to a planner with no `ANALYZE` stats, that index won and the bucket went
    back to a SCAN (measured on a 100,000-tag catalog: 2.4 ms → 18 ms a
    keystroke). So the test reads the range CONSTRAINT out of the plan, which
    is the thing that is either there or not.

    The table holds every imported set's names too now, and the range is
    over the `lname` COLUMN rather than over `lower(name)` — the scope
    (`hidden`) leads the index and one seek answers both.
    """
    client, library = big_catalog
    with StatementLog(library.db.engine) as log:
        r = client.get("/api/tags/names?q=t1234&limit=10")
    assert len(r.json()) == 10, "the prefix bucket must fill the page here"
    over_tags = [(s, p) for s, p in zip(log.statements, log.params)
                 if "FROM tags" in s]
    assert len(over_tags) == 1, [s for s, _ in over_tags]
    stmt, params = over_tags[0]
    plan = "\n".join(
        row[-1] for row in library.db.engine.raw_connection()
        .cursor().execute("EXPLAIN QUERY PLAN " + stmt, params).fetchall())
    assert "ix_tags_visible_lname2" in plan or "ix_tags_scope_lname" in plan, plan
    # …and it is USED as a range, not merely mentioned.
    assert "lname>?" in plan and "lname<?" in plan, plan


def test_the_autocomplete_stays_under_a_tenth_of_a_second(big_catalog):
    """The ceiling is generous and the point is the shape above; what this
    adds is that the two together really do keep a keystroke interactive on a
    six-figure catalog."""
    client, _ = big_catalog
    for q in ("t", "t1", "t123", "t12345", "zzzz"):
        client.get(f"/api/tags/names?q={q}&limit=50")   # warm the page cache
        t0 = time.monotonic()
        r = client.get(f"/api/tags/names?q={q}&limit=50")
        dt = time.monotonic() - t0
        assert r.status_code == 200
        assert not timed_runs() or dt < 0.5, f"q={q!r} took {dt:.3f}s"


# ---- the 2026-09 sweep ------------------------------------------------------
#
# A second pass over every read endpoint, against a library with 1.5M items,
# 250K tags, 11.5M assignments, 5,000 groups, 400K faces, 300K captions, 4.5M
# metadata rows and 400K history events. Each test below is a SHAPE the fix
# depends on; the numbers in the docstrings are from that library.


def test_the_metadata_catalogs_intrinsic_figures_are_ONE_pass(big_catalog):
    """Eleven scans of the active-file join became one.

    Five counts and three min/max pairs, each its own full walk, answering
    eleven numbers about the same rows: 2.05 s for `names_only=true` at 1.5M
    items against 0.32 s. The shape, not the clock — a figure added back as
    its own `_count(...)` is a twelfth scan nothing else would notice.
    """
    client, library = big_catalog
    library.db.commits += 1                      # past the revision cache
    with StatementLog(library.db.engine) as log:
        assert client.get("/api/metadata/catalog?names_only=true").status_code == 200
    over_files = [q for q in log.statements
                  if "FROM files" in q and "item_metadata" not in q]
    assert len(over_files) == 1, over_files


def test_the_metadata_catalog_is_cached_on_the_library_revision(big_catalog):
    """What is left after that rewrite is an aggregate over every metadata
    row — the floor for the question — and the question is a pure function of
    the library that the query builder asks on every open."""
    client, library = big_catalog
    library.db.commits += 1
    assert client.get("/api/metadata/catalog").status_code == 200
    with StatementLog(library.db.engine) as log:
        assert client.get("/api/metadata/catalog").status_code == 200
    assert not [q for q in log.statements if "item_metadata" in q], log.statements


def test_metadata_values_reads_ONE_TABLE_AT_A_TIME_through_its_index(
        big_catalog):
    """A UNION is materialized as a co-routine no index can reach into, so
    the DISTINCT sorted every row of both tables into a temp b-tree. Asked
    per table it is a range on `ix_item_metadata_values` that stops at the
    limit: 1.92 s -> 0.79 s for the shape alone, -> 0.08 s with the index.
    """
    client, library = big_catalog
    with StatementLog(library.db.engine) as log:
        assert client.get("/api/metadata/values?name=camera_make").status_code == 200
    meta = [q for q in log.statements if "item_metadata" in q]
    assert meta, log.statements
    assert not [q for q in meta if "UNION" in q.upper()], meta
    plan = "\n".join(
        row[-1] for row in library.db.engine.raw_connection().cursor()
        .execute("EXPLAIN QUERY PLAN SELECT DISTINCT text_value "
                 "FROM item_metadata WHERE name = 'x' AND mtype = 'text' "
                 "AND text_value IS NOT NULL "
                 "AND item_id NOT IN (SELECT item_id FROM trashed_items) "
                 "ORDER BY text_value LIMIT 50").fetchall())
    assert "ix_item_metadata_values" in plan, plan


def test_the_group_trees_subtree_counts_are_cached(big_catalog):
    """Every membership is counted once per ANCESTOR — ~11M rows at 5,000
    groups over 2.3M memberships, 3.49 s of a 3.80 s `/api/groups`. The
    fan-out is inherent (see `_counts_by_group`), so what is bounded is how
    OFTEN it is paid: the tree is fetched on every load."""
    client, library = big_catalog
    library.db.commits += 1
    assert client.get("/api/groups").status_code == 200
    with StatementLog(library.db.engine) as log:
        assert client.get("/api/groups").status_code == 200
    assert not [q for q in log.statements if "RECURSIVE" in q.upper()], \
        log.statements


def test_counts_without_containers_reads_only_the_names_it_was_asked_about(
        big_catalog):
    """It read `(id, name)` for the WHOLE catalog to answer about a few
    thousand — 0.20 s of a 0.44 s call at 250,000 tags, on every subjects,
    places and events listing."""
    from media_compost.prefilter import counts_without_containers

    _client, library = big_catalog
    with library.db.session() as s:
        with StatementLog(library.db.engine) as log:
            counts_without_containers(s, ["t1", "t2", "t3"])
    unbounded = [q for q in log.statements
                 if "FROM tags" in q and "WHERE" not in q.upper()]
    assert not unbounded, unbounded


def test_the_tag_lists_meta_marks_read_their_table_ONCE(big_catalog):
    """The names and the nonzero counts are the same rows, and this list
    reads them for the whole catalog: 0.80 s each, 0.80 s for the pair."""
    _client, library = big_catalog
    from media_compost.ops import tagcatalog

    with library.db.session() as s:
        ids = [1, 2, 3]
        with StatementLog(library.db.engine) as log:
            tagcatalog.meta_marks(s, ids)
    assert len([q for q in log.statements if "tag_meta_tags" in q]) == 1, \
        log.statements


def test_the_tag_list_writes_dicts_that_match_the_model(big_catalog):
    """Building a validated model per row is most of what the whole-catalog
    listing costs once the queries are cheap — 1.9 s against 0.38 s for the
    same bytes at 250,000 tags. The MODEL is still the schema, so this holds
    the dicts to it: same keys, same values, same JSON."""
    import json

    from media_compost.ui.server.routers.tags import _tag_rows
    from media_compost.ui.server.schemas import TagRow
    from pydantic import TypeAdapter

    _client, library = big_catalog
    with library.db.session() as s:
        rows = _tag_rows(s)[:500]
    assert rows and isinstance(rows[0], dict)
    models = TypeAdapter(list[TagRow]).dump_json([TagRow(**r) for r in rows])
    assert json.loads(json.dumps(rows)) == json.loads(models)
