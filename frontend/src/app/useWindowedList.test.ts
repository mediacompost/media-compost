// The windowing arithmetic — the half of `useWindowedList` that can be
// stated rather than watched.
//
// This exists because of a bug that was invisible to every test the project
// had: the Sets tab mounted all 17,245 of a tag set's rows for one render,
// 375,000 DOM nodes and 1.2 seconds of blocked main thread, and then quietly
// windowed back down to a screenful. Nothing was WRONG afterwards — the list
// was correct, the API was fast, the statement counts were flat — so only a
// stopwatch on the browser could see it. The rule it broke is arithmetic,
// and arithmetic can be asserted.

import assert from "node:assert/strict";
import test from "node:test";

import { windowRange } from "./useWindowedList.ts";

const ROW = 44;
const SCREEN = 900;

test("a list at rest mounts a screenful and the overscan", () => {
  const w = windowRange({
    count: 17245, rowHeight: ROW, overscan: 10,
    rel: 0, clientHeight: 600, viewportHeight: SCREEN,
  });
  assert.equal(w.start, 0);
  // ceil(600 / 44) + 20 = 34 — a screenful, not seventeen thousand.
  assert.equal(w.end, Math.ceil(600 / ROW) + 20);
});

test("scrolled down, the window follows and keeps its size", () => {
  const w = windowRange({
    count: 17245, rowHeight: ROW, overscan: 10,
    rel: 4400, clientHeight: 600, viewportHeight: SCREEN,
  });
  assert.equal(w.start, 100 - 10);
  assert.equal(w.end - w.start, Math.ceil(600 / ROW) + 20);
});

test("AN UNBOUNDED PANE STILL MOUNTS ONLY A SCREENFUL", () => {
  // THE REGRESSION. A pane whose max-height is measured is unbounded until
  // the measurement lands, and for that one render its scroller's
  // clientHeight is its whole content. Sized against that, "how many rows
  // fit" answered ALL OF THEM.
  const count = 17245;
  const w = windowRange({
    count, rowHeight: ROW, overscan: 10,
    rel: 0, clientHeight: count * ROW, viewportHeight: SCREEN,
  });
  assert.ok(w.end - w.start < 100,
            `mounted ${w.end - w.start} rows for a ${SCREEN}px screen`);
  assert.equal(w.end, Math.ceil(SCREEN / ROW) + 20);
});

test("a scroller shorter than the screen is the bound, not the screen", () => {
  // The cap is a ceiling, never a floor: a small pane mounts a small window.
  const w = windowRange({
    count: 500, rowHeight: ROW, overscan: 4,
    rel: 0, clientHeight: 220, viewportHeight: SCREEN,
  });
  assert.equal(w.end, Math.ceil(220 / ROW) + 8);
});

test("the window never runs past the end of the list", () => {
  const w = windowRange({
    count: 12, rowHeight: ROW, overscan: 10,
    rel: 0, clientHeight: 5000, viewportHeight: SCREEN,
  });
  assert.equal(w.start, 0);
  assert.equal(w.end, 12);
});
