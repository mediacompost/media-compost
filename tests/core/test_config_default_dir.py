"""Where a bare run looks for its library.

`./_data` — the repository's convention for a directory a program writes
rather than a person — and nothing else. It used to be `./data`, and for one
commit it was "either, depending on which is there", which is what these tests
pin against coming back: which library a bare run opens must not depend on
what happens to be sitting in the working directory. A library made by an
older build is opened by NAMING it (`--data-dir`, `MEDIA_COMPOST_DATA`) or by
renaming its folder.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from media_compost.config import Config


@pytest.fixture()
def cwd(tmp_path, monkeypatch):
    """A clean working directory with no `MEDIA_COMPOST_DATA` over it."""
    monkeypatch.delenv("MEDIA_COMPOST_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_bare_run_uses_underscore_data(cwd: Path):
    assert Config().data_dir == (cwd / "_data").resolve()


def test_a_data_folder_beside_it_changes_NOTHING(cwd: Path):
    """Not even one holding a real library. The answer is unconditional, so
    there is no state of the working directory that moves it — which is the
    whole reason the adoption branch was removed."""
    (cwd / "data").mkdir()
    (cwd / "data" / "media.db").write_bytes(b"")
    assert Config().data_dir == (cwd / "_data").resolve()


def test_the_environment_wins(cwd: Path, monkeypatch):
    """`MEDIA_COMPOST_DATA` is what the Docker image, the CLI and every test
    set, and it is also the answer for a library made before the rename."""
    monkeypatch.setenv("MEDIA_COMPOST_DATA", str(cwd / "data"))
    assert Config().data_dir == (cwd / "data").resolve()


def test_an_explicit_path_is_untouched(cwd: Path):
    """The default is a DEFAULT — a caller naming a directory gets it."""
    assert Config(data_dir=cwd / "named").data_dir == cwd / "named"
    assert os.environ.get("MEDIA_COMPOST_DATA") is None
