/**
 * THE VIDEO EDITOR'S TIMELINE: the cutlist as a row of blocks, one per piece,
 * the way an editing program draws a track.
 *
 * It replaced a plain scrubber with tick marks at the joins. That said an edit
 * had happened and nothing else — you could not see which piece was which, how
 * long any of them was, or which one a marked range was about to eat, and the
 * only way to change one was to mark a range over it and press a button. A
 * block you can take hold of says all of that by existing.
 *
 * The SCALE — the scroll, the zoom, the ruler, the view bar, the marked
 * range's lane — is `shared/Timeline.tsx`, which the annotator's tag tracks
 * use too. What is left here is what only a cutlist has.
 *
 * **Dragging a block MOVES it, and the drop INSERTS** (`cutlist.moveCutTo`).
 * Gaps are ordinary pieces of the cutlist, so a POSITION can be said: the film
 * closes up behind the lift, the piece is spliced in where it was dropped —
 * SPLITTING whatever it lands on, whose far half moves along after it — a
 * piece can be parked past the end (the track pads with a gap), and a gap at
 * the very END is dropped, because a video does not end later for its last
 * clip having moved earlier.
 *
 * Three gestures, told apart by where the press lands rather than by a mode:
 * an EDGE trims that end, the BODY moves the piece, and everywhere else —
 * the ruler, the empty track past the last piece — scrubs. A body press that
 * never travels is a click, which selects, and a selected piece can be
 * deleted. The same "the pointer says which" rule the annotator draws boxes
 * with.
 *
 * **A gesture is previewed live and committed once.** Every mousemove
 * recomputes the whole cutlist FROM THE ONE THE DRAG STARTED ON (`trimCut` and
 * `moveCutTo` are pure and cheap), so nothing accumulates and the piece under
 * the pointer keeps its index for the length of the gesture; `onCommit` fires
 * on release, with the result COMPACTED — not normalized, which would join
 * pieces that meet in the source and so silently undo a deliberate split
 * (`cutlist.splitAt`) — and that is also the one undo entry the gesture
 * should leave behind.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { pickNext } from "../../shared/pickList";
import * as cl from "../cutlist";
import type { Cut } from "../cutlist";
import { formatTimecode, shortTime } from "../timecode";
import { Icon } from "../../shared/Icon";
import {
  EDGE_PX, EdgeGrip, RANGE_H, RULER_H, RangeLane, SLOP_PX, SNAP_PX, ScaleRow,
  TimelineRuler, VIEW_BAR_H, rangeDragEnd, rangeDragMove, useTimeline,
} from "./shared/Timeline";
import type { RangeDragState, RangeMode } from "./shared/Timeline";
import { isTypingTarget } from "../../shared/typingTarget";

const TRACK_H = 46;

/** The fill of a gap: diagonal hatching over nothing, so it reads as an
 *  absence rather than as a piece whose thumbnail has not arrived. */
const HATCH =
  "repeating-linear-gradient(45deg, transparent, transparent 5px, " +
  "var(--border-soft) 5px, var(--border-soft) 10px)";

type Drag =
  | { kind: "trim"; index: number; edge: "start" | "end"; x0: number; from: Cut[] }
  | { kind: "move"; index: number; x0: number; from: Cut[]; moved: boolean;
      mods: { meta: boolean; shift: boolean };
      /** Where in the piece it was taken hold of, in seconds — so the block
       *  stays under the pointer rather than jumping its own start to it. */
      grab: number;
      /** Where the carried piece currently sits IN THE DRAFT — the index the
       *  drop would give it, which is not `index` the moment it has moved.
       *  Written by the move handler so the render can tell which block on
       *  screen is the one in the hand. */
      to?: number }
  | { kind: "scrub" }
  | ({ kind: "range" } & RangeDragState);

export function CutTrack({
  cuts, sourceDuration, fps, time, onSeek, range, onRangeChange, onCommit,
  playing, onSelection, t,
}: {
  cuts: Cut[];
  /** The source's own length — the limit a piece can be dragged back out to. */
  sourceDuration: number;
  /** Only for the trim READOUT, which has to be frame-accurate: a trim is
   *  aimed at a frame, and `shortTime`'s whole seconds cannot say which. */
  fps: number;
  /** The playhead, in EDITED time. */
  time: number;
  onSeek: (t: number) => void;
  range: { start: number | null; end: number | null };
  onRangeChange: (start: number | null, end: number | null) => void;
  /** A finished gesture's cutlist. One call per gesture, so one undo entry. */
  onCommit: (cuts: Cut[]) => void;
  /** Keep the playhead in view while it runs. */
  playing?: boolean;
  /** HOW MANY BLOCKS ARE PICKED, what they are, and how to remove them —
   *  reported UPWARD so the actions can sit in the row of clip actions at the
   *  bottom of the window rather than beside the zoom bar, which is about the
   *  view. `remove` and `pieces` are stable and read the current selection
   *  through refs, so the report fires on the COUNT alone: a fresh function
   *  every render would report on every render, and the parent's state would
   *  report back. That also means a pick that swaps one block for another
   *  sends nothing — and needs to send nothing, since both callbacks read what
   *  is picked now rather than what was picked when the report went out. */
  onSelection?: (sel: {
    count: number;
    /** True when the pieces actually went — false where removing them all was
     *  refused, so a Cut can decline to fill the clipboard for a removal that
     *  did not happen. */
    remove: () => boolean;
    /** The picked pieces, in TRACK order. The clipboard is an assembly, and
     *  the order the eye can see is the only one it can mean — ⌘-clicking the
     *  fourth block and then the first must not paste them back to front. */
    pieces: () => Cut[];
  } | null) => void;
  /** REQUIRED — an optional translator is a silent-English hole. */
  t: (s: string, vars?: Record<string, string>) => string;
}) {
  const tr = t;
  // WHICH BLOCKS ARE PICKED — a set, because removing three strays is one
  // gesture and one undo entry. A plain click replaces it, ⌘/Ctrl adds and
  // removes, shift extends from the last pick: the grid's rules, and the
  // crop strip's, because a row of pictures you select from is a row of
  // pictures you select from wherever it is.
  const [sel, setSel] = useState<number[]>([]);
  const pickAnchor = useRef<number | null>(null);
  const [draft, setDraft] = useState<Cut[] | null>(null);
  const drag = useRef<Drag | null>(null);
  // THE BLOCK IN THE HAND, at the pointer rather than at the seam. The track
  // lays the draft out SNAPPED — that is what makes butting two clips together
  // possible at all — so between two seams the carried block does not move
  // while the pointer does, and a drag across a long piece looks like a drag
  // that has come loose. The ghost is the half that answers the hand: it
  // follows the pointer exactly, and the block underneath goes on showing
  // where the drop would actually land.
  const [ghost, setGhost] = useState<{ at: number; cut: Cut } | null>(null);

  const shown = draft ?? cuts;
  // Where each piece begins in EDITED time, accumulated once. The blocks all
  // need it, and asking `cl.cutStart` per block re-walks the list from the
  // start each time.
  const starts = useMemo(() => {
    const out: number[] = [];
    let at = 0;
    for (const c of shown) { out.push(at); at += Math.max(0, c.end - c.start); }
    return out;
  }, [shown]);
  const duration = cl.duration(shown);
  const tl = useTimeline(duration, `${sourceDuration}`, time, playing, fps);
  const { xOf, timeAt } = tl;

  // ---- the drag ----------------------------------------------------------
  const live = useRef({ tl, sourceDuration, onSeek, onRangeChange, onCommit, time });
  live.current = { tl, sourceDuration, onSeek, onRangeChange, onCommit, time };

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
      if (d.kind === "trim") {
        const c = d.from[d.index];
        if (!c) return;
        const delta = (e.clientX - d.x0) / px;
        const to = (d.edge === "start" ? c.start : c.end) + delta;
        setDraft(cl.trimCut(d.from, d.index, d.edge, to, L.sourceDuration));
        return;
      }
      // move — FREE, not a reorder: the piece goes where it is dropped and is
      // spliced into whatever is there (`cutlist.moveCutTo`).
      if (Math.abs(e.clientX - d.x0) > SLOP_PX) d.moved = true;
      if (!d.moved) return;
      const piece = d.from[d.index];
      const len = Math.max(0, (piece?.end ?? 0) - (piece?.start ?? 0));
      // SNAPPED to what is around it — every other piece's edges, the playhead
      // and the start — within a hand's tolerance measured in pixels, because
      // that is the tolerance a hand has. Butting two clips together at four
      // pixels per second is not otherwise something anybody can do, and the
      // frame of black left between them is invisible until it plays.
      const want = Math.max(0, at - d.grab);
      if (piece) setGhost({ at: want, cut: piece });
      const snapped = cl.snapTo(
        want, len, cl.snapTimes(d.from, d.index, L.time), SNAP_PX / px);
      const moved = cl.moveCutTo(d.from, d.index, snapped);
      d.to = moved.index;
      setDraft(moved.cuts);
    };
    const onUp = () => {
      const d = drag.current;
      drag.current = null;
      setGhost(null);
      if (!d) return;
      const L = live.current;
      if (d.kind === "range") { rangeDragEnd(d, L.onRangeChange); return; }
      if (d.kind === "scrub") return;
      // A press that never travelled is a CLICK: it selects the piece rather
      // than committing an edit that did not happen.
      if (d.kind === "move" && !d.moved) { pickRef.current(d.index, d.mods); setDraft(null); return; }
      setDraft((cur) => {
        // COMPACT, not normalize: normalize joins pieces that meet in the
        // source, which is exactly what a deliberate split produces — so any
        // gesture after a split would silently undo it (`cutlist.splitAt`).
        if (cur) L.onCommit(cl.compact(cur));
        return null;
      });
      setSel([]);
      pickAnchor.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // Delete the picked pieces. The Remove button beside the zoom does the same
  // thing and is what makes the action findable; this is for the hand already
  // on the keyboard.
  useEffect(() => {
    if (!sel.length) return;
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e)) return;
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      e.preventDefault();
      removePicked();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, cuts]);

  // Reported UPWARD on the COUNT alone (see `onSelection`): the row of clip
  // actions at the bottom of the window is where removing pieces belongs, and
  // the zoom bar this button used to sit on is about the view, not the film.
  const removeRef = useRef<() => boolean>(() => false);
  const piecesRef = useRef<() => Cut[]>(() => []);
  piecesRef.current = () => cl.pickCuts(cuts, sel);
  useEffect(() => {
    onSelection?.(sel.length
      ? { count: sel.length, remove: () => removeRef.current(),
          pieces: () => piecesRef.current() }
      : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel.length]);
  useEffect(() => () => onSelection?.(null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []);

  const removePicked = () => {
    if (!sel.length) return false;
    const next = cl.removeCuts(cuts, sel);
    // Everything is not deletable: a video of nothing is not something the
    // renderer can be asked for, and Undo cannot be the only way back.
    if (!next.length) return false;
    setSel([]);
    pickAnchor.current = null;
    onCommit(next);
    return true;
  };
  removeRef.current = removePicked;

  /** A click on a block: replace, toggle, or extend. In a ref because the
   *  mouseup handler that calls it is registered once. */
  const pickRef = useRef((_i: number, _m: { meta: boolean; shift: boolean }) => {});
  // The one click rule (`shared/pickList.ts`); the order is the pieces'.
  pickRef.current = (i, m) => {
    setSel((cur) => {
      const order = cuts.map((_, k) => k);
      const r = pickNext(cur, i, m, order, pickAnchor.current);
      pickAnchor.current = r.anchor;
      return r.next;
    });
  };

  const beginRange = (mode: RangeMode, e: React.MouseEvent) => {
    e.stopPropagation();
    drag.current = {
      kind: "range", mode, t0: timeAt(e.clientX), x0: e.clientX,
      s0: range.start, e0: range.end, moved: false,
    };
  };

  const d = drag.current;
  // WHICH BLOCK ON SCREEN IS IN THE HAND. For a trim that is the piece's own
  // index, since trimming keeps the array's order; for a move it is where the
  // piece has been carried TO, which is what the draft is showing. Reading
  // `d.index` for both — as this did — pointed at whichever piece had slid
  // into the vacated slot, so the lift and the drop markers landed on a block
  // nobody was dragging.
  const dragging = draft && d
    ? (d.kind === "move" ? (d.to ?? d.index)
       : d.kind === "trim" ? d.index : null)
    : null;
  /** The edge a trim is pulling, so it can be drawn as the one that moves. */
  const trimEdge = draft && d && d.kind === "trim" ? d.edge : null;
  const hasRange = range.start != null && range.end != null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {/* THE SCALE, in one row: the zoom buttons and then the bar saying which
          part of the video is on screen. ABOVE the ruler, not under the track:
          it says what the ruler is measuring, so it belongs on the same side of
          it as the numbers — and under the track it sat between the timeline
          and the transport, two rows of scale between the picture and the play
          button. */}
      <ScaleRow tl={tl} total={duration} time={time} t={tr} />

      {/* THE SCROLLBAR IS OURS (`ViewRange`, above), so this one is hidden.
          Hidden overflow still scrolls PROGRAMMATICALLY, which is all the
          zoom, the playhead-follow and the view bar ever did; what it does not
          do is scroll on a wheel, which `useTimeline` handles. */}
      <div
        ref={tl.scroller}
        onScroll={tl.onScroll}
        style={{ position: "relative", overflowX: "hidden", overflowY: "hidden" }}
      >
        <div style={{ position: "relative", width: tl.contentW,
          height: RULER_H + RANGE_H + TRACK_H + 4 }}>

          <TimelineRuler
            tl={tl}
            onScrub={(e) => { drag.current = { kind: "scrub" }; onSeek(timeAt(e.clientX)); }}
          />

          <RangeLane tl={tl} range={range} onBegin={beginRange} t={tr} />

          {/* ---- the pieces ---- */}
          <div
            onMouseDown={(e) => {
              // Past the last piece there is nothing to take hold of, so the
              // track scrubs like the ruler does.
              drag.current = { kind: "scrub" };
              onSeek(timeAt(e.clientX));
              setSel([]);
              pickAnchor.current = null;
            }}
            style={{ position: "absolute", left: 0, top: RULER_H + RANGE_H,
              width: "100%", height: TRACK_H, background: "var(--panel-2)",
              border: "1px solid var(--border)", borderRadius: "var(--r-2)",
              cursor: "pointer", overflow: "hidden" }}
          >
            {shown.map((c, i) => {
              // `starts` rather than `cl.cutStart(shown, i)`, which walks the
              // list from the beginning for every block — O(n²) per render, on
              // a component that re-renders on every pointer move of a scrub
              // and every frame of playback, with n growing at every split.
              const left = xOf(starts[i]);
              const w = Math.max(1, xOf(Math.max(0, c.end - c.start)));
              const picked = sel.includes(i) && !draft;
              const held = dragging === i;
              const blank = cl.isGap(c);
              const len = Math.max(0, c.end - c.start);
              return (
                <div
                  key={i}
                  onMouseDown={(e) => {
                    e.stopPropagation();
                    const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
                    const nearStart = e.clientX - box.left < EDGE_PX;
                    const nearEnd = box.right - e.clientX < EDGE_PX;
                    // A block too narrow to have two edges is all body: two
                    // 7 px zones on a 10 px block leave nothing to grab, and
                    // reordering is the gesture you can still reach it by.
                    if (w > EDGE_PX * 3 && (nearStart || nearEnd)) {
                      drag.current = { kind: "trim", index: i,
                        edge: nearStart ? "start" : "end",
                        x0: e.clientX, from: cuts };
                      setSel([]);
                      pickAnchor.current = null;
                    } else {
                      drag.current = { kind: "move", index: i, x0: e.clientX,
                        from: cuts, moved: false,
                        // Where in the block the hand took hold of it, so it
                        // stays under the pointer instead of jumping its own
                        // start there.
                        grab: Math.max(0, timeAt(e.clientX) - starts[i]),
                        mods: { meta: e.metaKey || e.ctrlKey, shift: e.shiftKey } };
                    }
                  }}
                  title={blank
                    ? `${tr("Gap")} · ${shortTime(len)}`
                    : `${tr("Piece")} ${i + 1} · ${shortTime(c.start)}–${shortTime(c.end)}`}
                  style={{
                    position: "absolute", left, width: w, top: held ? 1 : 3,
                    height: TRACK_H - 8, borderRadius: 4, overflow: "hidden",
                    // A GAP is drawn as an absence: no fill of its own, a
                    // dashed outline, and diagonal hatching. It has to read as
                    // "nothing here" at a glance rather than as a piece whose
                    // thumbnail has not loaded, which is what a plain darker
                    // block would have looked like.
                    background: held || picked ? "var(--accent-dim)"
                      : blank ? HATCH : "var(--panel)",
                    border: `1px ${blank ? "dashed" : "solid"} ${
                      held || picked ? "var(--accent)" : "var(--border-strong)"}`,
                    // A piece being dragged is the one the pointer is on, so it
                    // rides over its neighbours rather than under them.
                    zIndex: held ? 3 : 1,
                    // LIFTED while it is in the hand — raised two pixels, on an
                    // accent ring, over a shadow. The track already reorders
                    // live, so the drop position was visible; what was not was
                    // WHICH of the blocks was the one being carried, and the
                    // reordering itself made that harder rather than easier.
                    ...(held ? {
                      boxShadow: "var(--shadow-2), 0 0 0 1px var(--accent)",
                    } : null),
                    display: "flex", alignItems: "center",
                    cursor: held ? "grabbing" : "grab", userSelect: "none",
                    // No transition on the carried block: it must track the
                    // pointer exactly, and easing it turns a drag into a chase.
                    transition: held || draft ? "none" : "left 0.12s, width 0.12s",
                  }}
                >
                  {/* The trim zones, drawn only where they are reachable. */}
                  {w > EDGE_PX * 3 && (
                    <>
                      <EdgeGrip side="left" />
                      <EdgeGrip side="right" />
                    </>
                  )}
                  {/* The edge a trim is pulling, drawn solid while it moves —
                      the grips are otherwise identical, so nothing said which
                      of the two the pointer had hold of. */}
                  {held && trimEdge && (
                    <div style={{ position: "absolute", top: 0, bottom: 0,
                      width: 2, background: "var(--accent)",
                      pointerEvents: "none",
                      ...(trimEdge === "start" ? { left: 0 } : { right: 0 }) }} />
                  )}
                  {w > 46 && (
                    <span style={{ position: "absolute", left: EDGE_PX + 2,
                      right: EDGE_PX + 2, fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                      color: held ? "var(--accent)" : "var(--muted)",
                      pointerEvents: "none",
                      overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap" }}>
                      {/* A gap has no source timestamps to show — it comes
                          from nowhere — so it says how long it lasts, which
                          is the only thing about it there is to know. */}
                      {blank ? `${tr("Gap")} ${shortTime(len)}`
                             : `${shortTime(c.start)}–${shortTime(c.end)}`}
                    </span>
                  )}
                </div>
              );
            })}
            {/* WHERE IT WILL LAND. The blocks reorder live, so the result is
                already on screen — but "already on screen" is exactly what
                makes it hard to read, since every piece after the gap has
                shifted too. This marks the seam the carried piece would sit
                between, which is the one thing the reordering does not say
                out loud. Drawn outside the block so it survives its
                `overflow: hidden`. */}
            {dragging != null && d?.kind === "move" && shown[dragging] && (
              <>
                <DropMark x={xOf(starts[dragging])} />
                <DropMark x={xOf(starts[dragging]
                  + Math.max(0, shown[dragging].end - shown[dragging].start))} />
              </>
            )}
            {/* THE GHOST: the carried block drawn where the POINTER is, not
                where it would land. It takes no pointer and is drawn over
                everything in the track (the drop markers included — it is the
                thing in the hand), with no transition at all, since easing it
                is exactly the lag it exists to remove. */}
            {ghost && d?.kind === "move" && d.moved && (() => {
              const len = Math.max(0, ghost.cut.end - ghost.cut.start);
              const blank = cl.isGap(ghost.cut);
              const w = Math.max(1, xOf(len));
              return (
                <div style={{
                  position: "absolute", left: xOf(ghost.at), width: w, top: 1,
                  height: TRACK_H - 8, borderRadius: 4, overflow: "hidden",
                  background: blank ? HATCH : "var(--accent-dim)",
                  border: `1px ${blank ? "dashed" : "solid"} var(--accent)`,
                  boxShadow: "var(--shadow-2)",
                  opacity: 0.75, pointerEvents: "none", zIndex: 4,
                  display: "flex", alignItems: "center",
                }}>
                  {w > 46 && (
                    <span style={{ position: "absolute", left: EDGE_PX + 2,
                      right: EDGE_PX + 2, fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                      color: "var(--accent)", overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {blank ? `${tr("Gap")} ${shortTime(len)}`
                             : `${shortTime(ghost.cut.start)}–${shortTime(ghost.cut.end)}`}
                    </span>
                  )}
                </div>
              );
            })()}
            {/* WHAT THE MARKED RANGE COVERS, on the pieces themselves. The
                lane above says where the range IS; this says what it is ABOUT
                to eat, which is the question Trim and Remove ask and the one a
                thin bar over a row of blocks cannot answer. Over the blocks
                (z 2) but under the one in the hand (z 3), and it takes no
                pointer: the blocks underneath are still draggable. */}
            {hasRange && (
              <div style={{ position: "absolute", top: 0, bottom: 0,
                left: xOf(range.start!),
                width: Math.max(1, xOf(range.end! - range.start!)),
                background: "var(--accent-dim)",
                borderLeft: "1px solid var(--accent)",
                borderRight: "1px solid var(--accent)",
                boxSizing: "border-box", pointerEvents: "none", zIndex: 2 }} />
            )}
          </div>

          {/* WHAT THE EDGE IN THE HAND IS LANDING ON, frame-accurate, while a
              trim runs. The block's own label says the piece's source range,
              but it is `shortTime` — whole seconds — and rounds to nothing at
              the scale a trim is actually aimed at; a narrow block carries no
              label at all. A gap names no material, so it says its length and
              nothing else. Drawn over the track (it must not be clipped by the
              block it belongs to) and taking no pointer. */}
          {trimEdge && dragging != null && shown[dragging] && (() => {
            const c = shown[dragging];
            const len = Math.max(0, c.end - c.start);
            const x = xOf(starts[dragging] + (trimEdge === "start" ? 0 : len));
            const blank = cl.isGap(c);
            return (
              <div style={{ position: "absolute", left: x, top: RULER_H,
                transform: "translateX(-50%)", zIndex: 6, pointerEvents: "none",
                padding: "2px 6px", borderRadius: "var(--r-2)",
                background: "var(--surface-float)",
                border: "1px solid var(--accent)",
                boxShadow: "var(--shadow-2)",
                fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                color: "var(--accent)", whiteSpace: "nowrap" }}>
                {blank
                  ? shortTime(len)
                  : `${formatTimecode(trimEdge === "start" ? c.start : c.end, fps, true)} · ${shortTime(len)}`}
              </div>
            );
          })()}

          {/* ---- playhead, over everything ----
              zIndex above the blocks, and that is a FIX rather than a
              precaution: a carried block is `zIndex: 3` and the range shading
              `2`, both positioned descendants of this same content box, so an
              unlayered playhead painted UNDER the very pieces it is meant to
              be marking a moment in. */}
          <div style={{ position: "absolute", top: 0, left: xOf(time), width: 2,
            height: RULER_H + RANGE_H + TRACK_H, background: "var(--accent)",
            zIndex: 5, pointerEvents: "none" }} />
        </div>
      </div>
    </div>
  );
}

/** One end of where a carried piece would drop. A full-height accent rule with
 *  a wedge at the top, so it reads as a seam in the track rather than as a
 *  second playhead — that one is the same colour and this would otherwise be
 *  two identical lines meaning different things. */
function DropMark({ x }: { x: number }) {
  return (
    <div style={{ position: "absolute", top: 0, bottom: 0, left: x - 1, width: 2,
      background: "var(--accent)", pointerEvents: "none", zIndex: 4 }}>
      <div style={{ position: "absolute", top: 0, left: -3,
        borderLeft: "4px solid transparent", borderRight: "4px solid transparent",
        borderTop: "5px solid var(--accent)" }} />
    </div>
  );
}
