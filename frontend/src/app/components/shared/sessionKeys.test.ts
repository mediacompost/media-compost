import { test } from "node:test";
import assert from "node:assert/strict";
import { noMods, sessionKeyAction, type KeyLike, type SessionKeySpec } from "./sessionKeys.ts";

const ev = (key: string, o: Partial<KeyLike> = {}): KeyLike => ({
  key, code: key === " " ? "Space" : key,
  shiftKey: false, metaKey: false, ctrlKey: false, altKey: false, ...o,
});
const undoArrows = (e: KeyLike) => e.key === "u" || e.key === "U" || e.key === "ArrowUp";

// The rate and tag-batch shape: ↑ is undo, the arrows judge.
const RATE: SessionKeySpec = {
  hasTab: true, undo: undoArrows, hasPreview: true, hasSkip: true,
  keys: [
    { match: (e) => e.shiftKey && (e.key === "ArrowLeft" || e.key === "ArrowRight") },
    { match: (e) => e.key === "ArrowLeft" },
    { match: (e) => e.key === "ArrowRight" },
    { match: (e) => e.key === "ArrowDown" },
    { match: (e) => (e.key === "i" || e.key === "I") && noMods(e), underSummary: true },
  ],
};
// The tag grid's shape: ↑ is the cursor, U undoes, arrows walk the preview.
const GRID: SessionKeySpec = {
  hasTab: true, undo: (e) => (e.key === "u" || e.key === "U") && noMods(e),
  hasPreview: true, hasSkip: false,
  keys: [
    { match: (e) => e.key === "Enter" && noMods(e), underPreview: true },
    { match: (e) => e.key.startsWith("Arrow") && noMods(e), underPreview: true },
  ],
};
const calm = { preview: false, summary: false };

test("↑ undoes in the rate and tag-batch shape, and moves the cursor in the grid's", () => {
  assert.deepEqual(sessionKeyAction(RATE, ev("ArrowUp"), calm), { kind: "undo" });
  assert.deepEqual(sessionKeyAction(GRID, ev("ArrowUp"), calm), { kind: "key", index: 1 });
  assert.deepEqual(sessionKeyAction(GRID, ev("u"), calm), { kind: "undo" });
});

test("Space is the preview and S is the skip", () => {
  assert.deepEqual(sessionKeyAction(RATE, ev(" "), calm), { kind: "preview" });
  assert.deepEqual(sessionKeyAction(RATE, ev("s"), calm), { kind: "skip" });
  assert.deepEqual(sessionKeyAction(RATE, ev("S"), calm), { kind: "skip" });
  assert.equal(sessionKeyAction(GRID, ev("s"), calm), null, "the grid has no skip");
  assert.equal(sessionKeyAction(RATE, ev("s", { metaKey: true }), calm), null);
});

test("under the preview: Space still toggles it, Tab and ↑ are the preview's, only the card's keys run", () => {
  const under = { preview: true, summary: false };
  assert.deepEqual(sessionKeyAction(RATE, ev(" "), under), { kind: "preview" });
  assert.equal(sessionKeyAction(RATE, ev("Tab"), under), null);
  assert.equal(sessionKeyAction(RATE, ev("ArrowUp"), under), null);
  assert.equal(sessionKeyAction(RATE, ev("ArrowLeft"), under), null, "the arrows judge nothing under the preview");
  assert.equal(sessionKeyAction(RATE, ev("s"), under), null);
  assert.deepEqual(sessionKeyAction(GRID, ev("ArrowLeft"), under), { kind: "key", index: 1 });
  assert.deepEqual(sessionKeyAction(GRID, ev("Enter"), under), { kind: "key", index: 0 });
});

test("under the summary: Tab and undo, and only a key that says it runs there", () => {
  const under = { preview: false, summary: true };
  assert.deepEqual(sessionKeyAction(RATE, ev("Tab"), under), { kind: "tab" });
  assert.deepEqual(sessionKeyAction(RATE, ev("u"), under), { kind: "undo" });
  assert.equal(sessionKeyAction(RATE, ev("ArrowLeft"), under), null);
  assert.equal(sessionKeyAction(RATE, ev(" "), under), null);
  assert.deepEqual(sessionKeyAction(RATE, ev("i"), under), { kind: "key", index: 4 });
});

test("Tab with a modifier is somebody else's", () => {
  assert.equal(sessionKeyAction(RATE, ev("Tab", { shiftKey: true }), calm), null);
  assert.equal(sessionKeyAction(RATE, ev("Tab", { metaKey: true }), calm), null);
});
