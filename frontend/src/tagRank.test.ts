/** The autocomplete ranking rule — exact first, then match position, then
 *  the source's own (count) order. Pure, so the whole answer space is here.
 *  The cases from the retired `tagSuggest.ts` live here too: position is a
 *  strict refinement of its exact / prefix / substring tiers. */
import { strict as assert } from "node:assert";
import { test } from "node:test";

import { SUGGEST_CAP, rankTagMatches } from "./app/tagRank.ts";

const names = (rows: { name: string }[]) => rows.map((r) => r.name);
const src = (...ns: string[]) => ns.map((name) => ({ name }));

test("the exact name beats a more popular near-miss", () => {
  // Source arrives count-ordered: football (100) before ball (10).
  const got = rankTagMatches(src("football", "ball"), "ball", [], 6);
  assert.deepEqual(names(got), ["ball", "football"]);
});

test("an exact match outranks any number of busier substring matches", () => {
  // The live bug: six usage-ranked substring matches filled the cap and the
  // exact name — whose create row is suppressed because it exists — fell off
  // the list entirely, so "test" could not be added at all.
  const source = src("contest", "cutest", "testicles", "test_tube",
                     "protest", "attestation", "test");
  assert.equal(names(rankTagMatches(source, "test", [], 6))[0], "test");
});

test("an earlier match position beats a higher count", () => {
  // 123_abc (5 uses) arrives before abc_123 (2 uses); the fragment sits at
  // index 0 of abc_123, so it wins anyway.
  const got = rankTagMatches(src("123_abc", "abc_123"), "abc", [], 6);
  assert.deepEqual(names(got), ["abc_123", "123_abc"]);
});

test("prefix matches outrank substring matches, and earlier substrings earlier ones", () => {
  // `cutest` holds the fragment at 2, `contest` at 3 — the position rule is
  // finer than the tiers the retired ranker had, and it is the server's own
  // (`instr`), so a static and a remote source agree.
  const got = names(rankTagMatches(
    src("contest", "test_tube", "cutest", "tester"), "test", []));
  assert.deepEqual(got, ["test_tube", "tester", "cutest", "contest"]);
});

test("equal positions keep the source's count order", () => {
  const got = rankTagMatches(src("ball_red", "ball_blue"), "ball", [], 6);
  assert.deepEqual(names(got), ["ball_red", "ball_blue"]);
});

test("within a tier the source's own (usage) order is kept", () => {
  const got = names(rankTagMatches(
    src("test_b", "test_a", "atest_b", "atest_a"), "test", []));
  assert.deepEqual(got, ["test_b", "test_a", "atest_b", "atest_a"]);
});

test("the exact match survives a cap smaller than the match set", () => {
  // Capping before ranking would cut `ball` out of a list of two more
  // popular near-misses — the very case the exact rule exists for.
  const got = rankTagMatches(src("football", "ballroom", "ball"), "ball", [], 2);
  assert.deepEqual(names(got), ["ball", "ballroom"]);
});

test("existing names and non-matches are out; case is ignored", () => {
  const got = rankTagMatches(src("Ball", "cat", "ballroom"), "ball",
                             ["ballroom"], 6);
  assert.deepEqual(names(got), ["Ball"]);
});

test("existing names may arrive as a Set, and the cap holds after ranking", () => {
  const source = src("t1", "t2", "t3", "t4", "t5", "t6", "t7", "t");
  const got = names(rankTagMatches(source, "t", new Set(["t3"]), 6));
  assert.equal(got.length, 6);
  assert.equal(got[0], "t");
  assert.ok(!got.includes("t3"));
});

test("the default cap is SUGGEST_CAP", () => {
  const source = src(...Array.from({ length: SUGGEST_CAP + 5 },
                                    (_, i) => `t${i}`));
  assert.equal(rankTagMatches(source, "t", []).length, SUGGEST_CAP);
  assert.equal(SUGGEST_CAP, 30);
});

test("an empty query offers the catalog, in its own order, less what is taken", () => {
  // For a field over a SMALL catalog that lists itself on focus (the group
  // adder, the meta-tag adders); a host over a big one guards the needle.
  const rows = [{ name: "b" }, { name: "a" }, { name: "c" }];
  assert.deepEqual(rankTagMatches(rows, "", ["a"]).map((r) => r.name), ["b", "c"]);
  assert.deepEqual(rankTagMatches(rows, "", [], 2).map((r) => r.name), ["b", "a"]);
});
