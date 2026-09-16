/**
 * A ROW THAT CAN BE PICKED PAINTS ITS BACKGROUND THROUGH `rowBackground`.
 *
 * `tokens.css` tints a `.hoverable` row on hover with a plain background
 * rule, which any inline `background:` beats — so a list that painted its
 * rows inline (the accent wash when picked, "transparent" otherwise) had
 * rows that never answered the pointer. `rowBackground` stacks the hover
 * wash over the tint over the base. This holds the bare
 * `x ? "var(--accent-dim)" : "transparent"` ternaries that remain — the
 * ones on controls that are not rows — to an exact count per file.
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

const TERNARY = /\? "var\(--accent-dim\)" : (?:"transparent"|"var\(--panel(?:-[23])?\)"|undefined)/g;

const BUDGET: Record<string, number> = {
  // The tree row's BASE: a row being dropped into wears the tint through Row.
  "app/components/TagsTree.tsx": 1,
  "app/components/AnnotationOverlay.tsx": 7,
  "app/components/DescribedFields.tsx": 1,
  "app/components/EstimateOverlay.tsx": 1,
  "app/components/FacesView.tsx": 1,
  "app/components/FilterMenu.tsx": 1,
  "app/components/GroupTree.tsx": 5,
  "app/components/ItemGrid.tsx": 1,
  "app/components/MetaCapsules.tsx": 1,
  "app/components/MetaTagEditOverlay.tsx": 1,
  "app/components/PropertiesPanel.tsx": 15,
  "app/components/RateOverlay.tsx": 1,
  "app/components/SettingsOverlay.tsx": 1,
  "app/components/TagEditOverlay.tsx": 1,
  "app/components/TagMergeOverlay.tsx": 1,
  "app/components/TagSortOverlay.tsx": 1,
  "app/components/TagSuggestList.tsx": 1,
  "app/components/TagsView.tsx": 1,
  "app/components/TextSection.tsx": 1,
  "app/components/shared/ThemeMenu.tsx": 1,
  "app/components/shared/VideoTransport.tsx": 1,
  "query/QueryBuilder.tsx": 1,
  "query/SavedSearches.tsx": 1,
  "query/builderParts.tsx": 1,
  "shared/CountBadge.tsx": 1,
  "shared/SelectionBar.tsx": 1,
  "train/EvaluateView.tsx": 1,
  "train/FormRows.tsx": 1,
  "train/ModelsView.tsx": 1,
  "train/ResolutionPicker.tsx": 1,
};

test("a hoverable row never paints a bare selected/unselected background", () => {
  // The rule itself: a `.hoverable` element with an inline background that
  // is not rowBackground(…) is one the hover wash cannot reach.
  const offenders: string[] = [];
  for (const dir of ["app", "train", "shared", "query"]) {
    for (const p of walk(join(SRC, dir))) {
      const src = readFileSync(p, "utf8");
      for (const m of src.matchAll(/<(?:div|span|li|label)\b[^>]*?className=[^>]*hoverable[^>]*?style=\{\{([\s\S]*?)\}\}/g)) {
        const bg = m[1].match(/background: ([^,\n]+)/);
        if (bg && !/rowBackground\(/.test(bg[1]) && /accent-dim/.test(bg[1])) {
          offenders.push(`${p.slice(SRC.length)}: ${bg[1].slice(0, 60)}`);
        }
      }
    }
  }
  assert.deepEqual(offenders, [], "paint it with rowBackground():\n  " + offenders.join("\n  "));
});

test("the bare accent-dim ternaries that remain are in the budget, exactly", () => {
  const actual: Record<string, number> = {};
  for (const dir of ["app", "train", "shared", "query"]) {
    for (const p of walk(join(SRC, dir))) {
      const rel = p.slice(SRC.length);
      if (rel === "shared/Row.tsx") continue;
      const n = (readFileSync(p, "utf8").match(TERNARY) ?? []).length;
      if (n) actual[rel] = n;
    }
  }
  const problems: string[] = [];
  for (const [f, n] of Object.entries(actual)) {
    const b = BUDGET[f] ?? 0;
    if (n > b) problems.push(`${f}: ${n}, budget ${b} — a row goes through rowBackground()`);
    if (n < b) problems.push(`${f}: ${n}, budget ${b} — lower the budget`);
  }
  for (const f of Object.keys(BUDGET)) if (!(f in actual)) problems.push(`${f}: none left — drop it from the budget`);
  assert.deepEqual(problems, [], problems.join("\n"));
});
