// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import { compactCount, diskLevel, formatBytes, mpLabel } from "./format.ts";

test("formatBytes uses decimal units (matches macOS Finder), not binary", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(999), "999 B");
  assert.equal(formatBytes(1000), "1 KB");
  assert.equal(formatBytes(1_500_000), "1.5 MB");
  // A 1.5 GiB file (1024-based) reads as ~1.6 GB — what Finder shows — not 1.5.
  assert.equal(formatBytes(1024 ** 3 * 1.5), "1.6 GB");
  assert.equal(formatBytes(2_000_000_000), "2.0 GB");
  assert.equal(formatBytes(3_500_000_000_000), "3.5 TB");
});

test("mpLabel rounds half up on the exact pixel count", () => {
  assert.equal(mpLabel(1000, 1000), "1.0 MP");
  assert.equal(mpLabel(1920, 1080), "2.1 MP");
  // The case that used to disagree between the grid and the metadata list:
  // 0.6499 MP rounded to two decimals first (0.65) then to one became 0.7.
  assert.equal(mpLabel(850, 764), "0.6 MP");
  // Exact halves round up, in both languages, because the tie is decided on
  // the integer pixel count rather than on a float.
  assert.equal(mpLabel(1000, 650), "0.7 MP");
  assert.equal(mpLabel(1000, 649), "0.6 MP");
  assert.equal(mpLabel(0, 0), "0.0 MP");
});

test("diskLevel is driven by gigabytes, with the percentage only adding to it", () => {
  const GB = 1024 ** 3;
  // Plenty of room, by both measures.
  assert.equal(diskLevel(500 * GB, 1000 * GB), "none");
  // …and a big disk with a lot left stays quiet at a lowish percentage:
  // 500 GB of 4 TB is 12%, and 500 GB is still 500 GB.
  assert.equal(diskLevel(500 * GB, 4000 * GB), "none");
  // The absolute floor is what actually stops the next import: under 10 GB is
  // a warning wherever it happens (9 GB of 100 GB is a healthy-looking 9%).
  assert.equal(diskLevel(9 * GB, 100 * GB), "low");
  assert.equal(diskLevel(1 * GB, 4000 * GB), "critical");
  // On a huge disk a single-digit GB is both tiny and a rounding error of the
  // total, so it counts as critical rather than merely low.
  assert.equal(diskLevel(8 * GB, 4000 * GB), "critical");
  // The percentage adds urgency only while the figure is already smallish:
  // 80 GB of 4 TB (2%) is worth a nudge; 40 GB of it is worse.
  assert.equal(diskLevel(80 * GB, 4000 * GB), "low");
  assert.equal(diskLevel(40 * GB, 4000 * GB), "critical");
  // A small volume where a few GB IS the last of it: 3 GB of 64 GB.
  assert.equal(diskLevel(3 * GB, 64 * GB), "low");
  // Unknown or unreadable: say nothing rather than "0 B free".
  assert.equal(diskLevel(0, 0), "none");
  assert.equal(diskLevel(0, 500 * GB), "none");
});

test("a count for a small tile is at most four characters", () => {
  assert.equal(compactCount(0), "0");
  assert.equal(compactCount(842), "842");
  assert.equal(compactCount(1000), "1k");
  assert.equal(compactCount(1234), "1.2k");
  assert.equal(compactCount(48_000), "48k");
  assert.equal(compactCount(999_988), "1M");
  assert.equal(compactCount(1_300_000), "1.3M");
  assert.equal(compactCount(2_400_000_000), "2.4B");
});
