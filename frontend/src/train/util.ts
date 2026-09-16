// Shared helpers for the Train tab: default config, status colors, size math.
import { formatNumber } from "../shared/i18nCore.ts";
import type {
  SystemDevice, TrainDegradeVariant, TrainDevice, TrainingConfig,
  TrainingJobSummary, TrainModelSpec,
} from "./api";

/** Rows grouped by a key, each group in the order it first appears.
 *
 *  Both adapter pickers use it to put the weight sets under the model each
 *  was trained on: an adapter now fits a whole family of models, so one list
 *  holds several models' work and a flat list of names says nothing about
 *  which is which. */
export function groupBy<T>(rows: T[], keyOf: (row: T) => string): [string, T[]][] {
  const order: string[] = [];
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const k = keyOf(row);
    if (!groups.has(k)) { groups.set(k, []); order.push(k); }
    groups.get(k)!.push(row);
  }
  return order.map((k) => [k, groups.get(k)!]);
}

/** Which weights an adapter trained on `key` can be applied to: the built-in
 *  that model is a variant of, which for a built-in is itself.
 *
 *  A custom model is a finetune of a built-in and an adapter is a set of
 *  deltas on that built-in's layers, so an adapter trained on one SDXL
 *  finetune fits plain SDXL and every other SDXL finetune. NOT the
 *  architecture: FLUX.2 Klein 4B and 9B share an engine and are two
 *  different transformers. Mirrors `models.adapter_family` on the server,
 *  which refuses a mismatch — this is what keeps the app from offering one. */
export function adapterFamily(models: TrainModelSpec[], key: string): string {
  const m = models.find((x) => x.key === key);
  if (!m) return key;          // a model that is gone is its own family
  return m.base || m.key;
}

/** Whether an adapter (or finetune) trained on `trainedOn` fits `model`. */
export function fitsModel(models: TrainModelSpec[], trainedOn: string,
                          model: string): boolean {
  return adapterFamily(models, trainedOn) === adapterFamily(models, model);
}

/** Models by ARCHITECTURE, groups in the order the registry lists them and
 *  each group's built-ins before the user's own.
 *
 *  The architecture is what makes two entries the same KIND of model —
 *  one engine, one set of memory constants, one set of layer names. It is
 *  not the same question as "does this adapter fit" (that is
 *  `adapterFamily`, which is narrower: two releases of one architecture can
 *  be two different transformers). Grouping by "built-in vs yours" is
 *  provenance: it split Chroma's two releases from each other while putting
 *  SDXL next to FLUX.2. A user model predating the `engine` field falls back
 *  to the base it declared. */
export function groupByArchitecture(
  models: TrainModelSpec[],
): [string, TrainModelSpec[]][] {
  const order: string[] = [];
  const groups = new Map<string, TrainModelSpec[]>();
  for (const m of models) {
    const key = m.engine || m.base || m.key;
    if (!groups.has(key)) { groups.set(key, []); order.push(key); }
    groups.get(key)!.push(m);
  }
  for (const list of groups.values()) {
    list.sort((a, b) => Number(!!a.user) - Number(!!b.user));
  }
  return order.map((k) => [k, groups.get(k)!]);
}

/** The same groups, ordered by their HEADING.
 *
 *  Grouping and ORDER are two questions: `groupByArchitecture` answers the
 *  first and keeps the registry's own order, which is what the job editor's
 *  model dropdown wants (the registry lists the small, ordinary choices
 *  first). The Models PAGE is a list to find a name in, and there the order
 *  that helps is the alphabet. Numeric-aware, so FLUX.1 comes before FLUX.2
 *  and SDXL 1.0 sorts as a number rather than as text. */
export function byArchitectureLabel(
  groups: [string, TrainModelSpec[]][],
): [string, TrainModelSpec[]][] {
  return [...groups].sort(([ea, ga], [eb, gb]) =>
    architectureLabel(ea, ga).localeCompare(
      architectureLabel(eb, gb), undefined,
      { numeric: true, sensitivity: "base" }));
}

/** The heading for one architecture group.
 *
 *  Derived from the group's own built-in labels, not a table of engine names:
 *  with one built-in it is that model's name, with several it is what their
 *  labels share ("Chroma1" for HD and Base). So an engine added later needs
 *  nothing here — the table would be the thing nobody remembers to update.
 *
 *  **The shared part is cut at a WORD, never mid-token.** Two labels usually
 *  share more characters than they share meaning: "FLUX.2 Klein (base, 4B)"
 *  and "…9B)" have "FLUX.2 Klein (base, " in common, and the raw prefix put
 *  `FLUX.2 Klein (base,` at the top of the page — a heading ending in a comma
 *  and an unclosed bracket. (It only appeared when FLUX.2 dev was dropped and
 *  left the two Klein releases alone in their group, which is how a rule that
 *  looks right for years stops being right.) So the prefix falls back to the
 *  last whole word, and a trailing unclosed parenthetical goes with it. */
export function architectureLabel(engine: string,
                                  group: TrainModelSpec[]): string {
  const builtins = group.filter((m) => !m.user);
  if (!builtins.length) return engine;
  if (builtins.length === 1) return builtins[0].label;
  const common = wholeWords(commonPrefix(builtins.map((m) => m.label)));
  // Too short a shared prefix is a coincidence, not a family name.
  return common.length >= 3 ? common : builtins[0].label;
}

/** A shared prefix cut back to the last COMPLETE word, with a dangling
 *  opening parenthetical dropped. Exported for the test that states it. */
export function wholeWords(prefix: string): string {
  let out = prefix.trimEnd();
  // A prefix that stops inside a word ("FLUX.2 Kle") says nothing the shorter
  // one does not; only a prefix ending exactly where the inputs diverge at a
  // space is a whole word already.
  if (prefix.length !== out.length) {
    // It ended on whitespace, so every word in it is complete.
  } else {
    out = out.slice(0, out.lastIndexOf(" ") + 1).trimEnd();
  }
  // Drop a trailing token that opens a bracket it never closes, then any
  // punctuation left hanging off the end.
  const words = out.split(" ");
  const last = words[words.length - 1] ?? "";
  if (last.includes("(") && !last.includes(")")) words.pop();
  return words.join(" ").replace(/[\s,;:—-]+$/, "");
}

/** What distinguishes one release WITHIN its architecture group — the part of
 *  its label the family name does not already say ("HD", "Base"). Falls back
 *  to the whole label when there is nothing shared to strip. */
export function releaseLabel(model: TrainModelSpec, engine: string,
                             group: TrainModelSpec[]): string {
  const family = architectureLabel(engine, group);
  if (family && model.label.startsWith(family)) {
    const rest = model.label.slice(family.length).trim();
    // What is left is often the whole of a parenthetical the heading stopped
    // in front of ("(base, 4B)"); a row that is nothing but a bracketed aside
    // reads better without the brackets.
    const bare = /^\(([^()]*)\)$/.exec(rest);
    if (bare) return bare[1].trim();
    if (rest) return rest;
  }
  return model.label;
}

export function commonPrefix(values: string[]): string {
  if (!values.length) return "";
  let out = values[0];
  for (const v of values.slice(1)) {
    let i = 0;
    while (i < out.length && i < v.length && out[i] === v[i]) i++;
    out = out.slice(0, i);
  }
  return out;
}


/** Everything a user model inherits from the built-in it is based on, as one
 *  string — two releases agreeing on all of it are one choice. Native
 *  resolution is deliberately absent: the add form asks for it. */
function inheritedProfile(m: TrainModelSpec): string {
  return [
    m.engine, m.lora_only, m.default_lr, m.lora_mb_per_rank, m.full_gb,
    m.backbone_gb, m.aux_gb, m.act_gb, m.act_gb_cuda ?? 0, m.ckpt_factor,
    m.ckpt_factor_cuda ?? 0, m.te_act_gb, m.te_pooled_act_gb ?? 0,
    m.te_params_m_per_rank ?? 0, m.te_pooled_params_m_per_rank ?? 0,
    (m.params ?? []).map((p) => p.name).join("+"),
  ].join("|");
}

/** The Hugging Face page for a model's repo id, or "" when there isn't one.
 *
 * A repo id is `owner/name` — one slash and nothing that could be a path. The
 * same field carries a FILESYSTEM PATH for a model added as local, so linking
 * it blindly points at a page that cannot exist; `local` is checked as well as
 * the shape, since a POSIX path has the same one-slash form as an id.
 *
 * Here rather than beside the component that renders it: this module is
 * type-only at the edges, so `node --test` can load it — a .tsx importing
 * react-query cannot be. */
export function hubUrl(repo: string, local?: boolean): string {
  const id = (repo || "").trim();
  if (local || !id) return "";
  if (id.includes("\\") || /^[A-Za-z]:/.test(id) || id.startsWith("/")) return "";
  if (id.split("/").length !== 2) return "";
  if (id.endsWith(".safetensors") || id.endsWith(".ckpt")) return "";
  return `https://huggingface.co/${id}`;
}

/** How many sizes one run may train at.
 *
 *  The BACKEND is the authority (`train/spec.py: MAX_RESOLUTIONS`, which
 *  refuses a longer list); this copy is what lets the picker stop offering
 *  another tick rather than let the Save answer 400, and
 *  `tests/train/test_training_manifest_golden.py` holds the two equal. */
export const MAX_RESOLUTIONS = 5;

/** The sizes as the backend stores them: whole numbers, no duplicates,
 *  smallest first, never empty.
 *
 *  0 IS A MEMBER and means the model's own size, so it survives the filter
 *  and sorts to the front. Both sides normalize, and deliberately: the order
 *  fixes every index in the run's manifest and therefore what the trainer's
 *  seeded sampler draws, so nothing downstream may depend on what somebody
 *  happened to tick first. */
export function resolutionList(sizes: number[]): number[] {
  const out = new Set<number>();
  for (const s of sizes) {
    const n = Math.round(s);
    if (Number.isFinite(n) && n >= 0 && n <= 4096) out.add(n);
  }
  const kept = [...out].sort((a, b) => a - b).slice(0, MAX_RESOLUTIONS);
  // Naming nothing is naming the model's own size: a run trains at some
  // size, and the config would substitute this back anyway.
  return kept.length ? kept : [0];
}

export function defaultTrainingConfig(model?: TrainModelSpec): TrainingConfig {
  return {
    model: model?.key ?? "sdxl",
    local_path: "",
    method: "lora",
    init_lora: "",
    gpu: "auto",
    hyper: {
      steps: 2000,
      epochs: 0,
      lr: model?.default_lr ?? 1e-4,
      lr_scheduler: "cosine",
      warmup_steps: 0,
      batch_size: 1,
      grad_accum: 1,
      rank: 16,
      alpha: 16,
      precision: "bf16",
    bf16_masters: false,
      seed: 42,
      checkpoint_every: 500,
      checkpoint_epochs: 0,
      checkpoint_keep: 2,
      checkpoint_keep_every: 0,
      train_text_encoder: false,
      te_lr: 0,
      te_stop_ratio: 0.5,
      train_text_encoder_large: true,
      ema: false,
      ema_decay: 0.999,
      gradient_checkpointing: false,
      network: "lora",
      lokr_factor: -1,
      layer_include: [],
      layer_exclude: [],
      optimizer: "adamw",
      cache_latents: true,
      quantization: "none",
      quantize_text_encoder: false,
      // Off by default like its neighbour: it costs a CPU forward per step,
      // and a run that already fits should not pay that silently.
      offload_text_encoder: false,
      attention_slicing: "auto",
    },
    queries: [{ tree: null, search: "", weight: 1, regularize: false }],
    weight_mode: "sampling",
    reg_strength: 1,
    buckets: {
      resolutions: [0],
      bucket_step: 64,
      max_aspect: 2,
      random_crop: true,
      skip_upscale: true,
    no_flip_tags: [],
    no_flip_meta_tags: [],
      flip_p: 0,
      alpha_mask: false,
      alpha_bg_weight: 0.1,
      mask_loss_tags: [],
      mask_loss_meta_tags: [],
      mask_loss_weight: 0,
    },
    noise: { timesteps: "default", logit_mean: 0, logit_std: 1 },
    captions: {
      source: "tags",
      trigger: "",
      caption_repeat: "random",
      alias_p: 0,
      tag_text: "name" as const,
      include_meta_tags: [],
      exclude_meta_tags: [],
      always_tags: [],
      exclude_tags: [],
      always_tag_meta_tags: [],
      exclude_tag_meta_tags: [],
      value_rules: [],
      exclude_tag_group_meta_tags: [],
      min_tags: 0,
      max_tags: 0,
      balance: "none",
      freq_base: "dataset",
      loss_weight_by_freq: false,
      shuffle: true,
      dropout: 0,
      underscores_to_spaces: true,
      separator: ", ",
      group_tags: false,
    group_label: "none" as const,
    group_separator: "\n",
    skip_partial_tags: true,
    },
    video: {
      include: false,
      every: 1,
      unit: "seconds",
      dedupe: true,
      captions: "inherit" as const,
      caption_include_meta_tags: [],
      caption_exclude_meta_tags: [],
    },
    degrade: { variants: [] },
    sampling: {
      every_n_steps: 0,
      every_n_epochs: 0,
      at_start: false,
      prompts: [],
      seed: 42,
      steps: 25,
      cfg: 6,
      batch: 1,
      width: 0,
      height: 0,
    },
    validation: {
      every_n_steps: 0,
      holdout: 16,
      stable_items: 0,
      seed: 42,
    },
    model_params: Object.fromEntries(
      (model?.params ?? []).map((p) => [p.name, p.default])
    ),
  };
}

/** One degradation variant, at the defaults a new row starts from. */
export function defaultDegradeVariant(): TrainDegradeVariant {
  return {
    name: "",
    method: "jpeg",
    weight: 0.25,
    tags: [],
    remove_tags: [],
    require_tags: [],
    skip_tags: [],
    remove_tag_meta_tags: [],
    require_tag_meta_tags: [],
    skip_tag_meta_tags: [],
    variations: 1,
    passes: { lo: 1, hi: 1 },
    quality: { lo: 20, hi: 60 },
    subsampling: "4:2:0",
    codec: "h264",
    crf: { lo: 26, hi: 38 },
    scale: { lo: 0.35, hi: 0.75 },
    resample: "bilinear",
  };
}

/** What the run will actually draw, per ELIGIBLE picture.
 *
 * Worded per picture and not over the dataset because a variant with a
 * `require_tags` gate applies to a subset nobody can count without running the
 * query — a whole-dataset figure would simply be wrong. `clean` is 100 by
 * definition: the clean entry is the unit everything else is a ratio of.
 */
export function degradeMix(config: TrainingConfig):
    { clean: number; parts: { label: string; visits: number; gated: boolean }[] } {
  const live = (config.degrade?.variants ?? []).filter(
    (v) => v.weight > 0 && v.tags.length > 0);
  const mass = 1 + live.reduce((a, v) => a + v.weight, 0);
  return {
    clean: Math.round((1 / mass) * 100 * 100) / 100,
    parts: live.map((v) => ({
      label: v.name.trim() || v.method,
      visits: Math.round((v.weight / mass) * 100 * 100) / 100,
      gated: v.require_tags.length > 0 || v.skip_tags.length > 0,
    })),
  };
}

/** How many degraded files the run will cache, given how many pictures it
 *  selected — the disk cost of raising `variations`, where it is raised. */
export function degradeFileCount(config: TrainingConfig, items: number): number {
  const per = (config.degrade?.variants ?? [])
    .filter((v) => v.weight > 0 && v.tags.length > 0)
    .reduce((a, v) => a + v.variations, 0);
  return per * Math.max(0, items);
}

/** The intra-step note as a fraction of the step (images done / images per
 *  step), so a minutes-long big-batch step can show as "20.25 / 200"
 *  instead of a frozen counter. 0 when there is no note. */
export function stepFraction(note: string | undefined): number {
  const m = /^(\d+) \/ (\d+)$/.exec(note ?? "");
  if (!m) return 0;
  const total = Number(m[2]);
  return total > 0 ? Math.min(Number(m[1]) / total, 1) : 0;
}

/** "20.25" while inside a step, plain "20" otherwise. */
export function fracStepText(job: TrainingJobSummary): string {
  const frac = (job.status === "running" || job.status === "pausing")
    && job.phase === "training" ? stepFraction(job.phase_note) : 0;
  return frac > 0 ? (job.step + frac).toFixed(2) : String(job.step);
}

/** When the job last did something, as unix seconds (0 when unknown).
 *
 *  The record has no "updated" field — it has the moments a job passes
 *  through — so the newest of them IS the last activity: finished for a run
 *  that ended, started for one that is going, created for one that has not
 *  run yet.
 *
 *  **`queued_at` IS NOT ONE OF THEM, and reading it here was a bug.** For a
 *  waiting job that field is a POSITION rather than a time: `reorder_queue`
 *  assigns fresh stamps a millisecond apart to every queued, paused and draft
 *  job whenever the order changes, which the app does on every drag AND when
 *  the Drafts section is switched to manual ordering. Read as a time it made
 *  every row in the list say it had just been touched — and say it in the
 *  same breath, since one pass stamps them all — so switching the sort
 *  appeared to rewrite the history of every draft. Nothing is lost by
 *  dropping it: every job has a `created_at`, and a job that has actually run
 *  has the two moments that say so. */
export function lastActivity(job: {
  created_at?: number | null;
  started_at?: number | null; finished_at?: number | null;
}): number {
  return Math.max(job.finished_at || 0, job.started_at || 0,
                  job.created_at || 0);
}

export const ACTIVE_STATUSES = new Set(["queued", "running", "pausing"]);

export function anyJobActive(jobs: TrainingJobSummary[] | undefined): boolean {
  return (jobs ?? []).some((j) => ACTIVE_STATUSES.has(j.status));
}

/** Status word as shown to the user; the wire values are lowercase ids, and
 *  passing those to `t()` directly leaves them untranslated. */
export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft", queued: "Queued", running: "Running", pausing: "Pausing…",
  paused: "Paused", completed: "Completed", failed: "Failed",
  canceled: "Canceled",
};

export function statusColor(status: string): string {
  switch (status) {
    case "running": return "var(--accent)";
    case "pausing": return "var(--yellow-text)";
    case "paused": return "var(--yellow-text)";
    case "queued": return "var(--text-2)";
    case "completed": return "var(--green-text)";
    case "failed": return "var(--red-text)";
    case "canceled": return "var(--muted)";
    default: return "var(--muted)"; // draft
  }
}

/** How many step snapshots the run will end up holding.
 *
 *  The two rules are a UNION, so this is |window ∪ milestones|: the last
 *  `keep` snapshots, plus every `keep_every`-th one BEFORE that window (the
 *  milestones inside it are already counted). The window is fixed; the
 *  milestones grow with the run, which is exactly what the estimate has to
 *  show — a long run kept by milestones costs far more than a window does.
 *  At least one either way: the newest snapshot always survives. */
export function keptCheckpoints(config: TrainingConfig): number {
  const h = config.hyper;
  if (!h.checkpoint_every) return 0;
  // Snapshots the run writes: the cadence multiples it reaches. The final
  // step writes the resume point, not a cadence snapshot.
  //
  // A cadence in EPOCHS is countable only against a length in epochs — how
  // many steps a pass takes is the manifest's answer and the editor does not
  // have it. Against a length in steps this returns 0, which is the honest
  // answer and what makes the estimate line stand down rather than print a
  // number nobody can stand behind.
  const total = h.checkpoint_epochs > 0
    ? (h.epochs > 0
        ? Math.max(0, Math.ceil(h.epochs / h.checkpoint_epochs) - 1) : 0)
    : Math.floor(Math.max(0, h.steps - 1) / h.checkpoint_every);
  if (total <= 0) return 0;
  const last = Math.min(Math.max(0, h.checkpoint_keep), total);
  const every = Math.max(0, h.checkpoint_keep_every ?? 0);
  const older = every > 0 ? Math.floor((total - last) / every) : 0;
  return Math.max(1, last + older);
}

/** Rough on-disk size of ONE checkpoint for the editor's estimate line.
 *
 *  A LoKr adapter is far smaller than the LoRA figure here — how much smaller
 *  depends on how each individual weight factorises, which is not something
 *  this can know from the registry. It is left OVER-estimated rather than
 *  guessed at: the number's job is to warn about filling a disk, and erring
 *  towards "more" is the direction that does that. The editor says the same
 *  thing in words next to the adapter type. */
export function checkpointMb(config: TrainingConfig, model?: TrainModelSpec): number {
  if (!model) return 0;
  if (config.method === "lora") {
    let mb = model.lora_mb_per_rank * config.hyper.rank;
    if (config.hyper.train_text_encoder) mb *= 1.3;
    return mb;
  }
  return model.full_gb * 1024;
}

/** The parts of a training run's GPU memory, in GB.
 *
 *  An estimate, not a budget: weights and optimizer state follow from
 *  parameter counts and are fairly exact, while `activations` — the term that
 *  actually decides whether a run survives — depends on the model's internals
 *  and is calibrated per model in the registry. Presented to the user as "≈".
 */
export interface VramEstimate {
  weights: number;      // backbone + text encoders + VAE, resident
  optimizer: number;    // trained parameters + gradients + Adam moments
  activations: number;  // what a forward/backward keeps, per batch
  total: number;
}

/** Measured: slicing attention leaves ~57% of a step's activations, on both
 *  models tested and at both resolutions. */
const SLICE_FACTOR = 0.57;

/** What quantization does to ACTIVATIONS — see estimateVram. */
const QUANT_ACT_FACTOR = 1.6;

/** Bytes of optimizer state per trained parameter, by optimizer.
 *
 *  All four hold an fp32 master copy of the parameter (4 bytes) and its
 *  gradient (4). What differs is the running statistics on top:
 *
 *  - `adamw` — two fp32 moments, one per parameter: 8 more.
 *  - `adamw_8bit` — the same two moments at one byte each: 2 more.
 *  - `adafactor` — the second moment FACTORED into a row and a column vector
 *    per matrix, which is O(n+m) against O(n·m) and rounds to nothing here.
 *  - `prodigy` — Adam's two moments plus a copy of the initial weights it
 *    measures distance from, so 4 more than AdamW.
 */
export const OPTIMIZER_BYTES: Record<string, number> = {
  adamw: 16,
  adamw_8bit: 10,
  adafactor: 8,
  prodigy: 20,
};

/** Which backend a config will actually run on, for picking the activation
 *  constants. "auto" means the machine's first device, which is what
 *  `loop.pick_device` resolves it to. */
export function backendOf(config: TrainingConfig,
                          devices?: TrainDevice[]): string {
  const want = config.gpu || "auto";
  const id = want === "auto" ? (devices?.[0]?.id || "") : want;
  if (id.startsWith("cuda")) return "cuda";
  if (id.startsWith("mps")) return "mps";
  if (id.startsWith("cpu")) return "cpu";
  return "";
}

/** The activations-per-image constant and the checkpointing factor for one
 *  backend.
 *
 *  CUDA has fused/flash attention and MPS does not, so the same model's
 *  activations differ by between 1.7x and 8.5x between them — measured, not
 *  assumed. A model with no CUDA figure falls back to the MPS pair, which
 *  OVER-estimates there; that is the safe direction, since the number's job
 *  is to say whether a run will fit. */
export function activationConstants(model: TrainModelSpec, backend: string):
    { act: number; ckpt: number; constShare: number; quadShare: number;
      exp: number; teAct: number } {
  if (backend === "cuda" && model.act_gb_cuda) {
    return {
      act: model.act_gb_cuda,
      ckpt: model.ckpt_factor_cuda || model.ckpt_factor || 0.2,
      constShare: model.act_const_share_cuda ?? 0,
      // Zero on CUDA unless something measures otherwise: fused attention
      // never materializes the N×N matrix, which is the only term that grows
      // with the square of the token count.
      quadShare: model.act_quad_share_cuda ?? 0,
      exp: model.act_exp_cuda || model.act_exp || 1,
      teAct: model.te_act_gb_cuda || model.te_act_gb || 0,
    };
  }
  return {
    act: model.act_gb,
    ckpt: model.ckpt_factor || 0.2,
    constShare: model.act_const_share ?? 0,
    quadShare: model.act_quad_share ?? 0,
    exp: model.act_exp || 1,
    teAct: model.te_act_gb || 0,
  };
}

/** Millions of trainable parameters per rank the text-encoder adapter(s)
 *  add — the large encoder's included unless it is left frozen and the model
 *  has a figure for that case. 0 where the model states none. */
export function trainedEncoderParams(model: TrainModelSpec, large: boolean): number {
  if (!large && (model.te_pooled_act_gb ?? 0) > 0) {
    return model.te_pooled_params_m_per_rank ?? 0;
  }
  return model.te_params_m_per_rank ?? 0;
}

/** `sliceable` is false where the engine refuses to slice at all (MPS: it
 *  returns NaN there), so the estimate says what the run will really use.
 *  `backend` picks the activation constants — see `activationConstants`. */
export function estimateVram(config: TrainingConfig, model?: TrainModelSpec,
                             sliceable = true,
                             backend = ""): VramEstimate | null {
  if (!model || !model.backbone_gb) return null;
  const h = config.hyper;
  // fp32 doubles every resident tensor; quantization shrinks the backbone
  // only (the frozen weights it reads, not the maths it does).
  const dtypeScale = h.precision === "fp32" ? 2 : 1;
  // fp8 and int8 both store the frozen weights at one byte; nf4 at half of
  // one. Different mechanisms (a torch dtype vs bitsandbytes vs quanto), same
  // shape of saving — and it is the WEIGHTS only: the maths still runs at
  // `precision`.
  //
  // int8 reads its factor from the MODEL, because "one byte a weight" only
  // applies to the layers the quantizer converts — `Linear` — and a UNet is
  // mostly `Conv2d`. Measured, SD 1.5's UNet keeps 0.84 of its size where a
  // DiT keeps exactly 0.5. fp8 is a torch dtype applied by `apply_fp8` over
  // the same Linear selection, so it takes the same factor.
  //
  // NF4 READS ITS OWN, and used to be the flat theoretical 0.25 — which
  // nothing achieves. Measured on a 5070 Ti: FLUX.2 Klein 0.29, SDXL 0.41,
  // SD 1.5 0.81. It sits further from its floor than int8 does from a half
  // because bitsandbytes keeps per-block scales and converts less, so the
  // old constant promised SD 1.5 at 0.82 GB where the run wants 1.80 — a
  // whole GB in the direction that says a job fits when it does not.
  const int8Scale = model.int8_scale ?? 0.5;
  const quantScale = h.quantization === "nf4" ? (model.nf4_scale ?? 0.35)
    : (h.quantization === "int8" || h.quantization === "fp8") ? int8Scale : 1;
  const backbone = model.backbone_gb * dtypeScale * quantScale;
  // The text encoder(s) are most of `aux_gb`, and quantizing them is its own
  // setting — on the big models it is not a rounding error: 16.8 GB of
  // Qwen-Image's 57.7. The VAE is in `aux_gb` too and is NOT quantized, so
  // this over-states the saving by a fraction of a GB; the encoders dwarf it
  // (Qwen 16.58B params against the VAE's 0.13) and a second constant to split
  // them would be precision the estimate does not otherwise claim.
  // …and the encoders take their OWN factor, for the same reason the backbone
  // does not simply halve: a transformer block is Linear but its embedding
  // table is not, and on the small CLIP encoders that table is a large share.
  const teScale = h.quantization === "nf4" ? (model.nf4_te_scale ?? 0.4)
    : (h.quantization === "int8" || h.quantization === "fp8")
      ? (model.int8_te_scale ?? 0.5) : 1;
  // OFFLOADING BEATS QUANTIZING and is checked first: the encoder is not on
  // the card at all, so no scheme applied to it can matter. What is left of
  // `aux_gb` is the VAE, which is small (0.08-0.13B parameters against an
  // encoder's 4-8) and is itself parked on the CPU once the latents are
  // cached — so `VAE_SHARE` is a residual rather than a measurement, chosen
  // to leave the estimate a little high rather than a little low.
  //
  // Held against measurement at 4-bit on an RTX 5070 Ti — estimate against
  // resting: Chroma 5.55 against 5.29 (+4.9%), FLUX.1 7.30 against 6.98
  // (+4.6%), FLUX.2 Klein 2.59 against 2.37 (+9.3%). High in all three,
  // which is the direction that does not strand a run; Klein is the worst
  // because its encoder is the largest share of its `aux_gb`, so a flat
  // residual over-counts most there.
  const VAE_SHARE = 0.04;
  const auxScale = h.offload_text_encoder ? VAE_SHARE
    : h.quantize_text_encoder ? teScale : 1;
  const aux = model.aux_gb * dtypeScale * auxScale;
  const weights = backbone + aux;

  // What the optimizer holds per trained parameter, in BYTES — against the 2
  // a bf16 weight costs, which is what the sizes below are in. Every entry is
  // the same four things: an fp32 master copy of the parameter (4), its
  // gradient (4), and the optimizer's own running statistics.
  //
  // The 8-bit row used to be modelled as "half of AdamW", i.e. 8 bytes. That
  // is the saving on the MOMENTS alone applied to the whole term: the master
  // copy and the gradient do not shrink, so it is 10, not 8. The correction
  // moves the estimate for an 8-bit full finetune UP by a quarter, which is
  // the direction that matters — the old figure said a run fitted when it
  // did not.
  // HALF-PRECISION MASTERS TAKE TWO OF THOSE BYTES OFF, not four. Every
  // entry above is the master copy (4) plus its gradient (4) plus the
  // optimizer's own state; at bf16 the first two are 2 each, which would be
  // 4 saved — and the Kahan CARRY puts one of them back, a third buffer the
  // width of the parameter. So the term drops by 2 a parameter whatever the
  // optimizer: Adafactor 8 -> 6, AdamW 16 -> 14, 8-bit AdamW 10 -> 8. The
  // carry is what makes the setting cost nothing in quality (see
  // `scripts/kahan.py`); counting the 4 would be the estimate promising the
  // memory of the rounding-only version this replaced.
  const narrow = config.method !== "lora" && h.bf16_masters
    && h.precision !== "fp32";
  const optimizerBytes = (OPTIMIZER_BYTES[h.optimizer] ?? OPTIMIZER_BYTES.adamw)
    - (narrow ? 2 : 0);
  const perParam = optimizerBytes / 2;
  let optimizer: number;
  if (config.method === "lora") {
    // FROM THE PARAMETER COUNT, not from the file size. This used to derive
    // the trained parameters from `lora_mb_per_rank`, which is the constant
    // behind the editor's "Output size ≈" line — a FILE, written at fp32,
    // while this arithmetic reads it as bf16 and so doubles the count. On top
    // of that the constant is simply inaccurate for several models, and in
    // both directions: against measured trainable parameters at rank 16 it
    // implies 44.8M for SDXL's real 23.2M and 20.8M for FLUX.2 Klein's 3.9M,
    // but understates Chroma and Qwen-Image. Counting parameters directly
    // removes both errors at once; `lora_mb_per_rank` keeps its own job.
    const params = (model.lora_params_m_per_rank ?? 0) * h.rank * 1e6;
    optimizer = params
      ? (params * optimizerBytes) / 1e9
      // Unmeasured: fall back to the old file-size derivation rather than
      // reporting no optimizer cost at all.
      : ((model.lora_mb_per_rank * h.rank) / 1024) * perParam;
    // Training the text encoders adds their LoRA, not their weights — and
    // where the model says how big that adapter is, it is counted like the
    // backbone's rather than as a flat share of it: T5-XXL's adapter is
    // LARGER than the FLUX transformer's own, so 1.3x under-counted it by
    // half. The flat factor stays for a model with no figure.
    if (h.train_text_encoder) {
      const teParams = trainedEncoderParams(model, h.train_text_encoder_large);
      if (teParams > 0) {
        optimizer += (teParams * h.rank * 1e6 * optimizerBytes) / 1e9;
      } else {
        optimizer *= 1.3;
      }
    }
  } else {
    optimizer = model.backbone_gb * perParam;
  }
  // Weight averaging keeps one more full-precision copy of whatever is being
  // trained — 4 bytes a parameter against the 2 the sizes here are in. For a
  // LoRA that is a rounding error; for a full finetune it is another model,
  // which is exactly why it is counted rather than waved through.
  if (h.ema) {
    optimizer += (config.method === "lora"
      ? (model.lora_mb_per_rank * h.rank) / 1024
      : model.backbone_gb) * 2;
  }

  // Activations scale with the pixels per image and the batch — and gradient
  // checkpointing trades most of them back for recomputation.
  const native = model.default_area || 1024;
  // THE LARGEST SIZE THE RUN TRAINS AT: a batch holds one bucket, and what
  // a card has to survive is the biggest of them. A run adding a smaller
  // size needs no more memory than it already did; one adding a larger
  // needs what that larger one costs. 0 is the model's own size.
  const res = Math.max(...(config.buckets.resolutions ?? [0])
                            .map((r) => r || native));
  const areaScale = (res * res) / (native * native);
  const { act, ckpt, constShare, quadShare, exp, teAct } =
    activationConstants(model, backend);
  // ACTIVATIONS ARE A POLYNOMIAL IN THE PIXEL COUNT, not a power law, and the
  // three terms are three different things the hardware does:
  //
  //   constant   text conditioning, embeddings, per-layer scratch — a
  //              sequence whose length has nothing to do with the picture
  //   linear     per-image-token work: every block's activations
  //   quadratic  a MATERIALIZED attention matrix, which is N² in the tokens
  //
  // Which is why the shape differs by BACKEND rather than by model family: a
  // fused attention kernel never allocates that matrix, so CUDA has no
  // quadratic term and MPS does. Measured by fitting area sweeps (RMSE
  // against the measurements, lower is better):
  //
  //                    linear (the old rule)   affine   quadratic
  //   sdxl   [cuda]           6.4%              1.2%      1.4%
  //   klein  [cuda]          27.7%              0.3%       —
  //   sdxl   [mps]           30.3%             37.6%      0.1%
  //
  // The shares are FRACTIONS OF `act`, which is defined at the model's native
  // area — so they sum to 1 there and this reduces to exactly `act` whatever
  // they are, leaving every native-resolution constant untouched. Unset means
  // {0, 0}, i.e. purely linear, which is what the old rule did at exp 1.
  //
  // `act_exp` REMAINS as the fallback where no share has been measured, and
  // that is deliberate rather than tidy: those exponents are superlinear on
  // MPS (1.2 to 1.8), so replacing them with the plain linear default would
  // LOWER every unmeasured estimate — the one direction this number must
  // never move without evidence, because it ends with a run that was told it
  // fits and does not.
  const linShare = Math.max(0, 1 - constShare - quadShare);
  const shape = (constShare || quadShare)
    ? constShare + linShare * areaScale + quadShare * areaScale * areaScale
    : Math.pow(areaScale, exp);
  let activations = act * shape * Math.max(1, h.batch_size);
  // QUANTIZATION DOES NOT LEAVE ACTIVATIONS ALONE. The weights it shrinks are
  // dequantized per operation, and the buffer that produces is live memory —
  // so an int8 run holds MORE per image than the same run at bf16, not the
  // same. Measured at identical resolution: SD 1.5 1.14 -> 1.84 GB (x1.62)
  // and FLUX.2 Klein 5.34 -> 8.11 (x1.52). The estimate modelled only the
  // weight saving, which under-predicted exactly the runs people quantize —
  // the big models — and under-predicting is what strands a job.
  //
  // 1.6 is the higher of the two, because this factor makes the estimate
  // BIGGER and erring high refuses a run rather than losing one.
  //
  // KNOWN GAP: gradient checkpointing ALSO keeps more under quantization
  // (sd15's factor 0.241 -> 0.423, Klein's 0.122 -> 0.35), so a checkpointed
  // quantized run is still under-modelled. Two measurements disagree too much
  // (x1.76 against x2.87) to fit a second constant to them honestly.
  if (h.quantization !== "none") activations *= QUANT_ACT_FACTOR;
  if (h.gradient_checkpointing) activations *= ckpt;
  // Training the text encoder keeps ITS forward for the backward pass too.
  // Measured on SDXL at 1024 batch 1 as +1.3 GB — where the old 1.3x on the
  // optimizer term accounted for about 0.2 of it. It scales with the batch
  // (one prompt per image) but not with resolution: prompts have no pixels.
  //
  // With the LARGE encoder left frozen (FLUX.1's T5-XXL beside its CLIP-L)
  // the term is the model's `te_pooled_act_gb` instead — CLIP-L alone, a
  // few hundredths of a GB against T5's several. And the engine checkpoints
  // a trained encoder whenever the run checkpoints at all, so the same
  // factor applies: for a transformer encoder that leaves the layer inputs
  // plus one block, the same shape of number `ckpt` measures on the
  // backbone. (The SD/SDXL figures were measured before encoder-side
  // checkpointing existed and so are the no-checkpointing ones too.)
  if (h.train_text_encoder) {
    const pooledOnly = !h.train_text_encoder_large
      && (model.te_pooled_act_gb ?? 0) > 0;
    const te = pooledOnly ? (model.te_pooled_act_gb ?? 0) : teAct;
    const teCkpt = h.gradient_checkpointing ? ckpt : 1;
    activations += te * teCkpt * Math.max(1, h.batch_size);
  }
  // "auto" never slices; "on" only where the engine accepts it.
  if (h.attention_slicing === "on" && sliceable) activations *= SLICE_FACTOR;
  // Gradient accumulation costs nothing here: its passes are sequential.

  const total = weights + optimizer + activations;
  return { weights, optimizer, activations, total };
}

/** The memory a training run can draw on, in GB, or 0 when unknown.
 *
 *  A discrete GPU's own total if the stats report one; otherwise the machine's
 *  RAM, which on Apple Silicon *is* the GPU's memory. Only used to say when an
 *  estimate has already exceeded what exists.
 */
export function deviceMemoryGb(devices?: SystemDevice[],
                               want?: string): number {
  if (!devices?.length) return 0;
  const totalOf = (d: SystemDevice) =>
    d.stats.find((s) => s.key === "mem_total")?.value ?? 0;
  // THE JOB'S OWN CARD, when it names one. `cuda:N` and the stats' `gpuN`
  // are the same enumeration — `gpu.train_devices()` and `gpu.sample()` both
  // number what pynvml/nvidia-smi/rocm-smi hand back, in that order — so the
  // index maps straight across. Without this the biggest card in the machine
  // was the budget for every job: a run pinned to the 8 GB card was compared
  // against the 24 GB one and told it fitted.
  const pinned = /^cuda:(\d+)$/.exec(want || "");
  if (pinned) {
    const card = devices.find((d) => d.key === `gpu${pinned[1]}`);
    const gb = card ? totalOf(card) : 0;
    if (gb > 0) return gb;
    // Fall through where that device reports no total — an Apple GPU box has
    // none (memory is unified and the system row carries it), and a card the
    // stats probe could not read should not answer "0 GB, nothing fits".
  }
  const gpu = devices.filter((d) => d.key.startsWith("gpu")).map(totalOf);
  const best = Math.max(0, ...gpu);
  if (best > 0) return best;
  const system = devices.find((d) => d.key === "system");
  return system ? totalOf(system) : 0;
}

/** "12 GB" / "3.4 GB" / "820 MB" — memory at the precision it deserves.
 *  The optional locale localizes only the decimal separator ("3,4 GB"). */
export function fmtGb(gb: number, locale?: string): string {
  if (gb <= 0) return "?";
  if (gb < 1) return `${Math.round(gb * 1024)} MB`;
  return `${gb < 10 ? fixed1(gb, locale) : Math.round(gb)} GB`;
}

export function fmtSize(mb: number, locale?: string): string {
  if (mb <= 0) return "?";
  if (mb >= 1024) return `${fixed1(mb / 1024, locale)} GB`;
  if (mb >= 1) return `${Math.round(mb)} MB`;
  return `${Math.max(1, Math.round(mb * 1024))} KB`;
}

function fixed1(v: number, locale?: string): string {
  if (!locale) return v.toFixed(1);
  return formatNumber(locale, v, {
    minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false });
}

/** Human text from an api.ts error: req<T> throws `Error("<status>: <body>")`
 *  where the body is FastAPI JSON — unwrap {"detail": "..."} to the message. */
export function errText(e: unknown): string {
  // ANY error's class name, not just the bare `Error:` — the app's own is
  // `ApiError`, so every refusal this shows read "ApiError: the model still
  // has to be downloaded", which is the one word in the sentence that means
  // nothing to the person reading it.
  const raw = String(e).replace(/^\w*Error:\s*/, "")
    .replace(/^\d+:\s*/, "").trim();
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
  } catch { /* not JSON — use as-is */ }
  return raw;
}

/** Compact duration: "47s", "12m 30s", "3h 07m". */
export function fmtDur(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

/** WHAT THIS JOB'S GPU AND MODEL CANNOT DO — per ROW, and per OPTION.
 *
 *  Every one of these is enforced by the trainer, which raises rather than
 *  quietly training something other than what was asked for. The point of
 *  saying it in the editor is that the trainer says it minutes into a run,
 *  after the model has loaded; here it is visible while choosing.
 *
 *  **The two halves are different claims and used differently.** `rows` is a
 *  setting that does not apply at all — a full finetune has nothing to
 *  quantize — so its control is DISABLED. `values` names the choices this
 *  machine cannot run, and there the control stays live with those entries
 *  disabled inside it: a list that hides them cannot say a machine is what is
 *  missing, and one that dims the whole row says the supported choices are
 *  unavailable too. The row's chip is then whether the CURRENT value is one
 *  of them, which is the fix for a row that read "NVIDIA only" while set to
 *  "None" — a value every machine runs.
 *
 *  Keyed by dotted paths. Pure, so the rules are testable without a browser. */
export interface Unsupported {
  /** Dotted path → why the whole setting cannot apply here. */
  rows: Record<string, string>;
  /** Dotted path → option value → why that value cannot run here. */
  values: Record<string, Record<string, string>>;
}

export function unsupportedReasons(
  config: TrainingConfig, model: TrainModelSpec | undefined, device: string,
  /** Whether this machine can slice attention at all (`status.slices_attention`
   *  — false on Apple silicon, where the trainer uses the efficient default
   *  and slicing returns NaNs). Unknown means "assume it can". */
  canSliceAttention = true,
): Unsupported {
  const rows: Record<string, string> = {};
  const values: Record<string, Record<string, string>> = {};
  const h = config.hyper;
  // "auto" is whatever the machine's first device is; the caller resolves it.
  const cuda = device.startsWith("cuda");
  const isLora = config.method === "lora";

  if (!isLora) {
    rows["hyper.quantization"] = "a full finetune trains the base weights, so there is nothing to quantize";
    // The engines guard it with `train_te and method == "lora"`, so on a full
    // finetune the flag is simply ignored — say that here rather than let it
    // read as a setting that did nothing.
    rows["hyper.train_text_encoder"] = "only offered for LoRA training";
    rows["hyper.quantize_text_encoder"] = "a full finetune trains the base weights, so there is nothing to quantize";
  }
  if (config.method === "lora") {
    rows["hyper.bf16_masters"] = "only for a full finetune";
  }
  if (h.precision === "fp32") {
    rows["hyper.bf16_masters"] = "nothing to halve at full precision";
  }
  if (h.optimizer === "prodigy") {
    rows["hyper.bf16_masters"] = "Prodigy cannot be stepped one weight at a time";
  }
  if (!cuda) {
    // Per VALUE, not per row: "None" is what every machine does, so a row-wide
    // refusal was telling somebody their default was unavailable.
    //
    // **int8 is NOT in this list any more.** It runs off CUDA through
    // optimum-quanto, measured end to end on Apple silicon — it is what makes
    // Qwen-Image trainable on a Mac at all. fp8 needs an Ada-or-newer NVIDIA
    // dtype and nf4 needs bitsandbytes, so those two stay.
    values["hyper.quantization"] = {
      fp8: "needs an NVIDIA GPU (Ada or newer)",
      nf4: "needs an NVIDIA GPU",
    };
  }
  // Quantizing the encoder means freezing it at one byte a weight, which is
  // not something gradients can update — the trainer refuses the pair, so say
  // so before the save does.
  //
  // NOT reported when quantization is simply "none": that is the DEFAULT, and
  // a chip on a default row is the exact mistake the per-value rules above
  // exist to undo. The toggle is disabled there and its hint says what it
  // needs; "unsupported" is for what this machine or model cannot do.
  // QUANTIZING a trained encoder is allowed now — the adapter trains over
  // the quantized weights exactly as it does over the quantized backbone,
  // and it is what lets T5-XXL train on a 32 GB card. OFFLOADING one is
  // not: an encoder on the CPU cannot be the one gradients flow through,
  // and the backend refuses the pair. The row was once disabled with
  // nothing but its hint, so the one thing on screen that could have said
  // why was not there.
  if (isLora && h.train_text_encoder) {
    rows["hyper.offload_text_encoder"] = "cannot be combined with training the text encoder";
  }
  if (!cuda) values["hyper.optimizer"] = { adamw_8bit: "needs an NVIDIA GPU" };
  // fp16 is not refused on Apple silicon — it is silently ignored, which is
  // worse: `pick_dtype` never returns it there (a known NaN factory) and the
  // run trains in fp32, at twice the memory the estimate below shows.
  if (device === "mps") {
    values["hyper.precision"] = { fp16: "not used on Apple silicon, where the run trains in fp32" };
  }
  if (!canSliceAttention) {
    values["hyper.attention_slicing"] = { on: "not available on Apple silicon" };
  }
  // An EXPLICIT 0 means the engine trains no text encoder — not a hardware
  // limit but the same kind of "this does nothing here". A missing value (an
  // older API, a user model) is unknown, not "none", so it must NOT disable the
  // toggle — that mistook every model for having none.
  if (isLora && model && model.te_act_gb === 0) {
    rows["hyper.train_text_encoder"] = "this model has none";
  }
  // …but every model HAS a text encoder to quantize, trainable or not:
  // `te_act_gb === 0` says the engine does not train one, which is exactly the
  // case where quantizing it costs nothing at all.
  // Per value again: LoRA is offered, a full finetune is the one that cannot
  // run — the row itself is a live choice with one entry out of reach.
  if (model?.lora_only) {
    values["method"] = { full: "too large to finetune on any GPU this app has constants for" };
  }
  return { rows, values };
}


/** IS THIS A HUGGING FACE REPO OR A PATH ON THIS MACHINE?
 *
 *  Read off the string rather than asked with a dropdown. The two shapes do
 *  not overlap in practice — a hub id is `owner/repo`, two segments and
 *  nothing else — so a control asking which one you had just typed was a
 *  question whose answer was already on screen.
 *
 *  A PATH is anything that says so: an absolute or home-relative start, a
 *  Windows drive, an explicit `./`, a weights file by extension, or simply
 *  more (or fewer) than the two segments a repo id has. Ambiguity resolves to
 *  the REPO, because `owner/repo` is also a legal relative path and the hub is
 *  what that spelling means to everyone.
 */
export function looksLikeLocalPath(s: string): boolean {
  const v = s.trim();
  if (!v) return false;
  if (/^[~/\\]/.test(v)) return true;            // /x, ~/x, \\server\share
  if (/^[A-Za-z]:[\\/]/.test(v)) return true;     // C:\x, C:/x
  if (/^\.{1,2}[\\/]/.test(v)) return true;       // ./x, ../x
  if (/\.(safetensors|ckpt|pt|bin|gguf)$/i.test(v)) return true;
  if (v.includes("\\")) return true;              // any backslash separator
  // `owner/repo` is exactly two non-empty segments; anything else is a path.
  const parts = v.split("/");
  return !(parts.length === 2 && parts[0] !== "" && parts[1] !== "");
}

/** The models list, with each user model directly under the built-in it was
 *  based on.
 *
 *  A user model is a variant of one specific built-in — that is what `base`
 *  says — so listing every user model after every built-in made you match
 *  names by eye to see which was which. Anything whose base is not in this
 *  group (an older entry, a base since removed) falls to the end rather than
 *  disappearing. */
export function nestUserModels(
  group: TrainModelSpec[],
): { model: TrainModelSpec; child: boolean }[] {
  const builtins = group.filter((m) => !m.user);
  const users = group.filter((m) => m.user);
  const out: { model: TrainModelSpec; child: boolean }[] = [];
  const placed = new Set<string>();
  for (const b of builtins) {
    out.push({ model: b, child: false });
    for (const u of users) {
      if (u.base === b.key) { out.push({ model: u, child: true }); placed.add(u.key); }
    }
  }
  for (const u of users) {
    if (!placed.has(u.key)) out.push({ model: u, child: true });
  }
  return out;
}

/** A cadence in STEPS, for the countdowns in the phase strip.
 *
 *  The run reports what it resolved, and that is the answer whenever it has
 *  one: a cadence set in EPOCHS becomes a step count only when the built
 *  manifest says how long a pass is, so the config's step field is the one
 *  the epoch setting overruled — read straight, a job set to "every 2
 *  epochs" counted down to a step nothing was going to happen at.
 *
 *  Before the run has said (it reports with its first state write, so this
 *  is the load phase and a job that has never started), a STEP cadence is
 *  exact and an EPOCH one is simply not knowable — 0, which draws no dot,
 *  rather than a number that is going to be wrong. */
export function cadenceSteps(reported: number | undefined,
                             epochs: number | undefined,
                             steps: number | undefined): number {
  if (reported && reported > 0) return reported;
  return (epochs ?? 0) > 0 ? 0 : (steps ?? 0);
}

/**
 * WHETHER A TOGGLE IS LOCKED — and it is only ever locked OFF.
 *
 * A disabled control must never be the only way out of the state it is in.
 * Three of these rows are refused BY THE BACKEND in combination with
 * something else (a quantized or offloaded text encoder cannot be trained;
 * encoder quantization needs a scheme), and each of them disabled itself the
 * moment the conflict appeared — including when it was already ON. That is a
 * config the editor will not save and will not let you fix: the error names
 * the toggle to turn off and the toggle cannot be turned off.
 *
 * So a conflict stops it being switched ON and never stops it being switched
 * off. The `unsupported` chip beside it is what says why; the row staying
 * live is what makes the chip actionable.
 */
export function toggleLocked(cannot: boolean, checked: boolean): boolean {
  return cannot && !checked;
}
