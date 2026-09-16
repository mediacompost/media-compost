"""Build :class:`~media_compost.query.QueryCtx` inputs from the database.

Shared by the web search path and the scripting module so the two evaluate an
item against identical context. Kept separate from :mod:`media_compost.query`
(which stays pure / DB-free) and from the server layer.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .query import taken_window as q_taken_window
from .db import Caption, CaptionTag, Group, GroupParent, ItemGroup, ItemLocation, \
    ItemMetaPin, ItemMetadata, ItemSubject, ItemTag, Location, Occasion, \
    Relationship, RelationshipTag, Subject, Tag, chunked
from . import grouppath
from . import partialdate
from .query import MetaVal

# Every loader here takes a Python-side id list, so every ``IN (...)`` goes
# through ``db.chunked`` — SQLite caps bind parameters per statement, and a
# candidate set past that cap must split rather than raise.


def load_indexed_meta(
    s: Session, ids: list[int]
) -> dict[int, dict[str, list[MetaVal]]]:
    """Indexed static metadata: item -> name -> the values it answers with.

    THE UNION IS SPELLED HERE AND NOWHERE ELSE. An item answers with what its
    ACTIVE FILE says (``item_metadata``, already reduced by any mute) PLUS
    whatever has been promoted to the item itself (``item_meta_pins``) — which
    is the whole of "only item-level metadata and the active file's metadata
    are searched". Every reader that took only the first half would make a
    pinned value silently invisible to itself, so there is one loader.

    A LIST per name, not one value: a pin sits BESIDE the active file's answer
    rather than replacing it, so an item whose files disagree genuinely answers
    to both. Muting is what makes a pin an override, and it has already been
    applied by the time the rows get here.
    """
    result: dict[int, dict[str, list[MetaVal]]] = {}
    if not ids:
        return result
    for table in (ItemMetadata, ItemMetaPin):
        for chunk in chunked(ids):
            for iid, name, mtype, num, text in s.execute(
                select(table.item_id, table.name, table.mtype,
                       table.num_value, table.text_value)
                .where(table.item_id.in_(chunk))
            ).all():
                result.setdefault(iid, {}).setdefault(name, []).append(
                    MetaVal(mtype=mtype, num=num, text=text)
                )
    return result


def load_tag_meta(s: Session) -> dict[str, frozenset[str]]:
    """What the tag set says about each tag: NAME -> its meta tags.

    Catalog-wide and item-independent, unlike every other loader here — which
    is exactly why `TAG:noflip` costs one statement however many candidates
    there are: the answer is read off each item's own effective tags, which
    the evaluator already has.
    """
    from .db import TagMetaTag

    out: dict[str, set[str]] = {}
    for name, meta in s.execute(
        select(Tag.name, TagMetaTag.name)
        .join(TagMetaTag, TagMetaTag.tag_id == Tag.id)
    ).all():
        out.setdefault(name.lower(), set()).add(meta.lower())
    return {k: frozenset(v) for k, v in out.items()}


def load_value_sets(s: Session, conditions) -> dict[str, frozenset[str]]:
    """Resolve each VALUE condition to the catalog's matching tag NAMES.

    ``ValueCond.key()`` -> every tag in its namespace whose basename parses
    as a value satisfying the comparison (`tagvalue.matching_names`, the one
    definition). Catalog-wide like `load_tag_meta`, resolved once per search
    however many nodes share a literal — and read by BOTH the residue
    evaluator (against the item's effective tags) and the SQL compiler (as a
    tag-id set), so the two cannot disagree.

    Aliases are left out: assigning one redirects to its target, so an alias
    name never appears in an item's effective tags and a clause on its id
    could never match a row.
    """
    from . import tagvalue

    out: dict[str, frozenset[str]] = {}
    if not conditions:
        return out
    names = [n for (n,) in s.execute(
        select(Tag.name).where(Tag.alias_of_id.is_(None))).all()]
    for cond in conditions:
        key = cond.key()
        if key in out:
            continue
        out[key] = frozenset(tagvalue.matching_names(
            names, cond.name.lower(), cond.op, cond.value, cond.unit,
            cond.tol))
    return out


def load_caption_sets(
    s: Session, ids: list[int]
) -> tuple[dict[int, list[frozenset[str]]], dict[int, list[frozenset[str]]]]:
    """Per item: one frozenset of lowercased meta-tag names per caption (empty
    for an untagged caption), mirroring `load_link_sets` for relationships.

    Returns TWO maps — descriptions and instructions — because they are the
    same row type carrying the same meta tags, and an evaluator that saw one
    list would answer "has a caption" for an item that only says how it was
    made.
    """
    caps_out: dict[int, list[frozenset[str]]] = {}
    instr_out: dict[int, list[frozenset[str]]] = {}
    if not ids:
        return caps_out, instr_out
    caps: list[tuple[int, int, str]] = []
    for chunk in chunked(ids):
        caps.extend(s.execute(
            select(Caption.id, Caption.item_id, Caption.kind)
            .where(Caption.item_id.in_(chunk))
        ).all())
    tags_by_caption: dict[int, set[str]] = {}
    for chunk in chunked([c[0] for c in caps]):
        for cid, name in s.execute(
            select(CaptionTag.caption_id, CaptionTag.name)
            .where(CaptionTag.caption_id.in_(chunk))
        ).all():
            tags_by_caption.setdefault(cid, set()).add(name.lower())
    for cid, item_id, kind in caps:
        out = instr_out if kind == "instruction" else caps_out
        out.setdefault(item_id, []).append(
            frozenset(tags_by_caption.get(cid, set())))
    return caps_out, instr_out


def load_group_sets(
    s: Session, ids: list[int]
) -> tuple[dict[int, frozenset[str]], dict[int, frozenset[str]],
           dict[int, frozenset[str]], dict[int, frozenset[str]]]:
    """Per item: ``(direct, ancestors, direct paths, ancestor paths)``.

    The first two are the lowercased NAMES of its direct groups and of the
    strict ancestors of those (the group condition's "has" mode is the union
    of the two; "only" reads the direct sets alone).
    Group names are not unique across the tree, so the second pair carries
    each of those groups' full PATH — what lets a condition say WHICH "2024"
    it means (`grouppath`). Both are needed: the name sets answer every
    query written before paths existed, in one set lookup."""
    direct: dict[int, frozenset[str]] = {}
    ancestors: dict[int, frozenset[str]] = {}
    dpaths: dict[int, frozenset[str]] = {}
    apaths: dict[int, frozenset[str]] = {}
    if not ids:
        return direct, ancestors, dpaths, apaths
    memberships: list[tuple[int, int]] = []
    for chunk in chunked(ids):
        memberships.extend(s.execute(
            select(ItemGroup.item_id, ItemGroup.group_id)
            .where(ItemGroup.item_id.in_(chunk))
        ).all())
    if not memberships:
        return direct, ancestors, dpaths, apaths
    # Small tables (a library has dozens of groups): load the whole tree once.
    names = {gid: name for gid, name in s.execute(
        select(Group.id, Group.name)).all()}
    parent = {gid: pid for gid, pid in s.execute(
        select(GroupParent.group_id, GroupParent.parent_group_id)).all()}

    anc_cache: dict[int, frozenset[str]] = {}

    def ancestor_names(gid: int) -> frozenset[str]:
        cached = anc_cache.get(gid)
        if cached is not None:
            return cached
        out: set[str] = set()
        cur, hops = parent.get(gid), 0
        while cur is not None and hops < 100:  # hop cap guards a cycle
            name = names.get(cur)
            if name:
                out.add(name.strip().lower())
            cur = parent.get(cur)
            hops += 1
        frozen = frozenset(out)
        anc_cache[gid] = frozen
        return frozen

    path_cache: dict[int, str] = {}

    def path_str(gid: int) -> str:
        cached = path_cache.get(gid)
        if cached is None:
            cached = grouppath.joined(grouppath.path_of(gid, names, parent))
            path_cache[gid] = cached
        return cached

    def ancestor_paths(gid: int) -> set[str]:
        out: set[str] = set()
        cur, hops = parent.get(gid), 0
        while cur is not None and hops < 100:  # the hop cap guards a cycle
            out.add(path_str(cur))
            cur = parent.get(cur)
            hops += 1
        return out

    d_by_item: dict[int, set[str]] = {}
    a_by_item: dict[int, set[str]] = {}
    dp_by_item: dict[int, set[str]] = {}
    ap_by_item: dict[int, set[str]] = {}
    for item_id, gid in memberships:
        name = names.get(gid)
        if name:
            d_by_item.setdefault(item_id, set()).add(name.strip().lower())
            dp_by_item.setdefault(item_id, set()).add(path_str(gid))
        a_by_item.setdefault(item_id, set()).update(ancestor_names(gid))
        ap_by_item.setdefault(item_id, set()).update(ancestor_paths(gid))
    return (
        {iid: frozenset(v) for iid, v in d_by_item.items()},
        {iid: frozenset(v) for iid, v in a_by_item.items() if v},
        {iid: frozenset(v) for iid, v in dp_by_item.items() if v},
        {iid: frozenset(v) for iid, v in ap_by_item.items() if v},
    )


def load_subject_sets(
    s: Session, ids: list[int]
) -> dict[int, dict[str, list[tuple[Optional[int], Optional[int]]]]]:
    """Per item, its subjects' identity tag names -> the (date, age) of every
    APPEARANCE of that subject in it.

    A subject IS a tag, so the tag is what a query names; `ItemSubject` is what
    says how many times the person is in the picture and how old they are in
    each. A page holding one character at two ages has two answers to "how old
    is she here", and neither is more true than the other — so this is a LIST,
    and a bound matches when ANY entry does.

    An item carrying the tag with no appearance row still answers a bare
    `subject:alice`: the tag is the assignment, the appearances are detail.

    **Either half is derived from the other** where the subject's since-date
    allows it, exactly as the sidebar shows it: someone who types the year of
    the picture has said the age too, and a search for "aged 10 to 14" must
    find it. Nothing is stored twice — the derivation happens here, on the way
    into the query.
    """
    out: dict[int, dict[str, list[tuple[Optional[int], Optional[int]]]]] = {}
    if not ids:
        return out

    def derive(date, age, since):
        if age is None and date and since:
            age = partialdate.age_at(since, date)
        elif date is None and age is not None and since:
            date = partialdate.date_from_age(since, age)
        return (date, age)

    for chunk in chunked(ids):
        for item_id, name in s.execute(
            select(ItemTag.item_id, Tag.name)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .join(Subject, Subject.tag_id == Tag.id)
            .where(ItemTag.item_id.in_(chunk), ItemTag.negative.is_(False))
        ).all():
            out.setdefault(item_id, {}).setdefault(name.lower(), [])

    for chunk in chunked(ids):
        for item_id, name, date, age, since in s.execute(
            select(ItemSubject.item_id, Tag.name, ItemSubject.when_date,
                   ItemSubject.when_age, Subject.since_date)
            .join(Subject, Subject.id == ItemSubject.subject_id)
            .join(Tag, Tag.id == Subject.tag_id)
            .join(ItemTag, (ItemTag.tag_id == Tag.id)
                           & (ItemTag.item_id == ItemSubject.item_id))
            .where(ItemSubject.item_id.in_(chunk), ItemTag.negative.is_(False))
        ).all():
            states = out.setdefault(item_id, {}).setdefault(name.lower(), [])
            state = derive(date, age, since)
            # An appearance nobody dated says nothing the bare tag has not
            # already said, and a list of (None, None) would make every age
            # bound match.
            if state == (None, None) or state in states:
                continue
            states.append(state)
    # A tag with no dated appearance keeps one empty state, so `subject:alice`
    # matches while `subject:alice#12` does not.
    for names in out.values():
        for name, states in names.items():
            if not states:
                states.append((None, None))
    return out


def load_taken_windows(s: Session, ids: list[int]) -> dict[int, tuple[int, int]]:
    """Per item, the inclusive ``YYYYMMDDHHMMSS`` window it was taken in.

    Three sources, in order, and only the first that answers:

    1. what somebody typed (`Item.taken_at`) — an override, so a re-index from
       the files can never throw it away;
    2. the indexed EXIF `date_taken`;
    3. the SPAN OF ITS EVENTS. A photograph from a convention that ran 5–10
       January was taken then, which is the most anyone can say and is enough
       to find it. Only as a fallback: a picture with a date of its own never
       inherits one, which is the whole point of having typed it.

    A partial value is a window, not a point: "2020" covers the year, which is
    what makes a search for the first week of January find it.

    ``TAKEN_NONE`` is an answer and STOPS the walk: somebody said this picture
    has no date, so the EXIF the scanner invented and the event it happens to
    carry are both wrong, and `!TAKEN:` should find it.
    """
    from .db import TAKEN_NONE, Item, Occasion

    out: dict[int, tuple[int, int]] = {}
    if not ids:
        return out

    # One definition of "what does a partial capture date cover", shared with
    # the evaluator that compares against it.
    window = q_taken_window

    settled: set[int] = set()
    for chunk in chunked(ids):
        for item_id, taken in s.execute(
            select(Item.id, Item.taken_at)
            .where(Item.id.in_(chunk), Item.taken_at.is_not(None))
        ).all():
            settled.add(item_id)
            if taken != TAKEN_NONE:
                out[item_id] = window(taken)

    rest = set(ids) - out.keys() - settled
    # Through `effective_nums`, so a capture date somebody PINNED to the item
    # wins over whatever the active file's EXIF says — which is the whole point
    # of promoting one, and the same precedence the two other readers of this
    # value use.
    from .itemmeta import effective_nums

    for item_id, value in effective_nums(s, rest, "date_taken").items():
        if value:
            out[item_id] = window(int(value))

    rest -= out.keys()
    for chunk in chunked(rest):
        # An event's span is YYYYMMDD; `window` pads it to the day's end.
        for item_id, start, end in s.execute(
            select(ItemTag.item_id, Occasion.start_date, Occasion.end_date)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .join(Occasion, Occasion.tag_id == Tag.id)
            .where(ItemTag.item_id.in_(chunk), ItemTag.negative.is_(False))
        ).all():
            spans = [x for x in (start, end) if x]
            if not spans:
                continue
            lo = window(min(spans))[0]
            hi = window(max(spans))[1]
            have = out.get(item_id)
            out[item_id] = (min(lo, have[0]), max(hi, have[1])) if have else (lo, hi)
    return out


def load_face_counts(s: Session, ids: list[int]) -> dict[int, tuple[int, int]]:
    """Per item: how many faces it has, and how many of those are unnamed.

    A dismissed face counts as neither — it is on record so a detector does not
    re-offer it, not because there is a face there.
    """
    from .db import Face

    out: dict[int, tuple[int, int]] = {}
    if not ids:
        return out
    # A face is NAMED when an appearance points at it and that appearance's
    # subject has a name; a nameless subject is a hand-merged cluster, which is
    # exactly the state "nobody has said who this is". Scoped to the asked-for
    # items' faces — this used to read every named appearance in the library.
    named: set[int] = set()
    for chunk in chunked(ids):
        named.update(fid for fid, in s.execute(
            select(ItemSubject.face_id)
            .join(Subject, Subject.id == ItemSubject.subject_id)
            .join(Face, Face.id == ItemSubject.face_id)
            .where(Face.item_id.in_(chunk),
                   Subject.tag_id.is_not(None))
        ).all())
    for chunk in chunked(ids):
        for item_id, face_id in s.execute(
            select(Face.item_id, Face.id)
            .where(Face.item_id.in_(chunk), Face.dismissed.is_(False))
        ).all():
            total, unnamed = out.get(item_id, (0, 0))
            out[item_id] = (total + 1, unnamed + (0 if face_id in named else 1))
    return out


def load_sequence_counts(s: Session, ids: list[int]) -> dict[int, int]:
    """Per item: how many DISTINCT sequences it is a member of.

    Distinct, because one item may appear at several positions of one
    sequence (the occurrence rows the grid pages) and "how many books is
    this page in" counts books, not appearances. An item in none simply has
    no row, which the reader's `.get(iid, 0)` turns into the zero
    `INFO:sequence_count=0` searches by (`prefilter._compile_meta` mirrors
    the clause; the two must agree).
    """
    from .db import SequenceItem

    out: dict[int, int] = {}
    if not ids:
        return out
    for chunk in chunked(ids):
        for item_id, n in s.execute(
            select(SequenceItem.item_id,
                   func.count(func.distinct(SequenceItem.sequence_id)))
            .where(SequenceItem.item_id.in_(chunk))
            .group_by(SequenceItem.item_id)
        ).all():
            out[item_id] = int(n)
    return out


def load_file_counts(s: Session, ids: list[int]) -> dict[int, int]:
    """Per item: how many SOURCE FILES it has.

    Every `files` row of the item — derived saves and near-dup alternatives
    included, artifacts excluded (they hang off a file rather than being
    one), which is exactly the list the Sources panel shows. An item with
    none (a sequence container) simply has no row, which the reader's
    `.get(iid, 0)` turns into the zero `INFO:file_count=0` searches by
    (`prefilter._compile_meta` mirrors the clause; the two must agree).
    """
    from .db import File

    out: dict[int, int] = {}
    if not ids:
        return out
    for chunk in chunked(ids):
        for item_id, n in s.execute(
            select(File.item_id, func.count(File.id))
            .where(File.item_id.in_(chunk))
            .group_by(File.item_id)
        ).all():
            out[item_id] = int(n)
    return out


def load_text_counts(s: Session, ids: list[int]) -> dict[int, int]:
    """Per item: how many live TOP-LEVEL text regions its ACTIVE file has.

    Blocks, not words — the same number the sidebar's badge shows. A
    dismissed region counts as nothing, `load_face_counts`' rule, a child
    never counts (a block's lines are its breakdown, not more text), and
    another file's regions never count — a reading is a fact about pixels,
    so the number follows the active file exactly as the badge does
    (`prefilter._compile` mirrors the clause; the two must agree).
    """
    from .db import Item, TextRegion

    out: dict[int, int] = {}
    if not ids:
        return out
    for chunk in chunked(ids):
        for item_id, n in s.execute(
            select(TextRegion.item_id, func.count(TextRegion.id))
            .join(Item, Item.id == TextRegion.item_id)
            .where(TextRegion.item_id.in_(chunk),
                   TextRegion.file_id == Item.active_file_id,
                   TextRegion.parent_id.is_(None),
                   TextRegion.dismissed.is_(False))
            .group_by(TextRegion.item_id)
        ).all():
            out[item_id] = int(n)
    return out


def load_place_sets(s: Session, ids: list[int]) -> dict[int, list[str]]:
    """Per item, the ADDRESS of every place it is at — "" where a place has
    none, which is what a bare `PLACE:` still counts.

    Places hang off tags, so this walks the item's assignments; an UNNAMED
    place (a photo's bare GPS, which has no tag yet) is pinned to its items
    directly and joins in from there.

    THE IDENTITY TAG IS NOT IN HERE. It used to ride along so a bare
    `PLACE:berlin` matched the slug as well as the line, which made the
    condition a second, weaker spelling of the tag search — weaker because it
    silently does not fold sequence containers. What a place says is its
    name; who it IS, the tag search answers.

    Containment needs nothing here: a place inside another IMPLIES it (see
    `ops/places.set_parent`), so the item already carries the parent's tag by
    the time this runs.
    """
    out: dict[int, list[str]] = {}
    if not ids:
        return out
    by_place: dict[int, str] = {}
    reached: list[tuple[int, int]] = []   # (item_id, location_id)
    # A PLACE IS REACHED THROUGH THE IMPLICATIONS TOO, which is the whole of
    # the hierarchy: `shibuya_crossing` is inside `tokyo`, so an item carrying
    # the first is at the second — and it genuinely carries the second's tag,
    # since setting the parent wrote the implication. Reading `item_tags`
    # alone would answer "no", and the tag search would answer "yes" about the
    # very same item.
    from .resolve import tag_implications

    implies = tag_implications(s)
    for chunk in chunked(ids):
        for item_id, lid, line in s.execute(
            select(ItemTag.item_id, Location.id, Location.name)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .join(Location, Location.tag_id == Tag.id)
            .where(ItemTag.item_id.in_(chunk), ItemTag.negative.is_(False))
        ).all():
            by_place.setdefault(lid, line or "")
            reached.append((item_id, lid))
    # The implied half: every place whose tag an item's own tags entail.
    place_by_tag: dict[str, tuple[int, str]] = {}
    for lid, line, name in s.execute(
        select(Location.id, Location.name, Tag.name)
        .join(Tag, Tag.id == Location.tag_id)
    ).all():
        place_by_tag[name] = (lid, line or "")
    if place_by_tag:
        for chunk in chunked(ids):
            for item_id, carried in s.execute(
                select(ItemTag.item_id, Tag.name)
                .join(Tag, Tag.id == ItemTag.tag_id)
                .where(ItemTag.item_id.in_(chunk), ItemTag.negative.is_(False))
            ).all():
                for name in implies.get(carried, ()):
                    hit = place_by_tag.get(name)
                    if hit is None:
                        continue
                    by_place.setdefault(hit[0], hit[1])
                    if (item_id, hit[0]) not in reached:
                        reached.append((item_id, hit[0]))
    for chunk in chunked(ids):
        for item_id, lid, line in s.execute(
            select(ItemLocation.item_id, Location.id, Location.name)
            .join(Location, Location.id == ItemLocation.location_id)
            .where(ItemLocation.item_id.in_(chunk))
        ).all():
            by_place.setdefault(lid, line or "")
            reached.append((item_id, lid))
    for item_id, lid in reached:
        out.setdefault(item_id, []).append(by_place[lid])
    return out


def load_event_sets(
    s: Session, ids: list[int]
) -> dict[int, dict[str, tuple[Optional[int], Optional[int]]]]:
    """Per item, its events' identity tag names -> that event's own span.

    Flat, unlike `load_subject_sets`: an event's dates live on the catalog row,
    so one event on one item is one span. Reads `ItemTag` directly like its two
    siblings here, which means an event reached only through an IMPLICATION is
    not seen — consistent with `subject:` and `place:`, and deliberately not
    fixed alone.
    """
    out: dict[int, dict[str, tuple[Optional[int], Optional[int]]]] = {}
    if not ids:
        return out
    for chunk in chunked(ids):
        for item_id, name, start, end in s.execute(
            select(ItemTag.item_id, Tag.name,
                   Occasion.start_date, Occasion.end_date)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .join(Occasion, Occasion.tag_id == Tag.id)
            .where(ItemTag.item_id.in_(chunk), ItemTag.negative.is_(False))
        ).all():
            out.setdefault(item_id, {})[name.lower()] = (start, end)
    return out


def load_link_sets(
    s: Session, ids: list[int]
) -> tuple[dict[int, list[frozenset[str]]], dict[int, list[frozenset[str]]]]:
    """Outgoing/incoming relationship link-tag sets per item (one frozenset per
    relationship)."""
    outgoing: dict[int, list[frozenset[str]]] = {}
    incoming: dict[int, list[frozenset[str]]] = {}
    if not ids:
        return outgoing, incoming
    id_set = set(ids)
    # Columns, not ORM entities — nothing here needs a mapped object — and
    # deduped by relationship id: with chunked ids a relationship whose two
    # ends land in different chunks is returned twice.
    rels: dict[int, tuple[int, int]] = {}
    for chunk in chunked(ids):
        for rid, from_id, to_id in s.execute(
            select(Relationship.id, Relationship.from_item_id,
                   Relationship.to_item_id)
            .where(Relationship.from_item_id.in_(chunk)
                   | Relationship.to_item_id.in_(chunk))
        ).all():
            rels[rid] = (from_id, to_id)
    tags_by_rel: dict[int, set[str]] = {}
    for chunk in chunked(rels):
        for rid, name in s.execute(
            select(RelationshipTag.relationship_id, RelationshipTag.name)
            .where(RelationshipTag.relationship_id.in_(chunk))
        ).all():
            tags_by_rel.setdefault(rid, set()).add(name.lower())
    for rid, (from_id, to_id) in rels.items():
        tagset = frozenset(tags_by_rel.get(rid, set()))
        if from_id in id_set:
            outgoing.setdefault(from_id, []).append(tagset)
        if to_id in id_set:
            incoming.setdefault(to_id, []).append(tagset)
    return outgoing, incoming


#: Up to this tolerance the neighbourhood is ENUMERATED (see below); past it
#: the signatures are scanned. 3 is where `sum(C(56, k))` (29,317) stops
#: being smaller than a library's own row count.
ENUMERATED_TOL = 3


def neighbourhood(sig: int, tol: int) -> list[int]:
    """Every 56-bit signature within Hamming distance ``tol`` of ``sig``.

    Pure, and exported for the test that holds it to a brute-force popcount:
    an off-by-one here would narrow a search with nothing to see, since the
    scan it replaces answers the same question correctly.
    """
    from itertools import combinations

    out = [sig]
    for k in range(1, tol + 1):
        for combo in combinations(range(SIG_BITS), k):
            v = sig
            for b in combo:
                v ^= 1 << b
            out.append(v)
    return out


#: `colorkey.color_signature` packs 56 bits — SQLite's INTEGER is signed.
SIG_BITS = 56


def load_similar_sets(
    s: Session, conditions,
) -> dict[str, set[int]]:
    """Resolve each colour condition to the ITEM IDS it matches.

    ``SimilarCond.key()`` -> the set of items within its tolerance of its
    pivot, resolved once per query however many nodes share a pivot.

    TWO WAYS OF ASKING ONE QUESTION, and which runs is decided by the
    tolerance rather than guessed. A signature within Hamming distance
    ``tol`` of the pivot is one of ``sum(C(56, k) for k <= tol)`` VALUES, so
    for a small tolerance the neighbourhood can simply be ENUMERATED and
    looked up through ``ix_files_color_sig``: 57 values at 1, 1,597 at 2,
    29,317 at 3. Past that it doubles the library's row count and the scan
    is cheaper. Measured on a million-item library with realistic
    signatures: 4 / 17 / 61 ms for tolerance 1 / 2 / 3, against 240 ms for
    the scan that answered all of them before — and the DEFAULT sits inside
    the enumerated range on purpose.

    The scan is what remains for a wide tolerance, and it is honest about
    what it is: every signature into Python and a popcount each. A search
    that admits a tenth of the library is a deliberate ask, and there is
    nothing to make fast about it — the id set it produces is the expensive
    half (see `prefilter._compile_similar`).

    Colour is the only space here. Banding it the way the perceptual hash is
    banded would mean a second column set whose only caller is this — and,
    worse, one living next to the near-dup probe where somebody would
    eventually wire it into matching. Colour is a browsing aid; see
    :mod:`media_compost.colorkey`.

    Resolving here rather than in ``query`` or ``prefilter`` is what keeps
    those two free of the probe: the compiler and the evaluator both just
    read a set.
    """
    from .db import File, Item, chunked
    from .query import DEFAULT_COLOR_TOL, MAX_SIMILAR_TOL

    out: dict[str, set[int]] = {}
    if not conditions:
        return out

    colors: Optional[list[tuple[int, int]]] = None

    for cond in conditions:
        key = cond.key()
        if key in out:
            continue
        out[key] = found = set()
        tol = DEFAULT_COLOR_TOL if cond.tol is None else int(cond.tol)
        if tol < 0 or tol > MAX_SIMILAR_TOL:
            # Out of range resolves to "nothing", never to a clamp: the router
            # refuses such a value up front, so reaching here means a script
            # built the node by hand and should see an empty answer rather
            # than a different question silently answered.
            continue
        pivot = s.execute(
            select(Item.id, Item.active_file_id).where(Item.uid == cond.uid)
        ).first()
        if pivot is None or pivot[1] is None:
            continue
        src = s.execute(
            select(File.color_sig).where(File.id == pivot[1])
        ).scalar_one_or_none()
        if src is None:
            continue  # a video, or a file stored before the signature existed

        if tol <= ENUMERATED_TOL:
            for chunk in chunked(neighbourhood(int(src), tol), 900):
                found.update(s.execute(
                    select(File.item_id).where(File.color_sig.in_(chunk))
                ).scalars().all())
            continue
        if colors is None:
            colors = list(s.execute(
                select(File.item_id, File.color_sig)
                .where(File.color_sig.is_not(None))
            ).all())
        found.update(iid for iid, sig in colors
                     if (sig ^ src).bit_count() <= tol)
    return out
