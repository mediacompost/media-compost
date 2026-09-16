"""The generated fixtures are BYTE-IDENTICAL on every machine, and this says so.

`media_compost.testing` draws its pictures from a seed, so the PIXELS were
always portable. The encoded FILE was not, and the reason is that a PNG's
pixels travel through deflate, which leaves the compressor free to choose.
Two implementations, given the very same scanlines: Pillow's bundled zlib-ng
1.3.1 writes 2530 bytes at level 9 where CPython's classic zlib 1.2.12 writes
2536 — and at level 0, with nothing compressed at all, they still disagree,
zlib-ng packing stored blocks 33628 bytes at a time against classic zlib's
65531.

That is not a cosmetic difference, which is the reason this file exists. A
fixture's bytes are what `File.sha256` records; `sha256` is what
`train/degrade.file_seed` seeds its draw from, so a different digest picks a
different JPEG quality and renames the artifact that carries it; and
`itemdict.item_to_dict` — the whole of an item's state — is what the history
golden hashes. One zlib difference therefore failed three unrelated goldens
with three unrelated-looking messages, and none of them mentioned zlib. It
failed them on CI's Linux runner, against digests generated on a developer's
Mac, on the same version of Pillow.

So `testing.write_png` writes the file itself, out of the two things deflate
offers that have no latitude in them: the Up filter, and one fixed-Huffman
block whose only matches are runs of the byte just emitted. No match search,
no table building, no block splitting — nothing to agree with anybody about,
and 9,697 bytes rather than the 360,336 that storing the scanlines raw
would cost. This file pins the digests, inflates the stream with somebody else's
decoder to check it says what the picture says, and holds the module to
calling no compressor: an edit that reaches for one reports itself HERE, by
name, instead of surfacing as a drawn JPEG quality nobody can explain.

If one of these digests moves, the fixture's own bytes moved: either the
drawing changed (then the goldens genuinely need regenerating) or the writer
did (then find out why before regenerating anything).
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image

from media_compost import testing
from media_compost.testing import (make_dup_folder, make_image,
                                   make_jpeg_with_exif)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _idat(path: Path) -> bytes:
    """The PNG's compressed stream, chunks joined as a reader would."""
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    out, i = b"", 8
    while i < len(data):
        (length,) = struct.unpack(">I", data[i:i + 4])
        if data[i + 4:i + 8] == b"IDAT":
            out += data[i + 8:i + 8 + length]
        i += 12 + length
    return out


def test_the_file_says_what_the_picture_says(tmp_path):
    """Our stream, inflated by somebody else's decoder, is the drawing.

    The digests below say "these bytes"; this says the bytes are RIGHT — a
    hand-written deflate that quietly dropped a byte would otherwise be pinned
    as carefully as a correct one. Pillow decodes the file (its inflate, its
    un-filtering) and `zlib` inflates the stream on its own, and the Up filter
    is undone here by hand, so a wrong length code, a mis-ordered Huffman bit
    or an off-by-one row all land on this assertion.
    """
    path = make_image(tmp_path / "a.png", seed=1)
    with Image.open(path) as im:
        assert im.mode == "RGB" and im.size == (400, 300)
        pixels = im.tobytes()

    stride = 400 * 3
    raw = zlib.decompress(_idat(path))
    rebuilt, prior = bytearray(), bytes(stride)
    for y in range(300):
        line = raw[y * (stride + 1):(y + 1) * (stride + 1)]
        assert line[0] == 2, f"row {y} is filter {line[0]}, not Up"
        row = bytes((line[1 + i] + prior[i]) & 0xFF for i in range(stride))
        rebuilt += row
        prior = row
    assert bytes(rebuilt) == pixels


def test_the_fixtures_call_no_compressor():
    """The property the digests rest on, said where an edit would break it.

    Every portable byte here comes from NOT asking a compressor anything, so
    the failure to catch is somebody reaching for one — `compress_level=9` was
    what stood here, and it reads like the careful choice rather than the bug.
    `zlib` stays imported for `crc32` and `adler32`, which are answers rather
    than choices.
    """
    # Comment lines are dropped first: the module explains at length what
    # `compress_level=9` used to do there, and a test that cannot tell the
    # warning from the mistake would force the warning out.
    src = "\n".join(
        line for line in Path(testing.__file__).read_text(encoding="utf-8")
                             .splitlines()
        if not line.lstrip().startswith("#"))
    for reached in ("zlib.compress", "compressobj", "compress_level",
                    "compresslevel"):
        assert f"{reached}(" not in src and f"{reached}=" not in src, (
            f"`{reached}` is back in testing.py. A fixture's bytes would then "
            f"be whatever zlib the wheel was built against chose, and three "
            f"goldens would move on the next machine that ran them.")


@pytest.mark.parametrize("digest,build", [
    ("a36d16e8c91e316c80894da680557525b8f93d86eb85d1df58e3e4dc8166c93e",
     lambda d: make_image(d / "a.png", seed=1)),
    ("7bd7789fb2cb6523cd38b410e9291a02d788cede10df62f85e23aff98315a97c",
     lambda d: make_image(d / "b.png", seed=99, size=(500, 400))),
    ("410774e25dd0621acf966630a0a8925bc2c21bfdf92f8f4b5c9ac0764da89b03",
     lambda d: make_jpeg_with_exif(d / "c.jpg", seed=1)),
])
def test_a_generated_fixture_has_the_bytes_it_had(tmp_path, digest, build):
    assert _sha(build(tmp_path)) == digest, (
        "a generated fixture's bytes moved. Every golden built on it — the "
        "training manifests, the degrade artifacts, the history state hash — "
        "is about to fail for a reason that will not look like this one. "
        "Check whether the DRAWING changed or the WRITER did before "
        "regenerating anything.")


def test_the_duplicate_folder_is_byte_stable_too(tmp_path):
    """`make_dup_folder` writes one file the helpers above do not — the
    downscaled near-duplicate, which goes through its own write and is the one
    that would keep an encoder's default if the writer were used in only the
    obvious place."""
    src = make_dup_folder(tmp_path / "dup")
    assert _sha(src / "a_small.png") == \
        "c7ba171f8daffa1370b2c7c3cc83f384de165491b338a3a2dbeb2cf969666a56"
    # The exact copy is a copy, so it must agree with its source byte for byte
    # — that relationship is what three suites read as "a duplicate".
    assert _sha(src / "a_copy.png") == _sha(src / "a.png")
