// Vertical timeline of the job's run, newest step first: test-sample rounds
// (thumbnail grids), checkpoint saves and lifecycle events (started / paused
// / resumed / finished), each stamped with its wall-clock time and the net
// training duration reached (paused time excluded). A checkpoint still on
// disk shows its size with download/delete buttons; an auto-pruned one is
// left out of the timeline altogether.
import React, { useMemo, useState } from "react";
import { SectionHeading } from "../shared/SectionHeading";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, TrainCheckpoint, TrainEvent, TrainSample, TrainSampleRound } from "./api";
import { Icon } from "../shared/Icon";
import { confirm } from "../shared/ConfirmModal";
import { useT, useLang } from "./i18n";
import { Lightbox, LightboxImage } from "./Lightbox";
import { fmtDur, fmtSize } from "./util";
import { useDateFormatters } from "../shared/time";

type Row =
  | { kind: "event"; t: number; event: TrainEvent }
  | { kind: "samples"; t: number; event: null };

interface Entry {
  step: number;
  samples: TrainSample[];
  /** The round as the trainer reports it — present from the moment it starts
   *  rendering, so a round with no finished image yet still gets a row. */
  round: TrainSampleRound | null;
  checkpoint: TrainCheckpoint | null;
  // Events and the sample round, newest first — one list so they interleave.
  rows: Row[];
  events: TrainEvent[];
  t: number;             // latest known wall-clock time at this step
  trainSeconds: number;  // net training duration reached at this step
}

const EVENT_META: Record<string, { icon: string; label: string; color: string }> = {
  started: { icon: "play_arrow", label: "Training started", color: "var(--green-text)" },
  resumed: { icon: "play_circle", label: "Training resumed", color: "var(--green-text)" },
  paused: { icon: "pause", label: "Training paused", color: "var(--yellow-text)" },
  completed: { icon: "flag", label: "Training completed", color: "var(--green-text)" },
  failed: { icon: "error", label: "Training failed", color: "var(--red-text)" },
  canceled: { icon: "stop", label: "Training canceled", color: "var(--muted)" },
  edited: { icon: "edit", label: "Settings changed", color: "var(--muted)" },
};

export function SampleTimeline({ uid, active, phase = "", status = "" }: {
  uid: string;
  active: boolean;
  /** The job's current phase — "sampling" while a round is being rendered. */
  phase?: string;
  /** The job's status: a PAUSED job may turn its pause state into a real
   *  checkpoint (see below), no other one has anything to offer there. */
  status?: string;
}) {
  const t = useT();
  const lang = useLang();
  const { formatUnix } = useDateFormatters();
  const qc = useQueryClient();
  const sampling = active && phase === "sampling";
  const { data: samplesData } = useQuery({
    queryKey: ["train-samples", uid],
    queryFn: () => api.trainSamples(uid),
    // Each image appears the moment it is written, so poll briskly while a
    // round is actually rendering and lazily the rest of the time.
    refetchInterval: sampling ? 1500 : active ? 4000 : false,
  });
  const { data: ckptData } = useQuery({
    queryKey: ["train-checkpoints", uid],
    queryFn: () => api.trainCheckpoints(uid),
    refetchInterval: active ? 4000 : false,
  });
  const { data: eventData } = useQuery({
    queryKey: ["train-events", uid],
    queryFn: () => api.trainEvents(uid),
    refetchInterval: active ? 4000 : false,
  });
  const removeCkpt = useMutation({
    mutationFn: (step: number) => api.trainDeleteCheckpoint(uid, step),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["train-checkpoints", uid] }),
  });
  const keepCkpt = useMutation({
    mutationFn: (step: number) => api.trainKeepCheckpoint(uid, step),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["train-checkpoints", uid] });
      qc.invalidateQueries({ queryKey: ["train-lora-sources"] });
    },
  });
  const lockCkpt = useMutation({
    mutationFn: (a: { step: number; locked: boolean }) =>
      api.trainLockCheckpoint(uid, a.step, a.locked),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["train-checkpoints", uid] });
      qc.invalidateQueries({ queryKey: ["train-lora-sources"] });
    },
  });

  // What the user may see of a step's saved state. A `step-NNNNNN` snapshot
  // is a checkpoint: it stays put, it can be locked, downloaded and deleted.
  // `checkpoints/last` — the resume point — is NOT one: the trainer rewrites
  // it at every checkpoint and every pause, so it is internal bookkeeping.
  // (It used to be shown as its own kind of entry, which meant the newest
  // real checkpoint was labelled "Resume point" and looked like it had gone.)
  const snapshotOf = (e: Entry) => (e.checkpoint?.snapshot ? e.checkpoint : null);
  // The exception: a job paused at a step that has no snapshot has nothing
  // kept at all, and the next pause will overwrite the state it is holding.
  const pauseStateOf = (e: Entry) =>
    status === "paused" && e.checkpoint?.resume && !e.checkpoint.snapshot
      ? e.checkpoint : null;

  const entries = useMemo(() => {
    const m = new Map<number, Entry>();
    const at = (step: number): Entry => {
      let e = m.get(step);
      if (!e) {
        e = { step, samples: [], round: null, checkpoint: null, events: [],
              rows: [], t: 0, trainSeconds: 0 };
        m.set(step, e);
      }
      return e;
    };
    const stamp = (e: Entry, t: number, secs: number) => {
      e.t = Math.max(e.t, t);
      e.trainSeconds = Math.max(e.trainSeconds, secs);
    };
    for (const s of samplesData?.samples ?? []) {
      const e = at(s.step);
      e.samples.push(s);
      stamp(e, s.t, s.train_seconds);
    }
    for (const r of samplesData?.rounds ?? []) {
      const e = at(r.step);
      e.round = r;
      stamp(e, r.t, r.train_seconds);
    }
    for (const c of ckptData?.checkpoints ?? []) {
      if (!c.exists) continue; // auto-pruned snapshots stay out of the timeline
      const e = at(c.step);
      e.checkpoint = c;
      stamp(e, c.t, c.train_seconds);
    }
    for (const ev of eventData?.events ?? []) {
      const e = at(ev.step);
      e.events.push(ev);
      stamp(e, ev.t, ev.train_seconds);
    }
    for (const e of m.values()) {
      e.events.sort((a, b) => b.t - a.t);
      // The round's own timestamp (all its images share one) decides where it
      // sits among the events; without one it goes last, as it used to.
      const sampleT = e.round?.t
        ?? e.samples.reduce((mx, s) => Math.max(mx, s.t || 0), 0);
      e.rows = [
        ...e.events.map((ev) => ({ kind: "event" as const, t: ev.t, event: ev })),
        ...(e.round || e.samples.length
          ? [{ kind: "samples" as const, t: sampleT, event: null }] : []),
      ].sort((a, b) => (b.t || 0) - (a.t || 0));
    }
    return [...m.values()].sort((a, b) => b.step - a.step);
  }, [samplesData, ckptData, eventData]);

  // All samples in display order, for the lightbox's prev/next navigation.
  const gallery: LightboxImage[] = useMemo(
    () => entries.flatMap((e) => e.samples.map((s) => ({
      url: api.trainSampleUrl(uid, s.step, s.name),
      label: s.prompt,
      // The prompt again, beside the step: the big label sits above the image
      // and the subtitle is what you read while stepping through a round, so
      // "step 150" alone leaves you guessing which prompt you are looking at.
      sublabel: s.prompt
        ? `${t("Step")} ${s.step} · ${s.prompt}`
        : `${t("Step")} ${s.step}`,
      // Same file name = same prompt slot in every round, so ↑/↓ in the
      // lightbox walks this prompt through the run's sampled steps.
      group: s.name,
    }))),
    [entries, uid, t]
  );
  const [lightbox, setLightbox] = useState<number | null>(null);

  // How many images a round is still waiting for. Only while the job is
  // alive, and only for the NEWEST round: an older one cannot still be
  // rendering, so a round a pause cut short must not keep its hourglasses
  // for ever (the trainer finishes it on resume, which is when it fills in).
  const newestRound = entries.reduce(
    (mx, e) => (e.round ? Math.max(mx, e.step) : mx), -1);
  const pendingIn = (e: Entry) =>
    active && e.round && e.step === newestRound
      ? Math.max(0, e.round.expected - e.round.done) : 0;

  if (entries.length === 0) return null;

  return (
    <div>
      <SectionHeading style={{ margin: "0 2px 8px" }}>
        {t("Timeline")}
      </SectionHeading>
      <div style={{ position: "relative", paddingLeft: 18 }}>
        {/* timeline spine */}
        <div style={{
          position: "absolute", left: 5, top: 6, bottom: 6, width: 2,
          background: "var(--border)", borderRadius: 1,
        }} />
        {entries.map((e) => (
          <div key={e.step} style={{ position: "relative", marginBottom: 18 }}>
            <div style={{
              position: "absolute", left: -18, top: 3, width: 12, height: 12,
              borderRadius: "50%", background: "var(--panel)",
              border: `2px solid ${e.samples.length ? "var(--accent)" : "var(--border-strong)"}`,
              boxSizing: "border-box",
            }} />
            <div style={{
              display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
              fontSize: "var(--fs-2)", fontWeight: 600, color: "var(--text-2)",
              marginBottom: e.samples.length || e.events.length ? 7 : 0,
              minHeight: 20,
            }}>
              <span>{t("Step")} {e.step}</span>
              {/* Steps show only the net training time reached; wall-clock
                  timestamps live on the start/stop event rows. */}
              {e.trainSeconds > 0 && (
                <span style={{
                  fontWeight: 400, fontSize: "var(--fs-1)", color: "var(--muted)",
                  fontVariantNumeric: "tabular-nums",
                }}>
                  {t("{d} trained", { d: fmtDur(e.trainSeconds) })}
                </span>
              )}
              {snapshotOf(e) && (
                <span style={{
                  display: "inline-flex", alignItems: "stretch",
                  borderRadius: "var(--r-3)", overflow: "hidden", fontWeight: 500,
                  background: "var(--panel)", border: "1px solid var(--border)",
                  fontSize: "var(--fs-1)",
                }}>
                  {/* The whole left half IS the download button. */}
                  <button
                    title={t("Download checkpoint")}
                    onClick={() => {
                      // A plain navigation: the endpoint answers with a zip +
                      // filename, so the browser downloads instead of leaving.
                      const a = document.createElement("a");
                      a.href = api.trainCheckpointUrl(uid, e.step);
                      a.click();
                    }}
                    className="hoverable"
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      padding: "2px 8px", border: "none",
                      background: "transparent", color: "var(--text-2)",
                      fontSize: "var(--fs-1)", fontWeight: 500, cursor: "pointer",
                      fontFamily: "inherit",
                    }}
                  >
                    <Icon name="save" size={13} />
                    {t("Checkpoint")}
                    <span style={{ color: "var(--muted-2)", fontWeight: 400 }}>
                      {fmtSize(e.checkpoint!.size / 2 ** 20, lang)}
                    </span>
                  </button>
                  <span style={{
                    width: 1, background: "var(--border-strong)",
                  }} />
                  <button
                    title={e.checkpoint!.locked
                      ? t("Unlock — allows deleting again (and the keep-last rule may prune it)")
                      : t("Lock — protects this checkpoint from deletion and from the keep-last rule")}
                    onClick={() => lockCkpt.mutate({
                      step: e.step, locked: !e.checkpoint!.locked,
                    })}
                    className="hoverable"
                    style={{
                      border: "none", background: "transparent",
                      padding: "0 7px", display: "inline-flex",
                      alignItems: "center",
                      color: e.checkpoint!.locked
                        ? "var(--accent)" : "var(--muted)",
                      cursor: "pointer",
                    }}
                  >
                    <Icon name={e.checkpoint!.locked ? "lock" : "lock_open"}
                      size={13} />
                  </button>
                  {!e.checkpoint!.locked && (
                    <>
                      <span style={{
                        width: 1, background: "var(--border-strong)",
                      }} />
                      <button
                        title={t("Delete checkpoint")}
                        onClick={async () => {
                          if (await confirm({ title: t("Delete this checkpoint from disk?"),
                                              answer: { label: t("Delete"), danger: true } }))
                            removeCkpt.mutate(e.step);
                        }}
                        className="hoverable"
                        style={{
                          border: "none", background: "transparent",
                          padding: "0 7px", display: "inline-flex",
                          alignItems: "center", color: "var(--red-text)",
                          cursor: "pointer",
                        }}
                      >
                        <Icon name="delete" size={13} />
                      </button>
                    </>
                  )}
                </span>
              )}
              {/* The state a paused job would continue from is internal —
                  it is not a checkpoint, and the next pause overwrites it.
                  The one thing worth offering is turning it into a real one,
                  since otherwise this step has nothing kept at all. */}
              {pauseStateOf(e) && (
                <button
                  title={t("Save this pause state as a checkpoint — otherwise it is replaced the next time the job pauses")}
                  onClick={() => keepCkpt.mutate(e.step)}
                  className="hoverable"
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 5,
                    padding: "2px 8px", borderRadius: "var(--r-3)",
                    background: "var(--panel)",
                    border: "1px dashed var(--border-strong)",
                    color: "var(--muted)", fontSize: "var(--fs-1)", fontWeight: 500,
                    cursor: "pointer", fontFamily: "inherit",
                  }}
                >
                  <Icon name="bookmark_add" size={13} />
                  {t("Keep as checkpoint")}
                </button>
              )}
            </div>
            {/* Events and the sample round are ordered against each other by
                their own clocks, so a round sits where it happened — between
                "training started" and whatever ended the run. */}
            {e.rows.map((row, i) => row.kind === "samples" ? (
              <div key={`samples-${i}`}>
                <div style={{
                  display: "flex", alignItems: "center", gap: 7,
                  fontSize: "var(--fs-2)", color: "var(--text-2)", margin: "2px 0 6px",
                }}>
                  <Icon name="image" size={14} color="var(--muted)" />
                  <span style={{ fontWeight: 600, color: "var(--muted)" }}>
                    {t("Test samples")}
                  </span>
                  {row.t > 0 && (
                    <span style={{
                      color: "var(--muted)", fontVariantNumeric: "tabular-nums",
                    }}>
                      {formatUnix(row.t)}
                    </span>
                  )}
                  {pendingIn(e) > 0 && e.round && (
                    <span style={{
                      color: "var(--accent)", fontVariantNumeric: "tabular-nums",
                    }}>
                      {e.round.done} / {e.round.expected}
                    </span>
                  )}
                </div>
                <div style={{
                  display: "grid", gap: 8, marginBottom: 6,
                  gridTemplateColumns: "repeat(auto-fill, minmax(148px, 1fr))",
                }}>
                  {/* A round in progress shows the images it has finished plus
                      a placeholder for each one still to come, so the grid does
                      not silently grow and you can see how far along it is. */}
                  {e.samples.map((s) => {
                    const url = api.trainSampleUrl(uid, s.step, s.name);
                    return (
                      <button
                        key={s.name}
                        onClick={() => setLightbox(
                          gallery.findIndex((g) => g.url === url))}
                        title={s.prompt}
                        style={{
                          display: "block", borderRadius: "var(--r-6)", overflow: "hidden",
                          border: "1px solid var(--border)",
                          background: "var(--bg-deep)", aspectRatio: "1",
                          lineHeight: 0, padding: 0, cursor: "zoom-in",
                        }}
                      >
                        <img
                          src={api.trainSampleUrl(uid, s.step, s.name, 320)}
                          alt={s.prompt}
                          loading="lazy"
                          style={{ width: "100%", height: "100%", objectFit: "cover" }}
                        />
                      </button>
                    );
                  })}
                  {Array.from({ length: pendingIn(e) }).map((_, i) => (
                    <div
                      key={`pending-${i}`}
                      title={t("Still rendering…")}
                      style={{
                        borderRadius: "var(--r-6)", aspectRatio: "1",
                        border: "1px solid var(--border)",
                        // A filled grey tile, not an outline: it stands in for
                        // an image, and the icon says it is not one yet.
                        background: "var(--panel-3)", display: "flex",
                        alignItems: "center", justifyContent: "center",
                        color: "var(--muted-2)",
                      }}
                    >
                      <Icon name="hourglass_top" size={20} />
                    </div>
                  ))}
                </div>
              </div>
            ) : (() => {
              const ev = row.event;
              const meta = EVENT_META[ev.kind] ?? {
                icon: "info", label: ev.kind, color: "var(--muted)",
              };
              return (
                <div key={`${ev.kind}-${ev.t}-${i}`} style={{ margin: "2px 0 6px" }}>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 7,
                    fontSize: "var(--fs-2)", color: "var(--text-2)",
                  }}>
                    <Icon name={meta.icon} size={14} color={meta.color} />
                    <span style={{ fontWeight: 600, color: meta.color }}>
                      {t(meta.label)}
                    </span>
                    <span style={{
                      color: "var(--muted)", fontVariantNumeric: "tabular-nums",
                    }}>
                      {formatUnix(ev.t)}
                    </span>
                  </div>
                  {/* An edit says WHAT changed: the settings no longer
                      necessarily describe the run behind this point, so the
                      timeline carries the difference. */}
                  {(ev.changes ?? []).length > 0 && (
                    <div style={{
                      marginLeft: 21, marginTop: 2, display: "flex",
                      flexDirection: "column", gap: 1,
                    }}>
                      {(ev.changes ?? []).map((c) => (
                        <div key={c.field} style={{
                          fontSize: "var(--fs-1)", color: "var(--muted)",
                          fontFamily: "var(--mono)", whiteSpace: "nowrap",
                          overflow: "hidden", textOverflow: "ellipsis",
                        }}>
                          {c.field}: <span style={{ color: "var(--muted-3)" }}>
                            {c.old}
                          </span>
                          {" → "}
                          <span style={{ color: "var(--text-2)" }}>{c.new}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })())}
          </div>
        ))}
      </div>
      {lightbox !== null && lightbox >= 0 && (
        <Lightbox
          images={gallery}
          index={lightbox}
          onIndex={setLightbox}
          onClose={() => setLightbox(null)}
        />
      )}
    </div>
  );
}
