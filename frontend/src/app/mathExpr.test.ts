// The character allowlist is the entire safety argument for a Function()-based
// evaluator, so it is pinned here along with the arithmetic itself.
import { test } from "node:test";
import assert from "node:assert/strict";
import { evalExpr } from "./mathExpr.ts";

test("plain arithmetic evaluates", () => {
  assert.equal(evalExpr("500+10"), 510);
  assert.equal(evalExpr(" 2 * (3 + 4) "), 14);
  assert.equal(evalExpr("10/4"), 2.5);
  assert.equal(evalExpr("-3"), -3);
  assert.equal(evalExpr("0.5+0.25"), 0.75);
  assert.equal(evalExpr("42"), 42);
});

test("non-finite and malformed input yields null, never a throw", () => {
  assert.equal(evalExpr(""), null);
  assert.equal(evalExpr("   "), null);
  assert.equal(evalExpr("1/0"), null);          // Infinity is not a number to commit
  assert.equal(evalExpr("(1"), null);           // syntax error is caught
  assert.equal(evalExpr("1..2"), null);
  assert.equal(evalExpr("()"), null);
});

test("anything outside the allowlist is rejected before evaluation", () => {
  assert.equal(evalExpr("alert(1)"), null);
  assert.equal(evalExpr("1;2"), null);
  assert.equal(evalExpr("1e3"), null);          // letters are out, even in numbers
  assert.equal(evalExpr("0x10"), null);
  assert.equal(evalExpr("window"), null);
  assert.equal(evalExpr("1+`2`"), null);
  assert.equal(evalExpr("1,2"), null);
});
