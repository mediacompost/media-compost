"""DOES IT SCALE — the same work at two sizes, compared.

``pytest -m perf``. The other perf modules ask "is this shape right at
50,000 items"; this one asks the question a single size cannot: **does the
cost grow with the library**. A function that reads a row per item, a query
that goes quadratic in the catalog, an index the planner stops using — all
of them are fast at 50k and none of them is visible in an absolute number
there. The 1.5M sweeps that found most of this repo's real regressions were
manual runs, which means they happened when somebody thought to do one.

TWO ASSERTIONS PER CASE, and the first is the one that matters:

* **The STATEMENT COUNT must not move.** A read whose statement count grows
  with N is doing per-row work, and that is exactly the class this file
  exists to catch — `implied_names` handed every tag id in one `IN`, the
  group tree probing once per descendant, the tag list counting once per
  special tag. It is a deterministic assertion: no clock, no machine, no
  flake. It is also a strict one — every case here is expected to answer in
  the SAME number of statements at 4x the size.
* **And the TIME RATIO is bounded**, coarsely. Four times the library may
  cost more; it may not cost sixteen. The bound is generous (a quadratic
  would be 16x and the bound is 6) because a laptop's timings under load are
  noisy and a flaky perf test gets deleted — what it catches is a collapse,
  not a drift.

WHY 20k AND 80k rather than 1.5M: the ratio is the measurement, and it needs
the same answer to be computable twice. A 1.5M seed is ~10 minutes and
~3 GB, which is a thing somebody does deliberately, not a thing a test
suite does — and the numbers a single 1.5M run produces are not comparable
to anything, which is what made the manual sweeps a matter of judgement
rather than a pass or a fail. The FULL-SIZE run is still available and is
now the same code: `MEDIA_COMPOST_PERF_ITEMS=1500000 pytest -m perf`, which
every perf module reads.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from tests.ui.perfseed import seed_library, timed_runs
from tests.ui.test_perf_smoke import StatementLog

pytestmark = pytest.mark.perf

#: The two sizes, and the factor between them. Small on purpose: what is
#: measured is the RATIO, so the absolute size only has to be big enough for
#: the per-row work to show — at 80,000 items a statement per item is
#: 80,000 statements, which nothing hides.
SMALL = 20_000
FACTOR = 4
LARGE = SMALL * FACTOR

#: Four times the library may cost more; it may not cost sixteen.
#:
#: EIGHT, and the headroom is deliberate: several of these reads are an
#: honest linear scan of something that just quadrupled — the facets measure
#: 3.8x, the group tree 4.5x, the metadata catalog 3.6x — so a bound at 5 or
#: 6 would be a flake waiting for a loaded machine. Quadratic is 16x, which
#: this still catches with room.
#:
#: What it is NOT is a detector. A regression that costs a constant factor
#: (the group scope restored to a correlated EXISTS — 7.9 s on a real
#: library) measures 2.5x here, inside the bound, because at 80,000 items
#: with a shallow tree the probe count is small. That class is caught by the
#: SHAPE tests in the sibling modules, and by the statement-count half
#: above; this half is the backstop for a collapse nobody predicted.
MAX_RATIO = 8.0
#: Below this, the measurement is noise — a 2 ms read that becomes 9 ms says
#: nothing about scaling and everything about the scheduler.
FLOOR_MS = 8.0


def _library(tmp_path_factory, scale: int):
    """One library at `scale` times the small one — in EVERY axis."""
    data = tmp_path_factory.mktemp(f"scale{scale}") / "data"
    db = seed_library(data, items=SMALL * scale, tags=2_000 * scale,
                      groups=60 * scale, records=scale,
                      rich=True, meta_per_tag=2)
    return Library(db.config)


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    """Two libraries, one FACTOR times the other IN EVERY AXIS — items,
    tags, meta tags, groups, subjects, places, events, captions, links and
    metadata rows.

    All of them, because a read that walks a table which did not grow reads
    as a read that scales: the group tree's `count(DISTINCT)` per ancestor
    was 5.3 s on a real library and would be invisible against two libraries
    that both hold sixty groups. The catalog is the same story one axis
    along — `implied_names` was handed every tag id in one `IN`, which is
    instant at 2,000 however it is spelled.
    """
    small = _library(tmp_path_factory, 1)
    large = _library(tmp_path_factory, FACTOR)
    yield small, large


def _measure(library, call):
    """(statements, best-of-three milliseconds) for one request.

    Best-of-three because the question is what the work COSTS, and the
    slowest of three runs on a laptop is a fact about the laptop.

    **THE LIBRARY REVISION IS BUMPED BEFORE EVERY MEASURED RUN**, and that is
    not a detail: several of these reads are memoised on it
    (`Database.cached` — the view totals, the sidebar's stats, the metadata
    catalog, the group tree's subtree counts), so a warm second call answers
    in NO statements at all and takes no time. Measured that way, a read
    restored to one indexed count per group — the 5.3 s shape this repo
    actually had — passes both assertions at both sizes, because neither run
    ever reaches it. A scaling test has to measure the WORK; what the cache
    is worth is the other perf module's question, and it bumps for the same
    reason in the other direction.

    The first call is still made warm and unmeasured: connection pool, query
    plans and the app's own lazily-built singletons are not what is being
    asked about either.
    """
    app.dependency_overrides[get_library] = lambda: library
    deps.reset_library()
    with TestClient(app) as client:
        call(client)  # warm: connection pool, query plans, singletons
        library.db.commits += 1
        with StatementLog(library.db.engine) as log:
            call(client)

        def cold() -> float:
            library.db.commits += 1
            return _time(call, client)
        best = min(cold() for _ in range(3))
    app.dependency_overrides.clear()
    return len(log.statements), best


def _time(call, client) -> float:
    t0 = time.monotonic()
    call(client)
    return (time.monotonic() - t0) * 1000


def _get(path):
    def call(client):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text[:200])
        return r
    return call


def _post(path, body):
    def call(client):
        r = client.post(path, json=body)
        assert r.status_code == 200, (path, r.text[:200])
        return r
    return call


def _group_page():
    """A page scoped to a real GROUP — and the scope field takes group IDS.

    It read `{"groups": "g1"}`, a NAME, and `prefilter.scope_clauses` keeps
    only the parts of that field that are digits: the case was an unscoped
    page under a scoped name, which is the same nothing-measured the search
    file's own group case was seeded into. The id is looked up once per
    client and cached, so the measured calls are the POST alone — and `g1`
    is the group worth naming, being the one with a subtree under it.
    """
    known: dict[int, str] = {}

    def group_id(client) -> str:
        def walk(nodes):
            for n in nodes:
                if n["name"] == "g1":
                    return n["id"]
                found = walk(n.get("children") or [])
                if found is not None:
                    return found
            return None

        if id(client) not in known:
            found = walk(client.get("/api/groups").json())
            assert found is not None, "the seeded library has no group g1"
            known[id(client)] = str(found)
        return known[id(client)]

    def call(client):
        r = client.post("/api/items/query",
                        json={"groups": group_id(client), "page": 1,
                              "page_size": 60})
        assert r.status_code == 200, r.text[:200]
        return r
    return call


#: One per read that a library's SIZE could plausibly reach into. Each is
#: named for what it would mean if it failed.
CASES = [
    ("a grid page", _get("/api/items?page=1&page_size=60")),
    ("a deep grid page", _get("/api/items?page=200&page_size=60")),
    # A GROUP-SCOPED page: the scope is one `IN (subquery)` and was once a
    # correlated `EXISTS` probed per group id — 7.8 s for one page of a root
    # group's 73 descendants at a million items, and one statement either
    # way, so only the CLOCK can see it.
    ("a group-scoped page", _group_page()),
    ("a searched page", _post("/api/items/query", {
        "query": {"type": "group", "op": "and", "children": [
            {"type": "tag", "name": "t1"}]}, "page": 1, "page_size": 60})),
    ("the facets", _get("/api/items/facets")),
    ("the sidebar's counts", _get("/api/library/stats")),
    ("the group tree", _get("/api/groups")),
    ("the tag index", _get("/api/tags/index?limit=100")),
    ("the tag autocomplete", _get("/api/tags/names?q=t1&limit=20")),
    ("the metadata catalog", _get("/api/metadata/catalog")),
    ("a metadata value list", _get("/api/metadata/values?name=camera")),
    ("the named faces", _get("/api/faces/named?limit=50")),
    ("the subjects list", _get("/api/subjects?limit=50")),
    ("the places list", _get("/api/places?limit=50")),
    ("the events list", _get("/api/events")),
]


@pytest.mark.parametrize("label,call", CASES,
                         ids=[c[0].replace(" ", "_") for c in CASES])
def test_the_statement_count_does_not_grow_with_the_library(pair, label, call):
    """The deterministic half. A read that issues MORE statements against a
    bigger library is doing something per row — which is the whole class of
    regression this file is here for, and the only one that can be asserted
    without a clock."""
    small, large = pair
    n_small, _ = _measure(small, call)
    n_large, _ = _measure(large, call)
    assert n_large == n_small, (
        f"{label}: {n_small} statements at {SMALL:,} items, {n_large} at "
        f"{LARGE:,} — something in it runs per row")


@pytest.mark.parametrize("label,call", CASES,
                         ids=[c[0].replace(" ", "_") for c in CASES])
def test_the_cost_does_not_grow_faster_than_the_library(pair, label, call):
    """The coarse half. Four times the library may cost more; it may not cost
    sixteen, which is what quadratic looks like."""
    small, large = pair
    _, ms_small = _measure(small, call)
    _, ms_large = _measure(large, call)
    if ms_large < FLOOR_MS:
        return  # too fast to say anything about — see FLOOR_MS
    ratio = ms_large / max(ms_small, 0.05)
    assert not timed_runs() or ratio < MAX_RATIO, (
        f"{label}: {ms_small:.1f}ms at {SMALL:,} items and {ms_large:.1f}ms "
        f"at {LARGE:,} — {ratio:.1f}x for {FACTOR}x the library")
