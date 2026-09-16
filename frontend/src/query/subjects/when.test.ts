import test from "node:test";
import assert from "node:assert/strict";

import {
  ageAt, bounds, dateFromAge, decode, encode, formatDate, isValid,
  parseDate, precisionOf, whenLabel,
} from "./when.ts";

test("a partial date carries its own precision", () => {
  assert.equal(precisionOf(19750000), "year");
  assert.equal(precisionOf(19990700), "month");
  assert.equal(precisionOf(18790314), "day");
  assert.equal(precisionOf(null), "none");
  assert.deepEqual(decode(18790314), [1879, 3, 14]);
  assert.equal(encode(1879, 3, 14), 18790314);
});

test("a partial date covers what it does not say", () => {
  assert.deepEqual(bounds(19750000), [19750101, 19751231]);
  assert.deepEqual(bounds(19990700), [19990701, 19990731]);
  assert.deepEqual(bounds(18790314), [18790314, 18790314]);
});

test("a day needs a month to mean anything", () => {
  assert.equal(isValid(19750000), true);
  assert.equal(isValid(19990700), true);
  assert.equal(isValid(19750014), false, "day 14 of no month");
  assert.equal(isValid(19751332), false);
  assert.equal(isValid(0), false);
});

test("age never overstates itself", () => {
  // Born 14 March 1879: still 20 in January 1900, 21 in April.
  assert.equal(ageAt(18790314, 19000100), 20);
  assert.equal(ageAt(18790314, 19000401), 21);
  // A year-only date reads as the start of the year.
  assert.equal(ageAt(19750000, 19750000), 0);
  assert.equal(ageAt(19750000, 20200000), 45);
  assert.equal(ageAt(19750000, 19700000), null, "not yet born");
  assert.equal(ageAt(null, 20200000), null);
});

test("an age gives back a year, and only a year", () => {
  assert.equal(dateFromAge(19750000, 12), 19870000);
  assert.equal(precisionOf(dateFromAge(18790314, 21)), "year");
  assert.equal(dateFromAge(19750000, -1), null);
  assert.equal(dateFromAge(null, 12), null);
});

test("typed dates are read at the precision they were typed to", () => {
  assert.equal(parseDate("1975"), 19750000);
  assert.equal(parseDate("1999-07"), 19990700);
  assert.equal(parseDate("1879-03-14"), 18790314);
  assert.equal(parseDate("7/1999"), 19990700, "month first when the year trails");
  assert.equal(parseDate("14.3.1879"), 18790314, "day first when the year trails");
  assert.equal(parseDate(" 1975 "), 19750000);
  assert.equal(parseDate(""), null);
  assert.equal(parseDate("nope"), null);
  assert.equal(parseDate("75"), null, "a two-digit year is a guess, not a date");
  assert.equal(parseDate("1999-13"), null, "no thirteenth month");
});

test("a partial date formats at its own precision", () => {
  assert.equal(formatDate(19750000), "1975");
  assert.equal(formatDate(19990700), "July 1999");
  assert.equal(formatDate(18790314), "14 March 1879");
  assert.equal(formatDate(null), "");
  assert.equal(formatDate(19990700, "de-DE"), "Juli 1999");
});

test("the when chip says whichever half is known, and derives the other", () => {
  assert.equal(whenLabel({ date: 19210000 }, null), "1921");
  assert.equal(whenLabel({ age: 12 }, null), "age 12");
  // With a since-date the age follows from the year, and vice versa.
  assert.equal(whenLabel({ date: 20220000 }, 20100000), "2022 · age 12");
  assert.equal(whenLabel({ age: 12 }, 20100000), "age 12");
  assert.equal(whenLabel(null, 20100000), "");
});

test("what formatDate writes, parseDate reads back", () => {
  // The editor prefills its field with formatDate's output; if the parser
  // could not read it, the form would flag the value it had just shown.
  for (const v of [19750000, 19990700, 18790314, 20101231, 19000100]) {
    assert.equal(parseDate(formatDate(v)), v, String(v));
  }
  assert.equal(parseDate("March 1879"), 18790300);
  assert.equal(parseDate("14 mar 1879"), 18790314);
  assert.equal(parseDate("nope 1879"), null, "a word that is not a month");
});

// ---- localized round trip (the 8-language expansion) ------------------------
// `formatDate(v, locale)` prefills editors, so `parseDate(text, locale)` must
// read every form it writes — per language, per precision. This single
// property is what licenses localizing the display at all.

test("parseDate reads back every formatDate output, in every language", () => {
  const langs = ["en", "de", "ja", "zh-Hans", "ko", "es", "pt-BR", "fr"];
  const values = [19750000, 19990700, 18790314, 20200101, 15031200];
  for (const lang of langs) {
    for (const v of values) {
      const text = formatDate(v, lang);
      assert.equal(parseDate(text, lang), v, `${lang}: ${text}`);
    }
  }
});

test("an English month name still parses under any locale", () => {
  assert.equal(parseDate("March 1879", "ja"), 18790300);
  assert.equal(parseDate("14 March 1879", "fr"), 18790314);
});
