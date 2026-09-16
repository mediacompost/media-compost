"""The upgrade ladder: that it runs, that it is safe, and that it stays honest.

What is tested here is the MACHINERY, driven by a SYNTHETIC ladder built in
each test: the driver, the stamping, the crash behaviour, the backup, the
ordering against `create_all`, and every refusal. That is not a weaker test
than running the real steps would be. A step is a few lines of frozen SQL that
either did its job once, years ago, or did not; the driver is what every
future step will be handed to, and it is the part that can be wrong in ways no
step would reveal.

The one exception is `test_every_real_rung_leaves_the_models_shape_and_nothing
_extra`, which walks the REAL ladder a rung at a time and holds the result to
what `create_all` builds today. What it asks is not about the driver: a step's
DDL is FROZEN, so a rebuilding rung goes on emitting the table as it stood the
day it was written, and the model has moved since.

The `fresh` fixture moves BASELINE to 1 for the length of a test and stamps
a library there, so a synthetic step numbered 2 applies to it whatever the
real baseline is and however many real rungs stand above it. Without that,
a fresh library already stood at the top and `classify` planned nothing, so
every synthetic step silently did not run and its test failed on the column
it was supposed to have added.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from media_compost import migrations
from media_compost.config import Config
from media_compost.db import SCHEMA_VERSION, Database, LibraryVersionError


# ---------------------------------------------------------------------------
# Censuses — what "the same library" and "the same shape" mean here
# ---------------------------------------------------------------------------

def schema_census(db_path: Path) -> dict:
    """Every table's columns, indexes and foreign keys, normalized.

    Read back through ``PRAGMA``, never compared as ``sqlite_master`` TEXT.
    ``ALTER TABLE ADD COLUMN`` appends its column to the stored ``CREATE``
    statement with different whitespace and ordering from SQLAlchemy's DDL
    compiler, so a text comparison fails on every CORRECT migration and tells
    you nothing about the one incorrect one.

    **Column ORDER is deliberately not compared.** `ADD COLUMN` appends and
    `create_all` uses model order, so requiring the order to match would force
    a full table rebuild for every column ever added — an absurd price for a
    difference no query can observe. Do not "fix" this.

    It also cannot see an inline ``UNIQUE``, which materializes as a
    `sqlite_autoindex` this deliberately skips: a step that widens one needs a
    behaviour test of its own.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out: dict = {}
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall()]
        for t in tables:
            cols = {r[1]: (str(r[2]).upper(), r[3], r[4], r[5])
                    for r in con.execute(f"PRAGMA table_info({t})").fetchall()}
            idx = {}
            for r in con.execute(f"PRAGMA index_list({t})").fetchall():
                name, unique = r[1], r[2]
                if name.startswith("sqlite_autoindex"):
                    continue           # implied by a UNIQUE constraint, not declared
                on = tuple(c[2] for c in con.execute(
                    f"PRAGMA index_info({name})").fetchall())
                idx[name] = (unique, on)
            fks = frozenset(
                (r[3], r[2], r[4], r[6])          # from, table, to, on_delete
                for r in con.execute(f"PRAGMA foreign_key_list({t})").fetchall())
            out[t] = {"columns": cols, "indexes": idx, "fks": fks}
        return out
    finally:
        con.close()


def content_census(db_path: Path) -> dict:
    """Per table, ``(row count, digest of every row)``.

    The digest is what turns "my ADD COLUMN accidentally rewrote items" into a
    failure rather than a shrug.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out: dict = {}
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall()]
        for t in tables:
            cols = sorted(r[1] for r in
                          con.execute(f"PRAGMA table_info({t})").fetchall())
            names = ", ".join(f'"{c}"' for c in cols)
            rows = con.execute(
                f"SELECT {names} FROM {t} ORDER BY {names}").fetchall()
            h = hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()
            out[t] = (len(rows), h)
        return out
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh(tmp_path: Path, monkeypatch) -> Config:
    """A library standing at the BOTTOM rung — what every synthetic ladder
    here is climbed from.

    The bottom rung is 1 HERE: the synthetic steps are numbered 2 and 3, so
    the baseline is moved under them for the length of the test (`_ladder`
    then moves CURRENT with the steps). The real baseline is whatever the
    first public release wrote, which is a fact about the product and not
    about this driver — `test_the_promise_starts_at_the_first_release` holds
    it, and nothing else here reads the real number."""
    monkeypatch.setattr(migrations, "BASELINE", 1)
    cfg = Config(data_dir=tmp_path / "lib")
    db = Database(cfg)
    # Two rows, so the backup test can prove it copied a whole library rather
    # than an empty file.
    with db.session() as s:
        from media_compost.db import Tag

        s.add_all([Tag(name="a"), Tag(name="b")])
        s.commit()
    db.engine.dispose()
    _stamp(cfg.db_path, migrations.BASELINE)
    return cfg


def _stamp(db_path: Path, version: int) -> None:
    """Put a library's format stamp back where a test needs it."""
    con = sqlite3.connect(db_path)
    try:
        con.execute(f"PRAGMA user_version = {int(version)}")
        con.commit()
    finally:
        con.close()


def _user_version(db_path: Path) -> int:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return int(con.execute("PRAGMA user_version").fetchone()[0])
    finally:
        con.close()


def _ladder(monkeypatch, *steps: migrations.Migration) -> None:
    """Install a synthetic ladder, and move the target version with it.

    THREE names, and all three are load-bearing: `MIGRATIONS` is what `apply`
    walks, `migrations.CURRENT` is what `classify` compares a library's stamp
    against — patch only the first and every open plans nothing, because the
    library is already AT the current version — and `db.SCHEMA_VERSION` is
    what the messages and the final check read. They are derived from each
    other in the real module, which is exactly why a test that fakes one has
    to fake all of them.
    """
    target = steps[-1].version if steps else migrations.BASELINE
    monkeypatch.setattr(migrations, "MIGRATIONS", steps)
    monkeypatch.setattr(migrations, "CURRENT", target)
    monkeypatch.setattr("media_compost.db.SCHEMA_VERSION", target)


def _adds_a_column(conn) -> None:
    migrations.add_column(conn, "tags", "probe_col", "INTEGER NOT NULL DEFAULT 0")


STEP2 = migrations.Migration(
    version=2, summary="a synthetic step that adds a column",
    run=_adds_a_column, touches=frozenset({"tags"}))


# ---------------------------------------------------------------------------
# The ladder's own shape
# ---------------------------------------------------------------------------

def test_the_promise_starts_at_the_first_release():
    """Version 37 is the format the first release writes and so the oldest one
    outside this repository: the bottom of the ladder is where the promise
    begins and may never move, since raising BASELINE would be this build
    declaring it can no longer read a library it shipped. (The numbers below
    it were development formats that never reached anybody; a library carrying
    one is refused, not climbed.) The ladder itself is free to grow, and
    `_wellformed` below is what says it grew properly."""
    assert migrations.BASELINE == 37
    assert migrations.CURRENT == SCHEMA_VERSION >= migrations.BASELINE


def test_the_ladder_is_wellformed():
    versions = [m.version for m in migrations.MIGRATIONS]
    assert versions == sorted(set(versions)), "steps must ascend, and be unique"
    assert versions == list(range(migrations.BASELINE + 1,
                                  migrations.BASELINE + 1 + len(versions))), (
        "the ladder must be gapless from BASELINE + 1 — a gap cannot be told "
        "from a forgotten step")
    assert migrations.CURRENT == (versions[-1] if versions
                                  else migrations.BASELINE) == SCHEMA_VERSION
    for m in migrations.MIGRATIONS:
        assert m.mode in ("txn", "raw")
        assert m.summary and not m.summary.endswith("."), m.version
        assert isinstance(m.touches, frozenset)


def test_migrations_never_imports_the_models():
    """A step must go on producing the shape it produced the day it was
    written. Reaching for a model would make it produce whatever the CURRENT
    shape is, so a version 1 library upgraded under a future build would take
    a different route than it takes today and land somewhere no step
    describes. The import is the only way that happens by accident."""
    src = (Path(__file__).resolve().parents[2]
           / "media_compost" / "migrations.py").read_text(encoding="utf-8")
    for bad in ("from .db import", "from media_compost.db import",
                "import media_compost.db"):
        assert bad not in src, f"migrations.py must not `{bad}`"


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------

def test_a_step_runs_once_and_stamps_what_it_left_behind(fresh, monkeypatch):
    _ladder(monkeypatch, STEP2)
    Database(fresh).engine.dispose()
    assert _user_version(fresh.db_path) == 2
    assert "probe_col" in schema_census(fresh.db_path)["tags"]["columns"]


def test_a_step_leaves_every_table_it_did_not_declare_alone(fresh, monkeypatch):
    """`touches` is a promise, and this is what makes it one: everything else
    comes through byte-identical, which turns "my ADD COLUMN rewrote items"
    into a failure rather than a shrug."""
    before_shape = schema_census(fresh.db_path)
    before_rows = content_census(fresh.db_path)
    _ladder(monkeypatch, STEP2)
    Database(fresh).engine.dispose()
    after_shape = schema_census(fresh.db_path)
    after_rows = content_census(fresh.db_path)
    for table in before_shape:
        if table in STEP2.touches:
            continue
        assert after_shape[table] == before_shape[table], table
        assert after_rows[table] == before_rows[table], table


#: A column an EARLIER rung's frozen DDL puts back and a LATER one removes
#: for good — the one shape the check below cannot read on its own.
#:
#: It happens whenever a rung rebuilds a table whose snapshot still holds a
#: column a later rung takes away: between those two steps a library really
#: does hold a column the models do not, and that is the ladder working, not a
#: fault. Key it by the rung that REMOVES the column, so the allowance ends
#: there and the column must be gone after it like any other.
#:
#: Empty while the ladder is: fill it in the same commit as the rung that
#: needs it. (`jobs.new_item` was the case that named this, when v23's
#: rebuild carried it and v37 dropped it.)
RESURRECTED: dict[tuple[str, str], int] = {}


def _resurrected(table: str, version: int) -> set[str]:
    """The columns `table` is allowed to still have at `version`."""
    return {col for (tbl, col), gone in RESURRECTED.items()
            if tbl == table and version < gone}


def test_every_real_rung_leaves_the_models_shape_and_nothing_extra(tmp_path):
    """The REAL ladder, one rung at a time, against a MODERN library: after
    each step the file must hold exactly the tables and columns the models
    declare — nothing extra, nothing missing.

    The one test here that runs the real steps, because what it asks is not
    about the driver. Both directions are a bug somebody has already had:

    EXTRA is a rung that leaves a scratch table behind (`rebuild_table`
    renames the original aside), or adds a column under a name the model does
    not carry — a typo in frozen SQL is invisible, since the ORM simply never
    selects it and `create_all` never ALTERs. The class it CANNOT see is a
    column removed from the models with no rung at all: nothing here ever
    produces that shape, and a leftover NOT NULL one breaks every INSERT (see
    `Ranking.target`). The check for that one is a comparison against a
    library of the old vintage, which no fixture holds.

    MISSING is the recorded scar: a step's DDL is FROZEN, so a `mode="raw"`
    rebuild goes on emitting the table as it stood the day it was written, and
    the column the model has gained since is dropped by an upgrade nobody
    would think to re-read. The additive rungs are no-ops over this library
    (`add_column` checks first); the rebuilding ones are the point.
   
    RESURRECTED is the third case, and it is the ladder working rather than a
    scar: see the table below.
    """
    cfg = Config(data_dir=tmp_path / "lib")
    Database(cfg).engine.dispose()
    want = schema_census(cfg.db_path)      # what `create_all` builds today
    _stamp(cfg.db_path, migrations.BASELINE)
    engine = create_engine(f"sqlite:///{cfg.db_path}")
    try:
        for step in migrations.MIGRATIONS:
            migrations.apply(engine, [step])
            have = schema_census(cfg.db_path)
            where = f"after the rung to version {step.version} ({step.summary})"
            assert sorted(set(have) - set(want)) == [], f"extra tables {where}"
            assert sorted(set(want) - set(have)) == [], f"tables lost {where}"
            for table in want:
                extra = (set(have[table]["columns"])
                         - set(want[table]["columns"])
                         - _resurrected(table, step.version))
                assert sorted(extra) == [], f"extra columns in {table} {where}"
                assert (sorted(set(want[table]["columns"])
                               - set(have[table]["columns"]))
                        == []), f"columns lost from {table} {where}"
                # …AND WHAT EACH TABLE POINTS AT. The census has read the
                # foreign keys all along and nothing asked about them. What
                # this catches is a `mode="raw"` rung whose FROZEN DDL names
                # the wrong parent — the same class as the column checks
                # above, and as easy to miss, since the ORM never reads a
                # constraint and `create_all` never ALTERs one.
                #
                # It does NOT catch the bug that prompted it, and the reason
                # is the fixture: this library is built by `create_all` and
                # therefore starts with every FK already right, so a rung
                # that drops a table WITHOUT re-pointing what referenced it
                # leaves nothing here to see. That is what v29 did to
                # `tag_set_implications`, and it stood for five rungs —
                # visible only on a library that really climbed it, and only
                # on a WRITE, since SQLite resolves a parent at statement
                # time. `test_the_v36_rung_repoints_an_implication…` builds
                # that shape on purpose.
                assert have[table]["fks"] == want[table]["fks"], (
                    f"{table} points somewhere else {where}: "
                    f"{sorted(have[table]['fks'])} != "
                    f"{sorted(want[table]['fks'])}")
    finally:
        engine.dispose()


def test_an_additive_rung_builds_the_column_create_all_builds(tmp_path):
    """The rung's ALTER against `create_all`'s CREATE, column for column.

    The one thing `test_every_real_rung_leaves_the_models_shape_and_nothing
    _extra` cannot see: over a modern library an additive rung is a no-op
    (`add_column` checks first), so the DDL it would have emitted is never
    compared to anything. Here the column is taken back OUT of a fresh
    library, which is what the old shape was, and the rung has to put back
    exactly what was removed — `NOT NULL` included, and a `DEFAULT 0` that is
    the number and not the string `'0'` (a difference no query notices and
    the census does).

    Per rung: `(table, column) -> the version that adds it`, listed here
    because `touches` names tables and this needs columns. Empty while the
    ladder is; add a row in the same commit as the rung, and this arms itself.

    It RETURNS rather than skips on an empty ladder: a permanently-skipping
    test reads as coverage in the summary and is not.
    """
    added: dict[tuple[str, str], int] = {}
    if not added:
        return
    cfg = Config(data_dir=tmp_path / "lib")
    Database(cfg).engine.dispose()
    want = schema_census(cfg.db_path)
    con = sqlite3.connect(cfg.db_path)
    try:
        for (table, column) in added:
            con.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        con.execute(f"PRAGMA user_version = {migrations.BASELINE}")
        con.commit()
    finally:
        con.close()
    engine = create_engine(f"sqlite:///{cfg.db_path}")
    try:
        migrations.apply(engine, list(migrations.MIGRATIONS))
    finally:
        engine.dispose()
    have = schema_census(cfg.db_path)
    for (table, _column) in added:
        assert have[table] == want[table], table
    with sqlite3.connect(cfg.db_path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == migrations.CURRENT


def test_the_ladder_is_idempotent(fresh, monkeypatch):
    """Re-running the whole ladder against an upgraded library changes
    nothing. This is what makes a step safe to re-run after a partial
    failure, and what makes two processes racing merely wasteful."""
    _ladder(monkeypatch, STEP2)
    Database(fresh).engine.dispose()
    after_first = schema_census(fresh.db_path), content_census(fresh.db_path)

    engine = create_engine(f"sqlite:///{fresh.db_path}", future=True)
    try:
        migrations.apply(engine, migrations.MIGRATIONS)
    finally:
        engine.dispose()
    assert (schema_census(fresh.db_path),
            content_census(fresh.db_path)) == after_first


def test_a_second_open_does_nothing_and_says_nothing(fresh, monkeypatch, capsys):
    _ladder(monkeypatch, STEP2)
    Database(fresh).engine.dispose()
    capsys.readouterr()
    Database(fresh).engine.dispose()
    out = capsys.readouterr().out
    assert "Upgrading" not in out and "backup" not in out
    assert len(list((fresh.data_dir / "backups").glob("*.db"))) == 1, (
        "a no-op open must not take a backup")


# ---------------------------------------------------------------------------
# Crash safety
# ---------------------------------------------------------------------------

def _explodes(_conn):
    raise RuntimeError("disk went away")


def test_a_failing_step_leaves_the_previous_version_and_the_backup(
        fresh, monkeypatch):
    """`user_version` is always the last FULLY APPLIED step, so a crash rolls
    the partial one back and the next open re-runs it from a clean start."""
    broken = migrations.Migration(version=3, summary="a step that fails",
                                  run=_explodes, touches=frozenset())
    _ladder(monkeypatch, STEP2, broken)
    with pytest.raises(migrations.LibraryMigrationError) as exc:
        Database(fresh)
    assert "disk went away" in str(exc.value)
    # Step 2 committed; step 3 did not.
    assert _user_version(fresh.db_path) == 2
    assert list((fresh.data_dir / "backups").glob("media-v1-*.db")), (
        "the backup is taken before any step runs, which is the point of it")


def test_the_ladder_resumes_where_it_stopped(fresh, monkeypatch):
    broken = migrations.Migration(version=3, summary="a step that fails",
                                  run=_explodes, touches=frozenset())
    _ladder(monkeypatch, STEP2, broken)
    with pytest.raises(migrations.LibraryMigrationError):
        Database(fresh)
    fixed = migrations.Migration(version=3, summary="the same step, working",
                                 run=lambda c: None, touches=frozenset())
    _ladder(monkeypatch, STEP2, fixed)
    Database(fresh).engine.dispose()      # picks up from 2
    assert _user_version(fresh.db_path) == 3


def test_a_step_that_forgets_to_stamp_is_caught(fresh, monkeypatch):
    """A `raw` step stamps itself, so one that forgets would otherwise re-run
    on every open forever, silently."""
    forgetful = migrations.Migration(
        version=2, summary="a raw step that forgets", run=lambda c: None,
        touches=frozenset(), mode="raw")
    _ladder(monkeypatch, forgetful)
    with pytest.raises(migrations.LibraryMigrationError) as exc:
        Database(fresh)
    assert "left the library at version 1" in str(exc.value)


# ---------------------------------------------------------------------------
# Ordering, which is silent when it breaks
# ---------------------------------------------------------------------------

def test_the_ladder_runs_before_create_all(tmp_path, monkeypatch):
    """A step must see the library exactly as the previous build left it.

    If `create_all` ran first, a step that renames a table aside and recreates
    it would fail outright, and — worse — a step that creates a table and
    copies into it would find it already there and empty, i.e. silently
    half-applied. Nothing else pins this ordering, and it is invisible when it
    breaks.

    Driven from a library holding ONE table and a version stamp, which is the
    only way to tell "the step saw it" from "`create_all` made it".
    """
    cfg = Config(data_dir=tmp_path / "old")
    cfg.ensure_dirs()
    con = sqlite3.connect(cfg.db_path)
    con.executescript(
        "CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
        "PRAGMA user_version = 1;")
    con.commit()
    con.close()

    seen: dict = {}

    def probe(conn):
        seen["tables"] = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")).all()}

    monkeypatch.setattr(migrations, "BASELINE", 1)   # the stamp above is 1
    _ladder(monkeypatch, migrations.Migration(
        version=2, summary="a probe", run=probe, touches=frozenset()))
    Database(cfg).engine.dispose()

    assert seen["tables"] == {"tags"}, (
        f"`create_all` ran before the ladder: the step saw tables the old "
        f"library never had ({sorted(seen['tables'] - {'tags'})})")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def test_the_backup_is_openable_and_keeps_its_version(fresh, monkeypatch):
    """A backup that opened as version 0 would be ADOPTED by the build that
    wrote it rather than read as what it is — the one way a backup can be
    quietly useless."""
    _ladder(monkeypatch, STEP2)
    Database(fresh).engine.dispose()
    backups = list((fresh.data_dir / "backups").glob("media-v1-*.db"))
    assert len(backups) == 1, backups
    assert _user_version(backups[0]) == 1
    # And it is a whole library, not a truncated file: VACUUM INTO writes one
    # consistent snapshot with no WAL beside it.
    assert content_census(backups[0])["tags"][0] == 2


def test_backups_are_pruned_but_only_after_a_success(fresh, monkeypatch):
    monkeypatch.setattr(migrations, "KEEP_BACKUPS", 2)
    _ladder(monkeypatch, STEP2)
    Database(fresh).engine.dispose()
    backups = fresh.data_dir / "backups"
    # Three more upgrades' worth of backups, oldest first.
    for i in range(4):
        (backups / f"media-v1-2026010{i}-000000.db").write_bytes(b"x")
    migrations.prune_backups(backups, keep=2)
    assert len(list(backups.glob("*.db"))) == 2


def test_the_upgrade_says_what_it_is_DOING_and_not_only_what_it_did(
        fresh, monkeypatch, capsys):
    """Every slow thing announces itself BEFORE it runs and reports how long
    it took after.

    That is the whole point of the output: an upgrade with no lines for four
    minutes looks like a hang, and the one thing anybody does to a hang is
    kill it. Reported only on COMPLETION — which is what the backup line used
    to be — the longest single operation here is four silent minutes followed
    by a line saying it is over.
    """
    second = migrations.Migration(
        version=3, summary="a second synthetic step",
        run=lambda conn: migrations.add_column(
            conn, "tags", "probe_col_2", "INTEGER NOT NULL DEFAULT 0"),
        touches=frozenset({"tags"}))
    _ladder(monkeypatch, STEP2, second)
    Database(fresh).engine.dispose()
    out = capsys.readouterr().out

    # The heading sizes the job: how many rungs, and how big the thing is.
    assert "2 steps" in out
    # Announced first…
    assert "backing up the library first" in out
    # …and both halves of every rung are there, in order.
    assert out.index("backing up the library first") < out.index("backup:")
    for n, step in ((1, STEP2), (2, second)):
        assert f"{n}/2  {step.summary}" in out
    # Times, on the backup and on each rung — which is what says WHICH of
    # them was the four minutes.
    assert out.count("done in") >= 3


def test_the_backup_can_be_refused_but_only_out_loud(fresh, monkeypatch, capsys):
    monkeypatch.setenv(migrations.SKIP_BACKUP_VAR, "1")
    _ladder(monkeypatch, STEP2)
    Database(fresh).engine.dispose()
    out = capsys.readouterr().out
    assert "NO BACKUP" in out
    assert not (fresh.data_dir / "backups").exists()


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_a_library_from_the_future_is_refused_untouched(fresh):
    engine = create_engine(f"sqlite:///{fresh.db_path}", future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")
    engine.dispose()
    before = schema_census(fresh.db_path)
    with pytest.raises(LibraryVersionError) as exc:
        Database(fresh)
    assert "never downgrades" in str(exc.value)
    assert schema_census(fresh.db_path) == before


def test_the_server_does_not_refuse_to_migrate_on_its_own_account(
        fresh, monkeypatch):
    """The server takes its lock BEFORE opening the library, and a `flock` is
    per open file description — so a second `open()` in the SAME process
    conflicts exactly as another process would.

    Asking "is a server running?" naively therefore has every server answer
    "yes, me" and refuse to upgrade the library it is starting on. That is not
    a subtle failure: the server does not start at all, which is how it was
    found. Left to a real run rather than a unit test, this would have been an
    upgrade that worked everywhere except in the one place it matters.
    """
    from media_compost import instance

    _ladder(monkeypatch, STEP2)
    instance.acquire_server_lock(fresh.data_dir)
    try:
        assert instance.server_is_running(fresh.data_dir) is None, (
            "the process holding the server lock must not see itself")
        Database(fresh).engine.dispose()
        assert _user_version(fresh.db_path) == 2
    finally:
        instance.release_server_lock()


def test_an_upgrade_is_refused_while_a_server_holds_the_library(
        fresh, monkeypatch):
    """A table rebuild drops and recreates a table mid-request, and
    `foreign_keys=OFF` is per-connection, so a serving process would go on
    enforcing keys against a half-rebuilt table."""
    from media_compost import instance

    _ladder(monkeypatch, STEP2)
    monkeypatch.setattr(instance, "server_is_running",
                        lambda _d: "pid 999, media-compost serve")
    with pytest.raises(migrations.LibraryMigrationError) as exc:
        Database(fresh)
    assert "pid 999" in str(exc.value)
    assert _user_version(fresh.db_path) == 1, "and it changed nothing"


# ---------------------------------------------------------------------------
# Read-only inspection
# ---------------------------------------------------------------------------

def test_inspect_reports_without_touching_anything(fresh, monkeypatch):
    """`--check` and `--dry-run` must not go near a `Database`: constructing
    one IS the upgrade, so they would perform the thing they report on."""
    _ladder(monkeypatch, STEP2)
    before = fresh.db_path.read_bytes()
    found = migrations.inspect(fresh.db_path)
    assert found.exists and found.found == 1 and not found.up_to_date
    assert [m.version for m in found.plan] == [2]
    assert fresh.db_path.read_bytes() == before


def test_inspect_says_an_up_to_date_library_is_up_to_date(fresh):
    # NOT the `fresh` fixture's own stamp: that one deliberately stands at the
    # bottom rung so a synthetic ladder has something to climb. What is up to
    # date is a library at CURRENT, which is what an ordinary open leaves.
    _stamp(fresh.db_path, migrations.CURRENT)
    found = migrations.inspect(fresh.db_path)
    assert found.exists and found.found == migrations.CURRENT
    assert found.up_to_date and found.plan == ()


def test_inspect_on_a_library_it_cannot_read_says_so(fresh):
    engine = create_engine(f"sqlite:///{fresh.db_path}", future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA user_version = 999")
    engine.dispose()
    found = migrations.inspect(fresh.db_path)
    assert found.problem and "never downgrades" in found.problem
    assert not found.up_to_date


def test_inspect_on_a_library_that_is_not_there(tmp_path):
    found = migrations.inspect(tmp_path / "nothing.db")
    assert not found.exists and found.up_to_date


def test_a_brand_new_file_is_stamped_not_migrated(tmp_path, capsys):
    cfg = Config(data_dir=tmp_path / "brand-new")
    Database(cfg).engine.dispose()
    assert _user_version(cfg.db_path) == SCHEMA_VERSION
    assert "Upgrading" not in capsys.readouterr().out
    assert not (cfg.data_dir / "backups").exists()


def test_a_library_with_tables_and_no_stamp_is_refused_untouched(tmp_path):
    """ZERO is "nobody said", not "version zero": a blank the engine just made
    is stamped, and a file that already holds tables was written before the
    format number existed — before the first release — and is refused like
    any other library from below the baseline. It was ADOPTED at the baseline
    while the baseline was the first shape; now that the baseline is the
    release's shape, adopting would stamp an unknown pre-release shape as
    current and let `create_all` bake the mixture in."""
    cfg = Config(data_dir=tmp_path / "unstamped")
    cfg.ensure_dirs()
    con = sqlite3.connect(cfg.db_path)
    con.executescript(
        "CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL);")
    con.commit()
    con.close()
    assert _user_version(cfg.db_path) == 0
    before = schema_census(cfg.db_path)
    with pytest.raises(LibraryVersionError) as exc:
        Database(cfg)
    assert "before the first release" in str(exc.value)
    assert "Nothing was changed" in str(exc.value)
    assert _user_version(cfg.db_path) == 0, "refused means untouched"
    assert schema_census(cfg.db_path) == before
    assert not (cfg.data_dir / "backups").exists()


# ---------------------------------------------------------------------------
# A migration and a concurrent WRITER — the launched-UI-under-a-running-script
# case. Two halves: the ladder may not interleave with a chunk (the write
# lease), and the old build's writer must STOP once the format has moved
# (`db.ensure_schema_current`) instead of writing old-shape rows — after a
# rung like v10, rows that are silently wrong forever.
# ---------------------------------------------------------------------------


def _hold_write_lock_like_another_process(data_dir: Path) -> int:
    """A raw lock on ``write.lock`` through the module's own cross-platform
    `_take` — a separate open file description, so it conflicts with
    `acquire_write_lease` from this same test process exactly as another
    process's lease would (and never touches its reentrancy bookkeeping)."""
    import os

    from media_compost import instance

    path = data_dir / instance.WRITE_LOCK_NAME
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
                 0o644)
    instance._take(fd)
    return fd


def test_a_migration_refuses_while_a_write_is_in_flight(fresh, monkeypatch):
    """The ladder takes the write lease: a script mid-chunk holds it, so the
    upgrade waits and then REFUSES with the holder named — it must never run
    interleaved with a live writer's chunk, racing it on busy_timeout."""
    import os

    _ladder(monkeypatch, STEP2)
    monkeypatch.setattr("media_compost.db.MIGRATE_WRITE_WAIT", 0.2)
    fd = _hold_write_lock_like_another_process(fresh.data_dir)
    try:
        with pytest.raises(LibraryVersionError, match="mid-write"):
            Database(fresh)
        # Refused means REFUSED: the library was left exactly as found.
        assert _user_version(fresh.db_path) == migrations.BASELINE
    finally:
        os.close(fd)
    # With the writer gone the same open upgrades normally.
    Database(fresh).engine.dispose()
    assert _user_version(fresh.db_path) == STEP2.version


def test_an_import_run_stops_when_the_library_is_upgraded_under_it(tmp_path):
    """The importer re-checks the format at every chunk edge — exactly where
    a newer build's migration can slot in, since it takes the same lease the
    chunks do. An old build carrying on would insert rows in the old shape
    with no error anywhere; stopping loudly is the only honest answer."""
    from media_compost import instance
    from media_compost.importer import ImportOptions, Importer
    from media_compost.storage import ItemStore
    from tests.core.conftest import make_image

    cfg = Config(data_dir=tmp_path / "lib")
    db = Database(cfg)
    store = ItemStore(cfg)
    a = make_image(tmp_path / "a.png", seed=1)
    b = make_image(tmp_path / "b.png", seed=2)
    opts = ImportOptions(folders_as_groups=False)

    with db.session() as s:
        imp = Importer(s, store, cfg)
        imp.begin_run(opts)
        assert imp.add_source(a, opts).status == "imported"
        # End the chunk the way the cadence does: commit + lease release.
        imp._last_commit_time = 0.0
        imp.add_source(a, opts)  # a duplicate; its cadence check closes the chunk
        assert imp._leased is False, "the chunk must have ended"

        # A newer build upgrades between two chunks.
        _stamp(cfg.db_path, SCHEMA_VERSION + 1)

        with pytest.raises(LibraryVersionError, match="upgraded to format"):
            imp.add_source(b, opts)
        # The lease was released before raising — a leak here would make the
        # web import job hold it for the life of its process.
        assert str(cfg.data_dir) not in instance._write_held
    _stamp(cfg.db_path, SCHEMA_VERSION)  # put it back for teardown


def test_a_script_write_stops_when_the_library_is_upgraded_under_it(tmp_path):
    """`Library._do` and `transaction()` take the same check at depth 0: a
    long-running script's single-call writes are units of work too, and the
    migration can slot between any two of them."""
    from media_compost import instance
    from media_compost.library import LibraryVersionError as PubVersionError
    from media_compost.library import open_library

    with open_library(tmp_path / "lib") as lib:
        lib.tags.create("before")            # sanity: writes work

        _stamp(lib.config.db_path, SCHEMA_VERSION + 1)
        with pytest.raises(PubVersionError, match="upgraded to format"):
            lib.tags.create("after")
        with pytest.raises(PubVersionError, match="upgraded to format"):
            with lib.transaction():
                pass
        assert str(lib.config.data_dir) not in instance._write_held

        # Reads are untouched — the lease has never gated them.
        assert "before" in set(lib.tags)
        _stamp(lib.config.db_path, SCHEMA_VERSION)  # so close() can commit
