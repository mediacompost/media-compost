/** Immutable, path-addressed edits on a condition tree, for the visual builder.
 *  A path is the list of child indices from the root (e.g. [1, 0]). */
// Type-only, so `node --test` can strip it and this module stays testable
// without resolving tree.ts at runtime.
import type { Cond, Group, MetaType, Node, TagCond } from "./tree";

export type Path = number[];

const clone = <T>(x: T): T =>
  (typeof structuredClone === "function"
    ? structuredClone(x)
    : JSON.parse(JSON.stringify(x)));

/** The node at `path` (root when the path is empty). */
export function nodeAt(root: Group, path: Path): Node {
  let n: Node = root;
  for (const i of path) {
    if (n.type !== "group") throw new Error("bad path");
    n = n.children[i];
  }
  return n;
}

/** Replace the node at `path` with `fn(node)`, returning a new root. */
export function updateAt(root: Group, path: Path, fn: (n: Node) => Node): Group {
  if (path.length === 0) return fn(clone(root)) as Group;
  const r = clone(root);
  let parent = r as Group;
  for (let k = 0; k < path.length - 1; k++) parent = parent.children[path[k]] as Group;
  const i = path[path.length - 1];
  parent.children[i] = fn(parent.children[i]);
  return r;
}

/** Remove the node at `path` (clears the root's children for an empty path). */
export function removeAt(root: Group, path: Path): Group {
  const r = clone(root);
  if (path.length === 0) { r.children = []; return r; }
  let parent = r as Group;
  for (let k = 0; k < path.length - 1; k++) parent = parent.children[path[k]] as Group;
  parent.children.splice(path[path.length - 1], 1);
  return r;
}

/** Insert `node` as the sibling directly after `path`. */
export function insertAfter(root: Group, path: Path, node: Node): Group {
  const r = clone(root);
  if (path.length === 0) { r.children.push(node); return r; }
  let parent = r as Group;
  for (let k = 0; k < path.length - 1; k++) parent = parent.children[path[k]] as Group;
  parent.children.splice(path[path.length - 1] + 1, 0, node);
  return r;
}

/** Append `node` as the last child of the group at `path`. */
export function appendChild(root: Group, path: Path, node: Node): Group {
  return updateAt(root, path, (n) =>
    n.type === "group" ? { ...n, children: [...n.children, node] } : n
  ) as Group;
}

// ---- node factories --------------------------------------------------------

export const newTag = (): TagCond => ({ type: "tag", name: "", have: true, sign: "pos" });

/** What the builder's type dropdown offers. "instruction" is not a condition
 *  TYPE — it is a caption condition over the other list — but it is a different
 *  question to ask, so it gets its own entry rather than a second dropdown
 *  nested inside the first. */
export type CondKind = Cond["type"] | "instruction";

/** Which dropdown entry a condition IS (the inverse of `blankCond`). */
export function condKind(c: Cond): CondKind {
  return c.type === "caption" && c.caption_kind === "instruction"
    ? "instruction" : c.type;
}

/** A blank condition of the given kind, preserving nothing from the old one. */
export function blankCond(kind: CondKind, mtype: MetaType = "numeric"): Cond {
  if (kind === "tag") return newTag();
  if (kind === "link") return { type: "link", direction: "has", link_tags: [] };
  if (kind === "caption")
    return { type: "caption", mode: "has", caption_kind: "caption", caption_tags: [] };
  if (kind === "instruction")
    return { type: "caption", mode: "has", caption_kind: "instruction", caption_tags: [] };
  if (kind === "ingroup") return { type: "ingroup", name: "", mode: "has" };
  if (kind === "subject") return { type: "subject", name: "", have: true };
  if (kind === "place") return { type: "place", op: "~", value: "", have: true };
  if (kind === "event") return { type: "event", name: "", have: true };
  if (kind === "taken") return { type: "taken", have: true };
  // A blank similarity condition names no pivot yet, so it matches nothing
  // until one is picked. `tol` stays null — the library's own threshold —
  // rather than defaulting to a number the field would then have to explain.
  if (kind === "similar")
    return { type: "similar", by: "color", uid: "", tol: null, have: true };
  // A fresh value condition starts on `>=`, the metadata row's numeric
  // default — these ARE quantities, unlike the enum codes that start on `=`.
  if (kind === "value")
    return { type: "value", name: "", op: ">=", value: 0, unit: "",
             tol: 0.5, have: true };
  return { type: "meta", name: "", mtype, op: mtype === "text" ? "=" : ">=", value: "" };
}

/** A new group seeded with one blank condition of the given kind (so the group
 *  is non-empty and visible immediately). */
export const newGroup = (kind: CondKind = "tag"): Group => ({
  type: "group", op: "and", neg: false, children: [blankCond(kind)],
});

/** The root is implicitly an "All" (AND) group; wrap any other root shape so the
 *  top level is always AND and an OR/None root shows as a nested group. */
export function normalizeRoot(g: Group): Group {
  return g.op === "and" && !g.neg ? g : { type: "group", op: "and", neg: false, children: [g] };
}
