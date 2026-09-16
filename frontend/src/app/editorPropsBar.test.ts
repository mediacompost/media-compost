// Run with: npm test  (Node's built-in test runner + type stripping).
//
// THE PROPERTIES BAR IS LISTED, AND THE LIST IS WHAT THE BAR DRAWS.
//
// An empty bar is not nothing on screen — it is its own padding and border,
// a few pixels wide and 42 tall, which over a dark picture reads as a stray
// black mark at the top of the canvas. That is what the pipette showed for as
// long as the gate was `tool !== "hand"`: an exclusion list of one, written
// when the hand was the only tool with nothing to offer, and never revisited
// when a second such tool arrived.
//
// So the gate is a list, and this holds the list to the truth: every tool the
// bar has a branch for is in it, and every tool in it has a branch. A tool
// added with properties and left out of the list would silently lose its bar;
// one added to the list with nothing to draw brings the mark back.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL(".", import.meta.url));
const text = readFileSync(SRC + "components/EditorOverlay.tsx", "utf8");

/** The declared list. */
function declared(): string[] {
  const m = text.match(/const TOOLS_WITH_PROPS: readonly Tool\[] = \[([\s\S]*?)\];/);
  assert.ok(m, "TOOLS_WITH_PROPS must be a literal array of tool ids");
  return [...m![1].matchAll(/"([a-z]+)"/g)].map((x) => x[1]);
}

/** What the bar actually has a branch for. The body runs from the gate to the
 *  closing of the bar's own element, so a `tool === "x"` anywhere else in the
 *  file (the cursor, the hint, a menu) is not mistaken for one. */
function branches(): string[] {
  const from = text.indexOf("TOOLS_WITH_PROPS.includes(tool)");
  assert.ok(from > 0, "the bar must be gated on the list");
  const to = text.indexOf("{/* What you do TO the picture", from);
  assert.ok(to > from, "the props bar's end moved — this test reads the wrong span");
  const body = text.slice(from, to);
  const out = new Set<string>();
  for (const m of body.matchAll(/tool === "([a-z]+)"/g)) out.add(m[1]);
  // `isSelectTool(tool)` is the marquee and the lasso together.
  if (/isSelectTool\(tool\)/.test(body)) { out.add("select"); out.add("lasso"); }
  return [...out];
}

test("every tool with a branch in the properties bar is listed", () => {
  const missing = branches().filter((t) => !declared().includes(t));
  assert.deepEqual(missing, [],
    "these draw properties but the bar is not shown for them: " + missing.join(", "));
});

test("every listed tool actually draws something", () => {
  const extra = declared().filter((t) => !branches().includes(t));
  assert.deepEqual(extra, [],
    "these are listed but have no branch, so the bar would be empty — an 8px " +
      "black mark over the picture: " + extra.join(", "));
});

test("the hand and the pipette have no properties bar", () => {
  for (const t of ["hand", "pipette"]) {
    assert.equal(declared().includes(t), false, `${t} has no properties`);
  }
});
