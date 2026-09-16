"""Scaling tripwires over a 50k-item synthetic library (``pytest -m perf``).

Assertions are STATEMENT SHAPES and generous wall-clock ceilings, not tight
timings: what these catch is a regression back to per-item Python loops — a
listing that stops LIMITing, a count that starts resolving the library — not
a five-percent slowdown. A shape is the same shape at any size, which is why
the default library is small enough to seed in seconds; the SIZE is a knob
(`perfseed.perf_items`), and the full-size sweep is the same tests:

    MEDIA_COMPOST_PERF_ITEMS=1500000 pytest -m perf -q     # 156 s, 2.2 GB

`test_perf_scaling.py` asks the question one size cannot — whether the cost
GROWS with the library — by running the same reads against two of them.
"""

from __future__ import annotations

import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event

from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from media_compost.ui.server.routers import stats as stats_router
from tests.ui.perfseed import perf_items, seed_library, timed_runs

pytestmark = pytest.mark.perf

#: `MEDIA_COMPOST_PERF_ITEMS` overrides it — see `perfseed.perf_items`
#: for why the default is small and when to raise it.
N_ITEMS = perf_items(50_000)


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    data = tmp_path_factory.mktemp("perf") / "data"
    db = seed_library(data, items=N_ITEMS)
    library = Library(db.config)
    app.dependency_overrides[get_library] = lambda: library
    deps.reset_library()
    with TestClient(app) as c:
        yield c, library
    app.dependency_overrides.clear()


#: A statement whose select list begins with an aggregate answers with a
#: NUMBER rather than with rows, so it is not a page read at all — which is
#: why the total (`SELECT count(*) FROM (...)`) has always been left out of
#: the reads asserted on below. The library revision token
#: (`routers/items.py: _revision`, `max(items.id)` beside `max(events.id)`,
#: compared only for equality so the grid can notice a window mixing two
#: revisions) is the same category and was not, so a deep page failed the
#: bounded-read assertion on a query SQLite answers with one seek:
#:
#:     sqlite> EXPLAIN QUERY PLAN SELECT max(items.id) FROM items;
#:     `--SEARCH items                     <- the max()-on-a-rowid optimisation
#:     sqlite> EXPLAIN QUERY PLAN SELECT count(*) FROM items;
#:     `--SCAN items USING COVERING INDEX  <- and this one was already exempt
#:
#: Matched at the HEAD rather than anywhere in the statement (which is what
#: `"count(" not in s.lower()` did): an aggregate in a WHERE clause of a
#: statement that also selects rows exempts nothing.
#:
#: What this deliberately does not catch, since the plan is not consulted: an
#: aggregate over a column with no index, which really would walk the table.
#: The assertion below is about the page path materialising the library, and
#: that is a different mistake.
_AGGREGATE_HEAD = re.compile(r"\s*SELECT\s+(?:count|max|min|sum|avg)\s*\(", re.I)


class StatementLog:
    def __init__(self, engine):
        self.engine = engine
        self.statements: list[str] = []
        #: What each was BOUND with, in step with `statements` — a plan is
        #: only the plan for the values it was asked about, and a statement
        #: nobody can re-bind cannot be explained.
        self.params: list[tuple] = []

    def __enter__(self):
        sa_event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        sa_event.remove(self.engine, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, params, context, executemany):
        self.statements.append(statement)
        self.params.append(tuple(params or ()))


def test_listing_page_is_limited_and_fast(big):
    client, library = big
    with StatementLog(library.db.engine) as log:
        t0 = time.monotonic()
        r = client.get("/api/items?page=200&page_size=60")
        dt = time.monotonic() - t0
    assert r.status_code == 200
    assert r.json()["total"] == N_ITEMS
    assert len(r.json()["items"]) == 60
    assert not timed_runs() or dt < 2.0, f"page took {dt:.2f}s"
    # The page query itself carries a LIMIT; nothing selects the items table
    # unbounded (the residue-free path must not materialize candidates).
    assert any("LIMIT" in s for s in log.statements)


def test_tag_search_is_pure_sql(big):
    client, library = big
    body = {"query": {"type": "group", "op": "and", "children": [
        {"type": "tag", "name": "t1"}]}, "page": 1, "page_size": 60}
    with StatementLog(library.db.engine) as log:
        t0 = time.monotonic()
        r = client.post("/api/items/query", json=body)
        dt = time.monotonic() - t0
    assert r.status_code == 200
    assert r.json()["total"] > 0
    assert not timed_runs() or dt < 2.0, f"search took {dt:.2f}s"
    # An exactly-compiled tag never loads the whole assignment table: every
    # item_tags read is a correlated probe or an aggregate, so no statement
    # selects from item_tags without a WHERE.
    for stmt in log.statements:
        if "FROM item_tags" in stmt and "WHERE" not in stmt:
            raise AssertionError(f"unbounded item_tags read:\n{stmt}")


def test_facets_is_one_aggregate(big):
    client, library = big
    with StatementLog(library.db.engine) as log:
        r = client.get("/api/items/facets")
    assert r.status_code == 200
    assert r.json()["count"] == N_ITEMS
    aggregates = [s for s in log.statements if "count(" in s.lower()]
    assert len(aggregates) == 1, log.statements


def test_tag_list_counts_scale_with_catalog_not_library(big):
    client, library = big
    with StatementLog(library.db.engine) as log:
        t0 = time.monotonic()
        r = client.get("/api/tags")
        dt = time.monotonic() - t0
    assert r.status_code == 200
    assert len(r.json()) == 2_000
    assert not timed_runs() or dt < 3.0, f"tags list took {dt:.2f}s"
    # Statement count bounded by the special-tag set (grants + implication
    # targets, ~3 here), never by the item count.
    assert len(log.statements) < 60, len(log.statements)


def test_stats_pending_counts_in_sql(big):
    client, library = big
    # The endpoint is cached on a library-revision token, and by this point in
    # the module the answer may already be in it — so the shape this asserts
    # would be a list of nothing. Drop the entry and measure the recompute.
    stats_router._STATS_CACHE.clear()
    with StatementLog(library.db.engine) as log:
        r = client.get("/api/library/stats")
    assert r.status_code == 200
    assert any("count(" in s.lower() for s in log.statements), "cached away"
    for stmt in log.statements:
        if "FROM item_tags" in stmt and "count" not in stmt.lower():
            raise AssertionError(f"stats materialized ids:\n{stmt}")


def test_a_rating_pair_costs_the_same_whatever_the_pool_holds(big):
    """`/pair` runs once per PRESS, so nothing in it may scale with the pool.

    It used to: the endpoint fetched every id in scope (a Python list of the
    whole library) and handed it to `pick_pair`, which sorted it twice — at
    a million items that measured ~1.0 s for the fetch and ~1.4 s for the
    sorts, per judgement, to choose two pictures. The count and a sample are
    both one statement, and the shape is the assertion: every read of the
    items table here is bounded, exactly as a deep page's is.

    The ranking is created and deleted inside the test: minting a range adds
    its score tags to the catalog, and this file's library is shared by the
    whole module (`test_tag_list_counts_scale_with_catalog_not_library`
    counts it).
    """
    client, library = big
    made = client.post("/api/rankings",
                       json={"name": "perf"})
    assert made.status_code == 200, made.text
    rid = [r for r in made.json() if r["name"] == "perf"][0]["id"]
    try:
        with StatementLog(library.db.engine) as log:
            t0 = time.monotonic()
            r = client.post(f"/api/rankings/{rid}/pair", json={})
            dt = time.monotonic() - t0
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["pool"] == N_ITEMS
        assert body["a"] and body["b"], body
        assert not timed_runs() or dt < 2.0, f"a pair took {dt:.2f}s"
        reads = [x for x in log.statements
                 if "FROM items" in x and not _AGGREGATE_HEAD.match(x)]
        assert reads, "no statement read the items table at all"
        for stmt in reads:
            bounded = ("LIMIT" in stmt or "items.id IN" in stmt
                       or "items.id =" in stmt)
            assert bounded, (
                f"the pair endpoint read the whole pool — a judgement's cost "
                f"now grows with the library:\n{stmt}")
    finally:
        client.request("DELETE", f"/api/rankings/{rid}")


def test_the_grid_pages_by_INDEX_and_never_sorts_the_library(big):
    """A page is 60 rows; the sort must not cost the whole library.

    SQLite was answering the default view with `SEARCH items USING INDEX
    ix_items_hidden` and then `USE TEMP B-TREE FOR ORDER BY` — 246 ms per
    page at a million items, on every view and every page. The sort indexes
    (`db._INDEX_DDL`) put the scope's equality in front of the sort's own
    key, so the index IS the order and the page stops after 60 rows.

    The PLAN is the assertion: a timing at 50k cannot tell a sorted scan
    from an indexed walk, and the temp b-tree is exactly the thing that
    grows with the library.
    """
    client, library = big
    with library.db.session() as s:
        conn = s.connection()
        # The tiebreaker follows the key's own direction, exactly as
        # `order_by_for` writes it — an index walk satisfies `id DESC` after
        # a DESC key and `id ASC` after an ASC one, and mixing them is a
        # partial sort per tie group ("LAST TERM OF ORDER BY").
        for sort, order in (
            ("recent",
             "coalesce(items.last_imported_at, items.created_at) DESC"),
            ("modified", "items.updated_at DESC"),
            ("first", "items.created_at DESC"),
            ("name", "lower(items.name) ASC"),
        ):
            tie = "ASC" if order.endswith("ASC") else "DESC"
            q = ("SELECT items.id FROM items JOIN files ON files.id = "
                 "items.active_file_id AND (files.item_id = items.id OR "
                 "items.kind = 'sequence') WHERE items.hidden IS 0 AND "
                 "(items.id NOT IN (SELECT trashed_items.item_id FROM "
                 f"trashed_items)) ORDER BY {order}, items.id {tie} LIMIT 60")
            plan = " | ".join(
                r[-1] for r in conn.exec_driver_sql(
                    "EXPLAIN QUERY PLAN " + q).fetchall())
            assert "TEMP B-TREE" not in plan, f"{sort} sorts the library:\n{plan}"
            assert "ix_items_sort_" in plan, f"{sort} ignores its index:\n{plan}"


def test_a_tag_session_never_fetches_the_pool(big):
    """`/next` runs once per ANSWER, so nothing in it may scale with the pool.

    It used to: the pool was fetched whole and then filtered in Python —
    ~0.9 s of ids, ~0.6 s of chunked `item_tags` reads to drop the answered
    ones and ~0.5 s more to ask which carried a vector, per press, to put
    twelve pictures on screen. The candidates stay in SQL now, and the shape
    is the assertion: every read of the items table is bounded.
    """
    client, library = big
    body = {"tags": ["t1"], "count": 12, "recent": [], "smart": True}
    with StatementLog(library.db.engine) as log:
        t0 = time.monotonic()
        r = client.post("/api/tagsort/next", json=body)
        dt = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert not timed_runs() or dt < 2.0, f"a tag-session fetch took {dt:.2f}s"
    reads = [x for x in log.statements
             if "FROM items" in x and not _AGGREGATE_HEAD.match(x)]
    for stmt in reads:
        bounded = ("LIMIT" in stmt or "items.id IN" in stmt
                   or "items.id = " in stmt)
        assert bounded, (
            f"the tag session read the whole pool — an answer's cost now "
            f"grows with the library:\n{stmt}")


def test_scaling_ratio_page_cost_constant(big):
    """Page 800 must cost about what page 1 costs — pagination in SQL.

    The SHAPE is the assertion, not the clock. `deep < first * 20 + 200` was
    the previous bound and is close to unfalsifiable: a 50k-row Python-side
    walk would still come in under a fifth of a second, so the check passed
    whatever the implementation did. What actually distinguishes "SQL paged"
    from "materialized and sliced" is the STATEMENT — a deep page must carry
    its own LIMIT/OFFSET and must not read the items table unbounded — and
    that is the same thing the rest of this file asserts.

    The timing stays as a coarse ceiling, one order of magnitude rather than
    twenty times, so a genuine collapse is still noticed without the test
    becoming a benchmark of whatever machine CI gave us.
    """
    client, library = big

    def ms(page: int) -> float:
        t0 = time.monotonic()
        r = client.get(f"/api/items?page={page}&page_size=60")
        assert r.status_code == 200
        return (time.monotonic() - t0) * 1000

    ms(1)  # warm
    first = min(ms(1) for _ in range(3))
    with StatementLog(library.db.engine) as log:
        deep = min(ms(800) for _ in range(3))

    page_reads = [s for s in log.statements
                  if "FROM items" in s and not _AGGREGATE_HEAD.match(s)]
    assert page_reads, "no statement read the items table at all"
    # Every read of the table is BOUNDED, one of the two legitimate ways: the
    # paging query carries LIMIT/OFFSET, and the hydration that follows it
    # names the 60 ids that came back. What must never appear is a read with
    # neither — that is the whole library walked to reach row 48,000.
    # (A third kind of statement reaches the items table here and is not a
    # read at all — see `_AGGREGATE_HEAD`.)
    assert any("LIMIT" in s for s in page_reads), (
        "no statement paged in SQL — the offset is being applied in Python")
    for stmt in page_reads:
        bounded = "LIMIT" in stmt or "items.id IN" in stmt or "items.id =" in stmt
        assert bounded, (
            f"a deep page read the items table with no LIMIT and no id "
            f"filter, so it walks everything before row 48,000:\n{stmt}")
    assert deep < max(first * 10, 250), (
        f"page 1 {first:.0f}ms vs page 800 {deep:.0f}ms — pagination is "
        f"costing more the further in it goes")


def test_selecting_a_group_never_probes_PER_DESCENDANT(big):
    """A group's scope is one `IN (subquery)`, never an EXISTS per group id.

    It was `EXISTS (SELECT 1 FROM item_groups WHERE item_id = items.id AND
    group_id IN (…))`, and SQLite runs that as a correlated probe per row —
    at 1.1M items under a root group with 73 descendants the grid took 7.8 s
    for one page. As a plain `id IN (SELECT item_id …)` the subquery is
    materialized once and the page is 0.4 s. The shape is the assertion: the
    cost of the old form is invisible on a 50k library.
    """
    client, library = big
    root = client.get("/api/groups").json()[0]["id"]
    with StatementLog(library.db.engine) as log:
        t0 = time.monotonic()
        r = client.get(f"/api/items?groups={root}&page=1&page_size=60")
        dt = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert r.json()["total"] > 0
    assert not timed_runs() or dt < 2.0, f"group page took {dt:.2f}s"
    # The page's own "which groups are these 60 items in" read is bounded and
    # is not what this is about; the SCOPE is the statement selecting items.
    scoped = [s for s in log.statements
              if "item_groups" in s and "FROM items" in s]
    assert scoped, log.statements
    for stmt in scoped:
        # Every read of the membership table is the uncorrelated subquery —
        # counted rather than pattern-matched, since the statement carries an
        # unrelated EXISTS (the trash) that a regex walks straight past.
        assert (stmt.count("FROM item_groups")
                == stmt.count("IN (SELECT item_groups.item_id")
                >= 1), f"per-row group probe:\n{stmt}"


def test_the_group_tree_counts_in_ONE_statement(big):
    """`/api/groups` returns every group with what its SUBTREE holds.

    One `COUNT(DISTINCT item_id)` per group is a scan of the membership table
    per row — 5.3 s for 373 groups on a 1.3M-membership library — so the
    counts are one recursive-CTE closure joined to `item_groups`, grouped by
    ancestor. Statement count, not the clock: the per-group form is only
    seconds slow once the tree is big.

    The revision is bumped first because that one statement is also CACHED
    now (the fan-out is inherent, so what is bounded is how often it is
    paid) — without the bump this would be asserting the cache rather than
    the shape.
    """
    client, library = big
    library.db.commits += 1
    with StatementLog(library.db.engine) as log:
        r = client.get("/api/groups")
    assert r.status_code == 200

    def nodes(rows):
        return sum(1 + nodes(r["children"]) for r in rows)

    assert nodes(r.json()) == 60
    counting = [s for s in log.statements if "count(" in s.lower()]
    assert len(counting) == 1, counting


def _counts(log) -> list[str]:
    """The statements that COUNT the items table — what a view spends its
    time on once the sort indexes have made its page free."""
    return [s for s in log.statements
            if "count(" in s.lower() and "FROM items" in s]


def test_a_VIEW_COUNTS_ITSELF_ONCE_however_many_pages_are_asked_for(big):
    """The total is the cost of a view and the page beside it is free.

    With the sort indexes in place a page of 60 is an index range — 0.4 ms at
    a million items — while the total is a SCAN of everything the scope
    admits: 197 ms for All Items there, 375 for Ungrouped, 513 for Untagged.
    And it was asked again for every page and every switch back to a category,
    over a library that had not moved between them.

    So it goes through `Database.cached`, keyed on the compiled statement and
    the library revision. The assertion is the STATEMENT: on this 50,000-item
    library the clock cannot tell the two apart.
    """
    client, library = big
    library.db._memo.clear()
    with StatementLog(library.db.engine) as log:
        first = client.post("/api/items/query",
                            json={"page": 1, "page_size": 60})
    assert first.status_code == 200
    assert _counts(log), "the first look must actually count"
    total = first.json()["total"]

    with StatementLog(library.db.engine) as log:
        for page in (2, 3, 1):
            r = client.post("/api/items/query",
                            json={"page": page, "page_size": 60})
            assert r.json()["total"] == total
    assert _counts(log) == [], _counts(log)


def test_AND_COUNTS_ITSELF_AGAIN_once_the_library_moves(big):
    """Not a TTL: the token moves the moment anything is written, so the
    answer is either this library's or it is recomputed. A cache that could
    hand back yesterday's total would be worse than no cache."""
    client, library = big
    client.post("/api/items/query", json={"page": 1, "page_size": 60})
    with StatementLog(library.db.engine) as log:
        client.post("/api/items/query", json={"page": 1, "page_size": 60})
    assert _counts(log) == [], "not cached to begin with"

    made = client.post("/api/tags", json={"name": "moved-the-library"})
    assert made.status_code == 200, made.text
    with StatementLog(library.db.engine) as log:
        client.post("/api/items/query", json={"page": 1, "page_size": 60})
    assert _counts(log), "a write must make the next view recount"


def test_a_media_kind_category_counts_itself_FROM_AN_INDEX(big):
    """Images / Videos / Sequences are an equality on `kind` inside the
    ordinary `hidden` scope, and without `ix_items_kind` the count walks
    every visible item to find them — 107 ms for the 20,000 sequences in a
    million-item library. The PLAN is what says it: this library's items are
    all one kind, so the clock cannot.
    """
    client, library = big
    library.db._memo.clear()
    with StatementLog(library.db.engine) as log:
        r = client.post("/api/items/query",
                        json={"kind": "image", "page": 1, "page_size": 60})
    assert r.status_code == 200
    counting = _counts(log)
    assert len(counting) == 1, counting
    cur = library.db.engine.raw_connection().cursor()
    plan = "\n".join(row[-1] for row in
                     cur.execute("EXPLAIN QUERY PLAN " + counting[0],
                                 ("image", "image", 1)).fetchall())
    assert "ix_items_kind" in plan, plan


def test_a_rating_PRESS_neither_counts_nor_scans_the_pool(big):
    """A judgement is one `/judge` and one `/pair`, and neither may look at
    the pool as a whole.

    Two things used to: the pool's SIZE (a `count(*)` over the whole scope,
    for a number that cannot move while a session runs — the overlay asks
    once and then says `want_pool: false`), and the SAMPLE the pick is drawn
    from (`ORDER BY random() LIMIT 2000`, a scan; it is `k` random ids thrown
    at the scope now, with the scan behind it for a pool too thin to answer
    that way). Together they were 435 ms of a 441 ms judgement at a million
    items; it is ~20 ms.
    """
    client, library = big
    made = client.post("/api/rankings",
                       json={"name": "press"})
    rid = [r for r in made.json() if r["name"] == "press"][0]["id"]
    try:
        first = client.post(f"/api/rankings/{rid}/pair", json={}).json()
        assert first["pool"] == N_ITEMS
        pair = [first["a"]["item_id"], first["b"]["item_id"]]
        client.post(f"/api/rankings/{rid}/judge",
                    json={"a_item_id": pair[0], "b_item_id": pair[1],
                          "outcome": "a"})
        with StatementLog(library.db.engine) as log:
            r = client.post(f"/api/rankings/{rid}/pair",
                            json={"want_pool": False, "recent": [pair]})
        assert r.status_code == 200, r.text
        assert r.json()["pool"] is None, "it counted a pool nobody asked for"
        assert _counts(log) == [], _counts(log)
        for stmt in log.statements:
            assert "random()" not in stmt, f"the pick scanned the pool:\n{stmt}"
    finally:
        client.request("DELETE", f"/api/rankings/{rid}")


def test_a_page_PAST_THE_END_is_not_a_query(big):
    """The total bounds the page, so an empty view costs nothing to page.

    A `LIMIT 60` that can never fill has to walk the WHOLE scope to find that
    out — an Untagged view over a library with nothing untagged measured 243
    ms of scan for its zero rows, every time, with the cached total sitting
    beside it saying the answer. The same holds for a page scrolled past the
    end of any view.
    """
    client, library = big
    r = client.post("/api/items/query",
                    json={"untagged": True, "page": 1, "page_size": 60})
    assert r.status_code == 200 and r.json()["total"] == 0, r.json()["total"]
    with StatementLog(library.db.engine) as log:
        empty = client.post("/api/items/query",
                            json={"untagged": True, "page": 1,
                                  "page_size": 60})
    assert empty.json()["items"] == []
    for stmt in log.statements:
        assert "LIMIT" not in stmt, f"it paged a view it knew was empty:\n{stmt}"
    # …and a page past the end of a view that DOES hold rows.
    with StatementLog(library.db.engine) as log:
        far = client.post("/api/items/query",
                          json={"page": 10_000, "page_size": 60})
    assert far.json()["items"] == [] and far.json()["total"] == N_ITEMS
    for stmt in log.statements:
        assert "LIMIT" not in stmt, f"it paged past the end:\n{stmt}"


def test_a_tag_session_ANSWER_neither_counts_nor_scans_the_pool(big):
    """An answer is one `/tagsort/next`, and it may look at neither the pool's
    size nor the pool itself.

    Two things used to, the rating overlay's two exactly: the pool's SIZE (a
    `count(*)` over the whole scope minus what is decided, for a number the
    session can already work out — every item it is handed leaves the
    candidate set once, so what is left is the chooser's figure minus how
    many have been shown), and the SAMPLE the classifier is fed (up to
    `SCORE_CAP` rows drawn by `ORDER BY random()` with a per-row `EXISTS`
    over the embeddings — 2954 ms at a million items; `k` random ids thrown
    at the scope now, with the scan behind it for a pool too thin to answer
    that way). Together they were most of a 1–5 SECOND answer; it is ~90 ms.

    The chooser's own probe (`count: 0`) still counts — those numbers are
    what it exists to fetch — so this asserts the FEED.
    """
    client, library = big
    body = {"tags": ["t7"], "count": 12, "smart": True, "recent": []}
    first = client.post("/api/tagsort/next", json={**body, "count": 0})
    assert first.status_code == 200, first.text
    assert first.json()["pool"] > 0, "the probe must actually count"

    with StatementLog(library.db.engine) as log:
        r = client.post("/api/tagsort/next", json={**body, "want_pool": False})
    assert r.status_code == 200, r.text
    assert r.json()["pool"] is None, "it counted a pool nobody asked for"
    for stmt in log.statements:
        if "count(" in stmt.lower() and "FROM items" in stmt:
            raise AssertionError(f"it counted the pool:\n{stmt}")
        if "random()" in stmt:
            raise AssertionError(f"it scanned the pool for a sample:\n{stmt}")


def test_the_named_faces_list_hydrates_only_its_PAGE(big):
    """It loaded every named face in the library as an ORM row before
    deciding which fifty people to show — 1.22 s of a 1.70 s request at
    200,000 named faces, spent on rows the page would never mention. The
    counts and the ordering are one grouped pass now, and what is hydrated
    is at most `limit * per` crops.
    """
    import re as _re

    client, library = big
    with StatementLog(library.db.engine) as log:
        assert client.get("/api/faces/named?limit=5&per=3").status_code == 200
    # Every read of the faces table is bounded: by a subject, by an id list,
    # or by being an aggregate.
    unbounded = [
        q for q in log.statements
        if _re.search(r"\bFROM faces\b", q)
        and "count(" not in q.lower()
        and "item_subjects.subject_id = ?" not in q
        and " IN (" not in q
    ]
    assert not unbounded, unbounded
