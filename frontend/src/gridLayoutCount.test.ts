/**
 * THE GRID'S LAYOUT COUNT MAY NOT BE A REF WRITTEN AFTER THE GEOMETRY READ IT.
 *
 * The grid is a cycle: the count lays the cards out, the layout says which
 * rows are near the viewport, that range says which pages to fetch, and the
 * pages answer the count. `useCardGrid` is therefore called BEFORE the hook
 * that knows the total — and the obvious way to close the cycle, a ref
 * assigned just below it, is wrong: the geometry has already read the ref
 * this render, so the new count only reaches the layout at the NEXT one, and
 * nothing guarantees there is one. The fetch range is computed from the
 * SCROLL, not from the count, so a scope change re-renders nothing else: the
 * grid sat at count ZERO with every page loaded and drew nothing at all —
 * "the grid stays completely empty until I reload the page" (owner 2026-09),
 * and the tell was that opening the browser's inspector made the cards
 * appear, because resizing the pane is a render.
 *
 * The count is read from the query CACHE instead, where page 1 has already
 * put it by the time the page queries re-render this component — the same
 * answer, in the same frame.
 *
 * A ratchet because nothing here can see the failure: every test passes, the
 * data is loaded, the DOM is simply missing, and it only shows up when no
 * other render happens to come along.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const GRID = fileURLToPath(new URL("./app/components/ItemGrid.tsx", import.meta.url));

test("the grid's layout count is not read a render late", () => {
  const src = readFileSync(GRID, "utf8");
  const call = src.indexOf("useCardGrid({");
  assert.ok(call > 0, "ItemGrid builds its geometry with useCardGrid");
  // The option object's first line: `count: <expr>,`.
  const count = /\bcount:\s*([^,\n]+)/.exec(src.slice(call));
  assert.ok(count, "useCardGrid is given a count");
  assert.ok(
    !/\.current\b/.test(count[1]),
    `the grid lays out with \`${count[1].trim()}\` — a ref read here is the `
    + "count as of the PREVIOUS render, and after a scope change nothing "
    + "forces the render that would correct it",
  );
});
