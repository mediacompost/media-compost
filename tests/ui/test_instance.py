"""The one-server-per-library guard (media_compost/instance.py)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from media_compost import instance
from media_compost.instance import (
    AnotherServerRunning, acquire_server_lock, release_server_lock,
)


@pytest.fixture(autouse=True)
def _clean_lock_state():
    """Never leak a held lock between tests — the fd list is process-global."""
    yield
    release_server_lock()


def _forget_held():
    """Make this process forget its leases WITHOUT releasing them.

    A lease is idempotent per process now (the app leases training at
    startup and the Trainer it builds later must not conflict with it), so
    "call acquire twice" no longer simulates a second server. Clearing the
    ledger while the descriptors stay open does: the next acquire opens a
    fresh descriptor, and flock conflicts are per open file description —
    exactly what another process would hit.
    """
    fds = list(instance._held.values())
    instance._held.clear()
    return fds


def _held(data_dir: Path | None = None) -> set[str]:
    """Which lock names this process is holding, optionally for one library.

    Four of the tests below are "this does not raise" tests, and a body whose
    only content is a comment saying so is indistinguishable from a test
    somebody forgot to finish. Asserting the LEDGER is what "it worked" means
    here: the descriptor is open and this process owns it.
    """
    return {name for path, name in instance._held
            if data_dir is None or path == str(data_dir)}


def test_second_acquire_is_refused_and_names_the_holder(tmp_path: Path):
    acquire_server_lock(tmp_path)
    _forget_held()
    with pytest.raises(AnotherServerRunning) as exc:
        acquire_server_lock(tmp_path)
    msg = str(exc.value)
    assert str(tmp_path) in msg
    assert f"pid {os.getpid()}" in msg          # the advisory content arrived
    assert "MEDIA_COMPOST_DATA" in msg          # and the way out is named


def test_a_lease_is_idempotent_per_process(tmp_path: Path):
    """The app leases training at startup; the Trainer it builds later
    re-leases the same name and must NOT conflict with its own process."""
    instance.scheduler_lease(tmp_path, instance.TRAINING_LOCK_NAME)
    instance.scheduler_lease(tmp_path, instance.TRAINING_LOCK_NAME)  # no raise
    assert _held(tmp_path) == {instance.TRAINING_LOCK_NAME}


def test_the_two_scheduler_leases_are_independent(tmp_path: Path):
    """An app with training off holds jobs.lock only, and the trainer's CLI
    takes training.lock beside it — that coexistence is the whole reason the
    one server lock became two leases."""
    acquire_server_lock(tmp_path)               # the app: jobs.lock
    _forget_held()                              # now "another process"...
    instance.scheduler_lease(tmp_path, instance.TRAINING_LOCK_NAME)  # ...trains
    with pytest.raises(AnotherServerRunning):
        acquire_server_lock(tmp_path)           # but a second APP still refuses


def test_release_frees_the_library(tmp_path: Path):
    acquire_server_lock(tmp_path)
    release_server_lock()
    assert _held(tmp_path) == set(), "release should empty the ledger"
    acquire_server_lock(tmp_path)               # no raise: the lock is free
    assert instance.JOBS_LOCK_NAME in _held(tmp_path)


def test_two_libraries_do_not_conflict(tmp_path: Path):
    acquire_server_lock(tmp_path / "a")
    acquire_server_lock(tmp_path / "b")          # different library, no raise
    # Both, separately: the lease is per (library, name), so one library
    # holding jobs.lock says nothing about the next one.
    assert _held(tmp_path / "a") == {instance.JOBS_LOCK_NAME}
    assert _held(tmp_path / "b") == {instance.JOBS_LOCK_NAME}


def test_stale_lock_file_alone_does_not_block(tmp_path: Path):
    # A leftover FILE from a dead server must never wedge the library: the
    # flock is the truth, and the kernel released it with the process.
    (tmp_path / instance.JOBS_LOCK_NAME).write_text(json.dumps(
        {"pid": 999999, "command": "media-compost serve", "started": 0}))
    acquire_server_lock(tmp_path)               # no raise
    assert instance.JOBS_LOCK_NAME in _held(tmp_path)


def test_server_startup_refuses_a_locked_library(tmp_path: Path, monkeypatch):
    """End to end: the real app's startup hook aborts when another process
    holds the library (simulated by holding the lock in this process)."""
    from fastapi.testclient import TestClient

    from media_compost.ui.server.app import app

    monkeypatch.setenv("MEDIA_COMPOST_DATA", str(tmp_path))
    acquire_server_lock(tmp_path)
    _forget_held()                              # simulate another process
    assert not app.dependency_overrides  # would disarm the guard (test mode)
    with pytest.raises(AnotherServerRunning):
        with TestClient(app):
            pass


def test_server_startup_takes_and_returns_the_lock(tmp_path: Path,
                                                   monkeypatch):
    from fastapi.testclient import TestClient

    from media_compost.ui.server.app import app

    monkeypatch.setenv("MEDIA_COMPOST_DATA", str(tmp_path))
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ok"] is True
        held = _forget_held()                   # ask as another process would
        try:
            with pytest.raises(AnotherServerRunning):
                acquire_server_lock(tmp_path)   # held while it serves
        finally:
            # Give the ledger its descriptors back so shutdown releases them.
            instance._held[(str(tmp_path), instance.JOBS_LOCK_NAME)] = held[0]
            for i, fd in enumerate(held[1:], 1):
                instance._held[(str(tmp_path), f"held-{i}")] = fd
    acquire_server_lock(tmp_path)               # shutdown released it


# ---- keep-awake assertion ---------------------------------------------------
