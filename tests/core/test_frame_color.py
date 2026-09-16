"""What a frame's colour has to be converted from, and what it must not.

A PNG carries no colour information at all, so every viewer reads one as
sRGB — which means whatever ffmpeg hands back has to already BE sRGB. The
player, meanwhile, reads the stream's tags and does its own conversion. A
still that skips one is a still that does not look like the frame you were
watching, which is the bug these rules exist for.

The decision is pure once the tags are in hand, so that is what is tested:
the ffprobe call and the ffmpeg run are the parts that need a real file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from media_compost import media


@pytest.fixture
def zimg(monkeypatch):
    """An ffmpeg that HAS zscale — the interesting case."""
    monkeypatch.setattr(media, "_has_zscale", lambda: True)


def tags(monkeypatch, transfer, primaries):
    monkeypatch.setattr(media, "_colorimetry", lambda _p: (transfer, primaries))


PATH = Path("/nowhere.mp4")


def test_pq_and_hlg_are_hdr_under_every_spelling():
    for t in ("smpte2084", "SMPTE2084", "st2084", "arib-std-b67", "arib_std_b67"):
        assert media.is_hdr_transfer(t), t
    for t in ("bt709", "bt470bg", "smpte170m", "", None):
        assert not media.is_hdr_transfer(t), t


def test_an_hdr_stream_is_tone_mapped(monkeypatch, zimg):
    tags(monkeypatch, "smpte2084", "bt2020")
    filt = media.color_filter_for(PATH)
    assert filt and "tonemap" in filt
    # It ends on BT.709 — the whole point is landing where a PNG is read.
    assert "zscale=t=bt709:m=bt709" in filt


def test_plain_bt709_is_left_completely_alone(monkeypatch, zimg):
    """ffmpeg already reads the stream's own matrix and range. A filter here
    could only add a rounding difference to a frame that was already right."""
    tags(monkeypatch, "bt709", "bt709")
    assert media.color_filter_for(PATH) is None


def test_wide_primaries_are_converted_without_tone_mapping(monkeypatch, zimg):
    """Quiet — 0.05/255 on the average pixel of a real file — but it reaches 23
    on the saturated ones, which are the pixels it is about."""
    tags(monkeypatch, "bt709", "bt470bg")
    filt = media.color_filter_for(PATH)
    assert filt == "zscale=p=bt709,format=yuv420p"
    assert "tonemap" not in filt


def test_an_untagged_stream_is_never_converted(monkeypatch, zimg):
    """A file that says nothing is assumed BT.709 by everything that reads it,
    the player included. Converting from a guess turns a right picture wrong."""
    tags(monkeypatch, None, None)
    assert media.color_filter_for(PATH) is None


def test_ffprobes_unknown_counts_as_saying_nothing(monkeypatch):
    """`_colorimetry` is what normalises it, so this one drives the real
    function over a faked ffprobe reply."""
    monkeypatch.setattr(media, "_ffprobe_exe", lambda: "ffprobe")

    class Reply:
        returncode = 0
        stdout = ('{"streams":[{"color_transfer":"unknown",'
                  '"color_primaries":"unknown"}]}')

    monkeypatch.setattr(media.subprocess, "run", lambda *a, **k: Reply())
    assert media._colorimetry(PATH) == (None, None)


def test_without_zscale_nothing_is_attempted(monkeypatch):
    """A frame extracted the plain way is imperfect; no frame at all is worse,
    and a filter naming a missing library fails the whole extraction."""
    monkeypatch.setattr(media, "_has_zscale", lambda: False)
    tags(monkeypatch, "smpte2084", "bt2020")
    assert media.color_filter_for(PATH) is None
