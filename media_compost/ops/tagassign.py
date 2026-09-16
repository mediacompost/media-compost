"""What an item (or a library group) carries: assignments, placements, boxes.

The tag ROW is :mod:`media_compost.ops.tagcatalog`; this is everything about
putting one on something.

Three shapes live here and are easy to confuse:

* an **assignment** (`ItemTag`) — this item has this tag, positively or not;
* a **placement** (`ItemTagPlacement`) — that assignment filed into one of the
  item's per-item tag groups, or into none (`group_id` NULL, the implicit
  "Ungrouped"). The same tag may be placed in several groups at once;
* a **box** (`ItemTagBox`) — a rectangle, a time range, or both, hanging off a
  placement.

A pure TIME RANGE (a time with no geometry) is the one that carries its own
sign and obeys the non-overlap rule; a box with geometry is a moving subject's
placement, and two subjects sharing a `person` tag are on screen together all
the time.
"""

from __future__ import annotations

import re

from typing import Optional

from sqlalchemy import delete, func, select

from .. import representatives
from ..db import (
    Group, GroupTag, ItemTag, ItemTagBox, ItemTagGroup, ItemTagGroupSubject,
    LIB_META, ItemTagGroupTag, ItemTagPlacement, LinkTag, Tag, chunked,
    touch_items,
)
from . import actions, tagcatalog
from .context import Ctx
from .errors import Invalid, NotFound

# ---- placements -------------------------------------------------------------


def ensure_placement(ctx: Ctx, item_tag_id: int,
                     group_id: Optional[int],
                     negative: Optional[bool] = None) -> ItemTagPlacement:
    """Find (or create) the placement of an item-tag in a group (None=ungrouped).

    ``negative`` is the sign a CREATED placement starts with — an existing
    one keeps its own, because the sign is the instance's. ``None`` (the
    default) INHERITS the assignment's sign: most creations here are
    materializing the implicit ungrouped instance (a move's source, a first
    box), and that instance always meant whatever the assignment means — a
    ``False`` default silently turned a dragged negative tag positive."""
    s = ctx.session
    p = s.execute(select(ItemTagPlacement).where(
        ItemTagPlacement.item_tag_id == item_tag_id,
        ItemTagPlacement.group_id.is_(group_id) if group_id is None
        else ItemTagPlacement.group_id == group_id,
    )).scalars().first()
    if p is None:
        if negative is None:
            it = s.get(ItemTag, item_tag_id)
            negative = bool(it.negative) if it is not None else False
        p = ItemTagPlacement(item_tag_id=item_tag_id, group_id=group_id,
                             negative=bool(negative))
        s.add(p)
        s.flush()
    return p


def sync_placement_sign(ctx: Ctx, item_tag_id: int) -> None:
    """Keep ``ItemTag.negative`` in step with the instances' own signs.

    The timed-range rule one level up: the same tag may be positive in one
    group and negative in another, so the assignment — what search, facets,
    counts and training read — is negative only when EVERY placement is (any
    positive instance wins). An assignment with NO placement rows keeps its
    own sign: the implicit ungrouped instance IS the assignment. A tag with
    timed ranges is left to `sync_timed_sign`, whose boxes are the finer
    statement there.
    """
    s = ctx.session
    it = s.get(ItemTag, item_tag_id)
    if it is None:
        return
    placements = s.execute(select(ItemTagPlacement).where(
        ItemTagPlacement.item_tag_id == item_tag_id)).scalars().all()
    if not placements:
        return
    for p in placements:
        for b in s.execute(select(ItemTagBox).where(
                ItemTagBox.placement_id == p.id)).scalars().all():
            if is_range(b):
                return  # a film tag's sign is its ranges' business
    it.negative = all(bool(p.negative) for p in placements)


def item_of_placement(ctx: Ctx, placement_id: int) -> Optional[int]:
    return ctx.session.execute(
        select(ItemTag.item_id)
        .join(ItemTagPlacement, ItemTagPlacement.item_tag_id == ItemTag.id)
        .where(ItemTagPlacement.id == placement_id)
    ).scalar_one_or_none()


def placement_snapshot(ctx: Ctx, it: ItemTag) -> list[dict]:
    """An assignment's tag-group placements and their boxes, as plain data.

    Restoring a tag has to restore the SHAPE of the assignment, not just its
    existence: which per-item tag group it sat in, and every box or time range
    hanging off it (a film tag is nothing but its ranges).
    """
    s = ctx.session
    out: list[dict] = []
    for p in s.execute(select(ItemTagPlacement).where(
        ItemTagPlacement.item_tag_id == it.id
    )).scalars().all():
        grp = s.get(ItemTagGroup, p.group_id) if p.group_id else None
        out.append({
            # By NAME, not id: the group may itself be recreated by a revert.
            "group": grp.name if grp is not None else None,
            "system": bool(grp.system) if grp is not None else False,
            # The INSTANCE's own sign — part of the shape a revert restores.
            "negative": bool(p.negative),
            "boxes": [
                {"x": b.x, "y": b.y, "w": b.w, "h": b.h,
                 "time_start": b.time_start, "time_end": b.time_end,
                 "track_id": b.track_id, "negative": bool(b.negative),
                 **({"points": b.points} if b.points else {})}
                for b in s.execute(select(ItemTagBox).where(
                    ItemTagBox.placement_id == p.id)).scalars().all()
            ],
        })
    return out


def _iou(a: ItemTagBox, b: ItemTagBox) -> float:
    """Intersection-over-union of two spatial boxes (0 if either lacks a full
    x/y/w/h rectangle — e.g. a pure time-range annotation)."""
    vals = (a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h)
    if any(v is None for v in vals):
        return 0.0
    ix0, iy0 = max(a.x, b.x), max(a.y, b.y)
    ix1 = min(a.x + a.w, b.x + b.w)
    iy1 = min(a.y + a.h, b.y + b.h)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


# Boxes overlapping an existing box by at least this IoU are combined into one
# (their union rectangle) rather than kept as separate boxes.
_MERGE_IOU = 0.5


def fold_boxes(ctx: Ctx, src: ItemTagPlacement, dst: ItemTagPlacement) -> None:
    """Merge ``src``'s boxes into ``dst``: a box overlapping an existing dst box
    by ≥50% (IoU) is combined into that box's union rectangle; the rest are moved
    over as additional boxes. Boxes left on ``src`` are dropped when it's deleted."""
    targets = list(dst.boxes)
    for box in list(src.boxes):
        match = next((t for t in targets if _iou(t, box) >= _MERGE_IOU), None)
        if match is not None:
            # Combine into the union rectangle; the incoming box stays on src and
            # is deleted with it.
            x0, y0 = min(match.x, box.x), min(match.y, box.y)
            x1 = max(match.x + match.w, box.x + box.w)
            y1 = max(match.y + match.h, box.y + box.h)
            match.x, match.y, match.w, match.h = x0, y0, x1 - x0, y1 - y0
        else:
            # Reparent via the many-to-one side so delete-orphan doesn't fire and
            # later incoming boxes can merge against it too.
            box.placement = dst
            targets.append(box)
    ctx.session.flush()


def merge_placement_into_group(ctx: Ctx, placement: ItemTagPlacement,
                               to_group_id: Optional[int]) -> None:
    """Move ``placement`` to ``to_group_id``; if the same tag already has an
    instance there, fold this placement's boxes into it (merging overlapping
    boxes) and drop the duplicate."""
    s = ctx.session
    existing = s.execute(select(ItemTagPlacement).where(
        ItemTagPlacement.item_tag_id == placement.item_tag_id,
        ItemTagPlacement.id != placement.id,
        ItemTagPlacement.group_id.is_(to_group_id) if to_group_id is None
        else ItemTagPlacement.group_id == to_group_id,
    )).scalars().first()
    if existing is None:
        placement.group_id = to_group_id
        return
    fold_boxes(ctx, placement, existing)
    s.delete(placement)


def recompute_pending(ctx: Ctx, item_tag_id: int) -> None:
    """Set an item-tag's ``pending`` flag from whether it still has any placement
    in a system (Pending) group — used after moving/removing a pending copy so a
    tag that's also assigned elsewhere doesn't stay stuck as pending."""
    s = ctx.session
    it = s.get(ItemTag, item_tag_id)
    if it is None:
        return
    has_pending = s.execute(
        select(ItemTagPlacement.id)
        .join(ItemTagGroup, ItemTagGroup.id == ItemTagPlacement.group_id)
        .where(ItemTagPlacement.item_tag_id == item_tag_id,
               ItemTagGroup.system.is_(True))
        .limit(1)
    ).first() is not None
    it.pending = has_pending


def cleanup_pending_group(ctx: Ctx, group_id: Optional[int]) -> None:
    """Delete the auto-managed "Pending" group once it holds no placements."""
    s = ctx.session
    if group_id is None:
        return
    grp = s.get(ItemTagGroup, group_id)
    if grp is None or not grp.system:
        return
    remaining = s.execute(
        select(func.count()).select_from(ItemTagPlacement)
        .where(ItemTagPlacement.group_id == group_id)
    ).scalar_one()
    if remaining == 0:
        s.delete(grp)


# ---- timed ranges (video) ---------------------------------------------------


def is_range(box: ItemTagBox) -> bool:
    """A pure time range — a stretch of a film, with no geometry.

    Only these carry a sign and obey the non-overlap rule. A box that also has
    geometry is a moving subject's placement, and two subjects sharing a tag
    (both ``person``) are on screen at the same moment all the time.
    """
    return box.time_start is not None and box.x is None


def ranges_of_tag(ctx: Ctx, item_id: int, tag_id: int) -> list[ItemTagBox]:
    """Every pure time range of one tag on one item, across all of its groups.

    Ranges belong to the TAG, not to the placement: the same tag placed in two
    groups still describes one film, so the non-overlap rule spans all of them.
    """
    return list(ctx.session.execute(
        select(ItemTagBox)
        .join(ItemTagPlacement, ItemTagPlacement.id == ItemTagBox.placement_id)
        .join(ItemTag, ItemTag.id == ItemTagPlacement.item_tag_id)
        .where(ItemTag.item_id == item_id, ItemTag.tag_id == tag_id,
               ItemTagBox.time_start.is_not(None), ItemTagBox.x.is_(None))
    ).scalars().all())


def make_room(ctx: Ctx, item_id: int, tag_id: int, keep: ItemTagBox) -> None:
    """Cut ``keep``'s range out of every OTHER range of the same tag.

    A tag's ranges may not overlap, whatever their signs — "present here" and
    "absent here" cannot both be true of one moment. The newest edit wins and
    the others yield: one that is covered is deleted, one that is straddled
    keeps the pieces either side (the second becomes a row of its own), one
    that merely overlaps is trimmed. Enforced here rather than in the client so
    it holds for every writer.
    """
    s = ctx.session
    if not is_range(keep):
        return
    ks = keep.time_start
    ke = keep.time_end if keep.time_end is not None else keep.time_start
    for b in ranges_of_tag(ctx, item_id, tag_id):
        if b.id == keep.id or b.time_start is None:
            continue
        bs = b.time_start
        be = b.time_end if b.time_end is not None else b.time_start
        if be < ks or bs > ke:
            continue  # clear of it
        left = bs < ks
        right = be > ke
        if not left and not right:
            s.delete(b)
        elif left and right:
            # Straddled: keep the left piece here, add the right one beside it.
            s.add(ItemTagBox(
                placement_id=b.placement_id, x=b.x, y=b.y, w=b.w, h=b.h,
                time_start=ke, time_end=be, track_id=b.track_id,
                negative=b.negative,
            ))
            b.time_end = ks
        elif left:
            b.time_end = ks
        else:
            b.time_start = ke
    s.flush()


def sync_timed_sign(ctx: Ctx, item_id: int, tag_id: int) -> None:
    """Keep ``ItemTag.negative`` in step with the tag's timed ranges.

    The item-level flag is what search, facets and counts read, so a film whose
    tag has any positive range must read positive there; only a tag that is
    negative in every one of its ranges is negative for the item. A tag with no
    ranges at all keeps whatever sign it was assigned.
    """
    boxes = ranges_of_tag(ctx, item_id, tag_id)
    if not boxes:
        return
    it_tag = ctx.session.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag_id
    )).scalars().first()
    if it_tag is not None:
        it_tag.negative = all(b.negative for b in boxes)


def tag_id_of_box(ctx: Ctx, box: ItemTagBox) -> Optional[int]:
    return ctx.session.execute(
        select(ItemTag.tag_id)
        .join(ItemTagPlacement, ItemTagPlacement.item_tag_id == ItemTag.id)
        .where(ItemTagPlacement.id == box.placement_id)
    ).scalars().first()


def _box_tag_name(ctx: Ctx, box: ItemTagBox) -> str:
    """The tag a box is on, for the log's sentence (empty if it has none)."""
    tag_id = tag_id_of_box(ctx, box)
    if tag_id is None:
        return ""
    tag = ctx.session.get(Tag, tag_id)
    return tag.name if tag is not None else ""


# ---- assignments ------------------------------------------------------------


def assign_bulk(ctx: Ctx, pairs) -> int:
    """Assign many (item_id, tag name) pairs in ONE pass — the crawl batch.

    Each name goes through the one assignment door (`tagcatalog.
    get_or_create` — alias redirection, score-tag refusal; a refused name is
    SKIPPED, never a failed batch), resolved once per distinct name. A
    leading ``-`` is the negative sign, the import-tags rule. Pairs the item
    already carries are left alone, items that no longer exist are dropped,
    and the whole batch is chunked selects, one insert set, one sidecar
    touch and ONE revertible event — against an event, a touch and a flush
    per pair through the singular door, which is what a crawl of a hundred
    thousand pictures cannot afford. Returns how many assignments were new.
    """
    from .. import tagname
    from ..db import Item, chunked, touch_items

    s = ctx.session

    def _clean(raw) -> "Optional[tuple[str, bool]]":
        raw = str(raw).strip()
        negative = raw.startswith("-")
        if negative:
            raw = raw[1:]
        name = tagname.normalize(re.sub(r"\s+", "_", raw.strip().lower()))
        return (name, negative) if name else None

    tag_of: dict[str, Optional[int]] = {}

    def _tid(name: str) -> Optional[int]:
        if name not in tag_of:
            try:
                tag_of[name] = tagcatalog.get_or_create(ctx, name).id
            except Exception:  # noqa: BLE001 - a refused name is skipped
                tag_of[name] = None
        return tag_of[name]

    want: dict[tuple[int, int], bool] = {}
    for iid, raw in pairs:
        cleaned = _clean(raw)
        if cleaned is None:
            continue
        tid = _tid(cleaned[0])
        if tid is not None:
            want.setdefault((int(iid), tid), cleaned[1])
    if not want:
        return 0
    ids = sorted({iid for iid, _t in want})
    tag_ids = sorted({t for _i, t in want})
    alive: set[int] = set()
    have: set[tuple[int, int]] = set()
    for chunk in chunked(ids):
        alive.update(s.execute(
            select(Item.id).where(Item.id.in_(chunk))).scalars())
        have.update(s.execute(
            select(ItemTag.item_id, ItemTag.tag_id).where(
                ItemTag.item_id.in_(chunk),
                ItemTag.tag_id.in_(tag_ids))).all())
    fresh = [(iid, tid, neg) for (iid, tid), neg in want.items()
             if iid in alive and (iid, tid) not in have]
    if not fresh:
        return 0
    s.add_all([ItemTag(item_id=iid, tag_id=tid, negative=neg)
               for iid, tid, neg in fresh])
    s.flush()
    touch_items(s, sorted({iid for iid, _t, _n in fresh}))
    ctx.log(
        action=actions.ADD_TAGS_BULK, entity_type="items",
        summary="Assigned {tags} tags to {items} items",
        summary_vars={"tags": len({t for _i, t, _n in fresh}),
                      "items": len({i for i, _t, _n in fresh})},
        data={"created": [[iid, tid, neg] for iid, tid, neg in fresh]},
    )
    return len(fresh)


def assign_item_tag(ctx: Ctx, item_id: int, name: str, *,
                    negative: bool = False) -> ItemTag:
    """Put ``name`` on the item, alias-redirected, creating the tag if new.

    A hand assignment is an explicit assertion, so it RESOLVES a machine's
    pending suggestion of the same tag rather than leaving the flag to say
    something the answer just contradicted: a positive confirms it through
    the approve machinery (every system-group placement accepted, the same
    path the pending group's tick takes), a negative dismisses those
    placements. Never a bare ``pending = False`` — the placement would still
    sit in a system group and the next `recompute_pending` would flip the
    flag straight back.

    The row rides its ``add_tag`` event's id back as a transient
    ``event_id`` attribute (the `rankings.judge` shape), so a session
    overlay's undo can revert exactly this answer.
    """
    s = ctx.session
    tag = tagcatalog.get_or_create(ctx, name)
    row = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
    )).scalars().first()
    if row is not None and row.pending:
        if negative:
            # The suggestion was wrong: its pending placements go, with
            # their own (revertible) events; the last one may unassign the
            # row entirely, so re-fetch before the upsert below.
            waiting = s.execute(
                select(ItemTagPlacement.id)
                .join(ItemTagGroup,
                      ItemTagGroup.id == ItemTagPlacement.group_id)
                .where(ItemTagPlacement.item_tag_id == row.id,
                       ItemTagGroup.system.is_(True))
            ).scalars().all()
            for pid in waiting:
                delete_placement(ctx, pid)
            row = s.execute(select(ItemTag).where(
                ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
            )).scalars().first()
            if row is not None:
                row.pending = False
        else:
            # Confirmed — by the resolved name, since `name` may have been
            # an alias and `set_pending` looks the tag up literally.
            set_pending(ctx, item_id, tag.name, False)
    if row:
        row.negative = negative
        # A name-level statement: "this item is −X" covers every instance,
        # or the derived sign (any positive placement wins) would flip it
        # straight back.
        for p in s.execute(select(ItemTagPlacement).where(
                ItemTagPlacement.item_tag_id == row.id)).scalars().all():
            p.negative = negative
    else:
        row = ItemTag(item_id=item_id, tag_id=tag.id, negative=negative)
        s.add(row)
    touch_items(s, [item_id])
    ev = ctx.log(
        action=actions.ADD_TAG, entity_type="item", entity_id=item_id,
        summary=("Tagged item #{item} −{tag}" if negative
                 else "Tagged item #{item} +{tag}"),
        summary_vars={"item": item_id, "tag": name},
        data={"item_id": item_id, "tag": name, "negative": negative})
    s.flush()
    row.event_id = ev.id  # a transient attribute, not a column
    return row


def _drop_subject_group_bindings(ctx: Ctx, item_id: int,
                                 tag_id: int) -> None:
    """A subject leaving an ITEM takes its tag-group bindings there with it.

    A per-item tag group may be ABOUT a subject (`ItemTagGroupSubject`), and
    the binding is independent of the assignment — so removing the subject's
    identity tag from the item used to leave the group pointing at a subject
    the item no longer has, which the sidebar could only render as a "?"
    chip. Routed through `remove_group_subject`, so each dropped binding is
    its own logged, revertible event, exactly as the chip's own ✕ writes.
    """
    from ..db import Subject

    s = ctx.session
    subject_ids = s.execute(
        select(Subject.id).where(Subject.tag_id == tag_id)
    ).scalars().all()
    if not subject_ids:
        return
    rows = s.execute(
        select(ItemTagGroupSubject.group_id, ItemTagGroupSubject.subject_id)
        .join(ItemTagGroup, ItemTagGroup.id == ItemTagGroupSubject.group_id)
        .where(ItemTagGroup.item_id == item_id,
               ItemTagGroupSubject.subject_id.in_(subject_ids))
    ).all()
    for gid, sid in rows:
        remove_group_subject(ctx, gid, sid)


def unassign_item_tag(ctx: Ctx, item_id: int, name: str) -> bool:
    """Take ``name`` off the item. Returns whether anything was assigned.

    A ranking's own score row may be taken off too — it is the item's
    standing, and the next rebuild puts it straight back; the sidebar's
    Scores box offers "leave the ranking" instead, which sticks. A score
    tag assigned BY HAND is an ordinary row and this is its ordinary way
    off."""
    s = ctx.session
    removed = False
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if tag:
        row = s.execute(select(ItemTag).where(
            ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
        )).scalars().first()
        if row is not None:
            negative = bool(row.negative)
            # The placements go with the row (FK cascade), so THEIR pending
            # groups must be swept here — a dismissed suggestion's group
            # otherwise strands empty, a box no control can remove.
            group_ids = [p.group_id for p in row.placements
                         if p.group_id is not None]
            s.execute(delete(ItemTag).where(
                ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
            ))
            s.flush()
            for gid in group_ids:
                cleanup_pending_group(ctx, gid)
            # A Core delete — the flush listener never sees it, and the
            # representative row went by cascade: settle the tag here.
            representatives.settle(s, [tag.id])
            removed = True
            ctx.log(action=actions.REMOVE_TAG, entity_type="item",
                    entity_id=item_id,
                    summary="Removed tag {tag} from item #{item}",
                    summary_vars={"tag": name, "item": item_id},
                    data={"item_id": item_id, "tag": name,
                          "negative": negative})
            _drop_subject_group_bindings(ctx, item_id, tag.id)
    touch_items(s, [item_id])
    return removed


def _group_of_item(ctx: Ctx, item_id: int,
                   group_id: Optional[int]) -> Optional[ItemTagGroup]:
    if group_id is None:
        return None
    grp = ctx.session.get(ItemTagGroup, group_id)
    if grp is None or grp.item_id != item_id:
        raise Invalid("tag group does not belong to this item",
                      code="tag_group_wrong_item")
    return grp


def place_tag(ctx: Ctx, item_id: int, name: str, *,
              group_id: Optional[int] = None,
              negative: bool = False) -> ItemTagPlacement:
    """Add a tag as an instance in a specific group (None = ungrouped default),
    creating a placement. The same tag may be placed in several groups at once."""
    s = ctx.session
    _group_of_item(ctx, item_id, group_id)
    tag = tagcatalog.get_or_create(ctx, name)
    it_tag = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
    )).scalars().first()
    if it_tag is None:
        it_tag = ItemTag(item_id=item_id, tag_id=tag.id, negative=negative)
        s.add(it_tag)
        s.flush()
    placement = ensure_placement(ctx, it_tag.id, group_id, negative=negative)
    # An instance that already existed takes the requested sign — adding
    # "−face in group B" over an existing positive placement there IS a sign
    # edit — and the assignment re-derives (any positive placement wins).
    placement.negative = negative
    sync_placement_sign(ctx, it_tag.id)
    touch_items(s, [item_id])
    ctx.log(action=actions.ADD_TAG, entity_type="item", entity_id=item_id,
            summary=("Tagged item #{item} −{tag}" if negative
                     else "Tagged item #{item} +{tag}"),
            summary_vars={"item": item_id, "tag": name},
            data={"item_id": item_id, "tag": name, "negative": negative})
    return placement


def set_placement_sign(ctx: Ctx, placement_id: int,
                       negative: bool) -> ItemTagPlacement:
    """Flip ONE instance's sign — the row's own dot, not the tag's.

    The same tag may be positive in one group and negative in another on one
    item; the assignment re-derives (any positive instance wins). Logged and
    revertible: the revert restores the instance's old sign and re-derives.
    """
    s = ctx.session
    p = s.get(ItemTagPlacement, placement_id)
    if p is None:
        raise NotFound("tag instance not found", code="placement_not_found")
    it = s.get(ItemTag, p.item_tag_id)
    item_id = it.item_id if it is not None else None
    tag = s.get(Tag, it.tag_id) if it is not None else None
    name = tag.name if tag is not None else ""
    old = bool(p.negative)
    if old == bool(negative):
        return p
    p.negative = bool(negative)
    sync_placement_sign(ctx, p.item_tag_id)
    if item_id is not None:
        touch_items(s, [item_id])
        grp = s.get(ItemTagGroup, p.group_id) if p.group_id else None
        ctx.log(
            action=actions.SET_PLACEMENT_SIGN, entity_type="item",
            entity_id=item_id,
            summary=("Made {tag} negative in one group" if negative
                     else "Made {tag} positive in one group"),
            summary_vars={"tag": name},
            data={"item_id": item_id, "tag": name,
                  "placement_id": p.id,
                  "group": grp.name if grp is not None else None,
                  "old": old, "negative": bool(negative)})
    return p


def move_instance(ctx: Ctx, item_id: int, name: str, *,
                  from_group_id: Optional[int],
                  to_group_id: Optional[int]) -> bool:
    """Move a tag instance between the item's groups (None = ungrouped).

    Returns False when source and target are the same group (a no-op).
    """
    s = ctx.session
    for gid in (from_group_id, to_group_id):
        _group_of_item(ctx, item_id, gid)
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if tag is None:
        raise NotFound("tag not found", code="tag_not_found")
    it_tag = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
    )).scalars().first()
    if it_tag is None:
        raise NotFound("tag not assigned to this item", code="tag_not_assigned")
    if from_group_id == to_group_id:
        return False
    # The source instance may be implicit (no placement row yet) — create it so
    # it can be moved.
    src = ensure_placement(ctx, it_tag.id, from_group_id)
    merge_placement_into_group(ctx, src, to_group_id)
    cleanup_pending_group(ctx, from_group_id)
    # Moving a tag *out* of the auto-managed Pending group accepts it — but only
    # clear the pending flag if no other pending copy of the tag remains.
    recompute_pending(ctx, it_tag.id)
    # A move that folded into an existing instance dropped one sign from the
    # set (the target's survives), so the assignment re-derives.
    sync_placement_sign(ctx, it_tag.id)
    touch_items(s, [item_id])

    def _gname(gid: Optional[int]) -> str:
        if gid is None:
            return "Ungrouped"
        g = s.get(ItemTagGroup, gid)
        return g.name if g is not None else "a group"

    ctx.log(
        action=actions.MOVE_TAG_GROUP, entity_type="item", entity_id=item_id,
        summary="Moved tag {tag} from {from} to {to}",
        summary_vars={"tag": name, "from": _gname(from_group_id),
                      "to": _gname(to_group_id)},
        # Names are for the summary; the IDS are what a revert moves it back
        # with — two groups may share a name, and either may be renamed later.
        data={"item_id": item_id, "tag": name,
              "from_group": _gname(from_group_id),
              "to_group": _gname(to_group_id),
              "from_group_id": from_group_id, "to_group_id": to_group_id},
    )
    return True


def delete_placement(ctx: Ctx, placement_id: int) -> bool:
    """Remove a tag instance (a placement + its boxes) from its group.

    If that was the tag's *last* instance, the tag is fully unassigned from the
    item — otherwise a tag added to a group would reappear as an implicit
    ungrouped instance, so removing it appeared to need two clicks."""
    s = ctx.session
    p = s.get(ItemTagPlacement, placement_id)
    if p is None:
        return False
    item_id = item_of_placement(ctx, placement_id)
    it_tag_id = p.item_tag_id
    former_group_id = p.group_id
    s.delete(p)
    s.flush()
    cleanup_pending_group(ctx, former_group_id)
    remaining = s.execute(select(func.count(ItemTagPlacement.id)).where(
        ItemTagPlacement.item_tag_id == it_tag_id
    )).scalar_one()
    if remaining:
        # The instance that left may have been the one positive copy.
        sync_placement_sign(ctx, it_tag_id)
    if remaining == 0:
        it = s.get(ItemTag, it_tag_id)
        if it is not None:
            tag = s.get(Tag, it.tag_id)
            name = tag.name if tag else ""
            negative = bool(it.negative)
            tag_id = it.tag_id
            s.delete(it)
            if item_id is not None and name:
                ctx.log(action=actions.REMOVE_TAG, entity_type="item",
                        entity_id=item_id,
                        summary="Removed tag {tag} from item #{item}",
                    summary_vars={"tag": name, "item": item_id},
                        data={"item_id": item_id, "tag": name,
                              "negative": negative})
                _drop_subject_group_bindings(ctx, item_id, tag_id)
    else:
        # Dismissed one instance but the tag survives elsewhere — clear the
        # pending flag if no pending copy is left.
        recompute_pending(ctx, it_tag_id)
    if item_id is not None:
        touch_items(s, [item_id])
    return True


# ---- boxes ------------------------------------------------------------------


def _to_reference_frame(ctx: Ctx, file_id: Optional[int], x, y, w, h):
    """Boxes are stored in the ITEM's reference frame. A box drawn on a cropped
    file version is given in that file's frame, so map it through the crop."""
    if file_id is None or None in (x, y, w, h):
        return x, y, w, h
    from ..db import File

    f = ctx.session.get(File, file_id)
    if f is None:
        return x, y, w, h
    return (f.crop_x + x * f.crop_w, f.crop_y + y * f.crop_h,
            w * f.crop_w, h * f.crop_h)


def points_to_reference(ctx: Ctx, file_id: Optional[int],
                        points) -> Optional[str]:
    """A polygon's vertices, mapped from ``file_id``'s frame into the item's
    reference frame (each vertex through the crop, exactly as a box origin
    is) and serialized for the column. None/empty in, None out."""
    import json as _json

    if not points:
        return None
    out = []
    for p in points:
        px, py = float(p[0]), float(p[1])
        rx, ry, _, _ = _to_reference_frame(ctx, file_id, px, py, 0.0, 0.0)
        out.append([rx, ry])
    return _json.dumps(out)


def poly_bbox(points_json: Optional[str]):
    """The stored polygon's bounding box (x, y, w, h) — what the four
    rectangle columns hold while a polygon is set, so every rectangle reader
    stays unchanged. None for anything that is not a valid polygon."""
    import json as _json

    if not points_json:
        return None
    try:
        pts = _json.loads(points_json)
    except ValueError:
        return None
    if not isinstance(pts, list) or len(pts) < 3:
        return None
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def points_list(points_json: Optional[str]):
    """The stored polygon as a plain [[x, y], ...] list, for API output.

    None for a plain rectangle or anything malformed — a reader never sees a
    polygon that would not round-trip."""
    import json as _json

    if not points_json:
        return None
    try:
        pts = _json.loads(points_json)
    except ValueError:
        return None
    if not isinstance(pts, list) or len(pts) < 3:
        return None
    try:
        return [[float(p[0]), float(p[1])] for p in pts]
    except (TypeError, ValueError, IndexError):
        return None


def _box_state(box: ItemTagBox) -> dict:
    """A box's whole shape, for an event that has to put it back."""
    return {"x": box.x, "y": box.y, "w": box.w, "h": box.h,
            "time_start": box.time_start, "time_end": box.time_end,
            "track_id": box.track_id, "negative": bool(box.negative),
            "points": box.points, "placement_id": box.placement_id}


def add_box(ctx: Ctx, item_id: int, name: str, *, x=None, y=None, w=None,
            h=None, time_start=None, time_end=None, track_id=None,
            negative: bool = False, file_id: Optional[int] = None,
            group_id: Optional[int] = None, points=None) -> ItemTagBox:
    """Add a bounding-box / time-range annotation for a tag on an item.

    Ensures the (positive) tag is assigned first, then records the box. Several
    boxes may exist per (item, tag) — e.g. the same tag at different times in a
    video.
    """
    s = ctx.session
    tag = tagcatalog.get_or_create(ctx, name)
    it_tag = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
    )).scalars().first()
    minted_tag = it_tag is None
    if it_tag is None:
        it_tag = ItemTag(item_id=item_id, tag_id=tag.id, negative=False)
        s.add(it_tag)
        s.flush()
    # The box belongs to a tag instance in a group (None = ungrouped default).
    _group_of_item(ctx, item_id, group_id)
    placement = ensure_placement(ctx, it_tag.id, group_id)
    x, y, w, h = _to_reference_frame(ctx, file_id, x, y, w, h)
    pts = points_to_reference(ctx, file_id, points)
    bb = poly_bbox(pts)
    if bb is not None:
        # The rectangle columns HOLD the polygon's bounding box — the server
        # derives it, so the two cannot drift however the client spelled
        # them.
        x, y, w, h = bb
    box = ItemTagBox(placement_id=placement.id, x=x, y=y, w=w, h=h,
                     time_start=time_start, time_end=time_end,
                     track_id=track_id, negative=negative, points=pts)
    s.add(box)
    s.flush()
    if is_range(box):
        make_room(ctx, item_id, tag.id, box)
        sync_timed_sign(ctx, item_id, tag.id)
    touch_items(s, [item_id])
    # Drawing a box for a tag the item did not carry ASSIGNS it, so undoing
    # the box has to take that assignment back too — anything less leaves a
    # tag nobody asked for behind the shape they just removed.
    ctx.log(action=actions.ADD_TAG_BOX, entity_type="item", entity_id=item_id,
            summary="Drew a box for “{name}”", summary_vars={"name": tag.name},
            data={"item_id": item_id, "box_id": box.id, "tag": tag.name,
                  "tag_id": tag.id, "minted_tag": minted_tag,
                  "box": _box_state(box)})
    return box


def update_box(ctx: Ctx, box_id: int, *, x=None, y=None, w=None, h=None,
               file_id: Optional[int] = None, tag: Optional[str] = None,
               time_start=None, time_end=None, track_id=None,
               negative: Optional[bool] = None, clear_time: bool = False,
               clear_track: bool = False, points=None,
               clear_points: bool = False) -> ItemTagBox:
    """Update a box's geometry and/or its tag, keeping the same box id so the
    annotation editor's undo/redo can track it. Geometry is given in ``file_id``'s
    frame (mapped to the item's reference frame, like adding a box).
    ``points`` replaces the polygon (rectangle columns re-derived as its
    bounding box); ``clear_points`` turns it back into a plain rectangle."""
    s = ctx.session
    box = s.get(ItemTagBox, box_id)
    if box is None:
        raise NotFound("box not found", code="box_not_found")
    item_id = item_of_placement(ctx, box.placement_id)
    before = _box_state(box)
    if clear_points:
        box.points = None
    elif points:
        pts = points_to_reference(ctx, file_id, points)
        bb = poly_bbox(pts)
        if bb is not None:
            box.points = pts
            box.x, box.y, box.w, box.h = bb
            # The polygon is the geometry now — a rectangle sent beside it
            # would overwrite the derived bounding box and break the
            # invariant, so it is ignored.
            x = y = w = h = None
    if None not in (x, y, w, h):
        box.x, box.y, box.w, box.h = _to_reference_frame(ctx, file_id, x, y, w, h)
        if box.points is not None and not points:
            # A rectangle edit of a polygon box (the box-mode bbox transform):
            # map the stored vertices through the affine that carries the old
            # bounding box onto the new one, so the shape scales rather than
            # silently losing its polygon.
            import json as _json

            old = poly_bbox(box.points)
            if old is not None:
                ox, oy, ow, oh = old
                sx = (box.w / ow) if ow else 0.0
                sy = (box.h / oh) if oh else 0.0
                pts2 = [[box.x + (px - ox) * sx, box.y + (py - oy) * sy]
                        for px, py in _json.loads(box.points)]
                box.points = _json.dumps(pts2)
    # Timed-box range + track: a video subject moves, so the box's [start,end]
    # and its track membership can be edited in place. None means "leave as is";
    # the clear_* flags set the field back to null.
    if clear_time:
        box.time_start, box.time_end = None, None
    else:
        if time_start is not None:
            box.time_start = time_start
        if time_end is not None:
            box.time_end = time_end
    if clear_track:
        box.track_id = None
    elif track_id is not None:
        box.track_id = track_id
    if negative is not None:
        box.negative = negative
    if tag is not None and item_id is not None:
        newtag = tagcatalog.get_or_create(ctx, tag)
        it_tag = s.execute(select(ItemTag).where(
            ItemTag.item_id == item_id, ItemTag.tag_id == newtag.id
        )).scalars().first()
        if it_tag is None:
            it_tag = ItemTag(item_id=item_id, tag_id=newtag.id, negative=False)
            s.add(it_tag)
            s.flush()
        cur = s.get(ItemTagPlacement, box.placement_id)
        gid = cur.group_id if cur is not None else None
        box.placement_id = ensure_placement(ctx, it_tag.id, gid).id
    if item_id is not None:
        s.flush()
        if is_range(box):
            tag_id = tag_id_of_box(ctx, box)
            if tag_id is not None:
                make_room(ctx, item_id, tag_id, box)
                sync_timed_sign(ctx, item_id, tag_id)
        touch_items(s, [item_id])
    after = _box_state(box)
    if after != before:
        name = _box_tag_name(ctx, box)
        ctx.log(action=actions.EDIT_TAG_BOX, entity_type="item",
                entity_id=item_id, summary="Edited the box for “{name}”",
                summary_vars={"name": name},
                data={"item_id": item_id, "box_id": box.id, "tag": name,
                      "old": before, "new": after})
    return box


def delete_box(ctx: Ctx, box_id: int) -> bool:
    s = ctx.session
    box = s.get(ItemTagBox, box_id)
    if box is None:
        return False
    item_id = item_of_placement(ctx, box.placement_id)
    tag_id = tag_id_of_box(ctx, box) if is_range(box) else None
    state = _box_state(box)
    name = _box_tag_name(ctx, box)
    s.delete(box)
    if item_id is not None:
        # Dropping the last negative range makes the tag positive again.
        if tag_id is not None:
            s.flush()
            sync_timed_sign(ctx, item_id, tag_id)
        touch_items(s, [item_id])
    ctx.log(action=actions.DELETE_TAG_BOX, entity_type="item",
            entity_id=item_id, summary="Removed the box for “{name}”",
            summary_vars={"name": name},
            data={"item_id": item_id, "box_id": box_id, "tag": name,
                  "box": state})
    return True


# ---- per-item tag groups ----------------------------------------------------


def tag_group_or_404(ctx: Ctx, group_id: int) -> ItemTagGroup:
    grp = ctx.session.get(ItemTagGroup, group_id)
    if grp is None:
        raise NotFound("tag group not found", code="tag_group_not_found")
    return grp


def groups_for_items(ctx: Ctx, item_ids: list[int]) -> dict[int, list[dict]]:
    """Every item's per-item tag groups, in one set of queries.

    The bulk sibling of `group_meta_tags` / `group_subjects` below, which
    answer for one group each — fine for a sidebar, four queries per picture
    for anything walking a library. Five statements total here, whatever the
    size of the set.

    Per item, in the groups' own order, each group as
    ``{id, name, system, tags, meta_tags, subjects}``. ``tags`` is the
    POSITIVE tag names placed in it, **in placement order** — a group is a
    layout, so the order somebody arranged is part of what it says, and
    leaving it to whatever the database returns makes the same library
    describe itself differently on two reads.
    """
    if not item_ids:
        return {}
    s = ctx.session
    groups = []
    for chunk in chunked(item_ids):
        groups.extend(s.execute(
            select(ItemTagGroup)
            .where(ItemTagGroup.item_id.in_(chunk))
            .order_by(ItemTagGroup.item_id, ItemTagGroup.position,
                      ItemTagGroup.id)
        ).scalars().all())
    if not groups:
        return {}
    gids = [g.id for g in groups]

    members: dict[int, list[str]] = {}
    for chunk in chunked(gids):
        for gid, name in s.execute(
            select(ItemTagPlacement.group_id, Tag.name)
            .join(ItemTag, ItemTag.id == ItemTagPlacement.item_tag_id)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .where(ItemTagPlacement.group_id.in_(chunk),
                   ItemTag.negative.is_(False))
            .order_by(ItemTagPlacement.group_id, ItemTagPlacement.id)
        ).all():
            members.setdefault(gid, []).append(name)

    metas: dict[int, list[str]] = {}
    for chunk in chunked(gids):
        for gid, name in s.execute(
            select(ItemTagGroupTag.group_id, ItemTagGroupTag.name)
            .where(ItemTagGroupTag.group_id.in_(chunk))
            .order_by(ItemTagGroupTag.group_id, ItemTagGroupTag.id)
        ).all():
            metas.setdefault(gid, []).append(name)

    # Who a group is ABOUT. The display name, falling back to the identity
    # tag's name for a subject nobody has named — the same fallback the
    # sidebar makes.
    from ..db import Subject

    subjects: dict[int, list[str]] = {}
    for chunk in chunked(gids):
        for gid, display, tag_name in s.execute(
            select(ItemTagGroupSubject.group_id, Subject.display_name, Tag.name)
            .join(Subject, Subject.id == ItemTagGroupSubject.subject_id)
            .outerjoin(Tag, Tag.id == Subject.tag_id)
            .where(ItemTagGroupSubject.group_id.in_(chunk))
            .order_by(ItemTagGroupSubject.group_id, ItemTagGroupSubject.id)
        ).all():
            name = (display or tag_name or "").strip()
            if name:
                subjects.setdefault(gid, []).append(name)

    out: dict[int, list[dict]] = {}
    for g in groups:
        out.setdefault(g.item_id, []).append({
            "id": g.id,
            "name": g.name or "",
            "system": bool(getattr(g, "system", False)),
            "tags": tuple(members.get(g.id, ())),
            "meta_tags": tuple(metas.get(g.id, ())),
            "subjects": tuple(subjects.get(g.id, ())),
        })
    return out


def ungrouped_for_items(ctx: Ctx, item_ids: list[int]) -> dict[int, set[str]]:
    """Per item, the positive tag names that sit OUTSIDE every tag group.

    "Outside" is two things at once and they answer the same way: a placement
    row whose group is NULL, and no placement row at all — the implicit
    ungrouped instance every directly-assigned tag has. That equivalence is
    the whole reason this is its own read rather than something derivable
    from `groups_for_items`: a tag can be placed in a group AND still be on
    the item by the ungrouped route, and a rule about "every placement of it"
    reads that case wrong in the direction that silently drops a tag the user
    never excluded.
    """
    if not item_ids:
        return {}
    out: dict[int, set[str]] = {}
    for chunk in chunked(item_ids):
        for iid, name, gid in ctx.session.execute(
            select(ItemTag.item_id, Tag.name, ItemTagPlacement.group_id)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .outerjoin(ItemTagPlacement,
                       ItemTagPlacement.item_tag_id == ItemTag.id)
            .where(ItemTag.item_id.in_(chunk), ItemTag.negative.is_(False))
        ).all():
            if gid is None:
                out.setdefault(iid, set()).add(name)
    return out


def boxes_for_items(ctx: Ctx, item_ids: list[int]
                    ) -> dict[int, dict[str, list[ItemTagBox]]]:
    """Every box on every one of these items, by item and tag name.

    `boxes_of` answers for one (item, tag) with a four-way join; a caller
    that wants a library's worth of geometry — a crop-aware exporter, a
    report — would pay that join per tag per picture.

    Rows come back as they are STORED: geometry in the item's reference
    frame, and a range-only box carrying a time and no rectangle. Boxes of a
    NEGATIVE assignment are included, because the name is what they are keyed
    by and whether that name applies to the item is a different question —
    ask `item.tags` if only the positive ones are wanted.
    """
    if not item_ids:
        return {}
    out: dict[int, dict[str, list[ItemTagBox]]] = {}
    for chunk in chunked(item_ids):
        for iid, name, box in ctx.session.execute(
            select(ItemTag.item_id, Tag.name, ItemTagBox)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .join(ItemTagPlacement, ItemTagPlacement.item_tag_id == ItemTag.id)
            .join(ItemTagBox, ItemTagBox.placement_id == ItemTagPlacement.id)
            .where(ItemTag.item_id.in_(chunk))
            .order_by(ItemTag.item_id, ItemTagBox.id)
        ).all():
            out.setdefault(iid, {}).setdefault(name, []).append(box)
    return out


def group_meta_tags(ctx: Ctx, group_id: int) -> list[str]:
    return list(ctx.session.execute(
        select(ItemTagGroupTag.name)
        .where(ItemTagGroupTag.group_id == group_id)
        .order_by(ItemTagGroupTag.id)
    ).scalars().all())


def group_subjects(ctx: Ctx, group_id: int) -> list[int]:
    return list(ctx.session.execute(
        select(ItemTagGroupSubject.subject_id)
        .where(ItemTagGroupSubject.group_id == group_id)
        .order_by(ItemTagGroupSubject.id)
    ).scalars().all())


def create_group(ctx: Ctx, item_id: int, name: str) -> ItemTagGroup:
    s = ctx.session
    pos = s.execute(
        select(func.count()).select_from(ItemTagGroup)
        .where(ItemTagGroup.item_id == item_id)
    ).scalar_one()
    grp = ItemTagGroup(item_id=item_id, name=name.strip() or "New group",
                       position=pos)
    s.add(grp)
    s.flush()
    touch_items(s, [item_id])
    ctx.log(action=actions.CREATE_TAG_GROUP, entity_type="item",
            entity_id=item_id, summary="Added the tag group “{name}”",
            summary_vars={"name": grp.name},
            data={"item_id": item_id, "group_id": grp.id, "name": grp.name,
                  "position": grp.position})
    return grp


def rename_group(ctx: Ctx, group_id: int, name: str) -> ItemTagGroup:
    grp = tag_group_or_404(ctx, group_id)
    name = name.strip()
    if name and name != grp.name:
        old = grp.name
        grp.name = name
        touch_items(ctx.session, [grp.item_id])
        ctx.log(action=actions.RENAME_TAG_GROUP, entity_type="item",
                entity_id=grp.item_id,
                summary="Renamed the tag group “{old}” → “{new}”",
                summary_vars={"old": old, "new": name},
                data={"item_id": grp.item_id, "group_id": grp.id,
                      "old_name": old, "name": name})
    return grp


def delete_group(ctx: Ctx, group_id: int) -> bool:
    """Delete a tag group; its instances fall back to the ungrouped default
    (merging boxes into any existing ungrouped instance of the same tag)."""
    s = ctx.session
    grp = s.get(ItemTagGroup, group_id)
    if grp is None:
        return False
    placements = s.execute(select(ItemTagPlacement).where(
        ItemTagPlacement.group_id == group_id
    )).scalars().all()
    # Which tags were in it, captured BEFORE the merge moves them out — that
    # is what a revert puts back. Boxes folded into an existing ungrouped
    # instance on the way out do not come apart again, exactly as they do not
    # for `move_tag_group`; the grouping is what is restored, not the geometry.
    tag_names = list(s.execute(
        select(Tag.name)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .join(ItemTagPlacement, ItemTagPlacement.item_tag_id == ItemTag.id)
        .where(ItemTagPlacement.group_id == group_id)
    ).scalars().all())
    for p in placements:
        merge_placement_into_group(ctx, p, None)
    s.flush()
    # Everything about the group, read BEFORE the delete takes it away.
    item_id, name, position = grp.item_id, grp.name, grp.position
    system = bool(grp.system)
    meta = group_meta_tags(ctx, group_id)
    subjects = group_subjects(ctx, group_id)
    s.delete(grp)
    touch_items(s, [item_id])
    ctx.log(action=actions.DELETE_TAG_GROUP, entity_type="item",
            entity_id=item_id, summary="Deleted the tag group “{name}”",
            summary_vars={"name": name},
            data={"item_id": item_id, "group_id": group_id, "name": name,
                  "position": position, "system": system, "tags": tag_names,
                  "meta_tags": meta, "subjects": subjects})
    return True


def add_group_meta_tag(ctx: Ctx, group_id: int, name: str) -> list[str]:
    """Add a meta tag to a tag group (idempotent). Returns the group's tags."""
    s = ctx.session
    grp = tag_group_or_404(ctx, group_id)
    name = " ".join((name or "").split())[:64]
    if not name:
        raise Invalid("empty tag", code="empty_meta_tag")
    exists = s.execute(
        select(ItemTagGroupTag).where(ItemTagGroupTag.group_id == group_id,
                                      ItemTagGroupTag.name == name)
    ).scalar_one_or_none()
    if exists is None:
        s.add(ItemTagGroupTag(group_id=group_id, name=name))
    # Persist the NAME too, exactly as the link and caption sides do: a meta
    # tag survives its last use, so the autocomplete list doesn't lose it.
    if s.execute(select(LinkTag).where(LinkTag.name == name, LIB_META)
                 ).scalar_one_or_none() is None:
        s.add(LinkTag(name=name))
    touch_items(s, [grp.item_id])
    ctx.log(action=actions.ADD_TAG_GROUP_TAG, entity_type="item",
            entity_id=grp.item_id,
            summary="Added meta tag “{tag}” to tag group “{group}”",
            summary_vars={"tag": name, "group": grp.name},
            data={"item_id": grp.item_id, "group_id": group_id, "name": name})
    s.flush()
    return group_meta_tags(ctx, group_id)


def remove_group_meta_tag(ctx: Ctx, group_id: int, name: str) -> list[str]:
    """Remove a meta tag from a tag group. The name itself stays in the
    catalog (it may still carry a comment, or be used elsewhere)."""
    s = ctx.session
    grp = tag_group_or_404(ctx, group_id)
    row = s.execute(
        select(ItemTagGroupTag).where(ItemTagGroupTag.group_id == group_id,
                                      ItemTagGroupTag.name == name)
    ).scalar_one_or_none()
    if row is not None:
        s.delete(row)
        touch_items(s, [grp.item_id])
        ctx.log(action=actions.REMOVE_TAG_GROUP_TAG, entity_type="item",
                entity_id=grp.item_id,
                summary="Removed meta tag “{tag}” from tag group “{group}”",
                summary_vars={"tag": name, "group": grp.name},
                data={"item_id": grp.item_id, "group_id": group_id,
                      "name": name})
        s.flush()
    return group_meta_tags(ctx, group_id)


def add_group_subject(ctx: Ctx, group_id: int, subject_id: int) -> list[int]:
    """Say the group is about this subject (idempotent)."""
    from ..db import Subject

    s = ctx.session
    grp = tag_group_or_404(ctx, group_id)
    subject = s.get(Subject, subject_id)
    if subject is None:
        raise NotFound("subject not found", code="subject_not_found")
    exists = s.execute(select(ItemTagGroupSubject).where(
        ItemTagGroupSubject.group_id == group_id,
        ItemTagGroupSubject.subject_id == subject.id,
    )).scalar_one_or_none()
    if exists is None:
        s.add(ItemTagGroupSubject(group_id=group_id, subject_id=subject.id))
        touch_items(s, [grp.item_id])
        ctx.log(action=actions.ADD_TAG_GROUP_SUBJECT, entity_type="item",
                entity_id=grp.item_id,
                summary=("Tag group “{group}” is about {name}"
                         if subject.display_name else
                         "Tag group “{group}” is about an unnamed subject"),
                summary_vars={"group": grp.name,
                              "name": subject.display_name or ""},
                data={"item_id": grp.item_id, "group_id": group_id,
                      "subject_id": subject.id})
    s.flush()
    return group_subjects(ctx, group_id)


def remove_group_subject(ctx: Ctx, group_id: int, subject_id: int) -> list[int]:
    s = ctx.session
    grp = tag_group_or_404(ctx, group_id)
    row = s.execute(select(ItemTagGroupSubject).where(
        ItemTagGroupSubject.group_id == group_id,
        ItemTagGroupSubject.subject_id == subject_id,
    )).scalar_one_or_none()
    if row is not None:
        s.delete(row)
        touch_items(s, [grp.item_id])
        ctx.log(action=actions.REMOVE_TAG_GROUP_SUBJECT, entity_type="item",
                entity_id=grp.item_id,
                summary="Tag group “{name}” is no longer about that subject",
                summary_vars={"name": grp.name},
                data={"item_id": grp.item_id, "group_id": group_id,
                      "subject_id": subject_id})
        s.flush()
    return group_subjects(ctx, group_id)


# ---- library-group tags -----------------------------------------------------


def _log_group_tag(ctx: Ctx, action: str, group_id: int, name: str,
                   negative: bool) -> None:
    """A group's tags flow down to every item in its subtree, so assigning one
    is as much a change as tagging an item — and was not in the log at all."""
    grp = ctx.session.get(Group, group_id)
    # Four whole templates: the group's WORDING ("group “x”" vs "group #7")
    # and the verb each pick their half, because a slotted English fragment
    # cannot translate.
    where = ("group “{group}”" if grp is not None else "group #{group}")
    gval = grp.name if grp is not None else group_id
    sign = "−" if negative else "+"
    ctx.log(action=action, entity_type="group", entity_id=group_id,
            summary=((f"Tagged {where} {sign}{{tag}}")
                     if action == actions.ADD_GROUP_TAG
                     else f"Removed tag {{tag}} from {where}"),
            summary_vars={"group": gval, "tag": name},
            data={"group_id": group_id, "tag": name, "negative": bool(negative)})


def assign_group_tag(ctx: Ctx, group_id: int, name: str, *,
                     negative: bool = False) -> None:
    s = ctx.session
    tag = tagcatalog.get_or_create(ctx, name)
    # Group tags fan out to every item in the group's subtree (their sidecars
    # embed the group's tag list and the assignment).
    row = s.execute(select(GroupTag).where(
        GroupTag.group_id == group_id, GroupTag.tag_id == tag.id
    )).scalars().first()
    if row:
        row.negative = negative
    else:
        s.add(GroupTag(group_id=group_id, tag_id=tag.id, negative=negative))
    _log_group_tag(ctx, actions.ADD_GROUP_TAG, group_id, tag.name, negative)


def unassign_group_tag(ctx: Ctx, group_id: int, name: str) -> None:
    s = ctx.session
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if tag:
        neg = s.execute(select(GroupTag.negative).where(
            GroupTag.group_id == group_id, GroupTag.tag_id == tag.id
        )).scalars().first()
        s.execute(delete(GroupTag).where(
            GroupTag.group_id == group_id, GroupTag.tag_id == tag.id
        ))
        if neg is not None:
            _log_group_tag(ctx, actions.REMOVE_GROUP_TAG, group_id, tag.name,
                           bool(neg))


# ---- quick assign -----------------------------------------------------------


def stamp(ctx: Ctx, item_ids: list[int], positive: list[str],
          negative: list[str], *, remove: bool = False) -> int:
    """Stamp (or remove) the quick-assign tag set across a selection.

    Each distinct name resolves once and the existing assignments for the
    whole (items × tags) grid load in one chunked pass — the per-pair SELECTs
    made a large stamp two round trips per (item, tag). The per-(item, change)
    events are unchanged: the log is the contract.

    **Bulk on purpose.** Rewriting this as a loop over `assign_item_tag` is
    observably identical and a large silent regression; only
    `tests/test_perf_smoke.py` would notice.
    """
    s = ctx.session
    tags: dict[str, Tag] = {}
    for name in [*positive, *negative]:
        if name not in tags:
            tags[name] = tagcatalog.get_or_create(ctx, name)
    tag_ids = list({t.id for t in tags.values()})
    existing: dict[tuple[int, int], ItemTag] = {}
    if tag_ids:
        for chunk in chunked(item_ids):
            for row in s.execute(select(ItemTag).where(
                ItemTag.item_id.in_(chunk), ItemTag.tag_id.in_(tag_ids)
            )).scalars().all():
                existing[(row.item_id, row.tag_id)] = row

    def apply(item_id: int, name: str, neg: bool):
        tag = tags[name]
        key = (item_id, tag.id)
        row = existing.get(key)
        if remove:
            if row is not None:
                # The unassign path's rule: sweep the placements' pending
                # groups, or a dismissed suggestion strands an empty box.
                group_ids = [p.group_id for p in row.placements
                             if p.group_id is not None]
                s.delete(row)
                s.flush()
                for gid in group_ids:
                    cleanup_pending_group(ctx, gid)
                existing.pop(key, None)
                ctx.log(action=actions.REMOVE_TAG, entity_type="item",
                        entity_id=item_id,
                        summary="Removed tag {tag} from item #{item}",
                    summary_vars={"tag": name, "item": item_id},
                        data={"item_id": item_id, "tag": name,
                              "negative": neg})
                _drop_subject_group_bindings(ctx, item_id, tag.id)
            return
        if row is not None:
            row.negative = neg
            # The name-level statement covers every instance, as in
            # `assign_item_tag` — or the derived sign flips it back.
            for p in s.execute(select(ItemTagPlacement).where(
                    ItemTagPlacement.item_tag_id == row.id)).scalars().all():
                p.negative = neg
        else:
            row = ItemTag(item_id=item_id, tag_id=tag.id, negative=neg)
            s.add(row)
            existing[key] = row
        ctx.log(action=actions.ADD_TAG, entity_type="item", entity_id=item_id,
                summary=("Tagged item #{item} −{tag}" if neg
                         else "Tagged item #{item} +{tag}"),
                summary_vars={"item": item_id, "tag": name},
                data={"item_id": item_id, "tag": name, "negative": neg})

    for iid in item_ids:
        for name in positive:
            apply(iid, name, False)
        for name in negative:
            apply(iid, name, True)
    touch_items(s, item_ids)
    return len(item_ids)


# ---- approving what a model suggested ---------------------------------------


def approve_placement(ctx: Ctx, placement_id: int) -> bool:
    """Accept a pending tag: clear its pending flag and move it out of the
    auto-managed Pending group into the ungrouped default, deleting the Pending
    group once it is empty."""
    s = ctx.session
    p = s.get(ItemTagPlacement, placement_id)
    if p is None:
        raise NotFound("placement not found", code="placement_not_found")
    it_tag_id = p.item_tag_id
    it = s.get(ItemTag, it_tag_id)
    item_id = it.item_id if it is not None else None
    # Capture the tag name + pending-group name before the move, so the approval
    # can be reverted (moved back into a re-created pending group) from History.
    tag = s.get(Tag, it.tag_id) if it is not None else None
    tag_name = tag.name if tag is not None else ""
    old_group = s.get(ItemTagGroup, p.group_id) if p.group_id is not None else None
    group_name = old_group.name if old_group is not None else "Pending"
    old_group_id = p.group_id
    # Accept → move to the ungrouped default. If the tag already has an ungrouped
    # instance (e.g. the tag was already assigned), fold this one's boxes into it
    # (merging overlapping boxes) instead of creating a duplicate placement.
    merge_placement_into_group(ctx, p, None)
    s.flush()
    cleanup_pending_group(ctx, old_group_id)
    # Clear the pending flag unless another pending copy of the tag remains.
    recompute_pending(ctx, it_tag_id)
    if item_id is not None:
        touch_items(s, [item_id])
        if tag_name:
            ctx.log(action=actions.APPROVE_TAG, entity_type="item",
                    entity_id=item_id, summary="Approved AI tag +{tag}",
                        summary_vars={"tag": tag_name},
                    data={"item_id": item_id, "tag": tag_name,
                          "group_name": group_name})
    return True


def set_pending(ctx: Ctx, item_id: int, name: str, value: bool) -> bool:
    """Mark an item's tag as a machine's guess, or accept it.

    Two directions with different shapes, which is why this is not a plain
    column write. **Accepting** has to go through `approve_placement` for every
    copy of the tag sitting in an auto-managed Pending group, or the flag would
    clear while the box around the tag still said it was waiting — and that
    path is what deletes the group once it empties, and what makes the approval
    revertible. **Flagging** writes the flag alone: a placement-less pending
    tag is exactly what a face's guess produces, so there is no group to make.
    """
    s = ctx.session
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    it = None if tag is None else s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
    )).scalars().first()
    if it is None:
        raise NotFound("{name} is not on this item", {"name": repr(name)},
                       code="tag_not_on_item")
    if value:
        it.pending = True
        touch_items(s, [item_id])
        return True
    waiting = s.execute(
        select(ItemTagPlacement.id)
        .join(ItemTagGroup, ItemTagGroup.id == ItemTagPlacement.group_id)
        .where(ItemTagPlacement.item_tag_id == it.id,
               ItemTagGroup.system.is_(True))
    ).scalars().all()
    for placement_id in waiting:
        approve_placement(ctx, placement_id)
    if not waiting:
        # No Pending group to leave — a guess a face assigned, say. Clearing
        # the flag IS the approval.
        it.pending = False
        touch_items(s, [item_id])
    return True
