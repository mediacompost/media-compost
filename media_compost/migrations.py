"""The library's on-disk FORMAT NUMBER, and the ladder that upgrades to it.

A library written by an older build must open under a newer one. That promise
starts at :data:`BASELINE` — 19, the format the first public release wrote —
and is kept by an ordered list of steps applied on open, driven by SQLite's
own ``user_version`` header slot.

**The list holds every rung since version 19**, each frozen the day it was
written, and a library at any version from 19 up is climbed through the rungs
it is missing on its first open. Appending a rung IS the version bump:
``CURRENT`` is the last entry's number.

(Two ladders stood here before the release and both were deleted with the
shapes they upgraded, since every library they knew how to open was one of
ours — the second one, eighteen rungs from 1 to 19, on the day of the first
public release. Two rungs of the first lasted a day, and are the lesson worth
keeping: a step's DDL is frozen literal SQL by design, so a rebuild went on
producing a table without the column the model had since gained, and the very
next open of an old library failed on an index for a column the rebuild had
dropped. A ladder is a promise about a format that has stopped moving.)

Why the header and not a ``settings`` row: this has to be readable BEFORE
anything else touches the file, it must survive a table being dropped and
recreated, and a library too old to open is one whose ``settings`` table may
not have the shape the reader expects either.

**This module imports nothing from** :mod:`~media_compost.db`, and that is
structural rather than stylistic. A step must go on producing the shape it
produced the day it was written; reaching for a model would make it produce
whatever the CURRENT shape is, so a version-3 library upgraded under a
version-9 build would take a different route than it did under version 4 and
arrive somewhere no step describes. Every piece of DDL here is therefore
FROZEN LITERAL SQL. ``tests/core/test_migrations.py`` greps for the import.

Adding a step
-------------

Append a :class:`Migration` to :data:`MIGRATIONS`. That is also the version
bump: :data:`CURRENT` is derived from the list, so the constant and the ladder
cannot disagree — which is the one disease a hand-rolled ladder dies of.

* ``mode="txn"`` for the ordinary case. The driver wraps the step in one
  transaction and stamps ``user_version`` as its last statement, so a crash
  rolls the whole step back and the next open re-runs it from a clean start.
* ``mode="raw"`` when the step needs pragmas — a table rebuild does, since
  ``PRAGMA foreign_keys`` is silently IGNORED inside a transaction. Such a
  step owns its connection mode, its ``BEGIN``/``COMMIT`` and its own stamp;
  :func:`rebuild_table` does all three, so no hand-written step spells a
  pragma.
* Name the tables it may change in ``touches``. The migration test asserts
  every OTHER table comes through byte-identical, which turns "my ADD COLUMN
  accidentally rewrote items" into a failure and makes the blast radius a
  reviewable one-liner.
* A change that only adds a TABLE still gets a step and a bump, even though
  ``create_all`` supplies the table for free. The ladder is the changelog of
  the on-disk format: a gap in it cannot be told from a forgotten step, and
  the version number is the only handle a FUTURE step has on "libraries from
  before that table existed".

**A step may not assume any table exists that only the current models
declare.** The ladder runs BEFORE ``create_all`` (see
:meth:`~media_compost.db.Database.__init__` for why), so a step that needs a
table creates it itself with frozen DDL.

What the deleted pre-release steps taught
-----------------------------------------

These are the traps the pre-release ladders' steps cost us to find, kept
because every step written since has met them again.

* **``create_all`` never ALTERs.** It supplies a missing TABLE and nothing
  else, so a column added to a model is invisible to an existing library
  until a step adds it. It also only builds a table's indexes when it builds
  the TABLE, which is why ``Database._ensure_indexes`` re-creates every
  model-declared index on every open — and why an index-only change needs no
  step at all.
* **``PRAGMA foreign_keys`` is silently IGNORED inside a transaction.** A
  table rebuild therefore cannot run in ``mode="txn"``: it needs an
  autocommit connection, its own ``BEGIN``/``COMMIT`` and its own stamp.
  :func:`rebuild_table` is the one place that knows this; no step should
  spell a pragma itself.
* **A rebuild must also set ``legacy_alter_table``.** Without it the rename
  at the heart of a rebuild rewrites every OTHER table's foreign keys onto
  the temporary name, and the damage is somewhere the step never mentions.
* **A hand-written ``ALTER`` and ``create_all`` do not produce the same
  column.** Two columns added by hand came out NULLABLE where a fresh library
  makes them NOT NULL, and a ``server_default`` of ``"0"`` writes
  ``DEFAULT '0'`` where ``text("0")`` writes ``DEFAULT 0`` — a difference no
  query notices and the shape comparison does. A widened inline ``UNIQUE`` is
  worse: the schema census cannot see it at all, so only a behaviour test
  catches it.
* **The comparison IS the test.** An upgraded library must end up in exactly
  the shape a library created today is in — table by table, column by column.
  A golden file would have to be re-recorded on every schema change, and a
  golden re-recorded whenever it goes red is a ratchet that ratchets down.
* **Name what a step touches.** Everything else is asserted byte-identical,
  which turns "my ADD COLUMN rewrote items" into a failure rather than a
  shrug, and makes the blast radius a reviewable one-liner.
* **Decoding every image in the library is not something a step may do.** It
  runs inside a startup hook. A step that wants derived values adds the
  column and says so in :data:`ADVICE`; the values arrive when the user has a
  minute. (The one entry that lived there named a CLI backfill command, and
  those commands are gone, so it now says what is simply absent instead.)
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Sequence

from sqlalchemy import text as sa_text
from sqlalchemy.engine import Connection, Engine


class LibraryVersionError(RuntimeError):
    """This library's format is one this build cannot read."""


class LibraryMigrationError(LibraryVersionError):
    """The upgrade was attempted and a step failed.

    A subclass, so every caller that already handles a version error — the
    CLI's red sentence, the public Python API's re-wrap, the server's startup
    hook — handles this too without knowing it exists.
    """


@dataclass(frozen=True)
class Migration:
    """One rung. ``version`` is the ``user_version`` the step LEAVES behind."""

    version: int
    summary: str
    run: Callable[[Connection], None]
    touches: frozenset[str] = field(default_factory=frozenset)
    mode: Literal["txn", "raw"] = "txn"


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

def table_exists(conn: Connection, table: str) -> bool:
    return conn.execute(
        sa_text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": table},
    ).first() is not None


def columns_of(conn: Connection, table: str) -> dict[str, tuple]:
    """``{name: (type, notnull, default, pk)}``; empty when the table is gone."""
    rows = conn.execute(sa_text(f"PRAGMA table_info({_ident(table)})")).all()
    return {r[1]: (r[2], r[3], r[4], r[5]) for r in rows}


def index_names(conn: Connection, table: str) -> list[str]:
    """The named indexes on a table — the ones that go down with it in a
    rebuild, and whose names the new table wants back."""
    return [r[0] for r in conn.execute(sa_text(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=:t "
        "AND sql IS NOT NULL"), {"t": table}).all()]


def user_version(conn: Connection) -> int:
    return int(conn.execute(sa_text("PRAGMA user_version")).scalar_one())


def stamp_user_version(conn: Connection, value: int) -> None:
    """PRAGMA takes no bound parameter, hence the f-string over our own int."""
    conn.exec_driver_sql(f"PRAGMA user_version = {int(value)}")


def has_user_tables(conn: Connection) -> bool:
    """Does this file hold a library, or is it a blank the engine just made?

    The distinction is the whole of the ``user_version == 0`` case: an unset
    header reads as zero for a brand-new file AND for every library written
    before the guard existed, and the two want opposite treatment.
    """
    return conn.execute(sa_text(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")).first() is not None


def _ident(name: str) -> str:
    """A table/column name for interpolation. Ours are all literals written in
    this file, so this only has to refuse the obviously wrong."""
    if not name.replace("_", "").isalnum():
        raise ValueError(f"not a plain identifier: {name!r}")
    return name


# ---------------------------------------------------------------------------
# Shape changes
# ---------------------------------------------------------------------------

def add_column(conn: Connection, table: str, column: str, ddl: str) -> bool:
    """``ALTER TABLE <table> ADD COLUMN <column> <ddl>``, idempotently.

    Returns False when the column is already there — which is what makes a
    step safe to re-run after a partial failure, and what makes it not matter
    which step claims a column that was originally added with no bump at all.

    ``ddl`` is LITERAL SQL frozen when the step was written ("INTEGER",
    "VARCHAR(16) NOT NULL DEFAULT 'caption'") and is NEVER derived from a
    model column. See the module docstring.
    """
    if column in columns_of(conn, table):
        return False
    conn.exec_driver_sql(
        f"ALTER TABLE {_ident(table)} ADD COLUMN {_ident(column)} {ddl}")
    return True


def rename_table(conn: Connection, old: str, new: str) -> None:
    conn.exec_driver_sql(
        f"ALTER TABLE {_ident(old)} RENAME TO {_ident(new)}")


def rebuild_table(conn: Connection, table: str, *, create_sql: str,
                  stamp: int, columns: Sequence[str] | None = None,
                  select_sql: str | None = None,
                  indexes: Sequence[str] = ()) -> None:
    """Rebuild a table into a new shape, copying what both shapes share.

    The SQLite recipe, generalized from the ``faces`` rebuild that first
    needed it. ``ALTER TABLE ... DROP COLUMN`` cannot stand in: SQLite refuses
    to drop a column a FOREIGN KEY clause mentions, and a type or constraint
    change has no ALTER at all.

    **Callable only from a ``mode="raw"`` step.** Two pragmas make it safe and
    neither is honoured inside a transaction, which is exactly why that mode
    exists: ``foreign_keys=OFF``, or the referencing tables see their rows
    orphaned mid-rebuild; and ``legacy_alter_table=ON``, so the rename does
    NOT rewrite those references to point at the temporary name — they stay on
    the real name, which is what the new table is called by the time the
    transaction ends.

    ``create_sql`` is frozen ``CREATE TABLE`` text, not ``Model.__table__``.
    ``columns`` defaults to the intersection of the old table's columns with
    the new one's, read back off the created table rather than parsed out of
    ``create_sql``. ``indexes`` are frozen ``CREATE INDEX`` statements re-run
    after the copy.
    """
    tmp = f"{_ident(table)}_migrating"
    old_indexes = index_names(conn, table)
    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
    conn.exec_driver_sql("BEGIN")
    try:
        for name in old_indexes:
            conn.exec_driver_sql(f"DROP INDEX {name}")
        old_cols = list(columns_of(conn, table))
        rename_table(conn, table, tmp)
        conn.exec_driver_sql(create_sql)
        if columns is None:
            live = set(columns_of(conn, table))
            columns = [c for c in old_cols if c in live]
        names = ", ".join(_ident(c) for c in columns)
        source = select_sql or f"SELECT {names} FROM {tmp}"
        conn.exec_driver_sql(f"INSERT INTO {_ident(table)} ({names}) {source}")
        conn.exec_driver_sql(f"DROP TABLE {tmp}")
        for ddl in indexes:
            conn.exec_driver_sql(ddl)
        # Last, and inside the transaction: the stamp is what says the step
        # completed, so it must roll back with everything else.
        stamp_user_version(conn, stamp)
        conn.exec_driver_sql("COMMIT")
    except Exception:
        conn.exec_driver_sql("ROLLBACK")
        raise
    finally:
        conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------

#: The oldest version this build upgrades from, and — while the ladder is
#: empty — also the newest: the format the first release writes. FROZEN now
#: that libraries exist outside this repository: moving it forward abandons
#: every library still on an older number, so it moves only when nobody could
#: still be on one.
#:
#: The numbers BELOW it were development formats that never reached anybody.
#: There is no upgrade path from one, and a library carrying one is refused
#: with a sentence saying so rather than climbed: adopting an unknown
#: pre-release shape at the baseline would let ``create_all`` bake the mixture
#: in, which is the silent failure the number exists to prevent.
BASELINE = 37


#: THE LADDER, ascending and gapless from ``BASELINE + 1``. Append only.
#:
#: EMPTY at the first release, and deliberately so: the rungs that stood here
#: upgraded shapes only pre-release libraries ever had, and a step that
#: produces a shape no released build ever wrote is not a migration, it is SQL
#: nobody will ever run. What version 37 means is the first release's shape;
#: everything after it climbs from there.
#:
#: What those rungs cost is kept here, because it binds every rung added now:
#:
#: * The DDL is FROZEN literal SQL, never derived from a model. A step must go
#:   on producing the shape it produced the day it was written — reach for
#:   ``Item.__table__`` and a library upgraded under a future build takes a
#:   different route than it takes today and lands somewhere no step
#:   describes. This module imports nothing from ``db.py``, and a test says so.
#: * The ladder runs BEFORE ``create_all``, so a step may not assume any table
#:   exists that only the current models declare. If it needs one, it creates
#:   it with frozen DDL.
#: * ``touches`` names the tables a step may change. Everything else is
#:   asserted to come through byte-identical.
#: * ``mode="raw"`` for a table rebuild: ``PRAGMA foreign_keys`` is silently
#:   ignored inside a transaction, so a rebuild needs its own connection mode,
#:   its own BEGIN/COMMIT and its own stamp. Rebuild through ``rebuild_table``,
#:   never ``DROP COLUMN``; where several tables are rebuilt, stamp on the LAST.
#: * BEFORE A RUNG DROPS A TABLE, read ``PRAGMA foreign_key_list`` over every
#:   other one. A foreign key is a reference somebody ELSE holds and SQLite
#:   resolves the parent at statement time, so a table whose key names a
#:   dropped one reads perfectly well and fails on the first WRITE — and
#:   ``create_all`` never ALTERs, so only a MIGRATED library carries the fault.
#: * A rung may be corrected before it ships; once it has shipped, the NEXT
#:   rung is the repair for whoever climbed the old wording.
#: * No image decoding in a startup hook.
MIGRATIONS: tuple[Migration, ...] = ()

#: What this build writes. DERIVED, so appending a step IS the version bump.
CURRENT = MIGRATIONS[-1].version if MIGRATIONS else BASELINE


def classify(found: int, *, has_tables: bool) -> tuple[Migration, ...]:
    """What opening a library at ``found`` means. Raises, or returns the plan.

    Pure and read-only. ZERO is "nobody said" — what an unset header reads
    as — and the file's contents say what it means: a blank the engine just
    made is this build's own and plans nothing (the caller stamps it
    :data:`CURRENT` before writing anything else), while a file already
    holding tables was written before the format number existed, i.e. before
    the first release, and is refused untouched like any other library from
    below the baseline. (It was ADOPTED at the baseline while the baseline was
    the first shape; with the baseline at the first release's shape, adopting
    would stamp an unknown pre-release shape as current and let ``create_all``
    bake the mixture in — the silent failure the number exists to prevent.)
    """
    if found == 0 and not has_tables:
        return ()
    if found == CURRENT:
        return ()
    if BASELINE <= found < CURRENT:
        return tuple(m for m in MIGRATIONS if m.version > found)
    if found > CURRENT:
        raise LibraryVersionError(
            f"this is a version {found} library and this build writes version "
            f"{CURRENT}. A library upgrades but never downgrades, so there is "
            f"nothing this build can do with it: install a Media Compost that "
            f"reads version {found} or newer. Nothing was changed."
        )
    what = (f"this is a version {found} library" if found
            else "this library carries no format number, so it was written "
                 "before the first release")
    raise LibraryVersionError(
        f"{what}. This build upgrades libraries from version {BASELINE} onward "
        f"and writes version {CURRENT} — there is no upgrade path from "
        f"{found}. Start a new data directory and import into it. Nothing was "
        f"changed."
    )


def apply(engine: Engine, plan: Sequence[Migration], *,
          on_step: Callable[[Migration], None] | None = None,
          on_done: Callable[[Migration, float], None] | None = None) -> None:
    """Run the steps in order, stamping each as it completes.

    The invariant, and it is exact: **``user_version`` is always the last
    FULLY APPLIED step.** SQLite writes the header through the pager and its
    DDL is transactional, so a ``txn`` step's stamp rolls back with everything
    else it did; a crash anywhere leaves the previous number and the next open
    re-runs that step from a clean start.

    Not one transaction for the whole ladder: a ``raw`` step could not
    participate, a large library would build one enormous WAL, and an
    hour-long all-or-nothing killed at minute 55 achieves nothing where
    per-step commits resume.

    Raw connections and ``text()`` only, never the ORM — whose models describe
    the CURRENT shape and would flush the wrong columns against an
    intermediate one.

    ``on_step`` fires BEFORE a step and ``on_done`` after it, with how long it
    took. Both, rather than one at the end: an hour-long rung reported only on
    completion is an hour of silence, and one reported only on entry never
    says which of them was the hour.
    """
    for m in plan:
        if on_step:
            on_step(m)
        began = time.time()
        try:
            if m.mode == "txn":
                with engine.begin() as conn:
                    m.run(conn)
                    stamp_user_version(conn, m.version)
            else:
                with engine.connect().execution_options(
                        isolation_level="AUTOCOMMIT") as conn:
                    m.run(conn)
        except LibraryVersionError:
            raise
        except Exception as exc:  # noqa: BLE001 — reported, never swallowed
            raise LibraryMigrationError(
                f"upgrading to version {m.version} ({m.summary}) failed: "
                f"{exc}"
            ) from exc
        # A `raw` step stamps itself, so this is what catches one that forgot
        # to — or stamped outside its own transaction — instead of letting it
        # re-run on every open forever.
        with engine.connect() as conn:
            got = user_version(conn)
        if got != m.version:
            raise LibraryMigrationError(
                f"the step to version {m.version} ({m.summary}) left the "
                f"library at version {got}. Nothing after it ran."
            )
        if on_done:
            on_done(m, time.time() - began)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

#: Typed, never inferred. Migrating without a backup is what turns "your disk
#: is full" into "your library is gone".
SKIP_BACKUP_VAR = "MEDIA_COMPOST_SKIP_MIGRATION_BACKUP"

#: How many to keep after a SUCCESSFUL upgrade. More than one because the bug
#: you find is usually not the one that just ran.
KEEP_BACKUPS = 3


def backup_name(found: int, when: float | None = None) -> str:
    """``media-v3-20260807-190851.db``.

    The version in the name is what the file IS, not what it was heading for:
    the question at 2am is "what was this before".
    """
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(when or time.time()))
    return f"media-v{found}-{stamp}.db"


def backup(engine: Engine, db_path: Path, into: Path, found: int) -> Path:
    """Copy the library aside with ``VACUUM INTO``, and return where.

    ``VACUUM INTO`` rather than a filesystem copy because of WAL: ``media.db``
    on its own is NOT the library, so copying the file either misses committed
    frames still sitting in ``-wal`` or catches a torn mid-checkpoint state.
    This reads one consistent committed snapshot through the pager and writes
    a single compacted file with no WAL attached, openable directly by the
    build that wrote it.
    """
    # Asked BEFORE anything is written, so running out of room is a sentence
    # naming both numbers rather than a half-written file.
    free = shutil.disk_usage(db_path.parent).free
    need = int(db_path.stat().st_size * 1.1)
    if free < need:
        raise LibraryMigrationError(
            f"not enough room to back the library up before upgrading it: "
            f"{need // 1_000_000} MB needed, {free // 1_000_000} MB free. "
            f"Free some space and open it again. Nothing was changed."
        )
    into.mkdir(parents=True, exist_ok=True)
    dest = into / backup_name(found)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(f"VACUUM INTO '{dest.as_posix()}'")
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise LibraryMigrationError(
            f"could not back the library up before upgrading it: {exc}. "
            f"Nothing was changed."
        ) from exc
    return dest


#: What a backup is CALLED, and the only thing anything here will delete. The
#: pattern lives beside `backup_name`, which is what produces it: a sweep that
#: guessed at the folder's contents would take whatever somebody had put in it.
BACKUP_GLOB = "media-v*-*.db"


def list_backups(into: Path) -> list[Path]:
    """Every backup in ``into``, newest first. An unreadable folder is an
    empty one — this answers "what is there", not "is the disk healthy"."""
    try:
        return sorted(into.glob(BACKUP_GLOB),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []


def prune_backups(into: Path, keep: int = KEEP_BACKUPS) -> None:
    """Drop all but the newest ``keep``. Only ever called after a SUCCESSFUL
    upgrade, so a failed run cannot destroy the last good copy."""
    for p in list_backups(into)[keep:]:
        try:
            p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Read-only inspection (the CLI's --check / --dry-run)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Inspection:
    """What ``migrate --check`` needs, without opening a Database.

    Constructing a :class:`~media_compost.db.Database` MIGRATES, so the two
    read-only CLI paths must not go anywhere near one.
    """

    path: Path
    exists: bool
    found: int
    current: int
    plan: tuple[Migration, ...]
    problem: str | None

    @property
    def up_to_date(self) -> bool:
        return self.problem is None and not self.plan


def inspect(db_path: Path) -> Inspection:
    """Read ``user_version`` off a library file and classify it.

    Plain ``sqlite3`` opened ``mode=ro``, deliberately, rather than an engine.
    ``db.py`` registers its pragmas on the SQLAlchemy ``Engine`` CLASS, so any
    engine anywhere in the process converts the file it connects to into WAL
    — which means the obvious implementation of "just tell me the version"
    writes to a library the user only asked a question about. Read-only makes
    that impossible rather than merely unintended.
    """
    if not db_path.exists():
        return Inspection(db_path, False, 0, CURRENT, (), None)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        found = int(con.execute("PRAGMA user_version").fetchone()[0])
        tables = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchone() is not None
    finally:
        con.close()
    try:
        plan = classify(found, has_tables=tables)
    except LibraryVersionError as exc:
        return Inspection(db_path, True, found, CURRENT, (), str(exc))
    return Inspection(db_path, True, found, CURRENT, plan, None)


def skip_backup() -> bool:
    return bool(os.environ.get(SKIP_BACKUP_VAR))


#: What a step cannot do for itself, said in words afterwards. A migration
#: runs inside a startup hook, so anything that would decode every image in
#: the library is named rather than done — the column arrives immediately and
#: the values are recovered when the user has a minute.
ADVICE: dict[int, str] = {}


def advice_for(plan: Sequence[Migration]) -> list[str]:
    return [ADVICE[m.version] for m in plan if m.version in ADVICE]
