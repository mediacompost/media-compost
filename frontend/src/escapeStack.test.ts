/**
 * The escape stack: Escape goes to whatever opened last, and nothing else.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { pushEscape, dispatchEscape, escapeDepth } from "./shared/escapeStack.ts";

const press = (key = "Escape") => {
  const ev = { key, target: null, prevented: false, stopped: false,
    preventDefault() { this.prevented = true; },
    stopPropagation() { this.stopped = true; } };
  return ev;
};

test("the top entry alone hears the key, and popping restores the one below", () => {
  const hits: string[] = [];
  const popA = pushEscape({ handler: () => hits.push("a"), overFields: false });
  const popB = pushEscape({ handler: () => hits.push("b"), overFields: false });
  const e = press();
  assert.equal(dispatchEscape(e), true);
  assert.deepEqual(hits, ["b"]);
  assert.ok(e.prevented && e.stopped, "a taken Escape is consumed");
  popB();
  assert.equal(dispatchEscape(press()), true);
  assert.deepEqual(hits, ["b", "a"]);
  popA();
  assert.equal(dispatchEscape(press()), false, "an empty stack lets the key through");
  assert.equal(escapeDepth(), 0);
});

test("an entry popped out of order leaves the others in place", () => {
  const hits: string[] = [];
  const popA = pushEscape({ handler: () => hits.push("a"), overFields: false });
  const popB = pushEscape({ handler: () => hits.push("b"), overFields: false });
  popA();
  popA(); // idempotent
  dispatchEscape(press());
  assert.deepEqual(hits, ["b"]);
  popB();
  assert.equal(escapeDepth(), 0);
});

test("any other key is not the stack's", () => {
  const pop = pushEscape({ handler: () => assert.fail("must not fire"), overFields: false });
  const e = press("Enter");
  assert.equal(dispatchEscape(e), false);
  assert.ok(!e.prevented);
  pop();
});

test("an owner that does not want the key over a field lets it through to the field", () => {
  const hits: string[] = [];
  const popA = pushEscape({ handler: () => hits.push("a"), overFields: false });
  assert.equal(dispatchEscape(press(), true), false, "declined while typing");
  const popB = pushEscape({ handler: () => hits.push("b"), overFields: true });
  assert.equal(dispatchEscape(press(), true), true, "an overFields owner takes it anyway");
  assert.deepEqual(hits, ["b"]);
  popB(); popA();
});
