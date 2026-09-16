"""Places — where a picture was taken.

Location data on a TAG, the same trick a subject uses. A place is an address
(ONE free text line — see :class:`db.Location`), a coordinate pair, and the
place it is IN.

**Containment is a PARENT now, and the parent is an implication.** It used to
live in the address components — a picture tagged `shibuya_crossing` answered
"in Tokyo" because that place's record said city=Tokyo — which worked only
while every place carried a full structured address and could never say that
a venue is inside a park inside a city. `set_parent` writes the ordinary
`TagImplication` between the two identity tags instead, so assigning the
child assigns the parents and search, counts, facets, training and the item
dict learn nothing new. The column is the TREE; the implication is what it means.

A place with no tag is the other case: a bare GPS pair off a photograph's EXIF,
which has no name because there is no geocoder here. Those are the only ones
that need `ItemLocation`, and naming one moves those rows onto the minted tag.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from ..db import (
    ItemLocation, ItemTag, Location, Tag, touch_items,
)
from . import actions, naming, tagcatalog
from .context import Ctx
from .errors import Conflict, Invalid, NotFound

def label(ctx: Ctx, place: Location) -> str:
    tag = ctx.session.get(Tag, place.tag_id) if place.tag_id else None
    if tag is not None:
        return tag.name
    return (place.name
            or (f"{place.lat:.4f}, {place.lon:.4f}" if place.lat is not None else "")
            or f"place #{place.id}")


def set_parent(ctx: Ctx, place: Location, parent_id: Optional[int]) -> None:
    """Put a place INSIDE another, or take it out of one.

    Two things happen, and only one of them is this module's own: the column
    moves (that is the tree the list draws), and the identity tags gain or
    lose an ordinary IMPLICATION (that is what "assigning a place implies its
    parents" means, and it is the machinery the whole app already reads).

    A cycle is refused here rather than left to the implication layer, because
    the tree is what the refusal is about — and a place cannot be its own
    parent however few tags are involved.
    """
    s = ctx.session
    if parent_id is not None:
        if parent_id == place.id:
            raise Invalid("a place cannot be inside itself", code="place_cycle")
        walk = s.get(Location, parent_id)
        if walk is None:
            raise NotFound("place not found", code="place_not_found")
        seen = {place.id}
        while walk is not None:
            if walk.id in seen:
                raise Invalid("that would put a place inside itself",
                              code="place_cycle")
            seen.add(walk.id)
            walk = s.get(Location, walk.parent_id) if walk.parent_id else None
    old = s.get(Location, place.parent_id) if place.parent_id else None
    place.parent_id = parent_id
    new = s.get(Location, parent_id) if parent_id else None
    _reparent_tag(ctx, place, old, new)


def _reparent_tag(ctx: Ctx, child, old, new) -> None:
    """Move the implication that carries the containment.

    Only ever between two NAMED records: an unnamed place has no tag, so
    there is nothing to imply — and nothing is lost, because an unnamed place
    is on its items directly rather than through a tag.
    """
    s = ctx.session
    if child.tag_id is None:
        return
    if old is not None and old.tag_id is not None:
        target = s.get(Tag, old.tag_id)
        if target is not None:
            tagcatalog.remove_implication(ctx, child.tag_id, target.name)
    if new is not None and new.tag_id is not None:
        target = s.get(Tag, new.tag_id)
        if target is not None:
            tagcatalog.add_implication(ctx, child.tag_id, target.name)


def create(ctx: Ctx, *, tag: str = "", name: str = "",
           comment: str = "",
           parent_id: Optional[int] = None,
           lat: Optional[float] = None,
           lon: Optional[float] = None) -> Location:
    """Create a place, minting its identity tag unless it is an unnamed one."""
    s = ctx.session
    if not (tag or "").strip() and not (name or "").strip() \
            and lat is None and lon is None:
        # Nothing to find it by again — the form refuses this; the API must
        # too, or the Places list grows an italic "unnamed" row with nothing
        # in it.
        raise Invalid("a place needs a name, a tag or coordinates",
                      code="place_empty")
    place = Location(name=(name or "").strip(), lat=lat, lon=lon)
    s.add(place)
    s.flush()
    # The prefix applies only where the slug is INVENTED — a tag typed by hand
    # is exactly what was asked for. Same rule as a subject's.
    wanted = (tag or "").strip() or naming.prefixed(s, "place", name or "")
    if wanted:
        row = s.execute(select(Tag).where(Tag.name == wanted)).scalars().first()
        if row is None:
            row = Tag(name=wanted)
            s.add(row)
            s.flush()
        elif s.execute(select(Location).where(Location.tag_id == row.id)
                       ).scalars().first() is not None:
            raise Conflict("that tag is already a place", code="tag_is_a_place")
        place.tag_id = row.id
    s.flush()
    # The comment lives on the TAG; an UNNAMED place (a bare GPS fix) has
    # none, and `describe` refuses rather than dropping the words silently.
    tagcatalog.describe(ctx, place.tag_id,
                        comment=(comment or "").strip() or None)
    # AFTER the tag: the containment is an implication between identity tags,
    # so a place gets its parent once it has a tag to carry one.
    if parent_id is not None:
        set_parent(ctx, place, parent_id)
    ctx.log(action=actions.CREATE_PLACE, entity_type="place",
            entity_id=place.id, summary="Added the place {name}",
            summary_vars={"name": label(ctx, place)},
            data={"place_id": place.id, "tag_id": place.tag_id,
                  "name": place.name, "parent_id": place.parent_id,
                  "lat": place.lat, "lon": place.lon})
    return place


def update(ctx: Ctx, place_id: int, *, tag: Optional[str] = None,
           name: Optional[str] = None,
           comment: Optional[str] = None,
           parent_id: Optional[int] = None,
           clear_parent: bool = False,
           lat: Optional[float] = None,
           lon: Optional[float] = None,
           clear_coords: bool = False) -> Location:
    s = ctx.session
    place = s.get(Location, place_id)
    if place is None:
        raise NotFound("place not found", code="place_not_found")
    before = {"name": place.name or "",
              "lat": place.lat, "lon": place.lon,
              "parent_id": place.parent_id}
    tagcatalog.describe(ctx, place.tag_id, comment=comment)
    if name is not None:
        place.name = name.strip()
    if clear_coords:
        # Emptying the field used to keep the old pair silently: None is what
        # "not mentioned" looks like, so the removal needs a flag of its own.
        place.lat, place.lon = None, None
    elif lat is not None or lon is not None:
        place.lat, place.lon = lat, lon
    if tag is not None:
        _set_identity_tag(ctx, place, tag)
    # AFTER the tag, for the same reason `create` does it last: a place named
    # in this same call has only just gained the tag the implication rides on.
    if clear_parent:
        set_parent(ctx, place, None)
    elif parent_id is not None:
        set_parent(ctx, place, parent_id)
    s.flush()
    after = {"name": place.name or "",
             "lat": place.lat, "lon": place.lon,
             "parent_id": place.parent_id}
    if after != before:
        ctx.log(action=actions.EDIT_PLACE, entity_type="place",
                entity_id=place.id,
                summary="Edited the place {name}",
                summary_vars={"name": label(ctx, place)},
                data={"place_id": place.id, **after,
                      **{f"old_{k}": v for k, v in before.items()}})
    return place


def _set_identity_tag(ctx: Ctx, place: Location, tag: str) -> None:
    s = ctx.session
    wanted = tag.strip()
    current = s.get(Tag, place.tag_id) if place.tag_id else None
    if wanted and current is None:
        # Naming an unnamed place: mint the tag, then move every item pinned to
        # it onto that tag — the same flow as naming a face.
        row = s.execute(select(Tag).where(Tag.name == wanted)).scalars().first()
        if row is None:
            row = Tag(name=wanted)
            s.add(row)
            s.flush()
        elif s.execute(select(Location).where(Location.tag_id == row.id)
                       ).scalars().first() is not None:
            # The same refusal `create` makes: two Location rows on one tag is
            # a state the search map and the delete-revert both assume away.
            raise Conflict("that tag is already a place",
                           code="tag_is_a_place")
        place.tag_id = row.id
        pinned = list(s.execute(select(ItemLocation).where(
            ItemLocation.location_id == place.id)).scalars().all())
        moved: list[int] = []
        for pin in pinned:
            exists = s.execute(select(ItemTag).where(
                ItemTag.item_id == pin.item_id, ItemTag.tag_id == row.id
            )).scalars().first()
            if exists is None:
                s.add(ItemTag(item_id=pin.item_id, tag_id=row.id,
                              negative=False))
            moved.append(pin.item_id)
            s.delete(pin)
        if moved:
            s.flush()
            touch_items(s, moved)
        ctx.log(action=actions.NAME_PLACE, entity_type="place",
                entity_id=place.id,
                summary=("Named the place {name}"
                         + (", on {items} items" if moved else "")),
                summary_vars={"name": row.name, "items": len(moved)},
                data={"place_id": place.id, "tag_id": row.id, "name": row.name,
                      "backfilled": moved})
    elif wanted and current is not None and wanted != current.name:
        tagcatalog.update(ctx, current.id, name=wanted)


def delete_place(ctx: Ctx, place_id: int, *, with_tag: bool = False):
    """Drop the location data, keeping its tag — the tag is an ordinary tag and
    the pictures were still taken somewhere. ``with_tag`` deletes that too.
    Returns the delete event (the identity cascade hands it to Undo). The
    payload carries the tag by NAME as well as by id — the subject delete's
    lesson: a tag deleted alongside the record comes back under a fresh rowid
    when ITS deletion is reverted, so the stored id names nothing."""
    s = ctx.session
    place = s.get(Location, place_id)
    if place is None:
        raise NotFound("place not found", code="place_not_found")
    tag_id = place.tag_id
    ev = ctx.log(action=actions.DELETE_PLACE, entity_type="place",
            entity_id=place.id,
            summary="Deleted the place {name}",
            summary_vars={"name": label(ctx, place)},
            data={"place_id": place.id, "tag_id": tag_id,
                  "tag_name": (s.get(Tag, tag_id).name if tag_id else ""),
                  "name": place.name, "parent_id": place.parent_id,
                  "lat": place.lat, "lon": place.lon})
    s.delete(place)
    s.flush()
    if with_tag and tag_id is not None:
        tagcatalog.delete_tag(ctx, tag_id)
    return ev


# ---- the place the file itself names ----------------------------------------
#
# The importer used to CREATE these outright — a named place from the XMP/IPTC
# city/state/country, an unnamed one from bare GPS — and a crawl of random web
# images filled the Places list with strangers' coordinates. What the file says
# is indexed as ordinary per-file metadata now (`location`, `gps_lat`,
# `gps_lon`); the Places section OFFERS the named claim, and only accepting it
# creates anything. Bare coordinates never mint a place at all any more: the
# map already reads them straight off the metadata (`ops.items.coords_of`),
# and a suggestion reading "create a place at 35.66, 139.70" is not a question
# anybody can answer.


def file_place_of(s, item_id: int) -> Optional[dict]:
    """The place the item's ACTIVE FILE names, as suggestion data, or None.

    A view, never stored: `{"name", "lat", "lon", "place"}` where ``place``
    is the existing named Location with exactly that line (the one accepting
    would reuse), else None (accepting creates it). No line, no suggestion —
    bare GPS is a coordinate, not a place.
    """
    from ..itemmeta import effective_num, effective_text

    line = (effective_text(s, item_id, "location") or "").strip()
    if not line:
        return None
    place = next(
        (p for p in s.execute(
            select(Location).where(Location.name == line)
        ).scalars().all() if p.tag_id is not None), None)
    return {
        "name": line,
        "lat": effective_num(s, item_id, "gps_lat"),
        "lon": effective_num(s, item_id, "gps_lon"),
        "place": place,
    }


def file_place_answered(s, item_id: int, info: dict) -> bool:
    """Whether the file's claim has already been answered — dismissed, or the
    item already carries the place's tag (directly; an implication is not an
    answer to THIS question)."""
    from ..db import ItemFilePlaceDismissal

    if s.execute(select(ItemFilePlaceDismissal).where(
            ItemFilePlaceDismissal.item_id == item_id)).scalars().first():
        return True
    place = info.get("place")
    if place is None or place.tag_id is None:
        return False
    return s.execute(select(ItemTag).where(
        ItemTag.item_id == item_id, ItemTag.tag_id == place.tag_id,
    )).scalars().first() is not None


def adopt_file_place(ctx: Ctx, item_id: int) -> Location:
    """Accept the place the item's file names — the deliberate spelling of
    what the importer used to do silently.

    Creates the place only when no named place carries exactly that line
    (with the configured ``place:`` prefix, via `create` — the importer's old
    minting skipped the prefix, which was its own bug), and assigns the
    identity tag through the ordinary stamp, so both halves log and revert
    as what they are.
    """
    from ..db import Item
    from . import tagassign

    if ctx.session.get(Item, item_id) is None:
        raise NotFound("item not found", code="not_found")
    info = file_place_of(ctx.session, item_id)
    if info is None:
        raise Invalid("this item's file names no place",
                      code="no_file_place")
    place = info["place"]
    if place is None:
        # Named after the finest component, like the importer's minting was —
        # `place:shibuya`, not `place:shibuya_tokyo_tokyo_japan` — but WITH
        # the configured prefix, which the importer always skipped.
        finest = naming.prefixed(ctx.session, "place",
                                 info["name"].split(",")[0])
        try:
            place = create(ctx, tag=finest, name=info["name"],
                           lat=info["lat"], lon=info["lon"])
        except Conflict:
            # The finest component's tag is already another place's identity;
            # fall back to the whole line, which create() derives from.
            place = create(ctx, name=info["name"],
                           lat=info["lat"], lon=info["lon"])
    elif place.lat is None and info["lat"] is not None:
        # The claim carries a fix the place does not have yet — same rule the
        # importer applied.
        place.lat, place.lon = info["lat"], info["lon"]
    tag = ctx.session.get(Tag, place.tag_id)
    tagassign.stamp(ctx, [item_id], [tag.name], [])
    return place


def dismiss_file_place(ctx: Ctx, item_id: int) -> None:
    """"Not there." Keyed on the ITEM alone — one file, one claim about where
    it was taken, one answer — because the suggested place need not exist yet
    and so cannot be keyed on."""
    from ..db import Item, ItemFilePlaceDismissal

    s = ctx.session
    if s.get(Item, item_id) is None:
        raise NotFound("item not found", code="not_found")
    exists = s.execute(select(ItemFilePlaceDismissal).where(
        ItemFilePlaceDismissal.item_id == item_id)).scalars().first()
    if exists is None:
        info = file_place_of(s, item_id)
        s.add(ItemFilePlaceDismissal(item_id=item_id))
        s.flush()
        touch_items(s, [item_id])
        where = (info or {}).get("name") or ""
        # Two templates, not one with an English fallback stuffed into the
        # variable — a slot cannot be translated (the dismiss_place rule).
        ctx.log(action=actions.DISMISS_FILE_PLACE, entity_type="item",
                entity_id=item_id,
                summary=("Not at {place}" if where else "Not at that place"),
                summary_vars={"place": where} if where else None,
                data={"item_id": item_id})
