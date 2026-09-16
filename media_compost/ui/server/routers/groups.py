"""Group tree CRUD, reparenting and duplication."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_compost.db import (
    Group, GroupParent, GroupTag, ItemGroup, Tag,
)
from media_compost.library import Library
from media_compost.ops import Ctx, groups as ops_groups, search
from media_compost.resolve import Resolver
from .. import viewscope
from ..deps import get_ctx, get_library, get_session
from ..schemas import (
    GroupAssignView,
    GroupBulkMembership,
    GroupCreate,
    GroupDetail,
    GroupDuplicate,
    GroupMerge,
    GroupMove,
    GroupNode,
    GroupTagOut,
    GroupUpdate,
)

router = APIRouter(prefix="/api/groups", tags=["groups"])


def _counts_by_group(s: Session) -> dict[int, int]:
    """Item count per group including its descendant groups — ONE statement.

    It was one indexed ``COUNT(DISTINCT item_id)`` per group over that
    group's subtree, which is a scan of the subtree's memberships per group:
    on a million-item library with 373 groups in a tree the sidebar spent
    **5.3 s** here, most of it re-counting the same rows once per ancestor
    (the roots alone were 350 ms each). The closure is a recursive CTE over
    the edge table — catalog-sized — joined to the memberships once, so
    every group's number falls out of a single grouped pass: 1.0 s for the
    same 373 answers.

    `UNION` rather than `UNION ALL` in the CTE is what keeps it cycle-safe,
    the same property the Python walk it replaces had by remembering what it
    had seen. A group whose subtree holds nothing is simply absent from the
    result and reads 0, exactly as it did.

    Trashed items are NOT excluded here — the badge has always counted them,
    and this is a faster route to the same number, not a new rule.

    CACHED on the library revision, because the CTE is still the tree's whole
    cost and the tree is fetched on every load: at 5,000 groups over 2.3M
    memberships it measured **3.49 s of a 3.80 s `/api/groups`**. The fan-out
    is inherent — every membership is counted once per ANCESTOR, ~11M rows at
    that shape — and the two ways around it are both worse. Summing each
    group's direct count up the tree is not the same number (an item in a
    parent AND a child would count twice, and `count(DISTINCT)` is exactly
    what stops that), and bubbling item-id SETS up the tree is a shape
    already rejected here: the root's set is the library.
    """
    from sqlalchemy import and_, func

    from media_compost.db import Item

    closure = (
        select(Group.id.label("anc"), Group.id.label("desc"))
        .cte("group_closure", recursive=True)
    )
    closure = closure.union(
        select(closure.c.anc, GroupParent.group_id)
        .join(GroupParent, GroupParent.parent_group_id == closure.c.desc)
    )
    rows = s.execute(
        select(closure.c.anc, func.count(func.distinct(ItemGroup.item_id)))
        .select_from(closure)
        .join(ItemGroup, ItemGroup.group_id == closure.c.desc)
        .join(Item, and_(Item.id == ItemGroup.item_id,
                         Item.hidden.is_(False)))
        .group_by(closure.c.anc)
    ).all()
    counts = {int(g): 0 for g in s.execute(select(Group.id)).scalars().all()}
    for gid, cnt in rows:
        counts[int(gid)] = int(cnt)
    return counts


def _tags_by_group(s: Session) -> dict[int, list[GroupTagOut]]:
    """Assigned tags per group (loaded once, so the tree can show them)."""
    names = dict(s.execute(select(Tag.id, Tag.name)).all())
    out: dict[int, list[GroupTagOut]] = {}
    for gt in s.execute(select(GroupTag)).scalars().all():
        nm = names.get(gt.tag_id)
        if nm is None:
            continue
        out.setdefault(gt.group_id, []).append(
            GroupTagOut(name=nm, negative=gt.negative)
        )
    for lst in out.values():
        lst.sort(key=lambda t: (t.negative, t.name))
    return out


@router.get("", response_model=list[GroupNode])
def get_tree(s: Session = Depends(get_session), lib=Depends(get_library)):
    groups = {g.id: g for g in s.execute(select(Group)).scalars().all()}
    children: dict[int, list[int]] = {}
    has_parent: set[int] = set()
    for gid, pid in s.execute(
        select(GroupParent.group_id, GroupParent.parent_group_id)
    ).all():
        children.setdefault(pid, []).append(gid)
        has_parent.add(gid)

    counts = lib.db.cached(s, "group-subtree-counts",
                           lambda: _counts_by_group(s))
    tags_by_group = _tags_by_group(s)

    def build(gid: int, path: frozenset[int]) -> GroupNode:
        g = groups[gid]
        kids = []
        if gid not in path:  # cycle guard
            child_ids = sorted(
                children.get(gid, []), key=lambda i: groups[i].name.lower()
            )
            kids = [build(c, path | {gid}) for c in child_ids]
        return GroupNode(
            id=g.id, name=g.name, icon=g.icon, color=g.color,
            smart=g.smart_query is not None,
            count=counts.get(gid, 0), tags=tags_by_group.get(gid, []),
            children=kids,
        )

    roots = sorted(
        (gid for gid in groups if gid not in has_parent),
        key=lambda i: groups[i].name.lower(),
    )
    return [build(r, frozenset()) for r in roots]


@router.post("", response_model=GroupNode)
def create_group(body: GroupCreate, ctx: Ctx = Depends(get_ctx)):
    g = ops_groups.create(ctx, body.name, icon=body.icon,
                          parent_id=body.parent_id,
                          smart_query=body.smart_query)
    return GroupNode(id=g.id, name=g.name, icon=g.icon,
                     smart=g.smart_query is not None,
                     count=0, children=[])


@router.post("/bulk-membership")
def bulk_membership(body: GroupBulkMembership, ctx: Ctx = Depends(get_ctx)):
    """Add/remove many items to/from many groups in one request.

    Returns ``{"ok": true, "added": n, "removed": n, "event_ids": [...]}``
    (changes, not requests). The ids are what a caller with its OWN undo
    needs — the tag grid answers a card by writing tags and groups together
    and takes the lot back with one press.
    """
    events: list = []
    added, removed = ops_groups.bulk_membership(ctx, body.item_ids, body.add,
                                                body.remove, events=events)
    ctx.session.flush()
    return {"ok": True, "added": added, "removed": removed,
            "event_ids": [e.id for e in events]}


#: How many items one view assignment writes (and commits) at a time. The
#: same figure — and the same reasoning — as the quick-assign view stamp in
#: tags.py: a view can be the whole library, one event per (item, group) is
#: the contract, and a single transaction at that size is minutes of held
#: write lock.
_VIEW_CHUNK = 500


@router.post("/{group_id}/assign-view")
def assign_view(group_id: int, body: GroupAssignView,
                ctx: Ctx = Depends(get_ctx),
                s: Session = Depends(get_session),
                lib: Library = Depends(get_library)):
    """Add every item of a whole VIEW to a group.

    "Create a group from the current items" can aim at the entire library,
    so the browser sends the scope it is showing rather than the ids in it,
    and this resolves it through the very same ``search_filtered`` the grid
    pages through — "everything here" means exactly what the grid is showing
    and cannot drift from it. Written in COMMITTED CHUNKS, like the view
    stamp: the per-item events are unchanged, only the transaction around
    them is cut up.
    """
    if not s.get(Group, group_id):
        raise HTTPException(404, "group not found")
    ids = viewscope.view_ids(s, lib, body)
    added = 0
    for chunk in viewscope.chunks(ids):
        a, _ = ops_groups.bulk_membership(ctx, chunk, [group_id], [])
        added += a
        s.commit()
    return {"ok": True, "added": added, "count": len(ids)}


@router.get("/{group_id}", response_model=GroupDetail)
def get_group(group_id: int, s: Session = Depends(get_session)):
    g = s.get(Group, group_id)
    if not g:
        raise HTTPException(404, "group not found")
    names = dict(s.execute(select(Tag.id, Tag.name)).all())
    tags = [
        GroupTagOut(name=names.get(gt.tag_id, "?"), negative=gt.negative)
        for gt in s.execute(
            select(GroupTag).where(GroupTag.group_id == group_id)
        ).scalars().all()
        if gt.tag_id in names
    ]
    tags.sort(key=lambda t: t.name)
    parent_id = s.execute(
        select(GroupParent.parent_group_id).where(GroupParent.group_id == group_id)
    ).scalar_one_or_none()
    return GroupDetail(
        id=g.id, name=g.name, icon=g.icon, color=g.color,
        smart_query=g.smart_query,
        parent_id=parent_id, tags=tags,
    )


@router.patch("/{group_id}")
def update_group(group_id: int, body: GroupUpdate,
                 ctx: Ctx = Depends(get_ctx)):
    ops_groups.update(ctx, group_id, name=body.name, icon=body.icon,
                      color=body.color, smart_query=body.smart_query)
    return {"ok": True}


@router.delete("/{group_id}")
def delete_group(group_id: int, assign_tags: bool = Query(False),
                 keep_children: bool = Query(False),
                 ctx: Ctx = Depends(get_ctx)):
    """Delete a group; its subtree goes with it unless ``keep_children``,
    which promotes the direct children to this group's own parent instead.
    Two verbs rather than one with a silent rule — see the op."""
    ops_groups.delete_group(ctx, group_id, assign_tags=assign_tags,
                            keep_children=keep_children)
    return {"ok": True}


@router.post("/{group_id}/duplicate")
def duplicate_group(group_id: int, body: GroupDuplicate,
                    ctx: Ctx = Depends(get_ctx)):
    """Deep-copy a group (and its subtree) into fresh groups with new ids."""
    return {"ok": True, "id": ops_groups.duplicate(ctx, group_id,
                                                   body.new_parent_id)}


@router.post("/{group_id}/merge")
def merge_groups(group_id: int, body: GroupMerge, ctx: Ctx = Depends(get_ctx)):
    """Empty the named groups into this one and delete them.

    The DESTINATION is the path id — the row the context menu was opened on —
    so which group survives is the one that was pointed at.
    """
    moved, emptied = ops_groups.merge(ctx, group_id, list(body.source_ids))
    return {"ok": True, "moved": moved, "emptied": emptied}


@router.post("/{group_id}/move")
def move_group(group_id: int, body: GroupMove, ctx: Ctx = Depends(get_ctx)):
    ops_groups.move(ctx, group_id, body.new_parent_id)
    return {"ok": True}
