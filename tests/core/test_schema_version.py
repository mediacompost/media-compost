"""The library format guard (``db.SCHEMA_VERSION`` / ``user_version``).

The number decides one of three things, and this file is about the two that
are not an upgrade: a library at the current version opens untouched, and a
library this build cannot read is REFUSED and left exactly as it was found.
Refusal is what stops a mismatched library opening almost-correctly —
`create_all` adds missing TABLES and never ALTERs one, so the queries would
run, a column that changed meaning would be read as whatever it used to hold,
and the first write would bake the mixture in.

The third case, where the number is one this build knows how to grow out of,
is `tests/test_migrations.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from media_compost.config import Config
from media_compost.db import SCHEMA_VERSION, Database, Item, LibraryVersionError
from media_compost.migrations import BASELINE


def _user_version(db_path: Path) -> int:
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    try:
        with engine.begin() as conn:
            return int(conn.execute(text("PRAGMA user_version")).scalar_one())
    finally:
        engine.dispose()


def _set_user_version(db_path: Path, value: int) -> None:
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text(f"PRAGMA user_version = {int(value)}"))
    finally:
        engine.dispose()


def test_a_new_library_is_stamped_with_the_current_version(tmp_path: Path):
    cfg = Config(data_dir=tmp_path)
    Database(cfg)
    assert _user_version(cfg.db_path) == SCHEMA_VERSION


def test_reopening_the_same_library_is_fine(tmp_path: Path):
    cfg = Config(data_dir=tmp_path)
    Database(cfg)
    Database(cfg)  # must not raise
    assert _user_version(cfg.db_path) == SCHEMA_VERSION


def test_a_newer_library_is_refused_and_says_both_numbers(tmp_path: Path):
    """A library upgrades but never downgrades. An older build reading a newer
    library writes the columns it knows and drops the ones it does not."""
    cfg = Config(data_dir=tmp_path)
    Database(cfg)
    _set_user_version(cfg.db_path, SCHEMA_VERSION + 1)
    with pytest.raises(LibraryVersionError) as exc:
        Database(cfg)
    msg = str(exc.value)
    assert str(SCHEMA_VERSION + 1) in msg and str(SCHEMA_VERSION) in msg
    assert "never downgrades" in msg
    assert "Nothing was changed" in msg


def test_a_library_older_than_the_baseline_is_refused(tmp_path: Path):
    """Below the baseline there is no ladder to climb, so it is a refusal
    again — and the message says how far back this build reaches.

    Written against `BASELINE - 1` explicitly. It used to say
    `max(SCHEMA_VERSION - 1, 0)`, which happened to be below the baseline
    while the two numbers were close and would have SILENTLY INVERTED into a
    migratable version the moment the format number moved on — a test still
    passing under a name that no longer described what it did.
    """
    cfg = Config(data_dir=tmp_path)
    Database(cfg)
    _set_user_version(cfg.db_path, BASELINE - 1 if BASELINE > 1 else 99)
    with pytest.raises(LibraryVersionError) as exc:
        Database(cfg)
    assert "Nothing was changed" in str(exc.value)


def test_a_refused_library_is_left_exactly_as_it_was(tmp_path: Path):
    """The check runs BEFORE `create_all`, so the build that cannot read a
    library never gets as far as adding its own tables to it."""
    cfg = Config(data_dir=tmp_path)
    Database(cfg)
    _set_user_version(cfg.db_path, SCHEMA_VERSION + 1)
    engine = create_engine(f"sqlite:///{cfg.db_path}", future=True)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE items"))
    engine.dispose()

    with pytest.raises(LibraryVersionError):
        Database(cfg)

    engine = create_engine(f"sqlite:///{cfg.db_path}", future=True)
    try:
        with engine.begin() as conn:
            names = {r[0] for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")).all()}
        assert "items" not in names, "a refused library was written to"
    finally:
        engine.dispose()


def test_a_library_from_before_versioning_is_refused_untouched(tmp_path: Path):
    """Zero is "nobody said" — what an unset header reads as. A blank the
    engine just made is stamped; a file that already holds tables was written
    before the format number existed, which is before the first release, and
    is refused like any other library from below the baseline — adopting it
    would stamp an unknown pre-release shape as current."""
    cfg = Config(data_dir=tmp_path)
    db = Database(cfg)
    with db.Session() as s:
        s.add(Item(name="from before the guard"))
        s.commit()
    db.engine.dispose()
    _set_user_version(cfg.db_path, 0)  # as an unversioned library reads

    with pytest.raises(LibraryVersionError) as exc:
        Database(cfg)
    assert "before the first release" in str(exc.value)
    assert "Nothing was changed" in str(exc.value)
    assert _user_version(cfg.db_path) == 0, "refused means untouched"
