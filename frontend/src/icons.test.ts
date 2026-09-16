/**
 * A GLYPH IS `<Icon>`, A RECORD'S GLYPH IS `RECORD_ICON`, A ⋯ IS HORIZONTAL,
 * AND + AND − ARE DRAWN.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

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

test("the symbol font's class is written once, in Icon", () => {
  const offenders = sources().filter((s) => s.rel !== "shared/Icon.tsx" && /className=\{?"msym/.test(s.text)).map((s) => s.rel);
  assert.deepEqual(offenders, [], "draw the glyph with <Icon>: " + offenders.join(", "));
});

test("a record's glyph is read off RECORD_ICON, never spelled", () => {
  const offenders: string[] = [];
  for (const { rel, text } of sources()) {
    if (rel === "shared/metaEnums.ts") continue;
    for (const m of text.matchAll(/(?:icon: |icon=|name=|mark\(|quiet\()"(person|location_on)"/g)) offenders.push(`${rel}: ${m[0]}`);
  }
  assert.deepEqual(offenders, [], offenders.join("\n"));
});

test("a ⋯ is more_horiz; nothing draws more_vert", () => {
  const offenders = sources().filter((s) => /"more_vert"/.test(s.text)).map((s) => s.rel);
  assert.deepEqual(offenders, [], offenders.join(", "));
});

test("+ and − are <PlusMinus>, never typed into a button", () => {
  const offenders = sources().filter((s) => s.rel !== "shared/PlusMinus.tsx" && /<button[^>]*>\s*[+−]\s*<\/button>|>[+−]<\/button>/.test(s.text)).map((s) => s.rel);
  assert.deepEqual(offenders, [], offenders.join(", "));
});
