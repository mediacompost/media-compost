import { strict as assert } from "node:assert";
import { test } from "node:test";

import {
  csvToBulkRows, guessColumns, looksLikeHeader, splitList,
} from "./tagSetCsv.ts";

test("the header guess claims each column once, exact words first", () => {
  assert.deepEqual(guessColumns(["name", "post_count", "category", "wiki", "aliases"]),
                   { name: 0, count: 1, category: 2, description: 3, aliases: 4 });
  // `tag_count` is the count even though it contains "tag"; `tag` is the name.
  assert.deepEqual(guessColumns(["tag_count", "tag"]), { name: 1, count: 0 });
  // A containing match fills what no exact word did — "Wiki Page Excerpt".
  assert.deepEqual(guessColumns(["Tag Name", "Wiki Page Excerpt"]),
                   { name: 0, description: 1 });
  assert.deepEqual(guessColumns(["x", "y"]), {});
});

test("a first row of names and numbers is data, not a header", () => {
  assert.equal(looksLikeHeader(["name", "count"]), true);
  assert.equal(looksLikeHeader(["1girl", "4500000"]), false);
  assert.equal(looksLikeHeader(["foo", "bar"]), false);
});

test("a list cell splits on commas and whitespace and normalizes each name", () => {
  assert.deepEqual(splitList("Blue_Hair, red hair  green_eyes"),
                   ["blue_hair", "red", "hair", "green_eyes"]);
  assert.deepEqual(splitList(""), []);
});

test("rows are normalized, deduplicated by name, and only mapped fields are written", () => {
  const table = [
    ["name", "post_count", "category", "aliases"],
    ["1girl", "4,500,000", "0", "1girls 1female"],
    ["1Girl", "1", "0", ""],
    ["", "5", "0", ""],
    ["Hatsune_Miku", "900000", "4", "miku"],
    ["   ", "", "", ""],
  ];
  const got = csvToBulkRows(table, guessColumns(table[0]), { hasHeader: true });
  assert.equal(got.skipped, 2);
  assert.deepEqual(got.rows, [
    { name: "1girl", count: 4500000, category: ["0"], aliases: ["1girls", "1female"] },
    { name: "hatsune_miku", count: 900000, category: ["4"], aliases: ["miku"] },
  ]);
  // No description column: the key is ABSENT, not "".
  assert.equal("description" in got.rows[0], false);
});

test("a category cell is split into the trail of names it spells", () => {
  // ONE cell has to hold the whole trail, so '/' separates two names HERE,
  // the one place left that reads one — the row the API takes carries the
  // names apart, which is what lets a name elsewhere hold a slash.
  const table = [["a", "7"], ["b", "people/girls"], ["c", " a / b "],
                 ["d", "/"]];
  const map = { name: 0, category: 1 };
  assert.deepEqual(csvToBulkRows(table, map, { hasHeader: false }).rows
    .map((r) => r.category),
    [["7"], ["people", "girls"], ["a", "b"], undefined]);
});

test("a minimum count drops the rows under it, keeps a row with no count, and counts what it dropped", () => {
  const table = [["a", "5"], ["b", "50"], ["c", ""], ["d", "49"]];
  const map = { name: 0, count: 1 };
  const got = csvToBulkRows(table, map, { hasHeader: false, minCount: 50 });
  assert.deepEqual(got.rows.map((r) => r.name), ["b", "c"]);
  assert.equal(got.belowMin, 2);
  assert.equal(got.skipped, 0);
  // Without a minimum, nothing is dropped for its count.
  assert.equal(csvToBulkRows(table, map, { hasHeader: false }).rows.length, 4);
});

test("an empty count cell is null and a self-alias is dropped", () => {
  const table = [["solo", "", "solo, alone"]];
  const got = csvToBulkRows(table, { name: 0, count: 1, aliases: 2 },
                            { hasHeader: false });
  assert.deepEqual(got.rows, [{ name: "solo", count: null, aliases: ["alone"] }]);
});
