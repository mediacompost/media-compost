/**
 * A menu closes through `useMenuDismiss`, never through a listener of its own.
 *
 * Twenty-six menus each put a mousedown listener on the window and disagreed
 * on the phase (a row that stops mousedown hid every press from the bubble
 * ones), on arming a tick late, and on Escape (ten did not answer it). One
 * hook, one rule; this holds every menu to it.
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

test("no window mousedown listener outside useMenuDismiss", () => {
  const offenders = walk(SRC)
    .filter((f) => !f.endsWith("shared/useMenuDismiss.ts"))
    .filter((f) => /addEventListener\("mousedown"/.test(readFileSync(f, "utf8")))
    .map((f) => f.slice(SRC.length));
  assert.deepEqual(offenders, [], "close a menu with useMenuDismiss():\n  " + offenders.join("\n  "));
  const users = walk(SRC).filter((f) => /useMenuDismiss\(/.test(readFileSync(f, "utf8"))).length;
  assert.ok(users >= 15, `only ${users} files use useMenuDismiss`);
  const hook = readFileSync(join(SRC, "shared", "useMenuDismiss.ts"), "utf8");
  assert.ok(hook.includes('addEventListener("mousedown", onDown, true)'), "the one listener is on the capture phase");
});
