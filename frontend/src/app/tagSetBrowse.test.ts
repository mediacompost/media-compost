import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  breadcrumb, browseRows, openRow, startCursor, upFrom,
} from "./tagSetBrowse.ts";

const cat = (id: number, parent_id: number | null, name: string, entries = 0,
             position = 0) =>
  ({ id, parent_id, name, entries, position, trail: [name] });
const SETS = [
  { id: 1, key: "basics", name: "Basics", uncategorized: 2, entries: 9,
    categories: [cat(10, null, "people", 0, 0),
                 cat(11, 10, "girls", 3, 1, true), cat(12, 10, "boys", 2, 0, true),
                 cat(20, null, "quality", 2, 1)] },
  { id: 2, key: "other", name: "Other", uncategorized: 0, entries: 0, categories: [] },
];
const sug = (name: string) => ({ name, comment: "", uses: 0 });

test("the root lists the sets, and one enabled set is entered directly", () => {
  assert.equal(startCursor(SETS), null);
  assert.deepEqual(startCursor([SETS[0]]), { setId: 1, categoryId: null });
  const rows = browseRows(SETS, null, []);
  assert.deepEqual(rows.map((r) => [r.kind, r.name]),
                   [["title", ""], ["set", "Basics"], ["set", "Other"]]);
});

test("inside a set: child categories in position order, then the loose entries", () => {
  const rows = browseRows(SETS, { setId: 1, categoryId: null }, [sug("solo"), sug("crowd")]);
  assert.deepEqual(rows.map((r) => [r.kind, r.name]), [
    ["category", "people"], ["category", "quality"], ["tag", "solo"], ["tag", "crowd"]]);
  const people = rows[0];
  assert.equal(people.kind === "category" && people.count, 5);   // 3 + 2, subtree
  assert.equal(people.kind === "category" && people.kids, true);
  const quality = rows[1];
  assert.equal(quality.kind === "category" && quality.kids, false);
});

test("a category's children come before its own tags, siblings by position", () => {
  const rows = browseRows(SETS, { setId: 1, categoryId: 10 }, [sug("1girl")]);
  assert.deepEqual(rows.map((r) => r.name), ["boys", "girls", "1girl"]);
});

test("the breadcrumb is the set then the path down to the node", () => {
  assert.deepEqual(breadcrumb(SETS, null), []);
  assert.deepEqual(breadcrumb(SETS, { setId: 1, categoryId: null }), ["Basics"]);
  assert.deepEqual(breadcrumb(SETS, { setId: 1, categoryId: 11 }), ["Basics", "people", "girls"]);
});

test("→ opens a set or a category and nothing else; ← climbs and stops at the top", () => {
  const root = browseRows(SETS, null, []);
  assert.deepEqual(openRow(root[1]), { setId: 1, categoryId: null });
  // A heading opens nothing.
  assert.equal(openRow(root[0]), null);
  const inside = browseRows(SETS, { setId: 1, categoryId: null }, [sug("x")]);
  assert.deepEqual(openRow(inside[0]), { setId: 1, categoryId: 10 });
  assert.equal(openRow(inside[2]), null);
  assert.deepEqual(upFrom(SETS, { setId: 1, categoryId: 11 }), { setId: 1, categoryId: 10 });
  assert.deepEqual(upFrom(SETS, { setId: 1, categoryId: 10 }), { setId: 1, categoryId: null });
  assert.equal(upFrom(SETS, { setId: 1, categoryId: null }), null);
  assert.equal(upFrom(SETS, null), undefined);
  // With one set there is no set list to go back to.
  assert.equal(upFrom([SETS[0]], { setId: 1, categoryId: null }), undefined);
});

test("a cursor into a set that is gone yields nothing rather than throwing", () => {
  assert.deepEqual(browseRows(SETS, { setId: 99, categoryId: null }, []), []);
  assert.deepEqual(breadcrumb(SETS, { setId: 99, categoryId: 3 }), []);
});

test("asked for, a Close row leads the TOP level and nowhere else", () => {
  // The set list is the top with several sets…
  const root = browseRows(SETS, null, [], true);
  assert.equal(root[0].kind, "close");
  assert.deepEqual(root.slice(2).map((r) => r.name), ["Basics", "Other"]);
  // …and a lone set's root is the top when there is one set.
  const lone = browseRows([SETS[0]], { setId: 1, categoryId: null }, [sug("x")], true);
  assert.equal(lone[0].kind, "close");
  assert.equal(lone[1].kind, "title");
  assert.equal(lone[2].kind, "category");
  // Inside a set (with a set list above it) and inside a category, ← is the
  // way back and no Close row is offered.
  assert.equal(browseRows(SETS, { setId: 1, categoryId: null }, [], true)[0].kind, "category");
  assert.equal(browseRows(SETS, { setId: 1, categoryId: 10 }, [], true)[0].kind, "category");
  // Not asked for, only the heading changes.
  assert.equal(browseRows(SETS, null, [])[1].kind, "set");
  // It opens nothing.
  assert.equal(openRow(root[0]), null);
});

test("the top level heads its sections; below it there are no headings", () => {
  // The breadcrumb bar is hidden at the top level, so the sets' own heading
  // is what says whose rows these are — with or without a history.
  assert.deepEqual(browseRows(SETS, null, []).map((r) => r.kind),
                   ["title", "set", "set"]);
  assert.deepEqual(browseRows(SETS, { setId: 1, categoryId: 10 }, [sug("1girl")])
                     .map((r) => r.kind),
                   ["category", "category", "tag"]);
  // Nothing to head, no heading.
  assert.deepEqual(browseRows([], null, [], true), [{ kind: "close", name: "" }]);
});

test("the history sits under the Close row, above the sets, between titles", () => {
  const rows = browseRows(SETS, null, [], true, ["cat -dog", "!bird"]);
  assert.deepEqual(rows.map((r) => [r.kind, r.name]), [
    ["close", ""],
    ["title", ""], ["history", "cat -dog"], ["history", "!bird"],
    ["title", ""],
    ["set", "Basics"], ["set", "Other"],
  ]);
  const [hist, sets] = rows.filter((r) => r.kind === "title");
  assert.equal(hist.kind === "title" && hist.section, "history");
  assert.equal(sets.kind === "title" && sets.section, "sets");
  // A history line opens nothing — picking it writes the line.
  assert.equal(openRow(rows[2]), null);
});

test("with no set to show, the history stands alone under its heading", () => {
  assert.deepEqual(browseRows([], null, [], true, ["cat -dog"]).map((r) => [r.kind, r.name]),
                   [["close", ""], ["title", ""], ["history", "cat -dog"]]);
});

test("no history, no history heading — and none of it below the top level", () => {
  assert.deepEqual(browseRows(SETS, null, [], true).map((r) => r.kind),
                   ["close", "title", "set", "set"]);
  // Inside a set the rows are that set's, whatever the history holds.
  assert.deepEqual(
    browseRows(SETS, { setId: 1, categoryId: 10 }, [sug("1girl")], true, ["cat"])
      .map((r) => r.kind),
    ["category", "category", "tag"]);
  // A lone set's root IS the top level, and takes it.
  assert.deepEqual(
    browseRows([SETS[0]], { setId: 1, categoryId: null }, [], true, ["cat"])
      .map((r) => r.kind),
    ["close", "title", "history", "title", "category", "category"]);
});

const GROUPS = [
  { id: 3, name: "Cats", depth: 0, parent: null, count: 40 },
  { id: 9, name: "To sort", depth: 1, parent: 3, trail: ["Cats"], count: 7 },
  { id: 4, name: "Dogs", depth: 0, parent: null, count: 12 },
];

test("the library's groups are a section of their own, over the sets", () => {
  const rows = browseRows(SETS, null, [], true, ["cat -dog"], GROUPS);
  // THE ROOTS AND ONLY THE ROOTS. What is inside `Cats` is one press away,
  // which is what the sets' own categories do — a hundred groups four deep
  // made this a hundred rows of which the ten that matter led.
  assert.deepEqual(rows.map((r) => [r.kind, r.name]), [
    ["close", ""],
    ["title", ""], ["history", "cat -dog"],
    ["title", ""], ["group", "Cats"], ["group", "Dogs"],
    ["title", ""],
    ["set", "Basics"], ["set", "Other"],
  ]);
  const titles = rows.filter((r) => r.kind === "title");
  assert.deepEqual(titles.map((r) => r.kind === "title" && r.section),
                   ["history", "groups", "sets"]);
  // The item count rides along, the way a category's entry count does.
  assert.deepEqual(rows.filter((r) => r.kind === "group")
    .map((r) => r.kind === "group" && r.count), [40, 12]);
  // Inside a set the rows are that set's, groups or no groups.
  assert.deepEqual(
    browseRows(SETS, { setId: 1, categoryId: 10 }, [sug("1girl")], true, [],
               GROUPS).map((r) => r.kind),
    ["category", "category", "tag"]);
  // No groups, no heading; and with only groups they stand alone.
  assert.deepEqual(browseRows(SETS, null, [], true).map((r) => r.kind),
                   ["close", "title", "set", "set"]);
  assert.deepEqual(browseRows([], null, [], true, [], GROUPS)
                     .map((r) => [r.kind, r.name]),
                   [["close", ""], ["title", ""], ["group", "Cats"],
                    ["group", "Dogs"]]);
});

test("a group that holds others is a PAGE, and it is on its own page", () => {
  const rows = browseRows(SETS, null, [], true, [], GROUPS);
  const cats = rows.find((r) => r.kind === "group" && r.name === "Cats")!;
  const dogs = rows.find((r) => r.kind === "group" && r.name === "Dogs")!;
  // → opens the one with children; the leaf opens nothing, since Enter on
  // it is the whole of what a leaf can mean.
  assert.deepEqual(openRow(cats), { groupId: 3 });
  assert.equal(openRow(dogs), null);
  assert.equal(cats.kind === "group" && cats.kids, true);
  assert.equal(dogs.kind === "group" && dogs.kids, false);

  // ITS PAGE: the group ITSELF first — a group that holds others is still a
  // group somebody may want, and a page of only children would have made
  // every parent unpickable — then what is inside it, and nothing else.
  const inside = browseRows(SETS, { groupId: 3 }, [], true, ["x"], GROUPS);
  assert.deepEqual(inside.map((r) => [r.kind, r.name]),
                   [["group", "Cats"], ["group", "To sort"]]);
  assert.equal(inside[0].kind === "group" && inside[0].self, true);
  // …and the page's own group never offers to open itself again.
  assert.equal(inside[0].kind === "group" && inside[0].kids, false);
  assert.equal(openRow(inside[0]), null);

  // ← goes back to the top, and the breadcrumb says where you are.
  assert.equal(upFrom(SETS, { groupId: 3 }, GROUPS), null);
  assert.deepEqual(upFrom(SETS, { groupId: 9 }, GROUPS), { groupId: 3 });
  assert.deepEqual(breadcrumb(SETS, { groupId: 9 }, GROUPS),
                   ["Cats", "To sort"]);
  // A cursor naming a group that is gone shows nothing rather than throwing.
  assert.deepEqual(browseRows(SETS, { groupId: 99 }, [], true, [], GROUPS), []);

  // AN ORPHAN IS A ROOT. A host offers the groups still worth adding — the
  // tag grid leaves out the ones already picked — so a child whose parent
  // is not in the list has to be reachable, and the top level is where.
  const noCats = GROUPS.filter((g) => g.id !== 3);
  assert.deepEqual(
    browseRows(SETS, null, [], false, [], noCats)
      .filter((r) => r.kind === "group").map((r) => r.name),
    ["To sort", "Dogs"]);
  assert.equal(upFrom(SETS, { groupId: 9 }, noCats), null);
});
