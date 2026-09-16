"""THE LIBRARY REVISION TOKEN, which everything expensive is remembered on.

`Database.cached` drops its whole memo the moment `Database.revision` answers
something else, so a token that moves when nothing has changed is a cache
that never hits — and the reads held there are the expensive ones by
definition (the Tags tab's `set-numbers` alone is 260 ms on a 132,255-entry
set).

The trap this pins: `PRAGMA data_version` counts changes made by OTHER
connections, and "other" is relative to the connection asking. A server hands
each request whatever connection its pool has free, so after any write the
writing connection and the rest disagree for ever — and the token flapped
from one request to the next.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from media_compost.config import Config
from media_compost.db import Database, Tag


def _tag(s, name: str) -> None:
    s.add(Tag(name=name))
    s.commit()


def test_every_connection_answers_the_same_revision(tmp_path):
    db = Database(Config(data_dir=tmp_path / "lib"))
    # FOUR AT ONCE, so the pool really hands out four connections rather than
    # the same one four times.
    sess = [db.session() for _ in range(4)]
    try:
        before = [db.revision(s) for s in sess]
        assert len(set(before)) == 1, before

        # A write through ONE of them — which is what makes the connections
        # disagree: SQLite's counter never moves for the writer itself.
        _tag(sess[0], "kitten")

        # THE FIRST PASS AFTER A WRITE IS ALLOWED TO RISE (the mark is raised
        # by whichever connection first sees the commit), and the memo is
        # being dropped over that write anyway. What matters is that it then
        # SETTLES: every pass after it agrees, on every connection, in any
        # order, for as long as nothing writes. That is the half a
        # per-connection counter could never do — it left two answers
        # standing for ever, and the token flapped between them from one
        # request to the next.
        [db.revision(s) for s in sess]
        after = [db.revision(s) for s in sess]
        assert len(set(after)) == 1, after
        assert after[0] != before[0]
        assert [db.revision(s) for s in sess] == after
        assert [db.revision(s) for s in reversed(sess)] == after
    finally:
        for s in sess:
            s.close()


def test_a_held_answer_is_not_dropped_by_reading_it_elsewhere(tmp_path):
    """What the flap actually cost: the memo emptied between two reads that
    changed nothing, so every answer held on the revision — the tag set's
    numbers, its category trails, the view's total, the sidebar's stats —
    was recomputed on about half of all requests for the rest of the
    session."""
    db = Database(Config(data_dir=tmp_path / "lib"))
    sess = [db.session() for _ in range(4)]
    try:
        # EVERY CONNECTION HAS READ BEFORE ANYTHING WRITES, which is the only
        # state a live server is ever in — and the state SQLite's counter
        # needs to diverge: a connection that has not touched the file yet
        # takes the current value as its baseline and agrees by accident.
        [db.revision(s) for s in sess]
        _tag(sess[0], "puppy")
        # One pass for the mark to settle — a write drops the memo anyway,
        # and it is the writer's own connection that is behind (see
        # `Database.revision`).
        [db.revision(s) for s in sess]
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return sorted(sess[0].execute(select(Tag.name)).scalars())

        # Once, however many connections ask and in whatever order.
        for s in sess + list(reversed(sess)):
            assert db.cached(s, "names", compute) == ["puppy"]
        assert calls["n"] == 1

        # …and it IS dropped by a write, which is the whole contract.
        _tag(sess[2], "kitten")
        assert db.cached(sess[1], "names", compute) == ["kitten", "puppy"]
        assert calls["n"] == 2
    finally:
        for s in sess:
            s.close()


def test_only_the_database_reads_the_per_connection_counter():
    """ONE READER OF `PRAGMA data_version`, AND IT IS `Database.revision`.

    A grep, because the failure this prevents is invisible from the outside:
    the counter is per CONNECTION, so a second copy of those two lines gives
    a second token that flaps between two values after any write, and the
    cache behind it then misses on about half of all requests while
    answering correctly the whole time. There WAS a second copy — the
    sidebar's `_STATS_CACHE` had one, word for word, docstring and all, and
    it recomputed eight aggregates over the whole library on eight of every
    twelve reads.

    A token read from the DATA is a different thing and is fine: every
    connection sees the same committed rows, which is why
    `routers/items.library_rev` (three indexed `MAX()`es) is not in here.
    """
    import media_compost

    import re

    # The QUOTED form — the string that gets executed. Prose about the trap
    # is welcome anywhere (and is, in the two comments that warn about it);
    # what may exist in one place is the read.
    reads = re.compile(r"""["']\s*PRAGMA\s+data_version""", re.I)
    root = Path(media_compost.__file__).resolve().parent
    guilty = []
    for path in sorted(root.rglob("*.py")):
        if "_web_dist" in path.parts:
            continue
        if reads.search(path.read_text(encoding="utf-8")):
            guilty.append(str(path.relative_to(root)))
    assert guilty == ["db.py"], guilty
