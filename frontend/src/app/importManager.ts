// A page-level import engine, independent of any component. Each *drop* becomes
// an import **task** that keeps running even after the Import overlay is closed
// (the File objects live in memory for the session). Tasks are surfaced in the
// left sidebar and the Import overlay; a simple subscribe/emit lets React
// components re-render on progress.

import { useSyncExternalStore } from "react";
import { api } from "./api";
import { bumpLibrary } from "./invalidation";
import { makeCoalescer } from "./coalesce";
import {
  ImportCounters, ImportWarning, countsOf, matchWarnings, newCounters,
  onProgressTick, onTransition, progressOf, resumeFrom,
} from "./importStats";

export interface DropSettings {
  parentId: number | null;
  /** A group of this run's own, INSIDE `parentId`. An empty name means the
   *  backend's own default (a timestamp), which is where that answer lives
   *  so this door and the CLI cannot drift. */
  newGroup?: boolean;
  newGroupName?: string;
  foldersAsGroups: boolean;
  archivesAsGroups: boolean;
  archiveSequences: boolean;
  /** Which half of a SEQUENCE joins the run's groups: both | container |
   *  members (`ImportOptions.sequence_grouping`). */
  sequenceGrouping?: string;
  /** The run's minimums; 0 is "not set" and a file must clear every one
   *  that is. A sequence is kept whole — any page clearing them is enough. */
  minMegapixels?: number;
  minShortEdge?: number;
  minLongEdge?: number;
  /** The run's aspect RANGE, width/height — narrower than `minAspect` or
   *  wider than `maxAspect` is left out. 0 is "not set" on each side. */
  minAspect?: number;
  maxAspect?: number;
  /** File types to leave alone (image / video / sequence / archive). */
  ignoreKinds?: string[];
  /** Model key to detect faces with on what was imported; "" = don't. */
  detectFaces?: string;
  /** Embedder id to index what was imported with (the tag batch's smart
   *  ordering); "" = don't. */
  indexEmbeddings?: string;
  /** Tags put on everything the run creates, plus per-kind lists. */
  tags?: string[];
  tagsExisting?: boolean;
  tagsImage?: string[];
  tagsVideo?: string[];
  tagsSequence?: string[];
}

export type ImportFileStatus =
  | "pending" | "uploading" | "processing" | "done" | "error" | "canceled";

export interface ImportFile {
  id: number;
  file: File;
  rel: string;       // display path (folder/name)
  status: ImportFileStatus;
  progress: number;  // 0..1 upload fraction
  message?: string;
  /** The import WORKED and still needs saying out loud: these bytes landed on
   *  an item that is hidden or in the Trash, so the picture is in the library
   *  and nowhere the grid will show it. Not a status — the file is `done`. */
  warning?: ImportWarning;
}

export interface ImportTask {
  id: number;
  label: string;
  settings: DropSettings;
  files: ImportFile[];
  createdAt: number;
  canceled: boolean;
  // Rolling outcome, folded in per completed batch.
  imported: number;
  skipped: number;
  /** Files the run's own minimums or type filter left out (`ImportOptions`).
   *  Separate from `skipped`, which is the library already having them. */
  ignored: number;
  /** How many files landed on a hidden or trashed item (see `ImportFile`). */
  warnings: number;
  /** Batch cursor: every file before this index has been handed to a batch
   *  (terminal or in flight); the next batch starts here. Slicing from it
   *  replaced re-filtering the whole file list per batch. */
  nextIdx: number;
  /** Incremental status counters (importStats.ts) — taskProgress/taskCounts
   *  read these in O(1) instead of reducing over every file. */
  counters: ImportCounters;
}

const BATCH_MAX_FILES = 200;
const BATCH_MAX_BYTES = 250 * 1e6;

let _fid = 0;
let _tid = 0;
let tasks: ImportTask[] = [];
const listeners = new Set<() => void>();

// Per-task control: the in-flight upload's AbortController.
const abortByTask = new Map<number, AbortController>();

// Every server-side import job THIS page started. The server keeps its own
// record of each one (it outlives the page), and the background-task list
// shows the ones nobody is watching — so it has to be able to tell those from
// the ones this page is already drawing a row for. Not persisted: after a
// reload the page owns none of them, which is exactly the case the list is
// for.
const ownJobs = new Set<string>();

export function ownsImportJob(id: string): boolean {
  return ownJobs.has(id);
}

function emit() {
  // New array identity so hooks relying on reference equality re-render.
  tasks = tasks.slice();
  listeners.forEach((l) => l());
}

// Upload-progress ticks arrive per network chunk — far faster than a progress
// bar needs to repaint. They coalesce into one trailing emit per ~100 ms;
// status TRANSITIONS keep emitting immediately (those are the moments a row
// changes what it says, not just how full its bar is).
const progressEmit = makeCoalescer(() => emit(), { wait: 100, maxWait: 100 });

export function subscribeImports(l: () => void): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}
export function getImportTasks(): ImportTask[] {
  return tasks;
}
/** Subscribe a React component to the live import task list. */
export function useImportTasks(): ImportTask[] {
  return useSyncExternalStore(subscribeImports, getImportTasks);
}

// ---- status bookkeeping ----------------------------------------------------

/** The one place a file's status changes, so the counters can never drift. */
function setStatus(task: ImportTask, f: ImportFile, status: ImportFileStatus) {
  if (f.status === status) return;
  onTransition(task.counters, f.status, status, f.progress);
  f.status = status;
  if (status === "uploading") f.progress = 0;
  if (status === "processing") {
    // Entering "processing" means the upload finished.
    f.progress = 1;
  }
}

function setProgress(task: ImportTask, f: ImportFile, p: number) {
  if (f.status !== "uploading" || p === f.progress) return;
  onProgressTick(task.counters, f.progress, p);
  f.progress = p;
}

// ---- derived helpers (pure) ------------------------------------------------

const TERMINAL: ImportFileStatus[] = ["done", "error", "canceled"];
export function isTerminal(f: ImportFile): boolean {
  return TERMINAL.includes(f.status);
}
export function taskDone(t: ImportTask): boolean {
  const c = t.counters.n;
  return c.pending + c.uploading + c.processing === 0;
}
export function taskActive(t: ImportTask): boolean {
  return t.counters.n.uploading + t.counters.n.processing > 0;
}
/** A finished task whose every file imported cleanly (no errors/cancellations).
 *  Such tasks auto-clear from the list shortly after completion. */
export function taskSucceeded(t: ImportTask): boolean {
  return !t.canceled && t.files.length > 0 && t.counters.n.done === t.files.length;
}
/** 0..1 overall progress across the task's files — O(1) over the counters. */
export function taskProgress(t: ImportTask): number {
  return progressOf(t.counters);
}
export function taskCounts(t: ImportTask) {
  return countsOf(t.counters);
}

// ---- engine ----------------------------------------------------------------

function invalidateAfterBatch() {
  // Coalesced: a large import finishes many batches in quick succession, and
  // each used to trigger its own O(library) refetch sweep.
  bumpLibrary();
}

/** Upload + ingest a set of a task's files as one request, splitting on a
 *  transport failure to isolate the bad file. Aborts propagate to the caller. */
async function uploadBatch(task: ImportTask, items: ImportFile[]): Promise<void> {
  if (items.length === 0) return;
  const s0 = task.settings;
  // setProgress too, not just setStatus: a transport-failure retry re-enters
  // "uploading" without a status change, and its bar restarts at 0.
  for (const it of items) { setStatus(task, it, "uploading"); setProgress(task, it, 0); }
  emit();
  const ctrl = new AbortController();
  abortByTask.set(task.id, ctrl);
  try {
    const job = await api.importFiles(items.map((b) => b.file), {
      parent_group_id: s0.parentId,
      new_group: s0.newGroup ?? false,
      new_group_name: s0.newGroupName ?? "",
      folders_as_groups: s0.foldersAsGroups,
      archives_as_groups: s0.archivesAsGroups,
      archive_sequences: s0.archiveSequences,
      sequence_grouping: s0.sequenceGrouping ?? "both",
      min_megapixels: s0.minMegapixels ?? 0,
      min_short_edge: s0.minShortEdge ?? 0,
      min_long_edge: s0.minLongEdge ?? 0,
      min_aspect: s0.minAspect ?? 0,
      max_aspect: s0.maxAspect ?? 0,
      ignore_kinds: s0.ignoreKinds ?? [],
      detect_faces: s0.detectFaces ?? "",
      index_embeddings: s0.indexEmbeddings ?? "",
      tagsExisting: s0.tagsExisting ?? true,
      tags: s0.tags ?? [],
      tags_image: s0.tagsImage ?? [],
      tags_video: s0.tagsVideo ?? [],
      tags_sequence: s0.tagsSequence ?? [],
      signal: ctrl.signal,
      onUploadProgress: (p) => {
        for (const it of items) setProgress(task, it, p);
        progressEmit.call();
      },
    });
    ownJobs.add(job.id);
    for (const it of items) setStatus(task, it, "processing");
    emit();
    let stats: Record<string, unknown> = {};
    let delay = 30;
    // WHAT THE SERVER HAS GOT THROUGH, while it is getting through it. This
    // poll was already running and its `stats` were already arriving; only
    // the LAST one was read, so a batch of 200 sat at "0/600 files" with a
    // motionless bar for the whole of its import and then jumped by 200.
    //
    // Marked in the server's OWN order — it imports `sorted(staging.iterdir())`
    // — so the file list shows the ones actually behind it rather than
    // whichever happened to be sent first.
    const byName = [...items].sort((a, b) => a.rel.localeCompare(b.rel));
    let marked = 0;
    const advance = () => {
      const n = Math.min(Number(stats.processed) || 0, byName.length);
      if (n <= marked) return;
      for (; marked < n; marked++) setStatus(task, byName[marked], "done");
      emit();
    };
    for (;;) {
      const s = await api.importJob(job.id);
      stats = s.stats as Record<string, unknown>;
      if (s.status === "error") throw new Error(s.message || "import failed");
      advance();
      if (s.status !== "running") break;
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(300, Math.round(delay * 1.6));
    }
    task.imported += items.length;
    // Both kinds of "stored nothing" — the byte-identical duplicate and what
    // the run's minimum resolution turned away. They are one number on the
    // row because they are one fact about the batch (these files are not in
    // the library), and an import that dropped files while reporting only
    // what it took is the one thing this line exists to prevent.
    task.skipped += (stats.skipped_duplicate as number) ?? 0;
    // ITS OWN counter, not folded into the duplicates: "you already have
    // this" and "you told me not to take this" are different answers, and
    // one number for both reads as "these are here somewhere".
    task.ignored += (stats.ignored as number) ?? 0;
    // Files that landed out of sight. Marked before the status change so one
    // emit carries both, and counted on the task so the row can say so without
    // walking every file.
    for (const [f, kind] of matchWarnings(items, stats.hidden_matches)) {
      f.warning = kind;
      task.warnings += 1;
    }
    for (const it of items) setStatus(task, it, "done");
    invalidateAfterBatch();
    emit();
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    // Halving isolates the ONE bad file — a transport failure, or a run the
    // server could not finish because of something in the batch. A request
    // the server REFUSED (a 4xx: options it will not take, a body it cannot
    // read) is refused again however the batch is cut, so splitting it only
    // re-uploads every byte on the way to the same answer for each file.
    if (items.length > 1 && !refused(err)) {
      const mid = Math.ceil(items.length / 2);
      await uploadBatch(task, items.slice(0, mid));
      await uploadBatch(task, items.slice(mid));
      return;
    }
    setStatus(task, items[0], "error");
    items[0].message = String((err as Error).message);
    emit();
  } finally {
    abortByTask.delete(task.id);
  }
}

/** Whether the server answered a request with a 4xx — `api.importFiles`
 *  rejects with `"<status>: <body>"`, and only that status class means the
 *  request itself was turned away rather than failing partway. */
function refused(err: unknown): boolean {
  return /^4\d\d:/.test(String((err as Error)?.message ?? ""));
}

async function runTask(task: ImportTask): Promise<void> {
  while (!task.canceled) {
    // Slice the next batch from the cursor instead of re-filtering the whole
    // list per batch — everything before nextIdx has already been handed out.
    const batch: ImportFile[] = [];
    let bytes = 0;
    let i = task.nextIdx;
    for (; i < task.files.length; i++) {
      const it = task.files[i];
      if (it.status !== "pending") continue;
      if (batch.length > 0 &&
          (batch.length >= BATCH_MAX_FILES || bytes + it.file.size > BATCH_MAX_BYTES)) break;
      batch.push(it);
      bytes += it.file.size;
    }
    if (batch.length === 0) break;
    // Advance before the upload: the batch's files are captured, and a cancel
    // then only has to mark from the cursor forward.
    task.nextIdx = i;
    try {
      await uploadBatch(task, batch);
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        // A cancel aborted the in-flight request: mark remaining non-terminal
        // files canceled and stop.
        for (const f of task.files) if (!isTerminal(f)) setStatus(task, f, "canceled");
        emit();
        break;
      }
      for (const it of batch) if (it.status !== "done") {
        setStatus(task, it, "error");
        it.message = String((err as Error).message);
      }
      emit();
    }
  }
  emit();
  // A cleanly-successful import clears itself shortly after finishing (a
  // failed or canceled one stays so the user can see and dismiss it) — and so
  // does one that has something to SAY: a warning nobody read before it
  // disappeared would be the silence it exists to break.
  if (taskSucceeded(task) && task.warnings === 0) {
    setTimeout(() => dismissImportTask(task.id), 2500);
  }
}

// ---- public API ------------------------------------------------------------

/** Queue a new import task for a set of dropped/selected files. */
export function addImportTask(files: File[], relOf: (f: File) => string, settings: DropSettings): void {
  const importFiles: ImportFile[] = files.map((f) => ({
    id: ++_fid, file: f, rel: relOf(f), status: "pending", progress: 0,
  }));
  if (importFiles.length === 0) return;
  const top = importFiles[0].rel.split("/")[0];
  const label = importFiles.length === 1
    ? importFiles[0].rel
    : `${importFiles.length} files${top && top !== importFiles[0].rel ? ` · ${top}` : ""}`;
  const task: ImportTask = {
    id: ++_tid, label, settings, files: importFiles, createdAt: Date.now(),
    warnings: 0,
    canceled: false, imported: 0, skipped: 0, ignored: 0,
    nextIdx: 0, counters: newCounters(importFiles.length),
  };
  tasks = [...tasks, task];
  emit();
  void runTask(task);
}

/** Cancel a whole task: abort any in-flight upload and drop pending files.
 *  Everything before the cursor is terminal or in the aborted request, so only
 *  the files from the cursor forward can still be "pending". */
export function cancelImportTask(taskId: number): void {
  const task = tasks.find((t) => t.id === taskId);
  if (!task) return;
  task.canceled = true;
  for (let i = task.nextIdx; i < task.files.length; i++) {
    const f = task.files[i];
    if (f.status === "pending") setStatus(task, f, "canceled");
  }
  abortByTask.get(taskId)?.abort();
  emit();
}

/** Put a cancelled task's untouched files back and carry on.
 *
 *  Cancelling drops the files from the cursor forward; it does not throw the
 *  `File` handles away, so what is left to do is still exactly known and the
 *  browser can pick it up where it stopped. Without this a cancel was final
 *  — the only way back was to drop the same folder again and let the whole
 *  thing dedup its way through what had already landed.
 *
 *  CANCELLED files only. An ERROR is a different answer: that file was read,
 *  handed over, and refused for a reason the row already carries, and a
 *  resume that quietly retried it would be hiding what it said. Everything
 *  DONE stays done, which is what makes this cheap — the run continues, it
 *  does not start again.
 *
 *  Session-local, like the task list itself: a reload takes the `File`
 *  handles with it, and nothing here can ask for them back.
 */
export function resumeImportTask(taskId: number): void {
  const task = tasks.find((t) => t.id === taskId);
  if (!task || taskActive(task)) return;
  const first = resumeFrom(task.files.map((f) => f.status));
  if (first < 0) return;
  for (const f of task.files) {
    if (f.status === "canceled") setStatus(task, f, "pending");
  }
  task.canceled = false;
  // The cursor goes back to the first file that is pending again — everything
  // before it is done, errored, or was never cancelled at all.
  task.nextIdx = first;
  emit();
  void runTask(task);
}

/** Whether a task has cancelled files waiting to be picked up again. */
export function taskResumable(t: ImportTask): boolean {
  return t.canceled && !taskActive(t)
    && resumeFrom(t.files.map((f) => f.status)) >= 0;
}

/** Remove a finished task from the list (only when nothing is in flight). */
export function dismissImportTask(taskId: number): void {
  const task = tasks.find((t) => t.id === taskId);
  if (!task || taskActive(task)) return;
  tasks = tasks.filter((t) => t.id !== taskId);
  emit();
}
