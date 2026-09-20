"""Videos as training images (TrainingConfig.video).

The interesting parts are not "does ffmpeg run" but the four rules the
feature is made of: a video contributes FRAMES rather than itself, a frame
carries the tags that hold AT ITS MOMENT, a held shot counts once, and a
frame with nothing to build a prompt from is left out — which is why the
clips here are tagged even where the test is about something else.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from media_compost import media
from media_compost.ui.config import UiConfig
from media_compost.db import Item, ItemTag, ItemTagBox, ItemTagPlacement, Tag
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.server.deps import Library
from media_compost.train.dataset import build_manifest
from tests.train.test_training import _manifest as _build_public
from media_compost.train.spec import DatasetQuery, TrainingConfig


def _video(path: Path, seconds: int = 6, source: str = "testsrc") -> Path:
    """A clip that CHANGES: a colour-bar source, so consecutive seconds are
    genuinely different pictures and dedup has something to keep.

    ``source`` is the lavfi generator, and naming it matters wherever a test
    wants TWO films: two clips of the same generator are the same pictures,
    and the importer folds them into one item — which is a test with one
    video in it however many files it wrote.
    """
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"{source}=size=320x180:rate=10:duration={seconds}",
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


def _still_video(path: Path, seconds: int = 6) -> Path:
    """A clip that does NOT change: one colour held for its whole length."""
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi",
         "-i", f"color=c=teal:size=320x180:rate=10:duration={seconds}",
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


@pytest.fixture
def lib_with_video(tmp_path: Path):
    def build(maker=_video, seconds: int = 6) -> tuple[Library, int]:
        maker(tmp_path / "clip.mp4", seconds)
        cfg = UiConfig(data_dir=tmp_path / "data")
        lib = Library(cfg)
        with lib.db.session() as s:
            Importer(s, lib.store, cfg).import_paths(
                [tmp_path / "clip.mp4"], ImportOptions())
            vid = s.query(Item).filter(Item.kind == "video").one()
            return lib, int(vid.id)
    return build


def _cfg(caps=None, **video) -> TrainingConfig:
    """The job, with the video settings as keywords — `caps` is the run's own
    caption config, which is a different `captions` from `video.captions`."""
    return TrainingConfig(
        model="sd15",
        hyper={"steps": 10, "checkpoint_every": 0},
        queries=[DatasetQuery(weight=1.0)],
        buckets={"resolutions": [256]},
        captions=caps or {},
        video=video,
    )


def _caption(lib, item_id: int, text: str, meta=()) -> None:
    """Caption the film, optionally labelled with meta tags — which is how a
    library says a caption is about the whole thing rather than a moment."""
    from media_compost import open_library

    with open_library(lib.config.data_dir, source="cli") as pub:
        cap = pub.items[item_id].add_caption(text)
        for name in meta:
            cap.meta_tags.add(name)


def _tag(lib, item_id: int, name: str, spans=()) -> None:
    """Assign a tag, optionally as a set of time RANGES (a film tag's
    coverage: a box with a time and no geometry)."""
    with lib.db.session() as s:
        tag = s.query(Tag).filter(Tag.name == name).one_or_none()
        if tag is None:
            tag = Tag(name=name)
            s.add(tag)
            s.flush()
        it = ItemTag(item_id=item_id, tag_id=tag.id, negative=False)
        s.add(it)
        s.flush()
        if spans:
            pl = ItemTagPlacement(item_tag_id=it.id, group_id=None)
            s.add(pl)
            s.flush()
            for a, b in spans:
                s.add(ItemTagBox(placement_id=pl.id, time_start=a, time_end=b))
        s.commit()


def _manifest(lib, cfg: TrainingConfig, tmp_path: Path) -> dict:
    jd = tmp_path / "job"
    jd.mkdir(exist_ok=True)
    return _build_public(lib, cfg.model_dump(mode="json"), jd)


def test_videos_are_skipped_unless_the_job_asks_for_them(lib_with_video,
                                                         tmp_path):
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    with pytest.raises(ValueError, match="no items match"):
        _manifest(lib, _cfg(include=False), tmp_path)


def test_a_video_contributes_frames_not_itself(lib_with_video, tmp_path):
    lib, vid = lib_with_video()
    # Tagged, because a frame with no tags and no caption has no prompt to
    # train against and is left out — the same rule an untagged picture meets.
    _tag(lib, vid, "clip")
    manifest = _manifest(lib, _cfg(include=True, every=1.0), tmp_path)
    items = manifest["items"]
    # ~6 seconds at one frame a second, and every entry is a real file that is
    # NOT the video (a video item is not a picture to train on).
    assert 4 <= len(items) <= 7
    for entry in items:
        assert entry["item_id"] == vid
        assert Path(entry["path"]).is_file()
        assert Path(entry["path"]).suffix == ".jpg"
        # No shared latent cache: these pixels vanish with the run.
        assert "latent_path" not in entry
    # The query pool points at the frames, not at the item.
    assert sorted(manifest["groups"][0]["items"]) == list(range(len(items)))


def test_a_frame_joins_every_resolution_the_run_trains_at(lib_with_video,
                                                          tmp_path):
    """A frame is an ordinary training picture once it exists, so several
    resolutions multiply it exactly as they multiply a picture.

    NEVER UPSCALE is not asked of it: a frame is extracted to order rather
    than found at whatever size somebody saved it, so it takes a bucket at
    every size the run trains at.
    """
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    one = _manifest(lib, _cfg(include=True, every=1.0), tmp_path)
    cfg = _cfg(include=True, every=1.0)
    cfg.buckets.resolutions = [128, 256]
    two_dir = tmp_path / "two"
    two_dir.mkdir()
    two = _manifest(lib, cfg, two_dir)
    assert len(two["items"]) == 2 * len(one["items"])
    at = {}
    for e in two["items"]:
        at.setdefault(e["video_time"], set()).add(e["bucket"])
    assert at and all(len(b) == 2 for b in at.values()), at


def test_a_held_shot_counts_once(lib_with_video, tmp_path):
    lib, vid = lib_with_video(_still_video, 6)
    _tag(lib, vid, "clip")
    kept = _manifest(lib, _cfg(include=True, every=1.0, dedupe=True), tmp_path)
    assert len(kept["items"]) == 1
    # Without dedup the same six seconds are six pictures.
    all_frames = _manifest(lib, _cfg(include=True, every=1.0, dedupe=False),
                           tmp_path)
    assert len(all_frames["items"]) >= 5


def test_a_frame_carries_the_tags_that_hold_at_its_moment(lib_with_video,
                                                          tmp_path):
    lib, vid = lib_with_video()
    _tag(lib, vid, "whole_film")                       # untimed: everywhere
    _tag(lib, vid, "early", spans=[(0.0, 2.0)])        # a range
    _tag(lib, vid, "late", spans=[(4.0, 6.0)])
    manifest = _manifest(lib, _cfg(include=True, every=1.0), tmp_path)
    by_time = {e["video_time"]: set(e["tags"]) for e in manifest["items"]}
    assert by_time, "no frames extracted"
    for t, tags in by_time.items():
        assert "whole_film" in tags, t
        assert ("early" in tags) == (t <= 2.5), (t, tags)
        assert ("late" in tags) == (t >= 3.5), (t, tags)


def test_a_range_takes_what_it_implies_with_it(lib_with_video, tmp_path):
    """A timed tag that does not hold at a frame must not leave the tags it
    entails behind — an implication is the assignment, one step removed."""
    lib, vid = lib_with_video()
    with lib.db.session() as s:
        from media_compost.db import TagImplication

        poodle = Tag(name="poodle")
        dog = Tag(name="dog")
        s.add_all([poodle, dog])
        s.flush()
        s.add(TagImplication(tag_id=poodle.id, implies_id=dog.id))
        s.commit()
    _tag(lib, vid, "poodle", spans=[(0.0, 2.0)])
    manifest = _manifest(lib, _cfg(include=True, every=1.0), tmp_path)
    for e in manifest["items"]:
        early = e["video_time"] <= 2.5
        assert ("poodle" in e["tags"]) == early, e
        assert ("dog" in e["tags"]) == early, e


def test_the_interval_can_be_counted_in_frames(lib_with_video, tmp_path):
    lib, vid = lib_with_video(_video, 4)   # 10 fps
    _tag(lib, vid, "clip")
    every_10th = _manifest(
        lib, _cfg(include=True, every=10, unit="frames", dedupe=False),
        tmp_path)
    every_second = _manifest(
        lib, _cfg(include=True, every=1.0, unit="seconds", dedupe=False),
        tmp_path)
    # Every 10th frame of a 10 fps clip IS one a second.
    assert len(every_10th["items"]) == len(every_second["items"])


def test_a_frame_inherits_the_film_s_captions(lib_with_video, tmp_path):
    lib, vid = lib_with_video()
    _caption(lib, vid, "a test pattern")
    manifest = _manifest(
        lib, _cfg({"source": "captions"}, include=True, every=1.0), tmp_path)
    assert manifest["items"]
    for e in manifest["items"]:
        assert e["captions"] == ["a test pattern"]


def test_a_run_can_withhold_the_film_s_captions_from_its_frames(
        lib_with_video, tmp_path):
    """Some captions describe the film, not any one moment of it. With
    inheritance off a captions run has nothing to train a frame against, so
    the film contributes nothing rather than a run of empty prompts."""
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    _caption(lib, vid, "a fight scene set to music")
    kept = _manifest(
        lib, _cfg({"source": "tags"}, include=True, every=1.0,
                  captions="none"), tmp_path)
    assert kept["items"] and all(e["captions"] == [] for e in kept["items"])
    with pytest.raises(ValueError, match="frames extracted"):
        _manifest(lib, _cfg({"source": "captions"}, include=True, every=1.0,
                            captions="none"), tmp_path)


def test_which_captions_a_frame_inherits_is_picked_by_meta_tag(lib_with_video,
                                                               tmp_path):
    lib, vid = lib_with_video()
    _caption(lib, vid, "a test pattern", meta=["frame"])
    _caption(lib, vid, "four seconds of colour bars", meta=["film"])
    manifest = _manifest(
        lib, _cfg({"source": "captions"}, include=True, every=1.0,
                  caption_exclude_meta_tags=["FILM"]), tmp_path)
    assert manifest["items"]
    for e in manifest["items"]:
        assert e["captions"] == ["a test pattern"]

    only = _manifest(
        lib, _cfg({"source": "captions"}, include=True, every=1.0,
                  caption_include_meta_tags=["frame"]), tmp_path)
    for e in only["items"]:
        assert e["captions"] == ["a test pattern"]


def test_the_frame_filter_narrows_the_run_s_own_and_never_widens_it(
        lib_with_video, tmp_path):
    """The run-wide lists say which captions the run may train on at all; the
    video ones say which of THOSE a frame inherits. So a caption the run
    excludes can never come back through a film."""
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    _caption(lib, vid, "a note to myself", meta=["private"])
    manifest = _manifest(
        lib, _cfg({"source": "both", "exclude_meta_tags": ["private"]},
                  include=True, every=1.0,
                  caption_include_meta_tags=["private"]), tmp_path)
    assert manifest["items"]
    for e in manifest["items"]:
        assert e["captions"] == []
        # …and with no caption to inherit, every frame is a tags visit.
        assert e["prompt_mode"] == "tags"


def test_a_frame_is_one_visit_per_prompt_mode_like_any_other_picture(
        lib_with_video, tmp_path):
    """A "caption + tags" run shows a picture TWICE, once under each — glueing
    the two into one prompt is what `_prompt_modes` exists to prevent, and a
    frame used to be the one picture it never reached."""
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    _caption(lib, vid, "a test pattern")
    manifest = _manifest(
        lib, _cfg({"source": "both"}, include=True, every=1.0), tmp_path)
    by_time: dict[float, set] = {}
    for e in manifest["items"]:
        by_time.setdefault(e["video_time"], set()).add(e["prompt_mode"])
    assert by_time
    for t, modes in by_time.items():
        assert modes == {"tags", "caption"}, t


def test_every_caption_repeats_a_frame_too(lib_with_video, tmp_path):
    lib, vid = lib_with_video()
    _caption(lib, vid, "a test pattern")
    _caption(lib, vid, "colour bars")
    manifest = _manifest(
        lib, _cfg({"source": "captions", "caption_repeat": "each_shared"},
                  include=True, every=1.0), tmp_path)
    per_frame: dict[float, list] = {}
    for e in manifest["items"]:
        per_frame.setdefault(e["video_time"], []).append(e)
    assert per_frame
    for t, entries in per_frame.items():
        assert len(entries) == 2, t
        assert {e["captions"][0] for e in entries} == {"a test pattern",
                                                       "colour bars"}
        # Two ways of describing one frame, not two frames' worth of gradient.
        assert all(e["loss_scale"] == 0.5 for e in entries)


def test_a_frame_with_nothing_to_say_is_left_out(lib_with_video, tmp_path):
    """A timed tag holds over its own stretch and nowhere else, so a film
    tagged only for its first half has frames with no prompt at all."""
    lib, vid = lib_with_video()
    _tag(lib, vid, "early", spans=[(0.0, 2.0)])
    manifest = _manifest(lib, _cfg(include=True, every=1.0), tmp_path)
    assert manifest["items"]
    for e in manifest["items"]:
        assert e["tags"] == ["early"]
        assert e["video_time"] <= 2.5


def _decodes(monkeypatch) -> list:
    """Count the times a video is actually DECODED.

    Calls to `videoframes.extract` say nothing — a cache hit is a call too —
    and the decode is the minutes this is all about.
    """
    seen: list[str] = []
    real = media.iter_video_frames

    def counted(path, *a, **kw):
        seen.append(str(path))
        return real(path, *a, **kw)

    monkeypatch.setattr(media, "iter_video_frames", counted)
    return seen


def test_a_rebuild_with_the_same_settings_reuses_the_frames(lib_with_video,
                                                            tmp_path,
                                                            monkeypatch):
    """The fix this cache exists for.

    A job is materialized again whenever it starts without a resume point —
    a pause during the extraction itself, a run that died before its first
    checkpoint, a finished job continued with more steps. Sampling a feature
    film is minutes of decoding, and doing it twice for the same frames is
    the whole of what the user sees.
    """
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    decodes = _decodes(monkeypatch)
    cfg = _cfg(include=True, every=1.0)
    first = _manifest(lib, cfg, tmp_path)
    assert len(decodes) == 1
    second = _manifest(lib, cfg, tmp_path)
    # Not decoded again, and the same dataset down to the paths: a reused
    # frame is the frame, not one like it.
    assert len(decodes) == 1
    assert second["items"] == first["items"]
    assert all(Path(e["path"]).is_file() for e in second["items"])


def test_a_changed_setting_samples_the_video_again(lib_with_video, tmp_path,
                                                   monkeypatch):
    """The stamp is what the frames were MADE of, so every input is in it —
    including the file itself, by size and mtime rather than by id: a film
    re-encoded in place is a different film, and an id survives that."""
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    decodes = _decodes(monkeypatch)
    _manifest(lib, _cfg(include=True, every=1.0), tmp_path)
    _manifest(lib, _cfg(include=True, every=2.0), tmp_path)
    assert len(decodes) == 2, "a moved interval is a different sampling"

    cfg = _cfg(include=True, every=2.0)
    _manifest(lib, cfg, tmp_path)
    assert len(decodes) == 2, "and the one just built is reused"

    with lib.db.session() as s:
        item = s.get(Item, vid)
        path = lib.store.path_of(s, item.active_file)
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 120))
    _manifest(lib, cfg, tmp_path)
    assert len(decodes) == 3, "a film that changed under us is sampled again"


def test_an_interrupted_extraction_is_never_taken_for_a_whole_one(
        lib_with_video, tmp_path):
    """A stopped extraction writes no stamp: the half of a film it got
    through is not the film, and a run reusing it would silently be training
    on the first thirty seconds."""
    from media_compost import open_library
    from media_compost.train import videoframes

    lib, vid = lib_with_video()
    out = tmp_path / "frames" / "uid"
    args = dict(every=0.5, unit="seconds", dedupe=True, threshold=8)
    with open_library(lib.config.data_dir, source="cli") as pub:
        item = pub.items[vid]
        part = videoframes.extract(
            item, out, **args,
            should_stop=lambda: len(list(out.glob("*.jpg"))) >= 3)
        assert part and not (out / videoframes.STAMP).exists()
        assert videoframes.cached(
            out, videoframes.cache_key(item, max_dim=0, **args)) is None
        # And the next extraction starts from an EMPTY folder, so the frames
        # of the interrupted pass cannot end up beside the new ones.
        again = videoframes.extract(item, out, **args)
        assert len(again) > len(part)
        assert set(out.glob("*.jpg")) == {f.path for f in again}


def test_a_film_that_leaves_the_dataset_takes_its_frames_with_it(
        lib_with_video, tmp_path, monkeypatch):
    """Per film, not wholesale: the sweep is what keeps the folder from
    growing every time a query moves."""
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    jd = tmp_path / "job"
    jd.mkdir(exist_ok=True)
    _build_public(lib, _cfg(include=True, every=1.0).model_dump(mode="json"), jd)
    stray = jd / "frames" / "some-other-uid"
    stray.mkdir()
    (stray / "f000000.jpg").write_bytes(b"x")
    _build_public(lib, _cfg(include=True, every=1.0).model_dump(mode="json"), jd)
    assert not stray.exists()
    assert list((jd / "frames").iterdir()), "the selected film keeps its own"


def test_rebuilding_replaces_the_previous_run_s_frames(lib_with_video,
                                                       tmp_path):
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    jd = tmp_path / "job"
    jd.mkdir()
    first = _build_public(
        lib, _cfg(include=True, every=1.0).model_dump(mode="json"), jd)
    stale = Path(first["items"][0]["path"])
    assert stale.is_file()
    second = _build_public(
        lib, _cfg(include=True, every=3.0).model_dump(mode="json"), jd)
    assert len(second["items"]) < len(first["items"])
    # The frames of the first build are gone, not left behind next to the new
    # ones where the sampler would train on both.
    kept = {Path(e["path"]) for e in second["items"]}
    frames = set((jd / "frames").rglob("*.jpg"))
    assert frames == kept
    assert json.loads((jd / "manifest.json").read_text(encoding="utf-8"))["items"]


# ---- across runs -------------------------------------------------------------
#
# A job is materialized again whenever it starts without a resume point, and
# with video frames that is the expensive half. These two are the rules that
# keep it from being paid for twice.


def test_a_pause_during_the_extraction_keeps_the_films_it_finished(
        tmp_path: Path, monkeypatch):
    """The user-visible bug: pause a job while it is unpacking its films,
    resume it, and every one of them is sampled again from the start.

    Nothing has a resume point yet — the trainer has not run a step — so the
    job is materialized from scratch, and the materialization used to wipe
    the frames folder before it began. The film the pause landed in is
    genuinely sampled twice (half a film is not a film, and it writes no
    stamp); the ones already finished are not.
    """
    from media_compost.ops import tagassign
    from media_compost.ops.context import Ctx
    from media_compost.train import paths as tp
    from tests.train.test_training import _use_fake_trainer, _wait

    _use_fake_trainer(monkeypatch)
    _video(tmp_path / "a.mp4", seconds=12)
    _video(tmp_path / "b.mp4", seconds=12, source="testsrc2")
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [tmp_path / "a.mp4", tmp_path / "b.mp4"], ImportOptions())
    with lib.db.session() as s:
        for item in s.query(Item).all():
            tagassign.stamp(Ctx(s, source="cli"), [item.id], ["clip"], [])
        s.commit()
    mgr = lib.training

    decodes: list[str] = []
    real = media.iter_video_frames

    def counted(path, *a, **kw):
        decodes.append(str(path))
        return real(path, *a, **kw)

    monkeypatch.setattr(media, "iter_video_frames", counted)

    job = TrainingConfig(
        model="sd15", hyper={"steps": 40, "checkpoint_every": 0},
        queries=[DatasetQuery(weight=1.0)],
        buckets={"resolutions": [64], "skip_upscale": False},
        video={"include": True, "every": 0.1},
    )
    uid = mgr.create("films", job, "tester")
    jd = tp.job_dir(mgr.dir, uid)
    mgr.enqueue(uid)
    mgr.queue_run()
    # Pause once the SECOND film is being sampled: one is finished, one is
    # half done, and telling those apart is the whole of the fix.
    end = time.time() + 90
    while time.time() < end and len(decodes) < 2:
        time.sleep(0.02)
    assert len(decodes) == 2, "the run never reached the second film"
    mgr.pause(uid)
    _wait(mgr, uid, ("queued", "paused", "draft"))
    assert not (tp.checkpoints_dir(jd) / "last").is_dir(), \
        "the point of this test is a job with nothing to resume from"

    mgr.queue_run()
    end = time.time() + 120
    while time.time() < end and mgr.get(uid).get("step", 0) < 3:
        time.sleep(0.05)
    assert mgr.get(uid).get("step", 0) >= 3, mgr.get(uid).get("message")
    # Three decodes: the finished film, the interrupted one, and the second
    # attempt at the interrupted one. The film that was already sampled is
    # not read again — which is what the whole run used to cost.
    assert len(decodes) == 3, decodes
    mgr.cancel(uid)


def test_rebuilding_drops_the_job_s_own_latents(lib_with_video, tmp_path):
    """A job-local latent is named by an entry's POSITION in the manifest,
    and a rebuild is precisely the moment those move — a frame that was entry
    7 can be another frame's pixels next time. The frames are kept and the
    latents are not, which is the same rule read from both ends: what is
    keyed by its content survives, what is keyed by its position does not."""
    lib, vid = lib_with_video()
    _tag(lib, vid, "clip")
    jd = tmp_path / "job"
    jd.mkdir(exist_ok=True)
    cfg = _cfg(include=True, every=1.0).model_dump(mode="json")
    _build_public(lib, cfg, jd)
    (jd / "latents").mkdir(exist_ok=True)
    stale = jd / "latents" / "i00003.pt"
    stale.write_bytes(b"not this dataset's")
    _build_public(lib, cfg, jd)
    assert not stale.exists()
    # …and the frames, which are keyed by what they were made of, stayed.
    assert list((jd / "frames").rglob("*.jpg"))


# A JOB WHOSE FRAMES WERE RECLAIMED used to be the one case that made a
# resume build its dataset again — `TrainingManager._dataset_ready`, which
# asked whether the previous run's scratch was still there. Every resume
# rebuilds now (the library it names goes on changing while a job waits), so
# there is nothing left to ask and the test that asked it is gone with the
# method; `tests/train/test_dataset_refresh.py` holds the rule that replaced
# it. The frames themselves are still cached per film, which is what keeps
# the rebuild cheap — the test above this one.
