// Namespace grouping for the Tags tab's Items list, pure so `node --test`
// can state its rules.
//
// Tags sharing a `<namespace>:` prefix group under a PARENT ROW — a
// view-level row representing the whole namespace, never an actual tag entry
// (the Places/Events tree presentation). FOLDING is the view's business:
// TagsView drops a collapsed group's children from what it renders, and this
// module keeps emitting the full structure. A parent appears once at least
// TWO tags share the prefix; a lone `costume:tiger` stays a plain row rather
// than gaining a one-child header.
//
// The list's column sort applies at both levels. Sorting by NAME, children
// order numeric-aware (`quality:2` before `quality:10`, `height:98cm` before
// `height:172cm`) and the parent sorts among the top-level rows by the
// namespace itself. Sorting by a COUNT column, each child sorts by its own
// count and the parent takes its place by the column's group TOTAL.

import type { TagRow } from "../shared/api.ts";
import { exactFirst } from "./exactFirst.ts";
import { tagCount, tagNamespace } from "./tags.ts";

export interface NamespaceRow {
  kind: "namespace";
  /** The namespace text — what the parent row shows. */
  name: string;
  rows: TagRow[];
  /** Column totals, for the parent's quiet aggregates and its sort value —
   *  keyed by COLUMN, whichever the tag set's are (`tagSetColumns.ts`).
   *  The library's three counts of pictures, or an imported set's pair. */
  numbers: Record<string, number>;
}

export type ItemsListEntry =
  /** `depth` is how far the row is INDENTED: 0 at the top level, 1 under a
   *  namespace parent — and one more than its target for an ALIAS, which is
   *  drawn under the name it spells the way a namespace's names are drawn
   *  under theirs. */
  | { kind: "tag"; row: TagRow; depth: number }
  | NamespaceRow;

/** ALIAS ROWS NESTED UNDER THE NAME THEY SPELL (owner 2026-09).
 *
 *  The server puts an alias directly beneath its target in every order —
 *  it carries no number and no place in a file of its own — and this is the
 *  other half of saying so: one indent past whatever the target sits at,
 *  the same shape a namespace's names have under their parent row. Where
 *  the target is not in the list (narrowed away, or absent), the alias
 *  stays where it is at its own depth: an indent under nothing reads as a
 *  child of the row above, which would be a different tag.
 */
export function nestAliases(entries: ItemsListEntry[]): ItemsListEntry[] {
  const kids = new Map<string, ItemsListEntry[]>();
  let any = false;
  for (const e of entries) {
    if (e.kind !== "tag" || !e.row.alias_of) continue;
    const key = e.row.alias_of.toLowerCase();
    (kids.get(key) ?? kids.set(key, []).get(key)!).push(e);
    any = true;
  }
  if (!any) return entries;
  const here = new Set(entries
    .filter((e): e is Extract<ItemsListEntry, { kind: "tag" }> =>
      e.kind === "tag" && !e.row.alias_of)
    .map((e) => e.row.name.toLowerCase()));
  for (const list of kids.values())
    list.sort((a, b) => numericCmp((a as { row: TagRow }).row.name,
                                   (b as { row: TagRow }).row.name));
  const out: ItemsListEntry[] = [];
  for (const e of entries) {
    if (e.kind === "tag" && e.row.alias_of) {
      // AN ORPHAN STAYS WHERE IT IS, at its own depth: its target was
      // narrowed away or is not a row of this tag set, and an indent
      // under nothing reads as a child of whatever ended up above it.
      if (!here.has(e.row.alias_of.toLowerCase())) out.push(e);
      continue;
    }
    out.push(e);
    if (e.kind !== "tag") continue;
    for (const kid of kids.get(e.row.name.toLowerCase()) ?? [])
      out.push({ ...(kid as Extract<ItemsListEntry, { kind: "tag" }>),
                 depth: e.depth + 1 });
  }
  return out;
}

/** Numeric-aware, case-insensitive — `quality:2` before `quality:10`.
 *
 *  A CACHED `Intl.Collator`, never `localeCompare` with options: passing an
 *  options object makes every single comparison rebuild the collation
 *  machinery, and this comparator runs O(n log n) times over a catalog that
 *  can be six figures. Measured on a 120,000-tag library, the whole
 *  `namespacedRows` pass fell from 4.6 s to a fraction of that in Chromium
 *  by this one change — identical order (verified element-for-element). */
const collator = new Intl.Collator(undefined,
                                   { numeric: true, sensitivity: "base" });
const numericCmp = (a: string, b: string) => collator.compare(a, b);

function total(rows: TagRow[], col: string): number {
  return rows.reduce((n, t) => n + tagCount(t, col), 0);
}

/**
 * The Items list's rows with namespace parents woven in.
 *
 * ``rows`` is the list as TagsView already filtered and sorted it; single
 * (un-namespaced or lone) rows keep exactly that relative order. Groups are
 * ordered among them by the active column — the namespace's name under a
 * name-ish sort, the group total under a count sort — and their children are
 * re-sorted inside per the rules above.
 */
export function namespacedRows(
  rows: TagRow[], sortKey: string, sortDir: "asc" | "desc",
  /** THE NUMERIC COLUMNS OF THE TAG SET being listed — what a parent
   *  totals, and which sort keys count as a number rather than a name. */
  columns: readonly string[] = ["positive", "implicit", "negative"],
  /** What was searched for, if anything. A row whose name is EXACTLY this
   *  leads the list, whatever the column sort — and a GROUP holding such a
   *  row leads with it, since a row hoisted out of its namespace parent
   *  would be drawn under whatever happened to be above it. Passed in
   *  because this module re-sorts what it is given: the server hoists the
   *  exact match to the front of the index, and the unit sort below threw
   *  that away, which is why searching `a` for the tag called `a` left it
   *  wherever its count put it. */
  exact = "",
): ItemsListEntry[] {
  const byNs = new Map<string, TagRow[]>();
  for (const t of rows) {
    const ns = tagNamespace(t.name);
    if (!ns) continue;
    const list = byNs.get(ns);
    if (list) list.push(t); else byNs.set(ns, [t]);
  }
  for (const [ns, list] of byNs) {
    if (list.length < 2) byNs.delete(ns);
  }
  if (byNs.size === 0) {
    return exactFirst(rows, exact, (r) => [r.name])
      .map((row) => ({ kind: "tag", row, depth: 0 }));
  }

  const dir = sortDir === "asc" ? 1 : -1;
  const isCount = columns.includes(sortKey);
  const count = (t: TagRow) => tagCount(t, sortKey);

  type Unit =
    | { one: TagRow; flat: number }
    | { ns: string; rows: TagRow[]; flat: number };
  const units: Unit[] = [];
  const seen = new Set<string>();
  rows.forEach((t, i) => {
    const ns = tagNamespace(t.name);
    if (ns && byNs.has(ns)) {
      if (!seen.has(ns)) {
        seen.add(ns);
        units.push({ ns, rows: byNs.get(ns)!, flat: i });
      }
      return;
    }
    units.push({ one: t, flat: i });
  });

  const label = (u: Unit) => ("one" in u ? u.one.name : u.ns);
  const value = (u: Unit) =>
    isCount ? ("one" in u ? count(u.one) : total(u.rows, sortKey)) : 0;
  if (sortKey === "name") {
    units.sort((a, b) => numericCmp(label(a), label(b)) * dir);
  } else if (isCount) {
    units.sort((a, b) => {
      const c = value(a) - value(b);
      return c !== 0 ? c * dir : numericCmp(label(a), label(b));
    });
  }
  // Any other column (comment): the flat order already sorted by it; units
  // keep their first-member positions.
  if (sortKey !== "name" && !isCount) {
    units.sort((a, b) => a.flat - b.flat);
  }
  // …and then the exact match, ahead of all of it. A group counts as a
  // match when one of its rows is one, so `subject:a` brings its group up
  // and leads it (below) rather than hiding inside a group sorted by count.
  const ordered = exactFirst(
    units, exact,
    (u) => ("one" in u ? [u.one.name] : [u.ns, ...u.rows.map((r) => r.name)]));

  const out: ItemsListEntry[] = [];
  for (const u of ordered) {
    if ("one" in u) {
      out.push({ kind: "tag", row: u.one, depth: 0 });
      continue;
    }
    let kids = [...u.rows];
    if (isCount) kids.sort((a, b) => (count(a) - count(b)) * dir
      || numericCmp(a.name, b.name));
    else kids.sort((a, b) => numericCmp(a.name, b.name));
    kids = exactFirst(kids, exact, (r) => [r.name]);
    out.push({
      kind: "namespace", name: u.ns, rows: kids,
      numbers: Object.fromEntries(columns.map((c) => [c, total(kids, c)])),
    });
    for (const row of kids) out.push({ kind: "tag", row, depth: 1 });
  }
  return out;
}
