"""The tag-batch session's endpoints — the pool, the labels, the ordering.

What these pin: the pool (scope ∩ selection, the per-mode exclusions, the
session's `recent`), the coverage probe, the answer's event fan (assigning
returns the ids, and reverting them puts the item back in the pool), the
pending-suggestion resolution (a YES confirms through the approve machinery,
a NO deletes the placements — never a bare flag flip), the classifier
ordering over seeded vectors (the labeled cluster leads, vectorless items
trail but appear), the /index enqueue rules, and the score-tag
refusal at session start.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost.db import (
    Item, ItemEmbedding, ItemTag, ItemTagGroup, ItemTagPlacement, Job, Tag,
)
from media_compost.testing import make_image
from media_compost.ui import itemvec
from media_compost.ui.config import UiConfig
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(10):
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


def _next(client, tags, **kw):
    r = client.post("/api/tagsort/next", json={"tags": tags, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _assign(client, item_id: int, tag: str, negative=False):
    r = client.post(f"/api/tags/assign/item/{item_id}",
                    json={"tag": tag, "negative": negative})
    assert r.status_code == 200, r.text
    return r.json()


def _seed_vector(client, item_id: int, direction, space=itemvec.SPACE):
    """A synthetic unit vector for an item, in the active file's name — the
    row only counts while it matches the active file, which is exactly what
    a session reads."""
    v = np.zeros(itemvec.DIM, dtype=np.float32)
    for at, val in direction:
        v[at] = val
    v = v / np.linalg.norm(v)
    with client.lib.db.session() as s:
        it = s.get(Item, item_id)
        s.add(ItemEmbedding(item_id=item_id, model=space,
                            file_id=it.active_file_id, dim=itemvec.DIM,
                            vector=itemvec.pack(v)))
        s.commit()


# ---- the pool -----------------------------------------------------------------


def test_a_selection_leads_the_queue_and_never_fences_the_pool(client):
    """The rankings' rule: `items` is the session's PRIORITY — those pictures
    are asked about first — while the pool stays the whole scope. (It used
    to intersect, so a small selection made a session that ended at once.)"""
    ids = _items(client)
    got = _next(client, ["cat"], items=ids[3:6], count=len(ids))
    assert got["pool"] == len(ids)
    served = [q["item_id"] for q in got["queue"]]
    assert served[:3] == ids[3:6]
    assert len(served) == len(ids)
    # A DECIDED selected item is still not re-asked — priority does not
    # override the exclusions.
    _assign(client, ids[3], "cat")
    got = _next(client, ["cat"], items=ids[3:6], count=len(ids))
    served = [q["item_id"] for q in got["queue"]]
    assert served[:2] == ids[4:6] and ids[3] not in served


def test_single_mode_excludes_either_sign_but_keeps_pending(client):
    ids = _items(client)
    _assign(client, ids[0], "cat")
    _assign(client, ids[1], "cat", negative=True)
    # A machine's unconfirmed suggestion is the QUESTION, not an answer.
    with client.lib.db.session() as s:
        tag = s.execute(select(Tag).where(Tag.name == "cat")).scalars().one()
        s.add(ItemTag(item_id=ids[2], tag_id=tag.id, pending=True))
        s.commit()
    got = _next(client, ["cat"], count=0)
    assert got["pool"] == len(ids) - 2
    assert got["labeled"]["cat"] == [1, 1]


def test_multi_mode_excludes_positives_only(client):
    ids = _items(client)
    _assign(client, ids[0], "photo")           # filed — out
    _assign(client, ids[1], "illu", negative=True)  # only a negative — stays
    got = _next(client, ["photo", "illu"], count=0)
    assert got["pool"] == len(ids) - 1


def test_a_counter_tag_decides_an_item_in_either_mode(client):
    """A "doesn't fit" written as a tag of its own is as much an answer as
    the negative it stands in for: an item carrying `low` positively is
    out of a `hi` session's pool, single or multi."""
    ids = _items(client)
    _assign(client, ids[0], "low")
    _assign(client, ids[1], "low", negative=True)   # a negative counter says nothing
    got = _next(client, ["hi"], counter_tags={"hi": "low"}, count=0)
    assert got["pool"] == len(ids) - 1
    got = _next(client, ["hi", "other"], counter_tags={"hi": "low"}, count=0)
    assert got["pool"] == len(ids) - 1
    # Without the counter declared it is an ordinary tag nobody asked about.
    assert _next(client, ["hi"], count=0)["pool"] == len(ids)


def test_the_body_refuses_the_scope_field_for_the_set(client):
    """`tag_groups`, never `groups` — that is the scope's field on the
    search body this one inherits, and a strict body says so."""
    r = client.post("/api/tagsort/next", json={
        "tags": ["a", "b"], "tag_groups": [{"tags": ["a", "b"], "exclusive": True,
                                          "nope": 1}]})
    assert r.status_code == 422


def test_recent_is_the_session_skip_memory(client):
    ids = _items(client)
    got = _next(client, ["cat"], recent=ids[:3], count=0)
    assert got["pool"] == len(ids) - 3
    got = _next(client, ["cat"], recent=ids[:3], count=20)
    served = [q["item_id"] for q in got["queue"]]
    assert not set(served) & set(ids[:3])


def test_a_name_in_a_rankings_shape_is_an_ordinary_session_tag(client):
    """A ranking owns no namespace (rung v31), so `quality:7` is somebody's
    tag like any other and a session may ask about it — which it always
    could, and which is now true without a rule saying so."""
    r = client.post("/api/rankings", json={"name": "Q"})
    assert r.status_code == 200, r.text
    r = client.post("/api/tagsort/next", json={"tags": ["quality:7"]})
    assert r.status_code == 200, r.text


def test_a_session_needs_a_tag(client):
    assert client.post("/api/tagsort/next", json={"tags": []}).status_code == 400


# ---- answers, the event fan, undo ---------------------------------------------


def test_an_answer_returns_its_event_fan_and_reverts_whole(client):
    ids = _items(client)
    before = _next(client, ["cat"], count=0)["pool"]
    got = _assign(client, ids[0], "cat")
    assert got["event_id"] is not None
    assert got["event_id"] in got["event_ids"]
    assert _next(client, ["cat"], count=0)["pool"] == before - 1
    r = client.post("/api/history/revert",
                    json={"event_ids": got["event_ids"]})
    assert r.status_code == 200, r.text
    assert _next(client, ["cat"], count=0)["pool"] == before


def test_a_yes_confirms_a_pending_suggestion_through_the_approve_path(client):
    ids = _items(client)
    iid = ids[0]
    with client.lib.db.session() as s:
        tag = Tag(name="cat")
        s.add(tag)
        s.flush()
        it = ItemTag(item_id=iid, tag_id=tag.id, pending=True)
        s.add(it)
        s.flush()
        grp = ItemTagGroup(item_id=iid, name="Pending: Model", system=True,
                           position=0)
        s.add(grp)
        s.flush()
        s.add(ItemTagPlacement(item_tag_id=it.id, group_id=grp.id))
        s.commit()
    got = _assign(client, iid, "cat")
    assert len(got["event_ids"]) >= 1
    with client.lib.db.session() as s:
        row = s.execute(select(ItemTag).join(Tag).where(
            ItemTag.item_id == iid, Tag.name == "cat")).scalars().one()
        assert row.pending is False and row.negative is False
        # The placement LEFT the system group (approve, not a flag flip) —
        # and the emptied pending group is gone.
        left = s.execute(
            select(ItemTagPlacement)
            .join(ItemTagGroup, ItemTagGroup.id == ItemTagPlacement.group_id)
            .where(ItemTagPlacement.item_tag_id == row.id,
                   ItemTagGroup.system.is_(True))).scalars().all()
        assert left == []


def test_a_no_dismisses_a_pending_suggestion(client):
    ids = _items(client)
    iid = ids[0]
    with client.lib.db.session() as s:
        tag = Tag(name="cat")
        s.add(tag)
        s.flush()
        it = ItemTag(item_id=iid, tag_id=tag.id, pending=True)
        s.add(it)
        s.flush()
        grp = ItemTagGroup(item_id=iid, name="Pending: Model", system=True,
                           position=0)
        s.add(grp)
        s.flush()
        s.add(ItemTagPlacement(item_tag_id=it.id, group_id=grp.id))
        s.commit()
    _assign(client, iid, "cat", negative=True)
    with client.lib.db.session() as s:
        row = s.execute(select(ItemTag).join(Tag).where(
            ItemTag.item_id == iid, Tag.name == "cat")).scalars().one()
        assert row.pending is False and row.negative is True
        assert s.execute(select(ItemTagPlacement).where(
            ItemTagPlacement.item_tag_id == row.id)).scalars().all() == []


# ---- ordering -----------------------------------------------------------------


def test_the_labeled_cluster_leads_the_queue(client):
    ids = _items(client)
    # Two separable clusters: A on axis 0, B on axis 1, with a little of a
    # third axis so nothing is exactly identical.
    a_ids, b_ids = ids[:5], ids[5:]
    for k, iid in enumerate(a_ids):
        _seed_vector(client, iid, [(0, 1.0), (2, 0.05 * (k + 1))])
    for k, iid in enumerate(b_ids):
        _seed_vector(client, iid, [(1, 1.0), (2, 0.05 * (k + 1))])
    # Answer yes on one A and no on one B.
    _assign(client, a_ids[0], "cat")
    _assign(client, b_ids[0], "cat", negative=True)
    got = _next(client, ["cat"], count=4)
    assert got["ordered"] is True
    served = [q["item_id"] for q in got["queue"]]
    # A plain top-k now (no exploration slot): every A left leads.
    assert served[:4] == [i for i in served if i in a_ids][:4]
    assert sum(1 for i in served if i in a_ids) == 4
    assert len(served) == 4
    # The chooser's "Smart ordering" switch OFF: same request, no fit — the
    # queue is plain pool order and says so (the coverage counts still travel).
    plain = _next(client, ["cat"], count=4, smart=False)
    assert plain["ordered"] is False
    assert plain["embedded"] == got["embedded"]


def test_vectorless_items_trail_but_appear(client):
    ids = _items(client)
    for iid in ids[:3]:
        _seed_vector(client, iid, [(0, 1.0), (2, 0.01 * iid)])
    _assign(client, ids[0], "cat")
    got = _next(client, ["cat"], count=len(ids))
    served = [q["item_id"] for q in got["queue"]]
    # Everything not yet decided is served…
    assert len(served) == len(ids) - 1
    # …scored candidates first, the unindexed tail after.
    scored = [i for i in served if i in ids[1:3]]
    assert served[:len(scored)] == scored


def test_the_embedder_choice_is_its_own_space(client):
    """DINOv2 and CLIP index independent spaces: coverage, the fit and the
    scores all read the CHOSEN one, and an unknown embedder is refused by
    name rather than silently scored in the default space."""
    ids = _items(client)
    _seed_vector(client, ids[0], [(0, 1.0)])  # the dinov2 space
    assert _next(client, ["cat"], count=0)["embedded"] == 1
    assert _next(client, ["cat"], count=0,
                 embedder="clip_vit_b32")["embedded"] == 0
    r = client.post("/api/tagsort/next",
                    json={"tags": ["cat"], "embedder": "nope"})
    assert r.status_code == 400


def test_a_stale_vector_reads_as_unindexed(client):
    ids = _items(client)
    _seed_vector(client, ids[0], [(0, 1.0)])
    with client.lib.db.session() as s:
        row = s.execute(select(ItemEmbedding)).scalars().one()
        row.file_id = None  # as if the active file moved on
        s.commit()
    got = _next(client, ["cat"], count=0)
    assert got["embedded"] == 0


def test_the_coverage_probe_counts_without_serving(client):
    ids = _items(client)
    _seed_vector(client, ids[0], [(0, 1.0)])
    got = _next(client, ["cat"], count=0)
    assert got["queue"] == []
    assert got["embedded"] == 1
    assert got["total"] == len(ids)


# ---- /index -------------------------------------------------------------------


def test_index_refuses_without_the_embedder(client, monkeypatch):
    # Availability is a fact about the machine (this dev venv holds torch,
    # CI does not), so the refusal is driven with it forced off — the same
    # way the gated-download refusal is tested.
    from media_compost.ui.plugins import registry

    monkeypatch.setattr(registry, "available", lambda mid: False)
    r = client.post("/api/tagsort/index", json={})
    assert r.status_code == 400
    assert "Settings" in r.json()["detail"]


def test_index_enqueues_only_the_unindexed(client, monkeypatch):
    from media_compost.ui.plugins import registry

    monkeypatch.setattr(registry, "available", lambda mid: True)
    ids = _items(client)
    _seed_vector(client, ids[0], [(0, 1.0)])
    # A selection does not narrow indexing either — the coverage the chooser
    # shows is the SESSION pool's, and the two must count the same scope.
    r = client.post("/api/tagsort/index", json={"items": ids[:4]})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["queued"] == len(ids) - 1 and got["skipped"] == 1


def test_a_one_item_index_run_is_still_a_batch_job(client, monkeypatch):
    """The LAST straggler indexes like every other one.

    `embed` has no branch in `jobs._apply_result` — its only path is
    `_run_item_batch` — and `enqueue` used to make a batch job only when the
    scope held more than one item. So a run over exactly one unindexed
    picture wrote a per-item `Job` with an empty `item_ids`, missed the batch
    dispatch, and died with `RuntimeError: unknown job kind 'embed'`. That is
    precisely the end of the job "Index remaining" exists to do.

    The defect is the SHAPE of the job, which is checkable without a model:
    a batch job carries its ids in `item_ids`.
    """
    from media_compost.ui.plugins import registry

    monkeypatch.setattr(registry, "available", lambda mid: True)
    ids = _items(client)
    for iid in ids[:-1]:
        _seed_vector(client, iid, [(0, 1.0), (1, 0.01 * iid)])
    r = client.post("/api/tagsort/index", json={})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["queued"] == 1 and got["skipped"] == len(ids) - 1
    with client.lib.db.session() as s:
        job = s.get(Job, got["job_ids"][0])
        assert job.kind == "embed"
        # Not `[]` and not None: the empty list is exactly what sent the old
        # job down the single-item path.
        assert json.loads(job.item_ids) == [ids[-1]]


def test_a_plugin_vector_survives_the_worker_wire(client):
    """The embed result's WHOLE wire, minus only the torch forward: what the
    plugin returns goes through the worker's `_marshal`, the host's one
    unwrap, and into `_apply_embedding`. The plugin once wrapped its dict in
    {"value": …} ITSELF — `_marshal` wraps any bare dict the same way, the
    host unwraps exactly one layer, and every item of a real 378-item run
    was skipped with "indexed 0 of 378" and nothing anywhere saying why."""
    from media_compost.db import Item, ItemEmbedding
    from media_compost.ui.itemvec import DIM, SPACE
    from media_compost.ui.plugins.worker import _marshal
    from sqlalchemy import select

    plugin_result = {"vector": [1.0] + [0.0] * (DIM - 1),
                     "dim": DIM, "space": SPACE}
    on_the_wire = _marshal(plugin_result, None)
    unwrapped = on_the_wire.get("value")  # host.py's one unwrap
    assert unwrapped == plugin_result

    iid = _items(client)[0]
    with client.lib.db.session() as s:
        item = s.get(Item, iid)
        assert client.lib.jobs._apply_embedding(s, item, unwrapped) is True
        s.commit()
        row = s.execute(select(ItemEmbedding).where(
            ItemEmbedding.item_id == iid)).scalars().one()
        assert row.model == SPACE and row.dim == DIM


def test_an_unlabeled_queue_is_a_random_draw_not_id_order(client):
    """Before the first "yes" nothing can be fit, and the draw used to come
    back ascending by id — a new tag's cold start was the library's oldest
    pictures, every session. Two fetches that both come back sorted is what
    the bug looked like; a shuffle makes that vanishingly unlikely over
    ten items (1 in 10! per fetch)."""
    ids = _items(client)
    for iid in ids:
        _seed_vector(client, iid, [(0, 1.0), (2, 0.01 * iid)])
    sortedness = 0
    for _ in range(4):
        got = _next(client, ["brand_new"], count=len(ids))
        assert got["ordered"] is False
        served = [q["item_id"] for q in got["queue"]]
        assert sorted(served) == ids
        sortedness += served == ids
    assert sortedness < 4


def test_carried_ids_are_scored_ahead_of_the_draw(client, monkeypatch):
    """The overlay hands back the queue it still holds; those ids are
    admitted like any candidate and scored — so the ordering accumulates
    across fetches even when the fresh sample misses them."""
    from media_compost.ui.server.routers import tagsort as feed

    ids = _items(client)
    a_ids, b_ids = ids[:5], ids[5:]
    for k, iid in enumerate(a_ids):
        _seed_vector(client, iid, [(0, 1.0), (2, 0.05 * (k + 1))])
    for k, iid in enumerate(b_ids):
        _seed_vector(client, iid, [(1, 1.0), (2, 0.05 * (k + 1))])
    _assign(client, a_ids[0], "cat")
    _assign(client, b_ids[0], "cat", negative=True)
    # A draw that never samples the A's: without the carry no A could be
    # served first; with it the carried A's lead.
    real = feed._pick_split
    monkeypatch.setattr(feed, "_pick_split",
                        lambda s, sel, space, k: ([i for i in real(s, sel, space, k)[0]
                                                   if i not in a_ids], []))
    got = _next(client, ["cat"], count=3, carry=a_ids[1:3])
    assert got["ordered"] is True
    assert set(q["item_id"] for q in got["queue"][:2]) == set(a_ids[1:3])
    # A carried id that is decided or shown is NOT re-served.
    got = _next(client, ["cat"], count=3, carry=[a_ids[0], a_ids[1]], recent=[a_ids[1]])
    served = [q["item_id"] for q in got["queue"]]
    assert a_ids[0] not in served and a_ids[1] not in served


def test_a_multi_tag_session_serves_the_tags_in_turn(client):
    """Tags [a, b] over three clusters: every a-looking picture first, then
    every b-looking one, then the rest — not the max over both."""
    ids = _items(client)
    a_ids, b_ids, c_ids = ids[:3], ids[3:6], ids[6:]
    for k, iid in enumerate(a_ids):
        _seed_vector(client, iid, [(0, 1.0), (3, 0.05 * (k + 1))])
    for k, iid in enumerate(b_ids):
        _seed_vector(client, iid, [(1, 1.0), (3, 0.05 * (k + 1))])
    for k, iid in enumerate(c_ids):
        _seed_vector(client, iid, [(2, 1.0), (3, 0.05 * (k + 1))])
    _assign(client, a_ids[0], "a"); _assign(client, b_ids[0], "b")
    _assign(client, c_ids[0], "a", negative=True)
    _assign(client, c_ids[0], "b", negative=True)
    group = [{"tags": ["a", "b"], "exclusive": True}]
    got = _next(client, ["a", "b"], count=len(ids), tag_groups=group)
    assert got["ordered"] is True
    served = [q["item_id"] for q in got["queue"]]
    kinds = ["a" if i in a_ids else "b" if i in b_ids else "c" for i in served]
    assert kinds == ["a", "a", "b", "b"] + ["c"] * (len(kinds) - 4), kinds
    # The other order of the same two tags is the other order of stretches.
    got = _next(client, ["b", "a"], count=len(ids), tag_groups=group)
    served = [q["item_id"] for q in got["queue"]]
    kinds = ["a" if i in a_ids else "b" if i in b_ids else "c" for i in served]
    assert kinds[:4] == ["b", "b", "a", "a"], kinds


def test_a_counter_tags_positives_are_negative_evidence(client):
    """`hi` with counter `low`: the pictures tagged `low` teach `hi`'s
    negative side, so a `hi` session leads with what looks like its one
    positive and trails what looks like `low` — with NO `hi` negative
    anywhere in the library."""
    ids = _items(client)
    hi_ids, low_ids = ids[:4], ids[4:]
    for k, iid in enumerate(hi_ids):
        _seed_vector(client, iid, [(0, 1.0), (3, 0.05 * (k + 1))])
    for k, iid in enumerate(low_ids):
        _seed_vector(client, iid, [(1, 1.0), (3, 0.05 * (k + 1))])
    _assign(client, hi_ids[0], "hi")
    _assign(client, low_ids[0], "low")
    got = _next(client, ["hi"], counter_tags={"hi": "low"}, count=len(ids))
    assert got["ordered"] is True
    served = [q["item_id"] for q in got["queue"]]
    assert set(served[:3]) == set(hi_ids[1:]), served
    # Without the counter there is only one positive and no negative: the
    # centroid fallback still orders, but by likeness to the one picture —
    # the point is the counter side is READ, which the exclusion above and
    # this ordering both show.


def test_fusion_scores_an_item_indexed_in_either_space(client):
    """The tag grid's rule, in the session feed: with two embedders named,
    each space is fit and scored on its own and an item's score is the mean
    of the spaces it is indexed in — so a picture indexed in EITHER space is
    scored, where a single-space session scores half of them. The chooser's
    probe reports coverage per embedder beside the any-space figure."""
    ids = _items(client)
    clip_space = itemvec.EMBEDDERS["clip_vit_b32"][0]
    dino_ids, clip_ids = ids[:5], ids[5:]
    for k, iid in enumerate(dino_ids):
        _seed_vector(client, iid, [(0, 1.0 if k < 3 else 0.0),
                                   (1, 0.0 if k < 3 else 1.0), (2, 0.05 * (k + 1))])
    clip_dim = itemvec.EMBEDDERS["clip_vit_b32"][1]
    for k, iid in enumerate(clip_ids):
        v = np.zeros(clip_dim, dtype=np.float32)
        v[0 if k < 3 else 1] = 1.0
        v[2] = 0.05 * (k + 1)
        with client.lib.db.session() as s:
            it = s.get(Item, iid)
            s.add(ItemEmbedding(item_id=iid, model=clip_space,
                                file_id=it.active_file_id, dim=clip_dim,
                                vector=itemvec.pack(v / np.linalg.norm(v))))
            s.commit()
    # A yes and a no in EACH space's cluster pair.
    _assign(client, dino_ids[0], "cat"); _assign(client, dino_ids[3], "cat", negative=True)
    _assign(client, clip_ids[0], "cat"); _assign(client, clip_ids[3], "cat", negative=True)
    probe = _next(client, ["cat"], count=0, embedders=["dinov2_small", "clip_vit_b32"])
    assert probe["embedded"] == 6
    assert probe["coverage"] == {"dinov2_small": 3, "clip_vit_b32": 3}
    single = _next(client, ["cat"], count=6, embedders=["dinov2_small"])
    fused = _next(client, ["cat"], count=6, embedders=["dinov2_small", "clip_vit_b32"])
    assert single["ordered"] and fused["ordered"]
    # Under fusion each space's A's lead the queue: both spaces' remaining
    # A (dino_ids[1], dino_ids[2], clip_ids[1], clip_ids[2]) come before
    # any B.
    served = [q["item_id"] for q in fused["queue"]]
    a_left = {dino_ids[1], dino_ids[2], clip_ids[1], clip_ids[2]}
    assert set(served[:4]) == a_left, served
    # Single-space: only the DINO-indexed items are scored, the CLIP-only
    # ones trail as the unscored tail whatever their cluster.
    served1 = [q["item_id"] for q in single["queue"]]
    assert set(served1[:3]) == {dino_ids[1], dino_ids[2], dino_ids[4]}, served1
