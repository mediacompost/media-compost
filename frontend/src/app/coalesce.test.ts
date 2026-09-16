// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeCoalescer } from "./coalesce.ts";

/** Deterministic clock: setTimeout/clearTimeout/now driven by advance(). */
class FakeClock {
  t = 0;
  private timers: { at: number; fn: () => void; id: number }[] = [];
  private nextId = 1;

  setTimeout = (fn: () => void, ms: number): unknown => {
    const id = this.nextId++;
    this.timers.push({ at: this.t + ms, fn, id });
    return id;
  };
  clearTimeout = (id: unknown): void => {
    this.timers = this.timers.filter((x) => x.id !== id);
  };
  now = (): number => this.t;

  /** Advance time, running due timers in order (a timer may schedule more). */
  advance(ms: number): void {
    const end = this.t + ms;
    for (;;) {
      const due = this.timers
        .filter((x) => x.at <= end)
        .sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      this.t = due.at;
      this.timers = this.timers.filter((x) => x.id !== due.id);
      due.fn();
    }
    this.t = end;
  }
}

function harness(opts = { wait: 400, maxWait: 2000 }) {
  const clock = new FakeClock();
  let fired = 0;
  const co = makeCoalescer(() => fired++, opts, clock);
  return { clock, co, fires: () => fired };
}

test("a burst of calls fires exactly once, `wait` after the last call", () => {
  const { clock, co, fires } = harness();
  co.call();
  clock.advance(100);
  co.call();
  clock.advance(100);
  co.call();
  assert.equal(fires(), 0);
  // 399ms after the last call: still quiet.
  clock.advance(399);
  assert.equal(fires(), 0);
  clock.advance(1);
  assert.equal(fires(), 1);
  // Nothing further pending.
  clock.advance(5000);
  assert.equal(fires(), 1);
});

test("continuous calls cannot postpone past maxWait", () => {
  const clock = new FakeClock();
  const fireTimes: number[] = [];
  const co = makeCoalescer(() => fireTimes.push(clock.t), { wait: 400, maxWait: 2000 }, clock);
  // Call every 100ms — trailing debounce alone would never fire.
  for (let i = 0; i < 30; i++) {
    co.call();
    clock.advance(100);
  }
  // First fire pinned to the burst's maxWait deadline (2000ms after the FIRST
  // call), not 400ms after whichever call happened to be last.
  assert.equal(fireTimes[0], 2000);
  // The calls after that fire form a second burst, which settles `wait` after
  // its last call (t=2900).
  clock.advance(400);
  assert.deepEqual(fireTimes, [2000, 3300]);
});

test("cancel drops the pending fire", () => {
  const { clock, co, fires } = harness();
  co.call();
  co.cancel();
  clock.advance(10_000);
  assert.equal(fires(), 0);
  // cancel also resets the burst: a fresh call gets the full maxWait again.
  co.call();
  clock.advance(400);
  assert.equal(fires(), 1);
});

test("flush fires a pending call immediately, and is a no-op when idle", () => {
  const { clock, co, fires } = harness();
  co.flush();
  assert.equal(fires(), 0);
  co.call();
  co.flush();
  assert.equal(fires(), 1);
  // The flushed timer is gone — nothing double-fires later.
  clock.advance(10_000);
  assert.equal(fires(), 1);
});

test("after a fire, the next call starts a fresh burst with a fresh deadline", () => {
  const { clock, co, fires } = harness({ wait: 400, maxWait: 2000 });
  co.call();
  clock.advance(400);
  assert.equal(fires(), 1);
  clock.advance(5000);
  co.call();
  assert.equal(fires(), 1);
  clock.advance(400);
  assert.equal(fires(), 2);
});
