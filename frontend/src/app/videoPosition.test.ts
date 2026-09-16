// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import { VideoPositions } from "./videoPosition.ts";

const A = "http://x/api/files/3";
const B = "http://x/api/files/4";

test("a source is resumed where it was left", () => {
  const p = new VideoPositions();
  p.loaded(A);
  p.record(97.5);
  assert.equal(p.resumeTo(A, 0, 300), 97.5);
});

test("a source nobody has seen is left alone", () => {
  const p = new VideoPositions();
  assert.equal(p.resumeTo(B, 0, 300), null);
});

test("a source left at the beginning is left alone", () => {
  // It is already there, and seeking to zero would be a re-decode for nothing.
  const p = new VideoPositions();
  p.loaded(A);
  p.record(0);
  assert.equal(p.resumeTo(A, 0, 300), null);
});

test("already at the remembered moment is left alone", () => {
  const p = new VideoPositions();
  p.loaded(A);
  p.record(97.5);
  assert.equal(p.resumeTo(A, 97.5, 300), null);
  // …but a real difference still seeks.
  assert.equal(p.resumeTo(A, 12, 300), 97.5);
});

test("a swap between two sources keeps both positions apart", () => {
  // The sequence a `<video>` really produces when React swaps its `src`: the
  // element resets to zero BETWEEN the two sources, and that zero must not be
  // recorded against either of them.
  const p = new VideoPositions();
  p.loaded(A);
  p.record(200);

  p.detached();       // loadstart / emptied for B
  p.record(0);        // the reset's timeupdate — belongs to nothing
  p.loaded(B);        // B's metadata
  assert.equal(p.resumeTo(B, 0, 600), null, "B was never watched");
  p.record(42);

  p.detached();       // back to A
  p.record(0);
  p.loaded(A);
  assert.equal(p.resumeTo(A, 0, 300), 200, "A is where it was left");

  p.detached();
  p.record(0);
  p.loaded(B);
  assert.equal(p.resumeTo(B, 0, 600), 42, "and so is B");
});

test("a fresh element records nothing until its metadata arrives", () => {
  // An unmount/remount (switching to an image tab and back): the new element
  // is at zero because it has loaded nothing, not because that is where
  // playback is.
  const p = new VideoPositions();
  p.loaded(A);
  p.record(311);

  p.detached();       // the element went away, a new one bound
  p.record(0);        // its untouched currentTime
  assert.equal(p.recall(A), 311, "the old position survived the remount");

  p.loaded(A);
  assert.equal(p.resumeTo(A, 0, 400), 311);
});

test("the resume is clamped to a source that got shorter", () => {
  const p = new VideoPositions();
  p.loaded(A);
  p.record(500);
  assert.equal(p.resumeTo(A, 0, 120), 120);
  // An unknown duration cannot clamp, and must not throw the position away.
  assert.equal(p.resumeTo(A, 0, 0), 500);
});
