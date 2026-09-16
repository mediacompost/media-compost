"""History view: list the library's modification log and revert entries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from media_compost.db import Event
from media_compost.history import can_revert, load_data, revert_event
from media_compost.ops import log as oplog
from media_compost.ops.context import Ctx
from ..deps import Library, get_current_user, get_library, get_session
from ..schemas import (
    ClearHistoryResult, EventOut, HistoryPage, RevertRequest, RevertResult,
)

router = APIRouter(prefix="/api/history", tags=["history"])


def _iso_utc(dt: datetime | None) -> str:
    """Serialize a stored timestamp as an explicit-UTC ISO string.

    Timestamps are written with ``datetime.now(timezone.utc)`` but the
    ``DateTime`` columns are naive, so the tz is dropped on the way in. Marking
    the value UTC here lets the browser convert it to the viewer's local zone
    (otherwise ``new Date(iso)`` parses it as local and shows the wrong time).
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _summary_vars(ev: Event) -> dict:
    try:
        val = json.loads(ev.summary_vars) if ev.summary_vars else {}
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


def _to_out(ev: Event, s: Session) -> EventOut:
    return EventOut(
        id=ev.id,
        created_at=_iso_utc(ev.created_at),
        source=ev.source,
        username=ev.username or "",
        action=ev.action,
        entity_type=ev.entity_type or "",
        entity_id=ev.entity_id,
        summary=ev.summary or "",
        summary_key=ev.summary_key or "",
        summary_vars=_summary_vars(ev),
        data=load_data(ev),
        reverted=ev.reverted_at is not None,
        # A reverted event can't be reverted again — but a REVERT can, which
        # simply does the original action once more (see history.can_revert).
        revertible=can_revert(s, ev),
    )


@router.get("", response_model=HistoryPage)
def list_history(limit: int = 500, offset: int = 0,
                 after_id: Optional[int] = None,
                 s: Session = Depends(get_session)):
    """Newest-first page of events. The UI groups similar consecutive ones.

    ``after_id`` narrows it to what has been written SINCE a known event, which
    is how a caller asks "what did the thing I just did log?" — the sidebar's
    undo bar takes a watermark before a removal and reads the answer back
    afterwards. Ids are the watermark rather than a timestamp because two
    events inside one request share a clock reading to the second.
    """
    total = s.execute(select(func.count(Event.id))).scalar_one()
    q = select(Event)
    if after_id is not None:
        q = q.where(Event.id > after_id)
    rows = s.execute(
        q.order_by(Event.created_at.desc(), Event.id.desc())
        .limit(max(1, min(limit, 2000))).offset(max(0, offset))
    ).scalars().all()
    return HistoryPage(events=[_to_out(e, s) for e in rows], total=int(total))


@router.delete("", response_model=ClearHistoryResult)
def clear_history(s: Session = Depends(get_session),
                  user: str = Depends(get_current_user)):
    """Empty the modification log.

    The log is append-only by design, and this is the one way out of that. It
    changes nothing about the library itself — only what it remembers having
    done — but it does make everything already done permanent, since a revert
    reads the entry it is undoing. The UI asks before calling it.
    """
    deleted = oplog.clear(Ctx(session=s, source="web", username=user))
    s.commit()
    return ClearHistoryResult(deleted=deleted)


@router.post("/revert", response_model=RevertResult)
def revert(body: RevertRequest, s: Session = Depends(get_session),
           lib: Library = Depends(get_library)):
    """Undo the given events where possible; report which succeeded/failed.

    Applied newest-first so a group reverted together unwinds in reverse order.

    `events` are the log entries the reversal itself wrote. Reverting THOSE
    replays the original, which is the whole of redo — so a caller that keeps
    them can offer one without knowing anything about what it undid.
    """
    reverted: list[int] = []
    failed: list[int] = []
    wrote: list[Event] = []
    rows = s.execute(
        select(Event).where(Event.id.in_(body.event_ids))
        .order_by(Event.created_at.desc(), Event.id.desc())
    ).scalars().all()
    for ev in rows:
        note = revert_event(s, ev, store=lib.store)
        if note is not None:
            reverted.append(ev.id)
            wrote.append(note)
        else:
            failed.append(ev.id)
    s.flush()   # the new rows have no id until this runs
    return RevertResult(reverted=reverted, failed=failed,
                        events=[e.id for e in wrote])
