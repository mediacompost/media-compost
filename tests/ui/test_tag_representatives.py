"""A tag's REPRESENTATIVE items — the Tags tab's strips (`representatives.py`).

What these pin: the first eligible assignments are adopted up to the cap and
no further; a representative losing the tag — through the ORM, through a
Core delete, through the item going — leaves a gap a random pick fills; a
refusal takes the item off, is never re-picked while the tag stays on the
item, and is forgotten with the assignment; a negative and a pending row
never stand for a tag; a tag with fewer items than the
cap shows all of them and settles without looping; and the strip endpoint
tops a short tag up on the way, which is the safety net for every writer
the flush listener cannot see.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from media_compost import representatives as reps
from media_compost.db import Item, ItemTag, Tag, TagRepresentative
from media_compost.importer import ImportOptions, Importer
from media_compost.testing import make_image
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

N_ITEMS = 12


@pytest.fixture
def client(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(N_ITEMS):
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


def _assign(client, item_id: int, tag: str, negative=False):
    r = client.post(f"/api/tags/assign/item/{item_id}",
                    json={"tag": tag, "negative": negative})
    assert r.status_code == 200, r.text


def _unassign(client, item_id: int, tag: str):
    r = client.delete(f"/api/tags/assign/item/{item_id}/{tag}")
    assert r.status_code == 200, r.text


def _tag_id(client, name: str) -> int:
    with client.lib.db.session() as s:
        return s.execute(select(Tag.id).where(Tag.name == name)).scalar_one()


def _strip(client, tag_id: int) -> list[int]:
    r = client.get(f"/api/tags/representatives?ids={tag_id}")
    assert r.status_code == 200, r.text
    return [x["item_id"] for x in r.json()["reps"].get(str(tag_id), [])]


def _rows(client, tag_id: int) -> list[tuple[int, bool]]:
    with client.lib.db.session() as s:
        return [(int(i), bool(r)) for i, r in s.execute(
            select(TagRepresentative.item_id, TagRepresentative.refused)
            .where(TagRepresentative.tag_id == tag_id)
            .order_by(TagRepresentative.item_tag_id)).all()]


# ---- adoption ------------------------------------------------------------


def test_the_first_assignments_are_adopted_up_to_the_cap(client):
    ids = _items(client)
    for iid in ids:
        _assign(client, iid, "cat")
    tid = _tag_id(client, "cat")
    live = [i for i, refused in _rows(client, tid) if not refused]
    assert live == ids[:reps.MAX_REPRESENTATIVES], \
        "the FIRST ones, in order, and no more"
    assert _strip(client, tid) == ids[:reps.MAX_REPRESENTATIVES]


def test_a_small_tag_shows_all_of_its_items_and_settles_without_looping(client):
    ids = _items(client)
    for iid in ids[:3]:
        _assign(client, iid, "rare")
    tid = _tag_id(client, "rare")
    assert _strip(client, tid) == ids[:3]
    with client.lib.db.session() as s:
        assert reps.settle(s, [tid]) == {}, "nothing more to pick"
    assert _strip(client, tid) == ids[:3]


def test_a_negative_or_pending_row_never_stands_for_a_tag(client):
    ids = _items(client)
    _assign(client, ids[0], "cat", negative=True)
    with client.lib.db.session() as s:
        tag = s.execute(select(Tag).where(Tag.name == "cat")).scalars().one()
        s.add(ItemTag(item_id=ids[1], tag_id=tag.id, pending=True))
        s.commit()
        tid = tag.id
    assert _strip(client, tid) == []
    # Approving the pending guess makes it an ordinary assignment: adopted.
    with client.lib.db.session() as s:
        row = s.execute(select(ItemTag).where(
            ItemTag.item_id == ids[1], ItemTag.tag_id == tid)).scalars().one()
        row.pending = False
        s.commit()
    assert _strip(client, tid) == [ids[1]]


# ---- the gap and the pick -------------------------------------------------


def test_a_representative_losing_the_tag_is_replaced_by_a_random_other(client):
    ids = _items(client)
    for iid in ids:
        _assign(client, iid, "cat")
    tid = _tag_id(client, "cat")
    first = _strip(client, tid)
    gone = first[0]
    _unassign(client, gone, "cat")          # a Core delete + an explicit settle
    after = _strip(client, tid)
    assert gone not in after
    assert len(after) == reps.MAX_REPRESENTATIVES
    assert set(after) - set(first) <= set(ids[reps.MAX_REPRESENTATIVES:]), \
        "the newcomer is one of the items that were waiting"
    # Its rows are gone entirely — nothing remembers an assignment that is
    # no longer there.
    assert all(i != gone for i, _ in _rows(client, tid))


def test_a_flip_to_negative_drops_the_representative_and_fills_the_gap(client):
    ids = _items(client)
    for iid in ids:
        _assign(client, iid, "cat")
    tid = _tag_id(client, "cat")
    first = _strip(client, tid)
    with client.lib.db.session() as s:
        row = s.execute(select(ItemTag).where(
            ItemTag.item_id == first[0], ItemTag.tag_id == tid)).scalars().one()
        row.negative = True
        s.commit()
    after = _strip(client, tid)
    assert first[0] not in after and len(after) == reps.MAX_REPRESENTATIVES


def test_an_item_going_takes_its_representative_rows_with_it(client):
    ids = _items(client)
    for iid in ids[:4]:
        _assign(client, iid, "cat")
    tid = _tag_id(client, "cat")
    with client.lib.db.session() as s:
        s.delete(s.get(Item, ids[0]))
        s.commit()
        left = s.execute(select(TagRepresentative.item_id).where(
            TagRepresentative.tag_id == tid)).scalars().all()
    assert ids[0] not in left, "the DB cascade, not any listener"
    assert _strip(client, tid) == ids[1:4]


# ---- the refusal -----------------------------------------------------------


def test_a_refusal_removes_the_item_picks_another_and_is_remembered(client):
    ids = _items(client)
    for iid in ids:
        _assign(client, iid, "cat")
    tid = _tag_id(client, "cat")
    first = _strip(client, tid)
    refused = first[0]
    r = client.delete(f"/api/tags/{tid}/representatives/{refused}")
    assert r.status_code == 200, r.text
    after = [x["item_id"] for x in r.json()["reps"]]
    assert refused not in after and len(after) == reps.MAX_REPRESENTATIVES
    assert (refused, True) in _rows(client, tid), "remembered as refused"
    # Every later settle steps around it: take the tag off the others until
    # only the refused item and one more are left — the strip still never
    # shows the refused one.
    for iid in ids:
        if iid not in (refused, ids[-1]):
            _unassign(client, iid, "cat")
    assert _strip(client, tid) == [ids[-1]]
    # Refusing an item that does not carry the tag is a 404 by name.
    r = client.delete(f"/api/tags/{tid}/representatives/{ids[1]}")
    assert r.status_code == 404
    # The refusal lives as long as the assignment: off and on again, the
    # item is an ordinary candidate.
    _unassign(client, refused, "cat")
    assert all(i != refused for i, _ in _rows(client, tid))
    _assign(client, refused, "cat")
    assert refused in _strip(client, tid)


# ---- the safety net -------------------------------------------------------


def test_the_strip_tops_up_a_tag_no_listener_saw(client):
    """A Core delete in a session of its own — what a script, a merge or an
    older build's write looks like to the listener: nothing. The row went
    by cascade, and the strip's read fills the gap."""
    ids = _items(client)
    for iid in ids:
        _assign(client, iid, "cat")
    tid = _tag_id(client, "cat")
    first = _strip(client, tid)
    with client.lib.db.session() as s:
        s.execute(delete(ItemTag).where(ItemTag.item_id == first[0],
                                        ItemTag.tag_id == tid))
        s.commit()
        left = s.execute(select(TagRepresentative.item_id).where(
            TagRepresentative.tag_id == tid, TagRepresentative.refused.is_(False)
        )).scalars().all()
    assert len(left) == reps.MAX_REPRESENTATIVES - 1, "short until read"
    after = _strip(client, tid)
    assert first[0] not in after and len(after) == reps.MAX_REPRESENTATIVES


def test_the_pick_is_a_seek_and_wraps(client):
    """`_pick_one` seeks the first eligible row at or past a random id and
    wraps to the front — a draw landing past every eligible item must still
    find one, and the ones already standing are stepped over."""
    import random

    ids = _items(client)
    for iid in ids:
        _assign(client, iid, "cat")
    tid = _tag_id(client, "cat")
    with client.lib.db.session() as s:
        bounds = reps._bounds(s, ItemTag, tid)
        assert bounds == (ids[0], ids[-1])
        # Every draw, however it lands, answers one of the four not standing.
        waiting = set(ids[reps.MAX_REPRESENTATIVES:])
        seen = set()
        for seed in range(40):
            got = reps._pick_one(s, tid, bounds, random.Random(seed))
            assert got is not None and got[1] in waiting
            seen.add(got[1])
        assert len(seen) > 1, "a random pick, not always the same item"


def test_the_endpoint_names_only_tags_it_was_asked_for(client):
    ids = _items(client)
    _assign(client, ids[0], "a")
    _assign(client, ids[1], "b")
    ta, tb = _tag_id(client, "a"), _tag_id(client, "b")
    r = client.get(f"/api/tags/representatives?ids={ta},{tb},x,")
    assert r.status_code == 200
    got = r.json()["reps"]
    assert set(got) == {str(ta), str(tb)}
    assert [x["item_id"] for x in got[str(ta)]] == [ids[0]]
    assert client.get("/api/tags/representatives").json() == {"reps": {}}


def test_two_readers_picking_the_same_assignment_do_not_collide(client):
    """TOPPING UP HAPPENS ON THE READ PATH, and scrolling a list of tags
    fires several of those at once. Each session's pick filters against the
    rows it can SEE, so two of them settling the same tag choose the same
    free assignment — and whichever wrote second used to break the primary
    key: "UNIQUE constraint failed: tag_representatives.item_tag_id", a
    traceback in the log per row, for a read that was only meant to fill a
    gap.

    Read, read, write, write — the order two requests actually interleave
    in, which is why neither reader can see the other's choice.
    """
    import random

    for iid in _items(client):
        _assign(client, iid, "crowded")
    lib = client.lib
    tid = _tag_id(client, "crowded")
    with lib.db.session() as s:
        s.execute(delete(TagRepresentative).where(TagRepresentative.tag_id == tid))
        s.commit()

    # BOTH READ FIRST, neither seeing the other: same seed, same free pool,
    # so they land on the same assignment — which is the whole problem.
    with lib.db.session() as a:
        bounds = reps._bounds(a, ItemTag, tid)
        mine = reps._pick_one(a, tid, bounds, random.Random(1))
    with lib.db.session() as b:
        theirs = reps._pick_one(b, tid, bounds, random.Random(1))
    assert mine is not None and mine == theirs

    # …then both write. The first claims it; the second must find it taken
    # and say so, rather than raising.
    with lib.db.session() as a:
        assert reps.claim(a, mine[0], tid, mine[1]) is True
        a.commit()
    with lib.db.session() as b:
        assert reps.claim(b, theirs[0], tid, theirs[1]) is False
        b.commit()

    with lib.db.session() as s:
        rows = s.execute(select(TagRepresentative).where(
            TagRepresentative.tag_id == tid)).scalars().all()
        assert len(rows) == 1 and rows[0].item_tag_id == mine[0]

    # And the ordinary top-up over the same tag, twice, is still bounded.
    with lib.db.session() as s:
        reps.settle(s, [tid])
        s.commit()
    with lib.db.session() as s:
        reps.settle(s, [tid])
        s.commit()
    with lib.db.session() as s:
        assert s.execute(select(func.count()).select_from(TagRepresentative)
                         .where(TagRepresentative.tag_id == tid)
                         ).scalar_one() == reps.MAX_REPRESENTATIVES
