"""One item's COMPLETE state as a plain dict — uids, names and per-item
file numbers, never database ids.

This is the transfer format the ``merge-library`` command moves items
through: `libimport` serializes each
source item with :func:`item_to_dict` against the SOURCE library's session
and applies the dict to the target. It used to be the ``item.json`` sidecar
each item's folder carried; the files are gone (owner decision, 2026-08 —
they were unused and their upkeep was measured at 72 s of catalog builds per
12 s of import on a large library), and the dict now carries only what is
DIRECTLY attached to the item: the item's own tag assignments by NAME, its
group memberships as uid/name refs, and never an implied tag, an embedded
definition or an ancestor chain. The tag set — tag defs, implications,
group tree, records, rankings — travels separately, read straight from the
source library's database, which is a strictly fuller answer than the old
embedded defs ever were.

Keys keep their meaning between builds; cross-references are item/group/
sequence uids, per-item file numbers and tag names.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import faces as facelib
from . import ocr as ocrlib
from .db import (
    Caption,
    Face,
    File,
    FileArtifact,
    FileMetadata,
    FileName,
    Group,
    GroupTag,
    Item,
    ItemGroup,
    ItemMetaMute,
    ItemMetaPin,
    ItemMetadata,
    ItemTag,
    ItemTagBox,
    ItemTagGroup,
    ItemTagGroupTag,
    ItemTagPlacement,
    ItemFaceRun,
    ItemLocation,
    ItemOccasionDismissal,
    ItemPlaceDismissal,
    ItemSubject,
    ItemSubjectBox,
    ItemTextRun,
    FaceOutline, FaceRejection,
    Location,
    Occasion,
    Ranking,
    RankingDismissal,
    RankingJudgment,
    RankingPool,
    Relationship,
    CaptionRef,
    CaptionTag,
    RelationshipTag,
    Sequence,
    SequenceItem,
    Subject,
    Tag,
    TextRegion,
    TrashedItem,
    chunked,
)
from . import tagname


class ItemDictCatalog:
    """The small cross-table lookups ``item_to_dict`` consults, loaded once
    per write batch: who each subject is (an appearance or face names its
    person), the group uid/name refs a membership entry needs, which groups
    are SMART (their derived memberships stay out of item.json), the
    sequence uid map, and the ranking NAMES (a judgment names its ranking
    by name — the portable identity a person chose).

    THE TAG CATALOG IS DELIBERATELY NOT HERE ANY MORE. It used to be — every
    tag row as an ORM entity, plus the implication edges — because item.json
    embedded each used tag's definition and its ancestor chain. Loading it
    cost ~0.42 s per batch at a 100k-tag catalog, and during a live import
    the writer drains small batches continuously: measured on a seeded 1.2M
    library, 159 batches spent 72 s building this object for 12 s of actual
    import work, and the builds held the GIL hard enough to stretch the
    importer's own 10 ms writes to seconds. Item sidecars carry only what is
    DIRECTLY attached to the item now (owner decision, 2026-08), so the only
    tag names a sidecar needs are the item's own — one indexed join per
    item, not the tag set.
    """

    def __init__(self, session: Session):
        # Subjects: tag -> subject (appearances hang off the item's tags) and
        # subject -> the NAME a sidecar refers to them by (the identity tag's
        # name, else the display name a nameless cluster has).
        self.subject_id_by_tag: dict[int, int] = {}
        self.subject_name_by_id: dict[int, str] = {}
        sub_rows = session.execute(
            select(Subject.id, Subject.tag_id, Subject.display_name)
        ).all()
        tag_name: dict[int, str] = {}
        for chunk in chunked(sorted({tid for _s, tid, _n in sub_rows
                                     if tid is not None})):
            tag_name.update(session.execute(
                select(Tag.id, Tag.name).where(Tag.id.in_(chunk))).all())
        for sid, tid, disp in sub_rows:
            if tid is not None:
                self.subject_id_by_tag[tid] = sid
                self.subject_name_by_id[sid] = tag_name.get(tid) or (disp or "")
            else:
                # An unnamed subject (a face cluster) has neither tag nor name:
                # the cluster is a working state, not a fact about the picture.
                self.subject_name_by_id[sid] = disp or ""
        # Groups: the uid/name REF a membership entry writes, and which
        # groups are smart (their memberships are derived and stay out —
        # the score-tag rule; `ops/smartgroups`).
        self.group_ref: dict[int, tuple[str, str]] = {}
        self.smart_group_ids: set[int] = set()
        for gid, uid, name, smart in session.execute(
            select(Group.id, Group.uid, Group.name, Group.smart_query)
        ).all():
            self.group_ref[gid] = (uid, name)
            if smart is not None:
                self.smart_group_ids.add(gid)
        self.seq_uid: dict[int, str] = dict(session.execute(
            select(Sequence.id, Sequence.uid)
        ).all())
        # A judgment names its ranking by NAME, the portable identity —
        # the `prefix` it used until a ranking stopped owning a tag
        # namespace (rung v31), and what a person chose in either case.
        self.ranking_names: set[str] = set()
        self.ranking_name_by_id: dict[int, str] = {}
        for rid, name in session.execute(
            select(Ranking.id, Ranking.name)
        ).all():
            if not name:
                continue
            self.ranking_names.add(name)
            self.ranking_name_by_id[rid] = name
        # A judgment's POOL travels by NAME (the unnamed one by omission,
        # so a single-pool library's dict is what it always was).
        self.ranking_pool_name_by_id: dict[int, str] = dict(
            session.execute(select(RankingPool.id, RankingPool.name)
                            ).all()) if self.ranking_names else {}


def _appearances_of(catalog: ItemDictCatalog, by_subject: dict,
                    tag_id: int, boxes: dict | None = None) -> list[dict] | None:
    """The item's appearances of whoever this tag is that are NOT at a face.

    `None` for a tag that is not somebody, so an ordinary tag's entry keeps
    exactly the shape it had.

    Only the face-less ones, because an appearance at a face is already written
    under that face, by name — and a reference from here to a face could only
    be an id or a position, neither of which a sidecar is allowed to carry.
    """
    sid = catalog.subject_id_by_tag.get(tag_id)
    if sid is None:
        return None
    out = []
    for r in sorted(by_subject.get(sid, []), key=lambda r: r.id):
        if r.face_id is not None:
            continue
        entry: dict = {"when": ({"date": r.when_date, "age": r.when_age}
                                if (r.when_date is not None
                                    or r.when_age is not None)
                                else None),
                       # The sidebar's drag-reorder — conditional, so an
                       # untouched library writes the bytes it always wrote.
                       **({"position": r.position} if r.position else {})}
        b = (boxes or {}).get(r.id)
        if b is not None:
            entry["box"] = [round(b.x, 6), round(b.y, 6),
                            round(b.w, 6), round(b.h, 6)]
            pts = _points_out(b.points)
            if pts:
                entry["points"] = pts
        out.append(entry)
    return out


def _points_out(points_json: Optional[str]) -> Optional[list]:
    """A box's polygon, as the nested pair list the sidecar writes.

    The DB keeps it as a JSON string (`ItemTagBox.points`); the sidecar spells
    it out so the folder is readable on its own. Conditional at every call
    site — a plain rectangle writes the bytes it always wrote."""
    if not points_json:
        return None
    try:
        pts = json.loads(points_json)
    except (TypeError, ValueError):
        return None
    if not (isinstance(pts, list) and len(pts) >= 3):
        return None
    try:
        return [[round(float(a), 6), round(float(b), 6)] for a, b in pts]
    except (TypeError, ValueError):
        return None


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _edit_lineage(f: File, num_by_fid: dict) -> dict:
    """The ``based_on`` / ``edit_action`` / ``edit_chain`` fields for one file.

    ``edit_chain`` is the stored historical lineage (numbers survive deletions);
    ``based_on`` is the number of the file's *current* live parent (the
    grandparent after a middle file was removed). Empty for imports/rotations."""
    steps = json.loads(f.edit_chain) if f.edit_chain else []
    if not steps:
        return {"based_on": None, "edit_action": "", "edit_chain": []}
    based_on = num_by_fid.get(f.derived_from_file_id) if f.derived_from_file_id else None
    return {"based_on": based_on, "edit_action": steps[-1].get("action", ""),
            "edit_chain": steps}


def item_to_dict(session: Session, item: Item,
                 catalog: ItemDictCatalog | None = None) -> dict:
    """The complete sidecar payload for one item (see the module docstring for
    the stability contract).

    ``catalog`` carries the global catalog reads; a batch builds one and
    passes it to every call, a one-off call builds its own."""
    cat = catalog if catalog is not None else ItemDictCatalog(session)
    files = session.execute(
        select(File).where(File.item_id == item.id)
        .order_by(File.number, File.id)
    ).scalars().all()
    num_by_fid = {f.id: f.number for f in files}

    # ---- files (+ their sources and artifacts) ----
    names_by_file: dict[int, list[dict]] = {}
    arts_by_file: dict[int, list[dict]] = {}
    meta_by_file: dict[int, list[dict]] = {}
    if files:
        fids = [f.id for f in files]
        for fn in session.execute(
            select(FileName).where(FileName.file_id.in_(fids))
            .order_by(FileName.created_at, FileName.id)
        ).scalars().all():
            names_by_file.setdefault(fn.file_id, []).append({
                "name": fn.name, "is_url": bool(fn.is_url),
                "accessed_at": _iso(fn.accessed_at),
            })
        for a in session.execute(
            select(FileArtifact).where(FileArtifact.file_id.in_(fids))
            .order_by(FileArtifact.created_at, FileArtifact.id)
        ).scalars().all():
            arts_by_file.setdefault(a.file_id, []).append({
                "kind": a.kind, "model": a.model or "", "filename": a.path,
                "sha256": a.sha256, "width": a.width, "height": a.height,
                "bytes": a.bytes, "format": a.format, "stale": bool(a.stale),
            })
        # WHAT EACH FILE SAYS ABOUT ITSELF. Read once for the whole item and
        # grouped in Python, never a query per file — the same hoisting rule
        # the catalog reads follow. This is the half a folder round trip used
        # to lose outright: a non-active file's metadata was never read, so
        # re-importing the folder could not restore what was never there.
        for fm in session.execute(
            select(FileMetadata).where(FileMetadata.file_id.in_(fids))
            .order_by(FileMetadata.name)
        ).scalars().all():
            meta_by_file.setdefault(fm.file_id, []).append({
                "name": fm.name, "mtype": fm.mtype,
                "num_value": fm.num_value, "text_value": fm.text_value,
                "raw": fm.raw or "",
            })

    files_out = []
    for f in files:
        # `phash` here is the FILE's own identity hash — what dedup compares, and
        # null for a video. A video's sampled per-frame hashes (VideoFrame) are
        # deliberately NOT written: they are a derived search index over the
        # file's pixels, regenerable by re-scanning it, and there are thousands
        # per film. Same reasoning as thumbnails, which the sidecar also omits.
        entry = {
            "number": f.number, "filename": f.path,
            "sha256": f.sha256, "phash": f.phash,
            # Beside the phash and for the same reason: both are read off the
            # pixels once and never again, and a folder import that dropped
            # them left the library unable to sort by colour or answer
            # `COLORLIKE:` — silently, since nothing about a picture looks
            # wrong when its colour key is missing.
            "color_key": f.color_key, "color_sig": f.color_sig,
            "source_kind": f.source_kind,
            "source_file": num_by_fid.get(f.source_file_id),
            "source_start": f.source_start, "source_end": f.source_end,
            "duration": f.duration, "frame_rate": f.frame_rate,
            "bitrate": f.bitrate,
            "width": f.width, "height": f.height, "bytes": f.bytes,
            "format": f.format,
            "is_derived": bool(f.is_derived),
            "is_kept_original": bool(f.is_kept_original),
            "rotation": int(f.rotation or 0), "mirrored": bool(f.mirrored),
            "crop_x": f.crop_x, "crop_y": f.crop_y,
            "crop_w": f.crop_w, "crop_h": f.crop_h,
            "created_at": _iso(f.created_at),
            "names": names_by_file.get(f.id, []),
            "artifacts": arts_by_file.get(f.id, []),
            "metadata": meta_by_file.get(f.id, []),
        }
        entry.update(_edit_lineage(f, num_by_fid))
        files_out.append(entry)

    # ---- tags (the item's OWN assignments, and nothing implied) ----
    # Only what is directly attached to the item: the tag NAME, the
    # assignment's state, its placements and boxes, and the appearances of
    # whoever the tag is. No embedded definitions, no ancestor chains, no
    # group-granted entries — a tag entailed by another tag or granted by a
    # group is the resolver's answer, not a fact recorded on this picture
    # (owner decision, 2026-08; older folders carried all three, marked
    # `assigned: parent|group`, which the reader still skips by that key).
    tag_group_names = {
        g.id: g.name for g in session.execute(
            select(ItemTagGroup).where(ItemTagGroup.item_id == item.id)
        ).scalars().all()
    }
    # Every appearance in this item, by subject — the dates the tag list shows
    # and the faces refer to. Read once here rather than per row.
    appearances: dict[int, list[ItemSubject]] = {}
    for row in session.execute(
        select(ItemSubject).where(ItemSubject.item_id == item.id)
    ).scalars().all():
        appearances.setdefault(row.subject_id, []).append(row)
    # Each appearance's SUBJECT BOX — a rectangle somebody drew, so it rides
    # like the face boxes do. CONDITIONAL per entry, so an item without one
    # writes the bytes it always wrote.
    appearance_boxes = {b.item_subject_id: b for b in session.execute(
        select(ItemSubjectBox)
        .join(ItemSubject, ItemSubject.id == ItemSubjectBox.item_subject_id)
        .where(ItemSubject.item_id == item.id)).scalars().all()}
    tags_out: list[dict] = []

    it_tags = session.execute(
        select(ItemTag).where(ItemTag.item_id == item.id)
    ).scalars().all()
    # The item's own tag names — one indexed lookup per item, which is the
    # whole of what serializing an item needs from the tag set now.
    tag_name_by_id: dict[int, str] = {}
    for chunk in chunked(sorted({t.tag_id for t in it_tags})):
        tag_name_by_id.update(session.execute(
            select(Tag.id, Tag.name).where(Tag.id.in_(chunk))).all())
    # One query for the item's placements and one for their boxes, instead of
    # one per tag row and one per placement.
    placements_by_tag: dict[int, list[ItemTagPlacement]] = {}
    for chunk in chunked([t.id for t in it_tags]):
        for p in session.execute(
            select(ItemTagPlacement)
            .where(ItemTagPlacement.item_tag_id.in_(chunk))
            .order_by(ItemTagPlacement.id)
        ).scalars().all():
            placements_by_tag.setdefault(p.item_tag_id, []).append(p)
    boxes_by_placement: dict[int, list[dict]] = {}
    all_placement_ids = [
        p.id for ps in placements_by_tag.values() for p in ps
    ]
    for chunk in chunked(all_placement_ids):
        for b in session.execute(
            select(ItemTagBox).where(ItemTagBox.placement_id.in_(chunk))
            .order_by(ItemTagBox.id)
        ).scalars().all():
            pts = _points_out(b.points)
            boxes_by_placement.setdefault(b.placement_id, []).append(
                {"x": b.x, "y": b.y, "w": b.w, "h": b.h,
                 "time_start": b.time_start, "time_end": b.time_end,
                 "track_id": b.track_id, "negative": b.negative,
                 **({"points": pts} if pts else {})})
    for it_tag in it_tags:
        name = tag_name_by_id.get(it_tag.tag_id)
        if name is None:
            continue
        instances = placements_by_tag.get(it_tag.id) or [None]
        for p in instances:
            tags_out.append({
                "name": name,
                # The INSTANCE's own sign where there is one — the same tag
                # may be positive in one group and negative in another. The
                # key keeps its meaning: an old folder holds the assignment's
                # sign on every entry, which is what every instance meant
                # until placements carried their own.
                "negative": (bool(p.negative) if p is not None
                             else bool(it_tag.negative)),
                "pending": bool(it_tag.pending),
                "group": tag_group_names.get(p.group_id) if p is not None else None,
                "boxes": boxes_by_placement.get(p.id, []) if p is not None else [],
                # Every appearance of this subject in the item — how many
                # times they are in it, and how old in each. None for a tag
                # that is not somebody.
                "appearances": _appearances_of(cat, appearances, it_tag.tag_id,
                                               appearance_boxes),
            })

    # ---- groups (direct memberships only — refs, never definitions) ----
    # SMART memberships are DERIVED (one writer, `ops/smartgroups.rebuild`)
    # and deliberately absent: round-tripping one would bring it back as a
    # manual membership — the score-tag lesson — and excluding them is also
    # what keeps a rebuild from queueing thousands of sidecar rewrites.
    # A membership is uid + name and NOTHING else: the group's icon, colour,
    # parent chain and granted tags are the tag set's business, not this
    # item's (the same owner decision that took the tag definitions out).
    member_gids = {
        gid for gid in session.execute(
            select(ItemGroup.group_id).where(ItemGroup.item_id == item.id)
        ).scalars().all()
        if gid not in cat.smart_group_ids
    }
    groups_out = []
    for gid in sorted(member_gids):
        ref = cat.group_ref.get(gid)
        if ref is not None:
            groups_out.append({"uid": ref[0], "name": ref[1]})

    # ---- per-item tag groups ----
    tg_rows = session.execute(
        select(ItemTagGroup).where(ItemTagGroup.item_id == item.id)
        .order_by(ItemTagGroup.position, ItemTagGroup.id)
    ).scalars().all()
    tg_tags: dict[int, list[str]] = {}
    if tg_rows:
        for gid, tname in session.execute(
            select(ItemTagGroupTag.group_id, ItemTagGroupTag.name)
            .where(ItemTagGroupTag.group_id.in_([g.id for g in tg_rows]))
            .order_by(ItemTagGroupTag.name)
        ).all():
            tg_tags.setdefault(gid, []).append(tname)
    tag_groups_out = [
        {"name": g.name, "position": g.position, "system": bool(g.system),
         # Meta tags by NAME (the sidecar never references DB ids).
         "tags": tg_tags.get(g.id, [])}
        for g in tg_rows
    ]

    # ---- captions ----
    caption_rows = session.execute(
        select(Caption).where(Caption.item_id == item.id)
        .order_by(Caption.position, Caption.id)
    ).scalars().all()
    cap_tags: dict[int, list[str]] = {}
    if caption_rows:
        for cid, tname in session.execute(
            select(CaptionTag.caption_id, CaptionTag.name)
            .where(CaptionTag.caption_id.in_([c.id for c in caption_rows]))
            .order_by(CaptionTag.name)
        ).all():
            cap_tags.setdefault(cid, []).append(tname)
    # An instruction's reference images, in order. Collected here and turned
    # into uids below, where the relationships block already has a lookup.
    cap_refs: dict[int, list[int]] = {}
    if caption_rows:
        for cid, riid in session.execute(
            select(CaptionRef.caption_id, CaptionRef.item_id)
            .where(CaptionRef.caption_id.in_([c.id for c in caption_rows]))
            .order_by(CaptionRef.caption_id, CaptionRef.position, CaptionRef.id)
        ).all():
            cap_refs.setdefault(cid, []).append(riid)

    # ---- sequences ----
    seq_uid = cat.seq_uid
    # One entry per POSITION — an item repeated in a sequence writes each
    # occurrence. Position and id in the order, or two occurrences of one
    # (sequence, item) pair make the file's byte order nondeterministic.
    sequences_out = [
        {"sequence": seq_uid.get(si.sequence_id), "position": si.position}
        for si in session.execute(
            select(SequenceItem).where(SequenceItem.item_id == item.id)
            .order_by(SequenceItem.sequence_id, SequenceItem.position,
                      SequenceItem.id)
        ).scalars().all()
        if si.sequence_id in seq_uid
    ]
    sequence_def = None
    if item.kind == "sequence":
        seq = session.execute(
            select(Sequence).where(Sequence.item_id == item.id)
        ).scalars().first()
        if seq is not None:
            # The uid is what members' `sequences` entries reference.
            sequence_def = {"uid": seq.uid, "name": seq.name, "kind": seq.kind,
                            "source_name": seq.source_name or ""}

    # ---- relationships (with link tags) ----
    rels = session.execute(
        select(Relationship).where(
            (Relationship.from_item_id == item.id)
            | (Relationship.to_item_id == item.id)
        ).order_by(Relationship.id)
    ).scalars().all()
    # Only the handful of items this payload actually points at get a uid
    # lookup — this used to load the whole items table per sidecar.
    referenced = {item.link_item_id}
    for r in rels:
        referenced.add(r.to_item_id if r.from_item_id == item.id
                       else r.from_item_id)
    # An instruction's sources ride on the same lookup rather than a second
    # query per item.
    for ids in cap_refs.values():
        referenced.update(ids)
    referenced.discard(None)
    uid_by_item: dict[int, str] = {}
    for chunk in chunked(referenced):
        uid_by_item.update(session.execute(
            select(Item.id, Item.uid).where(Item.id.in_(chunk))
        ).all())
    tags_by_rel: dict[int, list[str]] = {}
    for chunk in chunked([r.id for r in rels]):
        for rid, name in session.execute(
            select(RelationshipTag.relationship_id, RelationshipTag.name)
            .where(RelationshipTag.relationship_id.in_(chunk))
            .order_by(RelationshipTag.name)
        ).all():
            tags_by_rel.setdefault(rid, []).append(name)
    rels_out = []
    for r in rels:
        outgoing = r.from_item_id == item.id
        other_id = r.to_item_id if outgoing else r.from_item_id
        other_uid = uid_by_item.get(other_id)
        if other_uid is None:
            continue
        rels_out.append({
            "direction": "out" if outgoing else "in",
            "other": other_uid, "kind": r.kind, "meta": r.meta or "",
            # Meta tags by NAME alone: the comment is the namespace's own
            # definition, which item sidecars no longer embed.
            "link_tags": tags_by_rel.get(r.id, []),
        })

    # Captions, now that the uid lookup exists: an instruction's refs travel as
    # uids in order, like every other cross-reference here. A ref whose item is
    # not in this library resolves to nothing and is skipped, exactly as an
    # unresolvable relationship end is.
    captions_out = [
        {"text": c.text, "position": c.position,
         "kind": c.kind or "caption",
         "pending": bool(c.pending),
         "model": c.model or "", "edited": bool(c.edited),
         # Meta tags by NAME (the sidecar never references DB ids).
         "tags": cap_tags.get(c.id, []),
         "refs": [u for u in (uid_by_item.get(i)
                              for i in cap_refs.get(c.id, [])) if u]}
        for c in caption_rows
    ]

    # ---- indexed metadata ----
    # DERIVED now — this is what the item's ACTIVE file says, less what the
    # item mutes, rebuilt from `files[].metadata` and `meta_mutes` below. It is
    # still written, for two reasons: a key never changes meaning, and an older
    # build reading a folder this one wrote knows only this block. `libimport`
    # prefers the per-file blocks when they are there and falls back to this
    # one, which is what makes a folder from EITHER build restore correctly.
    def _values(rows) -> list[dict]:
        return [
            {"name": m.name, "mtype": m.mtype, "num_value": m.num_value,
             "text_value": m.text_value, "raw": m.raw or ""}
            for m in rows
        ]

    metadata_out = _values(session.execute(
        select(ItemMetadata).where(ItemMetadata.item_id == item.id)
        .order_by(ItemMetadata.name)
    ).scalars().all())
    # The item's OWN answers, and they are the half a round trip must keep:
    # a pin and a mute are decisions somebody made about which of several
    # files to believe, recoverable from no file's bytes. Same class as
    # `Item.taken_at`, which the round-trip audit already names.
    pin_rows = session.execute(
        select(ItemMetaPin).where(ItemMetaPin.item_id == item.id)
        .order_by(ItemMetaPin.name, ItemMetaPin.raw)
    ).scalars().all()
    pins_out = [
        # `source_file` is the per-item file NUMBER, never a database id —
        # provenance for the Info tab's "promoted from file 2" line.
        dict(v, source_file=num_by_fid.get(p.source_file_id))
        for p, v in zip(pin_rows, _values(pin_rows))
    ]
    mutes_out = sorted(m for (m,) in session.execute(
        select(ItemMetaMute.name).where(ItemMetaMute.item_id == item.id)
    ).all())

    # ---- faces ----
    # A face is worth carrying: the box, who it is, who played them and when —
    # all expensive to establish, and an item folder is meant to be
    # self-contained. `libimport` reads every one of these back. The
    # DESCRIPTOR is not — it is a few kilobytes of floats regenerable from the
    # picture itself, and it is meaningless outside the model that made it, so
    # only the names of the models that have one are written.
    face_rows = list(session.execute(
        select(Face).where(Face.item_id == item.id).order_by(Face.id)
    ).scalars().all())
    face_vectors = facelib.embeddings_of(session, [f.id for f in face_rows])
    faces_by_face: dict[int, list[ItemSubject]] = {}
    for rows in appearances.values():
        for r in rows:
            if r.face_id is not None:
                faces_by_face.setdefault(r.face_id, []).append(r)
    face_outlines = {o.face_id: o for o in session.execute(
        select(FaceOutline).where(
            FaceOutline.face_id.in_([f.id for f in face_rows])
        )).scalars().all()} if face_rows else {}
    rejected_by_face: dict[int, set[str]] = {}
    if face_rows:
        for fid, sid in session.execute(
            select(FaceRejection.face_id, FaceRejection.subject_id)
            .where(FaceRejection.face_id.in_([f.id for f in face_rows]))
        ).all():
            name = cat.subject_name_by_id.get(sid, "")
            if name:
                rejected_by_face.setdefault(fid, set()).add(name)
    faces_out = [
        {
            "box": [round(f.x, 6), round(f.y, 6), round(f.w, 6), round(f.h, 6)],
            "det_score": f.det_score,
            # Plural: detectors overlap, their boxes merge, and both are named.
            "models": [m for m in f.model.split(",") if m],
            # Who this face is — by NAME, like everything else a sidecar
            # refers to, and a LIST, because one rectangle can be a character
            # and the actor at once. Each carries its own age.
            "subjects": [
                {"subject": (cat.subject_name_by_id.get(r.subject_id, "")
                             if r.subject_id else ""),
                 "when": ({"date": r.when_date, "age": r.when_age}
                          if (r.when_date is not None or r.when_age is not None)
                          else None),
                 "assigned_by": r.assigned_by or "user",
                 **({"position": r.position} if r.position else {}),
                 **({"box": [round(appearance_boxes[r.id].x, 6),
                             round(appearance_boxes[r.id].y, 6),
                             round(appearance_boxes[r.id].w, 6),
                             round(appearance_boxes[r.id].h, 6)],
                     **({"points": _points_out(appearance_boxes[r.id].points)}
                        if _points_out(appearance_boxes[r.id].points)
                        else {})}
                    if r.id in appearance_boxes else {})}
                for r in sorted(faces_by_face.get(f.id, []), key=lambda r: r.id)
            ],
            "dismissed": bool(f.dismissed),
            # WHO THIS FACE IS NOT. A refusal is an answer somebody gave — the
            # same kind of thing as a dismissal, and lost the same way without
            # it: the next detection run offers the same wrong name again.
            "not": sorted(rejected_by_face.get(f.id, ())),
            # `has_embedding` keeps its meaning (a sidecar key never changes
            # one); `embedded_by` says which spaces, beside it.
            "has_embedding": bool(face_vectors.get(f.id)),
            "embedded_by": sorted((face_vectors.get(f.id) or {}).keys()),
            "file": num_by_fid.get(f.file_id),
            # The face's OUTLINE — drawn by hand, so it rides like the
            # subject boxes do. CONDITIONAL, so a face without one writes the
            # bytes it always wrote.
            **({"outline": {
                "box": [round(face_outlines[f.id].x, 6),
                        round(face_outlines[f.id].y, 6),
                        round(face_outlines[f.id].w, 6),
                        round(face_outlines[f.id].h, 6)],
                **({"points": _points_out(face_outlines[f.id].points)}
                   if _points_out(face_outlines[f.id].points) else {})}}
               if f.id in face_outlines else {}),
        }
        for f in face_rows
    ]

    # THE TEXT READ OFF THE PICTURE, tree and all. The OPPOSITE asymmetry
    # from a face's descriptor: every field here is written, because a
    # corrected string is not regenerable from anything — that somebody fixed
    # the reading is the whole point of keeping it. Nested by parent, refs by
    # file NUMBER, list order = `ord` (one definition of the reading order).
    text_rows = list(session.execute(
        select(TextRegion).where(TextRegion.item_id == item.id)
        .order_by(TextRegion.ord, TextRegion.id)
    ).scalars().all())
    text_children: dict[int, list[TextRegion]] = {}
    for r in text_rows:
        if r.parent_id is not None:
            text_children.setdefault(r.parent_id, []).append(r)

    def _text_out(r: TextRegion) -> dict:
        return {
            "level": r.level,
            "box": [round(r.x, 6), round(r.y, 6),
                    round(r.w, 6), round(r.h, 6)],
            "quad": [[round(p[0], 6), round(p[1], 6)]
                     for p in ocrlib.unpack_quad(r.quad)],
            "text": r.text or "",
            "score": r.score,
            "lang": r.lang or "",
            "models": [m for m in (r.model or "").split(",") if m],
            "dismissed": bool(r.dismissed),
            "edited": bool(r.edited),
            "file": num_by_fid.get(r.file_id),
            "children": [_text_out(c) for c in text_children.get(r.id, [])],
        }

    text_out = [_text_out(r) for r in text_rows if r.parent_id is None]

    # ---- trash state ----
    trash_row = session.execute(
        select(TrashedItem).where(TrashedItem.item_id == item.id)
    ).scalar_one_or_none()
    restore_groups = None
    if trash_row is not None:
        gids = [int(p) for p in trash_row.original_groups.split(",")
                if p.strip().isdigit()]
        uid_by_gid = dict(session.execute(
            select(Group.id, Group.uid).where(Group.id.in_(gids or [0]))
        ).all())
        restore_groups = [uid_by_gid[g] for g in gids if g in uid_by_gid]

    # Which detectors have already LOOKED at this item, whatever they found.
    # An item a model found nothing in has no face to carry the fact, and that
    # is exactly the item a "skip what is already done" sweep must not run
    # again (`ItemFaceRun`).
    face_models = sorted({
        m for m, in session.execute(
            select(ItemFaceRun.model).where(ItemFaceRun.item_id == item.id)
        ).all()
    })
    # …and which text engines (`ItemTextRun`), for the same skip sweep.
    # A text run is per FILE, so `text_runs` carries the pairing (file by
    # NUMBER, like a region's own ref); `text_models` stays beside it as the
    # flat model list it has always been — a sidecar key never changes
    # meaning, and an older reader goes on getting a true (if coarser)
    # answer from it.
    run_rows = session.execute(
        select(ItemTextRun.file_id, ItemTextRun.model)
        .where(ItemTextRun.item_id == item.id)
    ).all()
    text_models = sorted({m for _fid, m in run_rows})
    text_runs = sorted(
        ({"file": num_by_fid.get(fid), "model": m} for fid, m in run_rows),
        key=lambda r: (r["file"] if r["file"] is not None else -1, r["model"]),
    )
    # WHERE THE CAMERA SAID IT WAS, when nobody has named the spot: an unnamed
    # place is pinned to its items directly, having no tag to be assigned by.
    # The named ones are already here as tags.
    pinned = []
    for loc, in session.execute(
        select(Location).join(ItemLocation, ItemLocation.location_id == Location.id)
        .where(ItemLocation.item_id == item.id, Location.tag_id.is_(None))
        .order_by(Location.id)
    ).all():
        pinned.append({"name": loc.name or "",
                       "lat": loc.lat, "lon": loc.lon})
    # "NOT HERE" and "not then" — a suggestion refused for this picture, for
    # good. Keyed on the target and nothing else, so they are named by the
    # target's identity tag.
    dismissed_places = sorted({
        name for name, in session.execute(
            select(Tag.name)
            .join(Location, Location.tag_id == Tag.id)
            .join(ItemPlaceDismissal,
                  ItemPlaceDismissal.location_id == Location.id)
            .where(ItemPlaceDismissal.item_id == item.id)
        ).all()
    })
    dismissed_events = sorted({
        name for name, in session.execute(
            select(Tag.name)
            .join(Occasion, Occasion.tag_id == Tag.id)
            .join(ItemOccasionDismissal,
                  ItemOccasionDismissal.occasion_id == Occasion.id)
            .where(ItemOccasionDismissal.item_id == item.id)
        ).all()
    })

    # THE RATING RECORD: judgments this item is the A-side of (each pair is
    # written once, on one side, like a relationship) and the axes it was
    # marked not applicable to. The ranking travels by NAME and the other
    # item by UID — never ids. The fitted standings are derived from the
    # judgments and deliberately absent; a ranking writes no tags at all.
    judgments_out: list[dict] = []
    if cat.ranking_names:
        j_rows = session.execute(
            select(RankingJudgment)
            .where(RankingJudgment.a_item_id == item.id)
            .order_by(RankingJudgment.id)
        ).scalars().all()
        other_uid: dict[int, str] = {}
        for chunk in chunked(sorted({j.b_item_id for j in j_rows})):
            other_uid.update(session.execute(
                select(Item.id, Item.uid).where(Item.id.in_(chunk))).all())
        for j in j_rows:
            rname = cat.ranking_name_by_id.get(j.ranking_id)
            uid = other_uid.get(j.b_item_id)
            if rname and uid:
                entry = {"ranking": rname, "other": uid,
                         "outcome": j.outcome}
                # The pool, by name — and only a NAMED one: the unnamed
                # first pool is what an entry without the key means.
                pool = cat.ranking_pool_name_by_id.get(j.pool_id, "")
                if pool:
                    entry["pool"] = pool
                judgments_out.append(entry)
    ranking_na = sorted({
        p for p in (
            cat.ranking_name_by_id.get(rid) for rid, in session.execute(
                select(RankingDismissal.ranking_id)
                .where(RankingDismissal.item_id == item.id)).all())
        if p
    })

    out = {
        "uid": item.uid,
        "name": item.name,
        "kind": item.kind,
        "hidden": bool(item.hidden),
        # WHEN THE PICTURE WAS TAKEN, as somebody typed it (or -1 for "there
        # is none"). The other two answers are derived — the file's own EXIF
        # is re-indexed from the bytes, the events' span from the tags — but
        # this one is an override and nothing can recover it.
        "taken_at": item.taken_at,
        "face_models": face_models,
        "locations": pinned,
        "dismissed_places": dismissed_places,
        "dismissed_events": dismissed_events,
        "trashed": trash_row is not None,
        "restore_groups": restore_groups,
        "created_at": _iso(item.created_at),
        "last_imported_at": _iso(item.last_imported_at),
        "updated_at": _iso(item.updated_at),
        "active_file": num_by_fid.get(item.active_file_id),
        "main_sequence": seq_uid.get(item.main_sequence_id),
        "link": uid_by_item.get(item.link_item_id),
        "sequence_def": sequence_def,
        "files": files_out,
        "captions": captions_out,
        "tag_groups": tag_groups_out,
        "tags": tags_out,
        "groups": groups_out,
        "sequences": sequences_out,
        "relationships": rels_out,
        "metadata": metadata_out,
        "meta_pins": pins_out,
        "meta_mutes": mutes_out,
        "faces": faces_out,
        "text": text_out,
        "text_models": text_models,
        "text_runs": text_runs,
        "ranking_judgments": judgments_out,
        "ranking_na": ranking_na,
    }
    return out
