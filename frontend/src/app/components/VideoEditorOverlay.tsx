/**
 * The VIDEO editor — the third half of the item-window overlay, deliberately
 * the same chrome as the other two: the image editor's header (tab strip,
 * centred name, a Video menu where its Image menu is, the Save split-button)
 * around the annotator's transport (the same play/step/scrub/in-out row, from
 * the same component).
 *
 * **Nothing here touches the file.** Every edit is a rewrite of a CUTLIST —
 * which parts of the source, in which order — plus four whole-video transforms
 * (rotate, crop, resize, frame rate). The cutlist is the model (`cutlist.ts`,
 * pure and tested); this window is its editor, and Save is where it becomes a
 * video: the backend assembles it into a new file on the item, or into a new
 * item, exactly as the image editor's two save modes do.
 *
 * The render is a BACKGROUND JOB, not a request this window waits on. Encoding
 * a film is minutes: a request holding the connection open for them cannot
 * report progress, cannot be cancelled and dies with the tab. So the window
 * queues it and watches; closing the window leaves the job in the
 * background-task list where it can be stopped, and reopening the editor finds
 * it again and puts the progress back up.
 *
 * There is no sidebar. Tagging a film is the annotator's window and always
 * was; what was here — a list of the stills taken from it — is a fact about
 * the film rather than something you do to it, and it lives in the item's own
 * panel.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { IconButton } from "../../shared/IconButton";
import { ProgressBar } from "../../shared/ProgressBar";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MediaTrack, api, VideoEditPlan, fmtDuration } from "../api";
import { Icon } from "../../shared/Icon";
import { useUI } from "../store";
import { bumpLibrary } from "../invalidation";
import * as cl from "../cutlist";
import { rotateCrop } from "../cropRect";
import type { Cut } from "../cutlist";
import { useVideoPlayback } from "./shared/useVideoPlayback";
import { CutTrack } from "./CutTrack";
import { PlaybackBar, RangeFields, SpeedControl, TrackControls, VolumeControl,
         subtitleLabel } from "./shared/VideoTransport";
import { WindowTabs, filmTabSuffix } from "./shared/WindowTabs";
import { ConfirmModal } from "../../shared/ConfirmModal";
import { RowMenu } from "../../shared/RowMenu";
import { closeChoice } from "./shared/closeChoice";
import { runVideoKey, videoKeyAction } from "./shared/videoKeys";
import { ModeSwitch } from "./shared/ModeSwitch";
import { HeaderActions } from "./shared/HeaderActions";
import { ThemeMenu, useWindowTheme } from "./shared/ThemeMenu";
import { UndoRedoButtons } from "./shared/UndoRedoButtons";
import { ItemTitle } from "./shared/ItemTitle";
import { Divider, WindowCloseBtn } from "./shared/iconButtons";
import { CANVAS_INSET, CanvasBar, CanvasBarRow } from "./shared/CanvasBars";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { ZoomControls } from "./shared/ZoomControls";
import { useZoomPan } from "../useZoomPan";
import { useWheel } from "../useWheel";
import type { ZoomPan } from "../useZoomPan";
import { formatTimecode } from "../timecode";
import { useT, useTn, useErrText } from "../i18n";
import { isTypingTarget } from "../../shared/typingTarget";

/** What the window is editing, as ONE value — so undo is a stack of these
 *  rather than five stacks that could come apart from each other. */
interface EditState {
  cuts: Cut[];
  rotate: number;
  crop: { x: number; y: number; w: number; h: number } | null;
  scale: { w: number; h: number } | null;
  fps: number | null;
}

/** The clipboard is module-level, like the image editor's: a range cut in one
 *  tab is worth pasting into another, and both tabs are this one window. */
let clipboard: Cut[] = [];

export function VideoEditorOverlay({ itemId }: { itemId: number }) {
  const t = useT();
  const errText = useErrText();
  const tn = useTn();
  const qc = useQueryClient();
  const { editorTabs, setEditorItem, closeEditorTab, closeItemWindow,
          setEditorMode } = useUI();
  const [winTheme, setWinTheme] = useWindowTheme();

  const { data: detail } = useQuery({
    queryKey: ["item", itemId],
    queryFn: () => api.item(itemId),
    // Hold the previous item while the next loads, or the window blanks
    // between tabs (the annotator's rule, for the same reason).
    placeholderData: (prev) => prev,
  });
  const activeFile = useMemo(
    () => detail?.files.find((f) => f.active) ?? detail?.files[0],
    [detail]);
  const fps = activeFile?.frame_rate && activeFile.frame_rate > 0
    ? activeFile.frame_rate : 25;
  const sourceDuration = activeFile?.duration ?? detail?.duration ?? 0;
  const play = useVideoPlayback(fps, sourceDuration);

  // ---- the edit ----------------------------------------------------------
  const [state, setState] = useState<EditState>(
    { cuts: [], rotate: 0, crop: null, scale: null, fps: null });
  const undoStack = useRef<EditState[]>([]);
  const redoStack = useRef<EditState[]>([]);
  const [, setHistVer] = useState(0);
  // What the timeline says is picked, reported up so the action can live with
  // the other clip actions (see `CutTrack`'s `onSelection`).
  const [picked, setPicked] = useState<
    { count: number; remove: () => boolean; pieces: () => Cut[] } | null>(null);
  const [inPoint, setInPoint] = useState<number | null>(null);
  const [outPoint, setOutPoint] = useState<number | null>(null);
  // Keyed on the FILE, not the item: switching tabs, or saving (which makes a
  // new file active), has to start again from what is now on screen rather
  // than keep a cutlist measured against a file that is no longer there.
  const initedFor = useRef<string>("");
  useEffect(() => {
    const key = `${itemId}:${activeFile?.id ?? ""}`;
    if (!activeFile || initedFor.current === key) return;
    initedFor.current = key;
    setState({ cuts: cl.whole(sourceDuration), rotate: 0, crop: null,
               scale: null, fps: null });
    undoStack.current = [];
    redoStack.current = [];
    setHistVer((v) => v + 1);
    setInPoint(null);
    setOutPoint(null);
    // The playhead's derived state was about the OLD file: the piece index,
    // and a playhead possibly parked in one of its gaps.
    segRef.current = 0;
    setSegIndex(0);
    gapRef.current = null;
    setGapAt(null);
    gapRunRef.current = false;
    setGapRun(false);
  }, [itemId, activeFile, sourceDuration]);

  /** Every change goes through here, so undo covers all of them by
   *  construction rather than by each action remembering to push. */
  const apply = useCallback((next: Partial<EditState>) => {
    setState((cur) => {
      undoStack.current.push(cur);
      if (undoStack.current.length > 100) undoStack.current.shift();
      redoStack.current = [];
      return { ...cur, ...next };
    });
    setHistVer((v) => v + 1);
  }, []);
  const undo = useCallback(() => {
    setState((cur) => {
      const prev = undoStack.current.pop();
      if (!prev) return cur;
      redoStack.current.push(cur);
      return prev;
    });
    setHistVer((v) => v + 1);
  }, []);
  const redo = useCallback(() => {
    setState((cur) => {
      const next = redoStack.current.pop();
      if (!next) return cur;
      undoStack.current.push(cur);
      return next;
    });
    setHistVer((v) => v + 1);
  }, []);

  const dirty = state.cuts.length > 0
    && (!cl.isWhole(state.cuts, sourceDuration) || state.rotate !== 0
        || state.crop != null || state.scale != null || state.fps != null);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  useEffect(() => {
    // The browser's own X cannot show a dialog of ours, so fall back to its
    // native "unsaved changes" prompt — the image editor's rule.
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  // ---- playing the EDIT rather than the file -----------------------------
  // The element plays the source; the scrubber shows the assembly. `segIndex`
  // is which cut is playing, and it is what makes a pasted copy reachable at
  // all: the same source second can appear twice, so a position here is (cut,
  // time within it) and never a source time alone.
  const [segIndex, setSegIndex] = useState(0);
  const segRef = useRef(0);
  segRef.current = segIndex;
  const cutsRef = useRef<Cut[]>(state.cuts);
  cutsRef.current = state.cuts;
  const editedDuration = cl.duration(state.cuts);
  // WHERE THE PLAYHEAD IS WHILE A GAP IS PLAYING. The element cannot help: a
  // gap is not in the file, so there is nothing for it to be at. Its position
  // is therefore kept here, in edited time, and a clock advances it — which is
  // also why the element is PAUSED throughout rather than left running behind
  // the black.
  const [gapAt, setGapAt] = useState<number | null>(null);
  const gapRef = useRef<number | null>(null);
  gapRef.current = gapAt;
  const inGap = gapAt != null;
  // WHETHER THE EDIT IS PLAYING WHILE THE ELEMENT IS NOT. `play.playing`
  // mirrors the element, and the element is paused for the whole of a gap —
  // so a flag of this window's own is what carries "playing" across the
  // black: it drives the gap clock below, and the play button and the space
  // bar read the union (`playUi`). Without it there was nothing to hand the
  // state to when playback REACHED a gap, and the gap was simply skipped.
  const [gapRun, setGapRun] = useState(false);
  const gapRunRef = useRef(false);
  gapRunRef.current = gapRun;

  // Inside a gap the element's time means nothing, so the playhead is the one
  // this window is keeping (`gapAt`). Everywhere else it is derived from the
  // element as it always was.
  const editedTime = gapAt ?? cl.editedAt(state.cuts, segIndex, play.time);

  const seekEdited = useCallback((to: number) => {
    const hit = cl.sourceAt(cutsRef.current, to);
    if (!hit) return;
    segRef.current = hit.index;
    setSegIndex(hit.index);
    const piece = cutsRef.current[hit.index];
    if (piece && cl.isGap(piece)) {
      // Park the element and hold the position ourselves. Arriving while the
      // edit is playing — the previous piece running out, or a scrub during
      // playback — keeps it playing: the gap clock takes over.
      const run = gapRunRef.current || play.playing;
      setGapAt(to);
      gapRef.current = to;
      gapRunRef.current = run;
      setGapRun(run);
      play.videoRef.current?.pause();
      return;
    }
    const resume = gapRunRef.current;
    setGapAt(null);
    gapRef.current = null;
    gapRunRef.current = false;
    setGapRun(false);
    play.seek(hit.time);
    // Out of black into material: the element takes back over mid-play.
    if (resume) void play.videoRef.current?.play();
  }, [play]);

  // The gap's own clock. Only while the EDIT is playing (`gapRun`) — a paused
  // playhead parked in a gap simply stays where it was put, exactly as it
  // would inside a piece. The element cannot drive this: it is paused for the
  // whole of the black (its `playing` is exactly what this flag is not).
  useEffect(() => {
    if (!inGap || !gapRun) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      const cuts = cutsRef.current;
      const piece = cuts[segRef.current];
      // Black plays at the playback speed too, or 2× would slow to 1× for
      // the length of every gap. The element keeps its rate while paused.
      const rate = play.videoRef.current?.playbackRate ?? 1;
      const at = (gapRef.current ?? 0) + dt * rate;
      const endOfGap = cl.cutStart(cuts, segRef.current)
        + Math.max(0, (piece?.end ?? 0) - (piece?.start ?? 0));
      if (!piece || !cl.isGap(piece) || at >= endOfGap) {
        // Out the far side: the next piece is real again (`seekEdited`
        // resumes the element), or the edit ends in black and the playhead
        // parks at its end.
        const next = segRef.current + 1;
        if (next < cuts.length) seekEdited(cl.cutStart(cuts, next) + 1e-4);
        else {
          gapRunRef.current = false;
          setGapRun(false);
          gapRef.current = endOfGap;
          setGapAt(endOfGap);
        }
        return;
      }
      gapRef.current = at;
      setGapAt(at);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inGap, gapRun]);

  // What the transport, the track and the space bar see: "playing" is the
  // EDIT playing — the element playing OR the gap clock running — and
  // play/pause toggles whichever of the two is in charge. Everything else
  // passes through.
  //
  // AND IT SPEAKS EDITED TIME. The element runs on source time, and handing
  // the transport `play` as it is put the pill's timecode, its ±5 s and frame
  // steps, the In/Out "set to playhead" buttons and the arrow keys on the
  // SOURCE clock — right while nothing had been removed, and wrong from the
  // first cut on: the pill disagreed with the track's playhead, a typed
  // timecode could land inside removed material, and an In point set from
  // the playhead was a source timestamp that Trim and Remove read as an
  // edited one. Every position the transport reads or writes goes through
  // the cutlist's own mapping now, which is the timeline the track draws.
  const editedNow = () =>
    gapRef.current ?? cl.editedAt(cutsRef.current, segRef.current, play.nowTime());
  const playUi = useMemo(() => ({
    ...play,
    playing: play.playing || gapRun,
    time: editedTime,
    duration: cl.duration(state.cuts),
    nowTime: editedNow,
    seek: seekEdited,
    stepFrame: (dir: number) => {
      play.videoRef.current?.pause();
      seekEdited(editedNow() + dir / (fps > 0 ? fps : 25));
    },
    togglePlay: () => {
      if (gapRef.current != null) {
        gapRunRef.current = !gapRunRef.current;
        setGapRun(gapRunRef.current);
        return;
      }
      play.togglePlay();
    },
  }), [play, gapRun, editedTime, state.cuts, seekEdited, fps]);

  // Skip what the edit removed: the element runs on through the source, so
  // when it plays PAST the current cut the playhead jumps to the next one.
  //
  // Two rules here are load-bearing, and getting either wrong is what made
  // scrubbing a split video crawl or stop updating altogether.
  //
  // A SEEK IN FLIGHT REPORTS A TIME THAT IS NOT A POSITION. `play.time`
  // mirrors the element, which goes on firing `timeupdate` with the old (or
  // an intermediate) time until the new one has decoded. Treating that as
  // "the playhead has left this piece" issues a corrective seek, which
  // cancels the seek in flight, whose own report issues the next one — so
  // every pointer move during a scrub started a seek that was aborted before
  // it could decode. On a long file with sparse keyframes that is exactly the
  // reported symptom: the picture stops changing.
  //
  // And ONLY PAST THE END means the piece is over (`cl.playedPast`). The old
  // test also fired when the time was more than 0.3 s BEFORE the cut's start
  // and answered that by jumping FORWARD, which is the wrong direction for
  // the one thing that produces such a time: a scrub backwards sets the index
  // and seeks, and the stale reports that follow then walked the playhead
  // forward through the cutlist rather than leaving it where it was put.
  //
  // Neither could happen before a split, which is why it looked like the
  // split's fault: with one cut there is no `next` to jump to and the whole
  // effect could only ever pause at the end.
  useEffect(() => {
    const cuts = cutsRef.current;
    const cut = cuts[segRef.current];
    if (!cut || cuts.length === 0) return;
    if (play.videoRef.current?.seeking) return;
    // Inside a gap the element is parked and its time is a leftover from the
    // piece before; the gap's own clock is what advances the playhead there.
    if (gapRef.current != null) return;
    if (!cl.playedPast(cut, play.time)) return;
    const next = segRef.current + 1;
    if (next < cuts.length) {
      // Through `seekEdited`, which knows the difference between material
      // (seek the element there) and a GAP (park the element and let the gap
      // clock carry the playhead). Seeking the element at a gap's own start
      // — a source that does not exist — clamped to zero, and the element's
      // real (positive) time then read as "past the gap's end" at once: the
      // black was simply skipped.
      seekEdited(cl.cutStart(cuts, next));
    } else if (play.playing) {
      play.togglePlay();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [play.time]);

  // ---- the marked range, in EDITED time ----------------------------------
  const range = inPoint != null && outPoint != null && outPoint > inPoint
    ? { start: inPoint, end: outPoint } : null;
  const clearRange = () => { setInPoint(null); setOutPoint(null); };

  const afterEdit = (cuts: Cut[], at: number) => {
    clearRange();
    // Land the playhead where the edit happened rather than leave it wherever
    // the old position now points, which after a removal is a different frame.
    // Through `seekEdited`, so landing IN a gap (the Gap button puts one at
    // the playhead) parks the element instead of seeking it into the gap's
    // nonexistent source — but the state set just above has not rendered yet,
    // so the ref it reads is brought forward first.
    cutsRef.current = cuts;
    seekEdited(Math.max(0, Math.min(at, cl.duration(cuts))));
  };
  const [clipLen, setClipLen] = useState(cl.duration(clipboard));
  /** Cut the piece under the playhead in two, there. It changes nothing about
   *  the video — the halves play what the one piece did — and that is the
   *  point: they are two BLOCKS now, to be moved, trimmed or deleted apart
   *  from each other. Refused at a piece's own edge, where there is nothing to
   *  divide. */
  const doSplit = () => {
    const at = editedTime;
    const next = cl.splitAt(state.cuts, at);
    if (next.length === state.cuts.length) return;
    apply({ cuts: next });
    // The playhead does not MOVE — the same edited second, the same frame —
    // but which piece it is IN has changed, and `segIndex` is what says so.
    // Left pointing at the piece that was replaced, `editedAt` clamps the
    // element's time into that piece's old range: the playhead reads back as
    // the split point and the next step or play runs from the wrong piece.
    const hit = cl.sourceAt(next, at);
    if (hit) { segRef.current = hit.index; setSegIndex(hit.index); }
  };
  // Memoized because it ALLOCATES: `splitAt` copies the whole cutlist to
  // answer a question about one button's enabled state, and this sits in the
  // render path of a component that re-renders on every frame of playback and
  // every pointer move of a scrub.
  const canSplit = useMemo(
    () => cl.splitAt(state.cuts, editedTime).length > state.cuts.length,
    [state.cuts, editedTime]);
  // (There was a Gap button here, putting black in at the playhead. Black is
  // now something you MAKE rather than insert: dragging a piece away from its
  // neighbour leaves the distance between them, so the gesture that decides
  // where the black goes is the same one that decides how long it is. A button
  // that could only ever put it at the playhead, at a length it had to guess,
  // was a second, worse way to say the same thing.)
  const doTrim = () => {
    if (!range) return;
    const next = cl.trimTo(state.cuts, range.start, range.end);
    if (!next.length) return;
    apply({ cuts: next });
    afterEdit(next, 0);
  };
  const doRemove = () => {
    if (!range) return;
    const next = cl.removeRange(state.cuts, range.start, range.end);
    if (!next.length) return;
    apply({ cuts: next });
    afterEdit(next, range.start);
  };
  // CUT AND COPY HAVE TWO ARGUMENTS, and each spelling says which it takes.
  // The marked range is one; the pieces picked on the track are the other, and
  // picking blocks is the only way to say "these three, not the black between
  // them". The BUTTONS are per-argument (`*Range` under the range's heading,
  // `*Picked` under the selection's) so a button never acts on something its
  // own group has just said is empty; only the KEYBOARD has to choose, and it
  // prefers the range, which is the finer answer — it can begin and end
  // mid-piece where a selection is whole blocks.
  const copyRange = () => {
    if (!range) return;
    clipboard = cl.slice(state.cuts, range.start, range.end);
    setClipLen(cl.duration(clipboard));
  };
  const cutRange = () => { if (range) { copyRange(); doRemove(); } };
  const copyPicked = () => {
    if (!picked) return;
    // Verbatim, not normalized: two picked pieces that meet in the source were
    // split deliberately, and `insertAt` is what decides whether the paste
    // joins them again.
    clipboard = picked.pieces();
    setClipLen(cl.duration(clipboard));
  };
  // The clipboard is filled only if the removal actually happened — removing
  // every piece is refused (a video of nothing cannot be rendered), and a Cut
  // that quietly did half of itself is worse than one that did nothing. The
  // pieces are read BEFORE the removal, since that is the cutlist they name.
  const cutPicked = () => {
    if (!picked) return;
    const pieces = picked.pieces();
    if (!pieces.length || !picked.remove()) return;
    clipboard = pieces;
    setClipLen(cl.duration(clipboard));
  };
  const doCopy = () => { if (range) copyRange(); else copyPicked(); };
  const doCut = () => { if (range) cutRange(); else cutPicked(); };
  const doPaste = () => {
    if (!clipboard.length) return;
    const next = cl.insertAt(state.cuts, editedTime, clipboard);
    apply({ cuts: next });
    afterEdit(next, editedTime + cl.duration(clipboard));
  };

  // ---- the Video menu ----------------------------------------------------
  const [dialog, setDialog] = useState<null | "resize" | "fps">(null);
  const [cropMode, setCropMode] = useState(false);
  const [cropDraft, setCropDraft] = useState<
    { x: number; y: number; w: number; h: number } | null>(null);

  // What the render will produce, so the header can say it and Resize can
  // start from it.
  const srcW = activeFile?.width ?? 0;
  const srcH = activeFile?.height ?? 0;
  const rotated = state.rotate % 180 === 90
    ? { w: srcH, h: srcW } : { w: srcW, h: srcH };
  const cropped = state.crop
    ? { w: Math.round(rotated.w * state.crop.w),
        h: Math.round(rotated.h * state.crop.h) }
    : rotated;
  const outSize = state.scale ?? cropped;

  // WHAT THE VIDEO MENU HAS PENDING, in the order the menu offers it. Read
  // from the plan rather than remembered, so undo and redo move it too.
  const pending = useMemo(() => {
    const out: { key: string; icon: string; text: string }[] = [];
    if (state.rotate !== 0) {
      out.push({ key: "rotate", icon: "rotate_right",
                 text: `${state.rotate}°` });
    }
    if (state.crop) {
      out.push({ key: "crop", icon: "crop",
                 text: `${cropped.w}×${cropped.h}` });
    }
    if (state.scale) {
      out.push({ key: "scale", icon: "photo_size_select_large",
                 text: `${state.scale.w}×${state.scale.h}` });
    }
    // The rate is the one change the picture cannot show at all — the element
    // plays the file at the file's own rate whatever the plan says. It says
    // just the number: the capsule is the list of what is PENDING, so "when
    // saved" on one of four equally-pending rows read as a caveat that only
    // applied to that one.
    if (state.fps != null && Math.abs(state.fps - fps) > 0.005) {
      out.push({ key: "fps", icon: "speed",
                 text: t("{fps} fps", { fps: String(state.fps) }) });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.rotate, state.crop, state.scale, state.fps, fps, cropped.w, cropped.h, t]);

  // ---- the picture: zoom, pan, and what the bars leave of the canvas ------
  // The annotator's model, from the same hook, with the annotator's inset: the
  // canvas bar at the top left and the media bar / zoom cluster along the
  // bottom float OVER the video, so the fit has to be into what they leave.
  //
  // THE FRAME IS THE ROTATED PICTURE, STRETCHED SO THE CROP COMES OUT AT THE
  // OUTPUT'S ASPECT. Rotate and crop were both visible in the preview and a
  // RESIZE was not — a 1920×1080 film resized to 1080×1080 went on playing
  // wide, and the squashed picture only appeared in the rendered file. It is
  // one line of arithmetic: the crop region is `crop.w × crop.h` of the frame,
  // and we want it displayed at `sw : sh`, so the frame's own aspect has to be
  // `(sw/sh) · (crop.h/crop.w)`. With no crop that is just the output's
  // aspect. Doing it on the FRAME rather than on the video keeps the crop
  // overlay — which is drawn in fractions of the frame — lined up with what it
  // is dimming, and makes the picture inside the rectangle show exactly the
  // distortion the render will apply.
  const stage = useMemo(() => {
    const w = rotated.w || 1, h = rotated.h || 1;
    if (!state.scale || !state.scale.w || !state.scale.h) return { w, h };
    const cw = state.crop?.w || 1, ch = state.crop?.h || 1;
    const aspect = (state.scale.w / state.scale.h) * (ch / cw);
    // Keep the frame's AREA about that of the picture, so switching a size on
    // and off does not also change how big it is on screen.
    const area = w * h;
    return { w: Math.sqrt(area * aspect), h: Math.sqrt(area / aspect) };
  }, [rotated.w, rotated.h, state.scale, state.crop]);
  const zp = useZoomPan(stage.w, stage.h, {
    inset: CANVAS_INSET,
    fitKey: `${itemId}:${activeFile?.id ?? ""}:${state.rotate}`
      + `:${Math.round(stage.w)}x${Math.round(stage.h)}`,
  });
  // Every wheel over the stage is the picture's, ctrl held or not — see
  // `useWheel`, which is what lets the browser's own page zoom be refused.
  useWheel(zp.viewportRef, (e) => {
    e.preventDefault();
    const r = zp.viewportRef.current?.getBoundingClientRect();
    zp.zoomAt(r ? e.clientX - r.left : zp.vp.w / 2,
              r ? e.clientY - r.top : zp.vp.h / 2,
              e.deltaY < 0 ? 1.1 : 0.9);
  });
  /** Drag the picture about. There is no draw tool here to compete with it, so
   *  it needs no modifier — a plain drag on the canvas pans. */
  const startPan = (e: React.MouseEvent) => {
    if (cropMode || e.button !== 0) return;
    const from = { x: e.clientX, y: e.clientY };
    const pan0 = zp.pan;
    const move = (ev: MouseEvent) => {
      zp.setPan({ x: pan0.x + (ev.clientX - from.x), y: pan0.y + (ev.clientY - from.y) });
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  // The file's own streams: whether there is any audio to offer a volume
  // control for, and the subtitle/audio tracks the picker lists.
  const { data: mediaTracks } = useQuery({
    queryKey: ["item-tracks", itemId],
    queryFn: () => api.itemTracks(itemId),
    enabled: itemId >= 0,
  });
  const hasAudio = (mediaTracks?.tracks ?? []).some((x) => x.kind === "audio");
  const subTracks = useMemo(
    () => (mediaTracks?.tracks ?? []).filter((x) => x.kind === "subtitle"),
    [mediaTracks]);
  const audioStreams = useMemo(
    () => (mediaTracks?.tracks ?? []).filter((x) => x.kind === "audio"),
    [mediaTracks]);

  const rotateBy = (deg: number) => {
    // THE CROP TURNS WITH THE PICTURE (`cropRect.rotateCrop`). It is stored as
    // fractions of the ROTATED frame, so the same four numbers mean something
    // else after a quarter turn: left alone, the rectangle slid sideways and
    // came out the wrong shape. It used to be CLEARED instead, on the argument
    // that it could not be turned into one meaning the same thing — it can,
    // exactly, and clearing threw somebody's rectangle away to avoid four
    // lines of arithmetic. The DRAFT turns too, or a rotation mid-crop leaves
    // the rectangle you are still drawing over different pixels.
    //
    // A SIZE TURNS WITH IT TOO. A quarter turn swaps the picture's axes,
    // and a size typed before it was typed for the picture as it stood — left
    // alone it made the render squeeze a portrait frame into a landscape one,
    // which is what "a rotated video with flipped width and height" was. The
    // backend cannot repair it either: `output_size` takes the plan's scale
    // literally, and it is right to, since a size somebody typed is a size
    // somebody typed.
    const quarter = deg % 180 === 90 || deg % 180 === -90;
    setCropDraft((c) => rotateCrop(c, deg));
    apply({
      rotate: (((state.rotate + deg) % 360) + 360) % 360,
      crop: rotateCrop(state.crop, deg),
      scale: state.scale && quarter
        ? { w: state.scale.h, h: state.scale.w } : state.scale,
    });
  };

  // ---- saving ------------------------------------------------------------
  const [saveErr, setSaveErr] = useState("");
  // Asked when leaving an unrendered cutlist behind. It carries WHAT TO DO —
  // the image editor's `guardedClose` shape — because there are now four ways
  // out and each proceeds differently: the mode switch puts the whole file
  // back and hops to the annotate half, the window's ✕ and Escape close the
  // window, and the close question's "just this tab" closes the tab. It was a
  // bare boolean whose Discard always switched to annotate, because that was
  // the only exit that used it; the ✕ then reused the prompt and discarding
  // CLOSED nothing — it left you in the other half of the window you had just
  // asked to close. `going` is only the WORDING.
  const [leavePrompt, setLeavePrompt] = useState<
    null | { proceed: () => void; going: "annotate" | "close" }>(null);
  /** Every way out of this window goes through here. */
  const guardedLeave = useCallback(
    (proceed: () => void, going: "annotate" | "close" = "close") => {
      if (dirtyRef.current) setLeavePrompt({ proceed, going });
      else proceed();
    }, []);
  // A render in flight for THIS item, whoever started it and whenever. Asked
  // on open and polled while one runs: the job outlives the window, so the
  // window asks rather than remembers.
  const { data: jobState } = useQuery({
    queryKey: ["video-edit", itemId],
    queryFn: () => api.videoEditStatus(itemId),
    refetchInterval: (q) => (q.state.data?.job_id != null ? 700 : false),
    // …and keep counting while the window is in the BACKGROUND, which React
    // Query does not do by default. This modal is specifically about work that
    // continues while you are somewhere else: a bar that froze the moment the
    // window was hidden would still be showing a stale percentage — or a
    // render that had already finished — when you came back to it.
    refetchIntervalInBackground: true,
    enabled: itemId >= 0,
  });
  const liveJob = jobState?.job_id != null ? jobState : null;
  const wasRunning = useRef(false);
  useEffect(() => {
    if (liveJob) { wasRunning.current = true; return; }
    if (!wasRunning.current) return;
    // It finished (or was stopped): the item may have a new active file, so
    // everything reloads and the cutlist starts again from what is on screen.
    wasRunning.current = false;
    void qc.invalidateQueries({ queryKey: ["item", itemId] });
    void qc.invalidateQueries({ queryKey: ["items"] });
    bumpLibrary();
    // A SAVE TO A NEW ITEM OPENS IT, in a tab beside the one that made it —
    // which keeps its own cutlist, since nothing about the source changed. The
    // render is a background job and the new item does not exist until it
    // finishes, so which item it is has to be found afterwards: the edit LINK
    // the render writes is the answer, and the ids taken before the save are
    // what tell the new one from any earlier save's.
    const before = savedAsNew.current;
    savedAsNew.current = null;
    if (before) {
      void api.itemRelationships(itemId).then((rels) => {
        const fresh = rels
          .filter((r) => r.kind === "edit" && r.outgoing && !before.has(r.id))
          .sort((a, b) => b.id - a.id)[0];
        if (fresh) setEditorItem(fresh.other_item_id);
      }).catch(() => { /* the tab is a convenience, not the save */ });
    }
  }, [liveJob, itemId, qc, setEditorItem]);

  /** The edit links this item had before a save-to-a-new-item was queued, or
   *  null when the save in flight writes onto this item. */
  const savedAsNew = useRef<Set<number> | null>(null);
  const doSave = async (newItem = false) => {
    if (!dirtyRef.current) return;
    setSaveErr("");
    const body: VideoEditPlan = {
      cuts: state.cuts.map((c) => ({ start: c.start, end: c.end })),
      rotate: state.rotate,
      crop: state.crop,
      scale: state.scale,
      fps: state.fps,
      new_item: newItem,
    };
    try {
      savedAsNew.current = newItem
        ? new Set((await api.itemRelationships(itemId))
            .filter((r) => r.kind === "edit" && r.outgoing).map((r) => r.id))
        : null;
      await api.videoEdit(itemId, body);
      void qc.invalidateQueries({ queryKey: ["video-edit", itemId] });
      void qc.invalidateQueries({ queryKey: ["ml-jobs"] });
    } catch (e) {
      savedAsNew.current = null;
      setSaveErr(errText(e));
    }
  };
  const stopSave = async () => {
    const id = liveJob?.job_id;
    if (id == null) return;
    try { await api.cancelJob(id); } catch { /* already finished */ }
    void qc.invalidateQueries({ queryKey: ["video-edit", itemId] });
  };

  // ---- closing -----------------------------------------------------------
  const [closeAsk, setCloseAsk] = useState(false);
  const tabsRef = useRef(editorTabs);
  tabsRef.current = editorTabs;
  const requestCloseRef = useRef(() => {});
  requestCloseRef.current = () => {
    if (closeAsk) { setCloseAsk(false); return; }
    // WINDOW-OR-TAB IS ASKED FIRST, and only then the unsaved cuts: which
    // exit the prompt is about depends on that answer. ⌘/Ctrl+W is
    // deliberately NOT hijacked — the browser reserves it and mostly never
    // delivers the event — so this prompt is where the question is asked
    // instead. With one tab the window IS the tab and there is
    // nothing to ask, so it goes straight to the guard — which is what Escape
    // used to skip entirely, closing the window and taking an unrendered
    // cutlist with it while the ✕ two pixels away asked first.
    if (tabsRef.current.length > 1) { setCloseAsk(true); return; }
    guardedLeave(() => closeItemWindow());
  };
  // The space bar toggles the EDIT's playback, gap clock included (`playUi`).
  const keys = useRef({ undo, redo, doCut, doCopy, doPaste, doSave,
                        play: playUi, cropMode, dialog, asking: false });
  keys.current = { undo, redo, doCut, doCopy, doPaste, doSave, play: playUi,
                   cropMode, dialog, asking: leavePrompt != null };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e)) return;
      const k = keys.current;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) k.redo(); else k.undo();
      } else if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault(); void k.doSave();
      } else if (mod && e.key.toLowerCase() === "x") { e.preventDefault(); k.doCut(); }
      else if (mod && e.key.toLowerCase() === "c") { e.preventDefault(); k.doCopy(); }
      else if (mod && e.key.toLowerCase() === "v") { e.preventDefault(); k.doPaste(); }
      else if (mod) { /* leave the browser's own shortcuts alone */ }
      else if (e.key !== "Escape" && videoKeyAction(e)) {
        // THE TRANSPORT'S OWN KEYS — Space/K, ←/→ by a frame, J/L to
        // shuttle (`shared/videoKeys`, shared with the annotator so one
        // keystroke cannot mean two things across the window's two halves).
        // Escape is asked FIRST because this window's is about leaving it.
        e.preventDefault();
        runVideoKey(videoKeyAction(e)!, k.play);
      }
      else if (e.key === "Escape") {
        // The unsaved-cuts question first: Escape is what OPENED it, and the
        // backdrop dismisses it, so the key that reaches past it to ask the
        // same question again is the one gesture that cannot mean "no".
        if (k.asking) setLeavePrompt(null);
        else if (k.cropMode) { setCropMode(false); setCropDraft(null); }
        else if (k.dialog) setDialog(null);
        else requestCloseRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!detail || !activeFile) return null;

  // (The joins used to be ticks drawn on a plain scrubber. The track draws the
  // PIECES now, so the joins are simply where two of them meet.)

  const rangeBtn = (icon: string, label: string, title: string,
                    onClick: () => void, on: boolean) => (
    <button
      onClick={onClick}
      disabled={!on}
      title={title}
      style={{
        display: "flex", alignItems: "center", gap: 4, height: 28,
        padding: "0 10px", borderRadius: "var(--r-3)", fontSize: "var(--fs-2)",
        fontFamily: "inherit", cursor: on ? "pointer" : "default",
        border: "1px solid var(--border-strong)", background: "var(--panel-2)",
        color: on ? "var(--text-2)" : "var(--muted-3)", opacity: on ? 1 : 0.6,
      }}
    >
      <Icon name={icon} size={14} />{label}
    </button>
  );

  return (
    <div style={{ position: "fixed", inset: 0, display: "flex",
      flexDirection: "column", background: "var(--bg)" }}>
      <WindowTabs
        ids={editorTabs}
        active={itemId}
        onSelect={(id) => setEditorItem(id)}
        onClose={(id) => (editorTabs.length <= 1 ? closeItemWindow() : closeEditorTab(id))}
        suffix={filmTabSuffix(play, itemId)}
        t={t}
      />
      {/* The image editor's header, in the same order, with a Video menu where
          its Image menu is. */}
      <div style={{ height: 48, flex: "0 0 48px", background: "var(--panel)",
        borderBottom: "1px solid var(--border)", display: "flex",
        alignItems: "center", padding: "0 12px", gap: 8 }}>
        {/* Undo/redo has left the header and floats over the picture with the
            Video menu (`CanvasBars`): both act on the video, and the header is
            for what the window is. */}
        {/* The window's two halves, BEFORE the name — it sat past Save at the
            very end. Leaving EDIT can lose a cutlist nobody has rendered yet,
            so it asks: the image editor's three-way prompt, with Save queueing
            the render. */}
        <ModeSwitch
          t={t}
          mode="edit"
          onPick={(m) => {
            if (m !== "annotate") return;
            // Discarding here is not destructive — nothing has been written —
            // so it simply puts the whole file back before hopping over.
            guardedLeave(() => {
              apply({ cuts: cl.whole(sourceDuration), rotate: 0, crop: null,
                      scale: null, fps: null });
              setEditorMode(itemId, "annotate");
            }, "annotate");
          }}
          editIcon="movie_edit"
        />
        <Divider />
        {/* The name and nothing else. The ⋯ that used to sit here held one
            entry — Show in library — and closing the window is already the way
            back to it, so it was a menu for a thing the ✕ next to it does. */}
        <HeaderActions t={t} alwaysFolded actions={[]}>
          {/* The size and length under the name are what the RENDER will
              produce, not what the file is — this window is about the video
              you are making, and the numbers move as you cut. */}
          <ItemTitle
            name={detail.name}
            subtitle={`${outSize.w}×${outSize.h} · ${fmtDuration(editedDuration)}`}
          />
        </HeaderActions>
        <ThemeMenu t={t} value={winTheme} onChange={setWinTheme} />
        <Divider />
        {/* Save and its menu — the image editor's pair, doing the same two
            things: a new file on this item, or an item of its own. */}
        <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 1 }}>
          <button
            onClick={() => void doSave()}
            disabled={!dirty || !!liveJob}
            title={!dirty ? t("No changes to save")
                          : t("Render the edit into a new file on this item")}
            style={{ display: "flex", alignItems: "center", gap: 6, height: 32,
              padding: "0 14px", borderRadius: "8px 0 0 8px", border: "none",
              background: (!dirty || liveJob) ? "var(--border-soft)" : "var(--accent)",
              color: (!dirty || liveJob) ? "var(--muted-3)" : "var(--on-accent)",
              fontWeight: 600, fontSize: "var(--fs-3)", fontFamily: "inherit",
              cursor: (!dirty || liveJob) ? "default" : "pointer" }}
          >
            <Icon name="save" size={18} />{t("Save")}
          </button>
          <RowMenu always icon="expand_more" title={t("More save options")} minWidth={240}
            buttonStyle={{ width: 24, height: 32, borderRadius: "0 8px 8px 0",
              background: (!dirty || liveJob) ? "var(--border-soft)" : "var(--accent)",
              color: (!dirty || liveJob) ? "var(--muted)" : "var(--on-accent)" }}
            actions={[
              { icon: "library_add", label: t("Save to a new item"),
                disabled: !dirty || !!liveJob, onClick: () => void doSave(true) },
              { icon: "history", label: t("Revert to saved"), disabled: !dirty,
                onClick: () => apply({ cuts: cl.whole(sourceDuration), rotate: 0,
                                       crop: null, scale: null, fps: null }) },
              // No close of any kind: the tab's ✕ and the window's own control
              // already do that, and this is a menu about what happens to the
              // CUTS. Discarding on the way out is offered there.
            ]} />
        </div>
        {/* The window's own ✕, LAST and with no divider before it: it ends the
            row rather than starting a group, and it is the only visible way
            out now that a single tab shows no strip. It asks the same way
            leaving edit does — the cutlist is unrendered work. */}
        <WindowCloseBtn
          t={t}
          onClose={() => guardedLeave(() => closeItemWindow())}
        />
      </div>

      {/* The picture. */}
      <div
        ref={zp.viewportRef}
        onMouseDown={startPan}
        style={{ flex: 1, minHeight: 0, position: "relative", display: "flex",
          alignItems: "center", justifyContent: "center",
          background: "var(--bg-deep)", overflow: "hidden",
          cursor: cropMode ? "crosshair" : "grab" }}
      >
        {/* What you do TO the video, floating over it: undo/redo, then the
            Video menu. One pill per group. */}
        <CanvasBarRow>
          <CanvasBar>
            <UndoRedoButtons
              canUndo={undoStack.current.length > 0}
              canRedo={redoStack.current.length > 0}
              onUndo={undo} onRedo={redo} t={t}
            />
          </CanvasBar>
          <CanvasBar>
            <RowMenu always icon="movie_edit" minWidth={240}
              title={t("Video")}
              buttonStyle={{ width: "auto", height: 32, gap: 4, padding: "0 10px",
                borderRadius: "var(--r-4)", color: "var(--text-2)", fontSize: "var(--fs-3)", fontWeight: 600 }}
              label={<>{t("Video")}<Icon name="expand_more" size={15} color="var(--muted)" /></>}
              actions={[
                { icon: "rotate_left", label: t("Rotate left"), onClick: () => rotateBy(-90) },
                { icon: "rotate_right", label: t("Rotate right"), onClick: () => rotateBy(90) },
                { icon: "crop", label: t("Crop…"), onClick: () => { setCropMode(true); setCropDraft(state.crop); } },
                { icon: "photo_size_select_large", label: t("Resize…"), onClick: () => setDialog("resize") },
                { icon: "speed", label: t("Frame rate…"), onClick: () => setDialog("fps") },
                // There is no reset row here. The capsule over the picture
                // lists what is pending and carries the way back, which is
                // where somebody looking at the change already is.
              ]} />
          </CanvasBar>
        </CanvasBarRow>
        <VideoStage
          fileId={activeFile.id}
          videoRef={play.videoRef}
          zp={zp}
          rotate={state.rotate}
          crop={cropMode ? cropDraft : state.crop}
          cropMode={cropMode}
          onCropDraft={setCropDraft}
          blank={inGap}
          subTracks={subTracks}
        />
        {play.error && (
          <div style={{ position: "absolute", color: "var(--muted)", fontSize: "var(--fs-3)" }}>
            {t("This video cannot be played in this browser.")}
          </div>
        )}
        {/* WHAT THE RENDER WILL DO TO THE PICTURE, in one capsule in the
            corner opposite the media bar. It was one line for the frame rate
            alone — the only change the preview cannot show — and the rest were
            invisible unless you happened to notice the picture's shape: a
            rotation, a crop and a resize are all things you set once through a
            menu and then cannot see the state of. The capsule is the state,
            and its ✕ is the way back, which is why the Video menu no longer
            carries one.

            A rate EQUAL to the source's says nothing and is left out, since a
            capsule reading the rate a video already has is noise on every
            other edit. */}
        {pending.length > 0 && (
          <div style={{ position: "absolute", right: 14, top: 12, zIndex: 11,
            display: "flex", alignItems: "center", gap: 8, minHeight: 26,
            padding: "3px 5px 3px 10px", borderRadius: 13,
            background: "var(--surface-float)",
            border: "1px solid var(--accent)",
            boxShadow: "var(--shadow-2)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10,
              flexWrap: "wrap" }}>
              {pending.map((p) => (
                <span key={p.key} style={{ display: "flex", alignItems: "center",
                  gap: 5 }}>
                  <Icon name={p.icon} size={14} color="var(--accent)" />
                  <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                    color: "var(--accent)", whiteSpace: "nowrap" }}>
                    {p.text}
                  </span>
                </span>
              ))}
            </div>
            <IconButton icon="close" size={20} glyph={14} tone="accent" shape="round"
              onClick={() => {
                setCropMode(false);
                setCropDraft(null);
                apply({ rotate: 0, crop: null, scale: null, fps: null });
              }}
              title={t("Undo the picture changes")} style={{ flex: "0 0 auto" }} />
          </div>
        )}
        {/* The crop bar sits ABOVE the playback controls, clear of the strip
            along the bottom that the transport owns (`CANVAS_INSET.b`). At
            `bottom: 14` it was in exactly that strip, bottom-centre, which is
            where `PlaybackBar` is — so the one bar that says how to finish a
            crop was underneath five buttons. */}
        {cropMode && (
          <div style={{ position: "absolute", bottom: CANVAS_INSET.b + 10,
            left: "50%", zIndex: 11,
            transform: "translateX(-50%)", display: "flex", gap: 8, padding: 8,
            borderRadius: "var(--r-6)", background: "var(--surface-float)",
            border: "1px solid var(--border)",
            boxShadow: "var(--shadow-2)" }}>
            <span style={{ fontSize: "var(--fs-2)", color: "var(--muted)", alignSelf: "center" }}>
              {cropDraft ? t("Drag again to redraw") : t("Drag a rectangle over the picture")}
            </span>
            <button onClick={() => { setCropMode(false); setCropDraft(null); }}
              style={{ height: 28, padding: "0 12px", borderRadius: "var(--r-3)",
                border: "1px solid var(--border-strong)", background: "transparent",
                color: "var(--text-2)", fontSize: "var(--fs-3)", fontFamily: "inherit",
                cursor: "pointer" }}>
              {t("Cancel")}
            </button>
            <button
              onClick={() => { apply({ crop: cropDraft }); setCropMode(false); }}
              disabled={!cropDraft}
              style={{ height: 28, padding: "0 12px", borderRadius: "var(--r-3)", border: "none",
                background: cropDraft ? "var(--accent)" : "var(--border-soft)",
                color: cropDraft ? "var(--on-accent)" : "var(--muted-3)",
                fontSize: "var(--fs-3)", fontWeight: 600, fontFamily: "inherit",
                cursor: cropDraft ? "pointer" : "default" }}>
              {t("Apply crop")}
            </button>
          </div>
        )}

        {/* Media bar, bottom-LEFT, and the zoom cluster opposite it: the
            annotator's two, from the same components. They belong to the
            PICTURE rather than to the edit — how fast it plays, how loud, which
            subtitles, how close you are looking — so they are the same controls
            in the same corners in both windows, and this one simply did not
            have them. */}
        <div
          onMouseDown={(e) => e.stopPropagation()}
          style={{ position: "absolute", left: 14, bottom: 12, display: "flex",
            alignItems: "center", gap: 2, padding: 3,
            background: "var(--surface-float)", border: "1px solid var(--border)",
            borderRadius: "var(--r-5)", boxShadow: "var(--shadow-2)" }}
        >
          <SpeedControl rate={play.rate} onRate={play.setRate} />
          {hasAudio && (
            <VolumeControl muted={play.muted} volume={play.volume}
              onToggle={play.toggleMuted} onVolume={play.setVolume} />
          )}
          <TrackControls
            videoRef={play.videoRef} subTracks={subTracks} audioTracks={audioStreams}
          />
        </div>
        {/* Playback, bottom-CENTRE, between the media bar and the zoom
            cluster: the annotator's, in the annotator's place. */}
        <PlaybackBar play={playUi} fps={fps} t={t} />
        <div onMouseDown={(e) => e.stopPropagation()}>
          <ZoomControls zp={zp} t={t} />
        </div>
      </div>

      {/* The transport — the annotator's, from the same component — with the
          cutlist's own actions on the row under it. */}
      <div style={{ flex: "0 0 auto", display: "flex", flexDirection: "column",
        gap: 7, padding: "9px 14px", borderTop: "1px solid var(--border)",
        background: "var(--panel)" }}>
        {/* The assembly, piece by piece, scrubbed in EDITED time: this is the
            video you are making, not the file on disk. Reordering, trimming
            and deleting a piece happen here; what is PICKED here and the
            marked range below the ruler are the two arguments the buttons
            underneath work on. */}
        <CutTrack
          cuts={state.cuts}
          sourceDuration={sourceDuration}
          fps={fps}
          time={editedTime}
          onSeek={seekEdited}
          range={{ start: inPoint, end: outPoint }}
          onRangeChange={(s, e) => { setInPoint(s); setOutPoint(e); }}
          onCommit={(next) => {
            if (!next.length) return;
            apply({ cuts: next });
            // The playhead was pointing at an edited second that a reorder or
            // a trim has moved something else to. Land it where it was rather
            // than leaving it on whatever is now under it.
            afterEdit(next, Math.min(editedTime, cl.duration(next)));
          }}
          playing={playUi.playing}
          onSelection={setPicked}
          t={t}
        />
        {/* THE ACTIONS, GROUPED BY WHAT THEY TAKE, because they take three
            different arguments. Split and Paste happen AT THE PLAYHEAD; Trim,
            Remove, Cut and Copy act on the MARKED RANGE and do nothing without
            one; Remove, Cut and Copy again — the same verbs, deliberately —
            act on the PIECES PICKED on the track, and that group appears only
            while something is picked. In one undivided row those facts had to
            be learned from which buttons happened to be dim, and the range's
            own timecodes sat at the far left as a caption over the playhead
            actions. Each group now says what it works on, above its own
            buttons — and the in/out FIELDS end the row, which is where they
            have always been, one row further down now that the playback
            controls float over the picture. */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 10,
          flexWrap: "wrap" }}>
          <ActionGroup label={t("At the playhead")}
            value={formatTimecode(editedTime, fps, true)}>
            {rangeBtn("call_split", t("Split"),
              t("Cut the piece under the playhead in two"), doSplit, canSplit)}
            {rangeBtn("content_paste",
              clipLen > 0 ? `${t("Paste")} ${fmtDuration(clipLen)}` : t("Paste"),
              t("Insert what was cut or copied at the playhead"),
              doPaste, clipLen > 0)}
          </ActionGroup>
          <div style={{ width: 1, alignSelf: "stretch",
            background: "var(--border)" }} />
          <ActionGroup
            label={t("Marked range")}
            value={range
              ? `${formatTimecode(range.start, fps, true)} – ${formatTimecode(range.end, fps, true)}`
              : t("none")}
            /* The way OUT of a marked range, beside the range itself. The
               transport row has always had one, at the very end of a row of
               ten controls, where nobody looking at these four buttons was
               going to find it. */
            onClear={clearRange}
            clearDisabled={!range}
            clearTitle={t("Clear the marked range")}
          >
            {rangeBtn("content_cut", t("Trim"),
              t("Keep only the marked range"), doTrim, !!range)}
            {rangeBtn("backspace", t("Remove"),
              t("Take the marked range out of the video"), doRemove, !!range)}
            {rangeBtn("cut", t("Cut"),
              t("Remove the range and keep it to paste"), cutRange, !!range)}
            {rangeBtn("content_copy", t("Copy"),
              t("Keep the range to paste"), copyRange, !!range)}
          </ActionGroup>
          {/* THE PIECES YOU HAVE PICKED, which is a THIRD argument — not the
              playhead and not the marked range — so it is a group of its own,
              behind its own divider, and appears only while something is
              picked. It sat beside the zoom bar, which is about the VIEW: the
              one control up there that changed the film. */}
          {picked && (
            <>
              <div style={{ width: 1, alignSelf: "stretch",
                background: "var(--border)" }} />
              <ActionGroup
                label={t("Selected pieces")}
                value={String(picked.count)}
              >
                {/* The same three verbs the marked range has, in the same
                    order, because they mean the same things — only the
                    argument differs, which is what the two headings say. Cut
                    and Copy live HERE rather than falling into the range's
                    buttons: a Copy under a heading reading "Marked range: none"
                    would be a button whose group has just said it has nothing
                    to work on. */}
                {rangeBtn("delete", t("Remove"),
                  t("Remove the selected pieces from the video"),
                  picked.remove, true)}
                {rangeBtn("cut", t("Cut"),
                  t("Remove the selected pieces and keep them to paste"),
                  cutPicked, true)}
                {rangeBtn("content_copy", t("Copy"),
                  t("Keep the selected pieces to paste"), copyPicked, true)}
              </ActionGroup>
            </>
          )}
          <span style={{ flex: 1 }} />
          {dirty && (
            <span style={{ fontSize: "var(--fs-2)", color: "var(--muted)" }}>
              {tn({ one: "1 piece", other: "{n} pieces" },
                  state.cuts.length)} ·{" "}
              {fmtDuration(editedDuration)}
              {sourceDuration > 0 && ` (${t("was")} ${fmtDuration(sourceDuration)})`}
            </span>
          )}
          <RangeFields
            play={playUi} fps={fps} t={t}
            inPoint={inPoint} outPoint={outPoint}
            onIn={setInPoint} onOut={setOutPoint} onClear={clearRange}
          />
        </div>
        {saveErr && (
          <div style={{ fontSize: "var(--fs-2)", color: "var(--red-text)" }}>{saveErr}</div>
        )}
      </div>

      {dialog === "resize" && (
        <SizeDialog
          w={outSize.w} h={outSize.h} t={t}
          onCancel={() => setDialog(null)}
          onApply={(w, h) => { apply({ scale: { w, h } }); setDialog(null); }}
        />
      )}
      {dialog === "fps" && (
        <FpsDialog
          value={state.fps ?? fps} t={t}
          onCancel={() => setDialog(null)}
          onApply={(v) => { apply({ fps: v }); setDialog(null); }}
        />
      )}

      {/* The render, over everything: it is the one thing in here that is not
          reversible from in here, and the window must not look editable while
          it runs. It is NOT a lock on the WORK — closing the window leaves the
          job in the background-task list, and reopening finds it again. */}
      {liveJob && (
        <RenderProgress
          progress={liveJob.progress} status={liveJob.status}
          message={liveJob.message} t={t} onStop={() => void stopSave()}
          lastTab={editorTabs.length <= 1}
          onClose={() => (editorTabs.length <= 1
            ? closeItemWindow() : closeEditorTab(itemId))}
        />
      )}


      {leavePrompt && (
        <ConfirmModal t={t}
          title={t("Unsaved cuts")}
          body={leavePrompt.going === "close"
            ? t("This video has cuts that have not been rendered yet. Save them before closing?")
            : t("This video has cuts that have not been rendered yet. Save them before leaving?")}
          plain={{ label: t("Discard"), danger: true }}
          answer={{ label: t("Save") }}
          onResult={(r) => {
            const go = leavePrompt.proceed;
            setLeavePrompt(null);
            if (r === "plain") go();
            else if (r === "answer") void doSave();
          }} />
      )}

      {closeAsk && (
        <ConfirmModal t={t} {...closeChoice(t, detail.name)}
          // BOTH answers are guarded, and the tab one has to be: the cutlist
          // belongs to the tab on screen, so closing that tab loses it just
          // as closing the window does.
          onResult={(r) => {
            setCloseAsk(false);
            if (r === "answer") guardedLeave(() => closeItemWindow());
            else if (r === "plain") guardedLeave(() => closeEditorTab(itemId));
          }}
          />
      )}
    </div>
  );
}

/**
 * One group of cutlist actions, under a heading that names WHAT THEY ACT ON —
 * the playhead, or the marked range — and shows its current value.
 *
 * The heading is the whole point: these seven buttons take two different
 * arguments, and in one flat row the only thing saying so was which of them
 * happened to be dim. `onClear` is offered where the argument is something you
 * can put down again, which is the range and not the playhead.
 */
function ActionGroup({ label, value, onClear, clearTitle, clearDisabled,
                      children }: {
  label: string;
  value: string;
  onClear?: () => void;
  clearTitle?: string;
  /** Draw it dim and inert rather than taking it away — a control that comes
   *  and go(es) with the thing it acts on is one nobody learns the place of,
   *  and its absence shifts the two labels beside it. */
  clearDisabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4,
      flex: "0 0 auto" }}>
      <span style={{ display: "flex", alignItems: "center", gap: 5,
        paddingLeft: 2, fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>
        {label}
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
          color: "var(--muted-3)" }}>{value}</span>
        {onClear && (
          <IconButton icon="close" size={15} glyph={12} color={clearDisabled ? "var(--muted-3)" : "var(--muted-2)"} disabled={clearDisabled}
            onClick={clearDisabled ? undefined : onClear}
            title={clearTitle ?? ""} />
        )}
      </span>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {children}
      </div>
    </div>
  );
}

/** One row of the Video / Save menus. */

/**
 * The video, turned as the plan says, with the crop rectangle over it.
 *
 * **The frame is the ROTATED picture**, sized by `useZoomPan` exactly as the
 * annotator's canvas is — so zooming, panning and the safe area all work here
 * with no arithmetic of their own, and the crop rectangle is drawn in the
 * frame the crop is actually expressed in. It used to be capped by hand
 * (`maxWidth: 60vh` for a quarter turn, because a rotated element still lays
 * out at its unrotated size); the element is now given the frame's size the
 * other way round and turned about its own centre, which says the same thing
 * without a viewport unit in it.
 */
function VideoStage({ fileId, videoRef, zp, rotate, crop, cropMode, onCropDraft,
                      blank, subTracks }: {
  fileId: number;
  videoRef: React.RefObject<HTMLVideoElement>;
  zp: ZoomPan;
  rotate: number;
  crop: { x: number; y: number; w: number; h: number } | null;
  cropMode: boolean;
  onCropDraft: (c: { x: number; y: number; w: number; h: number } | null) => void;
  /** The playhead is inside a GAP. The element is parked on whatever frame it
   *  last showed, which is a frame of the film and not what plays here — so it
   *  is covered rather than left to say something untrue. */
  blank?: boolean;
  subTracks: MediaTrack[];
}) {
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const quarter = rotate % 180 === 90;

  const at = (e: React.MouseEvent) => {
    const r = box.current?.getBoundingClientRect();
    if (!r || !r.width || !r.height) return null;
    return {
      x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
      y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
    };
  };

  return (
    <div
      ref={box}
      onMouseDown={(e) => {
        if (!cropMode) return;
        const p = at(e);
        if (!p) return;
        drag.current = p;
        onCropDraft(null);
        e.preventDefault();
      }}
      onMouseMove={(e) => {
        if (!cropMode || !drag.current) return;
        const p = at(e);
        if (!p) return;
        const x = Math.min(drag.current.x, p.x);
        const y = Math.min(drag.current.y, p.y);
        const w = Math.abs(p.x - drag.current.x);
        const h = Math.abs(p.y - drag.current.y);
        onCropDraft(w > 0.02 && h > 0.02 ? { x, y, w, h } : null);
      }}
      onMouseUp={() => { drag.current = null; }}
      style={{ position: "relative", flex: "0 0 auto",
        width: zp.frameW, height: zp.frameH,
        transform: `translate(${zp.pan.x + zp.origin.x}px, ${zp.pan.y + zp.origin.y}px)`,
        cursor: cropMode ? "crosshair" : "default" }}
    >
      <video
        ref={videoRef}
        src={api.fileUrl(fileId)}
        draggable={false}
        // No native controls: the transport below IS the control, and two of
        // them would be two playheads to keep in step.
        style={{
          position: "absolute", left: "50%", top: "50%", display: "block",
          // A quarter turn swaps the axes: the element is laid out the other
          // way round and then turned into the frame.
          width: quarter ? zp.frameH : zp.frameW,
          height: quarter ? zp.frameW : zp.frameH,
          // FILL, not the element default. A <video> letterboxes inside a box
          // of another aspect, so a frame stretched to show a pending resize
          // would have shown the same picture with bars either side of it —
          // the one thing the stretch exists to make visible.
          objectFit: "fill",
          background: "#000", pointerEvents: "none",
          transform: `translate(-50%, -50%) rotate(${rotate}deg)`,
        }}
      >
        {subTracks.map((tr) => (
          <track key={tr.index} kind="subtitles"
            src={api.subtitleUrl(fileId, tr.index)}
            srcLang={tr.language ?? undefined}
            label={subtitleLabel(tr)} />
        ))}
      </video>
      {/* Black over the parked frame while a gap is playing. Covering rather
          than hiding, so the stage keeps its size and the picture does not
          jump as the playhead crosses in and out. */}
      {blank && (
        <div style={{ position: "absolute", inset: 0, background: "#000",
          display: "flex", alignItems: "center", justifyContent: "center",
          pointerEvents: "none" }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
            letterSpacing: "0.08em", textTransform: "uppercase",
            color: "var(--on-scrim-4)" }}>gap</span>
        </div>
      )}
      {crop && (
        <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
          {/* What is being cut away, dimmed — four rectangles rather than a
              huge box-shadow, so the crop reads as "what is left" at any
              size. */}
          <Dim style={{ left: 0, top: 0, right: 0, height: `${crop.y * 100}%` }} />
          <Dim style={{ left: 0, top: `${(crop.y + crop.h) * 100}%`, right: 0, bottom: 0 }} />
          <Dim style={{ left: 0, top: `${crop.y * 100}%`, width: `${crop.x * 100}%`, height: `${crop.h * 100}%` }} />
          <Dim style={{ left: `${(crop.x + crop.w) * 100}%`, top: `${crop.y * 100}%`, right: 0, height: `${crop.h * 100}%` }} />
          <div style={{ position: "absolute",
            left: `${crop.x * 100}%`, top: `${crop.y * 100}%`,
            width: `${crop.w * 100}%`, height: `${crop.h * 100}%`,
            border: "1px solid var(--accent)",
            boxShadow: "var(--ring-shadow)" }} />
        </div>
      )}
    </div>
  );
}

function Dim({ style }: { style: React.CSSProperties }) {
  return <div style={{ position: "absolute", background: "var(--scrim-2)", ...style }} />;
}

/** Resize: width and height, with the aspect ratio held unless it is unlinked. */
function SizeDialog({ w, h, t, onCancel, onApply }: {
  w: number; h: number;
  t: (s: string) => string;
  onCancel: () => void;
  onApply: (w: number, h: number) => void;
}) {
  const [width, setWidth] = useState(w);
  const [height, setHeight] = useState(h);
  const [linked, setLinked] = useState(true);
  const ratio = w > 0 && h > 0 ? w / h : 1;
  return (
    <Dialog title={t("Resize video")} t={t} onCancel={onCancel}
      onApply={() => onApply(Math.max(2, width), Math.max(2, height))}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
        <NumField label={t("Width")} value={width} onChange={(v) => {
          setWidth(v);
          if (linked) setHeight(Math.max(2, Math.round(v / ratio)));
        }} />
        <NumField label={t("Height")} value={height} onChange={(v) => {
          setHeight(v);
          if (linked) setWidth(Math.max(2, Math.round(v * ratio)));
        }} />
        <IconButton icon={linked ? "link" : "link_off"} size={30} glyph={16} color={linked ? "var(--accent)" : "var(--muted-2)"} bordered
          onClick={() => setLinked((v) => !v)}
          title={linked ? t("Aspect ratio locked") : t("Aspect ratio free")} />
      </div>
      <p style={{ fontSize: "var(--fs-2)", color: "var(--muted)", margin: "10px 0 0" }}>
        {t("Both are rounded down to an even number of pixels when the video is written.")}
      </p>
    </Dialog>
  );
}

/** Frame rate: a number, with the common ones offered beside it. */
function FpsDialog({ value, t, onCancel, onApply }: {
  value: number;
  t: (s: string) => string;
  onCancel: () => void;
  onApply: (v: number) => void;
}) {
  const [v, setV] = useState(Math.round(value * 100) / 100);
  return (
    <Dialog title={t("Frame rate")} t={t} onCancel={onCancel} onApply={() => onApply(v)}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 6, flexWrap: "wrap" }}>
        <NumField label={t("Frames per second")} value={v} onChange={setV} step={0.01} />
        {[23.976, 24, 25, 30, 50, 60].map((n) => (
          <button key={n} onClick={() => setV(n)}
            style={{ height: 30, padding: "0 9px", borderRadius: "var(--r-3)",
              border: `1px solid ${Math.abs(v - n) < 0.005 ? "var(--accent)" : "var(--border-strong)"}`,
              background: "transparent", fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
              color: Math.abs(v - n) < 0.005 ? "var(--accent)" : "var(--text-2)",
              cursor: "pointer" }}>
            {n}
          </button>
        ))}
      </div>
    </Dialog>
  );
}

function Dialog({ title, children, t, onCancel, onApply }: {
  title: string; children: React.ReactNode; t: (s: string) => string;
  onCancel: () => void; onApply: () => void;
}) {
  return (
    <ConfirmModal t={t} title={title} body={children}
      answer={{ label: t("Apply") }}
      onResult={(r) => { if (r === "answer") onApply(); else onCancel(); }} />
  );
}

function NumField({ label, value, onChange, step = 1 }: {
  label: string; value: number; onChange: (v: number) => void; step?: number;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: "var(--fs-2)", color: "var(--muted)" }}>{label}</span>
      <input
        type="number" value={value} step={step} min={1}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        style={{ width: 96, height: 30, padding: "0 8px", borderRadius: "var(--r-3)",
          border: "1px solid var(--border-strong)", background: "var(--panel-2)",
          color: "var(--text-bright)", fontFamily: "var(--mono)", fontSize: "var(--fs-3)" }}
      />
    </label>
  );
}

/** The render, while it runs: the bar, and the way to stop it — the shared
 *  confirm sheet with a progress body, not dismissable: closing IT is a
 *  choice (leave the render running and go), never a stray click. */
function RenderProgress({ progress, status, message, t, onStop, onClose, lastTab }: {
  progress: number; status: string; message: string;
  t: (s: string, vars?: Record<string, string>) => string;
  onStop: () => void;
  /** Leave the render running and go: it is a background job, and this modal
   *  is only the window watching it. Without a way out the overlay covered
   *  every control the sentence above it points at — including the ✕ that
   *  would have closed the tab. */
  onClose: () => void;
  lastTab: boolean;
}) {
  const queued = status === "queued";
  return (
    <ConfirmModal
      t={t}
      title={t("Saving the video")}
      dismissable={false}
      body={<>
        <div style={{ marginBottom: 14 }}>
          {queued
            ? t("Waiting for the other background tasks to finish.")
            : t("You can close this window — it keeps going in the background, and the Tasks list can stop it.")}
        </div>
        <ProgressBar value={progress} height={8} track="var(--border-soft)" />
        <div style={{ marginTop: 8, fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                      color: "var(--muted-2)" }}>
          {queued ? t("Queued") : `${progress}%`}
          {message ? ` · ${message}` : ""}
        </div>
      </>}
      plain={{ label: t("Stop") }}
      answer={{ label: lastTab ? t("Close the window") : t("Close the tab") }}
      onResult={(r) => { if (r === "plain") onStop(); else if (r === "answer") onClose(); }}
    />
  );
}
