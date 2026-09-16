"""Video import, on-demand frame refs, and dedup verification. (Videos
never become sequences — the one test of that name pins the absence.)"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select

import json

from media_compost import media
from media_compost.dedup import compute_phash, phash_to_int, hamming, verify_match
from media_compost.db import File, Item, Relationship, Sequence, SequenceItem, VideoFrame
from media_compost.importer import Importer, ImportOptions
from tests.core.conftest import make_image


def _count(session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def _count_files(session, item_id: int) -> int:
    return session.execute(
        select(func.count()).select_from(File).where(File.item_id == item_id)
    ).scalar_one()


def _make_video(still: Path, out: Path, seconds: int = 1, rate: int = 5) -> Path:
    ffmpeg = media._ffmpeg_exe()
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1",
         "-i", str(still), "-t", str(seconds), "-r", str(rate),
         "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )
    return out


def test_phash_256bit_and_verify(tmp_path: Path):
    a = make_image(tmp_path / "a.png", seed=1)
    b = make_image(tmp_path / "b.png", seed=99)
    ha, hb = compute_phash(a), compute_phash(b)
    # 256-bit hash => 64 hex chars.
    assert len(ha) == 64 and len(hb) == 64
    # Distinct images are far apart and fail the secondary pixel check.
    assert hamming(phash_to_int(ha), phash_to_int(hb)) > 10
    with Image.open(a) as ia, Image.open(b) as ib:
        assert verify_match(ia, ia, 0.02) is True
        assert verify_match(ia, ib, 0.02) is False


def test_video_import_creates_frame_refs_and_never_a_sequence(lib, tmp_path: Path):
    """A video import matches frames and records the references — and creates
    NO sequence, ever. A sequence is something read in order (a GIF's frames,
    a book's pages); the frames a film happens to match in the library are a
    scattered subset, not a reading order. (`ImportOptions.video_sequences`
    existed and was removed, pre-release.)"""
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    still = make_image(src / "still.png", seed=7, size=(320, 240))
    video = _make_video(still, src / "clip.mp4")

    with db.session() as s:
        Importer(s, store, cfg).import_paths([still], ImportOptions())
        s.commit()
    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths([video], ImportOptions())
        s.commit()

    with db.session() as s:
        # Just the image + video items — no sequence container.
        assert _count(s, Item) == 2
        assert {it.kind for it in s.execute(select(Item)).scalars()} == {
            "image", "video"}
        assert _count(s, Sequence) == 0
        assert _count(s, SequenceItem) == 0
        # Frame matching still happened: the matched frame added a
        # video_frame File to the still item.
        vf = s.execute(
            select(File).where(File.source_kind == "video_frame")
        ).scalars().all()
        assert len(vf) == 1 and vf[0].path is not None
        assert stats.frames_matched == 1


def test_aspect_close_guards_different_shapes():
    from media_compost.importer import _aspect_close
    assert _aspect_close(16 / 9, 16 / 9) is True
    assert _aspect_close(16 / 9, 1.85) is True          # ~cinema crop, close enough
    assert _aspect_close(16 / 9, 210 / 297) is False     # 16:9 frame vs A4 portrait
    assert _aspect_close(16 / 9, 0) is True              # unknown ratio never blocks


def test_screenshot_imported_after_video_links_back(lib, tmp_path: Path):
    """Importing a video stores a hash per sampled frame; a screenshot from it
    imported LATER matches those hashes and links back to the video with the
    timestamp(s) in the link metadata."""
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    still = make_image(src / "still.png", seed=7, size=(320, 240))
    video = _make_video(still, src / "clip.mp4")

    # Import the VIDEO first — no image to match yet, but frame hashes are kept.
    with db.session() as s:
        Importer(s, store, cfg).import_paths([video], ImportOptions())
        s.commit()
    with db.session() as s:
        assert _count(s, VideoFrame) > 0
        vid = s.execute(select(Item).where(Item.kind == "video")).scalars().one()
        vid_id = vid.id
        # No frame link yet (there was no image at video-import time).
        assert _count(s, Relationship) == 0

    # Now import the screenshot — it should link back to the video.
    with db.session() as s:
        Importer(s, store, cfg).import_paths([still], ImportOptions())
        s.commit()
    with db.session() as s:
        img = s.execute(select(Item).where(Item.kind == "image")).scalars().one()
        rel = s.execute(
            select(Relationship).where(Relationship.kind == "frame")
        ).scalars().one()
        assert rel.from_item_id == img.id and rel.to_item_id == vid_id
        meta = json.loads(rel.meta)
        assert len(meta.get("timestamps", [])) >= 1


def _moving_video(out: Path, seconds: int = 3, rate: int = 10) -> Path:
    """A clip whose picture actually CHANGES — the ordinary case, and the one a
    still picture looped into a video cannot stand in for."""
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=320x180:rate={rate}",
         "-t", str(seconds), "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )
    return out


def test_a_run_of_screenshots_becomes_a_run_of_ITEMS(lib, tmp_path: Path):
    """Frames of one film are moments, not near-duplicates of each other.

    Importing a folder of screenshots used to produce ONE item with the rest
    folded onto it as "alternative" source files: consecutive frames are
    near-duplicates by construction, so the first one made an item and every
    one after it landed on that item. Reported as "images that match frames in
    a video are skipped" — the pictures were in the library, invisibly, as
    extra files of a picture nobody was looking for.
    """
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    video = _moving_video(src / "clip.mp4")
    with db.session() as s:
        Importer(s, store, cfg).import_paths([video], ImportOptions())
        s.commit()

    shots = tmp_path / "shots"
    shots.mkdir()
    for i, at in enumerate((1.0, 1.1, 1.2, 1.3)):
        media.extract_frame(video, at).save(shots / f"shot-{i}.png")
    with db.session() as s:
        Importer(s, store, cfg).import_paths([shots], ImportOptions())
        s.commit()

    with db.session() as s:
        images = s.execute(
            select(Item).where(Item.kind == "image")).scalars().all()
        assert len(images) == 4, "one item per screenshot"
        # …and each is one FILE, not a pile of alternatives on one item.
        for img in images:
            assert _count_files(s, img.id) == 1
        # Every one of them names the film it came from.
        vid = s.execute(select(Item).where(Item.kind == "video")).scalars().one()
        linked = {r.from_item_id for r in s.execute(
            select(Relationship).where(
                Relationship.kind == "frame",
                Relationship.to_item_id == vid.id)).scalars().all()}
        assert linked == {i.id for i in images}


def _flickering_video(out: Path, tmp: Path, frames: int = 20,
                      rate: int = 10) -> Path:
    """A clip whose every frame is a DIFFERENT picture.

    `_moving_video`'s testsrc cannot stand in for this: measured, its frames
    are 4–10 bits apart, i.e. all near-duplicates of each other by the app's
    own threshold, so no rule about which moment a screenshot came from could
    be right about that clip. This is the other half of what a fixed sampling
    rate could not serve — a second holding twenty distinct pictures.
    """
    src = tmp / "flicker"
    src.mkdir()
    for i in range(frames):
        make_image(src / f"f-{i:03d}.png", seed=100 + i, size=(320, 180))
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-framerate", str(rate), "-i", str(src / "f-%03d.png"),
         "-pix_fmt", "yuv420p", "-crf", "12", str(out)],
        check=True,
    )
    return out


def test_a_screenshot_from_ANY_frame_finds_its_film(lib, tmp_path: Path):
    """Every frame is hashed, so no moment of a film is unfindable.

    Reported from a real library: two stills of one shot imported together,
    one of them landing exactly on a sample of the 2/s index (distance 0) and
    the other 22 bits from the nearest sample — well past the near-dup
    threshold. The first got its link to the film and the second got nothing.
    A film's content does not arrive at a steady rate, so no rate could have
    been the answer.
    """
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    # 10 fps: the old index sampled 2/s, so four of every five frames of this
    # clip were absent from it.
    video = _flickering_video(src / "clip.mp4", tmp_path, frames=20, rate=10)
    with db.session() as s:
        Importer(s, store, cfg).import_paths([video], ImportOptions())
        s.commit()

    shots = tmp_path / "shots"
    shots.mkdir()
    # 1.5 IS on the old 2/s grid; 1.6, 1.7 and 1.8 are the three frames after
    # it, which that grid could not hold.
    for at in (1.5, 1.6, 1.7, 1.8):
        media.extract_frame(video, at).save(shots / f"at-{at}.png")
    with db.session() as s:
        Importer(s, store, cfg).import_paths([shots], ImportOptions())
        s.commit()

    with db.session() as s:
        vid = s.execute(select(Item).where(Item.kind == "video")).scalars().one()
        linked = {}
        for r in s.execute(select(Relationship).where(
                Relationship.kind == "frame",
                Relationship.to_item_id == vid.id)).scalars().all():
            name = s.get(Item, r.from_item_id).name.rsplit("/", 1)[-1]
            linked[name] = json.loads(r.meta)["timestamps"]
        assert set(linked) == {"at-1.5.png", "at-1.6.png", "at-1.7.png",
                               "at-1.8.png"}, linked
        # …at its OWN moment: a picture matched to the frame before it would be
        # a link pointing at the wrong second of the film.
        for name, tss in linked.items():
            want = float(name[3:-4])
            assert any(abs(t - want) < 0.05 for t in tss), (name, tss)


def test_one_moment_per_appearance(lib, tmp_path: Path):
    """A picture is on screen for a while, so it matches a RUN of stored
    hashes — and one appearance is one answer, not thirty.

    Reporting every matching row would put a column of timestamps on one link
    and a row per frame in the stills list, for a picture that appears once.
    """
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    # A HELD picture: one drawing for two seconds at 20 fps, i.e. 40 frames
    # that are all the same and one row (identical hashes are one run) — then
    # a second copy of the same shot later in the film, which is a genuine
    # second moment.
    still = make_image(tmp_path / "held.png", seed=7, size=(320, 180))
    clip = src / "held.mp4"
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-loop", "1", "-i", str(still), "-t", "2", "-r", "20",
         "-pix_fmt", "yuv420p", str(clip)], check=True)
    with db.session() as s:
        Importer(s, store, cfg).import_paths([clip], ImportOptions())
        s.commit()

    with db.session() as s:
        shot = tmp_path / "shot.png"
        media.extract_frame(clip, 1.0).save(shot)
        Importer(s, store, cfg).import_paths([shot], ImportOptions())
        s.commit()
        rel = s.execute(select(Relationship).where(
            Relationship.kind == "frame")).scalars().first()
        assert rel is not None
        assert len(json.loads(rel.meta)["timestamps"]) == 1


def _clip_of_seeds(out: Path, tmp: Path, seeds: list[int], rate: int = 10) -> Path:
    """A clip of one distinct picture per frame, in the order given.

    `_flickering_video` with the seeds spelled out, so two clips can be built
    that SHARE one frame at different moments.
    """
    src = tmp / f"frames-{out.stem}"
    src.mkdir()
    for i, seed in enumerate(seeds):
        make_image(src / f"f-{i:03d}.png", seed=seed, size=(320, 180))
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-framerate", str(rate), "-i", str(src / "f-%03d.png"),
         "-pix_fmt", "yuv420p", "-crf", "12", str(out)],
        check=True,
    )
    return out


def test_a_frame_shared_BY_TWO_FILMS_links_to_both(lib, tmp_path: Path):
    """A screenshot is linked to EVERY film it is a frame of, at that film's
    own moment — not to whichever one matched best.

    A title card, a recap shot or a stock frame really is in several episodes,
    and `_match_video_frames` answers with a dict keyed by film for exactly
    that reason. Nothing else in this suite imports two films at once, so the
    loop over its entries was untested.
    """
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    shared = 500  # the picture both films hold
    # …at 0.3 s in the first film and 0.7 s in the second, so the timestamps
    # tell the two links apart.
    a = _clip_of_seeds(src / "a.mp4", tmp_path,
                       [100, 101, 102, shared, 103, 104, 105, 106, 107, 108])
    b = _clip_of_seeds(src / "b.mp4", tmp_path,
                       [200, 201, 202, 203, 204, 205, 206, shared, 207, 208])
    with db.session() as s:
        Importer(s, store, cfg).import_paths([a, b], ImportOptions())
        s.commit()

    shot = tmp_path / "shot.png"
    media.extract_frame(a, 0.3).save(shot)
    with db.session() as s:
        Importer(s, store, cfg).import_paths([shot], ImportOptions())
        s.commit()

    with db.session() as s:
        img = s.execute(
            select(Item).where(Item.kind == "image")).scalars().one()
        by_name = {}
        for r in s.execute(select(Relationship).where(
                Relationship.kind == "frame",
                Relationship.from_item_id == img.id)).scalars().all():
            film = s.get(Item, r.to_item_id)
            by_name[Path(film.name).name] = json.loads(r.meta)["timestamps"]
        assert set(by_name) == {"a.mp4", "b.mp4"}, by_name
        # Each link carries its OWN film's moment: reporting the matching
        # film's timestamp for both would put the shot at 0.3 s in a film
        # where it is not on screen until 0.7 s.
        assert any(abs(t - 0.3) < 0.05 for t in by_name["a.mp4"]), by_name
        assert any(abs(t - 0.7) < 0.05 for t in by_name["b.mp4"]), by_name


def test_the_same_screenshot_in_two_encodings_is_still_ONE_item(lib, tmp_path: Path):
    """The fold the near-dup rule exists for survives: same pixels, another
    file format, one item with two source files."""
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    video = _moving_video(src / "clip.mp4")
    with db.session() as s:
        Importer(s, store, cfg).import_paths([video], ImportOptions())
        s.commit()
    frame = media.extract_frame(video, 1.0)
    frame.save(tmp_path / "shot.png")
    frame.save(tmp_path / "shot.webp", lossless=True)
    with db.session() as s:
        Importer(s, store, cfg).import_paths(
            [tmp_path / "shot.png", tmp_path / "shot.webp"], ImportOptions())
        s.commit()
    with db.session() as s:
        img = s.execute(
            select(Item).where(Item.kind == "image")).scalars().one()
        assert _count_files(s, img.id) == 2


def test_video_frame_materialized_and_pruned_independently(lib, tmp_path: Path):
    """A matched frame is materialized as the still item's own picture, so the
    video and the still are independent on disk: deleting the video item (and
    pruning) removes only the video's folder — the frame file survives."""
    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    still = make_image(src / "still.png", seed=7, size=(320, 240))
    video = _make_video(still, src / "clip.mp4")
    with db.session() as s:
        Importer(s, store, cfg).import_paths([still], ImportOptions())
        s.commit()
    with db.session() as s:
        Importer(s, store, cfg).import_paths([video], ImportOptions())
        s.commit()

    def files_on_disk() -> int:
        return sum(1 for p in cfg.items_dir.rglob("*")
                   if p.is_file() and p.name != "item.json")

    # still + its materialized frame + the video file.
    assert files_on_disk() == 3
    with db.session() as s:
        still_item = s.execute(select(Item).where(Item.kind == "image")).scalars().one()
        frame_file = s.execute(select(File).where(
            File.item_id == still_item.id, File.source_kind == "video_frame"
        )).scalars().one()
        assert frame_file.bytes > 0 and frame_file.path.startswith("files/")
        assert store.path_of(s, frame_file).exists()

    with db.session() as s:
        video_item = s.execute(select(Item).where(Item.kind == "video")).scalars().one()
        s.delete(video_item)
        s.flush()
        # Prune removes the deleted video item's folder; the still's files stay.
        assert store.prune_all(s) >= 1
        s.commit()
    assert files_on_disk() == 2
    with db.session() as s:
        still_item = s.execute(select(Item).where(Item.kind == "image")).scalars().one()
        s.delete(still_item)
        s.flush()
        assert store.prune_all(s) >= 1
        s.commit()
    assert files_on_disk() == 0


def test_cbz_import_numbers_pages(lib, tmp_path: Path):
    cfg, db, store = lib
    # Pages out of lexical order (2, 10) to exercise natural sorting.
    pages = tmp_path / "pages"
    pages.mkdir()
    names = ["p2.png", "p10.png", "p1.png"]
    for i, nm in enumerate(names):
        make_image(pages / nm, seed=100 + i, size=(200, 300))
    cbz = tmp_path / "book.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        for nm in names:
            zf.write(pages / nm, nm)

    with db.session() as s:
        Importer(s, store, cfg).import_paths([cbz], ImportOptions())
        s.commit()
    with db.session() as s:
        seq = s.execute(select(Sequence).where(Sequence.kind == "archive")).scalars().one()
        assert seq.name == "book.cbz"
        members = s.execute(
            select(SequenceItem, Item.name)
            .join(Item, Item.id == SequenceItem.item_id)
            .where(SequenceItem.sequence_id == seq.id)
            .order_by(SequenceItem.position)
        ).all()
        ordered = [name for _si, name in members]
        # Natural order: p1, p2, p10.
        assert ordered == ["p1.png", "p2.png", "p10.png"]


def test_video_import_dedups_counts_and_reverts(lib, tmp_path: Path):
    """A video is IMPORTED like anything else: it counts in stats (so the run
    logs an import event and _revert_import can trash it), and re-importing
    the same bytes adopts the existing item instead of storing a second copy."""
    from media_compost.db import Item

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    still = make_image(src / "still.png", seed=7, size=(320, 240))
    video = _make_video(still, src / "clip.mp4")
    still.unlink()  # video-only import

    with db.session() as s:
        stats = Importer(s, store, cfg).import_paths([video], ImportOptions())
        s.commit()
        assert stats.imported == 1
        vid = s.execute(select(Item).where(Item.kind == "video")).scalars().one()
        assert stats.imported_item_ids == [vid.id]

    # Re-import: byte-identical, so no second item and no second copy.
    with db.session() as s:
        again = Importer(s, store, cfg).import_paths([video], ImportOptions())
        s.commit()
        assert again.imported == 0
        assert again.skipped_duplicate == 1
        assert _count(s, Item) == 1


def test_a_byte_identical_frame_is_answered_with_the_existing_file(
        lib, tmp_path: Path):
    """BYTE IDENTITY IS AUTHORITATIVE for a matched frame: if the encoded
    bytes already exist, the existing file — and therefore ITS item — is the
    answer, exact pixels beating nearest-hash-plus-tolerant-verify (the
    ordinary import's own precedence). This is what makes a frame child's
    ``file.item`` always the matched item by construction: the perceptual
    match and the byte check used to answer independently, and on
    near-identical items with a drifting index they could disagree — the
    link on one item, the bytes on another."""
    from media_compost.importer import ImportOptions as _IO

    cfg, db, store = lib
    src = tmp_path / "src"
    src.mkdir()
    still = make_image(src / "still.png", seed=7, size=(320, 240))
    video = _make_video(still, src / "clip.mp4")

    with db.session() as s:
        imp = Importer(s, store, cfg)
        imp.import_paths([still], _IO())
        stats = imp.import_paths([video], _IO())
        assert stats.frames_matched == 1 and stats.frames_extracted == 1
        frame_file = s.execute(
            select(File).where(File.source_kind == "video_frame")
        ).scalars().one()
        matched_item = frame_file.item_id

        # A decoy item, and the SAME decoded frame offered as if the
        # perceptual match had nominated the decoy: the answer is the
        # existing file on the matched item, and nothing is stored twice.
        decoy = Item(uid="decoy001", name="decoy", kind="image")
        s.add(decoy)
        s.flush()
        vfile = s.execute(
            select(File).where(File.item_id != matched_item,
                               File.source_kind == "stored")
        ).scalars().first()
        frames = media.extract_frames(video, [(0, 0.0)])
        before = stats.frames_extracted
        got = imp._add_video_frame_file(decoy.id, vfile.id, 0.0,
                                        frames[0])
        assert got is not None and got.id == frame_file.id
        assert got.item_id == matched_item != decoy.id
        assert imp.stats.frames_extracted == before, "nothing stored"
