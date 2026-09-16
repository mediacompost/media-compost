/**
 * A SMALL UPPERCASE LABEL IS `shared/SectionHeading` (or a `shared/Chip`),
 * and the inline `textTransform: "uppercase"` recipes that remain are a
 * stated budget — strict both ways, per file.
 *
 * Sixty-five headings were forty recipes; the five heading style constants
 * derive from the one now and twenty-five inline ones are the component.
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

const EXEMPT = new Set(["shared/SectionHeading.tsx", "shared/Chip.tsx"]);

const BUDGET: Record<string, number> = {
  "app/components/EditorOverlay.tsx": 1,
  "app/components/FilterMenu.tsx": 1,
  "app/components/HistoryView.tsx": 1,
  "app/components/PropertiesPanel.tsx": 1,
  "app/components/TagCsvOverlay.tsx": 1,
  "app/components/TagSetCsvOverlay.tsx": 1,
  "app/components/TagsView.tsx": 1,
  "app/components/VideoEditorOverlay.tsx": 1,
  "app/components/shared/FileChip.tsx": 1,
  "app/components/shared/ItemInfoPanel.tsx": 3,
  "app/components/shared/MediaTracksView.tsx": 1,
  "train/DegradeSection.tsx": 1,
  "train/TrainView.tsx": 2,
};

test("every inline uppercase label is in the budget, and the budget is exact", () => {
  const actual: Record<string, number> = {};
  for (const dir of ["app", "train", "shared", "query"]) {
    for (const p of walk(join(SRC, dir))) {
      const rel = p.slice(SRC.length);
      if (EXEMPT.has(rel)) continue;
      const n = (readFileSync(p, "utf8").match(/textTransform: "uppercase"/g) ?? []).length;
      if (n) actual[rel] = n;
    }
  }
  const problems: string[] = [];
  for (const [f, n] of Object.entries(actual)) {
    const b = BUDGET[f] ?? 0;
    if (n > b) problems.push(`${f}: ${n} inline uppercase labels, budget ${b} — use <SectionHeading> / <Chip>`);
    if (n < b) problems.push(`${f}: ${n} inline uppercase labels, budget ${b} — lower the budget`);
  }
  for (const f of Object.keys(BUDGET)) if (!(f in actual)) problems.push(`${f}: none left — drop it from the budget`);
  assert.deepEqual(problems, [], problems.join("\n"));
});
