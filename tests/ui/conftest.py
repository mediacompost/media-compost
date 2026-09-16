"""Shared fixtures for the app's suite: a scratch library and known pictures.

The suites are subpackages of ``tests`` (``tests.ui`` here), so their module
names cannot collide; the helpers they share live in ``media_compost.testing``
rather than in any suite's conftest, and the setup common to all three
(synchronous sidecars) lives in ``tests/conftest.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from media_compost.db import Database
from media_compost.storage import ItemStore
from media_compost.testing import make_dup_folder
from media_compost.ui.config import UiConfig


#: Tests that want a REAL plugin worker say so: `@pytest.mark.real_worker`.
#: Everything else gets a host that refuses to spawn one (see below).
_REAL_WORKER = "real_worker"


@pytest.fixture(autouse=True)
def _no_model_workers(request, monkeypatch):
    """NO TEST SPAWNS A MODEL WORKER UNLESS IT SAYS SO.

    Enqueuing an AI job is a handful of lines and dozens of tests do it for
    the bookkeeping alone — the `skipped` count, the job row, the queue's
    order. The job is REAL, though: the queue's worker thread picks it up and
    the model host spawns a plugin worker, a fresh interpreter that imports
    the package before it can even fail to load the weights (which it always
    does here, the cache being pointed at nothing — see `tests/conftest.py`).

    Measured over the default run: bursts of SEVENTEEN of those importing at
    once, twelve cores for seconds at a time, from tests that never look at
    the result. The load was going to fail either way, so the only thing
    those spawns bought was the machine.

    What is lost is nothing a test was asserting: a job whose model cannot
    load still fails, still writes its error, still leaves the queue as it
    found it. What still spawns for real is the handful of tests about the
    host and the worker wire, which carry the marker.
    """
    if request.node.get_closest_marker(_REAL_WORKER):
        return
    from media_compost.ui.plugins import host as host_mod

    def refuse(self, plugin, load_key, ctx):
        raise RuntimeError(
            f"model {load_key!r}: no model worker in the test environment "
            f"(mark the test @pytest.mark.{_REAL_WORKER} to spawn one)")

    monkeypatch.setattr(host_mod.ModelHost, "_spawn", refuse)


@pytest.fixture
def lib(tmp_path: Path):
    """A fresh library (config + db + object store) in a temp dir.

    A ``UiConfig``, not core's ``Config``: several of these tests hand the
    config on to the server's ``Library``, which reads the auth fields only
    the app's config carries.
    """
    cfg = UiConfig(data_dir=tmp_path / "data")
    db = Database(cfg)
    store = ItemStore(cfg)
    return cfg, db, store


@pytest.fixture
def images(tmp_path: Path):
    """A directory of source images with known duplicate relationships."""
    return make_dup_folder(tmp_path / "src")


@pytest.fixture(autouse=True)
def _release_leases():
    """Scheduler leases are per-process and idempotent, so tests that build a
    Trainer or start the app accumulate held descriptors; give them back after
    each test so the suite cannot creep up on the fd limit."""
    yield
    from media_compost import instance

    instance.release_server_lock()
    instance._write_held.clear()


@pytest.fixture(autouse=True)
def _default_florence_checkpoint():
    """Which Florence checkpoint is active is a PROCESS global set from a
    LIBRARY setting, and the suite runs many libraries in one process.

    `florence._ACTIVE` decides what `registry.models()` lists and what
    `model_label()` answers, and `settings.apply_runtime_prefs` writes it
    from whichever library is being served. In production that is exact —
    one process serves one library — but under xdist a test that stores a
    non-default checkpoint (`test_auth`'s "florence2_large") leaves it set
    for every later test in that worker, which is why
    `test_tag_job_adds_pending_tags_in_system_group` failed intermittently
    on the NAME of its pending group and passed on its own. Reset before
    each test, so a test's process state matches its own library.
    """
    from media_compost.ui.plugins.impl import florence

    florence.set_active("florence2_base")
    yield
    florence.set_active("florence2_base")
