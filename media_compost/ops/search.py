"""Turning a scope + a condition tree into a page of items, in SQL.

This is the read path's engine and it belongs below the transport layer for
two reasons. The web grid needs it, and so does anything that filters a
library from Python — where `scripting.query()` used to do
`select(Item)` over the WHOLE library and filter in Python, with no paging at
all, while this path has had SQL-narrowed candidates and LIMIT/OFFSET for some
time.

`media_compost.query.evaluate` stays the ONE definition of what a condition
means. `prefilter` compiles as much of the tree as it provably can into a
WHERE clause that is a SUPERSET of the matches; whatever will not compile
exactly is the RESIDUE, re-evaluated here over the SQL-narrowed candidates.
Adding a condition kind means a compiler in `prefilter` (or an honest
`Compiled(None, False, node)`) — never a change to what a match IS.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import prefilter
from .. import query as q
from ..db import (
    Caption, File, Item, ItemGroup, Sequence, SequenceItem, chunked,
)
from ..metadata_catalog import INTRINSIC_NAMES, intrinsic_nums, intrinsic_texts
from ..resolve import Resolver
from ..searchctx import (
    load_caption_sets, load_event_sets, load_face_counts, load_file_counts,
    load_group_sets, load_indexed_meta, load_link_sets, load_place_sets,
    load_sequence_counts, load_similar_sets, load_subject_sets, load_tag_meta,
    load_taken_windows, load_text_counts, load_value_sets,
)


def seq_inherited(
    s: Session, items: list[Item], resolver: Optional[Resolver] = None
) -> dict[int, set[str]]:
    """For each "sequence" container in ``items``, the union of its members'
    effective positive tags — inherited by the sequence just as a group's tags
    are inherited by its items. Keyed by container item id.

    A RANKING OWNED A NAMESPACE HERE UNTIL RUNG v31, and its score tags
    were left out of the union — a score was computed for the picture the
    fit placed, and a chapter answering to its best page's `quality:7` was
    inheritance nobody asked for. A ranking mints nothing now: whatever a
    rating axis put on a picture is an ordinary tag somebody's rules wrote,
    and it inherits like every other one.
    """
    container_ids = [it.id for it in items if it.kind == "sequence"]
    if not container_ids:
        return {}
    seq_by_item: dict[int, int] = {}
    for sid, iid in s.execute(
        select(Sequence.id, Sequence.item_id).where(Sequence.item_id.in_(container_ids))
    ).all():
        if iid is not None:
            seq_by_item[iid] = sid
    members_by_seq: dict[int, list[int]] = {}
    all_members: set[int] = set()
    if seq_by_item:
        for sid, mid in s.execute(
            select(SequenceItem.sequence_id, SequenceItem.item_id)
            .where(SequenceItem.sequence_id.in_(list(seq_by_item.values())))
        ).all():
            members_by_seq.setdefault(sid, []).append(mid)
            all_members.add(mid)
    res = resolver or Resolver(s)
    eff = res.effective_for(list(all_members)) if all_members else {}
    # THE CONTAINER'S OWN NEGATIVE WINS over its pages: a chapter marked
    # `-dog` has been said not to be about dogs, whatever one page carries.
    # The item detail always showed such a tag overridden; the search clause
    # (`prefilter._with_container`'s veto) and the counts drop it the same
    # way, so the exact path stays exact.
    own = res.effective_for(list(seq_by_item)) if seq_by_item else {}
    out: dict[int, set[str]] = {}
    for cid, sid in seq_by_item.items():
        tags: set[str] = set()
        for mid in members_by_seq.get(sid, []):
            e = eff.get(mid)
            if e:
                tags |= e.positive
        mine = own.get(cid)
        if mine:
            tags -= set(mine.direct_negative)
        out[cid] = tags
    return out


def pending_item_ids(s: Session, kind: str = "") -> set[int]:
    """Items with a machine-generated result awaiting review. ``kind`` narrows
    to "tags", "captions" or "faces"; empty means any of them (their union).

    The rule itself lives in ``prefilter._pending_clause`` (the listing path
    applies it as a WHERE clause, never materializing this set); this wrapper
    exists for callers — and the tests — that want the ids."""
    return set(s.execute(
        select(Item.id).where(prefilter._pending_clause(kind))
    ).scalars().all())


@dataclass
class CandidateSet:
    """A lazy description of the scoped+compiled candidate set.

    ``where`` is scope + the compiled query clause (a proven superset);
    ``residue`` is what :func:`media_compost.query.evaluate` must still check
    over the candidates (None = the SQL is exact and pages come straight from
    LIMIT/OFFSET)."""

    where: list
    residue: "Optional[q.Group]"
    sequence: Optional[int]
    # Likeness conditions resolved to id sets, ONCE per search: the compiler
    # turned them into `Item.id IN (...)` and the residue evaluator reads the
    # same answer, so a pivot is never resolved twice.
    similar: dict = dc_field(default_factory=dict, repr=False)
    # VALUE conditions resolved to matching tag-NAME sets, once per search —
    # the compiler turned each into a tag-set clause and the residue
    # evaluator reads the same answer.
    value_tags: dict = dc_field(default_factory=dict, repr=False)
    _matched: Optional[list[int]] = dc_field(default=None, repr=False)
    #: The temp-table KEY of a ranking scope, or None. Carried rather than
    #: turned into a WHERE clause because the join IS the membership AND the
    #: order — the sequence view's own shape.
    ranking: Optional[str] = None

    def ids_select(self):
        return prefilter.base_select([Item.id], self.sequence, self.where,
                                     ranking=self.ranking)

    def matched_ids(self, s: Session, resolver: Resolver) -> list[int]:
        """The residue-evaluated match set (cached per CandidateSet)."""
        if self._matched is None:
            self._matched = evaluate_residue(s, self, resolver)
        return self._matched


def memberships_for(s: Session, ids: list[int]) -> dict[int, list[int]]:
    """Group memberships for just these items."""
    m: dict[int, list[int]] = {}
    for chunk in chunked(ids):
        for iid, gid in s.execute(
            select(ItemGroup.item_id, ItemGroup.group_id)
            .where(ItemGroup.item_id.in_(chunk))
        ).all():
            m.setdefault(iid, []).append(gid)
    return m


def scope_of(body) -> dict:
    """The SCOPE fields of a search request, spelled once, as the keyword
    arguments `search_filtered` takes.

    Ten request models inherit `ItemSearchRequest` — the search, the id
    range, the group runs, the facets, the AI enqueue, and the whole-view
    hide / trash / group / quick-assign writes. Each used to name the eleven
    scope fields itself, so a field ADDED to the model reached every body on
    the wire and then depended on ten separate calls remembering to pass it
    on. A writer that forgot would not fail: it would act on a WIDER scope
    than the button said — "Hide 47 items" over the whole library.

    So the list lives here, and a caller that has a body has no reason to
    spell any of it. Duck-typed rather than importing the model, because this
    module sits below `server/`.
    """
    return dict(
        groups=body.groups, ungrouped=body.ungrouped, trash=body.trash,
        kind=body.kind, sequence=body.sequence,
        hide_sequenced=body.hide_sequenced, hidden=body.hidden,
        show_hidden=body.show_hidden, pending=body.pending,
        pending_kind=body.pending_kind, untagged=body.untagged,
        ranking=body.ranking, ranking_pool=body.ranking_pool,
        ranking_dismissed=body.ranking_dismissed,
    )


def search_filtered(
    s: Session, groups: str, ungrouped: bool, trash: bool = False,
    kind: str = "", sequence: Optional[int] = None,
    hide_sequenced: bool = False, hidden: bool = False, show_hidden: bool = False,
    pending: bool = False, pending_kind: str = "", untagged: bool = False,
    query: "Optional[q.Group]" = None,
    resolver: Optional[Resolver] = None,
    ranking: Optional[int] = None, ranking_pool: Optional[int] = None,
    ranking_dismissed: bool = False,
) -> CandidateSet:
    """The candidate set for one view: scope + search, described as SQL.

    Filtering comes from the structured condition ``query`` (the frontend's
    parsed tree); the backend never parses a query string. The tree is
    compiled to a WHERE clause where the compilation is provably exact and
    left to :func:`media_compost.query.evaluate` (over the SQL-narrowed
    candidates) where it is not — see :mod:`media_compost.prefilter`. Nothing
    here materializes items: pagination, counting and aggregates run over
    ``CandidateSet`` in SQL.
    """
    where = prefilter.scope_clauses(
        s, groups=groups, ungrouped=ungrouped, trash=trash, kind=kind,
        sequence=sequence, hide_sequenced=hide_sequenced, hidden=hidden,
        show_hidden=show_hidden, pending=pending, pending_kind=pending_kind,
        untagged=untagged,
    )
    rank_key = None
    if ranking and ranking_dismissed:
        # THE SET-ASIDE ONES HAVE NO STANDING, so this is a membership clause
        # and not the positioned join: there is no order to page them in, and
        # the sort control stays live the way it does for any ordinary view.
        # "Not applicable" is ranking-wide, never per pool.
        where = where + [_dismissed_clause(int(ranking))]
    elif ranking:
        rank_key = _ranking_scope(s, ranking, ranking_pool)
    active = query is not None and not q.is_empty(query)
    residue = None
    similar: dict = {}
    value_tags: dict = {}
    if active:
        if q.references_similar(query):
            # Resolved BEFORE compiling, because the compiler turns each set
            # into an exact `IN (...)`: one pass over the index answers both
            # the SQL clause and the residue evaluator.
            similar = load_similar_sets(
                s, q.similar_conditions(query))
        if q.references_values(query):
            # Same rule: one catalog pass answers the compiled tag-set
            # clause and the residue evaluator alike.
            value_tags = load_value_sets(s, q.value_conditions(query))
        clause, residue = prefilter.compile_query(
            s, query, similar=similar, value_tags=value_tags)
        if clause is not None:
            where = where + [clause]
    return CandidateSet(where=where, residue=residue, sequence=sequence,
                        similar=similar, value_tags=value_tags,
                        ranking=rank_key)


def _dismissed_clause(ranking_id: int):
    """The pictures somebody said this axis is not about."""
    from ..db import RankingDismissal

    return Item.id.in_(
        select(RankingDismissal.item_id)
        .where(RankingDismissal.ranking_id == ranking_id))


def _ranking_scope(s: Session, ranking_id: int,
                   pool_id: Optional[int]) -> Optional[str]:
    """Load a ranking's placed items, in their order, into the temp table and
    answer the key to join it by — or None where there is no such ranking.

    THE FIT IS MEMOIZED AND THE TABLE IS NOT. `db.cached` holds the ordered
    list for as long as the library has not moved, which is what keeps the
    page query, the count, the group runs, the id range and every facet
    request from each paying a Bradley-Terry fit for the same answer. The temp
    table is per CONNECTION, so each of those requests still materializes —
    an insert of a bounded id list, where the fit is O(iterations x
    judgments).

    Bounded, because a ranking holds what somebody compared: two items per
    judgment, never the library.
    """
    from ..db import Ranking
    from . import rankings as ops_rankings

    rk = s.get(Ranking, int(ranking_id))
    if rk is None:
        return None
    pools = [int(pool_id)] if pool_id else None
    key = f"rank:{rk.id}:{pool_id or ''}"
    lib_db = (s.info or {}).get("mc_db")
    placed = (lib_db.cached(s, ("ranking-order", rk.id, pool_id),
                            lambda: ops_rankings.placed_in_order(s, rk, pools))
              if lib_db is not None
              else ops_rankings.placed_in_order(s, rk, pools))
    prefilter.materialize_ranking(s, key, placed)
    return key



def evaluate_residue(
    s: Session, cands: CandidateSet, resolver: Resolver
) -> list[int]:
    """Run the residue tree over the SQL-narrowed candidates.

    Mirrors the old full-evaluation loop, but only loads what the residue
    actually references — an exactly-compiled condition never forces its
    loader anymore.
    """
    residue = cands.residue
    assert residue is not None
    candidate_ids = list(s.execute(cands.ids_select()).scalars().all())
    if not candidate_ids:
        return []

    meta_names = q.referenced_meta_names(residue)
    # Intrinsic file/item-derived values are only needed when the residue
    # still holds an intrinsic meta condition (an OR that kept whole).
    file_intrinsics = (meta_names & INTRINSIC_NAMES) - {
        "tag_count", "caption_count", "faces", "unnamed_faces",
        "text_blocks", "sequence_count", "file_count"}
    needs_eff = ("tag_count" in meta_names
                 or any(isinstance(n, (q.TagCond, q.ValueCond))
                        for n in q._walk(residue)))

    items: dict[int, Item] = {}
    active_file: dict[int, File] = {}
    if file_intrinsics or needs_eff:
        for chunk in chunked(candidate_ids):
            for it in s.execute(
                select(Item).where(Item.id.in_(chunk))
            ).scalars().all():
                items[it.id] = it
    if file_intrinsics:
        for chunk in chunked(candidate_ids):
            for iid, f in s.execute(
                prefilter.base_select([Item.id, File], None, [])
                .where(Item.id.in_(chunk))
            ).all():
                active_file[iid] = f

    eff = resolver.effective_for(candidate_ids) if needs_eff else {}
    inherited = (
        seq_inherited(s, [it for it in items.values()
                           if it.kind == "sequence"], resolver=resolver)
        if needs_eff else {}
    )

    meta_by_item: dict[int, dict[str, q.MetaVal]] = {}
    out_links: dict[int, list[frozenset[str]]] = {}
    in_links: dict[int, list[frozenset[str]]] = {}
    group_direct: dict[int, frozenset[str]] = {}
    group_anc: dict[int, frozenset[str]] = {}
    group_dpaths: dict[int, frozenset[str]] = {}
    group_apaths: dict[int, frozenset[str]] = {}
    caption_sets: dict[int, list[frozenset[str]]] = {}
    instruction_sets: dict[int, list[frozenset[str]]] = {}
    caption_counts: dict[int, int] = {}
    instruction_counts: dict[int, int] = {}
    subject_sets: dict[int, dict] = {}
    place_sets: dict[int, list[dict]] = {}
    event_sets: dict[int, dict] = {}
    taken_windows: dict[int, tuple[int, int]] = {}
    face_counts: dict[int, tuple[int, int]] = {}
    text_counts: dict[int, int] = {}
    # One map for the whole search rather than one per item: it is a fact
    # about the catalog, and every item's context reads the same answer.
    tag_meta: dict[str, frozenset[str]] = (
        load_tag_meta(s) if q.references_tag_meta(residue) else {})
    if q.referenced_indexed_meta(residue):
        meta_by_item = load_indexed_meta(s, candidate_ids)
    if q.references_links(residue):
        out_links, in_links = load_link_sets(s, candidate_ids)
    if q.references_groups(residue):
        (group_direct, group_anc,
         group_dpaths, group_apaths) = load_group_sets(s, candidate_ids)
    if q.references_captions(residue):
        caption_sets, instruction_sets = load_caption_sets(s, candidate_ids)
    if q.references_subjects(residue):
        subject_sets = load_subject_sets(s, candidate_ids)
    if q.references_places(residue):
        place_sets = load_place_sets(s, candidate_ids)
    if q.references_events(residue):
        event_sets = load_event_sets(s, candidate_ids)
    if q.references_taken(residue):
        taken_windows = load_taken_windows(s, candidate_ids)
    if {"faces", "unnamed_faces"} & meta_names:
        face_counts = load_face_counts(s, candidate_ids)
    if "text_blocks" in meta_names:
        text_counts = load_text_counts(s, candidate_ids)
    sequence_counts: dict[int, int] = {}
    if "sequence_count" in meta_names:
        sequence_counts = load_sequence_counts(s, candidate_ids)
    file_counts: dict[int, int] = {}
    if "file_count" in meta_names:
        file_counts = load_file_counts(s, candidate_ids)
    if {"caption_count", "instruction_count"} & meta_names:
        from sqlalchemy import func

        # One aggregate for both, split by kind: they are rows of one table and
        # a second GROUP BY over it would answer the same question twice.
        counts_by_kind: dict[str, dict[int, int]] = {
            "caption": caption_counts, "instruction": instruction_counts}
        for chunk in chunked(candidate_ids):
            for iid, kind, n in s.execute(
                select(Caption.item_id, Caption.kind, func.count(Caption.id))
                .where(Caption.item_id.in_(chunk),
                       Caption.pending.is_(False))
                .group_by(Caption.item_id, Caption.kind)
            ).all():
                target = counts_by_kind.get(kind or "caption")
                if target is not None:
                    target[iid] = target.get(iid, 0) + n

    matched: list[int] = []
    for iid in candidate_ids:
        it = items.get(iid)
        af = active_file.get(iid)
        tags: set[str] = set()
        neg: set[str] = set()
        if needs_eff:
            e = eff.get(iid)
            if e:
                tags, neg = set(e.positive), set(e.negative)
            if it is not None and it.kind == "sequence":
                tags |= inherited.get(iid, set())
        nums = (intrinsic_nums(af, it.last_imported_at, it.created_at)
                if af is not None and it is not None else {})
        nums["tag_count"] = float(len(tags))
        nums["caption_count"] = float(caption_counts.get(iid, 0))
        nums["instruction_count"] = float(instruction_counts.get(iid, 0))
        total, unnamed = face_counts.get(iid, (0, 0))
        nums["faces"] = float(total)
        nums["unnamed_faces"] = float(unnamed)
        nums["text_blocks"] = float(text_counts.get(iid, 0))
        nums["sequence_count"] = float(sequence_counts.get(iid, 0))
        nums["file_count"] = float(file_counts.get(iid, 0))
        qctx = q.QueryCtx(
            tags=frozenset(tags), neg=frozenset(neg),
            nums=nums,
            texts=(intrinsic_texts(it.kind, af, it.uid)
                   if it is not None else {}),
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
            # Already resolved by `search_filtered` — the same answer the
            # compiled clause was built from, so the two can never disagree.
            value_tags=cands.value_tags,
            similar=frozenset(k for k, ids in cands.similar.items()
                              if iid in ids),
            tag_meta=tag_meta,
        )
        if q.evaluate(residue, qctx):
            matched.append(iid)
    return matched
