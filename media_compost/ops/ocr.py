"""Detected text: the regions an OCR engine read (or a hand drew), and what
they say.

A region is **evidence, not an edit** — the reconciliation rule that makes a
re-run safe lives in the pure core :mod:`media_compost.ocr`. This module is
the writing half: correcting a transcription, dismissing a false positive,
moving a box, drawing one, deleting one, reordering.

Two rules the reverts lean on and nothing else states:

* **``edited`` travels on the edit event** (``old_edited``): a machine's
  reading restored as an *edited* one would be immune to the next run that
  reads it better, and an edit restored as un-edited would be silently
  overwritten by one — the exact analogue of ``unname_face`` carrying
  ``assigned_by``.
* **A delete event carries the whole SUBTREE, and no ids.** Deleting a block
  CASCADEs its lines and words away; without the tree the undo puts back a
  block with no lines, and with ids it restores under rowids SQLite may have
  handed on (the ``FaceRejection`` lesson).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, true as sa_true

from ..db import Item, TextRegion, chunked, touch_items
from . import actions
from .context import Ctx
from .errors import Invalid, NotFound

LEVELS = ("block", "line", "word", "char")


# ---- reads the writers need -------------------------------------------------


def _active_file_id(session, item_id: int):
    item = session.get(Item, item_id)
    return item.active_file_id if item is not None else None


def blocks_of(ctx: Ctx, item_id: int) -> list[TextRegion]:
    """The active file's top-level regions, in reading order."""
    return list(ctx.session.execute(
        select(TextRegion).where(
            TextRegion.item_id == item_id,
            TextRegion.parent_id.is_(None),
            TextRegion.file_id == _active_file_id(ctx.session, item_id))
        .order_by(TextRegion.ord, TextRegion.id)
    ).scalars().all())


def children_of(session, region_ids: list[int]) -> dict[int, list[TextRegion]]:
    """``{parent id: [child, ...]}`` in reading order. Takes a Session rather
    than a `Ctx` — a pure read, and the router's list-building calls it
    without one (`appearances_of`'s rule)."""
    out: dict[int, list[TextRegion]] = {}
    if not region_ids:
        return out
    for chunk in chunked(region_ids):
        for row in session.execute(
            select(TextRegion).where(TextRegion.parent_id.in_(chunk))
            .order_by(TextRegion.ord, TextRegion.id)
        ).scalars().all():
            out.setdefault(row.parent_id, []).append(row)
    return out


def subtree(session, region_id: int) -> Optional[dict]:
    """One region and everything under it, as plain nested data with NO ids —
    the shape a delete event stores and its revert recreates from."""
    row = session.get(TextRegion, region_id)
    if row is None:
        return None

    def as_dict(r: TextRegion) -> dict:
        kids = session.execute(
            select(TextRegion).where(TextRegion.parent_id == r.id)
            .order_by(TextRegion.ord, TextRegion.id)
        ).scalars().all()
        return {
            "level": r.level, "ord": r.ord,
            "box": [r.x, r.y, r.w, r.h], "quad": r.quad,
            "text": r.text, "score": r.score, "lang": r.lang,
            "model": r.model, "dismissed": bool(r.dismissed),
            "edited": bool(r.edited),
            "children": [as_dict(c) for c in kids],
        }

    return as_dict(row)


def restore_subtree(session, item_id: int, tree: dict,
                    parent_id: Optional[int] = None,
                    file_id: Optional[int] = None) -> TextRegion:
    """Recreate a :func:`subtree` snapshot. New rows, new ids — the caller
    (a revert, the sidecar restore) never expects the old ones back."""
    row = TextRegion(
        item_id=item_id, file_id=file_id, parent_id=parent_id,
        level=tree.get("level", "block"), ord=int(tree.get("ord", 0)),
        x=float(tree["box"][0]), y=float(tree["box"][1]),
        w=float(tree["box"][2]), h=float(tree["box"][3]),
        quad=tree.get("quad", ""), text=tree.get("text", ""),
        score=tree.get("score"), lang=tree.get("lang", ""),
        model=tree.get("model", ""),
        dismissed=bool(tree.get("dismissed", False)),
        edited=bool(tree.get("edited", False)),
    )
    session.add(row)
    session.flush()
    for child in tree.get("children", []):
        restore_subtree(session, item_id, child, parent_id=row.id,
                        file_id=file_id)
    return row


# ---- writers ----------------------------------------------------------------


def create_region(ctx: Ctx, item_id: int, x: float, y: float, w: float,
                  h: float, *, text: str = "", level: str = "block",
                  parent_id: Optional[int] = None) -> TextRegion:
    """A region drawn by hand — no engine, so no score and no model credit."""
    s = ctx.session
    item = s.get(Item, item_id)
    if item is None:
        raise NotFound("item not found", code="item_not_found")
    if item.active_file_id is None:
        # A reading is a fact about pixels, and this item has none of its
        # own — a region here would belong to no file and never be shown.
        raise Invalid("this item has no picture to read text off",
                      code="no_text_file")
    if level not in LEVELS:
        raise Invalid("that is not a text level", code="bad_text_level")
    parent = None
    if parent_id is not None:
        parent = s.get(TextRegion, parent_id)
        if parent is None or parent.item_id != item_id:
            raise NotFound("text region not found", code="text_not_found")
    # At the end of its sibling run: the reading order is the engine's where
    # there was an engine, and last is the only honest place for a late
    # addition (reordering exists for the rest). Siblings are the ACTIVE
    # file's — another file's regions are another reading.
    siblings = s.execute(
        select(TextRegion.ord).where(
            TextRegion.item_id == item_id,
            TextRegion.file_id == item.active_file_id,
            TextRegion.parent_id.is_(None) if parent_id is None
            else TextRegion.parent_id == parent_id)
    ).scalars().all()
    region = TextRegion(item_id=item.id, file_id=item.active_file_id,
                        parent_id=parent_id, level=level,
                        ord=(max(siblings) + 1 if siblings else 0),
                        x=x, y=y, w=w, h=h, text=text)
    s.add(region)
    s.flush()
    ctx.log(action=actions.ADD_TEXT, entity_type="item", entity_id=item.id,
            summary="Added a text box by hand",
            data={"item_id": item.id, "region_id": region.id,
                  "parent_id": parent_id})
    touch_items(s, [item.id])
    return region


def update_region(ctx: Ctx, region_id: int, *, text: Optional[str] = None,
                  dismissed: Optional[bool] = None,
                  x=None, y=None, w=None, h=None,
                  quad: Optional[str] = None) -> TextRegion:
    """Correct a region's text, dismiss it, or move its box. One mutator for
    the three because they arrive from one PATCH — and each logs its own
    event, `update_face`'s rule."""
    s = ctx.session
    region = s.get(TextRegion, region_id)
    if region is None:
        raise NotFound("text region not found", code="text_not_found")

    if text is not None and text != region.text:
        old_text, old_edited = region.text, bool(region.edited)
        region.text = text
        # The claim this flag makes is "a person said WHAT" — after this, no
        # run may rewrite the string (ocr.reconcile reads it).
        region.edited = True
        ctx.log(action=actions.EDIT_TEXT, entity_type="item",
                entity_id=region.item_id,
                summary="Corrected a text block",
                data={"item_id": region.item_id, "region_id": region.id,
                      "text": text, "old_text": old_text,
                      "edited": True, "old_edited": old_edited})

    if dismissed is not None and dismissed != bool(region.dismissed):
        region.dismissed = dismissed
        ctx.log(action=actions.DISMISS_TEXT, entity_type="item",
                entity_id=region.item_id,
                summary=("Marked a region as not text" if dismissed
                         else "Restored a dismissed text region"),
                data={"item_id": region.item_id, "region_id": region.id,
                      "dismissed": dismissed})

    old_box = [region.x, region.y, region.w, region.h]
    old_quad = region.quad
    for name, value in (("x", x), ("y", y), ("w", w), ("h", h)):
        if value is not None:
            setattr(region, name, value)
    if quad is not None:
        region.quad = quad
    box = [region.x, region.y, region.w, region.h]
    if box != old_box or region.quad != old_quad:
        # The quad travels on the event, or undoing a moved rotated line
        # puts back an upright rectangle — silently.
        ctx.log(action=actions.MOVE_TEXT, entity_type="item",
                entity_id=region.item_id, summary="Moved a text box",
                data={"item_id": region.item_id, "region_id": region.id,
                      "box": box, "old_box": old_box,
                      "quad": region.quad, "old_quad": old_quad})
    s.flush()
    touch_items(s, [region.item_id])
    return region


def delete_region(ctx: Ctx, region_id: int) -> int:
    """Remove a region and everything under it; returns the item it was on.

    Prefer dismissing a detected false positive — a deleted region comes
    straight back on the next run."""
    s = ctx.session
    region = s.get(TextRegion, region_id)
    if region is None:
        raise NotFound("text region not found", code="text_not_found")
    item_id = region.item_id
    ctx.log(action=actions.DELETE_TEXT, entity_type="item",
            entity_id=item_id,
            summary="Deleted a text region",
            data={"item_id": item_id, "region_id": region.id,
                  "parent_id": region.parent_id, "ord": region.ord,
                  # WHICH FILE the reading was of, or the revert restores it
                  # onto whatever file is active by then and it shows on the
                  # wrong pixels.
                  "file_id": region.file_id,
                  # The whole subtree, with no ids: the CASCADE takes the
                  # children down with the row, and the revert restores the
                  # SHAPE under fresh rowids.
                  "tree": subtree(s, region.id)})
    s.delete(region)
    s.flush()
    touch_items(s, [item_id])
    return item_id


def reorder_regions(ctx: Ctx, item_id: int, region_ids: list[int], *,
                    parent_id: Optional[int] = None) -> list[TextRegion]:
    """Set one sibling run's reading order — the FULL desired order, so add /
    remove / reorder is one op and one revert (`set_refs`' rule)."""
    s = ctx.session
    item = s.get(Item, item_id)
    if item is None:
        raise NotFound("item not found", code="item_not_found")
    # A top-level sibling run is the ACTIVE file's — the caller reordered
    # the list it can see, and another file's regions are another reading.
    # Children need no file clause: they share their parent's file.
    rows = list(s.execute(
        select(TextRegion).where(
            TextRegion.item_id == item_id,
            sa_true() if parent_id is not None
            else TextRegion.file_id == item.active_file_id,
            TextRegion.parent_id.is_(None) if parent_id is None
            else TextRegion.parent_id == parent_id)
        .order_by(TextRegion.ord, TextRegion.id)
    ).scalars().all())
    by_id = {r.id: r for r in rows}
    if sorted(region_ids) != sorted(by_id):
        raise Invalid("the order must name each sibling region exactly once",
                      code="bad_text_order")
    old_order = [r.id for r in rows]
    if region_ids == old_order:
        return rows
    for pos, rid in enumerate(region_ids):
        by_id[rid].ord = pos
    ctx.log(action=actions.REORDER_TEXT, entity_type="item",
            entity_id=item_id, summary="Reordered the text blocks",
            data={"item_id": item_id, "parent_id": parent_id,
                  "order": list(region_ids), "old_order": old_order})
    s.flush()
    touch_items(s, [item_id])
    return [by_id[rid] for rid in region_ids]
