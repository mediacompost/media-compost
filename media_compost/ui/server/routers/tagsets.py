"""`/api/tag-sets` — the imported tag lists (`ops/tagsets.py`).

Thin: every write is an op, every refusal an `OpError` the app maps to HTTP.
The two reads the rest of the app leans on — a tag's capsules and its
descriptions — are NOT here: they ride the tags endpoints (`/api/tags/names`,
`/api/tags/rows`), where the row is.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from media_compost.ops import Ctx, tagcatalog, tagsets as ops
from sqlalchemy import func, select

from media_compost.db import Tag, TagSet, TagSetEntry

from ..deps import get_ctx, get_library, get_session
from ..schemas import (
    TagSetBulkIn,
    TagSetBulkOut,
    TagSetCategoryCreate,
    TagSetCategoryOut,
    TagSetCategoryMove,
    TagSetCategoryUpdate,
    TagSetCreate,
    TagSetDetail,
    TagSetDuplicate,
    TagSetEnabled,
    TagSetEntriesOut,
    TagSetEntryCreate,
    TagSetEntryOut,
    TagSetEntryUpdate,
    TagSetImportIn,
    TagSetMetaTagCreate,
    TagSetMetaTagOut,
    TagSetMetaTagUpdate,
    TagSetImportOut,
    TagSetOut,
    TagSetAddIn,
    TagSetAddOut,
    TagSetSyncIn,
    TagSetSyncOut,
    TagSetTreeCategory,
    TagSetTreeOut,
    TagSetTreeSet,
    TagSetUpdate,
)

router = APIRouter(prefix="/api/tag-sets", tags=["tag-sets"])


def _says(d) -> dict:
    """`ops.SetSays` as the wire's `TagSetText` — the dataclass's own
    shaper, so the tags list, the autocomplete and `/describe` cannot
    answer differently about the same tag."""
    return d.as_dict()



def _out(ts: TagSet, counts: dict[int, tuple[int, int]]) -> TagSetOut:
    n_e, n_c = counts.get(ts.id, (0, 0))
    outdated = False
    if ts.builtin:
        outdated = ops.is_outdated(ts, ops.template_stamps(), n_e)
        # A BUILT-IN THAT HAS NEVER BEEN SWITCHED ON HOLDS NOTHING, and a row
        # saying "0 entries" is the one fact somebody deciding whether to
        # switch it on must not be told. Its size is the shipped file's.
        if not n_e:
            info = ops.template_info(ts.key)
            if info is not None:
                n_e, n_c = info.names, info.categories
    return TagSetOut(id=ts.id, key=ts.key, name=ts.name,
                     description=ts.description or "",
                     version=int(ts.version or 0), builtin=bool(ts.builtin),
                     outdated=outdated, enabled=bool(ts.enabled),
                     aliases_enabled=bool(ts.aliases_enabled),
                     implications_enabled=bool(ts.implications_enabled),
                     position=int(ts.position or 0), entries=n_e, categories=n_c)


def _rows(s: Session) -> list[TagSetOut]:
    """Every pill, the LIBRARY'S FIRST.

    `ops.all_sets` is about tag sets and leaves the library's own row
    out; here it leads, because the Tags tab's first pill is the library
    itself. It may not exist yet — it is created by the first thing that
    needs it — and until then there is nothing to list, which the frontend
    reads as "the Library pill with no categories in it".
    """
    counts = ops.counts_of(s)
    out = [_out(ts, counts) for ts in ops.all_sets(s)]
    lib = ops.library_set(s)
    # ALWAYS A LIBRARY PILL, row or no row. The row is lazy — a library that
    # has filed nothing has never needed one — but the library is always
    # there and is always the first pill, so it is SYNTHESIZED at id 0 until
    # something brings the row into being. Id 0 is safe to hand out: nothing
    # addresses the library's set by id (its categories are made through
    # `POST /api/tags/categories`, which is what creates the row), and the
    # frontend only ever compares it.
    row = _out(lib, counts) if lib is not None else TagSetOut(
        id=0, key=ops.LIBRARY_KEY, name=ops.LIBRARY_NAME)
    row.library = True
    # Not the number of ENTRY rows (there are none) — the names the library
    # actually has, which is what the pill's count means everywhere else.
    row.entries = int(s.execute(
        select(func.count()).select_from(Tag)).scalar() or 0)
    out.insert(0, row)
    return out


def _one(s: Session, set_id: int) -> TagSetOut:
    return _out(ops.by_id(s, set_id), ops.counts_of(s))


def _detail(s: Session, set_id: int) -> TagSetDetail:
    ts = ops.by_id(s, set_id)
    trails = ops.category_trails(s, ts.id)
    counts = ops.category_subtree_counts(s, ts.id)
    base = _out(ts, ops.counts_of(s))
    return TagSetDetail(
        **base.model_dump(),
        uncategorized=counts.get(None, 0),
        record_counts=ops.record_counts(s, ts.id),
        category_rows=[TagSetCategoryOut(
            id=c.id, parent_id=c.parent_id, name=c.name,
            icon=c.icon or "", hidden=bool(c.hidden),
            aliases=c.aliases, implications=c.implications,
            position=int(c.position or 0),
            trail=trails.get(c.id, [c.name]), count=counts.get(c.id, 0))
            for c in ops.categories_of(s, ts.id)])


def _behind(s: Session, lib, set_id: int, on: bool, records: bool = False):
    """The "behind the library" narrowing, as the id set `_entries_stmt`
    takes — or None when neither filter is on.

    TWO KINDS OF ADVICE, one narrowing. What a set says a name ENTAILS and
    what it says the name IS are separate questions with separate answers,
    and asking for both means "anything the library has not caught up with"
    — the UNION, not the intersection: an entry behind on its comment is
    behind, whatever its implications do.

    CACHED ON THE REVISION, each on its own key: the filtered list is paged
    and its `locate` asks the same question again, and each answer is a walk
    over every candidate entry in the set.
    """
    if not on and not records:
        return None
    out: set[int] = set()
    if on:
        out |= lib.db.cached(s, f"tagset-behind-{set_id}",
                             lambda: ops.behind_entry_ids(s, set_id))
    if records:
        out |= lib.db.cached(s, f"tagset-behind-records-{set_id}",
                             lambda: ops.behind_records_entry_ids(s, set_id))
    return out


def _entry_out(s: Session, rows: list[TagSetEntry], set_id: int, lib=None
               ) -> list[TagSetEntryOut]:
    ids = [r.id for r in rows]
    al, im = ops.aliases_of(s, ids), ops.implications_of(s, ids)
    # WHAT AN ALIAS ROW SPELLS — one statement for the page.
    of = ops.alias_targets(s, rows)
    mt = ops.meta_of(s, ids)
    # WHAT THE LIBRARY HAS NOT ACTED ON — computed for the page, since the
    # answer is about the library and changes without the set moving at all.
    gap = ops.missing_implications(s, rows)
    # …and the same question for the other kind of advice: what the set says
    # the tag IS that the library's tag is not.
    rec_gap = ops.missing_records(s, rows)
    # AND WHERE THE SWITCH IS OFF, so the row can leave the names out
    # entirely rather than promising something nothing will act on.
    sets_off, cats_off = ops.implication_scopes_off(s, [set_id])
    trails = ops.category_trails(s, set_id)
    # AND WHETHER THE LIBRARY HAS THE TAG AT ALL: one probe for the page,
    # which is what decides whether the row's menu offers to add it.
    have = ops.in_library(s, [r.name for r in rows])
    # …AND HOW MANY PICTURES IT HAS UNDER EACH: the `Library` column, one
    # number that says what the mark used to and says how much besides. The
    # counts come from the library's own cached pass, never a second one.
    from media_compost.ui.server.routers.tags import _effective_counts
    pos = _effective_counts(s, lib)[0] if lib is not None else None
    counts = ops.library_counts(s, [r.name for r in rows], pos)

    def imp_off(cid: Optional[int]) -> bool:
        return set_id in sets_off or (cid is not None and cid in cats_off)
    return [TagSetEntryOut(
        id=r.id, name=r.name, description=r.description or "", count=r.count,
        category_id=r.category_id,
        category_trail=trails.get(r.category_id, []) if r.category_id else [],
        position=int(r.position or 0), alias_of=of.get(r.id),
        aliases=al.get(r.id, []), implies=im.get(r.id, []),
        meta=mt.get(r.id, []),
        missing_implies=gap.get(r.id, []),
        implications_off=imp_off(r.category_id),
        in_library=r.lname in have,
        library_count=counts.get(r.lname),
        comment=r.comment or "",
        **{k: ops.record_of(r, k) for k in ops.RECORD_FIELDS},
        missing_records=rec_gap.get(r.id, []))
        for r in rows]


@router.get("", response_model=list[TagSetOut])
def list_tag_sets(s: Session = Depends(get_session)):
    return _rows(s)


@router.post("", response_model=TagSetOut)
def create_tag_set(body: TagSetCreate, ctx: Ctx = Depends(get_ctx)):
    ts = ops.create_tag_set(ctx, name=body.name, key=body.key,
                            description=body.description)
    return _one(ctx.session, ts.id)


@router.post("/import", response_model=TagSetImportOut)
def import_tag_set(body: TagSetImportIn, ctx: Ctx = Depends(get_ctx)):
    ts, result = ops.import_document(ctx, body.document, mode=body.mode,
                                     target_id=body.target_id)
    return TagSetImportOut(set=_one(ctx.session, ts.id), **result)


@router.get("/describe")
def describe(names: str = "", s: Session = Depends(get_session)):
    """What the enabled sets say about a few names — for a hover outside the
    lists. `names` is comma-separated."""
    want = [n.strip() for n in names.split(",") if n.strip()]
    lnames = [n.lower() for n in want]
    hits = ops.name_map(s, lnames)
    texts = ops.descriptions_for(s, lnames)
    # THE LIBRARY LEADS. This is the one caller with no row behind it — a
    # hover over a half-typed word — so it is the one that has to ask; every
    # list already carries the library's half on the row it drew.
    mine = ops.library_says(s, lnames)
    return {n: {"tag_sets": [{"key": h.key, "name": h.name, "count": h.count}
                             for h in hits.get(n.lower(), [])],
                "descriptions": [_says(d) for d in
                                 ([mine[n.lower()]] if n.lower() in mine else [])
                                 + list(texts.get(n.lower(), []))]}
            for n in want}


@router.get("/{set_id}/namespaces")
def tag_set_namespaces(set_id: int, s: Session = Depends(get_session)):
    """A set's namespaces — the sidebar's derived half for an imported
    tag set, the same shape and the same two-or-more rule the library's
    `/api/tags/namespaces` answers with.

    `hidden` is always false here: hiding a namespace is a library-global
    setting about what the autocomplete offers, and it is answered on the
    library's list rather than per set.
    """
    ops.by_id(s, set_id)
    return [{"name": ns, "count": n, "hidden": False}
            for ns, n in ops.namespaces_of(s, set_id)]


@router.get("/tree", response_model=TagSetTreeOut)
def tag_set_tree(s: Session = Depends(get_session)):
    """The ENABLED sets' category trees — what an empty, focused tag field
    browses. Entries are fetched per category (`GET /{id}/entries`), so this
    is small however big the sets are: the shape, and a count per node."""
    out = []
    for sid in ops.enabled_ids(s):
        ts = ops.by_id(s, sid)
        trails = ops.category_trails(s, sid)
        counts = ops.category_entry_counts(s, sid)
        # A HIDDEN CATEGORY IS NOT IN THE TREE AT ALL, and neither is
        # anything under it or its share of the counts — the browse is the
        # autocomplete wearing another shape, so what it offers and what the
        # typed list offers are the same set of names.
        skip = ops.hidden_category_ids(s, [sid])
        out.append(TagSetTreeSet(
            id=ts.id, key=ts.key, name=ts.name,
            categories=[TagSetTreeCategory(
                id=c.id, parent_id=c.parent_id, name=c.name,
                icon=c.icon or "",
                position=int(c.position or 0),
                trail=trails.get(c.id, [c.name]), entries=counts.get(c.id, 0))
                for c in ops.categories_of(s, sid) if c.id not in skip],
            uncategorized=counts.get(None, 0),
            entries=sum(n for cid, n in counts.items() if cid not in skip)))
    return TagSetTreeOut(sets=out)


@router.get("/{set_id}", response_model=TagSetDetail)
def get_tag_set(set_id: int, s: Session = Depends(get_session)):
    return _detail(s, set_id)


@router.patch("/{set_id}", response_model=TagSetOut)
def update_tag_set(set_id: int, body: TagSetUpdate, ctx: Ctx = Depends(get_ctx)):
    ops.edit_tag_set(ctx, set_id, name=body.name, description=body.description,
                     version=body.version, position=body.position,
                     aliases_enabled=body.aliases_enabled,
                     implications_enabled=body.implications_enabled)
    return _one(ctx.session, set_id)


@router.put("/{set_id}/enabled", response_model=TagSetOut)
def set_enabled(set_id: int, body: TagSetEnabled, ctx: Ctx = Depends(get_ctx)):
    ops.set_enabled(ctx, set_id, body.enabled)
    return _one(ctx.session, set_id)


@router.post("/{set_id}/update", response_model=TagSetOut)
def update_builtin(set_id: int, ctx: Ctx = Depends(get_ctx)):
    """Take the entries this build ships — the verb behind the row's *Update
    available* chip. Slow by nature (it rewrites every row of the set), which
    is exactly why nothing does it on its own at library open."""
    ops.update_builtin(ctx, set_id)
    return _one(ctx.session, set_id)


@router.delete("/{set_id}")
def delete_tag_set(set_id: int, ctx: Ctx = Depends(get_ctx)):
    ops.delete_tag_set(ctx, set_id)
    return {"ok": True}


@router.post("/{set_id}/duplicate", response_model=TagSetOut)
def duplicate_tag_set(set_id: int, body: TagSetDuplicate,
                      ctx: Ctx = Depends(get_ctx)):
    ts = ops.duplicate_tag_set(ctx, set_id, name=body.name, key=body.key)
    return _one(ctx.session, ts.id)


@router.get("/{set_id}/export")
def export_tag_set(set_id: int, s: Session = Depends(get_session)):
    ts = ops.by_id(s, set_id)
    doc = ops.export_document(s, set_id)
    return Response(
        content=json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="{ts.key}.json"'})


@router.get("/{set_id}/entries", response_model=TagSetEntriesOut)
def list_entries(set_id: int, q: str = "",
                 # REPEATED, so several picked categories are one page: the
                 # Sets tab lists their union. One `?category_id=` reads as
                 # a list of one, which is what every earlier caller sends.
                 category_id: list[int] = Query(default=[]),
                 uncategorized: bool = False,
                 subtree: bool = False,
                 has_aliases: bool = False, has_implies: bool = False,
                 described: Optional[bool] = None, behind: bool = False,
                 behind_records: bool = False,
                 record: list[str] = Query(default=[]),
                 # A RANGE ON THE COUNT COLUMN — the Items list's control,
                 # over the column it is about. Either end optional.
                 count_min: Optional[int] = None,
                 count_max: Optional[int] = None,
                 #: THE SIDEBAR'S DERIVED HALF, repeated: a namespace is
                 #: picked in the same list a category is and joins the same
                 #: union (`_entries_stmt`).
                 namespace: list[str] = Query(default=[]),
                 sort: str = "position", desc: bool = False,
                 limit: int = Query(default=200, ge=1, le=2000),
                 offset: int = Query(default=0, ge=0),
                 s: Session = Depends(get_session),
                 lib=Depends(get_library)):
    ops.by_id(s, set_id)
    rows, total = ops.entries_page(s, set_id, q=q, category_ids=category_id,
                                   uncategorized=uncategorized, subtree=subtree,
                                   count_min=count_min, count_max=count_max,
                                   namespace=namespace,
                                   has_aliases=has_aliases,
                                   has_implies=has_implies, described=described,
                                   records=record,
                          behind=_behind(s, lib, set_id, behind, behind_records),
                                   sort=sort, desc=desc,
                                   limit=limit, offset=offset)
    return TagSetEntriesOut(rows=_entry_out(s, rows, set_id, lib), total=total)


@router.get("/{set_id}/entries/ids")
def entry_ids(set_id: int, q: str = "",
              category_id: list[int] = Query(default=[]),
              uncategorized: bool = False,
              subtree: bool = False,
              has_aliases: bool = False, has_implies: bool = False,
              described: Optional[bool] = None, behind: bool = False,
              behind_records: bool = False,
              record: list[str] = Query(default=[]),
              count_min: Optional[int] = None,
              count_max: Optional[int] = None,
              namespace: list[str] = Query(default=[]),
              sort: str = "position", desc: bool = False,
              s: Session = Depends(get_session),
              lib=Depends(get_library)):
    """Every entry id the list holds, in its order — what SELECT ALL and a
    shift-range are about. The list is paged and windowed, so "all" cannot
    be read off what is loaded; every parameter is the entries endpoint's,
    because the answer is only true of the list they describe.

    Declared BEFORE `/{set_id}/entries/{entry_id}` would be, or `ids` reads
    as an entry id.
    """
    ops.by_id(s, set_id)
    return {"ids": ops.entry_ids(
        s, set_id, q=q, category_ids=category_id,
        uncategorized=uncategorized, subtree=subtree,
        count_min=count_min, count_max=count_max, namespace=namespace,
        has_aliases=has_aliases, has_implies=has_implies,
        described=described, records=record,
        behind=_behind(s, lib, set_id, behind, behind_records),
        sort=sort, desc=desc)}


@router.get("/{set_id}/entries/locate")
def locate_entry(set_id: int, name: str, q: str = "",
                 category_id: list[int] = Query(default=[]),
                 uncategorized: bool = False,
                 subtree: bool = False,
                 has_aliases: bool = False, has_implies: bool = False,
                 described: Optional[bool] = None, behind: bool = False,
                 behind_records: bool = False,
                 record: list[str] = Query(default=[]),
                 sort: str = "position", desc: bool = False,
                 s: Session = Depends(get_session),
                 lib=Depends(get_library)):
    """WHERE a named entry sits in the list as it is currently narrowed and
    sorted — `{"index": n, "id": …}`, or nulls when the list does not hold
    it. Every parameter is the entries endpoint's, because the answer is only
    true of the list those parameters describe.

    Declared BEFORE `/{set_id}/entries/{entry_id}` would be, or `locate`
    reads as an entry id.
    """
    ops.by_id(s, set_id)
    hit = ops.entry_index(s, set_id, name, q=q, category_ids=category_id,
                          uncategorized=uncategorized, subtree=subtree,
                          has_aliases=has_aliases, has_implies=has_implies,
                          described=described,
                          records=record,
                          behind=_behind(s, lib, set_id, behind, behind_records),
                          sort=sort, desc=desc)
    return {"index": hit[0] if hit else None, "id": hit[1] if hit else None,
            "category_id": hit[2] if hit else None}


@router.post("/{set_id}/entries", response_model=TagSetEntryOut)
def create_entry(set_id: int, body: TagSetEntryCreate,
                 ctx: Ctx = Depends(get_ctx)):
    row = ops.create_entry(ctx, set_id, name=body.name,
                           description=body.description, count=body.count,
                           category_id=body.category_id,
                           aliases=body.aliases, implies=body.implies,
                           meta=body.meta, comment=body.comment,
                           records={k: (v.model_dump() if v is not None
                                        else None)
                                    for k, v in (("subject", body.subject),
                                                 ("place", body.place),
                                                 ("event", body.event))})
    return _entry_out(ctx.session, [row], set_id)[0]


@router.post("/{set_id}/entries/sync", response_model=TagSetSyncOut)
def sync_entries(set_id: int, body: TagSetSyncIn,
                 ctx: Ctx = Depends(get_ctx)):
    """Make the library's tags say what this set says about them — what the
    name entails, the line it carries, and whether it is a subject, a place
    or an event.

    ONE VERB, because the door applies all of it at one moment (when it
    CREATES the tag) and a tag that was already there has heard none of it.
    Offering the two halves separately made a person choose between them
    for no reason anybody could give. `mode` is whether what the library
    already says survives it.

    Declared BEFORE `/{set_id}/entries/{entry_id}` would be, or the path
    reads as an entry id.
    """
    rows = ops.entries_by_ids(ctx.session, set_id, body.entry_ids)
    return TagSetSyncOut(**tagcatalog.sync_set_advice(
        ctx, [r.name for r in rows], replace=body.mode == "replace"))


@router.post("/{set_id}/entries/sync-parents", response_model=TagSetSyncOut)
def sync_parents(set_id: int, body: TagSetSyncIn,
                 ctx: Ctx = Depends(get_ctx)):
    """Build the parent hierarchy above these entries' places and events.

    ITS OWN verb: following a parent MINTS that tag, and its parent above
    it, so over a selection this fills the catalog rather than describing
    what was picked. `replace` also re-points a record that has a different
    parent, which is how a set that has moved a place is followed.

    Declared BEFORE `/{set_id}/entries/{entry_id}` would be, or the path
    reads as an entry id.
    """
    rows = ops.entries_by_ids(ctx.session, set_id, body.entry_ids)
    got = tagcatalog.sync_set_parents(
        ctx, [r.name for r in rows], replace=body.mode == "replace")
    return TagSetSyncOut(tags=got["tags"], added=got["written"],
                         skipped=got["skipped"])


@router.post("/{set_id}/entries/add-to-library",
             response_model=TagSetAddOut)
def add_entries_to_library(set_id: int, body: TagSetAddIn,
                           ctx: Ctx = Depends(get_ctx)):
    """Put these entries' tags in the library's own tag list.

    Through the DOOR (`tagcatalog.get_or_create`), so each tag arrives
    with what its set says about it — an alias name creates the
    canonical tag, and the entry's implied names are minted with it.

    Declared BEFORE `/{set_id}/entries/{entry_id}` would be, or the path
    reads as an entry id.
    """
    rows = ops.entries_by_ids(ctx.session, set_id, body.entry_ids)
    return TagSetAddOut(**tagcatalog.add_to_library(
        ctx, [r.name for r in rows]))


@router.post("/{set_id}/entries/bulk", response_model=TagSetBulkOut)
def bulk_entries(set_id: int, body: TagSetBulkIn, ctx: Ctx = Depends(get_ctx)):
    rows = [r.model_dump() for r in body.rows]
    return TagSetBulkOut(**ops.bulk_entries(ctx, set_id, rows,
                                            existing=body.existing))


@router.patch("/{set_id}/entries/{entry_id}", response_model=TagSetEntryOut)
def update_entry(set_id: int, entry_id: int, body: TagSetEntryUpdate,
                 ctx: Ctx = Depends(get_ctx)):
    kw: dict = {}
    if body.clear_count:
        kw["count"] = None
    elif body.count is not None:
        kw["count"] = body.count
    if body.clear_category:
        kw["category_id"] = None
    elif body.category_id is not None:
        kw["category_id"] = body.category_id
    if body.records is not None:
        # ONLY THE KINDS THIS EDIT NAMES. A record left out is left alone,
        # and one named as null is taken away — a distinction JSON cannot
        # make with an absent key alone, hence `kinds`.
        recs = body.records
        kw["records"] = {k: (getattr(recs, k).model_dump()
                             if getattr(recs, k) is not None else None)
                         for k in recs.kinds}
    row = ops.edit_entry(ctx, set_id, entry_id, name=body.name,
                         description=body.description, comment=body.comment,
                         aliases=body.aliases, implies=body.implies,
                         meta=body.meta, **kw)
    return _entry_out(ctx.session, [row], set_id)[0]


@router.delete("/{set_id}/entries/{entry_id}")
def delete_entry(set_id: int, entry_id: int, ctx: Ctx = Depends(get_ctx)):
    ops.delete_entry(ctx, set_id, entry_id)
    return {"ok": True}


# ---- the tag set's own META TAGS ----------------------------------------
# The labels a set puts on its NAMES ("character", "noflip") — the sidebar's
# Meta tags group, one tag set along from the library's own. They are
# `tags` rows of the set (`kind = 'meta'`), so a set carries them, they
# travel in its file and they go with it when it is deleted.

def _meta_out(s: Session, set_id: int) -> list[TagSetMetaTagOut]:
    uses = ops.meta_uses(s, set_id)
    return [TagSetMetaTagOut(id=m.id, name=m.name, comment=m.comment or "",
                             description=m.description or "",
                             uses=uses.get(m.name.lower(), 0))
            for m in ops.meta_tags_of(s, set_id)]


@router.get("/{set_id}/meta-tags", response_model=list[TagSetMetaTagOut])
def list_meta_tags(set_id: int, s: Session = Depends(get_session)):
    return _meta_out(s, set_id)


@router.post("/{set_id}/meta-tags", response_model=list[TagSetMetaTagOut])
def create_meta_tag(set_id: int, body: TagSetMetaTagCreate,
                    ctx: Ctx = Depends(get_ctx)):
    ops.create_meta_tag(ctx, set_id, name=body.name, comment=body.comment,
                        description=body.description)
    return _meta_out(ctx.session, set_id)


@router.patch("/{set_id}/meta-tags/{meta_id}",
              response_model=list[TagSetMetaTagOut])
def update_meta_tag(set_id: int, meta_id: int, body: TagSetMetaTagUpdate,
                    ctx: Ctx = Depends(get_ctx)):
    ops.edit_meta_tag(ctx, set_id, meta_id, name=body.name,
                      comment=body.comment, description=body.description)
    return _meta_out(ctx.session, set_id)


@router.delete("/{set_id}/meta-tags/{meta_id}",
               response_model=list[TagSetMetaTagOut])
def delete_meta_tag(set_id: int, meta_id: int, ctx: Ctx = Depends(get_ctx)):
    ops.delete_meta_tag(ctx, set_id, meta_id)
    return _meta_out(ctx.session, set_id)


@router.post("/{set_id}/categories", response_model=TagSetCategoryOut)
def create_category(set_id: int, body: TagSetCategoryCreate,
                    ctx: Ctx = Depends(get_ctx)):
    row = ops.create_category(ctx, set_id, name=body.name,
                              parent_id=body.parent_id,
                              icon=body.icon, hidden=body.hidden,
                              aliases=body.aliases,
                              implications=body.implications)
    trails = ops.category_trails(ctx.session, set_id)
    return TagSetCategoryOut(id=row.id, parent_id=row.parent_id, name=row.name,
                             icon=row.icon or "", hidden=bool(row.hidden),
                             aliases=row.aliases,
                             implications=row.implications,
                             position=int(row.position or 0),
                             trail=trails.get(row.id, [row.name]))


@router.post("/{set_id}/categories/{cat_id}/move", response_model=TagSetCategoryOut)
def move_category(set_id: int, cat_id: int, body: TagSetCategoryMove,
                  ctx: Ctx = Depends(get_ctx)):
    row = ops.move_category(ctx, set_id, cat_id, parent_id=body.parent_id,
                            index=body.index)
    trails = ops.category_trails(ctx.session, set_id)
    return TagSetCategoryOut(id=row.id, parent_id=row.parent_id, name=row.name,
                             icon=row.icon or "", hidden=bool(row.hidden),
                             aliases=row.aliases,
                             implications=row.implications,
                             position=int(row.position or 0),
                             trail=trails.get(row.id, [row.name]))


@router.patch("/{set_id}/categories/{cat_id}", response_model=TagSetCategoryOut)
def update_category(set_id: int, cat_id: int, body: TagSetCategoryUpdate,
                    ctx: Ctx = Depends(get_ctx)):
    kw: dict = {}
    if body.clear_parent:
        kw["parent_id"] = None
    elif body.parent_id is not None:
        kw["parent_id"] = body.parent_id
    # THREE-STATE: `clear_x` asks for the null (inherit), `x` for an answer,
    # and neither leaves the field alone — `None` cannot mean both.
    if body.clear_aliases:
        kw["aliases"] = None
    elif body.aliases is not None:
        kw["aliases"] = body.aliases
    if body.clear_implications:
        kw["implications"] = None
    elif body.implications is not None:
        kw["implications"] = body.implications
    row = ops.edit_category(ctx, set_id, cat_id, name=body.name,
                            icon=body.icon, hidden=body.hidden,
                            position=body.position, **kw)
    trails = ops.category_trails(ctx.session, set_id)
    return TagSetCategoryOut(id=row.id, parent_id=row.parent_id, name=row.name,
                             icon=row.icon or "", hidden=bool(row.hidden),
                             aliases=row.aliases,
                             implications=row.implications,
                             position=int(row.position or 0),
                             trail=trails.get(row.id, [row.name]))


@router.delete("/{set_id}/categories/{cat_id}")
def delete_category(set_id: int, cat_id: int, ctx: Ctx = Depends(get_ctx)):
    ops.delete_category(ctx, set_id, cat_id)
    return {"ok": True}
