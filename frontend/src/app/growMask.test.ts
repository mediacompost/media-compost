/**
 * THE SCHEDULE HAS TO LAND ON `n` AND STAY CONNECTED.
 *
 * The second half is the one that was wrong, and it is invisible from
 * outside: the old schedule grew by exactly the right amount too, in the
 * sense that its steps summed to `n` — it just left the shape in pieces.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { growSteps } from "./growMask.ts";

/** The radius the shape has when each round starts. */
const radii = (steps: number[]) => {
  let r = 0;
  return steps.map((s) => { const at = r; r += s; return at; });
};

test("the steps add up to the amount asked for", () => {
  for (let n = 0; n <= 600; n++) {
    assert.equal(growSteps(n).reduce((a, b) => a + b, 0), n, `n=${n}`);
  }
});

test("no round outruns what has been grown already", () => {
  // A shift of s over a shape of radius r leaves it connected only while
  // s <= 2r + 1. THIS is what the binary-bits schedule broke.
  for (let n = 0; n <= 600; n++) {
    const steps = growSteps(n);
    radii(steps).forEach((r, i) => {
      assert.ok(steps[i] <= 2 * r + 1,
        `n=${n}: step ${steps[i]} at radius ${r} would break the shape apart`);
    });
  }
});

test("the amounts that used to come back as a lattice", () => {
  // Every power of two was one round at its own offset — a single-pixel find
  // grown by 8 came back as nine pixels eight apart.
  assert.deepEqual(growSteps(2), [1, 1]);
  assert.deepEqual(growSteps(4), [1, 3]);
  assert.deepEqual(growSteps(8), [1, 3, 4]);
  assert.deepEqual(growSteps(16), [1, 3, 9, 3]);
  // 40 = 32 + 8 was two rounds, and made 81 dots of a one-pixel find.
  assert.deepEqual(growSteps(40), [1, 3, 9, 27]);
  // The small ones the old schedule happened to get right are unchanged.
  assert.deepEqual(growSteps(1), [1]);
  assert.deepEqual(growSteps(3), [1, 2]);
});

test("nothing asked for is nothing done", () => {
  assert.deepEqual(growSteps(0), []);
});

test("it stays logarithmic — that is the point of composing at all", () => {
  assert.ok(growSteps(500).length <= 8, growSteps(500).join("+"));
  assert.ok(growSteps(5000).length <= 12, growSteps(5000).join("+"));
});
