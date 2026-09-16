import test from "node:test";
import assert from "node:assert/strict";

import { exactFirst } from "./exactFirst.ts";

const names = (rows: Array<{ name: string }>) => rows.map((r) => r.name);
const rows = (...ns: string[]) => ns.map((name) => ({ name }));

test("the exact match leads, and the rest keeps its order", () => {
  const list = rows("aardvark", "abs", "a", "banana");
  assert.deepEqual(names(exactFirst(list, "a", (r) => [r.name])),
                   ["a", "aardvark", "abs", "banana"]);
});

test("no search, and the same array comes back", () => {
  const list = rows("b", "a");
  assert.equal(exactFirst(list, "   ", (r) => [r.name]), list);
});

test("no exact match, and the same array comes back", () => {
  const list = rows("aardvark", "abs");
  assert.equal(exactFirst(list, "a", (r) => [r.name]), list);
});

test("case and surrounding space do not matter", () => {
  const list = rows("Alpha beta", "ALPHA");
  assert.deepEqual(names(exactFirst(list, " alpha ", (r) => [r.name])),
                   ["ALPHA", "Alpha beta"]);
});

test("a row is found by ANY of its names", () => {
  // A subject is listed under its display name and assigns its tag; either
  // one typed in full is the row that was asked for.
  const list = [
    { name: "Alice Liddell", tag: "subject:alice" },
    { name: "Someone", tag: "alice" },
  ];
  assert.deepEqual(exactFirst(list, "alice", (r) => [r.name, r.tag])[0].name,
                   "Someone");
});

test("several exact matches keep their relative order", () => {
  const list = [{ name: "a", id: 1 }, { name: "ab", id: 2 }, { name: "A", id: 3 }];
  assert.deepEqual(exactFirst(list, "a", (r) => [r.name]).map((r) => r.id),
                   [1, 3, 2]);
});

test("a missing name is not a match", () => {
  const list = [{ name: null as string | null }, { name: "x" }];
  assert.equal(exactFirst(list, "x", (r) => [r.name])[0].name, "x");
  assert.equal(exactFirst(list, "", (r) => [r.name])[0].name, null);
});
