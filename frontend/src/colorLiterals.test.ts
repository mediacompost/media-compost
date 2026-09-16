/**
 * A COLOUR IS A TOKEN, and the literals that remain are a stated budget.
 *
 * Every hex and every rgba() in a component file is a colour that follows
 * neither the theme nor the fix when the token moves. The sweep of 2026-09
 * put the ~190 alphas onto the scrim, shadow and on-scrim tokens; what is
 * left is DATA — the grid's band colours, the tag colours, the image
 * adjuster's matrices, the editor's canvas strokes, the storage page's chart
 * palette, the group colour swatches, the annotator's marquee — and each
 * file's count is written down here. Strict in both directions: a file that
 * grows a literal fails, and so does one that loses one without the number
 * moving, so the table stays true.
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

const LITERAL = /#[0-9a-fA-F]{3,8}\b|rgba?\(/g;

/** file → how many colour literals it is allowed, all of them data. */
const BUDGET: Record<string, number> = {
  "app/canvasBlur.ts": 1,
  "app/components/AnnotationOverlay.tsx": 4,
  "app/components/ColorPicker.tsx": 15,
  "app/components/EditorOverlay.tsx": 25,
  "app/components/GroupPropertiesOverlay.tsx": 7,
  "app/components/SettingsStorage.tsx": 8,
  "app/components/VideoEditorOverlay.tsx": 2,
  "app/gridGroups.ts": 12,
  "app/imageAdjust.ts": 2,
};

test("every colour literal in a component is in the budget, and the budget is exact", () => {
  const actual: Record<string, number> = {};
  for (const dir of ["app", "train", "shared", "query"]) {
    for (const p of walk(join(SRC, dir))) {
      const n = (readFileSync(p, "utf8").match(LITERAL) ?? []).length;
      if (n) actual[p.slice(SRC.length)] = n;
    }
  }
  const problems: string[] = [];
  for (const [f, n] of Object.entries(actual)) {
    const b = BUDGET[f] ?? 0;
    if (n > b) problems.push(`${f}: ${n} literals, budget ${b} — use a token from tokens.css`);
    if (n < b) problems.push(`${f}: ${n} literals, budget ${b} — lower the budget`);
  }
  for (const f of Object.keys(BUDGET)) {
    if (!(f in actual)) problems.push(`${f}: no literals left — drop it from the budget`);
  }
  assert.deepEqual(problems, [], problems.join("\n"));
});
