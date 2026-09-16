// Run with: npm test  (Node's built-in test runner + type stripping).
//
// The slider and the number field beside it speak different units, so the
// mapping has to be exact in both directions: a size typed in, or set by a
// previous session, has to put the handle somewhere that reads back as that
// same size. A track too coarse to tell 199 from 200 loses a value quietly —
// the handle simply refuses to stop there.
import { test } from "node:test";
import assert from "node:assert/strict";
import { LOG_STEPS, logSliderPos, logSliderValue } from "./logSlider.ts";

const MIN = 1, MAX = 200;

test("every whole size survives the round trip", () => {
  for (let v = MIN; v <= MAX; v++) {
    assert.equal(logSliderValue(logSliderPos(v, MIN, MAX), MIN, MAX), v, `size ${v}`);
  }
});

test("the ends are the ends", () => {
  assert.equal(logSliderPos(MIN, MIN, MAX), 0);
  assert.equal(logSliderPos(MAX, MIN, MAX), LOG_STEPS);
  assert.equal(logSliderValue(0, MIN, MAX), MIN);
  assert.equal(logSliderValue(LOG_STEPS, MIN, MAX), MAX);
});

test("each doubling takes the same length of track", () => {
  const span = (a: number, b: number) => logSliderPos(b, MIN, MAX) - logSliderPos(a, MIN, MAX);
  const low = span(1, 2), high = span(100, 200);
  assert.ok(Math.abs(low - high) <= 1, `1→2 took ${low}, 100→200 took ${high}`);
});

test("the small end gets the room it could not have linearly", () => {
  // Under 20 px is a quarter of a logarithmic track and a tenth of a linear one.
  const share = logSliderPos(20, MIN, MAX) / LOG_STEPS;
  assert.ok(share > 0.5, `20 px sits at ${(share * 100).toFixed(0)}% of the track`);
});

test("out-of-range asks are clamped, not wrapped", () => {
  assert.equal(logSliderPos(0, MIN, MAX), 0);
  assert.equal(logSliderPos(9999, MIN, MAX), LOG_STEPS);
  assert.equal(logSliderValue(-50, MIN, MAX), MIN);
  assert.equal(logSliderValue(LOG_STEPS * 3, MIN, MAX), MAX);
});
