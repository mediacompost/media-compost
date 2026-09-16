"""How a video's frames get out of ffmpeg: exactly which frame, and how often.

The behaviour these pin was bought by measurement rather than by reading —
see `media.extract_frames` for the numbers — and each of them is silent when
it breaks: a frame one off the one that matched still looks like the picture,
and a redundant `ffprobe` per extraction only shows up as an import that is
slow for no visible reason.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from media_compost import media
from media_compost.db import File
from media_compost.importer import Importer, ImportOptions
from tests.core.conftest import make_image


def _video_of_distinct_frames(src: Path, out: Path, n: int = 24,
                              rate: int = 12) -> Path:
    """A clip whose every frame differs, so "which frame is this" has an answer.

    `_make_video` in test_video_sequences loops ONE still, which is right for
    what it tests and useless here: every frame of it is byte-identical, so an
    off-by-one is undetectable.
    """
    src.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        make_image(src / f"f{i:03d}.png", seed=100 + i, size=(160, 120))
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-framerate", str(rate), "-i", str(src / "f%03d.png"),
         "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(out)],
        check=True,
    )
    return out


def _scanned(video: Path) -> dict[int, bytes]:
    """Every frame the importer's scan sees, by index, as raw pixels."""
    info, _ = media.probe_video_full(video)
    return {i: im.tobytes()
            for i, _ts, im in media.iter_video_frames(video, info.frame_rate)}


def test_an_extracted_frame_is_the_frame_the_scan_SAW(tmp_path: Path):
    """The whole point of re-extracting: a matched frame is kept beside the
    picture it matched, so it has to BE that frame.

    Selection is by index for exactly this reason. `extract_frame`'s ``-ss`` is
    formatted to three decimals, which on a 23.976 fps file asks for frame 90
    (t=3.7537...s) as 3.754 and gets frame 91 back.
    """
    video = _video_of_distinct_frames(tmp_path / "src", tmp_path / "clip.mp4")
    scan = _scanned(video)
    info, _ = media.probe_video_full(video)
    rate = info.frame_rate or 12.0

    wanted = [(i, i / rate) for i in (0, 3, 11, 17, 23)]
    got = media.extract_frames(video, wanted)
    assert set(got) == {i for i, _ in wanted}
    for i, _ts in wanted:
        assert got[i].tobytes() == scan[i], f"frame {i} is not frame {i}"


def test_ONE_frame_is_extracted_the_same_exact_way_as_many(tmp_path: Path):
    """No count-dependent second path. A seek would be quicker for a single
    frame and is declined deliberately: two accuracies depending on how many
    frames were asked for is worse than the half-second it saves."""
    video = _video_of_distinct_frames(tmp_path / "src", tmp_path / "clip.mp4")
    scan = _scanned(video)
    info, _ = media.probe_video_full(video)
    rate = info.frame_rate or 12.0

    for count in (1, 2, 3, 5):
        idx = [0, 7, 13, 19, 23][:count]
        got = media.extract_frames(video, [(i, i / rate) for i in idx])
        assert set(got) == set(idx)
        for i in idx:
            assert got[i].tobytes() == scan[i], f"{count} wanted: frame {i}"

    assert media.extract_frames(video, []) == {}


def test_max_dim_downscales_and_never_upscales(tmp_path: Path):
    """The thumbnail's downscale belongs to ffmpeg: it is the whole saving, and
    a caller that keeps the frame as a picture in its own right passes none."""
    video = _video_of_distinct_frames(tmp_path / "src", tmp_path / "clip.mp4")
    assert media.extract_frame(video, 0.5).size == (160, 120)
    assert media.extract_frame(video, 0.5, max_dim=80).size == (80, 60)
    # Bigger than the frame changes nothing — `min(N,iw)` is what says so.
    assert media.extract_frame(video, 0.5, max_dim=4096).size == (160, 120)


def test_a_supplied_colour_filter_is_used_INSTEAD_of_probing(monkeypatch,
                                                             tmp_path: Path):
    """`color_filter_for` shells out to ffprobe. None is a real answer ("this
    file needs no conversion"), so "nobody has asked yet" needs a value of its
    own — passing None must not send it probing again."""
    video = _video_of_distinct_frames(tmp_path / "src", tmp_path / "clip.mp4")
    calls = []
    monkeypatch.setattr(media, "color_filter_for",
                        lambda p: calls.append(p) or None)

    media.extract_frame(video, 0.2, color_filter=None)
    media.extract_frames(video, [(1, 0.1), (2, 0.2)], color_filter=None)
    list(media.iter_video_frames(video, 12.0, color_filter=None))
    assert calls == []

    media.extract_frame(video, 0.2)
    assert len(calls) == 1


def test_importing_a_video_probes_its_COLOUR_once_and_extracts_in_ONE_pass(
        lib, monkeypatch, tmp_path: Path):
    """Both costs used to scale with the number of matched frames: an ffprobe
    and an ffmpeg run each, ~192 ms a match, 62% of the wall clock of a video
    with nine of them."""
    cfg, db, store = lib
    src = tmp_path / "src"
    video = _video_of_distinct_frames(src, tmp_path / "clip.mp4")

    # Pull three frames out as stills and import them, so the video's scan has
    # something to match. They must be what the scan sees, or nothing matches.
    info, _ = media.probe_video_full(video)
    rate = info.frame_rate or 12.0
    shots = tmp_path / "shots"
    shots.mkdir()
    picked = [4, 12, 20]
    frames = media.extract_frames(video, [(i, i / rate) for i in picked])
    for i in picked:
        frames[i].save(shots / f"shot{i}.png")

    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            sorted(shots.glob("*.png")), ImportOptions())
        s.commit()

    probes, passes, singles = [], [], []
    real_cf, real_many, real_one = (media.color_filter_for,
                                    media.extract_frames, media.extract_frame)
    monkeypatch.setattr(media, "color_filter_for",
                        lambda p: probes.append(p) or real_cf(p))
    monkeypatch.setattr(media, "extract_frames",
                        lambda p, w, **k: passes.append(len(w)) or real_many(p, w, **k))
    monkeypatch.setattr(media, "extract_frame",
                        lambda p, t, **k: singles.append(k.get("max_dim")) or real_one(p, t, **k))

    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths([video], ImportOptions())
        s.commit()

    assert stats.frames_matched == len(picked)
    # One probe for the whole video — the thumbnail, the scan and every matched
    # frame all take the same answer.
    assert len(probes) == 1
    # One batch for all the matches, whatever their number...
    assert passes == [len(picked)]
    # ...and the only single-frame extraction left is the thumbnail, which asks
    # ffmpeg to downscale rather than decoding 160x120 to resize it here.
    assert singles == [cfg.thumb_size]

    with db.session() as s:
        stored = s.execute(
            select(File).where(File.source_kind == "video_frame")
        ).scalars().all()
        assert len(stored) == len(picked)
        # And each one IS the frame that matched, not a neighbour of it:
        # `source_start` says which moment it claims to be, so the picture has
        # to be the frame at that moment.
        scan = _scanned(video)
        for f in stored:
            idx = round((f.source_start or 0.0) * rate)
            with Image.open(store.path_of(s, f)) as im:
                assert im.convert("RGB").tobytes() == scan[idx], \
                    f"the file for t={f.source_start} is not frame {idx}"


def test_a_file_is_PROBED_ONCE_however_many_frames_are_taken_from_it(
        monkeypatch, tmp_path: Path):
    """Two ffprobes per extraction, of a file that has not changed.

    `color_filter_for` (how the colour is tagged) and `video_has_alpha`
    (whether the pixel format carries alpha) are both questions about the same
    stream and both facts about the ENCODING — ~35 ms each on a 1.1 GB film,
    which was HALF of what capturing a still cost, paid again on every still.
    They are one probe now, remembered per FILE VERSION.

    The key is the STAT and not the path, and that is the load-bearing half: a
    path's contents change here (`fileops` rewrites a file in place to rotate
    it), so a path-only cache would go on describing the file that used to be
    there.
    """
    src = _video_of_distinct_frames(tmp_path / "src", tmp_path / "clip.mp4")
    media._STREAM_PROBES.clear()
    probes: list[list[str]] = []
    real = subprocess.run

    def counting(cmd, *a, **kw):
        # Probes OF THIS FILE. `_alpha_pix_fmts` asks ffprobe for its format
        # table, which is a fact about the BUILD and is already cached for the
        # process — a different question, and not the one here.
        if isinstance(cmd, list) and "ffprobe" in str(cmd[0]) \
                and str(src) in cmd:
            probes.append(cmd)
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", counting)
    for at in (0.1, 0.3, 0.5, 0.7):
        media.extract_frame(src, at, keep_alpha=True)
    assert len(probes) == 1, [" ".join(p) for p in probes]

    # …and the answer follows the BYTES. A rewritten file is a different file
    # however familiar its name, so the next question is asked again.
    src.write_bytes(src.read_bytes())
    media.video_has_alpha(src)
    assert len(probes) == 2, [" ".join(p) for p in probes]
