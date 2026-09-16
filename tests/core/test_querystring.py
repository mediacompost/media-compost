"""`querystring.py` and `frontend/src/query/tree.ts` must agree.

They are two implementations of one grammar. The frontend keeps its own copy
because the query builder is two-way bound to the text field — it re-parses on
every keystroke and re-serializes on every dropdown change, and a round trip to
the server in that loop is lag on every click. So the copies stay, and this is
what stops them drifting.

`golden/query_corpus.json` is the contract. Every row is
`{query, tree, canonical}`: the string, the tree it parses to, and the string
that tree serializes back to. **Both suites read the same file** — this one and
`frontend/src/query/corpus.test.ts` — so a change on either side that the other
has not made fails immediately, in the suite of whoever made it.

The rows deliberately pin the places these two have drifted before, or could:

* `split_escaped` returning pieces STILL escaped (the caller strips its own
  `!` before unescaping, so unescaping first turns `\\!name` into an exclusion);
* `num_tolerance` deriving precision from the typed literal — `0.70` is not
  `0.7` once it is a JSON number — and `meta_value_text` re-rendering it so the
  value round-trips;
* keywords matched CASE-SENSITIVELY, since the default tag prefixes put tags in
  exactly the `place:berlin` shape;
* `parse_when`'s 4/6/8-digit partial dates, which is where the live
  `subject:@1910` bug was.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from media_compost import querystring as qs

CORPUS = pathlib.Path(__file__).parent / "golden" / "query_corpus.json"
UPDATE = bool(os.environ.get("MEDIA_COMPOST_UPDATE_GOLDEN"))

#: Every string the corpus covers. Adding a condition kind means adding rows
#: here AND in the frontend's copy, in the same commit.
QUERIES = [
    # -- tags and booleans --
    "portrait",
    "!portrait",
    "-blurry",
    # A name that STARTS with a colon is a tag — the booru emoticons `:o`,
    # `:d`, `:3`; the keywords are uppercase and anchored, so nothing here
    # reads it as one, and `!`/`-` in front of it mean what they always do.
    ":o",
    "!:o",
    "-:d",
    # …and so is one that ENDS with one (`d:`, `3:`, `c:`). The keyword regexes
    # are anchored and uppercase, so a lowercase trailing colon is never read
    # as `PLACE:`-style punctuation, and `place:` is the tag, not the keyword.
    "d:",
    "!3:",
    "-c:",
    "place:",
    "!-blurry",
    "a b",
    "a|b",
    "a b|c",
    "(a b)|c",
    "!(a b)",
    "!(a|b)",
    "",
    # -- escaping: the characters the grammar itself uses --
    r"\!literal",
    r"\-literal",
    r"comma\,name",
    # -- a tag described by what the tag set says about it --
    "TAG:noflip",
    "TAG:noflip,!draft",
    "!TAG:noflip",
    "-TAG:noflip",
    "!-TAG:noflip",
    # -- metadata, and the precision that travels with a literal --
    "INFO:width>=800",
    "INFO:width<800",
    "INFO:width!=800",
    "INFO:resolution=0.7",
    "INFO:resolution=0.70",
    "INFO:resolution=0.750",
    "INFO:camera_make~canon",
    "INFO:camera_make!~canon",
    "INFO:format=jpeg",
    # -- groups --
    "GROUP:Trips",
    "!GROUP:Trips",
    "GROUPONLY:Trips",
    "!GROUPONLY:Trips",
    # -- places --
    "PLACE:Tokyo",
    "PLACE=Tokyo",
    "!PLACE:",
    # -- subjects: a date, an age, and the spans of each --
    "SUBJECT:alice",
    "SUBJECT:alice@1921",
    "SUBJECT:alice@192104",
    "SUBJECT:alice@19210408",
    "SUBJECT:@1910..1920",
    "SUBJECT:alice#12",
    "SUBJECT:alice#10..14",
    "SUBJECT:alice@1921#12",
    "!SUBJECT:",
    # -- events --
    "EVENT:sdcc",
    "EVENT:sdcc@2014",
    "EVENT:sdcc@2014..2016",
    "!EVENT:",
    # -- taken: the finer encoding --
    "TAKEN:@2020",
    "TAKEN:@2020-01",
    "TAKEN:@2020-01-07",
    "TAKEN:@2020-01-01..2020-01-07",
    "!TAKEN:",
    # -- similarity to a pivot item --
    # The bare form carries NO tolerance: it means "the library's own
    # phash_threshold", and writing today's number into a saved search would
    # freeze it. So these two must read back as different trees.
    "COLORLIKE:a1b2c3d4",
    "COLORLIKE:a1b2c3d4~4",
    "COLORLIKE:a1b2c3d4~0",
    "!COLORLIKE:a1b2c3d4",
    "COLORLIKE:a1b2c3d4~6",
    "!COLORLIKE:a1b2c3d4~6",
    # Lowercase is a TAG name, like every other keyword here.
    "similar:a1b2c3d4",
    # -- tags read as numbers --
    # `tol` is half the last typed decimal place, so `1.70` and `1.7` are
    # different trees and each survives its own round trip.
    "VALUE:height>190cm",
    "VALUE:quality>=8",
    "VALUE:height=1.70m",
    "VALUE:height=1.7m",
    "!VALUE:people=3",
    "VALUE:weight<=60kg",
    "VALUE:pages!=12",
    # A comma decimal READS and the canonical spelling writes the dot.
    "VALUE:height>1,5m",
    # An unknown unit still parses — it compares only within itself.
    "VALUE:size>300px",
    # Lowercase is a tag name here too.
    "value:height",
    # -- captions, instructions and links --
    "CAPTION:",
    "CAPTION:en",
    "CAPTION:en,!draft",
    "!CAPTION:",
    # The same condition over the OTHER list — an instruction says how the
    # picture was made, and CAPTION: must never match one.
    "INSTRUCTION:",
    "INSTRUCTION:en",
    "INSTRUCTION:en,!draft",
    "!INSTRUCTION:",
    "LINK:",
    "LINK:edit",
    "LINK:edit,!manual",
    "LINKEDBY:edit",
    "!LINK:",
    "!LINKEDBY:",
    # -- keywords are CASE-SENSITIVE: these are tag names, not conditions --
    "place:berlin",
    "Place:Berlin",
    "subject:alice",
    "meta:width",
    "info:width",
    "tag:noflip",
    "instruction:redraw",
    # -- a whole query --
    "portrait INFO:width>=800 !blurry",
    "(SUBJECT:alice|SUBJECT:bob) TAKEN:@2020",
    "COLORLIKE:a1b2c3d4~8 !portrait",
]


def _row(query: str) -> dict:
    tree = qs.parse(query)
    return {
        "query": query,
        "tree": json.loads(tree.model_dump_json(exclude_defaults=False)),
        "canonical": qs.serialize(tree),
    }


def _corpus() -> list[dict]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))["rows"]


def test_the_corpus_is_current():
    """Regenerate with MEDIA_COMPOST_UPDATE_GOLDEN=1 — and update the
    frontend's copy in the same commit."""
    rows = [_row(qy) for qy in QUERIES]
    if UPDATE:
        CORPUS.parent.mkdir(parents=True, exist_ok=True)
        CORPUS.write_text(json.dumps({"rows": rows}, indent=2,
                                     ensure_ascii=False) + "\n")
        pytest.skip(f"corpus written to {CORPUS}")
    # A MISSING corpus is a failure. It used to regenerate itself here, which
    # is the worst place in the tree for that: this file is what keeps the two
    # grammars in lockstep (`node --test` asserts the same rows), and
    # `test_stored_vocabularies.py` reads it as the syntax somebody may have
    # SAVED. Recreating it from today's parser would agree with today's
    # parser by construction, on both sides, and take the saved-query guard
    # with it.
    assert CORPUS.exists(), (
        f"{CORPUS} is missing — restore it from git. It is the shared record "
        f"the frontend's `query/corpus.test.ts` reads too, so a regenerated "
        f"one would simply agree with whatever the parser does today.")
    want = _corpus()
    assert len(rows) == len(want), (
        f"the corpus has {len(want)} rows, QUERIES has {len(rows)}"
    )
    for got, exp in zip(rows, want):
        assert got == exp, (
            f"{got['query']!r} parses differently now.\n"
            f"  corpus: {exp}\n  now:    {got}"
        )


@pytest.mark.parametrize("query", QUERIES)
def test_every_query_round_trips(query):
    """Serializing what a string parsed to gives a string that parses the
    same. Not necessarily the SAME string — `0.7` and `..2020` normalize —
    which is why the corpus records `canonical` separately."""
    tree = qs.parse(query)
    again = qs.parse(qs.serialize(tree))
    assert again == tree


def test_a_malformed_query_raises_and_try_parse_does_not():
    for bad in ["(a", "a)", "(", "!("]:
        with pytest.raises(qs.QueryStringError):
            qs.parse(bad)
        assert qs.try_parse(bad) is None


def test_escaping_survives_a_round_trip():
    """The rule that has bitten before: pieces come back STILL escaped, so a
    caller strips its own `!` before unescaping."""
    assert qs.split_escaped(r"a\,b,c") == [r"a\,b", "c"]
    assert qs.unescape_name(r"a\,b") == "a,b"
    assert qs.escape_name("a,b") == r"a\,b"
    assert qs.escape_name("!x") == r"\!x"
    assert qs.escape_name("-x") == r"\-x"


def test_a_typed_year_is_a_partial_date():
    """The live bug this pins: `@1910` must become 19100000, not 1910 — which
    the evaluator would read as year 0, month 19, day 10, matching nothing."""
    tree = qs.parse("SUBJECT:alice@1910")
    cond = tree.children[0]
    assert cond.date_from == 19100000 and cond.date_to == 19100000
    assert qs.parse("SUBJECT:alice@191003").children[0].date_from == 19100300
    assert qs.parse("SUBJECT:alice@19100308").children[0].date_from == 19100308


def test_a_numeric_literal_carries_its_precision():
    """`0.70` is not `0.7` — the tolerance is what says so, and it has to
    survive being written back out."""
    assert qs.parse("INFO:r=0.7").children[0].tol == pytest.approx(0.05)
    assert qs.parse("INFO:r=0.70").children[0].tol == pytest.approx(0.005)
    assert qs.serialize(qs.parse("INFO:r=0.70")) == "INFO:r=0.70"
    assert qs.serialize(qs.parse("INFO:r=0.7")) == "INFO:r=0.7"


def test_a_tag_can_be_asked_for_by_what_a_tag_set_says_about_it():
    """`TAG:` is the CAPTION: shape over the item's own tags: required and
    excluded meta tags, per TAG rather than across the item."""
    cond = qs.parse("TAG:noflip,!draft").children[0]
    assert cond.type == "tag" and cond.name == ""
    assert [(t.name, t.exclude) for t in cond.meta_tags] == [
        ("noflip", False), ("draft", True)]
    assert qs.parse("!TAG:noflip").children[0].have is False
    assert qs.parse("-TAG:noflip").children[0].sign == "neg"
    # Lowercase is a tag NAME, like every other keyword here.
    assert qs.parse("tag:noflip").children[0].name == "tag:noflip"


def test_keywords_are_case_sensitive():
    """`place:berlin` is a TAG, because that is the shape the app's own
    place-tag prefix produces."""
    assert qs.parse("place:berlin").children[0].type == "tag"
    assert qs.parse("PLACE:berlin").children[0].type == "place"
