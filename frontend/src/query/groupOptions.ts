/**
 * THE GROUP DROPDOWN'S ROWS — the tree, said in one line each.
 *
 * The list was flat and alphabetical: every group in the library as a bare
 * name, with nothing saying which of the three "2024" rows was which, and no
 * way to pick one of them. The rows are in TREE order and carry their
 * ancestors as a hint, so the list reads like the sidebar rather than like a
 * dictionary — and what a row COMMITS is the group's FULL PATH from the root
 * (owner 2026-09): `Trips/2024`, never a bare `2024`, because a group is
 * identified by its whole path (`media_compost.grouppath`) and a bare name
 * is the root-level group of that name and nothing else.
 *
 * Pure, so the cases are tests rather than prose.
 */
export interface GroupTreeNode {
  name: string;
  children?: GroupTreeNode[];
}

export interface GroupOptionRow {
  /** What picking the row puts in the condition. */
  name: string;
  /** The ancestors, for reading — "" for a root. */
  hint?: string;
}

const SEP = "/";

/** Every group as `{path}`, depth-first — the sidebar's own order. */
function walk(nodes: GroupTreeNode[], prefix: string[]): string[][] {
  const out: string[][] = [];
  for (const g of nodes ?? []) {
    const path = [...prefix, g.name];
    out.push(path);
    out.push(...walk(g.children ?? [], path));
  }
  return out;
}

export function groupOptions(tree: GroupTreeNode[]): GroupOptionRow[] {
  return walk(tree ?? [], []).map((path) => ({
    name: path.join(SEP),
    // The ancestors ALWAYS, not only where they disambiguate: the hint is
    // what makes the list read as a tree, and a hint that came and went
    // per row would be harder to read than none.
    hint: path.length > 1 ? path.slice(0, -1).join(" › ") : "",
  }));
}
