import { test } from "node:test";
import assert from "node:assert/strict";
import { groupOptions } from "./groupOptions.ts";

const TREE = [
  { name: "Trips", children: [
    { name: "2024", children: [{ name: "Paris" }] },
    { name: "2023" },
  ] },
  { name: "Work", children: [{ name: "2024" }] },
  { name: "Samples" },
];

test("the rows are the tree's own order, not an alphabet", () => {
  assert.deepEqual(groupOptions(TREE).map((o) => o.name),
    ["Trips", "Trips/2024", "Trips/2024/Paris", "Trips/2023", "Work", "Work/2024", "Samples"]);
});

test("every row commits its FULL path — a group is its whole address", () => {
  // Owner 2026-09: a bare name is the root-level group of that name and
  // nothing else, so a unique deeper name still commits with its ancestors.
  const by = new Map(groupOptions(TREE).map((o) => [o.hint ?? "", o.name]));
  assert.equal(by.get(""), "Samples");                     // a root
  assert.equal(by.get("Trips › 2024"), "Trips/2024/Paris"); // never a bare "Paris"
});

test("a shared name is told apart by the path, as everything is", () => {
  const rows = groupOptions(TREE);
  const twentyFours = rows.filter((o) => o.name.endsWith("2024"));
  assert.deepEqual(twentyFours.map((o) => o.name),
                   ["Trips/2024", "Work/2024"]);
});

test("the ancestors are the hint, on every row that has any", () => {
  const rows = groupOptions(TREE);
  assert.equal(rows.find((o) => o.name === "Trips/2024/Paris")?.hint, "Trips › 2024");
  assert.equal(rows.find((o) => o.name === "Trips")?.hint, "");
});

test("three of a name are three paths", () => {
  const rows = groupOptions([
    { name: "A", children: [{ name: "x", children: [{ name: "n" }] }] },
    { name: "B", children: [{ name: "x", children: [{ name: "n" }] }] },
    { name: "C", children: [{ name: "n" }] },
  ]);
  assert.deepEqual(rows.map((o) => o.name),
    ["A", "A/x", "A/x/n", "B", "B/x", "B/x/n", "C", "C/n"]);
});

test("an empty tree is an empty list", () => {
  assert.deepEqual(groupOptions([]), []);
});
