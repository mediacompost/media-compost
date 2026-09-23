// Right pane of the Train tab: one job's status header, actions, loss graph,
// sample timeline, read-only config summary and a log viewer.
import React, { useEffect, useState } from "react";
import { Button } from "../shared/Button";
import { ProgressBar } from "../shared/ProgressBar";
import { useInlineEdit } from "../shared/useInlineEdit";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { Icon } from "../shared/Icon";
import { Overlay } from "../shared/Overlay";
import { useNum, useT, useTn } from "./i18n";
import { ArchitectureMap } from "./ArchitectureMap";
import { LossGraph } from "./LossGraph";
import { fmtEta, pace, useMetrics } from "./useMetrics";
import { SampleTimeline } from "./SampleTimeline";
import { TrainDataInspector } from "./TrainDataInspector";
import { ACTIVE_STATUSES, cadenceSteps, errText, fracStepText, statusColor, STATUS_LABELS } from "./util";
import { invalidateJob } from "./invalidate";
import { StepPhases } from "./StepPhases";
import { useDateFormatters } from "../shared/time";
import { renderAnsi } from "../shared/ansi";

/** Inline total-steps editor: running jobs adopt the new target live, paused
 *  ones on resume, and completed ones flip back to paused so Resume can
 *  continue the finished run. */
function ExtendSteps({ uid, job, onDone }: {
  uid: string;
  job: { status: string; step: number; total_steps: number };
  onDone: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const num = useNum();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const apply = async () => {
    const steps = Math.round(Number(text));
    if (!isFinite(steps) || steps <= 0) return;
    setError("");
    try {
      await api.trainSetSteps(uid, steps);
      setEditing(false);
      onDone();
    } catch (e) {
      setError(errText(e));
    }
  };
  if (!editing) {
    return (
      <button
        onClick={() => { setText(String(job.total_steps)); setEditing(true); }}
        title={t("Change the total step count — raise it on a finished job to continue training from its last checkpoint.")}
        style={{
          display: "inline-flex", alignItems: "center", gap: 5, height: 24,
          padding: "0 9px", borderRadius: "var(--r-3)",
          border: "1px solid var(--border-strong)", background: "transparent",
          color: "var(--text-2)", fontSize: "var(--fs-2)", cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        <Icon name="edit" size={13} />
        {job.status === "completed" ? t("Extend steps") : t("Edit steps")}
      </button>
    );
  }
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <input
        autoFocus
        value={text}
        inputMode="numeric"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={useInlineEdit({ commit: apply, cancel: () => setEditing(false),
                                   commitOnBlur: false }).onKeyDown}
        style={{
          width: 80, height: 24, padding: "0 8px", textAlign: "right",
          background: "var(--bg)", border: "1px solid var(--border-strong)",
          borderRadius: "var(--r-3)", color: "var(--text)", fontSize: "var(--fs-2)",
          fontFamily: "inherit", outline: "none",
        }}
      />
      <button
        onClick={apply}
        style={{
          height: 24, padding: "0 10px", borderRadius: "var(--r-3)", border: "none",
          background: "var(--accent)", color: "var(--on-accent)",
          fontSize: "var(--fs-2)", fontWeight: 600, cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        {t("Apply")}
      </button>
      {error && (
        <span style={{ fontSize: "var(--fs-1)", color: "var(--red-text)" }}>{error}</span>
      )}
    </span>
  );
}

function HeaderButton({ icon, label, onClick, danger }: {
  icon: string; label: string; onClick: () => void; danger?: boolean;
}) {
  return (
    <Button variant={danger ? "danger" : "ghost"} size="sm"
   onClick={onClick} style={{ flex: "0 0 auto" }}>
      <Icon name={icon} size={15} />
      {label}
    </Button>
  );
}

// Steps in one pass over the dataset, for the loss graph's epoch lines. Sampling
// is weighted-with-replacement so an epoch is approximate (dataset coverage on
// average), but it's a useful landmark. 0 when the dataset size isn't known yet.
function stepsPerEpoch(job: {
  dataset?: { images?: number };
  config?: { hyper?: { batch_size?: number; grad_accum?: number } };
}): number {
  const images = job.dataset?.images ?? 0;
  const eff = Math.max(1, (job.config?.hyper?.batch_size ?? 1) * (job.config?.hyper?.grad_accum ?? 1));
  return images > 0 ? Math.max(1, Math.ceil(images / eff)) : 0;
}

// Fraction-digit presets for `useNum` — a loss and a rate readout keep their
// widths while the separator follows the language ("0,0421").
const FIX1 = { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false } as const;
const FIX4 = { minimumFractionDigits: 4, maximumFractionDigits: 4, useGrouping: false } as const;

export function TrainJobDetail({ uid, onEdit, onDelete }: {
  uid: string;
  onEdit: () => void;
  /** Remove this job — the list's own removal, so the question asked and
   *  what a locked checkpoint keeps are the same wherever it is pressed. */
  onDelete: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const num = useNum();
  const { formatUnix } = useDateFormatters();
  const qc = useQueryClient();
  const [showLog, setShowLog] = useState(false);
  const [showData, setShowData] = useState(false);
  // The list is polled while anything is active and is invalidated by every
  // action in it, so it is the freshest thing on the page. The detail follows
  // it: poll while the LIST says this job is alive (its own copy may still
  // say "draft"), and refetch whenever the two disagree — that is what makes
  // the right half react to a start/pause from the left, or to a job failing.
  const { data: list } = useQuery({
    queryKey: ["train-jobs"], queryFn: api.trainJobs,
  });
  const listed = list?.jobs.find((j) => j.uid === uid);
  const { data: job } = useQuery({
    queryKey: ["train-job", uid],
    queryFn: () => api.trainJob(uid),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return ACTIVE_STATUSES.has(s ?? "")
        || ACTIVE_STATUSES.has(listed?.status ?? "") ? 1500 : false;
    },
  });
  useEffect(() => {
    if (!listed || !job) return;
    if (listed.status !== job.status || listed.step !== job.step) {
      qc.invalidateQueries({ queryKey: ["train-job", uid] });
    }
  }, [listed?.status, listed?.step, job?.status, job?.step, uid, qc]);
  // One sweep for everything about this job — the pane's own actions change
  // the timeline too (a pause writes an entry, a checkpoint delete removes
  // one), and only a running job polls for it.
  const refresh = () => invalidateJob(qc, uid);
  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: refresh,
    onError: refresh,
  });

  const active = job?.status === "running" || job?.status === "pausing";
  // Fetched here rather than in the graph: the progress line above it reads
  // the same points (see useMetrics).
  const metrics = useMetrics(uid, active);
  if (!job) return null;
  const pct = job.total_steps > 0
    ? Math.min(100, (100 * job.step) / job.total_steps) : 0;
  const speed = pace(metrics.points);
  const left = job.total_steps - job.step;
  const eta = speed && left > 0 ? fmtEta(left * speed.secPerStep) : "";

  return (
    // NO READING WIDTH HERE (owner 2026-09): the pane is what the divider
    // beside it leaves, and a column that stopped at 860 px left the rest of
    // a wide window empty beside a chart that would have used it. What is
    // inside already answers to its width — the header wraps, the sample
    // grid fills by `auto-fill`, the chart is measured.
    <div style={{ padding: "18px 22px" }}>
      {/* Header */}
      {/* THE BUTTONS WRAP RATHER THAN SQUASH. This row is the job's name and
          up to five controls, and on a narrow right half they were sharing
          the width with the name — every label broken over two lines inside
          its own button, the name ellipsised to nothing. Wrapping keeps each
          one whole and, unlike folding them into a ⋯, keeps the run control
          (Start / Resume / Pause) visible at every width, which is the one
          the hand reaches for. The name keeps a 260px basis so it takes the
          first line by itself before anything drops below it. */}
      <div style={{ display: "flex", alignItems: "center", gap: 12,
                    flexWrap: "wrap", rowGap: 10 }}>
        <div style={{ flex: "1 1 260px", minWidth: 0 }}>
          <div style={{ fontSize: "var(--fs-5)", fontWeight: 600, userSelect: "text",
                        cursor: "text" }}>
            {job.name}
          </div>
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted)", marginTop: 3 }}>
            <span style={{ color: statusColor(job.status), fontWeight: 600 }}>
              {t(STATUS_LABELS[job.status] ?? job.status)}
            </span>
            {job.phase && active && job.phase !== "training" && (
              // What it is doing while there are no steps yet to report.
              <span> · {t(job.phase.replace(/_/g, " "))}
                {job.phase_note ? ` ${job.phase_note}` : ""}</span>
            )}
            {job.started_at && <span> · {t("started")} {formatUnix(job.started_at)}</span>}
            {job.finished_at && <span> · {t("finished")} {formatUnix(job.finished_at)}</span>}
            {job.username && <span> · {job.username}</span>}
          </div>
        </div>
        {/* Anything not yet running starts from here — including a QUEUED
            job, which used to offer only a red Cancel: the obvious thing to
            want from a job waiting in the queue is to run it now, not to
            discard it (it can still be taken out of the queue from its row).
            Paused jobs say Resume, since they continue from a checkpoint. */}
        {(job.status === "draft" || job.status === "queued"
          || job.status === "paused") && (
          <HeaderButton icon="play_arrow"
            label={job.status === "paused" ? t("Resume") : t("Start")}
            onClick={() => act.mutate(() => api.trainStart(uid))} />
        )}
        {job.status === "running" && (
          <HeaderButton icon="pause" label={t("Pause")}
            onClick={() => act.mutate(() => api.trainPause(uid))} />
        )}
        {/* Always offered: a finished or running job opens the same editor
            read-only-ish, where Save becomes "Save as new job". That replaced
            the Duplicate button — duplicating blind, without seeing what you
            were duplicating, was the worse half of the same action. It sits
            AFTER the run control: what the row is for is starting, resuming
            or pausing the run, and that verb is the one the hand reaches for
            first. */}
        <HeaderButton icon="edit" label={t("Edit")} onClick={onEdit} />
        {/* Removing it, beside the button that edits it — the two things one
            does TO a job rather than to its run, which is what the controls
            before them are. Never for a RUNNING job: pausing keeps everything
            the run has earned, and a red button one click from Pause is the
            more destructive half of the same gesture. Pause it first, then
            remove it if that is what you meant. */}
        {!active && (
          <HeaderButton icon="delete" label={t("Delete")} danger
            onClick={onDelete} />
        )}
        <HeaderButton icon="receipt_long" label={t("Log")}
          onClick={() => setShowLog(true)} />
        <HeaderButton icon="dataset" label={t("Data")}
          onClick={() => setShowData(true)} />
      </div>

      {/* Progress */}
      {(active || job.status === "paused") && job.total_steps > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            fontSize: "var(--fs-2)", color: "var(--text-2)", marginBottom: 5,
            fontVariantNumeric: "tabular-nums",
          }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
              {/* Inside a step the accumulation micro-batches show as a
                  fraction ("20.25"), so a minutes-long step still moves. */}
              {t("Step")} {fracStepText(job)} / {job.total_steps}
              <ExtendSteps uid={uid} job={job} onDone={refresh} />
            </span>
            <span>{pct.toFixed(0)}%</span>
          </div>
          <ProgressBar value={pct} transitionMs={600}
                       color={job.status === "paused" ? "var(--yellow-text)" : "var(--accent)"} />
          {/* What a step currently costs, what that leaves, and where the loss
              is — the three questions you have while watching a run, none of
              which "step 412 / 2000" answers. Measured over the last steps, so
              it follows the run rather than averaging its whole history. */}
          {speed && (
            <div style={{
              display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
              marginTop: 6, fontSize: "var(--fs-2)", color: "var(--muted)",
              fontVariantNumeric: "tabular-nums",
            }}>
              <span title={t("Measured over the last steps of this run")}>
                {speed.secPerStep >= 1
                  ? `${num(speed.secPerStep, FIX1)} s / ${t("step")}`
                  : `${num(1 / speed.secPerStep, FIX1)} ${t("steps")} / s`}
              </span>
              {eta && active && (
                <span>· {t("about {d} left", { d: eta })}</span>
              )}
              <span>· {t("loss")} {num(speed.loss, FIX4)}</span>
              {/* What it is training on — a number that explains the pace as
                  much as the model does. */}
              {job.dataset?.images ? (
                <span title={t("The images this run trains on, sorted into aspect-ratio buckets")}>
                  · {tn({ one: "1 image", other: "{n} images" },
                         job.dataset.images)}
                  {/* How many of them came out of a film. A frame has no
                      stored file and so nothing in the library to look at
                      afterwards — this is where a run says it took them. */}
                  {job.dataset.frames
                    ? ` · ${tn({ one: "1 from video", other: "{n} from video" },
                               job.dataset.frames)}`
                    : ""}
                  {/* Only when there are several: one bucket says nothing. */}
                  {(job.dataset.buckets ?? 0) > 1
                    ? ` · ${tn({ one: "1 bucket", other: "{n} buckets" },
                               job.dataset.buckets ?? 0)}`
                    : ""}
                </span>
              ) : null}
              {/* Sampling and checkpoints happen between steps, so they are
                  the reason a rate suddenly drops — say which is running. */}
              {active && job.phase && job.phase !== "training" && (
                <span style={{ color: "var(--accent)" }}>
                  · {t(job.phase.replace(/_/g, " "))}
                  {job.phase_note ? ` ${job.phase_note}` : ""}
                </span>
              )}
            </div>
          )}
        </div>
      )}
      {job.status === "completed" && (
        <div style={{
          marginTop: 12, display: "flex", alignItems: "center", gap: 10,
          fontSize: "var(--fs-2)", color: "var(--muted)",
          fontVariantNumeric: "tabular-nums",
        }}>
          <span>{t("Step")} {job.step} / {job.total_steps}</span>
          <ExtendSteps uid={uid} job={job} onDone={refresh} />
        </div>
      )}
      {job.message && (job.status === "failed" || job.status === "paused") && (
        // Selectable: the app suppresses text selection globally, but an
        // error exists to be copied into a search or a bug report.
        <div
          title={t("Select to copy")}
          style={{
            marginTop: 12, padding: "10px 12px", borderRadius: "var(--r-6)",
            background: "var(--panel)", border: "1px solid var(--red-text)",
            fontSize: "var(--fs-3)", color: "var(--red-text)", fontFamily: "var(--mono)",
            whiteSpace: "pre-wrap", overflowWrap: "anywhere",
            userSelect: "text", WebkitUserSelect: "text", cursor: "text",
          }}
        >
          {job.message}
        </div>
      )}

      <div style={{ height: 16 }} />
      {/* Where the loop is right now — above the graph, which is the run's
          history. A finished run keeps it, with Done lit and no countdowns. */}
      {(active || job.status === "completed") && (
        <StepPhases phase={job.phase ?? ""} note={job.phase_note ?? ""}
          sub={job.phase_sub ?? ""} status={job.status}
          step={job.step} totalSteps={job.total_steps}
          // A job that never samples doesn't get the dot at all.
          showSamples={(job.config?.sampling?.prompts?.length ?? 0) > 0}
          // The RUN's own figures where it has reported them — see
          // `cadenceSteps`.
          ckptEvery={cadenceSteps(
            job.ckpt_every, job.config?.hyper?.checkpoint_epochs,
            job.config?.hyper?.checkpoint_every)}
          sampleEvery={cadenceSteps(
            job.sample_every, job.config?.sampling?.every_n_epochs,
            job.config?.sampling?.every_n_steps)}
          // Only when the run can actually score anything — a cadence with
          // both counts at 0 validates nothing, and its dot would count down
          // to a phase that never comes.
          valEvery={((job.config?.validation?.holdout ?? 0) > 0
                     || (job.config?.validation?.stable_items ?? 0) > 0)
            ? (job.config?.validation?.every_n_steps ?? 0) : 0}
          accum={job.config?.hyper?.grad_accum ?? 1} />
      )}
      <div style={{ height: 16 }} />
      <LossGraph points={metrics.points} diverged={metrics.diverged}
        stepsPerEpoch={stepsPerEpoch(job)}
        warmupSteps={job.config?.hyper?.warmup_steps ?? 0} />
      <div style={{ height: 16 }} />
      {/* What is being trained — below the run's own progress, since it is
          the same for every step and the line above changes every second. */}
      <ArchitectureMap uid={uid} running={job.status === "running"} />

      <SampleTimeline uid={uid} active={active} phase={job.phase}
        status={job.status} />

      <div style={{ height: 24 }} />

      {showLog && (
        <LogOverlay uid={uid} active={active} onClose={() => setShowLog(false)} />
      )}
      {showData && (
        <TrainDataInspector uid={uid} active={active}
          points={metrics.points} onClose={() => setShowData(false)} />
      )}
    </div>
  );
}

/** The job's log, as its own dialog — the detail pane's Log button and the
 *  job list's context menu open the same one. */
export function LogOverlay({ uid, active, onClose }: {
  uid: string; active: boolean; onClose: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const num = useNum();
  const { data } = useQuery({
    queryKey: ["train-log", uid],
    queryFn: () => api.trainLog(uid),
    refetchInterval: active ? 2000 : false,
  });
  return (
    <Overlay icon="receipt_long" title={t("Training log")} width={760} onClose={onClose}>
      {/* Same reason as the failure box: a log is read to be copied out. */}
      <pre style={{
        margin: 0, padding: 16, minHeight: 200, maxHeight: 480,
        overflow: "auto", fontSize: "var(--fs-2)", lineHeight: 1.5,
        fontFamily: "var(--mono)", background: "var(--bg-deep)",
        whiteSpace: "pre-wrap", color: "var(--text-2)",
        userSelect: "text", WebkitUserSelect: "text", cursor: "text",
      }}>
        {data?.log ? renderAnsi(data.log) : t("No output yet.")}
      </pre>
    </Overlay>
  );
}
