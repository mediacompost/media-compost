/**
 * THE ANNOTATOR'S TIMELINE: a film's timed tags as blocks on their own tracks,
 * one track per tag — the video editor's cut track, over the other kind of
 * thing a film holds.
 *
 * It replaced a 5 px activity lane per SELECTED tag stacked over a 26 px
 * scrubber. Three things were wrong with that. A stretch you cannot take hold
 * of has to be edited from the sidebar, so a lane was a picture of an edit
 * rather than a way to make one. A lane appeared only once its tag was
 * selected, so the film's own tags were invisible until you went looking for
 * them one at a time — and the stack grew downwards under the pointer as you
 * picked, moving everything you were aiming at. And a 5 px bar has nowhere to
 * write what it is: the tag's name sat above the lane in 8.5 px type, and the
 * times were nowhere at all.
 *
 * So: **every timed tag has a track, always**, and a block carries its own
 * name and stretch inside it. Selecting tags no longer changes the LAYOUT at
 * all, and it does not GHOST the rest either: that was tried, borrowing the
 * canvas boxes' rule, and a timeline is not a picture — the boxes overlap the
 * thing they are about, so ghosting says "look past these", while a track is
 * the only place its own tag is drawn, and dimming it hides the very thing you
 * came to read. The accent ring on what is picked is enough.
 *
 * The SCALE is `shared/Timeline.tsx`, the same scroll, zoom, ruler and view
 * bar the video editor has: the two windows sit over the same film, and a
 * ruler that stepped in different numbers in one of them would be one feature
 * wearing two behaviours.
 *
 * Three gestures, told apart by where the press lands rather than by a mode —
 * the cut track's rule and the canvas's: an EDGE resizes that end, the BODY
 * moves the stretch, and everywhere else scrubs. A body press that never
 * travels is a click, which SELECTS — and a block's selection is the sidebar
 * row's, because the block and the row are the same stretch of film.
 *
 * A gesture is previewed live off the geometry it started from and committed
 * ONCE, on release; the preview is held until the write has actually landed,
 * or the block snaps back for the length of the round trip.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";

import { Icon } from "../../shared/Icon";
import { formatTimecode, shortTime } from "../timecode";
import { tagColor } from "../tagColor";
import {
  EDGE_PX, EdgeGrip, RANGE_H, RULER_H, RangeLane, SLOP_PX, SNAP_PX, ScaleRow,
  TimelineRuler, rangeDragEnd, rangeDragMove, useTimeline,
} from "./shared/Timeline";
import type { RangeDragState, RangeMode } from "./shared/Timeline";

/** One stretch of film a tag covers — a time-only `ItemTagBox`, plus the
 *  sidebar row key it IS, so picking one here picks the row there. */
export interface TagRangeBlock {
  id: number;
  key: string;
  name: string;
  start: number;
  end: number | null;
  negative: boolean;
}

/** A frame somebody kept, marked along the film. Keyed by ITEM AND MOMENT: one
 *  picture can be the film's still at several timestamps, so its item id alone
 *  names more than one tick. */
export interface StillMark {
  key: string;
  name: string;
  timestamp: number;
}

const LANE_H = 26;
const LANE_GAP = 3;
/** The shortest stretch a drag will make. Half a frame at any sane rate, and
 *  the same order as the backend's own tolerance for "no gap". */
const MIN_LEN = 0.04;

type Drag =
  | { kind: "scrub" }
  | ({ kind: "range" } & RangeDragState)
  | { kind: "block"; id: number; mode: "move" | "start" | "end";
      x0: number; grab: number; start: number; end: number | null;
      moved: boolean; mods: { meta: boolean; shift: boolean } };

export function TagTrack({
  duration, fps, time, onSeek, playing, range, onRangeChange,
  blocks, selKeys, onPick, onCommit, onToggleSign, onHoverTag,
  stills, fitKey, t,
}: {
  duration: number;
  fps: number;
  time: number;
  onSeek: (t: number) => void;
  playing?: boolean;
  range: { start: number | null; end: number | null };
  onRangeChange: (start: number | null, end: number | null) => void;
  blocks: TagRangeBlock[];
  /** The sidebar's selected tag rows. A block's key is a row key. */
  selKeys: Set<string>;
  onPick: (key: string, mods: { meta: boolean; shift: boolean }) => void;
  /** Awaited: the block keeps showing the dragged geometry until the stored
   *  one has caught up, so nothing snaps back while the write is in flight. */
  onCommit: (id: number, start: number, end: number | null) => void | Promise<void>;
  onToggleSign: (id: number) => void;
  onHoverTag: (tag: string | null) => void;
  stills: StillMark[];
  /** What a fresh fit hangs on — the film. */
  fitKey: string;
  t: (s: string, vars?: Record<string, string>) => string;
}) {
  const tl = useTimeline(duration, fitKey, time, playing, fps);
  const { xOf, timeAt } = tl;
  const drag = useRef<Drag | null>(null);
  /** The stretch being dragged, shown instead of its stored geometry until the
   *  edit has actually LANDED. Cleared on mouseup it would snap back to the
   *  old position for as long as the round trip took. */
  const [edit, setEdit] = useState<
    { id: number; start: number; end: number | null } | null>(null);
  const editRef = useRef(edit);
  editRef.current = edit;
  const [held, setHeld] = useState<number | null>(null);

  // One track per tag NAME, in reading order. A tag may sit in two groups, but
  // its stretches are the TAG's — the server keeps them from overlapping per
  // tag rather than per placement — so two placements would be one track drawn
  // twice.
  const lanes = useMemo(() => {
    const by = new Map<string, TagRangeBlock[]>();
    for (const b of blocks) {
      const list = by.get(b.name);
      if (list) list.push(b); else by.set(b.name, [b]);
    }
    return [...by.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([name, rows]) => ({ name, rows }));
  }, [blocks]);

  const tracksH = Math.max(LANE_H,
    lanes.length * LANE_H + Math.max(0, lanes.length - 1) * LANE_GAP);
  const headerH = RULER_H + RANGE_H;

  // ---- the drag ----------------------------------------------------------
  const live = useRef({ tl, onSeek, onRangeChange, onCommit, onPick, time, blocks });
  live.current = { tl, onSeek, onRangeChange, onCommit, onPick, time, blocks };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = drag.current;
      if (!d) return;
      const L = live.current;
      const at = L.tl.timeAt(e.clientX);
      if (d.kind === "scrub") { L.onSeek(at); return; }
      if (d.kind === "range") {
        rangeDragMove(d, e.clientX, at, L.onRangeChange, L.onSeek);
        return;
      }
      const px = L.tl.pxPerSec;
      if (px <= 0) return;
      if (Math.abs(e.clientX - d.x0) > SLOP_PX) d.moved = true;
      if (!d.moved) return;
      const tol = SNAP_PX / px;
      // The stretches around it, and the playhead — the same snap set the cut
      // track uses, for the same reason: butting two stretches together by
      // hand at four pixels per second is not something anybody can do.
      const stops = snapStops(L.blocks, d.id, L.time);
      if (d.mode === "move") {
        const len = (d.end ?? d.start) - d.start;
        const want = Math.max(0, at - d.grab);
        const s = snapTo(want, len, stops, tol);
        setEdit({ id: d.id, start: s, end: d.end == null ? null : s + len });
        return;
      }
      const raw = snapTo(at, 0, stops, tol);
      setEdit(d.mode === "start"
        ? { id: d.id, start: Math.min(raw, (d.end ?? d.start) - MIN_LEN), end: d.end }
        : { id: d.id, start: d.start, end: Math.max(raw, d.start + MIN_LEN) });
    };
    const onUp = () => {
      const d = drag.current;
      drag.current = null;
      setHeld(null);
      if (!d) return;
      const L = live.current;
      if (d.kind === "range") { rangeDragEnd(d, L.onRangeChange); return; }
      if (d.kind === "scrub") return;
      // A press that never travelled is a CLICK: it picks the stretch rather
      // than committing an edit that did not happen.
      if (!d.moved) {
        const b = L.blocks.find((x) => x.id === d.id);
        if (b) L.onPick(b.key, d.mods);
        return;
      }
      // Read the preview from the ref rather than from a setState updater:
      // committing inside one makes the write a side effect of rendering, and
      // React is free to run (or drop) that more than once.
      const cur = editRef.current;
      if (!cur || cur.id !== d.id) return;
      void Promise.resolve(L.onCommit(cur.id, cur.start, cur.end))
        .finally(() => setEdit((e2) => (e2 && e2.id === cur.id ? null : e2)));
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const beginRange = (mode: RangeMode, e: React.MouseEvent) => {
    e.stopPropagation();
    drag.current = {
      kind: "range", mode, t0: timeAt(e.clientX), x0: e.clientX,
      s0: range.start, e0: range.end, moved: false,
    };
  };
  const scrub = (e: React.MouseEvent) => {
    drag.current = { kind: "scrub" };
    onSeek(timeAt(e.clientX));
  };

  const shownOf = (b: TagRangeBlock) =>
    edit && edit.id === b.id ? { start: edit.start, end: edit.end } : b;

  return (
    // FILLS what it is given, rather than sizing itself to its tracks: the
    // annotator's bottom panel is resizable, and how many tracks fit is the
    // answer to how tall somebody has made it rather than a constant here.
    <div style={{ display: "flex", flexDirection: "column", gap: 4,
      flex: 1, minHeight: 0 }}>
      <ScaleRow tl={tl} total={duration} time={time} t={t} />

      {/* ONE scroller for both axes, with the ruler STICKY at its top: the
          tracks are what scrolls out of view, and a ruler that went with them
          would leave the eighth track measured by nothing. Horizontally the
          header is not sticky at all — it must travel with the film. */}
      <div
        ref={tl.scroller}
        onScroll={tl.onScroll}
        style={{ position: "relative", overflowX: "hidden", overflowY: "auto",
          flex: 1, minHeight: headerH + LANE_H + 2 }}
      >
        <div style={{ position: "relative", width: tl.contentW }}>
          <div style={{ position: "sticky", top: 0, zIndex: 7, height: headerH,
            background: "var(--panel)" }}>
            {/* The frames somebody kept are marked ON the ruler. They had a
                strip of their own, which spent a row saying "these are
                positions in the film" — which is what the ruler already is,
                and it put the marks a row away from the numbers naming
                them. */}
            <TimelineRuler
              tl={tl} onScrub={scrub}
              marks={stills.map((st) => ({
                key: st.key, at: st.timestamp,
                title: `${st.name} — ${shortTime(st.timestamp)}`,
                onClick: () => onSeek(st.timestamp),
              }))}
            />
            <RangeLane tl={tl} range={range} onBegin={beginRange} t={t} />
          </div>

          {/* ---- the tracks ---- */}
          <div
            onMouseDown={scrub}
            onMouseLeave={() => onHoverTag(null)}
            style={{ position: "relative", height: tracksH, cursor: "pointer" }}
          >
            {lanes.map((lane, li) => (
              <div
                key={lane.name}
                onMouseEnter={() => onHoverTag(lane.name)}
                style={{ position: "absolute", left: 0, right: 0,
                  top: li * (LANE_H + LANE_GAP), height: LANE_H,
                  background: "var(--panel-2)",
                  border: "1px solid var(--border)", borderRadius: "var(--r-1)",
                  boxSizing: "border-box" }}
              >
                {lane.rows.map((b) => {
                  const g = shownOf(b);
                  const end = g.end ?? g.start;
                  const left = xOf(g.start);
                  const w = Math.max(3, xOf(Math.max(0, end - g.start)));
                  const picked = selKeys.has(b.key);
                  const c = tagColor(b.name);
                  const inHand = held === b.id;
                  return (
                    <div
                      key={b.id}
                      onMouseDown={(e) => {
                        if (e.button !== 0) return;
                        e.stopPropagation();
                        const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
                        const nearStart = e.clientX - box.left < EDGE_PX;
                        const nearEnd = box.right - e.clientX < EDGE_PX;
                        // A single frame has no two edges to pull apart, and a
                        // block too narrow for two grip zones is all body.
                        const resizable = g.end != null && w > EDGE_PX * 3;
                        drag.current = {
                          kind: "block", id: b.id, x0: e.clientX,
                          mode: resizable && nearStart ? "start"
                            : resizable && nearEnd ? "end" : "move",
                          grab: Math.max(0, timeAt(e.clientX) - g.start),
                          start: g.start, end: g.end, moved: false,
                          mods: { meta: e.metaKey || e.ctrlKey, shift: e.shiftKey },
                        };
                        setHeld(b.id);
                      }}
                      onDoubleClick={(e) => { e.stopPropagation(); onToggleSign(b.id); }}
                      title={b.negative
                        ? t("{tag} − absent here", { tag: b.name })
                        : t("{tag} + present here", { tag: b.name })}
                      style={{
                        position: "absolute", left, width: w, top: 2,
                        height: LANE_H - 6, borderRadius: 4, overflow: "hidden",
                        boxSizing: "border-box",
                        // A tag's own colour says WHICH tag without reading;
                        // a NEGATIVE stretch is a different claim, so it is
                        // hollow and dashed rather than a second hue nobody
                        // can tell from a tag's.
                        background: b.negative ? "transparent" : c.fill,
                        border: `${picked ? 2 : 1}px ${b.negative ? "dashed" : "solid"} ${
                          picked ? "var(--accent)" : b.negative ? "var(--red)" : c.stroke}`,
                        zIndex: inHand ? 3 : picked ? 2 : 1,
                        ...(inHand ? {
                          boxShadow: "var(--shadow-2), 0 0 0 1px var(--accent)",
                        } : null),
                        display: "flex", alignItems: "center",
                        cursor: inHand ? "grabbing" : "grab", userSelect: "none",
                      }}
                    >
                      {g.end != null && w > EDGE_PX * 3 && (
                        <>
                          <EdgeGrip side="left" />
                          <EdgeGrip side="right" />
                        </>
                      )}
                      {/* WHAT IT IS AND WHEN, inside the block. A 5 px lane
                          could carry neither: the name went above it in 8.5 px
                          type and the times went nowhere. The stretch is
                          dropped first when there is no room for both — the
                          name is what you are looking for, the numbers are
                          what you check — and its threshold is wide enough for
                          a name BESIDE it rather than for the pair alone, or
                          the numbers appear by ellipsising the name. */}
                      {w > 34 && (
                        <span style={{ position: "absolute",
                          left: EDGE_PX + 1, right: EDGE_PX + 1,
                          display: "flex", alignItems: "baseline", gap: 5,
                          pointerEvents: "none", overflow: "hidden",
                          whiteSpace: "nowrap" }}>
                          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                            color: "var(--text-bright)",
                            textDecoration: b.negative ? "line-through" : "none",
                            overflow: "hidden", textOverflow: "ellipsis" }}>
                            {b.name}
                          </span>
                          {w > 210 && (
                            <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-0)",
                              color: "var(--muted-2)", flex: "0 0 auto" }}>
                              {formatTimecode(g.start, fps, true)}
                              {g.end != null && ` – ${formatTimecode(g.end, fps, true)}`}
                            </span>
                          )}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
            {lanes.length === 0 && (
              <div style={{ position: "absolute", inset: 0,
                background: "var(--panel-2)", border: "1px solid var(--border)",
                borderRadius: "var(--r-1)", display: "flex", alignItems: "center",
                paddingLeft: 8, pointerEvents: "none" }}>
                <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-3)" }}>
                  {t("Mark a stretch below and give it a tag")}
                </span>
              </div>
            )}
            {/* WHAT THE MARKED RANGE COVERS, over the tracks: the lane above
                says where it is, this says which stretches it is about to add
                to or cut out of. */}
            {range.start != null && range.end != null && (
              <div style={{ position: "absolute", top: 0, bottom: 0,
                left: xOf(range.start), width: Math.max(1, xOf(range.end - range.start)),
                background: "var(--accent-dim)",
                borderLeft: "1px solid var(--accent)",
                borderRight: "1px solid var(--accent)",
                boxSizing: "border-box", pointerEvents: "none", zIndex: 4 }} />
            )}
          </div>

          {/* The playhead spans the whole content, header included, and rides
              over the blocks — an unlayered one paints UNDER any positioned
              block with a z-index, which is every one of them. */}
          <div style={{ position: "absolute", top: 0, left: xOf(time), width: 2,
            height: headerH + tracksH, background: "var(--accent)",
            zIndex: 8, pointerEvents: "none" }} />
        </div>
      </div>
    </div>
  );
}

/** Where a dragged stretch's edges want to land: every OTHER stretch's edges,
 *  the playhead, and the start of the film. */
function snapStops(blocks: TagRangeBlock[], skipId: number, playhead: number): number[] {
  const out = [0, playhead];
  for (const b of blocks) {
    if (b.id === skipId) continue;
    out.push(b.start);
    if (b.end != null) out.push(b.end);
  }
  return out;
}

/** Move `at` (with `len` behind it) onto a stop within `tolerance` of either
 *  of its edges. The NEAREST wins. */
function snapTo(at: number, len: number, stops: number[], tolerance: number): number {
  let best = at;
  let bestGap = tolerance;
  for (const s of stops) {
    for (const candidate of [s, s - len]) {
      const d = Math.abs(candidate - at);
      if (d < bestGap && candidate >= 0) { bestGap = d; best = candidate; }
    }
  }
  return best;
}

/** The strip of actions under the timeline: what the marked range does to the
 *  tags that are selected.
 *
 * It is ALWAYS rendered, even with no range and nothing selected, and that is
 * the point. It used to appear the moment a range was marked, which pushed the
 * transport, the timeline and the picture up by its own height at the exact
 * moment somebody had finished aiming a drag — the row that says what you can
 * do now must not move what you were doing it with. */
export function RangeActions({
  range, fps, names, busy, onApply, onClear, trailing, t,
}: {
  range: { start: number; end: number } | null;
  fps: number;
  /** The tags the buttons would act on. */
  names: string[];
  busy: boolean;
  onApply: (op: "add" | "subtract") => void;
  onClear: () => void;
  /** What the window puts at the row's right end — the in/out fields. */
  trailing?: React.ReactNode;
  t: (s: string, vars?: Record<string, string | number>) => string;
}) {
  const on = !!range && names.length > 0 && !busy;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, height: 26 }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
        color: range ? "var(--muted-2)" : "var(--muted-3)" }}>
        {range
          ? `${formatTimecode(range.start, fps, true)} – ${formatTimecode(range.end, fps, true)}`
          : t("no range marked")}
      </span>
      {/* The way OUT of a marked range, beside the range itself — DIMMED
          rather than removed when there is nothing to clear. A control that
          appears and disappears with its argument is one nobody learns the
          place of, and its absence shifted the words either side of it every
          time a range was marked or cleared. */}
      <button
        onClick={range ? onClear : undefined}
        disabled={!range}
        title={t("Clear the marked range")}
        style={{ width: 18, height: 18, display: "flex", alignItems: "center",
          justifyContent: "center", padding: 0, borderRadius: "var(--r-1)",
          border: "none", background: "transparent",
          color: range ? "var(--muted-2)" : "var(--muted-3)",
          opacity: range ? 1 : 0.45,
          cursor: range ? "pointer" : "default" }}
      >
        <Icon name="close" size={13} />
      </button>
      <Icon name="arrow_forward" size={14} color="var(--muted-3)" />
      <span style={{ fontSize: "var(--fs-2)",
        color: names.length > 0 ? "var(--text-2)" : "var(--muted-3)" }}>
        {names.length === 0 ? t("select rows in the sidebar")
          : names.length === 1 ? names[0]
          : t("{count} selected", { count: names.length })}
      </span>
      <span style={{ flex: 1 }} />
      {(["add", "subtract"] as const).map((op) => (
        <button
          key={op}
          onClick={() => onApply(op)}
          disabled={!on}
          title={op === "add"
            ? t("Make what is selected cover this range too")
            : t("Cut this range out of what is selected")}
          style={{
            display: "flex", alignItems: "center", gap: 4, height: 26,
            padding: "0 10px", borderRadius: "var(--r-3)", fontSize: "var(--fs-2)",
            fontFamily: "inherit", cursor: on ? "pointer" : "default",
            border: "1px solid var(--border-strong)", background: "var(--panel-2)",
            color: on ? "var(--text-2)" : "var(--muted-3)", opacity: on ? 1 : 0.6,
          }}
        >
          <Icon name={op === "add" ? "add" : "remove"} size={14} />
          {op === "add" ? t("Add range") : t("Subtract range")}
        </button>
      ))}
      {trailing}
    </div>
  );
}
