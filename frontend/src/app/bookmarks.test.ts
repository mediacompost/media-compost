import test from "node:test";
import assert from "node:assert/strict";

import {
  isBookmarked, parseBookmarks, removeBookmark, serializeBookmarks,
  toggleBookmark,
} from "./bookmarks.ts";

test("a list survives the round trip", () => {
  assert.deepEqual(parseBookmarks(serializeBookmarks([3, 1, 2])), [3, 1, 2]);
});

test("nothing readable is nothing, and a bad entry is dropped, not thrown", () => {
  assert.deepEqual(parseBookmarks(null), []);
  assert.deepEqual(parseBookmarks(""), []);
  assert.deepEqual(parseBookmarks("{["), []);
  assert.deepEqual(parseBookmarks('{"itemId":1}'), []);
  // The shape it used to have — an object per mark — reads as nothing
  // rather than as a list of undefineds.
  assert.deepEqual(parseBookmarks('[{"itemId":1,"name":"x"}]'), []);
  assert.deepEqual(parseBookmarks('[1,"2",0,-3,4.5,null,6]'), [1, 6]);
});

test("one mark per item", () => {
  assert.deepEqual(parseBookmarks("[1,2,1]"), [1, 2]);
  assert.deepEqual(toggleBookmark([1, 2], 3), [3, 1, 2]);
});

test("the row is a toggle, and a new one goes on top", () => {
  const one = toggleBookmark([], 1);
  assert.deepEqual(one, [1]);
  const two = toggleBookmark(one, 2);
  assert.deepEqual(two, [2, 1]);
  assert.ok(isBookmarked(two, 1) && isBookmarked(two, 2));
  assert.deepEqual(toggleBookmark(two, 1), [2]);
  assert.ok(!isBookmarked(toggleBookmark(two, 1), 1));
});

test("removing names the item", () => {
  assert.deepEqual(removeBookmark([1, 2], 1), [2]);
  assert.deepEqual(removeBookmark([1, 2], 9), [1, 2]);
});
