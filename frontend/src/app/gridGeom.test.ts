// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import { COLUMN_HYSTERESIS, MAX_SPACER_H, columnsFor, gridWindow, marqueeHits, scrollScale, type GridGeom } from "./gridGeom.ts";

// A concrete layout matching the grid's real constants: PAD 18, GAP 16,
// META_H 40, three columns of 100px cells → rowStride = 100 + 40 + 16 = 156.
const GEOM: GridGeom = {
  columns: 3,
  cellW: 100,
  rowStride: 156,
  total: 8, // last row has two cards (indices 6, 7)
  pad: 18,
  gap: 16,
};

// ---- marqueeHits ------------------------------------------------------------

test("marqueeHits: a rect over the first thumbnail hits index 0 only", () => {
  const hits = marqueeHits(GEOM, { left: 20, top: 20, right: 40, bottom: 40 });
  assert.deepEqual(hits, [0]);
});

test("marqueeHits: spans rows and columns in flat order", () => {
  // Covers columns 0-1 of rows 0-1: cells at x 18..118 and 134..234,
  // rows at y 18..118 and 174..274.
  const hits = marqueeHits(GEOM, { left: 20, top: 20, right: 200, bottom: 200 });
  assert.deepEqual(hits, [0, 1, 3, 4]);
});

test("marqueeHits: the meta strip between rows hits nothing", () => {
  // Row 0's thumbnail band ends at y 118; row 1 starts at 174. A rect wholly
  // inside 119..173 crosses only meta text and the gap.
  const hits = marqueeHits(GEOM, { left: 0, top: 125, right: 400, bottom: 170 });
  assert.deepEqual(hits, []);
});

test("marqueeHits: clipped to the total item count", () => {
  // Row 2 (y 330..430) holds only indices 6 and 7 (total 8).
  const hits = marqueeHits(GEOM, { left: 0, top: 335, right: 1000, bottom: 400 });
  assert.deepEqual(hits, [6, 7]);
});

test("marqueeHits: empty grid or zero columns hit nothing", () => {
  const r = { left: 0, top: 0, right: 1000, bottom: 1000 };
  assert.deepEqual(marqueeHits({ ...GEOM, total: 0 }, r), []);
  assert.deepEqual(marqueeHits({ ...GEOM, columns: 0 }, r), []);
});

// ---- gridWindow -------------------------------------------------------------

const WIN = {
  viewportH: 400,
  total: 100,
  columns: 4,
  cellW: 100,
  metaH: 40,
  pad: 18,
  gap: 16,
  buffer: 3,
};

test("gridWindow: geometry at the top of the scroll", () => {
  const w = gridWindow({ ...WIN, scrollTop: 0 });
  assert.equal(w.rowCount, 25);
  assert.equal(w.firstRow, 0);
  assert.equal(w.startIdx, 0);
  assert.equal(w.offsetTop, 18);
  // 25 rows of 140px cards + 24 gaps of 16 + 2×18 padding.
  assert.equal(w.totalH, 18 * 2 + 25 * 140 + 24 * 16);
  // ceil(400/156)=3 rows in view + 2×3 buffer = 9 rows → rows 0..9.
  assert.equal(w.lastRow, 9);
  assert.equal(w.endIdx, 40);
});

test("gridWindow: scrolled into the middle", () => {
  const w = gridWindow({ ...WIN, scrollTop: 1560 }); // exactly 10 row strides
  assert.equal(w.firstRow, 6); // floor((1560-18)/156)=9, minus buffer 3
  assert.equal(w.startIdx, 24);
  assert.equal(w.offsetTop, 18 + 6 * 156);
  assert.equal(w.lastRow, 15);
  assert.equal(w.endIdx, 64);
});

test("gridWindow: the last window clamps to the item count", () => {
  const w = gridWindow({ ...WIN, scrollTop: 1_000_000 });
  assert.equal(w.lastRow, 24);
  assert.equal(w.endIdx, 100); // not 25*4 rounded past the total
  assert.ok(w.startIdx <= w.endIdx);
});

test("gridWindow: empty view collapses to nothing", () => {
  const w = gridWindow({ ...WIN, total: 0, scrollTop: 0 });
  assert.equal(w.rowCount, 0);
  assert.equal(w.totalH, 0);
  assert.equal(w.lastRow, -1);
  assert.equal(w.startIdx, 0);
  assert.equal(w.endIdx, 0);
});

// ---- how many columns, and why it refuses to flap -----------------------

test("columnsFor is the plain arithmetic with nothing established yet", () => {
  // 168 px cards, 16 px gaps: a column is 184 px of pitch.
  assert.equal(columnsFor(720, 168, 16), 4);   // (720+16)/184 = 4.0
  assert.equal(columnsFor(719, 168, 16), 3);
  assert.equal(columnsFor(904, 168, 16), 5);
  assert.equal(columnsFor(0, 168, 16), 1);
  assert.equal(columnsFor(50, 168, 16), 1);
});

test("a scrollbar-sized wobble across a boundary cannot change the count", () => {
  // The flapping: a track one pixel over the 4-column boundary, losing 15 px
  // to a scrollbar and getting them back. Either way it stays where it was.
  assert.equal(columnsFor(721, 168, 16, 4), 4);
  assert.equal(columnsFor(706, 168, 16, 4), 4);   // -15, would be 3 alone
  assert.equal(columnsFor(721, 168, 16, 3), 3);   // …and the other way round
  assert.equal(columnsFor(706, 168, 16, 3), 3);
});

test("a deliberate resize still changes it, one hysteresis past the edge", () => {
  // 4 columns are the right answer from 720 up; held down to 20 px below that.
  assert.equal(columnsFor(720, 168, 16, 4), 4);
  assert.equal(columnsFor(701, 168, 16, 4), 4);
  assert.equal(columnsFor(700, 168, 16, 4), 3);
  // Upwards: 4 columns hold to 903 + 20.
  assert.equal(columnsFor(923, 168, 16, 4), 4);
  assert.equal(columnsFor(924, 168, 16, 4), 5);
});

test("a wildly different width is taken at once, not walked to", () => {
  // Dragging a window from tiny to huge must not need a step per column.
  assert.equal(columnsFor(1800, 168, 16, 2), 9);
  assert.equal(columnsFor(200, 168, 16, 9), 1);
});

test("what hysteresis costs is bounded: cards never shrink past it", () => {
  // Holding a count over a boundary means dividing the track into cells a
  // little narrower than asked for. That is the whole trade, and it has to
  // stay small — never below one column, and never more than the hysteresis
  // itself narrower than the size that was requested.
  for (let w = 40; w < 2000; w++) {
    for (const prev of [0, 1, 2, 3, 5, 9, 40]) {
      const c = columnsFor(w, 168, 16, prev);
      assert.ok(c >= 1, `w=${w} prev=${prev} gave ${c}`);
      const cellW = (w - (c - 1) * 16) / c;
      assert.ok(c === 1 || cellW >= 168 - COLUMN_HYSTERESIS,
                `w=${w} prev=${prev} gave ${c} columns of ${cellW}px`);
    }
  }
});

// ---- grouped layout ---------------------------------------------------------

import {
  cardBox, groupLayout, groupWindow, marqueeHitsGrouped, sectionOfIndex,
  stepIndex, type GroupLayout, type GroupRun,
} from "./gridGeom.ts";

const G_BASE = { columns: 3, cellW: 100, metaH: 40, pad: 18, gap: 16,
                 headerH: 32, groupGap: 24 };

function lay(runs: GroupRun[], over: Partial<typeof G_BASE> = {}): GroupLayout {
  return groupLayout({ ...G_BASE, ...over, runs });
}

// THE INVARIANT THAT KEEPS GROUPING HONEST: one section with no header and no
// gap must place the cards exactly where the ungrouped grid places them. If
// this drifts, grouping has quietly moved the layout every ungrouped view
// still uses.
//
// The mounted RANGE is deliberately not asserted equal. The two overscan
// models differ: `gridWindow` clamps `firstRow` to 0 and then hangs the whole
// 2×buffer below it, so at the top of a view it mounts twice the buffer
// downward; the band here stays symmetric and simply loses what falls off the
// top. Matching that quirk row-for-row across a layout with headers in it is
// fitting to an accident, so what is pinned instead is the property that
// matters — everything visible is mounted, with real overscan around it.
test("groupLayout: the degenerate case places cards exactly like gridWindow", () => {
  const flat = { columns: 3, cellW: 140, metaH: 0, pad: 18, gap: 16 };
  const L = lay([{ key: "all", count: 75 }],
                { ...flat, headerH: 0, groupGap: 0 });
  const ref = gridWindow({ ...flat, total: 75, scrollTop: 0, viewportH: 400,
                           buffer: 3 });
  assert.equal(L.totalH, ref.totalH, "the scrollbar must span the same content");
  for (const scrollTop of [0, 100, 733, 2000]) {
    const gw = groupWindow({ layout: L, scrollTop, viewportH: 400, buffer: 3 });
    const rw = gridWindow({ ...flat, total: 75, scrollTop, viewportH: 400,
                            buffer: 3 });
    assert.equal(gw.startIdx, rw.startIdx, `startIdx @${scrollTop}`);
    assert.equal(gw.slices[0].offsetTop, rw.offsetTop, `offsetTop @${scrollTop}`);
  }
  // Every card the ungrouped grid would put on screen is in the same place.
  for (let i = 0; i < L.total; i++) {
    const b = cardBox(L, i)!;
    assert.equal(b.top, 18 + Math.floor(i / 3) * 156);
    assert.equal(b.left, 18 + (i % 3) * 156);
  }
});

test("groupWindow: everything in the viewport is mounted, with overscan", () => {
  const runs = [{ key: "a", count: 7 }, { key: "b", count: 1 },
                { key: "c", count: 40 }, { key: "d", count: 3 }];
  const L = lay(runs);
  const viewportH = 380;
  for (let scrollTop = 0; scrollTop <= L.totalH; scrollTop += 29) {
    const w = groupWindow({ layout: L, scrollTop, viewportH, buffer: 2 });
    for (let i = 0; i < L.total; i++) {
      const b = cardBox(L, i)!;
      const onScreen = b.top + b.height > scrollTop
                    && b.top < scrollTop + viewportH;
      if (!onScreen) continue;
      assert.ok(i >= w.startIdx && i < w.endIdx,
                `card ${i} is visible at ${scrollTop} but not mounted`);
    }
  }
});

test("groupLayout: sections tile the index space with no gaps", () => {
  const L = lay([{ key: "a", count: 5 }, { key: "b", count: 1 },
                 { key: "c", count: 9 }]);
  assert.equal(L.total, 15);
  let at = 0;
  for (const s of L.sections) {
    assert.equal(s.startIdx, at);
    at = s.endIdx;
  }
  assert.equal(at, 15);
});

test("groupLayout: an empty run is dropped, not given a header", () => {
  const L = lay([{ key: "a", count: 2 }, { key: "empty", count: 0 },
                 { key: "b", count: 2 }]);
  assert.deepEqual(L.sections.map((s) => s.key), ["a", "b"]);
});

test("groupLayout: y is monotone and headers clear the previous section", () => {
  const L = lay([{ key: "a", count: 4 }, { key: "b", count: 7 },
                 { key: "c", count: 1 }]);
  for (let i = 1; i < L.sections.length; i++) {
    assert.ok(L.sections[i].headerTop >= L.sections[i - 1].bottom,
              "sections must not overlap in y");
  }
});

// The claim the fetch layer rests on: whatever is mounted is ONE contiguous
// range, so `useItemView({start, end})` needs no change at all.
test("groupWindow: the mounted range is contiguous and fully covered", () => {
  const runs = [{ key: "a", count: 7 }, { key: "b", count: 1 },
                { key: "c", count: 40 }, { key: "d", count: 3 },
                { key: "e", count: 22 }];
  const L = lay(runs);
  for (let scrollTop = 0; scrollTop < L.totalH + 400; scrollTop += 37) {
    const w = groupWindow({ layout: L, scrollTop, viewportH: 380, buffer: 2 });
    if (!w.slices.length) continue;
    const covered: number[] = [];
    let prevEnd = -1;
    for (const s of w.slices) {
      assert.ok(s.startIdx >= prevEnd || s.startIdx === s.endIdx,
                "slices must ascend and not overlap");
      for (let i = s.startIdx; i < s.endIdx; i++) covered.push(i);
      if (s.endIdx > s.startIdx) prevEnd = s.endIdx;
    }
    assert.equal(w.startIdx, covered.length ? covered[0] : w.startIdx);
    for (let i = 0; i < covered.length; i++) {
      assert.equal(covered[i], covered[0] + i,
                   `a hole at scrollTop ${scrollTop}`);
    }
    if (covered.length) assert.equal(w.endIdx, covered[covered.length - 1] + 1);
  }
});

test("groupWindow: a section's partial last row never spills into the next", () => {
  // 4 items over 3 columns: row 1 holds index 3 alone.
  const L = lay([{ key: "a", count: 4 }, { key: "b", count: 6 }]);
  const w = groupWindow({ layout: L, scrollTop: 0, viewportH: 5000, buffer: 0 });
  const a = w.slices.find((s) => s.section === 0)!;
  assert.equal(a.endIdx, 4, "clamped to the section, not to (row+1)*columns");
});

// A scroll position past the content is not hypothetical: the view can shrink
// under one (a trash, a filter) before the scroller is told. An empty window
// there renders nothing at all, which reads as a broken grid.
test("groupWindow: a stale scroll past the end yields the end, not nothing", () => {
  const L = lay([{ key: "a", count: 4 }, { key: "b", count: 20 }]);
  const w = groupWindow({ layout: L, scrollTop: 999_999, viewportH: 400,
                          buffer: 2 });
  assert.ok(w.slices.length > 0, "must mount something");
  assert.equal(w.endIdx, L.total, "and it must be the last of the content");
});

test("groupWindow: currentSection tracks the top edge", () => {
  const L = lay([{ key: "a", count: 3 }, { key: "b", count: 3 },
                 { key: "c", count: 3 }]);
  assert.equal(groupWindow({ layout: L, scrollTop: 0, viewportH: 300,
                             buffer: 0 }).currentSection, 0);
  const w = groupWindow({ layout: L, scrollTop: L.sections[2].headerTop + 4,
                          viewportH: 300, buffer: 0 });
  assert.equal(w.currentSection, 2);
});

// ---- marqueeHitsGrouped -----------------------------------------------------

// The bug the ungrouped clamp would have carried in: `marqueeHits` ends the
// whole scan at the first index past the total, which in a grouped layout
// means everything below a partial last row silently stops selecting.
test("marqueeHitsGrouped: a drag through a partial last row keeps going", () => {
  const L = lay([{ key: "a", count: 4 }, { key: "b", count: 6 }]);
  const hits = marqueeHitsGrouped(L, {
    left: 0, top: 0, right: 10_000, bottom: L.totalH,
  });
  assert.deepEqual(hits, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
});

test("marqueeHitsGrouped: a rect in a header band hits nothing", () => {
  const L = lay([{ key: "a", count: 3 }, { key: "b", count: 3 }]);
  const b = L.sections[1];
  const hits = marqueeHitsGrouped(L, {
    left: 0, top: b.headerTop + 2, right: 10_000, bottom: b.rowsTop - 2,
  });
  assert.deepEqual(hits, []);
});

test("marqueeHitsGrouped: hits ascend, so the same-hits shortcut still fires", () => {
  const L = lay([{ key: "a", count: 5 }, { key: "b", count: 5 },
                 { key: "c", count: 5 }]);
  const hits = marqueeHitsGrouped(L, {
    left: 0, top: 0, right: 10_000, bottom: L.totalH,
  });
  assert.deepEqual(hits, [...hits].sort((x, y) => x - y));
});

// ---- stepIndex --------------------------------------------------------------

test("stepIndex: up and down round-trip across a section boundary", () => {
  // Section a is 5 items over 3 columns (rows: 0,1,2 / 3,4), b starts at 5 —
  // so b's startIdx is NOT a multiple of columns, which is exactly what the
  // naive cur ± columns gets wrong.
  const L = lay([{ key: "a", count: 5 }, { key: "b", count: 6 }]);
  const down = stepIndex(L, 4, "down");   // a row 1 col 1 -> b row 0 col 1
  assert.equal(down, 6);
  assert.equal(stepIndex(L, down, "up"), 4, "must return where it started");
});

test("stepIndex: down from a full row into a partial one clamps", () => {
  const L = lay([{ key: "a", count: 4 }]);        // rows: 0,1,2 / 3
  assert.equal(stepIndex(L, 2, "down"), 3, "column 2 has no card below it");
});

test("stepIndex: left and right cross boundaries in reading order", () => {
  const L = lay([{ key: "a", count: 4 }, { key: "b", count: 3 }]);
  assert.equal(stepIndex(L, 3, "right"), 4);
  assert.equal(stepIndex(L, 4, "left"), 3);
  assert.equal(stepIndex(L, 0, "left"), 0);
  assert.equal(stepIndex(L, 6, "right"), 6);
});

test("stepIndex: never leaves the layout", () => {
  const L = lay([{ key: "a", count: 5 }, { key: "b", count: 2 }]);
  for (let i = 0; i < L.total; i++) {
    for (const d of ["left", "right", "up", "down"] as const) {
      const n = stepIndex(L, i, d);
      assert.ok(n >= 0 && n < L.total, `${i} ${d} -> ${n}`);
    }
  }
});

// ---- sectionOfIndex / cardBox -----------------------------------------------

test("sectionOfIndex: finds the owner, and -1 outside", () => {
  const L = lay([{ key: "a", count: 3 }, { key: "b", count: 4 }]);
  assert.equal(sectionOfIndex(L, 0), 0);
  assert.equal(sectionOfIndex(L, 2), 0);
  assert.equal(sectionOfIndex(L, 3), 1);
  assert.equal(sectionOfIndex(L, 6), 1);
  assert.equal(sectionOfIndex(L, 7), -1);
  assert.equal(sectionOfIndex(L, -1), -1);
});

test("cardBox: agrees with where marqueeHitsGrouped finds the card", () => {
  const L = lay([{ key: "a", count: 4 }, { key: "b", count: 5 }]);
  for (let i = 0; i < L.total; i++) {
    const b = cardBox(L, i)!;
    const hits = marqueeHitsGrouped(L, {
      left: b.left + 1, top: b.top + 1,
      right: b.left + 2, bottom: b.top + 2,
    });
    assert.deepEqual(hits, [i], `card ${i}`);
  }
});

test("groupWindow: the pill stands down when a header is in its band", () => {
  // b is deliberately TALL (10 rows), so "deep inside its rows" is a real
  // place rather than already the next section's header.
  const L = lay([{ key: "a", count: 6 }, { key: "b", count: 30 },
                 { key: "c", count: 6 }]);
  const b = L.sections[1];
  // Scrolled to just above b's header — where a JUMP lands. The pill would
  // otherwise name section a directly over b's own header.
  const w = groupWindow({ layout: L, scrollTop: b.headerTop - G_BASE.pad,
                          viewportH: 400, buffer: 1 });
  assert.equal(w.currentHeaderOnScreen, true);
  // Deep inside a section's rows there is no header to collide with, so the
  // pill is the only thing that can say where you are.
  const mid = groupWindow({ layout: L, scrollTop: b.rowsTop + 4 * L.rowStride,
                            viewportH: 200, buffer: 0 });
  assert.equal(mid.currentHeaderOnScreen, false);
});

// ---- scrollScale: the scaled scrollbar past the browser's height cap -------

test("scrollScale: under the cap is the identity", () => {
  const s = scrollScale(5_000_000, 600);
  assert.equal(s.physH, 5_000_000);
  assert.equal(s.k, 1);
});

test("scrollScale: over the cap, the two scroll ranges map end to end", () => {
  const totalH = 52_000_000, vp = 600;
  const s = scrollScale(totalH, vp);
  assert.equal(s.physH, MAX_SPACER_H);
  // Physical zero is virtual zero, and the BOTTOM of the physical range is
  // exactly the bottom of the virtual one — the last row must be reachable,
  // not `cap/totalH` short of it.
  assert.equal(0 * s.k, 0);
  const virtAtBottom = (s.physH - vp) * s.k;
  assert.ok(Math.abs(virtAtBottom - (totalH - vp)) < 1e-6);
});

test("scrollScale: a jump target round-trips through the conversion", () => {
  const s = scrollScale(52_000_000, 600);
  const headerTop = 40_000_000;               // deep in the library
  const phys = headerTop / s.k;               // what jumpToGroup writes
  assert.ok(phys < s.physH - 600);            // within the physical range
  assert.ok(Math.abs(phys * s.k - headerTop) < 1e-3);  // lands where aimed
});
