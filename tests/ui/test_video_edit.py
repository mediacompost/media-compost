"""Saving a video edit: the cutlist actually becomes a file on the item.

`test_videoedit.py` covers the arithmetic without ffmpeg; this runs the real
thing on a tiny generated clip, because the parts that break are the ones that
only exist once ffmpeg is involved — the filter graph's stream names, the
audio chain on a silent source, and the file the item ends up with.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from media_compost import media, videoedit
from media_compost.ui.config import UiConfig
from media_compost.db import File, Item
from media_compost.importer import ImportOptions, Importer
from media_compost.ops import Ctx
from media_compost.ui.ops import video as ops_video
from media_compost.ui.server.deps import Library


def _clip(path: Path, seconds: int = 4, audio: bool = False) -> Path:
    cmd = [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi",
           "-i", f"testsrc=size=160x120:rate=10:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                "-c:a", "aac", "-shortest"]
    cmd += ["-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture
def lib_video(tmp_path: Path):
    def build(seconds: int = 4, audio: bool = False) -> tuple[Library, int]:
        _clip(tmp_path / "clip.mp4", seconds, audio)
        cfg = UiConfig(data_dir=tmp_path / "data")
        lib = Library(cfg)
        with lib.db.session() as s:
            Importer(s, lib.store, cfg).import_paths(
                [tmp_path / "clip.mp4"], ImportOptions())
            vid = s.query(Item).filter(Item.kind == "video").one()
            return lib, int(vid.id)
    return build


def _ctx(lib: Library, s):
    return Ctx(session=s, _store=lib.store, _config=lib.config, source="web")


def _render(lib: Library, item_id: int, plan, **kw) -> dict:
    with lib.db.session() as s:
        res = ops_video.render_edit(_ctx(lib, s), item_id, plan, **kw)
        s.commit()
        return res


def test_a_cutlist_becomes_a_new_active_file(lib_video):
    lib, iid = lib_video(seconds=4)
    plan = videoedit.Plan(cuts=[(0.0, 1.0), (2.0, 3.0)])
    res = _render(lib, iid, plan)
    with lib.db.session() as s:
        item = s.get(Item, iid)
        files = s.query(File).filter(File.item_id == iid).all()
        assert len(files) == 2, "the source is kept — a cut is not destructive"
        new = s.get(File, res["file_id"])
        assert item.active_file_id == new.id
        # Two one-second pieces, whatever rounding the encoder does at the ends.
        assert 1.6 < (new.duration or 0) < 2.4
        assert new.derived_from_file_id is not None


def test_saving_to_a_new_item_leaves_the_original_alone(lib_video):
    lib, iid = lib_video(seconds=3)
    plan = videoedit.Plan(cuts=[(0.0, 1.0)])
    res = _render(lib, iid, plan, new_item=True)
    assert res["item_id"] != iid
    with lib.db.session() as s:
        assert s.query(File).filter(File.item_id == iid).count() == 1
        made = s.get(Item, res["item_id"])
        assert made.kind == "video" and made.active_file_id is not None


def test_a_rotation_swaps_the_stored_size(lib_video):
    lib, iid = lib_video(seconds=2)
    res = _render(lib, iid, videoedit.Plan(cuts=[(0.0, 2.0)], rotate=90))
    with lib.db.session() as s:
        new = s.get(File, res["file_id"])
        assert (new.width, new.height) == (120, 160)


def test_an_edit_that_changes_nothing_is_refused(lib_video):
    lib, iid = lib_video(seconds=2)
    with lib.db.session() as s:
        with pytest.raises(Exception) as err:
            ops_video.render_edit(_ctx(lib, s), iid,
                                  videoedit.Plan(cuts=[(0.0, 2.0)]))
        assert "unchanged" in str(err.value)


def test_a_clip_with_sound_keeps_it(lib_video):
    lib, iid = lib_video(seconds=3, audio=True)
    res = _render(lib, iid, videoedit.Plan(cuts=[(0.0, 1.0), (2.0, 3.0)]))
    with lib.db.session() as s:
        new = s.get(File, res["file_id"])
        path = lib.store.path_of(s, new)
    kinds = {t.get("kind") for t in media.probe_tracks(path)}
    assert "audio" in kinds


def test_cancelling_leaves_nothing_behind(lib_video):
    lib, iid = lib_video(seconds=4)
    plan = videoedit.Plan(cuts=[(0.0, 3.0)], rotate=90)
    with lib.db.session() as s:
        with pytest.raises(media.Canceled):
            ops_video.render_edit(_ctx(lib, s), iid, plan,
                                  should_cancel=lambda: True)
        s.rollback()
    with lib.db.session() as s:
        assert s.query(File).filter(File.item_id == iid).count() == 1


def test_progress_is_reported(lib_video):
    lib, iid = lib_video(seconds=4)
    seen: list[float] = []
    _render(lib, iid, videoedit.Plan(cuts=[(0.0, 3.0)], rotate=90),
            on_progress=seen.append)
    assert seen, "ffmpeg's -progress stream is what drives the modal"
    assert all(0.0 <= f <= 1.0 for f in seen)


# ---- gaps ------------------------------------------------------------------


def test_a_gap_renders_as_black_of_the_length_asked_for(lib_video):
    """The one that has to be run rather than reasoned about: a gap is
    GENERATED, so nothing about it exists in the source, and the concat filter
    is particular about its inputs agreeing."""
    lib, iid = lib_video(seconds=4)
    plan = videoedit.Plan(cuts=[(0.0, 1.0), (videoedit.GAP, videoedit.GAP + 2.0), (3.0, 4.0)])
    res = _render(lib, iid, plan)
    with lib.db.session() as s:
        new = s.get(File, res["file_id"])
        # One second, two seconds of nothing, one second.
        assert 3.6 < (new.duration or 0) < 4.4, new.duration


def test_a_gap_renders_with_sound_too(lib_video):
    """The audio side of the same graph: silence has to arrive at the concat
    in the same sample format and layout as the real segments, or the render
    fails outright."""
    lib, iid = lib_video(seconds=3, audio=True)
    plan = videoedit.Plan(cuts=[(0.0, 1.0), (videoedit.GAP, videoedit.GAP + 1.0)])
    res = _render(lib, iid, plan)
    with lib.db.session() as s:
        new = s.get(File, res["file_id"])
        assert 1.6 < (new.duration or 0) < 2.4, new.duration


def test_a_video_that_is_only_a_gap_still_renders(lib_video):
    lib, iid = lib_video(seconds=2)
    res = _render(lib, iid, videoedit.Plan(cuts=[(videoedit.GAP, videoedit.GAP + 1.5)]))
    with lib.db.session() as s:
        new = s.get(File, res["file_id"])
        assert 1.2 < (new.duration or 0) < 1.9, new.duration


def _streams(path: Path) -> list[tuple[str, str]]:
    """(codec_type, codec_tag) for every stream in a file."""
    out = subprocess.run(
        [media._ffprobe_exe(), "-v", "error", "-show_entries",
         "stream=codec_type,codec_tag_string", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return [tuple(line.split(",")[:2])  # type: ignore[misc]
            for line in out.stdout.splitlines() if line.strip()]


@pytest.mark.parametrize("fps", [None, 5.0])
def test_a_cut_carries_none_of_the_source_s_chapters(tmp_path: Path, fps):
    """ffmpeg copies chapters from the first input that has them unless told
    otherwise, and the mov muxer writes them as a `text` DATA TRACK spanning
    the WHOLE SOURCE. `-map` does not touch it — it is metadata rather than a
    stream being selected — so a one-second cut of a two-hour film came out
    with a two-hour data track in it, and a `<video>` element takes its
    duration from the longest track: the library said one second and the
    player said two hours.

    Both render paths are covered: `fps` is what decides whether the cut is
    re-encoded through the filter graph or copied.
    """
    meta = tmp_path / "chapters.txt"
    meta.write_text(
        ";FFMETADATA1\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=4000\ntitle=One\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=4000\nEND=8000\ntitle=Two\n",
        encoding="utf-8")
    src = tmp_path / "chaptered.mp4"
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=8",
         "-i", str(meta), "-map_metadata", "1", "-map_chapters", "1",
         "-pix_fmt", "yuv420p", str(src)], check=True)
    assert any(t == "data" for t, _ in _streams(src)), "the fixture has none"

    out = tmp_path / "cut.mp4"
    plan = videoedit.Plan(cuts=[(1.0, 2.5)], fps=fps)
    media.render_cutlist(src, out, plan, 8.0, 160, 120, None)
    assert [t for t, _ in _streams(out)] == ["video"]
