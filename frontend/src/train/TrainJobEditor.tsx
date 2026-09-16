// The training job editor: a modal with a left page nav (like Settings) and
// per-parameter explanation lines. Editable only for draft/queued jobs — the
// backend enforces it (409), the UI simply doesn't offer Edit elsewhere.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { storage } from "../shared/storage";
import { SectionHeading } from "../shared/SectionHeading";
import { IconButton } from "../shared/IconButton";
import { Button } from "../shared/Button";
import { useMenuDismiss } from "../shared/useMenuDismiss";
import { AnchoredDropdown, useAnchorRect } from "../shared/AnchoredDropdown";
import { useInlineEdit } from "../shared/useInlineEdit";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api, TrainFieldSpec, TrainingConfig, TrainLoraSource, TrainModelSpec,
  TrainSamplePrompt,
} from "./api";
import { Overlay } from "../shared/Overlay";
import { Icon } from "../shared/Icon";
import { useT, useLang } from "./i18n";
import {
  inputStyle, NoteRow, NumRow, Section, SelectRow, SIZE_PRESETS,
  SizeRow, TextRow, ToggleRow,
} from "./FormRows";
import { PromptArea } from "./PromptArea";
import { QueriesEditor } from "./QueriesEditor";
import { OfflineWarning, TokenWarning } from "../shared/HfWarnings";
import {
  architectureLabel, backendOf,
  checkpointMb, defaultTrainingConfig, deviceMemoryGb, errText, estimateVram,
  fitsModel, groupBy, groupByArchitecture, keptCheckpoints, releaseLabel,
  toggleLocked,
  unsupportedReasons, fmtGb, fmtSize,
} from "./util";
import { ResolutionPicker } from "./ResolutionPicker";
import {
  configFromPreset, defaultPreset, loadPresets, storePresets, withDefault,
  type TrainPreset,
} from "./presets";
import { ValueRulesSection } from "./ValueRulesSection";
import { DegradeSection } from "./DegradeSection";
import { LAYER } from "../shared/layers";
import { HelpMark } from "../shared/HelpMark";
// The ⓘ texts are compiled from `docs/training/fields/*.md` — the docs
// are the source, `scripts/gen_field_help.py` is the compiler.
import { HELP } from "./fieldHelp";

// Seven pages rather than one long scroll, grouped by the question each answers.
// "Hyperparameters" used to hold optimization, LoRA, checkpoints AND memory —
// four unrelated subjects and half the settings in the editor. LoRA belongs
// with the model it modifies, checkpoints with the samples they are paired
// with in the job timeline, and memory is its own decision (it changes what
// fits, not what is learned).
type Page = "model" | "hyper" | "memory" | "dataset" | "captions"
  | "checkpoints" | "samples";

const PAGES: [Page, string, string][] = [
  ["model", "Model", "deployed_code"],
  ["hyper", "Optimization", "tune"],
  ["memory", "Memory & speed", "memory"],
  ["dataset", "Dataset", "photo_library"],
  // What every training example is asked against. It was "Captions &
  // tags", which named two of the four sources this page offers
  // (instructions is a third, caption + tags a fourth) — the page is
  // about the PROMPT, whichever of them it is built from.
  ["captions", "Prompt", "sell"],
  // TWO pages, not one. What to KEEP off a run and what to LOOK at while
  // it goes are different decisions, taken at different times: the first is
  // set once and is about disk, the second is a prompt list you come back to.
  // Together they were the longest page in the editor.
  ["checkpoints", "Checkpoints", "save"],
  ["samples", "Samples", "image"],
];

function splitTags(text: string): string[] {
  return text.split(",").map((s) => s.trim()).filter(Boolean);
}

// Named sets of test prompts, remembered in the browser so a proven prompt
// list can be restored into any job with one click.
const PROMPT_SETS_KEY = "mc.trainPromptSets";
// `id` rather than the name identifies a set, so renaming one — and two sets
// ending up with the same name — can't delete or overwrite the wrong entry.
type PromptSet = { id: string; name: string; prompts: TrainSamplePrompt[] };
function loadPromptSets(): PromptSet[] {
  try {
    const v = JSON.parse(storage.get(PROMPT_SETS_KEY) || "[]");
    if (!Array.isArray(v)) return [];
    return v
      .filter((s) => s && typeof s.name === "string" && Array.isArray(s.prompts))
      .map((s, i) => ({ ...s, id: typeof s.id === "string" ? s.id : `legacy-${i}-${s.name}` }));
  } catch { return []; }
}
function storePromptSets(sets: PromptSet[]) {
  try { storage.set(PROMPT_SETS_KEY, JSON.stringify(sets)); } catch { /* ignore */ }
}

function ModelParamRow({ spec, value, onChange, last }: {
  spec: TrainFieldSpec;
  value: unknown;
  onChange: (v: unknown) => void;
  last?: boolean;
}) {
  // The registry's own English text is translated by source string, exactly
  // like the hand-written rows around it — otherwise the model-specific rows
  // would be the only untranslated ones on the page.
  const t = useT();
  const label = t(spec.label);
  const hint = spec.hint ? t(spec.hint) : spec.hint;
  const details = spec.details ? t(spec.details) : spec.details;
  if (spec.type === "bool") {
    return <ToggleRow label={label} hint={hint} details={details} last={last}
      checked={Boolean(value)} onChange={onChange} />;
  }
  if (spec.type === "choice") {
    return <SelectRow label={label} hint={hint} details={details} last={last}
      value={String(value ?? spec.default)}
      options={spec.choices.map((c) => [c, c] as const)}
      onChange={onChange} />;
  }
  return <NumRow label={label} hint={hint} details={details} last={last}
    value={Number(value ?? spec.default)}
    min={spec.min ?? undefined} max={spec.max ?? undefined}
    step={spec.type === "int" ? 1 : undefined}
    onChange={onChange} />;
}

/** A separator as something you can see and type in a one-line field: a real
 *  newline shown as the two characters `\n`, and back again on the way in. */
const showEscapes = (v: string) => v.replace(/\n/g, "\\n").replace(/\t/g, "\\t");
const readEscapes = (v: string) => v.replace(/\\n/g, "\n").replace(/\\t/g, "\t");

export function TrainJobEditor({ uid, models, onClose }: {
  uid: string | null; // null = create new
  models: TrainModelSpec[];
  onClose: (createdUid?: string) => void;
}) {
  const t = useT();
  const lang = useLang();
  const qc = useQueryClient();
  // For the environment warnings below: this job's model has to be downloaded
  // before the run can start, and the run is what downloads it.
  const { data: status } = useQuery({
    queryKey: ["train-status"], queryFn: api.trainStatus,
  });
  const [page, setPage] = useState<Page>("model");
  const [name, setName] = useState("");
  const [config, setConfig] = useState<TrainingConfig>(() => {
    // A new job starts from the default preset if one is marked, so the setup
    // someone arrived at after a few runs is where the next one begins.
    const preset = uid === null ? defaultPreset() : undefined;
    if (preset) return configFromPreset(preset.config, models);
    return defaultTrainingConfig(models.find((m) => m.key === "sdxl") ?? models[0]);
  });
  const [loaded, setLoaded] = useState(uid === null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Whether this job still takes changes. A started job doesn't — but it is
  // still worth opening: seeing what it was set to is how you decide what the
  // next one should be, and then "Save as new job" makes that next one.
  const [editable, setEditable] = useState(true);
  useQuery({
    queryKey: ["train-job-edit", uid],
    queryFn: async () => {
      const job = await api.trainJob(uid!);
      setName(job.name);
      setConfig(job.config);
      // Anything not currently running takes changes — they apply to the
      // NEXT run, and the timeline records what was changed (the backend
      // applies exactly this rule and writes the "edited" event). "Save as
      // new job" stays available either way.
      //
      // PAUSING counts as not running: the trainer read its config when it
      // was spawned and is now writing its checkpoint, so an edit reaches the
      // next run exactly as it does on a job already paused — and a pause of
      // a big-batch job takes long enough that refusing the edit for the
      // length of it is a refusal nobody can explain.
      setEditable(job.status !== "running");
      setLoaded(true);
      return job;
    },
    enabled: uid !== null && !loaded,
  });

  const model = models.find((m) => m.key === config.model);
  // `slices_attention` reports whether this machine can slice at all.
  const vram = estimateVram(config, model, status?.slices_attention !== false,
                            backendOf(config, status?.devices));
  const { data: devices } = useQuery({
    queryKey: ["train-gpu"], queryFn: api.trainGpu,
  });
  // Comparing the estimate against what exists is the whole point: a number
  // that quietly exceeds the machine is how a run gets started anyway.
  const deviceGb = deviceMemoryGb(devices, config.gpu);
  const overBudget = !!vram && deviceGb > 0 && vram.total > deviceGb;
  // Several images per step with every activation kept — the combination that
  // runs out of memory part-way into a run.
  const memoryWarning = config.hyper.batch_size > 2
    && !config.hyper.gradient_checkpointing;
  const set = (patch: Partial<TrainingConfig>) =>
    setConfig((c) => ({ ...c, ...patch }));
  const setHyper = (patch: Partial<TrainingConfig["hyper"]>) =>
    setConfig((c) => ({ ...c, hyper: { ...c.hyper, ...patch } }));
  // CHANGING THE OPTIMIZER CAN CHANGE WHAT THE LEARNING RATE MEANS.
  //
  // Prodigy works its own rate out and treats the configured one as a
  // multiplier, where 1 is neutral — so the value that means "as before" for
  // every other optimizer (1e-4) means "a ten-thousandth of what I found"
  // here, and the run trains almost not at all with nothing to see. Switching
  // to it therefore moves the rate to 1, and switching away puts the model's
  // own default back rather than leaving a 1 that would now be catastrophic.
  //
  // Only when the rate is still the one the other side implies: a number
  // somebody has deliberately typed is left alone in both directions.
  const setOptimizer = (next: TrainingConfig["hyper"]["optimizer"]) =>
    setConfig((c) => {
      const wasProdigy = c.hyper.optimizer === "prodigy";
      const isProdigy = next === "prodigy";
      const fallback = model?.default_lr ?? 1e-4;
      let lr = c.hyper.lr;
      if (isProdigy && !wasProdigy && lr === fallback) lr = 1;
      if (!isProdigy && wasProdigy && lr === 1) lr = fallback;
      return { ...c, hyper: { ...c.hyper, optimizer: next, lr } };
    });
  const setNoise = (patch: Partial<TrainingConfig["noise"]>) =>
    setConfig((c) => ({ ...c, noise: { ...c.noise, ...patch } }));
  const setBuckets = (patch: Partial<TrainingConfig["buckets"]>) =>
    setConfig((c) => ({ ...c, buckets: { ...c.buckets, ...patch } }));
  const setCaptions = (patch: Partial<TrainingConfig["captions"]>) =>
    setConfig((c) => ({ ...c, captions: { ...c.captions, ...patch } }));
  const setVideo = (patch: Partial<TrainingConfig["video"]>) =>
    setConfig((c) => ({ ...c, video: { ...c.video, ...patch } }));
  const setSampling = (patch: Partial<TrainingConfig["sampling"]>) =>
    setConfig((c) => ({ ...c, sampling: { ...c.sampling, ...patch } }));
  // Sampling is ON when EITHER cadence is set — the two are one setting said
  // two ways, and reading only the step count would make an epoch cadence a
  // run rendering rounds under a toggle that says it is off.
  const sampleOn = config.sampling.every_n_steps > 0
    || config.sampling.every_n_epochs > 0;
  const setValidation = (patch: Partial<TrainingConfig["validation"]>) =>
    setConfig((c) => ({ ...c, validation: { ...c.validation, ...patch } }));

  // Reordering the test prompts: only the handle starts the drag, and `dropAt`
  // is the slot the row would land in (0…length), drawn as an insertion line.
  const promptDrag = useRef<number | null>(null);
  const [dropAt, setDropAt] = useState<number | null>(null);
  // Which slot a pointer at `y` over row `i` means: before it, or after it.
  const slotAt = (i: number, y: number, box: DOMRect) =>
    i + (y > box.top + box.height / 2 ? 1 : 0);
  // The drop reads the slot from its OWN coordinates rather than from `dropAt`
  // — that state exists only to draw the line, and depending on it would tie
  // the move to a dragover having been rendered first.
  const dropPrompt = (to: number) => {
    const from = promptDrag.current;
    promptDrag.current = null;
    setDropAt(null);
    if (from == null || to === from || to === from + 1) return;
    const list = config.sampling.prompts.slice();
    const [moved] = list.splice(from, 1);
    list.splice(to > from ? to - 1 : to, 0, moved);
    setSampling({ prompts: list });
  };

  const switchModel = (key: string) => {
    const m = models.find((x) => x.key === key);
    if (!m) return;
    setConfig((c) => ({
      ...c,
      model: key,
      method: m.lora_only ? "lora" : c.method,
      // The same shape as the line above it: a model that cannot edit has no
      // use for instructions, and the backend refuses the pair outright — so
      // the config must not be left holding it after a model change.
      captions: {
        ...c.captions,
        // Both directions, because both are wrong to leave alone: a model
        // that cannot edit has no use for instructions (and the backend
        // refuses the pair outright), and a model that exists to edit should
        // not start on a source that trains the half of it nobody uses.
        source: c.captions.source === "instructions" && !m.edit ? "tags"
          : m.edit_only ? "instructions" : c.captions.source,
      },
      hyper: { ...c.hyper, lr: m.default_lr },
      model_params: Object.fromEntries(m.params.map((p) => [p.name, p.default])),
    }));
  };

  const save = async (queue: boolean, duplicate = false) => {
    setSaving(true);
    setError("");
    try {
      const job = uid && editable && !duplicate
        ? await api.trainUpdate(uid, name, config)
        : await api.trainCreate(name, config);
      if (queue) await api.trainQueue(job.uid);
      onClose(job.uid);
    } catch (e) {
      setError(errText(e));
      setSaving(false);
    }
  };

  // An instruction run's prompt is an imperative sentence and its target must
  // still line up with its reference pictures — so tag selection, flipping and
  // random crops all say nothing here, and the pages simply do not offer them.
  const instructing = config.captions.source === "instructions";

  const ckptMb = checkpointMb(config, model);
  // What the retention rule will actually cost. "Last N" is a fixed window;
  // "every Nth" grows with the run, so the honest number is how many
  // milestones the configured step count will produce.
  const ckptKept = keptCheckpoints(config);
  // With the cadence in epochs and the length in steps there is no count to
  // give — how many steps a pass takes is the manifest's answer — so the line
  // says what one snapshot costs instead of implying a total.
  const ckptKeepHint = `${t("Kept for good, on top of the window above.")} ${
    ckptKept > 0
      ? t("Estimated disk use: {n} × {size} ≈ {total}", {
          n: ckptKept, size: fmtSize(ckptMb, lang),
          total: fmtSize(ckptMb * ckptKept, lang),
        })
      : t("Each snapshot is about {size}.", { size: fmtSize(ckptMb, lang) })}`;
  // The model's OWN size — what a 0 in the resolution list means, and what a
  // test sample with no size of its own is rendered at (the engines resolve
  // a missing width to their native area; the TRAINING sizes never reach
  // them). Both the picker's labels and the sample rows read it.
  const nativeArea = model?.default_area || 1024;
  const isLora = config.method === "lora";
  // What this job's GPU and model cannot do. "auto" is the machine's first
  // device, resolved the same way the scheduler resolves it.
  const jobDevice = config.gpu !== "auto" ? config.gpu
    : (status?.devices?.[0]?.id ?? "cpu");
  const cannot = unsupportedReasons(config, model, jobDevice,
                                    status?.slices_attention !== false);
  /** The reasons come out of a pure module, so they are translated here.
   *  `t()` of a non-literal falls back to the English source, which is what
   *  every one of these strings is. */
  const rowCannot = (path: string) =>
    cannot.rows[path] ? t(cannot.rows[path]) : undefined;
  const optCannot = (path: string) => {
    const m = cannot.values[path];
    return m && Object.fromEntries(
      Object.entries(m).map(([v, why]) => [v, t(why)]));
  };

  return (
    <>
    <Overlay
      icon="model_training"
      title={!uid ? t("New training job")
        : editable ? t("Edit training job") : t("Training job settings")}
      width={920}
      onClose={() => onClose()}
      footer={
        <>
          {error ? (
            <div style={{
              flex: 1, alignSelf: "center", fontSize: "var(--fs-2)",
              color: "var(--red-text)", textAlign: "left",
            }}>
              {error}
            </div>
          ) : vram ? (
            // What the settings above will ask of the GPU, updating as they
            // change — the number people otherwise only learn from a crash
            // several minutes into a run.
            <div
              title={t("Weights {w} · optimizer {o} · activations {a}. This is the working set — what the run needs at once. Peak allocation runs higher: freed blocks stay pooled rather than being returned, sampling rounds allocate on top, and fragmentation adds more, so a run wants real headroom above this figure rather than a machine that merely matches it. The activation part is the rough one (it depends on the model's internals), and gradient accumulation costs nothing here — its passes run one after another.",
                { w: fmtGb(vram.weights, lang), o: fmtGb(vram.optimizer, lang),
                  a: fmtGb(vram.activations, lang) })}
              style={{
                flex: 1, alignSelf: "center", textAlign: "left",
                display: "flex", alignItems: "center", gap: 6,
                fontSize: "var(--fs-2)", cursor: "help",
                color: overBudget ? "var(--yellow-text)" : "var(--muted)",
              }}
            >
              <Icon name={overBudget ? "warning" : "memory"} size={15} />
              <span>
                {t("about {v} of GPU memory", { v: fmtGb(vram.total, lang) })}
                {overBudget && ` · ${t("more than this machine's {m}",
                                       { m: fmtGb(deviceGb, lang) })}`}
              </span>
            </div>
          ) : null}
          <PresetsMenu
            config={config}
            models={models}
            onLoad={(c) => setConfig(c)}
          />
          <Button variant="ghost" onClick={() => onClose()}>{t("Cancel")}</Button>
          {editable && uid ? (
            /* EDITING one that exists. "Save draft" and "Save & queue" are
               what you press when a job is being MADE — they name where it
               lands. Against a job already sitting in a section, the first
               said nothing (it is already a draft, or already queued, and
               saving does not move it) and the second quietly moved it into
               the queue as the price of a settings change. Save leaves it
               where it is; the second button is the one that makes another
               job, which is what "save this as something else" means. */
            <>
              <Button variant="ghost" onClick={() => save(false, true)}>
                {t("Save as duplicate")}
              </Button>
              <Button variant="primary" icon="check" onClick={() => save(false)}
                disabled={saving || !loaded}>
                {t("Save")}
              </Button>
            </>
          ) : editable ? (
            <>
              <Button variant="ghost" onClick={() => save(false)}>{t("Save draft")}</Button>
              <Button variant="primary" icon="play_arrow" onClick={() => save(true)}
                disabled={saving || !loaded}>
                {t("Save & queue")}
              </Button>
            </>
          ) : (
            // A started job's settings are fixed, so saving means starting a
            // new one from them — the same thing Duplicate did, except you
            // have seen and adjusted what you are copying.
            <Button variant="primary" icon="content_copy" onClick={() => save(false)}
              disabled={saving || !loaded}>
              {t("Save as new job")}
            </Button>
          )}
        </>
      }
    >
      {/* Grows with the window (the Overlay caps the whole modal at 88% of the
          viewport; 150px covers its header + footer chrome). */}
      <div style={{ display: "flex", minHeight: 380, height: "calc(88vh - 150px)" }}>
        {/* Page nav */}
        <div style={{
          width: 190, flex: "0 0 190px", padding: 12,
          borderRight: "1px solid var(--border)", display: "flex",
          flexDirection: "column", gap: 2,
        }}>
          {PAGES.map(([p, label, icon]) => (
            <button
              key={p}
              onClick={() => setPage(p)}
              style={{
                display: "flex", alignItems: "center", gap: 9,
                height: 34, padding: "0 11px", borderRadius: "var(--r-4)", border: "none",
                background: page === p ? "var(--border)" : "transparent",
                color: page === p ? "var(--text)" : "var(--muted)",
                fontWeight: page === p ? 600 : 500, fontSize: "var(--fs-3)",
                cursor: "pointer", textAlign: "left", fontFamily: "inherit",
              }}
            >
              <Icon name={icon} size={17} />
              {t(label)}
            </button>
          ))}
        </div>

        {/* Page body */}
        <div className="mc-settings-page" style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: 18 }}>
          {!loaded ? (
            <div style={{ color: "var(--muted)", fontSize: "var(--fs-3)" }}>{t("Loading…")}</div>
          ) : page === "model" ? (
            <>
              <Section label={t("Job")}>
                <TextRow label={t("Name")} value={name} onChange={setName}
                  placeholder={t("e.g. watercolor style LoRA")} wide last />
              </Section>

              {/* The job's NAME leads: one field, and the first thing you
                  fill in. The model follows, with the download warnings that
                  are about it. Which CARD it runs on moved to Memory & speed —
                  that is a question about the machine, not about the job. */}
              {/* The run downloads its base model on first use, so the same
                  environment warnings the Models page shows belong here too —
                  before a job is queued against a model that cannot arrive. */}
              {model && !model.cached && !!status?.env_offline && (
                <div style={{ marginBottom: 14 }}>
                  <OfflineWarning variable={status.env_offline}
                    onChanged={() => qc.invalidateQueries({ queryKey: ["train-status"] })} />
                </div>
              )}
              {model && !model.cached && !status?.token_available && (
                <div style={{ marginBottom: 14 }}>
                  <TokenWarning
                    onChanged={() => qc.invalidateQueries({ queryKey: ["train-status"] })} />
                </div>
              )}
              <Section label={t("Base model")}>
                <SelectRow
                  label={t("Model")}
                  hint={model?.note ? t(model.note) : undefined}
                  details={t(HELP["base-model.model"])}
                  value={config.model}
                  // Headed by ARCHITECTURE, the same grouping the Models page
                  // uses and for the same reason: eighteen entries flat is a
                  // list you scroll, and which of them are versions of one
                  // another is the first thing you want to see. The heading is
                  // what the group's own labels share, so a model added later
                  // needs nothing here.
                  groups={groupByArchitecture(models).map(([engine, group]) => (
                    // A family of ONE gets no heading — a heading identical to
                    // the single row under it says the name twice. The rest
                    // are headed, and their rows then drop what the heading
                    // already said ("Klein (base, 4B)" under "FLUX.2").
                    group.length > 1
                      ? [architectureLabel(engine, group),
                         group.map((m) =>
                           [m.key, releaseLabel(m, engine, group)] as const)] as const
                      : ["", group.map((m) => [m.key, m.label] as const)] as const
                  ))}
                  onChange={switchModel}
                />
                <SelectRow
                  label={t("Method")}
                  hint={t("An adapter is a small add-on file layered over the untouched model — fast, low memory, ideal for styles, characters and concepts. Full finetune rewrites the whole model: much more VRAM and data needed, only worth it for broad domain shifts. Which kind of adapter is the next question down.")}
                  details={t(HELP["base-model.method"])}
                  value={config.method}
                  cannot={optCannot("method")}
                  // NOT "LoRA": that is one of the two ADAPTER TYPES below, so
                  // naming the method after it made a LoKr run read "Method:
                  // LoRA / Adapter type: LoKr" on one screen. The stored value
                  // stays `"lora"` — it is in every job.json and read by the
                  // manager, the evaluator and `lora_only`.
                  options={[["lora", t("Adapter")], ["full", t("Full finetune")]] as const}
                  onChange={(v) => set({ method: v as "lora" | "full" })}
                />
                <LoraStartRow
                  value={config.init_lora}
                  model={config.model}
                  models={models}
                  disabled={!isLora}
                  onChange={(v) => set({ init_lora: v })}
                />
              </Section>


              {isLora && (
                <Section label={t("Adapter")}>
                  <SelectRow label={t("Adapter type")} value={config.hyper.network}
                    // The hint says what the CURRENT choice means, rather than
                    // naming both — with a NoteRow underneath it as well, a
                    // LoKr run showed two subtitles making overlapping claims,
                    // one of them mostly about the option NOT selected. Same
                    // shape the quantization row uses for `isLora`.
                    hint={config.hyper.network === "lokr"
                      ? t("A much smaller file, and not limited by the rank the way a LoRA is. Whether it can be used outside this app depends on the model — see the ⓘ.")
                      : t("The standard choice, and the format every other tool understands — a LoRA can be used anywhere.")}
                    details={t(HELP["adapter.adapter-type"])}
                    options={[["lora", "LoRA"], ["lokr", "LoKr"]] as const}
                    onChange={(v) => setHyper({ network: v as TrainingConfig["hyper"]["network"] })} />
                  <NumRow label={t("Rank")} value={config.hyper.rank}
                    min={1} max={256} step={4}
                    hint={t("Adapter capacity. Higher learns more detail but overfits sooner and grows the file; 8–32 is typical, 4–8 for simple styles.")}
                    details={t(HELP["adapter.rank"])}
                    onChange={(v) => setHyper({ rank: v })} />
                  <NumRow label={t("Alpha")} value={config.hyper.alpha} min={0.1} step={1}
                    hint={t("Scales the adapter's effect; the common convention is alpha = rank. Lower alpha = weaker influence at the same rank.")}
                    details={t(HELP["adapter.alpha"])}
                    onChange={(v) => setHyper({ alpha: v })} />
                  {config.hyper.network === "lokr" && (
                    <NumRow label={t("Kronecker factor")} value={config.hyper.lokr_factor}
                      min={-1} max={512} step={1} placeholder={t("automatic")}
                      emptyValue={-1}
                      hint={t("How each weight is split into LoKr's two parts. Leave empty unless you have a reason not to.")}
                      details={t(HELP["adapter.kronecker-factor"])}
                      onChange={(v) => setHyper({ lokr_factor: v })} />
                  )}
                  <ToggleRow label={t("Train text encoder")}
                    checked={config.hyper.train_text_encoder}
                    disabled={toggleLocked(
                      !!rowCannot("hyper.train_text_encoder"),
                      config.hyper.train_text_encoder)}
                    unsupported={rowCannot("hyper.train_text_encoder")}
                    hint={t("Helps the model learn a NEW trigger word, at higher overfitting risk. Guarded: it uses a lower learning rate and stops partway through training.")}
                    details={t(HELP["adapter.train-text-encoder"])}
                    onChange={(v) => setHyper({ train_text_encoder: v })} />
                  {config.hyper.train_text_encoder && (
                    <>
                      {/* Only where the model HAS a large encoder beside a
                          small one (`te_pooled_act_gb` > 0: FLUX.1). On
                          Chroma T5 is the only encoder and the main toggle
                          already means it; on SD/SDXL there is no large one.
                          A switch that could only ever be left on says
                          nothing, so it is not drawn. */}
                      {(model?.te_pooled_act_gb ?? 0) > 0 && (
                        <ToggleRow label={t("Include the large encoder")}
                          checked={config.hyper.train_text_encoder_large}
                          hint={t("T5-XXL, the encoder that reads the whole prompt — most of the memory and most of the effect. Unticked, only the small CLIP-L trains: cheap, and what most FLUX LoRA tools mean by training the text encoder.")}
                          details={t(HELP["adapter.include-the-large-encoder"])}
                          onChange={(v) => setHyper({ train_text_encoder_large: v })} />
                      )}
                      <NumRow label={t("Text encoder LR")} value={config.hyper.te_lr}
                        min={0} placeholder={t("automatic")}
                        hint={t("Left empty: half the main learning rate.")}
                        details={t(HELP["adapter.text-encoder-lr"])}
                        onChange={(v) => setHyper({ te_lr: v })} />
                      <NumRow label={t("Stop TE after")} value={config.hyper.te_stop_ratio}
                        min={0.05} max={1} step={0.05} suffix={t("of total steps")}
                        hint={t("The text encoder stops training after this fraction of the run while the rest continues — the standard guard against a fried text encoder.")}
                        details={t(HELP["adapter.stop-te-after"])}
                        onChange={(v) => setHyper({ te_stop_ratio: v })} />
                    </>
                  )}
                  {/* WHICH LAYERS, last in the section: it is the one setting
                      here that most runs should leave alone, and it reads as
                      a refinement of the three above rather than a fourth
                      thing to decide. */}
                  <TextRow label={t("Only these layers")} wide
                    suggest={model?.layer_hints}
                    value={config.hyper.layer_include.join(", ")}
                    placeholder={t("all of them")}
                    hint={t("Comma-separated parts of a layer's name. Leave empty to train every attention layer — which is what you want unless you have a reason not to.")}
                    details={t(HELP["adapter.only-these-layers"])}
                    onChange={(v) => setHyper({ layer_include: splitTags(v) })} />
                  <TextRow label={t("Except these layers")} wide
                    suggest={model?.layer_hints}
                    value={config.hyper.layer_exclude.join(", ")}
                    placeholder={t("none")}
                    hint={t("Comma-separated parts of a layer's name to leave out. Applied after the field above, and it wins.")}
                    details={t(HELP["adapter.except-these-layers"])}
                    onChange={(v) => setHyper({ layer_exclude: splitTags(v) })} />
                  <div style={{ padding: "8px 16px", fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
                    {/* No figure for LoKr on purpose: its size depends on how
                        each weight happens to factorise, so any single number
                        would be a guess dressed as an estimate. What is worth
                        saying is the comparison, which holds. */}
                    {config.hyper.network === "lokr"
                      ? t("Output size: a small fraction of a LoRA of the same rank — usually under a tenth.")
                      : t("Output size ≈ {size}", { size: fmtSize(model ? model.lora_mb_per_rank * config.hyper.rank : 0, lang) })}
                  </div>
                </Section>
              )}
            </>
          ) : page === "hyper" ? (
            <>
              <Section label={t("Length & learning rate")}>
                {/* WHICH UNIT the length is given in. Epochs resolve to
                    steps in the TRAINER, not here: a pass is as long as the
                    manifest is, and only the manifest knows a film's frames,
                    a degraded copy, or an item contributing one entry per
                    caption. So this page shows the unit and the number, and
                    the run prints what it worked out. */}
                <SelectRow label={t("Length measured in")}
                  value={config.hyper.epochs > 0 ? "epochs" : "steps"}
                  hint={t("Steps are a fixed amount of work; epochs are full passes over your images, so the run grows with the dataset.")}
                  details={t(HELP["length-learning-rate.length-measured-in"])}
                  options={[["steps", t("Steps")], ["epochs", t("Epochs")]] as const}
                  onChange={(v) => setHyper(v === "epochs"
                    ? { epochs: config.hyper.epochs || 10 }
                    : { epochs: 0 })} />
                {config.hyper.epochs > 0 ? (
                  <NumRow label={t("Epochs")} value={config.hyper.epochs}
                    min={1} step={1}
                    hint={t("Full passes over the dataset. The exact step count is worked out when the run starts and shown in its log.")}
                    details={t(HELP["length-learning-rate.epochs"])}
                    onChange={(v) => setHyper({ epochs: v })} />
                ) : (
                <NumRow label={t("Total steps")} value={config.hyper.steps}
                  min={1} step={100}
                  hint={t("How long to train. Rule of thumb for LoRA: ~100× your image count; 1500–5000 is typical. Too many steps overfit (samples all start looking like the training images).")}
                  details={t(HELP["length-learning-rate.total-steps"])}
                  onChange={(v) => setHyper({ steps: v })} />
                )}
                {/* With Prodigy this row means something else entirely — a
                    multiplier rather than a step size — so it says so rather
                    than showing a "1" that reads as a wildly high rate. */}
                {config.hyper.optimizer === "prodigy" ? (
                  <NumRow label={t("Learning rate multiplier")} value={config.hyper.lr}
                    min={0}
                    hint={t("Prodigy works the rate out for itself; this scales what it finds. 1 leaves it alone — lower it if the run overshoots, raise it if it never gets going.")}
                    details={t(HELP["length-learning-rate.learning-rate-multiplier"])}
                    onChange={(v) => setHyper({ lr: v })} />
                ) : (
                <NumRow label={t("Learning rate")} value={config.hyper.lr}
                  min={0}
                  hint={t("Step size of each update. Too high fries the model (artifacts, deep-fried colors); too low changes nothing. LoRA: ~1e-4; full finetune: 1e-6…1e-5.")}
                  details={t(HELP["length-learning-rate.learning-rate"])}
                  onChange={(v) => setHyper({ lr: v })} />
                )}
                <SelectRow label={t("LR schedule")} value={config.hyper.lr_scheduler}
                  hint={t("Cosine decays smoothly to zero — a good default. Constant keeps full speed until the end; use warmup when training the text encoder.")}
                  details={t(HELP["length-learning-rate.lr-schedule"])}
                  options={[["cosine", t("Cosine")], ["constant", t("Constant")],
                    ["linear", t("Linear decay")],
                    ["constant_with_warmup", t("Constant + warmup")]] as const}
                  onChange={(v) => setHyper({ lr_scheduler: v as TrainingConfig["hyper"]["lr_scheduler"] })} />
                <NumRow label={t("Warmup steps")} value={config.hyper.warmup_steps}
                  min={0} step={1} placeholder={t("none")}
                  hint={t("Ramp the learning rate up over the first N steps. Leave empty for no warmup.")}
                  details={t(HELP["length-learning-rate.warmup-steps"])}
                  onChange={(v) => setHyper({ warmup_steps: v })} last />
              </Section>

              <Section label={t("Batch & seed")}>
                <NumRow label={t("Batch size")} value={config.hyper.batch_size}
                  min={1} max={64} step={1}
                  // The warning below belongs to this row, so the row's own
                  // separator would cut between the two. Hand the separator to
                  // the warning instead, which then closes the pair.
                  last={memoryWarning}
                  hint={t("Images per step — limited by VRAM. Raise gradient accumulation instead when memory runs out.")}
                  details={t(HELP["batch-seed.batch-size"])}
                  onChange={(v) => setHyper({ batch_size: v })} />
                {/* The combination that ends in an out-of-memory crash minutes
                    into a run: several images per step, at full resolution,
                    with every activation kept. Say it here, where it is still
                    one click to fix. */}
                {memoryWarning && (
                  <div style={{
                    padding: "0 16px 10px",
                    borderBottom: "1px solid var(--border-soft)",
                  }}>
                    <div style={{
                      padding: "8px 10px", borderRadius: "var(--r-5)",
                      display: "flex", alignItems: "flex-start", gap: 8,
                      background: "var(--yellow-dim)",
                      border: "1px solid var(--yellow-border)",
                      fontSize: "var(--fs-2)", lineHeight: 1.5, color: "var(--text-2)",
                    }}>
                      <Icon name="warning" size={15} color="var(--yellow-text)" />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        {t("Batch size {n} with gradient checkpointing off keeps every layer's activations for {n} images at once — the usual cause of an out-of-memory failure part-way into a run. Either switch gradient checkpointing on (on the Memory & speed page) or set the batch size to 1 and raise gradient accumulation to {m}, which trains the same effective batch.",
                          { n: config.hyper.batch_size,
                            m: config.hyper.batch_size * config.hyper.grad_accum })}
                      </div>
                    </div>
                  </div>
                )}
                <NumRow label={t("Gradient accumulation")} value={config.hyper.grad_accum}
                  min={1} max={256} step={1}
                  hint={t("Accumulate N batches before each update — the effect of a bigger batch without the VRAM cost (N× slower per step).")}
                  details={t(HELP["batch-seed.gradient-accumulation"])}
                  onChange={(v) => setHyper({ grad_accum: v })} />
                <NumRow label={t("Seed")} value={config.hyper.seed} step={1} last
                  hint={t("Makes sampling, crops and tag picks reproducible.")}
                  details={t(HELP["batch-seed.seed"])}
                  onChange={(v) => setHyper({ seed: v })} />
              </Section>

              {/* WHAT the run teaches, rather than how fast or how much —
                  which is why it sits on this page and not with the dataset:
                  the pictures are the same either way. */}
              <Section label={t("Noise levels")}>
                <SelectRow label={t("Train on")} value={config.noise.timesteps}
                  hint={t("Which stage of denoising to spend the run on. High noise decides a picture's layout, low noise its detail — so this decides what the training is mostly about.")}
                  details={t(HELP["noise-levels.train-on"])}
                  options={[["default", t("The model's own (recommended)")],
                    ["uniform", t("Evenly across all levels")],
                    ["logit_normal", t("A bell curve I can aim")],
                    ["cosmap", t("Leaning towards layout")]] as const}
                  onChange={(v) => setNoise({ timesteps: v as TrainingConfig["noise"]["timesteps"] })}
                  last={config.noise.timesteps !== "logit_normal"} />
                {config.noise.timesteps === "logit_normal" && (
                  <>
                    <NumRow label={t("Aim at")} value={config.noise.logit_mean}
                      min={-4} max={4} step={0.25}
                      hint={t("0 is the middle. Positive leans towards layout and composition, negative towards detail and texture. ±1 is already a strong lean.")}
                      details={t(HELP["noise-levels.aim-at"])}
                      onChange={(v) => setNoise({ logit_mean: v })} />
                    <NumRow label={t("Spread")} value={config.noise.logit_std}
                      min={0.1} max={4} step={0.1} last
                      hint={t("How wide the curve is. 1 is the default; smaller concentrates the run on a narrow band around the aim, larger reaches both extremes.")}
                      details={t(HELP["noise-levels.spread"])}
                      onChange={(v) => setNoise({ logit_std: v })} />
                  </>
                )}
              </Section>

              {/* About the RESULT rather than about memory, which is why it
                  sits here and not with the savers: it changes which weights
                  are saved, and costs memory only as a side effect. */}
              <Section label={t("Weight averaging")}>
                <ToggleRow label={t("Average the weights")}
                  checked={config.hyper.ema}
                  hint={t("Save a smoothed version of the weights instead of whatever the last step happened to produce. Makes checkpoints more consistent and overtraining slower to bite.")}
                  details={t(HELP["weight-averaging.average-the-weights"])}
                  onChange={(v) => setHyper({ ema: v })}
                  last={!config.hyper.ema} />
                {config.hyper.ema && (
                  <NumRow label={t("Averaging window")} value={config.hyper.ema_decay}
                    min={0.5} max={0.9999} step={0.001} last
                    hint={t("How much of the old average is kept each step. 0.999 averages roughly the last 1000 steps; lower follows training more closely, higher smooths harder.")}
                    details={t(HELP["weight-averaging.averaging-window"])}
                    onChange={(v) => setHyper({ ema_decay: v })} />
                )}
              </Section>

              {model && model.params.length > 0 && (
                <Section label={t("Model-specific")}>
                  {model.params.map((p, i) => (
                    <ModelParamRow
                      key={p.name} spec={p}
                      value={config.model_params[p.name]}
                      last={i === model.params.length - 1}
                      onChange={(v) => set({
                        model_params: { ...config.model_params, [p.name]: v },
                      })}
                    />
                  ))}
                </Section>
              )}
            </>
          ) : page === "memory" ? (
            <>
              {/* WHICH CARD comes before what has to fit on it. It sat in the
                  Job section beside the name, which is bookkeeping; it belongs
                  with the settings that are about the machine. */}
              <Section label={t("Device")}>
                <SelectRow
                  label={t("GPU")}
                  hint={t("One job runs per GPU — on machines with several, jobs on different GPUs run at the same time.")}
                  details={t(HELP["device.gpu"])}
                  value={config.gpu}
                  options={[["auto", t("Automatic")] as const,
                    ...(status?.devices ?? []).map(
                      (d) => [d.id, d.label] as const)]}
                  onChange={(v) => set({ gpu: v })}
                  last
                />
              </Section>

              {/* Two groups, both titled, and no subtitle over them: "these
                  change what fits, not what is learned" described the whole
                  page from inside one of its sections, and the page's own
                  name already says it.

                  How many BITS each number uses, then what to trade away to
                  make it fit. Precision leads its group because it is the one
                  everything else is measured against — the estimate in the
                  footer moves with it. */}
              <Section label={t("Precision & quantization")}>
                <SelectRow label={t("Precision")} value={config.hyper.precision}
                  hint={t("bf16 is the safe modern default. fp32 doubles memory (automatic fallback on Macs without bf16); avoid fp16 for training.")}
                  details={t(HELP["precision-quantization.precision"])}
                  options={[["bf16", "bf16"], ["fp16", "fp16"], ["fp32", "fp32"]] as const}
                  cannot={optCannot("hyper.precision")}
                  onChange={(v) => setHyper({ precision: v as TrainingConfig["hyper"]["precision"] })} />
                {/* The mirror image of the row below it: quantization is
                    for a LoRA, where the trained weights are tiny and the
                    frozen ones are everything; this is for a FULL finetune,
                    where the trained weights ARE the memory.

                    HIDDEN rather than dimmed on an adapter, which is the
                    exception to this page's own rule. A dimmed row exists so
                    its answer stays readable while it does not apply — and
                    this one has no answer to keep: it cannot be reached from
                    a LoRA, an adapter run always leaves it off, and what it
                    would save there is tens of megabytes out of tens of
                    gigabytes (`spec.py` has the figures). A row that can only
                    ever read "off, unsupported" is one line of the page spent
                    saying nothing. It comes back with the method, since the
                    setting travels on the config either way. */}
                {!isLora && (
                <ToggleRow label={t("Half-precision master weights")}
                  checked={config.hyper.bf16_masters}
                  disabled={toggleLocked(!!rowCannot("hyper.bf16_masters"),
                                         config.hyper.bf16_masters)}
                  unsupported={rowCannot("hyper.bf16_masters")}
                  hint={t("Keeps the trained weights and their gradients at 16 bits instead of 32. What the rounding drops is carried to the next update, so the run learns what it would have learned; the cost is one more buffer of the same width.")}
                  details={t(HELP["precision-quantization.half-precision-master-weights"])}
                  onChange={(v) => setHyper({ bf16_masters: v })} />
                )}
                <SelectRow label={t("Base model quantization")} value={config.hyper.quantization}
                  disabled={!isLora}
                  unsupported={rowCannot("hyper.quantization")}
                  cannot={optCannot("hyper.quantization")}
                  hint={isLora
                    ? t("Loads the frozen base weights in 8-bit or 4-bit so big models fit in little memory (QLoRA). 8-bit (int8) runs on Apple silicon too; fp8 and 4-bit need an NVIDIA GPU.")
                    : t("Only available for LoRA training — a full finetune updates the base weights, so they can't be quantized.")}
                  details={t(HELP["precision-quantization.base-model-quantization"])}
                  options={[["none", t("None (full precision)")],
                    ["fp8", t("8-bit float (fp8)")], ["int8", t("8-bit (int8)")],
                    ["nf4", t("4-bit (NF4)")]] as const}
                  onChange={(v) => setHyper({ quantization: v as TrainingConfig["hyper"]["quantization"] })} />
                {/* The OTHER large frozen model. Its own switch because it
                    shrinks a different term of the estimate — and because a
                    run that already fits should not pay for it silently. */}
                <ToggleRow label={t("Quantize the text encoder")}
                  checked={config.hyper.quantize_text_encoder}
                  disabled={toggleLocked(
                    !isLora || config.hyper.quantization === "none",
                    config.hyper.quantize_text_encoder)}
                  unsupported={rowCannot("hyper.quantize_text_encoder")}
                  hint={t("Applies the same scheme to the text encoder, the other big frozen model. On the largest models it is worth several GB.")}
                  details={t(HELP["precision-quantization.quantize-the-text-encoder"])}
                  onChange={(v) => setHyper({ quantize_text_encoder: v })} />
                {/* The SAME model as the row above and the other thing you can
                    do to it: shrink it, or move it off the card entirely.
                    Beside it rather than in "Memory savers" because what it
                    is ABOUT is the text encoder, and a reader deciding what
                    to do with that should see both answers together. */}
                <ToggleRow label={t("Keep the text encoder on the CPU")}
                  checked={config.hyper.offload_text_encoder}
                  disabled={toggleLocked(config.hyper.train_text_encoder,
                                         config.hyper.offload_text_encoder)}
                  unsupported={rowCannot("hyper.offload_text_encoder")}
                  hint={t("Frees all of its VRAM instead of some. The next batch's prompt is encoded while this one trains, so it costs nothing as long as the processor keeps up with the card.")}
                  details={t(HELP["precision-quantization.keep-the-text-encoder-on-the-cpu"])}
                  onChange={(v) => setHyper({ offload_text_encoder: v })} last />
              </Section>

              <Section label={t("Memory savers")}>
                <ToggleRow label={t("Gradient checkpointing")}
                  checked={config.hyper.gradient_checkpointing}
                  hint={t("Trades ~25% speed for a large VRAM saving. Recommended for full finetunes and big models.")}
                  details={t(HELP["memory-savers.gradient-checkpointing"])}
                  onChange={(v) => setHyper({ gradient_checkpointing: v })} />
                {/* A CUDA-only VRAM lever. On NVIDIA the default fused-attention
                    kernels are the fast, memory-efficient path; slicing trades a
                    little speed for lower peak VRAM when you're memory-bound. On
                    Apple silicon the trainer uses the efficient default and does
                    not slice, so the control is fixed off there. "Automatic" was
                    identical to "Off" on every platform, so it's gone. */}
                <SelectRow label={t("Attention slicing")}
                  value={config.hyper.attention_slicing === "on" ? "on" : "off"}
                  cannot={optCannot("hyper.attention_slicing")}
                  options={[["off", t("Off (fused kernels)")], ["on", t("On (save VRAM)")]] as const}
                  hint={t("NVIDIA only: slice attention into chunks to lower peak VRAM when a run won't otherwise fit, at some cost in speed. Off by default — the fused attention kernels are faster.")}
                  details={t(HELP["memory-savers.attention-slicing"])}
                  onChange={(v) => setHyper({ attention_slicing: v as "on" | "off" })} />
                <SelectRow label={t("Optimizer")} value={config.hyper.optimizer}
                  cannot={optCannot("hyper.optimizer")}
                  hint={t("Mostly a memory choice, except for Prodigy, which works the learning rate out for itself. Adafactor saves the most memory and runs on every GPU; 8-bit AdamW saves less and needs an NVIDIA or AMD card.")}
                  details={t(HELP["memory-savers.optimizer"])}
                  options={[["adamw", "AdamW"], ["adamw_8bit", t("AdamW (8-bit)")],
                    ["adafactor", "Adafactor"],
                    ["prodigy", t("Prodigy (finds its own rate)")]] as const}
                  onChange={(v) => setOptimizer(v as TrainingConfig["hyper"]["optimizer"])} />
                {config.hyper.optimizer === "prodigy" && (
                  <NoteRow>
                    {t("Prodigy works the learning rate out for itself, so the rate on the Optimization page becomes a multiplier on what it finds — 1 leaves it alone. It needs a few hundred steps to settle, so early samples will look untrained.")}
                  </NoteRow>
                )}
                <ToggleRow label={t("Cache latents")} last
                  checked={config.hyper.cache_latents}
                  hint={t("Pre-encode every image once and reuse it all run (random crops still vary — they happen in latent space). Frees the VAE from VRAM; uses some disk.")}
                  details={t(HELP["memory-savers.cache-latents"])}
                  onChange={(v) => setHyper({ cache_latents: v })} />
              </Section>
            </>
          ) : page === "dataset" ? (
            <>
              {/* `bare`: the queries editor brings its own boxes, so the
                  section contributes the heading and nothing around them. */}
              <Section label={t("Training images")} bare
                hint={t("Training images come straight from the library. Add several queries with weights to mix datasets — a weight-2 query counts for twice as much as a weight-1 query.")}>
                <QueriesEditor queries={config.queries} config={config}
                  onChange={(qs) => set({ queries: qs })} />
              </Section>

              {/* Only worth asking once there are two pools to weigh against
                  each other. */}
              {config.queries.length > 1 && (
              <Section label={t("Query weight")}>
                <SelectRow label={t("A weight buys")}
                  value={config.weight_mode}
                  hint={t("Whether a heavier query's images are seen more often, or seen the same and counted for more.")}
                  details={t(HELP["query-weight.a-weight-buys"])}
                  options={[["sampling", t("Seen more often")],
                            ["loss", t("Counted for more")]] as const}
                  onChange={(v) => set({ weight_mode: v as TrainingConfig["weight_mode"] })}
                  last />
              </Section>
              )}

              {/* Only once a pool is actually marked one — the number means
                  nothing otherwise, and a row that is always there invites
                  the question of what it does to a run with no reminder
                  images (nothing). */}
              {config.queries.some((q) => q.regularize) && (
              <Section label={t("Regularization")}>
                <NumRow label={t("How much reminders count")}
                  value={config.reg_strength}
                  min={0} max={10} step={0.1} last
                  hint={t("1 gives a regularization picture the same say as a training picture, which is the usual setting. Lower makes it a gentler reminder.")}
                  details={t(HELP["regularization.how-much-reminders-count"])}
                  onChange={(v) => set({ reg_strength: v })} />
              </Section>
              )}
              {/* ONE LIST FOR THE SIZES, and "Never upscale" under it:
                  what counts as "too small" is a bucket of one of these
                  resolutions, and the setting's own answer — join the sizes
                  you fit — is only readable beside them. */}
              <Section label={t("Resolutions")}>
                <ResolutionPicker
                  value={config.buckets.resolutions}
                  native={nativeArea}
                  hint={t("Pick every size this run should train at. A picture joins each one it is big enough for, so the same picture can be learnt at more than one scale — and each size is another pass over the dataset per epoch.")}
                  details={t(HELP["resolutions.resolutions"])}
                  onChange={(v) => setBuckets({ resolutions: v })} />
                <ToggleRow label={t("Never upscale")} last
                  checked={config.buckets.skip_upscale}
                  hint={t("Leave out any image smaller than the bucket it would be fitted to, rather than enlarging it.")}
                  details={t(HELP["resolutions.never-upscale"])}
                  onChange={(v) => setBuckets({ skip_upscale: v })} />
              </Section>
              <Section label={t("Crops & flips")}>
                <NumRow label={t("Max aspect ratio")} value={config.buckets.max_aspect}
                  min={1} max={4} step={0.1} last={instructing}
                  details={t(HELP["crops-flips.max-aspect-ratio"])}
                  hint={t("Images are sorted into width/height buckets of equal area so nothing gets squashed. This caps how extreme the buckets get (2 = up to 2:1 and 1:2).")}
                  onChange={(v) => setBuckets({ max_aspect: v })} />
                {/* Both of these move the TARGET and not its reference
                    pictures, so on an instruction run they would break the very
                    correspondence the run is teaching. Not offered rather than
                    refused — the setting simply has no meaning here. */}
                {!instructing && (<>
                <ToggleRow label={t("Random crop")} checked={config.buckets.random_crop}
                  hint={t("Each visit crops a different window of the image (augmentation — helps small datasets). Off = always the center crop.")}
                  details={t(HELP["crops-flips.random-crop"])}
                  onChange={(v) => setBuckets({ random_crop: v })} />
                <NumRow label={t("Horizontal flip probability")} value={config.buckets.flip_p}
                  min={0} max={0.5} step={0.05} last
                  details={t(HELP["crops-flips.horizontal-flip-probability"])}
                  hint={t("Randomly mirrors images. Free variety for most subjects — keep 0 for text, logos or asymmetric characters.")}
                  onChange={(v) => setBuckets({ flip_p: v })} />
                {/* Only worth showing once flipping is actually on. */}
                {config.buckets.flip_p > 0 && (<>
                  <TextRow label={t("Never flip images tagged")} wide
                    value={config.buckets.no_flip_tags.join(", ")}
                    hint={t("Comma-separated tags that switch mirroring off for the images carrying them, e.g. 'text'. Everything else still flips.")}
                    details={t(HELP["crops-flips.never-flip-images-tagged"])}
                    onChange={(v) => setBuckets({ no_flip_tags: splitTags(v) })} />
                  {/* The same veto said ONCE, in the library, instead of tag
                      by tag here: a meta tag put on the tags mirroring would
                      spoil covers every picture carrying one — including
                      tags added after this job was written. */}
                  <TextRow label={t("Never flip images whose tags are marked")} wide last
                    value={config.buckets.no_flip_meta_tags.join(", ")}
                    hint={t("Comma-separated META tags. Any tag the library marks with one of these switches mirroring off for the pictures carrying that tag — so the rule is stated once in the Tags tab rather than listed here.")}
                    details={t(HELP["crops-flips.never-flip-images-whose-tags-are-marked"])}
                    onChange={(v) => setBuckets({ no_flip_meta_tags: splitTags(v) })} />
                </>)}
                </>)}
              </Section>

              {/* Degrading the TARGET of an edit while its reference pictures
                  stay pristine teaches the model to ADD compression artifacts
                  to an edit — the same reason flip and random crop are not
                  offered above. Not shown rather than refused. */}
              {!instructing && (
                <DegradeSection config={config}
                  onChange={(d) => set({ degrade: d })} />
              )}

              {/* A video frame is nobody's instruction target — nothing wrote
                  an instruction for one particular frame. */}
              {!instructing && (
              <Section label={t("Videos")}>
                <ToggleRow label={t("Train on video frames")}
                  checked={config.video.include}
                  hint={t("Off, a video the queries match is skipped. On, its frames are extracted while the dataset is built, trained on as images, and deleted with the run.")}
                  details={t(HELP["videos.train-on-video-frames"])}
                  onChange={(v) => setVideo({ include: v })}
                  last={!config.video.include} />
                {config.video.include && (
                  <>
                    <NumRow label={t("One frame every")}
                      value={config.video.every}
                      min={config.video.unit === "frames" ? 1 : 0.1}
                      max={3600}
                      step={config.video.unit === "frames" ? 1 : 0.5}
                      suffix={config.video.unit === "frames" ? t("frames") : t("seconds")}
                      hint={t("The sampling interval. A second apart is a good starting point — consecutive frames of a film are the same picture, and every one of them costs a step's worth of training.")}
                      details={t(HELP["videos.one-frame-every"])}
                      onChange={(v) => setVideo({ every: v })} />
                    <SelectRow label={t("Interval unit")} value={config.video.unit}
                      hint={t("Seconds follows the clock whatever the frame rate; frames counts the file's own frames.")}
                      options={[["seconds", t("Seconds")], ["frames", t("Frames")]] as const}
                      onChange={(v) => setVideo({ unit: v as TrainingConfig["video"]["unit"] })} />
                    <ToggleRow label={t("Drop repeated frames")}
                      checked={config.video.dedupe}
                      hint={t("A shot held for five seconds is one picture, not five. Each kept frame is compared with the ones already kept from the same video.")}
                      details={t(HELP["videos.drop-repeated-frames"])}
                      onChange={(v) => setVideo({ dedupe: v })}
                      last={config.captions.source === "tags"} />
                    {/* Only where a prompt can contain caption text at all —
                        with tags alone there is nothing here to decide. */}
                    {config.captions.source !== "tags" && (
                      <>
                        <SelectRow label={t("The film's captions")}
                          value={config.video.captions}
                          hint={t("Whether a frame is trained against the captions written on the video it came from.")}
                          details={t(HELP["videos.the-films-captions"])}
                          options={[["inherit", t("Its frames inherit them")],
                                    ["none", t("Its frames get none")]] as const}
                          onChange={(v) => setVideo({
                            captions: v as TrainingConfig["video"]["captions"] })}
                          last={config.video.captions !== "inherit"} />
                        {config.video.captions === "inherit" && (
                          <>
                            <TextRow label={t("Frames only inherit captions tagged")} wide
                              value={config.video.caption_include_meta_tags.join(", ")}
                              hint={t("Comma-separated meta tags. When set, a frame inherits only the captions carrying one of them. Empty = every caption the run already allows.")}
                              details={t(HELP["videos.frames-only-inherit-captions-tagged"])}
                              onChange={(v) => setVideo({ caption_include_meta_tags: splitTags(v) })} />
                            <TextRow label={t("Frames never inherit captions tagged")} wide last
                              value={config.video.caption_exclude_meta_tags.join(", ")}
                              hint={t("Comma-separated meta tags whose captions no frame inherits. Applied after the include list, so it also removes captions the list let in.")}
                              details={t(HELP["videos.frames-never-inherit-captions-tagged"])}
                              onChange={(v) => setVideo({ caption_exclude_meta_tags: splitTags(v) })} />
                          </>
                        )}
                      </>
                    )}
                  </>
                )}
              </Section>
              )}

              <Section label={t("Transparency")}>
                <ToggleRow label={t("Use alpha as a loss mask")}
                  checked={config.buckets.alpha_mask}
                  hint={t("For cut-out images (transparent background): train on the visible pixels and largely ignore the rest. Images without transparency are unaffected.")}
                  details={t(HELP["transparency.use-alpha-as-a-loss-mask"])}
                  onChange={(v) => setBuckets({ alpha_mask: v })}
                  last={!config.buckets.alpha_mask} />
                {config.buckets.alpha_mask && (
                  <NumRow label={t("Background weight")} last
                    value={config.buckets.alpha_bg_weight}
                    min={0} max={1} step={0.05}
                    hint={t("How much the transparent region still counts. 0 ignores it completely; a little (0.05–0.2) keeps some sense of what surrounds the subject. 1 is the same as masking off.")}
                    details={t(HELP["transparency.background-weight"])}
                    onChange={(v) => setBuckets({ alpha_bg_weight: v })} />
                )}
              </Section>

              {/* The other loss mask: not "where the picture is transparent"
                  but "where a named tag's boxes are" — a watermark, a caption
                  strip. The two multiply where both apply. */}
              <Section label={t("Masked regions")}>
                <TextRow label={t("Mask out regions tagged")} wide
                  value={config.buckets.mask_loss_tags.join(", ")}
                  hint={t("Comma-separated tags whose bounding boxes are largely ignored by the loss — e.g. 'watermark'. The picture still trains; the region inside the boxes stops teaching. Tags without boxes on an image mask nothing there.")}
                  details={t(HELP["masked-regions.mask-out-regions-tagged"])}
                  onChange={(v) => setBuckets({ mask_loss_tags: splitTags(v) })} />
                <TextRow label={t("Mask out regions of tags marked")} wide
                  value={config.buckets.mask_loss_meta_tags.join(", ")}
                  hint={t("Comma-separated META tags. Any tag the library marks with one of these has its boxes masked — so the rule is stated once in the Tags tab rather than listed here.")}
                  details={t(HELP["masked-regions.mask-out-regions-of-tags-marked"])}
                  onChange={(v) => setBuckets({ mask_loss_meta_tags: splitTags(v) })}
                  last={config.buckets.mask_loss_tags.length === 0
                    && config.buckets.mask_loss_meta_tags.length === 0} />
                {(config.buckets.mask_loss_tags.length > 0
                  || config.buckets.mask_loss_meta_tags.length > 0) && (
                  <NumRow label={t("Masked region weight")} last
                    value={config.buckets.mask_loss_weight}
                    min={0} max={1} step={0.05}
                    hint={t("How much a masked region still counts. 0 hides it from training entirely; 1 is the same as not masking.")}
                    details={t(HELP["masked-regions.masked-region-weight"])}
                    onChange={(v) => setBuckets({ mask_loss_weight: v })} />
                )}
              </Section>
            </>
          ) : page === "captions" ? (
            <>
              <Section label={t("Source")}>
                <SelectRow label={t("Build prompts from")} value={config.captions.source}
                  hint={t("What each training prompt is made of: the item's caption text, its tags, caption followed by tags, or nothing but the trigger word.")}
                  details={t(HELP["source.build-prompts-from"])}
                  options={[["tags", t("Tags")], ["captions", t("Captions")],
                    ["both", t("Caption + tags")],
                    // LAST, because it is the answer for a run that has no
                    // text at all — the trigger word alone — rather than
                    // one of the three ways of choosing some.
                    ["none", t("Nothing (trigger word only)")],
                    // Only where it can mean something. An instruction run
                    // needs a model that takes reference pictures beside the
                    // prompt, and the backend refuses the pair anyway.
                    ...(model?.edit
                      ? [["instructions", t("Instructions")] as const] : []),
                  ] as const}
                  onChange={(v) => setCaptions({ source: v as TrainingConfig["captions"]["source"] })} />
                {model?.edit_only && !instructing && (
                  <NoteRow tone="warn">
                    {t("This model exists to edit a picture it is given, so this trains the half of it nobody generates with. It works, and the result will not know what to do with a reference image — pick Instructions unless that is what you meant.")}
                  </NoteRow>
                )}
                {instructing && (
                  <NoteRow>
                    {t("Each image trains as the RESULT of one of its instructions, with that instruction's reference images as the input. Items carrying no instruction are left out of the run, and tag selection does not apply.")}
                  </NoteRow>
                )}
                {config.captions.source === "none" && (
                  <NoteRow tone={config.captions.trigger.trim() ? "muted" : "warn"}>
                    {config.captions.trigger.trim()
                      ? t("Every prompt is the trigger word and nothing else, so every selected picture is in the run whatever it carries. Tag and caption selection do not apply.")
                      : t("Every prompt would be EMPTY — with no text at all, there is nothing for the model to bind what it sees to. Set a trigger word below.")}
                  </NoteRow>
                )}
                <TextRow label={t("Trigger word")} value={config.captions.trigger}
                  hint={t("Prepended to every prompt. Use a rare token (e.g. 'ohwx style') you'll later type to invoke the trained concept.")}
                  details={t(HELP["source.trigger-word"])}
                  onChange={(v) => setCaptions({ trigger: v })} last />
              </Section>

              {/* CAPTION SELECTION IS ITS OWN SECTION. Which captions a run
                  may use is a different question from what a prompt is built
                  OUT of, and mixing the two put two long text fields between
                  the source dropdown and the trigger word that belongs beside
                  it. Shown only where it can mean something: with tags
                  alone there is no caption to pick, and with nothing but
                  the trigger word there is no text at all. */}
              {config.captions.source !== "tags"
               && config.captions.source !== "none" && (
              <Section label={instructing ? t("Instruction selection")
                                          : t("Caption selection")}>
                <TextRow label={instructing ? t("Only instructions tagged")
                                : t("Only captions tagged")} wide
                value={config.captions.include_meta_tags.join(", ")}
                hint={instructing
                  ? t("Comma-separated meta tags. When set, only instructions carrying one of them are used — the meta tags on an instruction, not the item's own tags. Empty = every instruction.")
                  : t("Comma-separated meta tags. When set, only captions carrying one of them are used — the meta tags on a caption, not the item's own tags. Empty = every caption.")}
                details={t(HELP["instruction-selection.only-instructions-tagged"])}
                onChange={(v) => setCaptions({ include_meta_tags: splitTags(v) })} />
                {!instructing && (
                  <SelectRow label={t("An item with several captions")}
                    value={config.captions.caption_repeat}
                    hint={t("Whether every caption is used each pass, or one is drawn per visit.")}
                    details={t(HELP["instruction-selection.an-item-with-several-captions"])}
                    options={[["random", t("One at random each visit")],
                              ["each", t("Every caption, once each")],
                              ["each_shared", t("Every caption, sharing one item's weight")]] as const}
                    onChange={(v) => setCaptions({
                      caption_repeat: v as TrainingConfig["captions"]["caption_repeat"] })} />
                )}
                <TextRow label={instructing ? t("Skip instructions tagged")
                                : t("Skip captions tagged")} wide
                value={config.captions.exclude_meta_tags.join(", ")}
                hint={instructing
                  ? t("Comma-separated meta tags whose instructions are never used. Applied after the include list, so it also removes instructions the list let in.")
                  : t("Comma-separated meta tags whose captions are never used. Applied after the include list, so it also removes captions the list let in.")}
                details={t(HELP["instruction-selection.skip-instructions-tagged"])}
                onChange={(v) => setCaptions({ exclude_meta_tags: splitTags(v) })} last />
              </Section>
              )}

              {/* Only where the prompt actually CONTAINS tags. A captions
                  run and an instruction run both build their text from
                  something else, so every row here would be a setting with no
                  effect — visible, editable, and doing nothing. */}
              {(config.captions.source === "tags"
                || config.captions.source === "both") && (
              <Section label={t("Tag selection")}
                hint={t("Tags are re-picked and re-shuffled fresh every time an image is visited.")}>
                <TextRow label={t("Always include")} wide
                  value={config.captions.always_tags.join(", ")}
                  hint={t("Comma-separated tags the random pick can never drop — included (at a random position) whenever the image actually has the tag, e.g. 'watermark'. Never forced onto images without it.")}
                  details={t(HELP["tag-selection.always-include"])}
                  onChange={(v) => setCaptions({ always_tags: splitTags(v) })} />
                {/* The same rule one level up: a meta tag on the vocabulary
                    applies to every tag carrying it, including tags made
                    after this job was written. */}
                <TextRow label={t("Always include tags marked")} wide
                  value={config.captions.always_tag_meta_tags.join(", ")}
                  hint={t("Comma-separated META tags. Any tag the library marks with one of these is never dropped by the random pick — again, only where the image actually has that tag.")}
                  details={t(HELP["tag-selection.always-include-tags-marked"])}
                  onChange={(v) => setCaptions({ always_tag_meta_tags: splitTags(v) })} />
                <TextRow label={t("Exclude")} wide
                  value={config.captions.exclude_tags.join(", ")}
                  hint={t("Comma-separated tags stripped from prompts (e.g. quality tags or the concept itself when using a trigger word).")}
                  details={t(HELP["tag-selection.exclude"])}
                  onChange={(v) => setCaptions({ exclude_tags: splitTags(v) })} />
                <TextRow label={t("Exclude tags marked")} wide
                  value={config.captions.exclude_tag_meta_tags.join(", ")}
                  hint={t("Comma-separated META tags. Any tag the library marks with one of these is stripped from prompts.")}
                  details={t(HELP["tag-selection.exclude-tags-marked"])}
                  onChange={(v) => setCaptions({ exclude_tag_meta_tags: splitTags(v) })} />
                <TextRow label={t("Skip tag groups tagged")} wide
                  value={config.captions.exclude_tag_group_meta_tags.join(", ")}
                  hint={t("Comma-separated meta tags naming whole tag groups to ignore: a tag placed only in such a group never reaches a prompt. The tags stay on your items.")}
                  details={t(HELP["tag-selection.skip-tag-groups-tagged"])}
                  onChange={(v) => setCaptions({ exclude_tag_group_meta_tags: splitTags(v) })} />
                <NumRow label={t("Min tags per prompt")} value={config.captions.min_tags}
                  min={0} step={1} placeholder={t("no limit")}
                  hint={t("Lower bound of the random pick. Both limits empty = use all tags.")}
                  details={t(HELP["tag-selection.min-tags-per-prompt"])}
                  onChange={(v) => setCaptions({ min_tags: v })} />
                <NumRow label={t("Max tags per prompt")} value={config.captions.max_tags}
                  min={0} step={1} placeholder={t("no limit")}
                  hint={t("Upper bound of the random pick. Picking a random subset each visit teaches tags independently instead of as a fixed clump.")}
                  details={t(HELP["tag-selection.max-tags-per-prompt"])}
                  onChange={(v) => setCaptions({ max_tags: v })} />
                <SelectRow label={t("Pick probability")} value={config.captions.balance}
                  hint={t("'Balance rare tags' picks tags with probability ∝ 1/frequency, so rare tags appear about as often as common ones over the whole run — the model stops over-learning your most frequent tags.")}
                  details={t(HELP["tag-selection.pick-probability"])}
                  options={[["none", t("Uniform")],
                    ["inverse_freq", t("Balance rare tags")]] as const}
                  onChange={(v) => setCaptions({ balance: v as TrainingConfig["captions"]["balance"] })} />
                {config.captions.balance === "inverse_freq" && (
                  <SelectRow label={t("Frequency measured in")} value={config.captions.freq_base}
                    hint={t("Whether a tag's rarity is measured within the selected training images or across the whole library.")}
                    details={t(HELP["tag-selection.frequency-measured-in"])}
                    options={[["dataset", t("Training data")],
                              ["library", t("Whole library")]] as const}
                    onChange={(v) => setCaptions({ freq_base: v as TrainingConfig["captions"]["freq_base"] })} />
                )}
                <ToggleRow label={t("Weight loss by tag rarity")}
                  checked={config.captions.loss_weight_by_freq}
                  hint={t("Same balancing goal, different lever: images whose tags are rare count more toward each update (clamped ×0.25–×4). Combines with the pick probability above.")}
                  details={t(HELP["tag-selection.weight-loss-by-tag-rarity"])}
                  onChange={(v) => setCaptions({ loss_weight_by_freq: v })} />
                <ToggleRow label={t("Skip partially matching tags")}
                  checked={config.captions.skip_partial_tags !== false}
                  hint={t("If a picked tag is a whole-word part of another picked tag ('shirt' next to 'white shirt'), the generic one is replaced by a different random tag — the prompt never teaches both as one clump.")}
                  details={t(HELP["tag-selection.skip-partially-matching-tags"])}
                  onChange={(v) => setCaptions({ skip_partial_tags: v })} />
                <ToggleRow label={t("Shuffle tag order")} checked={config.captions.shuffle}
                  hint={t("Standard practice: prevents the model from binding concepts to a fixed tag position.")}
                  details={t(HELP["tag-selection.shuffle-tag-order"])}
                  onChange={(v) => setCaptions({ shuffle: v })} />
                <NumRow label={t("Caption dropout")} value={config.captions.dropout}
                  min={0} max={0.5} step={0.05}
                  hint={t("Chance of training a step with an EMPTY prompt (0.05–0.1). Preserves the model's unconditional quality and improves CFG behavior.")}
                  details={t(HELP["tag-selection.caption-dropout"])}
                  onChange={(v) => setCaptions({ dropout: v })} />
                <TextRow label={t("Tag separator")}
                  value={config.captions.separator}
                  hint={t("Joins the prompt parts; comma + space is the standard.")}
                  details={t(HELP["tag-selection.tag-separator"])}
                  onChange={(v) => setCaptions({ separator: v || ", " })} />
                {/* Grouping and its two sub-settings, then the formatting
                    rows: the layout question comes before the spelling one. */}
                <ToggleRow label={t("Group tags by tag group")}
                  checked={config.captions.group_tags}
                  hint={t("Lay the picked tags out one block per tag group instead of one flat list, so what belongs to the same thing in the picture stays together.")}
                  details={t(HELP["tag-selection.group-tags-by-tag-group"])}
                  onChange={(v) => setCaptions({ group_tags: v })} />
                {config.captions.group_tags && (
                  <>
                    <SelectRow label={t("Label each block with")}
                      value={config.captions.group_label}
                      options={[["none", t("Nothing")] as const,
                                ["group", t("The tag group's name")] as const,
                                ["subject", t("The subjects it is about")] as const]}
                      hint={t("What to write in front of a block, as “label: tags”. Nothing by default — a group's name is often for the person tagging rather than for the model.")}
                      details={t(HELP["tag-selection.label-each-block-with"])}
                      onChange={(v) => setCaptions({ group_label: v as "none" | "group" | "subject" })} />
                    {/* Shown as the ESCAPED form: the default is a newline,
                        which a single-line input renders as nothing at all —
                        an empty box reads as "unset". */}
                    <TextRow label={t("Between groups")}
                      value={showEscapes(config.captions.group_separator)}
                      hint={t("Put between blocks. A newline by default, which is what makes them read as separate statements.")}
                      details={t(HELP["tag-selection.between-groups"])}
                      onChange={(v) => setCaptions({ group_separator: readEscapes(v) || "\n" })} />
                  </>
                )}
                <NumRow label={t("Write tags as an alias")}
                  value={config.captions.alias_p}
                  min={0} max={1} step={0.05}
                  hint={t("Chance of writing a picked tag as one of its aliases instead of its own name, rolled per tag every time an image is visited.")}
                  details={t(HELP["tag-selection.write-tags-as-an-alias"])}
                  onChange={(v) => setCaptions({ alias_p: v })} />
                <SelectRow label={t("Write tags as")}
                  value={config.captions.tag_text}
                  options={[["name", t("Their name")],
                            ["comment", t("Their comment")],
                            ["both", t("Name and comment")]]}
                  hint={t("A tag's comment is the one line beside its name in the Tags tab — the same idea in words a text encoder can read. A tag with no comment is written as its name.")}
                  details={t(HELP["tag-selection.write-tags-as"])}
                  onChange={(v) => setCaptions({ tag_text: v as "name" | "comment" | "both" })} />
                <ToggleRow label={t("Underscores to spaces")} last
                  checked={config.captions.underscores_to_spaces}
                  hint={t("Write booru-style tags out in natural language ('red_fox' → 'red fox') in the training prompt. Matching and balancing still use the raw tag names.")}
                  details={t(HELP["tag-selection.underscores-to-spaces"])}
                  onChange={(v) => setCaptions({ underscores_to_spaces: v })} />
              </Section>
              )}

              {/* The same gate: a rule rewrites tags in the prompt, and a
                  run whose prompt holds no tags has nothing to rewrite. */}
              {(config.captions.source === "tags"
                || config.captions.source === "both") && (
                <ValueRulesSection rules={config.captions.value_rules}
                  onChange={(value_rules) => setCaptions({ value_rules })} />
              )}
            </>
          ) : page === "checkpoints" ? (
            <>
              <Section label={t("Checkpoints")}>
                <ToggleRow label={t("Keep step snapshots")}
                  checked={config.hyper.checkpoint_every > 0}
                  hint={t("Save a permanent snapshot every N steps, so the best-looking step can be picked afterwards. Off: only the resumable 'last' checkpoint is kept.")}
                  details={t(HELP["checkpoints.keep-step-snapshots"])}
                  onChange={(v) => setHyper({
                    // Off is off: an epoch cadence left behind would go on
                    // writing snapshots with the toggle saying it does not.
                    checkpoint_every: v ? 500 : 0, checkpoint_epochs: 0 })} />
                {config.hyper.checkpoint_every > 0 && (<>
                {/* The same choice the run's LENGTH offers, for the same
                    reason: "one per pass over my pictures" is a rhythm that
                    carries between datasets where a step count does not. */}
                <SelectRow label={t("Cadence measured in")}
                  value={config.hyper.checkpoint_epochs > 0 ? "epochs" : "steps"}
                  options={[["steps", t("Steps")], ["epochs", t("Epochs")]] as const}
                  hint={t("How often a snapshot is written: after a fixed number of steps, or after a number of full passes over the dataset.")}
                  details={t(HELP["checkpoints.cadence-measured-in"])}
                  onChange={(v) => setHyper({
                    checkpoint_epochs: v === "epochs"
                      ? Math.max(1, config.hyper.checkpoint_epochs || 1) : 0 })} />
                {config.hyper.checkpoint_epochs > 0 ? (
                <NumRow label={t("Checkpoint every")}
                  value={config.hyper.checkpoint_epochs}
                  min={1} step={1} suffix={t("epochs")}
                  hint={t("Written after this many full passes. The equivalent step count appears in the job's log when the run starts.")}
                  details={t(HELP["checkpoints.checkpoint-every"])}
                  onChange={(v) => setHyper({ checkpoint_epochs: v })} />
                ) : (
                <NumRow label={t("Checkpoint every")} value={config.hyper.checkpoint_every}
                  min={1} step={100} suffix={t("steps")}
                  details={t(HELP["checkpoints.checkpoint-every-2"])}
                  onChange={(v) => setHyper({ checkpoint_every: v })} />
                )}
                </>)}
                {/* Two independent rules, and a snapshot survives if
                    EITHER keeps it — "the last 5" plus "every 5th" is how
                    you hold on to a milestone every 1000 steps while still
                    having the recent ones to compare. */}
                <NumRow label={t("Keep the last")}
                  value={config.hyper.checkpoint_keep}
                  min={0} max={50} step={1} suffix={t("checkpoints")}
                  hint={t("A rolling window at the end of the run. 0 keeps none by recency.")}
                  details={t(HELP["checkpoints.keep-the-last"])}
                  onChange={(v) => setHyper({ checkpoint_keep: v })} />
                <NumRow label={t("Also keep one in")}
                  value={config.hyper.checkpoint_keep_every ?? 0}
                  min={0} max={50} step={1} last suffix={t("checkpoints")}
                  hint={ckptKeepHint}
                  details={t(HELP["checkpoints.also-keep-one-in"])}
                  onChange={(v) => setHyper({ checkpoint_keep_every: v })} />
              </Section>
            </>
          ) : (
            <>
              <Section label={t("Test samples")}
                hint={t("Generate preview images with the in-training model to watch progress in the job's timeline.")}>
                <ToggleRow label={t("Generate test samples")}
                  checked={sampleOn}
                  hint={t("Sampling pauses training briefly, so don't set it too low — every 250–500 steps is a good rhythm.")}
                  details={t(HELP["test-samples.generate-test-samples"])}
                  // Off is off: an epoch cadence left behind would go on
                  // rendering rounds with the toggle saying it does not —
                  // the checkpoints section's rule, one section along.
                  onChange={(v) => setSampling({
                    every_n_steps: v ? 250 : 0, every_n_epochs: 0 })} />
                {sampleOn && (<>
                {/* The same choice the checkpoint cadence and the run's own
                    LENGTH offer, for the same reason: "one round per pass
                    over my pictures" is a rhythm that carries between
                    datasets where a step count does not. */}
                <SelectRow label={t("Cadence measured in")}
                  value={config.sampling.every_n_epochs > 0 ? "epochs" : "steps"}
                  options={[["steps", t("Steps")], ["epochs", t("Epochs")]] as const}
                  hint={t("How often a round of samples is rendered: after a fixed number of steps, or after a number of full passes over the dataset.")}
                  details={t(HELP["test-samples.cadence-measured-in"])}
                  onChange={(v) => setSampling({
                    every_n_epochs: v === "epochs"
                      ? Math.max(1, config.sampling.every_n_epochs || 1) : 0 })} />
                {config.sampling.every_n_epochs > 0 ? (
                  <NumRow label={t("Generate every")}
                    value={config.sampling.every_n_epochs}
                    min={1} step={1} suffix={t("epochs")}
                    hint={t("Rendered after this many full passes. The equivalent step count appears in the job's log when the run starts.")}
                    details={t(HELP["test-samples.generate-every"])}
                    onChange={(v) => setSampling({ every_n_epochs: v })} />
                ) : (
                  <NumRow label={t("Generate every")} value={config.sampling.every_n_steps}
                    min={1} step={50} suffix={t("steps")}
                    details={t(HELP["test-samples.generate-every-steps"])}
                    onChange={(v) => setSampling({ every_n_steps: v })} />
                )}
                </>)}
                <ToggleRow label={t("Baseline before training")}
                  checked={config.sampling.at_start}
                  hint={t("Also render the prompts at step 0, before any training — the untrained reference to compare progress against.")}
                  details={t(HELP["test-samples.baseline-before-training"])}
                  onChange={(v) => setSampling({ at_start: v })} />
                {/* Shown whatever the prompt count is: prompts are added on
                    the page below this one, and a row that appears only after
                    you have gone and added a second prompt is a setting people
                    never find. */}
                <NumRow label={t("Batch size")} value={config.sampling.batch}
                    min={1} max={8} step={1}
                    hint={t("How many test prompts are rendered in one go. Only prompts of the same size can share a call, so a mixed set batches within each size — and images from one call appear together, so 1 shows them one by one.")}
                    details={t(HELP["test-samples.batch-size"])}
                    onChange={(v) => setSampling({ batch: v })} />
                <NumRow label={t("Sampler steps")} value={config.sampling.steps}
                  min={1} max={150} step={5}
                  details={t(HELP["test-samples.sampler-steps"])}
                  onChange={(v) => setSampling({ steps: v })} />
                <NumRow label={t("CFG scale")} value={config.sampling.cfg}
                  min={0} max={30} step={0.5}
                  details={t(HELP["test-samples.cfg-scale"])}
                  onChange={(v) => setSampling({ cfg: v })} />
                <NumRow label={t("Sample seed")} value={config.sampling.seed} step={1}
                  hint={t("Fixed per prompt so consecutive samples differ only by training progress.")}
                  details={t(HELP["test-samples.sample-seed"])}
                  onChange={(v) => setSampling({ seed: v })} />
                {/* THE MODEL'S OWN SIZE, not the run's: a prompt with no
                    size of its own reaches the engine as `None` and the
                    engine renders at its native area (`generate_samples`).
                    It said "the training resolution" while a job had one of
                    those, which was the same number often enough for nobody
                    to notice and is not what the trainer does. */}
                <SizeRow label={t("Size")} last
                  width={config.sampling.width} height={config.sampling.height}
                  placeholder={String(nativeArea)}
                  hint={t("Left empty both fields use the model's own size — a test sample is not tied to the sizes the run trains at.")}
                  onChange={(w, h) => setSampling({ width: w, height: h })} />
              </Section>

              {/* The prompt list is its own section at the bottom: the actions
                  sit on top, then one compact row per prompt/negative pair,
                  told apart by the leading icon rather than by a tint. */}
              <Section label={t("Test prompts")}
                hint={t("Include your trigger word — library tags autocomplete as you type. Keep the same prompts for the whole run so steps stay comparable.")}>
                <PromptSetsRow
                  prompts={config.sampling.prompts}
                  onAdd={() => setSampling({
                    prompts: [...config.sampling.prompts, { prompt: "", negative: "" }],
                  })}
                  onClear={() => setSampling({ prompts: [] })}
                  onLoad={(ps) => {
                    // Loading a set ADDS what is missing rather than replacing
                    // the list, so sets can be combined; a pair already present
                    // (same prompt and same negative) is not duplicated. Empty
                    // rows left over from "Add prompt" are dropped.
                    const key = (q: TrainSamplePrompt) => `${q.prompt.trim()}\u0000${q.negative.trim()}`;
                    const kept = config.sampling.prompts.filter((q) => q.prompt.trim() || q.negative.trim());
                    const have = new Set(kept.map(key));
                    const added = ps.filter((q) => !have.has(key(q))).map((q) => ({ ...q }));
                    setSampling({ prompts: [...kept, ...added] });
                  }}
                />
                {config.sampling.prompts.length === 0 && (
                  <div style={{ padding: "12px 16px", fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
                    {t("No prompts yet — add one to render test samples.")}
                  </div>
                )}
                {config.sampling.prompts.map((p, i) => (
                  <div key={i}
                    onDragOver={(e) => {
                      if (promptDrag.current == null) return;
                      e.preventDefault();
                      setDropAt(slotAt(i, e.clientY, e.currentTarget.getBoundingClientRect()));
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      dropPrompt(slotAt(i, e.clientY, e.currentTarget.getBoundingClientRect()));
                    }}
                    style={{
                      display: "flex", alignItems: "flex-start", gap: 6, padding: "8px 10px 8px 10px",
                      borderTop: "1px solid var(--border-soft)",
                      // Insertion line: above this row, or below it when this is
                      // the last row and the drop lands at the end.
                      boxShadow: dropAt === i ? "inset 0 2px 0 var(--accent)"
                        : dropAt === i + 1 && i === config.sampling.prompts.length - 1
                        ? "inset 0 -2px 0 var(--accent)" : undefined,
                    }}>
                    {/* Only the handle starts a reorder drag, so the prompt text
                        stays selectable. */}
                    <span
                      draggable
                      onDragStart={() => { promptDrag.current = i; }}
                      onDragEnd={() => { promptDrag.current = null; setDropAt(null); }}
                      title={t("Drag to reorder")}
                      style={{
                        flex: "0 0 auto", display: "flex", paddingTop: 8,
                        color: "var(--muted-3)", cursor: "grab",
                      }}
                    >
                      <Icon name="drag_indicator" size={15} />
                    </span>
                    <span style={{
                      flex: "0 0 auto", width: 14, paddingTop: 8, fontSize: "var(--fs-2)",
                      fontFamily: "var(--mono)", color: "var(--muted-2)", textAlign: "right",
                    }}>
                      {i + 1}
                    </span>
                    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                      <PromptArea label="" bare rows={1} icon="add_circle"
                        value={p.prompt}
                        placeholder={t("prompt — e.g. ohwx style, a fox in the snow")}
                        onChange={(v) => setSampling({
                          prompts: config.sampling.prompts.map((q, j) => j === i ? { ...q, prompt: v } : q),
                        })} />
                      <PromptArea label="" bare rows={1} icon="do_not_disturb_on"
                        value={p.negative}
                        placeholder={t("negative prompt (optional)")}
                        onChange={(v) => setSampling({
                          prompts: config.sampling.prompts.map((q, j) => j === i ? { ...q, negative: v } : q),
                        })} />
                      {/* Own size — shown once this prompt has one, so the list
                          stays two lines per prompt until you ask for more. */}
                      {(p.width || p.height) ? (
                        <PromptSizeRow
                          width={p.width ?? 0} height={p.height ?? 0}
                          placeholder={`${config.sampling.width || nativeArea} × ${config.sampling.height || nativeArea}`}
                          onChange={(w, h) => setSampling({
                            prompts: config.sampling.prompts.map((q, j) => j === i ? { ...q, width: w, height: h } : q),
                          })} />
                      ) : null}
                    </div>
                    <IconButton icon="aspect_ratio" size={24} glyph={15} color={(p.width || p.height) ? "var(--accent)" : "var(--muted)"}
                      title={(p.width || p.height)
                        ? t("Use the shared size for this prompt")
                        : t("Give this prompt its own size")}
                      onClick={() => {
                        const own = !!(p.width || p.height);
                        const w = own ? 0 : (config.sampling.width || nativeArea);
                        const h = own ? 0 : (config.sampling.height || nativeArea);
                        setSampling({
                          prompts: config.sampling.prompts.map((q, j) =>
                            j === i ? { ...q, width: w, height: h } : q),
                        });
                      }} style={{ flex: "0 0 auto", marginTop: 4 }} />
                    <IconButton icon="close" size={24} glyph={15} tone="muted"
                      title={t("Remove this prompt")}
                      onClick={() => setSampling({
                        prompts: config.sampling.prompts.filter((_, j) => j !== i),
                      })} style={{ flex: "0 0 auto", marginTop: 4 }} />
                  </div>
                ))}
              </Section>

              {/* The measured half of "how is it going": samples are what the
                  model DRAWS, this is a number that cannot be squinted at.
                  Held-out images say when the run starts memorizing; the
                  stable series is the training curve with the noise removed. */}
              <Section label={t("Validation")}>
                <ToggleRow label={t("Score a validation loss")}
                  checked={config.validation.every_n_steps > 0}
                  hint={t("A few images are held out of training and re-scored on a fixed seed as the run goes. Falling: still learning. Rising while the training loss falls: memorizing — pick an earlier checkpoint.")}
                  details={t(HELP["validation.score-a-validation-loss"])}
                  onChange={(v) => setValidation({ every_n_steps: v ? 200 : 0 })}
                  last={config.validation.every_n_steps <= 0} />
                {config.validation.every_n_steps > 0 && (<>
                  <NumRow label={t("Validate every")}
                    value={config.validation.every_n_steps}
                    min={1} step={50} suffix={t("steps")}
                    hint={t("Each round costs one forward pass per scored image — a small set every few hundred steps is barely noticeable.")}
                    details={t(HELP["validation.validate-every"])}
                    onChange={(v) => setValidation({ every_n_steps: v })} />
                  <NumRow label={t("Held-out images")}
                    value={config.validation.holdout}
                    min={0} step={1}
                    hint={t("Taken OUT of training entirely and scored each round. Capped at half the dataset; 16 is plenty for a LoRA-sized run. 0 turns the held-out series off.")}
                    details={t(HELP["validation.held-out-images"])}
                    onChange={(v) => setValidation({ holdout: v })} />
                  <NumRow label={t("Stable-loss images")} last
                    value={config.validation.stable_items}
                    min={0} step={1}
                    hint={t("Ordinary TRAINING images re-scored the same fixed way — the training curve without its sampling noise. They stay in training; 0 turns the series off.")}
                    details={t(HELP["validation.stable-loss-images"])}
                    onChange={(v) => setValidation({ stable_items: v })} />
                </>)}
              </Section>
            </>
          )}
        </div>
      </div>
    </Overlay>
    </>
  );
}

/** The row under the prompt pairs: add a new pair, and save/load prompt SETS
 *  (stored in the browser via localStorage; named after the fact in the list). */
/** The job-settings presets: save what is in the editor now, load a saved one
 *  into it, and mark one as where new jobs start. Deliberately the same menu
 *  as the test-prompt sets a page away — same rows, same rename-in-place, same
 *  ✕ — because it is the same idea applied to the whole configuration. */
function PresetsMenu({ config, models, onLoad }: {
  config: TrainingConfig;
  models: TrainModelSpec[];
  onLoad: (config: TrainingConfig) => void;
}) {
  const t = useT();
  const [presets, setPresets] = useState<TrainPreset[]>(loadPresets);
  const [menu, setMenu] = useState(false);
  const menuAnchor0 = useRef<HTMLButtonElement>(null);
  const menuRect0 = useAnchorRect(menuAnchor0, menu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(menu, () => setMenu(false), { within: [menuAnchor0] });
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const renameRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (renameId) renameRef.current?.select(); }, [renameId]);

  const openMenu = () => setMenu((v) => !v);

  const commit = (next: TrainPreset[]) => { setPresets(next); storePresets(next); };
  const commitRename = () => {
    if (!renameId) return;
    const v = renameVal.trim();
    if (v) commit(presets.map((p) => (p.id === renameId ? { ...p, name: v } : p)));
    setRenameId(null);
  };
  const renameKeys = useInlineEdit({ commit: commitRename,
                                     cancel: () => setRenameId(null), stop: true });
  const savePreset = () => {
    const taken = new Set(presets.map((p) => p.name));
    let n = presets.length + 1;
    while (taken.has(`${t("Preset")} ${n}`)) n++;
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const name = `${t("Preset")} ${n}`;
    // A deep copy: the editor keeps mutating `config` after this.
    commit([{ id, name, config: JSON.parse(JSON.stringify(config)) }, ...presets]);
    setRenameId(id);
    setRenameVal(name);
  };

  return (
    <div style={{ marginRight: "auto" }}>
      <Button ref={menuAnchor0} variant="ghost" size="md" onClick={openMenu}
        title={t("Save these settings as a preset, or load one")}>
        <Icon name="bookmarks" size={15} />{t("Presets")}
        <Icon name="expand_more" size={13} style={{ opacity: 0.7 }} />
      </Button>
      {menu && (
          <AnchoredDropdown rect={menuRect0} minWidth={280} focusable>
            <div
              className="hoverable"
              title={t("Remember every setting in this job — name the preset in this list afterwards")}
              onClick={savePreset}
              style={{
                display: "flex", alignItems: "center", gap: 8, padding: "6px 9px",
                borderRadius: "var(--r-3)", fontSize: "var(--fs-3)", color: "var(--text-2)",
                cursor: "pointer",
              }}>
              <Icon name="bookmark_add" size={14} color="var(--muted)" />
              <span style={{ flex: 1 }}>{t("Save current settings")}</span>
            </div>
            {presets.length > 0 && (
              <div style={{ height: 1, background: "var(--menu-border)", margin: "4px 2px" }} />
            )}
            {presets.map((p) => (
              <div key={p.id} style={{
                display: "flex", alignItems: "center", gap: 2, minHeight: 34,
                borderRadius: "var(--r-3)",
              }}>
                {renameId === p.id ? (
                  <>
                    <input
                      ref={renameRef}
                      value={renameVal}
                      onChange={(e) => setRenameVal(e.target.value)}
                      onBlur={renameKeys.onBlur}
                      onKeyDown={renameKeys.onKeyDown}
                      placeholder={t("Preset name")}
                      spellCheck={false}
                      style={{
                        flex: 1, minWidth: 0, margin: 2, background: "var(--bg)",
                        border: "1px solid var(--accent)", borderRadius: "var(--r-3)",
                        padding: "5px 7px", color: "var(--text)", fontSize: "var(--fs-3)",
                        fontWeight: 600, fontFamily: "inherit", outline: "none",
                      }}
                    />
                    <IconButton icon="check" size={24} glyph={15} tone="accent"
                      onMouseDown={(e) => { e.preventDefault(); commitRename(); }}
                      title={t("Done")} style={{ flex: "none" }} />
                  </>
                ) : (
                  <>
                    <button
                      className="hoverable"
                      onClick={() => {
                        setMenu(false);
                        onLoad(configFromPreset(p.config, models));
                      }}
                      title={t("Load this preset into the job — it replaces every setting")}
                      style={{
                        flex: 1, minWidth: 0, display: "flex", alignItems: "center",
                        gap: 7, textAlign: "left", background: "transparent",
                        border: "none", borderRadius: "var(--r-3)", padding: "5px 7px",
                        cursor: "pointer", fontFamily: "inherit",
                      }}
                    >
                      <span style={{
                        flex: 1, minWidth: 0, fontSize: "var(--fs-3)", fontWeight: 600,
                        color: "var(--text-2)", overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>{p.name}</span>
                      <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>
                        {String(p.config?.model || "").toUpperCase()}
                      </span>
                    </button>
                    {/* The star is the "new jobs start here" mark — one at a
                        time, and clicking the marked one clears it. */}
                    <IconButton icon={p.isDefault ? "star" : "star_outline"} size={24} glyph={14} color={p.isDefault ? "var(--accent)" : "var(--muted-2)"}
                      onClick={() => commit(withDefault(presets, p.id))}
                      title={p.isDefault
                        ? t("New jobs start from this preset — click to stop")
                        : t("Start new jobs from this preset")} style={{ flex: "none" }} />
                    <IconButton icon="edit" size={24} glyph={13}
                      onClick={() => { setRenameId(p.id); setRenameVal(p.name); }}
                      title={t("Rename")} style={{ flex: "none" }} />
                    <IconButton icon="close" size={24} glyph={14}
                      onClick={() => commit(presets.filter((x) => x.id !== p.id))}
                      title={t("Delete this preset")} style={{ flex: "none" }} />
                  </>
                )}
              </div>
            ))}
          </AnchoredDropdown>
        
)}
    </div>
  );
}


function PromptSetsRow({ prompts, onAdd, onClear, onLoad }: {
  prompts: TrainSamplePrompt[];
  onAdd: () => void;
  onClear: () => void;
  onLoad: (prompts: TrainSamplePrompt[]) => void;
}) {
  const t = useT();
  const [sets, setSets] = useState<PromptSet[]>(loadPromptSets);
  // Portaled and fixed-positioned like the other menus in this editor: the
  // Section's rounded box and the scrolling page both clip, so an in-flow
  // popup gets cut off as soon as a few sets are saved. `menu` holds the
  // anchor the button had when it opened.
  const [menu, setMenu] = useState(false);
  const menuAnchor1 = useRef<HTMLButtonElement>(null);
  const menuRect1 = useAnchorRect(menuAnchor1, menu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(menu, () => setMenu(false), { within: [menuAnchor1] });
  const openMenu = () => setMenu((v) => !v);
  const hasContent = prompts.some((p) => p.prompt.trim());

  // Exactly the saved-searches flow: a row is a plain entry until you rename
  // it, and saving drops you straight into naming the new one.
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const renameRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (renameId) renameRef.current?.select(); }, [renameId]);

  const commit = (next: PromptSet[]) => { setSets(next); storePromptSets(next); };
  const commitRename = () => {
    if (!renameId) return;
    const v = renameVal.trim();
    if (v) commit(sets.map((s) => (s.id === renameId ? { ...s, name: v } : s)));
    setRenameId(null);
  };
  const renameKeys = useInlineEdit({ commit: commitRename,
                                     cancel: () => setRenameId(null), stop: true });
  const saveSet = () => {
    const taken = new Set(sets.map((s) => s.name));
    let n = sets.length + 1;
    while (taken.has(`${t("Set")} ${n}`)) n++;
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const name = `${t("Set")} ${n}`;
    commit([{ id, name, prompts: prompts.map((p) => ({ ...p })) }, ...sets]);
    // The menu stays open with the new row in rename mode, so the name is
    // typed while you can still see what it is a name for.
    setRenameId(id);
    setRenameVal(name);
  };
  const deleteSet = (id: string) => commit(sets.filter((s) => s.id !== id));

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 16px", flexWrap: "wrap" }}>
      <Button variant="ghost" size="xs" icon="add" onClick={onAdd}>{t("Add prompt")}</Button>
      {prompts.length > 0 && (
        <Button variant="ghost" size="xs" icon="delete_sweep" onClick={onClear}
                title={t("Remove every prompt from this job")}>
          {t("Remove all")}
        </Button>
      )}
      <div style={{ flex: 1 }} />
      <div>
        {/* Saving and loading are the same subject, so they live in one menu:
            the button opens it whether or not anything is saved yet. */}
        <Button ref={menuAnchor1} variant="ghost" size="xs" icon="bookmarks"
          title={t("Save the current prompts, or load a saved set")}
          onClick={openMenu}>
          {t("Prompts")}
          <Icon name="expand_more" size={13} style={{ opacity: 0.7 }} />
        </Button>
        {menu && (
            <AnchoredDropdown rect={menuRect1} minWidth={250} focusable>
              <div
                className={hasContent ? "hoverable" : undefined}
                title={hasContent ? t("Remember the current prompts — name the set in this list afterwards") : t("Write a prompt first")}
                onClick={() => { if (hasContent) saveSet(); }}
                style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "6px 9px",
                  borderRadius: "var(--r-3)", fontSize: "var(--fs-3)", color: "var(--text-2)",
                  opacity: hasContent ? 1 : 0.45,
                  cursor: hasContent ? "pointer" : "default",
                }}>
                <Icon name="bookmark_add" size={14} color="var(--muted)" />
                <span style={{ flex: 1 }}>{t("Save current prompts")}</span>
              </div>
              {sets.length > 0 && (
                <div style={{ height: 1, background: "var(--menu-border)", margin: "4px 2px" }} />
              )}
              {sets.map((s) => (
                <div key={s.id} style={{
                  display: "flex", alignItems: "center", gap: 2, minHeight: 34,
                  borderRadius: "var(--r-3)",
                }}>
                  {renameId === s.id ? (
                    <>
                      <input
                        ref={renameRef}
                        value={renameVal}
                        onChange={(e) => setRenameVal(e.target.value)}
                        onBlur={renameKeys.onBlur}
                        onKeyDown={renameKeys.onKeyDown}
                        placeholder={t("Set name")}
                        spellCheck={false}
                        style={{
                          flex: 1, minWidth: 0, margin: 2, background: "var(--bg)",
                          border: "1px solid var(--accent)", borderRadius: "var(--r-3)",
                          padding: "5px 7px", color: "var(--text)", fontSize: "var(--fs-3)",
                          fontWeight: 600, fontFamily: "inherit", outline: "none",
                        }}
                      />
                      <IconButton icon="check" size={24} glyph={15} tone="accent"
                        onMouseDown={(e) => { e.preventDefault(); commitRename(); }}
                        title={t("Done")} style={{ flex: "none" }} />
                    </>
                  ) : (
                    <>
                      <button
                        className="hoverable"
                        onClick={() => { setMenu(false); onLoad(s.prompts); }}
                        title={t("Load this set into the job")}
                        style={{
                          flex: 1, minWidth: 0, display: "flex", alignItems: "center",
                          gap: 7, textAlign: "left", background: "transparent",
                          border: "none", borderRadius: "var(--r-3)", padding: "5px 7px",
                          cursor: "pointer", fontFamily: "inherit",
                        }}
                      >
                        <span style={{
                          flex: 1, minWidth: 0, fontSize: "var(--fs-3)", fontWeight: 600,
                          color: "var(--text-2)", overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}>{s.name}</span>
                        <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>
                          {s.prompts.length}
                        </span>
                      </button>
                      <IconButton icon="edit" size={24} glyph={13}
                        onClick={() => { setRenameId(s.id); setRenameVal(s.name); }}
                        title={t("Rename")} style={{ flex: "none" }} />
                      <IconButton icon="close" size={24} glyph={14}
                        onClick={() => deleteSet(s.id)}
                        title={t("Delete this set")} style={{ flex: "none" }} />
                    </>
                  )}
                </div>
              ))}
            </AnchoredDropdown>
          
)}
      </div>
    </div>
  );
}

/** One prompt's own width × height, with the size-preset menu. Compact enough
 *  to sit inside a prompt row; clearing a field falls back to the shared size. */
function PromptSizeRow({ width, height, placeholder, onChange }: {
  width: number; height: number; placeholder: string;
  onChange: (w: number, h: number) => void;
}) {
  const t = useT();
  const [menu, setMenu] = useState(false);
  const menuAnchor2 = useRef<HTMLButtonElement>(null);
  const menuRect2 = useAnchorRect(menuAnchor2, menu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(menu, () => setMenu(false), { within: [menuAnchor2] });
  const field: React.CSSProperties = {
    ...inputStyle, height: 24, width: 62, padding: "0 6px",
    fontSize: "var(--fs-2)", textAlign: "center",
  };
  const num = (v: number) => (v ? String(v) : "");
  const commit = (raw: string, other: number, isWidth: boolean) => {
    const v = Math.max(0, Math.min(4096, Math.round(Number(raw.replace(",", ".")) || 0)));
    onChange(isWidth ? v : other, isWidth ? other : v);
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5, paddingLeft: 2 }}>
      <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)", marginRight: 1 }}>
        {t("Size")}
      </span>
      <input defaultValue={num(width)} key={`w${width}`} placeholder={placeholder.split(" × ")[0]}
        inputMode="numeric" style={field}
        onBlur={(e) => commit(e.target.value, height, true)}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
      <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>×</span>
      <input defaultValue={num(height)} key={`h${height}`} placeholder={placeholder.split(" × ")[1]}
        inputMode="numeric" style={field}
        onBlur={(e) => commit(e.target.value, width, false)}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
      <button ref={menuAnchor2}
        title={t("Size presets")}
        onClick={() => setMenu((v) => !v)}
        style={{ ...field, width: 26, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: "var(--muted)" }}
      >
        <Icon name="photo_size_select_large" size={14} />
      </button>
      {menu && (
          <AnchoredDropdown rect={menuRect2} minWidth={170}>
            {SIZE_PRESETS.map(([group, sizes]) => (
              <div key={group}>
                <SectionHeading sm style={{ padding: "6px 9px 3px" }}>
                  {group}
                </SectionHeading>
                {sizes.map(([w, h]) => (
                  <div key={`${w}x${h}`} className="hoverable"
                    onClick={() => { setMenu(false); onChange(w, h); }}
                    style={{ padding: "5px 9px", borderRadius: "var(--r-2)", cursor: "pointer", fontSize: "var(--fs-2)", color: "var(--text-2)", fontFamily: "var(--mono)" }}>
                    {w} × {h}
                  </div>
                ))}
              </div>
            ))}
          </AnchoredDropdown>
        
)}
    </div>
  );
}

/** "Start from an existing LoRA": pick one of the finished jobs' weight sets
 *  (final output or a step checkpoint), or type a path to one elsewhere. */
function LoraStartRow({ value, model, models, disabled, onChange }: {
  value: string;
  model: string;
  models: TrainModelSpec[];
  disabled?: boolean;
  onChange: (v: string) => void;
}) {
  const t = useT();
  // Portaled like the size presets: the surrounding Section clips its
  // children, so an in-flow popup would be cut off once there are a few
  // checkpoints to choose from.
  const [menu, setMenu] = useState(false);
  const menuAnchor3 = useRef<HTMLButtonElement>(null);
  const menuRect3 = useAnchorRect(menuAnchor3, menu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(menu, () => setMenu(false), { within: [menuAnchor3] });
  const { data } = useQuery({
    queryKey: ["train-lora-sources"],
    queryFn: api.trainLoraSources,
  });
  // Only adapters that FIT: the model this job trains, and every other model
  // built on the same one — a custom SDXL and plain SDXL are the same layers
  // with different numbers in them. Matching the key alone hid every adapter
  // trained on a sibling model, which for a custom model was all of them.
  const sources = (data?.loras ?? [])
    .filter((l) => fitsModel(models, l.model, model));
  // …and the menu says which model each came from, in groups, because the
  // list now holds more than one model's work.
  const groups = useMemo(() => groupBy(sources, (l) => l.model), [sources]);
  const current = sources.find((l) => l.path === value);
  // A weight set is named by the step it holds — "final" alone said nothing
  // about how far that job actually trained. The icon carries final vs.
  // intermediate instead.
  const stepOf = (l: TrainLoraSource) => l.step ?? l.final_step;
  const stepText = (l: TrainLoraSource) =>
    stepOf(l) > 0 ? `${t("step")} ${stepOf(l)}` : t("final");
  const label = current ? `${current.name} · ${stepText(current)}` : "";

  return (
    <div style={{ padding: "10px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, minHeight: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 5, opacity: disabled ? 0.5 : 1 }}>
          <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)" }}>{t("Start from an existing adapter")}</div>
          <HelpMark
            tooltip={t("What does this do?")}
            heading={t("Start from an existing adapter")}
            text={t("A fresh adapter starts from noise and has to learn your concept from nothing. Starting from an existing one keeps everything it already learned and refines it — the usual reasons are adding new images to a concept you trained before, or nudging one that came out almost right.\n\nWeight sets trained on the same base model are offered — including ones trained on another model built on it — and the new job has to match the one it continues: the same adapter type, the same rank, and the same layer targeting. The trainer stops with a message naming what it found otherwise. Picking a job's finished result continues where it ended; picking an intermediate checkpoint rewinds to that point and continues from there.")}
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 7, position: "relative", opacity: disabled ? 0.5 : 1 }}>
          <input
            value={value}
            disabled={disabled}
            placeholder={t("train from scratch")}
            onChange={(e) => onChange(e.target.value)}
            style={{ ...inputStyle, width: 300 }}
          />
          <button ref={menuAnchor3}
            disabled={disabled || sources.length === 0}
            title={sources.length ? t("Pick a finished adapter") : t("No finished adapter for this base model yet")}
            onClick={() => setMenu((v) => !v)}
            style={{
              ...inputStyle, width: 34, padding: 0,
              cursor: sources.length && !disabled ? "pointer" : "default",
              display: "flex", alignItems: "center", justifyContent: "center",
              background: menu ? "var(--accent-dim)" : "var(--bg)",
              // Greyed out with nothing to offer: the button was already inert
              // there, it just didn't say so.
              color: menu ? "var(--accent)"
                : sources.length ? "var(--muted)" : "var(--muted-2)",
              opacity: sources.length ? 1 : 0.45,
            }}
          >
            <Icon name="playlist_add" size={17} />
          </button>
          {menu && (
              <AnchoredDropdown rect={menuRect3} minWidth={280}>
                {groups.map(([mk, entries]) => (
                  <div key={mk}>
                    {/* Only where there is something to tell apart: one
                        model's adapters under a heading naming that model
                        is a heading saying what the row above it says. */}
                    {groups.length > 1 && (
                      <SectionHeading sm style={{ padding: "6px 9px 3px" }}>
                        {models.find((m) => m.key === mk)?.label || mk}
                      </SectionHeading>
                    )}
                {entries.map((l) => (
                  <div
                    key={`${l.job_uid}-${l.step ?? "final"}`}
                    className="hoverable"
                    onClick={() => { setMenu(false); onChange(l.path); }}
                    style={{
                      display: "flex", alignItems: "center", gap: 8, padding: "6px 9px",
                      borderRadius: "var(--r-3)", cursor: "pointer", fontSize: "var(--fs-3)", color: "var(--text-2)",
                    }}
                  >
                    {/* Filled circle = where the job finished, hollow one =
                        an intermediate checkpoint along the way. */}
                    <span title={l.step == null ? t("Finished result") : t("Intermediate checkpoint")}
                          style={{ display: "flex", flex: "0 0 auto" }}>
                      <Icon name={l.step == null ? "check_circle" : "radio_button_unchecked"}
                            size={14} color="var(--muted)" />
                    </span>
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {l.name}
                    </span>
                    <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)", fontFamily: "var(--mono)" }}>
                      {stepText(l)}
                    </span>
                  </div>
                ))}
                  </div>
                ))}
              </AnchoredDropdown>
            
)}
        </div>
      </div>
      <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 4, maxWidth: 520 }}>
        {label
          ? `${t("Continues")} ${label}`
          : t("Optional: continue training an existing adapter instead of starting from scratch.")}
      </div>
    </div>
  );
}
