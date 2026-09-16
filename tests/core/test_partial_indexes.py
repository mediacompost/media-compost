"""A partial index is only used if the query is SPELLED like its predicate.

SQLite matches a partial index by comparing the query's WHERE terms against
the index's own predicate, and the comparison is syntactic. Probed on 3.53:
`flag` reaches an index declared `WHERE flag`, `flag IS 1` reaches one
declared `WHERE flag IS 1`, and neither reaches the other — nor do `flag = 1`
or `flag IS NOT 0`. A bound parameter reaches none of them at all.

That is a rot nothing else here can see. The index exists, the query is
correct, the answer is right, the tests pass, and the plan quietly falls back
to a full probe: four of these were written in a spelling SQLAlchemy cannot
emit and had never been used once, which cost the sidebar's own counts 351 ms
where they now take 156 ms. So this asserts the PLAN — the only place the
difference shows.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from media_compost.config import Config
from media_compost.db import Database

#: (index name, the real query, what it is for). Each query is the shape the
#: app actually issues — copied from the caller, not invented here, because a
#: query written for the test could be spelled to pass.
CASES = (
    ("ix_item_tags_pending_is1",
     "SELECT count(*) FROM items WHERE EXISTS ("
     "SELECT 1 FROM item_tags it WHERE it.item_id = items.id "
     "AND it.pending IS 1)",
     "prefilter._pending_clause, via /api/library/stats"),
    ("ix_captions_pending_is1",
     "SELECT count(*) FROM items WHERE EXISTS ("
     "SELECT 1 FROM captions c WHERE c.item_id = items.id "
     "AND c.pending IS 1)",
     "prefilter._pending_clause"),
    ("ix_faces_item_live_is0",
     "SELECT count(*) FROM faces WHERE faces.item_id = 1 "
     "AND faces.dismissed IS 0",
     "searchctx.load_face_counts and the faces router"),
    ("ix_text_regions_live_is0",
     "SELECT count(*) FROM text_regions WHERE text_regions.item_id = 1 "
     "AND text_regions.dismissed IS 0",
     "searchctx's text counts and the OCR readers"),
)


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Database:
    return Database(Config(data_dir=tmp_path_factory.mktemp("pi") / "data"))


@pytest.mark.parametrize("index,sql,who", CASES,
                         ids=[c[0] for c in CASES])
def test_the_partial_index_is_actually_chosen(db: Database, index: str,
                                              sql: str, who: str):
    with db.engine.connect() as conn:
        plan = "\n".join(
            str(r) for r in conn.execute(text("EXPLAIN QUERY PLAN " + sql)))
    assert index in plan, (
        f"{index} exists but the plan does not use it — the predicate it is "
        f"declared with no longer matches how {who} spells the query:\n{plan}")


def test_only_the_matching_spelling_reaches_a_partial_index(db: Database):
    """The rule itself, so the reason above is not folklore.

    If a future SQLite starts matching these to each other this goes red,
    which is the right moment to simplify the DDL rather than to discover it
    by accident.
    """
    with db.engine.connect() as conn:
        conn.execute(text("CREATE TABLE _pi (id INTEGER PRIMARY KEY, "
                          "item_id INT, flag BOOLEAN)"))
        conn.execute(text("CREATE INDEX _pi_bare ON _pi (item_id) WHERE flag"))
        conn.execute(text("CREATE INDEX _pi_is1 ON _pi (item_id) "
                          "WHERE flag IS 1"))

        def plan(pred: str) -> str:
            return "\n".join(str(r) for r in conn.execute(
                text(f"EXPLAIN QUERY PLAN SELECT 1 FROM _pi "
                     f"WHERE item_id = 5 AND {pred}")))

        assert "_pi_bare" in plan("flag")
        assert "_pi_is1" in plan("flag IS 1")
        # The spellings do NOT reach each other's index…
        assert "_pi_is1" not in plan("flag")
        assert "_pi_bare" not in plan("flag IS 1")
        # …and these reach neither, which is what SQLAlchemy's `~col` emits.
        for pred in ("flag = 1", "flag IS NOT 0"):
            got = plan(pred)
            assert "_pi_bare" not in got and "_pi_is1" not in got, pred
        conn.execute(text("DROP TABLE _pi"))


def test_sqlalchemy_still_spells_the_booleans_the_way_the_ddl_expects():
    """The other half: the DDL is written to match what SQLAlchemy EMITS, so
    a change in its rendering is what would silently break the plans above."""
    from sqlalchemy.dialects import sqlite

    from media_compost.db import Caption, Face, ItemTag, TextRegion

    d = sqlite.dialect()
    for expr, want in ((ItemTag.pending.is_(True), "item_tags.pending IS 1"),
                       (Caption.pending.is_(True), "captions.pending IS 1"),
                       (Face.dismissed.is_(False), "faces.dismissed IS 0"),
                       (TextRegion.dismissed.is_(False),
                        "text_regions.dismissed IS 0")):
        assert str(expr.compile(dialect=d)) == want


def test_no_index_on_the_tags_table_can_answer_the_discriminator(tmp_path):
    """`kind` says which TAG SET a row belongs to (`db.TagRow`), and
    SQLAlchemy adds it to every read of `Tag` — including the ON clause of a
    join from `item_tags`, `subjects` or `tag_implications`, where the id
    already came from a table that holds none but the library's.

    So no index may LEAD with it, which is what would let a seek answer it
    on its own. With one, a planner that has no `ANALYZE` stats reads that
    equality as the cheapest thing in the query and drives the whole join
    from `tags`: measured on a 100,000-tag catalog, the implication join
    behind `GET /api/tags` went from 3 ms to 4.8 s a chunk, and the listing
    from 7 seconds to 238.

    Behind a real key it is welcome, and uniqueness needs it there: the
    library's names are unique PER KIND (`red` the tag and `red` the meta
    tag are two names), so `uq_tags_library_name_kind` carries it — second.
    The scope that leads an index is `tag_set_id` — a real value, NULL for
    the library, which a seek can use.
    """
    cfg = Config(data_dir=tmp_path / "lib")
    db = Database(cfg)
    with db.engine.connect() as conn:
        for (name,) in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='tags'").all():
            cols = [r[2] for r in conn.exec_driver_sql(
                f"SELECT * FROM pragma_index_info('{name}')").all()]
            assert cols[:1] != ["kind"], f"{name} leads with the discriminator"
        # …and the join a library id drives is planned from the OTHER table.
        plan = "\n".join(str(r) for r in conn.exec_driver_sql(
            "EXPLAIN QUERY PLAN "
            "SELECT tag_implications.tag_id, tags.name FROM tag_implications "
            "JOIN tags ON tags.id = tag_implications.implies_id "
            "AND tags.kind IN ('lib') WHERE tag_implications.tag_id IN (1, 2, 3)"
        ).all())
        assert "SCAN tags" not in plan, plan
    db.engine.dispose()
