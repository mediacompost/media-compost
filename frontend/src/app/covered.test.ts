// WHAT THE LIBRARY GRID STANDS DOWN FOR.
//
// The grid stays mounted under every full-window overlay — deliberately, so
// a page turn keeps its scroll and its selection — which means its page
// queries are still live while nobody can see them. That was measured once
// at six `POST /api/items/query` per edit made in the item window; a TAG
// BATCH session makes an edit per keypress, so the invisible grid re-paged
// as fast as somebody could answer cards, and the page query is a gate of
// two slots that answers 503 when the queue behind it gets deep. Which is
// exactly what "a lot of 503s during a tag batch session" was.

import assert from "node:assert/strict";
import test from "node:test";

import { coveredByWindow } from "./covered.ts";

const IDLE = {
  editorTabs: [] as unknown[], tagSortOpen: false, tagGridOpen: false,
  rateRankingId: null as number | null, quickTagOpen: false,
  quickCaptionOpen: false,
};

test("an idle library is not covered", () => {
  assert.equal(coveredByWindow(IDLE), false);
});

test("every full-window session covers the grid", () => {
  for (const patch of [
    { editorTabs: [1] },
    { tagSortOpen: true },
    { tagGridOpen: true },
    { rateRankingId: 3 },
    { quickTagOpen: true },
    { quickCaptionOpen: true },
  ]) {
    assert.equal(coveredByWindow({ ...IDLE, ...patch }), true,
                 `${JSON.stringify(patch)} should cover the grid`);
  }
});

test("a rating session at ranking zero still covers it", () => {
  // `rateRankingId` is an ID, and 0 is a legitimate one: the test is for
  // null, never for truthiness.
  assert.equal(coveredByWindow({ ...IDLE, rateRankingId: 0 }), true);
});
