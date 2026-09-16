// What a running job is doing, as one short line: Prepare → Train → the
// interludes still to come (Sample / Checkpoint, in the order they will
// actually happen) → Done.
//
// The line is plain: the repetition between two phases is said by the
// subtitles ("in 120 steps"), not drawn. Earlier versions tried an arc, a
// counter and an arrowhead per case, then a dashed stretch — both became
// decoration that had to be learned before it meant anything.
//
// Each phase says under its label how many steps away it is; the ACTIVE one
// says what it is doing right now instead (which preparation, which image of
// the round), because a countdown to something already running is noise. The
// Train dot doubles as a ring that fills with the step's forward/backward
// passes.
import React from "react";
import { Icon } from "../shared/Icon";
import { useT, useTn } from "./i18n";

const LINE_OFF = "var(--border)";
const RING_OFF = "var(--border-strong)";

const PREPARE_PHASES = ["", "preparing", "starting", "loading_model",
                        "caching_latents"];

/** The dot itself, and the gap to the connector on either side. Both fixed:
 *  labels and subtitles are taken out of the layout (absolutely positioned)
 *  so that a subtitle appearing, growing or clearing can never move the dots
 *  or resize the lines between them. */
const DOT = 14;
const GAP = 7;

/** Steps until a cadence-driven phase next runs (null when it has none). */
function nextIn(every: number, step: number): number | null {
  if (!every || every < 1) return null;
  const left = every - (step % every);
  return left === 0 ? every : left;
}

/** One dot with its label and subtitle. With `progress` the dot becomes a
 *  ring that fills — the training step's passes. */
function PhaseDot({ label, subtitle, state, progress, check }: {
  label: string;
  subtitle?: string;
  state: "done" | "current" | "todo";
  progress?: number;
  /** Fill the dot with a checkmark — the run reached the end. */
  check?: boolean;
}) {
  const lit = state === "current";
  const on = state !== "todo";
  return (
    <div style={{
      position: "relative", width: DOT, flex: "0 0 auto",
      display: "flex", justifyContent: "center",
    }}>
      {check ? (
        <span style={{
          width: DOT, height: DOT, borderRadius: "50%",
          display: "flex", alignItems: "center", justifyContent: "center",
          background: "var(--accent)", color: "var(--on-accent)",
        }}>
          <Icon name="check" size={11} />
        </span>
      ) : progress == null ? (
        <span style={{
          width: DOT, height: DOT, borderRadius: "50%",
          boxSizing: "border-box",
          border: `2px solid ${on ? "var(--accent)" : RING_OFF}`,
          background: lit ? "var(--accent)" : "transparent",
        }} />
      ) : (
        <svg width={DOT} height={DOT} viewBox="0 0 20 20"
             style={{ transform: "rotate(-90deg)", display: "block" }}>
          {/* The unfilled part of the ring: dim ACCENT while this is the
              phase running now, so a round that has just started ("0 / 3")
              does not read as a greyed-out, inactive dot. */}
          <circle cx="10" cy="10" r="8" fill="none"
                  stroke={lit ? "var(--accent-soft)" : RING_OFF}
                  strokeWidth="3.4" />
          <circle
            cx="10" cy="10" r="8" fill="none" stroke="var(--accent)"
            strokeWidth="3.4" strokeLinecap="round"
            strokeDasharray={
              `${Math.max(0, Math.min(1, progress)) * 50.27} 50.27`}
          />
        </svg>
      )}
      {/* Out of the flow, centred on the dot: the line's geometry is the
          dots and the connectors, nothing else. */}
      <div style={{
        position: "absolute", top: DOT + 4, left: "50%",
        transform: "translateX(-50%)", textAlign: "center",
        whiteSpace: "nowrap", pointerEvents: "none",
      }}>
        <div style={{
          fontSize: "var(--fs-1)",
          color: lit ? "var(--text)" : "var(--muted)",
          fontWeight: lit ? 600 : 500,
        }}>
          {label}
        </div>
        <div style={{
          height: 11, lineHeight: "11px", fontSize: "var(--fs-0)",
          color: lit ? "var(--accent)" : "var(--muted-3)",
          fontVariantNumeric: "tabular-nums",
        }}>
          {subtitle ?? ""}
        </div>
      </div>
    </div>
  );
}

/** The connector between two dots — a plain line. The repetition it spans is
 *  already said by the subtitles ("in 120 steps"); a dashed stretch on top of
 *  that was decoration, and the eye read it as a different KIND of link. */
function Connector({ on }: { on?: boolean }) {
  return (
    <div style={{
      flex: 1, minWidth: 24, marginTop: DOT / 2 - 1, height: 2,
      marginLeft: GAP, marginRight: GAP, borderRadius: 1,
      background: on ? "var(--accent)" : LINE_OFF,
    }} />
  );
}

export function StepPhases({ phase, note, sub, status = "",
                             showSamples = true, step = 0, totalSteps = 0,
                             ckptEvery = 0, sampleEvery = 0, valEvery = 0,
                             accum = 1 }: {
  phase: string;
  note: string;
  /** The in-step phase while training: batch | forward | backward | update. */
  sub?: string;
  status?: string;
  /** False when the job never samples — the dot is then not drawn at all. */
  showSamples?: boolean;
  step?: number;
  totalSteps?: number;
  ckptEvery?: number;
  sampleEvery?: number;
  /** The validation cadence; 0 when the run scores none. */
  valEvery?: number;
  /** Gradient-accumulation micro-batches per step, for the ring's resolution. */
  accum?: number;
}) {
  const t = useT();
  const tn = useTn();
  const done = status === "completed";
  // A job that has not started yet has no phase, which is why "" counts as
  // preparing — but so does a FINISHED one, and treating that as preparing
  // left the Train dot "not reached yet" (grey) while every other dot on a
  // completed run was accent-coloured.
  const preparing = !done && PREPARE_PHASES.includes(phase);
  const training = phase === "training";
  const stepsIn = (n: number) =>
    tn({ one: "in 1 step", other: "in {n} steps" }, n);

  // Prepare says WHICH preparation: the model load and the latent cache are
  // the long ones, and "preparing" alone leaves you watching a spinner.
  const prepSub = phase === "loading_model" ? t("loading model")
    : phase === "caching_latents"
      ? `${t("caching latents")}${note ? ` ${note}` : ""}`
      : phase && preparing ? t(phase.replace(/_/g, " ")) : "";

  // The ring is the step's progress through its forward/backward passes: the
  // trainer's note counts the images finished ("2 / 4"), which lands on a
  // micro-batch boundary, and a backward pass is half a micro-batch further
  // in. With accumulation 2 that reads 0 · ¼ · ½ · ¾ — forward, backward,
  // forward, backward — rather than a bar that only moves twice.
  const m = /^(\d+) \/ (\d+)$/.exec(note ?? "");
  const noteFrac = m && Number(m[2]) > 0 ? Number(m[1]) / Number(m[2]) : 0;
  const micros = Math.max(1, accum || 1);
  const inBackward = sub === "backward" || sub === "update";

  // The interludes, in the order they will actually happen next.
  const interludes = [
    ...(showSamples && sampleEvery > 0
      ? [{ key: "sampling", label: t("Sample"),
           left: nextIn(sampleEvery, step) ?? 0 }] : []),
    ...(ckptEvery > 0
      ? [{ key: "checkpoint", label: t("Checkpoint"),
           left: nextIn(ckptEvery, step) ?? 0 }] : []),
    ...(valEvery > 0
      ? [{ key: "validating", label: t("Validate"),
           left: nextIn(valEvery, step) ?? 0 }] : []),
  ].sort((a, b) => a.left - b.left);

  // A sample round or a checkpoint happens BETWEEN steps, so while one runs
  // the step's own passes are complete: the Train ring stays full rather than
  // dropping back to an empty outline behind the phase that interrupted it.
  const inInterlude = interludes.some((it) => it.key === phase);
  const stepProgress = training
    ? Math.min(1, noteFrac + (inBackward ? 0.5 / micros : 0))
    : inInterlude ? 1 : undefined;

  const stateOf = (mine: boolean, passed: boolean) =>
    mine ? ("current" as const) : passed ? ("done" as const) : ("todo" as const);

  return (
    <div style={{
      background: "var(--panel)", border: "1px solid var(--border)",
      // The generous sides are for the first and last dots: their labels are
      // centred on them, so half of the widest one hangs past the dot —
      // measured, that is "caching latents 162 / 162" at ~45 px.
      borderRadius: "var(--r-6)", padding: "20px 56px 38px", marginTop: 0,
      display: "flex", alignItems: "flex-start",
    }}>
      <PhaseDot label={t("Prepare")} subtitle={prepSub}
        state={stateOf(preparing && !done, true)} />
      <Connector on={!preparing || done} />
      <PhaseDot
        label={t("Train")}
        state={stateOf(training, !preparing)}
        progress={stepProgress}
      />
      {interludes.map((it, i) => (
        <React.Fragment key={it.key}>
          <Connector on={phase === it.key || done} />
          <PhaseDot
            label={it.label}
            // Nothing under a phase that is already running: a countdown to
            // it would be noise, and what a sample round has left to render
            // is in its ring.
            subtitle={phase === it.key || done ? "" : stepsIn(it.left)}
            state={stateOf(phase === it.key, done)}
            // A round renders one image at a time, so it fills a ring for
            // the same reason the training step does.
            progress={it.key === "sampling" && phase === it.key
              ? noteFrac : undefined}
          />
        </React.Fragment>
      ))}
      <Connector on={done} />
      <PhaseDot
        label={t("Done")}
        subtitle={!done && totalSteps > step
          ? stepsIn(totalSteps - step) : ""}
        state={stateOf(done, done)}
        check={done}
      />
    </div>
  );
}
