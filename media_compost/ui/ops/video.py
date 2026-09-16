"""Cutting a film up: a CLIP, and a STILL.

A still is an ordinary image ITEM — the whole frame, materialized as a real
lossless WebP, linked to the film by a `frame` relationship carrying the
timestamp. That is the whole design: a moment of a film needs tags, groups and
bounding boxes, which is exactly an image item, so there is no second tagging
model.

The link points STILL → FILM, like every other derived-from link here (a crop
to what it was cropped from, a panel to its page).

Capture goes through the SAME dedup as import: a frame that already exists as
an image is ADOPTED — linked at this moment — rather than stored twice. So a
screenshot somebody imported becomes the film's still instead of a second copy
of the pixels.

But A MOMENT IS WHAT A STILL IS, so that dedup does not get to decide whether
two frames of THIS film are one picture. Consecutive frames are near-duplicates
by construction — that is what a film is — and letting the near-dup rule answer
meant every still taken within a second collapsed onto the first, which read as
the app ignoring the frame part of the timecode. Against another moment of the
same film only an EXACT match adopts; everything else is a still of its own.
Two timestamps within half a frame ARE one moment, so pressing the button twice
is idempotent.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from media_compost import media
from media_compost.db import (
    File, Item, ItemTag, ItemTagBox, ItemTagPlacement, Relationship, Tag,
)
from media_compost.colorkey import color_signature
from media_compost.dedup import compute_phash_image, phash_to_int, verify_match
from media_compost.dedup_index import find_nearest_file
from media_compost.itemmeta import index_file_metadata
from media_compost.ops import actions, tagassign
from media_compost.ops.context import Ctx
from media_compost.ops.errors import Invalid, NotFound, OpError


class MediaFailed(OpError):
    """ffmpeg could not do it. A 500 on the wire: the request was fine."""

    status = 500


def _video_file(s, item: Item) -> File:
    """The item's active stored video file, or 400 if it isn't a video."""
    f = s.get(File, item.active_file_id) if item.active_file_id else None
    if item.kind != "video" or f is None or f.source_kind == "video_frame":
        raise Invalid("item is not a video")
    return f


def _frame_eps(frame_rate: float | None) -> float:
    """Half a frame — how near two timestamps have to be to BE one moment.

    The same window the sidebar's "At this frame" list and the inherited tags
    use, so what counts as one frame is one answer.
    """
    fps = frame_rate or 25.0
    return 0.5 / (fps if fps > 0 else 25.0)


def _link_times(row: Relationship) -> list[float]:
    """The moments a `frame` link records — always a LIST, from the first
    capture on (see `capture`), so a still kept once is a list of one."""
    try:
        info = json.loads(row.meta) if row.meta else {}
    except ValueError:
        return []
    return list(info.get("timestamps") or [])


def _frame_links(s: Session, video_id: int) -> list[Relationship]:
    return list(s.execute(
        select(Relationship).where(
            Relationship.to_item_id == video_id,
            Relationship.kind == "frame",
        )
    ).scalars().all())


def _still_at(s: Session, video_id: int, timestamp: float,
              frame_rate: float | None) -> int | None:
    """The still this film already has AT THIS FRAME, if any.

    Asked FIRST, before any pixel comparison, because it is the exact
    question: has this moment been kept? A near-dup search answers a
    different one and answers it with a single best match, so with three
    stills a second apart it would hand back whichever it liked and the
    second press of the button would mint a duplicate of a frame already
    there.
    """
    eps = _frame_eps(frame_rate)
    for row in _frame_links(s, video_id):
        if any(abs(t - timestamp) <= eps for t in _link_times(row)):
            return row.from_item_id
    return None


def _identical(a, b) -> bool:
    """The same picture to the byte — no tolerance at all."""
    return a.size == b.size and a.tobytes() == b.tobytes()


def _kept_at_other_frame(s: Session, still_id: int, video_id: int,
                         timestamp: float, frame_rate: float | None) -> bool:
    """Is this image already a still of this film, at a DIFFERENT frame?

    Read off the `frame` link's own `timestamps`, which is where the moments
    live; an image that is no still of this film at all has no such link and
    answers False, so a screenshot imported earlier is still adopted.
    """
    row = s.execute(
        select(Relationship).where(
            Relationship.from_item_id == still_id,
            Relationship.to_item_id == video_id,
            Relationship.kind == "frame",
        )
    ).scalars().first()
    if row is None:
        return False
    times = _link_times(row)
    if not times:
        return False
    eps = _frame_eps(frame_rate)
    return not any(abs(t - timestamp) <= eps for t in times)


def _link(s: Session, src_id: int, dst_id: int, kind: str, meta: dict) -> None:
    s.add(Relationship(
        from_item_id=src_id, to_item_id=dst_id, kind=kind, meta=json.dumps(meta)
    ))


def _link_frame(s: Session, video_id: int, item_id: int, meta: dict,
                *, eps: float = 1e-3) -> None:
    """Link an image to the video as one of its frames, adopting an image that
    is already in the library rather than storing the same pixels twice.

    The link points STILL → VIDEO, the way every derived-from link in the app
    points (a crop to what it was cropped from, a panel to its page) — and the
    way the importer already writes it when it matches a screenshot to a film.
    Capture used to write the same `frame` kind the other way round, so the two
    halves of one relationship disagreed about which end was which.

    A `frame` link is unique per (still, video, kind), so a still that dedups
    onto an existing image just JOINS that link: the timestamps accumulate in
    the meta, and a legacy crop keeps its rectangle alongside them.

    The FIRST link is written as a `timestamps` LIST too, not as the singular
    `timestamp` it used to be. The list was the shape only a second capture
    produced, and the sidebar reads the list — so the ordinary case, a frame
    kept once, was a link that said nothing about which frame it was. The
    singular is still the CALLER's spelling, folded here on the way in.
    """
    row = s.execute(
        select(Relationship).where(
            Relationship.from_item_id == item_id,
            Relationship.to_item_id == video_id,
            Relationship.kind == "frame",
        )
    ).scalars().first()
    if row is None:
        first = dict(meta)
        ts = first.pop("timestamp", None)
        if ts is not None:
            first["timestamps"] = [ts]
        _link(s, item_id, video_id, "frame", first)
        return
    try:
        info = json.loads(row.meta) if row.meta else {}
    except ValueError:
        info = {}
    times = _link_times(row)
    ts = meta.get("timestamp")
    # ONE FRAME IS ONE MOMENT: `eps` is half a frame where the caller knows the
    # rate. Without it two presses a millisecond apart put two entries in the
    # stills list for the picture you took once.
    if ts is not None and not any(abs(t - ts) <= eps for t in times):
        times.append(ts)
    merged = {k: v for k, v in info.items() if k not in ("timestamp", "timestamps")}
    merged["timestamps"] = sorted(times)
    if meta.get("crop") and "crop" not in merged:
        merged["crop"] = meta["crop"]
    row.meta = json.dumps(merged)



def tags_at(ctx: Ctx, item_id: int, timestamp: float, *, eps: float) -> list[str]:
    """The film's tags that cover ``timestamp`` — the sidebar's "At this frame".

    A pure TIME RANGE only (``x is null``): a box with geometry is a moving
    subject's placement or a still's own annotation and says nothing about when
    the tag applies. Negative ranges are dropped rather than carried across
    negatively: "this tag is pointedly absent from this stretch of the film" is
    a claim about the film, and repeating it on a picture cut out of it would
    be putting a tag on the still in order to say the still has not got it.
    """
    rows = ctx.session.execute(
        select(Tag.name, ItemTagBox.time_start, ItemTagBox.time_end,
               ItemTagBox.negative)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .join(ItemTagPlacement, ItemTagPlacement.item_tag_id == ItemTag.id)
        .join(ItemTagBox, ItemTagBox.placement_id == ItemTagPlacement.id)
        .where(ItemTag.item_id == item_id,
               ItemTagBox.time_start.is_not(None), ItemTagBox.x.is_(None))
    ).all()
    names: set[str] = set()
    for name, start, end, negative in rows:
        if negative:
            continue
        stop = start if end is None else end
        if start - eps <= timestamp <= stop + eps:
            names.add(name)
    return sorted(names)


def _inherit_frame_tags(ctx: Ctx, video: Item, still_id: int, timestamp: float,
                        fps: float | None) -> None:
    """Put the film's tags AT THIS MOMENT on the frame taken from it.

    A still is a picture OF that moment, so whatever the film says is on screen
    then is true of it — and typing it all again by hand is the work capturing
    a frame exists to save. Half a frame of tolerance, the same window the
    sidebar's "At this frame" list uses, so a single-frame tag is inherited by
    the still of the frame it names.

    Tags the still already carries are left alone: an adopted picture (a frame
    that dedups onto an image already in the library) has tags of its own, and
    re-assigning one would write a history event saying nothing happened.
    """
    s = ctx.session
    eps = 0.5 / fps if fps and fps > 0 else 0.02
    want = tags_at(ctx, video.id, timestamp, eps=eps)
    if not want:
        return
    have = {
        name for (name,) in s.execute(
            select(Tag.name).join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id == still_id))
    }
    for name in want:
        if name not in have:
            tagassign.assign_item_tag(ctx, still_id, name)


def set_thumbnail_frame(ctx: Ctx, item_id: int, timestamp: float) -> None:
    """Make the frame at ``timestamp`` the film's thumbnail.

    A video's thumbnail is a frame extracted at its midpoint, which is a guess
    and is often black, a logo or a title card. Which frame REPRESENTS a film
    is a judgement, and the person watching it is the one who can make it.

    It writes the cache and nothing else: a thumbnail is derived, so there is
    no row to keep in step and nothing to revert — the way back is to pick
    another frame. (`media.extract_frame` does the colour conversion a still
    gets, so the thumbnail is the picture that was on screen.)
    """
    s = ctx.session
    item = s.get(Item, item_id)
    if not item:
        raise NotFound("item not found")
    vf = _video_file(s, item)
    try:
        frame = media.extract_frame(ctx.store.path_of(s, vf), timestamp)
    except media.MediaError as exc:
        raise MediaFailed(f"frame extraction failed: {exc}") from exc
    ctx.store.set_thumb_from_image(vf.id, vf.sha256, frame)
    # The row is what every reader keys its cache off (`ItemOut.thumb_token`,
    # the thumb ETag): the bytes on disk have changed and the file they were
    # derived from has not, so nothing else would say so.
    vf.thumb_rev = int(vf.thumb_rev or 0) + 1


def create_clip(ctx: Ctx, item_id: int, start: float, end: float, *,
                name: str = "") -> int:
    """Cut ``[start, end]`` into a new video item. The excerpt is re-encoded by
    ffmpeg synchronously at creation (acceptable for clip-length excerpts) and
    stored as the new item's own file."""
    s = ctx.session
    item = s.get(Item, item_id)
    if not item:
        raise NotFound("item not found")
    vf = _video_file(s, item)
    if end <= start:
        raise Invalid("clip end must be after start")

    clip = Item(name=name or f"{item.name} [clip]", kind="video",
                link_item_id=item.id)
    s.add(clip)
    s.flush()
    video_path = ctx.store.path_of(s, vf)
    dst, rel = ctx.store.file_target(clip.uid, 1, "mp4")
    try:
        media.extract_clip(video_path, start, end, dst)
    except media.MediaError as exc:
        raise MediaFailed(f"clip extraction failed: {exc}") from exc
    from media_compost.storage import sha256_file
    cfile = File(
        item_id=clip.id, sha256=sha256_file(dst),
        path=rel, number=1, source_kind="video_clip", source_file_id=vf.id,
        source_start=start, source_end=end,
        duration=end - start, frame_rate=vf.frame_rate,
        width=vf.width, height=vf.height, bytes=dst.stat().st_size,
        format="mp4",
    )
    s.add(cfile)
    s.flush()
    clip.active_file_id = cfile.id
    index_file_metadata(s, ctx.store, cfile)
    _link(s, item.id, clip.id, "clip", {"start": start, "end": end})
    return clip.id



def capture_frame(ctx: Ctx, item_id: int, timestamp: float, *,
                  name: str = "") -> tuple[int, bool]:
    """Add the WHOLE frame at ``timestamp`` as a new image item, unless one
    already matches an existing image (in which case that item is returned).

    A still is an ordinary image item: it carries its own tags, groups and
    bounding boxes exactly like an imported picture, which is the whole point —
    annotating a moment of a film needs the same machinery as annotating a
    picture, not a second one. That is also why a still is captured WHOLE and
    never as a sub-region: cropping an image is the image editor's job, and a
    crop made there links to the still it came from, keeping the chain
    honest — crop → still → film — instead of pointing a "frame of the film" at
    a rectangle that is not one.
    """
    s = ctx.session
    item = s.get(Item, item_id)
    if not item:
        raise NotFound("item not found")
    vf = _video_file(s, item)
    # THIS MOMENT, ALREADY KEPT? Answered before a frame is even extracted:
    # pressing the button twice is idempotent, and the answer is the film's
    # own record of which frames it has stills for rather than a guess made
    # from pixels.
    kept = _still_at(s, item.id, timestamp, vf.frame_rate)
    if kept is not None:
        _link_frame(s, item.id, kept, {"timestamp": timestamp},
                    eps=_frame_eps(vf.frame_rate))
        _inherit_frame_tags(ctx, item, kept, timestamp, vf.frame_rate)
        return kept, False
    video_path = ctx.store.path_of(s, vf)
    # `keep_alpha`: a still is the one extraction that becomes a picture in
    # its own right, stored losslessly — and a transparent video read as RGB
    # is not flattened but WRONG, showing whatever colour sat under the
    # transparent pixels. The hash and the colour signature both flatten
    # alpha exactly as they do for an imported RGBA picture, so the still
    # dedups and sorts like any other image.
    frame = media.extract_frame(video_path, timestamp, keep_alpha=True)
    phash = compute_phash_image(frame)
    ckey, csig = color_signature(frame)

    # Does an existing image already match this frame? One probe of the
    # band-key columns — the same rows the importer's near-dup match reads.
    got = _find_candidate(ctx, phash_to_int(phash))
    if got is not None:
        cand, cand_dist = got
        cand_file = s.get(File, cand)
        cand_item = cand_file.item_id if cand_file is not None else None
        try:
            other = _frame_or_object(ctx, cand_file)
            same = verify_match(frame, other,
                                ctx.config.verify_mse(cand_dist))
        except (OSError, media.MediaError):
            other, same = None, True
        # AGAINST ANOTHER MOMENT OF THIS SAME FILM, ONLY AN EXACT MATCH
        # ADOPTS. Near-dup matching cannot tell two frames of a film apart
        # and never will: consecutive frames ARE near-duplicates — that is
        # what a film is. Measured on a 480×270 test clip whose only moving
        # element is a small counter block, two visibly different frames
        # came back with an IDENTICAL 256-bit phash and a whole-image MSE
        # under 1, so every still taken within a second collapsed onto the
        # first and the frame part of the timecode looked like it was being
        # thrown away.
        #
        # Exact rather than "not at all": a film built from one still
        # picture really does have byte-identical frames, and two moments of
        # it are one picture the library should hold once. So the near-dup
        # rule keeps the case it exists for (a screenshot imported earlier,
        # re-encoded and not byte-equal, becomes the film's still), and
        # loses only the case it gets wrong.
        if (same and cand_item is not None and other is not None
                and _kept_at_other_frame(s, cand_item, item.id, timestamp,
                                         vf.frame_rate)):
            same = _identical(frame, other)
        if same and cand_item is not None:
            # Adopt the image that is already here: link it to this film at
            # this moment, so a capture of an existing picture lands in the
            # stills list instead of silently doing nothing.
            _link_frame(s, item.id, cand_item, {"timestamp": timestamp},
                        eps=_frame_eps(vf.frame_rate))
            _inherit_frame_tags(ctx, item, cand_item, timestamp, vf.frame_rate)
            return cand_item, False

    # Create a new frame image item; the frame is stored as its own real file
    # (already extracted above), with video-frame provenance for the UI label.
    # THREE decimals, because two stills of one second must not be named the
    # same thing: at 30 fps consecutive frames are 0.033 s apart and two
    # decimals rounds a third of them together. Seconds rather than a
    # timecode — a timecode needs the frame rate and a formatter mirrored on
    # both sides, and this is a default NAME somebody is free to change.
    default_name = f"{item.name} @ {timestamp:.3f}s"
    new_item = Item(name=name or default_name, kind="image",
                    link_item_id=item.id)
    s.add(new_item)
    s.flush()
    # LOSSLESS, through the one encoder every render here goes through
    # (`media.encode_lossless`). A still is cut from the film once and is the
    # only copy of that moment the library will hold, so the capture may not
    # re-encode it — and it costs nothing to be careful, since lossless WebP is
    # smaller and faster than the PNG this used to write.
    ext, data = media.encode_lossless(frame)
    from media_compost.storage import sha256_bytes
    rel = ctx.store.write_file(new_item.uid, 1, ext, data=data)
    ffile = File(
        item_id=new_item.id, sha256=sha256_bytes(data),
        phash=phash, color_key=ckey, color_sig=csig,
        path=rel, number=1, source_kind="video_frame",
        source_file_id=vf.id, source_start=timestamp,
        width=frame.width, height=frame.height, bytes=len(data), format=ext,
    )
    s.add(ffile)
    s.flush()
    new_item.active_file_id = ffile.id
    index_file_metadata(s, ctx.store, ffile)
    ctx.store.ensure_thumb_from_image(ffile.id, ffile.sha256, frame)
    _link_frame(s, item.id, new_item.id, {"timestamp": timestamp},
                eps=_frame_eps(vf.frame_rate))
    # WHAT THE FILM SAYS IS ON SCREEN AT THIS MOMENT is true of the picture cut
    # out of it, so the still is given those tags rather than being left blank
    # for somebody to type them all again.
    _inherit_frame_tags(ctx, item, new_item.id, timestamp, vf.frame_rate)
    # A still joins NO sequence. Sequences are for things read in order — a
    # comic's pages, a film's extracted frames — and the handful of moments
    # somebody stopped to annotate is not that: a "sequence" of three stills
    # taken hours apart in the film only clutters the Sequences list and gives
    # each still a page number that means nothing. The frame link back to the
    # video is the whole relationship a still needs.
    return new_item.id, True



#: How many stills one "every N seconds" run may make. Not a policy on how
#: many stills a film deserves — it is a guard against an interval typed with
#: a stray zero, where the difference between 3 s and 0.03 s over a
#: 24-minute film is 480 items and 48 000. Creating items is the one thing
#: here that no single action undoes.
MAX_EVERY_STILLS = 2000


def every_n_timestamps(duration: float, every: float, *,
                       start: float = 0.0,
                       end: float | None = None,
                       frame_rate: float | None = None) -> list[float]:
    """The moments an "every N seconds" run captures, in order.

    Pure, so the rules are stated here rather than inside a job:

    * The window defaults to the whole film, and its END is the last frame
      rather than the duration — a seek to `duration` itself is past the last
      frame, and would land on whatever the decoder gives for "after the end".
    * The FIRST moment is always the window's start, so a marked range's own
      in-point is one of the stills. An interval wider than the range still
      yields that one, which is the honest answer to "every 10 s of these 4".
    * A moment is included while it is `<= end`, so a range that divides
      exactly by the interval keeps its out-point too.
    """
    if every <= 0:
        raise Invalid("the interval has to be more than zero seconds")
    last = max(0.0, duration - (1.0 / frame_rate if frame_rate else 0.0))
    lo = max(0.0, start)
    hi = last if end is None else min(end, last)
    if hi < lo:
        return []
    out: list[float] = []
    k = 0
    # Multiplied out rather than accumulated: adding 0.1 thirty times lands
    # somewhere that is not 3, and the last moment of a long range would drift
    # off the frame it names (`timelineRuler.rulerTicks`' lesson).
    while True:
        t = lo + k * every
        if t > hi + 1e-9:
            break
        out.append(round(t, 3))
        k += 1
        if len(out) > MAX_EVERY_STILLS:
            raise Invalid(
                "that is more than {max} stills — pick a longer interval or "
                "mark a shorter range", {"max": str(MAX_EVERY_STILLS)})
    return out


def every_n_moments(ctx: Ctx, item_id: int, *, every: float,
                    start: float = 0.0, end: float | None = None) -> list[float]:
    """The moments an "every N seconds" run over this film would capture.

    A READ: it resolves the film's duration and frame rate and hands back the
    list. The loop that takes the stills lives in the JOB (`jobs._run_stills`)
    rather than here, and deliberately — a run of hundreds is minutes of
    ffmpeg, so it commits per still, which an op may not do (one transaction
    around the lot would hold the write lock for all of it and lose every
    still if the last one failed). Each still is then `capture_frame`, so
    every rule that one holds — a moment already kept is not taken twice, an
    existing picture is ADOPTED rather than stored again, the film's tags at
    that moment come with it — holds here without a second implementation of
    it.
    """
    s = ctx.session
    item = s.get(Item, item_id)
    if not item:
        raise NotFound("item not found")
    vf = _video_file(s, item)
    return every_n_timestamps(float(vf.duration or 0.0), every,
                              start=start, end=end, frame_rate=vf.frame_rate)


def _find_candidate(ctx: Ctx, phash_int: int):
    """``(file id, Hamming distance)`` of the nearest stored file within the
    near-dup threshold, or None.

    One probe of the band-key columns (`dedup_index.find_nearest_file`) — the
    same rows and the same tie-break the importer's near-dup match reads, so
    a capture and an import can never disagree about which picture a frame
    already is. (This used to prefer the server's shared in-memory index
    behind a freshness guard and otherwise hydrate EVERY File row's phash per
    capture; both paths went with the index.) The distance comes back because
    the pixel bound depends on it — `Config.verify_mse`.
    """
    return find_nearest_file(ctx.session, phash_int,
                             ctx.config.phash_threshold)


def _frame_or_object(ctx: Ctx, f: File):
    from PIL import Image

    return Image.open(ctx.store.path_of(ctx.session, f)).convert("RGB")




# ---- editing a film: the cutlist ---------------------------------------------


def plan_from_options(opts: dict) -> "videoedit.Plan":
    """Read the editor's saved plan out of a job's options JSON.

    Tolerant on purpose: this crosses a process boundary (the job row) and a
    version boundary (a job queued before an upgrade), so a missing or
    malformed field means "not asked for" rather than a failed render.
    """
    from media_compost import videoedit

    cuts = []
    for pair in opts.get("cuts") or []:
        try:
            a, b = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        cuts.append((a, b))
    crop = None
    c = opts.get("crop")
    if isinstance(c, dict):
        try:
            crop = videoedit.Crop(float(c["x"]), float(c["y"]),
                                  float(c["w"]), float(c["h"]))
        except (KeyError, TypeError, ValueError):
            crop = None
    scale = None
    sc = opts.get("scale")
    if isinstance(sc, dict):
        try:
            scale = (int(sc["w"]), int(sc["h"]))
        except (KeyError, TypeError, ValueError):
            scale = None
    try:
        rotate = int(opts.get("rotate") or 0) % 360
    except (TypeError, ValueError):
        rotate = 0
    fps = opts.get("fps")
    try:
        fps = float(fps) if fps else None
    except (TypeError, ValueError):
        fps = None
    return videoedit.Plan(cuts=cuts, rotate=rotate, crop=crop, scale=scale,
                          fps=fps)


def render_edit(ctx: Ctx, item_id: int, plan, *, new_item: bool = False,
                on_progress=None, should_cancel=None) -> dict:
    """Assemble the plan into a new video file and attach it.

    Two destinations, the image editor's pair: the same item gains a file and
    that file becomes active (the source stays as a prior version), or a NEW
    item is created carrying the result and linked back as its edit. Nothing
    about the source file changes either way — a cut is never destructive.
    """
    from media_compost import videoedit
    from media_compost.db import copy_item_associations, next_file_number
    from media_compost.fileops import record_edit
    from media_compost.storage import sha256_file

    s = ctx.session
    item = s.get(Item, item_id)
    if not item:
        raise NotFound("item not found")
    vf = _video_file(s, item)
    duration = float(vf.duration or 0.0)
    cuts = videoedit.normalize_cuts(plan.cuts, duration)
    if not cuts:
        raise Invalid("the edit keeps nothing of the video")
    plan.cuts = cuts
    if videoedit.is_noop(plan, duration):
        raise Invalid("nothing to render — the video is unchanged")

    src = ctx.store.path_of(s, vf)
    audio_stream = _audio_stream(src)
    width, height = int(vf.width or 0), int(vf.height or 0)
    if not width or not height:
        info = media.probe_video(src)
        width, height = int(info.width or 0), int(info.height or 0)
    out_w, out_h = videoedit.output_size(width, height, plan)

    # RENDER FIRST, into a temp file, and only then write a single row.
    #
    # Not tidiness: the rows were created before the render, and creating them
    # opens this session's WRITE transaction — which SQLite holds for the whole
    # encode. The job's own progress writes (a separate session, once a second)
    # then piled up against a locked database and the render died reporting
    # "database is locked" after finishing the video. Nothing is written until
    # there is something to write about, which also means a failed or cancelled
    # render leaves no half-built item behind.
    #
    # The temp lives INSIDE the data dir (`render_stage_dir`), never in the
    # system temp: the finished file is MOVED into the item folder below, and
    # with the library on another volume (a NAS, an external disk) a /tmp
    # staging turns that rename into a second full copy of the whole video.
    stage_root = ctx.config.render_stage_dir
    stage_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mc_render_",
                                     dir=str(stage_root)) as td:
        tmp_out = Path(td) / "out.mp4"
        try:
            media.render_cutlist(src, tmp_out, plan, duration, width, height,
                                 audio_stream, on_progress=on_progress,
                                 should_cancel=should_cancel)
        except media.Canceled:
            raise
        except media.MediaError as exc:
            raise MediaFailed(f"video render failed: {exc}") from exc

        target = item
        if new_item:
            target = Item(name=_edited_name(item.name), kind="video",
                          link_item_id=item.id)
            s.add(target)
            s.flush()
            # A COPY of the item, like the image editor's — the same tags with
            # their time ranges, captions, subjects, links and the rest. It is
            # the same film, cut differently.
            copy_item_associations(s, item.id, target.id, links=True)
        number = 1 if new_item else next_file_number(s, target.id)
        dst, rel = ctx.store.file_target(target.uid, number, "mp4")
        shutil.move(str(tmp_out), str(dst))

    # The FULL probe: the rendered file is a new set of bytes with its own
    # codecs and tracks, and this is the one call that reads them.
    out, out_meta = media.probe_video_full(dst)
    new_file = File(
        item_id=target.id, sha256=sha256_file(dst), path=rel, number=number,
        width=out.width or out_w, height=out.height or out_h,
        duration=out.duration or videoedit.total_duration(cuts),
        frame_rate=out.frame_rate or vf.frame_rate,
        bitrate=out.bitrate, bytes=dst.stat().st_size, format="mp4",
        is_derived=True, derived_from_file_id=vf.id,
    )
    s.add(new_file)
    s.flush()
    if new_item:
        target.active_file_id = new_file.id
        _link(s, item.id, target.id, "edit", {"transform": "user"})
    else:
        record_edit(s, item.id, vf, new_file, "video_edit")
        target.active_file_id = new_file.id
    index_file_metadata(s, ctx.store, new_file, values=out_meta)
    s.flush()
    ctx.log(
        action=actions.EDIT_VIDEO, entity_type="item", entity_id=target.id,
        summary=("Edited the video into “{name}”" if new_item
                 else "Edited the video"),
        summary_vars={"name": target.name} if new_item else None,
        data={"item_id": target.id, "source_item_id": item.id,
              "file_id": new_file.id, "source_file_id": vf.id,
              "cuts": [[a, b] for a, b in cuts], "rotate": plan.rotate,
              "new_item": bool(new_item)},
    )
    return {"item_id": target.id, "file_id": new_file.id,
            "new_item": bool(new_item)}


def _audio_stream(path) -> int | None:
    """WHICH audio track the render takes: the one the container marks
    DEFAULT, else the first — and None for a silent file.

    The index is among the AUDIO streams, which is what ffmpeg's `0:a:N`
    counts. It has to be said out loud: `[0:a]` in a filter graph (and a bare
    `-c copy` with no `-map`) leaves the choice to ffmpeg's own stream
    selection, which picks the track with the MOST CHANNELS — so a film with a
    stereo original and a 5.1 dub silently rendered with the dub, whatever the
    container marked default and whatever the window was playing.
    """
    try:
        audio = [t for t in media.probe_tracks(path) if t.get("kind") == "audio"]
    except Exception:  # noqa: BLE001 - a probe failure means "assume silent"
        return None
    if not audio:
        return None
    for i, t in enumerate(audio):
        if t.get("default"):
            return i
    return 0


def _edited_name(name: str) -> str:
    if "." in name:
        stem, _, ext = name.rpartition(".")
        return f"{stem}_edit.{ext}"
    return f"{name} [edit]"
