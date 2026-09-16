import test from "node:test";
import assert from "node:assert/strict";
import { formatTaken, isValidTaken, parseTaken, precisionOf } from "./taken.ts";

test("a value carries how much of itself is known", () => {
  assert.equal(precisionOf(20200000000000), "year");
  assert.equal(precisionOf(20200300000000), "month");
  assert.equal(precisionOf(20200305000000), "day");
  assert.equal(precisionOf(20200305140000), "hour");
  assert.equal(precisionOf(20200305143000), "minute");
  assert.equal(precisionOf(20200305143012), "second");
  assert.equal(precisionOf(null), "none");
});

test("typed dates are read at the precision they were typed to", () => {
  assert.equal(parseTaken("2020"), 20200000000000);
  assert.equal(parseTaken("March 2020"), 20200300000000);
  assert.equal(parseTaken("5 March 2020"), 20200305000000);
  assert.equal(parseTaken("2020-03-05"), 20200305000000);
});

test("a time is read only when the day is known", () => {
  assert.equal(parseTaken("5 March 2020 14:30"), 20200305143000);
  assert.equal(parseTaken("2020-03-05 14:30:12"), 20200305143012);
  // "March 2020 at half two" is not a moment, so the time is dropped rather
  // than stored as a precision nobody has.
  assert.equal(parseTaken("March 2020 14:30"), 20200300000000);
});

test("nonsense is refused rather than rounded", () => {
  assert.equal(parseTaken(""), null);
  assert.equal(parseTaken("not a date"), null);
  assert.equal(parseTaken("5 March 2020 25:00"), null);
});

test("what it writes, it reads back", () => {
  for (const text of ["2020", "March 2020", "5 March 2020",
                      "5 March 2020 14:30", "5 March 2020 14:30:12"]) {
    const value = parseTaken(text);
    assert.ok(value, text);
    assert.equal(parseTaken(formatTaken(value)), value, text);
  }
});

test("a smaller component needs the one above it", () => {
  assert.equal(isValidTaken(20200005000000), false, "a day with no month");
  assert.equal(isValidTaken(20200300143000), false, "a time with no day");
  assert.equal(isValidTaken(20200305143000), true);
  assert.equal(isValidTaken(20201305000000), false, "month 13");
});
