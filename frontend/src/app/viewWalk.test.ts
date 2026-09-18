import test from "node:test";
import assert from "node:assert/strict";

import { nextDistinctIndex, occurrenceIndex } from "./viewWalk.ts";

// A chapter of 33 cards whose blank page (item 900) sits at positions 2 and
// 30 — the shape the bug was reported against.
const IDS = [
  ...Array.from({ length: 2 }, (_, i) => 100 + i),   // 0, 1
  900,                                              // 2
  ...Array.from({ length: 27 }, (_, i) => 200 + i),  // 3..29
  900,                                              // 30
  300, 301,                                         // 31, 32
];
const MEMBERS = IDS.map((_, i) => 500 + i);

test("a repeated page is walked where it stands, not where its copy is", () => {
  // The report: 0 → 1 → 2 → 31, because the walk asked "where is item 900"
  // and was told 30.
  assert.equal(nextDistinctIndex(IDS, 1, 1), 2);
  assert.equal(nextDistinctIndex(IDS, 2, 1), 3);
  assert.equal(nextDistinctIndex(IDS, 29, 1), 30);
  assert.equal(nextDistinctIndex(IDS, 30, 1), 31);
  // …and the same going back.
  assert.equal(nextDistinctIndex(IDS, 30, -1), 29);
  assert.equal(nextDistinctIndex(IDS, 3, -1), 2);
  assert.equal(nextDistinctIndex(IDS, 2, -1), 1);
});

test("a run of the same picture is one stop", () => {
  const run = [10, 20, 20, 20, 30];
  assert.equal(nextDistinctIndex(run, 1, 1), 4);
  assert.equal(nextDistinctIndex(run, 3, -1), 0);
  // Entering the run from either side still stops in it once.
  assert.equal(nextDistinctIndex(run, 0, 1), 1);
  assert.equal(nextDistinctIndex(run, 4, -1), 3);
});

test("off either end there is no next", () => {
  assert.equal(nextDistinctIndex(IDS, IDS.length - 1, 1), -1);
  assert.equal(nextDistinctIndex(IDS, 0, -1), -1);
  assert.equal(nextDistinctIndex(IDS, -1, 1), -1);
  assert.equal(nextDistinctIndex(IDS, 2, 0), -1);
  assert.equal(nextDistinctIndex([], 0, 1), -1);
  // A view of one picture repeated has nowhere to go.
  assert.equal(nextDistinctIndex([7, 7, 7], 0, 1), -1);
});

test("the occurrence the selection names is where the walk is", () => {
  // Both copies of item 900 are the same id; only the member says which.
  assert.equal(occurrenceIndex(IDS, MEMBERS, 900, 530), 30);
  assert.equal(occurrenceIndex(IDS, MEMBERS, 900, 502), 2);
  // Nothing named: the id answers, which outside a sequence view is exact.
  assert.equal(occurrenceIndex(IDS, MEMBERS, 301, null), 32);
  // A member the view no longer holds falls back to the id.
  assert.equal(occurrenceIndex(IDS, MEMBERS, 900, 999), 2);
  assert.equal(occurrenceIndex(IDS, MEMBERS, 12345, null), -1);
  assert.equal(occurrenceIndex(IDS, MEMBERS, null, null), -1);
});
