// THE TRAINER'S PERSISTED PREFERENCES — the `mc.train…`/`mc.eval…` keys,
// listed here so the index in `app/prefs.ts` and this one cover every key
// between them (`prefs.test.ts`). `train/` may not import `app/`.
import { boolPref, numPref } from "../shared/storage.ts";

export const TRAIN_PREFS = {
  statsOpen: boolPref("mc.trainStatsOpen", false),
  // The Evaluate grid's S/M/L — one of `GRID_SIZES`' px values; the bounds
  // are that table's ends.
  evalGridSize: numPref("mc.eval.gridSize", { def: 168, min: 124, max: 232 }),
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
