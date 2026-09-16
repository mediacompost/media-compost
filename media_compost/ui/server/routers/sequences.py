"""Sequences: ordered collections (comic pages, video frames, manual).

An item may belong to several sequences; ``Item.main_sequence_id`` selects the
one that drives its grid number badge. Members can be renamed, reordered,
removed, and a main sequence chosen.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_compost.db import Item, Sequence, SequenceItem
from media_compost.sequences import ensure_container
from media_compost.ops import Ctx, sequences as ops_sequences
from ..deps import get_ctx, get_session
from ..schemas import (
    MainSequenceIn,
    SequenceCreate,
    SequenceInfo,
    SequenceItemsIn,
    SequenceMember,
    SequenceRename,
    SequenceReorder,
    SequenceSummary,
)

router = APIRouter(tags=["sequences"])


@router.get("/api/sequences", response_model=None)
def list_sequences(q: str = "",
                   limit: int | None = Query(default=None, ge=1, le=500),
                   offset: int = Query(default=0, ge=0),
                   s: Session = Depends(get_session)):
    """Every sequence in the library (for the left-sidebar Sequences list).

    Counts and first-member thumbnails are gathered in one pass so the list
    stays O(members) rather than per-sequence.

    **Paging is opt-in.** Without ``limit`` the response is the bare
    ``list[SequenceSummary]`` it has always been; with ``limit`` it becomes
    ``{"rows": [SequenceSummary], "total": N}`` (``total`` = filtered count).
    ``q`` is a case-insensitive substring match on the name; the sort stays
    name order.
    """
    from sqlalchemy import func

    seqs = s.execute(select(Sequence)).scalars().all()
    if not seqs:
        return [] if limit is None else {"rows": [], "total": 0}
    # Counts in ONE grouped statement and first members in one windowed
    # statement (this used to stream every membership row into Python).
    totals: dict[int, int] = {
        sid: int(cnt) for sid, cnt in s.execute(
            select(SequenceItem.sequence_id, func.count())
            .group_by(SequenceItem.sequence_id)
        ).all()
    }
    rn = func.row_number().over(
        partition_by=SequenceItem.sequence_id,
        order_by=(SequenceItem.position, SequenceItem.id),
    ).label("rn")
    ranked = select(SequenceItem.sequence_id, SequenceItem.item_id,
                    rn).subquery()
    first_item: dict[int, tuple[int, int]] = {
        sid: (0, iid) for sid, iid in s.execute(
            select(ranked.c.sequence_id, ranked.c.item_id)
            .where(ranked.c.rn == 1)
        ).all()
    }
    active_by_item = {
        it.id: it.active_file_id
        for it in s.execute(
            select(Item).where(Item.id.in_([v[1] for v in first_item.values()] or [0]))
        ).scalars().all()
    }
    out = [
        SequenceSummary(
            id=seq.id, name=seq.name, kind=seq.kind, total=totals.get(seq.id, 0),
            thumb_file_id=active_by_item.get(
                first_item[seq.id][1]) if seq.id in first_item else None,
        )
        for seq in seqs
    ]
    out.sort(key=lambda x: x.name.lower())
    needle = q.strip().lower()
    if needle:
        out = [r for r in out if needle in r.name.lower()]
    if limit is None:
        return out[offset:] if offset else out
    return {"rows": out[offset:offset + limit], "total": len(out)}


@router.post("/api/sequences")
def create_sequence(body: SequenceCreate, ctx: Ctx = Depends(get_ctx)):
    """Create a manual sequence from the given items (in the order supplied)."""
    seq_id, item_id = ops_sequences.create(ctx, body.item_ids, name=body.name)
    return {"ok": True, "id": seq_id, "item_id": item_id}


@router.delete("/api/sequences/{seq_id}")
def remove_sequence(seq_id: int, ctx: Ctx = Depends(get_ctx)):
    """Remove a sequence (and its container item) without deleting its members."""
    ops_sequences.remove(ctx, seq_id)
    return {"ok": True}


def _members(s: Session, seq: Sequence) -> list[SequenceMember]:
    rows = s.execute(
        select(SequenceItem, Item)
        .join(Item, Item.id == SequenceItem.item_id)
        .where(SequenceItem.sequence_id == seq.id)
        .order_by(SequenceItem.position, SequenceItem.id)
    ).all()
    out: list[SequenceMember] = []
    for pos, (si, it) in enumerate(rows, start=1):
        out.append(SequenceMember(
            id=si.id, item_id=it.id, position=pos, name=it.name,
            active_file_id=it.active_file_id, kind=it.kind,
        ))
    return out


@router.get("/api/sequences/{seq_id}", response_model=SequenceInfo)
def get_sequence(seq_id: int, s: Session = Depends(get_session)):
    """One sequence with its ordered members (drives a sequence item's sidebar)."""
    seq = s.get(Sequence, seq_id)
    if not seq:
        raise HTTPException(404, "sequence not found")
    members = _members(s, seq)
    # Ensure the container item exists so the sidebar can select it when a
    # sequence is opened with nothing else selected.
    container = ensure_container(s, seq)
    return SequenceInfo(
        id=seq.id, uid=seq.uid, name=seq.name, kind=seq.kind, is_main=False,
        total=len(members), members=members, item_id=container.id,
        item_uid=container.uid,
    )


@router.get("/api/items/{item_id}/sequences", response_model=list[SequenceInfo])
def item_sequences(item_id: int, s: Session = Depends(get_session)):
    item = s.get(Item, item_id)
    if not item:
        raise HTTPException(404, "item not found")
    # DISTINCT: an item at three positions of one sequence is in ONE
    # sequence, not three copies of it.
    seq_ids = s.execute(
        select(SequenceItem.sequence_id)
        .where(SequenceItem.item_id == item_id).distinct()
    ).scalars().all()
    out: list[SequenceInfo] = []
    for sid in seq_ids:
        seq = s.get(Sequence, sid)
        if seq is None:
            continue
        members = _members(s, seq)
        container = s.get(Item, seq.item_id) if seq.item_id else None
        out.append(SequenceInfo(
            id=seq.id, uid=seq.uid, name=seq.name, kind=seq.kind,
            is_main=(item.main_sequence_id == seq.id),
            total=len(members), members=members,
            item_id=container.id if container else None,
            item_uid=container.uid if container else None,
        ))
    # Main sequence first, then by name for stable display.
    out.sort(key=lambda si: (not si.is_main, si.name.lower()))
    return out


@router.patch("/api/sequences/{seq_id}")
def rename_sequence(seq_id: int, body: SequenceRename,
                    ctx: Ctx = Depends(get_ctx)):
    ops_sequences.rename(ctx, seq_id, body.name)
    return {"ok": True}


@router.post("/api/sequences/{seq_id}/reorder")
def reorder_sequence(seq_id: int, body: SequenceReorder,
                     ctx: Ctx = Depends(get_ctx)):
    if body.member_ids:
        ops_sequences.reorder(ctx, seq_id, member_ids=body.member_ids)
    else:
        ops_sequences.reorder(ctx, seq_id, body.item_ids)
    return {"ok": True}


@router.post("/api/sequences/{seq_id}/remove")
def remove_from_sequence(seq_id: int, body: SequenceItemsIn,
                         ctx: Ctx = Depends(get_ctx)):
    if body.member_ids:
        count = ops_sequences.remove_members(ctx, seq_id,
                                             member_ids=body.member_ids)
    else:
        count = ops_sequences.remove_members(ctx, seq_id, body.item_ids)
    return {"ok": True, "count": count}


@router.patch("/api/items/{item_id}/main-sequence")
def set_main_sequence(item_id: int, body: MainSequenceIn,
                      ctx: Ctx = Depends(get_ctx)):
    ops_sequences.set_main(ctx, item_id, body.sequence_id)
    return {"ok": True}
