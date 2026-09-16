// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parse, serialize, atomNode, emptyGroup, toRequest,
  type Group, type LinkCond, type MetaCond, type TagCond,
} from "./tree.ts";

/** Parsing then re-serializing a canonical string must return it unchanged. */
const roundtrip = (s: string) => serialize(parse(s));

test("atomNode: tag polarity forms", () => {
  assert.deepEqual(atomNode("portrait"), { type: "tag", name: "portrait", have: true, sign: "pos" });
  assert.equal((atomNode("!portrait") as TagCond).have, false);
  assert.equal((atomNode("-portrait") as TagCond).sign, "neg");
  assert.deepEqual(atomNode("!-portrait"), { type: "tag", name: "portrait", have: false, sign: "neg" });
  assert.equal((atomNode("Portrait") as TagCond).name, "portrait");
});

test("atomNode: metadata typed operators", () => {
  assert.deepEqual(atomNode("INFO:width>=800"),
    { type: "meta", name: "width", mtype: "numeric", op: ">=", value: 800, tol: 0.5 });
  assert.deepEqual(atomNode("INFO:camera_make~canon"), { type: "meta", name: "camera_make", mtype: "text", op: "~", value: "canon" });
  assert.equal((atomNode("INFO:iso!=100") as MetaCond).op, "!=");
});

test("atomNode: a tag asked for by what the tag set says about it", () => {
  assert.deepEqual(atomNode("TAG:noflip,!draft"), {
    type: "tag", name: "", have: true, sign: "pos",
    meta_tags: [{ name: "noflip", exclude: false },
                { name: "draft", exclude: true }],
  });
  assert.equal((atomNode("!TAG:noflip") as TagCond).have, false);
  assert.equal((atomNode("-TAG:noflip") as TagCond).sign, "neg");
  // Lowercase is a tag NAME, like every other keyword here.
  assert.equal((atomNode("tag:noflip") as TagCond).name, "tag:noflip");
  for (const c of ["TAG:noflip", "TAG:noflip,!draft", "!TAG:noflip",
                   "-TAG:noflip", "!-TAG:noflip"]) {
    assert.equal(roundtrip(c), c, `round-trip: ${c}`);
  }
});

test("numeric conditions carry the precision they were typed with", () => {
  // The window an "=" accepts follows the decimals in the literal, and the
  // backend is handed the finished window rather than the text.
  const tol = (s: string) => (atomNode(s) as MetaCond).tol;
  assert.equal(tol("INFO:resolution=0.7"), 0.05);
  assert.equal(tol("INFO:resolution=0.75"), 0.005);
  assert.equal(tol("INFO:resolution=0.750"), 0.0005);
  assert.equal(tol("INFO:width=800"), 0.5);
  // Trailing zeros are a deliberate statement of precision, so serializing
  // must not collapse them back to what String(0.750) would give.
  assert.equal(serialize(parse("INFO:resolution=0.750")), "INFO:resolution=0.750");
  assert.deepEqual(toRequest(parse("INFO:resolution=0.7"))?.children[0],
    { type: "meta", name: "resolution", mtype: "numeric", op: "=", value: 0.7, tol: 0.05 });
});

test("atomNode: link directions and required/excluded tags", () => {
  assert.deepEqual(atomNode("LINK:"), { type: "link", direction: "has", link_tags: [] });
  assert.equal((atomNode("!LINK:") as LinkCond).direction, "hasnot");
  assert.equal((atomNode("LINKEDBY:") as LinkCond).direction, "linkedby");
  assert.equal((atomNode("!LINKEDBY:") as LinkCond).direction, "notlinkedby");
  assert.deepEqual((atomNode("LINK:crop,!edit") as LinkCond).link_tags, [
    { name: "crop", exclude: false },
    { name: "edit", exclude: true },
  ]);
  // A bare 'link' word (no colon) is a plain tag, not a link condition.
  assert.deepEqual(atomNode("link"), { type: "tag", name: "link", have: true, sign: "pos" });
});

test("round-trip parse ∘ serialize", () => {
  for (const c of [
    "portrait", "!blurred", "-color", "!-color",
    "portrait landscape", "portrait|landscape",
    "(portrait|landscape) !blurred",
    "INFO:width>=800", "INFO:width>=800 INFO:height<=600",
    "LINK:crop,!edit", "!LINKEDBY:", "a|b|c", "a (b|c) !d",
    "!(anime|comic)", "portrait INFO:iso!=100 LINK:crop",
  ]) {
    assert.equal(roundtrip(c), c, `round-trip: ${c}`);
  }
});

test("groups: empty, none, quoting, collapse", () => {
  assert.deepEqual(parse(""), emptyGroup());
  assert.equal(serialize(emptyGroup()), "");
  assert.equal(toRequest(emptyGroup()), null);

  const none = parse("!(anime|comic)") as Group;
  assert.equal(none.op, "or");
  assert.equal(none.neg, true);

  const g: Group = {
    type: "group", op: "and", neg: false,
    children: [{ type: "meta", name: "Lens Model", mtype: "text", op: "~", value: "canon ef" }],
  };
  assert.equal(serialize(g), '"INFO:Lens Model~canon ef"');
  assert.equal(roundtrip('"INFO:Lens Model~canon ef"'), '"INFO:Lens Model~canon ef"');

  // A single-child group collapses (no redundant parens).
  assert.equal(roundtrip("(portrait)"), "portrait");
});

test("quoted atoms: prefixes stay outside the quotes", () => {
  // A `!` (or `-`) before a quoted atom must negate it, not split into a
  // separate token — `!"ball"` used to fail to parse and silently match all.
  assert.deepEqual((parse('!"my tag"') as Group).children[0],
    { type: "tag", name: "my tag", have: false, sign: "pos" });
  // Partial quoting works too: the quotes may wrap just the part with spaces.
  assert.deepEqual((parse('INFO:"Lens Model"~canon') as Group).children[0],
    { type: "meta", name: "Lens Model", mtype: "text", op: "~", value: "canon" });
  // Two quoted (whitespace-bearing) tags separated by whitespace stay two.
  const two = parse('"a b" "c d"') as Group;
  assert.equal(two.children.length, 2);
});

test("quotes are literal unless they protect whitespace", () => {
  // `"ball"` (a tag whose name really contains quotes) and `ball` are distinct
  // tags, so they must parse to distinct conditions — the quotes are only a
  // strippable wrapper when they enclose whitespace.
  assert.deepEqual((parse('"ball"') as Group).children[0],
    { type: "tag", name: '"ball"', have: true, sign: "pos" });
  assert.deepEqual(atomNode("ball"), { type: "tag", name: "ball", have: true, sign: "pos" });
  // Same for the has-not and negative-assignment forms.
  assert.deepEqual((parse('!"ball"') as Group).children[0],
    { type: "tag", name: '"ball"', have: false, sign: "pos" });
  assert.deepEqual((parse('-"ball"') as Group).children[0],
    { type: "tag", name: '"ball"', have: true, sign: "neg" });
  // A quote-named tag round-trips (the serializer never wraps a tag).
  assert.equal(roundtrip('"ball"'), '"ball"');
  assert.equal(roundtrip('!"ball"'), '!"ball"');
});

test("atomNode: group membership", () => {
  assert.deepEqual(atomNode("GROUP:samples"),
    { type: "ingroup", name: "samples", mode: "has" });
  assert.deepEqual(atomNode("!GROUP:samples"),
    { type: "ingroup", name: "samples", mode: "hasnot" });
  assert.deepEqual(atomNode("GROUPONLY:samples"),
    { type: "ingroup", name: "samples", mode: "only" });
  assert.deepEqual(atomNode("!GROUPONLY:samples"),
    { type: "ingroup", name: "samples", mode: "notonly" });
  // Group names keep their case (matched case-insensitively server-side).
  assert.deepEqual(atomNode("GROUP:My Folder"),
    { type: "ingroup", name: "My Folder", mode: "has" });
});

test("group condition round-trips, quoted when the name has spaces", () => {
  assert.equal(roundtrip("GROUP:samples"), "GROUP:samples");
  assert.equal(roundtrip("!GROUP:samples"), "!GROUP:samples");
  assert.equal(roundtrip("GROUPONLY:samples"), "GROUPONLY:samples");
  assert.equal(roundtrip("!GROUPONLY:samples"), "!GROUPONLY:samples");
  assert.equal(roundtrip('"GROUPONLY:My Folder"'), '"GROUPONLY:My Folder"');
  assert.equal(roundtrip('"GROUP:My Folder"'), '"GROUP:My Folder"');
  assert.equal(roundtrip('"!GROUP:My Folder"'), '"!GROUP:My Folder"');
  // OR nested under the implicit AND root gets canonical parentheses.
  assert.equal(roundtrip("cat GROUP:pets|GROUP:zoo"), "cat (GROUP:pets|GROUP:zoo)");
});

test("caption conditions round-trip (bare, tagged, negated)", () => {
  assert.deepEqual(parse("CAPTION:").children[0],
    { type: "caption", mode: "has", caption_kind: "caption", caption_tags: [] });
  assert.deepEqual(parse("CAPTION:alt,!draft").children[0],
    { type: "caption", mode: "has", caption_kind: "caption",
      caption_tags: [{ name: "alt", exclude: false },
                     { name: "draft", exclude: true }] });
  assert.deepEqual(parse("!CAPTION:alt").children[0],
    { type: "caption", mode: "hasnot", caption_kind: "caption",
      caption_tags: [{ name: "alt", exclude: false }] });
  for (const q of ["CAPTION:", "CAPTION:alt,!draft", "!CAPTION:alt"]) {
    assert.equal(serialize(parse(q)), q);
  }
});

test("INSTRUCTION is the same condition over the other list", () => {
  assert.deepEqual(parse("INSTRUCTION:").children[0],
    { type: "caption", mode: "has", caption_kind: "instruction",
      caption_tags: [] });
  assert.deepEqual(parse("!INSTRUCTION:draft").children[0],
    { type: "caption", mode: "hasnot", caption_kind: "instruction",
      caption_tags: [{ name: "draft", exclude: false }] });
  for (const q of ["INSTRUCTION:", "INSTRUCTION:alt,!draft",
                   "!INSTRUCTION:alt"]) {
    assert.equal(serialize(parse(q)), q);
  }
  // Lowercase is a tag name, like every other keyword here.
  assert.deepEqual(parse("instruction:redraw").children[0],
    { type: "tag", name: "instruction:redraw", have: true, sign: "pos" });
});

test("backslash escapes commas and a leading ! in tag names", () => {
  // A meta tag whose name contains a comma.
  assert.deepEqual(parse("CAPTION:test\\,tag,abc").children[0], {
    type: "caption", mode: "has", caption_kind: "caption",
    caption_tags: [{ name: "test,tag", exclude: false },
                   { name: "abc", exclude: false }],
  });
  // A tag literally named "!test" — not a negation.
  assert.deepEqual(parse("\\!test").children[0],
    { type: "tag", name: "!test", have: true, sign: "pos" });
  assert.deepEqual(parse("!test").children[0],
    { type: "tag", name: "test", have: false, sign: "pos" });
  // …and inside a list, where ! means "exclude".
  assert.deepEqual(parse("LINK:\\!odd,!plain").children[0], {
    type: "link", direction: "has",
    link_tags: [{ name: "!odd", exclude: false },
                { name: "plain", exclude: true }],
  });
  // Round-trip: serializing puts the escapes back.
  for (const q of ["CAPTION:test\\,tag,abc", "\\!test", "LINK:\\!odd,!plain",
                   "GROUP:a\\,b"]) {
    assert.equal(serialize(parse(q)), q);
  }
});

test("a subject atom round-trips with its date and age ranges", () => {
  const cases = [
    "SUBJECT:alice",
    "!SUBJECT:alice",
    "SUBJECT:alice@1921",
    "SUBJECT:alice@1910..1920",
    "SUBJECT:alice#12",
    "SUBJECT:alice#10..14",
    "SUBJECT:alice@1910..1920#10..14",
    "SUBJECT:",
  ];
  for (const q of cases) {
    assert.equal(serialize(parse(q)), q, q);
  }
});

test("a subject atom parses into the shape the backend evaluates", () => {
  const one = parse("SUBJECT:alice@1910..1920#10..14").children[0] as any;
  assert.equal(one.type, "subject");
  assert.equal(one.name, "alice");
  assert.equal(one.have, true);
  // A typed YEAR becomes a partial date. Writing the bare 1910 through was a
  // live bug: the evaluator decoded it as year 0, month 19, day 10 and the
  // query silently matched nothing.
  assert.deepEqual([one.date_from, one.date_to], [19100000, 19200000]);
  assert.deepEqual([one.age_from, one.age_to], [10, 14]);
  const any = parse("!SUBJECT:").children[0] as any;
  assert.equal(any.name, "");
  assert.equal(any.have, false);
});

test("a place atom round-trips", () => {
  for (const q of ["PLACE:Tokyo", "PLACE=Tokyo", "!PLACE:", "PLACE:"]) {
    assert.equal(serialize(parse(q)), q, q);
  }
  const c = parse("PLACE=Tokyo").children[0] as any;
  assert.equal(c.type, "place");
  assert.equal(c.op, "=");
  assert.equal(c.value, "Tokyo");
});

test("an event atom round-trips, with and without a span", () => {
  for (const q of ["EVENT:comic_con", "!EVENT:comic_con", "EVENT:", "!EVENT:",
                   "EVENT:@2014", "EVENT:@2014..2016", "EVENT:comic_con@2014"]) {
    assert.equal(serialize(parse(q)), q, q);
  }
  const c = parse("EVENT:comic_con@2014..2016").children[0] as any;
  assert.equal(c.type, "event");
  assert.equal(c.name, "comic_con");
  assert.equal(c.have, true);
  assert.deepEqual([c.date_from, c.date_to], [20140000, 20160000]);
});

test("a typed date keeps its precision, at any length", () => {
  const from = (q: string) => (parse(q).children[0] as any).date_from;
  assert.equal(from("EVENT:@2014"), 20140000, "a year");
  assert.equal(from("EVENT:@201407"), 20140700, "a month");
  assert.equal(from("EVENT:@20140724"), 20140724, "a day");
  // And the shortest form that reads back the same is what is written, since
  // a query string is typed by hand as often as it is generated.
  assert.equal(serialize(parse("EVENT:@20140000")), "EVENT:@2014");
});

test("an event name is not read as a tag", () => {
  // The atom chain is prefix-matched and ends in a bare-tag fallback, so a
  // keyword that lands after it silently becomes a tag literally called
  // "EVENT:sdcc_2014".
  const c = parse("EVENT:sdcc_2014").children[0] as any;
  assert.equal(c.type, "event");
  assert.equal(c.name, "sdcc_2014");
});

test("a keyword is UPPERCASE, and lowercase is always a tag", () => {
  // The whole reason for the shouting: the Tagging settings namespace
  // subjects, places and events as `subject:`/`place:`/`event:` by default, so
  // a case-insensitive keyword would swallow the very tags the app invents.
  for (const name of ["place:berlin", "subject:alice", "event:sdcc_2014",
                      "meta:width", "group:samples", "link:crop",
                      "caption:alt", "Place:Berlin", "PLACE_holder"]) {
    const c = parse(name).children[0] as any;
    assert.equal(c.type, "tag", name);
    assert.equal(c.name, name.toLowerCase(), name);
    assert.equal(serialize(parse(name)), name.toLowerCase(), name);
  }
  // And the shouted forms are still conditions.
  for (const [q, kind] of [["PLACE:Tokyo", "place"], ["SUBJECT:alice", "subject"],
                           ["EVENT:sdcc", "event"], ["INFO:width>=8", "meta"],
                           ["GROUP:s", "ingroup"], ["LINK:crop", "link"],
                           ["CAPTION:alt", "caption"]] as const) {
    assert.equal((parse(q).children[0] as any).type, kind, q);
  }
});

test("a namespaced tag survives the round trip it used to break", () => {
  // `place:berlin` typed as a search, serialized and parsed again, has to stay
  // one tag — it was read as a place condition with the value "berlin" before.
  const q = "place:berlin !subject:alice -event:x";
  assert.equal(serialize(parse(q)), q);
  const kinds = (parse(q).children as any[]).map((c) => c.type);
  assert.deepEqual(kinds, ["tag", "tag", "tag"]);
});

test("a capture-date window round-trips at the precision it was typed", () => {
  for (const q of ["TAKEN:@2020", "TAKEN:@2020-01-01..2020-01-07",
                   "TAKEN:@2020-03-05T14:30", "!TAKEN:"]) {
    assert.equal(serialize(parse(q)), q, q);
  }
});

test("a taken window is read as a partial date, separators and all", () => {
  const one = (q: string) => (parse(q).children[0] as any);
  assert.equal(one("TAKEN:@2020").date_from, 20200000000000);
  assert.equal(one("TAKEN:@2020-01-07").date_to, 20200107000000);
  assert.equal(one("TAKEN:@2020-03-05T14:30:12").date_from, 20200305143012);
  // No window at all is "anything with a date", and `!` is its negation.
  assert.equal(one("TAKEN:").have, true);
  assert.equal(one("!TAKEN:").have, false);
});
