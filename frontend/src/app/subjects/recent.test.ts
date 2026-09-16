import test from "node:test";
import assert from "node:assert/strict";
import { byRecent } from "./recent.ts";

const list = (...names: string[]) => names.map((name) => ({ name }));
const names = (rows: { name: string }[]) => rows.map((r) => r.name);

test("the most recently used comes first, and is the first arrow key reaches", () => {
  assert.deepEqual(
    names(byRecent(list("Alice", "Bob", "Carol"), ["Carol"])),
    ["Carol", "Alice", "Bob"],
  );
});

test("several recent ones keep the order they were used in", () => {
  assert.deepEqual(
    names(byRecent(list("Alice", "Bob", "Carol"), ["Carol", "Alice"])),
    ["Carol", "Alice", "Bob"],
  );
});

test("everyone untouched keeps the order they arrived in", () => {
  // The caller's order is the catalog's own — by name, or by how many pictures
  // use it — and that stays the answer for people nobody has named yet.
  assert.deepEqual(
    names(byRecent(list("Zoe", "Alice", "Bob"), ["Bob"])),
    ["Bob", "Zoe", "Alice"],
  );
});

test("a display name matches whatever case it was recorded in", () => {
  assert.deepEqual(
    names(byRecent(list("Kaguya Shinomiya", "Alice"), ["kaguya shinomiya"])),
    ["Kaguya Shinomiya", "Alice"],
  );
});

test("a remembered name nobody offers any more is simply skipped", () => {
  assert.deepEqual(
    names(byRecent(list("Alice", "Bob"), ["Deleted", "Bob"])),
    ["Bob", "Alice"],
  );
});

test("no history at all leaves the list exactly as it came", () => {
  assert.deepEqual(names(byRecent(list("Alice", "Bob"), [])), ["Alice", "Bob"]);
});
