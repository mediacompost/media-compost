import { test } from "node:test";
import assert from "node:assert/strict";
import { filterNumeric } from "./useNumericText.ts";

test("a number field refuses the keystroke rather than storing NaN", () => {
  assert.equal(filterNumeric("12"), "12");
  assert.equal(filterNumeric("12a"), null);
  assert.equal(filterNumeric(""), "", "empty is 'not yet'");
  assert.equal(filterNumeric("1."), "1.", "a decimal on its way");
  assert.equal(filterNumeric(".5"), ".5");
  assert.equal(filterNumeric("1.5", { integer: true }), null);
  assert.equal(filterNumeric("1.234", { decimals: 2 }), null);
  assert.equal(filterNumeric("1.23", { decimals: 2 }), "1.23");
  assert.equal(filterNumeric("1234", { maxLen: 3 }), null);
  assert.equal(filterNumeric("123", { integer: true, maxLen: 3 }), "123");
  assert.equal(filterNumeric("-3"), null, "no minus unless asked");
  assert.equal(filterNumeric("-3", { negative: true }), "-3");
});
