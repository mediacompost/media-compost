"""Rankings — pairwise-comparison axes, and nothing about tags.

**A RANKING ORDERS PICTURES AND TAGS NONE OF THEM** (rung v31). It used to
own a namespace and materialize a score tag per placed picture; what these
pin now is what is left, which is what a ranking always was: a judgment
chain must come out as ordered BUCKETS (read off the detail histogram,
fitted on the way out and stored nowhere), the pool (scope ∩ session view,
dismissals honoured), the pools (fitted apart, one judgment per pool),
History (every mutation logs, and the judgment revert takes the evidence
back), and the sidecar round trip (judgments and dismissals travel; there
is nothing derived left to refit).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.testing import make_image
from media_compost.ui.config import UiConfig
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(8):
        make_image(src / f"p{i}.png", seed=i, size=(220, 160))
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([src], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib
        yield c
    app.dependency_overrides.clear()


def _items(client) -> list[int]:
    return sorted(it["id"] for it in client.get("/api/items").json()["items"])


def _mk(client, name="Quality", **kw):
    rows = client.post("/api/rankings", json={"name": name, **kw})
    assert rows.status_code == 200, rows.text
    return next(r for r in rows.json() if r["name"] == name)


def _chain(client, rid: int, ids: list[int]) -> None:
    """Judge a strict order: each item beats the one before it."""
    for k in range(len(ids) - 1):
        r = client.post(f"/api/rankings/{rid}/judge",
                        json={"a_item_id": ids[k + 1], "b_item_id": ids[k],
                              "outcome": "a"})
        assert r.status_code == 200, r.text


def _placed(client, rid: int, pool: int | None = None) -> dict[int, int]:
    """item id -> the BUCKET its standing lands in, off the detail
    histogram. Nothing is written any more, so the histogram is the answer;
    a bucket lists only its top few samples, which for these eight-picture
    fixtures is every one of them."""
    d = client.get(f"/api/rankings/{rid}/detail").json()
    buckets = d["buckets"]
    if pool is not None:
        lg = next(x for x in d["pools"] if x["id"] == pool)
        buckets = lg["buckets"]
    out: dict[int, int] = {}
    for b in buckets:
        for ref in b["samples"]:
            out[ref["item_id"]] = b["bucket"]
    return out


def _scored(client, rid: int, pool: int | None = None) -> int:
    d = client.get(f"/api/rankings/{rid}/detail").json()
    if pool is None:
        return int(d["scored"])
    return int(next(x for x in d["pools"] if x["id"] == pool)["scored"])


# ---- the standings ------------------------------------------------------------


def test_a_judgment_chain_becomes_ordered_buckets(client):
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids)
    assert _scored(client, row["id"]) == len(ids)
    placed = _placed(client, row["id"])
    buckets = [placed[i] for i in ids]
    assert buckets == sorted(buckets), "the fit lost the judged order"
    # Endpoint-inclusive: the best picture is a 9 and the worst a 0, however
    # small the library — equal-population percentiles never hand out the top
    # bucket below ten items, and "my best picture is an 8" is the
    # arithmetic showing through.
    assert buckets[0] == 0 and buckets[-1] == 9
    # AND NOTHING IS ON THE PICTURES. A ranking tags none of them; what it
    # has to show for itself is the standings above.
    assert all(not it.get("direct_tags")
               for it in client.get("/api/items").json()["items"])
    # The list counts the DISTINCT items the judgments name (either side) —
    # the chain touches every item, each item at most twice.
    lst = client.get("/api/rankings").json()
    mine = next(r for r in lst if r["id"] == row["id"])
    assert mine["items"] == len(ids)
    assert mine["judgments"] == len(ids) - 1


def test_the_detail_histogram_counts_what_the_standings_say(client):
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids)
    d = client.get(f"/api/rankings/{row['id']}/detail").json()
    assert sum(b["count"] for b in d["buckets"]) == len(ids)
    assert d["scored"] == len(ids)
    assert all(len(b["samples"]) <= b["count"] for b in d["buckets"])


def test_not_applicable_leaves_scoring_and_the_pair_pool(client):
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids)
    r = client.post(f"/api/rankings/{row['id']}/dismiss",
                    json={"item_id": ids[3]})
    assert r.status_code == 200
    placed = _placed(client, row["id"])
    assert ids[3] not in placed and len(placed) == len(ids) - 1
    d = client.get(f"/api/rankings/{row['id']}/detail").json()
    assert [x["item_id"] for x in d["not_applicable"]] == [ids[3]]
    # The way back exists, and the fit takes it straight away.
    client.post(f"/api/rankings/{row['id']}/undismiss",
                json={"item_id": ids[3]})
    assert ids[3] in _placed(client, row["id"])


def test_the_pair_endpoint_draws_from_the_scope(client):
    ids = _items(client)
    row = _mk(client)
    r = client.post(f"/api/rankings/{row['id']}/pair", json={})
    body = r.json()
    assert r.status_code == 200 and body["a"] and body["b"]
    assert body["pool"] == len(ids)
    # A selection is the session's PRIORITY, never a fence around the pool:
    # the pair leads with a selected item, its partner comes from the whole
    # pool, and the pool count says nothing was narrowed. (Two selected
    # items used to make a one-pair session that ended immediately.)
    two = ids[:2]
    body = client.post(f"/api/rankings/{row['id']}/pair",
                       json={"items": two}).json()
    assert {body["a"]["item_id"], body["b"]["item_id"]} & set(two)
    assert body["pool"] == len(ids)
    # Even a SINGLE selected item seeds a session — it is compared against
    # the rest of the pool rather than starving a one-item one.
    body = client.post(f"/api/rankings/{row['id']}/pair",
                       json={"items": ids[:1]}).json()
    assert body["a"] and body["b"]
    assert ids[0] in {body["a"]["item_id"], body["b"]["item_id"]}


def test_a_skipped_pair_is_set_aside(client):
    ids = _items(client)
    row = _mk(client)
    two = ids[:2]
    client.post(f"/api/rankings/{row['id']}/judge",
                json={"a_item_id": two[0], "b_item_id": two[1],
                      "outcome": "skip"})
    body = client.post(f"/api/rankings/{row['id']}/pair",
                       json={"items": two}).json()
    # The skipped pair itself never comes back; the priority items go on
    # pairing with the rest of the pool instead.
    assert body["a"] and body["b"]
    assert {body["a"]["item_id"], body["b"]["item_id"]} != set(two)


def test_every_kind_rates_and_a_sequence_card_carries_its_pages(client):
    """The pool is no longer pictures-only: a sequence container joins it,
    its ref says so (`kind`), and carries member refs for the card to flip
    through — pages in reading order, each with a file to draw."""
    lib = client.lib
    from media_compost.ops import Ctx, sequences as ops_sequences

    ids = _items(client)
    with lib.db.session() as s:
        ops_sequences.create(Ctx(s), ids[:3], name="chapter")
        s.commit()
    row = _mk(client)
    # The pool is the VIEW: all 8 pictures plus the container by default,
    # and the view's hide-sequenced toggle folds the pages away.
    body = client.post(f"/api/rankings/{row['id']}/pair", json={}).json()
    assert body["pool"] == 9
    body = client.post(f"/api/rankings/{row['id']}/pair",
                       json={"hide_sequenced": True}).json()
    assert body["pool"] == 6
    refs = {}
    seen: set[int] = set()
    recent: list[list[int]] = []
    for _ in range(80):
        b = client.post(f"/api/rankings/{row['id']}/pair",
                        json={"recent": recent,
                              "hide_sequenced": True}).json()
        if not b.get("a"):
            break
        recent.append([b["a"]["item_id"], b["b"]["item_id"]])
        for side in (b["a"], b["b"]):
            refs[side["item_id"]] = side
            seen.add(side["item_id"])
    seq_refs = [r for r in refs.values() if r["kind"] == "sequence"]
    assert len(seq_refs) == 1
    (seq,) = seq_refs
    assert [m["item_id"] for m in seq["members"]] == ids[:3]
    assert all(m["file_id"] is not None for m in seq["members"])
    assert all(m["kind"] == "image" for m in seq["members"])
    # A member ref carries no members of its own — one level only.
    assert all(m["members"] == [] for m in seq["members"])
    # The session's own kind filter still narrows what a session rates.
    b = client.post(f"/api/rankings/{row['id']}/pair",
                    json={"kind": "image"}).json()
    assert b["pool"] == 8


def test_a_stored_scope_limits_pool_and_scores(client):
    ids = _items(client)
    # Tag half the pictures and scope the ranking to them.
    client.post("/api/tags/quick-assign", json={
        "item_ids": ids[:4], "positive": ["manga"], "negative": []})
    row = _mk(client, scope="manga")
    body = client.post(f"/api/rankings/{row['id']}/pair", json={}).json()
    assert body["pool"] == 4
    # An unparseable scope is refused up front, not stored meaning
    # "everything".
    r = client.post("/api/rankings", json={"name": "Broken",
                                           "scope": "GROUP:("})
    assert r.status_code == 400


# ---- history ------------------------------------------------------------------


def test_every_ranking_mutation_logs_and_the_judgment_revert_unasks_it(client):
    ids = _items(client)
    top = client.get("/api/history").json()["events"]
    newest = top[0]["id"] if top else 0
    row = _mk(client)
    _chain(client, row["id"], ids)
    client.post(f"/api/rankings/{row['id']}/dismiss",
                json={"item_id": ids[0]})
    client.patch(f"/api/rankings/{row['id']}", json={"name": "Q2"})
    events = client.get(f"/api/history?after_id={newest}").json()["events"]
    got = {e["action"] for e in events}
    assert {"create_ranking", "judge_ranking", "dismiss_ranking_item",
            "edit_ranking"} <= got
    before = _placed(client, row["id"])
    assert before, "nothing placed"
    # Reverting the newest judgment un-asks the question, and the standings
    # follow the evidence because they ARE the evidence, fitted on read.
    judgment = next(e for e in events if e["action"] == "judge_ranking")
    r = client.post("/api/history/revert", json={"event_ids": [judgment["id"]]})
    assert r.status_code == 200, r.text
    after = _placed(client, row["id"])
    assert after != before, "the revert left the standings where they were"


def test_delete_ranking_takes_its_judgments_and_nothing_else(client):
    """A ranking mints nothing, so a delete costs the evidence and no tag.
    What a rating session was SPENT on — whatever the Assign-ratings action
    wrote — is somebody's own assignment and stays exactly where it is."""
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids)
    client.post("/api/tags/quick-assign", json={
        "item_ids": ids[:2], "positive": ["excellent"], "negative": []})
    assert _placed(client, row["id"])
    r = client.delete(f"/api/rankings/{row['id']}")
    assert r.status_code == 200 and r.json() == []
    left = {t["name"] for t in client.get("/api/tags").json()}
    assert "excellent" in left


# ---- the sidecar round trip ---------------------------------------------------


def test_judgments_round_trip_and_the_standings_come_with_them(client, tmp_path):
    from media_compost import open_library

    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids)
    client.post(f"/api/rankings/{row['id']}/dismiss",
                json={"item_id": ids[0]})

    with open_library(tmp_path / "restored", source="cli") as fresh:
        stats = fresh.merge_library(tmp_path / "data")
        assert not stats.errors, stats.errors
        # The axis, its judgments and the dismissal all came back — the
        # ranking matched by NAME, which is its portable identity.
        with fresh.transaction():
            pass
    from media_compost.config import Config
    from media_compost.db import Database, Ranking, RankingJudgment
    from sqlalchemy import func, select
    db = Database(Config(data_dir=tmp_path / "restored"))
    with db.session() as s:
        got = s.execute(select(Ranking).where(
            Ranking.name == "Quality")).scalars().first()
        assert got is not None
        n = s.execute(select(func.count()).select_from(RankingJudgment)
                      .where(RankingJudgment.ranking_id == got.id)
                      ).scalar_one()
        assert n == len(ids) - 1
    db.engine.dispose()


def test_the_bucket_range_is_the_rankings_own(client):
    """The SCALE the standings are spread over: 1–5 and the best of the
    chain reads 5, 0–9 and it reads 9. A range edit costs nothing now — the
    judgments never moved and the fit is on the way out — and its revert
    puts the old range back. Nonsense ranges are refused up front."""
    ids = _items(client)
    row = _mk(client, name="Stars", bucket_lo=1, bucket_hi=5)
    assert (row["bucket_lo"], row["bucket_hi"]) == (1, 5)

    _chain(client, row["id"], ids)
    placed = _placed(client, row["id"])
    assert placed[ids[-1]] == 5   # endpoint-inclusive at any range
    assert placed[ids[0]] == 1

    hist_before = client.get("/api/history").json()["events"][0]["id"]
    r = client.patch(f"/api/rankings/{row['id']}",
                     json={"bucket_lo": 0, "bucket_hi": 9})
    assert r.status_code == 200
    assert _placed(client, row["id"])[ids[-1]] == 9

    # The detail's histogram runs over the ranking's own numbers.
    det = client.get(f"/api/rankings/{row['id']}/detail").json()
    assert [b["bucket"] for b in det["buckets"]] == list(range(0, 10))

    ev = [e for e in client.get("/api/history").json()["events"]
          if e["id"] > hist_before and e["action"] == "edit_ranking"]
    assert ev
    r = client.post("/api/history/revert", json={"event_ids": [ev[0]["id"]]})
    assert r.status_code == 200, r.text
    rows = {x["name"]: x for x in client.get("/api/rankings").json()}
    assert (rows["Stars"]["bucket_lo"], rows["Stars"]["bucket_hi"]) == (1, 5)
    assert _placed(client, row["id"])[ids[-1]] == 5

    # A range that runs nowhere is refused, not clamped.
    assert client.post("/api/rankings", json={
        "name": "Bad", "bucket_lo": 5, "bucket_hi": 5,
    }).status_code == 400
    assert client.post("/api/rankings", json={
        "name": "Bad2", "bucket_lo": 0, "bucket_hi": 101,
    }).status_code == 400


def test_removing_an_item_deletes_its_judgments_and_reverts_whole(client):
    """Take a picture out of the pool: every judgment it was part of goes,
    and the ONE event's revert puts them back — which is what lets the
    sidebar's undo bar offer it."""
    ids = _items(client)
    four = ids[:4]
    row = _mk(client)
    _chain(client, row["id"], four)
    assert len(_placed(client, row["id"])) == 4

    r = client.delete(f"/api/rankings/{row['id']}/items/{four[1]}")
    assert r.status_code == 200 and r.json()["removed"] == 2
    # Its two judgments went with it, so only the untouched pair still
    # places anything — and the removed item places nothing.
    assert sorted(_placed(client, row["id"])) == sorted(four[2:])

    ev = next(e for e in client.get("/api/history").json()["events"]
              if e["action"] == "remove_ranking_item")
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    assert len(_placed(client, row["id"])) == 4


def test_a_tie_is_evidence_that_pulls_two_items_together(client):
    """"About equal" (the overlay's ↑): half a win each in the fit, counted
    as a judgment by the pair selector — and two pictures whose ONLY
    evidence is a tie share one MID bucket, not the 0-and-9 split the by-id
    tiebreak used to hand out (the loudest possible way to say the opposite
    of what was judged)."""
    ids = _items(client)
    a, b, c, d = ids[:4]
    row = _mk(client)
    r = client.post(f"/api/rankings/{row['id']}/judge",
                    json={"a_item_id": a, "b_item_id": b, "outcome": "tie"})
    assert r.status_code == 200, r.text
    placed = _placed(client, row["id"])
    assert placed[a] == placed[b] == 4

    # Beside decisive evidence the tie still pulls together: c beats d and
    # ties with a — so c tops the pool and a sits ABOVE the b it tied with
    # only as far as the shared evidence allows, never at the bottom.
    client.post(f"/api/rankings/{row['id']}/judge",
                json={"a_item_id": c, "b_item_id": d, "outcome": "a"})
    client.post(f"/api/rankings/{row['id']}/judge",
                json={"a_item_id": c, "b_item_id": a, "outcome": "tie"})
    num = _placed(client, row["id"])
    assert num[c] == 9 and num[d] == 0
    assert num[d] < num[b] <= num[a] <= num[c]


def test_an_exhausted_session_reports_the_standings(client):
    """With every pair judged, the pair endpoint answers a SUMMARY — the
    pool's units best first with the BUCKET each stands in — computed on
    read and written nowhere. A ranking tags nothing; this is what the
    session has to show for itself."""
    import itertools

    ids = _items(client)
    two = ids[:2]
    row = _mk(client)
    client.post(f"/api/rankings/{row['id']}/judge", json={
        "a_item_id": two[1], "b_item_id": two[0], "outcome": "a"})
    # The overlay reports every pair the session has shown; a session ends
    # when nothing outside that list is left. (A selection no longer fences
    # the pool, so exhaustion means every PAIR of the pool is on the list.)
    body = client.post(f"/api/rankings/{row['id']}/pair",
                       json={"recent": [[a, b] for a, b
                                        in itertools.combinations(ids, 2)]}
                       ).json()
    assert body["a"] is None
    got = [(e["ref"]["item_id"], e["bucket"]) for e in body["summary"]]
    assert got == [(two[1], 9), (two[0], 0)]


# ---- pools ------------------------------------------------------------------
#
# A ranking is computed over one or more POOLS — populations with standings
# of their own under the one range. Membership is derived from the
# judgments, the first pool is born unnamed with the ranking, and one
# judgement may be written into several pools at once.


def _judge(client, rid: int, a: int, b: int, outcome: str = "a",
           pools: list[int] | None = None) -> dict:
    body = {"a_item_id": a, "b_item_id": b, "outcome": outcome}
    if pools is not None:
        body["pool_ids"] = pools
    r = client.post(f"/api/rankings/{rid}/judge", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _chain_in(client, rid: int, ids: list[int], pools: list[int]) -> None:
    for k in range(len(ids) - 1):
        _judge(client, rid, ids[k + 1], ids[k], pools=pools)


def _scores_of(client, rid: int) -> dict[int, set[int]]:
    """item id -> the buckets it stands in ACROSS the pools. An item
    rated in two of them has a standing in each, which need not agree."""
    d = client.get(f"/api/rankings/{rid}/detail").json()
    out: dict[int, set[int]] = {}
    for lg in d["pools"]:
        for b in lg["buckets"]:
            for ref in b["samples"]:
                out.setdefault(ref["item_id"], set()).add(b["bucket"])
    return out


def _row(client, rid: int) -> dict:
    return next(r for r in client.get("/api/rankings").json()
                if r["id"] == rid)


def _events(client, action: str) -> list[dict]:
    """Newest first — the endpoint's own order."""
    return [e for e in client.get("/api/history").json()["events"]
            if e["action"] == action]


def test_a_ranking_is_born_with_an_unnamed_pool_and_pools_are_managed(client):
    row = _mk(client)
    assert [lg["name"] for lg in row["pools"]] == [""]
    default = row["pools"][0]["id"]

    r = client.post(f"/api/rankings/{row['id']}/pools",
                    json={"name": "Photos"})
    assert r.status_code == 200, r.text
    mine = _row(client, row["id"])
    assert [lg["name"] for lg in mine["pools"]] == ["", "Photos"]
    photos = mine["pools"][1]["id"]
    # Refusals, each by name: a taken name, an empty one, another
    # ranking's pool.
    assert client.post(f"/api/rankings/{row['id']}/pools",
                       json={"name": "Photos"}).status_code == 409
    assert client.post(f"/api/rankings/{row['id']}/pools",
                       json={"name": "  "}).status_code == 400
    other = _mk(client, "Style")
    assert client.patch(f"/api/rankings/{other['id']}/pools/{photos}",
                        json={"name": "x"}).status_code == 404
    # A rename, and its revert.
    assert client.patch(f"/api/rankings/{row['id']}/pools/{photos}",
                        json={"name": "Photographs"}).status_code == 200
    assert [lg["name"] for lg in _row(client, row["id"])["pools"]] \
        == ["", "Photographs"]
    ev = _events(client, "edit_ranking_pool")[0]
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    assert [lg["name"] for lg in _row(client, row["id"])["pools"]] \
        == ["", "Photos"]
    # A created pool reverts while it is still empty…
    r = client.post(f"/api/rankings/{row['id']}/pools",
                    json={"name": "Scratch"})
    ev = _events(client, "create_ranking_pool")[0]
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    assert [lg["name"] for lg in _row(client, row["id"])["pools"]] \
        == ["", "Photos"]
    # …and deleting one takes its judgments with it, refits, and is not
    # something History offers back.
    ids = _items(client)
    _chain_in(client, row["id"], ids[:4], [photos])
    assert len(_scores_of(client, row["id"])) == 4
    r = client.delete(f"/api/rankings/{row['id']}/pools/{photos}")
    assert r.status_code == 200, r.text
    assert _scores_of(client, row["id"]) == {}
    ev = _events(client, "delete_ranking_pool")[0]
    assert ev["data"]["judgments"] == 3 and not ev["revertible"]
    # The last pool stays — a ranking always has one.
    r = client.delete(f"/api/rankings/{row['id']}/pools/{default}")
    assert r.status_code == 400, r.text
    assert [lg["name"] for lg in _row(client, row["id"])["pools"]] == [""]


def test_pools_are_fitted_apart_and_an_item_may_stand_in_two(client):
    """The same four pictures ordered one way in one pool and the other
    way in another: the best of one is the worst of the other, so the item
    has TWO standings — and where two pools agree, one number."""
    ids = _items(client)
    four = ids[:4]
    row = _mk(client)
    a = row["pools"][0]["id"]
    rows = client.post(f"/api/rankings/{row['id']}/pools",
                       json={"name": "B"}).json()
    b = next(lg for lg in next(r for r in rows if r["id"] == row["id"])
             ["pools"] if lg["name"] == "B")["id"]
    _chain_in(client, row["id"], four, [a])
    _chain_in(client, row["id"], list(reversed(four)), [b])
    scores = _scores_of(client, row["id"])
    assert scores[four[0]] == {0, 9}
    assert scores[four[-1]] == {0, 9}
    # The list counts per pool, the detail draws one histogram per pool
    # and keeps the first pool's as the top-level answer.
    mine = _row(client, row["id"])
    assert [lg["judgments"] for lg in mine["pools"]] == [3, 3]
    assert mine["judgments"] == 6 and mine["items"] == 4
    d = client.get(f"/api/rankings/{row['id']}/detail").json()
    assert [lg["name"] for lg in d["pools"]] == ["", "B"]
    assert all(lg["scored"] == 4 for lg in d["pools"])
    assert d["buckets"] == d["pools"][0]["buckets"]
    # Agreement collapses to one row: the same order in both pools.
    other = _mk(client, "Grade")
    ga = other["pools"][0]["id"]
    rows = client.post(f"/api/rankings/{other['id']}/pools",
                       json={"name": "B"}).json()
    gb = next(lg for lg in next(r for r in rows if r["id"] == other["id"])
              ["pools"] if lg["name"] == "B")["id"]
    _chain_in(client, other["id"], four, [ga, gb])
    agreed = _scores_of(client, other["id"])
    assert all(len(v) == 1 for v in agreed.values()), agreed


def test_one_judgement_writes_every_picked_pool_and_undoes_as_a_fan(client):
    ids = _items(client)
    row = _mk(client)
    a = row["pools"][0]["id"]
    rows = client.post(f"/api/rankings/{row['id']}/pools",
                       json={"name": "B"}).json()
    b = next(lg for lg in next(r for r in rows if r["id"] == row["id"])
             ["pools"] if lg["name"] == "B")["id"]
    res = _judge(client, row["id"], ids[1], ids[0], pools=[a, b])
    assert len(res["judgment_ids"]) == 2 and len(res["event_ids"]) == 2
    assert res["judgment_id"] == res["judgment_ids"][0]
    assert res["event_id"] == res["event_ids"][0]
    mine = _row(client, row["id"])
    assert [lg["judgments"] for lg in mine["pools"]] == [1, 1]
    assert mine["judgments"] == 2
    events = _events(client, "judge_ranking")
    assert {e["data"]["pool_id"] for e in events} == {a, b}
    # The whole fan reverts, which is what the overlay's undo sends.
    assert client.post("/api/history/revert",
                       json={"event_ids": res["event_ids"]}).status_code == 200
    assert _row(client, row["id"])["judgments"] == 0
    # Naming no pool means the default one — every caller before pools.
    _judge(client, row["id"], ids[1], ids[0])
    assert [lg["judgments"] for lg in _row(client, row["id"])["pools"]] \
        == [1, 0]


def test_the_pair_and_the_summary_read_the_picked_pools_only(client):
    ids = _items(client)
    row = _mk(client)
    a = row["pools"][0]["id"]
    rows = client.post(f"/api/rankings/{row['id']}/pools",
                       json={"name": "B"}).json()
    b = next(lg for lg in next(r for r in rows if r["id"] == row["id"])
             ["pools"] if lg["name"] == "B")["id"]
    _chain_in(client, row["id"], ids[:3], [b])
    every = [[x, y] for i, x in enumerate(ids) for y in ids[i + 1:]]
    got = client.post(f"/api/rankings/{row['id']}/pair",
                      json={"recent": every, "pool_ids": [b]}).json()
    assert got["a"] is None
    assert sorted(e["ref"]["item_id"] for e in got["summary"]) == ids[:3]
    assert {e["pool_id"] for e in got["summary"]} == {b}
    assert {e["pool"] for e in got["summary"]} == {"B"}
    # The default pool has no evidence, so its standings are empty.
    got = client.post(f"/api/rankings/{row['id']}/pair",
                      json={"recent": every, "pool_ids": [a]}).json()
    assert got["a"] is None and got["summary"] == []
    # Both picked: the entries arrive pool by pool, in the order asked.
    got = client.post(f"/api/rankings/{row['id']}/pair",
                      json={"recent": every, "pool_ids": [b, a],
                            "summary_only": True}).json()
    assert [e["pool_id"] for e in got["summary"]] == [b, b, b]
    # A pool of another ranking is refused by name.
    other = _mk(client, "Style")
    r = client.post(f"/api/rankings/{other['id']}/pair",
                    json={"pool_ids": [b]})
    assert r.status_code == 404


def test_removing_an_item_spans_the_pools_and_reverts_each_into_its_own(client):
    ids = _items(client)
    four = ids[:4]
    row = _mk(client)
    a = row["pools"][0]["id"]
    rows = client.post(f"/api/rankings/{row['id']}/pools",
                       json={"name": "B"}).json()
    b = next(lg for lg in next(r for r in rows if r["id"] == row["id"])
             ["pools"] if lg["name"] == "B")["id"]
    _chain_in(client, row["id"], four, [a])
    _chain_in(client, row["id"], four, [b])
    r = client.delete(f"/api/rankings/{row['id']}/items/{four[1]}")
    assert r.status_code == 200 and r.json()["removed"] == 4
    assert [lg["judgments"] for lg in _row(client, row["id"])["pools"]] \
        == [1, 1]
    ev = _events(client, "remove_ranking_item")[0]
    assert {j["pool_id"] for j in ev["data"]["judgments"]} == {a, b}
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    assert [lg["judgments"] for lg in _row(client, row["id"])["pools"]] \
        == [3, 3]


def test_a_named_pool_travels_in_a_merge_and_the_unnamed_one_by_omission(
        client, tmp_path):
    from media_compost import open_library
    from media_compost.config import Config
    from media_compost.db import (Database, Item, RankingJudgment,
                                  RankingPool)
    from media_compost.itemdict import item_to_dict
    from sqlalchemy import select

    ids = _items(client)
    row = _mk(client)
    a = row["pools"][0]["id"]
    rows = client.post(f"/api/rankings/{row['id']}/pools",
                       json={"name": "Photos"}).json()
    photos = next(lg for lg in next(r for r in rows if r["id"] == row["id"])
                  ["pools"] if lg["name"] == "Photos")["id"]
    _chain_in(client, row["id"], ids[:4], [a])
    _chain_in(client, row["id"], ids[4:8], [photos])

    # The item dict names a pool ONLY when it is named — the unnamed
    # first pool is what an entry without the key means, which is what
    # keeps a single-pool library's dict what it always was.
    with client.lib.db.session() as s:
        in_default = s.get(Item, ids[1])
        in_photos = s.get(Item, ids[5])
        d1 = item_to_dict(s, in_default)["ranking_judgments"]
        d2 = item_to_dict(s, in_photos)["ranking_judgments"]
    assert d1 and all("pool" not in j for j in d1)
    assert d2 and all(j["pool"] == "Photos" for j in d2)

    with open_library(tmp_path / "restored", source="cli") as fresh:
        stats = fresh.merge_library(tmp_path / "data")
        assert not stats.errors, stats.errors
    db = Database(Config(data_dir=tmp_path / "restored"))
    with db.session() as s:
        pools = s.execute(select(RankingPool).order_by(RankingPool.id)
                            ).scalars().all()
        assert [lg.name for lg in pools] == ["", "Photos"]
        by_pool = {}
        for j in s.execute(select(RankingJudgment)).scalars().all():
            by_pool[j.pool_id] = by_pool.get(j.pool_id, 0) + 1
        assert by_pool == {pools[0].id: 3, pools[1].id: 3}
    db.engine.dispose()


def test_pools_keep_the_order_they_are_dragged_into(client):
    """The dialog's drag-reorder: the order given is the order listed and
    asked in, it must name every pool once, a new pool appends, and
    the one event reverts every position."""
    row = _mk(client)
    rid = row["id"]
    for name in ("B", "C"):
        client.post(f"/api/rankings/{rid}/pools", json={"name": name})
    ids = {lg["name"]: lg["id"] for lg in _row(client, rid)["pools"]}
    assert [lg["name"] for lg in _row(client, rid)["pools"]] == ["", "B", "C"]
    r = client.post(f"/api/rankings/{rid}/pools/order",
                    json={"pool_ids": [ids["C"], ids[""], ids["B"]]})
    assert r.status_code == 200, r.text
    assert [lg["name"] for lg in _row(client, rid)["pools"]] == ["C", "", "B"]
    # A partial or doubled order is refused; the same order logs nothing.
    assert client.post(f"/api/rankings/{rid}/pools/order",
                       json={"pool_ids": [ids["C"]]}).status_code == 400
    n = len(_events(client, "reorder_ranking_pools"))
    client.post(f"/api/rankings/{rid}/pools/order",
                json={"pool_ids": [ids["C"], ids[""], ids["B"]]})
    assert len(_events(client, "reorder_ranking_pools")) == n
    # A new pool appends after the dragged order.
    client.post(f"/api/rankings/{rid}/pools", json={"name": "D"})
    assert [lg["name"] for lg in _row(client, rid)["pools"]] \
        == ["C", "", "B", "D"]
    # The detail and the chooser's list read the same order.
    d = client.get(f"/api/rankings/{rid}/detail").json()
    assert [lg["name"] for lg in d["pools"]] == ["C", "", "B", "D"]
    ev = _events(client, "reorder_ranking_pools")[0]
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev["id"]]}).status_code == 200
    assert [lg["name"] for lg in _row(client, rid)["pools"]] \
        == ["", "B", "C", "D"]


def test_a_pool_scores_only_once_its_comparisons_could_order_its_pictures(
        client):
    """`buckets` spreads whatever it is handed over the whole range, so two
    answers would tag a best at 9 and a worst at 0. A pool materializes
    nothing until its comparisons reach `pictures - 1` — the fewest that
    could put them all in one chain — and the API says which state it is
    in, since the detail draws the histogram either way."""
    ids = _items(client)
    row = _mk(client)
    default = row["pools"][0]["id"]
    assert _row(client, row["id"])["pools"][0]["settled"] is False

    # One comparison over two pictures IS a chain of two, and settles them.
    _judge(client, row["id"], ids[1], ids[0])
    assert _row(client, row["id"])["pools"][0]["settled"] is True
    assert set(_scores_of(client, row["id"])) == {ids[0], ids[1]}

    # A THIRD picture judged against a fourth leaves four pictures on two
    # comparisons — two islands, whose order relative to each other is the
    # prior speaking. The standings are still DRAWN (the histogram is how
    # you watch the evidence come in, and nothing is written anywhere any
    # more); what the flag says is that they cannot be trusted yet.
    _judge(client, row["id"], ids[3], ids[2])
    assert _row(client, row["id"])["pools"][0]["settled"] is False
    assert set(_scores_of(client, row["id"])) == set(ids[:4])
    _judge(client, row["id"], ids[2], ids[1])
    assert _row(client, row["id"])["pools"][0]["settled"] is True
    assert set(_scores_of(client, row["id"])) == set(ids[:4])

    # The detail still draws the pool either way — the histogram is how
    # you watch the evidence come in.
    detail = client.get(f"/api/rankings/{row['id']}/detail").json()
    assert detail["pools"][0]["settled"] is True
    assert detail["pools"][0]["scored"] == 4


def test_a_skip_is_not_a_comparison_and_a_dismissed_picture_is_not_placed(
        client):
    ids = _items(client)
    row = _mk(client)
    _judge(client, row["id"], ids[1], ids[0])
    _judge(client, row["id"], ids[3], ids[2])
    # Two islands: not settled. A SKIP over the gap is not evidence, so it
    # does not settle them either.
    _judge(client, row["id"], ids[2], ids[1], outcome="skip")
    assert _row(client, row["id"])["pools"][0]["settled"] is False

    # Taking one island out of the axis leaves two pictures on one
    # comparison — which IS enough for the two that are left.
    for i in (ids[2], ids[3]):
        assert client.post(f"/api/rankings/{row['id']}/dismiss",
                           json={"item_id": i}).status_code == 200
    assert _row(client, row["id"])["pools"][0]["settled"] is True
    assert set(_scores_of(client, row["id"])) == {ids[0], ids[1]}


def test_the_reported_evidence_is_the_evidence_rebuild_itself_weighs(client):
    """The list and the detail count in SQL (a fit per pool would make the
    list a scan of the library); `rebuild` counts off its own fit. Two ways
    of gathering the same two numbers, so they are held to each other."""
    from media_compost.ops import rankings as ops_rankings
    from media_compost.ops.context import Ctx
    from media_compost import rankingmath

    ids = _items(client)
    row = _mk(client)
    a = row["pools"][0]["id"]
    rows = client.post(f"/api/rankings/{row['id']}/pools",
                       json={"name": "Photos"}).json()
    photos = next(lg for lg in next(r for r in rows if r["id"] == row["id"])
                  ["pools"] if lg["name"] == "Photos")["id"]
    _chain_in(client, row["id"], ids[:5], [a])
    _judge(client, row["id"], ids[6], ids[5], pools=[photos])
    _judge(client, row["id"], ids[7], ids[6], pools=[photos], outcome="skip")
    client.post(f"/api/rankings/{row['id']}/dismiss", json={"item_id": ids[0]})

    with client.lib.db.session() as s:
        ranking = ops_rankings.by_id(Ctx(session=s), row["id"])
        by_sql = ops_rankings.pool_evidence_of(s, [row["id"]])
        for lid in (a, photos):
            n, scores = ops_rankings._fitted(s, ranking, [lid])
            assert by_sql[lid] == (n, len(scores)), lid
            assert (ops_rankings.settled_pools(s, [row["id"]])[lid]
                    is (bool(scores)
                        and rankingmath.enough_comparisons(n, len(scores))))


# ---- the ranking as a library VIEW ------------------------------------------
#
# A standing is fitted on read and stored nowhere, so until 2026-09 nothing in
# search or sort could name one: the order existed only as a histogram on the
# rankings page. These pin the scope that lets the grid BE the ranking —
# membership, order, sections, and the whole-view writes that must not widen
# past it.


def test_a_ranking_scopes_the_grid_to_what_it_placed_best_first(client):
    ids = _items(client)
    row = _mk(client)
    # Four of the eight, in a strict chain: p3 beats p2 beats p1 beats p0.
    _chain(client, row["id"], ids[:4])

    r = client.post("/api/items/query",
                    json={"ranking": row["id"], "page_size": 100})
    assert r.status_code == 200, r.text
    got = [it["id"] for it in r.json()["items"]]

    # MEMBERSHIP IS WHAT A JUDGMENT SAYS: the four compared, and not the four
    # the ranking has never been shown.
    assert sorted(got) == ids[:4]
    assert r.json()["total"] == 4
    # AND THE ORDER IS THE STANDING, best first — the chain's winner leads.
    assert got[0] == ids[3]
    assert got[-1] == ids[0]


def test_a_ranking_view_sections_by_bucket(client):
    ids = _items(client)
    row = _mk(client, bucket_lo=1, bucket_hi=4)
    _chain(client, row["id"], ids[:4])

    r = client.post("/api/items/groups",
                    json={"ranking": row["id"], "group_by": "bucket"})
    assert r.status_code == 200, r.text
    runs = r.json()["runs"]
    # One section per bucket, best first, and they are RUNS of the page order
    # — which is the rule that makes a grouping legal at all.
    assert [int(x["key"]) for x in runs] == [4, 3, 2, 1]
    assert [x["count"] for x in runs] == [1, 1, 1, 1]
    assert sum(x["count"] for x in runs) == 4


def test_a_whole_view_write_in_a_ranking_stops_at_the_ranking(client):
    """The sharpest edge of a scope that rides `ItemSearchRequest`: ten request
    models inherit it, and a writer that took the body but dropped the field
    would act on the whole library from a button that said four."""
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids[:4])

    r = client.post("/api/items/view/hide",
                    json={"ranking": row["id"], "hidden": False})
    assert r.status_code == 200, r.text

    hidden = {it["id"] for it in
              client.get("/api/items", params={"hidden": True}).json()["items"]}
    assert hidden == set(ids[:4]), "the write widened past the ranking"


def test_a_rating_session_started_in_a_ranking_view_still_offers_new_pairs(client):
    """The session's pool is the VIEW, so a view scoped to ranking X would
    hand it exactly what X has already placed — it could never offer an
    unplaced picture and would run out of pairs with the library full."""
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids[:3])

    r = client.post(f"/api/rankings/{row['id']}/pair",
                    json={"ranking": row["id"], "want_pool": True})
    assert r.status_code == 200, r.text
    assert r.json()["pool"] == len(ids)


def test_the_sidebar_count_is_what_the_ranking_view_shows(client):
    """`items` said how many pictures a judgment had NAMED, which is not the
    same as how many the ranking PLACED — a skip is not evidence and a
    dismissal takes one back out of the fit. Harmless while the number only
    sat in a table; on a sidebar row it is a promise about the grid."""
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids[:4])
    # One more picture, compared and then set aside.
    _judge(client, row["id"], ids[4], ids[0])
    client.post(f"/api/rankings/{row['id']}/dismiss",
                json={"item_id": ids[4]})
    # And one only ever skipped past.
    _judge(client, row["id"], ids[5], ids[6], outcome="skip")

    badge = next(r for r in client.get("/api/rankings").json()
                 if r["id"] == row["id"])["items"]
    shown = client.post("/api/items/query",
                        json={"ranking": row["id"], "page_size": 100}).json()
    assert badge == shown["total"] == 4

    # AND WHAT THE LIBRARY IS NOT SHOWING is out of both. Every other badge in
    # that sidebar counts the ordinary listing; one that counted a trashed
    # picture would promise a grid it cannot deliver. The judgments stay, so
    # restoring puts it back at the standing they always said.
    r = client.post("/api/items/trash", json={"item_ids": [ids[0]]})
    assert r.status_code == 200, r.text
    badge = next(r for r in client.get("/api/rankings").json()
                 if r["id"] == row["id"])["items"]
    shown = client.post("/api/items/query",
                        json={"ranking": row["id"], "page_size": 100}).json()
    assert badge == shown["total"] == 3


# ---- the three verbs at the sizes the sidebar offers them ---------------------


def test_setting_aside_takes_a_selection_and_a_whole_view(client):
    """The sidebar offers "not applicable" on the picked picture, on a
    selection of them, and — with nothing picked — on everything in the view.
    One endpoint for all three: the ids when there are any, the SCOPE when
    the caller asks for the view."""
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids)

    r = client.post(f"/api/rankings/{row['id']}/items/dismiss",
                    json={"items": ids[:3]})
    assert r.status_code == 200, r.text
    assert r.json() == {"count": 3, "total": 3, "judgments": 0}
    placed = _placed(client, row["id"])
    assert not set(ids[:3]) & set(placed)

    # A repeat changes nothing and says so — `count` is what MOVED.
    again = client.post(f"/api/rankings/{row['id']}/items/dismiss",
                        json={"items": ids[:3]}).json()
    assert again["count"] == 0 and again["total"] == 3

    # The way back, over the same selection.
    back = client.post(f"/api/rankings/{row['id']}/items/undismiss",
                       json={"items": ids[:3]}).json()
    assert back["count"] == 3
    assert set(ids[:3]) <= set(_placed(client, row["id"]))

    # AND THE WHOLE VIEW: the ids never travel, the scope does.
    whole = client.post(f"/api/rankings/{row['id']}/items/dismiss",
                        json={"view": True, "ranking": row["id"]}).json()
    assert whole["count"] == len(ids), whole
    assert _placed(client, row["id"]) == {}


def test_a_verb_that_names_neither_ids_nor_the_view_is_refused(client):
    """"No ids" and "the whole library" are the two answers a slip between
    them would confuse, and one of them is a write over a scope nobody
    enumerated."""
    row = _mk(client)
    r = client.post(f"/api/rankings/{row['id']}/items/dismiss", json={})
    assert r.status_code == 400
    assert r.json()["detail"] == "name the pictures, or ask for the view"


def test_removing_a_selection_deletes_each_comparison_once(client):
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids)          # seven comparisons, a chain
    before = next(r for r in client.get("/api/rankings").json()
                  if r["id"] == row["id"])["judgments"]
    # Two ADJACENT pictures: the comparison between them names both, and a
    # per-item loop would count it twice.
    r = client.post(f"/api/rankings/{row['id']}/items/remove",
                    json={"items": [ids[3], ids[4]]})
    assert r.status_code == 200, r.text
    left = next(x for x in client.get("/api/rankings").json()
                if x["id"] == row["id"])["judgments"]
    assert r.json()["judgments"] == before - left
    placed = _placed(client, row["id"])
    assert not {ids[3], ids[4]} & set(placed)


def test_a_ranking_can_hand_over_its_cover_pictures(client):
    """The grid draws a ranking as a card with a 2x2 mosaic, and what belongs
    in it is the TOP of the standings — the card answers "what is this axis
    about". Asked for, never assumed: the sidebar's own poll wants no covers
    and pays for no fit."""
    ids = _items(client)
    row = _mk(client)
    _chain(client, row["id"], ids)          # a strict order, best last
    plain = next(r for r in client.get("/api/rankings").json()
                 if r["id"] == row["id"])
    assert plain["thumbs"] == [], "the sidebar's list pays for no fit"

    got = next(r for r in client.get("/api/rankings?thumbs=4").json()
               if r["id"] == row["id"])
    assert len(got["thumbs"]) == 4
    # FILE ids, and the ranking's own order: the best picture leads.
    best = _placed(client, row["id"])
    top = max(best, key=lambda iid: best[iid])
    first = client.get(f"/api/items/{top}").json()
    assert got["thumbs"][0] == first["active_file_id"]


def test_a_ranking_with_nothing_placed_has_no_cover(client):
    row = _mk(client)
    got = next(r for r in client.get("/api/rankings?thumbs=4").json()
               if r["id"] == row["id"])
    assert got["thumbs"] == []
