/**
 * Anything portalled to <body> takes its z-index from `shared/layers.ts`.
 *
 * Portalling escapes every clipping ancestor, which is what these popovers
 * want — and it also makes them SIBLINGS of whatever is open, so the z-index
 * is the only thing holding the order. Get it wrong and the failure is the
 * most confusing one this codebase produces: the thing opens, is positioned,
 * is hit-testable by a script, and is completely invisible. It reads as a
 * control that does nothing.
 *
 * It has happened four times, each time because a number was chosen against
 * the layer that existed when the code was written:
 *
 *   - the image editor's two hand-rolled menus at 90/91, like every menu in
 *     the library (which has no such ancestor), under the item window at 300;
 *   - every dialog opened from inside that window, until `Overlay` went from
 *     40 to 500 — "creating a place in the annotator does nothing";
 *   - `ModelDownloadButton`'s menu at 200, under the settings dialog at 500,
 *     so its chevron "stopped opening" while opening it every time;
 *   - the training editor's help popovers and menus at 61, under the same
 *     dialog — and the face hover preview at 200, under the item window.
 *
 * THE LIST USED TO BE WRITTEN BY HAND, and that is the fifth way this breaks.
 * Nine files portalled something and were simply not on it, two of them with
 * a number chosen exactly the way the four above were: `GroupTree`'s context
 * menu at 90 (under the item window, latent only because that window covers
 * the tree it hangs off), and `InPicture` at a bare 1000 — right today, and
 * silently wrong the day `LAYER.popover` moves. So this discovers its own
 * inputs, the way `backdropDismiss.test.ts` and `noRawApiFetch.test.ts` do:
 * every `createPortal` call in the tree is checked, and a file cannot escape
 * by not being mentioned.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { coversWindow, DIM, openingTag, styleBlocks } from "./styleBlocks.ts";

const SRC = fileURLToPath(new URL(".", import.meta.url));
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");

/** The layer constants, read from their own module so this cannot drift. */
function layers(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const m of read("shared/layers.ts").matchAll(/^\s{2}(\w+):\s*(\d+),/gm)) {
    out[m[1]] = Number(m[2]);
  }
  assert.ok(out.modal && out.popover && out.itemWindow,
    "shared/layers.ts should define itemWindow, modal and popover");
  return out;
}

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) sources(p, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

/**
 * The text of one `createPortal(…)` call.
 *
 * Bounded at the container argument every one of these names — `document.body`
 * is the whole point, since that is what makes the thing a sibling of the
 * windows. A big component carries dozens of z-indexes that are NOT portalled
 * (an absolutely-positioned dropdown inside its own panel is layered against
 * its siblings and is nobody's business but that panel's), so the check has to
 * be per CALL rather than per file.
 */
function portalCalls(src: string): string[] {
  const out: string[] = [];
  for (const m of src.matchAll(/createPortal\(/g)) {
    const start = m.index!;
    const end = src.indexOf("document.body", start);
    out.push(src.slice(start, end === -1 ? start + 4000 : end));
  }
  return out;
}

test("every portalled popover takes its layer from shared/layers.ts", () => {
  const known = new Set(Object.keys(layers()));
  const offenders: string[] = [];
  for (const path of sources(SRC)) {
    const rel = path.slice(SRC.length);
    if (rel === "shared/layers.ts") continue;
    const src = readFileSync(path, "utf8");
    for (const call of portalCalls(src)) {
      for (const z of call.matchAll(/zIndex:\s*([^,\n}]+)/g)) {
        const value = z[1].trim();
        // A LEADING number is the bug this file exists for. Arithmetic on a
        // layer is not: `LAYER.popover - 1` is exactly what a backdrop under
        // its own menu wants, so the offset is allowed and only the thing it
        // is measured FROM has to be one of ours.
        const bare = value.replace(/LAYER\.\w+|POPOVER_BACKDROP/g, "L");
        if (/(?:^|[^.\w])\d/.test(bare.replace(/[-+*/\s]\s*\d+\b/g, ""))) {
          offenders.push(`${rel}: zIndex: ${value}`);
          continue;
        }
        // Every name in the expression has to resolve to a layer — directly,
        // or through a local alias (`const MENU_Z = LAYER.popover`, which is
        // how the image editor spells it).
        for (const id of bare.matchAll(/[A-Za-z_$][\w$]*/g)) {
          const name = id[0];
          if (name === "L") continue;
          const decl = new RegExp(
            `(?:const|let)\\s+${name}\\s*=\\s*[^;\\n]*` +
            `(?:LAYER\\.(\\w+)|POPOVER_BACKDROP)`).exec(src);
          if (!decl) {
            offenders.push(`${rel}: zIndex: ${value} — ${name} is not a LAYER`);
          } else if (decl[1] && !known.has(decl[1])) {
            offenders.push(`${rel}: zIndex: ${value} — no LAYER.${decl[1]}`);
          }
        }
        for (const m of value.matchAll(/LAYER\.(\w+)/g)) {
          if (!known.has(m[1])) {
            offenders.push(`${rel}: zIndex: ${value} — no LAYER.${m[1]}`);
          }
        }
      }
    }
  }
  assert.deepEqual(offenders, [],
    "these portal something to <body> with a z-index that is not a LAYER:\n  "
    + offenders.join("\n  ")
    + "\n\nPortalled, the element is a sibling of every window and dialog, so "
    + "a number chosen against today's layout is the bug this file exists "
    + "for. Use LAYER.popover / POPOVER_BACKDROP from shared/layers.ts.");
});

test("the ratchet is looking at something", () => {
  // Non-vacuous: it is a discovery walk, so a broken walk reads as a clean
  // tree. These are the files that portal a popover today.
  const found = sources(SRC).filter((p) =>
    readFileSync(p, "utf8").includes("createPortal("));
  assert.ok(found.length >= 15,
    `only ${found.length} files portal anything — has the walk broken?`);
  for (const must of ["shared/AnchoredDropdown.tsx", "shared/Overlay.tsx"]) {
    assert.ok(found.some((p) => p.endsWith(must)), `${must} not walked`);
  }
});

test("a popover sits above every window and dialog", () => {
  const l = layers();
  assert.ok(l.popover > l.modal, "a popover must clear a dialog's panel");
  assert.ok(l.popover > l.modalConfirm, "…and the confirm it can raise");
  assert.ok(l.popover > l.itemWindow, "…and the item window");
  assert.ok(l.modal > l.itemWindow,
    "a dialog opened from inside the item window must clear it — this one "
    + "cost 'creating a place in the annotator does nothing'");
});

test("the layers above the popovers are the three that mean it", () => {
  // Everything portalled is either a popover or one of these, and each is
  // above the popovers for a reason worth stating rather than a number that
  // happened to be free.
  const l = layers();
  assert.ok(l.dragGhost > l.popover,
    "what is being carried is the topmost thing on screen while it is");
  assert.ok(l.toast > l.dragGhost,
    "the undo bar is the way back from a deletion; nothing may cover it");
  assert.ok(l.quickTag > l.toast,
    "the quick-tag screen is raised over everything, the toast included");
});

test("every dimmed full-window sheet stands on a named layer", () => {
  // Portalled or not: a sheet that covers the window is ordered against
  // every other one by its z-index alone, and a number chosen against
  // today's neighbours is the bug this file exists for. The item window
  // was 300 by hand, the lightbox 60, the video render 120 and the job
  // log 200 — each right until something moved.
  const known = new Set(Object.keys(layers()));
  const offenders: string[] = [];
  for (const path of sources(SRC)) {
    const rel = path.slice(SRC.length);
    if (rel === "shared/layers.ts") continue;
    const src = readFileSync(path, "utf8");
    for (const b of styleBlocks(src)) {
      if (!coversWindow(b.text) || !DIM.test(b.text)) continue;
      const z = /zIndex:\s*([^,\n}]+)/.exec(b.text);
      if (!z) { offenders.push(`${rel}: a dim sheet with no zIndex`); continue; }
      const value = z[1].trim();
      const m = /^(?:LAYER\.(\w+)|POPOVER_BACKDROP)$/.exec(value);
      if (!m) offenders.push(`${rel}: zIndex: ${value} is not a LAYER`);
      else if (m[1] && !known.has(m[1])) offenders.push(`${rel}: no LAYER.${m[1]}`);
    }
  }
  assert.deepEqual(offenders, [],
    "these paint a dim full-window sheet off the layer table:\n  " + offenders.join("\n  "));
  const found = sources(SRC).filter((p) =>
    styleBlocks(readFileSync(p, "utf8")).some((b) => coversWindow(b.text) && DIM.test(b.text)));
  assert.ok(found.length >= 6, `only ${found.length} files paint a dim sheet — has the walk broken?`);
});

test("no menu puts a click-catcher behind itself", () => {
  // An invisible full-window element with a press handler is a hand-rolled
  // "close on a click outside": fourteen menus had one, each a second way
  // for a menu to close beside `useMenuDismiss` — and each one a sheet over
  // the page that no other menu knew about. The hook is the one rule.
  const offenders: string[] = [];
  for (const path of sources(SRC)) {
    const rel = path.slice(SRC.length);
    const src = readFileSync(path, "utf8");
    for (const b of styleBlocks(src)) {
      if (!coversWindow(b.text) || /background/.test(b.text)) continue;
      const tag = openingTag(src, b.at);
      if (/on(?:Click|MouseDown)=/.test(tag)) offenders.push(rel);
    }
  }
  assert.deepEqual(offenders, [],
    "these put a click-catcher behind a menu — use useMenuDismiss():\n  " + offenders.join("\n  "));
});
