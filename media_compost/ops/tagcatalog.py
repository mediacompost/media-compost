"""The tag table itself: names, comments, aliases, implications, merge, delete.

Everything here is about a Tag ROW. What an item carries is
:mod:`media_compost.ops.tagassign`.

The one thing in this module that nothing else may work around is
:func:`get_or_create`, which **redirects an alias to its target**. A caller
that inserts an `ItemTag` against a name it looked up itself will happily
assign the alias row, and an alias assigned directly is a tag that search,
counts and training all disagree about. Every assignment path goes through
here.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import delete, func, select

from .. import tagname
from ..db import (
    Event, GroupTag, ItemTag, ItemTagPlacement, Location, Occasion, Subject,
    Tag, TagImplication, TagSetCategory, chunked,
)
from ..resolve import tag_implications
from . import actions
from .context import Ctx
from .errors import Conflict, Invalid, NotFound, Refused

# ---- names ------------------------------------------------------------------


def check_name(name: str) -> str:
    """A typed tag name, or a refusal saying what is wrong with it.

    REFUSED rather than quietly fixed, which is what the space rule has always
    done: the field normalizes as you type (`tags.ts: sanitizeTagInput`), so
    anything that reaches here malformed came from a script, and silently
    storing something else is how a caller ends up with a tag it cannot find
    again. `tagname.normalize` is the one definition of the shape.
    """
    name = name.strip()
    if not name or " " in name:
        raise Invalid("tag names cannot contain spaces", code="tag_name_spaces")
    if not tagname.is_normalized(name):
        raise Invalid(
            f"a tag name holds no whitespace — try {tagname.normalize(name)!r}",
            code="tag_name_shape",
        )
    return name


def get_or_create_raw(ctx: Ctx, name: str) -> Tag:
    """The tag row named ``name`` (created if new), *without* alias resolution."""
    name = check_name(name)
    s = ctx.session
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if not tag:
        tag = Tag(name=name)
        s.add(tag)
        s.flush()
    return tag


def get_or_create(ctx: Ctx, name: str) -> Tag:
    """As :func:`get_or_create_raw`, but assigning an alias resolves to the
    linked (target) tag — so an alias name is never assigned directly.

    This is every ASSIGNMENT path's door, and what a ranking used to mint
    passes through it like any other name now: a ranking writes no rows of
    its own, so there is no second kind of assignment to tell apart.

    **AND IT IS THE ONE PLACE A TAG SET WRITES INTO THE LIBRARY.** A set is
    read-only advice (`ops/tagsets.py`) until a name of its is ASSIGNED;
    then, and only when the row is being CREATED here, two things the set
    says are honoured: a name the enabled sets call an ALIAS creates and
    returns the canonical instead (the same redirect a library alias gets,
    one step earlier), the names the set says the tag IMPLIES are minted
    and linked as ordinary `TagImplication`s (each its own logged
    `add_tag_implication`, so the log says what happened and the undo takes
    it back), and what the set says the tag IS — its comment, and whether it
    is a subject, a place or an event — is written as the ordinary logged
    records (`apply_set_records`), and the META TAGS it says the name
    carries go on as ordinary logged assignments
    (`apply_set_meta_tags`). An existing tag is left exactly as it is — the set never
    re-describes a library that already has an answer — and `tagcatalog.
    create` (the Tags tab's explicit Create) takes neither step: a name typed
    into the catalog is exactly what was asked for."""
    tag, created = _row_for(ctx, name)
    if created:
        _mint_set_implications(ctx, tag)
        # PARENTS TOO at the door: a place the set says is inside another is
        # not a place standing in nothing, and this is the one moment the
        # whole chain can arrive with it.
        apply_set_records(ctx, tag, parents=True)
        apply_set_meta_tags(ctx, tag)
    if tag.alias_of_id is not None:
        target = ctx.session.get(Tag, tag.alias_of_id)
        if target is not None:
            return target
    return tag


def _row_for(ctx: Ctx, name: str) -> tuple[Tag, bool]:
    """The row named ``name``, made when new — with the sets' ALIAS redirect
    honoured and nothing else. Returns it with whether it was just created,
    which is what says the sets get a say at all.

    Apart from `get_or_create` because the implications are minted BREADTH
    FIRST from the name that was actually assigned (`_mint_set_implications`)
    rather than by recursing through this door, and the walk needs to make a
    row without setting that walk off again.
    """
    name = check_name(name)
    s = ctx.session
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if tag is not None:
        return tag, False
    from . import tagsets as tagsets_ops

    canon = tagsets_ops.canonical_of_alias(s, name)
    if canon and canon.lower() != name.lower():
        return _row_for(ctx, canon)
    tag = Tag(name=name)
    s.add(tag)
    s.flush()
    return tag, True


def _mint_set_implications(ctx: Ctx, root: Tag) -> int:
    """What the enabled sets say the new tag entails, minted and linked —
    and what they say THOSE entail, and so on.

    **BREADTH FIRST FROM THE NAME THAT WAS ASSIGNED**, which is what decides
    where a set's CYCLE breaks. `a → b → c → a` cannot be a library
    implication (`link_implication` refuses the edge that closes a loop), so
    one of the three has to go, and it must not be the one the person's own
    assignment is about: walking depth-first through the door reached `c → a`
    first and left `a → b` — the edge `a` was assigned for — as the refused
    one. Here `a → b` is linked, then `b → c`, and `c → a` is the edge that
    finds the loop already there and is dropped.

    Every edge is an ordinary logged `add_tag_implication`, so the log says
    what happened and the undo takes it back. `names` is passed so the cycle
    check does not read the whole tag table per edge (`link_implication`
    would otherwise select every row of a 200,000-tag catalog to find two
    names); the closure IS re-read per edge, on purpose — the edges this
    walk has already added are exactly what the next one must see.

    Returns HOW MANY edges it added, which is what `sync_set_implications`
    reports back to the person who asked for the sync.
    """
    from . import tagsets as tagsets_ops

    s = ctx.session
    added = 0
    queue: list[Tag] = [root]
    seen = {root.id}
    while queue:
        cur = queue.pop(0)
        for implied in tagsets_ops.implied_names_for(s, cur.name):
            try:
                target, created = _row_for(ctx, implied)
            except Invalid:
                continue
            # A name the LIBRARY calls an alias entails what its target does
            # — the same redirect assigning it would take. An entry that
            # implies its own alias therefore lands on itself and is skipped.
            if target.alias_of_id is not None:
                target = s.get(Tag, target.alias_of_id) or target
            if target.id == cur.id:
                continue
            if link_implication(ctx, cur.id, target.id,
                                names={cur.id: cur.name, target.id: target.name}):
                added += 1
                ctx.log(action=actions.ADD_TAG_IMPLICATION, entity_type="tag",
                        entity_id=cur.id, summary="{tag} now implies {target}",
                        summary_vars={"tag": cur.name, "target": target.name},
                        data={"tag_id": cur.id, "name": cur.name,
                              "implies": target.name})
            if created and target.id not in seen:
                seen.add(target.id)
                queue.append(target)
    return added


def set_hidden(ctx: Ctx, names: Sequence[str], hidden: bool) -> list[str]:
    """Keep these tags out of the AUTOCOMPLETE, or put them back.

    The tag is untouched in every other way: it assigns, it searches, it
    counts, and the Tags tab lists it. It simply stops being SUGGESTED — a
    booru dump puts a hundred thousand names in front of every field
    somebody types in, while most of a library's own work happens in a few
    hundred of them, and this is how the rest get out of the way without
    being deleted.

    Returns the names that actually MOVED, and logs only those: hiding what
    is already hidden is not an event, and a revert of it would put back a
    state nothing left.
    """
    s = ctx.session
    moved: list[str] = []
    for name in dict.fromkeys(n for n in names if n):
        tag = s.execute(select(Tag).where(
            Tag.lname == name.strip().lower())).scalars().first()
        if tag is None or bool(tag.hidden) == bool(hidden):
            continue
        tag.hidden = bool(hidden)
        moved.append(tag.name)
    if not moved:
        return []
    s.flush()
    ctx.log(action=actions.SET_TAG_HIDDEN, entity_type="tag",
            entity_id=None,
            summary=("Hid {n} tags from the autocomplete" if hidden
                     else "Put {n} tags back in the autocomplete"),
            summary_vars={"n": str(len(moved))},
            data={"names": moved, "hidden": bool(hidden)})
    return moved


def set_hidden_namespaces(ctx: Ctx, names: Sequence[str]) -> list[str]:
    """The WHOLE list of namespaces kept out of the autocomplete.

    A namespace is the text before a tag name's first colon and nothing
    else — no column, no table — so this is a setting, and the event
    carries the whole list before and after: what a revert has to put back
    is the list, not a row.

    Hiding a namespace hides the tags in it as they are MADE as well as the
    ones there now, which is the point: a dump's `artist:` names keep
    arriving.
    """
    from .. import prefs
    from ..db import get_setting, set_setting

    s = ctx.session
    before = prefs.read_hidden_namespaces(s)
    after: list[str] = []
    for n in names:
        clean = str(n or "").strip().lower().rstrip(":")
        if clean and clean not in after:
            after.append(clean)
    if after == before:
        return before
    import json as _json

    cur = _json.loads(get_setting(s, prefs.PREFS_GLOBAL) or "{}")
    cur["hidden_namespaces"] = after
    set_setting(s, prefs.PREFS_GLOBAL, _json.dumps(cur))
    s.flush()
    ctx.log(action=actions.SET_HIDDEN_NAMESPACES, entity_type="tag",
            entity_id=None,
            summary="Changed which namespaces the autocomplete offers",
            summary_vars={},
            data={"before": before, "after": after})
    return after


def add_to_library(ctx: Ctx, names: Sequence[str]) -> dict[str, int]:
    """Put these names in the library's own tag list, through the DOOR.

    A tag set is advice about tags, and until a tag exists there is nothing
    for the advice to be about: a row for a name the library has never
    heard of can say what it implies, but nothing will act on it and
    nothing is out of sync. This is the verb that makes it real, asked for
    from the row itself.

    It goes through `get_or_create` and NOT through `create`, which is the
    whole point: the door is the one place a set writes into the library,
    so the tag arrives with what its set says about it — a name the sets
    call an alias creates the CANONICAL tag instead, and the entry's
    implied names are minted and linked as it is made. Adding it any other
    way would produce a bare tag that the set's own row then reports as
    behind.

    The creation is LOGGED here, unlike the door's usual implicit one: there
    it is a side effect of an assignment that logs its own event, and here
    it IS the action. A name the library already has is skipped rather than
    refused — over a selection, that is the only reading that works.
    """
    s = ctx.session
    out = {"added": 0, "skipped": 0}
    for name in dict.fromkeys(n for n in names if n):
        clean = check_name(name)
        if s.execute(select(Tag).where(Tag.lname == clean.lower())
                     ).scalars().first() is not None:
            out["skipped"] += 1
            continue
        tag = get_or_create(ctx, clean)
        s.flush()
        ctx.log(action=actions.CREATE_TAG, entity_type="tag", entity_id=tag.id,
                summary="Created tag {name}", summary_vars={"name": tag.name},
                data={"tag_id": tag.id, "name": tag.name, "alias_of": None,
                      "implies": []})
        out["added"] += 1
    return out


def sync_set_implications(ctx: Ctx, names: Sequence[str], *,
                          replace: bool = False) -> dict[str, int]:
    """Make the library entail what the enabled sets say these tags entail.

    THE DOOR ONLY EVER SPEAKS ONCE. A set's implications are minted when
    `get_or_create` CREATES the tag and never again, which is right for the
    door — a set may not re-describe a library that already has an answer —
    and leaves nowhere at all to say "the set has changed its mind, apply
    it". A tag the library had before the set arrived, and an entry that
    gained an `implies` after its tag was in use, both sit there entailing
    nothing the set says. This is that verb, asked for by hand, over the
    names the person picked in the list.

    Two endings, because there are two things "sync" can honestly mean.
    APPEND adds the edges the set names and touches nothing else: whatever
    else the tag entails was somebody's own decision or another set's, and a
    sync is not a reason to lose it. REPLACE makes the tag's implications
    exactly what the sets say — every DIRECT edge they do not name is
    removed first, then the walk adds theirs, so a set that has dropped an
    implication can be followed rather than only added to. Both are made of
    the ordinary logged primitives, so the whole sync reverts.

    A name the library does not have is SKIPPED, not created: an unassigned
    tag is not out of sync with anything, and minting the catalog's worth of
    them is the opposite of what was asked. So is a name whose tag no set
    speaks for — under REPLACE that would read as "the sets say nothing,
    therefore remove everything", which is not what an empty answer means.
    """
    from . import tagsets as tagsets_ops

    s = ctx.session
    out = {"tags": 0, "added": 0, "removed": 0, "skipped": 0}
    for name in dict.fromkeys(n for n in names if n):
        tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
        if tag is not None and tag.alias_of_id is not None:
            # The tag an assignment would land on is the one that carries the
            # implications, exactly as at the door.
            tag = s.get(Tag, tag.alias_of_id) or tag
        wanted = tagsets_ops.implied_names_for(s, tag.name) if tag else []
        if tag is None or not wanted:
            out["skipped"] += 1
            continue
        out["tags"] += 1
        if replace:
            keep = {n.lower() for n in wanted}
            for surplus in implied_names(s, [tag.id]).get(tag.id, []):
                if surplus.lower() not in keep:
                    remove_implication(ctx, tag.id, surplus)
                    out["removed"] += 1
        out["added"] += _mint_set_implications(ctx, tag)
    return out


def apply_set_records(ctx: Ctx, tag: Tag, *, replace: bool = False,
                     parents: bool = False,
                     _seen: frozenset[str] = frozenset()) -> int:
    """What the enabled sets say this tag IS, written into the library.

    The door's second half and the sync verb's engine. Everything it makes
    is an ORDINARY record — a comment on the tag, a `Subject`, a `Location`,
    an `Occasion` — through the ops that make those, so each is logged and
    each reverts. A tag set holds no records of its own; it says what the
    library's should be, exactly as it says what a name entails.

    **WHAT THE LIBRARY ALREADY HAS WINS.** A tag that carries a comment is
    not re-described, and one that is already somebody is not made into a
    second person. `replace` is the same override the implication sync has,
    and it is deliberately NOT "delete and rewrite": it fills in the fields
    a record is missing and leaves the rest, since a record somebody edited
    by hand is an answer and the set is advice.

    **`parents` IS ITS OWN ANSWER.** A place's parent (and an event's) is
    another tag with a record of its own, so following one means MINTING
    that tag — and its parent, and so on up. When the door is making this
    record for the first time that is exactly right: Shibuya is in Tokyo is
    in Japan, and a set that says so should not leave a place standing in
    nothing. Over a SELECTION of four hundred rows it is a different act —
    it fills the catalog from a dump — which is why the ⋯ menu offers it as
    its own verb and the ordinary sync passes False.

    Returns how many things it wrote.
    """
    from . import events as events_ops
    from . import places as places_ops
    from . import subjects as subjects_ops
    from . import tagsets as tagsets_ops

    s = ctx.session
    said = tagsets_ops.records_for(s, tag.name)
    if not said:
        return 0
    seen = _seen | {tag.name.lower()}
    n = 0
    comment = said.get("comment") or ""
    if comment and (replace or not (tag.comment or "")):
        describe(ctx, tag.id, comment=comment)
        n += 1
    rec = said.get("subject")
    if rec is not None:
        row = s.execute(select(Subject).where(
            Subject.tag_id == tag.id)).scalars().first()
        if row is None:
            subjects_ops.create(ctx, rec.get("name") or tag.name,
                                since_date=rec.get("since"), tag=tag.name)
            n += 1
        elif replace:
            subjects_ops.update(ctx, row.id,
                                display_name=rec.get("name") or None,
                                since_date=rec.get("since"))
            n += 1
    rec = said.get("place")
    if rec is not None:
        row = s.execute(select(Location).where(
            Location.tag_id == tag.id)).scalars().first()
        parent = _record_parent(ctx, "place", Location, rec.get("parent"),
                                make=parents, seen=seen)
        if row is None:
            places_ops.create(ctx, tag=tag.name,
                              name=rec.get("name") or "",
                              lat=rec.get("lat"), lon=rec.get("lon"),
                              parent_id=parent)
            n += 1
        elif replace:
            places_ops.update(ctx, row.id, name=rec.get("name"),
                              lat=rec.get("lat"), lon=rec.get("lon"),
                              parent_id=parent)
            n += 1
    rec = said.get("event")
    if rec is not None:
        row = s.execute(select(Occasion).where(
            Occasion.tag_id == tag.id)).scalars().first()
        parent = _record_parent(ctx, "event", Occasion, rec.get("parent"),
                                make=parents, seen=seen)
        if row is None:
            events_ops.create(ctx, tag=tag.name,
                              display_name=rec.get("name") or tag.name,
                              start_date=rec.get("start"),
                              end_date=rec.get("end"), parent_id=parent)
            n += 1
        elif replace:
            events_ops.update(ctx, row.id,
                              display_name=rec.get("name") or None,
                              start_date=rec.get("start"),
                              end_date=rec.get("end"), parent_id=parent)
            n += 1
    return n


def _record_parent(ctx: Ctx, kind: str, model, name: Optional[str], *,
                   make: bool, seen: frozenset[str]) -> Optional[int]:
    """The id of the record ``name``'s tag owns — made, with its own parent
    above it, when ``make``.

    Without ``make`` this is a lookup and nothing else: a parent the library
    has never heard of yields None, the rule the implication sync keeps for
    a name the library lacks. With it, the chain is followed all the way up,
    each level through the ordinary door and the ordinary record ops, so
    "Shibuya is in Tokyo is in Japan" arrives as three places and two
    containment implications rather than one place standing in nothing.

    ``seen`` is what stops a RING — a set that says a is in b and b is in a
    — and it drops the edge furthest from the name that was asked for,
    exactly as `_mint_set_implications` does one kind of advice along.
    """
    s = ctx.session
    if not name or name.lower() in seen:
        return None
    tag = s.execute(select(Tag).where(
        Tag.lname == name.lower())).scalars().first()
    if tag is None:
        if not make:
            return None
        # THE ORDINARY DOOR, minus the records: this call is already inside
        # `apply_set_records`, and re-entering it here would lose the `seen`
        # the ring guard is carried in.
        tag, created = _row_for(ctx, name)
        if created:
            _mint_set_implications(ctx, tag)
        if tag.alias_of_id is not None:
            tag = s.get(Tag, tag.alias_of_id) or tag
    row = s.execute(select(model).where(
        model.tag_id == tag.id)).scalars().first()
    if row is None and make:
        apply_set_records(ctx, tag, parents=True, _seen=seen)
        row = s.execute(select(model).where(
            model.tag_id == tag.id)).scalars().first()
    return None if row is None else row.id


def sync_set_records(ctx: Ctx, names: Sequence[str], *,
                     replace: bool = False) -> dict[str, int]:
    """Make the library carry what the enabled sets say these tags ARE.

    `sync_set_implications`' sibling, and for its reason: the door speaks
    once, when it creates the tag, so a tag the library already had — or an
    entry that gained a record after its tag was in use — sits there being
    nothing the set says it is. This is that verb, asked for by hand over
    the names somebody picked in the list.

    A name the library does not have is SKIPPED, never created: an
    unassigned tag is not out of sync with anything, and minting a whole
    dump's worth of subjects is the opposite of what was asked.
    """
    s = ctx.session
    out = {"tags": 0, "written": 0, "skipped": 0}
    for name in dict.fromkeys(n for n in names if n):
        tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
        if tag is not None and tag.alias_of_id is not None:
            # The tag an assignment would land on is the one that carries
            # the record, exactly as at the door.
            tag = s.get(Tag, tag.alias_of_id) or tag
        if tag is None:
            out["skipped"] += 1
            continue
        wrote = apply_set_records(ctx, tag, replace=replace)
        if wrote:
            out["tags"] += 1
            out["written"] += wrote
        else:
            out["skipped"] += 1
    return out


def sync_set_advice(ctx: Ctx, names: Sequence[str], *,
                    replace: bool = False) -> dict[str, int]:
    """EVERYTHING THE SETS SAY ABOUT THESE TAGS, in one verb.

    The door applies a set's advice at one moment — when it creates the tag
    — and it applies all of it: what the name entails, what it is, the line
    it carries. A tag that was already in the library, or an entry edited
    after its tag went into use, has heard none of it, and asking for that
    in two menu entries made a person decide between two halves of one
    thing. This is the whole of it; `replace` means what it means in both
    halves (the implications become exactly what the sets name, and a
    record's empty fields are filled in over what the library has).

    Parents are NOT in it — see `sync_set_parents`.
    """
    imp = sync_set_implications(ctx, names, replace=replace)
    rec = sync_set_records(ctx, names, replace=replace)
    return {
        # A tag either heard something or it did not; the two halves count
        # the same names, so the totals cannot simply be added.
        "tags": max(imp["tags"], rec["tags"]),
        "added": imp["added"] + rec["written"],
        "removed": imp["removed"],
        "skipped": min(imp["skipped"], rec["skipped"]),
    }


def sync_set_parents(ctx: Ctx, names: Sequence[str], *,
                     replace: bool = False) -> dict[str, int]:
    """Build the parent hierarchy the sets name above these tags' records.

    ITS OWN VERB, and that is the point. Applying what a set says a tag IS
    writes one record about one tag; following its PARENT mints another
    tag, and that one's parent, and so on up — which over a selection of
    four hundred rows is filling the catalog from a dump rather than
    describing what was picked. So the ordinary sync leaves parents alone
    and this is where somebody asks for them.

    `append` gives a record with no parent the one the set names; `replace`
    also re-points one that has a different parent, which is how a set that
    has moved a place is followed.
    """
    from . import events as events_ops
    from . import places as places_ops
    from . import tagsets as tagsets_ops

    s = ctx.session
    out = {"tags": 0, "written": 0, "skipped": 0}
    for name in dict.fromkeys(n for n in names if n):
        tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
        if tag is not None and tag.alias_of_id is not None:
            tag = s.get(Tag, tag.alias_of_id) or tag
        if tag is None:
            out["skipped"] += 1
            continue
        said = tagsets_ops.records_for(s, tag.name)
        wrote = 0
        for kind, model, ops_mod in (("place", Location, places_ops),
                                     ("event", Occasion, events_ops)):
            rec = said.get(kind)
            if rec is None or not rec.get("parent"):
                continue
            row = s.execute(select(model).where(
                model.tag_id == tag.id)).scalars().first()
            if row is None:
                # No record to hang a parent on. The other verb makes it.
                continue
            parent = _record_parent(ctx, kind, model, rec["parent"],
                                    make=True,
                                    seen=frozenset({tag.name.lower()}))
            if parent is None or parent == row.parent_id:
                continue
            if row.parent_id is not None and not replace:
                continue
            ops_mod.set_parent(ctx, row, parent)
            wrote += 1
        if wrote:
            out["tags"] += 1
            out["written"] += wrote
        else:
            out["skipped"] += 1
    return out


def apply_set_meta_tags(ctx: Ctx, tag: Tag) -> int:
    """What the enabled sets say the new tag is LABELLED with, put on it.

    The door's third errand, beside `_mint_set_implications` and
    `apply_set_records` and for the same reason: a set that knows
    `hatsune_miku` is a `character` is saying something about the NAME, and
    a library told once per name by hand is a library that never gets told.

    Ordinary logged assignments (`_move_meta_tag`), so the log says what
    happened and the undo takes it back. A label the LIBRARY does not have
    is registered in its own meta namespace first, carrying the set's words
    for it — that row is the only place a meta tag's comment and description
    live. What the library already says about a label is left alone, the
    rule everywhere a set meets an answer that is already there.
    """
    from ..db import LIB_META, LinkTag
    from . import tagsets as tagsets_ops

    s = ctx.session
    n = 0
    for name, comment, description in tagsets_ops.meta_names_for(s, tag.name):
        row = s.execute(select(LinkTag).where(
            LinkTag.name == name, LIB_META)).scalar_one_or_none()
        if row is None and (comment or description):
            s.add(LinkTag(name=name, comment=comment, description=description))
            s.flush()
        if _move_meta_tag(ctx, tag, name) is not None:
            n += 1
    return n


def by_id(ctx: Ctx, tag_id: int) -> Tag:
    tag = ctx.session.get(Tag, tag_id)
    if tag is None:
        raise NotFound("tag not found", code="tag_not_found")
    return tag


# ---- aliases ----------------------------------------------------------------


def set_alias(ctx: Ctx, tag: Tag, target_name: str) -> None:
    """Link ``tag`` as an alias of the tag named ``target_name``. Empty clears
    the link. Guards against self- and chained aliases.

    The target must ALREADY EXIST. An alias is a second name for a tag you
    have, so conjuring the target from a typo produces two useless rows — an
    empty tag and an alias pointing at it — where the user meant to point at
    something real.
    """
    s = ctx.session
    target_name = (target_name or "").strip()
    if not target_name:
        tag.alias_of_id = None
        return
    if target_name == tag.name:
        raise Refused("a tag cannot be an alias of itself", code="alias_self")
    target = s.execute(
        select(Tag).where(Tag.name == target_name)).scalars().first()
    if target is None:
        raise NotFound("no tag named “{name}” to alias to",
                       {"name": target_name}, code="alias_target_missing")
    if target.alias_of_id is not None:
        raise Refused("cannot alias to another alias", code="alias_chain")
    tag.alias_of_id = target.id
    # An alias entails nothing of its own: assigning it redirects to the
    # target, whose implications are the ones that apply.
    s.execute(delete(TagImplication).where(TagImplication.tag_id == tag.id))
    s.flush()


# ---- implications -----------------------------------------------------------


def tags_by_id(session, tag_ids) -> dict[int, Tag]:
    """The tag rows for these ids, keyed by id — CHUNKED.

    The identity lists (subjects, places, events) each pass one tag id per
    ROW, which is the shape that made the tag list hang: an `IN` of a whole
    catalog does not fail on a modern SQLite, it goes quadratic (see
    `db.chunked`). None of these lists is as long as the tag catalog, so
    nobody has hit it here — which is exactly why it wants to be one helper
    rather than the same three lines written five times, each of them a
    place to forget.
    """
    ids = [i for i in tag_ids if i is not None]
    out: dict[int, Tag] = {}
    for chunk in chunked(ids):
        for row in session.execute(
                select(Tag).where(Tag.id.in_(chunk))).scalars().all():
            out[row.id] = row
    return out


def implied_names(session, tag_ids: list[int]) -> dict[int, list[str]]:
    """tag id -> the names it DIRECTLY implies (not the transitive closure —
    the list shows what was actually declared, the way it shows an alias).

    Takes a Session rather than a `Ctx`: it is a pure read with nothing to log
    and no acting user, and the tag-list endpoint calls it without one.
    """
    out: dict[int, list[str]] = {}
    # CHUNKED, like `meta_names` beside it and for a worse reason than the
    # error the rule was written against: the tag-list endpoint passes EVERY
    # tag id, and an `IN` of the whole catalog does not fail on a modern
    # SQLite — its variable limit is 250,000 here, not the 32,766 the rule
    # assumes — it goes quadratic. Measured on a 100,000-tag library: 0.05 s
    # at 90,000 ids and 241 s at 100,000, for the same two rows back. So the
    # failure mode moved from a loud "too many SQL variables" to a listing
    # that appears to hang, which is why this must not be spelled the
    # obvious way.
    for chunk in chunked(tag_ids):
        for tid, name in session.execute(
            select(TagImplication.tag_id, Tag.name)
            .join(Tag, Tag.id == TagImplication.implies_id)
            .where(TagImplication.tag_id.in_(chunk))
            .order_by(Tag.name)
        ).all():
            out.setdefault(tid, []).append(name)
    # One chunk's rows are name-ordered; several chunks concatenate, and a
    # tag's implications all live in the chunk its own id falls in — so the
    # per-tag list is still name-ordered whatever the chunking.
    return out


def _implication(ctx: Ctx, tag: Tag, name: str) -> Tag:
    """``tag`` also entails the tag named ``name`` (created if new).

    Guards mirror the old parent rules, minus the tree: no self-implication,
    no alias on either side (an alias redirects, so it can neither carry nor
    be the target of an implication), and no cycle — the target must not
    already entail this tag, or assigning either would entail both forever.
    """
    s = ctx.session
    name = (name or "").strip()
    if not name:
        raise Invalid("no tag given", code="no_tag")
    if tag.alias_of_id is not None:
        raise Refused(
            "an alias implies nothing — assigning it redirects to its "
            "target, so give the target the implication instead",
            code="alias_implies")
    if name == tag.name:
        raise Refused("a tag cannot imply itself", code="implies_self")
    target = get_or_create_raw(ctx, name)
    if target.alias_of_id is not None:
        raise Refused("a tag cannot imply an alias", code="implies_alias")
    # Would the new edge close a loop? Ask what the target already entails.
    if tag.name in tag_implications(s).get(target.name, set()):
        raise Refused(
            "“{target}” already implies “{tag}” — that would be a loop",
            {"target": target.name, "tag": tag.name}, code="implies_loop")
    exists = s.execute(select(TagImplication).where(
        TagImplication.tag_id == tag.id,
        TagImplication.implies_id == target.id)).scalars().first()
    if exists is None:
        s.add(TagImplication(tag_id=tag.id, implies_id=target.id))
        s.flush()
    return target


def link_implication(ctx: Ctx, tag_id: int, implies_id: int,
                     names: Optional[dict[int, str]] = None,
                     closure: Optional[dict[str, set[str]]] = None) -> bool:
    """Add one implication edge; False when it already exists or would loop.

    ``names``/``closure`` let a bulk caller (merge) compute the tag-name map
    and the transitive closure ONCE instead of per edge. The closure need not
    include edges the same call already added: a cycle that would only close
    through one of them maps onto a pre-existing cycle through the merged tag
    (the new edges are exactly the old tag's), which cannot exist.
    """
    s = ctx.session
    if tag_id == implies_id:
        return False
    if s.execute(select(TagImplication).where(
        TagImplication.tag_id == tag_id, TagImplication.implies_id == implies_id
    )).scalars().first() is not None:
        return False
    if names is None:
        names = dict(s.execute(select(Tag.id, Tag.name)).all())
    if closure is None:
        closure = tag_implications(s)
    a, b = names.get(tag_id), names.get(implies_id)
    if a and b and a in closure.get(b, set()):
        return False  # the other direction exists — this would close a cycle
    s.add(TagImplication(tag_id=tag_id, implies_id=implies_id))
    return True


def add_implication(ctx: Ctx, tag_id: int, name: str) -> list[str]:
    """``tag_id`` also entails ``name``. Returns its implications."""
    tag = by_id(ctx, tag_id)
    # Every item carrying this tag (or anything that entails it) gains a tag,
    # so their sidecars change — collect them BEFORE the edit, since the set
    # is defined by the pre-change relation.
    target = _implication(ctx, tag, name)
    ctx.log(action=actions.ADD_TAG_IMPLICATION, entity_type="tag",
            entity_id=tag.id, summary="{tag} now implies {target}",
            summary_vars={"tag": tag.name, "target": target.name},
            data={"tag_id": tag.id, "name": tag.name, "implies": target.name})
    return implied_names(ctx.session, [tag.id]).get(tag.id, [])


def remove_implication(ctx: Ctx, tag_id: int, name: str) -> list[str]:
    """Stop ``tag_id`` entailing the tag named ``name``."""
    s = ctx.session
    tag = by_id(ctx, tag_id)
    target = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if target is not None:
        s.execute(delete(TagImplication).where(
            TagImplication.tag_id == tag.id,
            TagImplication.implies_id == target.id))
        ctx.log(action=actions.REMOVE_TAG_IMPLICATION, entity_type="tag",
                entity_id=tag.id,
                summary="{tag} no longer implies {target}",
                summary_vars={"tag": tag.name, "target": target.name},
                data={"tag_id": tag.id, "name": tag.name,
                      "implies": target.name})
    return implied_names(ctx.session, [tag.id]).get(tag.id, [])


# ---- create / update --------------------------------------------------------


def create(ctx: Ctx, name: str, *, comment: str = "",
           alias_of: str = "",
           implies: str = "") -> tuple[Tag, Optional[str], list[str]]:
    """A new tag row. Returns it with its resolved alias target and implications."""
    s = ctx.session
    name = check_name(name or "")
    # A ranking's namespace is not a place to put tags by hand.
    # A tag (or alias) can only be created under a name that doesn't already
    # exist — no duplicates, and an alias can't shadow an existing tag's name.
    if s.execute(select(Tag).where(Tag.name == name)).scalars().first() is not None:
        raise Conflict("a tag with that name already exists", code="tag_exists")
    tag = Tag(name=name, comment=comment)
    s.add(tag)
    s.flush()
    alias_name = None
    if alias_of:
        set_alias(ctx, tag, alias_of)
        target = s.get(Tag, tag.alias_of_id) if tag.alias_of_id else None
        alias_name = target.name if target else None
    implied: list[str] = []
    if implies:
        implied = [_implication(ctx, tag, implies).name]
    ctx.log(action=actions.CREATE_TAG, entity_type="tag", entity_id=tag.id,
            summary=("Created alias {name} → {target}" if alias_name
                     else "Created tag {name}"),
            summary_vars={"name": name, "target": alias_name or ""},
            data={"tag_id": tag.id, "name": name, "alias_of": alias_name,
                  "implies": implied})
    return tag, alias_name, implied


def _count_wanted(mode: Optional[str], cur: int, new: int) -> int:
    """What a meta-tag assignment's ``count`` should be after an import row.

    ``mode`` is the dialog's dropdown, and it is the WHOLE rule: ``replace``
    takes the file's number, ``min``/``max`` keep the smaller or the larger
    of the two, and ``keep`` — the default, and what ``None`` means — leaves
    a number that is already there alone. An unset count (0 means unset)
    always takes the file's, whatever the mode, since there is nothing to
    compare it with.

    It does NOT read the text columns' rule (``existing``), and used to:
    ``None`` meant "fill a gap, and replace under overwrite", so one switch
    governed both the words and a number, and the dropdown had to carry a
    "Keep it, unless overwriting" entry — a state of some other control,
    written into this one's list of answers. That switch is about what an
    existing tag's WORDS keep; a count has its own question and its own four
    answers.
    """
    if mode == "replace":
        return new
    if mode == "min":
        return new if not cur else min(cur, new)
    if mode == "max":
        return max(cur, new)
    return new if not cur else cur


def _takes(existing: str, from_file, in_library) -> bool:
    """Does an import row's value win over what the tag already says?

    The text half of :func:`_count_wanted`, and the same shape: ``keep``
    fills a gap, ``update`` takes anything the row actually says, and
    ``replace`` takes the row whatever it says — including an EMPTY value,
    which is how a field the file no longer carries is cleared. A row that
    does not carry the field at all (``None``) is never a clear: the batch
    cannot tell that from "the caller did not mention it".
    """
    if from_file is None:
        return False
    if existing == "replace":
        return True
    if existing == "update":
        return bool(str(from_file).strip())
    return bool(str(from_file).strip()) and not str(in_library or "").strip()


def bulk_upsert(ctx: Ctx, rows, *, existing: str = "keep",
                meta_tags: tuple = (),
                count_meta: str = "",
                count_mode: Optional[str] = None) -> list[dict]:
    """The CSV import's tag table, as ONE operation — a bulk op extracted as
    a bulk op, per the house rule.

    Each ``row`` carries ``name`` plus optional ``comment`` and ``count``
    (``None`` = the file says nothing). There is no ``description``: a tag
    has none of its own (rung v17 — a description is a tag set's). The per-row path
    this replaces was two HTTP requests and two commits per tag; here the
    whole catalog is read ONCE, the missing tags are created in one flush,
    and the caller commits the lot as one transaction. What does NOT change
    is the log: a creation writes the same ``create_tag`` event `create`
    writes, and a change to an existing tag goes through :func:`update`, so
    every event and every revert is exactly the single-call ops'.

    ``existing`` is the import dialog's three-way answer for a tag the
    library ALREADY has: ``keep`` fills in only what it has not said,
    ``update`` takes the file's value wherever the row has one, and
    ``replace`` makes the tag match the row — a field the row carries EMPTY
    is cleared, which is how a re-imported dump drops what it no longer says.
    (A field the row does not carry at all is not touched: the batch cannot
    tell "the file has no such column" from "the caller did not mention it",
    so the dialog sends the empties it means.)

    ``count_meta`` is the dialog's "store the count on" — the ONE meta tag a
    row's ``count`` lands on, as that assignment's own figure ("abc" can
    carry tumblr 50 and twitter 100 at once). Naming it also ASSIGNS the
    meta tag to every counted row, since a count is a fact about an
    assignment. ``count_mode`` is the count's own conflict policy (see
    :func:`_count_wanted`) and reads nothing else — ``existing`` governs the
    text columns and only those. A row
    may also bring per-meta counts of its own (``row.meta_counts``, the
    meta-assignments file's third column), applied the same way.

    ``meta_tags`` is the dialog's "Mark every tag with" — a fact about the
    whole file, so it is a parameter of the batch rather than a field of a
    row. Every tag the batch names is marked (existing tags included, once
    per tag however many rows say it), each addition its own
    ``add_link_tag`` event exactly as :func:`add_meta_tag` writes it. It
    used to be one request per tag, which put the minutes this endpoint
    removed straight back.

    Returns one dict per row — ``{"name", "id", "created", "error"}`` — with
    a refused name reported in place rather than failing the batch.
    """
    s = ctx.session
    # The whole catalog, once, keyed the way the import matches (lowercase).
    # The map is updated as rows create, so a name the file says twice is two
    # rows against one tag — the per-row path's behavior exactly.
    have: dict[str, Tag] = {
        t.name.lower(): t for t in s.execute(select(Tag)).scalars()
    }
    created: list[tuple] = []  # (row, Tag) — events logged after the flush
    out: list[dict] = []
    for row in rows:
        try:
            # A name the catalog refuses is reported per row, like a
            # malformed one — the rest of the batch goes on.
            name = check_name(row.name or "")
        except (Invalid, Refused) as exc:
            out.append({"name": row.name or "", "id": None,
                        "created": False, "error": str(exc)})
            continue
        tag = have.get(name.lower())
        if tag is None:
            tag = Tag(name=name, comment=row.comment or "")
            s.add(tag)
            have[name.lower()] = tag
            entry = {"name": name, "id": None, "created": True, "error": None}
            created.append((name, tag, entry))
            out.append(entry)
            continue
        if tag.id is None:
            # A duplicate name within this batch: the first occurrence made
            # the row and it has no id yet, so the fields merge directly —
            # its create event has not been written either. The entry rides
            # in `created` (marked not-created) so the flush below fills in
            # the id it shares with the first occurrence.
            if _takes(existing, row.comment, tag.comment):
                tag.comment = row.comment or ""
            entry = {"name": name, "id": None, "created": False,
                     "error": None}
            created.append((None, tag, entry))
            out.append(entry)
            continue
        # An existing tag takes the import dialog's keep rule, each change
        # through `update` so it logs and reverts like any hand edit. An
        # alias keeps its emptiness: words on it are refused there anyway.
        changes: dict = {}
        if tag.alias_of_id is None:
            if _takes(existing, row.comment, tag.comment) \
                    and (row.comment or "") != (tag.comment or ""):
                changes["comment"] = row.comment or ""
        if changes:
            update(ctx, tag.id, **changes)
        out.append({"name": name, "id": tag.id, "created": False,
                    "error": None})
    # ONE flush hands out every new id; the events then say what happened,
    # with the payload `create` writes (no alias, no implication — the tag
    # table's columns are already on the row).
    s.flush()
    for name, tag, entry in created:
        entry["id"] = tag.id
        if name is None:
            continue  # an in-batch duplicate: the id, but no second event
        ctx.log(action=actions.CREATE_TAG, entity_type="tag",
                entity_id=tag.id,
                summary="Created tag {name}",
                summary_vars={"name": name, "target": ""},
                data={"tag_id": tag.id, "name": name, "alias_of": None,
                      "implies": []})
    marks = [_meta_name(m) for m in meta_tags if str(m or "").strip()]
    counted = _meta_name(count_meta) if str(count_meta or "").strip() else ""
    # A row may carry marks of its OWN (the meta-assignments file imports
    # through this same batch), so what each tag should end up wearing is the
    # file-wide marks plus whatever its rows said — per tag, once. A counted
    # row additionally wears the count target: a count is a fact about an
    # ASSIGNMENT, so naming a meta tag to count on is assigning it.
    wanted: dict[int, set[str]] = {}
    tag_of: dict[int, Tag] = {}
    # (tag id, meta name) → the folded count this batch asks for. Folded by
    # the count policy itself, so a file saying one tag twice behaves as two
    # single imports would.
    counts_wanted: dict[tuple[int, str], int] = {}

    def _fold(key: tuple[int, str], value: int) -> None:
        value = max(0, int(value))
        if key in counts_wanted:
            if count_mode == "min":
                value = min(counts_wanted[key], value)
            elif count_mode == "max":
                value = max(counts_wanted[key], value)
        counts_wanted[key] = value

    for row, entry in zip(rows, out):
        if entry["id"] is None:
            continue
        tag = have.get(entry["name"].lower())
        if tag is None:
            continue
        row_marks = [_meta_name(m) for m in (row.meta_tags or ())
                     if str(m or "").strip()]
        row_counts = {_meta_name(k): v
                      for k, v in (getattr(row, "meta_counts", None) or {}).items()
                      if str(k or "").strip()}
        count = getattr(row, "count", None)
        if counted and count is not None:
            _fold((entry["id"], counted), int(count))
        for k, v in row_counts.items():
            _fold((entry["id"], k), int(v))
        if marks or row_marks or row_counts \
                or (counted and count is not None):
            tag_of[entry["id"]] = tag
            wanted.setdefault(entry["id"], set()).update(
                marks, row_marks, row_counts,
                [counted] if counted and count is not None else [])
    if wanted:
        from ..db import LIB_META, LinkTag, TagMetaTag

        all_names = sorted(set().union(*wanted.values()))
        # Which (tag, name) pairs already exist — and what each counts — in
        # one pass instead of one probe per tag; only the missing rows are
        # written, each with the event `_move_meta_tag` logs for a single
        # addition.
        existing: dict[tuple[int, str], TagMetaTag] = {}
        for chunk in chunked(list(wanted)):
            for tmt in s.execute(
                select(TagMetaTag).where(
                    TagMetaTag.tag_id.in_(chunk),
                    TagMetaTag.name.in_(all_names))).scalars().all():
                existing[(tmt.tag_id, tmt.name)] = tmt
        for name in all_names:
            # The namespace keeps the name even with no carrier left, so it
            # is registered exactly as a single addition registers it.
            if s.execute(select(LinkTag).where(
                    LinkTag.name == name, LIB_META)).scalar_one_or_none() is None:
                s.add(LinkTag(name=name))
        for tid, want in wanted.items():
            tag = tag_of[tid]
            for name in sorted(want):
                new_count = counts_wanted.get((tid, name))
                row0 = existing.get((tid, name))
                if row0 is None:
                    n = max(0, int(new_count or 0))
                    s.add(TagMetaTag(tag_id=tid, name=name, count=n))
                    ctx.log(action=actions.ADD_LINK_TAG, entity_type="tag",
                            entity_id=tid,
                            summary="Added meta tag “{name}” to tag {tag}",
                            summary_vars={"name": name, "tag": tag.name},
                            data={"tag_id": tid, "tag": tag.name,
                                  "name": name,
                                  # Conditional, so a plain mark's event is
                                  # byte-identical to what every earlier
                                  # build wrote.
                                  **({"count": n} if n else {})})
                    continue
                if new_count is None:
                    continue
                cur = int(row0.count or 0)
                want_n = _count_wanted(count_mode, cur,
                                       max(0, int(new_count)))
                if want_n != cur:
                    _log_meta_count(ctx, tag, row0, want_n)
    return out


def describe(ctx: Ctx, tag_id: Optional[int], *,
             comment: Optional[str] = None,
             description: Optional[str] = None) -> None:
    """Write the one-liner a NAMED THING carries — on its tag, which is where
    it lives.

    A subject, a place and an event are extra data ON a tag, so what the thing
    is, in a line, is the tag's own answer: kept twice, the two drift, and
    every list showing "the comment" had to pick one. The three record ops
    therefore route their `comment=` through here rather than holding a
    column of their own.

    The LONG form travels here too, again: a tag carries its own
    `description` (rung v27), because the library is a tag set now and one
    that cannot say what its names mean exports to a template with no
    teaching in it.

    A record with NO tag is refused rather than silently dropping the text: a
    face cluster nobody has named and a bare GPS fix are not named things yet,
    and the caller has just been asked for words about one.
    """
    if comment is None and description is None:
        return
    if tag_id is None:
        raise Refused(
            "name this first — a comment belongs to its tag",
            code="no_identity_tag")
    update(ctx, tag_id, comment=comment, description=description)


def update(ctx: Ctx, tag_id: int, *, name: Optional[str] = None,
           comment: Optional[str] = None,
           description: Optional[str] = None,
           alias_of: Optional[str] = None) -> Tag:
    """Rename, re-alias, comment and/or describe a tag. Each change is its
    own event."""
    s = ctx.session
    tag = by_id(ctx, tag_id)
    # AN ALIAS SAYS NOTHING OF ITS OWN. It is a second NAME for a tag —
    # assigning it redirects to the target, whose comment, implications and
    # records apply — so words on the alias itself are words
    # nothing reads, and they showed up in the one list that drew them
    # (`alias → test123` with a comment beside it, typed into the inline
    # comment cell the Items list used to have; that cell is gone, and this
    # is the rule rather than the absence of an entry point).
    aliasing = (alias_of or "").strip() if alias_of is not None else None
    is_alias = bool(aliasing) or (alias_of is None and tag.alias_of_id is not None)
    if is_alias and comment:
        raise Refused(
            "an alias says nothing of its own — comment the tag it stands for",
            code="alias_has_no_comment")
    # Becoming one drops whatever it used to say, for the same reason.
    if aliasing and tag.comment:
        tag.comment = ""
    if name is not None:
        new = check_name(name)
        clash = s.execute(
            select(Tag).where(Tag.name == new, Tag.id != tag_id)
        ).scalars().first()
        if clash:
            # The caller decides what "the name is taken" means — keep both and
            # pick another, or fold this tag into that one (merge).
            raise Conflict("a tag with that name already exists",
                           code="tag_exists")
        old_name = tag.name
        if new != old_name:
            tag.name = new
            ctx.log(action=actions.RENAME_TAG, entity_type="tag",
                    entity_id=tag.id,
                    summary="Renamed tag {old} → {new}",
                    summary_vars={"old": old_name, "new": new},
                    data={"tag_id": tag.id, "old_name": old_name, "name": new})
    if alias_of is not None:
        prev = s.get(Tag, tag.alias_of_id) if tag.alias_of_id else None
        old_alias = prev.name if prev is not None else ""
        set_alias(ctx, tag, alias_of)
        cur = s.get(Tag, tag.alias_of_id) if tag.alias_of_id else None
        new_alias = cur.name if cur is not None else ""
        if new_alias != old_alias:
            ctx.log(action=actions.SET_ALIAS, entity_type="tag",
                    entity_id=tag.id,
                    summary=(f"Aliased {tag.name} → {new_alias}" if new_alias
                             else f"Removed alias on {tag.name}"),
                    data={"tag_id": tag.id, "name": tag.name,
                          "old_alias_of": old_alias, "new_alias_of": new_alias})
    if comment is not None:
        old_comment = tag.comment or ""
        had = bool((tag.comment or "").strip())
        now = bool(comment.strip())
        tag.comment = comment
        if now:
            snippet = " ".join(comment.split())
            if len(snippet) > 80:
                snippet = snippet[:79] + "…"
            ctx.log(action=actions.COMMENT_TAG, entity_type="tag",
                    entity_id=tag.id,
                    summary=("Updated comment on tag {tag}: “{snippet}”" if had
                             else "Commented on tag {tag}: “{snippet}”"),
                    summary_vars={"tag": tag.name, "snippet": snippet},
                    data={"tag_id": tag.id, "tag": tag.name, "comment": comment,
                          "old_comment": old_comment})
        elif had:
            ctx.log(action=actions.COMMENT_TAG, entity_type="tag",
                    entity_id=tag.id,
                    summary="Cleared comment on tag {tag}",
                    summary_vars={"tag": tag.name},
                    data={"tag_id": tag.id, "tag": tag.name, "comment": "",
                          "old_comment": old_comment})
    if description is not None:
        old_description = tag.description or ""
        if description != old_description:
            tag.description = description
            had = bool(old_description.strip())
            now = bool(description.strip())
            ctx.log(action=actions.DESCRIBE_TAG, entity_type="tag",
                    entity_id=tag.id,
                    summary=("Described tag {tag}" if not had
                             else "Updated the description of tag {tag}"
                             if now else "Cleared the description of tag {tag}"),
                    summary_vars={"tag": tag.name},
                    data={"tag_id": tag.id, "tag": tag.name,
                          "description": description,
                          "old_description": old_description})
    return tag


def set_category(ctx: Ctx, tag_ids: Sequence[int],
                 category_id: Optional[int],
                 set_id: Optional[int] = None) -> list[int]:
    """File these names in a category of their own tag set, or take them
    out of one (`category_id=None` — "Uncategorized").

    ``set_id`` is the tag set: None is the LIBRARY's own tags, an id is
    that imported set's entries. One verb for both, because it is one
    gesture over one table — a set used to file its entries one PATCH at a
    time, which is the same drag costing four hundred requests.

    Filing is AUTHORED: somebody drags a row onto a category, and it stays
    there through a rename. The derived grouping is the NAMESPACE, which is
    read off the name and has no row at all; the two are separate axes on
    purpose, so `artist:kantoku` can be filed under People while still
    sitting under the `artist:` namespace.

    One event for the whole gesture, carrying each tag's PREVIOUS category —
    a selection dragged onto a category need not have come from one place, so
    a single `before` could not put it back. Bulk on purpose: the gesture is a
    drag of a selection, and a loop over a single-tag op is the perf
    regression `tests/test_perf_smoke.py` exists to catch.

    Returns the ids that actually MOVED; filing something where it already
    sits is not an event.
    """
    from ..db import TagSetEntry
    from . import tagsets as _tagsets

    s = ctx.session
    ids = [int(i) for i in dict.fromkeys(tag_ids) if i]
    if not ids:
        return []
    Row = Tag if set_id is None else TagSetEntry
    own = set_id
    if own is None:
        lib = _tagsets.library_set(s)
        own = lib.id if lib is not None else None
    cat: Optional[TagSetCategory] = None
    if category_id is not None:
        cat = s.get(TagSetCategory, int(category_id))
        if cat is None or own is None or cat.tag_set_id != own:
            # A category of ANOTHER tag set files nothing here: two
            # tag sets, one model, and the row would read as filed
            # somewhere its own list cannot show it.
            raise Invalid("that category is not one of this tag set's",
                          code="not_a_library_category")
    before: dict[str, Optional[int]] = {}
    moved: list[int] = []
    for chunk in chunked(ids):
        sel = select(Row).where(Row.id.in_(chunk))
        if set_id is not None:
            sel = sel.where(TagSetEntry.tag_set_id == set_id)
        for tag in s.execute(sel).scalars():
            was = tag.category_id
            if was == (cat.id if cat is not None else None):
                continue
            before[str(tag.id)] = was
            tag.category_id = cat.id if cat is not None else None
            moved.append(tag.id)
    if not moved:
        return []
    s.flush()
    where = (_tagsets.trail_label(s, cat.id) if cat is not None else "")
    ctx.log(action=actions.SET_TAG_CATEGORY, entity_type="tag", entity_id=None,
            summary=("Filed {n} tags under {where}" if cat is not None
                     else "Took {n} tags out of their category"),
            summary_vars={"n": str(len(moved)), "where": where},
            # `set_id` rides CONDITIONALLY, so the library's own gesture
            # writes exactly the payload it always wrote — which is what
            # keeps the history golden byte-identical.
            data={"category_id": cat.id if cat is not None else None,
                  **({"set_id": set_id} if set_id is not None else {}),
                  "before": before})
    return moved


# ---- meta tags on a tag -----------------------------------------------------
#
# The FOURTH carrier of the meta-tag namespace (see `db.TagMetaTag`). Kept here
# rather than in `ops/links.py` beside the other three because these are edits
# to a TAG ROW, which is what this module is; what links.py owns is the
# namespace itself — its names, comments, renames and deletions — and those
# already reach this table.


def meta_marks(session, tag_ids: list[int]
               ) -> tuple[dict[int, list[str]], dict[int, dict[str, int]]]:
    """Both halves of what a tag's meta tags say, in ONE pass.

    The names and the nonzero counts are the same rows read twice, and the
    tags list reads them for the whole catalog: measured at 500,000
    assignments, 0.80 s each and 0.80 s for the pair. The counts stay SPARSE
    — almost every assignment is a plain mark, and an empty dict costs
    nothing on the wire.
    """
    from ..db import TagMetaTag

    names: dict[int, list[str]] = {}
    counts: dict[int, dict[str, int]] = {}
    for chunk in chunked(tag_ids):
        for tid, name, count in session.execute(
            select(TagMetaTag.tag_id, TagMetaTag.name, TagMetaTag.count)
            .where(TagMetaTag.tag_id.in_(chunk))
            .order_by(TagMetaTag.name)
        ).all():
            names.setdefault(tid, []).append(name)
            if count:
                counts.setdefault(tid, {})[name] = int(count)
    return names, counts


def meta_names(session, tag_ids: list[int]) -> dict[int, list[str]]:
    """The meta tags of each of these tags, by tag id."""
    return meta_marks(session, tag_ids)[0]


def meta_counts(session, tag_ids: list[int]) -> dict[int, dict[str, int]]:
    """Each tag's NONZERO per-meta counts, by tag id."""
    return meta_marks(session, tag_ids)[1]


def _meta_name(raw: str) -> str:
    """A meta tag's name, by the namespace's own rule — whitespace collapsed
    and capped, NOT a tag name. `link_tags` holds "main character" with its
    space, so `check_name` would refuse half the catalog."""
    name = " ".join(str(raw or "").split())[:64]
    if not name:
        raise Invalid("empty tag", code="empty_meta_tag")
    return name


def _log_meta_count(ctx: Ctx, tag: Tag, row, want: int) -> Event:
    """Set an assignment's count and write the event whose revert puts the
    old number back."""
    old = int(row.count or 0)
    row.count = max(0, int(want))
    return ctx.log(action=actions.SET_META_COUNT, entity_type="tag",
                   entity_id=tag.id,
                   summary=("Set the “{name}” count on {tag} to {n}" if row.count
                            else "Cleared the “{name}” count on {tag}"),
                   summary_vars={"name": row.name, "tag": tag.name,
                                 "n": str(row.count)},
                   data={"tag_id": tag.id, "tag": tag.name, "name": row.name,
                         "count": row.count, "old_count": old})


def _move_meta_tag(ctx: Ctx, tag: Tag, name: str,
                   count: Optional[int] = None) -> Optional[Event]:
    """Put one meta tag on a tag row, logging it. None when it was already
    there with nothing to change. The shared half of `add_meta_tag` and the
    merge. ``count`` is the assignment's own figure — how many pictures the
    tag has where the meta tag says — set on a fresh assignment, and logged
    as its own `set_meta_count` on an existing one."""
    from ..db import LIB_META, LinkTag, TagMetaTag

    s = ctx.session
    event = None
    row = s.execute(select(TagMetaTag).where(
        TagMetaTag.tag_id == tag.id, TagMetaTag.name == name,
    )).scalars().first()
    if row is None:
        n = max(0, int(count or 0))
        s.add(TagMetaTag(tag_id=tag.id, name=name, count=n))
        event = ctx.log(action=actions.ADD_LINK_TAG, entity_type="tag",
                        entity_id=tag.id,
                        summary="Added meta tag “{name}” to tag {tag}",
                        summary_vars={"name": name, "tag": tag.name},
                        data={"tag_id": tag.id, "tag": tag.name, "name": name,
                              # Conditional: a countless add stays
                              # byte-identical to every earlier build's.
                              **({"count": n} if n else {})})
    elif count is not None and int(count) != int(row.count or 0):
        event = _log_meta_count(ctx, tag, row, int(count))
    # A meta tag survives its last use, so the name is registered in the
    # catalog exactly as the other three carriers register theirs.
    if s.execute(select(LinkTag).where(
            LinkTag.name == name, LIB_META)).scalar_one_or_none() is None:
        s.add(LinkTag(name=name))
    return event


def add_meta_tag(ctx: Ctx, tag_id: int, name: str,
                 count: Optional[int] = None) -> list[str]:
    """Put a meta tag on a tag (idempotent). ``count`` sets the assignment's
    own figure — on a fresh assignment directly, on an existing one as its
    own logged `set_meta_count`. Returns the tag's meta tags."""
    s = ctx.session
    tag = by_id(ctx, tag_id)
    _move_meta_tag(ctx, tag, _meta_name(name), count)
    s.flush()
    return meta_names(s, [tag.id]).get(tag.id, [])


def remove_meta_tag(ctx: Ctx, tag_id: int, name: str) -> list[str]:
    """Take a meta tag off a tag. Returns the tag's remaining meta tags."""
    from ..db import TagMetaTag

    s = ctx.session
    tag = by_id(ctx, tag_id)
    name = str(name or "").strip()
    row = s.execute(select(TagMetaTag).where(
        TagMetaTag.tag_id == tag.id, TagMetaTag.name == name,
    )).scalars().first()
    if row is not None:
        count = int(row.count or 0)
        s.delete(row)
        ctx.log(action=actions.REMOVE_LINK_TAG, entity_type="tag",
                entity_id=tag.id,
                summary="Removed meta tag “{name}” from tag {tag}",
                summary_vars={"name": name, "tag": tag.name},
                data={"tag_id": tag.id, "tag": tag.name, "name": name,
                      # Conditional: the revert restores the SHAPE, and the
                      # assignment's count is part of it — while a countless
                      # removal's event stays byte-identical to every
                      # earlier build's.
                      **({"count": count} if count else {})})
    s.flush()
    return meta_names(s, [tag.id]).get(tag.id, [])


# ---- snapshots --------------------------------------------------------------


def relations_snapshot(ctx: Ctx, tag: Tag) -> dict:
    """What the tag row itself takes down with it: its implications in both
    directions, the library groups that assign it, its aliases (whose FK
    cascades, so they are deleted outright), and — since `Subject.tag_id` is
    SET NULL rather than CASCADE — the identity it WAS. That last one is a
    link, not a row: the subject survives, unlinked, and only the tag's own
    revert knows what to point back at what."""
    from ..db import Subject

    s = ctx.session
    names = dict(s.execute(select(Tag.id, Tag.name)).all())
    implies = [names[i] for i in s.execute(select(TagImplication.implies_id).where(
        TagImplication.tag_id == tag.id)).scalars().all() if i in names]
    implied_by = [names[i] for i in s.execute(select(TagImplication.tag_id).where(
        TagImplication.implies_id == tag.id)).scalars().all() if i in names]
    groups = [{"group_id": gid, "negative": bool(neg)} for gid, neg in s.execute(
        select(GroupTag.group_id, GroupTag.negative)
        .where(GroupTag.tag_id == tag.id)).all()]
    aliases = [{"name": n, "comment": c or ""} for n, c in s.execute(
        select(Tag.name, Tag.comment).where(Tag.alias_of_id == tag.id)).all()]
    was = s.execute(select(Subject.id).where(
        Subject.tag_id == tag.id)).scalars().first()
    out = {"implies": implies, "implied_by": implied_by,
           "group_tags": groups, "aliases": aliases, "subject_id": was}
    # The meta tags the row carried — they cascade with it, and only its own
    # revert can put them back. Written only when there are any, so an event
    # for a tag with none is byte-identical to what every earlier build wrote.
    metas = meta_names(s, [tag.id]).get(tag.id, [])
    if metas:
        out["meta_tags"] = metas
        counts = meta_counts(s, [tag.id]).get(tag.id, {})
        if counts:
            # The per-assignment counts go down with the rows too; the
            # revert restores the SHAPE, and a count is part of it.
            out["meta_counts"] = counts
    return out


# ---- merge / delete ---------------------------------------------------------


def merge(ctx: Ctx, tag_id: int, into: str, *,
          keep_alias: bool = True) -> list[Event]:
    """Fold this tag into another one and delete it.

    Everything it carries moves across: every item assignment (with its tag
    groups, boxes and time ranges), what it entailed and what entailed it, the
    library groups that assigned it, and its aliases — plus its own name, which
    becomes another alias of the target so anything still calling it that finds
    the right tag.

    Every step is logged as the change it is (an `add_tag` per item that gains
    the target, a `remove_tag` per item that loses this one, then the deletion),
    so History shows what happened and reverting the set puts it all back.

    Returns the events written, so a caller can offer an Undo for exactly this.
    """
    # Imported here rather than at module scope: `tagassign` needs
    # `get_or_create` from THIS module, so a top-level import either way is a
    # cycle. The catalog is the lower layer and only reaches up for the two
    # placement primitives below.
    from . import tagassign

    s = ctx.session
    from ..db import ItemTagBox, ItemTagGroup

    src = by_id(ctx, tag_id)
    dst = s.execute(select(Tag).where(
        Tag.name == (into or "").strip())).scalars().first()
    if dst is None:
        raise NotFound("no tag with that name to merge into",
                       code="merge_target_missing")
    if dst.id == src.id:
        raise Refused("a tag cannot be merged into itself", code="merge_self")
    if dst.alias_of_id is not None:
        raise Refused("merge into the tag itself, not one of its aliases",
                      code="merge_into_alias")

    events: list[Event] = []
    src_name, dst_name = src.name, dst.name

    # Everything the move reads, loaded up front in bulk maps: the source's
    # assignments, the target's assignments on those same items, the source's
    # placements with their boxes and groups, and the target's placements per
    # group. The per-row SELECTs made a popular tag's merge O(assignments²)
    # round trips; the events written per (item, change) are unchanged.
    src_its = s.execute(select(ItemTag)
                        .where(ItemTag.tag_id == src.id)).scalars().all()
    dst_by_item: dict[int, ItemTag] = {}
    for chunk in chunked([it.item_id for it in src_its]):
        for row in s.execute(select(ItemTag).where(
                ItemTag.item_id.in_(chunk), ItemTag.tag_id == dst.id
        )).scalars().all():
            dst_by_item[row.item_id] = row
    placements_by_it: dict[int, list[ItemTagPlacement]] = {}
    for chunk in chunked([it.id for it in src_its]):
        for p in s.execute(select(ItemTagPlacement)
                           .where(ItemTagPlacement.item_tag_id.in_(chunk))
                           .order_by(ItemTagPlacement.id)).scalars().all():
            placements_by_it.setdefault(p.item_tag_id, []).append(p)
    src_ps = [p for ps in placements_by_it.values() for p in ps]
    boxes_by_p: dict[int, list[ItemTagBox]] = {}
    for chunk in chunked([p.id for p in src_ps]):
        for b in s.execute(select(ItemTagBox)
                           .where(ItemTagBox.placement_id.in_(chunk))
                           .order_by(ItemTagBox.id)).scalars().all():
            boxes_by_p.setdefault(b.placement_id, []).append(b)
    groups_by_id: dict[int, ItemTagGroup] = {}
    for chunk in chunked({p.group_id for p in src_ps if p.group_id}):
        for g in s.execute(select(ItemTagGroup)
                           .where(ItemTagGroup.id.in_(chunk))).scalars().all():
            groups_by_id[g.id] = g
    # The target side's existing placements, keyed the way the fold looks
    # them up; kept current as placements move so later moves fold into them.
    dst_pl: dict[tuple[int, Optional[int]], ItemTagPlacement] = {}
    for chunk in chunked([row.id for row in dst_by_item.values()]):
        for p in s.execute(select(ItemTagPlacement)
                           .where(ItemTagPlacement.item_tag_id.in_(chunk))
                           .order_by(ItemTagPlacement.id)).scalars().all():
            dst_pl.setdefault((p.item_tag_id, p.group_id), p)

    def snapshot_of(it: ItemTag) -> list[dict]:
        # `tagassign.placement_snapshot`, fed from the maps — identical output.
        out: list[dict] = []
        for p in placements_by_it.get(it.id, []):
            grp = groups_by_id.get(p.group_id) if p.group_id else None
            out.append({
                "group": grp.name if grp is not None else None,
                "system": bool(grp.system) if grp is not None else False,
                "boxes": [
                    {"x": b.x, "y": b.y, "w": b.w, "h": b.h,
                     "time_start": b.time_start, "time_end": b.time_end,
                     "track_id": b.track_id, "negative": bool(b.negative),
                     **({"points": b.points} if b.points else {})}
                    for b in boxes_by_p.get(p.id, [])
                ],
            })
        return out

    for it in src_its:
        item_id = it.item_id
        snapshot = snapshot_of(it)
        target = dst_by_item.get(item_id)
        if target is None:
            target = ItemTag(item_id=item_id, tag_id=dst.id,
                             negative=it.negative, pending=it.pending)
            s.add(target)
            s.flush()
            dst_by_item[item_id] = target
            events.append(ctx.log(
                action=actions.ADD_TAG, entity_type="item", entity_id=item_id,
                summary=("Tagged item #{item} −{tag}" if it.negative
                         else "Tagged item #{item} +{tag}"),
                summary_vars={"item": item_id, "tag": dst_name},
                data={"item_id": item_id, "tag": dst_name,
                      "negative": bool(it.negative)},
            ))
        # The assignment's SHAPE comes along: each placement moves to the target,
        # folding into an instance it already has in that group (boxes and all).
        for p in placements_by_it.get(it.id, []):
            gid = p.group_id
            p.item_tag_id = target.id
            s.flush()
            existing = dst_pl.get((target.id, gid))
            if existing is None or existing is p:
                # `merge_placement_into_group` with no collision: the
                # placement simply belongs to the target in its group now.
                p.group_id = gid
                dst_pl[(target.id, gid)] = p
            else:
                tagassign.fold_boxes(ctx, p, existing)
                s.delete(p)
        s.flush()
        tagassign.recompute_pending(ctx, target.id)
        events.append(ctx.log(
            action=actions.REMOVE_TAG, entity_type="item", entity_id=item_id,
            summary="Removed tag {tag} from item #{item}",
            summary_vars={"tag": src_name, "item": item_id},
            data={"item_id": item_id, "tag": src_name,
                  "negative": bool(it.negative), "pending": bool(it.pending),
                  "placements": snapshot},
        ))

    # Relations move too: what it entailed, what entailed it, and the library
    # groups that assigned it — added to the target where it doesn't have them.
    # The name map and the implication closure are computed ONCE and passed
    # down; `link_implication` used to rebuild both per edge.
    names = dict(s.execute(select(Tag.id, Tag.name)).all())
    closure = tag_implications(s)

    def _moved_edge(from_id: int, to_id: int) -> None:
        if not link_implication(ctx, from_id, to_id, names=names,
                                closure=closure):
            return
        a_name, b_name = names.get(from_id, "?"), names.get(to_id, "?")
        events.append(ctx.log(
            action=actions.ADD_TAG_IMPLICATION, entity_type="tag",
            entity_id=from_id,
            summary="{tag} now implies {target}",
            summary_vars={"tag": a_name, "target": b_name},
            data={"tag_id": from_id, "name": a_name, "implies": b_name},
        ))

    for other_id in s.execute(select(TagImplication.implies_id).where(
        TagImplication.tag_id == src.id)).scalars().all():
        _moved_edge(dst.id, other_id)
    for other_id in s.execute(select(TagImplication.tag_id).where(
        TagImplication.implies_id == src.id)).scalars().all():
        _moved_edge(other_id, dst.id)
    for gid, neg in s.execute(select(GroupTag.group_id, GroupTag.negative)
                              .where(GroupTag.tag_id == src.id)).all():
        if s.execute(select(GroupTag).where(
            GroupTag.group_id == gid, GroupTag.tag_id == dst.id
        )).scalars().first() is None:
            s.add(GroupTag(group_id=gid, tag_id=dst.id, negative=neg))
            events.append(ctx.log(
                action=actions.ADD_GROUP_TAG, entity_type="group",
                entity_id=gid,
                summary=("Tagged group #{group} −{tag}" if neg
                         else "Tagged group #{group} +{tag}"),
                summary_vars={"group": gid, "tag": dst_name},
                data={"group_id": gid, "tag": dst_name, "negative": bool(neg)},
            ))
    for alias in s.execute(select(Tag).where(
        Tag.alias_of_id == src.id)).scalars().all():
        alias.alias_of_id = dst.id
    # The meta tags move too — a merge is a rename onto a taken name, and what
    # the tag set said about the source ("noflip") is still true of the tag
    # it became. Each is its own event, so the merge reverts whole. A count
    # rides its assignment; where both sides carry one the LARGER stands —
    # the two figures counted overlapping pictures, so the sum would double
    # them and the smaller is subsumed.
    src_counts = meta_counts(s, [src.id]).get(src.id, {})
    dst_counts = meta_counts(s, [dst.id]).get(dst.id, {})
    for name in meta_names(s, [src.id]).get(src.id, []):
        n = src_counts.get(name, 0)
        moved = max(n, dst_counts.get(name, 0)) if n else None
        events.extend(e for e in [_move_meta_tag(ctx, dst, name, moved)] if e)

    events.append(ctx.log(
        action=actions.DELETE_TAG, entity_type="tag", entity_id=src.id,
        summary="Merged tag {source} into {target}",
        summary_vars={"source": src_name, "target": dst_name},
        data={"name": src_name, "comment": src.comment or "", "alias_of": None,
              "merged_into": dst_name, **relations_snapshot(ctx, src)},
    ))
    s.delete(src)
    s.flush()
    # The old name lives on as an alias of the target, so nothing that still
    # says it goes looking for a tag that no longer exists.
    if keep_alias and s.execute(select(Tag).where(
            Tag.name == src_name)).scalars().first() is None:
        s.add(Tag(name=src_name, alias_of_id=dst.id))
    s.flush()
    return events


def _delete_identity_records(ctx: Ctx, tag: Tag) -> list[Event]:
    """An identity tag takes its RECORD with it: the subject, place or event
    pointing at the tag is deleted through its own op — its own revertible
    event — rather than SET-NULL'd into the orphan
    state a select-all sweep once left a whole library in ("several records
    without tags, this shouldn't be possible"). Called with the record ops'
    ``with_tag=False``, since the tag is already on its way; the reverse
    direction (``delete_subject(with_tag=True)`` calling back in) cannot
    recurse, because by then the record row is gone and nothing matches.

    Lazy imports both ways round: the record ops import `tagcatalog` (their
    ``with_tag`` is this module's delete), so a top-level import is a
    cycle."""
    from ..db import Location, Occasion, Subject
    from . import events as ev_ops
    from . import places as place_ops
    from . import subjects as subject_ops

    s = ctx.session
    out: list[Event] = []
    sub = s.execute(select(Subject).where(
        Subject.tag_id == tag.id)).scalars().first()
    if sub is not None:
        out.append(subject_ops.delete_subject(ctx, sub.id))
    loc = s.execute(select(Location).where(
        Location.tag_id == tag.id)).scalars().first()
    if loc is not None:
        out.append(place_ops.delete_place(ctx, loc.id))
    occ = s.execute(select(Occasion).where(
        Occasion.tag_id == tag.id)).scalars().first()
    if occ is not None:
        out.append(ev_ops.delete_event(ctx, occ.id))
    return [e for e in out if e is not None]


def delete_tag(ctx: Ctx, tag_id: int) -> list[Event]:
    """Delete a tag everywhere. A missing tag is a no-op returning no events.

    Returns the events written, so a caller can offer an Undo for exactly this
    deletion — which is the only way back from it.
    """
    from . import tagassign  # see the note in `merge`

    s = ctx.session
    tag = s.get(Tag, tag_id)
    events: list[Event] = []
    if tag is not None:
        events.extend(_delete_identity_records(ctx, tag))
        # Assignment rows cascade away at the DB level (invisible to the ORM
        # sweep) — queue the users' sidecars while they still exist.
        target = s.get(Tag, tag.alias_of_id) if tag.alias_of_id else None
        alias_of = target.name if target is not None else None
        # Deleting a tag takes it off every item it was on, and each of those is
        # a change of its own — logged as such, so the History view can show
        # them (grouped into one row) and REVERTING brings the assignments back,
        # whole: the sign, the tag groups it sat in, and each placement's boxes
        # and time ranges. A single delete_tag event only ever restored the
        # empty tag row.
        for it in s.execute(select(ItemTag)
                            .where(ItemTag.tag_id == tag.id)).scalars().all():
            events.append(ctx.log(
                action=actions.REMOVE_TAG, entity_type="item",
                entity_id=it.item_id,
                summary="Removed tag {tag} from item #{item}",
                summary_vars={"tag": tag.name, "item": it.item_id},
                data={"item_id": it.item_id, "tag": tag.name,
                      "negative": bool(it.negative), "pending": bool(it.pending),
                      "placements": tagassign.placement_snapshot(ctx, it)},
            ))
        events.append(ctx.log(
            action=actions.DELETE_TAG, entity_type="tag", entity_id=tag.id,
            summary=(f"Deleted alias {tag.name} → {alias_of}" if alias_of
                     else f"Deleted tag {tag.name}"),
            # Everything else that dies with the tag row, so the revert can put
            # it back: what it entailed and what entailed IT, the library groups
            # that assigned it, and the aliases the FK cascade takes with it.
            data={"name": tag.name, "comment": tag.comment or "",
                  "alias_of": alias_of, **relations_snapshot(ctx, tag)},
        ))
        s.delete(tag)
    s.flush()  # an Event has no id until it is flushed
    return events


def bulk_delete(ctx: Ctx, tag_ids) -> list[Event]:
    """Delete many tags at once — a bulk op extracted as a bulk op.

    The events are `delete_tag`'s to the key: one `remove_tag` per assignment
    (with its placement snapshot) and one `delete_tag` per row (with its
    relations snapshot), so History and revert see exactly what a loop over
    single deletions writes. What changes is the cost: the loop was two
    library-wide reads PER TAG (`relations_snapshot` builds the whole name
    map, the fan-out walks the implication table), which on a 32k-tag
    selection is a quadratic nobody sees end — reported as a Delete button
    that "does nothing". Here every map is loaded once.

    Order matters the way it does for a sequence of single deletions: a
    snapshot never mentions a tag an EARLIER row of the same call already
    deleted, and an alias whose target went first has already cascaded away —
    it is skipped without an event, exactly as a single delete of a missing
    tag is a no-op.
    """
    from ..db import ItemTagBox, ItemTagGroup, Location, Occasion, Subject

    s = ctx.session
    tags: dict[int, Tag] = {}
    for chunk in chunked([int(i) for i in tag_ids]):
        for t in s.execute(select(Tag).where(Tag.id.in_(chunk))).scalars():
            tags[t.id] = t
    order, seen = [], set()
    for i in tag_ids:
        i = int(i)
        if i in tags and i not in seen:
            seen.add(i)
            order.append(i)
    if not order:
        return []

    names = dict(s.execute(select(Tag.id, Tag.name)).all())
    # The implication table, both directions — it is the small edge table.
    fwd: dict[int, list[int]] = {}
    rev: dict[int, list[int]] = {}
    for tid, iid in s.execute(
            select(TagImplication.tag_id, TagImplication.implies_id)).all():
        fwd.setdefault(tid, []).append(iid)
        rev.setdefault(iid, []).append(tid)
    # ONE fan-out for the lot, before anything is deleted: the union of every
    # tag's `tag_and_children_names` is exactly its name plus its direct
    # impliers' names.
    fan: set[str] = set()
    for tid in order:
        fan.add(names[tid])
        fan.update(names[i] for i in rev.get(tid, []) if i in names)

    gts: dict[int, list[tuple[int, bool]]] = {}
    aliases: dict[int, list[Tag]] = {}
    subj: dict[int, int] = {}
    locs: dict[int, int] = {}
    occs: dict[int, int] = {}
    its: dict[int, list[ItemTag]] = {}
    for chunk in chunked(order):
        for gid, tid, neg in s.execute(
                select(GroupTag.group_id, GroupTag.tag_id, GroupTag.negative)
                .where(GroupTag.tag_id.in_(chunk))).all():
            gts.setdefault(tid, []).append((gid, bool(neg)))
        for a in s.execute(select(Tag)
                           .where(Tag.alias_of_id.in_(chunk))
                           .order_by(Tag.id)).scalars():
            aliases.setdefault(a.alias_of_id, []).append(a)
        for sid, tid in s.execute(
                select(Subject.id, Subject.tag_id)
                .where(Subject.tag_id.in_(chunk)).order_by(Subject.id)).all():
            subj.setdefault(tid, sid)
        for lid, tid in s.execute(
                select(Location.id, Location.tag_id)
                .where(Location.tag_id.in_(chunk)).order_by(Location.id)).all():
            locs.setdefault(tid, lid)
        for oid, tid in s.execute(
                select(Occasion.id, Occasion.tag_id)
                .where(Occasion.tag_id.in_(chunk)).order_by(Occasion.id)).all():
            occs.setdefault(tid, oid)
        for it in s.execute(select(ItemTag)
                            .where(ItemTag.tag_id.in_(chunk))
                            .order_by(ItemTag.id)).scalars():
            its.setdefault(it.tag_id, []).append(it)
    metas = meta_names(s, order)

    # The assignments' SHAPE, preloaded the way `merge` preloads it —
    # `placement_snapshot` per ItemTag is three queries each.
    all_its = [it for l in its.values() for it in l]
    placements_by_it: dict[int, list[ItemTagPlacement]] = {}
    for chunk in chunked([it.id for it in all_its]):
        for p in s.execute(select(ItemTagPlacement)
                           .where(ItemTagPlacement.item_tag_id.in_(chunk))
                           .order_by(ItemTagPlacement.id)).scalars().all():
            placements_by_it.setdefault(p.item_tag_id, []).append(p)
    all_ps = [p for ps in placements_by_it.values() for p in ps]
    boxes_by_p: dict[int, list[ItemTagBox]] = {}
    for chunk in chunked([p.id for p in all_ps]):
        for b in s.execute(select(ItemTagBox)
                           .where(ItemTagBox.placement_id.in_(chunk))
                           .order_by(ItemTagBox.id)).scalars().all():
            boxes_by_p.setdefault(b.placement_id, []).append(b)
    groups_by_id: dict[int, ItemTagGroup] = {}
    for chunk in chunked({p.group_id for p in all_ps if p.group_id}):
        for g in s.execute(select(ItemTagGroup)
                           .where(ItemTagGroup.id.in_(chunk))).scalars().all():
            groups_by_id[g.id] = g

    def snapshot_of(it: ItemTag) -> list[dict]:
        # `tagassign.placement_snapshot`, fed from the maps — identical output.
        out: list[dict] = []
        for p in placements_by_it.get(it.id, []):
            grp = groups_by_id.get(p.group_id) if p.group_id else None
            out.append({
                "group": grp.name if grp is not None else None,
                "system": bool(grp.system) if grp is not None else False,
                "boxes": [
                    {"x": b.x, "y": b.y, "w": b.w, "h": b.h,
                     "time_start": b.time_start, "time_end": b.time_end,
                     "track_id": b.track_id, "negative": bool(b.negative),
                     **({"points": b.points} if b.points else {})}
                    for b in boxes_by_p.get(p.id, [])
                ],
            })
        return out

    events: list[Event] = []
    dead: set[int] = set()
    removed: list[int] = []
    from . import events as ev_ops
    from . import places as place_ops
    from . import subjects as subject_ops

    for tid in order:
        if tid in dead:
            continue  # an alias whose target went first — already cascaded
        tag = tags[tid]
        # An identity tag takes its record with it — through the record ops,
        # so the event and its revert are the record's own (see
        # `_delete_identity_records`; here from the preloaded maps).
        if tid in subj:
            events.append(subject_ops.delete_subject(ctx, subj[tid]))
        if tid in locs:
            events.append(place_ops.delete_place(ctx, locs[tid]))
        if tid in occs:
            events.append(ev_ops.delete_event(ctx, occs[tid]))
        target_ok = tag.alias_of_id is not None and tag.alias_of_id not in dead
        alias_of = names.get(tag.alias_of_id) if target_ok else None
        for it in its.get(tid, []):
            events.append(ctx.log(
                action=actions.REMOVE_TAG, entity_type="item",
                entity_id=it.item_id,
                summary="Removed tag {tag} from item #{item}",
                summary_vars={"tag": tag.name, "item": it.item_id},
                data={"item_id": it.item_id, "tag": tag.name,
                      "negative": bool(it.negative),
                      "pending": bool(it.pending),
                      "placements": snapshot_of(it)},
            ))
        # `relations_snapshot`, from the maps — minus whatever an earlier row
        # of this same call already deleted, which is what a sequence of
        # single deletions would (not) have seen.
        snapshot: dict = {
            "implies": [names[i] for i in fwd.get(tid, [])
                        if i in names and i not in dead],
            "implied_by": [names[i] for i in rev.get(tid, [])
                           if i in names and i not in dead],
            "group_tags": [{"group_id": gid, "negative": neg}
                           for gid, neg in gts.get(tid, [])],
            "aliases": [{"name": a.name, "comment": a.comment or ""}
                        for a in aliases.get(tid, []) if a.id not in dead],
            "subject_id": subj.get(tid),
        }
        if metas.get(tid):
            snapshot["meta_tags"] = metas[tid]
        events.append(ctx.log(
            action=actions.DELETE_TAG, entity_type="tag", entity_id=tid,
            summary=(f"Deleted alias {tag.name} → {alias_of}" if alias_of
                     else f"Deleted tag {tag.name}"),
            data={"name": tag.name, "comment": tag.comment or "",
                  "alias_of": alias_of, **snapshot},
        ))
        removed.append(tid)
        dead.add(tid)
        # Its alias rows go with it at the DB level — a later id in this same
        # call that names one must be the no-op a single delete would be.
        for a in aliases.get(tid, []):
            dead.add(a.id)
    # ONE Core statement per chunk rather than an ORM delete per row: the DB
    # cascades exactly as it does for the single delete, and the unit of work
    # — which does not know the alias self-FK — cannot order a row behind the
    # cascade that already took it.
    for chunk in chunked(removed):
        s.execute(delete(Tag).where(Tag.id.in_(chunk)))
    s.flush()  # an Event has no id until it is flushed
    return events
