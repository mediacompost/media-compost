/** The session body rule — see `sessionBody.ts` for why it exists at all. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { sessionBody } from "./sessionBody.ts";

test("a session that has not heard back yet is LOADING, not exhausted", () => {
  // The state every session is in the moment Start is pressed: nothing
  // queued, no figure for the pool, the first reply still on its way.
  assert.equal(sessionBody({ loading: true, failed: false, queued: 0 }),
               "loading");
});

test("a failed fetch is an ERROR, never an empty summary", () => {
  assert.equal(sessionBody({ loading: false, failed: true, queued: 0 }),
               "error");
});

test("a picture on screen is the CARD whatever is in flight", () => {
  assert.equal(sessionBody({ loading: true, failed: false, queued: 3 }),
               "card");
  // A background refetch that failed leaves the picture on screen; the
  // failure shows when the queue runs dry.
  assert.equal(sessionBody({ loading: false, failed: true, queued: 1 }),
               "card");
});

test("exhausted is what is LEFT: nothing queued, in flight or failed", () => {
  assert.equal(sessionBody({ loading: false, failed: false, queued: 0 }),
               "exhausted");
});

test("a retry after a failure reads as loading again", () => {
  // The overlay clears `failed` when it asks again, so the spinner comes
  // back rather than the error sitting under it.
  assert.equal(sessionBody({ loading: true, failed: false, queued: 0 }),
               "loading");
});
