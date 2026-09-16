"""Detected text: what an OCR engine read, and the corrections people make.

Reading itself is an AI job (``jobs._apply_ocr``); this router owns
everything a person does with the result — correcting a transcription,
marking a region as not text, drawing a box by hand, reordering, deleting.

Ops-only from day one (`tests/ui/test_ops_ratchet.py` CONVERTED): the
writes live in `ops/ocr.py` with their events and attribution, and the only
`HTTPException` here is the crop GET's transport 404. Every mutating handler
returns the item's whole refreshed tree, faces' rule — one mutation is one
cache write for the client, and it is what lets the annotator write the
cache before dropping a live rectangle.
"""

from __future__ import annotations

import hashlib
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_compost import ocr as ocrlib
from media_compost.db import Item, TextRegion
from media_compost.ops import Ctx, ocr as ops_ocr
from media_compost.storage import ItemStore

from ..deps import get_ctx, get_library, get_session
from ..schemas import TextOrder, TextRegionCreate, TextRegionOut, \
    TextRegionUpdate

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


def _region_out(r: TextRegion, item_uid: str,
                children: dict[int, list[TextRegion]]) -> TextRegionOut:
    return TextRegionOut(
        id=r.id, item_id=r.item_id, item_uid=item_uid, file_id=r.file_id,
        parent_id=r.parent_id, level=r.level, ord=r.ord,
        x=r.x, y=r.y, w=r.w, h=r.h,
        quad=[[p[0], p[1]] for p in ocrlib.unpack_quad(r.quad)],
        text=r.text or "", score=r.score, lang=r.lang or "",
        models=[m for m in (r.model or "").split(",") if m],
        dismissed=bool(r.dismissed), edited=bool(r.edited),
        children=[_region_out(c, item_uid, children)
                  for c in children.get(r.id, [])],
    )


def _tree_of(s: Session, item_id: int) -> list[TextRegionOut]:
    """The ACTIVE file's text tree, top-level regions in reading order.

    Per file, the artifact rule: a reading is a fact about pixels, so an
    edited file made active answers with nothing until an engine (or a
    hand) reads it — and switching back to the old file brings its reading
    back untouched.
    """
    item = s.get(Item, item_id)
    uid = item.uid if item is not None else ""
    rows = s.execute(
        select(TextRegion).where(
            TextRegion.item_id == item_id,
            TextRegion.file_id == (item.active_file_id
                                   if item is not None else None))
        .order_by(TextRegion.ord, TextRegion.id)
    ).scalars().all()
    children: dict[int, list[TextRegion]] = {}
    for r in rows:
        if r.parent_id is not None:
            children.setdefault(r.parent_id, []).append(r)
    return [_region_out(r, uid, children) for r in rows
            if r.parent_id is None]


@router.get("/item/{item_id}", response_model=list[TextRegionOut])
def list_text(item_id: int, s: Session = Depends(get_session)):
    return _tree_of(s, item_id)


@router.post("", response_model=list[TextRegionOut])
def create_text(body: TextRegionCreate, ctx: Ctx = Depends(get_ctx)):
    region = ops_ocr.create_region(
        ctx, body.item_id, body.x, body.y, body.w, body.h,
        text=body.text, level=body.level, parent_id=body.parent_id)
    return _tree_of(ctx.session, region.item_id)


@router.patch("/{region_id}", response_model=list[TextRegionOut])
def update_text(region_id: int, body: TextRegionUpdate,
                ctx: Ctx = Depends(get_ctx)):
    quad = None
    if body.quad is not None:
        # [] clears it (the box becomes the shape); pack_quad answers "" for
        # that and for anything that is not four points.
        quad = ocrlib.pack_quad(body.quad)
    region = ops_ocr.update_region(
        ctx, region_id, text=body.text, dismissed=body.dismissed,
        x=body.x, y=body.y, w=body.w, h=body.h, quad=quad)
    return _tree_of(ctx.session, region.item_id)


@router.post("/item/{item_id}/order", response_model=list[TextRegionOut])
def reorder_text(item_id: int, body: TextOrder, ctx: Ctx = Depends(get_ctx)):
    ops_ocr.reorder_regions(ctx, item_id, body.region_ids,
                            parent_id=body.parent_id)
    return _tree_of(ctx.session, item_id)


@router.delete("/{region_id}", response_model=list[TextRegionOut])
def delete_text(region_id: int, ctx: Ctx = Depends(get_ctx)):
    item_id = ops_ocr.delete_region(ctx, region_id)
    return _tree_of(ctx.session, item_id)


@router.get("/{region_id}/crop")
def text_crop(region_id: int, w: int = Query(default=160, ge=16, le=1024),
              at: str = Query(default=""),
              s: Session = Depends(get_session),
              lib=Depends(get_library)):
    """The region as a small JPEG strip, cached beside the item's files.

    Sized by WIDTH with the height following (capped at 4×w for vertical
    text) — `face_crop`'s `thumbnail((w, w))` fits a square, and a line of
    text is 20:1, so it would come back a few pixels tall.

    `at` is the caller's copy of the geometry and is never read: a region id
    is a rowid handed on after deletion, and a day-long cache would serve
    the old crop under the new id (`face_crop`'s reasoning). The QUAD is in
    the server-side key too, not just the box — moving a rotated line by
    hand changes the crop without changing the AABB.
    """
    del at
    from PIL import Image

    region = s.get(TextRegion, region_id)
    if region is None:
        raise HTTPException(404, "text region not found")
    item = s.get(Item, region.item_id)
    file_id = region.file_id or (item.active_file_id if item else None)
    if item is None or file_id is None:
        raise HTTPException(404, "no image for this text region")
    from media_compost.db import File

    row = s.get(File, file_id)
    if row is None:
        raise HTTPException(404, "no image for this text region")
    path = lib.store.path_of(s, row)

    store: ItemStore = lib.store
    cache = store.item_dir(item.uid) / "thumbs"
    cache.mkdir(parents=True, exist_ok=True)
    stamp = f"{region.x:.4f}-{region.y:.4f}-{region.w:.4f}-{region.h:.4f}"
    if region.quad:
        stamp += "-" + hashlib.sha1(region.quad.encode()).hexdigest()[:8]
    cached = cache / f"text-{region.id}-{stamp}-{w}.jpg"
    if not cached.exists():
        with Image.open(path) as im:
            im = im.convert("RGB")
            crop = im.crop(ocrlib.crop_box(
                (region.x, region.y, region.w, region.h),
                im.width, im.height))
            crop.thumbnail((w, 4 * w))
            buf = io.BytesIO()
            crop.save(buf, "JPEG", quality=88)
            cached.write_bytes(buf.getvalue())
    return Response(cached.read_bytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})
