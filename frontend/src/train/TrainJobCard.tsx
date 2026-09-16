// One job row in the Train tab's list: name, model/method chips, progress and
// the status-dependent actions that MOVE it between sections (start now, add
// to / take out of the queue, pause). Removing a job is deliberately not one
// of them -- that is the selection bar's verb.
import React, { useRef } from "react";
import { gripProps } from "../shared/useDragRow";
import { rowBackground } from "../shared/Row";
import { SectionHeading } from "../shared/SectionHeading";
import { IconButton } from "../shared/IconButton";
import { ProgressBar } from "../shared/ProgressBar";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, TrainingJobSummary } from "./api";
import { Icon } from "../shared/Icon";
import { useT } from "./i18n";
import { errText, fracStepText, lastActivity, statusColor, STATUS_LABELS } from "./util";
import { useDateFormatters } from "../shared/time";

function ActionButton({ icon, title, onClick, danger, disabled }: {
  icon: string; title: string; onClick: () => void;
  danger?: boolean; disabled?: boolean;
}) {
  return (
    <IconButton icon={icon} size={28} color={danger ? "var(--red-text)" : "var(--muted)"} disabled={disabled}
      title={title}
      onClick={(e) => { e.stopPropagation(); onClick(); }} style={{ flex: "0 0 auto" }} />
  );
}

export function TrainJobCard({ job, selected, onSelect, dragHandle,
                              evalBusy, queueActive, onRefused }: {
  job: TrainingJobSummary;
  /** In the tab's ONE selection: what a bulk action would act on, and — while
   *  it holds exactly this row — what the detail pane is showing. */
  selected: boolean;
  onSelect: (mods: { meta: boolean; shift: boolean }) => void;
  /** An Evaluate generation holds the GPU this job would use. */
  evalBusy?: boolean;
  /** Whether the queue is working through jobs — the start button says which
   *  of the two things it is about to do. */
  queueActive?: boolean;
  /** Present on draggable rows: only the handle starts the drag. */
  dragHandle?: {
    title?: string; onDragStart: () => void; onDragEnd: () => void;
  };
  /** WHAT THE SERVER SAID when an action was refused. Every one of these
   *  buttons can be refused for a reason only the server knows — the model
   *  still has to be downloaded and downloads are off (400), the device is
   *  busy, the config is not queueable — and the reply was dropped on the
   *  floor: the row simply did not move, which reads as a button that does
   *  nothing. Reported upward rather than shown here because a 34 px row has
   *  nowhere to put a sentence, and because the drag has the same problem
   *  and must land in the same place. */
  onRefused?: (message: string) => void;
}) {
  const t = useT();
  const { formatAgo } = useDateFormatters();
  const qc = useQueryClient();
  // Both halves of the tab: the detail pane has its own query, and refreshing
  // only the list left it showing the state from before the click.
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["train-jobs"] });
    qc.invalidateQueries({ queryKey: ["train-job", job.uid] });
  };
  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => { onRefused?.(""); refresh(); },
    // A refusal is still a reason to re-sync — a 409 means the list is stale
    // — but it is also the answer to "why did nothing happen", so it is said
    // out loud as well.
    onError: (e) => { onRefused?.(errText(e)); refresh(); },
  });

  // The row itself is the drag preview: only the handle starts a drag, and
  // a drag showing nothing but the handle icon says nothing about what is
  // being moved. Handing `setDragImage` a LIVE, on-screen element (rather
  // than a clone parked off-viewport) is also the form Safari renders
  // reliably — it snapshots what is actually on the screen.
  const rowRef = useRef<HTMLDivElement | null>(null);

  const running = job.status === "running" || job.status === "pausing";
  const pct = job.total_steps > 0
    ? Math.min(100, (100 * job.step) / job.total_steps) : 0;

  return (
    <div
      ref={rowRef}
      onClick={(e) => onSelect({ meta: e.metaKey || e.ctrlKey, shift: e.shiftKey })}
      className="hoverable"
      style={{
        padding: "10px 12px", cursor: "pointer",
        borderBottom: "1px solid var(--border-soft)",
        background: rowBackground(selected, "transparent"),
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {dragHandle && (
          <span
            {...gripProps({ payload: job.uid, rowRef,
                            onStart: () => dragHandle.onDragStart(),
                            onEnd: () => dragHandle.onDragEnd() })}
            onClick={(e) => e.stopPropagation()}
            title={dragHandle.title ?? t("Drag to change the queue order")}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              width: 16, margin: "0 -4px 0 -6px", alignSelf: "stretch",
              color: "var(--muted-3)", cursor: "grab", flex: "0 0 auto",
            }}
          >
            <Icon name="drag_indicator" size={14} />
          </span>
        )}
        {job.status === "running" || job.status === "pausing" ? (
          <Icon name="progress_activity" size={16} color="var(--accent)" spin />
        ) : (
          <span style={{
            width: 8, height: 8, borderRadius: "50%", margin: "0 4px",
            background: statusColor(job.status), flex: "0 0 auto",
          }} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: "var(--fs-3)", fontWeight: 600, whiteSpace: "nowrap",
            overflow: "hidden", textOverflow: "ellipsis",
            // Copyable: text selection is suppressed app-wide, but a job's
            // name is something you paste into searches and messages.
            userSelect: "text",
          }}>
            {job.name}
          </div>
          <div style={{ fontSize: "var(--fs-1)", color: "var(--muted)", marginTop: 1 }}>
            {job.model && <SectionHeading>{job.model}</SectionHeading>}
            {job.method && <span> · {job.method === "lora"
              ? (job.network === "lokr" ? "LoKr" : "LoRA")
              : t("Full finetune")}</span>}
            <span> · <span style={{ color: statusColor(job.status) }}>
              {t(STATUS_LABELS[job.status] ?? job.status)}
            </span></span>
            {/* Queued because the OTHER tab has the GPU, not because it is
                next in line — "Queued" alone made a start look ignored. */}
            {job.status === "queued" && evalBusy && (
              <span style={{ color: "var(--yellow-text)" }}>
                {" · "}{t("waiting for the GPU — the Evaluate tab is generating")}
              </span>
            )}
            {running && job.phase && job.phase !== "training" && (
              <span> · {t(job.phase.replace(/_/g, " "))}
                {job.phase_note ? ` ${job.phase_note}` : ""}</span>
            )}
          </div>
        </div>
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "flex-end",
          gap: 1, flex: "0 0 auto",
        }}>
          <div style={{
            fontSize: "var(--fs-2)", color: "var(--text-2)",
            fontVariantNumeric: "tabular-nums",
          }}>
            {/* Queued and draft jobs show it too: "0 / 2000" is how long the
                run will be, which is exactly what you want to see before it
                starts — not only after. While inside a step, the accumulation
                micro-batches show as a fraction ("20.25"), so a minutes-long
                big-batch step still visibly moves. */}
            {job.total_steps > 0 ? `${fracStepText(job)} / ${job.total_steps}` : null}
          </div>
          {/* When this job last did anything. With a dozen jobs in the list,
              "yesterday" against "3 months ago" is what tells you which one
              you were working on. */}
          <div style={{ fontSize: "var(--fs-0)", color: "var(--muted-3)" }}>
            {formatAgo(lastActivity(job))}
          </div>
        </div>
        <div style={{ display: "flex", gap: 1, flex: "0 0 auto" }}>
          {/* START IS ON EVERY WAITING ROW, and it means "this one, now": the
              job goes to the front of the queue, whatever is running is
              paused, and the queue is left running so the rest follows. It
              was deliberately absent for a while — the argument being that a
              tab whose model is a QUEUE you press Run on should not also let
              a row start something the queue was never told to start. What
              that cost is the ordinary case: wanting THIS job next meant
              dragging it to the top, pausing the running one, and pressing
              Run — three gestures for one intent, none of them undoable in
              one step either. The button is that intent, and the queue is
              still explicit: it says what it will do, and it leaves the queue
              running rather than sneaking one job past it.

              The verb that MOVES the job between sections stays beside it. */}
          {(job.status === "draft" || job.status === "paused"
            || job.status === "queued") && (
            <ActionButton icon="play_arrow"
              title={queueActive
                ? t("Start now — pauses the running job and puts this one first")
                : t("Start now — puts this job first and starts the queue")}
              onClick={() => act.mutate(() => api.trainStart(job.uid, true))} />
          )}
          {job.status === "draft" && (
            <ActionButton icon="playlist_add" title={t("Add to the queue")}
              onClick={() => act.mutate(() => api.trainQueue(job.uid))} />
          )}
          {job.status === "paused" && (
            <ActionButton icon="playlist_add"
              title={t("Add to the queue — resumes from the last checkpoint when its turn comes")}
              onClick={() => act.mutate(() => api.trainQueue(job.uid))} />
          )}
          {job.status === "queued" && (
            <ActionButton icon="playlist_remove" title={t("Remove from the queue — the job keeps its place for later")}
              onClick={() => act.mutate(() => api.trainPause(job.uid))} />
          )}
          {job.status === "running" && (
            <ActionButton icon="pause" title={t("Pause (saves a checkpoint)")}
              onClick={() => act.mutate(() => api.trainPause(job.uid))} />
          )}
          {job.status === "pausing" && (
            <ActionButton icon="pause" title={t("Pausing…")} onClick={() => {}} disabled />
          )}
          {/* THERE IS NO DELETE ON THE ROW. Removing a job is the SELECTION
              BAR's verb — it names how many it will take, leaves a running
              job alone and says so, and asks by name — and a bin on every
              row was a second door to the one irreversible action in this
              list, sitting a few pixels from the pause button on a row whose
              neighbours look alike. The buttons that remain all move the job
              between sections, which is what a row's own controls are for. */}
        </div>
      </div>
      {/* Only the RUNNING job carries the thin progress bar — the counter
          says where a paused job stands, and a bar on every held row made
          the sidebar read as if everything were in flight. */}
      {running && job.total_steps > 0 && (
        <ProgressBar value={pct} height={3} transitionMs={600} style={{ marginTop: 7 }} />
      )}
      {(job.status === "failed" || job.status === "paused") && job.message && (
        <div style={{
          marginTop: 6, fontSize: "var(--fs-1)", color: "var(--red-text)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {job.message}
        </div>
      )}
    </div>
  );
}
