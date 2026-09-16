"""Events: what was happening.

An event hangs off a TAG, exactly as subject and location data do (see
:class:`db.Occasion`), so assigning an event is assigning its tag and search,
counts and facets need nothing new. What this router owns is the extra half —
the display name, the span of days, the places it was at — plus the one thing
only events need: the SUGGESTIONS an event implies, and the refusals that stop
them being offered twice.

Note the model is `Occasion` and the API is `/api/events`: `Event` is the
modification log's row. Locals here are named ``occ`` for the same reason.

Nothing here formats a date or a place's line; `partialdate.format_en` writes the
one sentence a log entry needs and the frontend does the rest.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_compost import partialdate as pdate
from media_compost.db import (
    Item,
    ItemMetadata,
    ItemOccasionDismissal,
    ItemPlaceDismissal,
    Location,
    Occasion,
    OccasionPlace,
    Tag,
    chunked,
)
from media_compost.ops import (Ctx, events as ops_events,
                               places as ops_places, tagcatalog)
from media_compost.resolve import effective_for_items
from ..deps import get_ctx, get_session
from ..schemas import (
    DismissEvent,
    DismissPlace,
    EventCreate,
    EventRow,
    EventUpdate,
    FilePlaceRef,
    FilePlaceSuggestion,
    ItemSuggestions,
    PlaceRow,
    SuggestedEvent,
    SuggestedPlace,
)

router = APIRouter(prefix="/api/events", tags=["events"])


def _place_row(s: Session, loc) -> PlaceRow:
    tag = s.get(Tag, loc.tag_id) if loc.tag_id else None
    return PlaceRow(
        id=loc.id, tag=tag.name if tag else "", tag_id=loc.tag_id,
        name=loc.name or "", parent_id=loc.parent_id,
        lat=loc.lat, lon=loc.lon,
    )


def _places_of(s: Session, occasion_ids: list[int]) -> dict[int, list[PlaceRow]]:
    """The places each event was at, as whole rows."""
    out: dict[int, list[PlaceRow]] = {}
    if not occasion_ids:
        return out
    rows = []
    for chunk in chunked(occasion_ids):
        rows.extend(s.execute(
            select(OccasionPlace.occasion_id, Location)
            .join(Location, Location.id == OccasionPlace.location_id)
            .where(OccasionPlace.occasion_id.in_(chunk))
        ).all())
    names = {t.id: t.name for t in tagcatalog.tags_by_id(
        s, [loc.tag_id for _, loc in rows]).values()}
    for oid, loc in rows:
        out.setdefault(oid, []).append(PlaceRow(
            id=loc.id, tag=names.get(loc.tag_id, "") if loc.tag_id else "",
            tag_id=loc.tag_id, name=loc.name or "",
            parent_id=loc.parent_id, lat=loc.lat, lon=loc.lon,
        ))
    return out


def _rows(s: Session) -> list[EventRow]:
    """Every event with its places and its picture count.

    The count comes from the same resolver the item-tag list uses, so an event
    and its tag can never show two different numbers."""
    occasions = s.execute(select(Occasion)).scalars().all()
    if not occasions:
        return []
    places = _places_of(s, [o.id for o in occasions])
    rows = list(tagcatalog.tags_by_id(
        s, [o.tag_id for o in occasions]).values())
    tags = {t.id: t.name for t in rows}
    # What the event IS, in a line, is its TAG's — one answer, one editor.
    # An event with no tag shows none.
    comments = {t.id: t.comment or "" for t in rows}

    counts: dict[str, int] = {}
    if tags:
        # ONE bulk pass, not a COUNT per event — see `counts_without_containers`.
        from media_compost.prefilter import counts_without_containers

        counts = counts_without_containers(s, list(tags.values()))

    out = [
        EventRow(
            id=o.id, tag=tags.get(o.tag_id, "") if o.tag_id else "",
            tag_id=o.tag_id, display_name=o.display_name or "",
            parent_id=o.parent_id,
            comment=comments.get(o.tag_id, ""),
            start_date=o.start_date, end_date=o.end_date,
            places=places.get(o.id, []),
            items=counts.get(tags.get(o.tag_id, ""), 0) if o.tag_id else 0,
        )
        for o in occasions
    ]
    # By when it was, then by name — a list of events reads as a timeline, and
    # an undated one has no place on it, so it sorts last.
    out.sort(key=lambda r: (r.start_date or 99999999,
                            (r.display_name or r.tag).lower()))
    return out


@router.get("", response_model=list[EventRow])
def list_events(s: Session = Depends(get_session)):
    return _rows(s)


@router.post("", response_model=list[EventRow])
def create_event(body: EventCreate, ctx: Ctx = Depends(get_ctx)):
    """Create an event, minting its identity tag from the name."""
    ops_events.create(ctx, tag=body.tag, display_name=body.display_name,
                      comment=body.comment,
                      parent_id=body.parent_id,
                      start_date=body.start_date,
                      end_date=body.end_date, places=body.place_ids)
    return _rows(ctx.session)


@router.patch("/{event_id}", response_model=list[EventRow])
def update_event(event_id: int, body: EventUpdate,
                 ctx: Ctx = Depends(get_ctx)):
    ops_events.update(ctx, event_id, tag=body.tag,
                      display_name=body.display_name, comment=body.comment,
                      parent_id=body.parent_id,
                      clear_parent=body.clear_parent,
                      start_date=body.start_date, end_date=body.end_date,
                      places=body.place_ids)
    return _rows(ctx.session)


@router.delete("/{event_id}", response_model=list[EventRow])
def delete_event(event_id: int, with_tag: bool = False,
                 ctx: Ctx = Depends(get_ctx)):
    """Drop the event data, keeping its tag. ``with_tag`` deletes that too."""
    ops_events.delete_event(ctx, event_id, with_tag=with_tag)
    return _rows(ctx.session)


# ---- suggestions -----------------------------------------------------------
#
# Nothing here is stored. An event knows where it was and when, so a picture
# that carries its tag can be OFFERED its venues, and a picture taken inside
# its span can be offered the event — but never given either, because half of
# a week's photographs were taken somewhere else. Only the refusals persist.
#
# It lives in the backend for the same reason `_subjects_on_item` does: it is a
# VIEW, computed on read and owning no state, and the one place the rule is
# written. The frontend could not own it honestly anyway — `date_taken` reaches
# the browser only as a formatted display string, and the refusals are here.

def _date_taken(s: Session, item_id: int) -> Optional[int]:
    """The item's indexed capture date as YYYYMMDD, or None.

    The index stores YYYYMMDDHHMMSS; the time of day says nothing about which
    event a picture is from, so it is dropped before the comparison.
    """
    # What somebody TYPED wins over what the camera said: that is what makes
    # it an override rather than a second opinion — including when what they
    # typed is "there is no date", which offers nothing rather than falling
    # through to the EXIF they were overruling.
    from media_compost.db import TAKEN_NONE

    item = s.get(Item, item_id)
    if item is not None and item.taken_at == TAKEN_NONE:
        return None
    if item is not None and item.taken_at:
        return int(item.taken_at) // 1_000_000 or None
    # Pin first, then the active file's EXIF (see `itemmeta.effective_nums`).
    from media_compost.itemmeta import effective_num

    row = effective_num(s, item_id, "date_taken")
    if row is None:
        return None
    return int(row) // 1_000_000 or None


def _covers(occ: Occasion, day: int) -> bool:
    """Whether the event's span contains that day. A half-open span is read as
    the point it names — "from July 2014" with no end covers July 2014, which
    is all that is actually known."""
    if occ.start_date is None and occ.end_date is None:
        return False
    lo = pdate.bounds(occ.start_date or occ.end_date)[0]
    hi = pdate.bounds(occ.end_date or occ.start_date)[1]
    return lo <= day <= hi


@router.get("/suggestions/{item_id}", response_model=ItemSuggestions)
def suggestions(item_id: int, s: Session = Depends(get_session)):
    if s.get(Item, item_id) is None:
        raise HTTPException(404, "item not found")
    # Through the ONE resolver, so an event reached by an IMPLICATION counts —
    # the same way `dog` counts for a `poodle`-tagged item.
    eff = effective_for_items(s, [item_id]).get(item_id)
    on_item = set(eff.positive) | set(eff.negative) if eff else set()

    occasions = s.execute(
        select(Occasion).where(Occasion.tag_id.is_not(None))).scalars().all()
    tag_names = {t.id: t.name for t in tagcatalog.tags_by_id(
        s, [o.tag_id for o in occasions]).values()}
    places = _places_of(s, [o.id for o in occasions])

    # 1. The venues of the events this picture is already at.
    refused_places = set(s.execute(
        select(ItemPlaceDismissal.location_id)
        .where(ItemPlaceDismissal.item_id == item_id)).scalars().all())
    offered: list[SuggestedPlace] = []
    seen: set[int] = set()
    for occ in occasions:
        name = tag_names.get(occ.tag_id, "")
        if not name or name not in (eff.positive if eff else ()):
            continue
        for p in places.get(occ.id, []):
            # Already answered: it is on the picture, it was refused, or another
            # event at the same venue has offered it in this very list.
            if p.id in refused_places or p.id in seen or p.tag in on_item:
                continue
            seen.add(p.id)
            offered.append(SuggestedPlace(
                place=p, occasion_id=occ.id, via_event_tag=name,
                via_event_name=occ.display_name or name))

    # 2. The events whose span holds this picture's own capture date.
    day = _date_taken(s, item_id)
    refused_events = set(s.execute(
        select(ItemOccasionDismissal.occasion_id)
        .where(ItemOccasionDismissal.item_id == item_id)).scalars().all())
    by_id = {r.id: r for r in _rows(s)}
    events = [
        SuggestedEvent(event=by_id[occ.id], date_taken=day)
        for occ in occasions
        if day is not None and occ.id not in refused_events
        and tag_names.get(occ.tag_id, "") not in on_item
        and _covers(occ, day) and occ.id in by_id
    ]
    events.sort(key=lambda e: e.event.start_date or 0)

    # 3. What the item's OWN FILE says about where it was taken — offered,
    # never created (the importer used to mint the place outright; a crawl of
    # random web images made that a Places list full of strangers'
    # coordinates). Derived from the indexed `location`/`gps_lat`/`gps_lon`
    # metadata, so it costs no file read.
    file_place = None
    info = ops_places.file_place_of(s, item_id)
    if info is not None and not ops_places.file_place_answered(s, item_id,
                                                               info):
        p = info["place"]
        file_place = FilePlaceSuggestion(
            name=info["name"], lat=info["lat"], lon=info["lon"],
            place=_place_row(s, p) if p is not None else None)
    return ItemSuggestions(places=offered, events=events, dated=day is not None,
                           file_place=file_place)


@router.post("/dismiss-place", response_model=ItemSuggestions)
def dismiss_place(body: DismissPlace, ctx: Ctx = Depends(get_ctx)):
    """"Not there." Keyed on (item, place) and nothing else."""
    ops_events.dismiss_place(ctx, body.item_id, body.location_id,
                             via_occasion_id=body.via_occasion_id)
    return suggestions(body.item_id, ctx.session)


@router.post("/dismiss-event", response_model=ItemSuggestions)
def dismiss_event(body: DismissEvent, ctx: Ctx = Depends(get_ctx)):
    ops_events.dismiss_event(ctx, body.item_id, body.occasion_id)
    return suggestions(body.item_id, ctx.session)


@router.post("/adopt-file-place", response_model=ItemSuggestions)
def adopt_file_place(body: FilePlaceRef, ctx: Ctx = Depends(get_ctx)):
    """Accept the place the item's own file names: create it if it does not
    exist yet (with the configured place-tag prefix) and assign its tag —
    the deliberate spelling of what the importer used to do silently."""
    ops_places.adopt_file_place(ctx, body.item_id)
    return suggestions(body.item_id, ctx.session)


@router.post("/dismiss-file-place", response_model=ItemSuggestions)
def dismiss_file_place(body: FilePlaceRef, ctx: Ctx = Depends(get_ctx)):
    """"Not there." Keyed on the item alone — the suggested place need not
    exist yet, so there is nothing else to key on."""
    ops_places.dismiss_file_place(ctx, body.item_id)
    return suggestions(body.item_id, ctx.session)
