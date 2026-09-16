"""The write lease: one library, several processes, writers that queue.

`open_library()` never locked anything, WAL keeps single statements honest,
and what was missing is exclusion for anything that is NOT one statement —
two importers interleaving, a script deleting folders a job is mid-way
through writing. The lease is scoped to the unit of the COMMIT (a chunk, a
transaction block, one applied result, one save), waits like `busy_timeout`
does one layer down, and readers take nothing.
"""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest

from media_compost import instance, open_library
from media_compost.instance import (
    LockBusy,
    acquire_write_lease,
    release_write_lease,
    write_lease,
)


@pytest.fixture(autouse=True)
def _clean_lease_state():
    yield
    # Never leak a held lease between tests — the ledgers are process-global.
    instance._write_held.clear()
    instance.release_server_lock()


def _forget_write_held():
    """Simulate another process: the ledger forgets, the descriptors hold on
    (flock conflicts are per open file description)."""
    fds = [h[0] for h in instance._write_held.values()]
    instance._write_held.clear()
    return fds


def test_the_lease_waits_and_then_names_the_holder(tmp_path: Path):
    acquire_write_lease(tmp_path)
    _forget_write_held()
    t0 = time.monotonic()
    with pytest.raises(LockBusy) as exc:
        acquire_write_lease(tmp_path, timeout=0.2)
    assert time.monotonic() - t0 >= 0.2          # it WAITED, not failed fast
    assert "write lease" in str(exc.value)


def test_the_lease_is_reentrant_and_counted(tmp_path: Path):
    """A script's `lib.transaction()` may hold it while the importer it calls
    leases per chunk — the inner release must not take the outer's with it."""
    with write_lease(tmp_path):
        with write_lease(tmp_path):
            assert instance._write_held[str(tmp_path)][1] == 2
        assert instance._write_held[str(tmp_path)][1] == 1
        # still held: a fresh "process" cannot take it
        fds = _forget_write_held()
        with pytest.raises(LockBusy):
            acquire_write_lease(tmp_path, timeout=0.05)
        instance._write_held[str(tmp_path)] = [fds[0], 1]
    assert str(tmp_path) not in instance._write_held


def test_transaction_holds_the_lease_for_the_block(tmp_path: Path):
    with open_library(tmp_path / "lib") as lib:
        data_dir = lib.path
        with lib.transaction():
            assert str(data_dir) in instance._write_held
        assert str(data_dir) not in instance._write_held


def test_an_import_releases_at_its_end(tmp_path: Path, images: Path):
    """The importer leases per CHUNK; when the run is over, nothing is held."""
    with open_library(tmp_path / "lib") as lib:
        got = lib.import_folder(images)
        assert got.status != "error"
        assert len(lib.items) == 2
        assert str(lib.path) not in instance._write_held


def _hold_write_lease(data_dir: str, seconds: float) -> None:
    from media_compost.instance import write_lease as wl

    with wl(Path(data_dir)):
        time.sleep(seconds)


def test_two_processes_take_turns(tmp_path: Path, images: Path):
    """The headline scenario: another PROCESS holds the lease while this one
    imports — the import queues at the lease and both finish intact."""
    data_dir = tmp_path / "lib"
    data_dir.mkdir()
    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_hold_write_lease, args=(str(data_dir), 1.0))
    child.start()
    try:
        # Give the child time to actually take it.
        deadline = time.monotonic() + 5
        while not (data_dir / instance.WRITE_LOCK_NAME).exists():
            assert time.monotonic() < deadline, "child never took the lease"
            time.sleep(0.02)
        time.sleep(0.1)
        with open_library(data_dir) as lib:
            got = lib.import_folder(images)
            assert got.status != "error"
            assert len(lib.items) == 2
    finally:
        child.join(timeout=10)
    assert child.exitcode == 0


def test_readers_take_nothing(tmp_path: Path, images: Path):
    """`mode="r"` (and every read) works while somebody else holds the lease —
    WAL already lets readers through, and no read path touches it."""
    data_dir = tmp_path / "lib"
    with open_library(data_dir) as lib:
        lib.import_folder(images)
    acquire_write_lease(data_dir)
    _forget_write_held()                          # "another process" holds it
    try:
        with open_library(data_dir, mode="r") as lib:
            assert len(lib.items) == 2
    finally:
        instance._write_held.clear()


def test_lease_overhead_is_negligible(tmp_path: Path):
    """The importer takes one lease per 20-file chunk; the perf question is
    whether that cadence costs anything. 200 cycles well under a second is
    the tripwire — the real figure is microseconds each."""
    t0 = time.monotonic()
    for _ in range(200):
        with write_lease(tmp_path):
            pass
    assert time.monotonic() - t0 < 1.0
