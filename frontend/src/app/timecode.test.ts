// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  TC_SEGMENTS, formatSpan, spanLines, formatTimecode, getSegment, parseTimecode,
  segmentAt, segmentMax, setSegment, shortTime,
} from "./timecode.ts";

test("formatTimecode is full SMPTE HH:MM:SS:FF", () => {
  assert.equal(formatTimecode(0, 25), "00:00:00:00");
  assert.equal(formatTimecode(2 * 60 + 43 + 7 / 25, 25), "00:02:43:07");
  assert.equal(formatTimecode(59.5, 30), "00:00:59:15");
  assert.equal(formatTimecode(3600 + 2 * 60 + 3 + 4 / 24, 24), "01:02:03:04");
});

test("formatTimecode never renders a frame equal to fps (rolls over)", () => {
  // 0.99 s at 25fps rounds to frame 25 → roll to the next second, frame 0.
  assert.equal(formatTimecode(0.999, 25), "00:00:01:00");
});

test("parseTimecode mirrors formatTimecode", () => {
  const fps = 25;
  for (const s of [0, 3.24, 2 * 60 + 43 + 7 / 25, 3600 + 5]) {
    const round = parseTimecode(formatTimecode(s, fps), fps);
    assert.ok(round != null && Math.abs(round - s) < 1 / fps, `round-trip ${s} → ${round}`);
  }
});

test("parseTimecode accepts bare seconds, M:SS and full SMPTE", () => {
  assert.equal(parseTimecode("12", 25), 12);
  assert.equal(parseTimecode("1:30", 25), 90);
  assert.equal(parseTimecode("2:43:07", 25), 2 * 60 + 43 + 7 / 25);
  assert.equal(parseTimecode("01:02:03:04", 24), 3600 + 2 * 60 + 3 + 4 / 24);
});

test("parseTimecode rejects junk and out-of-range frames", () => {
  assert.equal(parseTimecode("", 25), null);
  assert.equal(parseTimecode("ab:cd", 25), null);
  assert.equal(parseTimecode("1:99:99", 25), null); // frame 99 >= 25 fps
});


// --- per-field editing (the annotator's segmented timecode input) -----------

test("segmentAt maps a caret offset to its field, separators included", () => {
  assert.equal(segmentAt(0), 0);
  assert.equal(segmentAt(2), 0);   // just after the hours, before the ":"
  assert.equal(segmentAt(3), 1);
  assert.equal(segmentAt(7), 2);
  assert.equal(segmentAt(11), 3);
  assert.equal(segmentAt(99), 3);  // past the end clamps to the last field
});

test("segmentMax is 99 hours, 59 minutes/seconds and fps-1 frames", () => {
  assert.equal(segmentMax(0, 25), 99);
  assert.equal(segmentMax(1, 25), 59);
  assert.equal(segmentMax(2, 25), 59);
  assert.equal(segmentMax(3, 25), 24);
  assert.equal(segmentMax(3, 23.976), 23);
  assert.equal(segmentMax(3, 0), 24);  // no frame rate → the 25 fps default
});

test("setSegment writes one field, clamped, and leaves the rest alone", () => {
  assert.equal(setSegment("00:00:00:00", 1, 7, 25), "00:07:00:00");
  assert.equal(setSegment("01:02:03:04", 2, 99, 25), "01:02:59:04");
  assert.equal(setSegment("01:02:03:04", 3, 40, 25), "01:02:03:24");
  assert.equal(setSegment("01:02:03:04", 0, 5, 25), "05:02:03:04");
});

test("getSegment reads back what setSegment wrote", () => {
  let tc = "00:00:00:00";
  for (let seg = 0; seg < TC_SEGMENTS.length; seg++) tc = setSegment(tc, seg, 12, 25);
  assert.equal(tc, "12:12:12:12");
  assert.deepEqual([0, 1, 2, 3].map((s) => getSegment(tc, s)), [12, 12, 12, 12]);
  assert.equal(parseTimecode(tc, 25), 12 * 3600 + 12 * 60 + 12 + 12 / 25);
});

test("formatSpan writes a pair, and a lone code for one frame", () => {
  assert.equal(formatSpan({ start: 1, end: 2 }, 25),
    "00:00:01:00 – 00:00:02:00");
  assert.equal(formatSpan({ start: 1, end: null }, 25), "00:00:01:00");
});

test("formatTimecode drops a zero hour only when asked", () => {
  assert.equal(formatTimecode(83.2, 25, true), "01:23:05");
  assert.equal(formatTimecode(83.2, 25), "00:01:23:05");
  // Past the hour it is back to the full four fields, or the two forms would
  // be indistinguishable.
  assert.equal(formatTimecode(3600 + 83.2, 25, true), "01:01:23:05");
});

test("spanLines is one stretch per line, and counts the rest", () => {
  const spans = [
    { start: 0, end: 1 }, { start: 2, end: 3 },
    { start: 4, end: 5 }, { start: 6, end: 7 },
  ];
  assert.deepEqual(spanLines(spans, 25, 2, (n) => `+${n} more`),
    ["00:00:00 – 00:01:00", "00:02:00 – 00:03:00", "+2 more"]);
  // Exactly at the cap says nothing about a remainder there isn't one of.
  assert.deepEqual(spanLines(spans.slice(0, 2), 25, 2),
    ["00:00:00 – 00:01:00", "00:02:00 – 00:03:00"]);
  assert.deepEqual(spanLines([], 25), []);
});

test("formatSpan writes a lone code for a single frame, trimmed too", () => {
  assert.equal(formatSpan({ start: 1, end: null }, 25, true), "00:01:00");
});

test("shortTime drops the hour until there is one", () => {
  assert.equal(shortTime(0), "0:00");
  assert.equal(shortTime(7), "0:07");
  assert.equal(shortTime(83), "1:23");
  assert.equal(shortTime(599), "9:59");
  assert.equal(shortTime(600), "10:00");
  assert.equal(shortTime(3600), "1:00:00");
  assert.equal(shortTime(3723), "1:02:03");
});

test("shortTime floors, and never goes negative", () => {
  // Whole seconds only: a tab title that flickered through tenths would be
  // noise, and the width has to stay put.
  assert.equal(shortTime(83.9), "1:23");
  assert.equal(shortTime(-5), "0:00");
  assert.equal(shortTime(NaN), "0:00");
});
