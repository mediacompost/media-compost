// Debounce a changing value: the returned value trails `value` by `ms` of
// quiet. The source state stays instantly updated (a controlled input keeps
// every keystroke); only readers of the debounced copy wait out the burst.
import { useEffect, useState } from "react";

/** How long a TAG-NAME field waits before asking the server, given what has
 * been typed so far.
 *
 * One rule for all of them (the quick tag overlay, the shared autocomplete,
 * the query builder's tag token) — a field that felt different from the one
 * beside it would be one behaviour wearing two names.
 *
 * It was a flat 200 ms, chosen when a keystroke against a big catalog cost
 * 120–160 ms of SQL and the debounce was the cheap half of the wait.
 * `/api/tags/names` answers from an index now (its docstring has the
 * numbers), and what it costs depends on the FRAGMENT: a six-figure catalog
 * answers `blue_h` in ~2 ms and `b` in ~45, because one letter matches most
 * of the tag set. So the wait follows the same axis, in the direction
 * that is also right for reading:
 *
 * - **1–2 characters** keep the long wait. That list is the top few of tens
 *   of thousands of matches, so it is not what anybody is reading — they are
 *   still typing — and it is the expensive half to ask for.
 * - **3 or more** barely wait at all. That is where somebody is looking for
 *   a particular tag, the answer is milliseconds, and the wait IS the lag:
 *   at 200 ms the list was empty for most of the time between keystrokes,
 *   which is what "the autocomplete shows nothing" was.
 */
export function tagDebounceMs(fragment: string): number {
  return fragment.trim().length < 3 ? 220 : 60;
}

export function useDebouncedValue<T>(value: T, ms = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    if (Object.is(value, debounced)) return;
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
    // `debounced` is deliberately not a dependency beyond the equality guard:
    // re-arming on our own state write would double the timer churn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, ms]);
  return debounced;
}
