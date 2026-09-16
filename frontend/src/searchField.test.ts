/**
 * A FIELD WITH A MAGNIFIER IS `shared/SearchField`.
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
    else if (/\.tsx$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

test("no list draws its own magnifier beside an input", () => {
  const offenders: string[] = [];
  for (const dir of ["app", "train", "shared", "query"]) {
    for (const p of walk(join(SRC, dir))) {
      const rel = p.slice(SRC.length);
      // The query bar (a builder behind a magnifier) and the caption
      // editor's find/replace are fields of their own, not list searches.
      if (rel === "shared/SearchField.tsx" || rel === "query/QueryBuilder.tsx"
          || rel === "app/components/CaptionEditor.tsx") continue;
      const src = readFileSync(p, "utf8");
      if (/name="search"[\s\S]{0,400}<input/.test(src) || /className="msym"[\s\S]{0,200}>\s*search\s*</.test(src)) offenders.push(rel);
    }
  }
  assert.deepEqual(offenders, [], "use <SearchField>: " + offenders.join(", "));
});
