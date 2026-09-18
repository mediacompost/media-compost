import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef,
                useState } from "react";
import { pickNext } from "../../shared/pickList";
import { numPref } from "../../shared/storage";
import { SplitHandle, useSplit } from "../../shared/Split";
import { storage } from "../../shared/storage";
import { RECORD_ICON } from "../../shared/metaEnums";
import { rowBackground } from "../../shared/Row";
import { IconButton } from "../../shared/IconButton";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, FileVersion, ItemDetail, JobOut, MediaTrack, SequenceInfo,
         TagInstance, TextRegion } from "../api";
import { Icon } from "../../shared/Icon";
import { useUI } from "../store";
// `bumpEdits`, NEVER `bumpLibrary`. Every write this window makes is a HAND
// EDIT — a tag, a box, a face, a caption, a still — and `bumpLibrary` is the
// sweep for a BACKGROUND process (an import batch, a job finishing): it
// invalidates the broad `["item"]` prefix, the whole tag catalog and every
// list the app has, which is the storm `bumpEdits` exists to narrow (see
// `invalidation.ts`, where `EDIT_KEYS` says so in as many words). This window
// used it thirteen times, from when it was a separate BROWSER WINDOW with a
// cache of its own that had to be swept wholesale; it shares the library's
// cache now, so the sweep was only ever the cost. Measured on one tag added
// here: 29 requests before, 14 after.
import { bumpEdits } from "../invalidation";
import { tagFieldInput, tagFieldName } from "../tags";
import { useZoomPan } from "../useZoomPan";
import { useWheel } from "../useWheel";
import { tagColor } from "../tagColor";
import { checkerCss } from "../canvasChecker";
import { FACE_OUTLINE_RADIUS } from "../faceOutline";
import { ZoomControls } from "./shared/ZoomControls";
import { UndoRedoButtons } from "./shared/UndoRedoButtons";
import { CANVAS_INSET, CanvasBar, CanvasBarRow } from "./shared/CanvasBars";
import { WindowTabs, filmTabSuffix } from "./shared/WindowTabs";
import { ConfirmModal } from "../../shared/ConfirmModal";
import { RowMenu } from "./shared/RowMenu";
import { closeChoice } from "./shared/closeChoice";
import { runVideoKey, videoKeyAction } from "./shared/videoKeys";
import { ModeSwitch } from "./shared/ModeSwitch";
import { HeaderActions } from "./shared/HeaderActions";
import { ItemTitle } from "./shared/ItemTitle";
import { FileChip } from "./shared/FileChip";
import { Divider, WindowCloseBtn } from "./shared/iconButtons";
import { ThemeMenu, useWindowTheme } from "./shared/ThemeMenu";
import { AiActionButtons, CaptionsSection, GroupedTags,
         rowKeyName, tagRowKey } from "./PropertiesPanel";
import { PeopleSection } from "./PeopleSection";
import { TextSection, textRowKey } from "./TextSection";
import { enginesOf, inRegion, liveRoots } from "../text/regions";
import { useChosenEngine } from "../text/engineChoice";
import { fileToRef, pointsToRef, quadToFile, refToFile } from "../refFrame";
import { PlacesSection } from "./PlacesSection";
import { EventsSection } from "./EventsSection";
import { SELECTION_BAR_GAP, SELECTION_BAR_H, SelectionBar, SelectionBarSlot,
         SelectionReport } from "../../shared/SelectionBar";
import { UNDO_BAR_H, UndoBar } from "./shared/UndoBar";
import { UndoRunnerSlot, useUndoBar } from "./shared/useUndoBar";
import { usePeopleSelection } from "./shared/usePeopleSelection";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { TagSuggestion } from "./TagAutocomplete";
import { fmtDuration } from "../api";
import { useVideoPlayback } from "./shared/useVideoPlayback";
import { RangeActions, TagTrack } from "./TagTrack";
import type { TagRangeBlock } from "./TagTrack";
import {
  JumpBtns, MenuButton, PopRow, RangeField, SpeedControl, TimecodeField,
  PlaybackBar, RangeFields, TrackControls, TransportPopover, VBtn, VolumeControl,
  subtitleLabel,
} from "./shared/VideoTransport";
import { addSpan, entryContains, nextStop, subtractSpan } from "../videoTracks";
import {
  TC_SEGMENTS, formatTimecode, getSegment, parseTimecode, segmentAt, segmentMax,
  setSegment,
} from "../timecode";
import { useAnchorRect } from "../../shared/AnchoredDropdown";
import { TagAutocomplete, fetchTagNameSuggestions } from "./TagAutocomplete";
import { byRecent, rememberSubject, useRecentSubjects } from "../subjects/recent";
import { useT } from "../i18n";
import { useErrText } from "../../shared/i18n";
import { isTypingTarget } from "../../shared/typingTarget";

/**
 * Standalone tag-annotation editor (its own `?annotate=<id>` window). Draw,
 * move, resize and re-label bounding boxes over the image; zoom + pan; step to
 * the previous/next image. Every change is applied to the server immediately
 * (no save button); undo/redo reconciles the server to a snapshot history.
 *
 * A single box may carry *several* tags (e.g. "person" + "wearing_hat"): each
 * tag is one server-side `ItemTagBox` sharing the box's geometry. Boxes at the
 * same geometry are merged back into one visual box on load.
 *
 * Box geometry is kept internally in the *active file's* frame (0..1 fractions)
 * so it maps directly onto the displayed image; the API maps that to the item's
 * reference frame via the active file's crop.
 */

interface Label {
  tag: string;
  group: number | null; // tag group the box's instance belongs to
}
interface Box {
  cid: string;                 // stable client id (tracks a box across undo/redo)
  labels: Label[];             // one or more tags sharing this geometry
  x: number; y: number; w: number; h: number; // active-file-frame fractions
  // Video only: the placement's time range (seconds; end null = single frame)
  // and the track (moving subject) it belongs to. Undefined for image boxes.
  start?: number | null;
  end?: number | null;
  trackId?: number | null;
  // Optional POLYGON outline, active-file-frame fractions. While set,
  // x/y/w/h are its bounding box (kept in step locally AND by the server) —
  // a rect is just a polygon with four edges the columns can carry alone.
  points?: [number, number][];
}

/** The tick / cross beside the face-naming field. Solid rather than ghosted:
 *  they sit over the picture, where a faint control is unreadable on a white
 *  manga page. */
const faceFieldBtn: React.CSSProperties = {
  flex: "0 0 auto", width: 26, height: 26, borderRadius: "var(--r-3)",
  display: "flex", alignItems: "center", justifyContent: "center",
  cursor: "pointer", background: "var(--overlay-chrome)",
  border: "1px solid var(--border-strong)", color: "var(--muted)",
};


let _cid = 0;
const newCid = () => `c${Date.now().toString(36)}_${_cid++}`;
// Server-id lookup key: one server box per (visual box, tag).
const sk = (cid: string, tag: string) => `${cid}::${tag}`;

/** A rectangle in the active file's frame (0..1 fractions) — a face's box, or
 *  the geometry half of a `Box`. */
interface Rect { x: number; y: number; w: number; h: number }

/** Is this point inside the ELLIPSE that rectangle carries?
 *
 *  A face is drawn as an oval and the browser hit-tests its outline that way
 *  (`border-radius` clips pointer events), so the click that PICKS one has to
 *  agree — or two heads side by side would each be selectable from a corner
 *  that belongs to neither. */
const inFaceOutline = (p: { x: number; y: number }, r: Rect) => {
  const dx = (p.x - (r.x + r.w / 2)) / ((r.w || 1) / 2);
  const dy = (p.y - (r.y + r.h / 2)) / ((r.h || 1) / 2);
  return dx * dx + dy * dy <= 1;
};

// Map a stored reference-frame box into the active file's frame.
// Container format → a MIME type we can ask the browser about. `canPlayType`
// reflects THIS browser's own capability (Safari answers "" for Matroska while
// Chromium answers "maybe"), so it's the right per-browser signal for whether to
// warn — never a hardcoded "these formats are unsupported" guess.
const VIDEO_MIME: Record<string, string> = {
  mkv: "video/x-matroska", mp4: "video/mp4", m4v: "video/mp4",
  webm: "video/webm", ogg: "video/ogg", ogv: "video/ogg",
  mov: "video/quicktime", quicktime: "video/quicktime",
  avi: "video/x-msvideo", wmv: "video/x-ms-wmv", flv: "video/x-flv",
  ts: "video/mp2t", mpg: "video/mpeg", mpeg: "video/mpeg",
};
function browserCantPlay(format?: string): boolean {
  if (!format) return false;
  const mime = VIDEO_MIME[format.toLowerCase()];
  if (!mime) return false; // unknown format → let the runtime error decide
  try {
    return document.createElement("video").canPlayType(mime) === "";
  } catch { return false; }
}

// Where each film was left off, by item id — restored when it is opened again.
// A handful of numbers, so one key holds them all; the cap keeps a long-lived
// library from growing an unbounded blob.
/** The narrowest this window's sidebar goes. The same floor the library's
 *  right sidebar has (`App.RIGHT_MIN`) — it is the same panel with the same
 *  rows in it, and it was 240 here against 264 there, so one window allowed a
 *  width the other refused for one component. */
const ANNOTATOR_SIDEBAR_MIN = 260;

/** The timeline panel's height, and where it is remembered. The floor is the
 *  scale row, the ruler, one track and the actions row; the ceiling leaves the
 *  picture at least a third of the window, because a film you cannot see is
 *  not something to tag. */
const BOTTOM_H_KEY = "mc.annotatorTimelineH";
const BOTTOM_MIN = 150;
const bottomMax = () => Math.max(BOTTOM_MIN, window.innerHeight * 0.62);

const TIME_KEY = "mc.annotatorTime";
const TIME_KEEP = 100;

function readTimes(): Record<string, number> {
  try {
    const raw = JSON.parse(storage.get(TIME_KEY) || "{}");
    return raw && typeof raw === "object" ? raw as Record<string, number> : {};
  } catch { return {}; }
}

function rememberedTime(itemId: number): number {
  const t = readTimes()[String(itemId)];
  return typeof t === "number" && isFinite(t) && t > 0 ? t : 0;
}

function rememberTime(itemId: number, seconds: number): void {
  const times = readTimes();
  // Re-insert so the most recently watched film is last: plain assignment keeps
  // an existing key in its old position, and the prune below drops from the
  // front.
  delete times[String(itemId)];
  times[String(itemId)] = Math.round(seconds * 100) / 100;
  const keys = Object.keys(times);
  for (const k of keys.slice(0, Math.max(0, keys.length - TIME_KEEP))) delete times[k];
  try { storage.set(TIME_KEY, JSON.stringify(times)); } catch { /* full/blocked */ }
}

const near = (a: number, b: number) => Math.abs(a - b) < 1e-6;
const ptsSame = (a?: [number, number][], b?: [number, number][]) => {
  if (!a && !b) return true;
  if (!a || !b || a.length !== b.length) return false;
  return a.every((p, i) => near(p[0], b[i][0]) && near(p[1], b[i][1]));
};
const geoSame = (a: Box, b: Box) =>
  near(a.x, b.x) && near(a.y, b.y) && near(a.w, b.w) && near(a.h, b.h)
  && ptsSame(a.points, b.points);
// Geometry key used to merge same-position server boxes into one visual box.
// The polygon is part of the geometry: two shapes over one bounding box are
// two boxes, and merging them would hand one shape the other's tags.
const geoKey = (x: number, y: number, w: number, h: number,
                pts?: [number, number][] | null) =>
  [x, y, w, h].map((v) => v.toFixed(4)).join(",")
  + (pts ? "|" + pts.map((pt) => pt.map((v) => v.toFixed(4)).join(":")).join(",") : "");

/** Even-odd point-in-polygon — the hit test a polygon box's outline needs,
 *  since its bounding box covers plenty the shape does not. */
const inPoly = (f: { x: number; y: number }, pts: [number, number][]) => {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > f.y) !== (yj > f.y)
        && f.x < ((xj - xi) * (f.y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
};
/** Within `tol` of any edge — a thin polygon's outline is otherwise nearly
 *  impossible to click, and a miss starts a draft nobody wanted. */
const nearPolyEdge = (f: { x: number; y: number }, pts: [number, number][],
                      tol: number) => {
  for (let i = 0; i < pts.length; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[(i + 1) % pts.length];
    const dx = bx - ax, dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1,
      ((f.x - ax) * dx + (f.y - ay) * dy) / len2)) : 0;
    const px = ax + t * dx, py = ay + t * dy;
    if (Math.hypot(f.x - px, f.y - py) <= tol) return true;
  }
  return false;
};
/** Which edge a point is within `tol` of — the nearest, so two edges meeting
 *  at a sharp corner answer the one actually being aimed at. -1 for none. */
const nearestEdge = (f: { x: number; y: number }, pts: [number, number][],
                     tol: number) => {
  let best = -1, bestD = tol;
  for (let i = 0; i < pts.length; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[(i + 1) % pts.length];
    const dx = bx - ax, dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1,
      ((f.x - ax) * dx + (f.y - ay) * dy) / len2)) : 0;
    const d = Math.hypot(f.x - (ax + t * dx), f.y - (ay + t * dy));
    if (d <= bestD) { bestD = d; best = i; }
  }
  return best;
};
const polyBounds = (pts: [number, number][]) => {
  const xs = pts.map((pt) => pt[0]), ys = pts.map((pt) => pt[1]);
  const x = Math.min(...xs), y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
};
/** Map a polygon's vertices through the affine carrying one bounding box
 *  onto another — the box-mode transform: dragging a polygon's bbox handles
 *  scales the shape rather than silently losing it. */
const affinePts = (
  pts: [number, number][],
  from: { x: number; y: number; w: number; h: number },
  to: { x: number; y: number; w: number; h: number },
): [number, number][] => pts.map(([px, py]) => [
  to.x + (from.w ? (px - from.x) / from.w : 0) * to.w,
  to.y + (from.h ? (py - from.y) / from.h : 0) * to.h,
]);
/** Rotate a shape about a point, in FRACTIONAL coordinates but by a
 *  SCREEN angle: box coordinates are fractions of the file's width and
 *  height, so a plain rotation there shears anything that is not square.
 *  `aspect` is the frame's width over its height — x is taken into that
 *  space, turned, and brought back.
 *
 *  The result is a polygon whatever it started as, which is exactly what
 *  makes rotation cost nothing downstream: `points` is the geometry and the
 *  rectangle columns are its bounding box, the invariant the whole polygon
 *  feature already rests on. */
const rotatePts = (pts: [number, number][], cx: number, cy: number,
                   ang: number, aspect: number): [number, number][] => {
  const cos = Math.cos(ang), sin = Math.sin(ang);
  return pts.map(([px, py]) => {
    const dx = (px - cx) * aspect, dy = py - cy;
    return [cx + (dx * cos - dy * sin) / aspect, cy + dx * sin + dy * cos];
  });
};
/** The screen angle from a shape's centre to a point, in the same space. */
const angleTo = (f: { x: number; y: number }, cx: number, cy: number,
                 aspect: number) => Math.atan2(f.y - cy, (f.x - cx) * aspect);

/** A rect read AS a polygon with four edges — what poly-mode editing of a
 *  plain box starts from. */
const rectPts = (b: { x: number; y: number; w: number; h: number },
                 ): [number, number][] => [
  [b.x, b.y], [b.x + b.w, b.y], [b.x + b.w, b.y + b.h], [b.x, b.y + b.h],
];
export type DrawShape = "box" | "octagon" | "poly";
/** The square a polygon CORNER is grabbed by, in screen px. Bigger than the
 *  dot it holds (10-12px): the dot is sized to be looked at and the grab to
 *  be hit — see the handle's own note. */
const VERT_GRAB = 20;
/** How close to a polygon's own outline a press means THE EDGE rather than
 *  the whole shape. Fractions of the frame, so it is the same band at any
 *  zoom. Inside it a drag carries the edge's two corners; outside it, in the
 *  interior, the shape moves as one. */
const EDGE_DEAD = 0.012;
/** How much of each side an octagon's corner cut takes. 1/3 rather than the
 *  regular octagon's 0.293: this is a shape somebody drags out around a
 *  subject, not a tiling, and the regular one reads as a rectangle with the
 *  corners nicked off. */
const OCT_CUT = 1 / 3;
/** A rect read as a REGULAR-ish octagon inscribed in it — the shape an
 *  octagon-mode drag leaves behind. Corner-cut proportions of the box's own
 *  width and height, so a wide box gives a wide octagon rather than one with
 *  square corners. */
const octPts = (b: { x: number; y: number; w: number; h: number },
                ): [number, number][] => {
  const cx = b.w * OCT_CUT, cy = b.h * OCT_CUT;
  const x0 = b.x, x1 = b.x + b.w, y0 = b.y, y1 = b.y + b.h;
  return [
    [x0 + cx, y0], [x1 - cx, y0], [x1, y0 + cy], [x1, y1 - cy],
    [x1 - cx, y1], [x0 + cx, y1], [x0, y1 - cy], [x0, y0 + cy],
  ];
};

/** The polygon, drawn inside its bbox-positioned div. The viewBox is the
 *  unit square and the stroke is `non-scaling`, so the shape stretches with
 *  the box while the line stays a screen-pixel width. */
const PolyShape = ({ b, pts, stroke, fill, width, dash, ring }: {
  b: { x: number; y: number; w: number; h: number };
  pts: [number, number][];
  stroke: string; fill: string; width: number; dash?: string; ring?: boolean;
}) => {
  const norm = pts.map(([px, py]) =>
    `${(px - b.x) / (b.w || 1)},${(py - b.y) / (b.h || 1)}`).join(" ");
  return (
    <svg viewBox="0 0 1 1" preserveAspectRatio="none"
         style={{ position: "absolute", inset: 0, width: "100%",
                  height: "100%", overflow: "visible", display: "block",
                  pointerEvents: "none" }}>
      {ring && (
        <polygon points={norm} fill="none" stroke="var(--on-scrim)"
                 strokeWidth={width + 3} vectorEffect="non-scaling-stroke" />
      )}
      <polygon points={norm} fill={fill} stroke={stroke} strokeWidth={width}
               strokeDasharray={dash} vectorEffect="non-scaling-stroke"
               strokeLinejoin="round" />
    </svg>
  );
};

/** The sidebar's lists, in the order the tab strip shows them. The same five
 *  the library sidebar has for an item — a picture being annotated is the same
 *  picture, and coming here to name a face only to find the list is somewhere
 *  else is the gap this closes. */
type SideTab = "stills" | "tags" | "subjects" | "places" | "events"
  | "captions" | "text";
const SIDE_TABS: { id: SideTab; icon: string; label: string;
                   /** Only on a film — an image has no frames to keep. */
                   video?: boolean;
                   /** Only on a picture — a film has nothing for a text box
                    *  to sit on (its text is read on a STILL), the mirror of
                    *  `video` and filtered in BOTH places that flag is. */
                   image?: boolean }[] = [
  // FIRST, and only on a film. A still is not something the film IS — it is a
  // frame you have kept — so it never belonged among the lists that say what
  // the picture is about, and under the Tags tab it was a second list wedged
  // beneath the tag list it has nothing to do with.
  { id: "stills", icon: "photo_camera", label: "Stills", video: true },
  { id: "tags", icon: "sell", label: "Tags" },
  { id: "subjects", icon: RECORD_ICON.subject, label: "Subjects" },
  { id: "places", icon: RECORD_ICON.place, label: "Places" },
  { id: "events", icon: RECORD_ICON.event, label: "Events" },
  { id: "captions", icon: "notes", label: "Captions" },
  // LAST — the array order is the strip order AND the JSX order (Stills was
  // written last once and appeared under Tags while its button sat first).
  { id: "text", icon: "document_scanner", label: "Text", image: true },
  // (Instructions and Links were tabs here too. Both are about the item's
  // place among OTHER items — how it was made from them, what it came from and
  // led to — which is a question you ask in the library, in front of a grid
  // you can drag from. This window is for saying what is in ONE picture, and
  // six tabs of that is already a strip. They are in the library's sidebar,
  // unchanged.)
];
const TAB_KEY = "mc.annotatorTab";

/** Roughly how wide the bottom-right zoom cluster is (`ZoomControls`): three
 *  30 px buttons, a 44 px readout, its gaps and padding, plus its own 14 px
 *  inset. The hint opposite keeps clear of it — an overlap is the one thing
 *  neither of them can notice about the other. */
const ZOOM_CLUSTER = 176;

/**
 * Step through the sequence the open item belongs to — a manga chapter is read
 * page by page, and reaching for the grid to do it is leaving the window.
 *
 * WHICH sequence the walk follows is held in state and never re-derived from
 * the item: a page can be in two chapters, so reading "the item's main
 * sequence" afresh on every step would hand the walk to whichever sequence the
 * NEXT page happens to call its main one, and you would finish a chapter you
 * never opened. The pick only falls back (to the main sequence, else the first)
 * when the item is in no sequence the pick names — which is exactly the case
 * where it has nothing to say.
 *
 * Navigation goes through `navigateEditor`, so a page REPLACES the tab it was
 * reached from; `setEditorItem` would leave a tab behind per page turned.
 *
 * It floats over the TOP-RIGHT of the picture, the same chrome as the zoom
 * cluster and the media bar: turning the page is about the picture, and in the
 * header it sat among the window's own controls. Both chevrons are to the
 * RIGHT of the counter and the bar is anchored to the right edge, so the bar
 * grows leftwards as the counter widens — `9 / 58` becoming `10 / 58` leaves
 * the two buttons exactly where the hand left them. `tabular-nums` keeps it
 * still within a digit count as well.
 */
function SequenceNav({ seqs, itemId, pick, onPick, onGo, t }: {
  seqs: SequenceInfo[];
  itemId: number;
  pick: number | null;
  onPick: (id: number) => void;
  onGo: (id: number) => void;
  t: (s: string) => string;
}) {
  // WHICH OCCURRENCE the walk is standing on — the membership row, not the
  // item. A book's blank page sits at positions 1, 5 and 9 and is ONE item,
  // so a walk that asked "where is this item" always answered 1 and the
  // forward chevron always went to page 2, whichever copy you had opened.
  // The spot is remembered as we step, falls back to the card the window was
  // opened on where the grid named one (`selMembers`), and then to the
  // item's first occurrence — which is the case where the window was pointed
  // here by something that names no card (a tab, a link) and there is
  // nothing better to assume.
  const [spot, setSpot] = useState<number | null>(null);
  // WHICH CARD THE WINDOW WAS OPENED ON, when the grid named one: a
  // sequence view tracks the occurrence a gesture picked (`selMembers`), and
  // for a repeated page that is the difference between opening page 60 and
  // reading 59 — from which the first Next showed the same picture again.
  // Only until this nav has stepped once, and only where the named member
  // really is this item's (the walk's own validity test).
  const picked = useUI((s) => s.selMembers);
  const seq = seqs.find((s) => s.id === pick)
    ?? seqs.find((s) => s.is_main) ?? seqs[0] ?? null;
  const held = seq && spot != null
    ? seq.members.findIndex((m) => m.id === spot && m.item_id === itemId) : -1;
  const opened = seq && spot == null && picked.size === 1
    ? seq.members.findIndex((m) => m.id === [...picked][0]
                                   && m.item_id === itemId) : -1;
  const at = held >= 0 ? held : opened >= 0 ? opened
    : (seq ? seq.members.findIndex((m) => m.item_id === itemId) : -1);
  if (!seq || at < 0) return null;
  const prev = at > 0 ? seq.members[at - 1] : null;
  const next = at + 1 < seq.members.length ? seq.members[at + 1] : null;
  const many = seqs.length > 1;
  const step = (m: { id: number; item_id: number } | null,
                title: string, icon: string) => (
    <button
      // The spot moves with the step, so turning the page onto a repeated
      // one lands on THAT copy — and stepping between two identical pages
      // changes the counter even though the picture does not.
      onClick={() => { if (m) { setSpot(m.id); onGo(m.item_id); } }}
      disabled={!m}
      title={title}
      className={m ? "hoverable" : undefined}
      style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: "0 0 auto", width: 24, height: 24, borderRadius: "var(--r-7)", border: "none", background: "transparent", color: m ? "var(--text-2)" : "var(--muted-2)", cursor: m ? "pointer" : "default", opacity: m ? 1 : 0.4 }}
    >
      <Icon name={icon} size={18} />
    </button>
  );
  return (
    // Stop the mousedown reaching the canvas draw handler, or a box flashes
    // behind the bar — the same guard the zoom cluster and media bar carry.
    <div
      onMouseDown={(e) => e.stopPropagation()}
      style={{ position: "absolute", right: 14, top: 12, zIndex: 5, display: "flex", alignItems: "center", gap: 2, padding: 3, background: "var(--surface-float)", border: "1px solid var(--border)", borderRadius: "var(--r-5)", boxShadow: "var(--shadow-2)" }}
    >
      {/* Which sequence to step through: the current one ticked, each with
          where this page sits in it. Inert with one sequence. */}
      <RowMenu always icon={null} disabled={!many} minWidth={260}
        title={many ? t("Which sequence to step through") : seq.name}
        buttonStyle={{ width: "auto", height: 24, gap: 3, padding: many ? "0 6px 0 10px" : "0 10px",
          borderRadius: "var(--r-7)", background: "var(--border-soft)", color: "var(--text-3)",
          fontFamily: "var(--mono)", fontSize: "var(--fs-2)", fontWeight: 600,
          fontVariantNumeric: "tabular-nums", opacity: 1 }}
        label={<>
          {at + 1} / {seq.members.length}
          {many && <Icon name="expand_more" size={13} color="var(--muted)" />}
        </>}
        actions={seqs.map((s) => {
          const cur = s.id === seq.id;
          // The spot only means anything in the sequence being walked; for
          // the others "where is this page" is its first copy.
          const i = cur ? at : s.members.findIndex((m) => m.item_id === itemId);
          return {
            checked: cur, label: s.name,
            hint: s.is_main ? t("main") : undefined,
            trailing: i >= 0 ? `${i + 1} / ${s.members.length}` : String(s.members.length),
            onClick: () => { setSpot(null); onPick(s.id); },
          };
        })} />
      {step(prev, t("Previous in this sequence"), "chevron_left")}
      {step(next, t("Next in this sequence"), "chevron_right")}
    </div>
  );
}

export function AnnotationOverlay() {
  const t = useT();
  const errText = useErrText();
  const { editorItemId, editorTabs, setEditorItem, navigateEditor, closeEditorTab,
          closeItemWindow, setEditorMode } = useUI();
  const qc = useQueryClient();
  // The window is opened on one item, and that is the item it annotates.
  //
  // A film's STILLS used to be edited inside this same window — `stillId`
  // pointed the whole sidebar at a captured frame while the transport stayed
  // below it — and they are not any more: a still is an ordinary image item,
  // so it opens as its own TAB (double-click its row), where it gets the
  // window's full width and every section rather than a cramped "Still tags"
  // list wedged under the film's own. That also ends a half-state nothing
  // could explain — a picture of one frame on screen while the playhead was
  // free to move to another. `hostId` and `itemId` are still two names
  // because the reading below distinguishes the film that owns the playhead
  // from the item being annotated, and keeping both spellings is what makes
  // the stills list, the transport and the tag lanes read as being about the
  // film.
  const hostId = editorItemId;
  const itemId = hostId;
  // Readable from a callback registered once — `setTabs` writes to WHICHEVER
  // item tab is open, and is handed out as a stable function.
  const itemIdRef = useRef(itemId);
  itemIdRef.current = itemId;

  const { data: hostItem } = useQuery({
    queryKey: ["item", hostId],
    queryFn: () => api.item(hostId as number),
    enabled: hostId != null,
    // Turning the page must not blank the window. Without this the query has
    // no data for the new id for as long as the request takes, `hostItem` goes
    // undefined, and the guard below replaces the entire window with an empty
    // rectangle — a white flash between every two pages of a chapter. Holding
    // the previous item keeps a coherent frame on screen (old picture, old
    // sidebar) until the new one arrives, which is a page turn rather than a
    // blink.
    placeholderData: (prev) => prev,
  });
  const item = hostItem;
  // NO WHOLE-CATALOG READ HERE. This window used to hold `["tags"]` — the
  // app's largest reply, the entire tag set — solely to build the tag
  // autocomplete's suggestion list, re-sorted in JS on every arrival. Every
  // edit made in the annotator invalidates that key, so adding one tag
  // re-fetched and re-sorted the whole catalog: measured at 454 ms a fetch on
  // a small demo library, THREE times per edit, and the reply is 62 MB at
  // 250,000 tags. `GET /api/tags/names` is what that field wants and what
  // every other tag field in the app already uses — the match is made in SQL,
  // ranked by count, 2-5 ms and one page of rows.
  // Faces are a second, independent set of rectangles over the same picture, so
  // they get their own layer and their own drawing mode rather than becoming a
  // kind of tag box — a face is evidence about a person, not a label.
  // Which list the sidebar is showing. The FACES layer rides on it: the boxes
  // are drawn exactly while the Subjects tab is open, because that is the tab
  // they belong to — a toggle in the header was a second control for one
  // question, and the tab already carries Detect faces.
  // SEVERAL at once, ⌘/Ctrl-click, exactly as the library sidebar's tabs do —
  // the same gesture has to mean the same thing in both windows.
  //
  // PER ITEM TAB, because the tabs of this window are different KINDS of
  // thing: a film has a Stills list and a picture does not, so switching to a
  // still forced the sidebar off Stills — and switching back left it wherever
  // that had pushed it. What each item was last being looked at through is a
  // fact about that item.
  //
  // A newly opened tab starts from the LAST set used, which is also what is
  // remembered across sessions: there is nothing else to start it from, and
  // "the same lists I was just using" is what anybody would expect of a
  // freshly opened picture.
  const [tabsByItem, setTabsByItem] = useState<Record<number, SideTab[]>>({});
  // WHETHER THE OPEN TAB IS A FILM, readable by the memo below — which runs
  // before the item detail this window fetches is even in scope. The ref
  // carries the answer, the state re-runs the memo when it changes.
  const isVideoRef = useRef(false);
  const [isVideoTick, setIsVideoTick] = useState(false);
  const lastTabs = useRef<SideTab[]>((() => {
    try {
      const raw = JSON.parse(storage.get(TAB_KEY) || "[]") as SideTab[];
      const keep = raw.filter((x) => SIDE_TABS.some((s2) => s2.id === x));
      return keep.length ? keep : (["tags"] as SideTab[]);
    } catch { return ["tags"] as SideTab[]; }
  })());
  // A FILM-ONLY tab is filtered out for a picture rather than written away.
  // Stills is the one: its button is not drawn on an image, so a tab holding
  // it would leave the sidebar showing nothing with no way to say so — which
  // is what taking a still did, since capturing one opens it in a tab. Doing
  // it here rather than in an effect that corrects the state means the film
  // the tab came from keeps its Stills, and so does the remembered set.
  const tabs = useMemo(() => {
    const raw = (itemId != null ? tabsByItem[itemId] : null) ?? lastTabs.current;
    // Filtered here, never corrected in an effect: a correction is
    // indistinguishable from the user closing the tab, and the item the tab
    // belongs on would lose it on the way back.
    const keep = raw.filter((x) => {
      const def = SIDE_TABS.find((s2) => s2.id === x);
      if (!isVideoRef.current && def?.video) return false;
      if (isVideoRef.current && def?.image) return false;
      return true;
    });
    return new Set<SideTab>(keep.length ? keep : (["tags"] as SideTab[]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabsByItem, itemId, isVideoTick]);
  const sideTabsRef = useRef(tabs);
  sideTabsRef.current = tabs;
  /** Change the OPEN ITEM's tabs. It starts from what is ON SCREEN, not from
   *  the stored list: an item with no entry of its own is showing the
   *  remembered set with the film-only tabs already filtered out, and starting
   *  from the unfiltered one would file a Stills tab under a picture. */
  const setTabs = useCallback((fn: (prev: Set<SideTab>) => Set<SideTab>) => {
    const key = itemIdRef.current;
    if (key == null) return;
    setTabsByItem((cur) => {
      const next = fn(new Set<SideTab>(sideTabsRef.current));
      lastTabs.current = [...next];
      try { storage.set(TAB_KEY, JSON.stringify(lastTabs.current)); }
      catch { /* ignore */ }
      return { ...cur, [key]: [...next] };
    });
  }, []);
  // Which row a tab being jumped to should land on, set by a tag row's
  // person / pin / calendar / face marker — the same jump the library
  // sidebar's tag list offers, because it is the same list. One per kind
  // rather than one shared: the jump names a tab AND a row, and a stale value
  // would flash something the next time that tab was opened.
  const [focusSubject, setFocusSubject] = useState<string | null>(null);
  const [focusPlace, setFocusPlace] = useState<string | null>(null);
  const [focusEvent, setFocusEvent] = useState<string | null>(null);
  const [focusFace, setFocusFace] = useState<string | null>(null);
  // WHICH TAB THE OPENER ASKED FOR. Every list in the library sidebar has an
  // Annotate button now, and pressing it in Captions should arrive in
  // Captions. Consumed once and cleared — an unconsumed value would re-open
  // that tab the next time this window opened for any other reason.
  const annotateTab = useUI((s) => s.annotateTab);
  const clearAnnotateTab = useUI((s) => s.clearAnnotateTab);
  useEffect(() => {
    if (!annotateTab || itemId == null) return;
    const want = SIDE_TABS.find((s2) => s2.id === annotateTab);
    if (want) setTabs(() => new Set<SideTab>([want.id]));
    clearAnnotateTab();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [annotateTab, itemId]);
  const pickTab = (id: SideTab, additive: boolean) => {
    setTabs((prev) => {
      if (!additive) return new Set<SideTab>([id]);
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        if (next.size === 0) next.add(id);   // never none
      } else next.add(id);
      return next;
    });
  };
  const { data: faces } = useQuery({
    queryKey: ["faces", itemId],
    queryFn: () => api.faces(itemId as number),
    enabled: itemId != null && tabs.has("subjects"),
  });
  const { data: subjectRows } = useQuery({
    queryKey: ["subjects"], queryFn: api.subjects, enabled: tabs.has("subjects"),
  });
  const [namingFace, setNamingFace] = useState<number | null>(null);
  const [faceName, setFaceName] = useState("");
  const faceModeRef = useRef(false);
  const refreshFaces = () => {
    qc.invalidateQueries({ queryKey: ["faces", itemId] });
    qc.invalidateQueries({ queryKey: ["faces-unnamed"] });
    qc.invalidateQueries({ queryKey: ["item", itemId] });
    // Naming or dismissing a face changes what the library's own sidebar
    // says about the item, so the lists behind this window are refreshed too.
    bumpEdits();
  };
  const refreshFacesRef = useRef(refreshFaces);
  refreshFacesRef.current = refreshFaces;
  // Read by the rubber band at mouseup, which runs from a window listener and
  // so cannot see this render's `faces`.
  const facesRef = useRef(faces);
  facesRef.current = faces;
  const nameFace = async (faceId: number, text: string) => {
    const wanted = text.trim();
    if (!wanted) return;
    setNamingFace(null);
    setFaceName("");
    let subject = (subjectRows ?? []).find(
      (r) => (r.display_name || r.tag).toLowerCase() === wanted.toLowerCase());
    if (!subject) {
      const rows = await api.createSubject({ display_name: wanted });
      subject = rows.find((r) => r.display_name === wanted) ?? rows[rows.length - 1];
      qc.invalidateQueries({ queryKey: ["subjects"] });
    }
    if (!subject) return;
    await api.nameFace(faceId, { subject_id: subject.id });
    rememberSubject(subject.display_name || subject.tag);
    refreshFaces();
  };
  // Most recently named first: a page is the same few people over and over, so
  // the useful order is the one the library cannot know (`subjects/recent.ts`).
  const recentSubjects = useRecentSubjects();
  const faceSuggestions = useMemo(
    () => byRecent((subjectRows ?? [])
      .filter((r) => r.display_name || r.tag)
      .map((r) => ({ name: r.display_name || r.tag, comment: r.comment,
                     uses: r.items })), recentSubjects),
    [subjectRows, recentSubjects]
  );

  // Which of the item's files is on screen. The ACTIVE one unless somebody
  // picked another from the header's chip — boxes are stored in the item's
  // reference frame and mapped through whichever file is shown, so switching
  // one costs nothing but the mapping (`refToFile` / `fileToRef`).
  const [fileOverride, setFileOverride] = useState<number | null>(null);
  useEffect(() => { setFileOverride(null); }, [itemId]);
  const activeFile = item?.files.find((f) => f.id === fileOverride)
    ?? item?.files.find((f) => f.active) ?? item?.files[0] ?? null;
  const activeFileRef = useRef(activeFile);
  activeFileRef.current = activeFile;
  /** What the shown file measures, under its name in the header: the size, and
   *  a film's length after it. Built from the file rather than the item so it
   *  follows the header's own file chip. */
  const headerSubtitle = [
    activeFile?.width && activeFile?.height
      ? `${activeFile.width}×${activeFile.height}` : "",
    activeFile?.duration ? fmtDuration(activeFile.duration) : "",
  ].filter(Boolean).join(" · ");
  const hostFile = hostItem?.files.find((f) => f.active) ?? hostItem?.files[0] ?? null;
  // Is this window on a video? The transport, the timed tags and the stills
  // list all follow from it. `onVideo` is kept as its own name for the places
  // that ask about the CANVAS rather than about the item — they are the same
  // question now that a still opens in a tab of its own instead of taking
  // this canvas over, and the two spellings say which is being asked.
  const isVideo = hostItem?.kind === "video" || (hostFile?.duration ?? null) != null;
  const onVideo = isVideo;
  isVideoRef.current = isVideo;
  useEffect(() => { setIsVideoTick(isVideo); }, [isVideo]);
  // The FACES layer rides on the Subjects tab: the boxes are drawn exactly
  // while that list is open, because that is the list they belong to. A film's
  // own annotations carry times rather than geometry, so there is nothing on a
  // moving picture for one to sit on.
  const faceMode = tabs.has("subjects") && !onVideo;
  faceModeRef.current = faceMode;
  // ONE face selection, shared by the ovals on the picture and the rows in the
  // sidebar. They are two views of the same thing — a crop in a list and the
  // place it was cut from — so picking in either has to light up both, or the
  // list and the picture disagree about what you are pointing at. Kept here
  // rather than inside PeopleSection because the canvas needs it too.
  const [faceSel, setFaceSel] = useState<number[]>([]);
  const faceSelRef = useRef<number[]>([]);
  faceSelRef.current = faceSel;
  // WHAT a draw on the Subjects tab makes: a FACE, or a subject's whole-figure
  // OUTLINE — the face|person switch. Remembered like the shape below, because
  // it is a way of working rather than a per-picture decision.
  const [subjectDraw, setSubjectDrawState] = useState<"face" | "outline">(() =>
    (storage.get("mc.annotator.subjectDraw") === "outline"
      ? "outline" : "face"));
  const subjectDrawRef = useRef(subjectDraw);
  subjectDrawRef.current = subjectDraw;
  const setSubjectDraw = (v: "face" | "outline") => {
    setSubjectDrawState(v);
    try { storage.set("mc.annotator.subjectDraw", v); } catch { /* full */ }
  };
  // A fresh outline drawn with NOBODY picked in the sidebar: the shape waits
  // under a naming field, the face flow one level up. File-frame fractions.
  const [pendingOutline, setPendingOutline] = useState<
    { x: number; y: number; w: number; h: number;
      points?: [number, number][] } | null>(null);
  const [outlineName, setOutlineName] = useState("");
  const pendingOutlineRef = useRef<typeof pendingOutline>(null);
  pendingOutlineRef.current = pendingOutline;
  useEffect(() => { setPendingOutline(null); setOutlineName(""); }, [itemId]);
  // Assigned below, once the people selection exists — the draw handlers run
  // long before that and reach it through the ref.
  const commitSubjectOutlineRef = useRef<(g: {
    x: number; y: number; w: number; h: number;
    points?: [number, number][] }) => void>(() => {});
  // Which SHAPE a draw makes: a rectangle drag, or a polygon laid corner by
  // corner. A mode rather than a modifier because it also decides what a
  // selected outline's handles edit (corners of the shape vs its bounding
  // box) — and remembered, because it is a way of working, not a per-picture
  // decision. Faces stay ovals and text boxes stay rectangles either way.
  //
  // OCTAGON is a third mode and it is a BOX mode, not a polygon one: it is
  // dragged out as a rectangle and edited by the same bounding-box handles,
  // and all that differs is the shape the drag leaves behind — a polygon
  // with a default shape, which is what a picture's subject usually is more
  // nearly than a rectangle. So `polyUI` (per-corner editing) stays FALSE
  // for it; only `drawShape` itself decides what a fresh drag produces.
  const [drawShape, setDrawShapeState] = useState<DrawShape>(() => {
    const v = storage.get("mc.annotator.drawShape");
    return v === "poly" || v === "octagon" ? v : "box";
  });
  const drawShapeRef = useRef(drawShape);
  drawShapeRef.current = drawShape;
  const setDrawShape = (v: DrawShape) => {
    setDrawShapeState(v);
    try { storage.set("mc.annotator.drawShape", v); } catch { /* full */ }
  };
  // The polygon being laid down, corner by corner (active-file fractions).
  const [polyDraft, setPolyDraft] = useState<[number, number][] | null>(null);
  const polyDraftRef = useRef<[number, number][] | null>(null);
  polyDraftRef.current = polyDraft;
  const [polyHover, setPolyHover] = useState<{ x: number; y: number } | null>(null);
  useEffect(() => { setFaceSel([]); }, [itemId]);
  // Picking a FACE puts every subject/place/event row down, and picking one
  // of those rows puts the faces down (the effect beside `people`): the two
  // selections answer different questions, and both lit at once left the
  // next action ambiguous about which it was aimed at.
  const clearPeopleRef = useRef<() => void>(() => {});
  const pickFace = (id: number, additive: boolean) => {
    const cur = faceSelRef.current;
    const next = additive
      ? (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id])
      : (cur.length === 1 && cur[0] === id ? [] : [id]);
    if (next.length) clearPeopleRef.current();
    setFaceSel(next);
  };
  /** Write a dragged face's new box back. The rows the PATCH returns are put
   *  into the cache before the live geometry is dropped, so the oval never
   *  jumps back to where it was for the length of a refetch. */
  const commitFaceMove = (id: number, r: Rect) => {
    void api.updateFace(id, fileToRef(r, activeFile))
      .then((rows) => {
        if (itemId != null) qc.setQueryData(["faces", itemId], rows);
        refreshFaces();
      })
      .finally(() => dropLiveFaceRef.current(id));
  };
  const commitFaceMoveRef = useRef(commitFaceMove);
  commitFaceMoveRef.current = commitFaceMove;
  // Declared below (with the live-geometry state); reached through a ref for
  // the same reason every other forward reference in this file is.
  const dropLiveFaceRef = useRef<(id: number) => void>(() => {});

  // THE TEXT LAYER rides on the Text tab exactly as faces ride on Subjects:
  // the boxes belong to the list, and Detect text is already at its top. A
  // film has nothing for one to sit on (its text is read on a still).
  const textMode = tabs.has("text") && !onVideo;
  // The box｜polygon switch belongs to the layers that HAVE shapes to draw —
  // tag boxes and subject outlines — so it shows (and polygon gestures run)
  // only while the Tags or Subjects tab is open.
  const shapeTabs = (tabs.has("tags") || tabs.has("subjects")) && !onVideo;
  const shapeTabsRef = useRef(false);
  shapeTabsRef.current = shapeTabs;
  // Poly mode is "on" only where its switch is: elsewhere the remembered
  // choice waits, and every handle renders the box-mode way.
  const polyUI = drawShape === "poly" && shapeTabs;
  const polyUIRef = useRef(polyUI);
  polyUIRef.current = polyUI;
  const textModeRef = useRef(false);
  textModeRef.current = textMode;
  const { data: textTree } = useQuery({
    queryKey: ["text", itemId],
    queryFn: () => api.itemText(itemId as number),
    enabled: itemId != null && tabs.has("text"),
  });
  // Flat, for hit-testing and drawing; the sidebar renders the tree.
  const textRegions = useMemo(() => {
    const out: TextRegion[] = [];
    const visit = (r: TextRegion) => { out.push(r); r.children.forEach(visit); };
    (textTree ?? []).forEach(visit);
    return out;
  }, [textTree]);
  const textRegionsRef = useRef(textRegions);
  textRegionsRef.current = textRegions;
  // ONE selection, shared by the outlines on the picture and the rows in the
  // sidebar (`TextSection`'s controlled mode) — the faces rule: a row and
  // the box it names are two views of one thing. Keys are the section's own
  // (`t:<id>`).
  const [textSel, setTextSel] = useState<string[]>([]);
  const textSelRef = useRef<string[]>([]);
  textSelRef.current = textSel;
  useEffect(() => { setTextSel([]); }, [itemId]);
  // WHICH ENGINE'S READING is on show — the sidebar's dropdown and this
  // canvas must agree, so the state lives here and TextSection is
  // controlled (it reports the resolved fallback back up). Null until the
  // section resolves it; hand-drawn regions belong to no engine and always
  // show.
  const [textEngine, setTextEngine] = useState<string | null>(null);
  useEffect(() => { setTextEngine(null); }, [itemId]);
  // THE CANVAS RESOLVES THE ACTIVE READING ITSELF, by the same rule the list
  // uses (`engineChoice.chosen`: the item's remembered engine, else the
  // first). It used to treat "not resolved yet" as "show everything", which
  // was invisible while one engine had read the page and wrong the moment a
  // second finished: both readings' boxes landed on the picture at once, and
  // only touching the dropdown sorted them out. There is no such state now —
  // the fallback is a value, not an absence.
  const textReadEngines = useMemo(
    () => enginesOf(liveRoots(textTree ?? [])), [textTree]);
  const textPreferred = useChosenEngine(itemId, textReadEngines);
  const textShown = textEngine != null && textReadEngines.includes(textEngine)
    ? textEngine : textPreferred;
  const textVisible = useMemo(() => {
    const out = new Set<number>();
    const add = (r: TextRegion) => { out.add(r.id); r.children.forEach(add); };
    for (const root of textTree ?? []) {
      const eng = root.models[0] ?? "";
      // Hand-drawn text belongs to no engine and rides along with whichever
      // reading is on show.
      if (!eng || !textShown || eng === textShown) add(root);
    }
    return out;
  }, [textTree, textShown]);
  const textVisibleRef = useRef(textVisible);
  textVisibleRef.current = textVisible;
  // THE FINER BOXES SHOW UNDER A PICKED ROW, and only there. A line's words
  // (and their characters) are the mask's smallest unit and the answer to
  // "which part of this line is which" — but a manga page holds hundreds of
  // them, laid over the very lines they belong to, so drawing them all at
  // once turns a read page into a mesh. Descendants of every picked region,
  // at any depth: a picked block shows its lines' words too.
  const textSub = useMemo(() => {
    const picked = new Set(textSel);
    const out = new Set<number>();
    const under = (r: TextRegion) => {
      for (const c of r.children) { out.add(c.id); under(c); }
    };
    const walk = (r: TextRegion) => {
      if (picked.has(textRowKey(r.id))) under(r);
      else r.children.forEach(walk);
    };
    (textTree ?? []).forEach(walk);
    return out;
  }, [textTree, textSel]);
  // Which region the sidebar is POINTING at — hovering a row's box glyph
  // lights it up here rather than opening a crop of a region that is already
  // on screen a few centimetres away.
  const [textHover, setTextHover] = useState<number | null>(null);
  useEffect(() => { setTextHover(null); }, [itemId]);
  // A region drawn by hand opens its row's editor, focused and EMPTY — you
  // are transcribing, not replacing.
  const [textAutoEdit, setTextAutoEdit] = useState<number | null>(null);
  const refreshText = () => {
    qc.invalidateQueries({ queryKey: ["text", itemId] });
    qc.invalidateQueries({ queryKey: ["item", itemId] });
    bumpEdits();
  };
  const refreshTextRef = useRef(refreshText);
  refreshTextRef.current = refreshText;

  // The video file's stream tracks (video/audio/subtitle) — shown in the sidebar
  // and used to decide whether to offer volume controls.
  const { data: mediaTracks } = useQuery({
    queryKey: ["item-tracks", hostId],
    queryFn: () => api.itemTracks(hostId as number),
    enabled: isVideo && hostId != null,
  });
  const hasAudio = (mediaTracks?.tracks ?? []).some((t) => t.kind === "audio");
  // Subtitle streams (shown via extracted WebVTT <track>s) and the multi-track
  // controls in the transport.
  const subTracks = useMemo(
    () => (mediaTracks?.tracks ?? []).filter((t) => t.kind === "subtitle"),
    [mediaTracks]
  );
  const audioStreams = useMemo(
    () => (mediaTracks?.tracks ?? []).filter((t) => t.kind === "audio"),
    [mediaTracks]
  );

  // Current box set + undo/redo stills. Server ids are tracked by (client id,
  // tag) so a box keeps its identity through delete→undo→redo (which re-creates
  // it) and through adding/removing individual labels.
  const [boxes, setBoxes] = useState<Box[]>([]);
  const serverIdByKey = useRef<Record<string, number | null>>({});
  const undoStack = useRef<Box[][]>([]);
  const redoStack = useRef<Box[][]>([]);
  const [, forceTick] = useState(0);
  const tick = () => forceTick((n) => n + 1);
  /** Which (item, FILE) the box set below was built for.
   *
   *  The file is part of the key because the boxes are held in the shown
   *  file's frame (`refToFile` at build time) while the server stores them in
   *  the ITEM's — so the moment another file is shown, every box on screen is
   *  in the wrong frame until it is rebuilt. Keyed on the item alone this
   *  effect returned early and they simply stayed wrong: for the header
   *  chip's file switch, and for a save made in the image editor next door,
   *  which adds a source file and makes it active under this window. */
  const initedFor = useRef<string | null>(null);
  const initKey = (id: number | null, fileId: number | null | undefined) =>
    `${id ?? ""}:${fileId ?? ""}`;

  // (There used to be two effects here and neither has anything left to do: a
  // `pagehide` that told the library window to reload — the backstop for a
  // message sent while it was still loading — and a listener for the reverse,
  // so a save made in the image editor landed on the picture this half was
  // drawing boxes over. Both existed only because the two windows held two
  // query caches. One overlay, one cache: an invalidation IS the other half's
  // refresh.)

  const tagGroups = item?.tag_groups ?? [];
  const groupName = (gid: number | null) =>
    gid == null ? null : tagGroups.find((g) => g.id === gid)?.name ?? null;

  // Initialize the box set from the server the first time an item loads (and on
  // navigation). We drive the server after that, so we don't re-sync per edit.
  useEffect(() => {
    // `item.id !== itemId` is the STALE case, and it is load-bearing now that
    // the query holds the previous item while the next one loads: without it
    // this builds the new item's box set out of the OLD item's tags and then
    // stamps `initedFor` as done, so the wrong boxes stick until you navigate
    // away and back.
    if (!item || itemId == null || item.id !== itemId) return;
    const key = initKey(itemId, activeFile?.id);
    if (initedFor.current === key) return;
    const list: Box[] = [];
    const ids: Record<string, number | null> = {};
    // A film carries no boxes: its tags are timed, and anything picture-shaped
    // lives on a snapshot. (A library made before that split may still hold
    // boxes on a video; they are simply not drawn over the moving picture.)
    if (onVideo) {
      serverIdByKey.current = {};
      undoStack.current = [];
      redoStack.current = [];
      setBoxes([]);
      initedFor.current = key;
      tick();
      return;
    }
    // Boxes belong to a picture: an image item, or a SNAPSHOT of a frame. Server
    // boxes are grouped by geometry so several tags at one spot merge into a
    // single visual box. (A video's own tags carry times, never geometry — they
    // are handled as timed tags, not boxes.)
    const merged = new Map<string, { geo: { x: number; y: number; w: number; h: number; points?: [number, number][] }; labels: Label[]; sids: number[] }>();
    for (const inst of item.tag_instances) {
      for (const b of inst.boxes ?? []) {
        if (b.x == null || b.w == null) continue; // skip pure time ranges
        const pts = b.points?.length
          ? (quadToFile(b.points, activeFile) as [number, number][])
          : undefined;
        const f = { ...refToFile(b, activeFile), points: pts };
        const gk = geoKey(f.x, f.y, f.w, f.h, pts);
        const entry = merged.get(gk) ?? { geo: f, labels: [], sids: [] };
        entry.labels.push({ tag: inst.name, group: inst.group_id ?? null });
        entry.sids.push(b.id ?? -1);
        merged.set(gk, entry);
      }
    }
    for (const { geo, labels, sids } of merged.values()) {
      const cid = newCid();
      list.push({ cid, labels, ...geo });
      labels.forEach((l, i) => { ids[sk(cid, l.tag)] = sids[i] >= 0 ? sids[i] : null; });
    }
    serverIdByKey.current = ids;
    undoStack.current = [];
    redoStack.current = [];
    setBoxes(list);
    initedFor.current = key;
    tick();
  }, [item, itemId, activeFile, onVideo]);

  // Honor a tag+group the sidebar's bbox icon asked for: open with that row
  // selected, so its boxes are the ones drawn fully and a new box takes it.
  // It rode in `localStorage` while this was a separate document, which was
  // the only channel there was; it is plain state now, read and cleared.
  useEffect(() => {
    if (itemId == null) return;
    const want = useUI.getState().editorFocusTag;
    if (want && want.id === itemId && want.tag) {
      useUI.getState().clearEditorFocusTag();
      setTagSel([tagRowKey(want.group ?? null, want.tag)]);
    }
  }, [itemId]);

  // ---- server reconciliation (serialized) ----
  const chain = useRef<Promise<void>>(Promise.resolve());
  const enqueue = (fn: () => Promise<void>) => {
    chain.current = chain.current.then(fn).catch(() => {});
    return chain.current;
  };
  const broadcast = () => {
    qc.invalidateQueries({ queryKey: ["item", itemId] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    bumpEdits();
  };
  const reconcile = (from: Box[], to: Box[]) => {
    const fromByCid = new Map(from.map((b) => [b.cid, b]));
    const toByCid = new Map(to.map((b) => [b.cid, b]));
    const geo = (b: Box) => ({ x: b.x, y: b.y, w: b.w, h: b.h });
    const pts = (b: Box) => b.points?.length ? b.points : null;
    enqueue(async () => {
      // Boxes removed entirely: drop every server box for their labels.
      for (const fb of from) {
        if (toByCid.has(fb.cid)) continue;
        for (const lb of fb.labels) {
          const key = sk(fb.cid, lb.tag);
          const sid = serverIdByKey.current[key];
          if (sid != null) await api.deleteTagBox(sid);
          serverIdByKey.current[key] = null;
        }
      }
      // Added or changed boxes.
      for (const tb of to) {
        const fb = fromByCid.get(tb.cid);
        const changedGeo = !fb || !geoSame(fb, tb);
        const toTags = new Set(tb.labels.map((l) => l.tag));
        // Labels removed from an existing box.
        if (fb) {
          for (const lb of fb.labels) {
            if (toTags.has(lb.tag)) continue;
            const key = sk(fb.cid, lb.tag);
            const sid = serverIdByKey.current[key];
            if (sid != null) await api.deleteTagBox(sid);
            serverIdByKey.current[key] = null;
          }
        }
        // Labels present now: create the missing ones, move existing ones.
        for (const lb of tb.labels) {
          const key = sk(tb.cid, lb.tag);
          const sid = serverIdByKey.current[key];
          if (sid == null) {
            const r = await api.addTagBox(
              itemId as number, lb.tag,
              {
                ...geo(tb),
                time_start: tb.start ?? null,
                time_end: tb.end ?? null,
                track_id: tb.trackId ?? null,
                points: pts(tb),
              },
              activeFile?.id, lb.group,
            );
            serverIdByKey.current[key] = r.id;
          } else if (changedGeo) {
            await api.updateTagBox(sid, {
              ...geo(tb), fileId: activeFile?.id,
              // The polygon rides every geometry write (the client already
              // transformed it, so the server stores exactly what is on
              // screen); losing one is said explicitly.
              points: pts(tb) ?? undefined,
              clearPoints: !!(fb && pts(fb) && !pts(tb)),
            });
          }
        }
      }
      broadcast();
    });
  };

  // Apply a new box set as one undoable step.
  const apply = useCallback((next: Box[]) => {
    setBoxes((prev) => {
      undoStack.current.push(prev);
      redoStack.current = [];
      reconcile(prev, next);
      return next;
    });
    tick();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFile, itemId]);

  const undo = useCallback(() => {
    if (undoStack.current.length === 0) return;
    setBoxes((cur) => {
      const target = undoStack.current.pop()!;
      redoStack.current.push(cur);
      reconcile(cur, target);
      return target;
    });
    tick();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFile, itemId]);
  const redo = useCallback(() => {
    if (redoStack.current.length === 0) return;
    setBoxes((cur) => {
      const target = redoStack.current.pop()!;
      undoStack.current.push(cur);
      reconcile(cur, target);
      return target;
    });
    tick();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFile, itemId]);

  // ---- navigation ----
  // Step between the window's tabs.
  const tabsRef = useRef(editorTabs);
  tabsRef.current = editorTabs;
  const goTab = (delta: number) => {
    const tabs = tabsRef.current;
    const at = itemId != null ? tabs.indexOf(itemId) : -1;
    if (at < 0) return;
    const next = tabs[at + delta];
    if (next != null) { initedFor.current = null; setEditorItem(next); }
  };

  // Step through the sequence the item is in (header, next to the file chip).
  // The pick survives every step — see SequenceNav for why it must.
  const { data: itemSeqs } = useQuery({
    queryKey: ["item-sequences", itemId],
    queryFn: () => api.itemSequences(itemId as number),
    enabled: itemId != null,
  });
  const [seqPick, setSeqPick] = useState<number | null>(null);
  // The window's tabs, readable from the key handler — which is registered
  // once and would otherwise see whatever they were when it was.
  const editorTabsRef = useRef(editorTabs);
  editorTabsRef.current = editorTabs;
  const editorItemIdRef = useRef(editorItemId);
  editorItemIdRef.current = editorItemId;

  // Closing the WINDOW (Escape). With a second tab open that is a question
  // rather than an action — ⌘W used to answer it and could not be relied on
  // to arrive at all — so it is asked. With one tab the window is the tab.
  const [closeAsk, setCloseAsk] = useState(false);
  const requestCloseRef = useRef(() => {});
  // Assigned every render, so it reads today's tabs and today's answer —
  // Escape while the question is up takes it back, which is the third button.
  requestCloseRef.current = () => {
    if (closeAsk) setCloseAsk(false);
    else if (editorTabsRef.current.length > 1 && editorItemIdRef.current != null) setCloseAsk(true);
    else closeItemWindow();
  };

  const goItem = (id: number) => {
    initedFor.current = null;
    navigateEditor(id);
    // ANNOTATE, said explicitly — `openTab`'s rule, for the same reason one
    // level along: a tab with no mode of its own takes the mode the WINDOW
    // was opened in, so turning the page from a window opened by Edit image
    // handed the next page to the paintbrush. You are reading a chapter; the
    // chevron is the page turn, not a change of what you are doing.
    setEditorMode(id, "annotate");
  };
  /** Open an item as a TAB of this window — how a still is looked at.
   *  Appending rather than replacing (`navigateEditor`, which page-turning
   *  uses): the film you took the still FROM is what you want to come back to.
   *  Clearing `initedFor` for the same reason every other switch does —
   *  otherwise the new item's boxes are built from the old one's tags.
   *
   *  ANNOTATE, said explicitly. A tab with no mode of its own takes the one
   *  the WINDOW was opened in, so a still captured from a film opened by Edit
   *  video arrived in the image editor — a picture nobody has tagged yet,
   *  offered with a paintbrush. You took it to tag it, and every other use of
   *  this (a link, a panel's page) is the same "look at that item" from a
   *  window whose whole job is looking. */
  const openTab = (id: number) => {
    if (id === editorItemId) return;
    initedFor.current = null;
    setEditorMode(id, "annotate");
    setEditorItem(id);
  };

  // ---- viewport / zoom / pan (fit-based, shared with the image editor) ----
  const frameRef = useRef<HTMLDivElement>(null);
  const iw = activeFile?.width || 1;
  const ih = activeFile?.height || 1;
  // `zp.zoom` is a multiplier over the fit scale (1 = fit-to-screen); the hook
  // owns viewport measuring, the auto-fit on navigation (via `fitKey`), and the
  // fit ↔ actual-size toggle so it matches the editor.
  // The SAFE AREA: what the floating bars leave of the canvas — the undo pill
  // at the top left (and the sequence chip opposite it), the hint or media bar
  // at the bottom left, the zoom cluster at the bottom right. Without it a
  // fitted picture runs under all four, and the corners of a page — where a
  // panel's boxes usually are — sit behind a control. The image editor has
  // always done this; `useZoomPan` now owns the arithmetic for all of them.
  const zp = useZoomPan(iw, ih, { fitKey: itemId, inset: CANVAS_INSET });
  const { viewportRef, pan, setPan, frameW, frameH, vp, origin } = zp;
  // The draw tool is always active; panning happens while Space is held (there
  // is no separate pan tool — see DESCRIPTION §Annotation editor).
  const [spaceHeld, setSpaceHeld] = useState(false);

  // ---- video playback + timing (video items only) ----
  const fps = hostFile?.frame_rate && hostFile.frame_rate > 0 ? hostFile.frame_rate : 25;
  const play = useVideoPlayback(fps, hostItem?.duration ?? 0);
  // The window key handler is registered ONCE, so it reads the current
  // transport through a ref rather than closing over the first one.
  const playRef = useRef(play);
  playRef.current = play;
  // In/out range that new/edited timed boxes span (null = untimed / single frame).
  const [inPoint, setInPoint] = useState<number | null>(null);
  const [outPoint, setOutPoint] = useState<number | null>(null);
  useEffect(() => { setInPoint(null); setOutPoint(null); }, [itemId]);
  // Reset the range whenever it's consumed by a draw/edit.
  const clearRange = () => { setInPoint(null); setOutPoint(null); };
  // The time context for a new timed box: the in/out range, else a single frame
  // at the playhead.
  const newBoxTime = (): { start: number | null; end: number | null } =>
    inPoint != null && outPoint != null && outPoint > inPoint
      ? { start: inPoint, end: outPoint }
      : { start: play.nowTime(), end: null };

  // The playhead is REMEMBERED PER ITEM (localStorage), restored when the film
  // opens and written when the page goes away, so a reload comes back to the
  // same frame. It used to ride in the URL, which meant rewriting the address
  // bar every second for a value nobody types or shares.
  const restored = useRef(false);
  useEffect(() => {
    if (!isVideo || hostId == null || restored.current || play.duration <= 0) return;
    restored.current = true;
    const t = rememberedTime(hostId);
    if (t > 0) play.seek(Math.min(t, play.duration));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isVideo, hostId, play.duration]);
  useEffect(() => {
    if (!isVideo || hostId == null) return;
    // Read off the ELEMENT, never off the mirrored time: `pagehide` can fire in
    // the same beat as a seek, when the mirror is still a frame behind.
    const save = () => {
      if (!restored.current) return;
      const t = play.videoRef.current?.currentTime;
      if (t != null) rememberTime(hostId, t);
    };
    window.addEventListener("pagehide", save);
    // The cleanup covers leaving for another item, and unmount.
    return () => { window.removeEventListener("pagehide", save); save(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isVideo, hostId]);

  // Window theme — remembered separately from the image editor, following the
  // app by default.
  const [winTheme, setWinTheme] = useWindowTheme("mc.annotatorTheme");

  // Resizable right sidebar (persisted). The divider on its left edge drags it.
  const sidebar = useSplit({
    pref: numPref("mc.annotatorSidebarW", { def: 300, min: ANNOTATOR_SIDEBAR_MIN, max: 680 }),
    min: ANNOTATOR_SIDEBAR_MIN, max: 680, axis: "x", from: "end",
  });
  const sidebarW = sidebar.size;

  // Resizable TIMELINE panel (persisted), dragged by its top edge. How many
  // tag tracks fit is what the bottom half of this window is about, and it
  // differs per film and per job — a fixed height could only ever suit one of
  // them. Clamped against the window, since one shrunk past the stored value
  // would leave the panel taller than the picture; that is a `useLayoutEffect`
  // so a window resize never paints a frame with the picture squeezed to
  // nothing.
  const bottom = useSplit({
    pref: numPref(BOTTOM_H_KEY, { def: 230, min: BOTTOM_MIN }),
    min: BOTTOM_MIN, max: bottomMax, axis: "y", from: "end", reclampOnResize: true,
  });
  const bottomH = bottom.size;

  // The sidebar's selected tag rows (keys from `tagRowKey`) ARE the box filter:
  // selecting tags draws their boxes fully and ghosts the rest, and selecting a
  // box on the canvas selects its tag rows. With nothing selected every box
  // draws fully — there is no separate legend to keep in step.
  const [tagSel, setTagSel] = useState<string[]>([]);
  const tagSelSet = useMemo(() => new Set(tagSel), [tagSel]);
  // A selection that outlives its list is a filter nobody can see: with the
  // Tags tab closed the rows are gone, but the picked keys kept that tag's
  // boxes drawn on the Subjects tab — through `boxFocused` — with nothing
  // anywhere saying why.
  useEffect(() => { if (!tabs.has("tags")) setTagSel([]); }, [tabs]);
  // The film's own (timed) tag rows are a SECOND selection: they have no boxes
  // to filter, they pick which activity lanes are drawn under the scrubber. One
  // shared selection would mean picking a timed tag ghosts every box of the
  // snapshot being edited, which is nonsense — they annotate different things.
  const [timeSel, setTimeSel] = useState<string[]>([]);
  const timeSelSet = useMemo(() => new Set(timeSel), [timeSel]);
  // Which tags STAND OUT on the timeline. Empty means nothing is picked, and
  // then nothing is ghosted.
  const visibleTags = useMemo(() => new Set(timeSel.map(rowKeyName)), [timeSel]);
  /** A click on a block of the timeline, which is a click on the sidebar row
   *  it is: the tag list's own rules, so one selection cannot grow two
   *  dialects. Shift extends over the stretches in READING order — track by
   *  track, left to right within each — which is what the timeline draws, and
   *  is written by the render below rather than guessed at here. */
  const timeOrder = useRef<string[]>([]);
  const timeAnchor = useRef<string | null>(null);
  // The one click rule (`shared/pickList.ts`), over the timeline's own order.
  const pickTimeRow = useCallback(
    (key: string, m: { meta: boolean; shift: boolean }) => {
      setTimeSel((cur) => {
        const r = pickNext(cur, key, m, timeOrder.current, timeAnchor.current);
        timeAnchor.current = r.anchor;
        return r.next;
      });
    }, []);
  // Reset the focus filter when navigating to another item.
  useEffect(() => { setTagSel([]); }, [itemId]);
  useEffect(() => { setTimeSel([]); }, [hostId]);
  // The labels a newly-drawn box gets: the selected rows, resolved back to
  // tag+group off the item (never by splitting the key, since a tag name may
  // contain the separator). Nothing selected → the box asks for a tag name.
  const selectedLabels = useMemo(
    () => (item?.tag_instances ?? [])
      .filter((i) => tagSelSet.has(tagRowKey(i.group_id ?? null, i.name)))
      .map((i) => ({ tag: i.name, group: i.group_id ?? null })),
    [item, tagSelSet]
  );

  // Which tag's track the pointer is over, so that tag's boxes glow. Hovering
  // used to SCRUB the film as well — an affordance a 5 px lane needed, since
  // there was nothing else to do with it — and a timeline whose blocks are
  // dragged cannot have one: crossing a stretch on the way to its edge would
  // seek the film out from under the drag.
  const [hoverTag, setHoverTag] = useState<string | null>(null);

  // ---- pointer handling ----
  type Drag =
    | { kind: "pan"; from: { x: number; y: number }; pan0: { x: number; y: number } }
    | { kind: "draw"; start: { x: number; y: number }; shift: boolean;
        // Poly mode: the press landed on something drawn, so releasing may
        // only PICK — a drag must not draw a rectangle in polygon mode.
        pickOnly?: boolean }
    | { kind: "move"; cid: string; startFrac: { x: number; y: number }; orig: Box;
        shift: boolean }
    | { kind: "resize"; cid: string; corner: string; orig: Box }
    | { kind: "rotate"; cid: string; orig: Box; pts0: [number, number][];
        cx: number; cy: number; a0: number; aspect: number }
    // The freshly-drawn box, still waiting for its tag: it can be nudged and
    // resized before it is committed, so it gets its own drag kinds (it isn't
    // in `boxes` yet, so the cid-keyed ones can't reach it).
    | { kind: "pmove"; startFrac: { x: number; y: number }; orig: Box }
    | { kind: "presize"; corner: string; orig: Box }
    // A face's oval, dragged. Only a SELECTED one takes the pointer at all
    // (the same rule the boxes follow).
    // A press that never moves is a click — which is how a face is put down
    // again. Every face moves now, detected ones included: the first hand
    // edit keeps the detector's rectangle aside (`FaceBoxEdit`), so a re-run
    // can no longer put the box back.
    | { kind: "facemove"; id: number; startFrac: { x: number; y: number };
        orig: Rect; shift: boolean }
    // A picked face's corner: resizing the rectangle behind the oval.
    | { kind: "faceresize"; id: number; corner: string; orig: Rect }
    // A polygon DRAFT corner: the press that appended it drags it until
    // release ("add a corner on click, move it on drag" as one gesture).
    | { kind: "polypt"; idx: number; shift: boolean; freshDraft: boolean;
        moved: boolean }
    // A committed box's corner in poly mode — a rect's four count too.
    // `moved` starts true for an INSERTED corner (pressing the midpoint adds
    // it even without a drag) and false for an existing one, whose press
    // without movement is a click that SELECTS the corner.
    | { kind: "emove"; cid: string; idx: number; pts0: [number, number][];
        startFrac: { x: number; y: number }; orig: Box; moved: boolean }
    | { kind: "vmove"; cid: string; idx: number; pts0: [number, number][];
        orig: Box; moved: boolean }
    // The selected OUTLINE (subject box or face figure), moved /
    // bbox-resized / corner-dragged. `okey` is `app:<id>` / `face:<id>`.
    | { kind: "omove"; okey: string; startFrac: { x: number; y: number };
        orig: { x: number; y: number; w: number; h: number;
                points?: [number, number][] }; shift: boolean }
    | { kind: "oresize"; okey: string; corner: string;
        orig: { x: number; y: number; w: number; h: number;
                points?: [number, number][] } }
    | { kind: "ovmove"; okey: string; idx: number; pts0: [number, number][];
        moved: boolean }
    // The selected TEXT REGION's box, moved or bbox-resized. Its quad (a
    // slanted engine reading) rides along through the same affine the
    // polygon boxes use, so the shape is never silently replaced by an
    // upright rectangle.
    | { kind: "tmove"; id: number; startFrac: { x: number; y: number };
        orig: { x: number; y: number; w: number; h: number;
                quad?: [number, number][] } }
    | { kind: "tresize"; id: number; corner: string;
        orig: { x: number; y: number; w: number; h: number;
                quad?: [number, number][] } }
    | { kind: "marquee"; start: { x: number; y: number }; additive: boolean; base: string[] };
  const drag = useRef<Drag | null>(null);
  const [draft, setDraft] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [selectedCids, setSelectedCids] = useState<string[]>([]);
  const [marquee, setMarquee] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [pending, setPending] = useState<{ box: Box } | null>(null);
  // Renaming an existing label, or adding a new label to a box.
  const [renaming, setRenaming] = useState<{ cid: string; tag: string } | null>(null);
  const [addingTo, setAddingTo] = useState<string | null>(null);
  const [nameInput, setNameInput] = useState("");
  // Open group-picker for an existing label (change which group a tag is in).
  const [groupMenu, setGroupMenu] = useState<{ cid: string; tag: string; x: number; y: number } | null>(null);
  // Provisional (uncommitted) geometry for the box being moved/resized.
  //
  // THE REF IS WRITTEN IN THE SAME BREATH AS THE STATE, and the mouseup reads
  // the REF. This was a real bug and a silent one: `onUp` read the `liveBoxes`
  // captured in its own closure, which is the value from the last render the
  // listener was registered on — so a drag whose mouseup arrived before React
  // had committed its last mousemove saw either one sample behind or, on a
  // short drag with a single move, NOTHING AT ALL, and the whole edit was
  // dropped with no error anywhere. That is the "boxes are not always saved":
  // a quick nudge of a corner lost the nudge, a slow one kept it. Every other
  // in-flight shape here already goes through a ref (`liveOutlineRef`,
  // `liveTextRef`) — those are assigned during render, which is enough for
  // them because their commits compare against `d.orig` rather than needing
  // the newest sample; these two are written from the move handler itself, so
  // they are right whether or not a render has happened.
  const [liveBoxes, setLiveBoxes] = useState<Record<string, Box>>({});
  const liveBoxesRef = useRef<Record<string, Box>>({});
  const putLiveBox = useCallback((cid: string, b: Box) => {
    liveBoxesRef.current = { ...liveBoxesRef.current, [cid]: b };
    setLiveBoxes(liveBoxesRef.current);
  }, []);
  const dropLiveBox = useCallback((cid: string) => {
    const n = { ...liveBoxesRef.current };
    delete n[cid];
    liveBoxesRef.current = n;
    setLiveBoxes(n);
  }, []);
  // …and for the face being moved, in the active file's frame like the boxes.
  const [liveFaces, setLiveFaces] = useState<Record<number, Rect>>({});
  const liveFacesRef = useRef<Record<number, Rect>>({});
  const putLiveFace = useCallback((id: number, r: Rect) => {
    liveFacesRef.current = { ...liveFacesRef.current, [id]: r };
    setLiveFaces(liveFacesRef.current);
  }, []);
  const dropLiveFace = useCallback((id: number) => {
    const n = { ...liveFacesRef.current };
    delete n[id];
    liveFacesRef.current = n;
    setLiveFaces(n);
  }, []);
  dropLiveFaceRef.current = dropLiveFace;
  // The selected OUTLINE is DERIVED, never its own state — a subject box
  // (`app:<appearance>`) from the sidebar's row selection, a face's figure
  // outline (`face:<face>`) from the face selection — see `selOut` below;
  // only its in-flight geometry while a drag is live is kept here.
  const [liveOutline, setLiveOutline] = useState<
    { okey: string; x: number; y: number; w: number; h: number;
      points?: [number, number][] } | null>(null);
  const liveOutlineRef = useRef<typeof liveOutline>(null);
  liveOutlineRef.current = liveOutline;
  useEffect(() => { setLiveOutline(null); }, [itemId]);
  // The selected text region's in-flight geometry while a drag is live.
  const [liveText, setLiveText] = useState<
    { id: number; x: number; y: number; w: number; h: number;
      quad?: [number, number][] } | null>(null);
  const liveTextRef = useRef<typeof liveText>(null);
  liveTextRef.current = liveText;
  useEffect(() => { setLiveText(null); }, [itemId]);
  // The picked CORNER of the selected box or outline (poly mode): clicking a
  // corner handle selects it, and Delete/Backspace then removes that corner
  // rather than the whole box. A rect's four derived corners count too —
  // deleting one is what turns the rect into a triangle.
  const [selVertex, setSelVertex] = useState<
    { kind: "box"; cid: string; idx: number }
    | { kind: "out"; okey: string; idx: number;
        pts: [number, number][] } | null>(null);
  const selVertexRef = useRef<typeof selVertex>(null);
  selVertexRef.current = selVertex;
  useEffect(() => { setSelVertex(null); }, [itemId, drawShape]);

  const frac = (clientX: number, clientY: number) => {
    const r = frameRef.current!.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (clientX - r.left) / r.width)),
      y: Math.max(0, Math.min(1, (clientY - r.top) / r.height)),
    };
  };

  const onBackgroundDown = (e: React.MouseEvent) => {
    // Pan with the middle mouse button (like holding Space) or Space + left drag.
    if (e.button === 1 || (e.button === 0 && spaceHeld)) {
      e.preventDefault();
      drag.current = { kind: "pan", from: { x: e.clientX, y: e.clientY }, pan0: { ...pan } };
      return;
    }
    if (e.button !== 0) return;
    const f = frac(e.clientX, e.clientY);
    // ALT rubber-band selects; everything else draws. There are no modes: a
    // drag is a new box, a CLICK is a selection, and which one you meant is
    // read off the distance at mouseup rather than from a toggle you had to
    // set first. Shift keeps the existing selection.
    if (e.altKey) {
      drag.current = { kind: "marquee", start: f, additive: e.shiftKey,
                       base: e.shiftKey ? selectedCids : [] };
      setMarquee({ x: f.x, y: f.y, w: 0, h: 0 });
      return;
    }
    if (polyActiveRef.current()) {
      const cur = polyDraftRef.current;
      if (cur) {
        // Close on the first corner (a polygon needs three); otherwise the
        // press appends a corner and drags it until release — "add on
        // click, move on drag" as one gesture.
        if (cur.length >= 3
            && Math.hypot(f.x - cur[0][0], f.y - cur[0][1]) < 0.015) {
          finishPolyRef.current();
          return;
        }
        setPolyDraft([...cur, [f.x, f.y]]);
        drag.current = { kind: "polypt", idx: cur.length, shift: e.shiftKey,
                         freshDraft: false, moved: false };
        return;
      }
      // No draft yet: a press on something drawn is a pick, everything else
      // lays the first corner.
      const file = activeFileRef.current;
      const hit = boxesRef.current.some((bx) => boxDrawnRef.current(bx)
        && (bx.points
          ? inPoly(f, bx.points) || nearPolyEdge(f, bx.points, 0.008)
          : f.x >= bx.x && f.x <= bx.x + bx.w
            && f.y >= bx.y && f.y <= bx.y + bx.h))
        || (faceModeRef.current && subjectDrawRef.current === "face"
          && (facesRef.current ?? []).some((fc) =>
            !fc.dismissed && inFaceOutline(f, refToFile(fc, file))))
        || (subjectDrawRef.current === "outline"
          ? outlineGeosRef.current : []).some((geo) => geo.points
          ? inPoly(f, geo.points) || nearPolyEdge(f, geo.points, 0.008)
          : f.x >= geo.x && f.x <= geo.x + geo.w
            && f.y >= geo.y && f.y <= geo.y + geo.h);
      if (!hit) {
        setPolyDraft([[f.x, f.y]]);
        drag.current = { kind: "polypt", idx: 0, shift: e.shiftKey,
                         freshDraft: true, moved: false };
        return;
      }
      drag.current = { kind: "draw", start: f, shift: e.shiftKey,
                       pickOnly: true };
      return;
    }
    drag.current = { kind: "draw", start: f, shift: e.shiftKey };
    setDraft({ x: f.x, y: f.y, w: 0, h: 0 });
  };

  // Whether a box is drawn at all (it is not, in face mode with the tag list
  // closed). Held in a ref because the pointer handlers are registered once
  // and would otherwise read whatever the tabs were when they were.
  const boxDrawnRef = useRef<(b: Box) => boolean>(() => true);

  // Whether a click lays polygon corners here and now: poly mode, on a
  // picture, and either the outline draw mode or the ordinary tag-box
  // layer — faces stay ovals and text boxes stay rectangles.
  const polyActiveRef = useRef<() => boolean>(() => false);
  polyActiveRef.current = () =>
    drawShapeRef.current === "poly" && !onVideoRef.current && !spaceHeld
    && shapeTabsRef.current
    && ((faceModeRef.current && subjectDrawRef.current === "outline")
        || (!faceModeRef.current && !textModeRef.current));

  /** Commit the polygon draft: the armed subject outline when one is armed,
   *  else a tag box exactly like a drawn rectangle — the sidebar's selected
   *  tags label it, or the name prompt opens. */
  const finishPoly = () => {
    const pts = polyDraftRef.current;
    setPolyDraft(null);
    setPolyHover(null);
    if (!pts || pts.length < 3) return;
    const bounds = polyBounds(pts);
    if (bounds.w <= 0.005 && bounds.h <= 0.005) return;
    // OUTLINE draw mode (the face|person switch): the polygon is a subject's
    // outline — onto the picked people rows, or a fresh shape that asks who.
    if (faceModeRef.current && subjectDrawRef.current === "outline"
        && !onVideoRef.current && itemId != null) {
      commitSubjectOutlineRef.current({ ...bounds, points: pts });
      return;
    }
    const labels = labelsRef.current;
    if (labels.length) {
      apply([...boxesRef.current, {
        cid: newCid(), labels: labels.map((l) => ({ ...l })),
        ...bounds, points: pts,
      }]);
    } else {
      setPending({ box: { cid: newCid(), labels: [], ...bounds, points: pts } });
      setNameInput("");
    }
  };
  const finishPolyRef = useRef(finishPoly);
  finishPolyRef.current = finishPoly;

  /** Write the selected outline's edited geometry back. The KEY says whose
   *  it is — `app:<appearance>` for a subject box, `face:<face>` for a
   *  face's figure outline — so one drag machinery serves both. */
  const commitOutline = (g: { x: number; y: number; w: number; h: number;
                              points?: [number, number][] }, okey: string) => {
    const file = activeFileRef.current;
    const [okind, oid] = okey.split(":");
    const payload = g.points?.length
      ? { x: 0, y: 0, w: 0, h: 0, points: pointsToRef(g.points, file) }
      : fileToRef(g, file);
    void (okind === "face"
      ? api.setFaceOutline(Number(oid), payload)
      : api.setAppearanceBox(Number(oid), payload)
    ).then(() => {
      void qc.invalidateQueries({ queryKey: ["item", itemId] });
      if (okind === "face") {
        void qc.invalidateQueries({ queryKey: ["faces", itemId] });
      }
    }).finally(() => setLiveOutline(null));
  };
  const commitOutlineRef = useRef(commitOutline);
  commitOutlineRef.current = commitOutline;

  /** Write a dragged text region's geometry back — box and, where the
   *  engine read a slanted quad, the quad it was transformed into. */
  const commitText = (live: { id: number; x: number; y: number; w: number;
                              h: number; quad?: [number, number][] }) => {
    const file = activeFileRef.current;
    const body: Parameters<typeof api.updateTextRegion>[1] =
      fileToRef(live, file);
    if (live.quad) body.quad = pointsToRef(live.quad, file);
    void api.updateTextRegion(live.id, body).then((rows) => {
      if (itemId != null) qc.setQueryData(["text", itemId], rows);
      refreshTextRef.current();
    }).finally(() => setLiveText(null));
  };
  const commitTextRef = useRef(commitText);
  commitTextRef.current = commitText;

  /** Delete with a CORNER picked removes the corner, not the box. Returns
   *  whether the key was consumed — true even when a three-corner polygon
   *  keeps its corner, since the picked corner is what the key is about. */
  const deleteSelVertex = () => {
    const sv = selVertexRef.current;
    if (!sv) return false;
    if (sv.kind === "box") {
      const b = boxesRef.current.find((bx) => bx.cid === sv.cid);
      if (b) removeVertex(b, b.points ?? rectPts(b), sv.idx);
      setSelVertex(null);
    } else {
      setSelVertex(null);
      if (sv.pts.length > 3) {
        const next = sv.pts.filter((_, i) => i !== sv.idx)
          .map((q) => [...q] as [number, number]);
        commitOutlineRef.current({ ...polyBounds(next), points: next },
                                 sv.okey);
      }
    }
    return true;
  };
  const deleteSelVertexRef = useRef(deleteSelVertex);
  deleteSelVertexRef.current = deleteSelVertex;

  /** A click (a draw that never moved): pick what is under the pointer.
   *
   *  Overlapping outlines: one fully under another cannot be reached with a
   *  plain click, so a repeated click at the same spot cycles down the stack
   *  (topmost first). Clicking the one that is ALREADY the only thing selected
   *  puts it down again — the way out, and the rule the library's row lists
   *  follow. Shift toggles one in or out.
   *
   *  A FACE OVAL AND A TAG RECTANGLE ARE ONE STACK. They are two selections
   *  underneath (`faceSel` and `selectedCids`, because they name different
   *  kinds of thing) but under the pointer they are just outlines lying over
   *  each other, and cycling that stopped at the topmost FACE could never
   *  reach a rectangle beneath it — the exact case the cycle exists for. So
   *  the hits are gathered across both layers in drawing order (faces are
   *  drawn over boxes, so they come first) and the two selections are read
   *  and written as one.
   *
   *  Only what is DRAWN can be picked: in face mode with the tag list closed
   *  the boxes stand down, and a click that found one under the picture used
   *  to select a rectangle nobody could see. */
  const clickAt = (f: { x: number; y: number }, shift: boolean) => {
    // Any click that is not on a corner handle puts the picked corner down.
    setSelVertex(null);
    type Hit = { kind: "face"; key: number } | { kind: "text"; key: number }
      | { kind: "box"; key: string } | { kind: "outline"; key: string };
    const file = activeFileRef.current;
    const hits: Hit[] = [
      // OUTLINES first — they draw over the ovals and the boxes, and picking
      // one is the same click-the-shape gesture the tag boxes have. Only in
      // OUTLINE mode: in face mode they are barely drawn, and a click cannot
      // be aiming at something it can hardly see (the hidden-tag-box rule).
      ...(subjectDrawRef.current === "outline" ? outlineGeosRef.current : [])
        .filter((geo) => geo.points
          ? inPoly(f, geo.points) || nearPolyEdge(f, geo.points, 0.008)
          : f.x >= geo.x && f.x <= geo.x + geo.w
            && f.y >= geo.y && f.y <= geo.y + geo.h)
        .map((geo): Hit => ({ kind: "outline", key: geo.key }))
        .reverse(),
      // …and the ovals only in FACE mode, for the same reason the other way.
      ...(faceModeRef.current && subjectDrawRef.current === "face"
        ? (facesRef.current ?? [])
            .filter((fc) => !fc.dismissed)
            .filter((fc) => inFaceOutline(f, refToFile(fc, file)))
            .map((fc): Hit => ({ kind: "face", key: fc.id }))
            .reverse()
        : []),
      // The text layer sits between faces and tag boxes, in drawing order.
      // The hit test is quad-aware: a corner of a slanted line's bounding
      // box belongs to nothing and must not select it.
      ...(textModeRef.current
        ? textRegionsRef.current
            .filter((r) => !r.dismissed
              && textVisibleRef.current.has(r.id))
            .filter((r) => inRegion(f.x, f.y, {
              ...refToFile(r, file),
              quad: r.quad.length === 4 ? quadToFile(r.quad, file) : [],
            }))
            .map((r): Hit => ({ kind: "text", key: r.id }))
            .reverse()
        : []),
      ...boxesRef.current
        .filter((bx) => boxDrawnRef.current(bx))
        // A polygon box answers to its SHAPE, not its bounding box — the
        // bbox covers plenty the outline deliberately leaves out.
        .filter((bx) => bx.points
          ? inPoly(f, bx.points) || nearPolyEdge(f, bx.points, 0.008)
          : f.x >= bx.x && f.x <= bx.x + bx.w
            && f.y >= bx.y && f.y <= bx.y + bx.h)
        .map((bx): Hit => ({ kind: "box", key: bx.cid }))
        .reverse(),
    ];
    const faceSelNow = faceSelRef.current;
    const textSelNow = textSelRef.current;
    const cidSelNow = selectedCidsRef.current;
    // A click on nothing puts ALL of them down — that is what a click
    // outside means for every other selection here.
    if (hits.length === 0) {
      if (!shift) {
        setFaceSel([]); setTextSel([]); setSelectedCids([]);
        // The rows too: an outline's selection IS its row's (a subject's
        // sidebar entry, or the face it belongs to).
        clearPeopleRef.current();
      }
      return;
    }
    const isPicked = (h: Hit) => (h.kind === "face"
      ? faceSelNow.includes(h.key)
      : h.kind === "text" ? textSelNow.includes(textRowKey(h.key))
      : h.kind === "outline" ? selOutRef.current === h.key
      : cidSelNow.includes(h.key));
    if (shift) {
      const top = hits.find((h) => !isPicked(h)) ?? hits[0];
      if (top.kind === "face") {
        clearPeopleRef.current();
        setFaceSel((cur) => (cur.includes(top.key)
          ? cur.filter((id) => id !== top.key) : [...cur, top.key]));
      } else if (top.kind === "outline") {
        if (top.key.startsWith("app:")) {
          const row = `a:${top.key.slice(4)}`;
          subjectSelSetRef.current(subjectSelRef.current.includes(row)
            ? subjectSelRef.current.filter((k) => k !== row)
            : [...subjectSelRef.current, row]);
        } else {
          // A face's figure outline is selected AS the face.
          const fid = Number(top.key.slice(5));
          clearPeopleRef.current();
          setFaceSel((cur) => (cur.includes(fid)
            ? cur.filter((id) => id !== fid) : [...cur, fid]));
        }
      } else if (top.kind === "text") {
        const key = textRowKey(top.key);
        setTextSel((cur) => (cur.includes(key)
          ? cur.filter((k) => k !== key) : [...cur, key]));
      } else {
        setSelectedCids((cur) => (cur.includes(top.key)
          ? cur.filter((c) => c !== top.key) : [...cur, top.key]));
      }
      return;
    }
    // Pick ONE, across the layers: whatever kind it is, the other kinds'
    // selections go down with the same click.
    const pickOnly = (h: Hit | null) => {
      // A face's figure outline is picked AS the face — its sidebar crop
      // lights up with the shape, the same one-selection rule the subject
      // outlines follow through their rows.
      setFaceSel(h?.kind === "face" ? [h.key]
        : h?.kind === "outline" && h.key.startsWith("face:")
          ? [Number(h.key.slice(5))] : []);
      setTextSel(h?.kind === "text" ? [textRowKey(h.key)] : []);
      setSelectedCids(h?.kind === "box" ? [h.key] : []);
      // A subject outline is picked BY selecting its sidebar row — the two
      // are one selection; picking anything else puts the rows down.
      if (h?.kind === "outline" && h.key.startsWith("app:")) {
        subjectSelSetRef.current([`a:${h.key.slice(4)}`]);
      } else {
        clearPeopleRef.current();
      }
    };
    // Down through the stack while there is one, then off — counting the
    // layers together, so exactly one thing selected anywhere is what arms it.
    // A face-derived outline selection IS a face selection, already counted
    // in `faceSelNow` — counting it again would keep the cycle from arming.
    const only = faceSelNow.length + textSelNow.length + cidSelNow.length
      + (selOutRef.current?.startsWith("app:") ? 1 : 0) === 1
      ? hits.findIndex(isPicked) : -1;
    if (only >= 0) {
      pickOnly(hits.length > 1 ? hits[(only + 1) % hits.length] : null);
      return;
    }
    pickOnly(hits[0]);
  };

  // Only a SELECTED box takes the pointer; an unselected one is draw-through,
  // so a drag across it makes a new box and a click on it selects it (see
  // `clickAt`). That is what lets one gesture do both without a mode.
  //
  // The selection is NOT changed here. A press on a selected box may turn out
  // to be a move or a click, and only the mouseup knows which — deciding on
  // the way down would deselect the box somebody was about to drag.
  const startMove = (e: React.MouseEvent, b: Box) => {
    // Let a middle-button press bubble to the background handler so it pans.
    if (e.button !== 0) return;
    e.stopPropagation();
    const f = frac(e.clientX, e.clientY);
    // A PRESS NEAR THE OUTLINE, IN POLY MODE, DRAGS THAT EDGE — both of its
    // corners at once — and never the whole shape. Two things at once, and
    // they are the same rule read from either end. An EDGE is a thing
    // somebody means to move: "this side is a little too far left" is one
    // gesture, where doing it corner by corner is two drags that have to
    // agree. And a near miss on a CORNER used to grab the shape and move it,
    // which is the worst possible answer to "I meant that point" — the whole
    // outline moves, and the thing being aimed at goes with it.
    //
    // The corners still win: their handles sit on top with a grab square
    // wider than the band. The interior still moves the shape. Box mode is
    // untouched — there are no corner handles there to miss, and its
    // bounding-box handles are what an edge means there.
    if (polyUIRef.current) {
      const pts = b.points ?? rectPts(b);
      const edge = nearestEdge(f, pts, EDGE_DEAD);
      if (edge >= 0) {
        drag.current = { kind: "emove", cid: b.cid, idx: edge,
                         pts0: pts.map((pt) => [...pt] as [number, number]),
                         startFrac: f, orig: b, moved: false };
        return;
      }
    }
    drag.current = { kind: "move", cid: b.cid, startFrac: f, orig: b,
                     shift: e.shiftKey };
  };
  const startResize = (e: React.MouseEvent, b: Box, corner: string) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    drag.current = { kind: "resize", cid: b.cid, corner, orig: b };
  };
  /** Turn the shape about its own centre. A rectangle becomes a four-point
   *  POLYGON the moment it turns — which is the whole reason this is a small
   *  feature: `points` is already the geometry and the rect columns already
   *  its bounding box, so a turned box stores, searches, crops, masks,
   *  merges and reverts exactly as any polygon does. */
  const startRotate = (e: React.MouseEvent, b: Box, aspect: number) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    const pts0 = (b.points ?? rectPts(b)).map((pt) => [...pt] as [number, number]);
    const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
    const f = frac(e.clientX, e.clientY);
    drag.current = { kind: "rotate", cid: b.cid, orig: b, pts0, cx, cy,
                     a0: angleTo(f, cx, cy, aspect), aspect };
  };
  // Poly-mode corner editing. `pts` is the shape as rendered — a plain
  // rectangle's four derived corners included, so dragging one of those is
  // exactly what turns the rect into a polygon.
  const startVertex = (e: React.MouseEvent, b: Box,
                       pts: [number, number][], idx: number) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    drag.current = { kind: "vmove", cid: b.cid, idx,
                     pts0: pts.map((pt) => [...pt] as [number, number]),
                     orig: b, moved: false };
  };
  const insertVertex = (e: React.MouseEvent, b: Box,
                        pts: [number, number][], after: number,
                        at: [number, number]) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    const pts0 = [...pts.slice(0, after + 1), at, ...pts.slice(after + 1)]
      .map((pt) => [...pt] as [number, number]);
    drag.current = { kind: "vmove", cid: b.cid, idx: after + 1, pts0, orig: b,
                     moved: true };
    putLiveBox(b.cid, { ...b, ...polyBounds(pts0), points: pts0 });
  };
  /** Take one corner off. A plain RECT counts as its four derived corners —
   *  removing one is what turns it into a (triangle) polygon; a polygon
   *  already at three keeps them, since fewer is not a shape. */
  const removeVertex = (b: Box, pts: [number, number][], idx: number) => {
    if (pts.length <= 3) return;
    const next = pts.filter((_, i) => i !== idx)
      .map((pt) => [...pt] as [number, number]);
    setSelVertex(null);
    apply(boxesRef.current.map((bx) => (bx.cid === b.cid
      ? { ...bx, ...polyBounds(next), points: next } : bx)));
  };
  // The pending box moves and resizes like a real one, but writes straight back
  // into `pending` (there is nothing on the server to reconcile yet).
  const startPendingDrag = (e: React.MouseEvent, corner: string | null) => {
    if (e.button !== 0 || !pending) return;
    e.stopPropagation();
    drag.current = corner
      ? { kind: "presize", corner, orig: pending.box }
      : { kind: "pmove", startFrac: frac(e.clientX, e.clientY), orig: pending.box };
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = drag.current;
      if (!d) return;
      if (d.kind === "pan") {
        setPan({ x: d.pan0.x + (e.clientX - d.from.x), y: d.pan0.y + (e.clientY - d.from.y) });
        return;
      }
      const f = frac(e.clientX, e.clientY);
      if (d.kind === "draw") {
        setDraft({
          x: Math.min(d.start.x, f.x), y: Math.min(d.start.y, f.y),
          w: Math.abs(f.x - d.start.x), h: Math.abs(f.y - d.start.y),
        });
      } else if (d.kind === "move") {
        const dx = f.x - d.startFrac.x, dy = f.y - d.startFrac.y;
        const nx = Math.max(0, Math.min(1 - d.orig.w, d.orig.x + dx));
        const ny = Math.max(0, Math.min(1 - d.orig.h, d.orig.y + dy));
        // The polygon travels with its bounding box — a translated shape.
        const pts = d.orig.points?.length
          ? affinePts(d.orig.points, d.orig, { ...d.orig, x: nx, y: ny })
          : undefined;
        putLiveBox(d.cid, { ...d.orig, x: nx, y: ny, points: pts });
      } else if (d.kind === "resize") {
        const o = d.orig;
        let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
        if (d.corner.includes("w")) x1 = f.x;
        if (d.corner.includes("e")) x2 = f.x;
        if (d.corner.includes("n")) y1 = f.y;
        if (d.corner.includes("s")) y2 = f.y;
        const nx = Math.min(x1, x2), ny = Math.min(y1, y2);
        const geo = { x: nx, y: ny, w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
        // The box-mode transform: the bbox handles scale the polygon.
        const pts = o.points?.length ? affinePts(o.points, o, geo) : undefined;
        putLiveBox(d.cid, { ...o, ...geo, points: pts });
      } else if (d.kind === "rotate") {
        // SHIFT snaps to 15°, the one modifier a rotation wants: most turns
        // are meant to be square with something in the picture.
        let ang = angleTo(f, d.cx, d.cy, d.aspect) - d.a0;
        if (e.shiftKey) {
          const step = Math.PI / 12;
          ang = Math.round(ang / step) * step;
        }
        const pts = rotatePts(d.pts0, d.cx, d.cy, ang, d.aspect);
        putLiveBox(d.cid, { ...d.orig, ...polyBounds(pts), points: pts });
      } else if (d.kind === "polypt") {
        d.moved = true;
        setPolyDraft((cur) => cur
          ? cur.map((pt, i): [number, number] => i === d.idx ? [f.x, f.y] : pt)
          : cur);
      } else if (d.kind === "emove") {
        d.moved = true;
        const dx = f.x - d.startFrac.x, dy = f.y - d.startFrac.y;
        const a = d.idx, bIdx = (d.idx + 1) % d.pts0.length;
        const pts = d.pts0.map((pt, i): [number, number] =>
          i === a || i === bIdx ? [pt[0] + dx, pt[1] + dy] : pt);
        putLiveBox(d.cid, { ...d.orig, ...polyBounds(pts), points: pts });
      } else if (d.kind === "vmove") {
        d.moved = true;
        const pts = d.pts0.map((pt, i): [number, number] =>
          i === d.idx ? [f.x, f.y] : pt);
        putLiveBox(d.cid, { ...d.orig, ...polyBounds(pts), points: pts });
      } else if (d.kind === "omove") {
        const dx = f.x - d.startFrac.x, dy = f.y - d.startFrac.y;
        const nx = Math.max(0, Math.min(1 - d.orig.w, d.orig.x + dx));
        const ny = Math.max(0, Math.min(1 - d.orig.h, d.orig.y + dy));
        const pts = d.orig.points?.length
          ? affinePts(d.orig.points, d.orig, { ...d.orig, x: nx, y: ny })
          : undefined;
        setLiveOutline({ okey: d.okey, ...d.orig, x: nx, y: ny, points: pts });
      } else if (d.kind === "oresize") {
        const o = d.orig;
        let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
        if (d.corner.includes("w")) x1 = f.x;
        if (d.corner.includes("e")) x2 = f.x;
        if (d.corner.includes("n")) y1 = f.y;
        if (d.corner.includes("s")) y2 = f.y;
        const geo = { x: Math.min(x1, x2), y: Math.min(y1, y2),
                      w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
        const pts = o.points?.length ? affinePts(o.points, o, geo) : undefined;
        setLiveOutline({ okey: d.okey, ...geo, points: pts });
      } else if (d.kind === "ovmove") {
        d.moved = true;
        const pts = d.pts0.map((pt, i): [number, number] =>
          i === d.idx ? [f.x, f.y] : pt);
        setLiveOutline({ okey: d.okey, ...polyBounds(pts), points: pts });
      } else if (d.kind === "tmove") {
        const dx = f.x - d.startFrac.x, dy = f.y - d.startFrac.y;
        const nx = Math.max(0, Math.min(1 - d.orig.w, d.orig.x + dx));
        const ny = Math.max(0, Math.min(1 - d.orig.h, d.orig.y + dy));
        const quad = d.orig.quad
          ? affinePts(d.orig.quad, d.orig, { ...d.orig, x: nx, y: ny })
          : undefined;
        setLiveText({ id: d.id, ...d.orig, x: nx, y: ny, quad });
      } else if (d.kind === "tresize") {
        const o = d.orig;
        let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
        if (d.corner.includes("w")) x1 = f.x;
        if (d.corner.includes("e")) x2 = f.x;
        if (d.corner.includes("n")) y1 = f.y;
        if (d.corner.includes("s")) y2 = f.y;
        const geo = { x: Math.min(x1, x2), y: Math.min(y1, y2),
                      w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
        const quad = o.quad ? affinePts(o.quad, o, geo) : undefined;
        setLiveText({ id: d.id, ...geo, quad });
      } else if (d.kind === "facemove") {
        const dx = f.x - d.startFrac.x, dy = f.y - d.startFrac.y;
        const nx = Math.max(0, Math.min(1 - d.orig.w, d.orig.x + dx));
        const ny = Math.max(0, Math.min(1 - d.orig.h, d.orig.y + dy));
        putLiveFace(d.id, { ...d.orig, x: nx, y: ny });
      } else if (d.kind === "faceresize") {
        const o = d.orig;
        let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
        if (d.corner.includes("w")) x1 = f.x;
        if (d.corner.includes("e")) x2 = f.x;
        if (d.corner.includes("n")) y1 = f.y;
        if (d.corner.includes("s")) y2 = f.y;
        putLiveFace(d.id, {
          x: Math.min(x1, x2), y: Math.min(y1, y2),
          w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) });
      } else if (d.kind === "pmove") {
        const dx = f.x - d.startFrac.x, dy = f.y - d.startFrac.y;
        const nx = Math.max(0, Math.min(1 - d.orig.w, d.orig.x + dx));
        const ny = Math.max(0, Math.min(1 - d.orig.h, d.orig.y + dy));
        const pts = d.orig.points?.length
          ? affinePts(d.orig.points, d.orig, { ...d.orig, x: nx, y: ny })
          : undefined;
        setPending({ box: { ...d.orig, x: nx, y: ny, points: pts } });
      } else if (d.kind === "presize") {
        const o = d.orig;
        let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
        if (d.corner.includes("w")) x1 = f.x;
        if (d.corner.includes("e")) x2 = f.x;
        if (d.corner.includes("n")) y1 = f.y;
        if (d.corner.includes("s")) y2 = f.y;
        const geo = { x: Math.min(x1, x2), y: Math.min(y1, y2),
                      w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
        const pts = o.points?.length ? affinePts(o.points, o, geo) : undefined;
        setPending({ box: { ...o, ...geo, points: pts } });
      } else if (d.kind === "marquee") {
        setMarquee({
          x: Math.min(d.start.x, f.x), y: Math.min(d.start.y, f.y),
          w: Math.abs(f.x - d.start.x), h: Math.abs(f.y - d.start.y),
        });
      }
    };
    const onUp = (e: MouseEvent) => {
      const d = drag.current;
      drag.current = null;
      if (!d) return;
      if (d.kind === "polypt") {
        return; // the corner stays where the release left it
      }
      if (d.kind === "emove") {
        const live = liveBoxesRef.current[d.cid];
        dropLiveBox(d.cid);
        // A press on the line that never travelled is a CLICK, and the
        // shape is already selected (only a selected box takes the pointer),
        // so it means the tag boxes' cycle: down through whatever else is
        // under the pointer, or put this one down.
        if (!d.moved) { clickAt(frac(e.clientX, e.clientY), false); return; }
        if (live && !geoSame(live, d.orig)) {
          apply(boxesRef.current.map((b) => (b.cid === d.cid
            ? { ...b, x: live.x, y: live.y, w: live.w, h: live.h,
                points: live.points } : b)));
        }
        return;
      }
      if (d.kind === "vmove") {
        const live = liveBoxesRef.current[d.cid];
        dropLiveBox(d.cid);
        if (!d.moved) {
          // A press that never moved is a click: it PICKS the corner, and
          // Delete then removes that corner rather than the whole box.
          setSelVertex({ kind: "box", cid: d.cid, idx: d.idx });
          return;
        }
        if (live && !geoSame(live, d.orig)) {
          apply(boxesRef.current.map((b) => (b.cid === d.cid
            ? { ...b, x: live.x, y: live.y, w: live.w, h: live.h,
                points: live.points } : b)));
        }
        return;
      }
      if (d.kind === "ovmove" && !d.moved) {
        setLiveOutline(null);
        setSelVertex({ kind: "out", okey: d.okey, idx: d.idx, pts: d.pts0 });
        return;
      }
      if (d.kind === "tmove" || d.kind === "tresize") {
        const live = liveTextRef.current;
        if (live && live.id === d.id
            && !(near(live.x, d.orig.x) && near(live.y, d.orig.y)
                 && near(live.w, d.orig.w) && near(live.h, d.orig.h))) {
          commitTextRef.current(live);
        } else {
          setLiveText(null);
        }
        return;
      }
      if (d.kind === "omove" || d.kind === "oresize" || d.kind === "ovmove") {
        const live = liveOutlineRef.current;
        if (live && live.okey === d.okey
            && !(d.kind !== "ovmove" && near(live.x, d.orig.x)
                 && near(live.y, d.orig.y) && near(live.w, d.orig.w)
                 && near(live.h, d.orig.h))) {
          commitOutlineRef.current(live, d.okey);
        } else {
          setLiveOutline(null);
          // It never moved, so it was a click on an outline that was already
          // selected — which cycles down through whatever else is under the
          // pointer, or puts it down: the tag boxes' rule, and without it two
          // overlapping outlines left the one underneath unreachable. Only
          // for the body press — a corner handle's click is about the corner.
          if (d.kind === "omove") clickAt(frac(e.clientX, e.clientY), d.shift);
        }
        return;
      }
      if (d.kind === "draw") {
        const f = frac(e.clientX, e.clientY);
        const rect = {
          x: Math.min(d.start.x, f.x), y: Math.min(d.start.y, f.y),
          w: Math.abs(f.x - d.start.x), h: Math.abs(f.y - d.start.y),
        };
        setDraft(null);
        // Too small to be a box: it was a click, so it picks rather than draws.
        if (rect.w <= 0.01 && rect.h <= 0.01) { clickAt(f, d.shift); return; }
        // Poly mode's press-on-something: releasing may only pick, and a
        // drag that moved is simply nothing.
        if (d.pickOnly) return;
        if (rect.w > 0.01 && rect.h > 0.01) {
          // OUTLINE draw mode (the face|person switch): the rectangle is a
          // subject's outline — onto the picked people rows, or a fresh
          // shape that asks who it is (the face naming flow, one level up).
          if (faceModeRef.current && subjectDrawRef.current === "outline"
              && !onVideoRef.current && itemId != null) {
            commitSubjectOutlineRef.current(rect);
            return;
          }
          // Faces mode: the drag draws a face, not a tag box. A hand-drawn face
          // has no detector and so no score — and no later run may take it away
          // (`reconcile` never touches what it did not find).
          if (faceModeRef.current && !onVideoRef.current && itemId != null) {
            // Which row is the new one is answered by DIFFING the ids: the
            // endpoint replies with the item's whole face list, sorted biggest
            // first, so the last row is the SMALLEST face — and the naming
            // field used to open on whichever unrelated face that was.
            const before = new Set((facesRef.current ?? []).map((fc) => fc.id));
            void api.addFace({ item_id: itemId, ...fileToRef(rect, activeFileRef.current) })
              .then((rows) => {
                refreshFacesRef.current();
                const made = rows.find((fc) => !before.has(fc.id));
                if (made) { setNamingFace(made.id); setFaceName(""); }
              });
            return;
          }
          // Text mode: the drag draws a text box — level "block", no parent,
          // no engine, so no run may rewrite what is typed into it. The new
          // row's editor opens focused and EMPTY (`autoEdit`): you are
          // transcribing, not replacing. Which row is new is answered by
          // DIFFING the ids (the reply is the whole tree in reading order,
          // and the last row is whatever sorted last — the faces lesson).
          if (textModeRef.current && !faceModeRef.current
              && !onVideoRef.current && itemId != null) {
            const before = new Set(textRegionsRef.current.map((r) => r.id));
            void api.addTextRegion({
              item_id: itemId,
              ...fileToRef(rect, activeFileRef.current),
            }).then((rows) => {
              qc.setQueryData(["text", itemId], rows);
              refreshTextRef.current();
              const flat: TextRegion[] = [];
              const visit = (r: TextRegion) => {
                flat.push(r); r.children.forEach(visit);
              };
              rows.forEach(visit);
              const made = flat.find((r) => !before.has(r.id));
              if (made) {
                setTextSel([textRowKey(made.id)]);
                setTextAutoEdit(made.id);
              }
            });
            return;
          }
          // Nothing to draw on the FILM: a video's own tags carry times, not
          // geometry, so there is nothing on a moving picture for a box to be
          // attached to. Boxes live on stills (and a still is the whole frame).
          if (onVideoRef.current) return;
          // The new box takes the tags selected in the sidebar; with none
          // selected it asks for a name instead.
          const labels = labelsRef.current;
          // In OCTAGON mode the same drag leaves a polygon behind — the
          // rectangle it was dragged out to, with its corners cut. It is an
          // ordinary polygon box from that moment on (`points` is the
          // geometry, the rect columns its bounding box), so nothing
          // downstream learns a third shape.
          const shape = drawShapeRef.current === "octagon"
            ? { ...rect, points: octPts(rect) } : rect;
          if (labels.length) {
            const box = { cid: newCid(), labels: labels.map((l) => ({ ...l })), ...shape };
            apply([...boxesRef.current, box]);
          } else {
            // Ask for a tag name before committing the new box.
            setPending({ box: { cid: newCid(), labels: [], ...shape } });
            setNameInput("");
          }
        }
      } else if (d.kind === "move" || d.kind === "resize"
                 || d.kind === "rotate") {
        const live = liveBoxesRef.current[d.cid];
        dropLiveBox(d.cid);
        if (live && !geoSame(live, d.orig)) {
          apply(boxesRef.current.map((b) => (b.cid === d.cid
            ? { ...b, x: live.x, y: live.y, w: live.w, h: live.h,
                points: live.points } : b)));
        } else if (d.kind === "move") {
          // It never moved, so it was a click on a box that was already
          // selected — which is how one is put down again.
          clickAt(frac(e.clientX, e.clientY), d.shift);
        }
      } else if (d.kind === "facemove") {
        const live = liveFacesRef.current[d.id];
        if (live && !(near(live.x, d.orig.x) && near(live.y, d.orig.y))) {
          commitFaceMoveRef.current(d.id, live);
        } else {
          dropLiveFace(d.id);
          // Never moved: it was a click on a face that was already
          // selected, which is how one is put down again.
          clickAt(frac(e.clientX, e.clientY), d.shift);
        }
      } else if (d.kind === "faceresize") {
        const live = liveFacesRef.current[d.id];
        if (live && !(near(live.x, d.orig.x) && near(live.y, d.orig.y)
            && near(live.w, d.orig.w) && near(live.h, d.orig.h))) {
          commitFaceMoveRef.current(d.id, live);
        } else {
          dropLiveFace(d.id);
        }
      } else if (d.kind === "marquee") {
        const f = frac(e.clientX, e.clientY);
        const rect = {
          x: Math.min(d.start.x, f.x), y: Math.min(d.start.y, f.y),
          w: Math.abs(f.x - d.start.x), h: Math.abs(f.y - d.start.y),
        };
        setMarquee(null);
        // In face mode the band picks FACES: they are what is drawn over the
        // picture there, and a rubber band that swept up tag boxes nobody can
        // see would be selecting things off screen. In OUTLINE mode it picks
        // the outlines instead — as their sidebar rows, which IS their
        // selection.
        if (faceModeRef.current && subjectDrawRef.current === "outline") {
          if (rect.w < 0.005 && rect.h < 0.005) {
            if (!d.additive) clearPeopleRef.current();
          } else {
            const hit = outlineGeosRef.current
              .filter((g) => g.key.startsWith("app:"))
              .filter((g) => g.x < rect.x + rect.w && g.x + g.w > rect.x
                && g.y < rect.y + rect.h && g.y + g.h > rect.y)
              .map((g) => `a:${g.key.slice(4)}`);
            if (hit.length) setFaceSel([]);
            subjectSelSetRef.current(d.additive
              ? Array.from(new Set([...subjectSelRef.current, ...hit]))
              : hit);
          }
        } else if (faceModeRef.current) {
          if (rect.w < 0.005 && rect.h < 0.005) {
            if (!d.additive) setFaceSel([]);
          } else {
            const hit = (facesRef.current ?? [])
              .filter((fc) => !fc.dismissed)
              .map((fc) => ({ id: fc.id, r: refToFile(fc, activeFileRef.current) }))
              .filter(({ r }) => r.x < rect.x + rect.w && r.x + r.w > rect.x
                && r.y < rect.y + rect.h && r.y + r.h > rect.y)
              .map(({ id }) => id);
            if (hit.length) clearPeopleRef.current();
            setFaceSel(d.additive
              ? Array.from(new Set([...faceSelRef.current, ...hit])) : hit);
          }
        } else if (textModeRef.current) {
          // In text mode the band picks TEXT REGIONS — they are what is
          // drawn there, and a band that swept up hidden tag boxes would be
          // selecting things off screen.
          if (rect.w < 0.005 && rect.h < 0.005) {
            if (!d.additive) setTextSel([]);
          } else {
            const file = activeFileRef.current;
            const hit = textRegionsRef.current
              .filter((r) => !r.dismissed && r.parent_id == null
                && textVisibleRef.current.has(r.id))
              .map((r) => ({ id: r.id, r: refToFile(r, file) }))
              .filter(({ r }) => r.x < rect.x + rect.w && r.x + r.w > rect.x
                && r.y < rect.y + rect.h && r.y + r.h > rect.y)
              .map(({ id }) => textRowKey(id));
            setTextSel(d.additive
              ? Array.from(new Set([...textSelRef.current, ...hit])) : hit);
          }
        } else if (rect.w < 0.005 && rect.h < 0.005) {
          // A plain click on empty space clears the selection.
          if (!d.additive) setSelectedCids([]);
        } else {
          const hit = boxesRef.current
            // Only what is drawn, for the same reason a click only picks what
            // is drawn: a band must not sweep up rectangles nobody can see.
            .filter((b) => boxDrawnRef.current(b))
            .filter((b) => b.x < rect.x + rect.w && b.x + b.w > rect.x
              && b.y < rect.y + rect.h && b.y + b.h > rect.y)
            .map((b) => b.cid);
          setSelectedCids(d.additive ? Array.from(new Set([...d.base, ...hit])) : hit);
        }
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // NOT `liveBoxes`/`liveFaces`: the handlers read those through refs
    // now, so the listeners are registered ONCE for the length of a drag
    // rather than torn down and rebuilt on every pointer sample.
  }, [apply, putLiveBox, dropLiveBox, putLiveFace, dropLiveFace]);

  // Keep a ref of the latest boxes so pointer handlers read fresh state.
  const boxesRef = useRef<Box[]>(boxes);
  boxesRef.current = boxes;
  // Same for the selection — the key handler is registered once.
  const selectedCidsRef = useRef<string[]>(selectedCids);
  selectedCidsRef.current = selectedCids;

  // Selecting a box selects its tag row(s) in the sidebar — the canvas and the
  // tag list are two views of one selection. Only this direction is mirrored:
  // selecting rows in the sidebar filters what is drawn (see `boxVisible`) but
  // must not reach back and select boxes, or the two would chase each other.
  const selectedCidsKey = selectedCids.join(" ");
  useEffect(() => {
    const keys = new Set<string>();
    for (const cid of selectedCidsRef.current) {
      const b = boxesRef.current.find((x) => x.cid === cid);
      for (const l of b?.labels ?? []) keys.add(tagRowKey(l.group ?? null, l.tag));
    }
    setTagSel([...keys]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCidsKey]);
  // Latest selected tag rows, read by the (persistent) pointer-up handler.
  const labelsRef = useRef(selectedLabels);
  labelsRef.current = selectedLabels;
  // Same for "is the canvas a film right now" and how to capture a snapshot of
  // it — the draw handler is registered once and must not close over either.
  const onVideoRef = useRef(onVideo);
  onVideoRef.current = onVideo;

  const commitPending = (typed?: string) => {
    if (!pending) return;
    const name = tagFieldName(typed ?? nameInput);
    if (name) {
      // A named box lands in the group of the first selected row (the group the
      // user was working in), else Ungrouped.
      apply([...boxesRef.current, {
        ...pending.box,
        labels: [{ tag: name, group: labelsRef.current[0]?.group ?? null }],
      }]);
    }
    setPending(null);
    setNameInput("");
  };
  const commitRename = () => {
    const r = renaming;
    setRenaming(null);
    if (!r) return;
    const name = tagFieldName(nameInput);
    const b = boxesRef.current.find((x) => x.cid === r.cid);
    if (!b || !name || name === r.tag) return;
    if (b.labels.some((l) => l.tag === name)) return; // no duplicate tags in a box
    apply(boxesRef.current.map((x) => x.cid !== r.cid ? x : {
      ...x, labels: x.labels.map((l) => l.tag === r.tag ? { ...l, tag: name } : l),
    }));
    // The selection follows the tag it named. A row key carries the NAME, so
    // renaming leaves the old key pointing at a row that no longer exists —
    // the box goes quiet (nothing matches the filter) and the list shows
    // nothing picked, for an edit that changed only what the tag is called.
    const g = b.labels.find((l) => l.tag === r.tag)?.group ?? null;
    const was = tagRowKey(g, r.tag);
    const now = tagRowKey(g, name);
    setTagSel((cur) => (cur.includes(was)
      ? Array.from(new Set(cur.map((k) => (k === was ? now : k)))) : cur));
  };
  const commitAddLabel = (typed?: string) => {
    const cid = addingTo;
    setAddingTo(null);
    if (!cid) return;
    const name = tagFieldName(typed ?? nameInput);
    setNameInput("");
    const b = boxesRef.current.find((x) => x.cid === cid);
    if (!b || !name || b.labels.some((l) => l.tag === name)) return;
    apply(boxesRef.current.map((x) => x.cid !== cid ? x
      : { ...x, labels: [...x.labels, { tag: name, group: labelsRef.current[0]?.group ?? null }] }));
  };
  const removeLabel = (cid: string, tag: string) => {
    const b = boxesRef.current.find((x) => x.cid === cid);
    if (!b) return;
    if (b.labels.length <= 1) { removeBox(cid); return; } // last tag → drop the box
    apply(boxesRef.current.map((x) => x.cid !== cid ? x : { ...x, labels: x.labels.filter((l) => l.tag !== tag) }));
  };
  const removeBox = (cid: string) => apply(boxesRef.current.filter((b) => b.cid !== cid));

  // Move an existing label's tag into a different group. Tag groups are a
  // separate server concept (a placement), so this can't ride the box
  // reconcile: flush any pending box writes, move the instance server-side,
  // then re-initialize the local box set from the fresh item.
  const changeLabelGroup = async (cid: string, tag: string, to: number | null | "__new__") => {
    setGroupMenu(null);
    const b = boxesRef.current.find((x) => x.cid === cid);
    const lb = b?.labels.find((l) => l.tag === tag);
    if (!b || !lb) return;
    await chain.current; // ensure the box (and its server id) exists first
    let toGroup: number | null;
    if (to === "__new__") {
      const name = (window.prompt(t("New tag group name"), t("New group")) || "").trim();
      if (!name) return;
      const g = await api.createTagGroup(itemId as number, name);
      toGroup = g.id;
    } else {
      toGroup = to;
    }
    if (lb.group === toGroup) return;
    await api.moveTagInstance(itemId as number, tag, lb.group, toGroup);
    // Rebuild from the server so the grouping (and box ids) stay consistent.
    initedFor.current = null;
    await qc.invalidateQueries({ queryKey: ["item", itemId] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    bumpEdits();
  };

  // Wheel zoom keeps the image point under the cursor fixed (Photoshop-style).
  // Every wheel over the canvas is the picture's, ctrl held or not — see
  // `useWheel`, which is what lets the browser's own page zoom be refused.
  useWheel(viewportRef, (e) => {
    e.preventDefault();
    const r = viewportRef.current?.getBoundingClientRect();
    const vx = r ? e.clientX - r.left : vp.w / 2;
    const vy = r ? e.clientY - r.top : vp.h / 2;
    zp.zoomAt(vx, vy, e.deltaY < 0 ? 1.1 : 0.9);
  });

  // ---- keyboard ----
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e)) return;
      // ON A FILM THE TRANSPORT OWNS THE KEYBOARD (`shared/videoKeys`, the
      // same map the video editor uses — the two are halves of one window
      // over one film, and a key that paused in one and did nothing in the
      // other would be one feature wearing two behaviours). Space/K play,
      // ←/→ step a frame, J/L shuttle.
      //
      // It costs the two things those keys do on a PICTURE, and only there:
      // Space is Photoshop's pan-hold and ←/→ walk the window's own tabs.
      // Both stay exactly as they were on a picture — this is not a mode, it
      // is what the tab in front of you IS.
      if (isVideoRef.current) {
        const act = videoKeyAction(e);
        if (act) { e.preventDefault(); runVideoKey(act, playRef.current); return; }
      }
      // Space holds pan mode (Photoshop-style), unless typing in a field.
      if (e.code === "Space") {
        e.preventDefault();
        setSpaceHeld(true);
        return;
      }
      // A polygon draft owns Enter / Escape / Backspace while it is up:
      // finish, cancel, take the last corner back.
      if (polyDraftRef.current) {
        if (e.key === "Enter") {
          e.preventDefault();
          finishPolyRef.current();
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setPolyDraft(null);
          setPolyHover(null);
          return;
        }
        if (e.key === "Backspace" || e.key === "Delete") {
          e.preventDefault();
          setPolyDraft((cur) =>
            cur && cur.length > 1 ? cur.slice(0, -1) : null);
          return;
        }
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo(); else undo();
      } else if (e.key === "Delete" || e.key === "Backspace") {
        // A picked CORNER takes the key before the box selection does.
        if (deleteSelVertexRef.current()) { e.preventDefault(); return; }
        // Delete the selected box(es). Backspace too — it is the delete key on
        // a Mac keyboard, and nothing here is a text field once `typing` is out.
        if (selectedCidsRef.current.length) {
          e.preventDefault();
          const gone = new Set(selectedCidsRef.current);
          setSelectedCids([]);
          apply(boxesRef.current.filter((b) => !gone.has(b.cid)));
        }
      // ←/→ step through the window's OWN tabs now, not the whole grid: this
      // window holds the items it was opened on, and walking past them into
      // whatever else the grid was showing is not what the arrows can mean any
      // more.
      // ←/→ step through the window's OWN tabs (on a FILM they are a frame —
      // see the transport above).
      } else if (e.key === "ArrowRight") { goTab(1); }
      else if (e.key === "ArrowLeft") { goTab(-1); }
      else if (e.key === "Escape") {
        if (groupMenu) { setGroupMenu(null); }
        else if (pendingOutlineRef.current) {
          setPendingOutline(null); setOutlineName("");
        }
        else if (pending) { setPending(null); }
        else if (addingTo) { setAddingTo(null); }
        else if (renaming) { setRenaming(null); }
        else requestCloseRef.current();
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space") setSpaceHeld(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [undo, redo, pending, addingTo, renaming, groupMenu]);


  // ---- stills (video) ----
  // Every image item captured from this film. A snapshot is an ordinary image
  // item, so opening one here is just pointing `itemId` at it: its tags, groups
  // and boxes are the same machinery an imported picture uses.
  const { data: stills } = useQuery({
    queryKey: ["stills", hostId],
    queryFn: () => api.stills(hostId as number),
    enabled: isVideo && hostId != null,
  });
  // The ones taken at the frame on screen (half a frame either way).
  const frameStills = useMemo(
    () => (stills ?? []).filter((st) => Math.abs(st.timestamp - play.time) <= 0.5 / fps),
    [stills, play.time, fps]
  );
  const [capturing, setCapturing] = useState(false);
  // A whole frame can only be a still once — capturing it again dedups onto the
  // one that is already there, so the button says so rather than no-op.
  const wholeFrameTaken = frameStills.some((st) => !st.crop);
  // A still is always the WHOLE frame. Cropping is the image editor's job, done
  // on the still itself, so a crop links to the still it came from — crop →
  // still → film — rather than claiming to be a frame of the film.
  const makeStill = async () => {
    if (hostId == null || capturing) return;
    setCapturing(true);
    try {
      await api.captureFrame(hostId, play.nowTime());
      await qc.invalidateQueries({ queryKey: ["stills", hostId] });
      qc.invalidateQueries({ queryKey: ["items"] });
      bumpEdits();
      // IT GOES IN THE LIST AND NOTHING ELSE HAPPENS. It used to open in a
      // tab of its own ("you took it to tag it"), which is true of one still
      // and wrong of the way stills are actually taken: several moments of a
      // film in a row, each one throwing the film off screen and needing the
      // tab put away again before the next. The list is right there, and
      // double-clicking a row is how you open one.
    } finally {
      setCapturing(false);
    }
  };
  // ---- a still every N seconds --------------------------------------------
  // The interval lives in the BROWSER, `text/engineChoice.ts`' reasoning: how
  // often you want a still out of a film is personal working state, not a
  // fact about the film. One value for the app rather than one per item —
  // unlike an engine choice, "every 5 seconds" is a habit rather than a
  // decision about this chapter.
  const [everySecs, setEverySecs] = useState<number>(() => {
    try {
      const v = Number(storage.get(EVERY_KEY));
      return v > 0 ? v : 5;
    } catch { return 5; }
  });
  const [everyOpen, setEveryOpen] = useState(false);
  const [everyDraft, setEveryDraft] = useState("5");
  // WHAT THE RUN WILL TAKE is counted by the SERVER and reported back — the
  // rule ("every N seconds of this film") is `every_n_timestamps` and an
  // estimate here would be a second copy of it, differing in exactly the
  // cases that are hard (where the last moment falls, whether the film's
  // duration is a frame you can seek to).
  const [everyMsg, setEveryMsg] = useState("");
  const { data: mlJobsData } = useQuery({
    queryKey: ["ml-jobs"], queryFn: api.mlJobs,
    enabled: isVideo,
    // Only while one of ours is in flight; the enqueue below invalidates this
    // query, which is what starts the polling at all. IN THE BACKGROUND TOO:
    // taking a few hundred stills is exactly the wait you spend in another
    // window (the editor's Detect text records the same trap).
    refetchInterval: (q) => {
      const jobs = (q.state.data as { jobs: JobOut[] } | undefined)?.jobs ?? [];
      return jobs.some((j) => j.kind === "stills"
        && (j.status === "queued" || j.status === "running")) ? 1200 : false;
    },
    refetchIntervalInBackground: true,
  });
  const stillsJob = (mlJobsData?.jobs ?? []).find(
    (j) => j.kind === "stills" && j.item_id === hostId
      && (j.status === "queued" || j.status === "running"));
  // A RUN WE STARTED, still outstanding. The list has to be refreshed when it
  // ends, and the library's own job-finish sweep cannot be relied on: it runs
  // from `JobList`, which polls every few seconds, and a run of a dozen
  // stills is over before it looks (the editor's Detect text records the same
  // trap). So this watches the job list itself — the enqueue invalidates it,
  // and the first answer that no longer holds our job is the finish.
  const stillsRunRef = useRef(false);
  const takeEvery = async () => {
    if (hostId == null || stillsJob) return;
    setEveryMsg("");
    try {
      const r = await api.captureFramesEvery(
        hostId, everySecs, markedRange ?? undefined);
      setEveryMsg(r.message || "");
      stillsRunRef.current = true;
      qc.invalidateQueries({ queryKey: ["ml-jobs"] });
    } catch (e: unknown) {
      setEveryMsg(errText(e));
    }
  };
  useEffect(() => {
    if (!stillsRunRef.current || stillsJob) return;
    stillsRunRef.current = false;
    void qc.invalidateQueries({ queryKey: ["stills", hostId] });
    qc.invalidateQueries({ queryKey: ["items"] });
    bumpEdits();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stillsJob, mlJobsData, hostId]);

  // Removing a snapshot trashes its item — it IS an item, so it goes where
  // every other deleted item goes and can be restored from there. Its tab
  // goes with it: a tab on a trashed item is a window onto nothing.
  // WHICH STILL IS BEING ASKED ABOUT. Removing one takes an ITEM to the trash
  // — with whatever was tagged on it, and its own tab with it — so it asks
  // first. The other actions on that row are a seek and an open; a bin sitting
  // among them that fires on the first click is the one irreversible thing in
  // a list of reversible ones.
  const saveEvery = () => {
    const v = Number(everyDraft);
    if (!(v > 0)) return;
    setEverySecs(v);
    try { storage.set(EVERY_KEY, String(v)); } catch { /* private mode */ }
    setEveryOpen(false);
  };
  const [stillToRemove, setStillToRemove] = useState<number | null>(null);
  const removeStill = async (id: number) => {
    closeEditorTab(id);
    await api.trashItems([id]);
    await qc.invalidateQueries({ queryKey: ["stills", hostId] });
    qc.invalidateQueries({ queryKey: ["items"] });
    bumpEdits();
  };

  // ---- jumping between interesting frames ----
  // The moments where the answer to "what is here?" changes: every time a timed
  // tag starts or stops, and every moment that holds a still. Jumping between
  // them is how you sweep a film without scrubbing blind.
  const jumpTo = (times: number[], dir: 1 | -1) => {
    const next = nextStop(times, play.nowTime(), dir, fps);
    if (next != null) play.seek(next);
  };
  const tagChangeTimes = useMemo(() => {
    const out = new Set<number>();
    for (const t of hostItem?.tag_instances ?? []) {
      for (const b of t.boxes ?? []) {
        if (b.time_start == null) continue;
        out.add(b.time_start);
        // One frame PAST the end: that is the first frame where the tag is gone,
        // which is the change you want to land on.
        if (b.time_end != null) out.add(b.time_end + 1 / fps);
      }
    }
    return [...out].filter((t) => t >= 0);
  }, [hostItem, fps]);
  const stillTimes = useMemo(
    () => [...new Set((stills ?? []).map((st) => st.timestamp))],
    [stills]
  );

  // ---- the two tag sections (video) ----
  // A tag is "timed" when any of its boxes carries a time; on a video that is
  // every box (a box without a time would be there for the whole film), so this
  // splits the sidebar into whole-item tags and tags that belong to a moment.
  const isTimed = (i: TagInstance) => (i.boxes ?? []).some((b) => b.time_start != null);
  // …and it is made of RANGES when any of those times carries no geometry: a
  // range is a stretch of the film, and gets a row of its own (see the sidebar's
  // per-range rows). A timed box WITH geometry is a moving subject's placement,
  // which still rides on the tag's own row.
  const hasRanges = (i: TagInstance) =>
    (i.boxes ?? []).some((b) => b.time_start != null && b.x == null);
  // …and it is live now when one of those times covers the current frame. Half
  // a frame either way, so a single-frame tag is listed while its frame shows.
  const liveNow = (i: TagInstance) => (i.boxes ?? []).some((b) =>
    b.time_start != null
    && entryContains({ start: b.time_start, end: b.time_end ?? null }, play.time, 0.5 / fps));
  // WHICH OF THE ITEM'S OWN TAGS COVER THIS FRAME — an untimed one covers the
  // whole film, a timed one only its own stretches. It is what an ENTAILED
  // tag's presence has to be judged by, since an implication carries no boxes
  // of its own to test.
  const liveNames = useMemo(() => {
    const out = new Set<string>();
    for (const i of hostItem?.tag_instances ?? []) {
      if (!isTimed(i) || liveNow(i)) out.add(i.name);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostItem, play.time, fps]);
  const impliedLive = useCallback(
    (via: string[]) => via.some((v) => liveNames.has(v)), [liveNames]);
  const tagsChanged = () => {
    qc.invalidateQueries({ queryKey: ["item", itemId] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    bumpEdits();
    // Re-derive the box set from the refreshed item.
    initedFor.current = null;
  };
  /** A list's own heading. The tab strip is icons only — with several tabs
   *  open, a column of unlabelled lists is a column nobody can read — so each
   *  section says what it is, exactly as the Tags one always has. */
  const sideTitle = (label: string, extra?: React.ReactNode) => (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
      <span style={{ fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text-bright)" }}>{label}</span>
      {extra}
    </div>
  );

  // ---- the sidebar's other four lists -------------------------------------
  //
  // The library sidebar's own sections, on the item that is ON SCREEN — the
  // still when one is open, since that is what a face or a caption would be
  // about. Their selection, and what removing a row means, come from the one
  // definition both windows share.
  const { data: allPlaces } = useQuery({
    queryKey: ["places"], queryFn: api.places, enabled: tabs.has("places") });
  const { data: allEvents } = useQuery({
    queryKey: ["events"], queryFn: api.events, enabled: tabs.has("events") });
  const { data: offers, refetch: refetchOffers } = useQuery({
    queryKey: ["item-suggestions", itemId],
    queryFn: () => api.itemSuggestions(itemId as number),
    enabled: itemId != null && (tabs.has("places") || tabs.has("events")),
  });
  const peopleChanged = () => {
    qc.invalidateQueries({ queryKey: ["item", itemId] });
    qc.invalidateQueries({ queryKey: ["subjects"] });
    qc.invalidateQueries({ queryKey: ["places"] });
    qc.invalidateQueries({ queryKey: ["events"] });
    qc.invalidateQueries({ queryKey: ["faces", itemId] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    void refetchOffers();
    bumpEdits();
  };
  const people = usePeopleSelection({
    itemId,
    detail: item ?? null,
    places: allPlaces,
    events: allEvents,
    // With several open the bar belongs to the first of the three in tab
    // order — one bar, and it has to name a list somebody can see.
    tab: tabs.has("subjects") ? "subjects"
      : tabs.has("places") ? "places" : tabs.has("events") ? "events" : null,
    onChanged: peopleChanged,
    removeTitle: t("Remove them from this item"),
    removeTitleGuessed: t("Remove them from this item, and remember the wrong guesses"),
  });
  const [barH, setBarH] = useState(SELECTION_BAR_H);
  const [reports, setReports] = useState<Record<string, SelectionReport | null>>({});
  const report = useCallback((id: string, r: SelectionReport | null) => {
    setReports((all) => (all[id] === r ? all : { ...all, [id]: r }));
  }, []);
  // The panel's OWN selection is not a report — a component cannot consume its
  // own provider — so it is simply preferred when it has anything. Captions
  // report; the tag list does too, and its rows are the box filter.
  // What the sidebar is pointing at: a picked tag ROW (matched on tag AND
  // group, since the same tag in two groups is two rows), or a picked subject
  // / place / event, which is a pick of that record's TAG. The two are one
  // question — "which of this picture's tags am I looking at" — so they share
  // the highlight rather than each inventing one.
  clearPeopleRef.current = people.clearAll;
  // The subject rows' selection, reachable from the once-registered pointer
  // handlers: the canvas outlines are the same entries, so picking a shape
  // picks its row (see `selOut` below).
  const subjectSelRef = useRef<string[]>([]);
  subjectSelRef.current = people.subjectSel.selected;
  const subjectSelSetRef = useRef<(next: string[]) => void>(() => {});
  subjectSelSetRef.current = people.subjectSel.set;
  /** Commit a drawn subject outline (file-frame geometry). With people rows
   *  picked it lands on THEM — a box straight onto each picked appearance,
   *  and a first appearance for somebody on the item through their tag alone
   *  — exactly the way a drawn tag box takes the selected tag rows. With
   *  nobody picked the shape waits under a naming field instead. */
  const commitSubjectOutline = (geom: {
    x: number; y: number; w: number; h: number;
    points?: [number, number][] }) => {
    const keys = people.subjectSel.selected;
    if (!keys.length) { setPendingOutline(geom); setOutlineName(""); return; }
    const file = activeFileRef.current;
    const payload = geom.points?.length
      ? { x: 0, y: 0, w: 0, h: 0, points: pointsToRef(geom.points, file) }
      : fileToRef(geom, file);
    void (async () => {
      for (const key of keys) {
        if (key.startsWith("a:")) {
          await api.setAppearanceBox(Number(key.slice(2)), payload);
        } else if (key.startsWith("s:") && itemId != null) {
          // On the item through the tag alone: give them an appearance to
          // carry the box.
          const sub = (item?.subjects ?? []).find(
            (r) => r.tag === key.slice(2));
          if (!sub) continue;
          const rows = await api.addAppearance(
            { item_id: itemId, subject_id: sub.id });
          const mine = rows.find((r) => r.id === sub.id);
          const ap = mine?.appearances[mine.appearances.length - 1];
          if (ap) await api.setAppearanceBox(ap.id, payload);
        }
      }
      void qc.invalidateQueries({ queryKey: ["item", itemId] });
      bumpEdits();
    })();
  };
  commitSubjectOutlineRef.current = commitSubjectOutline;
  /** Name a fresh outline: find or make the subject, put them in the picture
   *  where nothing carries the box yet, and draw it. An appearance WITHOUT a
   *  box takes it; with every one boxed the person is in the picture a
   *  second time, which is what a second outline of them says. */
  const nameOutline = async (text: string) => {
    const wanted = text.trim();
    if (!wanted) return;
    const geom = pendingOutline;
    setPendingOutline(null);
    setOutlineName("");
    if (!geom || itemId == null) return;
    let subject = (subjectRows ?? []).find(
      (r) => (r.display_name || r.tag).toLowerCase() === wanted.toLowerCase());
    if (!subject) {
      const made = await api.createSubject({ display_name: wanted });
      subject = made.find((r) => r.display_name === wanted)
        ?? made[made.length - 1];
      qc.invalidateQueries({ queryKey: ["subjects"] });
    }
    if (!subject) return;
    const sid = subject.id;
    const file = activeFileRef.current;
    const payload = geom.points?.length
      ? { x: 0, y: 0, w: 0, h: 0, points: pointsToRef(geom.points, file) }
      : fileToRef(geom, file);
    const mine = (item?.subjects ?? []).find((r) => r.id === sid);
    let ap = mine?.appearances.find((a) => !a.box);
    if (!ap) {
      const before = new Set((mine?.appearances ?? []).map((a) => a.id));
      const rows = await api.addAppearance(
        { item_id: itemId, subject_id: sid });
      const now = rows.find((r) => r.id === sid);
      ap = now?.appearances.find((a) => !before.has(a.id))
        ?? now?.appearances[now.appearances.length - 1];
    }
    if (ap) await api.setAppearanceBox(ap.id, payload);
    rememberSubject(subject.display_name || subject.tag);
    void qc.invalidateQueries({ queryKey: ["item", itemId] });
    bumpEdits();
  };
  // The reverse of `pickFace`'s clear: a subject / place / event row picked
  // in the sidebar puts the face crops down.
  useEffect(() => {
    if (people.selectedTags.size && faceSelRef.current.length) setFaceSel([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [people.selectedTags]);
  const boxFocused = (b: Box) => b.labels.some(
    (l) => tagSelSet.has(tagRowKey(l.group ?? null, l.tag))
      || people.selectedTags.has(l.tag));
  // The sidebar's people picks at APPEARANCE grain: the same person can be
  // in one picture twice, and lighting every outline of the TAG made picking
  // one entry ring another entry's shape.
  const selApps = useMemo(() => new Set(people.subjectSel.selected
    .filter((k) => k.startsWith("a:")).map((k) => Number(k.slice(2)))),
    [people.subjectSel.selected]);
  // EVERY outline on the canvas, one list for both kinds — a subject's box
  // (`app:<appearance>`) and a face's whole-figure outline (`face:<face>`) —
  // in the active file's frame, with the label, highlight and remove each
  // carries. The render, the click hit test and the drag machinery all read
  // this one derivation, so the three cannot disagree about what is there.
  const outlineGeos = useMemo(() => {
    if (!faceMode || onVideo) return [];
    type Geo = { key: string; label: string; hot: boolean;
                 x: number; y: number; w: number; h: number;
                 points?: [number, number][]; clear: () => void };
    const geos: Geo[] = [];
    for (const sub of item?.subjects ?? []) {
      for (const a of sub.appearances ?? []) {
        if (!a.box) continue;
        geos.push({
          key: `app:${a.id}`,
          label: sub.display_name || sub.tag,
          hot: selApps.has(a.id),
          ...refToFile({ x: a.box[0], y: a.box[1],
                         w: a.box[2], h: a.box[3] }, activeFile),
          points: a.points?.length
            ? (quadToFile(a.points, activeFile) as [number, number][])
            : undefined,
          clear: () => {
            void api.clearAppearanceBox(a.id).then(() => {
              void qc.invalidateQueries({ queryKey: ["item", itemId] });
            });
          },
        });
      }
    }
    for (const fc of faces ?? []) {
      if (fc.dismissed || !fc.outline) continue;
      geos.push({
        key: `face:${fc.id}`,
        // The face's first claim names it — the label chip's rule — and a
        // nameless face's outline still says what it is.
        label: fc.subjects[0]?.name || fc.subjects[0]?.tag || t("Face"),
        hot: faceSel.includes(fc.id)
          || (item?.subjects ?? []).some((s2) => s2.appearances.some(
            (a2) => a2.face_id === fc.id && selApps.has(a2.id))),
        ...refToFile({ x: fc.outline[0], y: fc.outline[1],
                       w: fc.outline[2], h: fc.outline[3] }, activeFile),
        points: fc.outline_points?.length
          ? (quadToFile(fc.outline_points, activeFile) as [number, number][])
          : undefined,
        clear: () => {
          void api.clearFaceOutline(fc.id).then(() => {
            void qc.invalidateQueries({ queryKey: ["item", itemId] });
            void qc.invalidateQueries({ queryKey: ["faces", itemId] });
          });
        },
      });
    }
    return geos;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [faceMode, onVideo, item, faces, activeFile, selApps,
      faceSel, itemId]);
  const outlineGeosRef = useRef(outlineGeos);
  outlineGeosRef.current = outlineGeos;
  // The canvas's SELECTED outline — DERIVED, one selection per kind: a
  // subject box from the sidebar row selection (exactly one entry picked,
  // and it has a shape), a face's figure outline from the face selection
  // (exactly one face picked, and it has one). Derived is what makes
  // "selecting the shape selects the sidebar entry, and vice versa" a fact
  // rather than a sync. Only in outline mode: in face mode nothing at this
  // layer is selectable.
  const selOut = (() => {
    if (subjectDraw !== "outline" || !faceMode) return null;
    const sel = people.subjectSel.selected;
    if (sel.length === 1 && sel[0].startsWith("a:")) {
      const key = `app:${sel[0].slice(2)}`;
      if (outlineGeos.some((g) => g.key === key)) return key;
    }
    if (faceSel.length === 1) {
      const key = `face:${faceSel[0]}`;
      if (outlineGeos.some((g) => g.key === key)) return key;
    }
    return null;
  })();
  const selOutRef = useRef<string | null>(null);
  selOutRef.current = selOut;
  const anyFocus = tagSel.length > 0 || people.selectedTags.size > 0;
  // A box renders "full" when nothing is focused, or when it is what is.
  const boxVisible = (b: Box) => !anyFocus || boxFocused(b);
  // The Subjects tab is about FACES, and its own layer of ovals goes over the
  // same picture — tag rectangles underneath turn that into two overlapping
  // grids of outlines. So they stand down while it is the list you are on
  // (unless the tag list is open beside it, where you asked for both).
  // EXCEPT a box the sidebar is pointing at: picking somebody whose tag
  // carries a box should show you that box, which is the whole use of picking
  // them, so it comes back for as long as the pick lasts.
  // …and the Text tab hides them harder: a tag box and a text box are both
  // RECTANGLES, so two layers of them over one picture are indistinguishable
  // where an oval never is.
  const hideTagBoxes = (tabs.has("subjects") || tabs.has("text"))
    && !tabs.has("tags");
  const boxDrawn = (b: Box) => !hideTagBoxes || boxFocused(b);
  // What a click and the rubber band are allowed to pick: only what is drawn.
  boxDrawnRef.current = boxDrawn;

  // Shown whenever a selectable list is on screen, rows or none — the same
  // rule the library sidebar's bar follows. The people tabs win while they
  // have rows; then a section with something picked, then one that merely has
  // rows; a list with NO rows only ever owns the bar when nothing else on
  // screen has any.
  const rawBar: SelectionReport | null = (() => {
    // In tab order. "links" and "linked-by" are two reports because both
    // directions are on the one tab and the second would otherwise replace
    // the first.
    const rs = ["tags", "captions", "instructions", "links", "linked-by",
                "text"]
      .map((id) => reports[id])
      .filter(Boolean) as SelectionReport[];
    return (people.report?.total ? people.report : null)
      ?? rs.find((r) => r.count)
      ?? rs.find((r) => r.total)
      ?? people.report
      ?? rs[0]
      ?? null;
  })();
  // The way back from a removal made in this sidebar — the same offer the
  // library window's panel makes, because these are the same lists removing
  // the same things. It was missing here for no reason but that the sections
  // were rendered with no provider above them, which made `useUndoRun` a
  // passthrough: the removal happened and nothing was offered.
  //
  // Scoped to the open tabs AND the item, like the panel's: an offer that
  // outlived either would be a button aimed at rows nobody can see.
  const undoScope = `${[...tabs].sort().join(",")}|${itemId ?? ""}`;
  const undoBar = useUndoBar(undoScope, () => {
    // Only what is local to THIS window — the hook refreshes everything a
    // revert can touch (see `bumpReverted`), which is where this list's
    // missing `relationships` used to leave an undone unlink invisible.
    //
    // A reverted tag removal puts boxes back, so the local box set has to be
    // rebuilt from the item rather than kept.
    initedFor.current = null;
    void refetchOffers();
  });
  const bar: SelectionReport | null = rawBar && {
    ...rawBar,
    onRemove: () => void undoBar.run(
      `${t(rawBar.removeLabel ?? "Removed")} ${rawBar.count}`,
      async () => { await rawBar.onRemove(); }),
  };

  // Adding a tag in the playhead section tags the current range/frame: the tag
  // itself, then a box with a time but no geometry (the "tag this range" of the
  // old video editor).
  const addTimedTag = async (name: string, gid: number | null, negative = false) => {
    if (itemId == null) return;
    await chain.current;
    await api.addTagToGroup(itemId, name, gid, negative);
    const t = newBoxTime();
    // The range carries the sign too: a film tag's sign is derived from its
    // ranges (the finer statement), so a positive first range would flip a
    // `!name` straight back.
    await api.addTagBox(
      itemId, name,
      { x: null, y: null, w: null, h: null, time_start: t.start ?? play.nowTime(),
        time_end: t.end, negative },
      undefined, gid,
    );
  };

  // ---- the marked range, applied to the selected tags ----
  // What the selected rows come to: one entry per (tag instance, sign), since a
  // row is either a whole tag or ONE of its ranges, and two ranges of the same
  // tag with the same sign are one target. A tag row with no range means the
  // tag itself — the marked stretch would be its first, so it is positive.
  const rangeTargets = useMemo(() => {
    const out: { inst: TagInstance; negative: boolean; viaRow?: boolean }[] = [];
    for (const inst of hostItem?.tag_instances ?? []) {
      const gid = inst.group_id ?? null;
      for (const negative of [false, true]) {
        const hit = timeSel.some((k) =>
          k === tagRowKey(gid, inst.name, null) ? !negative
            : (inst.boxes ?? []).some((b) =>
                b.id != null && b.x == null && b.time_start != null
                && !!b.negative === negative
                && k === tagRowKey(gid, inst.name, b.id)));
        if (hit) out.push({ inst, negative, viaRow: true });
      }
    }
    // A SUBJECT, a PLACE and an EVENT are each extra data on a TAG, so picking
    // one in the sidebar is picking that tag — and a stretch granted to the
    // tag is granted to whoever it names. Without this the two lists disagreed
    // about what they were: selecting a person lit up her boxes on the picture
    // but left these buttons dead, so timing somebody meant finding her tag in
    // the tag list and picking it there instead.
    //
    // The target is the tag ITSELF, positive: these rows carry no range of
    // their own (a row here is the person, not the stretch), so the marked
    // range is one they ARE in. Deduped by NAME, since the server keeps
    // ranges from overlapping per tag rather than per placement — two
    // placements of one tag as two targets would have them trimming each
    // other.
    for (const tag of people.selectedTags) {
      if (out.some((o) => o.inst.name === tag)) continue;
      const inst = (hostItem?.tag_instances ?? []).find((i) => i.name === tag);
      if (inst) out.push({ inst, negative: false });
    }
    return out;
  }, [hostItem, timeSel, people.selectedTags]);
  const selectedTagNames = useMemo(
    () => Array.from(new Set(rangeTargets.map((t) => t.inst.name))),
    [rangeTargets]
  );
  const markedRange = inPoint != null && outPoint != null && outPoint > inPoint
    ? { start: Math.min(inPoint, outPoint), end: Math.max(inPoint, outPoint) }
    : null;
  const [rangeBusy, setRangeBusy] = useState(false);
  /**
   * Add the marked range to what each selected tag covers, or cut it out of it.
   * What a tag covers WITH ONE SIGN is the union of its ranges of that sign, so
   * this is plain interval arithmetic on that set — then the result is written
   * back as the boxes it needs: a stretch that came through unchanged keeps its
   * box (and its id), what is left over is deleted, and what is new is created.
   * Ranges of the OPPOSITE sign are the server's business: it trims whatever
   * the new one overlaps, since a tag cannot be both present and absent at one
   * moment (see tags.py `_make_room`).
   */
  const applyRange = async (op: "add" | "subtract") => {
    if (hostId == null || !hostItem || markedRange == null) return;
    const eps = 0.5 / fps; // a gap under half a frame is no gap
    // A row's identity is its BOX id, and this rewrites the boxes — so the
    // selection would be pointing at rows that no longer exist. Remember which
    // tags were selected and re-select their rows once the item comes back.
    // Only the ones picked AS ROWS: a target that came from a person, a place
    // or an event is selected in its own list, and putting its tag rows into
    // the tag list's selection as well would be this button quietly picking
    // things nobody pointed at.
    const targets = rangeTargets.filter((r) => r.viaRow).map(({ inst }) =>
      ({ gid: inst.group_id ?? null, name: inst.name }));
    setRangeBusy(true);
    try {
      await chain.current;
      for (const { inst, negative } of rangeTargets) {
        // Only the film's own time-only boxes of this sign. A box with geometry
        // belongs to a still or a moving subject; a range edit must not touch it.
        const timed = (inst.boxes ?? []).filter(
          (b) => b.time_start != null && b.x == null && !!b.negative === negative);
        const current = timed.map((b) => ({ start: b.time_start as number, end: b.time_end }));
        const next = op === "add"
          ? addSpan(current, markedRange, eps)
          : subtractSpan(current, markedRange, eps);
        const kept = new Set<number>();
        const missing: { start: number; end: number | null }[] = [];
        for (const sp of next) {
          const same = timed.find((b) => b.id != null && !kept.has(b.id)
            && Math.abs((b.time_start as number) - sp.start) < 1e-6
            && Math.abs((b.time_end ?? (b.time_start as number)) - (sp.end ?? sp.start)) < 1e-6);
          if (same?.id != null) kept.add(same.id);
          else missing.push(sp);
        }
        for (const b of timed) {
          if (b.id != null && !kept.has(b.id)) await api.deleteTagBox(b.id);
        }
        for (const sp of missing) {
          await api.addTagBox(
            hostId, inst.name,
            { x: null, y: null, w: null, h: null, time_start: sp.start,
              time_end: sp.end, negative },
            undefined, inst.group_id ?? null,
          );
        }
        // Subtracting a tag's LAST stretch removes the tag: a timed tag with no
        // times left would read as "applies to the whole film", the opposite of
        // what was just asked for.
        const left = (inst.boxes ?? []).filter(
          (b) => !timed.some((t) => t.id === b.id)).length + next.length;
        if (op === "subtract" && timed.length > 0 && left === 0) {
          if (inst.placement_id != null) await api.deleteTagPlacement(inst.placement_id);
          else await api.unassignItemTag(hostId, inst.name);
        }
      }
      await qc.invalidateQueries({ queryKey: ["item", hostId] });
      tagsChanged();
      // Re-select the same TAGS, whatever boxes they are made of now.
      const fresh = qc.getQueryData<ItemDetail>(["item", hostId]);
      if (fresh) {
        const keys: string[] = [];
        for (const inst of fresh.tag_instances ?? []) {
          const gid = inst.group_id ?? null;
          if (!targets.some((t) => t.gid === gid && t.name === inst.name)) continue;
          const spans = (inst.boxes ?? []).filter(
            (b) => b.id != null && b.x == null && b.time_start != null);
          if (spans.length === 0) keys.push(tagRowKey(gid, inst.name, null));
          else for (const b of spans) keys.push(tagRowKey(gid, inst.name, b.id));
        }
        setTimeSel(keys);
      }
      // The range STAYS marked: the next thing you do with it is usually the
      // same range on another tag, or the opposite operation after a misclick.
    } finally {
      setRangeBusy(false);
    }
  };

  // The film's OWN tags are timed, never boxed: whole-item, a range, or a
  // single frame. Read from the host, since the edited item may be a snapshot
  // of it. Each stretch carries the SIDEBAR ROW KEY it is, because the block on
  // the timeline and the row in the list are the same stretch and picking
  // either has to pick both.
  const timedRanges: TagRangeBlock[] = useMemo(
    () => (!isVideo || !hostItem ? [] : (hostItem.tag_instances ?? []).flatMap((t) =>
      (t.boxes ?? [])
        .filter((b) => b.id != null && b.time_start != null && b.x == null)
        .map((b) => ({
          name: t.name, id: b.id as number,
          key: tagRowKey(t.group_id ?? null, t.name, b.id as number),
          start: b.time_start as number,
          end: b.time_end ?? null, negative: !!b.negative,
        })))),
    [isVideo, hostItem]);
  // Reading order, for a shift-extend on the timeline: track by track (the
  // tracks are sorted by name), left to right within each.
  timeOrder.current = useMemo(
    () => [...timedRanges]
      .sort((a, b) => a.name.localeCompare(b.name) || a.start - b.start)
      .map((r) => r.key),
    [timedRanges]);
  // A track's edits: the sign is the stretch's own, and dragging an edge moves
  // it (the server trims whatever of the same tag it now overlaps).
  const toggleRangeSign = useCallback(async (id: number) => {
    const r = timedRanges.find((x) => x.id === id);
    if (!r) return;
    await chain.current;
    await api.updateTagBox(id, { negative: !r.negative });
    qc.invalidateQueries({ queryKey: ["item", hostId] });
    tagsChanged();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timedRanges, hostId]);
  const commitRange = useCallback(async (id: number, start: number, end: number | null) => {
    await chain.current;
    await api.updateTagBox(id, { timeStart: start, timeEnd: end ?? undefined });
    // Awaited, so the lane can hold its preview until the stored geometry has
    // actually caught up instead of snapping back for the length of the trip.
    await qc.invalidateQueries({ queryKey: ["item", hostId] });
    tagsChanged();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostId]);

  // A tick per frame somebody kept, along the timeline's own scale. Seek only:
  // the tick says a still was taken HERE, so it takes you to the frame;
  // opening the picture is the stills list's own double-click, where the row
  // you are opening is the one you can see.
  const stillMarks = useMemo(
    () => (!isVideo ? [] : (stills ?? []).map((st) => ({
      key: `${st.item_id}:${st.timestamp}`, name: st.name,
      timestamp: st.timestamp }))),
    [isVideo, stills]);


  // Gate on the HOST, so the <video> is never unmounted while a detail is in
  // flight — that would throw away the playhead the stills list is keyed on
  // (and with it the frame you were working at).
  if (hostId == null || !hostItem) {
    return <div style={{ position: "fixed", inset: 0, background: "var(--bg)" }} />;
  }

  const renderBox = (b: Box) => liveBoxes[b.cid] ?? b;

  const labelInput: React.CSSProperties = {
    width: 90, height: 16, padding: "0 3px", border: "none", borderRadius: 3,
    fontFamily: "var(--mono)", fontSize: "var(--fs-1)", outline: "none",
  };

  return (
    <div style={{ position: "fixed", inset: 0, display: "flex", flexDirection: "column", background: "var(--bg)" }}>
      {/* One tab per item the window was opened on — the same strip the image
          editor has. It replaced previous/next arrows, which walked the whole
          grid: the two pages you meant to compare could be forty apart, and
          nothing said which items the window held. */}
      <WindowTabs
        ids={editorTabs}
        active={editorItemId}
        onSelect={(id) => { initedFor.current = null; setEditorItem(id); }}
        onClose={(id) => (editorTabs.length <= 1 ? closeItemWindow() : closeEditorTab(id))}
        suffix={filmTabSuffix(play, editorItemId)}
        t={t}
      />
      {/* Top bar. `--panel` is the ACTIVE TAB's background, which is the whole
          point: the tab is supposed to merge into the bar below it, and with
          the bar left on the window's `--bg` the selected tab was a lighter
          rectangle sitting on top of a darker header rather than part of it.
          The image editor's bar has always been `--panel`; this is the same
          bar. */}
      <div style={{ flex: "0 0 auto", height: 48, display: "flex", alignItems: "center", gap: 8, padding: "0 12px", background: "var(--panel)", borderBottom: "1px solid var(--border)" }}>
        {/* Undo/redo has left the header and floats over the picture
            (`CanvasBars`), where the other two halves of the window keep it:
            it acts on the ANNOTATION, not on the window, and the header is
            for what the window is and how to leave it. */}
        {/* The window's two halves, BEFORE the name. It sat at the far right,
            past the theme button, which put the control that changes
            everything below the header at the end of a row of small ones —
            and left the header opening with actions on a mode it had not yet
            named. Switching INTO edit needs no guard: an annotation is
            applied as it is made, so there is never anything unsaved here to
            lose. */}
        {itemId != null && (
          <>
            <ModeSwitch
              t={t}
              mode="annotate"
              onPick={(m) => { if (itemId != null) setEditorMode(itemId, m); }}
              editIcon={item?.kind === "video" ? "movie_edit" : "edit"}
              disabled={!(item?.kind === "image" || item?.kind === "video")}
            />
            <Divider />
          </>
        )}
        {/* The name and the file chip. `HeaderActions` stays with an empty
            `actions` because it is what measures the name against the width
            the fixed sides leave over — and with none it draws no ⋯, which is
            the point: the menu held one entry, Show in library, and closing
            the window already goes there. */}
        <HeaderActions t={t} alwaysFolded actions={[]}>
          {/* The name takes whatever the header has left, rather than a fixed
              220 px that truncated "chapter-04-page-12.png" halfway; the
              actions beside it fold into a ⋯ before it starts to truncate at
              all (see `HeaderActions`). What it measures goes UNDERNEATH — one
              header, one shape, and the numbers stop taking width from the
              name (see `ItemTitle`). */}
          <ItemTitle
            name={item?.name ?? hostItem.name}
            subtitle={headerSubtitle}
          />
          {/* The image editor's file chip, and the same menu behind it: which of
              the item's files this is, and a way to any of the others. The name
              no longer needs an icon in front of it or the word "Annotate"
              after it — the window is titled that, and a picture with tools
              around it is not something anybody mistakes for a preview.

              PORTALLED (`FileChip`): the header's lead clips its overflow so
              the name can ellipsise, and an absolutely-positioned menu inside
              it was clipped to the chip — the click toggled and nothing
              appeared. */}
          {item && (
            <FileChip
              files={item.files}
              currentId={activeFile?.id ?? null}
              onPick={(id) => setFileOverride(id)}
              t={t}
            />
          )}
        </HeaderActions>

        {/* Window theme (zoom lives bottom-right on the canvas), then the
            window's own ✕. That cross used to be argued against, because the
            tab strip was always shown and every tab carried one — but the
            strip is hidden for a single tab now, so this is the only visible
            way out of a one-item window. No divider before it: it ends the
            row rather than starting a group. */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <ThemeMenu t={t} value={winTheme} onChange={setWinTheme} />
          <WindowCloseBtn t={t} onClose={closeItemWindow} />
        </div>
      </div>

      {/* Body: canvas (+ video transport) + right sidebar */}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>

      {/* Left column: the canvas, and below it the video transport (so the
          transport never overlaps the on-canvas zoom controls). */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0 }}>

      {/* Canvas */}
      <div
        ref={viewportRef}
        onMouseDown={onBackgroundDown}
        onMouseMove={(e) => {
          // Only while a polygon is being laid down — the rubber line to the
          // pointer is the one thing here that needs per-move renders.
          if (polyDraftRef.current) setPolyHover(frac(e.clientX, e.clientY));
        }}
        onDoubleClick={() => {
          // A double-click finishes the polygon: its second press appended a
          // duplicate corner, which is taken back before closing.
          const cur = polyDraftRef.current;
          if (cur && cur.length > 3) {
            const trimmed = cur.slice(0, -1);
            polyDraftRef.current = trimmed;
            setPolyDraft(trimmed);
            finishPolyRef.current();
          }
        }}
        style={{
          flex: 1, minHeight: 0, position: "relative", overflow: "hidden",
          display: "flex", alignItems: "center", justifyContent: "center",
          background: "var(--bg-deep)",
          cursor: spaceHeld ? "grab" : "crosshair",
        }}
      >
        {/* What you do TO the annotation, floating over the picture's top-left
            corner — the same row and the same pill the other two halves of the
            window put their undo/redo and their menus in. There is nothing to
            put beside it here: an annotation is applied as it is made, so this
            window has no menu of transformations to offer. */}
        <CanvasBarRow>
          <CanvasBar>
            <UndoRedoButtons
              canUndo={undoStack.current.length > 0}
              canRedo={redoStack.current.length > 0}
              onUndo={undo}
              onRedo={redo}
              t={t}
            />
          </CanvasBar>
          {/* Which SHAPE a draw makes — its own pill, per the one-pill-per-
              group rule. Only while a tab with shapes to draw is open (Tags
              or Subjects): a film's tags carry times, and faces and text
              boxes keep their own shapes either way. */}
          {/* WHAT a draw on the Subjects tab makes — a face, or a subject's
              whole-figure outline. Its own pill, before the shape: what you
              draw, then which shape it takes. */}
          {faceMode && (
            <CanvasBar>
              {([["face", "face", t("Draw faces")],
                 ["outline", "accessibility_new",
                  t("Draw outlines — a box or polygon around a whole figure")],
                ] as const
              ).map(([mode, icon, title]) => (
                <span
                  key={mode}
                  onClick={() => { setSubjectDraw(mode); setPolyDraft(null);
                    setPolyHover(null); setPendingOutline(null);
                    // Each mode's layer is the selectable one, so the other
                    // layer's selection goes down with the switch.
                    if (mode === "outline") setFaceSel([]); }}
                  title={title}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "center",
                    width: 28, height: 24, borderRadius: "var(--r-2)", cursor: "pointer",
                    background: subjectDraw === mode ? "var(--accent-dim)" : "transparent",
                    color: subjectDraw === mode ? "var(--accent)" : "var(--muted)",
                  }}
                >
                  <Icon name={icon} size={16} />
                </span>
              ))}
            </CanvasBar>
          )}
          {shapeTabs && (tabs.has("tags")
            || (faceMode && subjectDraw === "outline")) && (
            <CanvasBar>
              {([["box", "crop_square", t("Draw boxes")],
                 ["octagon", "pentagon", t("Draw octagons — dragged out like a box")],
                 ["poly", "polyline", t("Draw polygons — click corner by corner")]] as const
              ).map(([mode, icon, title]) => (
                <span
                  key={mode}
                  onClick={() => { setDrawShape(mode); setPolyDraft(null); setPolyHover(null); }}
                  title={title}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "center",
                    width: 28, height: 24, borderRadius: "var(--r-2)", cursor: "pointer",
                    background: drawShape === mode ? "var(--accent-dim)" : "transparent",
                    color: drawShape === mode ? "var(--accent)" : "var(--muted)",
                  }}
                >
                  <Icon name={icon} size={16} />
                </span>
              ))}
            </CanvasBar>
          )}
        </CanvasBarRow>
        <div
          ref={frameRef}
          style={{
            position: "relative", width: frameW, height: frameH,
            // `origin` shifts it from the viewport's centre to the SAFE area's:
            // flexbox centres it in the whole canvas, and the fit was computed
            // against what the floating bars leave over.
            transform: `translate(${pan.x + origin.x}px, ${pan.y + origin.y}px)`,
            flex: "0 0 auto",
            ...checkerCss,
          }}
        >
          {activeFile && !onVideo && (
            <img
              src={api.fileUrl(activeFile.id)}
              alt=""
              draggable={false}
              style={{ display: "block", width: "100%", height: "100%", userSelect: "none" }}
            />
          )}
          {/* Rendered only while the tab being annotated IS a film — so this
              element goes away whenever you switch to an image tab, and two
              film tabs SHARE it with the `src` swapped under them. Neither
              keeps a playhead, which is why `useVideoPlayback` remembers the
              position per source and puts it back: it used to come back at
              the beginning. (The comment here used to claim the film stayed
              mounted behind an open still. That was true when a still was
              edited inside the film's own window; a still is its own tab
              now.) */}
          {hostFile && isVideo && (
            <video
              ref={play.videoRef}
              src={api.fileUrl(hostFile.id)}
              draggable={false}
              // The box overlay handles pointer drawing; clicking the frame
              // toggles play only when NOT drawing (Space-pan / edit modes pass
              // through to the background handler).
              style={{ display: onVideo ? "block" : "none", width: "100%", height: "100%", userSelect: "none", background: "#000", pointerEvents: "none" }}
            >
              {subTracks.map((tr) => (
                <track key={tr.index} kind="subtitles"
                  src={api.subtitleUrl(hostFile.id, tr.index)}
                  srcLang={tr.language ?? undefined}
                  label={subtitleLabel(tr)} />
              ))}
            </video>
          )}
          {/* Existing boxes */}
          {(() => {
            // Tags carried by the currently-selected boxes — used to tint the
            // other boxes that share a tag with the selection.
            const selSet = new Set(selectedCids);
            const selTags = new Set<string>();
            for (const rb of boxes) if (selSet.has(rb.cid)) for (const l of rb.labels) selTags.add(l.tag);
            return boxes.filter(boxDrawn).map((raw) => {
            const b = renderBox(raw);
            // "Hot": carries a tag row that is selected in the sidebar but is
            // not itself the selected box — the boxes a new draw would join.
            const hot = anyFocus && boxFocused(b);
            const isSel = selSet.has(b.cid);
            // A box's color is its tag's deterministic color (1.2). When several
            // tags share the box, prefer one that's in the current selection so
            // the box tints toward what you're inspecting.
            const primaryTag = b.labels.find((l) => selTags.has(l.tag))?.tag
              ?? b.labels[0]?.tag ?? "";
            const tc = primaryTag ? tagColor(primaryTag)
              : { stroke: "var(--accent)", fill: "var(--accent-dim)", text: "var(--on-accent)" };
            // Ghosted: not in the sidebar's visibility focus — drawn as a faint
            // thin outline for context only, not interactive (1.3).
            const ghost = !boxVisible(b);
            // A box glows while its tag's activity lane is being hovered (T14).
            const laneHovered = hoverTag != null && b.labels.some((l) => l.tag === hoverTag);
            // Selection/hot is a border-weight + ring treatment layered on the
            // tag color, never a separate hue (1.2).
            const borderW = isSel || hot || laneHovered ? 3 : 2;
            // The label is shown only for the selected box (plus while it's being
            // renamed or having a tag added) — other boxes read by color (1.4).
            const showLabel = isSel || renaming?.cid === b.cid || addingTo === b.cid;
            // A SELECTED box takes the pointer so it can be dragged; an
            // unselected one is draw-through, which is what lets one gesture
            // both make a box and pick one. Ghosts are never interactive.
            const canMove = !spaceHeld && isSel && !ghost;
            // The label bar normally sits just above the box, but the canvas
            // clips to its bounds — so for a box near the top edge that bar
            // (with the ×, rename and + controls) would be cut off and become
            // unclickable. Flip it below the box in that case.
            const boxTopVp = (vp.h - frameH) / 2 + origin.y + pan.y + b.y * frameH;
            const labelBelow = boxTopVp < 26;
            return (
              <React.Fragment key={b.cid}>
              <div
                onMouseDown={(e) => canMove ? startMove(e, b) : undefined}
                style={{
                  position: "absolute", left: `${b.x * 100}%`, top: `${b.y * 100}%`,
                  width: `${b.w * 100}%`, height: `${b.h * 100}%`,
                  // A POLYGON box draws its shape in the SVG below; the div is
                  // its bounding box, visible only as the dashed transform
                  // frame while it is selected in box mode.
                  border: b.points
                    ? (isSel && !polyUI && !spaceHeld
                        ? `1px dashed ${tc.stroke}` : "none")
                    : ghost ? `1px solid ${tc.stroke}` : `${borderW}px solid ${tc.stroke}`,
                  background: b.points ? "transparent"
                    : ghost ? "transparent" : tc.fill,
                  opacity: ghost ? 0.3 : 1,
                  // The selected box gets a bright inner ring (layered on the tag
                  // color, not a separate hue); the hot box a lighter one; a
                  // lane-hovered box an outer glow in its own colour. A polygon
                  // says the same things on its own stroke instead.
                  boxShadow: b.points ? undefined
                    : laneHovered ? `0 0 0 2px ${tc.stroke}, 0 0 10px 2px ${tc.stroke}`
                    : isSel ? "inset 0 0 0 1.5px var(--on-scrim)"
                    : hot ? "inset 0 0 0 1.5px var(--on-scrim-3)" : undefined,
                  // Ghosts are context only.
                  pointerEvents: ghost ? "none" : undefined,
                  // Lift the selected box (and its resize handles) above other
                  // boxes so a box covered by another stays visible and grabbable
                  // once selected. Kept below the labels' z-index (5/6) so tag
                  // labels still composite on top.
                  zIndex: isSel ? 4 : undefined,
                  borderRadius: 2, cursor: spaceHeld ? "grab" : isSel ? "move" : "crosshair",
                }}
              >
                {b.points && (
                  <PolyShape
                    b={b} pts={b.points} stroke={tc.stroke}
                    fill={ghost ? "transparent" : tc.fill}
                    width={ghost ? 1 : borderW}
                    ring={!ghost && (isSel || hot)}
                  />
                )}
                {/* Transform handles — the selected box only, which is also
                    the only one that takes the pointer at all. In box (and
                    octagon) mode they are the bounding box's, polygon or not:
                    the transform scales the shape. In poly mode the shape's
                    own corners take their place.

                    The four EDGE handles are here beside the corners because
                    a corner changes two dimensions at once, and most of what
                    a box needs is one of them — a subject a little too far
                    left is a west edge, not a north-west corner and a
                    correction to the height nobody asked for. Their hit area
                    is the same 10px square the corners have, centred on the
                    edge rather than sized to it: an edge-long grab strip
                    would swallow the corners on a small box. */}
                {isSel && !spaceHeld && !polyUI
                  && ["nw", "n", "ne", "e", "se", "s", "sw", "w"].map((corner) => (
                  <span
                    key={corner}
                    onMouseDown={(e) => startResize(e, b, corner)}
                    style={{
                      position: "absolute", width: 10, height: 10, background: tc.stroke,
                      border: "1px solid var(--scrim-2)",
                      borderRadius: corner.length === 1 ? "50%" : 2,
                      left: corner.includes("w") ? -5
                        : corner === "n" || corner === "s" ? "calc(50% - 5px)"
                        : undefined,
                      right: corner.includes("e") ? -5 : undefined,
                      top: corner.includes("n") ? -5
                        : corner === "e" || corner === "w" ? "calc(50% - 5px)"
                        : undefined,
                      bottom: corner.includes("s") ? -5 : undefined,
                      cursor: corner === "n" || corner === "s" ? "ns-resize"
                        : corner === "e" || corner === "w" ? "ew-resize"
                        : `${corner}-resize`,
                    }}
                  />
                ))}
                {/* And the ROTATION handle, on a short stem above the top
                    edge — outside the shape, because every point inside it
                    already means something else. It is offered in box and
                    octagon mode only: in poly mode the corners are what the
                    handles are for, and a shape being edited corner by corner
                    is not one being turned as a whole. */}
                {isSel && !spaceHeld && !polyUI && (
                  <>
                    <span style={{
                      position: "absolute", left: "calc(50% - 0.5px)", top: -22,
                      width: 1, height: 17, background: tc.stroke,
                      pointerEvents: "none", opacity: 0.8 }} />
                    <span
                      onMouseDown={(e) => startRotate(e, b, frameW / (frameH || 1))}
                      title={t("Drag to turn · hold Shift for 15° steps")}
                      style={{
                        position: "absolute", left: "calc(50% - 11px)", top: -33,
                        width: 22, height: 22, borderRadius: "50%",
                        display: "flex", alignItems: "center",
                        justifyContent: "center", cursor: "grab",
                        background: tc.stroke, color: tc.text,
                        border: "1px solid var(--scrim-2)",
                      }}
                    >
                      <Icon name="rotate_right" size={13} />
                    </span>
                  </>
                )}
                {/* Poly mode: the shape's corners, draggable one by one — a
                    plain rectangle's four count too (a rect is a polygon with
                    four edges), and dragging one is what turns it into a
                    polygon. The small dot on each edge's middle inserts a
                    corner there and drags it in the same gesture. */}
                {isSel && !spaceHeld && polyUI && (() => {
                  const pts = b.points ?? rectPts(b);
                  const vSel = selVertex?.kind === "box"
                    && selVertex.cid === raw.cid ? selVertex.idx : -1;
                  return (
                    <>
                      {pts.map((pt, i) => {
                        const on = i === vSel;
                        const r2 = on ? 6 : 5;
                        // WHAT IS GRABBED IS BIGGER THAN WHAT IS DRAWN. A
                        // 10px dot is the right size to look at and the wrong
                        // size to hit — a corner is aimed at with a mouse over
                        // a picture, often zoomed out, and a miss used to grab
                        // the shape and MOVE it. The hit square is
                        // `VERT_GRAB`, transparent, with the dot centred
                        // inside it; `dropping the visible size` instead would
                        // have made the shape's own corners a row of blobs.
                        return (
                        <span
                          key={`v${i}`}
                          onMouseDown={(e) => startVertex(e, raw, pts, i)}
                          onDoubleClick={(e) => {
                            e.stopPropagation();
                            removeVertex(raw, pts, i);
                          }}
                          title={pts.length > 3 ? t("Drag to move · click picks · Delete removes this corner") : t("Drag to move this corner")}
                          style={{
                            position: "absolute",
                            width: VERT_GRAB, height: VERT_GRAB,
                            left: `calc(${((pt[0] - b.x) / (b.w || 1)) * 100}% - ${VERT_GRAB / 2}px)`,
                            top: `calc(${((pt[1] - b.y) / (b.h || 1)) * 100}% - ${VERT_GRAB / 2}px)`,
                            display: "flex", alignItems: "center",
                            justifyContent: "center",
                            background: "transparent",
                            cursor: "move", zIndex: 6,
                          }}
                        >
                          <span style={{
                            width: r2 * 2, height: r2 * 2,
                            background: on ? "var(--on-scrim)" : tc.stroke,
                            border: on ? `2px solid ${tc.stroke}`
                                       : "1.5px solid var(--on-scrim)",
                            boxShadow: "0 0 0 1px var(--scrim-2)",
                            borderRadius: "50%",
                          }} />
                        </span>
                        );
                      })}
                      {pts.map((pt, i) => {
                        const nx2 = pts[(i + 1) % pts.length];
                        const mx = (pt[0] + nx2[0]) / 2, my = (pt[1] + nx2[1]) / 2;
                        return (
                          <span
                            key={`m${i}`}
                            onMouseDown={(e) => insertVertex(e, raw, pts, i, [mx, my])}
                            title={t("Add a corner here")}
                            style={{
                              position: "absolute", width: 7, height: 7,
                              left: `calc(${((mx - b.x) / (b.w || 1)) * 100}% - 3.5px)`,
                              top: `calc(${((my - b.y) / (b.h || 1)) * 100}% - 3.5px)`,
                              background: "var(--on-scrim)",
                              border: `1.5px solid ${tc.stroke}`,
                              borderRadius: "50%", cursor: "copy", zIndex: 5,
                            }}
                          />
                        );
                      })}
                    </>
                  );
                })()}
              </div>
              {/* Label bar — one chip per tag (double-click to rename, click the
                  group pill to move it to another group, × to remove), plus a +
                  to add another tag to this box. Flipped below the box when it
                  would be clipped by the top canvas edge. Rendered as a
                  canvas-level SIBLING of the box: the selected box's own zIndex
                  (needed to grab it above overlapping boxes) forms a stacking
                  context that would trap its label underneath other boxes'
                  labels. As a sibling the z-order is free: the SELECTED box's
                  label always composites above every other label and box, then
                  the focused-tag labels, then the rest — while the box
                  rectangles keep their own (lower) stacking so overlapping
                  boxes stay selectable. */}
              {showLabel && (
              <div
                onMouseDown={(e) => e.stopPropagation()}
                style={{ position: "absolute", zIndex: isSel ? 7 : hot ? 6 : 5, left: `calc(${b.x * 100}% - 2px)`, top: labelBelow ? `calc(${(b.y + b.h) * 100}% + 4px)` : `calc(${b.y * 100}% - 22px)`, display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap", maxWidth: 340 }}>
                  {b.labels.map((lb) => {
                    const isRen = renaming?.cid === b.cid && renaming?.tag === lb.tag;
                    const gname = groupName(lb.group);
                    const lc = tagColor(lb.tag);
                    return (
                      <div key={lb.tag} style={{ display: "flex", alignItems: "center", gap: 4, background: lc.stroke, color: lc.text, fontSize: "var(--fs-1)", fontFamily: "var(--mono)", padding: "1px 4px 1px 5px", borderRadius: 4, whiteSpace: "nowrap" }}>
                        {isRen ? (
                          <input
                            autoFocus
                            value={nameInput}
                            onChange={(e) => setNameInput(tagFieldInput(e.target.value))}
                            onMouseDown={(e) => e.stopPropagation()}
                            onBlur={commitRename}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") { e.preventDefault(); commitRename(); }
                              if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setRenaming(null); }
                            }}
                            style={labelInput}
                          />
                        ) : (
                          <span
                            onMouseDown={(e) => e.stopPropagation()}
                            onDoubleClick={(e) => { e.stopPropagation(); setRenaming({ cid: b.cid, tag: lb.tag }); setNameInput(lb.tag); }}
                            style={{ cursor: "text", display: "inline-flex", alignItems: "center" }}
                            title={t("Double-click to rename")}
                          >
                            {lb.tag}
                          </span>
                        )}
                        {/* Group pill: click to move this tag into another group. */}
                        <span
                          onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); }}
                          onClick={(e) => {
                            e.stopPropagation();
                            const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                            setGroupMenu({ cid: b.cid, tag: lb.tag, x: r.left, y: r.bottom + 4 });
                          }}
                          title={gname
                            ? t("Group: {name} · click to change", { name: gname })
                            : t("Ungrouped · click to set a group")}
                          style={{ display: "inline-flex", alignItems: "center", gap: 2, cursor: "pointer", padding: "0 3px", borderRadius: 3, background: "rgba(0,0,0,0.16)", maxWidth: 90, overflow: "hidden" }}
                        >
                          <Icon name={gname ? "folder" : "folder_off"} size={10} />
                          {gname && <span style={{ opacity: 0.85, fontSize: "var(--fs-0)", overflow: "hidden", textOverflow: "ellipsis" }}>{gname}</span>}
                        </span>
                        <span onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); }} onClick={(e) => { e.stopPropagation(); removeLabel(b.cid, lb.tag); }} title={t("Remove this tag")} style={{ cursor: "pointer", display: "flex" }}>
                          <Icon name="close" size={12} />
                        </span>
                      </div>
                    );
                  })}
                  {/* Add-a-tag control. */}
                  {addingTo === b.cid ? (
                    <TagAutocomplete
                      autoFocus
                      commitOnBlur
                      value={nameInput}
                      onChange={setNameInput}
                      onCommit={(name) => commitAddLabel(name)}
                      onCancel={() => setAddingTo(null)}
                      fetchSuggestions={fetchTagNameSuggestions}
                      existing={b.labels.map((l) => l.tag)}
                      placeholder={t("tag…")}
                      inputStyle={{ ...labelInput, width: 110, borderRadius: "var(--r-1)", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border-strong)" }}
                    />
                  ) : (
                    <span
                      // Activate on click (fires reliably in Safari); mousedown
                      // only suppresses the box drag + native focus-steal.
                      onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); }}
                      onClick={(e) => { e.stopPropagation(); setAddingTo(b.cid); setNameInput(""); }}
                      title={t("Add another tag to this box")}
                      style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 16, height: 16, borderRadius: 4, background: "var(--surface-float)", border: "1px solid var(--menu-border)", color: "var(--text-2)", cursor: "pointer" }}
                    >
                      <Icon name="add" size={12} />
                    </span>
                  )}
                </div>
              )}
              </React.Fragment>
            );
          });
          })()}
          {/* Marquee selection rectangle (edit mode). */}
          {marquee && (
            <div style={{ position: "absolute", left: `${marquee.x * 100}%`, top: `${marquee.y * 100}%`, width: `${marquee.w * 100}%`, height: `${marquee.h * 100}%`, border: "1px dashed #ff4faf", background: "rgba(255,79,175,0.10)", pointerEvents: "none" }} />
          )}
          {/* Box being drawn */}
          {draft && (
            <div style={{ position: "absolute", left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.w * 100}%`, height: `${draft.h * 100}%`, border: "2px dashed var(--accent)", background: "var(--accent-dim)", pointerEvents: "none" }} />
          )}
          {/* Polygon being laid down: the corners so far, a rubber line to
              the pointer, and the first corner enlarged — clicking it (or
              Enter) is what finishes the shape; Esc cancels, Backspace takes
              the last corner back. */}
          {polyDraft && (
            <>
              <svg viewBox="0 0 1 1" preserveAspectRatio="none"
                   style={{ position: "absolute", inset: 0, width: "100%",
                            height: "100%", overflow: "visible",
                            display: "block", pointerEvents: "none",
                            zIndex: 6 }}>
                <polyline
                  points={[...polyDraft,
                           ...(polyHover ? [[polyHover.x, polyHover.y]] : [])]
                    .map((pt) => `${pt[0]},${pt[1]}`).join(" ")}
                  fill={polyDraft.length >= 3 ? "var(--accent-dim)" : "none"}
                  stroke="var(--accent)" strokeWidth={2} strokeDasharray="6 4"
                  vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
              </svg>
              {polyDraft.map((pt, i) => (
                <span key={i} style={{
                  position: "absolute", zIndex: 6, pointerEvents: "none",
                  width: i === 0 ? 12 : 8, height: i === 0 ? 12 : 8,
                  left: `calc(${pt[0] * 100}% - ${i === 0 ? 6 : 4}px)`,
                  top: `calc(${pt[1] * 100}% - ${i === 0 ? 6 : 4}px)`,
                  background: i === 0 ? "var(--on-scrim)" : "var(--accent)",
                  border: i === 0 ? "2px solid var(--accent)"
                                  : "1.5px solid var(--on-scrim)",
                  boxShadow: "0 0 0 1px var(--scrim-2)", borderRadius: "50%",
                }} />
              ))}
            </>
          )}
          {/* Name prompt for a freshly-drawn box. The box itself stays adjustable
              while it waits for its tag — drag it to move, its corners to
              resize — so a slightly-off drag doesn't have to be redrawn. */}
          {pending && (
            <div
              onMouseDown={(e) => startPendingDrag(e, null)}
              style={{ position: "absolute", left: `${pending.box.x * 100}%`, top: `${pending.box.y * 100}%`, width: `${pending.box.w * 100}%`, height: `${pending.box.h * 100}%`, border: pending.box.points ? "1px dashed var(--accent)" : "2px dashed var(--accent)", background: pending.box.points ? "transparent" : "var(--accent-dim)", cursor: "move", zIndex: 5 }}
            >
              {pending.box.points && (
                <PolyShape b={pending.box} pts={pending.box.points}
                  stroke="var(--accent)" fill="var(--accent-dim)"
                  width={2} dash="6 4" />
              )}
              {["nw", "ne", "sw", "se"].map((corner) => (
                <span
                  key={corner}
                  onMouseDown={(e) => startPendingDrag(e, corner)}
                  style={{
                    position: "absolute", width: 10, height: 10, background: "var(--accent)",
                    border: "1px solid var(--scrim-2)", borderRadius: 2,
                    left: corner.includes("w") ? -5 : undefined,
                    right: corner.includes("e") ? -5 : undefined,
                    top: corner.includes("n") ? -5 : undefined,
                    bottom: corner.includes("s") ? -5 : undefined,
                    cursor: `${corner}-resize`,
                  }}
                />
              ))}
              <div onMouseDown={(e) => e.stopPropagation()} style={{ position: "absolute", top: -34, left: 0, display: "flex", gap: 4, background: "var(--surface-float)", border: "1px solid var(--menu-border)", borderRadius: "var(--r-3)", padding: 5, zIndex: 6, cursor: "default" }}>
                <TagAutocomplete
                  autoFocus
                  value={nameInput}
                  onChange={setNameInput}
                  onCommit={(name) => commitPending(name)}
                  onCancel={() => setPending(null)}
                  fetchSuggestions={fetchTagNameSuggestions}
                  placeholder={t("tag…")}
                  inputStyle={{ height: 26, width: 130, borderRadius: "var(--r-1)", fontSize: "var(--fs-3)" }}
                />
                <button onMouseDown={(e) => { e.stopPropagation(); commitPending(); }} title={t("Add this box")} style={{ height: 26, padding: "0 10px", borderRadius: "var(--r-1)", border: "none", background: "var(--accent)", color: "var(--on-accent)", fontSize: "var(--fs-2)", cursor: "pointer" }}>{t("Add")}</button>
                <button onMouseDown={(e) => { e.stopPropagation(); setPending(null); }} title={t("Discard this box (Esc)")} style={{ width: 26, height: 26, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "var(--r-1)", border: "1px solid var(--border-strong)", background: "transparent", color: "var(--muted-2)", cursor: "pointer" }}>
                  <Icon name="close" size={15} />
                </button>
              </div>
            </div>
          )}
          {/* A fresh subject outline waiting for its person: the shape stays
              put while the field asks who it is — the face naming flow, one
              level up. Only reached with nobody picked in the sidebar; picked
              rows take the shape without asking. */}
          {pendingOutline && (
            <div
              onMouseDown={(e) => e.stopPropagation()}
              style={{ position: "absolute",
                left: `${pendingOutline.x * 100}%`,
                top: `${pendingOutline.y * 100}%`,
                width: `${pendingOutline.w * 100}%`,
                height: `${pendingOutline.h * 100}%`,
                border: pendingOutline.points
                  ? "1px dashed var(--accent)" : "2px dashed var(--accent)",
                background: pendingOutline.points
                  ? "transparent" : "var(--accent-dim)",
                zIndex: 9 }}
            >
              {pendingOutline.points && (
                <PolyShape b={pendingOutline} pts={pendingOutline.points}
                  stroke="var(--accent)" fill="var(--accent-dim)"
                  width={2} dash="6 4" />
              )}
              <div
                onMouseDown={(e) => e.stopPropagation()}
                style={{ position: "absolute", left: "50%", top: "100%",
                  marginTop: 4, transform: "translateX(-50%)", zIndex: 9,
                  display: "flex", alignItems: "center", gap: 4,
                  pointerEvents: "auto" }}
              >
                <div style={{ width: 268, display: "flex",
                  alignItems: "center", gap: 4 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <TagAutocomplete
                      value={outlineName}
                      onChange={setOutlineName}
                      onCommit={(text) => void nameOutline(text)}
                      onCancel={() => { setPendingOutline(null); setOutlineName(""); }}
                      suggestions={faceSuggestions}
                      placeholder={t("Who is this?")}
                      freeText
                      autoFocus
                      minWidth={220}
                    />
                  </div>
                  <div
                    onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    onClick={() => void nameOutline(outlineName)}
                    title={t("Add this outline")}
                    style={{ ...faceFieldBtn, opacity: outlineName.trim() ? 1 : 0.4,
                      color: "var(--accent)", borderColor: "var(--accent)" }}
                  >
                    <Icon name="check" size={15} />
                  </div>
                  <div
                    onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    onClick={() => { setPendingOutline(null); setOutlineName(""); }}
                    title={t("Cancel")}
                    style={faceFieldBtn}
                  >
                    <Icon name="close" size={15} />
                  </div>
                </div>
              </div>
            </div>
          )}
          {/* Snapshot outlines over the film: where the crops of this frame
              sit. Neutral white, so they never read as a tag's box. Nothing
              creates a cropped still any more — these are what older libraries
              collected — so the outline only SAYS where one was taken, and
              double-clicking opens it in its own tab, the same gesture the
              stills list uses. */}
          {onVideo && frameStills.filter((st) => st.crop).map((st) => {
            const [x, y, w, h] = st.crop as [number, number, number, number];
            const open = editorTabs.includes(st.item_id);
            return (
              <div
                key={st.item_id}
                onMouseDown={(e) => e.stopPropagation()}
                onDoubleClick={(e) => { e.stopPropagation(); openTab(st.item_id); }}
                title={t("{name} — double-click to open this still", { name: st.name })}
                style={{
                  position: "absolute", left: `${x * 100}%`, top: `${y * 100}%`,
                  width: `${w * 100}%`, height: `${h * 100}%`,
                  border: `${open ? 2 : 1}px ${open ? "solid" : "dashed"} ${open ? "var(--on-scrim)" : "var(--on-scrim-3)"}`,
                  borderRadius: 2, cursor: "pointer",
                }}
              />
            );
          })}
          {/* Faces — a second layer over the same picture, shown only while
              the mode is on. Clicking the label names the face, which puts
              that subject's tag on the item; the button beside it dismisses a
              DETECTED face (so the next run does not offer the same false
              positive again) and deletes a hand-drawn one, which nothing ever
              offered.

              The oval takes the pointer only once it is SELECTED, exactly as a
              tag box does: an unselected one is draw-through, so a drag across
              it makes a new face and a click on it picks one (`clickAt`), and
              a click on nothing puts the selection down. */}
          {/* OUTLINES — a subject's box, or a face's whole figure; rectangles
              or polygons, never ovals (the outline says the figure where the
              face says the head). Draw-through until SELECTED — clicking the
              shape picks it exactly like a tag box (`clickAt`), the name row
              still does too — and selected it moves, its corners edit (bbox
              handles in box mode, the shape's own corners in poly mode), and
              a click on nothing puts it down. It HIGHLIGHTS while its
              subject's row (or its face's crop) is picked in the sidebar,
              the same shared highlight the tag boxes read off that pick. */}
          {outlineGeos.map((geo) => {
              const g = (liveOutline && liveOutline.okey === geo.key)
                ? liveOutline : geo;
              const isSel = selOut === geo.key;
              const hot = geo.hot;
              const bw = isSel || hot ? 3 : 2;
              // Barely there in FACE mode (the ovals' layer is what a draw is
              // about, and two full grids over one picture read as one), and
              // in outline mode an entry nobody picked recedes while anything
              // is picked — the tag boxes' ghost rule at the outline layer.
              // A picked or sidebar-lit outline shows whole in OUTLINE mode;
              // in face mode even a lit one only comes halfway back (`soft`),
              // saying where the figure is without competing with the ovals.
              const dim = !isSel && !hot
                && (subjectDraw === "face"
                    || selApps.size > 0 || faceSel.length > 0);
              const soft = !dim && subjectDraw === "face";
              return (
                <div key={`out-${geo.key}`}
                  onMouseDown={(e) => {
                    if (!isSel || e.button !== 0 || spaceHeld) return;
                    e.stopPropagation();
                    drag.current = { kind: "omove", okey: geo.key,
                                     startFrac: frac(e.clientX, e.clientY),
                                     orig: g, shift: e.shiftKey };
                  }}
                  style={{
                    position: "absolute", left: `${g.x * 100}%`,
                    top: `${g.y * 100}%`, width: `${g.w * 100}%`,
                    height: `${g.h * 100}%`, zIndex: 7,
                    opacity: dim ? 0.3 : soft ? 0.55 : 1,
                    // Only a SELECTED outline takes the pointer — unselected
                    // it stays draw-through, so a drag across it still draws
                    // a face, and the click that picks it goes through
                    // `clickAt` like every other shape.
                    pointerEvents: isSel ? "auto" : "none",
                    cursor: isSel ? "move" : undefined,
                    border: g.points
                      ? (isSel && !polyUI
                          ? "1px dashed var(--accent)" : "none")
                      : `${bw}px solid var(--accent)`,
                    boxShadow: g.points ? undefined
                      : "var(--ring-shadow), inset var(--ring-shadow)"
                        + (isSel || hot
                            ? ", inset 0 0 0 2.5px var(--on-scrim)" : ""),
                  }}>
                  {g.points && (
                    <PolyShape b={g} pts={g.points} stroke="var(--accent)"
                      fill={isSel || hot ? "var(--accent-dim)" : "transparent"}
                      width={bw} ring={isSel || hot} />
                  )}
                  {isSel && !spaceHeld && !polyUI
                    && ["nw", "ne", "sw", "se"].map((corner) => (
                    <span key={corner}
                      onMouseDown={(e) => {
                        if (e.button !== 0) return;
                        e.stopPropagation();
                        drag.current = { kind: "oresize", okey: geo.key,
                                         corner, orig: g };
                      }}
                      style={{
                        position: "absolute", width: 10, height: 10,
                        background: "var(--accent)",
                        border: "1px solid var(--scrim-2)", borderRadius: 2,
                        left: corner.includes("w") ? -5 : undefined,
                        right: corner.includes("e") ? -5 : undefined,
                        top: corner.includes("n") ? -5 : undefined,
                        bottom: corner.includes("s") ? -5 : undefined,
                        cursor: `${corner}-resize`,
                      }}
                    />
                  ))}
                  {isSel && !spaceHeld && polyUI && (() => {
                    const pts = g.points ?? rectPts(g);
                    return (
                      <>
                        {pts.map((pt, i) => {
                          const on = selVertex?.kind === "out"
                            && selVertex.okey === geo.key
                            && selVertex.idx === i;
                          const r2 = on ? 6 : 5;
                          return (
                          <span key={`v${i}`}
                            onMouseDown={(e) => {
                              if (e.button !== 0) return;
                              e.stopPropagation();
                              drag.current = { kind: "ovmove", okey: geo.key,
                                idx: i, moved: false,
                                pts0: pts.map((q) => [...q] as [number, number]) };
                            }}
                            onDoubleClick={(e) => {
                              e.stopPropagation();
                              if (pts.length <= 3) return;
                              const next = pts.filter((_, j) => j !== i)
                                .map((q) => [...q] as [number, number]);
                              commitOutlineRef.current(
                                { ...polyBounds(next), points: next },
                                geo.key);
                            }}
                            title={pts.length > 3
                              ? t("Drag to move · click picks · Delete removes this corner")
                              : t("Drag to move this corner")}
                            style={{
                              position: "absolute",
                              width: r2 * 2, height: r2 * 2,
                              left: `calc(${((pt[0] - g.x) / (g.w || 1)) * 100}% - ${r2}px)`,
                              top: `calc(${((pt[1] - g.y) / (g.h || 1)) * 100}% - ${r2}px)`,
                              background: on ? "var(--on-scrim)" : "var(--accent)",
                              border: on ? "2px solid var(--accent)"
                                         : "1.5px solid var(--on-scrim)",
                              boxShadow: "0 0 0 1px var(--scrim-2)",
                              borderRadius: "50%", cursor: "move", zIndex: 8,
                            }}
                          />
                          );
                        })}
                        {pts.map((pt, i) => {
                          const nx2 = pts[(i + 1) % pts.length];
                          const mx = (pt[0] + nx2[0]) / 2;
                          const my = (pt[1] + nx2[1]) / 2;
                          return (
                            <span key={`m${i}`}
                              onMouseDown={(e) => {
                                if (e.button !== 0) return;
                                e.stopPropagation();
                                const pts0 = [...pts.slice(0, i + 1),
                                              [mx, my] as [number, number],
                                              ...pts.slice(i + 1)]
                                  .map((q) => [...q] as [number, number]);
                                drag.current = { kind: "ovmove",
                                                 okey: geo.key,
                                                 idx: i + 1, pts0,
                                                 moved: true };
                                setLiveOutline({ okey: geo.key,
                                  ...polyBounds(pts0), points: pts0 });
                              }}
                              title={t("Add a corner here")}
                              style={{
                                position: "absolute", width: 7, height: 7,
                                left: `calc(${((mx - g.x) / (g.w || 1)) * 100}% - 3.5px)`,
                                top: `calc(${((my - g.y) / (g.h || 1)) * 100}% - 3.5px)`,
                                background: "var(--on-scrim)",
                                border: "1.5px solid var(--accent)",
                                borderRadius: "50%", cursor: "copy", zIndex: 8,
                              }}
                            />
                          );
                        })}
                      </>
                    );
                  })()}
                  {!dim && !soft && <div style={{
                    position: "absolute", left: "50%", top: "100%",
                    marginTop: 4, transform: "translateX(-50%)",
                    display: "flex", alignItems: "center", gap: 4,
                    pointerEvents: "auto",
                    background: isSel ? "var(--accent)" : "var(--scrim-3)",
                    color: isSel ? "var(--on-accent)" : "var(--on-scrim)",
                    borderRadius: "var(--r-2)", padding: "2px 6px", fontSize: "var(--fs-2)",
                    whiteSpace: "nowrap",
                  }}>
                    <span
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={() => (geo.key.startsWith("app:")
                        ? people.subjectSel.set(
                            isSel ? [] : [`a:${geo.key.slice(4)}`])
                        : setFaceSel(
                            isSel ? [] : [Number(geo.key.slice(5))]))}
                      title={isSel ? t("Put this outline down")
                                   : t("Select this outline to edit it")}
                      style={{ cursor: "pointer" }}>
                      {geo.label}
                    </span>
                    <span title={t("Remove this outline")}
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={geo.clear}
                      style={{ display: "flex", cursor: "pointer",
                               opacity: 0.8 }}>
                      <Icon name="close" size={12} />
                    </span>
                  </div>}
                </div>
              );
            })}
          {faceMode && !onVideo && (faces ?? []).filter((f) => !f.dismissed).map((f) => {
            const r = liveFaces[f.id] ?? refToFile(f, activeFile);
            // Who this face is — its FIRST claim, since a box can be a
            // character and the actor at once and the chip has room for one.
            const who = f.subjects[0];
            const named = !!who && who.assigned_by === "user";
            const picked = faceSel.includes(f.id);
            const naming = namingFace === f.id;
            // Barely there in OUTLINE mode: the outlines' layer is what a
            // draw is about there, and the ovals with their labels over the
            // same figures read as a second grid of the same thing. A picked
            // face still shows whole — the sidebar's crops can pick one, and
            // picking its OUTLINE picks it too — but with an outline on
            // screen the chip stays away even then: the outline's own label
            // already names it, and two chips under one figure said the same
            // thing twice (the label row's render condition below).
            const dimFace = subjectDraw === "outline" && !picked;
            return (
              <div key={f.id}
                onMouseDown={(e) => {
                  if (e.button !== 0 || spaceHeld) return;
                  e.stopPropagation();
                  e.preventDefault();
                  drag.current = {
                    kind: "facemove", id: f.id, startFrac: frac(e.clientX, e.clientY),
                    orig: r, shift: e.shiftKey,
                  };
                }}
                style={{
                position: "absolute", left: `${r.x * 100}%`, top: `${r.y * 100}%`,
                width: `${r.w * 100}%`, height: `${r.h * 100}%`, zIndex: picked ? 9 : 8,
                opacity: dimFace ? 0.25 : 1,
                // Only the selected oval is grabbable; the rest are
                // draw-through so one gesture still both draws and picks.
                // Its CHILDREN take their clicks back — the label is how a
                // face is named, and that must not need selecting first.
                pointerEvents: picked && !spaceHeld
                  && subjectDraw === "face" ? undefined : "none",
                cursor: picked ? "move" : "crosshair",
                border: `${picked ? 3 : 2}px ${named || picked ? "solid" : "dashed"} ${picked || named ? "var(--accent)" : "var(--on-scrim)"}`,
                borderRadius: FACE_OUTLINE_RADIUS,
                background: picked ? "var(--accent-dim)" : undefined,
                // A white outline disappears on a white page, and this library
                // is mostly black-and-white manga. The dark ring either side of
                // it keeps the oval readable on any background.
                boxShadow: named || picked
                  ? "var(--ring-shadow)"
                  : "var(--ring-shadow), inset var(--ring-shadow)",
              }}>
                {/* A picked face's corners resize its rectangle — detected
                    faces included, now that a hand edit survives the next
                    run (`FaceBoxEdit`) and can be reset from the row's ⋯. */}
                {picked && !spaceHeld && subjectDraw === "face"
                  && ["nw", "ne", "sw", "se"].map((corner) => (
                  <span key={corner}
                    onMouseDown={(e) => {
                      if (e.button !== 0) return;
                      e.stopPropagation();
                      e.preventDefault();
                      drag.current = { kind: "faceresize", id: f.id,
                                       corner, orig: r };
                    }}
                    style={{
                      position: "absolute", width: 10, height: 10,
                      background: "var(--accent)",
                      border: "1px solid var(--scrim-2)", borderRadius: 2,
                      left: corner.includes("w") ? -5 : undefined,
                      right: corner.includes("e") ? -5 : undefined,
                      top: corner.includes("n") ? -5 : undefined,
                      bottom: corner.includes("s") ? -5 : undefined,
                      cursor: `${corner}-resize`, zIndex: 10,
                    }}
                  />
                ))}
                {/* The row under the oval: who this is, and the one way to be
                    rid of it. CENTRED below rather than left-aligned above —
                    the outline is an ellipse, so a chip hung off the bounding
                    box's top-left corner sits in empty space beside the head
                    it names, while under its widest point it reads as a
                    caption of the face. Naming REPLACES this row in place, so
                    the field opens exactly where the label you clicked was
                    rather than somewhere else on the picture. */}
                {!dimFace
                  && !(subjectDraw === "outline" && f.outline) && <div
                  onMouseDown={(e) => e.stopPropagation()}
                  style={{
                    position: "absolute", left: "50%", top: "100%", marginTop: 4,
                    transform: "translateX(-50%)", zIndex: 9,
                    display: "flex", alignItems: "center", gap: 4,
                    // Taken back from the oval, which is draw-through until it
                    // is picked.
                    pointerEvents: "auto",
                  }}
                >
                {naming ? (
                  // The field takes the focus AND selects what is in it, so a
                  // face that already has a name is retyped rather than
                  // appended to. The tick and cross are here because the field
                  // opens over the picture: Enter and Escape work, but nothing
                  // on screen said so, and the mouse that opened it had no way
                  // to finish.
                  <div
                    // Focus leaving the field closes it WITHOUT naming — the
                    // same thing Escape and the ✕ do. A field floating over
                    // the picture with nothing in it is in the way of the next
                    // thing you reach for, and clicking away is how anyone
                    // says "not that one after all". The tick, the cross and
                    // the suggestion rows all `preventDefault` their mousedown
                    // so they never blur it; `relatedTarget` covers the rest.
                    onBlur={(e) => {
                      if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
                      setNamingFace(null); setFaceName("");
                    }}
                    style={{ width: 268, display: "flex", alignItems: "center", gap: 4 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <TagAutocomplete
                        value={faceName}
                        onChange={setFaceName}
                        onCommit={(text) => void nameFace(f.id, text)}
                        onCancel={() => { setNamingFace(null); setFaceName(""); }}
                        suggestions={faceSuggestions}
                        placeholder={t("Who is this?")}
                        freeText
                        autoFocus
                        autoSelect
                        minWidth={220}
                      />
                    </div>
                    <div
                      onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
                      onClick={() => void nameFace(f.id, faceName)}
                      title={t("Name this face")}
                      style={{ ...faceFieldBtn, opacity: faceName.trim() ? 1 : 0.4,
                        color: "var(--accent)", borderColor: "var(--accent)" }}
                    >
                      <Icon name="check" size={15} />
                    </div>
                    <div
                      onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
                      onClick={() => { setNamingFace(null); setFaceName(""); }}
                      title={t("Cancel")}
                      style={faceFieldBtn}
                    >
                      <Icon name="close" size={15} />
                    </div>
                  </div>
                ) : (<>
                  <div
                    onMouseDown={(e) => {
                      e.stopPropagation();
                      // preventDefault, or the field never gets the caret: a
                      // mousedown's default action is to focus what was pressed,
                      // and that runs AFTER the field has mounted and taken
                      // focus — so the chip stole it straight back and you had
                      // to click the empty box before typing.
                      e.preventDefault();
                      setNamingFace(f.id);
                      setFaceName(who?.name || "");
                    }}
                    title={f.det_score != null
                      ? t("{pct}% — click to name", { pct: Math.round(f.det_score * 100) })
                      : t("Added by hand — click to name")}
                    style={{
                      height: 20, maxWidth: 200, padding: "0 7px", display: "flex",
                      alignItems: "center", gap: 4, borderRadius: "var(--r-1)", cursor: "pointer",
                      background: named ? "var(--accent)" : "var(--overlay-chrome)",
                      color: named ? "var(--on-accent)" : "var(--muted)",
                      border: "1px solid var(--border)", fontSize: "var(--fs-2)",
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    }}
                  >
                    <Icon name="face" size={13} />
                    {who?.name || (who?.assigned_by === "suggested"
                      ? "?" : t("Who is this?"))}
                    {who?.assigned_by === "suggested" && who.match_score != null
                      && ` ${Math.round(who.match_score * 100)}%`}
                    {f.subjects.length > 1 && ` +${f.subjects.length - 1}`}
                  </div>
                  {/* On a DETECTED face this dismisses: that is how a detector
                      is told to stop offering the same false positive, and it
                      works by absorbing the next detection over the box. On a
                      box drawn HERE by hand there is nothing to stop offering
                      it, so the same button deletes instead — and it is the
                      only removal this window has.

                      DIRECTLY AFTER the label, not on the ring: on the outline
                      it was an 18 px target somebody had to aim at over the
                      picture, and it moved with every head it belonged to.
                      Beside the name it sits where the face's other answer
                      already is. */}
                  <div
                    onMouseDown={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      void (f.models.length
                        ? api.updateFace(f.id, { dismissed: true })
                        : api.deleteFace(f.id)).then(refreshFaces);
                    }}
                    title={f.models.length ? t("Not a face — stop offering it")
                                           : t("Delete this face")}
                    data-faceact
                    style={{
                      flex: "0 0 auto", width: 20, height: 20, borderRadius: "var(--r-1)",
                      background: "var(--overlay-chrome)",
                      border: "1px solid var(--border)", display: "flex",
                      alignItems: "center", justifyContent: "center",
                      cursor: "pointer", color: "var(--muted-2)",
                    }}
                  >
                    {/* The glyph says which of the two this is — a face crossed out
                        for "not a face", a cross for deleting one drawn by hand.
                        One control doing two things must not wear one icon. */}
                    <Icon name={f.models.length ? "face_retouching_off" : "close"} size={13} />
                  </div>
                </>)}
                </div>}
              </div>
            );
          })}

          {/* THE TEXT LAYER — a rectangle per region (or the engine's own
              quad, drawn as an SVG polygon: an upright rectangle over
              slanted text is a picture that lies). Green, not the accent:
              accent means "selected" on this canvas, and a text box and a
              tag box are both rectangles, so the layer needs a colour of
              its own. Draw-through unless picked, the face rule — one
              gesture still both draws and picks. Read-only geometry in v1:
              a detected region's box follows the next run anyway. */}
          {textMode && !onVideo && textRegions
            // Only the ACTIVE engine's reading (hand-drawn always shows) —
            // the sidebar's dropdown and this canvas must say the same
            // thing.
            .filter((r) => textVisible.has(r.id))
            // A CHILD box is drawn only under a picked row (see `textSub`).
            .filter((r) => r.parent_id == null || textSub.has(r.id))
            // A dismissed region takes its DESCENDANTS off the picture with
            // it — "not text" is about the stretch, and the words inside it
            // are the same stretch said smaller.
            .filter((r) => {
              for (let cur: TextRegion | undefined = r; cur;
                   cur = textRegions.find((p) => p.id === cur!.parent_id)) {
                if (cur.dismissed) return false;
                if (cur.parent_id == null) break;
              }
              return true;
            })
            .map((r) => {
              const picked = textSel.includes(textRowKey(r.id));
              const child = r.parent_id != null;
              // Pointed at from the sidebar. Drawn like a pick (it is the
              // same claim — "this row, this box") but it does not touch the
              // selection, so it fades the moment the pointer leaves.
              const lit = textHover === r.id;
              const stroke = picked || lit ? "var(--accent)" : "var(--green)";
              // A PICKED region is editable: its box moves and bbox-resizes
              // exactly like a tag box (only the selected one takes the
              // pointer at all), and a slanted quad rides the same affine so
              // the shape is never flattened to an upright rectangle.
              const live = liveText && liveText.id === r.id ? liveText : null;
              const box = live ?? refToFile(r, activeFile);
              const quad = live
                ? live.quad ?? null
                : r.quad.length === 4
                  ? (quadToFile(r.quad, activeFile) as [number, number][])
                  : null;
              const editable = picked && !spaceHeld;
              const grab = (e: React.MouseEvent, corner: string | null) => {
                if (e.button !== 0) return;
                e.stopPropagation();
                const orig = { x: box.x, y: box.y, w: box.w, h: box.h,
                               quad: quad ?? undefined };
                drag.current = corner
                  ? { kind: "tresize", id: r.id, corner, orig }
                  : { kind: "tmove", id: r.id,
                      startFrac: frac(e.clientX, e.clientY), orig };
              };
              return (
                <React.Fragment key={`t${r.id}`}>
                {quad && (
                  <svg viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                    style={{ position: "absolute", inset: 0, width: "100%",
                             height: "100%", overflow: "visible",
                             pointerEvents: "none",
                             zIndex: picked || lit ? 7 : 6 }}>
                    <polygon
                      points={quad.map(([x, y]) => `${x * 100},${y * 100}`)
                        .join(" ")}
                      fill="none"
                      stroke="var(--scrim-2)"
                      strokeWidth={child ? 3 : 4}
                      vectorEffect="non-scaling-stroke" />
                    <polygon
                      points={quad.map(([x, y]) => `${x * 100},${y * 100}`)
                        .join(" ")}
                      fill={picked || lit ? "var(--accent-dim)" : "none"}
                      stroke={stroke} strokeWidth={child ? 1 : lit ? 3 : 2}
                      vectorEffect="non-scaling-stroke" />
                  </svg>
                )}
                {(!quad || editable) && (
                <div
                  onMouseDown={editable ? (e) => grab(e, null) : undefined}
                  style={{
                  position: "absolute",
                  left: `${box.x * 100}%`, top: `${box.y * 100}%`,
                  width: `${box.w * 100}%`, height: `${box.h * 100}%`,
                  zIndex: picked || lit ? 7 : 6,
                  pointerEvents: editable ? "auto" : "none",
                  cursor: editable ? "move" : undefined,
                  // A quad's rectangle is only its transform frame.
                  border: quad
                    ? "1px dashed var(--accent)"
                    : `${child ? 1 : picked || lit ? 3 : 2}px solid ${stroke}`,
                  borderRadius: 2,
                  background: !quad && (picked || lit)
                    ? "var(--accent-dim)" : undefined,
                  // The dark ring that keeps a light outline readable on a
                  // white manga page.
                  boxShadow: quad ? undefined : "var(--ring-shadow)",
                  opacity: child && !picked ? 0.55 : 1,
                }}>
                  {editable && ["nw", "ne", "sw", "se"].map((corner) => (
                    <span
                      key={corner}
                      onMouseDown={(e) => grab(e, corner)}
                      style={{
                        position: "absolute", width: 10, height: 10,
                        background: "var(--accent)",
                        border: "1px solid var(--scrim-2)", borderRadius: 2,
                        left: corner.includes("w") ? -5 : undefined,
                        right: corner.includes("e") ? -5 : undefined,
                        top: corner.includes("n") ? -5 : undefined,
                        bottom: corner.includes("s") ? -5 : undefined,
                        cursor: `${corner}-resize`,
                      }}
                    />
                  ))}
                </div>
                )}
                </React.Fragment>
              );
            })}
        </div>

        {/* Hint (image). Only what cannot be guessed from looking: the two
            gestures that a drag can mean, and the key that pans. What a "+"
            does, that corners resize and that a double-click renames are all
            things the control says itself by being there — spelling them out
            made a line long enough to slide under the zoom cluster opposite,
            which is why it is also BOUNDED away from it rather than merely
            shortened. Bounded rather than truncated: the text wraps inside its
            own corner instead of disappearing under something. */}
        {!isVideo && (
          <div style={{ position: "absolute", left: 14, bottom: 12, maxWidth: `calc(100% - ${ZOOM_CLUSTER + 28}px)`, display: "flex", alignItems: "center", gap: 8, padding: "6px 11px", background: "var(--overlay-chrome)", border: "1px solid var(--border)", borderRadius: "var(--r-4)", fontSize: "var(--fs-2)", color: "var(--muted)" }}>
            <Icon name="keyboard" size={15} color="var(--accent)" />
            {spaceHeld
              ? t("Drag to pan · scroll to zoom")
              // A WHOLE sentence per draw target, never a fragment slotted
              // into a frame — and the bar is what says which layer a drag
              // draws into when several are on screen.
              : polyDraft
                ? t("Click to add corners · the first corner or Enter finishes · Backspace takes one back · Esc cancels")
                : textMode && !faceMode
                ? t("Drag to draw a text box · click to select · ⌥ drag to select · Space to pan")
                : faceMode && subjectDraw === "outline"
                ? (polyUI
                  ? t("Click to lay an outline's corners · it lands on the picked people, or asks who it is")
                  : t("Drag to outline a figure · it lands on the picked people, or asks who it is"))
                : polyUI && !faceMode
                ? t("Click to lay a polygon's corners · click to select · ⌥ drag to select · Space to pan")
                : t("Drag to draw · click to select · ⌥ drag to select · Space to pan")}
          </div>
        )}

        {/* Unplayable video: shown when THIS browser can't play the file — either
            a hard load/decode error, or its own `canPlayType` says it can't
            (Safari for an MKV, where Chromium reports it fine). Never a format
            guess, so it stays silent wherever the file actually plays (T22). */}
        {onVideo && (play.error || browserCantPlay(hostFile?.format)) && (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", pointerEvents: "none" }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, maxWidth: 420, textAlign: "center", padding: "18px 22px", background: "var(--overlay-chrome)", border: "1px solid var(--border)", borderRadius: "var(--r-7)", color: "var(--text-2)" }}>
              <Icon name="error_outline" size={28} color="var(--yellow)" />
              <div style={{ fontSize: "var(--fs-4)", fontWeight: 600, color: "var(--text-bright)" }}>{t("This video can't be played here")}</div>
              <div style={{ fontSize: "var(--fs-2)", color: "var(--muted)", lineHeight: 1.5 }}>
                {t("Its format or codec ({format}) isn't supported by the browser's player. You can still tag the whole item and manage its metadata; drawing timed boxes needs a playable preview.", { format: activeFile?.format ?? "" })}
              </div>
            </div>
          </div>
        )}

        {/* Media bar, bottom-LEFT: speed, volume and the subtitle/audio track
            pickers, mirroring the zoom cluster opposite it. They belong to the
            picture rather than to the edit, and each opens its popover upwards
            into the empty canvas instead of crowding the transport row. */}
        {isVideo && (
          <div
            onMouseDown={(e) => e.stopPropagation()}
            style={{ position: "absolute", left: 14, bottom: 12, display: "flex", alignItems: "center", gap: 2, padding: 3, background: "var(--surface-float)", border: "1px solid var(--border)", borderRadius: "var(--r-5)", boxShadow: "var(--shadow-2)" }}
          >
            <SpeedControl rate={play.rate} onRate={play.setRate} />
            {hasAudio && (
              <VolumeControl muted={play.muted} volume={play.volume} onToggle={play.toggleMuted} onVolume={play.setVolume} />
            )}
            <TrackControls
              videoRef={play.videoRef} subTracks={subTracks} audioTracks={audioStreams}
            />
          </div>
        )}

        {/* Playback, bottom-CENTRE, between those two: play, step and the
            timecode are about the picture — how it is running and where it is
            — which is what this whole edge already says. */}
        {isVideo && <PlaybackBar play={play} fps={fps} t={t} />}

        {/* Sequence step, top-RIGHT: turning the page is about the picture, so
            it floats over it like the zoom cluster and the media bar rather
            than sitting in the header among the window's own controls. */}
        {itemId != null && itemSeqs && itemSeqs.length > 0 && (
          <SequenceNav
            seqs={itemSeqs}
            itemId={itemId}
            pick={seqPick}
            onPick={setSeqPick}
            onGo={goItem}
            t={t}
          />
        )}

        {/* Zoom controls (shared editor chrome), bottom-right. Stop the mousedown
            reaching the canvas draw handler (else a box flashes behind them). */}
        <div onMouseDown={(e) => e.stopPropagation()}>
          <ZoomControls zp={zp} t={t} />
        </div>
      </div>

      {/* THE TIMELINE PANEL, below the canvas and RESIZABLE by its top edge.
          How many tag tracks fit is the question this window's whole bottom
          half is about, and it differs per film and per job — a fixed height
          could only ever be right for one of them. The height is remembered
          per browser, and clamped on every window resize, since a window
          shrunk past it would leave the panel taller than the picture. */}
      {isVideo && (
        <div style={{ flex: `0 0 ${bottomH}px`, height: bottomH, minHeight: 0,
          display: "flex", flexDirection: "column",
          borderTop: "1px solid var(--border)", background: "var(--panel)" }}>
          <SplitHandle split={bottom} inFlow thickness={5} title={t("Drag to resize the timeline")} />
          <div style={{ flex: 1, minHeight: 0, display: "flex",
            flexDirection: "column", gap: 7, padding: "4px 14px 9px" }}>
          {/* THE FILM'S TIMED TAGS, one track each, on the video editor's own
              scale. Every tag has a track whether or not it is selected, and
              picking one changes nothing about what is drawn — so the thing
              you are aiming at does not move as you aim at it. */}
          <TagTrack
            duration={play.duration}
            fps={fps}
            time={play.time}
            onSeek={play.seek}
            playing={play.playing}
            range={{ start: inPoint, end: outPoint }}
            onRangeChange={(s, e) => { setInPoint(s); setOutPoint(e); }}
            blocks={timedRanges}
            selKeys={timeSelSet}
            onPick={pickTimeRow}
            onCommit={commitRange}
            onToggleSign={toggleRangeSign}
            onHoverTag={setHoverTag}
            stills={stillMarks}
            fitKey={`${hostId}:${activeFile?.id ?? ""}`}
            t={t}
          />
          {/* The marked range, applied to the tags SELECTED in the sidebar. A
              film tag is a stretch of time, and this is how a stretch is
              granted or taken away in one go — without hunting down the
              individual entries it is made of. ALWAYS rendered: it used to
              appear the moment a range was marked, which pushed the transport,
              the timeline and the picture up by its own height at the exact
              moment a drag had just finished aiming at them. The in/out FIELDS
              ride at its right end, which is where they have always been —
              one row further down now that the playback controls float over
              the picture instead. */}
          <RangeActions
            range={markedRange}
            fps={fps}
            names={selectedTagNames}
            busy={rangeBusy}
            onApply={(op) => void applyRange(op)}
            onClear={clearRange}
            trailing={
              <RangeFields
                play={play} fps={fps} t={t}
                inPoint={inPoint} outPoint={outPoint}
                onIn={setInPoint} onOut={setOutPoint} onClear={clearRange}
              />
            }
            t={t}
          />
          </div>
        </div>
      )}
      </div>{/* end left column */}

      {/* Draggable divider to resize the sidebar: a hairline, with a wider
          invisible grab area around it so it stays easy to hit. */}
      <SplitHandle split={sidebar} inFlow hairline thickness={5} title={t("Drag to resize the sidebar")} />

      {/* Right sidebar. The TAGS list's row selection is the box filter and
          mirrors what is selected on the canvas, so the separate "Boxes"
          legend is gone — it was a second place to select the same thing. The
          other four lists are the library sidebar's own, because a picture
          being annotated is the same picture and its people, places, events
          and captions do not become a different subject in this window. */}
      <div style={{ flex: `0 0 ${sidebarW}px`, width: sidebarW, minWidth: ANNOTATOR_SIDEBAR_MIN, background: "var(--panel)", display: "flex", flexDirection: "column" }}>
        {/* One row of tabs, scrolled with nothing: the strip is the sidebar's
            heading and stays put while the list under it moves. */}
        <div style={{ flex: "0 0 auto", display: "flex", gap: 2, padding: "8px 8px 0" }}>
          {/* A film-only tab is not offered on a picture: a Stills button over
              an image is a button that can only ever open an empty list. */}
          {SIDE_TABS.filter((s2) => (!s2.video || isVideo)
                                 && (!s2.image || !isVideo)).map((s2) => (
            <button
              key={s2.id}
              onClick={(e) => pickTab(s2.id, e.metaKey || e.ctrlKey)}
              title={`${t(s2.label)} — ${t("click to switch · ⌘-click to keep several open")}`}
              style={{
                flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
                gap: 4, height: 28, borderRadius: "var(--r-3)", cursor: "pointer",
                border: `1px solid ${tabs.has(s2.id) ? "var(--accent)" : "transparent"}`,
                background: tabs.has(s2.id) ? "var(--accent-dim)" : "transparent",
                color: tabs.has(s2.id) ? "var(--accent)" : "var(--muted-2)",
                fontFamily: "inherit", fontSize: "var(--fs-2)", fontWeight: 600,
              }}
            >
              <Icon name={s2.icon} size={15} />
            </button>
          ))}
        </div>
        {/* The bars float over the bottom of the scroll area, positioned
            against THIS wrapper rather than inside the scroller — absolutely
            positioned inside a scrolling box would scroll away with the rows,
            and `sticky` only ever pulls an element back INTO view, so on a
            short list both bars sat under the last row halfway up the sidebar
            (where the undo bar's negative bottom margin let the selection bar
            land straight on top of it). */}
        <div style={{ position: "relative", flex: 1, minHeight: 0,
          display: "flex", flexDirection: "column" }}>
        <SelectionBarSlot report={report}>
        <UndoRunnerSlot run={undoBar.run}>
        {/* The reserve that keeps the last row clear of the bars is a SPACER at
            the end of the content, never `paddingBottom` on this scroller: the
            padding would sit below the last row AND below the overlay's own
            offset, so the reserve reads twice. */}
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {/* The video's file/track metadata lives only in the library sidebar's
            Metadata tab, not here — the annotator is for tagging. */}
        {/* THE FRAMES SOMEBODY KEPT — a tab of its own, and the first one. A
            still is an ordinary image item, so it carries its own tags, groups
            and boxes; what this list is for is finding them again and getting
            back to the moment each came from.
            The whole FILM's stills, not just this frame's: a list that emptied
            itself as the playhead moved could not answer "which frames have I
            already taken", which is the question you come here with. The ones
            at the playhead are marked. */}
        {tabs.has("stills") && isVideo && (
          <div style={{ padding: "12px 14px 16px" }}>
            {sideTitle(t("Stills"), (
              <JumpBtns
                times={stillTimes}
                now={play.time}
                fps={fps}
                onJump={(d: 1 | -1) => jumpTo(stillTimes, d)}
                prevTitle={t("Jump to the previous frame with a still")}
                nextTitle={t("Jump to the next frame with a still")}
              />
            ))}
            {/* A whole frame can only be taken ONCE — a second one would dedup
                straight back onto the first — so the button says so instead of
                doing nothing. */}
            <button
              onClick={() => makeStill()}
              disabled={capturing || wholeFrameTaken}
              title={wholeFrameTaken
                ? t("This frame is already a still — it is in the list below")
                : t("Capture this whole frame as an image item you can tag")}
              style={{ ...bigBtn, opacity: capturing || wholeFrameTaken ? 0.5 : 1 }}
            >
              <Icon name="add_photo_alternate" size={16} />
              {wholeFrameTaken ? t("Frame already taken") : t("Take still")}
            </button>
            {/* A STILL EVERY N SECONDS — the other way to fill this list, for
                a film you want sampled rather than a moment you stopped at.
                Bounded by the MARKED RANGE when there is one, which is what
                makes it usable on a feature: mark the scene, sample the scene.
                Queued as a background job (each still is an ffmpeg seek plus a
                dedup probe, so a few hundred is minutes), and the reply says
                how many — counted server-side, since what "every N seconds of
                this film" comes to is one rule and this is not the place it
                lives. */}
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <button
                onClick={() => void takeEvery()}
                disabled={!!stillsJob}
                title={markedRange
                  ? t("Take a still every {n} seconds of the marked range",
                       { n: String(everySecs) })
                  : t("Take a still every {n} seconds of the whole film",
                       { n: String(everySecs) })}
                style={{ ...bigBtn, flex: 1, minWidth: 0,
                         opacity: stillsJob ? 0.5 : 1 }}
              >
                <Icon name="burst_mode" size={16} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                               whiteSpace: "nowrap" }}>
                  {stillsJob
                    ? (stillsJob.message
                       || t("Taking stills…"))
                    : markedRange
                      ? t("Every {n}s of the range", { n: String(everySecs) })
                      : t("Every {n}s", { n: String(everySecs) })}
                </span>
              </button>
              {/* The INTERVAL, behind its own control: it is a setting, not
                  the action, and a number field in the sidebar would sit
                  there being edited by nobody most of the time. */}
              <button
                onClick={() => { setEveryDraft(String(everySecs));
                                 setEveryOpen(true); }}
                title={t("How often to take one")}
                style={{ ...bigBtn, width: 32, flex: "0 0 32px",
                         justifyContent: "center", padding: 0 }}
              >
                <Icon name="tune" size={16} />
              </button>
            </div>
            {/* What the run came to, in the server's own words — or why it
                would not start. It stays until the next press rather than
                fading: it is the only place the COUNT is ever said. */}
            {everyMsg && (
              <div style={{ marginTop: 6, fontSize: "var(--fs-2)",
                            color: "var(--muted-2)" }}>
                {everyMsg}
              </div>
            )}
            {/* A still OPENS IN ITS OWN TAB, on a double-click — the grid's
                gesture for "open this picture". It used to point this whole
                window at the still and wedge a "Still tags" list under the
                film's own: half the width, none of the other sections, and a
                picture of one frame on screen while the playhead was free to
                move to another. As a tab it is simply the item, with
                everything. A single click SEEKS to the moment it came from,
                which is the other thing a row here can answer. */}
            {(stills ?? []).length === 0 ? (
              <div style={{ marginTop: 8, fontSize: "var(--fs-2)", color: "var(--muted-2)", lineHeight: 1.5 }}>
                {t("No stills from this film yet.")}
              </div>
            ) : (
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 3 }}>
                {(stills ?? []).map((st) => {
                  // A STILL IS SELECTED EXACTLY WHILE THE PLAYHEAD IS AT ITS
                  // MOMENT, and clicking one takes the playhead there. There
                  // is no second state to keep: a still IS a moment of the
                  // film, so "which one am I on" is a question the playhead
                  // already answers — and a selection of its own could
                  // disagree with the picture on screen.
                  const here = Math.abs(st.timestamp - play.time) <= 0.5 / fps;
                  return (
                    <div
                      key={`${st.item_id}:${st.timestamp}`}
                      className="hoverable"
                      onClick={() => play.seek(st.timestamp)}
                      onDoubleClick={() => openTab(st.item_id)}
                      title={`${st.crop ? t("A crop of this frame") : t("This whole frame")} — ${t("click to go to the moment, double-click to open it in its own tab")}`}
                      style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "3px 6px 3px 3px",
                        borderRadius: "var(--r-3)", cursor: "pointer",
                        border: `1px solid ${here ? "var(--accent)" : "var(--border)"}`,
                        background: rowBackground(here, "transparent"),
                      }}
                    >
                      <img
                        src={st.file_id != null ? api.thumbUrl(st.file_id) : ""}
                        alt=""
                        style={{ flex: "0 0 auto", width: 48, height: 32, objectFit: "cover", borderRadius: 4, background: "var(--panel-3)" }}
                      />
                      <span style={{ flex: 1, minWidth: 0, display: "flex",
                        flexDirection: "column", gap: 1 }}>
                        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                          color: here ? "var(--accent)" : "var(--text-2)",
                          overflow: "hidden", textOverflow: "ellipsis",
                          whiteSpace: "nowrap" }}>
                          {formatTimecode(st.timestamp, fps, true)}
                        </span>
                        <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)",
                          overflow: "hidden", textOverflow: "ellipsis",
                          whiteSpace: "nowrap" }}>
                          {st.crop ? t("Crop") : t("Frame")} · {st.width}×{st.height}
                        </span>
                      </span>
                      {/* ON HOVER, and the two are told apart by colour as well
                          as by glyph: the pencil OPENS the still to work on,
                          the bin takes it away. The bin is OUTERMOST and has
                          the row's edge padding to itself — the destructive one
                          should not sit between your pointer and anything
                          else. */}
                      <span className="row-actions" style={{ flex: "0 0 auto", gap: 4 }}>
                        <IconButton icon="edit" size={20} glyph={14} reveal="hover" tone="accent"
                          onClick={(e) => { e.stopPropagation(); openTab(st.item_id); }}
                          title={t("Open this still in its own tab")} />
                        <IconButton icon="delete" size={20} glyph={14} reveal="hover" tone="danger" color="var(--red-text)"
                          onClick={(e) => { e.stopPropagation(); setStillToRemove(st.item_id); }}
                          title={t("Remove this still")} />
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {tabs.has("tags") && (<>
        {/* THE ITEM'S OWN TAGS. On a video these are the timed ones — a film's
            tags describe moments, not regions, so they carry no boxes; the
            boxes live on stills below. The panel is the same component the
            properties sidebar uses, with its row selection controlled from
            here. */}
        <div style={{ padding: "12px 14px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            {/* "Tags" on a film too. The heading used to read "Film tags" to
                tell it from "At this frame" below — but both are the film's
                tags, and the one thing that distinguishes them is what "At
                this frame" already says about itself. */}
            <span style={{ fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text-bright)" }}>
              {t("Tags")}
            </span>
            {!isVideo && tagSel.length > 0 && (
              <button
                onClick={() => { setTagSel([]); setSelectedCids([]); }}
                title={t("Clear the selection — every box draws fully again")}
                style={{ fontSize: "var(--fs-2)", color: "var(--accent)", background: "transparent", border: "none", cursor: "pointer" }}
              >
                {t("Show all boxes")}
              </button>
            )}
          </div>
          <GroupedTags
            itemId={hostId as number}
            detail={hostItem as ItemDetail}
            fetchSuggestions={fetchTagNameSuggestions}
            hideHeader
            hideAnnotate
            selectedKeys={isVideo ? timeSel : tagSel}
            onSelectedKeys={isVideo ? setTimeSel : setTagSel}
            // On a video the tags live at the playhead get their own section
            // below, so this one holds what applies to the whole film.
            instanceFilter={isVideo ? (i) => !isTimed(i) : undefined}
            // The markers behind a tag name open the tab that edits that half
            // of it — the same jump the library sidebar's tag list offers.
            // Additive: the tag list you came FROM is the one that says which
            // tags there are, and closing it to show a person is answering a
            // question by hiding the thing that asked it.
            onShowKind={(what, tag) => {
              // SWITCHES rather than adding: the marker is a way to the row
              // that edits this half of the tag, and opening its tab beside
              // the one you were reading left both on screen with nothing
              // saying which the jump had aimed at.
              if (what === "place") { setFocusPlace(tag); pickTab("places", false); }
              else if (what === "event") { setFocusEvent(tag); pickTab("events", false); }
              else {
                if (what === "face") setFocusFace(tag); else setFocusSubject(tag);
                pickTab("subjects", false);
              }
            }}
            onChange={tagsChanged}
          />
        </div>

        {/* The film's tags AT THE PLAYHEAD: every tag whose time range covers
            the current frame, grouped like the section above (Ungrouped
            included, since that is where a new one lands). It re-reads on every
            seek, so it always describes the frame on screen. Adding here tags
            the current range/frame rather than the whole film. */}
        {isVideo && hostItem && (
          <div style={{ padding: "0 14px 16px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <span style={{ fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text-bright)" }}>{t("At this frame")}</span>
              <span style={{ flex: 1, fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>
                {formatTimecode(play.time, fps, true)}
              </span>
              <JumpBtns
                times={tagChangeTimes}
                now={play.time}
                fps={fps}
                onJump={(d: 1 | -1) => jumpTo(tagChangeTimes, d)}
                prevTitle={t("Jump to the previous frame with a different set of tags")}
                nextTitle={t("Jump to the next frame with a different set of tags")}
              />
            </div>
            <GroupedTags
              itemId={hostId as number}
              detail={hostItem}
              fetchSuggestions={fetchTagNameSuggestions}
              hideHeader
              hideAnnotate
              selectedKeys={timeSel}
              onSelectedKeys={setTimeSel}
              // The rows here are RANGES, so the filter is per range: a tag
              // live now shows the stretch that covers this frame, not every
              // stretch it has elsewhere in the film.
              // A tag made of ranges is judged per range below; one that is
              // timed only through a placement's geometry still needs the
              // playhead test, or it would sit here for the whole film.
              instanceFilter={(i) => isTimed(i) && (hasRanges(i) || liveNow(i))}
              rangeFilter={(b) => entryContains(
                { start: b.time_start as number, end: b.time_end ?? null },
                play.time, 0.5 / fps)}
              // An IMPLIED tag has no boxes of its own, so the filter above
              // cannot see it: the hierarchy section listed every implication
              // in the film whatever the playhead was doing. It is live here
              // exactly while something implying it is.
              impliedFilter={impliedLive}
              onAddInstance={addTimedTag}
              onChange={tagsChanged}
            />
          </div>
        )}

        </>)}

        {/* The library sidebar's own four lists, on the item this window is
            annotating. */}
        {itemId != null && item && (<>
          {tabs.has("subjects") && (
            <div style={{ padding: "12px 14px 0" }}>
              {sideTitle(t("Subjects"))}
              <PeopleSection
                itemId={itemId}
                detail={item}
                sel={people.subjectSel}
                // Never on a FILM: a detector reads a picture, and a film's
                // active file is not one. Its faces are worth finding on a
                // STILL taken from it, which is an ordinary image item with a
                // Subjects tab of its own.
                topAction={isVideo ? null : (
                  <AiActionButtons itemIds={[itemId]} kinds={["faces"]}
                    doneModels={item.face_models ?? []}
                    onEnqueued={() => refreshFaces()} />
                )}
                faceSel={faceSel}
                onPickFace={pickFace}
                focusTag={focusSubject}
                focusFace={focusFace}
                onFocused={() => { setFocusSubject(null); setFocusFace(null); }}
                onChange={peopleChanged}
              />
            </div>
          )}
          {tabs.has("places") && (
            <div style={{ padding: "12px 14px 0" }}>
              {sideTitle(t("Places"))}
              <PlacesSection
                itemId={itemId}
                detail={item}
                sel={people.placeSel}
                suggested={offers?.places ?? []}
                focusTag={focusPlace}
                onFocused={() => setFocusPlace(null)}
                onChange={peopleChanged}
                onAnswered={() => void refetchOffers()}
              />
            </div>
          )}
          {tabs.has("events") && (
            <div style={{ padding: "12px 14px 0" }}>
              {sideTitle(t("Events"))}
              <EventsSection
                itemId={itemId}
                detail={item}
                sel={people.eventSel}
                suggested={offers?.events ?? []}
                dated={offers?.dated ?? true}
                focusTag={focusEvent}
                onFocused={() => setFocusEvent(null)}
                onChange={peopleChanged}
                onAnswered={() => void refetchOffers()}
              />
            </div>
          )}
          {tabs.has("captions") && (
            <div style={{ padding: "12px 14px 0" }}>
              {sideTitle(t("Captions"))}
              <CaptionsSection
                itemId={itemId}
                captions={item.captions ?? null}
                multi={false}
                hideHeader
                onChange={peopleChanged}
              />
            </div>
          )}
          {tabs.has("text") && (
            <div style={{ padding: "12px 14px 0" }}>
              {sideTitle(t("Text"))}
              <TextSection
                itemId={itemId}
                detail={item}
                // Never on a FILM, the faces rule: an OCR engine reads a
                // picture, and a film's text is read on a still.
                topAction={isVideo ? null : (
                  <AiActionButtons itemIds={[itemId]} kinds={["ocr"]}
                    doneModels={item.text_models ?? []}
                    onEnqueued={() => refreshText()} />
                )}
                selectedKeys={textSel}
                onSelectedKeys={setTextSel}
                activeEngine={textEngine}
                onActiveEngine={setTextEngine}
                // The picture is right there: point at the box rather than
                // opening a crop of something already on screen.
                onHoverRegion={(r) => setTextHover(r?.id ?? null)}
                autoEditId={textAutoEdit}
                onAutoEditDone={() => setTextAutoEdit(null)}
                onChange={refreshText}
              />
            </div>
          )}
        </>)}

        {/* The reserve the bars float over: what the selection bar costs is
            permanent (it comes and goes with the selection, and the content
            must not move when it does), what the undo bar costs is added only
            while it is showing. */}
        <div style={{ height: barH + SELECTION_BAR_GAP * 2
          + (undoBar.state ? UNDO_BAR_H + 6 : 0) }} />
      </div>
      </UndoRunnerSlot>
      </SelectionBarSlot>
      {/* Inset to the same 14 px the rows are, or the bars run edge to edge in
          a column where nothing else does. `pointerEvents: none` on the frame,
          so the gap between the two is not a dead strip over the list — each
          bar takes its own clicks back. */}
      {(undoBar.state || bar) && (
        <div style={{ position: "absolute", left: 14, right: 14,
          bottom: SELECTION_BAR_GAP, zIndex: 5, pointerEvents: "none" }}>
          {undoBar.state && (
            <UndoBar
              label={undoBar.state.label}
              undone={undoBar.state.undone}
              onToggle={() => void undoBar.toggle()}
              onDismiss={undoBar.dismiss}
              t={t}
              style={{ pointerEvents: "auto" }}
            />
          )}
          {/* LONGHANDS, not `margin: 0`: the floating variant sets
              `marginBottom` to minus its own height (its way of costing the
              scroll content nothing), and a shorthand handed to React beside a
              longhand does not reliably win. */}
          {bar && <SelectionBar {...bar} t={t} floating onHeight={setBarH}
            style={{ position: "static", marginTop: 0, marginBottom: 0,
                     pointerEvents: "auto" }} />}
        </div>
      )}
      </div>
      </div>
      </div>

      {/* Group picker for an existing label — move a tag into another group
          (Ungrouped, one of the item's groups, or a brand-new one). */}
      {groupMenu && (
        <>
          <div
            onMouseDown={() => setGroupMenu(null)}
            style={{ position: "fixed", inset: 0, zIndex: 79 }}
          />
          <div
            style={{
              position: "fixed", top: groupMenu.y, left: groupMenu.x, zIndex: 80,
              minWidth: 150, maxHeight: 260, overflowY: "auto",
              background: "var(--surface-float)", border: "1px solid var(--menu-border)",
              borderRadius: "var(--r-4)", boxShadow: "var(--shadow-3)", padding: 4,
            }}
          >
            {(() => {
              const cur = boxes.find((x) => x.cid === groupMenu.cid)
                ?.labels.find((l) => l.tag === groupMenu.tag)?.group ?? null;
              const row = (gid: number | null, label: string, icon: string) => (
                <div
                  key={gid ?? "u"}
                  onMouseDown={(e) => { e.stopPropagation(); changeLabelGroup(groupMenu.cid, groupMenu.tag, gid); }}
                  style={{
                    display: "flex", alignItems: "center", gap: 8, padding: "6px 9px",
                    borderRadius: "var(--r-2)", cursor: "pointer", fontSize: "var(--fs-3)",
                    color: gid === cur ? "var(--accent)" : "var(--text-2)",
                    background: gid === cur ? "var(--accent-dim)" : "transparent",
                  }}
                >
                  <Icon name={icon} size={15} color={gid === cur ? "var(--accent)" : "var(--muted-2)"} />
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
                  {gid === cur && <Icon name="check" size={15} />}
                </div>
              );
              return (
                <>
                  {row(null, t("Ungrouped"), "label_off")}
                  {tagGroups.map((g) => row(g.id, g.name, "folder"))}
                  <div
                    onMouseDown={(e) => { e.stopPropagation(); changeLabelGroup(groupMenu.cid, groupMenu.tag, "__new__"); }}
                    style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 9px", borderRadius: "var(--r-2)", cursor: "pointer", fontSize: "var(--fs-3)", color: "var(--text-2)", borderTop: "1px solid var(--border)", marginTop: 2 }}
                  >
                    <Icon name="create_new_folder" size={15} color="var(--muted-2)" />
                    {t("New group…")}
                  </div>
                </>
              );
            })()}
          </div>
        </>
      )}

      {/* Removing a still takes an ITEM to the trash, with whatever was tagged
          on it. The Trash is the way back, and this is the sentence that says
          so before the thing happens rather than after. */}

      {stillToRemove != null && (
        <ConfirmModal t={t}
          title={t("Remove this still?")}
          body={t("It is an item of its own, so it goes to the Trash with everything tagged on it — and comes back into this list if you restore it.")}
          answer={{ label: t("Remove"), danger: true }}
          onResult={(r) => {
            const id = stillToRemove;
            setStillToRemove(null);
            if (r === "answer") void removeStill(id);
          }} />
      )}

      {/* HOW OFTEN, in its own sheet. It is one number and it is remembered,
          so it belongs out of the way of the button it configures — the
          sidebar is a list of stills, not a form. */}
      {everyOpen && (
        <ConfirmModal t={t}
          title={t("How often to take a still")}
          body={
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                autoFocus
                value={everyDraft}
                inputMode="decimal"
                onChange={(e) => setEveryDraft(
                  e.target.value.replace(/[^0-9.]/g, ""))}
                onKeyDown={(e) => { if (e.key === "Enter" && Number(everyDraft) > 0) saveEvery(); }}
                style={{ width: 90, height: 32, padding: "0 10px",
                  background: "var(--bg)", borderRadius: "var(--r-4)",
                  border: "1px solid var(--border-strong)",
                  color: "var(--text)", fontSize: "var(--fs-4)",
                  fontFamily: "var(--mono)", outline: "none" }}
              />
              <span style={{ fontSize: "var(--fs-3)", color: "var(--muted)" }}>
                {t("seconds")}
              </span>
            </div>
          }
          answer={{ label: t("Save"), disabled: !(Number(everyDraft) > 0) }}
          onResult={(r) => { if (r === "answer") saveEvery(); else setEveryOpen(false); }} />
      )}

      {/* Escape with several tabs open: window, tab, or neither. */}
      {closeAsk && (
        <ConfirmModal t={t} {...closeChoice(t, item?.name ?? hostItem.name)}
          onResult={(r) => {
            setCloseAsk(false);
            if (r === "answer") closeItemWindow();
            else if (r === "plain" && editorItemId != null) closeEditorTab(editorItemId);
          }}
        />
      )}
    </div>
  );
}

/**
 * The selected box's own time row, below the main scrubber: every placement of
 * its track drawn in the tag's colour — a span, or a tick for a single frame —
 * with the playhead marked across it. Clicking a placement picks it; the ×
 * removes it; the buttons on the right add one at the current range/frame or
 * collapse them all into a single span (what the removed "Subjects" list did).
 */
function BoxRanges({
  color, label, entries, duration, time, current, onPick, onRemove, onKeyframe, onMerge,
}: {
  color: string;
  label: string;
  entries: Box[];
  duration: number;
  time: number;
  /** cid of the placement currently selected on the canvas. */
  current: string;
  onPick: (e: Box) => void;
  onRemove: (cid: string) => void;
  onKeyframe: () => void;
  onMerge?: () => void;
}) {
  const t = useT();
  const [hover, setHover] = useState<string | null>(null);
  const pct = (t: number) => (duration > 0 ? (t / duration) * 100 : 0);
  const timed = entries.filter((e) => e.start != null);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div
        style={{ position: "relative", flex: 1, height: 16, borderRadius: 4, background: "var(--panel-2)", border: `1px solid ${color}`, overflow: "hidden" }}
      >
        <span style={{ position: "absolute", left: 5, top: 0, bottom: 0, display: "flex", alignItems: "center", fontSize: 8.5, fontFamily: "var(--mono)", color: "var(--muted-2)", pointerEvents: "none", zIndex: 2 }}>{label}</span>
        {timed.map((e) => {
          const on = e.cid === current;
          const single = e.end == null;
          return (
            <div
              key={e.cid}
              onMouseEnter={() => setHover(e.cid)}
              onMouseLeave={() => setHover((h) => (h === e.cid ? null : h))}
              onClick={() => onPick(e)}
              title={t("{range} — click to select this range", {
                range: `${fmtDuration(e.start as number)}${e.end != null ? `–${fmtDuration(e.end)}` : ""}`,
              })}
              style={{
                position: "absolute", top: 2, bottom: 2, left: `${pct(e.start as number)}%`,
                width: single ? 3 : `${Math.max(1, pct((e.end as number) - (e.start as number)))}%`,
                minWidth: 3, background: color, borderRadius: 2,
                opacity: on ? 1 : 0.5,
                boxShadow: on ? "inset 0 0 0 1px var(--on-scrim)" : undefined,
                cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "flex-end",
              }}
            >
              {hover === e.cid && timed.length > 1 && (
                <span
                  onClick={(ev) => { ev.stopPropagation(); onRemove(e.cid); }}
                  title={t("Remove this placement")}
                  style={{ display: "flex", color: "var(--on-accent)", background: "var(--scrim-1)", borderRadius: 3, cursor: "pointer" }}
                >
                  <Icon name="close" size={11} />
                </span>
              )}
            </div>
          );
        })}
        {/* Playhead, so the placements can be read against the current frame. */}
        <div style={{ position: "absolute", top: 0, bottom: 0, left: `${pct(time)}%`, width: 1.5, background: "var(--text-bright)", pointerEvents: "none", zIndex: 1 }} />
      </div>
      <button onClick={onKeyframe} title={t("Add a placement at the current range/frame")} style={miniBtn}>
        <Icon name="add" size={13} /> {t("Keyframe")}
      </button>
      {onMerge && (
        <button onClick={onMerge} title={t("Merge all placements into one span")} style={miniBtn}>
          <Icon name="merge" size={13} /> {t("Merge")}
        </button>
      )}
    </div>
  );
}


// Full-width action button, matching the library sidebar's (Annotate, Generate
// tags): icon, label, left-aligned.
/** Where "every N seconds" remembers its N — see the state that reads it. */
const EVERY_KEY = "mc.stillsEvery";

const bigBtn: React.CSSProperties = {
  width: "100%", height: 32, borderRadius: "var(--r-4)", display: "flex", alignItems: "center",
  justifyContent: "flex-start", gap: 6, padding: "0 10px",
  border: "1px solid var(--border-strong)", background: "var(--panel-2)",
  color: "var(--text-2)", cursor: "pointer", fontSize: "var(--fs-3)", fontWeight: 600,
};

// Small action button in the track placement list.
const miniBtn: React.CSSProperties = {
  height: 24, padding: "0 8px", borderRadius: "var(--r-2)", border: "1px solid var(--border-strong)",
  background: "transparent", color: "var(--text-2)", cursor: "pointer", fontSize: "var(--fs-2)",
  display: "inline-flex", alignItems: "center", gap: 3,
};

