import { test } from "node:test";
import assert from "node:assert/strict";
import { CACHE_MAX_PX, visibleBlit } from "./canvasBlit.ts";

test("a picture wholly on screen blits whole", () => {
  assert.deepEqual(visibleBlit(100, 50, 0.5, 400, 300, 800, 600),
    { sx: 0, sy: 0, sw: 400, sh: 300, dx: 100, dy: 50, dw: 200, dh: 150 });
});

test("zoomed in, only the visible patch is drawn, on whole source pixels", () => {
  // 16x over a 4000x3000 page, panned so the viewport starts 10.5 source
  // pixels in: the patch starts at pixel 10 (rounded outward) and lands
  // exactly where that pixel sits on screen.
  const b = visibleBlit(-168, -80, 16, 4000, 3000, 800, 600)!;
  assert.equal(b.sx, 10); assert.equal(b.sy, 5);
  assert.equal(b.dx, -168 + 10 * 16); assert.equal(b.dy, -80 + 5 * 16);
  // ceil((800 + 168) / 16) = 61 → 51 pixels wide, 61 rows... and never past the picture.
  assert.equal(b.sw, 51); assert.equal(b.sh, Math.ceil((600 + 80) / 16) - 5);
  assert.equal(b.dw, b.sw * 16); assert.equal(b.dh, b.sh * 16);
  assert.ok(b.sx + b.sw <= 4000 && b.sy + b.sh <= 3000);
});

test("the patch is clipped to the picture at its far edges", () => {
  const b = visibleBlit(700, 500, 4, 100, 100, 800, 600)!;
  assert.deepEqual([b.sx, b.sy, b.sw, b.sh], [0, 0, 25, 25]);
});

test("a picture entirely off screen blits nothing", () => {
  assert.equal(visibleBlit(900, 0, 1, 100, 100, 800, 600), null);
  assert.equal(visibleBlit(-200, 0, 1, 100, 100, 800, 600), null);
});

test("the cache cap is under every browser's canvas limit", () => {
  // 32767 per side is the smallest cap in use; the cache is square-ish at
  // worst, so a picture under the cap fits either way round.
  assert.ok(Math.sqrt(CACHE_MAX_PX) <= 32767);
  assert.ok(CACHE_MAX_PX >= 3840 * 2160);
});
