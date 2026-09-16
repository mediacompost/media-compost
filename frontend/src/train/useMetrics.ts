// The job's loss points, fetched once for the whole detail pane.
//
// Two things read them — the graph, and the progress line above it — and they
// must be the same points: the query accumulates incrementally (`?after=`), so
// a second component with its own copy would either refetch everything every
// 2.5 s or quietly disagree with the first.
//
// What accumulates is BOUNDED (`compactMetrics`): the server answers a full
// fetch with about two thousand points however long the run is, and an
// incremental one with everything new, so an unbounded accumulator was the
// page growing by one object per training step for as long as it stayed open.
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, TrainMetricPoint } from "./api";
import { compactMetrics } from "./metricsWindow";

export interface Metrics {
  points: TrainMetricPoint[];
  /** Steps whose loss was not a usable number (the run diverged into NaN). */
  diverged: number;
}

export function useMetrics(uid: string, active: boolean): Metrics {
  const acc = useRef<{ uid: string; points: TrainMetricPoint[]; last: number }>(
    { uid, points: [], last: 0 }
  );
  const [diverged, setDiverged] = useState(0);
  useEffect(() => {
    if (acc.current.uid !== uid) acc.current = { uid, points: [], last: 0 };
  }, [uid]);

  const { data: points = [] } = useQuery({
    queryKey: ["train-metrics", uid],
    queryFn: async () => {
      if (acc.current.uid !== uid) acc.current = { uid, points: [], last: 0 };
      const r = await api.trainMetrics(uid, acc.current.last);
      if (acc.current.last === 0) acc.current.points = r.points;
      else if (r.points.length) {
        acc.current.points = compactMetrics(
          [...acc.current.points, ...r.points]);
      }
      acc.current.last = Math.max(acc.current.last, r.last_step);
      if (r.diverged !== undefined) setDiverged(r.diverged);
      return acc.current.points.slice();
    },
    refetchInterval: active ? 2500 : false,
  });
  return { points, diverged };
}

/** How fast the run is going and what that means for the time left.
 *
 *  Measured over the last handful of steps rather than the whole run: the rate
 *  changes when a sampling round or a checkpoint lands in the middle, and an
 *  average over an hour would hide that. Gaps longer than `GAP` are pauses,
 *  server restarts or sampling rounds — time the next step did not cost — so
 *  they are left out instead of being smeared into the estimate.
 */
const GAP = 120;

export function pace(points: TrainMetricPoint[], window = 20):
    { secPerStep: number; loss: number } | null {
  if (points.length < 2) return null;
  const tail = points.slice(-window);
  let seconds = 0, steps = 0;
  for (let i = 1; i < tail.length; i++) {
    const dt = tail[i].t - tail[i - 1].t;
    const ds = tail[i].step - tail[i - 1].step;
    if (dt <= 0 || ds <= 0 || dt > GAP) continue;
    seconds += dt;
    steps += ds;
  }
  if (!steps || !seconds) return null;
  return { secPerStep: seconds / steps, loss: tail[tail.length - 1].loss };
}

/** "4 min", "2 h 10 min" — a duration people read at a glance, rounded to the
 *  precision it deserves (nobody needs seconds on a two-hour estimate). */
export function fmtEta(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return "";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  const mins = Math.round(seconds / 60);
  if (mins < 90) return `${mins} min`;
  const h = Math.floor(mins / 60);
  return `${h} h ${mins - h * 60} min`;
}
