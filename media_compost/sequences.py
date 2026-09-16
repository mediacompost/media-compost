"""Helpers for the container Item that represents a Sequence in the library.

Each :class:`~media_compost.db.Sequence` has a 1:1 container
:class:`~media_compost.db.Item` of ``kind="sequence"``. The container carries the
sequence's tags, groups and captions and is what the user sees/searches in the
grid; it owns no files of its own — its thumbnail/active file is borrowed from
its first member so the grid can show a representative image. Members remain
independent items (they still appear in the library on their own).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Item, Sequence, SequenceItem


def _first_member_file(s: Session, seq_id: int) -> Optional[int]:
    """active_file_id of the sequence's first (lowest-position) member."""
    row = s.execute(
        select(Item.active_file_id)
        .join(SequenceItem, SequenceItem.item_id == Item.id)
        .where(SequenceItem.sequence_id == seq_id)
        .order_by(SequenceItem.position, SequenceItem.id)
        .limit(1)
    ).first()
    return row[0] if row else None


def ensure_container(s: Session, seq: Sequence) -> Item:
    """Create (or update) the container item for a sequence and link it.

    Call after the sequence's members exist so the thumbnail can be borrowed
    from the first member.
    """
    item = s.get(Item, seq.item_id) if seq.item_id is not None else None
    if item is None:
        item = Item(name=seq.name, kind="sequence")
        s.add(item)
        s.flush()
        seq.item_id = item.id
    item.name = seq.name
    item.active_file_id = _first_member_file(s, seq.id)
    return item


def sync_container(s: Session, seq_id: int) -> None:
    """Refresh the container's borrowed thumbnail after members change."""
    seq = s.get(Sequence, seq_id)
    if seq is None or seq.item_id is None:
        return
    item = s.get(Item, seq.item_id)
    if item is not None:
        item.active_file_id = _first_member_file(s, seq_id)


def delete_sequence(s: Session, seq: Sequence) -> None:
    """Remove a sequence and its container item, keeping the member items.

    Member items lose their membership rows (cascade) and any ``main_sequence_id``
    pointing here is cleared; the items themselves survive.
    """
    for it in s.execute(
        select(Item).where(Item.main_sequence_id == seq.id)
    ).scalars().all():
        it.main_sequence_id = None
    container_id = seq.item_id
    s.delete(seq)  # cascades SequenceItem rows
    if container_id is not None:
        container = s.get(Item, container_id)
        if container is not None:
            s.delete(container)  # cascades the container's own tags/groups/captions
