// The namespace parents in the Items tags list — the rules as tests.
import test from "node:test";
import assert from "node:assert/strict";

import { namespacedRows, nestAliases } from "./tagNamespaceRows.ts";
import type { TagRow } from "../shared/api.ts";

//: The library's numeric columns — what `namespacedRows` totals.
const COLS = ["positive", "implicit", "negative"];

const tag = (name: string, positive = 0, over: Partial<TagRow> = {}): TagRow =>
  ({
    id: name.length + positive, name, comment: "", description: "",
    // The tag set's numeric columns, keyed by column — the library's
    // three counts of pictures here (`tagSetColumns.ts`).
    numbers: { positive, negative: 0, implicit: 0 },
    alias_of: null, implies: [], meta_tags: [],
    ...over,
  }) as unknown as TagRow;

test("two shared prefixes gain a parent row; a lone one does not", () => {
  const rows = [tag("apple"), tag("costume:tiger"), tag("costume:dog"),
                tag("height:172cm")];
  const out = namespacedRows(rows, "name", "asc");
  const kinds = out.map((e) => (e.kind === "namespace" ? `ns:${e.name}`
    : `${"depth" in e ? e.depth : 0}:${e.row.name}`));
  assert.deepEqual(kinds, [
    "0:apple",
    "ns:costume", "1:costume:dog", "1:costume:tiger",
    "0:height:172cm",
  ]);
});

test("name sort orders children numeric-aware", () => {
  const rows = [tag("quality:10"), tag("quality:2"), tag("quality:9")];
  const out = namespacedRows(rows, "name", "asc");
  assert.deepEqual(
    out.filter((e) => e.kind === "tag").map((e) => e.row.name),
    ["quality:2", "quality:9", "quality:10"]);
});

test("a count sort places the parent by the group TOTAL", () => {
  // costume totals 12; "big" alone has 10 — the group outranks it even though
  // its best member (7) does not.
  const rows = [tag("big", 10), tag("costume:tiger", 7), tag("costume:dog", 5)];
  const out = namespacedRows(rows, "positive", "desc");
  assert.equal(out[0].kind, "namespace");
  assert.equal((out[0] as { numbers: Record<string, number> })
               .numbers.positive, 12);
  const last = out[out.length - 1];
  assert.equal(last.kind === "tag" ? last.row.name : "", "big");
  // …and children sort by their own count.
  assert.deepEqual(
    out.filter((e) => e.kind === "tag" && e.depth === 1)
      .map((e) => (e as { row: TagRow }).row.name),
    ["costume:tiger", "costume:dog"]);
});

test("no namespaces means the flat list, untouched", () => {
  const rows = [tag("b"), tag("a")];
  const out = namespacedRows(rows, "name", "asc");
  assert.deepEqual(out.map((e) => e.kind === "tag" ? e.row.name : ""),
                   ["b", "a"]);
});

test("the tag you searched for by name comes first, whatever the sort", () => {
  // THE POINT: this module RE-SORTS what it is given, so the server hoisting
  // the exact match to the front of the index was not enough — searching `a`
  // in a library where `a` is tagged twice left it hundreds of rows down,
  // under everything more popular that merely contains an `a`.
  const rows = [tag("photograph", 64), tag("manga", 43), tag("a", 2)];
  const out = namespacedRows(rows, "positive", "desc", COLS, "a");
  assert.deepEqual(out.map((e) => (e.kind === "tag" ? e.row.name : "")),
                   ["a", "photograph", "manga"]);
  // Without a search the order is the column's, untouched.
  assert.deepEqual(
    namespacedRows(rows, "positive", "desc")
      .map((e) => (e.kind === "tag" ? e.row.name : "")),
    ["photograph", "manga", "a"]);
});

test("an exact match inside a namespace brings its group up and leads it", () => {
  // A row lifted out of its parent would be drawn under whatever ended up
  // above it, so the GROUP comes first and the row leads the group.
  const rows = [tag("big", 99), tag("costume:tiger", 7), tag("costume:dog", 1)];
  const out = namespacedRows(rows, "positive", "desc", COLS, "costume:dog");
  assert.equal(out[0].kind, "namespace");
  assert.deepEqual(
    out.filter((e) => e.kind === "tag" && e.depth === 1)
      .map((e) => (e as { row: TagRow }).row.name),
    ["costume:dog", "costume:tiger"]);
  const last = out[out.length - 1];
  assert.equal(last.kind === "tag" ? last.row.name : "", "big");
});

test("an alias row nests one indent under the name it spells", () => {
  // The server puts it directly beneath its target in every order; this is
  // the other half of saying so.
  const rows = [tag("big", 10),
                tag("large", 0, { alias_of: "big" }),
                tag("costume:tiger", 7), tag("costume:dog", 5),
                tag("costume:pup", 0, { alias_of: "costume:dog" })];
  const out = nestAliases(namespacedRows(rows, "name", "asc", COLS));
  const shape = out.map((e) => (e.kind === "namespace" ? `ns:${e.name}`
    : `${e.depth}:${e.row.name}`));
  assert.deepEqual(shape, [
    "0:big", "1:large",
    "ns:costume", "1:costume:dog", "2:costume:pup", "1:costume:tiger",
  ]);
});

test("an alias whose target is not in the list keeps its own depth", () => {
  // An indent under nothing reads as a child of the row above, which would
  // be a different tag.
  const rows = [tag("apple"), tag("large", 0, { alias_of: "big" })];
  const out = nestAliases(namespacedRows(rows, "name", "asc", COLS));
  assert.deepEqual(out.map((e) => (e.kind === "tag" ? e.depth : -1)), [0, 0]);
});
