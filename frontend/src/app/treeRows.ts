/**
 * A LIST OF PARENTED ROWS, READ AS A TREE — flattened back into a list.
 *
 * The places and events lists are windowed (only the rows on screen exist),
 * their selection is a flat set of keys, and their sort is a column heading —
 * none of which a nested render survives. So the tree is flattened HERE, into
 * exactly the rows the list would have had, each carrying its depth and
 * whether it can be opened. Everything downstream stays a list.
 *
 * Pure, so `node --test` covers the cases that matter and the two lists share
 * one answer: the orphan (a parent that was filtered out, or deleted), the
 * cycle (which the API refuses but a file could still restore), and the order
 * (siblings by the list's own sort, children under their parent).
 */

export interface TreeRow {
  id: number;
  parent_id?: number | null;
}

export interface Flat<T> {
  row: T;
  depth: number;
  /** Has children AMONG THE ROWS GIVEN — a place whose only child was
   *  filtered out has no chevron, because there is nothing to open. */
  kids: boolean;
}

/**
 * @param rows      In the order siblings should appear (the list's own sort).
 * @param collapsed Ids whose children are hidden.
 */
export function flattenTree<T extends TreeRow>(
  rows: readonly T[], collapsed: ReadonlySet<number> = new Set(),
): Flat<T>[] {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const kids = new Map<number, T[]>();
  const roots: T[] = [];
  for (const r of rows) {
    // A parent that is not in this list — filtered out, or gone — makes its
    // child a ROOT rather than hiding it. A row nobody can see is worse than
    // a row at the wrong depth.
    const up = r.parent_id != null ? byId.get(r.parent_id) : undefined;
    if (up && up.id !== r.id) {
      const list = kids.get(up.id);
      if (list) list.push(r);
      else kids.set(up.id, [r]);
    } else {
      roots.push(r);
    }
  }
  // Reachable from a root, COLLAPSE IGNORED: that is what tells a row hidden
  // under a closed parent (which must stay hidden) from a row cut off by a
  // cycle (which must still be listed).
  const reachable = new Set<number>();
  const reach = (row: T, depth: number) => {
    if (reachable.has(row.id) || depth > 32) return;
    reachable.add(row.id);
    for (const k of kids.get(row.id) ?? []) reach(k, depth + 1);
  };
  for (const r of roots) reach(r, 0);

  const out: Flat<T>[] = [];
  const seen = new Set<number>();
  const walk = (row: T, depth: number) => {
    // A CYCLE cannot be drawn and must not hang: the API refuses one, but a
    // restored folder or a hand-edited library can still hold it, and a list
    // that loops forever is worse than one that shows a row once.
    if (seen.has(row.id) || depth > 32) return;
    seen.add(row.id);
    const mine = kids.get(row.id) ?? [];
    out.push({ row, depth, kids: mine.length > 0 });
    if (collapsed.has(row.id)) return;
    for (const k of mine) walk(k, depth + 1);
  };
  for (const r of roots) walk(r, 0);
  // Anything a CYCLE kept out of the walk still belongs in the list — a row
  // nobody can reach is worse than a row at the wrong depth.
  for (const r of rows) {
    if (!reachable.has(r.id)) out.push({ row: r, depth: 0, kids: false });
  }
  return out;
}

/** Every id from `id` up to the root — what has to be OPEN for a row to be
 *  reachable. Used when the list jumps to a row somebody clicked elsewhere. */
export function ancestorsOf<T extends TreeRow>(
  rows: readonly T[], id: number,
): number[] {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const out: number[] = [];
  let at = byId.get(id);
  const seen = new Set<number>();
  while (at && at.parent_id != null && !seen.has(at.id)) {
    seen.add(at.id);
    const up = byId.get(at.parent_id);
    if (!up) break;
    out.push(up.id);
    at = up;
  }
  return out;
}
