"""Image edits that produce a file (or a new item).

The pixel work already lives in :mod:`media_compost.ui.editor`, which raises
`ValueError`. This is the thin layer that gives it a `Ctx` and turns those
into proper refusals.

That translation is worth its own module rather than a `try/except` in the
router, because the router's version mapped EVERY `ValueError` to a 404 — an
unreadable image, a missing item and a crop outside the frame all came back as
"not found". A script got the same soup.
"""

from __future__ import annotations

from typing import Optional

from ..editor import EditOps, apply_edit, crop_to_new_item, save_raster
from media_compost.db import Item
from media_compost.instance import write_lease
from media_compost.ops import actions
from media_compost.ops.context import Ctx
from media_compost.ops.errors import NotFound

__all__ = ["EditOps", "edit", "save_pixels", "crop_to_item"]


def _log_save(ctx: Ctx, item_id: int, source_file_id: int, was, out: dict,
              *, what: str) -> dict:
    """Record one editor save, with the way back.

    Two shapes, and the event says which by naming the item it produced. A
    save INTO the item adds a file and makes it active, so the undo is the
    one `set_active_file` already makes — put the previous file back, and
    leave the new one standing as a source (deleting a file is the Sources
    list's job, and is not something a revert should do behind somebody's
    back). A save that made a NEW ITEM cannot be un-generated, so its undo
    is the one every item has: it goes to the Trash, from where it comes
    back.
    """
    made = out.get("item_id")
    ctx.log(action=actions.EDIT_IMAGE, entity_type="item", entity_id=item_id,
            summary=("Cropped to a new item" if what == "crop"
                     else "Saved an edited picture"),
            data={"item_id": item_id, "source_file_id": source_file_id,
                  "file_id": out.get("file_id"),
                  "new_item_id": made if made != item_id else None,
                  "old_active_file_id": was,
                  "mode": out.get("mode") or what})
    return out


def _active(ctx: Ctx, item_id: int):
    it = ctx.session.get(Item, item_id)
    return it.active_file_id if it is not None else None


def edit(ctx: Ctx, item_id: int, source_file_id: int, ops: EditOps, *,
         save_mode: str = "overwrite") -> dict:
    """Apply a declarative edit (rotate / crop) to one of an item's files."""
    # One save is one write unit: pixels land in the item's folder and the
    # rows describing them in the same breath, and a concurrent process's
    # importer or jobs worker queues at the lease instead of interleaving.
    was = _active(ctx, item_id)
    try:
        with write_lease(ctx.config.data_dir):
            return _log_save(ctx, item_id, source_file_id, was,
                             apply_edit(ctx.session, ctx.store, ctx.config,
                                        item_id, source_file_id, ops,
                                        save_mode),
                             what="edit")
    except ValueError as exc:
        raise NotFound(str(exc), code="edit_target") from exc


def save_pixels(ctx: Ctx, item_id: int, source_file_id: int, data: bytes, *,
                save_mode: str = "overwrite",
                crop: Optional[tuple] = None) -> dict:
    """Persist a fully client-rendered image (brush / fill / angle-crop)."""
    was = _active(ctx, item_id)
    try:
        with write_lease(ctx.config.data_dir):
            return _log_save(ctx, item_id, source_file_id, was,
                             save_raster(ctx.session, ctx.store, ctx.config,
                                         item_id, source_file_id, data,
                                         save_mode, crop),
                             what="save")
    except ValueError as exc:
        raise NotFound(str(exc), code="edit_target") from exc


def crop_to_item(ctx: Ctx, item_id: int, source_file_id: int, data: bytes, *,
                 box: Optional[tuple] = None) -> dict:
    """Create a new item from a crop, linked back to the original with the
    crop region as a bounding box."""
    was = _active(ctx, item_id)
    try:
        with write_lease(ctx.config.data_dir):
            return _log_save(ctx, item_id, source_file_id, was,
                             crop_to_new_item(ctx.session, ctx.store,
                                              ctx.config, item_id,
                                              source_file_id, data, box),
                             what="crop")
    except ValueError as exc:
        raise NotFound(str(exc), code="edit_target") from exc
