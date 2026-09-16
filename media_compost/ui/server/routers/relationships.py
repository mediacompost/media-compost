"""Directional relationships between items (original -> derived).

Examples: a video and a clip cut from it ("clip", with a time range), an image
and its edited version ("edit"/"derived"), a video and a frame captured from it
("frame"). Relationships are acyclic; the create endpoint rejects any edge that
would close a cycle.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from media_compost.db import LIB_META, Item, LinkTag, Relationship
from media_compost.ops import Ctx, links as ops_links
from ..deps import get_ctx, get_session
from ..schemas import (
    LinkTagCreate,
    LinkTagDelete,
    LinkTagRow,
    LinkTagUpdate,
    RelationshipCreate,
    RelationshipOut,
    RelationshipTagBody,
)


router = APIRouter(tags=["relationships"])


def _load_meta(text: str) -> dict:
    try:
        val = json.loads(text) if text else {}
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


def _boxes_from_meta(meta: dict) -> list[dict]:
    """Normalize a link's bounding boxes out of its ``meta`` JSON. Accepts a
    ``boxes`` list (of ``{x,y,w,h}`` dicts or ``[x,y,w,h]`` lists) and the legacy
    single ``box`` list (a detected panel's region). Returns ``{x,y,w,h}`` dicts."""
    raw = meta.get("boxes")
    if raw is None and "box" in meta:
        raw = [meta["box"]]
    out: list[dict] = []
    for b in raw or []:
        if isinstance(b, dict):
            vals = (b.get("x"), b.get("y"), b.get("w"), b.get("h"))
        elif isinstance(b, (list, tuple)) and len(b) >= 4:
            vals = tuple(b[:4])
        else:
            continue
        if any(v is None for v in vals):
            continue
        try:
            x, y, w, h = (float(v) for v in vals)
        except (TypeError, ValueError):
            continue
        out.append({"x": x, "y": y, "w": w, "h": h})
    return out


@router.get("/api/items/{item_id}/relationships",
            response_model=list[RelationshipOut])
def item_relationships(item_id: int, s: Session = Depends(get_session)):
    item = s.get(Item, item_id)
    if not item:
        raise HTTPException(404, "item not found")
    rels = s.execute(
        select(Relationship).where(
            (Relationship.from_item_id == item_id)
            | (Relationship.to_item_id == item_id)
        )
    ).scalars().all()
    # Only the handful of items the relationships actually point at — this
    # used to hydrate every Item in the library to label a few neighbours.
    needed = {item_id}
    for r in rels:
        needed.update((r.from_item_id, r.to_item_id))
    names: dict[int, str] = {}
    uids: dict[int, str] = {}
    files: dict[int, Optional[int]] = {}
    for iid, name, uid, af in s.execute(
        select(Item.id, Item.name, Item.uid, Item.active_file_id)
        .where(Item.id.in_(sorted(needed)))
    ).all():
        names[iid], uids[iid], files[iid] = name, uid, af
    tags = ops_links.tags_by_rel(s, [r.id for r in rels])
    out: list[RelationshipOut] = []
    for r in rels:
        outgoing = r.from_item_id == item_id
        other = r.to_item_id if outgoing else r.from_item_id
        meta = _load_meta(r.meta)
        out.append(RelationshipOut(
            id=r.id, from_item_id=r.from_item_id, to_item_id=r.to_item_id,
            other_item_id=other, other_item_uid=uids.get(other, ""),
            other_name=names.get(other, "?"),
            other_file_id=files.get(other), outgoing=outgoing,
            kind=r.kind, meta=meta, boxes=_boxes_from_meta(meta),
            tags=tags.get(r.id, []),
        ))
    return out


def _out(s, r) -> RelationshipOut:
    meta = _load_meta(r.meta)
    return RelationshipOut(
        id=r.id, from_item_id=r.from_item_id, to_item_id=r.to_item_id,
        other_item_id=r.to_item_id, other_name="", outgoing=True,
        kind=r.kind, meta=meta, boxes=_boxes_from_meta(meta),
    )


@router.post("/api/relationships", response_model=RelationshipOut)
def create_relationship(body: RelationshipCreate,
                        ctx: Ctx = Depends(get_ctx)):
    r = ops_links.create(ctx, body.from_item_id, body.to_item_id,
                         kind=body.kind, meta=body.meta)
    return _out(ctx.session, r)


@router.delete("/api/relationships/{rel_id}")
def delete_relationship(rel_id: int, ctx: Ctx = Depends(get_ctx)):
    ops_links.remove(ctx, rel_id)
    return {"ok": True}


@router.post("/api/relationships/{rel_id}/flip", response_model=RelationshipOut)
def flip_relationship(rel_id: int, ctx: Ctx = Depends(get_ctx)):
    """Reverse the direction of an original->derived link."""
    return _out(ctx.session, ops_links.flip(ctx, rel_id))


@router.get("/api/link-tags", response_model=list[str])
def link_tags(s: Session = Depends(get_session)):
    """Meta-tag names for autocomplete: those currently used by a relationship,
    a caption or a tag group, plus any that carry a comment (a persisted
    :class:`LinkTag` row), so a commented-but-unused meta tag still suggests
    itself.

    (The route keeps its /api/link-tags path — links were the first user of
    this namespace; captions and tag groups joined it later and the UI calls
    them all "meta tags".)"""
    names = set(s.execute(
        select(LinkTag.name).where(LIB_META)).scalars().all())
    for table, _key, _field in ops_links.META_CARRIERS:
        names |= set(s.execute(
            select(table.name).where(*ops_links.carrier_scope(table))
            .distinct()).scalars().all())
    return sorted(names)


@router.get("/api/link-tags/rows", response_model=list[LinkTagRow])
def link_tag_rows(s: Session = Depends(get_session)):
    """Every meta tag with its comment and one usage count PER CARRIER —
    relationships, captions, per-item tag groups and the library's own tags —
    plus their total. The data behind the Tags tab's "Meta" mode."""
    per: dict[str, dict[str, int]] = {}
    for table, _key, field in ops_links.META_CARRIERS:
        for name, n in s.execute(
            select(table.name, func.count())
            .where(*ops_links.carrier_scope(table))
            .group_by(table.name)
        ).all():
            per.setdefault(name, {})[field] = n
    comments = dict(s.execute(
        select(LinkTag.name, LinkTag.comment).where(LIB_META)).all())
    descriptions = dict(s.execute(
        select(LinkTag.name, LinkTag.description).where(LIB_META)).all())
    names = set(per) | set(comments)
    rows = [
        LinkTagRow(
            name=n, comment=comments.get(n, ""),
            description=descriptions.get(n, ""),
            count=sum(per.get(n, {}).values()), **per.get(n, {}),
        )
        for n in names
    ]
    rows.sort(key=lambda r: r.name.lower())
    return rows


@router.post("/api/link-tags/create", response_model=list[LinkTagRow])
def create_link_tag(body: LinkTagCreate, ctx: Ctx = Depends(get_ctx)):
    """Create a link tag by name (used-count 0). Idempotent."""
    ops_links.create_meta_tag(ctx, body.name, comment=body.comment,
                              description=body.description)
    return link_tag_rows(ctx.session)


@router.post("/api/link-tags/update", response_model=list[LinkTagRow])
def update_link_tag(body: LinkTagUpdate, ctx: Ctx = Depends(get_ctx)):
    """Rename and/or set the comment of a meta tag (identified by name)."""
    ops_links.update_meta_tag(ctx, body.name, new_name=body.new_name,
                              comment=body.comment,
                              description=body.description)
    return link_tag_rows(ctx.session)


@router.post("/api/link-tags/delete", response_model=list[LinkTagRow])
def delete_link_tag(body: LinkTagDelete, ctx: Ctx = Depends(get_ctx)):
    """Delete a meta tag everywhere."""
    ops_links.delete_meta_tag(ctx, body.name)
    return link_tag_rows(ctx.session)


@router.post("/api/relationships/{rel_id}/tags", response_model=list[str])
def add_link_tag(rel_id: int, body: RelationshipTagBody,
                 ctx: Ctx = Depends(get_ctx)):
    """Add a link tag to a relationship (idempotent). Returns the link's tags."""
    return ops_links.add_meta_tag(ctx, rel_id, body.name)


@router.delete("/api/relationships/{rel_id}/tags/{name}", response_model=list[str])
def remove_link_tag(rel_id: int, name: str, ctx: Ctx = Depends(get_ctx)):
    """Remove a link tag from a relationship."""
    return ops_links.remove_meta_tag(ctx, rel_id, name)
