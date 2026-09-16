/**
 * The judging sessions' one history stack.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { sessionStack } from "./app/components/shared/sessionStack.ts";

test("push, peek, pop and size", () => {
  const s = sessionStack<number>();
  assert.equal(s.size, 0);
  assert.equal(s.peek(), undefined);
  s.push(1); s.push(2);
  assert.equal(s.size, 2);
  assert.equal(s.peek(), 2);
  assert.equal(s.pop(), 2);
  assert.deepEqual([...s.steps], [1]);
});

test("drop takes the NEWEST matching step and leaves the rest in order", () => {
  const s = sessionStack<{ k: string; n: number }>();
  s.push({ k: "a", n: 1 }); s.push({ k: "b", n: 2 }); s.push({ k: "a", n: 3 }); s.push({ k: "c", n: 4 });
  assert.deepEqual(s.drop((x) => x.k === "a"), { k: "a", n: 3 });
  assert.deepEqual(s.steps.map((x) => x.n), [1, 2, 4]);
  assert.equal(s.drop((x) => x.k === "z"), undefined);
});

test("clear empties it in place, so a held reference sees the same stack", () => {
  const s = sessionStack<number>();
  const held = s.steps;
  s.push(1); s.clear();
  assert.equal(held.length, 0);
});

test("a session reverts through its stack, never api.revertEvents itself", () => {
  const root = fileURLToPath(new URL(".", import.meta.url));
  for (const f of ["app/components/RateOverlay.tsx", "app/components/TagSortOverlay.tsx",
                   "app/components/TagGridOverlay.tsx", "app/components/TagsView.tsx"]) {
    assert.ok(!/api\.revertEvents\(/.test(readFileSync(root + f, "utf8")),
              `${f}: revert through useSessionUndo / useUndoBar`);
  }
});
