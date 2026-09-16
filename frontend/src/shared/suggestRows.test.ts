import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  buildSuggestRows, clampHighlight, defaultHighlight, stepHighlight,
} from "./suggestRows.ts";

const items = (...ns: string[]) => ns.map((name) => ({ name }));

test("the Create row is FIRST and the first MATCH is the default highlight", () => {
  const rows = buildSuggestRows(items("blue_hair", "blue_house"), "blue_h");
  assert.equal(rows[0].kind, "create");
  assert.equal(defaultHighlight(rows), 1);
  const hi = clampHighlight(null, rows);
  const row = rows[hi];
  assert.equal(row.kind === "match" && row.item.name, "blue_hair");
});

test("Create is one ArrowUp from the default, and the top clamps", () => {
  const rows = buildSuggestRows(items("blue_hair"), "blue_h");
  const hi = clampHighlight(null, rows);
  assert.equal(rows[stepHighlight(hi, -1, rows.length)].kind, "create");
  assert.equal(stepHighlight(0, -1, rows.length), 0);
});

test("with no match the Create row is the only row and the default", () => {
  const rows = buildSuggestRows([], "brand_new");
  assert.equal(rows.length, 1);
  assert.equal(defaultHighlight(rows), 0);
});

test("an ACTION is never what Enter does to a name that was typed out", () => {
  // The face namer's shape: [Unnamed, Create "new_person"]. Nothing in the
  // catalog matches, and the answer being given is the one in the field.
  const rows = buildSuggestRows([], "new_person",
                                [{ id: "unnamed", label: "Unnamed" }]);
  assert.equal(rows[0].kind, "action");
  assert.equal(defaultHighlight(rows), 1);
  const row = rows[clampHighlight(null, rows)];
  assert.equal(row.kind === "create" && row.name, "new_person");
});

test("…and with a match under both, the match still leads", () => {
  const rows = buildSuggestRows(items("alice"), "ali",
                                [{ id: "unnamed", label: "Unnamed" }]);
  assert.equal(defaultHighlight(rows), 2);
});

test("an action alone is still the default — it is the only answer there is",
     () => {
  const rows = buildSuggestRows([], null, [{ id: "unnamed", label: "Unnamed" }]);
  assert.equal(defaultHighlight(rows), 0);
});

test("with no Create row the default is the first match", () => {
  const rows = buildSuggestRows(items("a", "b"), null);
  assert.equal(rows.length, 2);
  assert.equal(defaultHighlight(rows), 0);
});

test("ArrowDown clamps at the last row", () => {
  const rows = buildSuggestRows(items("a", "b"), "x");
  assert.equal(stepHighlight(2, 1, rows.length), 2);
  assert.equal(stepHighlight(1, 1, rows.length), 2);
});

test("a row the host calls unselectable is stepped OVER, never landed on", () => {
  // [create, title, a, title, b] — the T overlay's shape: sections with
  // headings nobody can pick.
  const rows = buildSuggestRows(items("t1", "a", "t2", "b"), "x");
  const titles = new Set([1, 3]);
  const ok = (i: number) => !titles.has(i);
  // The default skips the Create row AND the heading under it.
  assert.equal(defaultHighlight(rows, ok), 2);
  assert.equal(stepHighlight(2, 1, rows.length, ok), 4);
  assert.equal(stepHighlight(4, -1, rows.length, ok), 2);
  // Up from the first match is the Create row; there is nothing above it.
  assert.equal(stepHighlight(2, -1, rows.length, ok), 0);
  assert.equal(stepHighlight(0, -1, rows.length, ok), 0);
  // A remembered highlight that lands on a heading moves off it.
  assert.equal(clampHighlight(3, rows, ok), 4);
  assert.equal(clampHighlight(9, rows, ok), 4);
});

test("with nothing selectable but the Create row, the Create row is the default", () => {
  const rows = buildSuggestRows(items("title"), "brand_new");
  const ok = (i: number) => i === 0;
  assert.equal(defaultHighlight(rows, ok), 0);
  assert.equal(stepHighlight(0, 1, rows.length, ok), 0);
});

test("a remembered highlight is clamped when the rows shrink", () => {
  const rows = buildSuggestRows(items("a"), null);
  assert.equal(clampHighlight(7, rows), 0);
  assert.equal(clampHighlight(-3, rows), 0);
});

test("an empty list steps nowhere", () => {
  assert.equal(stepHighlight(0, 1, 0), 0);
  assert.deepEqual(buildSuggestRows([], null), []);
});

import { inputKeyAction } from "./suggestRows.ts";

test("a key in the field: arrows step, Enter picks or commits, Escape is two-stage", () => {
  const up = { listOpen: true, hasRows: true };
  const shut = { listOpen: false, hasRows: false };
  const k = (key: string, shiftKey = false) => ({ key, shiftKey });
  assert.equal(inputKeyAction(k("ArrowDown"), shut), "step", "an arrow asks a dismissed list back");
  assert.equal(inputKeyAction(k("Enter"), up), "pick");
  assert.equal(inputKeyAction(k("Enter"), shut), "commitTyped");
  assert.equal(inputKeyAction(k("Enter"), { listOpen: true, hasRows: false }), "commitTyped");
  assert.equal(inputKeyAction(k("Escape"), up), "dismiss");
  assert.equal(inputKeyAction(k("Escape"), shut), "cancel");
  assert.equal(inputKeyAction(k("Escape"), { ...shut, alsoOpen: true }), "dismiss", "a tree counts as a list");
  assert.equal(inputKeyAction(k("Tab"), up), "none");
  assert.equal(inputKeyAction(k("Tab"), { ...up, tabPicks: true }), "pick");
  assert.equal(inputKeyAction(k("Tab", true), { ...up, tabPicks: true }), "none", "shift-tab is the page's");
  assert.equal(inputKeyAction(k("a"), up), "none");
});
