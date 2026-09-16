"""A transient "database is locked" is retried on a fresh snapshot, not lost.

The collision: pysqlite begins transactions DEFERRED, so a unit of work that
READ and then meets another process's commit at its first write is refused
immediately — `busy_timeout` deliberately does not apply, because the
transaction's snapshot can never become current. A crawler importing beside
an open app saw exactly this as per-file "database is locked" errors. The
cure is always the same: end the transaction, wait a moment, run the work
again — and both write choke points do that now (`Library._do` for the
single-call API writes, the importer's per-file savepoint for imports).
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from media_compost import open_library
from media_compost.db import is_locked_error
from media_compost.importer import Importer
from tests.core.conftest import make_image


def _locked() -> OperationalError:
    return OperationalError("INSERT …", {},
                            sqlite3.OperationalError("database is locked"))


def test_the_predicate_knows_the_two_spellings_and_nothing_else():
    assert is_locked_error(_locked())
    assert is_locked_error(OperationalError(
        "x", {}, sqlite3.OperationalError("database is busy")))
    assert not is_locked_error(OperationalError(
        "x", {}, sqlite3.OperationalError("no such table: items")))
    assert not is_locked_error(ValueError("database is locked"))


def test_a_single_call_write_retries_past_a_transient_lock(tmp_path: Path):
    """`item.tags.add(...)` beside a busy neighbour succeeds instead of
    raising — the failed attempts rolled back and re-ran on fresh
    snapshots."""
    with open_library(tmp_path / "data") as lib:
        got = lib.import_bytes(make_image(tmp_path / "a.png",
                                          seed=1).read_bytes(), "a.png")
        calls = {"n": 0}

        def flaky(ctx, item_id, name):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _locked()
            return "landed"

        # Drive _do directly with a flaky op standing in for a real one.
        assert lib._do(flaky, got.item.id, "patient") == "landed"
        assert calls["n"] == 3

        def hopeless(ctx):
            raise _locked()

        with pytest.raises(Exception, match="database is locked"):
            lib._do(hopeless)

        def broken(ctx):
            calls["n"] += 1
            raise OperationalError("x", {},
                                   sqlite3.OperationalError("no such table"))

        calls["n"] = 0
        with pytest.raises(Exception, match="no such table"):
            lib._do(broken)
        assert calls["n"] == 1, "a non-transient error is not retried"


def test_the_importer_retries_a_file_that_met_a_lock(tmp_path: Path,
                                                     monkeypatch):
    """The per-file path: the savepoint rolls the file back, the chunk's
    stale-snapshot transaction ENDS, and the file runs again — so a crawl
    beside an open app keeps the file instead of printing an error for it."""
    data = make_image(tmp_path / "b.png", seed=2).read_bytes()
    real = Importer._ingest_image
    calls = {"n": 0}

    def flaky(self, path, group, source_name="__use_path__"):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _locked()
        return real(self, path, group, source_name=source_name)

    monkeypatch.setattr(Importer, "_ingest_image", flaky)
    with open_library(tmp_path / "data") as lib:
        got = lib.import_bytes(data, "b.png")
        assert got.status == "imported", got.error
        assert not got.stats.errors
    assert calls["n"] == 3

    # Past the retry budget the error is RECORDED, as before — the run
    # carries on rather than raising out of the loop.
    calls["n"] = -100
    with open_library(tmp_path / "data2") as lib:
        got = lib.import_bytes(data, "b.png")
        assert got.status == "error"
        assert "database is locked" in got.error
