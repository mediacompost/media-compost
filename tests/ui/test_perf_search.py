"""Every search condition, over a 50k-item library that can answer it.

``pytest -m perf``. The sibling module (`test_perf_smoke.py`) covers the
paths a view goes through whatever it is filtered by — the page, the count,
the tree, the facets. This one covers the FILTER: one case per condition
kind, each against a library seeded with the tag set that condition asks
about, because a condition matching nothing is a condition nobody has
measured (the compiled clause is never reached, the residue never runs, and
a page of no rows is fast whatever it did).

What it pins, in order of how quietly each could break:

**Which conditions compile EXACTLY.** That is the whole scaling story. An
exact clause is a WHERE the page's LIMIT applies to; anything else falls to
the RESIDUE, which materialises every candidate the SQL admits and evaluates
it in Python at ~30 µs each — on this library the difference is 20 ms against
1.3 s, and at 1.5M items it is the difference between a view and a hang. A
compiler that silently stops compiling (a field renamed, a cap lowered, an
early `return Compiled(None, ...)`) costs no test today and every second of
every search tomorrow, so the table below is a RATCHET: it says which kinds
are exact and which are not, and either direction fails.

**That the page is still a bounded read.** Whatever the filter, one page is
a LIMITed statement — never a select of the items table that Python then
slices.

**And a ceiling per condition**, generous enough (2 s exact, 4 s residue —
against a measured worst of 1.3 s) to catch a return to per-item work rather
than a five-percent drift.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from media_compost import query as q
from media_compost.ops import search as ops_search
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from tests.ui.perfseed import perf_items, seed_library, timed_runs
from tests.ui.test_perf_smoke import StatementLog

pytestmark = pytest.mark.perf

N_ITEMS = perf_items(50_000)


@pytest.fixture(scope="module")
def rich(tmp_path_factory):
    data = tmp_path_factory.mktemp("perfsearch") / "data"
    db = seed_library(data, items=N_ITEMS, rich=True, meta_per_tag=2)
    library = Library(db.config)
    app.dependency_overrides[get_library] = lambda: library
    deps.reset_library()
    with TestClient(app) as c:
        yield c, library
    app.dependency_overrides.clear()


#: (label, condition node, compiles exactly).
#:
#: The five that do NOT are each documented where they are decided, and each
#: for a different reason:
#:
#: * ``TAG:<meta>`` past ``_MAX_META_TAGS`` — the expansion is one clause per
#:   tag, so a mark on half the catalog would be thousands of EXISTS.
#: * ``tag_count`` on a library with implications or group grants — the
#:   resolved count is not the stored one; only the ``<=``-shaped operators
#:   have a sound superset, and this case is ``>=``.
#: * a BOUNDED subject — presence is the superset, the dates are read off the
#:   loaded appearance states.
#: * ``TAKEN:`` — its walk ends in the events an item carries, which no
#:   clause reaches.
#:
#: Everything else compiles, including the two that resolve a SET first
#: (``SIMILAR:`` through the colour probe, ``VALUE:`` through the catalog):
#: those are `Item.id IN (...)` by the time the compiler sees them.
CONDITIONS = [
    ("tag", {"type": "tag", "name": "t1"}, True),
    ("tag negated", {"type": "tag", "name": "t1", "have": False}, True),
    ("tag by meta tag",
     {"type": "tag", "name": "", "meta_tags": [{"name": "tumblr"}]}, False),
    ("group", {"type": "ingroup", "name": "g0"}, True),
    ("group only",
     {"type": "ingroup", "name": "g1", "mode": "only"}, True),
    ("meta numeric",
     {"type": "meta", "name": "width", "mtype": "numeric",
      "op": ">=", "value": 1000}, True),
    ("meta text",
     {"type": "meta", "name": "camera", "mtype": "text",
      "op": "~", "value": "camera 3"}, True),
    ("meta date",
     {"type": "meta", "name": "date_taken", "mtype": "date",
      "op": ">=", "value": 20200101000000}, True),
    ("meta tag_count",
     {"type": "meta", "name": "tag_count", "mtype": "numeric",
      "op": ">=", "value": 6}, False),
    ("subject", {"type": "subject", "name": "subject:s5"}, True),
    ("subject any", {"type": "subject", "name": ""}, True),
    ("subject dated",
     {"type": "subject", "name": "", "date_from": 19900101,
      "date_to": 19951231}, False),
    ("place", {"type": "place", "op": "~", "value": "Town 3"}, True),
    ("place any", {"type": "place", "value": ""}, True),
    ("event", {"type": "event", "name": "event:e1"}, True),
    ("event dated",
     {"type": "event", "name": "", "date_from": 20120101,
      "date_to": 20131231}, True),
    ("taken",
     {"type": "taken", "date_from": 20210101, "date_to": 20211231}, False),
    ("caption",
     {"type": "caption", "mode": "has",
      "caption_tags": [{"name": "en"}]}, True),
    ("instruction",
     {"type": "caption", "mode": "has", "caption_kind": "instruction"}, True),
    ("link",
     {"type": "link", "direction": "has",
      "link_tags": [{"name": "derived"}]}, True),
    ("linked by", {"type": "link", "direction": "linkedby"}, True),
    ("value",
     {"type": "value", "name": "height", "op": ">=",
      "value": 170, "unit": "cm"}, True),
]

#: `SIMILAR:` names a PIVOT, so its case is built once the library exists.
SIMILAR_TOL = 6


def _tree(node: dict) -> dict:
    return {"type": "group", "op": "and", "children": [node]}


def _residue_of(library, node: dict):
    """Whether this condition reaches the evaluator, asked the way the app
    asks it — through `search_filtered`, which resolves the `SIMILAR:` and
    `VALUE:` sets before compiling. `compile_query` on its own cannot see
    those and reports them as inexact, which is a property of the probe
    rather than of the condition."""
    with library.db.session() as s:
        cs = ops_search.search_filtered(
            s, groups="", ungrouped=False,
            query=q.Group.model_validate(_tree(node)))
        return cs.residue


def _similar_case(client):
    uid = client.get("/api/items?page=1&page_size=1").json()["items"][0]["uid"]
    return {"type": "similar", "by": "color", "uid": uid, "tol": SIMILAR_TOL}


def test_every_condition_kind_compiles_the_way_we_think(rich):
    client, library = rich
    wrong = []
    for label, node, exact in CONDITIONS:
        if (_residue_of(library, node) is None) != exact:
            wrong.append(f"{label}: expected exact={exact}")
    # `SIMILAR:` resolves to an id set, so it compiles — the guarantee the
    # 12 band keys buy is what makes that affordable, and losing it would
    # turn every colour search into a scan of the library.
    if _residue_of(library, _similar_case(client)) is not None:
        wrong.append("similar: expected exact=True")
    assert not wrong, wrong


def test_every_condition_matches_something(rich):
    """The premise of everything above it. A condition that matches nothing
    exercises neither the clause nor the residue, so a table of fast empty
    answers would pass every assertion here while measuring nothing."""
    client, _ = rich
    empty = []
    for label, node, _exact in CONDITIONS + [("similar", _similar_case(client),
                                              True)]:
        r = client.post("/api/items/query",
                        json={"query": _tree(node), "page": 1,
                              "page_size": 60})
        assert r.status_code == 200, (label, r.text)
        total = r.json()["total"]
        if not 0 < total < N_ITEMS:
            empty.append(f"{label}: {total} of {N_ITEMS}")
    assert not empty, empty


def test_every_condition_pages_in_bounded_sql(rich):
    """One page is a LIMITed read whatever the filter is.

    The residue path materialises the candidates it must evaluate — that is
    what makes it the slow one — but the PAGE it then serves is still a
    window over the matched ids, so no condition may answer a page by
    selecting the items table and slicing in Python.
    """
    client, library = rich
    slow = []
    for label, node, exact in CONDITIONS + [("similar", _similar_case(client),
                                             True)]:
        body = {"query": _tree(node), "page": 1, "page_size": 60}
        with StatementLog(library.db.engine) as log:
            t0 = time.monotonic()
            r = client.post("/api/items/query", json=body)
            dt = time.monotonic() - t0
        assert r.status_code == 200, (label, r.text)
        assert any("LIMIT" in s for s in log.statements), label
        # PER ITEM, not absolute: both halves of this are linear in the
        # scope by construction — an exact clause pays a count over it, the
        # residue pays ~30 µs of Python per candidate — so a ceiling written
        # for 50,000 items is a failure waiting for anybody who raises
        # `MEDIA_COMPOST_PERF_ITEMS` (at 400,000 the two residue cases
        # measure 10.5 s and 9.9 s, which is exactly what the residue costs
        # and says nothing new). Scaled, the bound still separates the two
        # classes at every size: a condition that stops compiling moves by
        # ~65x, and this allows 2x.
        scale = max(1.0, N_ITEMS / 50_000)
        ceiling = (2.0 if exact else 4.0) * scale
        if timed_runs() and dt > ceiling:
            slow.append(f"{label}: {dt:.2f}s > {ceiling:.1f}s")
    assert not slow, slow


def _counts_the_view(sql: str) -> bool:
    """Is this statement the VIEW's own count?

    Named rather than "starts with select count(", which it was until the
    compiler started asking how many rows a tag has before choosing its
    clause shape (`prefilter._direct_tag`): that probe is a count too, over
    `item_tags`, and it is the cheap half of what makes a filtered view fast
    — so a test about counting the view twice must say the view.
    """
    head = " ".join(sql.split()).lower()
    return head.startswith("select count(") and " from items" in head


def test_a_searched_view_counts_itself_ONCE(rich):
    """The COUNT is what a filtered view costs — the page under it is an
    index range — so it is memoised on the library revision like every other
    scope count. Asked again for the same search, it is not a query at all.
    """
    client, library = rich
    body = {"query": _tree({"type": "place", "value": ""}),
            "page": 1, "page_size": 60}
    client.post("/api/items/query", json=body)      # warm
    with StatementLog(library.db.engine) as log:
        t0 = time.monotonic()
        r = client.post("/api/items/query", json=body)
        warm = time.monotonic() - t0
    assert r.status_code == 200
    assert not [s for s in log.statements if _counts_the_view(s)], log.statements
    assert not timed_runs() or warm < 0.5, f"warm search took {warm:.2f}s"

    # …and it is counted AGAIN once the library has moved, or the figure
    # would outlive what it describes.
    library.db.commits += 1
    with StatementLog(library.db.engine) as log:
        client.post("/api/items/query", json=body)
    assert [s for s in log.statements if _counts_the_view(s)], log.statements
