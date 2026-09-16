"""The structured condition evaluator (media_compost.query.evaluate)."""

from __future__ import annotations

from media_compost.query import (
    Group, LinkCond, LinkTagRef, MetaCond, MetaVal, QueryCtx, SubjectCond,
    TagCond,
    evaluate, num_tolerance, referenced_indexed_meta, references_links,
)


def ctx(**kw) -> QueryCtx:
    return QueryCtx(**kw)


# ---- tags: four polarity states -------------------------------------------

def test_tag_polarity_states():
    c = ctx(tags=frozenset({"portrait"}), neg=frozenset({"blurred"}))
    # has + positive
    assert evaluate(TagCond(name="portrait"), c)
    assert not evaluate(TagCond(name="landscape"), c)
    # has-not + positive  (== !tag)
    assert evaluate(TagCond(name="landscape", have=False), c)
    assert not evaluate(TagCond(name="portrait", have=False), c)
    # has + negative assignment  (== -tag)
    assert evaluate(TagCond(name="blurred", sign="neg"), c)
    assert not evaluate(TagCond(name="portrait", sign="neg"), c)
    # has-not + negative  (== !-tag)
    assert evaluate(TagCond(name="portrait", have=False, sign="neg"), c)
    assert not evaluate(TagCond(name="blurred", have=False, sign="neg"), c)


def test_tag_name_case_insensitive():
    c = ctx(tags=frozenset({"portrait"}))
    assert evaluate(TagCond(name="Portrait"), c)


# ---- groups: and / or / none (neg) ----------------------------------------

def test_groups_and_or_none():
    c = ctx(tags=frozenset({"a", "b"}))
    assert evaluate(Group(op="and", children=[TagCond(name="a"), TagCond(name="b")]), c)
    assert not evaluate(Group(op="and", children=[TagCond(name="a"), TagCond(name="z")]), c)
    assert evaluate(Group(op="or", children=[TagCond(name="a"), TagCond(name="z")]), c)
    # None (neg or) — matches only when NONE of the children match.
    none_ab = Group(op="or", neg=True, children=[TagCond(name="a"), TagCond(name="z")])
    assert not evaluate(none_ab, c)  # 'a' matches -> none fails
    none_xy = Group(op="or", neg=True, children=[TagCond(name="x"), TagCond(name="z")])
    assert evaluate(none_xy, c)
    # Empty root matches everything.
    assert evaluate(Group(), c)


# ---- metadata: intrinsic (nums) + indexed (typed) -------------------------

def test_meta_intrinsic_numeric():
    c = ctx(nums={"width": 1920.0})
    assert evaluate(MetaCond(name="width", op=">=", value=800), c)
    assert not evaluate(MetaCond(name="width", op="<", value=800), c)


def typed(name: str, op: str, literal: str) -> MetaCond:
    """A numeric condition as the frontend sends it: the value as a number,
    plus the window its typed precision implies."""
    return MetaCond(name=name, op=op, value=float(literal),
                    tol=num_tolerance(literal))


def test_num_tolerance_is_half_the_last_typed_decimal():
    assert num_tolerance("0.7") == 0.05
    assert num_tolerance("0.75") == 0.005
    assert num_tolerance("0.750") == 0.0005   # trailing zeros mean precision
    assert num_tolerance("800") == 0.5
    assert num_tolerance("1e3") == 0.0        # exponent form: compare exactly


def test_meta_numeric_equality_tolerance_follows_typed_precision():
    """`resolution=0.7` means "about 0.7" (±0.05); `=0.75` narrows it to
    ±0.005 — a value matches when it would ROUND to what was searched for."""
    def res(v):  # an item with this resolution (megapixels)
        return ctx(nums={"resolution": v})

    for value in (0.65, 0.68, 0.7, 0.74, 0.749):
        assert evaluate(typed("resolution", "=", "0.7"), res(value)), value
    for value in (0.64, 0.75, 0.8):
        assert not evaluate(typed("resolution", "=", "0.7"), res(value)), value

    # One more decimal = a ten times tighter window.
    for value in (0.745, 0.75, 0.754, 0.7549):
        assert evaluate(typed("resolution", "=", "0.75"), res(value)), value
    for value in (0.744, 0.755, 0.7):
        assert not evaluate(typed("resolution", "=", "0.75"), res(value)), value

    # != is the exact complement of =.
    assert evaluate(typed("resolution", "!=", "0.75"), res(0.7))
    assert not evaluate(typed("resolution", "!=", "0.75"), res(0.752))

    # Whole numbers tolerate ±0.5 ("about 8 megapixels")…
    assert evaluate(typed("resolution", "=", "8"), ctx(nums={"resolution": 8.4}))
    assert not evaluate(typed("resolution", "=", "8"), ctx(nums={"resolution": 8.6}))
    # …which leaves integer-valued fields behaving exactly as before.
    assert evaluate(typed("width", "=", "1920"), ctx(nums={"width": 1920.0}))
    assert not evaluate(typed("width", "=", "1920"), ctx(nums={"width": 1921.0}))


def test_meta_numeric_equality_without_tolerance_is_exact():
    """A condition built by hand (scripting) carries no window and compares
    exactly — the fuzziness comes from what the user typed, not from the op."""
    c = ctx(nums={"resolution": 0.74})
    assert not evaluate(MetaCond(name="resolution", op="=", value=0.7), c)
    assert evaluate(MetaCond(name="resolution", op="=", value=0.74), c)


def test_meta_numeric_ordered_ops_stay_strict():
    """Only equality is fuzzy — a range filter must not silently widen."""
    c = ctx(nums={"aspect": 0.74})
    assert not evaluate(typed("aspect", ">", "0.7"), ctx(nums={"aspect": 0.7}))
    assert evaluate(typed("aspect", ">", "0.7"), c)
    assert not evaluate(typed("aspect", "<", "0.7"), c)
    assert evaluate(typed("aspect", "<=", "0.74"), c)


def test_meta_indexed_numeric_equality_tolerance():
    """The same rule applies to indexed (static) metadata, not just intrinsics."""
    c = ctx(meta={"exposure": [MetaVal(mtype="numeric", num=2.24)]})
    assert evaluate(typed("exposure", "=", "2.2"), c)
    assert not evaluate(typed("exposure", "=", "2.25"), c)
    assert evaluate(typed("exposure", "=", "2.24"), c)


def test_meta_first_and_last_import_date_filterable():
    # Both the first (import_date, from created_at) and last (last_import_date)
    # import dates are intrinsic filterable names, evaluated from the item's
    # YYYYMMDDHHMMSS date numbers.
    from media_compost.db import File
    from media_compost.metadata_catalog import (
        INTRINSIC_NAMES, intrinsic_nums,
    )
    assert {"import_date", "last_import_date"} <= INTRINSIC_NAMES

    from datetime import datetime
    af = File(width=100, height=100)
    nums = intrinsic_nums(
        af, datetime(2026, 7, 8, 12, 0, 0), datetime(2026, 7, 6, 9, 30, 0)
    )
    assert nums["import_date"] == 20260706093000.0         # created_at (first)
    assert nums["last_import_date"] == 20260708120000.0    # last_imported_at

    c = ctx(nums=nums)
    assert evaluate(MetaCond(name="import_date", op="<", value=20260707000000), c)
    assert not evaluate(MetaCond(name="last_import_date", op="<", value=20260707000000), c)


def test_meta_date_precision_and_separators():
    # An item imported 2026-07-12 22:12:16.
    c = ctx(nums={"import_date": 20260712221216.0})
    # Exact second (14 digits) matches; a different second doesn't.
    assert evaluate(MetaCond(name="import_date", op="=", value=20260712221216), c)
    assert not evaluate(MetaCond(name="import_date", op="=", value=20260712221217), c)
    # Day precision (8 digits) matches the whole day; a different day doesn't.
    assert evaluate(MetaCond(name="import_date", op="=", value=20260712), c)
    assert not evaluate(MetaCond(name="import_date", op="=", value=20260713), c)
    # Month + year precision.
    assert evaluate(MetaCond(name="import_date", op="=", value=202607), c)
    assert not evaluate(MetaCond(name="import_date", op="=", value=202608), c)
    assert evaluate(MetaCond(name="import_date", op="=", value=2026), c)
    # Separated forms (hyphens / T / colons) parse identically.
    assert evaluate(MetaCond(name="import_date", op="=", value="2026-07-12"), c)
    assert evaluate(MetaCond(name="import_date", op="=", value="2026-07-12T22:12:16"), c)
    assert not evaluate(MetaCond(name="import_date", op="=", value="2026-07-13"), c)
    # Ordered ops compare against the edge of the period: "> 2026-07-12" (the day)
    # is false (the item is inside that day), "< 2026-07-13" is true.
    assert not evaluate(MetaCond(name="import_date", op=">", value="2026-07-12"), c)
    assert evaluate(MetaCond(name="import_date", op=">=", value="2026-07-12"), c)
    assert evaluate(MetaCond(name="import_date", op="<", value="2026-07-13"), c)
    assert not evaluate(MetaCond(name="import_date", op="<", value="2026-07-12"), c)


def test_meta_intrinsic_text_type():
    # The item's media type is an intrinsic *text* metadata name (case-insensitive).
    c = ctx(texts={"type": "video"})
    assert evaluate(MetaCond(name="type", mtype="text", op="=", value="Video"), c)
    assert not evaluate(MetaCond(name="type", mtype="text", op="=", value="image"), c)
    assert evaluate(MetaCond(name="type", mtype="text", op="!=", value="image"), c)


def test_meta_indexed_text_ops():
    c = ctx(meta={"camera_make": [MetaVal("text", text="Canon EOS")]})
    assert evaluate(MetaCond(name="camera_make", mtype="text", op="~", value="canon"), c)
    assert not evaluate(MetaCond(name="camera_make", mtype="text", op="=", value="canon"), c)
    assert evaluate(MetaCond(name="camera_make", mtype="text", op="!~", value="nikon"), c)


def test_meta_absent_value():
    c = ctx()  # no metadata at all
    assert not evaluate(MetaCond(name="camera_make", mtype="text", op="=", value="x"), c)
    # "is not" / "doesn't contain" hold for an absent value.
    assert evaluate(MetaCond(name="camera_make", mtype="text", op="!=", value="x"), c)
    assert evaluate(MetaCond(name="camera_make", mtype="text", op="!~", value="x"), c)


def test_meta_indexed_date_numeric_compare():
    c = ctx(meta={"date_taken": [MetaVal("date", num=20200115143000.0)]})
    assert evaluate(MetaCond(name="date_taken", mtype="date", op=">", value=20200101000000), c)
    assert not evaluate(MetaCond(name="date_taken", mtype="date", op="<", value=20200101000000), c)


# ---- links: direction + required/excluded tags ----------------------------

def test_link_any_and_none():
    c = ctx(out_links=[frozenset({"crop"})])
    assert evaluate(LinkCond(direction="has"), c)
    assert not evaluate(LinkCond(direction="hasnot"), c)
    empty = ctx()
    assert not evaluate(LinkCond(direction="has"), empty)
    assert evaluate(LinkCond(direction="hasnot"), empty)


def test_link_required_and_excluded_tags():
    # One relationship carries {crop, edit}; another carries {crop}.
    c = ctx(out_links=[frozenset({"crop", "edit"}), frozenset({"crop"})])
    # require crop -> matches (either rel)
    assert evaluate(LinkCond(direction="has", link_tags=[LinkTagRef(name="crop")]), c)
    # require crop, exclude edit -> only the {crop} rel qualifies -> matches
    assert evaluate(LinkCond(direction="has", link_tags=[
        LinkTagRef(name="crop"), LinkTagRef(name="edit", exclude=True)]), c)
    # require crop+edit but exclude edit -> impossible per relationship
    assert not evaluate(LinkCond(direction="has", link_tags=[
        LinkTagRef(name="crop"), LinkTagRef(name="edit"),
        LinkTagRef(name="edit", exclude=True)]), c)


def test_link_incoming_direction():
    c = ctx(in_links=[frozenset({"variant"})])
    assert evaluate(LinkCond(direction="linkedby"), c)
    assert not evaluate(LinkCond(direction="notlinkedby"), c)
    assert not evaluate(LinkCond(direction="has"), c)  # no outgoing


# ---- tree inspection -------------------------------------------------------

def test_tree_inspection_helpers():
    tree = Group(op="and", children=[
        TagCond(name="a"),
        MetaCond(name="width", op=">", value=1),        # intrinsic
        MetaCond(name="camera_make", mtype="text", op="=", value="x"),  # indexed
        LinkCond(direction="has"),
    ])
    assert referenced_indexed_meta(tree)
    assert references_links(tree)
    # A tree with only intrinsic meta needs no index load.
    intrinsic_only = Group(children=[MetaCond(name="width", op=">", value=1)])
    assert not referenced_indexed_meta(intrinsic_only)
    assert not references_links(intrinsic_only)


def test_group_condition_eval():
    from media_compost.query import Group, GroupCond, QueryCtx, evaluate

    # The condition reads the PATH sets (a group is its full path); the
    # name sets ride along for the facets.
    ctx = QueryCtx(groups=frozenset({"samples", "my folder"}),
                   group_ancestors=frozenset({"parent"}),
                   group_paths=frozenset({"parent/samples", "my folder"}),
                   group_ancestor_paths=frozenset({"parent"}))
    assert evaluate(GroupCond(name="Parent/samples"), ctx)
    assert not evaluate(GroupCond(name="samples"), ctx)  # not at the root
    assert evaluate(GroupCond(name="My Folder"), ctx)  # case-insensitive
    assert not evaluate(GroupCond(name="other"), ctx)
    assert evaluate(GroupCond(name="other", mode="hasnot"), ctx)
    assert not evaluate(GroupCond(name="parent/samples", mode="hasnot"), ctx)
    # "has" is the group AND everything under it (what selecting it in the
    # sidebar shows); "only" is the group itself.
    assert evaluate(GroupCond(name="Parent"), ctx)
    assert not evaluate(GroupCond(name="Parent", mode="hasnot"), ctx)
    assert evaluate(GroupCond(name="Parent/samples", mode="only"), ctx)
    assert not evaluate(GroupCond(name="Parent", mode="only"), ctx)
    assert evaluate(GroupCond(name="Parent", mode="notonly"), ctx)
    assert not evaluate(GroupCond(name="Parent/samples", mode="notonly"), ctx)
    # Wire-format round trip (type discriminator "ingroup").
    tree = Group.model_validate({
        "type": "group", "op": "and", "neg": False,
        "children": [{"type": "ingroup", "name": "parent/samples", "mode": "has"}],
    })
    assert evaluate(tree, ctx)
    assert not evaluate(tree, QueryCtx())


def test_load_group_sets_includes_ancestors(lib):
    from media_compost.db import Group as DbGroup, GroupParent, Item, ItemGroup
    from media_compost.searchctx import load_group_sets

    cfg, db, store = lib
    with db.session() as s:
        parent = DbGroup(name="Parent")
        child = DbGroup(name="Child")
        other = DbGroup(name="Other")
        item = Item(name="x", kind="image")
        loner = Item(name="y", kind="image")
        s.add_all([parent, child, other, item, loner])
        s.flush()
        s.add(GroupParent(group_id=child.id, parent_group_id=parent.id))
        s.add(ItemGroup(item_id=item.id, group_id=child.id))
        s.commit()
        direct, ancestors, dpaths, apaths = load_group_sets(
            s, [item.id, loner.id])
        # Direct membership and the strict-ancestor chain, separately.
        assert direct[item.id] == frozenset({"child"})
        assert ancestors[item.id] == frozenset({"parent"})
        assert loner.id not in direct and loner.id not in ancestors
        # ... and the same two as PATHS, which is what tells one "child"
        # from another when two branches each hold one.
        assert dpaths[item.id] == frozenset({"parent/child"})
        assert apaths[item.id] == frozenset({"parent"})
        assert loner.id not in dpaths and loner.id not in apaths


def test_tag_and_caption_count_metadata():
    from media_compost.query import MetaCond, QueryCtx, evaluate

    ctx = QueryCtx(nums={"tag_count": 3.0, "caption_count": 0.0})
    assert evaluate(MetaCond(name="tag_count", op=">=", value=3), ctx)
    assert not evaluate(MetaCond(name="tag_count", op=">", value=3), ctx)
    assert evaluate(MetaCond(name="caption_count", op="=", value=0), ctx)


# ---- subjects: the assignment's state, which nothing covered ---------------
#
# `subject:` is what a tag cannot say — how old somebody was, or when the
# picture is from. These tests are the net under the change that lets a FACE
# carry its own date, so the widening is visible rather than silent.

def _subj(**states) -> QueryCtx:
    """States are given as one tuple for brevity; the context holds a list,
    because one picture can claim several (see `load_subject_sets`)."""
    return ctx(subjects={k: (v if isinstance(v, list) else [v])
                         for k, v in states.items()})


def test_subject_presence_and_absence():
    c = _subj(alice=(None, None))
    assert evaluate(SubjectCond(name="alice"), c)
    assert not evaluate(SubjectCond(name="bob"), c)
    assert evaluate(SubjectCond(name="bob", have=False), c)
    # An empty name asks whether the item has ANY subject at all.
    assert evaluate(SubjectCond(), c)
    assert not evaluate(SubjectCond(), ctx())
    assert evaluate(SubjectCond(have=False), ctx())


def test_subject_name_is_case_insensitive():
    assert evaluate(SubjectCond(name="Alice"), _subj(alice=(None, None)))


def test_a_state_bound_only_ever_narrows():
    """An assignment nobody dated cannot satisfy "aged 10 to 14" — the honest
    answer is that we do not know, and that must not read as a match."""
    undated = _subj(alice=(None, None))
    assert evaluate(SubjectCond(name="alice"), undated)
    assert not evaluate(SubjectCond(name="alice", age_from=10, age_to=14), undated)
    assert not evaluate(SubjectCond(name="alice", date_from=19100000), undated)
    # ...and "has not, in that state" is therefore true.
    assert evaluate(SubjectCond(name="alice", age_from=10, have=False), undated)


def test_subject_age_bounds():
    c = _subj(alice=(None, 12))
    assert evaluate(SubjectCond(name="alice", age_from=10, age_to=14), c)
    assert evaluate(SubjectCond(name="alice", age_from=12, age_to=12), c)
    assert not evaluate(SubjectCond(name="alice", age_from=13), c)
    assert not evaluate(SubjectCond(name="alice", age_to=11), c)


def test_subject_date_is_compared_by_what_the_partial_date_COVERS():
    """A picture dated "1921" is inside 1910..1920 only if the whole year is —
    partial dates are ranges, not points."""
    c = _subj(alice=(19210000, None))
    assert not evaluate(SubjectCond(name="alice", date_from=19100000,
                                    date_to=19200000), c)
    assert evaluate(SubjectCond(name="alice", date_from=19100000,
                                date_to=19300000), c)
    # A whole year covers every day in it.
    assert evaluate(SubjectCond(name="alice", date_from=19210615), c)


def test_a_bound_matches_when_ANY_subject_is_in_that_state():
    """With no name, the bound is about the item, not about one person."""
    c = _subj(alice=(None, 12), bob=(None, 40))
    assert evaluate(SubjectCond(age_from=35), c)
    assert evaluate(SubjectCond(age_to=15), c)
    assert not evaluate(SubjectCond(age_from=60), c)


def test_several_states_for_one_subject_each_get_a_chance():
    """A page showing somebody at six and at twelve answers both questions.
    Neither state is truer than the other, so a bound matches when ANY does."""
    c = ctx(subjects={"kaguya": [(None, 6), (None, 12)]})
    assert evaluate(SubjectCond(name="kaguya", age_from=5, age_to=7), c)
    assert evaluate(SubjectCond(name="kaguya", age_from=11, age_to=13), c)
    assert not evaluate(SubjectCond(name="kaguya", age_from=20), c)
