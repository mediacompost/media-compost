"""The SQL prefilter against the old evaluate-everything semantics.

The oracle below is the PRE-CHANGE ``_search_filtered`` body, frozen: scope
the candidates in Python, build every item's full ``QueryCtx``, evaluate the
FULL tree. Random condition trees over the whole grammar then assert that
``POST /api/items/query`` answers with exactly the oracle's id set, that each
sort token orders pages the way Python-sorting the oracle set does, and that
a fully-exact tree never enters the residue evaluator.
"""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from media_compost import query as q
from media_compost.ui.config import UiConfig
from media_compost.db import (
    Caption, CaptionTag, Face, File, Group, GroupParent, GroupTag, Item,
    ItemGroup, ItemLocation, ItemMetadata, ItemSubject, ItemTag, Location,
    Occasion, Relationship, RelationshipTag, Sequence,
    SequenceItem, Subject, Tag, TagImplication, TagMetaTag, TrashedItem,
    TAKEN_NONE,
)
from media_compost.metadata_catalog import intrinsic_nums, intrinsic_texts
from media_compost.resolve import Resolver, descendant_groups
from media_compost.searchctx import (
    load_caption_sets, load_event_sets, load_face_counts, load_group_sets,
    load_text_counts,
    load_indexed_meta, load_link_sets, load_place_sets, load_similar_sets,
    load_subject_sets, load_tag_meta, load_taken_windows, load_value_sets,
)
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

TAG_NAMES = ["dog", "poodle", "pet", "cat", "outdoor", "portrait",
             "subject:alice", "event:con2020", "place:tokyo",
             # Value tags for `VALUE:` — two heights in DIFFERENT units of one
             # family (the conversion is part of what the oracle checks), a
             # unitless score, and a plain word that shares the namespace and
             # must never match a number.
             "height:172cm", "height:1.9m", "quality:7", "height:tall",
             "tall_marker"]
GROUP_NAMES = ["animals", "trips", "2020", "nested"]


def _file(item, n, w, h, fmt="png", duration=None, fps=None, bitrate=None,
          phash=None, color_sig=None):
    return File(item_id=item.id, number=n, path=f"files/{n}.{fmt}",
                sha256=f"sha-{item.id}-{n}", width=w, height=h,
                bytes=1000 + w, format=fmt, duration=duration,
                frame_rate=fps, bitrate=bitrate,
                phash=phash, color_sig=color_sig)


def _near_phash(i: int) -> str:
    """A 256-bit hash whose distance from its neighbours is small and known.

    Items 0..3 differ from item 0 by 0, 1, 2 and 3 bits, so a `SIMILAR:` with
    a tolerance of 2 has a non-trivial answer to be wrong about. Everything
    past them is far away."""
    base = 0xA5 << 240
    if i < 4:
        return f"{base | ((1 << i) - 1):064x}"
    return f"{(base >> 1) | (0xFFFF << (i % 200)):064x}"


def _seed(s) -> None:
    tags = {n: Tag(name=n) for n in TAG_NAMES}
    s.add_all(tags.values())
    s.flush()
    tags["cat"].alias_of_id = tags["pet"].id
    s.add_all([
        TagImplication(tag_id=tags["poodle"].id, implies_id=tags["dog"].id),
        TagImplication(tag_id=tags["dog"].id, implies_id=tags["pet"].id),
        # A cycle, so the closure walk is exercised.
        TagImplication(tag_id=tags["pet"].id, implies_id=tags["dog"].id),
        # A value tag reached only through an implication — the compiler's
        # tag-set clause must take the same implication step the evaluator's
        # effective tags do.
        TagImplication(tag_id=tags["tall_marker"].id,
                       implies_id=tags["height:1.9m"].id),
    ])
    # What the TAG SET says about a few of them, so `TAG:` conditions have
    # something to resolve to — including a tag carrying TWO marks and one
    # that is only reachable through an implication (`poodle` -> `dog`).
    s.add_all([
        TagMetaTag(tag_id=tags["dog"].id, name="noflip"),
        TagMetaTag(tag_id=tags["portrait"].id, name="noflip"),
        TagMetaTag(tag_id=tags["portrait"].id, name="draft"),
        TagMetaTag(tag_id=tags["outdoor"].id, name="draft"),
    ])
    sub = Subject(tag_id=tags["subject:alice"].id, display_name="Alice",
                  since_date=20100000)
    s.add(sub)
    occ = Occasion(tag_id=tags["event:con2020"].id, display_name="Con 2020",
                   start_date=20200105, end_date=20200110)
    s.add(occ)
    loc = Location(tag_id=tags["place:tokyo"].id, name="Tokyo")
    s.add(loc)
    s.flush()
    pin = Location(tag_id=None, lat=52.5, lon=13.4)
    s.add(pin)

    groups = {n: Group(name=n, uid=f"g-{n}") for n in GROUP_NAMES}
    s.add_all(groups.values())
    s.flush()
    s.add(GroupParent(group_id=groups["nested"].id,
                      parent_group_id=groups["trips"].id))
    s.add(GroupTag(group_id=groups["animals"].id, tag_id=tags["pet"].id,
                   negative=False))
    s.add(GroupTag(group_id=groups["trips"].id, tag_id=tags["outdoor"].id,
                   negative=False))
    s.add(GroupTag(group_id=groups["nested"].id, tag_id=tags["outdoor"].id,
                   negative=True))

    rng = random.Random(7)
    items: list[Item] = []
    for i in range(40):
        it = Item(uid=f"eq-{i:03d}", name=f"Item {i:02d}", kind="image",
                  created_at=datetime(2024, 1 + i % 12, 1 + i % 27, i % 24),
                  last_imported_at=datetime(2025, 1 + i % 12, 1 + i % 27))
        items.append(it)
    items[35].kind = "video"
    items[36].kind = "video"
    s.add_all(items)
    s.flush()
    for i, it in enumerate(items):
        if it.kind == "video":
            f = _file(it, 1, 1920, 1080, "mp4", duration=12.5 + i,
                      fps=24.0, bitrate=4_000_000)
        else:
            f = _file(it, 1, 400 + i * 37 % 1200, 300 + i * 53 % 900,
                      rng.choice(["png", "jpeg", "webp"]),
                      phash=_near_phash(i),
                      color_sig=(0b111 << (i % 40)) & ((1 << 56) - 1))
        s.add(f)
        s.flush()
        it.active_file_id = f.id

    # A sequence container borrowing a member's file.
    cont = Item(uid="eq-seq", name="Chapter", kind="sequence",
                created_at=datetime(2024, 6, 1),
                last_imported_at=datetime(2025, 6, 1))
    s.add(cont)
    s.flush()
    seq = Sequence(uid="seq-eq", name="Chapter", kind="comic", item_id=cont.id)
    s.add(seq)
    s.flush()
    for pos, member in enumerate(items[:5]):
        s.add(SequenceItem(sequence_id=seq.id, item_id=member.id,
                           position=pos + 1))
    cont.active_file_id = items[0].active_file_id
    items.append(cont)

    def tag_of(i):  # varied, deterministic assignments
        return [
            (tags["poodle"], False), (tags["dog"], False),
            (tags["outdoor"], False), (tags["portrait"], False),
            (tags["dog"], True), (tags["pet"], True),
        ][i % 6]

    for i, it in enumerate(items[:40]):
        t, negative = tag_of(i)
        s.add(ItemTag(item_id=it.id, tag_id=t.id, negative=negative,
                      pending=(i % 11 == 0)))
        if i % 4 == 0:
            s.add(ItemGroup(item_id=it.id, group_id=groups["animals"].id))
        if i % 5 == 0:
            s.add(ItemGroup(item_id=it.id, group_id=groups["nested"].id))
        if i % 6 == 0:
            s.add(ItemTag(item_id=it.id, tag_id=tags["subject:alice"].id,
                          negative=False))
        if i % 7 == 0:
            s.add(ItemTag(item_id=it.id, tag_id=tags["event:con2020"].id,
                          negative=False))
        if i % 8 == 0:
            s.add(ItemTag(item_id=it.id, tag_id=tags["place:tokyo"].id,
                          negative=False))
        # Value tags: direct in two units, one NEGATIVE (a negative
        # assignment must not answer a VALUE:), one only implied, and the
        # word that shares the namespace.
        if i % 3 == 0:
            s.add(ItemTag(item_id=it.id, tag_id=tags["height:172cm"].id,
                          negative=(i % 9 == 0)))
        if i % 5 == 2:
            s.add(ItemTag(item_id=it.id, tag_id=tags["tall_marker"].id,
                          negative=False))
        if i % 7 == 3:
            s.add(ItemTag(item_id=it.id, tag_id=tags["quality:7"].id,
                          negative=False))
        if i % 11 == 4:
            s.add(ItemTag(item_id=it.id, tag_id=tags["height:tall"].id,
                          negative=False))
        if i % 9 == 0:
            s.add(ItemLocation(item_id=it.id, location_id=pin.id))
        if i % 5 == 1:
            c = Caption(item_id=it.id, text=f"cap {i}", position=1,
                        pending=(i % 10 == 1))
            s.add(c)
            s.flush()
            if i % 10 != 1:
                s.add(CaptionTag(caption_id=c.id, name="style"))
        if i % 6 == 2:
            s.add(ItemMetadata(item_id=it.id, name="camera", mtype="text",
                               text_value=f"Cam {i % 3}"))
            s.add(ItemMetadata(item_id=it.id, name="iso", mtype="numeric",
                               num_value=float(100 * (i % 5 + 1))))
        if i % 6 == 3:
            s.add(ItemMetadata(item_id=it.id, name="date_taken", mtype="date",
                               num_value=float(20200000000000 + i)))
        if i % 13 == 0:
            it.taken_at = 20190000000000 + i
        if i % 17 == 3:
            it.taken_at = TAKEN_NONE
    s.flush()
    # Subject appearances with dates/ages.
    for i, it in enumerate(items[:40]):
        if i % 6 == 0:
            s.add(ItemSubject(item_id=it.id, subject_id=sub.id,
                              when_date=20200000 + i if i % 12 == 0 else None,
                              when_age=(10 + i % 5) if i % 12 == 6 else None,
                              assigned_by="user"))
    # Relationships with tags.
    for i in range(0, 30, 6):
        r = Relationship(from_item_id=items[i].id, to_item_id=items[i + 1].id,
                         kind="edit")
        s.add(r)
        s.flush()
        if i % 12 == 0:
            s.add(RelationshipTag(relationship_id=r.id, name="crop"))
    # Faces, some named, one dismissed; a suggested appearance for pending.
    for i in (2, 8, 14, 20):
        f = Face(item_id=items[i].id, x=0.1, y=0.1, w=0.2, h=0.2,
                 model="anime_face_magi", dismissed=(i == 20))
        s.add(f)
        s.flush()
        if i in (8, 14):
            s.add(ItemSubject(item_id=items[i].id, subject_id=sub.id,
                              face_id=f.id,
                              assigned_by="suggested" if i == 14 else "user",
                              match_score=0.9 if i == 14 else None))
    # Text regions: without rows the SQL and Python paths would be compared
    # over a column that is always zero — a vacuous equivalence. A child and
    # a dismissed block make the "top-level, live" definition earn its keep.
    from media_compost.db import TextRegion
    for i in (3, 9, 15):
        blk = TextRegion(item_id=items[i].id, level="block", ord=0,
                         x=0.1, y=0.1, w=0.4, h=0.1, text=f"text {i}",
                         model="rapidocr_multi", dismissed=(i == 15))
        s.add(blk)
        s.flush()
        if i == 9:
            s.add(TextRegion(item_id=items[i].id, parent_id=blk.id,
                             level="word", ord=0, x=0.1, y=0.1, w=0.2,
                             h=0.1, text="text", model="rapidocr_multi"))
    s.add(TrashedItem(item_id=items[30].id, original_groups=""))
    items[31].hidden = True
    s.flush()


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    cfg = UiConfig(data_dir=tmp_path_factory.mktemp("eqlib") / "data")
    library = Library(cfg)
    with library.db.session() as s:
        _seed(s)
        s.commit()
    app.dependency_overrides[get_library] = lambda: library
    deps.reset_library()
    with TestClient(app) as c:
        yield c, library
    app.dependency_overrides.clear()


# ---- the oracle: the pre-change evaluation, frozen --------------------------


def _oracle_ids(s, tree, *, groups="", ungrouped=False, untagged=False,
                trash=False, hidden=False, show_hidden=False, kind="",
                sequence=None, hide_sequenced=False, pending=False,
                pending_kind="") -> list[int]:
    trashed = set(s.execute(select(TrashedItem.item_id)).scalars().all())
    hidden_ids = set(s.execute(
        select(Item.id).where(Item.hidden.is_(True))).scalars().all())
    exclude_hidden = hidden_ids if not show_hidden else set()
    group_ids = [int(x) for x in groups.split(",") if x.strip().isdigit()]

    memberships: dict[int, list[int]] = {}
    for iid, gid in s.execute(
        select(ItemGroup.item_id, ItemGroup.group_id)
    ).all():
        memberships.setdefault(iid, []).append(gid)

    if sequence is not None:
        member_ids = list(s.execute(
            select(SequenceItem.item_id)
            .where(SequenceItem.sequence_id == sequence)
            .order_by(SequenceItem.position, SequenceItem.id)
        ).scalars().all())
        candidate_ids = [i for i in member_ids
                         if i not in trashed and i not in exclude_hidden]
    elif trash:
        candidate_ids = list(trashed)
    elif hidden:
        candidate_ids = [i for i in hidden_ids if i not in trashed]
    elif pending:
        pend: set[int] = set()
        if pending_kind in ("", "tags"):
            pend |= set(s.execute(select(ItemTag.item_id)
                                  .where(ItemTag.pending.is_(True))
                                  ).scalars().all())
        if pending_kind in ("", "captions"):
            pend |= set(s.execute(select(Caption.item_id)
                                  .where(Caption.pending.is_(True))
                                  ).scalars().all())
        if pending_kind in ("", "faces"):
            pend |= set(s.execute(
                select(ItemSubject.item_id)
                .join(Face, Face.id == ItemSubject.face_id)
                .where(ItemSubject.assigned_by == "suggested",
                       Face.dismissed.is_(False))).scalars().all())
        candidate_ids = [i for i in pend
                         if i not in trashed and i not in exclude_hidden]
    else:
        all_ids = list(s.execute(select(Item.id)).scalars().all())
        excluded = trashed | exclude_hidden
        if ungrouped:
            candidate_ids = [i for i in all_ids
                             if i not in memberships and i not in excluded]
        elif untagged:
            tagged = set(s.execute(
                select(ItemTag.item_id).distinct()).scalars().all())
            candidate_ids = [i for i in all_ids
                             if i not in tagged and i not in excluded]
        elif group_ids:
            wanted = descendant_groups(s, group_ids)
            candidate_ids = [
                iid for iid, gids in memberships.items()
                if any(g in wanted for g in gids) and iid not in excluded
            ]
        else:
            candidate_ids = [i for i in all_ids if i not in excluded]

    items = {it.id: it for it in s.execute(
        select(Item).where(Item.id.in_(candidate_ids))).scalars().all()}
    files_by_item: dict[int, list[File]] = {}
    for f in s.execute(select(File).where(
            File.item_id.in_(candidate_ids))).scalars().all():
        files_by_item.setdefault(f.item_id, []).append(f)
    borrowed = {}
    borrowed_ids = [it.active_file_id for it in items.values()
                    if it.kind == "sequence" and it.active_file_id is not None]
    if borrowed_ids:
        borrowed = {f.id: f for f in s.execute(
            select(File).where(File.id.in_(borrowed_ids))).scalars().all()}

    kinds = {k.strip() for k in kind.split(",") if k.strip()}
    active = tree is not None and not q.is_empty(tree)
    res = Resolver(s)
    eff = res.effective_for(candidate_ids) if active else {}
    inherited: dict[int, set[str]] = {}
    if active:
        for it in items.values():
            if it.kind != "sequence":
                continue
            sid = s.execute(select(Sequence.id).where(
                Sequence.item_id == it.id)).scalars().first()
            if sid is None:
                continue
            mids = list(s.execute(select(SequenceItem.item_id).where(
                SequenceItem.sequence_id == sid)).scalars().all())
            meff = res.effective_for(mids)
            inherited[it.id] = set().union(
                *[e.positive for e in meff.values()]) if meff else set()

    meta_by_item = load_indexed_meta(s, candidate_ids) if active else {}
    out_links, in_links = (load_link_sets(s, candidate_ids)
                           if active else ({}, {}))
    (group_direct, group_anc, group_dpaths, group_apaths) = (
        load_group_sets(s, candidate_ids) if active else ({}, {}, {}, {}))
    caption_sets, instruction_sets = (load_caption_sets(s, candidate_ids)
                                      if active else ({}, {}))
    subject_sets = load_subject_sets(s, candidate_ids) if active else {}
    place_sets = load_place_sets(s, candidate_ids) if active else {}
    event_sets = load_event_sets(s, candidate_ids) if active else {}
    taken_windows = load_taken_windows(s, candidate_ids) if active else {}
    face_counts = load_face_counts(s, candidate_ids) if active else {}
    text_counts = load_text_counts(s, candidate_ids) if active else {}
    # The oracle resolves likeness the same way the real path does — the
    # question here is whether the COMPILER agrees with `evaluate()`, not
    # whether two implementations of Hamming distance agree.
    # Catalog-wide and item-independent, unlike every other loader here.
    tag_meta = load_tag_meta(s) if active else {}
    similar_sets = (load_similar_sets(s, q.similar_conditions(tree))
                    if active else {})
    value_tags = (load_value_sets(s, q.value_conditions(tree))
                  if active else {})
    caption_counts: dict[int, int] = {}
    instruction_counts: dict[int, int] = {}
    if active:
        by_kind = {"caption": caption_counts,
                   "instruction": instruction_counts}
        for iid_, kind_, n_ in s.execute(
            select(Caption.item_id, Caption.kind, func.count(Caption.id))
            .where(Caption.item_id.in_(candidate_ids),
                   Caption.pending.is_(False))
            .group_by(Caption.item_id, Caption.kind)
        ).all():
            target = by_kind.get(kind_ or "caption")
            if target is not None:
                target[iid_] = target.get(iid_, 0) + n_

    file_counts: dict[int, int] = {}
    for iid_, n_ in s.execute(
        select(File.item_id, func.count(File.id)).group_by(File.item_id)
    ).all():
        file_counts[iid_] = int(n_)

    sequenced = set(s.execute(select(SequenceItem.item_id)).scalars().all())
    seq_counts: dict[int, int] = {}
    for iid_, n_ in s.execute(
        select(SequenceItem.item_id,
               func.count(func.distinct(SequenceItem.sequence_id)))
        .group_by(SequenceItem.item_id)
    ).all():
        seq_counts[iid_] = int(n_)
    out = []
    for iid in candidate_ids:
        it = items[iid]
        if kinds and it.kind not in kinds:
            continue
        if hide_sequenced and iid in sequenced:
            continue
        af = next((f for f in files_by_item.get(iid, [])
                   if f.id == it.active_file_id), None)
        if af is None and it.kind == "sequence":
            af = borrowed.get(it.active_file_id)
        if af is None:
            continue
        if active:
            tags = set(eff.get(iid).positive if iid in eff else set())
            neg = set(eff.get(iid).negative if iid in eff else set())
            if it.kind == "sequence":
                tags |= inherited.get(iid, set())
            nums = intrinsic_nums(af, it.last_imported_at, it.created_at)
            nums["tag_count"] = float(len(tags))
            nums["caption_count"] = float(caption_counts.get(iid, 0))
            nums["instruction_count"] = float(instruction_counts.get(iid, 0))
            total, unnamed = face_counts.get(iid, (0, 0))
            nums["faces"] = float(total)
            nums["unnamed_faces"] = float(unnamed)
            nums["text_blocks"] = float(text_counts.get(iid, 0))
            nums["sequence_count"] = float(seq_counts.get(iid, 0))
            nums["file_count"] = float(file_counts.get(iid, 0))
            ctx = q.QueryCtx(
                tags=frozenset(tags), neg=frozenset(neg), nums=nums,
                texts=intrinsic_texts(it.kind, af, it.uid),
                meta=meta_by_item.get(iid, {}),
                out_links=out_links.get(iid, []),
                in_links=in_links.get(iid, []),
                captions=caption_sets.get(iid, []),
                instructions=instruction_sets.get(iid, []),
                groups=group_direct.get(iid, frozenset()),
                group_ancestors=group_anc.get(iid, frozenset()),
                group_paths=group_dpaths.get(iid, frozenset()),
                group_ancestor_paths=group_apaths.get(iid, frozenset()),
                subjects=subject_sets.get(iid, {}),
                places=place_sets.get(iid, []),
                events=event_sets.get(iid, {}),
                taken=taken_windows.get(iid),
                similar=frozenset(k for k, sids in similar_sets.items()
                                  if iid in sids),
                tag_meta=tag_meta,
                value_tags=value_tags,
            )
            if not q.evaluate(tree, ctx):
                continue
        out.append(iid)
    return out


# ---- random condition trees over the whole grammar --------------------------


def _rand_leaf(rng: random.Random) -> q.Node:
    kind = rng.randrange(11)
    tname = rng.choice(TAG_NAMES + ["missing_tag"])
    if kind == 0:
        return q.TagCond(name=tname, have=rng.random() < 0.8,
                         sign=rng.choice(["pos", "pos", "neg"]))
    if kind == 10:
        # The same condition asked by what the TAG SET marks a tag with.
        # The compiler claims this is EXACT, which is what this run tests: it
        # resolves the marks to a set of tag ids and hands them to the very
        # clause a named tag takes, implications and group grants included.
        refs = [q.LinkTagRef(name=n, exclude=rng.random() < 0.3)
                for n in rng.sample(["noflip", "draft", "unmarked"],
                                    rng.randint(1, 2))]
        return q.TagCond(name="", have=rng.random() < 0.8,
                         sign=rng.choice(["pos", "pos", "neg"]),
                         meta_tags=refs)
    if kind == 1:
        return q.GroupCond(name=rng.choice(GROUP_NAMES + ["nope"]),
                           mode=rng.choice(
                               ["has", "hasnot", "only", "notonly"]))
    if kind == 2:
        name = rng.choice(["width", "height", "resolution", "aspect",
                           "length", "fps", "bitrate", "tag_count",
                           "caption_count", "faces", "unnamed_faces",
                           "text_blocks", "sequence_count", "file_count"])
        op = rng.choice([">", "<", ">=", "<=", "=", "!="])
        val = rng.choice([0, 1, 2, 400, 750.0, 0.7, 1.3])
        return q.MetaCond(name=name, mtype="numeric", op=op, value=val,
                          tol=rng.choice([0.0, 0.05, 0.5]))
    if kind == 3:
        name = rng.choice(["type", "format", "id"])
        op = rng.choice(["=", "!=", "~", "!~"])
        val = rng.choice(["image", "video", "png", "jpeg", "eq-0", ""])
        return q.MetaCond(name=name, mtype="text", op=op, value=val)
    if kind == 4:
        name = rng.choice(["camera", "iso", "date_taken", "unknown_meta"])
        if name == "camera" or name == "unknown_meta":
            return q.MetaCond(name=name, mtype="text",
                              op=rng.choice(["=", "!=", "~", "!~"]),
                              value=rng.choice(["Cam 1", "cam", ""]))
        if name == "iso":
            return q.MetaCond(name=name, mtype="numeric",
                              op=rng.choice([">", "=", "!=", "<="]),
                              value=rng.choice([100, 300, 500.0]),
                              tol=rng.choice([0.0, 0.5]))
        return q.MetaCond(name=name, mtype="date",
                          op=rng.choice(["=", "!=", ">", "<"]),
                          value=rng.choice(["2020", "2020-01", "2021"]))
    if kind == 5:
        return q.CaptionCond(mode=rng.choice(["has", "hasnot"]),
                             caption_kind=rng.choice(
                                 ["caption", "instruction"]),
                             caption_tags=[q.LinkTagRef(
                                 name="style",
                                 exclude=rng.random() < 0.3)]
                             if rng.random() < 0.6 else [])
    if kind == 6:
        return q.LinkCond(direction=rng.choice(
            ["has", "hasnot", "linkedby", "notlinkedby"]),
            link_tags=[q.LinkTagRef(name="crop",
                                    exclude=rng.random() < 0.3)]
            if rng.random() < 0.5 else [])
    if kind == 7:
        bounded = rng.random() < 0.5
        return q.SubjectCond(
            name=rng.choice(["subject:alice", ""]),
            have=rng.random() < 0.7,
            date_from=20200000 if bounded and rng.random() < 0.5 else None,
            age_from=10 if bounded and rng.random() < 0.5 else None,
            age_to=13 if bounded and rng.random() < 0.3 else None,
        )
    if kind == 8:
        bounded = rng.random() < 0.6
        return q.EventCond(
            name=rng.choice(["event:con2020", ""]),
            have=rng.random() < 0.7,
            date_from=20200101 if bounded else None,
            date_to=20201231 if bounded and rng.random() < 0.5 else None,
        )
    if rng.random() < 0.25:
        # Tags read as numbers. The seed holds `height:172cm`, `height:1.9m`
        # and `quality:7` (one implied via `tall_marker`), so a comparison
        # has partial answers, unit conversion and the implication step to
        # get wrong; `height>5m` and an unknown namespace must resolve to
        # nothing rather than to everything.
        ns, unit = rng.choice([("height", "cm"), ("height", "m"),
                               ("quality", ""), ("nothing", "")])
        return q.ValueCond(
            name=ns, op=rng.choice(["=", "!=", ">", ">=", "<", "<="]),
            value=rng.choice([1.5, 1.9, 172.0, 190.0, 5.0, 7.0]),
            unit=unit, tol=rng.choice([0.0, 0.05, 0.5]),
            have=rng.random() < 0.7)
    if rng.random() < 0.3:
        # Likeness to a pivot. `eq-000`..`eq-003` sit 0–3 bits apart, so a
        # tolerance of 1–3 has a partial answer the compiler can get wrong;
        # a missing uid must resolve to nothing rather than to everything.
        return q.SimilarCond(
            uid=rng.choice(["eq-000", "eq-001", "eq-020", "eq-nope"]),
            # Either side of `searchctx.ENUMERATED_TOL`, so the oracle sees
            # both ways of resolving one condition.
            tol=rng.choice([None, 0, 1, 3, 8]),
            have=rng.random() < 0.7)
    if rng.random() < 0.5:
        return q.TakenCond(have=rng.random() < 0.7,
                           date_from=rng.choice([None, 20190000000000,
                                                 20200101000000]),
                           date_to=rng.choice([None, 20211231000000]))
    # ONE field — the address — so the only axes left are the operator, the
    # value (including "", which asks whether there is a place at all) and
    # the sign.
    return q.PlaceCond(op=rng.choice(["=", "~"]),
                       value=rng.choice(["tokyo", "Japan", "JP", ""]),
                       have=rng.random() < 0.7)


def _rand_tree(rng: random.Random, depth: int = 0) -> q.Group:
    n = rng.randint(1, 3)
    children: list[q.Node] = []
    for _ in range(n):
        if depth < 2 and rng.random() < 0.3:
            children.append(_rand_tree(rng, depth + 1))
        else:
            children.append(_rand_leaf(rng))
    return q.Group(op=rng.choice(["and", "or"]),
                   neg=rng.random() < 0.25, children=children)


def _post_ids(client, tree, **scope) -> tuple[list[int], int]:
    body = {"query": tree.model_dump() if tree is not None else None,
            "page": 1, "page_size": 500, **scope}
    r = client.post("/api/items/query", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    return [it["id"] for it in data["items"]], data["total"]


def test_random_trees_match_oracle(lib):
    client, library = lib
    rng = random.Random(42)
    sizes: set[int] = set()
    with library.db.session() as s:
        n_items = len(_oracle_ids(s, None))
        for i in range(300):
            tree = _rand_tree(rng)
            got, total = _post_ids(client, tree)
            want = _oracle_ids(s, tree)
            assert set(got) == set(want), (
                f"tree #{i}: {tree.model_dump_json()}\n"
                f"missing={sorted(set(want) - set(got))} "
                f"extra={sorted(set(got) - set(want))}"
            )
            assert total == len(want)
            sizes.add(len(want))
    # NON-VACUOUS. `set(got) == set(want)` is satisfied by two empty sets, so
    # a run where the seed stopped populating — or where a condition kind was
    # added to `_rand_leaf` and its loader never wired in, which is exactly
    # what this file exists to catch — would agree with itself, 300 times,
    # and pass. So the answers have to VARY: some trees match nothing, some
    # match everything, and some land in between.
    assert 0 in sizes, "no tree matched nothing — is the seed wrong?"
    assert n_items in sizes, "no tree matched the whole library"
    assert any(0 < n < n_items for n in sizes), (
        f"every answer was all-or-nothing ({sorted(sizes)}) — the trees are "
        f"not discriminating between items, so an agreeing oracle proves "
        f"nothing")


def test_the_random_trees_reach_every_condition_kind(lib):
    """The second half of "non-vacuous": the run above proves the compiler
    and the evaluator AGREE, and this proves they agreed about everything.

    A condition kind added to `query.py` and not to `_rand_leaf` is the
    failure mode — the generator keeps producing the ten kinds it knows, the
    300 trees still pass, and the new one is unwatched. Read off `CondModel`'s
    own subclasses rather than a list here, so adding one is what fails.
    """
    rng = random.Random(42)                      # the same stream as above
    seen: set[str] = set()

    def walk(node) -> None:
        seen.add(node.type)
        for child in getattr(node, "children", []) or []:
            walk(child)

    for _ in range(300):
        walk(_rand_tree(rng))

    want = {c.model_fields["type"].default
            for c in q.CondModel.__subclasses__()
            if c.model_fields.get("type") is not None
            and c.model_fields["type"].default is not None}
    missing = sorted(want - seen)
    assert not missing, (
        f"the generator never produces {missing}, so the oracle above says "
        f"nothing about {'it' if len(missing) == 1 else 'them'}. Add a branch "
        f"to `_rand_leaf` — and, if the kind is new, a compiler in "
        f"prefilter.py and a loader in ops/search.py with it.")


def test_scopes_match_oracle(lib):
    client, library = lib
    with library.db.session() as s:
        seq_id = s.execute(select(Sequence.id)).scalars().first()
        gid = s.execute(select(Group.id).where(
            Group.name == "trips")).scalars().first()
        scopes = [
            {}, {"trash": True}, {"hidden": True}, {"show_hidden": True},
            {"ungrouped": True}, {"untagged": True}, {"kind": "video"},
            {"kind": "image,sequence"}, {"hide_sequenced": True},
            {"pending": True}, {"pending": True, "pending_kind": "faces"},
            {"pending": True, "pending_kind": "captions"},
            {"groups": str(gid)}, {"sequence": seq_id},
        ]
        tree = q.Group(children=[q.TagCond(name="dog")])
        for scope in scopes:
            for t in (None, tree):
                got, total = _post_ids(client, t, **scope)
                want = _oracle_ids(s, t, **scope)
                assert set(got) == set(want), (scope, t)
                assert total == len(want), (scope, t)


def test_sort_orders_match_python_sort(lib):
    client, library = lib
    tree = q.Group(children=[q.TagCond(name="dog")])
    with library.db.session() as s:
        want_ids = _oracle_ids(s, tree)
        items = {it.id: it for it in s.execute(
            select(Item).where(Item.id.in_(want_ids))).scalars().all()}
        files = {}
        for it in items.values():
            f = s.execute(select(File).where(
                File.id == it.active_file_id)).scalars().first()
            files[it.id] = f
        keys = {
            "name": lambda i: items[i].name.lower(),
            "resolution": lambda i: (files[i].width or 0) * (files[i].height or 0),
            "width": lambda i: files[i].width or 0,
            "modified": lambda i: items[i].updated_at,
            "first": lambda i: items[i].created_at,
            "import": lambda i: (items[i].last_imported_at
                                 or items[i].created_at),
        }
        for field, key in keys.items():
            for direction in ("asc", "desc"):
                got, _ = _post_ids(client, tree, sort=f"{field}_{direction}")
                rev = direction == "desc"
                want = sorted(want_ids,
                              key=lambda i: (key(i), i), reverse=rev)
                assert got == want, (field, direction)


def test_exact_tree_skips_residue_evaluator(lib, monkeypatch):
    client, _library = lib
    import media_compost.ops.search as search_mod

    def boom(*a, **k):
        raise AssertionError("residue evaluator ran for an exact tree")

    monkeypatch.setattr(search_mod, "evaluate_residue", boom)
    tree = q.Group(children=[
        q.TagCond(name="dog"),
        q.MetaCond(name="width", mtype="numeric", op=">", value=100),
        q.GroupCond(name="animals", mode="has"),
        q.CaptionCond(mode="has"),
        q.EventCond(name="event:con2020"),
        q.PlaceCond(op="~", value="tokyo"),
        q.SubjectCond(name="subject:alice"),
        # A tag asked for by what the tag set MARKS it with compiles
        # exactly too — it resolves the marks to tag ids and hands them to
        # the clause a named tag takes.
        q.TagCond(name="", meta_tags=[q.LinkTagRef(name="noflip")]),
    ])
    got, total = _post_ids(client, tree)
    assert total == len(got)


def test_residue_tree_still_answers(lib):
    client, library = lib
    # A SubjectCond with bounds is a superset+residue node by design.
    tree = q.Group(children=[
        q.SubjectCond(name="subject:alice", age_from=10, age_to=14)])
    with library.db.session() as s:
        got, total = _post_ids(client, tree)
        want = _oracle_ids(s, tree)
        assert set(got) == set(want)


def test_the_count_intrinsics_survive_the_residue_path(lib):
    """A count the compiler answers EXACTLY still has to be answered by the
    evaluator, because an OR holding one inexact condition keeps the whole
    group as residue — and there the value comes from `QueryCtx.nums`.

    `sequence_count` was loaded there and never put in the map, so
    `INFO:sequence_count>=1 OR <anything inexact>` answered NOTHING while the
    plain search worked; the random trees above never happened to build that
    pair. `tag_count` is the inexact partner (it needs effective resolution)
    and matches nothing at 999, so the OR is exactly the count condition.
    """
    client, library = lib
    never = q.MetaCond(name="tag_count", mtype="numeric", op=">=", value=999)
    for name in ("sequence_count", "file_count"):
        for op, value in ((">=", 1), ("=", 0)):
            cond = q.MetaCond(name=name, mtype="numeric", op=op, value=value)
            with library.db.session() as s:
                want = set(_oracle_ids(s, q.Group(children=[cond])))
            alone, _ = _post_ids(client, q.Group(children=[cond]),
                                 hide_sequenced=False)
            mixed, _ = _post_ids(
                client, q.Group(op="or", children=[cond, never]),
                hide_sequenced=False)
            assert set(alone) == want, f"{name}{op}{value} (exact)"
            assert set(mixed) == want, f"{name}{op}{value} (residue)"
        # Non-vacuous: the fixture really does hold both answers.
        with library.db.session() as s:
            assert _oracle_ids(s, q.Group(
                children=[q.MetaCond(name=name, mtype="numeric",
                                     op=">=", value=1)]))


def test_facets_match_oracle(lib):
    """The scope count, against the oracle's own answer.

    The endpoint used to carry min/max width, height, megapixels and aspect
    ratio too, and this test checked those against the same items; they are
    gone (nothing read them, and they joined the active file of every item
    in scope to compute them), so what is left is the number the sidebar
    actually shows."""
    client, library = lib
    with library.db.session() as s:
        r = client.get("/api/items/facets")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == len(_oracle_ids(s, None))
        assert "width" not in data, data