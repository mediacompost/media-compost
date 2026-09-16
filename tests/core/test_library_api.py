"""The public Python API.

Replaces `test_scripting.py`. The three cases that file carried are kept —
`test_a_subject_and_a_place_condition_mean_here_what_they_mean_in_the_app`
especially, which encodes a real bug (a `QueryCtx` built without `subjects=`
or `places=`, so every such condition quietly evaluated false and a scripted
export selected nothing with no error to read). It has to keep guarding the
new query path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from media_compost import (
    NEVER, AmbiguousName, DuplicateName, InvalidTagName, NotFound,
    ObjectDeleted, PartialDate, ReadOnlyError, Rect, TimeRange, TagCond,
    open_library,
)
from tests.core.conftest import make_image, make_jpeg_with_exif


@pytest.fixture
def lib(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    make_jpeg_with_exif(src / "a.jpg", seed=1)
    make_jpeg_with_exif(src / "b.jpg", seed=2)
    with open_library(tmp_path / "data", user="alice") as handle:
        handle.import_all([src / "a.jpg", src / "b.jpg"])
        yield handle


@pytest.fixture
def item(lib):
    return lib.query().first()


# ---- opening ---------------------------------------------------------------


def test_open_library_is_a_context_manager(tmp_path: Path):
    with open_library(tmp_path / "data") as handle:
        assert handle.path == (tmp_path / "data").resolve()
        assert len(handle.items) == 0


def test_a_read_only_library_refuses_every_write(tmp_path: Path, item):
    path = item._lib.path
    with open_library(path, mode="r") as ro:
        got = ro.query().first()
        assert got is not None            # reading is fine
        assert sorted(got.effective_tags) == []
        with pytest.raises(ReadOnlyError):
            got.tags.add("nope")
        with pytest.raises(ReadOnlyError):
            got.name = "nope"


def test_a_nonsense_mode_says_why(tmp_path: Path):
    with pytest.raises(ValueError, match="cannot be truncated"):
        open_library(tmp_path / "data", mode="w")


# ---- items and tags --------------------------------------------------------


def test_an_item_reads_like_an_object(item):
    assert item.uid and len(item.uid) == 32
    assert item.kind == "image"
    assert item.width == 640 and item.height == 480
    assert item.path is not None and item.path.exists()
    item.name = "Renamed"
    assert item.name == "Renamed"


def test_tags_are_a_set_and_writing_to_it_is_the_write(item):
    item.tags.add("portrait")
    item.tags.add("temple")
    assert "portrait" in item.tags
    assert len(item.tags) == 2
    assert sorted(item.tags) == ["portrait", "temple"]
    item.tags.discard("temple")
    assert sorted(item.tags) == ["portrait"]
    item.tags |= {"a", "b"}
    assert sorted(item.tags) == ["a", "b", "portrait"]


def test_a_negative_tag_is_the_sibling_set(item):
    item.tags.negative.add("blurry")
    assert "blurry" in item.tags.negative
    assert "blurry" not in item.tags
    assert "blurry" in item.effective_neg_tags


def test_effective_tags_are_read_only_and_include_what_is_implied(lib, item):
    lib.tags.create("poodle").implies.add("dog")
    item.tags.add("poodle")
    assert "dog" in item.effective_tags
    assert "dog" not in item.tags          # nobody assigned it
    with pytest.raises(AttributeError):
        item.effective_tags.add("cat")     # frozenset says so itself


def test_explain_says_where_a_tag_came_from(lib, item):
    lib.tags.create("poodle").implies.add("dog")
    item.tags.add("poodle")
    group = lib.groups.create("Dogs")
    item.groups.add(group)
    group.tags.add("pet")

    assert item.tags.explain("poodle").direct
    implied = item.tags.explain("dog")
    assert not implied.direct and implied.implied_by == ("poodle",)
    granted = item.tags.explain("pet")
    assert not granted.direct and [g.name for g in granted.from_groups] == ["Dogs"]


def test_a_group_grant_reaches_the_whole_subtree(lib, item):
    trips = lib.groups.create("Trips")
    japan = lib.groups.create("Japan", parent=trips)
    item.groups.add(japan)
    assert japan.path == "Trips/Japan"
    trips.tags.add("travel")
    assert "travel" in item.effective_tags


def test_a_smart_group_is_the_documented_example(lib, item):
    """The `docs/python-api.md` smart-group snippet, run: create with a
    query, members follow it, `add` refuses, and smart is an identity —
    emptying the rule keeps the group smart, holding nothing."""
    import pytest

    item.tags.add("cat")
    g = lib.groups.create("Cats", smart_query="cat")
    assert g.smart and g.smart_query == "cat"
    assert [i.id for i in g.items] == [item.id]
    other = [i for i in lib.query() if i.id != item.id][0]
    with pytest.raises(Exception):
        g.add(other)
    g.smart_query = ""
    assert g.smart                       # identity, not a state
    assert list(g.items) == []           # an empty rule holds nothing
    plain = lib.groups.create("Plain")
    with pytest.raises(Exception):
        plain.smart_query = "cat"        # an ordinary group never converts


def test_a_group_cannot_be_moved_under_itself(lib):
    from media_compost import GroupCycleError

    root = lib.groups.create("Root")
    child = lib.groups.create("Child", parent=root)
    with pytest.raises(GroupCycleError):
        root.parent = child


# ---- the tag catalog -------------------------------------------------------


def test_the_tag_catalog_is_a_mapping_and_a_read_never_creates(lib):
    lib.tags.create("portrait")
    assert "portrait" in lib.tags
    assert list(lib.tags) == ["portrait"]          # iterating yields KEYS
    assert lib.tags["portrait"].name == "portrait"
    with pytest.raises(NotFound):
        lib.tags["nope"]
    assert "nope" not in lib.tags                  # ...and did not create it
    assert lib.tags.get("nope") is None


def test_assigning_a_tag_mints_it_but_looking_one_up_does_not(lib, item):
    item.tags.add("brand_new")
    assert "brand_new" in lib.tags


def test_what_the_catalog_says_about_a_tag(lib, item):
    """`tag.meta_tags` is the documented example, run — the rule this file
    exists for. And `meta_map()` beside it, which answers for the whole
    catalog in one statement where the handle is a query per tag."""
    tag = lib.tags.create("text")
    tag.meta_tags.add("noflip")
    tag.meta_tags.add("character")
    assert sorted(tag.meta_tags) == ["character", "noflip"]
    tag.meta_tags.remove("character")
    assert sorted(tag.meta_tags) == ["noflip"]

    lib.tags.create("logo").meta_tags.add("noflip")
    assert lib.tags.meta_map() == {"text": {"noflip"}, "logo": {"noflip"}}

    # It never reaches the picture: what it changes is what can be ASKED.
    item.tags.add("text")
    assert "noflip" not in item.tags
    assert [i.id for i in lib.query("TAG:noflip")] == [item.id]
    assert [i.id for i in lib.query("TAG:nothing")] == []


def test_a_duplicate_name_is_refused_and_merge_is_the_other_answer(lib, item):
    lib.tags.create("cat")
    with pytest.raises(DuplicateName):
        lib.tags.create("cat")
    item.tags.add("cat")
    lib.tags.create("feline")
    lib.tags["cat"].merge_into(lib.tags["feline"])
    assert "feline" in item.tags


def test_a_name_the_api_would_change_is_refused_not_fixed(item):
    with pytest.raises(InvalidTagName):
        item.tags.add("two words")
    with pytest.raises(InvalidTagName):
        item.tags.add("tab\tinside")
    # …but a colon is not one of those, wherever it stands: interior colons are
    # kept, however many (see `tagname.normalize`), and so are a LEADING and a
    # TRAILING one (owner decision: the booru emoticons `:d`, `:o` and `d:`,
    # `c:`, which a rule that ate the colon turned into bare letters).
    item.tags.add("costume:hat:straw")
    assert "costume:hat:straw" in item.tags
    item.tags.add(":leading")
    assert ":leading" in item.tags
    item.tags.add("trailing:")
    assert "trailing:" in item.tags
    item.tags.add("d:")
    assert "d:" in item.tags


# ---- querying --------------------------------------------------------------


def test_a_query_takes_a_string_a_condition_tree_or_nothing(lib, item):
    item.tags.add("portrait")
    assert len(lib.query()) == 2
    assert [i.id for i in lib.query("portrait")] == [item.id]
    # A bare condition and a list of them (an implicit AND) are both trees.
    assert [i.id for i in lib.query(TagCond(name="portrait"))] == [item.id]
    assert [i.id for i in lib.query([TagCond(name="portrait")])] == [item.id]
    assert len(lib.query("!portrait")) == 1


def test_an_itemset_counts_slices_and_refines(lib, item):
    item.tags.add("portrait")
    every = lib.query()
    assert len(every) == 2 and bool(every)
    assert len(every[:1]) == 1
    assert every.filter("portrait").one().id == item.id
    assert len(every.exclude("portrait")) == 1
    assert item in every


def test_metadata_conditions_read_the_indexed_exif(lib, item):
    assert item.metadata["camera_make"] == "TestMake"
    assert item.metadata["width"] == 640.0
    assert len(lib.query("INFO:width>=600")) == 2
    assert len(lib.query("INFO:width>=800")) == 0
    assert len(lib.query('INFO:camera_make~Test')) == 2


def test_a_subject_and_a_place_condition_mean_here_what_they_mean_in_the_app(
    lib, item,
):
    """They used to match NOTHING. `QueryCtx` was built without `subjects=` or
    `places=`, so both fields defaulted empty and every such condition quietly
    evaluated false — a scripted export selecting no items, with no error to
    read, while the same query worked in the search field."""
    alice = lib.create_subject("Alice", since="1975")
    item.tags.add(alice.tag.name)
    # ONE text field. A `place.` condition naming anything else — the old
    # `country`, `city`, `street` — reads the address, which is where those
    # words live now.
    tokyo = lib.create_place(name="Tokyo, Japan")
    item.tags.add(tokyo.tag.name)

    assert [i.id for i in lib.query("SUBJECT:")] == [item.id]
    assert [i.id for i in lib.query(f"SUBJECT:{alice.tag.name}")] == [item.id]
    assert [i.id for i in lib.query("PLACE:Japan")] == [item.id]
    # And a bound still narrows: nobody dated this assignment.
    assert len(lib.query("SUBJECT:#10..14")) == 0


def test_bulk_writes_are_one_pass_not_one_per_item(lib):
    assert lib.query().add_tags("reviewed") == 2
    assert len(lib.query("reviewed")) == 2
    assert lib.query().remove_tags("reviewed") == 2
    assert len(lib.query("reviewed")) == 0


# ---- files -----------------------------------------------------------------


def test_a_file_gives_its_path_and_its_sources(item):
    got = item.active_file
    assert got.path.exists() and got.format == "jpeg"
    assert [s.name for s in got.sources] == [f"{item.name}"]
    src = got.add_url("https://example.com/a.jpg")
    assert src.is_url and src.name == "https://example.com/a.jpg"
    assert len(got.sources) == 2
    src.delete()
    assert len(got.sources) == 1


def test_rotating_turns_the_stored_pixels_not_just_a_flag(item):
    """`File.rotation` is PROVENANCE — which way the bytes sit relative to the
    item's first source file — not a transform to apply. Rotating branches to
    a new file whose pixels are already turned, so `image()` opens the path
    and stops there; rotating by `rotation` on top would turn it twice."""
    before = item.image().size
    item.rotate("right")
    assert item.image().size == (before[1], before[0])
    assert item.active_file.rotation == 90
    assert (item.active_file.width, item.active_file.height) == item.image().size


# ---- people, places, events ------------------------------------------------


def test_a_subject_is_a_tag_with_a_record_on_it(lib, item):
    alice = lib.create_subject("Alice Meyer", comment="the tall one",
                               since="1990-06-14")
    assert alice.tag.name == "subject:alice_meyer"
    assert alice.since == PartialDate.parse("1990-06-14")
    item.tags.add(alice.tag.name)
    assert alice.tag.name in item.effective_tags


def test_a_face_is_named_and_the_name_reaches_the_item(lib, item):
    alice = lib.create_subject("Alice")
    face = item.add_face(0.1, 0.1, 0.2, 0.2)
    assert face.drawn_by_hand and face.det_score is None
    face.name(alice)
    assert [str(s) for s in item.subjects] == ["Alice"]
    assert alice.tag.name in item.effective_tags
    face.unname(alice)
    assert list(item.subjects) == []


def test_detected_text_reads_edits_and_dismisses(lib, item):
    """The docs' "Detected text" section, executed — including the one-liner
    it recommends in place of an `item.text` property."""
    block = item.add_text(0.1, 0.1, 0.5, 0.2, text="hand-typed")
    assert block.drawn_by_hand and block.score is None
    assert block.level == "block" and block.quad == ()
    word = item.add_text(0.1, 0.1, 0.2, 0.2, text="hand", level="word",
                         parent=block)
    assert [w.text for w in block.children] == ["hand"]
    assert word.parent.id == block.id

    block.text = "corrected by script"
    assert block.text == "corrected by script" and block.edited

    block.dismissed = True
    assert block.dismissed
    block.dismissed = False

    img = block.crop()
    assert img.width > 0

    assert "\n".join(b.text for b in item.text_blocks) == "corrected by script"
    assert item.text_models == ()
    assert lib.stats["text_regions"] == 2

    block.move(0.15, 0.1, 0.5, 0.2)
    assert block.rect.x == 0.15
    word.delete()
    assert list(block.children) == []
    block.delete()
    assert list(item.text_blocks) == []


def test_an_appearance_carries_an_age(lib, item):
    alice = lib.create_subject("Alice")
    item.subjects.add(alice)
    ap = item.appearances[0]
    ap.age = 12
    assert ap.age == 12 and not ap.guessed


def test_a_place_is_an_address_a_country_and_what_it_is_inside(lib):
    """One free text line, not eight typed components — and the parent, which
    is what containment is now: assigning the child implies the parents,
    through the ordinary tag implications."""
    japan = lib.create_place(name="Japan")
    place = lib.create_place(name="Center Gai, Shibuya, Tokyo",
                             parent=japan)
    assert place.name == "Center Gai, Shibuya, Tokyo"
    assert place.parent is not None and place.parent.tag.name == japan.tag.name
    # The containment IS an implication — nothing else had to learn about it.
    assert japan.tag.name in list(place.tag.implies)
    place.name = "Dogenzaka, Shibuya"
    assert place.name == "Dogenzaka, Shibuya"
    place.parent = None
    assert place.parent is None
    assert japan.tag.name not in list(place.tag.implies)


def test_an_event_has_a_span(lib):
    con = lib.create_event("Comic-Con", start="2014-07-05", end="2014-07-10")
    assert con.start == PartialDate.parse("2014-07-05")
    assert con.tag.name == "event:comic_con"


# ---- when the picture was taken --------------------------------------------


def test_taken_has_three_states(item):
    assert item.taken is None                      # nobody has said
    item.taken = "2019-04"
    assert item.taken == PartialDate.parse("2019-04")
    assert item.taken_source == "set"
    item.taken = NEVER                             # somebody looked
    assert item.taken is NEVER
    assert item.taken_source == "never"
    item.taken = None                              # back to automatic
    assert item.taken is None


def test_a_typed_date_stores_at_the_columns_full_width(item):
    """``item.taken = "1503"`` used to store the date-width ``15030000``,
    which every fourteen-digit reader of ``items.taken_at`` misread — the
    grid's year grouping divides by 10¹⁰ and filed it under year 0. The ops
    layer widens the value on write; the handle still answers at date width,
    which is what keeps the parse round-trip above true."""
    from media_compost.db import Item as _Item

    item.taken = "1503"
    assert item.taken == PartialDate.parse("1503")
    row = item._lib._session.get(_Item, item._id)
    assert row.taken_at == 15030000000000
    item.taken = "1969-07-20"
    assert row.taken_at == 19690720000000
    assert item.taken == PartialDate.parse("1969-07-20")


# ---- captions, links, sequences --------------------------------------------


def test_a_caption_carries_meta_tags(item):
    cap = item.add_caption("a temple at dusk")
    cap.meta_tags.add("en")
    assert sorted(cap.meta_tags) == ["en"]
    assert cap.text == "a temple at dusk"
    cap.text = "a shrine at dusk"
    assert item.captions[0].text == "a shrine at dusk"


def test_a_link_points_one_way_and_reads_from_both_ends(lib):
    a, b = list(lib.query())
    link = a.links.add(b, kind="manual")
    link.meta_tags.add("same_scene")
    assert [x.other.id for x in a.links] == [b.id]
    assert [x.other.id for x in b.linked_by] == [a.id]
    assert sorted(link.meta_tags) == ["same_scene"]


def test_a_sequence_is_ordered_and_reorderable(lib):
    a, b = list(lib.query())
    seq = lib.create_sequence([a, b], name="Chapter 1")
    assert [m.id for m in seq.members] == [a.id, b.id]
    seq.members.reorder([b, a])
    assert [m.id for m in seq.members] == [b.id, a.id]


# ---- transactions, identity, errors ----------------------------------------


def test_a_transaction_commits_once_and_rolls_back_whole(lib):
    with lib.transaction():
        for it in lib.query():
            it.tags.add("reviewed")
    assert len(lib.query("reviewed")) == 2

    with pytest.raises(RuntimeError):
        with lib.transaction():
            for it in lib.query():
                it.tags.add("half")
            raise RuntimeError("boom")
    assert len(lib.query("half")) == 0


def test_two_lookups_of_one_item_are_equal_and_hashable(lib, item):
    again = lib.items[item.uid]
    assert again == item and hash(again) == hash(item)
    assert len({item, again}) == 1
    assert lib.items[item.id] == item


def test_a_deleted_handle_raises_rather_than_answering(lib, item):
    item.delete()
    with pytest.raises(ObjectDeleted):
        item.name
    assert not item.exists and not bool(item)


def test_an_unknown_uid_is_a_KeyError(lib):
    with pytest.raises(NotFound):
        lib.items["0" * 32]
    with pytest.raises(KeyError):          # NotFound IS one
        lib.items["0" * 32]
    assert lib.items.get("0" * 32) is None


def test_two_groups_of_one_name_need_a_path(lib):
    a = lib.groups.create("Trips")
    b = lib.groups.create("Other")
    lib.groups.create("2019", parent=a)
    lib.groups.create("2019", parent=b)
    with pytest.raises(AmbiguousName):
        lib.groups["2019"]
    assert lib.groups["Trips/2019"].path == "Trips/2019"


# ---- history ---------------------------------------------------------------


def test_history_reads_newest_first_and_reverts(lib, item):
    item.tags.add("portrait")
    newest = lib.history[0]
    assert newest.action == "add_tag" and newest.username == "alice"
    assert newest.source == "cli"
    assert newest.revertible
    assert newest.revert()
    assert "portrait" not in item.tags


def test_the_watermark_pattern_finds_what_a_change_produced(lib, item):
    mark = lib.history[0].id
    item.tags.add("portrait")
    item.tags.add("temple")
    got = lib.history.since(mark)
    assert len(got) == 2
    assert lib.history.revert(got) == 2
    assert sorted(item.tags) == []


# ---- importing -------------------------------------------------------------


def test_import_file_says_where_it_landed(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "one.png", seed=5)
    with open_library(tmp_path / "data") as handle:
        got = handle.import_file(src / "one.png")
        assert got and got.status == "imported"
        assert got.item is not None and got.file is not None
        assert got.item.path.exists()
        # ...and the handle is usable straight away, which is the point.
        got.item.tags.add("scraped")
        got.file.add_url("https://example.com/one.png")
        assert "scraped" in got.item.tags


def test_re_importing_the_same_bytes_reports_a_duplicate(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "one.png", seed=5)
    make_image(src / "copy.png", seed=5)
    with open_library(tmp_path / "data") as handle:
        first = handle.import_file(src / "one.png")
        again = handle.import_file(src / "copy.png")
        assert again.status == "duplicate"
        assert again.item == first.item
        assert len(handle.items) == 1


def test_move_takes_the_source_including_a_duplicate(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "one.png", seed=5)
    make_image(src / "copy.png", seed=5)
    with open_library(tmp_path / "data") as handle:
        handle.import_file(src / "one.png", move=True)
        assert not (src / "one.png").exists()
        # A duplicate stores nothing, but "move it in" is not achieved by
        # leaving the original in the inbox.
        assert handle.import_file(src / "copy.png", move=True).status == "duplicate"
        assert not (src / "copy.png").exists()


def test_a_failed_import_leaves_the_source_alone(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "broken.png").write_bytes(b"not an image")
    with open_library(tmp_path / "data") as handle:
        got = handle.import_file(src / "broken.png", move=True)
        assert not got and got.status == "error"
        assert (src / "broken.png").exists()


def test_import_bytes_records_where_they_came_from(tmp_path: Path):
    from datetime import datetime, timezone

    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "one.png", seed=9)
    data = (src / "one.png").read_bytes()
    when = datetime(2020, 5, 1, 12, 0, tzinfo=timezone.utc)
    with open_library(tmp_path / "data") as handle:
        got = handle.import_bytes(data, "one.png")
        assert got.status == "imported"
        # Provenance is the caller's line, on the result's own file.
        got.file.add_url("https://example.com/one.png", accessed_at=when)
        names = [s.name for s in got.file.sources]
        assert "https://example.com/one.png" in names


def test_an_import_run_shares_one_pass(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(3):
        make_image(src / f"p{i}.png", seed=i + 40)
    with open_library(tmp_path / "data") as handle:
        with handle.importing() as run:
            for i in range(3):
                got = run.add(src / f"p{i}.png")
                got.item.tags.add("batch")
            assert run.stats.imported == 3
        assert len(handle.query("batch")) == 3


def test_item_count_finds_a_tag_a_search_cannot_be_typed_for(tmp_path: Path):
    """`items` goes through the query grammar, which lowercases what it is
    given; the catalog preserves case, because an import can carry it. So a
    mixed-case tag reads as being on nothing — `item_count` matches the name
    as stored and is the number to report."""
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "one.png", seed=44)
    with open_library(tmp_path / "data") as handle:
        got = handle.import_file(src / "one.png")
        got.item.tags.add("Shouting")
        got.item.tags.add("quiet")
        loud, soft = handle.tags["Shouting"], handle.tags["quiet"]
        assert soft.item_count == len(soft.items) == 1
        assert loud.item_count == 1
        assert len(loud.items) == 0, "the trap this exists for"


# ---- surfaces the documentation exercises ----------------------------------
#
# Every one of these was missing or broken until the docs were written against
# the API and each documented call was actually run. They are the reason that
# exercise is worth repeating whenever the doc grows a new example.


def test_a_tags_boxes_can_be_added_and_read(item):
    """`BoxList` declared a `_read` METHOD over `HandleList`'s slot of that
    name, which shadows the slot descriptor — so the base constructor's own
    assignment raised "attribute '_read' is read-only" and no box could ever
    be added."""
    item.tags.add("portrait")
    box = item.tags["portrait"].boxes.add(0.1, 0.2, 0.3, 0.4)
    assert box is not None
    got = list(item.tags["portrait"].boxes)
    assert len(got) == 1
    assert got[0].rect == pytest.approx((0.1, 0.2, 0.3, 0.4))


def test_a_caption_carries_meta_tags(item):
    """The app's caption cards have them; the API had no way to reach them."""
    cap = item.add_caption("a woman in a red coat")
    cap.tags.add("alt-text")
    assert set(cap.tags) == {"alt-text"}
    cap.tags.remove("alt-text")
    assert set(cap.tags) == set()


def test_per_item_tag_groups_can_be_made_and_filled(item):
    grp = item.tag_groups.create("Hers")
    grp.tags.add("blue_eyes")
    assert [g.name for g in item.tag_groups] == ["Hers"]
    assert "blue_eyes" in set(item.tag_groups.one("Hers").tags)
    # A tag placed in a group is still a tag on the item.
    assert "blue_eyes" in item.tags


def test_tag_groups_take_a_name_and_get_or_create(lib, item):
    """The doc's layer-4 line, run verbatim: `tag_groups["Hers"]` used to be
    an id lookup, so the documented example died in `int("Hers")`. A name now
    finds the group or creates it — placing a tag in a named layout is what
    brings the layout into being."""
    item.tag_groups["Hers"].tags.add("blue_eyes")
    assert [g.name for g in item.tag_groups] == ["Hers"]
    assert "blue_eyes" in set(item.tag_groups["Hers"].tags)

    # A second use reuses it — including a spelling that differs only in
    # case, which would otherwise mint a silent duplicate.
    grp = item.tag_groups["Hers"]
    assert item.tag_groups["hers"].id == grp.id
    assert len(item.tag_groups) == 1
    assert "Hers" in item.tag_groups

    # `.get(name)` is the read that never creates; an int is still an id.
    assert item.tag_groups.get("Nope") is None
    assert len(item.tag_groups) == 1
    assert item.tag_groups[grp.id].name == "Hers"

    # A name two groups share is refused rather than picked.
    item.tag_groups.create("Hers")
    with pytest.raises(AmbiguousName):
        item.tag_groups["Hers"]

    # The catalogs that did NOT opt in stay keyed by id, with an error that
    # says so instead of a bare int() ValueError.
    with pytest.raises(TypeError, match="keyed by id"):
        lib.subjects["Alice"]


def test_a_group_path_is_created_whole(lib):
    """Walking the chain by hand is what every caller would otherwise do, and
    the name has to be matched among the level's own CHILDREN — group names
    are not unique, so a library-wide scan would adopt an unrelated "Japan"
    from somewhere else in the tree."""
    made = lib.groups.get_or_create("Trips/2019/Japan")
    assert made.path == "Trips/2019/Japan"
    # Idempotent, and it reuses the levels that already exist.
    again = lib.groups.get_or_create("Trips/2019/Japan")
    assert again.id == made.id
    assert lib.groups.get_or_create("Trips/2019/Korea").parent.id == \
        made.parent.id
    # A same-named group elsewhere is not adopted.
    other = lib.groups.get_or_create("Archive/Japan")
    assert other.id != made.id


def test_a_change_reports_when_it_happened(lib, item):
    item.tags.add("portrait")
    change = lib.history[0]
    assert change.created_at is not None
    assert change.action == "add_tag"
    assert change.username == "alice"
    assert change.source == "cli"


def test_add_takes_the_signs_and_extras_the_docs_promise(item):
    """The set's own sign is a DEFAULT the call can override — one closure
    serves `item.tags` and `item.tags.negative`, and binding the sign
    positionally made `add(name, negative=True)` raise "got multiple values
    for keyword argument 'negative'"."""
    item.tags.add("plain")
    item.tags.add("nope", negative=True)
    assert "plain" in item.tags and "nope" not in item.tags
    assert "nope" in item.tags.negative
    # And the other direction: the negative set can be told to add a positive.
    item.tags.negative.add("yes", negative=False)
    assert "yes" in item.tags
    # The remaining documented extras.
    item.tags.add("boxed", box=(0.1, 0.2, 0.3, 0.4))
    assert len(item.tags["boxed"].boxes) == 1
    item.tags.add("guessed", pending=True)
    assert item.tags["guessed"].pending


def test_an_unknown_add_option_is_refused_rather_than_ignored(item):
    """It used to land in `**kw` and be dropped, so a typo looked like it had
    worked — which is how `box=` stayed unimplemented while being documented."""
    with pytest.raises(TypeError, match="bbox"):
        item.tags.add("x", bbox=(0.1, 0.2, 0.3, 0.4))


def test_pending_is_readable_and_accepting_it_clears_the_group(item):
    """Accepting has to go through the placement path: clearing the flag while
    a copy still sat in an auto-managed Pending group would leave the box
    around the tag saying it was waiting."""
    item.tags.add("guessed", pending=True)
    assert item.tags["guessed"].pending
    assert item.id in lib_pending_ids(item)
    item.tags["guessed"].pending = False
    assert not item.tags["guessed"].pending
    assert "guessed" in item.tags          # accepting keeps the tag


def lib_pending_ids(item):
    return item._lib.pending.ids()


def test_a_face_reports_its_people_and_its_claims_separately(item, lib):
    """`Face.subjects` returned the `Appearance` rows, so the obvious
    `face.subjects[0].display_name` raised. `Item` already had the pair."""
    alice = lib.create_subject("Alice")
    face = item.add_face(0.3, 0.15, 0.25, 0.3)
    face.name(alice)
    assert [s.display_name for s in face.subjects] == ["Alice"]
    assert [a.subject.display_name for a in face.appearances] == ["Alice"]
    assert repr(face)


# ---- artifacts as a cache ---------------------------------------------------


def test_an_artifact_can_be_written_and_found_again_by_its_key(item):
    """The cache round trip: address it, write it, find it. Before this the
    public API could delete an artifact and never make one, so a consumer
    caching derived pixels had to reach into `ItemStore` and the ORM."""
    f = item.active_file
    assert f.find_artifact("degraded") is None
    art = f.add_artifact("degraded", b"jpeg-ish bytes", key="jpeg-q30",
                         ext="jpg", model="jpeg-q30", width=64, height=48)
    assert art.rel_path == f"artifacts/{f.number}-degraded-jpeg-q30.jpg"
    assert art.path.read_bytes() == b"jpeg-ish bytes"
    assert (art.kind, art.model, art.format) == ("degraded", "jpeg-q30", "jpg")
    assert (art.width, art.height, art.bytes) == (64, 48, 14)
    assert art.sha256 and art.file.id == f.id and art.item.id == item.id
    assert f.find_artifact("degraded", model="jpeg-q30").id == art.id


def test_an_artifact_name_is_deterministic_and_creates_nothing(item):
    """It is the cache ADDRESS, so asking twice must give one answer — and
    asking must not make anything. `store.write_artifact` suffixes -2/-3 on a
    clash, which for a cache would pile up copies nobody can find again."""
    f = item.active_file
    first = f.artifact_name("latent", "sd15-512x512", "pt")
    f.add_artifact("latent", b"tensor", key="sd15-512x512", ext="pt")
    assert f.artifact_name("latent", "sd15-512x512", "pt") == first
    assert len(f.artifacts) == 1


def test_cache_name_is_the_string_it_has_always_been():
    """Pinned against literals, because one character of drift silently
    orphans every cached file in every library that already exists — the old
    bytes stay on disk under a name nothing looks for, and everything is
    generated again."""
    from media_compost.ops.artifacts import cache_name

    assert cache_name(3, "latent", "sd15-512x512", "pt") == \
        "artifacts/3-latent-sd15-512x512.pt"
    assert cache_name(3, "latent", "sd15-512x512-f", "pt") == \
        "artifacts/3-latent-sd15-512x512-f.pt"
    assert cache_name(3, "latent", "sdxl-am-1024x1024", "pt") == \
        "artifacts/3-latent-sdxl-am-1024x1024.pt"
    assert cache_name(3, "latent", "sd15-dresize-052-am-768x512", "pt") == \
        "artifacts/3-latent-sd15-dresize-052-am-768x512.pt"
    # A user model's key carries a colon and capitals; a slug is what makes it
    # a filename, and composing the key before slugging must not change it.
    assert cache_name(3, "latent", "user:My Model-512x512", "pt") == \
        "artifacts/3-latent-user-my-model-512x512.pt"
    assert cache_name(9, "degraded", "jpeg-q30-p2", "jpg") == \
        "artifacts/9-degraded-jpeg-q30-p2.jpg"
    assert cache_name(9, "depth") == "artifacts/9-depth.bin"


def test_bytes_another_process_wrote_are_recorded_once(item):
    """A trainer writes its own tensors; the library only indexes them. Twice
    over the same folder must add nothing, and nothing on disk is None rather
    than an empty row."""
    f = item.active_file
    assert f.record_artifact("latent", key="sd15-512x512", ext="pt") is None
    f.artifact_path("latent", "sd15-512x512", "pt").write_bytes(b"tensor")
    got = f.record_artifact("latent", key="sd15-512x512", ext="pt",
                            model="sd15")
    assert got is not None and got.bytes == 6
    assert f.record_artifact("latent", key="sd15-512x512", ext="pt",
                             model="sd15").id == got.id
    assert len(f.artifacts) == 1


def test_an_artifact_made_from_another_is_deleted_with_it(item):
    """`parent` is what makes a latent cached off a degraded copy go when the
    copy does — otherwise the row survives pointing at bytes that are gone."""
    f = item.active_file
    src = f.add_artifact("degraded", b"x", key="k", ext="jpg", model="k")
    f.artifact_path("latent", "k-512x512", "pt").write_bytes(b"t")
    lat = f.record_artifact("latent", key="k-512x512", ext="pt", parent=src)
    assert lat.parent.id == src.id
    src.delete()
    assert len(f.artifacts) == 0


def test_making_a_cache_entry_writes_no_history(item, lib):
    """A cache is not an edit. The logged tier exists for a model's output;
    a materialization run would otherwise write six figures of history
    saying it had warmed a cache, none of it revertible."""
    before = len(lib.history)
    item.active_file.add_artifact("latent", b"t", key="k-64x64", ext="pt")
    assert len(lib.history) == before


# ---- video and hashing ------------------------------------------------------


def test_a_pil_image_can_be_hashed_the_way_the_importer_hashes_files(item):
    """`Phash.of` so a consumer deduping pictures of its OWN — frames it
    sampled, copies it derived — means what the library means by 'the same'.
    Pair it with `phash_threshold` and the two agree by construction."""
    from PIL import Image

    from media_compost import Phash

    stored = Phash.parse(item.active_file.phash)
    assert Phash.of(Image.open(item.active_file.path)) == stored
    assert stored.distance(stored) == 0
    assert stored.near(stored, item._lib.phash_threshold)
    assert Phash.parse(str(stored)) == stored


def test_frames_of_a_still_is_refused_and_a_still_has_no_frame_rate(item):
    from media_compost import UnsupportedOperation

    assert item.active_file.frame_rate is None
    with pytest.raises(UnsupportedOperation):
        list(item.frames())


# ---- bulk reads -------------------------------------------------------------


def test_explain_all_answers_for_every_tag_in_one_resolve(lib, item):
    """`explain()` per name is one full resolve per name. A caller deciding
    something about ALL of an item's tags asks this instead."""
    lib.tags.get_or_create("dog")
    lib.tags.create("poodle", implies="dog")
    group = lib.groups.create("Animals")
    group.tags.add("creature")
    item.groups.add(group)
    item.tags.add("poodle")

    origins = item.tags.explain_all()
    assert origins["poodle"].direct and origins["poodle"].effective
    assert origins["dog"].implied_by == ("poodle",) and not origins["dog"].direct
    assert [g.name for g in origins["creature"].from_groups] == ["Animals"]
    for name, got in origins.items():
        assert got.name == name
        assert repr(got) == repr(item.tags.explain(name))


def test_tag_groups_reads_a_whole_result_in_placement_order(lib, item):
    """Placement order, not whatever the database returns: a group is a
    layout, and an undefined order makes one library describe itself two ways
    on two reads."""
    grp = item.tag_groups.create("hers")
    item.tags.add("scarf", group=grp)
    item.tags.add("hat", group=grp)
    grp.meta_tags.add("clothing")

    got = lib.query().tag_groups()
    (block,) = got[item.id]
    assert (block.name, block.system) == ("hers", False)
    assert block.tags == ("scarf", "hat")
    assert block.meta_tags == ("clothing",)
    assert block.subjects == ()
    assert block.id == grp.id


def test_tag_groups_names_the_subject_a_block_is_about(lib, item):
    alice = lib.create_subject("Alice")
    grp = item.tag_groups.create("hers")
    item.tags.add("scarf", group=grp)
    grp.subjects.add(alice)
    (block,) = lib.query().tag_groups()[item.id]
    assert block.subjects == ("Alice",)


def test_tag_boxes_reads_a_whole_result_in_the_reference_frame(lib, item):
    item.tags.add("scarf")
    item.tags["scarf"].boxes.add(0.1, 0.2, 0.3, 0.4)
    item.tags["scarf"].boxes.add(time=(1.5, 3.0))

    got = lib.query().tag_boxes()[item.id]["scarf"]
    assert [b.rect for b in got] == [Rect(0.1, 0.2, 0.3, 0.4), None]
    assert [b.time for b in got] == [None, TimeRange(1.5, 3.0)]
    assert [b.id for b in got] == [b.id for b in item.tags["scarf"].boxes]


def test_bulk_reads_of_an_empty_result_are_empty(lib):
    empty = lib.query(TagCond(name="nothing-has-this"))
    assert empty.tag_groups() == {} and empty.tag_boxes() == {}


def test_a_file_can_be_reached_by_id(lib, item):
    got = lib.file(item.active_file.id)
    assert got.id == item.active_file.id and got.item.id == item.id
    with pytest.raises(NotFound):
        lib.file(99999)


def test_prefetching_tags_is_read_rather_than_only_written(lib, item):
    """`_eff_cache` was filled by `prefetch("tags")` and never read: every
    `item.effective_tags` built a fresh `Resolver`, reloading the group
    ancestors, every grant and the whole implication closure — once per
    picture."""
    item.tags.add("blue")
    result = lib.query().prefetch("tags")
    lib._forget_resolved()
    items = list(result)
    assert lib._eff_cache, "the prefetch filled nothing"
    cached = lib._eff_cache[items[0].id]
    assert items[0]._effective() is cached, "the read went around the cache"


def test_a_write_inside_a_transaction_invalidates_the_resolved_tags(lib, item):
    """A write inside `transaction()` does not commit, so the generation
    counter alone would leave the cache describing the library as it was."""
    assert "late" not in item.effective_tags
    with lib.transaction():
        item.tags.add("late")
        assert "late" in item.effective_tags
    assert "late" in item.effective_tags


# ---- video, through the public API ------------------------------------------


@pytest.fixture
def video_lib(tmp_path: Path):
    """A clip that CHANGES — `testsrc` moves, so sampled frames are genuinely
    different pictures and a dedup has something to keep."""
    import subprocess

    from media_compost import media

    src = tmp_path / "src"
    src.mkdir()
    subprocess.run(
        [media._ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=4",
         "-pix_fmt", "yuv420p", str(src / "clip.mp4")], check=True)
    with open_library(tmp_path / "data") as handle:
        handle.import_all([src / "clip.mp4"])
        yield handle


def test_a_video_reports_its_frame_rate(video_lib):
    """The column was always there and the handle never showed it, so a
    consumer converting an every-N-frames interval into a sampling rate had
    no way to ask."""
    video = video_lib.query(None, kind="video").first()
    assert video.active_file.frame_rate == pytest.approx(10.0)
    assert video.duration == pytest.approx(4.0, abs=0.2)


def test_frames_caps_the_long_side_without_upscaling(video_lib):
    """`max_dim` so a consumer wanting a bucket-sized picture pays neither
    the decode nor the scratch space of a full-resolution frame."""
    video = video_lib.query(None, kind="video").first()
    assert {im.size for _, _, im in video.frames(fps=1.0, max_dim=64)} == \
        {(64, 36)}
    # Never upscales: the source is 320 wide and the cap is larger.
    assert {im.size for _, _, im in video.frames(fps=1.0, max_dim=4096)} == \
        {(320, 180)}


def test_sampled_frames_dedup_by_the_librarys_own_rule(video_lib):
    """`Phash.of` + `phash_threshold` is the whole point: a consumer keeping
    one frame per shot means by "the same picture" exactly what the importer
    means, rather than inventing a second rule."""
    from media_compost import Phash

    video = video_lib.query(None, kind="video").first()
    kept = []
    for _, _, frame in video.frames(fps=1.0, max_dim=256):
        h = Phash.of(frame)
        if not any(h.near(k, video_lib.phash_threshold) for k in kept):
            kept.append(h)
    assert 1 < len(kept) <= 4, kept


def test_an_unreadable_film_raises_its_own_error(video_lib):
    """Its own class so a walk over a library can skip one broken file
    without catching everything."""
    from media_compost import MediaUnreadable

    video = video_lib.query(None, kind="video").first()
    video.path.write_bytes(b"not a video at all")
    with pytest.raises(MediaUnreadable):
        list(video.frames(fps=1.0))


def test_a_still_can_be_pushed_through_a_video_encoder(item):
    """The one pixel operation a consumer needs that PIL cannot do — and it
    lives here because this package owns ffmpeg discovery."""
    from media_compost import codec_roundtrip, encoder_available

    if not encoder_available("h264"):
        pytest.skip("this ffmpeg has no h264 encoder")
    before = item.image().convert("RGB")
    after = codec_roundtrip(before, "h264", 32)
    assert after.size == before.size
    assert after.tobytes() != before.tobytes()


# ---- lib.settings ----------------------------------------------------------
#
# The four LIBRARY-wide settings, documented in `docs/python-api.md` and, until
# now, covered by nothing at all: `library/settings.py` measured 0% with the
# whole suite running. That is the exact liability the docstring on
# `test_the_documented_calls_all_run` names — a doc example nobody has
# executed — and it applies with more force here, because these are the values
# a script has to read before it mints a tag of its own.


def test_the_tag_prefixes_default_to_what_the_app_mints(lib):
    assert lib.settings.subject_tag_prefix == "subject:"
    assert lib.settings.place_tag_prefix == "place:"
    assert lib.settings.event_tag_prefix == "event:"


def test_a_prefix_is_written_and_read_back(lib):
    lib.settings.subject_tag_prefix = "who:"
    assert lib.settings.subject_tag_prefix == "who:"
    # …and the other two are untouched: they are three keys, not one.
    assert lib.settings.place_tag_prefix == "place:"
    assert lib.settings.event_tag_prefix == "event:"


def test_a_prefix_survives_reopening_the_library(lib):
    """It is a fact about the LIBRARY, so it belongs in the file rather than
    in the handle — which is also what makes it readable by the app."""
    lib.settings.place_tag_prefix = "at:"
    path = lib.path
    lib.close()
    with open_library(path) as again:
        assert again.settings.place_tag_prefix == "at:"


def test_a_prefix_is_lowercased_on_the_way_out(lib):
    """`Subject:alice` beside `subject:alice` is two namespaces nobody meant
    to make, so the read lowercases whatever is stored — including a value an
    older build wrote before the settings router started lowercasing."""
    lib.settings.subject_tag_prefix = "WHO:"
    assert lib.settings.subject_tag_prefix == "who:"


def test_an_empty_prefix_means_no_prefix_and_is_not_the_default(lib):
    """The distinction `or ""` would destroy: a MISSING key takes the
    default, a key stored as "" is somebody asking for no namespace."""
    lib.settings.subject_tag_prefix = ""
    assert lib.settings.subject_tag_prefix == ""
    # Whitespace prefixes nothing, so it reads the same way.
    lib.settings.place_tag_prefix = "   "
    assert lib.settings.place_tag_prefix == ""


def test_the_face_threshold_defaults_to_the_libraries_own_constant(lib):
    """`MATCH_DEFAULT`, not `SAME_PERSON`: one is what a fresh library is set
    to and the other is where Magi's own faces were MEASURED to separate,
    which is what a setting is read against."""
    from media_compost import faces as facelib

    assert lib.settings.face_match_threshold == facelib.MATCH_DEFAULT


def test_the_face_threshold_round_trips_inside_its_range(lib):
    lib.settings.face_match_threshold = 0.75
    assert lib.settings.face_match_threshold == 0.75


def test_an_out_of_range_threshold_falls_back_rather_than_clamping(lib):
    """A 0 here would name every face after the first person in the library,
    and a clamp to 0.3 would be a number nobody asked for — so the answer is
    the built-in default, whatever nonsense was stored."""
    from media_compost import faces as facelib

    for bad in (0.0, -1.0, 1.5, 99.0):
        lib.settings.face_match_threshold = bad
        assert lib.settings.face_match_threshold == facelib.MATCH_DEFAULT


def test_settings_are_written_inside_an_open_transaction(lib):
    """A write at depth 0 commits itself; inside `transaction()` it waits, so
    a script can set a prefix and mint the tags that use it as one unit."""
    with lib.transaction():
        lib.settings.event_tag_prefix = "when:"
        assert lib.settings.event_tag_prefix == "when:"
    assert lib.settings.event_tag_prefix == "when:"


def test_a_read_only_library_refuses_a_settings_write(lib):
    path = lib.path
    with open_library(path, mode="r") as ro:
        assert ro.settings.subject_tag_prefix == "subject:"   # reading is fine
        with pytest.raises(ReadOnlyError):
            ro.settings.subject_tag_prefix = "nope"
        with pytest.raises(ReadOnlyError):
            ro.settings.face_match_threshold = 0.5


def test_a_re_import_that_only_tags_writes_an_entry_that_reverts(tmp_path: Path):
    """A re-import creates nothing, but `tags_existing` (the default) puts the
    run's tags on the items it MATCHED. That used to leave no History entry —
    the run's one `import` event was written only when something was created
    — so those assignments were invisible and could not be taken back. The
    entry carries the pairs it assigned now, and reverting it removes them."""
    src = tmp_path / "src"
    src.mkdir()
    make_image(src / "a.jpg", seed=11)
    with open_library(tmp_path / "data") as lib:
        lib.import_all([src / "a.jpg"])
        before = lib.history[0].id
        got = lib.import_all([src / "a.jpg"], tags=["again"])
        assert got.stats.imported == 0
        assert [it.uid for it in lib.query("again")]
        newest = lib.history[0]
        assert newest.id != before and newest.action == "import"
        assert "1 existing" in newest.summary
        assert newest.revert()
        assert list(lib.query("again")) == []
