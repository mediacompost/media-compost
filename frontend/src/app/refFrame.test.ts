/**
 * Between the ITEM's reference frame and a FILE's.
 *
 * The module's own argument for existing is that "two copies of an affine
 * transform are two chances to draw a box a few pixels off from the pixels it
 * names" — and it had no test, so the one thing nobody could check was that
 * the two directions are actually inverses. A box drawn in the annotator is
 * mapped OUT to save it and back IN to draw it again; if those disagree by a
 * hair, a face crawls a pixel every time somebody opens the window, and
 * nothing anywhere says so.
 *
 * `FileVersion` is a type-only import, so this loads under `node --test` with
 * nothing but the arithmetic.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { fileToRef, quadToFile, refToFile } from "./refFrame.ts";
import type { FileVersion } from "./api.ts";

/** A file that IS a crop of the item's original: the right half, lower two
 *  thirds. Only the four crop fields are read. */
const crop = { crop_x: 0.5, crop_y: 1 / 3, crop_w: 0.5, crop_h: 2 / 3 } as
  unknown as FileVersion;

/** The ordinary case: the file is the original, so the mapping is identity. */
const whole = { crop_x: 0, crop_y: 0, crop_w: 1, crop_h: 1 } as
  unknown as FileVersion;

const near = (a: number, b: number, what: string) =>
  assert.ok(Math.abs(a - b) < 1e-12, `${what}: ${a} != ${b}`);

const box = (x: number, y: number, w: number, h: number) => ({ x, y, w, h });

test("an uncropped file is the identity, and so is no file at all", () => {
  const b = box(0.2, 0.3, 0.4, 0.1);
  assert.deepEqual(refToFile(b, whole), b);
  assert.deepEqual(fileToRef(b, whole), b);
  // `null` is what every caller passes before the item's detail has loaded,
  // so it must mean "the whole picture" rather than throw or collapse to 0.
  assert.deepEqual(refToFile(b, null), b);
  assert.deepEqual(fileToRef(b, null), b);
});

test("the two directions are exact inverses", () => {
  // THE point of the module. Round-tripped both ways round, because the
  // annotator maps in to draw and out to save on every single edit.
  for (const b of [box(0.5, 1 / 3, 0.5, 2 / 3), box(0.6, 0.5, 0.2, 0.25),
                   box(0.5, 1 / 3, 0.01, 0.01), box(0.99, 0.99, 0.01, 0.01)]) {
    const back = fileToRef(refToFile(b, crop), crop);
    for (const k of ["x", "y", "w", "h"] as const) {
      near(back[k], b[k], `ref->file->ref ${k}`);
    }
  }
  for (const b of [box(0, 0, 1, 1), box(0.25, 0.5, 0.5, 0.25)]) {
    const back = refToFile(fileToRef(b, crop), crop);
    for (const k of ["x", "y", "w", "h"] as const) {
      near(back[k], b[k], `file->ref->file ${k}`);
    }
  }
});

test("the crop's own corners map to the file's own corners", () => {
  // The anchor that says the transform is the right way round: a box covering
  // exactly the cropped region fills the file, and a box filling the file is
  // exactly the cropped region.
  const full = refToFile(box(0.5, 1 / 3, 0.5, 2 / 3), crop);
  near(full.x, 0, "x"); near(full.y, 0, "y");
  near(full.w, 1, "w"); near(full.h, 1, "h");

  const region = fileToRef(box(0, 0, 1, 1), crop);
  near(region.x, 0.5, "x"); near(region.y, 1 / 3, "y");
  near(region.w, 0.5, "w"); near(region.h, 2 / 3, "h");
});

test("a box outside the crop comes out negative rather than clamped", () => {
  // A face on the half of the picture this file cut away is off-screen, and
  // the caller has to be able to see that it is — clamping would draw it
  // pinned to the edge, which reads as a detector that put it there.
  const off = refToFile(box(0.1, 0.1, 0.2, 0.2), crop);
  assert.ok(off.x < 0, `x=${off.x}`);
  assert.ok(off.y < 0, `y=${off.y}`);
  // …and it still round-trips, so "off-screen" is not a lossy state.
  near(fileToRef(off, crop).x, 0.1, "x");
});

test("a size scales by the crop and a position also shifts", () => {
  // The distinction the two branches exist for: w/h take no offset. Halving
  // the width doubles a box's relative width; it does not move its size by
  // the crop's origin.
  const b = refToFile(box(0.75, 2 / 3, 0.25, 1 / 3), crop);
  near(b.x, 0.5, "x");     // (0.75 − 0.5) / 0.5
  near(b.y, 0.5, "y");     // (2/3 − 1/3) / (2/3)
  near(b.w, 0.5, "w");     // 0.25 / 0.5 — no offset
  near(b.h, 0.5, "h");     // (1/3) / (2/3)
});

test("a missing field reads as zero, and a zero crop size never divides by 0", () => {
  // A box row can carry nulls (a tag with no geometry), and a file's crop
  // fields are nullable in the API. Neither may produce NaN: a NaN reaches
  // the DOM as a style nothing renders, i.e. a box that silently vanishes.
  const nulls = { x: null, y: null, w: null, h: null };
  const got = refToFile(nulls, crop);
  for (const k of ["x", "y", "w", "h"] as const) {
    assert.ok(Number.isFinite(got[k]), `${k} is not finite`);
  }
  const degenerate = { crop_x: 0, crop_y: 0, crop_w: 0, crop_h: 0 } as
    unknown as FileVersion;
  const safe = refToFile(box(0.2, 0.2, 0.2, 0.2), degenerate);
  for (const k of ["x", "y", "w", "h"] as const) {
    assert.ok(Number.isFinite(safe[k]), `${k} divided by a zero crop`);
  }
});

test("a quad takes the same mapping as the box around it", () => {
  // Slanted text draws its quad, and a click has to agree with what is drawn
  // — so the quad cannot be mapped by a second, nearly-identical rule.
  const quad: [number, number][] = [
    [0.5, 1 / 3], [1, 1 / 3], [1, 1], [0.5, 1],
  ];
  const got = quadToFile(quad, crop);
  assert.deepEqual(got.map(([x, y]) => [Math.round(x), Math.round(y)]),
                   [[0, 0], [1, 0], [1, 1], [0, 1]]);
  // Each corner agrees with what refToFile does to a zero-size box there.
  for (const [x, y] of quad) {
    const asBox = refToFile(box(x, y, 0, 0), crop);
    const [qx, qy] = quadToFile([[x, y]], crop)[0];
    near(qx, asBox.x, "quad x");
    near(qy, asBox.y, "quad y");
  }
});

test("a quad keeps its point count and order", () => {
  const quad: [number, number][] = [[0.6, 0.4], [0.9, 0.42], [0.9, 0.5],
                                    [0.6, 0.48]];
  const got = quadToFile(quad, crop);
  assert.equal(got.length, 4);
  // Monotone in x the same way the input is — a map that reordered or
  // mirrored would still "look like a quad" and be the wrong one.
  assert.ok(got[1][0] > got[0][0] && got[2][0] > got[3][0]);
});
