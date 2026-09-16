"""Events — what was happening.

An event hangs off a TAG, exactly as subject and location data do (see
:class:`db.Occasion`), so assigning an event is assigning its tag and search,
counts and facets need nothing new. What this module owns is the extra half —
the display name, the span of days, the places it was at — plus the refusals
that stop a suggestion being offered twice.

Note the model is `Occasion` and the API is `/api/events`: `Event` is the
modification log's row. Locals here are named ``occ`` for the same reason.

**A refusal is keyed on (item, target) and NOTHING else.** Keying it on the
event that prompted the offer reads more precise and is wrong twice: editing
that event's venue list would re-offer a refused place, and a second event at
the same venue would ask again. `via_occasion_id` is for the History sentence
only and is never read by the rule.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from .. import partialdate as pdate
from ..db import (
    Item, ItemOccasionDismissal, ItemPlaceDismissal, Location, Occasion,
    OccasionPlace, Tag, touch_items,
)
from . import actions, naming, tagcatalog
from .context import Ctx
from .errors import Conflict, Invalid, NotFound

# ---- helpers ----------------------------------------------------------------


def check_span(start: Optional[int], end: Optional[int]) -> None:
    """A date that is not one, or a span that runs backwards, is refused HERE
    and not only in the overlay — this is reachable from scripting and from
    the CLI, and a backwards span makes every suggestion silently empty."""
    for d in (start, end):
        if d and not pdate.is_valid(d):
            raise Invalid("not a valid partial date", code="invalid_date")
    if start and end and pdate.bounds(start)[0] > pdate.bounds(end)[1]:
        raise Invalid("the event ends before it starts", code="span_backwards")


def place_ids(ctx: Ctx, occ: Occasion) -> list[int]:
    return sorted(ctx.session.execute(
        select(OccasionPlace.location_id)
        .where(OccasionPlace.occasion_id == occ.id)
    ).scalars().all())


def set_places(ctx: Ctx, occ: Occasion, ids: list[int]) -> None:
    """Replace the event's places with the ones given.

    A place must be NAMED. That is what makes the sidecar possible: refs there
    are tag names, never row ids, and an unnamed place has no name to write.
    """
    s = ctx.session
    wanted = set(ids)
    if wanted:
        found = {
            loc.id: loc for loc in s.execute(
                select(Location).where(Location.id.in_(wanted))
            ).scalars().all()
        }
        missing = wanted - set(found)
        if missing:
            raise NotFound("no such place: {name}",
                           {"name": sorted(missing)[0]},
                           code="place_not_found")
        for loc in found.values():
            if loc.tag_id is None:
                raise Invalid("an event's place must be named first",
                              code="place_unnamed")
    have = {row.location_id: row for row in s.execute(
        select(OccasionPlace).where(OccasionPlace.occasion_id == occ.id)
    ).scalars().all()}
    for lid in wanted - set(have):
        s.add(OccasionPlace(occasion_id=occ.id, location_id=lid))
    for lid in set(have) - wanted:
        s.delete(have[lid])


def label(ctx: Ctx, occ: Occasion) -> str:
    if occ.display_name:
        return occ.display_name
    tag = ctx.session.get(Tag, occ.tag_id) if occ.tag_id else None
    return tag.name if tag is not None else f"event #{occ.id}"


def state(ctx: Ctx, occ: Occasion) -> dict:
    """The fields an edit event records, before and after."""
    return {"display_name": occ.display_name or "",
            "parent_id": occ.parent_id,
            "start_date": occ.start_date, "end_date": occ.end_date,
            "place_ids": place_ids(ctx, occ)}


def _claim_tag(ctx: Ctx, wanted: str) -> Tag:
    """The tag named ``wanted``, refused if another event already IS it."""
    s = ctx.session
    tag = s.execute(select(Tag).where(Tag.name == wanted)).scalars().first()
    if tag is None:
        tag = Tag(name=wanted)
        s.add(tag)
        s.flush()
    elif s.execute(select(Occasion).where(Occasion.tag_id == tag.id)
                   ).scalars().first() is not None:
        raise Conflict("that tag is already an event", code="tag_is_an_event")
    return tag


# ---- the record -------------------------------------------------------------


def set_parent(ctx: Ctx, occ: Occasion, parent_id: Optional[int]) -> None:
    """Put an event INSIDE another — Day 1 in the convention in the season.

    The same two halves a place's parent has: the column is the tree, and the
    identity tags gain the ordinary IMPLICATION that makes assigning the day
    assign everything it is part of. A cycle is refused here, where the tree
    is what the refusal is about.
    """
    s = ctx.session
    if parent_id is not None:
        if parent_id == occ.id:
            raise Invalid("an event cannot be part of itself", code="event_cycle")
        walk = s.get(Occasion, parent_id)
        if walk is None:
            raise NotFound("event not found", code="event_not_found")
        seen = {occ.id}
        while walk is not None:
            if walk.id in seen:
                raise Invalid("that would put an event inside itself",
                              code="event_cycle")
            seen.add(walk.id)
            walk = s.get(Occasion, walk.parent_id) if walk.parent_id else None
    old = s.get(Occasion, occ.parent_id) if occ.parent_id else None
    occ.parent_id = parent_id
    new = s.get(Occasion, parent_id) if parent_id else None
    if occ.tag_id is None:
        return
    if old is not None and old.tag_id is not None:
        target = s.get(Tag, old.tag_id)
        if target is not None:
            tagcatalog.remove_implication(ctx, occ.tag_id, target.name)
    if new is not None and new.tag_id is not None:
        target = s.get(Tag, new.tag_id)
        if target is not None:
            tagcatalog.add_implication(ctx, occ.tag_id, target.name)


def create(ctx: Ctx, *, tag: str = "", display_name: str = "",
           comment: str = "",
           parent_id: Optional[int] = None,
           start_date: Optional[int] = None,
           end_date: Optional[int] = None,
           places: Optional[list[int]] = None) -> Occasion:
    """Create an event, minting its identity tag from the name."""
    s = ctx.session
    check_span(start_date, end_date)
    occ = Occasion(display_name=(display_name or "").strip(),
                   start_date=start_date or None, end_date=end_date or None)
    s.add(occ)
    s.flush()
    set_places(ctx, occ, places or [])
    # Invented slugs carry the library's event namespace; a tag typed by hand
    # is left exactly as typed.
    wanted = (tag or "").strip() or naming.prefixed(s, "event",
                                                    display_name or "")
    if wanted:
        occ.tag_id = _claim_tag(ctx, wanted).id
    s.flush()
    # On the TAG, like a subject's and a place's.
    tagcatalog.describe(ctx, occ.tag_id,
                        comment=(comment or "").strip() or None)
    if parent_id is not None:
        set_parent(ctx, occ, parent_id)
    ctx.log(action=actions.CREATE_EVENT, entity_type="event", entity_id=occ.id,
            summary="Added the event {name}",
            summary_vars={"name": label(ctx, occ)},
            data={"occasion_id": occ.id, "tag_id": occ.tag_id,
                  **state(ctx, occ)})
    return occ


def update(ctx: Ctx, event_id: int, *, tag: Optional[str] = None,
           display_name: Optional[str] = None, comment: Optional[str] = None,
           parent_id: Optional[int] = None, clear_parent: bool = False,
           start_date: Optional[int] = None, end_date: Optional[int] = None,
           places: Optional[list[int]] = None) -> Occasion:
    s = ctx.session
    occ = s.get(Occasion, event_id)
    if occ is None:
        raise NotFound("event not found", code="event_not_found")
    check_span(start_date if start_date is not None else occ.start_date,
               end_date if end_date is not None else occ.end_date)
    before = state(ctx, occ)
    # Twice, around the mutation: the items carrying the OLD tag need rewriting
    # as much as the ones carrying the new.
    if display_name is not None:
        occ.display_name = display_name.strip()
    if start_date is not None:
        occ.start_date = start_date or None
    if end_date is not None:
        occ.end_date = end_date or None
    if places is not None:
        set_places(ctx, occ, places)
    # AFTER the tag work below would be wrong for a rename (the pair rides on
    # whichever tag is the identity now) and before it is wrong for a fresh
    # one — so it sits here, where the identity is whatever it was, and the
    # rename below carries the words with the row.
    if tag is None:
        tagcatalog.describe(ctx, occ.tag_id, comment=comment)
    if tag is not None:
        wanted = tag.strip()
        current = s.get(Tag, occ.tag_id) if occ.tag_id else None
        if wanted and current is None:
            occ.tag_id = _claim_tag(ctx, wanted).id
        elif wanted and current is not None and wanted != current.name:
            # Renaming the identity tag is an ordinary tag rename, so it logs
            # the tag's own revertible event.
            tagcatalog.update(ctx, current.id, name=wanted)
        tagcatalog.describe(ctx, occ.tag_id, comment=comment)
    # LAST, like a place's: an event named in this same call has only just
    # gained the tag the implication rides on.
    if clear_parent:
        set_parent(ctx, occ, None)
    elif parent_id is not None:
        set_parent(ctx, occ, parent_id)
    s.flush()
    after = state(ctx, occ)
    if after != before:
        ctx.log(action=actions.EDIT_EVENT, entity_type="event",
                entity_id=occ.id,
                summary="Edited the event {name}",
                summary_vars={"name": label(ctx, occ)},
                data={"occasion_id": occ.id, "tag_id": occ.tag_id, **after,
                      **{f"old_{k}": v for k, v in before.items()}})
    return occ


def delete_event(ctx: Ctx, event_id: int, *, with_tag: bool = False):
    """Drop the event data, keeping its tag — the tag is an ordinary tag and
    the pictures were still taken at whatever it was. ``with_tag`` deletes that
    too. Returns the delete event; the payload carries the tag by NAME as
    well as by id (the subject delete's fresh-rowid lesson)."""
    s = ctx.session
    occ = s.get(Occasion, event_id)
    if occ is None:
        raise NotFound("event not found", code="event_not_found")
    tag_id = occ.tag_id
    children = list(s.execute(
        select(Occasion).where(Occasion.parent_id == occ.id)).scalars())
    ev = ctx.log(action=actions.DELETE_EVENT, entity_type="event", entity_id=occ.id,
            summary="Deleted the event {name}",
            summary_vars={"name": label(ctx, occ)},
            data={"occasion_id": occ.id, "tag_id": tag_id,
                  "tag_name": (s.get(Tag, tag_id).name if tag_id else ""),
                  # What was INSIDE it, so the revert can put the tree back;
                  # the column alone would SET NULL and forget.
                  **({"child_ids": [c.id for c in children]} if children else {}),
                  **state(ctx, occ)})
    # The parent link is TWO things (the column and the implication between
    # the identity tags), and deleting the row only takes the column — every
    # child's tag would go on implying the dead event's tag, which survives
    # as an ordinary tag. Unlink through `set_parent`, so both halves go.
    for child in children:
        set_parent(ctx, child, None)
    if occ.parent_id is not None:
        set_parent(ctx, occ, None)
    s.delete(occ)
    s.flush()
    if with_tag and tag_id is not None:
        tagcatalog.delete_tag(ctx, tag_id)
    return ev


# ---- dismissals -------------------------------------------------------------


def dismiss_place(ctx: Ctx, item_id: int, location_id: int, *,
                  via_occasion_id: Optional[int] = None) -> None:
    """"Not there." Keyed on (item, place) and nothing else, so editing the
    event that offered it cannot resurrect it and a second event at the same
    venue does not re-ask."""
    s = ctx.session
    loc = s.get(Location, location_id)
    if loc is None or s.get(Item, item_id) is None:
        raise NotFound("not found", code="not_found")
    exists = s.execute(select(ItemPlaceDismissal).where(
        ItemPlaceDismissal.item_id == item_id,
        ItemPlaceDismissal.location_id == location_id,
    )).scalars().first()
    if exists is None:
        s.add(ItemPlaceDismissal(item_id=item_id, location_id=location_id,
                                 via_occasion_id=via_occasion_id))
        s.flush()
        touch_items(s, [item_id])
        tag = s.get(Tag, loc.tag_id) if loc.tag_id else None
        ctx.log(action=actions.DISMISS_PLACE, entity_type="item",
                entity_id=item_id,
                summary=("Not at {place}" if tag else "Not at that place"),
                summary_vars={"place": tag.name} if tag else None,
                data={"item_id": item_id, "location_id": location_id,
                      "place_tag": tag.name if tag else "",
                      "via_occasion_id": via_occasion_id})


def dismiss_event(ctx: Ctx, item_id: int, occasion_id: int) -> None:
    s = ctx.session
    occ = s.get(Occasion, occasion_id)
    if occ is None or s.get(Item, item_id) is None:
        raise NotFound("not found", code="not_found")
    exists = s.execute(select(ItemOccasionDismissal).where(
        ItemOccasionDismissal.item_id == item_id,
        ItemOccasionDismissal.occasion_id == occasion_id,
    )).scalars().first()
    if exists is None:
        s.add(ItemOccasionDismissal(item_id=item_id, occasion_id=occasion_id))
        s.flush()
        touch_items(s, [item_id])
        ctx.log(action=actions.DISMISS_EVENT, entity_type="item",
                entity_id=item_id,
                summary="Not from {name}",
                summary_vars={"name": label(ctx, occ)},
                data={"item_id": item_id, "occasion_id": occasion_id,
                      "event_tag": (s.get(Tag, occ.tag_id).name
                                    if occ.tag_id else "")})
