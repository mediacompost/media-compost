"""`COLORLIKE:` — a palette like one particular picture's.

Likeness is pairwise, so this is the one condition that names another item.
Three things are worth pinning beyond "it finds the right rows": that the two
ways of resolving it agree (a small tolerance ENUMERATES the neighbourhood
and looks it up by index; a wide one scans every signature), that it compiles
**exactly** at any size — the obvious reading is that Hamming distance has no
SQL and must therefore be a residue scan, and the residue is precisely what
made this unusable on a large library — and that an out-of-range tolerance is
refused rather than clamped.

There was a `SIMILAR:` beside it over the perceptual hash. It is gone with the
grid action that was its only door: the importer FOLDS a re-encode, a crop and
a rotation onto the item they match, so on an imported library the search
reliably found that item and nothing else.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from media_compost import prefilter
from media_compost import query as q
from media_compost.ui.config import UiConfig
from media_compost.db import File, Item
from media_compost.searchctx import (
    ENUMERATED_TOL, SIG_BITS, load_similar_sets, neighbourhood,
)
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

#: The pivot's signature, and the others as N bits away from it. Bits well
#: apart so no two rows are nearer each other than to the pivot.
PIVOT_SIG = 0b1111 | (1 << 40)


def _sig(bits_off: int) -> int:
    v = PIVOT_SIG
    for b in range(bits_off):
        v ^= 1 << (4 + b * 3)
    return v


# name -> colour signature (None = a video, which carries none)
ROWS = {
    "pivot": _sig(0),
    "same": _sig(0),          # a re-encode: the identical palette
    "one-off": _sig(1),
    "three-off": _sig(3),
    "five-off": _sig(5),
    "far": 0b1111 << 20,
    "video": None,
}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    cfg = UiConfig(data_dir=tmp_path_factory.mktemp("simlib") / "data")
    library = Library(cfg)
    with library.db.session() as s:
        for i, (name, sig) in enumerate(ROWS.items()):
            it = Item(uid=f"s-{i:02d}", name=name,
                      kind="video" if name == "video" else "image")
            s.add(it)
            s.flush()
            f = File(item_id=it.id, sha256=f"sha{i}", path=f"files/{i}.png",
                     number=1, width=100, height=100, bytes=10, format="png",
                     color_sig=sig)
            s.add(f)
            s.flush()
            it.active_file_id = f.id
        s.commit()
    app.dependency_overrides[get_library] = lambda: library
    deps.reset_library()
    with TestClient(app) as c:
        yield c, library
    app.dependency_overrides.clear()


def _names(client, tree):
    r = client.post("/api/items/query",
                    json={"query": tree, "page_size": 50})
    assert r.status_code == 200, r.text
    return {i["name"] for i in r.json()["items"]}


def _sim(uid="s-00", tol=None, have=True, by="color"):
    cond = {"type": "similar", "by": by, "uid": uid, "have": have}
    if tol is not None:
        cond["tol"] = tol
    return {"type": "group", "op": "and", "children": [cond]}


# ---- the neighbourhood ------------------------------------------------------


@pytest.mark.parametrize("tol", [0, 1, 2, 3])
def test_the_enumerated_neighbourhood_is_exactly_the_popcount_answer(tol):
    """The fast path replaces a popcount over every signature, so it has to
    BE that answer — an off-by-one here narrows a search with nothing to see.
    Checked in a small space, where brute force is possible at all."""
    sig = 0b1011001
    got = neighbourhood(sig, tol)
    assert len(got) == len(set(got)), "a signature enumerated twice"
    # Every value it produces is within the tolerance...
    assert all((v ^ sig).bit_count() <= tol for v in got)
    # ...and every value within it is produced (over the low 12 bits, whose
    # 4096 values can be walked; the rule does not depend on which bits).
    want = {sig ^ x for x in range(1 << 12)
            if x.bit_count() <= tol}
    assert want <= set(got)
    assert len(got) == sum(_choose(SIG_BITS, k) for k in range(tol + 1))


def _choose(n: int, k: int) -> int:
    from math import comb
    return comb(n, k)


# ---- matching ---------------------------------------------------------------


def test_a_tolerance_of_zero_finds_only_the_identical_palette(client):
    c, _ = client
    assert _names(c, _sim(tol=0)) == {"pivot", "same"}


def test_widening_the_tolerance_takes_in_the_near_ones(client):
    c, _ = client
    assert _names(c, _sim(tol=1)) == {"pivot", "same", "one-off"}
    assert _names(c, _sim(tol=3)) == {"pivot", "same", "one-off", "three-off"}


def test_THE_TWO_RESOLUTION_PATHS_ANSWER_THE_SAME_QUESTION(client):
    """One condition, two mechanisms, told apart by the tolerance alone — so
    the seam is exactly where a wrong answer would hide. Either side of it,
    against the popcount both are supposed to compute."""
    _c, lib = client
    with lib.db.session() as s:
        for tol in (ENUMERATED_TOL, ENUMERATED_TOL + 1):
            cond = q.SimilarCond(uid="s-00", tol=tol)
            got = load_similar_sets(s, [cond])[cond.key()]
            want = {
                iid for iid, sig in s.execute(
                    prefilter.sa.select(File.item_id, File.color_sig)
                    .where(File.color_sig.is_not(None))).all()
                if (sig ^ PIVOT_SIG).bit_count() <= tol
            }
            assert got == want, f"paths disagree at tolerance {tol}"


def test_the_pivot_matches_itself(client):
    """It is within zero of itself, and excluding it would make "what else is
    coloured like this" answer with a list the picture itself is missing
    from."""
    c, _ = client
    assert "pivot" in _names(c, _sim(tol=3))


def test_a_video_never_matches_because_it_has_no_signature(client):
    c, _ = client
    assert "video" not in _names(c, _sim(tol=16))


def test_negation_is_the_complement_within_the_scope(client):
    c, _ = client
    near = _names(c, _sim(tol=1))
    far = _names(c, _sim(tol=1, have=False))
    assert near & far == set()
    assert near | far == set(ROWS)


def test_an_unknown_pivot_matches_nothing_rather_than_everything(client):
    """The direction that matters: a uid nobody has must not read as "no
    restriction" and hand back the library."""
    c, _ = client
    assert _names(c, _sim(uid="no-such-uid", tol=3)) == set()
    assert _names(c, _sim(uid="no-such-uid", tol=3, have=False)) == set(ROWS)


def test_the_bare_form_is_the_measured_default(client):
    """No `tol` means `query.DEFAULT_COLOR_TOL`, which is 2 because the same
    picture re-encoded lands at distance 0 and 3 more than doubles the share
    of unrelated pictures admitted. It USED to be the library's
    `phash_threshold` — a 256-bit near-dup setting read against a 56-bit
    palette hash, which on real signatures admitted 72% of unrelated pairs.
    """
    from media_compost.query import DEFAULT_COLOR_TOL

    c, lib = client
    assert DEFAULT_COLOR_TOL == 2
    assert DEFAULT_COLOR_TOL != lib.config.phash_threshold
    assert _names(c, _sim()) == _names(c, _sim(tol=DEFAULT_COLOR_TOL))
    assert _names(c, _sim()) != _names(c, _sim(tol=lib.config.phash_threshold))


# ---- how it compiles --------------------------------------------------------


def test_it_compiles_exactly_so_the_residue_never_runs(client):
    """The whole reason this is cheap. `searchctx` resolves the pivot to an
    id set, so what reaches SQL is membership — and an `IN (...)` is exact,
    not a superset the Python evaluator has to re-check."""
    _c, lib = client
    with lib.db.session() as s:
        tree = q.Group(op="and", children=[q.SimilarCond(uid="s-00", tol=3)])
        similar = load_similar_sets(s, q.similar_conditions(tree))
        clause, residue = prefilter.compile_query(s, tree, similar=similar)
        assert clause is not None
        assert residue is None, "a resolved pivot must not fall to the residue"


def test_A_BIG_SET_STILL_COMPILES_EXACTLY_through_the_temp_table(client):
    """The bug this feature actually had on a large library.

    An id set past `_MAX_IDS` used to fall back to the residue, which
    materializes every candidate the rest of the query admits and evaluates
    it in Python — so a colour search admitting a few percent of a
    million-item library paid a whole-library pass PER PAGE (measured: 5.0 s
    against 1.1 s for the same search one bit tighter, purely because the set
    crossed the guard). A join reads it in SQL like any other set.
    """
    _c, lib = client
    with lib.db.session() as s:
        ids = set(range(1, prefilter._MAX_IDS + 500))
        key = "color:s-00:3"
        clause, residue = prefilter.compile_query(
            s, q.Group(op="and", children=[q.SimilarCond(uid="s-00", tol=3)]),
            similar={key: ids})
        assert residue is None, "a big set must not fall to the residue"
        # And the clause really reads those ids back.
        got = set(s.execute(
            prefilter.sa.select(Item.id).where(clause)).scalars().all())
        assert got == {i for i in ids if i <= len(ROWS)}


def test_two_pivots_do_not_overwrite_each_others_temp_rows(client):
    """The temp table is keyed, because a query may hold two of these and one
    table per condition is not something a temp schema can grow."""
    _c, lib = client
    with lib.db.session() as s:
        a = prefilter.materialize_similar(s, "color:a:2", {1, 2, 3})
        b = prefilter.materialize_similar(s, "color:b:2", {3, 4})
        assert set(s.execute(
            prefilter.sa.select(Item.id).where(a)).scalars().all()) == {1, 2, 3}
        assert set(s.execute(
            prefilter.sa.select(Item.id).where(b)).scalars().all()) == {3, 4}


def test_without_resolved_sets_it_refuses_to_compile(client):
    """A caller that compiles a tree it never loaded sets for must get a
    residue, not a clause claiming everything matches."""
    _c, lib = client
    with lib.db.session() as s:
        tree = q.Group(op="and", children=[q.SimilarCond(uid="s-00", tol=3)])
        clause, residue = prefilter.compile_query(s, tree)
        assert residue is not None


# ---- refusals ---------------------------------------------------------------


@pytest.mark.parametrize("tol", [17, -1])
def test_an_out_of_range_tolerance_is_refused_not_clamped(client, tol):
    c, _ = client
    r = c.post("/api/items/query", json={"query": _sim(tol=tol)})
    assert r.status_code == 400
    assert "tolerance" in r.json()["detail"]


def test_a_tolerance_AT_the_cap_still_answers(client):
    from media_compost.query import MAX_SIMILAR_TOL

    c, _ = client
    assert _names(c, _sim(tol=MAX_SIMILAR_TOL)) >= {
        "pivot", "same", "one-off", "three-off"}


def test_THE_RETIRED_VISUAL_SPACE_IS_REFUSED_BY_NAME(client):
    """`by` keeps one value rather than going away, so a stored tree naming
    the retired space is a 422 naming the field — not a silently different
    answer, which is what an ignored key would be (`CondModel` is strict for
    exactly this reason)."""
    c, _ = client
    r = c.post("/api/items/query", json={"query": _sim(by="visual", tol=3)})
    assert r.status_code == 422
    assert "by" in r.text


def test_the_SIMILAR_keyword_is_nobodys_keyword_now():
    """It falls through to a tag name, which matches nothing — a search that
    visibly finds no pictures rather than one quietly answering something
    else."""
    from media_compost.querystring import parse

    tree = parse("SIMILAR:a1b2c3d4")
    assert [c.type for c in tree.children] == ["tag"]
