// Hand-rolled SVG loss curve (no chart library in this app): raw loss as a
// faint line, EMA-smoothed loss in accent, optional log Y, hover readout.
// The points come from the detail pane (useMetrics), which polls them.
import React, { useCallback, useMemo, useRef, useState } from "react";
import { TrainMetricPoint } from "./api";
import { useT, useNum } from "./i18n";

// THE CHART IS AS WIDE AS IT IS DRAWN, AND ITS COORDINATES SAY SO. The
// viewBox used to be a fixed 720 under `width: 100%`, which scales the whole
// drawing — so in a pane dragged to 1400 px every label, stroke and tick came
// out at twice its size, a chart blown up rather than a wider one. Measured,
// one unit is one CSS pixel at every width: the text stays 11 px, the curve
// gets the room, and the bars mode gets more bars rather than fatter ones.
// The HEIGHT is fixed on purpose — a graph that grew with the window would
// push the timeline under it off the page.
const W_DEFAULT = 720, W_MIN = 320;
const H = 220, PAD_L = 44, PAD_R = 10, PAD_T = 10, PAD_B = 22;
const BAR_MAX = 20, BAR_MIN = 1;   // bar width bounds (viewBox units ≈ points)

type Metric = "loss" | "lr" | "speed";

// THE RANGE OF A SERIES, WITHOUT SPREADING IT INTO A CALL. `Math.min(...ys)`
// is an argument per point, and past about 125,000 of them V8 answers
// `RangeError: Maximum call stack size exceeded` — which is not a chart that
// looks wrong, it is the whole Train tab on its error boundary. A tab left
// open through a long run used to get there (see `metricsWindow.ts`, which
// now keeps the array far below it); a loop costs nothing and has no ceiling.
function minOf(vals: readonly number[], fallback = 0): number {
  let m = Infinity;
  for (const v of vals) if (v < m) m = v;
  return m === Infinity ? fallback : m;
}

function maxOf(vals: readonly number[], fallback = 0): number {
  let m = -Infinity;
  for (const v of vals) if (v > m) m = v;
  return m === -Infinity ? fallback : m;
}

/** The drawn width of the box this chart sits in, in CSS pixels, and the ref
 *  to put on that box.
 *
 *  A CALLBACK REF, not an effect over a `useRef`: this chart renders a "no
 *  points yet" box first and the card only once the metrics land, so an
 *  effect that read `ref.current` on mount found null, returned, and — its
 *  dependency being the stable ref object — never ran again. The observer
 *  was then attached to nothing for the life of the pane and the width
 *  stayed at its default, which is a chart scaled up to fit rather than a
 *  wider one. A callback ref is called with the element every time one
 *  mounts, which is the question being asked. */
function useDrawnWidth(): [(el: HTMLElement | null) => void, number] {
  const [w, setW] = useState(W_DEFAULT);
  const seen = useRef<ResizeObserver | null>(null);
  const attach = useCallback((el: HTMLElement | null) => {
    seen.current?.disconnect();
    seen.current = null;
    if (!el) return;
    const read = (px: number) => setW(Math.max(W_MIN, Math.round(px)));
    read(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([e]) => read(e.contentRect.width));
    ro.observe(el);
    seen.current = ro;
  }, []);
  return [attach, w];
}

function ema(vals: number[], alpha: number): number[] {
  const out: number[] = [];
  let v = vals.length ? vals[0] : 0;
  for (const x of vals) {
    v = alpha * x + (1 - alpha) * v;
    out.push(v);
  }
  return out;
}

// Step numbers where a new pass over the dataset begins, within [x0, x1].
// Skipped when they'd be too dense to read (a run of many short epochs).
function epochBoundaries(stepsPerEpoch: number, x0: number, x1: number): { step: number; epoch: number }[] {
  if (!stepsPerEpoch || stepsPerEpoch < 1) return [];
  const first = Math.max(1, Math.ceil(x0 / stepsPerEpoch));
  const last = Math.floor(x1 / stepsPerEpoch);
  if (last < first || last - first + 1 > 40) return [];
  const out: { step: number; epoch: number }[] = [];
  for (let k = first; k <= last; k++) out.push({ step: k * stepsPerEpoch, epoch: k });
  return out;
}

export interface HoverInfo {
  step: number; loss: number; lr?: number;
  lmin?: number | null; lmax?: number | null;
  // The validation round at this step, when the run scored one.
  val?: number | null; stable?: number | null;
  // The plotted value for the current metric (loss/lr/speed).
  value?: number;
}

// The validation series' colours — NOT the accent, which the smoothed loss
// already owns, and the same on both themes by token.
const VAL_COLOR = "var(--yellow)";
const STABLE_COLOR = "var(--green)";

const FIX4 = { minimumFractionDigits: 4, maximumFractionDigits: 4, useGrouping: false } as const;

export function LossGraph({ points, diverged, stepsPerEpoch = 0, warmupSteps = 0 }: {
  /** Fetched by the detail pane — see useMetrics for why they are shared. */
  points: TrainMetricPoint[];
  diverged: number;
  /** Steps in one pass over the dataset; >0 draws faint epoch gridlines. */
  stepsPerEpoch?: number;
  /** LR warmup length; >0 shades the warmup range on the LR graph. */
  warmupSteps?: number;
}) {
  const t = useT();
  const num = useNum();
  // The card measures itself, and everything below is in ITS pixels.
  const [chart, w] = useDrawnWidth();
  const [logY, setLogY] = useState(false);
  const [bars, setBars] = useState(false);
  const [smoothOn, setSmoothOn] = useState(true);
  const [metric, setMetric] = useState<Metric>("loss");
  const [hover, setHover] = useState<number | null>(null); // point index (line mode)
  // Unified hover readout for the header, set by both the line and bars modes.
  const [hoverInfo, setHoverInfo] = useState<HoverInfo | null>(null);

  // Nothing here may assume a point has a number in it. The API can report a
  // step whose loss diverged, and older runs wrote NaN, which arrives as null
  // — `hp.loss.toFixed()` on one of those unmounted the whole app.
  const usable = useMemo(
    () => points.filter((p) => typeof p.loss === "number" && isFinite(p.loss)),
    [points]
  );
  // A run with gradient accumulation records each step's micro-batch spread
  // (min/max); only then is the bars mode meaningful.
  const hasAccum = useMemo(
    () => usable.some((p) => p.lmin != null && p.lmax != null), [usable]);
  // The plotted series for the chosen metric. Speed (steps/second) comes from
  // the wall-clock stamps: the step gap over the time gap between logged points.
  const metricVals = useMemo(() => {
    if (metric === "lr") return usable.map((p) => (isFinite(p.lr) ? p.lr : 0));
    if (metric === "speed") {
      const v = usable.map((p, i) => {
        if (i === 0) return NaN;
        const ds = p.step - usable[i - 1].step;
        const dt = p.t - usable[i - 1].t;
        return dt > 0 && ds > 0 ? ds / dt : NaN;
      });
      if (v.length > 1 && !isFinite(v[0])) v[0] = v[1];    // no gap for the first point
      return v.map((x) => (isFinite(x) ? x : 0));
    }
    return usable.map((p) => p.loss);
  }, [usable, metric]);
  // The validation rounds, where the run scored any: sparse points merged
  // onto their step's training point by the API, drawn as series of their
  // own on the loss view.
  const valSeries = useMemo(
    () => (metric === "loss" ? usable.filter((p) => p.val != null) : []),
    [usable, metric]);
  const stableSeries = useMemo(
    () => (metric === "loss" ? usable.filter((p) => p.stable != null) : []),
    [usable, metric]);
  // Bars and the ±min/max readout are loss-only. The learning rate is a known
  // schedule — smoothing it only distorts the warmup spike — so it is never
  // smoothed; loss and speed are noisy and smoothing is a toggle.
  const showBars = bars && metric === "loss";
  const useSmoothing = metric !== "lr" && smoothOn;
  const fmtY = (v: number) =>
    metric === "lr" ? v.toExponential(0)
      : v >= 100 ? v.toFixed(0) : v >= 1 ? v.toFixed(2) : v.toFixed(3);

  const geom = useMemo(() => {
    if (usable.length < 2) return null;
    const alpha = Math.min(0.3, 2 / Math.max(10, usable.length / 20));
    const smooth = ema(metricVals, alpha);
    const xs = usable.map((p) => p.step);
    // The validation lines share the Y scale, so their values must be in the
    // fit — a held-out loss sits above the training loss by nature, and a
    // scale fitted without it would push the very series off the chart.
    const ys = metricVals.concat(smooth,
      valSeries.map((p) => p.val as number),
      stableSeries.map((p) => p.stable as number));
    const yPos = ys.filter((y) => y > 0);
    // Fit the data (with a little padding) rather than forcing 0 into view — a
    // loss that hovers around 0.2 shouldn't waste four fifths of the height on
    // empty space below it.
    const dataMin = minOf(ys), dataMax = maxOf(ys);
    const pad = (dataMax - dataMin) * 0.08 || Math.abs(dataMax) * 0.08 || 0.01;
    const yMin = logY ? minOf(yPos, 0.001) : dataMin - pad;
    const yMax = logY ? dataMax : dataMax + pad;
    const x0 = minOf(xs), x1 = maxOf(xs);
    const ty = (v: number) => {
      let f: number;
      if (logY) {
        const lv = Math.log(Math.max(v, yMin));
        f = (lv - Math.log(yMin)) / (Math.log(yMax) - Math.log(yMin) || 1);
      } else {
        f = (v - yMin) / (yMax - yMin || 1);
      }
      return PAD_T + (1 - f) * (H - PAD_T - PAD_B);
    };
    const tx = (s: number) =>
      PAD_L + ((s - x0) / (x1 - x0 || 1)) * (w - PAD_L - PAD_R);
    const path = (vals: number[]) =>
      usable.map((p, i) => `${i ? "L" : "M"}${tx(p.step).toFixed(1)},${ty(vals[i]).toFixed(1)}`).join("");
    // ~4 horizontal gridlines at round loss values.
    const grid: number[] = [];
    for (let i = 0; i <= 3; i++) {
      grid.push(logY
        ? Math.exp(Math.log(yMin) + (i / 3) * (Math.log(yMax) - Math.log(yMin)))
        : yMin + (i / 3) * (yMax - yMin));
    }
    // Vertical gridlines at ROUND steps (1/2/5 × 10^k), aiming for one line
    // every ~90 px — the eye needs step landmarks between the two corner
    // labels once a run is thousands of steps wide.
    const xGrid: number[] = [];
    const span = x1 - x0;
    if (span > 0) {
      const target = span / ((w - PAD_L - PAD_R) / 90);
      const mag = Math.pow(10, Math.floor(Math.log10(target)));
      const tick = [1, 2, 5, 10].map((m) => m * mag)
        .find((tk) => tk >= target) ?? 10 * mag;
      for (let v = Math.ceil(x0 / tick) * tick; v <= x1; v += tick) {
        // The corner labels already mark the ends; a line on top just
        // doubles ink.
        if (v > x0 + span * 0.03 && v < x1 - span * 0.03) xGrid.push(v);
      }
    }
    return { smooth, tx, ty, path, grid, xGrid, x0, x1 };
  }, [usable, metricVals, valSeries, stableSeries, logY, w]);

  // The two polylines do not depend on the hover, so they are built once per
  // data change rather than per mouse move. Measured at 6400 points: 2.8 ms
  // to build each string and 4.5 ms for the browser to re-parse and
  // re-rasterise it — ~14 ms of work per move, for two paths that came out
  // identical every time. Memoized, React leaves the `d` attributes alone and
  // a move only moves the crosshair. (Above the early return below: hooks
  // cannot sit after one.)
  const rawPath = useMemo(
    () => (geom ? geom.path(metricVals) : ""), [geom, metricVals]);
  const smoothPath = useMemo(
    () => (geom ? geom.path(geom.smooth) : ""), [geom]);
  // The validation lines, memoized with the other two paths. Sparse by
  // nature (one point per cadence), so each point also gets a dot below —
  // a two-point "line" is otherwise barely visible.
  const seriesPath = (pts: TrainMetricPoint[], get: (p: TrainMetricPoint) => number) =>
    pts.map((p, i) =>
      `${i ? "L" : "M"}${geom!.tx(p.step).toFixed(1)},${geom!.ty(get(p)).toFixed(1)}`)
      .join("");
  const valPath = useMemo(
    () => (geom && valSeries.length ? seriesPath(valSeries, (p) => p.val as number) : ""),
    [geom, valSeries]);  // eslint-disable-line react-hooks/exhaustive-deps
  const stablePath = useMemo(
    () => (geom && stableSeries.length ? seriesPath(stableSeries, (p) => p.stable as number) : ""),
    [geom, stableSeries]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!geom) {
    return (
      <div style={{
        height: 120, display: "flex", alignItems: "center",
        justifyContent: "center", color: "var(--muted)", fontSize: "var(--fs-3)",
        background: "var(--panel)", border: "1px solid var(--border)",
        borderRadius: "var(--r-7)",
      }}>
        {diverged > 0 && usable.length < 2
          ? t("No usable loss was recorded — the run diverged (NaN).")
          : t("Loss appears here once training starts.")}
      </div>
    );
  }

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * w;
    const step = geom.x0 + ((x - PAD_L) / (w - PAD_L - PAD_R)) * (geom.x1 - geom.x0);
    // Binary search: the steps are ascending, and a linear scan of a long
    // run's points ran on every mouse move.
    let lo = 0, hi = usable.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (usable[mid].step < step) lo = mid + 1; else hi = mid;
    }
    const prev = Math.max(0, lo - 1);
    const i = Math.abs(usable[prev].step - step) <= Math.abs(usable[lo].step - step) ? prev : lo;
    setHover(i);
    const p = usable[i];
    setHoverInfo({ step: p.step, loss: p.loss, lr: p.lr, lmin: p.lmin, lmax: p.lmax,
      val: p.val, stable: p.stable, value: metricVals[i] });
  };
  const onLeave = () => { setHover(null); setHoverInfo(null); };

  const hp = hover != null ? usable[hover] : null;
  const epochs = epochBoundaries(stepsPerEpoch, geom.x0, geom.x1);

  return (
    <div style={{
      background: "var(--panel)", border: "1px solid var(--border)",
      borderRadius: "var(--r-7)", padding: "10px 12px 6px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        {/* Which series is plotted. */}
        <div style={{ display: "flex", border: "1px solid var(--border-strong)", borderRadius: "var(--r-3)", overflow: "hidden" }}>
          {([["loss", t("Loss")], ["lr", t("LR")], ["speed", t("Speed")]] as const).map(([m, label]) => (
            <button key={m} onClick={() => setMetric(m)}
              style={{
                height: 24, padding: "0 9px", border: "none", cursor: "pointer",
                background: metric === m ? "var(--accent)" : "transparent",
                color: metric === m ? "var(--on-accent)" : "var(--text-2)",
                fontSize: "var(--fs-1)", fontWeight: 600, fontFamily: "inherit",
              }}>
              {label}
            </button>
          ))}
        </div>
        {hoverInfo && (
          <span style={{ fontSize: "var(--fs-2)", color: "var(--muted)", fontVariantNumeric: "tabular-nums" }}>
            {t("step")} {hoverInfo.step} · {
              metric === "lr" ? `lr ${(hoverInfo.value ?? 0).toExponential(2)}`
              : metric === "speed" ? `${(hoverInfo.value ?? 0).toFixed(2)} ${t("steps/s")}`
              : num(hoverInfo.loss, FIX4)}
            {metric === "loss" && hoverInfo.lmin != null && hoverInfo.lmax != null &&
              ` (${hoverInfo.lmin.toFixed(3)} - ${hoverInfo.lmax.toFixed(3)})`}
            {metric === "loss" && hoverInfo.val != null &&
              ` · ${t("val")} ${hoverInfo.val.toFixed(4)}`}
            {metric === "loss" && hoverInfo.stable != null &&
              ` · ${t("stable")} ${hoverInfo.stable.toFixed(4)}`}
            {metric === "loss" && hoverInfo.lr != null && hoverInfo.lr > 0 && ` · lr ${hoverInfo.lr.toExponential(1)}`}
          </span>
        )}
        {/* A quiet legend, only once the run actually has the series — the
            two extra lines are otherwise unexplained colours. */}
        {metric === "loss" && !hoverInfo && (valSeries.length > 0 || stableSeries.length > 0) && (
          <span style={{ fontSize: "var(--fs-1)", color: "var(--muted)", display: "inline-flex",
            alignItems: "center", gap: 10 }}>
            {valSeries.length > 0 && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 12, height: 2, background: VAL_COLOR, borderRadius: 1 }} />
                {t("validation")}
              </span>
            )}
            {stableSeries.length > 0 && (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 12, height: 2, background: STABLE_COLOR, borderRadius: 1 }} />
                {t("stable")}
              </span>
            )}
          </span>
        )}
        <div style={{ flex: 1 }} />
        {/* Smoothing toggle — meaningful only for the noisy series. */}
        {metric !== "lr" && !showBars && (
          <button
            onClick={() => setSmoothOn((v) => !v)}
            title={t("Smooth the line (EMA)")}
            style={{
              height: 24, padding: "0 10px", borderRadius: "var(--r-3)",
              border: "1px solid var(--border-strong)",
              background: smoothOn ? "var(--border)" : "transparent",
              color: "var(--text-2)", fontSize: "var(--fs-1)", cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            {t("smooth")}
          </button>
        )}
        {hasAccum && metric === "loss" && (
          <button
            onClick={() => setBars((v) => !v)}
            title={t("Show each step's min/max micro-batch loss")}
            style={{
              height: 24, padding: "0 10px", borderRadius: "var(--r-3)",
              border: "1px solid var(--border-strong)",
              background: bars ? "var(--border)" : "transparent",
              color: "var(--text-2)", fontSize: "var(--fs-1)", cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            {t("bars")}
          </button>
        )}
        <button
          onClick={() => setLogY((v) => !v)}
          style={{
            height: 24, padding: "0 10px", borderRadius: "var(--r-3)",
            border: "1px solid var(--border-strong)",
            background: logY ? "var(--border)" : "transparent",
            color: "var(--text-2)", fontSize: "var(--fs-1)", cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          log
        </button>
      </div>
      {/* THE MEASURED BOX IS THE CHART'S OWN, not the card's: the card has
          padding, and a viewBox a padding wider than the picture it holds is
          the whole drawing scaled by that much. */}
      <div ref={chart}>
      {showBars ? (
        <BarsView usable={usable} logY={logY} stepsPerEpoch={stepsPerEpoch}
          w={w} onHover={setHoverInfo} onLeave={() => setHoverInfo(null)} />
      ) : (
      <svg
        viewBox={`0 0 ${w} ${H}`}
        style={{ width: "100%", height: "auto", display: "block" }}
        onMouseMove={onMove}
        onMouseLeave={onLeave}
      >
        {/* Learning-rate warmup range: the ramp-up over the first N steps,
            shaded and labelled so it isn't mistaken for the run misbehaving. */}
        {metric === "lr" && warmupSteps > geom.x0 && (
          <g>
            <rect x={geom.tx(geom.x0)} y={PAD_T}
              width={Math.max(0, geom.tx(Math.min(warmupSteps, geom.x1)) - geom.tx(geom.x0))}
              height={H - PAD_T - PAD_B} fill="var(--accent)" opacity={0.1} />
            <line x1={geom.tx(warmupSteps)} x2={geom.tx(warmupSteps)} y1={PAD_T} y2={H - PAD_B}
              stroke="var(--accent)" strokeWidth={1} strokeDasharray="3 3" opacity={0.5} />
            <text x={geom.tx(geom.x0) + 4} y={PAD_T + 9} fontSize={9} fill="var(--accent)">
              {t("warmup")}
            </text>
          </g>
        )}
        {/* Epoch boundaries (one pass over the dataset). */}
        {epochs.map((e) => (
          <g key={`ep${e.epoch}`}>
            <line x1={geom.tx(e.step)} x2={geom.tx(e.step)} y1={PAD_T} y2={H - PAD_B}
              stroke="var(--accent)" strokeWidth={1} strokeDasharray="2 3" opacity={0.35} />
          </g>
        ))}
        {geom.grid.map((v, i) => (
          <g key={i}>
            <line x1={PAD_L} x2={w - PAD_R} y1={geom.ty(v)} y2={geom.ty(v)}
              stroke="var(--border-soft)" strokeWidth={1} />
            <text x={PAD_L - 6} y={geom.ty(v) + 3} textAnchor="end"
              fontSize={9} fill="var(--muted-2)">
              {fmtY(v)}
            </text>
          </g>
        ))}
        {geom.xGrid.map((v) => (
          <g key={`x${v}`}>
            <line x1={geom.tx(v)} x2={geom.tx(v)} y1={PAD_T} y2={H - PAD_B}
              stroke="var(--border-soft)" strokeWidth={1} />
            <text x={geom.tx(v)} y={H - 6} textAnchor="middle"
              fontSize={9} fill="var(--muted-2)">
              {v}
            </text>
          </g>
        ))}
        <text x={PAD_L} y={H - 6} fontSize={9} fill="var(--muted-2)">{geom.x0}</text>
        <text x={w - PAD_R} y={H - 6} fontSize={9} fill="var(--muted-2)"
          textAnchor="end">{geom.x1}</text>
        {/* With smoothing the raw series is a faint backdrop to the accent
            EMA; without it (or on the LR schedule) the raw series IS the line. */}
        <path d={rawPath} fill="none"
          stroke={useSmoothing ? "var(--border-strong)" : "var(--accent)"}
          strokeWidth={useSmoothing ? 1 : 1.8} opacity={useSmoothing ? 0.8 : 1} />
        {useSmoothing && (
          <path d={smoothPath} fill="none" stroke="var(--accent)" strokeWidth={1.8} />
        )}
        {/* The validation rounds: sparse lines with a dot per round, so a
            young run's one or two points are still visible. */}
        {valPath && (
          <g>
            <path d={valPath} fill="none" stroke={VAL_COLOR} strokeWidth={1.6} />
            {valSeries.length <= 200 && valSeries.map((p) => (
              <circle key={`v${p.step}`} cx={geom.tx(p.step)}
                cy={geom.ty(p.val as number)} r={2.2} fill={VAL_COLOR} />
            ))}
          </g>
        )}
        {stablePath && (
          <g>
            <path d={stablePath} fill="none" stroke={STABLE_COLOR} strokeWidth={1.6} />
            {stableSeries.length <= 200 && stableSeries.map((p) => (
              <circle key={`s${p.step}`} cx={geom.tx(p.step)}
                cy={geom.ty(p.stable as number)} r={2.2} fill={STABLE_COLOR} />
            ))}
          </g>
        )}
        {hp && (
          <>
            <line x1={geom.tx(hp.step)} x2={geom.tx(hp.step)}
              y1={PAD_T} y2={H - PAD_B}
              stroke="var(--muted-2)" strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={geom.tx(hp.step)}
              cy={geom.ty(useSmoothing ? geom.smooth[hover!] : metricVals[hover!])}
              r={3} fill="var(--accent)" />
          </>
        )}
      </svg>
      )}
      </div>
    </div>
  );
}

/**
 * Gradient-accumulation "bars" mode: one vertical bar per step from its
 * micro-batch min to max loss (with a tick at the step mean). Bars are 20 units
 * wide and shrink to a 1-unit floor; once even 1-unit bars don't fit the whole
 * run, a window is shown and a range slider below the axis moves it (drag the
 * body) or zooms it (drag either tip).
 */
function BarsView({ usable, logY, stepsPerEpoch = 0, w, onHover, onLeave }: {
  usable: TrainMetricPoint[];
  logY: boolean;
  stepsPerEpoch?: number;
  /** The chart's drawn width in pixels, measured by the card around it — so
   *  a wider pane shows MORE BARS rather than wider ones. */
  w: number;
  onHover?: (h: HoverInfo) => void;
  onLeave?: () => void;
}) {
  const innerW = w - PAD_L - PAD_R;
  const total = usable.length;
  const needsWindow = total > innerW;
  const minCount = Math.max(2, Math.ceil(innerW / BAR_MAX)); // deepest zoom
  const [win, setWin] = useState<[number, number]>(
    () => needsWindow ? [total - Math.floor(innerW), total - 1] : [0, total - 1]);
  const [hoverI, setHoverI] = useState<number | null>(null); // index within the window
  // Keep the window inside the data as the run grows.
  const a = needsWindow ? Math.max(0, Math.min(win[0], total - minCount)) : 0;
  const b = needsWindow ? Math.max(a + minCount - 1, Math.min(win[1], total - 1)) : total - 1;
  const count = b - a + 1;
  const barW = Math.max(BAR_MIN, Math.min(BAR_MAX, innerW / count));
  const view = usable.slice(a, b + 1);
  const epochs = epochBoundaries(stepsPerEpoch, usable[a].step, usable[b].step);
  const tx = (s: number) => PAD_L + ((s - usable[a].step) / ((usable[b].step - usable[a].step) || 1)) * (count * barW);

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * w;
    const i = Math.min(count - 1, Math.max(0, Math.floor((x - PAD_L) / barW)));
    setHoverI(i);
    const p = view[i];
    if (p) onHover?.({ step: p.step, loss: p.loss, lr: p.lr, lmin: p.lmin, lmax: p.lmax });
  };
  const leave = () => { setHoverI(null); onLeave?.(); };

  const lows = view.map((p) => (p.lmin ?? p.loss));
  const highs = view.map((p) => (p.lmax ?? p.loss));
  const posLows = lows.filter((v) => v > 0);
  // Fit the visible bars, not 0..max.
  const loMin = minOf(lows), hiMax = maxOf(highs);
  const pad = (hiMax - loMin) * 0.08 || 0.01;
  const yMin = logY ? minOf(posLows, 1e-3) : loMin - pad;
  const yMax = logY ? hiMax : hiMax + pad;
  const ty = (v: number) => {
    let f: number;
    if (logY) {
      const lv = Math.log(Math.max(v, yMin));
      f = (lv - Math.log(yMin)) / (Math.log(yMax) - Math.log(yMin) || 1);
    } else f = (v - yMin) / (yMax - yMin || 1);
    return PAD_T + (1 - f) * (H - PAD_T - PAD_B);
  };
  const barX = (i: number) => PAD_L + i * barW; // i is index within the window

  // gridlines
  const grid: number[] = [];
  for (let i = 0; i <= 3; i++) grid.push(logY
    ? Math.exp(Math.log(yMin) + (i / 3) * (Math.log(yMax) - Math.log(yMin)))
    : yMin + (i / 3) * (yMax - yMin));

  return (
    <>
      <svg viewBox={`0 0 ${w} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}
        onMouseMove={onMove} onMouseLeave={leave}>
        {grid.map((v, i) => (
          <g key={i}>
            <line x1={PAD_L} x2={w - PAD_R} y1={ty(v)} y2={ty(v)} stroke="var(--border-soft)" strokeWidth={1} />
            <text x={PAD_L - 6} y={ty(v) + 3} textAnchor="end" fontSize={9} fill="var(--muted-2)">
              {v >= 100 ? v.toFixed(0) : v >= 1 ? v.toFixed(2) : v.toFixed(3)}
            </text>
          </g>
        ))}
        {/* Epoch boundaries. */}
        {epochs.map((e) => (
          <line key={`ep${e.epoch}`} x1={tx(e.step)} x2={tx(e.step)} y1={PAD_T} y2={H - PAD_B}
            stroke="var(--accent)" strokeWidth={1} strokeDasharray="2 3" opacity={0.35} />
        ))}
        {view.map((p, i) => {
          const x = barX(i) + barW / 2;
          const yHi = ty(p.lmax ?? p.loss), yLo = ty(p.lmin ?? p.loss);
          const w = Math.max(0.6, barW * 0.7);
          const on = hoverI === i;
          return (
            <g key={p.step}>
              <line x1={x} x2={x} y1={yHi} y2={yLo} stroke="var(--accent)"
                strokeWidth={Math.min(w, 3)} opacity={on ? 0.95 : 0.55} />
              <line x1={x - w / 2} x2={x + w / 2} y1={ty(p.loss)} y2={ty(p.loss)}
                stroke="var(--accent)" strokeWidth={1.4} />
            </g>
          );
        })}
        <text x={PAD_L} y={H - 6} fontSize={9} fill="var(--muted-2)">{usable[a].step}</text>
        <text x={w - PAD_R} y={H - 6} fontSize={9} fill="var(--muted-2)" textAnchor="end">{usable[b].step}</text>
      </svg>
      {needsWindow && (
        <RangeSlider total={total} a={a} b={b} minCount={minCount}
          onChange={(na, nb) => setWin([na, nb])} />
      )}
    </>
  );
}

/** A minimap scrollbar under the bars: a window rect with two resize tips over
 *  the full step range. Drag the body to pan, a tip to zoom. */
function RangeSlider({ total, a, b, minCount, onChange }: {
  total: number; a: number; b: number; minCount: number;
  onChange: (a: number, b: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{ mode: "body" | "l" | "r"; x: number; a: number; b: number } | null>(null);
  const idxAt = (clientX: number) => {
    const el = ref.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    return Math.round(((clientX - r.left) / r.width) * (total - 1));
  };
  const onDown = (mode: "body" | "l" | "r") => (e: React.PointerEvent) => {
    e.preventDefault();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { mode, x: e.clientX, a, b };
  };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const dIdx = Math.round(((e.clientX - d.x) / r.width) * (total - 1));
    let na = d.a, nb = d.b;
    if (d.mode === "body") {
      const span = d.b - d.a;
      na = Math.max(0, Math.min(d.a + dIdx, total - 1 - span));
      nb = na + span;
    } else if (d.mode === "l") {
      na = Math.max(0, Math.min(d.a + dIdx, d.b - minCount + 1));
    } else {
      nb = Math.min(total - 1, Math.max(d.b + dIdx, d.a + minCount - 1));
    }
    onChange(na, nb);
  };
  const end = () => { drag.current = null; };
  const pct = (i: number) => `${(i / (total - 1)) * 100}%`;
  const left = (a / (total - 1)) * 100;
  const width = ((b - a) / (total - 1)) * 100;
  return (
    <div ref={ref} onPointerMove={onMove} onPointerUp={end} onPointerCancel={end}
      style={{ position: "relative", height: 16, margin: "6px 10px 2px",
        background: "var(--bg-deep)", borderRadius: "var(--r-1)", touchAction: "none" }}>
      <div onPointerDown={onDown("body")}
        style={{ position: "absolute", top: 0, bottom: 0, left: `${left}%`, width: `${width}%`,
          minWidth: 10, background: "var(--accent-dim)", border: "1px solid var(--accent)",
          borderRadius: "var(--r-1)", cursor: "grab" }} />
      <div onPointerDown={onDown("l")}
        style={{ position: "absolute", top: -1, bottom: -1, left: pct(a), width: 8, marginLeft: -4,
          cursor: "ew-resize" }}>
        <div style={{ width: 3, height: "100%", margin: "0 auto", background: "var(--accent)", borderRadius: 2 }} />
      </div>
      <div onPointerDown={onDown("r")}
        style={{ position: "absolute", top: -1, bottom: -1, left: pct(b), width: 8, marginLeft: -4,
          cursor: "ew-resize" }}>
        <div style={{ width: 3, height: "100%", margin: "0 auto", background: "var(--accent)", borderRadius: 2 }} />
      </div>
    </div>
  );
}
