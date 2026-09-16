"""Synthetic-library seeder for the perf smoke tests.

Core ``insert().values`` batches, no files on disk, sidecars off — a 50k-item
library seeds in a couple of seconds. Shapes follow a Zipf-ish tag
distribution so the popular-tag paths (grouped counts, prefilter probes) see
realistic skew.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import insert, select, text

from media_compost.ui.config import UiConfig
from media_compost.db import (
    Caption, CaptionTag, Database, File, Group, GroupParent, GroupTag, Item,
    ItemGroup, ItemMetadata, ItemSubject, ItemTag, Location, Occasion,
    Relationship, RelationshipTag, Subject, Tag, TagImplication, TagMetaTag,
)


#: Whether a WALL-CLOCK reading means anything in this process.
#:
#: The perf files assert two different kinds of thing. The SHAPE assertions —
#: a LIMIT on the page, one aggregate for the facets, a statement count that
#: does not grow with the library — are deterministic, and they are what
#: actually catches a regression here. The CLOCK is the backstop, and it can
#: only be read on a machine that is not doing something else: under `-n 8`
#: there are seven other workers on the same cores, so a two-second ceiling
#: measures how the run was scheduled rather than what the query costs.
#:
#: It was flaking exactly that way — `test_every_condition_pages_in_bounded_
#: sql` failed once in a parallel `-m ""` run and passed on its own, which is
#: the signature. The rule is not "make the ceiling generous": a bound loose
#: enough to survive eight-way contention is loose enough to miss the
#: regression it exists for. So the clock is SKIPPED there and asserted in a
#: serial run, where it means what it says.
def timed_runs() -> bool:
    """False under xdist, where nothing can be timed honestly."""
    return not os.environ.get("PYTEST_XDIST_WORKER")


def perf_items(default: int) -> int:
    """How many items the perf modules seed — `MEDIA_COMPOST_PERF_ITEMS`.

    THE DEFAULT IS SMALL AND THE KNOB IS THE POINT. What these tests assert
    is SHAPES (a LIMIT on the page, one aggregate for the facets, a
    statement count that does not grow), and a shape is the same shape at
    any size — so the default is chosen for how long the suite takes rather
    than for how much it proves: 50,000 items seeds in 3.3 s into a 70 MB
    file, where 1.5M is **156 s and 2.2 GB** (4.2 with the WAL), which is a
    thing to do deliberately and not a thing a `pytest -m perf` should do.

    The full-size sweeps that found most of this repo's real regressions
    were manual scripts; this is that run, as the same tests:

        MEDIA_COMPOST_PERF_ITEMS=1500000 pytest -m perf -q

    The wall-clock ceilings are written for the default and are generous
    multiples rather than absolute numbers, so a big run may legitimately
    exceed one — read a failure there as "this is what it costs at 1.5M"
    and check the SHAPE assertions, which hold at every size.
    """
    return int(os.environ.get("MEDIA_COMPOST_PERF_ITEMS") or default)


def perf_tags(default: int) -> int:
    """The catalog's size — `MEDIA_COMPOST_PERF_TAGS`, the other axis.

    Separate from the item count because they break different things: a
    read that walks the catalog (the tags list, the autocomplete) is
    unmoved by a million items, and the bug that went quadratic in the
    tag set was invisible below 90,000 tags.
    """
    return int(os.environ.get("MEDIA_COMPOST_PERF_TAGS") or default)


#: The sites a bulk-imported tag carries its counts under. A real dump gives
#: a tag about two of these, which is why `meta_per_tag` exists at all: the
#: autocomplete's tie-break reads them, so a catalog with none of them cannot
#: see that half of the query get slow.
_META_SITES = ("tumblr", "twitter", "danbooru", "gelbooru", "pixiv", "e621")


def seed_library(data_dir: Path, *, items: int = 50_000, tags: int = 2_000,
                 groups: int = 60, tags_per_item: int = 4,
                 meta_per_tag: int = 0, rich: bool = False,
                 records: int = 1) -> Database:
    """Seed a synthetic library.

    ``rich`` adds the RECORDS the record conditions ask about — subjects
    with dated appearances, addressed places, dated events, captions and
    instructions with their meta tags, links with theirs, indexed metadata,
    capture dates, colour keys and value tags. It is what lets a search perf
    test cover every condition kind against a library that can actually
    ANSWER each of them: a condition matching nothing is a condition whose
    cost nobody has measured (the compiled clause is never reached, the
    residue never runs, and a page of no rows is fast whatever it did).
    """
    db = Database(UiConfig(data_dir=data_dir))
    with db.session() as s:
        s.execute(insert(Tag), [{"name": f"t{i}"} for i in range(tags)])
        # A short implication chain so tag probes exercise the closure path.
        s.execute(insert(TagImplication), [
            {"tag_id": 2, "implies_id": 1}, {"tag_id": 3, "implies_id": 2},
        ])
        s.execute(insert(Group), [
            {"name": f"g{i}", "uid": f"g-{i}"} for i in range(groups)])
        gids = list(s.execute(select(Group.id).order_by(Group.id)).scalars())
        s.execute(insert(GroupParent), [
            {"group_id": gids[i], "parent_group_id": gids[i // 4]}
            for i in range(4, groups)
        ])
        s.execute(insert(GroupTag), [
            {"group_id": gids[0], "tag_id": 5, "negative": False}])
        s.execute(insert(Item), [
            {"uid": f"p{i:07d}", "name": f"item {i}", "kind": "image"}
            for i in range(items)])
        ids = list(s.execute(select(Item.id).order_by(Item.id)).scalars())
        s.execute(insert(File), [
            {"item_id": iid, "number": 1, "path": "files/1.png",
             "sha256": f"s{iid}", "width": 640 + iid % 1280,
             "height": 480 + iid % 720, "bytes": 1000, "format": "png"}
            for iid in ids])
        s.execute(text(
            "UPDATE items SET active_file_id = "
            "(SELECT id FROM files WHERE files.item_id = items.id)"))
        assignments = []
        for n, iid in enumerate(ids):
            for k in range(tags_per_item):
                # Zipf-ish: low tag ids are carried by many items.
                tid = 1 + ((n * (k + 1) * 7919) % (tags // (k + 1)))
                assignments.append({"item_id": iid, "tag_id": tid,
                                    "negative": False, "pending": False})
        seen = set()
        rows = []
        for a in assignments:
            key = (a["item_id"], a["tag_id"])
            if key not in seen:
                seen.add(key)
                rows.append(a)
        s.execute(insert(ItemTag), rows)
        s.execute(insert(ItemGroup), [
            {"item_id": iid, "group_id": gids[n % groups]}
            for n, iid in enumerate(ids) if n % 3 == 0])
        if meta_per_tag:
            tids = list(s.execute(select(Tag.id).order_by(Tag.id)).scalars())
            s.execute(insert(TagMetaTag), [
                {"tag_id": tid, "name": _META_SITES[(n + k) % len(_META_SITES)],
                 "count": (tid * 7919 + k) % 5000}
                for n, tid in enumerate(tids) for k in range(meta_per_tag)])
        if rich:
            _seed_records(s, ids, tags, records)
        s.commit()
    return db


#: How much of each kind the rich seed makes, at ``records=1``. Small on
#: purpose: what a search condition costs is decided by the ITEM table it
#: filters, not by how many places exist — the one exception (`PLACE:` over
#: thousands of places) is measured by its own case. `records` multiplies all
#: three, which is what the SCALING tests need: a library four times the
#: size has to be four times the size in every axis, or a per-row read over
#: a table that did not grow reads as a
#: read that scales.
_SUBJECTS = 60
_PLACES = 40
_EVENTS = 30


def _seed_records(s, ids: list[int], tags: int, records: int = 1) -> None:
    """The records, captions, links, metadata and dates a search asks about.

    Everything here rides on TAGS that already exist (a subject, a place and
    an event are extra data on a tag), so the identity tags are minted here
    and assigned to a slice of the library — which is what makes the record
    conditions match something.
    """
    n = len(ids)
    n_subjects = _SUBJECTS * records
    n_places = _PLACES * records
    n_events = _EVENTS * records
    # EVERY record gets items. A slice taken every Nth item and filed under
    # `k % <count>` only ever reaches the multiples of N — 60 subjects with
    # every fifth item under `k % 60` gives twelve of them items and 48 none,
    # so a search for one of the 48 measures an empty answer. `k // N` walks
    # the records instead, which is what makes a named condition below match.
    # ---- identity tags, one namespace each ---------------------------------
    names = ([f"subject:s{i}" for i in range(n_subjects)]
             + [f"place:p{i}" for i in range(n_places)]
             + [f"event:e{i}" for i in range(n_events)]
             # VALUE: reads a tag's basename as a number — a namespace of
             # them, so `VALUE:height>=170cm` has a set to resolve.
             + [f"height:{150 + i}cm" for i in range(40)])
    s.execute(insert(Tag), [{"name": x} for x in names])
    tid = {t.name: t.id for t in s.execute(
        select(Tag).where(Tag.name.in_(names))).scalars()}

    # ---- the records themselves --------------------------------------------
    s.execute(insert(Subject), [
        {"tag_id": tid[f"subject:s{i}"], "display_name": f"Subject {i}",
         "since_date": 19700101 + i * 10000}
        for i in range(n_subjects)])
    s.execute(insert(Location), [
        {"tag_id": tid[f"place:p{i}"],
         "name": f"{i} Example Street, Town {i % 7}, Country {i % 3}",
         "lat": 50.0 + i / 100, "lon": 8.0 + i / 100}
        for i in range(n_places)])
    s.execute(insert(Occasion), [
        {"tag_id": tid[f"event:e{i}"], "display_name": f"Event {i}",
         "start_date": 20100101 + i * 10000,
         "end_date": 20100107 + i * 10000}
        for i in range(n_events)])
    subj_ids = list(s.execute(select(Subject.id).order_by(Subject.id))
                    .scalars())

    # ---- assignments (the identity tag IS the assignment) ------------------
    rows = []
    for k, iid in enumerate(ids):
        if k % 5 == 0:
            rows.append({"item_id": iid,
                         "tag_id": tid[f"subject:s{(k // 5) % n_subjects}"],
                         "negative": False, "pending": False})
        if k % 7 == 0:
            rows.append({"item_id": iid,
                         "tag_id": tid[f"place:p{(k // 7) % n_places}"],
                         "negative": False, "pending": False})
        if k % 11 == 0:
            rows.append({"item_id": iid,
                         "tag_id": tid[f"event:e{(k // 11) % n_events}"],
                         "negative": False, "pending": False})
        if k % 3 == 0:
            rows.append({"item_id": iid,
                         "tag_id": tid[f"height:{150 + k % 40}cm"],
                         "negative": False, "pending": False})
    s.execute(insert(ItemTag), rows)

    # An APPEARANCE is what dates a subject on an item — `subject:x#12` reads
    # these rather than the tag.
    s.execute(insert(ItemSubject), [
        {"item_id": iid, "subject_id": subj_ids[(k // 5) % n_subjects],
         "when_date": 19900101 + (k % 30) * 10000, "assigned_by": "user"}
        for k, iid in enumerate(ids) if k % 5 == 0])

    # ---- captions and instructions, with their meta tags -------------------
    s.execute(insert(Caption), [
        {"item_id": iid, "text": f"a picture of number {k}", "position": 0,
         "kind": "instruction" if k % 40 == 0 else "caption"}
        for k, iid in enumerate(ids) if k % 4 == 0])
    cap_ids = list(s.execute(select(Caption.id).order_by(Caption.id)).scalars())
    s.execute(insert(CaptionTag), [
        {"caption_id": cid, "name": "en" if k % 2 else "de"}
        for k, cid in enumerate(cap_ids)])

    # ---- links, with theirs ------------------------------------------------
    s.execute(insert(Relationship), [
        {"from_item_id": ids[k], "to_item_id": ids[k + 1], "kind": "edit"}
        for k in range(0, n - 1, 9)])
    rel_ids = list(s.execute(select(Relationship.id)
                             .order_by(Relationship.id)).scalars())
    s.execute(insert(RelationshipTag), [
        {"relationship_id": rid, "name": "derived" if k % 2 else "original"}
        for k, rid in enumerate(rel_ids)])

    # ---- indexed metadata, capture dates and colour ------------------------
    s.execute(insert(ItemMetadata), [
        {"item_id": iid, "name": "camera", "mtype": "text",
         "text_value": f"Camera {(k // 2) % 12}",
         "raw": f"Camera {(k // 2) % 12}"}
        for k, iid in enumerate(ids) if k % 2 == 0])
    s.execute(insert(ItemMetadata), [
        {"item_id": iid, "name": "date_taken", "mtype": "date",
         "num_value": float(20200101000000 + (k % 300) * 1000000),
         "raw": "2020"}
        for k, iid in enumerate(ids) if k % 2 == 0])
    # A TYPED capture date on a slice of them (the override that beats EXIF),
    # and colour on every file — both are plain column writes.
    s.execute(text(
        "UPDATE items SET taken_at = 20210101000000 + (id % 300) * 1000000 "
        "WHERE id % 6 = 0"))
    s.execute(text(
        "UPDATE files SET color_key = (id * 7919) % 65536, "
        "color_sig = (id * 104729) % 72057594037927936"))
