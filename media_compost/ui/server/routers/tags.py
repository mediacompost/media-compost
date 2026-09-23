"""HTTP for the tag catalog and tag assignment.

Thin over :mod:`media_compost.ops.tagcatalog` and
:mod:`media_compost.ops.tagassign`, which hold the logic and know nothing about
HTTP — so the same operations are reachable from a script, from the CLI and
from the revert layer. What stays here is the read side: the counts, the
autocomplete ranking and the response shapes, which are Pydantic's business
and nobody else's.
"""

from __future__ import annotations

from typing import Optional, Sequence

from collections import OrderedDict, namedtuple
from functools import lru_cache
import json
from weakref import WeakKeyDictionary

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import Response
from pydantic import BaseModel, TypeAdapter
import sqlalchemy as sa
from sqlalchemy import func, or_, select, true
from sqlalchemy.orm import Session

from media_compost import prefs, tagname
from media_compost.db import ItemTag, Tag, TagSetEntry, chunked
from media_compost.library import Library
from media_compost.ops import Ctx, groups, tagassign, tagcatalog, tagsets
from .. import viewscope
from ..deps import get_ctx, get_library, get_session
from ..schemas import (
    LibraryCategoryIn,
    TagCategoryIn,
    AddTagToGroup,
    AssignTag,
    AssignTagBox, PlacementSign,
    BulkDeleteTagsIn,
    BulkTagsIn,
    MoveTagInstance,
    UpdateTagBox,
    QuickAssign,
    QuickAssignView,
    HiddenNamespacesIn,
    TagCreate,
    TagsHiddenIn,
    TagGroupCreate,
    TagGroupOut,
    TagGroupSubjectBody,
    TagGroupTagBody,
    TagGroupUpdate,
    TagImplies,
    TagMerge,
    TagMetaTagBody,
    TagNameRow,
    TagRow,
    TagRowsIn,
    TagUpdate,
)

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _says(d) -> dict:
    """`ops.SetSays` as the wire's `TagSetText` — the dataclass's own
    shaper, so the tags list, the autocomplete and `/describe` cannot
    answer differently about the same tag."""
    return d.as_dict()



def _tag_rows(s: Session, lib=None) -> list[dict]:
    # Counts are the *effective* (resolved) counts: an item counts toward a tag
    # when the tag is effectively positive/negative on it — assigned directly,
    # inherited from a group, implied by a descendant tag (parent implication),
    # or, for a sequence container, carried by any of its members. This is
    # exactly what a search for the tag returns (see items._search_filtered) —
    # computed in SQL rather than by resolving every item (see
    # ``prefilter.effective_tag_counts``).
    #
    # PLAIN DICTS, not `TagRow`s. This list is the one read that materializes
    # the whole catalog, and building a validated model per row is most of
    # what it costs once the queries are cheap: measured at 250,000 tags,
    # 1.9 s to build the models and dump them against 0.38 s for the same
    # bytes as dicts. The KEYS are `TagRow`'s, and
    # `test_tag_list_dicts_match_the_model` holds them to it byte for byte —
    # the model is still the schema, this is only how the page is written.
    from media_compost.prefilter import effective_tag_counts

    pos_count, ind_count, neg_count = effective_tag_counts(s)

    # COLUMNS, not entities. A full ORM load builds an object and an identity
    # map entry per tag for six attributes nobody mutates — measured on a
    # 100,000-tag library, 0.382 s against 0.086 s for the same six columns.
    all_tags = s.execute(
        select(Tag.id, Tag.name, Tag.comment, Tag.description, Tag.alias_of_id,
               Tag.hidden, Tag.category_id)
        .order_by(Tag.name)
    ).all()
    name_by_id = {t.id: t.name for t in all_tags}
    ids = [t.id for t in all_tags]
    implied = tagcatalog.implied_names(s, ids)
    # ONE pass for both — they are the same rows, and this list reads them
    # for the whole catalog.
    metas, mcounts = tagcatalog.meta_marks(s, ids)
    # What the enabled TAG SETS say about every name, one scan of their
    # entries and aliases — a pure function of the library, so it is held on
    # the revision like the counts (`descriptions` stays None here: the
    # whole-catalog listing does not fetch texts; the window's rows do).
    from media_compost.ops import tagsets as tagsets_ops
    if lib is not None:
        setmap = lib.db.cached(s, "tagset-name-map", lambda: tagsets_ops.name_map(s))
    else:
        setmap = tagsets_ops.name_map(s)

    def sets_of(name: str) -> list[dict]:
        return [{"key": h.key, "name": h.name, "count": h.count} for h in setmap.get(name.lower(), ())]

    lib_set = tagsets_ops.library_set(s)
    trails = (tagsets_ops.category_trails(s, lib_set.id)
              if lib_set is not None else {})

    def _library_numbers(name: Optional[str]) -> dict[str, int]:
        # THE MAP THE FRONTEND READS (`TagRow.numbers`, `tags.ts: tagCount`),
        # keyed as `LIBRARY_COLUMNS` and as `POST /api/tags/rows` answers.
        # The three named fields above it stay for the Python side; a row
        # without the map read as zero everywhere this listing is used — the
        # training and evaluate prompt autocomplete, the tag CSV export, the
        # merge and edit overlays' suggestions.
        if not name:
            return {"positive": 0, "implicit": 0, "negative": 0}
        return {"positive": pos_count.get(name, 0),
                "implicit": ind_count.get(name, 0),
                "negative": neg_count.get(name, 0)}

    rows = []
    for t in all_tags:
        if t.alias_of_id is not None:
            # Alias: carry the *linked* tag's counts (for autocomplete) and name.
            tname = name_by_id.get(t.alias_of_id)
            rows.append({
                "id": t.id, "name": t.name, "comment": t.comment,
                "description": t.description or "",
                "category_id": t.category_id,
                "category_trail": trails.get(t.category_id or 0, []),
                "positive": pos_count.get(tname, 0) if tname else 0,
                "positive_indirect": ind_count.get(tname, 0) if tname else 0,
                "negative": neg_count.get(tname, 0) if tname else 0,
                "numbers": _library_numbers(tname),
                "alias_of": tname or "",
                "implies": [],
                "meta_tags": metas.get(t.id, []),
                "meta_counts": mcounts.get(t.id, {}),
                "tag_sets": sets_of(t.name),
                "descriptions": None,
                "hidden": bool(t.hidden),
            })
            continue
        rows.append({
            "id": t.id, "name": t.name, "comment": t.comment,
            "description": t.description or "",
            "category_id": t.category_id,
            "category_trail": trails.get(t.category_id or 0, []),
            "positive": pos_count.get(t.name, 0),
            "positive_indirect": ind_count.get(t.name, 0),
            "negative": neg_count.get(t.name, 0),
            "numbers": _library_numbers(t.name),
            "alias_of": None,
            "implies": implied.get(t.id, []),
            "meta_tags": metas.get(t.id, []),
            "meta_counts": mcounts.get(t.id, {}),
            "tag_sets": sets_of(t.name),
            "descriptions": None,
            "hidden": bool(t.hidden),
        })
    return rows


class _TagPage(BaseModel):
    """The `{rows, total}` envelope `limit` opts into. It exists only so the
    serializer below has a type for it — the wire shape is unchanged."""

    rows: list[TagRow]
    total: int


#: The tag list serialized by PYDANTIC rather than by FastAPI's encoder.
#: `jsonable_encoder` walks every model attribute in Python and is what a
#: whole-catalog response actually spends its time in — measured over 100,000
#: rows, 1.06 s against 0.04 s for the same bytes out of `dump_json`, which is
#: pydantic-core's Rust serializer. The route has to build the JSON itself to
#: reach it, because `response_model` cannot be declared here: the reply is a
#: bare list or a `{rows, total}` envelope depending on `limit`, and FastAPI
#: takes one shape per route.
#: One adapter per SHAPE rather than a union of the two: a smart union has to
#: guess which member it was handed, and guessing costs a warning per response
#: for the envelope, which is a dict with a list in it either way.
_TAG_LIST_JSON = TypeAdapter(list[TagRow])
_TAG_PAGE_JSON = TypeAdapter(_TagPage)


def _json(adapter: TypeAdapter, payload) -> Response:
    return Response(content=adapter.dump_json(payload),
                    media_type="application/json")


def _raw_json(payload) -> Response:
    """The same thing for a payload that is already plain JSON values."""
    import json

    return Response(content=json.dumps(payload).encode(),
                    media_type="application/json")


#: THE LAST FEW INDEX ANSWERS, as the bytes that went out.
#:
#: The index is a pure function of the library and the narrowing, and it is
#: the most expensive read the Tags tab makes — six megabytes and half a
#: second over a 132,000-name set, paid again for every sort, every filter
#: toggle and every time somebody comes back to the tab. Held here rather
#: than in `Database.cached`, which is an LRU of SIXTY-FOUR entries and
#: would hold as much as four hundred megabytes of these.
#:
#: Keyed by the library's REVISION, so a write drops every answer rather
#: than leaving one to go stale; no lock, since the worst a race between two
#: request threads can do is compute the same bytes twice.
#:
#: AND PER LIBRARY, which a revision cannot say on its own: a fresh
#: `Database` starts at zero commits with `PRAGMA data_version` at 1, so two
#: of them in one process — which is every test module here — would answer
#: each other's questions. A weak key so a library's answers leave with it.
_INDEX_CACHE: "WeakKeyDictionary[object, OrderedDict[tuple, bytes]]" = (
    WeakKeyDictionary())
_INDEX_CACHE_MAX = 4


def _index_cached(db, rev, key: tuple) -> Optional[bytes]:
    hold = _INDEX_CACHE.get(db)
    if hold is None:
        return None
    got = hold.get((rev, key))
    if got is not None:
        hold.move_to_end((rev, key))
    return got


def _index_keep(db, rev, key: tuple, body: bytes) -> None:
    hold = _INDEX_CACHE.get(db)
    if hold is None:
        hold = _INDEX_CACHE[db] = OrderedDict()
    for k in [k for k in hold if k[0] != rev]:
        del hold[k]
    hold[(rev, key)] = body
    while len(hold) > _INDEX_CACHE_MAX:
        hold.popitem(last=False)


#: HOW MANY LEADING ROWS THE INDEX MAY CARRY WHOLE.
#:
#: The index says every name and its counts; the REST of a row — its
#: comment, its implications, its capsules, what the sets say — was a second
#: request for the band on screen, and a fresh listing therefore drew twice:
#: names first, then everything under them a round trip later, which moves
#: every row on the page. The first screenful rides along with the index
#: instead, so a listing arrives COMPLETE and the band fetch is left to do
#: what it is for — the bands a scroll reaches. A window is tens of rows;
#: this is the guard on what a caller may ask to have inlined.
_INDEX_ROWS_MAX = 300


#: THE ROWS OF A LISTING ARE PLAIN TUPLES, NOT `Row` OBJECTS.
#:
#: SQLAlchemy's `Row` is built per row and reads per attribute through its
#: own machinery, and this endpoint does both a hundred and thirty thousand
#: times over: materializing the five-column read was 211 ms against 108 for
#: the driver's own tuples, and every pass over them afterwards — the
#: id -> name map, the alias slotting, the response arrays — was five to
#: fifteen times the cost of the same loop over tuples (48 ms against 3 for
#: the map alone). A NAMEDTUPLE rather than the bare tuple so every reader
#: still says `t.name`: its access is a C descriptor and measures the same
#: as unpacking, and the class is keyed on the SHAPE, since which columns
#: are selected depends on what the listing was asked.
#:
#: `Session.connection()` is the same transaction the ORM is reading in —
#: this is the ORM's own statement, executed one layer down, not a second
#: connection. Nothing here writes, so there is no flush to miss.
@lru_cache(maxsize=32)
def _row_class(fields: "tuple[str, ...]"):
    return namedtuple("IndexRow", fields)


def _plain_rows(s: Session, stmt, fields: "tuple[str, ...]") -> list:
    make = _row_class(fields)._make
    return list(map(make, s.connection().execute(stmt).cursor.fetchall()))


@router.get("", response_model=None)
def list_tags(q: str = "", sort: str = "name", dir: str = "asc",
              limit: int | None = Query(default=None, ge=1, le=500),
              offset: int = Query(default=0, ge=0),
              s: Session = Depends(get_session),
              lib=Depends(get_library)):
    """The tag table, optionally filtered / sorted / paged.

    **Paging is opt-in.** Without ``limit`` the response is the bare
    ``list[TagRow]`` it has always been (``q``/``sort``/``offset`` still apply
    to it); with ``limit`` it becomes ``{"rows": [TagRow], "total": N}`` where
    ``total`` is the FILTERED count. ``q`` is a case-insensitive substring
    match on the name; ``sort`` is ``name`` | ``positive``; the counts stay
    the effective ones (one ``effective_tag_counts`` pass either way), and
    alias rows keep their semantics (the linked tag's counts).
    """
    rows = _tag_rows(s, lib)
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if needle in r["name"].lower()]
    reverse = dir == "desc"
    if sort == "positive":
        rows.sort(key=lambda r: (r["positive"], r["name"].lower()),
                  reverse=reverse)
    elif reverse:
        rows.sort(key=lambda r: r["name"].lower(), reverse=True)
    # else: already name-ascending from the SELECT.
    if limit is None:
        return _raw_json(rows[offset:] if offset else rows)
    return _raw_json({"rows": rows[offset:offset + limit], "total": len(rows)})


# ---- the paged tag list ----------------------------------------------------
#
# THE WHOLE CATALOG WAS ONE RESPONSE, and at 250,000 tags that is 4.2 s and
# 60 MB — ~2.7 s of queries nothing can avoid (the effective counts over
# every assignment, the tag columns, the meta marks) and ~1.2 s of building
# and dumping rows the page will never show. `?limit=` did not help, because
# it filtered, sorted and sliced in PYTHON after building every row.
#
# The split is: an INDEX of what the list's own machinery needs about EVERY
# tag — its id and its name, in the order and filtering the view asks for —
# and the ROWS for the window that is actually on screen. The index is what
# the frontend groups by namespace, folds, windows and selects over (those
# are all questions about names), and it is one indexed read; the rows carry
# the counts, the comments, the implications and the meta capsules, for a
# hundred tags rather than a quarter of a million.


def _effective_counts(s: Session, lib, media: str = "") -> tuple[dict, dict, dict]:
    """`effective_tag_counts`, remembered for as long as the library has not
    moved.

    It is two grouped passes over every assignment (1.2 s at 8M) and a pure
    function of the library, and the index needs it for exactly two of its
    questions — sorting by a count, and "unassigned". Uncached, those two
    would each pay it again on every keystroke of the filter above them.
    """
    from media_compost.prefilter import effective_tag_counts

    # `media` is a comma list of kinds; none, or all three, is no narrowing.
    kinds = sorted({k for k in media.split(",") if k in MEDIA_KINDS})
    if len(kinds) == len(MEDIA_KINDS):
        kinds = []
    if lib is None:
        return effective_tag_counts(s, kinds)
    # One memo per kind set: the counts over videos alone are a different
    # answer from the counts over everything, and each is asked repeatedly.
    return lib.db.cached(s, f"effective-tag-counts:{','.join(kinds) or 'all'}",
                         lambda: effective_tag_counts(s, kinds))


#: The tags list's "counted over" filter — an `Item.kind`. Anything else
#: (the default "all") is every item.
MEDIA_KINDS = ("image", "video", "sequence")


def _meta_maxima(s: Session, lib) -> dict[int, int]:
    """Each tag's HIGHEST per-meta count, for the positive sort's tie-break.

    One grouped pass over `tag_meta_tags`, remembered on the library
    revision like the counts beside it — it is only ever asked for by one
    sort, and asking again per keystroke of the filter above it is what a
    cache is for.
    """
    from media_compost.db import TagMetaTag

    def compute():
        return {int(tid): int(mx) for tid, mx in s.execute(
            select(TagMetaTag.tag_id, func.max(TagMetaTag.count))
            .group_by(TagMetaTag.tag_id)).all()}

    if lib is None:
        return compute()
    return lib.db.cached(s, "tag-meta-maxima", compute)


def _with_meta(s: Session, name: str) -> set[int]:
    """The ids of the tags carrying this META tag.

    A meta tag is the mark a bulk import leaves ("danbooru", "booru 4.7k") —
    which is to say, the one thing a catalog of 200,000 names can be cut
    along that nobody has to type. One indexed read of the join table; the
    NAME is matched case-insensitively, because that is how it is written on
    the capsule somebody clicked."""
    from media_compost.db import TagMetaTag

    want = (name or "").strip().lower()
    if not want:
        return set()
    return {int(i) for (i,) in s.execute(
        select(TagMetaTag.tag_id)
        .where(func.lower(TagMetaTag.name) == want)).all()}


def _in_hidden_ns(name: str, hidden_ns: "set[str]") -> bool:
    """Whether this name's NAMESPACE is one of the hidden ones — the same
    reading `tagname.namespace` gives, so the setting and the list cannot
    disagree about whether `character` and `character:` are one thing."""
    if not hidden_ns:
        return False
    ns = tagname.namespace(name)
    return ns is not None and ns.lower() in hidden_ns


#: THE NUMERIC COLUMNS A TAG SET HAS, in the order the header draws them.
#: The library counts PICTURES three ways; an imported set carries the
#: popularity figure its file came with and what the library has under the
#: same name. One list draws whichever pair belongs to the tag set it is
#: showing, and every range filter and every sort speaks these keys.
LIBRARY_COLUMNS = ("positive", "implicit", "negative")
SET_COLUMNS = ("library", "count")

#: How many category ids the index will name in one `IN (...)`. `db.chunked`'s
#: own size: past it the list would have to be split, and a narrowing that
#: wide is most of the set anyway, which the unnarrowed read already serves.
_CATEGORY_IN_MAX = 10_000


def _set_numbers(s: Session, lib, set_id: Optional[int], cols,
                 media: str) -> dict[str, dict[str, int]]:
    """column key -> lowercase name -> the number, for one tag set.

    THE ONE PLACE THE TWO DIFFER once the rows are in hand: what a row of
    the library says is how many pictures carry it, and what a row of an
    imported set says is what its file claimed and what this library has
    under the name. Everything above this — the search, the categories, the
    namespaces, the sorts, the ranges — is the same code for both.
    """
    if set_id is None:
        pos, ind, neg = _effective_counts(s, lib, media)
        return {"positive": {k.lower(): v for k, v in pos.items()},
                "implicit": {k.lower(): v for k, v in ind.items()},
                "negative": {k.lower(): v for k, v in neg.items()}}

    def compute() -> dict[str, dict[str, int]]:
        # THE WHOLE SET, never the rows this listing happens to be showing:
        # the answer is a fact about the tag set and the library, so it is
        # the same for every narrowing and can be remembered for all of them.
        from media_compost.ops import tagsets as _ts
        rows = s.connection().execute(
            select(TagSetEntry.name, TagSetEntry.count)
            .where(TagSetEntry.tag_set_id == set_id)).cursor.fetchall()
        have = _effective_counts(s, lib)[0] if lib is not None else None
        return {"library": _ts.library_counts(s, [n for n, _ in rows], have),
                "count": {n.lower(): int(c) for n, c in rows if c is not None}}

    if lib is None:
        return compute()
    # Cached on the revision, which is what the caller's comment has always
    # said: the library half of it is `effective_tag_counts` (already
    # memoized) read through a chunked probe of the set's every name, and
    # the file half is a dict the size of the set. At 132,000 entries that
    # is 300 ms a listing — paid again for every filter, every sort and
    # every keystroke of the search, since none of them changes it.
    return lib.db.cached(s, f"set-numbers:{set_id}", compute)


def _index_rows(s: Session, lib, *, q: str, sort: str, dir: str, kind: str,
                aliases: bool, implies: bool, unassigned: bool,
                set_id: Optional[int] = None,
                described: Optional[bool] = None,
                behind: "set[int] | None" = None,
                media: str = "", meta: str = "",
                suggest: str = "all", category: str = "",
                uncategorized: bool = False, namespace: Sequence[str] = (),
                ranges: "dict[str, tuple[Optional[int], Optional[int]]] | None" = None):
    """The filtered, sorted rows of every name the view would list — the
    LIBRARY's own (``set_id`` None) or one imported set's.

    ONE LIST, ONE PATH (owner 2026-09). The two used to be two endpoints
    behind two components: a set's entries were paged and narrowed by
    `ops/tagsets.entries_page`, the library's by this. They are names in a
    tag set either way — the same table, the same categories, the same
    namespaces, the same search — and every speed-up, every filter and every
    fix landed on whichever half somebody happened to be looking at.

    Every filter the Tags tab offers is applied HERE rather than over rows
    the browser has been sent, which is the whole point: what leaves the
    server is a few parallel arrays.
    """
    # The COMMENT is read only when something asks about it — the search
    # matches it and one sort orders by it, and nothing else here does. At
    # 250,000 rows a column that is almost always empty is still a column to
    # fetch.
    needle = q.strip().lower()
    want_comment = bool(needle) or sort == "comment"
    #: WHICH TAG SET. `Tag` and `TagSetEntry` are two mapped classes over
    #: one table, so this is the same select with one more clause — and the
    #: discriminator rides on the class, which is what keeps a set's
    #: seventeen thousand names out of every library read that never says so.
    Row = Tag if set_id is None else TagSetEntry
    # A COLUMN NOBODY WILL READ IS NOT SELECTED — not even as a literal
    # stand-in, which is how `comment` and `description` used to travel. At
    # a hundred and thirty thousand rows the ten-column row costs 257 ms to
    # materialize and the five-column one 184. The three guards below are
    # exactly the conditions the readers are already written under, which is
    # what makes leaving a column out the same contract as substituting it:
    # `want_comment` is the search and the comment sort, `described` is the
    # has-a-description filter, and `want_kinds` is the `Is a` filter over a
    # SET — the three record flags answer that and nothing else, and only
    # for a set (the library reads its records from their own tables).
    # `count` used to be in here and is read nowhere at all: every figure
    # the list shows comes from `_set_numbers`.
    want_kinds = kind not in ("", "all") and set_id is not None
    wanted = [Row.id, Row.name, Row.alias_of_id, Row.hidden, Row.category_id]
    if want_comment:
        wanted.append(Row.comment)
    if described is not None:
        wanted.append(Row.description)
    if want_kinds:
        wanted += [Row.is_subject, Row.is_place, Row.is_event]
    sel = select(*wanted)
    # The shape the rows come back in, taken NOW: `wanted` is a local name
    # this function uses again for the category ids.
    fields = tuple(c.key for c in wanted)

    # WHICH NAMESPACES ARE OUT OF THE AUTOCOMPLETE — cached like every
    # other per-request catalog read, since the filter asks per keystroke.
    hidden_ns = set(lib.db.cached(
        s, "hidden-namespaces", lambda: prefs.read_hidden_namespaces(s)))
    # …and the one meta tag the list is narrowed to, where a capsule was
    # clicked. An empty set is "no tag carries it", not "no narrowing".
    with_meta = _with_meta(s, meta) if meta else None

    # WHERE THE LIBRARY FILES IT — the sidebar's category tree, several
    # picked being the UNION, each one taken with its subtree the way the
    # tree's own counts take it. `uncategorized` is the tree's last fixed
    # row and joins the same union, since "in Clothing or filed nowhere" is
    # a thing a person can pick.
    in_cats: "set[Optional[int]] | None" = None
    picked = [int(x) for x in category.replace(",", " ").split() if x.strip("-").isdigit()]
    if picked or uncategorized:
        from media_compost.ops import tagsets as _ts
        # The tag set's OWN tree: the library files its tags in its own
        # set's categories, an imported set in its own. Same rows, same
        # rollup, one branch.
        own = set_id if set_id is not None else (
            lambda ls: ls.id if ls is not None else None)(_ts.library_set(s))
        wanted: set[Optional[int]] = set()
        if own is not None:
            for cid in picked:
                wanted.update(_ts.category_subtree_ids(s, own, cid))
        if uncategorized:
            wanted.add(None)
        in_cats = wanted

    # …and the DERIVED half beside it. A namespace has no row, so this is
    # the text before the first colon and nothing more (`tagname`), matched
    # case-insensitively the way the hidden-namespaces setting is.
    #
    # A NAMESPACE READS AS A CATEGORY HOLDING THE NAMES MADE WITH IT (owner
    # 2026-09): it is picked in the same list of rows by the same gesture,
    # several of them are a union like several categories, and one picked
    # BESIDE a category lists the tags in either. They used to intersect,
    # which made a plain click in the lower block empty the list more often
    # than not.
    want_ns = {ns for ns in
               (x.strip().lower().rstrip(":") for x in namespace) if ns}

    # THE CATEGORY NARROWING IS A WHERE CLAUSE, and it is the one the
    # sidebar sends on every click. Read whole, a 132,000-entry set is
    # 290 ms of rows to throw all but a few hundred of away — again per
    # click, per keystroke and per sort.
    #
    # **AND IT NAMES THE CATEGORIES ONLY.** A category belongs to exactly
    # one tag set, so its rows are that set's rows and `tag_set_id` says
    # nothing further — while SAYING it is what stopped the narrowing
    # working: with both, SQLite (which has no statistics here, and never
    # will — see `research/performance-work.md`) takes the equality on
    # `tag_set_id`, walks all 132,255 rows of the set and tests the
    # category per row. 240 ms for eight rows; asked by category alone it
    # seeks `ix_tags_category_id` in 0.2 ms. UNCATEGORIZED is the
    # exception, being no category at all, so that half of the union
    # carries the scope itself.
    #
    # A NAMESPACE has no column to filter on (it is the text before the
    # first colon), so a pick that includes one reads everything and
    # decides in Python — where the union of the two is spelled, and where
    # it stays: the clause below only ever removes rows the loop would have
    # dropped anyway, so it cannot change an answer.
    scope = TagSetEntry.tag_set_id == set_id if set_id is not None else None
    ids = sorted(c for c in in_cats or () if c is not None)
    # One chunk's worth or nothing: past it the narrowing is most of the set
    # anyway, and an oversized `IN` is the shape `db.chunked` exists for.
    if in_cats is not None and not want_ns and len(ids) <= _CATEGORY_IN_MAX:
        clause = Row.category_id.in_(ids) if ids else sa.false()
        if None in in_cats:
            bare = Row.category_id.is_(None)
            clause = sa.or_(clause, sa.and_(scope, bare)
                            if scope is not None else bare)
        sel = sel.where(clause)
    elif scope is not None:
        sel = sel.where(scope)
    cols = _plain_rows(s, sel.order_by(Row.name), fields)

    # IS IT A PERSON, A PLACE, AN OCCASION — one filter, two answers. What
    # the LIBRARY has is a record row pointing at the tag; what a SET says
    # is a flag on the row, since a set's names are advice and a record is a
    # thing the library HAS. The question is the same either way, which is
    # why the Sets tab's "Is a" and the Items list's kind filter are one
    # control now.
    keep = None
    if kind and kind != "all":
        wanted_kinds = [k for k in
                        (kind.replace(",", " ").split() if kind != "plain"
                         else [])]
        if set_id is not None:
            flag = {"subjects": "is_subject", "places": "is_place",
                    "events": "is_event"}
            if kind == "plain":
                keep = {t.id for t in cols
                        if not (t.is_subject or t.is_place or t.is_event)}
            else:
                want = [flag[k] for k in wanted_kinds if k in flag]
                keep = {t.id for t in cols
                        if any(getattr(t, f) for f in want)}
        else:
            from media_compost.db import Location, Occasion, Subject

            models = {"subjects": Subject, "places": Location,
                      "events": Occasion}
            if kind == "plain":  # a tag no record claims
                claimed: set[int] = set()
                for m in models.values():
                    claimed.update(t for (t,) in s.execute(
                        select(m.tag_id).where(m.tag_id.is_not(None))).all())
                keep = {t.id for t in cols} - claimed
            else:
                keep = set()
                for k in wanted_kinds:
                    m = models.get(k)
                    if m is None:
                        continue
                    keep |= {t for (t,) in s.execute(
                        select(m.tag_id).where(m.tag_id.is_not(None))).all()}

    implied_names = None
    if q or implies:
        # The search matches an IMPLIED name too, so the closure is needed
        # for exactly those two questions — and for nothing else. A set says
        # what it entails by NAME on its own rows; the library's is the
        # closure over its implication table.
        if set_id is not None:
            # THE WHOLE SET'S, held on the revision: it is a fact about the
            # tag set, the same for every narrowing, and the search above it
            # asks per keystroke.
            implied_names = (
                lib.db.cached(s, f"set-implications:{set_id}",
                              lambda: tagsets.implications_of_set(s, set_id))
                if lib is not None else
                tagsets.implications_of_set(s, set_id))
        else:
            implied_names = tagcatalog.implied_names(s, [t.id for t in cols])

    # The numbers are in the index whatever the sort, because the LIST reads
    # them for more than ordering: the namespace parent rows total them, the
    # "unassigned" filter is them, and whether a column is worth drawing is
    # "does any row have one". Cached on the revision, so the first listing
    # pays for them and the rest of the session does not.
    nums = _set_numbers(s, lib, set_id, cols, media)
    keys = SET_COLUMNS if set_id is not None else LIBRARY_COLUMNS
    pos = nums.get("positive", {})
    neg = nums.get("negative", {})

    # Built BEFORE the loop, because the count ranges read an alias's target
    # the way the column does.
    #
    # AND A TARGET MAY BE OUTSIDE THE NARROWING. The rows are read narrowed
    # now, so an alias whose entry sits in another category is here without
    # it; asked for the few that are missing, rather than by reading the
    # whole table back to be sure.
    names_by_id = {t.id: t.name for t in cols}
    missing = sorted({t.alias_of_id for t in cols
                      if t.alias_of_id is not None
                      and t.alias_of_id not in names_by_id})
    for chunk in chunked(missing):
        names_by_id.update(s.execute(
            select(Row.id, Row.name).where(Row.id.in_(chunk))).all())

    def numbers_of(t) -> dict[str, int]:
        """This row's number in each of the tag set's columns.

        AN ALIAS ANSWERS WITH ITS TARGET'S, which is what the cell shows
        and therefore what a range on the column has to narrow by. A column
        the tag set does not have simply is not in the dict.
        """
        nm = (names_by_id.get(t.alias_of_id) if t.alias_of_id is not None
              else t.name)
        ln = (nm or "").lower()
        return {k: nums[k].get(ln, 0) for k in keys}

    # NOTHING TO ASK OF A ROW IS ITS OWN ANSWER. Every test in the loop
    # below can only DROP a row, so when a listing carries no narrowing at
    # all — the first one the tab makes, and every sort of it — the loop is
    # a hundred and thirty thousand iterations to hand back the list it was
    # given. The category clause is already in the SELECT, and `in_cats`
    # stays in this test rather than out of it because a NAMESPACE pick
    # reaches here unnarrowed.
    narrowed = (keep is not None or in_cats is not None or want_ns
                or aliases or implies or unassigned
                or suggest in ("hidden", "shown")
                or with_meta is not None or described is not None
                or behind is not None or bool(ranges) or bool(needle))
    out = list(cols)
    if narrowed:
        out = []
        for t in cols:
            if keep is not None and t.id not in keep:
                continue
            # ONE UNION over both halves of the sidebar (see above): a row is in
            # scope when it is in one of the picked categories OR carries one of
            # the picked namespaces.
            if in_cats is not None or want_ns:
                if not ((in_cats is not None and t.category_id in in_cats)
                        or (want_ns
                            and tagname.namespace(t.name).lower() in want_ns)):
                    continue
            if aliases and t.alias_of_id is None:
                continue
            # KEPT OUT OF THE AUTOCOMPLETE, or not — EITHER WAY it is hidden
            # (owner 2026-09; it was the tag's own flag alone). A name in a
            # hidden namespace is not offered any more than a name somebody
            # took out one at a time, and a filter that could not find those was
            # a filter that answered a question nobody asked.
            if suggest in ("hidden", "shown"):
                gone = bool(t.hidden) or _in_hidden_ns(t.name, hidden_ns)
                if (suggest == "hidden") != gone:
                    continue
            if implies and not (implied_names or {}).get(t.id):
                continue
            if unassigned and (t.alias_of_id is not None
                               or pos.get(t.name.lower(), 0)
                               or neg.get(t.name.lower(), 0)):
                continue
            if with_meta is not None and t.id not in with_meta:
                continue
            # WITH A DESCRIPTION, OR WITHOUT ONE — a three-state question over
            # the long form the tag set wrote for the name.
            if described is not None and bool((t.description or "").strip()) != described:
                continue
            # AND WHAT THE LIBRARY HAS NOT CAUGHT UP WITH: the id set is the
            # caller's, computed once per narrowing rather than per page.
            if behind is not None and t.id not in behind:
                continue
            # A RANGE ON A COUNT COLUMN. Read from the same tables the column
            # draws from, so "positive between 2 and 10" narrows to exactly the
            # rows whose Positive cell reads between 2 and 10 — an alias carries
            # its target's counts here as it does there.
            if ranges:
                got = numbers_of(t)
                if any((lo is not None and got.get(col, 0) < lo)
                       or (hi is not None and got.get(col, 0) > hi)
                       for col, (lo, hi) in ranges.items() if col in got):
                    continue
            if needle and not (
                needle in t.name.lower()
                or needle in (t.comment or "").lower()
                or any(needle in n.lower()
                       for n in (implied_names or {}).get(t.id, []))
            ):
                continue
            out.append(t)

    # EVERY SORT THE LIST OFFERS, here rather than in the browser — the
    # browser is what stopped being given the rows to sort. One rule for
    # every NUMERIC column, whichever tag set's it is.
    rev = dir == "desc"
    if sort == "comment":
        out.sort(key=lambda t: ((t.comment or "").lower(), t.name.lower()),
                 reverse=rev)
    elif sort == "position":
        # THE FILE'S OWN ORDER — an imported set's only. The library has no
        # file, so nothing offers it there.
        out.sort(key=lambda t: (int(t.position or 0) if hasattr(t, "position")
                                else 0, t.name.lower()), reverse=rev)
    elif sort == "category":
        # BY THE TRAIL, name by name: an outer category orders before every
        # one under it and two siblings order by their own names. A joined
        # string put `a/b` between `a` and `a-c` wherever a name held the
        # separator.
        trails = _own_trails(s, set_id, lib)
        rank = {cid: i for i, cid in
                enumerate(sorted(trails, key=lambda c: [n.lower()
                                                        for n in trails[c]]))}
        out.sort(key=lambda t: (t.category_id is None,
                                rank.get(t.category_id, len(rank)),
                                t.name.lower()), reverse=rev)
    elif sort in keys:
        table = nums[sort]
        # A figure NOBODY GAVE sorts last either way, so the numbers stay
        # together at the top of a descending list and the bottom of an
        # ascending one. (A library column always has one: an unassigned tag
        # is on zero pictures. A set's `count` and `library` need not.)
        def one(t):
            nm = (names_by_id.get(t.alias_of_id)
                  if t.alias_of_id is not None else t.name)
            return table.get((nm or "").lower())
        # DECORATED ONCE, because `one` is a dict lookup and a `lower()` per
        # row and the two passes below would each pay for both again. Two
        # passes rather than one key: a figure nobody gave sorts last in
        # EITHER direction, which one reversed key cannot say.
        dec = [(one(t), t.name.lower(), t) for t in out]
        if sort == "positive":
            # The highest per-meta count breaks a tie: a freshly imported
            # dump is thousands of tags at 0 here, and the numbers they came
            # with are the only order they have.
            top = _meta_maxima(s, lib)
            dec.sort(key=lambda d: (d[0] or 0, top.get(d[2].id, 0), d[1]),
                     reverse=rev)
        else:
            dec.sort(key=lambda d: (d[0] or 0, d[1]), reverse=rev)
        dec.sort(key=lambda d: d[0] is None)
        out = [d[2] for d in dec]
    elif rev:
        out.sort(key=lambda t: t.name.lower(), reverse=True)
    # else: already name-ascending from the SELECT.

    # AN ALIAS STANDS UNDER THE NAME IT SPELLS, in EVERY order (owner
    # 2026-09; it was every order but the alphabetical one). The list draws
    # it INDENTED there, the way a namespace's names are drawn under their
    # parent row — so where it sits and how it is drawn say the same thing,
    # and an alias sorted alphabetically away from its tag was a row whose
    # `→ target` was the only thing tying it to anything.
    if True:
        kids: dict[int, list] = {}
        for t in out:
            if t.alias_of_id is not None:
                kids.setdefault(int(t.alias_of_id), []).append(t)
        if kids:
            here = {t.id for t in out}
            slotted = []
            for t in out:
                # An ORPHAN — its target narrowed away, or absent — stays
                # where the sort put it rather than vanishing.
                if t.alias_of_id is not None and int(t.alias_of_id) in here:
                    continue
                slotted.append(t)
                slotted.extend(kids.get(t.id, ()))
            out = slotted

    # AND THE TAG YOU TYPED COMES FIRST, whatever the sort. A search for `a`
    # in a booru-sized library matches four thousand names containing an `a`
    # and the one actually called `a` is somewhere in the middle of them —
    # asking for a name by its whole name and then hunting for it is the list
    # ignoring the most specific thing it was told. `sort` is stable, so this
    # only lifts those rows and leaves everything else in the order chosen
    # above. (The autocomplete has always led its key with this.)
    if needle:
        out.sort(key=lambda t: t.name.lower() != needle)
    return out, names_by_id, nums


def _own_trails(s: Session, set_id: Optional[int],
                lib=None) -> dict[int, list[str]]:
    """The category trails of the tag set being listed — the library's
    own set's, or an imported set's.

    HELD ON THE REVISION, because it is the set's whole category tree and
    two reads ask for it per window: the `category` sort, and every detail
    band, which needs the trail of whatever categories its rows are filed
    in. On the Characters set that is 4,356 rows and 15 ms, and a scroll
    asks for a band per step.
    """
    own = set_id
    if own is None:
        ls = tagsets.library_set(s)
        if ls is None:
            return {}
        own = ls.id
    if lib is None:
        return tagsets.category_trails(s, own)
    return lib.db.cached(s, f"category-trails:{own}",
                         lambda: tagsets.category_trails(s, own))


@router.get("/index", response_model=None)
def tag_index(q: str = "", sort: str = "name", dir: str = "asc",
              kind: str = "all", aliases: bool = False,
              suggest: str = "all", category: str = "",
              uncategorized: bool = False,
              #: THE SIDEBAR'S DERIVED HALF, repeated: a namespace is picked
              #: in the same list of rows a category is, and joins the same
              #: union (`_index_rows`).
              namespace: list[str] = Query(default=[]),
              implies: bool = False, unassigned: bool = False,
              media: str = "all", meta: str = "",
              #: WHICH TAG SET: absent is the LIBRARY's own names, an id
              #: is that imported set's. One list, one path — the Tags tab
              #: draws both through this.
              set_id: Optional[int] = None,
              described: Optional[bool] = None,
              behind: bool = False, behind_records: bool = False,
              pos_min: Optional[int] = None, pos_max: Optional[int] = None,
              ind_min: Optional[int] = None, ind_max: Optional[int] = None,
              neg_min: Optional[int] = None, neg_max: Optional[int] = None,
              lib_min: Optional[int] = None, lib_max: Optional[int] = None,
              cnt_min: Optional[int] = None, cnt_max: Optional[int] = None,
              rows: int = Query(default=0, ge=0, le=_INDEX_ROWS_MAX),
              s: Session = Depends(get_session),
              lib=Depends(get_library)):
    """Which names this view lists, and in what order — ids and names only.

    Two parallel arrays rather than a list of objects: the same 250,000
    answers are 6 MB this way against 60 MB as rows, and the client reads
    them positionally anyway.
    """
    from .tagsets import _behind as _behind_ids

    # `rows` the PARAMETER is how many leading rows to carry whole; `rows`
    # below is the listing's own, which is what this function has always
    # called them.
    leading = rows
    # WHAT THIS ANSWER DEPENDS ON, spelled once: the library and every
    # narrowing. A parameter added to this endpoint belongs in here too, or
    # two different questions share one answer.
    key = (set_id, q, sort, dir, kind, aliases, suggest, category,
           uncategorized, tuple(namespace), implies, unassigned, media, meta,
           described, behind, behind_records, pos_min, pos_max, ind_min,
           ind_max, neg_min, neg_max, lib_min, lib_max, cnt_min, cnt_max,
           rows)
    rev = lib.db.revision(s) if lib is not None else None
    if rev is not None:
        got = _index_cached(lib.db, rev, key)
        if got is not None:
            return Response(content=got, media_type="application/json")

    rows, names_by_id, nums = _index_rows(
        s, lib, q=q, sort=sort, dir=dir, kind=kind, aliases=aliases,
        implies=implies, unassigned=unassigned, media=media,
        set_id=set_id, described=described,
        behind=(_behind_ids(s, lib, set_id, behind, behind_records)
                if set_id is not None else None),
        suggest=suggest, category=category, uncategorized=uncategorized,
        namespace=namespace,
        meta=meta,
        # A RANGE PER NUMERIC COLUMN, and only the ones somebody typed into:
        # an absent bound is no bound, which is what makes "at least 2" and
        # "at most 10" the same control with one end filled in.
        ranges={col: (lo, hi) for col, lo, hi in
                (("positive", pos_min, pos_max), ("implicit", ind_min, ind_max),
                 ("negative", neg_min, neg_max), ("library", lib_min, lib_max),
                 ("count", cnt_min, cnt_max))
                if lo is not None or hi is not None} or None)
    pos = nums.get("positive", {})
    neg = nums.get("negative", {})
    # The same cached read `_index_rows` narrowed by — the mark says WHICH
    # kind of hidden a row is, and a namespace's is not on the row.
    hidden_ns = set(lib.db.cached(
        s, "hidden-namespaces", lambda: prefs.read_hidden_namespaces(s)))
    # How many rows the "unassigned" filter would leave, over everything ELSE
    # this view is narrowed by — the filter menu's count promises exactly
    # that, and the browser can no longer work it out for itself because it
    # is not given the rows.
    # ONE PASS OVER THE ROWS, and one attribute read per field in it. The
    # answer is eight parallel arrays and they were eight walks of a
    # hundred and thirty thousand rows, each paying SQLAlchemy's own
    # attribute machinery again — and a `lower()` again, which every number
    # below is a lookup by. `spelled` is what a row ANSWERS with (an alias
    # carries the linked tag's numbers, exactly as the cell does) where
    # `own` is its own name, which is what "unassigned" asks about.
    ids: list[int] = []
    names: list[str] = []
    alias_names: list[str] = []
    spelled: list[str] = []
    hidden_idx: list[int] = []
    hidden_ns_idx: list[int] = []
    unassigned_total = 0
    for i, t in enumerate(rows):
        name = t.name
        low = name.lower()
        ids.append(t.id)
        names.append(name)
        aid = t.alias_of_id
        if aid is None:
            alias_names.append("")
            spelled.append(low)
            if not unassigned and not pos.get(low, 0) and not neg.get(low, 0):
                unassigned_total += 1
        else:
            target = names_by_id.get(aid) or ""
            alias_names.append(target)
            spelled.append(target.lower())
        if t.hidden:
            hidden_idx.append(i)
        elif _in_hidden_ns(name, hidden_ns):
            hidden_ns_idx.append(i)
    if unassigned:
        unassigned_total = len(rows)

    #: BLANK IS NOT ZERO, and which of the two an absent number means is
    #: the tag set's: a library column counts PICTURES, so a name with
    #: no entry is on none of them; a set's two are figures that need not
    #: exist at all — no popularity in the file, no such tag in the library.
    absent = 0 if set_id is None else None

    body = _raw_json({
        "ids": ids,
        "names": names,
        #: THE NUMERIC COLUMNS THIS TAG SET HAS, keyed by column — the
        #: library's three counts of pictures, or an imported set's pair
        #: (what this library has under the name, and what the file
        #: claimed). `null` where the tag set has no figure at all,
        #: which is not zero: zero is a tag that exists and is on nothing.
        "columns": list(SET_COLUMNS if set_id is not None else LIBRARY_COLUMNS),
        "numbers": {k: [v.get(ln, absent) if ln else absent for ln in spelled]
                    for k, v in nums.items()},
        # The name of the tag an alias points at, "" for an ordinary tag —
        # what the list slots aliases under and what the row renders.
        "alias_of": alias_names,
        # WHICH ROWS THE AUTOCOMPLETE DOES NOT OFFER, as INDICES rather than
        # a boolean per row: it is a handful of rows in a catalog of a
        # quarter of a million, and the mark has to be known for the whole
        # index — it was read off the per-window detail fetch, so it blinked
        # out of every row on every filter change until the band landed.
        # TWO LISTS, because the two are not the same fact: one name was
        # taken out, the other belongs to a namespace that was — and only
        # the first is undone from the row.
        "hidden": hidden_idx,
        "hidden_ns": hidden_ns_idx,
        "total": len(rows),
        "unassigned_total": unassigned_total,
        # THE FIRST SCREENFUL, WHOLE (see `_INDEX_ROWS_MAX`). Empty when the
        # caller did not ask, which is every caller that only wants the
        # names — the browse tree, a test, anything counting.
        "rows": _row_details(s, lib, ids[:leading], set_id) if leading else [],
    })
    if rev is not None:
        _index_keep(lib.db, rev, key, body.body)
    return body


@router.get("/representatives", response_model=None)
def tag_representatives(ids: str = "", s: Session = Depends(get_session)):
    """The REPRESENTATIVE items of the tags named — a comma list of ids, the
    window on screen — as strip refs, per tag (`representatives.py`).

    A read that may WRITE: the short tags are topped up first — the safety
    net for the writers the flush listener cannot see. On a settled library
    that is one indexed count per tag and nothing else.
    """
    from media_compost import representatives
    from .rankings import _refs

    want = list(dict.fromkeys(
        int(x) for x in ids.split(",") if x.strip().isdigit()))[:MAX_ROW_IDS]
    if not want:
        return {"reps": {}}
    by_tag = representatives.for_tags(s, want)
    refs = _refs(s, sorted({i for v in by_tag.values() for i in v}),
                 members=False)
    return {"reps": {str(tid): [refs[i].model_dump() for i in items
                                if i in refs]
                     for tid, items in by_tag.items()}}


@router.delete("/{tag_id}/representatives/{item_id}", response_model=None)
def refuse_representative(tag_id: int, item_id: int,
                          s: Session = Depends(get_session)):
    """"Not representative": the item stops standing for the tag, is never
    picked for it again while it carries the tag, and another item is
    chosen in its place. Answers the tag's strip as it now is."""
    from media_compost import representatives
    from media_compost.ops.errors import NotFound
    from .rankings import _refs

    if not representatives.refuse(s, tag_id, item_id):
        raise NotFound("the item does not carry that tag",
                       code="representative_not_assigned")
    items = representatives.for_tags(s, [tag_id]).get(tag_id, [])
    refs = _refs(s, items, members=False)
    return {"reps": [refs[i].model_dump() for i in items if i in refs]}


def _row_details(s: Session, lib, ids: "list[int]",
                 set_id: Optional[int]) -> list[dict]:
    """THE WHOLE OF A ROW, for the ids named, in the order named.

    Two callers: `POST /rows`, which a scroll asks for the band it has just
    reached, and the INDEX, which carries the first screenful's worth so a
    fresh listing arrives complete (`_INDEX_ROWS`).
    """
    from media_compost.ops import tagsets as tagsets_ops

    ids = list(dict.fromkeys(ids))[:MAX_ROW_IDS]
    if not ids:
        return []
    Row = Tag if set_id is None else TagSetEntry
    cols = {}
    for chunk in chunked(ids):
        sel = select(Row).where(Row.id.in_(chunk))
        if set_id is not None:
            sel = sel.where(TagSetEntry.tag_set_id == set_id)
        for t in s.execute(sel).scalars():
            cols[t.id] = t
    rows = list(cols.values())
    names = {t.id: t.name for t in rows}
    # An alias carries the LINKED tag's counts, so its target's name has to
    # be resolvable even when the target is not on this page.
    want = {t.alias_of_id for t in rows if t.alias_of_id is not None}
    if want - set(names):
        for chunk in chunked(sorted(want - set(names))):
            for tid, nm in s.execute(
                    select(Row.id, Row.name).where(Row.id.in_(chunk))).all():
                names[tid] = nm
    nums = _set_numbers(s, lib, set_id, rows, "all")
    lnames = [t.name.lower() for t in rows]
    # WHAT THE NAME ENTAILS. The library's is the closure over its own
    # implication table; a set says it by name on the row.
    implied = (tagsets_ops.implications_of(s, list(cols)) if set_id is not None
               else tagcatalog.implied_names(s, list(cols)))
    metas, mcounts = tagcatalog.meta_marks(s, list(cols))
    if set_id is not None:
        metas = {k: v for k, v in tagsets_ops.meta_of(s, list(cols)).items()}
    # The enabled TAG SETS' claims and texts, for the window only — three
    # indexed statements for a hundred rows, derived on read (disabling a set
    # takes every capsule with it on the next fetch, nothing to revert). A
    # SET's own row does not wear them: it IS one of the claims.
    sethits = tagsets_ops.name_map(s, lnames) if set_id is None else {}
    settexts = tagsets_ops.descriptions_for(s, lnames) if set_id is None else {}
    # WHERE THE TAG SET FILES THEM — the trails for the window's
    # categories only, resolved once. A trail is a LIST of names: a category
    # name may contain a slash, so a joined string could never be split back.
    trails: dict[int, list[str]] = {}
    if any(t.category_id for t in rows):
        trails = _own_trails(s, set_id, lib)
    # WHAT ONLY A SET'S ROW SAYS: whether the library has the name at all,
    # what of the set's advice it has not taken, and where the switch is off.
    al: dict[int, list[str]] = {}
    gap: dict[int, list[str]] = {}
    rec_gap: dict[int, list[str]] = {}
    have: set[str] = set()
    off: set[Optional[int]] = set()
    all_off = False
    if set_id is None:
        # THE OTHER SPELLINGS OF A LIBRARY TAG, for the window's rows: tags
        # whose target is one of them. A set's entry answers the same
        # question from its own table (`aliases_of` below) — the editor asks
        # it of either tag set, so both have to answer.
        for chunk in chunked(ids):
            for name, target in s.execute(
                select(Tag.name, Tag.alias_of_id)
                .where(Tag.alias_of_id.in_(chunk))
                .order_by(func.lower(Tag.name))
            ).all():
                al.setdefault(int(target), []).append(name)
    if set_id is not None:
        al = tagsets_ops.aliases_of(s, list(cols))
        gap = tagsets_ops.missing_implications(s, rows)
        rec_gap = tagsets_ops.missing_records(s, rows)
        have = tagsets_ops.in_library(s, [t.name for t in rows])
        sets_off, cats_off = tagsets_ops.implication_scopes_off(s, [set_id])
        all_off, off = set_id in sets_off, set(cats_off)
    out = []
    for tid in ids:
        t = cols.get(tid)
        if t is None:
            continue
        alias = names.get(t.alias_of_id) if t.alias_of_id is not None else None
        cname = (alias if t.alias_of_id is not None else t.name) or ""
        ln = t.name.lower()
        row = {
            "id": t.id, "name": t.name, "comment": t.comment,
            "description": t.description or "",
            "category_id": t.category_id,
            "category_trail": trails.get(t.category_id or 0, []),
            "numbers": {k: v.get(cname.lower()) for k, v in nums.items()},
            "alias_of": (alias or "") if t.alias_of_id is not None else None,
            "implies": [] if t.alias_of_id is not None
                       else implied.get(t.id, []),
            "meta_tags": metas.get(t.id, []),
            "meta_counts": mcounts.get(t.id, {}),
            "tag_sets": [{"key": h.key, "name": h.name, "count": h.count}
                         for h in sethits.get(ln, ())],
            # WHAT ELSE THIS NAME IS SPELLED, for the editor's own list. A
            # set's row overwrites it below with its entry's spellings.
            "aliases": al.get(t.id, []),
            "descriptions": [_says(d) for d in settexts.get(ln, ())],
            "hidden": bool(t.hidden),
        }
        if set_id is not None:
            row.update({
                # The OTHER SPELLINGS of this entry. They are rows of the
                # list in their own right; the editor holds them as a field,
                # so a save carries them through untouched.
                "aliases": al.get(t.id, []),
                "in_library": ln in have,
                "missing_implies": gap.get(t.id, []),
                "missing_records": rec_gap.get(t.id, []),
                "implications_off": all_off or t.category_id in off,
                "position": int(t.position or 0),
                **{k: tagsets_ops.record_of(t, k)
                   for k in tagsets_ops.RECORD_FIELDS},
            })
        out.append(row)
    return out


@router.post("/rows", response_model=None)
def tag_rows(body: TagRowsIn, s: Session = Depends(get_session),
             lib=Depends(get_library)):
    """The full rows for the window on screen, in the order asked for.

    A POST because the ids are a body — a window is a hundred of them and a
    URL is not where that belongs. It is a READ, so `build.READ_ONLY_POSTS`
    names it: a stale page must still be able to draw its list.
    """
    return _raw_json(_row_details(s, lib, list(body.ids), body.set_id))


#: How many rows one window may ask for. A window is tens; this is the guard
#: against a caller asking for the catalog one POST at a time.
MAX_ROW_IDS = 2_000


def _like_escaped(needle: str) -> str:
    """``needle`` as a LIKE pattern fragment with its wildcards escaped
    (``ESCAPE '\\'`` on the clause)."""
    return (needle.replace("\\", "\\\\")
            .replace("%", "\\%").replace("_", "\\_"))


def _prefix_bounds(needle: str) -> tuple[str, str] | None:
    """``[lo, hi)`` covering every name that STARTS with ``needle``.

    A RANGE rather than a `LIKE 'needle%'`, because that is the only spelling
    `ix_tags_lname` can answer: SQLite's LIKE optimization wants a plain
    indexed column and does not reach an indexed expression (its query plan
    says so — a scan for the LIKE, a seek for the range).

    ``None`` where the last character has no clean successor — a surrogate
    boundary, or the top of the range. The caller then simply skips the
    prefix stage and scans, which is what it does for a short bucket anyway,
    so this can only ever cost time and never an answer.
    """
    nxt = ord(needle[-1]) + 1
    if 0xD800 <= nxt <= 0xDFFF or nxt > 0x10FFFF:
        return None
    return needle, needle[:-1] + chr(nxt)


@router.get("/names", response_model=list[TagNameRow])
def tag_names(q: str = "", limit: int = Query(default=50, ge=1, le=200),
              s: Session = Depends(get_session), lib=Depends(get_library)):
    """The autocomplete source: tag names matching ``q`` (case-insensitive
    substring, filtered in SQL) with each tag's DIRECT positive count — and,
    behind the library's own rows, the names the enabled TAG SETS know that
    the library does not have yet.

    The order is (1) the EXACT name first — the tag called `ball` must beat
    `football` however their counts compare, because the person has finished
    typing it; (2) then WHERE the match sits, earlier first — `abc_123`
    before `123_abc` for the fragment `abc`, whatever their counts, because a
    name that STARTS with what was typed is what was being reached for; (3)
    then the DIRECT positive count, EQUAL counts ordered by the tag's
    HIGHEST meta-tag count — a freshly imported dump is thousands of tags at
    0 here, and the number they came with (per site now, so the largest
    site's figure) is the only order they have; (4) then the name. Direct
    and not effective, because autocomplete only ranks by it; an alias row
    carries its TARGET's counts, like the full list's alias rows do.

    Each row also carries the tag's meta tags and its nonzero per-meta
    counts — the capsules on the row, and the hover behind them — plus what
    the tag sets say: their claims (`tag_sets`) and their descriptions.

    **NOTHING HERE MAY SCALE WITH THE LIBRARY, and as one statement all of it
    did.** This runs once per KEYSTROKE, and on a 200,000-tag catalog with 3M
    assignments it measured 120–160 ms a keystroke — long enough that the
    list was empty most of the time somebody was typing. Two changes, and
    each attacks a different half:

    **The counts are CORRELATED, not aggregated.** A `GROUP BY tag_id` over
    `item_tags` is materialized in full however few tags match, and it grows
    with the ASSIGNMENT table — the part of a library that grows without
    bound. Per matched tag it is an index-only range count instead, so the
    work is the MATCH: 58 ms for a three-letter fragment where the aggregate
    was 121, and the same 88 ms in the pathological case where the matched
    tags hold most of the assignments. Never worse.

    **And the PREFIX bucket is filled first, from an index.** Rule (2) puts
    every name starting with the fragment above every name merely containing
    it, so those rows are a contiguous RANGE of `ix_tags_lname`
    (`_prefix_bounds`) — a seek rather than a scan of the catalog. Where it
    fills the page, the substring scan never runs at all: a six-letter
    fragment went 120 ms → **0.6 ms**. Where it does not, the second stage
    asks for exactly the rows the first could not supply (`instr > 1`, which
    is the complement of the range by definition), so the two concatenate
    into precisely the order the single statement produced — the same rows,
    in the same order, and `tests/ui/test_tag_names.py` holds them to a
    reference implementation over a catalog built to make the stages
    disagree if they can.

    **THE TAG SETS ARE SEPARATE STATEMENTS, NEVER A UNION.** A compound
    subquery is materialized as a co-routine no index can reach into (the
    `metadata/values` lesson), so the set stage is up to four statements of
    its own — entries and aliases, each in the same prefix-range and
    substring stages over their lowercase indexes, each with a correlated
    `NOT EXISTS` probe of `ix_tags_lname` so a name the library already has
    is the LIBRARY's row (which then wears the set's capsule) — and the
    sources are merged in Python on the same key the SQL ordered by. A
    set-only row ranks after every USED library row at its match position
    and among itself by the set's count; a library row never loses a rank,
    and a library with no enabled set emits exactly the statements it
    always did (`lib.db.cached` answers "which sets" without a read).

    The EMPTY needle keeps the aggregate and one statement: "the most-used
    tags" matches every row, so there is no bucket to seek and a correlated
    count would probe the whole catalog.
    """
    from sqlalchemy.orm import aliased

    from media_compost import prefs
    from media_compost.db import TagMetaTag
    from media_compost.ops import tagsets as tagsets_ops

    Target = aliased(Tag)
    lname = Tag.lname
    target = func.coalesce(Tag.alias_of_id, Tag.id)
    needle = q.strip().lower()
    set_ids = lib.db.cached(s, "tagset-enabled",
                            lambda: tagsets_ops.enabled_ids(s))
    # THE CATEGORIES THE SETS KEEP TO THEMSELVES — hidden ones and everything
    # under them. Cached on the revision beside the enabled ids: it is a
    # closure over a few hundred rows and this runs per keystroke.
    skip_cats = lib.db.cached(
        s, "tagset-hidden-cats",
        lambda: tagsets_ops.hidden_category_ids(s, set_ids)) if set_ids else set()
    # …AND THE SCOPES WHOSE ALIASES ARE SWITCHED OFF, cached the same way and
    # for the same reason: a three-state walk over those same rows.
    alias_off = lib.db.cached(
        s, "tagset-alias-off",
        lambda: tagsets_ops.alias_scopes_off(s, set_ids)) \
        if set_ids else (set(), set())
    # WHAT THE AUTOCOMPLETE DOES NOT OFFER: the tags somebody hid, and every
    # tag in a hidden NAMESPACE. Neither is a deletion — the tags assign,
    # search, count and list exactly as before — but a booru dump puts a
    # hundred thousand names in front of every field while most of a
    # library's work happens in a few hundred of them.
    #
    # The namespace half is a LIKE on the prefix rather than a computed
    # column: a namespace has no row to join to (`tagname.py`), and the few
    # prefixes a library hides are cheap ORed clauses. Cached with the rest,
    # since this runs per keystroke.
    hidden_ns = lib.db.cached(s, "hidden-namespaces",
                              lambda: prefs.read_hidden_namespaces(s))
    visible = [Tag.hidden.is_(False)]
    for ns in hidden_ns:
        visible.append(Tag.lname.not_like(f"{ns}:%"))
    if not needle:
        counts = (
            select(ItemTag.tag_id, func.count().label("cnt"))
            .where(ItemTag.negative.is_(False))
            .group_by(ItemTag.tag_id)
            .subquery()
        )
        elsewhere = (
            select(TagMetaTag.tag_id, func.max(TagMetaTag.count).label("mx"))
            .group_by(TagMetaTag.tag_id)
            .subquery()
        )
        positive = func.coalesce(counts.c.cnt, 0)
        highest = func.coalesce(elsewhere.c.mx, 0)
        rows = s.execute(
            select(Tag.name, positive, Tag.comment, target,
                   highest.label("highest"), Target.name.label("alias_name"),
                   Tag.description)
            .outerjoin(Target, Target.id == Tag.alias_of_id)
            .join(counts, counts.c.tag_id == target, isouter=True)
            .join(elsewhere, elsewhere.c.tag_id == target, isouter=True)
            .where(*visible)
            .order_by(positive.desc(), highest.desc(), Tag.name)
            .limit(limit)
        ).all()
        setrows = (_set_candidates(s, "", limit, set_ids, None, skip_cats, alias_off)
                   if set_ids else [])
        return _merged_rows(s, rows, setrows, "", limit)

    # LABELLED, and ordered BY THE LABEL. A scalar subquery spelled out in
    # both the select list and the ORDER BY is rendered twice and SQLite
    # evaluates it twice — the count for every matched tag, done again for
    # nothing. Measured on the 200,000-tag catalog: 60 ms a keystroke against
    # 33 for the same rows.
    positive = (
        select(func.count())
        .select_from(ItemTag)
        .where(ItemTag.tag_id == target, ItemTag.negative.is_(False))
        .scalar_subquery().label("positive")
    )
    highest = func.coalesce(
        select(func.max(TagMetaTag.count))
        .where(TagMetaTag.tag_id == target)
        .scalar_subquery(), 0).label("highest")
    picked = (select(Tag.name, positive, Tag.comment, target,
                     highest, Target.name.label("alias_name"), Tag.description)
              .outerjoin(Target, Target.id == Tag.alias_of_id)
              .where(*visible)
              .order_by((lname == needle).desc(),
                        positive.desc(), highest.desc(), Tag.name))
    rows = []
    bounds = _prefix_bounds(needle)
    if bounds is not None:
        rows = s.execute(
            picked.where(lname >= bounds[0], lname < bounds[1]).limit(limit)
        ).all()
    if len(rows) < limit:
        # Everything the prefix bucket could not supply, in its own order.
        # `instr > 1` is the complement of that range — a match at position 1
        # IS a prefix — so nothing is counted twice and nothing is missed,
        # including when the bounds could not be computed at all (`> 0`).
        at = func.instr(lname, needle)
        rows += s.execute(
            picked.where(at > (0 if bounds is None else 1))
            .order_by(None)
            .order_by(at, positive.desc(), highest.desc(), Tag.name)
            .limit(limit - len(rows))
        ).all()
    setrows = (_set_candidates(s, needle, limit, set_ids, bounds, skip_cats,
                               alias_off)
               if set_ids else [])
    return _merged_rows(s, rows, setrows, needle, limit)


def _set_candidates(s: Session, needle: str, limit: int, set_ids: list[int],
                    bounds, skip_cats: set[int] = frozenset(),
                    alias_off: tuple[set[int], set[int]] = (frozenset(),
                                                            frozenset())
                    ) -> list[tuple]:
    """The enabled sets' names the LIBRARY lacks, matching ``needle``: up to
    ``limit`` entries and up to ``limit`` aliases, each `(lname, name,
    count, alias_of)`, fetched in the same two stages the library rows are.
    A `GROUP BY lname` over the RANGE (a name two sets both know is one row,
    the larger count kept), and a correlated `NOT EXISTS` on
    `lower(tags.name)` — one `ix_tags_lname` seek per candidate — that hands
    every name the library has back to the library's own row.

    ``skip_cats`` is the HIDDEN categories' closure (`ops/tagsets.
    hidden_category_ids`): an entry in one is not offered, and neither is its
    alias. An entry in NO category always is — a NULL never matches a `NOT
    IN`, so the test is spelled as the two cases it is.

    ``alias_off`` is `ops/tagsets.alias_scopes_off` — the sets and the
    categories whose ALIAS SPELLINGS are switched off. It narrows the second
    stage only: the entry's own name is what the set knows the tag as, and
    that is offered whether or not its other spellings are."""
    from sqlalchemy import exists
    from sqlalchemy.orm import aliased

    from media_compost.db import TagSetEntry as E
    from media_compost.ops.tagsets import Alias as A, NOT_ALIAS
    from media_compost.ops import tagsets as tagsets_ops

    out: list[tuple] = []
    #: The lnames an ENTRY answered for. An alias for one of those is not
    #: offered a second time: a name some set knows as a tag IS that tag,
    #: whatever another set calls it, and two rows for one word — one of them
    #: pointing somewhere else — is the list disagreeing with itself.
    as_entry: set[str] = set()

    def stages(base, col, name_expr, canon_expr):
        cnt = func.max(E.count)
        exact = (col == needle).desc() if needle else None
        got: list = []
        if not needle:
            got = s.execute(base.order_by(cnt.is_(None), cnt.desc(), col)
                            .limit(limit)).all()
        else:
            if bounds is not None:
                got = s.execute(
                    base.where(col >= bounds[0], col < bounds[1])
                    .order_by(exact, cnt.is_(None), cnt.desc(), col)
                    .limit(limit)).all()
            if len(got) < limit:
                at = func.instr(col, needle)
                got += s.execute(
                    base.where(at > (0 if bounds is None else 1))
                    .order_by(at, cnt.is_(None), cnt.desc(), col)
                    .limit(limit - len(got))).all()
        return got

    shown = (or_(E.category_id.is_(None), E.category_id.notin_(list(skip_cats)))
             if skip_cats else true())
    # THE LIBRARY'S ROWS AND A SET'S ARE ONE TABLE now, so the probe needs an
    # ALIAS of its own: without one the subquery's only FROM is the outer
    # query's and SQLAlchemy correlates it away entirely.
    L = aliased(Tag)
    in_library = exists(select(L.id).where(L.lname == E.lname).correlate(E))
    entries = (select(E.lname, func.min(E.name), func.max(E.count))
               .where(E.tag_set_id.in_(set_ids), NOT_ALIAS, ~in_library, shown)
               .group_by(E.lname))
    for ln, name, cnt in stages(entries, E.lname, None, None):
        as_entry.add(ln)
        out.append((ln, name, cnt, None))
    if needle:
        alias_in_library = exists(
            select(L.id).where(L.lname == A.lname).correlate(A))
        aliases = (select(A.lname, func.min(A.name), func.max(E.count),
                          func.min(E.name))
                   .join(E, E.id == A.alias_of_id)
                   .where(A.tag_set_id.in_(set_ids), ~alias_in_library, shown,
                          *tagsets_ops.scope_clauses(*alias_off, E))
                   .group_by(A.lname))
        for ln, name, cnt, canon in stages(aliases, A.lname, None, None):
            if ln in as_entry:
                continue
            out.append((ln, name, cnt, canon))
    return out


def _alias_of(cand: dict, hits) -> Optional[str]:
    """WHAT THIS ROW IS AN ALIAS OF, once every set has had its say.

    A LIBRARY row answers for itself: the library's own alias is a fact
    about this library, and no set overrules it. For a set-only row the
    answer is the STRONGEST claim — `name_map` sorts an entry ahead of an
    alias and then by the sets' own order, so the first hit is it: a name
    some set knows as a tag is that tag (`alias_of` None), and one only ever
    aliased takes the target the FIRST set gives it.
    """
    if cand["lib"]:
        return cand["alias_of"]
    for h in hits:
        return h.alias_of
    return cand["alias_of"]


def _merged_rows(s: Session, rows, setrows: list[tuple], needle: str,
                 limit: int) -> list[TagNameRow]:
    """The page: library rows and set-only rows on ONE key — exact, match
    position, used before unused, count, the figure elsewhere (a library
    row's highest meta count, a set row's count), name — cut to ``limit``,
    then decorated. Merging can only push a row DOWN, so each source's own
    top-``limit`` is enough. With no set rows this is a stable re-sort of
    rows the SQL already ordered by the same key, i.e. the identity
    (`tests/ui/test_tag_names.py` holds it there)."""
    from media_compost.ops import tagsets as tagsets_ops

    cands: list[dict] = []
    seen: set[str] = set()
    for name, pos, comment, t, highest, alias_name, description in rows:
        ln = name.lower()
        seen.add(ln)
        cands.append({"name": name, "lname": ln, "positive": int(pos or 0),
                      "comment": comment or "",
                      "description": description or "",
                      "tid": int(t), "elsewhere": int(highest or 0),
                      "alias_of": alias_name, "lib": True})
    for ln, name, cnt, canon in setrows:
        if ln in seen:
            continue
        seen.add(ln)
        cands.append({"name": name, "lname": ln, "positive": 0, "comment": "",
                      "description": "",
                      "tid": None,
                      "elsewhere": cnt if cnt is not None else -1,
                      # Superseded by `_alias_of` below, which reads the
                      # sets' claims in RANK order; the SQL above can only
                      # group, so its canonical is alphabetical.
                      "alias_of": canon, "lib": False})

    # THE TIE-BREAK IS THE BIGGEST FIGURE ANYBODY HAS FOR THE NAME, and a
    # library row can be told one by a tag SET as well as by a meta tag. In a
    # young library most names are unused, so `positive` is 0 for hundreds of
    # candidates at once and the tie-break is what actually orders the list —
    # reading only the meta counts left a name a booru set says is on 4.7M
    # pictures ranked under one nobody has ever used.
    #
    # The sets' claims are therefore looked up for every CANDIDATE rather
    # than for the page: the figure decides who is on the page. Two hundred
    # names at most, one indexed statement, and the page's own lookup below
    # reuses it.
    allhits = tagsets_ops.name_map(s, [c["lname"] for c in cands]) if cands else {}
    for c in cands:
        if c["lib"]:
            best = max((h.count for h in allhits.get(c["lname"], ())
                        if h.count is not None), default=0)
            c["elsewhere"] = max(c["elsewhere"], best)

    def key(c: dict):
        at = c["lname"].find(needle) if needle else 0
        return (c["lname"] != needle if needle else False, at,
                c["positive"] <= 0, -c["positive"], -c["elsewhere"], c["name"])

    cands.sort(key=key)
    page = cands[:limit]
    ids = [c["tid"] for c in page if c["tid"] is not None]
    mcounts = tagcatalog.meta_counts(s, ids)
    mnames = tagcatalog.meta_names(s, ids)
    lnames = [c["lname"] for c in page]
    sethits = {ln: allhits.get(ln, ()) for ln in lnames}
    settexts = tagsets_ops.descriptions_for(s, lnames) if lnames else {}
    out = []
    for c in page:
        tid = c["tid"]
        out.append(TagNameRow(
            name=c["name"], positive=c["positive"], comment=c["comment"],
            description=c.get("description", ""),
            meta_counts=mcounts.get(tid, {}) if tid is not None else {},
            meta_tags=mnames.get(tid, []) if tid is not None else [],
            alias_of=_alias_of(c, sethits.get(c["lname"], ())),
            tag_sets=[{"key": h.key, "name": h.name, "count": h.count}
                      for h in sethits.get(c["lname"], ())],
            descriptions=[_says(d) for d in settexts.get(c["lname"], ())]))
    return out





# ---- the tag catalog --------------------------------------------------------


@router.get("/export")
def export_library(s: Session = Depends(get_session)):
    """The library's own tag set as a format-2 tag-set file.

    Its own route rather than `/api/tag-sets/{id}/export`: the library's set
    row is LAZY, so there need not be an id to export by — and what is
    exported is the `tags` table either way, not that row's (nonexistent)
    entries.
    """
    from media_compost.ops import tagsets as _ts

    doc = _ts.export_library(s)
    return Response(
        content=json.dumps(doc, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="library.json"'})


@router.get("/namespaces")
def tag_namespaces(s: Session = Depends(get_session),
                   lib=Depends(get_library)):
    """The library's NAMESPACES — the sidebar's derived half.

    A namespace is not a thing: no table, no column, no id, just the text
    before a tag name's first colon (`tagname`). So this is one scan of the
    names, grouped in Python.

    ONLY WHERE TWO OR MORE NAMES SHARE IT, the rule the inline parent rows
    have always followed (`tagNamespaceRows.ts`): a lone `costume:tiger`
    gets no group row in the list and no row here either — a heading over
    one thing is a heading that says nothing.

    `hidden` is the SETTING, not a fact on any row: hiding a namespace keeps
    every name made with it out of the autocomplete, including the ones made
    later, which is the point of it being a prefix rule.
    """
    from media_compost import tagname

    counts: dict[str, int] = {}
    for (name,) in s.execute(select(Tag.name).where(Tag.name.like("%:%"))).all():
        ns = tagname.namespace(name)
        if ns:
            counts[ns] = counts.get(ns, 0) + 1
    hidden = {n.lower() for n in lib.db.cached(
        s, "hidden-namespaces", lambda: prefs.read_hidden_namespaces(s))}
    return [{"name": ns, "count": n, "hidden": ns.lower() in hidden}
            for ns, n in sorted(counts.items(), key=lambda kv: kv[0].lower())
            if n >= 2]


@router.get("/value-namespaces")
def value_namespaces(q: str = "", limit: int = Query(default=50, ge=1, le=200),
                     s: Session = Depends(get_session)):
    """The VALUE row's namespace autocomplete: every namespace holding at
    least one value-shaped tag (`height` for `height:172cm`), with how many
    it holds. Its own endpoint, because deriving this from a count-ranked
    `/names` sample fails exactly on a big library — the top forty tags of a
    booru dump are never value tags, so the dropdown read "no matches" while
    the catalog held plenty."""
    from media_compost import tagvalue

    needle = q.strip().lower()
    seen: dict[str, int] = {}
    for (name,) in s.execute(
        select(Tag.name).where(Tag.name.like("%:%"))
    ).all():
        i = name.index(":")
        ns = name[:i]
        if needle and needle not in ns.lower():
            continue
        if tagvalue.parse(name[i + 1:]) is None:
            continue
        seen[ns] = seen.get(ns, 0) + 1
    rows = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"name": ns, "count": n} for ns, n in rows]


@router.post("", response_model=TagRow)
def create_tag(body: TagCreate, ctx: Ctx = Depends(get_ctx)):
    tag, alias_of, implies = tagcatalog.create(
        ctx, body.name or "", comment=body.comment,
        alias_of=body.alias_of, implies=body.implies)
    return TagRow(id=tag.id, name=tag.name, comment=tag.comment,
                  positive=0, negative=0, alias_of=alias_of, implies=implies)


@router.post("/hidden", response_model=list[str])
def set_tags_hidden(body: TagsHiddenIn, ctx: Ctx = Depends(get_ctx)):
    """Keep these tags out of the autocomplete, or put them back.

    Returns the names that MOVED. Not a deletion and not a scope: the tags
    assign, search, count and list exactly as before.
    """
    return tagcatalog.set_hidden(ctx, body.names, body.hidden)


@router.get("/hidden-namespaces", response_model=list[str])
def get_hidden_namespaces(s: Session = Depends(get_session)):
    """The namespaces the autocomplete does not offer."""
    from media_compost import prefs

    return prefs.read_hidden_namespaces(s)


@router.put("/hidden-namespaces", response_model=list[str])
def put_hidden_namespaces(body: HiddenNamespacesIn,
                          ctx: Ctx = Depends(get_ctx)):
    """The WHOLE list, not a delta — a namespace has no row, so the list is
    the state and that is what a revert puts back."""
    return tagcatalog.set_hidden_namespaces(ctx, body.namespaces)


@router.post("/bulk-upsert")
def bulk_upsert_tags(body: BulkTagsIn, ctx: Ctx = Depends(get_ctx)):
    """The CSV import's tag table, one batch per request.

    Create-or-update per row under the dialog's keep rule, ONE transaction
    for the batch — the per-row path was two requests and two commits per
    tag, which over a booru dump was minutes of commit convoy. Events and
    reverts are identical to the single calls' (see `tagcatalog.bulk_upsert`).
    A refused name is reported in its row rather than failing the batch.
    """
    return {"rows": tagcatalog.bulk_upsert(
        ctx, body.rows, existing=body.existing,
        meta_tags=tuple(body.meta_tags), count_meta=body.count_meta,
        count_mode=body.count_mode)}


@router.post("/categories")
def create_library_category(body: LibraryCategoryIn,
                            ctx: Ctx = Depends(get_ctx)):
    """Make a category of the LIBRARY'S OWN set — and the set itself, if this
    is the first one.

    The bootstrap, and only the bootstrap. Every other verb on a category
    (edit, move, delete) goes through `/api/tag-sets/{set_id}/categories/…`
    with the id this hands back, because by then the set exists and a
    category of the library's is an ordinary category. What could not go that
    way is the FIRST one: the set row is lazy — a library that never files a
    tag never grows it — so there is no id to post to yet.

    Returns the set id beside the category, since the caller has just learnt
    both.
    """
    ts = tagsets.ensure_library_set(ctx)
    row = tagsets.create_category(ctx, ts.id, name=body.name,
                                  parent_id=body.parent_id,
                                  icon=body.icon, hidden=body.hidden)
    return {"set_id": ts.id, "id": row.id, "name": row.name,
            "parent_id": row.parent_id, "icon": row.icon or "",
            "hidden": bool(row.hidden), "position": int(row.position or 0)}


@router.post("/category", response_model=list[int])
def set_tag_category(body: TagCategoryIn, ctx: Ctx = Depends(get_ctx)):
    """File these names under a category of their own tag set.

    Declared BEFORE `/{tag_id}` would swallow it — "category" is not a tag
    id, but the router matches in order and a 422 is a worse answer than the
    route simply working.

    Returns the ids that MOVED; filing something where it already sits is not
    an event.
    """
    return tagcatalog.set_category(ctx, body.tag_ids, body.category_id,
                                   body.set_id)


@router.patch("/{tag_id}")
def update_tag(tag_id: int, body: TagUpdate, ctx: Ctx = Depends(get_ctx)):
    tagcatalog.update(ctx, tag_id, name=body.name, comment=body.comment,
                      description=body.description, alias_of=body.alias_of)
    return {"ok": True}


# ---- implications -----------------------------------------------------------
#
# "Assigning A also assigns B." Replaces the old single parent: a tag entails
# a SET of others, declared one at a time, and the effective-tag resolver
# closes them transitively (`resolve.tag_implications`).


@router.post("/{tag_id}/implies", response_model=list[str])
def add_tag_implication(tag_id: int, body: TagImplies,
                        ctx: Ctx = Depends(get_ctx)):
    """``tag_id`` also entails ``body.name``. Returns its implications."""
    return tagcatalog.add_implication(ctx, tag_id, body.name)


@router.delete("/{tag_id}/implies/{name}", response_model=list[str])
def remove_tag_implication(tag_id: int, name: str,
                           ctx: Ctx = Depends(get_ctx)):
    """Stop ``tag_id`` entailing the tag named ``name``."""
    return tagcatalog.remove_implication(ctx, tag_id, name)


# ---- meta tags on a tag -----------------------------------------------------
#
# The one meta-tag namespace, on the library's own tag set. Named
# `meta-tags` here rather than `link-tags`: those routes are the NAMESPACE's
# (its catalog, its comments, its renames) and keep their historical path,
# while these put one of its names on one tag.


@router.post("/{tag_id}/meta-tags", response_model=list[str])
def add_tag_meta_tag(tag_id: int, body: TagMetaTagBody,
                     ctx: Ctx = Depends(get_ctx)):
    """Put a meta tag on a tag (idempotent). Returns its meta tags."""
    return tagcatalog.add_meta_tag(ctx, tag_id, body.name, body.count)


@router.delete("/{tag_id}/meta-tags/{name}", response_model=list[str])
def remove_tag_meta_tag(tag_id: int, name: str, ctx: Ctx = Depends(get_ctx)):
    """Take a meta tag off a tag. Returns its remaining meta tags."""
    return tagcatalog.remove_meta_tag(ctx, tag_id, name)


@router.post("/{tag_id}/merge")
def merge_tag(tag_id: int, body: TagMerge, ctx: Ctx = Depends(get_ctx)):
    """Fold this tag into another one and delete it."""
    events = tagcatalog.merge(ctx, tag_id, body.into,
                              keep_alias=body.keep_alias)
    return {"ok": True, "event_ids": [e.id for e in events]}


@router.delete("/{tag_id}")
def delete_tag(tag_id: int, ctx: Ctx = Depends(get_ctx)):
    # The ids let the caller offer an Undo that reverts exactly this deletion.
    events = tagcatalog.delete_tag(ctx, tag_id)
    return {"ok": True, "event_ids": [e.id for e in events]}


@router.post("/bulk-delete")
def bulk_delete_tags(body: BulkDeleteTagsIn, ctx: Ctx = Depends(get_ctx)):
    """Delete many tags in one transaction — the Tags list's selection.

    One request per tag was a 32k-row selection's Delete "doing nothing":
    each round trip carried two library-wide reads, so the loop ran for the
    better part of an hour with no feedback. The events written are the
    single delete's exactly, so the Undo toast reverts the lot.
    """
    events = tagcatalog.bulk_delete(ctx, body.tag_ids)
    return {"ok": True, "event_ids": [e.id for e in events]}


# ---- assignments ------------------------------------------------------------


@router.post("/assign/item/{item_id}")
def assign_item_tag(item_id: int, body: AssignTag,
                    ctx: Ctx = Depends(get_ctx)):
    """Assign one tag. The reply carries the ANSWER'S event fan — the
    `add_tag` id plus whatever resolving a pending suggestion wrote — so a
    session overlay's undo can revert exactly this answer (`event_id` is the
    primary, kept for callers that only want one). Additive; existing
    callers read `ok` alone."""
    from media_compost.db import Event

    s = ctx.session
    mark = s.execute(select(func.max(Event.id))).scalar() or 0
    row = tagassign.assign_item_tag(ctx, item_id, body.tag,
                                    negative=body.negative)
    s.flush()
    fan = s.execute(
        select(Event.id).where(Event.id > mark,
                               Event.entity_type == "item",
                               Event.entity_id == item_id)
        .order_by(Event.id)
    ).scalars().all()
    return {"ok": True,
            "event_id": getattr(row, "event_id", None),
            "event_ids": [int(i) for i in fan]}


@router.delete("/assign/item/{item_id}/{name}")
def unassign_item_tag(item_id: int, name: str, ctx: Ctx = Depends(get_ctx)):
    """Take one tag off. The reply carries the removal's event fan, the
    assign route's rule — a session correcting an existing tag reverts
    the correction as one step. Additive; existing callers read `ok`."""
    from media_compost.db import Event

    s = ctx.session
    mark = s.execute(select(func.max(Event.id))).scalar() or 0
    tagassign.unassign_item_tag(ctx, item_id, name)
    s.flush()
    fan = s.execute(
        select(Event.id).where(Event.id > mark,
                               Event.entity_type == "item",
                               Event.entity_id == item_id)
        .order_by(Event.id)
    ).scalars().all()
    return {"ok": True, "event_ids": [int(i) for i in fan]}


@router.post("/assign/item/{item_id}/box")
def add_item_tag_box(item_id: int, body: AssignTagBox,
                     ctx: Ctx = Depends(get_ctx)):
    """Add a bounding-box / time-range annotation for a tag on an item."""
    b = body.box
    box = tagassign.add_box(
        ctx, item_id, body.tag, x=b.x, y=b.y, w=b.w, h=b.h,
        time_start=b.time_start, time_end=b.time_end, track_id=b.track_id,
        negative=b.negative, file_id=body.file_id, group_id=body.group_id,
        points=b.points)
    return {"ok": True, "id": box.id}


@router.patch("/box/{box_id}")
def update_tag_box(box_id: int, body: UpdateTagBox,
                   ctx: Ctx = Depends(get_ctx)):
    """Update a box's geometry and/or its tag, keeping the same box id so the
    annotation editor's undo/redo can track it."""
    tagassign.update_box(
        ctx, box_id, x=body.x, y=body.y, w=body.w, h=body.h,
        file_id=body.file_id, tag=body.tag, time_start=body.time_start,
        time_end=body.time_end, track_id=body.track_id, negative=body.negative,
        clear_time=body.clear_time, clear_track=body.clear_track,
        points=body.points, clear_points=body.clear_points)
    return {"ok": True}


@router.post("/placement/{placement_id}/sign")
def set_placement_sign(placement_id: int, body: PlacementSign,
                       ctx: Ctx = Depends(get_ctx)):
    """Flip one tag instance's sign; the assignment re-derives."""
    tagassign.set_placement_sign(ctx, placement_id, body.negative)
    return {"ok": True}


@router.delete("/box/{box_id}")
def delete_tag_box(box_id: int, ctx: Ctx = Depends(get_ctx)):
    tagassign.delete_box(ctx, box_id)
    return {"ok": True}


# ---- per-item tag groups & instances ----------------------------------------


@router.post("/item/{item_id}/groups", response_model=TagGroupOut)
def create_tag_group(item_id: int, body: TagGroupCreate,
                     ctx: Ctx = Depends(get_ctx)):
    grp = tagassign.create_group(ctx, item_id, body.name)
    return TagGroupOut(id=grp.id, name=grp.name)


@router.patch("/groups/{group_id}")
def rename_tag_group(group_id: int, body: TagGroupUpdate,
                     ctx: Ctx = Depends(get_ctx)):
    tagassign.rename_group(ctx, group_id, body.name)
    return {"ok": True}


@router.delete("/groups/{group_id}")
def delete_tag_group(group_id: int, ctx: Ctx = Depends(get_ctx)):
    tagassign.delete_group(ctx, group_id)
    return {"ok": True}


# ---- meta tags on a tag group -----------------------------------------------
#
# A tag group's meta tags come from the SAME namespace as a link's and a
# caption's (``LinkTag`` names) — labels about the annotation rather than about
# the image, so they never leak into the item's tags, search or training
# prompts. These two endpoints mirror the caption ones exactly.


@router.post("/groups/{group_id}/tags", response_model=list[str])
def add_tag_group_tag(group_id: int, body: TagGroupTagBody,
                      ctx: Ctx = Depends(get_ctx)):
    """Add a meta tag to a tag group (idempotent). Returns the group's tags."""
    return tagassign.add_group_meta_tag(ctx, group_id, body.name)


@router.delete("/groups/{group_id}/tags/{name}", response_model=list[str])
def remove_tag_group_tag(group_id: int, name: str,
                         ctx: Ctx = Depends(get_ctx)):
    """Remove a meta tag from a tag group."""
    return tagassign.remove_group_meta_tag(ctx, group_id, name)


# ---- a tag group is ABOUT a subject -----------------------------------------
#
# A picture with two people wants two groups of tags — hers and his — and naming
# the groups by hand leaves the connection in a string. Binding the grouping to
# the identity is purely organizational, exactly like the meta tags above: the
# grouped tags stay the ITEM's tags, and search never learns "her hair is
# blonde".


@router.post("/groups/{group_id}/subjects", response_model=list[int])
def add_tag_group_subject(group_id: int, body: TagGroupSubjectBody,
                          ctx: Ctx = Depends(get_ctx)):
    """Say the group is about this subject (idempotent)."""
    return tagassign.add_group_subject(ctx, group_id, body.subject_id)


@router.delete("/groups/{group_id}/subjects/{subject_id}",
               response_model=list[int])
def remove_tag_group_subject(group_id: int, subject_id: int,
                             ctx: Ctx = Depends(get_ctx)):
    return tagassign.remove_group_subject(ctx, group_id, subject_id)


@router.delete("/placements/{placement_id}")
def delete_placement(placement_id: int, ctx: Ctx = Depends(get_ctx)):
    """Remove a tag instance (a placement + its boxes) from its group."""
    tagassign.delete_placement(ctx, placement_id)
    return {"ok": True}


@router.post("/item/{item_id}/group-tag")
def add_tag_to_group(item_id: int, body: AddTagToGroup,
                     ctx: Ctx = Depends(get_ctx)):
    """Add a tag as an instance in a specific group (None = ungrouped default)."""
    tagassign.place_tag(ctx, item_id, body.tag, group_id=body.group_id,
                        negative=body.negative)
    return {"ok": True}


@router.post("/item/{item_id}/move-instance")
def move_tag_instance(item_id: int, body: MoveTagInstance,
                      ctx: Ctx = Depends(get_ctx)):
    """Move a tag instance between the item's groups (None = ungrouped)."""
    tagassign.move_instance(ctx, item_id, body.name,
                            from_group_id=body.from_group_id,
                            to_group_id=body.to_group_id)
    return {"ok": True}


# ---- library-group tags -----------------------------------------------------


@router.post("/assign/group/{group_id}")
def assign_group_tag(group_id: int, body: AssignTag,
                     ctx: Ctx = Depends(get_ctx)):
    tagassign.assign_group_tag(ctx, group_id, body.tag, negative=body.negative)
    return {"ok": True}


@router.delete("/assign/group/{group_id}/{name}")
def unassign_group_tag(group_id: int, name: str, ctx: Ctx = Depends(get_ctx)):
    tagassign.unassign_group_tag(ctx, group_id, name)
    return {"ok": True}


@router.post("/quick-assign")
def quick_assign(body: QuickAssign, ctx: Ctx = Depends(get_ctx)):
    """Stamp (or remove) the quick-assign tag set across a selection —
    tags, and the set's GROUP memberships beside them, one request so a
    stamp is one gesture however much the set carries."""
    count = tagassign.stamp(ctx, body.item_ids, body.positive, body.negative,
                            remove=body.remove)
    if body.assign_groups:
        groups.bulk_membership(
            ctx, body.item_ids,
            add=[] if body.remove else body.assign_groups,
            remove=body.assign_groups if body.remove else [])
    return {"ok": True, "count": count}


@router.post("/quick-assign/view")
def quick_assign_view(body: QuickAssignView, ctx: Ctx = Depends(get_ctx),
                      s: Session = Depends(get_session),
                      lib: Library = Depends(get_library)):
    """Stamp (or remove) the quick-assign tag set across a whole VIEW.

    The browser sends the scope it is showing rather than the ids in it —
    see :class:`QuickAssignView` for why — and this resolves it through the
    very same `search_filtered` the grid pages through, so "everything here"
    means exactly what the grid is showing and cannot drift from it.

    **Written in COMMITTED CHUNKS.** `stamp` is one bulk pass and stays so;
    what is chunked is the transaction around it. A stamp over the whole
    library writes one event per (item, tag) — that is the contract, and it
    is also why a single transaction is the wrong shape at that size.
    """
    count = 0
    for chunk in viewscope.chunks(viewscope.view_ids(s, lib, body)):
        count += tagassign.stamp(ctx, chunk, body.positive, body.negative,
                                 remove=body.remove)
        if body.assign_groups:
            # The whole-view stamp only ever ASSIGNS (a match is unknowable
            # over a view), so its groups only ever add.
            groups.bulk_membership(ctx, chunk, add=body.assign_groups,
                                   remove=[])
        s.commit()
    return {"ok": True, "count": count}
