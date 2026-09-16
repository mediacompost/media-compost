import { strict as assert } from "node:assert";
import { test } from "node:test";

import { QUICK_TAG_HISTORY_MAX, pushHistoryLine } from "./quickTagHistory.ts";

test("the newest line leads and the list is capped", () => {
  let h: string[] = [];
  for (const line of ["a", "b", "c", "d", "e", "f"]) h = pushHistoryLine(h, line);
  assert.deepEqual(h, ["f", "e", "d", "c", "b"]);
  assert.equal(h.length, QUICK_TAG_HISTORY_MAX);
});

test("applying the same line again MOVES it rather than repeating it", () => {
  const h = pushHistoryLine(["b", "cat -dog", "c"], "cat -dog");
  assert.deepEqual(h, ["cat -dog", "b", "c"]);
});

test("a blank line is no entry, and the line is kept as typed", () => {
  assert.deepEqual(pushHistoryLine(["a"], "   "), ["a"]);
  assert.deepEqual(pushHistoryLine([], "  cat  -dog !bird "), ["cat  -dog !bird"]);
});
