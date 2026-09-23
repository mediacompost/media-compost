// THE TRAINER'S PERSISTED PREFERENCES — the `mc.train…`/`mc.eval…` keys,
// listed here so the index in `app/prefs.ts` and this one cover every key
// between them (`prefs.test.ts`). `train/` may not import `app/`.
import { boolPref, numPref, strPref } from "../shared/storage.ts";

/** What the Evaluate grid gathers its runs by: the sitting they were made
 *  in, the model (and finetune) they ran on, the adapters stacked on it, or
 *  the prompt. */
export const EVAL_GROUPINGS = ["session", "model", "adapters", "prompt"] as const;
export type EvalGrouping = typeof EVAL_GROUPINGS[number];

export const TRAIN_PREFS = {
  statsOpen: boolPref("mc.trainStatsOpen", false),
  // The Evaluate grid's S/M/L — one of `GRID_SIZES`' px values; the bounds
  // are that table's ends.
  evalGridSize: numPref("mc.eval.gridSize", { def: 168, min: 124, max: 232 }),
  evalGroupBy: strPref<EvalGrouping>("mc.eval.groupBy", "session", EVAL_GROUPINGS),
};

export const TRAIN_PREF_KEYS: Record<string, string> = {
  "mc.train.sidebarW": "the Train tab's sidebar width",
  "mc.eval.sidebarW": "the Evaluate tab's sidebar width",
  "mc.train.draftsOrder": "the Train tab's drafts order (manual|date)",
  "mc.trainPresets": "the job editor's presets (JSON)",
  "mc.trainPromptSets": "the job editor's saved prompt sets (JSON)",
  "mc.trainValueRuleSets": "the job editor's saved value-rule sets (JSON)",
  "mc.trainDegradeSets": "the job editor's saved degrade sets (JSON)",
  "mc.evalPanel": "the Evaluate tab's panel state (JSON)",
};
