import assert from "node:assert/strict";
import { test } from "node:test";

import type { TextRegion } from "../api";
import {
  childrenAreRows, dismissedRoots, enginesOf, flattenText, groupByEngine,
  inQuad, inRegion, liveRoots, regionCounts, regionText,
} from "./regions.ts";

let nextId = 1;
function region(over: Partial<TextRegion> = {}): TextRegion {
  return {
    id: nextId++, item_id: 1, item_uid: "u", file_id: null, parent_id: null,
    level: "block", ord: 0, x: 0.1, y: 0.1, w: 0.4, h: 0.1, quad: [],
    text: "", score: null, lang: "", models: ["m"], dismissed: false,
    edited: false, children: [],
    ...over,
  };
}

test("flattenText: collapsed blocks are one row each", () => {
  const tree = [
    region({ text: "a", children: [region({ level: "line", text: "l1" })] }),
    region({ text: "b" }),
  ];
  const rows = flattenText(tree, new Set());
  assert.deepEqual(rows.map((r) => r.region.text), ["a", "b"]);
});

test("flattenText: an expanded block's LINES are rows at one indent", () => {
  const block = region({ text: "a", children: [
    region({ level: "line", text: "l1" }),
    region({ level: "line", text: "l2" }),
  ] });
  const rows = flattenText([block], new Set([block.id]));
  assert.deepEqual(rows.map((r) => [r.region.text, r.depth]),
                   [["a", 0], ["l1", 1], ["l2", 1]]);
  assert.equal(rows[1].parentId, block.id);
});

test("flattenText: word children are chips, never rows", () => {
  const line = region({ level: "line", text: "hello world", children: [
    region({ level: "word", text: "hello" }),
    region({ level: "word", text: "world" }),
  ] });
  assert.equal(childrenAreRows(line), false);
  const rows = flattenText([line], new Set([line.id]));
  assert.equal(rows.length, 1, "expanding a chip-level parent adds no rows");
});

test("regionText: a block with no text of its own joins its children", () => {
  const block = region({ children: [
    region({ level: "line", text: "one" }),
    region({ level: "line", text: "two" }),
  ] });
  assert.equal(regionText(block), "one\ntwo");
  const line = region({ level: "line", children: [
    region({ level: "word", text: "hello" }),
    region({ level: "word", text: "world" }),
  ] });
  assert.equal(regionText(line), "hello world");
});

test("regionText: the region's OWN text wins, at every level", () => {
  // A word is a BOX, not an editable unit — its text is the engine's
  // reading, while the correctable string is the line's. So a corrected
  // line reads as corrected even though its words still say what the
  // engine read (the words were briefly the only editable thing here,
  // which put a row of little fields where a sentence belongs).
  const line = region({ level: "line", text: "the corrected reading",
    children: [
      region({ level: "word", text: "the" }),
      region({ level: "word", text: "engines" }),
      region({ level: "word", text: "reading" }),
    ] });
  assert.equal(regionText(line), "the corrected reading");
  const block = region({ text: "its own text", children: [
    region({ level: "line", text: "a line" }),
  ] });
  assert.equal(regionText(block), "its own text");
  // Only an EMPTY region falls back to its children — words joined by a
  // space, lines by a newline.
  const bare = region({ level: "line", text: "", children: [
    region({ level: "word", text: "two" }),
    region({ level: "word", text: "words" }),
  ] });
  assert.equal(regionText(bare), "two words");
});

test("enginesOf lists engines in first-seen order, skipping hand-drawn", () => {
  const roots = [
    region({ models: [] }),
    region({ models: ["magi"] }),
    region({ models: ["rapid"] }),
    region({ models: ["magi"] }),
  ];
  assert.deepEqual(enginesOf(roots), ["magi", "rapid"]);
});

test("regionCounts counts every level below, recursively", () => {
  const block = region({ children: [
    region({ level: "line", children: [
      region({ level: "word", text: "a" }),
      region({ level: "word", text: "b" }),
    ] }),
    region({ level: "line" }),
  ] });
  assert.deepEqual(regionCounts(block), { lines: 2, words: 2, chars: 0 });
});

test("live and dismissed roots split the disclosure", () => {
  const a = region({});
  const b = region({ dismissed: true });
  assert.deepEqual(liveRoots([a, b]).map((r) => r.id), [a.id]);
  assert.deepEqual(dismissedRoots([a, b]).map((r) => r.id), [b.id]);
});

test("groupByEngine: two engines' readings stay apart, hand-drawn under ''", () => {
  const roots = [
    region({ models: ["magi"] }),
    region({ models: ["rapid"] }),
    region({ models: ["magi"] }),
    region({ models: [] }),
  ];
  const groups = groupByEngine(roots);
  assert.deepEqual(groups.map((g) => [g.model, g.regions.length]),
                   [["magi", 2], ["rapid", 1], ["", 1]]);
});

test("inQuad agrees with what is drawn, not with the bounding box", () => {
  // A diamond: its bounding box's corner is OUTSIDE the shape.
  const diamond: [number, number][] = [[0.5, 0.0], [1.0, 0.5],
                                       [0.5, 1.0], [0.0, 0.5]];
  assert.equal(inQuad(0.5, 0.5, diamond), true);
  assert.equal(inQuad(0.05, 0.05, diamond), false, "the corner belongs to nothing");
});

test("inRegion falls back to the box when there is no quad", () => {
  const r = { x: 0.1, y: 0.1, w: 0.2, h: 0.1, quad: [] as [number, number][] };
  assert.equal(inRegion(0.2, 0.15, r), true);
  assert.equal(inRegion(0.5, 0.5, r), false);
});
