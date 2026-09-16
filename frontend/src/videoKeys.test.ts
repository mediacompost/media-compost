import test from "node:test";
import assert from "node:assert/strict";

import { videoKeyAction } from "./app/components/shared/videoKeys.ts";

const K = (key: string, mods: Record<string, boolean> = {}) =>
  videoKeyAction({ key, ...mods } as Parameters<typeof videoKeyAction>[0]);

test("the transport's keys are the ones every editor has", () => {
  assert.deepEqual(videoKeyAction({ key: " ", code: "Space" }), { kind: "play" });
  assert.deepEqual(K("k"), { kind: "play" });
  assert.deepEqual(K("K"), { kind: "play" });
  assert.deepEqual(K("ArrowLeft"), { kind: "step", frames: -1 });
  assert.deepEqual(K("ArrowRight"), { kind: "step", frames: 1 });
  assert.deepEqual(K(","), { kind: "step", frames: -1 });
  assert.deepEqual(K("."), { kind: "step", frames: 1 });
  assert.deepEqual(K("j"), { kind: "shuttle", dir: -1 });
  assert.deepEqual(K("l"), { kind: "shuttle", dir: 1 });
  assert.deepEqual(K("Home"), { kind: "edge", to: 0 });
  assert.deepEqual(K("End"), { kind: "edge", to: 1 });
});

test("SHIFT is the map's own 'further', and every other modifier is somebody else's", () => {
  assert.deepEqual(K("ArrowRight", { shiftKey: true }), { kind: "seconds", by: 1 });
  assert.deepEqual(K("ArrowLeft", { shiftKey: true }), { kind: "seconds", by: -1 });
  // ⌘Z, ⌘S, ⌘←: the window's own shortcuts and the browser's, untouched.
  for (const mod of ["metaKey", "ctrlKey", "altKey"]) {
    assert.equal(K("ArrowRight", { [mod]: true }), null, mod);
    assert.equal(K("k", { [mod]: true }), null, mod);
    assert.equal(K(" ", { [mod]: true }), null, mod);
  }
});

test("a key that means nothing to a film is not claimed", () => {
  for (const key of ["a", "Enter", "Escape", "Delete", "ArrowUp", "ArrowDown",
                     "Backspace", "1", "t", "q"]) {
    assert.equal(K(key), null, key);
  }
});
