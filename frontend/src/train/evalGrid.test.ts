import test from "node:test";
import assert from "node:assert/strict";

import { stepTile } from "./evalGrid.ts";
import type { GridSection, StepDir } from "./evalGrid.ts";

/** Three sessions: 5 tiles, 2 tiles, 4 tiles, over 3 columns. Their starts
 *  (0, 5, 7) are deliberately not multiples of 3 — the whole point. */
const S: GridSection[] = [
  { start: 0, count: 5 }, { start: 5, count: 2 }, { start: 7, count: 4 },
];
const step = (cur: number, dir: StepDir, cols = 3) =>
  stepTile(S, cols, cur, dir);

test("left and right walk the flat reading order across sessions", () => {
  assert.equal(step(4, "right"), 5);
  assert.equal(step(5, "left"), 4);
  // Both ends absorb.
  assert.equal(step(0, "left"), 0);
  assert.equal(step(10, "right"), 10);
});

test("up and down move a row WITHIN the session, not by a flat offset", () => {
  // Session 0 is rows [0 1 2] [3 4].
  assert.equal(step(0, "down"), 3);
  assert.equal(step(3, "up"), 0);
  // Column 2 of the first row has no tile under it — the short row's last
  // one is the answer, not the next session.
  assert.equal(step(2, "down"), 4);
  // A naive cur+columns would land on 5, i.e. the next session.
  assert.notEqual(step(2, "down"), 5);
});

test("a section boundary is a row boundary, and it round-trips", () => {
  // Off the bottom of session 0 into session 1, same column.
  assert.equal(step(3, "down"), 5);
  assert.equal(step(4, "down"), 6);
  assert.equal(step(5, "up"), 3);
  assert.equal(step(6, "up"), 4);
  // Session 1 holds two tiles, so column 2 clamps to its last.
  assert.equal(step(2, "down"), 4);
  assert.equal(step(4, "down"), 6);
  // Down out of the last section stays inside the grid.
  assert.equal(step(9, "down"), 10);
  assert.equal(step(10, "down"), 10);
  // Up out of the first section stays on the first tile.
  assert.equal(step(1, "up"), 0);
});

test("one column makes every step a single tile", () => {
  assert.equal(step(4, "down", 1), 5);
  assert.equal(step(5, "up", 1), 4);
  // A column count of zero is not a division by zero.
  assert.equal(stepTile(S, 0, 4, "down"), 5);
});

test("an empty grid and an out-of-range cursor answer inside the grid", () => {
  assert.equal(stepTile([], 3, 0, "down"), 0);
  assert.equal(step(99, "left"), 9);
  assert.equal(step(-4, "right"), 1);
});
