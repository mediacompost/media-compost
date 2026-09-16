// Run with: npm test.
import { test } from "node:test";
import assert from "node:assert/strict";

import { compactMetrics, COMPACT_AT, HEAD_KEEP, TAIL_KEEP } from "./metricsWindow.ts";
import type { TrainMetricPoint } from "./api.ts";

const pt = (step: number, extra: Partial<TrainMetricPoint> = {}): TrainMetricPoint =>
  ({ step, loss: 0.5, lr: 1e-4, t: 1000 + step, ...extra });

const series = (n: number, from = 1) =>
  Array.from({ length: n }, (_, i) => pt(from + i));

test("below the threshold nothing is touched, array and all", () => {
  const pts = series(COMPACT_AT);
  // IDENTITY, not a copy: the chart's memos hang on it, and a fresh array per
  // poll would rebuild every one of them for nothing.
  assert.equal(compactMetrics(pts), pts);
});

test("past it the array comes back bounded, and stays bounded", () => {
  let pts = series(COMPACT_AT + 1);
  pts = compactMetrics(pts);
  assert.equal(pts.length, HEAD_KEEP + TAIL_KEEP);
  // A day of polling: a thousand new points at a time, for ever.
  for (let i = 0; i < 200; i++) {
    const last = pts[pts.length - 1].step;
    pts = compactMetrics([...pts, ...series(1000, last + 1)]);
    assert.ok(pts.length <= COMPACT_AT,
              `grew to ${pts.length} on round ${i}`);
  }
  // …and the run is still 200,000 steps long on the x axis.
  assert.equal(pts[pts.length - 1].step, COMPACT_AT + 1 + 200 * 1000);
});

test("the newest points are kept whole — the pace is read off them", () => {
  const pts = compactMetrics(series(COMPACT_AT + 500));
  const tail = pts.slice(-TAIL_KEEP);
  for (let i = 1; i < tail.length; i++) {
    assert.equal(tail[i].step - tail[i - 1].step, 1,
                 "a gap in the tail would flatten the ETA's step rate");
  }
  assert.equal(tail[tail.length - 1].step, COMPACT_AT + 500);
});

test("it stays sorted, and keeps both ends of the run", () => {
  const pts = compactMetrics(series(50000));
  assert.equal(pts[0].step, 1);
  assert.equal(pts[pts.length - 1].step, 50000);
  for (let i = 1; i < pts.length; i++) {
    assert.ok(pts[i].step > pts[i - 1].step, `out of order at ${i}`);
  }
});

test("a validation round survives the stride", () => {
  // One point in hundreds, which is exactly what a plain stride drops — and
  // it is the series the thinning exists to protect (the server's own rule).
  const pts = series(20000).map((p, i) =>
    (i % 500 === 0 ? { ...p, val: 0.42, stable: 0.4 } : p));
  const out = compactMetrics(pts);
  const scored = pts.filter((p) => p.val != null);
  const kept = out.filter((p) => p.val != null);
  assert.equal(kept.length, scored.length);
});
