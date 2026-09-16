import { test } from "node:test";
import assert from "node:assert/strict";
import { frozenNext } from "./useFrozen.ts";

test("the first answer is held; a later one is ignored until the key changes", () => {
  let h = frozenNext<number[] | undefined>(null, undefined, 1);
  assert.equal(h, null, "nothing yet");
  h = frozenNext(h, [1], 1);
  assert.deepEqual(h?.value, [1]);
  h = frozenNext(h, [1, 2], 1);
  assert.deepEqual(h?.value, [1], "the refetch does not move the form");
  h = frozenNext(h, [1, 2], 2);
  assert.deepEqual(h?.value, [1, 2], "another subject takes the fresh answer");
});
