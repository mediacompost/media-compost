/**
 * TYPE AND RADIUS ARE SCALES. `tokens.css` names eight font sizes and
 * eight radii; a component's literal names one. What is left numeric —
 * sizes off the scale, and the SVG map's text — is a stated budget, strict
 * both ways per file.
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
function check(name: string, re: RegExp, budget: Record<string, number>, hint: string) {
  const actual: Record<string, number> = {};
  for (const dir of ["app", "train", "shared", "query"]) {
    for (const p of walk(join(SRC, dir))) {
      const n = (readFileSync(p, "utf8").match(re) ?? []).length;
      if (n) actual[p.slice(SRC.length)] = n;
    }
  }
  const problems: string[] = [];
  for (const [f, n] of Object.entries(actual)) {
    const b = budget[f] ?? 0;
    if (n > b) problems.push(`${f}: ${n} ${name}, budget ${b} — ${hint}`);
    if (n < b) problems.push(`${f}: ${n} ${name}, budget ${b} — lower the budget`);
  }
  for (const f of Object.keys(budget)) if (!(f in actual)) problems.push(`${f}: none left — drop it from the budget`);
  assert.deepEqual(problems, [], problems.join("\n"));
}

const FONT_BUDGET: Record<string, number> = {
  "app/components/AnnotationOverlay.tsx": 1,
  "app/components/HistoryView.tsx": 1,
};
const RADIUS_BUDGET: Record<string, number> = {
  "app/components/AnnotationOverlay.tsx": 15,
  "app/components/CaptionEditor.tsx": 1,
  "app/components/CardGrid.tsx": 1,
  "app/components/ColorPicker.tsx": 2,
  "app/components/CutTrack.tsx": 2,
  "app/components/EstimateOverlay.tsx": 1,
  "app/components/HistoryView.tsx": 1,
  "app/components/ItemGrid.tsx": 5,
  "app/components/Mark.tsx": 1,
  "app/components/PropertiesPanel.tsx": 9,
  "app/components/QuickLook.tsx": 2,
  "app/components/QuickTagOverlay.tsx": 1,
  "app/components/RateOverlay.tsx": 1,
  "app/components/SettingsStorage.tsx": 1,
  "app/components/TagGridOverlay.tsx": 5,
  "app/components/TagSortOverlay.tsx": 2,
  "app/components/TagTrack.tsx": 1,
  "app/components/TagsTree.tsx": 2,
  "app/components/VideoEditorOverlay.tsx": 1,
  "app/components/shared/JudgeCard.tsx": 1,
  "app/components/shared/TextInPicture.tsx": 1,
  "app/components/shared/Timeline.tsx": 5,
  "query/ConditionRow.tsx": 2,
  "shared/Overlay.tsx": 1,
  "shared/WorldMap.tsx": 1,
  "train/FormRows.tsx": 1,
  "train/LossGraph.tsx": 4,
  "train/SampleTimeline.tsx": 1,
  "train/StepPhases.tsx": 1,
  "train/TrainDataInspector.tsx": 2,
  "train/TrainView.tsx": 2,
};

test("a font size names a step of the scale (--fs-0 … --fs-7)", () => {
  check("numeric font sizes", /fontSize: [0-9.]+(?![0-9.])/g, FONT_BUDGET, "use var(--fs-n)");
});

test("a radius names a step of the scale (--r-1 … --r-7, --r-round)", () => {
  check("numeric radii", /borderRadius: [0-9.]+(?![0-9.])/g, RADIUS_BUDGET, "use var(--r-n)");
});

test("the scales are defined", () => {
  const css = readFileSync(join(SRC, "shared", "tokens.css"), "utf8");
  for (const n of [0, 1, 2, 3, 4, 5, 6, 7]) assert.match(css, new RegExp(`--fs-${n}: [0-9.]+px;`));
  for (const n of [1, 2, 3, 4, 5, 6, 7]) assert.match(css, new RegExp(`--r-${n}: [0-9]+px;`));
  assert.match(css, /--r-round: 999px;/);
});
