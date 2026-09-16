"""Relationships between items, and the META-TAG namespace they share.

A relationship is a directed edge with a `kind`: an edit points from the
derived file to what it came from, a panel to its page, a still to its film. A
`manual` one is whatever somebody meant by it.

The meta tags are the confusing part and worth stating plainly: ONE namespace
(`LinkTag` names) serves relationships, captions, per-item tag groups AND the
library's own tags. The table keeps the name `link_tags` and the routes keep
`/api/link-tags` because renaming either would strand every existing library;
the UI says "meta tags". So a rename or a delete here has to rewrite all FOUR
carriers — miss one and the rename strands it.

`META_CARRIERS` is that list, written once: the rename, the delete and the
per-carrier counts all walk it, so a fifth carrier is one entry rather than
three edits that must agree.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from sqlalchemy import select

from ..db import (
    LIB_META, CaptionTag, Item, ItemTagGroupTag, LinkTag, Relationship,
    RelationshipTag, Tag,
    TagMetaTag, chunked, touch_items,
)
from . import actions
from .context import Ctx
from .errors import Invalid, NotFound, Refused

# Relationship kind for original->derived image versions (rotations/flips and
# user edits). Kept in sync with importer._EDIT_KIND.
_EDIT_KIND = "edit"


#: Every table the ONE meta-tag namespace lives in: (model, owner column name,
#: the field its per-carrier count is reported under). The order is the order
#: the counts are listed in the app.
META_CARRIERS = (
    (RelationshipTag, "relationship_id", "links"),
    (CaptionTag, "caption_id", "captions"),
    (ItemTagGroupTag, "group_id", "tag_groups"),
    (TagMetaTag, "tag_id", "tags"),
)


def carrier_scope(table) -> list:
    """The clauses that keep a carrier's rows in the LIBRARY's namespace.

    Three of the four are the library's by construction — a relationship, a
    caption and an item's tag group are the library's or nothing. The fourth
    hangs off a `tags` row, and since the two tag sets became one table
    a tag SET's entries are `tags` rows too, wearing the labels their OWN
    tag set puts on them. So a rename or a delete of the library's meta
    tag has to say it means the library's, or it reaches across into a set
    and rewrites advice nobody asked it to touch.
    """
    if table is TagMetaTag:
        return [TagMetaTag.tag_id.in_(select(Tag.id))]
    return []


def norm_name(name: str) -> str:
    """Link-tag names are lowercased with spaces collapsed to underscores (like
    item tag names, which never contain spaces)."""
    return re.sub(r"\s+", "_", (name or "").strip().lower())


def tags_by_rel(session, rel_ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    if not rel_ids:
        return out
    for rid, name in session.execute(
        select(RelationshipTag.relationship_id, RelationshipTag.name)
        .where(RelationshipTag.relationship_id.in_(rel_ids))
        .order_by(RelationshipTag.name)
    ).all():
        out.setdefault(rid, []).append(name)
    return out


def would_cycle(s, from_id: int, to_id: int) -> bool:
    """True if adding from->to would create a cycle (to can already reach from).

    An iterative frontier walk — one indexed query per hop over shallow
    lineage graphs — instead of loading the whole relationships table per
    link created (the panels job creates one link per panel)."""
    if from_id == to_id:
        return True
    seen: set[int] = set()
    frontier = {to_id}
    while frontier:
        if from_id in frontier:
            return True
        seen |= frontier
        nxt: set[int] = set()
        for chunk in chunked(frontier):
            nxt.update(s.execute(
                select(Relationship.to_item_id)
                .where(Relationship.from_item_id.in_(chunk))
            ).scalars().all())
        frontier = nxt - seen
    return False


def create(ctx: Ctx, from_item_id: int, to_item_id: int, *,
           kind: str = "manual", meta: Optional[dict] = None) -> Relationship:
    s = ctx.session
    if s.get(Item, from_item_id) is None or s.get(Item, to_item_id) is None:
        raise NotFound("item not found", code="item_not_found")
    if would_cycle(s, from_item_id, to_item_id):
        raise Refused("relationship would create a cycle", code="link_cycle")
    existing = s.execute(
        select(Relationship).where(
            Relationship.from_item_id == from_item_id,
            Relationship.to_item_id == to_item_id,
            Relationship.kind == kind,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.meta = json.dumps(meta or {})
        r = existing
    else:
        r = Relationship(
            from_item_id=from_item_id, to_item_id=to_item_id,
            kind=kind, meta=json.dumps(meta or {}),
        )
        s.add(r)
        s.flush()
        # A newly added link is a revertible history change.
        ctx.log(
            action=actions.ADD_LINK, entity_type="item",
            entity_id=from_item_id, summary="Linked two items",
            data={"rel_id": r.id, "from_item_id": r.from_item_id,
                  "to_item_id": r.to_item_id, "kind": r.kind},
        )
    touch_items(s, [r.from_item_id, r.to_item_id])
    return r




def remove(ctx: Ctx, rel_id: int) -> bool:
    s = ctx.session
    r = s.get(Relationship, rel_id)
    if r is not None:
        # Capture the link (and its link-tag names) so the removal can be
        # reverted from the History; deleting it cascades the tags away.
        tag_names = list(s.execute(
            select(RelationshipTag.name).where(RelationshipTag.relationship_id == r.id)
        ).scalars().all())
        ctx.log(
            action=actions.REMOVE_LINK, entity_type="item",
            entity_id=r.from_item_id, summary="Removed a link between two items",
            data={"from_item_id": r.from_item_id, "to_item_id": r.to_item_id,
                  "kind": r.kind, "meta": r.meta or "", "link_tags": tag_names},
        )
        touch_items(s, [r.from_item_id, r.to_item_id])
        s.delete(r)
    return r is not None




def flip(ctx: Ctx, rel_id: int) -> Relationship:
    s = ctx.session
    """Reverse the direction of an original->derived link: the item assumed to be
    the original becomes the derived one and vice versa.

    For an ``edit`` link this also **re-roots** the cluster: every other item that
    was derived from the old original is re-pointed onto the new original, so the
    "one original per item" tree stays consistent (e.g. if A was the original of
    both B and C, flipping A/B makes B the original of A *and* of C).
    """
    r = s.get(Relationship, rel_id)
    if r is None:
        raise NotFound("relationship not found", code="link_not_found")
    old_from, old_to = r.from_item_id, r.to_item_id
    moved: list[int] = []
    dropped: list[dict] = []
    # Reverse this edge: the derived item becomes the new original.
    r.from_item_id, r.to_item_id = old_to, old_from
    if r.kind == _EDIT_KIND:
        siblings = s.execute(
            select(Relationship).where(
                Relationship.from_item_id == old_from,
                Relationship.kind == _EDIT_KIND,
                Relationship.id != r.id,
            )
        ).scalars().all()
        for sib in siblings:
            if sib.to_item_id == old_to:
                # The new original was already recorded as a sibling — drop the
                # now-redundant edge instead of creating a duplicate/self-loop.
                # It is SNAPSHOTTED first: a flip is not its own inverse once
                # it has deleted a row, so the undo has to carry it.
                dropped.append({
                    "from_item_id": sib.from_item_id,
                    "to_item_id": sib.to_item_id,
                    "kind": sib.kind, "meta": sib.meta or "",
                    "tags": [t.name for t in sib.tags],
                })
                s.delete(sib)
            else:
                moved.append(sib.id)
                sib.from_item_id = old_to
    s.flush()
    ctx.log(action=actions.FLIP_LINK, entity_type="item", entity_id=old_to,
            summary="Reversed a link", data={
                "rel_id": r.id, "from_item_id": old_to,
                "to_item_id": old_from, "kind": r.kind,
                # The cluster's other edges follow the new original, so an
                # undo has to walk them home as well.
                "moved_rel_ids": moved, "dropped": dropped})
    return r


# ---- link tags (free-form labels on a relationship) ------------------------



def create_meta_tag(ctx: Ctx, name: str, *, comment: str = "",
                    description: str = "") -> None:
    s = ctx.session
    """Create a link tag by name (used-count 0). Idempotent — a name that
    already exists is left as-is.

    The pair rides along so the New dialog is one call: they are logged by
    `update_meta_tag` as their own events, which is what makes each of them
    separately revertible, exactly as an edit's are."""
    name = norm_name(name)
    if not name:
        raise Invalid("empty tag", code="empty_meta_tag")
    if s.execute(select(LinkTag).where(LinkTag.name == name, LIB_META)).scalar_one_or_none() is None:
        s.add(LinkTag(name=name))
        s.flush()
        ctx.log(
            action=actions.CREATE_META_TAG, entity_type="meta_tag",
            summary="Created meta tag {name}", summary_vars={"name": name},
            data={"name": name},
        )
    if comment or description:
        update_meta_tag(ctx, name, comment=comment or None,
                        description=description or None)




def update_meta_tag(ctx: Ctx, name: str, *, new_name: Optional[str] = None,
                    comment: Optional[str] = None,
                    description: Optional[str] = None) -> None:
    s = ctx.session
    """Rename and/or set the comment of a meta tag (identified by name).

    Renaming rewrites the tag on every relationship, caption AND tag group
    using it; renaming onto an existing meta tag merges the two (a carrier
    holding both keeps a single tag)."""
    # The OLD name is a LOOKUP and is deliberately not normalized: the shared
    # catalog holds names in two spellings (link tags are underscored, caption
    # and tag-group meta tags keep their spaces — "main character" is a real
    # stored name), so folding it would make exactly those unrenamable.
    name = name.strip()
    if not name:
        raise Invalid("empty tag", code="empty_meta_tag")
    if new_name is not None:
        new = norm_name(new_name)
        if new and new != name:

            # Every carrier's sidecar spells the OLD name out; collect them
            # before the rewrite renames the rows out from under the lookup.
            # Rewrite relationship tags, deduping where a relationship already
            # carries the destination name.
            for row in s.execute(
                select(RelationshipTag).where(RelationshipTag.name == name)
            ).scalars().all():
                dup = s.execute(select(RelationshipTag.id).where(
                    RelationshipTag.relationship_id == row.relationship_id,
                    RelationshipTag.name == new,
                )).first()
                if dup:
                    s.delete(row)
                else:
                    row.name = new
            # Captions, tag groups and the library's own tags carry the same
            # namespace — rewrite them the same way, deduping per carrier.
            for table, key, _field in META_CARRIERS[1:]:
                owner = getattr(table, key)
                for crow in s.execute(
                    select(table).where(table.name == name,
                                        *carrier_scope(table))
                ).scalars().all():
                    dup = s.execute(select(table.id).where(
                        owner == getattr(crow, key), table.name == new,
                    )).first()
                    if dup:
                        s.delete(crow)
                    else:
                        crow.name = new
            # Move/merge the persisted comment onto the destination.
            old_lt = s.execute(
                select(LinkTag).where(LinkTag.name == name, LIB_META)
            ).scalar_one_or_none()
            new_lt = s.execute(
                select(LinkTag).where(LinkTag.name == new, LIB_META)
            ).scalar_one_or_none()
            if old_lt is not None:
                if new_lt is not None:
                    if not new_lt.comment and old_lt.comment:
                        new_lt.comment = old_lt.comment
                    s.delete(old_lt)
                else:
                    old_lt.name = new
            s.flush()
            ctx.log(
                action=actions.RENAME_META_TAG,
                entity_type="meta_tag",
                summary="Renamed meta tag {old} → {new}",
                summary_vars={"old": name, "new": new},
                data={"old_name": name, "name": new},
            )
            name = new
    if comment is not None:
        lt = s.execute(
            select(LinkTag).where(LinkTag.name == name, LIB_META)
        ).scalar_one_or_none()
        old_comment = lt.comment if lt is not None else ""
        if lt is None:
            s.add(LinkTag(name=name, comment=comment))
        else:
            lt.comment = comment
        if comment != old_comment:
            ctx.log(
                action=actions.COMMENT_META_TAG,
                entity_type="meta_tag",
                summary=("Commented on meta tag {name}" if comment
                         else "Cleared comment on meta tag {name}"),
                summary_vars={"name": name},
                data={"name": name, "comment": comment,
                      "old_comment": old_comment},
            )
        # The comment is embedded in the sidecars of every relationship
        # endpoint using this link tag (a LinkTag row alone carries no item
        # reference the flush sweep could see).

    if description is not None:
        lt = s.execute(
            select(LinkTag).where(LinkTag.name == name, LIB_META)
        ).scalar_one_or_none()
        old_description = lt.description if lt is not None else ""
        if lt is None:
            s.add(LinkTag(name=name, description=description))
        else:
            lt.description = description
        if description != old_description:
            # Its own event beside the comment's — two fields, and an undo
            # has to know which it is putting back. NO fan-out: a meta tag's
            # description is not embedded in any item.json (its comment is),
            # so nothing goes stale when it changes.
            ctx.log(
                action=actions.DESCRIBE_META_TAG,
                entity_type="meta_tag",
                summary=("Described meta tag {name}" if description.strip()
                         else "Cleared the description on meta tag {name}"),
                summary_vars={"name": name},
                data={"name": name, "description": description,
                      "old_description": old_description},
            )




def delete_meta_tag(ctx: Ctx, name: str) -> None:
    s = ctx.session
    """Delete a meta tag everywhere: remove it from every relationship,
    caption and tag group, and drop its persisted comment."""

    # A lookup, not a write — see update_meta_tag for why it stays verbatim.
    name = name.strip()
    # The name is embedded in every carrier's sidecar; collect them BEFORE the
    # rows that name them are gone.
    # Deleting a meta tag takes it off every link, caption and tag group that
    # carries it — recorded, so the History view shows what it cost and the
    # revert can put the tag back where it was.
    carriers: dict[str, list[int]] = {}
    for table, owner_key, field in META_CARRIERS:
        ids = []
        for row in s.execute(
            select(table).where(table.name == name, *carrier_scope(table))
        ).scalars().all():
            ids.append(getattr(row, owner_key))
            s.delete(row)
        # `relationships` rather than `links` — the payload key the revert
        # reads has said that since the first build, and an event already in a
        # library is not something a rename may reach.
        carriers["relationships" if field == "links" else field] = ids
    lt = s.execute(select(LinkTag).where(LinkTag.name == name, LIB_META)).scalar_one_or_none()
    comment = lt.comment if lt is not None else ""
    if lt is not None:
        s.delete(lt)
    s.flush()
    ctx.log(
        action=actions.DELETE_META_TAG, entity_type="meta_tag",
        summary="Deleted meta tag {name}",
        summary_vars={"name": name},
        data={"name": name, "comment": comment, **carriers},
    )




def add_meta_tag(ctx: Ctx, rel_id: int, name: str) -> list[str]:
    s = ctx.session
    """Add a link tag to a relationship (idempotent). Returns the link's tags."""
    r = s.get(Relationship, rel_id)
    if r is None:
        raise NotFound("relationship not found", code="link_not_found")
    name = norm_name(name)
    if not name:
        raise Invalid("empty tag", code="empty_meta_tag")
    exists = s.execute(
        select(RelationshipTag).where(
            RelationshipTag.relationship_id == rel_id,
            RelationshipTag.name == name,
        )
    ).scalar_one_or_none()
    if exists is None:
        s.add(RelationshipTag(relationship_id=rel_id, name=name))
        # LOGGED, like the same edit on a caption and on a tag group. These two
        # were the only carriers of the one meta-tag namespace that wrote
        # nothing at all: the change landed, the History said nothing, and the
        # sidebar's Undo had no event to offer — which read as the offer being
        # unreliable rather than absent.
        ctx.log(action=actions.ADD_LINK_TAG, entity_type="item",
                entity_id=r.from_item_id,
                summary="Added meta tag “{name}” to a link",
                summary_vars={"name": name},
                data={"item_id": r.from_item_id, "rel_id": rel_id,
                      "name": name})
    # Persist the name so it survives even after its last use is removed (link
    # tags are no longer auto-deleted when unused).
    if s.execute(select(LinkTag).where(LinkTag.name == name, LIB_META)).scalar_one_or_none() is None:
        s.add(LinkTag(name=name))
    s.flush()
    return tags_by_rel(s, [rel_id]).get(rel_id, [])




def remove_meta_tag(ctx: Ctx, rel_id: int, name: str) -> list[str]:
    s = ctx.session
    """Remove a link tag from a relationship. When no relationship uses that name
    anymore it disappears from the autocomplete list automatically."""
    row = s.execute(
        select(RelationshipTag).where(
            RelationshipTag.relationship_id == rel_id,
            RelationshipTag.name == name,
        )
    ).scalar_one_or_none()
    if row is not None:
        r = s.get(Relationship, rel_id)
        s.delete(row)
        if r is not None:
            ctx.log(action=actions.REMOVE_LINK_TAG, entity_type="item",
                    entity_id=r.from_item_id,
                    summary="Removed meta tag “{name}” from a link",
                    summary_vars={"name": name},
                    data={"item_id": r.from_item_id, "rel_id": rel_id,
                          "name": name})
        s.flush()
    return tags_by_rel(s, [rel_id]).get(rel_id, [])
