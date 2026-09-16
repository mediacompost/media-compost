"""The metadata catalog: every filterable metadata name in the library.

Unions **intrinsic** names (dimensions, duration, import date — computed live)
with **indexed** names (EXIF and similar, from ``item_metadata``), each with a
value type and an item count, plus numeric/date range hints for the value input.
The search UI's Metadata condition builds its autocomplete from this.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select, union_all
from sqlalchemy.orm import Session

from media_compost.db import File, Item, ItemMetaPin, ItemMetadata, TrashedItem
from media_compost.metadata_catalog import INTRINSIC
from ..deps import get_library, get_session
from ..schemas import MetadataCatalogEntry

router = APIRouter(prefix="/api/metadata", tags=["metadata"])


@router.get("/catalog", response_model=list[MetadataCatalogEntry])
def catalog(s: Session = Depends(get_session), lib=Depends(get_library),
            names_only: bool = False) -> list[MetadataCatalogEntry]:
    """The filterable-name catalog. ``names_only=true`` skips every
    distinct-values fetch (the enumerated text dropdowns), so all entries carry
    ``values=None`` — names, types, counts and range hints are unchanged; ask
    ``GET /api/metadata/values`` for one name's values on demand.

    CACHED on the library revision. What is left after the one-pass rewrite
    below is an aggregate over every metadata row (0.68 s at 4.5M) plus a
    scan of the active files — the floor for the question, and the question
    is a pure function of the library that the query builder asks on every
    open. `names_only` is in the key: it is a different answer.
    """
    return lib.db.cached(s, ("meta-catalog", bool(names_only)),
                         lambda: _catalog(s, names_only))


def _catalog(s: Session, names_only: bool) -> list[MetadataCatalogEntry]:
    # Count over visible items (trashed excluded, matching the grid); hidden ones
    # are counted since search can still target them.
    trashed_sub = select(TrashedItem.item_id)
    visible = ~Item.id.in_(trashed_sub)

    # THE INTRINSIC FIGURES ARE ONE PASS, not one per figure. They were
    # eleven — five counts and three min/max pairs, each its own full walk of
    # the active-file join — so a catalog cost eleven scans of the library to
    # answer eleven numbers about the same rows. Conditional aggregates give
    # every one of them from a single scan: measured at 1.5M items, 2.05 s
    # for `names_only=true` against 0.32 s.
    def _n(cond):
        return func.count(case((cond, 1)))

    def _lo(col, cond):
        return func.min(case((cond, col)))

    def _hi(col, cond):
        return func.max(case((cond, col)))

    has_dims = File.width > 0
    has_dur = File.duration.isnot(None)
    has_fps = File.frame_rate.isnot(None)
    has_rate = File.bitrate.isnot(None)
    agg = s.execute(
        select(
            _n(has_dims), _lo(File.width, has_dims), _hi(File.width, has_dims),
            _lo(File.height, has_dims), _hi(File.height, has_dims),
            _n(has_dur), _lo(File.duration, has_dur), _hi(File.duration, has_dur),
            _n(has_fps), _lo(File.frame_rate, has_fps), _hi(File.frame_rate, has_fps),
            _n(has_rate), _lo(File.bitrate, has_rate), _hi(File.bitrate, has_rate),
            _n(File.format != ""), func.count(),
        )
        .select_from(File).join(Item, Item.active_file_id == File.id)
        .where(visible)
    ).one()

    def _f(v):
        return float(v) if v is not None else None

    entries: list[MetadataCatalogEntry] = []
    dim_count = int(agg[0])
    w_lo, w_hi = _f(agg[1]), _f(agg[2])
    h_lo, h_hi = _f(agg[3]), _f(agg[4])
    dur_count, dur_lo, dur_hi = int(agg[5]), _f(agg[6]), _f(agg[7])
    fps_count, fps_lo, fps_hi = int(agg[8]), _f(agg[9]), _f(agg[10])
    rate_count, rate_lo, rate_hi = int(agg[11]), _f(agg[12]), _f(agg[13])
    fmt_count = int(agg[14])
    # Every visible item has an active file here, so the same pass counts
    # them — an item without one carries no intrinsic property to catalog.
    item_count = int(agg[15])
    kinds: list[str] = []
    formats: list[str] = []
    if not names_only:
        # Distinct media kinds present (for the "type" value dropdown).
        kinds = sorted(k for (k,) in s.execute(
            select(Item.kind).where(visible).distinct()
        ).all() if k)
        # Distinct ACTIVE-file formats, for the "format" dropdown. Read live off
        # the files rather than the metadata index: format follows the active
        # file, so an indexed copy would be stale the moment an item is edited.
        formats = sorted({(f or "").upper() for (f,) in s.execute(
            select(File.format).select_from(File)
            .join(Item, Item.active_file_id == File.id).where(visible).distinct()
        ).all() if f})
    # Intrinsic entries with cheap counts + hints (resolution/aspect derived).
    intrinsic_meta = {
        "width": (dim_count, w_lo, w_hi),
        "height": (dim_count, h_lo, h_hi),
        "resolution": (dim_count,
                       (w_lo * h_lo / 1e6) if w_lo and h_lo else None,
                       (w_hi * h_hi / 1e6) if w_hi and h_hi else None),
        "aspect": (dim_count, None, None),
        "length": (dur_count, dur_lo, dur_hi),
        "fps": (fps_count, fps_lo, fps_hi),
        "bitrate": (rate_count, rate_lo, rate_hi),
        "type": (item_count, None, None),
        "format": (fmt_count, None, None),
        "id": (item_count, None, None),
        "import_date": (item_count, None, None),
        "last_import_date": (item_count, None, None),
        # Live tag/caption counts apply to every item (0 when it has none), so
        # no range hint — the search path computes the values at query time.
        "tag_count": (item_count, None, None),
        "caption_count": (item_count, None, None),
        "instruction_count": (item_count, None, None),
        # Same for the face counts: every item has one (0 when it has no
        # faces), computed at query time.
        "faces": (item_count, None, None),
        "unnamed_faces": (item_count, None, None),
        "text_blocks": (item_count, None, None),
        "sequence_count": (item_count, None, None),
        "file_count": (item_count, None, None),
    }
    for name, mtype in INTRINSIC.items():
        count, lo, hi = intrinsic_meta[name]
        if count:
            # bitrate is stored in bps but reported in Mbps.
            if name == "bitrate" and lo is not None:
                lo, hi = lo / 1e6, (hi / 1e6 if hi is not None else None)
            vals = None
            if name == "type" and kinds:
                vals = kinds
            elif name == "format" and formats:
                vals = formats
            entries.append(MetadataCatalogEntry(
                name=name, mtype=mtype, count=count, num_min=lo, num_max=hi,
                values=vals))

    # Indexed (EXIF/static) names: count distinct items + numeric range per name.
    #
    # Over BOTH halves of what an item answers with — its active file's values
    # and anything pinned to it — because the catalog's promise is "how many
    # items would choosing this leave", and reading only `item_metadata` would
    # under-count a name that exists in the library solely as a pin, or omit it
    # from the query builder's autocomplete entirely.
    # NOT trashed, rather than IN (every visible item). The two say the same
    # thing — both metadata tables cascade on the item, so a row whose item
    # is gone cannot exist — and they cost differently: the positive form
    # drove the whole aggregate off a 200,000-id list, one index seek per
    # item. 2.30 s -> 1.93 s on its own, and it is the form the indexes
    # below can work with.
    not_trashed = ~ItemMetadata.item_id.in_(select(TrashedItem.item_id))

    # THE UNION IS SKIPPED WHEN NOTHING IS PINNED, which is nearly always: a
    # pin is a deliberate act on one item. It matters because a compound
    # subquery is materialized as a CO-ROUTINE, so the outer GROUP BY can
    # never be index-ordered through it — SQLite sorts every row into a temp
    # b-tree twice whatever indexes exist. Over 3.6M rows the union costs
    # 2.30 s and the single table 0.56 s.
    #
    # The union is kept for the case it is right for, and the fallback is
    # the whole query rather than a merge: `count(distinct item_id)` over
    # two tables is NOT the sum of their counts, because a pin sits BESIDE
    # the file's answer — the same item can be in both halves for one name
    # — and reconstructing that in Python needs the item sets themselves.
    pinned = s.execute(
        select(ItemMetaPin.id).limit(1)).scalar_one_or_none() is not None
    if pinned:
        idx = union_all(
            select(ItemMetadata.item_id.label("item_id"),
                   ItemMetadata.name.label("name"),
                   ItemMetadata.mtype.label("mtype"),
                   ItemMetadata.num_value.label("num_value"),
                   ItemMetadata.text_value.label("text_value")),
            select(ItemMetaPin.item_id, ItemMetaPin.name, ItemMetaPin.mtype,
                   ItemMetaPin.num_value, ItemMetaPin.text_value),
        ).subquery("indexed_meta")
        src, keep = idx.c, ~idx.c.item_id.in_(select(TrashedItem.item_id))
    else:
        src, keep = ItemMetadata, not_trashed

    rows = s.execute(
        select(
            src.name, src.mtype,
            func.count(func.distinct(src.item_id)),
            func.min(src.num_value), func.max(src.num_value),
        )
        .where(keep)
        .group_by(src.name, src.mtype)
    ).all()

    # Distinct text values per name — an *enumerated* text name (few values,
    # e.g. format / mode) gets a value dropdown in the UI. Names with more than
    # MAX_ENUM distinct values are free-form and get a text field instead.
    # Count the distinct values FIRST and fetch only the qualifying names' —
    # a high-cardinality name (a lens serial, a software string) used to
    # materialize millions of strings just to be thrown away at the cutoff.
    MAX_ENUM = 40
    enum_names = [] if names_only else [
        name for name, n in s.execute(
            select(src.name, func.count(func.distinct(src.text_value)))
            .where(src.mtype == "text", src.text_value.isnot(None), keep)
            .group_by(src.name)
        ).all() if int(n) <= MAX_ENUM
    ]
    text_values: dict[str, set[str]] = {}
    if enum_names:
        for name, val in s.execute(
            select(src.name, src.text_value)
            .where(src.mtype == "text", src.text_value.isnot(None),
                   src.name.in_(enum_names), keep)
            .distinct()
        ).all():
            text_values.setdefault(name, set()).add(val)

    for name, mtype, count, lo, hi in rows:
        vals = text_values.get(name)
        entries.append(MetadataCatalogEntry(
            name=name, mtype=mtype, count=int(count),
            num_min=float(lo) if lo is not None else None,
            num_max=float(hi) if hi is not None else None,
            values=sorted(vals) if (mtype == "text" and vals and len(vals) <= MAX_ENUM) else None,
        ))

    entries.sort(key=lambda e: (-e.count, e.name))
    return entries


@router.get("/values", response_model=list[str])
def values(name: str, q: str = "",
           limit: int = Query(default=50, ge=1, le=200),
           s: Session = Depends(get_session)) -> list[str]:
    """Distinct text values for ONE metadata name — the on-demand complement
    of ``catalog?names_only=true``. Filtered (case-insensitive substring) and
    LIMITed in SQL, sorted, over visible (non-trashed) items — the same scope
    the catalog counts. Covers the intrinsic ``type``/``format`` names too,
    read live like the catalog reads them.
    """
    from .tags import _like_escaped

    if not name.strip():
        raise HTTPException(400, "no metadata name given")
    trashed_sub = select(TrashedItem.item_id)
    visible = ~Item.id.in_(trashed_sub)
    needle = q.strip().lower()

    if name == "type":
        expr = Item.kind
        stmt = select(expr).select_from(Item).where(visible, expr != "")
    elif name == "format":
        expr = func.upper(File.format)
        stmt = (select(expr).select_from(File)
                .join(Item, Item.active_file_id == File.id)
                .where(visible, File.format != ""))
    else:
        # BOTH HALVES, ONE TABLE AT A TIME. A value that exists only as a pin
        # is still a value the grid can be narrowed to, so both are asked —
        # but as a UNION they were asked through a compound subquery, which
        # SQLite materializes as a co-routine that no index can reach into:
        # every row of both tables sorted into a temp b-tree for the DISTINCT.
        # Separately, each is a range on its own covering index and the
        # DISTINCT stops at `limit`. And `NOT IN (trashed)` says exactly what
        # `IN (every visible item)` said — both tables cascade on the item, so
        # a row whose item is gone cannot exist — without driving the whole
        # query off a list of every id in the library.
        #
        # Measured over 4.5M rows: 1.92 s -> 0.79 s for the shape alone,
        # -> 0.08 s with `ix_item_metadata_values` (see `db.ItemMetadata`).
        out: list[str] = []
        for table in (ItemMetadata, ItemMetaPin):
            col = table.text_value
            stmt = select(col).where(
                table.name == name, table.mtype == "text", col.isnot(None),
                ~table.item_id.in_(trashed_sub))
            if needle:
                stmt = stmt.where(func.lower(col).like(
                    f"%{_like_escaped(needle)}%", escape="\\"))
            out.extend(v for (v,) in s.execute(
                stmt.distinct().order_by(col).limit(limit)).all())
        # Merged, deduped and re-cut: two sorted runs, and the caller asked
        # for the first `limit` of the whole.
        return sorted(set(out))[:limit]
    if needle:
        stmt = stmt.where(func.lower(expr).like(
            f"%{_like_escaped(needle)}%", escape="\\"))
    return [v for (v,) in s.execute(
        stmt.distinct().order_by(expr).limit(limit)).all()]
