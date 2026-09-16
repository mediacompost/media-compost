// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addSpan, coverageOfAll, entryContains, nextStop, subtractSpan, tagRanges,
} from "./videoTracks.ts";

test("entryContains handles ranges and single frames", () => {
  assert.equal(entryContains({ start: 1, end: 3 }, 2), true);
  assert.equal(entryContains({ start: 1, end: 3 }, 3.5), false);
  assert.equal(entryContains({ start: 5, end: null }, 5), true);
  assert.equal(entryContains({ start: 5, end: null }, 5.5), false);
});

test("addSpan unions the range into the coverage", () => {
  // Disjoint: appended, sorted.
  assert.deepEqual(addSpan([{ start: 10, end: 12 }], { start: 2, end: 4 }),
    [{ start: 2, end: 4 }, { start: 10, end: 12 }]);
  // Overlapping and merely touching both fuse into one.
  assert.deepEqual(addSpan([{ start: 2, end: 6 }], { start: 4, end: 9 }),
    [{ start: 2, end: 9 }]);
  assert.deepEqual(addSpan([{ start: 2, end: 4 }], { start: 4, end: 9 }),
    [{ start: 2, end: 9 }]);
  // A single frame inside the range is swallowed by it.
  assert.deepEqual(addSpan([{ start: 5, end: null }], { start: 2, end: 9 }),
    [{ start: 2, end: 9 }]);
  // …but one well clear of it keeps its own shape.
  assert.deepEqual(addSpan([{ start: 5, end: null }], { start: 20, end: 30 }),
    [{ start: 5, end: null }, { start: 20, end: 30 }]);
  // A gap under the tolerance (half a frame) is no gap.
  assert.deepEqual(addSpan([{ start: 0, end: 1 }], { start: 1.01, end: 2 }, 0.02),
    [{ start: 0, end: 2 }]);
});

test("an implied tag covers the union of what implies it", () => {
  // poodle 0–10 and terrier 20–30 both imply dog; dog is on screen for both.
  assert.deepEqual(
    coverageOfAll([[{ start: 0, end: 10 }], [{ start: 20, end: 30 }]]),
    [{ start: 0, end: 10 }, { start: 20, end: 30 }]);
  // Overlapping sources fuse rather than stacking.
  assert.deepEqual(
    coverageOfAll([[{ start: 0, end: 10 }], [{ start: 5, end: 20 }]]),
    [{ start: 0, end: 20 }]);
  // NULL IS THE WHOLE FILM, AND IT IS CONTAGIOUS: one untimed source applies
  // throughout, so what it entails does too, whatever the others say.
  assert.equal(coverageOfAll([[], [{ start: 20, end: 30 }]]), null);
  assert.equal(coverageOfAll([[]]), null);
  // Nothing known says nothing — an implication with no recorded source.
  assert.equal(coverageOfAll([]), null);
  // A single frame stays a single frame.
  assert.deepEqual(coverageOfAll([[{ start: 4, end: null }]]),
                   [{ start: 4, end: null }]);
});

test("subtractSpan cuts the range out of the coverage", () => {
  // Straddled: the pieces on either side survive.
  assert.deepEqual(subtractSpan([{ start: 0, end: 10 }], { start: 4, end: 6 }),
    [{ start: 0, end: 4 }, { start: 6, end: 10 }]);
  // Fully covered: gone.
  assert.deepEqual(subtractSpan([{ start: 4, end: 6 }], { start: 0, end: 10 }), []);
  // Clear of the cut: untouched.
  assert.deepEqual(subtractSpan([{ start: 0, end: 2 }], { start: 4, end: 6 }),
    [{ start: 0, end: 2 }]);
  // Overlapping one end: trimmed.
  assert.deepEqual(subtractSpan([{ start: 0, end: 10 }], { start: 8, end: 20 }),
    [{ start: 0, end: 8 }]);
  // A single frame inside the cut disappears; one outside stays.
  assert.deepEqual(subtractSpan([{ start: 5, end: null }], { start: 4, end: 6 }), []);
  assert.deepEqual(subtractSpan([{ start: 5, end: null }], { start: 7, end: 9 }),
    [{ start: 5, end: null }]);
  // A remainder shorter than the tolerance is below the resolution anyone can
  // see or seek to, so it goes rather than leaving a phantom frame behind.
  assert.deepEqual(subtractSpan([{ start: 0, end: 10 }], { start: 0.01, end: 20 }, 0.02), []);
  // A remainder longer than it survives as a range.
  assert.deepEqual(subtractSpan([{ start: 0, end: 10 }], { start: 0.5, end: 20 }, 0.02),
    [{ start: 0, end: 0.5 }]);
});

test("nextStop walks to the next moment on another frame", () => {
  const times = [10, 20, 30];
  assert.equal(nextStop(times, 15, 1, 25), 20);
  assert.equal(nextStop(times, 15, -1, 25), 10);
  assert.equal(nextStop(times, 30, 1, 25), null);
  assert.equal(nextStop(times, 10, -1, 25), null);
});

test("nextStop ignores the frame it is already on, wherever the seek landed", () => {
  // Seeking to 913 at 23.976 fps puts the element on the frame CONTAINING it
  // and reports that frame's own start — a few ms below what was asked for.
  // Every one of those is the same frame, so there is nothing further either
  // way; this is what left a jump button lit after it had already taken you
  // there.
  const fps = 23.976;
  const frameStart = Math.floor(913 * fps) / fps;
  for (const landed of [913, frameStart, frameStart + 0.001, 913 + 0.03]) {
    assert.equal(nextStop([913], landed, 1, fps), null, `forward from ${landed}`);
    assert.equal(nextStop([913], landed, -1, fps), null, `back from ${landed}`);
  }
  // …but a different frame is reachable again.
  assert.equal(nextStop([913], 912, 1, fps), 913);
  assert.equal(nextStop([913], 914, -1, fps), 913);
});

test("nextStop can still step between adjacent frames", () => {
  const fps = 25;
  assert.equal(nextStop([1, 1 + 1 / fps], 1, 1, fps), 1 + 1 / fps);
});

test("tagRanges keeps only the time-only boxes, in order", () => {
  const boxes = [
    { x: null, time_start: 9, time_end: 12 },
    // Geometry: a still's box or a moving subject's placement. It says where,
    // never when the tag applies.
    { x: 0.1, time_start: 1, time_end: 2 },
    { x: null, time_start: 3, time_end: null },
    // No time at all: an ordinary image box.
    { x: 0.4, time_start: null, time_end: null },
  ];
  assert.deepEqual(tagRanges(boxes), [
    { start: 3, end: null },
    { start: 9, end: 12 },
  ]);
});

test("tagRanges reads no boxes as no ranges", () => {
  // Which the caller reads as "the whole film", never as "never" — a tag with
  // no ranges applies throughout.
  assert.deepEqual(tagRanges([]), []);
  assert.deepEqual(tagRanges(null), []);
  assert.deepEqual(tagRanges(undefined), []);
});
