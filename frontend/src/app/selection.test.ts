// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  HISTORY_MAX_ENTRY,
  navWindow,
  pushHistory,
  sameEntry,
  selectionUpdate,
} from "./selection.ts";

// ---- selectionUpdate --------------------------------------------------------

test("selectionUpdate: same ids in any order is a no-op", () => {
  const prev = [1, 2, 3];
  const set = new Set(prev);
  assert.equal(selectionUpdate(prev, set, [3, 1, 2]), null);
  assert.equal(selectionUpdate(prev, set, [1, 2, 3]), null);
});

test("selectionUpdate: a real change returns a lockstep pair", () => {
  const prev = [1, 2];
  const set = new Set(prev);
  const u = selectionUpdate(prev, set, [2, 5]);
  assert.ok(u);
  assert.deepEqual(u.list, [2, 5]);
  assert.deepEqual([...u.set].sort(), [2, 5]);
});

test("selectionUpdate: a duplicated next is not the previous selection", () => {
  // A window assembled across two library revisions (external importer
  // mid-run) can hand a marquee the same id twice: [1, 1] must not read as
  // "still [1, 2]", and what is stored must hold each id once.
  const prev = [1, 2];
  const set = new Set(prev);
  const u = selectionUpdate(prev, set, [1, 1]);
  assert.ok(u);
  assert.deepEqual(u.list, [1]);
  assert.deepEqual([...u.set], [1]);
});

test("selectionUpdate: the stored list is deduplicated", () => {
  const u = selectionUpdate([], new Set<number>(), [7, 7, 8]);
  assert.ok(u);
  assert.deepEqual(u.list, [7, 8]);
  assert.deepEqual([...u.set].sort(), [7, 8]);
});

test("selectionUpdate: length change alone is a change", () => {
  const prev = [1, 2, 3];
  const set = new Set(prev);
  const u = selectionUpdate(prev, set, [1, 2]);
  assert.ok(u);
  assert.deepEqual(u.list, [1, 2]);
});

test("selectionUpdate: empty to empty is a no-op, empty to some is not", () => {
  const empty: number[] = [];
  const set = new Set<number>();
  assert.equal(selectionUpdate(empty, set, []), null);
  assert.ok(selectionUpdate(empty, set, [7]));
});

// ---- pushHistory ------------------------------------------------------------

test("pushHistory: appends and keeps order", () => {
  const past = pushHistory([[1]], [2, 3]);
  assert.deepEqual(past, [[1], [2, 3]]);
});

test("pushHistory: drops the oldest entries past the cap", () => {
  let past: number[][] = [];
  for (let i = 0; i < 60; i++) past = pushHistory(past, [i], 50);
  assert.equal(past.length, 50);
  assert.deepEqual(past[0], [10]); // entries 0..9 dropped
  assert.deepEqual(past[49], [59]);
});

test("pushHistory: skips oversized entries, returning the stack unchanged", () => {
  const before = [[1]];
  const huge = new Array(HISTORY_MAX_ENTRY + 1).fill(0);
  const after = pushHistory(before, huge);
  assert.equal(after, before); // same reference: nothing was recorded
});

test("pushHistory: an entry exactly at the limit is still recorded", () => {
  const atLimit = new Array(HISTORY_MAX_ENTRY).fill(0);
  const after = pushHistory([], atLimit);
  assert.equal(after.length, 1);
});

// ---- navWindow --------------------------------------------------------------

const range = (n: number) => Array.from({ length: n }, (_, i) => i);

test("navWindow: short lists are returned whole (copied)", () => {
  const ids = range(100);
  const w = navWindow(ids, 50, 500);
  assert.deepEqual(w, ids);
  assert.notEqual(w, ids); // a copy, safe to stash
});

test("navWindow: centers on the opened id", () => {
  const ids = range(10_000);
  const w = navWindow(ids, 5_000, 500);
  assert.equal(w.length, 1001);
  assert.equal(w[0], 4_500);
  assert.equal(w[1000], 5_500);
  assert.ok(w.includes(5_000));
});

test("navWindow: keeps its full width at either end", () => {
  const ids = range(10_000);
  const head = navWindow(ids, 3, 500);
  assert.equal(head.length, 1001);
  assert.equal(head[0], 0);
  const tail = navWindow(ids, 9_998, 500);
  assert.equal(tail.length, 1001);
  assert.equal(tail[1000], 9_999);
});

test("navWindow: unknown center falls back to the head", () => {
  const ids = range(5_000);
  const w = navWindow(ids, -1, 500);
  assert.equal(w[0], 0);
  assert.equal(w.length, 1001);
});

test("pushHistory: an entry equal to the top is not recorded", () => {
  // X -> clear -> X -> Y records the prior selection twice with only an
  // EMPTY state (which nothing records) between them; stacked, Back walked
  // to the selection already on screen.
  let past = pushHistory([], [7, 3]);
  past = pushHistory(past, [3, 7]); // order-insensitively the same selection
  assert.equal(past.length, 1);
  past = pushHistory(past, [3]);
  past = pushHistory(past, [7, 3]); // the same ids AFTER a different entry: kept
  assert.deepEqual(past, [[7, 3], [3], [7, 3]]);
});

test("sameEntry: order-insensitive, length-strict", () => {
  assert.ok(sameEntry([1, 2, 3], [3, 2, 1]));
  assert.ok(!sameEntry([1, 2], [1, 2, 3]));
  assert.ok(!sameEntry([1, 2, 4], [1, 2, 3]));
  assert.ok(sameEntry([], []));
});
