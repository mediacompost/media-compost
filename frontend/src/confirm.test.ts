/** The confirm store: one question at a time, answered the way it was asked. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { ask, confirm, pending, settle } from "./shared/confirm.ts";

test("ask resolves with the answer pressed, and null for Cancel", async () => {
  const p1 = ask({ title: "Delete?", answer: { label: "Delete", danger: true } });
  assert.equal(pending()?.spec.title, "Delete?");
  settle(pending()!, "answer");
  assert.equal(await p1, "answer");
  const p2 = ask({ title: "Close?", answer: { label: "Close all" }, plain: { label: "Close tab" } });
  settle(pending()!, "plain");
  assert.equal(await p2, "plain");
  const p3 = confirm({ title: "Sure?", answer: { label: "Yes" } });
  settle(pending()!, null);
  assert.equal(await p3, false);
  assert.equal(pending(), null);
});

test("a second question waits its turn rather than replacing the first", async () => {
  const a = ask({ title: "A", answer: { label: "a" } });
  const b = ask({ title: "B", answer: { label: "b" } });
  assert.equal(pending()?.spec.title, "A");
  settle(pending()!, "answer");
  assert.equal(pending()?.spec.title, "B");
  settle(pending()!, null);
  assert.deepEqual(await Promise.all([a, b]), ["answer", null]);
});

test("settling a question twice is harmless", async () => {
  const p = ask({ title: "A", answer: { label: "a" } });
  const q = pending()!;
  settle(q, "answer");
  settle(q, null);
  assert.equal(await p, "answer");
  assert.equal(pending(), null);
});
