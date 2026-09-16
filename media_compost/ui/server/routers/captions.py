"""HTTP for captions and their meta tags.

Thin over :mod:`media_compost.ops.captions`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from fastapi import HTTPException

from media_compost.ops import Ctx, captions as ops_captions
from ..deps import get_ctx
from ..schemas import (CaptionBulkIn, CaptionIn, CaptionRefsIn,
                       CaptionTagBody)

router = APIRouter(prefix="/api/items", tags=["captions"])

#: The most items one bulk add may name — `items._DETAILS_CAP`'s number and
#: its reason: this serves a SELECTION somebody is holding in the sidebar,
#: not a way to caption a library.
_BULK_CAP = 500


@router.post("/captions/bulk")
def add_caption_bulk(body: CaptionBulkIn, ctx: Ctx = Depends(get_ctx)):
    """The same caption onto every item named — one request, one
    transaction, and one ordinary `add_caption` event per item, so each
    reverts on its own exactly as a caption typed into one item does.

    Declared BEFORE the per-item route below: that one's second segment is
    the literal "captions", so the two cannot collide, but a reader should
    not have to work that out.
    """
    ids = list(dict.fromkeys(body.item_ids))
    if len(ids) > _BULK_CAP:
        raise HTTPException(413, f"at most {_BULK_CAP} items per request")
    made = [ops_captions.add(ctx, i, body.text, kind=body.kind).id
            for i in ids]
    return {"ids": made}


@router.post("/{item_id}/captions")
def add_caption(item_id: int, body: CaptionIn, ctx: Ctx = Depends(get_ctx)):
    c = ops_captions.add(ctx, item_id, body.text, kind=body.kind)
    return {"id": c.id}


@router.patch("/{item_id}/captions/{caption_id}")
def edit_caption(item_id: int, caption_id: int, body: CaptionIn,
                 ctx: Ctx = Depends(get_ctx)):
    ops_captions.edit(ctx, item_id, caption_id, body.text)
    return {"ok": True}


@router.delete("/{item_id}/captions/{caption_id}")
def delete_caption(item_id: int, caption_id: int,
                   ctx: Ctx = Depends(get_ctx)):
    ops_captions.remove(ctx, item_id, caption_id)
    return {"ok": True}


@router.put("/{item_id}/captions/{caption_id}/refs", response_model=list[int])
def set_caption_refs(item_id: int, caption_id: int, body: CaptionRefsIn,
                     ctx: Ctx = Depends(get_ctx)):
    """Set an instruction's reference images to exactly this list, in order.

    One endpoint for adding, removing and reordering: it is one ordered list,
    and taking the whole of it is what makes the undo "put the old one back".
    """
    return ops_captions.set_refs(ctx, item_id, caption_id, body.item_ids)


@router.post("/{item_id}/captions/{caption_id}/tags", response_model=list[str])
def add_caption_tag(item_id: int, caption_id: int, body: CaptionTagBody,
                    ctx: Ctx = Depends(get_ctx)):
    """Add a meta tag to a caption (idempotent). Returns the caption's tags."""
    return ops_captions.add_meta_tag(ctx, item_id, caption_id, body.name)


@router.delete("/{item_id}/captions/{caption_id}/tags/{name}",
               response_model=list[str])
def remove_caption_tag(item_id: int, caption_id: int, name: str,
                       ctx: Ctx = Depends(get_ctx)):
    """Remove a meta tag from a caption. The name itself stays in the
    catalog (it may still carry a comment, or be used elsewhere)."""
    return ops_captions.remove_meta_tag(ctx, item_id, caption_id, name)
