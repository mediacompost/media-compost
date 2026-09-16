// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import { tagColor } from "./tagColor.ts";

test("tagColor is deterministic", () => {
  assert.deepEqual(tagColor("person"), tagColor("person"));
  assert.deepEqual(tagColor("dog"), tagColor("dog"));
  assert.notDeepEqual(tagColor("person"), tagColor("dog"));
});

test("tagColor returns well-formed hsl strings", () => {
  const c = tagColor("cat");
  assert.match(c.stroke, /^hsl\(\d+(\.\d+)?, 75%, 58%\)$/);
  assert.match(c.fill, /^hsla\(\d+(\.\d+)?, 75%, 58%, 0\.16\)$/);
  assert.match(c.text, /^hsl\(\d+(\.\d+)?, 80%, 12%\)$/);
});

test("tagColor spreads hues across many names", () => {
  // A pile of realistic tag names should not all collapse into one narrow band.
  const names = [
    "person", "dog", "cat", "car", "tree", "hat", "wearing_hat", "background",
    "sky", "water", "building", "road", "grass", "flower", "bird", "hand",
    "face", "eye", "shirt", "shoe",
  ];
  const hues = names.map((n) => {
    const m = /^hsl\(([\d.]+),/.exec(tagColor(n).stroke)!;
    return Number(m[1]);
  });
  // Buckets of 30° each: expect the names to touch at least half the wheel.
  const buckets = new Set(hues.map((h) => Math.floor(h / 30)));
  assert.ok(buckets.size >= 6, `expected wide hue spread, got ${buckets.size} buckets`);
});
