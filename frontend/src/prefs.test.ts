/**
 * EVERY PERSISTED KEY IS REGISTERED, AND `localStorage` IS TOUCHED ONCE.
 *
 * `app/prefs.ts` and `train/prefs.ts` are the index of every `mc.…` key
 * the app writes; `shared/storage.ts` is the one try/catch around the
 * browser's store, and the typed makers there say what a key holds.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { boolPref, jsonPref, numPref, strPref } from "./shared/storage.ts";

const SRC = fileURLToPath(new URL(".", import.meta.url));
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "locales") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}
const sources = () => ["app", "train", "shared", "query"].flatMap((d) => walk(join(SRC, d)))
  .map((p) => ({ rel: p.slice(SRC.length), text: readFileSync(p, "utf8") }));
const keysIn = (text: string) => [...text.matchAll(/"(mc\.[A-Za-z0-9_.-]+)"/g)].map((m) => m[1]);

test("every mc. key in the source is in one registry, and only one", () => {
  const app = keysIn(readFileSync(join(SRC, "app", "prefs.ts"), "utf8"));
  const train = keysIn(readFileSync(join(SRC, "train", "prefs.ts"), "utf8"));
  const both = app.filter((k) => train.includes(k));
  assert.deepEqual(both, [], "a key in both registries");
  const dup = (list: string[]) => list.filter((k, i) => list.indexOf(k) !== i);
  assert.deepEqual(dup(app), [], "a key twice in app/prefs.ts");
  assert.deepEqual(dup(train), [], "a key twice in train/prefs.ts");
  const registered = new Set([...app, ...train, "mc.lang"]);
  const prefixes = [...registered].filter((k) => k.endsWith("."));
  const missing: string[] = [];
  for (const { rel, text } of sources()) {
    if (rel === "app/prefs.ts" || rel === "train/prefs.ts") continue;
    for (const k of keysIn(text)) {
      if (registered.has(k) || prefixes.some((p) => k.startsWith(p))) continue;
      missing.push(`${rel}: ${k}`);
    }
  }
  assert.deepEqual([...new Set(missing)], [], "register the key in app/prefs.ts or train/prefs.ts");
  assert.ok(app.length > 40 && train.length > 5);
});

test("localStorage is read and written in shared/storage.ts alone", () => {
  const offenders = sources().filter((s) => s.rel !== "shared/storage.ts" && /\blocalStorage\./.test(s.text)).map((s) => s.rel);
  assert.deepEqual(offenders, [], "go through storage / a Pref");
});

function fakeStore() {
  const m = new Map<string, string>();
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => { m.set(k, String(v)); },
    removeItem: (k: string) => { m.delete(k); },
  };
  return m;
}

test("numPref clamps, rounds, and answers the default for garbage", () => {
  const m = fakeStore();
  const p = numPref("mc.test.n", { def: 10, min: 5, max: 20 });
  assert.equal(p.read(), 10);
  m.set("mc.test.n", "abc"); assert.equal(p.read(), 10);
  m.set("mc.test.n", "99"); assert.equal(p.read(), 10, "out of range reads as the default");
  p.write(99.6); assert.equal(m.get("mc.test.n"), "20");
  p.write(7.4); assert.equal(p.read(), 7);
});

test("boolPref is 1/0, and an inverted key keeps its old meaning", () => {
  const m = fakeStore();
  const p = boolPref("mc.test.b", true);
  assert.equal(p.read(), true);
  p.write(false); assert.equal(m.get("mc.test.b"), "0"); assert.equal(p.read(), false);
  const inv = boolPref("mc.test.i", true, { inverted: true });
  m.set("mc.test.i", "0"); assert.equal(inv.read(), false, "\"0\" is shut");
  inv.write(true); assert.equal(m.get("mc.test.i"), "0", "on is written the way it was always read");
  inv.write(false); assert.equal(m.get("mc.test.i"), "1");
});

test("strPref refuses a value off its list; jsonPref refuses a shape its guard does", () => {
  const m = fakeStore();
  const s = strPref("mc.test.s", "a", ["a", "b"] as const);
  m.set("mc.test.s", "zzz"); assert.equal(s.read(), "a");
  m.set("mc.test.s", "b"); assert.equal(s.read(), "b");
  const j = jsonPref<number[]>("mc.test.j", [], (v): v is number[] => Array.isArray(v) && v.every((x) => typeof x === "number"));
  m.set("mc.test.j", "{bad"); assert.deepEqual(j.read(), []);
  m.set("mc.test.j", "[1, \"x\"]"); assert.deepEqual(j.read(), []);
  j.write([1, 2]); assert.deepEqual(j.read(), [1, 2]);
});

test("storage never throws without a store", () => {
  delete (globalThis as { localStorage?: unknown }).localStorage;
  assert.equal(numPref("mc.test.n", { def: 3 }).read(), 3);
  assert.doesNotThrow(() => boolPref("mc.test.b", false).write(true));
});
