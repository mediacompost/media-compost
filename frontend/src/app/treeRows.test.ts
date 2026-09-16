import { test } from "node:test";
import assert from "node:assert/strict";

import { ancestorsOf, flattenTree } from "./treeRows.ts";

const rows = [
  { id: 1, parent_id: null },      // japan
  { id: 2, parent_id: 1 },         //   tokyo
  { id: 3, parent_id: 2 },         //     tokyo tower
  { id: 4, parent_id: null },      // germany
];

test("children follow their parent, at a depth", () => {
  assert.deepEqual(flattenTree(rows).map((f) => [f.row.id, f.depth, f.kids]),
    [[1, 0, true], [2, 1, true], [3, 2, false], [4, 0, false]]);
});

test("a collapsed row keeps its own place and hides what is under it", () => {
  const flat = flattenTree(rows, new Set([2]));
  assert.deepEqual(flat.map((f) => f.row.id), [1, 2, 4]);
  // Still openable — the chevron is about having children, not showing them.
  assert.equal(flat.find((f) => f.row.id === 2)!.kids, true);
});

test("a row whose parent is not in the list is a ROOT, not a lost row", () => {
  // What filtering does: the parent no longer passes, the child still does.
  const flat = flattenTree(rows.filter((r) => r.id !== 2));
  assert.deepEqual(flat.map((f) => [f.row.id, f.depth]),
    [[1, 0], [3, 0], [4, 0]]);
});

test("a cycle shows each row once instead of hanging", () => {
  const looped = [
    { id: 1, parent_id: 2 },
    { id: 2, parent_id: 1 },
    { id: 3, parent_id: null },
  ];
  const flat = flattenTree(looped);
  assert.deepEqual(flat.map((f) => f.row.id).sort(), [1, 2, 3]);
});

test("a row is never its own parent", () => {
  const flat = flattenTree([{ id: 1, parent_id: 1 }]);
  assert.deepEqual(flat.map((f) => [f.row.id, f.depth]), [[1, 0]]);
});

test("siblings keep the order they were given — the list's own sort", () => {
  const unsorted = [
    { id: 9, parent_id: 1 }, { id: 1, parent_id: null }, { id: 5, parent_id: 1 },
  ];
  assert.deepEqual(flattenTree(unsorted).map((f) => f.row.id), [1, 9, 5]);
});

test("the ancestors are what has to be open for a row to be reachable", () => {
  assert.deepEqual(ancestorsOf(rows, 3), [2, 1]);
  assert.deepEqual(ancestorsOf(rows, 1), []);
});
