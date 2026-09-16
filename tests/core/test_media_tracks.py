"""Per-track names out of an MP4's ``trak/udta`` boxes.

ffprobe reports a stream's title only where the container carries one as a
stream tag; QuickTime-style files keep it in the track's own ``udta`` box, which
the mov demuxer does not map. The parser reads those boxes directly, so it is
tested against a hand-built box tree rather than a real movie.
"""

from __future__ import annotations

import struct

import pytest

from media_compost.media import _edit_shift, _mp4_track_edits, _mp4_track_names, shift_vtt


def box(kind: str, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind.encode("latin-1") + payload


def titl(text: str) -> bytes:
    """A 3GPP title atom: version/flags, packed language, NUL-terminated UTF-8."""
    return box("titl", b"\0\0\0\0" + b"\x55\xc4" + text.encode("utf-8") + b"\0")


def trak(*children: bytes) -> bytes:
    return box("trak", b"".join(children))


def write(tmp_path, *top: bytes):
    p = tmp_path / "movie.mp4"
    p.write_bytes(b"".join(top))
    return p


def test_names_are_keyed_by_track_order(tmp_path):
    p = write(
        tmp_path,
        box("ftyp", b"isom" + b"\0" * 8),
        box("moov", b"".join([
            box("mvhd", b"\0" * 100),
            trak(box("tkhd", b"\0" * 84)),                                # 0: no name
            trak(box("udta", box("name", b"German Audio") + titl("German Audio"))),
            trak(box("udta", box("name", b"Signs"))),
            trak(box("udta", titl("English Subs"))),                      # titl only
        ])),
    )
    assert _mp4_track_names(p) == {1: "German Audio", 2: "Signs", 3: "English Subs"}


def test_a_64_bit_box_header_is_followed(tmp_path):
    # A large mdat is written with the 64-bit extended size form; the walk must
    # step over it and still find the moov behind it.
    big = struct.pack(">I", 1) + b"mdat" + struct.pack(">Q", 16 + 4) + b"data"
    p = write(tmp_path, big, box("moov", trak(box("udta", box("name", b"Signs")))))
    assert _mp4_track_names(p) == {0: "Signs"}


def test_a_truncated_box_ends_the_walk_without_raising(tmp_path):
    # A trak header claiming more bytes than the moov holds: the walk stops
    # there and keeps whatever the traks before it named.
    good = trak(box("udta", box("name", b"Signs")))
    p = write(tmp_path, box("moov", good + struct.pack(">I", 1 << 20) + b"trak"))
    assert _mp4_track_names(p) == {0: "Signs"}


def test_a_non_mp4_file_yields_nothing(tmp_path):
    p = tmp_path / "movie.mkv"
    p.write_bytes(b"\x1a\x45\xdf\xa3" + b"\0" * 64)  # EBML magic
    assert _mp4_track_names(p) == {}


# --- edit lists -------------------------------------------------------------
# A subtitle track's `elst` is what puts its cues on the same timeline as the
# picture; ffmpeg's own handling of it rebases the track (see
# `extract_subtitle_vtt`), so the shift is computed here and applied to the VTT.

def elst(*entries: tuple[int, int]) -> bytes:
    body = b"\0\0\0\0" + struct.pack(">I", len(entries))
    for dur, mt in entries:
        body += struct.pack(">Iih", dur, mt, 1) + b"\0\0"
    return box("elst", body)


def mvhd(timescale: int) -> bytes:
    return box("mvhd", b"\0\0\0\0" + b"\0" * 8 + struct.pack(">I", timescale) + b"\0" * 84)


def mdhd(timescale: int) -> bytes:
    return box("mdhd", b"\0\0\0\0" + b"\0" * 8 + struct.pack(">I", timescale) + b"\0" * 8)


def test_edit_shift_is_the_delay_minus_the_media_start():
    # A plain edit starting 1.1 s into the media pulls every sample earlier.
    assert _edit_shift([(2257578, 1100)], 600, 1000) == pytest.approx(-1.1)
    # An empty edit is a pure delay, and a following edit still counts.
    assert _edit_shift([(600, -1), (1000, 500)], 600, 1000) == pytest.approx(0.5)
    assert _edit_shift([], 600, 1000) == 0.0


def test_track_edits_are_read_per_stream(tmp_path):
    p = write(
        tmp_path,
        box("moov", b"".join([
            mvhd(600),
            trak(box("mdia", mdhd(100000)), box("edts", elst((2257805, 8400)))),
            trak(box("mdia", mdhd(1000))),                                   # no edits
            trak(box("mdia", mdhd(1000)), box("edts", elst((2257578, 1100)))),
        ])),
    )
    assert _mp4_track_edits(p) == pytest.approx({0: -0.084, 1: 0.0, 2: -1.1})


def test_a_non_mp4_has_no_edit_list_answer(tmp_path):
    p = tmp_path / "movie.mkv"
    p.write_bytes(b"\x1a\x45\xdf\xa3" + b"\0" * 64)
    # None, not {} — the caller uses it to decide whether ffmpeg even
    # understands -ignore_editlist.
    assert _mp4_track_edits(p) is None


VTT = """WEBVTT

1
00:00:11.130 --> 00:00:12.080 line:90%
Hey...

00:00:12.490 --> 00:00:14.880
They say it's five centimeters per second.
"""


def test_shift_vtt_moves_every_cue_and_keeps_its_settings():
    out = shift_vtt(VTT, -1.1)
    assert "00:00:10.030 --> 00:00:10.980 line:90%" in out
    assert "00:00:11.390 --> 00:00:13.780" in out
    assert "Hey..." in out and out.startswith("WEBVTT")


def test_shift_vtt_drops_cues_pushed_before_zero():
    out = shift_vtt(VTT, -13)
    assert "Hey..." not in out          # ended before the video starts
    assert "1\n" not in out             # …and so did its identifier
    assert "00:00:00.000 --> 00:00:01.880" in out  # the straddling cue is clamped
