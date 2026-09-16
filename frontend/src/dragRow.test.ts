/**
 * ONE ROW DRAG: `shared/useDragRow` measures the drop, sets the grip's
 * data and image, and hangs the one dragend safety net.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { halfOf, quarterOf, insertionIndex } from "./shared/dragRowMath.ts";

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

test("halfOf and quarterOf read the pointer's place in the row", () => {
  assert.equal(halfOf(10, 30), "before"); assert.equal(halfOf(16, 30), "after");
  assert.equal(quarterOf(2, 40), "before"); assert.equal(quarterOf(20, 40), "into"); assert.equal(quarterOf(35, 40), "after");
  assert.equal(quarterOf(0, 0), "into", "a zero-height row is entered, never split");
});

test("insertionIndex lands where the pointer said, not one short", () => {
  // [a b c d]: carry a onto the lower half of c → [b c a d]
  assert.equal(insertionIndex(0, 2, "after"), 2);
  // carry d onto the upper half of b → [a d b c]
  assert.equal(insertionIndex(3, 1, "before"), 1);
  // carry a onto the upper half of b: nothing moves
  assert.equal(insertionIndex(0, 1, "before"), 0);
});

test("the dragend safety net is hung by useDragEndReset (and the body-class one)", () => {
  const offenders = sources().filter((s) => !["shared/dragBody.ts", "shared/useDragRow.ts"].includes(s.rel)
    && /addEventListener\("dragend"/.test(s.text)).map((s) => s.rel);
  assert.deepEqual(offenders, [], "use useDragEndReset: " + offenders.join(", "));
});

test("no list measures the drop half by hand", () => {
  const offenders = sources().filter((s) => s.rel !== "shared/useDragRow.ts"
    && /height \/ 2/.test(s.text) && /clientY/.test(s.text)
    && /(clientY [<>] [^\n]*height \/ 2)/.test(s.text)).map((s) => s.rel);
  assert.deepEqual(offenders, [], "use dropHalf(): " + offenders.join(", "));
});
