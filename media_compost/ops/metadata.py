"""Item-level metadata: PINNING a value to the item, and MUTING one away.

An item holds several source files and they can disagree — the same picture
re-saved with a better capture date, a scan whose EXIF says something the
original does not. What the item ANSWERS with is its active file's values plus
whatever has been promoted to the item itself, and these four ops are the two
ways to shape that:

* ``pin`` copies one file's answer onto the item, where it survives the active
  file changing, being re-encoded, or being deleted.
* ``mute`` takes one of the ACTIVE file's answers out of the set.

Together they cover both directions. A pin ADDS rather than replaces, so an
item pinned to one ISO and carrying another is found by both; muting the
active file's is how a pin becomes an override. That is why there are four
verbs here rather than two: a row you promoted is un-pinned, a row the file
gave you is muted, and neither operation can undo the other.

`index_file_metadata` — what a file says about itself — is NOT here. It is
derived state like the phash and the colour key, it writes no history, and it
takes a ``Session`` rather than a ``Ctx``; see :mod:`media_compost.itemmeta`.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from ..db import (
    File, FileMetadata, Item, ItemMetaMute, ItemMetaPin, touch_items,
)
from ..itemmeta import rebuild_item_metadata
from ..media import meta_label
from ..metadata_catalog import INTRINSIC_NAMES
from . import actions
from .context import Ctx
from .errors import Invalid, NotFound


def _item(ctx: Ctx, item_id: int) -> Item:
    item = ctx.session.get(Item, item_id)
    if item is None:
        raise NotFound("item not found")
    return item


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise Invalid("no metadata name given")
    if name in INTRINSIC_NAMES:
        # An intrinsic name is read live off the active file's own columns
        # (`prefilter._intrinsic_num_expr`), so a pin on one would show in the
        # panel and change nothing any search could see. The way to change an
        # item's width is to change which file is in charge.
        raise Invalid(
            "“{name}” is read from the active file and cannot be pinned",
            {"name": meta_label(name)},
        )
    return name


def _check_type(ctx: Ctx, name: str, mtype: str) -> None:
    """Refuse a pin that would make ONE item compare a name differently.

    `prefilter._compile_meta` branches on each row's own ``mtype``, so an
    ``iso`` pinned as text while every other item indexes it numerically makes
    a search that is right for the library and wrong for exactly the picture
    somebody curated — silently, since both branches compile.
    """
    known = ctx.session.execute(
        select(FileMetadata.mtype).where(FileMetadata.name == name).limit(1)
    ).scalars().first()
    if known and known != mtype:
        raise Invalid(
            "“{name}” is {known} everywhere else in this library",
            {"name": meta_label(name), "known": known},
        )


def pin(ctx: Ctx, item_id: int, name: str, file_id: int) -> ItemMetaPin:
    """Promote what ``file_id`` says about ``name`` onto the item.

    A file id rather than a value string, deliberately: the pin stores the
    TYPED row (numeric / text / date, plus the display string), and re-deriving
    a type from a string on the wire is how a numeric name quietly becomes a
    text one. Copying the row also makes an invented value impossible.

    Idempotent per (item, name, value) — pinning the same answer twice is one
    pin — while a DIFFERENT value for the same name is a second pin beside it,
    which is what makes "these two files disagree and both are true" sayable.
    """
    s = ctx.session
    item = _item(ctx, item_id)
    name = _check_name(name)
    f = s.get(File, file_id)
    if f is None or f.item_id != item_id:
        raise NotFound("file not found on this item")
    row = s.execute(
        select(FileMetadata).where(FileMetadata.file_id == file_id,
                                   FileMetadata.name == name)
    ).scalars().first()
    if row is None:
        raise NotFound("that file says nothing about “{name}”",
                       {"name": meta_label(name)})
    _check_type(ctx, name, row.mtype)
    existing = s.execute(
        select(ItemMetaPin).where(ItemMetaPin.item_id == item_id,
                                  ItemMetaPin.name == name,
                                  ItemMetaPin.raw == (row.raw or ""))
    ).scalars().first()
    if existing is not None:
        existing.source_file_id = file_id
        return existing
    pinned = ItemMetaPin(
        item_id=item_id, name=name, mtype=row.mtype,
        num_value=row.num_value, text_value=row.text_value, raw=row.raw or "",
        source_file_id=file_id,
    )
    s.add(pinned)
    s.flush()
    ctx.log(action=actions.PIN_METADATA, entity_type="item", entity_id=item_id,
            summary="Kept “{value}” as this item’s {name}",
            summary_vars={"value": row.raw or "", "name": meta_label(name)},
            data={"item_id": item_id, "name": name, "raw": row.raw or "",
                  "mtype": row.mtype, "num_value": row.num_value,
                  "text_value": row.text_value, "source_file_id": file_id})
    touch_items(s, [item.id])
    return pinned


def unpin(ctx: Ctx, item_id: int, name: str, raw: str = "") -> bool:
    """Take one promoted value off the item. Returns whether there was one."""
    s = ctx.session
    item = _item(ctx, item_id)
    name = _check_name(name)
    q = select(ItemMetaPin).where(ItemMetaPin.item_id == item_id,
                                  ItemMetaPin.name == name)
    if raw:
        q = q.where(ItemMetaPin.raw == raw)
    rows = list(s.execute(q).scalars().all())
    if not rows:
        return False
    for row in rows:
        # The whole row, so the revert can put back the SHAPE — the value, its
        # type and which file it came from — rather than just its existence.
        ctx.log(action=actions.UNPIN_METADATA, entity_type="item",
                entity_id=item_id,
                summary="Stopped keeping “{value}” as this item’s {name}",
                summary_vars={"value": row.raw or "",
                              "name": meta_label(name)},
                data={"item_id": item_id, "name": name, "raw": row.raw or "",
                      "mtype": row.mtype, "num_value": row.num_value,
                      "text_value": row.text_value,
                      "source_file_id": row.source_file_id})
        s.delete(row)
    s.flush()
    touch_items(s, [item.id])
    return True


def mute(ctx: Ctx, item_id: int, name: str) -> bool:
    """Stop taking ``name`` from the item's active file. Returns whether this
    changed anything.

    Per NAME rather than per value: the active file gives at most one answer
    per name, and keyed on the name the mute survives that file being
    re-encoded or another file becoming active — which is the point of an
    answer that lives on the item.
    """
    s = ctx.session
    item = _item(ctx, item_id)
    name = _check_name(name)
    if s.execute(
        select(ItemMetaMute).where(ItemMetaMute.item_id == item_id,
                                   ItemMetaMute.name == name)
    ).scalars().first() is not None:
        return False
    s.add(ItemMetaMute(item_id=item_id, name=name))
    s.flush()
    rebuild_item_metadata(s, item_id)
    ctx.log(action=actions.MUTE_METADATA, entity_type="item",
            entity_id=item_id,
            summary="Ignored the file’s {name} for this item",
            summary_vars={"name": meta_label(name)},
            data={"item_id": item_id, "name": name})
    touch_items(s, [item.id])
    return True


def unmute(ctx: Ctx, item_id: int, name: str) -> bool:
    """Take ``name`` from the active file again. Returns whether it was muted."""
    s = ctx.session
    item = _item(ctx, item_id)
    name = _check_name(name)
    row = s.execute(
        select(ItemMetaMute).where(ItemMetaMute.item_id == item_id,
                                   ItemMetaMute.name == name)
    ).scalars().first()
    if row is None:
        return False
    s.delete(row)
    s.flush()
    rebuild_item_metadata(s, item_id)
    ctx.log(action=actions.UNMUTE_METADATA, entity_type="item",
            entity_id=item_id,
            summary="Used the file’s {name} for this item again",
            summary_vars={"name": meta_label(name)},
            data={"item_id": item_id, "name": name})
    touch_items(s, [item.id])
    return True
