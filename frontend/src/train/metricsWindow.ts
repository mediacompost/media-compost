// HOW MANY LOSS POINTS THE TAB KEEPS, and which ones it lets go of.
//
// The server answers a FULL fetch (`after=0`) with about two thousand points
// however long the run is (`_MAX_METRIC_POINTS`): a 720-unit-wide chart cannot
// show more, so a reload costs the same at step 200 and at step 200,000. Every
// INCREMENTAL fetch returns everything new, because the client is meant to
// append it to what it already has — and left alone, that is one point per
// step for as long as the tab is open.
//
// Which is what a tab left open all day was doing. Measured against a run
// writing 400 steps a second: 4,600 points became 11,300 over twelve polls,
// the chart's two SVG path strings grew from 106 KB to 260 KB with them, and
// nothing ever gave any of it back — where a reload snapped the page straight
// back to two thousand. At a real day's run (65,000 steps) that is 65,000
// point objects held, six derived arrays of that length rebuilt into the chart
// on every 2.5-second poll, and a megabyte of path string in the DOM. Past
// ~125,000 it stops being a memory question: `Math.min(...ys)` on an array
// that long throws `RangeError: Maximum call stack size exceeded` and the
// whole Train tab lands on its error boundary.
//
// So the client holds itself to the server's own ceiling, with one difference:
// THE RECENT TAIL IS KEPT WHOLE. What is read off the tail has to be exact —
// the pace and the ETA (`pace()` reads the last twenty points' stamps) and the
// live end of the curve, which is the half anybody watching a run is watching.
// The older half is thinned by the same plain stride the server uses, so what
// the graph draws after an hour is what a reload would have drawn.
//
// Thinning the head again at every compaction means the oldest stretch is
// coarser than the middle, which is the right way round: an hour-old loss
// curve is read as a shape, and a minute-old one point by point.

// TYPE-ONLY, so `node --test` (which strips types and then resolves what is
// left) never tries to load the API module for a shape.
import type { TrainMetricPoint } from "./api";

/** Compact once the array passes this — not at the target, so a compaction
 *  happens once per THOUSAND new points rather than on nearly every poll
 *  (the grid's column hysteresis, for the same reason). */
export const COMPACT_AT = 4000;
/** How many of the older points survive one compaction. */
export const HEAD_KEEP = 2000;
/** How many of the newest are never touched. */
export const TAIL_KEEP = 1000;

/**
 * The points to keep, given everything fetched so far.
 *
 * Returns the array UNCHANGED below the threshold — identity is what the
 * chart's `useMemo`s hang on, and a fresh array per poll would rebuild every
 * one of them for nothing.
 */
export function compactMetrics(
  points: TrainMetricPoint[],
  compactAt = COMPACT_AT,
  headKeep = HEAD_KEEP,
  tailKeep = TAIL_KEEP,
): TrainMetricPoint[] {
  if (points.length <= compactAt) return points;
  const cut = Math.max(0, points.length - tailKeep);
  const head = points.slice(0, cut);
  const kept: TrainMetricPoint[] = [];
  const seen = new Set<number>();
  const take = (p: TrainMetricPoint | undefined) => {
    if (!p || seen.has(p.step)) return;
    seen.add(p.step);
    kept.push(p);
  };
  const stride = head.length / headKeep;
  for (let i = 0; i < headKeep; i++) take(head[Math.floor(i * stride)]);
  // A VALIDATION ROUND IS ONE POINT IN HUNDREDS, so a plain stride drops most
  // of the very series the thinning exists to protect — the server's own rule
  // for the same sampling.
  for (const p of head) {
    if (p.val != null || p.stable != null) take(p);
  }
  kept.sort((a, b) => a.step - b.step);
  return kept.concat(points.slice(cut));
}
