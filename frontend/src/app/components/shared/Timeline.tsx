/**
 * THE TIMELINE CHROME BOTH FILM WINDOWS SHARE: the horizontal scale.
 *
 * The video editor grew a real timeline first — a scrolling, zoomable track
 * with a ruler above it and a view bar saying which stretch of the film is on
 * screen — and the annotator then needed exactly the same thing under its own
 * lanes. The two windows sit over the same file, and a ruler that stepped in
 * different numbers or a zoom that answered a different wheel in one of them
 * would be one feature wearing two behaviours, which is the rule the transport
 * already follows.
 *
 * So the SCALE lives here — how many pixels a second is, where the view is,
 * what a client x means in film time, the ruler, the view bar, the marked
 * range's lane and the playhead — and each window supplies only what it draws
 * on it: pieces of a cutlist, or a tag's stretches.
 *
 * `useTimeline` keeps the scale in a REF as well as in state, and every zoom
 * reads and writes that ref. A wheel fires dozens of times a second and a
 * button gets clicked three times in a row, both far faster than React
 * re-renders: reading the rendered value, each of those events computed its new
 * scale from the SAME stale one, so three clicks zoomed once and a trackpad
 * flick barely moved at all.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { rulerLabel, rulerStep, rulerTicks } from "../../timelineRuler";
import { Icon } from "../../../shared/Icon";
import { useWheel } from "../../useWheel";

/** The ruler's height, and the marked range's own lane under it. */
export const RULER_H = 16;
export const RANGE_H = 12;
/** The height of the strip that says which part of the video is on screen. */
export const VIEW_BAR_H = 11;
/** How near an edge a press counts as a resize rather than a move. */
export const EDGE_PX = 7;
/** Travel before a press on a block becomes a drag rather than a click. */
export const SLOP_PX = 3;
/** How near a neighbour's edge (or the playhead) a dragged block jumps onto
 *  it. In PIXELS, because that is the tolerance a hand has — in seconds it
 *  would mean something different at every zoom. */
export const SNAP_PX = 7;

const MIN_PX_PER_SEC = 0.2;
/** Far enough in that a single FRAME is comfortably wide — 4000 px/s is 133 px
 *  a frame at 30 fps, which is what makes a per-frame ruler (and a trim aimed
 *  at one) reachable. At the old 800 the finest mark the ladder could offer
 *  was every fifth frame. */
const MAX_PX_PER_SEC = 4000;
/** The shortest stretch the view bar will squeeze down to. Below this the
 *  block is too small to take hold of again. */
const MIN_VIEW = 0.25;

export interface Timeline {
  /** Put this on the scrolling element, with `onScroll`. The wheel is bound
   *  to the same element by `useTimeline` itself (see the handler). */
  scroller: React.RefObject<HTMLDivElement>;
  onScroll: React.UIEventHandler<HTMLElement>;
  /** The scroller's own width, and the width the content needs at this scale. */
  viewW: number;
  contentW: number;
  pxPerSec: number;
  scrollX: number;
  /** Film time → x in the content's own coordinates. */
  xOf: (at: number) => number;
  /** A client x → the film time under it. */
  timeAt: (clientX: number) => number;
  zoomBy: (factor: number, anchorClientX?: number) => void;
  setView: (from: number, to: number, zoom: boolean) => void;
  fit: () => void;
  /** The ruler's marks and how far apart they are, memoized. */
  ticks: number[];
  step: number;
  /** The film's frame rate, so the ruler can count in frames when the zoom
   *  is fine enough to show them. */
  fps: number;
}

/**
 * The scale, the scroll and the zoom for one timeline.
 *
 * `fitKey` is what a fresh fit hangs on — the file, normally. It starts fitted
 * and re-fits when that changes, but NEVER once somebody has zoomed: a scale
 * reset by a re-render is a scale nobody can hold on to.
 */
export function useTimeline(
  duration: number, fitKey: string, time: number, playing?: boolean,
  fps = 0,
): Timeline {
  const scroller = useRef<HTMLDivElement>(null);
  const [viewW, setViewW] = useState(0);
  const [pxPerSec, setPxPerSec] = useState(0);
  const [scrollX, setScrollX] = useState(0);
  const contentW = Math.max(viewW, duration * pxPerSec);
  // Read by the zoom, which runs from an event rather than from a render.
  const timeRef = useRef(time);
  timeRef.current = time;
  const pxRef = useRef(pxPerSec);
  pxRef.current = pxPerSec;

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setViewW(el.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fitted = useRef("");
  useEffect(() => {
    if (viewW <= 0 || duration <= 0 || fitted.current === fitKey) return;
    fitted.current = fitKey;
    setPxPerSec(Math.max(MIN_PX_PER_SEC, (viewW - 2) / duration));
  }, [viewW, duration, fitKey]);

  const xOf = useCallback((at: number) => at * pxPerSec, [pxPerSec]);
  const timeAt = useCallback((clientX: number) => {
    const el = scroller.current;
    if (!el || pxPerSec <= 0) return 0;
    const r = el.getBoundingClientRect();
    return Math.max(0, (clientX - r.left + el.scrollLeft) / pxPerSec);
  }, [pxPerSec]);

  /** Rescale by a factor, holding whatever is under `anchorClientX` (or the
   *  playhead) where it is — a zoom that jumps somewhere else is a zoom you
   *  have to find your place after. */
  const zoomBy = useCallback((factor: number, anchorClientX?: number) => {
    const el = scroller.current;
    const was = pxRef.current;
    const to = Math.max(MIN_PX_PER_SEC, Math.min(MAX_PX_PER_SEC, was * factor));
    pxRef.current = to;
    setPxPerSec(to);
    if (!el || was <= 0) return;
    const r = el.getBoundingClientRect();
    const offset = anchorClientX != null
      ? anchorClientX - r.left
      : Math.min(el.clientWidth / 2, timeRef.current * was - el.scrollLeft);
    const at = (offset + el.scrollLeft) / was;
    requestAnimationFrame(() => {
      if (scroller.current) scroller.current.scrollLeft = at * to - offset;
    });
  }, []);

  /** Show exactly `[from, to)` — what the view bar drags. A PAN keeps the
   *  scale it already has rather than recomputing it from the length, or a
   *  drag along the bar would creep the zoom by a rounding error per frame. */
  const setView = useCallback((from: number, to: number, zoom: boolean) => {
    const el = scroller.current;
    if (!el || viewW <= 0) return;
    let px = pxRef.current;
    if (zoom) {
      px = Math.max(MIN_PX_PER_SEC,
                    Math.min(MAX_PX_PER_SEC, viewW / Math.max(0.05, to - from)));
      pxRef.current = px;
      setPxPerSec(px);
    }
    const left = Math.max(0, from * px);
    el.scrollLeft = left;
    setScrollX(left);
  }, [viewW]);

  const fit = useCallback(() => {
    if (duration <= 0 || viewW <= 0) return;
    const to = Math.max(MIN_PX_PER_SEC, (viewW - 2) / duration);
    pxRef.current = to;
    setPxPerSec(to);
    if (scroller.current) scroller.current.scrollLeft = 0;
  }, [duration, viewW]);

  // Keep the playhead in view while it runs — at any zoom past "the whole
  // film fits" it leaves the window within seconds otherwise.
  useEffect(() => {
    const el = scroller.current;
    if (!el || !playing || pxPerSec <= 0) return;
    const x = time * pxPerSec;
    const pad = 40;
    if (x < el.scrollLeft + pad) el.scrollLeft = Math.max(0, x - pad);
    else if (x > el.scrollLeft + el.clientWidth - pad)
      el.scrollLeft = x - el.clientWidth + pad;
  }, [time, playing, pxPerSec]);

  const step = rulerStep(pxPerSec, 64, fps);
  // THE VISIBLE STRETCH, not the whole film. `rulerTicks` caps its count as a
  // backstop against a runaway, and asked for the whole duration at a fine
  // step it keeps the first 400 — so a zoomed-in film had a ruler that
  // stopped partway along and left the rest unnumbered. One step of margin
  // either side, so a mark is never missing at the edge mid-scroll.
  const from = pxPerSec > 0 ? scrollX / pxPerSec : 0;
  const to = pxPerSec > 0 ? (scrollX + viewW) / pxPerSec : duration;
  const ticks = useMemo(
    () => rulerTicks(Math.max(0, from - step),
                     Math.min(duration, to + step), step),
    [from, to, duration, step]);

  const onScroll: React.UIEventHandler<HTMLElement> = (e) =>
    setScrollX((e.target as HTMLElement).scrollLeft);

  // BOUND NATIVELY, because this handler has a `preventDefault` to make and
  // React's own `wheel` listener is passive — for as long as the zoom branch
  // below has existed, Firefox zoomed the whole PAGE on top of it. `useWheel`
  // is that rule. A plain wheel still falls through to the browser, which is
  // what scrolls the stack of tracks.
  useWheel(scroller, (e) => {
    // The modifier is what every timeline uses for this, and without it a
    // trackpad's horizontal scroll would fight the zoom.
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX);
      return;
    }
    const el = scroller.current;
    if (!el) return;
    // A VERTICAL WHEEL OVER A STACK THAT SCROLLS SCROLLS THE STACK, and this
    // handler stays out of it. The scroller is `overflow-y: auto`, so the
    // browser is already scrolling it — reading `deltaY` as "pan sideways" as
    // well made one gesture do both, and paging down through the annotator's
    // tag tracks slid the film out from under them. Where there is nothing to
    // scroll vertically (the cut track, one row deep) a plain wheel is the
    // only way to pan, so it goes on meaning that.
    const canScrollY = el.scrollHeight > el.clientHeight + 1;
    if (canScrollY && Math.abs(e.deltaY) >= Math.abs(e.deltaX)) return;
    // A trackpad's sideways flick, and a plain wheel where there is nothing to
    // scroll vertically anyway.
    const by = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    if (!by) return;
    el.scrollLeft += by;
  });

  return { scroller, onScroll, viewW, contentW, pxPerSec, scrollX,
           xOf, timeAt, zoomBy, setView, fit, ticks, step, fps };
}

/** The scale's three buttons. */
export function ZoomButtons({ tl, t }: {
  tl: Timeline; t: (s: string) => string;
}) {
  const btn = (icon: string, title: string, onClick: () => void) => (
    <button
      onClick={onClick} title={title}
      style={{ width: 24, height: VIEW_BAR_H + 6, borderRadius: "var(--r-2)",
        border: "1px solid var(--border-strong)", background: "transparent",
        color: "var(--text-2)", cursor: "pointer", display: "flex",
        alignItems: "center", justifyContent: "center", flex: "0 0 auto" }}
    >
      <Icon name={icon} size={15} />
    </button>
  );
  return (
    <>
      {btn("remove", t("Zoom out"), () => tl.zoomBy(1 / 1.6))}
      {btn("add", t("Zoom in"), () => tl.zoomBy(1.6))}
      {btn("fit_screen", t("Fit the whole video"), tl.fit)}
    </>
  );
}

/**
 * THE SCALE, AS ONE ROW: the zoom buttons and then the view bar they change.
 *
 * They were a row apart — the buttons over a line of hint text, the bar under
 * them — which put two controls for one thing in two places and spent a whole
 * row on a sentence. What the sentence said (drag a block, drag its edges)
 * every one of those blocks now says by having a grip on it, and the two
 * gestures are the first thing anybody tries anyway.
 *
 * `extra` is what a window puts after the bar (the cut track's Remove).
 */
export function ScaleRow({ tl, total, time, extra, t }: {
  tl: Timeline;
  /** The film's length as the caller counts it — the EDIT's, in the cut
   *  track, which is not the source's. */
  total: number;
  time: number;
  extra?: React.ReactNode;
  t: (s: string) => string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <ZoomButtons tl={tl} t={t} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <ViewRange
          total={total}
          from={tl.pxPerSec > 0 ? tl.scrollX / tl.pxPerSec : 0}
          to={tl.pxPerSec > 0 ? (tl.scrollX + tl.viewW) / tl.pxPerSec : total}
          time={time}
          onView={tl.setView}
          t={t}
        />
      </div>
      {extra}
    </div>
  );
}

/** A moment worth marking on the ruler — a frame somebody kept. */
export interface RulerMark {
  key: string;
  at: number;
  title: string;
  onClick?: () => void;
}

/** The numbers along the top, and the strip you scrub on. */
export function TimelineRuler({ tl, onScrub, marks = [] }: {
  tl: Timeline;
  /** A press anywhere on it: the caller arms its own scrub. */
  onScrub: (e: React.MouseEvent) => void;
  /** Moments drawn ON the ruler rather than on a row of their own. A still is
   *  a POSITION in the film, which is what the ruler is already about; a
   *  strip to itself spent a row saying so and put the marks a row away from
   *  the numbers naming them. */
  marks?: RulerMark[];
}) {
  return (
    <div
      onMouseDown={onScrub}
      style={{ position: "absolute", left: 0, top: 0, width: "100%",
        height: RULER_H, cursor: "pointer",
        borderBottom: "1px solid var(--border)" }}
    >
      {tl.ticks.map((at) => (
        <div key={at} style={{ position: "absolute", left: tl.xOf(at), top: 0,
          height: "100%", borderLeft: "1px solid var(--border-strong)",
          paddingLeft: 3, display: "flex", alignItems: "center",
          pointerEvents: "none" }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-0)",
            color: "var(--muted-2)", whiteSpace: "nowrap" }}>
            {rulerLabel(at, tl.step, tl.fps)}
          </span>
        </div>
      ))}
      {marks.map((m) => (
        <div
          key={m.key}
          onMouseDown={(e) => { e.stopPropagation(); m.onClick?.(); }}
          title={m.title}
          // The BOTTOM half of the ruler: the numbers live in the top half, so
          // a full-height mark would strike through whichever label it landed
          // on.
          style={{ position: "absolute", left: tl.xOf(m.at) - 1, bottom: 0,
            width: 3, height: Math.round(RULER_H / 2),
            background: "var(--text-bright)", borderRadius: 1,
            cursor: "pointer" }}
        />
      ))}
    </div>
  );
}

export type RangeMode = "new" | "in" | "out" | "slide";

/** A marked-range drag in flight. Both windows keep one of these inside their
 *  own drag union, and both drive it through the two functions below — marking
 *  a range to tag it and marking one to cut it are the same gesture. */
export interface RangeDragState {
  mode: RangeMode;
  /** Where the press landed, in film time. */
  t0: number;
  x0: number;
  /** The range as it was when the press landed. */
  s0: number | null;
  e0: number | null;
  moved: boolean;
}

/** One pointer move of a range drag. `at` is the film time under the pointer.
 *
 *  Dragging an EDGE scrubs the film to that edge, so the range is picked by
 *  the frame rather than by the pixel — and the playhead STAYS there when the
 *  drag ends (see below). */
export function rangeDragMove(
  d: RangeDragState, clientX: number, at: number,
  onRangeChange: (start: number | null, end: number | null) => void,
  onSeek: (t: number) => void,
): void {
  if (Math.abs(clientX - d.x0) > 2) d.moved = true;
  if (d.mode === "in") {
    onRangeChange(Math.min(at, d.e0 ?? Infinity), d.e0);
    onSeek(at);
  } else if (d.mode === "out") {
    onRangeChange(d.s0, Math.max(at, d.s0 ?? 0));
    onSeek(at);
  } else if (d.mode === "new") {
    // Only once the pointer has travelled: a press that pulls out no range is
    // a CLICK, and `rangeDragEnd` is what that means.
    if (!d.moved) return;
    onRangeChange(Math.min(d.t0, at), Math.max(d.t0, at));
    onSeek(at);
  } else if (d.s0 != null && d.e0 != null) {
    const w = d.e0 - d.s0;
    const s = Math.max(0, d.s0 + (at - d.t0));
    onRangeChange(s, s + w);
  }
}

/**
 * The end of a range drag.
 *
 * **A CLICK ON THE EMPTY LANE CLEARS THE RANGE.** The lane is the one place
 * that is unambiguously about the range and nothing else, and pressing there
 * used to do nothing at all unless the pointer travelled.
 *
 * **THE PLAYHEAD STAYS WHERE THE DRAG PUT IT.** It used to be put back where
 * it was before the drag, on the reasoning that the scrub was a preview of the
 * edge. But an edge is chosen by looking at the frame it lands on, and the
 * next thing anybody does is look at that frame — so returning the playhead
 * threw away the one thing the gesture had just established.
 */
export function rangeDragEnd(
  d: RangeDragState,
  onRangeChange: (start: number | null, end: number | null) => void,
): void {
  if (d.mode === "new" && !d.moved) onRangeChange(null, null);
}

/** The marked in/out range, on its own lane under the ruler: a grey line
 *  saying a selection can live here, the selection over it in accent, and a
 *  handle at each end. */
export function RangeLane({ tl, range, onBegin, top = RULER_H, t }: {
  tl: Timeline;
  range: { start: number | null; end: number | null };
  onBegin: (mode: RangeMode, e: React.MouseEvent) => void;
  top?: number;
  t: (s: string) => string;
}) {
  const has = range.start != null && range.end != null;
  return (
    <div style={{ position: "absolute", left: 0, top, width: "100%",
      height: RANGE_H }}>
      <div
        onMouseDown={(e) => onBegin("new", e)}
        title={t("Drag to select a time range")}
        style={{ position: "absolute", top: 4, left: 0, right: 0, height: 5,
          background: "var(--border-strong)", borderRadius: 3,
          cursor: "ew-resize" }}
      />
      {has && (
        <div
          onMouseDown={(e) => onBegin("slide", e)}
          title={t("Drag to move the range")}
          style={{ position: "absolute", top: 4, height: 5,
            left: tl.xOf(range.start!),
            width: Math.max(0, tl.xOf(range.end! - range.start!)),
            background: "var(--accent)", borderRadius: 3, cursor: "grab" }}
        />
      )}
      {range.start != null && (
        <RangeHandle left={tl.xOf(range.start)} title={t("Drag the range start")}
          onDown={(e) => onBegin("in", e)} />
      )}
      {range.end != null && (
        <RangeHandle left={tl.xOf(range.end)} title={t("Drag the range end")}
          onDown={(e) => onBegin("out", e)} />
      )}
    </div>
  );
}

/** The 3 px bar at a range's edge, at a pixel offset rather than a percentage,
 *  because a timeline scrolls. */
export function RangeHandle({ left, title, onDown }: {
  left: number; title: string; onDown: (e: React.MouseEvent) => void;
}) {
  return (
    <div
      onMouseDown={onDown}
      title={title}
      style={{ position: "absolute", top: 0, left, transform: "translateX(-50%)",
        width: 11, height: RANGE_H, display: "flex", alignItems: "center",
        justifyContent: "center", cursor: "ew-resize" }}
    >
      <div style={{ width: 3, height: RANGE_H, borderRadius: 2,
        background: "var(--accent)", boxShadow: "var(--ring-shadow)" }} />
    </div>
  );
}

/**
 * THE TIMELINE'S OWN SCROLLBAR: which stretch of the video the track is
 * showing, as a block on a bar of the whole thing.
 *
 * It replaced the system one, which appeared and disappeared with the zoom —
 * and since the timeline sits in a fixed row at the bottom of the window, that
 * took everything above it up and down by the scrollbar's own height every
 * time somebody zoomed. A bar that shoves what it is measuring.
 *
 * What it buys beyond not doing that is the thing a scrollbar is not allowed
 * to do: its EDGES resize, so the same control that pans the view also zooms
 * it, and the whole film is visible behind it as context (with the playhead
 * marked) rather than being an abstract trough.
 *
 * It sits ABOVE the ruler in both windows: it says what the ruler is
 * measuring, so it belongs on the same side of it as the numbers.
 */
export function ViewRange({ total, from, to, time, onView, t }: {
  total: number;
  from: number;
  to: number;
  /** The playhead, so the bar says where you are in the whole film. */
  time: number;
  /** `zoom` is false for a pan — the same visible LENGTH, somewhere else — so
   *  a drag along the bar cannot drift the scale by rounding. */
  onView: (from: number, to: number, zoom: boolean) => void;
  t: (s: string) => string;
}) {
  const bar = useRef<HTMLDivElement>(null);
  const drag = useRef<
    { mode: "pan" | "start" | "end"; t0: number; from: number; to: number } | null>(null);

  const timeAt = (clientX: number) => {
    const r = bar.current?.getBoundingClientRect();
    if (!r || r.width <= 0 || total <= 0) return 0;
    return Math.max(0, Math.min(total, ((clientX - r.left) / r.width) * total));
  };

  // Subscribed ONCE; the handlers read the latest `total`, `onView` and
  // `timeAt` through a ref rather than re-subscribing on every render.
  const live = useRef({ total, onView, timeAt });
  live.current = { total, onView, timeAt };
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = drag.current;
      if (!d) return;
      const { total, onView, timeAt } = live.current;
      const at = timeAt(e.clientX);
      const len = d.to - d.from;
      if (d.mode === "pan") {
        const s = Math.max(0, Math.min(Math.max(0, total - len), d.from + (at - d.t0)));
        onView(s, s + len, false);
      } else if (d.mode === "start") {
        onView(Math.min(at, d.to - MIN_VIEW), d.to, true);
      } else {
        onView(d.from, Math.max(at, d.from + MIN_VIEW), true);
      }
    };
    const onUp = () => { drag.current = null; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  if (total <= 0) return null;
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / total) * 100))}%`;
  const begin = (mode: "pan" | "start" | "end") => (e: React.MouseEvent) => {
    e.stopPropagation();
    drag.current = { mode, t0: timeAt(e.clientX), from, to };
  };
  const whole = to - from >= total - 1e-6;

  return (
    <div
      ref={bar}
      onMouseDown={(e) => {
        // Anywhere else on the bar: bring the view here, keeping its length —
        // the one thing a scrollbar's trough does that is worth keeping.
        const at = timeAt(e.clientX);
        const len = to - from;
        const s = Math.max(0, Math.min(Math.max(0, total - len), at - len / 2));
        onView(s, s + len, false);
        drag.current = { mode: "pan", t0: at, from: s, to: s + len };
      }}
      title={t("Drag to move what the timeline is showing, its edges to zoom")}
      style={{ position: "relative", height: VIEW_BAR_H, borderRadius: "var(--r-1)",
        background: "var(--panel-2)", border: "1px solid var(--border)",
        cursor: "pointer", boxSizing: "border-box" }}
    >
      {/* Where the playhead is in the WHOLE film — the bar's other job, and
          what tells you which way to drag when the view is somewhere else. */}
      <div style={{ position: "absolute", top: 1, bottom: 1, left: pct(time),
        width: 1.5, background: "var(--accent)", opacity: 0.55,
        pointerEvents: "none" }} />
      <div
        onMouseDown={begin("pan")}
        style={{ position: "absolute", top: -1, bottom: -1, left: pct(from),
          width: pct(to - from), borderRadius: "var(--r-1)", boxSizing: "border-box",
          // Nothing to move when the whole film already fits: the block would
          // fill the bar and dragging it could only fail.
          background: whole ? "var(--border-soft)" : "var(--accent-dim)",
          border: `1px solid ${whole ? "var(--border)" : "var(--accent)"}`,
          cursor: whole ? "default" : "grab" }}
      >
        <ViewGrip side="left" shown={!whole} onDown={begin("start")} />
        <ViewGrip side="right" shown={!whole} onDown={begin("end")} />
      </div>
    </div>
  );
}

/** The grab area at one end of the view block, and the bar that SAYS it is
 *  one. It was a 7 px strip with nothing drawn in it: the only thing telling
 *  anybody the edges resize was a tooltip on the whole bar, and a gesture
 *  nobody can see is a gesture nobody finds. Hidden while the whole film
 *  already fits, where dragging an edge could only fail. */
function ViewGrip({ side, shown, onDown }: {
  side: "left" | "right"; shown: boolean; onDown: (e: React.MouseEvent) => void;
}) {
  return (
    <div
      onMouseDown={onDown}
      style={{ position: "absolute", top: -2, bottom: -2, [side]: -3, width: 7,
        display: "flex", alignItems: "center", justifyContent: "center",
        cursor: "ew-resize" }}
    >
      {shown && (
        <div style={{ width: 3, height: "70%", borderRadius: 2,
          background: "var(--accent)",
          boxShadow: "var(--ring-shadow)" }} />
      )}
    </div>
  );
}

/** Where a block's end can be taken hold of. It is drawn rather than left to
 *  the cursor alone: a 7 px strip nobody can see is a gesture nobody finds. */
export function EdgeGrip({ side }: { side: "left" | "right" }) {
  return (
    <div style={{ position: "absolute", top: 0, bottom: 0, [side]: 0,
      width: EDGE_PX, cursor: "ew-resize",
      background: "var(--border-soft)" }} />
  );
}
