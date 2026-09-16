"""The metadata index: what each FILE says about itself, and what the ITEM
therefore answers for ``INFO:``.

Three tables, one meaning each — :class:`db.FileMetadata` is a file's own
answers, :class:`db.ItemMetaPin` is a value somebody promoted to the item,
:class:`db.ItemMetaMute` takes one of the active file's answers away — and
:class:`db.ItemMetadata` is derived from the last two. Search reads the UNION of
``item_metadata`` and ``item_meta_pins``, which is the whole of "only item-level
metadata and the active file's metadata are searched".

Its own module rather than a corner of :mod:`media_compost.importer`, where the
first of these functions started: ``fileops`` has to write per-file metadata
too, and ``importer`` already imports ``fileops`` — so the honest shape is a
module below both. It imports ``db``, ``media`` and ``storage`` and nothing
else.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import media
from .db import File, FileMetadata, Item, ItemMetaMute, ItemMetadata
from .storage import ItemStore


def effective_nums(session: Session, item_ids, name: str) -> dict[int, float]:
    """The ONE number each item answers with for ``name``, pin first.

    Search matches ANY of an item's values for a name — a pin sits beside the
    active file's answer rather than replacing it — but three readers need a
    single answer rather than a set: the capture-date walk's EXIF step
    (``searchctx.load_taken_windows``), ``ops.items.taken_of``'s fallback, and
    the event-date suggestion. "The pin, else the active file" is that rule and
    it is written once, here, so those three cannot drift.

    A pin with several values for one name answers with the lowest, which is
    arbitrary and says so: pinning two capture dates is not a question this
    library can answer, and picking deterministically beats picking by rowid.
    """
    ids = list(item_ids)
    out: dict[int, float] = {}
    if not ids:
        return out
    from .db import ItemMetaPin, chunked

    # The active file's answers first, then the pins OVER them: reading the two
    # in that order is the precedence, so there is no rule to state twice.
    # Descending, so the plain dict write leaves the lowest value standing.
    for table in (ItemMetadata, ItemMetaPin):
        for chunk in chunked(ids):
            for iid, value in session.execute(
                select(table.item_id, table.num_value)
                .where(table.item_id.in_(chunk), table.name == name,
                       table.num_value.is_not(None))
                .order_by(table.num_value.desc())
            ).all():
                out[iid] = float(value)
    return out


def effective_num(session: Session, item_id: int, name: str):
    """``effective_nums`` for one item. See it for the precedence rule."""
    return effective_nums(session, [item_id], name).get(item_id)


def effective_text(session: Session, item_id: int, name: str):
    """The ONE text an item answers with for ``name`` — `effective_nums`'
    precedence (the pin, else the active file), for the text-valued names.
    Written for the file-place suggestion's read of ``location``."""
    from .db import ItemMetaPin

    out = None
    for table in (ItemMetadata, ItemMetaPin):
        for (value,) in session.execute(
            select(table.text_value)
            .where(table.item_id == item_id, table.name == name,
                   table.text_value.is_not(None))
            .order_by(table.text_value.desc())
        ).all():
            out = str(value)  # like effective_nums: the lowest value stands
    return out


def index_file_metadata(session: Session, store: ItemStore, file: File, *,
                        values: "list[media.MetaValue] | None" = None,
                        fresh: bool = False) -> None:
    """Read what ONE FILE says about itself into :class:`FileMetadata`.

    EVERY path that creates a ``File`` from real bytes must call this, and so
    must the two that rewrite an existing file's bytes in place — a file with no
    rows here contributes NOTHING the moment it becomes the active one, which
    would read as an item that has lost its metadata. That is the same call-site
    discipline ``compute_phash_image`` and ``colorkey.color_signature`` already
    carry, for the same reason: every one of those callers has the bytes in
    hand, and a listener over ``session.new`` cannot see an in-place rewrite at
    all.

    ``values`` lets a caller that has ALREADY probed the file hand the answer
    over — which is what keeps a video import at one ffprobe run rather than two.

    CALL IT AFTER SETTING ``item.active_file_id``, not before, and every
    caller here does. The active-file listener covers a file that becomes
    active LATER, but it can only see items that already exist
    (``session.dirty``) — a brand-new item has no id during the flush that
    creates it, which is why "a new item is indexed by whoever created it" is
    the rule. Index first and assign after, and that new item ends up with a
    file that knows its metadata and an item that answers nothing.

    It logs nothing. This is derived state like the phash and the colour key,
    and the reasoning ``ops.artifacts.create_one`` writes down applies verbatim:
    the event could never be acted on, a bulk import would write one per file
    saying a cache warmed, and the CASCADE that removes them is silent too.

    Never raises: an unreadable file simply carries no metadata.
    """
    if file.id is None:
        return
    if values is None:
        # Only the READING path needs a file on disk. A caller that already has
        # the answer (the video import, the sidecar restore) may hand it over
        # for a row that has no path yet, and refusing that was a real bug:
        # nothing was written and nothing said so.
        if not file.path:
            return
        try:
            path = store.path_of(session, file)
            if not path.exists():
                return
            if media.classify(path) == "video":
                values = media.probe_video_full(path)[1]
            else:
                values = media.typed_image_metadata(path)
        except Exception:  # noqa: BLE001 - indexing must never break a write
            return
    # Replace, both halves: the DELETE clears what the DB has, the expunge what
    # this transaction has queued (they would collide on (file_id, name)).
    # `fresh`: a file row made a moment ago has neither, and the importer
    # says so rather than pay the statement and the scan of `session.new`
    # for every picture.
    if not fresh:
        session.query(FileMetadata).filter(
            FileMetadata.file_id == file.id).delete()
        for pending in list(session.new):
            if isinstance(pending, FileMetadata) and pending.file_id == file.id:
                session.expunge(pending)
    for mv in values:
        session.add(FileMetadata(
            file_id=file.id, name=mv.name, mtype=mv.mtype,
            num_value=mv.num, text_value=mv.text, raw=mv.raw,
        ))
    # FLUSH, and it is load-bearing: `rebuild_item_metadata` reads these back
    # with SQL and cannot see rows still pending in `session.new`. It runs under
    # `no_autoflush` when the active-file listener calls it, so it cannot flush
    # them itself.
    session.flush()
    item = session.get(Item, file.item_id)
    if item is not None and item.active_file_id == file.id:
        rebuild_item_metadata(session, item.id)


def rebuild_item_metadata(session: Session, item_id: int) -> None:
    """Rebuild an item's derived index from its ACTIVE file, minus its mutes.

    ``ItemMetadata`` is half of what an item answers for ``INFO:`` and
    ``ItemMetaPin`` is the other half; this writes the first half and nothing
    else. Requirement "only item-level and active-file metadata are searched"
    therefore holds BY CONSTRUCTION rather than by a rule anybody has to
    remember: there is no query in the tree that can reach a non-active file's
    values, because nothing copies them here.

    Pure SQL and no I/O. That is what makes it safe inside ``before_flush``,
    where a Pillow open was already the wrong shape and an ffprobe subprocess
    would be indefensible — and it is what finally makes this work for VIDEOS,
    which the disk-reading ``reindex_active_file_metadata`` never could.

    THE CALLER MUST HAVE FLUSHED any ``FileMetadata`` it just wrote: this reads
    them back with SQL, and rows still pending in ``session.new`` are invisible
    to it. Under ``no_autoflush`` — which is where this runs — they cannot be
    flushed from here, so ``index_file_metadata`` flushes for exactly this
    reason. Do not remove that flush.
    """
    item = session.get(Item, item_id)
    if item is None:
        return
    # Both halves of "replace" — the DELETE clears what the DB has, the expunge
    # clears what this transaction has queued. Leaving the pending ones would
    # collide on (item_id, name); see index_item_metadata, which learnt it first.
    session.query(ItemMetadata).filter(ItemMetadata.item_id == item_id).delete()
    for pending in list(session.new):
        if isinstance(pending, ItemMetadata) and pending.item_id == item_id:
            session.expunge(pending)
    if not item.active_file_id:
        return
    muted = set(session.execute(
        select(ItemMetaMute.name).where(ItemMetaMute.item_id == item_id)
    ).scalars().all())
    for fm in session.execute(
        select(FileMetadata).where(FileMetadata.file_id == item.active_file_id)
    ).scalars().all():
        if fm.name in muted:
            continue
        session.add(ItemMetadata(
            item_id=item_id, name=fm.name, mtype=fm.mtype,
            num_value=fm.num_value, text_value=fm.text_value, raw=fm.raw,
        ))
