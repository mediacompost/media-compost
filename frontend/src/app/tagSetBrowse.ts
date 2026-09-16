/** BROWSING the enabled tag sets from an EMPTY tag field — the pure half.
 *
 *  Typing narrows a flat ranked list; an empty, focused field has nothing
 *  to narrow and used to show nothing. It shows the sets' CATEGORY TREES
 *  instead: which sets there are (skipped when there is only one), then a
 *  set's categories with their entry counts, then a category's own tags —
 *  children FIRST, then the category's direct entries. → opens a row, ←
 *  goes up, Enter on a tag assigns it. A breadcrumb says where you are.
 *  Categories are a browsing aid and nothing more.
 *
 *  Pure over the tree the server sends (`/api/tag-sets/tree`, flat category
 *  rows with `parent_id`) plus the entries fetched for the cursor's node, so
 *  the whole answer space is a test. Cycles and orphans are `treeRows.ts`'
 *  problem, whose rules this reuses. */

import type { TagSetTreeCategory, TagSetTreeSet } from "./api";
import type { TagSuggestion } from "./components/TagAutocomplete";
import { ancestorsOf } from "./treeRows.ts";

/** Where the browser is: `null` is the top level (the history, the groups
 *  and the sets); a set with no category is the set's root (its top-level
 *  categories, then its loose entries); a `groupId` is one library group's
 *  page — itself, then the groups inside it. */
export type BrowseCursor =
  | { setId: number; categoryId: number | null; groupId?: undefined }
  | { groupId: number; setId?: undefined; categoryId?: undefined }
  | null;

/** A library group as the browser needs it: the flattened tree
 *  (`GroupSelect.flattenGroupTree`), which is where `parent` and the item
 *  `count` come from. */
export interface BrowseGroup {
  id: number;
  name: string;
  /** Its parent in the group tree, `null` at the top level. */
  parent?: number | null;
  depth?: number;
  trail?: string[];
  /** How many items are in it — what the row shows, the way a category's
   *  entry count does. */
  count?: number;
}

export type BrowseRow =
  /** The way OUT, first at the browser's top level and nowhere else — the
   *  T overlay's: the tree opens by itself over an empty line and holds
   *  Enter while it is up, so with this row under the default highlight
   *  Enter closes the tree and the next Enter is the overlay's own. Its
   *  `name` is empty so a host's row keys and the highlight identity still
   *  read off `name` unchanged. */
  | { kind: "close"; name: "" }
  /** A SECTION HEADING, and nothing else: the keyboard steps over it and
   *  the mouse cannot commit it (`TagSuggestList`'s `selectable`). Drawn
   *  only where two sections meet — with a history to head, the sets need
   *  saying too. */
  | { kind: "title"; name: ""; section: "history" | "sets" | "groups" }
  /** A WHOLE LINE somebody applied before (`cat -dog !bird`), prefixes and
   *  all: the T overlay's history, offered over an EMPTY field where there
   *  is nothing to complete. It is not a tag and picking it writes the
   *  whole line, so it is its own kind rather than a tag row. */
  | { kind: "history"; name: string }
  /** A LIBRARY GROUP, offered where the host takes groups as well as tags
   *  (the tag batch's set editor). Not a tag and not in any set — its own
   *  section over an empty field, beside the history and the sets. `depth`
   *  is how deep in the group TREE it sits, so the list can show the
   *  hierarchy the way every other group picker does. */
  | { kind: "group"; name: string; id: number; depth: number;
      /** Its ancestors, outermost first — empty at the top level. A host
       *  draws EITHER this or the indent: the tag batch's list nests, the
       *  quick assign drawer's spells the path out behind the name. */
      trail: string[];
      /** Something is inside it, so → opens its page. A group with none is
       *  a leaf and Enter is all it does. */
      kids: boolean;
      /** How many items are in it. */
      count: number;
      /** THIS PAGE'S OWN GROUP, drawn first inside it. A group that holds
       *  others is still a group somebody may want, and a page that only
       *  listed the children would have made it unreachable. */
      self: boolean }
  | { kind: "set"; name: string; set: TagSetTreeSet }
  | { kind: "category"; name: string; setId: number; cat: TagSetTreeCategory;
      /** How many entries sit in it and in its children — what the row shows. */
      count: number; kids: boolean }
  | { kind: "tag"; name: string; item: TagSuggestion };

/** The cursor a fresh browse starts at: one enabled set is entered
 *  directly (a list of one is a step for nothing). */
export function startCursor(sets: readonly TagSetTreeSet[]): BrowseCursor {
  return sets.length === 1 ? { setId: sets[0].id, categoryId: null } : null;
}

function subtreeCount(cats: readonly TagSetTreeCategory[], root: number): number {
  const byParent = new Map<number | null, TagSetTreeCategory[]>();
  for (const c of cats) {
    const list = byParent.get(c.parent_id) ?? [];
    list.push(c);
    byParent.set(c.parent_id, list);
  }
  let total = 0;
  const seen = new Set<number>();
  const walk = (id: number) => {
    if (seen.has(id)) return;
    seen.add(id);
    const me = cats.find((c) => c.id === id);
    if (me) total += me.entries;
    for (const k of byParent.get(id) ?? []) walk(k.id);
  };
  walk(root);
  return total;
}

/** The rows for `cursor`: the sets at the root; inside a set, the cursor
 *  node's CHILD categories (siblings in `position` order) first, then the
 *  node's own entries (already fetched by the caller, as suggestions). */
export function browseRows(
  sets: readonly TagSetTreeSet[], cursor: BrowseCursor,
  entries: readonly TagSuggestion[],
  /** Lead with a Close row at the top level — where ← has nowhere left to
   *  go (`upFrom` is `undefined`): the set list, or a lone set's root. */
  closeRow = false,
  /** The lines applied before, newest first, under the Close row and above
   *  the sets — the TOP LEVEL only, for the same reason the Close row is
   *  there: it is the list an empty field opens on, and inside a category
   *  the rows are that category's. Empty everywhere else, which is also
   *  what leaves the section titles off. */
  history: readonly string[] = [],
  /** LIBRARY GROUPS the host will take, in the tree's own order — the TOP
   *  LEVEL only, for the same reason the history is: inside a category the
   *  rows are that category's. */
  groups: readonly BrowseGroup[] = [],
): BrowseRow[] {
  // What the CURSOR holds — the sets, or a node's categories and tags. Built
  // first, because whether there is a "Tag sets" heading to draw is whether
  // there is anything under it: a library with no set enabled still has a
  // history to offer.
  const body: BrowseRow[] = [];
  if (cursor != null && cursor.groupId != null) {
    // ONE GROUP'S PAGE: the group ITSELF first, then what is inside it —
    // the tag-set categories' shape, and for their reason. A tree drawn
    // flat with indents is unreadable past a screenful and unbrowsable on
    // a page of ten rows, and a page that listed only the children would
    // have made every parent unpickable.
    const me = groups.find((g) => g.id === cursor.groupId);
    if (!me) return [];
    body.push(groupRow(me, groups, true));
    for (const g of groups.filter((g) => (g.parent ?? null) === me.id)) {
      // NO PATH ON A PAGE: the breadcrumb above the list already says where
      // these are, and a host that spells the trail out would print it on
      // every row. It is the TOP level that needs it, where an orphan's
      // ancestors are not on screen at all.
      body.push({ ...groupRow(g, groups, false), trail: [] } as BrowseRow);
    }
    return body;
  }
  if (cursor == null) {
    for (const set of sets) body.push({ kind: "set", name: set.name, set });
  } else {
    const set = sets.find((s) => s.id === cursor.setId);
    if (!set) return [];
    const cats = set.categories;
    const kids = cats
      .filter((c) => (c.parent_id ?? null) === cursor.categoryId)
      .sort((a, b) => a.position - b.position || a.id - b.id);
    for (const cat of kids) body.push({
      kind: "category", name: cat.name, setId: set.id, cat,
      count: subtreeCount(cats, cat.id),
      kids: cats.some((c) => c.parent_id === cat.id),
    });
    for (const item of entries) body.push({ kind: "tag", name: item.name, item });
  }
  const rows: BrowseRow[] = [];
  const top = upFrom(sets, cursor) === undefined;
  if (closeRow && top) rows.push({ kind: "close", name: "" });
  if (top && history.length) {
    rows.push({ kind: "title", name: "", section: "history" });
    for (const line of history) rows.push({ kind: "history", name: line });
  }
  // THE ROOT GROUPS AND ONLY THOSE. What is inside one is one press away
  // (its own page, with the way back), which is what the tag sets' own
  // categories do — a library with a hundred groups four deep made this
  // list a hundred rows long, of which the ten that matter were at the top.
  const roots = groups.filter((g) => isRoot(g, groups));
  if (top && roots.length) {
    rows.push({ kind: "title", name: "", section: "groups" });
    for (const g of roots) rows.push(groupRow(g, groups, false));
  }
  // THE SETS' OWN HEADING, at the top level and only there — the breadcrumb
  // bar above the list is hidden until you have gone INTO a set (where it
  // carries the way back), so at the top the heading is what says whose
  // rows these are. Nothing to head, no heading.
  if (top && body.length) rows.push({ kind: "title", name: "", section: "sets" });
  rows.push(...body);
  return rows;
}

/** AN ORPHAN IS A ROOT. The hosts hand over the groups still worth
 *  offering — the tag grid leaves out the ones already picked — so a parent
 *  can be missing from a list its children are in, and a child nothing
 *  lists as a root and no page holds would simply not be reachable. */
function isRoot(g: BrowseGroup, all: readonly BrowseGroup[]): boolean {
  const p = g.parent ?? null;
  return p === null || !all.some((x) => x.id === p);
}

function groupRow(g: BrowseGroup, all: readonly BrowseGroup[],
                  self: boolean): BrowseRow {
  return {
    kind: "group", name: g.name, id: g.id, depth: g.depth ?? 0,
    trail: g.trail ?? [], count: g.count ?? 0, self,
    // A group's own page never offers to open it AGAIN, however many
    // children it has: that is the page you are on.
    kids: !self && all.some((x) => (x.parent ?? null) === g.id),
  };
}

/** The path from the set down to the cursor's node, for the breadcrumb.
 *  Empty at the root. */
export function breadcrumb(sets: readonly TagSetTreeSet[], cursor: BrowseCursor,
                           groups: readonly BrowseGroup[] = []): string[] {
  if (cursor == null) return [];
  if (cursor.groupId != null) {
    const me = groups.find((g) => g.id === cursor.groupId);
    return me ? [...(me.trail ?? []), me.name] : [];
  }
  const set = sets.find((s) => s.id === cursor.setId);
  if (!set) return [];
  const out = [set.name];
  if (cursor.categoryId != null) {
    const up = ancestorsOf(set.categories, cursor.categoryId).reverse();
    for (const id of [...up, cursor.categoryId]) {
      const c = set.categories.find((x) => x.id === id);
      if (c) out.push(c.name);
    }
  }
  return out;
}

/** Where → (or Enter on a set / category) goes. Every other row — a tag,
 *  a history line, the Close row, a title — opens nothing. */
export function openRow(row: BrowseRow): BrowseCursor | null {
  if (row.kind === "set") return { setId: row.set.id, categoryId: null };
  if (row.kind === "category") return { setId: row.setId, categoryId: row.cat.id };
  // A group with nothing inside it opens nothing: Enter assigns it, which
  // is all a leaf can mean.
  if (row.kind === "group" && row.kids) return { groupId: row.id };
  return null;
}

/** Where ← goes: the parent category, the set's root, the set list — or
 *  `undefined` when already at the top of everything this browser shows
 *  (the root, or a lone set's root). */
export function upFrom(
  sets: readonly TagSetTreeSet[], cursor: BrowseCursor,
  groups: readonly BrowseGroup[] = [],
): BrowseCursor | undefined {
  if (cursor == null) return undefined;
  if (cursor.groupId != null) {
    const me = groups.find((g) => g.id === cursor.groupId);
    if (!me || isRoot(me, groups)) return null;
    return { groupId: me.parent as number };
  }
  const set = sets.find((s) => s.id === cursor.setId);
  if (cursor.categoryId == null) {
    return sets.length === 1 ? undefined : null;
  }
  const cat = set?.categories.find((c) => c.id === cursor.categoryId);
  const parent = cat?.parent_id ?? null;
  return { setId: cursor.setId, categoryId: parent };
}
