// A DIMMED BACKDROP DISMISSES ON BOTH ENDS, and this is the ratchet.
//
// The obvious spelling — `onClick={onClose}` on the dim, `stopPropagation` on
// the panel — closes a dialog on a gesture that never meant to: press inside
// a field, drag past the panel's edge to select its text, release. The click
// is delivered to the nearest common ancestor of the two, which IS the
// backdrop. It threw away whatever had been typed, and it was written that
// way in nine files, including `shared/Overlay` — the chrome every editor in
// the app is built on.
//
// So: a file that paints a dim full-window backdrop must import
// `useBackdropDismiss`. Read off the source, because that is where the
// mistake is made, and the failure is invisible until somebody drags.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { coversWindow, DIM, openingTag, styleBlocks } from "./styleBlocks.ts";

const SRC = new URL("./", import.meta.url).pathname;

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) sources(p, out);
    else if (name.endsWith(".tsx")) out.push(p);
  }
  return out;
}

test("every dimmed backdrop dismisses through the shared rule", () => {
  // PER BLOCK, not per file: a file that imports the hook for one sheet
  // and paints a second one with a bare `onClick` is the mistake again.
  // The sheet's element must spread a value the file declared with
  // `useBackdropDismiss(`, or say `data-dismiss-anywhere` — the viewers
  // (Quick Look, the face-in-picture preview) and the tag-grid session,
  // which close on a press anywhere by design: no field, no selectable
  // body text, their inner content stopping its own press.
  const offenders: string[] = [];
  let checked = 0;
  for (const p of sources(SRC)) {
    const name = p.slice(p.lastIndexOf("/") + 1);
    const src = readFileSync(p, "utf8");
    const spreads = new Set(
      [...src.matchAll(/const\s+(\w+)\s*=\s*useBackdropDismiss\(/g)].map((m) => m[1]));
    for (const b of styleBlocks(src)) {
      if (!coversWindow(b.text) || !DIM.test(b.text)) continue;
      checked++;
      const tag = openingTag(src, b.at);
      if (tag.includes("data-dismiss-anywhere")) continue;
      const ok = [...tag.matchAll(/\{\.\.\.(\w+)\}/g)].some((m) => spreads.has(m[1]));
      if (!ok) offenders.push(name);
    }
  }
  assert.deepEqual(offenders, [],
    "these paint a dim backdrop without spreading useBackdropDismiss on it: "
    + offenders.join(", "));
  assert.ok(checked >= 6, `only ${checked} dim sheets found — has the walk broken?`);
});
