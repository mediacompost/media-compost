"""Stills: a whole frame or a crop of one, captured from a video.

A still is a plain image item — that is the point of the design, since a
moment of a film has to be taggable with exactly the machinery an imported
picture already has. Only the `frame` relationship back to the video knows
which part of which frame it came from.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost import media
from media_compost.ui.config import UiConfig
from media_compost.db import File, Item, Job, Relationship, Sequence
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from media_compost.testing import make_image


@pytest.fixture
def video_client(tmp_path: Path):
    """A library holding one short video, served through the API."""
    still = make_image(tmp_path / "still.png", seed=7, size=(320, 180))
    vid = tmp_path / "clip.mp4"
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-loop", "1", "-i", str(still), "-t", "1", "-r", "5",
         "-pix_fmt", "yuv420p", str(vid)],
        check=True,
    )
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([vid], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _video_id(lib: Library) -> int:
    with lib.db.session() as s:
        item = s.execute(
            Item.__table__.select().where(Item.kind == "video")
        ).first()
        return int(item.id)


def test_a_still_is_its_own_image_item_linked_to_the_film(video_client):
    """A still is a plain image item, and its `frame` link points STILL → FILM —
    the same way a crop points at what it was cropped from, and the same way the
    importer writes it when it matches a screenshot to a film."""
    client, lib = video_client
    vid = _video_id(lib)
    body = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.4}).json()
    assert body["created"] is True
    with lib.db.session() as s:
        snap = s.get(Item, body["item_id"])
        assert snap is not None and snap.kind == "image"
        f = s.get(File, snap.active_file_id)
        assert f is not None and (f.width, f.height) == (320, 180)  # the whole frame
        rel = s.execute(select(Relationship).where(
            Relationship.kind == "frame",
            Relationship.from_item_id == snap.id)).scalars().first()
        assert rel is not None and rel.to_item_id == vid


def test_a_still_is_stored_LOSSLESSLY(video_client):
    """A still is cut from the film once and is the only copy of that moment the
    library will hold, so the capture may not re-encode it. Asserted by decoding
    what was stored and comparing it with the frame `extract_frame` hands over —
    `media.encode_lossless` is one call that could be swapped for a lossy save
    with nothing else changing, and the file size is a judgement call rather
    than a test."""
    from PIL import Image, ImageChops

    from media_compost import media

    client, lib = video_client
    vid = _video_id(lib)
    body = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.4}).json()
    with lib.db.session() as s:
        snap = s.get(Item, body["item_id"])
        f = s.get(File, snap.active_file_id)
        path = lib.store.path_of(s, f)
        src = s.get(File, s.get(Item, vid).active_file_id)
        want = media.extract_frame(lib.store.path_of(s, src), 0.4)
    assert f.format == "webp" and path.suffix == ".webp"
    with Image.open(path) as im:
        im.load()
        assert im.format == "WEBP"
        got = im.convert("RGB")
    assert ImageChops.difference(got, want.convert("RGB")).getbbox() is None


@pytest.fixture
def hdr_client(tmp_path: Path):
    """A library holding one short film TAGGED PQ/BT.2020 — an HDR source."""
    vid = tmp_path / "hdr.mp4"
    made = subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=0x808080:s=320x180:d=1:r=5",
         "-pix_fmt", "yuv420p10le", "-c:v", "libx265",
         # BOTH: the container flags alone are dropped by this muxer, so the
         # encoder has to be told as well or the file comes out untagged and
         # the test silently stops testing anything.
         "-x265-params",
         "log-level=none:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
         "-color_trc", "smpte2084", "-color_primaries", "bt2020",
         "-colorspace", "bt2020nc", str(vid)],
        capture_output=True)
    if made.returncode != 0 or not vid.exists():
        pytest.skip("this ffmpeg cannot encode HEVC 10-bit")
    if not media.color_filter_for(vid):
        pytest.skip("this ffmpeg has no zscale, or the tags did not survive")
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([vid], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


@pytest.fixture
def alpha_client(tmp_path: Path):
    """A library holding a video WITH AN ALPHA CHANNEL (qtrle/argb): opaque
    red left half, fully transparent right half — a still of it can only be
    right by keeping the transparency."""
    from PIL import Image

    src = Image.new("RGBA", (320, 240), (255, 0, 0, 255))
    for y in range(240):
        for x in range(160, 320):
            src.putpixel((x, y), (0, 255, 0, 0))
    png = tmp_path / "src.png"
    src.save(png)
    vid = tmp_path / "sticker.mov"
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-loop", "1", "-i", str(png), "-t", "1", "-r", "5",
         "-c:v", "qtrle", "-pix_fmt", "argb", str(vid)],
        check=True,
    )
    if not media.video_has_alpha(vid):
        pytest.skip("this ffmpeg cannot encode an alpha video")
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([vid], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def test_a_still_of_an_ALPHA_video_keeps_the_transparency(alpha_client):
    """A video can carry alpha (qtrle, ProRes 4444, VP9 yuva420p — stickers,
    motion graphics), and the still is the one extraction that becomes a
    picture in its own right, stored losslessly.

    Read as RGB it is not merely flattened, it is WRONG: a fully transparent
    pixel comes back as whatever colour sat under it, so this clip's still
    showed a bright green field where the player showed nothing. Two losses
    had to be fixed at once — ffmpeg's BMP is a BITMAPINFOHEADER with no
    alpha mask, so the alpha frame travels as uncompressed TIFF, and the
    reader keeps the mode instead of converting to RGB.
    """
    from PIL import Image

    client, lib = alpha_client
    vid = _video_id(lib)
    body = client.post(f"/api/items/{vid}/frame",
                       json={"timestamp": 0.4}).json()
    with lib.db.session() as s:
        snap = s.get(Item, body["item_id"])
        f = s.get(File, snap.active_file_id)
        path = lib.store.path_of(s, f)
    with Image.open(path) as im:
        im.load()
        got = im.convert("RGBA")
    assert got.getpixel((10, 10)) == (255, 0, 0, 255)
    r, g, b, a = got.getpixel((300, 10))
    assert a == 0, "the transparent half must still be transparent"


def test_a_plain_video_still_stays_RGB(video_client):
    """The flag must not widen every ordinary still: a yuv420p film has no
    alpha, and its stored still keeps the three channels it always had."""
    from PIL import Image

    client, lib = video_client
    vid = _video_id(lib)
    body = client.post(f"/api/items/{vid}/frame",
                       json={"timestamp": 0.4}).json()
    with lib.db.session() as s:
        snap = s.get(Item, body["item_id"])
        f = s.get(File, snap.active_file_id)
        path = lib.store.path_of(s, f)
    with Image.open(path) as im:
        im.load()
        assert im.mode in ("RGB", "P"), im.mode


def test_an_HDR_still_is_TONE_MAPPED_on_the_way_into_the_file(hdr_client):
    """The still has to look like the frame the player was showing.

    A stored picture carries no colour information — nothing here writes an ICC
    profile — so every viewer reads one as sRGB, whether it is a PNG or the
    WebP a still is written as now. The player, meanwhile, reads the stream's
    tags and tone-maps. So the conversion has to happen on the way in, and
    `extract_frame` does it with `color_filter_for`.

    This is the end-to-end half of `tests/core/test_frame_color.py`, which
    tests the DECISION: here a real PQ-tagged film is captured through the ops
    path and the bytes on disk are compared with the raw, unconverted decode of
    the same frame. They must differ — a still that matched the raw PQ values
    would be one nobody tone-mapped.
    """
    import subprocess as sp

    from PIL import Image, ImageChops, ImageStat

    client, lib = hdr_client
    vid = _video_id(lib)
    body = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.4}).json()
    assert body["created"] is True
    with lib.db.session() as s:
        snap = s.get(Item, body["item_id"])
        f = s.get(File, snap.active_file_id)
        stored_path = lib.store.path_of(s, f)
        src = s.get(File, s.get(Item, vid).active_file_id)
        src_path = lib.store.path_of(s, src)

    # Still lossless, still WebP — the transition did not cost the conversion.
    assert f.format == media.LOSSLESS_EXT
    with Image.open(stored_path) as im:
        im.load()
        stored = im.convert("RGB")
    assert ImageChops.difference(
        stored, media.extract_frame(src_path, 0.4).convert("RGB")).getbbox() is None

    # The same frame with NO colour conversion at all, which is what the file
    # would hold if the filter had been dropped anywhere along the way.
    raw = sp.run([media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                  "-ss", "0.400", "-i", str(src_path), "-frames:v", "1",
                  "-f", "image2", "-c:v", "png", "-"], capture_output=True)
    assert raw.returncode == 0 and raw.stdout
    import io as _io
    with Image.open(_io.BytesIO(raw.stdout)) as im:
        untouched = im.convert("RGB")
    gap = abs(ImageStat.Stat(stored).mean[0] - ImageStat.Stat(untouched).mean[0])
    assert gap > 8, f"the stored still looks unconverted (mean gap {gap:.1f})"


def test_a_crop_cannot_be_captured_from_the_annotator(video_client):
    """Cropping is the image editor's job, on the still. Keeping it out of the
    capture keeps the chain honest — crop → still → film — instead of pointing a
    "frame of the film" at a rectangle that is not one."""
    client, lib = video_client
    vid = _video_id(lib)
    # The field is REFUSED, not ignored. It used to be dropped silently, which
    # is the same failure the crop was asking to avoid: a caller asking for a
    # rectangle and getting the whole frame back with nothing said.
    refused = client.post(f"/api/items/{vid}/frame",
                          json={"timestamp": 0.4, "crop": [0.25, 0.25, 0.5, 0.5]})
    assert refused.status_code == 422 and "crop" in refused.text

    # Capturing the same moment without it gives the WHOLE frame.
    body = client.post(f"/api/items/{vid}/frame",
                       json={"timestamp": 0.4}).json()
    with lib.db.session() as s:
        f = s.get(File, s.get(Item, body["item_id"]).active_file_id)
        assert (f.width, f.height) == (320, 180)
    assert client.get(f"/api/items/{vid}/stills").json()[0]["crop"] is None


def test_stills_list_reports_the_time(video_client):
    client, lib = video_client
    vid = _video_id(lib)
    client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.2})
    rows = client.get(f"/api/items/{vid}/stills").json()
    assert [round(r["timestamp"], 1) for r in rows] == [0.2]
    assert rows[0]["width"] == 320 and rows[0]["crop"] is None


def test_a_still_joins_no_sequence(video_client):
    """Sequences are for things read in order. A handful of moments somebody
    stopped to annotate is not that — the frame link back to the video is the
    whole relationship a still needs."""
    client, lib = video_client
    vid = _video_id(lib)
    # ONE still. This used to capture twice — the second with a `crop` at the
    # same timestamp — and since the crop was silently dropped both calls
    # deduped onto one item, so the second assertion re-checked the first.
    # (Two timestamps would not fix it either: the fixture's video is a looped
    # still, so every frame is the same pixels and adopts the same item.)
    snap = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.2}).json()
    with lib.db.session() as s:
        assert s.get(Item, snap["item_id"]).main_sequence_id is None
        assert s.execute(select(Sequence).where(Sequence.kind == "video")).first() is None


def test_a_trashed_still_leaves_the_list(video_client):
    client, lib = video_client
    vid = _video_id(lib)
    snap = client.post(f"/api/items/{vid}/frame",
                       json={"timestamp": 0.4}).json()
    assert len(client.get(f"/api/items/{vid}/stills").json()) == 1
    client.post("/api/items/trash", json={"item_ids": [snap["item_id"]]})
    assert client.get(f"/api/items/{vid}/stills").json() == []
    # The link survives, so restoring brings it straight back.
    client.post("/api/items/restore", json={"item_ids": [snap["item_id"]]})
    assert len(client.get(f"/api/items/{vid}/stills").json()) == 1


def test_capturing_the_same_whole_frame_twice_adopts_the_first_still(video_client):
    client, lib = video_client
    vid = _video_id(lib)
    a = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.4}).json()
    b = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.4}).json()
    # The second capture dedups onto the first: same item, nothing created.
    assert b["item_id"] == a["item_id"] and b["created"] is False
    rows = client.get(f"/api/items/{vid}/stills").json()
    assert [r["item_id"] for r in rows] == [a["item_id"]]


def test_an_image_already_in_the_library_is_adopted_as_a_still(video_client, tmp_path):
    """The point of running captures through the dedup: a screenshot imported
    earlier becomes the film's still rather than a second copy of the pixels."""
    client, lib = video_client
    vid = _video_id(lib)
    # Import the exact frame as a standalone image first.
    with lib.db.session() as s:
        video = s.get(Item, vid)
        path = lib.store.path_of(s, s.get(File, video.active_file_id))
    shot = tmp_path / "shot.png"
    media.extract_frame(path, 0.4).save(shot)
    before = len(client.get("/api/items?limit=500").json()["items"])
    with lib.db.session() as s:
        Importer(s, lib.store, lib.config).import_paths([shot], ImportOptions())
    imported = len(client.get("/api/items?limit=500").json()["items"])
    assert imported == before + 1

    r = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.4}).json()
    assert r["created"] is False
    # No new item — the imported image itself is now the film's still.
    assert len(client.get("/api/items?limit=500").json()["items"]) == imported
    rows = client.get(f"/api/items/{vid}/stills").json()
    # One link, shared with the importer's own frame matches: the same image is
    # the film's still at every moment it was matched at, listed once per moment.
    assert {r2["item_id"] for r2 in rows} == {r["item_id"]}


def test_two_moments_are_two_stills_however_alike_they_look(video_client):
    """The frame is what a still IS, so a different one is a different still.

    Near-dup matching cannot tell two frames of a film apart — consecutive
    frames ARE near-duplicates — so for as long as it decided this, every
    still taken within a second collapsed onto the first one and the frame
    part of the timecode looked like it was being thrown away. This clip is
    one still picture looped, i.e. the hardest case: even here the encoder's
    own noise means the two frames are not the same picture, and each moment
    somebody stopped at gets a still of its own.
    """
    client, lib = video_client
    vid = _video_id(lib)
    a = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.2}).json()
    b = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.8}).json()
    assert a["item_id"] != b["item_id"] and b["created"] is True
    rows = client.get(f"/api/items/{vid}/stills").json()
    assert [round(r["timestamp"], 1) for r in rows] == [0.2, 0.8]
    assert {r["item_id"] for r in rows} == {a["item_id"], b["item_id"]}


def test_two_frames_of_ONE_SECOND_are_two_stills(video_client):
    """The report this rule came from: "it should be possible to take stills
    of different frames within the same second"."""
    client, lib = video_client
    vid = _video_id(lib)
    # 5 fps, so 0.2 apart is frame by frame.
    made = [client.post(f"/api/items/{vid}/frame", json={"timestamp": ts}).json()
            for ts in (0.2, 0.4, 0.6)]
    assert len({m["item_id"] for m in made}) == 3
    rows = client.get(f"/api/items/{vid}/stills").json()
    assert [round(r["timestamp"], 1) for r in rows] == [0.2, 0.4, 0.6]


def test_the_same_frame_asked_for_twice_is_the_same_still(video_client):
    """…and idempotent to the FRAME, not to the float: a second press a
    thousandth of a second later is the same moment, and adds no second
    timestamp to the link."""
    client, lib = video_client
    vid = _video_id(lib)
    a = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.4}).json()
    b = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.401}).json()
    assert b["item_id"] == a["item_id"] and b["created"] is False
    rows = client.get(f"/api/items/{vid}/stills").json()
    assert [round(r["timestamp"], 2) for r in rows] == [0.4]


def test_capture_probes_the_same_rows_the_importer_matches(video_client):
    """`_find_candidate` is one probe of the band-key columns — the same rows
    and the same tie-break the importer's near-dup match reads, so a capture
    and an import can never disagree about which picture a frame already is.
    (This used to be a shared in-memory index behind a freshness guard, with
    a per-capture O(library) scan as the fallback; both paths are gone.)"""
    from media_compost.dedup import compute_phash, find_similar, phash_to_int
    from media_compost.ops.context import Ctx
    from media_compost.ui.ops.video import _find_candidate

    client, lib = video_client
    img = make_image(lib.config.data_dir.parent / "probe.png", seed=7,
                     size=(320, 180))
    with lib.db.session() as s:
        Importer(s, lib.store, lib.config).import_paths([img], ImportOptions())
        s.commit()
    probe = phash_to_int(compute_phash(img))

    with lib.db.session() as s:
        ctx = Ctx(session=s, _store=lib.store, _config=lib.config)
        got = _find_candidate(ctx, probe)
        assert got is not None, "the imported image is its own best match"
        # The flat scan is the oracle: same nearest, same tie-break. The
        # DISTANCE rides along with the id (it picks the pixel bound —
        # `Config.verify_mse`), so only the id is the oracle's to answer.
        fid, distance = got
        rows = s.execute(select(File.id, File.phash)
                         .where(File.phash.is_not(None))).all()
        assert fid == find_similar(
            probe, [(fid2, phash_to_int(ph)) for fid2, ph in rows],
            lib.config.phash_threshold)
        assert distance == 0, "its own hash is zero bits away"


# ---- what a still inherits from the frame it was cut out of -----------------

def _tag_range(client, item_id: int, name: str, start: float,
               end: float | None, *, negative: bool = False):
    """Give the film a tag over a stretch of itself — a pure time range."""
    r = client.post(
        f"/api/tags/assign/item/{item_id}/box",
        json={"tag": name, "box": {
            "x": None, "y": None, "w": None, "h": None,
            "time_start": start, "time_end": end, "negative": negative}},
    )
    assert r.status_code == 200, r.text
    return r


def _tags_of(client, item_id: int) -> set[str]:
    detail = client.get(f"/api/items/{item_id}").json()
    return {i["name"] for i in detail["tag_instances"]}


def test_a_still_inherits_the_film_s_tags_at_that_moment(video_client):
    """A still is a picture OF that moment, so what the film says is on screen
    then is true of it — and typing it all again by hand is exactly the work
    capturing a frame exists to save."""
    client, lib = video_client
    vid = _video_id(lib)
    _tag_range(client, vid, "harbour", 0.0, 0.5)
    _tag_range(client, vid, "night", 0.6, 1.0)

    # Only what covers THIS moment: `night` starts after it.
    body = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.2}).json()
    assert _tags_of(client, body["item_id"]) == {"harbour"}


def test_a_negative_stretch_is_not_inherited(video_client):
    """"This tag is pointedly absent here" is a claim about the FILM. Carrying
    it across would put a tag on the still in order to say the still has not
    got it."""
    client, lib = video_client
    vid = _video_id(lib)
    _tag_range(client, vid, "narrator", 0.0, 0.5, negative=True)
    body = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.2}).json()
    assert _tags_of(client, body["item_id"]) == set()


def test_an_adopted_still_gains_the_moment_s_tags_without_losing_its_own(
        video_client, tmp_path):
    """Capturing a frame that is already in the library adopts that picture.
    It keeps whatever it was tagged with and gains what the film says about the
    moment it has just been linked to.

    Driven through an IMPORTED picture rather than a second capture: another
    frame of this film is a still of its own now, and adopting a picture the
    library already has is the case the near-dup match exists for.
    """
    client, lib = video_client
    vid = _video_id(lib)
    with lib.db.session() as s:
        video = s.get(Item, vid)
        path = lib.store.path_of(s, s.get(File, video.active_file_id))
    shot = tmp_path / "shot.png"
    media.extract_frame(path, 0.4).save(shot)
    with lib.db.session() as s:
        Importer(s, lib.store, lib.config).import_paths([shot], ImportOptions())
    imported = client.get("/api/items?limit=500").json()["items"][0]["id"]
    kept = client.post(f"/api/tags/assign/item/{imported}",
                       json={"tag": "keeper"})
    assert kept.status_code == 200, kept.text
    _tag_range(client, vid, "harbour", 0.0, 0.5)

    again = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.4}).json()
    assert again["created"] is False and again["item_id"] == imported
    assert _tags_of(client, imported) == {"keeper", "harbour"}


def test_a_frame_link_names_its_moment_from_the_very_first_capture(video_client):
    """The list shape, not the singular one a SECOND capture used to produce:
    the sidebar reads `timestamps`, so a frame kept once said nothing at all
    about which frame it was."""
    import json as _json

    client, lib = video_client
    vid = _video_id(lib)
    body = client.post(f"/api/items/{vid}/frame", json={"timestamp": 0.4}).json()
    with lib.db.session() as s:
        rel = s.execute(select(Relationship).where(
            Relationship.kind == "frame",
            Relationship.from_item_id == body["item_id"])).scalars().first()
        meta = _json.loads(rel.meta)
    assert [round(t, 1) for t in meta["timestamps"]] == [0.4]
    assert "timestamp" not in meta


# ---- every N seconds --------------------------------------------------------


def _finished(lib, job_id: int, timeout: float = 60.0) -> str:
    """Wait for the queue's worker to finish `job_id`, and return its message."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with lib.db.session() as s:
            job = s.get(Job, job_id)
            if job is not None and job.status not in ("queued", "running"):
                assert job.status == "done", f"{job.status}: {job.message}"
                return job.message or ""
        time.sleep(0.05)
    raise AssertionError("the stills job never finished")


def test_every_n_timestamps_states_the_rule(video_client):
    """The moments an "every N seconds" run takes, as arithmetic — no film, no
    ffmpeg, so the rules are stated rather than inferred from a run."""
    from media_compost.ops.errors import Invalid
    from media_compost.ui.ops.video import (MAX_EVERY_STILLS,
                                            every_n_timestamps)

    # The window's START is always taken, and the END is inclusive when it
    # divides exactly — a marked range keeps both of its own points.
    assert every_n_timestamps(10.0, 2.0, start=2.0, end=6.0) == [2.0, 4.0, 6.0]
    # An interval wider than the range still yields its start, which is the
    # honest answer to "every 10 s of these 4".
    assert every_n_timestamps(10.0, 10.0, start=2.0, end=6.0) == [2.0]
    # THE WHOLE FILM ENDS AT ITS LAST FRAME, not at its duration: a seek to
    # `duration` is past the end, where the decoder answers with whatever it
    # likes.
    assert every_n_timestamps(10.0, 5.0, frame_rate=25) == [0.0, 5.0]
    assert every_n_timestamps(10.0, 4.0, frame_rate=25) == [0.0, 4.0, 8.0]
    # A range beyond the film is empty rather than an error — a marked range
    # can outlive the file it was marked on.
    assert every_n_timestamps(10.0, 1.0, start=20.0) == []
    with pytest.raises(Invalid):
        every_n_timestamps(10.0, 0)
    # An interval typed with a stray zero is refused rather than turned into
    # tens of thousands of items.
    with pytest.raises(Invalid):
        every_n_timestamps(float(MAX_EVERY_STILLS) * 2, 1.0)


def test_a_still_every_n_seconds_over_the_marked_range(tmp_path: Path):
    """The whole path: the endpoint queues a job, the job takes one still per
    moment, and each is an ordinary image item linked at its own timestamp.

    A FLICKERING clip, not the fixture's held one: every frame of that is the
    same picture, so a run over it would adopt onto the first still and prove
    nothing about the count.
    """
    src = tmp_path / "frames"
    src.mkdir()
    for i in range(20):
        make_image(src / f"f-{i:03d}.png", seed=100 + i, size=(320, 180))
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-framerate", "10", "-i", str(src / "f-%03d.png"),
         "-pix_fmt", "yuv420p", "-crf", "12", str(clip)], check=True)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([clip], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    try:
        with TestClient(app) as client:
            vid = _video_id(lib)
            r = client.post(f"/api/items/{vid}/frames",
                            json={"every": 0.5, "start": 0.0, "end": 1.0})
            assert r.status_code == 200, r.text
            assert r.json()["message"] == "3 stills"
            # WAITED FOR rather than run by hand: `enqueue_stills` wakes the
            # queue's own worker, so a `run_one` beside it is a second runner
            # racing the first — both take the same moment and the film ends
            # up with two stills of it (seen while writing this).
            assert _finished(lib, r.json()["job_id"]) == "3 stills"
            stills = client.get(f"/api/items/{vid}/stills").json()
            assert [round(st["timestamp"], 1) for st in stills] == [0.0, 0.5, 1.0]
            # Ordinary image items, exactly as a hand-taken still is.
            with lib.db.session() as s:
                for st in stills:
                    assert s.get(Item, st["item_id"]).kind == "image"
            # Running it again over the same range takes NOTHING new: each
            # moment is already kept, which `capture_frame` answers from the
            # film's own record rather than from pixels.
            r2 = client.post(f"/api/items/{vid}/frames",
                             json={"every": 0.5, "start": 0.0, "end": 1.0})
            assert _finished(lib, r2.json()["job_id"]) == \
                "0 new stills, 3 already in the library"
            assert len(client.get(f"/api/items/{vid}/stills").json()) == 3
    finally:
        app.dependency_overrides.clear()


def test_an_impossible_interval_is_refused_before_anything_is_queued(video_client):
    """A 400 with a sentence, not a job that starts making items."""
    client, lib = video_client
    vid = _video_id(lib)
    assert client.post(f"/api/items/{vid}/frames", json={"every": 0}).status_code == 400
    assert client.post(f"/api/items/{vid}/frames",
                       json={"every": 1, "start": 900}).status_code == 400
    with lib.db.session() as s:
        assert s.execute(select(Job)).scalars().all() == []
