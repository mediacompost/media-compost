/**
 * A WHEEL HANDLER THAT MUST REFUSE THE BROWSER GOES THROUGH `useWheel`.
 *
 * React registers `wheel` at the root container PASSIVELY, so
 * `e.preventDefault()` inside an `onWheel` prop is a no-op — and a no-op that
 * LOOKS like the rule being followed, which is how the timeline came to zoom
 * itself and let Firefox zoom the whole page on top of it for as long as the
 * scale has existed. The app's zoomable surfaces (both editors, the video
 * stage, the preview, the two timelines) bind the wheel natively instead, via
 * `app/useWheel.ts`, where `{ passive: false }` makes the refusal stick.
 *
 * A ratchet because nothing here can see the failure: the zoom works either
 * way, and what is wrong happens in the browser's chrome — the page sits at
 * 110% with nothing on screen saying so. Writing `onWheel={…}` back onto an
 * element is one line, reads as ordinary React, and quietly hands the gesture
 * back.
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
    else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

test("nothing takes the wheel through React's passive prop", () => {
  const offenders: string[] = [];
  for (const file of walk(SRC)) {
    const rel = file.slice(SRC.length);
    const text = readFileSync(file, "utf8");
    // The PROP, wherever it is set — `onWheel={…}` on an element and
    // `onWheel:` in a props object both end up as the same passive listener.
    if (/\bonWheel\s*[={:]/.test(text) && rel !== "app/useWheel.ts") {
      offenders.push(rel);
    }
  }
  assert.deepEqual(
    offenders, [],
    "these hand the wheel to React, whose listener is passive — a " +
      "`preventDefault` there is ignored and the browser zooms the page over " +
      "whatever the handler just did. Bind it with `useWheel` instead:\n  " +
      offenders.join("\n  "),
  );
});

test("every wheel zoom refuses the page zoom", () => {
  // Each surface that zooms on a wheel: the two pixel editors, the video
  // stage, the preview (which the grid's pinned caption view also mounts) and
  // the timelines' shared scale. A ctrl+wheel over any of them is meant for
  // the picture — on a Mac a trackpad pinch arrives as one — so each calls
  // `preventDefault` on the path that takes it.
  const FILES = [
    "app/components/EditorOverlay.tsx",
    "app/components/AnnotationOverlay.tsx",
    "app/components/VideoEditorOverlay.tsx",
    "app/components/QuickLook.tsx",
    "app/components/shared/Timeline.tsx",
  ];
  for (const rel of FILES) {
    const text = readFileSync(join(SRC, rel), "utf8");
    assert.ok(
      /\buseWheel\s*\(/.test(text),
      `${rel} zooms on a wheel and must bind it with useWheel`,
    );
    const body = text.slice(text.indexOf("useWheel("));
    assert.ok(
      /preventDefault\(\)/.test(body),
      `${rel}'s wheel handler must preventDefault, or the browser zooms the ` +
        "page on top of the zoom it just did",
    );
  }
});
