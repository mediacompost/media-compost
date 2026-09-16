// Incremental counters for an import task's file list — pure, unit-tested.
//
// `taskProgress` / `taskCounts` used to be O(files) reductions over the whole
// list, called per row per render while a big import emitted progress ticks;
// these counters are updated at each status transition / progress tick instead,
// so reading them is O(1) however many files a drop staged.
//
// The weights are the ones the old whole-list computation used: a terminal
// file counts 1, "processing" 0.95, "uploading" its upload fraction × 0.9 —
// the test suite checks the counters against exactly that oracle.

export type ImportFileStatus =
  | "pending" | "uploading" | "processing" | "done" | "error" | "canceled";

export interface ImportCounters {
  total: number;
  n: Record<ImportFileStatus, number>;
  /** Sum of `progress` over the files currently in "uploading". */
  uploadSum: number;
}

export function newCounters(total: number): ImportCounters {
  return {
    total,
    n: { pending: total, uploading: 0, processing: 0, done: 0, error: 0, canceled: 0 },
    uploadSum: 0,
  };
}

/** A file moved `from` → `to`. `fromProgress` is the file's upload fraction at
 *  that moment (read before overwriting it); it only matters when the file is
 *  LEAVING "uploading". A file entering "uploading" starts at fraction 0 — the
 *  caller resets its progress alongside. */
export function onTransition(
  c: ImportCounters,
  from: ImportFileStatus,
  to: ImportFileStatus,
  fromProgress: number,
): void {
  if (from === to) return;
  c.n[from] -= 1;
  c.n[to] += 1;
  if (from === "uploading") c.uploadSum -= fromProgress;
}

/** An uploading file's fraction moved `prev` → `next`. */
export function onProgressTick(c: ImportCounters, prev: number, next: number): void {
  c.uploadSum += next - prev;
}

/** 0..1 overall task progress — same figure the old per-file reduction gave. */
export function progressOf(c: ImportCounters): number {
  if (c.total === 0) return 1;
  const sum =
    c.n.done + c.n.error + c.n.canceled +
    c.n.processing * 0.95 +
    c.uploadSum * 0.9;
  return sum / c.total;
}

export interface TaskCounts {
  done: number;
  error: number;
  /** Everything still moving: pending + uploading + processing. */
  pending: number;
  total: number;
}

export function countsOf(c: ImportCounters): TaskCounts {
  return {
    done: c.n.done,
    error: c.n.error,
    pending: c.n.pending + c.n.uploading + c.n.processing,
    total: c.total,
  };
}

// ---- files that landed somewhere invisible ---------------------------------

/** Why a file's import needs saying out loud although it worked. */
export type ImportWarning = "hidden" | "trashed";

/** Match the run's `hidden_matches` onto the batch's files.
 *
 *  The backend names a file the way IT saw it — the path relative to the root
 *  it was handed, which for a folder drop is `subdir/name.png` and for a loose
 *  file is the bare name — while the browser knows it as `rel`, its display
 *  path. Those agree for a loose file and differ by a prefix for a nested one,
 *  so the rule is a SUFFIX match, falling back to the basename.
 *
 *  A name is claimed by at most one file (two folders can hold `page01.png`,
 *  and the run reports one entry per landing), so matched files are struck off
 *  as they are found. Pure and here rather than in the manager because this is
 *  the module `node --test` can load.
 */
export function matchWarnings<T extends { rel: string }>(
  files: T[], pairs: unknown,
): Map<T, ImportWarning> {
  const out = new Map<T, ImportWarning>();
  if (!Array.isArray(pairs)) return out;
  const base = (s: string) => s.slice(s.lastIndexOf("/") + 1);
  for (const pair of pairs) {
    if (!Array.isArray(pair) || pair.length < 2) continue;
    const name = String(pair[0]).replace(/^\.\//, "");
    const kind = String(pair[1]) === "trashed" ? "trashed" : "hidden";
    const hit =
      files.find((f) => !out.has(f) && (f.rel === name || f.rel.endsWith("/" + name)))
      ?? files.find((f) => !out.has(f) && base(f.rel) === base(name));
    if (hit) out.set(hit, kind);
  }
  return out;
}

/** WHERE A RESUMED IMPORT PICKS UP, given its files' statuses in order.
 *
 *  Cancelling drops the files from the cursor forward without throwing their
 *  `File` handles away, so what is left to do is exactly known — this is the
 *  rule for what comes back:
 *
 *  - a CANCELLED file goes back to pending, because nothing was decided
 *    about it;
 *  - an ERRORED one does not. That file was read, handed over and refused
 *    for a reason the row already carries, and a resume that quietly retried
 *    it would be hiding what it said;
 *  - a DONE one stays done, which is what makes a resume cheap: the run
 *    continues, it does not start again.
 *
 *  Answers the index of the first file that comes back, or -1 for a task
 *  with nothing to resume. Pure, and here rather than in the manager because
 *  this is the module `node --test` can load.
 */
export function resumeFrom(statuses: readonly ImportFileStatus[]): number {
  return statuses.indexOf("canceled");
}
