// Named job configurations, remembered in the browser like the test-prompt
// sets next to them (same store, same shape) — a setup that worked once can be
// dropped into any new job, and one of them can be the starting point for
// every new job.
//
// A preset holds the CONFIG only. The name of a job, and which job it is, are
// not settings; loading a preset into a half-written job replaces what it
// trains and how, and leaves the job itself alone.
import type { TrainingConfig, TrainModelSpec } from "./api";
import { storage } from "../shared/storage.ts";
import { defaultTrainingConfig, resolutionList } from "./util";

const KEY = "mc.trainPresets";

export interface TrainPreset {
  // `id` rather than the name identifies a preset, so renaming one — and two
  // presets ending up with the same name — can't overwrite the wrong entry.
  id: string;
  name: string;
  config: TrainingConfig;
  /** Applied to every new job. At most one preset carries it. */
  isDefault?: boolean;
}

export function loadPresets(): TrainPreset[] {
  try {
    const v = JSON.parse(storage.get(KEY) || "[]");
    if (!Array.isArray(v)) return [];
    return v.filter((p) => p && typeof p.name === "string" && p.config)
      .map((p, i) => ({
        id: typeof p.id === "string" ? p.id : `legacy-${i}-${p.name}`,
        name: p.name,
        config: p.config as TrainingConfig,
        isDefault: !!p.isDefault,
      }));
  } catch { return []; }
}

export function storePresets(list: TrainPreset[]) {
  try { storage.set(KEY, JSON.stringify(list)); } catch { /* ignore */ }
}

export function defaultPreset(list = loadPresets()): TrainPreset | undefined {
  return list.find((p) => p.isDefault);
}

/** Exactly one default: marking one clears the rest. Marking the current
 *  default again clears it, so "new jobs start from the app's defaults" stays
 *  reachable without deleting the preset. */
export function withDefault(list: TrainPreset[], id: string): TrainPreset[] {
  const on = !list.find((p) => p.id === id)?.isDefault;
  return list.map((p) => ({ ...p, isDefault: on && p.id === id }));
}

/** A stored config on top of the current defaults.
 *
 * Presets outlive the code that wrote them: a preset saved before a setting
 * existed has no value for it, and taking it verbatim would hand `undefined`
 * to the editor's inputs. Every section is merged over a fresh default, so an
 * old preset gains new settings at their default instead of breaking.
 */
export function configFromPreset(saved: TrainingConfig,
                                 models: TrainModelSpec[]): TrainingConfig {
  const model = models.find((m) => m.key === saved?.model);
  const base = defaultTrainingConfig(model ?? models[0]);
  return {
    ...base,
    ...saved,
    hyper: { ...base.hyper, ...(saved?.hyper ?? {}) },
    buckets: { ...base.buckets, ...(saved?.buckets ?? {}) },
    noise: { ...base.noise, ...(saved?.noise ?? {}) },
    captions: { ...base.captions, ...(saved?.captions ?? {}) },
    video: { ...base.video, ...(saved?.video ?? {}) },
    degrade: { ...base.degrade, ...(saved?.degrade ?? {}) },
    sampling: { ...base.sampling, ...(saved?.sampling ?? {}) },
    model_params: { ...base.model_params, ...(saved?.model_params ?? {}) },
    // A model the registry no longer has would make the whole editor blank.
    model: model ? saved.model : base.model,
  };
}
