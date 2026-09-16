/** `tree.ts` and `media_compost/querystring.py` must agree.
 *
 *  They are two implementations of one grammar. This side keeps its own copy
 *  because the query builder is two-way bound to the text field — it re-parses
 *  on every keystroke and re-serializes on every dropdown change, and a round
 *  trip to the server in that loop is lag on every click.
 *
 *  `tests/core/golden/query_corpus.json` is the contract, and BOTH suites
 *  read the same file: this one and `tests/core/test_querystring.py`. A
 *  change on either side that the other has not made fails immediately, in the
 *  suite of whoever made it. Regenerate with
 *  `MEDIA_COMPOST_UPDATE_GOLDEN=1 pytest tests/core/test_querystring.py` and
 *  update both in the same commit.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { parse, serialize } from "./tree.ts";

const here = dirname(fileURLToPath(import.meta.url));
// frontend/src/query -> frontend/src -> frontend -> repo root
const CORPUS = join(here, "../../../tests/core/golden/query_corpus.json");

type Row = { query: string; tree: unknown; canonical: string };
const rows: Row[] = JSON.parse(readFileSync(CORPUS, "utf8")).rows;

/** Fields a TS object literal legitimately OMITS where Pydantic writes the
 *  default. Kept to an explicit list rather than "undefined matches anything
 *  falsy": that blanket rule would also let a missing `have: false` pass, and
 *  `have: false` is the difference between "has this tag" and "does not".
 *
 *  `tol` is the half-width a numeric `=` accepts. A TEXT condition has no such
 *  thing, so `tree.ts` leaves it off and the backend's model defaults it to 0.
 *  Both mean exact; neither is wrong.
 *
 *  `meta_tags` is the same story on a tag condition: with none, the condition
 *  is about the tag it NAMES, and `tree.ts` writes no key at all.
 *
 *  Matched by VALUE, not by identity — `[] === []` is false, so the reference
 *  comparison this used to do would have silently never matched the empty
 *  list. */
const OMITTABLE: Record<string, unknown> = { tol: 0, meta_tags: [] };

/** Compare on the keys the corpus carries, recursively — the point is that the
 *  two agree about the QUERY, not that they serialize identically. */
function sameShape(got: any, want: any, path = ""): void {
  if (Array.isArray(want)) {
    assert.ok(Array.isArray(got), `${path}: expected an array`);
    assert.equal(got.length, want.length, `${path}: length`);
    want.forEach((w, i) => sameShape(got[i], w, `${path}[${i}]`));
    return;
  }
  if (want && typeof want === "object") {
    for (const key of Object.keys(want)) {
      const here = path ? `${path}.${key}` : key;
      if (got?.[key] === undefined && key in OMITTABLE
          && JSON.stringify(want[key]) === JSON.stringify(OMITTABLE[key])) {
        continue;  // see OMITTABLE
      }
      sameShape(got?.[key], want[key], here);
    }
    return;
  }
  assert.deepEqual(got, want, `${path}`);
}

for (const row of rows) {
  test(`parses ${JSON.stringify(row.query)} as the backend does`, () => {
    sameShape(parse(row.query), row.tree);
  });

  test(`serializes ${JSON.stringify(row.query)} as the backend does`, () => {
    assert.equal(serialize(parse(row.query)), row.canonical);
  });
}

test("the corpus is not empty", () => {
  assert.ok(rows.length > 20, `only ${rows.length} rows`);
});
