// The training-data inspector (opened from a job's "Data" button): for one
// optimizer step, the images/prompts/crops the step actually trained on. Paged
// by step (a page = one full gradient-accumulation step) with prev/next buttons
// and a low loss graph you can click or drag to scrub to any step. Each row
// shows the source thumbnail with the crop drawn on top and the flip applied in
// the browser (so no new thumbnails are stored during training), the prompt, and
// metadata chips (crop, flip, image/bucket sizes, loss).
import React, { useEffect, useMemo, useRef, useState } from "react";
import { IconButton } from "../shared/IconButton";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, TrainMetricPoint, TrainVisit } from "./api";
import { useT, useNum } from "./i18n";
import { Overlay } from "../shared/Overlay";
import { Icon } from "../shared/Icon";
import { Chip as SharedChip } from "../shared/Chip";

// GW is only the width used until the element has been measured; the graph
// tracks its real pixel width so the viewBox maps 1:1 and the axis labels are
// drawn undistorted (see the ResizeObserver below).
const GW = 720, GH = 76, GPAD = 4;
// Room under the plot for the x-axis labels, which are always shown.
const AXIS_H = 14;

// Exponential moving average, for a readable trend line over the noisy loss.
function ema(vals: number[], alpha: number): number[] {
  const out: number[] = [];
  let v = vals.length ? vals[0] : 0;
  for (const x of vals) { v = alpha * x + (1 - alpha) * v; out.push(v); }
  return out;
}

/** Round grid values across `[lo, hi]` — the 1/2/5×10ⁿ ladder, so the lines land
 *  on numbers a reader recognises. `minStep` keeps a step axis on integers. */
function gridTicks(lo: number, hi: number, count: number, minStep = 0): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [];
  const raw = span / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = Math.max(minStep, (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag);
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) out.push(v);
  return out;
}

/** A loss curve you can click OR drag to scrub steps; hovering reads out the
 *  step under the cursor, and an expand toggle grows it and adds axis labels. */
function ScrubGraph({ points, current, onPick }: {
  points: TrainMetricPoint[];
  current: number;
  onPick: (step: number) => void;
}) {
  const t = useT();
  const num = useNum();
  const [expanded, setExpanded] = useState(false);
  const [hover, setHover] = useState<{ step: number; loss: number; x: number } | null>(null);
  const dragging = useRef(false);
  const box = useRef<HTMLDivElement | null>(null);
  // The viewBox is kept at the element's real pixel width so that user units
  // are CSS pixels: the axis labels then render at their true aspect (a fixed
  // viewBox stretched to a wider box would smear the text horizontally).
  const [w, setW] = useState(GW);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(120, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const gh = expanded ? 170 : GH;
  const padB = AXIS_H;
  const usable = useMemo(
    () => points.filter((p) => typeof p.loss === "number" && isFinite(p.loss)),
    [points]
  );
  const geom = useMemo(() => {
    if (usable.length < 2) return null;
    const xs = usable.map((p) => p.step);
    const raw = usable.map((p) => p.loss);
    const smooth = ema(raw, Math.min(0.3, 2 / Math.max(10, usable.length / 20)));
    const all = raw.concat(smooth);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...all), y1 = Math.max(...all);
    const tx = (s: number) => GPAD + ((s - x0) / (x1 - x0 || 1)) * (w - 2 * GPAD);
    const ty = (v: number) => GPAD + (1 - (v - y0) / (y1 - y0 || 1)) * (gh - GPAD - padB);
    const line = (vals: number[]) => usable.map((p, i) => `${i ? "L" : "M"}${tx(p.step).toFixed(1)},${ty(vals[i]).toFixed(1)}`).join("");
    // Grid: round step values across the x range (integers), round loss values
    // across the y range. The y values are drawn as lines only — the labels
    // would crowd a graph this short, and the hover readout gives the number.
    const xt = gridTicks(x0, x1, Math.max(2, Math.round(w / 110)), 1);
    const yt = gridTicks(y0, y1, expanded ? 5 : 3);
    return { tx, ty, d: line(raw), ds: line(smooth), smooth, x0, x1, y0, y1, xt, yt };
  }, [usable, gh, padB, w, expanded]);
  if (!geom) return null;
  // The nearest recorded point to a client x (binary search — steps ascending).
  const nearest = (clientX: number, rect: DOMRect) => {
    const x = ((clientX - rect.left) / rect.width) * w;
    const step = geom.x0 + ((x - GPAD) / (w - 2 * GPAD)) * (geom.x1 - geom.x0);
    let lo = 0, hi = usable.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (usable[mid].step < step) lo = mid + 1; else hi = mid;
    }
    const prev = Math.max(0, lo - 1);
    return usable[Math.abs(usable[prev].step - step) <= Math.abs(usable[lo].step - step) ? prev : lo];
  };
  const onDown = (e: React.PointerEvent<SVGSVGElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    onPick(nearest(e.clientX, e.currentTarget.getBoundingClientRect()).step);
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const p = nearest(e.clientX, e.currentTarget.getBoundingClientRect());
    setHover({ step: p.step, loss: p.loss, x: geom.tx(p.step) });
    if (dragging.current) onPick(p.step);
  };
  const onUp = () => { dragging.current = false; };
  return (
    <div ref={box} style={{ position: "relative" }}>
      <IconButton icon={expanded ? "close_fullscreen" : "open_in_full"} size={22} glyph={13} bordered fill="panel"
        onClick={() => setExpanded((v) => !v)}
        title={expanded ? t("Collapse graph") : t("Expand graph")} style={{ position: "absolute", top: 4, right: 4, zIndex: 1 }} />
      {/* preserveAspectRatio="none": the box has a fixed pixel height but a
          full-width, so the viewBox must STRETCH to fill it rather than be
          scaled uniformly and centred (which left wide side gutters that threw
          the pointer mapping off, and made the expand animation scale
          horizontally too). Now the viewBox fills exactly, so the pointer math
          lines up and the height change animates vertically only. */}
      <svg viewBox={`0 0 ${w} ${gh}`} preserveAspectRatio="none"
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp}
        onPointerLeave={() => { setHover(null); dragging.current = false; }}
        style={{ width: "100%", height: gh, display: "block", cursor: "pointer",
          background: "var(--bg-deep)", borderRadius: "var(--r-4)", touchAction: "none",
          transition: "height 0.2s ease" }}>
        {/* Background grid. The y lines carry no labels (the hover readout says
            the loss); the x labels are always on, so the graph reads as a step
            axis even collapsed. */}
        {geom.yt.map((v) => (
          <line key={`y${v}`} x1={GPAD} x2={w - GPAD} y1={geom.ty(v)} y2={geom.ty(v)}
            stroke="var(--border)" strokeWidth={1} opacity={0.55} />
        ))}
        {geom.xt.map((s) => (
          <line key={`x${s}`} x1={geom.tx(s)} x2={geom.tx(s)} y1={GPAD} y2={gh - padB}
            stroke="var(--border)" strokeWidth={1} opacity={0.55} />
        ))}
        {geom.xt.filter((s) => geom.tx(s) >= 12 && geom.tx(s) <= w - 12).map((s) => (
          <text key={`l${s}`} x={geom.tx(s)} y={gh - 4} textAnchor="middle" fontSize={9}
            fill="var(--muted-2)" style={{ pointerEvents: "none" }}>{Math.round(s)}</text>
        ))}
        <path d={geom.d} fill="none" stroke="var(--border-strong)" strokeWidth={1} opacity={0.7} />
        <path d={geom.ds} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
        {current > 0 && (
          <line x1={geom.tx(current)} x2={geom.tx(current)} y1={0} y2={gh - padB}
            stroke="var(--text-bright)" strokeWidth={1.5} />
        )}
        {hover && (
          <>
            <line x1={hover.x} x2={hover.x} y1={0} y2={gh - padB}
              stroke="var(--muted-2)" strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={hover.x} cy={geom.ty(hover.loss)} r={2.5} fill="var(--accent)" />
          </>
        )}
      </svg>
      {hover && (
        <span style={{ position: "absolute", top: 4, left: 6,
          fontSize: "var(--fs-1)", fontFamily: "var(--mono)", color: "var(--muted)",
          background: "var(--overlay-chrome)", borderRadius: 4, padding: "0 4px", pointerEvents: "none" }}>
          {t("step")} {hover.step} · {num(hover.loss, FIX4)}
        </span>
      )}
    </div>
  );
}

/** Seconds as m:ss (or h:mm:ss) — where in the film a frame came from. */
function clockTime(t: number): string {
  const s = Math.max(0, Math.round(t));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

function Chip({ children, tone }: { children: React.ReactNode; tone?: "accent" }) {
  return <SharedChip size="sm" mono bordered tone={tone}>{children}</SharedChip>;
}

function VisitRow({ v, uid }: { v: TrainVisit; uid: string }) {
  const t = useT();
  const num = useNum();
  const crop = v.crop && v.crop.length === 4 ? v.crop : null;
  const cropped = !!crop && (crop[2] < 0.999 || crop[3] < 0.999);
  const [iw, ih] = v.img.length === 2 ? v.img : [1, 1];
  const [bw, bh] = v.bucket.length === 2 ? v.bucket : [0, 0];
  return (
    <div style={{ display: "flex", gap: 12, padding: "10px 4px", borderTop: "1px solid var(--border)" }}>
      {/* Thumbnail: the whole box is mirrored when flipped, so the crop overlay
          mirrors with the image — matching what the model actually saw. */}
      <div style={{ flex: "0 0 auto", width: 108 }}>
        <div style={{
          position: "relative", width: 108,
          aspectRatio: `${Math.max(1, iw)} / ${Math.max(1, ih)}`,
          borderRadius: "var(--r-2)", overflow: "hidden", background: "var(--panel-3)",
          border: "1px solid var(--border)",
          transform: v.flip ? "scaleX(-1)" : undefined,
        }}>
          {/* A stored picture has a thumbnail; a video frame is scratch in
              the job folder and is served from there — the frame ITSELF,
              which is the only picture of it there will ever be. An empty
              box is what is left once a finished run's frames are gone. */}
          {v.file_id != null ? (
            <img className="mc-checker" src={api.thumbUrl(v.file_id)} alt=""
              style={thumbStyle} />
          ) : v.frame ? (
            <img className="mc-checker" src={api.trainFrameUrl(uid, v.frame)}
              alt="" style={thumbStyle} />
          ) : (
            <div style={{ width: "100%", height: "100%" }} />
          )}
          {crop && (
            <div style={{
              position: "absolute",
              left: `${crop[0] * 100}%`, top: `${crop[1] * 100}%`,
              width: `${crop[2] * 100}%`, height: `${crop[3] * 100}%`,
              border: "2px solid var(--accent)", borderRadius: 2,
              boxShadow: "0 0 0 9999px var(--scrim-2)",
            }} />
          )}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontSize: "var(--fs-3)", color: "var(--text-bright)", lineHeight: 1.4, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {v.prompt || <span style={{ color: "var(--muted)" }}>{t("(empty prompt)")}</span>}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
          {/* A frame extracted from a video has no stored file and so no
              thumbnail above — the moment it came from is what names it. */}
          {typeof v.video_time === "number" && (
            <Chip tone="accent">{t("video frame")} {clockTime(v.video_time)}</Chip>
          )}
          {cropped && <Chip tone="accent">{t("cropped")}</Chip>}
          {v.flip && <Chip tone="accent">{t("flipped")}</Chip>}
          {iw > 0 && ih > 0 && <Chip>{iw}×{ih}</Chip>}
          {bw > 0 && bh > 0 && <Chip>{t("bucket")} {bw}×{bh}</Chip>}
          {typeof v.loss === "number" && <Chip>{t("loss")} {num(v.loss, FIX4)}</Chip>}
        </div>
      </div>
    </div>
  );
}

const thumbStyle: React.CSSProperties = {
  width: "100%", height: "100%", objectFit: "cover", display: "block",
};

const FIX4 = { minimumFractionDigits: 4, maximumFractionDigits: 4, useGrouping: false } as const;

export function TrainDataInspector({ uid, active, points, onClose }: {
  uid: string;
  active: boolean;
  points: TrainMetricPoint[];
  onClose: () => void;
}) {
  const t = useT();
  const num = useNum();
  // null = "latest available step"; a number selects that step.
  const [step, setStep] = useState<number | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["train-visits", uid, step],
    queryFn: () => api.trainVisits(uid, step ?? undefined),
    refetchInterval: active && step === null ? 3000 : false,
    // Keep the previous step's rows on screen while the next loads, so scrubbing
    // doesn't flash a "Loading…" / empty state on every step.
    placeholderData: keepPreviousData,
  });
  const steps = data?.steps ?? [];
  const cur = data?.step ?? 0;
  const idx = steps.indexOf(cur);
  const go = (i: number) => { if (i >= 0 && i < steps.length) setStep(steps[i]); };

  return (
    <Overlay icon="dataset" title={t("Training data")} width={860} onClose={onClose}>
      {/* Fixed height (a fraction of the window) so scrubbing between steps with
          different row counts never resizes the overlay. */}
      <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 12, height: "80vh", boxSizing: "border-box" }}>
        {/* Scrub graph — the picked step is a real recorded point, so pass it
            straight through (the backend snaps to the nearest step if needed). */}
        <ScrubGraph points={points} current={cur} onPick={setStep} />

        {/* The step's visits. */}
        {isLoading && !data ? (
          <div style={{ flex: 1, padding: 30, textAlign: "center", color: "var(--muted)", fontSize: "var(--fs-3)" }}>{t("Loading…")}</div>
        ) : steps.length === 0 ? (
          <div style={{ flex: 1, padding: 30, textAlign: "center", color: "var(--muted)", fontSize: "var(--fs-3)" }}>
            {t("No training-data records yet — they appear once the run starts stepping.")}
          </div>
        ) : (
          <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
            {(data?.visits ?? []).map((v, i) => <VisitRow key={i} v={v} uid={uid} />)}
          </div>
        )}

        {/* Step navigation lives in a footer below the (scrollable) list, so it
            stays reachable however far down the visits you are: the step being
            read on the left, the two buttons paired on the right. */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, paddingTop: 10,
          borderTop: "1px solid var(--border)" }}>
          <div style={{ flex: 1, fontSize: "var(--fs-3)", color: "var(--text-2)", fontVariantNumeric: "tabular-nums" }}>
            {t("Step")} <b style={{ color: "var(--text-bright)" }}>{cur}</b>
            {steps.length > 0 && <span style={{ color: "var(--muted)" }}> / {steps[steps.length - 1]}</span>}
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            <button onClick={() => go(idx - 1)} disabled={idx <= 0}
              title={t("Previous step")} style={navBtn(idx <= 0)}>
              <Icon name="chevron_left" size={18} />
            </button>
            <button onClick={() => go(idx + 1)} disabled={idx < 0 || idx >= steps.length - 1}
              title={t("Next step")} style={navBtn(idx < 0 || idx >= steps.length - 1)}>
              <Icon name="chevron_right" size={18} />
            </button>
          </div>
        </div>
      </div>
    </Overlay>
  );
}

function navBtn(disabled: boolean): React.CSSProperties {
  return {
    width: 30, height: 26, display: "flex", alignItems: "center", justifyContent: "center",
    borderRadius: "var(--r-3)", border: "1px solid var(--border-strong)", background: "transparent",
    color: disabled ? "var(--muted-2)" : "var(--text-2)",
    cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.5 : 1,
  };
}
