"""Sequences: an ordered run of items — a chapter, a film's frames, a set.

A sequence has a CONTAINER item (`Sequence.item_id`) so it can be selected,
tagged and opened like anything else in the grid, and `sequences.sync_container`
keeps that item in step. The `kind` records how it came to be — `archive`,
`video` or `manual` — and is provenance only: all sequences behave alike, but a
re-import recognises its own by it.

**The same item may sit at SEVERAL positions** (a book's blank pages all
dedup onto one item, and the sequence is what keeps the book's structure), so
the ops here speak two tag sets and say which: ``member_ids`` are
`SequenceItem` ROW ids and address one occurrence; ``item_ids`` mean every
occurrence of that item at once. Reorder is row-addressed only — an item id
cannot say WHICH copy goes where.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from ..db import Item, Sequence, SequenceItem, touch_items
from ..sequences import delete_sequence, ensure_container, sync_container
from . import actions
from .context import Ctx
from .errors import Invalid, NotFound


def _snapshot(s, seq: Sequence) -> dict:
    """Everything needed to build this sequence again.

    The CONTAINER item is not in it: it is made from the sequence
    (`ensure_container`), so a restore mints a new one rather than putting a
    deleted item back — which is why a revert here gives the sequence a new
    id as well. Anything naming the old one (a later event) no longer
    resolves, the same trade `_revert_delete_place` already makes.
    """
    rows = list(s.execute(
        select(SequenceItem).where(SequenceItem.sequence_id == seq.id)
        .order_by(SequenceItem.position, SequenceItem.id)
    ).scalars().all())
    return {
        "name": seq.name, "kind": seq.kind, "source_name": seq.source_name,
        "members": [si.item_id for si in rows],
        # Whose MAIN sequence this was — a pointer the delete cleared and
        # nothing else records.
        "main_for": [iid for iid in {si.item_id for si in rows}
                     if (it := s.get(Item, iid)) is not None
                     and it.main_sequence_id == seq.id],
    }


def create(ctx: Ctx, item_ids: list[int], *, name: str = "") -> tuple[int, int]:
    s = ctx.session
    """Create a manual sequence from the given items (in the order supplied).

    An item repeated in the list is repeated in the sequence — one position
    per entry, deliberately.
    """
    ids = [i for i in item_ids if s.get(Item, i) is not None]
    if len(ids) < 2:
        raise Invalid("a sequence needs at least two items")
    seq = Sequence(name=name or "New sequence", kind="manual",
                   source_name=name or "")
    s.add(seq)
    s.flush()
    for pos, iid in enumerate(ids):
        s.add(SequenceItem(sequence_id=seq.id, item_id=iid, position=pos))
        it = s.get(Item, iid)
        if it is not None and it.main_sequence_id is None:
            it.main_sequence_id = seq.id
    s.flush()
    container = ensure_container(s, seq)  # the sequence's library item
    touch_items(s, ids)
    ctx.log(action=actions.CREATE_SEQUENCE, entity_type="sequence",
            entity_id=seq.id, summary="Created sequence “{name}”",
            summary_vars={"name": seq.name},
            data={"sequence_id": seq.id, "sequence_name": seq.name,
                  "item_ids": ids})
    return seq.id, container.id




def remove(ctx: Ctx, seq_id: int) -> None:
    s = ctx.session
    """Remove a sequence (and its container item) without deleting its members."""
    seq = s.get(Sequence, seq_id)
    if not seq:
        raise NotFound("sequence not found")
    members = [si.item_id for si in seq.items]
    snap = _snapshot(s, seq)
    delete_sequence(s, seq)
    touch_items(s, members)
    ctx.log(action=actions.DELETE_SEQUENCE, entity_type="sequence",
            entity_id=seq_id, summary="Removed sequence “{name}”",
            summary_vars={"name": snap["name"]},
            data={"sequence_id": seq_id, "sequence_name": snap["name"],
                  "sequence": snap})






def rename(ctx: Ctx, seq_id: int, name: str) -> None:
    s = ctx.session
    seq = s.get(Sequence, seq_id)
    if not seq:
        raise NotFound("sequence not found")
    old = seq.name
    if old == name:
        return
    seq.name = name
    if seq.item_id is not None:  # keep the container item's name in sync
        container = s.get(Item, seq.item_id)
        if container is not None:
            container.name = name
    ctx.log(action=actions.RENAME_SEQUENCE, entity_type="sequence",
            entity_id=seq_id, summary="Renamed sequence “{old}” to “{name}”",
            summary_vars={"old": old, "name": name},
            data={"sequence_id": seq_id, "old_name": old, "name": name})




def reorder(ctx: Ctx, seq_id: int, item_ids: Optional[list[int]] = None, *,
            member_ids: Optional[list[int]] = None) -> None:
    """Set the sequence's order.

    ``member_ids`` (row ids) is the real tag set — it can say which COPY
    of a repeated item goes where. ``item_ids`` is kept for callers that
    think in items (the Python API's ``members.reorder``), and is refused
    the moment it turns ambiguous: with an item at two positions, a list of
    item ids cannot express the order it looks like it expresses, and the
    old implementation silently left the extra rows at stale positions.

    Either list may be partial: the named rows take the front in the given
    order, the rest keep their relative order after them.
    """
    s = ctx.session
    seq = s.get(Sequence, seq_id)
    if not seq:
        raise NotFound("sequence not found")
    rows = list(s.execute(
        select(SequenceItem).where(SequenceItem.sequence_id == seq_id)
        .order_by(SequenceItem.position, SequenceItem.id)
    ).scalars().all())

    if member_ids is None:
        by_item: dict[int, list[SequenceItem]] = {}
        for si in rows:
            by_item.setdefault(si.item_id, []).append(si)
        named = [i for i in (item_ids or []) if i in by_item]
        if any(len(by_item[i]) > 1 for i in named):
            raise Invalid(
                "that item is in the sequence more than once — reorder by "
                "member rows, which say which copy goes where")
        member_ids = [by_item[i][0].id for i in named]

    # The order as it stands, so the revert is "put the list back" — one
    # action for what is otherwise a dozen moves nobody could undo singly.
    was = [si.id for si in rows]
    by_id = {si.id: si for si in rows}
    pos = 0
    seen: set[int] = set()
    for mid in member_ids:
        si = by_id.get(mid)
        if si is None or mid in seen:
            continue
        seen.add(mid)
        si.position = pos
        pos += 1
    # Any members not named keep their relative order after the listed ones.
    for si in rows:
        if si.id not in seen:
            si.position = pos
            pos += 1
    s.flush()
    sync_container(s, seq_id)  # first member (thumbnail) may have changed
    touch_items(s, list({si.item_id for si in rows}))
    now = [si.id for si in sorted(rows, key=lambda r: (r.position, r.id))]
    if now != was:
        ctx.log(action=actions.REORDER_SEQUENCE, entity_type="sequence",
                entity_id=seq_id, summary="Reordered sequence “{name}”",
                summary_vars={"name": seq.name},
                data={"sequence_id": seq_id, "sequence_name": seq.name,
                      "old_member_ids": was, "member_ids": now})




def remove_members(ctx: Ctx, seq_id: int, item_ids: Optional[list[int]] = None,
                   *, member_ids: Optional[list[int]] = None) -> int:
    """Take members out of the sequence.

    ``member_ids`` removes those ROWS — one occurrence each, which is what a
    row's own ✕ means. ``item_ids`` removes EVERY occurrence of each item,
    which is what "take this picture out of the chapter" means. The
    main-sequence pointer is cleared only when the item's LAST row goes, and
    the survivors are renumbered densely, so a position never lies about how
    far into the sequence it is.
    """
    s = ctx.session
    seq = s.get(Sequence, seq_id)
    if not seq:
        raise NotFound("sequence not found")
    # The WHOLE sequence as it stands, because taking the last member out
    # deletes it: one snapshot covers both endings, and the revert is the
    # same "restore this sequence" either way.
    snap = _snapshot(s, seq)
    if member_ids is not None:
        doomed = [si for si in s.execute(
            select(SequenceItem).where(
                SequenceItem.sequence_id == seq_id,
                SequenceItem.id.in_(member_ids or []),
            )
        ).scalars().all()]
    else:
        doomed = [si for si in s.execute(
            select(SequenceItem).where(
                SequenceItem.sequence_id == seq_id,
                SequenceItem.item_id.in_(item_ids or []),
            )
        ).scalars().all()]
    touched = list({si.item_id for si in doomed})
    removed = 0
    for si in doomed:
        s.delete(si)
        removed += 1
    s.flush()
    # Clear a main-sequence pointer only for an item with no row LEFT — a
    # repeated page with one copy removed is still in the sequence.
    for iid in touched:
        still = s.execute(select(SequenceItem.id).where(
            SequenceItem.sequence_id == seq_id,
            SequenceItem.item_id == iid).limit(1)).first()
        if still:
            continue
        it = s.get(Item, iid)
        if it is not None and it.main_sequence_id == seq_id:
            it.main_sequence_id = None
    # Drop the sequence (and its container item) entirely if it's now empty;
    # otherwise renumber the survivors and refresh the container's borrowed
    # thumbnail.
    rest = list(s.execute(
        select(SequenceItem).where(SequenceItem.sequence_id == seq_id)
        .order_by(SequenceItem.position, SequenceItem.id)
    ).scalars().all())
    if not rest:
        delete_sequence(s, seq)
    else:
        for pos, si in enumerate(rest):
            si.position = pos
        sync_container(s, seq_id)
    touch_items(s, touched)
    if removed:
        ctx.log(
            action=actions.REMOVE_SEQUENCE_MEMBERS, entity_type="sequence",
            entity_id=seq_id,
            summary=("Removed 1 item from sequence “{name}”" if removed == 1
                     else "Removed {n} items from sequence “{name}”"),
            summary_vars={"n": str(removed), "name": snap["name"]},
            data={"sequence_id": seq_id, "sequence_name": snap["name"],
                  "removed": removed, "emptied": not rest,
                  "sequence": snap})
    return removed




def set_main(ctx: Ctx, item_id: int, sequence_id: Optional[int]) -> None:
    s = ctx.session
    item = s.get(Item, item_id)
    if not item:
        raise NotFound("item not found")
    if sequence_id is not None:
        member = s.execute(
            select(SequenceItem.id).where(
                SequenceItem.sequence_id == sequence_id,
                SequenceItem.item_id == item_id,
            )
        ).first()
        if not member:
            raise Invalid("item is not in that sequence")
    was = item.main_sequence_id
    if was == sequence_id:
        return
    item.main_sequence_id = sequence_id
    seq = s.get(Sequence, sequence_id) if sequence_id is not None else None
    ctx.log(
        action=actions.SET_MAIN_SEQUENCE, entity_type="item",
        entity_id=item_id,
        summary=("Made “{name}” the main sequence for “{item}”" if seq
                 else "Cleared the main sequence for “{item}”"),
        summary_vars={"name": seq.name if seq else "",
                      "item": item.name or str(item.uid)},
        data={"item_id": item_id, "old_sequence_id": was,
              "sequence_id": sequence_id})
