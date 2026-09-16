import { test } from "node:test";
import assert from "node:assert/strict";

import {
  CHECK_W, LIBRARY_COLUMNS, SET_COLUMNS, columnsFor, gridTemplate, shownColumns,
} from "./tagSetColumns.ts";

/** A row as the list hands it over: only its numbers matter here. */
const row = (numbers: Record<string, number | null>) => ({ numbers });

test("which columns a list draws is which tag set it is showing", () => {
  // The library counts PICTURES, three ways.
  assert.deepEqual(columnsFor(null).map((c) => c.key),
                   ["positive", "implicit", "negative"]);
  // An imported set counts neither: it holds no pictures, so its pair is
  // what this library has under the name and what the file claimed.
  assert.deepEqual(columnsFor(7).map((c) => c.key), ["library", "count"]);
  assert.equal(columnsFor(null), LIBRARY_COLUMNS);
  assert.equal(columnsFor(7), SET_COLUMNS);
});

test("only a column that counts pictures offers to narrow the library", () => {
  // `press` is what makes a figure a link into the grid, so it can only sit
  // on a count of items — a set's `count` is what a booru file said, and
  // there is nothing here to show for it.
  assert.deepEqual(LIBRARY_COLUMNS.filter((c) => c.press).map((c) => c.key),
                   ["positive", "negative"]);
  assert.deepEqual(SET_COLUMNS.filter((c) => c.press), []);
});

test("a column nothing has a figure in is dropped, and the rest keep their order", () => {
  const rows = [row({ positive: 3, implicit: 0, negative: 1 })];
  // `implicit` is `onlyWhenUsed`: a column of blanks says nothing, and these
  // are narrow, so its absence is what gives the name its room.
  assert.deepEqual(shownColumns(LIBRARY_COLUMNS, rows).map((c) => c.key),
                   ["positive", "negative"]);
  // One row with a figure is enough, and the column comes back where the
  // TABLE puts it rather than at the end.
  const used = [...rows, row({ positive: 1, implicit: 2, negative: 0 })];
  assert.deepEqual(shownColumns(LIBRARY_COLUMNS, used).map((c) => c.key),
                   ["positive", "implicit", "negative"]);
});

test("no rows at all drops every optional column, and keeps every other", () => {
  assert.deepEqual(shownColumns(LIBRARY_COLUMNS, []).map((c) => c.key),
                   ["positive", "negative"]);
});

test("null is no figure, not a zero that throws", () => {
  // `TagRow.numbers` is `Record<string, number | null>`: null is "no figure
  // at all", which only a SET's columns can be — a library column counts
  // pictures, so a name with no assignment counts zero rather than nothing.
  // It reaches this filter all the same, and must read as unused.
  assert.deepEqual(
    shownColumns(LIBRARY_COLUMNS, [row({ implicit: null })]).map((c) => c.key),
    ["positive", "negative"]);
  // A row that carries no `numbers` at all is the same answer.
  assert.deepEqual(
    shownColumns(LIBRARY_COLUMNS, [{}]).map((c) => c.key),
    ["positive", "negative"]);
});

test("a set's columns are never dropped, however empty", () => {
  // Neither is `onlyWhenUsed`: a set has exactly two numbers and both are
  // part of what the row is FOR — "the library has none of this" is an
  // answer, and a column that vanished when it was true would hide it.
  assert.deepEqual(
    shownColumns(SET_COLUMNS, [row({ library: null, count: null })])
      .map((c) => c.key),
    ["library", "count"]);
  assert.deepEqual(shownColumns(SET_COLUMNS, []).map((c) => c.key),
                   ["library", "count"]);
});

test("the grid is the checkbox, the name, then one track per column", () => {
  // The 26px track leads again (owner 2026-09): a list of a hundred
  // thousand names needs a select-all a person can see — the header's box
  // — and a row's box adds that row without disturbing the run already
  // picked. `CHECK_W` is that track, so the header and every row agree.
  const got = gridTemplate(LIBRARY_COLUMNS);
  assert.equal(got, `${CHECK_W}px minmax(0, 2fr) 88px 88px 88px`);
  // The NAME follows it, and it is the flexible one: the columns are
  // fixed-width tracks in the order the table declares them.
  assert.ok(got.startsWith("26px minmax(0, 2fr) "));
  assert.deepEqual(got.split(" ").slice(3), ["88px", "88px", "88px"]);
});

test("the category track gives before the name does", () => {
  // `minmax(0, …)` on the category and a plain `2fr` on the name: a path is
  // a hint, the name is the row, so a narrow window takes the path apart
  // first.
  assert.equal(gridTemplate(SET_COLUMNS, { category: 140 }),
               "26px minmax(0, 2fr) minmax(0, 140px) 84px 84px");
  // Absent, null and 0 all mean "no category column" — the caller passes
  // `showCategory ? catW : null`.
  const none = "26px minmax(0, 2fr) 84px 84px";
  assert.equal(gridTemplate(SET_COLUMNS), none);
  assert.equal(gridTemplate(SET_COLUMNS, { category: null }), none);
  assert.equal(gridTemplate(SET_COLUMNS, { category: 0 }), none);
});

test("the name track can be given a floor", () => {
  assert.equal(gridTemplate(SET_COLUMNS, { tagMin: 220 }),
               "26px minmax(220px, 2fr) 84px 84px");
  assert.equal(gridTemplate([], { tagMin: 220, category: 140 }),
               "26px minmax(220px, 2fr) minmax(0, 140px)");
});

test("no columns is still a grid", () => {
  // The Meta list draws its own template, but an empty column table must not
  // produce a trailing space or an empty track.
  assert.equal(gridTemplate([]), "26px minmax(0, 2fr)");
});
