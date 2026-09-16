"""An item's own life: trash, restore, hide, delete, merge, rotate, rename.

## The two tiers, and why

Several of these come in a pair::

    trash_one(ctx, item_id)   -> bool   # the state change. Logs nothing.
    trash(ctx, item_ids)      -> int    # the OPERATION: trash_one + one event

The routers call the operation. The **revert layer calls the primitive** — and
that is the point. `history.py` used to carry its own line-for-line copy of
trash and restore (and a third, inlined in `_revert_import`) purely because it
needed the state change without the event that goes with it. With the pair,
"a revert must not write the forward event" is true by construction rather than
by a flag somebody can pass wrong.

Only genuinely identical primitives get this treatment. Most `_revert_*`
handlers restore a *recorded shape* rather than performing the action —
`_revert_remove_tag` recreates a deleted tag row where `get_or_create` would
redirect an alias — and those must keep their own implementations.
"""

from __future__ import annotations

import json as _json
from typing import Optional

from sqlalchemy import delete, select

from ..db import (
    TAKEN_NONE, Caption, File, FileArtifact, Group, Item, ItemGroup, ItemMetadata,
    ItemTag, Occasion, Relationship, Sequence, SequenceItem, Tag, TrashedItem,
    chunked, normalize_taken, touch_items,
)
from ..sequences import sync_container
from . import actions
from .context import Ctx
from .errors import NotFound, Refused

# ---- storage ----------------------------------------------------------------


def remove_item_storage(ctx: Ctx, item: Item) -> None:
    """Drop an item's on-disk folder and its files' thumbnails (call before
    deleting the row — the uid and file ids are needed)."""
    remove_items_storage(ctx, [(item.id, item.uid)])


def remove_items_storage(ctx: Ctx, rows) -> None:
    """The same for a BATCH: one query for every file id, not one per item.

    `rows` is ``(item_id, uid)`` pairs. Splitting it out is what lets the bulk
    delete below ask the database once instead of once per item — at 500 items
    a chunk that was 500 round trips for a list the caller already had the
    ids for.
    """
    s = ctx.session
    rows = list(rows)
    if not rows:
        return
    by_item: dict[int, list[int]] = {}
    for iid, fid in s.execute(
        select(File.item_id, File.id)
        .where(File.item_id.in_([r[0] for r in rows]))
    ).all():
        by_item.setdefault(iid, []).append(fid)
    for iid, uid in rows:
        for fid in by_item.get(iid, ()):
            ctx.store.drop_thumb(fid)
        ctx.store.remove_item(uid)


# ---- trash / restore --------------------------------------------------------


def trash_one(ctx: Ctx, item_id: int) -> bool:
    """Move one item to the Trash: snapshot its groups and its sequence
    memberships, then drop both so it vanishes from normal listings AND from
    the chapters it was a page of — a trashed page must not go on holding a
    place in a sequence. Logs nothing.

    **AND IT IS NO LONGER HIDDEN.** Hidden and trashed are two different
    answers to "why is this not in the grid", and an item that was both said
    both: the sidebar's Hidden badge went on counting a picture the Hidden
    view no longer showed, which is a number nothing could make agree with
    the list under it. The flag is snapshotted like the groups
    (`TrashedItem.original_hidden`), so restoring puts the item back the way
    it was rather than back in everybody's face."""
    s = ctx.session
    item = s.get(Item, item_id)
    if item is None:
        return False
    if s.execute(
        select(TrashedItem.id).where(TrashedItem.item_id == item_id)
    ).first():
        return False  # already trashed
    gids = s.execute(
        select(ItemGroup.group_id).where(ItemGroup.item_id == item_id)
    ).scalars().all()
    # One "seq:pos" per OCCURRENCE — a repeated page is several rows and must
    # come back as several. The stored POSITIONS of the survivors are left
    # alone (no renumbering): sparse positions are already a supported state
    # (the grid shows list ranks, never the stored number), and the hole is
    # exactly what lets restore put the row back where it was.
    seq_rows = s.execute(
        select(SequenceItem).where(SequenceItem.item_id == item_id)
        .order_by(SequenceItem.sequence_id, SequenceItem.position)
    ).scalars().all()
    s.add(TrashedItem(
        item_id=item_id,
        original_groups=",".join(str(g) for g in gids),
        original_sequences=",".join(
            f"{r.sequence_id}:{r.position}" for r in seq_rows),
        original_hidden=bool(item.hidden),
    ))
    item.hidden = False
    s.execute(delete(ItemGroup).where(ItemGroup.item_id == item_id))
    if seq_rows:
        touched = sorted({r.sequence_id for r in seq_rows})
        for r in seq_rows:
            s.delete(r)
        s.flush()
        # The container's borrowed thumbnail may have been this item's; its
        # sidecar carries the member list either way. A sequence emptied by
        # this is deliberately NOT deleted (remove_members' rule): restore
        # needs somewhere to put the rows back.
        containers = []
        for sid in touched:
            sync_container(s, sid)
            seq = s.get(Sequence, sid)
            if seq is not None and seq.item_id is not None:
                containers.append(seq.item_id)
        touch_items(s, containers)
        # `Item.main_sequence_id` is left ALONE: the item is invisible while
        # trashed, and the pointer heals itself the moment restore puts the
        # membership back — clearing it would need a second snapshot.
    return True


def restore_one(ctx: Ctx, item_id: int,
                existing: Optional[set[int]] = None) -> bool:
    """Put one trashed item back into the groups — and the sequences — it was
    in. Logs nothing.

    ``existing`` is the set of group ids that still exist; a bulk caller hoists
    it out of the loop, which is why it is a parameter rather than a lookup.
    """
    s = ctx.session
    row = s.execute(
        select(TrashedItem).where(TrashedItem.item_id == item_id)
    ).scalar_one_or_none()
    if row is None:
        return False
    if existing is None:
        existing = set(s.execute(select(Group.id)).scalars().all())
    # Back the way it was, hidden included — trashing is what took the flag
    # off, and a restore that left it off would put a picture somebody had
    # deliberately put away back in the middle of the grid.
    item = s.get(Item, item_id)
    if item is not None and row.original_hidden:
        item.hidden = True
    for part in row.original_groups.split(","):
        if not part.strip().isdigit():
            continue
        gid = int(part)
        if gid in existing and not s.execute(
            select(ItemGroup.id).where(
                ItemGroup.item_id == item_id, ItemGroup.group_id == gid
            )
        ).first():
            s.add(ItemGroup(item_id=item_id, group_id=gid))
    # Sequence membership, from the same snapshot idea: re-add each recorded
    # occurrence at its recorded position — the hole trash left is still
    # there when nothing reordered meanwhile, and after a reorder the value
    # still lands the row in its old neighbourhood (ranks are computed from
    # list order, so a duplicate position is a tie, not a lie). A sequence
    # deleted while the item sat in the Trash is simply skipped; NULL (a row
    # from before the column existed) recorded nothing and removes nothing.
    touched: list[int] = []
    for part in (row.original_sequences or "").split(","):
        sid_s, _, pos_s = part.partition(":")
        if not (sid_s.strip().isdigit() and pos_s.strip().isdigit()):
            continue
        sid = int(sid_s)
        seq = s.get(Sequence, sid)
        if seq is None:
            continue
        s.add(SequenceItem(sequence_id=sid, item_id=item_id,
                           position=int(pos_s)))
        touched.append(sid)
    if touched:
        s.flush()
        containers = []
        for sid in sorted(set(touched)):
            sync_container(s, sid)
            seq = s.get(Sequence, sid)
            if seq is not None and seq.item_id is not None:
                containers.append(seq.item_id)
        touch_items(s, containers)
    s.delete(row)
    return True


def trash(ctx: Ctx, item_ids: list[int]) -> int:
    s = ctx.session
    count = 0
    for iid in item_ids:
        item = s.get(Item, iid)
        if item is None or not trash_one(ctx, iid):
            continue
        ctx.log(action=actions.TRASH_ITEM, entity_type="item", entity_id=iid,
                summary="Moved “{name}” to Trash",
                summary_vars={"name": item.name},
                data={"item_id": iid, "item_name": item.name})
        count += 1
    return count


def restore(ctx: Ctx, item_ids: list[int]) -> int:
    s = ctx.session
    count = 0
    # Hoisted: `restore_one` would otherwise re-read the whole group table per
    # item, which a large restore feels.
    existing = set(s.execute(select(Group.id)).scalars().all())
    for iid in item_ids:
        if not restore_one(ctx, iid, existing):
            continue
        it = s.get(Item, iid)
        ctx.log(action=actions.RESTORE_ITEM, entity_type="item", entity_id=iid,
                summary="Restored “{name}” from Trash",
                summary_vars={"name": it.name if it else iid},
                data={"item_id": iid, "item_name": it.name if it else ""})
        count += 1
    return count


# ---- hide / delete ----------------------------------------------------------


def hide(ctx: Ctx, item_ids: list[int], hidden: bool) -> int:
    """Mark items hidden (or visible again). Hidden items drop out of the grid
    and every category count but remain in the library, reachable via links and
    the dedicated Hidden view."""
    s = ctx.session
    count = 0
    for iid in item_ids:
        item = s.get(Item, iid)
        if item is None or bool(item.hidden) == bool(hidden):
            continue
        item.hidden = bool(hidden)
        touch_items(s, [iid])
        # One combined "toggled hidden" action (carrying the resulting state)
        # rather than separate hide/unhide actions, so a mixed run groups
        # cleanly and the summary reflects the final state.
        ctx.log(action=actions.SET_HIDDEN, entity_type="item", entity_id=iid,
                summary=("Hid “{name}”" if hidden else "Showed “{name}”"),
                summary_vars={"name": item.name},
                data={"item_id": iid, "item_name": item.name,
                      "hidden": bool(hidden)})
        count += 1
    return count


def delete_items(ctx: Ctx, item_ids: list[int]) -> int:
    """Delete items (and their file/caption/tag/group rows via cascade) along
    with their on-disk folders (files and artifacts) and thumbnails.

    THE DELETE IS ONE STATEMENT PER CHUNK, not one per item, and the database
    does the cascading. `s.delete(item)` makes the ORM do it in Python: it
    loads `files`, `captions`, `tags` and `groups` for the item, then each
    file's own children, to issue a DELETE per row — about fourteen
    statements an item, which on a 250k-item library was the whole cost of a
    prune once the missing FK indexes were in (7,178 statements a chunk, of
    which the SQL itself was a tenth of a second and the ORM machinery a
    second).

    Bypassing it is safe because it is REDUNDANT rather than load-bearing:
    every one of the 31 foreign keys pointing at `items` is declared
    `ON DELETE CASCADE` or `SET NULL`, `PRAGMA foreign_keys=ON` is set by the
    connect hook, and `tests/core/test_foreign_key_indexes.py` holds the
    indexes that make the cascade cheap. What the ORM was doing in Python,
    SQLite does in C in one statement.

    What does NOT come free with a Core statement, and is therefore explicit
    here: the session's identity map would keep the deleted rows, so they
    are expunged.
    """
    from ..sequences import delete_sequence

    s = ctx.session
    ids = [i for i in dict.fromkeys(item_ids) if i is not None]
    if not ids:
        return 0

    # One query for what the loop needs, rather than `s.get` per id.
    rows: list[tuple[int, str, str, str]] = []
    for chunk in chunked(ids):
        rows.extend(s.execute(
            select(Item.id, Item.uid, Item.name, Item.kind)
            .where(Item.id.in_(chunk))
        ).all())
    if not rows:
        return 0

    remove_items_storage(ctx, [(r[0], r[1]) for r in rows])

    plain: list[int] = []
    for iid, _uid, name, kind in rows:
        if kind == "sequence":
            # Deleting a sequence container removes the sequence but keeps
            # its members, which is a rule and not a cascade — so these keep
            # the per-item path.
            seq = s.execute(
                select(Sequence).where(Sequence.item_id == iid)
            ).scalar_one_or_none()
            if seq is not None:
                delete_sequence(s, seq)
                item = s.get(Item, iid)
                if item is not None:
                    s.delete(item)
            else:
                plain.append(iid)
        else:
            plain.append(iid)
        ctx.log(action=actions.DELETE_ITEM, entity_type="item", entity_id=iid,
                summary="Permanently deleted “{name}”",
                summary_vars={"name": name},
                data={"item_id": iid, "item_name": name})

    # Flush FIRST: the events above and anything else pending must land while
    # the rows they name still exist, and `delete_sequence` leaves ORM work of
    # its own. Then the rest goes in one statement per chunk.
    s.flush()
    for chunk in chunked(plain):
        s.execute(delete(Item).where(Item.id.in_(chunk)))
    # The identity map would otherwise hand out rows the database no longer
    # has — `expire_on_commit=False` is the sessionmaker's default here, so
    # nothing would ever refresh them.
    for iid, _uid, _name, _kind in rows:
        obj = s.identity_map.get(s.identity_key(Item, iid))
        if obj is not None:
            s.expunge(obj)
    return len(rows)


def empty_trash(ctx: Ctx) -> int:
    """Permanently delete *every* trashed item (regardless of current filter),
    along with each item's on-disk folder and thumbnails."""
    s = ctx.session
    ids = list(s.execute(select(TrashedItem.item_id)).scalars().all())
    count = 0
    for iid in ids:
        item = s.get(Item, iid)
        if item is not None:
            name = item.name
            remove_item_storage(ctx, item)
            # cascades files, captions, tags, memberships, trash row
            s.delete(item)
            # The same per-item event `delete_items` writes: this is the most
            # destructive action in the app, and it was the only one that
            # left nothing in the log.
            ctx.log(action=actions.DELETE_ITEM, entity_type="item",
                    entity_id=iid,
                    summary="Permanently deleted “{name}”",
                    summary_vars={"name": name},
                    data={"item_id": iid, "item_name": name})
            count += 1
    s.flush()
    return count


# ---- update / rotate --------------------------------------------------------


def update(ctx: Ctx, item_id: int, *, name: Optional[str] = None,
           active_file_id: Optional[int] = None,
           link_item_id: Optional[int] = None,
           taken_at: Optional[int] = None,
           lat: Optional[float] = None,
           lon: Optional[float] = None,
           clear_coords: bool = False,
           no_coords: bool = False) -> Item:
    s = ctx.session
    item = s.get(Item, item_id)
    if not item:
        raise NotFound("item not found", code="item_not_found")
    if name is not None:
        item.name = name
        # If this item is a sequence's container, keep the Sequence row's name
        # in sync too (the reverse of rename_sequence) so its members'
        # "belongs to" panels show the new name.
        if item.kind == "sequence":
            seq = s.execute(
                select(Sequence).where(Sequence.item_id == item_id)
            ).scalars().first()
            if seq is not None:
                seq.name = name
    if active_file_id is not None:
        # Switching the active source file is a revertible history change.
        if active_file_id != item.active_file_id:
            ctx.log(action=actions.SET_ACTIVE_FILE, entity_type="item",
                    entity_id=item_id, summary="Changed the active source file",
                    data={"item_id": item_id,
                          "prev_active_file_id": item.active_file_id,
                          "new_active_file_id": active_file_id})
        item.active_file_id = active_file_id
    if link_item_id is not None:
        item.link_item_id = link_item_id
    if taken_at is not None:
        was = item.taken_at
        # 0 clears the override and falls back; -1 SAYS there is no date. A
        # date-width YYYYMMDD is widened to the column's YYYYMMDDHHMMSS here,
        # at the one choke point every writer passes through — the router, the
        # Python API and any script land in this function.
        item.taken_at = normalize_taken(taken_at) or None
        if item.taken_at != was:
            ctx.log(action=actions.SET_TAKEN, entity_type="item",
                    entity_id=item_id,
                    summary=("Said this item has no date"
                             if item.taken_at == TAKEN_NONE
                             else "Dated this item" if item.taken_at
                             else "Took the date off this item"),
                    data={"item_id": item_id, "taken_at": item.taken_at,
                          "old_taken_at": was})
    # WHERE it was taken — the same three states, and the same reasons.
    # `clear_coords` falls back to the file, `no_coords` says there is none.
    if clear_coords or no_coords or (lat is not None and lon is not None):
        from ..db import COORD_NONE

        old = (item.lat, item.lon)
        if clear_coords:
            item.lat = item.lon = None
        elif no_coords:
            item.lat, item.lon = COORD_NONE, None
        else:
            item.lat, item.lon = float(lat), float(lon)
        if (item.lat, item.lon) != old:
            ctx.log(action=actions.SET_COORDS, entity_type="item",
                    entity_id=item_id,
                    summary=("Said this item has no coordinates"
                             if item.lat == COORD_NONE
                             else "Placed this item" if item.lat is not None
                             else "Took the coordinates off this item"),
                    data={"item_id": item_id, "lat": item.lat, "lon": item.lon,
                          "old_lat": old[0], "old_lon": old[1]})
    touch_items(s, [item_id])
    return item


def rotate(ctx: Ctx, item_id: int, direction: str = "right") -> dict:
    """Rotate the item's *active* image 90° left/right.

    The rotation applies to whichever file is active: an already-edited/derived
    file is overwritten in place (rotating it further), while a pristine
    imported original is preserved — rotating it branches to a new derived file
    that records it's based on the original (via a "rotate" action). Either way
    the active file's control-image artifacts are rotated to stay aligned.
    Rotation is a lossless quarter-turn, so repeated rotations never degrade
    the image.
    """
    from ..fileops import (
        copy_rotated_artifacts, record_edit, rotate_active_file,
        rotate_file_artifacts,
    )

    s = ctx.session
    item = s.get(Item, item_id)
    if item is None or item.active_file_id is None:
        raise NotFound("item not found", code="item_not_found")
    active = s.get(File, item.active_file_id)
    if active is None or not active.path:
        raise NotFound("active file not found", code="active_file_missing")
    delta = 90 if direction == "right" else -90
    prev_active = active.id

    if active.is_derived:
        # Already an edited/derived file → rotate it in place (overwrite).
        rotate_active_file(s, ctx.store, active, delta, in_place=True)
        rotate_file_artifacts(s, ctx.store, active.id, active.id, delta)
        new_active = active.id
        new_rot = active.rotation
    else:
        # A pristine imported original → branch to a new rotated derived file
        # so the original is preserved; the new file records what it's based on
        # and gets rotated copies of the original's artifacts.
        rot_file = rotate_active_file(s, ctx.store, active, delta,
                                      in_place=False)
        record_edit(s, item_id, active, rot_file, "rotate")
        item.active_file_id = rot_file.id
        copy_rotated_artifacts(s, ctx.store, active.id, rot_file.id, delta)
        new_active = rot_file.id
        new_rot = rot_file.rotation

    touch_items(s, [item_id])
    ctx.log(action=actions.ROTATE_ITEM, entity_type="item", entity_id=item_id,
            summary=("Rotated “{name}” right" if delta > 0
                     else "Rotated “{name}” left"),
            summary_vars={"name": item.name},
            data={"item_id": item_id, "delta": delta, "rotation": new_rot,
                  "prev_active_file_id": prev_active,
                  "active_file_id": new_active})
    return {"rotation": new_rot, "active_file_id": new_active}


# ---- group membership -------------------------------------------------------


def add_to_group(ctx: Ctx, item_id: int, group_id: int) -> None:
    from . import smartgroups

    smartgroups.ensure_assignable(ctx, [group_id])
    s = ctx.session
    exists = s.execute(
        select(ItemGroup.id).where(
            ItemGroup.item_id == item_id, ItemGroup.group_id == group_id
        )
    ).first()
    if not exists:
        s.add(ItemGroup(item_id=item_id, group_id=group_id))
        g = s.get(Group, group_id)
        ctx.log(action=actions.ADD_TO_GROUP, entity_type="item",
                entity_id=item_id,
                summary="Added item #{item} to group “{group}”",
                summary_vars={"item": item_id,
                              "group": g.name if g else group_id},
                data={"item_id": item_id, "group_id": group_id,
                      "group_name": g.name if g else ""})
    touch_items(s, [item_id])


def remove_from_group(ctx: Ctx, item_id: int, group_id: int) -> None:
    from . import smartgroups

    smartgroups.ensure_assignable(ctx, [group_id])
    s = ctx.session
    existed = s.execute(select(ItemGroup.id).where(
        ItemGroup.item_id == item_id, ItemGroup.group_id == group_id
    )).first()
    s.execute(delete(ItemGroup).where(
        ItemGroup.item_id == item_id, ItemGroup.group_id == group_id
    ))
    if existed:
        g = s.get(Group, group_id)
        ctx.log(action=actions.REMOVE_FROM_GROUP, entity_type="item",
                entity_id=item_id,
                summary="Removed item #{item} from group “{group}”",
                summary_vars={"item": item_id,
                              "group": g.name if g else group_id},
                data={"item_id": item_id, "group_id": group_id,
                      "group_name": g.name if g else ""})
    touch_items(s, [item_id])


# ---- merge ------------------------------------------------------------------


def merge(ctx: Ctx, source_id: int, target_id: int) -> int:
    """Fold ``source_id`` into ``target_id``: move its files, group memberships,
    tags and captions onto the target, then delete the (now empty) source."""
    from sqlalchemy import func

    s = ctx.session
    if source_id == target_id:
        raise Refused("cannot merge an item into itself", code="merge_self")
    source = s.get(Item, source_id)
    target = s.get(Item, target_id)
    if source is None or target is None:
        raise NotFound("item not found", code="item_not_found")
    if source.kind == "sequence" or target.kind == "sequence":
        raise Refused("sequence items cannot be merged", code="merge_sequence")

    # Snapshot everything the merge moves/removes so it can be reverted from
    # the History (recreating the source item and putting its data back).
    source_name = source.name
    source_active = source.active_file_id
    target_active_prev = target.active_file_id
    # Preserve the source's dates so a revert restores it in place (import-date
    # sorts) instead of floating the recreated item to the top as brand new.
    source_created_at = source.created_at.isoformat() if source.created_at else None
    source_last_imported_at = (
        source.last_imported_at.isoformat() if source.last_imported_at else None
    )
    source_updated_at = source.updated_at.isoformat() if source.updated_at else None
    # Relationships touching the source, captured before its deletion cascades
    # them away (restored on revert, remapping the old source id).
    source_rels = [
        {"from": r.from_item_id, "to": r.to_item_id, "kind": r.kind,
         "meta": r.meta or ""}
        for r in s.execute(select(Relationship).where(
            (Relationship.from_item_id == source_id)
            | (Relationship.to_item_id == source_id)
        )).scalars().all()
    ]

    # Files: reassign to the target (they carry their own FileName rows). Doing
    # this before deleting the source keeps them out of the cascade. Numbers are
    # shifted past the target's current maximum (collision-free, and relative
    # history — including references to already-deleted files — is preserved by
    # shifting each file's ``edit_chain`` by the same offset). Bytes and
    # artifacts physically move into the target's folder.
    off = int(s.execute(
        select(func.coalesce(func.max(File.number), 0))
        .where(File.item_id == target_id)
    ).scalar_one())
    moved_file_ids: list[int] = []
    src_files = s.execute(
        select(File).where(File.item_id == source_id)
        .order_by(File.number, File.id)
    ).scalars().all()
    for f in src_files:
        new_number = (f.number or 0) + off
        if f.path:
            ext = f.path.rsplit(".", 1)[-1] if "." in f.path else (f.format or "bin")
            _dst, new_rel = ctx.store.file_target(target.uid, new_number, ext)
            ctx.store.move_file(source.uid, target.uid, f.path, new_rel)
            f.path = new_rel
        if f.edit_chain:
            steps = _json.loads(f.edit_chain)
            for step in steps:
                if step.get("from") is not None:
                    step["from"] += off
                if step.get("to") is not None:
                    step["to"] += off
            f.edit_chain = _json.dumps(steps)
        f.number = new_number
        f.item_id = target_id
        # Artifacts ride along: fix the denormalized item id and move/rename
        # their bytes (the filename embeds the owning file's number).
        for art in s.execute(
            select(FileArtifact).where(FileArtifact.file_id == f.id)
        ).scalars().all():
            if art.path:
                old_arel = art.path
                aext = old_arel.rsplit(".", 1)[-1] if "." in old_arel else "png"
                data = ctx.store.file_path(source.uid, old_arel).read_bytes()
                art.path = ctx.store.write_artifact(
                    target.uid, new_number, art.kind, aext, data, art.model
                )
                ctx.store.remove_file(source.uid, old_arel)
            art.item_id = target_id
        moved_file_ids.append(f.id)

    # Groups: union (skip memberships the target already has).
    added_group_ids: list[int] = []
    tgt_groups = set(s.execute(
        select(ItemGroup.group_id).where(ItemGroup.item_id == target_id)
    ).scalars().all())
    for gid in s.execute(
        select(ItemGroup.group_id).where(ItemGroup.item_id == source_id)
    ).scalars().all():
        if gid not in tgt_groups:
            s.add(ItemGroup(item_id=target_id, group_id=gid))
            tgt_groups.add(gid)
            added_group_ids.append(gid)

    # Tags: keep the target's assignment when both carry the same tag (target
    # wins on a sign conflict); otherwise move the source's assignment over.
    moved_tags: list[dict] = []
    tgt_tag_ids = set(s.execute(
        select(ItemTag.tag_id).where(ItemTag.item_id == target_id)
    ).scalars().all())
    for row in s.execute(
        select(ItemTag).where(ItemTag.item_id == source_id)
    ).scalars().all():
        if row.tag_id not in tgt_tag_ids:
            row.item_id = target_id
            tgt_tag_ids.add(row.tag_id)
            moved_tags.append({"tag_id": row.tag_id,
                               "negative": bool(row.negative)})

    # Captions: append the source's, skipping exact-text duplicates.
    moved_caption_ids: list[int] = []
    tgt_texts = {c.text.strip() for c in target.captions}
    pos = max((c.position for c in target.captions), default=-1)
    for c in s.execute(
        select(Caption).where(Caption.item_id == source_id)
    ).scalars().all():
        if c.text.strip() in tgt_texts:
            continue
        pos += 1
        c.item_id = target_id
        c.position = pos
        tgt_texts.add(c.text.strip())
        moved_caption_ids.append(c.id)

    # Clear the source's active-file pointer so deleting it can't cascade a file
    # we just moved, then remove any leftover source rows and the item itself
    # (its folder is empty now — every file moved to the target).
    source_uid = source.uid
    source.active_file_id = None
    s.flush()
    s.execute(delete(ItemTag).where(ItemTag.item_id == source_id))
    s.execute(delete(ItemGroup).where(ItemGroup.item_id == source_id))
    s.delete(source)
    ctx.store.remove_item(source_uid)

    # The largest surviving file becomes the target's active version.
    remaining = s.execute(
        select(File).where(File.item_id == target_id)
    ).scalars().all()
    if remaining and target.active_file_id not in {f.id for f in remaining}:
        target.active_file_id = max(remaining,
                                    key=lambda f: f.width * f.height).id

    ctx.log(
        action=actions.MERGE_ITEM, entity_type="item", entity_id=target_id,
        summary="Merged {source} into {target}",
        summary_vars={"source": source_name, "target": target.name},
        data={
            "source_id": source_id, "source_name": source_name,
            "target_id": target_id,
            "source_active_file_id": source_active,
            "target_active_prev": target_active_prev,
            "source_created_at": source_created_at,
            "source_last_imported_at": source_last_imported_at,
            "source_updated_at": source_updated_at,
            "moved_file_ids": moved_file_ids,
            "added_group_ids": added_group_ids,
            "moved_tags": moved_tags, "moved_caption_ids": moved_caption_ids,
            "source_rels": source_rels,
        },
    )
    touch_items(s, [target_id])
    return target_id


def taken_of(s, item: Item) -> tuple[Optional[int], str]:
    """When the picture was taken, and which of the three answers it is.

    Lives HERE, below both callers, because two of them need the same answer:
    the item detail the sidebar renders, and `Item.taken_effective` in the
    Python API. It sat in the items ROUTER, so the public API imported from a
    request handler — the inverted layering the ops extraction exists to
    remove, reintroduced by the one read the API could not compute itself.

    The same order the search reads: what somebody typed, then the indexed
    EXIF date, then the span of the events the picture carries. The source
    travels with the value because "1975, because that is when the convention
    was" is a different claim from "1975, because the camera said so", and the
    sidebar has to be able to say which.

    "None, and that is the answer" is its own source (`TAKEN_NONE` → "never"),
    distinct from the empty source, which means nothing anywhere knew.
    """
    if item.taken_at == TAKEN_NONE:
        return None, "never"
    if item.taken_at:
        return item.taken_at, "set"
    # Pin first, then the active file's EXIF — `effective_nums` is where that
    # precedence lives, shared with the two other readers of this value.
    from ..itemmeta import effective_num

    row = effective_num(s, item.id, "date_taken")
    if row:
        return int(row), "exif"
    spans = [
        x for start, end in s.execute(
            select(Occasion.start_date, Occasion.end_date)
            .join(Tag, Tag.id == Occasion.tag_id)
            .join(ItemTag, (ItemTag.tag_id == Tag.id)
                           & (ItemTag.item_id == item.id))
            .where(ItemTag.negative.is_(False))
        ).all() for x in (start, end) if x
    ]
    if spans:
        return min(spans) * 1_000_000, "event"
    return None, ""


def coords_of(s, item: Item) -> tuple[Optional[float], Optional[float], str]:
    """Where the item was taken, and which answer it is — `taken_of`'s shape.

    What somebody TYPED first, then the file's own GPS. The third state is
    ``COORD_NONE`` in the latitude: "somebody looked and there is none", which
    is how a wrong fix off a borrowed camera is removed rather than merely
    replaced — clearing the pair falls back to the file, so without it there
    would be no way to say the file is wrong.

    The file's answer comes from the indexed ``gps_lat``/``gps_lon`` metadata
    (what the active file's EXIF says), with the UNNAMED place an item may be
    PINNED to (`ItemLocation`) read first — a pin is a statement somebody kept
    (or accepted from the file's suggestion), where the metadata is merely
    what the camera wrote. A NAMED place is not read here, because that is a
    claim about the place and this is a claim about the picture.
    """
    from ..db import ItemLocation, Location, COORD_NONE

    if item.lat == COORD_NONE:
        return None, None, "never"
    if item.lat is not None and item.lon is not None:
        return item.lat, item.lon, "set"
    row = s.execute(
        select(Location.lat, Location.lon)
        .join(ItemLocation, ItemLocation.location_id == Location.id)
        .where(ItemLocation.item_id == item.id,
               Location.lat.is_not(None))
        .order_by(Location.id)
    ).first()
    if row:
        return float(row[0]), float(row[1]), "exif"
    from ..itemmeta import effective_num

    lat = effective_num(s, item.id, "gps_lat")
    lon = effective_num(s, item.id, "gps_lon")
    if lat is not None and lon is not None:
        return float(lat), float(lon), "exif"
    return None, None, ""
