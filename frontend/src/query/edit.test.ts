// Path-addressed immutable tree edits — the visual builder's whole editing
// surface. The manual index walks and the clone are exactly the kind of code
// a path test pins down.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  appendChild, blankCond, insertAfter, newGroup, nodeAt, normalizeRoot,
  removeAt, updateAt,
} from "./edit.ts";
import type { Group, TagCond } from "./tree.ts";

const tag = (name: string): TagCond =>
  ({ type: "tag", name, have: true, sign: "pos" });
const group = (...children: Group["children"]): Group =>
  ({ type: "group", op: "and", neg: false, children });

// root = AND( a, OR(b, c) )
const root = (): Group => {
  const inner: Group = { type: "group", op: "or", neg: false,
    children: [tag("b"), tag("c")] };
  return group(tag("a"), inner);
};

test("nodeAt walks child indices; empty path is the root", () => {
  const r = root();
  assert.equal(nodeAt(r, []), r);
  assert.deepEqual(nodeAt(r, [0]), tag("a"));
  assert.deepEqual(nodeAt(r, [1, 1]), tag("c"));
  assert.throws(() => nodeAt(r, [0, 0]));  // a tag has no children
});

test("updateAt replaces the addressed node and nothing else", () => {
  const r = root();
  const out = updateAt(r, [1, 0], () => tag("B"));
  assert.deepEqual(nodeAt(out, [1, 0]), tag("B"));
  assert.deepEqual(nodeAt(out, [1, 1]), tag("c"));
  assert.deepEqual(nodeAt(r, [1, 0]), tag("b"), "the input tree is untouched");
});

test("updateAt on the empty path transforms the root itself", () => {
  const out = updateAt(root(), [], (n) => ({ ...(n as Group), op: "or" }));
  assert.equal(out.op, "or");
});

test("removeAt splices the child out; empty path clears the root", () => {
  const r = root();
  const out = removeAt(r, [1, 0]);
  assert.deepEqual((nodeAt(out, [1]) as Group).children, [tag("c")]);
  assert.equal(removeAt(r, []).children.length, 0);
  assert.equal(r.children.length, 2, "the input tree is untouched");
});

test("insertAfter puts the node right after its sibling; empty path appends", () => {
  const r = root();
  const out = insertAfter(r, [0], tag("x"));
  assert.deepEqual(out.children.map((c) => (c as TagCond).name ?? "grp"),
    ["a", "x", "grp"]);
  const app = insertAfter(r, [], tag("z"));
  assert.deepEqual(app.children[2], tag("z"));
});

test("appendChild adds to a group and leaves a non-group alone", () => {
  const r = root();
  const out = appendChild(r, [1], tag("d"));
  assert.equal((nodeAt(out, [1]) as Group).children.length, 3);
  const noop = appendChild(r, [0], tag("d"));  // [0] is a tag, not a group
  assert.deepEqual(noop, r);
});

test("blankCond covers every condition kind with its own shape", () => {
  for (const kind of ["tag", "link", "caption", "ingroup", "subject",
                      "place", "event", "taken", "meta"] as const) {
    assert.equal(blankCond(kind).type, kind);
  }
  assert.equal(blankCond("meta", "text").op, "=");
  assert.equal(blankCond("meta", "numeric").op, ">=");
});

test("newGroup is non-empty so it renders immediately", () => {
  assert.equal(newGroup().children.length, 1);
  assert.equal(newGroup("place").children[0].type, "place");
});

test("normalizeRoot wraps any non-AND root so the top level stays AND", () => {
  const and = group(tag("a"));
  assert.equal(normalizeRoot(and), and);
  const or: Group = { type: "group", op: "or", neg: false, children: [tag("a")] };
  const out = normalizeRoot(or);
  assert.equal(out.op, "and");
  assert.deepEqual(out.children, [or]);
  const negated: Group = { ...and, neg: true };
  assert.equal(normalizeRoot(negated).neg, false);
});
