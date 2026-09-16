/**
 * ONE DIVIDER: `shared/Split` owns the drag, the clamp and the body class.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { clampSplit } from "./shared/splitMath.ts";

const SRC = fileURLToPath(new URL(".", import.meta.url));
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "locales") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}
const sources = () => ["app", "train", "shared", "query"].flatMap((d) => walk(join(SRC, d)))
  .map((p) => ({ rel: p.slice(SRC.length), text: readFileSync(p, "utf8") }));

test("clampSplit keeps a size between its bounds and inside the room", () => {
  assert.equal(clampSplit(300, { min: 200, max: 500 }), 300);
  assert.equal(clampSplit(100, { min: 200, max: 500 }), 200);
  assert.equal(clampSplit(900, { min: 200, max: 500 }), 500);
  assert.equal(clampSplit(450, { min: 200, max: 500, room: 800, restMin: 400 }), 400, "the other side keeps its floor");
  assert.equal(clampSplit(300.6, { min: 200, max: 500 }), 301, "whole pixels");
  assert.equal(clampSplit(50, { min: 200, max: 500, room: 100, restMin: 400 }), 200, "min wins over a room too small for both");
});

test("only Split arms the body's resizing class", () => {
  const offenders = sources().filter((s) => s.rel !== "shared/Split.tsx" && /classList\.(add|remove)\("resizing/.test(s.text)).map((s) => s.rel);
  assert.deepEqual(offenders, [], "use useSplit: " + offenders.join(", "));
});

test("only Split draws a col-resize / row-resize handle", () => {
  const offenders = sources().filter((s) => s.rel !== "shared/Split.tsx" && /cursor: "(col|row)-resize"/.test(s.text)).map((s) => s.rel);
  assert.deepEqual(offenders, [], "use <SplitHandle>: " + offenders.join(", "));
});
