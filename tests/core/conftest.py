"""Shared pytest fixtures: a scratch library and deterministic test images."""

from __future__ import annotations

from pathlib import Path

# MEDIA_COMPOST_SYNC_SWEEPS is set once for every suite in tests/conftest.py.

#: The trainer's standalone scripts. They are not importable — they run
#: in a venv of their own and may never import `media_compost` — so the
#: tests that exercise their pure halves load them by FILE PATH, and this
#: is the one place that knows where the path is.
TRAINING_SCRIPTS = (Path(__file__).resolve().parents[2]
                    / "media_compost" / "train" / "scripts")

import pytest

from media_compost.config import Config
from media_compost.db import Database
from media_compost.storage import ItemStore
from media_compost.testing import (  # noqa: F401 - re-exported for the suite
    make_dup_folder,
    make_image,
    make_jpeg_with_exif,
)


@pytest.fixture
def lib(tmp_path: Path):
    """A fresh library (config + db + object store) in a temp dir."""
    cfg = Config(data_dir=tmp_path / "data")
    db = Database(cfg)
    store = ItemStore(cfg)
    return cfg, db, store


@pytest.fixture
def images(tmp_path: Path):
    """A directory of source images with known duplicate relationships."""
    return make_dup_folder(tmp_path / "src")
