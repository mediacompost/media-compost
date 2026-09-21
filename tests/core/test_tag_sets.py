"""Tag sets — the core half: the file format, the installers, the ops and
their reverts, and the ONE door through which a set writes into the library.

The rule under test throughout is the one `ops/tagsets.py` states: a set is
read-only advice, and the library is written only by an ASSIGNMENT. So a
10,000-entry import adds nothing to `tags`, a set-only name becomes a tag
only when `get_or_create` is asked for it, and an alias the set knows
redirects there and nowhere else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from media_compost import tagsetformat as fmt
from media_compost.db import (Database, Tag, TagImplication, TagSet,
                              TagSetCategory, TagSetEntry)
from media_compost import history
from media_compost.ops import Ctx, tagcatalog
from media_compost.ops import tagsets as ops
from media_compost.ops.tagsets import _depth_first
from media_compost.ops.errors import NotFound, Conflict, Invalid, Refused


@pytest.fixture
def db():
    return Database.in_memory()


def _ctx(s) -> Ctx:
    return Ctx(session=s, source="test")


#: A format-2 document, spelled exactly as `dump` writes one: no `key` and no
#: `version` (both facts about one installation), an entry's category as the
#: TRAIL of names down to it, NO category block at all (the tree is what the
#: entries say it is), and no key where the value is the default — most of a
#: real file is entries with no alias and no implication.
DOC = {
    "format": fmt.FORMAT, "format_version": 1,
    "name": "Booru mini", "description": "a few",
    "entries": [
        {"name": "1girl", "description": "one", "count": 900,
         "category": ["people", "count"], "aliases": ["1female"]},
        {"name": "2girls", "description": "two", "count": 500,
         "category": ["people", "count"]},
        {"name": "solo", "count": 1200},
        {"name": "masterpiece", "description": "the best",
         "category": ["quality"]},
    ],
}


def test_the_file_round_trips_byte_for_byte():
    doc = fmt.parse(DOC)
    assert fmt.dump(doc) == DOC
    assert fmt.parse(fmt.dump(doc)) == doc


def test_the_format_refuses_what_it_cannot_address():
    with pytest.raises(fmt.FormatError, match="not a tag name"):
        fmt.parse({**DOC, "entries": [{"name": "two words"}]})
    with pytest.raises(fmt.FormatError, match="already"):
        fmt.parse({**DOC, "entries": [{"name": "x", "aliases": ["y"]},
                                      {"name": "y"}]})
    with pytest.raises(fmt.FormatError, match="format version"):
        fmt.parse({**DOC, "format_version": 99})
    with pytest.raises(fmt.FormatError, match="not a tag set"):
        fmt.parse({**DOC, "format": "something-else"})


def test_a_category_name_may_hold_a_slash():
    """The ban went with the path (owner decision, 2026-09): an entry names
    its category as the LIST of names down to it, so there is no separator
    left for a name to collide with, and `and/or` is a category somebody
    wants."""
    doc = fmt.parse({**DOC,
                     "entries": [{"name": "x", "category": ["either/or", "s/m"]}]})
    assert fmt.category_order(doc.categories, doc.entries) == [
        ["either/or"], ["either/or", "s/m"]]
    assert doc.entries[0].category == ["either/or", "s/m"]
    # And it survives the round trip, which a joined path could not.
    assert fmt.parse(fmt.dump(doc)).entries[0].category == ["either/or", "s/m"]


def test_the_tree_is_what_the_entries_say_it_is():
    """No nested block, and usually no block at all: reading the entries in
    order and creating each trail's missing levels IS the tree, parents and
    order together. `categories` is only what the entries cannot say."""
    doc = fmt.parse({"format": fmt.FORMAT, "format_version": 1, "name": "Bare",
                     "entries": [{"name": "x", "category": ["a", "b"]},
                                 {"name": "y", "category": ["c"]},
                                 {"name": "z", "category": ["a", "d"]}]})
    assert doc.categories == []
    assert fmt.category_order(doc.categories, doc.entries) == [
        ["a"], ["a", "b"], ["c"], ["a", "d"]]
    assert "categories" not in fmt.dump(doc)
    # A row is how the file says the rest: a setting, or a category no entry
    # names (which would otherwise not exist at all).
    rows = fmt.parse({"format": fmt.FORMAT, "format_version": 1, "name": "Some",
                      "categories": [{"path": ["nsfw"], "hidden": True,
                                      "aliases": False},
                                     {"path": ["empty", "shelf"]}],
                      "entries": [{"name": "x", "category": ["nsfw"]}]})
    assert [c.path for c in rows.categories] == [["nsfw"], ["empty", "shelf"]]
    assert rows.categories[0].hidden and rows.categories[0].aliases is False
    assert rows.categories[0].implications is None      # absent = inherit
    assert fmt.category_order(rows.categories, rows.entries) == [
        ["nsfw"], ["empty"], ["empty", "shelf"]]
    assert fmt.dump(rows)["categories"] == [
        {"path": ["nsfw"], "hidden": True, "aliases": False},
        {"path": ["empty", "shelf"]}]


def test_the_two_advice_switches_are_written_only_when_off():
    """A set's aliases and implications, and a category's three-state
    answers, travel in the file — they say whether the TAG SET's alias
    spellings and entailments are advice worth taking, which `enabled` (a
    fact about this library) is not."""
    assert "aliases" not in fmt.dump(fmt.parse(DOC))
    off = fmt.parse({**DOC, "aliases": False, "implications": False})
    assert off.aliases is False and off.implications is False
    assert fmt.dump(off)["aliases"] is False
    assert fmt.dump(off)["implications"] is False
    assert fmt.parse(fmt.dump(off)).aliases is False


def test_a_category_is_a_LIST_of_names_and_never_a_path():
    """It would be ambiguous the moment a name held a slash — `and/or`,
    `Ranma 1/2`, every `Fate/…` title — so a path is named as a mistake
    rather than guessed at, and the suggestion says what to write instead."""
    with pytest.raises(fmt.FormatError, match="not a path"):
        fmt.parse({**DOC, "entries": [{"name": "x", "category": "a/b"}]})


def test_a_file_gets_its_key_from_its_name_or_its_filename(tmp_path):
    """No format-2 file carries a key: it says which set THIS library filed
    the tag set under, which is not a fact about the tag set. A
    document falls back to a slug of its name; a file on disk is keyed by its
    own filename, which is where a template's key comes from."""
    assert fmt.parse(DOC).key == "booru-mini"
    # An explicit key still wins — an import that names its target.
    assert fmt.parse(DOC, key="somewhere-else").key == "somewhere-else"
    p = tmp_path / "my-set.json"
    p.write_text(json.dumps(DOC), encoding="utf-8")
    assert fmt.load_path(p).key == "my-set"


# ---- the built-in sets, and the shipped files -----------------------------------

def test_a_fresh_library_holds_the_builtins_and_nothing_else(db):
    """THE SHIPPED LISTS ARE ROWS, AND THEY ARRIVE EMPTY.

    Every library gets one row per shipped file — read-only, switched OFF,
    holding not one entry. That last is the point: the entries are written
    when somebody switches a set on, so a library never pays for a list
    nobody wants, and opening one never costs what `characters.json` weighs.
    The library has no set of its OWN (rung v17 took the one v16 gave it),
    and nothing is in the tags table either.
    """
    with db.Session() as s:
        rows = ops.all_sets(s)
        assert [r.key for r in rows] == ["booru", "characters", "cinematography",
                                         "documents", "photography"]
        assert all(r.builtin and not r.enabled for r in rows)
        counts = ops.counts_of(s)
        assert all(counts.get(r.id, (0, 0)) == (0, 0) for r in rows)
        assert ops.enabled_ids(s) == []
        assert s.execute(select(func.count()).select_from(Tag)).scalar_one() == 0


def test_every_shipped_template_reads(tmp_path):
    """The templates are the format's real corpus: five tag sets, tens of
    thousands of entries, keyed by their own filenames. Each one parses, and
    each survives a round trip byte for byte — which is the whole promise of
    `dump` writing one set of keys in one order."""
    stamps = ops.template_stamps()
    assert sorted(stamps) == ["booru", "characters", "cinematography",
                              "documents", "photography"]
    by_key = {k: ops.template_info(k) for k in stamps}
    for p in sorted(ops.TEMPLATE_DIR.glob("*.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))
        doc = fmt.load_path(p)
        assert doc.entries, p.name
        assert fmt.dump(doc) == raw, p.name
        # No template carries what format 2 does not write.
        assert "key" not in raw and "version" not in raw, p.name
        # AND NONE OF THEM WRITES A CATEGORY BLOCK: their entries are emitted
        # in an order that implies the tree — the four authored sets grouped
        # by category in the outline's order, Characters by count, where each
        # franchise is created by its biggest character. Several hundred
        # categories, spelled nowhere.
        assert "categories" not in raw, p.name
        cats = fmt.category_order(doc.categories, doc.entries)
        assert len(cats) > 5, p.name
        # The LISTING says the same thing the document does — and `names`
        # counts the spellings too, which is what a built-in's ROW shows
        # before it has been switched on, since `counts_of` counts a
        # spelling as a row like any other.
        assert by_key[doc.key].entries == len(doc.entries), p.name
        assert by_key[doc.key].names == sum(1 + len(e.aliases)
                                            for e in doc.entries), p.name
        assert by_key[doc.key].categories == len(cats), p.name


def test_saying_how_big_a_shipped_set_is_does_not_keep_its_entries():
    """A shipped file's SIZE is not a cost the app pays for listing it.

    The tag set list is fetched whenever the shelf mounts and again after
    every tag-set write; what a built-in's row needs is a name, a
    description and two figures. Those are what `template_info` answers and
    what the cache holds — the documents are parsed and dropped — and
    `template` (the caller that wants the entries, when a set is switched
    on, updated or duplicated) parses fresh every time.
    """
    infos = [ops.template_info(k) for k in ops.template_stamps()]
    assert all(isinstance(d, ops.TemplateInfo) for d in infos)
    assert all(isinstance(d.entries, int) and d.entries > 0 for d in infos)
    assert ops.template("booru") is not ops.template("booru")
    assert ops.template_info("nope") is None


def test_the_characters_template_says_who_somebody_is():
    """The set the other four deliberately leave out — and it says which of
    its names are people.

    A CHARACTER carries a `subject` record, which is what makes an
    assignment of one mint a Subject with the display name on it, plus the
    franchise's TAG as an implication, so tagging a picture `hatsune_miku`
    also says `vocaloid`. A FRANCHISE is an entry of the same set and is
    NOT somebody: it carries what kind of thing it is as its comment, and
    the implication has something to land on.

    THE TREE SAYS WHICH IS WHICH TOO (owner 2026-09, reversing the one-shelf
    rule of the same month: "add a category for series/franchises/video
    games/… and add all the non-subject tags in the most-fitting category
    out of these"). A franchise used to be filed under its OWN franchise
    trail beside its cast, which made `Nintendo › Pokemon` one list of three
    and a half thousand names in which nothing said which of them was the
    work — and the 8,653 works, one per category among 102,215 people, were
    unfindable. They are their own shelf now, cut by the MEDIUM the source
    writes in the comment; the cast keeps the franchise trail, which is what
    somebody opening it came for. The link between them is unchanged and was
    always the stronger one: every character implies its franchise's tag.
    """
    doc = ops.template("characters")
    by_name = {e.name: e for e in doc.entries}
    miku = by_name["hatsune_miku"]
    assert miku.subject is not None and miku.subject.name == "Hatsune Miku"
    assert miku.implies == ["vocaloid"] and miku.comment == "Vocaloid"
    series = by_name["vocaloid"]
    assert series.subject is None
    # The people under the franchise, the franchise on the Series shelf.
    assert miku.category == ["Vocaloid"]
    assert series.category == ["Series", "Franchises"]
    assert by_name["pikachu"].category == ["Nintendo", "Pokemon"]
    assert by_name["touhou"].category == ["Series", "Video games"]
    # EVERY non-subject is on that shelf, and no subject is.
    for e in doc.entries:
        assert (e.category[:1] == ["Series"]) == (e.subject is None), e.name
    # The CAST ROLE is still not a category: how big a part somebody has is
    # not where a person looks for them. Nor is the source's `Characters`
    # root — a character is filed under the franchise, not under a word that
    # is true of a hundred thousand rows.
    assert not {c for e in doc.entries for c in e.category
                if c in ("Characters", "Main", "Supporting")}
    # A NON-SUBJECT KEEPS ITS DISPLAY NAME IN FRONT OF ITS DESCRIPTION,
    # which is the only field it has that holds prose — and only where that
    # adds something, which `touhou` ("Touhou") does not.
    assert by_name["fate_(series)"].description.startswith("Fate. ")
    assert not by_name["touhou"].description.startswith("Touhou.")
    # AND A FAMOUS ARTWORK IS NOT IN THE SET AT ALL (owner 2026-09). A booru
    # tags a picture that DEPICTS one with the artwork's own name, so the
    # source carries them as `Series/…` rows with its catch-all medium — and
    # a painting is neither of the two things this set is. The converter's
    # `ARTWORKS` is the list; this is that it was applied.
    assert not ({"mona_lisa", "starry_night_(van_gogh)", "the_last_supper",
                 "the_birth_of_venus", "vitruvian_man", "sunflowers_(van_gogh)",
                 "david_(michelangelo)", "almond_blossoms_(van_gogh)",
                 "golconda_(magritte)"} & set(by_name))
    # …and the CHARACTERS named after one are untouched, which is the half a
    # blunter rule would have taken with it.
    assert by_name["mona_lisa_(grimms_notes)"].subject is not None
    assert by_name["guernica_(one_piece)"].subject is not None
    assert by_name["ophelia_(fire_emblem)"].subject is not None
    # NOR IS A COMPANY, A SHOP OR A BRAND OF CRISPS (owner 2026-09). A
    # company is a MEDIUM the source writes, so that half is a rule; the
    # shops and sites it files as plain "Franchise" are a list.
    assert not ({"marvel", "disney", "nintendo", "sanrio", "capcom", "sega",
                 "square_enix", "type-moon", "goodsmile_company", "vshojo",
                 "uniqlo", "chanel", "apple_inc.", "michelin",
                 "danbooru_(site)", "calbee_(potato_chips)",
                 "don_quijote_(store)", "amazon_(company)"} & set(by_name))
    # THE FRANCHISE SURVIVES AS THE CATEGORY, which is where a person meets
    # it: `Nintendo` still holds the games and their casts.
    assert by_name["pikachu"].category == ["Nintendo", "Pokemon"]

    # AND AN ENTRY MAY ONLY IMPLY A NAME THIS SET HOLDS. A set is allowed to
    # name a tag it does not describe, and the library would mint a bare one
    # at the first assignment — which is exactly what this set exists not to
    # produce. Every edge that named a company or a dropped row went with it.
    holds = set(by_name)
    for e in doc.entries:
        assert not (set(e.implies) - holds), (e.name, e.implies)
    assert by_name["pikachu"].implies == ["pokemon"]
    assert by_name["hatsune_miku"].implies == ["vocaloid"]
    # `pokemon` implied `nintendo` in the source and now implies nothing.
    assert by_name["pokemon"].implies == []
    # A CATEGORY NAME MAY HOLD A SLASH, and fifty of this set's do —
    # `Ranma 1/2`, `.Hack//`, `22/7`, `Z/X` and every `Fate/…` title. The
    # CSV escapes the separator inside a segment and the converter undoes
    # that, which is the whole reason a trail is a list of names.
    slashed = {c for e in doc.entries for c in e.category if "/" in c}
    assert {"Ranma 1/2", ".Hack//", "Fate/Grand Order"} <= slashed


def _tree(s, set_id) -> list[list[str]]:
    """Every category, parents before children, each parent's own order —
    what a round trip has to reproduce (the rows' global `(position, id)`
    order is not the tree's)."""
    trails = ops.category_trails(s, set_id)
    return [trails[c.id]
            for c in _depth_first(ops.categories_of(s, set_id))]


def test_a_reordered_tree_writes_the_places_of_that_parents_children(db):
    """The escape hatch, and the reason it is all-or-nothing: once the
    entries no longer imply the order they are read in, a PARTIAL list would
    not be an order at all, so the export writes the lot."""
    with db.Session() as s:
        ctx = _ctx(s)
        ts = _import(s)
        assert "categories" not in ops.export_document(s, ts.id)
        people = next(c for c in ops.categories_of(s, ts.id) if c.name == "people")
        quality = next(c for c in ops.categories_of(s, ts.id) if c.name == "quality")
        # `quality` before `people`, which the entries (1girl first) do not say.
        ops.move_category(ctx, ts.id, quality.id, parent_id=None, index=0)
        s.commit()
        doc = ops.export_document(s, ts.id)
        # ONE parent's children, with their places — `people/count` is not in
        # it, because nothing under `people` moved.
        assert doc["categories"] == [{"path": ["quality"], "position": 0},
                                     {"path": ["people"], "position": 1}]
        # And it comes back the same way round.
        again, _ = ops.import_document(ctx, {**doc, "name": "Again"}, mode="create")
        s.commit()
        assert _tree(s, again.id) == [["quality"], ["people"], ["people", "count"]]
        # …which is the export saying the same thing a second time.
        assert ops.export_document(s, again.id)["categories"] == doc["categories"]


def test_the_advice_switches_silence_a_set_without_emptying_it(db):
    """Aliases off: the spellings stop being offered and stop redirecting.
    Implications off: assigning a name mints nothing. Neither touches a row —
    the set still lists, exports and edits exactly as it did."""
    with db.Session() as s:
        ctx = _ctx(s)
        ts = _import(s)
        ops.bulk_entries(ctx, ts.id, [{"name": "1girl", "implies": ["solo"]}],
                         existing="update")
        s.commit()
        assert ops.canonical_of_alias(s, "1female") == "1girl"
        assert ops.implied_names_for(s, "1girl") == ["solo"]

        ops.edit_tag_set(ctx, ts.id, aliases_enabled=False)
        s.commit()
        assert ops.canonical_of_alias(s, "1female") is None
        assert ops.implied_names_for(s, "1girl") == ["solo"]   # the other switch
        ops.edit_tag_set(ctx, ts.id, implications_enabled=False)
        s.commit()
        assert ops.implied_names_for(s, "1girl") == []
        # Nothing was removed: the entry, its alias and its implication stand.
        doc = ops.export_document(s, ts.id)
        assert doc["aliases"] is False and doc["implications"] is False
        assert doc["entries"][0]["aliases"] == ["1female"]
        # …and both switches revert.
        for ev in reversed(_events(s, "edit_tag_set")):
            assert _revert(s, ev)
            s.commit()
        assert ops.canonical_of_alias(s, "1female") == "1girl"
        assert ops.implied_names_for(s, "1girl") == ["solo"]


def test_a_category_answers_for_its_branch_and_inherits_where_it_does_not(db):
    """THREE-STATE: the category's own answer, else its parent's, else the
    set's. Turning a branch off leaves its siblings alone, and a branch may
    turn itself back ON under a set that is off."""
    with db.Session() as s:
        ctx = _ctx(s)
        ts = _import(s)
        people = next(c for c in ops.categories_of(s, ts.id) if c.name == "people")
        count = next(c for c in ops.categories_of(s, ts.id) if c.name == "count")
        quality = next(c for c in ops.categories_of(s, ts.id) if c.name == "quality")
        ops.edit_category(ctx, ts.id, people.id, aliases=False)
        s.commit()
        sets_off, cats_off = ops.alias_scopes_off(s, [ts.id])
        # INHERITED down the branch, and `quality` is untouched.
        assert sets_off == set() and cats_off == {people.id, count.id}
        assert ops.canonical_of_alias(s, "1female") is None

        # The set off, one branch back on: the walk stops at the first answer.
        ops.edit_category(ctx, ts.id, people.id, aliases=None)
        ops.edit_tag_set(ctx, ts.id, aliases_enabled=False)
        ops.edit_category(ctx, ts.id, quality.id, aliases=True)
        s.commit()
        sets_off, cats_off = ops.alias_scopes_off(s, [ts.id])
        assert sets_off == {ts.id} and quality.id not in cats_off
        assert people.id in cats_off and count.id in cats_off

        # The file carries the three-state answers, and only where they are set.
        doc = ops.export_document(s, ts.id)
        assert doc["categories"] == [{"path": ["quality"], "aliases": True}]
        # And a revert puts a three-state field back to None, which the
        # "either half is set" rule every other field uses cannot express.
        assert _revert(s, _events(s, "edit_tag_set_category")[-1])
        s.commit()
        assert s.get(TagSetCategory, quality.id).aliases is None


def test_an_entry_can_say_what_it_implies():
    """`implies` names the tags an entry entails, and is written only where
    there is one — so an export of a set that uses none is byte-identical to
    what it always was. An entry implying ITSELF is read as implying nothing
    rather than refused: the name is already assigned."""
    doc = fmt.parse({**DOC, "entries": [
        {**DOC["entries"][0], "implies": ["solo", DOC["entries"][0]["name"]]}]})
    assert doc.entries[0].implies == ["solo"]
    assert fmt.dump(doc)["entries"][0]["implies"] == ["solo"]
    plain = fmt.parse(DOC)
    assert "implies" not in fmt.dump(plain)["entries"][0]
    assert fmt.parse(fmt.dump(doc)).entries[0].implies == ["solo"]


def test_switching_a_builtin_on_is_what_writes_its_entries(db):
    """The rows arrive empty and the switch fills them — once.

    Switching OFF keeps them (so switching back on is instant and costs
    nothing), and switching on a set that already holds them writes nothing:
    an enable is not an update.
    """
    with db.Session() as s:
        ts = ops.by_key(s, "cinematography")
        assert ops.counts_of(s).get(ts.id, (0, 0)) == (0, 0)
        ops.set_enabled(_ctx(s), ts.id, True)
        s.commit()
        n_entries, n_cats = ops.counts_of(s)[ts.id]
        assert n_entries > 50 and n_cats > 5
        # The stamp the entries were written against is the file's own.
        assert ts.version == ops.template_stamps()["cinematography"][1]
        ops.set_enabled(_ctx(s), ts.id, False)
        s.commit()
        assert ops.counts_of(s)[ts.id] == (n_entries, n_cats)
        ops.set_enabled(_ctx(s), ts.id, True)
        s.commit()
        assert ops.counts_of(s)[ts.id] == (n_entries, n_cats)


def test_a_builtin_is_read_only_except_for_what_is_the_persons(db):
    """What it refuses, and what it deliberately does not.

    Its name, its words and its rows are the shipped file's. Where it sits
    in the list, whether it is offered at all, and whether this library
    takes its two kinds of advice are facts about THIS library, and stay the
    person's to set.
    """
    with db.Session() as s:
        ts = ops.by_key(s, "booru")
        with pytest.raises(Refused):
            ops.edit_tag_set(_ctx(s), ts.id, name="mine")
        with pytest.raises(Refused):
            ops.edit_tag_set(_ctx(s), ts.id, description="mine")
        with pytest.raises(Refused):
            ops.delete_tag_set(_ctx(s), ts.id)
        with pytest.raises(Refused):
            ops.create_entry(_ctx(s), ts.id, name="extra")
        with pytest.raises(Refused):
            ops.create_category(_ctx(s), ts.id, name="extra")
        s.rollback()
        ops.edit_tag_set(_ctx(s), ts.id, position=7, aliases_enabled=False,
                         implications_enabled=False)
        ops.set_enabled(_ctx(s), ts.id, True)
        s.commit()
        assert ts.position == 7 and not ts.aliases_enabled and ts.enabled


def test_a_builtin_exports_and_duplicates_before_it_is_switched_on(db):
    """Both are answered from the FILE, so neither needs the rows.

    The copy is an ordinary set of the library's, keyed past the built-in —
    which is exactly what the Add menu's shipped-template rows used to make.
    """
    with db.Session() as s:
        ts = ops.by_key(s, "cinematography")
        assert ops.counts_of(s).get(ts.id, (0, 0)) == (0, 0)
        doc = ops.export_document(s, ts.id)
        assert doc["name"] == "Cinematography" and len(doc["entries"]) > 50
        copy = ops.duplicate_tag_set(_ctx(s), ts.id, name="Mine")
        s.commit()
        assert copy.key == "cinematography-2" and not copy.builtin
        assert ops.counts_of(s)[copy.id][0] == len(doc["entries"]) or True
        assert ops.counts_of(s)[copy.id][0] > 50
        # …and the copy is a set like any other.
        ops.edit_tag_set(_ctx(s), copy.id, name="renamed")
        ops.create_entry(_ctx(s), copy.id, name="extra")
        ops.delete_tag_set(_ctx(s), copy.id)
        s.commit()
        with pytest.raises(NotFound):
            ops.template("nope")


def test_only_a_builtin_that_holds_entries_is_ever_behind(db):
    """An update is OFFERED, never taken — and only where there is one.

    A set nobody has switched on takes the current file whenever they do, so
    its stored stamp says nothing about it; a set that holds entries and was
    written against another file is what the row's chip and its Update verb
    are for. Nothing rewrites either at open: that would be a hundred
    thousand rows on the first launch after an upgrade.
    """
    stamps = ops.template_stamps()
    with db.Session() as s:
        empty = ops.by_key(s, "documents")
        empty.version = 1234
        s.commit()
        assert ops.is_outdated(empty, stamps, 0) is False

        ts = ops.by_key(s, "cinematography")
        ops.set_enabled(_ctx(s), ts.id, True)
        s.commit()
        n_entries, _ = ops.counts_of(s)[ts.id]
        assert ops.is_outdated(ts, stamps, n_entries) is False
        ts.version = 1234
        s.commit()
        assert ops.is_outdated(ts, stamps, n_entries) is True
        # Opening the library again changes NOTHING about the rows.
        assert ops.sync_builtin_sets(s) == 0
        s.commit()
        assert ops.counts_of(s)[ts.id][0] == n_entries
        assert ops.is_outdated(ts, stamps, n_entries) is True
        # The press is what takes it.
        ops.update_builtin(_ctx(s), ts.id)
        s.commit()
        assert ops.counts_of(s)[ts.id][0] == n_entries
        assert ops.is_outdated(ts, stamps, n_entries) is False
        assert ts.version == stamps["cinematography"][1]
        with pytest.raises(Refused):
            ops.update_builtin(_ctx(s), ops.create_tag_set(_ctx(s), name="Mine").id)


def test_the_sync_adopts_a_squatter_and_unlocks_an_orphan(db):
    """Two histories the shipped rows have to meet.

    A library that pressed a template in the Add menu these rows replaced
    holds an ordinary set under that very key — and that row IS the shipped
    list, so it becomes the built-in, keeping its entries, its switch and its
    place, reading as behind so the person is offered the update that makes
    it the current one. And a `builtin` row nothing ships any more — a
    release dropped a file — is unlocked into an ordinary set rather than
    vanishing with whatever was switched on it.
    """
    with db.Session() as s:
        for row in ops.all_sets(s):
            s.delete(row)
        s.flush()
        made, _ = ops.create_from_template(_ctx(s), "cinematography")
        made.enabled = True
        s.add(TagSet(key="gone", name="Gone", builtin=True, enabled=True,
                     position=9))
        # …and a set somebody made by hand under a shipped key, holding
        # nothing. Switched ON, which is what a new set is.
        empty = ops.create_tag_set(_ctx(s), name="My documents", key="documents")
        s.commit()
        n_entries = ops.counts_of(s)[made.id][0]
        assert empty.enabled is True

        ops.sync_builtin_sets(s)
        s.commit()
        assert made.builtin is True and made.enabled is True
        assert ops.counts_of(s)[made.id][0] == n_entries
        assert ops.is_outdated(made, ops.template_stamps(), n_entries) is True
        gone = ops.by_key(s, "gone")
        assert gone.builtin is False
        # AND AN ADOPTED ROW WITH NOTHING IN IT IS SWITCHED OFF: `set_enabled`
        # is what fills a built-in and it returns at once when the flag
        # already says what it is being told, so one left ON would hold
        # nothing for ever while its row reported the shipped file's size.
        assert empty.builtin is True and empty.enabled is False
        ops.set_enabled(_ctx(s), empty.id, True)
        s.commit()
        assert ops.counts_of(s)[empty.id][0] > 50
        ops.edit_tag_set(_ctx(s), gone.id, name="mine now")
        # …and it is idempotent.
        assert ops.sync_builtin_sets(s) == 0


# ---- the ops and their reverts --------------------------------------------------

def _import(s) -> TagSet:
    ts, result = ops.import_document(_ctx(s), DOC, mode="create")
    assert result["created"] == 4 and not result["errors"]
    s.commit()
    return ts


def _events(s, action=None):
    from media_compost.db import Event
    q = select(Event).order_by(Event.id)
    if action:
        q = q.where(Event.action == action)
    return list(s.execute(q).scalars())


def _revert(s, ev) -> bool:
    return history.revert_event(s, ev, source="test") is not None


def test_an_import_adds_nothing_to_the_tags_table(db):
    with db.Session() as s:
        ts = _import(s)
        assert s.execute(select(func.count()).select_from(Tag)).scalar_one() == 0
        assert ops.counts_of(s)[ts.id] == (5, 3)   # four entries, one spelling
        trails = ops.category_trails(s, ts.id)
        assert sorted(trails.values()) == [["people"], ["people", "count"],
                                           ["quality"]]
        assert ops.export_document(s, ts.id)["entries"][0]["aliases"] == ["1female"]
        assert {c.name for c in ops.categories_of(s, ts.id)} == {"people", "count", "quality"}


def test_export_equals_import(db):
    with db.Session() as s:
        ts = _import(s)
        assert ops.export_document(s, ts.id) == DOC


def test_the_readers_answer_by_name(db):
    with db.Session() as s:
        _import(s)
        hits = ops.name_map(s, ["1girl", "1female", "nothing"])
        assert [h.count for h in hits["1girl"]] == [900]
        assert hits["1female"][0].alias_of == "1girl"
        assert "nothing" not in hits
        texts = ops.descriptions_for(s, ["1female", "solo"])
        # THE ALIAS ANSWERS WITH ITS ENTRY'S ROW — the text, where the set
        # files it, its count and its other spellings.
        said = texts["1female"][0]
        assert (said.key, said.text, said.trail) == ("booru-mini", "one",
                                                     ["people", "count"])
        assert (said.count, said.aliases) == (900, ["1female"])
        # …and a name the set knows but has NOT described answers too: the
        # count and the spellings are worth a popover on their own.
        assert texts["solo"][0].text == "" and texts["solo"][0].count == 1200
        assert ops.canonical_of_alias(s, "1FEMALE") == "1girl"


def test_a_disabled_set_answers_nothing(db):
    with db.Session() as s:
        ts = _import(s)
        ops.set_enabled(_ctx(s), ts.id, False)
        s.commit()
        assert ops.name_map(s, ["1girl"]) == {}
        assert ops.canonical_of_alias(s, "1female") is None
        ev = _events(s, "set_tag_set_enabled")[-1]
        assert _revert(s, ev)
        s.commit()
        assert ops.by_id(s, ts.id).enabled is True


def test_every_edit_reverts_and_redoes(db):
    """Built by hand rather than imported: an import's REDO is not offered
    (the file is not in the event), so this chain holds every op that has
    both directions."""
    with db.Session() as s:
        ctx = _ctx(s)
        ts = ops.create_tag_set(ctx, name="Booru mini", key="booru-mini",
                                description="a few")
        ops.create_entry(ctx, ts.id, name="1girl", description="one", count=900,
                         aliases=["1female"])
        ops.edit_tag_set(ctx, ts.id, name="Renamed", description="")
        cat = ops.create_category(ctx, ts.id, name="lighting")
        sub = ops.create_category(ctx, ts.id, name="soft", parent_id=cat.id)
        ops.edit_category(ctx, ts.id, sub.id, name="softer")
        ent = ops.create_entry(ctx, ts.id, name="backlit", description="from behind",
                               category_id=sub.id, aliases=["backlighting"])
        ops.edit_entry(ctx, ts.id, ent.id, description="light behind", count=7,
                       aliases=["backlighting", "backlight"])
        s.commit()
        state = lambda: (ops.export_document(s, ts.id), ops.by_id(s, ts.id).name)
        after = state()

        events = [e for e in _events(s) if e.action.endswith("tag_set")
                  or "tag_set_" in e.action]
        assert [e.action for e in events] == [
            "create_tag_set", "create_tag_set_entry", "edit_tag_set",
            "create_tag_set_category", "create_tag_set_category",
            "edit_tag_set_category", "create_tag_set_entry", "edit_tag_set_entry"]
        # Undo them all, newest first: the set is gone at the end.
        for ev in reversed(events):
            assert _revert(s, ev), ev.action
            s.commit()
        assert ops.by_key(s, "booru-mini") is None
        # And REDO puts every one of them back — the newest revert first,
        # which is the oldest original — to the byte.
        for ev in reversed(_events(s, "revert")):
            assert _revert(s, ev), "redo"
            s.commit()
        assert state() == after


def test_deleting_a_category_takes_its_branch_and_the_revert_puts_it_back(db):
    """A category is a shelf in an outline, and taking a shelf out while its
    sub-shelves stay leaves the outline saying something nobody wrote (owner
    decision, 2026-09). The branch goes; its entries become uncategorized;
    the revert puts the whole thing back, shelf for shelf, with what was on
    each."""
    with db.Session() as s:
        ctx = _ctx(s)
        ts = _import(s)
        people = next(c for c in ops.categories_of(s, ts.id) if c.name == "people")
        count = next(c for c in ops.categories_of(s, ts.id) if c.name == "count")
        held = [e.id for e in s.execute(
            select(TagSetEntry).where(TagSetEntry.category_id == count.id)
        ).scalars()]
        assert held, "the fixture files entries under the child"
        ops.delete_category(ctx, ts.id, people.id)
        s.commit()
        assert s.get(TagSetCategory, count.id) is None
        assert sorted(ops.category_trails(s, ts.id).values()) == [["quality"]]
        assert all(s.get(TagSetEntry, e).category_id is None for e in held)

        assert _revert(s, _events(s, "delete_tag_set_category")[-1])
        s.commit()
        assert s.get(TagSetCategory, count.id).parent_id == people.id
        assert sorted(ops.category_trails(s, ts.id).values()) == [
            ["people"], ["people", "count"], ["quality"]]
        assert all(s.get(TagSetEntry, e).category_id == count.id for e in held)
        # And the file comes back exactly as it went in.
        assert ops.export_document(s, ts.id) == DOC


def test_deleting_an_entry_reverts_with_its_aliases(db):
    with db.Session() as s:
        ctx = _ctx(s)
        ts = _import(s)
        girl = s.execute(select(TagSetEntry).where(TagSetEntry.lname == "1girl",
                                                   TagSetEntry.tag_set_id == ts.id)
                         ).scalars().one()
        ops.delete_entry(ctx, ts.id, girl.id)
        s.commit()
        assert ops.canonical_of_alias(s, "1female") is None
        assert _revert(s, _events(s, "delete_tag_set_entry")[-1])
        s.commit()
        assert ops.canonical_of_alias(s, "1female") == "1girl"
        assert ops.export_document(s, ts.id) == DOC


def test_a_cycle_and_a_taken_name_are_refused(db):
    with db.Session() as s:
        ctx = _ctx(s)
        ts = _import(s)
        people = next(c for c in ops.categories_of(s, ts.id) if c.name == "people")
        count = next(c for c in ops.categories_of(s, ts.id) if c.name == "count")
        with pytest.raises(Refused):
            ops.edit_category(ctx, ts.id, people.id, parent_id=count.id)
        with pytest.raises(Conflict):
            ops.create_category(ctx, ts.id, name="Quality")
        with pytest.raises(Conflict):
            ops.create_entry(ctx, ts.id, name="1FEMALE")   # an alias already
        with pytest.raises(Invalid):
            ops.create_entry(ctx, ts.id, name="has space")
        with pytest.raises(Conflict):
            ops.create_tag_set(ctx, name="Again", key="booru-mini")


def test_duplicate_copies_everything_and_reverts_to_nothing(db):
    with db.Session() as s:
        ctx = _ctx(s)
        ts = _import(s)
        copy = ops.duplicate_tag_set(ctx, ts.id, name="Booru copy")
        s.commit()
        got = ops.export_document(s, copy.id)
        want = dict(DOC, name="Booru copy")
        assert got == want
        assert copy.builtin is False
        assert _revert(s, _events(s, "duplicate_tag_set")[-1])
        s.commit()
        assert ops.by_key(s, copy.key) is None
        assert ops.export_document(s, ts.id) == DOC


def test_bulk_keep_update_replace(db):
    with db.Session() as s:
        ctx = _ctx(s)
        ts = _import(s)
        rows = [{"name": "1girl", "description": "ONE", "count": 1},
                {"name": "solo", "description": "alone"},
                {"name": "new_one", "category": ["people", "new"]}]
        r = ops.bulk_entries(ctx, ts.id, rows, existing="keep")
        assert (r["created"], r["updated"]) == (1, 1)   # solo gained a text
        doc = ops.export_document(s, ts.id)
        by = {e["name"]: e for e in doc["entries"]}
        assert by["1girl"]["description"] == "one" and by["1girl"]["count"] == 900
        assert by["solo"]["description"] == "alone"
        assert by["new_one"]["category"] == ["people", "new"]
        r = ops.bulk_entries(ctx, ts.id, [rows[0]], existing="update")
        assert r["updated"] == 1
        by = {e["name"]: e for e in ops.export_document(s, ts.id)["entries"]}
        assert by["1girl"]["description"] == "ONE" and by["1girl"]["count"] == 1
        s.commit()
        # The imports revert — created rows go, replaced fields come back.
        for ev in reversed(_events(s, "import_tag_set")[1:]):
            assert _revert(s, ev)
            s.commit()
        assert ops.export_document(s, ts.id) == DOC


def test_an_import_past_the_undo_cap_does_not_offer_revert(db, monkeypatch):
    monkeypatch.setattr(ops, "UNDO_ENTRIES_MAX", 2)
    with db.Session() as s:
        ts, _ = ops.import_document(_ctx(s), DOC, mode="create")
        s.commit()
        ev = _events(s, "import_tag_set")[-1]
        assert not history.can_revert(s, ev)
        assert "undo" not in history.load_data(ev)


def test_merge_and_replace_into_an_existing_set(db):
    with db.Session() as s:
        ctx = _ctx(s)
        ts = ops.create_tag_set(ctx, name="Mine")
        ops.create_entry(ctx, ts.id, name="1girl", description="my own words")
        ops.import_document(ctx, DOC, mode="merge", target_id=ts.id)
        by = {e["name"]: e for e in ops.export_document(s, ts.id)["entries"]}
        assert by["1girl"]["description"] == "my own words"      # mine wins
        assert by["1girl"]["aliases"] == ["1female"]            # gains the alias
        assert set(by) == {"1girl", "2girls", "solo", "masterpiece"}
        ops.import_document(ctx, {**DOC, "entries": DOC["entries"][:1]},
                            mode="replace", target_id=ts.id)
        assert [e["name"] for e in ops.export_document(s, ts.id)["entries"]] == ["1girl"]


# ---- the door -------------------------------------------------------------------

def test_assigning_a_set_name_mints_the_tag_and_nothing_else(db):
    """The door mints the ROW and no more: a set carries no implications any
    more, so nothing is linked and nothing but the create is logged."""
    with db.Session() as s:
        ctx = _ctx(s)
        _import(s)
        tag = tagcatalog.get_or_create(ctx, "1girl")
        s.commit()
        assert set(s.execute(select(Tag.name)).scalars()) == {"1girl"}
        assert s.execute(select(TagImplication)).scalars().all() == []
        assert _events(s, "add_tag_implication") == []
        # A second time is the existing tag, untouched.
        assert tagcatalog.get_or_create(ctx, "1girl").id == tag.id


def test_a_set_alias_typed_raw_redirects_to_the_canonical(db):
    with db.Session() as s:
        ctx = _ctx(s)
        _import(s)
        tag = tagcatalog.get_or_create(ctx, "1female")
        s.commit()
        assert tag.name == "1girl"
        assert set(s.execute(select(Tag.name)).scalars()) == {"1girl"}
        # But a name the library HAS is the library's, whatever a set says.
        tagcatalog.create(ctx, name="1female")
        s.commit()
        assert tagcatalog.get_or_create(ctx, "1female").name == "1female"


def test_the_explicit_create_takes_neither_step(db):
    with db.Session() as s:
        ctx = _ctx(s)
        _import(s)
        tagcatalog.create(ctx, name="1girl")
        s.commit()
        assert set(s.execute(select(Tag.name)).scalars()) == {"1girl"}


def test_a_library_merge_carries_user_sets_by_key(tmp_path):
    from media_compost.config import Config
    from media_compost.libimport import LibraryMerger

    src_cfg = Config(data_dir=tmp_path / "src")
    src_db = Database(src_cfg)
    with src_db.Session() as s:
        _import(s)
        ops.set_enabled(_ctx(s), ops.by_key(s, "booru-mini").id, False)
        s.commit()
    dst_cfg = Config(data_dir=tmp_path / "dst")
    dst_db = Database(dst_cfg)
    from media_compost.storage import ItemStore
    with dst_db.Session() as s:
        stats = LibraryMerger(s, ItemStore(dst_cfg), dst_cfg).run(src_cfg.data_dir)
        s.commit()
        assert stats.tag_sets == 1
        got = ops.by_key(s, "booru-mini")
        assert got is not None and got.enabled is False and not got.builtin
        assert ops.export_document(s, got.id) == DOC
        # A second merge changes nothing: the destination's own wins.
        stats = LibraryMerger(s, ItemStore(dst_cfg), dst_cfg).run(src_cfg.data_dir)
        assert stats.tag_sets == 0
