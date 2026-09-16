import { test } from "node:test";
import assert from "node:assert/strict";
import { composeOverPage } from "./overPage.ts";

test("except(k) is false when only k is up, true when anything else is", () => {
  const up = { a: false, b: false, c: false };
  const over = composeOverPage({
    a: () => up.a, b: () => up.b, c: () => up.c,
  });
  assert.equal(over.any(), false);
  assert.equal(over.except("a")(), false);
  up.a = true;
  assert.equal(over.any(), true);
  assert.equal(over.except("a")(), false, "a's own guard must not see a");
  assert.equal(over.except("b")(), true);
  up.b = true;
  assert.equal(over.except("a")(), true);
  assert.equal(over.except("a", "b")(), false);
  up.c = true;
  assert.equal(over.except("a", "b")(), true);
});

test("the questions read the flags live, not at composition", () => {
  let x = false;
  const over = composeOverPage({ x: () => x });
  const ask = over.except();
  assert.equal(ask(), false);
  x = true;
  assert.equal(ask(), true);
});
