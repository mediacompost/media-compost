"""Spinning a new item off a source copies its groups, tags and captions.

``copy_item_associations`` is the shared helper used by the background/watermark
"new item" results and by splitting a file into its own item.
"""

from __future__ import annotations

from sqlalchemy import func, select

from media_compost.db import (
    Caption, CaptionTag, Face, FaceEmbedding, File, Group, Item, ItemGroup,
    ItemSubject, ItemTag, ItemTagBox, ItemTagGroup, ItemTagGroupTag,
    ItemTagPlacement, Relationship, RelationshipTag, Subject, Tag,
    copy_item_associations,
)
from media_compost.ops import ctx_for, files as ops_files
from types import SimpleNamespace


def _lib(store):
    return SimpleNamespace(store=store)


def test_copy_item_associations_copies_everything(lib):
    cfg, db, store = lib
    with db.session() as s:
        src = Item(name="src")
        dst = Item(name="dst")
        s.add_all([src, dst])
        s.flush()

        grp = Group(name="G")
        s.add(grp)
        s.flush()
        s.add(ItemGroup(item_id=src.id, group_id=grp.id))

        # A positive tag placed in a named per-item tag group, carrying a box.
        tg = ItemTagGroup(item_id=src.id, name="Person A", position=0)
        s.add(tg)
        s.flush()
        # ...and a meta tag on the grouping itself.
        s.add(ItemTagGroupTag(group_id=tg.id, name="main character"))
        dog = Tag(name="dog")
        cat = Tag(name="cat")
        s.add_all([dog, cat])
        s.flush()
        it_dog = ItemTag(item_id=src.id, tag_id=dog.id, negative=False, pending=True)
        s.add(it_dog)
        s.flush()
        p = ItemTagPlacement(item_tag_id=it_dog.id, group_id=tg.id)
        s.add(p)
        s.flush()
        s.add(ItemTagBox(placement_id=p.id, x=0.1, y=0.2, w=0.3, h=0.4))
        # A negative timed range with a track — the box-level shape that used
        # to be dropped by the copy.
        s.add(ItemTagBox(placement_id=p.id, time_start=1.0, time_end=2.0,
                         negative=True, track_id=7))
        # A negative, ungrouped tag.
        it_cat = ItemTag(item_id=src.id, tag_id=cat.id, negative=True)
        s.add(it_cat)
        s.flush()
        s.add(ItemTagPlacement(item_tag_id=it_cat.id, group_id=None))
        # A caption with provenance/flags.
        s.add(Caption(item_id=src.id, text="a caption", position=0, pending=True,
                      model="joycaption:descriptive"))
        s.flush()

        copy_item_associations(s, src.id, dst.id)
        s.flush()

        # Group membership.
        assert s.execute(select(ItemGroup.group_id).where(
            ItemGroup.item_id == dst.id)).scalars().all() == [grp.id]

        # The per-item tag group is recreated with a NEW id.
        dst_tgs = s.execute(select(ItemTagGroup).where(
            ItemTagGroup.item_id == dst.id)).scalars().all()
        assert len(dst_tgs) == 1
        assert dst_tgs[0].name == "Person A" and dst_tgs[0].id != tg.id
        assert s.execute(select(ItemTagGroupTag.name).where(
            ItemTagGroupTag.group_id == dst_tgs[0].id)).scalars().all() \
            == ["main character"]

        # Both tags copied with their polarity + pending flag.
        dst_tags = {t.tag_id: t for t in s.execute(
            select(ItemTag).where(ItemTag.item_id == dst.id)).scalars().all()}
        assert set(dst_tags) == {dog.id, cat.id}
        assert dst_tags[dog.id].negative is False and dst_tags[dog.id].pending is True
        assert dst_tags[cat.id].negative is True

        # The dog placement points at the NEW tag group and keeps its box.
        p_dog = s.execute(select(ItemTagPlacement).where(
            ItemTagPlacement.item_tag_id == dst_tags[dog.id].id)).scalars().one()
        assert p_dog.group_id == dst_tgs[0].id
        boxes = s.execute(select(ItemTagBox).where(
            ItemTagBox.placement_id == p_dog.id)).scalars().all()
        geo = next(b for b in boxes if b.x is not None)
        assert (geo.x, geo.y, geo.w, geo.h) == (0.1, 0.2, 0.3, 0.4)
        timed = next(b for b in boxes if b.time_start is not None)
        assert (timed.time_start, timed.time_end) == (1.0, 2.0)
        assert timed.negative is True and timed.track_id == 7
        # The cat placement stays ungrouped.
        p_cat = s.execute(select(ItemTagPlacement).where(
            ItemTagPlacement.item_tag_id == dst_tags[cat.id].id)).scalars().one()
        assert p_cat.group_id is None

        # Caption copied with its flags.
        caps = s.execute(select(Caption).where(
            Caption.item_id == dst.id)).scalars().all()
        assert len(caps) == 1
        assert caps[0].text == "a caption" and caps[0].pending is True
        assert caps[0].model == "joycaption:descriptive"

        # The source is untouched — this is a copy, not a move.
        assert s.execute(select(func.count()).select_from(ItemTag).where(
            ItemTag.item_id == src.id)).scalar_one() == 2
        assert s.execute(select(func.count()).select_from(Caption).where(
            Caption.item_id == src.id)).scalar_one() == 1


def test_split_copies_group_tag_and_caption(lib):
    cfg, db, store = lib
    with db.session() as s:
        item = Item(name="orig")
        s.add(item)
        s.flush()
        f1 = File(item_id=item.id, sha256="c" * 64, width=100, height=100,
                  bytes=10, format="png", source_kind="stored", path="p")
        f2 = File(item_id=item.id, sha256="d" * 64, width=100, height=100,
                  bytes=10, format="png", source_kind="stored", path="q")
        s.add_all([f1, f2])
        s.flush()
        item.active_file_id = f1.id
        grp = Group(name="G")
        tag = Tag(name="dog")
        s.add_all([grp, tag])
        s.flush()
        s.add(ItemGroup(item_id=item.id, group_id=grp.id))
        it = ItemTag(item_id=item.id, tag_id=tag.id)
        s.add(it)
        s.flush()
        s.add(ItemTagPlacement(item_tag_id=it.id, group_id=None))
        s.add(Caption(item_id=item.id, text="hi", position=0))
        s.flush()

        new_id = ops_files.split(ctx_for(s, _store=store), f2.id)
        s.flush()

        # The split-off item inherits the group, tag and caption.
        assert s.execute(select(ItemGroup.group_id).where(
            ItemGroup.item_id == new_id)).scalars().all() == [grp.id]
        assert s.execute(select(ItemTag.tag_id).where(
            ItemTag.item_id == new_id)).scalars().all() == [tag.id]
        assert s.execute(select(Caption.text).where(
            Caption.item_id == new_id)).scalars().all() == ["hi"]
        # The original keeps them too (copied, not moved).
        assert s.execute(select(Caption.text).where(
            Caption.item_id == item.id)).scalars().all() == ["hi"]


def test_a_copy_carries_the_faces_the_people_and_the_links(lib):
    """"Save to a new item" is a COPY of the item, not a bare new one — so
    everything the library knew about the picture comes with it. Tags,
    captions and groups are covered above; these are the rest, and each was
    missing until the editors started asking for a full copy."""
    cfg, db, store = lib
    with db.session() as s:
        src, dst, other = Item(name="src"), Item(name="dst"), Item(name="other")
        s.add_all([src, dst, other])
        s.flush()
        src.taken_at = 20140705000000

        subject = Subject(display_name="Alice")
        s.add(subject)
        s.flush()
        face = Face(item_id=src.id, x=0.1, y=0.2, w=0.3, h=0.4,
                    det_score=0.9, model="insightface_faces")
        s.add(face)
        s.flush()
        s.add(FaceEmbedding(face_id=face.id, model="insightface_faces",
                            vector=b"\x00\x01\x02\x03"))
        s.add(ItemSubject(item_id=src.id, subject_id=subject.id,
                          face_id=face.id, when_age=12,
                          assigned_by="suggested", match_score=0.87))
        link = Relationship(from_item_id=src.id, to_item_id=other.id,
                            kind="manual", meta="")
        s.add(link)
        s.flush()
        s.add(RelationshipTag(relationship_id=link.id, name="same_scene"))
        cap = Caption(item_id=src.id, text="hi", position=0)
        s.add(cap)
        s.flush()
        s.add(CaptionTag(caption_id=cap.id, name="alt_text"))
        s.flush()

        copy_item_associations(s, src.id, dst.id, links=True)
        s.flush()

        # The face, with its descriptor — a copy whose faces could not cluster
        # would have to be re-detected to be worth anything.
        faces = s.execute(select(Face).where(Face.item_id == dst.id)).scalars().all()
        assert len(faces) == 1 and faces[0].id != face.id
        assert (faces[0].x, faces[0].det_score) == (0.1, 0.9)
        assert s.execute(select(FaceEmbedding.vector).where(
            FaceEmbedding.face_id == faces[0].id)).scalars().one() == b"\x00\x01\x02\x03"

        # …and WHO it is, pointing at the copy's OWN face rather than the
        # original's, which is the one thing a naive copy gets wrong.
        app = s.execute(select(ItemSubject).where(
            ItemSubject.item_id == dst.id)).scalars().one()
        assert app.face_id == faces[0].id
        assert (app.subject_id, app.when_age, app.assigned_by, app.match_score) \
            == (subject.id, 12, "suggested", 0.87)

        # The link, in the same direction, with its meta tag.
        rels = s.execute(select(Relationship).where(
            Relationship.from_item_id == dst.id)).scalars().all()
        assert len(rels) == 1 and rels[0].to_item_id == other.id
        assert s.execute(select(RelationshipTag.name).where(
            RelationshipTag.relationship_id == rels[0].id)).scalars().all() \
            == ["same_scene"]

        # A caption's meta tags, and the capture date somebody typed.
        ncap = s.execute(select(Caption).where(Caption.item_id == dst.id)).scalars().one()
        assert s.execute(select(CaptionTag.name).where(
            CaptionTag.caption_id == ncap.id)).scalars().all() == ["alt_text"]
        assert s.get(Item, dst.id).taken_at == 20140705000000


def test_a_copy_carries_the_text_tree_with_its_parents_remapped(lib):
    """The detected text travels like a face does — it is evidence about the
    picture, and a corrected string is not regenerable from anything. The
    REMAP is the bug this case exists for (`face_map`'s reason): a child must
    point at the COPY's parent, not the original's."""
    from media_compost.db import TextRegion

    cfg, db, store = lib
    with db.session() as s:
        src, dst = Item(name="src"), Item(name="dst")
        s.add_all([src, dst])
        s.flush()
        block = TextRegion(item_id=src.id, level="block", ord=0,
                           x=0.1, y=0.1, w=0.4, h=0.2,
                           quad="0.1,0.1,0.5,0.12,0.5,0.3,0.1,0.28",
                           text="fixed by hand", score=0.9, lang="ja",
                           model="rapidocr_multi", edited=True)
        s.add(block)
        s.flush()
        word = TextRegion(item_id=src.id, parent_id=block.id, level="word",
                          ord=0, x=0.1, y=0.1, w=0.2, h=0.2, text="fixed",
                          model="rapidocr_multi")
        noise = TextRegion(item_id=src.id, level="block", ord=1,
                           x=0.7, y=0.7, w=0.1, h=0.1, text="",
                           model="rapidocr_multi", dismissed=True)
        s.add_all([word, noise])
        s.flush()

        copy_item_associations(s, src.id, dst.id)
        s.flush()

        rows = s.execute(select(TextRegion).where(
            TextRegion.item_id == dst.id).order_by(TextRegion.ord,
                                                   TextRegion.id)
        ).scalars().all()
        assert len(rows) == 3
        nblock = next(r for r in rows if r.level == "block" and r.ord == 0)
        nword = next(r for r in rows if r.level == "word")
        nnoise = next(r for r in rows if r.ord == 1)
        # New rows, and the child points at the COPY's parent.
        assert nblock.id != block.id
        assert nword.parent_id == nblock.id
        # The whole shape: text, correction, quad, score, lang, dismissal.
        assert (nblock.text, nblock.edited, nblock.quad, nblock.score,
                nblock.lang) == ("fixed by hand", True,
                                 "0.1,0.1,0.5,0.12,0.5,0.3,0.1,0.28",
                                 0.9, "ja")
        assert nnoise.dismissed
        # The copy has its own files, so file_id does not travel.
        assert nblock.file_id is None


def test_links_are_only_copied_when_asked(lib):
    """A background-removal result is not "linked to everything the original is
    linked to" — nobody said that. A copy of the item is."""
    cfg, db, store = lib
    with db.session() as s:
        src, dst, other = Item(name="src"), Item(name="dst"), Item(name="other")
        s.add_all([src, dst, other])
        s.flush()
        s.add(Relationship(from_item_id=src.id, to_item_id=other.id,
                           kind="manual", meta=""))
        s.flush()
        copy_item_associations(s, src.id, dst.id)
        s.flush()
        assert s.execute(select(func.count()).select_from(Relationship).where(
            Relationship.from_item_id == dst.id)).scalar() == 0


def test_a_copy_is_not_linked_to_itself(lib):
    """The copy is already related to its source by the edit link the caller
    writes; a second link from the source's own relationships would point it at
    itself."""
    cfg, db, store = lib
    with db.session() as s:
        src, dst = Item(name="src"), Item(name="dst")
        s.add_all([src, dst])
        s.flush()
        s.add(Relationship(from_item_id=src.id, to_item_id=dst.id,
                           kind="edit", meta=""))
        s.flush()
        copy_item_associations(s, src.id, dst.id, links=True)
        s.flush()
        assert s.execute(select(func.count()).select_from(Relationship).where(
            Relationship.from_item_id == dst.id)).scalar() == 0
