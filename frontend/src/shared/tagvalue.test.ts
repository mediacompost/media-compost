/** `tagvalue.ts` and `media_compost/tagvalue.py` must agree.
 *
 *  `tests/core/golden/value_corpus.json` is the contract; both suites read
 *  the same file (this one and `tests/core/test_tagvalue.py`), so a unit
 *  added or a family factor moved on one side fails the other's suite.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { parseValue, canonValue, matchesValue } from "./tagvalue.ts";

const here = dirname(fileURLToPath(import.meta.url));
// frontend/src/shared -> frontend/src -> frontend -> repo root
const CORPUS = join(here, "../../../tests/core/golden/value_corpus.json");

type Case = {
  basename: string; value: number | null; unit?: string;
  space?: string; canon?: number;
};
type Match = {
  basename: string; op: string; value: number; unit: string;
  tol: number; hit: boolean;
};
const corpus = JSON.parse(readFileSync(CORPUS, "utf8")) as {
  cases: Case[]; matches: Match[];
};

const close = (a: number, b: number) => Math.abs(a - b) <= Math.abs(b) * 1e-9 + 1e-12;

test("parse matches the corpus", () => {
  for (const c of corpus.cases) {
    const got = parseValue(c.basename);
    if (c.value === null) {
      assert.equal(got, null, c.basename);
      continue;
    }
    assert.ok(got, c.basename);
    assert.ok(close(got.value, c.value), `${c.basename} value`);
    assert.equal(got.unit, c.unit, `${c.basename} unit`);
    const [sp, canon] = canonValue(got);
    assert.equal(sp, c.space, `${c.basename} space`);
    assert.ok(close(canon, c.canon!), `${c.basename} canon`);
  }
});

test("matches follow the corpus", () => {
  for (const m of corpus.matches) {
    assert.equal(
      matchesValue(m.basename, m.op, m.value, m.unit, m.tol), m.hit,
      `${m.basename} ${m.op} ${m.value}${m.unit} tol ${m.tol}`);
  }
});
