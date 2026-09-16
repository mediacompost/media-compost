import { test } from "node:test";
import assert from "node:assert/strict";
import { pickNext } from "./pickList.ts";

const ORDER = ["a", "b", "c", "d", "e"];
const plain = { meta: false, shift: false };
const meta = { meta: true, shift: false };
const shift = { meta: false, shift: true };
const both = { meta: true, shift: true };

test("a plain click picks this one alone, and again on the only pick puts it down", () => {
  assert.deepEqual(pickNext(["a", "b"], "c", plain, ORDER, "a"), { next: ["c"], anchor: "c" });
  assert.deepEqual(pickNext(["c"], "c", plain, ORDER, "c"), { next: [], anchor: null });
  assert.deepEqual(pickNext(["a", "c"], "c", plain, ORDER, "a"), { next: ["c"], anchor: "c" },
                   "with several picked it narrows rather than empties");
});

test("⌘ toggles one and keeps the rest", () => {
  assert.deepEqual(pickNext(["a"], "c", meta, ORDER, "a"), { next: ["a", "c"], anchor: "c" });
  assert.deepEqual(pickNext(["a", "c"], "c", meta, ORDER, "a"), { next: ["a"], anchor: "c" });
});

test("shift REPLACES with the run from the anchor; ⌘⇧ adds it; the anchor stays", () => {
  assert.deepEqual(pickNext(["e"], "c", shift, ORDER, "a"), { next: ["a", "b", "c"], anchor: "a" });
  assert.deepEqual(pickNext(["e"], "c", both, ORDER, "a"), { next: ["e", "a", "b", "c"], anchor: "a" });
  assert.deepEqual(pickNext(["e"], "a", shift, ORDER, "c"), { next: ["a", "b", "c"], anchor: "c" }, "either direction");
});

test("shift with no anchor, or an anchor the order has lost, is a plain click", () => {
  assert.deepEqual(pickNext(["b"], "c", shift, ORDER, null), { next: ["c"], anchor: "c" });
  assert.deepEqual(pickNext(["b"], "c", shift, ORDER, "zz"), { next: ["c"], anchor: "c" });
  assert.deepEqual(pickNext(["c"], "c", shift, ORDER, "c"), { next: [], anchor: null }, "the anchor itself");
});

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

test("no list unions a shift-range or keeps a lastPick of its own", () => {
  // The five flat pickers each spelled the click rule themselves, and
  // every one of them ADDED a shift-range where a click replaces.
  const SRC = fileURLToPath(new URL(".", import.meta.url)).replace(/shared\/$/, "");
  for (const rel of ["train/TrainView.tsx", "train/EvaluateView.tsx",
                     "app/components/CutTrack.tsx", "app/components/AnnotationOverlay.tsx",
                     "app/components/ImportOverlay.tsx", "app/components/GroupTree.tsx",
                     "app/components/shared/useRowSelect.ts"]) {
    const src = readFileSync(join(SRC, rel), "utf8");
    assert.ok(!/new Set\(\[\.\.\.cur, \.\.\.(?:run|range)\]\)/.test(src), `${rel} unions a range`);
    assert.ok(!/lastPick = useRef/.test(src), `${rel} keeps a lastPick of its own`);
    assert.ok(/pickNext\(/.test(src), `${rel} does not use pickNext`);
  }
});
