import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CROP_ASPECTS, CUSTOM_ID, aspectDragRect, aspectRatio, clampRect,
  customRatio, fitExtents, fitRectToAspect, resizeLocal,
} from "./cropAspect.ts";
import type { Bounds, Rect, Sign } from "./cropAspect.ts";

const DIMS = { w: 400, h: 200 };                 // a landscape picture, 2:1
const px = (r: Rect, dims = DIMS) => ({ w: r.w * dims.w, h: r.h * dims.h });
const near = (a: number, b: number, msg = "") =>
  assert.ok(Math.abs(a - b) < 1e-9, `${msg} ${a} vs ${b}`);
const shape = (r: Rect, aspect: number, dims = DIMS) => {
  const p = px(r, dims);
  near(p.w / p.h, aspect, "ratio");
};

test("a ratio is about PIXELS, not about the stored fractions", () => {
  // Half the width and half the height of a 2:1 picture is not a square.
  const sq = fitRectToAspect({ x: 0.25, y: 0.25, w: 0.5, h: 0.5 }, 1, DIMS);
  shape(sq, 1);
  near(sq.w, 0.25);
  near(sq.h, 0.5);
});

test("Original resolves against the picture; an unknown id is free", () => {
  near(aspectRatio("original", DIMS)!, 2);
  assert.equal(aspectRatio("free", DIMS), null);
  assert.equal(aspectRatio("nonsense", DIMS), null);
  near(aspectRatio("16:9", DIMS)!, 16 / 9);
});

test("every offered ratio has a positive value or is free", () => {
  for (const a of CROP_ASPECTS) {
    assert.ok(a.ratio === null || a.ratio > 0, a.id);
    if (a.ratio !== null) near(aspectRatio(a.id, DIMS)!, a.ratio, a.id);
  }
});

test("a typed ratio is what the fields say, and null while they say nothing", () => {
  near(customRatio({ w: "16", h: "10" })!, 1.6);
  near(customRatio({ w: "2.5", h: "1" })!, 2.5);
  // Half-typed, empty, zero or nonsense is FREE rather than a shape nothing
  // can satisfy — a field being typed into must not fight the hand.
  for (const c of [{ w: "16", h: "" }, { w: "", h: "" }, { w: "16", h: "0" },
                   { w: "-2", h: "1" }, { w: "x", h: "1" }, { w: ".", h: "." }]) {
    assert.equal(customRatio(c), null, JSON.stringify(c));
  }
  assert.equal(customRatio(undefined), null);
});

test("Custom resolves through aspectRatio, and only with the fields", () => {
  near(aspectRatio(CUSTOM_ID, DIMS, { w: "3", h: "1" })!, 3);
  // Asked without them it is free, which is what an id nothing can resolve
  // has always meant here.
  assert.equal(aspectRatio(CUSTOM_ID, DIMS), null);
  // ... and the fields never leak into another option.
  near(aspectRatio("1:1", DIMS, { w: "3", h: "1" })!, 1);
  near(aspectRatio("original", DIMS, { w: "3", h: "1" })!, 2);
});

test("the extents EXPAND to the ratio rather than retreating from the cursor", () => {
  // Wider than 1:1 wants a taller box; taller than 1:1 wants a wider one.
  assert.deepEqual(fitExtents(100, 40, 1), { lx: 100, ly: 100 });
  assert.deepEqual(fitExtents(40, 100, 1), { lx: 100, ly: 100 });
  // Already on the ratio: untouched.
  assert.deepEqual(fitExtents(80, 40, 2), { lx: 80, ly: 40 });
});

test("a locked drag keeps its anchor and its shape", () => {
  const r = aspectDragRect({ x: 100, y: 50 }, { x: 180, y: 60 }, DIMS, 1);
  shape(r, 1);
  // Dragged right and down, so the anchor is the top-left corner.
  near(r.x * DIMS.w, 100);
  near(r.y * DIMS.h, 50);
  // The wider extent (80 px) won.
  near(px(r).w, 80);
  near(px(r).h, 80);
});

test("dragging up and left anchors the OTHER corner", () => {
  const r = aspectDragRect({ x: 300, y: 150 }, { x: 220, y: 140 }, DIMS, 1);
  shape(r, 1);
  near((r.x + r.w) * DIMS.w, 300);
  near((r.y + r.h) * DIMS.h, 150);
});

test("a drag past the edge SHRINKS to the ratio instead of being clipped", () => {
  // 300 px of room to the right, only 40 below: the square is 40 on a side.
  const r = aspectDragRect({ x: 100, y: 160 }, { x: 399, y: 199 }, DIMS, 1);
  shape(r, 1);
  near(px(r).h, 40);
  assert.ok(r.x >= 0 && r.y >= 0 && r.x + r.w <= 1 + 1e-9 && r.y + r.h <= 1 + 1e-9);
});

test("with no ratio, a handle drag is exactly what the free crop always did", () => {
  const hw = 40, hh = 30;
  const cases: [Sign, Sign][] = [[1, 1], [-1, -1], [1, -1], [0, 1], [1, 0], [0, -1], [-1, 0]];
  for (const [sx, sy] of cases) {
    const loc = { x: 65, y: -12 };
    const got = resizeLocal(sx, sy, hw, hh, loc, null);
    const fixedX = -sx * hw, fixedY = -sy * hh;
    near(got.w, sx === 0 ? hw * 2 : Math.abs(loc.x - fixedX), `w ${sx},${sy}`);
    near(got.h, sy === 0 ? hh * 2 : Math.abs(loc.y - fixedY), `h ${sx},${sy}`);
    near(got.midX, sx === 0 ? 0 : (fixedX + loc.x) / 2, `midX ${sx},${sy}`);
    near(got.midY, sy === 0 ? 0 : (fixedY + loc.y) / 2, `midY ${sx},${sy}`);
  }
});

test("a locked CORNER keeps the opposite corner fixed", () => {
  // se handle on a 80x60 rect: the nw corner sits at (-40, -30) and stays.
  const got = resizeLocal(1, 1, 40, 30, { x: 100, y: 10 }, 1);
  near(got.w, 140);          // 140 wide beats 40 tall, so the square is 140
  near(got.h, 140);
  near(got.midX - got.w / 2, -40);
  near(got.midY - got.h / 2, -30);
});

test("a locked EDGE grows the other axis about the rect's own centre", () => {
  // An east handle names one edge; the two the ratio forces are the ones the
  // hand is not on, so they move symmetrically and the centre line holds.
  const got = resizeLocal(1, 0, 40, 30, { x: 60, y: 999 }, 1);
  near(got.w, 100);          // from the fixed west edge at -40 to +60
  near(got.h, 100);
  near(got.midY, 0);
  near(got.midX, 10);
});

test("a corner dragged past its fixed side turns the rect inside out", () => {
  const got = resizeLocal(1, 1, 40, 30, { x: -140, y: -50 }, null);
  near(got.w, 100);          // fixed side at -40, cursor at -140
  near(got.midX, -90);       // ... so the rect is to the LEFT of it
});

test("clamping without a ratio clips; with one it shrinks and slides", () => {
  const over: Rect = { x: 0.8, y: 0.1, w: 0.4, h: 0.2 };
  const clipped = clampRect(over, null);
  near(clipped.w, 0.2);
  const held = clampRect(over, 2);
  near(held.w, 0.4);         // the shape survived
  near(held.h, 0.2);
  near(held.x, 0.6);         // it slid back inside instead
  const huge = clampRect({ x: -0.5, y: -0.5, w: 2, h: 4 }, 1);
  assert.ok(huge.w <= 1 + 1e-9 && huge.h <= 1 + 1e-9);
  assert.ok(huge.x >= 0 && huge.y >= 0);
});

test("picking up a ratio fits INSIDE the rect that is already there", () => {
  const r = fitRectToAspect({ x: 0.5, y: 0.5, w: 0.5, h: 0.5 }, 16 / 9, DIMS);
  shape(r, 16 / 9);
  assert.ok(r.w <= 0.5 + 1e-9 && r.h <= 0.5 + 1e-9);
  // The centre is where it was.
  near(r.x + r.w / 2, 0.75);
  near(r.y + r.h / 2, 0.75);
  // ... and it never leaves the picture.
  assert.ok(r.x >= 0 && r.y >= 0 && r.x + r.w <= 1 + 1e-9 && r.y + r.h <= 1 + 1e-9);
});

test("no ratio leaves a rect exactly as it is", () => {
  const r: Rect = { x: 0.1, y: 0.2, w: 0.3, h: 0.4 };
  assert.deepEqual(fitRectToAspect(r, null, DIMS), r);
});

test("a locked resize STOPS at the picture's edge, keeping its fixed side", () => {
  // A 80x60 rect centred at (200, 100) in a 400x200 picture: the se handle is
  // dragged far out, so the square wants 300 a side and there are only 130
  // below the fixed north edge.
  const bounds: Bounds = { minX: -200, maxX: 200, minY: -100, maxY: 100 };
  const got = resizeLocal(1, 1, 40, 30, { x: 260, y: 300 }, 1, bounds);
  near(got.w, 130);
  near(got.h, 130);
  // The fixed north-west corner has not moved.
  near(got.midX - got.w / 2, -40);
  near(got.midY - got.h / 2, -30);
});

test("a locked EDGE is bounded by the room either side of its centre line", () => {
  // Rect centred 20 px above the middle of a 200-tall picture: the derived
  // axis grows both ways, so the tighter side (80) decides.
  const bounds: Bounds = { minX: -200, maxX: 200, minY: -80, maxY: 120 };
  const got = resizeLocal(1, 0, 40, 30, { x: 400, y: 0 }, 1, bounds);
  near(got.h, 160);          // 2 x 80
  near(got.w, 160);
  near(got.midY, 0);
});

test("bounds never touch a FREE resize", () => {
  const bounds: Bounds = { minX: -1, maxX: 1, minY: -1, maxY: 1 };
  const free = resizeLocal(1, 1, 40, 30, { x: 260, y: 300 }, null, bounds);
  const same = resizeLocal(1, 1, 40, 30, { x: 260, y: 300 }, null);
  assert.deepEqual(free, same);
});

test("a resize that already fits is left alone by the bounds", () => {
  const bounds: Bounds = { minX: -200, maxX: 200, minY: -100, maxY: 100 };
  const got = resizeLocal(1, 1, 40, 30, { x: 20, y: 20 }, 1, bounds);
  near(got.w, 60);           // fixed side at -40, cursor at 20
  near(got.h, 60);
});
