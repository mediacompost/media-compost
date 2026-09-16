"""Tag sets: imported tag lists that stay APART from the library's tags.

A set is names with usage descriptions, optional popularity counts, aliases,
implied names and nestable categories (`db.TagSet` and its four tables). It
is read-only ADVICE — the autocomplete offers its names, the tags list wears
a capsule for a tag a set knows, the `?` shows its description — and the
LIBRARY IS WRITTEN ONLY BY AN ASSIGNMENT: `tagcatalog.get_or_create` is the
one door, and it asks this module two things when it CREATES a row — is the
name a set's alias (then the canonical is what gets made), and what does the
set say the name IMPLIES (those are minted and linked as ordinary
`TagImplication`s, each its own logged event). Nothing else is ever copied
out of a set. (The implications were dropped for a round — owner decision
2026-09, reversed the same month: a set that knows `1girl` entails `solo` is
saying something a library has to be told once per name otherwise, and the
table was kept through the whole detour.)

No set is special. The shipped Booru list is a TEMPLATE (`tagsets/*.json`,
package data beside this module's parent), and `create_from_template` makes
an ordinary set of the library's from it — editable, deletable, the same as
an imported file. Nothing is installed on open; a shipped set an older build
installed is unlocked into an ordinary one (`unlock_builtin_sets`). There
USED to be a per-library set as well (`key="library"`, rung v16), holding
what somebody typed into a tag's description field; it went with rung v17,
because the only way to describe a tag is a set somebody made or imported.

Readers take a Session; the logged ops take a Ctx and log one event each
(`ops/actions.py`, the `tag_set` block). ONE PRIMITIVE is deliberately
unlogged, as the CLAUDE.md list records: `unlock_builtin_sets` is a system
write at open (no Ctx exists yet).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import case, delete, func, insert, literal, or_, select
from sqlalchemy.orm import Session, aliased

from .. import tagsetformat as fmt
from ..db import (
    Location,
    MetaTag,
    Occasion,
    Subject,
    Tag,
    TagImplication,
    TagMetaTag,
    TagSet,
    TagSetCategory,
    TagSetEntry,
    TagSetImplication,
    chunked,
)
from . import actions
from .context import Ctx
from .errors import Conflict, Invalid, NotFound, Refused

#: The shipped TEMPLATES — `tagsets/*.json`, package data. Nothing installs
#: one: a set is CREATED from a template (`create_from_template`), after which
#: it is an ordinary set of the library's, editable and deletable. (The
#: shipped set was an installed, locked row in every library for a round —
#: owner decision, 2026-09: a set you cannot edit or remove is not yours.)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "tagsets"

#: HOW MANY NEW ENTRIES GO IN AT ONCE (`bulk_entries`). Big enough that the
#: per-statement cost stops mattering, small enough that one chunk's rows and
#: their bound parameters are an ordinary amount of memory — and SQLite has a
#: ceiling on the parameters in one statement, which a wider row would reach
#: first.
_INSERT_CHUNK = 500

#: An entry this import has made but not written yet: it is in `have` so the
#: rows after it dedup against it, and it has no id until the chunk goes in.
_PENDING = -1

#: Past this many entries an import carries no `undo` block, and its event
#: stops offering Revert (`history.can_revert`) — the `delete_group` rule.
UNDO_ENTRIES_MAX = 5000


# ---- readers ------------------------------------------------------------------

def by_id(s: Session, set_id: int) -> TagSet:
    row = s.get(TagSet, set_id)
    if row is None:
        raise NotFound("tag set not found", code="tag_set_not_found")
    return row


def by_key(s: Session, key: str) -> Optional[TagSet]:
    return s.execute(select(TagSet).where(TagSet.key == key)).scalars().first()


#: THE LIBRARY'S OWN SET — the first pill in the Tags tab, and the one row in
#: `tag_sets` that is not a tag set somebody imported.
#:
#: It holds NO entries, ever. The library's names live in `tags`, which is
#: what the Items list has always drawn; what this row exists for is to OWN
#: `TagSetCategory` rows, so the library's tags can be filed in a nestable
#: tree (`Tag.category_id`) using the same model, the same tree endpoint and
#: the same drag gestures an imported set already has, rather than a second
#: category implementation beside it.
#:
#: THE ROW IS LAZY. Nothing creates it at open — a library that never files a
#: tag never grows it — and no read may create it, so `library_set` answers
#: None and only `ensure_library_set` (a write path: making the first
#: category, or editing the set's own properties) brings it into being.
LIBRARY_KEY = "library"

#: What the pill reads before anybody renames it.
LIBRARY_NAME = "Library"


def _every_set(s: Session) -> list[TagSet]:
    """Every row in the table, the library's included. Only the few callers
    that are about the TABLE want this; the ones about TAG SETS want
    `all_sets`."""
    return list(s.execute(select(TagSet).order_by(TagSet.position, TagSet.id))
                .scalars())


def library_set(s: Session) -> Optional[TagSet]:
    """The library's own set row, or None where nothing has needed it yet.

    A READ, and it stays one: see `LIBRARY_KEY`.
    """
    return by_key(s, LIBRARY_KEY)


def ensure_library_set(ctx: Ctx) -> TagSet:
    """The library's own set row, made if this is the first thing to need it.

    Deliberately not `create_tag_set`: that one logs a `create_tag_set`
    event, and the library's set is not something somebody created — it is
    the library, which was always there. Nothing to undo, so nothing logged.
    """
    s = ctx.session
    row = library_set(s)
    if row is not None:
        return row
    row = TagSet(key=LIBRARY_KEY, name=LIBRARY_NAME, description="",
                 version=0, builtin=False, enabled=True, position=0)
    s.add(row)
    s.flush()
    return row


def all_sets(s: Session) -> list[TagSet]:
    """The imported tag sets, in position order — NOT the library's own.

    Every caller of this one is asking about advice: what feeds the
    autocomplete, what capsules a name wears, what the `?` popover reads,
    what an export offers. The library's set answers none of those (it has no
    entries), and letting it through meant every one of them carrying a
    "…except that one" clause of its own.
    """
    return list(s.execute(
        select(TagSet).where(TagSet.key != LIBRARY_KEY)
        .order_by(TagSet.position, TagSet.id)).scalars())


def enabled_ids(s: Session) -> list[int]:
    """The enabled sets in position order — what the autocomplete, the
    capsules, the browse tree and the door's two questions all read."""
    return list(s.execute(
        select(TagSet.id)
        .where(TagSet.enabled.is_(True), TagSet.key != LIBRARY_KEY)
        .order_by(TagSet.position, TagSet.id)).scalars())


@dataclass(frozen=True)
class Hit:
    """One set's claim on a name: which set, its popularity figure, and the
    canonical name when the hit is an ALIAS."""
    set_id: int
    key: str
    name: str
    count: Optional[int]
    alias_of: Optional[str]


def _set_meta(s: Session, ids: list[int]) -> dict[int, tuple[str, int, str]]:
    """set id -> (key, position, name)."""
    return {r.id: (r.key, r.position, r.name) for r in s.execute(
        select(TagSet.id, TagSet.key, TagSet.position, TagSet.name)
        .where(TagSet.id.in_(ids))).all()} if ids else {}


def name_map(s: Session, lnames: Optional[Iterable[str]] = None
             ) -> dict[str, list[Hit]]:
    """lowercase name -> every enabled set's claim on it (entries and
    aliases), sets in position order. Over the whole catalog when `lnames` is
    None — the shape `lib.db.cached` holds for the whole-catalog listing — or
    over the page given."""
    ids = enabled_ids(s)
    if not ids:
        return {}
    meta = _set_meta(s, ids)
    out: dict[str, list[Hit]] = {}
    want = None if lnames is None else list(dict.fromkeys(lnames))
    # Entries, then aliases: an entry is the stronger claim, so it lands first
    # and the merge below keeps it ahead of an alias from another set.
    entries = (select(TagSetEntry.lname, TagSetEntry.tag_set_id,
                      TagSetEntry.count)
               .where(TagSetEntry.tag_set_id.in_(ids), NOT_ALIAS))
    for lname, sid, count in _rows_in(s, entries, TagSetEntry.lname, want):
        key, _, nm = meta[sid]
        out.setdefault(lname, []).append(Hit(sid, key, nm, count, None))
    aliases = (select(Alias.lname, Alias.tag_set_id,
                      TagSetEntry.name, TagSetEntry.count)
               .join(TagSetEntry, TagSetEntry.id == Alias.alias_of_id)
               .where(Alias.tag_set_id.in_(ids),
                      *scope_clauses(*alias_scopes_off(s, ids), TagSetEntry)))
    for lname, sid, canon, count in _rows_in(s, aliases, Alias.lname, want):
        key, _, nm = meta[sid]
        out.setdefault(lname, []).append(Hit(sid, key, nm, count, canon))
    for hits in out.values():
        hits.sort(key=lambda h: (h.alias_of is not None, meta[h.set_id][1], h.set_id))
    return out


#: A SET'S ALIASES ARE ROWS OF THE SET, pointing at their target through
#: `alias_of_id` — which is what a library alias always was. `TagSetAlias`
#: was a table beside the entries until the two tag sets became one
#: shape; this is the handle the joins that used it now take, so a query
#: still names two things and reads the way it always did.
Alias = aliased(TagSetEntry, name="tag_set_alias")

#: …and an ENTRY is a row of the set that is NOT one. Every list, count and
#: lookup of "the set's entries" carries this, exactly as the library's own
#: reads carry `Tag.alias_of_id.is_(None)`.
NOT_ALIAS = TagSetEntry.alias_of_id.is_(None)


def _rows_in(s: Session, stmt, col, want: Optional[list[str]]):
    """`stmt`, restricted to `col IN want` in chunks — or whole when want is
    None."""
    if want is None:
        return s.execute(stmt).all()
    out = []
    for chunk in chunked(want):
        out.extend(s.execute(stmt.where(col.in_(chunk))).all())
    return out


@dataclass
class SetSays:
    """Everything one enabled set says about one name — what the `?` popover
    draws. More than the description it is named for: a set that knows a tag
    and has not written a sentence about it still knows how common it is,
    what else it is called, what it entails and what entails it, and that is
    a popover worth opening.
    """
    key: str
    text: str
    #: The names down to the category it is filed under.
    trail: list[str]
    #: The set's own popularity figure, where it has one.
    count: Optional[int]
    #: The entry's other spellings, what it entails, and — read the other way
    #: round — the entries of the SAME set that entail it.
    aliases: list[str]
    implies: list[str]
    implied_by: list[str]
    #: WHAT THE SET LABELS THE NAME WITH — its meta tags. The popover drew
    #: everything else a set says and left these out, though they are often
    #: the whole of what a dump knows: which kind of name it is, what a
    #: dataset should do with it.
    meta: list[str] = field(default_factory=list)
    #: THE ENTRY'S OWN NAME, where the name asked about is an ALIAS of it.
    #: Empty when the two are the same. Without it the popover showed a
    #: description for something it never named: ask about `manga`, read a
    #: sentence about comics, with nothing saying the set files both under
    #: one entry.
    alias_of: str = ""
    #: The one-liner it says the tag should carry, and what it says the tag
    #: IS — the same records an entry's row draws, so the `?` answers "who
    #: is this" from a field with no list behind it. Absent where the set
    #: says nothing of the kind.
    comment: str = ""
    subject: Optional[dict] = None
    place: Optional[dict] = None
    event: Optional[dict] = None

    def as_dict(self) -> dict:
        """The wire's `TagSetText`. HERE, not in a router: the tags list,
        the autocomplete and `/describe` all shape one of these, and while
        each did it itself the three came to disagree about what a set
        says — which is a bug nobody sees until one surface is missing a
        field the others have."""
        return {"key": self.key, "text": self.text, "trail": list(self.trail),
                "count": self.count, "aliases": list(self.aliases),
                "implies": list(self.implies),
                "implied_by": list(self.implied_by),
                "meta": list(self.meta), "alias_of": self.alias_of,
                "comment": self.comment,
                # EVERY FIELD, defaults filled. `record_of` answers sparsely
                # — it is what a row's response model fills in — and this
                # endpoint has no model to fill it, so the two surfaces
                # would have described the same tag differently.
                **{k: full_record(k, getattr(self, k)) for k in RECORD_FIELDS}}


def implied_by_for(s: Session, set_ids: Sequence[int], lnames: Sequence[str]
                   ) -> dict[tuple[int, str], list[str]]:
    """(set id, lowercase name) -> the entries of that set that ENTAIL it.

    The implication table read backwards. It is the half of "what does this
    set say" that an entry cannot carry, since the fact lives on the other
    entries; one query over the window's names, so a list of fifty rows
    costs one statement rather than fifty.
    """
    if not set_ids or not lnames:
        return {}
    #: TWO INDEXED STEPS, AND NEITHER NAMES THE TAG SET (2026-09). Asked as
    #: one join with `tag_set_id IN (…)` beside the name probe, SQLite —
    #: which has no statistics here and never will — takes the equality on
    #: `tag_set_id`, walks the SET's every row and tests the implication per
    #: row: 1.36 seconds a detail band on the 132,255-entry Characters set,
    #: for a handful of rows. It is the `_index_rows` category lesson again,
    #: one table along: ask by the column you have an index for, and settle
    #: the scope in Python over what comes back.
    want_sets = {int(x) for x in set_ids}
    hits: list[tuple[int, str]] = []
    for chunk in chunked(list(dict.fromkeys(lnames))):
        hits.extend((int(eid), nm) for eid, nm in s.execute(
            select(TagSetImplication.entry_id, TagSetImplication.implies_lname)
            .where(TagSetImplication.implies_lname.in_(chunk))).all())
    if not hits:
        return {}
    owner: dict[int, tuple[int, str, str]] = {}
    for chunk in chunked(sorted({eid for eid, _ in hits})):
        for eid, sid, name, lname in s.execute(
                select(TagSetEntry.id, TagSetEntry.tag_set_id,
                       TagSetEntry.name, TagSetEntry.lname)
                .where(TagSetEntry.id.in_(chunk))).all():
            if sid is not None:
                owner[int(eid)] = (int(sid), name, lname)
    #: …in the ENTRIES' own name order, which is what the join's
    #: `order_by(TagSetEntry.lname)` said.
    pairs: dict[tuple[int, str], list[tuple[str, str]]] = {}
    for eid, implied in hits:
        got = owner.get(eid)
        if got is None or got[0] not in want_sets:
            continue
        pairs.setdefault((got[0], implied), []).append((got[2], got[1]))
    return {k: [name for _l, name in sorted(v)] for k, v in pairs.items()}


def library_says(s: Session, lnames: Iterable[str]) -> dict[str, SetSays]:
    """What the LIBRARY says about each of these names.

    The library is a tag set now, so it answers the `?` popover like any
    other — and FIRST, because it is the tag set somebody is actually
    working in. It answers only where it has something to say: the long
    form, the one-liner, or a category to name. What it does NOT carry here
    is the aliases, the implications and the records — those are the tag's
    own columns, already on the row the popover was opened from, and reading
    them again per name would put four more statements on a path that runs
    per keystroke.

    Keyed by the library set's key, so the frontend tells it apart the same
    way it tells two imported sets apart.
    """
    want = list(dict.fromkeys(lnames))
    if not want:
        return {}
    from ..db import Tag
    rows = list(_rows_in(
        s, select(Tag.lname.label("lname"), Tag.description,
                  Tag.comment, Tag.category_id),
        Tag.lname, want))
    if not rows:
        return {}
    lib = library_set(s)
    trails = (category_trails(s, lib.id)
              if lib is not None and any(r[3] for r in rows) else {})
    out: dict[str, SetSays] = {}
    for lname, description, comment, cid in rows:
        if not (description or "").strip() and not (comment or "").strip() \
                and cid is None:
            continue
        out[lname] = SetSays(
            key=LIBRARY_KEY, text=description or "",
            trail=trails.get(cid, []) if cid is not None else [],
            count=None, aliases=[], implies=[], implied_by=[],
            comment=comment or "")
    return out


def descriptions_for(s: Session, lnames: Iterable[str]
                     ) -> dict[str, list[SetSays]]:
    """lowercase name -> what each enabled FOREIGN set says about it, sets in
    position order (an alias answers with its entry's row).

    A set answers for every name it KNOWS, described or not: the popover
    shows its count, its other spellings and its implications either way,
    and a `?` that appears only where somebody wrote a sentence hides the
    rest of what the set knows.

    THE LIBRARY'S OWN WORDS ARE NOT HERE, though the popover draws them
    first. This runs per KEYSTROKE (`/api/tags/names`), and every caller
    that wants the library's half already holds it without another
    statement: a tag row carries `description`, `comment` and
    `category_trail` off the same select that fetched the row, and the
    autocomplete carries `description` off its own. `/describe` — a hover
    with no row behind it — is the one caller with nothing to read, and it
    asks `library_says` itself.
    """
    ids = enabled_ids(s)
    want = list(dict.fromkeys(lnames))
    if not ids or not want:
        return {}
    meta = _set_meta(s, ids)
    # (position, set id, entry id, text, category id) per name.
    got: dict[str, list[tuple[int, int, int, str, Optional[int]]]] = {}
    entries = (select(TagSetEntry.lname, TagSetEntry.tag_set_id, TagSetEntry.id,
                      TagSetEntry.description, TagSetEntry.category_id)
               .where(TagSetEntry.tag_set_id.in_(ids), NOT_ALIAS))
    for lname, sid, eid, text, cid in _rows_in(s, entries, TagSetEntry.lname, want):
        got.setdefault(lname, []).append((meta[sid][1], sid, eid, text or "", cid))
    #: WHICH NAMES ANSWERED THROUGH A SPELLING, and whose entry. The popover
    #: has to be able to say so — a description for `comic` shown under
    #: `manga` names neither the entry nor the relation otherwise.
    spelled: dict[tuple[str, int], str] = {}
    aliases = (select(Alias.lname, Alias.tag_set_id, TagSetEntry.id,
                      TagSetEntry.description, TagSetEntry.category_id,
                      TagSetEntry.name)
               .join(TagSetEntry, TagSetEntry.id == Alias.alias_of_id)
               .where(Alias.tag_set_id.in_(ids),
                      *scope_clauses(*alias_scopes_off(s, ids), TagSetEntry)))
    for lname, sid, eid, text, cid, entry_name in _rows_in(
            s, aliases, Alias.lname, want):
        got.setdefault(lname, []).append((meta[sid][1], sid, eid, text or "", cid))
        spelled[(lname, sid)] = entry_name
    if not got:
        return {}

    # ONE lookup per KIND over everything that answered, rather than one per
    # row: a window of fifty names costs four statements, not two hundred.
    picked: dict[str, list[tuple[int, int, str, Optional[int]]]] = {}
    for lname, items in got.items():
        items.sort(key=lambda it: (it[0], it[1]))
        seen: set[int] = set()
        for _, sid, eid, text, cid in items:
            if sid in seen:
                continue
            seen.add(sid)
            picked.setdefault(lname, []).append((sid, eid, text, cid))
    eids = [eid for rows in picked.values() for _sid, eid, _t, _c in rows]
    al = aliases_of(s, eids)
    im = implications_of(s, eids)
    counts = dict(s.execute(select(TagSetEntry.id, TagSetEntry.count)
                            .where(TagSetEntry.id.in_(eids))).all()) if eids else {}
    # …and what each entry says the TAG is. One read over the same ids: the
    # popover draws it, so a `?` opened from a field answers "who is this"
    # without a list behind it.
    says: dict[int, dict] = {}
    if eids:
        for row in s.execute(select(TagSetEntry).where(
                TagSetEntry.id.in_(eids))).scalars():
            says[row.id] = records_of(row)
    back = implied_by_for(s, ids, list(picked))
    #: …AND WHAT THE SET LABELS EACH ENTRY WITH. One read over the same ids,
    #: beside the aliases and the implications: a meta tag is as much what a
    #: set says about a name as those are.
    labels = meta_of(s, eids) if eids else {}
    trails: dict[int, dict[int, list[str]]] = {}
    out: dict[str, list[SetSays]] = {}
    for lname, rows in picked.items():
        for sid, eid, text, cid in rows:
            if sid not in trails:
                trails[sid] = category_trails(s, sid)
            out.setdefault(lname, []).append(SetSays(
                key=meta[sid][0], text=text,
                trail=list(trails[sid].get(cid, []) if cid is not None else []),
                count=counts.get(eid),
                aliases=al.get(eid, []), implies=im.get(eid, []),
                implied_by=back.get((sid, lname), []),
                meta=labels.get(eid, []),
                alias_of=spelled.get((lname, sid), ""),
                **{k: v for k, v in says.get(eid, {}).items()}))
    return out


def canonical_of_alias(s: Session, name: str) -> Optional[str]:
    """The entry an enabled set says ``name`` is an alias OF, else None. The
    first set in position order answers.

    A NAME SOME SET KNOWS AS AN ENTRY IS NOT AN ALIAS, whatever another set
    calls it (owner decision, 2026-09). Two tag sets disagreeing about
    one word is ordinary — `a` is a tag in one and a spelling of
    `a_(phrase)` in another — and redirecting there would assign a tag
    nobody asked for. The stronger claim wins, and the tag is what somebody
    typed.
    """
    ids = enabled_ids(s)
    if not ids:
        return None
    if s.execute(select(TagSetEntry.id).where(
            TagSetEntry.tag_set_id.in_(ids), NOT_ALIAS,
            TagSetEntry.lname == name.lower()).limit(1)).first():
        return None
    row = s.execute(
        select(TagSetEntry.name)
        .join(Alias, Alias.alias_of_id == TagSetEntry.id)
        .join(TagSet, TagSet.id == Alias.tag_set_id)
        .where(Alias.lname == name.lower(), TagSet.id.in_(ids),
               *scope_clauses(*alias_scopes_off(s, ids), TagSetEntry))
        .order_by(TagSet.position, TagSet.id).limit(1)).first()
    return row[0] if row else None


def implied_names_for(s: Session, name: str) -> list[str]:
    """What the enabled sets say ``name`` entails, in set order, deduped.

    The door's question (`tagcatalog.get_or_create`), asked only for a name
    it is CREATING — a library that already has the tag has already had its
    say about what the tag entails."""
    ids = enabled_ids(s)
    if not ids:
        return []
    rows = s.execute(
        select(TagSetImplication.implies_name)
        .join(TagSetEntry, TagSetEntry.id == TagSetImplication.entry_id)
        .join(TagSet, TagSet.id == TagSetEntry.tag_set_id)
        .where(TagSetEntry.lname == name.lower(), TagSet.id.in_(ids),
               *scope_clauses(*implication_scopes_off(s, ids), TagSetEntry))
        .order_by(TagSet.position, TagSet.id, TagSetImplication.id)).scalars()
    return list(dict.fromkeys(rows))


def implied_names_for_many(s: Session, names: Sequence[str]
                           ) -> dict[str, list[str]]:
    """`implied_names_for` over a whole page of names at once — lowercase
    name -> what the enabled sets say it entails, in set order, deduped.

    Same answer, one statement. The list draws a mark per row for "the
    library does not entail this yet", and asking the single-name question
    two hundred times a page is two hundred four-way joins.
    """
    ids = enabled_ids(s)
    want = list(dict.fromkeys(n.lower() for n in names if n))
    if not ids or not want:
        return {}
    stmt = (select(TagSetEntry.lname, TagSetImplication.implies_name)
            .join(TagSetEntry, TagSetEntry.id == TagSetImplication.entry_id)
            .join(TagSet, TagSet.id == TagSetEntry.tag_set_id)
            .where(TagSet.id.in_(ids),
                   *scope_clauses(*implication_scopes_off(s, ids), TagSetEntry))
            .order_by(TagSet.position, TagSet.id, TagSetImplication.id))
    out: dict[str, list[str]] = {}
    for lname, implied in _rows_in(s, stmt, TagSetEntry.lname, want):
        out.setdefault(lname, []).append(implied)
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def meta_names_for(s: Session, name: str) -> list[tuple[str, str, str]]:
    """What the enabled sets say ``name`` is LABELLED with — the meta tag's
    name, its comment and its description, in set order, deduped by name.

    The door's question, beside `implied_names_for`, and asked at the same
    one moment: a set that knows `hatsune_miku` is a `character` is saying
    something about the NAME, and the library has to be told once per name
    otherwise. The comment and the description ride along because they are
    what a set has to say about the LABEL, and the library's meta namespace
    is where they land if it does not have that label yet.

    Follows `enabled` alone, like the records do: whether the tag set's
    labels are worth taking is not the aliases switch or the implications
    one — those are about spellings and entailments.
    """
    ids = enabled_ids(s)
    if not ids:
        return []
    # AN ALIAS, because the label's row and the entry's are the same TABLE:
    # a set's meta tags are `tags` rows of that set, as its entries are.
    M = aliased(MetaTag, name="set_meta")
    rows = s.execute(
        select(TagMetaTag.name, M.comment, M.description)
        .join(TagSetEntry, TagSetEntry.id == TagMetaTag.tag_id)
        .join(TagSet, TagSet.id == TagSetEntry.tag_set_id)
        # The set's own row for the label, where it has one — matched by
        # LOWERCASE name inside the same set, which is how every name in a
        # tag set is matched.
        .outerjoin(M, (M.tag_set_id == TagSetEntry.tag_set_id)
                   & (M.lname == func.lower(TagMetaTag.name)))
        .where(TagSetEntry.lname == name.lower(), TagSet.id.in_(ids))
        .order_by(TagSet.position, TagSet.id, TagMetaTag.id)).all()
    out: dict[str, tuple[str, str, str]] = {}
    for n, comment, description in rows:
        if n.lower() not in out:
            out[n.lower()] = (n, comment or "", description or "")
    return list(out.values())


#: How far the walk after a page's tags follows the library's implications.
#:
#: A chain longer than this reads as "the library does not entail it", and
#: the sync then adds a direct edge that was already true — a redundant row,
#: never a wrong one. The cap exists because the walk is otherwise unbounded
#: in the library's own size, which is the one thing a page may not be.
_ENTAIL_DEPTH = 12


def _entailed(s: Session, wanted: dict[int, set[int]]) -> dict[int, set[int]]:
    """root tag id -> which of `wanted[root]` it entails, directly or through
    a chain of the library's implications.

    A BREADTH-FIRST WALK FROM THE PAGE'S TAGS, one indexed query per level
    over every root's frontier at once, and a root drops out of the walk the
    moment it has found everything asked of it. What it replaces was
    `resolve.tag_implications` — the whole implication table, closed
    transitively in Python — which is the right shape for a catalog-wide
    read and quite wrong for a page: 530 ms of a 615 ms page on a library of
    200,000 tags, all of it about tags the page never mentions.
    """
    roots = [r for r, want in wanted.items() if want]
    if not roots:
        return {}
    found: dict[int, set[int]] = {r: set() for r in roots}
    seen: dict[int, set[int]] = {r: {r} for r in roots}
    frontier: dict[int, list[int]] = {r: [r] for r in roots}
    for _ in range(_ENTAIL_DEPTH):
        ids = sorted({i for f in frontier.values() for i in f})
        if not ids:
            break
        edges: dict[int, list[int]] = {}
        for chunk in chunked(ids):
            for a, b in s.execute(
                    select(TagImplication.tag_id, TagImplication.implies_id)
                    .where(TagImplication.tag_id.in_(chunk))).all():
                edges.setdefault(a, []).append(b)
        if not edges:
            break
        nxt: dict[int, list[int]] = {}
        for root, step in frontier.items():
            if not wanted[root] - found[root]:
                continue
            ahead = []
            for a in step:
                for b in edges.get(a, ()):
                    if b in seen[root]:
                        continue
                    seen[root].add(b)
                    ahead.append(b)
                    if b in wanted[root]:
                        found[root].add(b)
            if ahead and wanted[root] - found[root]:
                nxt[root] = ahead
        frontier = nxt
    return found


def _library_names(s: Session, lnames: Iterable[str]
                   ) -> tuple[dict[str, int], dict[int, str]]:
    """(lowercase name -> the tag id an ASSIGNMENT of it would land on,
    tag id -> name), for the names the library actually has.

    An alias answers for its target, since that is the tag the door would
    resolve it to. `ix_tags_lname` is an index on `lower(name)`, which is
    why the lookup is spelled that way.
    """
    want = sorted({n.lower() for n in lnames if n})
    if not want:
        return {}, {}
    by_id: dict[int, str] = {}
    alias: dict[str, Optional[int]] = {}
    for tid, name, aid in _rows_in(s, select(Tag.id, Tag.name, Tag.alias_of_id),
                                   Tag.lname, want):
        by_id[tid] = name
        alias[name.lower()] = aid if aid is not None else tid
    return {k: v for k, v in alias.items() if v is not None}, by_id


def in_library(s: Session, names: Sequence[str]) -> set[str]:
    """WHICH OF THESE NAMES THE LIBRARY HAS, lowercased — an entry's name
    resolved the way an assignment would resolve it, aliases included.

    What a row needs in order to know whether it offers to ADD the tag or
    to do something about the implications of a tag that is already there.
    One chunked probe of `ix_tags_lname` with the names we already hold —
    the shape `behind_entry_ids` uses, and for the same reason: asked the
    other way round it is a scan of the tags table.
    """
    have, _ = _library_names(s, names)
    return set(have)


def library_counts(s: Session, names: Sequence[str],
                   pos: Optional[dict[str, int]] = None) -> dict[str, int]:
    """lowercase name -> how many pictures the LIBRARY has under it.

    The `Library` column on an imported set's rows: one number that says
    what the in-library mark used to say, and says how much besides — a name
    the library has on nine hundred pictures and one it has on none read
    very differently when you are deciding what a tag set is worth.

    Blank (absent) where the library does not have the name at all, which is
    not the same as zero: zero is a tag that exists and is on nothing.

    An alias answers with its TARGET's count, exactly as the row does
    everywhere else — assigning it lands there.
    """
    have, by_id = _library_names(s, names)
    if not have:
        return {}
    # THE COUNTS ARE THE LIBRARY'S, so they are the library's cached ones:
    # `effective_tag_counts` is two grouped passes over every assignment and
    # a pure function of the library, which is why the tags router holds it
    # on the revision. A page of a 17,000-entry set may not pay for that
    # twice, so the caller hands its own copy in.
    if pos is None:
        from ..prefilter import effective_tag_counts
        pos, _ind, _neg = effective_tag_counts(s)
    return {lname: int(pos.get(by_id.get(tid, ""), 0))
            for lname, tid in have.items()}


def missing_implications(s: Session, rows: Sequence[TagSetEntry]
                         ) -> dict[int, list[str]]:
    """entry id -> the names it says it entails that the LIBRARY does not.

    A set's implications reach the library through the door
    (`tagcatalog.get_or_create`) and only for a name it is CREATING: a tag
    the library already had when the set arrived — or one whose entry gained
    an `implies` afterwards — entails nothing the set says, silently, and the
    list drew the names as though it did. This is the difference, so the row
    can strike through what is only advice and the ⋯ menu can offer to close
    it (`tagcatalog.sync_set_implications`).

    Two rules about what does NOT count as missing. A name the library has
    never heard of is not out of sync — nothing is claiming it entails
    anything yet, and it will be minted the first time the tag is assigned.
    And the test is the library's transitive closure, not its direct edges:
    a tag that entails the name through a chain already behaves as the set
    says, and marking that missing would be a mark nothing is wrong with.

    COSTS THE PAGE, NOT THE LIBRARY. Everything here is keyed on the names
    the page actually holds — `_entailed` walks out from those tags rather
    than closing the whole implication table.
    """
    if not rows:
        return {}
    wanted = implied_names_for_many(s, [r.name for r in rows])
    if not wanted:
        return {}
    names = {r.name.lower() for r in rows}
    for v in wanted.values():
        names.update(n.lower() for n in v)
    tag_of, by_id = _library_names(s, names)
    if not tag_of:
        return {}

    # WHAT TO ASK THE WALK, per root tag: the ids of the names its entries
    # say it entails. A said name the library does not have is not missing
    # (it is unassigned), and one that resolves to the root itself is the
    # edge the door skips too.
    said_by_entry = implications_of(s, [r.id for r in rows])
    asked: dict[int, set[int]] = {}
    per_row: list[tuple[TagSetEntry, int, list[str]]] = []
    for r in rows:
        root = tag_of.get(r.name.lower())
        if root is None:
            continue
        said = {n.lower() for n in wanted.get(r.name.lower(), ())}
        if not said:
            continue
        mine = [n for n in said_by_entry.get(r.id, []) if n.lower() in said]
        if not mine:
            continue
        # Only the names the library HAS are a question for the walk. One it
        # does not have is missing outright — the sync would create it and
        # link it — and one that resolves to the root itself is the edge the
        # door skips too.
        ids = {t for n in mine if (t := tag_of.get(n.lower())) is not None}
        ids.discard(root)
        if ids:
            asked.setdefault(root, set()).update(ids)
        per_row.append((r, root, mine))
    entailed = _entailed(s, asked)

    out: dict[int, list[str]] = {}
    for r, root, mine in per_row:
        have = entailed.get(root, set())
        gap = []
        for n in mine:
            tid = tag_of.get(n.lower())
            if tid is None:
                gap.append(n)
            elif tid != root and tid not in have:
                gap.append(n)
        if gap:
            out[r.id] = gap
    return out


def records_for_many(s: Session, names: Sequence[str]
                     ) -> dict[str, dict[str, Any]]:
    """What the ENABLED sets say the library's tags should BE — lowercase
    name -> ``{"comment": str, "subject"/"place"/"event": dict}``.

    FIRST SET WINS, per kind, in the sets' own order. Unlike `implies`,
    which unions across sets because two tag sets naming two entailments
    both mean them, a record cannot be unioned: two sets with an address
    each do not describe a place with two addresses. So each kind is
    answered by the first enabled set that has one, and the same for the
    comment — a rule somebody can act on by reordering their sets.

    Not gated on the implications switch: that switch is about what a name
    ENTAILS. A place's parent is written as an implication downstream, and
    rides along here with the rest of the record.
    """
    ids = enabled_ids(s)
    want = list(dict.fromkeys(n.lower() for n in names if n))
    if not ids or not want:
        return {}
    #: BY THE NAME ALONE, and the set settled in Python — the same trap
    #: `implied_by_for` above fell into: joined to `tag_sets` with the
    #: enabled ids in the WHERE, SQLite drove from `ix_tags_set` and walked
    #: the whole tag set (23 ms a band on the Characters set, for 75 names
    #: an index can seek in a fraction of one). `enabled_ids` is already in
    #: the sets' own order, which is the order FIRST SET WINS reads.
    rank = {sid: i for i, sid in enumerate(ids)}
    rows: list[TagSetEntry] = []
    for chunk in chunked(want):
        rows.extend(s.execute(select(TagSetEntry)
                              .where(TagSetEntry.lname.in_(chunk))).scalars())
    rows = [e for e in rows if e.tag_set_id in rank]
    rows.sort(key=lambda e: (rank[e.tag_set_id], e.id))
    out: dict[str, dict[str, Any]] = {}
    for entry in rows:
        got = out.setdefault(entry.lname, {})
        if entry.comment and "comment" not in got:
            got["comment"] = entry.comment
        for kind in RECORD_FIELDS:
            rec = record_of(entry, kind)
            if rec is not None and kind not in got:
                got[kind] = rec
    return {k: v for k, v in out.items() if v}


def records_for(s: Session, name: str) -> dict[str, Any]:
    """`records_for_many` for one name — the door's question."""
    return records_for_many(s, [name]).get(name.lower(), {})


def _library_records(s: Session, tag_ids: Sequence[int]
                     ) -> dict[int, set[str]]:
    """tag id -> which of comment/subject/place/event the LIBRARY already
    has on it. Four chunked probes, each on an indexed column."""
    out: dict[int, set[str]] = {t: set() for t in tag_ids}
    if not tag_ids:
        return out
    for chunk in chunked(sorted(set(tag_ids))):
        for tid, comment in s.execute(select(Tag.id, Tag.comment)
                                      .where(Tag.id.in_(chunk))).all():
            if comment:
                out.setdefault(tid, set()).add("comment")
        for kind, model in (("subject", Subject), ("place", Location),
                            ("event", Occasion)):
            for (tid,) in s.execute(select(model.tag_id).where(
                    model.tag_id.in_(chunk))).all():
                out.setdefault(tid, set()).add(kind)
    return out


def missing_records(s: Session, rows: Sequence[TagSetEntry]
                    ) -> dict[int, list[str]]:
    """entry id -> which of ``comment``/``subject``/``place``/``event`` it
    claims that the LIBRARY's tag does not have.

    The implications rule, one subject along: a name the library has never
    heard of is not out of sync (nothing is claiming anything about it yet,
    and the door will apply the record the first time the tag is assigned),
    and a claim only counts while an ENABLED set is making it. What the
    library HAS wins — a tag that already carries a comment, or already is
    somebody, is not behind on anything; the set is advice, and advice does
    not overwrite an answer.
    """
    if not rows:
        return {}
    said = records_for_many(s, [r.name for r in rows])
    if not said:
        return {}
    tag_of, _ = _library_names(s, [r.name for r in rows])
    if not tag_of:
        return {}
    have = _library_records(s, list(dict.fromkeys(tag_of.values())))
    out: dict[int, list[str]] = {}
    for r in rows:
        tid = tag_of.get(r.name.lower())
        if tid is None:
            continue
        live = said.get(r.name.lower(), {})
        mine = records_of(r)
        gaps = [k for k in ("comment", *RECORD_FIELDS)
                if k in mine and k in live and k not in have.get(tid, ())]
        if gaps:
            out[r.id] = gaps
    return out


def behind_records_entry_ids(s: Session, set_id: int) -> set[int]:
    """Every entry of this set whose comment or record the library lacks —
    `behind_entry_ids` for the other kind of advice.

    The same shape and for the same reason: narrow to a proven superset in
    SQL (the entry says SOMETHING, and the library has its name), then
    refine the candidates in chunks. The library's half is a chunked index
    probe rather than a subquery, which is the whole of why that function
    is fast.
    """
    if set_id not in enabled_ids(s):
        # A DISABLED set is not advice anybody is taking, so nothing is
        # behind on it.
        return set()
    said = select(TagSetEntry.id, TagSetEntry.lname).where(
        TagSetEntry.tag_set_id == set_id,
        or_(TagSetEntry.comment != "", TagSetEntry.is_subject.is_(True),
            TagSetEntry.is_place.is_(True), TagSetEntry.is_event.is_(True)))
    by_name: dict[str, list[int]] = {}
    for eid, lname in s.execute(said).all():
        by_name.setdefault(lname, []).append(eid)
    if not by_name:
        return set()
    known: list[int] = []
    for chunk in chunked(sorted(by_name)):
        for (name,) in s.execute(select(Tag.name)
                                 .where(Tag.lname.in_(chunk))).all():
            known.extend(by_name.get(name.lower(), ()))
    out: set[int] = set()
    for i in range(0, len(known), _BEHIND_CHUNK):
        rows = list(s.execute(select(TagSetEntry).where(
            TagSetEntry.id.in_(known[i:i + _BEHIND_CHUNK]))).scalars())
        out.update(missing_records(s, rows))
    return out


def behind_entry_ids(s: Session, set_id: int) -> set[int]:
    """Every entry of this set the LIBRARY has not caught up with — the ids
    `missing_implications` would answer for, over the whole set rather than
    over a page.

    What the "Missing implied tags" filter narrows to, and the one question
    here that is genuinely about the whole set: a list of 17,000 entries with
    eleven out of step is unreadable without it.

    NARROWED FIRST, refined after — `prefilter`'s own shape. The narrowing is
    a proven SUPERSET: the entry says it entails something, the switch is on
    for it, and the library has its name. On a real set that is most of the
    pruning, since a booru dump is seventeen thousand names and a library has
    heard of a few hundred of them; what survives goes through the same walk
    a page does, in chunks, so the refinement costs the CANDIDATES.

    THE LIBRARY'S HALF IS AN INDEX PROBE, NOT A SUBQUERY. Spelled `lname IN
    (SELECT lower(name) FROM tags)` it read as 8.4 of 8.5 seconds on a set of
    17,000 against a library of 6,000 tags — SQLite has no index to match a
    column against a computed column of another table and does the obvious
    quadratic thing. Asked the other way round, in chunks of the names we
    already hold, every probe is a seek on `ix_tags_lname`.

    Cache it on the revision at the caller — paging through the filtered
    list must not recompute it per page.
    """
    ids = enabled_ids(s)
    if set_id not in ids:
        # A DISABLED set says nothing the library could be behind on: its
        # implications are not in force, so nothing is out of step.
        return set()
    sets_off, cats_off = implication_scopes_off(s, [set_id])
    if set_id in sets_off:
        return set()
    said = select(TagSetEntry.id, TagSetEntry.lname).where(
        TagSetEntry.tag_set_id == set_id,
        TagSetEntry.id.in_(select(TagSetImplication.entry_id)))
    if cats_off:
        said = said.where(or_(TagSetEntry.category_id.is_(None),
                              TagSetEntry.category_id.notin_(sorted(cats_off))))
    by_name: dict[str, list[int]] = {}
    for eid, lname in s.execute(said).all():
        by_name.setdefault(lname, []).append(eid)
    if not by_name:
        return set()
    known: list[int] = []
    for chunk in chunked(sorted(by_name)):
        for (name,) in s.execute(select(Tag.name)
                                 .where(Tag.lname.in_(chunk))).all():
            known.extend(by_name.get(name.lower(), ()))
    out: set[int] = set()
    for i in range(0, len(known), _BEHIND_CHUNK):
        rows = list(s.execute(select(TagSetEntry).where(
            TagSetEntry.id.in_(known[i:i + _BEHIND_CHUNK]))).scalars())
        gaps = missing_implications(s, rows)
        if not gaps:
            continue
        # BOTH TAGS HAVE TO BE IN THE LIBRARY (owner decision, 2026-09).
        # A gap whose implied name the library has never heard of is an
        # entry saying something about a tag nobody uses: syncing it would
        # mint that tag, which is a way to fill the catalog from a
        # 17,000-entry dump rather than a repair. The ROW still strikes such
        # a name through — the library does not entail it, and that is
        # true — but the filter is for the rows where only the LINK is
        # missing.
        seen, _ = _library_names(s, [n for names in gaps.values() for n in names])
        out.update(eid for eid, names in gaps.items()
                   if any(n.lower() in seen for n in names))
    return out


#: How many candidate entries `behind_entry_ids` refines at once — the same
#: order as a page, so the walk's frontier stays the size it was measured at.
_BEHIND_CHUNK = 500


def counts_of(s: Session) -> dict[int, tuple[int, int]]:
    """set id -> (names, categories).

    NAMES, aliases included: they are rows of the list, so the pill's
    number has to be the number of rows the list holds — which is what the
    library's own pill has always counted.
    """
    out: dict[int, tuple[int, int]] = {}
    for sid, n in s.execute(select(TagSetEntry.tag_set_id, func.count())
                            .group_by(TagSetEntry.tag_set_id)).all():
        out[sid] = (int(n), 0)
    for sid, n in s.execute(select(TagSetCategory.tag_set_id, func.count())
                            .group_by(TagSetCategory.tag_set_id)).all():
        e, _ = out.get(sid, (0, 0))
        out[sid] = (e, int(n))
    return out


def is_library(s: Session, set_id: int) -> bool:
    """Is this the library's own set? Asked by every count below, because the
    library's names are `tags` rows and an imported set's are
    `tag_set_entries` — one question, answered once, rather than two code
    paths through the Tags tab."""
    lib = library_set(s)
    return lib is not None and lib.id == int(set_id)


def record_counts(s: Session, set_id: int) -> dict[str, int]:
    """How many of the set's names are a subject, a place, an event —
    what the sidebar's three rows show, and whether they are drawn at all.

    ONE PASS of conditional sums, the shape every count here takes. For the
    LIBRARY the records are real rows (`Subject`, `Location`, `Occasion`
    hanging off a tag) rather than an entry's claim, so the pass is over
    those instead; the number means the same thing either way.
    """
    if is_library(s, set_id):
        from ..db import Location, Occasion, Subject
        out: dict[str, int] = {}
        for kind, model in (("subject", Subject), ("place", Location),
                            ("event", Occasion)):
            out[kind] = int(s.execute(
                select(func.count()).select_from(model)
                .where(model.tag_id.isnot(None))).scalar() or 0)
        return out
    row = s.execute(select(*(
        func.sum(case((getattr(TagSetEntry, f"is_{k}").is_(True), 1), else_=0))
        for k in RECORD_FIELDS)).where(
            TagSetEntry.tag_set_id == set_id)).one()
    return {k: int(v or 0) for k, v in zip(RECORD_FIELDS, row)}


def category_entry_counts(s: Session, set_id: int) -> dict[Optional[int], int]:
    """category id -> DIRECT names filed in it; `None` is the uncategorized
    count.

    The library files `tags` (`Tag.category_id`); an imported set files its
    own entries. Same shape, same rollup (`category_subtree_counts`), so the
    tree draws one way for both.
    """
    if is_library(s, set_id):
        from ..db import Tag
        return {cid: int(n) for cid, n in s.execute(
            select(Tag.category_id, func.count())
            .group_by(Tag.category_id)).all()}
    return {cid: int(n) for cid, n in s.execute(
        select(TagSetEntry.category_id, func.count())
        .where(TagSetEntry.tag_set_id == set_id)
        .group_by(TagSetEntry.category_id)).all()}


def namespaces_of(s: Session, set_id: int) -> list[tuple[str, int]]:
    """The set's NAMESPACES and how many of its names carry each — the
    sidebar's derived half, for a set rather than for the library.

    Same rule as the library's (`routers/tags.tag_namespaces`) and the same
    rule the inline parent rows follow: two or more names must share the
    prefix, since a heading over one thing says nothing. The library reads
    `tags`, a set reads its own rows — ALIASES INCLUDED, since they are
    rows of the list now and the library has always counted its own.
    """
    from .. import tagname

    counts: dict[str, int] = {}
    for (name,) in s.execute(
        select(TagSetEntry.name)
        .where(TagSetEntry.tag_set_id == set_id,
               TagSetEntry.name.like("%:%"))
    ).all():
        ns = tagname.namespace(name)
        if ns:
            counts[ns] = counts.get(ns, 0) + 1
    return [(ns, n) for ns, n in sorted(counts.items(), key=lambda kv: kv[0].lower())
            if n >= 2]


def category_subtree_ids(s: Session, set_id: int, cat_id: int) -> list[int]:
    """The category and everything under it — what "in this category" means
    to the Sets tab, where a category IMPLICITLY holds its sub-categories'
    entries (the tree's counts and the list agree on it)."""
    kids: dict[Optional[int], list[int]] = {}
    for c in categories_of(s, set_id):
        kids.setdefault(c.parent_id, []).append(c.id)
    out: list[int] = []
    stack, seen = [cat_id], set()
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
        stack.extend(kids.get(x, []))
    return out


def category_subtree_counts(s: Session, set_id: int) -> dict[Optional[int], int]:
    """category id -> entries in it AND under it; `None` stays the
    uncategorized count. The direct counts rolled up the tree once."""
    direct = category_entry_counts(s, set_id)
    parent = {c.id: c.parent_id for c in categories_of(s, set_id)}
    out: dict[Optional[int], int] = dict(direct)
    for cid, n in direct.items():
        if cid is None:
            continue
        up, seen = parent.get(cid), {cid}
        while up is not None and up not in seen:
            out[up] = out.get(up, 0) + n
            seen.add(up)
            up = parent.get(up)
    return out


def hidden_category_ids(s: Session, set_ids: Sequence[int]) -> set[int]:
    """Every category the autocomplete must not offer, across `set_ids`: the
    ones marked hidden AND everything under them.

    One statement over the few hundred category rows the enabled sets have,
    closed in Python — the closure is a tree walk SQLite would need a
    recursive CTE for, and this answer is cached on the library's revision
    beside `enabled_ids` (`routers/tags`), so it is computed once per edit
    rather than once per keystroke.

    HIDING IS ABOUT WHAT IS OFFERED. It leaves the entries where they are:
    the Sets tab still lists and edits them, an EXPORT still carries them,
    and a name the LIBRARY has is answered by the library's own row, which no
    set has ever had a say in.
    """
    if not set_ids:
        return set()
    rows = s.execute(
        select(TagSetCategory.id, TagSetCategory.parent_id, TagSetCategory.hidden)
        .where(TagSetCategory.tag_set_id.in_(list(set_ids)))).all()
    kids: dict[Optional[int], list[int]] = {}
    for cid, parent, _hidden in rows:
        kids.setdefault(parent, []).append(cid)
    out: set[int] = set()
    stack = [cid for cid, _p, hidden in rows if hidden]
    while stack:
        cid = stack.pop()
        if cid in out:
            continue
        out.add(cid)
        stack.extend(kids.get(cid, ()))
    return out


def _scopes_off(s: Session, set_ids: Sequence[int], cat_col: Any,
                set_col: Any) -> tuple[set[int], set[int]]:
    """(sets that answer NO outright, categories that answer NO) for one of
    the two three-state switches.

    The walk is: a category's own answer, else its parent's, else its
    parent's parent's… else the SET's flag. Resolved in Python over the few
    hundred rows the enabled sets have, in two statements — the same shape
    and the same reason as `hidden_category_ids`, and cached on the
    library's revision beside it.

    A set that is off outright is returned as a set id rather than as every
    one of its categories, because its UNCATEGORIZED entries are off too and
    they have no category to name.
    """
    if not set_ids:
        return set(), set()
    ids = list(set_ids)
    roots = {sid: bool(on) for sid, on in s.execute(
        select(TagSet.id, set_col).where(TagSet.id.in_(ids))).all()}
    sets_off = {sid for sid, on in roots.items() if not on}
    rows = s.execute(
        select(TagSetCategory.id, TagSetCategory.parent_id,
               TagSetCategory.tag_set_id, cat_col)
        .where(TagSetCategory.tag_set_id.in_(ids))).all()
    own = {cid: (parent, sid, val) for cid, parent, sid, val in rows}
    answer: dict[int, bool] = {}

    def resolve(cid: int, depth: int = 0) -> bool:
        if cid in answer:
            return answer[cid]
        parent, sid, val = own[cid]
        if val is not None:
            out = bool(val)
        elif parent is None or parent not in own or depth > 32:
            out = roots.get(sid, True)
        else:
            out = resolve(parent, depth + 1)
        answer[cid] = out
        return out

    cats_off = {cid for cid in own if not resolve(cid)}
    return sets_off, cats_off


def scope_clauses(sets_off: set[int], cats_off: set[int], entry: Any) -> list[Any]:
    """The WHERE clauses that keep a query to the scopes still answering.

    Takes what `alias_scopes_off` / `implication_scopes_off` returned and an
    entry table (or alias thereof) to read the set and category from. Empty
    when nothing is off, so the usual query is the query it always was.
    """
    out: list[Any] = []
    if sets_off:
        out.append(entry.tag_set_id.notin_(list(sets_off)))
    if cats_off:
        # A NULL category never matches a NOT IN — an uncategorized entry is
        # governed by its SET's flag alone, which the clause above covers.
        out.append(or_(entry.category_id.is_(None),
                       entry.category_id.notin_(list(cats_off))))
    return out


def _held_scopes_off(s: Session, which: str, set_ids: Sequence[int],
                     cat_col: Any, set_col: Any) -> tuple[set[int], set[int]]:
    """`_scopes_off`, held on the library's revision — which is what its
    docstring has always said it was.

    It reads every category of the sets named to answer a yes/no about a
    branch, and the readers ask per page: `implied_names_for_many` asks it
    for every detail band the Tags tab fetches, which on a 4,356-category
    set is 5 ms a scroll step for an answer no scroll can change. The memo
    is the DATABASE's (`session.info["mc_db"]`, the way `ops/search` reaches
    it for a ranking's fit), so nothing below the server has to be handed a
    library to get at it.
    """
    key = (f"scopes-off:{which}", tuple(sorted(set_ids)))
    db = (s.info or {}).get("mc_db")
    if db is None:
        return _scopes_off(s, set_ids, cat_col, set_col)
    return db.cached(s, key, lambda: _scopes_off(s, set_ids, cat_col, set_col))


def alias_scopes_off(s: Session, set_ids: Sequence[int]
                     ) -> tuple[set[int], set[int]]:
    """Where an alias spelling is NOT offered and does NOT redirect."""
    return _held_scopes_off(s, "alias", set_ids,
                            TagSetCategory.aliases, TagSet.aliases_enabled)


def implication_scopes_off(s: Session, set_ids: Sequence[int]
                           ) -> tuple[set[int], set[int]]:
    """Where an entry's `implies` mints NOTHING when its name is assigned."""
    return _held_scopes_off(s, "implies", set_ids,
                            TagSetCategory.implications,
                            TagSet.implications_enabled)


def categories_of(s: Session, set_id: int) -> list[TagSetCategory]:
    return list(s.execute(
        select(TagSetCategory).where(TagSetCategory.tag_set_id == set_id)
        .order_by(TagSetCategory.position, TagSetCategory.id)).scalars())


def category_trails(s: Session, set_id: int) -> dict[int, list[str]]:
    """category id -> the names down to it, outermost first.

    A LIST, never a joined string: a category name may hold a `/` (owner
    decision, 2026-09), so there is no separator left to join on that some
    name cannot also contain. Everything that used to read a path — the
    wire, the file, the sort, the event summaries — takes the trail and
    joins it, or does not join it at all.
    """
    cats = {c.id: c for c in categories_of(s, set_id)}
    trails: dict[int, list[str]] = {}

    def trail_of(cid: int, depth: int = 0) -> list[str]:
        if cid in trails:
            return trails[cid]
        c = cats[cid]
        if c.parent_id is None or c.parent_id not in cats or depth > 32:
            t = [c.name]
        else:
            t = [*trail_of(c.parent_id, depth + 1), c.name]
        trails[cid] = t
        return t

    for cid in cats:
        trail_of(cid)
    return trails


ENTRY_SORTS = ("position", "name", "count", "category")


def _entries_stmt(s: Session, set_id: int, *, q: str = "",
                  category_id: Optional[int] = None,
                  category_ids: Sequence[int] = (),
                  uncategorized: bool = False,
                  subtree: bool = False,
                  has_aliases: bool = False, has_implies: bool = False,
                  described: Optional[bool] = None,
                  records: Sequence[str] = (),
                  count_min: Optional[int] = None,
                  count_max: Optional[int] = None,
                  namespace: Sequence[str] = (),
                  behind: Optional[set[int]] = None):
    """WHICH entries a page holds — every narrowing, no order and no window.

    Shared by `entries_page` and `entry_index`, so "what is on this page" and
    "where in it is this tag" are one question asked twice.

    ``behind`` is the one narrowing whose answer is not in this table: which
    entries the LIBRARY has not caught up with (`behind_entry_ids`). It
    arrives as the id set so the caller can cache it on the revision — the
    filtered list is paged, and asking it per page would recompute it per
    page.
    """
    # AN ALIAS IS A ROW OF THE LIST, exactly as it is in the library's own
    # (owner 2026-09, reversing "each entry with its other spellings drawn
    # on its row"): it is a name of the tag set, it has a checkbox and a
    # selection of its own, and it is narrowed, searched and sorted like any
    # other. Two tag sets drawing the same fact two ways is the drift
    # one list exists to end.
    stmt = select(TagSetEntry).where(TagSetEntry.tag_set_id == set_id)
    # A RANGE ON THE COUNT COLUMN, the Items list's control over the column
    # it is about. Either end optional — an absent bound is no bound, which
    # is what makes "at least 1000" and "at most 50" the same control with
    # one end filled in. An entry with NO count is out of any bounded range:
    # "how popular is this" has no answer there, and a set that carries no
    # counts simply never shows the control.
    if count_min is not None:
        stmt = stmt.where(TagSetEntry.count.is_not(None),
                          TagSetEntry.count >= count_min)
    if count_max is not None:
        stmt = stmt.where(TagSetEntry.count.is_not(None),
                          TagSetEntry.count <= count_max)
    if q:
        stmt = stmt.where(func.instr(TagSetEntry.lname, q.lower()) > 0)
    if behind is not None:
        # An EMPTY set is "nothing is behind", not "no narrowing" — the
        # filter must be able to answer with an empty list.
        #
        # NOT chunked, unlike every other Python id list here: this is one
        # WHERE inside a paged query and there is nowhere to split it. The
        # bound is the SET's own size — seventeen thousand for the booru
        # template, which SQLite takes in one statement (its variable limit
        # is 250,000) well under a tenth of a second.
        stmt = stmt.where(TagSetEntry.id.in_(sorted(behind)) if behind
                          else literal(False))
    # WHAT THE SIDEBAR PICKED, AND IT IS ONE UNION (owner 2026-09). A
    # NAMESPACE READS AS A CATEGORY HOLDING THE NAMES MADE WITH IT: it is
    # picked in the same list, by the same gesture, and picking one beside a
    # real category lists the entries in EITHER — the two used to intersect,
    # which meant a plain click in the lower block silently narrowed what the
    # upper block was showing to nothing at all more often than not.
    #
    # `subtree`: a category's own entries AND its sub-categories' — the Sets
    # tab's reading; the browse tree keeps the direct ones, since its
    # sub-category rows lead to the rest. Several categories are deduped —
    # picking a category and one inside it lists each entry once.
    wanted = list(category_ids) if category_ids else (
        [] if category_id is None else [category_id])
    scope = []
    if wanted:
        ids: list[int] = []
        for cid in wanted:
            for x in (category_subtree_ids(s, set_id, cid) if subtree else [cid]):
                if x not in ids:
                    ids.append(x)
        scope.append(TagSetEntry.category_id.in_(ids))
    if uncategorized:
        scope.append(TagSetEntry.category_id.is_(None))
    # THE DERIVED HALF: the text before the first colon. No column to match,
    # so it is a prefix on `lname` — which `ix_tag_set_entries_lname` serves,
    # the same index the name probes use. Written with or without the colon,
    # since a person types one and the setting stores neither.
    for raw in namespace:
        ns = raw.strip().lower().rstrip(":")
        if ns:
            scope.append(TagSetEntry.lname.like(f"{ns}:%"))
    if scope:
        stmt = stmt.where(or_(*scope))
    # EXISTS per row rather than a join: a join would multiply the row by its
    # aliases and need a DISTINCT, and the count is taken over this same
    # statement.
    if has_aliases:
        stmt = stmt.where(select(literal(1)).where(
            Alias.alias_of_id == TagSetEntry.id).exists())
    if has_implies:
        stmt = stmt.where(select(literal(1)).where(
            TagSetImplication.entry_id == TagSetEntry.id).exists())
    # THREE-STATE, unlike the two above: "what have I not written up yet" is
    # as much a question as "what have I", so the filter answers both ways
    # and None is no filter at all.
    if described is not None:
        stmt = stmt.where(TagSetEntry.description != ""
                          if described else TagSetEntry.description == "")
    # WHICH KINDS OF THING, and several at once is the UNION: "subjects and
    # places" is one list of the entries that are either, not the empty list
    # of entries that are both. (An entry CAN be both, and is listed once.)
    kinds = [k for k in dict.fromkeys(records) if k in RECORD_FIELDS]
    if kinds:
        stmt = stmt.where(or_(*(getattr(TagSetEntry, f"is_{k}").is_(True)
                                for k in kinds)))
    return stmt


def _entry_order(s: Session, set_id: int, sort: str, desc: bool,
                 q: str = "") -> list[Any]:
    """The ORDER BY a page is read in. `sort` is the file's own order
    (`position`), the name, the count or the category — a count nobody gave
    and an entry in no category sort LAST either way, so the figures stay
    together at the top of a descending list and at the bottom of an
    ascending one; the NAME, ascending, breaks every tie whatever the
    direction, so two equal counts read alphabetically under a descending
    sort too. The category order is the tree's own (its trails, name by name,
    as the list shows them), which is a CASE over the set's few category ids
    rather than a join — the trails are nested, and a recursive CTE for a
    column of a few dozen values is the wrong size of tool.

    Ahead of all of it, where the list is being SEARCHED: the entry whose
    name IS what was typed. `1girl` in the booru set matches nine other
    entries that contain it, and the one asked for by its whole name sat
    among them in file order. `q` is the same string `_entries_stmt`
    narrowed by, so the two cannot disagree about what an exact match is.
    """
    lead: list[Any] = []
    if q.strip():
        lead = [TagSetEntry.lname != q.strip().lower()]
    of = TagSetEntry.alias_of_id

    def own_or_target(col: str):
        """The row's own value of ``col``, or — for an ALIAS ROW — the value
        on the name it spells.

        A spelling carries no count and no place in the file's order of its
        own, so under either it goes directly beneath the name it spells:
        the library list's alias slotting, done here because this list is
        server-paged and a client cannot slot across a page it has not got.
        A correlated read of one column, on the primary key.
        """
        tgt = aliased(TagSetEntry, name=f"alias_{col}")
        return case((of.is_(None), getattr(TagSetEntry, col)),
                    else_=select(getattr(tgt, col))
                    .where(tgt.id == of).scalar_subquery())

    #: The spelling's entry FIRST, then its spellings, wherever they share a
    #: key — and the row's own name breaking every remaining tie.
    slot = [own_or_target("lname"), of.is_not(None), TagSetEntry.lname]
    if sort == "name":
        # ALPHABETICAL IS ALPHABETICAL: a spelling stands where its own name
        # puts it, as it does in the library's list.
        return lead + [TagSetEntry.lname.desc() if desc else TagSetEntry.lname]
    if sort == "count":
        num = own_or_target("count")
        return lead + [num.is_(None), num.desc() if desc else num, *slot]
    if sort == "category":
        trails = category_trails(s, set_id)
        # By the TRAIL, name by name — an outer category orders before every
        # one under it, and two siblings order by their own names. Ranking
        # a joined string put `a/b` between `a` and `a-c` wherever a name
        # held the separator.
        ranked = sorted(trails, key=lambda cid: [n.lower() for n in trails[cid]])
        rank = case({cid: i for i, cid in enumerate(ranked)},
                    value=TagSetEntry.category_id, else_=len(ranked)) if ranked \
            else literal(0)
        return lead + [TagSetEntry.category_id.is_(None),
                       rank.desc() if desc else rank, *slot]
    pos = own_or_target("position")
    return lead + [pos.desc() if desc else pos, *slot]


def entries_page(s: Session, set_id: int, *,
                 sort: str = "position", desc: bool = False,
                 limit: int = 200, offset: int = 0, **narrow: Any
                 ) -> tuple[list[TagSetEntry], int]:
    """One page of a set's entries, and how many the narrowing holds.

    ``narrow`` is `_entries_stmt`'s: ``q``, ``category_ids`` (SEVERAL at
    once — what the Sets tab asks for when several rows of its tree are
    picked — each expanded through its own subtree where ``subtree`` says
    so), the one-category ``category_id``, ``uncategorized``, the
    ``has_aliases`` / ``has_implies`` pair, and ``described`` (three-state:
    with a description, without one, or either).
    """
    if sort not in ENTRY_SORTS:
        raise Invalid("sort must be position, name, count or category",
                      code="tag_set_bad_sort")
    stmt = _entries_stmt(s, set_id, **narrow)
    total = s.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    order = _entry_order(s, set_id, sort, desc, narrow.get("q", ""))
    rows = list(s.execute(stmt.order_by(*order).limit(limit).offset(offset)).scalars())
    return rows, int(total)


def entry_ids(s: Session, set_id: int, *, sort: str = "position",
              desc: bool = False, limit: int = 50_000,
              **narrow: Any) -> list[int]:
    """Every entry id the narrowing holds, in the order a page reads.

    What SELECT ALL is: the header's checkbox means every row in the list,
    not every row that happens to be loaded — the list is server-paged and
    windowed, so on a set of seventeen thousand it was picking the two
    hundred in hand. Shift-ranges reach across the unloaded middle for the
    same reason.

    Ids only, and one statement: the page's own narrowing and order with a
    single column selected, which for a booru-sized set is about a hundred
    kilobytes and is asked for once per narrowing, beside the page itself.
    """
    if sort not in ENTRY_SORTS:
        raise Invalid("sort must be position, name, count or category",
                      code="tag_set_bad_sort")
    stmt = _entries_stmt(s, set_id, **narrow).with_only_columns(TagSetEntry.id)
    order = _entry_order(s, set_id, sort, desc, narrow.get("q", ""))
    return [int(i) for (i,) in
            s.execute(stmt.order_by(*order).limit(limit)).all()]


def entry_index(s: Session, set_id: int, name: str, *,
                sort: str = "position", desc: bool = False, **narrow: Any
                ) -> Optional[tuple[int, int, Optional[int]]]:
    """(row index, entry id, category id) for ``name`` under the SAME
    narrowing and sort a page is read with, or None when the list does not
    hold it. The CATEGORY rides along because the caller's first question is
    which category to open, asked of the whole set, before it can ask where
    in the narrowed list the row then sits.

    What "jump to this tag" needs, and the only thing that can supply it: the
    list is server-paged and windowed, so the client scrolls by INDEX
    (`useWindowedList.scrollToIndex`) and has no way to work one out. A
    window function over the page's own statement — one scan of the narrowed
    set per click, rather than a second idea of what the order is.
    """
    if sort not in ENTRY_SORTS:
        raise Invalid("sort must be position, name, count or category",
                      code="tag_set_bad_sort")
    lname = (name or "").strip().lower()
    if not lname:
        return None
    numbered = _entries_stmt(s, set_id, **narrow).with_only_columns(
        TagSetEntry.id, TagSetEntry.lname, TagSetEntry.category_id,
        (func.row_number().over(order_by=_entry_order(
            s, set_id, sort, desc, narrow.get("q", "")))
         - 1).label("idx")).subquery()
    row = s.execute(select(numbered.c.idx, numbered.c.id, numbered.c.category_id)
                    .where(numbered.c.lname == lname)).first()
    return (int(row[0]), int(row[1]),
            None if row[2] is None else int(row[2])) if row else None


def alias_target_name(s: Session, row: TagSetEntry) -> Optional[str]:
    """The name an alias row SPELLS, or None for an ordinary entry."""
    if row.alias_of_id is None:
        return None
    return s.execute(select(TagSetEntry.name)
                     .where(TagSetEntry.id == row.alias_of_id)).scalar()


def alias_targets(s: Session, rows: Sequence[TagSetEntry]) -> dict[int, str]:
    """row id -> the name it spells, for the alias rows among ``rows``.

    One statement for a page, the way every other per-row fact here is
    read: the list draws `→ target` on an alias row, and asking per row
    would be a query per alias on a page of two hundred.
    """
    ids = [int(r.alias_of_id) for r in rows if r.alias_of_id is not None]
    if not ids:
        return {}
    names: dict[int, str] = {}
    for chunk in chunked(list(dict.fromkeys(ids))):
        for tid, name in s.execute(select(TagSetEntry.id, TagSetEntry.name)
                                   .where(TagSetEntry.id.in_(chunk))).all():
            names[int(tid)] = name
    return {r.id: names[int(r.alias_of_id)] for r in rows
            if r.alias_of_id is not None and int(r.alias_of_id) in names}


def aliases_of(s: Session, entry_ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for chunk in chunked(entry_ids):
        for eid, name in s.execute(
                select(Alias.alias_of_id, Alias.name)
                .where(Alias.alias_of_id.in_(chunk))
                .order_by(Alias.id)).all():
            out.setdefault(eid, []).append(name)
    return out


def implications_of_set(s: Session, set_id: int) -> dict[int, list[str]]:
    """`implications_of` for a WHOLE tag set, asked of the set rather than
    of a list of its entries.

    The same answer, and the same shape — but the caller that wants every
    entry's is the tags index, whose id list is the whole set: a hundred and
    thirty thousand bound parameters in fourteen chunked `IN`s, 209 ms, for
    a question the entry's own `tag_set_id` already asks. Its caller holds
    it on the library revision, so a search pays for it once rather than
    once per keystroke.
    """
    out: dict[int, list[str]] = {}
    for eid, name in s.execute(
            select(TagSetImplication.entry_id, TagSetImplication.implies_name)
            .join(TagSetEntry, TagSetEntry.id == TagSetImplication.entry_id)
            .where(TagSetEntry.tag_set_id == set_id)
            .order_by(TagSetImplication.id)).all():
        out.setdefault(eid, []).append(name)
    return out


def implications_of(s: Session, entry_ids: list[int]) -> dict[int, list[str]]:
    """entry id -> the NAMES it says are entailed, in the order they were
    written. Names, never ids: a set is keyed by name throughout, and the
    tags it names need not exist in the library at all."""
    out: dict[int, list[str]] = {}
    for chunk in chunked(entry_ids):
        for eid, name in s.execute(
                select(TagSetImplication.entry_id, TagSetImplication.implies_name)
                .where(TagSetImplication.entry_id.in_(chunk))
                .order_by(TagSetImplication.id)).all():
            out.setdefault(eid, []).append(name)
    return out


# ---- the templates, and the one system write at open ------------------------

@dataclass(frozen=True)
class TemplateInfo:
    """What a template says ABOUT ITSELF — and not one of its entries.

    Everything the list of templates shows, plus the two figures that say
    how big each one is. It exists because a template's SIZE must not be a
    cost the app pays for merely listing it: the list is fetched whenever
    the Sets shelf mounts and again after every tag-set write, and holding
    the parsed entries of every shipped file for the life of the process
    is proportional to the largest set anybody ever ships. The Characters
    template made that visible — 380,000 entries was 3.8 s and ~900 MB
    resident against 0.09 s and 132 MB for the four sets before it — and
    the fix is to keep the ANSWER rather than the document.
    """
    key: str
    name: str
    description: str
    entries: int
    categories: int


@lru_cache(maxsize=16)
def _template_info(path: str, mtime_ns: int) -> TemplateInfo:
    """One file's own facts, read once per file version.

    The document is parsed and THROWN AWAY; what is cached is the handful
    of numbers. `categories` is the count `category_order` gives — the
    tree the entries imply — since a shipped template writes no
    `categories` block at all and the length of that list is zero for
    every one of them.
    """
    doc = fmt.load_path(Path(path))
    return TemplateInfo(key=doc.key, name=doc.name, description=doc.description,
                        entries=len(doc.entries),
                        categories=len(fmt.category_order(doc.categories,
                                                          doc.entries)))


def templates() -> list[TemplateInfo]:
    """The shipped templates, by name — their facts, never their entries."""
    infos = [_template_info(str(p), p.stat().st_mtime_ns)
             for p in sorted(TEMPLATE_DIR.glob("*.json"))]
    return sorted(infos, key=lambda d: d.name.lower())


def template(key: str) -> fmt.TagSetDoc:
    """The whole document of ONE template, parsed fresh.

    Deliberately not cached: the only caller is `create_from_template`,
    which happens once in the life of a set, and the entries it wants are
    exactly what nothing should be holding afterwards.
    """
    for p in sorted(TEMPLATE_DIR.glob("*.json")):
        if _template_info(str(p), p.stat().st_mtime_ns).key == key:
            return fmt.load_path(p)
    raise NotFound("no such template: {key}", {"key": key}, code="tag_set_template")


def create_from_template(ctx: Ctx, template_key: str, *, name: str = ""
                         ) -> tuple[TagSet, dict]:
    """A NEW set holding a template's categories and entries — an import of
    the shipped file, so it logs and reverts exactly as an import does, and
    a second one from the same template takes a fresh key like a second
    import of one file."""
    doc = template(template_key)
    obj = fmt.dump(doc)
    if name.strip():
        obj["name"] = name.strip()
    # The template's key travels EXPLICITLY: a format-2 file carries none
    # (it names one installation, not the tag set), and the key is what
    # says WHICH tag set this is — a second Booru set is `booru-2`,
    # whatever the person called it.
    return import_document(ctx, obj, mode="create", key=doc.key)


def unlock_builtin_sets(s: Session) -> int:
    """The shipped set used to be INSTALLED in every library as a locked
    row (`builtin=1`). It is a template now, and the copy a library already
    holds becomes an ordinary set of its own — same rows, same switch, now
    editable and deletable. A system write at open, idempotent."""
    rows = s.execute(select(TagSet).where(TagSet.builtin.is_(True))).scalars().all()
    for r in rows:
        r.builtin = False
    if rows:
        s.flush()
    return len(rows)


def _next_position(s: Session) -> int:
    mx = s.execute(select(func.max(TagSet.position))).scalar()
    return int(mx or 0) + 1


def _clear_rows(s: Session, set_id: int) -> None:
    eids = select(TagSetEntry.id).where(TagSetEntry.tag_set_id == set_id)
    s.execute(delete(TagSetImplication).where(TagSetImplication.entry_id.in_(eids)))
    # An entry's meta tags go with it by CASCADE; the set's own meta-tag
    # ROWS are `tags` rows of this set and have to be said.
    # The aliases are rows of the set too, so one delete takes both.
    s.execute(delete(TagSetEntry).where(TagSetEntry.tag_set_id == set_id))
    s.execute(delete(MetaTag).where(MetaTag.tag_set_id == set_id))
    s.execute(delete(TagSetCategory).where(TagSetCategory.tag_set_id == set_id))
    s.flush()


def _apply_category_settings(row: TagSetCategory, c: fmt.CategoryDoc) -> None:
    row.icon = c.icon or ""
    row.hidden = bool(c.hidden)
    row.aliases = c.aliases
    row.implications = c.implications


def _write_categories(s: Session, ts: TagSet, doc: fmt.TagSetDoc,
                      trails: dict[tuple[str, ...], int],
                      made: list[int]) -> None:
    """Every category the document implies, made in `fmt.category_order`'s
    order — the ONE definition of what the tree is, walked here rather than
    reimplemented.

    Settings and an explicit `position` land only on a category this call
    CREATED. On a merge the rows already here keep their own icon, their own
    hidden and their own place: a file merged in adds what the set lacks,
    and quietly restyling or reordering somebody's tree is not that.
    """
    says = {tuple(c.path): c for c in doc.categories}
    fresh: dict[tuple[str, ...], int] = {}
    last: dict[Optional[int], int] = {}
    for trail in fmt.category_order(doc.categories, doc.entries):
        before = len(made)
        cid = _ensure_trail(s, ts, trail, trails, made, last)
        if cid is None or cid not in made[before:]:
            continue
        fresh[tuple(trail)] = cid
        c = says.get(tuple(trail))
        # ONLY WHERE THE FILE HAS SOMETHING TO APPLY. The identity map holds
        # objects WEAKLY and `_ensure_trail` keeps no reference to the row it
        # made, so this `get` is a full SELECT per category — and the usual
        # file, every shipped template included, writes no `categories` block
        # at all, so there is nothing to put on the row it fetched.
        if c is not None:
            row = s.get(TagSetCategory, cid)
            if row is not None:
                _apply_category_settings(row, c)
    # POSITIONS LAST, over the creation order that has just been assigned:
    # a file only carries them for a parent whose children were reordered by
    # hand, and then for every one of them.
    for c in doc.categories:
        cid = fresh.get(tuple(c.path))
        if c.position is not None and cid is not None:
            row = s.get(TagSetCategory, cid)
            if row is not None:
                row.position = int(c.position)
    s.flush()


def _write_meta_tags(s: Session, ts: TagSet, doc: fmt.TagSetDoc) -> None:
    """The file's own META TAG rows — the labels it has a comment or a
    description for. Before the entries, so those words land on the row
    rather than on a bare name the entries would have minted behind it.

    What the set already says about a label WINS, the rule everywhere an
    import meets an answer that is already there.
    """
    if not doc.meta_tags:
        return
    have = {r.lower() for r in s.execute(
        select(MetaTag.lname).where(MetaTag.tag_set_id == ts.id)).scalars()}
    fresh = [m for m in doc.meta_tags if m.name.lower() not in have]
    if not fresh:
        return
    mx = s.execute(select(func.max(MetaTag.position))
                   .where(MetaTag.tag_set_id == ts.id)).scalar() or 0
    s.execute(MetaTag.__table__.insert(), [
        {"tag_set_id": ts.id, "kind": "meta", "name": m.name,
         "comment": m.comment, "description": m.description,
         "position": mx + i + 1}
        for i, m in enumerate(fresh)])
    s.flush()


def _depth_first(cats: Sequence[TagSetCategory]) -> list[TagSetCategory]:
    """The rows parents-first, each parent's children in their own order.

    What `category_order` replays: written in this order, a full category
    list reproduces every sibling order exactly, which the rows' global
    `(position, id)` order does not (a child may sort before its parent).
    """
    kids: dict[Optional[int], list[TagSetCategory]] = {}
    for c in cats:
        kids.setdefault(c.parent_id, []).append(c)
    have = {c.id for c in cats}
    out: list[TagSetCategory] = []

    def walk(parent: Optional[int]) -> None:
        for c in kids.get(parent, ()):
            out.append(c)
            walk(c.id)

    walk(None)
    # A row whose parent is missing (a SET NULL that lost its target) roots
    # itself in `category_trails` too; keep it rather than dropping it.
    walk_roots = [c for c in cats if c.parent_id is not None and c.parent_id not in have]
    for c in walk_roots:
        if c not in out:
            out.append(c)
            walk(c.id)
    return out


def _sibling_order(order: Sequence[Sequence[str]]) -> dict[tuple[str, ...], list[str]]:
    """trail of the parent -> its children's names, in order. What has to
    survive a round trip: a category's PARENT and its place among its
    siblings. The rows' global order is not that and never was."""
    out: dict[tuple[str, ...], list[str]] = {}
    for trail in order:
        out.setdefault(tuple(trail[:-1]), []).append(trail[-1])
    return out


def _category_docs(s: Session, ts: TagSet,
                   entries: list[fmt.EntryDoc]) -> list[fmt.CategoryDoc]:
    """The `categories` rows an export has to write — usually none.

    A row is written for a category that says something beyond existing (an
    icon, hidden, an alias or implication answer of its own) or that no entry
    names, which would otherwise not come back at all. Then the ORDER is
    checked, per PARENT: where reading the file would not lay a parent's
    children out as they stand, every one of that parent's children is
    written with its `position`. Per parent rather than per set, so hiding
    one branch of a 387-category template still writes one row.
    """
    cats = _depth_first(categories_of(s, ts.id))
    trails = category_trails(s, ts.id)

    def trail_of(c: TagSetCategory) -> tuple[str, ...]:
        return tuple(trails.get(c.id, [c.name]))

    def doc_of(c: TagSetCategory) -> fmt.CategoryDoc:
        return fmt.CategoryDoc(path=list(trail_of(c)),
                               icon=c.icon or "", hidden=bool(c.hidden),
                               aliases=c.aliases, implications=c.implications)

    def says_something(c: TagSetCategory) -> bool:
        return bool(c.icon) or bool(c.hidden) \
            or c.aliases is not None or c.implications is not None

    implied = {tuple(t) for t in fmt.category_order([], entries)}
    rows = [doc_of(c) for c in cats
            if says_something(c) or trail_of(c) not in implied]
    want = _sibling_order([list(trail_of(c)) for c in cats])
    have = _sibling_order(fmt.category_order(rows, entries))
    off = {parent for parent, kids in want.items() if have.get(parent) != kids}
    if off:
        by_path = {tuple(r.path): r for r in rows}
        for c in cats:
            trail = trail_of(c)
            parent = trail[:-1]
            if parent not in off:
                continue
            row = by_path.get(trail)
            if row is None:
                row = doc_of(c)
                rows.append(row)
                by_path[trail] = row
            row.position = want[parent].index(trail[-1])
    return rows


def _record_columns(e: fmt.EntryDoc) -> dict:
    """One document entry's records as the row's own columns — a Core insert
    of tens of thousands of rows cannot go through the ORM."""
    out: dict[str, Any] = {}
    for kind in RECORD_FIELDS:
        rec = getattr(e, kind)
        out[f"is_{kind}"] = rec is not None
        for f in RECORD_FIELDS[kind]:
            default = (None if (f in _RECORD_DATES or f in _RECORD_COORDS)
                       else "")
            out[f"{kind}_{f}"] = (getattr(rec, f, None) if rec is not None
                                  else default)
            if out[f"{kind}_{f}"] is None and default == "":
                out[f"{kind}_{f}"] = ""
    return out


def _doc_records(row: TagSetEntry) -> dict:
    """The row's records as the document's own dataclasses."""
    out: dict[str, Any] = {}
    for kind, cls in (("subject", fmt.SubjectDoc), ("place", fmt.PlaceDoc),
                      ("event", fmt.EventDoc)):
        rec = record_of(row, kind)
        out[kind] = None if rec is None else cls(**rec)
    return out


def _write_doc(s: Session, ts: TagSet, doc: fmt.TagSetDoc) -> None:
    """Every row of a document into an EMPTY set — the installers' and the
    duplicate's path. Core inserts: a booru dump is tens of thousands."""
    trails: dict[tuple[str, ...], int] = {}
    _write_categories(s, ts, doc, trails, [])
    if not doc.entries:
        return
    # A CORE INSERT SETS THE DISCRIMINATOR ITSELF: `kind` is what the three
    # mapped classes are keyed on, and nothing below the ORM fills it in.
    s.execute(TagSetEntry.__table__.insert(), [
        {"tag_set_id": ts.id, "kind": "set",
         "category_id": trails.get(tuple(e.category)) if e.category else None,
         "name": e.name, "description": e.description,
         "count": e.count, "position": i, "comment": e.comment,
         **_record_columns(e)}
        for i, e in enumerate(doc.entries)])
    s.flush()
    ids = dict(s.execute(select(TagSetEntry.lname, TagSetEntry.id)
                         .where(TagSetEntry.tag_set_id == ts.id,
                                NOT_ALIAS)).all())
    aliases = [{"tag_set_id": ts.id, "kind": "set",
                "alias_of_id": ids[e.name.lower()],
                "category_id": trails.get(tuple(e.category)) if e.category else None,
                "name": a, "comment": "", "description": ""}
               for e in doc.entries for a in e.aliases]
    if aliases:
        s.execute(TagSetEntry.__table__.insert(), aliases)
    implies = [{"entry_id": ids[e.name.lower()], "implies_name": n,
                "implies_lname": n.lower()}
               for e in doc.entries for n in e.implies]
    if implies:
        s.execute(TagSetImplication.__table__.insert(), implies)
    # THE META TAGS THE FILE HAS SOMETHING TO SAY ABOUT FIRST, so a comment
    # or a description lands on the row rather than on a bare name minted
    # behind it; the rest arrive on the entries, as a category trail does.
    if doc.meta_tags:
        s.execute(MetaTag.__table__.insert(), [
            {"tag_set_id": ts.id, "kind": "meta", "name": m.name,
             "comment": m.comment, "description": m.description,
             "position": i + 1}
            for i, m in enumerate(doc.meta_tags)])
    _ensure_meta_rows(s, ts.id, [n for e in doc.entries for n in e.meta])
    marks = [{"tag_id": ids[e.name.lower()], "name": n, "count": 0}
             for e in doc.entries for n in e.meta]
    if marks:
        s.execute(TagMetaTag.__table__.insert(), marks)
    s.flush()


# ---- documents ----------------------------------------------------------------

def _doc_of(s: Session, ts: TagSet) -> fmt.TagSetDoc:
    trails = category_trails(s, ts.id)
    rows = s.execute(select(*entry_columns())
                     .where(TagSetEntry.tag_set_id == ts.id, NOT_ALIAS)
                     .order_by(TagSetEntry.position, TagSetEntry.id)).all()
    ids = [r.id for r in rows]
    al, im = aliases_of(s, ids), implications_of(s, ids)
    mt = meta_of(s, ids)
    entries = [fmt.EntryDoc(name=r.name, description=r.description or "",
                            count=r.count, comment=r.comment or "",
                            category=list(trails.get(r.category_id, []))
                            if r.category_id else [],
                            aliases=al.get(r.id, []), implies=im.get(r.id, []),
                            meta=mt.get(r.id, []),
                            **_doc_records(r))
               for r in rows]
    return fmt.TagSetDoc(key=ts.key, name=ts.name, description=ts.description or "",
                         version=int(ts.version or 0),
                         aliases=bool(ts.aliases_enabled),
                         implications=bool(ts.implications_enabled),
                         categories=_category_docs(s, ts, entries),
                         # ONLY THE ONES WITH SOMETHING TO SAY: a bare name
                         # rides on whichever entries carry it, and writing
                         # a row for it as well would be the file saying the
                         # same thing twice.
                         meta_tags=[fmt.MetaDoc(name=m.name,
                                                comment=m.comment or "",
                                                description=m.description or "")
                                    for m in meta_tags_of(s, ts.id)
                                    if m.comment or m.description],
                         entries=entries)


def export_document(s: Session, set_id: int) -> dict:
    """The set as its file."""
    if is_library(s, set_id):
        return export_library(s)
    return fmt.dump(_doc_of(s, by_id(s, set_id)))


def export_library(s: Session) -> dict:
    """THE LIBRARY'S OWN TAG SET as an ordinary format-2 tag-set file.

    Its own export, not `_doc_of`'s: the library's set row holds no entries
    — its names are the `tags` table — so the generic path would write a
    file with nothing in it. Every tag becomes an entry carrying what the
    library knows about the name: its long form, its one-liner, its other
    spellings, what it entails, where it is filed, and what it IS.

    IMPORTED INTO ANOTHER LIBRARY it is a set like any other: advice,
    written into that library only when one of its names is assigned. Which
    is the point of it — a tag set somebody built by hand is worth
    carrying to the next library, and until now the only way was the tag
    CSV, which knows nothing about categories or descriptions.

    An ALIAS is not an entry of its own here: it is a spelling of the tag it
    points at, which is exactly what the file's `aliases` key is for.

    NOTHING IS LEFT OUT ANY MORE. A ranking used to mint `<prefix>:0`…`:9`
    and assign them, and this walk dropped those rows — a hundred
    `quality:N` entries are noise in every library but the one that made
    them. Rung v31 took the namespace, the minting and `score_names_of`
    with it, and the filter went on calling it: every export of a library
    holding a ranking answered 500. A ranking mints nothing now, so there
    is nothing here that is not somebody's own tag.
    """
    from ..db import Location, Occasion, Subject, Tag

    lib = library_set(s)
    trails = category_trails(s, lib.id) if lib is not None else {}
    rows = list(s.execute(select(Tag).order_by(Tag.name)).scalars())
    by_id_map = {t.id: t for t in rows}
    # Their other spellings, and what they entail — one statement each.
    aliases: dict[int, list[str]] = {}
    for t in rows:
        if t.alias_of_id is not None:
            aliases.setdefault(t.alias_of_id, []).append(t.name)
    from ..resolve import tag_implications
    implies = tag_implications(s)
    # …and what the library says each name IS.
    subjects = {r.tag_id: r for r in s.execute(
        select(Subject).where(Subject.tag_id.isnot(None))).scalars()}
    places = {r.tag_id: r for r in s.execute(
        select(Location).where(Location.tag_id.isnot(None))).scalars()}
    events = {r.tag_id: r for r in s.execute(
        select(Occasion).where(Occasion.tag_id.isnot(None))).scalars()}
    place_by_id = {r.id: r for r in places.values()}
    event_by_id = {r.id: r for r in events.values()}

    def tag_name(tid: Optional[int]) -> str:
        row = by_id_map.get(tid) if tid is not None else None
        return row.name if row is not None else ""

    entries: list[fmt.EntryDoc] = []
    for t in rows:
        if t.alias_of_id is not None:
            continue
        sub, pl, ev = subjects.get(t.id), places.get(t.id), events.get(t.id)
        entries.append(fmt.EntryDoc(
            name=t.name, description=t.description or "",
            comment=t.comment or "",
            category=list(trails.get(t.category_id, [])) if t.category_id else [],
            aliases=sorted(aliases.get(t.id, [])),
            implies=sorted(implies.get(t.name, set())),
            subject=None if sub is None else fmt.SubjectDoc(
                name=sub.display_name or "", since=sub.since_date),
            place=None if pl is None else fmt.PlaceDoc(
                name=pl.name or "", lat=pl.lat, lon=pl.lon,
                parent=tag_name(place_by_id[pl.parent_id].tag_id
                                if pl.parent_id in place_by_id else None)),
            event=None if ev is None else fmt.EventDoc(
                name=ev.display_name or "", start=ev.start_date, end=ev.end_date,
                parent=tag_name(event_by_id[ev.parent_id].tag_id
                                if ev.parent_id in event_by_id else None)),
        ))
    doc = fmt.TagSetDoc(
        key=LIBRARY_KEY,
        name=(lib.name if lib is not None else LIBRARY_NAME),
        description=(lib.description if lib is not None else ""),
        version=0, aliases=True, implications=True,
        categories=_category_docs(s, lib, entries) if lib is not None else [],
        entries=entries)
    return fmt.dump(doc)


# ---- logged ops -----------------------------------------------------------------

def _refuse_builtin(ts: TagSet) -> None:
    if ts.builtin:
        raise Refused("the built-in tag set is read-only — duplicate it to edit",
                      code="tag_set_builtin")


def _refuse_library(ts: TagSet) -> None:
    """THE LIBRARY'S OWN SET IS NOT ONE OF THE SETS to be got rid of.

    Its rows are the library's tags — the ones on pictures, in searches and
    in training prompts — so deleting it is not "remove a tag set", it is
    "empty the catalog", and nothing that asks for the first means the
    second. `TagSetOut.library` has said "not deletable" on the wire since
    the row was invented; the lists that drew it simply never read the flag,
    and this is the floor under them.
    """
    if ts.key == LIBRARY_KEY:
        raise Refused("the library's own tag set cannot be deleted",
                      code="tag_set_is_library")


def _key_taken(s: Session, key: str) -> bool:
    """Is this key spoken for? `LIBRARY_KEY` always is, whether or not the
    row exists yet — it is lazy, so "nothing has it" is not "it is free"."""
    return key == LIBRARY_KEY or by_key(s, key) is not None


def _free_key(s: Session, key: str) -> str:
    key = fmt.check_key(key)
    if _key_taken(s, key):
        raise Conflict("a tag set with that key already exists",
                       code="tag_set_key_taken")
    return key


def _refuse_taken_name(s: Session, name: str, *, except_id: Optional[int] = None) -> None:
    """A set's NAME is what every pill, chip and dropdown shows, so two sets
    of one name are two things nobody can tell apart — refused on create and
    on rename (case-insensitively), the way a tag name is. The KEY was always
    unique; this makes the name it is derived from unique too. An import goes
    through `create_tag_set` and so is held to it — a second import of one
    file is refused by name rather than making a twin — while `duplicate`
    numbers its copy past a clash (`_free_name`)."""
    ln = (name or "").strip().lower()
    for ts in _every_set(s):
        if ts.id != except_id and (ts.name or "").strip().lower() == ln:
            raise Conflict("a tag set with that name already exists",
                           code="tag_set_name_taken")


def _free_name(s: Session, base: str) -> str:
    """`base`, or `base 2`, `base 3`… — the first not already a set's name."""
    taken = {(ts.name or "").strip().lower() for ts in all_sets(s)}
    name, n = base, 2
    while name.strip().lower() in taken:
        name = f"{base} {n}"
        n += 1
    return name


def _unique_key(s: Session, base: str) -> str:
    base = fmt.slug_key(base)
    key, n = base, 2
    while _key_taken(s, key):
        key = f"{base[:60]}-{n}"
        n += 1
    return key


def create_tag_set(ctx: Ctx, *, name: str, key: str = "",
                   description: str = "", version: int = 0) -> TagSet:
    s = ctx.session
    name = (name or "").strip()
    if not name:
        raise Invalid("a tag set needs a name", code="tag_set_name_required")
    _refuse_taken_name(s, name)
    k = _free_key(s, key.strip()) if key.strip() else _unique_key(s, name)
    row = TagSet(key=k, name=name, description=description or "",
                 version=int(version or 0), builtin=False,
                 enabled=True, position=_next_position(s))
    s.add(row)
    s.flush()
    ctx.log(action=actions.CREATE_TAG_SET, entity_type="tag_set", entity_id=row.id,
            summary="Created tag set {name}", summary_vars={"name": name},
            data={"tag_set_id": row.id, "key": k, "name": name,
                  "description": description or "", "version": int(version or 0),
                  "position": row.position})
    return row


def edit_tag_set(ctx: Ctx, set_id: int, *, name: Optional[str] = None,
                 description: Optional[str] = None,
                 version: Optional[int] = None,
                 position: Optional[int] = None,
                 aliases_enabled: Optional[bool] = None,
                 implications_enabled: Optional[bool] = None) -> TagSet:
    s = ctx.session
    ts = by_id(s, set_id)
    if ts.builtin and (name is not None or description is not None
                       or version is not None):
        _refuse_builtin(ts)
    data: dict[str, Any] = {"tag_set_id": ts.id, "key": ts.key}
    if name is not None and name.strip() and name.strip() != ts.name:
        _refuse_taken_name(s, name, except_id=ts.id)
        data["old_name"], data["name"] = ts.name, name.strip()
        ts.name = name.strip()
    if description is not None and description != (ts.description or ""):
        data["old_description"], data["description"] = ts.description or "", description
        ts.description = description
    if version is not None and int(version) != int(ts.version or 0):
        data["old_version"], data["version"] = int(ts.version or 0), int(version)
        ts.version = int(version)
    if position is not None and int(position) != int(ts.position or 0):
        data["old_position"], data["position"] = int(ts.position or 0), int(position)
        ts.position = int(position)
    # The two ADVICE switches ride the same event as the rest of the set's
    # fields — one edit, one revert. Booleans, so the "either half is set"
    # test `_revert_edit_tag_set` uses works on them as it does on a name.
    for field_, want in (("aliases_enabled", aliases_enabled),
                         ("implications_enabled", implications_enabled)):
        if want is not None and bool(want) != bool(getattr(ts, field_)):
            data[f"old_{field_}"] = bool(getattr(ts, field_))
            data[field_] = bool(want)
            setattr(ts, field_, bool(want))
    if len(data) == 2:
        return ts
    s.flush()
    ctx.log(action=actions.EDIT_TAG_SET, entity_type="tag_set", entity_id=ts.id,
            summary="Edited tag set {name}", summary_vars={"name": ts.name},
            data=data)
    return ts


def set_enabled(ctx: Ctx, set_id: int, enabled: bool) -> TagSet:
    s = ctx.session
    ts = by_id(s, set_id)
    if bool(ts.enabled) == bool(enabled):
        return ts
    old = bool(ts.enabled)
    ts.enabled = bool(enabled)
    s.flush()
    ctx.log(action=actions.SET_TAG_SET_ENABLED, entity_type="tag_set",
            entity_id=ts.id,
            summary=("Enabled tag set {name}" if enabled
                     else "Disabled tag set {name}"),
            summary_vars={"name": ts.name},
            data={"tag_set_id": ts.id, "key": ts.key, "enabled": bool(enabled),
                  "old_enabled": old})
    return ts


def delete_tag_set(ctx: Ctx, set_id: int) -> None:
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    _refuse_library(ts)
    n_entries, _ = counts_of(s).get(ts.id, (0, 0))
    ctx.log(action=actions.DELETE_TAG_SET, entity_type="tag_set", entity_id=ts.id,
            summary="Deleted tag set {name} ({count} entries)",
            summary_vars={"name": ts.name, "count": n_entries},
            data={"tag_set_id": ts.id, "key": ts.key, "name": ts.name,
                  "entries": n_entries})
    _clear_rows(s, ts.id)
    s.delete(ts)
    s.flush()


def duplicate_tag_set(ctx: Ctx, set_id: int, *, name: str,
                      key: str = "") -> TagSet:
    """A user copy of a set, the way the built-in one is edited."""
    s = ctx.session
    src = by_id(s, set_id)
    name = (name or "").strip() or _free_name(s, f"{src.name} (copy)")
    _refuse_taken_name(s, name)
    k = _free_key(s, key.strip()) if key.strip() else _unique_key(s, name)
    doc = _doc_of(s, src)
    doc.key, doc.name = k, name
    row = TagSet(key=k, name=name, description=doc.description, version=doc.version,
                 builtin=False, enabled=bool(src.enabled),
                 position=_next_position(s))
    s.add(row)
    s.flush()
    _write_doc(s, row, doc)
    ctx.log(action=actions.DUPLICATE_TAG_SET, entity_type="tag_set",
            entity_id=row.id,
            summary="Duplicated tag set {name} as {copy}",
            summary_vars={"name": src.name, "copy": name},
            data={"tag_set_id": src.id, "key": src.key, "new_tag_set_id": row.id,
                  "new_key": k, "name": name})
    return row


# ---- categories -----------------------------------------------------------------

def _category(s: Session, set_id: int, cat_id: int) -> TagSetCategory:
    row = s.get(TagSetCategory, cat_id)
    if row is None or row.tag_set_id != set_id:
        raise NotFound("category not found", code="tag_set_category_not_found")
    return row


def _check_category_name(s: Session, set_id: int, name: str,
                         parent_id: Optional[int], *, ignore: Optional[int] = None
                         ) -> str:
    name = (name or "").strip()
    if not name:
        raise Invalid("a category needs a name", code="tag_set_category_name")
    # A '/' is an ORDINARY character here (owner decision, 2026-09). It used
    # to be refused because a category was addressed by a slash-joined path;
    # nothing joins one any more — the file, the wire and the sort all carry
    # the trail as a list of names — so there is nothing left for the ban to
    # protect, and `and/or` is a category somebody wants.
    stmt = select(TagSetCategory.id).where(
        TagSetCategory.tag_set_id == set_id,
        func.lower(TagSetCategory.name) == name.lower(),
        TagSetCategory.parent_id.is_(None) if parent_id is None
        else TagSetCategory.parent_id == parent_id)
    if ignore is not None:
        stmt = stmt.where(TagSetCategory.id != ignore)
    if s.execute(stmt).first() is not None:
        raise Conflict("a category of that name already exists here",
                       code="tag_set_category_taken")
    return name


def _would_cycle(s: Session, cat_id: int, parent_id: Optional[int]) -> bool:
    seen: set[int] = set()
    cur = parent_id
    while cur is not None and cur not in seen:
        if cur == cat_id:
            return True
        seen.add(cur)
        row = s.get(TagSetCategory, cur)
        cur = row.parent_id if row is not None else None
    return cur is not None  # a pre-existing loop reads as a cycle too


#: What separates two category names where one STRING has to hold the trail:
#: an event's summary sentence, and nothing else. Not a path separator — the
#: trail travels as a list everywhere it is read back, and this is only ever
#: written for a person to look at (the UI draws the same chevron).
TRAIL_SEP = " › "


def _cat_label(s: Session, set_id: int, cat_id: int) -> str:
    """The trail as one string, for an event's summary sentence."""
    return TRAIL_SEP.join(category_trails(s, set_id).get(cat_id, []))


def trail_label(s: Session, cat_id: int) -> str:
    """The same one string, for a caller that has a category and not the set
    it belongs to (`tagcatalog.set_category`, which is handed a library
    category id and nothing else)."""
    cat = s.get(TagSetCategory, int(cat_id))
    return "" if cat is None else _cat_label(s, cat.tag_set_id, cat.id)


def create_category(ctx: Ctx, set_id: int, *, name: str,
                    parent_id: Optional[int] = None,
                    icon: str = "", hidden: bool = False,
                    aliases: Optional[bool] = None,
                    implications: Optional[bool] = None) -> TagSetCategory:
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    if parent_id is not None:
        _category(s, set_id, parent_id)
    name = _check_category_name(s, set_id, name, parent_id)
    pos = s.execute(select(func.max(TagSetCategory.position)).where(
        TagSetCategory.tag_set_id == set_id,
        TagSetCategory.parent_id.is_(None) if parent_id is None
        else TagSetCategory.parent_id == parent_id)).scalar()
    row = TagSetCategory(tag_set_id=set_id, parent_id=parent_id, name=name,
                         icon=(icon or "").strip(), hidden=bool(hidden),
                         aliases=aliases, implications=implications,
                         position=int(pos or 0) + 1)
    s.add(row)
    s.flush()
    ctx.log(action=actions.CREATE_TAG_SET_CATEGORY, entity_type="tag_set",
            entity_id=ts.id,
            summary="Added category {path} to tag set {name}",
            summary_vars={"path": _cat_label(s, set_id, row.id), "name": ts.name},
            data={"tag_set_id": ts.id, "key": ts.key, "category_id": row.id,
                  "name": name, "parent_id": parent_id,
                  # Conditional, so a category with no icon and nothing
                  # hidden logs the payload every earlier build wrote.
                  **({"icon": row.icon} if row.icon else {}),
                  **({"hidden": True} if row.hidden else {})})
    return row


_UNSET: Any = object()


def _siblings(s: Session, set_id: int, parent_id: Optional[int]) -> list[TagSetCategory]:
    return list(s.execute(
        select(TagSetCategory).where(
            TagSetCategory.tag_set_id == set_id,
            TagSetCategory.parent_id.is_(None) if parent_id is None
            else TagSetCategory.parent_id == parent_id)
        .order_by(TagSetCategory.position, TagSetCategory.id)).scalars())


def _place_categories(s: Session, set_id: int, orders: dict) -> None:
    """Write sibling orders back: `orders` maps a parent id (or "root") to
    the ids under it, in order — every row named gets that parent and its
    index as position. The revert's and the redo's one primitive, so the two
    cannot renumber differently."""
    for key, ids in orders.items():
        parent = None if key in (None, "root") else int(key)
        for i, cid in enumerate(ids):
            row = s.get(TagSetCategory, cid)
            if row is None or row.tag_set_id != set_id:
                continue
            row.parent_id = parent
            row.position = i
    s.flush()


def move_category(ctx: Ctx, set_id: int, cat_id: int, *,
                  parent_id: Optional[int], index: int) -> TagSetCategory:
    """The tree's drag: put a category under `parent_id` (None = the top) at
    `index` among the siblings there. ONE event carrying both sibling orders
    before and after — the old parent's and the new one's — so the revert
    puts every row that moved back where it was, and a redo replays the same
    orders rather than re-deriving them (`_place_categories` both ways)."""
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    row = _category(s, set_id, cat_id)
    if parent_id is not None:
        _category(s, set_id, parent_id)
        if parent_id == row.id or _would_cycle(s, row.id, parent_id):
            raise Refused("a category cannot be inside itself",
                          code="tag_set_category_cycle")
    if parent_id != row.parent_id:
        _check_category_name(s, set_id, row.name, parent_id, ignore=row.id)
    key_of = lambda p: "root" if p is None else str(p)
    old_parent = row.parent_id
    before = {key_of(old_parent): [c.id for c in _siblings(s, set_id, old_parent)]}
    if parent_id != old_parent:
        before[key_of(parent_id)] = [c.id for c in _siblings(s, set_id, parent_id)]
    after = {k: [i for i in v if i != row.id] for k, v in before.items()}
    target = after.setdefault(key_of(parent_id), [])
    target.insert(max(0, min(int(index), len(target))), row.id)
    if after == before:
        return row
    _place_categories(s, set_id, after)
    ctx.log(action=actions.MOVE_TAG_SET_CATEGORY, entity_type="tag_set",
            entity_id=ts.id,
            summary="Moved category {path} in tag set {name}",
            summary_vars={"path": _cat_label(s, set_id, row.id), "name": ts.name},
            data={"tag_set_id": ts.id, "key": ts.key, "category_id": row.id,
                  "old_parent_id": old_parent, "parent_id": parent_id,
                  "old_orders": before, "orders": after})
    return row


def edit_category(ctx: Ctx, set_id: int, cat_id: int, *,
                  name: Optional[str] = None, parent_id: Any = _UNSET,
                  icon: Optional[str] = None, hidden: Optional[bool] = None,
                  aliases: Any = _UNSET, implications: Any = _UNSET,
                  position: Optional[int] = None) -> TagSetCategory:
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    row = _category(s, set_id, cat_id)
    data: dict[str, Any] = {"tag_set_id": ts.id, "key": ts.key, "category_id": row.id}
    new_parent = row.parent_id if parent_id is _UNSET else parent_id
    if parent_id is not _UNSET and new_parent != row.parent_id:
        if new_parent is not None:
            _category(s, set_id, new_parent)
            if new_parent == row.id or _would_cycle(s, row.id, new_parent):
                raise Refused("a category cannot be inside itself",
                              code="tag_set_category_cycle")
        data["old_parent_id"], data["parent_id"] = row.parent_id, new_parent
    new_name = row.name
    if name is not None and name.strip() != row.name:
        new_name = _check_category_name(s, set_id, name, new_parent, ignore=row.id)
        data["old_name"], data["name"] = row.name, new_name
    elif "parent_id" in data:
        _check_category_name(s, set_id, row.name, new_parent, ignore=row.id)
    if icon is not None and icon.strip() != (row.icon or ""):
        data["old_icon"], data["icon"] = row.icon or "", icon.strip()
    if hidden is not None and bool(hidden) != bool(row.hidden):
        data["old_hidden"], data["hidden"] = bool(row.hidden), bool(hidden)
    # THREE-STATE, so `None` is a value and cannot mean "unchanged": these
    # two take `_UNSET` the way `parent_id` does. The event names them in
    # `tri_fields` so the revert can tell "set it back to None" from "this
    # edit never touched it" — the `old_x is not None` test every other
    # field uses cannot.
    tri: list[str] = []
    for field_, want in (("aliases", aliases), ("implications", implications)):
        if want is _UNSET:
            continue
        want = None if want is None else bool(want)
        if want != getattr(row, field_):
            data[f"old_{field_}"], data[field_] = getattr(row, field_), want
            tri.append(field_)
    if tri:
        data["tri_fields"] = tri
    if position is not None and int(position) != int(row.position or 0):
        data["old_position"], data["position"] = int(row.position or 0), int(position)
    if len(data) == 3:
        return row
    row.name = new_name
    row.parent_id = new_parent
    if "icon" in data:
        row.icon = data["icon"]
    if "hidden" in data:
        row.hidden = data["hidden"]
    for field_ in tri:
        setattr(row, field_, data[field_])
    if "position" in data:
        row.position = data["position"]
    s.flush()
    ctx.log(action=actions.EDIT_TAG_SET_CATEGORY, entity_type="tag_set",
            entity_id=ts.id,
            summary="Edited category {path} in tag set {name}",
            summary_vars={"path": _cat_label(s, set_id, row.id), "name": ts.name},
            data=data)
    return row


def _category_shape(row: TagSetCategory, entries: list[int]) -> dict:
    """One category as the delete's snapshot records it. The optional fields
    are CONDITIONAL: a plain category writes exactly the payload every
    earlier build wrote, and a hidden one comes back hidden rather than as a
    category whose names the autocomplete has quietly started offering
    again."""
    return {"category_id": row.id, "name": row.name,
            "parent_id": row.parent_id, "position": int(row.position or 0),
            **({"icon": row.icon} if row.icon else {}),
            **({"hidden": True} if row.hidden else {}),
            **({"aliases": row.aliases} if row.aliases is not None else {}),
            **({"implications": row.implications}
               if row.implications is not None else {}),
            "entry_ids": entries}


def delete_category(ctx: Ctx, set_id: int, cat_id: int) -> None:
    """The category goes AND SO DOES EVERYTHING UNDER IT; every entry that
    was filed anywhere in the branch becomes uncategorized.

    Owner decision, 2026-09. It used to promote the children to the deleted
    category's parent, which is a defensible reading of "delete this one" and
    the wrong one here: a category is a shelf in an outline, and taking a
    shelf out while its sub-shelves stay leaves the outline saying something
    nobody wrote — twelve orphans at the top level of a 387-category
    template, to be re-filed by hand. Deleting the branch is what the tree
    looks like it does.

    The snapshot carries the whole branch (`descendants`, top-down, each with
    the entries it held) so a revert puts it back shelf for shelf. That key
    is written only when there IS a branch, so a childless delete records
    nothing extra.
    """
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    row = _category(s, set_id, cat_id)
    path = _cat_label(s, set_id, row.id)
    # Top-down, so a revert inserts each shelf after the one it hangs from.
    branch = category_subtree_ids(s, set_id, row.id)
    kids = [c for cid in branch if cid != row.id
            and (c := s.get(TagSetCategory, cid)) is not None]
    held = {cid: list(s.execute(select(TagSetEntry.id).where(
        TagSetEntry.category_id == cid)).scalars()) for cid in branch}
    snap = {"tag_set_id": ts.id, "key": ts.key,
            **_category_shape(row, held.get(row.id, [])),
            **({"descendants": [_category_shape(c, held.get(c.id, []))
                                for c in kids]} if kids else {})}
    for cid in branch:
        for chunk in chunked(held.get(cid, [])):
            s.execute(TagSetEntry.__table__.update()
                      .where(TagSetEntry.id.in_(chunk)).values(category_id=None))
    # Deepest first, so no row is deleted while another still points at it.
    for c in reversed(kids):
        s.delete(c)
    s.delete(row)
    s.flush()
    ctx.log(action=actions.DELETE_TAG_SET_CATEGORY, entity_type="tag_set",
            entity_id=ts.id,
            summary="Removed category {path} from tag set {name}",
            summary_vars={"path": path, "name": ts.name}, data=snap)


def restore_category(s: Session, snap: dict) -> bool:
    """The revert's half of `delete_category`: the row back under its old id,
    its children and entries re-linked."""
    if s.get(TagSetCategory, snap.get("category_id")) is not None:
        return False
    if s.get(TagSet, snap.get("tag_set_id")) is None:
        return False
    parent = snap.get("parent_id")
    if parent is not None and s.get(TagSetCategory, parent) is None:
        parent = None
    s.execute(TagSetCategory.__table__.insert().values(
        id=snap["category_id"], tag_set_id=snap["tag_set_id"], parent_id=parent,
        name=snap.get("name") or "",
        icon=snap.get("icon") or "",
        hidden=bool(snap.get("hidden")),
        aliases=snap.get("aliases"), implications=snap.get("implications"),
        position=int(snap.get("position") or 0)))
    # The whole branch, top-down under its own old ids.
    for kid in snap.get("descendants") or []:
        if s.get(TagSetCategory, kid.get("category_id")) is not None:
            continue
        up = kid.get("parent_id")
        s.execute(TagSetCategory.__table__.insert().values(
            id=kid["category_id"], tag_set_id=snap["tag_set_id"],
            parent_id=up if up is None or s.get(TagSetCategory, up) is not None
            else snap["category_id"],
            name=kid.get("name") or "", icon=kid.get("icon") or "",
            hidden=bool(kid.get("hidden")),
            aliases=kid.get("aliases"), implications=kid.get("implications"),
            position=int(kid.get("position") or 0)))
    for shelf in [snap, *(snap.get("descendants") or [])]:
        eids = [int(x) for x in (shelf.get("entry_ids") or [])]
        for chunk in chunked(eids):
            s.execute(TagSetEntry.__table__.update()
                      .where(TagSetEntry.id.in_(chunk),
                             TagSetEntry.tag_set_id == snap["tag_set_id"])
                      .values(category_id=shelf["category_id"]))
    s.flush()
    return True


# ---- entries --------------------------------------------------------------------

def _entry(s: Session, set_id: int, entry_id: int) -> TagSetEntry:
    row = s.get(TagSetEntry, entry_id)
    if row is None or row.tag_set_id != set_id:
        raise NotFound("entry not found", code="tag_set_entry_not_found")
    return row


def _taken(s: Session, set_id: int, lnames: list[str], *,
           ignore_entry: Optional[int] = None) -> Optional[str]:
    """The first of ``lnames`` another entry or alias of the set already
    holds, else None."""
    # ONE QUERY, because an alias IS a row of the set: what was two lookups
    # (the entries, then the aliases beside them) is the same question asked
    # of one table.
    for chunk in chunked(lnames):
        stmt = select(TagSetEntry.lname).where(
            TagSetEntry.tag_set_id == set_id, TagSetEntry.lname.in_(chunk))
        if ignore_entry is not None:
            stmt = stmt.where(TagSetEntry.id != ignore_entry,
                              or_(TagSetEntry.alias_of_id.is_(None),
                                  TagSetEntry.alias_of_id != ignore_entry))
        hit = s.execute(stmt).first()
        if hit:
            return hit[0]
    return None


def _clean_names(names: Iterable[str], where: str) -> list[str]:
    out: list[str] = []
    for n in names or []:
        try:
            c = fmt.check_tag_name(n, where)
        except fmt.FormatError as exc:
            raise Invalid(str(exc), code="tag_set_bad_name") from None
        if c.lower() not in {x.lower() for x in out}:
            out.append(c)
    return out


def _clean_trail(raw: Any) -> list[str]:
    """A bulk row's category, as the list of names down to it.

    A LIST is what the wire and the file carry. A STRING is still split on
    `/`, for the one caller that cannot send a list — a script, and the CSV
    import, whose one cell has to mean something. That spelling cannot name
    a category whose own name holds a slash, which is the documented price
    of a single cell (`docs/tag-sets.md`).
    """
    if raw is None:
        return []
    parts = raw.split("/") if isinstance(raw, str) else list(raw)
    return [str(p).strip() for p in parts if str(p).strip()]


def _set_aliases(s: Session, entry: TagSetEntry, names: list[str], *,
                 fresh: bool = False) -> None:
    """The entry's other spellings, as the ROWS they are: a row of the set
    pointing at this one, which is what a library alias always was.

    ``fresh`` is a row that was made a moment ago: nothing can point at it
    yet, so the delete is a statement per entry over the whole table for an
    answer that is always none — 17,245 of them in a template install."""
    if not fresh:
        s.execute(delete(TagSetEntry).where(TagSetEntry.alias_of_id == entry.id))
    if names:
        s.execute(TagSetEntry.__table__.insert(),
                  [_alias_row(entry.id, entry.tag_set_id, entry.category_id, n)
                   for n in names])


def _alias_row(entry_id: int, tag_set_id: Optional[int],
               category_id: Optional[int], name: str) -> dict:
    """ONE spelling as the row it is — written here and nowhere else, so the
    bulk path and the single one cannot say it differently.

    FILED WHERE ITS ENTRY IS. A spelling is a row of the list, so it is
    somewhere in the tree, and the only shelf it can mean is the one holding
    the name it spells — a booru dump's eight thousand spellings landing in
    Uncategorized would say the set is mostly unfiled when every one of them
    is filed.
    """
    return {"tag_set_id": tag_set_id, "kind": "set", "alias_of_id": entry_id,
            "comment": "", "description": "", "category_id": category_id,
            "name": name}


def meta_tags_of(s: Session, set_id: int) -> list[MetaTag]:
    """The META TAGS this tag set knows, in file order.

    A meta tag labels a NAME — "character", "noflip", "from a booru" — and
    never a picture, which is why it is its own kind of row rather than a
    tag: `red` the tag and `red` the meta tag are two different names. A
    set carries its own, so a tag set can say what it labels its entries
    with; `tag_set_id IS NULL` is the LIBRARY's, which is the namespace the
    four carriers (a link, a caption, a tag group, a tag) read.
    """
    return list(s.execute(
        select(MetaTag).where(MetaTag.tag_set_id == set_id)
        .order_by(MetaTag.position, MetaTag.id)).scalars())


def meta_of(s: Session, entry_ids: list[int]) -> dict[int, list[str]]:
    """entry id -> the meta tags it carries, by NAME.

    The same `tag_meta_tags` rows a library tag's meta tags are: since the
    two tag sets became one table, an entry IS a `tags` row and the
    assignment needed nothing of its own.
    """
    out: dict[int, list[str]] = {}
    for chunk in chunked(entry_ids):
        for eid, name in s.execute(
                select(TagMetaTag.tag_id, TagMetaTag.name)
                .where(TagMetaTag.tag_id.in_(chunk))
                .order_by(TagMetaTag.id)).all():
            out.setdefault(eid, []).append(name)
    return out


def _ensure_meta_rows(s: Session, set_id: int, names: Sequence[str]) -> None:
    """Mint the set's missing meta-tag rows. A name an entry carries is one
    the tag set knows, exactly as a category trail an entry names is a
    category the tag set has."""
    if not names:
        return
    have = {r.lower() for r in s.execute(
        select(MetaTag.lname).where(MetaTag.tag_set_id == set_id)).scalars()}
    fresh = [n for n in dict.fromkeys(names) if n.lower() not in have]
    if not fresh:
        return
    mx = s.execute(select(func.max(MetaTag.position))
                   .where(MetaTag.tag_set_id == set_id)).scalar() or 0
    s.execute(MetaTag.__table__.insert(), [
        {"tag_set_id": set_id, "kind": "meta", "name": n, "comment": "",
         "description": "", "position": mx + i + 1}
        for i, n in enumerate(fresh)])


def _set_meta_names(s: Session, entry: TagSetEntry, names: list[str], *,
                    fresh: bool = False) -> None:
    """What this entry says the tag is LABELLED with. The names are minted
    into the set's own meta tag set first, for the same reason a category
    trail is made: the entry naming one is what says the set knows it."""
    if not fresh:
        s.execute(delete(TagMetaTag).where(TagMetaTag.tag_id == entry.id))
    if not names:
        return
    _ensure_meta_rows(s, entry.tag_set_id, names)
    s.execute(TagMetaTag.__table__.insert(),
              [_meta_row(entry.id, n) for n in names])


def _meta_row(entry_id: int, name: str) -> dict:
    return {"tag_id": entry_id, "name": name, "count": 0}


def _meta(s: Session, set_id: int, meta_id: int) -> MetaTag:
    row = s.get(MetaTag, meta_id)
    if row is None or row.tag_set_id != set_id or row.kind != "meta":
        raise NotFound("that meta tag is not in this tag set",
                       code="tag_set_meta_not_found")
    return row


def _meta_taken(s: Session, set_id: int, lname: str, *,
                ignore: Optional[int] = None) -> bool:
    stmt = select(MetaTag.id).where(MetaTag.tag_set_id == set_id,
                                    MetaTag.lname == lname)
    if ignore is not None:
        stmt = stmt.where(MetaTag.id != ignore)
    return s.execute(stmt).first() is not None


def create_meta_tag(ctx: Ctx, set_id: int, *, name: str, comment: str = "",
                    description: str = "") -> MetaTag:
    """A meta tag of this tag set's own — a label it puts on its names.

    An entry naming one makes it too (`_ensure_meta_rows`, the category
    trail's rule); this is the door for the ones somebody wants to describe
    before anything carries them.
    """
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    cname = _clean_names([name], "name")[0]
    if _meta_taken(s, set_id, cname.lower()):
        raise Conflict("“{name}” is already a meta tag of this set",
                       {"name": cname}, code="tag_set_meta_taken")
    mx = s.execute(select(func.max(MetaTag.position))
                   .where(MetaTag.tag_set_id == set_id)).scalar() or 0
    row = MetaTag(tag_set_id=set_id, name=cname, comment=(comment or "").strip(),
                  description=description or "", position=int(mx) + 1)
    s.add(row)
    s.flush()
    ctx.log(action=actions.CREATE_TAG_SET_META, entity_type="tag_set",
            entity_id=ts.id,
            summary="Added meta tag {entry} to tag set {name}",
            summary_vars={"entry": row.name, "name": ts.name},
            data={"tag_set_id": ts.id, "key": ts.key, "meta_id": row.id,
                  "name": row.name, "comment": row.comment,
                  "description": row.description})
    return row


def edit_meta_tag(ctx: Ctx, set_id: int, meta_id: int, *,
                  name: Optional[str] = None, comment: Optional[str] = None,
                  description: Optional[str] = None) -> MetaTag:
    """Rename or re-describe one. A RENAME carries the assignments with it:
    the entries name the label by string, exactly as the library's four
    carriers do, so the rows that say so have to be rewritten."""
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    row = _meta(s, set_id, meta_id)
    data: dict[str, Any] = {"tag_set_id": ts.id, "key": ts.key,
                            "meta_id": row.id}
    if name is not None:
        cname = _clean_names([name], "name")[0]
        if cname != row.name:
            if _meta_taken(s, set_id, cname.lower(), ignore=row.id):
                raise Conflict("“{name}” is already a meta tag of this set",
                               {"name": cname}, code="tag_set_meta_taken")
            data["old_name"], data["name"] = row.name, cname
    if comment is not None and comment.strip() != (row.comment or ""):
        data["old_comment"], data["comment"] = row.comment or "", comment.strip()
    if description is not None and description != (row.description or ""):
        data["old_description"], data["description"] = (row.description or "",
                                                        description)
    if len(data) == 3:
        return row
    apply_meta_fields(s, row, data)
    ctx.log(action=actions.EDIT_TAG_SET_META, entity_type="tag_set",
            entity_id=ts.id,
            summary="Edited meta tag {entry} in tag set {name}",
            summary_vars={"entry": row.name, "name": ts.name}, data=data)
    return row


def apply_meta_fields(s: Session, row: MetaTag, fields: dict) -> None:
    """The NEW half of an edit payload onto the row — and the rename onto
    every entry of the set that carries the label."""
    if "name" in fields and fields["name"] != row.name:
        was, now = row.name, fields["name"]
        row.name = now
        eids = select(TagSetEntry.id).where(
            TagSetEntry.tag_set_id == row.tag_set_id)
        s.execute(TagMetaTag.__table__.update()
                  .where(TagMetaTag.tag_id.in_(eids),
                         func.lower(TagMetaTag.name) == was.lower())
                  .values(name=now))
    if "comment" in fields:
        row.comment = fields["comment"] or ""
    if "description" in fields:
        row.description = fields["description"] or ""
    s.flush()


def meta_snapshot(s: Session, row: MetaTag) -> dict:
    """What a delete has to be able to put back — the row, and every entry
    of the set that carried it."""
    eids = select(TagSetEntry.id).where(
        TagSetEntry.tag_set_id == row.tag_set_id)
    on = list(s.execute(
        select(TagMetaTag.tag_id).where(
            TagMetaTag.tag_id.in_(eids),
            func.lower(TagMetaTag.name) == row.lname)).scalars())
    return {"meta_id": row.id, "name": row.name, "comment": row.comment or "",
            "description": row.description or "",
            "position": int(row.position or 0),
            **({"entry_ids": on} if on else {})}


def delete_meta_tag(ctx: Ctx, set_id: int, meta_id: int) -> None:
    """The label goes, and so does every entry's claim to carry it — a name
    nothing in the tag set knows is not advice, it is a typo."""
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    row = _meta(s, set_id, meta_id)
    snap = meta_snapshot(s, row)
    eids = select(TagSetEntry.id).where(TagSetEntry.tag_set_id == set_id)
    s.execute(delete(TagMetaTag).where(
        TagMetaTag.tag_id.in_(eids),
        func.lower(TagMetaTag.name) == row.lname))
    name = row.name
    s.delete(row)
    s.flush()
    ctx.log(action=actions.DELETE_TAG_SET_META, entity_type="tag_set",
            entity_id=ts.id,
            summary="Removed meta tag {entry} from tag set {name}",
            summary_vars={"entry": name, "name": ts.name},
            data={"tag_set_id": ts.id, "key": ts.key, **snap})


def restore_meta_tag(s: Session, set_id: int, snap: dict) -> bool:
    """The revert's half of `delete_meta_tag` (and of a create's redo)."""
    ts = s.get(TagSet, set_id)
    if ts is None or s.get(MetaTag, snap.get("meta_id")) is not None:
        return False
    row = MetaTag(id=snap.get("meta_id"), tag_set_id=set_id,
                  name=snap["name"], comment=snap.get("comment") or "",
                  description=snap.get("description") or "",
                  position=int(snap.get("position") or 0))
    s.add(row)
    s.flush()
    back = [e for e in (snap.get("entry_ids") or [])
            if s.get(TagSetEntry, e) is not None]
    if back:
        s.execute(TagMetaTag.__table__.insert(), [
            {"tag_id": e, "name": row.name, "count": 0} for e in back])
    s.flush()
    return True


def meta_uses(s: Session, set_id: int) -> dict[str, int]:
    """lowercase meta-tag name -> how many of the set's entries carry it."""
    eids = select(TagSetEntry.id).where(TagSetEntry.tag_set_id == set_id)
    return {n.lower(): int(c) for n, c in s.execute(
        select(TagMetaTag.name, func.count())
        .where(TagMetaTag.tag_id.in_(eids))
        .group_by(func.lower(TagMetaTag.name))).all()}


def _drop_self(names: Iterable[str], own: str, aliases: Iterable[str]) -> list[str]:
    """The implied names that are not this entry itself. An entry's own name
    and its own aliases assign the same tag, so implying one would be the
    tag implying itself — which the library refuses and which says nothing
    anyway."""
    me = {own.lower(), *(a.lower() for a in aliases)}
    return [n for n in names if n.lower() not in me]


def _set_implies(s: Session, entry: TagSetEntry, names: list[str], *,
                 fresh: bool = False) -> None:
    """What this entry entails, by NAME.

    ``fresh`` is `_set_aliases`' flag and it is here for the same reason,
    doubled: on a row made a moment ago nothing can point at it, so the
    delete is a statement per entry for an answer that is always none —
    and an ORM `delete()` does not stop at the statement. Its default
    `synchronize_session` walks the session's identity map to see which
    loaded objects the criteria matched, which over an import is every
    entry read so far: 24.6 million `mapper.isa` calls and 51% of the
    whole run for 8,000 entries, growing with the square of the set.
    """
    if not fresh:
        s.execute(delete(TagSetImplication).where(TagSetImplication.entry_id == entry.id))
    if names:
        s.execute(TagSetImplication.__table__.insert(),
                  [_implies_row(entry.id, n) for n in names])


def _implies_row(entry_id: int, name: str) -> dict:
    return {"entry_id": entry_id, "implies_name": name,
            "implies_lname": name.lower()}


#: THE THREE RECORDS AND THEIR FIELDS, written down once.
#:
#: A tag set entry may say that its name IS somebody, a place or an event —
#: the same three things that are data ON a tag in the library, never a
#: catalog beside it. The columns are `is_<kind>` plus `<kind>_<field>`, so
#: everything below is one table lookup rather than twelve spellings.
RECORD_FIELDS: dict[str, tuple[str, ...]] = {
    "subject": ("name", "since"),
    "place": ("name", "lat", "lon", "parent"),
    "event": ("name", "start", "end", "parent"),
}

#: Which of a record's fields is which KIND of value, for cleaning and for
#: the wire. Everything not named here is text.
_RECORD_DATES = {"since", "start", "end"}
_RECORD_COORDS = {"lat": 90.0, "lon": 180.0}
_RECORD_TAGS = {"parent"}


def entry_columns() -> tuple:
    """The COLUMNS an export reads off an entry, records and all.

    Named rather than entity-selected, and derived from `RECORD_FIELDS` so
    a fourth kind of record cannot be forgotten here. Selecting the entity
    builds a `TagSetEntry` object per row and puts it in the identity map,
    which for a 110,000-entry set is 145,000 attribute populations and most
    of the export; a `Row` answers `.is_subject` and `.subject_name` the
    same way for a tenth of the work, which is why `record_of` takes
    anything with the attributes rather than the class.
    """
    return (TagSetEntry.id, TagSetEntry.name, TagSetEntry.description,
            TagSetEntry.count, TagSetEntry.comment, TagSetEntry.category_id,
            *(getattr(TagSetEntry, f"is_{k}") for k in RECORD_FIELDS),
            *(getattr(TagSetEntry, f"{k}_{f}")
              for k, fields in RECORD_FIELDS.items() for f in fields))


def record_of(row: TagSetEntry, kind: str) -> Optional[dict]:
    """One record as a plain dict, or None where the entry does not say.

    An EMPTY dict is a record: "this name is a person" is the whole of what
    a tag set often knows, and it is not the same as saying nothing.
    """
    if not getattr(row, f"is_{kind}"):
        return None
    out: dict[str, Any] = {}
    for f in RECORD_FIELDS[kind]:
        val = getattr(row, f"{kind}_{f}")
        if val not in (None, ""):
            out[f] = val
    return out


def full_record(kind: str, rec: Optional[dict]) -> Optional[dict]:
    """A record with every field of its kind present, defaults and all —
    what a wire shape looks like once a response model has filled it in.
    None stays None: "the set does not say" is not an empty record."""
    if rec is None:
        return None
    out: dict[str, Any] = {}
    for f in RECORD_FIELDS[kind]:
        default = None if (f in _RECORD_DATES or f in _RECORD_COORDS) else ""
        out[f] = rec.get(f, default)
    return out


def records_of(row: TagSetEntry) -> dict[str, Any]:
    """Everything the entry says about the LIBRARY's tag — the comment and
    the three records. The keys that say nothing are absent."""
    out: dict[str, Any] = {}
    if row.comment:
        out["comment"] = row.comment
    for kind in RECORD_FIELDS:
        rec = record_of(row, kind)
        if rec is not None:
            out[kind] = rec
    return out


def clean_record(kind: str, raw: Any) -> Optional[dict]:
    """A record from the wire, checked. None passes through as "says
    nothing"; anything else must be an object, and each field is held to
    what it is — a partial date, a coordinate, a tag name, or text."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise Invalid("a record is an object", code="tag_set_bad_record")
    out: dict[str, Any] = {}
    for f in RECORD_FIELDS[kind]:
        val = raw.get(f)
        if val is None or val == "":
            continue
        if f in _RECORD_DATES:
            try:
                n = int(val)
            except (TypeError, ValueError):
                raise Invalid(
                    "a date is the number YYYYMMDD, with zeros for what is "
                    "not known", code="tag_set_bad_date") from None
            if not (0 <= n <= 99991231):
                raise Invalid(
                    "a date is the number YYYYMMDD, with zeros for what is "
                    "not known", code="tag_set_bad_date")
            if n:
                out[f] = n
        elif f in _RECORD_COORDS:
            try:
                x = float(val)
            except (TypeError, ValueError):
                raise Invalid("a coordinate is a number",
                              code="tag_set_bad_coord") from None
            limit = _RECORD_COORDS[f]
            if not (-limit <= x <= limit):
                raise Invalid("a coordinate is out of range",
                              code="tag_set_bad_coord")
            out[f] = x
        elif f in _RECORD_TAGS:
            out[f] = _clean_names([str(val)], f)[0]
        else:
            text = str(val).strip()
            if text:
                out[f] = text
    return out


def _record_values(kind: str, rec: Optional[dict]) -> dict:
    """A cleaned record as the COLUMNS it is — the flag AND every field, so
    a record taken away leaves nothing of the last one behind.

    Values rather than an assignment, because a row is built two ways: one
    at a time as an object, and by the chunk as a dict handed to an INSERT.
    """
    out: dict[str, Any] = {f"is_{kind}": rec is not None}
    for f in RECORD_FIELDS[kind]:
        default = None if (f in _RECORD_DATES or f in _RECORD_COORDS) else ""
        out[f"{kind}_{f}"] = ((rec or {}).get(f, default)
                              if rec is not None else default)
    return out


def _apply_record(row: TagSetEntry, kind: str, rec: Optional[dict]) -> None:
    """One record onto an existing row."""
    for col, val in _record_values(kind, rec).items():
        setattr(row, col, val)


def _self_parent(rec: Optional[dict], own: str,
                 aliases: Iterable[str]) -> Optional[dict]:
    """A record naming ITSELF as its parent names none — the rule `implies`
    keeps: its own name and its own aliases both assign this very tag, so a
    parent spelled that way is the entry pointing at itself."""
    if rec is None or not rec.get("parent"):
        return rec
    me = {own.lower(), *(a.lower() for a in aliases)}
    if str(rec["parent"]).lower() in me:
        rec = dict(rec)
        rec.pop("parent")
    return rec


def entry_snapshot(s: Session, row: TagSetEntry) -> dict:
    im = implications_of(s, [row.id]).get(row.id, [])
    mt = meta_of(s, [row.id]).get(row.id, [])
    # AN ALIAS ROW SNAPSHOTS WHAT IT SPELLS, by name — the id would be a
    # stale number after the target's own delete and restore. Conditional,
    # like the three below: an entry writes exactly the payload the builds
    # without this field wrote, which is what keeps the golden identical.
    of = alias_target_name(s, row)
    return {"entry_id": row.id, "name": row.name, "description": row.description or "",
            "count": row.count, "category_id": row.category_id,
            "position": int(row.position or 0),
            "aliases": aliases_of(s, [row.id]).get(row.id, []),
            # Conditional, so an entry that implies nothing snapshots exactly
            # the payload the builds without this field wrote — which is what
            # keeps the history golden byte-identical. The records go in the
            # same way and for the same reason.
            **({"implies": im} if im else {}),
            **({"meta": mt} if mt else {}),
            **({"alias_of": of} if of else {}),
            **records_of(row)}


def create_entry(ctx: Ctx, set_id: int, *, name: str, description: str = "",
                 count: Optional[int] = None, category_id: Optional[int] = None,
                 aliases: Iterable[str] = (), implies: Iterable[str] = (),
                 meta: Iterable[str] = (),
                 comment: str = "", records: Optional[dict] = None
                 ) -> TagSetEntry:
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    row = _make_entry(s, ts, name=name, description=description, count=count,
                      category_id=category_id, aliases=aliases,
                      implies=implies, meta=meta, comment=comment,
                      records=records)
    snap = entry_snapshot(s, row)
    ctx.log(action=actions.CREATE_TAG_SET_ENTRY, entity_type="tag_set",
            entity_id=ts.id,
            summary="Added {entry} to tag set {name}",
            summary_vars={"entry": row.name, "name": ts.name},
            data={"tag_set_id": ts.id, "key": ts.key, **snap})
    return row


def _make_entry(s: Session, ts: TagSet, *, name: str, description: str,
                count: Optional[int], category_id: Optional[int],
                aliases: Iterable[str], implies: Iterable[str] = (),
                meta: Iterable[str] = (),
                comment: str = "", records: Optional[dict] = None,
                entry_id: Optional[int] = None,
                position: Optional[int] = None) -> TagSetEntry:
    cname = _clean_names([name], "name")[0]
    al = _clean_names(aliases, "aliases")
    # An implied NAME is held to the tag-name rule and to nothing else: it
    # may name a tag the library has never heard of — that is the point, the
    # door mints it — and it may be another entry of this set. What it may
    # not be is THIS entry under another spelling: its own name, or one of
    # its own aliases, both of which assign this very tag. Dropped rather
    # than refused, since the file that says it means the tag it names.
    im = _drop_self(_clean_names(implies, "implies"), cname, al)
    if cname.lower() in {a.lower() for a in al}:
        raise Invalid("an entry cannot be its own alias", code="tag_set_bad_name")
    clash = _taken(s, ts.id, [cname.lower(), *[a.lower() for a in al]])
    if clash is not None:
        raise Conflict("“{name}” is already in this tag set", {"name": clash},
                       code="tag_set_name_taken")
    if category_id is not None:
        _category(s, ts.id, category_id)
    if count is not None and int(count) < 0:
        raise Invalid("a count cannot be negative", code="tag_set_bad_count")
    if position is None:
        mx = s.execute(select(func.max(TagSetEntry.position))
                       .where(TagSetEntry.tag_set_id == ts.id)).scalar()
        position = int(mx or 0) + 1
    row = TagSetEntry(tag_set_id=ts.id, category_id=category_id, name=cname,
                      description=description or "",
                      count=count, position=position,
                      comment=(comment or "").strip())
    for kind in RECORD_FIELDS:
        _apply_record(row, kind, _self_parent(
            clean_record(kind, (records or {}).get(kind)), cname, al))
    if entry_id is not None:
        row.id = entry_id
    s.add(row)
    s.flush()
    _set_aliases(s, row, al)
    _set_implies(s, row, im)
    _set_meta_names(s, row, _clean_names(meta, "meta"), fresh=True)
    s.flush()
    return row


def edit_entry(ctx: Ctx, set_id: int, entry_id: int, *,
               name: Optional[str] = None, description: Optional[str] = None,
               count: Any = _UNSET, category_id: Any = _UNSET,
               aliases: Optional[Iterable[str]] = None,
               implies: Optional[Iterable[str]] = None,
               meta: Optional[Iterable[str]] = None,
               comment: Optional[str] = None,
               records: Optional[dict] = None) -> TagSetEntry:
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    row = _entry(s, set_id, entry_id)
    before = entry_snapshot(s, row)
    data: dict[str, Any] = {"tag_set_id": ts.id, "key": ts.key, "entry_id": row.id}
    new_aliases = (_clean_names(aliases, "aliases") if aliases is not None
                   else before["aliases"])
    if name is not None:
        cname = _clean_names([name], "name")[0]
        if cname != row.name:
            data["old_name"], data["name"] = row.name, cname
    cname = data.get("name", row.name)
    if cname.lower() in {a.lower() for a in new_aliases}:
        raise Invalid("an entry cannot be its own alias", code="tag_set_bad_name")
    check = [cname.lower(), *[a.lower() for a in new_aliases]]
    clash = _taken(s, set_id, check, ignore_entry=row.id)
    if clash is not None:
        raise Conflict("“{name}” is already in this tag set", {"name": clash},
                       code="tag_set_name_taken")
    if description is not None and description != (row.description or ""):
        data["old_description"], data["description"] = row.description or "", description
    if count is not _UNSET and count != row.count:
        if count is not None and int(count) < 0:
            raise Invalid("a count cannot be negative", code="tag_set_bad_count")
        data["old_count"], data["count"] = row.count, count
    if category_id is not _UNSET and category_id != row.category_id:
        if category_id is not None:
            _category(s, set_id, category_id)
        data["old_category_id"], data["category_id"] = row.category_id, category_id
    if aliases is not None and new_aliases != before["aliases"]:
        data["old_aliases"], data["aliases"] = before["aliases"], new_aliases
    was_implies = before.get("implies", [])
    new_implies = (_drop_self(_clean_names(implies, "implies"), cname, new_aliases)
                   if implies is not None else was_implies)
    if implies is not None and new_implies != was_implies:
        data["old_implies"], data["implies"] = was_implies, new_implies
    was_meta = before.get("meta", [])
    if meta is not None:
        new_meta = _clean_names(meta, "meta")
        if new_meta != was_meta:
            data["old_meta"], data["meta"] = was_meta, new_meta
    if comment is not None and comment.strip() != (row.comment or ""):
        data["old_comment"], data["comment"] = row.comment or "", comment.strip()
    # THE RECORDS TRAVEL ONE BY ONE, and only the ones this edit names: a
    # dialog that sends `records` sends all three (an absent key is "no such
    # record"), while a script editing a count sends none and touches none.
    for kind in RECORD_FIELDS:
        if records is None or kind not in records:
            continue
        was = record_of(row, kind)
        now = _self_parent(clean_record(kind, records[kind]), cname,
                           new_aliases)
        if now != was:
            data[f"old_{kind}"], data[kind] = was, now
    if len(data) == 3:
        return row
    apply_entry_fields(s, row, data)
    ctx.log(action=actions.EDIT_TAG_SET_ENTRY, entity_type="tag_set",
            entity_id=ts.id,
            summary="Edited {entry} in tag set {name}",
            summary_vars={"entry": row.name, "name": ts.name}, data=data)
    return row


def apply_entry_fields(s: Session, row: TagSetEntry, fields: dict) -> None:
    """The NEW half of an edit payload onto the row — what the edit does and
    what its redo does; the revert hands in the `old_` half under the plain
    names."""
    if "name" in fields:
        # `lname` follows by itself — it is a GENERATED column, and a write
        # here was ignored by SQLAlchemy rather than applied.
        row.name = fields["name"]
    if "description" in fields:
        row.description = fields["description"] or ""
    if "count" in fields:
        row.count = fields["count"]
    if "category_id" in fields:
        row.category_id = fields["category_id"]
    if "aliases" in fields:
        _set_aliases(s, row, list(fields["aliases"] or []))
    if "implies" in fields:
        _set_implies(s, row, list(fields["implies"] or []))
    if "meta" in fields:
        _set_meta_names(s, row, list(fields["meta"] or []))
    if "comment" in fields:
        row.comment = fields["comment"] or ""
    for kind in RECORD_FIELDS:
        if kind in fields:
            _apply_record(row, kind, fields[kind])
    s.flush()


def entries_by_ids(s: Session, set_id: int, ids: Sequence[int]
                   ) -> list[TagSetEntry]:
    """The set's entries with these ids, in the order they were given.

    Scoped to the SET: an id from another set is silently absent rather than
    acted on, so a stale selection cannot reach across.
    """
    if not ids:
        return []
    rows: dict[int, TagSetEntry] = {}
    for chunk in chunked(list(dict.fromkeys(ids))):
        for r in s.execute(select(TagSetEntry).where(
                TagSetEntry.tag_set_id == set_id, NOT_ALIAS,
                TagSetEntry.id.in_(chunk))).scalars():
            rows[r.id] = r
    return [rows[i] for i in dict.fromkeys(ids) if i in rows]


def delete_entry(ctx: Ctx, set_id: int, entry_id: int) -> None:
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    row = _entry(s, set_id, entry_id)
    snap = entry_snapshot(s, row)
    name = row.name
    s.delete(row)
    s.flush()
    ctx.log(action=actions.DELETE_TAG_SET_ENTRY, entity_type="tag_set",
            entity_id=ts.id,
            summary="Removed {entry} from tag set {name}",
            summary_vars={"entry": name, "name": ts.name},
            data={"tag_set_id": ts.id, "key": ts.key, **snap})


def restore_entry(s: Session, set_id: int, snap: dict) -> bool:
    """The revert's half of `delete_entry` (and of a create's redo)."""
    ts = s.get(TagSet, set_id)
    if ts is None or s.get(TagSetEntry, snap.get("entry_id")) is not None:
        return False
    if snap.get("alias_of"):
        # A row that spells another name: put the spelling back on the row
        # it pointed at, by name. Gone with its target, and nothing to put
        # back — the target's own restore brings its spellings with it.
        target = s.execute(select(TagSetEntry.id).where(
            TagSetEntry.tag_set_id == ts.id,
            TagSetEntry.lname == str(snap["alias_of"]).lower(),
            NOT_ALIAS)).scalar()
        if target is None or _taken(s, ts.id, [str(snap["name"]).lower()]):
            return False
        s.execute(TagSetEntry.__table__.insert(), [
            {"id": snap.get("entry_id"), "tag_set_id": ts.id, "kind": "set",
             "alias_of_id": int(target), "comment": "", "description": "",
             "name": snap["name"]}])
        s.flush()
        return True
    cat = snap.get("category_id")
    if cat is not None and s.get(TagSetCategory, cat) is None:
        cat = None
    try:
        _make_entry(s, ts, name=snap["name"], description=snap.get("description") or "",
                    count=snap.get("count"), category_id=cat,
                    aliases=snap.get("aliases") or [],
                    implies=snap.get("implies") or [],
                    meta=snap.get("meta") or [],
                    comment=snap.get("comment") or "",
                    records={k: snap.get(k) for k in RECORD_FIELDS
                             if snap.get(k) is not None},
                    entry_id=snap.get("entry_id"), position=snap.get("position"))
    except (Conflict, Invalid):
        return False
    return True


# ---- bulk -----------------------------------------------------------------------

def _ensure_trail(s: Session, ts: TagSet, trail: list[str],
                  trails: dict[tuple[str, ...], int],
                  made: list[int],
                  last: Optional[dict[Optional[int], int]] = None
                  ) -> Optional[int]:
    """The category at ``trail``, created along the way when missing.

    The trail is the LIST of names down to the category, never a joined
    path: a name may hold a `/`, so there is no string to split.

    ``last`` is where each parent's highest child position is remembered
    across calls, and an import that makes seventeen thousand categories is
    why it exists: asked of the database it is one `MAX(position)` per
    category made, and the answer is one this walk has just decided itself.
    Its absence means "ask every time", which is right for a caller making
    one.
    """
    key = tuple(trail)
    if not key:
        return None
    if key in trails:
        return trails[key]
    parent: Optional[int] = None
    sofar: tuple[str, ...] = ()
    for part in trail:
        sofar = (*sofar, part)
        if sofar in trails:
            parent = trails[sofar]
            continue
        if last is not None and parent in last:
            pos = last[parent]
        else:
            pos = int(s.execute(select(func.max(TagSetCategory.position)).where(
                TagSetCategory.tag_set_id == ts.id,
                TagSetCategory.parent_id.is_(None) if parent is None
                else TagSetCategory.parent_id == parent)).scalar() or 0)
        pos += 1
        if last is not None:
            last[parent] = pos
        row = TagSetCategory(tag_set_id=ts.id, parent_id=parent, name=part,
                             position=pos)
        s.add(row)
        s.flush()
        trails[sofar] = row.id
        made.append(row.id)
        parent = row.id
    return parent


def bulk_entries(ctx: Ctx, set_id: int, rows: list[dict], *,
                 existing: str = "keep", log: bool = True,
                 made_categories: Optional[list[int]] = None) -> dict:
    """Many entries at once — the CSV import's target and what
    `import_document` calls. Each row: ``name`` plus optional
    ``description``, ``count``, ``category`` (the trail of names, created when
    missing), ``aliases``, ``implies``, ``meta`` (the labels, minted into the
    set's own meta tag set the way a trail's levels are), ``comment`` and the three records
    (``subject``/``place``/``event``, each an object or None). ``existing`` is what happens to an
    entry the set already has: ``keep`` (the row adds only what is empty),
    ``update`` (the row's non-empty fields win), ``replace`` (the row's
    fields win, empties included; aliases and implications are replaced).

    Returns ``{created, updated, errors}``; one `import_tag_set` event, with
    an `undo` block under `UNDO_ENTRIES_MAX` changed entries.
    ``made_categories`` are categories the CALLER made for this import (a
    file's own tree, written before its entries) — they ride the same undo
    block, so reverting the import leaves the set as it was."""
    s = ctx.session
    ts = by_id(s, set_id)
    _refuse_builtin(ts)
    if existing not in ("keep", "update", "replace"):
        raise Invalid("existing must be keep, update or replace",
                      code="tag_set_bad_existing")
    trails: dict[tuple[str, ...], int] = {
        tuple(t): cid for cid, t in category_trails(s, ts.id).items()}
    last_pos: dict[Optional[int], int] = {}
    made_cats: list[int] = list(made_categories or [])
    created: list[int] = []
    replaced: list[dict] = []
    errors: list[dict] = []
    have = {ln: eid for ln, eid in s.execute(
        select(TagSetEntry.lname, TagSetEntry.id)
        .where(TagSetEntry.tag_set_id == ts.id, NOT_ALIAS)).all()}
    alias_owner = {ln: eid for ln, eid in s.execute(
        select(TagSetEntry.lname, TagSetEntry.alias_of_id)
        .where(TagSetEntry.tag_set_id == ts.id,
               TagSetEntry.alias_of_id.is_not(None))).all()}
    pos = int(s.execute(select(func.max(TagSetEntry.position))
                        .where(TagSetEntry.tag_set_id == ts.id)).scalar() or 0)

    # NEW ROWS GO IN BY THE CHUNK. A flush per entry is an INSERT round trip
    # and a pass of the session's own machinery for one row, and a template
    # is a hundred thousand of them; held back and added together, a chunk
    # is ONE insert for the entries, one for all their spellings, one for
    # all their implications and one for all their labels.
    #
    # `have` and `alias_owner` still learn each name the moment it is taken,
    # since the rows after it dedup against them — they learn it as PENDING,
    # the id nothing has yet, and anything that needs a real id drains
    # first. Which is every path but the one this is for: an entry the set
    # already has is an UPDATE, and that reads the row.
    pending: list[tuple[dict, list[str], list[str], list[str]]] = []

    def drain() -> None:
        """The chunk in, as four statements.

        The entries go through a CORE insert with RETURNING rather than the
        ORM's `add_all`: the unit of work writes one statement per object
        because it wants each row's key back one row at a time, where one
        `INSERT … RETURNING id` over five hundred value sets is one
        statement and hands the keys back IN THE ORDER THEY WERE GIVEN.
        The rows land outside the session, which is what an alias row has
        always done here and is why nothing downstream notices: the only
        reader of a new entry is the update path, and that drains first.
        """
        if not pending:
            return
        ids = list(s.execute(insert(TagSetEntry).returning(TagSetEntry.id),
                             [v for v, _, _, _ in pending]).scalars())
        aliases: list[dict] = []
        implies: list[dict] = []
        metas: list[dict] = []
        meta_names: list[str] = []
        for eid, (values, al, im, mt) in zip(ids, pending, strict=True):
            have[values["name"].lower()] = eid
            for a in al:
                alias_owner[a.lower()] = eid
            created.append(eid)
            aliases += [_alias_row(eid, ts.id, values["category_id"], n)
                        for n in al]
            implies += [_implies_row(eid, n) for n in im]
            metas += [_meta_row(eid, n) for n in mt]
            meta_names += mt
        if aliases:
            s.execute(TagSetEntry.__table__.insert(), aliases)
        if implies:
            s.execute(TagSetImplication.__table__.insert(), implies)
        if metas:
            _ensure_meta_rows(s, ts.id, meta_names)
            s.execute(TagMetaTag.__table__.insert(), metas)
        pending.clear()

    for r in rows:
        raw = r.get("name")
        try:
            name = _clean_names([raw], "name")[0]
            al = _clean_names(r.get("aliases") or [], "aliases")
            im = _drop_self(_clean_names(r.get("implies") or [], "implies"),
                            name, al)
            mt = _clean_names(r.get("meta") or [], "meta")
        except Invalid as exc:
            errors.append({"name": str(raw), "error": str(exc)})
            continue
        ln = name.lower()
        count = r.get("count")
        if count is not None and (not isinstance(count, int) or count < 0):
            errors.append({"name": name, "error": "count must be a non-negative integer"})
            continue
        cat_id = _ensure_trail(s, ts, _clean_trail(r.get("category")),
                               trails, made_cats, last_pos)
        eid = have.get(ln)
        if eid is None and ln in alias_owner:
            eid = alias_owner[ln] if existing != "keep" else None
            if eid is None:
                errors.append({"name": name,
                               "error": "already an alias in this set"})
                continue
        if eid == _PENDING:
            # A name this very import made a moment ago and has not written
            # yet — the file says it twice. Everything below this point
            # wants the row, so put the chunk in and ask again.
            drain()
            eid = have.get(ln) or alias_owner.get(ln)
        if eid is None:
            # Aliases claimed by another row are skipped, never stolen.
            al = [a for a in al if a.lower() not in have and a.lower() not in alias_owner
                  and a.lower() != ln]
            pos += 1
            values = {"tag_set_id": ts.id, "category_id": cat_id, "name": name,
                      "description": r.get("description") or "",
                      "count": count, "position": pos,
                      "comment": (r.get("comment") or "").strip()}
            for kind in RECORD_FIELDS:
                values.update(_record_values(kind, _self_parent(
                    clean_record(kind, r.get(kind)), name, al)))
            pending.append((values, al, im, mt))
            have[ln] = _PENDING
            for a in al:
                alias_owner[a.lower()] = _PENDING
            if len(pending) >= _INSERT_CHUNK:
                drain()
            continue
        drain()
        row = s.get(TagSetEntry, eid)
        before = entry_snapshot(s, row)
        changes: dict[str, Any] = {}
        desc = r.get("description")
        if desc is not None and _takes(existing, desc, row.description):
            changes["description"] = desc or ""
        if "count" in r and _takes(existing, count, row.count):
            changes["count"] = count
        if cat_id is not None and _takes(existing, cat_id, row.category_id):
            changes["category_id"] = cat_id
        if al:
            new_al = [a for a in al if a.lower() != ln
                      and (alias_owner.get(a.lower()) in (None, row.id))
                      and a.lower() not in have]
            merged = new_al if existing == "replace" else list(dict.fromkeys(
                [*before["aliases"], *new_al]))
            if merged != before["aliases"]:
                changes["aliases"] = merged
        if im:
            # The same rule the aliases take: `replace` writes the row's
            # list, anything else UNIONS it with what the set already said,
            # in the order it was already in.
            merged_im = im if existing == "replace" else list(dict.fromkeys(
                [*before.get("implies", []), *im]))
            if merged_im != before.get("implies", []):
                changes["implies"] = merged_im
        if mt:
            merged_mt = mt if existing == "replace" else list(dict.fromkeys(
                [*before.get("meta", []), *mt]))
            if merged_mt != before.get("meta", []):
                changes["meta"] = merged_mt
        comment = r.get("comment")
        if comment is not None and _takes(existing, comment.strip(),
                                          row.comment):
            changes["comment"] = comment.strip()
        # A RECORD IS TAKEN WHOLE OR NOT AT ALL. Merging one field of a
        # place into another file's place would make an address and a
        # coordinate that were never written down together; `keep` leaves an
        # existing record alone, `update` and `replace` take the file's.
        for kind in RECORD_FIELDS:
            if kind not in r:
                continue
            rec = _self_parent(clean_record(kind, r.get(kind)), name, al)
            if _takes(existing, rec, record_of(row, kind)) \
                    and rec != record_of(row, kind):
                changes[kind] = rec
        if not changes:
            continue
        apply_entry_fields(s, row, changes)
        for a in changes.get("aliases", []):
            alias_owner[a.lower()] = row.id
        # What the row LOOKED like, for `revert_import`. `implies` rides
        # only where the change touched it — and then it must, even when it
        # was empty, or a revert would leave the implications behind.
        snap = {k: before[k] for k in ("entry_id", "name", "description",
                                       "count", "category_id", "aliases")}
        if "implies" in changes:
            snap["implies"] = before.get("implies", [])
        if "meta" in changes:
            snap["meta"] = before.get("meta", [])
        # …and the same rule for the comment and the records: each rides only
        # where the change touched it, and then it must, even when it was
        # absent, or a revert would leave the new one standing.
        if "comment" in changes:
            snap["comment"] = before.get("comment", "")
        for kind in RECORD_FIELDS:
            if kind in changes:
                snap[kind] = before.get(kind)
        replaced.append(snap)
    drain()
    s.flush()
    result = {"created": len(created), "updated": len(replaced), "errors": errors}
    if log:
        data: dict[str, Any] = {"tag_set_id": ts.id, "key": ts.key, **{
            k: result[k] for k in ("created", "updated")}}
        if len(created) + len(replaced) <= UNDO_ENTRIES_MAX:
            data["undo"] = {"created_entry_ids": created,
                            "created_category_ids": made_cats,
                            "replaced": replaced}
        ctx.log(action=actions.IMPORT_TAG_SET, entity_type="tag_set", entity_id=ts.id,
                summary="Imported {count} entries into tag set {name}",
                summary_vars={"count": len(created) + len(replaced), "name": ts.name},
                data=data)
    return result


def _takes(existing: str, from_file, in_set) -> bool:
    if existing == "replace":
        return True
    if from_file in (None, ""):
        return False
    return existing == "update" or in_set in (None, "")


def revert_import(s: Session, undo: dict) -> bool:
    """The `undo` block of an `import_tag_set` event, applied backwards."""
    ok = False
    for eid in undo.get("created_entry_ids") or []:
        row = s.get(TagSetEntry, eid)
        if row is not None:
            s.delete(row)
            ok = True
    s.flush()
    for snap in undo.get("replaced") or []:
        row = s.get(TagSetEntry, snap.get("entry_id"))
        if row is None:
            continue
        apply_entry_fields(s, row, {k: snap[k] for k in
                                    ("name", "description", "count",
                                     "category_id", "aliases", "implies",
                                     "comment", *RECORD_FIELDS) if k in snap})
        ok = True
    for cid in reversed(undo.get("created_category_ids") or []):
        row = s.get(TagSetCategory, cid)
        if row is None:
            continue
        used = s.execute(select(TagSetEntry.id).where(
            TagSetEntry.category_id == cid).limit(1)).first()
        kids = s.execute(select(TagSetCategory.id).where(
            TagSetCategory.parent_id == cid).limit(1)).first()
        if used is None and kids is None:
            s.delete(row)
            ok = True
    s.flush()
    return ok


def import_document(ctx: Ctx, obj: Any, *, mode: str = "create",
                    target_id: Optional[int] = None,
                    key: Optional[str] = None) -> tuple[TagSet, dict]:
    """A tag-set FILE into the library. ``create`` makes a new set from it
    (its key made unique); ``merge`` adds what the target lacks; ``replace``
    empties the target and writes the file (not revertible — the emptied rows
    are gone, so no `undo` block).

    ``key`` is the key to file it under before `_unique_key` makes it free —
    what `create_from_template` passes, since a format-2 file carries none of
    its own and a document falls back to a slug of its NAME."""
    s = ctx.session
    try:
        doc = fmt.parse(obj, key=key)
    except fmt.FormatError as exc:
        raise Invalid(str(exc), code="tag_set_bad_file") from None
    if mode not in ("create", "merge", "replace"):
        raise Invalid("mode must be create, merge or replace", code="tag_set_bad_mode")
    rows = [{"name": e.name, "description": e.description, "count": e.count,
             "category": e.category, "aliases": e.aliases,
             "implies": e.implies, "meta": e.meta, "comment": e.comment,
             **{k: (None if getattr(e, k) is None
                    else asdict(getattr(e, k))) for k in RECORD_FIELDS}}
            for e in doc.entries]
    if mode == "create":
        ts = create_tag_set(ctx, name=doc.name, key=_unique_key(s, doc.key),
                            description=doc.description, version=doc.version)
        made: list[int] = []
        _write_categories(s, ts, doc, {}, made)
        _write_meta_tags(s, ts, doc)
        result = bulk_entries(ctx, ts.id, rows, existing="keep",
                              made_categories=made)
        return ts, result
    if target_id is None:
        raise Invalid("merge and replace need a target set", code="tag_set_no_target")
    ts = by_id(s, target_id)
    _refuse_builtin(ts)
    if mode == "replace":
        _clear_rows(s, ts.id)
        _write_doc(s, ts, doc)
        n = len(doc.entries)
        ctx.log(action=actions.IMPORT_TAG_SET, entity_type="tag_set", entity_id=ts.id,
                summary="Imported {count} entries into tag set {name}",
                summary_vars={"count": n, "name": ts.name},
                data={"tag_set_id": ts.id, "key": ts.key, "created": n,
                      "updated": 0, "replaced_all": True})
        return ts, {"created": n, "updated": 0, "errors": []}
    # merge: the file's category rows are created where they are new (with
    # what they say); bulk_entries creates the rest along the entries'
    # trails. ONE writer for both, since a flat list of paths is exactly
    # what the create path walks too.
    have = {tuple(t): cid for cid, t in category_trails(s, ts.id).items()}
    made: list[int] = []
    _write_categories(s, ts, doc, have, made)
    _write_meta_tags(s, ts, doc)
    result = bulk_entries(ctx, ts.id, rows, existing="keep",
                          made_categories=made)
    return ts, result


def to_json(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
