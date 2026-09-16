// Run with: npm test  (Node's built-in test runner + type stripping).
//
// Four shapes from two modifiers, and they compose — which is the reason the
// geometry is a function rather than a nest of branches in the pointer
// handler, and the reason it is pinned here: every combination is a drag
// somebody makes by accident, and three of the four cannot be seen in a test
// that only checks the plain one.
import { test } from "node:test";
import assert from "node:assert/strict";
import { marqueeRect } from "./marqueeRect.ts";

const A = { x: 100, y: 100 };

test("a plain drag runs from the press to the pointer", () => {
  assert.deepEqual(marqueeRect(A, { x: 160, y: 140 }), { x: 100, y: 100, w: 60, h: 40 });
});

test("a plain drag backwards is the same box, normalised", () => {
  assert.deepEqual(marqueeRect(A, { x: 40, y: 60 }), { x: 40, y: 60, w: 60, h: 40 });
});

test("square takes the larger distance and keeps the drag's direction", () => {
  // Right and down: the box grows right and down, 60 on both sides.
  assert.deepEqual(marqueeRect(A, { x: 160, y: 140 }, { square: true }),
    { x: 100, y: 100, w: 60, h: 60 });
  // Left and up: it grows left and up.
  assert.deepEqual(marqueeRect(A, { x: 40, y: 60 }, { square: true }),
    { x: 40, y: 40, w: 60, h: 60 });
  // Left and down: one of each.
  assert.deepEqual(marqueeRect(A, { x: 40, y: 140 }, { square: true }),
    { x: 40, y: 100, w: 60, h: 60 });
});

test("from the centre, the press is the middle and the box is twice the reach", () => {
  assert.deepEqual(marqueeRect(A, { x: 160, y: 140 }, { fromCentre: true }),
    { x: 40, y: 60, w: 120, h: 80 });
  // Dragging the other way reaches the same box: the centre is what is fixed.
  assert.deepEqual(marqueeRect(A, { x: 40, y: 60 }, { fromCentre: true }),
    { x: 40, y: 60, w: 120, h: 80 });
});

test("both together is a square centred on the press", () => {
  const r = marqueeRect(A, { x: 160, y: 140 }, { fromCentre: true, square: true });
  assert.deepEqual(r, { x: 40, y: 40, w: 120, h: 120 });
  assert.equal(r.x + r.w / 2, A.x);
  assert.equal(r.y + r.h / 2, A.y);
});

test("a drag along one axis still squares off, positively", () => {
  assert.deepEqual(marqueeRect(A, { x: 100, y: 160 }, { square: true }),
    { x: 100, y: 100, w: 60, h: 60 });
});

test("a drag that has not moved is an empty box, whatever is held", () => {
  for (const opts of [{}, { square: true }, { fromCentre: true }, { fromCentre: true, square: true }]) {
    const r = marqueeRect(A, A, opts);
    assert.equal(r.w, 0, JSON.stringify(opts));
    assert.equal(r.h, 0, JSON.stringify(opts));
  }
});
