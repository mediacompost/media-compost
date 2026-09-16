"""Video-editor backend: create clips, capture frames, list frame markers.

Clips and captured frames are **materialized at creation**: the frame/excerpt
is extracted with ffmpeg right away and stored as a real file in the new item's
folder (``source_kind``/``source_start``/``source_end`` are kept as provenance
for the UI's "frame @ Xs" labels). Both are linked back to the original via a
directional :class:`Relationship`.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_compost.db import (
    File,
    Item,
    Job,
    Relationship,
    TrashedItem,
)
from media_compost.ops import Ctx
from media_compost.ops.errors import Invalid

from ...ops import video as ops_video
from ..schemas import RequestModel
from ..deps import get_ctx, get_current_user, get_library, get_session

router = APIRouter(tags=["video"])


class ClipIn(RequestModel):
    start: float
    end: float
    name: str | None = None


class FrameIn(RequestModel):
    timestamp: float
    name: str | None = None


class ThumbnailFrameIn(RequestModel):
    timestamp: float


class FrameMarker(BaseModel):
    item_id: int
    timestamp: float
    name: str


class Still(BaseModel):
    """A STILL of this video: an image item holding a whole frame or a crop of one."""
    item_id: int
    timestamp: float
    name: str
    # Fractions of the frame; null for a whole-frame capture.
    crop: list[float] | None = None
    width: int = 0
    height: int = 0
    # The still's active file — what `/api/files/{id}/thumb` needs.
    file_id: int | None = None


class EveryStillsIn(RequestModel):
    """An "every N seconds" run of stills. `start`/`end` are the marked range
    when there is one — omitted, the run covers the whole film."""

    every: float
    start: float = 0.0
    end: float | None = None


class CutIn(RequestModel):
    start: float
    end: float


class CropIn(RequestModel):
    x: float
    y: float
    w: float
    h: float


class SizeIn(RequestModel):
    w: int
    h: int


class VideoEditIn(RequestModel):
    """One save from the video editor: which parts of the source to keep, and
    what to do to the picture. Everything but `cuts` is optional — the editor
    only sends what was actually asked for."""

    cuts: list[CutIn]
    rotate: int = 0
    crop: CropIn | None = None
    scale: SizeIn | None = None
    fps: float | None = None
    #: Put the result in a NEW item linked back to this one, instead of adding
    #: a file to this one. The image editor's pair, in the same menu.
    new_item: bool = False


class VideoJobOut(BaseModel):
    """A render in flight for this item, or `job_id: null` for none."""

    job_id: int | None = None
    status: str = ""
    progress: int = 0
    message: str = ""


@router.post("/api/items/{item_id}/video-edit", response_model=VideoJobOut)
def enqueue_video_edit(item_id: int, body: VideoEditIn,
                       lib=Depends(get_library),
                       user: str = Depends(get_current_user)):
    """Queue the editor's cutlist as a background render.

    Queued rather than run here for the reason every long job is: encoding a
    film is minutes, and a request that holds the connection open for them
    cannot be cancelled, cannot report progress, and dies with the tab. The
    editor shows the queued job's progress and can be closed while it runs.
    """
    if not body.cuts:
        raise HTTPException(400, "the edit keeps nothing of the video")
    running = _active_video_job(lib, item_id)
    if running is not None:
        # One render per item at a time: a second would race the first for the
        # item's next file number and the active-file pointer.
        raise HTTPException(409, "this video is already being saved")
    opts = {
        "cuts": [[c.start, c.end] for c in body.cuts],
        "rotate": body.rotate,
        "crop": body.crop.model_dump() if body.crop else None,
        "scale": body.scale.model_dump() if body.scale else None,
        "fps": body.fps,
        "new_item": body.new_item,
    }
    try:
        jid = lib.jobs.enqueue_video_edit(item_id, opts, username=user)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return VideoJobOut(job_id=jid, status="queued")


@router.get("/api/items/{item_id}/video-edit", response_model=VideoJobOut)
def video_edit_status(item_id: int, s: Session = Depends(get_session)):
    """The render in flight for this item, if any.

    This is what lets the editor put its progress modal back up when the window
    is reopened mid-render: the job outlives the window, so the window asks.
    """
    job = s.execute(
        select(Job).where(Job.item_id == item_id, Job.kind == "video_edit",
                          Job.status.in_(["queued", "running"]))
        .order_by(Job.id.desc()).limit(1)
    ).scalars().first()
    if job is None:
        return VideoJobOut()
    return VideoJobOut(job_id=job.id, status=job.status,
                       progress=job.progress or 0, message=job.message or "")


def _active_video_job(lib, item_id: int):
    with lib.db.session() as s:
        return s.execute(
            select(Job.id).where(Job.item_id == item_id,
                                 Job.kind == "video_edit",
                                 Job.status.in_(["queued", "running"]))
        ).scalars().first()


@router.post("/api/items/{item_id}/clip")
def create_clip(item_id: int, body: ClipIn, ctx: Ctx = Depends(get_ctx)):
    """Cut ``[start, end]`` into a new video item."""
    new_id = ops_video.create_clip(ctx, item_id, body.start, body.end,
                                   name=body.name or "")
    return {"ok": True, "item_id": new_id}


@router.post("/api/items/{item_id}/frame")
def capture_frame(item_id: int, body: FrameIn, ctx: Ctx = Depends(get_ctx)):
    """Add the WHOLE frame at ``timestamp`` as a new image item, unless one
    already matches an existing image (in which case that item is returned)."""
    new_id, created = ops_video.capture_frame(ctx, item_id, body.timestamp,
                                              name=body.name or "")
    return {"ok": True, "item_id": new_id, "created": created}


@router.post("/api/items/{item_id}/frames", response_model=VideoJobOut)
def capture_frames_every(item_id: int, body: EveryStillsIn,
                         ctx: Ctx = Depends(get_ctx),
                         lib=Depends(get_library),
                         user: str = Depends(get_current_user)):
    """Queue a still every `every` seconds, over the marked range or the film.

    QUEUED, for the same reason a render is: each still is an ffmpeg seek plus
    a dedup probe, so a few hundred of them is minutes — a request holding the
    connection open for that could not be cancelled, could not report
    progress, and would die with the tab. The count is checked HERE, before
    anything is queued, so an interval typed with a stray zero is a 400 with a
    sentence rather than a job that starts making items.
    """
    # `Invalid` rather than an HTTPException, like the interval and count
    # refusals `every_n_moments` itself raises: one handler maps all three to
    # the same 400, and a script calling the op catches them the same way.
    moments = ops_video.every_n_moments(
        ctx, item_id, every=body.every, start=body.start, end=body.end)
    if not moments:
        raise Invalid("there are no frames in that range")
    if _active_stills_job(lib, item_id):
        # One per film at a time: two runs would race for the same moments and
        # each take the stills the other was about to.
        raise HTTPException(409, "this film is already having stills taken")
    jid = lib.jobs.enqueue_stills(
        item_id,
        {"every": body.every, "start": body.start, "end": body.end},
        username=user)
    return VideoJobOut(job_id=jid, status="queued",
                       message=f"{len(moments)} stills")


def _active_stills_job(lib, item_id: int):
    with lib.db.session() as s:
        return s.execute(
            select(Job.id).where(Job.item_id == item_id,
                                 Job.kind == "stills",
                                 Job.status.in_(["queued", "running"]))
        ).scalars().first()


@router.post("/api/items/{item_id}/thumbnail-frame")
def set_thumbnail_frame(item_id: int, body: ThumbnailFrameIn,
                        ctx: Ctx = Depends(get_ctx)):
    """Make the frame at ``timestamp`` this video's thumbnail."""
    ops_video.set_thumbnail_frame(ctx, item_id, body.timestamp)
    return {"ok": True}


@router.get("/api/items/{item_id}/stills", response_model=list[Still])
def stills(item_id: int, s: Session = Depends(get_session)):
    """Every image item captured from this video — whole frames and crops.

    Read from the `frame` relationships rather than the files, because the crop
    is provenance: the still's own file is a plain image whose frame of
    reference is the crop itself (its boxes are relative to what it shows), and
    only the link back to the video knows which part of which frame it was.
    """
    item = s.get(Item, item_id)
    if not item:
        raise HTTPException(404, "item not found")
    rows = s.execute(
        select(Relationship.from_item_id, Relationship.meta, Item.name,
               File.width, File.height, File.id)
        .join(Item, Item.id == Relationship.from_item_id)
        .join(File, File.id == Item.active_file_id, isouter=True)
        .where(
            Relationship.to_item_id == item_id, Relationship.kind == "frame",
            # A trashed still is gone from the annotator too — the link
            # survives so a restore brings it straight back.
            ~Item.id.in_(select(TrashedItem.item_id)),
        )
    ).all()
    out: list[Still] = []
    for still_id, meta, name, w, h, fid in rows:
        try:
            info = json.loads(meta) if meta else {}
        except ValueError:
            info = {}
        crop = info.get("crop")
        # One image can be the film's frame at SEVERAL moments — a repeated shot,
        # or a screenshot the importer matched to more than one frame. Each of
        # those is its own row here, so the still shows up at every moment it
        # belongs to; they all open the same item.
        times = info.get("timestamps") or []
        for t in times:
            out.append(Still(
                item_id=still_id, timestamp=float(t), name=name,
                crop=list(crop) if crop else None,
                width=w or 0, height=h or 0, file_id=fid,
            ))
    out.sort(key=lambda st: (st.timestamp, st.item_id))
    return out


@router.get("/api/items/{item_id}/frame-markers",
            response_model=list[FrameMarker])
def frame_markers(item_id: int, s: Session = Depends(get_session)):
    """Timestamps of image items captured/matched from this video (timeline)."""
    item = s.get(Item, item_id)
    if not item:
        raise HTTPException(404, "item not found")
    vf = s.get(File, item.active_file_id) if item.active_file_id else None
    if vf is None:
        return []
    rows = s.execute(
        select(File.item_id, File.source_start, Item.name)
        .join(Item, Item.id == File.item_id)
        .where(
            File.source_kind == "video_frame",
            File.source_file_id == vf.id,
        )
        .order_by(File.source_start)
    ).all()
    return [
        FrameMarker(item_id=iid, timestamp=ts or 0.0, name=name)
        for iid, ts, name in rows
    ]
