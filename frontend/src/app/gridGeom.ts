// Pure grid-geometry math for the windowed item grid (unit-tested with
// node --test — keep this module React-free). The grid renders a fixed-size
// card per INDEX of a view of `total` items, whether or not that index's item
// is loaded yet; only arithmetic lives here, so the per-frame marquee
// hit-testing and the visible-window computation stay allocation-light and
// testable without a DOM.

export interface GridGeom {
  /** Number of columns (>= 1 for a non-empty grid). */
  columns: number;
  /** Width of one cell in px — also the thumbnail band's height (cards are a
   *  square thumb plus a fixed meta block). */
  cellW: number;
  /** Vertical distance between row tops (card height + gap). */
  rowStride: number;
  /** Total number of items in the view, loaded or not. */
  total: number;
  /** Padding around the grid, px. */
  pad: number;
  /** Gap between cells, px. */
  gap: number;
}

export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/**
 * How near a column boundary the track has to get before the count is allowed
 * to change, in px. Comfortably more than any scrollbar (15–17 px on the
 * platforms this runs on) and a small fraction of a column, so a real resize
 * still changes the count where you would expect it to.
 */
export const COLUMN_HYSTERESIS = 20;

/**
 * HOW MANY COLUMNS FIT — refusing to change on a width that is merely
 * wobbling across a boundary.
 *
 * `floor((trackW + gap) / (cell + gap))` is the whole of the arithmetic, and
 * on its own it is a hair trigger: a track sitting within a pixel of a
 * boundary flips the count on any width change at all, however small and
 * whatever caused it. A layout that then feeds back into the width — a
 * scrollbar appearing because the new count made the content taller, a
 * measurement that rounds the other way — flips it straight back, and the grid
 * flashes between three and four cards a row, several times a second, until
 * something else moves.
 *
 * `scrollbar-gutter: stable` already removed the one cause anybody had
 * identified, and the flashing was reported again afterwards. So rather than
 * hunt the next source of a few pixels, this makes the count indifferent to
 * ALL of them: once a count is established it is kept until the track is
 * `COLUMN_HYSTERESIS` px clear of the range that count is right for. A wobble
 * smaller than that cannot flip anything, whatever produced it; a deliberate
 * resize still does, one column-width later.
 *
 * `prev` of 0 (or nothing) means "no established count" — a first measurement
 * takes the arithmetic as it stands.
 */
export function columnsFor(
  trackW: number, cell: number, gap: number, prev = 0,
): number {
  const pitch = cell + gap;
  if (!(trackW > 0) || !(pitch > 0)) return 1;
  const raw = Math.max(1, Math.floor((trackW + gap) / pitch));
  if (prev < 1 || prev === raw) return raw;
  // The track widths `prev` columns are the right answer for, widened by the
  // hysteresis at both ends. Inside that, `prev` stands.
  const lo = prev * pitch - gap - COLUMN_HYSTERESIS;
  const hi = (prev + 1) * pitch - gap + COLUMN_HYSTERESIS;
  return trackW > lo && trackW < hi ? prev : raw;
}

/**
 * Flat item INDICES whose thumbnail band intersects `rect` (scroll-content
 * coordinates). Indices, not ids: with windowed pages an index may not be
 * loaded yet, and the caller resolves ids and skips the unloaded ones.
 * Only the thumbnail band counts — a rect entirely within the meta/gap strip
 * between two rows hits nothing (same rule the old inline version had).
 */
export function marqueeHits(g: GridGeom, r: Rect): number[] {
  const out: number[] = [];
  if (g.columns < 1 || g.total <= 0 || g.rowStride <= 0) return out;
  const rowFrom = Math.max(0, Math.floor((r.top - g.pad) / g.rowStride));
  const rowTo = Math.floor((r.bottom - g.pad) / g.rowStride);
  for (let row = rowFrom; row <= rowTo; row++) {
    const top = g.pad + row * g.rowStride;
    if (top + g.cellW < r.top || top > r.bottom) continue; // thumbnail band only
    for (let col = 0; col < g.columns; col++) {
      const left = g.pad + col * (g.cellW + g.gap);
      if (left + g.cellW < r.left || left > r.right) continue;
      const idx = row * g.columns + col;
      if (idx >= g.total) return out; // past the last item — nothing below it
      out.push(idx);
    }
  }
  return out;
}

// ---- grouped layout ---------------------------------------------------------
//
// THE SECTIONS ARE CONTIGUOUS RUNS OF THE SERVER ORDER, which is the whole
// reason grouping costs so little here: the backend's `/api/items/groups`
// prepends the grouping to the same ORDER BY the pages use, so prefix-summing
// the runs' counts gives each section its [startIdx, endIdx) in the SAME flat
// index space the ungrouped grid already pages through. `useItemView` and the
// flat-index -> page mapping are therefore untouched.
//
// The ungrouped functions above stay exactly as they were and still run
// whenever `groupBy` is "none" — the degenerate case below is asserted equal
// to them, rather than the two being merged into one parameterised path.

export interface GroupRun {
  /** Machine key from the server: "202403", "a", a band index. Never a label
   *  — month and colour names are localized at the render site. */
  key: string;
  count: number;
}

export interface GroupSection {
  index: number;
  key: string;
  count: number;
  /** Flat item indices this section owns: [startIdx, endIdx). */
  startIdx: number;
  endIdx: number;
  rowCount: number;
  /** Content-space y of the header's top. */
  headerTop: number;
  /** Content-space y of the first card row (headerTop + headerH). */
  rowsTop: number;
  /** Content-space y past the last row — EXCLUDING the trailing groupGap. */
  bottom: number;
}

export interface GroupLayout {
  sections: GroupSection[];
  /** Sum of the run counts: the index space this layout describes. */
  total: number;
  totalH: number;
  // Echoed inputs, so the marquee, the keyboard and the renderer all read ONE
  // object and cannot disagree with the layout they were built from.
  columns: number;
  cellW: number;
  cardH: number;
  rowStride: number;
  headerH: number;
  groupGap: number;
  pad: number;
  gap: number;
}

/**
 * Lay out `runs` as sections of cards. Scroll-independent — memoize it.
 *
 * A run of `count <= 0` is DROPPED rather than laid out: a header with no
 * rows under it is worse than a missing group, and it would break the
 * "sections tile the index space with no gaps" invariant that the window, the
 * marquee and the keyboard all depend on.
 */
export function groupLayout(o: {
  runs: readonly GroupRun[];
  columns: number;
  cellW: number;
  metaH: number;
  pad: number;
  gap: number;
  /** Fixed height of a section header, including its own bottom spacing. */
  headerH: number;
  /** Space between one section's last row and the next section's header. */
  groupGap: number;
}): GroupLayout {
  const cardH = o.cellW + o.metaH;
  const rowStride = cardH + o.gap;
  const sections: GroupSection[] = [];
  let y = o.pad;
  let at = 0;
  for (const run of o.runs) {
    if (!(run.count > 0)) continue;
    const rowCount = o.columns > 0 ? Math.ceil(run.count / o.columns) : 0;
    const rowsTop = y + o.headerH;
    const bottom = rowsTop + rowCount * cardH + Math.max(0, rowCount - 1) * o.gap;
    sections.push({
      index: sections.length, key: run.key, count: run.count,
      startIdx: at, endIdx: at + run.count, rowCount,
      headerTop: y, rowsTop, bottom,
    });
    at += run.count;
    y = bottom + o.groupGap;
  }
  const totalH = sections.length
    ? sections[sections.length - 1].bottom + o.pad : 0;
  return {
    sections, total: at, totalH, columns: o.columns, cellW: o.cellW, cardH,
    rowStride, headerH: o.headerH, groupGap: o.groupGap, pad: o.pad, gap: o.gap,
  };
}

export interface GroupWindowSlice {
  /** Index into layout.sections. */
  section: number;
  /** Mount this section's header? */
  header: boolean;
  /** Content-space top of this slice's first mounted row. */
  offsetTop: number;
  /** Flat indices to mount: [startIdx, endIdx). May be empty when only the
   *  header is in band. */
  startIdx: number;
  endIdx: number;
}

export interface GroupWindow {
  slices: GroupWindowSlice[];
  totalH: number;
  /** ONE contiguous range covering every mounted index — what the fetch layer
   *  gets. Contiguous because sections tile both the index space and y
   *  monotonically, so only the FIRST section in band is clipped from the top
   *  and only the LAST from the bottom; everything between is mounted whole. */
  startIdx: number;
  endIdx: number;
  /** Section owning the viewport's top scanline; -1 when empty. */
  currentSection: number;
  /** True while SOME header is showing in the band a pinned pill would
   *  occupy, so the pill can stand down rather than sit on top of one.
   *
   *  Both neighbours count, not just the current section's own header. After
   *  a jump the scroll lands just ABOVE the target's header, which makes the
   *  target `currentSection + 1` — so checking only the current section left
   *  the pill naming the PREVIOUS section directly over the header of the one
   *  you had just jumped to. */
  currentHeaderOnScreen: boolean;
}

/**
 * Which sections and cards to mount for a scroll position.
 *
 * `buffer` becomes a PIXEL band rather than a row count: a per-section row
 * buffer is ambiguous for a section shorter than the buffer, and a band makes
 * the header's own visibility fall out of the same comparison.
 */
export function groupWindow(o: {
  layout: GroupLayout;
  scrollTop: number;
  viewportH: number;
  buffer: number;
}): GroupWindow {
  const L = o.layout;
  const empty: GroupWindow = {
    slices: [], totalH: L.totalH, startIdx: 0, endIdx: 0,
    currentSection: -1, currentHeaderOnScreen: false,
  };
  if (!L.sections.length || L.columns < 1 || L.rowStride <= 0) return empty;

  // A stale scroll position — the view just shrank under it — must yield the
  // view's END rather than an empty window past every section. `gridWindow`
  // clamps its firstRow for the same reason.
  const scrollTop = Math.max(0, Math.min(o.scrollTop,
                                         Math.max(0, L.totalH - L.rowStride)));
  const pad = o.buffer * L.rowStride;
  const bandTop = scrollTop - pad;
  const bandBottom = scrollTop + o.viewportH + pad;

  // First section whose content reaches into the band.
  let lo = 0, hi = L.sections.length - 1, first = L.sections.length;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (L.sections[mid].bottom > bandTop) { first = mid; hi = mid - 1; }
    else lo = mid + 1;
  }
  if (first >= L.sections.length) first = L.sections.length - 1;

  const slices: GroupWindowSlice[] = [];
  for (let i = first; i < L.sections.length; i++) {
    const s = L.sections[i];
    if (s.headerTop >= bandBottom) break;
    const header = s.headerTop < bandBottom && s.rowsTop > bandTop;
    let startIdx = s.startIdx, endIdx = s.startIdx, offsetTop = s.rowsTop;
    if (s.rowCount > 0 && s.rowsTop < bandBottom && s.bottom > bandTop) {
      const rowFrom = Math.min(
        Math.max(0, Math.floor((bandTop - s.rowsTop) / L.rowStride)),
        s.rowCount - 1);
      const rowTo = Math.min(
        Math.max(0, Math.floor((bandBottom - s.rowsTop) / L.rowStride)),
        s.rowCount - 1);
      startIdx = s.startIdx + rowFrom * L.columns;
      // Clamped to the SECTION's end, not the layout's — the twin of
      // gridWindow's `Math.min(o.total, …)`, and the reason a partial last
      // row does not spill into the next section.
      endIdx = Math.min(s.endIdx, s.startIdx + (rowTo + 1) * L.columns);
      offsetTop = s.rowsTop + rowFrom * L.rowStride;
    }
    if (!header && startIdx === endIdx) continue;
    slices.push({ section: i, header, offsetTop, startIdx, endIdx });
  }
  if (!slices.length) return empty;

  // The section under the viewport's top edge.
  let cur = 0;
  for (let i = 0; i < L.sections.length; i++) {
    if (L.sections[i].headerTop <= scrollTop) cur = i;
    else break;
  }
  // The pill's own band: from the top of the viewport past a header's height.
  const bandEnd = scrollTop + L.headerH + L.pad;
  const showing = (i: number) => {
    const s = L.sections[i];
    return !!s && s.headerTop >= scrollTop - L.headerH && s.headerTop < bandEnd;
  };
  return {
    slices,
    totalH: L.totalH,
    startIdx: slices[0].startIdx,
    endIdx: slices[slices.length - 1].endIdx,
    currentSection: cur,
    currentHeaderOnScreen: showing(cur) || showing(cur + 1),
  };
}

/** Section holding a flat index, or -1. */
export function sectionOfIndex(layout: GroupLayout, idx: number): number {
  let lo = 0, hi = layout.sections.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const s = layout.sections[mid];
    if (idx < s.startIdx) hi = mid - 1;
    else if (idx >= s.endIdx) lo = mid + 1;
    else return mid;
  }
  return -1;
}

/** Content-space box of one card — the grouped replacement for
 *  `pad + floor(i / columns) * rowStride`. */
export function cardBox(
  layout: GroupLayout, idx: number,
): { left: number; top: number; width: number; height: number } | null {
  const si = sectionOfIndex(layout, idx);
  if (si < 0) return null;
  const s = layout.sections[si];
  const off = idx - s.startIdx;
  const row = Math.floor(off / layout.columns);
  const col = off % layout.columns;
  return {
    left: layout.pad + col * (layout.cellW + layout.gap),
    top: s.rowsTop + row * layout.rowStride,
    width: layout.cellW,
    height: layout.cardH,
  };
}

/**
 * Flat indices whose thumbnail band intersects `r`, grouped-layout aware.
 *
 * The one line that must NOT be carried over from `marqueeHits` is its total
 * clamp: there it is `return out`, correct only because a flat grid has
 * nothing after its last partial row. Here every section has one, so it
 * becomes a per-section `break` of the column loop — otherwise a marquee
 * dragged from a section with a partial last row through the next one selects
 * nothing in the second, while visibly covering it.
 *
 * Results stay in ascending flat order: the grid compares them element-wise
 * against the previous frame to avoid writing the store on every drag frame.
 */
export function marqueeHitsGrouped(layout: GroupLayout, r: Rect): number[] {
  const out: number[] = [];
  if (layout.columns < 1 || layout.rowStride <= 0) return out;
  for (const s of layout.sections) {
    if (s.bottom < r.top) continue;
    if (s.rowsTop > r.bottom) break;
    const rowFrom = Math.max(0, Math.floor((r.top - s.rowsTop) / layout.rowStride));
    const rowTo = Math.min(s.rowCount - 1,
                           Math.floor((r.bottom - s.rowsTop) / layout.rowStride));
    for (let row = rowFrom; row <= rowTo; row++) {
      const top = s.rowsTop + row * layout.rowStride;
      if (top + layout.cellW < r.top || top > r.bottom) continue;
      for (let col = 0; col < layout.columns; col++) {
        const left = layout.pad + col * (layout.cellW + layout.gap);
        const idx = s.startIdx + row * layout.columns + col;
        if (idx >= s.endIdx) break; // this section's partial last row ends here
        if (left + layout.cellW < r.left || left > r.right) continue;
        out.push(idx);
      }
    }
  }
  return out;
}

/**
 * Arrow-key movement across sections.
 *
 * Left/right stay `cur ± 1`: the flat order IS the reading order across a
 * boundary. Up/down must preserve the COLUMN and clamp into the target
 * section's partial row — a section's `startIdx` is generally not a multiple
 * of `columns`, so the naive `cur ± columns` slides the cursor sideways at
 * every boundary and does not round-trip.
 */
export function stepIndex(
  layout: GroupLayout, cur: number, dir: "left" | "right" | "up" | "down",
): number {
  const last = layout.total - 1;
  if (last < 0) return 0;
  if (dir === "left") return Math.max(0, cur - 1);
  if (dir === "right") return Math.min(last, cur + 1);
  const si = sectionOfIndex(layout, cur);
  if (si < 0) return Math.min(Math.max(0, cur), last);
  const s = layout.sections[si];
  const off = cur - s.startIdx;
  const row = Math.floor(off / layout.columns);
  const col = off % layout.columns;
  if (dir === "down") {
    if (row + 1 < s.rowCount) {
      const t = s.startIdx + (row + 1) * layout.columns + col;
      return t < s.endIdx ? t : s.endIdx - 1; // the last row is partial
    }
    const n = layout.sections[si + 1];
    if (!n) return last;
    return Math.min(n.startIdx + col, n.endIdx - 1);
  }
  if (row > 0) return s.startIdx + (row - 1) * layout.columns + col;
  const p = layout.sections[si - 1];
  if (!p) return 0;
  return Math.min(p.startIdx + (p.rowCount - 1) * layout.columns + col,
                  p.endIdx - 1);
}

export interface GridWindow {
  rowCount: number;
  firstRow: number;
  /** Last rendered row (-1 when the grid is empty). */
  lastRow: number;
  /** First rendered flat index. */
  startIdx: number;
  /** One past the last rendered flat index. */
  endIdx: number;
  /** Height of the whole scroll content, so the scrollbar spans the view. */
  totalH: number;
  /** Content-space top of the first rendered row. */
  offsetTop: number;
}

/**
 * The visible window of a grid of `total` fixed-size cards: which flat index
 * range to mount for the current scroll position, and the full content height.
 * Same equations the grid used inline before windowed pages — kept exact, the
 * marquee math and placeholder cards depend on it.
 */
export function gridWindow(o: {
  scrollTop: number;
  viewportH: number;
  total: number;
  columns: number;
  cellW: number;
  /** Height of the meta block under each thumbnail. */
  metaH: number;
  pad: number;
  gap: number;
  /** Extra rows rendered above and below the viewport. */
  buffer: number;
}): GridWindow {
  const cardH = o.cellW + o.metaH;
  const rowStride = cardH + o.gap;
  const rowCount = o.columns > 0 ? Math.ceil(Math.max(0, o.total) / o.columns) : 0;
  const totalH =
    rowCount > 0 ? o.pad * 2 + rowCount * cardH + (rowCount - 1) * o.gap : 0;
  // Clamped to the last row: a stale scroll position (the view just shrank
  // under it) must yield the view's end, not a window past every item.
  const firstRow = Math.min(
    Math.max(0, Math.floor((o.scrollTop - o.pad) / rowStride) - o.buffer),
    Math.max(0, rowCount - 1)
  );
  const rowsInView = Math.ceil(o.viewportH / rowStride) + o.buffer * 2;
  const lastRow = Math.min(rowCount - 1, firstRow + rowsInView);
  const startIdx = firstRow * o.columns;
  const endIdx = Math.max(startIdx, Math.min(o.total, (lastRow + 1) * o.columns));
  return {
    rowCount,
    firstRow,
    lastRow,
    startIdx,
    endIdx,
    totalH,
    offsetTop: o.pad + firstRow * rowStride,
  };
}

/**
 * THE BROWSER CAPS AN ELEMENT'S HEIGHT, and a big grouped library is taller.
 *
 * Chromium's layout unit tops out just under 2^24 px (a 600,000-item library
 * grouped by month lays out to ~52,000,000 px; its scroller measured
 * `scrollHeight` 16,777,214) and Firefox caps near 17.9M — so above the cap
 * every `scrollTop` write silently CLAMPS, which is how "jump to section"
 * landed a third of the way into the library and could never reach further.
 *
 * The answer is the scaled scrollbar: the spacer takes a capped height and
 * only the SCROLLER's coordinate space is compressed. Everything else — the
 * window computation, the marquee, the section headers, the jump targets —
 * stays in the layout's own (virtual) space; reads of the DOM scroller
 * multiply by `k` and writes divide by it. At `k === 1` (every library under
 * the cap) both are exact no-ops.
 */
export const MAX_SPACER_H = 12_000_000;

export interface ScrollScale {
  /** The spacer's rendered height — `totalH` until the cap, then the cap. */
  physH: number;
  /** virtual px per physical scroll px (>= 1). */
  k: number;
}

export function scrollScale(
  totalH: number, viewportH: number, cap = MAX_SPACER_H,
): ScrollScale {
  if (totalH <= cap) return { physH: totalH, k: 1 };
  // Both spaces scroll over [0, H - viewport]; the ratio of those ranges is
  // what maps the ends onto each other exactly — the last row is reachable
  // at the bottom of the physical range, not `cap/totalH` short of it.
  const span = Math.max(1, cap - viewportH);
  return { physH: cap, k: (totalH - viewportH) / span };
}

// The three thumbnail sizes offered by the grid's segmented size control
// (px = the grid's minimum column width). Keep the M value in sync with the
// store default. `key` is the MACHINE token (React key); `letter` is the
// DISPLAY glyph, routed through t() so CJK catalogs can say 小/中/大 and
// pt-BR P/M/G. Single-letter catalog keys are shared app-wide — if "S" ever
// needs a different translation in another context, split the keys then.
// Lives here (not in ItemGrid.tsx) so `i18nCoverage.test.ts` can import it
// and hold both the letters and the labels to catalog entries, the same
// treatment COLOR_BANDS gets.
export const GRID_SIZES = [
  { key: "S", letter: "S", label: "Small", px: 124 },
  { key: "M", letter: "M", label: "Medium", px: 168 },
  { key: "L", letter: "L", label: "Large", px: 232 },
] as const;
