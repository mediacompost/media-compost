/**
 * "Are you sure?" is asked through the one confirm sheet.
 *
 * Forty-three sites asked with the browser's own `window.confirm`: a native
 * dialog in the wrong font, the wrong theme, no danger colour, no count it
 * could not say with a "\n\n", and no Escape rule it shared with anything.
 * `shared/confirm.ts`'s `confirm()`/`ask()` is the door now, and this holds
 * it shut — silently, like every ratchet here, because a `window.confirm`
 * works the day it is written.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL(".", import.meta.url));

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

test("nothing asks with window.confirm", () => {
  const offenders: string[] = [];
  for (const file of walk(SRC)) {
    const text = readFileSync(file, "utf8");
    if (/window\.confirm\(|\bconfirm\(\s*["'`]/.test(text)) offenders.push(file.slice(SRC.length));
  }
  assert.deepEqual(offenders, [], "use confirm()/ask() from shared/confirm.ts:\n  " + offenders.join("\n  "));
  // Non-vacuous: the sheet's door is in use.
  const users = walk(SRC).filter((f) => /from "[./]*shared\/ConfirmModal"/.test(readFileSync(f, "utf8"))).length;
  assert.ok(users >= 10, `only ${users} files use the confirm sheet`);
});
