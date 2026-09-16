"""Image editor endpoint: apply rotate/crop and save."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Form, UploadFile

from ...editor import EditOps
from media_compost.ops import Ctx

from ...ops import editor as ops_editor
from ..schemas import RequestModel
from ..deps import get_ctx

router = APIRouter(prefix="/api/items", tags=["editor"])


class EditRequest(RequestModel):
    source_file_id: int
    rotate: int = 0
    crop: Optional[list[int]] = None  # [left, top, right, bottom]
    save_mode: Literal["overwrite", "derived"] = "overwrite"


@router.post("/{item_id}/edit")
def edit_item(item_id: int, body: EditRequest,
              ctx: Ctx = Depends(get_ctx)):
    crop = tuple(body.crop) if body.crop and len(body.crop) == 4 else None
    ops = EditOps(
        rotate=body.rotate,
        crop=crop,  # type: ignore[arg-type]
    )
    return ops_editor.edit(ctx, item_id, body.source_file_id, ops,
                           save_mode=body.save_mode)


@router.post("/{item_id}/edit-raster")
async def edit_raster(
    item_id: int,
    image: UploadFile,
    source_file_id: int = Form(...),
    save_mode: Literal["overwrite", "derived"] = Form("overwrite"),
    crop_x: Optional[float] = Form(None),
    crop_y: Optional[float] = Form(None),
    crop_w: Optional[float] = Form(None),
    crop_h: Optional[float] = Form(None),
    ctx: Ctx = Depends(get_ctx),
):
    """Persist a fully client-rendered image (brush/fill/selection/angle-crop)."""
    data = await image.read()
    crop_norm = None
    if None not in (crop_x, crop_y, crop_w, crop_h):
        crop_norm = (crop_x, crop_y, crop_w, crop_h)
    return ops_editor.save_pixels(ctx, item_id, source_file_id, data,
                                  save_mode=save_mode, crop=crop_norm)


@router.post("/{item_id}/crop-to-item")
async def crop_to_item(
    item_id: int,
    image: UploadFile,
    source_file_id: int = Form(...),
    box_x: Optional[float] = Form(None),
    box_y: Optional[float] = Form(None),
    box_w: Optional[float] = Form(None),
    box_h: Optional[float] = Form(None),
    ctx: Ctx = Depends(get_ctx),
):
    """Create a new item from a client-rendered crop, linked back to the
    original with the crop region as a bounding box."""
    data = await image.read()
    crop_norm = None
    if None not in (box_x, box_y, box_w, box_h):
        crop_norm = (box_x, box_y, box_w, box_h)
    return ops_editor.crop_to_item(ctx, item_id, source_file_id, data,
                                   box=crop_norm)
