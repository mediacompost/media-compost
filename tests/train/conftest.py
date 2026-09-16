"""Fixtures for the trainer's own suite.

It reads a library through the public API and nothing else — which is the whole
reason this package can live apart from the app — so its fixtures build one the
same way anybody else would.
"""

from __future__ import annotations

import sys
from pathlib import Path

# MEDIA_COMPOST_SYNC_SWEEPS is set once for every suite in tests/conftest.py.

import pytest

from media_compost.testing import (  # noqa: F401 - re-exported for the suite
    make_dup_folder,
    make_image,
    make_jpeg_with_exif,
)
from media_compost.train.paths import TRAIN_SCRIPTS


def train_module():
    """`train/scripts/train.py`, imported by file — with its own directory on
    `sys.path`, because that is the condition the trainer runs under.

    `JobIO.write_state` resolves `atomicio` LAZILY, and deliberately: the
    module is also loaded by path by the tests' fake trainer, where that path
    entry is not set up. Loaded the naive way, then, a test that writes a
    state file raises `ModuleNotFoundError: No module named 'atomicio'` — and
    PASSES whenever some earlier test in the same worker happened to leave
    that module in `sys.modules`, which `loop_module` below does. That is the
    exact shape of a flake: under xdist it depends on which tests share a
    worker and in what order, which is why
    `test_the_phase_carries_a_progress_note` failed in a full run and passed
    in another with nothing about it having changed.

    So the sibling is imported HERE, where the path entry exists; it stays in
    `sys.modules` for the rest of the session, which is the state the trainer
    itself is always in. One loader rather than one per call site, for the
    reason `loop_module` gives: a copy in each is a second chance to put a
    different directory on the path.
    """
    import importlib
    import importlib.util as _u

    directory = str(TRAIN_SCRIPTS)
    added = directory not in sys.path
    if added:
        sys.path.insert(0, directory)
    try:
        importlib.import_module("atomicio")
        spec = _u.spec_from_file_location("train_scripts_train",
                                          TRAIN_SCRIPTS / "train.py")
        mod = _u.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if added:
            sys.path.remove(directory)


def loop_module():
    """`train/scripts/loop.py`, imported by file.

    It imports its siblings by BARE NAME (`import compose`), the way they
    resolve when the trainer runs them as scripts, so the directory has to be
    on the path for the duration.

    Here rather than in a test file because two of them load it —
    `test_training.py` for the manager and sampling paths, `test_engine_math.
    py` for the latent cache — and a loader copied into both is two chances
    to put a different directory on `sys.path`.
    """
    import importlib

    directory = str(TRAIN_SCRIPTS)
    added = directory not in sys.path
    if added:
        sys.path.insert(0, directory)
    try:
        return importlib.import_module("loop")
    finally:
        if added:
            sys.path.remove(directory)


@pytest.fixture
def images(tmp_path: Path) -> Path:
    """A directory of source images with known duplicate relationships.

    ``make_dup_folder`` is the one definition of that folder, and it has to
    be: several tests here assert the ITEM COUNT it imports to, which is a
    statement about what the deduper merged. This fixture began as a verbatim
    copy of the library's, and an earlier copy that re-seeded the
    near-duplicate rather than RESIZING the original quietly imported to
    three items instead of two.
    """
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
