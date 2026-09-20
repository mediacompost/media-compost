"""An Evaluate picture is on disk complete or not at all.

The reported symptom: a thumbnail in the Evaluate tab showing the top of
the picture and white below. The run's folder is listed by the server WHILE
the generation is going (`EvalManager.readable` takes every `.png` in it)
and the app asks for each name the moment it appears — so a picture written
in place was offered to the browser mid-write.

Both halves of the serving path then make a truncated file worse than an
error. Measured here: PIL refuses it, which is what sends `_thumb_of` down
its "no thumbnail — serve the original" branch, and the browser decodes the
partial PNG happily at full size with pixels only as far as the bytes go.
"""

from __future__ import annotations

import importlib.util
import io
import threading
from pathlib import Path

import pytest
from PIL import Image

from media_compost.train.paths import TRAIN_SCRIPTS
from media_compost.train.web.routes import _thumb_of


def _generate():
    """`generate.py`, imported by file — with its own directory on
    `sys.path`, which is the condition it runs under (it is spawned as a
    script, so that directory is `sys.path[0]`) and what lets it reach
    `atomicio` for the rename. The sibling is imported HERE, where the path
    entry exists, and stays in `sys.modules` after — the same arrangement,
    and the same reason, as `conftest.train_module`."""
    import importlib
    import sys

    directory = str(TRAIN_SCRIPTS)
    added = directory not in sys.path
    if added:
        sys.path.insert(0, directory)
    try:
        importlib.import_module("atomicio")
        p = TRAIN_SCRIPTS / "generate.py"
        spec = importlib.util.spec_from_file_location("generate_writes", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if added:
            sys.path.remove(directory)


def _picture(px: int = 512) -> Image.Image:
    """Noisy on purpose: a flat colour compresses to a handful of kilobytes
    and is written in one go, which is precisely the case that never showed
    the bug."""
    import random

    rng = random.Random(7)
    img = Image.new("RGB", (px, px))
    img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                 for _ in range(px * px)])
    return img


def _listed(d: Path) -> list[str]:
    """What `EvalManager.readable` would report for this folder."""
    return sorted(f.name for f in d.iterdir() if f.suffix == ".png")


def test_a_reader_racing_the_writer_never_sees_a_half_written_picture(
        tmp_path):
    """The rule, tested the way it fails: a reader listing and opening the
    folder as fast as it can, while pictures are written into it."""
    gen = _generate()
    img = _picture()
    seen: list[tuple[str, int]] = []
    broken: list[str] = []
    stop = False

    def reader():
        while not stop:
            for name in _listed(tmp_path):
                data = (tmp_path / name).read_bytes()
                try:
                    with Image.open(io.BytesIO(data)) as im:
                        im.load()
                except OSError:
                    broken.append(name)
                    continue
                seen.append((name, len(data)))

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(12):
            gen._save_image(img, tmp_path / f"p{i:03d}.png")
    finally:
        stop = True
        t.join()

    assert broken == [], "a listed picture could not be decoded"
    assert seen, "the reader never caught a picture at all"
    # And every read was of the WHOLE file, not a prefix of one.
    whole = {f.name: f.stat().st_size for f in tmp_path.glob("p*.png")}
    assert all(size == whole[name] for name, size in seen)


def test_the_temp_file_is_invisible_to_the_listing(tmp_path):
    """What makes the rename enough: while a picture is being written there
    is a file in the folder, and neither the listing nor the thumbnail glob
    may count it."""
    gen = _generate()
    gen._save_image(_picture(64), tmp_path / "p000.png")
    # The name the writer uses, as it exists mid-write.
    (tmp_path / ".p001.png.tmp").write_bytes(b"\x89PNG half of one")
    assert _listed(tmp_path) == ["p000.png"]
    assert list(tmp_path.glob(".thumb-*-p001.webp")) == []


def test_a_truncated_picture_is_why_this_matters(tmp_path):
    """The other end of the bug, pinned so the reasoning stays checkable:
    PIL refuses a half-written PNG, which is exactly what makes the
    thumbnailer hand the raw bytes to the browser instead."""
    whole = tmp_path / "full.png"
    _picture(512).save(whole)
    half = tmp_path / "half.png"
    half.write_bytes(whole.read_bytes()[:len(whole.read_bytes()) // 2])

    with pytest.raises(OSError):
        with Image.open(half) as im:
            im.load()
    # …and that is the branch the route takes: no thumbnail, serve the file.
    assert _thumb_of(half, 320) is None
    assert _thumb_of(whole, 320) is not None
