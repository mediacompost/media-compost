"""Library modification log (the History view) — shared by web and CLI.

Every meaningful mutation appends one :class:`Event`. Events are fine-grained so
the UI can group similar consecutive ones into a single summary row (and expand
them again). The payload is structured JSON so an action can be linked to the
entities it touched, reverted where invertible, and diffed between two points in
time later on.

Only clearly-invertible, low-risk actions are revertible here (tag assignments,
group membership, a just-created group). Destructive or bulk actions (deleting
items, deleting a group, an import) are recorded but not revertible from History;
trashing/restoring items is reversed through the Trash, not here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .fillvars import fillvars
from .resolve import tag_implications
from .db import (
    Caption, Event, File, FileArtifact, FileName, Group, GroupParent, Item,
    ItemGroup, ItemTag, ItemTagBox, ItemTagGroup, ItemTagPlacement,
    Relationship, RelationshipTag, Tag, next_file_number, touch_items,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def log_event(
    session: Session,
    *,
    source: str,
    action: str,
    entity_type: str = "",
    entity_id: Optional[int] = None,
    summary: str = "",
    summary_vars: Optional[dict] = None,
    data: Optional[dict] = None,
) -> Event:
    """Append one event to the log (does not commit).

    ``summary`` is a fixed English TEMPLATE — ``{placeholders}`` filled from
    ``summary_vars`` — and the row stores both halves: the filled sentence in
    ``summary`` (byte-identical to what the old f-strings wrote, which is what
    keeps ``tests/golden/history_events.json`` a record of insertions) and the
    template + values beside it, so the History view can re-say the sentence
    in another language. A summary with no vars is its own template and the
    columns stay empty, exactly as every pre-existing row reads.

    A var may itself be ``{"key": …, "vars": …, "text": …}`` — a nested
    template. The English fill uses its ``text``; the UI resolver translates
    the inner key and fills recursively. One case needs it: "Reverted:
    {summary}", where the inner sentence has a template of its own.

    The acting user is read from ``session.info["username"]`` — set per request by
    ``get_session`` and, for off-request writers (AI jobs, imports), from the
    username captured when the work was enqueued. Empty means anonymous / CLI.
    """
    fill = {k: (v["text"] if isinstance(v, dict) else v)
            for k, v in (summary_vars or {}).items()}
    stored = {k: (v if isinstance(v, dict) else str(v))
              for k, v in (summary_vars or {}).items()}
    ev = Event(
        source=source,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=fillvars(summary, fill),
        summary_key=summary if summary_vars else "",
        summary_vars=json.dumps(stored) if summary_vars else "",
        data=json.dumps(data or {}),
        username=session.info.get("username", ""),
    )
    session.add(ev)
    return ev


def load_data(ev: Event) -> dict:
    try:
        val = json.loads(ev.data) if ev.data else {}
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


# ---- revert ---------------------------------------------------------------
#
# Each handler undoes one action given its recorded ``data``. It returns True on
# success (the event is then marked reverted) or False when it could not be
# applied (e.g. the target entity is gone) — the event is left untouched so the
# UI can report that it couldn't be reverted.

def _revert_add_tag(s: Session, d: dict) -> bool:
    tag = s.execute(select(Tag).where(Tag.name == d.get("tag"))).scalars().first()
    if tag is None or d.get("item_id") is None:
        return False
    s.execute(delete(ItemTag).where(
        ItemTag.item_id == d["item_id"], ItemTag.tag_id == tag.id
    ))
    # A Core delete: the representative row went by cascade, the tag may be
    # short — settled here, since the flush listener never sees it.
    from . import representatives
    representatives.settle(s, [tag.id])
    return True


def _revert_remove_tag(s: Session, d: dict) -> bool:
    """Put a tag back on an item — with the SHAPE it had.

    An assignment is more than its existence: it sits in particular per-item
    tag groups, and each of those placements carries its own boxes and time
    ranges (a film tag is nothing but its ranges). Events written before this
    carry no `placements` and simply restore the bare assignment."""
    if d.get("item_id") is None or not d.get("tag"):
        return False
    item_id = d["item_id"]
    tag = s.execute(select(Tag).where(Tag.name == d["tag"])).scalars().first()
    if tag is None:
        tag = Tag(name=d["tag"])
        s.add(tag)
        s.flush()
    it = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
    )).scalars().first()
    if it is None:
        it = ItemTag(item_id=item_id, tag_id=tag.id,
                     negative=bool(d.get("negative")), pending=bool(d.get("pending")))
        s.add(it)
        s.flush()
    for snap in d.get("placements") or []:
        gid = None
        gname = snap.get("group")
        if gname:
            grp = s.execute(select(ItemTagGroup).where(
                ItemTagGroup.item_id == item_id, ItemTagGroup.name == gname
            )).scalars().first()
            if grp is None:
                pos = s.execute(
                    select(func.count()).select_from(ItemTagGroup)
                    .where(ItemTagGroup.item_id == item_id)
                ).scalar_one()
                grp = ItemTagGroup(item_id=item_id, name=gname,
                                   system=bool(snap.get("system")), position=pos)
                s.add(grp)
                s.flush()
            gid = grp.id
        p = s.execute(select(ItemTagPlacement).where(
            ItemTagPlacement.item_tag_id == it.id,
            ItemTagPlacement.group_id.is_(gid) if gid is None
            else ItemTagPlacement.group_id == gid,
        )).scalars().first()
        if p is None:
            p = ItemTagPlacement(item_tag_id=it.id, group_id=gid,
                                 negative=bool(snap.get(
                                     "negative", d.get("negative", False))))
            s.add(p)
            s.flush()
        for b in snap.get("boxes") or []:
            s.add(ItemTagBox(
                placement_id=p.id, x=b.get("x"), y=b.get("y"),
                w=b.get("w"), h=b.get("h"),
                time_start=b.get("time_start"), time_end=b.get("time_end"),
                track_id=b.get("track_id"), negative=bool(b.get("negative")),
                points=b.get("points"),
            ))
    return True


def _revert_add_to_group(s: Session, d: dict) -> bool:
    if d.get("item_id") is None or d.get("group_id") is None:
        return False
    s.execute(delete(ItemGroup).where(
        ItemGroup.item_id == d["item_id"], ItemGroup.group_id == d["group_id"]
    ))
    return True


def _revert_remove_from_group(s: Session, d: dict) -> bool:
    if d.get("item_id") is None or d.get("group_id") is None:
        return False
    if s.get(Group, d["group_id"]) is None:
        return False  # the group is gone, nothing to rejoin
    exists = s.execute(select(ItemGroup).where(
        ItemGroup.item_id == d["item_id"], ItemGroup.group_id == d["group_id"]
    )).first()
    if not exists:
        s.add(ItemGroup(item_id=d["item_id"], group_id=d["group_id"]))
    return True


def _revert_approve_caption(s: Session, d: dict) -> bool:
    """Undo approving a machine caption — put it back to pending."""
    c = s.get(Caption, d.get("caption_id"))
    if c is None:
        return False
    c.pending = True
    return True


def _revert_edit_caption(s: Session, d: dict) -> bool:
    """Undo a caption text edit — restore the previous text (and its pending /
    edited flags as they were before the edit)."""
    c = s.get(Caption, d.get("caption_id"))
    if c is None or "old_text" not in d:
        return False
    c.text = d["old_text"]
    c.pending = bool(d.get("was_pending"))
    c.edited = bool(d.get("was_edited"))
    return True


def _revert_approve_tag(s: Session, d: dict) -> bool:
    """Undo approving a pending tag — move its (now ungrouped) instance back into
    a re-created pending group and mark it pending again."""
    item_id = d.get("item_id")
    name = d.get("tag")
    gname = d.get("group_name") or "Pending"
    if item_id is None or not name:
        return False
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if tag is None:
        return False
    it = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
    )).scalars().first()
    if it is None:
        return False
    grp = s.execute(select(ItemTagGroup).where(
        ItemTagGroup.item_id == item_id, ItemTagGroup.system.is_(True),
        ItemTagGroup.name == gname,
    )).scalars().first()
    if grp is None:
        pos = s.execute(
            select(func.count()).select_from(ItemTagGroup)
            .where(ItemTagGroup.item_id == item_id)
        ).scalar_one()
        grp = ItemTagGroup(item_id=item_id, name=gname, system=True, position=pos)
        s.add(grp)
        s.flush()
    # Move the tag's ungrouped instance (where approve left it) into the group.
    p = s.execute(select(ItemTagPlacement).where(
        ItemTagPlacement.item_tag_id == it.id, ItemTagPlacement.group_id.is_(None)
    )).scalars().first()
    if p is not None:
        p.group_id = grp.id
    else:
        s.add(ItemTagPlacement(item_tag_id=it.id, group_id=grp.id))
    it.pending = True
    return True


def _revert_add_caption(s: Session, d: dict) -> bool:
    c = s.get(Caption, d.get("caption_id"))
    if c is None:
        return False
    s.delete(c)
    return True


def _revert_remove_caption(s: Session, d: dict) -> bool:
    """Put a removed caption back — with its SHAPE, not just its text.

    Provenance, flags, meta tags, position, kind and an instruction's ordered
    reference images all travel in the event now; an event written before they
    did falls back to a bare caption at the end of the list, which is all its
    payload can say.
    """
    from .db import CaptionRef, CaptionTag

    if d.get("item_id") is None:
        return False
    pos = d.get("position")
    if pos is None:
        pos = (s.execute(
            select(func.coalesce(func.max(Caption.position), -1))
            .where(Caption.item_id == d["item_id"])
        ).scalar_one()) + 1
    cap = Caption(item_id=d["item_id"], text=d.get("text", ""), position=pos,
                  kind=d.get("kind") or "caption",
                  pending=bool(d.get("pending")), model=d.get("model") or "",
                  edited=bool(d.get("edited")))
    s.add(cap)
    s.flush()
    for name in d.get("tags") or []:
        s.add(CaptionTag(caption_id=cap.id, name=name))
    # An instruction without its sources is a sentence pointing at nothing, so
    # the order comes back with it. A reference whose item has since gone is
    # dropped rather than failing the whole revert.
    pos_ref = 0
    for iid in d.get("refs") or []:
        if s.get(Item, iid) is None:
            continue
        s.add(CaptionRef(caption_id=cap.id, item_id=iid, position=pos_ref))
        pos_ref += 1
    return True


def _apply_caption_refs(s: Session, caption_id, item_ids) -> bool:
    """Write an instruction's reference list, in order — the primitive both
    directions of the undo use (revert writes the old list, redo the new)."""
    from .db import CaptionRef

    cap = s.get(Caption, caption_id)
    if cap is None:
        return False
    s.execute(delete(CaptionRef).where(CaptionRef.caption_id == cap.id))
    s.flush()
    pos = 0
    for iid in item_ids or []:
        if s.get(Item, iid) is None:
            continue
        s.add(CaptionRef(caption_id=cap.id, item_id=iid, position=pos))
        pos += 1
    return True


def _revert_set_caption_refs(s: Session, d: dict) -> bool:
    return _apply_caption_refs(s, d.get("caption_id"), d.get("old_refs") or [])


def _redo_set_caption_refs(s: Session, d: dict) -> bool:
    return _apply_caption_refs(s, d.get("caption_id"), d.get("refs") or [])


def _set_hidden(s: Session, d: dict, value: bool) -> bool:
    it = s.get(Item, d.get("item_id"))
    if it is None:
        return False
    it.hidden = value
    return True


def _revert_set_hidden(s: Session, d: dict) -> bool:
    """Undo a combined hide/show toggle: restore the opposite of what it set."""
    return _set_hidden(s, d, not bool(d.get("hidden")))


def _revert_import(s: Session, d: dict) -> bool:
    """Undo an import by moving the items it created into the Trash (reversible).

    Only items recorded on the event (``imported_item_ids``) are trashed — never
    pre-existing dedup targets. Items already trashed/gone are skipped. Older
    import events without the id list can't be reverted."""
    ids = d.get("imported_item_ids") or []
    tagged = d.get("tagged") or []
    if not ids and not tagged:
        return False
    from .ops import ctx_for, items as ops_items

    ctx = ctx_for(s)
    did = any(ops_items.trash_one(ctx, iid) for iid in ids)
    # The run's own tags, on new AND matched items — the created items are
    # in the Trash now, but a duplicate the run merely tagged is not, and
    # its tag came from this run. Only rows still standing come off.
    for pair in tagged:
        try:
            iid, tid = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        row = s.execute(select(ItemTag).where(
            ItemTag.item_id == iid, ItemTag.tag_id == tid)).scalars().first()
        if row is not None:
            s.delete(row)
            did = True
    if tagged:
        s.flush()
    return did


def _revert_trash_item(s: Session, d: dict) -> bool:
    """Undo a trash by restoring the item to its original groups — only while it
    is still in the Trash (a permanently-deleted item can't be brought back)."""
    from .ops import ctx_for, items as ops_items

    iid = d.get("item_id")
    return ops_items.restore_one(ctx_for(s), iid) if iid is not None else False


def _revert_restore_item(s: Session, d: dict) -> bool:
    """Undo a restore-from-trash by moving the item back into the Trash."""
    from .ops import ctx_for, items as ops_items

    iid = d.get("item_id")
    return ops_items.trash_one(ctx_for(s), iid) if iid is not None else False


def _revert_rotate_item(s: Session, d: dict) -> bool:
    """Undo a rotate: reactivate the file that was active, and drop the one the
    rotate branched off.

    Rotating a pristine original does not turn it — it BRANCHES, writing a new
    derived file with the turned pixels and making that active, so the import
    is preserved. Restoring `active_file_id` alone therefore left that file in
    the item's Source list for ever: undo a rotate and the picture looked right
    while the Files tab had grown an entry nobody asked for, and every
    rotate/undo pair added another.

    Rotating an already-derived file overwrites it in place, so there is
    nothing to drop and the only way back is turning the pixels the other way
    — which needs the store (`revert_event(store=...)` puts it on the
    session). Without one that case is REFUSED rather than silently claimed:
    this handler used to re-assign `active_file_id` to itself and return
    True, striking the event through while the picture stayed rotated.

    A branched file's row is deleted; its BYTES are left to
    `ItemStore.prune_all`, which exists to sweep exactly these strays.
    """
    prev = d.get("prev_active_file_id")
    if prev is None:
        return False
    item = s.get(Item, d.get("item_id"))
    file = s.get(File, prev)
    if item is None or file is None:
        return False
    made = d.get("active_file_id")
    if made == prev:
        store = s.info.get("revert_store")
        delta = d.get("delta")
        if store is None or not delta:
            return False
        from .fileops import rotate_active_file, rotate_file_artifacts

        rotate_active_file(s, store, file, -delta, in_place=True)
        rotate_file_artifacts(s, store, file.id, file.id, -delta)
        touch_items(s, [item.id])
        return True
    item.active_file_id = prev
    if made and made != prev:
        _drop_branched_file(s, made, prev)
    return True


def _drop_branched_file(s: Session, file_id: int, parent_id: int) -> None:
    """Delete a file an edit branched off, when nothing has claimed it since.

    Every guard here is a way the file could have stopped being "the thing that
    rotate just made": somebody edited it further, another item adopted it, or
    the id was reused. Any of those and it stays — a stale extra file in a list
    is a blemish, deleting somebody's work is not.
    """
    f = s.get(File, file_id)
    if f is None or not f.is_derived or f.derived_from_file_id != parent_id:
        return
    derived_from_it = s.execute(select(File.id).where(
        File.derived_from_file_id == file_id).limit(1)).first()
    if derived_from_it is not None:
        return
    if s.execute(select(Item.id).where(
        Item.active_file_id == file_id).limit(1)).first() is not None:
        return
    item_id = f.item_id
    s.delete(f)   # cascades FileName + FileArtifact rows
    s.flush()
    touch_items(s, [item_id])


def _tag_by(s: Session, d: dict) -> Optional[Tag]:
    tag = s.get(Tag, d["tag_id"]) if d.get("tag_id") else None
    if tag is None and d.get("name"):
        tag = s.execute(select(Tag).where(Tag.name == d["name"])).scalars().first()
    return tag


def _revert_create_tag(s: Session, d: dict) -> bool:
    """Undo creating a tag — delete it, but only while it isn't assigned to any
    item (an added tag that has since been assigned can't be dropped safely)."""
    tag = _tag_by(s, d)
    if tag is None:
        return True  # already gone
    if s.execute(select(ItemTag.id).where(ItemTag.tag_id == tag.id).limit(1)).first():
        return False  # now assigned to items — not revertible
    s.delete(tag)
    return True


# ---- subjects --------------------------------------------------------------
#
# A subject is extra data on a tag, so its tag-side changes (rename, merge, the
# assignments a back-fill writes) already revert through the tag handlers above.
# What is left here is the identity itself.

def _subject_by(s: Session, d: dict):
    from .db import Subject

    return s.get(Subject, d["subject_id"]) if d.get("subject_id") else None


def _revert_create_subject(s: Session, d: dict) -> bool:
    """Undo creating a subject. Its tag stays — it is an ordinary tag now, and
    may already be on items; only the identity goes."""
    subject = _subject_by(s, d)
    if subject is None:
        return True  # already gone
    s.delete(subject)
    return True


def _revert_delete_subject(s: Session, d: dict) -> bool:
    """Undo deleting a subject — the identity comes back pointing at the same
    tag, unless another subject has claimed it in the meantime (one tag, one
    subject)."""
    from .db import Subject, Tag

    if _subject_by(s, d) is not None:
        return True  # already back
    tag_id = d.get("tag_id")
    # By NAME first. A tag deleted alongside the subject comes back under a new
    # rowid when ITS deletion is reverted, so the stored id names nothing —
    # which left the identity with no tag at all, the very thing the revert was
    # supposed to put back.
    name = d.get("tag_name") or ""
    again = (s.execute(select(Tag).where(Tag.name == name)).scalars().first()
             if name else None)
    if again is not None:
        tag_id = again.id
    elif tag_id is not None and s.get(Tag, tag_id) is None:
        # The tag is not back yet — reverting ITS deletion is what re-links
        # this, so leave the identity unlinked rather than pointing at a rowid
        # nothing owns.
        tag_id = None
    if tag_id is not None and s.execute(
        select(Subject).where(Subject.tag_id == tag_id)
    ).scalars().first() is not None:
        return False
    s.add(Subject(
        id=d.get("subject_id"),
        display_name=d.get("display_name") or "",
        since_date=d.get("since_date"),
        tag_id=tag_id,
    ))
    # An event from before the pair moved carries the deleted subject's own
    # comment. It belongs to the tag now — put it back there, and only into a
    # tag that says nothing, since the tag survived the subject and may have
    # been given words of its own since.
    if tag_id is not None and d.get("comment"):
        tag = s.get(Tag, tag_id)
        if tag is not None and not (tag.comment or ""):
            tag.comment = d["comment"]
    return True


def _revert_rename_subject(s: Session, d: dict) -> bool:
    subject = _subject_by(s, d)
    if subject is None:
        return False
    subject.display_name = d.get("old_name") or ""
    return True


def _revert_record_pair(s: Session, tag_id, d: dict) -> bool:
    """Put back a comment or a description a RECORD used to hold.

    Those columns are gone — the pair lives on the identity tag — so the
    events written while they existed are reverted onto the tag, which is
    where the value they name is now. A record whose tag has since been taken
    away has nowhere to put it and reports so, like every other revert whose
    target is gone.
    """
    from .db import Tag

    tag = s.get(Tag, tag_id) if tag_id else None
    if tag is None:
        return False
    if "old_comment" in d:
        tag.comment = d.get("old_comment") or ""
    # `old_description` stays in the payload and is left alone: a tag's own
    # description is not a thing any more (rung v17), so there is nowhere to
    # put it back.
    return True


def _revert_date_subject(s: Session, d: dict) -> bool:
    subject = _subject_by(s, d)
    if subject is None:
        return False
    subject.since_date = d.get("old_since_date")
    return True


def _revert_name_subject(s: Session, d: dict) -> bool:
    """Undo naming an unnamed subject: the identity loses its tag again, and
    the assignments the naming back-filled are dropped — but only the ones it
    actually wrote, which is why the event carries them."""
    from .db import ItemTag

    subject = _subject_by(s, d)
    if subject is None:
        return False
    subject.tag_id = None
    for item_id in d.get("backfilled") or []:
        it = s.execute(select(ItemTag).where(
            ItemTag.item_id == item_id, ItemTag.tag_id == d.get("tag_id")
        )).scalars().first()
        if it is not None:
            s.delete(it)
    return True


def _revert_add_tag_group_subject(s: Session, d: dict) -> bool:
    from .db import ItemTagGroupSubject

    s.execute(delete(ItemTagGroupSubject).where(
        ItemTagGroupSubject.group_id == d.get("group_id"),
        ItemTagGroupSubject.subject_id == d.get("subject_id"),
    ))
    return True


def _revert_remove_tag_group_subject(s: Session, d: dict) -> bool:
    from .db import ItemTagGroup, ItemTagGroupSubject, Subject

    gid, sid = d.get("group_id"), d.get("subject_id")
    if s.get(ItemTagGroup, gid) is None or s.get(Subject, sid) is None:
        return False  # the group or the identity is gone
    exists = s.execute(select(ItemTagGroupSubject).where(
        ItemTagGroupSubject.group_id == gid,
        ItemTagGroupSubject.subject_id == sid,
    )).scalars().first()
    if exists is None:
        s.add(ItemTagGroupSubject(group_id=gid, subject_id=sid))
    return True


# ---- places ----------------------------------------------------------------

def _place_by(s: Session, d: dict):
    from .db import Location

    return s.get(Location, d["place_id"]) if d.get("place_id") else None


def _revert_create_place(s: Session, d: dict) -> bool:
    """Undo adding a place. Its tag stays — an ordinary tag now."""
    place = _place_by(s, d)
    if place is None:
        return True
    s.delete(place)
    return True


def _revert_delete_place(s: Session, d: dict) -> bool:
    from .db import Location, Tag

    if _place_by(s, d) is not None:
        return True
    tag_id = d.get("tag_id")
    # By NAME first — the subject revert's lesson: a tag deleted alongside
    # the record comes back under a fresh rowid when ITS deletion is
    # reverted, so the stored id names nothing (or worse, something else).
    name = d.get("tag_name") or ""
    again = (s.execute(select(Tag).where(Tag.name == name)).scalars().first()
             if name else None)
    if again is not None:
        tag_id = again.id
    elif tag_id is not None and s.get(Tag, tag_id) is None:
        tag_id = None
    if tag_id is not None and s.execute(
        select(Location).where(Location.tag_id == tag_id)
    ).scalars().first() is not None:
        return False  # something else claimed the tag
    place = Location(id=d.get("place_id"), tag_id=tag_id,
                     name=d.get("name") or "",
                     parent_id=d.get("parent_id"),
                     lat=d.get("lat"), lon=d.get("lon"))
    s.add(place)
    s.flush()
    return True


def _revert_edit_place(s: Session, d: dict) -> bool:
    place = _place_by(s, d)
    if place is None:
        return False
    if "old_name" in d:
        place.name = d.get("old_name") or ""
    if "old_parent_id" in d:
        # The COLUMN only: the implication the parent carries logged its own
        # add/remove event, which reverts on its own like every other one.
        place.parent_id = d.get("old_parent_id")
    # Events from before the pair moved carry the old values; today's carry
    # neither, and the tag's own edit event is what undoes them.
    _revert_record_pair(s, place.tag_id, d)
    place.lat, place.lon = d.get("old_lat"), d.get("old_lon")
    return True


def _revert_name_place(s: Session, d: dict) -> bool:
    """Undo naming a place: the tag comes off the items it was back-filled onto,
    and they go back to being pinned to the unnamed place."""
    from .db import ItemLocation, ItemTag

    place = _place_by(s, d)
    if place is None:
        return False
    place.tag_id = None
    for item_id in d.get("backfilled") or []:
        it = s.execute(select(ItemTag).where(
            ItemTag.item_id == item_id, ItemTag.tag_id == d.get("tag_id")
        )).scalars().first()
        if it is not None:
            s.delete(it)
        exists = s.execute(select(ItemLocation).where(
            ItemLocation.item_id == item_id,
            ItemLocation.location_id == place.id,
        )).scalars().first()
        if exists is None:
            s.add(ItemLocation(item_id=item_id, location_id=place.id))
    touch_items(s, d.get("backfilled") or [])
    return True


# ---- events ----------------------------------------------------------------
#
# `Occasion` is the row; `Event` in this module is always the log entry. Locals
# here are named `occ` for that reason.

def _occ_by(s: Session, d: dict):
    from .db import Occasion

    return s.get(Occasion, d["occasion_id"]) if d.get("occasion_id") else None


def _write_places(s: Session, occ, place_ids) -> None:
    from .db import Location, OccasionPlace

    s.execute(delete(OccasionPlace).where(OccasionPlace.occasion_id == occ.id))
    for lid in place_ids or []:
        # A venue deleted since the event was edited is simply not restored:
        # the undo puts back what it can, and inventing a place it cannot name
        # would be worse than the gap.
        if s.get(Location, lid) is not None:
            s.add(OccasionPlace(occasion_id=occ.id, location_id=lid))


def _revert_create_event(s: Session, d: dict) -> bool:
    """Undo adding an event. Its tag stays — an ordinary tag now."""
    occ = _occ_by(s, d)
    if occ is None:
        return True
    s.delete(occ)
    return True


def _revert_delete_event(s: Session, d: dict) -> bool:
    from .db import Occasion, Tag

    if _occ_by(s, d) is not None:
        return True
    tag_id = d.get("tag_id")
    # By NAME first — see `_revert_delete_place`.
    name = d.get("tag_name") or ""
    again = (s.execute(select(Tag).where(Tag.name == name)).scalars().first()
             if name else None)
    if again is not None:
        tag_id = again.id
    elif tag_id is not None and s.get(Tag, tag_id) is None:
        tag_id = None
    if tag_id is not None and s.execute(
        select(Occasion).where(Occasion.tag_id == tag_id)
    ).scalars().first() is not None:
        return False  # something else claimed the tag
    occ = Occasion(id=d.get("occasion_id"), tag_id=tag_id,
                   display_name=d.get("display_name") or "",
                   parent_id=d.get("parent_id"),
                   start_date=d.get("start_date"), end_date=d.get("end_date"))
    # Pre-move events carry the pair here; the comment lives on the tag now
    # and the description nowhere (rung v17), so only the first is restored.
    if tag_id is not None and d.get("comment"):
        tag = s.get(Tag, tag_id)
        if tag is not None and not (tag.comment or ""):
            tag.comment = d["comment"]
    s.add(occ)
    s.flush()
    _write_places(s, occ, d.get("place_ids"))
    # The tree, both halves of it: the parent column and the implication a
    # parent link writes between the identity tags, for the restored event
    # and for whatever had been inside it.
    _relink_event(s, occ, occ.parent_id)
    for cid in d.get("child_ids") or []:
        child = s.get(Occasion, cid)
        if child is not None and child.parent_id is None:
            _relink_event(s, child, occ.id)
    return True


def _relink_event(s: Session, occ, parent_id) -> None:
    """Put ``occ`` under ``parent_id`` again — column and implication."""
    from .db import Occasion, Tag, TagImplication

    occ.parent_id = parent_id
    parent = s.get(Occasion, parent_id) if parent_id else None
    if parent is None or occ.tag_id is None or parent.tag_id is None:
        return
    if s.execute(select(TagImplication).where(
            TagImplication.tag_id == occ.tag_id,
            TagImplication.implies_id == parent.tag_id)).scalars().first():
        return
    s.add(TagImplication(tag_id=occ.tag_id, implies_id=parent.tag_id))
    s.flush()


def _revert_edit_event(s: Session, d: dict) -> bool:
    occ = _occ_by(s, d)
    if occ is None:
        return False
    occ.display_name = d.get("old_display_name") or ""
    if "old_parent_id" in d:
        occ.parent_id = d.get("old_parent_id")
    _revert_record_pair(s, occ.tag_id, d)
    occ.start_date = d.get("old_start_date")
    occ.end_date = d.get("old_end_date")
    _write_places(s, occ, d.get("old_place_ids"))
    return True


def _revert_dismiss_place(s: Session, d: dict) -> bool:
    """Offer a refused place again. The refusal is keyed on (item, place) and
    nothing else, so this deletes by those two and never by the event that
    prompted it."""
    from .db import ItemPlaceDismissal

    s.execute(delete(ItemPlaceDismissal).where(
        ItemPlaceDismissal.item_id == d.get("item_id"),
        ItemPlaceDismissal.location_id == d.get("location_id"),
    ))
    touch_items(s, [d["item_id"]] if d.get("item_id") else [])
    return True


def _revert_dismiss_event(s: Session, d: dict) -> bool:
    from .db import ItemOccasionDismissal

    s.execute(delete(ItemOccasionDismissal).where(
        ItemOccasionDismissal.item_id == d.get("item_id"),
        ItemOccasionDismissal.occasion_id == d.get("occasion_id"),
    ))
    touch_items(s, [d["item_id"]] if d.get("item_id") else [])
    return True


def _revert_dismiss_file_place(s: Session, d: dict) -> bool:
    """Offer the file's own place again — keyed on the item alone, like the
    dismissal it undoes."""
    from .db import ItemFilePlaceDismissal

    s.execute(delete(ItemFilePlaceDismissal).where(
        ItemFilePlaceDismissal.item_id == d.get("item_id")))
    touch_items(s, [d["item_id"]] if d.get("item_id") else [])
    return True


def _revert_create_ranking(s: Session, d: dict) -> bool:
    """Take a freshly created ranking down again. The NAME in the payload is
    the rowid-reuse guard: a ranking that no longer matches it is somebody
    else's row. (It was the `prefix` until a ranking stopped owning a tag
    namespace — rung v31 — so an event written before that reverts by the
    name it also carries.)"""
    from .db import Ranking

    row = s.get(Ranking, d.get("ranking_id"))
    if row is None or row.name != d.get("name"):
        return False
    s.delete(row)
    return True


def _revert_create_ranking_pool(s: Session, d: dict) -> bool:
    """Take a freshly added pool down again. The ranking id and the name
    are the rowid-reuse guard; a pool that has since been rated in is
    left alone — deleting it would cascade evidence a revert of "added a
    pool" never promised to take — and so is the ranking's last one."""
    from .db import RankingJudgment, RankingPool

    row = s.get(RankingPool, d.get("pool_id"))
    if (row is None or row.ranking_id != d.get("ranking_id")
            or row.name != d.get("name")):
        return False
    siblings = s.execute(select(func.count()).select_from(RankingPool)
                         .where(RankingPool.ranking_id == row.ranking_id)
                         ).scalar_one()
    used = s.execute(select(func.count()).select_from(RankingJudgment)
                     .where(RankingJudgment.pool_id == row.id)
                     ).scalar_one()
    if siblings <= 1 or used:
        return False
    s.delete(row)
    return True


def _revert_edit_ranking_pool(s: Session, d: dict) -> bool:
    """Put a pool's old name back, unless a sibling has taken it since."""
    from .db import RankingPool

    row = s.get(RankingPool, d.get("pool_id"))
    if row is None or row.ranking_id != d.get("ranking_id"):
        return False
    old = str(d.get("old") or "")
    taken = s.execute(select(RankingPool).where(
        RankingPool.ranking_id == row.ranking_id,
        RankingPool.name == old,
        RankingPool.id != row.id)).scalars().first()
    if taken is not None:
        return False
    row.name = old
    return True


def _revert_reorder_ranking_pools(s: Session, d: dict) -> bool:
    """Every old position back — `_revert_reorder_appearances`' shape."""
    from .db import RankingPool

    ok = False
    for k, v in (d.get("old_positions") or {}).items():
        row = s.get(RankingPool, int(k))
        if row is not None and row.ranking_id == d.get("ranking_id"):
            row.position = int(v)
            ok = True
    return ok


def _revert_set_placement_sign(s: Session, d: dict) -> bool:
    """Put one instance's old sign back and re-derive the assignment's."""
    from .ops import tagassign
    from .ops.context import Ctx

    p = s.get(ItemTagPlacement, d.get("placement_id"))
    if p is None:
        return False
    p.negative = bool(d.get("old", False))
    tagassign.sync_placement_sign(Ctx(session=s), p.item_tag_id)
    return True


def _revert_set_face_outline(s: Session, d: dict) -> bool:
    """`_revert_set_appearance_box`'s shape for a FACE's outline."""
    from .db import Face, FaceOutline

    face = s.get(Face, d.get("face_id"))
    if face is None:
        return False
    row = s.execute(select(FaceOutline).where(
        FaceOutline.face_id == face.id)).scalars().first()
    old = d.get("old")
    if old is None:
        if row is not None:
            s.delete(row)
        return True
    if row is None:
        row = FaceOutline(face_id=face.id, x=0, y=0, w=0, h=0)
        s.add(row)
    row.x, row.y = float(old["x"]), float(old["y"])
    row.w, row.h = float(old["w"]), float(old["h"])
    row.points = old.get("points")
    return True


def _revert_set_appearance_box(s: Session, d: dict) -> bool:
    from .db import ItemSubject, ItemSubjectBox

    row = s.get(ItemSubject, d.get("appearance_id"))
    if row is None:
        return False
    box = s.execute(select(ItemSubjectBox).where(
        ItemSubjectBox.item_subject_id == row.id)).scalars().first()
    old = d.get("old")
    if old is None:
        # The edit drew where nothing was — the revert takes it down.
        if box is not None:
            s.delete(box)
        return True
    if box is None:
        box = ItemSubjectBox(item_subject_id=row.id, x=0, y=0, w=0, h=0)
        s.add(box)
    box.x, box.y = float(old["x"]), float(old["y"])
    box.w, box.h = float(old["w"]), float(old["h"])
    # The polygon is part of the shape being restored — an old snapshot
    # without the key restores a plain rectangle.
    box.points = old.get("points")
    return True


def _revert_edit_ranking(s: Session, d: dict) -> bool:
    """Put back what the edit changed. An event written before rung v31
    carries a `prefix` and an `enabled` too — fields a ranking no longer
    has, so those halves of it simply have nothing to restore; the rest of
    the payload reverts exactly as it always did."""
    from .db import Ranking

    row = s.get(Ranking, d.get("ranking_id"))
    old = d.get("old") or {}
    if row is None:
        return False
    if "name" in old:
        row.name = old["name"]
    if "scope" in old:
        row.scope = old["scope"]
    if "bucket_lo" in old:
        row.bucket_lo = int(old["bucket_lo"])
    if "bucket_hi" in old:
        row.bucket_hi = int(old["bucket_hi"])
    return True


def _revert_judge_ranking(s: Session, d: dict) -> bool:
    """Un-ask the question: delete the judgment and refit, so the scores move
    with the evidence rather than going stale."""
    from .db import RankingJudgment

    j = s.get(RankingJudgment, d.get("judgment_id"))
    if j is None or j.ranking_id != d.get("ranking_id"):
        return False
    touch_items(s, [j.a_item_id])
    s.delete(j)
    s.flush()
    return True


def _revert_remove_ranking_item(s: Session, d: dict) -> bool:
    """Put the removed item's judgments back from the event's snapshot; the
    standings are fitted on read, so the picture stands where it stood."""
    from .db import Ranking, RankingJudgment, RankingPool
    from .ops import rankings as rankings_ops

    ranking_id = d.get("ranking_id")
    ranking = s.get(Ranking, ranking_id)
    if ranking is None:
        return False
    rows = d.get("judgments") or []
    # Each judgment goes back into the POOL it was made in. An event from
    # before pools existed names none, which was the ranking's one pool
    # — its default now; a judgment whose pool has since been deleted has
    # nowhere to go and is skipped (the pool's delete took that evidence
    # deliberately).
    default = rankings_ops.default_pool(s, ranking)
    for j in rows:
        lid = j.get("pool_id")
        if lid is None:
            lid = default.id if default is not None else None
        elif s.get(RankingPool, lid) is None:
            lid = None
        if lid is None:
            continue
        s.add(RankingJudgment(
            ranking_id=ranking_id, pool_id=int(lid),
            a_item_id=int(j["a_item_id"]), b_item_id=int(j["b_item_id"]),
            outcome=str(j["outcome"]), username=str(j.get("username") or "")))
    touch_items(s, [int(j["a_item_id"]) for j in rows])
    s.flush()
    return True


def _revert_dismiss_ranking_item(s: Session, d: dict) -> bool:
    """Make the picture applicable again — keyed on (ranking, item), like the
    other dismissals."""
    from .db import RankingDismissal

    s.execute(delete(RankingDismissal).where(
        RankingDismissal.ranking_id == d.get("ranking_id"),
        RankingDismissal.item_id == d.get("item_id")))
    touch_items(s, [d["item_id"]] if d.get("item_id") else [])
    return True


def _revert_undismiss_ranking_item(s: Session, d: dict) -> bool:
    from .db import RankingDismissal

    ranking_id, item_id = d.get("ranking_id"), d.get("item_id")
    if not ranking_id or not item_id:
        return False
    exists = s.execute(select(RankingDismissal).where(
        RankingDismissal.ranking_id == ranking_id,
        RankingDismissal.item_id == item_id)).scalars().first()
    if exists is None:
        s.add(RankingDismissal(ranking_id=ranking_id, item_id=item_id))
    touch_items(s, [item_id])
    return True


def _redo_dismiss_file_place(s: Session, d: dict) -> bool:
    from .db import ItemFilePlaceDismissal

    item_id = d.get("item_id")
    if not item_id:
        return False
    exists = s.execute(select(ItemFilePlaceDismissal).where(
        ItemFilePlaceDismissal.item_id == item_id)).scalars().first()
    if exists is None:
        s.add(ItemFilePlaceDismissal(item_id=item_id))
    touch_items(s, [item_id])
    return True


def _redo_dismiss_place(s: Session, d: dict) -> bool:
    """Refuse it again. Unlike the other row-creating handlers this one IS
    redoable: the exclusion is about ids that later payloads reference, and a
    dismissal's id appears in none — the revert finds it by its keys."""
    from .db import ItemPlaceDismissal

    item_id, location_id = d.get("item_id"), d.get("location_id")
    if not item_id or not location_id:
        return False
    exists = s.execute(select(ItemPlaceDismissal).where(
        ItemPlaceDismissal.item_id == item_id,
        ItemPlaceDismissal.location_id == location_id,
    )).scalars().first()
    if exists is None:
        s.add(ItemPlaceDismissal(item_id=item_id, location_id=location_id,
                                 via_occasion_id=d.get("via_occasion_id")))
    touch_items(s, [item_id])
    return True


def _redo_dismiss_event(s: Session, d: dict) -> bool:
    from .db import ItemOccasionDismissal

    item_id, occasion_id = d.get("item_id"), d.get("occasion_id")
    if not item_id or not occasion_id:
        return False
    exists = s.execute(select(ItemOccasionDismissal).where(
        ItemOccasionDismissal.item_id == item_id,
        ItemOccasionDismissal.occasion_id == occasion_id,
    )).scalars().first()
    if exists is None:
        s.add(ItemOccasionDismissal(item_id=item_id, occasion_id=occasion_id))
    touch_items(s, [item_id])
    return True


def _revert_pin_metadata(s: Session, d: dict) -> bool:
    """Take a promoted value back off the item."""
    from .db import ItemMetaPin

    row = s.execute(
        select(ItemMetaPin).where(
            ItemMetaPin.item_id == d.get("item_id"),
            ItemMetaPin.name == d.get("name"),
            ItemMetaPin.raw == (d.get("raw") or ""))
    ).scalars().first()
    if row is None:
        return False
    s.delete(row)
    touch_items(s, [d["item_id"]])
    return True


def _revert_unpin_metadata(s: Session, d: dict) -> bool:
    """Put a promoted value back — its SHAPE, not just its existence: the
    value, the type it was compared as, and which file it was promoted from.
    Restoring it as a bare string would leave a numeric name comparing as
    text on exactly the picture somebody curated."""
    from .db import Item, ItemMetaPin

    item = s.get(Item, d.get("item_id"))
    if item is None:
        return False
    if s.execute(
        select(ItemMetaPin).where(
            ItemMetaPin.item_id == item.id, ItemMetaPin.name == d.get("name"),
            ItemMetaPin.raw == (d.get("raw") or ""))
    ).scalars().first() is not None:
        return True
    s.add(ItemMetaPin(
        item_id=item.id, name=d.get("name") or "",
        mtype=d.get("mtype") or "text", num_value=d.get("num_value"),
        text_value=d.get("text_value"), raw=d.get("raw") or "",
        source_file_id=d.get("source_file_id"),
    ))
    touch_items(s, [item.id])
    return True


def _revert_mute_metadata(s: Session, d: dict) -> bool:
    """Take the name from the active file again."""
    from .db import ItemMetaMute
    from .itemmeta import rebuild_item_metadata

    row = s.execute(
        select(ItemMetaMute).where(ItemMetaMute.item_id == d.get("item_id"),
                                   ItemMetaMute.name == d.get("name"))
    ).scalars().first()
    if row is None:
        return False
    s.delete(row)
    s.flush()
    rebuild_item_metadata(s, d["item_id"])
    touch_items(s, [d["item_id"]])
    return True


def _revert_unmute_metadata(s: Session, d: dict) -> bool:
    """Stop taking the name from the active file again."""
    from .db import Item, ItemMetaMute
    from .itemmeta import rebuild_item_metadata

    item = s.get(Item, d.get("item_id"))
    if item is None:
        return False
    if s.execute(
        select(ItemMetaMute).where(ItemMetaMute.item_id == item.id,
                                   ItemMetaMute.name == d.get("name"))
    ).scalars().first() is None:
        s.add(ItemMetaMute(item_id=item.id, name=d.get("name") or ""))
        s.flush()
        rebuild_item_metadata(s, item.id)
    touch_items(s, [item.id])
    return True


def _revert_set_taken(s: Session, d: dict) -> bool:
    """Put back the capture date that was there before — or take it away again
    when there was none, which falls back to what the camera said.

    Normalized on the way back in: an event logged while the Python API still
    stored date-width values carries an 8-digit ``old_taken_at``, and restoring
    it verbatim would plant the very value the widening exists to prevent."""
    from .db import Item, normalize_taken

    item = s.get(Item, d.get("item_id"))
    if item is None:
        return False
    item.taken_at = normalize_taken(d.get("old_taken_at")) or None
    touch_items(s, [item.id])
    return True


def _revert_set_coords(s: Session, d: dict) -> bool:
    """Put back where the item was said to be — or take it away again, which
    falls back to what the file said."""
    from .db import Item

    item = s.get(Item, d.get("item_id"))
    if item is None:
        return False
    item.lat, item.lon = d.get("old_lat"), d.get("old_lon")
    touch_items(s, [item.id])
    return True


def _revert_set_alias(s: Session, d: dict) -> bool:
    """Undo an alias change — restore the previous linked (target) tag."""
    tag = _tag_by(s, d)
    if tag is None:
        return False
    old = (d.get("old_alias_of") or "").strip()
    if not old:
        tag.alias_of_id = None
        return True
    target = s.execute(select(Tag).where(Tag.name == old)).scalars().first()
    if target is None:
        return False
    tag.alias_of_id = target.id
    return True


def _revert_add_tag_implication(s: Session, d: dict) -> bool:
    """Undo "A now implies B" — drop the edge again."""
    from .db import TagImplication

    tag = _tag_by(s, d)
    target = s.execute(select(Tag).where(
        Tag.name == (d.get("implies") or ""))).scalars().first()
    if tag is None or target is None:
        return False
    s.execute(delete(TagImplication).where(
        TagImplication.tag_id == tag.id,
        TagImplication.implies_id == target.id))
    return True


def _revert_remove_tag_implication(s: Session, d: dict) -> bool:
    """Undo "A no longer implies B" — put the edge back, unless something has
    since made it a loop."""
    from .db import TagImplication

    tag = _tag_by(s, d)
    target = s.execute(select(Tag).where(
        Tag.name == (d.get("implies") or ""))).scalars().first()
    if tag is None or target is None or tag.id == target.id:
        return False
    if tag.name in tag_implications(s).get(target.name, set()):
        return False   # the other direction exists now; restoring would loop
    exists = s.execute(select(TagImplication).where(
        TagImplication.tag_id == tag.id,
        TagImplication.implies_id == target.id)).scalars().first()
    if exists is None:
        s.add(TagImplication(tag_id=tag.id, implies_id=target.id))
    return True


def _group_tag_row(s: Session, d: dict):
    """(group id, tag) for a group-tag event, or None when either is gone."""
    from .db import GroupTag

    gid = d.get("group_id")
    tag = s.execute(select(Tag).where(Tag.name == (d.get("tag") or ""))).scalars().first()
    if not isinstance(gid, int) or tag is None or s.get(Group, gid) is None:
        return None
    return GroupTag, gid, tag


def _revert_add_group_tag(s: Session, d: dict) -> bool:
    """Undo tagging a library group."""
    row = _group_tag_row(s, d)
    if row is None:
        return False
    GroupTag, gid, tag = row
    s.execute(delete(GroupTag).where(
        GroupTag.group_id == gid, GroupTag.tag_id == tag.id))
    return True


def _revert_remove_group_tag(s: Session, d: dict) -> bool:
    row = _group_tag_row(s, d)
    if row is None:
        return False
    GroupTag, gid, tag = row
    if s.execute(select(GroupTag).where(
        GroupTag.group_id == gid, GroupTag.tag_id == tag.id
    )).scalars().first() is None:
        s.add(GroupTag(group_id=gid, tag_id=tag.id,
                       negative=bool(d.get("negative"))))
    return True


# ---- meta tags (the namespace links, captions and tag groups share) --------
#
# These were not in the log at all, so the whole Meta list of the Tags tab made
# changes nothing could see or undo.

def _drop_tag_group(s: Session, group_id) -> bool:
    """Delete a per-item tag group, its instances falling back to ungrouped.

    The forward delete's own body, minus the logging — so undoing a create and
    redoing a delete cannot drift apart from what the endpoint does.
    """
    from .db import ItemTagGroup, ItemTagPlacement

    from .ops import ctx_for, tagassign

    grp = s.get(ItemTagGroup, group_id)
    if grp is None:
        return False
    item_id = grp.item_id
    for p in s.execute(select(ItemTagPlacement).where(
        ItemTagPlacement.group_id == group_id
    )).scalars().all():
        # Through the same fold the forward delete uses: a bare
        # `p.group_id = None` had drifted from it, leaving TWO ungrouped
        # placements of one tag when the tag also had an ungrouped instance.
        tagassign.merge_placement_into_group(ctx_for(s), p, None)
    s.flush()
    s.delete(grp)
    touch_items(s, [item_id])
    return True


def _tag_group_by(s: Session, d: dict, name):
    """The tag group an event names, guarded against ROWID REUSE.

    A group id is a rowid, and SQLite hands out ``max(rowid) + 1`` — so a
    revert that deletes the newest group frees an id the very next insert
    takes. Inside one reverse walk that happens routinely: undoing
    `approve_tag` re-creates the auto-managed Pending group, which lands on the
    id a `delete_tag_group` undo had just vacated. Trusting the id alone made
    "undo the create" delete the Pending group instead, leaving the real one
    behind — two wrong groups from one lookup.

    So the id is only believed when the row at it still belongs to the same
    item and answers to the expected name; otherwise the group is found by
    (item, name), which is what the walk has just finished restoring.
    """
    from .db import ItemTagGroup

    item_id = d.get("item_id")
    gid = d.get("group_id")
    grp = s.get(ItemTagGroup, gid) if gid else None
    if grp is not None and grp.item_id == item_id and grp.name == name:
        return grp
    if item_id is None or not name:
        return None
    return s.execute(select(ItemTagGroup).where(
        ItemTagGroup.item_id == item_id, ItemTagGroup.name == name
    )).scalars().first()


def _revert_create_tag_group(s: Session, d: dict) -> bool:
    grp = _tag_group_by(s, d, d.get("name"))
    return _drop_tag_group(s, grp.id) if grp is not None else False


def _revert_rename_tag_group(s: Session, d: dict) -> bool:
    # Found by the name the rename PUT there, which is what it still carries.
    grp = _tag_group_by(s, d, d.get("name"))
    if grp is None or not d.get("old_name"):
        return False
    grp.name = d["old_name"]
    touch_items(s, [grp.item_id])
    return True


def _revert_delete_group(s: Session, d: dict) -> bool:
    """Put a deleted group back — the whole subtree, with its shape.

    Deleting a group takes everything under it (see `ops/groups.delete_group`:
    a deletion removes the shelf rather than emptying it onto the floor), so
    this restores the lot: the rows, the tree edges between them, the tags each
    granted, and the items each held.

    UNDER THE ORIGINAL IDS where they are still free, for the reason
    `_revert_delete_tag_group` reuses one: every earlier event about these
    groups names them by id, and coming back under fresh ones would leave all
    of those pointing at nothing. Root first, so a child's parent edge always
    has something to point at.

    A SMART group carries no items in the snapshot — its rows are derived, so
    restoring the query is restoring the membership, and the sweeper this
    commit pokes refits it.

    A deletion that KEPT the children (`ops/groups.delete_group`'s
    `keep_children`) snapshots only the group itself and names the groups it
    moved up; putting them back under it is the other half of that undo, and
    without it the restore would return an empty shelf with its contents
    still scattered where the deletion left them.

    Answers False when the event has no snapshot (the deletion was too large
    to carry one — `can_revert` declines those before this is reached) or when
    the group is somehow already back.
    """
    from .db import Group, GroupParent, GroupTag, Item, ItemGroup

    snap = d.get("undo")
    if not isinstance(snap, dict):
        return False
    groups = snap.get("groups")
    if not isinstance(groups, list) or not groups:
        return False
    root = groups[0].get("id")
    if root is None or s.get(Group, root) is not None:
        return False

    restored: set[int] = set()
    for row in groups:
        gid = row.get("id")
        if gid is None or s.get(Group, gid) is not None:
            continue
        g = Group(name=row.get("name") or "Group",
                  icon=row.get("icon") or "folder",
                  color=row.get("color"),
                  smart_query=row.get("smart_query"))
        uid = row.get("uid")
        if uid:
            g.uid = uid
        g.id = gid
        s.add(g)
        restored.add(gid)
    s.flush()
    for row in groups:
        gid = row.get("id")
        if gid not in restored:
            continue
        parent = row.get("parent")
        # Only back under a parent that is there — the group may have hung
        # off something that has since been deleted itself, and a top-level
        # group is a better answer than an edge to nothing.
        if parent is not None and s.get(Group, parent) is not None:
            s.add(GroupParent(group_id=gid, parent_group_id=parent))
        for pair in row.get("tags") or []:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            tag_id, neg = pair
            if s.get(Tag, tag_id) is not None:
                s.add(GroupTag(group_id=gid, tag_id=tag_id,
                               negative=bool(neg)))
        # An item trashed or deleted since simply has no membership to put
        # back, which is the same tolerance every other restore here has.
        ids = [i for i in (row.get("items") or [])
               if s.get(Item, i) is not None]
        if ids:
            s.add_all([ItemGroup(item_id=i, group_id=gid) for i in ids])
    # The children the deletion moved up, back under the group it hung them
    # from. Tolerant in the same way the rest of this is: one deleted or
    # re-filed since simply stays where it is.
    promoted = [gid for gid in (d.get("promoted_group_ids") or [])
                if isinstance(gid, int) and s.get(Group, gid) is not None]
    if promoted:
        s.execute(delete(GroupParent)
                  .where(GroupParent.group_id.in_(promoted)))
        s.add_all([GroupParent(group_id=gid, parent_group_id=root)
                   for gid in promoted])
    return True


def _revert_delete_tag_group(s: Session, d: dict) -> bool:
    """Put a per-item tag group back, with the tags that were filed in it.

    The group is recreated under its ORIGINAL id when that id is still free,
    for the reason `_restore_appearance` reuses an appearance's: the rename and
    the tag-group meta-tag events behind this one name the group by id, and a
    fresh one leaves them all pointing at nothing.
    """
    from .db import (
        ItemTag, ItemTagGroup, ItemTagGroupSubject, ItemTagGroupTag,
        ItemTagPlacement, Tag,
    )

    item_id = d.get("item_id")
    if item_id is None or s.get(Item, item_id) is None:
        return False
    grp = ItemTagGroup(item_id=item_id, name=d.get("name") or "New group",
                       position=d.get("position") or 0,
                       system=bool(d.get("system")))
    want = d.get("group_id")
    if want and s.get(ItemTagGroup, want) is None:
        grp.id = want
    s.add(grp)
    s.flush()
    # Move the tags back in. A tag that has since been taken off the item
    # simply has no placement to move, and is skipped.
    for name in d.get("tags") or []:
        placement = s.execute(
            select(ItemTagPlacement)
            .join(ItemTag, ItemTag.id == ItemTagPlacement.item_tag_id)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .where(ItemTag.item_id == item_id, Tag.name == name,
                   ItemTagPlacement.group_id.is_(None))
        ).scalars().first()
        if placement is not None:
            placement.group_id = grp.id
    for name in d.get("meta_tags") or []:
        s.add(ItemTagGroupTag(group_id=grp.id, name=name))
    for sid in d.get("subjects") or []:
        s.add(ItemTagGroupSubject(group_id=grp.id, subject_id=sid))
    touch_items(s, [item_id])
    return True


def _meta_carriers(s: Session):
    from .db import CaptionTag, ItemTagGroupTag

    return ((RelationshipTag, "relationship_id", "relationships"),
            (CaptionTag, "caption_id", "captions"),
            (ItemTagGroupTag, "group_id", "tag_groups"))


def _revert_create_meta_tag(s: Session, d: dict) -> bool:
    """Undo creating a meta tag — only while nothing has started using it."""
    from .db import LIB_META, LinkTag

    name = (d.get("name") or "").strip()
    if not name:
        return False
    for table, _key, _label in _meta_carriers(s):
        if s.execute(select(table.id).where(table.name == name).limit(1)).first():
            return False  # in use now — dropping it would strand a carrier
    row = s.execute(select(LinkTag).where(LinkTag.name == name, LIB_META)).scalar_one_or_none()
    if row is not None:
        s.delete(row)
    return True


def _rename_meta_tag(s: Session, frm: str, to: str) -> bool:
    """Rewrite a meta tag's name on every carrier, folding into an existing one
    where a carrier already has both (the endpoint's own rule)."""
    from .db import LIB_META, LinkTag

    if not frm or not to:
        return False
    for table, key, _label in _meta_carriers(s):
        owner = getattr(table, key)
        for row in s.execute(select(table).where(table.name == frm)).scalars().all():
            dup = s.execute(select(table.id).where(
                owner == getattr(row, key), table.name == to)).first()
            if dup:
                s.delete(row)
            else:
                row.name = to
    src = s.execute(select(LinkTag).where(LinkTag.name == frm, LIB_META)).scalar_one_or_none()
    dst = s.execute(select(LinkTag).where(LinkTag.name == to, LIB_META)).scalar_one_or_none()
    if src is not None:
        if dst is not None:
            if not dst.comment and src.comment:
                dst.comment = src.comment
            s.delete(src)
        else:
            src.name = to
    elif dst is None:
        s.add(LinkTag(name=to))
    return True


def _revert_rename_meta_tag(s: Session, d: dict) -> bool:
    return _rename_meta_tag(s, (d.get("name") or "").strip(),
                            (d.get("old_name") or "").strip())


def _revert_comment_meta_tag(s: Session, d: dict) -> bool:
    from .db import LIB_META, LinkTag

    name = (d.get("name") or "").strip()
    row = s.execute(select(LinkTag).where(LinkTag.name == name, LIB_META)).scalar_one_or_none()
    if row is None:
        return False
    row.comment = d.get("old_comment") or ""
    return True


def _revert_describe_meta_tag(s: Session, d: dict) -> bool:
    from .db import LIB_META, LinkTag

    name = (d.get("name") or "").strip()
    row = s.execute(select(LinkTag).where(LinkTag.name == name, LIB_META)).scalar_one_or_none()
    if row is None:
        return False
    row.description = d.get("old_description") or ""
    return True


def _revert_delete_meta_tag(s: Session, d: dict) -> bool:
    """Undo deleting a meta tag — the name AND every carrier it was on."""
    from .db import LIB_META, CaptionTag, ItemTagGroupTag, LinkTag, TagMetaTag

    name = (d.get("name") or "").strip()
    if not name:
        return False
    if s.execute(select(LinkTag).where(
        LinkTag.name == name, LIB_META)).scalar_one_or_none() is None:
        s.add(LinkTag(name=name, comment=d.get("comment") or ""))
    by_label = {"relationships": (RelationshipTag, "relationship_id"),
                "captions": (CaptionTag, "caption_id"),
                "tag_groups": (ItemTagGroupTag, "group_id"),
                # Absent from every event written before tags could carry one,
                # which `d.get(label) or []` already reads as "none".
                "tags": (TagMetaTag, "tag_id")}
    for label, (table, key) in by_label.items():
        owner = getattr(table, key)
        for owner_id in d.get(label) or []:
            if not isinstance(owner_id, int):
                continue
            if s.execute(select(table.id).where(
                owner == owner_id, table.name == name)).first():
                continue
            s.add(table(**{key: owner_id, "name": name}))
    s.flush()
    return True


def _revert_rename_tag(s: Session, d: dict) -> bool:
    """Undo a rename — put the old name back, unless something else has taken
    it in the meantime (renaming onto an existing name is a merge, not this)."""
    tag = s.get(Tag, d["tag_id"]) if d.get("tag_id") else None
    if tag is None:
        tag = s.execute(select(Tag).where(
            Tag.name == (d.get("name") or ""))).scalars().first()
    old = (d.get("old_name") or "").strip()
    if tag is None or not old:
        return False
    if old != tag.name and s.execute(select(Tag).where(
        Tag.name == old, Tag.id != tag.id
    )).scalars().first() is not None:
        return False
    tag.name = old
    return True


def _revert_comment_tag(s: Session, d: dict) -> bool:
    """Undo a tag-comment change — restore the comment as it was before the edit
    (recorded in ``old_comment``; legacy events without it clear the comment)."""
    tag = _tag_by(s, d)
    if tag is None:
        return False
    tag.comment = d.get("old_comment") or ""
    return True


def _revert_set_tag_hidden(s: Session, d: dict) -> bool:
    """Put these tags back where the autocomplete had them. The event
    carries only the names that MOVED, so the revert is the flag flipped
    the other way — a tag deleted since is simply skipped."""
    from .db import Tag

    from .db import chunked

    names = [str(n) for n in (d.get("names") or [])]
    if not names:
        return False
    back = not bool(d.get("hidden"))
    moved = False
    for chunk in chunked(names):
        for tag in s.execute(select(Tag).where(Tag.name.in_(chunk))).scalars():
            tag.hidden = back
            moved = True
    return moved


def _revert_describe_tag(s: Session, d: dict) -> bool:
    """Put the tag's long form back.

    The payload is the shape the pre-removal events used — `tag_id`, `tag`,
    `description`, `old_description` — deliberately, so an event written
    before a tag stopped carrying a description reverts again now that it
    carries one, rather than staying dead in the log.
    """
    from .db import Tag

    tag = s.get(Tag, int(d.get("tag_id") or 0))
    if tag is None:
        name = str(d.get("tag") or "")
        tag = (s.execute(select(Tag).where(Tag.name == name)).scalars().first()
               if name else None)
    if tag is None:
        return False
    tag.description = str(d.get("old_description") or "")
    return True


def _revert_set_tag_category(s: Session, d: dict) -> bool:
    """Put each tag back in the category it came out of.

    `before` maps a tag id to the category it was in (or null), because a
    selection dragged onto one category need not have come from one place.
    A category deleted since is dropped rather than restored — the column is
    SET NULL, so pointing at it again is not something this can do.
    """
    from .db import Tag, TagSetCategory, TagSetEntry, chunked

    before = dict(d.get("before") or {})
    if not before:
        return False
    # WHICH TAG SET — absent is the library's own, the shape every event
    # written before a set's entries were filed this way has.
    Row = Tag if d.get("set_id") is None else TagSetEntry
    ids = [int(k) for k in before]
    moved = False
    for chunk in chunked(ids):
        for tag in s.execute(select(Row).where(Row.id.in_(chunk))).scalars():
            was = before.get(str(tag.id))
            if was is not None and s.get(TagSetCategory, int(was)) is None:
                was = None
            tag.category_id = int(was) if was is not None else None
            moved = True
    return moved


def _revert_set_hidden_namespaces(s: Session, d: dict) -> bool:
    """Put the whole list back. A namespace has no row, so the list IS the
    state and `before` is all a revert needs."""
    import json as _json

    from . import prefs
    from .db import get_setting, set_setting

    before = d.get("before")
    if before is None:
        return False
    cur = _json.loads(get_setting(s, prefs.PREFS_GLOBAL) or "{}")
    cur["hidden_namespaces"] = [str(n) for n in before]
    set_setting(s, prefs.PREFS_GLOBAL, _json.dumps(cur))
    return True


def _revert_set_meta_count(s: Session, d: dict) -> bool:
    """Undo a meta-tag count change — put back the number the assignment
    carried. The assignment itself may have gone since (a removal has its
    own event); putting a number back needs the row, so it comes back with
    it — the count is part of the assignment's SHAPE."""
    from .db import LIB_META, LinkTag, TagMetaTag

    tag = _tag_by(s, d)
    if tag is None or not d.get("name"):
        return False
    old = max(0, int(d.get("old_count") or 0))
    row = s.execute(select(TagMetaTag).where(
        TagMetaTag.tag_id == tag.id, TagMetaTag.name == d["name"],
    )).scalars().first()
    if row is None:
        s.add(TagMetaTag(tag_id=tag.id, name=d["name"], count=old))
        if s.execute(select(LinkTag).where(
                LinkTag.name == d["name"], LIB_META)).scalar_one_or_none() is None:
            s.add(LinkTag(name=d["name"]))
    else:
        row.count = old
    return True


def _revert_delete_tag(s: Session, d: dict) -> bool:
    """Undo deleting a tag — the row AND everything that went down with it.

    Deleting a tag cascades: its implications in both directions, the library
    groups that assigned it, and its aliases (whose foreign key deletes them
    outright). The item assignments come back through the per-item `remove_tag`
    events the deletion also logs; everything else is restored here, from the
    snapshot in the event. Older events carry only name/comment/alias and
    restore just that.
    """
    from .db import GroupTag, Subject, TagImplication

    name = (d.get("name") or "").strip()
    if not name:
        return False
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if tag is None:
        tag = Tag(name=name, comment=d.get("comment", ""))
        s.add(tag)
        s.flush()
    # The alias link is RESTORED, not merely set: a merge leaves the old name
    # behind as an alias of the target, and undoing the merge has to promote
    # that row back to the tag it was rather than leave it pointing away.
    alias = (d.get("alias_of") or "").strip()
    target = (s.execute(select(Tag).where(Tag.name == alias)).scalars().first()
              if alias else None)
    tag.alias_of_id = (target.id if target is not None
                       and target.alias_of_id is None else None)
    # The identity it WAS. `Subject.tag_id` is SET NULL, so deleting the tag
    # leaves the subject unlinked rather than gone — and the subject's own
    # revert cannot restore this, because it may run BEFORE the tag is back and
    # the recreated row carries a fresh id either way. So the link is restored
    # here, where the row that broke it comes back.
    was = d.get("subject_id")
    if was is not None:
        sub = s.get(Subject, was)
        if sub is not None and sub.tag_id is None and s.execute(
            select(Subject).where(Subject.tag_id == tag.id)
        ).scalars().first() is None:
            sub.tag_id = tag.id

    def _named(n: str) -> Optional[Tag]:
        return s.execute(select(Tag).where(Tag.name == n)).scalars().first()

    def _edge(from_tag: Optional[Tag], to_tag: Optional[Tag]) -> None:
        if from_tag is None or to_tag is None or from_tag.id == to_tag.id:
            return
        if s.execute(select(TagImplication).where(
            TagImplication.tag_id == from_tag.id,
            TagImplication.implies_id == to_tag.id,
        )).scalars().first() is None:
            s.add(TagImplication(tag_id=from_tag.id, implies_id=to_tag.id))

    for other in d.get("implies") or []:
        _edge(tag, _named(other))
    for other in d.get("implied_by") or []:
        _edge(_named(other), tag)
    for g in d.get("group_tags") or []:
        gid = g.get("group_id")
        if not isinstance(gid, int) or s.get(Group, gid) is None:
            continue
        if s.execute(select(GroupTag).where(
            GroupTag.group_id == gid, GroupTag.tag_id == tag.id
        )).scalars().first() is None:
            s.add(GroupTag(group_id=gid, tag_id=tag.id,
                           negative=bool(g.get("negative"))))
    # The aliases went with it (their foreign key cascades), so they are
    # recreated pointing back at it.
    for a in d.get("aliases") or []:
        aname = (a.get("name") or "").strip()
        if not aname:
            continue
        existing = _named(aname)
        if existing is None:
            s.add(Tag(name=aname, comment=a.get("comment") or "",
                      alias_of_id=tag.id))
        elif existing.alias_of_id is None and existing.id != tag.id:
            existing.alias_of_id = tag.id
    # What the TAG SET said about it. These cascade with the row and no
    # other event records them, so the tag would come back stripped of the
    # meta tags a training run or a `TAG:` search reads.
    from .db import TagMetaTag

    meta_counts = d.get("meta_counts") or {}
    for meta in d.get("meta_tags") or []:
        name = " ".join(str(meta).split())[:64]
        if not name:
            continue
        if s.execute(select(TagMetaTag).where(
            TagMetaTag.tag_id == tag.id, TagMetaTag.name == name,
        )).scalars().first() is None:
            s.add(TagMetaTag(tag_id=tag.id, name=name,
                             count=max(0, int(meta_counts.get(name) or 0))))
    s.flush()
    return True


def _revert_split_item(s: Session, d: dict) -> bool:
    """Undo a file split — move the files back onto the original item, with
    their numbers, their bytes, their artifacts and their edit lineage, and
    delete the split-off item (its copied groups, tags, captions and the split
    relationship cascade away).

    Only a still-pristine split (the new item holds just the files the split
    moved) is reverted, so a split-off image the user has since built on is
    safe.

    A FILE'S NUMBER NAMES IT ON DISK, so putting the rows back is not enough:
    the split renumbered them from #1 and moved the bytes into the new item's
    folder, and a revert that only reassigned ``item_id`` left the file
    claiming a number the old item may already have had, with its bytes still
    in a folder that was about to be deleted. `ops/files.split` records what
    each file looked like (``files``), and this puts all of it back — number,
    path, edit chain, derived-from — re-deriving each artifact's path from the
    restored number, which is how it was built in the first place.

    Two things it cannot promise. An event logged BEFORE that record existed
    carries only ``file_id``/``file_ids``: the rows and bytes still come back,
    but under a FRESH number, since the original is not in the log. And a
    recorded number that the old item has since handed to another file gets
    the same treatment — `db.next_file_number` continues past the maximum, so
    a number freed by the split can be reissued once the survivors' maximum
    falls below it.

    Needs the store (`revert_event(store=...)` puts it on the session) and is
    REFUSED without one rather than half-done."""
    old = s.get(Item, d.get("old_item_id"))
    new = s.get(Item, d.get("new_item_id"))
    recorded = d.get("files") or []
    ids = ([r.get("id") for r in recorded] or d.get("file_ids")
           or ([d["file_id"]] if d.get("file_id") is not None else []))
    was = {r.get("id"): r for r in recorded}
    moved = [s.get(File, fid) for fid in ids]
    if old is None or new is None or not moved or any(f is None for f in moved):
        return False
    if any(f.item_id != new.id for f in moved):
        return False  # a file has moved on since the split
    files = s.execute(select(File.id).where(File.item_id == new.id)).scalars().all()
    if set(files) != {f.id for f in moved}:
        return False  # the split-off item gained other files — don't destroy them
    store = s.info.get("revert_store")
    if store is None:
        return False

    # The numbers the old item is using RIGHT NOW, so a recorded one that has
    # since been reissued there falls back to a fresh number instead of
    # colliding. Read before anything moves, and kept up to date below.
    taken = set(s.execute(
        select(File.number).where(File.item_id == old.id)
    ).scalars().all())
    for f in moved:
        r = was.get(f.id) or {}
        number = r.get("number")
        if number is None or number in taken:
            number = next_file_number(s, old.id)
            while number in taken:
                number += 1
        taken.add(number)
        # The bytes, and then every artifact derived from this file — each
        # rebuilt under the restored number exactly as the split rebuilt it
        # under the new one.
        if f.path:
            ext = f.path.rsplit(".", 1)[-1] if "." in f.path else (f.format or "bin")
            back = r.get("path")
            if not back:
                _dst, back = store.file_target(old.uid, number, ext)
            store.move_file(new.uid, old.uid, f.path, back)
            f.path = back
        for art in s.execute(
            select(FileArtifact).where(FileArtifact.file_id == f.id)
        ).scalars().all():
            if art.path:
                here = art.path
                aext = here.rsplit(".", 1)[-1] if "." in here else "png"
                data = store.file_path(new.uid, here).read_bytes()
                art.path = store.write_artifact(
                    old.uid, number, art.kind, aext, data, art.model
                )
                store.remove_file(new.uid, here)
            art.item_id = old.id
        f.item_id = old.id
        f.number = number
        f.edit_chain = r.get("edit_chain", "") or ""
        f.derived_from_file_id = r.get("based_on_file_id")
    new.active_file_id = None  # keep the moved files out of the delete cascade
    s.flush()
    s.delete(new)
    prev = d.get("old_active_before")
    if prev is not None and (pf := s.get(File, prev)) is not None and pf.item_id == old.id:
        old.active_file_id = prev
    touch_items(s, [old.id])
    return True


def _revert_merge_item(s: Session, d: dict) -> bool:
    """Undo a merge — recreate the source item (a new id) and move its files,
    group memberships, direct tags, captions and relationships back off the
    target. Sign-conflict tags dropped by the merge, and per-item tag groupings,
    are not restored (the merge already discarded them)."""
    target_id = d.get("target_id")
    target = s.get(Item, target_id)
    if target is None:
        return False
    new = Item(name=d.get("source_name") or "")
    # Restore the source's original dates so it reappears in place under the
    # import-date sorts rather than floating to the top as newly created.
    for attr, key in (
        ("created_at", "source_created_at"),
        ("last_imported_at", "source_last_imported_at"),
        ("updated_at", "source_updated_at"),
    ):
        raw = d.get(key)
        if raw:
            try:
                setattr(new, attr, datetime.fromisoformat(raw))
            except ValueError:
                pass
    s.add(new)
    s.flush()
    for fid in d.get("moved_file_ids") or []:
        f = s.get(File, fid)
        if f is not None and f.item_id == target_id:
            f.item_id = new.id
    for mt in d.get("moved_tags") or []:
        tag_id = mt.get("tag_id")
        if tag_id is None:
            continue
        it = s.execute(select(ItemTag).where(
            ItemTag.item_id == target_id, ItemTag.tag_id == tag_id
        )).scalars().first()
        if it is not None:
            it.item_id = new.id
        else:
            s.add(ItemTag(item_id=new.id, tag_id=tag_id,
                          negative=bool(mt.get("negative"))))
    for cid in d.get("moved_caption_ids") or []:
        c = s.get(Caption, cid)
        if c is not None and c.item_id == target_id:
            c.item_id = new.id
    for gid in d.get("added_group_ids") or []:
        s.execute(delete(ItemGroup).where(
            ItemGroup.item_id == target_id, ItemGroup.group_id == gid
        ))
        if s.get(Group, gid) is not None:
            s.add(ItemGroup(item_id=new.id, group_id=gid))
    old_source_id = d.get("source_id")
    for r in d.get("source_rels") or []:
        frm = new.id if r.get("from") == old_source_id else r.get("from")
        to = new.id if r.get("to") == old_source_id else r.get("to")
        if frm is None or to is None or frm == to:
            continue
        if s.get(Item, frm) is None or s.get(Item, to) is None:
            continue
        s.add(Relationship(from_item_id=frm, to_item_id=to,
                           kind=r.get("kind") or "manual", meta=r.get("meta") or ""))
    s.flush()
    src_active = d.get("source_active_file_id")
    if src_active is not None and (sf := s.get(File, src_active)) is not None and sf.item_id == new.id:
        new.active_file_id = src_active
    else:
        anyf = s.execute(select(File).where(File.item_id == new.id)).scalars().first()
        new.active_file_id = anyf.id if anyf is not None else None
    tgt_active = d.get("target_active_prev")
    if tgt_active is not None and (tf := s.get(File, tgt_active)) is not None and tf.item_id == target_id:
        target.active_file_id = tgt_active
    return True


def _revert_set_active_file(s: Session, d: dict) -> bool:
    """Undo an active-source-file switch — restore the previous active file, but
    only while it still belongs to the item (it may have been split off/deleted)."""
    item = s.get(Item, d.get("item_id"))
    prev = d.get("prev_active_file_id")
    if item is None or prev is None:
        return False
    f = s.get(File, prev)
    if f is None or f.item_id != item.id:
        return False
    item.active_file_id = prev
    return True


def _revert_add_link(s: Session, d: dict) -> bool:
    """Undo adding a link — delete the relationship it created (matched by its id,
    falling back to its endpoints/kind if the id has since changed)."""
    r = s.get(Relationship, d.get("rel_id")) if d.get("rel_id") else None
    if r is None or (r.from_item_id != d.get("from_item_id")
                     or r.to_item_id != d.get("to_item_id")
                     or r.kind != d.get("kind")):
        r = s.execute(select(Relationship).where(
            Relationship.from_item_id == d.get("from_item_id"),
            Relationship.to_item_id == d.get("to_item_id"),
            Relationship.kind == d.get("kind"),
        )).scalars().first()
    if r is not None:
        s.delete(r)
    return True  # already gone counts as reverted


def _revert_remove_link(s: Session, d: dict) -> bool:
    """Undo removing a link — recreate the relationship (and its link tags), if
    both items still exist and the link isn't already back."""
    frm, to = d.get("from_item_id"), d.get("to_item_id")
    if frm is None or to is None:
        return False
    if s.get(Item, frm) is None or s.get(Item, to) is None:
        return False
    r = s.execute(select(Relationship).where(
        Relationship.from_item_id == frm, Relationship.to_item_id == to,
        Relationship.kind == d.get("kind", "manual"),
    )).scalars().first()
    if r is None:
        r = Relationship(from_item_id=frm, to_item_id=to,
                         kind=d.get("kind") or "manual", meta=d.get("meta") or "")
        s.add(r)
        s.flush()
    for name in d.get("link_tags") or []:
        if not s.execute(select(RelationshipTag.id).where(
            RelationshipTag.relationship_id == r.id, RelationshipTag.name == name
        )).first():
            s.add(RelationshipTag(relationship_id=r.id, name=name))
    return True


def _revert_edit_image(s: Session, d: dict) -> bool:
    """Undo one editor save — by its own account of what it produced.

    A save INTO the item made a file active; putting the previous one back
    is the whole of the undo, and the file it wrote stays as a source (a
    revert does not delete files — that is the Sources list's verb). A save
    that made a NEW ITEM sends that item to the Trash, which is the way back
    every item has and is itself revertible.
    """
    made = d.get("new_item_id")
    if made is not None:
        from .ops.context import Ctx
        from .ops.items import trash_one

        if s.get(Item, made) is None:
            return True  # already gone counts as reverted
        trash_one(Ctx(session=s), made)
        return True
    it = s.get(Item, d.get("item_id"))
    was = d.get("old_active_file_id")
    if it is None or was is None:
        return False
    if s.get(File, was) is None:
        return False
    it.active_file_id = was
    s.flush()
    # The file the save wrote goes with it — `_drop_branched_file` is the
    # rotate revert's own rule and every one of its guards applies here for
    # the same reason: anything that has since built on that file, adopted
    # it or made it active leaves it standing.
    if d.get("file_id") and d.get("source_file_id"):
        _drop_branched_file(s, d["file_id"], d["source_file_id"])
    touch_items(s, [it.id])
    return True


def _revert_flip_link(s: Session, d: dict) -> bool:
    """Turn the link back round — and walk the cluster home with it.

    A flip is NOT its own inverse: on an `edit` link it re-roots every other
    edge onto the new original and drops one that became redundant, so the
    undo puts those back too, from the snapshot.
    """
    r = s.get(Relationship, d.get("rel_id"))
    if r is None:
        return False
    r.from_item_id, r.to_item_id = d.get("to_item_id"), d.get("from_item_id")
    for rid in d.get("moved_rel_ids") or []:
        sib = s.get(Relationship, rid)
        if sib is not None:
            sib.from_item_id = d.get("to_item_id")
    for row in d.get("dropped") or []:
        if (s.get(Item, row.get("from_item_id")) is None
                or s.get(Item, row.get("to_item_id")) is None):
            continue
        sib = Relationship(from_item_id=row["from_item_id"],
                           to_item_id=row["to_item_id"],
                           kind=row.get("kind") or "manual",
                           meta=row.get("meta") or "")
        s.add(sib)
        s.flush()
        for name in row.get("tags") or []:
            s.add(RelationshipTag(relationship_id=sib.id, name=name))
    return True


def _revert_create_group(s: Session, d: dict) -> bool:
    g = s.get(Group, d.get("group_id"))
    if g is None:
        return False
    s.execute(delete(GroupParent).where(GroupParent.group_id == g.id))
    s.execute(delete(GroupParent).where(GroupParent.parent_group_id == g.id))
    s.delete(g)
    return True


def _apply_group_fields(s: Session, gid, fields: dict) -> bool:
    """Put a group's own fields back (or forward) — the `edit_group` pair.

    The NAME goes through the sibling-uniqueness rule like every other write
    to it: the level may have gained the old name in the meantime, and an
    undo is not a licence to break the one invariant the tree relies on.
    """
    from .ops.groups import parent_of, unique_sibling_name

    g = s.get(Group, gid)
    if g is None:
        return False
    if "name" in fields:
        g.name = unique_sibling_name(s, parent_of(s, g.id), fields["name"],
                                     exclude_id=g.id)
    if "icon" in fields:
        g.icon = fields["icon"]
    if "color" in fields:
        g.color = fields["color"]
    if "smart_query" in fields:
        g.smart_query = fields["smart_query"]
        s.flush()
        _rebuild_smart_group(s, g)
    return True


def _rebuild_smart_group(s: Session, g: Group) -> None:
    """Refit a smart group's derived membership after its rule moved."""
    from .ops import smartgroups
    from .ops.context import Ctx

    if smartgroups.is_smart(g):
        smartgroups.rebuild(Ctx(session=s), g)


def _revert_edit_group(s: Session, d: dict) -> bool:
    return _apply_group_fields(s, d.get("group_id"), d.get("old") or {})


def _redo_edit_group(s: Session, d: dict) -> bool:
    return _apply_group_fields(s, d.get("group_id"), d.get("new") or {})


def _place_group(s: Session, gid, parent_id, name) -> bool:
    """Put a group under `parent_id` and give it back `name`.

    Both halves, because a move that had to number the arrival ("Trips 2")
    only reverts as a move if the number comes off again on the way home.
    """
    from .ops.groups import unique_sibling_name
    from .resolve import descendant_groups

    g = s.get(Group, gid)
    if g is None:
        return False
    if parent_id is not None:
        if s.get(Group, parent_id) is None:
            return False
        # The tree may have moved under us; a revert must not build a cycle.
        if parent_id in descendant_groups(s, [g.id]):
            return False
    s.execute(delete(GroupParent).where(GroupParent.group_id == g.id))
    if parent_id is not None:
        s.add(GroupParent(group_id=g.id, parent_group_id=parent_id))
    s.flush()
    if name:
        g.name = unique_sibling_name(s, parent_id, name, exclude_id=g.id)
    return True


def _revert_move_group(s: Session, d: dict) -> bool:
    return _place_group(s, d.get("group_id"), d.get("old_parent_id"),
                        d.get("old_name"))


def _redo_move_group(s: Session, d: dict) -> bool:
    return _place_group(s, d.get("group_id"), d.get("parent_id"),
                        d.get("name"))


def _revert_duplicate_group(s: Session, d: dict) -> bool:
    """Take the copy back down — the whole clone, subtree and all.

    `_redo_delete_group`'s reading rather than `_revert_create_group`'s: the
    duplicate made every group under it too, so undoing it means removing
    all of them. There is no redo, which is honest — re-cloning a group is
    not something a snapshot of the first clone can describe.
    """
    return _redo_delete_group(s, d)


def _redo_delete_group(s: Session, d: dict) -> bool:
    """Delete it AGAIN — the subtree and all, which is what the action does.

    Not `_revert_create_group`, which takes down one group and its own edges:
    that is the right answer for undoing a CREATE (nothing was under it yet)
    and the wrong one here, where a redo that left the children standing
    would not be the deletion being replayed.
    """
    from .resolve import descendant_groups

    gid = d.get("group_id")
    if gid is None or s.get(Group, gid) is None:
        return False
    for x in sorted(descendant_groups(s, [gid]), reverse=True):
        obj = s.get(Group, x)
        if obj is not None:
            s.delete(obj)
    return True


# ---- sequences --------------------------------------------------------------


def _restore_sequence(s: Session, d: dict) -> bool:
    """Put a sequence back the way the snapshot says — whether it was
    DELETED outright or merely had members taken out of it.

    One handler for both, because "remove the last member" deletes the
    sequence: the two endings differ only in whether the row is still there,
    and the answer either way is "make it hold exactly this list again". A
    restored sequence gets a NEW id (its container item is minted from it by
    `ensure_container`), which is the same trade `_revert_delete_place`
    makes when it re-creates a record by name.
    """
    from .db import Sequence, SequenceItem
    from .sequences import ensure_container, sync_container

    snap = d.get("sequence") or {}
    members = [int(i) for i in snap.get("members") or []]
    if not members:
        return False
    seq = s.get(Sequence, d.get("sequence_id"))
    if seq is None:
        seq = Sequence(name=snap.get("name") or "",
                       kind=snap.get("kind") or "manual",
                       source_name=snap.get("source_name") or "")
        s.add(seq)
        s.flush()
    else:
        s.execute(delete(SequenceItem)
                  .where(SequenceItem.sequence_id == seq.id))
        s.flush()
    live = [iid for iid in members if s.get(Item, iid) is not None]
    if not live:
        return False
    for pos, iid in enumerate(live):
        s.add(SequenceItem(sequence_id=seq.id, item_id=iid, position=pos))
    s.flush()
    ensure_container(s, seq)
    sync_container(s, seq.id)
    for iid in snap.get("main_for") or []:
        it = s.get(Item, iid)
        if it is not None and it.main_sequence_id is None:
            it.main_sequence_id = seq.id
    touch_items(s, live)
    return True


def _revert_create_sequence(s: Session, d: dict) -> bool:
    from .db import Sequence
    from .sequences import delete_sequence

    seq = s.get(Sequence, d.get("sequence_id"))
    if seq is None:
        return True  # already gone counts as reverted
    members = [si.item_id for si in seq.items]
    delete_sequence(s, seq)
    touch_items(s, members)
    return True


def _revert_rename_sequence(s: Session, d: dict) -> bool:
    return _name_sequence(s, d.get("sequence_id"), d.get("old_name"))


def _redo_rename_sequence(s: Session, d: dict) -> bool:
    return _name_sequence(s, d.get("sequence_id"), d.get("name"))


def _name_sequence(s: Session, seq_id, name) -> bool:
    from .db import Sequence

    seq = s.get(Sequence, seq_id)
    if seq is None or name is None:
        return False
    seq.name = name
    if seq.item_id is not None:  # the container item carries the name too
        container = s.get(Item, seq.item_id)
        if container is not None:
            container.name = name
    return True


def _order_sequence(s: Session, seq_id, member_ids) -> bool:
    from .db import SequenceItem
    from .sequences import sync_container

    if not member_ids:
        return False
    rows = {si.id: si for si in s.execute(
        select(SequenceItem).where(SequenceItem.sequence_id == seq_id)
    ).scalars().all()}
    # Every row the order names must still be there, or "put the list back"
    # would silently mean something else.
    if not rows or any(mid not in rows for mid in member_ids):
        return False
    for pos, mid in enumerate(member_ids):
        rows[mid].position = pos
    s.flush()
    sync_container(s, seq_id)
    touch_items(s, list({si.item_id for si in rows.values()}))
    return True


def _revert_reorder_sequence(s: Session, d: dict) -> bool:
    return _order_sequence(s, d.get("sequence_id"), d.get("old_member_ids"))


def _redo_reorder_sequence(s: Session, d: dict) -> bool:
    return _order_sequence(s, d.get("sequence_id"), d.get("member_ids"))


def _set_main_sequence(s: Session, item_id, seq_id) -> bool:
    from .db import Sequence, SequenceItem

    it = s.get(Item, item_id)
    if it is None:
        return False
    if seq_id is not None:
        if s.get(Sequence, seq_id) is None:
            return False
        member = s.execute(select(SequenceItem.id).where(
            SequenceItem.sequence_id == seq_id,
            SequenceItem.item_id == item_id)).first()
        if not member:
            return False
    it.main_sequence_id = seq_id
    return True


def _revert_set_main_sequence(s: Session, d: dict) -> bool:
    return _set_main_sequence(s, d.get("item_id"), d.get("old_sequence_id"))


def _redo_set_main_sequence(s: Session, d: dict) -> bool:
    return _set_main_sequence(s, d.get("item_id"), d.get("sequence_id"))


# ---- tag boxes --------------------------------------------------------------


def _apply_box_state(box: ItemTagBox, st: dict) -> None:
    box.x, box.y = st.get("x"), st.get("y")
    box.w, box.h = st.get("w"), st.get("h")
    box.time_start, box.time_end = st.get("time_start"), st.get("time_end")
    box.track_id = st.get("track_id")
    box.negative = bool(st.get("negative"))
    box.points = st.get("points")
    if st.get("placement_id") is not None:
        box.placement_id = st["placement_id"]


def _revert_add_tag_box(s: Session, d: dict) -> bool:
    """Remove the box — AND the assignment it minted, when it minted one.

    Drawing a shape for a tag the item did not carry assigns that tag, so an
    undo that took only the rectangle away would leave the tag behind the
    thing somebody just removed.
    """
    box = s.get(ItemTagBox, d.get("box_id"))
    if box is not None:
        s.delete(box)
    if d.get("minted_tag") and d.get("tag_id") is not None:
        row = s.execute(select(ItemTag).where(
            ItemTag.item_id == d.get("item_id"),
            ItemTag.tag_id == d.get("tag_id"))).scalars().first()
        if row is not None:
            s.execute(delete(ItemTagPlacement)
                      .where(ItemTagPlacement.item_tag_id == row.id))
            s.delete(row)
    if d.get("item_id"):
        touch_items(s, [d["item_id"]])
    return True


def _restore_tag_box(s: Session, d: dict, st: dict) -> bool:
    """Draw the box again on the placement it was on (a new row id)."""
    if not st or st.get("placement_id") is None:
        return False
    if s.get(ItemTagPlacement, st["placement_id"]) is None:
        return False
    box = ItemTagBox(placement_id=st["placement_id"], x=0, y=0, w=0, h=0)
    _apply_box_state(box, st)
    s.add(box)
    if d.get("item_id"):
        touch_items(s, [d["item_id"]])
    return True


def _revert_delete_tag_box(s: Session, d: dict) -> bool:
    return _restore_tag_box(s, d, d.get("box") or {})


def _move_tag_box(s: Session, d: dict, st: dict) -> bool:
    box = s.get(ItemTagBox, d.get("box_id"))
    if box is None or not st:
        return False
    _apply_box_state(box, st)
    if d.get("item_id"):
        touch_items(s, [d["item_id"]])
    return True


def _revert_edit_tag_box(s: Session, d: dict) -> bool:
    return _move_tag_box(s, d, d.get("old") or {})


def _redo_edit_tag_box(s: Session, d: dict) -> bool:
    return _move_tag_box(s, d, d.get("new") or {})


def _revert_add_source(s: Session, d: dict) -> bool:
    """Undo adding a source info — delete the FileName it created (matched by id,
    falling back to file_id+name)."""
    fn = s.get(FileName, d.get("name_id")) if d.get("name_id") else None
    if fn is None or fn.file_id != d.get("file_id") or fn.name != d.get("name"):
        fn = s.execute(select(FileName).where(
            FileName.file_id == d.get("file_id"), FileName.name == d.get("name"),
        )).scalars().first()
    if fn is not None:
        s.delete(fn)
    return True  # already gone counts as reverted


def _revert_add_sources_bulk(s: Session, d: dict) -> bool:
    """Undo a bulk web-source recording — delete exactly the FileName rows the
    batch created (matched by id, falling back to file+name+time; a row
    already gone counts as reverted, `_revert_add_source`'s rule)."""
    for name_id, file_id, name, acc in d.get("created", ()):
        fn = s.get(FileName, name_id) if name_id else None
        if fn is None or fn.file_id != file_id or fn.name != name:
            acc_dt = datetime.fromisoformat(acc) if acc else None
            fn = s.execute(select(FileName).where(
                FileName.file_id == file_id, FileName.name == name,
                FileName.accessed_at == acc_dt,
            )).scalars().first()
        if fn is not None:
            s.delete(fn)
    return True


def _revert_add_tags_bulk(s: Session, d: dict) -> bool:
    """Undo a bulk tag assignment — delete exactly the (item, tag) rows the
    batch created. The batch only ever ADDED rows the items did not carry,
    so deleting the recorded pairs restores the state precisely; a pair
    already gone counts as reverted."""
    touched = []
    for iid, tid, _neg in d.get("created", ()):
        row = s.execute(select(ItemTag).where(
            ItemTag.item_id == iid, ItemTag.tag_id == tid,
        )).scalars().first()
        if row is not None:
            s.delete(row)
            touched.append(iid)
    if touched:
        s.flush()
        touch_items(s, sorted(set(touched)))
    return True


def _revert_rename_source(s: Session, d: dict) -> bool:
    """Undo a source-info edit — set its name back (matched by id, else new name)."""
    fn = s.get(FileName, d.get("name_id")) if d.get("name_id") else None
    if fn is None or fn.file_id != d.get("file_id"):
        fn = s.execute(select(FileName).where(
            FileName.file_id == d.get("file_id"), FileName.name == d.get("new_name"),
        )).scalars().first()
    if fn is None:
        return False
    fn.name = d.get("old_name") or fn.name
    return True


def _revert_remove_source(s: Session, d: dict) -> bool:
    """Undo removing a source info — re-add the FileName if the file still exists
    and it isn't already back."""
    file_id, name = d.get("file_id"), d.get("name")
    if file_id is None or name is None or s.get(File, file_id) is None:
        return False
    if s.execute(select(FileName.id).where(
        FileName.file_id == file_id, FileName.name == name
    )).first():
        return True  # already back
    acc = d.get("accessed_at")
    s.add(FileName(
        file_id=file_id, name=name, is_url=bool(d.get("is_url")),
        accessed_at=datetime.fromisoformat(acc) if acc else None,
    ))
    return True


def _meta_tag_carrier(s: Session, d: dict):
    """(model, owner column, owner id, item id) for a meta-tag event — a
    caption's, a tag group's or a link's. Meta tags carry no item_id of their
    own, so the item has to be looked up to keep its sidecar in step.

    ONE namespace, four carriers, and this is what lets one pair of revert
    handlers serve all of them (`_revert_add_meta_tag` / `_revert_remove_...`)
    — which is also why adding the link's own actions to the tables below was
    a two-line change rather than a third implementation.

    The TAG carrier is the one with no item at all: it annotates the
    tag set, so its item id is None and the handlers mark the CATALOG dirty
    instead. It is asked LAST, because a caption's, a group's and a link's
    payload each name their own carrier and only this one keys on `tag_id`."""
    from .db import (CaptionTag, ItemTagGroup, ItemTagGroupTag,
                     RelationshipTag, TagMetaTag)

    if d.get("caption_id") is not None:
        cap = s.get(Caption, d["caption_id"])
        if cap is None:
            return None
        return CaptionTag, CaptionTag.caption_id, cap.id, cap.item_id
    if d.get("group_id") is not None:
        grp = s.get(ItemTagGroup, d["group_id"])
        if grp is None:
            return None
        return (ItemTagGroupTag, ItemTagGroupTag.group_id, grp.id, grp.item_id)
    if d.get("rel_id") is not None:
        rel = s.get(Relationship, d["rel_id"])
        if rel is None:
            return None
        return (RelationshipTag, RelationshipTag.relationship_id, rel.id,
                rel.from_item_id)
    if d.get("tag_id") is not None:
        tag = s.get(Tag, d["tag_id"])
        if tag is None:
            return None
        return TagMetaTag, TagMetaTag.tag_id, tag.id, None
    return None


def _touch_meta_carrier(s: Session, item_id) -> None:
    """Bump the carrying item's modification date. The tag carrier has no
    item — its meta tags annotate the tag set — so there is nothing to
    touch there."""
    if item_id is not None:
        touch_items(s, [item_id])


def _revert_add_meta_tag(s: Session, d: dict) -> bool:
    carrier = _meta_tag_carrier(s, d)
    if carrier is None or not d.get("name"):
        return False
    model, owner, owner_id, item_id = carrier
    row = s.execute(select(model).where(
        owner == owner_id, model.name == d["name"])).scalars().first()
    if row is not None:
        s.delete(row)
    _touch_meta_carrier(s, item_id)
    return True


def _revert_remove_meta_tag(s: Session, d: dict) -> bool:
    from .db import LIB_META, LinkTag

    carrier = _meta_tag_carrier(s, d)
    if carrier is None or not d.get("name"):
        return False
    model, owner, owner_id, item_id = carrier
    exists = s.execute(select(model).where(
        owner == owner_id, model.name == d["name"])).scalars().first()
    if exists is None:
        fields = {owner.key: owner_id, "name": d["name"]}
        # The TAG carrier's assignments carry a count (recorded only when
        # nonzero); the revert restores the SHAPE, and the count is part of
        # it. The other three carriers have no such column and no such key.
        if d.get("count") and hasattr(model, "count"):
            fields["count"] = max(0, int(d["count"]))
        s.add(model(**fields))
        # A meta tag survives its last use, so put the NAME back in the
        # catalog too — deleting the last one may have been what removed it.
        if s.execute(select(LinkTag).where(
                LinkTag.name == d["name"], LIB_META)).scalar_one_or_none() is None:
            s.add(LinkTag(name=d["name"]))
    _touch_meta_carrier(s, item_id)
    return True


def _revert_move_tag_group(s: Session, d: dict) -> bool:
    """Put a moved tag instance back in the group it came from.

    Reuses the move operation's own helpers rather than re-implementing the
    merge: moving into a group that already holds the tag folds the two
    instances (and their boxes) together, and undoing has to do the same.
    """
    # Imported here, not at module scope: `ops.context` imports `log_event`
    # from this module, so a top-level import is a cycle.
    from .ops import ctx_for, tagassign

    ctx = ctx_for(s)

    item_id, name = d.get("item_id"), d.get("tag")
    if item_id is None or not name:
        return False
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if tag is None:
        return False
    it_tag = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag.id)).scalars().first()
    if it_tag is None:
        return False
    # Back the way it came: the event's "to" is where it is now.
    src = tagassign.ensure_placement(ctx, it_tag.id, d.get("to_group_id"))
    tagassign.merge_placement_into_group(ctx, src, d.get("from_group_id"))
    # The move endpoint recomputes this and the undo has to as well, or moving
    # a tag OUT of a Pending group and undoing leaves it sitting in that group
    # no longer flagged pending — a state nothing else can produce, in which
    # search, training and export treat it as approved while the box around it
    # says it is waiting for an answer.
    tagassign.recompute_pending(ctx, it_tag.id)
    touch_items(s, [item_id])
    return True


# ---- faces -----------------------------------------------------------------

def _restore_appearance(s, entry: dict) -> None:
    """Put one appearance back exactly as it was — its ID included.

    The SHAPE matters, not just the subject: a guess restored as an answer
    would be immune to the next run that disagrees with it, an answer restored
    as a guess would be overwritten by one, and an age typed by hand would
    simply be gone.

    And so does the **identity**. `_revert_add_appearance`,
    `_revert_edit_appearance` and `_revert_name_face` all find their row with
    `s.get(ItemSubject, d["appearance_id"])`, so a restore that minted a fresh
    id silently broke the next Undo in the chain: it looked the row up by the
    id it had recorded, found nothing, and returned False — which the History
    view renders as "could not be undone" for an action that plainly could.
    Reachable in three clicks: put somebody in a picture, give them an age,
    take them out, then Undo three times. The first worked and the other two
    did nothing.

    The recorded id is reused only when it is still FREE. SQLite hands out
    `max(rowid) + 1`, so a row deleted at the top of the table has its id
    handed to whatever is inserted next — the same rowid-reuse trap
    `FaceRejection` carries `item_uid`/`box` to survive. When it is taken, a
    fresh id is the honest answer and the chain simply behaves as it did
    before.
    """
    from .db import ItemSubject

    face_id = entry.get("face_id")
    exists = s.execute(select(ItemSubject).where(
        ItemSubject.item_id == entry.get("item_id"),
        ItemSubject.subject_id == entry.get("subject_id"),
        ItemSubject.face_id.is_(None) if face_id is None
        else ItemSubject.face_id == face_id,
    )).scalars().first()
    if exists is not None:
        row = exists
    else:
        row = ItemSubject(item_id=entry.get("item_id"),
                          subject_id=entry.get("subject_id"), face_id=face_id)
        want = entry.get("appearance_id")
        if want and s.get(ItemSubject, want) is None:
            row.id = want
        s.add(row)
    row.when_date = entry.get("when_date")
    row.when_age = entry.get("when_age")
    row.assigned_by = entry.get("assigned_by") or "user"
    row.match_score = entry.get("match_score")


def _drop_tag_if(s, item_id: int, subject_id, added) -> None:
    """Take a subject's tag off an item, when the action being undone is what
    put it there."""
    from .db import ItemTag, Subject

    if not added:
        return
    subject = s.get(Subject, subject_id)
    if subject is None or subject.tag_id is None:
        return
    row = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == subject.tag_id,
    )).scalars().first()
    if row is not None:
        s.delete(row)


def _revert_name_face(s: Session, d: dict) -> bool:
    """Undo saying who a face is: the claim goes, and the tag with it only if
    naming put it there."""
    from .db import ItemSubject, Subject

    row = s.get(ItemSubject, d.get("appearance_id"))
    if row is None:
        return False
    item_id = row.item_id
    if d.get("was_new"):
        s.delete(row)
    if d.get("created_subject"):
        subject = s.get(Subject, d.get("subject_id"))
        if subject is not None:
            s.delete(subject)
    else:
        s.flush()
        _drop_tag_if(s, item_id, d.get("subject_id"), d.get("was_new"))
    touch_items(s, [item_id])
    return True


def _revert_add_appearance(s: Session, d: dict) -> bool:
    from .db import ItemSubject, Subject

    row = s.get(ItemSubject, d.get("appearance_id"))
    if row is None:
        return False
    item_id, subject_id = row.item_id, row.subject_id
    s.delete(row)
    s.flush()
    left = s.execute(select(ItemSubject).where(
        ItemSubject.item_id == item_id,
        ItemSubject.subject_id == subject_id)).scalars().first()
    if left is None:
        _drop_tag_if(s, item_id, subject_id, True)
    if d.get("created_subject"):
        subject = s.get(Subject, subject_id)
        if subject is not None:
            s.delete(subject)
    touch_items(s, [item_id])
    return True


def _revert_edit_appearance(s: Session, d: dict) -> bool:
    from .db import ItemSubject

    row = s.get(ItemSubject, d.get("appearance_id"))
    if row is None:
        return False
    row.when_date, row.when_age = d.get("old_date"), d.get("old_age")
    row.face_id = d.get("old_face_id")
    touch_items(s, [row.item_id])
    return True


def _revert_confirm_appearance(s: Session, d: dict) -> bool:
    """Un-agree with a guess: the flag AND the score go back.

    The same rule `unname_face` follows — a guess restored as a `"user"` answer
    would be immune to the next run that disagrees with it, and a score is what
    says how sure the machine was. The tag it put on the picture goes back to
    pending too, since the reason for the flag has not changed.
    """
    from .db import ItemSubject, ItemTag, Subject

    row = s.get(ItemSubject, d.get("appearance_id"))
    if row is None:
        return False
    row.assigned_by = d.get("old_assigned_by") or "suggested"
    row.match_score = d.get("old_match_score")
    subject = s.get(Subject, row.subject_id)
    if subject is not None and subject.tag_id is not None:
        # Only where NO other answer on this item still stands behind it.
        others = s.execute(select(ItemSubject).where(
            ItemSubject.item_id == row.item_id,
            ItemSubject.subject_id == row.subject_id,
            ItemSubject.id != row.id,
            ItemSubject.assigned_by == "user")).scalars().first()
        if others is None:
            it = s.execute(select(ItemTag).where(
                ItemTag.item_id == row.item_id,
                ItemTag.tag_id == subject.tag_id)).scalars().first()
            if it is not None:
                # `tag_added` says confirming is what PUT the tag there, so
                # flagging it pending would leave behind a tag the picture
                # never carried. Older events lack the key and fall back to
                # the flag, which is what they recorded.
                if d.get("tag_added"):
                    s.delete(it)
                else:
                    it.pending = True
    touch_items(s, [row.item_id])
    return True


def _revert_remove_appearance(s: Session, d: dict) -> bool:
    from .db import ItemTag, Subject

    _restore_appearance(s, {"item_id": d.get("item_id"),
                            "subject_id": d.get("subject_id"),
                            "face_id": d.get("face_id"),
                            "appearance_id": d.get("appearance_id"),
                            "when_date": d.get("date"),
                            "when_age": d.get("age"),
                            "assigned_by": d.get("assigned_by"),
                            "match_score": d.get("match_score")})
    if d.get("tag_removed"):
        subject = s.get(Subject, d.get("subject_id"))
        if subject is not None and subject.tag_id is not None:
            exists = s.execute(select(ItemTag).where(
                ItemTag.item_id == d.get("item_id"),
                ItemTag.tag_id == subject.tag_id,
            )).scalars().first()
            if exists is None:
                s.add(ItemTag(item_id=d.get("item_id"), tag_id=subject.tag_id,
                              negative=False))
    touch_items(s, [d.get("item_id")])
    return True


def _revert_name_faces(s: Session, d: dict) -> bool:
    """Undo naming a whole cluster — every claim, every back-filled tag, and
    the subject too when the naming is what created it.

    The faces go back to WHOEVER they were on, not to nobody: the same call
    names an unnamed cluster (where that is nobody) and moves crops from one
    person's row to another's, and undoing the second must return them.
    """
    from .db import ItemSubject, Subject

    subject_id = d.get("subject_id")
    for face_id in d.get("face_ids") or []:
        for row in s.execute(select(ItemSubject).where(
            ItemSubject.face_id == face_id,
            ItemSubject.subject_id == subject_id,
        )).scalars().all():
            s.delete(row)
    s.flush()
    for entry in d.get("before") or []:
        _restore_appearance(s, entry)
        # A replace recorded the displaced guess as refused; the refusal goes
        # with the undo, or the restored guess is vetoed by the very next run
        # (the same rule `_revert_unname_face` spells out).
        if entry.get("assigned_by") == "suggested":
            from .db import FaceRejection

            s.execute(delete(FaceRejection).where(
                FaceRejection.face_id == entry.get("face_id"),
                FaceRejection.subject_id == entry.get("subject_id")))
    s.flush()
    for item_id in d.get("backfilled") or []:
        _drop_tag_if(s, item_id, subject_id, True)
    touch_items(s, d.get("backfilled") or [])
    if d.get("created_subject"):
        subject = s.get(Subject, subject_id)
        still = s.execute(select(ItemSubject.id).where(
            ItemSubject.subject_id == subject_id).limit(1)).first()
        if subject is not None and still is None:
            s.delete(subject)
    return True


def _revert_dismiss_face(s: Session, d: dict) -> bool:
    from .db import Face

    face = s.get(Face, d.get("face_id"))
    if face is None:
        return False
    face.dismissed = not bool(d.get("dismissed"))
    return True


def _revert_add_face(s: Session, d: dict) -> bool:
    from .db import Face

    face = s.get(Face, d.get("face_id"))
    if face is None:
        return False
    item_id = face.item_id
    s.delete(face)
    touch_items(s, [item_id])
    return True


def _revert_delete_face(s: Session, d: dict) -> bool:
    """Put a deleted face back — box, score and everyone it was.

    The descriptor is NOT restored: it is regenerable from the picture, and
    carrying a few kilobytes of floats in every event log entry to save one
    re-run is the wrong trade.
    """
    from .db import Face

    box = d.get("box") or [0, 0, 0, 0]
    face = Face(item_id=d.get("item_id"), x=box[0], y=box[1], w=box[2],
                h=box[3], det_score=d.get("det_score"),
                model=d.get("model") or "",
                dismissed=bool(d.get("dismissed")))
    s.add(face)
    s.flush()
    for entry in d.get("subjects") or []:
        _restore_appearance(s, {**entry, "face_id": face.id})
    touch_items(s, [d.get("item_id")])
    return True


def _revert_unname_face(s: Session, d: dict) -> bool:
    """Put a name back on a face — as the answer it was, not as a new one."""
    from .db import Face, FaceRejection, ItemTag, Subject

    face = s.get(Face, d.get("face_id"))
    old = d.get("old_subject_id")
    if face is None or not old:
        return False
    _restore_appearance(s, {"item_id": face.item_id, "subject_id": old,
                            "face_id": face.id,
                            "appearance_id": d.get("old_appearance_id"),
                            "when_date": d.get("old_date"),
                            "when_age": d.get("old_age"),
                            "assigned_by": d.get("old_assigned_by"),
                            "match_score": d.get("old_match_score")})
    # The refusal goes with it. Leaving it would restore the name and have the
    # very next run veto it — an undo that undoes itself.
    s.execute(delete(FaceRejection).where(FaceRejection.face_id == face.id,
                                          FaceRejection.subject_id == old))
    # The pending tag the guess had put there went with it; put that back too,
    # pending as it was — the reason it was pending has not changed.
    if d.get("tag_removed"):
        subject = s.get(Subject, old)
        if subject is not None and subject.tag_id is not None:
            exists = s.execute(select(ItemTag).where(
                ItemTag.item_id == face.item_id,
                ItemTag.tag_id == subject.tag_id,
            )).scalars().first()
            if exists is None:
                s.add(ItemTag(item_id=face.item_id, tag_id=subject.tag_id,
                              negative=False, pending=True))
    touch_items(s, [face.item_id])
    return True


def _revert_move_face(s: Session, d: dict) -> bool:
    from .db import Face, FaceBoxEdit

    face = s.get(Face, d.get("face_id"))
    box = d.get("old_box") or []
    if face is None or len(box) != 4:
        return False
    face.x, face.y, face.w, face.h = box
    # The move that first edited a DETECTED face also kept the detector's
    # rectangle aside; undoing that move takes the record down with it, or
    # the face reads as hand-edited while holding the detector's own box.
    if d.get("orig_recorded"):
        rec = s.execute(select(FaceBoxEdit).where(
            FaceBoxEdit.face_id == face.id)).scalars().first()
        if rec is not None:
            s.delete(rec)
    touch_items(s, [face.item_id])
    return True


def _revert_reorder_appearances(s: Session, d: dict) -> bool:
    from .db import ItemSubject

    old = d.get("old_positions") or {}
    ok = False
    for k, v in old.items():
        row = s.get(ItemSubject, int(k))
        if row is not None:
            row.position = int(v)
            ok = True
    if ok:
        touch_items(s, [d.get("item_id")])
    return ok


def _revert_reset_face_box(s: Session, d: dict) -> bool:
    """Put the hand-edited rectangle back — INCLUDING the edit record, with
    the detector's box the reset restored. Restored without it, the edit
    would be overwritten by the next run and could never be reset again."""
    from .db import Face, FaceBoxEdit

    face = s.get(Face, d.get("face_id"))
    old = d.get("old_box") or []
    det = d.get("box") or []
    if face is None or len(old) != 4 or len(det) != 4:
        return False
    face.x, face.y, face.w, face.h = old
    exists = s.execute(select(FaceBoxEdit).where(
        FaceBoxEdit.face_id == face.id)).scalars().first()
    if exists is None:
        s.add(FaceBoxEdit(face_id=face.id, x=det[0], y=det[1],
                          w=det[2], h=det[3]))
    touch_items(s, [face.item_id])
    return True


def _revert_edit_text(s: Session, d: dict) -> bool:
    """Put a transcription back — INCLUDING its `edited` flag. A machine's
    reading restored as an edited one is immune to the next run that reads it
    better; an edit restored as un-edited is silently overwritten by one."""
    from .db import TextRegion

    region = s.get(TextRegion, d.get("region_id"))
    if region is None or "old_text" not in d:
        return False
    region.text = d.get("old_text") or ""
    region.edited = bool(d.get("old_edited"))
    touch_items(s, [region.item_id])
    return True


def _revert_dismiss_text(s: Session, d: dict) -> bool:
    from .db import TextRegion

    region = s.get(TextRegion, d.get("region_id"))
    if region is None:
        return False
    region.dismissed = not bool(d.get("dismissed"))
    touch_items(s, [region.item_id])
    return True


def _redo_dismiss_text(s: Session, d: dict) -> bool:
    from .db import TextRegion

    region = s.get(TextRegion, d.get("region_id"))
    if region is None:
        return False
    region.dismissed = bool(d.get("dismissed"))
    touch_items(s, [region.item_id])
    return True


def _revert_move_text(s: Session, d: dict) -> bool:
    """The QUAD travels with the box, or undoing a moved rotated line puts
    back an upright rectangle — silently."""
    from .db import TextRegion

    region = s.get(TextRegion, d.get("region_id"))
    box = d.get("old_box") or []
    if region is None or len(box) != 4:
        return False
    region.x, region.y, region.w, region.h = box
    region.quad = d.get("old_quad") or ""
    touch_items(s, [region.item_id])
    return True


def _revert_add_text(s: Session, d: dict) -> bool:
    from .db import TextRegion

    region = s.get(TextRegion, d.get("region_id"))
    if region is None:
        return False
    item_id = region.item_id
    s.delete(region)  # the FK CASCADE takes any children down with it
    touch_items(s, [item_id])
    return True


def _revert_delete_text(s: Session, d: dict) -> bool:
    """Put a deleted region back — the whole SUBTREE, under fresh rowids.

    Deleting a block CASCADEd its lines and words away, so the event carries
    the tree; without it the undo would put back a block with no lines. Ids
    are not restored — SQLite may have handed them on (`FaceRejection`'s
    rowid-reuse lesson)."""
    from .db import TextRegion
    from .ops.ocr import restore_subtree

    tree = d.get("tree")
    item_id = d.get("item_id")
    if not tree or item_id is None:
        return False
    parent_id = d.get("parent_id")
    if parent_id is not None and s.get(TextRegion, parent_id) is None:
        # The parent is gone; better a block at top level than lost text.
        parent_id = None
    # WHICH FILE the reading was of. An event from before file binding
    # carries none — fall back to the item's active file, the file every
    # region of that era was implicitly about.
    file_id = d.get("file_id")
    if file_id is None:
        item = s.get(Item, item_id)
        file_id = item.active_file_id if item is not None else None
    elif s.get(File, file_id) is None:
        # The file itself has been deleted since; there is nothing for the
        # reading to describe any more.
        return False
    row = restore_subtree(s, item_id, tree, parent_id=parent_id,
                          file_id=file_id)
    row.ord = int(d.get("ord") or row.ord)
    touch_items(s, [item_id])
    return True


def _revert_reorder_text(s: Session, d: dict) -> bool:
    from .db import TextRegion

    old = d.get("old_order") or []
    if not old:
        return False
    rows = {r.id: r for r in s.execute(
        select(TextRegion).where(TextRegion.id.in_(old))
    ).scalars().all()}
    for pos, rid in enumerate(old):
        region = rows.get(rid)
        if region is not None:
            region.ord = pos
    touch_items(s, [d.get("item_id")])
    return True


def _restore_assignments(s: Session, d: dict) -> bool:
    """Undo a merge or a split: every face back where it was, and the identity
    the action minted deleted with it.

    One handler for both, because they are the same edit in two directions —
    each moves a set of faces onto one nameless subject and records what they
    were on before.
    """
    from .db import ItemSubject, Subject

    rows = d.get("before")
    if rows is None:
        return False
    subject_id = d.get("subject_id")
    # The faces the action touched, from the event — NOT from the snapshot,
    # which is empty when the faces had no name to begin with (two unnamed
    # clusters merged), and the rows the merge wrote would then survive it.
    faces = d.get("face_ids") or [r.get("face_id") for r in rows]
    for row in s.execute(select(ItemSubject).where(
        ItemSubject.subject_id == subject_id,
        ItemSubject.face_id.in_([f for f in faces if f is not None]),
    )).scalars().all():
        s.delete(row)
    s.flush()
    for entry in rows:
        _restore_appearance(s, entry)
        touch_items(s, [entry.get("item_id")])
    s.flush()
    if d.get("created_subject"):
        subject = s.get(Subject, subject_id)
        # Only when nothing was left behind on it — a second merge into the
        # same identity would otherwise take the first one's faces with it.
        still = s.execute(select(ItemSubject.id).where(
            ItemSubject.subject_id == subject_id).limit(1)).first()
        if subject is not None and still is None:
            s.delete(subject)
    return True


def _revert_clusters_differ(s: Session, d: dict) -> bool:
    """Take back "not this person": the two identities may be one again.

    The nameless identities the statement needed are LEFT: they hold the
    clusters as they stood when somebody looked at them, which is what a
    merge's own revert leaves too where it did not mint them.
    """
    from . import faces as facelib

    a, b = d.get("a_subject_id"), d.get("b_subject_id")
    if a is None or b is None:
        return False
    facelib.allow_same(s, int(a), int(b))
    return True


def _revert_set_cluster_unnamed(s: Session, d: dict) -> bool:
    """Undo "this is somebody with no name": the flag goes back to what it
    was, and the faces to where they were.

    `_restore_assignments`' shape plus one column — the mark is a flag on a
    nameless subject, and the reseating that put the cluster on one is the
    same move a merge makes.
    """
    from .db import Subject

    subject = s.get(Subject, d.get("subject_id"))
    if subject is not None:
        subject.unnamed = bool(d.get("was", False))
        s.flush()
    return _restore_assignments(s, d)


# A detection run is deliberately not undone — its faces are evidence, not an
# edit, and dismissing a wrong one is the action that exists for that. That is
# said by `detect_faces` simply not being in `_REVERT` (so `is_revertible`
# answers False and the UI never offers the button); `ops/actions.
# NOT_REVERTIBLE` records the reason. A handler returning False was tried and
# was dead code: nothing ever wired it into the table.

# ---- tag sets -----------------------------------------------------------------
# An imported tag list (`ops/tagsets.py`). Every op there logs one event and
# every one but `delete_tag_set` reverts; the payloads carry the tag set's
# `key` beside its id as the rowid-reuse guard.

def _tag_set_by(s: Session, d: dict):
    from .db import TagSet

    row = s.get(TagSet, d.get("tag_set_id"))
    if row is None or row.key != d.get("key"):
        return None
    return row


def _revert_create_tag_set(s: Session, d: dict) -> bool:
    """Take a fresh set down — only while it is still EMPTY. One that has
    gained entries since is somebody's work, which "created a set" never
    promised to take."""
    from .ops import tagsets as tagsets_ops

    row = _tag_set_by(s, d)
    if row is None or row.builtin:
        return False
    n_entries, n_cats = tagsets_ops.counts_of(s).get(row.id, (0, 0))
    if n_entries or n_cats:
        return False
    s.delete(row)
    return True


def _redo_create_tag_set(s: Session, d: dict) -> bool:
    from .db import TagSet

    if _tag_set_by(s, d) is not None or s.get(TagSet, d.get("tag_set_id")) is not None:
        return False
    s.execute(TagSet.__table__.insert().values(
        id=d["tag_set_id"], key=d["key"], name=d.get("name") or d["key"],
        description=d.get("description") or "", version=int(d.get("version") or 0),
        builtin=False, enabled=True,
        position=int(d.get("position") or 0)))
    return True


def _revert_edit_tag_set(s: Session, d: dict) -> bool:
    row = _tag_set_by(s, d)
    if row is None:
        return False
    for f in ("name", "description", "version", "position",
              "aliases_enabled", "implications_enabled"):
        # A field is IN the edit when either half is set — after `_swap_many`
        # every named field carries both keys, None where the edit never
        # touched it, and a None must not overwrite a name.
        if d.get(f"old_{f}") is not None or d.get(f) is not None:
            setattr(row, f, d[f"old_{f}"])
    s.flush()
    return True


def _revert_set_tag_set_enabled(s: Session, d: dict) -> bool:
    row = _tag_set_by(s, d)
    if row is None:
        return False
    row.enabled = bool(d.get("old_enabled", True))
    s.flush()
    return True


def _revert_duplicate_tag_set(s: Session, d: dict) -> bool:
    """The COPY goes; the source is untouched."""
    from .db import TagSet
    from .ops import tagsets as tagsets_ops

    copy = s.get(TagSet, d.get("new_tag_set_id"))
    if copy is None or copy.key != d.get("new_key") or copy.builtin:
        return False
    tagsets_ops._clear_rows(s, copy.id)
    s.delete(copy)
    return True


def _revert_import_tag_set(s: Session, d: dict) -> bool:
    """Only while the event carries its `undo` block (`can_revert` says so
    before the button is offered) — the `delete_group` rule."""
    from .ops import tagsets as tagsets_ops

    undo = d.get("undo")
    if not isinstance(undo, dict) or _tag_set_by(s, d) is None:
        return False
    return tagsets_ops.revert_import(s, undo)


def _revert_create_tag_set_category(s: Session, d: dict) -> bool:
    from .db import TagSetCategory, TagSetEntry

    row = s.get(TagSetCategory, d.get("category_id"))
    if row is None or row.tag_set_id != d.get("tag_set_id") or row.name != d.get("name"):
        return False
    if s.execute(select(TagSetEntry.id).where(
            TagSetEntry.category_id == row.id).limit(1)).first():
        return False
    if s.execute(select(TagSetCategory.id).where(
            TagSetCategory.parent_id == row.id).limit(1)).first():
        return False
    s.delete(row)
    return True


def _revert_move_tag_set_category(s: Session, d: dict) -> bool:
    """Put every sibling the move renumbered back — both parents' orders as
    the event recorded them BEFORE (`old_orders`). The redo is the same
    function over the swapped payload, so it replays `orders` through the
    one primitive rather than re-deriving a placement."""
    from .db import TagSetCategory
    from .ops import tagsets as tagsets_ops

    row = s.get(TagSetCategory, d.get("category_id"))
    if row is None or row.tag_set_id != d.get("tag_set_id"):
        return False
    tagsets_ops._place_categories(s, d["tag_set_id"], d.get("old_orders") or {})
    return True


def _revert_edit_tag_set_category(s: Session, d: dict) -> bool:
    from .db import TagSetCategory

    row = s.get(TagSetCategory, d.get("category_id"))
    if row is None or row.tag_set_id != d.get("tag_set_id"):
        return False
    for f in ("name", "parent_id", "icon", "hidden", "position"):
        # A field is IN the edit when either half is set — after `_swap_many`
        # every named field carries both keys, None where the edit never
        # touched it, and a None must not overwrite a name.
        if d.get(f"old_{f}") is not None or d.get(f) is not None:
            setattr(row, f, d[f"old_{f}"])
    # The THREE-STATE fields say so by name (`tri_fields`), because for them
    # None is an answer — "inherit from the parent" — and the test above
    # cannot tell it from "not in this edit".
    for f in d.get("tri_fields") or ():
        if f in ("aliases", "implications"):
            setattr(row, f, d.get(f"old_{f}"))
    s.flush()
    return True


def _revert_delete_tag_set_category(s: Session, d: dict) -> bool:
    from .ops import tagsets as tagsets_ops

    return tagsets_ops.restore_category(s, d)


def _revert_create_tag_set_meta(s: Session, d: dict) -> bool:
    from .db import MetaTag

    row = s.get(MetaTag, d.get("meta_id"))
    if row is None or row.tag_set_id != d.get("tag_set_id") \
            or row.name != d.get("name"):
        return False
    s.delete(row)
    return True


def _revert_edit_tag_set_meta(s: Session, d: dict) -> bool:
    from .db import MetaTag
    from .ops import tagsets as tagsets_ops

    row = s.get(MetaTag, d.get("meta_id"))
    if row is None or row.tag_set_id != d.get("tag_set_id"):
        return False
    fields = {f: d.get(f"old_{f}")
              for f in ("name", "comment", "description")
              if d.get(f"old_{f}") is not None or d.get(f) is not None}
    if fields.get("name") is None:
        fields.pop("name", None)
    tagsets_ops.apply_meta_fields(s, row, fields)
    return True


def _revert_delete_tag_set_meta(s: Session, d: dict) -> bool:
    from .ops import tagsets as tagsets_ops

    return tagsets_ops.restore_meta_tag(s, d.get("tag_set_id"), d)


def _revert_create_tag_set_entry(s: Session, d: dict) -> bool:
    from .db import TagSetEntry

    row = s.get(TagSetEntry, d.get("entry_id"))
    if row is None or row.tag_set_id != d.get("tag_set_id") or row.name != d.get("name"):
        return False
    s.delete(row)
    return True


def _revert_edit_tag_set_entry(s: Session, d: dict) -> bool:
    from .db import TagSetEntry
    from .ops import tagsets as tagsets_ops

    row = s.get(TagSetEntry, d.get("entry_id"))
    if row is None or row.tag_set_id != d.get("tag_set_id"):
        return False
    fields = {f: d.get(f"old_{f}")
              for f in ("name", "description", "count", "category_id",
                        "aliases", "implies", "meta", "comment",
                        *tagsets_ops.RECORD_FIELDS)
              if d.get(f"old_{f}") is not None or d.get(f) is not None}
    if fields.get("name") is None:
        fields.pop("name", None)
    tagsets_ops.apply_entry_fields(s, row, fields)
    return True


def _revert_delete_tag_set_entry(s: Session, d: dict) -> bool:
    from .ops import tagsets as tagsets_ops

    return tagsets_ops.restore_entry(s, d.get("tag_set_id"), d)


_REVERT: dict[str, Callable[[Session, dict], bool]] = {
    "add_tag": _revert_add_tag,
    "remove_tag": _revert_remove_tag,
    "add_to_group": _revert_add_to_group,
    "remove_from_group": _revert_remove_from_group,
    "rotate_item": _revert_rotate_item,
    "set_active_file": _revert_set_active_file,
    "add_link": _revert_add_link,
    "remove_link": _revert_remove_link,
    "add_source": _revert_add_source,
    "add_sources_bulk": _revert_add_sources_bulk,
    "add_tags_bulk": _revert_add_tags_bulk,
    "rename_source": _revert_rename_source,
    "remove_source": _revert_remove_source,
    "split_item": _revert_split_item,
    "merge_item": _revert_merge_item,
    "create_group": _revert_create_group,
    "add_caption": _revert_add_caption,
    "remove_caption": _revert_remove_caption,
    "approve_caption": _revert_approve_caption,
    # An instruction's references are ONE ordered list, so the undo is simply
    # the list as it was.
    "set_caption_refs": _revert_set_caption_refs,
    "approve_tag": _revert_approve_tag,
    # Meta tags on a caption or a tag group, and moving a tag between groups —
    # ordinary edits, so they undo like the rest.
    "add_caption_tag": _revert_add_meta_tag,
    "remove_caption_tag": _revert_remove_meta_tag,
    "add_tag_group_tag": _revert_add_meta_tag,
    "remove_tag_group_tag": _revert_remove_meta_tag,
    # A link's meta tags are the same namespace on a third carrier, so they
    # revert through the same pair (see `_meta_tag_carrier`).
    "add_link_tag": _revert_add_meta_tag,
    "remove_link_tag": _revert_remove_meta_tag,
    "move_tag_group": _revert_move_tag_group,
    "edit_caption": _revert_edit_caption,
    "create_tag": _revert_create_tag,
    # Subjects — the identity side; their tag-side changes revert as tag events.
    "create_subject": _revert_create_subject,
    "delete_subject": _revert_delete_subject,
    "rename_subject": _revert_rename_subject,
    "date_subject": _revert_date_subject,
    "name_subject": _revert_name_subject,
    "create_place": _revert_create_place,
    "delete_place": _revert_delete_place,
    "edit_place": _revert_edit_place,
    "name_place": _revert_name_place,
    "create_event": _revert_create_event,
    "delete_event": _revert_delete_event,
    "edit_event": _revert_edit_event,
    "dismiss_place": _revert_dismiss_place,
    "dismiss_file_place": _revert_dismiss_file_place,
    "dismiss_event": _revert_dismiss_event,
    # Rankings. `delete_ranking` and `delete_ranking_pool` are deliberately
    # absent (NOT_REVERTIBLE — their judgments cascade).
    "create_ranking": _revert_create_ranking,
    "create_ranking_pool": _revert_create_ranking_pool,
    "edit_ranking_pool": _revert_edit_ranking_pool,
    "reorder_ranking_pools": _revert_reorder_ranking_pools,
    "create_tag_set": _revert_create_tag_set,
    "edit_tag_set": _revert_edit_tag_set,
    "set_tag_set_enabled": _revert_set_tag_set_enabled,
    "duplicate_tag_set": _revert_duplicate_tag_set,
    "import_tag_set": _revert_import_tag_set,
    "create_tag_set_category": _revert_create_tag_set_category,
    "edit_tag_set_category": _revert_edit_tag_set_category,
    "move_tag_set_category": _revert_move_tag_set_category,
    "delete_tag_set_category": _revert_delete_tag_set_category,
    "create_tag_set_meta": _revert_create_tag_set_meta,
    "edit_tag_set_meta": _revert_edit_tag_set_meta,
    "delete_tag_set_meta": _revert_delete_tag_set_meta,
    "create_tag_set_entry": _revert_create_tag_set_entry,
    "edit_tag_set_entry": _revert_edit_tag_set_entry,
    "delete_tag_set_entry": _revert_delete_tag_set_entry,
    "set_appearance_box": _revert_set_appearance_box,
    "set_face_outline": _revert_set_face_outline,
    "set_placement_sign": _revert_set_placement_sign,
    "edit_ranking": _revert_edit_ranking,
    "judge_ranking": _revert_judge_ranking,
    "remove_ranking_item": _revert_remove_ranking_item,
    "dismiss_ranking_item": _revert_dismiss_ranking_item,
    "undismiss_ranking_item": _revert_undismiss_ranking_item,
    "name_face": _revert_name_face,
    "name_faces": _revert_name_faces,
    "dismiss_face": _revert_dismiss_face,
    "unname_face": _revert_unname_face,
    "move_face": _revert_move_face,
    "reorder_appearances": _revert_reorder_appearances,
    "reset_face_box": _revert_reset_face_box,
    "set_taken": _revert_set_taken,
    "set_coords": _revert_set_coords,
    # Item-level metadata. Each verb's revert IS the other verb's forward
    # state change, which is what makes the `_REDO` pairing below honest.
    "pin_metadata": _revert_pin_metadata,
    "unpin_metadata": _revert_unpin_metadata,
    "mute_metadata": _revert_mute_metadata,
    "unmute_metadata": _revert_unmute_metadata,
    "add_appearance": _revert_add_appearance,
    "edit_appearance": _revert_edit_appearance,
    "confirm_appearance": _revert_confirm_appearance,
    "remove_appearance": _revert_remove_appearance,
    "clusters_differ": _revert_clusters_differ,
    "merge_faces": _restore_assignments,
    "set_cluster_unnamed": _revert_set_cluster_unnamed,
    "split_faces": _restore_assignments,
    "add_face": _revert_add_face,
    "delete_face": _revert_delete_face,
    # Detected text — the same family of edits as faces, plus the tree.
    "add_text": _revert_add_text,
    "delete_text": _revert_delete_text,
    "edit_text": _revert_edit_text,
    "dismiss_text": _revert_dismiss_text,
    "move_text": _revert_move_text,
    "reorder_text": _revert_reorder_text,
    "add_tag_group_subject": _revert_add_tag_group_subject,
    "remove_tag_group_subject": _revert_remove_tag_group_subject,
    "create_tag_group": _revert_create_tag_group,
    "rename_tag_group": _revert_rename_tag_group,
    "delete_group": _revert_delete_group,
    "delete_tag_group": _revert_delete_tag_group,
    "set_alias": _revert_set_alias,
    "add_tag_implication": _revert_add_tag_implication,
    "remove_tag_implication": _revert_remove_tag_implication,
    "comment_tag": _revert_comment_tag,
    "set_tag_hidden": _revert_set_tag_hidden,
    "describe_tag": _revert_describe_tag,
    "set_tag_category": _revert_set_tag_category,
    "set_hidden_namespaces": _revert_set_hidden_namespaces,
    "set_meta_count": _revert_set_meta_count,
    "rename_tag": _revert_rename_tag,
    "add_group_tag": _revert_add_group_tag,
    "create_meta_tag": _revert_create_meta_tag,
    "rename_meta_tag": _revert_rename_meta_tag,
    "comment_meta_tag": _revert_comment_meta_tag,
    "describe_meta_tag": _revert_describe_meta_tag,
    "delete_meta_tag": _revert_delete_meta_tag,
    "remove_group_tag": _revert_remove_group_tag,
    "delete_tag": _revert_delete_tag,
    # Legacy split hide/unhide events stay revertible; new events use set_hidden.
    "set_hidden": _revert_set_hidden,
    "import": _revert_import,
    "trash_item": _revert_trash_item,
    "restore_item": _revert_restore_item,
    "edit_group": _revert_edit_group,
    "move_group": _revert_move_group,
    "duplicate_group": _revert_duplicate_group,
    "create_sequence": _revert_create_sequence,
    "delete_sequence": _restore_sequence,
    "remove_sequence_members": _restore_sequence,
    "rename_sequence": _revert_rename_sequence,
    "reorder_sequence": _revert_reorder_sequence,
    "set_main_sequence": _revert_set_main_sequence,
    "flip_link": _revert_flip_link,
    "edit_image": _revert_edit_image,
    "add_tag_box": _revert_add_tag_box,
    "edit_tag_box": _revert_edit_tag_box,
    "delete_tag_box": _revert_delete_tag_box,
}


# ---- redo (reverting a revert) --------------------------------------------
#
# Undoing a revert means DOING THE ORIGINAL ACTION AGAIN, and every handler
# above is already "apply this data" — so a redo is one of the same handlers,
# fed the same event data:
#
#   * an add/remove pair redoes through its opposite's handler (redoing an
#     `add_tag` is exactly what reverting a `remove_tag` does), and
#   * a setter redoes through its OWN handler with the before/after keys
#     swapped (every setter event records both sides, which is what makes this
#     work at all).
#
# What is missing from the table is what cannot be redone honestly: an action
# that CREATED or DESTROYED a row (create_tag, create_group, delete_tag,
# split/merge, import, add/remove_source) hands out new ids when replayed, so
# the chain would silently stop matching the log. Those reverts stay final, and
# the UI offers no button for them.

def _swap(a: str, b: str) -> Callable[[dict], dict]:
    """Data with two keys exchanged — a setter's before and after."""
    def mapper(d: dict) -> dict:
        out = dict(d)
        out[a], out[b] = d.get(b), d.get(a)
        return out
    return mapper


def _rotate_redo_payload(d: dict) -> dict:
    """A rotate's redo payload: files swapped AND the turn's sign flipped.

    The revert handler applies ``-delta`` to the in-place case, so a redo —
    which goes through the same handler — must hand it the negated delta or
    the "redo" turns the picture the same way the undo just did.
    """
    out = dict(d)
    out["prev_active_file_id"], out["active_file_id"] = (
        d.get("active_file_id"), d.get("prev_active_file_id"))
    if d.get("delta"):
        out["delta"] = -d["delta"]
    return out


def _swap_many(*names: str) -> Callable[[dict], dict]:
    """The same, for an editor that writes SEVERAL fields in one event.

    Each name is swapped with its ``old_`` twin. Using `_swap` on one field of
    such an event is a quiet bug: the redo restores that field and leaves every
    other one at the value the undo put back — which is what `edit_place` did
    with country, lat and lon for as long as it existed.
    """
    def mapper(d: dict) -> dict:
        out = dict(d)
        for n in names:
            # A NAME NEITHER HALF CARRIES IS LEFT ALONE. Inventing the
            # pair as (None, None) puts a key into the payload that the
            # revert then reads as "this field was empty", which WIPES the
            # field it exists to restore. An optional field — one an event
            # carries only when it changed — is every such name here.
            if n not in d and f"old_{n}" not in d:
                continue
            out[n], out[f"old_{n}"] = d.get(f"old_{n}"), d.get(n)
        return out
    return mapper


def _redo_edit_caption(s: Session, d: dict) -> bool:
    """Re-apply a caption edit: the new text, and the flags the edit itself
    left behind (an edited caption is no longer pending)."""
    c = s.get(Caption, d.get("caption_id"))
    if c is None or "text" not in d:
        return False
    c.text = d["text"]
    if d.get("was_pending") or c.model:
        c.edited = True
    c.pending = False
    return True


def _redo_remove_caption(s: Session, d: dict) -> bool:
    """Re-remove a caption. Matched by item and text, not by id: the revert
    re-created it, and a re-created row is a new id."""
    if d.get("item_id") is None:
        return False
    c = s.execute(select(Caption).where(
        Caption.item_id == d["item_id"], Caption.text == d.get("text", "")
    ).order_by(Caption.position.desc())).scalars().first()
    if c is None:
        return True  # already gone counts as redone
    s.delete(c)
    return True


def _redo_set_hidden(s: Session, d: dict) -> bool:
    return _set_hidden(s, d, bool(d.get("hidden")))


def _redo_approve_tag(s: Session, d: dict) -> bool:
    """Re-approve a pending tag: out of the pending group, no longer pending."""
    item_id, name = d.get("item_id"), d.get("tag")
    if item_id is None or not name:
        return False
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if tag is None:
        return False
    it = s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == tag.id
    )).scalars().first()
    if it is None:
        return False
    for p in s.execute(select(ItemTagPlacement).where(
        ItemTagPlacement.item_tag_id == it.id
    )).scalars().all():
        grp = s.get(ItemTagGroup, p.group_id) if p.group_id else None
        if grp is not None and grp.system:
            p.group_id = None
    it.pending = False
    return True


def _redo_approve_caption(s: Session, d: dict) -> bool:
    c = s.get(Caption, d.get("caption_id"))
    if c is None:
        return False
    c.pending = False
    return True


# action -> (handler, data mapper). See the note above for what is absent.
_REDO: dict[str, tuple[Callable[[Session, dict], bool], Optional[Callable[[dict], dict]]]] = {
    "add_tag": (_revert_remove_tag, None),
    "remove_tag": (_revert_add_tag, None),
    # Each of these four undoes exactly what the other does, so redoing one is
    # reverting its opposite — the `add_tag`/`remove_tag` pairing above.
    "pin_metadata": (_revert_unpin_metadata, None),
    "unpin_metadata": (_revert_pin_metadata, None),
    "mute_metadata": (_revert_unmute_metadata, None),
    "unmute_metadata": (_revert_mute_metadata, None),
    "add_to_group": (_revert_remove_from_group, None),
    "remove_from_group": (_revert_add_to_group, None),
    "add_link": (_revert_remove_link, None),
    "remove_link": (_revert_add_link, None),
    "add_caption": (_revert_remove_caption, None),
    "remove_caption": (_redo_remove_caption, None),
    "set_caption_refs": (_redo_set_caption_refs, None),
    "add_caption_tag": (_revert_remove_meta_tag, None),
    "remove_caption_tag": (_revert_add_meta_tag, None),
    "add_tag_group_tag": (_revert_remove_meta_tag, None),
    "remove_tag_group_tag": (_revert_add_meta_tag, None),
    "add_link_tag": (_revert_remove_meta_tag, None),
    "remove_link_tag": (_revert_add_meta_tag, None),
    # A create and a delete are each other's redo; a rename is its own, with
    # the two names swapped.
    "delete_group": (_redo_delete_group, None),
    "create_tag_group": (_revert_delete_tag_group, None),
    "delete_tag_group": (_revert_create_tag_group, None),
    "rename_tag_group": (_revert_rename_tag_group, _swap("name", "old_name")),
    "add_tag_implication": (_revert_remove_tag_implication, None),
    "remove_tag_implication": (_revert_add_tag_implication, None),
    # Tag sets: a create and a delete are each other's redo, the editors
    # swap their old/new pairs, the switch swaps its two flags.
    "create_tag_set": (_redo_create_tag_set, None),
    "edit_tag_set": (_revert_edit_tag_set,
                     _swap_many("name", "description", "version", "position")),
    "set_tag_set_enabled": (_revert_set_tag_set_enabled,
                            _swap("old_enabled", "enabled")),
    "create_tag_set_category": (_revert_delete_tag_set_category, None),
    "delete_tag_set_category": (_revert_create_tag_set_category, None),
    "edit_tag_set_category": (_revert_edit_tag_set_category,
                              _swap_many("name", "parent_id",
                                         "icon", "hidden", "position")),
    "move_tag_set_category": (_revert_move_tag_set_category,
                              _swap_many("parent_id", "orders")),
    "create_tag_set_meta": (_revert_delete_tag_set_meta, None),
    "delete_tag_set_meta": (_revert_create_tag_set_meta, None),
    "edit_tag_set_meta": (_revert_edit_tag_set_meta,
                          _swap_many("name", "comment", "description")),
    "create_tag_set_entry": (_revert_delete_tag_set_entry, None),
    "delete_tag_set_entry": (_revert_create_tag_set_entry, None),
    "edit_tag_set_entry": (_revert_edit_tag_set_entry,
                           _swap_many("name", "description", "count",
                                      "category_id", "aliases", "implies",
                                      "meta")),
    "trash_item": (_revert_restore_item, None),
    "restore_item": (_revert_trash_item, None),
    "set_hidden": (_redo_set_hidden, None),
    "approve_tag": (_redo_approve_tag, None),
    "approve_caption": (_redo_approve_caption, None),
    "edit_caption": (_redo_edit_caption, None),
    "comment_tag": (_revert_comment_tag, _swap("old_comment", "comment")),
    # A REDO is the same verb the other way: the revert flipped the flag
    # back, so redoing it flips it again — which is the ORIGINAL payload
    # replayed, not a swap of two recorded fields.
    "set_tag_hidden": (_revert_set_tag_hidden,
                       lambda d: {**d, "hidden": not bool(d.get("hidden"))}),
    "set_hidden_namespaces": (_revert_set_hidden_namespaces,
                              _swap("before", "after")),
    "describe_tag": (_revert_describe_tag,
                     _swap("old_description", "description")),
    # A REDO files them again: the same handler, handed a `before` map that
    # sends every tag the event named to the category the event chose.
    "set_tag_category": (
        _revert_set_tag_category,
        lambda d: {"before": {k: d.get("category_id")
                              for k in (d.get("before") or {})}}),
    "set_meta_count": (_revert_set_meta_count,
                       _swap("old_count", "count")),
    "set_coords": (_revert_set_coords, _swap_many("lat", "lon")),
    # Its twin: the event carries `taken_at` and `old_taken_at`, and the
    # revert normalizes whatever it is handed, so a replay is the same swap.
    "set_taken": (_revert_set_taken, _swap_many("taken_at")),
    "rename_tag": (_revert_rename_tag, _swap("old_name", "name")),
    "rename_subject": (_revert_rename_subject, _swap("old_name", "name")),
    "date_subject": (_revert_date_subject, _swap("old_since_date", "since_date")),
    "edit_place": (_revert_edit_place,
                   _swap_many("name", "parent_id", "lat", "lon")),
    "edit_event": (_revert_edit_event,
                   _swap_many("display_name", "parent_id", "start_date",
                              "end_date", "place_ids")),
    # Row-creating, and still redoable: see `_redo_dismiss_place`.
    "dismiss_place": (_redo_dismiss_place, None),
    "dismiss_file_place": (_redo_dismiss_file_place, None),
    "dismiss_event": (_redo_dismiss_event, None),
    # Text setters redo through their own handlers with the sides swapped;
    # add_text/delete_text stay out (a replay hands out new ids).
    "edit_text": (_revert_edit_text, _swap_many("text", "edited")),
    "move_text": (_revert_move_text, _swap_many("box", "quad")),
    "dismiss_text": (_redo_dismiss_text, None),
    "reorder_text": (_revert_reorder_text, _swap("order", "old_order")),
    "add_tag_group_subject": (_revert_remove_tag_group_subject, None),
    "remove_tag_group_subject": (_revert_add_tag_group_subject, None),
    # A group's own fields and its PLACE in the tree are two setters, each
    # redoing through its own handler with the sides swapped. `create_sequence`
    # and `duplicate_group` stay out for the reason above them: replaying one
    # hands out new ids.
    "edit_group": (_redo_edit_group, None),
    "move_group": (_redo_move_group, None),
    "rename_sequence": (_redo_rename_sequence, None),
    "reorder_sequence": (_redo_reorder_sequence, None),
    "set_main_sequence": (_redo_set_main_sequence, None),
    "edit_tag_box": (_redo_edit_tag_box, None),
    # Deleting a tag again is exactly what undoing its creation does, and the
    # payloads agree (both name the tag). The order works out: a batch's
    # per-item removals are redone before the row itself, so by the time this
    # runs the tag is unassigned and `_revert_create_tag`'s guard passes.
    "delete_tag": (_revert_create_tag, None),
    "add_group_tag": (_revert_remove_group_tag, None),
    "rename_meta_tag": (_revert_rename_meta_tag, _swap("old_name", "name")),
    "comment_meta_tag": (_revert_comment_meta_tag, _swap("old_comment", "comment")),
    "describe_meta_tag": (_revert_describe_meta_tag,
                          _swap("old_description", "description")),
    "remove_group_tag": (_revert_add_group_tag, None),
    "set_alias": (_revert_set_alias, _swap("old_alias_of", "new_alias_of")),
    "move_tag_group": (_revert_move_tag_group, _swap("from_group_id", "to_group_id")),
    "rename_source": (_revert_rename_source, _swap("old_name", "new_name")),
    "set_active_file": (_revert_set_active_file,
                        _swap("prev_active_file_id", "new_active_file_id")),
    "rotate_item": (_revert_rotate_item, _rotate_redo_payload),
}


def is_revertible(action: str) -> bool:
    return action in _REVERT


def _origin_of(s: Session, ev: Event, d: dict) -> tuple[Optional[Event], str, str]:
    """For a ``revert`` event: the event it is ultimately about, that event's
    action, and which way this revert went — "undo" (it took the action back) or
    "redo" (it put the action back). Reverts logged before redo existed carry no
    direction and were all undos."""
    origin_id = d.get("origin_event_id", d.get("reverted_event_id"))
    origin = s.get(Event, origin_id) if isinstance(origin_id, int) else None
    action = d.get("origin_action") or d.get("reverted_action") or ""
    return origin, action, d.get("replay") or "undo"


def _replay(s: Session, ev: Event, d: dict) -> Optional[str]:
    """Undo a revert by doing the OPPOSITE of what it did to its original
    event: a revert that undid the action re-applies it, one that re-applied it
    undoes it again. Returns the direction the new revert went, or None when it
    could not be done (the log is then left untouched)."""
    origin, action, went = _origin_of(s, ev, d)
    payload = load_data(origin) if origin is not None else {}
    if not payload:
        return None
    if went == "undo":
        entry = _REDO.get(action)
        if entry is None:
            return None
        handler, mapper = entry
        payload_out, direction = (mapper(payload) if mapper else payload), "redo"
    else:
        handler = _REVERT.get(action)  # type: ignore[assignment]
        if handler is None:
            return None
        payload_out, direction = payload, "undo"
    if not handler(s, payload_out):
        return None
    # The original event is reverted exactly while the last word was an undo.
    if origin is not None:
        origin.reverted_at = _now() if direction == "undo" else None
    return direction


def can_revert(s: Session, ev: Event) -> bool:
    """Whether this event offers a Revert button: not already reverted, and
    either an invertible action or a revert that can be replayed the other way."""
    if ev.reverted_at is not None:
        return False
    if ev.action in ("delete_group", "import_tag_set"):
        # The TWO actions whose revertibility is a fact about the EVENT rather
        # than about the action: a deletion (or an import) too large to
        # snapshot carries no `undo` block (see `ops/groups.UNDO_MEMBERS_MAX`
        # and `ops/tagsets.UNDO_ENTRIES_MAX`), and offering a button that
        # would bring the groups back empty is worse than not offering one.
        return isinstance(load_data(ev).get("undo"), dict)
    if ev.action != "revert":
        return ev.action in _REVERT
    _, action, went = _origin_of(s, ev, load_data(ev))
    return action in (_REDO if went == "undo" else _REVERT)


def revert_event(s: Session, ev: Event, *, source: str = "web",
                 store=None) -> Event | None:
    """Undo one event if possible; mark it reverted and return the event that
    records the reversal (None if it could not be undone).

    On success a new ``revert`` event is appended to the log so the reversal is
    itself recorded — and that one is revertible in turn, which is how a revert
    can be taken back. Each step flips which way the original action stands, so
    the chain can be walked as far as anyone likes. RETURNING that event is
    what lets a caller offer a Redo: reverting it replays the original.

    ``store`` is the library's ItemStore, for the one revert that has to
    rewrite pixels (an in-place rotate). It rides on ``session.info`` the way
    the username does, so the ~80 handlers keep their (session, data)
    signature; a caller that passes none simply cannot revert that case."""
    if store is not None:
        s.info["revert_store"] = store
    if ev.reverted_at is not None:
        return None
    d = load_data(ev)
    chain: dict = {}
    if ev.action == "revert":
        direction = _replay(s, ev, d)
        if direction is None:
            return None
        origin_id = d.get("origin_event_id", d.get("reverted_event_id"))
        chain = {
            "origin_event_id": origin_id,
            "origin_action": d.get("origin_action") or d.get("reverted_action") or "",
            "replay": direction,
        }
    else:
        handler = _REVERT.get(ev.action)
        if handler is None:
            return None
        if not handler(s, d):
            return None
        chain = {"origin_event_id": ev.id, "origin_action": ev.action, "replay": "undo"}
    ev.reverted_at = _now()
    return log_event(
        s, source=source, action="revert",
        entity_type=ev.entity_type or "", entity_id=ev.entity_id,
        # The inner sentence rides as a NESTED template var (its own key and
        # vars, plus the filled text): the English summary stays byte-for-byte
        # `f"Reverted: {ev.summary}"`, while a translated History view can
        # translate BOTH halves — without this every reverted entry read
        # half-translated.
        summary="Reverted: {summary}" if ev.summary else "Reverted a change",
        summary_vars=({"summary": {
            "key": ev.summary_key or ev.summary,
            "vars": (json.loads(ev.summary_vars)
                     if ev.summary_vars else {}),
            "text": ev.summary,
        }} if ev.summary else None),
        # `reverted_*` name the event this one struck through; `origin_*` and
        # `replay` name the action being replayed and which way it now stands,
        # which is what the next revert in the chain needs.
        data={"reverted_event_id": ev.id, "reverted_action": ev.action, **chain},
    )
