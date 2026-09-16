"""EVERY foreign-key column is indexed, and that is a performance contract.

With ``PRAGMA foreign_keys=ON`` — which the connect hook sets — SQLite has to
find the children of a row before it can delete it. With no index on the
child's FK column that search is a FULL TABLE SCAN, once per parent row, so a
bulk delete over a big library is quadratic in the size of the library rather
than linear in what it deletes.

It is not a theoretical cost. On a synthetic 100k-item library the storage
prune took **15 seconds per 500 items**, of which 14.3 s was two statements:
`DELETE FROM files` (10.9 s) and `DELETE FROM items` (3.3 s). Three unindexed
columns were doing it — `items.active_file_id`, `files.derived_from_file_id`
and `files.source_file_id`, each 98k rows scanned per file removed — plus
`items.link_item_id` for the items. Indexed, the same chunk takes 0.59 s and
the cost stops growing with the library: 0.62 s at 50k items, 0.64 s at 250k.

So this is a ratchet rather than a one-off repair, and it is deliberately
absolute — no exception list. An index on a FK column is cheap, every one of
these parents is deleted somewhere (the prune, Empty Trash, a merge, a
re-import), and "this table is small today" is not a property that holds.
A composite index counts only when the FK column is its FIRST column, which
is the only form SQLite can use for the lookup.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from media_compost.db import Database
from media_compost.ui.config import UiConfig


def _usable_first_columns(db: sqlite3.Connection, table: str) -> set[str]:
    """Columns SQLite can look a row up by: the first column of any index,
    plus the primary key."""
    cols: set[str] = set()
    for index in db.execute(f"PRAGMA index_list('{table}')").fetchall():
        info = db.execute(f"PRAGMA index_info('{index[1]}')").fetchall()
        if info:
            cols.add(info[0][2])
    for column in db.execute(f"PRAGMA table_info('{table}')").fetchall():
        if column[5]:  # part of the primary key
            cols.add(column[1])
    return cols


def test_every_foreign_key_column_is_indexed(tmp_path: Path):
    Database(UiConfig(data_dir=tmp_path / "data"))
    con = sqlite3.connect(tmp_path / "data" / "media.db")
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        unindexed = [
            f"{table}.{fk[3]} -> {fk[2]}.{fk[4]}"
            for table in tables
            for fk in con.execute(
                f"PRAGMA foreign_key_list('{table}')").fetchall()
            if fk[3] not in _usable_first_columns(con, table)
        ]
    finally:
        con.close()
    assert unindexed == [], (
        "these foreign-key columns have no index, so deleting a parent row "
        "scans the whole child table: " + ", ".join(sorted(unindexed))
    )


def test_an_existing_library_gains_them_when_it_is_OPENED(tmp_path: Path):
    """`create_all` never touches a table it did not create, so a library made
    before an index was declared would never get it — which is what
    `Database._ensure_indexes` is for. Without this the fix above reaches new
    libraries only, and the one library that needs it is the big old one."""
    data = tmp_path / "data"
    Database(UiConfig(data_dir=data))
    dropped = ["ix_items_active_file_id", "ix_files_derived_from_file_id",
               "ix_items_link_item_id"]

    con = sqlite3.connect(data / "media.db")
    for name in dropped:
        con.execute(f"DROP INDEX IF EXISTS {name}")
    con.commit()
    present = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    con.close()
    assert not (present & set(dropped)), "the drop is what the test rests on"

    Database(UiConfig(data_dir=data))  # open it again

    con = sqlite3.connect(data / "media.db")
    present = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    con.close()
    assert set(dropped) <= present
