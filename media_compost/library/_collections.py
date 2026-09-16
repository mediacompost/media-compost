"""The collection protocols the handles expose.

Anything set-shaped is a `MutableSet`, anything ordered a `MutableSequence`,
anything keyed by a genuinely unique name a `Mapping`. Mutating the collection
IS the write — `item.tags.add("portrait")` assigns the tag then and there —
which is what makes the API read like Python rather than like a REST client.

The one thing that is NOT a Mapping is a catalog keyed by a display name.
Two subjects can both be "Alex" and two groups both "2019", so `[...]` on
those would be a landmine; they get `find()` and `one()` instead, and `one()`
raises `AmbiguousName` rather than picking.

An item's tag groups are the stated exception: that catalog opts into name
keys (`by_name=`), and `item.tag_groups["Hers"]` GETS-OR-CREATES — placing a
tag into a named layout is what brings the layout into being, the same way
the app's add flow mints it. The landmine is disarmed the loud way: a name
two groups share raises `AmbiguousName` rather than picking one.
"""

from __future__ import annotations

from collections.abc import (
    Collection, Mapping, MutableSequence, MutableSet,
)
from typing import Any, Callable, Iterator, Optional

from .errors import AmbiguousName, NotFound, UnsupportedOperation


class NameSet(MutableSet):
    """A set of names that writes through on every change.

    `add` takes keyword extras beyond the ABC's single positional — a sign, a
    group, a box — which keeps the one-argument contract intact while making
    the annotated case a single line.
    """

    __slots__ = ("_read", "_add", "_remove", "_what")

    def __init__(self, read: Callable[[], set], add: Callable[..., Any],
                 remove: Callable[[str], Any], what: str = "tag"):
        self._read = read
        self._add = add
        self._remove = remove
        self._what = what

    def __contains__(self, name: object) -> bool:
        return str(name) in self._read()

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._read()))

    def __len__(self) -> int:
        return len(self._read())

    def add(self, name: str, **kw):
        """Returns whatever the write produced, where there is something worth
        having back. `MutableSet.add` is specified to return None, but the
        mixin methods that call it (`|=` and friends) ignore the value, so
        handing one back costs nothing and saves a lookup."""
        return self._add(name, **kw)

    def discard(self, name: str) -> None:
        self._remove(str(name))

    def remove(self, name: str) -> None:
        """Like a set's: raises when it was not there."""
        if str(name) not in self:
            raise NotFound(f"no {self._what} {name!r} here")
        self._remove(str(name))

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "{" + ", ".join(repr(n) for n in self) + "}"


class HandleSet(MutableSet):
    """A set of handles — the groups an item is in, the places on it."""

    __slots__ = ("_read", "_add", "_remove", "_what")

    def __init__(self, read: Callable[[], list], add: Callable[..., Any],
                 remove: Callable[[Any], Any], what: str = "entry"):
        self._read = read
        self._add = add
        self._remove = remove
        self._what = what

    def __contains__(self, value: object) -> bool:
        return value in self._read()

    def __iter__(self) -> Iterator:
        return iter(self._read())

    def __len__(self) -> int:
        return len(self._read())

    def add(self, value, **kw):
        """Returns what the write produced — the Link, the Appearance. See
        `NameSet.add` for why that is safe."""
        return self._add(value, **kw)

    def discard(self, value) -> None:
        self._remove(value)

    def remove(self, value) -> None:
        if value not in self:
            raise NotFound(f"no such {self._what} here")
        self._remove(value)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "{" + ", ".join(repr(v) for v in self) + "}"


class HandleList(MutableSequence):
    """An ordered run of handles — an item's files, a sequence's members."""

    __slots__ = ("_read", "_insert", "_delete", "_reorder")

    def __init__(self, read: Callable[[], list],
                 insert: Optional[Callable[[int, Any], Any]] = None,
                 delete: Optional[Callable[[Any], Any]] = None,
                 reorder: Optional[Callable[[list], Any]] = None):
        self._read = read
        self._insert = insert
        self._delete = delete
        self._reorder = reorder

    def __getitem__(self, index):
        return self._read()[index]

    def __len__(self) -> int:
        return len(self._read())

    def __setitem__(self, index, value):
        raise TypeError("assign through the item's own properties instead")

    def __delitem__(self, index) -> None:
        if self._delete is None:
            raise TypeError("this list cannot be shortened directly")
        for row in ([self._read()[index]] if isinstance(index, int)
                    else self._read()[index]):
            self._delete(row)

    def insert(self, index: int, value) -> None:
        if self._insert is None:
            raise TypeError("this list cannot be inserted into directly")
        self._insert(index, value)

    def reorder(self, values: list) -> None:
        """Put the members in this order."""
        if self._reorder is None:
            raise TypeError("this list is not reorderable")
        self._reorder(list(values))

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return repr(self._read())


class NameMap(Mapping):
    """A catalog keyed by a genuinely unique name — tags, meta tags.

    A FULL Mapping: iterating yields KEYS, `.values()` yields handles,
    `"x" in cat` is membership. A dict-shaped thing that iterated values
    instead would be the single most confusing thing this API could do.

    `cat["nope"]` raises `KeyError`. A read must not write — Python's
    create-on-read container is `defaultdict`, and it is opt-in for exactly
    this reason. Creation is `create()` / `get_or_create()`.
    """

    __slots__ = ("_names", "_lookup", "_what")

    def __init__(self, names: Callable[[], list[str]],
                 lookup: Callable[[str], Any], what: str = "tag"):
        self._names = names
        self._lookup = lookup
        self._what = what

    def __getitem__(self, name: str):
        got = self._lookup(str(name))
        if got is None:
            raise NotFound(f"no {self._what} named {name!r}")
        return got

    def __iter__(self) -> Iterator[str]:
        return iter(self._names())

    def __len__(self) -> int:
        return len(self._names())

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{len(self)} {self._what}s>"


class Catalog(Collection):
    """A catalog whose rows are NOT uniquely named — subjects, places, events.

    Two people really can share a display name, and a place or an unnamed
    cluster has no name at all. `[...]` takes an ID; `find()` searches;
    `one()` raises `AmbiguousName` rather than picking for you.

    A catalog may opt into NAME keys with `by_name=` (a lookup answering the
    handle, None for no match, or raising `AmbiguousName`): then `[...]` with
    a string finds the row — or, where the catalog is creatable, creates it,
    which is what makes `item.tag_groups["Hers"].tags.add(...)` one line.
    `get()` stays a pure read either way.
    """

    __slots__ = ("_all", "_get", "_match", "_what", "_create", "_extra",
                 "_by_name", "_exact")

    def __init__(self, all_rows: Callable[[], list],
                 get: Callable[[int], Any],
                 match: Callable[[str], list], what: str = "row",
                 create: Optional[Callable[..., Any]] = None,
                 extra: Optional[dict] = None,
                 by_name: Optional[Callable[[str], Any]] = None,
                 exact: Optional[Callable[[str], list]] = None):
        self._all = all_rows
        self._get = get
        self._match = match
        self._what = what
        self._create = create
        # Derived one-offs a particular catalog answers (an item's tag groups
        # have a `pending` one). Callables, evaluated on read, because a
        # catalog is a live view and a captured row would go stale.
        self._extra = extra or {}
        self._by_name = by_name
        self._exact = exact

    def create(self, *args, **kw):
        """Add a row, where this catalog is one you can add to."""
        if self._create is None:
            raise UnsupportedOperation(
                f"a {self._what} catalog is read-only here")
        return self._create(*args, **kw)

    def __getattr__(self, name: str):
        got = self._extra.get(name)
        if got is None:
            raise AttributeError(name)
        return got()

    def __iter__(self) -> Iterator:
        return iter(self._all())

    def __len__(self) -> int:
        return len(self._all())

    def __contains__(self, value: object) -> bool:
        if isinstance(value, int):
            return self._get(value) is not None
        if isinstance(value, str) and self._by_name is not None:
            try:
                return self._by_name(value) is not None
            except AmbiguousName:
                return True
        return value in self._all()

    def __getitem__(self, key):
        if isinstance(key, str) and self._by_name is not None:
            got = self._by_name(key)
            if got is not None:
                return got
            if self._create is not None:
                return self._create(key)
            raise NotFound(f"no {self._what} named {key!r}")
        try:
            row_id = int(key)
        except (TypeError, ValueError):
            raise TypeError(
                f"a {self._what} catalog is keyed by id — {self._what} names "
                f"are not unique, so use find() or one()") from None
        got = self._get(row_id)
        if got is None:
            raise NotFound(f"no {self._what} with id {key}")
        return got

    def get(self, key, default=None):
        """Lookup that never creates: by id, or — where the catalog takes
        name keys — by name, answering ``default`` for no match."""
        if isinstance(key, str) and self._by_name is not None:
            got = self._by_name(key)
            return default if got is None else got
        try:
            return self[key]
        except NotFound:
            return default

    def find(self, name: str = "") -> list:
        """Every row whose name contains ``name`` (case-insensitive)."""
        return self._match(name)

    def one(self, name: str = ""):
        """The single row matching ``name``.

        Where several rows contain the name, one whose name IS the name (case
        aside) wins — "Alice" beside "Alice Meyer" is not what ambiguity is
        for. Two exact namesakes still raise `AmbiguousName`.
        """
        got = self._match(name)
        if len(got) > 1 and name and self._exact is not None:
            narrowed = self._exact(name)
            if len(narrowed) == 1:
                return narrowed[0]
        if not got:
            raise NotFound(f"no {self._what} matching {name!r}")
        if len(got) > 1:
            raise AmbiguousName(
                f"{len(got)} {self._what}s match {name!r} — "
                f"use find() and pick, or [] with an id")
        return got[0]

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{len(self)} {self._what}s>"
