// Run with: npm test. Property-style: random status/progress sequences over a
// simulated file list, with the OLD whole-list computation as the oracle — the
// counters must agree with it after every single step.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  countsOf, matchWarnings, newCounters, onProgressTick, onTransition, progressOf,
  resumeFrom,
} from "./importStats.ts";
import type { ImportCounters, ImportFileStatus } from "./importStats.ts";

interface SimFile { status: ImportFileStatus; progress: number }

// The pre-counter implementations, verbatim (importManager.ts before Stage 4).
const TERMINAL: ImportFileStatus[] = ["done", "error", "canceled"];
const isTerminal = (f: SimFile) => TERMINAL.includes(f.status);
function oracleProgress(files: SimFile[]): number {
  if (files.length === 0) return 1;
  const sum = files.reduce((a, f) => {
    if (isTerminal(f)) return a + 1;
    if (f.status === "processing") return a + 0.95;
    if (f.status === "uploading") return a + f.progress * 0.9;
    return a;
  }, 0);
  return sum / files.length;
}
function oracleCounts(files: SimFile[]) {
  let done = 0, error = 0, pending = 0;
  for (const f of files) {
    if (f.status === "done") done++;
    else if (f.status === "error") error++;
    else if (f.status !== "canceled") pending++;
  }
  return { done, error, pending, total: files.length };
}

// Deterministic PRNG so a failure reproduces.
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

// The transitions the import engine actually performs.
const NEXT: Record<ImportFileStatus, ImportFileStatus[]> = {
  pending: ["uploading", "canceled", "error"],
  uploading: ["processing", "error", "canceled"],
  processing: ["done", "error", "canceled"],
  done: [], error: [], canceled: [],
};

function step(files: SimFile[], c: ImportCounters, rand: () => number): void {
  const live = files.filter((f) => !isTerminal(f));
  if (live.length === 0) return;
  const f = live[Math.floor(rand() * live.length)];
  // Half the time an uploading file just ticks progress.
  if (f.status === "uploading" && rand() < 0.5) {
    const next = Math.min(1, f.progress + rand() * 0.5);
    onProgressTick(c, f.progress, next);
    f.progress = next;
    return;
  }
  const options = NEXT[f.status];
  const to = options[Math.floor(rand() * options.length)];
  onTransition(c, f.status, to, f.progress);
  f.status = to;
  if (to === "uploading") f.progress = 0;
  if (to === "processing") f.progress = 1;
}

test("counters agree with the whole-list oracle over random runs", () => {
  for (let seed = 1; seed <= 20; seed++) {
    const rand = rng(seed * 7919);
    const total = 1 + Math.floor(rand() * 40);
    const files: SimFile[] = Array.from(
      { length: total }, () => ({ status: "pending", progress: 0 }));
    const c = newCounters(total);
    for (let i = 0; i < 300; i++) {
      step(files, c, rand);
      const p = progressOf(c);
      const want = oracleProgress(files);
      assert.ok(Math.abs(p - want) < 1e-9,
        `seed ${seed} step ${i}: progress ${p} != ${want}`);
      assert.deepEqual(countsOf(c), oracleCounts(files),
        `seed ${seed} step ${i}: counts diverged`);
    }
  }
});

test("an empty task reads as complete", () => {
  const c = newCounters(0);
  assert.equal(progressOf(c), 1);
  assert.deepEqual(countsOf(c), { done: 0, error: 0, pending: 0, total: 0 });
});

test("a fully-done task reads 1.0 exactly", () => {
  const c = newCounters(3);
  for (let i = 0; i < 3; i++) {
    onTransition(c, "pending", "uploading", 0);
    onProgressTick(c, 0, 1);
    onTransition(c, "uploading", "processing", 1);
    onTransition(c, "processing", "done", 1);
  }
  assert.equal(progressOf(c), 1);
  assert.deepEqual(countsOf(c), { done: 3, error: 0, pending: 0, total: 3 });
});

test("a warning finds its file by suffix, then by basename", () => {
  const files = [{ rel: "chapter/page01.png" }, { rel: "page02.png" },
                 { rel: "other/page01.png" }];
  const got = matchWarnings(files, [
    ["chapter/page01.png", "hidden"],
    ["page02.png", "trashed"],
  ]);
  assert.equal(got.get(files[0]), "hidden");
  assert.equal(got.get(files[1]), "trashed");
  assert.equal(got.get(files[2]), undefined);
});

test("one name is claimed by one file, however many share a basename", () => {
  // Two folders holding `page01.png`, and the run reports both landings.
  const files = [{ rel: "a/page01.png" }, { rel: "b/page01.png" }];
  const got = matchWarnings(files, [["page01.png", "hidden"],
                                    ["page01.png", "trashed"]]);
  assert.equal(got.size, 2);
});

test("a stats blob with no warnings in it is not an error", () => {
  assert.equal(matchWarnings([{ rel: "a.png" }], undefined).size, 0);
  assert.equal(matchWarnings([{ rel: "a.png" }], 3).size, 0);
});

test("a resume picks up at the first CANCELLED file", () => {
  // Everything before it is settled: done stays done, which is what makes a
  // resume cheap — the run continues rather than starting again.
  assert.equal(resumeFrom(["done", "done", "canceled", "canceled"]), 2);
  // An ERROR is a different answer from a cancel: that file was read, handed
  // over and refused for a reason the row carries. It is not retried, and it
  // does not hold the cursor either.
  assert.equal(resumeFrom(["done", "error", "canceled"]), 2);
  assert.equal(resumeFrom(["done", "error"]), -1, "nothing to resume");
  assert.equal(resumeFrom([]), -1);
  // A task cancelled before anything went out resumes from the top.
  assert.equal(resumeFrom(["canceled", "canceled"]), 0);
});
