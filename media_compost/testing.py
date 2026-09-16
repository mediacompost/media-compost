"""Deterministic test pictures, and the small helpers three suites share.

Lifted out of the library's own `tests/conftest.py` because three suites need
them now — the library's, the app's and the trainer's — and a fixture copied
three ways is three fixtures that drift. (The trainer's suite already proved
the point the hard way: its verbatim copy of the duplicates folder re-seeded
one image, which made a near-duplicate into a different picture and the import
count silently wrong.) It is also genuinely useful to anyone writing tests
against a library of their own, which is why it ships rather than sitting in a
test directory.

Every picture is CONTENT-RICH and seeded: a flat colour has a degenerate
perceptual hash (every solid image hashes alike), so a fixture built from one
would make the deduper look broken in tests and fine in life.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

from PIL import ExifTags, Image, ImageDraw

__all__ = ["make_image", "make_jpeg_with_exif", "make_dup_folder", "write_png",
           "q_tag", "q_meta", "search_items"]

# THE FIXTURE PNGs ARE WRITTEN HERE, BYTE FOR BYTE, AND NOT BY AN ENCODER.
#
# The pixels below are computed from a seed and are identical everywhere. The
# FILE was not, because a PNG's pixels travel through deflate, and deflate
# leaves the compressor free to choose — so the same picture came out with a
# different digest depending on which zlib the Pillow wheel was built against.
# That reaches much further than it looks: the bytes are what `File.sha256`
# records, which is what `train/degrade.file_seed` draws its variant
# parameters from, and what `itemdict.item_to_dict` — and so the history
# golden's state hash — is built out of. One zlib difference moved three
# unrelated goldens with three unrelated-looking messages, and none of them
# mentioned zlib, and it moved them on a CI runner against digests generated
# on a laptop running the same version of Pillow.
#
# This file used to answer that with `compress_level=9`, on a measurement that
# the two implementations then in play agreed at maximum effort. They do not.
# Measured on ONE machine, feeding both the very same filtered scanlines:
# Pillow's bundled zlib-ng 1.3.1 writes 2530 bytes at level 9 where CPython's
# classic zlib 1.2.12 writes 2536 — and at level 0, with nothing compressed at
# all, they STILL differ, zlib-ng packing stored blocks 33628 bytes at a time
# against classic zlib's 65531. There is no setting to pick: what a deflate
# stream looks like is the compressor's to decide, and a wheel's compressor is
# not ours.
#
# So the stream is built here, out of the two choices deflate offers that have
# no latitude in them:
#
#   * the UP filter on every scanline, which turns a row into its difference
#     from the row above — and these pictures are flat backgrounds with a few
#     shapes on them, so most of that is zeros;
#   * one fixed-Huffman block (the code table is IN the format, not in the
#     file) whose only matches are runs of the byte just emitted, which is the
#     whole of what those zeros need.
#
# No match search, no table building, no block splitting: nothing an
# implementation could do differently, and nothing that has to agree with
# anybody. `zlib` is still imported for `crc32`, `adler32` and — in the tests
# — `decompress`: those are answers, not choices.
#
# It is also SMALL, which is why it is this rather than the stored blocks that
# stood here for an afternoon: 9,697 bytes for the 400x300 fixture against
# 360,336 stored, and against 2,530 that Pillow's level 9 would have spent a
# real compressor on. A fixture that costs four times the best possible and
# nothing in portability is a good trade; one that costs 140 times it — and
# 11% of the core suite's wall clock — was the same trade at a silly price.
#
# `tests/core/test_fixture_bytes.py` pins the digests, decodes the file back
# to the pixels that went in, and holds this module to calling no compressor.


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


#: (code, first length it covers, extra bits) for deflate's length alphabet,
#: longest first — `_match` takes the first entry that fits.
_LENGTHS = [(285, 258, 0), (284, 227, 5), (283, 195, 5), (282, 163, 5),
            (281, 131, 5), (280, 115, 4), (279, 99, 4), (278, 83, 4),
            (277, 67, 4), (276, 59, 3), (275, 51, 3), (274, 43, 3),
            (273, 35, 3), (272, 31, 2), (271, 27, 2), (270, 23, 2),
            (269, 19, 2), (268, 17, 1), (267, 15, 1), (266, 13, 1),
            (265, 11, 1), (264, 10, 0), (263, 9, 0), (262, 8, 0), (261, 7, 0),
            (260, 6, 0), (259, 5, 0), (258, 4, 0), (257, 3, 0)]


class _Bits:
    """A deflate bit stream.

    Extra bits go in LSB first and Huffman codes MSB first — that asymmetry is
    the format's, not a choice made here, so every code in the tables below is
    stored already REVERSED and everything can then be shifted into one
    accumulator. Bits leave in whole bytes, which is what keeps this loop off
    the suite's wall clock: per-bit appends cost more than the drawing did.
    """

    def __init__(self) -> None:
        self._out = bytearray()
        self._acc = 0
        self._n = 0

    def put(self, value: int, width: int) -> None:
        self._acc |= value << self._n
        self._n += width
        if self._n >= 32:
            whole = self._n >> 3        # the accumulator keeps the remainder,
            spill = whole * 8           # so only the whole bytes go out
            self._out += (self._acc & ((1 << spill) - 1)).to_bytes(
                whole, "little")
            self._acc >>= spill
            self._n -= spill

    def done(self) -> bytes:
        out = self._out + self._acc.to_bytes((self._n + 7) // 8, "little")
        self._out, self._acc, self._n = bytearray(), 0, 0
        return bytes(out)


def _reversed(value: int, width: int) -> int:
    out = 0
    for i in range(width):
        out = (out << 1) | ((value >> i) & 1)
    return out


#: Every byte's fixed-table code, reversed and paired with its width: 0-143
#: are eight bits from 0x30, 144-255 nine from 0x190.
_LITERAL = [(_reversed(0x30 + b, 8), 8) if b < 144
            else (_reversed(0x190 + b - 144, 9), 9) for b in range(256)]

#: The same for a length: the code, then the extra bits it needs, then how
#: many lengths that code covers. `_LENGTHS` above is longest-first, so the
#: first entry that fits is the one to write.
_LENGTH_CODE = {
    code: (_reversed(code - 256, 7), 7) if code < 280
    else (_reversed(0xC0 + code - 280, 8), 8) for code, _, _ in _LENGTHS}

#: Distance 1 — five bits of zero — and the end-of-block symbol, seven.
_DISTANCE_1 = (0, 5)
_END_OF_BLOCK = (0, 7)


def _deflate_runs(raw: bytes) -> bytes:
    """`raw` as one fixed-Huffman block whose only matches are byte runs.

    0x78 0x01 is the zlib header for a 32 kB window (the two bytes read as a
    multiple of 31, which is the format's own check); the trailer is adler32.
    The runs are found by numpy — a base dependency, and the difference
    between a fixture that costs a millisecond and one that costs fifty.
    """
    import numpy as np

    bits = _Bits()
    bits.put(1, 1)              # final block
    bits.put(1, 2)              # …with the fixed code table

    data = np.frombuffer(raw, dtype=np.uint8)
    starts = np.concatenate(([0], np.flatnonzero(data[1:] != data[:-1]) + 1))
    lengths = np.diff(np.append(starts, data.size))
    literal = _LITERAL
    for byte, run in zip(data[starts].tolist(), lengths.tolist()):
        lit, lit_width = literal[byte]
        bits.put(lit, lit_width)
        rest = run - 1          # the rest of a run is a copy of that byte
        while rest >= 3:
            take = min(rest, 258)
            if 0 < rest - take < 3:
                take -= 3       # never leave a tail too short to be a match
            for length_code, base, extra in _LENGTHS:
                if take >= base:
                    code, width = _LENGTH_CODE[length_code]
                    bits.put(code, width)
                    if extra:
                        bits.put(take - base, extra)
                    bits.put(*_DISTANCE_1)
                    break
            rest -= take
        for _ in range(rest):   # a tail of one or two is two literals
            bits.put(lit, lit_width)
    bits.put(*_END_OF_BLOCK)
    return (b"\x78\x01" + bits.done()
            + struct.pack(">I", zlib.adler32(raw) & 0xFFFFFFFF))


def write_png(path: Path, img: Image.Image) -> Path:
    """Write `img` as a PNG that is the same bytes on every machine.

    RGB, eight bits, no interlacing, Up filter — the shapes every reader is
    required to understand, written the one way this module writes them. The
    encoded bytes are remembered per picture: a suite asks for the same half
    dozen fixtures hundreds of times, and they cannot come out differently.
    """
    import hashlib

    import numpy as np

    rgb = img if img.mode == "RGB" else img.convert("RGB")
    w, h = rgb.size
    px = rgb.tobytes()
    key = (w, h, hashlib.blake2b(px, digest_size=16).digest())
    blob = _WRITTEN.get(key)
    if blob is None:
        rows = np.frombuffer(px, dtype=np.uint8).reshape(h, w * 3)
        out = np.empty((h, w * 3 + 1), dtype=np.uint8)
        out[:, 0] = 2                                   # the Up filter
        out[0, 1:] = rows[0]
        out[1:, 1:] = rows[1:] - rows[:-1]              # uint8 wraps, as PNG says
        blob = (b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + _chunk(b"IDAT", _deflate_runs(out.tobytes()))
                + _chunk(b"IEND", b""))
        _WRITTEN[key] = blob
    Path(path).write_bytes(blob)
    return Path(path)


#: Encoded fixtures, keyed by their pixels. Bounded by how many distinct
#: pictures a test run draws, which is a handful.
_WRITTEN: dict[tuple[int, int, bytes], bytes] = {}


def make_image(path: Path, seed: int, size: tuple[int, int] = (400, 300)) -> Path:
    """Create a deterministic, content-rich image so pHashes are distinct."""
    w, h = size
    img = Image.new("RGB", (w, h), (10 + seed * 7 % 200, 20, 30))
    d = ImageDraw.Draw(img)
    for i in range(6):
        x = (seed * 37 + i * 53) % w
        y = (seed * 61 + i * 29) % h
        r = 20 + (seed * 13 + i * 17) % 60
        color = ((seed * 41 + i * 90) % 256, (seed * 97) % 256, (i * 60) % 256)
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)
    # A gradient bar to give the pHash structure to lock onto.
    for x in range(w):
        v = int(255 * (0.5 + 0.5 * math.sin(x / 20 + seed)))
        d.line([(x, 0), (x, 12)], fill=(v, v, v))
    write_png(path, img)
    return path


def make_jpeg_with_exif(path: Path, seed: int, size: tuple[int, int] = (640, 480)) -> Path:
    """A content-rich JPEG (distinct pHash per seed) carrying camera EXIF across
    the base + Exif sub-IFDs, for metadata-index tests."""
    w, h = size
    img = Image.new("RGB", (w, h), (10 + seed * 7 % 200, 20, 30))
    d = ImageDraw.Draw(img)
    for i in range(6):
        x = (seed * 37 + i * 53) % w
        y = (seed * 61 + i * 29) % h
        r = 30 + (seed * 13 + i * 17) % 90
        d.ellipse([x - r, y - r, x + r, y + r],
                  fill=((seed * 41 + i * 90) % 256, (seed * 97) % 256, (i * 60) % 256))
    for x in range(w):
        v = int(255 * (0.5 + 0.5 * math.sin(x / 20 + seed)))
        d.line([(x, 0), (x, 16)], fill=(v, v, v))
    exif = img.getexif()
    exif[271] = "TestMake"
    exif[272] = f"Model{seed}"
    exif[306] = "2026:07:11 09:44:03"
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    sub[36867] = "2020:01:15 14:30:00"
    sub[34855] = 400
    sub[33437] = 2.8
    img.save(path, "JPEG", exif=exif)
    return path


def make_dup_folder(src: Path) -> Path:
    """A directory of source images with known duplicate relationships:
    an original, a byte-identical copy, a downscaled near-duplicate, and one
    unrelated picture. Importing it yields exactly two items — which is what
    every fixture built on it asserts, so the relationships are the contract:
    re-seeding any file here changes what "a duplicate" means in three suites.
    """
    src.mkdir(parents=True, exist_ok=True)
    a = make_image(src / "a.png", seed=1, size=(400, 300))
    # Exact byte-for-byte duplicate of a.
    (src / "a_copy.png").write_bytes(a.read_bytes())
    # Same content as a, smaller resolution -> near-duplicate (alternative).
    with Image.open(a) as im:
        write_png(src / "a_small.png", im.resize((200, 150)))
    # A visually distinct image -> new item.
    make_image(src / "b.png", seed=99, size=(500, 400))
    return src


# ---- structured-search helpers (POST /api/items/query) ----------------------
# Pure dict-builders for the wire shape `query.py` defines; `search_items`
# takes any client with `.post` (the app's TestClient in practice). They live
# here rather than in a server-side suite so a test of core behaviour that is
# DRIVEN through the API can still share one spelling of the tree.


def q_tag(name: str, have: bool = True, sign: str = "pos") -> dict:
    return {"type": "tag", "name": name, "have": have, "sign": sign}


def q_meta(name: str, mtype: str, op: str, value) -> dict:
    return {"type": "meta", "name": name, "mtype": mtype, "op": op, "value": value}


def search_items(client, *children, **scope) -> dict:
    """POST a structured AND query built from `children` and return the page."""
    body = {
        "query": {"type": "group", "op": "and", "neg": False, "children": list(children)}
        if children else None,
        **scope,
    }
    r = client.post("/api/items/query", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def commit_offenders(paths) -> list[str]:
    """Where a module calls `.commit()`, `.rollback()` or `.close()`.

    The scan behind "ops must NEVER commit" — the one rule the whole layering
    rests on, since whoever owns the session owns its cadence. It lived in two
    suites at once (core's `test_ops_context.py` over `media_compost/ops/`,
    the app's `test_ops_ratchet.py` over `media_compost.ui/ops/` and
    `editor.py`), with the same regex, the same `noqa` escape and the same
    message written out a copy apart — which is the exact duplication `ops/`
    was extracted to stop, happening to the guard rather than to the code.

    Here rather than in a conftest because the suites are separate packages
    and the core one runs on a base-only install; a genuine file-handle
    `.close()` may carry a `# noqa`.
    """
    import re

    pattern = re.compile(r"\.(commit|rollback|close)\(\)")
    out: list[str] = []
    for path in paths:
        for i, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and "noqa" not in line:
                out.append(f"{path.name}:{i}: {line.strip()}")
    return out


#: The sentence both callers print, so the two cannot drift into explaining
#: the same rule differently.
COMMIT_RULE = (
    "ops must never commit, roll back or close — the session's owner does "
    "(a genuine file-handle .close() may carry a noqa):\n")
