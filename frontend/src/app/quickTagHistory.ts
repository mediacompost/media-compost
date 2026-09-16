import { storage } from "../shared/storage.ts";
/** THE LAST FEW LINES THE T OVERLAY APPLIED — the pure half plus the one
 *  place they are stored.
 *
 *  The overlay's field takes a WHOLE edit as one line (`cat -dog !bird`),
 *  and the same edit is usually wanted again on the next picture: typing it
 *  a second time is the field's own grammar re-entered by hand. So the line
 *  is remembered as it was TYPED — prefixes and all, one entry per apply —
 *  and offered over an empty field, above the tag sets.
 *
 *  It is per browser and nothing else: `localStorage`, like every other
 *  per-viewer convenience here, and every read and write is wrapped because
 *  a private window throws on the accessor itself. */

/** How many lines are kept and offered. Five is what fits above the sets
 *  without the field's own list becoming a list of lists. */
export const QUICK_TAG_HISTORY_MAX = 5;

const KEY = "mc.quickTagHistory";

/** `line` in front, the rest after it, at most `max` — and the same line
 *  applied twice MOVES rather than repeating. A blank line is no entry. */
export function pushHistoryLine(
  history: readonly string[], line: string, max = QUICK_TAG_HISTORY_MAX,
): string[] {
  const l = line.trim();
  if (!l) return [...history].slice(0, max);
  return [l, ...history.filter((h) => h !== l)].slice(0, max);
}

export function readQuickTagHistory(): string[] {
  try {
    const raw = storage.get(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === "string")
      .slice(0, QUICK_TAG_HISTORY_MAX);
  } catch {
    return [];
  }
}

export function writeQuickTagHistory(history: readonly string[]): void {
  try {
    storage.set(KEY, JSON.stringify(history));
  } catch {
    /* a browser that refuses to store simply forgets */
  }
}
