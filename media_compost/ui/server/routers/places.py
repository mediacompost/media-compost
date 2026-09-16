"""Places: where a picture is.

Location data hangs off a TAG, exactly as subject data does (see
:class:`db.Location`), so assigning a place is assigning its tag and search,
counts and facets need nothing new. What this router owns is the structured
half — the one line it is called by, the coordinates, the parent — plus the unnamed
places an older library's bare GPS pins left behind, and the file-place
suggestion an item's own metadata makes.
"""

from __future__ import annotations


from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_compost.db import (
    ItemLocation,
    Location,
    Tag,
)
from media_compost.ops import Ctx, places as ops_places, tagcatalog

from ..deps import get_ctx, get_session
from ..schemas import PlaceCreate, PlaceRow, PlaceUpdate

router = APIRouter(prefix="/api/places", tags=["places"])

def _rows(s: Session) -> list[PlaceRow]:
    """Every place with its name and its picture count.

    A named place counts its tag's items (the tag IS the assignment); an
    unnamed one counts the items pinned to it directly, which is the only case
    that needs `item_locations` at all.
    """
    places = s.execute(select(Location)).scalars().all()
    if not places:
        return []
    rows = list(tagcatalog.tags_by_id(
        s, [p.tag_id for p in places]).values())
    tags = {t.id: t.name for t in rows}
    # The comment is the identity TAG's — one answer, one editor.
    comments = {t.id: t.comment or "" for t in rows}

    counts: dict[str, int] = {}
    if tags:
        # ONE bulk pass, not a COUNT per place — see `counts_without_containers`.
        from media_compost.prefilter import counts_without_containers

        counts = counts_without_containers(s, list(tags.values()))
    pinned: dict[int, int] = {}
    for lid, in s.execute(select(ItemLocation.location_id)).all():
        pinned[lid] = pinned.get(lid, 0) + 1

    out = [
        PlaceRow(
            id=p.id, tag=tags.get(p.tag_id, "") if p.tag_id else "",
            tag_id=p.tag_id,
            name=p.name or "", parent_id=p.parent_id,
            comment=comments.get(p.tag_id, ""),
            lat=p.lat, lon=p.lon,
            items=(counts.get(tags[p.tag_id], 0) if p.tag_id in tags
                   else pinned.get(p.id, 0)),
        )
        for p in places
    ]
    out.sort(key=lambda r: ((r.name or r.tag or "").lower(), r.tag))
    return out


@router.get("", response_model=None)
def list_places(q: str = "",
                limit: int | None = Query(default=None, ge=1, le=500),
                offset: int = Query(default=0, ge=0),
                s: Session = Depends(get_session)):
    """Every place, optionally filtered / paged.

    **Paging is opt-in.** Without ``limit`` the response is the bare
    ``list[PlaceRow]`` it has always been; with ``limit`` it becomes
    ``{"rows": [PlaceRow], "total": N}`` (``total`` = filtered count).
    ``q`` is a case-insensitive substring match on the identity tag or the
    one line; the sort is that name, then tag.
    """
    rows = _rows(s)
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows
                if needle in (r.tag or "").lower()
                or needle in (r.name or "").lower()]
    if limit is None:
        return rows[offset:] if offset else rows
    return {"rows": rows[offset:offset + limit], "total": len(rows)}


@router.post("", response_model=list[PlaceRow])
def create_place(body: PlaceCreate, ctx: Ctx = Depends(get_ctx)):
    """Create a place, minting its identity tag unless it is an unnamed one."""
    ops_places.create(ctx, tag=body.tag, name=body.name,
                      parent_id=body.parent_id,
                      comment=body.comment,
                      lat=body.lat, lon=body.lon)
    return _rows(ctx.session)


@router.patch("/{place_id}", response_model=list[PlaceRow])
def update_place(place_id: int, body: PlaceUpdate,
                 ctx: Ctx = Depends(get_ctx)):
    ops_places.update(ctx, place_id, tag=body.tag,
                      name=body.name,
                      parent_id=body.parent_id,
                      clear_parent=body.clear_parent,
                      comment=body.comment,
                      lat=body.lat, lon=body.lon,
                      clear_coords=body.clear_coords)
    return _rows(ctx.session)


@router.delete("/{place_id}", response_model=list[PlaceRow])
def delete_place(place_id: int, with_tag: bool = False,
                 ctx: Ctx = Depends(get_ctx)):
    """Drop the location data, keeping its tag — the tag is an ordinary tag and
    the pictures were still taken somewhere. ``with_tag`` deletes that too."""
    ops_places.delete_place(ctx, place_id, with_tag=with_tag)
    return _rows(ctx.session)
