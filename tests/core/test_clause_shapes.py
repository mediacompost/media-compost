"""A rare thing is looked up BY ITS OWN ROWS, never once per item — and this
holds the PLAN to it.

A condition asking "does this item have X" has two spellings that return the
same answer. As a correlated ``EXISTS``, SQLite walks the view's sort index
and probes X's table once per row: with no stats it cannot turn that around,
so a tag on twenty-one pictures in a library of 1.5M costs 1.5M b-tree
lookups. As ``items.id IN (SELECT …)``, X's own rows are read once into an
ephemeral index and the items are fetched by rowid. Measured on 1.5M
pictures, page 1 of a search with the view's own total:

    a tag on 21 items                     1,101 -> 62 ms
    a `camera_model` on 3,000               496 -> 17 ms
    `CAPTION:` with 5,000 captions           411 -> 21 ms

Nothing but the plan can see this — the answer is right either way, and a
test that only counted statements or timed a small library would pass on
both — which is `test_probe.py`'s reasoning about the same class of bug.

The other half is the THRESHOLD (`prefilter._ID_LIST_MAX`): past it the list
stops being worth building and the correlated form is right again, so each
case is asserted in BOTH directions.
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert, select, text

from media_compost import prefilter, query as q
from media_compost.config import Config
from media_compost.db import (
    Caption, Database, File, Item, ItemMetadata, ItemTag, Tag,
)
from media_compost.ops import search
from media_compost.resolve import Resolver


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Database:
    """Four hundred pictures, exactly one of which carries each rare thing —
    the shape the complaint was about, small."""
    db = Database(Config(data_dir=tmp_path_factory.mktemp("shapes") / "data"))
    with db.session() as s:
        s.execute(insert(Item), [{"uid": f"p{i:05d}", "name": f"i{i}",
                                  "kind": "image"} for i in range(400)])
        ids = list(s.execute(select(Item.id)).scalars())
        s.execute(insert(File), [
            {"item_id": i, "path": "1.png", "format": "png", "bytes": 1,
             "width": 8, "height": 8, "sha256": f"h{i}"} for i in ids])
        s.execute(text("UPDATE items SET active_file_id = "
                       "(SELECT id FROM files WHERE files.item_id = items.id)"))
        s.execute(insert(Tag), [{"name": "rare", "comment": ""}])
        tid = s.execute(select(Tag.id)).scalar_one()
        s.execute(insert(ItemTag), [{"item_id": ids[0], "tag_id": tid,
                                     "negative": False, "pending": False}])
        s.execute(insert(ItemMetadata), [
            {"item_id": ids[0], "name": "camera_model", "mtype": "text",
             "text_value": "Rare Cam", "raw": "Rare Cam"}])
        s.execute(insert(Caption), [
            {"item_id": ids[0], "text": "a picture", "position": 0,
             "kind": "caption", "pending": False, "model": "",
             "edited": False}])
        s.commit()
    return db


#: label -> the condition, and the table its rows live in as the plan spells
#: it (an alias keeps the table's name as a prefix, so this matches either).
CASES = [
    ("tag", q.TagCond(name="rare"), "item_tags"),
    ("meta", q.MetaCond(name="camera_model", mtype="text", op="=",
                        value="Rare Cam"), "item_metadata"),
    ("caption", q.CaptionCond(mode="has"), "captions"),
]


def _plan(db: Database, s, node) -> list[str]:
    """The page query's plan for a view filtered by this one condition."""
    cands = search.search_filtered(s, groups="", ungrouped=False,
                                   query=q.Group(children=[node]),
                                   resolver=Resolver(s))
    sel = prefilter.base_select([Item.id], None, list(cands.where)).limit(60)
    sql = str(sel.compile(db.engine, compile_kwargs={"literal_binds": True}))
    return [row[-1] for row in s.execute(text("EXPLAIN QUERY PLAN " + sql))]


def _lines_for(plan: list[str], table: str) -> list[str]:
    """The plan's steps that read that table, whatever they are called."""
    return [ln for ln in plan if f" {table}" in ln]


@pytest.mark.parametrize("label,node,table", CASES,
                         ids=[c[0] for c in CASES])
def test_a_rare_thing_is_read_once_into_a_list(db, label, node, table):
    with db.session() as s:
        plan = _plan(db, s, node)
    assert any("LIST SUBQUERY" in ln for ln in plan), (label, plan)
    reads = _lines_for(plan, table)
    assert reads, (label, plan)
    # The point: nothing says CORRELATED about this table's own rows.
    for i, ln in enumerate(plan):
        if "CORRELATED" in ln:
            assert table not in plan[i + 1], (label, plan)


@pytest.mark.parametrize("label,node,table", CASES,
                         ids=[c[0] for c in CASES])
def test_past_the_threshold_it_is_a_correlated_exists_again(
        db, label, node, table, monkeypatch):
    """The switch, in the other direction. A cap of zero is what a thing
    bigger than the library looks like to the compiler, and the clause has
    to go back — otherwise the threshold is decoration and the measured
    regression at 1.2M rows is waiting in the next library."""
    monkeypatch.setattr(prefilter, "_ID_LIST_MAX", 0)
    with db.session() as s:
        plan = _plan(db, s, node)
    idx = [i for i, ln in enumerate(plan) if "CORRELATED" in ln]
    assert any(table in plan[i + 1] for i in idx if i + 1 < len(plan)), (
        label, plan)
