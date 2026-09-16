"""Subjects: who or what a picture is OF.

A subject is **extra data on a tag** (see :class:`db.Subject`), so almost
nothing here is new machinery: assigning a subject to an item is assigning its
identity tag, its count is that tag's count, and merging two subjects merges
their tags through the endpoint that already does it. What this router owns is
the identity itself — the display name, the disambiguating comment, the
since-date, and the one case a tag cannot express: a subject with no name yet.
"""

from __future__ import annotations


from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_compost.db import (
    Subject,
    Tag,
)
from media_compost.ops import Ctx, subjects as ops_subjects, tagcatalog

from ..deps import get_ctx, get_session
from ..schemas import (
    AppearanceBoxSet,
    AppearanceCreate,
    AppearanceOrder,
    AppearanceUpdate,
    SubjectCreate,
    SubjectMerge,
    SubjectOnItem,
    SubjectRow,
    SubjectUpdate,
)

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


def _rows(s: Session) -> list[SubjectRow]:
    """Every subject, with its tag's effective count and implications.

    The counts come from the same resolver the item-tag list uses, so a subject
    and its tag can never show two different numbers.
    """
    subjects = s.execute(select(Subject)).scalars().all()
    tags = tagcatalog.tags_by_id(s, [x.tag_id for x in subjects])

    counts: dict[str, int] = {}
    if tags:
        # ONE bulk pass, not a COUNT per subject — a 3000-subject library
        # took seconds per listing that way. No container fold — this list
        # never folded it.
        from media_compost.prefilter import counts_without_containers

        counts = counts_without_containers(
            s, [t.name for t in tags.values()])

    implied = tagcatalog.implied_names(s, list(tags))
    out = [
        SubjectRow(
            id=x.id,
            display_name=x.display_name,
            # THE TAG'S, and there is only one of each now: a subject is
            # extra data on a tag, so what it is in a line is the tag's own
            # answer. A subject with no tag has none, which is what an
            # unnamed face cluster genuinely is.
            comment=(tags[x.tag_id].comment or "") if x.tag_id in tags else "",
            tag=(tags[x.tag_id].name if x.tag_id in tags else ""),
            tag_id=x.tag_id,
            since_date=x.since_date,
            items=counts.get(tags[x.tag_id].name, 0) if x.tag_id in tags else 0,
            implies=implied.get(x.tag_id, []) if x.tag_id else [],
            unnamed=bool(x.unnamed),
        )
        for x in subjects
    ]
    out.sort(key=lambda r: (r.display_name or "￿").lower())
    return out


@router.get("", response_model=None)
def list_subjects(q: str = "",
                  limit: int | None = Query(default=None, ge=1, le=500),
                  offset: int = Query(default=0, ge=0),
                  s: Session = Depends(get_session)):
    """Every subject, optionally filtered / paged.

    **Paging is opt-in.** Without ``limit`` the response is the bare
    ``list[SubjectRow]`` it has always been; with ``limit`` it becomes
    ``{"rows": [SubjectRow], "total": N}`` (``total`` = filtered count).
    ``q`` is a case-insensitive substring match on the display name or the
    identity tag; the sort stays the display-name order the list always had.
    """
    rows = _rows(s)
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows
                if needle in (r.display_name or "").lower()
                or needle in (r.tag or "").lower()]
    if limit is None:
        return rows[offset:] if offset else rows
    return {"rows": rows[offset:offset + limit], "total": len(rows)}


@router.post("", response_model=list[SubjectRow])
def create_subject(body: SubjectCreate, ctx: Ctx = Depends(get_ctx)):
    ops_subjects.create(ctx, body.display_name, comment=body.comment,
                        since_date=body.since_date, tag=body.tag)
    return _rows(ctx.session)


@router.patch("/{subject_id}", response_model=list[SubjectRow])
def update_subject(subject_id: int, body: SubjectUpdate,
                   ctx: Ctx = Depends(get_ctx)):
    ops_subjects.update(ctx, subject_id, display_name=body.display_name,
                        comment=body.comment,
                        since_date=body.since_date,
                        tag=body.tag)
    return _rows(ctx.session)


@router.delete("/{subject_id}", response_model=list[SubjectRow])
def delete_subject(subject_id: int, with_tag: bool = False,
                   ctx: Ctx = Depends(get_ctx)):
    """Delete the identity, keeping its tag — the tag is an ordinary one and
    the pictures are still of something. ``with_tag`` deletes that too."""
    ops_subjects.delete_subject(ctx, subject_id, with_tag=with_tag)
    return _rows(ctx.session)


@router.post("/{subject_id}/merge")
def merge_subject(subject_id: int, body: SubjectMerge,
                  ctx: Ctx = Depends(get_ctx)):
    """Fold one subject into another.

    Returns the rows AND the event ids, like ``tags.merge_tag``: the list view
    offers an Undo straight after a merge, and it can only do that if it is
    told what to undo.
    """
    events = ops_subjects.merge(ctx, subject_id, body.into_id,
                                keep_alias=body.keep_alias)
    return {"subjects": _rows(ctx.session), "event_ids": events}


# ---- appearances --------------------------------------------------------

@router.post("/appearances", response_model=list[SubjectOnItem])
def add_appearance(body: AppearanceCreate, ctx: Ctx = Depends(get_ctx)):
    """Somebody is in this picture — optionally at a particular face."""
    row = ops_subjects.add_appearance(
        ctx, body.item_id, subject_id=body.subject_id,
        display_name=body.display_name, face_id=body.face_id)
    return _subjects_on_item(ctx.session, row.item_id)


@router.post("/appearances/order", response_model=list[SubjectOnItem])
def order_appearances(body: AppearanceOrder, ctx: Ctx = Depends(get_ctx)):
    """The sidebar's drag-reorder — every appearance of the item, in the
    order the list now shows."""
    ops_subjects.reorder_appearances(ctx, body.item_id, body.ids)
    return _subjects_on_item(ctx.session, body.item_id)


@router.patch("/appearances/{appearance_id}", response_model=list[SubjectOnItem])
def edit_appearance(appearance_id: int, body: AppearanceUpdate,
                    ctx: Ctx = Depends(get_ctx)):
    """Date one appearance, move it onto (or off) a face, or agree with it."""
    row = ops_subjects.edit_appearance(
        ctx, appearance_id,
        when_date=body.when.date if body.when else None,
        when_age=body.when.age if body.when else None,
        set_when=body.when is not None,
        face_id=body.face_id, confirm=body.confirm)
    return _subjects_on_item(ctx.session, row.item_id)


@router.put("/appearances/{appearance_id}/box",
            response_model=list[SubjectOnItem])
def set_appearance_box(appearance_id: int, body: AppearanceBoxSet,
                       ctx: Ctx = Depends(get_ctx)):
    """Draw (or replace) the appearance's subject box."""
    row = ops_subjects.set_appearance_box(
        ctx, appearance_id, x=body.x, y=body.y, w=body.w, h=body.h,
        points=body.points)
    return _subjects_on_item(ctx.session, row.item_id)


@router.delete("/appearances/{appearance_id}/box",
               response_model=list[SubjectOnItem])
def clear_appearance_box(appearance_id: int, ctx: Ctx = Depends(get_ctx)):
    """Take the appearance's subject box down."""
    row = ops_subjects.set_appearance_box(ctx, appearance_id, clear=True)
    return _subjects_on_item(ctx.session, row.item_id)


@router.delete("/appearances/{appearance_id}", response_model=list[SubjectOnItem])
def remove_appearance(appearance_id: int, ctx: Ctx = Depends(get_ctx)):
    """Take one appearance off."""
    item_id = ops_subjects.remove_appearance(ctx, appearance_id)
    return _subjects_on_item(ctx.session, item_id)


def _subjects_on_item(s: Session, item_id: int):
    """The item's subjects and every appearance of each — imported from the
    items router, which owns the shape."""
    from .items import _subjects_on_item as build

    return build(s, item_id)
