"""Smart groups — membership DERIVED from a stored search string.

A group whose ``smart_query`` is non-empty is SMART: it looks and behaves
like any other group (name, icon, colour, granted tags, a place in the
tree), but which items belong to it is decided by its query alone —
:func:`rebuild` is the one writer of its ``item_groups`` rows, manual
assignment is refused (`ensure_assignable`), and it may not have child
groups (its membership says nothing about what a child would mean). The
`rebuild_item_metadata` / rankings pattern: derived rows, one writer,
rebuildable at any time, NO events — the query edit is the logged thing,
and a membership log would bury History under rows that all mean "the
library changed".

**When membership refreshes.** Immediately when the query is written
(`ops/groups.update` calls :func:`rebuild`), and after ordinary writes via
:class:`media_compost.smartsweep.SmartGroupSweeper` — a debounced daemon thread the `Database` pokes
from its ``after_commit`` hook, so EVERY writer is covered (API, importer,
jobs, CLI, scripting), the sidecar writer's own argument. The sweep is
cheap when it has nothing to do (one indexed SELECT says whether any smart
group exists) and a rebuild that changes nothing writes nothing, which is
what lets the sweeper's own commit not re-trigger itself; its session also
carries a ``smart_sweep`` marker as the belt to that brace. In synchronous
mode (the sidecar writer's knob — the test suite's determinism) the sweep
runs inline instead.

**Sidecars.** Smart memberships are DERIVED, so `item_to_dict` leaves them
out of ``item.json`` (the score-tag rule: a derived row round-tripping
would come back as a manual assignment) and ``groups.json`` carries the
``smart_query``; a folder restore recreates the group and
`libimport._rebuild_smart_groups` refits membership at the end, exactly as
`_refit_rankings` refits scores. That exclusion is also what keeps a
rebuild from queueing thousands of sidecar rewrites: membership changes
touch no per-item file.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, func, insert, literal, select

from ..db import Group, GroupParent, ItemGroup, chunked
from ..querystring import try_parse
from .context import Ctx
from .errors import Invalid, Refused


def is_smart(group: Group) -> bool:
    """Smart is an IDENTITY: the column is NULL for an ordinary group and a
    string — empty included — for a smart one, fixed at creation."""
    return group.smart_query is not None


def smart_group_ids(session) -> set[int]:
    return set(session.execute(
        select(Group.id).where(Group.smart_query.is_not(None))
    ).scalars().all())


def check_query(query: str) -> None:
    """A smart query must PARSE when set — stored unparseable it would
    silently mean "nothing", which reads as a group that lost its items
    (the ranking-scope rule)."""
    query = (query or "").strip()
    if query and try_parse(query) is None:
        raise Invalid("the smart group's search is not a valid query",
                      code="smart_query_invalid")


def ensure_assignable(ctx: Ctx, group_ids) -> None:
    """Refuse manually assigning items to (or removing them from) a smart
    group: its query is the only thing that decides membership, and a hand
    edit would be silently undone by the next rebuild."""
    s = ctx.session
    for gid in group_ids:
        g = s.get(Group, gid)
        if g is not None and is_smart(g):
            raise Refused(
                "“{name}” is a smart group — its search decides which items "
                "belong to it",
                {"name": g.name}, code="smart_group_derived",
            )


def ensure_can_parent(ctx: Ctx, parent_id: Optional[int]) -> None:
    """Refuse making anything a CHILD of a smart group."""
    if parent_id is None:
        return
    g = ctx.session.get(Group, parent_id)
    if g is not None and is_smart(g):
        raise Refused(
            "“{name}” is a smart group and cannot have groups inside it",
            {"name": g.name}, code="smart_group_no_children",
        )


def rebuild(ctx: Ctx, group: Group) -> dict:
    """Refit one smart group's membership from its query — the ONE writer.

    The query resolves through `ops/search.search_filtered`, the same code
    path the grid uses (the "one QueryCtx" rule), over the whole library
    with hidden items included — a membership rule is a statement about the
    library, not about what a view happens to be showing. Core statements
    for the diff, because a first build can add half a million rows and
    per-row ORM inserts are minutes of that; the rows never reach per-item
    sidecars (see the module docstring), so there is nothing to mark.
    """
    from ..resolve import Resolver
    from . import search

    s = ctx.session
    # An EMPTY rule holds nothing — a fresh smart group has not said which
    # items yet, and "no rule" meaning "everything" would be a whole-library
    # membership nobody asked for. `try_parse("")` answers None either way.
    tree = try_parse(group.smart_query or "")
    if not (group.smart_query or "").strip() or tree is None:
        return _replace_with(s, group, None)

    res = Resolver(s)
    cs = search.search_filtered(s, "", False, False,
                                show_hidden=True, query=tree,
                                resolver=res)
    if cs.residue is None:
        # THE DIFF STAYS IN SQLITE. It used to come back as two Python sets —
        # every matching id and every current member — and on a big library
        # that is the difference between a sweep and a stall: measured on a
        # 1.1M-item library, 5.8 s and 309 MB of peak allocation against
        # 0.89 s and 0.2 MB for the same answer expressed as two statements.
        # The sweeper runs after EVERY commit burst, so during an import it
        # was doing that continuously — which is what made a web import get
        # slower with every batch while the same import from the CLI, with
        # no second process sweeping beside it, did not.
        return _replace_with(s, group, cs.ids_select())
    # The residue path cannot be a subquery — the match is decided in Python
    # by definition — so it keeps the set it has to build either way.
    return _replace_with(s, group, sorted(cs.matched_ids(s, res)))


def _replace_with(s, group: Group, wanted) -> dict:
    """Make the group's membership exactly ``wanted`` and say what moved.

    ``wanted`` is a SELECT of item ids (the exact path), a list of ids (the
    residue path), or None for "nothing at all". Both id-bearing forms go
    through the same two statements, so the two paths cannot drift into two
    ideas of what a rebuild writes.

    ``synchronize_session=False`` on both, deliberately: these are DERIVED
    rows that no caller holds as objects, and the ORM's default would answer
    a subquery-shaped WHERE by SELECTing the affected rows first — which is
    the whole cost this is here to avoid.
    """
    current = select(ItemGroup.item_id).where(ItemGroup.group_id == group.id)
    if wanted is None:
        removed = s.execute(
            delete(ItemGroup).where(ItemGroup.group_id == group.id),
            execution_options={"synchronize_session": False},
        ).rowcount or 0
        if removed:
            s.flush()
        return {"members": 0, "added": 0, "removed": removed}

    if isinstance(wanted, list):
        # A LIST is chunked against SQLite's bind-parameter cap, the rule
        # every Python-side id list here follows.
        keep = set(wanted)
        have = set(s.execute(current).scalars().all())
        gone = sorted(have - keep)
        fresh = [i for i in wanted if i not in have]
        for chunk in chunked(gone):
            s.execute(delete(ItemGroup).where(
                ItemGroup.group_id == group.id,
                ItemGroup.item_id.in_(chunk)))
        for chunk in chunked(fresh):
            s.execute(insert(ItemGroup),
                      [{"item_id": iid, "group_id": group.id}
                       for iid in chunk])
        if gone or fresh:
            s.flush()
        return {"members": len(keep), "added": len(fresh),
                "removed": len(gone)}

    removed = s.execute(
        delete(ItemGroup).where(ItemGroup.group_id == group.id,
                                ItemGroup.item_id.not_in(wanted)),
        execution_options={"synchronize_session": False},
    ).rowcount or 0
    # ONE subquery object, referred to twice. Calling `.subquery()` again
    # builds a SECOND anonymous select, so the guard would be comparing a
    # different query's column and every row already in the group would be
    # inserted a second time — which the unique index catches, loudly.
    ids = wanted.subquery()
    added = s.execute(
        insert(ItemGroup).from_select(
            ["item_id", "group_id"],
            select(ids.c[0], literal(group.id))
            .where(ids.c[0].not_in(current))),
        execution_options={"synchronize_session": False},
    ).rowcount or 0
    if removed or added:
        s.flush()
    members = s.execute(
        select(func.count()).select_from(current.subquery())).scalar() or 0
    return {"members": members, "added": added, "removed": removed}


def rebuild_all(ctx: Ctx) -> bool:
    """Every smart group, refit — in id order, one session, so a smart query
    reading another smart group's membership (`group:Other`) sees this
    sweep's fresh rows for groups rebuilt before it. Returns whether
    anything changed."""
    changed = False
    for g in ctx.session.execute(
        select(Group).where(Group.smart_query.is_not(None))
        .order_by(Group.id)
    ).scalars().all():
        out = rebuild(ctx, g)
        changed = changed or bool(out["added"] or out["removed"])
    return changed
