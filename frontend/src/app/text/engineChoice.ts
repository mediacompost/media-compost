/**
 * Which reading of a page you are looking at, remembered per item.
 *
 * Two engines read one page two ways, and the choice between them is a
 * WORKING decision about that page — the manga engine for a chapter, the
 * multilingual one for a scan of a form. It has to be the same choice in all
 * three places that show a reading (the library sidebar, the annotator, the
 * editor's text tool), or switching windows silently switches engines, and
 * it has to survive a reload, or every trip back to a page starts on the
 * wrong one.
 *
 * In the BROWSER rather than on the item, `subjects/recent.ts`' reasoning:
 * this is personal working state, not a fact about the picture — a second
 * person reading the same library may well want the other engine. Bounded,
 * because it is keyed per item and a library has hundreds of thousands:
 * oldest choices fall off the end, and a forgotten one simply means the
 * first reading again, which is what a page nobody has chosen for shows.
 *
 * `pick`/`chosen` are pure over the stored map so the fallback rule can be
 * tested without storage.
 */
import { useSyncExternalStore } from "react";
import { storage } from "../../shared/storage.ts";

const KEY = "mc.textEngine";
/** Enough for a long session over a chapter or two; the tail is disposable. */
const MAX = 300;

type Choices = Record<string, string>;

// Handed out BY IDENTITY — `useSyncExternalStore` compares snapshots by
// reference, so parsing the JSON per call would re-render forever.
let cached: Choices | null = null;
const listeners = new Set<() => void>();

function load(): Choices {
  try {
    const raw = JSON.parse(storage.get(KEY) || "{}");
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    const out: Choices = {};
    for (const [k, v] of Object.entries(raw)) {
      if (typeof v === "string") out[k] = v;
    }
    return out;
  } catch {
    return {};
  }
}

export function readChoices(): Choices {
  if (cached === null) cached = load();
  return cached;
}

/** Remember the reading being looked at for this item. */
export function rememberEngine(itemId: number | null, model: string): void {
  if (itemId == null || !model) return;
  const cur = readChoices();
  if (cur[String(itemId)] === model) return;
  // Insertion order IS the age here: re-inserting the key moves it to the
  // end, so the oldest choices are the ones the cap drops.
  const next: Choices = { ...cur };
  delete next[String(itemId)];
  next[String(itemId)] = model;
  const keys = Object.keys(next);
  cached = keys.length <= MAX ? next
    : Object.fromEntries(keys.slice(keys.length - MAX).map((k) => [k, next[k]]));
  try {
    storage.set(KEY, JSON.stringify(cached));
  } catch {
    /* a full or disabled store just means no memory — never a failed read */
  }
  listeners.forEach((l) => l());
}

/** THE ONE FALLBACK RULE, pure: what was chosen for this item if that engine
 *  still has a reading, else the first engine there is (else ""). Every
 *  window resolves it the same way, which is what stops the list and the
 *  boxes beside it disagreeing about which reading is on show. */
export function chosen(choices: Choices, itemId: number | null,
                      engines: string[]): string {
  const want = itemId == null ? "" : choices[String(itemId)] ?? "";
  return want && engines.includes(want) ? want : (engines[0] ?? "");
}

const EMPTY: Choices = {};

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

/** The remembered choice for this item, live — resolved against the engines
 *  that actually have a reading. */
export function useChosenEngine(itemId: number | null,
                                engines: string[]): string {
  const choices = useSyncExternalStore(subscribe, readChoices, () => EMPTY);
  return chosen(choices, itemId, engines);
}
