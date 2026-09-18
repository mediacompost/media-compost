import { test } from "node:test";
import assert from "node:assert/strict";
import {
  QA_NUM_MAX, assignNumber, itemHasAllQaTags, itemHasAnyQaTag,
  lowestFreeNumber, newQaSet, numberedSets, parseQaSets, qaSetDone,
  qaSetMatch, serializeQaSets, setIsEmpty, sortSets, type QaSet,
} from "./qaSets.ts";

const set = (pos: string[], neg: string[] = [], num: number | null = null): QaSet =>
  ({ ...newQaSet(num), pos, neg });
/** The persisted shape — ids are session-local and never written, so any
 *  comparison across a parse strips them. */
const bare = (sets: QaSet[]) => sets.map(({ id: _id, ...rest }) => rest);
const dt = (pos: string[], neg: string[] = []) => [
  ...pos.map((name) => ({ name, negative: false, count: 0 })),
  ...neg.map((name) => ({ name, negative: true, count: 0 })),
];
/** The membership lists of a selection that is in NO group — spelled here
 *  rather than defaulted in `qaSetMatch`, which is what a caller leaving
 *  them off used to mean and is the whole of the bug that made them
 *  required (a set of one group read as carried by everything). */
const inNoGroup = (per: unknown[]) => per.map(() => [] as number[]);

// ---- numbers ---------------------------------------------------------------

test("lowestFreeNumber fills gaps first and answers null when all are taken", () => {
  assert.equal(lowestFreeNumber([]), 1);
  assert.equal(lowestFreeNumber([set([], [], 1), set([], [], 3)]), 2);
  const full = Array.from({ length: QA_NUM_MAX }, (_, i) => set([], [], i + 1));
  assert.equal(lowestFreeNumber(full), null);
  assert.equal(lowestFreeNumber([...full, set([], [], null)]), null);
});

test("numberedSets keeps only numbered sets, in number order", () => {
  const sets = [set(["c"], [], 3), set(["x"]), set(["a"], [], 1)];
  assert.deepEqual(numberedSets(sets).map((s) => s.num), [1, 3]);
  assert.deepEqual(numberedSets(sets).map((s) => s.pos[0]), ["a", "c"]);
});

test("assignNumber to a free number just moves it", () => {
  const sets = [set(["a"], [], 1), set(["b"], [], 2)];
  const out = assignNumber(sets, 0, 5);
  assert.deepEqual(out.map((s) => s.num), [5, 2]);
  // The input is untouched (fresh objects throughout).
  assert.deepEqual(sets.map((s) => s.num), [1, 2]);
});

test("assignNumber to a taken number EXCHANGES the two", () => {
  const sets = [set(["a"], [], 1), set(["b"], [], 2)];
  const out = assignNumber(sets, 0, 2);
  assert.deepEqual(out.map((s) => s.num), [2, 1]);
});

test("an unnumbered set taking a number hands its nothing back", () => {
  const sets = [set(["a"], [], null), set(["b"], [], 2)];
  const out = assignNumber(sets, 0, 2);
  // The other set inherits the old num — null — so it becomes unnumbered.
  assert.deepEqual(out.map((s) => s.num), [2, null]);
});

test("assignNumber to null unassigns without touching anyone else", () => {
  const sets = [set(["a"], [], 1), set(["b"], [], 2)];
  const out = assignNumber(sets, 1, null);
  assert.deepEqual(out.map((s) => s.num), [1, null]);
});

test("assignNumber is a no-op (same identity) when nothing changes", () => {
  const sets = [set(["a"], [], 1)];
  assert.equal(assignNumber(sets, 0, 1), sets);
  assert.equal(assignNumber(sets, 5, 2), sets); // no such set
  assert.equal(assignNumber(sets, 0, 0), sets); // out of range
  assert.equal(assignNumber(sets, 0, QA_NUM_MAX + 1), sets);
  assert.equal(assignNumber(sets, 0, 1.5), sets);
});

// ---- matching --------------------------------------------------------------

test("full: every item carries the whole set with the right signs", () => {
  const s = set(["cat"], ["dog"]);
  const per = [dt(["cat"], ["dog"]), dt(["cat", "x"], ["dog"])];
  assert.equal(qaSetMatch(per, s, inNoGroup(per)), "full");
});

test("partial: some item carries some of it; a sign mismatch is no match", () => {
  const s = set(["cat"], ["dog"]);
  assert.equal(qaSetMatch([dt(["cat"]), dt([])], s, [[], []]), "partial");
  // `dog` carried POSITIVE satisfies nothing of a set that wants it negative.
  assert.equal(qaSetMatch([dt(["dog"])], s, [[]]), "none");
  assert.equal(qaSetMatch([dt([], ["cat"])], s, [[]]), "none");
});

test("an empty set never matches — a green row must promise a real removal", () => {
  assert.equal(qaSetMatch([dt(["cat"])], set([]), [[]]), "none");
  // The vacuous truth guarded against — and it is vacuous over the GROUPS
  // too, which is why a caller may not leave them out.
  assert.ok(itemHasAllQaTags(dt(["cat"]), [], [], [], []));
});

test("an empty selection matches nothing", () => {
  assert.equal(qaSetMatch([], set(["cat"]), []), "none");
});

test("an unloaded item ([]) demotes full to partial", () => {
  const s = set(["cat"]);
  assert.equal(qaSetMatch([dt(["cat"]), []], s, [[], []]), "partial");
});

test("qaSetDone names what EVERY item already carries, sign included", () => {
  const s = set(["cat", "bird"], ["dog"]);
  const per = [dt(["cat", "bird"], ["dog"]), dt(["cat"], ["dog"])];
  assert.deepEqual([...qaSetDone(per, s, inNoGroup(per))].sort(),
                   ["+cat", "-dog"]);
  // A sign mismatch is not done, and an empty selection answers empty.
  assert.deepEqual([...qaSetDone([dt(["dog"])], s, [[]])], []);
  assert.deepEqual([...qaSetDone([], s, [])], []);
});

test("qaSetDone names a GROUP every item is already in", () => {
  const s = { ...newQaSet(1), pos: ["cat"], groups: [7, 9] };
  const per = [dt(["cat"]), dt(["cat"])];
  // 7 is shared, 9 is not — the row greys the one the press need not write.
  assert.deepEqual([...qaSetDone(per, s, [[7, 9], [7]])].sort(),
                   ["+cat", "g7"]);
  assert.deepEqual([...qaSetDone(per, s, [[], []])], ["+cat"]);
});

test("itemHasAnyQaTag reads signs like the full check does", () => {
  assert.ok(itemHasAnyQaTag(dt([], ["dog"]), ["cat"], ["dog"], [], []));
  assert.ok(!itemHasAnyQaTag(dt(["dog"]), ["cat"], ["dog"], [], []));
});

// ---- order -----------------------------------------------------------------

test("sortSets: numbered ascending, unnumbered after, ties stable", () => {
  const sets = [set(["x"]), set(["c"], [], 7), set(["y"]), set(["a"], [], 2)];
  assert.deepEqual(sortSets(sets).map((s) => s.pos[0]), ["a", "c", "x", "y"]);
  // The input keeps its own order.
  assert.deepEqual(sets.map((s) => s.pos[0]), ["x", "c", "y", "a"]);
});

// ---- persistence -----------------------------------------------------------

test("a round trip keeps sets and numbers, in the invariant order", () => {
  const sets = [set(["a"], ["b"], 2), set(["c"]), set([], [], 7)];
  // Ids are minted fresh per session; the order comes back sorted (numbered
  // ascending, unnumbered after).
  assert.deepEqual(bare(parseQaSets(serializeQaSets(sets))),
    bare([sets[0], sets[2], sets[1]]));
});

test("the serialized form carries no session ids", () => {
  assert.ok(!serializeQaSets([set(["a"], [], 1)]).includes('"id"'));
});

test("garbage decodes to the one default set, never an empty list", () => {
  const def = [{ pos: [], neg: [], groups: [], num: 1 }];
  assert.deepEqual(bare(parseQaSets(null)), def);
  assert.deepEqual(bare(parseQaSets("")), def);
  assert.deepEqual(bare(parseQaSets("not json")), def);
  assert.deepEqual(bare(parseQaSets("{}")), def);
  assert.deepEqual(bare(parseQaSets("[]")), def);
  assert.deepEqual(bare(parseQaSets("[1, null, \"x\"]")), def);
});

test("a malformed entry degrades instead of throwing the list away", () => {
  const out = parseQaSets(JSON.stringify([
    { pos: ["a", "a", 3, "b"], neg: ["a", "c"], num: 2 },
    { pos: "nope", neg: { x: 1 }, num: "2" },
    { pos: ["d"], num: 99 },
  ]));
  // Dupes gone, `a` kept where it was first seen, bad shapes emptied/nulled.
  assert.deepEqual(bare(out), [
    { pos: ["a", "b"], neg: ["c"], groups: [], num: 2 },
    { pos: [], neg: [], groups: [], num: null },
    { pos: ["d"], neg: [], groups: [], num: null },
  ]);
});

test("a duplicate number keeps its first carrier", () => {
  const out = parseQaSets(JSON.stringify([
    { pos: ["a"], neg: [], num: 3 },
    { pos: ["b"], neg: [], num: 3 },
  ]));
  assert.deepEqual(out.map((s) => s.num), [3, null]);
});

test("setIsEmpty reads both lists", () => {
  assert.ok(setIsEmpty(set([])));
  assert.ok(!setIsEmpty(set(["a"])));
  assert.ok(!setIsEmpty(set([], ["a"])));
});

test("a set's groups round-trip and count toward emptiness and matching", () => {
  const g = { ...newQaSet(1), pos: ["a"], groups: [7, 7, 3] };
  const back = parseQaSets(serializeQaSets([g]));
  assert.deepEqual(back[0].groups, [7, 3]);
  const membersOnly = { ...newQaSet(null), groups: [7] };
  assert.equal(setIsEmpty(membersOnly), false);
  // A set's groups are part of the question, always: the memberships say
  // which items carry it, and an item in none of them carries none of it
  // however many of its tags it has.
  const dt = [{ name: "a", negative: false, count: 1 }];
  assert.equal(qaSetMatch([dt], g, [[7, 3]]), "full");
  assert.equal(qaSetMatch([dt], g, [[7]]), "partial");
  assert.equal(qaSetMatch([dt], g, [[]]), "partial");
  // A set of GROUPS ALONE is the case the sidebar's button got wrong: asked
  // by the tags it has none, so "every tag is there" was vacuously true and
  // the button offered to remove a membership nothing had.
  assert.equal(qaSetMatch([dt], membersOnly, [[]]), "none");
  assert.equal(qaSetMatch([dt], membersOnly, [[7]]), "full");
  assert.equal(qaSetMatch([dt, dt], membersOnly, [[7], []]), "partial");
});
