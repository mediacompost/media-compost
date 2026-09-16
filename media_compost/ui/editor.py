"""Image editor operations (Phase 2, first cut): rotate and crop.

Applies a transform to a source file and writes the result as a new file,
either overwriting the item (keeping the original for reference) or creating a
linked derived item. Brush/fill/lasso painting is a later increment.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Literal, Optional

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_compost import media
from media_compost.config import Config
from media_compost.db import (
    File, Item, ItemGroup, Relationship, copy_item_associations,
    next_file_number,
)
from media_compost.fileops import record_edit
from media_compost.itemmeta import index_file_metadata
from media_compost.colorkey import color_signature
from media_compost.dedup import compute_phash_image
from media_compost.storage import ItemStore, sha256_bytes

SaveMode = Literal["overwrite", "derived"]


@dataclass
class EditOps:
    # Clockwise rotation applied first, in degrees (0/90/180/270).
    rotate: int = 0
    # Crop box in the *rotated* image's pixel space (left, top, right, bottom).
    crop: Optional[tuple[int, int, int, int]] = None
    # The saved buffer's region within the *source file*, normalized to [0,1]
    # (x, y, w, h). Used to keep tag bounding boxes aligned across crops. None
    # means the whole source frame (no crop).
    crop_norm: Optional[tuple[float, float, float, float]] = None


def _apply_pixels(im: Image.Image, ops: EditOps) -> Image.Image:
    out = im.convert("RGB")
    if ops.rotate % 360:
        # PIL rotates counter-clockwise; negate for a clockwise convention.
        out = out.rotate(-ops.rotate, expand=True)
    if ops.crop:
        left, top, right, bottom = ops.crop
        left = max(0, min(left, out.width))
        right = max(left + 1, min(right, out.width))
        top = max(0, min(top, out.height))
        bottom = max(top + 1, min(bottom, out.height))
        out = out.crop((left, top, right, bottom))
    return out


def apply_edit(
    session: Session,
    store: ItemStore,
    cfg: Config,
    item_id: int,
    source_file_id: int,
    ops: EditOps,
    save_mode: SaveMode,
) -> dict:
    """Render ``ops`` onto the source file and persist per ``save_mode``."""
    item = session.get(Item, item_id)
    source = session.get(File, source_file_id)
    if not item or not source:
        raise ValueError("item or source file not found")

    src_path = store.file_path(item.uid, source.path)
    with Image.open(src_path) as im:
        sw, sh = im.width, im.height
        rendered = _apply_pixels(im, ops)
        rendered.load()
        _ext, data = media.encode_lossless(rendered)
    # Derive the normalized crop for box alignment (only when un-rotated; a
    # rotation would need the boxes rotated too, which we don't attempt here).
    if ops.crop and ops.rotate % 360 == 0 and sw and sh:
        left, top, right, bottom = ops.crop
        ops.crop_norm = (left / sw, top / sh, (right - left) / sw, (bottom - top) / sh)
    return _persist(session, store, item, source, data, save_mode, ops)


def save_raster(
    session: Session,
    store: ItemStore,
    cfg: Config,
    item_id: int,
    source_file_id: int,
    png_bytes: bytes,
    save_mode: SaveMode,
    crop_norm: Optional[tuple[float, float, float, float]] = None,
) -> dict:
    """Persist a client-rendered PNG (brush/fill/selection/angle-crop output)."""
    item = session.get(Item, item_id)
    source = session.get(File, source_file_id)
    if not item or not source:
        raise ValueError("item or source file not found")
    ops = EditOps(crop_norm=crop_norm)
    return _persist(session, store, item, source, png_bytes, save_mode, ops)


def _persist(session, store, item, source, data: bytes, save_mode, ops) -> dict:
    """Store ``data`` as a new file and wire it up per ``save_mode``."""
    from PIL import Image as _Image

    # RE-ENCODED here rather than stored as it arrived, because both callers
    # reach this with PNG bytes — one built them, the client sent the other —
    # and PNG → lossless WebP changes no pixel while the file gets smaller.
    # The picture is decoded anyway for the hash, so this costs one encode.
    # From the ORIGINAL mode, not the RGB copy below: a brush stroke saved with
    # transparency would otherwise lose its alpha on the way to disk.
    with _Image.open(io.BytesIO(data)) as im:
        im.load()
        original = im.copy()
    rendered = original.convert("RGB")
    w, h = rendered.width, rendered.height
    phash = compute_phash_image(rendered)
    ckey, csig = color_signature(rendered)
    ext, data = media.encode_lossless(original)
    digest = sha256_bytes(data)

    # The saved file's region within the item's reference frame = the source
    # file's region composed with the crop applied in the editor.
    cx, cy, cw, ch = _compose_crop(source, ops.crop_norm)

    if save_mode == "derived":
        target = Item(name=_derived_name(item.name), link_item_id=item.id)
        session.add(target)
        session.flush()
        # A COPY of the item, not a bare new one: the same tags (with their
        # groups, boxes and dates), captions, faces and who they are, places,
        # capture date, refused suggestions — and the same links. It is the
        # same picture with different pixels, so everything the library knew
        # about it is still true; starting bare would mean re-doing the work
        # that made the original worth keeping.
        copy_item_associations(session, item.id, target.id, links=True)
        rel = store.write_file(target.uid, 1, ext, data=data)
        new_file = File(
            item_id=target.id, sha256=digest, phash=phash,
            color_key=ckey, color_sig=csig, path=rel, number=1,
            width=w, height=h, bytes=len(data), format=ext,
            crop_x=cx, crop_y=cy, crop_w=cw, crop_h=ch,
            is_derived=True, derived_from_file_id=source.id,
        )
        session.add(new_file)
        session.flush()
        target.active_file_id = new_file.id
        index_file_metadata(session, store, new_file)
        # Record the directional original -> derived relationship (edit). The
        # "user" transform distinguishes an editor save from an auto-detected
        # rotation/flip so the sidebar can label it "Modified in editor".
        session.add(Relationship(
            from_item_id=item.id, to_item_id=target.id, kind="edit",
            meta=json.dumps({"transform": "user"}),
        ))
        # No commit here: this runs under ops/, whose callers own the
        # transaction (a commit mid-request would break `lib.transaction()`
        # batching and commit whatever else the caller had pending).
        session.flush()
        return {"item_id": target.id, "file_id": new_file.id, "mode": "derived"}

    if not source.is_derived:
        source.is_kept_original = True
    # A save adds a *new* file (the source is kept intact as a prior version), so
    # the source's artifacts still match it — they are not marked stale here. Only
    # an in-place pixel overwrite invalidates artifacts (see rotate_item, which
    # rotates them to keep them aligned rather than staling them).
    number = next_file_number(session, item.id)
    rel = store.write_file(item.uid, number, ext, data=data)
    new_file = File(
        item_id=item.id, sha256=digest, phash=phash,
        color_key=ckey, color_sig=csig, path=rel, number=number,
        width=w, height=h, bytes=len(data), format=ext,
        crop_x=cx, crop_y=cy, crop_w=cw, crop_h=ch,
        is_derived=True, derived_from_file_id=source.id,
    )
    session.add(new_file)
    session.flush()
    # Record the edit lineage: this new file is based on ``source`` via the
    # image-editor action, numbered stably within the item.
    record_edit(session, item.id, source, new_file, "edit")
    item.active_file_id = new_file.id
    index_file_metadata(session, store, new_file)
    session.flush()
    return {"item_id": item.id, "file_id": new_file.id, "mode": "overwrite"}


def crop_to_new_item(
    session: Session,
    store: ItemStore,
    cfg: Config,
    item_id: int,
    source_file_id: int,
    png_bytes: bytes,
    crop_norm: Optional[tuple[float, float, float, float]] = None,
) -> dict:
    """Create a brand-new item from a client-rendered crop of ``item_id`` and
    link it *back* to the original, carrying the crop region as a bounding box.

    Unlike a "derived" save (a variant of the same logical image), this is a
    standalone new item whose own reference frame is the crop. ``crop_norm`` is
    the crop's region within the source file (x, y, w, h in [0,1]); when given,
    it's composed through the source's own crop to a box on the *original*
    item's reference frame and stored on the link so the panel-style bbox icon /
    hover preview line up. A rotated crop can't be expressed as a box, so callers
    pass ``crop_norm=None`` and the link simply carries no box."""
    item = session.get(Item, item_id)
    source = session.get(File, source_file_id)
    if not item or not source:
        raise ValueError("item or source file not found")

    with Image.open(io.BytesIO(png_bytes)) as im:
        im.load()
        original = im.copy()
    rendered = original.convert("RGB")
    w, h = rendered.width, rendered.height
    phash = compute_phash_image(rendered)
    ckey, csig = color_signature(rendered)
    # Lossless re-encode of what the client rendered (see `_persist`).
    ext, data = media.encode_lossless(original)
    digest = sha256_bytes(data)

    target = Item(name=_cropped_name(item.name))
    session.add(target)
    session.flush()
    # The crop belongs to the same groups as the original.
    for gid in session.execute(
        select(ItemGroup.group_id).where(ItemGroup.item_id == item.id)
    ).scalars().all():
        session.add(ItemGroup(item_id=target.id, group_id=gid))
    rel = store.write_file(target.uid, 1, ext, data=data)
    new_file = File(
        item_id=target.id, sha256=digest, phash=phash,
        color_key=ckey, color_sig=csig, path=rel, number=1,
        width=w, height=h, bytes=len(data), format=ext,
        crop_x=0.0, crop_y=0.0, crop_w=1.0, crop_h=1.0,
        is_derived=True, derived_from_file_id=source.id,
    )
    session.add(new_file)
    session.flush()
    target.active_file_id = new_file.id
    index_file_metadata(session, store, new_file)

    meta: dict = {"transform": "user"}
    if crop_norm is not None:
        bx, by, bw, bh = _compose_crop(source, crop_norm)
        meta["boxes"] = [[round(bx, 5), round(by, 5), round(bw, 5), round(bh, 5)]]
    # Its own kind, in the panel/frame direction: derived -> source, with the
    # region on the SOURCE's frame (link boxes render in the to_item frame).
    # It used to be kind="edit", whose rows every other writer and the
    # importer's chain walk read as original -> derived — so an item with a
    # crop had the CROP adopted as its "original" (later rotations folded into
    # the crop), and a second crop made `_current_original`'s one-row read
    # raise, erroring the import of an unrelated file.
    session.add(Relationship(
        from_item_id=target.id, to_item_id=item.id, kind="crop",
        meta=json.dumps(meta),
    ))
    session.flush()
    return {"item_id": target.id, "file_id": new_file.id}


def _cropped_name(name: str) -> str:
    if "." in name:
        stem, _, ext = name.rpartition(".")
        return f"{stem}_crop.{ext}"
    return f"{name}_crop"


def _compose_crop(source: File, crop_norm) -> tuple[float, float, float, float]:
    """Region of the reference frame for a new file cropped out of ``source``.

    ``source`` already covers (crop_x, crop_y, crop_w, crop_h) of the reference
    frame; ``crop_norm`` (x, y, w, h in [0,1] of the source) narrows it further.
    """
    sx, sy, sw, sh = source.crop_x, source.crop_y, source.crop_w, source.crop_h
    if not crop_norm:
        return sx, sy, sw, sh
    x, y, w, h = crop_norm
    return sx + x * sw, sy + y * sh, w * sw, h * sh


def _derived_name(name: str) -> str:
    if "." in name:
        stem, _, ext = name.rpartition(".")
        return f"{stem}_edit.{ext}"
    return f"{name}_edit"
