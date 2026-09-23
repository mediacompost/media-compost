/**
 * A BUTTON IS `shared/Button` (or, for a glyph alone, `shared/IconButton`),
 * and the `<button style={{ height: … }}>` recipes that remain are a stated
 * budget.
 *
 * Sixty-odd inline recipes drew the same five text buttons at heights from
 * 26 to 40; the dialogs' primary and ghost, the sidebar's panel-filled
 * verbs, the tinted danger and the sessions' outlined-on-dark are one
 * component now. What is left is counted here per file, strict in both
 * directions, so a new inline recipe fails and a migrated one lowers its
 * number in the same commit.
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

/** The `<button …>` opening tags of a source whose inline style names a
 *  height — a hand-drawn button recipe. Brace-matched, so a `{…}` in an
 *  attribute does not end the tag early. */
export function styledButtonTags(src: string): number {
  let n = 0;
  for (const m of src.matchAll(/<button\b/g)) {
    let depth = 0; let j = m.index! + 7;
    for (; j < src.length; j++) {
      const c = src[j];
      if (c === "{") depth++;
      else if (c === "}") depth--;
      else if (c === ">" && depth === 0) break;
    }
    if (/style=\{\{[\s\S]*?\bheight:/.test(src.slice(m.index!, j + 1))) n++;
  }
  return n;
}

const EXEMPT = new Set(["shared/Button.tsx", "shared/IconButton.tsx"]);

const BUDGET: Record<string, number> = {
  "app/components/AnnotationOverlay.tsx": 4,
  "app/components/ColorPicker.tsx": 2,
  "app/components/EditorMenu.tsx": 1,
  "app/components/EditorOverlay.tsx": 7,
  "app/components/EstimateOverlay.tsx": 2,
  "app/components/FilterMenu.tsx": 1,
  "app/components/GroupPropertiesOverlay.tsx": 2,
  "app/components/GroupSelect.tsx": 1,
  "app/components/ImportOverlay.tsx": 2,
  "app/components/OffscreenSelection.tsx": 1,
  "app/components/PropertiesPanel.tsx": 17,
  "app/components/QuickLook.tsx": 4,
  "app/components/RateOverlay.tsx": 1,
  "app/components/SettingsOverlay.tsx": 2,
  "app/components/SubjectFaces.tsx": 1,
  "app/components/TagGridOverlay.tsx": 2,
  "app/components/TagSetsView.tsx": 1,
  "app/components/TagSortOverlay.tsx": 4,
  "app/components/TagTrack.tsx": 2,
  "app/components/UpdateBanner.tsx": 1,
  "app/components/VideoEditorOverlay.tsx": 5,
  "app/components/shared/FileChip.tsx": 1,
  "app/components/shared/Timeline.tsx": 1,
  "app/components/shared/UndoBar.tsx": 1,
  "app/components/shared/VideoTransport.tsx": 5,
  "app/components/shared/iconButtons.tsx": 1,
  "query/ConditionRow.tsx": 2,
  "shared/SegmentedControl.tsx": 1,
  "train/DegradeSection.tsx": 4,
  "train/EvaluateView.tsx": 2,
  "train/FormRows.tsx": 1,
  "train/Lightbox.tsx": 2,
  "train/LossGraph.tsx": 4,
  "train/ModelsView.tsx": 1,
  "train/QueriesEditor.tsx": 1,
  "train/ResolutionPicker.tsx": 1,
  "train/TrainJobDetail.tsx": 2,
  "train/TrainJobEditor.tsx": 1,
  "train/ValueRulesSection.tsx": 2,
};

test("every hand-drawn button recipe is in the budget, and the budget is exact", () => {
  const actual: Record<string, number> = {};
  for (const dir of ["app", "train", "shared", "query"]) {
    for (const p of walk(join(SRC, dir))) {
      const rel = p.slice(SRC.length);
      if (EXEMPT.has(rel)) continue;
      const n = styledButtonTags(readFileSync(p, "utf8"));
      if (n) actual[rel] = n;
    }
  }
  const problems: string[] = [];
  for (const [f, n] of Object.entries(actual)) {
    const b = BUDGET[f] ?? 0;
    if (n > b) problems.push(`${f}: ${n} inline button recipes, budget ${b} — use <Button> / <IconButton>`);
    if (n < b) problems.push(`${f}: ${n} inline button recipes, budget ${b} — lower the budget`);
  }
  for (const f of Object.keys(BUDGET)) if (!(f in actual)) problems.push(`${f}: none left — drop it from the budget`);
  assert.deepEqual(problems, [], problems.join("\n"));
});

/** A `.row-action` glyph drawn by hand rather than by `<IconButton reveal>`. */
const ROW_ACTION_BUDGET: Record<string, number> = {
  "app/components/HistoryView.tsx": 1,
  "app/components/JobList.tsx": 3,
  "app/components/PeopleSection.tsx": 1,
  "app/components/PropertiesPanel.tsx": 4,
  "app/components/TagSortOverlay.tsx": 2,
};

test("a revealed glyph button is <IconButton reveal>, and the hand-drawn ones are counted", () => {
  const actual: Record<string, number> = {};
  for (const dir of ["app", "train", "shared", "query"]) {
    for (const p of walk(join(SRC, dir))) {
      const rel = p.slice(SRC.length);
      if (rel === "shared/IconButton.tsx") continue;
      const n = (readFileSync(p, "utf8").match(/className="row-action(?!s)/g) ?? []).length;
      if (n) actual[rel] = n;
    }
  }
  const problems: string[] = [];
  for (const [f, n] of Object.entries(actual)) {
    const b = ROW_ACTION_BUDGET[f] ?? 0;
    if (n > b) problems.push(`${f}: ${n} row-action spans, budget ${b} — use <IconButton reveal>`);
    if (n < b) problems.push(`${f}: ${n} row-action spans, budget ${b} — lower the budget`);
  }
  for (const f of Object.keys(ROW_ACTION_BUDGET)) if (!(f in actual)) problems.push(`${f}: none left — drop it from the budget`);
  assert.deepEqual(problems, [], problems.join("\n"));
});
