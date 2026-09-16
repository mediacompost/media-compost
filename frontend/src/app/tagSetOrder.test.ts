import { strict as assert } from "node:assert";
import { test } from "node:test";

import { moveToFront, orderTexts } from "./tagSetOrder.ts";

const c = (...keys: string[]) => keys.map((key) => ({ key }));

test("the preferred sets come first, in the preference's own order", () => {
  const got = orderTexts(c("library", "basics", "danbooru"), ["danbooru", "basics"]);
  assert.deepEqual(got.map((x) => x.key), ["danbooru", "basics", "library"]);
});

test("keys the preference does not name keep the order they came in", () => {
  const got = orderTexts(c("a", "b", "c"), ["zzz"]);
  assert.deepEqual(got.map((x) => x.key), ["a", "b", "c"]);
});

test("an empty preference is the identity", () => {
  assert.deepEqual(orderTexts(c("b", "a"), []).map((x) => x.key), ["b", "a"]);
});

test("picking a set moves it to the front and keeps the rest", () => {
  assert.deepEqual(moveToFront(["a", "b", "c"], "c"), ["c", "a", "b"]);
  assert.deepEqual(moveToFront(["a", "b"], "new"), ["new", "a", "b"]);
  assert.deepEqual(moveToFront(["a"], "a"), ["a"]);
});
