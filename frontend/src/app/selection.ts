// Pure selection-state helpers for the UI store (unit-tested with node --test,
// like coalesce.ts — keep this module React-free).
//
// The grid selection can reach hundreds of thousands of ids (Cmd+A on a big
// library, a long marquee drag), so the hot paths here — "did the selection
// actually change?" during a marquee frame, pushing undo history, stashing the
// editor-navigation order — are written to stay O(n) with no throwaway Set
// allocation per call.

/** Selection-history entries larger than this are not recorded: a 500k-id
 *  Cmd+A pushed 50 entries deep would pin tens of MB of ids forever. */
export const HISTORY_MAX_ENTRY = 100_000;

/** How many selection-history entries are kept (browser-style Back/Forward). */
export const HISTORY_CAP = 50;

/** How many ids either side of the opened item the editor-nav hand-off keeps. */
export const NAV_RADIUS = 500;

/**
 * The ONE way the selection pair (list + lockstep Set) advances. Returns the
 * new pair, or null when `next` is (order-insensitively) the same selection.
 * The no-change check runs against the EXISTING set — the old `sameIds` built
 * a fresh Set per call, which a marquee drag paid once per frame.
 */
export function selectionUpdate(
  prevList: number[],
  prevSet: ReadonlySet<number>,
  next: number[]
): { list: number[]; set: ReadonlySet<number> } | null {
  if (next.length === prevList.length) {
    let same = true;
    for (let i = 0; i < next.length; i++) {
      if (!prevSet.has(next[i])) {
        same = false;
        break;
      }
    }
    // Equal lengths with next ⊆ prev is only "the same selection" when
    // `next` holds no duplicate: a grid window assembled across two library
    // revisions (an external importer mid-run) can hand a marquee the same
    // id twice, and [A, A] must not read as equal to [A, B]. The Set is
    // built only on this would-be no-change path, so the frames the check
    // exists to keep allocation-free — the ones that DID change — still
    // allocate exactly once, below.
    if (same && new Set(next).size !== next.length) same = false;
    if (same) return null;
  }
  const set = new Set(next);
  // The stored list is duplicate-free too — every consumer iterates it as
  // "the selected items", and one item twice would count, render and act
  // twice.
  return { list: set.size === next.length ? next : [...set], set };
}

/** Order-insensitive "same selection" between two history entries. */
export function sameEntry(a: number[], b: number[]): boolean {
  if (a.length !== b.length) return false;
  const bs = new Set(b);
  for (const id of a) if (!bs.has(id)) return false;
  return true;
}

/**
 * Append `entry` to a selection-history stack: the oldest entries are dropped
 * past `cap`, and an oversized entry is skipped entirely (the stack is
 * returned unchanged, so callers can assign the result unconditionally).
 *
 * AN ENTRY EQUAL TO THE TOP IS NOT RECORDED. The pushes record the PRIOR
 * selection, and a selection cleared and then re-made records the same ids
 * either side of an EMPTY state nothing records (clearing pushes the old
 * selection; re-selecting from empty deliberately pushes nothing) — so
 * X → clear → X → Y stacked [X, X], and Back walked to the selection already
 * on screen. The same ids MAY appear twice with a different selection between
 * them; only the consecutive copy says nothing.
 */
export function pushHistory(
  past: number[][],
  entry: number[],
  cap = HISTORY_CAP
): number[][] {
  if (entry.length > HISTORY_MAX_ENTRY) return past;
  if (past.length && sameEntry(entry, past[past.length - 1])) return past;
  const out = [...past, entry];
  return out.length > cap ? out.slice(out.length - cap) : out;
}

/**
 * A window of `ids` around `centerId` (the item being opened), for the
 * editor-navigation localStorage hand-off. Writing the WHOLE visible-id list
 * threw a silent QuotaExceededError past ~500k ids, and an editor's
 * prev/next only ever walks near where it was opened anyway. The window keeps
 * its full width at either end of the list; an unknown center falls back to
 * the head of the list.
 */
export function navWindow(
  ids: number[],
  centerId: number,
  radius = NAV_RADIUS
): number[] {
  const width = radius * 2 + 1;
  if (ids.length <= width) return ids.slice();
  let i = ids.indexOf(centerId);
  if (i === -1) i = 0;
  const lo = Math.max(0, Math.min(i - radius, ids.length - width));
  return ids.slice(lo, lo + width);
}
