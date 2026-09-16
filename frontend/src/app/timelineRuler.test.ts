import test from "node:test";
import assert from "node:assert/strict";

import { rulerLabel, rulerStep, rulerTicks } from "./timelineRuler.ts";

test("a step is always a number people count in", () => {
  const allowed = new Set([0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300,
                           600, 900, 1800, 3600, 7200]);
  for (let px = 0.05; px < 8000; px *= 1.17) {
    assert.ok(allowed.has(rulerStep(px)), `${px} px/s gave ${rulerStep(px)}`);
  }
});

test("below a tenth of a second, every step is a whole number of FRAMES", () => {
  for (const fps of [24, 25, 29.97, 30, 60]) {
    for (let px = 1; px < 8000; px *= 1.13) {
      const s = rulerStep(px, 64, fps);
      if (s >= 0.1) continue;
      const frames = s * fps;
      assert.ok(Math.abs(frames - Math.round(frames)) < 1e-9,
                `${fps} fps at ${px} px/s gave ${s}s = ${frames} frames`);
      assert.ok(frames >= 1, `finer than a frame: ${frames}`);
    }
  }
});

test("a frame rate never coarsens the ruler — the tenths are still there", () => {
  // 700 px/s: 0.1 s is 70 px and fits, whether or not we know the rate.
  assert.equal(rulerStep(700, 64), 0.1);
  assert.equal(rulerStep(700, 64, 30), 0.1);
});

test("zoomed far in, the finest step is ONE frame and no finer", () => {
  // 4000 px/s is the timeline's own limit: 133 px a frame at 30 fps.
  assert.ok(Math.abs(rulerStep(4000, 64, 30) - 1 / 30) < 1e-9);
  // …and it stops there however far anybody zooms.
  assert.ok(Math.abs(rulerStep(100000, 64, 30) - 1 / 30) < 1e-9);
});

test("labels never crowd — every step leaves room for its own text", () => {
  for (let px = 1; px < 4000; px *= 1.13) {
    const s = rulerStep(px, 64);
    // Either it clears the minimum, or it is the coarsest the ladder has.
    assert.ok(s * px >= 64 || s === 7200, `${px} px/s → ${s}s`);
  }
});

test("the step is the SMALLEST that fits, so the ruler is as detailed as it can be", () => {
  // 100 px/s: 0.5 s is 50 px (too close), 1 s is 100 px (fits).
  assert.equal(rulerStep(100, 64), 1);
  // 10 px/s: 5 s is 50 px, 10 s is 100 px.
  assert.equal(rulerStep(10, 64), 10);
});

test("a zoom past the ladder falls back rather than inventing a step", () => {
  assert.equal(rulerStep(0.0001), 7200);
  assert.equal(rulerStep(0), 7200);
  assert.equal(rulerStep(-5), 7200);
});

test("marks sit on multiples of the step, not on the window's left edge", () => {
  // Scrolled to 3.2 s: the first mark is 4, not 3.2 — so scrolling slides the
  // ruler PAST the marks rather than dragging them along.
  assert.deepEqual(rulerTicks(3.2, 8, 2), [4, 6, 8]);
  assert.deepEqual(rulerTicks(0, 5, 1), [0, 1, 2, 3, 4, 5]);
});

test("fine steps do not drift", () => {
  const ticks = rulerTicks(0, 3, 0.1);
  assert.equal(ticks.length, 31);
  // Accumulated addition puts 0.1 × 30 at 2.9999999999999996.
  assert.ok(Math.abs(ticks[30] - 3) < 1e-9, String(ticks[30]));
});

test("the count is capped — a long film at a fine step is not 36000 nodes", () => {
  assert.equal(rulerTicks(0, 3600, 0.1, 400).length, 400);
});

test("nothing to draw", () => {
  assert.deepEqual(rulerTicks(5, 5, 1), []);
  assert.deepEqual(rulerTicks(0, 10, 0), []);
});

test("a label says only what the step can distinguish", () => {
  assert.equal(rulerLabel(3, 1), "3s");
  assert.equal(rulerLabel(3.5, 0.5), "3.5s");
  assert.equal(rulerLabel(90, 30), "1:30");
  assert.equal(rulerLabel(3661, 60), "1:01:01");
});

test("at FRAME SCALE a label is a timecode with its frame, and not before", () => {
  // 12 s and 4 frames at 30 fps, on a two-frame step.
  assert.equal(rulerLabel(12 + 4 / 30, 2 / 30, 30), "00:12:04");
  // A tenth-of-a-second step keeps the decimal even with a rate to hand:
  // `00:00:15` for half a second reads as fifteen SECONDS.
  assert.equal(rulerLabel(0.5, 0.5, 30), "0.5s");
  assert.equal(rulerLabel(3.1, 0.1, 30), "3.1s");
  // A whole-second step is unaffected — the frame would always read 00.
  assert.equal(rulerLabel(12, 1, 30), "12s");
  // No frame rate, no frames to count.
  assert.equal(rulerLabel(3.5, 0.5), "3.5s");
});
