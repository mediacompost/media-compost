// Which stat bars change colour, and which deliberately never do.
import test from "node:test";
import assert from "node:assert/strict";
import { barColor } from "./gpuStats.ts";

test("pressure metrics warn and then alarm as they approach the ceiling", () => {
  for (const key of ["vram", "mem", "disk", "temp", "power"]) {
    assert.equal(barColor(key, 10), "var(--accent)", key);
    assert.equal(barColor(key, 79), "var(--accent)", key);
    assert.equal(barColor(key, 85), "var(--yellow)", key);
    assert.equal(barColor(key, 97), "var(--red)", key);
  }
});

test("a busy GPU and a spinning fan are NOT warnings", () => {
  // The whole point of a training box is a card at 100%, and a fan at 100%
  // is the cooling working rather than failing. Colouring these would paint
  // a healthy run red and teach people to ignore the colour everywhere else.
  assert.equal(barColor("util", 100), "var(--accent)");
  assert.equal(barColor("fan", 100), "var(--accent)");
});

test("each level has ONE boundary, so a steady value cannot flicker", () => {
  assert.equal(barColor("temp", 80), "var(--yellow)");
  assert.equal(barColor("temp", 92), "var(--red)");
});
