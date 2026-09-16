/** The tag-grid session's pure rules — the cursor walk over the fixed grid,
 *  the codec and the embedder resolution. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_CONFIG, FUSED, GRID_COLS, GRID_ROWS, batchSize, cycleAll, cycleAssignment,
  embeddersOf, offered, parseTagGridConfig, serializeTagGridConfig,
  startAnswer, stepCursor, summarizeBatches, writeFor, hasCounter,
  canSayBoth, writeIsEmpty,
  tagNames, wireTags, withCounter, withoutTag, withTag, renameTag,
} from "./tagGrid.ts";

test("→ cycles none → fits → doesn't fit → none, and ← the other way", () => {
  assert.equal(cycleAssignment("none"), "positive");
  assert.equal(cycleAssignment("positive"), "negative");
  assert.equal(cycleAssignment("negative"), "none");
  assert.equal(cycleAssignment("none", true), "negative");
  assert.equal(cycleAssignment("negative", true), "positive");
  assert.equal(cycleAssignment("positive", true), "none");
});

test("the ring skips an answer that is not offered, and steps onto the ring from one", () => {
  const two = offered("no_none");
  assert.deepEqual(two, ["positive", "negative"]);
  assert.equal(cycleAssignment("positive", false, two), "negative");
  assert.equal(cycleAssignment("negative", false, two), "positive");
  assert.equal(cycleAssignment("negative", true, two), "positive");
  assert.equal(cycleAssignment("none", false, two), "positive",
               "a card that started undecided steps onto the offered ring");
  const soft = offered("no_negative");
  assert.deepEqual(soft, ["positive", "none"]);
  assert.equal(cycleAssignment("positive", false, soft), "none");
  assert.equal(cycleAssignment("none", true, soft), "positive");
  assert.deepEqual(offered("all"), ["positive", "negative", "none"]);
  assert.deepEqual(offered("all", true), ["positive", "negative", "both", "none"],
                   "both follows doesn't fit");
  assert.deepEqual(offered("no_negative", true), ["positive", "none"],
                   "no doesn't fit, no both");
  assert.equal(cycleAssignment("negative", false, offered("all", true)), "both");
  assert.equal(cycleAssignment("both", false, offered("all", true)), "none");
});

test("a card starts on its bucket where that is offered, else on the nearest decision", () => {
  assert.equal(startAnswer("none", offered("all")), "none");
  assert.equal(startAnswer("none", offered("no_none")), "negative",
               "without undecided every card gets a decision");
  assert.equal(startAnswer("negative", offered("no_negative")), "none");
  assert.equal(startAnswer("positive", offered("no_negative")), "positive");
  assert.equal(startAnswer("positive", offered("all"), "negative"), "negative",
               "what the picture carries beats the guess");
  assert.equal(startAnswer("none", offered("no_negative"), "negative"), "none",
               "…through the same nearest-decision rule");
});

test("→ and ← step in reading order, ↓ and ↑ by a row, and the edges absorb", () => {
  const ids = [1, 2, 3, 4, 5, 6, 7];  // three columns: 1 2 3 / 4 5 6 / 7
  assert.equal(stepCursor(ids, 2, "right", 3), 3);
  assert.equal(stepCursor(ids, 3, "right", 3), 4, "a row's last leads to the next row's first");
  assert.equal(stepCursor(ids, 7, "right", 3), 7, "the end absorbs");
  assert.equal(stepCursor(ids, 4, "left", 3), 3);
  assert.equal(stepCursor(ids, 1, "left", 3), 1, "the start absorbs");
  assert.equal(stepCursor(ids, 2, "down", 3), 5, "the card below");
  assert.equal(stepCursor(ids, 5, "down", 3), 5, "no card below: absorbs");
  assert.equal(stepCursor(ids, 4, "down", 3), 7);
  assert.equal(stepCursor(ids, 5, "up", 3), 2);
  assert.equal(stepCursor(ids, 2, "up", 3), 2, "the first row absorbs");
});

test("nothing is selected until a key asks: the first press lands on the first card", () => {
  assert.equal(stepCursor([7, 8], null, "right", 2), 7);
  assert.equal(stepCursor([7, 8], null, "up", 2), 7);
  assert.equal(stepCursor([7, 8], 99, "right", 2), 7, "a stale cursor too");
  assert.equal(stepCursor([], null, "right", 2), null);
});

test("the config round-trips and repairs a bad grid shape", () => {
  const cfg = { ...DEFAULT_CONFIG,
                tags: [{ name: "cat", negative: "not_cat" }],
                groups: [3], cols: 6, rows: 3,
                embedder: FUSED, skipSequenced: true,
                answers: "no_none" as const };
  assert.deepEqual(parseTagGridConfig(serializeTagGridConfig(cfg)), cfg);
  assert.deepEqual(parseTagGridConfig(null), DEFAULT_CONFIG);
  assert.deepEqual(parseTagGridConfig("nope"), DEFAULT_CONFIG);
  const bad = parseTagGridConfig(JSON.stringify({ cols: 99, rows: 0 }));
  assert.equal(bad.cols, DEFAULT_CONFIG.cols);
  assert.equal(bad.rows, DEFAULT_CONFIG.rows);
  assert.equal(bad.skipSequenced, false);
  assert.equal(parseTagGridConfig(JSON.stringify({ answers: "nope" })).answers, "all");
  assert.ok(GRID_COLS.includes(DEFAULT_CONFIG.cols));
  assert.ok(GRID_ROWS.includes(DEFAULT_CONFIG.rows));
  assert.equal(batchSize(cfg), 18);
});

test("the embedder choice resolves against what is listed", () => {
  const avail = ["dinov2_small", "clip_vit_b32"];
  assert.deepEqual(embeddersOf("clip_vit_b32", avail), ["clip_vit_b32"]);
  assert.deepEqual(embeddersOf(FUSED, avail), avail);
  assert.deepEqual(embeddersOf("gone", avail), ["dinov2_small"]);
  assert.deepEqual(embeddersOf(FUSED, []), []);
});

test("the summary counts every committed answer", () => {
  const s = summarizeBatches([
    { assign: new Map([[1, "positive"], [2, "none"]]) },
    { assign: new Map([[3, "negative"], [4, "positive"]]) },
  ]);
  assert.deepEqual(s, { positive: 2, negative: 1, none: 1, both: 0 });
});

test("⇧⌥→ turns a batch that agrees, and first ALIGNS one that differs", () => {
  // Agreeing cards step together, on the ring the session offers.
  assert.equal(cycleAll(["none", "none", "none"]), "positive");
  assert.equal(cycleAll(["positive", "positive"], true), "none");
  assert.equal(cycleAll(["positive", "positive"], false, ["positive", "negative"]), "negative");
  // Differing cards are put onto the FIRST card's answer, whichever way the
  // arrow points — a step that nobody saw the starting point of is not taken.
  assert.equal(cycleAll(["negative", "positive", "none"]), "negative");
  assert.equal(cycleAll(["negative", "positive", "none"], true), "negative");
  // And the press after that turns them together.
  assert.equal(cycleAll(["negative", "negative", "negative"]), "none");
  // Nothing to turn.
  assert.equal(cycleAll([]), "none");
});

test("what an answer writes IS the set, and its counters are the other side", () => {
  const base = parseTagGridConfig(JSON.stringify({ tags: ["cat"] }));
  assert.deepEqual(writeFor(base, "positive"),
                   { pos: ["cat"], neg: [], groups: [] });
  assert.deepEqual(writeFor(base, "negative"),
                   { pos: [], neg: ["cat"], groups: [] });
  assert.deepEqual(writeFor(base, "none"), { pos: [], neg: [], groups: [] });

  // A counter tag is assigned POSITIVELY in the negative's place.
  const one = parseTagGridConfig(JSON.stringify({
    tags: [{ name: "big", negative: "small" }], groups: [3],
  }));
  assert.deepEqual(writeFor(one, "positive"),
                   { pos: ["big"], neg: [], groups: [3] });
  assert.deepEqual(writeFor(one, "negative"),
                   { pos: ["small"], neg: [], groups: [] });
  assert.deepEqual(writeFor(one, "both").pos.sort(), ["big", "small"]);
  // A MEMBERSHIP HAS NO NEGATIVE FORM: "not in that group" is not something
  // to record, so the groups ride the "fits" side alone.
  assert.deepEqual(writeFor(one, "negative").groups, []);
  assert.equal(hasCounter(one), true);
  assert.equal(hasCounter(base), false);
});

test("a conjunction's “doesn't fit” writes nothing at all", () => {
  // THE TWO ANSWERS ARE ASYMMETRIC. "Fits" decomposes — the picture is
  // every tag of the set, and each conjunct is written. "Doesn't fit" is
  // `NOT big OR NOT tall`, which no assignment can spell: the picture may
  // well be big, just not big AND tall. So it writes nothing — not the
  // counter either, which is the same claim about one conjunct in another
  // spelling — and the answer reaches the fit as a session negative.
  const set = parseTagGridConfig(JSON.stringify({
    tags: [{ name: "big", negative: "small" }, { name: "tall" }],
    groups: [3],
  }));
  assert.deepEqual(writeFor(set, "positive"),
                   { pos: ["big", "tall"], neg: [], groups: [3] });
  assert.deepEqual(writeFor(set, "negative"),
                   { pos: [], neg: [], groups: [] });
  assert.equal(writeIsEmpty(writeFor(set, "negative")), true);
  // "Both" is then the two answers at once with nothing on one side — a
  // fourth button spelling "fits" — so it is not on offer.
  assert.equal(hasCounter(set), true, "the counter still READS as evidence");
  assert.equal(canSayBoth(set), false);
  assert.equal(canSayBoth(parseTagGridConfig(JSON.stringify({
    tags: [{ name: "big", negative: "small" }] }))), true);
  assert.deepEqual(offered("all", canSayBoth(set)),
                   ["positive", "negative", "none"],
                   "the answer is still OFFERED — it is a label, not a write");
});

test("the old one-tag shape becomes a set of one", () => {
  // The question was one tag with a counter and two write sets beside it.
  // What that config MEANT is the tag, its counter, whatever else "fits"
  // wrote, and the groups it joined.
  const c = parseTagGridConfig(JSON.stringify({
    tag: "cat", negativeTag: "not_cat",
    fitsWrite: { pos: ["cat", "animal"], neg: ["empty"], groups: [3] },
    noWrite: { pos: [], neg: ["cat"], groups: [] },
  }));
  assert.deepEqual(c.tags, [{ name: "cat", negative: "not_cat" },
                            { name: "animal", negative: "" }]);
  assert.deepEqual(c.groups, [3]);
  assert.deepEqual(writeFor(c, "positive"),
                   { pos: ["cat", "animal"], neg: [], groups: [3] });
  // Two tags, so its "doesn't fit" writes nothing — what that old config
  // asked is a conjunction now, and a conjunction's "no" names no tag.
  assert.deepEqual(writeFor(c, "negative"),
                   { pos: [], neg: [], groups: [] });
  // The plainest old config of all.
  const one = parseTagGridConfig(JSON.stringify({ tag: "cat" }));
  assert.deepEqual(one.tags, [{ name: "cat", negative: "" }]);
});

test("the set is edited by name, and a rename keeps the slot", () => {
  let c = withTag(parseTagGridConfig(null), "cat");
  c = withTag(c, "dog");
  assert.equal(withTag(c, "cat"), c, "a name already in the set changes nothing");
  assert.deepEqual(tagNames(c), ["cat", "dog"]);
  c = withCounter(c, "cat", "not_cat");
  assert.deepEqual(wireTags(c), [{ name: "cat", negative: "not_cat" },
                                 { name: "dog", negative: "" }]);
  // THE COUNTERS GO WITH THE ANSWER: with "doesn't fit" off, a tag nothing
  // will write must not decide the pool either.
  assert.deepEqual(wireTags(c, false), [{ name: "cat", negative: "" },
                                        { name: "dog", negative: "" }]);
  c = renameTag(c, "cat", "kitten");
  assert.deepEqual(c.tags, [{ name: "kitten", negative: "not_cat" },
                            { name: "dog", negative: "" }]);
  assert.equal(renameTag(c, "kitten", "dog"), c, "onto a taken name: nothing");
  assert.deepEqual(tagNames(withoutTag(c, "kitten")), ["dog"]);
  // A tag is no counter for itself.
  assert.equal(withCounter(c, "dog", "dog").tags[1].negative, "");
});
