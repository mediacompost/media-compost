// Run with: npm test (Node's built-in runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import { chunks, runBulk } from "./bulk.ts";

test("processes every item, chunked, in order across chunks", async () => {
  const started: number[][] = [];
  let current: number[] = [];
  const res = await runBulk(
    [0, 1, 2, 3, 4, 5, 6],
    async (n) => {
      current.push(n);
      // Yield so a whole chunk gathers before the next starts.
      await Promise.resolve();
    },
    {
      chunk: 3,
      onProgress: () => { started.push(current); current = []; },
    },
  );
  assert.deepEqual(res, { done: 7, aborted: false });
  assert.deepEqual(started, [[0, 1, 2], [3, 4, 5], [6]]);
});

test("reports progress at chunk boundaries", async () => {
  const ticks: [number, number][] = [];
  await runBulk([1, 2, 3, 4, 5], async () => {}, {
    chunk: 2,
    onProgress: (done, total) => ticks.push([done, total]),
  });
  assert.deepEqual(ticks, [[2, 5], [4, 5], [5, 5]]);
});

test("chunk defaults keep a bare call working", async () => {
  let calls = 0;
  const res = await runBulk([1, 2, 3], async () => { calls++; });
  assert.equal(calls, 3);
  assert.deepEqual(res, { done: 3, aborted: false });
});

test("an abort mid-run stops between chunks", async () => {
  const ctrl = new AbortController();
  const ran: number[] = [];
  const res = await runBulk(
    [0, 1, 2, 3, 4, 5],
    async (n) => {
      ran.push(n);
      if (n === 1) ctrl.abort(); // during the first chunk
    },
    { chunk: 2, signal: ctrl.signal },
  );
  // The in-flight chunk finished; nothing further started.
  assert.deepEqual(ran, [0, 1]);
  assert.deepEqual(res, { done: 2, aborted: true });
});

test("an already-aborted signal runs nothing", async () => {
  const ctrl = new AbortController();
  ctrl.abort();
  let calls = 0;
  const res = await runBulk([1, 2], async () => { calls++; }, { signal: ctrl.signal });
  assert.equal(calls, 0);
  assert.deepEqual(res, { done: 0, aborted: true });
});

test("empty input resolves immediately with no progress ticks", async () => {
  const ticks: number[] = [];
  const res = await runBulk([], async () => {}, { onProgress: (d) => ticks.push(d) });
  assert.deepEqual(res, { done: 0, aborted: false });
  assert.deepEqual(ticks, []);
});

test("chunks splits into runs of at most size, keeping order", () => {
  assert.deepEqual(chunks([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
  assert.deepEqual(chunks([1, 2], 5), [[1, 2]]);
  assert.deepEqual(chunks([], 3), []);
  // A nonsense size still makes progress rather than looping.
  assert.deepEqual(chunks([1, 2], 0), [[1], [2]]);
});

test("a rejection propagates", async () => {
  await assert.rejects(
    runBulk([1, 2, 3], async (n) => {
      if (n === 2) throw new Error("boom");
    }, { chunk: 1 }),
    /boom/,
  );
});
