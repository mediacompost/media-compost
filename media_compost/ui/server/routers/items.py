"""Item listing (tag search + range filters + pagination), detail and edits."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case as sa_case, func, or_, select
from sqlalchemy.orm import Session

from media_compost.db import (
    Caption,
    CaptionRef,
    CaptionTag,
    File,
    FileArtifact,
    FileMetadata,
    FileName,
    Group,
    Item,
    ItemFaceRun,
    ItemGroup,
    ItemMetaMute,
    ItemMetaPin,
    ItemTag,
    ItemTagBox,
    ItemTagGroup,
    ItemTagGroupTag,
    ItemTagPlacement,
    ItemTextRun,
    Relationship,
    Sequence,
    SequenceItem,
    Tag,
    TextRegion,
    TrashedItem,
)
from ...plugins import registry as ml_registry
from media_compost import prefilter
from media_compost.db import chunked
from media_compost.media import normalize_format
from media_compost.resolve import Resolver
from media_compost.itemdict import _edit_lineage
from media_compost.ops import Ctx, groups as ops_groups, \
    items as ops_items, links as ops_links, \
    metadata as ops_metadata, search, tagassign
from media_compost.ops.errors import Invalid
from media_compost.ops.items import coords_of as _coords
from media_compost.ops.items import taken_of as _taken
from .. import dbgate, viewscope
from ..deps import Library, get_ctx, get_library, get_session
from ..schemas import (
    CaptionOut,
    CaptionRefOut,
    FileArtifactOut,
    FileNameEntry,
    FileVersion,
    GroupRun,
    IndirectGroupTags,
    LinkSlim,
    ItemDelete,
    ItemDetailsIn,
    ItemDetailsOut,
    ItemHide,
    ItemDetail,
    ItemGroupRuns,
    ItemGroupRunsRequest,
    ItemIdRange,
    ItemIdRangeRequest,
    ItemIndexRequest,
    ItemIndexes,
    ItemMerge,
    ItemSlim,
    ItemMetadataOut,
    ItemOut,
    ItemPage,
    ItemSearchRequest,
    ItemUpdate,
    MediaTrack,
    MediaTracks,
    MetadataField,
    MetadataSource,
    MuteMetadataIn,
    PinMetadataIn,
    SubjectAppearance,
    SubjectOnItem,
    TagAssignment,
    TagBox,
    TagGroupOut,
    TagInstance,
    TagWhen,
    UnpinMetadataIn,
    ViewActionOut,
    ViewGroupMembership,
    ViewTrash,
    ViewVisibility,
)

router = APIRouter(prefix="/api/items", tags=["items"])


def _thumb_token(active: Optional[File]) -> str:
    """What cache-busts an item's thumbnail URL.

    The active file's content hash, plus how many times its thumbnail has been
    REPLACED. The hash alone was the whole answer while a thumbnail was derived
    from the file and nothing else; choosing which frame represents a film
    changes the thumbnail's bytes and not the file's, so without the counter
    the grid and the sidebar kept the old picture until a reload.
    """
    if not active or not active.sha256:
        return ""
    rev = int(active.thumb_rev or 0)
    return f"{active.sha256[:16]}-{rev}" if rev else active.sha256[:16]


def _mp(w: int, h: int) -> float:
    return round(w * h / 1_000_000, 2)


def _item_out(
    item: Item,
    files: list[File],
    group_ids: list[int],
    direct_tags: Optional[list[TagAssignment]] = None,
    eff_tags: Optional[list[str]] = None,
    eff_neg: Optional[list[str]] = None,
    seq_index: Optional[int] = None,
    seq_total: int = 0,
    seq_count: int = 0,
    member_id: Optional[int] = None,
    sequence_id: Optional[int] = None,
    active_override: Optional[File] = None,
    member_thumbs: Optional[list[int]] = None,
) -> ItemOut:
    # A "sequence" item owns no files; its active file is borrowed from its first
    # member (passed as ``active_override``) purely for the thumbnail/dimensions.
    active = active_override or next(
        (f for f in files if f.id == item.active_file_id), None
    )
    # The active file's stored bytes are already in their final orientation, so
    # its recorded width/height are the visible dimensions (no swap needed).
    w = active.width if active else 0
    h = active.height if active else 0
    rotation = int(active.rotation or 0) if active else 0
    return ItemOut(
        id=item.id, uid=item.uid, name=item.name, kind=item.kind,
        sequence_id=sequence_id,
        duration=active.duration if active else None,
        width=w, height=h, megapixels=_mp(w, h), rotation=rotation,
        active_file_id=item.active_file_id,
        thumb_token=_thumb_token(active),
        file_count=len(files),
        alt_count=max(0, len(files) - 1), hidden=bool(item.hidden),
        link_item_id=item.link_item_id,
        group_ids=group_ids, direct_tags=direct_tags or [],
        eff_tags=eff_tags or [], eff_neg=eff_neg or [],
        seq_index=seq_index, seq_total=seq_total,
        seq_count=seq_count, member_id=member_id,
        member_thumbs=member_thumbs or [],
    )


def _seq_badges(
    s: Session, items: list[Item], sequence: Optional[int] = None,
) -> dict[int, tuple[int, int]]:
    """Map item id -> (1-based index, total) within a sequence.

    When ``sequence`` is given (an open sequence view) the index/total are
    relative to *that* sequence; otherwise each item's own main sequence — the
    "first" sequence it belongs to — is used. Computed in a single query so the
    listing stays O(total) rather than per-item.
    """
    if sequence is not None:
        seq_ids = {sequence}
    else:
        seq_ids = {it.main_sequence_id for it in items if it.main_sequence_id}
    if not seq_ids:
        return {}
    by_seq: dict[int, list[tuple[int, int]]] = {}
    for sid, iid, pos in s.execute(
        select(SequenceItem.sequence_id, SequenceItem.item_id, SequenceItem.position)
        .where(SequenceItem.sequence_id.in_(seq_ids))
    ).all():
        by_seq.setdefault(sid, []).append((pos, iid))
    order: dict[tuple[int, int], int] = {}
    totals: dict[int, int] = {}
    for sid, members in by_seq.items():
        # Positions, not distinct items: a repeated page really is page 5
        # AND page 17, and the "/ 24" should say how long the book is.
        totals[sid] = len(members)
        for rank, (_pos, iid) in enumerate(sorted(members), start=1):
            # FIRST occurrence wins the badge's numerator — one card stands
            # for every copy, and its first position is the least surprising
            # one to name.
            order.setdefault((sid, iid), rank)
    badges: dict[int, tuple[int, int]] = {}
    for it in items:
        sid = sequence if sequence is not None else it.main_sequence_id
        if sid and (sid, it.id) in order:
            badges[it.id] = (order[(sid, it.id)], totals[sid])
    return badges


def _member_ranks(s: Session, sequence: int) -> dict[int, int]:
    """Map a sequence's member ROW id -> its 1-based place in the book.

    The rank, not the stored ``position``: that column is dense today and
    the two agree, but the member LIST already ranks its rows this way
    (`sequences._members`), and the grid's chip and that list must never
    disagree about which page you are looking at.
    """
    rows = s.execute(
        select(SequenceItem.id)
        .where(SequenceItem.sequence_id == sequence)
        .order_by(SequenceItem.position, SequenceItem.id)
    ).scalars().all()
    return {mid: rank for rank, mid in enumerate(rows, start=1)}


def _seq_counts(s: Session, items: list[Item]) -> dict[int, int]:
    """Map item id -> number of sequences it is a member of (one query).

    DISTINCT sequences, not rows: an item at three positions of one book is
    in ONE sequence, and this number drives the "In N sequences" tooltip and
    the Sequence tab's gate."""
    from sqlalchemy import distinct, func

    ids = [it.id for it in items]
    if not ids:
        return {}
    return {
        iid: cnt for iid, cnt in s.execute(
            select(SequenceItem.item_id,
                   func.count(distinct(SequenceItem.sequence_id)))
            .where(SequenceItem.item_id.in_(ids))
            .group_by(SequenceItem.item_id)
        ).all()
    }


def _container_info(
    s: Session, items: list[Item]
) -> tuple[dict[int, int], dict[int, int], dict[int, File]]:
    """For the "sequence" container items in ``items``, resolve which sequence
    each represents, its member count, and the borrowed active File.

    Returns (seq_id_by_item, member_total_by_item, active_file_by_item_id).
    """
    from sqlalchemy import func

    container_ids = [it.id for it in items if it.kind == "sequence"]
    if not container_ids:
        return {}, {}, {}
    seq_by_item: dict[int, int] = {}
    for sid, iid in s.execute(
        select(Sequence.id, Sequence.item_id).where(Sequence.item_id.in_(container_ids))
    ).all():
        if iid is not None:
            seq_by_item[iid] = sid
    totals_by_seq: dict[int, int] = {}
    if seq_by_item:
        for sid, cnt in s.execute(
            select(SequenceItem.sequence_id, func.count(SequenceItem.id))
            .where(SequenceItem.sequence_id.in_(list(seq_by_item.values())))
            .group_by(SequenceItem.sequence_id)
        ).all():
            totals_by_seq[sid] = cnt
    total_by_item = {iid: totals_by_seq.get(sid, 0) for iid, sid in seq_by_item.items()}
    active_ids = [it.active_file_id for it in items
                  if it.kind == "sequence" and it.active_file_id is not None]
    files_by_id: dict[int, File] = {}
    if active_ids:
        files_by_id = {
            f.id: f for f in s.execute(
                select(File).where(File.id.in_(active_ids))
            ).scalars().all()
        }
    active_by_item = {
        it.id: files_by_id[it.active_file_id]
        for it in items
        if it.kind == "sequence" and it.active_file_id in files_by_id
    }
    return seq_by_item, total_by_item, active_by_item


def _member_thumbs(s: Session, items: list[Item]) -> dict[int, list[int]]:
    """For each "sequence" container in ``items``, the active file ids of its
    first four members (in position order), for the grid's 2×2 mosaic thumb."""
    container_ids = [it.id for it in items if it.kind == "sequence"]
    if not container_ids:
        return {}
    seq_by_item: dict[int, int] = {}
    for sid, iid in s.execute(
        select(Sequence.id, Sequence.item_id).where(Sequence.item_id.in_(container_ids))
    ).all():
        if iid is not None:
            seq_by_item[iid] = sid
    if not seq_by_item:
        return {}
    members_by_seq: dict[int, list[tuple[int, int]]] = {}
    for sid, iid, pos in s.execute(
        select(SequenceItem.sequence_id, SequenceItem.item_id, SequenceItem.position)
        .where(SequenceItem.sequence_id.in_(list(seq_by_item.values())))
    ).all():
        members_by_seq.setdefault(sid, []).append((pos, iid))
    first_items: dict[int, list[int]] = {}
    needed: set[int] = set()
    for sid, mem in members_by_seq.items():
        # Distinct items, in first-occurrence order: a book that opens with
        # three copies of one blank page should not spend three of the
        # mosaic's four tiles saying so.
        firsts = list(dict.fromkeys(iid for _pos, iid in sorted(mem)))[:4]
        first_items[sid] = firsts
        needed.update(firsts)
    active_by_item: dict[int, Optional[int]] = {}
    if needed:
        active_by_item = {
            it.id: it.active_file_id
            for it in s.execute(select(Item).where(Item.id.in_(needed))).scalars().all()
        }
    out: dict[int, list[int]] = {}
    for cont_id, sid in seq_by_item.items():
        fids = [active_by_item.get(iid) for iid in first_items.get(sid, [])]
        out[cont_id] = [f for f in fids if f is not None]
    return out


def _fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


@router.get("/facets")
async def facets(
    request: Request,
    s: Session = Depends(get_session),
    lib: Library = Depends(get_library),
    groups: str = Query(""),
    ungrouped: bool = Query(False),
    untagged: bool = Query(False),
    trash: bool = Query(False),
    hidden: bool = Query(False),
    show_hidden: bool = Query(False),
    kind: str = Query(""),
    sequence: Optional[int] = Query(None),
    hide_sequenced: bool = Query(False),
    fold_sequenced: bool = Query(False),
    pending: bool = Query(False),
    pending_kind: str = Query(""),
):
    """How many items the current scope holds — the sidebar's
    Trash/Ungrouped/Untagged figures. One aggregate statement; the scope never
    carries a search query, so there is no residue path here.

    IT USED TO ANSWER EIGHT MORE NUMBERS — min/max width, height, megapixels
    and aspect ratio, "input hints" for a filter panel that no longer exists.
    Nothing read them, on either side of the wire, and they were not free:
    a min/max over the active FILE's columns turns the count into a join
    over every item in scope, which measured 0.69 s against 0.03 s at a
    million items — paid three times over on every view change, for eight
    numbers nobody looked at.

    THROUGH `dbgate` LIKE THE PAGE QUERY: Untagged and Ungrouped are an
    `EXISTS` probe per item — a quarter to half a second at a million — and an
    edit invalidates all three of these at once, beside the grid's pages.
    Left to race them each one took FIFTEEN seconds.

    AND REMEMBERED THE WAY THE PAGE'S OWN TOTAL IS (`scope_count`), which it
    was not: this is the same question — count the items a scope admits — and
    it was the one asking it that paid in full every single time, while the
    grid's total beside it answered from the memo in 7 ms. Measured at 1.2M
    items, three times in a row each: Ungrouped 0.46/0.46/0.46 s, Untagged
    0.30/0.30/0.30. Three of the five library walks a LAUNCH fires are these,
    and every edit invalidates all three again; now they cost that once per
    revision, like everything else that scans the library for a number."""
    return await dbgate.guarded(
        request, _facets_sync, s, lib, groups, ungrouped, trash, kind,
        sequence, hide_sequenced, fold_sequenced, hidden, show_hidden,
        pending, pending_kind, untagged)


def _facets_sync(s: Session, lib: Library, groups: str, ungrouped: bool,
                 trash: bool, kind: str, sequence: Optional[int],
                 hide_sequenced: bool, fold_sequenced: bool, hidden: bool,
                 show_hidden: bool, pending: bool, pending_kind: str,
                 untagged: bool):
    """The count proper — see `facets`."""
    cands = search.search_filtered(s, groups, ungrouped, trash,
                             kind=kind, sequence=sequence,
                             hide_sequenced=hide_sequenced,
                             fold_sequenced=fold_sequenced, hidden=hidden,
                             show_hidden=show_hidden, pending=pending,
                             pending_kind=pending_kind, untagged=untagged)
    # No search travels with a scope, so there is no residue: `cands.where`
    # IS the whole question, and the statement is what `scope_count` keys on.
    count = scope_count(
        s, lib.db,
        prefilter.base_select([Item.id], cands.sequence, cands.where))
    return {"count": int(count or 0)}


@router.get("", response_model=ItemPage)
async def list_items(
    request: Request,
    s: Session = Depends(get_session),
    lib: Library = Depends(get_library),
    groups: str = Query("", description="Comma-separated group ids."),
    ungrouped: bool = Query(False, description="Only items with no group."),
    untagged: bool = Query(False, description="Only items with no tags."),
    trash: bool = Query(False, description="Only trashed items."),
    hidden: bool = Query(False, description="Only hidden items."),
    show_hidden: bool = Query(False, description="Also include hidden items (dimmed)."),
    kind: str = Query("", description="Restrict to a media kind: image | video."),
    sequence: Optional[int] = Query(None, description="Only members of this sequence."),
    hide_sequenced: bool = Query(False, description="Hide items that belong to a sequence."),
    fold_sequenced: bool = Query(False, description="Hide a sequence's members where the sequence itself is in this view."),
    pending: bool = Query(False, description="Only items with pending AI tags/captions."),
    pending_kind: str = Query("", description="Narrow Pending to 'tags', 'captions' or 'faces'."),
    page: int = 1, page_size: int = 60, sort: str = "import_desc",
):
    """List items in a scope (no condition filtering). For a structured search
    use ``POST /api/items/query`` with the parsed condition tree.

    Through `dbgate` — it is the same page walk `query_items` does."""
    return await dbgate.guarded(
        request, _list_items_sync, s, lib, groups, ungrouped, untagged, trash,
        hidden, show_hidden, kind, sequence, hide_sequenced, fold_sequenced,
        pending, pending_kind, page, page_size, sort)


def _list_items_sync(s: Session, lib: Library, groups: str, ungrouped: bool,
                     untagged: bool, trash: bool, hidden: bool,
                     show_hidden: bool, kind: str, sequence: Optional[int],
                     hide_sequenced: bool, fold_sequenced: bool,
                     pending: bool, pending_kind: str,
                     page: int, page_size: int, sort: str):
    """The listing proper — see `list_items`."""
    res = Resolver(s)
    base = search.search_filtered(s, groups, ungrouped, trash,
                            kind=kind, sequence=sequence,
                            hide_sequenced=hide_sequenced,
                            fold_sequenced=fold_sequenced, hidden=hidden,
                            show_hidden=show_hidden, pending=pending,
                            pending_kind=pending_kind, untagged=untagged,
                            resolver=res)
    return _page_response(s, base, page, page_size, sort, sequence,
                          resolver=res, db=lib.db)


def scope_count(s: Session, db, stmt) -> int:
    """``SELECT count(*)`` over a scope, remembered until the library moves.

    THE COUNT IS THE COST OF A VIEW, and the page beside it is free. With the
    sort indexes in place a page of 60 is an index range — 0.4 ms at a
    million items — while the total is a SCAN of every row the scope admits:
    measured on a 1M-item library, 197 ms for All Items, 107 for a media
    kind, 375 for Ungrouped, 513 for Untagged. And it is asked again for
    every page and every switch back to a category, over a library that has
    not moved between them.

    So it goes through `Database.cached`, keyed on the STATEMENT — its
    compiled SQL and its parameters, which is the scope itself and cannot be
    wrong about it — plus the library revision, which drops the whole memo
    the moment anything is written. The sort is deliberately not in the key:
    a total does not depend on the order.

    `db` may be None (a caller with no library to hand), and then this is the
    plain count it always was.
    """
    from sqlalchemy import func

    stmt = select(func.count()).select_from(stmt.subquery())
    if db is None:
        return int(s.execute(stmt).scalar_one())
    compiled = stmt.compile(s.get_bind())
    # `repr` of the sorted parameters, not a tuple of them: an expanding
    # `IN` binds a LIST, which is not hashable. Deterministic and faithful
    # for what a scope actually carries (ints, strings, bools, id lists),
    # and a collision would mean two scopes whose SQL and parameters both
    # match — which is one scope.
    key = ("count", str(compiled),
           repr(sorted(compiled.params.items(), key=lambda kv: kv[0])))
    return db.cached(s, key, lambda: int(s.execute(stmt).scalar_one()))


def _page_response(
    s: Session,
    cands: search.CandidateSet,
    page: int, page_size: int, sort: str, sequence: Optional[int],
    resolver: Optional[Resolver] = None,
    db=None,
) -> "ItemPage":
    """Project a candidate set into an ``ItemPage``.

    Total, sort and pagination run in SQL; only the PAGE's rows are hydrated
    and decorated. ``sort`` is "<field>[_<dir>]" — field in {first, recent,
    modified, resolution, name, width}; a sequence view is always in its own
    position order. The exact path is COUNT + ORDER BY/LIMIT over the
    candidate select; the residue path first evaluates the residue tree in
    Python, then pages the matched ids through the per-connection temp table
    (an ORDER BY over a huge id list cannot be chunked, a join can).
    """
    from sqlalchemy import func

    res = resolver or Resolver(s)
    start = max(0, (page - 1) * page_size)
    order = prefilter.order_by_for(sort, sequence, ranking=cands.ranking)
    # A SEQUENCE VIEW PAGES OCCURRENCES, not items: a page repeated three
    # times in a book is three cards, each at its own position (see
    # `prefilter.base_select`). The member ROW id comes back with the item id
    # so each card can key on the occurrence and carry its own index.
    seq_cols = ([Item.id, SequenceItem.id, SequenceItem.position]
                if sequence is not None else [Item.id])
    occ = sequence is not None

    def _rows(stmt, total: int) -> list[tuple[int, Optional[int], Optional[int]]]:
        # THE TOTAL BOUNDS THE PAGE, so a page past the end is not a query.
        # A `LIMIT 60` that can never fill has to walk the WHOLE scope to
        # find that out — an Untagged view over a library with nothing
        # untagged cost 243 ms of scan for its zero rows, every time, with
        # the total sitting cached beside it saying so.
        if start >= total:
            return []
        got = s.execute(stmt.order_by(*order)
                        .limit(page_size).offset(start)).all()
        return [(r[0], r[1] if occ else None, r[2] if occ else None)
                for r in got]

    if cands.residue is None:
        total = scope_count(s, db, prefilter.base_select(
            [Item.id], sequence, cands.where, occurrences=occ,
            ranking=cands.ranking))
        page_rows = _rows(prefilter.base_select(
            seq_cols, sequence, cands.where, occurrences=occ,
            ranking=cands.ranking), total)
    else:
        matched = cands.matched_ids(s, res)
        tbl = prefilter.materialize_matches(s, matched)
        # The residue path's own total is the count of MATCHED items, which
        # is the same number only when nothing repeats — so a sequence view
        # counts the joined rows instead, or the grid reserves fewer cards
        # than it pages.
        base = prefilter.base_select(seq_cols, sequence, [], occurrences=occ,
                                     ranking=cands.ranking) \
            .join(tbl, tbl.c.item_id == Item.id)
        total = (len(matched) if not occ else int(s.execute(
            select(func.count()).select_from(
                prefilter.base_select([Item.id], sequence, [], occurrences=occ,
                                      ranking=cands.ranking)
                .join(tbl, tbl.c.item_id == Item.id).subquery())
        ).scalar_one()))
        page_rows = _rows(base, total)

    page_ids = [r[0] for r in page_rows]
    items: dict[int, Item] = {}
    files_by_item: dict[int, list[File]] = {}
    for chunk in chunked(page_ids):
        for it in s.execute(select(Item).where(Item.id.in_(chunk))).scalars():
            items[it.id] = it
        for f in s.execute(
            select(File).where(File.item_id.in_(chunk))
        ).scalars().all():
            files_by_item.setdefault(f.item_id, []).append(f)
    memberships = search.memberships_for(s, page_ids)
    # One entry per ROW — a repeated member appears as often as it sits in
    # the sequence, each with the member row that put it there.
    page_rows = [r for r in page_rows if r[0] in items]
    page_items = [items[r[0]] for r in page_rows]

    # Effective (direct + group-inherited) tags so the grid can highlight
    # items carrying the sidebar-selected tags; direct assignments so it can
    # tell which already carry the full Quick-Assign set.
    eff_map = res.effective_for(page_ids) if page_ids else {}
    direct_by_item: dict[int, list[TagAssignment]] = {}
    for chunk in chunked(page_ids):
        for iid, name, neg in s.execute(
            select(ItemTag.item_id, Tag.name, ItemTag.negative)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .where(ItemTag.item_id.in_(chunk))
        ).all():
            direct_by_item.setdefault(iid, []).append(
                TagAssignment(name=name, negative=neg)
            )

    badges = _seq_badges(s, page_items, sequence=sequence)
    ranks = _member_ranks(s, sequence) if sequence is not None else {}
    seq_counts = _seq_counts(s, page_items)
    seq_inherited = search.seq_inherited(s, page_items, resolver=res)
    seq_by_item, total_by_item, active_by_item = _container_info(s, page_items)
    member_thumbs = _member_thumbs(s, page_items)

    rows: list[ItemOut] = []
    for it, (_iid, member_id, _pos) in zip(page_items, page_rows):
        eff = eff_map.get(it.id)
        badge = badges.get(it.id)
        is_seq = it.kind == "sequence"
        # A sequence's effective tags include the tags its members carry.
        eff_names = set(eff.positive) if eff else set()
        if is_seq:
            eff_names |= seq_inherited.get(it.id, set())
        rows.append(_item_out(
            it, files_by_item.get(it.id, []), memberships.get(it.id, []),
            direct_by_item.get(it.id, []),
            sorted(eff_names), eff_neg=sorted(eff.negative) if eff else [],
            member_id=member_id,
            # THIS occurrence's place in the book, not the first one's:
            # `_seq_badges` answers per item (one card standing for every
            # copy), which is still what an item's own main-sequence badge
            # means outside a sequence view.
            seq_index=(ranks.get(member_id) if member_id is not None
                       else (badge[0] if badge else None)),
            # A container item's badge count is its member total.
            seq_total=total_by_item.get(it.id, 0) if is_seq else (badge[1] if badge else 0),
            seq_count=seq_counts.get(it.id, 0),
            sequence_id=seq_by_item.get(it.id) if is_seq else None,
            active_override=active_by_item.get(it.id) if is_seq else None,
            member_thumbs=member_thumbs.get(it.id, []) if is_seq else None,
        ))

    return ItemPage(items=rows, total=total, page=page, page_size=page_size,
                    rev=library_rev(s))


def library_rev(s: Session) -> str:
    """A cheap fingerprint of the library state a page describes.

    Three indexed MAX() lookups: the items pk moves as an EXTERNAL importer's
    chunks commit (a script's run logs its one event only at the END, so the
    event log alone would sit still through it), the events pk moves on
    every logged edit, deletions included, and `last_imported_at` moves on a
    re-import TOUCH — the one order-shifting write that creates no row and
    logs no event (`_touch_imported`), which is exactly what a crawler
    re-run over already-imported content does to every item it matches:
    without this column in the fingerprint such a run reorders the whole
    Imported ↓ view while the rev sits still, so the grid mixed pre- and
    post-shift pages forever (the same item ringed selected on two pages)
    instead of noticing and re-syncing. The grid compares the value across
    the pages it has assembled: offset pagination under a newest-first sort
    means a window mixing two revisions is describing an ordering that no
    longer exists — the same item on two pages, a click selecting a card the
    layout has since moved — and a writer in another process sends no
    invalidation to heal it. Not a version, not ordered, only ever compared
    for equality.
    """
    from media_compost.db import Event

    mi = s.execute(select(func.max(Item.id))).scalar() or 0
    me = s.execute(select(func.max(Event.id))).scalar() or 0
    mt = s.execute(select(func.max(Item.last_imported_at))).scalar()
    return f"{mi}:{me}:{mt.isoformat() if mt else ''}"


def _check_similar(query) -> None:
    """Refuse a likeness condition asking for more than either space means.

    The tolerance is a Hamming distance over a 256-bit hash (or a 56-bit
    colour signature), and past `MAX_SIMILAR_TOL` everything matches
    everything. Refused rather than clamped: a caller asking for 200 wants
    something this cannot do, and quietly answering a different question is
    how a search comes back with the whole library and looks like it worked.
    """
    from media_compost.query import MAX_SIMILAR_TOL, similar_conditions

    if query is None:
        return
    for cond in similar_conditions(query):
        if cond.tol is not None and not (0 <= cond.tol <= MAX_SIMILAR_TOL):
            raise Invalid(
                "colour tolerance must be 0–{cap} (got {tol})",
                {"cap": MAX_SIMILAR_TOL, "tol": cond.tol},
            )


#: How many ids one range request may answer with.
#:
#: A shift+click is bounded by the VIEW, which can be the whole library, and
#: what comes back is a selection the browser then holds and re-derives from
#: on every render. 50,000 is far past any gesture anybody makes on purpose
#: and still a small reply (gzipped, a few tens of KB); past it the range is
#: truncated and `total` says so rather than the answer quietly being short.
SELECT_RANGE_MAX = 50_000


@router.post("/ids", response_model=ItemIdRange)
async def item_id_range(request: Request, body: "ItemIdRangeRequest",
                        s: Session = Depends(get_session),
                        lib: Library = Depends(get_library)):
    """The ids of one stretch of the view's order — what a SHIFT+CLICK needs.

    The grid holds only the pages it has drawn, so a range whose other end
    has scrolled away is a range it cannot name: the anchor's id is not in
    the loaded list and the click fell back to selecting one item. The
    positions are known on both ends (the grid pages by flat index), so the
    question is "which items are between these two", and only the server can
    answer it.

    Ids and nothing else: the rows would be the ordinary page payload —
    thumbs, tags, groups — for a list the browser is going to reduce to ids
    anyway.

    Through `dbgate` — it is a walk of the view's order like the page query.
    """
    return await dbgate.guarded(request, _item_id_range_sync, body, s)


def _item_id_range_sync(body: "ItemIdRangeRequest", s: Session):
    """The range proper — see `item_id_range`."""
    _check_similar(body.query)
    res = Resolver(s)
    base = search.search_filtered(
        s, **search.scope_of(body), query=body.query, resolver=res)
    start = max(0, int(body.start))
    total = max(0, int(body.count))
    occ = body.sequence is not None
    order = prefilter.order_by_for(body.sort, body.sequence,
                                   ranking=base.ranking)
    want = min(total, SELECT_RANGE_MAX)
    if want <= 0:
        return ItemIdRange(ids=[], total=total)
    if base.residue is None:
        rows = s.execute(
            prefilter.base_select([Item.id], body.sequence, base.where,
                                  occurrences=occ, ranking=base.ranking)
            .order_by(*order).limit(want).offset(start)).scalars().all()
    else:
        # The residue path pages through the per-connection temp table, the
        # way `_page_response` does — its matches are decided in Python.
        tbl = prefilter.materialize_matches(s, base.matched_ids(s, res))
        rows = s.execute(
            prefilter.base_select([Item.id], body.sequence, [], occurrences=occ,
                                  ranking=base.ranking)
            .join(tbl, tbl.c.item_id == Item.id)
            .order_by(*order).limit(want).offset(start)).scalars().all()
    return ItemIdRange(ids=[int(i) for i in rows], total=total)


@router.post("/index", response_model=ItemIndexes)
async def item_index(request: Request, body: "ItemIndexRequest",
                     s: Session = Depends(get_session),
                     lib: Library = Depends(get_library)):
    """Where these items sit in this view's order — see `ItemIndexRequest`.

    Through `dbgate` with the rest: it walks the view's order exactly as the
    range above it does.
    """
    return await dbgate.guarded(request, _item_index_sync, body, s)


def _item_index_sync(body: "ItemIndexRequest", s: Session):
    """The positions proper — see `item_index`.

    A WINDOW FUNCTION over the same ordered select the page query uses, so
    the answers are the rows the grid would draw and not a second opinion
    about the order. The FIRST occurrence where a sequence view repeats an
    item: the grid's cards are occurrences, and what a bookmark points at is
    the picture.
    """
    _check_similar(body.query)
    want = [int(i) for i in body.item_ids if int(i) > 0]
    if not want:
        return ItemIndexes(indices=[None] * len(body.item_ids))
    res = Resolver(s)
    base = search.search_filtered(
        s, **search.scope_of(body), query=body.query, resolver=res)
    occ = body.sequence is not None
    order = prefilter.order_by_for(body.sort, body.sequence,
                                   ranking=base.ranking)
    pos = (func.row_number().over(order_by=order) - 1).label("pos")
    if base.residue is None:
        sel = prefilter.base_select([Item.id.label("id"), pos], body.sequence,
                                    base.where, occurrences=occ,
                                    ranking=base.ranking)
    else:
        # The residue path walks the per-connection temp table, the way the
        # range above and `_page_response` do — its matches are decided in
        # Python.
        tbl = prefilter.materialize_matches(s, base.matched_ids(s, res))
        sel = (prefilter.base_select([Item.id.label("id"), pos], body.sequence,
                                     [], occurrences=occ, ranking=base.ranking)
               .join(tbl, tbl.c.item_id == Item.id))
    numbered = sel.subquery()
    at: dict[int, int] = {}
    for chunk in chunked(want):
        for iid, p in s.execute(
                select(numbered.c.id, func.min(numbered.c.pos))
                .where(numbered.c.id.in_(chunk))
                .group_by(numbered.c.id)):
            at[int(iid)] = int(p)
    return ItemIndexes(indices=[at.get(int(i)) for i in body.item_ids])


@router.post("/query", response_model=ItemPage)
async def query_items(request: Request, body: "ItemSearchRequest",
                      s: Session = Depends(get_session),
                      lib: Library = Depends(get_library)):
    """List items matching a structured condition tree (the frontend's parsed
    query). The backend evaluates the tree directly — it never parses a query
    string. Scope (groups/trash/kind/…), pagination and sort travel in the body.

    Async only to QUEUE: the work is `_query_items_sync`, run through
    `dbgate.guarded` like every other read here that walks the library."""
    return await dbgate.guarded(request, _query_items_sync, body, s, lib)


def _query_items_sync(body: "ItemSearchRequest", s: Session, lib: Library):
    """The page query proper — see `query_items`."""
    _check_similar(body.query)
    res = Resolver(s)
    base = search.search_filtered(
        s, **search.scope_of(body), query=body.query, resolver=res)
    return _page_response(s, base, body.page, body.page_size, body.sort,
                          body.sequence, resolver=res, db=lib.db)


@router.post("/groups", response_model=ItemGroupRuns)
async def item_group_runs(request: Request, body: "ItemGroupRunsRequest",
                          s: Session = Depends(get_session),
                          lib: Library = Depends(get_library)):
    """The grid's sections for one view: ``(key, count)`` in the page order.

    Each run is a CONTIGUOUS stretch of the very order `/query` pages through
    — `order_by_for` prepends the same coarsening — so the counts prefix-sum
    into each section's span in the flat index space the grid already uses.
    That is the whole reason this can be one aggregate rather than a per-item
    group key the pages would have to carry.

    Keys are machine-readable and never labels: month names and colour names
    are localized in the frontend, where the date formatters live.

    Through `dbgate`: it is one aggregate over the whole view, and it is
    fired beside the pages it describes.
    """
    return await dbgate.guarded(request, _item_group_runs_sync, body, s)


def _item_group_runs_sync(body: "ItemGroupRunsRequest", s: Session):
    """The runs proper — see `item_group_runs`."""
    from sqlalchemy import func

    if not body.group_by:
        raise Invalid("group_by is required")
    allowed = prefilter.group_options_for(body.sort,
                                          ranking=body.ranking is not None)
    if body.group_by not in allowed:
        # Refused rather than answered: a grouping that does not match the
        # sort produces runs that are not runs of the page order, and the
        # grid's whole layout is derived from believing that they are.
        raise Invalid(
            "cannot group by {group} when sorting by {sort}"
            + (" (try {allowed})" if allowed else ""),
            {"group": repr(body.group_by), "sort": repr(body.sort),
             "allowed": ", ".join(allowed)}
        )

    _check_similar(body.query)
    res = Resolver(s)
    cands = search.search_filtered(
        s, **search.scope_of(body), query=body.query, resolver=res)
    expr = prefilter.group_expr_for(body.group_by, body.sort)
    order = prefilter.group_order_for(body.sort, body.group_by,
                                      ranking=cands.ranking)
    cols = [expr.label("k"), func.count()]
    if cands.residue is None:
        stmt = prefilter.base_select(cols, cands.sequence, cands.where,
                                     ranking=cands.ranking)
    else:
        # The same bridge back into SQL the paging path uses: evaluate the
        # residue in Python, then aggregate over a join to the matched ids.
        tbl = prefilter.materialize_matches(s, cands.matched_ids(s, res))
        stmt = (prefilter.base_select(cols, cands.sequence, [],
                                      ranking=cands.ranking)
                .join(tbl, tbl.c.item_id == Item.id))
    rows = s.execute(stmt.group_by(expr).order_by(*order)).all()

    runs = [GroupRun(key="" if k is None else str(k), count=int(n))
            for k, n in rows]
    return ItemGroupRuns(rev=library_rev(s), group_by=body.group_by,
                         total=sum(r.count for r in runs), runs=runs)


def _subjects_on_item(s: Session, item_id: int) -> list[SubjectOnItem]:
    """The item's subjects, and every appearance of each.

    A subject IS a tag (plus a display name and a date), so the tag is the
    assignment: remove it and the subject is gone with it. `ItemSubject` says
    how many times they are in the picture, at which face, and how old — a
    manga page holding one character twice at two ages has two rows here and
    one tag.
    """
    from media_compost.db import ItemSubject, ItemSubjectBox, Subject
    from .faces import resolve_when

    rows = s.execute(
        # The one-liner comes off the TAG, which is where what a named thing
        # IS lives — a subject is extra data on one.
        select(Subject, Tag.name, Tag.id, Tag.comment)
        .join(Tag, Tag.id == Subject.tag_id)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .where(ItemTag.item_id == item_id, ItemTag.negative.is_(False))
    ).all()
    seen: dict[int, list[ItemSubject]] = {}
    for row in s.execute(
        select(ItemSubject).where(ItemSubject.item_id == item_id)
    ).scalars().all():
        seen.setdefault(row.subject_id, []).append(row)
    boxes = {b.item_subject_id: b for b in s.execute(
        select(ItemSubjectBox)
        .join(ItemSubject, ItemSubject.id == ItemSubjectBox.item_subject_id)
        .where(ItemSubject.item_id == item_id)).scalars().all()}

    out = []
    for sub, name, tag_id, comment in rows:
        appearances = []
        for r in sorted(seen.get(sub.id, []),
                        key=lambda r: (r.position, r.id)):
            when = resolve_when(r.when_date, r.when_age, sub.since_date)
            appearances.append(SubjectAppearance(
                id=r.id, face_id=r.face_id,
                when=(TagWhen(date=when[0], age=when[1])
                      if when[0] is not None or when[1] is not None else None),
                when_derived=when[2],
                assigned_by=r.assigned_by or "user", match_score=r.match_score,
                position=r.position or 0,
                box=([boxes[r.id].x, boxes[r.id].y,
                      boxes[r.id].w, boxes[r.id].h]
                     if r.id in boxes else None),
                points=(tagassign.points_list(boxes[r.id].points)
                        if r.id in boxes else None),
            ))
        out.append(SubjectOnItem(
            id=sub.id, display_name=sub.display_name, comment=comment or "",
            tag=name, tag_id=tag_id, since_date=sub.since_date,
            appearances=appearances,
        ))
    out.sort(key=lambda r: (r.display_name or r.tag).lower())
    return out


@router.post("/delete")
def delete_items(body: ItemDelete, ctx: Ctx = Depends(get_ctx)):
    """Delete items (and their file/caption/tag/group rows via cascade) along
    with their on-disk folders (files and artifacts) and thumbnails."""
    return {"ok": True, "count": ops_items.delete_items(ctx, body.item_ids)}


@router.post("/trash")
def trash_items(body: ItemDelete, ctx: Ctx = Depends(get_ctx)):
    """Move items to the Trash: snapshot their groups, then drop them out of
    every group so they vanish from all normal listings until restored."""
    return {"ok": True, "count": ops_items.trash(ctx, body.item_ids)}


@router.post("/restore")
def restore_items(body: ItemDelete, ctx: Ctx = Depends(get_ctx)):
    """Restore trashed items to the groups they were in when trashed (skipping
    any groups that no longer exist)."""
    return {"ok": True, "count": ops_items.restore(ctx, body.item_ids)}


@router.post("/hide")
def hide_items(body: ItemHide, ctx: Ctx = Depends(get_ctx)):
    """Mark items hidden (or visible again)."""
    return {"ok": True, "count": ops_items.hide(ctx, body.item_ids, body.hidden)}


# ---- the same three, over a whole VIEW -------------------------------------
#
# With nothing selected, the sidebar's actions are about everything the grid
# is showing — which can be the whole library, so the SCOPE travels and
# `viewscope` resolves it (see that module for why there is exactly one
# resolution). Each of these is the id-list endpoint above with its scope
# resolved and its transaction chunked; the op underneath is the same bulk op,
# so History and revert learn nothing new.
#
# WHAT IS DELIBERATELY NOT HERE is a whole-view PERMANENT delete. Trashing is
# reversible, which is what makes it offerable over a scope nobody has
# enumerated; `delete_items` is not, and the one place that erases a library's
# worth of pictures should stay the Trash's own Empty button, where what is
# about to go can be looked at first.


@router.post("/view/groups", response_model=ViewActionOut)
def view_group_membership(body: ViewGroupMembership,
                          ctx: Ctx = Depends(get_ctx),
                          s: Session = Depends(get_session),
                          lib: Library = Depends(get_library)):
    """Add every item in the view to (and/or remove it from) groups."""
    if not body.add and not body.remove:
        return ViewActionOut()
    ids = viewscope.view_ids(s, lib, body)
    count = 0
    for chunk in viewscope.chunks(ids):
        added, removed = ops_groups.bulk_membership(
            ctx, chunk, add=body.add, remove=body.remove)
        count += added + removed
        s.commit()
    return ViewActionOut(count=count, total=len(ids))


@router.post("/view/hide", response_model=ViewActionOut)
def view_hide(body: ViewVisibility, ctx: Ctx = Depends(get_ctx),
              s: Session = Depends(get_session),
              lib: Library = Depends(get_library)):
    """Hide — or show again — every item in the view. ``count`` is what
    actually CHANGED, which over a view is routinely fewer than `total`: the
    op skips an item already in that state."""
    ids = viewscope.view_ids(s, lib, body)
    count = 0
    for chunk in viewscope.chunks(ids):
        count += ops_items.hide(ctx, chunk, body.hide)
        s.commit()
    return ViewActionOut(count=count, total=len(ids))


@router.post("/view/trash", response_model=ViewActionOut)
def view_trash(body: ViewTrash, ctx: Ctx = Depends(get_ctx),
               s: Session = Depends(get_session),
               lib: Library = Depends(get_library)):
    """Move every item in the view to the Trash."""
    ids = viewscope.view_ids(s, lib, body)
    count = 0
    for chunk in viewscope.chunks(ids):
        count += ops_items.trash(ctx, chunk)
        s.commit()
    return ViewActionOut(count=count, total=len(ids))


@router.post("/empty-trash")
def empty_trash(ctx: Ctx = Depends(get_ctx)):
    """Permanently delete *every* trashed item (regardless of current filter),
    along with each item's on-disk folder and thumbnails."""
    return {"ok": True, "count": ops_items.empty_trash(ctx)}


@router.post("/merge")
def merge_items(body: ItemMerge, ctx: Ctx = Depends(get_ctx)):
    """Fold ``source_id`` into ``target_id``."""
    target_id = ops_items.merge(ctx, body.source_id, body.target_id)
    return {"ok": True, "target_id": target_id}


_DETAILS_CAP = 500


@router.post("/details", response_model=ItemDetailsOut)
def item_details_bulk(body: ItemDetailsIn, s: Session = Depends(get_session)):
    """Slim per-item details for a batch of items — what the grid's context
    menu needs (the caption probe and the copy actions) without a full
    ``ItemDetail`` fetch per item.

    Per item: ``captions`` (full :class:`CaptionOut` rows), ``tags`` (the
    DIRECT tag names, both signs, sorted), ``tag_groups`` (id/name/system —
    meta tags and subjects stay empty) and ``tag_instances`` (each direct
    tag's placements, implicit ungrouped instances included; ``boxes`` stays
    empty). Requests over 500 ids are refused with 413. Items that do not
    exist are simply absent from the reply.
    """
    ids = list(dict.fromkeys(body.item_ids))
    if len(ids) > _DETAILS_CAP:
        raise HTTPException(
            413, f"at most {_DETAILS_CAP} items per request")
    if not ids:
        return ItemDetailsOut(items=[])
    found = [iid for chunk in chunked(ids) for iid in s.execute(
        select(Item.id).where(Item.id.in_(chunk))).scalars().all()]
    present = set(found)

    caps: dict[int, list[Caption]] = {}
    for chunk in chunked(ids):
        for c in s.execute(
            select(Caption).where(Caption.item_id.in_(chunk))
            .order_by(Caption.position, Caption.id)
        ).scalars().all():
            caps.setdefault(c.item_id, []).append(c)
    cap_tags: dict[int, list[str]] = {}
    all_cap_ids = [c.id for rows in caps.values() for c in rows]
    for chunk in chunked(all_cap_ids):
        for cid, name in s.execute(
            select(CaptionTag.caption_id, CaptionTag.name)
            .where(CaptionTag.caption_id.in_(chunk))
            .order_by(CaptionTag.name)
        ).all():
            cap_tags.setdefault(cid, []).append(name)
    # An instruction's references, in order — BARE ids. What reads them copies
    # an instruction onto another item and re-links the same sources; the
    # hydrated form (uid, name, thumbnail file) is the single-item detail's,
    # where a reference strip is actually rendered.
    cap_refs: dict[int, list[CaptionRefOut]] = {}
    for chunk in chunked(all_cap_ids):
        for cid, riid in s.execute(
            select(CaptionRef.caption_id, CaptionRef.item_id)
            .where(CaptionRef.caption_id.in_(chunk))
            .order_by(CaptionRef.caption_id, CaptionRef.position, CaptionRef.id)
        ).all():
            cap_refs.setdefault(cid, []).append(CaptionRefOut(item_id=riid))

    # Relationships, both directions, with their meta tags.
    links: dict[int, list[LinkSlim]] = {}
    rel_rows: list[Relationship] = []
    for chunk in chunked(ids):
        rel_rows.extend(s.execute(
            select(Relationship).where(
                or_(Relationship.from_item_id.in_(chunk),
                    Relationship.to_item_id.in_(chunk)))
        ).scalars().all())
    rel_tags = ops_links.tags_by_rel(s, [r.id for r in rel_rows])
    for r in rel_rows:
        for iid, out_going, other in (
            (r.from_item_id, True, r.to_item_id),
            (r.to_item_id, False, r.from_item_id),
        ):
            if iid not in present:
                continue
            links.setdefault(iid, []).append(LinkSlim(
                other_item_id=other, outgoing=out_going, kind=r.kind,
                tags=rel_tags.get(r.id, []),
            ))

    tg_by_item: dict[int, list[TagGroupOut]] = {}
    for chunk in chunked(ids):
        for g in s.execute(
            select(ItemTagGroup).where(ItemTagGroup.item_id.in_(chunk))
            .order_by(ItemTagGroup.position, ItemTagGroup.id)
        ).scalars().all():
            tg_by_item.setdefault(g.item_id, []).append(
                TagGroupOut(id=g.id, name=g.name, system=bool(g.system)))

    # Direct assignments and their placements. An assignment with no
    # placement row is the implicit ungrouped instance — same rule as the
    # single-item detail.
    direct: dict[int, list[tuple[str, bool, bool]]] = {}
    for chunk in chunked(ids):
        for iid, name, neg, pend in s.execute(
            select(ItemTag.item_id, Tag.name, ItemTag.negative,
                   ItemTag.pending)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .where(ItemTag.item_id.in_(chunk))
        ).all():
            direct.setdefault(iid, []).append(
                (name, bool(neg), bool(pend)))
    inst_by_item: dict[int, list[TagInstance]] = {}
    placed: dict[int, set[str]] = {}
    for chunk in chunked(ids):
        for iid, pid, gid, name, neg, pend in s.execute(
            select(ItemTag.item_id, ItemTagPlacement.id,
                   ItemTagPlacement.group_id, Tag.name,
                   ItemTagPlacement.negative, ItemTag.pending)
            .join(ItemTag, ItemTag.id == ItemTagPlacement.item_tag_id)
            .join(Tag, Tag.id == ItemTag.tag_id)
            .where(ItemTag.item_id.in_(chunk))
        ).all():
            placed.setdefault(iid, set()).add(name)
            inst_by_item.setdefault(iid, []).append(TagInstance(
                placement_id=pid, name=name, negative=bool(neg),
                group_id=gid, pending=bool(pend)))
    # Live top-level regions on each item's ACTIVE file — the same count the
    # single-item detail reports, in one grouped pass. The active-file join
    # is not optional: a region belongs to the FILE it was read from, and
    # counting an edited item's old file's text would say the picture on
    # screen has been read when it has not.
    text_counts: dict[int, int] = {}
    for chunk in chunked(ids):
        for iid, n in s.execute(
            select(TextRegion.item_id, func.count())
            .join(Item, Item.id == TextRegion.item_id)
            .where(TextRegion.item_id.in_(chunk),
                   TextRegion.file_id == Item.active_file_id,
                   TextRegion.parent_id.is_(None),
                   TextRegion.dismissed.is_(False))
            .group_by(TextRegion.item_id)
        ).all():
            text_counts[iid] = n

    out = []
    for iid in ids:
        if iid not in present:
            continue
        insts = inst_by_item.get(iid, [])
        for name, neg, pend in sorted(direct.get(iid, [])):
            if name not in placed.get(iid, set()):
                insts.append(TagInstance(name=name, negative=neg,
                                         pending=pend))
        out.append(ItemSlim(
            id=iid,
            # `refs` rides along as BARE ids (see `cap_refs`): copying an
            # instruction means re-linking the same sources on the target, and
            # that needs the ids and their order and nothing else.
            captions=[CaptionOut(
                id=c.id, text=c.text, kind=c.kind or "caption",
                pending=bool(c.pending),
                model=ml_registry.model_label(c.model) if c.model else "",
                edited=bool(c.edited), tags=cap_tags.get(c.id, []),
                refs=cap_refs.get(c.id, []),
            ) for c in caps.get(iid, [])],
            tags=sorted({n for n, *_ in direct.get(iid, [])}),
            tag_groups=tg_by_item.get(iid, []),
            tag_instances=insts,
            links=links.get(iid, []),
            text_count=text_counts.get(iid, 0),
        ))
    return ItemDetailsOut(items=out)


def _num_text(value: float) -> str:
    """A number as the atom should carry it — no trailing ``.0`` on a whole
    one, because `numTolerance` reads the written decimals as the comparison's
    precision and ``400.0`` would mean ±0.05 where ``400`` means exact."""
    if value == int(value):
        return str(int(value))
    return repr(round(value, 6))


def _meta_row(name: str, mtype: str, num, text, raw: str, *,
              searchable: bool, pinned: bool = False, muted: bool = False,
              sources: list[MetadataSource] | None = None) -> MetadataField:
    """One indexed value, as the Info tab shows it and the filter button writes
    it. ``searchable`` is what decides `filter_value`: a value only an unpinned,
    non-active file carries is SHOWN but is not what search would find the item
    by, and a button claiming otherwise would be a condition about a different
    picture."""
    from media_compost import media

    iso = media.exif_datetime_iso(raw) if mtype == "date" else None
    if mtype == "text":
        atom = text or raw
    elif num is None:
        atom = raw
    else:
        atom = (_num_text(num) if mtype != "date"
                else str(int(num)).rjust(14, "0"))
    return MetadataField(
        key=media.meta_label(name), value=raw or (text or ""), iso=iso,
        name=name, filter_value=atom if searchable else None,
        pinned=pinned, muted=muted, sources=sources or [],
    )


@router.get("/{item_id}/metadata", response_model=ItemMetadataOut)
def item_metadata(item_id: int, s: Session = Depends(get_session),
                  lib: Library = Depends(get_library)):
    """The Info tab: what this item IS, and what its files say about it.

    Two lists, and the split is the whole feature. ``fields`` is the MAIN
    section — the item's own dates and dimensions, then every value it actually
    answers with: the ones promoted to the item, and the ones its ACTIVE file
    gives (muted ones included, struck rather than dropped, so there is a way
    back). ``others`` is every value only a NON-ACTIVE file carries, offered
    rather than applied — metadata from another file never joins the main
    section until somebody pins it.

    It reads the tables and never touches the filesystem, which also took an
    ffprobe subprocess out of every render of a video's panel (``has_audio`` is
    read once, at import, and is searchable now as a side effect).

    INTRINSIC rows carry no sources and can be neither pinned nor muted: width,
    format and the rest are read live off whichever file is active
    (`prefilter._intrinsic_num_expr`), so promoting one would change nothing
    any search could see. The way to change an item's width is to change which
    file is in charge, and that control is one tab to the left.
    """
    item = s.get(Item, item_id)
    if not item:
        return ItemMetadataOut()
    from media_compost import media

    fields: list[MetadataField] = []
    # The item's media type and import dates live here (filterable), not in the
    # Properties block. Always shown; the frontend formats the ISO per the
    # user's preferences.
    type_label = {"sequence": "Sequence", "video": "Video"}.get(
        item.kind, "Image")
    fields.append(MetadataField(key="Type", value=type_label, name="type",
                                filter_value=item.kind or None))
    for label, when, cat in (("First import", item.created_at, "import_date"),
                             ("Last import", item.last_imported_at,
                              "last_import_date")):
        if when is not None:
            fields.append(MetadataField(
                key=label, value=when.isoformat(), iso=when.isoformat(),
                name=cat, filter_value=when.strftime("%Y%m%d%H%M%S")))
    # Last modification: bumped by touch_items on any change to the item. NOT
    # filterable — it is the item's own last-change stamp and is in no search
    # catalog, so it carries no `name` and the button is not drawn.
    if item.updated_at is not None:
        fields.append(MetadataField(key="Modified",
                                    value=item.updated_at.isoformat(),
                                    iso=item.updated_at.isoformat()))

    # A sequence container owns no files of its own (its active file is
    # borrowed from a member, whose EXIF would be misleading here) — show its
    # member count instead. Count-only row: nothing to filter by.
    if item.kind == "sequence":
        from sqlalchemy import func

        count = s.execute(
            select(func.count(SequenceItem.id))
            .join(Sequence, Sequence.id == SequenceItem.sequence_id)
            .where(Sequence.item_id == item_id)
        ).scalar_one()
        fields.insert(1, MetadataField(key="Items", value=str(count)))
        return ItemMetadataOut(fields=fields)

    files = list(s.execute(
        select(File).where(File.item_id == item_id).order_by(File.number)
    ).scalars().all())
    by_id = {f.id: f for f in files}
    af = by_id.get(item.active_file_id or 0)

    # ---- intrinsic rows, off the active file's own columns ----
    if af is not None:
        if af.width and af.height:
            fields.append(MetadataField(
                key="Width", value=f"{af.width} px", name="width",
                filter_value=str(af.width)))
            fields.append(MetadataField(
                key="Height", value=f"{af.height} px", name="height",
                filter_value=str(af.height)))
            fields.append(MetadataField(
                key="Resolution",
                value=media.megapixel_label(af.width, af.height),
                name="resolution",
                filter_value=_num_text(round(af.width * af.height / 1e6, 1))))
        if af.format:
            fields.append(MetadataField(
                key="Format", value=af.format.upper(), name="format",
                filter_value=af.format.upper()))
        if af.duration is not None:
            fields.append(MetadataField(
                key="Length", value=_fmt_duration(af.duration), name="length",
                filter_value=_num_text(round(af.duration, 2))))
        if af.frame_rate is not None:
            fields.append(MetadataField(
                key="Frame rate", value=f"{af.frame_rate:.2f} fps", name="fps",
                filter_value=_num_text(round(af.frame_rate, 2))))
        if af.bitrate is not None:
            mbps = af.bitrate / 1_000_000.0
            fields.append(MetadataField(
                key="Bitrate", value=f"{mbps:.2f} Mbps", name="bitrate",
                filter_value=_num_text(round(mbps, 2))))

    # ---- what the files and the item say ----
    per_file: dict[int, dict[str, FileMetadata]] = {}
    if files:
        for row in s.execute(
            select(FileMetadata).where(FileMetadata.file_id.in_(list(by_id)))
        ).scalars().all():
            per_file.setdefault(row.file_id, {})[row.name] = row
    pins = list(s.execute(
        select(ItemMetaPin).where(ItemMetaPin.item_id == item_id)
        .order_by(ItemMetaPin.name, ItemMetaPin.raw)
    ).scalars().all())
    muted = {m for (m,) in s.execute(
        select(ItemMetaMute.name).where(ItemMetaMute.item_id == item_id)
    ).all()}

    def _sources(name: str, raw: str) -> list[MetadataSource]:
        """Every file that gives this exact value for this name."""
        return [
            MetadataSource(file_id=f.id, number=f.number,
                           active=f.id == item.active_file_id)
            for f in files
            if (per_file.get(f.id, {}).get(name) is not None
                and (per_file[f.id][name].raw or "") == raw)
        ]

    shown: set[tuple[str, str]] = set()
    # Pins first: they are the item's own answer, so they lead the section.
    for p in pins:
        shown.add((p.name, p.raw or ""))
        fields.append(_meta_row(
            p.name, p.mtype, p.num_value, p.text_value, p.raw or "",
            searchable=True, pinned=True,
            sources=_sources(p.name, p.raw or "")))
    # Then the active file's own, in the order `_EXIF_INDEX` declares.
    if af is not None:
        for name, row in sorted(
            per_file.get(af.id, {}).items(),
            key=lambda kv: media.meta_order(kv[0]),
        ):
            raw = row.raw or ""
            if (name, raw) in shown:
                continue        # already standing as a pin of the same value
            shown.add((name, raw))
            fields.append(_meta_row(
                name, row.mtype, row.num_value, row.text_value, raw,
                # A muted value is shown and NOT searched — that is what muting
                # is — so it carries no atom for the filter button.
                searchable=name not in muted, muted=name in muted,
                sources=_sources(name, raw)))

    # ---- the other files ----
    others: list[MetadataField] = []
    seen_other: set[tuple[str, str]] = set()
    for f in files:
        if f.id == item.active_file_id:
            continue
        for name, row in sorted(per_file.get(f.id, {}).items(),
                                key=lambda kv: media.meta_order(kv[0])):
            raw = row.raw or ""
            # One row per UNIQUE value, and never one the main section already
            # shows: repeating an answer that is already the item's says
            # nothing, and the offer attached to it would be a no-op.
            if (name, raw) in shown or (name, raw) in seen_other:
                continue
            seen_other.add((name, raw))
            others.append(_meta_row(
                name, row.mtype, row.num_value, row.text_value, raw,
                searchable=False, sources=_sources(name, raw)))
    return ItemMetadataOut(fields=fields, others=others)


@router.post("/{item_id}/metadata/pin")
def pin_metadata(item_id: int, body: PinMetadataIn,
                 ctx: Ctx = Depends(get_ctx)):
    """Promote what one of the item's files says onto the item itself, where it
    survives the active file changing."""
    ops_metadata.pin(ctx, item_id, body.name, body.file_id)
    return {"ok": True}


@router.post("/{item_id}/metadata/unpin")
def unpin_metadata(item_id: int, body: UnpinMetadataIn,
                   ctx: Ctx = Depends(get_ctx)):
    return {"ok": ops_metadata.unpin(ctx, item_id, body.name, body.raw)}


@router.post("/{item_id}/metadata/mute")
def mute_metadata(item_id: int, body: MuteMetadataIn,
                  ctx: Ctx = Depends(get_ctx)):
    """Stop taking one name from the item's active file. A verb of its own
    rather than a nullable flag on the pin route: a misspelled field must not
    silently mean the opposite and answer 200."""
    return {"ok": ops_metadata.mute(ctx, item_id, body.name)}


@router.post("/{item_id}/metadata/unmute")
def unmute_metadata(item_id: int, body: MuteMetadataIn,
                    ctx: Ctx = Depends(get_ctx)):
    return {"ok": ops_metadata.unmute(ctx, item_id, body.name)}


@router.get("/{item_id}/tracks", response_model=MediaTracks)
def item_tracks(item_id: int, s: Session = Depends(get_session),
                lib: Library = Depends(get_library)):
    """Media streams (video/audio/subtitle tracks) inside the active file.

    Best-effort via ffprobe; returns an empty list for images or when the probe
    finds a single video track only (already surfaced in Properties)."""
    from media_compost import media

    item = s.get(Item, item_id)
    if not item or item.active_file_id is None:
        return MediaTracks(tracks=[])
    f = s.get(File, item.active_file_id)
    if not f or not f.path:
        return MediaTracks(tracks=[])
    path = lib.store.path_of(s, f)
    if not path.exists():
        return MediaTracks(tracks=[])
    tracks = media.probe_tracks(path)
    return MediaTracks(tracks=[MediaTrack(**t) for t in tracks])


def _latent_variant(path: str) -> str:
    """"flipped" / "masked" / "flipped, masked" for a latent cache entry.

    A file has one entry per bucket, plus a separately encoded mirrored copy
    when flipping is on and its own set for masked runs (`-am`), so the rows
    are only distinguishable by which variant each one is.
    """
    name = (path or "").rsplit("/", 1)[-1]
    parts = []
    if name.endswith("-f.pt"):
        parts.append("flipped")
    if "-am-" in name:
        parts.append("masked")
    return ", ".join(parts)


@router.get("/{item_id}", response_model=ItemDetail)
def get_item(item_id: int, s: Session = Depends(get_session)):
    item = s.get(Item, item_id)
    if not item:
        raise HTTPException(404, "item not found")
    files = s.execute(
        select(File).where(File.item_id == item_id)
    ).scalars().all()
    # File numbers are assigned eagerly at creation (they name the on-disk file).
    num_by_fid = {f.id: f.number for f in files}
    group_ids = s.execute(
        select(ItemGroup.group_id).where(ItemGroup.item_id == item_id)
    ).scalars().all()

    # Bounding-box / time-range annotations for this item's direct tags. Boxes
    # belong to a *placement* (a tag instance in a group); collect them keyed by
    # tag name (union across groups, for the flat tag rows) and by placement id
    # (for the grouped tag-instances view).
    boxes_by_tag: dict[str, list[TagBox]] = {}
    boxes_by_placement: dict[int, list[TagBox]] = {}
    for name, pid, b in s.execute(
        select(Tag.name, ItemTagPlacement.id, ItemTagBox)
        .join(ItemTagPlacement, ItemTagPlacement.id == ItemTagBox.placement_id)
        .join(ItemTag, ItemTag.id == ItemTagPlacement.item_tag_id)
        .join(Tag, Tag.id == ItemTag.tag_id)
        .where(ItemTag.item_id == item_id)
    ).all():
        box = TagBox(id=b.id, x=b.x, y=b.y, w=b.w, h=b.h,
                     time_start=b.time_start, time_end=b.time_end,
                     track_id=b.track_id, negative=b.negative,
                     points=tagassign.points_list(b.points))
        boxes_by_tag.setdefault(name, []).append(box)
        boxes_by_placement.setdefault(pid, []).append(box)

    def _assign(name: str, negative: bool) -> TagAssignment:
        return TagAssignment(
            name=name, negative=negative, boxes=boxes_by_tag.get(name, [])
        )

    res = Resolver(s)
    eff = res.effective_for([item_id]).get(item_id)
    tags = []
    if eff:
        for name in sorted(eff.positive):
            tags.append(_assign(name, False))
        for name in sorted(eff.direct_negative):
            tags.append(_assign(name, True))
    group_names = {
        g.id: g.name for g in s.execute(select(Group)).scalars().all()
    }
    # Tags the item assigns directly (either sign) override any indirect copy —
    # the sidebar greys those out inside their read-only group.
    direct_names = (eff.direct_positive | eff.direct_negative) if eff else set()

    def _overridden(names) -> list[str]:
        return sorted(n for n in names if n in direct_names)

    indirect = [
        IndirectGroupTags(
            group_id=gid, group_name=group_names.get(gid, "?"),
            tags=sorted(names), negative=False, source="group",
            overridden=_overridden(names),
        )
        for gid, names in (eff.indirect_by_group.items() if eff else [])
    ]
    indirect += [
        IndirectGroupTags(
            group_id=gid, group_name=group_names.get(gid, "?"),
            tags=sorted(names), negative=True, source="group",
            overridden=_overridden(names),
        )
        for gid, names in (eff.indirect_negative_by_group.items() if eff else [])
    ]
    # Tags implied by the tag hierarchy (a narrower tag entails its parents).
    if eff and eff.indirect_by_parent:
        indirect.append(IndirectGroupTags(
            group_id=-2, group_name="tag hierarchy",
            tags=sorted(eff.indirect_by_parent), negative=False, source="parent",
            overridden=_overridden(eff.indirect_by_parent),
            sources={anc: sorted(srcs) for anc, srcs in eff.parent_sources.items()},
        ))

    # A sequence inherits the tags of the items it contains, shown just like
    # group-inherited tags (a tag directly assigned on the sequence overrides).
    if item.kind == "sequence":
        member_tags = search.seq_inherited(s, [item], resolver=res).get(item_id, set())
        direct_names = (eff.direct_positive | eff.direct_negative) if eff else set()
        inh = sorted(member_tags - direct_names)
        if inh:
            indirect.append(IndirectGroupTags(
                group_id=-1, group_name="sequence contents",
                tags=inh, negative=False, source="sequence",
            ))

    # Directly-assigned tags (with sign) drive the editable tag list; keep them
    # distinct from `tags` (effective) and the group-inherited `indirect` set.
    direct_tags: list[TagAssignment] = []
    if eff:
        for name in sorted(eff.direct_positive):
            direct_tags.append(_assign(name, False))
        for name in sorted(eff.direct_negative):
            direct_tags.append(_assign(name, True))

    # Source filenames per file (a file may carry several after byte-identical
    # re-imports under different names). Source files have no dates of their own.
    names_by_file: dict[int, list[FileNameEntry]] = {}
    if files:
        for nid, fid, nm, is_url, acc in s.execute(
            select(FileName.id, FileName.file_id, FileName.name,
                   FileName.is_url, FileName.accessed_at)
            .where(FileName.file_id.in_([f.id for f in files]))
            .order_by(FileName.created_at, FileName.id)
        ).all():
            names_by_file.setdefault(fid, []).append(FileNameEntry(
                id=nid, name=nm,
                # Treat a legacy URL row (accessed_at set, is_url not yet stored)
                # as a URL too.
                is_url=bool(is_url) or acc is not None,
                accessed_at=acc.isoformat() if acc else None))

    # Auxiliary artifacts per source file: depth maps and pose overlays, and
    # the cached training latents. Latents are tensors rather than images, but
    # they sit in the same folder and take up the same disk, so they are listed
    # too — with the variant that tells one cache entry from another.
    artifacts_by_file: dict[int, list[FileArtifactOut]] = {}
    if files:
        rows = s.execute(
            select(FileArtifact)
            .where(FileArtifact.file_id.in_([f.id for f in files]))
            .order_by(FileArtifact.created_at, FileArtifact.id)
        ).scalars().all()

        def _out(a) -> FileArtifactOut:
            latent = a.kind == "latent"
            return FileArtifactOut(
                id=a.id, kind=a.kind,
                # A latent's `model` is a TRAINING model key (sd15/sdxl/…) and
                # a degraded copy's is its drawn key ("jpeg-q37-s420"), which
                # says more than any sentence would — neither is a plugin id,
                # so both are shown as they stand.
                model=a.model if latent or a.kind == "degraded"
                      else (ml_registry.model_label(a.model) if a.model else ""),
                variant=_latent_variant(a.path) if latent else "",
                width=a.width, height=a.height, bytes=a.bytes,
                format=normalize_format(a.format), stale=a.stale,
            )

        # Two levels: a degraded copy of the picture, and under it the latents
        # encoded FROM it. A parent that somehow isn't in this file's rows
        # leaves its child at the top level rather than dropping it — a row
        # nobody can see is a row nobody can delete.
        built = {a.id: _out(a) for a in rows}
        for a in rows:
            node = built[a.id]
            parent = built.get(a.parent_id) if a.parent_id else None
            if parent is not None:
                parent.children.append(node)
            else:
                artifacts_by_file.setdefault(a.file_id, []).append(node)

    # Trash state: when trashed, surface the (still existing) groups the item
    # will be restored to, since it's been pulled out of all groups meanwhile.
    trash_row = s.execute(
        select(TrashedItem).where(TrashedItem.item_id == item_id)
    ).scalar_one_or_none()
    restore_groups: list[int] = []
    if trash_row is not None:
        existing = set(s.execute(select(Group.id)).scalars().all())
        restore_groups = [
            int(p) for p in trash_row.original_groups.split(",")
            if p.strip().isdigit() and int(p) in existing
        ]

    # Meta tags per caption (same namespace as a link's tags).
    caption_tags: dict[int, list[str]] = {}
    cap_ids = [c.id for c in item.captions]
    if cap_ids:
        for cid, name in s.execute(
            select(CaptionTag.caption_id, CaptionTag.name)
            .where(CaptionTag.caption_id.in_(cap_ids))
            .order_by(CaptionTag.name)
        ).all():
            caption_tags.setdefault(cid, []).append(name)

    # An instruction's reference images, IN ORDER, hydrated with the same three
    # identity fields a link row carries — the row shows a thumbnail and a name.
    caption_refs: dict[int, list[CaptionRefOut]] = {}
    if cap_ids:
        ref_rows = s.execute(
            select(CaptionRef.caption_id, CaptionRef.item_id)
            .where(CaptionRef.caption_id.in_(cap_ids))
            .order_by(CaptionRef.caption_id, CaptionRef.position, CaptionRef.id)
        ).all()
        ref_items = {
            i.id: i for i in s.execute(
                select(Item).where(Item.id.in_({r for _, r in ref_rows}))
            ).scalars().all()
        } if ref_rows else {}
        for cid, riid in ref_rows:
            ri = ref_items.get(riid)
            if ri is None:
                continue
            caption_refs.setdefault(cid, []).append(CaptionRefOut(
                item_id=ri.id, item_uid=ri.uid, name=ri.name or "",
                file_id=ri.active_file_id,
            ))

    # Per-item tag groups and the placement of each direct tag into them (the
    # same tag may appear in several groups, each with its own boxes). A direct
    # tag with no placement row shows once as an implicit ungrouped instance.
    tg_rows = s.execute(
        select(ItemTagGroup).where(ItemTagGroup.item_id == item_id)
        .order_by(ItemTagGroup.position, ItemTagGroup.id)
    ).scalars().all()
    group_tags: dict[int, list[str]] = {}
    if tg_rows:
        for gid, name in s.execute(
            select(ItemTagGroupTag.group_id, ItemTagGroupTag.name)
            .where(ItemTagGroupTag.group_id.in_([g.id for g in tg_rows]))
            .order_by(ItemTagGroupTag.name)
        ).all():
            group_tags.setdefault(gid, []).append(name)
    group_subjects: dict[int, list[int]] = {}
    if tg_rows:
        from media_compost.db import ItemTagGroupSubject

        for gid, sid in s.execute(
            select(ItemTagGroupSubject.group_id, ItemTagGroupSubject.subject_id)
            .where(ItemTagGroupSubject.group_id.in_([g.id for g in tg_rows]))
            .order_by(ItemTagGroupSubject.id)
        ).all():
            group_subjects.setdefault(gid, []).append(sid)
    tag_groups = [
        TagGroupOut(id=g.id, name=g.name, system=bool(g.system),
                    tags=group_tags.get(g.id, []),
                    subjects=group_subjects.get(g.id, []))
        for g in tg_rows
    ]
    tag_instances: list[TagInstance] = []
    placed_names: set[str] = set()
    for pid, gid, name, neg, pend in s.execute(
        select(ItemTagPlacement.id, ItemTagPlacement.group_id,
               Tag.name, ItemTagPlacement.negative, ItemTag.pending)
        .join(ItemTag, ItemTag.id == ItemTagPlacement.item_tag_id)
        .join(Tag, Tag.id == ItemTag.tag_id)
        .where(ItemTag.item_id == item_id)
    ).all():
        placed_names.add(name)
        tag_instances.append(TagInstance(
            placement_id=pid, name=name, negative=neg, group_id=gid,
            pending=bool(pend), boxes=boxes_by_placement.get(pid, []),
        ))
    # An assignment with no placement row is the implicit ungrouped instance,
    # and it can be pending too: a face named by a detector assigns the
    # subject's tag directly, with no group to put it in. Reading `pending`
    # only off the placements left those invisible to every reviewer.
    pending_names = {
        name for name, in s.execute(
            select(Tag.name).join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id == item_id, ItemTag.pending.is_(True))
        ).all()
    }
    if eff:
        for name in sorted(eff.direct_positive):
            if name not in placed_names:
                tag_instances.append(TagInstance(
                    name=name, negative=False,
                    pending=name in pending_names))
        for name in sorted(eff.direct_negative):
            if name not in placed_names:
                tag_instances.append(TagInstance(
                    name=name, negative=True,
                    pending=name in pending_names))

    badge = _seq_badges(s, [item]).get(item_id)
    seq_by_item, total_by_item, active_by_item = _container_info(s, [item])
    seq_count = _seq_counts(s, [item]).get(item_id, 0)
    is_seq = item.kind == "sequence"
    base = _item_out(
        item, files, list(group_ids), direct_tags,
        sorted(eff.positive) if eff else [],
        seq_index=badge[0] if badge else None,
        seq_total=total_by_item.get(item_id, 0) if is_seq else (badge[1] if badge else 0),
        seq_count=seq_count,
        sequence_id=seq_by_item.get(item_id) if is_seq else None,
        active_override=active_by_item.get(item_id) if is_seq else None,
    )
    taken = _taken(s, item)
    where = _coords(s, item)
    return ItemDetail(
        **base.model_dump(),  # carries `uid` now — do not pass it again
        created_at=item.created_at.isoformat() if item.created_at else None,
        last_imported_at=(
            item.last_imported_at.isoformat() if item.last_imported_at else None
        ),
        trashed=trash_row is not None,
        restore_groups=restore_groups,
        files=[
            FileVersion(
                id=f.id, width=f.width, height=f.height, bytes=f.bytes,
                format=normalize_format(f.format), is_derived=f.is_derived,
                active=(f.id == item.active_file_id),
                source_kind=f.source_kind, duration=f.duration,
                frame_rate=f.frame_rate, bitrate=f.bitrate,
                source_start=f.source_start, source_end=f.source_end,
                edited=f.is_derived, rotation=int(f.rotation or 0),
                mirrored=bool(f.mirrored),
                crop_x=f.crop_x, crop_y=f.crop_y, crop_w=f.crop_w, crop_h=f.crop_h,
                created_at=f.created_at.isoformat() if f.created_at else None,
                names=names_by_file.get(f.id, []),
                artifacts=artifacts_by_file.get(f.id, []),
                number=f.number,
                **_edit_lineage(f, num_by_fid),
            )
            for f in sorted(files, key=lambda f: (f.number or 0, f.id))
        ],
        captions=[
            CaptionOut(
                id=c.id, text=c.text, kind=c.kind or "caption",
                pending=bool(c.pending),
                model=ml_registry.model_label(c.model) if c.model else "",
                edited=bool(c.edited),
                tags=caption_tags.get(c.id, []),
                refs=caption_refs.get(c.id, []),
            )
            for c in item.captions
        ],
        tags=tags,
        indirect=indirect,
        tag_groups=tag_groups,
        tag_instances=tag_instances,
        subjects=_subjects_on_item(s, item_id),
        # Which face detectors have already looked at this item — see
        # `ItemFaceRun`, and the Detect faces menus that tick them.
        face_models=sorted({
            m for m, in s.execute(
                select(ItemFaceRun.model).where(ItemFaceRun.item_id == item_id)
            ).all()
        }),
        # …and which text engines have read the ACTIVE file, for the Detect
        # text menus' ticks — per file, so an edited file made active clears
        # them and the re-run is offered fresh.
        text_models=sorted({
            m for m, in s.execute(
                select(ItemTextRun.model).where(
                    ItemTextRun.item_id == item_id,
                    ItemTextRun.file_id == item.active_file_id)
            ).all()
        }),
        # The active file's live top-level regions — the Text tab's badge,
        # counted here so the badge never pulls the whole tree.
        text_count=s.execute(
            select(func.count()).select_from(TextRegion).where(
                TextRegion.item_id == item_id,
                TextRegion.file_id == item.active_file_id,
                TextRegion.parent_id.is_(None),
                TextRegion.dismissed.is_(False))
        ).scalar_one(),
        taken_at=taken[0],
        taken_source=taken[1],
        lat=where[0], lon=where[1], coords_source=where[2],
    )


@router.patch("/{item_id}")
def update_item(item_id: int, body: ItemUpdate, ctx: Ctx = Depends(get_ctx)):
    ops_items.update(ctx, item_id, name=body.name,
                     active_file_id=body.active_file_id,
                     link_item_id=body.link_item_id, taken_at=body.taken_at,
                     lat=body.lat, lon=body.lon,
                     clear_coords=body.clear_coords,
                     no_coords=body.no_coords)
    return {"ok": True}


@router.post("/{item_id}/rotate")
def rotate_item(item_id: int, dir: str = "right",
                ctx: Ctx = Depends(get_ctx)):
    """Rotate the item's *active* image 90° left/right."""
    return {"ok": True, **ops_items.rotate(ctx, item_id, dir)}


@router.post("/{item_id}/groups/{group_id}")
def add_to_group(item_id: int, group_id: int, ctx: Ctx = Depends(get_ctx)):
    ops_items.add_to_group(ctx, item_id, group_id)
    return {"ok": True}


@router.delete("/{item_id}/groups/{group_id}")
def remove_from_group(item_id: int, group_id: int,
                      ctx: Ctx = Depends(get_ctx)):
    ops_items.remove_from_group(ctx, item_id, group_id)
    return {"ok": True}
