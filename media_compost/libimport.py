"""Merge another LIBRARY folder into this one — CLI ``merge-library``.

The source is a complete library (``media.db`` beside ``items/``). Its
database is opened for reading and IS the record merged from — a strictly
fuller answer than the per-item ``item.json`` sidecars this module used to
scan (they are gone; owner decision, 2026-08) — and file bytes are copied
out of its item folders, which share this library's layout.

Per item (identified by its stable uid):

1. uid already in the DB           -> skip (idempotent re-runs are no-ops).
2. a file matches an existing item -> merge into it (byte-identical sha256, or
   pHash-near + pixel verify — the importer's dedup rules): missing files are
   added with the merge offset-renumbering rule; tags/captions/groups union in.
3. otherwise                       -> create the item preserving its uid,
   copying the bytes into a fresh folder.

The TAG SET travels first, read straight from the source's own tables —
tags with comments, aliases, implications and meta tags; the group tree with
icons, grants and smart queries; subject/place/event records; the ranking
axes — and get-or-created here, existing definitions always winning. Each
source item then crosses as `itemdict.item_to_dict`'s plain dict (built
against the SOURCE session), applied by the same machinery the sidecar
restore used. Relationships are created from ``direction == "out"`` entries
only, and sequences from container items' ``sequence_def`` plus each member's
``sequences`` list — both in a second pass, once every item exists.

The source must already be at this build's schema format; a behind source is
REFUSED untouched (open it once with this build — or ``media-compost migrate``
— to upgrade it first), because merging must not mutate what it reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import media, ocr as ocrlib
from .itemdict import ItemDictCatalog, item_to_dict
from .config import Config
from .dedup import phash_to_int, verify_match
from .dedup_index import find_nearest_file
from .db import (
    chunked,
    Caption,
    Face,
    File,
    FileArtifact,
    FileName,
    Group,
    GroupParent,
    GroupTag,
    Item,
    ItemGroup,
    ItemTag,
    ItemTagBox,
    ItemTagGroup,
    ItemTagGroupTag,
    ItemTagPlacement,
    ItemSubject,
    ItemFaceRun,
    ItemLocation,
    ItemOccasionDismissal,
    ItemPlaceDismissal,
    ItemTextRun,
    FaceOutline, FaceRejection,
    CaptionRef,
    CaptionTag,
    LIB_META,
    LinkTag,
    Location,
    Occasion,
    OccasionPlace,
    Relationship,
    RelationshipTag,
    Sequence,
    SequenceItem,
    Subject,
    Tag,
    TagImplication,
    TextRegion,
    TrashedItem,
    normalize_taken,
)
from .itemmeta import index_file_metadata
from .storage import ItemStore


@dataclass
class MergeStats:
    scanned: int = 0
    created: int = 0
    merged: int = 0
    skipped: int = 0        # uid already present
    tag_sets: int = 0       # user tag sets the destination lacked
    files_added: int = 0
    errors: list[str] = field(default_factory=list)


def _place_line(rec: dict) -> str:
    """A place's ONE LINE out of an item dict."""
    return rec.get("name") or ""


def _dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None



def _source_group_defs(src: Session) -> list[dict]:
    """Every source group as the def dict the priming below consumes —
    uid, name, icon, colour, parent (by uid), granted tags (by name), and
    `smart_query` when present (the key's presence IS the smart identity)."""
    parent_of: dict[int, int] = dict(src.execute(
        select(GroupParent.group_id, GroupParent.parent_group_id)
    ).all())
    groups = {g.id: g for g in src.execute(
        select(Group).order_by(Group.id)).scalars().all()}
    tags_by_group: dict[int, list[dict]] = {}
    for gid, tname, neg in src.execute(
        select(GroupTag.group_id, Tag.name, GroupTag.negative)
        .join(Tag, Tag.id == GroupTag.tag_id).order_by(GroupTag.id)
    ).all():
        tags_by_group.setdefault(gid, []).append(
            {"name": tname, "negative": bool(neg)})
    out = []
    for gid, g in groups.items():
        pid = parent_of.get(gid)
        out.append({
            "uid": g.uid, "name": g.name, "icon": g.icon, "color": g.color,
            "parent": groups[pid].uid if pid in groups else None,
            "tags": tags_by_group.get(gid, []),
            **({"smart_query": g.smart_query}
               if g.smart_query is not None else {}),
        })
    return out


def _source_tag_defs(src: Session) -> list[dict]:
    """Every source tag with everything hanging off it — comment,
    description, alias, implications, meta tags with their counts, and the
    subject / place / event record it carries. The same def shape the
    retired `tags.json` held, built from the tables it was derived from."""
    from .db import TagMetaTag

    tags = {t.id: t for t in src.execute(
        select(Tag).order_by(Tag.name)).scalars().all()}
    tag_meta: dict[int, list[str]] = {}
    tag_meta_counts: dict[int, dict[str, int]] = {}
    for tid, name, count in src.execute(
        select(TagMetaTag.tag_id, TagMetaTag.name, TagMetaTag.count)
        .order_by(TagMetaTag.name)
    ).all():
        tag_meta.setdefault(tid, []).append(name)
        if count:
            tag_meta_counts.setdefault(tid, {})[name] = int(count)
    implies: dict[int, set[str]] = {}
    for tid, iid in src.execute(
        select(TagImplication.tag_id, TagImplication.implies_id)
    ).all():
        target = tags.get(iid)
        if target is not None:
            implies.setdefault(tid, set()).add(target.name)

    subjects: dict[int, dict] = {}
    for sub_row in src.execute(select(Subject)).scalars().all():
        if sub_row.tag_id is not None:
            subjects[sub_row.tag_id] = {
                "display_name": sub_row.display_name,
                "since_date": sub_row.since_date,
            }

    places: dict[int, dict] = {}
    place_tag_by_id: dict[int, str] = {}
    locs = {l.id: l for l in src.execute(select(Location)).scalars().all()}
    for loc in locs.values():
        if loc.tag_id is None:
            continue
        parent = locs.get(loc.parent_id) if loc.parent_id else None
        parent_tag = (tags.get(parent.tag_id)
                      if parent and parent.tag_id else None)
        places[loc.tag_id] = {
            "name": loc.name or "", "lat": loc.lat, "lon": loc.lon,
            # By the parent's identity TAG, like an event's venues.
            **({"parent": parent_tag.name} if parent_tag is not None else {}),
        }
        tag = tags.get(loc.tag_id)
        if tag is not None:
            place_tag_by_id[loc.id] = tag.name

    venues: dict[int, list[str]] = {}
    for oid, lid in src.execute(
        select(OccasionPlace.occasion_id, OccasionPlace.location_id)
        .order_by(OccasionPlace.id)
    ).all():
        name = place_tag_by_id.get(lid)
        if name:
            venues.setdefault(oid, []).append(name)
    events: dict[int, dict] = {}
    occs = {o.id: o for o in src.execute(select(Occasion)).scalars().all()}
    for occ in occs.values():
        if occ.tag_id is None:
            continue
        up = occs.get(occ.parent_id) if occ.parent_id else None
        up_tag = tags.get(up.tag_id) if up and up.tag_id else None
        events[occ.tag_id] = {
            "display_name": occ.display_name,
            **({"parent": up_tag.name} if up_tag is not None else {}),
            "start_date": occ.start_date,
            "end_date": occ.end_date,
            # By the venue's identity TAG: an event's place must be a named
            # one, which is what makes that reference stable.
            "places": venues.get(occ.id, []),
        }

    # No `description`: a tag has none of its own (rung v17) — a source
    # written before that carries the key and the reader drops it.
    out = []
    for tid, tag in tags.items():
        alias_of = (tags[tag.alias_of_id].name
                    if tag.alias_of_id in tags else None)
        e = {"name": tag.name, "comment": tag.comment or "",
             "alias_of": alias_of,
             "implies": sorted(implies.get(tid, ()))}
        if tid in subjects:
            e["subject"] = subjects[tid]
        if tag_meta.get(tid):
            e["meta_tags"] = tag_meta[tid]
            if tag_meta_counts.get(tid):
                e["meta_counts"] = tag_meta_counts[tid]
        if tid in places:
            e["place"] = places[tid]
        if tid in events:
            e["event"] = events[tid]
        out.append(e)
    return out


class LibraryMerger:
    def __init__(self, session: Session, store: ItemStore, cfg: Config):
        self.session = session
        self.store = store
        self.cfg = cfg
        self.stats = MergeStats()
        # uid (from the source payloads) -> DB item id, for the link passes.
        self.item_by_uid: dict[str, int] = {}
        self._tag_by_name: dict[str, Tag] = {}
        self._group_by_uid: dict[str, Group] = {}
        # Which uids this RUN created — ranking judgments restore only for
        # those (they are not unique rows, so re-running over an existing
        # library would double every one).
        self._created_uids: set[str] = set()

    # ---- entry point -------------------------------------------------------

    def run(self, source: Path, dry_run: bool = False) -> "MergeStats":
        src_root = self._resolve_source(Path(source).resolve())
        with self._source_session(src_root) as src:
            known = self._already_here(src)
            payloads = self._payloads(src_root, src, skip=set(known))
            self.stats.scanned = len(payloads) + len(known)
            if dry_run:
                self.stats.skipped += len(known)
                self._dry_run(payloads)
                return self.stats

            self._prime_catalogs(src)
            self._prime_rankings(src)
            self._prime_tag_sets(src)
        max_file_id = self._max_file_id()

        # The uids already here were decided in bulk (`_already_here`):
        # they take part in the links pass below, and nothing else.
        self.item_by_uid.update(known)
        self.stats.skipped += len(known)
        for folder, payload in payloads:
            uid = payload["uid"]
            try:
                target = self._find_merge_target(folder, payload, max_file_id)
                if target is not None:
                    self._merge_into(target, folder, payload)
                    self.item_by_uid[uid] = target.id
                    self.stats.merged += 1
                else:
                    item = self._create_item(folder, payload, adopt=False)
                    self.item_by_uid[uid] = item.id
                    self._created_uids.add(uid)
                    self.stats.created += 1
                self.session.flush()
            except Exception as exc:  # noqa: BLE001 - keep going per item
                self.stats.errors.append(f"{uid}: {exc}")

        # Second pass: cross-item links and sequences (every item exists now).
        # Sequences come from the container items' defs first, so members'
        # membership entries (which reference the sequence's uid) resolve.
        for _folder, payload in payloads:
            try:
                self._apply_links(payload)
            except Exception as exc:  # noqa: BLE001
                self.stats.errors.append(f"{payload['uid']} links: {exc}")
        for _folder, payload in payloads:
            try:
                self._apply_caption_refs(payload)
            except Exception as exc:  # noqa: BLE001
                self.stats.errors.append(
                    f"{payload['uid']} instructions: {exc}")
        for _folder, payload in payloads:
            try:
                self._ensure_sequence(payload)
            except Exception as exc:  # noqa: BLE001
                self.stats.errors.append(f"{payload['uid']} sequences: {exc}")
        for _folder, payload in payloads:
            try:
                self._apply_membership(payload)
            except Exception as exc:  # noqa: BLE001
                self.stats.errors.append(f"{payload['uid']} sequences: {exc}")
        for _folder, payload in payloads:
            try:
                self._sync_container(payload)
            except Exception as exc:  # noqa: BLE001
                self.stats.errors.append(f"{payload['uid']} container: {exc}")
        # Rating records reference the OTHER item by uid, so they wait for the
        # second pass like relationships do; the ranking's own score rows
        # never travel (a hand-assigned score tag rides the tag list like
        # any tag), so the judgments that came back are refit at the end.
        for _folder, payload in payloads:
            try:
                self._apply_ranking_records(payload)
            except Exception as exc:  # noqa: BLE001
                self.stats.errors.append(f"{payload['uid']} rankings: {exc}")
        self._rebuild_smart_groups()
        self.session.commit()
        return self.stats

    def _resolve_source(self, source: Path) -> Path:
        """The source LIBRARY root — the folder holding ``media.db``.

        Takes the library folder itself or its ``items/`` tree (the CLI's two
        historical spellings), refuses this library's own folder (merging a
        library into itself can only skip every uid — asking for it is a
        mistake worth naming), and refuses a source whose format is behind:
        merging must not mutate what it reads, so the upgrade has to happen
        under a build of its own first.
        """
        from . import migrations

        if source.name == "items" and (source.parent / "media.db").is_file():
            source = source.parent
        db_path = source / "media.db"
        if not db_path.is_file():
            raise ValueError(
                f"{source} is not a library folder (no media.db). "
                f"merge-library reads another library's own database; to "
                f"bring in loose pictures, use `import`.")
        if source == self.cfg.data_dir.resolve():
            raise ValueError("that IS this library — nothing to merge")
        insp = migrations.inspect(db_path)
        if insp.problem:
            raise ValueError(f"cannot read {db_path}: {insp.problem}")
        if insp.plan:
            raise ValueError(
                f"{source} is at format {insp.found} and this build works "
                f"with {insp.current}. Merging must not change the source, "
                f"so upgrade it first: media-compost migrate --data-dir "
                f"{source}")
        return source

    def _source_session(self, src_root: Path) -> Session:
        """A session over the source's database, opened READ-ONLY.

        ``mode=ro`` at the SQLite level, so no path through the merge —
        session autoflush included — can write into the library being read.
        (The global connect hook's ``journal_mode=WAL`` is a no-op on a
        database that is already WAL, which every library this app made is.)
        """
        from sqlalchemy import create_engine

        engine = create_engine(
            f"sqlite:///file:{(src_root / 'media.db').as_posix()}"
            f"?mode=ro&uri=true", future=True)
        return Session(engine)

    def _already_here(self, src: Session) -> dict[str, int]:
        """Source uid -> THIS library's item id, for every source item that
        is already here: decided in bulk, up front, so that a re-run of a
        merge builds no transfer dict for an item it will skip.

        MEASURED (5090 box, 20 000 source items into 200 000): the second
        run of the same merge took 45 s, exactly the first run's. Every
        source item's dict (32 statements each, `item_to_dict`) was built
        and then thrown away at the per-item "does this uid exist" lookup.
        One chunked `IN` over the source's uids answers the question for
        all of them before a dict is built."""
        uids = list(src.execute(select(Item.uid)).scalars())
        out: dict[str, int] = {}
        for chunk in chunked(uids):
            for uid, iid in self.session.execute(
                select(Item.uid, Item.id).where(Item.uid.in_(chunk))
            ).all():
                out[uid] = iid
        return out

    def _payloads(self, src_root: Path, src: Session,
                  skip: "set[str] | None" = None) -> "list[tuple[Path, dict]]":
        """(source item folder, the item's full dict) for every source item
        not in ``skip`` (the uids already here, `_already_here`).

        `item_to_dict` against the SOURCE session is the transfer format —
        the same shape the item.json files used to hold, minus the embedded
        tag set (which `_prime_catalogs` now reads from the source's
        tables directly, a fuller answer).
        """
        items_dir = src_root / "items"
        catalog = ItemDictCatalog(src)
        out: list[tuple[Path, dict]] = []
        for item in src.execute(
            select(Item).order_by(Item.id)
        ).scalars().all():
            if skip and item.uid in skip:
                continue
            # The source's own layout, built by hand: `ItemStore(cfg)` calls
            # `ensure_dirs()`, and a merge must not write into what it reads.
            out.append((items_dir / item.uid[:2] / item.uid,
                        item_to_dict(src, item, catalog=catalog)))
        return out

    def _dry_run(self, payloads) -> None:
        max_file_id = self._max_file_id()
        for folder, payload in payloads:
            if self._find_merge_target(folder, payload, max_file_id) is not None:
                self.stats.merged += 1
            else:
                self.stats.created += 1

    # ---- global catalogs (tags + groups) ------------------------------------

    def _prime_catalogs(self, src: Session) -> None:
        """Get-or-create the source's whole tag set, then wire the trees
        (alias/implications by name, group parents by uid). Existing
        definitions are left untouched — the current library wins.

        Read straight from the SOURCE library's tables — tags with their
        comments, descriptions, aliases, implications and meta tags; the
        group tree with icons, colours, grants and smart queries; the
        subject/place/event records; the meta-tag namespace. This replaced
        reading the retired `groups.json` / `tags.json` catalog files, and is
        the fuller answer: the database was always what those files were
        derived from.
        """
        for t in self.session.execute(select(Tag)).scalars().all():
            self._tag_by_name[t.name] = t
        for g in self.session.execute(select(Group)).scalars().all():
            self._group_by_uid[g.uid] = g

        tag_defs = {e["name"]: e for e in _source_tag_defs(src)}
        group_defs = {e["uid"]: e for e in _source_group_defs(src)}
        meta_defs = {
            name: (comment or "", description or "")
            for name, comment, description in src.execute(
                select(LinkTag.name, LinkTag.comment, LinkTag.description)
                .where(LIB_META)
            ).all()
        }

        created_tags: set[str] = set()
        for name, d in tag_defs.items():
            if name not in self._tag_by_name:
                tag = Tag(name=name, comment=d.get("comment") or "")
                self.session.add(tag)
                self._tag_by_name[name] = tag
                created_tags.add(name)
        self.session.flush()
        for name in created_tags:
            d = tag_defs[name]
            tag = self._tag_by_name[name]
            alias = d.get("alias_of")
            if alias and alias in self._tag_by_name:
                tag.alias_of_id = self._tag_by_name[alias].id
                continue
            targets = list(d.get("implies") or [])
            for target in targets:
                other = self._tag_by_name.get(target)
                if other is None or other.id == tag.id:
                    continue
                self.session.add(
                    TagImplication(tag_id=tag.id, implies_id=other.id))

        # A subject is extra data on a tag, and it rides on the tag definition —
        # so it is created here, beside the tag it is. Without this a folder
        # round-trip keeps the tag and loses the identity: the display name, the
        # comment that tells two Michael Jordans apart, and the since-date that
        # turns a year into an age.
        for name, d in tag_defs.items():
            sub = d.get("subject")
            if not isinstance(sub, dict):
                continue
            tag = self._tag_by_name.get(name)
            if tag is None:
                continue
            existing = self.session.execute(
                select(Subject).where(Subject.tag_id == tag.id)
            ).scalars().first()
            if existing is not None:
                continue
            self.session.add(Subject(
                tag_id=tag.id,
                display_name=sub.get("display_name") or "",
                since_date=sub.get("since_date"),
            ))
        self.session.flush()

        # A place and an event are the same trick as a subject — extra data on
        # a tag — and they ride on the same definition. Only the LIBRARY-WIDE
        # file carries them (an item.json says which tags a picture has, not
        # what the tag set means), so a folder without one simply restores
        # the tags and no records, exactly as before.
        self._restore_places(tag_defs)
        self._restore_events(tag_defs)
        for name, (comment, description) in meta_defs.items():
            self._ensure_meta_tag(name, comment, description)
        self._restore_tag_meta_tags(tag_defs)
        self.session.flush()

        created_groups: set[str] = set()
        for uid, d in group_defs.items():
            if uid not in self._group_by_uid:
                g = Group(uid=uid, name=d.get("name") or "Group",
                          icon=d.get("icon") or "folder",
                          color=d.get("color"),
                          # The KEY's presence is the identity: absent means
                          # an ordinary group (every older folder), present
                          # — the empty rule included — a smart one.
                          smart_query=(str(d["smart_query"])
                                       if "smart_query" in d else None))
                self.session.add(g)
                self._group_by_uid[uid] = g
                created_groups.add(uid)
        self.session.flush()
        for uid in created_groups:
            parent_uid = group_defs[uid].get("parent")
            parent = self._group_by_uid.get(parent_uid) if parent_uid else None
            if parent is not None:
                self.session.add(GroupParent(
                    group_id=self._group_by_uid[uid].id,
                    parent_group_id=parent.id,
                ))
            for gt in group_defs[uid].get("tags") or []:
                tag = self._tag_by_name.get(gt.get("name"))
                if tag is not None:
                    self.session.add(GroupTag(
                        group_id=self._group_by_uid[uid].id, tag_id=tag.id,
                        negative=bool(gt.get("negative")),
                    ))
        self.session.flush()

    # ---- dedup matching ------------------------------------------------------

    def _max_file_id(self) -> int:
        """The files table's high-water mark BEFORE this restore ran — the
        bound `_find_merge_target` probes under. Without it the probe would
        see the files this very restore just flushed, and two near-identical
        items from the folder (film frames the film-frame rule keeps
        separate, say) would merge into one — a restore's job is to recreate
        what was there, so it may only ever merge onto what already was."""
        from sqlalchemy import func

        return int(self.session.execute(
            select(func.coalesce(func.max(File.id), 0))).scalar_one())

    def _find_merge_target(self, folder: Path, payload: dict,
                           max_file_id: int) -> Optional[Item]:
        """An existing item this payload's files visually/byte-match, or None.
        Container/sequence payloads (no files) never merge."""
        for fe in payload.get("files") or []:
            sha = fe.get("sha256")
            if sha:
                hit = self.session.execute(
                    select(File).where(File.sha256 == sha)
                ).scalars().first()
                if hit is not None:
                    return self.session.get(Item, hit.item_id)
        for fe in payload.get("files") or []:
            ph = fe.get("phash")
            if not ph or not max_file_id:
                continue
            got = find_nearest_file(
                self.session, phash_to_int(ph), self.cfg.phash_threshold,
                max_id=max_file_id,
            )
            if got is None:
                continue
            cand, cand_dist = got
            cand_file = self.session.get(File, cand)
            if cand_file is None:
                continue
            if self.cfg.dedup_verify:
                src = folder / (fe.get("filename") or "")
                try:
                    incoming = Image.open(src).convert("RGB")
                    ours = Image.open(
                        self.store.path_of(self.session, cand_file)
                    ).convert("RGB")
                    if not verify_match(incoming, ours,
                                        self.cfg.verify_mse(cand_dist)):
                        continue
                except OSError:
                    continue
            return self.session.get(Item, cand_file.item_id)
        return None

    # ---- item construction ---------------------------------------------------

    def _add_files(self, item: Item, folder: Path, payload: dict,
                   *, offset: int = 0, adopt: bool = False,
                   skip_shas: set[str] | None = None) -> dict[int, File]:
        """Create File rows (+names/artifacts) from the payload; returns
        payload-number -> File. Bytes are copied into the item's folder (or
        adopted in place); numbers are shifted by ``offset`` (merge rule),
        ``edit_chain`` entries alike."""
        by_number: dict[int, File] = {}
        for fe in payload.get("files") or []:
            num = fe.get("number")
            filename = fe.get("filename")
            if not num or not filename:
                continue
            if skip_shas and fe.get("sha256") in skip_shas:
                continue
            src = folder / filename
            if not adopt and not src.is_file():
                self.stats.errors.append(
                    f"{payload['uid']}: missing file {filename}")
                continue
            new_num = int(num) + offset
            ext = filename.rsplit(".", 1)[-1] if "." in filename else \
                (fe.get("format") or "bin")
            if adopt and offset == 0:
                rel = filename
            else:
                rel = self.store.write_file(item.uid, new_num, ext, src=src)
            chain = fe.get("edit_chain") or []
            if offset:
                chain = [
                    {**step,
                     "from": (step.get("from") or 0) + offset,
                     "to": (step.get("to") or 0) + offset}
                    for step in chain
                ]
            f = File(
                item_id=item.id, sha256=fe.get("sha256") or "",
                phash=fe.get("phash"), path=rel, number=new_num,
                color_key=fe.get("color_key"), color_sig=fe.get("color_sig"),
                source_kind=fe.get("source_kind") or "stored",
                source_start=fe.get("source_start"),
                source_end=fe.get("source_end"),
                duration=fe.get("duration"), frame_rate=fe.get("frame_rate"),
                bitrate=fe.get("bitrate"),
                width=fe.get("width") or 0, height=fe.get("height") or 0,
                bytes=fe.get("bytes") or 0, format=fe.get("format") or ext,
                crop_x=fe.get("crop_x") or 0.0, crop_y=fe.get("crop_y") or 0.0,
                crop_w=fe.get("crop_w") if fe.get("crop_w") is not None else 1.0,
                crop_h=fe.get("crop_h") if fe.get("crop_h") is not None else 1.0,
                is_derived=bool(fe.get("is_derived")),
                is_kept_original=bool(fe.get("is_kept_original")),
                rotation=int(fe.get("rotation") or 0),
                mirrored=bool(fe.get("mirrored")),
                edit_chain=json.dumps(chain) if chain else "",
                created_at=_dt(fe.get("created_at")) or datetime.now(),
            )
            self.session.add(f)
            self.session.flush()
            by_number[int(num)] = f
            self.stats.files_added += 1
            for ne in fe.get("names") or []:
                if ne.get("name"):
                    self.session.add(FileName(
                        file_id=f.id, name=ne["name"],
                        is_url=bool(ne.get("is_url")),
                        accessed_at=_dt(ne.get("accessed_at")),
                    ))
            # What this file says about itself. A folder written by THIS build
            # carries it, so it is restored verbatim — including a value only a
            # non-active file has, which is exactly what a re-import used to
            # lose. A folder from an older build has no such block, so the
            # bytes are read instead (`values=None`), which is also what the
            # top-level legacy block falls back to further down.
            fmeta = [
                media.MetaValue(
                    name=m["name"], mtype=m.get("mtype") or "text",
                    num=m.get("num_value"), text=m.get("text_value"),
                    raw=m.get("raw") or "",
                )
                for m in fe.get("metadata") or [] if m.get("name")
            ]
            index_file_metadata(self.session, self.store, f,
                                values=fmeta or None)
            for ae in fe.get("artifacts") or []:
                a_name = ae.get("filename")
                a_src = folder / a_name if a_name else None
                if a_src is None or (not adopt and not a_src.is_file()):
                    continue
                if adopt and offset == 0:
                    a_rel = a_name
                else:
                    a_ext = a_name.rsplit(".", 1)[-1] if "." in a_name else "png"
                    a_rel = self.store.write_artifact(
                        item.uid, new_num, ae.get("kind") or "artifact",
                        a_ext, a_src.read_bytes(), ae.get("model") or "",
                    )
                self.session.add(FileArtifact(
                    file_id=f.id, item_id=item.id,
                    kind=ae.get("kind") or "", model=ae.get("model") or "",
                    sha256=ae.get("sha256") or "", path=a_rel,
                    width=ae.get("width") or 0, height=ae.get("height") or 0,
                    bytes=ae.get("bytes") or 0,
                    format=ae.get("format") or "png",
                    stale=bool(ae.get("stale")),
                ))
        # Intra-item wiring by (shifted) payload number.
        for fe in payload.get("files") or []:
            f = by_number.get(fe.get("number"))
            if f is None:
                continue
            sf = by_number.get(fe.get("source_file"))
            if sf is not None:
                f.source_file_id = sf.id
            base = by_number.get(fe.get("based_on"))
            if base is not None:
                f.derived_from_file_id = base.id
        return by_number

    def _apply_tags(self, item: Item, payload: dict) -> None:
        tg_by_name: dict[str, ItemTagGroup] = {}
        for tge in payload.get("tag_groups") or []:
            name = tge.get("name")
            if not name:
                continue
            tg = ItemTagGroup(item_id=item.id, name=name,
                              position=tge.get("position") or 0,
                              system=bool(tge.get("system")))
            self.session.add(tg)
            tg_by_name[name] = tg
        self.session.flush()
        for tge in payload.get("tag_groups") or []:
            tg = tg_by_name.get(tge.get("name"))
            if tg is None:
                continue
            for mname in self._meta_names(tge.get("tags")):
                self.session.add(ItemTagGroupTag(group_id=tg.id, name=mname))

        item_tags: dict[str, ItemTag] = {}
        for e in payload.get("tags") or []:
            name = e.get("name")
            tag = self._tag_by_name.get(name)
            if tag is None:
                continue
            it = item_tags.get(name)
            if it is None:
                it = ItemTag(item_id=item.id, tag_id=tag.id,
                             negative=bool(e.get("negative")),
                             pending=bool(e.get("pending")))
                self.session.add(it)
                self.session.flush()
                item_tags[name] = it
            elif not e.get("negative"):
                # Instances may disagree about the sign; the assignment is
                # negative only when EVERY one is (`sync_placement_sign`'s
                # rule, applied as the entries land).
                it.negative = False
            group = tg_by_name.get(e.get("group")) if e.get("group") else None
            boxes = e.get("boxes") or []
            if group is None and not boxes:
                # The IMPLICIT ungrouped instance — an assignment with no
                # placement row, which is what the app writes for a plain tag
                # and what several rules read: a placement-less pending tag is
                # the one a face guessed (drawn amber), and `_recompute_pending`
                # asks whether any placement is still in a system group.
                # Creating one here made every restored tag a different kind of
                # thing from the one that was written.
                self._restore_appearances(item, tag, e)
                continue
            placement = ItemTagPlacement(
                item_tag_id=it.id, group_id=group.id if group else None,
                negative=bool(e.get("negative")),
            )
            self.session.add(placement)
            self.session.flush()
            for b in boxes:
                self.session.add(ItemTagBox(
                    placement_id=placement.id,
                    x=b.get("x"), y=b.get("y"), w=b.get("w"), h=b.get("h"),
                    time_start=b.get("time_start"), time_end=b.get("time_end"),
                    # The sidecar writes both; dropping them read every
                    # negative time range back as positive and dissolved
                    # every movement track on re-import.
                    track_id=b.get("track_id"),
                    negative=bool(b.get("negative")),
                    points=self._points_in(b.get("points")),
                ))
            # The appearances of this subject that are NOT at a face — the
            # ones at a face are restored with the face, by name. Only the
            # first placement carrying the tag writes them, since the list
            # describes the item and not the placement.
            self._restore_appearances(item, tag, e)

    def _restore_appearances(self, item: Item, tag, entry: dict) -> None:
        """The face-less appearances of whoever a tag is, from its entry.

        A face-attached one comes back with its face (`_apply_faces`), by name
        — a sidecar refers to nothing by id, and a face has no name of its own
        to refer to.
        """
        rows = entry.get("appearances")
        if not isinstance(rows, list):
            return
        subject = self.session.execute(
            select(Subject).where(Subject.tag_id == tag.id)
        ).scalars().first()
        if subject is None:
            return
        have = self.session.execute(select(ItemSubject).where(
            ItemSubject.item_id == item.id,
            ItemSubject.subject_id == subject.id,
            ItemSubject.face_id.is_(None),
        )).scalars().first()
        if have is not None:
            return
        for r in rows:
            when = r.get("when") if isinstance(r.get("when"), dict) else {}
            row = ItemSubject(
                item_id=item.id, subject_id=subject.id, face_id=None,
                when_date=when.get("date"), when_age=when.get("age"),
                assigned_by="user", position=int(r.get("position") or 0))
            self.session.add(row)
            self._restore_appearance_box(row, r.get("box"), r.get("points"))

    @staticmethod
    def _points_in(points) -> "str | None":
        """A sidecar's polygon pair list, back to the DB's JSON string.

        Best-effort like every sidecar read: anything malformed restores as
        the plain rectangle the box columns already carry."""
        if not (isinstance(points, list) and len(points) >= 3):
            return None
        try:
            pts = [[float(a), float(b)] for a, b in points]
        except (TypeError, ValueError):
            return None
        return json.dumps(pts)

    def _restore_appearance_box(self, row, box, points=None) -> None:
        """The appearance's subject box, where the folder recorded one."""
        if not (isinstance(box, list) and len(box) == 4):
            return
        from .db import ItemSubjectBox

        try:
            x, y, w, h = (float(v) for v in box)
        except (TypeError, ValueError):
            return
        self.session.flush()
        self.session.add(ItemSubjectBox(
            item_subject_id=row.id, x=x, y=y, w=w, h=h,
            points=self._points_in(points)))

    def _apply_groups_captions_meta(self, item: Item, payload: dict,
                                    by_number: dict[int, File] | None = None
                                    ) -> None:
        for g in payload.get("groups") or []:
            if not g.get("member", True):
                continue
            grp = self._group_by_uid.get(g.get("uid"))
            # Never into a SMART group: its membership is derived, and the
            # refit at the end of the run is what fills it.
            if grp is None or grp.smart_query is not None:
                continue
            exists = self.session.execute(select(ItemGroup.id).where(
                ItemGroup.item_id == item.id, ItemGroup.group_id == grp.id
            )).first()
            if not exists:
                self.session.add(ItemGroup(item_id=item.id, group_id=grp.id))
        for c in payload.get("captions") or []:
            if c.get("text"):
                cap = Caption(
                    item_id=item.id, text=c["text"],
                    position=c.get("position") or 0,
                    # An instruction restored as a description would be trained
                    # on as one; the refs themselves come back in the second
                    # pass, once the items they name exist.
                    kind=c.get("kind") or "caption",
                    pending=bool(c.get("pending")), model=c.get("model") or "",
                    edited=bool(c.get("edited")),
                )
                self.session.add(cap)
                self._restore_caption_tags(cap, c.get("tags") or [])
        self._restore_metadata(item, payload, by_number)
        if payload.get("trashed"):
            gids = [
                str(self._group_by_uid[u].id)
                for u in payload.get("restore_groups") or []
                if u in self._group_by_uid
            ]
            self.session.add(TrashedItem(
                item_id=item.id, original_groups=",".join(gids)
            ))

    def _restore_metadata(self, item: Item, payload: dict,
                          by_number: dict[int, File] | None = None,
                          *, merge: bool = False) -> None:
        """The item's own metadata answers: its pins and its mutes.

        The INDEX is not restored from the payload's top-level `metadata`
        block: that is derived, `_add_files` has already put each file's own
        answers back from `files[].metadata`, and `rebuild_item_metadata`
        below rebuilds the item's index from those. Restoring the derived
        block directly would not survive the item's first active-file change.
        """
        from .db import ItemMetaMute, ItemMetaPin
        from .itemmeta import index_file_metadata, rebuild_item_metadata

        # ON A MERGE THE EXISTING ANSWER WINS. The merge already treats the
        # local item as the survivor, and a pin here is the newer statement in
        # THIS library — the same COALESCE shape every other merge decision
        # takes. Nothing is overwritten; a name the target has no answer for
        # still gains the folder's.
        have_pins = set()
        have_mutes = set()
        if merge:
            have_pins = {
                (n, r or "") for n, r in self.session.execute(
                    select(ItemMetaPin.name, ItemMetaPin.raw)
                    .where(ItemMetaPin.item_id == item.id)).all()
            }
            have_mutes = {n for (n,) in self.session.execute(
                select(ItemMetaMute.name)
                .where(ItemMetaMute.item_id == item.id)).all()}
        for name in payload.get("meta_mutes") or []:
            if name and name not in have_mutes:
                self.session.add(ItemMetaMute(item_id=item.id, name=name))
                have_mutes.add(name)
        by_number = by_number or {}
        for p in payload.get("meta_pins") or []:
            if not p.get("name"):
                continue
            if (p["name"], p.get("raw") or "") in have_pins:
                continue
            src = by_number.get(p.get("source_file"))
            self.session.add(ItemMetaPin(
                item_id=item.id, name=p["name"],
                mtype=p.get("mtype") or "text", num_value=p.get("num_value"),
                text_value=p.get("text_value"), raw=p.get("raw") or "",
                source_file_id=src.id if src is not None else None,
            ))
            have_pins.add((p["name"], p.get("raw") or ""))
        self.session.flush()
        rebuild_item_metadata(self.session, item.id)

    def _meta_names(self, names) -> list[str]:
        """Normalize a sidecar meta-tag list (captions and tag groups share one
        namespace) and register every name in the catalog, the same way the
        endpoints do — a meta tag survives its last use."""
        out: list[str] = []
        seen: set[str] = set()
        for raw in names or []:
            name = " ".join(str(raw).split())[:64]
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
            if self.session.execute(
                select(LinkTag).where(LinkTag.name == name, LIB_META)
            ).scalar_one_or_none() is None:
                self.session.add(LinkTag(name=name))
        return out

    def _ensure_meta_tag(self, raw: str, comment: str = "",
                         description: str = "") -> None:
        """One meta tag, by the endpoints' own normalization. Text is only
        ever ADDED — an existing row belongs to the current library."""
        name = " ".join(str(raw).split())[:64]
        if not name:
            return
        row = self.session.execute(
            select(LinkTag).where(LinkTag.name == name, LIB_META)
        ).scalar_one_or_none()
        if row is None:
            self.session.add(LinkTag(name=name, comment=comment or "",
                                     description=description or ""))
            return
        if comment and not (row.comment or ""):
            row.comment = comment
        if description and not (row.description or ""):
            row.description = description

    def _restore_tag_meta_tags(self, tag_defs: dict[str, dict]) -> None:
        """The meta tags on each tag that carries any.

        ADDED, never replaced: a name already on the tag here is left alone,
        and the current library's own annotations survive an import — the rule
        every catalog restore in this file follows."""
        from .db import TagMetaTag

        for name, d in tag_defs.items():
            names = d.get("meta_tags")
            if not isinstance(names, list) or not names:
                continue
            tag = self._tag_by_name.get(name)
            if tag is None:
                continue
            counts = d.get("meta_counts")
            counts = counts if isinstance(counts, dict) else {}
            have = {row.name: row for row in self.session.execute(
                select(TagMetaTag).where(TagMetaTag.tag_id == tag.id)
            ).scalars().all()}
            for meta in self._meta_names(names):
                try:
                    n = max(0, int(counts.get(meta) or 0))
                except (TypeError, ValueError):
                    n = 0
                row = have.get(meta)
                if row is None:
                    have[meta] = TagMetaTag(tag_id=tag.id, name=meta, count=n)
                    self.session.add(have[meta])
                elif n and not int(row.count or 0):
                    # ADDED, never replaced — the file only fills in what the
                    # library has not said, the rule every catalog restore in
                    # this file follows.
                    row.count = n

    def _restore_places(self, tag_defs: dict[str, dict]) -> None:
        """The location record on every tag that carries one."""
        for name, d in tag_defs.items():
            rec = d.get("place")
            if not isinstance(rec, dict):
                continue
            tag = self._tag_by_name.get(name)
            if tag is None:
                continue
            if self.session.execute(select(Location).where(
                    Location.tag_id == tag.id)).scalars().first() is not None:
                continue
            loc = Location(tag_id=tag.id,
                           name=_place_line(rec),
                           lat=rec.get("lat"), lon=rec.get("lon"))
            self.session.add(loc)
            self.session.flush()

    def _restore_events(self, tag_defs: dict[str, dict]) -> None:
        """The event record on every tag that carries one, and its venues.

        The venues are named by their own identity TAG, so they resolve
        through the same map — and an event's place must be a named one, which
        is what makes that reference stable. A venue whose tag is missing is
        skipped rather than invented.
        """
        for name, d in tag_defs.items():
            rec = d.get("event")
            if not isinstance(rec, dict):
                continue
            tag = self._tag_by_name.get(name)
            if tag is None:
                continue
            if self.session.execute(select(Occasion).where(
                    Occasion.tag_id == tag.id)).scalars().first() is not None:
                continue
            occ = Occasion(tag_id=tag.id,
                           display_name=rec.get("display_name") or "",
                           start_date=rec.get("start_date"),
                           end_date=rec.get("end_date"))
            self.session.add(occ)
            self.session.flush()
            for venue in rec.get("places") or []:
                vtag = self._tag_by_name.get(venue)
                if vtag is None:
                    continue
                loc = self.session.execute(select(Location).where(
                    Location.tag_id == vtag.id)).scalars().first()
                if loc is None:
                    continue
                self.session.add(OccasionPlace(
                    occasion_id=occ.id, location_id=loc.id))

    def _apply_faces(self, item: Item, payload: dict,
                     by_number: dict[int, File]) -> None:
        """Restore the item's faces from its sidecar.

        A face was expensive to establish — a detector run, and then a person
        saying who it is, who played them and how old they are — and until now
        none of it survived a folder round-trip: the sidecar wrote faces and
        nothing ever read them back.

        Subjects travel BY NAME, like everything else a sidecar refers to, so a
        face lands on the identity the tags restored rather than on a database
        id that means nothing in the new library.

        The DESCRIPTOR is not restored, because it is not written: it is
        regenerable from the picture and meaningless outside the model that
        made it. A restored face is matchable again after the next detector
        run, and until then it is still a box with a name on it.
        """
        subjects = self._subject_by_tag_name()
        for fe in payload.get("faces") or []:
            box = fe.get("box") or [0.0, 0.0, 0.0, 0.0]
            if len(box) != 4:
                continue
            file = by_number.get(fe.get("file"))
            face = Face(
                item_id=item.id,
                file_id=file.id if file is not None else item.active_file_id,
                x=float(box[0]), y=float(box[1]),
                w=float(box[2]), h=float(box[3]),
                det_score=fe.get("det_score"),
                model=",".join(fe.get("models") or []),
                # A dismissal is an ANSWER. Losing it means every false
                # positive somebody already rejected is offered again.
                dismissed=bool(fe.get("dismissed")),
            )
            self.session.add(face)
            self.session.flush()
            # The face's OUTLINE, where the folder recorded one — a person's
            # drawing, like the subject boxes.
            oe = fe.get("outline")
            if isinstance(oe, dict):
                ob = oe.get("box")
                if isinstance(ob, list) and len(ob) == 4:
                    try:
                        ox, oy, ow, oh = (float(v) for v in ob)
                    except (TypeError, ValueError):
                        ox = None
                    if ox is not None:
                        self.session.add(FaceOutline(
                            face_id=face.id, x=ox, y=oy, w=ow, h=oh,
                            points=self._points_in(oe.get("points"))))
            # Who it is — a LIST, resolved BY NAME through the same map the
            # tags use, because that is what makes a sidecar portable.
            for r in fe.get("subjects") or []:
                sub_id = subjects.get(r.get("subject") or "")
                if sub_id is None:
                    continue
                when = r.get("when") if isinstance(r.get("when"), dict) else {}
                row = ItemSubject(
                    item_id=item.id, subject_id=sub_id, face_id=face.id,
                    when_date=when.get("date"), when_age=when.get("age"),
                    assigned_by=r.get("assigned_by") or "user",
                    position=int(r.get("position") or 0))
                self.session.add(row)
                self._restore_appearance_box(row, r.get("box"), r.get("points"))
            # WHO IT IS NOT. A refusal is an answer like a dismissal is, and
            # without it the next detection run offers the same wrong name
            # again. The guard fields ride along for the same reason they do
            # everywhere else: a face id is a rowid and gets handed on.
            for who in fe.get("not") or []:
                sub_id = subjects.get(who)
                if sub_id is None:
                    continue
                self.session.add(FaceRejection(
                    face_id=face.id, subject_id=sub_id,
                    model=face.model or "", item_uid=item.uid,
                    box=f"{face.x:.4f},{face.y:.4f},{face.w:.4f},{face.h:.4f}",
                ))

    def _apply_ocr_regions(self, item: Item, payload: dict,
                           by_number: dict[int, File]) -> None:
        """Restore the item's detected text from its sidecar, tree and all.

        The cleanest round trip in the file: nothing travels by id (a child
        is nested under its parent, so there is nothing to remap) and every
        field was written — a corrected string is not regenerable from
        anything. `ord` comes from LIST POSITION, not from the payload: the
        list is the order, one definition.
        """
        def restore(rec: dict, parent_id, ord_: int) -> None:
            box = rec.get("box") or [0.0, 0.0, 0.0, 0.0]
            if len(box) != 4:
                return
            file = by_number.get(rec.get("file"))
            region = TextRegion(
                item_id=item.id,
                file_id=file.id if file is not None else item.active_file_id,
                parent_id=parent_id,
                level=str(rec.get("level") or "block"),
                ord=ord_,
                x=float(box[0]), y=float(box[1]),
                w=float(box[2]), h=float(box[3]),
                quad=ocrlib.pack_quad(rec.get("quad")),
                text=str(rec.get("text") or ""),
                score=rec.get("score"),
                lang=str(rec.get("lang") or ""),
                model=",".join(rec.get("models") or []),
                # A dismissal and a correction are ANSWERS; losing either
                # means re-offering what somebody already settled.
                dismissed=bool(rec.get("dismissed")),
                edited=bool(rec.get("edited")),
            )
            self.session.add(region)
            self.session.flush()
            for i, child in enumerate(rec.get("children") or []):
                if isinstance(child, dict):
                    restore(child, region.id, i)

        for i, rec in enumerate(payload.get("text") or []):
            if isinstance(rec, dict):
                restore(rec, None, i)

    def _apply_item_records(self, item: Item, payload: dict,
                            by_number: dict[int, File]) -> None:
        """The item's own records that hang off no tag and no file.

        Which detectors have run over it, the coordinates a camera recorded
        that nobody has named, and the two kinds of "no, not this one". Each
        was written into the sidecar and read by nothing until now, so a
        folder round trip re-ran every detector, lost every bare GPS fix and
        asked every refused question again.
        """
        for model in payload.get("face_models") or []:
            if not model:
                continue
            have = self.session.execute(select(ItemFaceRun.id).where(
                ItemFaceRun.item_id == item.id,
                ItemFaceRun.model == model,
            )).first()
            if not have:
                self.session.add(ItemFaceRun(item_id=item.id, model=model))

        # A text run is per FILE: `text_runs` names the file by number.
        for rec in payload.get("text_runs") or []:
            if not isinstance(rec, dict) or not rec.get("model"):
                continue
            file = by_number.get(rec.get("file"))
            file_id = file.id if file is not None else item.active_file_id
            have = self.session.execute(select(ItemTextRun.id).where(
                ItemTextRun.item_id == item.id,
                ItemTextRun.file_id == file_id,
                ItemTextRun.model == rec["model"],
            )).first()
            if not have:
                self.session.add(ItemTextRun(
                    item_id=item.id, file_id=file_id, model=rec["model"]))

        for rec in payload.get("locations") or []:
            if not isinstance(rec, dict):
                continue
            lat, lon = rec.get("lat"), rec.get("lon")
            # Matched on the coordinates themselves: an unnamed place has no
            # name to match on, and two pictures taken at one spot share one
            # record — which is the whole point of clustering them.
            loc = None
            if lat is not None and lon is not None:
                loc = self.session.execute(select(Location).where(
                    Location.tag_id.is_(None), Location.lat == lat,
                    Location.lon == lon,
                )).scalars().first()
            if loc is None:
                loc = Location(name=_place_line(rec), lat=lat, lon=lon)
                self.session.add(loc)
                self.session.flush()
            have = self.session.execute(select(ItemLocation.id).where(
                ItemLocation.item_id == item.id,
                ItemLocation.location_id == loc.id,
            )).first()
            if not have:
                self.session.add(ItemLocation(item_id=item.id,
                                              location_id=loc.id))

        for name in payload.get("dismissed_places") or []:
            tag = self._tag_by_name.get(name)
            if tag is None:
                continue
            loc = self.session.execute(select(Location).where(
                Location.tag_id == tag.id)).scalars().first()
            if loc is not None:
                self.session.add(ItemPlaceDismissal(
                    item_id=item.id, location_id=loc.id))
        for name in payload.get("dismissed_events") or []:
            tag = self._tag_by_name.get(name)
            if tag is None:
                continue
            occ = self.session.execute(select(Occasion).where(
                Occasion.tag_id == tag.id)).scalars().first()
            if occ is not None:
                self.session.add(ItemOccasionDismissal(
                    item_id=item.id, occasion_id=occ.id))

    def _subject_by_tag_name(self) -> dict[str, int]:
        """Identity tag name -> subject id, for the faces above.

        Also keyed by DISPLAY name, because a nameless subject has no tag and
        the sidecar falls back to writing its display name there.
        """
        out: dict[str, int] = {}
        for sub, name in self.session.execute(
            select(Subject, Tag.name)
            .outerjoin(Tag, Tag.id == Subject.tag_id)
        ).all():
            if name:
                out[name] = sub.id
            if sub.display_name:
                out.setdefault(sub.display_name, sub.id)
        return out

    def _restore_caption_tags(self, cap, names) -> None:
        """Meta tags on a restored caption. Travels by name (the sidecar has
        no ids)."""
        self.session.flush()   # the Caption needs its id
        for name in self._meta_names(names):
            self.session.add(CaptionTag(caption_id=cap.id, name=name))

    def _create_item(self, folder: Path, payload: dict, adopt: bool) -> Item:
        item = Item(
            uid=payload["uid"],
            name=payload.get("name") or "",
            kind=payload.get("kind") or "image",
            hidden=bool(payload.get("hidden")),
            # The capture date somebody TYPED (or the -1 that says there is
            # none). The file's own EXIF is re-indexed from the bytes and the
            # events' span from the tags, but this one overrules both and
            # nothing else can bring it back. Normalized: a sidecar written
            # while the Python API stored date-width values carries 8 digits,
            # and restoring it verbatim would plant the value the widening
            # exists to prevent.
            taken_at=normalize_taken(payload.get("taken_at")),
        )
        created = _dt(payload.get("created_at"))
        if created:
            item.created_at = created
        last = _dt(payload.get("last_imported_at"))
        if last:
            item.last_imported_at = last
        updated = _dt(payload.get("updated_at"))
        if updated:
            item.updated_at = updated
        self.session.add(item)
        self.session.flush()
        by_number = self._add_files(item, folder, payload, adopt=adopt)
        active = by_number.get(payload.get("active_file"))
        if active is not None:
            item.active_file_id = active.id
        self._apply_tags(item, payload)
        self._apply_groups_captions_meta(item, payload, by_number)
        self._apply_faces(item, payload, by_number)
        self._apply_ocr_regions(item, payload, by_number)
        self._apply_item_records(item, payload, by_number)
        return item

    def _merge_into(self, target: Item, folder: Path, payload: dict) -> None:
        """Union the payload into an existing, visually-matching item: add its
        missing files past the target's numbering, and its tags/captions/groups
        the target doesn't have yet."""
        from sqlalchemy import func

        existing_shas = set(self.session.execute(
            select(File.sha256).where(File.item_id == target.id)
        ).scalars().all())
        off = int(self.session.execute(
            select(func.coalesce(func.max(File.number), 0))
            .where(File.item_id == target.id)
        ).scalar_one())
        merged_files = self._add_files(target, folder, payload, offset=off,
                                       skip_shas=existing_shas)
        self._restore_metadata(target, payload, merged_files, merge=True)

        have_tags = set(self.session.execute(
            select(Tag.name).join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id == target.id)
        ).scalars().all())
        for e in payload.get("tags") or []:
            if e.get("name") in have_tags:
                continue
            tag = self._tag_by_name.get(e.get("name"))
            if tag is None:
                continue
            self.session.add(ItemTag(
                item_id=target.id, tag_id=tag.id,
                negative=bool(e.get("negative")),
                pending=bool(e.get("pending")),
            ))
            have_tags.add(e["name"])

        have_captions = {
            c.text.strip() for c in self.session.execute(
                select(Caption).where(Caption.item_id == target.id)
            ).scalars().all()
        }
        pos = len(have_captions)
        for c in payload.get("captions") or []:
            text = (c.get("text") or "").strip()
            if text and text not in have_captions:
                # The kind travels even on the merge path, where the flags do
                # not: a dropped kind turns an instruction into a description,
                # which is a different claim about the picture rather than a
                # lost detail about the caption.
                cap = Caption(item_id=target.id, text=text, position=pos,
                              kind=c.get("kind") or "caption")
                self.session.add(cap)
                self._restore_caption_tags(cap, c.get("tags") or [])
                have_captions.add(text)
                pos += 1

        for g in payload.get("groups") or []:
            if not g.get("member", True):
                continue
            grp = self._group_by_uid.get(g.get("uid"))
            if grp is None or grp.smart_query is not None:
                continue
            exists = self.session.execute(select(ItemGroup.id).where(
                ItemGroup.item_id == target.id, ItemGroup.group_id == grp.id
            )).first()
            if not exists:
                self.session.add(ItemGroup(item_id=target.id,
                                           group_id=grp.id))

    # ---- second pass: links + sequences --------------------------------------

    def _resolve_uid(self, uid: Optional[str]) -> Optional[int]:
        if not uid:
            return None
        if uid in self.item_by_uid:
            return self.item_by_uid[uid]
        return self.session.execute(
            select(Item.id).where(Item.uid == uid)
        ).scalar_one_or_none()

    def _apply_links(self, payload: dict) -> None:
        iid = self._resolve_uid(payload["uid"])
        if iid is None:
            return
        item = self.session.get(Item, iid)
        link_id = self._resolve_uid(payload.get("link"))
        if link_id is not None and item.link_item_id is None:
            item.link_item_id = link_id
        for r in payload.get("relationships") or []:
            if r.get("direction") != "out":
                continue   # each link is serialized on both ends; create once
            other = self._resolve_uid(r.get("other"))
            if other is None:
                continue
            kind = r.get("kind") or "manual"
            rel = self.session.execute(select(Relationship).where(
                Relationship.from_item_id == iid,
                Relationship.to_item_id == other,
                Relationship.kind == kind,
            )).scalars().first()
            if rel is None:
                rel = Relationship(from_item_id=iid, to_item_id=other,
                                   kind=kind, meta=r.get("meta") or "")
                self.session.add(rel)
                self.session.flush()
            for lt in r.get("link_tags") or []:
                # A plain name; the namespace row itself (with its comment)
                # came across in `_prime_catalogs`.
                name = lt if isinstance(lt, str) else lt.get("name")
                if not name:
                    continue
                if not self.session.execute(select(RelationshipTag.id).where(
                    RelationshipTag.relationship_id == rel.id,
                    RelationshipTag.name == name,
                )).first():
                    self.session.add(RelationshipTag(
                        relationship_id=rel.id, name=name))
                if self.session.execute(
                    select(LinkTag).where(LinkTag.name == name, LIB_META)
                ).scalar_one_or_none() is None:
                    self.session.add(LinkTag(name=name))

    def _apply_caption_refs(self, payload: dict) -> None:
        """An instruction's reference images, in the SECOND pass.

        They name other items, which may not have been imported yet when the
        caption itself was restored — the same reason relationships wait. The
        caption is found again by its exact TEXT, which is the key the
        merge-into-existing path already dedupes captions on.
        """
        iid = self._resolve_uid(payload["uid"])
        if iid is None:
            return
        by_text: dict[str, list[str]] = {}
        for c in payload.get("captions") or []:
            text = (c.get("text") or "").strip()
            if text and (c.get("kind") or "caption") == "instruction" \
                    and c.get("refs"):
                by_text[text] = list(c["refs"])
        if not by_text:
            return
        for cap in self.session.execute(
            select(Caption).where(Caption.item_id == iid)
        ).scalars().all():
            refs = by_text.get((cap.text or "").strip())
            if not refs:
                continue
            existing = {
                r for r, in self.session.execute(
                    select(CaptionRef.item_id)
                    .where(CaptionRef.caption_id == cap.id)
                ).all()
            }
            pos = len(existing)
            for uid in refs:
                other = self._resolve_uid(uid)
                if other is None or other in existing:
                    continue
                self.session.add(CaptionRef(
                    caption_id=cap.id, item_id=other, position=pos))
                existing.add(other)
                pos += 1

    def _ensure_sequence(self, payload: dict) -> None:
        """Get-or-create the Sequence a container item defines (its uid is
        recorded in the container's ``sequence_def`` and referenced by every
        member's ``sequences`` entries)."""
        seq_def = payload.get("sequence_def")
        if seq_def is None:
            return
        iid = self._resolve_uid(payload["uid"])
        if iid is None:
            return
        uid = seq_def.get("uid")
        seq = self._sequence_by_uid(uid) if uid else None
        if seq is None:
            seq = self.session.execute(
                select(Sequence).where(Sequence.item_id == iid)
            ).scalars().first()
        if seq is None:
            seq = Sequence(
                name=seq_def.get("name") or payload.get("name") or "",
                kind=seq_def.get("kind") or "manual",
                source_name=seq_def.get("source_name") or "",
                item_id=iid,
            )
            if uid:
                seq.uid = uid
            self.session.add(seq)
            self.session.flush()

    def _apply_membership(self, payload: dict) -> None:
        iid = self._resolve_uid(payload["uid"])
        if iid is None:
            return
        item = self.session.get(Item, iid)
        for se in payload.get("sequences") or []:
            seq = self._sequence_by_uid(se.get("sequence"))
            if seq is None:
                continue
            # The probe is per (sequence, item, POSITION): an item may sit at
            # several positions (a book's repeated blank page), and probing
            # by item alone dropped every occurrence after the first.
            exists = self.session.execute(select(SequenceItem.id).where(
                SequenceItem.sequence_id == seq.id,
                SequenceItem.item_id == iid,
                SequenceItem.position == (se.get("position") or 0),
            )).first()
            if not exists:
                self.session.add(SequenceItem(
                    sequence_id=seq.id, item_id=iid,
                    position=se.get("position") or 0,
                ))
        main = payload.get("main_sequence")
        if main and item.main_sequence_id is None:
            seq = self._sequence_by_uid(main)
            if seq is not None:
                item.main_sequence_id = seq.id

    def _sync_container(self, payload: dict) -> None:
        """Borrowed container thumbnail — recomputed once all memberships are
        in (a container processed before its members would pick nothing)."""
        if payload.get("sequence_def") is None:
            return
        iid = self._resolve_uid(payload["uid"])
        if iid is None:
            return
        from .sequences import sync_container

        seq = self.session.execute(
            select(Sequence).where(Sequence.item_id == iid)
        ).scalars().first()
        if seq is not None:
            self.session.flush()
            sync_container(self.session, seq.id)

    def _sequence_by_uid(self, uid: Optional[str]) -> Optional[Sequence]:
        if not uid:
            return None
        return self.session.execute(
            select(Sequence).where(Sequence.uid == uid)
        ).scalars().first()

    # ---- rankings -----------------------------------------------------------

    def _prime_tag_sets(self, src: Session) -> None:
        """The source's tag sets, whole, by key — the destination's own wins
        where the key exists. A locked built-in copy an older build installed
        stays behind (the template is package data here)."""
        from .db import TagSet
        from .ops import tagsets as tagsets_ops

        for rec in src.execute(select(TagSet).order_by(TagSet.position, TagSet.id)
                               ).scalars().all():
            if rec.builtin:
                continue
            if tagsets_ops.by_key(self.session, rec.key) is not None:
                continue
            doc = tagsets_ops._doc_of(src, rec)
            row = TagSet(key=rec.key, name=rec.name, description=rec.description or "",
                         version=int(rec.version or 0), builtin=False,
                         enabled=bool(rec.enabled),
                         position=tagsets_ops._next_position(self.session))
            self.session.add(row)
            self.session.flush()
            tagsets_ops._write_doc(self.session, row, doc)
            self.stats.tag_sets += 1
        self.session.flush()

    def _prime_rankings(self, src: Session) -> None:
        """Recreate the source's ranking axes, read from its own table, and
        their POOLS by name. **The two libraries' axes are matched by
        NAME** — it was the `prefix` until a ranking stopped owning a tag
        namespace (rung v31), and the name is what is left that a person
        chose. The current library wins on a name it already has (its
        fields stay), and gains every pool name of the source's it lacks
        — a judgment names its pool by name, so the name has to exist
        here before the items land. A ranking with no pool at all (a row
        somebody inserted directly) gets its unnamed one, since every
        judgment must belong to one."""
        from .db import Ranking, RankingPool

        for rec in src.execute(select(Ranking).order_by(Ranking.name)
                               ).scalars().all():
            if not rec.name:
                continue
            have = self.session.execute(select(Ranking).where(
                Ranking.name == rec.name)).scalars().first()
            if have is None:
                have = Ranking(
                    name=rec.name,
                    scope=rec.scope or "",
                    bucket_lo=int(rec.bucket_lo or 0),
                    bucket_hi=int(rec.bucket_hi if rec.bucket_hi
                                  is not None else 9),
                )
                self.session.add(have)
                self.session.flush()
            mine = {lg.name for lg in self.session.execute(
                select(RankingPool).where(
                    RankingPool.ranking_id == have.id)).scalars().all()}
            for lg in src.execute(
                    select(RankingPool)
                    .where(RankingPool.ranking_id == rec.id)
                    .order_by(RankingPool.position, RankingPool.id)
                    ).scalars().all():
                if lg.name not in mine:
                    self.session.add(RankingPool(
                        ranking_id=have.id, name=lg.name,
                        position=int(lg.position or 0)))
                    mine.add(lg.name)
        self.session.flush()
        for row in self.session.execute(select(Ranking)).scalars().all():
            has_one = self.session.execute(select(RankingPool.id).where(
                RankingPool.ranking_id == row.id)).first()
            if has_one is None:
                self.session.add(RankingPool(ranking_id=row.id, name=""))
        self.session.flush()

    def _apply_ranking_records(self, payload: dict) -> None:
        """The item's judgments and not-applicable marks, by ranking NAME
        and the other item's uid. Judgments restore only for items this run
        CREATED — they are deliberately not unique rows, so re-importing a
        folder over the same library must not double the evidence.
        Dismissals are unique per (ranking, item) and restore for everyone."""
        from .db import (Ranking, RankingDismissal, RankingJudgment,
                         RankingPool)

        iid = self._resolve_uid(payload.get("uid"))
        if iid is None:
            return
        by_name: dict[str, Ranking] = {
            r.name: r for r in self.session.execute(
                select(Ranking)).scalars().all()
        }
        pool_ids: dict[tuple[int, str], int] = {
            (lg.ranking_id, lg.name): lg.id
            for lg in self.session.execute(select(RankingPool)
                                           ).scalars().all()}

        def _pool(ranking: Ranking, name: str) -> int:
            key = (ranking.id, name)
            if key not in pool_ids:
                lg = RankingPool(ranking_id=ranking.id, name=name)
                self.session.add(lg)
                self.session.flush()
                pool_ids[key] = lg.id
            return pool_ids[key]
        for rname in payload.get("ranking_na") or []:
            ranking = by_name.get(str(rname))
            if ranking is None:
                continue
            have = self.session.execute(select(RankingDismissal).where(
                RankingDismissal.ranking_id == ranking.id,
                RankingDismissal.item_id == iid)).scalars().first()
            if have is None:
                self.session.add(RankingDismissal(
                    ranking_id=ranking.id, item_id=iid))
        if payload.get("uid") not in self._created_uids:
            return
        for rec in payload.get("ranking_judgments") or []:
            ranking = by_name.get(str(rec.get("ranking") or ""))
            other = self._resolve_uid(rec.get("other"))
            outcome = str(rec.get("outcome") or "")
            if ranking is None or other is None or \
                    outcome not in ("a", "b", "tie", "skip"):
                continue
            # The pool by NAME; an entry without the key is the unnamed
            # first pool (made here if the ranking somehow lacks it).
            self.session.add(RankingJudgment(
                ranking_id=ranking.id,
                pool_id=_pool(ranking, str(rec.get("pool") or "")),
                a_item_id=iid, b_item_id=other, outcome=outcome))
        self.session.flush()

    def _rebuild_smart_groups(self) -> None:
        """Smart memberships never travel either — the group came back with
        its query from `groups.json`, and this refit is what fills it."""
        from .ops import smartgroups
        from .ops.context import Ctx

        smartgroups.rebuild_all(Ctx(session=self.session, source="cli"))


def merge_library(session: Session, store: ItemStore, cfg: Config,
                  source: Path, dry_run: bool = False) -> MergeStats:
    return LibraryMerger(session, store, cfg).run(source, dry_run=dry_run)
