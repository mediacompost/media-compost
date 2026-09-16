/** Past a thousand items a bulk edit is worth a question before a thousand
 *  writes; below that it just runs. One number for every section that asks. */
export const BIG_EDIT = 1000;

// Chunked bulk runner for "do this to N things" UI operations — pure logic,
// no React, unit-tested under `node --test`.
//
// Items are processed chunk by chunk: within a chunk `fn` runs concurrently
// (Promise.all), between chunks the abort signal is checked and progress is
// reported. Sequential behavior is chunk size 1. An abort stops BETWEEN
// chunks — whatever was in flight completes, nothing further starts.

export interface BulkOpts {
  /** Items per chunk (concurrency within a chunk). Default 25. */
  chunk?: number;
  /** Called after each chunk with how many items have completed. */
  onProgress?: (done: number, total: number) => void;
  /** Checked between chunks; an aborted signal stops the run. */
  signal?: AbortSignal;
}

export interface BulkResult {
  /** How many items completed. */
  done: number;
  /** True when the signal stopped the run before every item was processed. */
  aborted: boolean;
}

/** Split `items` into runs of at most `size` — for endpoints that take a
 *  BATCH per request rather than an item per request (feed the runs to
 *  `runBulk` with chunk 1 to keep the requests sequential). */
export function chunks<T>(items: readonly T[], size: number): T[][] {
  const n = Math.max(1, size);
  const out: T[][] = [];
  for (let at = 0; at < items.length; at += n) out.push(items.slice(at, at + n));
  return out;
}

export async function runBulk<T>(
  items: readonly T[],
  fn: (item: T, index: number) => Promise<unknown>,
  opts: BulkOpts = {},
): Promise<BulkResult> {
  const size = Math.max(1, opts.chunk ?? 25);
  let done = 0;
  for (let at = 0; at < items.length; at += size) {
    if (opts.signal?.aborted) return { done, aborted: true };
    const slice = items.slice(at, at + size);
    await Promise.all(slice.map((it, i) => fn(it, at + i)));
    done += slice.length;
    opts.onProgress?.(done, items.length);
  }
  return { done, aborted: false };
}
