"""Flip-direction for original->derived (edit) links, including re-rooting."""

from __future__ import annotations

from sqlalchemy import select

from media_compost.db import Item, Relationship, RelationshipTag
from media_compost.ops import ctx_for, links as ops_links
from media_compost.ui.server.routers.relationships import (
    item_relationships,
    link_tags,
)


def _rel(s, frm, to) -> Relationship:
    r = Relationship(from_item_id=frm, to_item_id=to, kind="edit", meta="")
    s.add(r)
    s.flush()
    return r


def _originals(s) -> dict[int, int]:
    """derived_item_id -> original_item_id for every edit link."""
    return {
        r.to_item_id: r.from_item_id
        for r in s.execute(
            select(Relationship).where(Relationship.kind == "edit")
        ).scalars()
    }


def test_flip_rewires_direction_and_reroots_cluster(lib):
    cfg, db, store = lib
    with db.session() as s:
        a, b, c = Item(name="A"), Item(name="B"), Item(name="C")
        s.add_all([a, b, c])
        s.flush()
        # A is the original of both B and C.
        rel_ab = _rel(s, a.id, b.id)
        _rel(s, a.id, c.id)
        s.flush()

        # Flip A->B: B becomes the new original of the whole cluster.
        ops_links.flip(ctx_for(s), rel_ab.id)
        s.flush()

        # B is now the original of both A and C; A is no longer anyone's original.
        assert _originals(s) == {a.id: b.id, c.id: b.id}
        assert s.execute(
            select(Relationship).where(
                Relationship.from_item_id == a.id, Relationship.kind == "edit"
            )
        ).first() is None


def test_flip_avoids_duplicate_when_new_original_was_a_sibling(lib):
    cfg, db, store = lib
    with db.session() as s:
        a, b = Item(name="A"), Item(name="B")
        s.add_all([a, b])
        s.flush()
        rel_ab = _rel(s, a.id, b.id)
        s.flush()

        ops_links.flip(ctx_for(s), rel_ab.id)
        s.flush()

        # Exactly one edge remains: B -> A (no duplicate/self-loop).
        rels = s.execute(
            select(Relationship).where(Relationship.kind == "edit")
        ).scalars().all()
        assert len(rels) == 1
        assert (rels[0].from_item_id, rels[0].to_item_id) == (b.id, a.id)


def test_link_tags_add_remove_and_autocomplete(lib):
    cfg, db, store = lib
    with db.session() as s:
        a, b, c = Item(name="A"), Item(name="B"), Item(name="C")
        s.add_all([a, b, c])
        s.flush()
        r1 = _rel(s, a.id, b.id)
        r2 = _rel(s, a.id, c.id)
        s.flush()

        # Adding is idempotent and returns the link's tags (sorted).
        assert ops_links.add_meta_tag(ctx_for(s), r1.id, "cropped") == ["cropped"]
        assert ops_links.add_meta_tag(ctx_for(s), r1.id, "cropped") == ["cropped"]
        assert ops_links.add_meta_tag(ctx_for(s), r1.id, "edited") == ["cropped", "edited"]
        ops_links.add_meta_tag(ctx_for(s), r2.id, "cropped")
        s.flush()

        # Autocomplete = distinct names (persisted, so unused ones stay too).
        assert link_tags(s) == ["cropped", "edited"]

        # Link tags are no longer auto-deleted when unused: removing "edited"
        # from its only link keeps it in the autocomplete list (usable again).
        ops_links.remove_meta_tag(ctx_for(s), r1.id, "edited")
        s.flush()
        assert link_tags(s) == ["cropped", "edited"]
        ops_links.remove_meta_tag(ctx_for(s), r1.id, "cropped")
        s.flush()
        assert link_tags(s) == ["cropped", "edited"]  # still on r2, edited persists


def test_link_tag_names_normalized(lib):
    cfg, db, store = lib
    with db.session() as s:
        a, b = Item(name="A"), Item(name="B")
        s.add_all([a, b])
        s.flush()
        r = _rel(s, a.id, b.id)
        s.flush()
        # Mixed case + spaces are normalized to lowercase-with-underscores.
        assert ops_links.add_meta_tag(ctx_for(s), r.id, "Big Crop") == ["big_crop"]
        assert link_tags(s) == ["big_crop"]


def test_link_tags_cascade_on_relationship_delete(lib):
    cfg, db, store = lib
    with db.session() as s:
        a, b = Item(name="A"), Item(name="B")
        s.add_all([a, b])
        s.flush()
        r = _rel(s, a.id, b.id)
        s.flush()
        ops_links.add_meta_tag(ctx_for(s), r.id, "variant")
        s.flush()
        s.delete(r)
        s.flush()
        assert s.execute(select(RelationshipTag)).first() is None


def test_relationship_boxes_surface_from_meta(lib):
    """A link's bounding boxes (panel ``box`` or an explicit ``boxes`` list) are
    surfaced on the ``RelationshipOut.boxes`` field for the outgoing item."""
    import json

    cfg, db, store = lib
    with db.session() as s:
        a, b = Item(name="A"), Item(name="B")
        s.add_all([a, b])
        s.flush()
        s.add(Relationship(
            from_item_id=a.id, to_item_id=b.id, kind="panel",
            meta=json.dumps({"index": 0, "box": [0.1, 0.2, 0.3, 0.4]}),
        ))
        s.flush()
        out = item_relationships(a.id, s)
        assert len(out) == 1
        assert out[0].outgoing is True
        assert [(bx.x, bx.y, bx.w, bx.h) for bx in out[0].boxes] == [(0.1, 0.2, 0.3, 0.4)]


def test_linking_bumps_modified_timestamp(lib):
    """Adding/removing a link bumps both items' modification timestamp (which
    surfaces as the 'Modified' metadata field)."""
    import time

    cfg, db, store = lib
    with db.session() as s:
        a, b = Item(name="A"), Item(name="B")
        s.add_all([a, b])
        s.commit()
        aid, bid = a.id, b.id
    # Read the baseline back from the DB (SQLite round-trips as naive datetimes).
    with db.session() as s:
        before = s.get(Item, aid).updated_at
    time.sleep(0.01)
    with db.session() as s:
        ops_links.create(ctx_for(s), aid, bid, kind="manual")
        s.commit()
    with db.session() as s:
        assert s.get(Item, aid).updated_at > before
        assert s.get(Item, bid).updated_at > before
