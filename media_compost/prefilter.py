"""Compile the search condition tree into SQL — a prefilter, not a second
evaluator.

:func:`media_compost.query.evaluate` stays the single definition of what a
condition means. What this module adds is a WHERE clause derived from the same
tree, with a per-node contract:

* the clause is **always a superset** of the node's true matches, and
* when a node's compiler marks it ``exact``, the clause IS the node's
  semantics (as items.py evaluates it, sequence-container inheritance
  included) and ``evaluate()`` need not look at it again.

:func:`compile_query` therefore returns a WHERE clause plus a RESIDUE tree —
the part of the query that still needs the Python evaluator, run only over
the SQL-narrowed candidates. A fully exact tree has no residue at all, which
is what turns a ``tag:x`` search over a huge library into one indexed SQL
statement. Callers with their own evaluation loop (scripting, training) may
use the clause as pure narrowing and still evaluate the FULL tree: a
superset can never change their answer.

Catalog reasoning happens in Python at compile time (tags, implications,
group grants, occasions, locations are all small tables); only the per-item
tables are probed via correlated EXISTS. Every compiled id set is bounded by
``_MAX_IDS`` — a pathological set falls back to the residue path instead of
building a statement SQLite refuses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Iterable

import sqlalchemy as sa
from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.orm import Session, aliased

from . import grouppath
from . import query as q
from . import tagname
from .db import (
    Caption,
    chunked,
    CaptionTag,
    Face,
    File,
    Group,
    GroupParent,
    GroupTag,
    Item,
    ItemGroup,
    ItemLocation,
    ItemMetaPin,
    ItemMetadata,
    ItemSubject,
    ItemTag,
    Location,
    Occasion,
    Relationship,
    RelationshipTag,
    Sequence,
    SequenceItem,
    Subject,
    Tag,
    TagImplication,
    TAKEN_NONE,
    TextRegion,
    TrashedItem,
)
from .metadata_catalog import INTRINSIC, INTRINSIC_NAMES

# A compiled id set past this size falls back to residue evaluation rather
# than building an IN list SQLite may refuse (bind-parameter limit).
_MAX_IDS = 5000


@dataclass
class Compiled:
    """One node's compilation: a superset clause (None = no restriction),
    whether it is exactly the node's semantics, and what ``evaluate()`` must
    still check (None when exact)."""

    clause: Optional[sa.ColumnElement]
    exact: bool
    residue: Optional[q.Node]


def _false() -> sa.ColumnElement:
    return sa.false()


class CompilePrep:
    """Catalog snapshots for one compilation, loaded lazily and memoized.

    ``containers`` mirrors items.py's sequence-container tag inheritance in
    the compiled clauses. Callers whose OWN evaluation has no container fold
    compile with it OFF: for them a negated tag clause built over the
    container-inclusive positive would wrongly exclude a container their
    evaluator accepts. Today that is the per-tag counts behind the
    subjects/places/events rows (``count_items_with_tag(containers=False)``);
    the scripting/training path used to be such a caller, but it funnels
    through ``ops/search.py`` now and takes the default.

    ``file_join`` says the consuming statement joins ``File`` on the active
    file (``base_select`` does). Without it, file-backed intrinsic conditions
    must NOT compile — a bare ``File`` reference in the clause becomes a
    cartesian product — so they fall to the caller's own evaluation."""

    def __init__(self, s: Session, *, containers: bool = True,
                 file_join: bool = True, similar: Optional[dict] = None,
                 value_tags: Optional[dict] = None):
        self.s = s
        self.containers = containers
        self.file_join = file_join
        # Likeness conditions already resolved to id sets by `searchctx`.
        # Passed IN rather than resolved here: the index they come from lives
        # on `Library`, and a core module reaching into the server's
        # singletons is a mistake this codebase has made once already.
        self.similar: dict = similar or {}
        # VALUE conditions already resolved to matching tag NAMES
        # (`searchctx.load_value_sets`) — passed in for the same reason, and
        # so the compiled clause and the residue evaluator read one answer.
        self.value_tags: dict = value_tags or {}
        # Keys for oversized id sets parked in the temp table (`id_source`),
        # one compile at a time so two sets of one query cannot share one.
        self._id_sets = 0
        self._eff_direct: bool | None = None
        #: A caller's key -> whether its rows fit under a cap; see
        #: `rows_under`, which every shape decision here goes through.
        self._under_cap: dict[tuple, bool] = {}
        self._has_containers: bool | None = None
        self._impl_edges: list[tuple[int, int]] | None = None
        self._grants: tuple[dict[int, set[int]], dict[int, set[int]]] | None = None
        self._group_names: list[tuple[int, str]] | None = None
        self._group_parent: dict[int, int] | None = None
        self._group_anc: dict[int, set[int]] | None = None
        self._occasions: list[tuple[int, str, Optional[int], Optional[int]]] | None = None
        self._places: list[tuple[int, dict[str, str], dict[str, str]]] | None = None
        self._tag_meta: dict[int, set[str]] | None = None
        # A RANKING OWNED A NAMESPACE HERE UNTIL RUNG v31 (`ranking_prefixes`
        # / `ranking_tag_ids`): its score tags never folded onto a sequence
        # container, since a chapter was never in anybody's rating pool. A
        # ranking mints nothing now — what a rating axis leaves on a picture
        # is an ordinary tag somebody's rules wrote — so every name folds by
        # the one rule again, and both the compiler's split and the counts'
        # exception went with it.

    def tag_ids(self, lowered: str) -> set[int]:
        """Ids of tags whose stored name equals the lowercased needle —
        binary equality, exactly the evaluator's ``name.lower() in pool``
        against stored names."""
        return set(self.s.execute(
            select(Tag.id).where(Tag.name == lowered)
        ).scalars().all())

    def tags_with_meta(self, required: set[str],
                       excluded: set[str]) -> set[int]:
        """Ids of the tags the TAG SET marks this way — carrying every
        required meta tag and none of the excluded.

        Per TAG, which is what makes the compiled clause exact: the evaluator
        asks the same question of each of the item's tags one at a time
        (`query._any_tag_with_meta`), so resolving the set here and testing
        membership is the same answer by a cheaper route.

        EVERY TAG IS IN THE MAP, marked or not — the trap this walked into.
        Built from the `tag_meta_tags` rows alone it held only the tags
        somebody had marked, and an all-EXCLUSIONS condition (`TAG:!draft`,
        which the evaluator reads as "a tag not marked draft" and every
        unmarked tag satisfies) then matched none of them. `test_search_
        equivalence`'s oracle is what said so."""
        if self._tag_meta is None:
            from .db import TagMetaTag

            per: dict[int, set[str]] = {
                tid: set() for tid in
                self.s.execute(select(Tag.id)).scalars().all()}
            for tid, name in self.s.execute(
                select(TagMetaTag.tag_id, TagMetaTag.name)
            ).all():
                per.setdefault(tid, set()).add((name or "").lower())
            self._tag_meta = per
        return {tid for tid, metas in self._tag_meta.items()
                if required <= metas and not (excluded & metas)}

    def big_ids(self, ids):
        """An oversized id set as a SELECT — see `id_source`.

        USABLE AT THE TOP LEVEL ONLY (`Item.id.in_(...)`, which is what
        `_compile_similar` does). Inside a correlated EXISTS it is a
        REGRESSION: measured on a 1.5M-item library, a place search whose
        set is over the guard went from 32.7 s on the residue to over 60 s
        this way, because SQLite re-evaluates an `IN (subquery)` per outer
        row of the EXISTS where it materializes a top-level one once.
        """
        self._id_sets += 1
        return id_source(self.s, f"ids{self._id_sets}", ids)

    @property
    def effective_is_direct(self) -> bool:
        """Can an item's EFFECTIVE tags differ from the ones it assigns?

        Three things make them differ and this library may have none of
        them: an implication, a tag a group grants, and a sequence whose
        container folds its members' tags. All three are catalog-sized
        questions — `EXISTS`, not a count — so asking is microseconds, and a
        plain photo library answers no to all three.
        """
        if self._eff_direct is None:
            if self.s is None:
                # A caller compiling without a session (the shape tests) can
                # be told nothing about this library, so assume the general
                # case — which is the one that does not compile.
                return False
            gpos, gneg = self.group_grants
            self._eff_direct = (
                not self.implication_edges
                and not any(gpos.values()) and not any(gneg.values())
                and self.s.execute(
                    select(SequenceItem.id).limit(1)).first() is None
            )
        return self._eff_direct

    @property
    def implication_edges(self) -> list[tuple[int, int]]:
        if self._impl_edges is None:
            self._impl_edges = [
                (a, b) for a, b in self.s.execute(
                    select(TagImplication.tag_id, TagImplication.implies_id)
                ).all()
            ]
        return self._impl_edges

    @property
    def has_containers(self) -> bool:
        """Does this library hold a SEQUENCE CONTAINER at all?

        One indexed EXISTS, memoized per compilation — what `_with_container`
        asks before it adds the fold's OR to a clause (the numbers are
        there). A library of loose pictures answers no, and the compiled
        clause is then exactly what it says: the items carrying the tag.
        """
        if self._has_containers is None:
            self._has_containers = bool(self.s.execute(
                select(sa.literal(1)).select_from(Sequence).limit(1)
            ).first())
        return self._has_containers

    def rows_under(self, key, rows: sa.Select, cap: int) -> bool:
        """Does ``rows`` hold AT MOST ``cap`` rows — the question every
        "which way round should this clause be" decision in this file asks.

        COUNTED UNDER A LIMIT, NEVER COUNTED WHOLE. The answer wanted is a
        yes or a no about one threshold, and counting whole makes the
        cheapest case (a name nothing carries) cost the same as the dearest
        (a tag on most of the library). Under the limit the walk stops at
        ``cap + 1`` rows: a tag with nothing on it answers in under a tenth
        of a millisecond however big the library is, and only a caller that
        goes on to FAIL this pays the full walk — about 12 ms at a cap of
        half a million, against 5 ms to count 300,000 rows exactly.

        ``key`` is the caller's own identity for the question (the select is
        not hashable), memoized for this compilation: a tag condition asks
        about the same tag on both sides and the container fold asks again
        per member.
        """
        have = self._under_cap.get(key)
        if have is None:
            have = int(self.s.execute(
                select(func.count()).select_from(rows.limit(cap + 1).subquery())
            ).scalar_one() or 0) <= cap
            self._under_cap[key] = have
        return have

    def tag_is_small(self, tag_ids, negative: bool, cap: int) -> bool:
        """Do these tags have at most ``cap`` assignments on that side — the
        question `_direct_tag` picks its shape by. One walk of
        `ix_item_tags_tag_neg_item`, which is covering, so no row is
        fetched."""
        ids = tuple(sorted(int(x) for x in tag_ids))
        return self.rows_under(
            ("tag", ids, bool(negative), int(cap)),
            select(sa.literal(1)).select_from(ItemTag).where(
                ItemTag.tag_id.in_(list(ids)),
                ItemTag.negative.is_(bool(negative))),
            cap)

    def meta_name_pinned(self, name: str) -> bool:
        """Has ANYTHING been pinned under this metadata name? One seek into
        `ix_item_meta_pins_name`, and a no lets `_compile_meta` drop the
        pins half of its OR — which is what lets SQLite drive the query off
        the other half (`_with_container` learnt the same thing about the
        sequence fold). A pin is a deliberate act on one picture, so in most
        libraries the answer is no for every name."""
        return not self.rows_under(
            ("pin", name),
            select(sa.literal(1)).select_from(ItemMetaPin).where(
                ItemMetaPin.name == name),
            0)

    def meta_name_is_small(self, name: str, cap: int) -> bool:
        """Do at most ``cap`` items say anything under this metadata name —
        what `_compile_meta` picks its shape by, and deliberately NOT "how
        many match the value": the name is one seek into
        `ix_item_metadata_name`, the value is the scan being decided about.
        The name is the sound bound, since a row matching the value is a row
        carrying the name."""
        return self.rows_under(
            ("meta", name, int(cap)),
            select(sa.literal(1)).select_from(ItemMetadata).where(
                ItemMetadata.name == name),
            cap)

    def impliers_of(self, tag_ids: set[int]) -> set[int]:
        """Tags whose transitive closure contains any of ``tag_ids`` (the
        REVERSE walk), excluding ``tag_ids`` themselves."""
        rev: dict[int, set[int]] = {}
        for a, b in self.implication_edges:
            rev.setdefault(b, set()).add(a)
        seen = set(tag_ids)
        queue = list(tag_ids)
        while queue:
            cur = queue.pop()
            for t in rev.get(cur, ()):
                if t not in seen:
                    seen.add(t)
                    queue.append(t)
        return seen - tag_ids

    @property
    def group_ancestors(self) -> dict[int, set[int]]:
        if self._group_anc is None:
            from .resolve import _group_ancestors

            self._group_anc = _group_ancestors(self.s)
        return self._group_anc

    @property
    def group_names(self) -> list[tuple[int, str]]:
        if self._group_names is None:
            self._group_names = [
                (gid, name or "") for gid, name in self.s.execute(
                    select(Group.id, Group.name)
                ).all()
            ]
        return self._group_names

    @property
    def group_parent(self) -> dict[int, int]:
        """Each group's parent id — the other half of what a PATH is read
        from. Loaded once, like the names beside it: a library has dozens of
        groups, and both are read per group condition."""
        if self._group_parent is None:
            self._group_parent = {
                gid: pid for gid, pid in self.s.execute(
                    select(GroupParent.group_id,
                           GroupParent.parent_group_id)).all()
            }
        return self._group_parent

    @property
    def group_grants(self) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
        """Per group, the tag ids it EFFECTIVELY grants (its own group_tags
        plus every ancestor's), split by sign — the ancestor walk done once
        here instead of per item in SQL."""
        if self._grants is None:
            own_pos: dict[int, set[int]] = {}
            own_neg: dict[int, set[int]] = {}
            for gid, tid, neg in self.s.execute(
                select(GroupTag.group_id, GroupTag.tag_id, GroupTag.negative)
            ).all():
                (own_neg if neg else own_pos).setdefault(gid, set()).add(tid)
            anc = self.group_ancestors
            all_gids = (set(own_pos) | set(own_neg) | set(anc)
                        | {g for g, _ in self.group_names})
            eff_pos: dict[int, set[int]] = {}
            eff_neg: dict[int, set[int]] = {}
            for g in all_gids:
                pos: set[int] = set()
                neg: set[int] = set()
                for a in anc.get(g, {g}):
                    pos |= own_pos.get(a, set())
                    neg |= own_neg.get(a, set())
                if pos:
                    eff_pos[g] = pos
                if neg:
                    eff_neg[g] = neg
            self._grants = (eff_pos, eff_neg)
        return self._grants

    def groups_granting(self, tag_ids: set[int],
                        negative: bool) -> set[int]:
        eff_pos, eff_neg = self.group_grants
        grants = eff_neg if negative else eff_pos
        return {g for g, tids in grants.items() if tids & tag_ids}

    @property
    def occasions(self) -> list[tuple[int, str, Optional[int], Optional[int]]]:
        """(tag_id, lowercased tag name, start, end) per occasion with an
        identity tag."""
        if self._occasions is None:
            self._occasions = [
                (tid, (name or "").lower(), start, end)
                for tid, name, start, end in self.s.execute(
                    select(Occasion.tag_id, Tag.name,
                           Occasion.start_date, Occasion.end_date)
                    .join(Tag, Tag.id == Occasion.tag_id)
                ).all()
            ]
        return self._occasions

    @property
    def places(self) -> list[tuple[int, str]]:
        """(location_id, name) per location — what
        ``searchctx.load_place_sets`` hands the evaluator, in the same shape,
        so the compiled clause and the evaluator read the same text.

        It used to be two maps per location, one for each way a place is
        reached, because the identity tag rode along in one of them. The tag
        is not searched here any more (see :class:`query.PlaceCond`), so how a
        place was reached no longer changes what it says."""
        if self._places is None:
            self._places = [
                (lid, line or "")
                for lid, line in self.s.execute(
                    select(Location.id, Location.name)).all()
            ]
        return self._places


# ---- per-item probe builders ------------------------------------------------
# Every builder takes the ITEM-ID EXPRESSION it correlates on — the outer
# Item.id normally, a sequence member's item id inside the container branch.

IdExpr = sa.ColumnElement


#: How many rows a thing may have before the clause about it goes back to
#: the per-item EXISTS — the one number this file's hottest decision turns
#: on. It is the tag's assignments in `_direct_tag`, the rows under one
#: metadata name in `_compile_meta`, the captions or the links in
#: `_tagged_exists`: one row per item per thing in every case, which is why
#: one number serves them all.
#:
#: MEASURED with a TAG, on 1.5M pictures, none of them in a sequence (M4
#: Max), and the default sort; the other three carry their own numbers
#: where they are decided. Three things one search pays for: page 1 WITH the
#: view's own total, the grid's group runs, and page 20 once that total is
#: memoized (the scroll). Before is this file at the previous release, after
#: is the id list plus the no-books rule in `_with_container`:
#:
#:      tag rows   page 1 + total    group runs       page 20
#:                 before   after   before  after   before  after
#:            21    1,085      60      489    1.1      2.5     1.3
#:         3,006      511      16      494     12      241      30
#:        30,020      533      70      541     78       31      13
#:       100,005      580     139      616    159       15      17
#:       300,008      696     289      791    349        9      39
#:       500,000      803     427      979    552        8      61
#:     1,200,000    1,094     710    1,506  1,096        7      18
#:
#: Both shapes walk the sort index; what differs is the per-row TEST — a
#: probe into an ephemeral index of the tag's items against a b-tree lookup
#: in `item_tags`, about 2.5x dearer — plus the LIST's one-off build, which
#: is linear in the tag. So the list wins by more the SPARSER the tag is,
#: and the last row is where it stops winning: a tag on 80% of the library
#: is found by the walk within a few rows, and building a list of 1.2M ids
#: to answer that is work for nothing. THE THRESHOLD IS THE LAST SIZE
#: MEASURED TO WIN, not a guess past it.
#:
#: The count and the group runs want the list at EVERY size (they visit
#: everything either way), the scroll wants it only while the tag is
#: sparse — and they share one compiled clause on purpose: one predicate
#: compiled two ways is two predicates, and the page a person waits on is
#: the FIRST one, which carries the total.
#:
#: Note what does NOT appear here: the fraction of the library. A rule on
#: density would need the library's own item count per compile, and a fixed
#: cap is wrong only where the cap is a large share of the library — a
#: library under a million pictures, where the whole table above is
#: milliseconds.
_ID_LIST_MAX = 500_000


def _direct_tag(prep: "CompilePrep | None", tag_ids, negative: bool,
                iid: IdExpr) -> sa.ColumnElement:
    """``the item directly assigns one of these tags``.

    ``tag_ids`` is a set OR a SELECT of ids — the second is what an
    oversized set becomes (`id_source`), and `IN` takes either.

    AN ID LIST UNLESS THE TAG IS MOST OF THE LIBRARY, in which case the
    correlated EXISTS (`_ID_LIST_MAX` above is where that line is, with
    what it was measured at). The complaint that found this: one tag in a
    library of 1.5M pictures where almost nothing is tagged — the tag's
    twenty-one rows were answered by 1.5M b-tree lookups, one per item in
    the sort order, because a correlated EXISTS is the one shape SQLite
    cannot turn around with no stats to go on. `_in_groups` has said the
    same thing about group membership since the day a group scope cost
    7.9 s; this is that lesson carried to the rest of the file.
    """
    if isinstance(tag_ids, (set, frozenset, list, tuple)):
        if not tag_ids:
            return _false()
        tag_ids = sorted(tag_ids)
        if prep is not None and prep.tag_is_small(tag_ids, negative,
                                                  _ID_LIST_MAX):
            return iid.in_(
                select(ItemTag.item_id).where(
                    ItemTag.tag_id.in_(tag_ids),
                    ItemTag.negative.is_(negative)))
    it = aliased(ItemTag)
    return exists(select(sa.literal(1)).where(
        it.item_id == iid, it.tag_id.in_(tag_ids),
        it.negative.is_(negative),
    ))


def _in_groups(group_ids: set[int], iid: IdExpr) -> sa.ColumnElement:
    """``the item is in one of these groups``.

    AN `IN (subquery)`, NOT AN `EXISTS`, and the difference is the whole
    cost of selecting a group on a large library. As an EXISTS, SQLite
    probes the `(item_id, group_id)` index once PER GROUP ID for every item
    in scope — a group with 73 subgroups over a million items is 73 million
    probes, measured at 7.9 s for the grid's own total. As an IN, the
    membership rows are read ONCE through `ix_item_groups_group_id` and
    matched by rowid: the same answer in 0.26 s, and 0.33 s → 0.012 s for a
    single group.

    The two are exactly equivalent (`item_groups.item_id` is NOT NULL, so
    the `NOT IN` this becomes under a negation has no third truth value to
    trip over) — this is which side SQLite drives from, nothing more.
    """
    if not group_ids:
        return _false()
    return iid.in_(
        select(ItemGroup.item_id).where(
            ItemGroup.group_id.in_(sorted(group_ids))))


def _positive_pre(prep: CompilePrep, tag_ids: set[int],
                  iid: IdExpr) -> sa.ColumnElement:
    """``name(T) ∈ eff.positive`` BEFORE the implication step — mirrors
    ``resolve``: direct, or group-inherited and not group-negated; a direct
    negative overrides either."""
    gp = prep.groups_granting(tag_ids, negative=False)
    gn = prep.groups_granting(tag_ids, negative=True)
    inherited = (and_(_in_groups(gp, iid), not_(_in_groups(gn, iid)))
                 if gp else _false())
    return and_(
        or_(_direct_tag(prep, tag_ids, False, iid), inherited),
        not_(_direct_tag(prep, tag_ids, True, iid)),
    )


def _tag_negative(prep: CompilePrep, tag_ids: set[int],
                  iid: IdExpr) -> sa.ColumnElement:
    """``name(T) ∈ eff.negative``: a direct negative or a group-granted one."""
    gn = prep.groups_granting(tag_ids, negative=True)
    return or_(_direct_tag(prep, tag_ids, True, iid), _in_groups(gn, iid))


def _tag_positive(prep: CompilePrep, name: str,
                  iid: IdExpr) -> Optional[sa.ColumnElement]:
    """``name ∈ ctx.tags`` for one item (WITHOUT container inheritance).
    None = fall back to residue (a pathological implier set)."""
    return _tag_positive_ids(prep, prep.tag_ids(name), iid)


def _tag_positive_ids(prep: CompilePrep, tx: set[int],
                      iid: IdExpr) -> Optional[sa.ColumnElement]:
    """``ONE tag ∈ ctx.tags``, by id rather than by name.

    ``tx`` is a name lookup's answer, so it holds 0 or 1 ids — `Tag.name` is
    unique. It is a SET because every step below takes one, NOT because the
    clause generalizes to several tags: `_positive_pre` applies the negative
    override across the whole set, which for one tag is what "a direct
    negative overrides" means and for several is a different question. Use
    `_any_tag_positive` for that."""
    if not tx:
        return _false()  # an unknown tag matches nothing — like the evaluator
    impliers = prep.impliers_of(tx)
    if len(impliers) > _MAX_IDS:
        return None
    pre = _positive_pre(prep, tx, iid)
    if not impliers:
        return pre
    implied_any = or_(*[
        _positive_pre(prep, {z}, iid) for z in sorted(impliers)
    ])
    return or_(pre, and_(implied_any, not_(_tag_negative(prep, tx, iid))))


#: How many tags a `TAG:<meta>` condition may expand to before it is left to
#: the residue evaluator. The expansion is an OR of one per-tag clause each —
#: it has to be, since the negative override pairs a tag with ITSELF — so the
#: statement grows with the set, and a mark somebody put on half the catalog
#: would be a WHERE clause of thousands of EXISTS. The residue path answers
#: those correctly and no more slowly than such a clause would.
_MAX_META_TAGS = 200


def _any_tag_positive(prep: CompilePrep, tx: set[int],
                      iid: IdExpr) -> Optional[sa.ColumnElement]:
    """``any of these tags ∈ ctx.tags`` — the OR of the per-tag clause.

    NOT one clause over the set, and the difference is a real bug the
    equivalence oracle caught: `_positive_pre` reads "…and the item has none
    of these directly-negatively", which pairs each tag with itself for one
    tag and, for a set, lets a NEGATIVE assignment of one tag veto a POSITIVE
    assignment of another. An item tagged `pet` and `-outdoor` matched
    `TAG:!noflip` in the evaluator and not in SQL.
    """
    if not tx:
        return _false()
    if len(tx) > _MAX_META_TAGS:
        return None
    parts = []
    for t in sorted(tx):
        one = _tag_positive_ids(prep, {t}, iid)
        if one is None:
            return None
        parts.append(one)
    return or_(*parts)


def _with_container(builder: Callable[[IdExpr], Optional[sa.ColumnElement]],
                    veto: Optional[sa.ColumnElement] = None,
                    prep: "CompilePrep | None" = None,
                    ) -> Optional[sa.ColumnElement]:
    """A positive-tag clause for the outer item, plus the sequence-container
    branch: a container matches when any member does (`seq_inherited`) —
    UNLESS `veto` holds for the container, which is the container's own
    DIRECT NEGATIVE on the tag (`_direct_tag(tx, True, Item.id)`). A chapter
    marked `-dog` is a chapter somebody has said is not about dogs, whatever
    one of its pages carries; the evaluator's fold drops the name and the
    item detail already showed it overridden, and the search and the counts
    used to disagree with both."""
    own = builder(Item.id)
    if own is None:
        return None
    # A LIBRARY WITH NO BOOKS IN IT HAS NO FOLD, and paying for one is not
    # free: the branch is an OR, and an OR is what stops SQLite driving the
    # query off either disjunct — it walks the sort index testing both per
    # row instead, and the second one is a correlated join through
    # `sequences` and `sequence_items`. MEASURED on 1.5M pictures, none of
    # them in a sequence: page 1 and its total for a rare tag 1,085 -> 714
    # ms from dropping the branch alone, the group runs for a common one
    # 1,506 -> 1,103 (the id list, `_ID_LIST_MAX`, is the rest of both).
    # The question is one indexed EXISTS over `sequences`, asked once per
    # compilation, and the answer is no for every library that holds loose
    # pictures — which is most of them.
    if prep is not None and not prep.has_containers:
        return own
    sq = aliased(Sequence)
    si = aliased(SequenceItem)
    member = builder(si.item_id)
    if member is None:
        return None
    fold = [Item.kind == "sequence"]
    if veto is not None:
        fold.append(not_(veto))
    fold.append(exists(select(sa.literal(1))
                       .select_from(sq)
                       .join(si, si.sequence_id == sq.id)
                       .where(sq.item_id == Item.id, member)))
    return or_(own, and_(*fold))


def _fold_any(prep: CompilePrep, tx: set[int]) -> Optional[sa.ColumnElement]:
    """`_any_tag_positive` WITH the container fold — per tag, so a container's
    negative on one tag of the set vetoes only that tag's fold (the same
    reason `_any_tag_positive` is an OR of per-tag clauses)."""
    if not tx:
        return _false()
    if len(tx) > _MAX_META_TAGS:
        return None
    parts = []
    for t in sorted(tx):
        one = _with_container(lambda iid, z=t: _tag_positive_ids(prep, {z}, iid),
                              veto=_direct_tag(prep, {t}, True, Item.id),
                              prep=prep)
        if one is None:
            return None
        parts.append(one)
    return or_(*parts)


def _compile_tag(prep: CompilePrep, node: q.TagCond) -> Compiled:
    # WHICH tags the condition is about: the one it names, or every one the
    # tag set marks the asked-for way. Everything below is unchanged by
    # that choice — it has always worked on a set of ids.
    meta = bool(node.meta_tags)
    if meta:
        tx = prep.tags_with_meta(
            {t.name.lower() for t in node.meta_tags if not t.exclude},
            {t.name.lower() for t in node.meta_tags if t.exclude},
        )
    else:
        tx = prep.tag_ids(node.name.lower())
    if node.sign == "neg":
        # ctx.neg has no implication step and no container inheritance — and
        # unlike the positive side it DOES generalize to a set: "any of these
        # is directly negative, or a group grants any of them negatively" is
        # per-tag by construction.
        if len(tx) > _MAX_IDS:
            return Compiled(None, False, node)
        clause = _tag_negative(prep, tx, Item.id) if tx else _false()
        return Compiled(clause if node.have else not_(clause), True, None)
    # One tag by name, or any of the tags the tag set marks.
    if meta:
        clause = (_fold_any(prep, tx) if prep.containers
                  else _any_tag_positive(prep, tx, Item.id))
    else:
        build = lambda iid: _tag_positive_ids(prep, tx, iid)  # noqa: E731
        clause = (_with_container(build, veto=_direct_tag(prep, tx, True, Item.id),
                                  prep=prep)
                  if prep.containers else build(Item.id))
    if clause is None:
        return Compiled(None, False, node)
    return Compiled(clause if node.have else not_(clause), True, None)


def _compile_group(prep: CompilePrep, node: q.GroupCond) -> Compiled:
    # ONE definition of what a condition value names — a plain name, or a
    # PATH picking one of several groups that share it (`grouppath`).
    named = grouppath.matching_ids(
        node.name, dict(prep.group_names), prep.group_parent)
    if node.mode in ("only", "notonly"):
        matching = named  # filed in the group itself
    else:
        # `has` is the group and everything under it — the sidebar's own
        # scope (`scope_clauses`), so `GROUP:c` finds what selecting `c`
        # shows.
        anc = prep.group_ancestors
        matching = {g for g, _ in prep.group_names
                    if anc.get(g, {g}) & named}
    clause = _in_groups(matching, Item.id)
    return Compiled(clause if node.mode in ("has", "only") else not_(clause),
                    True, None)


# ---- meta ------------------------------------------------------------------

_EPS = 1e-9


def _num_pred(expr: sa.ColumnElement, op: str, value,
              tol: float) -> Optional[sa.ColumnElement]:
    """SQL mirror of ``query._num_cmp`` (None = the value cannot be compared,
    which the evaluator answers with False — callers map None to false())."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if tol > 0 and op in ("=", "!="):
        inside = and_(expr >= v - tol, expr < v + tol)
        return inside if op == "=" else not_(inside)
    if op == "=":
        return and_(expr > v - _EPS, expr < v + _EPS)
    if op == "!=":
        return or_(expr <= v - _EPS, expr >= v + _EPS)
    if op == ">":
        return expr > v
    if op == "<":
        return expr < v
    if op == ">=":
        return expr >= v
    if op == "<=":
        return expr <= v
    return sa.false()


def _text_pred(expr: sa.ColumnElement, op: str,
               value: str) -> sa.ColumnElement:
    """SQL mirror of ``query._text_cmp`` over a lowercased expression."""
    needle = str(value).lower()
    low = func.lower(expr)
    if op == "=":
        return low == needle
    if op == "!=":
        return low != needle
    if op == "~":
        # instr(x, '') is 1 in SQLite, matching Python's `'' in x`.
        return func.instr(low, needle) > 0
    if op == "!~":
        return func.instr(low, needle) == 0
    return sa.false()


def _date_pred(expr: sa.ColumnElement, op: str, value) -> sa.ColumnElement:
    """SQL mirror of ``query._date_cmp`` over a YYYYMMDDHHMMSS number."""
    bounds = q._date_bounds(value)
    if bounds is None:
        pred = _num_pred(expr, op, value, 0.0)
        return pred if pred is not None else sa.false()
    low, high = bounds
    a = func.cast(expr, sa.Integer)
    if op == "=":
        return and_(a >= low, a <= high)
    if op == "!=":
        return or_(a < low, a > high)
    if op == ">":
        return a > high
    if op == ">=":
        return a >= low
    if op == "<":
        return a < low
    if op == "<=":
        return a <= high
    return sa.false()


def _sql_datetime_num(col) -> sa.ColumnElement:
    """A DateTime column as the YYYYMMDDHHMMSS number the evaluator uses
    (0 when unset, like ``intrinsic_nums``)."""
    return func.coalesce(
        func.cast(func.strftime("%Y%m%d%H%M%S", col), sa.Integer), 0)


def _scalar_count(model, iid: IdExpr, *extra) -> sa.ColumnElement:
    inner = aliased(model)
    stmt = select(func.count()).where(inner.item_id == iid)
    for cond in extra:
        stmt = stmt.where(cond(inner))
    return stmt.scalar_subquery()


def _intrinsic_num_expr(name: str) -> Optional[sa.ColumnElement]:
    w = func.coalesce(File.width, 0)
    h = func.coalesce(File.height, 0)
    if name == "width":
        return sa.cast(w, sa.Float)
    if name == "height":
        return sa.cast(h, sa.Float)
    if name == "resolution":
        return (sa.cast(w, sa.Float) * h) / 1_000_000.0
    if name == "aspect":
        return sa.case((h > 0, sa.cast(w, sa.Float) / h), else_=0.0)
    if name == "length":
        return func.coalesce(File.duration, 0.0)
    if name == "fps":
        return func.coalesce(File.frame_rate, 0.0)
    if name == "bitrate":
        return func.coalesce(File.bitrate, 0.0) / 1_000_000.0
    return None


def _compile_meta(prep: CompilePrep, node: q.MetaCond) -> Compiled:
    name = node.name
    if name in INTRINSIC_NAMES:
        kind = INTRINSIC.get(name)
        file_backed = name in ("width", "height", "resolution", "aspect",
                               "length", "fps", "bitrate", "format")
        if file_backed and not prep.file_join:
            return Compiled(None, False, node)
        if kind == "text":
            expr = {"type": func.coalesce(Item.kind, ""),
                    "format": func.coalesce(File.format, ""),
                    "id": func.coalesce(Item.uid, "")}[name]
            # The evaluator sees format UPPERCASED and lowercases both sides
            # of the compare, so lower(stored) is the same value.
            return Compiled(_text_pred(expr, node.op, str(node.value)),
                            True, None)
        if kind == "date":
            col = (Item.created_at if name == "import_date"
                   else Item.last_imported_at)
            return Compiled(
                _date_pred(_sql_datetime_num(col), node.op, node.value),
                True, None)
        if name == "tag_count":
            # THE ONE INTRINSIC WHOSE VALUE IS RESOLVED, not stored: it counts
            # a tag an implication brings, a group grants or a sequence
            # member carries, so the direct rows are only half the answer —
            # and refusing to compile drops the WHOLE query to the residue,
            # which is every candidate materialized and evaluated in Python.
            # Measured at 1.5M items: `INFO:tag_count>=3` took 47 s, against
            # 13 ms for a condition that compiles. Two ways out, and both are
            # about the SHAPE of the difference rather than about the count.
            direct = sa.cast(_scalar_count(
                ItemTag, Item.id,
                lambda t: t.negative.is_(False)), sa.Float)
            if prep.effective_is_direct:
                # Nothing in this library can make them differ, so the
                # direct count IS the effective one — exact, in SQL.
                return Compiled(_num_pred(direct, node.op, node.value,
                                          node.tol), True, None)
            # Otherwise effective >= direct always, so an UPPER bound on the
            # effective count is a sound superset for `<=`-shaped operators
            # and there is none for `>=`-shaped ones (an item with one tag
            # can have any number implied). `=` is the pair, so it takes the
            # weaker half. What this buys is the common `tag_count = 0`
            # (Untagged) and every `<`: the residue then re-checks only the
            # candidates rather than the library.
            if node.op not in ("<=", "<", "="):
                return Compiled(None, False, node)
            # `direct <= value + tol`, with the tolerance ADDED rather than
            # passed on: `_num_pred` reads it as the window a `=` means, and
            # what is wanted here is only the loosest upper edge any of the
            # three operators can have. Sound for all three, and the random
            # trees found the version that was not.
            edge = float(node.value) + float(node.tol or 0.0)
            return Compiled(_num_pred(direct, "<=", edge, 0.0), False, node)
        if name in ("caption_count", "instruction_count"):
            # A description and an instruction are rows of one table told apart
            # by `kind`, so each count says which it means.
            want = ("instruction" if name == "instruction_count"
                    else "caption")
            expr = sa.cast(_scalar_count(
                Caption, Item.id,
                lambda c, want=want: sa.and_(c.pending.is_(False),
                                             c.kind == want)), sa.Float)
        elif name == "faces":
            expr = sa.cast(_scalar_count(
                Face, Item.id, lambda f: f.dismissed.is_(False)), sa.Float)
        elif name == "text_blocks":
            # Live TOP-LEVEL regions of the ACTIVE file — blocks, not words,
            # the badge's number and `searchctx.load_text_counts`' (the two
            # must agree, or the SQL and Python paths answer differently).
            expr = sa.cast(_scalar_count(
                TextRegion, Item.id,
                lambda r: sa.and_(r.parent_id.is_(None),
                                  r.dismissed.is_(False),
                                  r.file_id == Item.active_file_id)),
                sa.Float)
        elif name == "sequence_count":
            # DISTINCT sequences, `searchctx.load_sequence_counts`' rule (the
            # two must agree): an item repeated inside one chapter is in one
            # book, and the occurrence rows are the grid's business.
            si2 = aliased(SequenceItem)
            expr = sa.cast(
                select(func.count(func.distinct(si2.sequence_id)))
                .where(si2.item_id == Item.id).scalar_subquery(), sa.Float)
        elif name == "file_count":
            # Every SOURCE file of the item, `searchctx.load_file_counts`'
            # rule (the two must agree): artifacts hang off a file rather
            # than being one, so they are not counted here either.
            expr = sa.cast(_scalar_count(File, Item.id), sa.Float)
        elif name == "unnamed_faces":
            fc = aliased(Face)
            named = exists(select(sa.literal(1))
                           .select_from(ItemSubject)
                           .join(Subject, Subject.id == ItemSubject.subject_id)
                           .where(ItemSubject.face_id == fc.id,
                                  Subject.tag_id.is_not(None)))
            expr = sa.cast(
                select(func.count()).select_from(fc)
                .where(fc.item_id == Item.id, fc.dismissed.is_(False),
                       not_(named)).scalar_subquery(), sa.Float)
        else:
            expr = _intrinsic_num_expr(name)
            if expr is None:
                return Compiled(None, False, node)
        pred = _num_pred(expr, node.op, node.value, node.tol)
        return Compiled(pred if pred is not None else sa.false(), True, None)

    # Indexed metadata, and an item answers with SEVERAL values for one name:
    # what its ACTIVE FILE says (`item_metadata`, already less any mute) plus
    # whatever has been promoted to the item (`item_meta_pins`). So the clause
    # is an EXISTS over each table, OR'd.
    #
    # A negative operator asks its POSITIVE form and inverts the whole answer —
    # "no value is X" rather than "some value is not X", which any second value
    # would satisfy. That also SUBSUMES the absent-row branch this used to
    # carry: with no rows at all, neither EXISTS holds and the negation is
    # true, exactly as before.
    negated = node.op in q._NEG_OPS
    op = q._POSITIVE_OF.get(node.op, node.op) if negated else node.op

    def _one(table) -> sa.sql.ClauseElement:
        m = aliased(table)
        num = func.coalesce(m.num_value, 0.0)
        num_p = _num_pred(num, op, node.value, node.tol)
        value_pred = or_(
            and_(m.mtype == "text",
                 _text_pred(func.coalesce(m.text_value, ""), op,
                            str(node.value))),
            and_(m.mtype == "date", _date_pred(num, op, node.value)),
            and_(m.mtype.not_in(("text", "date")),
                 num_p if num_p is not None else sa.false()),
        )
        # AN ID LIST WHILE THE NAME IS RARE, `_direct_tag`'s rule for the
        # same reason: as a correlated EXISTS this is one index probe per
        # item in the SORT order, however few items say anything under the
        # name. MEASURED at 1.5M pictures, page 1 with its total and a
        # scroll page — 3,000 carrying a `camera_model`: 474 -> 17 ms and
        # 193 -> 30; 500,000 carrying an `iso`: `=` 673 -> 251 ms and
        # 16 -> 89, `>=` 711 -> 405 ms and 7 -> 92. The threshold is
        # `_ID_LIST_MAX` — one row per item per name here too, so it is
        # the same question about the same shape, and the last two rows are
        # what it costs: a name on a THIRD of the library is relisted per
        # page, for a first page worth three of them.
        rows = select(m.item_id).where(m.name == name, value_pred)
        if (table is ItemMetadata
                and prep.meta_name_is_small(name, _ID_LIST_MAX)):
            return Item.id.in_(rows)
        return exists(select(sa.literal(1)).where(
            m.item_id == Item.id, m.name == name, value_pred))

    # AND THE PIN HALF IS DROPPED WHERE NOBODY HAS PINNED THE NAME, because
    # an OR is what stops SQLite driving off the id list above — with the
    # branch still there the rare `camera_model` was 250 ms rather than 17.
    # `_with_container` says the same thing about the sequence fold.
    parts = [_one(ItemMetadata)]
    if prep.meta_name_pinned(name):
        parts.append(_one(ItemMetaPin))
    hit = or_(*parts) if len(parts) > 1 else parts[0]
    return Compiled(not_(hit) if negated else hit, True, None)


# ---- captions / links ------------------------------------------------------


def _tagged_exists(prep: "CompilePrep | None",
                   parent_model, parent_item_col, tag_model, tag_parent_col,
                   required: set[str], excluded: set[str],
                   iid: IdExpr, extra=None) -> sa.ColumnElement:
    p = aliased(parent_model)
    conds = []
    if extra is not None:
        conds.append(extra(p))
    for name in sorted(required):
        t = aliased(tag_model)
        conds.append(exists(select(sa.literal(1)).where(
            getattr(t, tag_parent_col) == p.id, func.lower(t.name) == name)))
    for name in sorted(excluded):
        t = aliased(tag_model)
        conds.append(not_(exists(select(sa.literal(1)).where(
            getattr(t, tag_parent_col) == p.id, func.lower(t.name) == name))))
    # AN ID LIST WHILE THE PARENT TABLE IS SMALL — `_direct_tag`'s rule, and
    # the bound is the table itself rather than what matches, since a caption
    # has no index on its kind and none is wanted for a question asked under
    # a LIMIT. Captions and links are the tables that hold ONE ROW PER THING
    # SOMEBODY WROTE, so in a library of a million pictures they are usually
    # small and the list is usually the shape. MEASURED at 1.5M pictures,
    # 5,000 of them captioned: `CAPTION:` page 1 and its total 400 -> 21 ms,
    # a scroll page 68 -> 21; `CAPTION:alpha` 409 -> 18 ms and 140 -> 69.
    if prep is not None and prep.rows_under(
            ("parent", parent_model.__name__, _ID_LIST_MAX),
            select(sa.literal(1)).select_from(parent_model), _ID_LIST_MAX):
        return iid.in_(
            select(getattr(p, parent_item_col)).select_from(p).where(*conds))
    return exists(select(sa.literal(1)).select_from(p).where(
        getattr(p, parent_item_col) == iid, *conds))


def _compile_caption(prep: CompilePrep, node: q.CaptionCond) -> Compiled:
    required = {t.name.lower() for t in node.caption_tags if not t.exclude}
    excluded = {t.name.lower() for t in node.caption_tags if t.exclude}
    # `kind` narrows to the list being asked about — descriptions or the
    # instructions saying how the picture was made. The evaluator reads two
    # separate lists for the same reason; this is that split in SQL.
    want = node.caption_kind
    clause = _tagged_exists(prep, Caption, "item_id", CaptionTag,
                            "caption_id", required, excluded, Item.id,
                            extra=lambda c: c.kind == want)
    return Compiled(clause if node.mode == "has" else not_(clause),
                    True, None)


def _compile_link(prep: CompilePrep, node: q.LinkCond) -> Compiled:
    outgoing = node.direction in ("has", "hasnot")
    negate = node.direction in ("hasnot", "notlinkedby")
    required = {t.name.lower() for t in node.link_tags if not t.exclude}
    excluded = {t.name.lower() for t in node.link_tags if t.exclude}
    col = "from_item_id" if outgoing else "to_item_id"
    clause = _tagged_exists(prep, Relationship, col, RelationshipTag,
                            "relationship_id", required, excluded, Item.id)
    return Compiled(not_(clause) if negate else clause, True, None)


# ---- subjects / places / events / taken ------------------------------------


def _subject_presence(name: str, iid: IdExpr) -> sa.ColumnElement:
    it = aliased(ItemTag)
    t = aliased(Tag)
    sub = aliased(Subject)
    conds = [it.item_id == iid, it.negative.is_(False),
             t.id == it.tag_id, sub.tag_id == t.id]
    if name:
        conds.append(func.lower(t.name) == name)
    return exists(select(sa.literal(1)).select_from(it)
                  .join(t, t.id == it.tag_id)
                  .join(sub, sub.tag_id == t.id)
                  .where(*conds))


def _compile_subject(prep: CompilePrep, node: q.SubjectCond) -> Compiled:
    bounded = any(x is not None for x in
                  (node.date_from, node.date_to, node.age_from, node.age_to))
    presence = _subject_presence(node.name.strip().lower(), Item.id)
    if not bounded:
        return Compiled(presence if node.have else not_(presence), True, None)
    if node.have:
        # Bounds only narrow: presence is a sound superset; the evaluator
        # applies the date/age windows over the loaded states.
        return Compiled(presence, False, node)
    return Compiled(None, False, node)  # cannot negate a superset


def _compile_event(prep: CompilePrep, node: q.EventCond) -> Compiled:
    needle = node.name.strip().lower()
    qualifying: set[int] = set()
    for tid, tname, start, end in prep.occasions:
        if needle and tname != needle:
            continue
        if node.date_from is not None or node.date_to is not None:
            if not q._span_overlaps(node, (start, end)):
                continue
        qualifying.add(tid)
    if len(qualifying) > _MAX_IDS:
        return Compiled(None, False, node)
    clause = _direct_tag(prep, qualifying, False, Item.id)
    return Compiled(clause if node.have else not_(clause), True, None)


def _compile_place(prep: CompilePrep, node: q.PlaceCond) -> Compiled:
    needle = node.value.strip().lower()

    # THE SAME RULE `query._eval_place` APPLIES, and it has to be: this
    # compiles a superset only if it reads what the evaluator reads.
    def hit(line: str) -> bool:
        v = (line or "").lower()
        if not v:
            return False
        return v == needle if node.op == "=" else needle in v

    if needle:
        matched = {lid for lid, line in prep.places if hit(line)}
    else:
        # Empty value = "has any location at all".
        matched = {lid for lid, _ in prep.places}
    # A LIBRARY WITH MORE PLACES THAN `_MAX_IDS` FALLS TO THE RESIDUE, and
    # that is measured at 32.7 s on a 1.5M-item, 10,000-place library. Parking
    # the set in the temp table (`prep.big_ids`) was tried and is WORSE — the
    # clauses below are correlated EXISTS, and an `IN (subquery)` inside one
    # is re-evaluated per outer row where a top-level `Item.id IN (...)` is
    # materialized once. That is the whole difference from `_compile_similar`,
    # where the same helper is a large win. The fix, if it is ever worth
    # making, is to compile the ADDRESS predicate into SQL instead of
    # resolving places to ids in Python — the implier closure is the part
    # that does not follow.
    if len(matched) > _MAX_IDS:
        return Compiled(None, False, node)
    via_tag = via_pin = matched
    place_ids = sorted(matched)

    parts_clauses = []
    if via_tag:
        it = aliased(ItemTag)
        loc = aliased(Location)
        # THE IMPLICATIONS COUNT, because that is what a place's parent is: an
        # item at Shibuya Crossing is in Tokyo, and it genuinely carries
        # `tokyo` — reading `item_tags` against the place's own tag alone
        # would answer "no" here while the tag search answered "yes" about
        # the same item.
        tag_ids = set(prep.s.execute(
            select(Location.tag_id).where(Location.id.in_(place_ids),
                                          Location.tag_id.is_not(None))
        ).scalars().all())
        reach = set(tag_ids) | prep.impliers_of(tag_ids)
        if len(reach) > _MAX_IDS:
            return Compiled(None, False, node)
        if reach:
            parts_clauses.append(_direct_tag(prep, reach, False, Item.id))
        # An unnamed place reached by a TAG is impossible (it has none), so
        # the join above is only still here for a place whose tag has since
        # been taken away — it is cheap and it cannot over-match.
        parts_clauses.append(exists(
            select(sa.literal(1)).select_from(it)
            .join(loc, loc.tag_id == it.tag_id)
            .where(it.item_id == Item.id, it.negative.is_(False),
                   loc.id.in_(place_ids))))
    if via_pin:
        il = aliased(ItemLocation)
        parts_clauses.append(exists(select(sa.literal(1)).where(
            il.item_id == Item.id, il.location_id.in_(place_ids))))
    clause = or_(*parts_clauses) if parts_clauses else _false()
    return Compiled(clause if node.have else not_(clause), True, None)


def _compile_taken(prep: CompilePrep, node: q.TakenCond) -> Compiled:
    if not node.have:
        return Compiled(None, False, node)
    # A sound superset: the item has SOME capture-window source and is not
    # marked TAKEN_NONE. The three-source priority and the window overlap
    # stay with the evaluator.
    md = aliased(ItemMetadata)
    has_exif = exists(select(sa.literal(1)).where(
        md.item_id == Item.id, md.name == "date_taken",
        md.mtype == "date", md.num_value.is_not(None), md.num_value != 0))
    it = aliased(ItemTag)
    occ = aliased(Occasion)
    has_event = exists(select(sa.literal(1)).select_from(it)
                       .join(occ, occ.tag_id == it.tag_id)
                       .where(it.item_id == Item.id, it.negative.is_(False),
                              or_(occ.start_date.is_not(None),
                                  occ.end_date.is_not(None))))
    clause = or_(
        Item.taken_at > 0,
        and_(Item.taken_at.is_(None), or_(has_exif, has_event)),
    )
    return Compiled(clause, False, node)


# ---- the tree ---------------------------------------------------------------


def compile_node(prep: CompilePrep, node: q.Node) -> Compiled:
    if isinstance(node, q.Group):
        return _compile_group_node(prep, node)
    if isinstance(node, q.TagCond):
        return _compile_tag(prep, node)
    if isinstance(node, q.GroupCond):
        return _compile_group(prep, node)
    if isinstance(node, q.MetaCond):
        return _compile_meta(prep, node)
    if isinstance(node, q.CaptionCond):
        return _compile_caption(prep, node)
    if isinstance(node, q.LinkCond):
        return _compile_link(prep, node)
    if isinstance(node, q.SubjectCond):
        return _compile_subject(prep, node)
    if isinstance(node, q.EventCond):
        return _compile_event(prep, node)
    if isinstance(node, q.PlaceCond):
        return _compile_place(prep, node)
    if isinstance(node, q.TakenCond):
        return _compile_taken(prep, node)
    if isinstance(node, q.SimilarCond):
        return _compile_similar(prep, node)
    if isinstance(node, q.ValueCond):
        return _compile_value(prep, node)
    return Compiled(None, True, None)  # unknown node: evaluate() returns True


def _compile_value(prep: CompilePrep, node: q.ValueCond) -> Compiled:
    """`VALUE:height>190cm` — any of the resolved value tags, effectively.

    `searchctx.load_value_sets` has already turned the literal into the
    catalog's matching tag NAMES, so this is the `TAG:<meta>` shape over that
    set: the OR of the per-tag positive clause, container fold included, with
    the same `_MAX_META_TAGS` residue past which the statement would only
    grow. An unresolved key (a direct caller that never loaded the sets)
    honestly refuses to compile, and the evaluator answers from an empty set.
    """
    names = prep.value_tags.get(node.key())
    if names is None:
        return Compiled(None, False, node)
    tx: set[int] = set()
    for chunk in chunked(sorted(names)):
        tx |= {t for (t,) in prep.s.execute(
            select(Tag.id).where(Tag.name.in_(chunk))).all()}
    clause = (_fold_any(prep, tx) if prep.containers
              else _any_tag_positive(prep, tx, Item.id))
    if clause is None:
        return Compiled(None, False, node)
    return Compiled(clause if node.have else not_(clause), True, None)


def _compile_similar(prep: CompilePrep, node: q.SimilarCond) -> Compiled:
    """EXACT, always — the pivot is already resolved to an id set.

    Hamming distance has no SQL to compile to (SQLite has no popcount), so
    the obvious reading is that this must be a residue condition scanning the
    library in Python. It is not: `searchctx.load_similar_sets` has already
    turned the pivot into the ids it matches, via the banded near-dup index,
    so all that is left is membership — and an id set is something SQL is
    very good at. The shape is `_compile_place`'s, `_MAX_IDS` guard included.

    A set larger than the guard goes through a TEMP TABLE instead of falling
    back to the residue, and that is not an optimisation — it is what makes
    the condition usable at all on a large library. The residue path
    materializes every candidate the rest of the query admits and evaluates
    it in Python, so a colour search that admits a few percent of a
    million-item library (which greyscale-heavy content does at any useful
    tolerance) paid a whole-library pass per page: measured at 5.0 s a page
    against 1.1 s for the same search one bit tighter, purely because the
    id set crossed `_MAX_IDS`. A join reads it in SQL like any other set.
    """
    ids = prep.similar.get(node.key())
    if ids is None:
        # Nothing resolved this pivot — a caller compiling a tree it never
        # loaded sets for. Refusing to compile keeps the clause honest, and
        # the residue evaluator answers from an empty set: no matches for
        # `COLORLIKE:`. (A NEGATED condition over that same empty set matches
        # everything — safe only because `search_filtered` always resolves
        # before compiling, so this branch is a direct-caller fallback.)
        return Compiled(None, False, node)
    if len(ids) > _MAX_IDS:
        clause = materialize_similar(prep.s, node.key(), ids)
    else:
        clause = Item.id.in_(sorted(ids)) if ids else _false()
    return Compiled(clause if node.have else not_(clause), True, None)


def _compile_group_node(prep: CompilePrep, node: q.Group) -> Compiled:
    if not node.children:
        # An empty group matches everything; negated, nothing.
        return (Compiled(sa.false(), True, None) if node.neg
                else Compiled(None, True, None))
    kids = [compile_node(prep, c) for c in node.children]

    if node.op == "and":
        clauses = [k.clause for k in kids if k.clause is not None]
        clause = and_(*clauses) if clauses else None
        residues = [k.residue for k in kids if k.residue is not None]
        exact = not residues
    else:  # or
        if any(k.exact and k.clause is None for k in kids):
            # An exactly-TRUE disjunct makes the whole OR true.
            clause, residues, exact = None, [], True
        elif all(k.exact for k in kids):
            clause = or_(*[k.clause for k in kids])
            residues, exact = [], True
        elif all(k.clause is not None for k in kids):
            # A superset OR is sound, but says nothing about WHICH disjunct
            # held — the whole node stays residue.
            clause = or_(*[k.clause for k in kids])
            residues, exact = [node.model_copy(update={"neg": False})], False
        else:
            clause, residues, exact = None, [node.model_copy(
                update={"neg": False})], False

    if node.neg:
        if exact:
            return Compiled(
                not_(clause) if clause is not None else sa.false(),
                True, None)
        # Negating a superset is unsound — the whole node (neg included)
        # goes to the evaluator, with no clause.
        return Compiled(None, False, node)

    if exact:
        return Compiled(clause, True, None)
    residue = (residues[0] if len(residues) == 1
               and isinstance(residues[0], q.Group) and node.op == "or"
               else q.Group(op=node.op, neg=False, children=residues))
    return Compiled(clause, False, residue)


def compile_query(
    s: Session, query: Optional[q.Group], *, containers: bool = True,
    file_join: bool = True, similar: Optional[dict] = None,
    value_tags: Optional[dict] = None,
) -> tuple[Optional[sa.ColumnElement], Optional[q.Group]]:
    """The WHERE clause (a proven superset; None = no restriction) and the
    residue tree ``evaluate()`` must still run (None = fully exact).

    ``containers=False`` compiles tag conditions without the sequence-
    container fold — for callers whose own evaluation has none.
    ``file_join=False`` says the consuming statement selects bare ``Item``
    (no active-file join), so file-backed intrinsics stay with the caller's
    evaluator instead of compiling into a cartesian product.
    ``similar`` carries the likeness conditions already resolved to id sets
    (`searchctx.load_similar_sets`); without it such a condition cannot
    compile and falls to the caller's evaluator."""
    if query is None or q.is_empty(query):
        return None, None
    prep = CompilePrep(s, containers=containers, file_join=file_join,
                       similar=similar, value_tags=value_tags)
    compiled = compile_node(prep, query)
    residue = None
    if compiled.residue is not None:
        residue = (compiled.residue
                   if isinstance(compiled.residue, q.Group)
                   else q.Group(op="and", children=[compiled.residue]))
    return compiled.clause, residue


# ---- scope ------------------------------------------------------------------


def scope_clauses(
    s: Session, *, groups: str = "", ungrouped: bool = False,
    trash: bool = False, kind: str = "", sequence: Optional[int] = None,
    hide_sequenced: bool = False, hidden: bool = False,
    show_hidden: bool = False, pending: bool = False,
    pending_kind: str = "", untagged: bool = False,
) -> list[sa.ColumnElement]:
    """The view scope as WHERE clauses over ``Item`` — the SQL mirror of the
    candidate-set branch that used to materialize every id in Python. The
    precedence is the old one: sequence > trash > hidden > pending > the
    group/ungrouped/untagged views."""
    from .resolve import descendant_groups

    out: list[sa.ColumnElement] = []
    kinds = {k.strip() for k in kind.split(",") if k.strip()}
    if kinds:
        out.append(Item.kind.in_(sorted(kinds)))
    if hide_sequenced:
        si = aliased(SequenceItem)
        out.append(not_(exists(select(sa.literal(1)).where(
            si.item_id == Item.id))))

    trashed = exists(select(sa.literal(1)).where(
        TrashedItem.item_id == Item.id))
    if sequence is not None:
        # The membership itself is the join in `base_select`; here only the
        # standard exclusions apply.
        out.append(not_(trashed))
        if not show_hidden:
            out.append(Item.hidden.is_(False))
        return out
    if trash:
        out.append(trashed)  # the trash view shows hidden trashed items too
        return out
    if hidden:
        out.append(Item.hidden.is_(True))
        out.append(not_(trashed))
        return out
    out.append(not_(trashed))
    if not show_hidden:
        out.append(Item.hidden.is_(False))
    if pending:
        out.append(_pending_clause(pending_kind))
        return out
    group_ids = [int(x) for x in groups.split(",") if x.strip().isdigit()]
    if ungrouped:
        ig = aliased(ItemGroup)
        out.append(not_(exists(select(sa.literal(1)).where(
            ig.item_id == Item.id))))
    elif untagged:
        it = aliased(ItemTag)
        out.append(not_(exists(select(sa.literal(1)).where(
            it.item_id == Item.id))))
    elif group_ids:
        # The SUBTREE, and through `_in_groups` for its reason: an EXISTS
        # here probed the membership index once per group id for every item
        # in the library.
        out.append(_in_groups(descendant_groups(s, group_ids), Item.id))
    return out


def _pending_clause(pending_kind: str) -> sa.ColumnElement:
    """Items with a machine-generated result awaiting review (the SQL mirror
    of ``_pending_item_ids``)."""
    parts = []
    if pending_kind in ("", "tags"):
        it = aliased(ItemTag)
        parts.append(exists(select(sa.literal(1)).where(
            it.item_id == Item.id, it.pending.is_(True))))
    if pending_kind in ("", "captions"):
        c = aliased(Caption)
        parts.append(exists(select(sa.literal(1)).where(
            c.item_id == Item.id, c.pending.is_(True))))
    if pending_kind in ("", "faces"):
        isub = aliased(ItemSubject)
        f = aliased(Face)
        parts.append(exists(select(sa.literal(1)).select_from(isub)
                            .join(f, f.id == isub.face_id)
                            .where(isub.item_id == Item.id,
                                   isub.assigned_by == "suggested",
                                   f.dismissed.is_(False))))
    return or_(*parts) if parts else sa.false()


def containers_in_view(where: list[sa.ColumnElement], *,
                       ranking: Optional[str] = None) -> sa.Select:
    """The SEQUENCE CONTAINERS this view shows — the view's own where list,
    asked of the containers.

    ``Item.kind == "sequence"`` says nothing new (a container is one by
    construction) and is what keeps the statement off the whole library:
    with it SQLite seeks ``ix_items_kind`` and reads the containers, without
    it the view's own scan is simply run a second time (measured at a
    million items: 862 ms against 442 for the same folded count).

    Uncorrelated on purpose (``correlate(None)``): it is a question about
    the VIEW, not about any row being tested, so SQLite runs it once per
    statement and probes the membership per item.
    """
    return base_select([Item.id], None, where + [Item.kind == "sequence"],
                       ranking=ranking).correlate(None)


def view_shows_a_container(s: Session, where: list[sa.ColumnElement], *,
                           ranking: Optional[str] = None) -> bool:
    """Is there a sequence in this view for anything to fold onto?

    The fold's own question, asked once and cheaply, so that a view holding
    no sequence pays nothing PER ROW for it — which is most views in most
    libraries, and every view in a library of loose pictures. Measured at a
    million items with a fifth of them in books: 0.05 ms over All Items
    (the first container answers at once), 1.1 ms under a search, 8.3 ms
    for the worst case of proving a negative over a group — against the
    16-230 ms the clause itself costs those same views.

    A superset is safe here in both directions: the where list of an
    inexactly-compiled search can only claim MORE containers than the view
    really shows, and a false yes costs a clause that folds nothing, where
    a no is the truth.
    """
    return bool(s.execute(
        containers_in_view(where, ranking=ranking).limit(1)).first())


def fold_sequenced_clause(
    where: list[sa.ColumnElement], *, ranking: Optional[str] = None,
) -> sa.ColumnElement:
    """Hide a member whose OWN sequence is in this view — the grid's "Fold
    sequences", as one WHERE clause over ``Item``.

    A page of a chapter and the chapter itself are two items, and in a view
    holding both the page is already on screen: it is what the chapter's card
    is a picture of. So the fold drops a member exactly where a sequence
    holding it has its CONTAINER in the same view — and where it does not, the
    member stays, which is the whole of the rule. A group holding the pages
    but not the chapter shows the pages; narrowing the media kinds to images
    takes every container out of the view and so shows them too. Nothing here
    is a fact about the item alone, which is why this is not a
    ``scope_clauses`` clause: it takes the view's OWN where list, the search's
    compiled clause included, and asks it again of the containers.

    The where list passed in must NOT already hold this clause: the view a
    container is judged against is the one without the fold. (A container
    that is itself a member of another sequence is not a shape the importer
    builds — a book inside a book is a flat sibling — so one step is the
    whole answer rather than the first of a walk.)

    AN ANTI-JOIN PROBE, not an id list. `Item.id NOT IN (the members of the
    shown containers)` counts faster (323 ms against 444 at a million items)
    and pages 200 times slower (58 ms against 0.27): it has to materialize
    every folded member before it can answer about the first row, where the
    probe streams in sort order and stops at the page's sixty. The page is
    what somebody is waiting for; the count is memoized on the revision
    (`routers/items.scope_count`).
    """
    si = aliased(SequenceItem)
    sq = aliased(Sequence)
    return not_(exists(
        select(sa.literal(1)).select_from(si)
        .join(sq, sq.id == si.sequence_id)
        .where(si.item_id == Item.id,
               sq.item_id.in_(containers_in_view(where, ranking=ranking)))))


def base_select(cols, sequence: Optional[int],
                where: list[sa.ColumnElement], *,
                occurrences: bool = False,
                ranking: Optional[str] = None) -> sa.Select:
    """``SELECT cols FROM items JOIN files ON the ACTIVE file`` (+ the
    sequence-membership join for a sequence view) with the given WHERE.

    The join reproduces the old "no active file → skip" rule; a sequence
    container legitimately borrows a member's file, so the own-file guard is
    waived for containers.

    ``occurrences`` decides what a repeated member counts as. A sequence may
    hold one item at several positions (a book's repeated blank page), so the
    membership join multiplies its rows — and the two callers want opposite
    things. The GRID wants a card per POSITION (`occurrences=True`): a book
    reads page by page, and a chapter that silently showed 22 cards for 24
    pages was a picture of the wrong book. Everything else — the facets, the
    counts, every list that answers "which items" — wants one row per ITEM,
    which is what the default keeps, by dropping every occurrence but the
    first."""
    stmt = (
        select(*cols)
        .select_from(Item)
        .join(File, and_(
            File.id == Item.active_file_id,
            or_(File.item_id == Item.id, Item.kind == "sequence"),
        ))
    )
    if ranking is not None:
        # THE JOIN IS THE MEMBERSHIP as well as the order: a ranking's scope
        # is exactly the items it has placed, so there is no WHERE clause to
        # go with it (the sequence view says the same thing the same way).
        stmt = stmt.join(_RANKED, and_(
            _RANKED.c.item_id == Item.id,
            _RANKED.c.key == ranking,
        ))
    if sequence is not None:
        stmt = stmt.join(SequenceItem, and_(
            SequenceItem.item_id == Item.id,
            SequenceItem.sequence_id == sequence,
        ))
        if not occurrences:
            twin = aliased(SequenceItem)
            earlier = exists(select(sa.literal(1)).where(
                twin.sequence_id == SequenceItem.sequence_id,
                twin.item_id == SequenceItem.item_id,
                or_(twin.position < SequenceItem.position,
                    and_(twin.position == SequenceItem.position,
                         twin.id < SequenceItem.id)),
            ))
            stmt = stmt.where(not_(earlier))
    return stmt.where(*where)


# ---- paging / aggregates ----------------------------------------------------

SORT_EXPRS: dict[str, sa.ColumnElement] = {}

#: Sort fields whose expression is NULL for "nobody knows" — an undated
#: picture, a file with no colour. Those are not a point on the scale, so they
#: do NOT swap ends when the direction flips: they stay at the bottom either
#: way. Without this SQLite's own NULL ordering moves them to the top on one
#: of the two directions, which reads as the sort having broken.
NULLS_LAST = frozenset({"taken", "color"})


def _taken_expr() -> sa.ColumnElement:
    """When the picture was taken, as a sortable ``YYYYMMDDHHMMSS`` number.

    TWO of ``Item.taken_at``'s three sources, deliberately. What somebody
    typed wins, ``TAKEN_NONE`` stops the walk (they looked and there is no
    date), and otherwise the indexed EXIF ``date_taken`` answers — the same
    priority ``events._date_taken`` reads, and the same encoding, so one
    expression covers both.

    The third source — the span of the EVENTS the picture carries
    (``searchctx.load_taken_windows``) — is left out on purpose: a span is a
    RANGE, not a point, so sorting by it would drop a whole event's undated
    pictures onto one instant and claim a precision nobody stated. An item
    with only that source sorts as undated, which is what it is.
    """
    md = aliased(ItemMetadata)
    exif = (
        select(md.num_value)
        .where(md.item_id == Item.id,
               md.name == "date_taken",
               md.mtype == "date")
        .scalar_subquery()
    )
    return sa.case(
        (Item.taken_at > 0, sa.cast(Item.taken_at, sa.Float)),
        (Item.taken_at == TAKEN_NONE, sa.null()),
        else_=func.nullif(exif, 0),
    )


#: The two primes the shuffle runs over. Both under 2**31, so every product
#: below stays well inside SQLite's signed 64-bit integers.
_SHUFFLE_P1 = 2147483647   # 2**31 - 1
_SHUFFLE_P2 = 2147483629


def _mix(n: int) -> int:
    """Avalanche an integer (murmur3's finalizer) so neighbouring seeds are
    nothing like each other."""
    x = (int(n) & 0xFFFFFFFF) ^ 0x9E3779B9
    x = (x * 0x85EBCA6B) & 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 0xC2B2AE35) & 0xFFFFFFFF
    x ^= x >> 16
    return x


def random_expr(seed: int) -> sa.ColumnElement:
    """A DETERMINISTIC shuffle of the items, keyed by ``seed``.

    Not `random()`: that draws a fresh number per row per statement, so page 2
    would be a different shuffle from page 1 — items appearing twice and
    others never at all. This is arithmetic on ``Item.id``, so every page of
    one view sees the same order and the dice button (a new seed) is the only
    thing that changes it.

    The middle round SQUARES, and that is the whole reason this reads as a
    shuffle. Every affine map ``(id * a + b) % p`` is a permutation, but
    consecutive ids land a CONSTANT number of ranks apart in it (the
    three-gap theorem), so the shuffled grid steps through the library at a
    fixed stride — measured over 1000 ids, one rank-step accounted for a
    quarter of every neighbouring pair. Composing two affine maps does not
    help: over two primes eighteen apart the composition is affine again.
    Squaring is not, and it flattens that count to a handful.

    ``x -> x²`` is two-to-one, so about half the keys collide with exactly
    one other. That is harmless and deliberate: ``Item.id`` is already the
    tiebreaker of every sort here, so a collision is still a total order and
    still the same one on every page.

    No XOR anywhere, on purpose — SQLite has no XOR operator, so the mixing
    has to be arithmetic the database can actually run.
    """
    # The multiplier has to be LARGE, or nothing wraps: a seed of 7 over ids
    # 1..14 gave `8 * id + 7`, which is monotonic — a "shuffle" that handed
    # back the library in id order. So the seed is avalanched first (`_mix`)
    # and the multiplier taken from that, which puts it up near the modulus
    # where consecutive ids land far apart.
    a = 1 + (_mix(seed) % (_SHUFFLE_P1 - 1))
    b = _mix(seed ^ 0x5BF03635) % _SHUFFLE_P1
    c = 1 + (_mix(seed ^ 0x2545F491) % (_SHUFFLE_P2 - 1))
    h = (Item.id * a + b) % _SHUFFLE_P1
    # Every product below stays under 2**62: both moduli are under 2**31.
    return ((h * h) % _SHUFFLE_P1 * c) % _SHUFFLE_P2


def _sort_exprs():
    if not SORT_EXPRS:
        SORT_EXPRS.update({
            "name": func.lower(Item.name),
            "resolution": sa.cast(func.coalesce(File.width, 0), sa.Float)
            * func.coalesce(File.height, 0),
            "megapixels": sa.cast(func.coalesce(File.width, 0), sa.Float)
            * func.coalesce(File.height, 0),
            "width": func.coalesce(File.width, 0),
            "modified": Item.updated_at,
            "first": Item.created_at,
            "earliest": Item.created_at,
            # Spelled out rather than left to the fallback below: it is the
            # DEFAULT sort, and a table that does not name its own default is
            # one where a typo and the intended value are indistinguishable.
            "recent": func.coalesce(Item.last_imported_at, Item.created_at),
            "taken": _taken_expr(),
            # The ORDERING key, not a hash: see `File.color_key`.
            "color": File.color_key,
        })
    return SORT_EXPRS


# ---- grouping ---------------------------------------------------------------
#
# THE GRID'S SECTIONS ARE CONTIGUOUS RUNS OF THE PAGE ORDER, and that is what
# makes grouping nearly free: the runs' counts prefix-sum into each section's
# [start, end) in the SAME flat index space the ungrouped grid already pages
# through, so the flat-index -> page mapping needs no change at all.
#
# Contiguity is STRUCTURAL, not an argument about the group key: `order_by_for`
# PREPENDS the group expression to the ORDER BY. The tempting alternative —
# "a group key must be a monotone coarsening of the sort key, so runs fall out
# by themselves" — holds for dates and breaks the moment a bucket collapses
# values that do not sort together, which two of the four groupings here do:
# `initial` folds every non-letter into "#", and `band` pulls brown out of the
# middle of the orange hues. With the prepend, neither is a special case.

#: Which coarsenings each sort field offers. The pair is validated at the
#: route: an illegal one is refused rather than quietly answered with runs
#: that do not describe the page order.
GROUP_OPTIONS: dict[str, tuple[str, ...]] = {
    "taken": ("year", "month", "day"),
    "recent": ("year", "month", "day"),
    "modified": ("year", "month", "day"),
    "first": ("year", "month", "day"),
    "earliest": ("year", "month", "day"),
    "name": ("initial",),
    "resolution": ("mp",),
    "megapixels": ("mp",),
    "color": ("band",),
}

#: Upper bound of each megapixel band, in MP. The last band is everything past
#: the final entry.
MP_BANDS = (1.0, 2.0, 4.0, 8.0, 16.0)


def group_options_for(sort: str, ranking: bool = False) -> tuple[str, ...]:
    """The groupings legal for one sort token (never including "none").

    A RANKING VIEW ANSWERS ITS OWN, whatever the sort token says: its order
    is the standings and the sort control stands down, so the only coarsening
    that means anything over it is the standings' own buckets — and that one
    always does, which is why a ranking view groups by default where every
    other view does not.
    """
    if ranking:
        return ("bucket",)
    field, _, _dir = sort.partition("_")
    return GROUP_OPTIONS.get(field, ())


def group_expr_for(group_by: str, sort: str) -> sa.ColumnElement:
    """The expression whose distinct values ARE the grid's sections.

    NULL is a value here — an undated picture, a file with no colour — and
    becomes the trailing "nobody knows" section, kept there by the same
    nulls-last term `order_by_for` uses.
    """
    field, _, _dir = sort.partition("_")
    exprs = _sort_exprs()
    if group_by in ("year", "month", "day"):
        expr = exprs.get(field, exprs["recent"])
        if field == "taken":
            # Already a sortable YYYYMMDDHHMMSS NUMBER, so the coarsening is
            # integer division. `strftime` would need it formatted first, and
            # the two spellings would then have to agree about a date the
            # index stores as digits rather than as a timestamp.
            div = {"year": 10 ** 10, "month": 10 ** 8, "day": 10 ** 6}[group_by]
            return sa.cast(expr / div, sa.Integer)
        # created_at / updated_at / last_imported_at are real DateTime columns.
        fmt = {"year": "%Y", "month": "%Y%m", "day": "%Y%m%d"}[group_by]
        return func.strftime(fmt, expr)
    if group_by == "initial":
        first = func.substr(func.lower(Item.name), 1, 1)
        return sa.case((first.op("GLOB")("[a-z]"), first), else_="#")
    if group_by == "mp":
        mp = exprs["resolution"] / 1_000_000.0
        return sa.case(
            *[(mp < cut, i) for i, cut in enumerate(MP_BANDS)],
            else_=len(MP_BANDS),
        )
    if group_by == "bucket":
        # The standings' own number, carried per item by `materialize_ranking`
        # — a bucket IS a contiguous run of the ranking order, which is the
        # rule that makes any grouping legal here.
        return _RANKED.c.bucket
    if group_by == "band":
        # The band is already the colour key's HIGH bits — see `colorkey` —
        # so this is a shift, not a CASE, and the tag set is not spelled
        # out a second time here.
        from .colorkey import BAND_SHIFT

        return sa.cast(File.color_key / (1 << BAND_SHIFT), sa.Integer)
    raise ValueError(f"unknown grouping: {group_by!r}")


def group_order_for(sort: str, group_by: str,
                    ranking: Optional[str] = None) -> list:
    """The ORDER BY for the group-runs aggregate.

    Exactly the LEADING terms of `order_by_for`, so the runs it returns are
    the page order's own runs. The nulls-last term reads the group expression
    rather than the sort expression; the two always agree, because every
    grouping is a function of its sort key and so is NULL exactly where it is.
    """
    if ranking is not None:
        # Best first, which is `position` ascending — and a bucket is a
        # contiguous run of that, so ordering the runs by the bucket
        # descending is the same order with the same boundaries.
        return [_RANKED.c.bucket.desc()]
    field, _, direction = sort.partition("_")
    expr = group_expr_for(group_by, sort)
    order = [expr.asc() if direction == "asc" else expr.desc()]
    if field in NULLS_LAST:
        order.insert(0, expr.is_(None).asc())
    return order


def order_by_for(sort: str, sequence: Optional[int],
                 group_by: Optional[str] = None,
                 ranking: Optional[str] = None) -> list:
    """The ORDER BY for one sort token, ``Item.id`` as the tiebreaker so
    pages stay disjoint whatever the sort keys collide on.

    ``group_by`` prepends its coarsening, which is what makes each group a
    contiguous run of this order. With no grouping the result is byte-identical
    to what it has always been.

    An unknown field falls back to ``recent`` rather than raising — the token
    arrives as a bare string from the API and always has."""
    if ranking is not None:
        # BEST FIRST, and the sort control stands down for it — the order is
        # the ranking, the way a sequence view's order is the book. `bucket`
        # is the grouping's own column and rides along so the sections are
        # contiguous runs of this order, which is what makes them legal.
        return [_RANKED.c.position]
    if sequence is not None:
        return [SequenceItem.position, SequenceItem.id]
    field, _, direction = sort.partition("_")
    if field == "random":
        # A shuffle carries its SEED where a direction would go — it is the
        # only thing such an order has to say about itself, so nothing else on
        # this path had to learn that a new kind of sort exists. Ascending by
        # a pseudo-random key is as good as descending by it, so there is no
        # direction to read.
        expr = random_expr(_seed_of(direction))
        return [expr.asc(), Item.id.asc()]
    asc = direction == "asc"
    exprs = _sort_exprs()
    expr = exprs.get(field, exprs["recent"])
    order = ([expr.asc(), Item.id.asc()] if asc
             else [expr.desc(), Item.id.desc()])
    if group_by:
        g = group_expr_for(group_by, sort)
        order.insert(0, g.asc() if asc else g.desc())
    if field in NULLS_LAST:
        order.insert(0, expr.is_(None).asc())
    return order


def _seed_of(text: str) -> int:
    """The seed out of a ``random_<seed>`` token. Anything unreadable is seed
    0 — one particular shuffle, rather than an error over what is only ever a
    bare string off the wire."""
    try:
        return int(text)
    except ValueError:
        return 0


_MATCHES = sa.table("search_matches", sa.column("item_id", sa.Integer))

#: The colour condition's oversized id sets, KEYED — a query may hold two
#: pivots, and one table per condition is not something a temp schema can
#: grow. Its own table rather than `search_matches`, which the residue path
#: refills mid-query: this one's rows are referenced by the page statement
#: that is about to run.
_SIMILAR = sa.table("similar_matches",
                    sa.column("key", sa.Text),
                    sa.column("item_id", sa.Integer))


def id_source(s: Session, key: str, ids) -> sa.Select:
    """Load an oversized id set into the per-connection temp table and return
    a SELECT of it, for wherever an `IN (...)` would otherwise be built.

    THE POINT IS NOT THE BIND-PARAMETER LIMIT, it is what the alternative
    was: every `_MAX_IDS` guard in this module used to answer "too many" by
    refusing to compile, which drops the WHOLE query to the residue — every
    candidate the rest of it admits materialized and evaluated in Python.
    Measured at 1.5M items: a place search over a 10,000-place library took
    32.7 s and the same search with the set under the guard is milliseconds,
    the entire difference being which side of 5,000 the set fell on. A join
    against a temp table is what an id set of any size costs in SQL.

    Sorted on the way in so the insert walks the primary key in order, and
    only this key's rows are cleared — a connection is reused across
    requests, and two sets of one query must not wipe each other.
    """
    from .db import chunked

    s.execute(sa.text(
        "CREATE TEMP TABLE IF NOT EXISTS similar_matches "
        "(key TEXT NOT NULL, item_id INTEGER NOT NULL, "
        "PRIMARY KEY (key, item_id))"))
    s.execute(sa.text("DELETE FROM similar_matches WHERE key = :k"),
              {"k": key})
    conn = s.connection()
    for chunk in chunked(sorted(ids), 5000):
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO similar_matches (key, item_id) VALUES (?, ?)",
            [(key, int(i)) for i in chunk],
        )
    return sa.select(_SIMILAR.c.item_id).where(_SIMILAR.c.key == key)


def materialize_similar(s: Session, key: str, ids) -> sa.ColumnElement:
    """`id_source` as a membership clause over item ids."""
    return Item.id.in_(id_source(s, key, ids))


_RANKED = sa.table(
    "ranking_order", sa.column("key", sa.Text), sa.column("item_id", sa.Integer),
    sa.column("position", sa.Integer), sa.column("bucket", sa.Integer),
)


def materialize_ranking(s: Session, key: str, placed) -> None:
    """A ranking's placed items, IN THEIR ORDER, into the per-connection temp
    table — the one shape in this module that carries a POSITION.

    A standing is fitted on read and stored nowhere (rung v31), so there is no
    column to sort by and `order_by_for` has nothing to name. `similar_matches`
    cannot carry the answer either: it holds membership, and an id set says
    nothing about order. What CAN is the shape the sequence view already uses —
    a table with a position, JOINED in `base_select`, ordered by that column —
    so offsets, counts and the group runs all keep working exactly as they do
    for a book's pages.

    `placed` is ``(item_id, bucket)`` best first; the position is the index.
    Keyed like `similar_matches` and for the same reason, with one more: a
    temp-table scope compiles to IDENTICAL SQL for every ranking, and
    `scope_count` memoizes on the compiled statement — without a discriminating
    bind parameter it would serve ranking A's count for ranking B inside one
    library revision.
    """
    from .db import chunked

    s.execute(sa.text(
        "CREATE TEMP TABLE IF NOT EXISTS ranking_order "
        "(key TEXT NOT NULL, item_id INTEGER NOT NULL, "
        "position INTEGER NOT NULL, bucket INTEGER, "
        "PRIMARY KEY (key, item_id))"))
    s.execute(sa.text("DELETE FROM ranking_order WHERE key = :k"), {"k": key})
    conn = s.connection()
    rows = [(key, int(i), n, None if b is None else int(b))
            for n, (i, b) in enumerate(placed)]
    for chunk in chunked(rows, 5000):
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO ranking_order "
            "(key, item_id, position, bucket) VALUES (?, ?, ?, ?)", chunk)


_PROBE = sa.table("probe_ids", sa.column("id", sa.Integer))


def admitted(s: Session, cands: sa.Select, ids) -> list[int]:
    """Which of ``ids`` the candidate select ``cands`` admits — ascending,
    deduplicated — DRIVEN FROM THE IDS.

    The obvious spelling, ``cands.where(Item.id.in_(chunk))``, is a
    disaster on exactly one shape of scope, and it is a common one: a
    GROUP (``items.id IN (SELECT item_id FROM item_groups …)``) under a KIND
    filter. There SQLite takes ``ix_items_kind`` (hidden, kind, id) and
    feeds BOTH multi-valued constraints on the id into it — the plan reads
    ``(hidden=? AND kind=? AND id=? AND rowid=?)`` — and runs the CROSS
    PRODUCT of the two lists: a 900-id chunk against a 60,000-member group
    is 54 million index probes. Measured on a 600,000-item library, **12.8 s
    per chunk**, so the session feeds' id probe (twenty-odd chunks) took
    minutes and the first picture of a tag batch never arrived. The same
    chunk without the kind filter is 24 ms and without the group 7 ms, which
    is why nothing smaller showed it.

    So the ids go into a keyed TEMP table and the question is asked per id:
    ``SELECT id FROM probe_ids WHERE EXISTS (<cands> AND items.id =
    probe_ids.id)``. That is a scan of the probe table with one rowid lookup
    into ``items`` each — 3–7 ms per 900 ids on EVERY scope shape measured,
    since nothing about the scope can change what drives the loop. (A plain
    JOIN to the temp table does not do it: SQLite still drives from the
    scope's index and looks the probe table up per scope row, i.e. a scan of
    the scope — 0.25 s over the whole library for 900 ids.)

    No chunking is needed: the temp table holds the lot, and a bind
    parameter is never involved. ``tests/core/test_probe.py`` holds the
    plan to the driving order.
    """
    from .db import chunked

    want = sorted({int(i) for i in ids})
    if not want:
        return []
    s.execute(sa.text(
        "CREATE TEMP TABLE IF NOT EXISTS probe_ids (id INTEGER PRIMARY KEY)"))
    s.execute(sa.text("DELETE FROM probe_ids"))
    conn = s.connection()
    for chunk in chunked(want, 5000):
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO probe_ids (id) VALUES (?)",
            [(i,) for i in chunk],
        )
    stmt = (select(_PROBE.c.id)
            .where(exists(cands.where(Item.id == _PROBE.c.id)))
            .order_by(_PROBE.c.id))
    return [int(i) for i in s.execute(stmt).scalars().all()]


def materialize_matches(s: Session, ids) -> sa.TableClause:
    """Load a Python-side matched-id set into the per-connection temp table
    (the residual path's bridge back into SQL: an ORDER BY/LIMIT/aggregate
    over a huge id list cannot be chunked, a join can)."""
    from .db import chunked

    s.execute(sa.text(
        "CREATE TEMP TABLE IF NOT EXISTS search_matches "
        "(item_id INTEGER PRIMARY KEY)"))
    s.execute(sa.text("DELETE FROM search_matches"))
    conn = s.connection()
    for chunk in chunked(ids, 5000):
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO search_matches (item_id) VALUES (?)",
            [(int(i),) for i in chunk],
        )
    return _MATCHES


# ---- effective tag counts ---------------------------------------------------
# The sidebar's per-tag counts used to come from resolving EVERY item's
# effective tags in Python. The same numbers decompose into SQL: a tag nobody
# grants through a group and nobody implies-into is effectively positive on
# exactly the items that assign it directly (one GROUP BY answers every such
# tag at once); only the SPECIAL tags — group-granted or implication targets,
# a catalog-sized set — need an individual COUNT over their exact clause.
# Sequence containers fold in the same split: member-direct pairs in one
# grouped query for the plain tags, and the clause's own container branch for
# the special ones.


def _tag_candidates(prep: CompilePrep, tx: set[int], *, containers: bool,
                    negative: bool = False):
    """The items that could possibly carry this tag effectively, as a SELECT
    of ids — and the thing a per-tag COUNT should iterate over.

    A COUNT of a tag clause is `SELECT count(*) FROM items WHERE <clause>`,
    which is a scan of the LIBRARY however few items carry the tag: measured
    at a million items, 0.74 s each, and the tags list runs one per tag that
    a group grants or an implication targets — 100 of those made the list
    take 42 SECONDS. Nothing about the answer needs the scan: every clause
    `_tag_positive` can produce requires either a DIRECT assignment of the
    tag or one of its impliers, or membership of a group granting one of
    them, and a container matches only when a member does. So those three
    index lookups are a proven SUPERSET of the answer, and counting over
    them asks the same question of far fewer rows (0.74 s → 0.017 s).

    The CLAUSE is unchanged and still decides — this only says where to look
    for candidates, so there is no second definition of what the count means.
    """
    ids = sorted(tx if negative else tx | prep.impliers_of(tx))
    if not ids:
        return None
    direct = select(ItemTag.item_id.label("id")).where(
        ItemTag.tag_id.in_(ids), ItemTag.negative.is_(negative))
    parts = [direct]
    granting = prep.groups_granting(set(ids), negative=negative)
    if granting:
        parts.append(select(ItemGroup.item_id.label("id"))
                     .where(ItemGroup.group_id.in_(sorted(granting))))
    if not containers:
        return _one_each(parts)
    sq, si = aliased(Sequence), aliased(SequenceItem)
    inner = _one_each(parts)
    conts = (select(sq.item_id.label("id")).select_from(sq)
             .join(si, si.sequence_id == sq.id)
             .where(sq.item_id.is_not(None),
                    si.item_id.in_(select(inner.c.id))))
    return _one_each(parts + [conts])


def _one_each(parts):
    """The union of these id selects, each item ONCE.

    A UNION is distinct by definition and a single SELECT is not — and one
    part is the ordinary case (a tag nothing grants through a group), where
    an item carrying two of the impliers would otherwise be a candidate
    twice and counted twice. Found by `test_effective_counts`' comparison
    against the old fold, which is what that test is for.
    """
    return (sa.union(*parts) if len(parts) > 1
            else parts[0].distinct()).subquery()


def count_items_with_tag(s: Session, name: str, *,
                         prep: Optional[CompilePrep] = None,
                         containers: bool = True,
                         item_kinds: Optional[Iterable[str]] = None) -> int:
    """How many items carry ``name`` effectively positive — the number a
    search for the tag returns. ``containers=False`` skips the
    sequence-container fold (the subjects/places/events lists never folded
    it, and their numbers must not drift from what they showed).

    ``name`` is the STORED catalog name, matched exactly — lowercasing is
    the query evaluator's convention for typed input, not the catalog's.
    ``item_kinds`` counts only items of those kinds (the tags list's media
    filter, any subset of image / video / sequence); the clause is unchanged,
    only the population is narrowed."""
    kinds = _kind_set(item_kinds)
    prep = prep or CompilePrep(s)
    if containers:
        clause = _with_container(
            lambda iid: _tag_positive(prep, name, iid),
            veto=_direct_tag(prep, prep.tag_ids(name), True, Item.id),
            prep=prep)
    else:
        clause = _tag_positive(prep, name, Item.id)
    if clause is None:  # a pathological implier set: fall back to resolving
        from .resolve import effective_for_items

        eff = effective_for_items(s)
        if kinds:
            kind_of = dict(s.execute(select(Item.id, Item.kind)).all())
            return sum(1 for iid, e in eff.items()
                       if name in e.positive and kind_of.get(iid) in kinds)
        return sum(1 for e in eff.values() if name in e.positive)
    cand = _tag_candidates(prep, prep.tag_ids(name), containers=containers)
    if cand is None:  # no such tag — the clause says so too
        return 0
    stmt = (select(func.count()).select_from(cand)
            .join(Item, Item.id == cand.c.id).where(clause))
    if kinds:
        stmt = stmt.where(Item.kind.in_(sorted(kinds)))
    return int(s.execute(stmt).scalar_one())


def _kind_set(item_kinds: Optional[Iterable[str]]) -> set[str]:
    """The media kinds a count is narrowed to — a string, an iterable or
    None — as a set; an empty set means every kind (no narrowing)."""
    if item_kinds is None:
        return set()
    if isinstance(item_kinds, str):
        return {item_kinds} if item_kinds else set()
    return {k for k in item_kinds if k}


def counts_without_containers(
    s: Session, names, *, prep: Optional[CompilePrep] = None,
) -> dict[str, int]:
    """``count_items_with_tag(..., containers=False)`` for MANY names at once.

    The subjects, places and events lists each show one identity tag's count
    per row, and each was running one exact-clause COUNT per row — a
    3000-subject library took seconds to list. The split is
    ``effective_tag_counts``' own: a tag nothing grants through a group and
    nothing implies INTO is effectively positive exactly where it is directly
    positive (a direct negative cannot coexist — ``UniqueConstraint``), so
    all of those are ONE GROUP BY; only the special ones keep their per-tag
    exact-clause COUNT, and an identity tag is almost never one.
    """
    prep = prep or CompilePrep(s)
    from .db import chunked

    want = {n for n in names if n}
    # ONLY THE NAMES ASKED ABOUT. It read `(id, name)` for the WHOLE catalog
    # to answer about a few thousand — 0.20 s of a 0.44 s call at 250,000
    # tags, on every subjects, places and events listing, for rows it then
    # threw away.
    tag_names: dict[int, str] = {}
    for chunk in chunked(sorted(want)):
        tag_names.update(
            (tid, nm) for tid, nm in
            s.execute(select(Tag.id, Tag.name).where(Tag.name.in_(chunk))).all())
    eff_gpos, _ = prep.group_grants
    granted = set().union(*eff_gpos.values()) if eff_gpos else set()
    implied_into = {b for _, b in prep.implication_edges}
    # A special tag OUTSIDE `want` cannot make one inside it special, so the
    # intersection is the whole of what has to be known here.
    special = {tag_names[t] for t in (granted | implied_into)
               if t in tag_names}
    out: dict[str, int] = {n: 0 for n in want}

    plain = [t for t, n in tag_names.items()
             if n in want and n not in special]
    for chunk in chunked(plain):
        for tid, cnt in s.execute(
            select(ItemTag.tag_id, func.count())
            .where(ItemTag.tag_id.in_(chunk), ItemTag.negative.is_(False))
            .group_by(ItemTag.tag_id)
        ).all():
            out[tag_names[tid]] = int(cnt)
    for n in want & special:
        out[n] = count_items_with_tag(s, n, prep=prep, containers=False)
    return out


def effective_tag_counts(
    s: Session, item_kinds: Optional[Iterable[str]] = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Per tag name: the effective positive count (container fold included),
    the indirect share of it, and the effective negative count — exactly the
    numbers the old whole-library resolve+fold produced for the tags list.

    ``indirect = positive - direct`` holds by construction: a direct positive
    assignment is always effectively positive (a direct negative on the same
    tag cannot coexist — ``UniqueConstraint(item_id, tag_id)``).

    ``item_kinds`` narrows every figure to items of those media kinds — the
    tags list's media button, any subset of image / video / sequence. The
    RULES are untouched; only the population is: the direct counts join the
    item, the container fold counts only containers of those kinds (a
    container is a sequence, so a filter without sequences folds nothing),
    and the special tags' exact counts take the same clause.
    """
    kinds = _kind_set(item_kinds)
    prep = CompilePrep(s)
    names = dict(s.execute(select(Tag.id, Tag.name)).all())

    direct_pos: dict[str, int] = {}
    direct_neg: dict[str, int] = {}
    direct_stmt = (select(ItemTag.tag_id, ItemTag.negative, func.count())
                   .group_by(ItemTag.tag_id, ItemTag.negative))
    if kinds:
        direct_stmt = (direct_stmt.join(Item, Item.id == ItemTag.item_id)
                       .where(Item.kind.in_(sorted(kinds))))
    for tid, negative, cnt in s.execute(direct_stmt).all():
        name = names.get(tid)
        if name is None:
            continue
        (direct_neg if negative else direct_pos)[name] = int(cnt)

    eff_gpos, eff_gneg = prep.group_grants
    granted_pos_ids = set().union(*eff_gpos.values()) if eff_gpos else set()
    granted_neg_ids = set().union(*eff_gneg.values()) if eff_gneg else set()
    implied_into_ids = {b for _, b in prep.implication_edges}
    special_pos = {names[t] for t in (granted_pos_ids | implied_into_ids)
                   if t in names}
    special_neg = {names[t] for t in granted_neg_ids if t in names}

    pos: dict[str, int] = {}
    neg: dict[str, int] = {}
    # Plain tags: direct count + containers whose members carry the tag
    # directly and that carry NO row of their own for it — a positive is
    # already in the direct count, and a NEGATIVE vetoes the fold (the
    # container's own word beats its pages', `_with_container`'s rule).
    sq = aliased(Sequence)
    si = aliased(SequenceItem)
    it = aliased(ItemTag)
    own = aliased(ItemTag)
    fold_stmt = (
        select(it.tag_id, func.count(func.distinct(sq.item_id)))
        .select_from(sq)
        .join(si, si.sequence_id == sq.id)
        .join(it, and_(it.item_id == si.item_id, it.negative.is_(False)))
        .where(sq.item_id.is_not(None),
               not_(exists(select(sa.literal(1)).where(
                   own.item_id == sq.item_id, own.tag_id == it.tag_id))))
        .group_by(it.tag_id))
    if kinds:
        cont = aliased(Item)
        fold_stmt = (fold_stmt.join(cont, cont.id == sq.item_id)
                     .where(cont.kind.in_(sorted(kinds))))
    container_pairs = dict(s.execute(fold_stmt).all())
    id_by_name = {n: t for t, n in names.items()}
    for name in set(direct_pos) | {names.get(t) for t in container_pairs
                                   if names.get(t)}:
        if name in special_pos:
            continue
        pos[name] = (direct_pos.get(name, 0)
                     + int(container_pairs.get(id_by_name.get(name), 0)))
    for name, cnt in direct_neg.items():
        if name not in special_neg:
            neg[name] = cnt
    # Special tags: one exact-clause COUNT each (catalog-sized sets).
    for name in special_pos:
        pos[name] = count_items_with_tag(s, name, prep=prep, item_kinds=kinds)
    for name in special_neg:
        tx = prep.tag_ids(name.lower())
        cand = _tag_candidates(prep, tx, containers=False, negative=True)
        if cand is None:
            neg[name] = 0
            continue
        neg_stmt = (select(func.count()).select_from(cand)
                    .join(Item, Item.id == cand.c.id)
                    .where(_tag_negative(prep, tx, Item.id)))
        if kinds:
            neg_stmt = neg_stmt.where(Item.kind.in_(sorted(kinds)))
        neg[name] = int(s.execute(neg_stmt).scalar_one())

    ind = {name: cnt - direct_pos.get(name, 0)
           for name, cnt in pos.items() if cnt > direct_pos.get(name, 0)}
    return pos, ind, neg
