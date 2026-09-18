"""`ItemSet` — a lazy, composable set of items.

Django's `QuerySet` is the idiom every Python user already knows for exactly
this object, and the alternative — the bare generator the old API returned —
cannot be counted, sliced, re-run, or bulk-mutated.

Iteration streams in WINDOWS, and `prefetch` is what makes a 50k-item walk
affordable: before a window is yielded, each named relation is bulk-loaded for
the whole window through the loaders the app already uses, so `item.tags`
inside the loop is a dict lookup rather than a query.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Iterator, Optional

from sqlalchemy import func, select

from .. import query as _q
from ..db import Item as _Item, chunked
from ..ops import search as ops_search, tagassign
from ..resolve import Resolver
from .errors import AmbiguousName, NotFound
from .coerce import as_group

#: How many items are hydrated at a time.
WINDOW = 500

#: What `prefetch` knows how to bulk-load. Only what `_warm` actually warms —
#: a key it accepted and silently ignored ("groups", "links", "metadata",
#: "sequences" once sat here) looks exactly like a prefetch that worked.
PREFETCHABLE = ("files", "tags", "captions", "subjects", "faces",
                "text", "all")


class ItemSet(Collection):
    """Every item matching a scope and a condition tree."""

    __slots__ = ("_lib", "_cond", "_scope", "_sort", "_prefetch", "_count")

    def __init__(self, lib, cond=None, scope: Optional[dict] = None,
                 sort: str = "recent", prefetch: tuple = ("files",)):
        self._lib = lib
        self._cond = cond
        self._scope = dict(scope or {})
        self._sort = sort
        self._prefetch = tuple(prefetch)
        self._count: Optional[int] = None

    # -- building ------------------------------------------------------------

    def _with(self, **kw) -> "ItemSet":
        return ItemSet(
            self._lib,
            kw.get("cond", self._cond),
            kw.get("scope", self._scope),
            kw.get("sort", self._sort),
            kw.get("prefetch", self._prefetch),
        )

    def filter(self, conditions) -> "ItemSet":
        """Narrow by more conditions (AND)."""
        extra = as_group(conditions)
        if extra is None:
            return self
        if self._cond is None:
            return self._with(cond=extra)
        return self._with(cond=_q.Group(op="and",
                                        children=[self._cond, extra]))

    def exclude(self, conditions) -> "ItemSet":
        extra = as_group(conditions)
        if extra is None:
            return self
        return self.filter(_q.Group(op="and", neg=True, children=[extra]))

    def scope(self, **kw) -> "ItemSet":
        merged = dict(self._scope)
        merged.update(kw)
        return self._with(scope=merged)

    def order_by(self, field: str) -> "ItemSet":
        """`first`, `recent`, `modified`, `name`, `resolution`, `width`…"""
        return self._with(sort=field)

    def prefetch(self, *names: str) -> "ItemSet":
        """Bulk-load these relations per window.

        Without it, reading `item.tags` on every item of a large result is one
        query per item. Set `MEDIA_COMPOST_WARN_N_PLUS_1=1` and the API says
        so the first time it happens.
        """
        bad = [n for n in names if n not in PREFETCHABLE]
        if bad:
            raise ValueError(f"cannot prefetch {bad[0]!r}; "
                             f"try one of {', '.join(PREFETCHABLE)}")
        return self._with(prefetch=tuple(names))

    # -- running -------------------------------------------------------------

    def _candidates(self):
        return ops_search.search_filtered(
            self._lib._session, query=self._cond,
            groups=self._scope.get("groups", ""),
            ungrouped=self._scope.get("ungrouped", False),
            trash=self._scope.get("trash", False),
            kind=self._scope.get("kind", ""),
            sequence=self._scope.get("sequence"),
            hide_sequenced=self._scope.get("hide_sequenced", False),
            fold_sequenced=self._scope.get("fold_sequenced", False),
            hidden=self._scope.get("hidden", False),
            show_hidden=self._scope.get("show_hidden", False),
            pending=self._scope.get("pending", False),
            pending_kind=self._scope.get("pending_kind", ""),
            untagged=self._scope.get("untagged", False),
            # A script has no primed near-dup index, so `SIMILAR:` builds a
            # transient one — gated on the query actually asking for it.
        )

    def ids(self) -> list[int]:
        """The matching ids, in sort order."""
        s = self._lib._session
        cands = self._candidates()
        order = ops_search.prefilter.order_by_for(self._sort,
                                                  self._scope.get("sequence"))
        stmt = ops_search.prefilter.base_select(
            [_Item.id], self._scope.get("sequence"), cands.where).order_by(*order)
        if cands.residue is None:
            return list(s.execute(stmt).scalars().all())
        # Whatever would not compile exactly is re-evaluated over the
        # SQL-narrowed candidates; `evaluate()` stays the one definition of
        # what a match is.
        matched = set(cands.matched_ids(s, Resolver(s)))
        return [i for i in s.execute(stmt).scalars().all() if i in matched]

    def uids(self) -> list[str]:
        s = self._lib._session
        out = []
        for chunk in chunked(self.ids()):
            out.extend(s.execute(select(_Item.uid)
                                 .where(_Item.id.in_(chunk))).scalars().all())
        return out

    # -- bulk reads ----------------------------------------------------------
    #
    # `prefetch` warms what a handle reads one item at a time. These two answer
    # for the whole result in one go instead, because the per-item shape of the
    # question is a multi-way join and a caller walking a library would pay it
    # per picture — or, for tag groups, four times per picture.

    def tag_groups(self) -> dict:
        """Every matching item's per-item tag GROUPS, keyed by item id.

        A list of `GroupedTags` per item in the groups' own order — the name,
        whether it is one the app manages, the positive tags placed in it in
        placement order, its meta tags, and who it is about.
        `item.tag_groups` is the live view of one item's; this is the read for
        a pass over many.
        """
        from .values import GroupedTags

        rows = tagassign.groups_for_items(self._lib._ctx(), self.ids())
        return {iid: [GroupedTags(**g) for g in groups]
                for iid, groups in rows.items()}

    def ungrouped_tags(self) -> dict:
        """Per item id, the positive tag names in NO tag group.

        The companion to `tag_groups()`, and not derivable from it: a tag can
        be placed in a group and still be on the picture by the ungrouped
        route as well, which a rule about "every placement of it" has to see.
        """
        return tagassign.ungrouped_for_items(self._lib._ctx(), self.ids())

    def tag_boxes(self) -> dict:
        """Every box on every matching item: `{item id: {tag name: [Box]}}`.

        The boxes come back as STORED — geometry in the item's REFERENCE
        frame, and a range-only box carrying a time and no rectangle. Map a
        rectangle through `item.active_file.crop` to get the frame the stored
        pixels actually show.

        A name whose assignment is NEGATIVE on that item is present too: the
        boxes are keyed by tag name, and whether the tag applies is a
        different question — `item.tags` answers it.
        """
        from .handles import Box

        rows = tagassign.boxes_for_items(self._lib._ctx(), self.ids())
        return {iid: {name: [Box(self._lib, b.id, b) for b in boxes]
                      for name, boxes in by_name.items()}
                for iid, by_name in rows.items()}

    def __iter__(self) -> Iterator:
        from .handles import Item

        s = self._lib._session
        ids = self.ids()
        for start in range(0, len(ids), WINDOW):
            window = ids[start:start + WINDOW]
            rows = {r.id: r for r in s.execute(
                select(_Item).where(_Item.id.in_(window))).scalars().all()}
            self._warm(window)
            for iid in window:
                row = rows.get(iid)
                if row is not None:
                    yield Item(self._lib, iid, row)

    def _warm(self, ids: list[int]) -> None:
        """Bulk-load the prefetched relations for one window."""
        want = set(self._prefetch)
        if "all" in want:
            want = set(PREFETCHABLE) - {"all"}
        s = self._lib._session
        if "files" in want:
            from ..db import File

            for chunk in chunked(ids):
                s.execute(select(File).where(File.item_id.in_(chunk))).all()
        if "tags" in want:
            # The library's shared resolver, not a fresh one: its three
            # catalogs are loaded once per generation, so warming the
            # hundredth window costs the same as the first.
            self._lib._eff_cache.update(
                self._lib._resolver().effective_for(ids))
        if "captions" in want:
            from ..db import Caption

            for chunk in chunked(ids):
                s.execute(select(Caption)
                          .where(Caption.item_id.in_(chunk))).all()
        if "subjects" in want:
            from ..db import ItemSubject

            for chunk in chunked(ids):
                s.execute(select(ItemSubject)
                          .where(ItemSubject.item_id.in_(chunk))).all()
        if "faces" in want:
            from ..db import Face

            for chunk in chunked(ids):
                s.execute(select(Face).where(Face.item_id.in_(chunk))).all()
        if "text" in want:
            from ..db import TextRegion

            for chunk in chunked(ids):
                s.execute(select(TextRegion)
                          .where(TextRegion.item_id.in_(chunk))).all()

    def batches(self, size: int = WINDOW) -> Iterator[list]:
        """Explicit windows, for a script that wants to control memory."""
        from .handles import Item

        ids = self.ids()
        for start in range(0, len(ids), size):
            window = ids[start:start + size]
            self._warm(window)
            yield [Item(self._lib, i) for i in window]

    # -- protocol ------------------------------------------------------------

    def __len__(self) -> int:
        if self._count is None:
            cands = self._candidates()
            if cands.residue is None:
                stmt = ops_search.prefilter.base_select(
                    [func.count(_Item.id.distinct())],
                    self._scope.get("sequence"), cands.where)
                self._count = int(self._lib._session.execute(stmt).scalar_one())
            else:
                self._count = len(self.ids())
        return self._count

    def __bool__(self) -> bool:
        return self.first() is not None

    def __contains__(self, value) -> bool:
        from .handles import Item

        if isinstance(value, Item):
            return value.id in set(self.ids())
        if isinstance(value, int):
            return value in set(self.ids())
        return False

    def __getitem__(self, key):
        from .handles import Item

        if isinstance(key, slice):
            ids = self.ids()[key]
            return [Item(self._lib, i) for i in ids]
        if isinstance(key, int):
            ids = self.ids()
            return Item(self._lib, ids[key])
        raise TypeError("index an ItemSet by position or slice; "
                        "look items up by uid on lib.items")

    def first(self):
        from .handles import Item

        ids = self.ids()[:1]
        return Item(self._lib, ids[0]) if ids else None

    def one(self):
        ids = self.ids()
        if not ids:
            raise NotFound("no item matches")
        if len(ids) > 1:
            raise AmbiguousName(f"{len(ids)} items match, not one")
        return self[0]

    def paths(self) -> Iterator:
        """Every matching item's file on disk, skipping the ones with none."""
        for item in self:
            got = item.path
            if got is not None:
                yield got

    # -- bulk writes ---------------------------------------------------------
    #
    # One transaction and one event per change, not per item — a 50k-item
    # script that looped would be 50k commits and 50k History entries.

    def add_tags(self, names, *, negative: bool = False) -> int:
        from ..ops import tagassign

        names = [names] if isinstance(names, str) else list(names)
        return self._lib._do(
            tagassign.stamp, self.ids(),
            [] if negative else names, names if negative else [])

    def remove_tags(self, names) -> int:
        from ..ops import tagassign

        names = [names] if isinstance(names, str) else list(names)
        return self._lib._do(tagassign.stamp, self.ids(), names, [],
                             remove=True)

    def add_to(self, group) -> int:
        from ..ops import groups as ops_groups
        from .handles import Group

        gid = group._id if isinstance(group, Group) else int(group)
        added, _ = self._lib._do(ops_groups.bulk_membership, self.ids(),
                                 [gid], [])
        return added

    def remove_from(self, group) -> int:
        from ..ops import groups as ops_groups
        from .handles import Group

        gid = group._id if isinstance(group, Group) else int(group)
        _, removed = self._lib._do(ops_groups.bulk_membership, self.ids(),
                                   [], [gid])
        return removed

    def hide(self) -> int:
        from ..ops import items as ops_items

        return self._lib._do(ops_items.hide, self.ids(), True)

    def show(self) -> int:
        from ..ops import items as ops_items

        return self._lib._do(ops_items.hide, self.ids(), False)

    def trash(self) -> int:
        from ..ops import items as ops_items

        return self._lib._do(ops_items.trash, self.ids())

    def restore(self) -> int:
        from ..ops import items as ops_items

        return self._lib._do(ops_items.restore, self.ids())

    def delete(self) -> int:
        """Permanently. `trash()` is the reversible one."""
        from ..ops import items as ops_items

        return self._lib._do(ops_items.delete_items, self.ids())

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<ItemSet {len(self)} items>"
