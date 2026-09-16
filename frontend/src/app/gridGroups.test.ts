// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import { groupLabel, jumpGroups } from "./gridGroups.ts";
import type { GroupRun } from "./gridGeom.ts";

// The real `t` fills `{name}` placeholders (`shared/i18n: fillVars`); a
// stand-in that only echoed would have let "Score {n}" pass as a label.
const t = (s: string, vars?: Record<string, string | number>) =>
  vars ? s.replace(/\{(\w+)\}/g, (m, k) => String(vars[k] ?? m)) : s;

// ---- groupLabel: dates ------------------------------------------------------

test("groupLabel: a year key is its own label", () => {
  assert.equal(groupLabel("year", "1503", "en", t), "1503");
  assert.equal(groupLabel("year", "2024", "en", t), "2024");
});

test("groupLabel: a real month formats as one", () => {
  assert.equal(groupLabel("month", "196907", "en", t), "July 1969");
});

test("groupLabel: a year-only date under Month grouping says the year", () => {
  // A capture date's zeros are its precision, so `15030000000000` keys as
  // "150300" — month unknown. Fed to `Date`, month -1 read "December 1502".
  assert.equal(groupLabel("month", "150300", "en", t), "1503");
});

test("groupLabel: a ranking's bucket is a SCORE, not a bare number", () => {
  // A section headed "7" over a row of pictures is a number with nothing to
  // hold it, where every other grouping here names what it is counting.
  assert.equal(groupLabel("bucket", "7", "en", t), "Score 7");
  assert.equal(groupLabel("bucket", "0", "en", t), "Score 0");
  // A picture the ranking has not placed is not at score zero.
  assert.equal(groupLabel("bucket", "", "en", t), "Unplaced");
});

test("groupLabel: partial dates under Day grouping say what is known", () => {
  assert.equal(groupLabel("day", "19690720", "en", t), "July 20, 1969");
  assert.equal(groupLabel("day", "18880900", "en", t), "September 1888");
  assert.equal(groupLabel("day", "15030000", "en", t), "1503");
});

test("groupLabel: the empty key is the undated section", () => {
  assert.equal(groupLabel("year", "", "en", t), "Undated");
});

// ---- jumpGroups: partial dates stack under their own year -------------------

test("jumpGroups: a year-only month section lands under its year", () => {
  const runs: GroupRun[] = [
    { key: "150300", count: 2 },
    { key: "196907", count: 3 },
    { key: "", count: 1 },
  ];
  const groups = jumpGroups("month", runs, "en", t);
  assert.deepEqual(groups.map((g) => g.label), ["1503", "1969", "Undated"]);
  assert.equal(groups[0].entries[0].label, "1503");
  assert.equal(groups[1].entries[0].label, "July 1969");
});

// ---- the lang argument reaches Intl (the 8-language expansion) --------------

test("groupLabel: month names follow the APP language, not the browser", () => {
  assert.equal(groupLabel("month", "196907", "de", t), "Juli 1969");
  assert.equal(groupLabel("month", "196907", "ja", t), "1969年7月");
  assert.equal(groupLabel("day", "18880900", "de", t), "September 1888");
  // A year-only key has no month to localize and reads the same everywhere.
  assert.equal(groupLabel("month", "150300", "ja", t), "1503");
});
