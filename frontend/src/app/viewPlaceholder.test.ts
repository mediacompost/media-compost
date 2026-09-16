// Run with: npm test.
import { test } from "node:test";
import assert from "node:assert/strict";
import { keepsPreviousPage, keepsPreviousPreview, keepsPreviousRuns } from "./viewPlaceholder.ts";

const key = (filters: string, tree: string, sort: string, page: number) =>
  ["items", filters, tree, sort, page] as const;

const LIB = JSON.stringify([[], false, false, false, false, false]);
const TRASH = JSON.stringify([[], false, false, true, false, false]);

test("typing in the search box keeps the previous answer", () => {
  // Same scope, same page: the items on screen are a stale answer to a live
  // question, which is what the placeholder is for.
  assert.equal(keepsPreviousPage(key(LIB, '"a"', "recent_desc", 1), LIB, 1), true);
});

test("a sort flip keeps it too", () => {
  assert.equal(keepsPreviousPage(key(LIB, "null", "name_asc", 1), LIB, 1), true);
});

test("switching to the Trash does NOT", () => {
  // The reported bug: the library's page 1 — led, after an import, by the very
  // items that import had just matched — shown under the Trash heading.
  assert.equal(keepsPreviousPage(key(LIB, "null", "recent_desc", 1), TRASH, 1), false);
  assert.equal(keepsPreviousPage(key(TRASH, "null", "recent_desc", 1), LIB, 1), false);
});

test("a slot re-aimed by scrolling shows placeholders, not another page", () => {
  assert.equal(keepsPreviousPage(key(LIB, "null", "recent_desc", 2), LIB, 3), false);
});

test("no previous query, or a key of another shape, keeps nothing", () => {
  assert.equal(keepsPreviousPage(undefined, LIB, 1), false);
  assert.equal(keepsPreviousPage(["items"], LIB, 1), false);
});

test("the grouped layout follows the same scope rule", () => {
  const g = (filters: string) => ["item-groups", filters, "null", "recent_desc", "day"] as const;
  assert.equal(keepsPreviousRuns(g(LIB), LIB), true);
  assert.equal(keepsPreviousRuns(g(LIB), TRASH), false);
  assert.equal(keepsPreviousRuns(undefined, LIB), false);
});

test("the preview holds the picture ON SCREEN, and only that one", () => {
  const item = (id: number) => ["item", id] as const;
  // A step inside an open preview: page 7 is on screen, page 8 is loading,
  // and 7 stays up rather than blinking through the "No preview" box.
  assert.equal(keepsPreviousPreview(item(7), 7), true);
  // A fresh open: nothing is on screen, so the last item this query held —
  // a picture from the previous visit — may not stand in for the new one.
  assert.equal(keepsPreviousPreview(item(7), null), false);
  // And data fetched under some other id never stands in, open or not.
  assert.equal(keepsPreviousPreview(item(7), 9), false);
  assert.equal(keepsPreviousPreview(undefined, 7), false);
  assert.equal(keepsPreviousPreview(["item"], 7), false);
});
