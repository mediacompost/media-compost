// The Evaluate tab: generate images with a base model + stacked LoRAs (from
// completed training jobs) at user-defined weights. Size and seed are
// automatic unless overridden. Past generations stack up as cards on the
// right, newest first.
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { storage } from "../shared/storage";
import { SectionHeading } from "../shared/SectionHeading";
import { IconButton } from "../shared/IconButton";
import { Button } from "../shared/Button";
import { useEscapeClears } from "../shared/escapeClears";
import { pickNext, type PickMods } from "../shared/pickList";
import { Select } from "../shared/Select";
import { useMenuDismiss } from "../shared/useMenuDismiss";
import { AnchoredDropdown, useAnchorRect } from "../shared/AnchoredDropdown";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, EvalRun, EvalRunBody, TrainModelSpec } from "./api";
import { Icon } from "../shared/Icon";
import { useT, useTn } from "./i18n";
import { GpuStatsBar } from "./GpuStatsBar";
import { TrainSetupBanner } from "./TrainSetupBanner";
import {
  inputStyle, NumRow, ProductRow, RowShell, Section, SelectRow, SizeRow,
  ToggleRow,
} from "./FormRows";
import { Lightbox } from "./Lightbox";
import { PromptArea } from "./PromptArea";

import { architectureLabel, errText, fitsModel, groupBy, groupByArchitecture, releaseLabel } from "./util";
import { stepTile } from "./evalGrid";
import type { GridSection, StepDir } from "./evalGrid";
import { useDateFormatters } from "../shared/time";
import { SidebarSplit } from "../shared/SidebarSplit";
import { TokenWarning } from "../shared/HfWarnings";
import { isTypingTarget } from "../shared/typingTarget";
import { confirm } from "../shared/ConfirmModal";
import { SELECTION_BAR_GAP, SELECTION_BAR_H, SelectionBar }
  from "../shared/SelectionBar";

/** Which full finetune the run generates with — a job and one of its saved
 *  weight sets. Null is the base model's own weights. */
interface FinetunePick {
  job_uid: string;
  step: number | null;
}

/** A pick as ONE `<option>` value, since a select carries one string: the
 *  job and the step it names. "" is the base model. */
const finetuneKey = (f: FinetunePick) =>
  `${f.job_uid}:${f.step === null ? "final" : f.step}`;
const finetunePick = (key: string): FinetunePick | null => {
  const cut = key.lastIndexOf(":");
  if (cut < 0) return null;
  const step = key.slice(cut + 1);
  return { job_uid: key.slice(0, cut),
           step: step === "final" ? null : Number(step) };
};

interface LoraRow {
  job_uid: string;
  user_key?: string;   // a LoRA added by hand, in place of a job
  step: number | null; // null = the job's final output
  weight: number;
}

/** A model's own name, or its key where the model is gone (a job outlives
 *  the entry it was trained on). */
function modelLabel(models: TrainModelSpec[], key: string): string {
  return models.find((m) => m.key === key)?.label || key;
}

/** One key per adapter SOURCE — a training job, or a hand-added LoRA. The
 *  select in a row swaps between them by this key. */
const sourceKey = (lo: { job_uid: string; user_key?: string }) =>
  lo.user_key ? `user:${lo.user_key}` : lo.job_uid;
const sourceOf = (key: string) =>
  key.startsWith("user:") ? { job_uid: "", user_key: key.slice(5) }
                          : { job_uid: key, user_key: undefined };
const sameSource = (a: { job_uid: string; user_key?: string },
                    b: { job_uid: string; user_key?: string }) =>
  sourceKey(a) === sourceKey(b);

/** Label for one weight-set entry: "Final · step 300" or "Step 150". */
function stepLabel(t: (s: string) => string, step: number | null,
                   finalStep: number): string {
  if (step === null) {
    return finalStep > 0
      ? `${t("Final")} · ${t("step")} ${finalStep}` : t("Final");
  }
  return `${t("Step")} ${step}`;
}

function LorasEditor({ model, models, rows, onChange }: {
  model: string;
  models: TrainModelSpec[];
  rows: LoraRow[];
  onChange: (rows: LoraRow[]) => void;
}) {
  const t = useT();
  const tn = useTn();
  const { data } = useQuery({ queryKey: ["eval-loras"], queryFn: api.evalLoras });
  // An adapter fits the model it was trained on AND every other model built
  // on the same one — a custom SDXL takes plain SDXL's adapters, and its own
  // are as good on plain SDXL. Matching the key alone left an adapter
  // trained on a custom model usable with that one entry and nothing else.
  const available = (data?.loras ?? [])
    .filter((lo) => fitsModel(models, lo.model, model));
  // Grouped per training job: one card per stacked LoRA, its checkpoints in
  // the card's own dropdown.
  const jobs = useMemo(() => {
    const m = new Map<string, { name: string; model: string;
                                entries: typeof available }>();
    for (const lo of available) {
      const g = m.get(sourceKey(lo))
        ?? { name: lo.name, model: lo.model, entries: [] };
      g.entries.push(lo);
      m.set(sourceKey(lo), g);
    }
    return m;
  }, [available]);
  // …and, inside that list, by the MODEL each was trained on: the whole
  // point of the wider rule is that this list now holds adapters from
  // several models, and a flat list of names says nothing about which.
  const byModel = useMemo(
    () => groupBy([...jobs.entries()], ([, g]) => g.model),
    [jobs]);

  if (available.length === 0) {
    return (
      <div style={{ padding: "12px 16px", fontSize: "var(--fs-2)", color: "var(--muted-2)", lineHeight: 1.55 }}>
        {(data?.loras ?? []).length > 0
          ? t("No adapters for this base model yet — an adapter fits the model it was trained on and any other built on the same one.")
          : t("No trained adapters yet — finish a training job first. Generating with the plain base model works regardless.")}
      </div>
    );
  }

  const update = (i: number, patch: Partial<LoraRow>) => {
    const next = rows.slice();
    next[i] = { ...next[i], ...patch };
    onChange(next);
  };

  return (
    <div style={{ padding: "10px 12px" }}>
      {rows.map((row, i) => {
        const job = jobs.get(sourceKey(row));
        return (
          <div key={i} style={{
            background: "var(--bg)", border: "1px solid var(--border)",
            borderRadius: "var(--r-6)", padding: "9px 11px", marginBottom: 8,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="layers" size={15} color="var(--accent)" />
              {/* IT LOOKS LIKE A DROPDOWN NOW. The title was a bare
                  `appearance: none` select — the LoRA's name in plain bold
                  text, with nothing saying it could be clicked at all, so the
                  one control that swaps which LoRA this row applies was
                  invisible unless you happened to click the name. The chevron
                  after it is what every other picker here wears; the select
                  stays borderless so the name still reads as the row's title
                  rather than as a form field. */}
              {/* No `hoverable`: this is the row's TITLE, and a background
                  that lit up under the pointer made the heading read as a
                  menu item. The chevron already says it can be clicked. */}
              <span style={{ flex: 1, minWidth: 0, display: "flex",
                             alignItems: "center", gap: 3, cursor: "pointer" }}
                    title={t("Which adapter this row applies")}>
                <Select bare
                  value={sourceKey(row)}
                  onChange={(v) => {
                    const g = jobs.get(v);
                    update(i, {
                      ...sourceOf(v),
                      step: g?.entries[0]?.step ?? null,
                    });
                  }}
                  style={{
                    flex: "0 1 auto", minWidth: 0, color: "var(--text)",
                    fontSize: "var(--fs-3)", fontWeight: 600, textOverflow: "ellipsis",
                  }}
                >
                  {byModel.length === 1
                    ? byModel[0][1].map(([uid, g]) => (
                        <option key={uid} value={uid}>{g.name}</option>))
                    : byModel.map(([mk, entries]) => (
                        <optgroup key={mk} label={modelLabel(models, mk)}>
                          {entries.map(([uid, g]) => (
                            <option key={uid} value={uid}>{g.name}</option>
                          ))}
                        </optgroup>
                      ))}
                </Select>
                <Icon name="expand_more" size={15} color="var(--muted-2)" />
              </span>
              <IconButton icon="close" size={24} glyph={14} tone="muted"
                title={t("Remove")}
                onClick={() => onChange(rows.filter((_, k) => k !== i))} style={{ flex: "0 0 auto" }} />
            </div>
            <div style={{
              display: "flex", alignItems: "center", gap: 10, marginTop: 8,
            }}>
              <select
                value={row.step === null ? "final" : String(row.step)}
                title={t("Which saved weights to apply — the finished result or an intermediate checkpoint.")}
                onChange={(e) => update(i, {
                  step: e.target.value === "final" ? null : Number(e.target.value),
                })}
                style={{ ...inputStyle, height: 26, fontSize: "var(--fs-2)", flex: "0 0 auto", cursor: "pointer" }}
              >
                {(job?.entries ?? []).map((en) => (
                  <option key={en.step === null ? "final" : en.step}
                    value={en.step === null ? "final" : String(en.step)}>
                    {stepLabel(t, en.step, en.final_step)}
                  </option>
                ))}
              </select>
              {/* NAMED. A slider and a number with nothing saying what they
                  are is a control you have to hover to understand — and the
                  tooltip that explained it only appeared once you had already
                  reached for it. */}
              <span style={{ flex: "0 0 auto", fontSize: "var(--fs-2)",
                             color: "var(--muted-2)" }}>
                {t("Strength")}
              </span>
              <input
                type="range"
                min={0} max={2} step={0.05}
                value={row.weight}
                title={t("Adapter strength: 1 = as trained, below weakens, above strengthens (can distort past ~1.5).")}
                onChange={(e) => update(i, { weight: Number(e.target.value) })}
                style={{ flex: 1, minWidth: 0, accentColor: "var(--accent)" }}
              />
              <input
                value={String(row.weight)}
                inputMode="decimal"
                onChange={(e) => {
                  const v = Number(e.target.value.replace(",", "."));
                  if (isFinite(v) && v >= 0) update(i, { weight: v });
                }}
                style={{ ...inputStyle, width: 46, height: 26, fontSize: "var(--fs-2)", textAlign: "right" }}
              />
            </div>
          </div>
        );
      })}
      <button
        onClick={() => {
          const first = [...jobs.entries()][0];
          if (!first) return;
          onChange([...rows, {
            ...sourceOf(first[0]),
            step: first[1].entries[0]?.step ?? null,
            weight: 1,
          }]);
        }}
        style={{
          width: "100%", display: "flex", alignItems: "center",
          justifyContent: "center", gap: 6, height: 30, borderRadius: "var(--r-5)",
          border: "1px dashed var(--border-strong)", background: "transparent",
          color: "var(--text-2)", fontSize: "var(--fs-2)", cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        <Icon name="add" size={15} />
        {t("Add adapter")}
      </button>
    </div>
  );
}

// A chip's click applies exactly its own value back into the form on the left.
// The Evaluate panel's last state, kept in the browser. Not server state: it
// is a scratchpad, personal and per-device, and it should survive a reload the
// same way it survives a tab switch.
const PANEL_KEY = "mc.evalPanel";
/** Where the form column's width is remembered (`SidebarSplit`). */
const SIDEBAR_KEY = "mc.eval.sidebarW";

interface EvalPanel {
  model?: string; loras?: LoraRow[]; finetune?: FinetunePick | null;
  prompt?: string; negative?: string;
  width?: number; height?: number; randomSeed?: boolean; seed?: number;
  steps?: number; cfg?: number; count?: number; batch?: number;
  batches?: number;
}

function loadEvalPanel(): EvalPanel {
  try {
    const v = JSON.parse(storage.get(PANEL_KEY) || "{}");
    return v && typeof v === "object" ? v : {};
  } catch { return {}; }
}

function storeEvalPanel(p: EvalPanel) {
  try { storage.set(PANEL_KEY, JSON.stringify(p)); } catch { /* ignore */ }
}

/** "12s" / "1:20" / "1:02:30" — a wall-clock duration at a glance. */
function fmtDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const s = total % 60, m = Math.floor(total / 60) % 60, h = Math.floor(total / 3600);
  const pad = (v: number) => String(v).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export interface ChipApply {
  prompt?: string;
  negative?: string;
  model?: string;
  /** The full finetune to generate with, or null for the base model's own
   *  weights. Applied AFTER `model`, since switching models clears it. */
  finetune?: FinetunePick | null;
  lora?: { model: string; row: LoraRow };
  /** The WHOLE adapter stack, replacing the form's — what "use all
   *  settings" sends beside the model, where a single chip merges one row. */
  loras?: LoraRow[];
  size?: [number, number];
  seed?: number;
  steps?: number;
  cfg?: number;
}

/** The generator's `elapsed` plus the time since that value arrived, ticking
 *  once a second.
 *
 *  The stamp moves once per denoising step, which for a slow model is a gap
 *  of many seconds — long enough that the card looked frozen mid-generation.
 *  A finished run keeps the generator's own final figure: that one is
 *  measured, this is only the gap between measurements. */
function useLiveElapsed(elapsed: number, running: boolean): number {
  const stampedAt = React.useRef(Date.now());
  const last = React.useRef(elapsed);
  if (elapsed !== last.current) {
    last.current = elapsed;
    stampedAt.current = Date.now();
  }
  const [, setTick] = useState(0);
  React.useEffect(() => {
    if (!running) return;
    const h = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(h);
  }, [running]);
  if (!running) return elapsed;
  return elapsed + (Date.now() - stampedAt.current) / 1000;
}

/** ONE RUN'S SETTINGS AND STATE — the card that opens under the grid row a
 *  result was clicked in. It used to carry the run's images too, one card per
 *  generation; the pictures are what this tab is looked at for, and stacking
 *  them in cards meant each session read as a column of forms with thumbnails
 *  inside rather than as a contact sheet. */
function RunDetails({ run, models, onApply, trainingBusy, onClose,
                      chrome = true, imageIndex }: {
  /** A training run holds the same GPU, so name that as the reason rather
   *  than leaving a queued generation looking stuck for no stated cause. */
  trainingBusy?: boolean;
  run: EvalRun;
  models: TrainModelSpec[];
  onApply: (patch: ChipApply) => void;
  onClose: () => void;
  /** The card's own ✕ and Remove. Off under the preview, which has a ✕ of
   *  its own and whose selection bar is where removing lives. */
  chrome?: boolean;
  /** WHICH picture of the run the card is under. The generator seeds image
   *  i with `seed + i` (so a picture comes out the same however it was
   *  batched), and the seed chip says — and applies — THAT seed; without an
   *  index it is the run's base seed, the first picture's. */
  imageIndex?: number;
}) {
  const t = useT();
  const { formatUnix } = useDateFormatters();
  const qc = useQueryClient();
  const shownElapsed = useLiveElapsed(run.elapsed, run.status === "running");
  const refresh = () => qc.invalidateQueries({ queryKey: ["eval-runs"] });
  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: refresh,
    onError: refresh,
  });
  const model = models.find((m) => m.key === run.model);
  const seed = run.seed + (imageIndex ?? 0);
  const loraRows: LoraRow[] = run.loras.map((lo) => ({
    job_uid: lo.job_uid, user_key: lo.user_key || undefined,
    step: lo.step, weight: lo.weight,
  }));
  // EVERYTHING that made this picture, into the form at once — the chips
  // apply one value each, and re-creating a picture to vary one thing
  // meant clicking seven of them.
  const everything: ChipApply = {
    prompt: run.prompt, negative: run.negative, model: run.model,
    finetune: run.finetune?.job_uid
      ? { job_uid: run.finetune.job_uid, step: run.finetune.step ?? null }
      : null,
    loras: loraRows, size: [run.width, run.height], seed,
    steps: run.steps, cfg: run.cfg,
  };
  const chips: { label: string; apply: ChipApply }[] = [
    { label: model?.label ?? run.model.toUpperCase(),
      apply: { model: run.model } },
    // The finetune stands where the base model's weights would — so it reads
    // right after the model and before the adapters stacked on it. It sets
    // the model too: a finetune only means anything on the one it is of.
    ...(run.finetune?.job_uid ? [{
      label: `${run.finetune.name || run.finetune.job_uid}${
        run.finetune.step != null ? ` @${run.finetune.step}` : ""}`,
      apply: { model: run.model, finetune: {
        job_uid: run.finetune.job_uid, step: run.finetune.step ?? null,
      } } as ChipApply,
    }] : []),
    ...run.loras.map((lo) => ({
      label: `${lo.name || lo.job_uid || lo.user_key}${lo.step != null ? ` @${lo.step}` : ""} ×${lo.weight}`,
      apply: { lora: { model: run.model, row: {
        job_uid: lo.job_uid, user_key: lo.user_key || undefined,
        step: lo.step, weight: lo.weight,
      } } },
    })),
    { label: `${run.width}×${run.height}`,
      apply: { size: [run.width, run.height] as [number, number] } },
    { label: `${t("seed")} ${seed}`, apply: { seed } },
    { label: `${run.steps} ${t("steps")}`, apply: { steps: run.steps } },
    { label: `CFG ${run.cfg}`, apply: { cfg: run.cfg } },
  ];
  return (
    <div data-keep-selection style={{
      background: "var(--panel)", border: "1px solid var(--border)",
      borderRadius: "var(--r-7)", padding: 14, marginBottom: 12,
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* The prompt is the most re-used part of a past run, so it is a
              button like the chips below it rather than dead text. */}
          <div
            onClick={() => onApply({ prompt: run.prompt, negative: run.negative })}
            title={t("Click to use this prompt for the next generation")}
            style={{
              fontSize: "var(--fs-3)", fontWeight: 600, lineHeight: 1.45,
              cursor: "pointer", borderRadius: "var(--r-2)", margin: "-2px -4px",
              padding: "2px 4px",
            }}
            className="hoverable"
          >
            {run.prompt || <span style={{ color: "var(--muted-2)", fontWeight: 400 }}>{t("(no prompt)")}</span>}
          </div>
          {run.negative && (
            <div
              onClick={() => onApply({ negative: run.negative })}
              title={t("Click to use this negative prompt for the next generation")}
              className="hoverable"
              style={{
                fontSize: "var(--fs-2)", color: "var(--muted)", marginTop: 2,
                cursor: "pointer", borderRadius: "var(--r-2)", margin: "2px -4px 0",
                padding: "1px 4px",
              }}
            >
              − {run.negative}
            </div>
          )}
          <div style={{
            display: "flex", flexWrap: "wrap", gap: 5, marginTop: 8,
          }}>
            {chips.map((c, i) => (
              <button
                key={i}
                onClick={() => onApply(c.apply)}
                title={t("Click to use this value for the next generation")}
                className="hoverable"
                style={{
                  padding: "2px 8px", borderRadius: "var(--r-3)", fontSize: "var(--fs-1)",
                  background: "var(--panel-3)", color: "var(--text-2)",
                  border: "none", cursor: "pointer", fontFamily: "inherit",
                }}
              >
                {c.label}
              </button>
            ))}
            <button
              onClick={() => onApply(everything)}
              title={t("Put every setting that made this picture into the form")}
              className="hoverable"
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                padding: "2px 8px", borderRadius: "var(--r-3)", fontSize: "var(--fs-1)",
                background: "transparent", color: "var(--accent)",
                border: "1px solid var(--accent-dim)", cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              <Icon name="input" size={12} />
              {t("Use all settings")}
            </button>
          </div>
        </div>
        <div style={{
          fontSize: "var(--fs-1)", color: "var(--muted)", flex: "0 0 auto",
          textAlign: "right",
        }}>
          {/* WHICH picture of the batch this is, over how many were asked
              for — the card is about one picture, and the run made several. */}
          {imageIndex != null && (
            <div style={{ fontFamily: "var(--mono)", marginBottom: 3,
                          color: "var(--text-2)" }}
              title={t("Image {i} of {n}", { i: String(imageIndex + 1),
                                             n: String(run.count) })}>
              {imageIndex + 1} / {run.count}
            </div>
          )}
          {formatUnix(run.created_at)}
          {run.username ? ` · ${run.username}` : ""}
          {/* What the wait actually cost, so the batch-size and step settings
              above can be judged against something. Includes loading the
              model — that is part of what you waited for. */}
          {shownElapsed > 0 && (
            <div style={{
              marginTop: 3, display: "flex", alignItems: "center", gap: 3,
              justifyContent: "flex-end", fontFamily: "var(--mono)",
            }} title={run.status === "running"
              ? t("Time so far, including loading the model")
              : t("Total time, including loading the model")}>
              <Icon name="timer" size={12} />
              {fmtDuration(shownElapsed)}
            </div>
          )}
        </div>
        {run.status === "running" || run.status === "queued" ? (
          <IconButton icon="stop" size={28} glyph={16} color="var(--red-text)"
            onClick={() => act.mutate(() => api.evalCancel(run.uid))}
            title={run.status === "queued" ? t("Remove from the queue") : t("Cancel")} style={{ flex: "0 0 auto" }} />
        ) : chrome && (
          <IconButton icon="delete" size={28} glyph={16} tone="muted"
            onClick={async () => {
              if (await confirm({ title: t("Remove this generation and its images?"),
                                  answer: { label: t("Remove"), danger: true } }))
                act.mutate(() => api.evalDelete(run.uid));
            }}
            title={t("Remove")} style={{ flex: "0 0 auto" }} />
        )}
        {chrome && (
          <IconButton icon="close" size={28} glyph={16} tone="muted"
            onClick={onClose}
            title={t("Close")} style={{ flex: "0 0 auto" }} />
        )}
      </div>

      {run.status === "canceled" && (
        // Said plainly: a cancelled run keeps whatever images it managed, so
        // without this it reads as one that simply produced fewer than asked.
        <div style={{
          marginTop: 10, display: "flex", alignItems: "center", gap: 6,
          fontSize: "var(--fs-2)", color: "var(--muted)",
        }}>
          <Icon name="cancel" size={15} />
          {run.images.length > 0
            ? t("Canceled — {n} of {total} images were generated",
                { n: run.images.length, total: run.count })
            : t("Canceled before any image was generated")}
        </div>
      )}
      {run.status === "failed" && (
        // Selectable: the app suppresses text selection globally (so
        // shift-clicking rows doesn't smear highlights), but a stack trace is
        // there precisely to be copied somewhere else.
        <div
          title={t("Select to copy")}
          style={{
            marginTop: 10, fontSize: "var(--fs-2)", color: "var(--red-text)",
            fontFamily: "var(--mono)", whiteSpace: "pre-wrap",
            userSelect: "text", WebkitUserSelect: "text", cursor: "text",
          }}
        >
          {run.error || t("generation failed")}
        </div>
      )}
      {run.status === "queued" && (
        <div style={{
          marginTop: 10, display: "flex", alignItems: "center", gap: 6,
          fontSize: "var(--fs-2)", color: "var(--muted)",
        }}>
          <Icon name="schedule" size={15} />
          {trainingBusy
            ? t("Waiting for the training run — they share the GPU.")
            : t("Waiting for the GPU…")}
        </div>
      )}
      {run.status === "running" && (
        <div style={{
          marginTop: 10, display: "flex", alignItems: "center", gap: 8,
          fontSize: "var(--fs-2)", color: "var(--text-2)",
        }}>
          <Icon name="progress_activity" size={15} color="var(--accent)" spin />
          <span>
            {t(run.phase.replace(/_/g, " ") || "starting")}
            {/* "generating" alone says nothing for the minutes a batch can
                take; the step count is the only thing that moves. */}
            {run.phase === "generating" && run.cur_step
              ? ` · ${t("step")} ${run.cur_step} / ${run.steps}`
              : ""}
            {run.images.length > 0 && run.count > run.images.length
              ? ` · ${t("{done} of {total} images",
                        { done: run.images.length, total: run.count })}`
              : ""}
          </span>
        </div>
      )}
    </div>
  );
}

/** ONE MENU ROW WITH A NOTE PER ENTRY. A menu rather than a `<select>`,
 *  because an entry can carry a line about what it is for — "1024 px, two
 *  text encoders…" — and a native option list has nowhere to put it, so it
 *  used to sit under the row describing only whichever model happened to
 *  be selected. Groups are headed only where there is more than one. */
function PickMenuRow({ label, hint, value, valueLabel, groups, onPick, last }: {
  label: string;
  hint?: string;
  value: string;
  valueLabel: string;
  groups: { title?: string; items: { id: string; label: string; note?: string }[] }[];
  onPick: (id: string) => void;
  last?: boolean;
}) {
  const [menu, setMenu] = useState(false);
  const menuAnchor = useRef<HTMLButtonElement>(null);
  const menuRect = useAnchorRect(menuAnchor, menu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(menu, () => setMenu(false), { within: [menuAnchor] });
  const filled = groups.filter((g) => g.items.length > 0);
  const headed = filled.length > 1;
  return (
    <RowShell label={label} hint={hint} last={last}>
      <button ref={menuAnchor}
        onClick={() => setMenu((v) => !v)}
        style={{
          ...inputStyle, width: 200, display: "flex", alignItems: "center",
          gap: 6, cursor: "pointer", textAlign: "left",
        }}
      >
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {valueLabel}
        </span>
        <Icon name="expand_more" size={16} color="var(--muted-2)" />
      </button>
      {menu && (
          <AnchoredDropdown rect={menuRect} minWidth={320}>
            {filled.map((g, gi) => (
              <div key={g.title ?? gi}>
                {headed && g.title && (
                  <SectionHeading sm style={{ padding: "8px 9px 3px" }}>{g.title}</SectionHeading>
                )}
                {g.items.map((m) => (
                  <button
                    key={m.id}
                    className="hoverable"
                    onClick={() => { setMenu(false); onPick(m.id); }}
                    style={{
                      display: "block", width: "100%", textAlign: "left",
                      background: m.id === value ? "var(--accent-dim)" : "transparent",
                      border: "none", borderRadius: "var(--r-3)", padding: "7px 9px",
                      cursor: "pointer", fontFamily: "inherit",
                    }}
                  >
                    <div style={{
                      fontSize: "var(--fs-3)", fontWeight: 600,
                      color: m.id === value ? "var(--accent)" : "var(--text-2)",
                    }}>
                      {m.label}
                    </div>
                    {m.note && (
                      <div style={{
                        fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 2,
                        lineHeight: 1.45,
                      }}>
                        {m.note}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            ))}
          </AnchoredDropdown>
      )}
    </RowShell>
  );
}

/** The architecture of a model — the Models page's and the job editor's own
 *  grouping (`groupByArchitecture`), spelled once for the two rows. */
const archOf = (m: TrainModelSpec) => m.engine || m.base || m.key;

/** THE MODEL IN TWO ROWS (owner 2026-09). Row one is the ARCHITECTURE — SDXL,
 *  Chroma, FLUX.2 Klein — the grouping the job editor and the Models page
 *  already use. Row two is the WEIGHTS that stand in for its backbone: the
 *  built-in releases, your own models based on one of them, and full
 *  finetunes, each under its heading. One flat list of every entry plus a
 *  finetune row that hid itself when nothing fitted was two rows saying one
 *  thing in two places; and a finetune is not an adapter — it IS the
 *  network with its own numbers — so it belongs where the model is picked.
 *
 *  What decides which adapters fit is the row-two pick's FAMILY
 *  (`adapterFamily`): Klein 4B and 9B share an architecture and are two
 *  different transformers, which is why the variants live in row two and
 *  not in row one. On the wire nothing moves: a run still carries a model
 *  key and an optional finetune, and row two maps onto those two fields. */
function ModelRows({ models, model, finetune, onModel, onFinetune }: {
  models: TrainModelSpec[];
  model: string;
  finetune: FinetunePick | null;
  /** The base model — `switchModel`, which also clears the adapters. */
  onModel: (key: string) => void;
  onFinetune: (v: FinetunePick | null) => void;
}) {
  const t = useT();
  const { data } = useQuery({
    queryKey: ["eval-finetunes"], queryFn: api.evalFinetunes,
  });
  const groups = useMemo(() => groupByArchitecture(models), [models]);
  const spec = models.find((m) => m.key === model);
  const arch = spec ? archOf(spec) : groups[0]?.[0] ?? "";
  const group = groups.find(([e]) => e === arch)?.[1] ?? [];
  const builtins = group.filter((m) => !m.user);
  const custom = group.filter((m) => m.user);
  const inArch = new Set(group.map((m) => m.key));
  const finetunes = (data?.finetunes ?? []).filter((f) => inArch.has(f.model));
  const releaseOf = (m: TrainModelSpec) =>
    builtins.length > 1 ? releaseLabel(m, arch, group) : m.label;
  const picked = finetunes.find((f) => finetune && finetuneKey(f) === finetuneKey(finetune));
  const valueLabel = picked
    ? `${picked.name} · ${stepLabel(t, picked.step, picked.final_step)}`
    : spec ? releaseOf(spec) : model;
  return (<>
    <PickMenuRow label={t("Model")}
      value={arch}
      valueLabel={groups.find(([e]) => e === arch)
        ? architectureLabel(arch, group) : arch}
      groups={[{ items: groups.map(([engine, g]) => ({
        id: engine, label: architectureLabel(engine, g),
        // The family's own note where its releases share one; a family of
        // several says nothing here and lets the release row say it.
        note: g.filter((m) => !m.user).length === 1 && g[0].note ? t(g[0].note) : undefined,
      })) }]}
      onPick={(engine) => {
        if (engine === arch) return;
        const g = groups.find(([e]) => e === engine)?.[1] ?? [];
        const first = g.find((m) => !m.user) ?? g[0];
        if (first) onModel(first.key);
      }} />
    <PickMenuRow label={t("Weights")}
      hint={finetunes.length || custom.length
        ? t("The built-in release, one of your own models, or a full finetune's weights in place of the base model's. Adapters stack on top of whatever is picked here.")
        : undefined}
      value={finetune ? finetuneKey(finetune) : model}
      valueLabel={valueLabel}
      groups={[
        { title: t("Built-in"),
          items: builtins.map((m) => ({ id: m.key, label: releaseOf(m),
                                        note: m.note ? t(m.note) : undefined })) },
        { title: t("Your models"),
          items: custom.map((m) => ({ id: m.key, label: m.label,
                                      note: m.note ? t(m.note)
                                        : m.base ? t("Based on {model}", { model: modelLabel(models, m.base) })
                                        : undefined })) },
        { title: t("Finetunes"),
          items: finetunes.map((f) => ({
            id: finetuneKey(f),
            label: `${f.name} · ${stepLabel(t, f.step, f.final_step)}`,
            note: t("A full finetune of {model}", { model: modelLabel(models, f.model) }),
          })) },
      ]}
      onPick={(id) => {
        const f = finetunes.find((x) => finetuneKey(x) === id);
        if (f) {
          // The finetune's own base, so the adapters are asked about the
          // right family; the same base keeps the adapters already picked.
          if (f.model !== model) onModel(f.model);
          onFinetune({ job_uid: f.job_uid, step: f.step });
        } else {
          if (id !== model) onModel(id);
          onFinetune(null);
        }
      }} />
  </>);
}


/** Runs closer together than this belong to the same sitting (30 minutes). */
const SESSION_GAP = 30 * 60;

/** One sitting's results, under a header naming when it started. The header
 *  carries the only bulk action there is: clearing that whole session, which
 *  is how a page full of experiments gets tidied without 20 confirmations. */
/** How many columns the results grid has right now.
 *
 *  Measured, because the detail panel opens after the ROW its picture is in —
 *  which is a fact about the layout, not about the data, and the grid is
 *  `auto-fill` so nothing else knows it. */
function useGridColumns(min: number, gap: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [cols, setCols] = useState(1);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      setCols(Math.max(1, Math.floor((w + gap) / (min + gap))));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [min, gap]);
  return { ref, cols };
}

const TILE_MIN = 180;
//: The LIBRARY's grid gap, and it has to be: the selection ring is drawn 3 px
//: outside a tile and is 2 px wide, so a tile reaches 5 px past its own box on
//: every side. At the 8 px this used to be, two neighbouring rings overlapped
//: — and here they usually ARE neighbours, because the whole run lights up
//: rather than the one picture clicked.
const TILE_GAP = 16;

/** How long the run's card takes to open and close.
 *
 *  Deliberately quicker than the 200 ms every other `0fr -> 1fr` collapse in
 *  this app uses (the properties panel's sections, the group tree's stats, the
 *  GPU bar at the foot of this very tab): those reveal a panel in place, while
 *  this one shoves every row below it down the page, and a long push reads as
 *  the grid lurching rather than as the card arriving.
 *
 *  The panel stays MOUNTED for this long after it is closed (`lingerUid`), or
 *  there would be nothing left on screen to animate — the collapse would be a
 *  disappearance. */

/** How a tile is ringed: the slot whose card is open, one of its BATCH, or
 *  neither. */
type Ring = "picked" | "none";

/** The tile's box, shared by a picture and an empty slot.
 *
 *  The ring is the LIBRARY's: 2 px 3 px OUTSIDE the tile, so there is a gap
 *  between the picture and the selection. It used to recolour the border
 *  itself, which on a picture whose edge happens to be the accent is a
 *  selection you cannot see.
 *
 *  TWO COLOURS, because the ring answers two different questions at once. The
 *  ACCENT is the picture you actually pressed — the one the card below is
 *  about. GREY is the rest of its batch: same generation, not the one you
 *  asked about. One colour for both said "these are all equally what you
 *  picked", which is not true of any of them but one. Grey rather than
 *  yellow: it is the library grid's colour for a selection's secondary
 *  copies — the same "with the picked one, not it" claim — where yellow
 *  reads as a warning or a machine's guess. */
function tileStyle(run: EvalRun, ring: Ring): React.CSSProperties {
  return {
    display: "block", borderRadius: "var(--r-6)", overflow: "hidden",
    border: "1px solid var(--border)",
    outline: ring === "none" ? "none" : "2px solid var(--accent)",
    outlineOffset: 3,
    background: "var(--bg-deep)",
    aspectRatio: `${run.width} / ${run.height}`, lineHeight: 0,
    padding: 0, cursor: "pointer",
  };
}

/** One tile of the results grid: a finished image, or the slot of one that is
 *  still to come (or never came). */
interface Tile {
  run: EvalRun;
  /** The image's file name and its index within the run — absent for a slot
   *  that has no picture. */
  name?: string;
  index: number;
}

/** The grid's tiles for a list of runs, in reading order — one per finished
 *  image, plus the slots of what a running run will still produce, and one
 *  slot for a run that failed or was cancelled with nothing to show (it has
 *  to appear somewhere, and the grid is the only place it does). */
function tilesOf(runs: EvalRun[]): Tile[] {
  return runs.flatMap((run) => {
    const done: Tile[] = run.images.map((name, index) => ({ run, name, index }));
    const missing = run.status === "running" ? Math.max(0, run.count - done.length)
      : done.length === 0 ? 1 : 0;
    return [...done, ...Array.from({ length: missing },
      (_, k) => ({ run, index: done.length + k }))];
  });
}

/** A tile's SELECTION key — the run and the position, so a slot can be
 *  picked as well as a picture (removing a failed run is done through its
 *  slot). */
function tileKey(uid: string, index: number): string {
  return `${uid}:${index}`;
}

/** The library grid's gestures: a plain click replaces the selection (and
 *  puts down the only picked tile), ⌘/Ctrl adds and removes, shift extends
 *  from the last pick over the reading order. */
export type { PickMods } from "../shared/pickList";

/** The four keys that walk the grid — a table, so a key this tab does not
 *  claim falls through to the browser untouched. */
const ARROWS: Record<string, StepDir | undefined> = {
  ArrowLeft: "left", ArrowRight: "right",
  ArrowUp: "up", ArrowDown: "down",
};

/** ONE SESSION AS A CONTACT SHEET. The runs of a session used to be a stack
 *  of cards, each with its own little grid inside it; the pictures are what
 *  this tab is looked at for, so they share one grid, and the settings that
 *  made each of them ride the PREVIEW under the picture — for a slot with no
 *  picture, the preview is the card alone. */
function SessionGroup({ runs, onClear, picked, onPick, onLightbox,
                       onColumns }: {
  runs: EvalRun[];
  onClear: () => void;
  /** How many tiles fit across — MEASURED here, where the grid is, and
   *  reported up because the arrow keys are the view's (the walk crosses
   *  sessions). Every session sits in one scroll column, so they all
   *  measure the same number and the last to report is right. */
  onColumns?: (n: number) => void;
  /** The VIEW's selection (tile keys) — it spans every session, like the
   *  library grid's spans every section. */
  picked: string[];
  onPick: (key: string, mods: PickMods) => void;
  /** The preview is the VIEW's — it walks the selection, which spans every
   *  session — so a tile only says which one it wants opened. */
  onLightbox: (v: { uid: string; i: number }) => void;
}) {
  const t = useT();
  const tn = useTn();
  const { formatUnix } = useDateFormatters();
  const { ref, cols } = useGridColumns(TILE_MIN, TILE_GAP);
  const tiles: Tile[] = tilesOf(runs);
  useEffect(() => { onColumns?.(cols); }, [cols, onColumns]);

  const mods = (e: React.MouseEvent): PickMods =>
    ({ meta: e.metaKey || e.ctrlKey, shift: e.shiftKey });

  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
        padding: "0 2px",
      }}>
        <SectionHeading>
          {formatUnix(runs[runs.length - 1].created_at)}
        </SectionHeading>
        <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-3)" }}>
          {tn({ one: "1 result", other: "{n} results" }, runs.length)}
        </span>
        <div style={{ flex: 1, height: 1, background: "var(--border-soft)" }} />
        <button
          onClick={onClear}
          title={t("Delete every result in this session")}
          className="hoverable"
          style={{
            display: "inline-flex", alignItems: "center", gap: 5, height: 24,
            padding: "0 9px", borderRadius: "var(--r-3)", border: "1px solid var(--border)",
            background: "transparent", color: "var(--muted)", fontSize: "var(--fs-2)",
            cursor: "pointer", fontFamily: "inherit",
          }}
        >
          <Icon name="delete_sweep" size={14} />
          {t("Clear")}
        </button>
      </div>
      <div ref={ref} style={{
        display: "grid", gap: TILE_GAP,
        gridTemplateColumns: `repeat(auto-fill, minmax(${TILE_MIN}px, 1fr))`,
      }}>
        {tiles.map((tile) => {
          const { run } = tile;
          const key = tileKey(run.uid, tile.index);
          // The ACCENT ring is the selection, the library grid's.
          const ring: Ring = picked.includes(key) ? "picked" : "none";
          const open = () => onLightbox({ uid: run.uid, i: tile.index });
          const failed = run.status === "failed";
          return tile.name ? (
            // A DIV, not a button, because it contains one — the info button
            // below is a real button and nesting two is invalid.
            // A CLICK SELECTS; the preview is a double-click or Space over
            // the selection — the library grid's rules, so the two grids
            // read as one app (a click used to open the preview outright).
            <div
              key={`${run.uid}-${tile.name}`}
              data-tilekey={key}
              role="button"
              tabIndex={0}
              onClick={(e) => onPick(key, mods(e))}
              onDoubleClick={open}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                e.preventDefault();
                open();
              }}
              title={run.prompt || t("(no prompt)")}
              style={{ ...tileStyle(run, ring), position: "relative" }}
            >
              <img
                src={api.evalImageUrl(run.uid, tile.name, 320)}
                alt={run.prompt}
                loading="lazy"
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
              {/* No ⓘ here any more: the run's settings ride the PREVIEW
                  now, under the image — the card is about the picture, so
                  it lives where the picture is looked at. */}
            </div>
          ) : (
            // A slot has no picture, so its preview is the settings card
            // alone — the same door as a picture's (double-click, Enter,
            // Space), where an inline card under the row used to open; a
            // click selects it like any tile (removing a failed run is
            // done through its slot).
            <div
              key={`${run.uid}-slot-${tile.index}`}
              data-tilekey={key}
              role="button"
              tabIndex={0}
              onClick={(e) => onPick(key, mods(e))}
              onDoubleClick={open}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                e.preventDefault();
                open();
              }}
              title={failed ? (run.error || t("generation failed"))
                : run.status === "running" ? t("not generated yet")
                : t("no image")}
              style={{
                ...tileStyle(run, ring), position: "relative",
                border: `1px dashed ${failed ? "var(--red)" : "var(--border-strong)"}`,
                background: "var(--panel-2)",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: failed ? "var(--red-text)" : "var(--muted-3)",
              }}
            >
              {run.status === "running"
                ? <Icon name="progress_activity" size={20} spin />
                : <Icon name={failed ? "error" : run.status === "queued"
                    ? "schedule" : "image"} size={20} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function EvaluateView() {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const [lightbox, setLightbox] = useState<{ uid: string; i: number } | null>(null);
  // THE SELECTION, across every session: tile keys, in no particular order
  // (the ORDER below is what shift-ranges and Select all read).
  const [picked, setPicked] = useState<string[]>([]);
  const pickAnchor = useRef<string | null>(null);
  useEscapeClears(true, picked.length > 0, () => { setPicked([]); pickAnchor.current = null; });
  // How many tiles fit across, measured by the session grids themselves.
  const [columns, setColumns] = useState(1);
  const { data: runsData } = useQuery({
    queryKey: ["eval-runs"],
    queryFn: api.evalRuns,
    refetchInterval: (q) =>
      (q.state.data?.runs ?? []).some(
        (r) => r.status === "running" || r.status === "queued")
        ? 1500 : false,
  });
  // While something is queued, the reason it is waiting can change under us
  // (a training run ends and the generation starts), so this poll follows the
  // queue rather than sitting on whatever was true when the tab opened.
  const anyQueued = (runsData?.runs ?? []).some((r) => r.status === "queued");
  const { data: status } = useQuery({
    queryKey: ["train-status"], queryFn: api.trainStatus,
    refetchInterval: anyQueued ? 5000 : false,
  });
  const runs = runsData?.runs ?? [];
  const models = status?.models ?? [];
  // A training run holds the GPU a generation would use, so a queued run can
  // say what it is actually waiting for.
  const trainingBusy = !!status?.running_uid;

  // A "session" is one sitting at the tab: runs arrive newest-first, and a
  // gap longer than SESSION_GAP starts a new group. Wall-clock alone (per
  // day, per hour) would split an evening's work at midnight and lump
  // yesterday morning in with yesterday night.
  const sessions = useMemo(() => {
    const out: EvalRun[][] = [];
    for (const r of runs) {
      const cur = out[out.length - 1];
      const prev = cur && cur[cur.length - 1];
      if (prev && prev.created_at - r.created_at <= SESSION_GAP) cur.push(r);
      else out.push([r]);
    }
    return out;
  }, [runs]);
  // Every tile of the page in reading order — the sessions newest-first,
  // each session's runs newest-first, each run's pictures in order.
  const allTiles = useMemo(() => sessions.flatMap((g) => tilesOf(g)), [sessions]);
  const order = useMemo(
    () => allTiles.map((x) => tileKey(x.run.uid, x.index)), [allTiles]);
  // WHERE EACH SESSION STARTS in that order — one grid per session, each
  // beginning a fresh row, which is what the arrow walk needs and what
  // `cur ± columns` cannot know.
  const sections = useMemo<GridSection[]>(() => {
    let start = 0;
    return sessions.map((g) => {
      const count = tilesOf(g).length;
      const at = start;
      start += count;
      return { start: at, count };
    });
  }, [sessions]);
  // A tile that is gone (its run deleted, or a slot filled by its picture
  // arriving) leaves the selection, or the bar counts things nobody can see.
  useEffect(() => {
    setPicked((cur) => {
      const keep = cur.filter((k) => order.includes(k));
      return keep.length === cur.length ? cur : keep;
    });
  }, [order]);
  // The one click rule (`shared/pickList.ts`): shift REPLACES with the run.
  // The arrow walk's shift-extend rides on it too (`walk` below).
  const pick = (key: string, m: PickMods) => {
    setPicked((cur) => {
      const r = pickNext(cur, key, m, order, pickAnchor.current);
      pickAnchor.current = r.anchor;
      return r.next;
    });
  };
  const clearPicked = () => { setPicked([]); pickAnchor.current = null; };

  // THE PREVIEW OVER THE SELECTION: the last picked picture (the preview
  // then steps through that run with the arrows), else the first pick that
  // has one. Space's and the bar's info button's one definition; answers
  // whether there was anything to open.
  const previewPicked = (): boolean => {
    const keys = pickAnchor.current && picked.includes(pickAnchor.current)
      ? [pickAnchor.current, ...picked] : picked;
    const tile = keys
      .map((k) => allTiles.find((x) => tileKey(x.run.uid, x.index) === k))
      .find((x) => x);
    if (!tile) return false;
    setLightbox({ uid: tile.run.uid, i: tile.index });
    return true;
  };
  const previewable = picked.length > 0;

  // THE ARROW KEYS WALK THE GRID, the library's rules: ←/→ step one tile in
  // reading order, ↑/↓ a row, a plain press replaces the selection and Shift
  // extends from the last pick. The sessions are separate grids, so the walk
  // goes through `stepTile` rather than `cur ± columns` — a session's first
  // index is generally not a multiple of the column count (see evalGrid.ts).
  // With nothing picked the first press lands on the first tile: the mouse is
  // primary here, and a cursor on a tile nobody pointed at would be a
  // suggestion rather than an answer.
  const walk = (dir: StepDir, shift: boolean): boolean => {
    if (!order.length) return false;
    const cur = pickAnchor.current ? order.indexOf(pickAnchor.current) : -1;
    const next = cur < 0 ? 0 : stepTile(sections, columns, cur, dir);
    const key = order[next];
    if (key == null) return false;
    pick(key, { meta: false, shift });
    // The tiles are all rendered (no windowing here), so the DOM is the
    // simplest honest way to keep the cursor on screen.
    document.querySelector(`[data-tilekey="${CSS.escape(key)}"]`)
      ?.scrollIntoView({ block: "nearest" });
    return true;
  };

  // SPACE IS THE PREVIEW, the library grid's key. A field keeps its own
  // Space — the prompt is a textarea on this very page — and an open
  // preview handles the key itself (it closes on it, and it owns the arrows
  // while it is up).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (lightbox) return;
      if (isTypingTarget(e)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.code === "Space") {
        if (previewPicked()) e.preventDefault();
        return;
      }
      const dir = ARROWS[e.key];
      if (dir && walk(dir, e.shiftKey)) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // WHAT THE PREVIEW STEPS THROUGH with ←/→: the SELECTION, in reading
  // order, while more than one tile is picked — that is what opening a
  // preview over several pictures is for — and otherwise the picture's
  // whole RUN (its batch, slots included), which is what a single pick or
  // a double-click means. One list, so the arrows, the counter and the
  // card under the picture cannot disagree about what "next" is.
  const lightList = useMemo<Tile[]>(() => {
    if (!lightbox) return [];
    if (picked.length > 1) {
      const set = new Set(picked);
      const sel = allTiles.filter((x) => set.has(tileKey(x.run.uid, x.index)));
      if (sel.some((x) => x.run.uid === lightbox.uid && x.index === lightbox.i))
        return sel;
    }
    return allTiles.filter((x) => x.run.uid === lightbox.uid);
  }, [lightbox, picked, allTiles]);
  const lightAt = lightbox
    ? lightList.findIndex((x) => x.run.uid === lightbox.uid && x.index === lightbox.i)
    : -1;
  const lightTile = lightAt >= 0 ? lightList[lightAt] : null;

  // What Remove will ACT on: a running or queued generation is not
  // removable (the folder is being written), so its tiles are left out of
  // the count rather than silently skipped. Per run, the pictures picked go
  // one by one — unless they are ALL of the run's pictures (or the run has
  // none, i.e. a failed run's slot), when the run goes whole: an image-less
  // run would otherwise linger as an empty slot.
  const pickedTiles = picked
    .map((k) => allTiles.find((x) => tileKey(x.run.uid, x.index) === k))
    .filter((x): x is Tile => !!x);
  const removableTiles = pickedTiles.filter(
    (x) => x.run.status !== "running" && x.run.status !== "queued");
  const removePicked = async () => {
    if (removableTiles.length === 0) return;
    if (!(await confirm({ title: t("Remove the selected images?"),
                          body: t("They cannot be recovered."),
                          answer: { label: t("Remove"), danger: true } })))
      return;
    const byRun = new Map<string, Tile[]>();
    for (const x of removableTiles) {
      byRun.set(x.run.uid, [...(byRun.get(x.run.uid) ?? []), x]);
    }
    // Sequential, like clearSession: the manager writes under one lock.
    for (const [uid, tiles] of byRun) {
      const run = tiles[0].run;
      const names = tiles.map((x) => x.name).filter((n): n is string => !!n);
      const whole = run.images.length === 0
        || run.images.every((n) => names.includes(n));
      try {
        if (whole) await api.evalDelete(uid);
        else for (const n of names) await api.evalDeleteImage(uid, n);
      } catch { /* already gone */ }
    }
    clearPicked();
    qc.invalidateQueries({ queryKey: ["eval-runs"] });
  };

  const clearSession = async (group: EvalRun[]) => {
    if (!(await confirm({
      title: t("Delete all {n} results from this session?", { n: group.length }),
      body: t("The generated images go with them."),
      answer: { label: t("Delete"), danger: true },
    }))) return;
    // Sequential rather than Promise.all: the manager writes the run folders
    // under one lock, and a burst of parallel deletes only queues there.
    for (const r of group) {
      try { await api.evalDelete(r.uid); } catch { /* already gone */ }
    }
    qc.invalidateQueries({ queryKey: ["eval-runs"] });
  };

  const [model, setModel] = useState(() => loadEvalPanel().model ?? "sdxl");
  const [loras, setLoras] = useState<LoraRow[]>(() => loadEvalPanel().loras ?? []);
  // Which full finetune stands in for the base model's weights, if any.
  const [finetune, setFinetune] = useState<FinetunePick | null>(
    () => loadEvalPanel().finetune ?? null);
  // Generating downloads the base model on first use — so the environment
  // warnings only apply while THIS model still has to be fetched. Once its
  // weights are here, neither offline mode nor a missing token can stop the
  // run, and saying otherwise is noise on the page you generate from.
  const selected = models.find((m) => m.key === model);
  const needsDownload = !!selected && !selected.cached;
  const offlineBlocked = !!status?.env_offline && needsDownload;
  const tokenMissing = !status?.token_available && needsDownload;
  const enableDownloads = async () => {
    await api.clearOffline();
    qc.invalidateQueries({ queryKey: ["train-status"] });
    qc.invalidateQueries({ queryKey: ["model-cache"] });
  };
  // The whole panel is remembered: switching to Library and back (or reloading)
  // used to throw away a prompt that took a minute to write.
  const saved = React.useMemo(loadEvalPanel, []);
  const [prompt, setPrompt] = useState(saved.prompt ?? "");
  const [negative, setNegative] = useState(saved.negative ?? "");
  const [width, setWidth] = useState(saved.width ?? 1024);
  const [height, setHeight] = useState(saved.height ?? 1024);
  const [randomSeed, setRandomSeed] = useState(saved.randomSeed ?? true);
  const [seed, setSeed] = useState(saved.seed ?? 42);
  const [steps, setSteps] = useState(saved.steps ?? 25);
  const [cfg, setCfg] = useState(saved.cfg ?? 6);
  const [batch, setBatch] = useState(saved.batch ?? 1);
  // A generation is now asked for in BATCHES — what the GPU does in one go —
  // times the batch size. Panels saved before that stored a total; derive the
  // batch count from it so a returning user keeps roughly what they had.
  const [batches, setBatches] = useState(
    saved.batches ?? Math.max(1, Math.ceil((saved.count ?? 2) / (saved.batch ?? 1))));
  const [error, setError] = useState("");

  const spec = models.find((m) => m.key === model);
  // Only the click itself blocks; a running generation no longer does, since
  // asking for another now queues it behind the first.
  const [submitting, setSubmitting] = useState(false);
  const busy = submitting;
  const pending = runs.filter((r) => r.status === "queued").length;

  const switchModel = (key: string) => {
    setModel(key);
    setLoras([]);
    // Bound to the model exactly as the adapters are: a finetune of one
    // network is not weights for another.
    setFinetune(null);
    // Start from the model's native size (the fields stay editable).
    const m = models.find((x) => x.key === key);
    if (m) { setWidth(m.default_area); setHeight(m.default_area); }
  };

  // A run-card chip applies exactly its own value into the form.
  const applyChip = (patch: ChipApply) => {
    if (patch.prompt !== undefined) setPrompt(patch.prompt);
    if (patch.negative !== undefined) setNegative(patch.negative);
    if (patch.model !== undefined && patch.model !== model) {
      setModel(patch.model);
      setLoras([]); // LoRAs are model-bound
      setFinetune(null);
    }
    // …and then the run's own, which is why this reads after the model: the
    // line above clears it.
    if (patch.finetune !== undefined) setFinetune(patch.finetune);
    if (patch.loras !== undefined) setLoras(patch.loras);
    if (patch.lora !== undefined) {
      const { model: loraModel, row } = patch.lora;
      if (loraModel !== model) {
        setModel(loraModel);
        setLoras([row]);
      } else {
        setLoras((cur) => {
          const i = cur.findIndex(
            (r) => sameSource(r, row) && r.step === row.step);
          if (i >= 0) {
            const next = cur.slice();
            next[i] = row;
            return next;
          }
          return [...cur, row];
        });
      }
    }
    if (patch.size !== undefined) {
      setWidth(patch.size[0]);
      setHeight(patch.size[1]);
    }
    if (patch.seed !== undefined) {
      setSeed(patch.seed);
      setRandomSeed(false); // otherwise the applied seed wouldn't be used
    }
    if (patch.steps !== undefined) setSteps(patch.steps);
    if (patch.cfg !== undefined) setCfg(patch.cfg);
  };

  React.useEffect(() => {
    storeEvalPanel({ model, loras, finetune, prompt, negative, width, height,
                     randomSeed, seed, steps, cfg, batches, batch });
  }, [model, loras, finetune, prompt, negative, width, height, randomSeed, seed,
      steps, cfg, batches, batch]);

  const generate = async () => {
    setError("");
    setSubmitting(true);
    // Random mode draws the seed NOW, for this click's batch, and shows it in
    // the (greyed) seed field as the last used seed.
    const usedSeed = randomSeed
      ? Math.floor(Math.random() * 2 ** 31) : seed;
    setSeed(usedSeed);
    const body: EvalRunBody = {
      model,
      // Only when one is picked: a run on the base model's own weights sends
      // the body it always sent.
      ...(finetune ? { finetune } : {}),
      loras: loras.map((lo) => ({
        job_uid: lo.job_uid, user_key: lo.user_key || undefined,
        step: lo.step, weight: lo.weight, name: "",
      })),
      prompt, negative,
      width, height,
      seed: usedSeed,
      steps, cfg, count: batches * batch, batch,
    };
    try {
      await api.evalGenerate(body);
      qc.invalidateQueries({ queryKey: ["eval-runs"] });
    } catch (e) {
      setError(errText(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SidebarSplit widthKey={SIDEBAR_KEY} initial={420} t={t}>
      {/* Left: generation form. A column, so Generate stays reachable at the
          bottom however far down the settings you have scrolled — it is the
          one button on this page. */}
      <div style={{
        minHeight: 0, display: "flex", flexDirection: "column",
        borderRight: "1px solid var(--border)",
      }}>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 14 }}>
        {status && !status.env_ready && <TrainSetupBanner />}

        {/* One section: a LoRA only exists in relation to its base model, and
            reading them apart meant looking in two places to know what would
            be generated. */}
        <Section label={t("Model")}>
          {/* The first rows of the Model box, under its title: they are about
              the model picked directly below, and have to be read before
              Generate rather than found by scrolling past it. A model that is
              not downloaded cannot be fetched while the launch environment
              forces Hugging Face offline — say so before the click fails, and
              offer the same one-click fix Settings has. */}
          {offlineBlocked && (
            <div style={{
              padding: "10px 16px",
              background: "var(--yellow-dim)",
              borderBottom: "1px solid var(--border-soft)", display: "flex",
              alignItems: "flex-start", gap: 8,
            }}>
              <Icon name="cloud_off" size={16} color="var(--yellow-text)" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: "var(--fs-2)", color: "var(--text-2)", lineHeight: 1.5 }}>
                  {t("This model isn't downloaded yet, and downloads are switched off")}
                  {" "}({status?.env_offline}).
                </div>
                <button
                  onClick={enableDownloads}
                  style={{
                    marginTop: 6, height: 24, padding: "0 10px", borderRadius: "var(--r-3)",
                    border: "1px solid var(--border-strong)", background: "transparent",
                    color: "var(--text-2)", fontSize: "var(--fs-2)", fontWeight: 600,
                    cursor: "pointer", fontFamily: "inherit",
                  }}
                >
                  {t("Enable downloads")}
                </button>
              </div>
            </div>
          )}
          {/* A missing token only matters while this model still has to be
              fetched — gated exactly like the offline warning above. The
              SHARED warning, so this page says what the others say and can
              take the token right here instead of sending you to Settings. */}
          {tokenMissing && !offlineBlocked && (
            <div style={{
              padding: "10px 12px",
              borderBottom: "1px solid var(--border-soft)",
            }}>
              <TokenWarning onChanged={() => {
                qc.invalidateQueries({ queryKey: ["train-status"] });
                qc.invalidateQueries({ queryKey: ["ml-models"] });
              }} />
            </div>
          )}
          <ModelRows models={models} model={model} finetune={finetune}
            onModel={switchModel} onFinetune={setFinetune} />
          <RowShell label={t("Adapters")} last
            hint={t("Stack trained adapters on the base model, each with its own strength — LoRA or LoKr. An adapter fits the model it was trained on and any other built on the same one.")}>
            <span />
          </RowShell>
          <div style={{ margin: "-10px 0 0" }}>
            <LorasEditor model={model} models={models} rows={loras}
              onChange={setLoras} />
          </div>
        </Section>

        <Section label={t("Prompt")}>
          <PromptArea label={t("Prompt")} value={prompt} rows={3}
            placeholder={t("what to generate — include your trigger word")}
            hint={t("Library tags autocomplete as you type.")}
            onChange={setPrompt} />
          <PromptArea label={t("Negative prompt")} value={negative} rows={2}
            onChange={setNegative} last />
        </Section>

        <Section label={t("Output")}>
          <SizeRow label={t("Size")} width={width} height={height}
            onChange={(w, h) => { setWidth(w); setHeight(h); }} />
          <ToggleRow label={t("Random seed")} checked={randomSeed}
            hint={t("A new seed is drawn each time you click Generate; the field below shows the seed used for the last generation.")}
            onChange={setRandomSeed} />
          <NumRow label={t("Seed")} value={seed} step={1}
            disabled={randomSeed} onChange={setSeed} />
          {/* One row, because the two numbers only mean anything together:
              a batch is what the GPU does in one pass, and the image count is
              the consequence of asking for several. */}
          <ProductRow label={t("Images")}
            a={batches} b={batch} aMax={50} bMax={8}
            aLabel={t("batches")} bLabel={t("per batch")}
            total={tn({ one: "= 1 image", other: "= {n} images" },
                       batches * batch)}
            hint={t("Each batch goes through the model in one pass: a larger batch needs that much more memory and is faster only where there is bandwidth to spare, while more batches simply take longer. Seeds run seed, seed+1, … across the whole set, so an image comes out identical however it was grouped.")}
            onChange={(nb, sz) => { setBatches(nb); setBatch(sz); }} />
          <NumRow label={t("Sampler steps")} value={steps} min={1} max={150}
            step={1} onChange={setSteps} />
          <NumRow label={t("CFG scale")} value={cfg} min={0} max={30} last
            hint={t("How strongly the prompt is enforced. Anything above 1 makes the model run TWICE per sampler step — once with the prompt and once without — so it costs about double the time (measured here on SDXL at 1024², 20 steps: 53 s at 6 against 24 s at 1). At 1 or below that second pass is skipped, but these models are trained to lean on guidance and the picture changes completely without it — so treat this as a quality dial that happens to cost time, not as a speed setting.")}
            onChange={setCfg} />
        </Section>

      </div>
      <div style={{ flex: "0 0 auto", padding: 14, borderTop: "1px solid var(--border-soft)" }}>
        <Button variant="primary" size="md" block
     onClick={generate}
     disabled={busy}>
          {busy ? (
            <Icon name="progress_activity" size={16} spin />
          ) : (
            <Icon name="auto_awesome" size={17} />
          )}
          {busy ? t("Generating…")
                : pending > 0 ? `${t("Generate")} (${pending} ${t("queued")})`
                : t("Generate")}
        </Button>
        {error && (
          <div style={{ marginTop: 8, fontSize: "var(--fs-2)", color: "var(--red-text)" }}>
            {error}
          </div>
        )}
      </div>
        <GpuStatsBar />
      </div>

      {/* Right: generation history, grouped by sitting. A non-scrolling FRAME
          around the scroller, so the selection bar can float at its foot
          over the content — the library sidebar's and the Train sidebar's
          shape, from the same component. */}
      <div style={{ minHeight: 0, position: "relative", display: "flex",
                    flexDirection: "column" }}>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto",
                    padding: "16px 20px" }}
        // A click on the BACKGROUND puts the selection down — the library
        // grid's rule. Background is anything that is not a tile, a
        // control or the inline settings card (whose prompt and chips are
        // clickable divs, so the card marks itself rather than each one).
        onClick={(e) => {
          const el = e.target as HTMLElement;
          if (el.closest("[role=button], button, a, input, textarea, "
                         + "select, [data-keep-selection]")) return;
          clearPicked();
        }}>
        {runs.length === 0 ? (
          <div style={{
            height: "100%", display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", gap: 10,
            color: "var(--muted)",
          }}>
            <Icon name="science" size={42} color="var(--border-strong)" />
            <div style={{ fontSize: "var(--fs-3)" }}>
              {t("Generated images appear here — try out a trained adapter against its base model.")}
            </div>
          </div>
        ) : (
          sessions.map((group) => (
            <SessionGroup key={group[0].uid} runs={group}
              onClear={() => clearSession(group)}
              onColumns={setColumns}
              picked={picked} onPick={pick} onLightbox={setLightbox} />
          ))
        )}
        {/* The bar takes no layout space, so the content reserves its height
            here — the last row has to be scrollable clear of it. */}
        {runs.length > 0 && (
          <div style={{ height: SELECTION_BAR_H + SELECTION_BAR_GAP * 2 }} />
        )}
      </div>
      {lightTile && (
        <Lightbox
          // No caption: the card under the picture already says the prompt
          // and the seed (this picture's own — `imageIndex`). A slot in the
          // list has no url, and the lightbox draws the card alone there.
          images={lightList.map((x) => ({
            url: x.name ? api.evalImageUrl(x.run.uid, x.name) : "",
          }))}
          index={lightAt}
          onIndex={(i) => {
            const x = lightList[i];
            if (x) setLightbox({ uid: x.run.uid, i: x.index });
          }}
          onClose={() => setLightbox(null)}
          openUrl={lightTile.name
            ? api.evalImageUrl(lightTile.run.uid, lightTile.name) : undefined}
          // The run's settings, under the picture they made. Applying a chip
          // closes the preview so the form it changed is on screen. No ✕
          // and no Remove on the card here: the preview has its own ✕, and
          // removing is the selection bar's.
          footer={
            <RunDetails run={lightTile.run} models={models}
              onApply={(patch) => { applyChip(patch); setLightbox(null); }}
              trainingBusy={trainingBusy} chrome={false}
              imageIndex={lightTile.index}
              onClose={() => setLightbox(null)} />
          }
        />
      )}
      {/* WHAT IS PICKED, and what to do with it — shown whenever there is
          anything in the grid at all, saying "None selected" with a Select
          all until something is. */}
      {runs.length > 0 && (
        <div style={{ position: "absolute", left: 20, right: 20,
                      bottom: SELECTION_BAR_GAP, zIndex: 5,
                      pointerEvents: "none" }}>
          <SelectionBar
            t={t}
            floating
            style={{ position: "static", marginTop: 0, marginBottom: 0,
                     pointerEvents: "auto" }}
            count={picked.length}
            total={order.length}
            onSelectAll={() => {
              setPicked(order);
              pickAnchor.current = order[order.length - 1] ?? null;
            }}
            onClear={clearPicked}
            onRemove={removePicked}
            removeIcon="delete"
            removeLabel={t("Remove")}
            removeCount={removableTiles.length}
            removeTitle={t("Remove the selected images (a generation that is still running stays)")}
            // The bar's third verb — the preview over the selection, the
            // same thing Space does — offered only while a picked tile has
            // a picture to show.
            extra={previewable ? {
              icon: "info",
              label: t("Info"),
              title: t("Preview the selected image (Space)"),
              onClick: () => { previewPicked(); },
            } : undefined}
          />
        </div>
      )}
      </div>
    </SidebarSplit>
  );
}
