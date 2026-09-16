"""The tag-grid overlay's feed — a pre-sorted batch for one tag.

What these pin: the coverage probe (per space, and "any" for fusion), a
fresh session's batch is all undecided, a labeled tag pre-fills the bands
from calibrated cuts (positives-only never pre-fills "doesn't fit"), fusion
scores an item indexed in EITHER space, the pool rules the session feed
already states (decided out, `recent` out, a selection leads), the boundary
mix against the plain top, and the refusals by name.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from media_compost.db import Item, ItemEmbedding
from media_compost.testing import make_image
from media_compost.ui import itemvec
from media_compost.ui.config import UiConfig
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

DINO = "dinov2_small"
CLIP = "clip_vit_b32"


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(16):
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


def _next(client, tag, negative_tag="", **kw):
    r = client.post("/api/taggrid/next",
                    json={"tags": [{"name": tag, "negative": negative_tag}],
                          **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _assign(client, item_id: int, tag: str, negative=False):
    r = client.post(f"/api/tags/assign/item/{item_id}",
                    json={"tag": tag, "negative": negative})
    assert r.status_code == 200, r.text
    return r.json()


def _seed_vector(client, item_id: int, direction, embedder=DINO):
    space, dim = itemvec.EMBEDDERS[embedder]
    v = np.zeros(dim, dtype=np.float32)
    for at, val in direction:
        v[at] = val
    v = v / np.linalg.norm(v)
    with client.lib.db.session() as s:
        it = s.get(Item, item_id)
        s.add(ItemEmbedding(item_id=item_id, model=space,
                            file_id=it.active_file_id, dim=dim,
                            vector=itemvec.pack(v)))
        s.commit()


def _two_clusters(client, ids, embedder=DINO):
    """Half on axis 0, half on axis 1, each with a little spread.

    The spread ALTERNATES down each list, so labeling the first few of a
    cluster (what every test below does) labels rows from across its
    spread rather than its tightest members — the way real answers fall.
    """
    a, b = ids[: len(ids) // 2], ids[len(ids) // 2:]
    spread = [0.05, 0.35, 0.15, 0.25, 0.1, 0.3, 0.2, 0.4]
    for k, iid in enumerate(a):
        _seed_vector(client, iid, [(0, 1.0), (2, spread[k % 8])], embedder)
    for k, iid in enumerate(b):
        _seed_vector(client, iid, [(1, 1.0), (2, spread[k % 8])], embedder)
    return a, b


# ---- the probe ------------------------------------------------------------------


def test_the_probe_counts_per_space_and_serves_nothing(client):
    ids = _items(client)
    _seed_vector(client, ids[0], [(0, 1.0)], DINO)
    _seed_vector(client, ids[1], [(0, 1.0)], CLIP)
    got = _next(client, "cat", count=0, embedders=[DINO, CLIP])
    assert got["queue"] == []
    assert got["total"] == len(ids)
    assert got["embedded"] == 2, "scorable = a vector in ANY space"
    assert got["coverage"] == {DINO: 1, CLIP: 1}
    assert got["labeled"] == [0, 0]
    one = _next(client, "cat", count=0, embedders=[CLIP])
    assert one["embedded"] == 1 and one["coverage"] == {CLIP: 1}


# ---- the batch -------------------------------------------------------------------


def test_a_fresh_session_is_all_undecided(client):
    ids = _items(client)
    _two_clusters(client, ids)
    got = _next(client, "cat", count=6)
    assert len(got["queue"]) == 6
    assert got["ordered"] is False
    assert {q["bucket"] for q in got["queue"]} == {"none"}
    assert all(q["score"] is None for q in got["queue"])


def test_labels_prefill_both_bands_from_calibrated_cuts(client):
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    # Four labels a side — the minimum before a band pre-fills.
    for iid in a[:4]:
        _assign(client, iid, "cat")
    for iid in b[:4]:
        _assign(client, iid, "cat", negative=True)
    got = _next(client, "cat", count=8)
    assert got["ordered"] is True
    assert got["cut_hi"] is not None and got["cut_lo"] is not None
    assert got["labeled"] == [4, 4]
    served = {q["item_id"]: q for q in got["queue"]}
    # Every undecided candidate is served (8 of them left), scored, and in
    # the band its cluster says.
    assert set(served) == set(a[4:]) | set(b[4:])
    for iid in a[4:]:
        assert served[iid]["bucket"] == "positive", served[iid]
    for iid in b[4:]:
        assert served[iid]["bucket"] == "negative", served[iid]
    # …and the batch is score-descending in the reply.
    scores = [q["score"] for q in got["queue"]]
    assert scores == sorted(scores, reverse=True)


def test_positives_only_never_prefills_doesnt_fit(client):
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    for iid in a[:4]:
        _assign(client, iid, "cat")
    got = _next(client, "cat", count=12)
    assert got["ordered"] is True
    assert got["cut_lo"] is None
    buckets = {q["bucket"] for q in got["queue"]}
    assert "negative" not in buckets
    assert "positive" in buckets


def test_below_the_label_minimum_nothing_prefills(client):
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    _assign(client, a[0], "cat")
    _assign(client, b[0], "cat", negative=True)
    got = _next(client, "cat", count=8)
    # Scored (the fit exists) but no band pre-fills below MIN_LABELS.
    assert got["ordered"] is True
    assert all(q["score"] is not None for q in got["queue"])
    assert {q["bucket"] for q in got["queue"]} == {"none"}


def test_fusion_scores_an_item_indexed_in_either_space(client):
    ids = _items(client)
    # The first eight carry DINO vectors, the last eight CLIP — no item has
    # both, so a single-space session scores half and the fused one all.
    a_d, b_d = _two_clusters(client, ids[:8], DINO)
    a_c, b_c = _two_clusters(client, ids[8:], CLIP)
    for iid in a_d[:2] + a_c[:2]:
        _assign(client, iid, "cat")
    for iid in b_d[:2] + b_c[:2]:
        _assign(client, iid, "cat", negative=True)
    single = _next(client, "cat", count=16, embedders=[DINO])
    assert sum(1 for q in single["queue"] if q["score"] is not None) == 4
    fused = _next(client, "cat", count=16, embedders=[DINO, CLIP])
    assert fused["ordered"] is True
    assert all(q["score"] is not None for q in fused["queue"])
    assert fused["labeled"] == [4, 4]
    served = {q["item_id"]: q for q in fused["queue"]}
    # Each space's fit still tells its own clusters apart under fusion.
    assert served[a_d[2]]["score"] > served[b_d[2]]["score"]
    assert served[a_c[2]]["score"] > served[b_c[2]]["score"]


def test_a_counter_tag_is_the_other_side_of_the_fit_and_decides_the_pool(client):
    """`negative_tag`: "doesn't fit" is a SECOND tag assigned positively
    (low_quality beside high_quality). Its positives are the fit's negative
    labels, count as such, and take an item out of the pool as decided."""
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    for iid in a[:4]:
        _assign(client, iid, "hq")
    for iid in b[:4]:
        _assign(client, iid, "lq")
    got = _next(client, "hq", count=8, negative_tag="lq")
    assert got["ordered"] is True
    assert got["labeled"] == [4, 4]
    served = {q["item_id"]: q for q in got["queue"]}
    assert set(served) == set(a[4:]) | set(b[4:]), "the lq items are decided"
    for iid in a[4:]:
        assert served[iid]["bucket"] == "positive", served[iid]
    for iid in b[4:]:
        assert served[iid]["bucket"] == "negative", served[iid]
    # Without the counter tag those four are undecided candidates and there
    # is no negative side to learn from.
    plain = _next(client, "hq", count=12)
    assert plain["labeled"] == [4, 0]
    assert set(b[:4]) <= {q["item_id"] for q in plain["queue"]}
    r = client.post("/api/taggrid/next",
                    json={"tags": [{"name": "hq", "negative": "hq"}]})
    assert r.status_code == 400


def test_a_picture_carrying_both_tags_is_decided_and_teaches_neither_side(client):
    """The "both" answer assigns both tags. Such a picture is mixed
    evidence: it leaves the pool, and the fit reads it as neither a
    positive nor a negative — the labeled counts say so too."""
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    for iid in a[:5]:
        _assign(client, iid, "hq")
    for iid in b[:5]:
        _assign(client, iid, "lq")
    # One of each cluster's labeled pictures is "both".
    _assign(client, a[0], "lq")
    _assign(client, b[0], "hq")
    got = _next(client, "hq", count=12, negative_tag="lq")
    assert got["labeled"] == [4, 4], "the two mixed pictures count on neither side"
    served = {q["item_id"] for q in got["queue"]}
    assert a[0] not in served and b[0] not in served, "decided"
    assert served == set(a[5:]) | set(b[5:])
    assert got["ordered"] is True


def test_including_the_tagged_serves_them_saying_what_they_carry(client):
    """`include_tagged`: decided pictures stay in the pool and come with
    `existing` — the tag, its negative or the counter tag, or both — so a
    session can check tags already given."""
    ids = _items(client)
    _assign(client, ids[0], "cat")
    _assign(client, ids[1], "cat", negative=True)
    _assign(client, ids[2], "not_cat")
    _assign(client, ids[3], "cat")
    _assign(client, ids[3], "not_cat")
    got = _next(client, "cat", count=len(ids), negative_tag="not_cat",
                include_tagged=True)
    served = {q["item_id"]: q for q in got["queue"]}
    assert set(served) == set(ids)
    assert served[ids[0]]["existing"] == "positive"
    assert served[ids[1]]["existing"] == "negative"
    assert served[ids[2]]["existing"] == "negative"
    assert served[ids[3]]["existing"] == "both"
    assert served[ids[4]]["existing"] is None
    # Without the option they are out, and nothing says `existing`.
    plain = _next(client, "cat", count=len(ids), negative_tag="not_cat")
    assert {q["item_id"] for q in plain["queue"]} == set(ids[4:])
    assert all(q["existing"] is None for q in plain["queue"])
    # The unassign reply carries its event fan, for a correction's undo.
    r = client.delete(f"/api/tags/assign/item/{ids[0]}/cat")
    assert r.status_code == 200 and r.json()["event_ids"]


def test_decided_and_recent_leave_the_pool_and_a_selection_leads(client):
    ids = _items(client)
    _assign(client, ids[0], "cat")
    _assign(client, ids[1], "cat", negative=True)
    got = _next(client, "cat", count=len(ids), recent=[ids[2]],
                items=[ids[5], ids[4]])
    served = [q["item_id"] for q in got["queue"]]
    assert ids[0] not in served and ids[1] not in served
    assert ids[2] not in served
    assert set(served[:2]) == {ids[4], ids[5]}
    assert len(served) == len(ids) - 3


def test_boundary_off_is_the_top_of_the_ranking(client):
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    for iid in a[:4]:
        _assign(client, iid, "cat")
    for iid in b[:4]:
        _assign(client, iid, "cat", negative=True)
    top = _next(client, "cat", count=4, boundary=False)
    assert [q["item_id"] for q in top["queue"]] and \
        all(q["item_id"] in a for q in top["queue"])
    mixed = _next(client, "cat", count=4, boundary=True)
    assert any(q["item_id"] in b for q in mixed["queue"]), \
        "the mix draws from both ends"


def test_smart_off_serves_plain_order_with_no_scores(client):
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    for iid in a[:4]:
        _assign(client, iid, "cat")
    got = _next(client, "cat", count=6, smart=False)
    assert got["ordered"] is False
    assert len(got["queue"]) == 6
    assert all(q["score"] is None and q["bucket"] == "none"
               for q in got["queue"])


# ---- refusals -------------------------------------------------------------------


def test_refusals_by_name(client):
    r = client.post("/api/taggrid/next", json={"tags": []})
    assert r.status_code == 400
    r = client.post("/api/taggrid/next", json={"tags": [{"name": "cat"}],
                                               "embedders": ["nope"]})
    assert r.status_code == 400
    r = client.post("/api/taggrid/next", json={"tags": [{"name": "cat"}],
                                               "embedders": []})
    assert r.status_code == 400


def test_a_name_in_a_rankings_shape_is_an_ordinary_session_tag(client):
    """A ranking owns no namespace (rung v31), so `quality:7` is somebody's
    tag like any other and a session may ask about it."""
    r = client.post("/api/rankings", json={"name": "Quality"})
    assert r.status_code == 200, r.text
    r = client.post("/api/taggrid/next",
                    json={"tags": [{"name": "quality:7"}]})
    assert r.status_code == 200, r.text


def test_the_feed_is_a_read_for_a_stale_page(client):
    from media_compost.ui.server import build as build_info
    r = client.post("/api/taggrid/next",
                    json={"tags": [{"name": "cat"}], "count": 0},
                    headers={build_info.HEADER: "index-OLD.js"})
    assert r.status_code == 200, r.text


def test_an_unlabeled_batch_is_a_random_draw_not_id_order(client):
    """The session feed's rule, here: a fresh grid used to open on items 1
    to 16, every time."""
    ids = _items(client)
    _two_clusters(client, ids)
    sortedness = 0
    for _ in range(4):
        got = _next(client, "brand_new", count=len(ids))
        assert got["ordered"] is False
        served = [q["item_id"] for q in got["queue"]]
        assert sorted(served) == ids
        sortedness += served == ids
    assert sortedness < 4


# ---- the question is a SET ---------------------------------------------------


def _set_next(client, tags, **kw):
    r = client.post("/api/taggrid/next", json={"tags": tags, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_set_of_tags_asks_about_the_pictures_that_have_them_ALL(client):
    """The question is a conjunction: `white_shirt` and `blue_pants` asks
    about pictures that are both, so only a picture carrying every tag is a
    positive example — and a picture carrying one of them is not answered at
    all, which is exactly the picture the session exists to ask about."""
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    both_ids, half_ids = a[:4], a[4:7]
    for iid in both_ids:
        _assign(client, iid, "shirt")
        _assign(client, iid, "pants")
    for iid in half_ids:
        _assign(client, iid, "shirt")          # one of the two only
    for iid in b[:4]:
        _assign(client, iid, "shirt", negative=True)

    tags = [{"name": "shirt"}, {"name": "pants"}]
    got = _set_next(client, tags, count=0)
    assert got["labeled"] == [len(both_ids), 4]
    # The half-answered ones are still in the pool; the fully answered ones
    # (either way) are not.
    served = {q["item_id"] for q in
              _set_next(client, tags, count=len(ids))["queue"]}
    assert set(half_ids) <= served
    assert not served & set(both_ids)
    assert not served & set(b[:4])


def test_evidence_against_ANY_tag_of_the_set_is_a_negative_example(client):
    """A picture failing one conjunct is not an example of the conjunction,
    whatever the others say — so ANY tag answered no decides it. With a
    COUNTER tag paired to one of them (`small` beside `big`), that tag's
    positives say the same thing, which is the only thing that says so."""
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    for iid in a[:4]:
        _assign(client, iid, "big")
        _assign(client, iid, "tall")
    # One picture is only "not tall" — evidence against the pair.
    _assign(client, b[0], "tall", negative=True)
    # …and one carries the counter of the other half.
    _assign(client, b[1], "small")

    tags = [{"name": "big", "negative": "small"}, {"name": "tall"}]
    got = _set_next(client, tags, count=0)
    assert got["labeled"] == [4, 2], got["labeled"]
    served = {q["item_id"] for q in
              _set_next(client, tags, count=len(ids))["queue"]}
    assert not served & {b[0], b[1]}


def test_the_one_tag_spelling_is_a_set_of_one(client):
    """A set of ONE tag, which is what most sessions are, and
    answers exactly as it did."""
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    for iid in a[:4]:
        _assign(client, iid, "hq")
    for iid in b[:3]:
        _assign(client, iid, "lq")
    assert _next(client, "hq", count=0, negative_tag="lq")["labeled"] \
        == _set_next(client, [{"name": "hq", "negative": "lq"}],
                     count=0)["labeled"]


def test_the_sessions_own_negatives_teach_the_fit_and_leave_its_pool(client):
    """A conjunction's "no" names no tag to write it on, so past one tag the
    grid writes nothing for it — and the answer rides back as
    `session_negatives` instead: a label the fit learns from, a picture the
    session does not ask about twice, and a figure the "learn from" line
    counts. The library is never told (that is the point), so nothing here
    survives the session.
    """
    ids = _items(client)
    a, b = _two_clusters(client, ids)
    for iid in a[:4]:
        _assign(client, iid, "shirt")
        _assign(client, iid, "pants")

    tags = [{"name": "shirt"}, {"name": "pants"}]
    # With no negatives at all the classifier has one side and pre-fills
    # nothing on the other.
    plain = _set_next(client, tags, count=len(ids))
    assert plain["labeled"] == [4, 0]
    assert plain["cut_lo"] is None

    # The session answers four of the OTHER cluster "doesn't fit".
    said_no = b[:4]
    got = _set_next(client, tags, count=len(ids), session_negatives=said_no)
    assert got["labeled"] == [4, 4], "the session's own answers are labels"
    assert got["cut_lo"] is not None, "…and the band they teach pre-fills"
    served = {q["item_id"]: q for q in got["queue"]}
    assert not set(said_no) & set(served), "answered: out of this pool"
    for iid in b[4:]:
        assert served[iid]["bucket"] == "negative", served[iid]

    # Nothing was written: another session, told nothing, is back where the
    # first one started.
    again = _set_next(client, tags, count=len(ids))
    assert again["labeled"] == [4, 0]
    assert set(said_no) <= {q["item_id"] for q in again["queue"]}


def test_a_session_negative_outranks_what_the_library_says(client):
    """The person has just looked at the picture and said it is not an
    example of the set; an assignment made a year ago does not overrule
    that. So it teaches the negative side and counts on neither positive
    figure."""
    ids = _items(client)
    a, _b = _two_clusters(client, ids)
    for iid in a[:5]:
        _assign(client, iid, "shirt")
        _assign(client, iid, "pants")
    tags = [{"name": "shirt"}, {"name": "pants"}]
    got = _set_next(client, tags, count=0, session_negatives=[a[0]])
    assert got["labeled"] == [4, 1]
