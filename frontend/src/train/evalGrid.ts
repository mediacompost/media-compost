/** Walking the Evaluate tab's contact sheet with the arrow keys.
 *
 * The grid is one flat reading order (`tilesOf` over the sessions, newest
 * first) laid out as one grid PER SESSION, each starting a fresh row. So
 * `cur ± columns` is wrong rather than merely imprecise — the library grid's
 * lesson, in this tab's terms: a session's first index is generally not a
 * multiple of `columns`, so a naive step slides the cursor sideways at every
 * session boundary and never round-trips.
 *
 * Pure, so the cases are stated as tests rather than as prose. The sessions
 * all sit in one scroll column and so share a column count; if that ever
 * stops being true this takes a count per section instead.
 */

export interface GridSection {
  /** The section's first index in the flat reading order. */
  start: number;
  /** How many tiles it holds (never zero — a session with no tiles is not
   *  rendered). */
  count: number;
}

export type StepDir = "left" | "right" | "up" | "down";

/** Which section holds `i`, or -1. */
function sectionOf(sections: GridSection[], i: number): number {
  for (let k = 0; k < sections.length; k++) {
    const s = sections[k];
    if (i >= s.start && i < s.start + s.count) return k;
  }
  return -1;
}

/** The index the cursor moves to. Always a real tile: every step is clamped
 *  into the grid, and ↑/↓ off the top or bottom row of a section land on the
 *  neighbouring section's nearest row rather than doing nothing — a section
 *  boundary is a row boundary, not a wall. */
export function stepTile(sections: GridSection[], columns: number,
                         cur: number, dir: StepDir): number {
  const cols = Math.max(1, columns);
  const total = sections.reduce((n, s) => n + s.count, 0);
  const last = total - 1;
  if (last < 0) return 0;
  const at = Math.min(Math.max(0, cur), last);
  if (dir === "left") return Math.max(0, at - 1);
  if (dir === "right") return Math.min(last, at + 1);
  const si = sectionOf(sections, at);
  if (si < 0) return at;
  const s = sections[si];
  const off = at - s.start;
  const row = Math.floor(off / cols);
  const col = off % cols;
  const rows = Math.ceil(s.count / cols);
  if (dir === "down") {
    // The last row of a section is usually partial, so a step down its short
    // end goes to that row's last tile rather than past the section.
    if (row + 1 < rows) return Math.min(s.start + (row + 1) * cols + col,
                                        s.start + s.count - 1);
    const n = sections[si + 1];
    if (!n) return last;
    return Math.min(n.start + col, n.start + n.count - 1);
  }
  if (row > 0) return s.start + (row - 1) * cols + col;
  const p = sections[si - 1];
  if (!p) return 0;
  const pRows = Math.ceil(p.count / cols);
  return Math.min(p.start + (pRows - 1) * cols + col, p.start + p.count - 1);
}
