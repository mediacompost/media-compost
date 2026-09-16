/**
 * The one funnel every user-visible date in the app goes through.
 *
 * It had no test at all, which is worth saying plainly: `renderDate` is a
 * hand-written pattern scanner, the Settings page renders its twelve options
 * by calling it on a sample date, and every date in the sidebar, the History
 * view, the Train tab and the item window is its output. A token that stopped
 * matching would be visible everywhere at once and caught by nothing.
 *
 * Dates are built with explicit local-time components (`new Date(y, m, d)`),
 * never parsed from an ISO string with a `Z` — the renderer reads
 * `getFullYear`/`getMonth`/`getDate`, which are local, so a UTC literal makes
 * these assertions depend on the machine's timezone.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DATE_FORMAT_OPTIONS, DEFAULT_FORMAT, fmtDuration, renderDate, renderTime,
} from "./dateFormat.ts";

/** 9 March 2026, local. Single-digit day AND month, so the padded and
 *  unpadded tokens are distinguishable in every pattern. */
const D = new Date(2026, 2, 9, 20, 5, 7);

test("every pattern Settings offers renders something with all three parts", () => {
  for (const pattern of DATE_FORMAT_OPTIONS) {
    const out = renderDate(D, pattern, { locale: "en-GB" });
    assert.ok(out.includes("2026"), `${pattern} lost the year: ${out}`);
    assert.ok(/9/.test(out), `${pattern} lost the day: ${out}`);
    // The month is a name in four of them and a number in the rest.
    assert.ok(/Mar|March|\b0?3\b/.test(out), `${pattern} lost the month: ${out}`);
  }
});

test("the numeric patterns render exactly", () => {
  const en = { locale: "en-GB" } as const;
  assert.equal(renderDate(D, "YYYY-MM-DD", en), "2026-03-09");
  assert.equal(renderDate(D, "YYYY/MM/DD", en), "2026/03/09");
  assert.equal(renderDate(D, "DD/MM/YYYY", en), "09/03/2026");
  assert.equal(renderDate(D, "D/M/YYYY", en), "9/3/2026");
  assert.equal(renderDate(D, "M/D/YYYY", en), "3/9/2026");
  assert.equal(renderDate(D, "DD.MM.YYYY", en), "09.03.2026");
  assert.equal(renderDate(D, "D.M.YYYY", en), "9.3.2026");
});

test("the name patterns take the month name from the locale passed in", () => {
  // The whole reason `locale` exists: a Japanese UI printing "9 Mar 2026"
  // because the browser is en-US reads as a bug.
  assert.equal(renderDate(D, "D MMM YYYY", { locale: "en-GB" }), "9 Mar 2026");
  assert.equal(renderDate(D, "D MMMM YYYY", { locale: "en-GB" }), "9 March 2026");
  assert.equal(renderDate(D, "D MMMM YYYY", { locale: "de" }), "9 März 2026");
  assert.equal(renderDate(D, "MMMM D, YYYY", { locale: "en-GB" }), "March 9, 2026");
});

test("the scanner is greedy: YYYY before YY, MMMM before MMM before MM", () => {
  // Longest-first is the whole of the token table's ordering, and getting it
  // wrong renders "2026" as "2020" + "26" — plausible-looking and wrong.
  const en = { locale: "en-GB" } as const;
  assert.equal(renderDate(D, "YYYY", en), "2026");
  assert.equal(renderDate(D, "YY", en), "26");
  assert.equal(renderDate(D, "MMMM", en), "March");
  assert.equal(renderDate(D, "MMM", en), "Mar");
  assert.equal(renderDate(D, "MM", en), "03");
  assert.equal(renderDate(D, "M", en), "3");
});

test("shortYear rewrites only the 4-digit token", () => {
  const en = { locale: "en-GB" } as const;
  assert.equal(renderDate(D, "YYYY-MM-DD", { ...en, shortYear: true }),
               "26-03-09");
  // A pattern already asking for two digits is unchanged by the flag.
  assert.equal(renderDate(D, "YY-MM-DD", { ...en, shortYear: true }),
               "26-03-09");
});

test("anything that is not a token is a literal, separators included", () => {
  const en = { locale: "en-GB" } as const;
  assert.equal(renderDate(D, "[D] YYYY", en), "[9] 2026");
  // A lone letter with no token meaning passes through rather than vanishing.
  assert.equal(renderDate(D, "D. XYZ", en), "9. XYZ");
});

test("an unparseable value is an empty string, never 'Invalid Date'", () => {
  // Callers render this straight into the DOM, so the failure has to be
  // silent-and-empty rather than the word the Date constructor produces.
  assert.equal(renderDate("not a date", "YYYY-MM-DD"), "");
  assert.equal(renderDate(NaN, "YYYY-MM-DD"), "");
  assert.equal(renderTime("not a date", true), "");
});

test("a number is read as an epoch in MILLISECONDS", () => {
  // `formatUnix` multiplies by 1000 before calling in, so this is the
  // contract that makes the training tab's unix seconds land in this century.
  const ms = D.getTime();
  assert.equal(renderDate(ms, "YYYY-MM-DD", { locale: "en-GB" }), "2026-03-09");
});

test("renderTime honours the 24-hour toggle", () => {
  assert.equal(renderTime(D, true), "20:05");
  // 12-hour keeps `hour: "2-digit"`, so it reads "08:05 PM" rather than
  // "8:05 PM" — pinned because it is the kind of thing somebody "fixes" to
  // `numeric` without noticing the 24-hour side then loses its leading zero.
  // The separator before the meridiem is locale punctuation (a narrow no-break
  // space in some ICU builds), so it is matched rather than spelled out.
  const half = renderTime(D, false);
  assert.match(half, /^08:05\s*PM$/i);
});

test("the default pattern is the first option, as Settings assumes", () => {
  assert.equal(DEFAULT_FORMAT, DATE_FORMAT_OPTIONS[0]);
  assert.equal(DEFAULT_FORMAT, "D MMM YYYY");
});

test("fmtDuration counts in m:ss and grows an hours field", () => {
  assert.equal(fmtDuration(0), "0:00");
  assert.equal(fmtDuration(7), "0:07");
  assert.equal(fmtDuration(75), "1:15");
  assert.equal(fmtDuration(599), "9:59");
  assert.equal(fmtDuration(3600), "1:00:00");
  assert.equal(fmtDuration(3661), "1:01:01");
  // Past an hour the minutes pad, so 1:05:00 cannot be misread as 1:5:00.
  assert.equal(fmtDuration(3900), "1:05:00");
});

test("fmtDuration never renders a negative or a NaN clock", () => {
  // It is fed `item.duration`, which is null for anything ffprobe could not
  // read — and "NaN:NaN" on a grid card is worse than a zero.
  assert.equal(fmtDuration(-5), "0:00");
  assert.equal(fmtDuration(NaN), "0:00");
  assert.equal(fmtDuration(Infinity), "0:00");
});

test("fmtDuration truncates rather than rounds", () => {
  // A 9.99 s clip reads 0:09 while it is still playing its tenth second;
  // rounding up would show a duration the transport can never reach.
  assert.equal(fmtDuration(9.99), "0:09");
  assert.equal(fmtDuration(59.9), "0:59");
});
