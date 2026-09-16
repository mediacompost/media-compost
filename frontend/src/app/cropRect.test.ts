import { test } from "node:test";
import assert from "node:assert/strict";
import { rotateCrop } from "./cropRect.ts";
import type { CropRect } from "./cropRect.ts";

const near = (a: CropRect | null, b: CropRect | null) => {
  assert.ok(a && b, "both rectangles exist");
  for (const k of ["x", "y", "w", "h"] as const) {
    assert.ok(Math.abs(a![k] - b![k]) < 1e-9, `${k}: ${a![k]} vs ${b![k]}`);
  }
};

test("a quarter turn swaps the rectangle's own axes", () => {
  // The top-left corner of a landscape picture, a quarter of it wide and half
  // of it tall. Turned clockwise it is the TOP-RIGHT corner, half wide and a
  // quarter tall.
  near(rotateCrop({ x: 0, y: 0, w: 0.25, h: 0.5 }, 90),
       { x: 0.5, y: 0, w: 0.5, h: 0.25 });
});

test("turning the other way is the other corner", () => {
  near(rotateCrop({ x: 0, y: 0, w: 0.25, h: 0.5 }, -90),
       { x: 0, y: 0.75, w: 0.5, h: 0.25 });
});

test("half a turn keeps the shape and mirrors the position", () => {
  near(rotateCrop({ x: 0.1, y: 0.2, w: 0.3, h: 0.4 }, 180),
       { x: 0.6, y: 0.4, w: 0.3, h: 0.4 });
});

test("four quarter turns come back to where they started", () => {
  const c = { x: 0.13, y: 0.27, w: 0.31, h: 0.42 };
  let out: CropRect | null = c;
  for (let i = 0; i < 4; i++) out = rotateCrop(out, 90);
  near(out, c);
});

test("the whole picture stays the whole picture", () => {
  for (const deg of [90, -90, 180, 270]) {
    near(rotateCrop({ x: 0, y: 0, w: 1, h: 1 }, deg),
         { x: 0, y: 0, w: 1, h: 1 });
  }
});

test("no crop and no turn are both left alone", () => {
  assert.equal(rotateCrop(null, 90), null);
  const c = { x: 0.2, y: 0.3, w: 0.4, h: 0.1 };
  near(rotateCrop(c, 0), c);
  near(rotateCrop(c, 360), c);
});
