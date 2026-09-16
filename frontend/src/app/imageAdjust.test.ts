import test from "node:test";
import assert from "node:assert/strict";

import { NO_ADJUST, adjustPixels, cssFilter, isIdentity } from "./imageAdjust.ts";

const px = (...rgb: number[]) => {
  const a = new Uint8ClampedArray(4);
  a[0] = rgb[0]; a[1] = rgb[1]; a[2] = rgb[2]; a[3] = 255;
  return a;
};
const near = (got: Uint8ClampedArray, want: number[], tol = 2) => {
  for (let i = 0; i < 3; i++) {
    assert.ok(Math.abs(got[i] - want[i]) <= tol,
      `channel ${i}: got ${got[i]}, want ~${want[i]}`);
  }
};

test("nothing set changes nothing", () => {
  const p = px(10, 120, 250);
  adjustPixels(p, NO_ADJUST);
  near(p, [10, 120, 250], 0);
  assert.equal(cssFilter(NO_ADJUST), "none");
  assert.ok(isIdentity(NO_ADJUST));
});

test("brightness scales every channel", () => {
  const p = px(100, 100, 100);
  adjustPixels(p, { ...NO_ADJUST, brightness: 50 });   // ×1.5
  near(p, [150, 150, 150]);
});

test("contrast pushes away from mid-grey, and leaves mid-grey alone", () => {
  const mid = px(128, 128, 128);
  adjustPixels(mid, { ...NO_ADJUST, contrast: 50 });
  near(mid, [128, 128, 128], 2);
  const dark = px(64, 64, 64);
  adjustPixels(dark, { ...NO_ADJUST, contrast: 100 });  // ×2 about 0.5
  near(dark, [0, 0, 0], 2);
});

test("saturation −100 is greyscale, at the luminance the matrix defines", () => {
  const p = px(255, 0, 0);
  adjustPixels(p, { ...NO_ADJUST, saturation: -100 });
  const lum = Math.round(0.213 * 255);
  near(p, [lum, lum, lum], 2);
  assert.equal(p[0], p[1]);
  assert.equal(p[1], p[2]);
});

test("a full turn of hue comes home", () => {
  const p = px(200, 60, 30);
  adjustPixels(p, { ...NO_ADJUST, hue: 360 });
  near(p, [200, 60, 30], 3);
});

test("hue rotation moves a colour without touching alpha", () => {
  const p = px(255, 0, 0);
  p[3] = 128;
  adjustPixels(p, { ...NO_ADJUST, hue: 120 });
  assert.equal(p[3], 128);
  assert.ok(p[1] > p[0], "red should have turned towards green");
});

test("the CSS filter names the same four, in the same order", () => {
  assert.equal(
    cssFilter({ brightness: 10, contrast: -20, saturation: 50, hue: 30 }),
    "brightness(1.1) contrast(0.8) saturate(1.5) hue-rotate(30deg)",
  );
  // Only what was actually set — an identity term would cost a filter pass.
  assert.equal(cssFilter({ ...NO_ADJUST, hue: 90 }), "hue-rotate(90deg)");
});
