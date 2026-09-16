"""Estimating a ranking's scale over unrated pictures, and tagging on it.

What these pin: the estimate learns the ranking's OWN numbers (a picture
next to a rated 9 comes back near 9), it refuses rather than guesses on too
little evidence, the preview writes nothing, the rules write ORDINARY tags
through the same door everything else does — a ranking has no rows of its
own — and the rated pictures are left out unless asked for.

And the WRITE IS A BACKGROUND JOB, a second path: the scope is the library,
so it can be minutes of walking and hundreds of thousands of tag rows. These
drive `run_one` themselves rather than waiting on the worker thread.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost.db import Item, ItemEmbedding, ItemTag, Tag
from media_compost.testing import make_image
from media_compost.ui import itemvec
from media_compost.ui.config import UiConfig
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

#: Enough pictures that a chain of judgments clears `enough_comparisons`
#: AND the estimate's own `MIN_RATED`, with a few left over to estimate.
RATED = 16
SPARE = 6


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(RATED + SPARE):
        make_image(src / f"p{i:02d}.png", seed=i, size=(200, 150))
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([src], ImportOptions())
    # No worker thread: these drive `run_one` themselves, so what the job
    # did is settled before the assertion rather than a moment later.
    lib.jobs._ensure_worker = lambda: None
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
    for k in range(len(ids) - 1):
        r = client.post(f"/api/rankings/{rid}/judge",
                        json={"a_item_id": ids[k + 1], "b_item_id": ids[k],
                              "outcome": "a"})
        assert r.status_code == 200, r.text


def _seed(client, item_id: int, along: float) -> None:
    """A vector on one axis, so the space says exactly what the standings do
    — the estimate then has a right answer to find."""
    v = np.zeros(itemvec.DIM, dtype=np.float32)
    v[0] = float(along)
    v[1] = 1.0
    v = v / np.linalg.norm(v)
    with client.lib.db.session() as s:
        it = s.get(Item, item_id)
        s.add(ItemEmbedding(item_id=item_id, model=itemvec.SPACE,
                            file_id=it.active_file_id, dim=itemvec.DIM,
                            vector=itemvec.pack(v)))
        s.commit()


def _estimate(client, rid: int, **body):
    """The PREVIEW: what the rules would claim. Writes nothing."""
    r = client.post(f"/api/rankings/{rid}/estimate",
                    json={"embedders": ["dinov2_small"], **body})
    assert r.status_code == 200, r.text
    return r.json()


def _apply(client, rid: int, **body) -> str:
    """The WRITE: queue it, then run the job here. Returns its message."""
    r = client.post(f"/api/rankings/{rid}/estimate/apply",
                    json={"embedders": ["dinov2_small"], **body})
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    out = client.lib.jobs.run_one(jid)
    return out


def _setup(client):
    """A ranking rated in a strict order, each picture's vector placed along
    the very axis the judgments describe — and the spare pictures placed ON
    TOP of rated ones, half beside the best and half beside the worst.

    Beside rather than beyond, deliberately: the rows are unit vectors, so
    "further along the axis" saturates and says nothing a fit can use. What
    the estimate promises is that a picture that LOOKS like a rated 9 comes
    back near 9, and that is what this asks.
    """
    ids = _items(client)
    rated, spare = ids[:RATED], ids[RATED:]
    row = _mk(client)
    _chain(client, row["id"], rated)
    for n, iid in enumerate(rated):
        _seed(client, iid, n - (RATED - 1) / 2)
    half = len(spare) // 2
    for iid in spare[:half]:
        _seed(client, iid, (RATED - 1) / 2)       # beside the best
    for iid in spare[half:]:
        _seed(client, iid, -(RATED - 1) / 2)      # beside the worst
    return row, rated, spare, spare[:half], spare[half:]


def test_the_estimate_learns_the_rankings_own_numbers(client):
    row, rated, spare, best, worst = _setup(client)
    # THREE BANDS: everything under 3, 3 up to 7, and 7 upward. They are
    # the rules sorted by where they start, each running to the next one's
    # start, so a picture is in exactly one.
    got = _estimate(client, row["id"], items=spare,
                    rules=[{"min": 7, "tags": ["great"]},
                           {"min": 0, "tags": ["poor"]},
                           {"min": 3, "tags": ["middling"]}])
    assert got["rated"] == RATED
    assert got["estimated"] == len(spare)
    assert got["unindexed"] == 0
    # The top half looks like the ranking's best pictures and the bottom
    # half like its worst, and the estimate says so on the ranking's own
    # 0…9 — which is the whole promise.
    assert got["rules"][0]["matched"] == len(best), got["rules"]
    assert got["rules"][1]["matched"] == len(worst), got["rules"]
    # And every picture landed in exactly one band.
    assert sum(r["matched"] for r in got["rules"]) == len(spare)
    # A SAMPLE PER RULE, of what THAT rule takes — highest first inside it.
    top = got["rules"][0]
    assert {x["item_id"] for x in top["sample"]} == set(best)
    assert top["sample_scores"] == sorted(top["sample_scores"], reverse=True)
    assert {x["item_id"] for x in got["rules"][1]["sample"]} == set(worst)
    # A PREVIEW WRITES NOTHING — the path that does is a second one.
    with client.lib.db.session() as s:
        assert s.execute(select(Tag).where(Tag.name == "great")) \
            .scalars().first() is None


def test_the_rules_write_ordinary_tags(client):
    """A ranking writes nothing of its own (rung v31), so there is no
    derived row an estimate could be confused with — and there never was
    one it could have been written as. These are ordinary assignments."""
    row, rated, spare, best, worst = _setup(client)
    # `stamp` counts the ITEMS it stamped, as the quick-assign write does,
    # and the job's message is what the row shows.
    msg = _apply(client, row["id"], items=spare,
                 rules=[{"min": 7, "tags": ["high_quality", "-blurry"]}])
    assert msg == f"{len(best)} tags on {len(best)} pictures", msg
    with client.lib.db.session() as s:
        names = {t.name: t.id for t in s.execute(select(Tag)).scalars()}
        rows = s.execute(select(ItemTag).where(
            ItemTag.tag_id.in_([names["high_quality"], names["blurry"]]))
        ).scalars().all()
        assert {r.item_id for r in rows} == set(best)
        signs = {(r.tag_id == names["blurry"], bool(r.negative)) for r in rows}
        assert signs == {(False, False), (True, True)}, "the leading - is the sign"
    # And every one of them is an ordinary logged assignment.
    log = client.get("/api/history?limit=100").json()
    events = log["events"] if isinstance(log, dict) else log
    assert sum(1 for e in events if e["action"] == "add_tag") >= 2 * len(best)


def test_too_little_evidence_is_refused_rather_than_guessed(client):
    """A line through four points in 384 dimensions is a line through four
    points: below `MIN_RATED` the answer is a refusal with the number in it,
    not a confident estimate."""
    ids = _items(client)
    row = _mk(client, name="Thin")
    _chain(client, row["id"], ids[:4])
    for n, iid in enumerate(ids[:4]):
        _seed(client, iid, n)
    r = client.post(f"/api/rankings/{row['id']}/estimate",
                    json={"rules": [{"min": 8, "tags": ["x"]}]})
    assert r.status_code == 400
    assert r.json()["detail_key"] or r.json()["detail"]


def test_the_rules_are_bands_whatever_order_they_arrive_in(client):
    """A rule says where its band STARTS; the bands are the rules sorted by
    that, so an out-of-order list cannot make one that holds nothing — the
    dialog re-sorts as somebody types, and the answers still come back
    beside the rules that asked."""
    row, _rated, spare, best, worst = _setup(client)
    got = _estimate(client, row["id"], items=spare,
                    rules=[{"min": 7, "tags": ["great"]},
                           {"min": 0, "tags": ["poor"]}])
    assert got["rules"][0]["matched"] == len(best)
    assert got["rules"][1]["matched"] == len(worst)
    assert sum(r["matched"] for r in got["rules"]) == len(spare)
    # A row with no number at all takes nothing — a half-typed row in the
    # dialog is not a claim.
    got = _estimate(client, row["id"], items=spare,
                    rules=[{"tags": ["x"]}, {"min": 0, "tags": ["any"]}])
    assert got["rules"][0]["matched"] == 0
    assert got["rules"][1]["matched"] == len(spare)


def test_a_picture_with_no_vector_is_counted_not_guessed(client):
    """No vector in any chosen space is a thing to go and index, not a
    failure of the estimate — it is reported and left alone."""
    row, rated, spare, _best, _worst = _setup(client)
    with client.lib.db.session() as s:
        s.execute(ItemEmbedding.__table__.delete().where(
            ItemEmbedding.item_id == spare[0]))
        s.commit()
    got = _estimate(client, row["id"], items=spare,
                    rules=[{"min": 0, "tags": ["any"]}])
    assert got["estimated"] == len(spare) - 1
    assert got["unindexed"] == 1


def test_the_unranked_pictures_are_guessed_at_or_left_out(client):
    """The pictures the ranking PLACED are always covered — that is the
    honest floor of the action. The switch is whether the rest are guessed
    at as well."""
    row, rated, spare, _best, _worst = _setup(client)
    rule = [{"min": 0, "tags": ["any"]}]
    got = _estimate(client, row["id"], rules=rule)          # the default
    assert got["estimated"] == len(rated) + len(spare)
    got = _estimate(client, row["id"], estimate_unranked=False, rules=rule)
    assert got["estimated"] == len(rated)


def test_a_selection_NARROWS_this_one(client):
    """Unlike the rating and tag sessions, where a selection is a priority:
    this is one bulk write rather than a queue, so a selection is the
    pictures somebody picked out for it."""
    row, rated, spare, _best, _worst = _setup(client)
    got = _estimate(client, row["id"],
                    items=spare[:2],
                    rules=[{"min": 0, "tags": ["any"]}])
    assert got["estimated"] == 2


def test_a_scored_picture_keeps_its_own_number(client):
    """Applied to the rated pictures too, the rules read the ranking's OWN
    standing for them — not the fit's answer, which would be near it rather
    than it, and could put a picture the ranking placed at the top under a
    threshold or not depending on the noise."""
    row, rated, spare, _best, _worst = _setup(client)
    # Every rated picture, and only them: their buckets run 0…9 over the
    # chain, so a rule at the top takes exactly the best tenth of them.
    got = _estimate(client, row["id"],
                    estimate_unranked=False,
                    items=rated,
                    rules=[{"min": 9, "tags": ["top"]},
                           {"min": 0, "tags": ["bottom"]}])
    assert got["estimated"] == len(rated)
    assert got["rules"][0]["matched"] >= 1
    assert got["rules"][1]["matched"] >= 1
    # The samples' numbers are the standings, which are whole buckets.
    scores = [v for r in got["rules"] for v in r["sample_scores"]]
    assert scores and all(float(v).is_integer() for v in scores), scores


def test_the_scope_is_walked_A_PAGE_AT_A_TIME(client, monkeypatch):
    """The scope is the library, so nothing here may hold it whole: at a
    million items a list of every id and a dict of every score was tens of
    megabytes before a tag was written, which is why there used to be a cap
    refusing anything past 200,000. The page size is the bound, and the
    answer must not depend on it."""
    from media_compost.ui.server.routers import estimate as mod
    row, rated, spare, best, worst = _setup(client)
    whole = _estimate(client, row["id"], items=spare,
                    rules=[{"min": 7, "tags": ["great"]}])
    monkeypatch.setattr(mod, "CANDIDATE_PAGE", 2)
    paged = _estimate(client, row["id"], items=spare,
                    rules=[{"min": 7, "tags": ["great"]}])
    assert paged["estimated"] == whole["estimated"]
    assert paged["rules"][0]["matched"] == whole["rules"][0]["matched"]
    assert [x["item_id"] for x in paged["rules"][0]["sample"]] \
        == [x["item_id"] for x in whole["rules"][0]["sample"]]
    # …and the WRITE is the same set, paged or not.
    msg = _apply(client, row["id"], items=spare,
                 rules=[{"min": 7, "tags": ["great"]}])
    assert msg.startswith(f"{whole['rules'][0]['matched']} tags on "), msg


def test_a_preview_says_when_it_only_looked_at_a_sample(client, monkeypatch):
    """A preview runs on every edit of a rule, so past a bound it draws a
    scrambled sample rather than reading every vector in the library — and
    it says so, since its counts are then exact over what it scanned and
    nothing more. A WRITE always walks the lot."""
    from media_compost.ui.server.routers import estimate as mod
    row, rated, spare, best, worst = _setup(client)
    monkeypatch.setattr(mod, "PREVIEW_SCAN", 2)
    got = _estimate(client, row["id"],
                    rules=[{"min": 0, "tags": ["any"]}])
    assert got["scanned"] == 2
    assert got["partial"] is True
    assert got["total"] == len(rated) + len(spare)
    assert got["rules"][0]["matched"] <= 2
    # The write is not sampled: it walks the lot, whatever the preview's
    # bound is.
    msg = _apply(client, row["id"], rules=[{"min": 0, "tags": ["any"]}])
    assert msg == (f"{len(rated) + len(spare)} tags on "
                   f"{len(rated) + len(spare)} pictures"), msg


def test_the_write_is_a_job_and_it_is_about_no_picture(client):
    """THE ONE JOB KIND THAT NAMES NO ITEM. It walks a search's whole scope
    a page at a time and never holds the ids — which is what lets it run
    over a million items — so `item_id` is NULL, and naming an arbitrary
    picture would have filed the job on that picture's row."""
    from media_compost.db import Job
    row, rated, spare, best, _worst = _setup(client)
    r = client.post(f"/api/rankings/{row['id']}/estimate/apply",
                    json={"embedders": ["dinov2_small"], "items": spare,
                          "rules": [{"min": 7, "tags": ["great"]}]})
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    with client.lib.db.session() as s:
        job = s.get(Job, jid)
        assert job.kind == "estimate"
        assert job.item_id is None
        assert job.status == "queued"
    # It lists, with no item to name and nothing to select.
    rows = client.get("/api/ml/jobs").json()["jobs"]
    mine = next(j for j in rows if j["id"] == jid)
    assert mine["item_id"] is None and mine["item_name"] == ""
    assert client.get(f"/api/ml/jobs/{jid}/items").json()["item_ids"] == []
    client.lib.jobs.run_one(jid)
    with client.lib.db.session() as s:
        assert {r.item_id for r in s.execute(select(ItemTag).join(
            Tag, Tag.id == ItemTag.tag_id).where(
                Tag.name == "great")).scalars()} == set(best)


def test_a_refusal_belongs_to_the_press_not_to_a_job_row(client):
    """The fit runs before anything is queued: too little evidence is an
    answer a person should get from the button, not from a task that failed
    a minute later."""
    ids = _items(client)
    row = _mk(client, name="Thin")
    _chain(client, row["id"], ids[:4])
    for n, iid in enumerate(ids[:4]):
        _seed(client, iid, n)
    r = client.post(f"/api/rankings/{row['id']}/estimate/apply",
                    json={"rules": [{"min": 8, "tags": ["x"]}]})
    assert r.status_code == 400
    assert client.get("/api/ml/jobs").json()["jobs"] == []


def test_a_cancel_keeps_what_was_already_written(client, monkeypatch):
    """A tag somebody asked for is not a half-rendered video: the write
    commits in chunks, and what a cancel finds already written STAYS."""
    from media_compost.ui.server.routers import estimate as mod
    row, rated, spare, best, _worst = _setup(client)
    monkeypatch.setattr(mod, "CHUNK", 1)
    r = client.post(f"/api/rankings/{row['id']}/estimate/apply",
                    json={"embedders": ["dinov2_small"], "items": spare,
                          "rules": [{"min": 7, "tags": ["great"]}]})
    jid = r.json()["job_id"]
    queue = client.lib.jobs
    real = queue._set_progress
    seen: list[tuple[int, str]] = []

    def spy(job_id, progress, message="", done=None):
        seen.append((progress, message))
        # The cancel lands the moment the first chunk is committed.
        if message.startswith("Writing tags"):
            queue._canceled.add(job_id)
        return real(job_id, progress, message, done)

    monkeypatch.setattr(queue, "_set_progress", spy)
    msg = queue.run_one(jid)
    assert msg.startswith("canceled — 1 tags on 1 pictures"), msg
    with client.lib.db.session() as s:
        kept = {r.item_id for r in s.execute(select(ItemTag).join(
            Tag, Tag.id == ItemTag.tag_id).where(
                Tag.name == "great")).scalars()}
    assert len(kept) == 1 and kept <= set(best), kept
    # The bar says what it is doing, in both phases and in that order.
    assert [m.split(" —")[0] for _p, m in seen][:1] == ["Estimating"]
    assert any(m.startswith("Writing tags") for _p, m in seen)
    assert [p for p, _m in seen] == sorted(p for p, _m in seen)
    queue._canceled.discard(jid)
