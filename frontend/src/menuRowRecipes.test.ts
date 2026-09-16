/**
 * A ROW IN A MENU OR A PICKER IS `shared/MenuRow`, and the inline
 * `padding: "6px 9px"`-family recipes that remain are a stated budget,
 * strict both ways.
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

const EXEMPT = new Set(["shared/MenuRow.tsx"]);
const RECIPE = /padding: "[567]px (?:8|9|10)px"/g;

const BUDGET: Record<string, number> = {
  "app/components/AnnotationOverlay.tsx": 2,
  "app/components/EditorOverlay.tsx": 3,
  "app/components/EmbedModelPicker.tsx": 2,
  "app/components/EstimateOverlay.tsx": 3,
  "app/components/FacesView.tsx": 1,
  "app/components/GroupSelect.tsx": 1,
  "app/components/GroupTree.tsx": 1,
  "app/components/HistoryView.tsx": 3,
  "app/components/ImportOverlay.tsx": 3,
  "app/components/ImportTasks.tsx": 1,
  "app/components/ItemGrid.tsx": 2,
  "app/components/JobList.tsx": 1,
  "app/components/ParentField.tsx": 1,
  "app/components/PropertiesPanel.tsx": 10,
  "app/components/SettingsOverlay.tsx": 1,
  "app/components/SubjectMergeOverlay.tsx": 1,
  "app/components/TagEditOverlay.tsx": 1,
  "app/components/TagGridOverlay.tsx": 1,
  "app/components/TagSortOverlay.tsx": 3,
  "app/components/shared/ActionToast.tsx": 2,
  "app/components/shared/FileChip.tsx": 1,
  "app/components/shared/MediaTracksView.tsx": 1,
  "query/QueryBuilder.tsx": 2,
  "query/SavedSearches.tsx": 3,
  "query/builderParts.tsx": 1,
  "shared/ModelDownloadButton.tsx": 1,
  "shared/SelectionBar.tsx": 1,
  "train/DegradeSection.tsx": 2,
  "train/EvaluateView.tsx": 1,
  "train/QueriesEditor.tsx": 1,
  "train/TrainJobEditor.tsx": 4,
  "train/ValueRulesSection.tsx": 2,
};

test("every inline menu-row padding is in the budget, and the budget is exact", () => {
  const actual: Record<string, number> = {};
  for (const dir of ["app", "train", "shared", "query"]) {
    for (const p of walk(join(SRC, dir))) {
      const rel = p.slice(SRC.length);
      if (EXEMPT.has(rel)) continue;
      const n = (readFileSync(p, "utf8").match(RECIPE) ?? []).length;
      if (n) actual[rel] = n;
    }
  }
  const problems: string[] = [];
  for (const [f, n] of Object.entries(actual)) {
    const b = BUDGET[f] ?? 0;
    if (n > b) problems.push(`${f}: ${n} menu-row recipes, budget ${b} — use <MenuRow>`);
    if (n < b) problems.push(`${f}: ${n} menu-row recipes, budget ${b} — lower the budget`);
  }
  for (const f of Object.keys(BUDGET)) if (!(f in actual)) problems.push(`${f}: none left — drop it from the budget`);
  assert.deepEqual(problems, [], problems.join("\n"));
});
