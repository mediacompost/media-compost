"""Library groups — a TREE, not a DAG.

Each group has at most one parent, enforced by a DB `UniqueConstraint` on
`group_parents` and by `move`, which always REPLACES the edge. Items, by
contrast, are many-to-many with groups.

A group's tags flow down to every item in its subtree, which is why deleting
one offers to BAKE them: the items keep what they were inheriting instead of
silently losing it.

A NAME IS UNIQUE AMONG ITS SIBLINGS (`unique_sibling_name`), so a PATH names
one group. `Group.name` is still not unique in the table — two branches may
each hold a "2024" — and a library written before this rule may hold two
side by side; nothing repairs those, because renaming somebody's groups on
open is not a migration to make. What the rule buys is the search: a group
condition can be given a path (`Trips/2024`) to say which of several
same-named groups it means, which only answers if a level cannot hold two.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select

from ..db import (
    Group, GroupParent, GroupTag, ItemGroup, ItemTag, chunked,
    touch_items,
)
from ..resolve import descendant_groups
from . import actions
from .context import Ctx
from .errors import NotFound, Refused


def sibling_names(s, parent_id: Optional[int],
                  exclude_id: Optional[int] = None) -> set[str]:
    """The names of the groups at one LEVEL — the children of `parent_id`, or
    the roots when it is None."""
    rows = s.execute(
        select(Group.id, Group.name, GroupParent.parent_group_id)
        .outerjoin(GroupParent, GroupParent.group_id == Group.id)).all()
    return {name for gid, name, pid in rows
            if pid == parent_id and gid != exclude_id}


def unique_sibling_name(s, parent_id: Optional[int], name: str,
                        exclude_id: Optional[int] = None) -> str:
    """`name`, or the first "name N" nothing else at that level is called.

    The training manager's job-name rule, applied to a level of the tree —
    numbering from 2, because the one already there IS the unnumbered name.
    Every writer goes through it (create, rename, move, duplicate), so the
    rule holds however a group arrives at a level: a drag onto a level that
    already has a "2024" renames the group being dragged, which is what makes
    the drop always succeed instead of refusing halfway through a gesture.

    A RENAME is numbered too, and that is deliberate rather than an
    oversight: refusing it would be a second way for a Save to fail, and
    leaving it would put back exactly the ambiguity the rule exists to
    remove. What somebody typed is still what the group is called — with a
    number after it when the level already had that name.
    """
    name = (name or "").strip()
    taken = sibling_names(s, parent_id, exclude_id)
    if name not in taken:
        return name
    n = 2
    while f"{name} {n}" in taken:
        n += 1
    return f"{name} {n}"


def parent_of(s, group_id: int) -> Optional[int]:
    """The group's parent id, or None for a root."""
    return s.execute(
        select(GroupParent.parent_group_id)
        .where(GroupParent.group_id == group_id)).scalars().first()


def create(ctx: Ctx, name: str, *, icon: str = "folder",
           parent_id: Optional[int] = None,
           smart_query: Optional[str] = None) -> Group:
    """A new group — SMART when ``smart_query`` is a string (the empty rule
    included: such a group holds nothing until the rule is written), and
    ordinary when it is None. That choice is the group's IDENTITY and never
    changes afterwards."""
    from . import smartgroups

    s = ctx.session
    if smart_query is not None:
        smart_query = smart_query.strip()
        smartgroups.check_query(smart_query)
        # No icon special-casing: the tree marks a smart group with a filter
        # glyph after its name, so the icon is free to say what the group is
        # ABOUT and both kinds share one palette. (A disjoint smart palette
        # with a rule_folder default was tried and retired with the marker.)
    smartgroups.ensure_can_parent(ctx, parent_id)
    name = unique_sibling_name(s, parent_id, name)
    g = Group(name=name, icon=icon, smart_query=smart_query)
    s.add(g)
    s.flush()
    if parent_id is not None:
        s.add(GroupParent(group_id=g.id, parent_group_id=parent_id))
    ctx.log(action=actions.CREATE_GROUP, entity_type="group", entity_id=g.id,
            summary="Created group “{name}”",
            summary_vars={"name": g.name},
            data={"group_id": g.id, "group_name": g.name,
                  "parent_id": parent_id,
                  **({"smart_query": smart_query}
                     if smart_query is not None else {})})
    if smart_query:
        smartgroups.rebuild(ctx, g)
    return g


def update(ctx: Ctx, group_id: int, *, name: Optional[str] = None,
           icon: Optional[str] = None, color: Optional[str] = None,
           smart_query: Optional[str] = None) -> Group:
    from . import smartgroups

    s = ctx.session
    g = s.get(Group, group_id)
    if not g:
        raise NotFound("group not found", code="group_not_found")
    # What the event carries is the FIELDS THAT MOVED, old and new — an edit
    # to the icon must not put yesterday's name back when it is undone, and
    # a save that changed nothing must not write an entry at all.
    before: dict = {}
    after: dict = {}

    def _moved(field: str, was, now) -> None:
        if was != now:
            before[field] = was
            after[field] = now

    if name is not None:
        was = g.name
        g.name = unique_sibling_name(s, parent_of(s, g.id), name,
                                     exclude_id=g.id)
        _moved("name", was, g.name)
    if icon is not None:
        _moved("icon", g.icon, icon)
        g.icon = icon
    if color is not None:
        _moved("color", g.color, color or None)
        g.color = color or None  # empty string clears it
    query_moved = False
    if smart_query is not None:
        # Smart is an IDENTITY, fixed at creation: an ordinary group never
        # becomes smart (make a new one), and this parameter only ever EDITS
        # a smart group's rule.
        if not smartgroups.is_smart(g):
            raise Refused(
                "“{name}” is an ordinary group and cannot become a smart "
                "group — create a new smart group instead",
                {"name": g.name}, code="group_identity_fixed",
            )
        wanted = smart_query.strip()
        smartgroups.check_query(wanted)
        query_moved = wanted != g.smart_query
        _moved("smart_query", g.smart_query, wanted)
        g.smart_query = wanted
    if before:
        ctx.log(action=actions.EDIT_GROUP, entity_type="group", entity_id=g.id,
                summary="Edited group “{name}”", summary_vars={"name": g.name},
                data={"group_id": g.id, "group_name": g.name,
                      "old": before, "new": after})
    if query_moved:
        s.flush()
        smartgroups.rebuild(ctx, g)
    return g


def bake_group_tags(ctx: Ctx, group_id: int) -> None:
    """Assign a group's tags directly to every item in its subtree, so they
    survive the group's deletion. A tag already assigned directly on an item is
    left as-is (its sign wins)."""
    s = ctx.session
    gtags = s.execute(
        select(GroupTag.tag_id, GroupTag.negative).where(GroupTag.group_id == group_id)
    ).all()
    if not gtags:
        return
    sub = descendant_groups(s, [group_id])  # includes group_id itself
    item_ids = set(s.execute(
        select(ItemGroup.item_id).where(ItemGroup.group_id.in_(sub))
    ).scalars().all())
    # One chunked sweep for what is already assigned, instead of a SELECT per
    # (item, tag) — baking a big group's tags was O(items × tags) round trips.
    tag_ids = [tid for tid, _neg in gtags]
    have: set[tuple[int, int]] = set()
    for chunk in chunked(item_ids):
        have.update(
            (iid, tid) for iid, tid in s.execute(
                select(ItemTag.item_id, ItemTag.tag_id).where(
                    ItemTag.item_id.in_(chunk), ItemTag.tag_id.in_(tag_ids))
            ).all())
    s.add_all([
        ItemTag(item_id=iid, tag_id=tid, negative=neg)
        for iid in item_ids for tid, neg in gtags
        if (iid, tid) not in have
    ])
    if item_ids:
        touch_items(s, list(item_ids))




def delete_group(ctx: Ctx, group_id: int, *,
                 assign_tags: bool = False,
                 keep_children: bool = False) -> None:
    """Delete a group. The subtree goes with it unless `keep_children`.

    THE SUBTREE GOES WITH IT, by default. The children used to be REPARENTED
    onto this group's own parent silently, which reads as tidiness and is a
    decision nobody asked for: deleting "2024" left its twelve months
    scattered across the root, and the way back was to make the parent again
    and drag each one home. Deleting a group means deleting the shelf, not
    emptying it onto the floor. ITEMS still stay in the library, which is the
    half that matters and has not changed — a group is a view of them, not a
    home.

    `keep_children` is that reparenting back as a SEPARATE VERB rather than
    as the default. What was wrong with it was never that nobody wants it —
    a group made only to hold three others is exactly the thing you take out
    from over them — it was that one word ("Delete") did two very different
    things and only one of them was named. So the menu offers both, the
    second only where there IS a subtree to keep, and each says which it is.

    The children promoted this way go to the deleted group's OWN parent, root
    included; their ids ride on the event so the revert can put them back
    under the group it restores.
    """
    s = ctx.session
    g = s.get(Group, group_id)
    if not g:
        raise NotFound("group not found", code="group_not_found")
    # Membership rows cascade away at the DB level (invisible to the ORM
    # sweep). Optionally bake the group's tags onto its items before removing
    # it, so the items keep the tags they were inheriting.
    whole = descendant_groups(s, [group_id])  # includes group_id itself
    sub = {group_id} if keep_children else whole
    promoted: list[int] = []
    if keep_children:
        promoted = sorted(s.execute(
            select(GroupParent.group_id)
            .where(GroupParent.parent_group_id == group_id)).scalars().all())
    if assign_tags:
        # Each group's OWN tags onto its OWN subtree, one call each: a child's
        # tags are not the parent's, and the child is going too. Baking only
        # the root's would keep what the items inherited from the top and lose
        # everything the groups underneath were granting. Keeping the
        # children, only THIS group's tags are stopping — the survivors go on
        # granting their own.
        for gid in sorted(sub):
            bake_group_tags(ctx, gid)
    inside = sorted(sub - {group_id})
    snap, dropped = _snapshot_subtree(s, group_id, sub)
    ctx.log(action=actions.DELETE_GROUP, entity_type="group",
            entity_id=group_id,
            # ONE TEMPLATE PER SHAPE rather than one with a count in it: a
            # slot holding a number cannot inflect the noun beside it once
            # this is translated, and the ordinary case — a group with
            # nothing inside it — has to keep saying exactly what it always
            # said.
            summary=(
                "Deleted group “{name}”" if not inside and not promoted
                else "Deleted group “{name}”, keeping the group inside it"
                if keep_children and len(promoted) == 1
                else "Deleted group “{name}”, keeping the {n} groups inside it"
                if keep_children
                else "Deleted group “{name}” and the group inside it"
                if len(inside) == 1
                else "Deleted group “{name}” and the {n} groups inside it"),
            summary_vars=(
                {"name": g.name}
                if (len(promoted) if keep_children else len(inside)) < 2
                else {"name": g.name,
                      "n": str(len(promoted) if keep_children else len(inside))}
            ),
            # The extra keys ride only when they say something, so an event
            # for a childless group is byte-identical to the one every
            # earlier build wrote.
            data={"group_id": group_id, "group_name": g.name,
                  **({"deleted_group_ids": inside} if inside else {}),
                  # The children this deletion moved UP, and where they were
                  # before it — what `_revert_delete_group` needs to put them
                  # back under the group it restores.
                  **({"promoted_group_ids": promoted} if promoted else {}),
                  # What a revert needs. Absent when it would not fit (see
                  # `_snapshot_subtree`), and `history.can_revert` reads that
                  # absence rather than guessing.
                  **({"undo": snap} if snap is not None else {}),
                  **({"members_dropped": dropped} if dropped else {})})
    if promoted:
        # Up to where this group hung, root included. `move` would refuse a
        # cycle it cannot make here (the target is this group's own parent,
        # which is never inside its subtree) and would re-check the smart
        # rules the parent already passed when this group was put under it.
        up = s.execute(select(GroupParent.parent_group_id)
                       .where(GroupParent.group_id == group_id)).scalar()
        s.execute(delete(GroupParent)
                  .where(GroupParent.group_id.in_(promoted)))
        if up is not None:
            s.add_all([GroupParent(group_id=gid, parent_group_id=up)
                       for gid in promoted])
        s.flush()
    # Deepest first. The edges cascade either way, but a child deleted after
    # its parent is a row deleted through an edge that has already gone —
    # correct, and harder to read than doing it in an order that cannot
    # depend on the cascade.
    for gid in sorted(inside, reverse=True):
        child = s.get(Group, gid)
        if child is not None:
            s.delete(child)
    s.delete(g)  # cascades remove its remaining edges + memberships


#: HOW MANY MEMBERSHIP ROWS A DELETION MAY CARRY IN ITS EVENT.
#:
#: The whole subtree goes into the event so a revert can put it back, and the
#: history LIST sends every event's `data` to the browser — so one deletion of
#: a group holding a million items would be an eight-megabyte row inside a
#: five-hundred-event page. Past this, the memberships are not snapshotted and
#: the event says so; `history.can_revert` then declines it rather than
#: offering an undo that would bring the groups back empty.
#:
#: A side TABLE would have no such bound and is the better shape if this ever
#: needs one — it is a schema change and a migration rung, which is a promise
#: about a format, and 20k ids (~140 KB of JSON) covers every group anybody
#: has actually built here.
UNDO_MEMBERS_MAX = 20_000


def _snapshot_subtree(s, root_id: int, sub: "set[int]"):
    """Everything a revert would need to put this subtree back, or None.

    Returns ``(snapshot, members_dropped)``. ROOT FIRST, then the rest in id
    order, so a restore can recreate parents before the children that name
    them.

    A SMART group carries its query and NOT its members: those rows are
    derived (`ops/smartgroups.rebuild` is their one writer), so restoring the
    query restores the membership — and counting them against the cap would
    let one smart group over the whole library make an ordinary sibling
    unrestorable.
    """
    rows = [s.get(Group, gid) for gid in [root_id, *sorted(sub - {root_id})]]
    rows = [g for g in rows if g is not None]
    parents = dict(s.execute(
        select(GroupParent.group_id, GroupParent.parent_group_id)
        .where(GroupParent.group_id.in_(sub))).all())
    members: dict[int, list[int]] = {}
    total = 0
    for g in rows:
        if g.smart_query is not None:
            continue
        ids = list(s.execute(
            select(ItemGroup.item_id)
            .where(ItemGroup.group_id == g.id)).scalars().all())
        total += len(ids)
        members[g.id] = ids
    if total > UNDO_MEMBERS_MAX:
        return None, total
    return {"groups": [{
        "id": g.id, "uid": g.uid, "name": g.name, "icon": g.icon,
        "color": g.color, "smart_query": g.smart_query,
        "parent": parents.get(g.id),
        "tags": [[tid, bool(neg)] for tid, neg in s.execute(
            select(GroupTag.tag_id, GroupTag.negative)
            .where(GroupTag.group_id == g.id)).all()],
        # Absent for a smart group, whose rows come back from its query.
        **({"items": members[g.id]} if g.id in members else {}),
    } for g in rows]}, 0


def move(ctx: Ctx, group_id: int, new_parent_id: Optional[int]) -> None:
    s = ctx.session
    g = s.get(Group, group_id)
    if not g:
        raise NotFound("group not found", code="group_not_found")
    if new_parent_id is not None:
        from . import smartgroups

        smartgroups.ensure_can_parent(ctx, new_parent_id)
        if new_parent_id in descendant_groups(s, [group_id]):
            raise Refused("cannot move a group under its own subtree",
                          code="group_cycle")
    # A group has at most one parent, so a move always replaces the existing
    # edge (dropping onto "All Items" / no parent makes it a root).
    old_parent_id = parent_of(s, group_id)
    s.execute(delete(GroupParent).where(GroupParent.group_id == group_id))
    if new_parent_id is not None:
        s.add(GroupParent(group_id=group_id, parent_group_id=new_parent_id))
    # A level cannot hold two of a name, so the group being MOVED takes the
    # number: the drop is what the user just did, and refusing it halfway
    # through a gesture is worse than arriving as "Trips 2".
    s.flush()
    old_name = g.name
    g.name = unique_sibling_name(s, new_parent_id, g.name, exclude_id=g.id)
    # The RENAME the arrival may have forced is part of the move and reverts
    # with it — put back under its old parent, the group takes its old name
    # again, which is free there by construction.
    if old_parent_id != new_parent_id or old_name != g.name:
        ctx.log(action=actions.MOVE_GROUP, entity_type="group", entity_id=g.id,
                summary="Moved group “{name}”", summary_vars={"name": g.name},
                data={"group_id": g.id, "group_name": g.name,
                      "old_parent_id": old_parent_id,
                      "parent_id": new_parent_id,
                      "old_name": old_name, "name": g.name})


def merge(ctx: Ctx, dest_id: int, source_ids: list[int]) -> tuple[int, int]:
    """Empty each source group into ``dest`` and delete it.

    What MOVES is the source's contents — its items and its child groups.
    What does not is anything about the source ITSELF: its name, icon,
    colour, its granted tags and its smart rule go with it, because the
    destination is the group that survives and merging must not quietly
    change what it says about the items already in it.

    Built out of the three logged primitives rather than as an operation of
    its own — `bulk_membership`, `move`, `delete_group` — which is
    `merge_tag`'s shape one level up: every step is an event somebody can
    read and revert, and there is no new action string, no new revert
    handler and nothing for the history golden to learn.

    Returns ``(items moved, groups emptied)``.
    """
    from . import smartgroups

    s = ctx.session
    dest = s.get(Group, dest_id)
    if dest is None:
        raise NotFound("group not found", code="group_not_found")
    # A SMART group cannot be either end: its membership is derived, so
    # merging into one is manual membership (which it refuses) and merging
    # one away would copy a rule's answer into a hand-made list — a
    # different claim, made silently.
    smartgroups.ensure_assignable(ctx, [dest_id])
    ids = [i for i in dict.fromkeys(source_ids) if i != dest_id]
    if not ids:
        raise Refused("nothing to merge into that group",
                      code="group_merge_empty")
    sources = {g.id: g for chunk in chunked(ids)
               for g in s.execute(
                   select(Group).where(Group.id.in_(chunk))).scalars().all()}
    missing = [i for i in ids if i not in sources]
    if missing:
        raise NotFound("group not found", code="group_not_found")
    smartgroups.ensure_assignable(ctx, ids)
    # An ANCESTOR of the destination cannot be a source: its children include
    # the branch the destination is in, so moving them would put the
    # destination inside itself. Refused by name rather than left to `move`'s
    # cycle guard, which would fire halfway through.
    if dest_id in descendant_groups(s, ids):
        raise Refused("cannot merge a group into one of its own descendants",
                      code="group_merge_cycle")

    moved = 0
    for sid in ids:
        items = list(s.execute(
            select(ItemGroup.item_id).where(ItemGroup.group_id == sid)
        ).scalars().all())
        if items:
            added, _ = bulk_membership(ctx, items, [dest_id], [])
            moved += added
        # The children move BEFORE the delete, or the delete takes them.
        for child in s.execute(select(GroupParent.group_id).where(
                GroupParent.parent_group_id == sid)).scalars().all():
            move(ctx, child, dest_id)
        s.flush()
        delete_group(ctx, sid)
    return moved, len(ids)


def duplicate(ctx: Ctx, group_id: int,
              new_parent_id: Optional[int] = None) -> int:
    """Deep-copy a group (and its subtree) into fresh groups with new ids.

    The clone shares the same items (new ``item_groups`` rows pointing at the
    existing items) and copies the group's tag assignments, but every cloned
    group gets its own unique id — it is fully independent of the original.
    """
    s = ctx.session
    if not s.get(Group, group_id):
        raise NotFound("group not found", code="group_not_found")

    # Child adjacency, built once.
    children: dict[int, list[int]] = {}
    for gid, pid in s.execute(
        select(GroupParent.group_id, GroupParent.parent_group_id)
    ).all():
        children.setdefault(pid, []).append(gid)

    from . import smartgroups

    smartgroups.ensure_can_parent(ctx, new_parent_id)

    def clone(src_id: int, parent_id: Optional[int],
              path: frozenset) -> int:
        src = s.get(Group, src_id)
        # smart_query travels VERBATIM: None is an ordinary group and any
        # string — empty included — is a smart one, so an `or ""` here turned
        # every ordinary group's clone into an empty-rule smart group, which
        # holds nothing (the membership copy below is skipped) and refuses
        # child groups. The duplicate must be the same KIND as the original.
        # Only the clone's ROOT can collide: it lands beside the original,
        # while every cloned child is the only one of its name under a
        # brand-new parent.
        cloned_name = (unique_sibling_name(s, parent_id, src.name)
                       if src_id == group_id else src.name)
        new = Group(name=cloned_name, icon=src.icon, color=src.color,
                    smart_query=src.smart_query)
        s.add(new)
        s.flush()  # assign new.id
        if parent_id is not None:
            s.add(GroupParent(group_id=new.id, parent_group_id=parent_id))
        for gt in s.execute(
            select(GroupTag).where(GroupTag.group_id == src_id)
        ).scalars().all():
            s.add(GroupTag(group_id=new.id, tag_id=gt.tag_id,
                           negative=gt.negative))
        # A smart clone derives its members from the copied query rather
        # than inheriting rows the next sweep would rewrite anyway.
        if smartgroups.is_smart(new):
            s.flush()
            smartgroups.rebuild(ctx, new)
        else:
            for iid in s.execute(
                select(ItemGroup.item_id).where(ItemGroup.group_id == src_id)
            ).scalars().all():
                s.add(ItemGroup(item_id=iid, group_id=new.id))
        for child in children.get(src_id, []):
            if child not in path:  # cycle-safe
                clone(child, new.id, path | {src_id})
        return new.id

    new_id = clone(group_id, new_parent_id, frozenset())
    clone_root = s.get(Group, new_id)
    ctx.log(action=actions.DUPLICATE_GROUP, entity_type="group",
            entity_id=new_id,
            summary="Duplicated group “{name}”",
            summary_vars={"name": clone_root.name if clone_root else ""},
            # The whole clone is ONE event: its subtree is a copy nobody has
            # touched yet, so undoing the duplicate means taking all of it
            # down again — the `delete_group` reading, not `create_group`'s.
            data={"group_id": new_id,
                  "group_name": clone_root.name if clone_root else "",
                  "source_group_id": group_id,
                  "parent_id": new_parent_id})
    return new_id


def bulk_membership(ctx: Ctx, item_ids: list[int], add: list[int],
                    remove: list[int], *,
                    events: Optional[list] = None) -> tuple[int, int]:
    """Add/remove many items to/from many groups in one call.

    Semantics mirror `items.add_to_group` / `remove_from_group` EXACTLY: one
    Event per (item, group) CHANGE with the same action and payload shape, so
    History groups them and the revert machinery undoes them identically.
    No-ops are skipped the same way. Only the existence checks are batched
    (one chunked select over the whole item × group grid) — the per-item events
    are unchanged, because the log is the contract.

    **Bulk on purpose:** rewriting this as a loop over the single-item op is
    observably identical and a large silent regression.

    ``events``: a list the caller passes in to collect the Events written —
    what a caller with its OWN undo needs (the tag grid answers a card by
    writing tags and groups together and takes the lot back with one press).
    Nothing else changes; the events are logged either way.
    """
    from . import smartgroups

    s = ctx.session
    add_ids = list(dict.fromkeys(add))
    remove_ids = list(dict.fromkeys(remove))
    item_ids = list(dict.fromkeys(item_ids))
    gids = set(add_ids) | set(remove_ids)
    if not item_ids or not gids:
        return 0, 0
    smartgroups.ensure_assignable(ctx, sorted(gids))
    groups = {g.id: g for chunk in chunked(sorted(gids))
              for g in s.execute(
                  select(Group).where(Group.id.in_(chunk))).scalars().all()}
    # The whole item × group membership grid in chunked selects, instead of a
    # SELECT per pair.
    member: set[tuple[int, int]] = set()
    for chunk in chunked(item_ids):
        member.update(
            (iid, gid) for iid, gid in s.execute(
                select(ItemGroup.item_id, ItemGroup.group_id).where(
                    ItemGroup.item_id.in_(chunk),
                    ItemGroup.group_id.in_(sorted(gids)))
            ).all())

    def _name(gid: int) -> str:
        g = groups.get(gid)
        return g.name if g else ""

    added = removed = 0
    for iid in item_ids:
        for gid in add_ids:
            if (iid, gid) in member:
                continue  # already a member — the single op logs nothing
            s.add(ItemGroup(item_id=iid, group_id=gid))
            member.add((iid, gid))
            ev = ctx.log(action=actions.ADD_TO_GROUP, entity_type="item",
                    entity_id=iid,
                    summary="Added item #{item} to group “{group}”",
                    summary_vars={"item": iid, "group": _name(gid) or gid},
                    data={"item_id": iid, "group_id": gid,
                          "group_name": _name(gid)})
            if events is not None and ev is not None:
                events.append(ev)
            added += 1
        for gid in remove_ids:
            if (iid, gid) not in member:
                continue  # not a member — the single op logs nothing
            s.execute(delete(ItemGroup).where(
                ItemGroup.item_id == iid, ItemGroup.group_id == gid))
            member.discard((iid, gid))
            ev = ctx.log(action=actions.REMOVE_FROM_GROUP, entity_type="item",
                    entity_id=iid,
                    summary="Removed item #{item} from group “{group}”",
                    summary_vars={"item": iid, "group": _name(gid) or gid},
                    data={"item_id": iid, "group_id": gid,
                          "group_name": _name(gid)})
            if events is not None and ev is not None:
                events.append(ev)
            removed += 1
    touch_items(s, item_ids)
    return added, removed
