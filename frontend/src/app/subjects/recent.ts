/**
 * Who you named last, first.
 *
 * Tagging a page of a comic is naming the same four people over and over, and
 * an alphabetical list makes that four arrow-keys-and-a-look every time. The
 * order that actually helps is the one nobody can compute from the library:
 * what THIS person did a moment ago.
 *
 * It is therefore stored in the browser rather than on the item — recency is
 * personal working state, like the saved searches and UI preferences, not a
 * fact about the picture. `localStorage` also means the annotator window (a
 * separate React app with its own store) shares it with the main window for
 * free, which a store slice would not.
 *
 * The sort is pure and exported separately so it can be tested without storage.
 */

import { useSyncExternalStore } from "react";
import { storage } from "../../shared/storage.ts";

const KEY = "mc.recentSubjects";
/** Long enough to cover a working session's cast, short enough to stay cheap. */
const MAX = 40;

// The list is cached and handed out by identity, because `useSyncExternalStore`
// compares snapshots by reference — parsing the JSON afresh each call would
// return a new array every time and re-render forever.
let cached: string[] | null = null;
const listeners = new Set<() => void>();

function load(): string[] {
  try {
    const raw = JSON.parse(storage.get(KEY) || "[]");
    return Array.isArray(raw) ? raw.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function readRecent(): string[] {
  if (cached === null) cached = load();
  return cached;
}

/** Record that a subject was just assigned. Newest first, no repeats. */
export function rememberSubject(name: string): void {
  const wanted = name.trim();
  if (!wanted) return;
  const low = wanted.toLowerCase();
  cached = [wanted, ...readRecent().filter((n) => n.toLowerCase() !== low)]
    .slice(0, MAX);
  try {
    storage.set(KEY, JSON.stringify(cached));
  } catch {
    /* a full or disabled store just means no recency — never a failed assign */
  }
  listeners.forEach((l) => l());
}

/**
 * The list, live. A component that only read it once would keep the order it
 * had when its suggestions were first built — which is exactly the order the
 * name just given was supposed to change.
 *
 * The `storage` event carries a name given in the OTHER window (the annotator
 * is its own React app), which is the whole reason this lives in the browser's store.
 */
export function useRecentSubjects(): string[] {
  return useSyncExternalStore(subscribe, readRecent, () => EMPTY);
}

const EMPTY: string[] = [];

function subscribe(l: () => void): () => void {
  listeners.add(l);
  if (listeners.size === 1 && typeof window !== "undefined") {
    window.addEventListener("storage", onStorage);
  }
  return () => {
    listeners.delete(l);
    if (listeners.size === 0 && typeof window !== "undefined") {
      window.removeEventListener("storage", onStorage);
    }
  };
}

function onStorage(e: StorageEvent): void {
  if (e.key !== null && e.key !== KEY) return;
  cached = load();
  listeners.forEach((l) => l());
}

/**
 * `list` reordered so the most recently used come first, in the order they were
 * used; everything else keeps the order it arrived in.
 *
 * Stable on purpose: the caller's order is usually the catalog's own (by name,
 * or by how many pictures use it), and that stays the answer for everyone the
 * user has not touched yet.
 */
export function byRecent<T extends { name: string }>(
  list: T[], recent: string[],
): T[] {
  const rank = new Map<string, number>();
  recent.forEach((n, i) => {
    const low = n.toLowerCase();
    if (!rank.has(low)) rank.set(low, i);
  });
  const seen = list.map((item, i) => ({ item, i }));
  seen.sort((a, b) => {
    const ra = rank.get(a.item.name.toLowerCase()) ?? Infinity;
    const rb = rank.get(b.item.name.toLowerCase()) ?? Infinity;
    return ra === rb ? a.i - b.i : ra - rb;
  });
  return seen.map((s) => s.item);
}

