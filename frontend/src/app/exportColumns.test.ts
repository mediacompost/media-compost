import { test } from "node:test";
import assert from "node:assert/strict";

import { moveBlock } from "./exportColumns.ts";

const L = ["a", "b", "c", "d", "e"];

test("a single column moves in both directions", () => {
  // Downward: it lands AFTER the row it was dropped on, so the last slot is
  // reachable at all.
  assert.deepEqual(moveBlock(L, ["a"], "c"), ["b", "c", "a", "d", "e"]);
  assert.deepEqual(moveBlock(L, ["a"], "e"), ["b", "c", "d", "e", "a"]);
  // Upward: BEFORE it, so the first slot is reachable too.
  assert.deepEqual(moveBlock(L, ["e"], "c"), ["a", "b", "e", "c", "d"]);
  assert.deepEqual(moveBlock(L, ["e"], "a"), ["e", "a", "b", "c", "d"]);
});

test("a group moves as one block and comes out contiguous", () => {
  // Its columns need not start contiguous — the display groups them, the
  // file's order need not have — and after the move they are.
  const cur = ["a", "g1", "b", "g2", "c"];
  assert.deepEqual(moveBlock(cur, ["g1", "g2"], "c"),
                   ["a", "b", "c", "g1", "g2"]);
  assert.deepEqual(moveBlock(cur, ["g1", "g2"], "a"),
                   ["g1", "g2", "a", "b", "c"]);
});

test("the block keeps its own order however it is dragged", () => {
  assert.deepEqual(moveBlock(L, ["b", "c"], "e"), ["a", "d", "e", "b", "c"]);
  assert.deepEqual(moveBlock(L, ["c", "b"], "e"), ["a", "d", "e", "c", "b"]);
});

test("a move that cannot mean anything is the list itself", () => {
  // Same array back, not a copy: the caller sets state with it, and a fresh
  // array would re-render on every dragover event.
  assert.equal(moveBlock(L, ["b"], "b"), L, "dropped on itself");
  assert.equal(moveBlock(L, ["a", "b"], "b"), L, "dropped inside the block");
  assert.equal(moveBlock(L, [], "b"), L, "nothing held");
  assert.equal(moveBlock(L, ["a"], "zz" as string), L, "target is not a column");
});
