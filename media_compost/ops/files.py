"""A file version of an item: its recorded SOURCES, splitting it out, deleting it.

A "source" (`FileName`) is where the bytes came from — a filename with its
relative import path, or a web URL with the time it was fetched. One stored
file may carry several: the same picture found at a second address is one file
with two sources, which is exactly what makes re-importing a duplicate worth
recording rather than skipping silently.

The uniqueness rules differ between the two and that is deliberate: a filename
is unique per (file, name), a URL per (file, name, accessed_at) — re-fetching
the same URL later is a new sighting, re-importing the same download is not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy import and_, case, delete as sql_delete, func, or_, select, true

from ..db import (
    File, FileArtifact, FileName, Item, Relationship, chunked,
    copy_item_associations, touch_items,
)
from . import actions
from .context import Ctx
from .errors import Invalid, NotFound


def _item_id_of(s, file_id: int) -> Optional[int]:
    f = s.get(File, file_id)
    return f.item_id if f is not None else None




def rename_source(ctx: Ctx, file_id: int, name_id: int, name: str) -> None:
    s = ctx.session
    """Rename one of a source file's source infos (a filename or a URL)."""
    fn = s.get(FileName, name_id)
    if fn is None or fn.file_id != file_id:
        raise NotFound("source name not found")
    new = name.strip()
    if not new:
        raise Invalid("name cannot be empty")
    if new != fn.name:
        # Same uniqueness rule as adding: a URL row only conflicts with another
        # row carrying the same name AND the same access time; a filename row
        # conflicts with any same-named row.
        clashes = s.execute(
            select(FileName).where(
                FileName.file_id == file_id, FileName.name == new,
                FileName.id != name_id,
            )
        ).scalars().all()
        if any(
            (not fn.is_url) or e.accessed_at == fn.accessed_at for e in clashes
        ):
            raise Invalid("that name already exists on this file")
    old = fn.name
    fn.name = new
    # A source-info edit is a revertible history change.
    ctx.log(
        action=actions.RENAME_SOURCE, entity_type="item",
        entity_id=_item_id_of(s, file_id), summary="Edited a source",
        data={"file_id": file_id, "name_id": name_id, "old_name": old, "new_name": new},
    )




def remove_source(ctx: Ctx, file_id: int, name_id: int) -> None:
    s = ctx.session
    """Remove one of a source file's source infos. The stored file itself is
    untouched — only the recorded source is dropped."""
    fn = s.get(FileName, name_id)
    if fn is None or fn.file_id != file_id:
        raise NotFound("source name not found")
    # Capture it so the removal can be reverted (re-added) from the History.
    ctx.log(
        action=actions.REMOVE_SOURCE, entity_type="item",
        entity_id=_item_id_of(s, file_id), summary="Removed a source",
        data={"file_id": file_id, "name": fn.name, "is_url": bool(fn.is_url),
              "accessed_at": fn.accessed_at.isoformat() if fn.accessed_at else None},
    )
    s.delete(fn)




def add_source(ctx: Ctx, file_id: int, *, name: Optional[str] = None,
               url: Optional[str] = None,
               accessed_at: Optional[str] = None,
               exist_ok: bool = False) -> FileName:
    s = ctx.session
    """Add a source to a file: either a filename+path or a web URL (which records
    an access date/time). Stored as a FileName row shown in the Source list.

    ``exist_ok`` returns the existing row instead of refusing — the crawler
    pattern, where re-recording the same fetch must be a no-op (the Source
    list's own form keeps the refusal, which is the answer a person wants).
    """
    from datetime import datetime, timezone

    f = s.get(File, file_id)
    if f is None:
        raise NotFound("file not found")
    acc = None
    is_url = False
    if url and url.strip():
        name = url.strip()
        is_url = True
        # The access date/time is optional for a URL source.
        raw = (accessed_at or "").strip()
        if raw:
            try:
                acc = datetime.fromisoformat(raw)
            except ValueError:
                raise Invalid("invalid access date/time")
            # Every datetime column here holds a NAIVE UTC wall clock, and
            # SQLite's DATETIME just formats the fields it is given — an
            # offset-aware time passed through would be stored hours off the
            # fetch it records. (This rule lived in the importer while the
            # import call recorded URLs itself; the provenance moved here
            # with it.)
            if acc.tzinfo is not None:
                acc = acc.astimezone(timezone.utc).replace(tzinfo=None)
    elif name and name.strip():
        name = name.strip()
    else:
        raise Invalid("provide a filename or a URL")
    # A filename source is unique per (file, name); a URL source is unique per
    # (file, name, accessed_at) — the same URL may be recorded again with a
    # *different* access time (e.g. re-downloaded later).
    existing = s.execute(
        select(FileName).where(FileName.file_id == file_id, FileName.name == name)
    ).scalars().all()
    if is_url:
        dup = next((e for e in existing if e.accessed_at == acc), None)
        if dup is not None:
            if exist_ok:
                return dup
            raise Invalid("that source already exists on this file")
    elif existing:
        if exist_ok:
            return existing[0]
        raise Invalid("that source already exists on this file")
    fn = FileName(file_id=file_id, name=name, is_url=is_url, accessed_at=acc)
    s.add(fn)
    s.flush()
    # A newly added source is a revertible history change.
    ctx.log(
        action=actions.ADD_SOURCE, entity_type="item",
        entity_id=f.item_id, summary="Added a source",
        data={"file_id": file_id, "name_id": fn.id, "name": name,
              "is_url": is_url, "accessed_at": acc.isoformat() if acc else None},
    )
    return fn




def _naive_utc(when) -> "Optional[object]":
    """An access time as the naive UTC wall clock every datetime column
    holds. Accepts a `datetime` or an ISO string; an offset-aware value is
    converted — an offset passed through would record the fetch hours off.
    An unreadable string answers None rather than failing a batch."""
    from datetime import datetime, timezone

    if when is None or when == "":
        return None
    if isinstance(when, str):
        try:
            when = datetime.fromisoformat(when)
        except ValueError:
            return None
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    return when


def add_urls_bulk(ctx: Ctx, rows) -> int:
    """Record many web-URL sources in ONE pass — the crawl batch.

    ``rows`` is (file_id, url, accessed_at) triples; `add_source`'s rules
    apply to each — idempotent per (file, url, access time), an offset-aware
    time stored as the UTC moment it names — but the writes are chunked
    selects and one insert set rather than an ops round-trip per file, which
    a crawl pays tens of thousands of times. A file that no longer exists is
    skipped (the batch may lag the import that named it). ONE revertible
    event for the whole batch; returns how many rows were new.
    """
    from ..db import File as FileRow, chunked

    s = ctx.session
    want: dict[tuple, None] = {}
    for fid, url, when in rows:
        url = (url or "").strip()
        if fid and url:
            want.setdefault((int(fid), url, _naive_utc(when)))
    if not want:
        return 0
    fids = sorted({fid for fid, _u, _w in want})
    alive: set[int] = set()
    have: set[tuple] = set()
    for chunk in chunked(fids):
        alive.update(s.execute(
            select(FileRow.id).where(FileRow.id.in_(chunk))).scalars())
        have.update(
            (r.file_id, r.name, r.accessed_at)
            for r in s.execute(
                select(FileName).where(FileName.file_id.in_(chunk),
                                       FileName.is_url.is_(True))
            ).scalars())
    fresh = [FileName(file_id=fid, name=url, is_url=True, accessed_at=acc)
             for fid, url, acc in want
             if fid in alive and (fid, url, acc) not in have]
    if not fresh:
        return 0
    s.add_all(fresh)
    s.flush()
    ctx.log(
        action=actions.ADD_SOURCES_BULK, entity_type="items",
        summary="Recorded {urls} web sources",
        summary_vars={"urls": len(fresh)},
        data={"created": [
            [fn.id, fn.file_id, fn.name,
             fn.accessed_at.isoformat() if fn.accessed_at else None]
            for fn in fresh]},
    )
    return len(fresh)


def split(ctx: Ctx, file_id: int) -> int:
    """Split one file version out into its own new image entry."""
    return split_files(ctx, [file_id])


def split_files(ctx: Ctx, file_ids: Sequence[int]) -> int:
    s = ctx.session
    """Split one or more file versions of an item out into ONE new image entry.

    Useful when the deduper grouped genuinely different images as versions of
    one item. The files are moved to a fresh item that inherits the original's
    group memberships, tags and captions; the original keeps its remaining
    files. Refuses to split an item's only file, or every file it has (there'd
    be nothing to split them from), and refuses a set spanning two items.

    SEVERAL FILES LEAVE AS ONE ITEM, AND KEEP THEIR LINEAGE AMONG THEMSELVES.
    Numbering restarts at #1 in the order the files were numbered here, so a
    ``based_on`` or an ``edit_chain`` step naming the OLD item's numbers would
    now point at whichever file happens to have taken that number. It is
    remapped where the whole reference moved along (splitting a picture
    together with the edits made from it is the case this exists for), and
    cleared where any part of it stayed behind — a lineage with a hole in it
    reads as a claim about files that are no longer there.
    """
    ids = list(dict.fromkeys(file_ids))
    if not ids:
        raise Invalid("no files to split")
    moving = [s.get(File, fid) for fid in ids]
    if any(f is None for f in moving):
        raise NotFound("file not found")
    item_ids = {f.item_id for f in moving}
    if len(item_ids) > 1:
        raise Invalid("cannot split files of different items into one item")
    old_item = s.get(Item, moving[0].item_id)
    old_active_before = old_item.active_file_id if old_item is not None else None
    siblings = s.execute(
        select(File).where(File.item_id == moving[0].item_id)
    ).scalars().all()
    if len(siblings) <= 1:
        raise Invalid("cannot split an item's only file")
    if len(ids) >= len(siblings):
        raise Invalid("cannot split every file of an item")
    # In the order they were numbered here, so the new #1, #2 … read the same
    # way round as they did before the move.
    moving.sort(key=lambda f: (f.number if f.number is not None else 0, f.id))

    # Name the new item after the first moved file's source filename, falling
    # back to a format label when none was recorded.
    src_name = s.execute(
        select(FileName.name).where(FileName.file_id == moving[0].id)
        .order_by(FileName.id)
    ).scalars().first()
    name = (src_name.rsplit("/", 1)[-1] if src_name
            else f"{moving[0].format.upper()} {moving[0].width}×{moving[0].height}")

    new_item = Item(name=name)
    s.add(new_item)
    s.flush()

    # Old number -> new number, for the lineage remap below. Built before
    # anything is renumbered, since both halves of a step may be moving.
    renum = {f.number: i for i, f in enumerate(moving, start=1)
             if f.number is not None}
    moved_ids = {f.id for f in moving}

    # WHAT EACH FILE LOOKED LIKE HERE, so the revert can put it back exactly
    # (`history._revert_split_item`). Every field below is one the loop is
    # about to overwrite and nothing else records: the number names the file
    # ON DISK, and a revert that moved the rows back without it left the file
    # carrying the new item's number on the old item — a collision with a
    # number already there, and bytes still sitting in the split-off item's
    # folder. The artifacts need no entry: their path is derived from the
    # file's number, kind and model, so restoring the number reproduces it.
    before = [
        {
            "id": f.id,
            **({"number": f.number} if f.number is not None else {}),
            **({"path": f.path} if f.path else {}),
            **({"edit_chain": f.edit_chain} if f.edit_chain else {}),
            **({"based_on_file_id": f.derived_from_file_id}
               if f.derived_from_file_id is not None else {}),
        }
        for f in moving
    ]

    for new_number, f in enumerate(moving, start=1):
        was_derived = bool(f.is_derived)
        # Move the bytes (and the file's artifacts) into the new item's folder.
        if old_item is not None and f.path:
            ext = f.path.rsplit(".", 1)[-1] if "." in f.path else (f.format or "bin")
            _dst, new_rel = ctx.store.file_target(new_item.uid, new_number, ext)
            ctx.store.move_file(old_item.uid, new_item.uid, f.path, new_rel)
            f.path = new_rel
        for art in s.execute(
            select(FileArtifact).where(FileArtifact.file_id == f.id)
        ).scalars().all():
            if old_item is not None and art.path:
                aext = art.path.rsplit(".", 1)[-1] if "." in art.path else "png"
                data = ctx.store.file_path(old_item.uid, art.path).read_bytes()
                new_arel = ctx.store.write_artifact(
                    new_item.uid, new_number, art.kind, aext, data, art.model
                )
                ctx.store.remove_file(old_item.uid, art.path)
                art.path = new_arel
            art.item_id = new_item.id
        f.item_id = new_item.id
        f.number = new_number
        f.edit_chain = _remapped_chain(f.edit_chain, renum)
        if f.derived_from_file_id not in moved_ids:
            f.derived_from_file_id = None

        # Always link the split-off image back to the item it came from. An
        # edited/derived file keeps the original->derived "edit" relationship
        # (with its transform); any other split gets a plain manual link. One
        # link per moved file would say the same thing several times, so only
        # the first writes one — the item is what is being linked, not the file.
        if old_item is not None and new_number == 1:
            if was_derived:
                s.add(Relationship(
                    from_item_id=old_item.id, to_item_id=new_item.id, kind="edit",
                    meta=json.dumps({"transform": "user"}),
                ))
            else:
                s.add(Relationship(
                    from_item_id=old_item.id, to_item_id=new_item.id, kind="manual",
                    meta="",
                ))

    # The file that was active here stays active there; otherwise the largest.
    new_item.active_file_id = (
        old_active_before if old_active_before in moved_ids
        else max(moving, key=lambda x: x.width * x.height).id
    )

    # The split-off image inherits the original's groups, tags and captions so it
    # stays in view and keeps its organization.
    if old_item is not None:
        copy_item_associations(s, old_item.id, new_item.id)
        # If we moved the active file, promote the largest that remains.
        if old_item.active_file_id in moved_ids:
            remaining = [x for x in siblings if x.id not in moved_ids]
            old_item.active_file_id = max(
                remaining, key=lambda x: x.width * x.height
            ).id
    ctx.log(
        action=actions.SPLIT_ITEM, entity_type="item",
        entity_id=new_item.id,
        summary=("Split {name} into its own item" if len(moving) == 1
                 else "Split {n} files into their own item"),
        summary_vars=({"name": name} if len(moving) == 1
                      else {"n": len(moving)}),
        data={
            # `files` is the record: the ids AND what each looked like here.
            # `file_id` rides along for a split of one because that is the key
            # every split logged before this one wrote, and the History tab and
            # any stored event still speak it; the revert prefers `files` and
            # falls back to it (see `history._revert_split_item`).
            "files": before,
            **({"file_id": moving[0].id} if len(moving) == 1
               else {"file_ids": [f.id for f in moving]}),
            "new_item_id": new_item.id,
            "old_item_id": old_item.id if old_item is not None else None,
            "old_active_before": old_active_before,
        },
    )
    touch_items(s, [old_item.id] if old_item is not None else [])
    return new_item.id


def _remapped_chain(chain: str, renum: dict[int, int]) -> str:
    """An edit chain in the new item's numbering, or empty where it cannot be.

    Every step's endpoints must name files that moved along; one that does not
    means the chain refers to a file left behind, and a number that means a
    different file in the new item is worse than no lineage at all.
    """
    if not chain:
        return ""
    try:
        steps = json.loads(chain)
    except (TypeError, ValueError):
        return ""
    if not isinstance(steps, list):
        return ""
    out = []
    for step in steps:
        if not isinstance(step, dict):
            return ""
        a, b = step.get("from"), step.get("to")
        if a not in renum or b not in renum:
            return ""
        out.append({**step, "from": renum[a], "to": renum[b]})
    return json.dumps(out)


def delete_file(ctx: Ctx, file_id: int) -> bool:
    s = ctx.session
    """Remove one file version of an item, along with its bytes, its artifacts
    and its thumbnail.

    Refuses to delete an item's last remaining file. If the deleted file was the
    active one, the largest remaining version becomes active.
    """
    f = s.get(File, file_id)
    if not f:
        raise NotFound("file not found")
    siblings = s.execute(
        select(File).where(File.item_id == f.item_id)
    ).scalars().all()
    if len(siblings) <= 1:
        raise Invalid("cannot delete an item's only file")

    item = s.get(Item, f.item_id)
    if item is not None and item.active_file_id == f.id:
        remaining = [x for x in siblings if x.id != f.id]
        item.active_file_id = max(remaining, key=lambda x: x.width * x.height).id

    # Re-parent any files derived from this one to *its* parent, so a deleted
    # middle of an edit chain (e.g. #3←#2←#1) becomes #3←#1 rather than an
    # orphan. The children's ``edit_chain`` already records the full history
    # (including the removed step), so the action list survives.
    for child in siblings:
        if child.id != f.id and child.derived_from_file_id == f.id:
            child.derived_from_file_id = f.derived_from_file_id

    ctx.store.drop_thumb(f.id)
    if item is not None:
        if f.path:
            ctx.store.remove_file(item.uid, f.path)
        if f.number:
            ctx.store.remove_artifacts_for(item.uid, f.number)
    number = f.number
    s.delete(f)   # cascades FileName + FileArtifact rows
    s.flush()
    if item is not None:
        # Irreversible (the bytes are gone), so not revertible — but its
        # siblings (split, rotate, source add/rename/remove) all log, and a
        # file version vanishing with no trace read as data loss.
        ctx.log(action=actions.DELETE_FILE, entity_type="item",
                entity_id=item.id,
                summary="Deleted file #{number} of “{name}”",
                summary_vars={"number": number, "name": item.name},
                data={"item_id": item.id, "file_id": file_id,
                      "number": number})
    touch_items(s, [item.id] if item is not None else [])
    return True


# ---- pruning by rule --------------------------------------------------------
#
# THE UNIT IS A RULE OVER EVERY FILE OF EVERY ITEM, not a file and not an
# item. Settings → Storage answers "why is this library 200 GB", and the
# answer is often a shape rather than a list: a folder imported at four sizes,
# a crawl that kept every thumbnail beside the picture it is a thumbnail of.
# Nothing in the app could act on that — the Sources list deletes one file at
# a time, and the grid selects ITEMS, which is the wrong unit entirely.
#
# The rule is a MATCHER with GUARDS. The thresholds say which files are small
# enough to go; `keep_active` / `keep_edited` say which are spared whatever
# their size. Both thresholds are MINIMUMS, so a file must clear every one
# that is set — the removal side is therefore an OR, and setting both is
# strictly more aggressive than setting either.


@dataclass(frozen=True)
class PruneRule:
    """Which files a prune removes.

    ``min_megapixels``, ``min_short_edge`` and ``min_long_edge`` are the
    matcher; a file below ANY of them is matched. ``keep_active`` and
    ``keep_edited`` are guards over whatever the matcher found.

    The two edge thresholds ask different questions and neither implies the
    other: the SHORT edge is about a thumbnail (small however it is shaped),
    the LONG edge about a picture that is small in the direction it is widest
    — a 2000x80 banner clears a 100 px short edge and fails nothing else, and
    a 300x300 crop clears a 200 px long edge while a 4000x150 strip does not.

    A file whose dimensions are unknown (a stored video that never probed, an
    audio-only stream) is NEVER matched by a size threshold: the rule cannot
    say whether it is small, and the safe direction for an irreversible delete
    is to leave it alone.
    """

    keep_active: bool = True
    keep_edited: bool = True
    min_megapixels: float = 0.0
    min_short_edge: int = 0
    min_long_edge: int = 0
    #: "" for every kind, else the `Item.kind` this rule is confined to
    #: ("image" or "video"). A SCOPE rather than a matcher: it narrows what
    #: the thresholds and guards are asked about instead of being another
    #: reason to remove a file, so it is ANDed with the whole condition.
    #: A sequence CONTAINER owns no file of its own and so is reached by
    #: neither, whatever this says.
    kind: str = ""

    @property
    def has_threshold(self) -> bool:
        return (self.min_megapixels > 0 or self.min_short_edge > 0
                or self.min_long_edge > 0)


def _prune_condition(rule: PruneRule):
    """The SQL for "this file goes", over a ``File`` joined to its ``Item``.

    NO threshold and NO guard is the whole library, and it is ALLOWED. It was
    refused here for a while, on the reasoning that a rule meaning everything
    is one nobody types on purpose — but it is a real thing to want ("start
    this library over, keep the groups and the tags"), the refusal made an
    empty form the one state the page could not preview, and it put the ops
    layer in the business of second-guessing a rule the caller had already
    confirmed. What guards it is what guards every other rule: the preview
    says how many files and how many ITEMS go, and the dialog spells that out
    again before anything runs.
    """
    matched = []
    if rule.min_megapixels > 0:
        matched.append(File.width * File.height
                       < int(round(rule.min_megapixels * 1_000_000)))
    if rule.min_short_edge > 0:
        # SQLite's two-argument `min()` is the scalar one, but spelling it
        # with `func.min` is one rename away from reading as the AGGREGATE in
        # a grouped statement — and this condition is used inside one.
        matched.append(
            case((File.width < File.height, File.width), else_=File.height)
            < int(rule.min_short_edge))
    if rule.min_long_edge > 0:
        matched.append(
            case((File.width > File.height, File.width), else_=File.height)
            < int(rule.min_long_edge))
    # Only where the file HAS dimensions: 0x0 is "nobody measured", not small.
    remove = (and_(File.width > 0, File.height > 0, or_(*matched))
              if matched else true())

    guards = []
    if rule.keep_active:
        # `!= ` alone would answer NULL — and therefore "no" — for an item
        # with no active file, which is the one item whose files are all
        # equally droppable.
        guards.append(or_(Item.active_file_id.is_(None),
                          Item.active_file_id != File.id))
    if rule.keep_edited:
        guards.append(File.is_derived.is_(False))
    if rule.kind:
        guards.append(Item.kind == rule.kind)
    return and_(remove, *guards)


def prune_preview(s, rule: PruneRule) -> tuple[int, int, int]:
    """``(files, bytes, items)`` a prune under ``rule`` would remove.

    Answered in TWO statements over the whole library rather than by listing
    the matches: the rule is written to be run against a hundred thousand
    files, and the page shows it live as the numbers are typed.

    ``items`` is how many would be left with no file at all, which is what
    makes this preview worth having — it is the number that says a rule aimed
    at duplicates is about to delete pictures. A sequence CONTAINER owns no
    files, so it never appears in the grouped statement and is never counted:
    the group is over files, and an item with none has no row in it.
    """
    cond = _prune_condition(rule)
    hit = case((cond, 1), else_=0)
    per_item = (
        select(File.item_id.label("iid"),
               func.count(File.id).label("total"),
               func.sum(hit).label("hits"))
        .join(Item, Item.id == File.item_id)
        .group_by(File.item_id)
        .having(func.sum(hit) > 0)
        .subquery()
    )
    files, items = s.execute(
        select(func.coalesce(func.sum(per_item.c.hits), 0),
               func.coalesce(
                   func.sum(case((per_item.c.hits >= per_item.c.total, 1),
                                 else_=0)), 0))
    ).one()
    # The bytes the disk actually gives back: a file's own, plus the artifacts
    # that hang off it and go with it. Two statements rather than a correlated
    # subquery inside the group above, which is the same answer at several
    # times the cost.
    own = s.execute(
        select(func.coalesce(func.sum(File.bytes), 0))
        .join(Item, Item.id == File.item_id).where(cond)
    ).scalar_one()
    derived = s.execute(
        select(func.coalesce(func.sum(FileArtifact.bytes), 0))
        .join(File, File.id == FileArtifact.file_id)
        .join(Item, Item.id == File.item_id).where(cond)
    ).scalar_one()
    return int(files or 0), int(own or 0) + int(derived or 0), int(items or 0)


def prune(ctx: Ctx, rule: PruneRule, *,
          limit: int = 500) -> tuple[int, int, int, bool]:
    """Remove one BATCH of the files ``rule`` matches.

    Answers ``(files, bytes, items, more)``. Batched for the reason
    `ops.artifacts.delete_kind` is: the transaction belongs to the caller, and
    one transaction around a hundred thousand deletions is a long-held write
    lock and a rollback nobody wanted. `more` is how the caller knows to come
    round again.

    An item left with NO file is deleted outright rather than trashed. Its
    bytes are already gone, so a trashed copy of it could only be restored
    into a picture that no longer exists — which is a worse answer than
    saying plainly that the item went with its last file.
    """
    from . import items as ops_items

    s = ctx.session
    cond = _prune_condition(rule)
    rows = list(s.execute(
        select(File).join(Item, Item.id == File.item_id).where(cond)
        .order_by(File.id).limit(limit + 1)
    ).scalars().all())
    more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return 0, 0, 0, False

    doomed = {f.id for f in rows}
    item_ids = {f.item_id for f in rows}
    items = {i.id: i for i in s.execute(
        select(Item).where(Item.id.in_(item_ids))).scalars().all()}
    # Every surviving file of every touched item, in ONE query: the active
    # file may have to be re-chosen and a derived file re-parented, and both
    # are per-item questions asked of a batch.
    siblings: dict[int, list[File]] = {}
    for f in s.execute(
        select(File).where(File.item_id.in_(item_ids))
    ).scalars().all():
        siblings.setdefault(f.item_id, []).append(f)

    freed = int(s.execute(
        select(func.coalesce(func.sum(FileArtifact.bytes), 0))
        .where(FileArtifact.file_id.in_(doomed))
    ).scalar_one() or 0)

    def _surviving_parent(fid: Optional[int]) -> Optional[int]:
        """The nearest ancestor this batch is not deleting.

        `delete_file` re-parents one level because it deletes one file; a
        batch can take a whole stretch of an edit chain at once, so the walk
        has to keep going. The chain is short and acyclic (a file is derived
        from an older one), and the seen-set is the belt to that brace.
        """
        seen = set()
        while fid in doomed and fid not in seen:
            seen.add(fid)
            parent = s.get(File, fid)
            fid = parent.derived_from_file_id if parent is not None else None
        return fid

    for f in rows:
        item = items.get(f.item_id)
        freed += int(f.bytes or 0)
        ctx.store.drop_thumb(f.id)
        if item is not None:
            if f.path:
                ctx.store.remove_file(item.uid, f.path)
            if f.number:
                ctx.store.remove_artifacts_for(item.uid, f.number)
            ctx.log(action=actions.DELETE_FILE, entity_type="item",
                    entity_id=item.id,
                    summary="Deleted file #{number} of “{name}”",
                    summary_vars={"number": f.number, "name": item.name},
                    data={"item_id": item.id, "file_id": f.id,
                          "number": f.number, "prune": True})

    emptied: list[int] = []
    for iid, item in items.items():
        left = [f for f in siblings.get(iid, []) if f.id not in doomed]
        if not left:
            emptied.append(iid)
            continue
        for f in left:
            if f.derived_from_file_id in doomed:
                f.derived_from_file_id = _surviving_parent(
                    f.derived_from_file_id)
        if item.active_file_id in doomed:
            item.active_file_id = max(
                left, key=lambda x: (x.width or 0) * (x.height or 0)).id

    # ONE statement per chunk, and the database does the cascading — the
    # `delete_items` reasoning one level down, for the same reason: every FK
    # at `files` is ON DELETE CASCADE or SET NULL, so the ORM's per-row walk
    # (load this file's names, its artifacts, its metadata, then a DELETE
    # each) was work SQLite does in C. The flush FIRST, because the loop
    # above re-pointed surviving files and active-file ids through the ORM
    # and those updates must land while the rows they reference still exist.
    s.flush()
    for chunk in chunked(list(doomed)):
        s.execute(sql_delete(File).where(File.id.in_(chunk)))
    # The identity map would go on handing out rows the database no longer
    # has (`expire_on_commit=False`), and `siblings` holds these objects.
    for f in rows:
        s.expunge(f)
    touch_items(s, item_ids - set(emptied))
    if emptied:
        # `delete_items` writes its own per-item event and takes the folder
        # (now holding nothing but a sidecar) with it.
        ops_items.delete_items(ctx, emptied)
    return len(rows), freed, len(emptied), more


def forget_chosen_thumbs(ctx: Ctx) -> int:
    """Move the thumbnail token of every file whose thumbnail was CHOSEN.

    A film's picked frame ("use this frame as the thumbnail") lives only in
    the thumbnail cache: `ops/video.set_thumb_frame` writes the picture and
    bumps `File.thumb_rev`, and nothing records which frame. So when the
    Storage page clears that cache, the thumbnail generated next is the
    default one — and it would be served under the SAME ETag and URL token
    as the picked one (both read `thumb_rev`), so a browser that has the
    picked frame goes on showing it. Moving the counter says the picture
    changed. Answers how many files it touched.

    Deliberately unlogged: the thumbnail is a derived cache and the counter
    is its version, not something anybody set (the frame pick logs nothing
    either).
    """
    res = ctx.session.execute(
        File.__table__.update()
        .where(File.thumb_rev > 0)
        .values(thumb_rev=File.thumb_rev + 1))
    return int(res.rowcount or 0)

