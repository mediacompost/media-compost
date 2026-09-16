"""The tag-set FILE — what an export writes and an import reads.

Pure: json and this module's own validation, nothing from the database. The
document is one object::

    {"format": "media-compost-tag-set", "format_version": 2,
     "name": "Danbooru", "description": "…",
     "categories": [{"path": ["nsfw"], "hidden": true}],
     "entries": [{"name": "1girl", "description": "…", "count": 12345,
                  "category": ["people", "count"],
                  "aliases": ["1female"], "implies": ["solo"]}]}

**An entry names its category as the LIST OF NAMES down to it**, not as a
slash-joined path. That is the whole of why a category name may contain a
``/`` (owner decision, 2026-09): a path string has to reserve one character
and escape it everywhere it is split, and the reserved character was one the
tag sets want — ``and/or``, ``either/or``, ``s/m``. A list reserves
nothing and cannot be mis-split. The UI draws the list with chevrons between
the names, which is what the slash was standing in for anyway.

**THE CATEGORY TREE IS NOT WRITTEN DOWN. IT IS WHAT THE ENTRIES SAY IT IS.**
(Owner decision, 2026-09, replacing a nested `categories` block that spelled
every branch a second time.) Reading the entries in order and creating each
trail's missing levels builds the whole tree, parents and order together —
:func:`category_order` is that one definition, and both the import and the
export use it.

``categories`` survives as a FLAT list of what the entries cannot say:

  * a category's ``icon``, ``hidden``, ``aliases`` and ``implications``;
  * a category that holds no entries at all, which would otherwise not
    exist (a row that is only a ``path`` means exactly that);
  * an ORDER the entries do not imply — a set whose categories somebody
    dragged into a different order writes every one of them, since a
    partial order is not one.

Each row is ``{"path": [...names...], …settings}``, and the whole key is
omitted when the entries already say everything. That is the usual case: the
shipped templates write no ``categories`` at all, because their entries are
emitted in the outline's own order.

`implies` names the tags an entry ENTAILS — the door mints and links them
when the entry's name is first assigned (`tagcatalog.get_or_create`). Like
an entry's `icon` and a category's `hidden` it is written ONLY when there is
one. (It was read and dropped for a round — owner decision 2026-09, reversed
the same month. An `exclusive` key on a category, the "one of these per
picture" hint, is still read and dropped.)

**ALIASES AND IMPLICATIONS CAN BE TURNED OFF**, for the whole set (the
top-level ``aliases`` / ``implications``, written only when false) or per
category (the same two keys on a row, three-state: absent inherits from the
parent, and the set's flag is the root). A set whose aliases are off offers
none of them in the autocomplete; one whose implications are off mints
nothing when a name is assigned. Both are properties of the TAG SET —
whether its alias spellings and its entailments are advice worth taking —
which is why they travel in the file, where `enabled` does not.

What is deliberately NOT in the file: `builtin`, `library`, `enabled`,
`position`, any id — and `key` and `version`. Those two read as facts about
the set and are facts about one INSTALLATION of it: the key is what this
library files the set under (a second copy of one file is `booru-2`), the
version a counter this library bumps as somebody edits. A template's key is
its FILENAME, which is where a reader looks anyway.

Names are held to the app's own tag-name rule (`tagname.normalize`) and
REFUSED when malformed rather than fixed, for the reason `tagcatalog.
check_name` gives: a name silently stored under another spelling is one the
importer cannot find again.

A file carrying a HIGHER `format_version` than this build writes is refused
by number, naming both, the way a library from the future is: the newer shape
is exactly what the older reader cannot be trusted to understand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import tagname

FORMAT = "media-compost-tag-set"
FORMAT_VERSION = 1

_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class FormatError(ValueError):
    """The document is not a tag set, and the message says where."""


@dataclass
class CategoryDoc:
    """What the file says about ONE category, beyond that it exists.

    The `path` is the trail of names down to it — the same shape an entry's
    `category` has, and the reason neither needs a separator. Every other
    field is optional, and a row carrying only a path still says something:
    that the category exists (for one no entry names) and where it sits.
    """
    path: list[str] = field(default_factory=list)
    #: A Material Symbols name for the tree row; "" is the folder.
    icon: str = ""
    #: Kept out of the autocomplete, with everything under it.
    hidden: bool = False
    #: Whether this branch's alias spellings are offered, and whether its
    #: entries' `implies` are minted. THREE-STATE: None inherits from the
    #: parent category, and the set's own flag is the root of that walk.
    aliases: Optional[bool] = None
    implications: Optional[bool] = None
    #: Where it sits among its SIBLINGS, when that is not where reading the
    #: entries would put it. Written only for a branch somebody reordered by
    #: hand, and then for all of that parent's children at once — half an
    #: order is not one. None means "wherever the entries say".
    position: Optional[int] = None


@dataclass
class SubjectDoc:
    """This name is somebody — a person, a character, a band, a cat.

    `name` is the DISPLAY name where it differs from the tag ("Hatsune
    Miku" for `hatsune_miku`); "" means the tag's own. `since` is when the
    subject came to be, as the library's partial date: the sortable number
    `YYYYMMDD` with ZEROS for what is not known (`19750000` is "1975").
    """
    name: str = ""
    since: Optional[int] = None


@dataclass
class PlaceDoc:
    """This name is a place: what it is CALLED — "Shibuya, Tokyo", "Bob's
    house", one line either way — optionally where on earth, optionally the
    place it is IN, named by that place's TAG since a set refers to
    everything by name.

    `name`, like a subject's and an event's. The library stores that line in
    `Location.address` and keeps the storage word there, but every surface a
    person meets calls it the place's name: an address is welcome in it and
    a field saying "Address" told people a name was not.
    """
    name: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    parent: str = ""


@dataclass
class EventDoc:
    """This name is an event: a display name, a span as two partial dates,
    and the event it is part of, by tag name."""
    name: str = ""
    start: Optional[int] = None
    end: Optional[int] = None
    parent: str = ""


@dataclass
class MetaDoc:
    """A META TAG the set knows — a label about a NAME, not about a picture.

    Only what an entry cannot say: the names themselves arrive on the
    entries' `meta` lists and are made on import, exactly as a category
    trail is. A row here exists to carry a comment or a description for
    one, which is why an entry-only meta tag writes no row at all."""

    name: str
    comment: str = ""
    description: str = ""


@dataclass
class EntryDoc:
    name: str
    description: str = ""
    count: Optional[int] = None
    #: The one-liner the TAG should carry. `description` is what the set
    #: says about the name and stays in the set; this is advice about the
    #: library's own tag, applied at the door and by the sync verb.
    comment: str = ""
    #: What KIND of thing this name is, where the tag set knows. Absent
    #: (None) means it says nothing — which is not the same as an empty
    #: record: a person with only a name recorded is still a person.
    subject: Optional[SubjectDoc] = None
    place: Optional[PlaceDoc] = None
    event: Optional[EventDoc] = None
    #: The names down to the category, outermost first. Empty = uncategorized.
    #: A trail the `categories` block does not list is MADE on import.
    category: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    #: The tags this one entails, by NAME. Optional in the file, written
    #: only when there is one.
    implies: list[str] = field(default_factory=list)
    #: The META TAGS the set says this name carries — "character", "noflip",
    #: "from a booru". Their own namespace, never tags: they label the NAME
    #: and never reach a picture. Applied at the door, like `implies`.
    meta: list[str] = field(default_factory=list)


@dataclass
class TagSetDoc:
    key: str
    name: str
    description: str = ""
    version: int = 0
    #: The set-wide answer the categories' three-state fields inherit from.
    aliases: bool = True
    implications: bool = True
    #: Only the categories the file has something to say about — see the
    #: module docstring. The tree itself comes from :func:`category_order`.
    categories: list[CategoryDoc] = field(default_factory=list)
    #: Only the meta tags the file has something to SAY about — the rest
    #: arrive on the entries, like a category trail.
    meta_tags: list[MetaDoc] = field(default_factory=list)
    entries: list[EntryDoc] = field(default_factory=list)


def slug_key(name: str) -> str:
    """A key derived from a display name, for a set that names none."""
    k = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return (k or "set")[:64]


def check_key(key: str) -> str:
    if not _KEY.match(key):
        raise FormatError(
            f"key {key!r}: lowercase letters, digits, '-' and '_', starting "
            "with a letter or digit, at most 64 characters")
    return key


def check_tag_name(name: Any, where: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise FormatError(f"{where}: a tag name is required")
    n = name.strip()
    if " " in n or not tagname.is_normalized(n):
        raise FormatError(
            f"{where}: {name!r} is not a tag name — try "
            f"{tagname.normalize(n)!r}")
    return n


def category_order(categories: list[CategoryDoc],
                   entries: list[EntryDoc]) -> list[list[str]]:
    """EVERY category the document implies, in the order it is created.

    The one definition of what the tree is: read the `categories` rows, then
    the entries, and for each trail create the levels not seen yet. Both the
    import (which makes the rows) and the export (which decides whether it
    has to write any) go through this, so "what the file says" and "what the
    file would produce" cannot drift.
    """
    seen: set[tuple[str, ...]] = set()
    out: list[list[str]] = []

    def add(trail: list[str]) -> None:
        for i in range(1, len(trail) + 1):
            key = tuple(trail[:i])
            if key not in seen:
                seen.add(key)
                out.append(list(key))

    # THE ENTRIES GO FIRST, and that is the whole reason a settings row is
    # free: a row on a category the entries already name must not drag it to
    # the front of its siblings, or hiding one branch would silently reorder
    # the tree. What a row can still do is bring in a category no entry
    # names — appended here, placed by its `position` if it needs placing.
    for e in entries:
        add(e.category)
    for c in categories:
        add(c.path)
    return out


def _tri(raw: Any, where: str) -> Optional[bool]:
    """A three-state flag: absent (or null) inherits, true/false decide."""
    if raw is None:
        return None
    if not isinstance(raw, bool):
        raise FormatError(f"{where}: must be true, false or absent")
    return raw


def _position(raw: Any, where: str) -> Optional[int]:
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise FormatError(f"{where}: must be a non-negative integer")
    return raw


def _parse_categories(raw: Any, where: str) -> list[CategoryDoc]:
    """The flat settings rows: what the entries' own trails cannot say.

    A category no entry names, an icon, the two advice switches, and a
    `position` where the entry order does not already imply it.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FormatError(f"{where}: categories must be a list")
    out: list[CategoryDoc] = []
    seen: set[tuple[str, ...]] = set()

    def one(c: Any, here: str, path: list[str]) -> None:
        if tuple(path) in seen:
            raise FormatError(f"{here}: {path!r} is named twice")
        seen.add(tuple(path))
        out.append(CategoryDoc(
            path=path,
            icon=str(c.get("icon") or "").strip(),
            hidden=bool(c.get("hidden")),
            aliases=_tri(c.get("aliases"), f"{here}.aliases"),
            implications=_tri(c.get("implications"), f"{here}.implications"),
            position=_position(c.get("position"), f"{here}.position"),
        ))

    for i, c in enumerate(raw):
        here = f"{where}[{i}]"
        if not isinstance(c, dict):
            raise FormatError(f"{here}: a category must be an object")
        path = c.get("path")
        if not isinstance(path, list) or not path:
            raise FormatError(
                f"{here}: a category is named by its path — the list of names "
                "down to it")
        names: list[str] = []
        for j, part in enumerate(path):
            if not isinstance(part, str) or not part.strip():
                raise FormatError(f"{here}.path[{j}]: a category needs a name")
            names.append(part.strip())
        if len(names) > 32:
            raise FormatError(f"{here}: categories nest too deeply")
        one(c, here, names)
    return out


def _names(raw: Any, where: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FormatError(f"{where} must be a list of names")
    out: list[str] = []
    for i, n in enumerate(raw):
        out.append(check_tag_name(n, f"{where}[{i}]"))
    return out


def _date(raw: Any, where: str) -> Optional[int]:
    """A partial date — `YYYYMMDD` with zeros, the library's own encoding
    (`partialdate.py`), so nothing has to be parsed or re-formatted on the
    way in. Written as a NUMBER because that is what it is: sortable, and a
    range query over it is an integer comparison."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise FormatError(
            f"{where}: a date is the number YYYYMMDD, with zeros for what is "
            "not known (19750000 is 1975)")
    if not (0 <= raw <= 99991231):
        raise FormatError(f"{where}: {raw} is not a date")
    return raw or None


def _coord(raw: Any, where: str, limit: float) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise FormatError(f"{where}: must be a number")
    if not (-limit <= float(raw) <= limit):
        raise FormatError(f"{where}: must be between -{limit:g} and {limit:g}")
    return float(raw)


def _text(raw: Any, where: str) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise FormatError(f"{where}: must be text")
    return raw.strip()


def _record(raw: Any, where: str, kind: str):
    """One of the three records, or None where the entry says nothing.

    An EMPTY object is a record — `"subject": {}` says "this name is
    somebody" and nothing more, which is a thing a tag set very often
    knows and the only thing it knows. That is why the three are optional
    objects rather than fields on the entry: absent and empty have to mean
    different things.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise FormatError(f"{where}: must be an object")
    if kind == "subject":
        return SubjectDoc(name=_text(raw.get("name"), f"{where}.name"),
                          since=_date(raw.get("since"), f"{where}.since"))
    if kind == "place":
        parent = raw.get("parent")
        return PlaceDoc(
            name=_text(raw.get("name"), f"{where}.name"),
            lat=_coord(raw.get("lat"), f"{where}.lat", 90.0),
            lon=_coord(raw.get("lon"), f"{where}.lon", 180.0),
            parent=(check_tag_name(parent, f"{where}.parent")
                    if parent else ""))
    parent = raw.get("parent")
    return EventDoc(
        name=_text(raw.get("name"), f"{where}.name"),
        start=_date(raw.get("start"), f"{where}.start"),
        end=_date(raw.get("end"), f"{where}.end"),
        parent=check_tag_name(parent, f"{where}.parent") if parent else "")


def _category_trail(raw: Any, where: str) -> list[str]:
    """An entry's category: the LIST of names down to it.

    Never a slash path — which is what lets a category name hold a `/`
    (`and/or`, `Ranma 1/2`, every `Fate/…` title).
    """
    if raw is None or raw == "" or raw == []:
        return []
    if isinstance(raw, str):
        raise FormatError(
            f"{where}: a category is the list of names down to it, not a "
            f"path — try {[p for p in raw.split('/') if p.strip()]!r}")
    if isinstance(raw, list):
        parts = []
        for i, p in enumerate(raw):
            if not isinstance(p, str) or not p.strip():
                raise FormatError(f"{where}[{i}]: a category needs a name")
            parts.append(p.strip())
    else:
        raise FormatError(f"{where}: a category is a list of names")
    if len(parts) > 32:
        raise FormatError(f"{where}: categories nest too deeply")
    return parts


def _parse_meta_tags(raw: Any, where: str) -> list[MetaDoc]:
    """The set's meta tags — the ones it has a comment or a description for.

    A row is `{"name": …, "comment": …, "description": …}`. The names alone
    live on the entries, so a row saying nothing but a name is kept anyway
    (it is how a set declares a label nothing carries yet), and a duplicate
    is refused rather than merged."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FormatError(f"{where}: meta tags are a list")
    out: list[MetaDoc] = []
    seen: set[str] = set()
    for i, m in enumerate(raw):
        here = f"{where}[{i}]"
        if not isinstance(m, dict):
            raise FormatError(f"{here}: a meta tag is an object")
        n = check_tag_name(m.get("name"), here)
        if n.lower() in seen:
            raise FormatError(f"{here}: {n!r} is listed twice")
        seen.add(n.lower())
        out.append(MetaDoc(name=n, comment=_text(m.get("comment"),
                                                 f"{here}.comment"),
                           description=_text(m.get("description"),
                                             f"{here}.description")))
    return out


def parse(obj: Any, *, key: Optional[str] = None) -> TagSetDoc:
    """A validated document. ``key`` overrides the file's (an import that
    names its target), and a file naming none gets one from its name."""
    if not isinstance(obj, dict):
        raise FormatError("a tag set file is a JSON object")
    fmt = obj.get("format")
    if fmt is not None and fmt != FORMAT:
        raise FormatError(f"not a tag set file (format {fmt!r})")
    fv = obj.get("format_version", FORMAT_VERSION)
    if not isinstance(fv, int) or fv < 1:
        raise FormatError("format_version must be a positive integer")
    if fv > FORMAT_VERSION:
        raise FormatError(
            f"this file is format version {fv}; this build reads up to "
            f"{FORMAT_VERSION}")
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        raise FormatError("a tag set needs a name")
    name = name.strip()
    # The key names the SET, so an explicit one wins; otherwise it is the
    # name's slug (`load_path` passes the filename's stem).
    k = key if key is not None else obj.get("key")
    k = check_key(str(k).strip()) if k else slug_key(name)
    description = obj.get("description") or ""
    if not isinstance(description, str):
        raise FormatError("description must be text")
    version = obj.get("version", 0)
    if not isinstance(version, int) or version < 0:
        raise FormatError("version must be a non-negative integer")
    for key_ in ("aliases", "implications"):
        if obj.get(key_) is not None and not isinstance(obj.get(key_), bool):
            raise FormatError(f"{key_} must be true or false")
    set_aliases = obj.get("aliases")
    set_implications = obj.get("implications")
    categories = _parse_categories(obj.get("categories"), "categories")
    meta_tags = _parse_meta_tags(obj.get("meta_tags"), "meta_tags")

    raw_entries = obj.get("entries")
    if raw_entries is None:
        raw_entries = []
    if not isinstance(raw_entries, list):
        raise FormatError("entries must be a list")
    entries: list[EntryDoc] = []
    taken: dict[str, str] = {}
    for i, e in enumerate(raw_entries):
        here = f"entries[{i}]"
        if not isinstance(e, dict):
            raise FormatError(f"{here}: an entry must be an object")
        ename = check_tag_name(e.get("name"), here)
        desc = e.get("description") or ""
        if not isinstance(desc, str):
            raise FormatError(f"{here}: description must be text")
        count = e.get("count")
        if count is not None and (not isinstance(count, int) or count < 0):
            raise FormatError(f"{here}: count must be a non-negative integer")
        cat = _category_trail(e.get("category"), f"{here}.category",
                              )
        aliases = _names(e.get("aliases"), f"{here}.aliases")
        implies = _names(e.get("implies"), f"{here}.implies")
        meta = _names(e.get("meta"), f"{here}.meta")
        for n in [ename, *aliases]:
            ln = n.lower()
            if ln in taken:
                raise FormatError(
                    f"{here}: {n!r} is already {taken[ln]} in this set")
            taken[ln] = "an alias" if n != ename else "an entry"
        # An entry never implies ITSELF — its own name or one of its own
        # aliases, both of which assign this very tag. Read as implying
        # nothing rather than refused: the file means the tag it names.
        me = {ename.lower(), *(a.lower() for a in aliases)}
        # A record naming ITSELF as its parent is read as naming none, the
        # rule `implies` keeps one line up: the file means the tag it is on.
        place = _record(e.get("place"), f"{here}.place", "place")
        occasion = _record(e.get("event"), f"{here}.event", "event")
        for rec in (place, occasion):
            if rec is not None and rec.parent.lower() in me:
                rec.parent = ""
        entries.append(EntryDoc(name=ename, description=desc, count=count,
                                comment=_text(e.get("comment"),
                                              f"{here}.comment"),
                                subject=_record(e.get("subject"),
                                                f"{here}.subject", "subject"),
                                place=place, event=occasion,
                                category=cat, aliases=aliases,
                                implies=[n for n in implies
                                         if n.lower() not in me],
                                meta=meta))
    return TagSetDoc(key=k, name=name, description=description,
                     version=version,
                     aliases=True if set_aliases is None else set_aliases,
                     implications=(True if set_implications is None
                                   else set_implications),
                     categories=categories, meta_tags=meta_tags,
                     entries=entries)


def _dump_categories(cats: list[CategoryDoc]) -> list[dict]:
    return [{"path": list(c.path),
             **({"icon": c.icon} if c.icon else {}),
             **({"hidden": True} if c.hidden else {}),
             **({"aliases": c.aliases} if c.aliases is not None else {}),
             **({"implications": c.implications}
                if c.implications is not None else {}),
             **({"position": c.position} if c.position is not None else {}),
             } for c in cats]


def _dump_record(rec) -> dict:
    """A record's own fields, the ones that say something. In the same
    order the dataclass declares them, so a round trip is byte-stable."""
    out: dict[str, Any] = {}
    for key in ("name", "since", "start", "end", "lat", "lon", "parent"):
        val = getattr(rec, key, None)
        if val not in (None, "", 0):
            out[key] = val
    return out


def dump(doc: TagSetDoc) -> dict:
    """The document as JSON-ready data — the keys that say something, in one
    order, so a round trip is byte-stable.

    An empty `categories`, `aliases` or `implies`, an absent count, an
    uncategorized entry and a flag at its default write NO key: on a set of
    any size those defaults are most of the file, and a reader that has to
    treat a missing key and an empty one alike anyway is not helped by
    writing both.
    """
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "name": doc.name,
        **({"description": doc.description} if doc.description else {}),
        **({} if doc.aliases else {"aliases": False}),
        **({} if doc.implications else {"implications": False}),
        **({"categories": _dump_categories(doc.categories)}
           if doc.categories else {}),
        **({"meta_tags": [{"name": m.name,
                           **({"comment": m.comment} if m.comment else {}),
                           **({"description": m.description}
                              if m.description else {})}
                          for m in doc.meta_tags]}
           if doc.meta_tags else {}),
        "entries": [{
            "name": e.name,
            **({"description": e.description} if e.description else {}),
            **({"count": e.count} if e.count is not None else {}),
            **({"category": list(e.category)} if e.category else {}),
            **({"aliases": list(e.aliases)} if e.aliases else {}),
            **({"implies": list(e.implies)} if e.implies else {}),
            **({"meta": list(e.meta)} if e.meta else {}),
            **({"comment": e.comment} if e.comment else {}),
            # A record writes its key even when EMPTY — `{}` is the whole
            # of what a set often knows ("this name is a person"), and a
            # key omitted for being empty would say the opposite.
            **({"subject": _dump_record(e.subject)}
               if e.subject is not None else {}),
            **({"place": _dump_record(e.place)}
               if e.place is not None else {}),
            **({"event": _dump_record(e.event)}
               if e.event is not None else {}),
        } for e in doc.entries],
    }


def load_path(path: Path) -> TagSetDoc:
    """A document read from a file, keyed by its FILENAME.

    The stem is the key a format-2 file does not carry — `booru.json` is the
    `booru` template. A format-1 file naming its own key keeps it, since that
    is what an older export of a renamed set means.
    """
    p = Path(path)
    try:
        obj = json.loads(p.read_text("utf-8"))
    except ValueError as exc:
        raise FormatError(f"{path}: not JSON ({exc})") from None
    if isinstance(obj, dict) and not obj.get("key"):
        stem = slug_key(p.stem)
        return parse(obj, key=stem if _KEY.match(stem) else None)
    return parse(obj)


def dumps(doc: TagSetDoc) -> str:
    return json.dumps(dump(doc), ensure_ascii=False, indent=2) + "\n"
