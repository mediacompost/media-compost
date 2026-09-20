/** The trainer's client: every `/api/train/*` call and its types.
 *
 * CUT out of the app's api.ts, which no longer knows these endpoints exist —
 * that is what lets the whole train UI load lazily and an install without
 * `[training]` never fetch it. The shared read slice (`itemsQuery`, `tags`,
 * `thumbUrl`, the HF/setup machine state) is spread in from `shared/api`, the
 * same one the query builder uses.
 */

import type { Group as QueryGroup } from "../query/tree";

import { api as sharedApi, req } from "../shared/api";
import type { SetupStatus } from "../shared/api";
import { apiFetch } from "../shared/build";

// A model-specific hyperparameter declared by the backend registry; the job
// editor renders these generically (no hardcoded per-model UI).
export interface TrainFieldSpec {
  name: string;
  type: "int" | "float" | "bool" | "choice";
  default: unknown;
  label: string;
  hint: string;
  // Long-form explanation behind the editor's "?" button.
  details?: string;
  min?: number | null;
  max?: number | null;
  choices: string[];
}

/** A LoRA file registered by the user (Models tab -> LoRAs). */
export interface UserLoraOut {
  key: string;
  label: string;
  model: string;     // the base model key it was trained for
  path: string;
  exists: boolean;
}

export interface TrainModelSpec {
  key: string;
  // Weights already present in the Hugging Face cache (or, for a local user
  // model, at its path).
  cached?: boolean;
  // Weights half-fetched by an interrupted download — resumable, not missing.
  partial?: boolean;
  // On-disk bytes of the downloaded weights; 0 when they are not in the
  // Hugging Face cache (not fetched, or a local path we did not fill).
  size?: number;
  // Live download state (present only while one is running / just failed).
  downloading?: boolean;
  // Accepted but WAITING for a download slot — nothing is moving yet.
  queued?: boolean;
  progress?: number;
  done_bytes?: number;
  total_bytes?: number;
  download_error?: string;
  // True for a user-added model; `local` marks a filesystem path and `base`
  // names the built-in architecture it follows.
  user?: boolean;
  local?: boolean;
  base?: string;
  label: string;
  // The architecture — several entries can share one (Chroma's two
  // releases), and it is what the Models tab groups by.
  engine?: string;
  /** The layer names the adapter's two filter fields offer, derived from the
   *  ARCHITECTURE rather than from the checkpoint — a user model based on
   *  SDXL has SDXL's module names. Optional: a `node --test` helper builds a
   *  partial spec, and a model whose engine has no table offers nothing
   *  rather than another architecture's names. */
  layer_hints?: string[];
  repo: string;
  default_area: number;
  lora_only: boolean;
  /** The repo needs a licence accepted and a token to download — shown as a
   *  chip, exactly as the Settings model list shows one. */
  gated?: boolean;
  /** Whether this checkpoint is image-conditioned — it takes reference
   *  pictures beside the prompt, which is what makes an INSTRUCTION run
   *  possible. Optional so the `node --test` helpers that build a partial
   *  spec keep compiling. */
  edit?: boolean;
  /** …and whether editing is what it is FOR — its pipeline takes a reference
   *  picture as the subject of the call. Decides which caption source the
   *  editor starts on, and nothing else: an editing checkpoint CAN be trained
   *  text-to-image, it is just not what anyone uses it for. */
  edit_only?: boolean;
  default_lr: number;
  note: string;
  // Size-estimate constants: LoRA file ≈ lora_mb_per_rank·rank; full ≈ full_gb.
  lora_mb_per_rank: number;
  full_gb: number;
  // The CUDA activation constants, 0 where unmeasured for this model — see
  // activationConstants: fused attention makes them 1.7-8.5x smaller there.
  act_gb_cuda?: number;
  ckpt_factor_cuda?: number;
  /** What training the text encoder adds on CUDA. A twin for the same reason
   *  `act_gb` has one: SDXL measured 1.3 GB on MPS and 0.364 on an RTX 5090,
   *  so the shared figure is the MPS one. 0 falls back to it. */
  te_act_gb_cuda?: number;
  /** The same term with the large encoder left frozen — only the small
   *  pooled encoder(s) training. 0 = there is no such option for this model
   *  (no large encoder, or no small one beside it), and the editor hides
   *  the switch. */
  te_pooled_act_gb?: number;
  /** Millions of trainable parameters per rank the encoder adapter(s) add —
   *  `lora_params_m_per_rank`'s twin, for the optimizer term. 0 falls back
   *  to a flat 1.3x on the backbone's own term. */
  te_params_m_per_rank?: number;
  /** …and with the large encoder left out. */
  te_pooled_params_m_per_rank?: number;
  /** The OLD area rule, `act_gb · areaRatio^exp`, kept as the fallback for a
   *  model whose shares below are unmeasured. Those exponents are superlinear
   *  on MPS (1.2-1.8), so dropping them would lower every unmeasured estimate
   *  — the one direction this number must not move without evidence. */
  act_exp?: number;
  act_exp_cuda?: number;
  /** How activations SPLIT, as fractions of `act_gb` at the native area: a
   *  part that does not scale with the picture at all (text conditioning,
   *  embeddings, scratch), a part linear in the pixel count (per-token work),
   *  and a part quadratic in it (a materialized N×N attention matrix).
   *  Whatever is left over is the linear share, so {0,0} is the plain linear
   *  rule and means nobody has measured this model.
   *
   *  The quadratic share is a fact about the BACKEND more than the model: a
   *  fused attention kernel never allocates that matrix, so it is 0 on CUDA
   *  and real on MPS. Measured by fitting area sweeps — see
   *  `activationConstants`. */
  act_const_share?: number;
  act_quad_share?: number;
  act_const_share_cuda?: number;
  act_quad_share_cuda?: number;
  /** Trainable parameters, in MILLIONS per LoRA rank — what the optimizer
   *  actually holds state for. Distinct from `lora_mb_per_rank`, which is the
   *  FILE the run writes; deriving one from the other was wrong by up to 5x
   *  and in both directions. 0 means unmeasured. */
  lora_params_m_per_rank?: number;
  /** What int8 leaves of the backbone / of the text encoders. 0.5 for an
   *  all-Linear DiT; a UNet keeps more, because quantizers convert `Linear`
   *  and a UNet is mostly `Conv2d`. Absent means the old flat 0.5. */
  int8_scale?: number;
  int8_te_scale?: number;
  /** The same two for nf4, which does NOT reach its theoretical 0.25:
   *  measured 0.29 (FLUX.2 Klein), 0.41 (SDXL), 0.81 (SD 1.5). Absent means
   *  the 0.35 default, which sits above every DiT reading rather than below
   *  them — this factor makes the estimate smaller. */
  nf4_scale?: number;
  nf4_te_scale?: number;
  // Memory-estimate constants in GB at bf16 (see estimateVram).
  backbone_gb: number;
  aux_gb: number;
  act_gb: number;
  // What fraction of act_gb survives gradient checkpointing.
  ckpt_factor: number;
  /** What training the text encoder adds per image; 0 = this model has none
   *  to train, so the setting is disabled rather than silently ignored. */
  te_act_gb: number;
  params: TrainFieldSpec[];
}

export interface TrainStatus {
  env_ready: boolean;
  // Non-empty when downloads are switched off in the environment.
  env_offline?: string;
  // A Hugging Face token is set for this server session.
  token_available?: boolean;
  // "auto" attention slicing resolves to on here (Apple Silicon).
  slices_attention?: boolean;
  running_uid: string | null;
  /** Device an Evaluate generation is rendering on, when one is — the two
   *  tabs share the GPU, so a job pinned to it is waiting rather than idle. */
  evaluating_device?: string | null;
  models: TrainModelSpec[];
  // The machine's trainable devices ("cuda:0" / "mps" / "cpu") for the job
  // editor's GPU dropdown. One job runs per device.
  devices: TrainDevice[];
}

/** One device a job can be pinned to. `id` is the torch device string, which
 *  is also what `estimateVram`'s backend is read off. */
export interface TrainDevice {
  id: string;
  label: string;
}

export interface GpuStat {
  key: string;
  label: string;
  value: number;
  unit: string;
  /** What the HARDWARE says the ceiling is, where it says one — a fan is
   *  reported as a percentage of its own maximum, and a power limit is
   *  enforced by the driver. Absent means no bar is drawn: one measured
   *  against a guessed ceiling is a number the reader cannot check. */
  max?: number;
}

// One stats box: a GPU (one per physical GPU), the CPU, or RAM. `label` is
// the device/model name shown as the box title.
export interface SystemDevice {
  key: string;
  label: string;
  stats: GpuStat[];
  /** Why a figure is missing, as a key this package words — "powermetrics"
   *  when macOS refused the temperature/power/fan sampler. "" when nothing
   *  is missing. */
  hint?: string;
}

export interface TrainCheckpoint {
  step: number;
  // false = the cadence snapshot existed but was auto-pruned by keep-last-N.
  exists: boolean;
  size: number; // bytes
  /** Locked: can't be deleted, and keep-last-N pruning skips it. */
  locked?: boolean;
  /** The run's resume point (what a pause saved) — never deletable. */
  resume?: boolean;
  /** A permanent snapshot exists at this step. */
  snapshot?: boolean;
  t: number;
  train_seconds: number;
}

// One usable LoRA weight set: a job's final output (step null, final_step =
// its trained steps) or a surviving step checkpoint (step = that step).
export interface TrainLoraSource {
  job_uid: string;
  name: string;
  model: string;
  step: number | null;   // null = the job's final output
  // The final output's trained step count (0 on checkpoint entries).
  final_step: number;
  path: string;          // stored in a job's config.init_lora
  /** Protected: a checkpoint is safe from deletion and from auto-pruning, and
   *  either kind survives the deletion of its job (it moves into the user's
   *  own LoRA list). */
  locked?: boolean;
}

export interface EvalLora {
  job_uid: string;      // "" for a LoRA added by hand on the Models tab …
  user_key?: string;    // … which carries its key here instead
  name: string;
  model: string;
  step: number | null;
  final_step: number;
}

/** A full finetune that can stand in for a base model's weights: a finished
 *  full-finetune job's output, or one of its surviving checkpoints. */
export interface EvalFinetune {
  job_uid: string;
  name: string;
  model: string;
  step: number | null;   // null = the job's finished output
  final_step: number;
}

export interface EvalRunFinetune {
  job_uid: string;
  step: number | null;
  /** Filled in by the server for the cards; not part of what is sent. */
  name?: string;
  path?: string;
}

export interface EvalRunLora {
  job_uid: string;
  user_key?: string;   // a hand-added LoRA, in place of a job
  step: number | null; // null = final output
  name: string;
  weight: number;
}

export interface EvalRunBody {
  model: string;
  /** Generate with a full finetune's weights instead of the base model's.
   *  One or none — a finetune IS the network, not a layer on it. */
  finetune?: EvalRunFinetune | null;
  loras: EvalRunLora[];
  prompt: string;
  negative: string;
  width: number;        // 0 = automatic (model native)
  height: number;
  seed: number | null;  // null = automatic (random, recorded on the run)
  steps: number;
  cfg: number;
  count: number;
  // Images generated in one pipeline call (1 = one at a time).
  batch: number;
}

export interface EvalRun {
  uid: string;
  status: string; // running | completed | failed | canceled
  phase: string;
  /** Short progress line for that phase ("62 / 162", the model repo). */
  phase_note?: string;
  /** What the run trains on, from when its dataset was materialized —
   *  `frames` is how many of those images came out of a film, absent when
   *  none did. */
  dataset?: { images?: number; buckets?: number; frames?: number };
  error: string;
  created_at: number;
  username: string;
  model: string;
  /** The finetune this run generated with, if any. */
  finetune?: EvalRunFinetune;
  loras: EvalRunLora[];
  prompt: string;
  negative: string;
  width: number;
  height: number;
  seed: number;
  steps: number;
  cfg: number;
  count: number;
  images: string[];
  // Wall time of the run in seconds, 0 until the generator reports one.
  elapsed: number;
  /** Denoising step reached in the batch being rendered (0 when not running).
   *  `steps` is what was asked for; this is where it has got to. */
  cur_step?: number;
  batch?: number;
}

// Mirrors backend training/spec.py TrainingConfig (the config.json shape).
export interface TrainDatasetQuery {
  tree: QueryGroup | null;
  search: string;
  weight: number;
  /** A REGULARIZATION pool: pictures that remind the model what it already
   *  knows rather than teaching it something new. Such an entry never carries
   *  the trigger word, and its loss is scaled by `reg_strength`. An item also
   *  matched by an ordinary pool is NOT one — being asked for by name wins. */
  regularize: boolean;
}

export interface TrainHyper {
  steps: number;
  /** Full passes over the dataset; 0 = the run's length is `steps`. Resolved
   *  to a step count by the trainer, the only place the number of dataset
   *  entries is known. */
  epochs: number;
  lr: number;
  lr_scheduler: "constant" | "cosine" | "linear" | "constant_with_warmup";
  warmup_steps: number;
  batch_size: number;
  grad_accum: number;
  /** Which kind of adapter. "lokr" builds the weight change as a Kronecker
   *  product instead of a low-rank one: a fraction of the file size, and not
   *  confined to the rank the way a LoRA is. It is not a diffusers LoRA, so
   *  no portable file is written for it. */
  network: "lora" | "lokr";
  /** Which layers of the image backbone the adapter attaches to, as plain
   *  substrings of a module's path. Empty include = every attention
   *  projection; exclude wins. A filter matching nothing is refused by the
   *  trainer rather than training an adapter over no layers. */
  layer_include: string[];
  layer_exclude: string[];
  /** How a weight is split into LoKr's two factors; -1 = the squarest split
   *  (the smallest factors). LoKr only. */
  lokr_factor: number;
  rank: number;
  alpha: number;
  precision: "bf16" | "fp16" | "fp32";
  seed: number;
  checkpoint_every: number;
  /** The cadence said in EPOCHS instead; 0 leaves `checkpoint_every`
   *  in charge. Resolved to steps by the trainer, like `epochs`. */
  checkpoint_epochs: number;
  /** Newest N snapshots to keep (0 = don't keep by recency). */
  checkpoint_keep: number;
  /** Also keep every Nth snapshot, for good (0 = off). The two are a union. */
  checkpoint_keep_every?: number;
  train_text_encoder: boolean;
  te_lr: number;
  te_stop_ratio: number;
  /** Whether the LARGE sequence encoder trains too where a model has one
   *  beside a small pooled encoder (FLUX.1: T5-XXL beside CLIP-L). Off, only
   *  CLIP-L trains. Ignored by a model with no such pair. */
  train_text_encoder_large: boolean;
  /** Keep a smoothed second copy of the trained weights and save THAT as the
   *  checkpoints, the result and the samples. Training is unaffected. */
  ema: boolean;
  /** Fraction of the old average kept per step: 0.999 ≈ the last 1000 steps. */
  ema_decay: number;
  gradient_checkpointing: boolean;
  /** What turns gradients into weight changes — mostly a memory choice.
   *  See util.OPTIMIZER_BYTES for what each holds per trained parameter. */
  optimizer: "adamw" | "adamw_8bit" | "adafactor" | "prodigy";
  cache_latents: boolean;
  /** Full finetune only: keep the trained weights (and their gradients) at
   *  16 bits, with the updates rounded stochastically so they land at all.
   *  Halves the term that IS the memory on a full run. */
  bf16_masters: boolean;
  quantization: "none" | "fp8" | "int8" | "nf4";
  /** Quantize the text encoder(s) too, in the same scheme. Its own switch
   *  because it shrinks `aux_gb` where the setting above shrinks
   *  `backbone_gb` — see estimateVram. */
  quantize_text_encoder: boolean;
  /** Keep the frozen text encoder(s) in system RAM and embed there, so none
   *  of their weights occupy VRAM (where quantizing leaves about a third). */
  offload_text_encoder: boolean;
  attention_slicing: "auto" | "on" | "off";
}

// WHICH NOISE LEVELS a run trains on. High noise decides a picture's layout,
// low noise its detail and texture, so where a run spends its steps decides
// what it mostly teaches. "default" is the model family's own choice and is
// exactly what every run did before this existed.
export interface TrainNoise {
  timesteps: "default" | "uniform" | "logit_normal" | "cosmap";
  /** Where the bell curve's centre sits: 0 is the middle, positive leans
   *  towards layout, negative towards detail. "logit_normal" only. */
  logit_mean: number;
  /** How wide it is — smaller concentrates on a narrower band. */
  logit_std: number;
}

export interface TrainBuckets {
  /** THE SIZES THIS RUN TRAINS AT, with no first among them. Each opens its
   *  own family of aspect-ratio buckets, and every picture contributes one
   *  entry at each size it is big enough for. 0 IS A MEMBER and means the
   *  model's own size. Normalized by the backend (a set, smallest first,
   *  never empty), so this is always sorted. */
  resolutions: number[];
  bucket_step: number;
  max_aspect: number;
  random_crop: boolean;
  /** Leave out an image smaller than its bucket instead of enlarging it. */
  skip_upscale: boolean;
  flip_p: number;
  // Tags that veto mirroring for the images carrying them.
  no_flip_tags: string[];
  /** The same veto, by what the LIBRARY marks a tag with. */
  no_flip_meta_tags: string[];
  // Masked training: weight each latent cell's loss by the source image's
  // alpha, so a cut-out subject is learned without its absent surroundings.
  alpha_mask: boolean;
  // What a fully transparent cell still counts for (0 = ignore it entirely).
  alpha_bg_weight: number;
  // Masked REGIONS: down-weight the loss inside these tags' bounding boxes
  // (a watermark, a caption strip), so the run trains on pictures carrying
  // one without teaching the model to draw it. Loss-only — the pixels still
  // reach the encoder, so the cached latents stay the shared ones.
  mask_loss_tags: string[];
  /** The same rule, by what the LIBRARY marks a tag with. */
  mask_loss_meta_tags: string[];
  // What a masked cell still counts for (0 hides the region entirely).
  mask_loss_weight: number;
}

// A loss the run cannot flatter: held-out images scored at a cadence with a
// fixed seed and the plain per-sample loss, plus a fixed slice of training
// images scored the same way (the training curve with the noise removed).
export interface TrainValidation {
  every_n_steps: number;
  // Whole images held OUT of training (clamped to half the dataset).
  holdout: number;
  // Fixed TRAINING images re-scored each round — the "stable" loss.
  stable_items: number;
  // Seeds every round's noise, timesteps, crops and prompt picks.
  seed: number;
}

export interface TrainValueRule {
  namespace: string;
  op: "=" | "!=" | ">" | ">=" | "<" | "<=";
  value: number;
  unit: string;
  text: string;
  keep_raw: boolean;
}

export interface TrainCaptions {
  /** "instructions" trains an EDIT model: the prompt is one of the item's
   *  instructions and the picture is the result its reference images produce.
   *  One enum, so a run can never mix a description with an imperative.
   *  "none" is the TRIGGER WORD ALONE — no tags, no caption, nothing the
   *  item says about itself, and every selected picture is in the run
   *  whatever it carries. */
  source: "captions" | "tags" | "both" | "instructions" | "none";
  trigger: string;
  // Which of an item's captions this run may use, by META TAG (the link/caption
  // namespace). Empty include = all of them; exclude wins over include.
  include_meta_tags: string[];
  exclude_meta_tags: string[];
  always_tags: string[];
  exclude_tags: string[];
  /** The same two rules, naming tags by what the LIBRARY says about them
   *  rather than one by one. Unioned with the lists above when the dataset is
   *  materialized, so the trainer reads one list per rule. */
  always_tag_meta_tags: string[];
  exclude_tag_meta_tags: string[];
  /** Prompt rules over VALUE tags (`height:172cm`): a matching tag is
   *  written as the rule's text (`keep_raw` keeps the raw tag alongside).
   *  First match wins — the list's order is part of the configuration. */
  value_rules: TrainValueRule[];
  // Whole per-item tag groups to ignore, named by the group's meta tag. A tag
  // is dropped only when every placement of it sits in an excluded group.
  exclude_tag_group_meta_tags: string[];
  min_tags: number;
  max_tags: number;
  balance: "none" | "inverse_freq";
  freq_base: "dataset" | "library";
  loss_weight_by_freq: boolean;
  shuffle: boolean;
  dropout: number;
  /** Chance of writing a picked tag as one of its aliases instead of its
   *  canonical name, rolled per tag per visit. Only the prompt changes:
   *  matching, balancing, loss weights and boxes stay on the canonical
   *  name. 0 is what every run did before this existed. */
  /** What an item with several captions does with them: one drawn per visit,
   *  one visit each, or one visit each sharing a single item's weight. */
  caption_repeat: "random" | "each" | "each_shared";
  alias_p: number;
  /** How a picked tag is WRITTEN: its name, its comment (the one-liner in
   *  the tags list), or the name with the comment after it. Prompt only. */
  tag_text: "name" | "comment" | "both";
  underscores_to_spaces: boolean;
  separator: string;
  // Lay the picked tags out one block per tag group, with the group's own name
  // in front when asked, blocks joined by `group_separator` (a newline).
  group_tags: boolean;
  /** What each block is labelled with: nothing, the group's name, or the
   *  subjects it is about. */
  group_label: "none" | "group" | "subject";
  group_separator: string;
  skip_partial_tags: boolean;
}

// One test-sample slot: a prompt with its OWN negative prompt.
export interface TrainSamplePrompt {
  prompt: string;
  negative: string;
  // Per-prompt size override; 0 = use the section's shared size (which in turn
  // falls back to the training resolution).
  width?: number;
  height?: number;
}

export interface TrainSampling {
  every_n_steps: number;
  // The same cadence in EPOCHS — above 0 it wins, and the trainer resolves
  // it once the built manifest says how long a pass is. Sampling is off
  // only when both are 0.
  every_n_epochs: number;
  at_start: boolean;
  prompts: TrainSamplePrompt[];
  seed: number;
  steps: number;
  cfg: number;
  // Sample prompts rendered in one pipeline call (grouped by size).
  batch: number;
  width: number;
  height: number;
}

// Videos as training images: off by default, and when on, a video's frames
// are extracted while the dataset is materialized and trained on as images.
export interface TrainVideo {
  include: boolean;
  every: number;
  unit: "seconds" | "frames";
  dedupe: boolean;
  // What a frame does with the FILM's captions. A tag has time ranges to say
  // when it holds; a caption has not, so this is where a film says which of
  // its captions describe its frames rather than the whole of it.
  captions: "inherit" | "none";
  // …and which of them, by meta tag. Applied on top of the run's own caption
  // filter, never instead of it.
  caption_include_meta_tags: string[];
  caption_exclude_meta_tags: string[];
}

// A closed range a value is drawn from. lo === hi is a fixed value, which is
// what makes "one number" a special case of the shape rather than a second one.
export interface TrainRange {
  lo: number;
  hi: number;
}

// One way of making a picture look worse, as an EXTRA training sample beside
// the clean one. See the backend's spec.DegradeVariant for the full rules.
export interface TrainDegradeVariant {
  name: string;
  method: "jpeg" | "video" | "resize";
  // Drawn RELATIVE to the clean entry, which is always 1.0.
  weight: number;
  // Always in this entry's prompt.
  tags: string[];
  // Taken off this entry when the item carries them (quality claims the
  // degraded copy no longer supports).
  remove_tags: string[];
  /** The three rules above and below, by what the LIBRARY says about a tag. */
  remove_tag_meta_tags: string[];
  // Which pictures this variant may touch. Empty require = every picture;
  // skip wins over require.
  require_tags: string[];
  skip_tags: string[];
  require_tag_meta_tags: string[];
  skip_tag_meta_tags: string[];
  // Separately-drawn entries per picture.
  variations: number;
  passes: TrainRange;
  quality: TrainRange;
  subsampling: "4:4:4" | "4:2:2" | "4:2:0";
  codec: "h264" | "h265";
  crf: TrainRange;
  scale: TrainRange;
  resample: "nearest" | "bilinear" | "bicubic" | "lanczos";
}

export interface TrainDegrade {
  variants: TrainDegradeVariant[];
}

export interface TrainingConfig {
  model: string;
  local_path: string;
  method: "lora" | "full";
  // Path of an existing LoRA to start from ("" = train from scratch).
  init_lora: string;
  // "auto" or a device id from TrainStatus.devices ("cuda:1", "mps").
  gpu: string;
  hyper: TrainHyper;
  queries: TrainDatasetQuery[];
  /** What a query's weight buys: "sampling" spends it on how often those
   *  images are visited, "loss" on how much each visit counts. Same ratio,
   *  different lever. */
  weight_mode: "sampling" | "loss";
  /** How much a regularization picture's loss counts, against 1 for a
   *  training picture. Only meaningful when a pool is marked `regularize`. */
  reg_strength: number;
  buckets: TrainBuckets;
  noise: TrainNoise;
  captions: TrainCaptions;
  video: TrainVideo;
  degrade: TrainDegrade;
  sampling: TrainSampling;
  validation: TrainValidation;
  model_params: Record<string, unknown>;
}

export interface TrainingJobSummary {
  uid: string;
  name: string;
  username: string;
  // draft | queued | running | pausing | paused | completed | failed | canceled
  status: string;
  step: number;
  total_steps: number;
  message: string;
  phase: string;
  /** Short progress line for that phase ("62 / 162", the model repo). */
  phase_note?: string;
  /** The in-step phase while training: batch | forward | backward | update. */
  phase_sub?: string;
  // The checkpoint and sample cadences AS THE RUN RESOLVED THEM, in steps
  // — 0 before it has started once. A cadence set in EPOCHS is a step count
  // only after the built manifest says how long a pass is, so these are the
  // only honest source for a countdown.
  ckpt_every?: number;
  sample_every?: number;
  /** What the run trains on, from when its dataset was materialized —
   *  `frames` is how many of those images came out of a film, absent when
   *  none did. */
  dataset?: { images?: number; buckets?: number; frames?: number };
  model: string;
  method: string;
  /** Which kind of adapter, when the method is one ("lora" | "lokr"); empty
   *  for a full finetune. `method` cannot say it — see the card. */
  network?: string;
  created_at: number | null;
  queued_at: number | null;
  started_at: number | null;
  finished_at: number | null;
}

export interface TrainingJobDetail extends TrainingJobSummary {
  config: TrainingConfig;
}

export interface TrainMetricPoint {
  step: number;
  loss: number;
  lr: number;
  t: number;
  // Min/max of the step's micro-batch losses (gradient accumulation only).
  lmin?: number | null;
  lmax?: number | null;
  // The validation round scored at this step, when the run has one: the
  // held-out loss and the stable training loss. Absent on every other step.
  val?: number | null;
  stable?: number | null;
}

export interface TrainVisit {
  file_id: number | null;
  // Set when the image was a frame extracted from a video: the second of the
  // film it came from (such a frame is scratch, so it has no file_id).
  video_time?: number | null;
  // …and where that frame is inside the job's own folder, so the inspector
  // can show the picture the model saw. Empty once the run is over and its
  // scratch has been reclaimed.
  frame?: string;
  prompt: string;
  flip: boolean;
  // Crop rect as fractions of the original (un-flipped) image: [x, y, w, h].
  crop: number[] | null;
  img: number[];      // original [w, h]
  bucket: number[];   // bucket [w, h] px
  loss: number | null;
}

export interface TrainVisits {
  step: number;
  steps: number[];    // every step with inspection data
  visits: TrainVisit[];
}

export interface TrainSample {
  step: number;
  name: string;
  prompt: string;
  // Wall-clock time (unix) and cumulative ACTIVE training seconds (paused
  // gaps excluded) at that step; 0 when unknown.
  t: number;
  train_seconds: number;
}

/** One top-level block of the trained model, read off its loaded weights. */
export interface TrainArchitectureBlock {
  name: string;
  params: number;
  /** Identical blocks in this stack (0 when it is not a stack). */
  count: number;
  kind: string;
  /** The stack's inner blocks, when it is one — each with its own size. */
  children?: { name: string; params: number }[];
}

/** A sampling round, listed from the moment it starts rendering. */
export interface TrainSampleRound {
  step: number;
  t: number;
  train_seconds: number;
  /** Images the round is rendering, and how many have landed so far. */
  expected: number;
  done: number;
}

export interface TrainEvent {
  // started | resumed | paused | completed | failed | canceled | edited |
  // dataset
  kind: string;
  step: number;
  t: number;
  train_seconds: number;
  /** "edited" only: the settings that changed, old → new. */
  changes?: { field: string; old: string; new: string }[];
  /** "dataset" only: items the rebuilt query gained and lost on a resume. */
  added?: number;
  removed?: number;
}

export const api = {
  ...sharedApi,
  trainStatus: () => req<TrainStatus>("/api/train/status"),
  // Base models the user added (extra weights for a built-in architecture).
  trainModels: () => req<{ models: TrainModelSpec[] }>("/api/train/models"),
  // `area` is the weights' native training resolution; 0 takes the base
  // architecture's own.
  trainAddModel: (body: { label: string; base: string; repo: string;
                          local: boolean; area?: number }) =>
    req<{ models: TrainModelSpec[] }>("/api/train/models", {
      method: "POST", body: JSON.stringify(body),
    }),
  // Editing keeps the KEY: a job stores `user:<slug>`, so re-deriving it from
  // a corrected name would strand every job configured with this model.
  trainEditModel: (key: string, body: { label: string; base: string;
                                        repo: string; local: boolean;
                                        area?: number }) =>
    req<{ models: TrainModelSpec[] }>(
      `/api/train/models/${encodeURIComponent(key)}`, {
        method: "PATCH", body: JSON.stringify(body),
      }),
  // Base-model weights: fetch into the HF cache, stop, or remove what's there.
  trainDownloadModel: (key: string) =>
    req<{ ok: boolean }>(
      `/api/train/models/${encodeURIComponent(key)}/download`, { method: "POST" }),
  trainCancelModelDownload: (key: string) =>
    req<{ ok: boolean }>(
      `/api/train/models/${encodeURIComponent(key)}/cancel-download`,
      { method: "POST" }),
  trainDeleteModelCache: (key: string) =>
    req<{ ok: boolean }>(
      `/api/train/models/${encodeURIComponent(key)}/cache`, { method: "DELETE" }),
  // LoRA files the user registered (path + which base model they are for).
  trainUserLoras: () => req<{ models: UserLoraOut[] }>("/api/train/user-loras"),
  trainAddUserLora: (body: { label: string; base: string; repo: string; local: boolean }) =>
    req<{ models: UserLoraOut[] }>("/api/train/user-loras", {
      method: "POST", body: JSON.stringify(body),
    }),
  trainEditUserLora: (key: string, body: { label: string; base: string;
                                           repo: string; local: boolean }) =>
    req<{ models: UserLoraOut[] }>(
      `/api/train/user-loras/${encodeURIComponent(key)}`, {
        method: "PATCH", body: JSON.stringify(body),
      }),
  trainDeleteUserLora: (key: string) =>
    req<{ models: UserLoraOut[] }>(
      `/api/train/user-loras/${encodeURIComponent(key)}`, { method: "DELETE" }),
  trainDeleteModel: (key: string) =>
    req<{ models: TrainModelSpec[] }>(
      `/api/train/models/${encodeURIComponent(key)}`, { method: "DELETE" }),
  trainGpu: () => req<SystemDevice[]>("/api/train/gpu"),
  /** Re-arm the probes that gave up (powermetrics) and sample again — what
   *  the hint's Try again button asks for once its sudoers rule is in. */
  trainGpuRecheck: () =>
    req<SystemDevice[]>("/api/train/gpu/recheck", { method: "POST" }),
  trainJobs: () => req<{ jobs: TrainingJobSummary[]; queue_active: boolean }>(
    "/api/train/jobs"),
  trainQueueRun: () =>
    req<{ ok: boolean }>("/api/train/queue/run", { method: "POST" }),
  trainQueueStop: () =>
    req<{ ok: boolean }>("/api/train/queue/stop", { method: "POST" }),
  trainJob: (uid: string) => req<TrainingJobDetail>(`/api/train/jobs/${uid}`),
  trainCreate: (name: string, config: TrainingConfig) =>
    req<TrainingJobDetail>("/api/train/jobs", {
      method: "POST", body: JSON.stringify({ name, config }),
    }),
  trainUpdate: (uid: string, name: string, config: TrainingConfig) =>
    req<TrainingJobDetail>(`/api/train/jobs/${uid}`, {
      method: "PUT", body: JSON.stringify({ name, config }),
    }),
  trainDelete: (uid: string) =>
    req<{ ok: boolean }>(`/api/train/jobs/${uid}`, { method: "DELETE" }),
  /** One degradation variant rendered over one item, at one END of its ranges
   *  — the gentlest or the harshest thing the run can produce. Returns an
   *  object URL the caller must revoke, plus the drawn key for the caption. */
  trainDegradePreview: async (
    itemId: number, variant: TrainDegradeVariant,
    end: "clean" | "low" | "high", width = 512,
  ): Promise<{ url: string; key: string }> => {
    const r = await apiFetch("/api/train/degrade/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: itemId, variant, end, width }),
    });
    if (!r.ok) {
      let msg = `${r.status}`;
      try { msg = (await r.json()).detail || msg; } catch { /* keep status */ }
      throw new Error(msg);
    }
    const key = r.headers.get("X-Degrade-Key") || "";
    return { url: URL.createObjectURL(await r.blob()), key };
  },
  trainQueue: (uid: string) =>
    req<{ ok: boolean }>(`/api/train/jobs/${uid}/queue`, { method: "POST" }),
  /** Run this one job. `now` is the job row's button: pause whatever holds
   *  the device, put this at the front, and leave the queue running after it.
   *  Without it, the detail pane's Start — one job, nothing chained, and a
   *  busy device refused rather than taken. */
  trainStart: (uid: string, now = false) =>
    req<{ ok: boolean }>(
      `/api/train/jobs/${uid}/start${now ? "?preempt=1&run_queue=1" : ""}`,
      { method: "POST" }),
  trainPause: (uid: string) =>
    req<{ ok: boolean }>(`/api/train/jobs/${uid}/pause`, { method: "POST" }),
  trainCancel: (uid: string) =>
    req<{ ok: boolean }>(`/api/train/jobs/${uid}/cancel`, { method: "POST" }),
  trainDuplicate: (uid: string) =>
    req<TrainingJobDetail>(`/api/train/jobs/${uid}/duplicate`, { method: "POST" }),
  trainMetrics: (uid: string, after = 0) =>
    req<{ points: TrainMetricPoint[]; last_step: number; diverged?: number }>(
      after ? `/api/train/jobs/${uid}/metrics?after=${after}`
            : `/api/train/jobs/${uid}/metrics`
    ),
  trainSamples: (uid: string) =>
    req<{ samples: TrainSample[]; rounds: TrainSampleRound[] }>(
      `/api/train/jobs/${uid}/samples`),
  trainVisits: (uid: string, step?: number) =>
    req<TrainVisits>(
      `/api/train/jobs/${uid}/visits${step != null && step >= 0 ? `?step=${step}` : ""}`),
  /** What each of a config's queries actually CONTRIBUTES to the run.
   *
   *  `matched` is what a query finds on its own; `contributes` is what it adds
   *  once precedence applies, which differs only for a regularization query —
   *  a picture an ordinary query also matches is a training picture, not a
   *  reminder. The whole config goes because the scope the queries resolve in
   *  depends on the rest of it (films are in or out), and the answer comes
   *  from the server so it cannot disagree with what the run does. */
  trainQueriesPreview: (config: unknown) =>
    req<{ queries: { matched: number; contributes: number }[] }>(
      "/api/train/queries/preview",
      { method: "POST", body: JSON.stringify({ config }) }),
  /** `w` asks for a downscaled copy — the grids show ~150 px tiles, and a
   *  browser decodes a 1024² PNG into 4 MB of bitmap for each one. The
   *  lightbox omits it and gets the real image. */
  trainSampleUrl: (uid: string, step: number, name: string, w?: number) =>
    `/api/train/jobs/${uid}/samples/${step}/${name}${w ? `?w=${w}` : ""}`,
  /** One frame a run extracted from a video, by the name its visit carries.
   *  404s once the job is over — the frames go with it. */
  trainFrameUrl: (uid: string, frame: string) =>
    `/api/train/jobs/${uid}/frames/${frame.split("/").map(encodeURIComponent).join("/")}`,
  trainLog: (uid: string) => req<{ log: string }>(`/api/train/jobs/${uid}/log`),
  trainSetSteps: (uid: string, steps: number) =>
    req<{ ok: boolean }>(`/api/train/jobs/${uid}/steps`, {
      method: "POST", body: JSON.stringify({ steps }),
    }),
  trainCheckpoints: (uid: string) =>
    req<{ checkpoints: TrainCheckpoint[] }>(`/api/train/jobs/${uid}/checkpoints`),
  trainReorderQueue: (uids: string[]) =>
    req<{ ok: boolean }>("/api/train/queue-order", {
      method: "POST", body: JSON.stringify({ uids }),
    }),
  trainArchitecture: (uid: string) =>
    req<{ blocks: TrainArchitectureBlock[] }>(
      `/api/train/jobs/${uid}/architecture`),
  trainEvents: (uid: string) =>
    req<{ events: TrainEvent[] }>(`/api/train/jobs/${uid}/events`),
  // A finished job's LoRA output, zipped — the Models tab lists it beside
  // the step checkpoints, so it downloads the same way.
  trainOutputUrl: (uid: string) =>
    `/api/train/jobs/${uid}/output/download`,
  trainCheckpointUrl: (uid: string, step: number) =>
    `/api/train/jobs/${uid}/checkpoints/${step}/download`,
  trainDeleteCheckpoint: (uid: string, step: number) =>
    req<{ ok: boolean }>(`/api/train/jobs/${uid}/checkpoints/${step}`, {
      method: "DELETE",
    }),
  trainKeepCheckpoint: (uid: string, step: number) =>
    req<{ ok: boolean }>(`/api/train/jobs/${uid}/checkpoints/${step}/keep`, {
      method: "POST",
    }),
  trainLockCheckpoint: (uid: string, step: number, locked: boolean) =>
    req<{ ok: boolean }>(`/api/train/jobs/${uid}/checkpoints/${step}/lock`, {
      method: "POST", body: JSON.stringify({ locked }),
    }),
  // A job's finished LoRA locks too — what that buys is surviving the
  // deletion of the job (it has no delete button of its own).
  trainLockOutput: (uid: string, locked: boolean) =>
    req<{ ok: boolean }>(`/api/train/jobs/${uid}/output/lock`, {
      method: "POST", body: JSON.stringify({ locked }),
    }),
  // ---- evaluation ----
  evalLoras: () => req<{ loras: EvalLora[] }>("/api/train/eval/loras"),
  /** Full finetunes that can stand in for a base model's weights. */
  evalFinetunes: () =>
    req<{ finetunes: EvalFinetune[] }>("/api/train/eval/finetunes"),
  trainLoraSources: () => req<{ loras: TrainLoraSource[] }>("/api/train/loras"),
  evalRuns: () => req<{ runs: EvalRun[] }>("/api/train/eval/runs"),
  evalGenerate: (body: EvalRunBody) =>
    req<EvalRun>("/api/train/eval/runs", {
      method: "POST", body: JSON.stringify(body),
    }),
  evalCancel: (uid: string) =>
    req<{ ok: boolean }>(`/api/train/eval/runs/${uid}/cancel`, { method: "POST" }),
  evalDelete: (uid: string) =>
    req<{ ok: boolean }>(`/api/train/eval/runs/${uid}`, { method: "DELETE" }),
  /** One picture out of a run; the rest of the generation stays. */
  evalDeleteImage: (uid: string, name: string) =>
    req<{ ok: boolean }>(`/api/train/eval/runs/${uid}/images/${name}`,
                         { method: "DELETE" }),
  evalImageUrl: (uid: string, name: string, w?: number) =>
    `/api/train/eval/runs/${uid}/images/${name}${w ? `?w=${w}` : ""}`,
  trainSetupStart: () =>
    req<{ ok: boolean }>("/api/train/setup", { method: "POST" }),
  trainSetupStatus: () => req<SetupStatus>("/api/train/setup"),
};
