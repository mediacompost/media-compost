import test from "node:test";
import assert from "node:assert/strict";

import { unsharpPixels } from "./imageSharpen.ts";

/** A row of grey pixels, opaque. */
const row = (...greys: number[]) => {
  const a = new Uint8ClampedArray(greys.length * 4);
  greys.forEach((g, i) => { a[i * 4] = g; a[i * 4 + 1] = g; a[i * 4 + 2] = g; a[i * 4 + 3] = 255; });
  return a;
};
const greys = (a: Uint8ClampedArray) =>
  [...Array(a.length / 4).keys()].map((i) => a[i * 4]);

test("nothing is added where the picture is flat", () => {
  // The blur of a flat field is the field, so the difference is nothing.
  const p = row(120, 120, 120);
  unsharpPixels(p, row(120, 120, 120), 200);
  assert.deepEqual(greys(p), [120, 120, 120]);
});

test("0% changes nothing at all", () => {
  const p = row(10, 200, 30);
  unsharpPixels(p, row(100, 100, 100), 0);
  assert.deepEqual(greys(p), [10, 200, 30]);
});

test("an edge is pushed further apart on both sides", () => {
  // A step 80 | 160, whose blur has smeared each side towards the other.
  const p = row(80, 80, 160, 160);
  unsharpPixels(p, row(80, 100, 140, 160), 100);
  const [a, b, c, d] = greys(p);
  assert.equal(a, 80);          // away from the edge: untouched
  assert.equal(d, 160);
  assert.ok(b < 80, `the dark side of the edge darkens: ${b}`);
  assert.ok(c > 160, `the light side brightens: ${c}`);
});

test("the amount is how far, and it clamps rather than wrapping", () => {
  const half = row(100, 100);
  unsharpPixels(half, row(100, 60), 50);
  assert.deepEqual(greys(half), [100, 120]);   // 100 + 0.5 × 40
  const over = row(250);
  unsharpPixels(over, row(0), 300);
  assert.deepEqual(greys(over), [255]);        // not 1000, and not wrapped
});

test("alpha is left alone", () => {
  const p = new Uint8ClampedArray([10, 10, 10, 128]);
  unsharpPixels(p, new Uint8ClampedArray([200, 200, 200, 0]), 100);
  assert.equal(p[3], 128);
});
