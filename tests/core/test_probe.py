"""`prefilter.admitted` — "which of these ids does the scope admit" — is
DRIVEN FROM THE IDS, and this holds the plan to it.

The obvious spelling, `cands.where(Item.id.in_(chunk))`, is correct and is a
disaster on one common scope: a GROUP under a KIND filter. SQLite takes
`ix_items_kind` (hidden, kind, id), feeds BOTH multi-valued id constraints
into it — the plan reads `(hidden=? AND kind=? AND id=? AND rowid=?)` — and
runs the cross product of the two lists: 12.8 s per 900-id chunk against a
60,000-member group on a 600,000-item library, minutes for a session's first
picture. Without the kind filter the same chunk is 24 ms, so nothing smaller
than that shape ever showed it.

Nothing but the PLAN can see this — the answer is right either way — which
is why the assertion is on `EXPLAIN QUERY PLAN` (the partial-index test's
reasoning), over a library holding exactly the pathological shape.
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert, select, text

from media_compost.config import Config
from media_compost.db import Database, File, Group, Item, ItemGroup
from media_compost.ops import search
from media_compost.prefilter import admitted
from media_compost.resolve import Resolver


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Database:
    """A few hundred items, a group holding every tenth, half of them
    videos — the group-under-a-kind-filter shape, small."""
    db = Database(Config(data_dir=tmp_path_factory.mktemp("probe") / "data"))
    with db.session() as s:
        s.execute(insert(Group), [{"name": "g", "uid": "g-1"}])
        gid = s.execute(select(Group.id)).scalar_one()
        s.execute(insert(Item), [
            {"uid": f"p{i:05d}", "name": f"item {i}",
             "kind": "image" if i % 2 else "video"}
            for i in range(400)])
        ids = list(s.execute(select(Item.id).order_by(Item.id)).scalars())
        s.execute(insert(File), [
            {"item_id": iid, "number": 1, "path": "files/1.png",
             "sha256": f"s{iid}", "width": 10, "height": 10, "bytes": 1,
             "format": "png"} for iid in ids])
        s.execute(text(
            "UPDATE items SET active_file_id = "
            "(SELECT id FROM files WHERE files.item_id = items.id)"))
        s.execute(insert(ItemGroup), [
            {"item_id": iid, "group_id": gid} for iid in ids if iid % 10 == 0])
        s.commit()
    return db


def _scope(s, db):
    gid = s.execute(select(Group.id)).scalar_one()
    return search.search_filtered(
        s, str(gid), False, False, kind="image", resolver=Resolver(s),
    ).ids_select()


def test_the_probe_is_driven_from_the_ids_not_the_scope(db):
    with db.session() as s:
        sel = _scope(s, db)
        # Plant the temp table the way `admitted` does, then read the plan
        # of the statement it runs.
        admitted(s, sel, [1, 2, 3])
        from media_compost.prefilter import _PROBE
        from sqlalchemy import exists
        stmt = (select(_PROBE.c.id)
                .where(exists(sel.where(Item.id == _PROBE.c.id))))
        sql = str(stmt.compile(db.engine,
                               compile_kwargs={"literal_binds": True}))
        plan = [r[-1] for r in s.execute(text("EXPLAIN QUERY PLAN " + sql))]
        assert plan[0].startswith("SCAN probe_ids"), plan
        assert any("items USING INTEGER PRIMARY KEY" in p for p in plan), plan
        assert not any("AND rowid=?" in p for p in plan), (
            f"two multi-valued id constraints on one index — the cross "
            f"product:\n" + "\n".join(plan))


def test_the_obvious_spelling_is_the_cross_product_this_guards_against(db):
    """The reason the helper exists, kept as a fact rather than a memory:
    the IN-list spelling on this scope plans both id lists into one index
    walk. If SQLite ever stops doing that, this test is the one to delete."""
    with db.session() as s:
        sel = _scope(s, db).where(Item.id.in_(list(range(1, 100))))
        sql = str(sel.compile(db.engine,
                              compile_kwargs={"literal_binds": True}))
        plan = [r[-1] for r in s.execute(text("EXPLAIN QUERY PLAN " + sql))]
        assert any("id=? AND rowid=?" in p for p in plan), plan


def test_admitted_answers_exactly_what_the_scope_admits(db):
    with db.session() as s:
        sel = _scope(s, db)
        want = list(range(0, 500, 3)) + [10**6]
        got = admitted(s, sel, want)
        brute = sorted(int(i) for i in s.execute(
            sel.where(Item.id.in_(want))).scalars())
        assert got == brute
        assert got, "the probe must hit something for this to prove anything"
        # Every hit is an image in the group; nothing else was admitted.
        rows = s.execute(select(Item.id, Item.kind).where(
            Item.id.in_(got))).all()
        assert all(k == "image" and i % 10 == 0 for i, k in rows)
        assert admitted(s, sel, []) == []
        # Duplicates collapse and the answer is ascending.
        assert admitted(s, sel, [20, 20, 10]) == [10, 20]
        assert admitted(s, sel, [21, 11]) == []
