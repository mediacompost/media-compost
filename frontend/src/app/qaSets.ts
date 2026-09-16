/** Quick-Assign tag sets: the data and the rules, with no React in them.
 *
 * A set is a positive and a negative tag list, plus an OPTIONAL number 1–9 —
 * the key that stamps it from the Q overlay. Numbers are identities: a set
 * keeps its number until somebody changes it, deleting a set frees its
 * number, and there may be any number of sets while only nine of them can
 * carry a key. Everything that has to be exactly right — the number exchange,
 * the match colours, the localStorage decode — lives here so `node --test`
 * can state it as tests rather than as prose.
 */
import type { TagAssignment } from "./api.ts";

export interface QaSet {
  /** Client-local identity — the React key that keeps a row THE SAME ROW
   *  while renumbering re-sorts the list (that is what lets the move
   *  animate, and what keeps an open add-field from remounting). Minted
   *  fresh per session (`newQaSet`), never persisted. */
  id: number;
  pos: string[];
  neg: string[];
  /** GROUP memberships the set stamps beside its tags (group ids). */
  groups: number[];
  /** The number key that stamps this set from the overlay, or null for none.
   *  Unique across the list while set. */
  num: number | null;
}

let nextId = 1;

export function newQaSet(num: number | null): QaSet {
  return { id: nextId++, pos: [], neg: [], groups: [], num };
}

/** The drawer's (and storage's) invariant order: numbered sets ascending,
 *  unnumbered after them, ties keeping their relative order (numbers are
 *  unique, so only the unnumbered tail has any). */
export function sortSets(sets: QaSet[]): QaSet[] {
  return [...sets].sort((a, b) => {
    if (a.num == null && b.num == null) return 0;
    if (a.num == null) return 1;
    if (b.num == null) return -1;
    return a.num - b.num;
  });
}

/** How many sets can carry a number: the digit keys there are. */
export const QA_NUM_MAX = 9;

/** Above this many selected items the per-item aggregations (match colours,
 *  the sidebar's tag/group/sequence rollups) are skipped as too slow. */
export const HEAVY_SELECTION = 200;

export function setIsEmpty(s: QaSet): boolean {
  return s.pos.length === 0 && s.neg.length === 0 && s.groups.length === 0;
}

/** The lowest number 1–QA_NUM_MAX no set carries, or null when all are taken. */
export function lowestFreeNumber(sets: QaSet[]): number | null {
  const used = new Set(sets.map((s) => s.num));
  for (let n = 1; n <= QA_NUM_MAX; n++) if (!used.has(n)) return n;
  return null;
}

/** The overlay's view: the sets that carry a number, in number order. */
export function numberedSets(sets: QaSet[]): QaSet[] {
  return sets
    .filter((s) => s.num != null)
    .sort((a, b) => (a.num as number) - (b.num as number));
}

/**
 * Give the set at `index` the number `num` (or none). A number another set
 * already carries is EXCHANGED — that set inherits this one's old number,
 * possibly becoming unnumbered — so the invariant "a number names at most one
 * set" holds without anything ever being refused. Returns the input array
 * unchanged (same identity) when there is nothing to do.
 */
export function assignNumber(
  sets: QaSet[],
  index: number,
  num: number | null
): QaSet[] {
  const cur = sets[index];
  if (!cur) return sets;
  if (num != null && (!Number.isInteger(num) || num < 1 || num > QA_NUM_MAX)) {
    return sets;
  }
  if (cur.num === num) return sets;
  const next = sets.map((s) => ({ ...s }));
  if (num != null) {
    const other = next.findIndex((s, i) => i !== index && s.num === num);
    if (other >= 0) next[other].num = cur.num;
  }
  next[index].num = num;
  return next;
}

/** True when the item carries every one of the set's tags directly and with
 *  the right sign (positives assigned, negatives marked negative). Empty tag
 *  lists are vacuously satisfied — callers guard with `setIsEmpty`. */
export function itemHasAllQaTags(
  directTags: TagAssignment[],
  qaPos: string[],
  qaNeg: string[],
  // The set's groups against the item's memberships — both optional so the
  // tag-only callers stay exactly what they were.
  qaGroups: number[] = [],
  groupIds: number[] = [],
): boolean {
  const pos = new Set(directTags.filter((t) => !t.negative).map((t) => t.name));
  const neg = new Set(directTags.filter((t) => t.negative).map((t) => t.name));
  const inGroups = new Set(groupIds);
  return qaPos.every((t) => pos.has(t)) && qaNeg.every((t) => neg.has(t))
    && qaGroups.every((g) => inGroups.has(g));
}

/** True when the item carries ANY of the set's tags with the right sign. */
export function itemHasAnyQaTag(
  directTags: TagAssignment[],
  qaPos: string[],
  qaNeg: string[],
  qaGroups: number[] = [],
  groupIds: number[] = [],
): boolean {
  const pos = new Set(directTags.filter((t) => !t.negative).map((t) => t.name));
  const neg = new Set(directTags.filter((t) => t.negative).map((t) => t.name));
  const inGroups = new Set(groupIds);
  return qaPos.some((t) => pos.has(t)) || qaNeg.some((t) => neg.has(t))
    || qaGroups.some((g) => inGroups.has(g));
}

/**
 * How a set relates to a selection: "full" when EVERY item carries the whole
 * set (the press would remove it), "partial" when some item carries some of
 * it, "none" otherwise.
 *
 * An EMPTY set is "none", never "full" — `itemHasAllQaTags` is vacuously true
 * over an empty set, and a green row promising a removal that would remove
 * nothing is a lie. An item whose page is not loaded arrives as `[]` and so
 * counts as non-matching, exactly as the drawer's all-selected-have check
 * always treated it.
 */
export function qaSetMatch(
  perItemDirect: TagAssignment[][],
  set: QaSet,
  // Each item's group memberships, aligned with `perItemDirect` — omitted
  // by callers that predate groups in sets, whose sets then match by tags
  // alone exactly as before.
  perItemGroups: number[][] = [],
): "full" | "partial" | "none" {
  if (setIsEmpty(set) || perItemDirect.length === 0) return "none";
  const gids = perItemGroups.length ? set.groups : [];
  const gOf = (i: number) => perItemGroups[i] ?? [];
  if (perItemDirect.every((dt, i) =>
      itemHasAllQaTags(dt, set.pos, set.neg, gids, gOf(i)))) {
    return "full";
  }
  if (perItemDirect.some((dt, i) =>
      itemHasAnyQaTag(dt, set.pos, set.neg, gids, gOf(i)))) {
    return "partial";
  }
  return "none";
}

/**
 * The set's tags EVERY item already carries with the right sign, keyed
 * "+name" / "-name". On a partially-matching overlay row these are the chips
 * greyed out — the press will only add what is left. An empty selection
 * answers empty.
 */
export function qaSetDone(
  perItemDirect: TagAssignment[][],
  set: QaSet
): Set<string> {
  const out = new Set<string>();
  if (perItemDirect.length === 0) return out;
  const per = perItemDirect.map((dt) => ({
    pos: new Set(dt.filter((t) => !t.negative).map((t) => t.name)),
    neg: new Set(dt.filter((t) => t.negative).map((t) => t.name)),
  }));
  for (const n of set.pos) if (per.every((p) => p.pos.has(n))) out.add("+" + n);
  for (const n of set.neg) if (per.every((p) => p.neg.has(n))) out.add("-" + n);
  return out;
}

/** The default a library starts with: one empty set on key 1. THERE IS ALWAYS
 *  AT LEAST ONE SET — the drawer edits sets in place, so an empty list would
 *  be a drawer with nothing to type into. */
function defaultSets(): QaSet[] {
  return [newQaSet(1)];
}

/** One tag list off an untrusted decode: strings only, deduped, minus any
 *  name already claimed (a name may not be positive and negative at once). */
function cleanTags(raw: unknown, taken: Set<string>): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const v of raw) {
    if (typeof v !== "string" || !v || taken.has(v)) continue;
    taken.add(v);
    out.push(v);
  }
  return out;
}

/**
 * Decode the persisted sets, tolerating garbage: bad JSON, a non-array, or a
 * malformed entry each degrade rather than throw (localStorage is writable by
 * anything, and a set list that crashes the store on load locks the whole app
 * out). Duplicate numbers keep their first carrier; the result is never empty.
 */
export function parseQaSets(raw: string | null): QaSet[] {
  if (!raw) return defaultSets();
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return defaultSets();
  }
  if (!Array.isArray(data)) return defaultSets();
  const out: QaSet[] = [];
  const usedNums = new Set<number>();
  for (const e of data) {
    if (typeof e !== "object" || e === null) continue;
    const o = e as { pos?: unknown; neg?: unknown; num?: unknown;
                     groups?: unknown };
    const taken = new Set<string>();
    const pos = cleanTags(o.pos, taken);
    const neg = cleanTags(o.neg, taken);
    const groups = Array.isArray(o.groups)
      ? [...new Set(o.groups.filter(
          (g): g is number => typeof g === "number" && Number.isInteger(g)))]
      : [];
    let num: number | null =
      typeof o.num === "number" && Number.isInteger(o.num) &&
      o.num >= 1 && o.num <= QA_NUM_MAX
        ? o.num
        : null;
    if (num != null && usedNums.has(num)) num = null;
    if (num != null) usedNums.add(num);
    out.push({ ...newQaSet(num), pos, neg, groups });
  }
  // The invariant order, restored on load — older storage may predate it.
  return out.length ? sortSets(out) : defaultSets();
}

/** The `id` is session-local and deliberately not written: persisted ids
 *  would collide with the counter of the session that reads them back. */
export function serializeQaSets(sets: QaSet[]): string {
  return JSON.stringify(sets, (k, v) => (k === "id" ? undefined : v));
}
