/**
 * A window-level shortcut stands down while something is over the page.
 *
 * The grid, the group tree, the tags view, the properties panel and Quick Look
 * register their keys ONCE on the window, so they go on hearing every
 * keystroke whatever is on top of them. Each used to ask its own hand-written
 * list of what might be — and every one of those lists was missing the
 * DIALOGS, so with the import overlay open Space still opened the preview
 * behind it, Delete still trashed the selection, and the group tree's Delete
 * still deleted groups.
 *
 * Two rules, because the list drifted in two different ways: one predicate has
 * to know every way something can be over the page, and no handler may go back
 * to naming them itself.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL(".", import.meta.url));
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) sources(p, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

/** The `OVER_PAGE` table — the one list of ways something can be over the
 *  page, which both `modalIsOpen` and `overPageExcept` derive from. */
function composite(): string {
  const store = read("app/store.ts");
  const at = store.indexOf("export const OVER_PAGE = {");
  assert.ok(at > 0, "app/store.ts should export the OVER_PAGE table");
  return store.slice(at, store.indexOf("};", at));
}

test("the OVER_PAGE table knows every way something can be over the page", () => {
  const store = read("app/store.ts");
  const body = composite();
  // Discovered, not listed: every `xIsOpen` the store exports is a way for
  // something to be on top, so a new overlay that adds one and forgets the
  // composite fails here rather than silently letting the page keep its keys.
  const flags = [...store.matchAll(/export const (\w+IsOpen)\b/g)]
    .map((m) => m[1])
    .filter((n) => n !== "modalIsOpen");
  assert.ok(flags.length >= 5, `only found ${flags.join(", ")}`);
  const missing = flags.filter((n) => !body.includes(n));
  assert.deepEqual(missing, [], "the OVER_PAGE table does not list these");
  // …and the DIALOGS, which are not in the store at all: most are local
  // component state, so `Overlay` counts its own mounts and that count is the
  // only thing that sees all of them.
  assert.ok(body.includes("overlayIsOpen"),
    "the table must ask `Overlay` whether a dialog is up");
  // Both questions are the table's, not a second list.
  assert.match(store, /export const modalIsOpen = \(\): boolean => OVER\.any\(\);/);
  assert.match(store, /export const overPageExcept = OVER\.except;/);
});

test("an overlay's own opener asks overPageExcept, never a tuple of flags", () => {
  // The three keyboard overlays each wrote the list of what they may not
  // open over, and T's and Q's never learned that C exists. Two flags in
  // one condition is a tuple starting again.
  const offenders: string[] = [];
  for (const path of sources(join(SRC, "app"))) {
    const rel = path.slice(SRC.length);
    if (rel === "app/store.ts") continue;
    const src = readFileSync(path, "utf8");
    for (const m of src.matchAll(/if \(([^;]*?)\)\s*return;/g)) {
      const flags = m[1].match(/\b\w+IsOpen\(\)/g) ?? [];
      if (new Set(flags).size >= 2) offenders.push(`${rel}: ${m[1].trim()}`);
    }
  }
  assert.deepEqual(offenders, [],
    "compose the guard from the table (overPageExcept(...)) instead:\n  "
    + offenders.join("\n  "));
  for (const f of ["app/components/QuickTagOverlay.tsx",
                   "app/components/QuickCaptionOverlay.tsx",
                   "app/components/QuickAssignOverlay.tsx"]) {
    assert.ok(read(f).includes("overPageExcept("), `${f} lost its guard`);
  }
});

test("a page handler never reads an overlay's flag off the store itself", () => {
  // The grid's arrows asked `rateRankingId` by hand and so stood down for
  // the rating session and nothing else — a tag batch's digits moved the
  // selection under the dim. `modalIsOpen()` is the question.
  const offenders: string[] = [];
  for (const path of sources(join(SRC, "app/components"))) {
    const rel = path.slice(SRC.length);
    // A session's OWN handler asks whether it is open; that is not a guard.
    if (/(RateOverlay|TagSortOverlay|TagGridOverlay)\.tsx$/.test(rel)) continue;
    const src = readFileSync(path, "utf8");
    for (const m of src.matchAll(
        /useUI\.getState\(\)\.(rateRankingId|tagSortOpen|tagGridOpen|quickTagOpen|quickCaptionOpen|qaOverlay)\b/g)) {
      offenders.push(`${rel}: ${m[0]}`);
    }
  }
  assert.deepEqual(offenders, [], "ask modalIsOpen() / overPageExcept():\n  "
    + offenders.join("\n  "));
});

test("no key handler names the overlays itself any more", () => {
  // `itemWindowIsOpen()` was the idiom every page-level guard was written
  // with, and copying it is how the next one would be written short. The
  // three call sites left are the full-window overlays' OWN guards, which
  // cannot use the composite (it would see them) — and they must still ask
  // about dialogs.
  const offenders: string[] = [];
  for (const path of sources(join(SRC, "app"))) {
    const rel = path.slice(SRC.length);
    if (rel === "app/store.ts") continue;
    const src = readFileSync(path, "utf8");
    for (const m of src.matchAll(/if \(([^)]*itemWindowIsOpen\(\)[^;]*)\)/g)) {
      if (!m[1].includes("overlayIsOpen()")) offenders.push(`${rel}: ${m[1].trim()}`);
    }
  }
  assert.deepEqual(offenders, [],
    "these guard on the item window without asking about dialogs — use "
    + "`modalIsOpen()` for a page handler, or add `overlayIsOpen()` for an "
    + "overlay's own:\n  " + offenders.join("\n  "));
});

test("the page's own handlers use the composite", () => {
  // Non-vacuous: these are the five that hear the keyboard whatever is on
  // screen. A sixth would be caught by the rule above only if it copied the
  // old idiom, so these are named — losing the guard from one of them is the
  // regression this file exists for.
  for (const f of ["app/components/ItemGrid.tsx",
                   "app/components/GroupTree.tsx",
                   // The Tags tab's own key handler went with the face
                   // strips it served: Space previews the picked crops, and
                   // the crops are the Faces tab's now.
                   "app/components/FacesView.tsx",
                   "app/components/QuickLook.tsx",
                   "app/components/PropertiesPanel.tsx"]) {
    assert.ok(read(f).includes("modalIsOpen()"), `${f} lost its guard`);
  }
});

test("'is somebody typing' is asked of isTypingTarget, never spelled out", () => {
  // Seventeen handlers each wrote `el.tagName === "INPUT" || …` by hand and
  // nine of them forgot SELECT: W stood down over a focused dropdown, ⌘A on
  // the same grid did not. One predicate in shared/typingTarget.ts; a handler
  // that spells the test out again is a handler that will drift again.
  const offenders: string[] = [];
  for (const path of sources(SRC)) {
    const rel = path.slice(SRC.length);
    if (rel === "shared/typingTarget.ts") continue;
    if (/tagName === "INPUT"/.test(readFileSync(path, "utf8"))) offenders.push(rel);
  }
  assert.deepEqual(offenders, [], "use isTypingTarget(e):\n  " + offenders.join("\n  "));
  const one = read("shared/typingTarget.ts");
  assert.ok(one.includes('"SELECT"'), "the one predicate must include SELECT");
});

test("Escape is arbitrated by the escape stack, never by whoever listened first", () => {
  // Thirteen surfaces each put their own Escape listener on the window and
  // which one won depended on registration order and on which propagation
  // trick had been copied. `useEscape` (shared/useEscape.ts) puts them on
  // one stack: the thing opened last answers. What is left with a window
  // listener that names Escape is a fixed list, each for a stated reason.
  const ALLOWED = new Set([
    "shared/escapeStack.ts",
    // A list's "Escape clears the selection" acts only while the stack is
    // EMPTY (`escapeDepth() === 0`) — it defers to the stack rather than
    // sitting in it, since a page may hold several such lists and the key
    // must clear all of them, not the last mounted.
    "shared/escapeClears.ts",
    // The item window's halves: Escape is a CASCADE there (cancel the
    // polygon, then the float, then the crop, then the selection, then
    // close), which is one handler by design.
    "app/components/AnnotationOverlay.tsx",
    "app/components/EditorOverlay.tsx",
    "app/components/VideoEditorOverlay.tsx",
    // Q: one handler owns opening, closing and the digits.
    "app/components/QuickAssignOverlay.tsx",
  ]);
  const offenders: string[] = [];
  for (const path of sources(SRC)) {
    const rel = path.slice(SRC.length);
    if (ALLOWED.has(rel)) continue;
    const src = readFileSync(path, "utf8");
    for (const m of src.matchAll(/addEventListener\("keydown",\s*(\w+)/g)) {
      const name = m[1];
      const def = src.indexOf(`const ${name} = (`);
      if (def < 0) continue;
      const open = src.indexOf("{", src.indexOf("=>", def));
      let depth = 0, i = open;
      for (; i < src.length; i++) {
        if (src[i] === "{") depth++;
        else if (src[i] === "}" && --depth === 0) break;
      }
      if (src.slice(open, i).includes('"Escape"')) offenders.push(`${rel}: ${name}`);
    }
  }
  assert.deepEqual(offenders, [],
    "handle Escape with useEscape() so the stack decides who owns it:\n  " + offenders.join("\n  "));
  // Non-vacuous: the hook is what the migrated surfaces use.
  // Fewer than there were: the sheets that used to call it themselves are
  // `Overlay`s now, and `Overlay` calls it once for all of them.
  const users = sources(SRC).filter((p) => /useEscape\(/.test(readFileSync(p, "utf8"))).length;
  assert.ok(users >= 6, `only ${users} files use useEscape`);
});
