"""`prefilter.effective_tag_counts` / `count_items_with_tag` against the old
whole-library resolve+fold, on randomized libraries with grants, implications
(including a cycle), aliases and sequence containers."""

from __future__ import annotations

import random

from sqlalchemy import select

from media_compost.db import (
    Database, Group, GroupParent, GroupTag, Item, ItemGroup, ItemTag,
    Sequence, SequenceItem, Tag, TagImplication,
)
from media_compost.prefilter import (
    CompilePrep, count_items_with_tag, effective_tag_counts,
)
from media_compost.resolve import effective_for_items


def _old_counts(s):
    """The pre-change tags.py fold, frozen as the oracle."""
    eff = effective_for_items(s)
    pos_by_item = {iid: set(e.positive) for iid, e in eff.items()}
    direct_by_item = {iid: set(e.direct_positive) for iid, e in eff.items()}
    members_by_seq: dict[int, list[int]] = {}
    for sid, mid in s.execute(
        select(SequenceItem.sequence_id, SequenceItem.item_id)
    ).all():
        members_by_seq.setdefault(sid, []).append(mid)
    for sid, cid in s.execute(select(Sequence.id, Sequence.item_id)).all():
        if cid is None:
            continue
        acc = pos_by_item.setdefault(cid, set())
        for mid in members_by_seq.get(sid, ()):
            e = eff.get(mid)
            if e:
                acc |= e.positive
        # The container's own negative vetoes the fold (`seq_inherited`).
        own = eff.get(cid)
        if own:
            acc -= set(own.direct_negative)
    pos, ind, neg = {}, {}, {}
    for iid, names in pos_by_item.items():
        direct = direct_by_item.get(iid, set())
        for n in names:
            pos[n] = pos.get(n, 0) + 1
            if n not in direct:
                ind[n] = ind.get(n, 0) + 1
    for e in eff.values():
        for n in e.negative:
            neg[n] = neg.get(n, 0) + 1
    return pos, ind, neg


def _build(s, rng: random.Random) -> list[str]:
    tags = [Tag(name=f"t{i}") for i in range(10)]
    s.add_all(tags)
    s.flush()
    tags[9].alias_of_id = tags[0].id
    edges = set()
    for _ in range(8):
        a, b = rng.sample(tags[:8], 2)
        edges.add((a.id, b.id))
    c1, c2 = rng.sample(tags[:8], 2)
    edges |= {(c1.id, c2.id), (c2.id, c1.id)}
    s.add_all([TagImplication(tag_id=a, implies_id=b) for a, b in edges])

    groups = [Group(name=f"g{i}", uid=f"cg{i}") for i in range(4)]
    s.add_all(groups)
    s.flush()
    s.add(GroupParent(group_id=groups[1].id, parent_group_id=groups[0].id))
    for g in groups[:3]:
        for t in rng.sample(tags[:8], rng.randint(0, 2)):
            s.add(GroupTag(group_id=g.id, tag_id=t.id,
                           negative=rng.random() < 0.3))

    items = [Item(uid=f"c{i}", name=f"i{i}", kind="image")
             for i in range(25)]
    conts = [Item(uid=f"cs{i}", name=f"seq{i}", kind="sequence")
             for i in range(2)]
    s.add_all(items + conts)
    s.flush()
    for ci, cont in enumerate(conts):
        seq = Sequence(uid=f"cseq{ci}", name=f"s{ci}", kind="comic",
                       item_id=cont.id)
        s.add(seq)
        s.flush()
        for pos_, member in enumerate(rng.sample(items, 5)):
            s.add(SequenceItem(sequence_id=seq.id, item_id=member.id,
                               position=pos_))
        if rng.random() < 0.5:  # a container with its own direct tag too
            s.add(ItemTag(item_id=cont.id, tag_id=tags[0].id,
                          negative=False))
    for it in items:
        for t in rng.sample(tags[:8], rng.randint(0, 3)):
            s.add(ItemTag(item_id=it.id, tag_id=t.id,
                          negative=rng.random() < 0.25))
        for g in rng.sample(groups, rng.randint(0, 2)):
            s.add(ItemGroup(item_id=it.id, group_id=g.id))
    s.flush()
    return [t.name for t in tags]


def test_effective_tag_counts_match_old_fold():
    for seed in range(20):
        rng = random.Random(seed)
        db = Database.in_memory()
        with db.session() as s:
            names = _build(s, rng)
            want_pos, want_ind, want_neg = _old_counts(s)
            got_pos, got_ind, got_neg = effective_tag_counts(s)
            for n in names:
                assert got_pos.get(n, 0) == want_pos.get(n, 0), (
                    f"seed {seed} pos {n}")
                assert got_ind.get(n, 0) == want_ind.get(n, 0), (
                    f"seed {seed} ind {n}")
                assert got_neg.get(n, 0) == want_neg.get(n, 0), (
                    f"seed {seed} neg {n}")


def test_count_items_with_tag_no_containers_matches_plain_fold():
    for seed in range(10):
        rng = random.Random(100 + seed)
        db = Database.in_memory()
        with db.session() as s:
            names = _build(s, rng)
            eff = effective_for_items(s)
            prep = CompilePrep(s)
            for n in names:
                want = sum(1 for e in eff.values() if n in e.positive)
                got = count_items_with_tag(s, n, prep=prep, containers=False)
                assert got == want, f"seed {seed} tag {n}"


def test_a_special_tag_is_counted_over_its_candidates_not_the_library():
    """The per-tag COUNT must be DRIVEN by the tag's own assignments.

    `SELECT count(*) FROM items WHERE <clause>` is a scan of the library
    however few items carry the tag — 0.74 s each at a million items, and
    the tags list runs one per tag a group grants or an implication targets,
    which made a library with 100 implications take 42 SECONDS to list its
    tags. The clause still decides; what changed is that it is asked of the
    items that could possibly match (`prefilter._tag_candidates`) instead of
    all of them, which is a proven superset and 40x fewer rows.
    """
    import random

    from sqlalchemy import event as sa_event

    rng = random.Random(7)
    db = Database.in_memory()
    seen: list[str] = []

    def rec(conn, cur, statement, params, context, many):
        seen.append(" ".join(statement.split()))

    with db.session() as s:
        _build(s, rng)
        prep = CompilePrep(s)
        # A tag something implies INTO — the special case, and the one that
        # used to scan.
        special = next(
            n for t, n in s.execute(select(Tag.id, Tag.name)).all()
            if t in {b for _, b in prep.implication_edges})
        sa_event.listen(db.engine, "before_cursor_execute", rec)
        try:
            count_items_with_tag(s, special, prep=prep)
        finally:
            sa_event.remove(db.engine, "before_cursor_execute", rec)
        # THE COUNT OF ITEMS, not every count the compile made: choosing a
        # tag clause's shape now asks how many rows the tag has
        # (`prefilter._direct_tag`), which is a count over `item_tags` and
        # is the cheap half of what keeps this one off the library.
        counts = [q for q in seen
                  if q.upper().startswith("SELECT COUNT(")
                  and "ITEMS" in q.upper().replace("ITEM_TAGS", "")]
    assert counts, seen
    for q in counts:
        assert "FROM (SELECT" in q and "JOIN items" in q, (
            "the count is driven by the items table rather than by the "
            f"tag's own candidates:\n{q}")


def test_counts_without_containers_matches_the_per_tag_count():
    """The bulk version the subjects/places/events lists use — one GROUP BY
    plus per-tag COUNTs only for the special set — against the per-tag call
    it replaced, over the same randomized grants/implications/aliases."""
    from media_compost.prefilter import counts_without_containers

    for seed in range(10):
        rng = random.Random(200 + seed)
        db = Database.in_memory()
        with db.session() as s:
            names = _build(s, rng)
            prep = CompilePrep(s)
            got = counts_without_containers(s, names)
            for n in names:
                want = count_items_with_tag(s, n, prep=prep, containers=False)
                assert got.get(n, 0) == want, f"seed {seed} tag {n}"
