// Run with: npm test  (Node's built-in test runner + type stripping).
//
// The flood is written twice — once over the picture's bytes for a click, once
// over `seedDistances` for the frames of a drag — because the second is 2.7x
// the first per frame and the first is 12x cheaper to START. Nothing in the app
// can tell you they have drifted: both answer plausible regions, and a drag
// would simply select something a hair different from the click that began it.
// So they are asserted equal here, against a third, deliberately stupid
// implementation that nobody would optimise.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  floodFromDistances, floodFromPixels, regionToMask, seedDistances, toleranceSteps,
} from "./floodRegion.ts";

/** The obvious thing: one pixel at a time, four neighbours, no cleverness. */
function reference(
  data: Uint8ClampedArray, w: number, h: number,
  x0: number, y0: number, tolerance: number,
): Uint8Array {
  const tol = toleranceSteps(tolerance);
  const j0 = (y0 * w + x0) * 4;
  const r0 = data[j0], g0 = data[j0 + 1], b0 = data[j0 + 2], a0 = data[j0 + 3];
  const ok = (i: number) => {
    const j = i * 4;
    return Math.abs(data[j] - r0) <= tol && Math.abs(data[j + 1] - g0) <= tol
      && Math.abs(data[j + 2] - b0) <= tol && Math.abs(data[j + 3] - a0) <= tol;
  };
  const region = new Uint8Array(w * h);
  const stack = [y0 * w + x0];
  region[y0 * w + x0] = 1;
  while (stack.length) {
    const i = stack.pop()!;
    const x = i % w;
    if (x > 0 && !region[i - 1] && ok(i - 1)) { region[i - 1] = 1; stack.push(i - 1); }
    if (x < w - 1 && !region[i + 1] && ok(i + 1)) { region[i + 1] = 1; stack.push(i + 1); }
    if (i >= w && !region[i - w] && ok(i - w)) { region[i - w] = 1; stack.push(i - w); }
    if (i < w * (h - 1) && !region[i + w] && ok(i + w)) { region[i + w] = 1; stack.push(i + w); }
  }
  return region;
}

/** A repeatable picture: blocks of a few colours, so regions have real shapes. */
function picture(w: number, h: number, seed: number): Uint8ClampedArray {
  let s = seed >>> 0;
  const rand = () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296;
  const data = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      // Coarse blocks with a little noise: flat areas the flood can run
      // through, and edges it has to stop at.
      const block = Math.floor(x / 5) * 7 + Math.floor(y / 4) * 13;
      const base = (block * 37) % 256;
      const j = (y * w + x) * 4;
      data[j] = base;
      data[j + 1] = (base + 40) % 256;
      data[j + 2] = (base + 90) % 256;
      data[j + 3] = rand() < 0.1 ? 200 : 255;
    }
  }
  return data;
}

const same = (a: Uint8Array, b: Uint8Array) => a.length === b.length && a.every((v, i) => v === b[i]);

test("both floods answer what the obvious implementation answers", () => {
  const w = 37, h = 29;
  for (let seed = 1; seed <= 6; seed++) {
    const data = picture(w, h, seed);
    for (const [x0, y0] of [[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1], [18, 14], [7, 22]]) {
      for (const tol of [0, 1, 5, 20, 50, 100]) {
        const want = reference(data, w, h, x0, y0, tol);
        const dist = seedDistances(data, w, h, x0, y0);
        assert.ok(same(floodFromPixels(data, w, h, x0, y0, tol), want),
          `pixels differ at seed ${seed}, (${x0},${y0}), tol ${tol}`);
        assert.ok(same(floodFromDistances(dist, w, h, x0, y0, tol), want),
          `distances differ at seed ${seed}, (${x0},${y0}), tol ${tol}`);
      }
    }
  }
});

test("at tolerance 100 the whole picture is one region", () => {
  const w = 12, h = 9;
  const region = floodFromPixels(picture(w, h, 3), w, h, 5, 5, 100);
  assert.equal(region.reduce((a, b) => a + b, 0), w * h);
});

test("at tolerance 0 only the seed's own colour is taken", () => {
  const w = 8, h = 8;
  const data = new Uint8ClampedArray(w * h * 4).fill(255);
  // One square of a different colour, seeded inside it.
  for (let y = 2; y < 5; y++) for (let x = 3; x < 6; x++) {
    const j = (y * w + x) * 4;
    data[j] = 10; data[j + 1] = 20; data[j + 2] = 30;
  }
  const region = floodFromPixels(data, w, h, 4, 3, 0);
  assert.equal(region.reduce((a, b) => a + b, 0), 9);
  assert.equal(region[3 * w + 4], 1);
  assert.equal(region[0], 0);
});

test("a region is 4-connected, so a diagonal neighbour is not reached", () => {
  const w = 3, h = 3;
  const data = new Uint8ClampedArray(w * h * 4).fill(255);
  // Black at the two opposite corners only: they touch at a corner alone.
  for (const [x, y] of [[0, 0], [1, 1]]) {
    const j = (y * w + x) * 4;
    data[j] = data[j + 1] = data[j + 2] = 0;
  }
  const region = floodFromPixels(data, w, h, 0, 0, 0);
  assert.equal(region[0], 1);
  assert.equal(region[1 * w + 1], 0);
});

test("the distance map is the colour test, spelled once", () => {
  const w = 16, h = 11;
  const data = picture(w, h, 9);
  const dist = seedDistances(data, w, h, 4, 4);
  const j0 = (4 * w + 4) * 4;
  for (let i = 0; i < w * h; i++) {
    const j = i * 4;
    const want = Math.max(
      Math.abs(data[j] - data[j0]), Math.abs(data[j + 1] - data[j0 + 1]),
      Math.abs(data[j + 2] - data[j0 + 2]), Math.abs(data[j + 3] - data[j0 + 3]));
    assert.equal(dist[i], want, `pixel ${i}`);
  }
});

test("the raster is opaque white exactly where the region is", () => {
  const region = new Uint8Array([0, 1, 1, 0, 1]);
  const out = new Uint8ClampedArray(region.length * 4).fill(7);
  regionToMask(region, out);
  for (let i = 0; i < region.length; i++) {
    const want = region[i] ? 255 : 0;
    for (let c = 0; c < 4; c++) assert.equal(out[i * 4 + c], want, `pixel ${i} channel ${c}`);
  }
});
