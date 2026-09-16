/**
 * WHAT THE APP SHOWS ABOUT ONE JOB, swept in one place.
 *
 * The right-hand pane reads a job through six queries — the record, its
 * timeline (events, samples, checkpoints) and its log — and only the ones a
 * RUNNING job needs poll on their own: everything else is refetched when
 * somebody says something has changed. A caller that says it by
 * invalidating `["train-jobs"]` alone therefore updates the LIST and leaves
 * the pane on what it was showing, which is what "saving an edit does not
 * add its entry to the timeline until I deselect and select the job again"
 * was: on a paused job nothing polls at all, so the edit's own event had no
 * way in.
 *
 * So it is a list, in one module rather than at each call site: the pane
 * grows a query far more often than a caller remembers to widen its sweep.
 */
import type { QueryClient } from "@tanstack/react-query";

/** Keyed `[name, uid]`. `train-metrics` is deliberately absent — it
 *  accumulates incrementally from its own cursor, so an invalidation would
 *  ask for what it already has. */
const PER_JOB = ["train-job", "train-events", "train-samples",
                 "train-checkpoints", "train-log"] as const;

/** The list, plus everything about one job when a uid is given. */
export function invalidateJob(qc: QueryClient, uid?: string | null): void {
  void qc.invalidateQueries({ queryKey: ["train-jobs"] });
  if (!uid) return;
  for (const key of PER_JOB) {
    void qc.invalidateQueries({ queryKey: [key, uid] });
  }
}
