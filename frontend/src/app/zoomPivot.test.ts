// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import { panForZoom, zoomPivot } from "./zoomPivot.ts";

const VP = { w: 800, h: 600 };
/** A picture that fits, sitting still. */
const fitted = { vp: VP, frame: { w: 400, h: 300 }, pan: { x: 0, y: 0 } };
/** One larger than the viewport on both axes. */
const big = { vp: VP, frame: { w: 1600, h: 1200 }, pan: { x: 0, y: 0 } };

test("a picture that fits turns about its own centre", () => {
  // The whole of it is on screen, so a cursor pivot only walks it off a corner.
  assert.deepEqual(zoomPivot(fitted, { x: 250, y: 200 }), { x: 400, y: 300 });
});

test("a picture that fits OFF centre still turns about its own centre", () => {
  // Its own centre, which is not the viewport's: turning about the cursor
  // here would recentre a picture somebody had put where they wanted it.
  // Content spans x 320…720, y 150…450, so its centre is (520, 300).
  const s = { vp: VP, frame: { w: 400, h: 300 }, pan: { x: 120, y: 0 } };
  assert.deepEqual(zoomPivot(s, { x: 350, y: 200 }), { x: 520, y: 300 });
});

test("a picture bigger than the viewport turns about the cursor", () => {
  assert.deepEqual(zoomPivot(big, { x: 250, y: 200 }), { x: 250, y: 200 });
});

test("the axes are decided separately", () => {
  // Wide and short: the width overflows and follows the cursor, the height
  // fits and holds still. Content spans x -50…850, y 150…450.
  const s = { vp: VP, frame: { w: 900, h: 300 }, pan: { x: 0, y: 0 } };
  assert.deepEqual(zoomPivot(s, { x: 120, y: 200 }), { x: 120, y: 300 });
});

test("a cursor off the picture falls back to the picture's centre", () => {
  // Overflowing but panned left, so there is empty viewport to point at:
  // content spans x -150…750, and its centre is 300.
  const s = { vp: VP, frame: { w: 900, h: 300 }, pan: { x: -100, y: 0 } };
  assert.deepEqual(zoomPivot(s, { x: 770, y: 300 }), { x: 300, y: 300 });
  // A wheel event with no cursor at all does the same.
  assert.deepEqual(zoomPivot(s, null), { x: 300, y: 300 });
});

test("half a pixel of layout rounding does not flip the rule", () => {
  const s = { vp: VP, frame: { w: 800.4, h: 599.7 }, pan: { x: 0.4, y: -0.3 } };
  assert.deepEqual(zoomPivot(s, { x: 10, y: 10 }),
    { x: 400.4, y: 299.7 }, "still counts as fitting");
});

test("a picture that fits grows where it stands", () => {
  // The headline case: zoom an off-centre picture up and it must not move.
  const s = { vp: VP, frame: { w: 400, h: 300 }, pan: { x: 120, y: -40 } };
  const pivot = zoomPivot(s, { x: 350, y: 200 });
  assert.deepEqual(panForZoom(s, pivot, 1.2), { x: 120, y: -40 });
  // And back down again lands exactly where it started.
  const up = { ...s, frame: { w: 480, h: 360 }, pan: { x: 120, y: -40 } };
  assert.deepEqual(panForZoom(up, zoomPivot(up, null), 1 / 1.2),
    { x: 120, y: -40 });
});

test("an edge stops it, and then pushes it", () => {
  // 400 wide at x-pan 120 has 80 px of slack on the right; grown to 600 it
  // has 100, so the picture is shifted the 20 px that keeps its right edge
  // on the viewport's rather than beyond it.
  const s = { vp: VP, frame: { w: 400, h: 300 }, pan: { x: 120, y: 0 } };
  assert.deepEqual(panForZoom(s, zoomPivot(s, null), 1.5), { x: 100, y: 0 });
});

test("a picture that filled the viewport comes back centred", () => {
  // Zoomed in past the edges and dragged about, then zoomed back out to
  // exactly the viewport's size: there is nowhere off centre left to be.
  const s = { vp: VP, frame: { w: 1000, h: 750 }, pan: { x: 40, y: -30 } };
  assert.deepEqual(panForZoom(s, { x: 100, y: 100 }, 0.8), { x: 0, y: 0 });
});

test("the pan keeps the pivot over the same part of the picture", () => {
  // Zoom 2x about a point a quarter of the way into a picture that already
  // overflows: that quarter-point must still be under the cursor.
  const pivot = { x: 200, y: 150 };
  const next = panForZoom(big, pivot, 2);
  const o2 = { x: (VP.w - 3200) / 2 + next.x, y: (VP.h - 2400) / 2 + next.y };
  const before = { x: (VP.w - 1600) / 2, y: (VP.h - 1200) / 2 };
  const fx = (pivot.x - before.x) / 1600;
  const fy = (pivot.y - before.y) / 1200;
  assert.ok(Math.abs(o2.x + fx * 3200 - pivot.x) < 1e-6);
  assert.ok(Math.abs(o2.y + fy * 2400 - pivot.y) < 1e-6);
});

test("an overflowing picture zooms about the cursor, corner or not", () => {
  // Magnified, with the pointer near the viewport's corner: the old clamp
  // kept the viewport covered and so pinned the picture's edge to the
  // viewport's, sliding the detail out from under the pointer. The pivot
  // stays put now, even where that opens a gap on the far side.
  const s = { vp: VP, frame: { w: 1600, h: 1200 }, pan: { x: 400, y: 300 } };
  const pivot = { x: 790, y: 590 };
  assert.deepEqual(zoomPivot(s, pivot), pivot, "the cursor is the pivot");
  const next = panForZoom(s, pivot, 0.6);
  const o = { x: (VP.w - 1600) / 2 + s.pan.x, y: (VP.h - 1200) / 2 + s.pan.y };
  const o2 = { x: (VP.w - 960) / 2 + next.x, y: (VP.h - 720) / 2 + next.y };
  const fx = (pivot.x - o.x) / 1600, fy = (pivot.y - o.y) / 1200;
  assert.ok(Math.abs(o2.x + fx * 960 - pivot.x) < 1e-6);
  assert.ok(Math.abs(o2.y + fy * 720 - pivot.y) < 1e-6);
  // ...and the clamp has NOT been applied: the pan is past the covered limit.
  assert.ok(Math.abs(next.x) > (960 - VP.w) / 2);
  // While an axis that comes to FIT is still clamped on to the screen.
  const small = panForZoom(s, pivot, 0.3);
  assert.ok(Math.abs(small.x) <= (VP.w - 480) / 2 + 1e-9);
  assert.ok(Math.abs(small.y) <= (VP.h - 360) / 2 + 1e-9);
});
