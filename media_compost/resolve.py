"""Effective-tag resolution over the group tree (DESCRIPTION §Library).

Tags assigned to a group are inherited by all descendant groups and items. A
negative assignment removes an indirectly-assigned tag from a child. Direct
item assignments take precedence over inherited ones.

Reads are SCOPED to the requested items (``item_tags``/``item_groups`` by
``item_id``, tag names only for the ids actually seen); the catalog tables the
algorithm consults (group edges, group tag grants, the implication closure) are
small and memoized per :class:`Resolver`. Share one Resolver across the calls
of a request — each ``effective_for_items`` call without one rebuilds the
catalogs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import GroupParent, GroupTag, ItemGroup, ItemTag, Tag, chunked


@dataclass
class EffectiveTags:
    positive: set[str] = field(default_factory=set)
    negative: set[str] = field(default_factory=set)
    direct_positive: set[str] = field(default_factory=set)
    direct_negative: set[str] = field(default_factory=set)
    # group_id -> set of tag names contributed (positively) by that group.
    indirect_by_group: dict[int, set[str]] = field(default_factory=dict)
    # group_id -> set of tag names contributed (negatively) by that group, i.e.
    # a group assignment that marks the tag negative on its items.
    indirect_negative_by_group: dict[int, set[str]] = field(default_factory=dict)
    # Tag names positive on the item *only* because a tag that entails them is
    # assigned — the implications (``TagImplication``). Full display set:
    # includes ones the item also assigns directly (those are the "overridden"
    # ones the sidebar greys out).
    indirect_by_parent: set[str] = field(default_factory=set)
    # implied name -> the assigned/effective tags that entail it (the "reason"
    # shown next to an implied tag in the sidebar).
    parent_sources: dict[str, set[str]] = field(default_factory=dict)


def _group_ancestors(session: Session) -> dict[int, set[int]]:
    """Map each group id to the set of its ancestor group ids (incl. itself).

    A group has at most one parent, so this walks a simple chain; the visited
    set is kept as a defensive guard against a malformed (cyclic) edge set.
    """
    parents: dict[int, list[int]] = {}
    for gid, pid in session.execute(
        select(GroupParent.group_id, GroupParent.parent_group_id)
    ).all():
        parents.setdefault(gid, []).append(pid)

    cache: dict[int, set[int]] = {}

    def ancestors(g: int, stack: set[int]) -> set[int]:
        if g in cache:
            return cache[g]
        acc = {g}
        for p in parents.get(g, ()):
            if p in stack:
                continue  # break cycle
            acc |= ancestors(p, stack | {g})
        cache[g] = acc
        return acc

    all_groups = set(parents.keys())
    for lst in parents.values():
        all_groups.update(lst)
    for g in all_groups:
        ancestors(g, set())
    return cache


def tag_implications(session: Session) -> dict[str, set[str]]:
    """Map each tag name to every name it entails, transitively.

    A tag may imply ANY NUMBER of others (``TagImplication``) — "poodle"
    implies "dog" and "pet" — and an implied tag's own implications follow, so
    a chain behaves the way the old single-parent hierarchy did. Cycle-safe:
    a loop stops at the tag it came from rather than recursing.

    SPARSE: only names that actually imply something have an entry (a name with
    no implications used to map to an empty set). Every caller reads it with
    ``.get(name, set())``, so the two shapes answer identically — but loading
    names only for the tags the (small) implication table references is what
    keeps this callable per request on a large library.
    """
    from .db import TagImplication

    edges = session.execute(
        select(TagImplication.tag_id, TagImplication.implies_id)
    ).all()
    if not edges:
        return {}
    involved = {tid for edge in edges for tid in edge}
    name_by_id: dict[int, str] = {}
    for chunk in chunked(involved):
        name_by_id.update(session.execute(
            select(Tag.id, Tag.name).where(Tag.id.in_(chunk))
        ).all())
    direct: dict[str, set[str]] = {}
    for tag_id, implies_id in edges:
        a, b = name_by_id.get(tag_id), name_by_id.get(implies_id)
        if a is not None and b is not None and a != b:
            direct.setdefault(a, set()).add(b)

    # A plain BFS per name. The old recursive walk memoized partial answers:
    # its guard only noticed a cycle cut at DIRECT-child depth, so a walk cut
    # at a grandchild was cached as if complete and poisoned every closure
    # that reused it — a `dog` search could silently miss `poodle`-implied
    # items whenever the implication graph held a cycle. The edge set is a
    # small catalog; per-name BFS is exact and costs nothing that matters.
    def closure(name: str) -> set[str]:
        seen = {name}
        queue = list(direct.get(name, ()))
        acc: set[str] = set()
        while queue:
            cur = queue.pop()
            if cur in seen:
                continue
            seen.add(cur)
            acc.add(cur)
            queue.extend(direct.get(cur, ()))
        return acc

    return {name: closure(name) for name in name_by_id.values()}


class Resolver:
    """Per-request effective-tag resolution with memoized catalogs.

    The catalogs the algorithm consults — group ancestor edges, group tag
    grants, the implication closure — are loaded ONCE per Resolver; per-item
    state (``item_tags``/``item_groups``) is read scoped to the ids asked
    about, tag names only for the ids those rows actually reference. Create
    one per request and pass it through, or the second ``effective_for`` call
    reloads the catalogs the first already had.
    """

    def __init__(self, session: Session):
        self.s = session
        self._ancestors: dict[int, set[int]] | None = None
        self._implications: dict[str, set[str]] | None = None
        self._grants: tuple[dict[int, set[str]], dict[int, set[str]]] | None = None
        self._names: dict[int, str] = {}       # tag id -> name, grown lazily
        self._names_missing: set[int] = set()  # ids known to have no Tag row

    @property
    def ancestors(self) -> dict[int, set[int]]:
        if self._ancestors is None:
            self._ancestors = _group_ancestors(self.s)
        return self._ancestors

    @property
    def implications(self) -> dict[str, set[str]]:
        if self._implications is None:
            self._implications = tag_implications(self.s)
        return self._implications

    def names_for(self, tag_ids: set[int]) -> dict[int, str]:
        """Tag names for these ids (chunked; a dangling id simply has none)."""
        wanted = tag_ids - self._names.keys() - self._names_missing
        for chunk in chunked(wanted):
            self._names.update(self.s.execute(
                select(Tag.id, Tag.name).where(Tag.id.in_(chunk))
            ).all())
        self._names_missing |= wanted - self._names.keys()
        return self._names

    @property
    def group_grants(self) -> tuple[dict[int, set[str]], dict[int, set[str]]]:
        """Group -> positive / negative tag-name sets (direct on the group).
        ``group_tags`` is a catalog table — dozens of rows — so it is loaded
        whole."""
        if self._grants is None:
            rows = self.s.execute(
                select(GroupTag.group_id, GroupTag.tag_id, GroupTag.negative)
            ).all()
            names = self.names_for({tid for _, tid, _ in rows})
            g_pos: dict[int, set[str]] = {}
            g_neg: dict[int, set[str]] = {}
            for gid, tid, neg in rows:
                name = names.get(tid)
                if name is None:
                    continue
                (g_neg if neg else g_pos).setdefault(gid, set()).add(name)
            self._grants = (g_pos, g_neg)
        return self._grants

    def effective_for(
        self, item_ids: list[int] | None = None
    ) -> dict[int, EffectiveTags]:
        """Compute effective tags for the given items (or all items)."""
        session = self.s
        ancestors = self.ancestors
        tag_anc = self.implications
        g_pos, g_neg = self.group_grants

        # Item -> its direct group memberships / direct tag assignments. Read
        # scoped to the requested ids; ``None`` still means the whole library
        # (the legacy mode small libraries and tests use).
        item_groups: dict[int, list[int]] = {}
        tag_rows: list[tuple[int, int, bool]] = []
        if item_ids is None:
            for iid, gid in session.execute(
                select(ItemGroup.item_id, ItemGroup.group_id)
            ).all():
                item_groups.setdefault(iid, []).append(gid)
            tag_rows = session.execute(
                select(ItemTag.item_id, ItemTag.tag_id, ItemTag.negative)
            ).all()
        else:
            for chunk in chunked(item_ids):
                for iid, gid in session.execute(
                    select(ItemGroup.item_id, ItemGroup.group_id)
                    .where(ItemGroup.item_id.in_(chunk))
                ).all():
                    item_groups.setdefault(iid, []).append(gid)
                tag_rows.extend(session.execute(
                    select(ItemTag.item_id, ItemTag.tag_id, ItemTag.negative)
                    .where(ItemTag.item_id.in_(chunk))
                ).all())

        names = self.names_for({tid for _, tid, _ in tag_rows})
        item_pos: dict[int, set[str]] = {}
        item_neg: dict[int, set[str]] = {}
        for iid, tid, neg in tag_rows:
            name = names.get(tid)
            if name is None:
                continue
            (item_neg if neg else item_pos).setdefault(iid, set()).add(name)

        if item_ids is None:
            item_ids = sorted({iid for iid, _, _ in tag_rows} | set(item_groups))

        return _fold_effective(
            item_ids, ancestors, tag_anc, g_pos, g_neg,
            item_groups, item_pos, item_neg,
        )


def effective_for_items(
    session: Session, item_ids: list[int] | None = None
) -> dict[int, EffectiveTags]:
    """Compute effective tags for the given items (or all items).

    Thin wrapper over :class:`Resolver` — callers that resolve more than once
    per request should hold a Resolver instead, so the catalog reads happen
    once.
    """
    return Resolver(session).effective_for(item_ids)


def _fold_effective(
    item_ids: list[int],
    ancestors: dict[int, set[int]],
    tag_anc: dict[str, set[str]],
    g_pos: dict[int, set[str]],
    g_neg: dict[int, set[str]],
    item_groups: dict[int, list[int]],
    item_pos: dict[int, set[str]],
    item_neg: dict[int, set[str]],
) -> dict[int, EffectiveTags]:
    result: dict[int, EffectiveTags] = {}
    for iid in item_ids:
        eff = EffectiveTags()
        eff.direct_positive = set(item_pos.get(iid, set()))
        eff.direct_negative = set(item_neg.get(iid, set()))

        inherited_pos: set[str] = set()
        inherited_neg: set[str] = set()
        for gid in item_groups.get(iid, ()):  # each membership + its ancestors
            for anc in ancestors.get(gid, {gid}):
                contributed = g_pos.get(anc, set())
                if contributed:
                    inherited_pos |= contributed
                    eff.indirect_by_group.setdefault(anc, set()).update(contributed)
                neg_contributed = g_neg.get(anc, set())
                if neg_contributed:
                    inherited_neg |= neg_contributed
                    eff.indirect_negative_by_group.setdefault(anc, set()).update(
                        neg_contributed
                    )

        eff.positive = (
            (inherited_pos - inherited_neg) | eff.direct_positive
        ) - eff.direct_negative
        eff.negative = eff.direct_negative | inherited_neg

        # Implication: everything a positive tag entails is positive too
        # (unless the item explicitly marks it negative). The full implied set
        # is kept for display (the sidebar greys out ones that are also
        # directly assigned); only the non-overridden ones become effective.
        if tag_anc:
            sources: dict[str, set[str]] = {}
            for n in eff.positive:  # the assigned/inherited tags (pre-implication)
                for anc in tag_anc.get(n, set()):
                    sources.setdefault(anc, set()).add(n)
            eff.parent_sources = sources
            implied = set(sources.keys())
            eff.indirect_by_parent = implied
            eff.positive |= implied - eff.negative
        # Keep a group's positive contribution in the display set even when a
        # *direct* assignment overrides it — the sidebar shows it greyed out
        # rather than hiding it. Only drop it when *another group's* negative
        # removed it (a genuine, non-user removal, not shown at all).
        keep_pos = eff.positive | eff.direct_negative
        for gid in list(eff.indirect_by_group):
            eff.indirect_by_group[gid] &= keep_pos
            if not eff.indirect_by_group[gid]:
                del eff.indirect_by_group[gid]
        # Group negatives are all kept for display (a direct assignment that
        # overrides one is greyed out by the sidebar, not dropped here).
        result[iid] = eff
    return result


def effective_for_item(session: Session, item_id: int) -> EffectiveTags:
    return effective_for_items(session, [item_id]).get(item_id, EffectiveTags())


def descendant_groups(session: Session, roots: list[int]) -> set[int]:
    """All groups reachable downward from ``roots`` (inclusive), cycle-safe."""
    children: dict[int, list[int]] = {}
    for gid, pid in session.execute(
        select(GroupParent.group_id, GroupParent.parent_group_id)
    ).all():
        children.setdefault(pid, []).append(gid)

    seen: set[int] = set()
    stack = list(roots)
    while stack:
        g = stack.pop()
        if g in seen:
            continue
        seen.add(g)
        stack.extend(children.get(g, ()))
    return seen
