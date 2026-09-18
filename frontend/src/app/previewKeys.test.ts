import test from "node:test";
import assert from "node:assert/strict";

import { previewArrow, type ArrowLike } from "./previewKeys.ts";

const key = (k: string, mods: Partial<ArrowLike> = {}): ArrowLike => ({
  key: k, shiftKey: false, metaKey: false, ctrlKey: false, altKey: false,
  ...mods,
});

test("up mirrors left and down mirrors right", () => {
  assert.deepEqual(previewArrow(key("ArrowRight")), { dir: 1, whole: false });
  assert.deepEqual(previewArrow(key("ArrowDown")), { dir: 1, whole: false });
  assert.deepEqual(previewArrow(key("ArrowLeft")), { dir: -1, whole: false });
  assert.deepEqual(previewArrow(key("ArrowUp")), { dir: -1, whole: false });
  assert.equal(previewArrow(key("Tab")), null);
  assert.equal(previewArrow(key("a")), null);
});

test("shift asks for the whole item, not the next page", () => {
  assert.deepEqual(previewArrow(key("ArrowRight", { shiftKey: true })),
                   { dir: 1, whole: true });
  assert.deepEqual(previewArrow(key("ArrowUp", { shiftKey: true })),
                   { dir: -1, whole: true });
});

test("a session that claims shift keeps it", () => {
  // The tag grid's ⇧ + ←/→ turn the cursor card's answer and run UNDER the
  // preview, so the press is the card's and the preview steps as it always
  // did rather than answering twice.
  assert.deepEqual(
    previewArrow(key("ArrowRight", { shiftKey: true }),
                 { sessionOwnsShift: true }),
    { dir: 1, whole: false });
  // The plain arrows are unaffected either way.
  assert.deepEqual(previewArrow(key("ArrowRight"), { sessionOwnsShift: true }),
                   { dir: 1, whole: false });
});

test("the preview claims a BARE shift", () => {
  // ⇧⌥ is the tag grid's `cycleAll`; ⌘/Ctrl belong to the browser.
  for (const mod of ["altKey", "metaKey", "ctrlKey"] as const) {
    assert.deepEqual(
      previewArrow(key("ArrowRight", { shiftKey: true, [mod]: true })),
      { dir: 1, whole: false }, mod);
  }
});
