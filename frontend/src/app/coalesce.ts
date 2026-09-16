// Pure trailing-debounce with a max wait, used to coalesce query-invalidation
// storms (imports finishing in batches, job completions, broadcast messages)
// into one refetch burst. No React, no query client — unit-tested under
// `node --test` with injected timers.

export interface CoalesceOpts {
  /** Quiet period: fire this long after the LAST call of a burst. */
  wait: number;
  /** Upper bound: during continuous calls, fire at least this often. */
  maxWait: number;
}

/** Injectable clock, so tests can drive time deterministically. */
export interface CoalesceTimers {
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (id: unknown) => void;
  now: () => number;
}

export interface Coalescer {
  /** Register one occurrence; `fn` fires after the burst settles. */
  call: () => void;
  /** Drop any pending fire without running it. */
  cancel: () => void;
  /** Run a pending fire immediately (no-op when nothing is pending). */
  flush: () => void;
}

export function makeCoalescer(
  fn: () => void,
  opts: CoalesceOpts,
  timers?: Partial<CoalesceTimers>
): Coalescer {
  const t: CoalesceTimers = {
    setTimeout: timers?.setTimeout ?? ((f, ms) => setTimeout(f, ms)),
    clearTimeout: timers?.clearTimeout ?? ((id) => clearTimeout(id as ReturnType<typeof setTimeout>)),
    now: timers?.now ?? Date.now,
  };

  let timer: unknown = null;
  // When the current burst began — the max-wait deadline is measured from here
  // and survives every re-arm, or continuous calls would postpone it forever.
  let burstStart: number | null = null;

  const fire = () => {
    if (timer != null) {
      t.clearTimeout(timer);
      timer = null;
    }
    burstStart = null;
    fn();
  };

  const call = () => {
    const now = t.now();
    if (burstStart == null) burstStart = now;
    const untilDeadline = Math.max(0, opts.maxWait - (now - burstStart));
    const delay = Math.min(opts.wait, untilDeadline);
    if (timer != null) t.clearTimeout(timer);
    timer = t.setTimeout(fire, delay);
  };

  const cancel = () => {
    if (timer != null) {
      t.clearTimeout(timer);
      timer = null;
    }
    burstStart = null;
  };

  const flush = () => {
    if (timer != null) fire();
  };

  return { call, cancel, flush };
}
