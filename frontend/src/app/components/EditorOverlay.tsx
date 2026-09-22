import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { IconButton } from "../../shared/IconButton";
import { Loading } from "../../shared/Loading";
import { filterNumeric } from "../../shared/useNumericText";
import { useMenuDismiss } from "../../shared/useMenuDismiss";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { isTypingTarget } from "../../shared/typingTarget";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, JobKind, JobOut, TextLevel, TextRegion } from "../api";
import { quadToFile, refToFile } from "../refFrame";
import { rememberEngine, useChosenEngine } from "../text/engineChoice";
import { engineOf, enginesOf, inQuad, liveRoots, subBoxes }
  from "../text/regions";
import { useDevicePixelRatio } from "../dpr";
import { useWheel } from "../useWheel";
import { marqueeRect } from "../marqueeRect";
import { LOG_STEPS, logSliderPos, logSliderValue } from "../logSlider";
import { floodFromDistances, floodFromPixels, regionToMask, seedDistances }
  from "../floodRegion";
import { panForZoom, zoomPivot } from "../zoomPivot";
import { CACHE_MAX_PX, visibleBlit } from "../canvasBlit";
import { Adjust, NO_ADJUST, drawAdjusted, isIdentity } from "../imageAdjust";
import { blurredCanvas, blurredImage } from "../canvasBlur";
import { sharpenedImage } from "../imageSharpen";
import { growMaskBy } from "../growMask";
import { EditorMenus } from "./EditorMenu";
import { Icon } from "../../shared/Icon";
import { RefPickerOverlay } from "./RefPicker";
import { ColorPickerPopover, recordRecentColor } from "./ColorPicker";
import { useUI } from "../store";
import { APP_PREFS, BLUR_IMAGE_MAX, SHARPEN_AMOUNT_MAX, SHARPEN_RADIUS, SHARPEN_RADIUS_MAX }
  from "../prefs";
import { bumpLibrary } from "../invalidation";
import { evalExpr } from "../mathExpr";
import { checkerPattern } from "../canvasChecker";
import { CROP_ASPECTS, CUSTOM_ID, aspectDragRect, aspectRatio, clampRect, fitExtents, fitRectToAspect, resizeLocal }
  from "../cropAspect";
import type { CustomAspect } from "../cropAspect";
import { Divider, IconBtn, LabelBtn, WindowCloseBtn } from "./shared/iconButtons";
import { ItemTitle } from "./shared/ItemTitle";
import { FileChip } from "./shared/FileChip";
import { CANVAS_BAR_H, CanvasBar, CanvasBarRow } from "./shared/CanvasBars";
import { UndoRedoButtons } from "./shared/UndoRedoButtons";
import { ThemeMenu, useWindowTheme } from "./shared/ThemeMenu";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { ConfirmModal } from "../../shared/ConfirmModal";
import { RowMenu } from "./shared/RowMenu";
import { closeChoice } from "./shared/closeChoice";
import { ModeSwitch } from "./shared/ModeSwitch";
import { HeaderActions } from "./shared/HeaderActions";
import { LAYER } from "../../shared/layers";

/**
 * Canvas-based image editor. All edits mutate an offscreen pixel buffer
 * (`pixelRef`); selection lives in a separate mask canvas (`maskRef`). Rotate,
 * crop, brush and fill are applied destructively to the buffer, so saving just
 * uploads the buffer as a PNG (raster).
 */

// This window is deliberately ENGLISH throughout — nothing in it is wrapped in
// t(), and a German ⋯ menu between "Save" and "Undo" would read worse than the
// source. The shared chrome REQUIRES a translator (optional was a silent-
// English hole), so the choice is stated here rather than made by omission.
// Placeholders still fill: CloseChoice's strings carry a {name}.
const english = (s: string, vars?: Record<string, string>): string =>
  vars ? s.replace(/\{(\w+)\}/g, (m, k) => vars[k] ?? m) : s;

type Tool = "hand" | "zoom" | "select" | "lasso" | "text" | "wand" | "brush" | "erase" | "blur" | "fill" | "pipette" | "crop";
/** The marquee and the lasso are ONE tool with two shapes underneath — the
 *  same modes, the same commit, the same everything the bar offers. Only
 *  which gesture draws the outline differs, which is why they are two
 *  entries in the palette and one branch in the code. */
const isSelectTool = (t: Tool) => t === "select" || t === "lasso";
/**
 * THE TOOLS WHOSE PROPERTIES BAR HAS ANYTHING IN IT.
 *
 * The bar was drawn for everything but the hand, which is an exclusion list of
 * one — and the pipette, which has no properties either, was never added to
 * it. An empty bar is not nothing on screen: it is its own padding and border,
 * 8 px wide and 42 tall, which over the picture reads as a stray black mark at
 * the top of the canvas. Listed positively, so a tool with no properties is
 * silent by DEFAULT and the next one added cannot inherit the bug.
 * `editorPropsBar.test.ts` holds the list to what the bar actually renders.
 */
const TOOLS_WITH_PROPS: readonly Tool[] = [
  "select", "lasso", "text", "wand", "brush", "erase", "blur", "fill", "crop", "zoom",
];
type SelStyle = "rect" | "ellipse" | "lasso";
type SelMode = "replace" | "extend" | "subtract" | "intersect";
/**
 * HOW A NEW SHAPE MEETS THE SELECTION ALREADY THERE — the one table, drawn by
 * the three tools that make a selection (the marquee, the lasso, the text
 * tool) and the wand. It was written out three times with the icons repeated
 * in each, which is how the marquee's buttons came to be titled `replace`,
 * `extend`, `subtract` in raw lowercase while the other two said it in words.
 *
 * INTERSECT is Shift+Alt, following Clip Studio Paint, where the pair has
 * meant "select from current selection" for as long as the other two have
 * meant add and remove.
 */
/**
 * WHICH MODE A PRESS ASKS FOR: the bar's, unless a modifier overrides it for
 * this one gesture. The PAIR is read before either key alone, or Shift+Alt
 * would come out as "extend" and the second key would do nothing.
 *
 * Only what is held AT THE PRESS reaches this — during the drag the same two
 * keys mean the SHAPE (`marqueeRect`), which is what lets one key carry both
 * jobs.
 */
const modeFor = (e: { shiftKey: boolean; altKey: boolean }, bar: SelMode): SelMode =>
  e.shiftKey && e.altKey ? "intersect"
    : e.shiftKey ? "extend" : e.altKey ? "subtract" : bar;

/** What every tip-size slider spans, in pixels. */
const SIZE_MIN = 1, SIZE_MAX = 200;

const SEL_MODES: { id: SelMode; icon: string; title: string }[] = [
  { id: "replace", icon: "swap_horiz", title: "Replace selection" },
  { id: "extend", icon: "add", title: "Add to selection (Shift)" },
  { id: "subtract", icon: "remove", title: "Remove from selection (Alt)" },
  { id: "intersect", icon: "join_inner", title: "Keep only the overlap (Shift+Alt)" },
];
interface Rect { x: number; y: number; w: number; h: number } // normalized 0..1

// Crop-to-new-item tabs before their FIRST save: the item is only created on
// save, so until then the tab is a "pending crop" keyed by a negative id.
// Holds the cropped pixels plus everything the eventual cropToItem call needs.
const pendingCrops = new Map<number, {
  canvas: HTMLCanvasElement;
  sourceItemId: number;
  sourceFileId: number;
  // Crop region within the source FILE's frame (null for rotated crops).
  box: { x: number; y: number; w: number; h: number } | null;
}>();
let nextPendingId = -1;

// The selection clipboard for ⌘/Ctrl+X/C/V — the cut/copied pixels plus the
// selection shape they were lifted with. Module-level so it survives tab
// switches within one editor window (each editor window has its own).
let SEL_CLIPBOARD: { canvas: HTMLCanvasElement; mask: HTMLCanvasElement } | null = null;

// A floating selection: the pixels of the current selection lifted off the
// buffer so they can be moved / scaled / rotated (Photoshop-style), then baked
// back down. `canvas` holds the cut pixels at their original bbox size (image
// px); the live transform is center + per-axis scale + rotation about center.
interface Floating {
  canvas: HTMLCanvasElement;
  // The lifted SELECTION shape (bbox-sized cut of the mask). The ants outline
  // and the committed mask derive from this, never from the content's alpha —
  // otherwise transparent pixels inside the selection would grow their own
  // outline and drop out of the re-derived selection.
  mask: HTMLCanvasElement;
  w0: number; h0: number;      // original bbox size (image px)
  cx: number; cy: number;      // center in image coords
  homeX: number; homeY: number; // original bbox top-left (image px)
  scaleX: number; scaleY: number;
  rot: number;                 // radians
  transforming: boolean;       // show the transform box + handles
  keep: boolean;               // copy mode: the original pixels stay in place
  pasted?: boolean;            // came from the clipboard — no original underneath
  // The bbox of the buffer as it was BEFORE the lift, for Keep original. The
  // hole is punched with the mask, so a soft or anti-aliased edge leaves the
  // pixel partly there — and drawing the lifted copy back over that does not
  // add up to the original (two partial alphas composite to less than one):
  // a blurred selection left a grey veil and a round one a thin ring. Keep
  // original therefore puts THESE pixels back, exactly.
  orig?: HTMLCanvasElement;
}

/** One undo/redo checkpoint of the destructive editor state. */
interface Snap {
  pixels: HTMLCanvasElement;
  mask: HTMLCanvasElement;
  dims: { w: number; h: number };
  hasSelection: boolean;
  // Identity of the buffer state this snapshot holds. The Save button is
  // enabled iff the CURRENT state's id differs from the last saved one, so
  // undoing back to the saved state disables it again.
  id: number;
}

/** Inputs nobody TYPES into: a slider, a tick box, a colour well. */
const NON_TEXT_INPUTS = new Set(["range", "checkbox", "radio", "button", "submit", "reset", "color", "file", "image"]);
/** A control that took focus from a click and holds no text — a button, a
 *  slider, a tick box. */
function isNonTextControl(el: EventTarget | null): el is HTMLElement {
  if (el instanceof HTMLButtonElement) return true;
  return el instanceof HTMLInputElement && NON_TEXT_INPUTS.has(el.type);
}
/**
 * WHETHER A KEY BELONGS TO A FIELD RATHER THAN TO THE EDITOR.
 *
 * `isTypingTarget` answers yes for every `<input>`, and a SLIDER is one: a
 * click on the brush's Size or Hardness track focuses it, and from then on B,
 * E, Space, ⌘Z and the rest all stood down until something else took the
 * focus — "the shortcuts stop working after I touch a slider". Nothing is
 * typed into a slider, so only its own arrow keys stay with it.
 */
function typingInEditor(e: KeyboardEvent): boolean {
  if (!isTypingTarget(e)) return false;
  const el = e.target;
  if (el instanceof HTMLInputElement && NON_TEXT_INPUTS.has(el.type)) {
    return el.type === "range" && /^(Arrow|Home$|End$|Page)/.test(e.key);
  }
  return true;
}

function cloneCanvas(src: HTMLCanvasElement): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = src.width;
  c.height = src.height;
  c.getContext("2d")!.drawImage(src, 0, 0);
  return c;
}

/**
 * A NEW CANVAS, PAINTED UNDER A TRANSFORM THAT CANNOT ESCAPE IT.
 *
 * A canvas has ONE 2D context for its whole life: `getContext("2d")` hands
 * back the same object every time, with whatever transform was last left on
 * it. So a function that rotates or translates a context to draw into it, and
 * then hands the canvas on, has changed the coordinates of every later draw
 * into that canvas by anyone — and the crop did exactly that. Afterwards a
 * brush stroke, an erase, an inpaint result, a blur stamp and an adjustment
 * all landed shifted by the crop's own inset: measured, a stroke painted at
 * (380, 465) put its pixels at (163, 66), jammed against the corner.
 *
 * (The MASK escaped it by luck: the crop resizes that canvas, and setting a
 * canvas's width or height resets its context to defaults.)
 *
 * So the transform is applied inside a `save`/`restore` pair here, once,
 * rather than being something each site has to remember to undo.
 */
function paintedCanvas(w: number, h: number,
                       paint: (c: CanvasRenderingContext2D) => void): HTMLCanvasElement {
  const out = document.createElement("canvas");
  out.width = Math.max(1, Math.round(w));
  out.height = Math.max(1, Math.round(h));
  const c = out.getContext("2d")!;
  c.save();
  paint(c);
  c.restore();
  return out;
}

/** The eight neighbours, which are the structuring element below: growing by
 *  one takes in every pixel touching the mask, corners included. */
/** The text tool's outlines, in the ANNOTATOR's text colour — the same green
 *  a text box wears on the other half of this window, because it is the same
 *  box. Spelled as a literal rather than `var(--green)`: this is canvas
 *  drawing, where a CSS variable resolves to nothing and the stroke silently
 *  comes out black. Translucent, so a page of them reads as a hint over the
 *  picture rather than a mesh laid on it. */
/** A PORTALLED MENU HAS TO CLEAR THE ITEM WINDOW. The editor is an overlay
 *  at z-index 300 (`ItemWindow`), and a menu portalled to `document.body` is
 *  its SIBLING — so the 90/91 these two used put them behind the very window
 *  they belong to: rendered, measurable, and completely covered. That is the
 *  whole of "the Detect text button does not open a menu". `AnchoredDropdown`
 *  (every other portalled menu in the app) sits at 1000 for this reason; the
 *  two here now say the same number out loud. */
const MENU_Z = LAYER.popover;

const TEXT_BOX_STROKE = "rgba(93, 176, 117, 0.75)";

/** The box levels a reading can hold, as the level switch says them. Short
 *  words rather than icons: glyphs that all mean "a rectangle round some
 *  text" are glyphs nobody can tell apart.
 *
 *  WORD IS NOT IN HERE. The switch's first option is the SMALLEST box each
 *  piece of text has, which on every engine that gives words IS the word —
 *  so it is simply called Word, and a second entry meaning the same thing
 *  for the same reading was two buttons doing one job. What the levels below
 *  add is the coarser answers. */
const LEVEL_LABEL: Record<string, string> = {
  char: "Aa", line: "Line", block: "Block",
};
const LEVEL_TITLE: Record<string, string> = {
  char: "Character boxes", line: "Line boxes", block: "Whole blocks",
};

const TOOLS: { id: Tool; icon: string; name: string; key: string }[] = [
  { id: "select", icon: "select", name: "Select", key: "M" },
  // The lasso is its own tool rather than a style inside Select: it is the
  // one of the three that is a different GESTURE (drag to draw, click to
  // place corners) rather than a different shape, and a shape picker is a
  // poor place to keep a mode you switch to as often as this one.
  { id: "lasso", icon: "gesture", name: "Lasso", key: "L" },
  // Offered on every picture: with nothing read yet its bar runs the OCR
  // engines, and once there is a reading it selects from it (`textLeaves`).
  { id: "text", icon: "abc", name: "Select text", key: "T" },
  { id: "wand", icon: "auto_fix_normal", name: "Wand", key: "W" },
  { id: "brush", icon: "brush", name: "Brush", key: "B" },
  { id: "erase", icon: "ink_eraser", name: "Erase", key: "E" },
  { id: "blur", icon: "water_drop", name: "Blur", key: "U" },
  { id: "fill", icon: "format_color_fill", name: "Fill", key: "G" },
  // Picks the colour under the pointer off the BUFFER into the paint colour
  // (Alt: the background colour); a drag keeps picking.
  { id: "pipette", icon: "colorize", name: "Pipette", key: "I" },
  { id: "crop", icon: "crop", name: "Crop", key: "C" },
  { id: "hand", icon: "back_hand", name: "Hand", key: "H" },
  { id: "zoom", icon: "zoom_in", name: "Zoom", key: "Z" },
];

/**
 * THE THREE LIVE EFFECTS, WHICH ARE ONE THING WITH THREE SETS OF NUMBERS ON
 * IT: the four adjustments, the blur and the sharpen. Each is previewed on
 * the full-resolution buffer from a snapshot taken when its panel opened,
 * each is confined to the selection where there is one, and each is applied
 * as one undoable step — so they share the panel (`EffectPanel`), the
 * snapshot, the preview and the commit, and differ only here.
 */
type Effect =
  | { kind: "adjust"; adjust: Adjust }
  | { kind: "blur"; radius: number }
  | { kind: "sharpen"; radius: number; amount: number };

/** Whether `e` would change nothing — Reset has nothing to do, and OK writes
 *  no undo step. A sharpen's RADIUS is not part of the answer: at 0% there is
 *  nothing to be the radius of. */
const effectIsNeutral = (e: Effect): boolean =>
  e.kind === "adjust" ? isIdentity(e.adjust)
    : e.kind === "blur" ? e.radius < 1
      : e.amount < 1;

/** What a panel opens on. Adjustments open neutral because their four
 *  numbers are four questions and none of them is asked yet; the blur and
 *  the sharpen open on what they were last used at and preview it straight
 *  away, because the number IS the question and a panel that opened neutral
 *  would make Reset and opening it the same thing. */
const freshEffect = (kind: Effect["kind"]): Effect =>
  kind === "adjust" ? { kind, adjust: { ...NO_ADJUST } }
    : kind === "blur" ? { kind, radius: APP_PREFS.blurImagePx.read() }
      : { kind, radius: APP_PREFS.sharpenRadiusPx.read(),
          amount: APP_PREFS.sharpenAmount.read() };

/** An applied effect's numbers are the next one's starting point. */
const rememberEffect = (e: Effect): void => {
  if (e.kind === "blur") APP_PREFS.blurImagePx.write(e.radius);
  if (e.kind === "sharpen") {
    APP_PREFS.sharpenAmount.write(e.amount);
    APP_PREFS.sharpenRadiusPx.write(e.radius);
  }
};

/** What Reset takes it to: neutral, keeping anything that is not a strength
 *  (a sharpen at 0% still has the radius on screen to go back up from). */
const resetEffect = (e: Effect): Effect =>
  e.kind === "adjust" ? { kind: "adjust", adjust: { ...NO_ADJUST } }
    : e.kind === "blur" ? { kind: "blur", radius: 0 }
      : { ...e, amount: 0 };

const EFFECT_PANEL: Record<Effect["kind"], { icon: string; title: string }> = {
  adjust: { icon: "tune", title: "Adjustments" },
  blur: { icon: "lens_blur", title: "Blur" },
  sharpen: { icon: "deblur", title: "Sharpen" },
};

/** One row of `EffectPanel`: a slider, what it reads as, and the two ways it
 *  is moved. */
interface EffectSlider {
  key: string; label: string; min: number; max: number; value: number;
  /** The value as it reads on screen, sign and unit and all. */
  text: string;
  onChange: (v: number) => void;
  /** Double-click: back to this slider's own resting value. */
  onRest: () => void;
}

/** The rows `e` puts on the panel. `to` takes the effect the row asks for —
 *  a slider never writes its own state, so what is on screen and what is
 *  being previewed cannot come apart. */
function effectSliders(e: Effect, to: (next: Effect) => void): EffectSlider[] {
  if (e.kind === "adjust") {
    return ([
      ["brightness", "Brightness", -100, 100],
      ["contrast", "Contrast", -100, 100],
      ["saturation", "Saturation", -100, 100],
      ["hue", "Hue", -180, 180],
    ] as const).map(([key, label, min, max]) => ({
      key, label, min, max, value: e.adjust[key],
      text: `${e.adjust[key] > 0 ? "+" : ""}${e.adjust[key]}${key === "hue" ? "°" : ""}`,
      onChange: (v: number) => to({ kind: "adjust", adjust: { ...e.adjust, [key]: v } }),
      onRest: () => to({ kind: "adjust", adjust: { ...e.adjust, [key]: 0 } }),
    }));
  }
  if (e.kind === "blur") {
    return [{
      key: "radius", label: "Radius", min: 0, max: BLUR_IMAGE_MAX,
      value: e.radius, text: `${e.radius} px`,
      onChange: (v: number) => to({ ...e, radius: v }),
      onRest: () => to({ ...e, radius: 0 }),
    }];
  }
  // Sharpen: the STRENGTH first — it is what somebody reaches for — and the
  // size of the detail it lifts under it. A radius has no neutral to
  // double-click back to, so it goes back to the one it starts at.
  return [
    { key: "amount", label: "Amount", min: 0, max: SHARPEN_AMOUNT_MAX,
      value: e.amount, text: `${e.amount} %`,
      onChange: (v: number) => to({ ...e, amount: v }),
      onRest: () => to({ ...e, amount: 0 }) },
    { key: "radius", label: "Radius", min: 1, max: SHARPEN_RADIUS_MAX,
      value: e.radius, text: `${e.radius} px`,
      onChange: (v: number) => to({ ...e, radius: v }),
      onRest: () => to({ ...e, radius: SHARPEN_RADIUS }) },
  ];
}

// Custom tool cursors (Photoshop-style): tiny inline SVGs with a dark outline
// so they read on any image.
//
// THE HOTSPOT IS THE PIXEL THE TOOL ACTS ON, and every one of these has to
// say where that is in its own drawing: the loupes' is the centre of the
// LENS, the wand's the sparkle at the TIP of the stick (which is why the
// stick runs away down-right), the bucket's the tip of the POUR — not the
// bucket — and the crop's and the rotate's the centre of their symbol,
// those two being about an area rather than a point. Getting it wrong is
// invisible in every test and in every screenshot (a screenshot does not
// capture the cursor): it shows up only as a tool that acts a few pixels
// away from where it is aimed. The brush, eraser and blur have no cursor at
// all — `cursor: none` plus the DOM ring centred on the pointer — and the
// selection tools, the text tool and the pipette use the native crosshair,
// whose hotspot is its middle.
const svgCursor = (svg: string, hx: number, hy: number, fallback: string) =>
  `url("data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">${svg}</svg>`
  )}") ${hx} ${hy}, ${fallback}`;
const _LOUPE = (sign: string) =>
  `<g fill="none" stroke="black" stroke-width="3.6" stroke-linecap="round"><circle cx="9" cy="9" r="5.5"/><line x1="13.2" y1="13.2" x2="19" y2="19"/>${sign}</g>` +
  `<g fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round"><circle cx="9" cy="9" r="5.5"/><line x1="13.2" y1="13.2" x2="19" y2="19"/>${sign}</g>`;
const CURSOR_ZOOM_IN = svgCursor(
  _LOUPE('<line x1="6.5" y1="9" x2="11.5" y2="9"/><line x1="9" y1="6.5" x2="9" y2="11.5"/>'),
  9, 9, "zoom-in");
const CURSOR_ZOOM_OUT = svgCursor(
  _LOUPE('<line x1="6.5" y1="9" x2="11.5" y2="9"/>'), 9, 9, "zoom-out");
// Paint bucket: the hotspot is the TIP OF THE POUR — the drop beside the
// bucket ends at (18.5, 17.9) and that is where the paint lands, so that is
// the pixel the flood fills from. It used to be (10, 17), the bucket's own
// bottom corner, which put the bucket body itself over the pointer: the
// cursor read as centred on the click and the paint fell somewhere down and
// to the right of whatever it was aimed at.
const CURSOR_FILL = svgCursor(
  `<g stroke="black" stroke-width="3.4" fill="none" stroke-linejoin="round"><path d="M8 3 L16 11 L10 17 L3 10 Z"/><path d="M18.5 13.5 q2 2.8 0 4.4 q-2 -1.6 0 -4.4"/></g>` +
  `<g stroke="white" stroke-width="1.6" fill="white" stroke-linejoin="round"><path d="M8 3 L16 11 L10 17 L3 10 Z"/><path d="M18.5 13.5 q2 2.8 0 4.4 q-2 -1.6 0 -4.4"/></g>`,
  18, 18, "crosshair");
const CURSOR_ROTATE = svgCursor(
  `<g fill="none" stroke="black" stroke-width="3.6" stroke-linecap="round"><path d="M17 11 a6 6 0 1 1 -3 -5.2"/><path d="M14.5 2.5 L14.5 6.5 L10.5 6.2" stroke-linejoin="round"/></g>` +
  `<g fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round"><path d="M17 11 a6 6 0 1 1 -3 -5.2"/><path d="M14.5 2.5 L14.5 6.5 L10.5 6.2" stroke-linejoin="round"/></g>`,
  11, 11, "grab");
const CURSOR_CROP = svgCursor(
  `<g fill="none" stroke="black" stroke-width="3.6" stroke-linecap="square"><path d="M6 2 V16 H20"/><path d="M2 6 H16 V20"/></g>` +
  `<g fill="none" stroke="white" stroke-width="1.8" stroke-linecap="square"><path d="M6 2 V16 H20"/><path d="M2 6 H16 V20"/></g>`,
  11, 11, "crosshair");
// Magic wand: the stick runs down-right, so its sparkling TIP sits on the
// hotspot — the pixel the flood select seeds from.
const _WAND = `<line x1="20" y1="20" x2="9" y2="9"/><path d="M5 1.5 V8.5 M1.5 5 H8.5"/>`;
const CURSOR_WAND = svgCursor(
  `<g fill="none" stroke="black" stroke-width="3.6" stroke-linecap="round">${_WAND}</g>` +
  `<g fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round">${_WAND}</g>`,
  5, 5, "crosshair");

export function EditorOverlay() {
  const { editorItemId, editorTabs, setEditorItem, closeEditorTab,
          closeItemWindow, setEditorMode } = useUI();
  const qc = useQueryClient();

  // The item window is an overlay, so closing it is closing the overlay.
  const closeEditor = useCallback(() => { closeItemWindow(); }, [closeItemWindow]);
  // Run `proceed` to close, but if there are unsaved edits first ask the user to
  // save / discard / cancel (via the modal below).
  const guardedClose = useCallback((proceed: () => void,
                                    going: "close" | "leave" = "close") => {
    if (dirtyRef.current) setClosePrompt({ proceed, going });
    else proceed();
  }, []);
  // The OS window-close (the browser's own X) can't show our 3-way prompt, so
  // fall back to the browser's native "unsaved changes" confirmation — also
  // when a not-yet-saved pending-crop tab is open (its content only exists
  // in this window).
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current || pendingCrops.size > 0) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);
  const isPending = editorItemId != null && editorItemId < 0;
  const { data: item } = useQuery({
    queryKey: ["item", editorItemId],
    queryFn: () => api.item(editorItemId as number),
    enabled: editorItemId != null && editorItemId >= 0,
  });
  // WHAT THE PAGE SAYS, for the text-select tool: the same reading the Text
  // tab shows, so the two windows can never point at different boxes. Fetched
  // for any item that has one (`text_count`) rather than only while the tool
  // is active — the tool's presence in the palette depends on the answer.
  const { data: textTree } = useQuery({
    queryKey: ["text", editorItemId],
    queryFn: () => api.itemText(editorItemId as number),
    enabled: editorItemId != null && editorItemId >= 0
      && (item?.text_count ?? 0) > 0,
  });

  // Offscreen buffers.
  const pixelRef = useRef<HTMLCanvasElement>(document.createElement("canvas"));
  const maskRef = useRef<HTMLCanvasElement>(document.createElement("canvas"));
  const viewRef = useRef<HTMLCanvasElement>(null);
  const antsRef = useRef<HTMLCanvasElement>(null);
  const canvasBoxRef = useRef<HTMLDivElement>(null);

  // THE TOOL OUTLIVES THE WINDOW. A tool is the job in hand — cropping a
  // hundred scans, painting out a hundred logos — and the editor is opened
  // once per picture, so starting every window on the hand tool made the
  // first gesture of each of them be picking the tool again. Checked against
  // `TOOLS` here rather than by a closed list in `prefs.ts`: this is where
  // the list lives, and a tool that has been renamed away reads as the hand.
  const [tool, setTool] = useState<Tool>(() => {
    const saved = APP_PREFS.editorTool.read();
    return TOOLS.some((t) => t.id === saved) ? (saved as Tool) : "hand";
  });
  // Written from an EFFECT rather than at the setters: the spring-loaded keys
  // (hold B to paint, release to go back) set the tool twice for one gesture,
  // and `setTool` is called from five places besides the palette.
  useEffect(() => { APP_PREFS.editorTool.write(tool); }, [tool]);
  // Held-key tool overrides (Photoshop-style): Space = temporary hand tool;
  // Alt flips the zoom tool to zoom-out (and its cursor to the minus loupe).
  const [spaceHand, setSpaceHand] = useState(false);
  const [altHeld, setAltHeld] = useState(false);
  const [shiftHeld, setShiftHeld] = useState(false);
  /**
   * THE MODE THE GESTURE IN FLIGHT IS USING, or null between gestures.
   *
   * The segmented control is a readout as well as a setting: with a modifier
   * held it shows what a press would do NOW, so the keys can be checked
   * against the bar rather than remembered. Once a gesture starts that has to
   * stop moving — the mode was decided at the press and cannot change, and the
   * same keys mean the SHAPE from then on, so a control still following them
   * would report the opposite of the truth halfway through a drag.
   */
  const [gestureMode, setGestureMode] = useState<SelMode | null>(null);
  // Every setting below is REMEMBERED across windows (`APP_PREFS`), written
  // from effects so the setters stay plain.
  const [color, setColor] = useState(() => APP_PREFS.editorColor.read() || "#ffffff");
  // Brush tip (size/hardness) kept separately per painting tool, so switching
  // between brush and blur restores each tool's own tip.
  const [tips, setTips] = useState(() => APP_PREFS.editorTips.read() ?? {
    brush: { size: 40, hardness: 80 },
    erase: { size: 40, hardness: 80 },
    blur: { size: 60, hardness: 60 },
  });
  const setTip = (key: "brush" | "erase" | "blur", patch: Partial<{ size: number; hardness: number }>) =>
    setTips((t) => ({ ...t, [key]: { ...t[key], ...patch } }));
  // Secondary / background color: what "removing" (erase, Delete-fill) paints.
  // null = transparent — erasing then truly knocks out to transparency.
  const [bgColor, setBgColor] = useState<string | null>(() => APP_PREFS.editorBgColor.read() || null);
  // Which swatch the custom color-picker popover is open for.
  const [pickerFor, setPickerFor] = useState<null | "fg" | "bg">(null);
  // The foreground swatch, named to its picker so a press on it toggles
  // rather than reading as a press outside.
  const fgSwatch = useRef<HTMLButtonElement>(null);
  // Blur-tool strength: the gaussian radius (px) applied per stamp.
  const [blurStrength, setBlurStrength] = useState(() => APP_PREFS.editorBlurStrength.read());
  // Color tolerance (0–100 → 0–255 per channel) of the fill and wand tools.
  // REMEMBERED, like the wand's Grow below: a tolerance dialled in by dragging
  // is an answer about the pictures being worked on, and the pictures being
  // worked on are usually a job rather than one file (`APP_PREFS`).
  const [fillTolerance, setFillTolerance] = useState(() => APP_PREFS.fillTolerance.read());
  const [wandTolerance, setWandTolerance] = useState(() => APP_PREFS.wandTolerance.read());
  // How a wand click merges with the current selection (Shift/Alt override it
  // per click, exactly like the select tool's marquee modes).
  const [wandMode, setWandMode] = useState<SelMode>(() => APP_PREFS.editorWandMode.read());
  // HOW FAR THE WAND'S OWN FIND IS GROWN BEFORE IT JOINS THE SELECTION, in
  // whole pixels; negative shrinks it. It applies to the NEW region ALONE —
  // a flood stops a pixel short of an edge it was never going to cross, and
  // growing by one or two is what closes that gap — so extending a selection
  // grows only the part being added, and what was already selected is left
  // exactly as it stands. (Growing the WHOLE selection is the Selection
  // menu's Grow/Shrink, which is this same morphology over the mask.)
  const [wandGrow, setWandGrow] = useState(() => APP_PREFS.wandGrow.read());
  // Written where they are SETTLED rather than at each call site: the drag's
  // release sets a tolerance too (`endFlood`), and a setter that persisted
  // only when a slider moved would forget the one somebody dialled in by hand.
  useEffect(() => { APP_PREFS.fillTolerance.write(fillTolerance); }, [fillTolerance]);
  useEffect(() => { APP_PREFS.wandTolerance.write(wandTolerance); }, [wandTolerance]);
  useEffect(() => { APP_PREFS.wandGrow.write(wandGrow); }, [wandGrow]);
  // Grow / Shrink / Blur-selection dialog (opened from the Selection menu).
  const [growShrink, setGrowShrink] = useState<null | "grow" | "shrink" | "blur">(null);
  // The marquee's shape. The lasso tool IS a style, so it answers for
  // itself and everything below goes on reading one `selStyle`.
  const [marqueeStyle, setMarqueeStyle] = useState<Exclude<SelStyle, "lasso">>(() => APP_PREFS.editorMarquee.read());
  const selStyle: SelStyle = tool === "lasso" ? "lasso" : marqueeStyle;
  const [selMode, setSelMode] = useState<SelMode>(() => APP_PREFS.editorSelMode.read());
  // Whether a lifted selection leaves its original in place (the transform's
  // Keep original), carried from one float to the next.
  const keepOriginalRef = useRef(APP_PREFS.editorKeepOriginal.read());
  useEffect(() => { APP_PREFS.editorColor.write(color); }, [color]);
  useEffect(() => { APP_PREFS.editorBgColor.write(bgColor ?? ""); }, [bgColor]);
  useEffect(() => { APP_PREFS.editorTips.write(tips); }, [tips]);
  useEffect(() => { APP_PREFS.editorBlurStrength.write(blurStrength); }, [blurStrength]);
  useEffect(() => { APP_PREFS.editorWandMode.write(wandMode); }, [wandMode]);
  useEffect(() => { APP_PREFS.editorMarquee.write(marqueeStyle); }, [marqueeStyle]);
  useEffect(() => { APP_PREFS.editorSelMode.write(selMode); }, [selMode]);
  const [hasSelection, setHasSelection] = useState(false);
  // Whether the buffer has unsaved edits since the last load/save — gates the
  // Save button and triggers the save/discard/cancel prompt on close.
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  // Pending close request awaiting the user's save/discard/cancel choice.
  // `going` is what the prompt is ABOUT — closing the tab, or leaving the
  // edit half for the annotate one. Same three answers, different sentence:
  // "before closing?" over a window that is not closing is the prompt telling
  // you something that is not true.
  const [closePrompt, setClosePrompt] = useState<
    null | { proceed: () => void; going?: "close" | "leave" }>(null);
  // Window-or-tab question, asked when the window is closed with several open.
  const [closeAsk, setCloseAsk] = useState(false);
  // Whole-editor close in progress: every tab's unsaved state is guarded ONE
  // BY ONE (the active buffer first, then each not-yet-saved pending-crop tab
  // — the only other tabs that hold unsaved content). Each stop shows the
  // save/discard/cancel prompt; Cancel aborts the remaining sequence.
  const closingRef = useRef(false);
  // Both ends on the dim: this prompt sits over a picture and its own text,
  // and dismissing it is what continues editing.
  const closeStepRef = useRef<() => void>(() => {});
  const closeGuardedAll = useCallback(() => {
    closingRef.current = true;
    closeStepRef.current();
  }, []);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dims, setDims] = useState({ w: 1, h: 1 });
  const [cropRect, setCropRect] = useState<Rect | null>(null);
  const [cropAngle, setCropAngle] = useState(0);
  // The shape the crop is held to, as an id from `cropAspect.CROP_ASPECTS`.
  // A TOOL SETTING, like the brush's size: it outlives the rectangle and the
  // tab, because "I am cropping these to 16:9" is a fact about the job rather
  // than about one picture.
  const [cropAspectId, setCropAspectId] = useState(() => {
    const saved = APP_PREFS.editorCropAspect.read();
    return CROP_ASPECTS.some((a) => a.id === saved) ? saved : "free";
  });
  useEffect(() => { APP_PREFS.editorCropAspect.write(cropAspectId); }, [cropAspectId]);
  // A ratio nothing in the list offers, as the two fields hold it — TEXT,
  // because a field halfway through being typed into has an empty side and
  // a lone "." in it, and a number can hold neither.
  const [cropCustom, setCropCustom] = useState<CustomAspect>(() => APP_PREFS.editorCropCustom.read());
  useEffect(() => { APP_PREFS.editorCropCustom.write(cropCustom); }, [cropCustom]);
  // The ratio it stands for, in pixels — null while the crop is free. Derived
  // rather than stored, so "Original" follows a resize and the typed pair
  // takes effect on the keystroke that completes it.
  const cropAspect = aspectRatio(cropAspectId, dims, cropCustom);
  // Zoom-tool drag marquee, in image pixels (drawn like the crop rect).
  const [zoomRect, setZoomRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  // Which live effect is open (see `Effect`), null = none. The panel floats
  // over the canvas rather than sitting in a modal, so the picture can still
  // be panned and zoomed while the sliders are open — judging one of these
  // means looking at the part of the picture it matters in.
  const [effect, setEffect] = useState<Effect | null>(null);
  // The buffer as it was when the panel opened; only one is ever open, and
  // opening one commits the other.
  const effectBase = useRef<HTMLCanvasElement | null>(null);
  // Error banner for editor-menu AI actions (apply/detect failures).
  const [opErr, setOpErr] = useState("");
  // Which of the item's files is loaded into the buffer; null = the active
  // file. Set from the header's file-name menu; reset on item switch.
  const [fileOverride, setFileOverride] = useState<number | null>(null);
  // The Save button's chevron menu (revert to saved / discard & close).
  const [busy, setBusy] = useState(false);
  const [box, setBox] = useState({ w: 800, h: 500 });
  const [loaded, setLoaded] = useState(false);
  // Editor theme: follow the app, or force light/dark for this window. The
  // shared hook owns the persistence + <html data-theme> stamping, restored on
  // unmount.
  const [edTheme, setEdTheme] = useWindowTheme();
  // Floating (moved / transformed) selection, if any.
  // The floating selection. floatRef is the SOURCE OF TRUTH (drag updates
  // are ref-only so a mousemove never waits on a React render); the state
  // mirror only drives UI (props bar) on lift/commit/cancel/mode changes.
  const [floating, setFloating] = useState<Floating | null>(null);
  const floatRef = useRef<Floating | null>(null);
  // Cursor override while hovering a transform handle / the draggable area.
  const [floatCursor, setFloatCursor] = useState<string | null>(null);

  // Undo / redo history of destructive edits.
  const undoStack = useRef<Snap[]>([]);
  const redoStack = useRef<Snap[]>([]);
  const [histVer, setHistVer] = useState(0);
  // Buffer-state identity (see Snap.id): every fresh mutation mints a new id;
  // undo/redo restore old ids. Saved-state comparison drives the Save button.
  const stateId = useRef(0);
  const nextStateId = useRef(1);
  const savedStateId = useRef(0);
  // The buffer's region within the loaded source file, as un-saved crops narrow
  // it. Null once a *rotated* crop happens (can't be expressed as an axis box),
  // in which case tag-box alignment is skipped for that save.
  const cropAcc = useRef<{ x: number; y: number; w: number; h: number } | null>({ x: 0, y: 0, w: 1, h: 1 });

  // ---- load the source image into the pixel buffer ----
  useEffect(() => { setFileOverride(null); }, [editorItemId]);
  // A pending crop-to-new-item tab loads its stashed pixels instead of a
  // file; it starts DIRTY (the item doesn't exist until the first save).
  useEffect(() => {
    if (editorItemId == null || editorItemId >= 0) return;
    const pend = pendingCrops.get(editorItemId);
    if (!pend) return;
    setLoaded(false);
    const px = pixelRef.current;
    px.width = pend.canvas.width;
    px.height = pend.canvas.height;
    px.getContext("2d")!.drawImage(pend.canvas, 0, 0);
    maskRef.current.width = px.width;
    maskRef.current.height = px.height;
    maskRef.current.getContext("2d")!.clearRect(0, 0, px.width, px.height);
    setDims({ w: px.width, h: px.height });
    cropAcc.current = { x: 0, y: 0, w: 1, h: 1 };
    setHasSelection(false);
    setCropRect(null);
    setCropAngle(0);
    setZoom(1);
    setPan({ x: 0, y: 0 });
    undoStack.current = [];
    redoStack.current = [];
    stateId.current = nextStateId.current++;
    savedStateId.current = -1;          // nothing saved yet — always dirty
    setHistVer((v) => v + 1);
    setDirty(true);
    setLoaded(true);
  }, [editorItemId]);
  const loadedFileId = fileOverride ?? item?.active_file_id ?? null;
  const loadedFile = item?.files.find((f) => f.id === loadedFileId);

  // ---- the text-select tool's geometry -------------------------------------
  // Which engine's reading, when two have read the page (the properties bar's
  // dropdown). Defaults to the item's REMEMBERED choice, the same one the
  // library sidebar and the annotator resolve — three windows showing three
  // different readings of one page is three answers to one question.
  const [textEngine, setTextEngine] = useState<string | null>(null);
  useEffect(() => { setTextEngine(null); }, [editorItemId]);
  const textEngines = useMemo(
    () => enginesOf(liveRoots(textTree ?? [])), [textTree]);
  const textRemembered = useChosenEngine(editorItemId, textEngines);
  const textModel = textEngine != null && textEngines.includes(textEngine)
    ? textEngine : textRemembered;
  /** WHICH LEVEL is drawn and pickable. `null` is the default and the honest
   *  one — the smallest unit each branch HAS, which is what the removal mask
   *  uses and what a page of mixed depths wants. A named level is the
   *  override the properties bar offers when the reading holds more than one:
   *  words are what you reach for to paint out a name in a bubble, lines are
   *  what you reach for to take the whole bubble. Changing it never touches
   *  the SELECTION — it changes what there is to pick, and a selection is
   *  already made. */
  const [textLevel, setTextLevel] = useState<TextLevel | null>(null);
  useEffect(() => { setTextLevel(null); }, [editorItemId, textModel]);
  /** The active engine's regions (plus anything drawn by hand), flat. */
  const textRegions = useMemo(() => {
    const out: TextRegion[] = [];
    const visit = (r: TextRegion) => { out.push(r); r.children.forEach(visit); };
    for (const root of liveRoots(textTree ?? [])) {
      const eng = engineOf(root);
      if (eng && textModel && eng !== textModel) continue;
      visit(root);
    }
    return out;
  }, [textTree, textModel]);
  /** The levels this reading actually holds, coarsest last — the switch is
   *  offered only when there is more than one, since a control with one
   *  choice is a label. */
  const textLevels = useMemo(() => {
    const seen = new Set(textRegions.filter((r) => !r.dismissed)
      .map((r) => r.level));
    // "word" is deliberately absent: the smallest-box option below IS it.
    const order: TextLevel[] = ["char", "line", "block"];
    return order.filter((l) => seen.has(l));
  }, [textRegions]);
  /** The boxes the tool picks from, in the LOADED FILE's frame: by default
   *  the SMALLEST unit each branch has (`regions.subBoxes`, the same leaves
   *  the removal mask uses — a block box is a whole speech bubble, so
   *  selecting one to inpaint would repaint the art inside it), or every box
   *  of one level when the bar names one. */
  const textLeaves = useMemo(() => {
    const out: { id: number; quad: [number, number][] }[] = [];
    const toQuad = (r: TextRegion): [number, number][] => {
      if (r.quad.length === 4) return quadToFile(r.quad, loadedFile ?? null);
      const b = refToFile(r, loadedFile ?? null);
      return [[b.x, b.y], [b.x + b.w, b.y],
              [b.x + b.w, b.y + b.h], [b.x, b.y + b.h]];
    };
    if (textLevel) {
      for (const r of textRegions) {
        if (!r.dismissed && r.level === textLevel) {
          out.push({ id: r.id, quad: toQuad(r) });
        }
      }
      return out;
    }
    for (const root of liveRoots(textTree ?? [])) {
      const eng = engineOf(root);
      if (eng && textModel && eng !== textModel) continue;
      const leaves = subBoxes(root);
      for (const r of (leaves.length ? leaves : [root])) {
        out.push({ id: r.id, quad: toQuad(r) });
      }
    }
    return out;
  }, [textTree, textRegions, textModel, textLevel, loadedFile]);
  const hasText = textLeaves.length > 0;
  // The pointer handlers are registered once (they live on a window-level
  // effect), so they read the boxes through a ref rather than closing over
  // the render's copy — the drift `textRegionsRef` records in the annotator.
  const textLeavesRef = useRef(textLeaves);
  textLeavesRef.current = textLeaves;
  // A model's own name for the engine dropdown, read from the registry the
  // backend serves — never a second table of labels here (the one in
  // `PeopleSection` already carries a retired entry). The raw key is the
  // fallback, which is why a model retired from the registry still names
  // itself on the reading it made.
  const { data: mlModelList } = useQuery({
    queryKey: ["ml-models"], queryFn: api.mlModels, staleTime: 60_000,
  });
  // WHAT A MODEL IS CALLED, in the words its own action row uses: a spec's
  // `name` is the family ("Text (RapidOCR)") and its `variant` is the answer
  // ("Multilingual"), and every Detect menu shows the variant under a family
  // heading — so spelling out "Text (RapidOCR) — Multilingual" in a dropdown
  // was a second name for one thing, and the longer one.
  const mlLabel = (key: string): string => {
    for (const task of mlModelList?.tasks ?? []) {
      for (const m of task.models) {
        if (m.id === key) return m.variant || m.name;   // see below
      }
    }
    return key;
  };
  useEffect(() => {
    if (!loadedFileId) return;
    setLoaded(false);
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const px = pixelRef.current;
      px.width = img.naturalWidth;
      px.height = img.naturalHeight;
      px.getContext("2d")!.drawImage(img, 0, 0);
      maskRef.current.width = img.naturalWidth;
      maskRef.current.height = img.naturalHeight;
      maskRef.current.getContext("2d")!.clearRect(0, 0, px.width, px.height);
      setDims({ w: px.width, h: px.height });
      cropAcc.current = { x: 0, y: 0, w: 1, h: 1 };
      setHasSelection(false);
      setCropRect(null);
      setCropAngle(0);
      setZoom(1);
      setPan({ x: 0, y: 0 });
      undoStack.current = [];
      redoStack.current = [];
      stateId.current = nextStateId.current++;
      savedStateId.current = stateId.current;
      setHistVer((v) => v + 1);
      setDirty(false);
      setLoaded(true);
    };
    img.src = api.fileUrl(loadedFileId);
  }, [item?.id, loadedFileId]);

  // One step of the guarded whole-editor close (see closeGuardedAll): prompt
  // for the current tab if dirty, else hop to the next unsaved pending-crop
  // tab, else actually close. Assigned every render so it sees fresh state.
  closeStepRef.current = () => {
    if (!closingRef.current) return;
    if (dirtyRef.current) {
      setClosePrompt({
        proceed: () => {
          // Discard path (the prompt's Save button saves before proceeding,
          // which clears dirty on its own): drop a pending tab's stash and
          // mark the buffer resolved so the sequence moves on.
          const cur = useUI.getState().editorItemId;
          if (cur != null && cur < 0) pendingCrops.delete(cur);
          dirtyRef.current = false;
          setDirty(false);
          closeStepRef.current();
        },
      });
      return;
    }
    const st = useUI.getState();
    const next = st.editorTabs.find((id) => id < 0 && pendingCrops.has(id) && id !== st.editorItemId);
    if (next == null) {
      closingRef.current = false;
      closeEditor();
      return;
    }
    // Activate the next unsaved tab; once its buffer loads (dirty by
    // definition for a pending crop) the effect below re-enters the step.
    setEditorItem(next);
  };
  // Re-enter the close sequence once the hopped-to tab has actually loaded
  // AND committed its dirty flag. Keying on `dirty` matters: on the tab
  // switch itself `loaded` is still true from the previous tab and dirtyRef
  // still false, so an editorItemId-only trigger would advance right past
  // the not-yet-loaded pending tab and close the window.
  useEffect(() => {
    if (closingRef.current && loaded && dirty) closeStepRef.current();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, loaded, editorItemId]);

  // ---- track canvas box size ----
  useEffect(() => {
    const el = canvasBoxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Height of the vertical bar column (tool palette + color panel), measured
  // so the bottom help bar can dodge right when a short window would make
  // them overlap.
  const sideBarsRef = useRef<HTMLDivElement>(null);
  const [sideBarsH, setSideBarsH] = useState(0);
  useEffect(() => {
    const el = sideBarsRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSideBarsH(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // How wide the floating section bars (undo/redo, the menus) came out. The
  // properties bar is centred in what they LEAVE, so it needs the number.
  const [barsW, setBarsW] = useState(0);
  /** Where the free space at the top of the canvas starts: past the tool
   *  palette, past the section bars, plus a gap. */
  const propsFrom = 12 + (barsW > 0 ? barsW + 12 : 0);

  // Safe-area insets: the floating bars overlay the canvas (tool palette +
  // color panel left, section/props bars top, help/zoom bars bottom), so
  // fitting and default centering keep the image inside the uncovered region.
  const INSET = { l: 72, t: 66, r: 16, b: 52 };
  const safeW = Math.max(50, box.w - INSET.l - INSET.r);
  const safeH = Math.max(50, box.h - INSET.t - INSET.b);
  const fit = Math.min(safeW / dims.w, safeH / dims.h) || 1;
  // See `atActualSize` below: the display scale is what "100%" is measured in.
  const dpr = useDevicePixelRatio();
  const scale = fit * zoom;
  const drawW = dims.w * scale;
  const drawH = dims.h * scale;
  // The image's origin when pan is zero: centered in the safe area.
  const baseX = (s: number) => INSET.l + (safeW - dims.w * s) / 2;
  const baseY = (s: number) => INSET.t + (safeH - dims.h * s) / 2;
  const originX = () => baseX(scale) + pan.x;
  const originY = () => baseY(scale) + pan.y;

  // Latest view transform + selection flag, read each frame by the marching-ants
  // animation loop (which must never close over stale render state).
  const xformRef = useRef({ ox: 0, oy: 0, scale: 1, drawW: 0, drawH: 0, bw: 0, bh: 0, hasSel: false });
  xformRef.current = { ox: originX(), oy: originY(), scale, drawW, drawH, bw: box.w, bh: box.h, hasSel: hasSelection };
  // Cursor position over the canvas + the live tool/brush size, read by the
  // overlay animation loop to draw the brush-size preview circle.
  const cursorRef = useRef({ x: 0, y: 0, over: false });
  /** THE TIP PREVIEW IS A DOM RING, not a canvas draw. The paint tools hide
   *  the system cursor (`cursor: none`) and this circle IS the pointer, so
   *  it has to be there in every browser — and drawn into the marching-ants
   *  canvas it was not: it went missing in Safari, where the only visible
   *  effect was a brush with no cursor at all. A div cannot be got wrong
   *  that way, and it costs nothing per frame: it is moved by the mousemove
   *  handler directly, never through React state (a re-render per pointer
   *  sample is what that would be). */
  const ringRef = useRef<HTMLDivElement | null>(null);
  const placeRing = useCallback((x: number, y: number, on: boolean) => {
    const el = ringRef.current;
    if (!el) return;
    const bv = brushViewRef.current;
    const paints = bv.tool === "brush" || bv.tool === "blur" || bv.tool === "erase";
    if (!on || !paints) { el.style.display = "none"; return; }
    const d = Math.max(2, bv.size * xformRef.current.scale);
    el.style.display = "block";
    el.style.width = `${d}px`;
    el.style.height = `${d}px`;
    el.style.transform = `translate(${x - d / 2}px, ${y - d / 2}px)`;
  }, []);
  // Pen pressure (0..1) of the current pointer; 1 for mouse/touch. Pointer
  // events fire just before their compatibility mouse events, so the ref is
  // fresh when a mouse-driven stamp lands.
  const pressureRef = useRef(1);
  const brushViewRef = useRef({ tool: "hand" as Tool, size: 40 });
  brushViewRef.current = {
    tool: spaceHand ? "hand" : altHeld && (tool === "brush" || tool === "fill") ? "pipette" : tool,
    size: tool === "blur" ? tips.blur.size : tool === "erase" ? tips.erase.size : tips.brush.size,
  };

  const toImg = (cx: number, cy: number) => {
    const r = viewRef.current!.getBoundingClientRect();
    return {
      x: (cx - r.left - originX()) / scale,
      y: (cy - r.top - originY()) / scale,
    };
  };

  // Holding Space temporarily switches any tool to the hand (pan) tool,
  // Photoshop-style; the picked tool comes back on release.
  //
  // Holding Alt/Option over the BRUSH or the FILL is the pipette, the same way
  // and for as long as it is held (Photoshop's eyedropper modifier). It is a
  // derived tool rather than a switch, so a brief tap of Alt changes nothing.
  const altPicks = (t: Tool) => t === "brush" || t === "fill";
  const activeTool: Tool = spaceHand ? "hand" : altHeld && altPicks(tool) ? "pipette" : tool;

  // Zoom by `factor` about the right point — the same rule the annotator uses,
  // from the same `zoomPivot.ts` (its tests are where the rule is stated): an
  // axis where the picture FITS holds still, an axis that overflows follows
  // the cursor, and the pan is clamped so the picture never leaves a gap it
  // does not have to.
  //
  // The "viewport" here is the SAFE AREA — the content area inset by the
  // floating bars — and the pure helpers work in its coordinates, so the
  // cursor goes in with the inset subtracted. That is exactly the frame the
  // pan is already expressed in (`baseX` centres within the safe area and
  // then adds `pan`), so what comes back needs no translating.
  //
  // A null cursor is the zoom BUTTONS, which take the same path so they
  // cannot drift a picture the wheel holds still.
  const zoomAt = (canvas: { x: number; y: number } | null, factor: number) => {
    const z2 = Math.max(0.1, Math.min(8, zoom * factor));
    if (z2 === zoom) return;
    const state = { vp: { w: safeW, h: safeH },
                    frame: { w: drawW, h: drawH }, pan };
    const pivot = zoomPivot(state, canvas
      ? { x: canvas.x - INSET.l, y: canvas.y - INSET.t } : null);
    setZoom(z2);
    setPan(panForZoom(state, pivot, z2 / zoom));
  };

  // Zoom so the dragged image-pixel rect fills the viewport, centered.
  const zoomToRect = (r: { x: number; y: number; w: number; h: number }) => {
    if (r.w < 2 || r.h < 2) return;
    const s2 = Math.max(0.1 * fit, Math.min(8 * fit,
      Math.min(safeW / r.w, safeH / r.h)));
    setZoom(s2 / fit);
    const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
    setPan({
      x: INSET.l + safeW / 2 - cx * s2 - baseX(s2),
      y: INSET.t + safeH / 2 - cy * s2 - baseY(s2),
    });
  };

  // ---- render loop ----
  const pending = useRef<{ pts: { x: number; y: number }[]; rect?: Rect } | null>(null);
  // A LASSO BUILT BY CLICKS. A press that never travels does not deselect
  // in lasso style (the rectangle's and the ellipse's rule stays theirs): it
  // places a CORNER, and the shape then lives in `pending` BETWEEN gestures
  // — every further click adds a corner, a drag adds a freehand stretch to
  // the same outline — until it is closed by a double-click, a click on the
  // first corner or Enter, or thrown away by Escape (and by leaving the tool
  // or the style). The mode and the history entry are the FIRST click's:
  // one gesture, however many presses it took.
  const polyRef = useRef<{ mode: SelMode; hadSel: boolean; pushed: boolean } | null>(null);

  const redraw = useCallback(() => {
    const view = viewRef.current;
    if (!view) return;
    // The BACKING STORE is in device pixels while every coordinate below stays
    // in CSS pixels (`ctx.scale`). Without this, 100% — one picture pixel per
    // device pixel — would draw the image into half as many canvas pixels as
    // the screen has, and "actual size" would be a downscale.
    view.width = Math.round(box.w * dpr);
    view.height = Math.round(box.h * dpr);
    const ctx = view.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, box.w, box.h);
    const ox = originX(), oy = originY();
    const cs = getComputedStyle(view);
    const checkerA = cs.getPropertyValue("--editor-checker-a").trim() || "#141416";
    const checkerB = cs.getPropertyValue("--editor-checker-b").trim() || "#191a1c";
    // A CANVAS CANNOT READ A CSS VARIABLE: `ctx.strokeStyle = accent`
    // is an invalid colour, silently ignored, so every accent outline below
    // was drawn in the context's default BLACK — a lasso preview and the
    // float's handles invisible over a dark picture. Resolved here once.
    const accent = cs.getPropertyValue("--accent").trim() || "#4f8cff";
    // Checkerboard only under the image (its transparent areas show it); the
    // area around the image keeps the container's solid background.
    const drawChecker = (c: CanvasRenderingContext2D) => {
      c.save();
      c.translate(ox, oy);
      c.fillStyle = checkerPattern(c, checkerA, checkerB);
      c.fillRect(0, 0, drawW, drawH);
      c.restore();
    };
    ctx.imageSmoothingEnabled = scale * dpr < 3;
    // WHAT IS UNDER EVERYTHING — the checker and the picture at the current
    // ZOOM — is CACHED, and so is the selection veil below. Drawing either
    // means scaling something image-resolution down (twelve megapixels on a
    // 4000×3000 page), and through a drag it is the same twelve megapixels
    // every frame: the pixel buffer is written when a stroke ENDS and the
    // mask when a selection COMMITS. Measured in Chromium at dpr 2, one
    // box-select pointer move on that page went 1.31 → 0.56 ms — and
    // Chromium accelerates exactly this, so that is the FLOOR; the reports
    // were Safari, whose canvas is not.
    //
    // Both are drawn at the ORIGIN and blitted at (ox, oy), so the key is the
    // zoom and NOT the whole transform: that is what makes PANNING free,
    // which it was not when the cached canvases were viewport-sized and every
    // pixel of pan invalidated them.
    const bw = Math.max(1, Math.round(drawW * dpr));
    const bh = Math.max(1, Math.round(drawH * dpr));
    const zoomKey = `${bw}x${bh}|${dims.w}x${dims.h}`;
    // ZOOMED IN PAST THE CACHE CAP THE PICTURE IS DRAWN BY VISIBLE PATCH
    // (`canvasBlit.ts` has the numbers): the caches below are the whole
    // picture at the current zoom, which at 16x over a large page is a
    // canvas no browser allocates — and, short of that, a gigapixel scaled
    // draw on every rebuild, i.e. every pointer move outside a gesture. That
    // was the select tool and the brush going slow when zoomed in a lot. Up
    // there the cache buys nothing anyway: what is on screen is a small patch
    // of the source, and drawing it straight from the buffer is bounded by
    // the viewport whatever the zoom. `vis` is null with the picture wholly
    // off screen, which draws nothing — correctly.
    const huge = bw * bh > CACHE_MAX_PX;
    const vis = visibleBlit(ox, oy, scale, dims.w, dims.h, box.w, box.h);
    const blit = (c: CanvasRenderingContext2D, src: CanvasImageSource) => {
      if (vis) c.drawImage(src, vis.sx, vis.sy, vis.sw, vis.sh, vis.dx, vis.dy, vis.dw, vis.dh);
    };
    // Trusted only while a gesture is in flight (`gestureRef`, which closes
    // BEFORE `onUp` does its work), and not during the three that change what
    // is cached: a fill drag rewrites pixels, a wand drag and a marquee move
    // rewrite the mask. Everything else — pan, marquee, lasso, brush, crop,
    // zoom marquee, float transform — only reads them, and outside a gesture
    // both are rebuilt on every redraw exactly as before.
    // So correctness rests on the mousedown/mouseup pair alone, rather than on
    // each of the dozens of places that write the buffer or the mask
    // remembering to redraw afterwards: a generation counter is one forgotten
    // line away from a picture that lies about what is selected.
    const dragging = gestureRef.current;
    const floodKind = floodDrag.current?.kind;
    const backLive = dragging && floodKind !== "fill";
    const veilLive = dragging && floodKind !== "wand"
      && (drag.current as { kind?: string } | null)?.kind !== "maskmove";
    // Live stroke preview. An erase stroke previews the REPLACE semantics on
    // a copy (knockout, then the background color at its own alpha — the
    // checker shows through where it ends up transparent); a paint stroke
    // overlays the layer at the color's alpha.
    const st = strokeRef.current;
    if (st && st.erase) {
      drawChecker(ctx);
      const lay = strokeLayer();
      // REUSED across the moves of a stroke: a fresh image-sized canvas per
      // pointer move is the allocation the stroke layer already learned not
      // to make.
      let tmpImg = eraseRef.current;
      if (!tmpImg || tmpImg.width !== dims.w || tmpImg.height !== dims.h) {
        tmpImg = document.createElement("canvas");
        tmpImg.width = dims.w;
        tmpImg.height = dims.h;
        eraseRef.current = tmpImg;
      }
      const tc = tmpImg.getContext("2d")!;
      tc.setTransform(1, 0, 0, 1, 0, 0);
      // CLIPPED TO WHAT IS ON SCREEN. These are four passes over the buffer,
      // run on every pointer move of an erase stroke, and only the visible
      // rect of the result is ever drawn from — so on a big page the rest was
      // the picture's area of work per move for pixels nobody could see.
      // `vis` is recomputed per redraw and the clip follows it, so the rect
      // that is built is exactly the rect that is then blitted.
      if (vis) {
        tc.save();
        tc.beginPath();
        tc.rect(vis.sx, vis.sy, vis.sw, vis.sh);
        tc.clip();
        tc.globalCompositeOperation = "source-over";
        tc.clearRect(vis.sx, vis.sy, vis.sw, vis.sh);
        tc.drawImage(pixelRef.current, 0, 0);
        tc.globalCompositeOperation = "destination-out";
        tc.drawImage(lay, 0, 0);
        if (!st.toTransparent) {
          // Additive to complete the lerp — see endStroke for the math.
          tc.globalCompositeOperation = "lighter";
          tc.globalAlpha = st.alpha;
          tc.drawImage(lay, 0, 0);
          tc.globalAlpha = 1;
          tc.globalCompositeOperation = "source-over";
        }
        tc.restore();
      }
      blit(ctx, tmpImg);
    } else if (huge) {
      if (vis) {
        ctx.save();
        ctx.translate(ox, oy);
        ctx.fillStyle = checkerPattern(ctx, checkerA, checkerB);
        ctx.fillRect(vis.dx - ox, vis.dy - oy, vis.dw, vis.dh);
        ctx.restore();
      }
      blit(ctx, pixelRef.current);
      if (st) {
        ctx.save();
        ctx.globalAlpha = st.alpha;
        blit(ctx, strokeLayer());
        ctx.restore();
      }
    } else {
      let back = backRef.current;
      if (!(backLive && back && backKeyRef.current === zoomKey)) {
        if (!back || back.width !== bw || back.height !== bh) {
          back = document.createElement("canvas");
          back.width = bw; back.height = bh;
          backRef.current = back;
        }
        const bc = back.getContext("2d")!;
        bc.setTransform(1, 0, 0, 1, 0, 0);
        bc.clearRect(0, 0, bw, bh);
        bc.setTransform(dpr, 0, 0, dpr, 0, 0);
        bc.fillStyle = checkerPattern(bc, checkerA, checkerB);
        bc.fillRect(0, 0, drawW, drawH);
        bc.imageSmoothingEnabled = scale * dpr < 3;
        bc.drawImage(pixelRef.current, 0, 0, drawW, drawH);
        backKeyRef.current = zoomKey;
      }
      ctx.drawImage(back, ox, oy, drawW, drawH);
      if (st) {
        ctx.save();
        ctx.globalAlpha = st.alpha;
        // The VISIBLE patch, as the huge path already did it: the layer is the
        // size of the picture, and scaling all of it into the viewport on
        // every pointer move is work the destination throws away.
        blit(ctx, strokeLayer());
        ctx.restore();
      }
    }

    // Selection: dim the non-selected area using the mask. (Skipped while a
    // floating selection is being moved/transformed — the outline is enough.)
    // The animated marching-ants outline is drawn by a separate overlay canvas.
    if (hasSelection && !floatRef.current) {
      // Cached at the origin and keyed on the zoom, exactly like the backdrop
      // above — this is the one that makes a gesture inside an existing
      // selection cost what the same gesture costs outside one, since the
      // whole image-resolution mask was being scaled down over a fill on
      // every pointer move for a mask that had not changed.
      let tmp = dimRef.current;
      if (huge) {
        // The viewport-sized version of the same veil, rebuilt every redraw:
        // one fill and one patch of the mask, both bounded by the screen.
        const vw = Math.max(1, Math.round(box.w * dpr)), vh = Math.max(1, Math.round(box.h * dpr));
        if (!tmp || tmp.width !== vw || tmp.height !== vh) {
          tmp = document.createElement("canvas");
          tmp.width = vw; tmp.height = vh;
          dimRef.current = tmp;
        }
        veilKeyRef.current = "";
        const tctx = tmp.getContext("2d")!;
        tctx.setTransform(1, 0, 0, 1, 0, 0);
        tctx.clearRect(0, 0, vw, vh);
        tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        tctx.globalCompositeOperation = "source-over";
        if (vis) {
          tctx.fillStyle = "rgba(10,12,20,0.28)";
          tctx.fillRect(vis.dx, vis.dy, vis.dw, vis.dh);
          tctx.globalCompositeOperation = "destination-out";
          tctx.imageSmoothingEnabled = scale * dpr < 1;
          // The visible patch of the mask WHERE IT IS BEING DRAGGED TO: the
          // origin moves, so the visible rect is computed against the moved
          // origin rather than the mask's own.
          const sh = maskShift.current;
          const mv = sh
            ? visibleBlit(ox + sh.x * scale, oy + sh.y * scale, scale,
                          dims.w, dims.h, box.w, box.h)
            : vis;
          if (mv) {
            tctx.drawImage(maskRef.current, mv.sx, mv.sy, mv.sw, mv.sh,
                           mv.dx, mv.dy, mv.dw, mv.dh);
          }
        }
        ringDirty.current = true;
        if (!maskShift.current) maskGen.current++;
        ctx.drawImage(tmp, 0, 0, box.w, box.h);
      } else if (!(veilLive && tmp && veilKeyRef.current === zoomKey)) {
        if (!tmp || tmp.width !== bw || tmp.height !== bh) {
          tmp = document.createElement("canvas");
          tmp.width = bw; tmp.height = bh;
          dimRef.current = tmp;
        }
        const tctx = tmp.getContext("2d")!;
        tctx.setTransform(1, 0, 0, 1, 0, 0);
        tctx.clearRect(0, 0, bw, bh);
        tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        tctx.globalCompositeOperation = "source-over";
        // Light enough to still SEE what is outside the selection: this
        // veil says "that part is not selected", and at 45% it was also
        // saying "and you cannot look at it", which matters on a page
        // where the reason for the selection is somewhere else on it.
        tctx.fillStyle = "rgba(10,12,20,0.28)";
        tctx.fillRect(0, 0, drawW, drawH);
        tctx.globalCompositeOperation = "destination-out";
        // Nearest-neighbour when magnified: a smoothed mask edge reads as a
        // blurry dim border once zoomed in — the cut must stay pixel-sharp.
        tctx.imageSmoothingEnabled = scale * dpr < 1;
        const sh = maskShift.current;
        if (sh) {
          // WHILE THE SELECTION IS BEING DRAGGED the mask does not change, so
          // it is rendered to screen scale ONCE and blitted at the offset from
          // then on. Downscaling the full-resolution mask is the expensive
          // half of this rebuild, and the rebuild happens on every move —
          // there is nothing to cache about the veil itself, because the hole
          // in it is what is moving.
          let sm = shiftMaskRef.current;
          if (!sm || sm.width !== bw || sm.height !== bh) {
            sm = document.createElement("canvas");
            sm.width = bw; sm.height = bh;
            shiftMaskRef.current = sm;
            shiftKeyRef.current = "";
          }
          if (shiftKeyRef.current !== zoomKey) {
            const sc = sm.getContext("2d")!;
            sc.setTransform(1, 0, 0, 1, 0, 0);
            sc.clearRect(0, 0, bw, bh);
            sc.setTransform(dpr, 0, 0, dpr, 0, 0);
            sc.imageSmoothingEnabled = scale * dpr < 1;
            sc.drawImage(maskRef.current, 0, 0, drawW, drawH);
            shiftKeyRef.current = zoomKey;
          }
          tctx.drawImage(sm, sh.x * scale, sh.y * scale, drawW, drawH);
        } else {
          tctx.drawImage(maskRef.current, 0, 0, drawW, drawH);
        }
        veilKeyRef.current = zoomKey;
        // Same two inputs, same moment: the ants ring is rebuilt exactly when
        // the veil is, so the outline and the dimming can never be pictures
        // of two different selections.
        ringDirty.current = true;
        // A selection being dragged is the SAME mask at an offset.
        if (!sh) maskGen.current++;
      }
      if (!huge) ctx.drawImage(tmp, ox, oy, drawW, drawH);
    }

    // Floating selection: the lifted pixels, drawn at their live transform, plus
    // (in transform mode) the bounding box and drag handles.
    if (floatRef.current) {
      // A float has no veil (the outline is enough), so nothing above marked
      // the ring — and its transform moves under the pointer, which is the
      // one thing that must redraw the outline every frame.
      ringDirty.current = true;
      const f = floatRef.current;
      const cxS = ox + f.cx * scale, cyS = oy + f.cy * scale;
      const halfW = (f.w0 * f.scaleX * scale) / 2, halfH = (f.h0 * f.scaleY * scale) / 2;
      // Copy mode needs nothing here: the buffer under the float still holds
      // the original (`placeHome`), so the picture drawn above shows it.
      ctx.save();
      ctx.translate(cxS, cyS);
      ctx.rotate(f.rot);
      ctx.imageSmoothingEnabled = scale < 3;
      ctx.drawImage(f.canvas, -halfW, -halfH, halfW * 2, halfH * 2);
      ctx.restore();
      if (f.transforming) {
        const cos = Math.cos(f.rot), sin = Math.sin(f.rot);
        const corner = (sx: number, sy: number) => ({
          x: cxS + sx * halfW * cos - sy * halfH * sin,
          y: cyS + sx * halfW * sin + sy * halfH * cos,
        });
        const c = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)];
        // The stalk point (0, -(halfH+22)) rotated by rot about the center:
        // R(rot)·(0,-h) = (h·sin, -h·cos) — keeps it perpendicular to the top
        // edge (the old negated sin made it swing the wrong way horizontally).
        const rotH = { x: cxS + (halfH + 22) * sin, y: cyS - (halfH + 22) * cos };
        ctx.strokeStyle = accent;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(c[0].x, c[0].y);
        for (let i = 1; i < 4; i++) ctx.lineTo(c[i].x, c[i].y);
        ctx.closePath();
        ctx.stroke();
        // line to the rotate handle
        const topMid = { x: (c[0].x + c[1].x) / 2, y: (c[0].y + c[1].y) / 2 };
        ctx.beginPath(); ctx.moveTo(topMid.x, topMid.y); ctx.lineTo(rotH.x, rotH.y); ctx.stroke();
        const handle = (p: { x: number; y: number }, round = false) => {
          ctx.fillStyle = accent;
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          if (round) ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
          else { ctx.rect(p.x - 5, p.y - 5, 10, 10); }
          ctx.fill(); ctx.stroke();
        };
        c.forEach((p) => handle(p));
        // Mid-edge handles (move just that edge).
        handle(corner(0, -1));
        handle(corner(0, 1));
        handle(corner(1, 0));
        handle(corner(-1, 0));
        handle(rotH, true);
      }
    }

    // Pending selection shape preview.
    const p = pending.current;
    if (p && isSelectTool(tool)) {
      // BLACK AND WHITE, like the marching ants the shape is about to become:
      // a white line under a black dashed one, so the outline reads over a
      // dark picture and a light one alike (one colour is invisible on the
      // half of the pictures that share it).
      const bwStroke = () => {
        ctx.lineWidth = 1.5;
        ctx.setLineDash([]);
        ctx.strokeStyle = "#fff";
        ctx.stroke();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = "#000";
        ctx.stroke();
      };
      if (selStyle === "lasso" && (p.pts.length > 1 || polyRef.current)) {
        ctx.beginPath();
        ctx.moveTo(ox + p.pts[0].x * scale, oy + p.pts[0].y * scale);
        for (const pt of p.pts) ctx.lineTo(ox + pt.x * scale, oy + pt.y * scale);
        bwStroke();
        if (polyRef.current) {
          // Between clicks the next edge follows the pointer, and the first
          // corner is drawn larger: it is the target a click closes on.
          const c = cursorRef.current;
          if (c.over && !drag.current) {
            const last = p.pts[p.pts.length - 1];
            ctx.beginPath();
            ctx.moveTo(ox + last.x * scale, oy + last.y * scale);
            ctx.lineTo(c.x, c.y);
            bwStroke();
          }
          ctx.setLineDash([]);
          ctx.lineWidth = 1;
          ctx.fillStyle = "#fff";
          ctx.strokeStyle = "#000";
          p.pts.forEach((pt, i) => {
            const r = i === 0 ? POLY_CLOSE_PX / 2 : 2.5;
            ctx.fillRect(ox + pt.x * scale - r, oy + pt.y * scale - r, 2 * r, 2 * r);
            ctx.strokeRect(ox + pt.x * scale - r + 0.5, oy + pt.y * scale - r + 0.5,
                           2 * r - 1, 2 * r - 1);
          });
        }
      } else if (p.rect) {
        const r = p.rect;
        ctx.beginPath();
        if (selStyle === "ellipse") {
          ctx.ellipse(ox + (r.x + r.w / 2) * scale, oy + (r.y + r.h / 2) * scale,
            (r.w / 2) * scale, (r.h / 2) * scale, 0, 0, Math.PI * 2);
        } else {
          // Preview the same pixel-snapped rect the commit will produce.
          const x0 = Math.round(r.x), y0 = Math.round(r.y);
          const x1 = Math.round(r.x + r.w), y1 = Math.round(r.y + r.h);
          ctx.rect(ox + x0 * scale, oy + y0 * scale, (x1 - x0) * scale, (y1 - y0) * scale);
        }
        bwStroke();
      }
      ctx.setLineDash([]);
    }

    // THE TEXT BOXES, while the text tool is active — what there is to pick.
    // Green like the annotator's text layer (the accent means "selected" on
    // a canvas, and here the SELECTION is what the marching ants already
    // draw), each with a dark ring so a light outline reads on a white manga
    // page. Only the leaves are drawn: they are the only thing pickable.
    if (tool === "text") {
      for (const leaf of textLeaves) {
        ctx.beginPath();
        leaf.quad.forEach(([x, y], i) => {
          const px = ox + x * drawW, py = oy + y * drawH;
          if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
        });
        ctx.closePath();
        // THIN, DASHED and translucent. These outlines are not the subject —
        // the page is — and at a word per box a solid 1.5 px ring around
        // every one of them read as a grid drawn over the text. The dark
        // under-stroke stays (a light outline on a white manga page is
        // invisible) but goes faint with them, and the dash tells them apart
        // from the selection's own marching ants at a glance.
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = "rgba(0,0,0,0.30)";
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.strokeStyle = TEXT_BOX_STROKE;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // …and the band, while one is being dragged across them.
      const band = pending.current?.rect;
      if (band) {
        ctx.strokeStyle = accent;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.strokeRect(ox + band.x * scale, oy + band.y * scale,
                       band.w * scale, band.h * scale);
        ctx.setLineDash([]);
      }
    }

    // Crop overlay (rotated by the angle slider), with drag handles: corners
    // resize, the stalked top handle rotates, inside moves.
    if (cropRect && tool === "crop") {
      const r = cropRect;
      const W = (r.w * drawW) / 2, H = (r.h * drawH) / 2;
      ctx.save();
      ctx.translate(ox + (r.x + r.w / 2) * drawW, oy + (r.y + r.h / 2) * drawH);
      ctx.rotate((cropAngle * Math.PI) / 180);
      ctx.strokeStyle = accent;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(-W, -H, W * 2, H * 2);
      // stalk + handles (drawn in the rotated frame so they follow the rect)
      ctx.beginPath(); ctx.moveTo(0, -H); ctx.lineTo(0, -H - 22); ctx.stroke();
      const hnd = (x: number, y: number, round = false) => {
        ctx.fillStyle = accent;
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        if (round) ctx.arc(x, y, 5, 0, Math.PI * 2);
        else ctx.rect(x - 5, y - 5, 10, 10);
        ctx.fill(); ctx.stroke();
      };
      hnd(-W, -H); hnd(W, -H); hnd(W, H); hnd(-W, H);
      hnd(0, -H); hnd(0, H); hnd(W, 0); hnd(-W, 0);   // mid-edge handles
      hnd(0, -H - 22, true);
      ctx.restore();
    }

    // Zoom-tool drag marquee (the area to zoom into).
    if (zoomRect && tool === "zoom") {
      ctx.strokeStyle = accent;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(ox + zoomRect.x * scale, oy + zoomRect.y * scale,
                     zoomRect.w * scale, zoomRect.h * scale);
      ctx.setLineDash([]);
    }

  }, [box, dpr, scale, drawW, drawH, pan, hasSelection, tool, selStyle, cropRect, cropAngle, zoomRect, dims, loaded, textLeaves]);

  useEffect(() => { redraw(); }, [redraw]);
  // Always call the *latest* redraw from imperative callbacks (rotate/crop/
  // restore). Using `redraw` directly there captures a stale closure with the
  // pre-mutation `dims`, which draws the new buffer at the old aspect ratio
  // (image looked stretched until the next zoom rebuilt redraw).
  const redrawRef = useRef(redraw);
  redrawRef.current = redraw;

  // ---- marching ants ----
  // Animated black/white dashes tracing the selection silhouette (or, while
  // a selection is floating, the moved/transformed silhouette). Drawn on its own
  // overlay canvas so the animation never re-runs the (heavy) main redraw. The
  // technique: rasterize the selection at screen scale, keep only a 1px ring
  // just OUTSIDE it, and fill that with a rotating black/white stripe pattern
  // whose offset advances each frame — perpendicular stripes over a 1px ring
  // read as dashes marching along the outline, for any shape.
  //
  // THE OUTLINE NEVER COVERS A SELECTED PIXEL, HOWEVER FAINTLY SELECTED (owner
  // 2026-09). It was the silhouette's own edge, taken from the mask's alpha,
  // so a blurred selection drew blurred ants sitting on top of the feather.
  // Now the silhouette is made BINARY first — any alpha at all is in — and the
  // ring is one pixel of growth beyond it; how strongly each pixel is
  // selected is the veil's job, which dims by the mask's own alpha.
  const stripePat = useRef<CanvasPattern | null>(null);
  useEffect(() => {
    const p = document.createElement("canvas");
    p.width = 8; p.height = 8;
    const pc = p.getContext("2d")!;
    pc.fillStyle = "#fff"; pc.fillRect(0, 0, 8, 8);
    pc.fillStyle = "#000"; pc.fillRect(0, 0, 4, 8);
    stripePat.current = document.createElement("canvas").getContext("2d")!.createPattern(p, "repeat");
  }, []);

  useEffect(() => {
    let raf = 0;
    let t = 0;
    const scratch = document.createElement("canvas");
    const grown = document.createElement("canvas");
    const ring = document.createElement("canvas");
    // The zoomed-out path's levels (image resolution, then each halving),
    // kept so a pan does not allocate a picture's worth of canvas per frame.
    const levels: HTMLCanvasElement[] = [];
    // The finished pyramid: which mask, which generation of it, and which
    // halving factor it was built for. Built over the WHOLE mask, so a pan
    // (which only changes the visible patch) reads it as it is.
    let pyr: { mask: HTMLCanvasElement; gen: number; f: number; w: number; h: number;
               canvas: HTMLCanvasElement } | null = null;
    const level = (i: number, w: number, h: number) => {
      const c = levels[i] ?? (levels[i] = document.createElement("canvas"));
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
      else c.getContext("2d")!.clearRect(0, 0, w, h);
      return c;
    };
    /** Any alpha at all to full, on the GPU, with no readback. `lighter`
     *  ADDS, so two copies that take turns adding the other into themselves
     *  grow as the Fibonacci numbers: thirteen draws take 1/255 to 610/255.
     *  Two canvases rather than one drawn into itself, because Safari copies
     *  a canvas that is its own source on every draw — the self-drawn
     *  doubling was 10.5 ms at screen size there, this is 3.7. */
    const partner = document.createElement("canvas");
    const harden = (c: HTMLCanvasElement) => {
      if (partner.width !== c.width || partner.height !== c.height) {
        partner.width = c.width; partner.height = c.height;
      }
      const cx = c.getContext("2d")!, px = partner.getContext("2d")!;
      px.globalCompositeOperation = "copy";
      px.drawImage(c, 0, 0);
      cx.globalCompositeOperation = "lighter";
      px.globalCompositeOperation = "lighter";
      // Odd, so the last draw lands in `c`.
      for (let i = 0; i < 13; i++) {
        if (i % 2 === 0) cx.drawImage(partner, 0, 0);
        else px.drawImage(c, 0, 0);
      }
      cx.globalCompositeOperation = "source-over";
      px.globalCompositeOperation = "source-over";
    };
    // THE RING IS BUILT ONLY WHEN THE SHAPE CHANGES; the frame loop just moves
    // the stripes across it. Building it is thirteen full-screen composites —
    // the mask scaled to screen, eight shifted copies for the erosion, the
    // subtraction, the oversized rotated fill and the mask-in — and it was ALL
    // of that, sixty times a second, for as long as anything was selected. It
    // ran while you painted, while you dragged a marquee, while you panned:
    // the biggest thing "a selection makes the editor slow" was made of, and
    // none of it was work, because only the stripe PHASE animates.
    // `ringDirty` is set by `redraw` exactly when it rebuilds the dim veil,
    // which depends on the same two things this does (the mask and the view
    // transform) — so the two cannot get out of step with each other.
    // THE DASHES STAND STILL WHILE YOUR HAND IS BUSY. They are the one thing
    // on this canvas that redraws when nothing has happened, and during a
    // gesture that is sixty wake-ups a second competing with what the hand is
    // actually doing. So while a gesture is in flight and NOTHING THE OUTLINE
    // DEPENDS ON HAS MOVED, the loop returns before it does anything at all —
    // not even the clear — and the dashes simply hold their last frame.
    //
    // "Nothing has moved" is the whole of the correctness argument, and it is
    // two things: the mask (`ringDirty`, set wherever the veil is rebuilt) and
    // the VIEW TRANSFORM (`antsKey`). The transform half is not optional and
    // its absence was a real bug: the ring is a screen-space raster, so a pan
    // moves the picture out from under an outline that stays where it was
    // drawn. A float being dragged marks itself dirty on every redraw, so it
    // goes on tracking — the shape is moving and an outline that lagged it
    // would be a line drawn where the selection is not.
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const ac = antsRef.current;
      const xf = xformRef.current;
      if (!ac) return;
      const f = floatRef.current;
      // The transform the outline was last RASTERISED at. A pan changes ox/oy
      // and nothing else, and that alone makes the cached ring wrong.
      const key = `${xf.bw}x${xf.bh}|${xf.ox}|${xf.oy}|${xf.drawW}|${xf.drawH}`;
      if (key !== antsKey.current) ringDirty.current = true;
      if (gestureRef.current && !ringDirty.current) return;      // frozen
      if (ac.width !== xf.bw || ac.height !== xf.bh) {
        ac.width = xf.bw; ac.height = xf.bh;
        ringDirty.current = true;
      }
      const actx = ac.getContext("2d")!;
      actx.clearRect(0, 0, ac.width, ac.height);
      if (!xf.hasSel && !f) { antsKey.current = ""; return; }
      antsKey.current = key;
      if (!ringDirty.current) { stripe(actx, ac); return; }
      ringDirty.current = false;
      // Rasterize the selection silhouette at screen scale into `scratch`.
      if (scratch.width !== xf.bw || scratch.height !== xf.bh) { scratch.width = xf.bw; scratch.height = xf.bh; }
      const sctx = scratch.getContext("2d")!;
      sctx.clearRect(0, 0, xf.bw, xf.bh);
      sctx.imageSmoothingEnabled = false;
      if (f) {
        const halfW = (f.w0 * f.scaleX * xf.scale) / 2, halfH = (f.h0 * f.scaleY * xf.scale) / 2;
        sctx.save();
        sctx.translate(xf.ox + f.cx * xf.scale, xf.oy + f.cy * xf.scale);
        sctx.rotate(f.rot);
        // Trace the lifted SELECTION shape, not the content: transparent
        // pixels inside the selection must not grow their own outline.
        sctx.drawImage(f.mask, -halfW, -halfH, halfW * 2, halfH * 2);
        sctx.restore();
      } else {
        // The visible PATCH of the mask, never the whole mask scaled to the
        // picture's zoomed size — at 16x that destination is tens of
        // thousands of pixels a side, and only the screen's worth lands.
        const m = maskRef.current;
        // Against the MOVED origin while a selection is being dragged, so the
        // outline travels with the veil's hole (`maskShift`).
        const sh = maskShift.current;
        const b = visibleBlit(xf.ox + (sh ? sh.x * xf.scale : 0),
                              xf.oy + (sh ? sh.y * xf.scale : 0),
                              xf.scale, m.width, m.height, xf.bw, xf.bh);
        if (b && xf.scale < 1) {
          // ZOOMED OUT, a screen pixel stands for several mask pixels, and
          // any ordinary downscale lets a faintly selected one average away
          // into its unselected neighbours — the outline would then run over
          // it. So the patch is made binary and HALVED: a draw at exactly
          // half size samples every 2x2 block at its shared corner, which is
          // an exact box average, and hardening again after each step keeps
          // any selected pixel in (a quarter of full is far from zero). The
          // last step, by less than two, samples between pixels rather than
          // on a grid of them, so the shape is grown by one pixel first and
          // nothing can fall between two samples.
          let wantF = 1;
          while (xf.scale * wantF * 2 <= 1) wantF *= 2;
          if (!pyr || pyr.mask !== m || pyr.gen !== maskGen.current || pyr.f !== wantF
              || pyr.w !== m.width || pyr.h !== m.height) {
            let cur = level(0, m.width, m.height);
            cur.getContext("2d")!.drawImage(m, 0, 0);
            harden(cur);
            let w = m.width, h = m.height, f = 1;
            while (f < wantF) {
              const next = level(levels.indexOf(cur) + 1, Math.ceil(w / 2), Math.ceil(h / 2));
              const nctx = next.getContext("2d")!;
              nctx.imageSmoothingEnabled = true;
              nctx.imageSmoothingQuality = "low";
              nctx.drawImage(cur, 0, 0, w, h, 0, 0, w / 2, h / 2);
              harden(next);
              cur = next; w = next.width; h = next.height; f *= 2;
            }
            if (xf.scale * f < 1) {
              const g = level(levels.indexOf(cur) + 1, w, h);
              const gc = g.getContext("2d")!;
              for (const [dx, dy] of [[0, 0], [1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]] as const) {
                gc.drawImage(cur, dx, dy);
              }
              cur = g;
            }
            pyr = { mask: m, gen: maskGen.current, f, w: m.width, h: m.height, canvas: cur };
          }
          const f = pyr.f, cur = pyr.canvas;
          sctx.imageSmoothingEnabled = true;
          sctx.imageSmoothingQuality = "low";
          sctx.drawImage(cur, b.sx / f, b.sy / f, b.sw / f, b.sh / f, b.dx, b.dy, b.dw, b.dh);
        } else if (b) {
          sctx.drawImage(m, b.sx, b.sy, b.sw, b.sh, b.dx, b.dy, b.dw, b.dh);
        }
      }
      // The silhouette, BINARY: anything selected at all is in. (A float's
      // mask scaled up also stretches its anti-aliased edge into a soft
      // fringe; hardened, the ring stays one crisp screen pixel whatever the
      // float's scale.)
      harden(scratch);
      // Grow it by one pixel (the union of eight shifted copies) and take the
      // silhouette back out: the ring is the pixels just OUTSIDE it.
      if (grown.width !== xf.bw || grown.height !== xf.bh) { grown.width = xf.bw; grown.height = xf.bh; }
      const gctx = grown.getContext("2d")!;
      gctx.clearRect(0, 0, xf.bw, xf.bh);
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]] as const) {
        gctx.drawImage(scratch, dx, dy);
      }
      gctx.globalCompositeOperation = "destination-out";
      gctx.drawImage(scratch, 0, 0);
      gctx.globalCompositeOperation = "source-over";
      // KEEP the ring: from here every frame is the two lines in `stripe`.
      if (ring.width !== xf.bw || ring.height !== xf.bh) {
        ring.width = xf.bw; ring.height = xf.bh;
      }
      const rctx = ring.getContext("2d")!;
      rctx.clearRect(0, 0, ring.width, ring.height);
      rctx.drawImage(grown, 0, 0);
      antsRing.current = ring;
      antsRingGen.current++;
      stripe(actx, ac);
    };

    /** One frame: the stripes, clipped to the ring built above. */
    function stripe(actx: CanvasRenderingContext2D, ac: HTMLCanvasElement) {
      const pat = stripePat.current;
      if (!pat) return;
      t = (t + 0.35) % 8;
      // Rotate/translate the CONTEXT and fill a rect: patterns follow the
      // canvas transform everywhere (Safari has no reliable
      // CanvasPattern.setTransform), so the dash phase animates there too.
      // THE RECT IS THE CANVAS SEEN FROM THE ROTATED FRAME — its four
      // corners through the inverse rotation, padded by one pattern period
      // for the phase — not a square on the diagonal, which covered four and
      // a half screens of pattern fill sixty times a second for as long as
      // anything was selected. This is every frame's whole cost on a
      // software canvas (Safari), where the fill is the brush's competitor.
      actx.globalCompositeOperation = "source-over";
      actx.save();
      const ang = (35 * Math.PI) / 180;
      const cs = Math.cos(ang), sn = Math.sin(ang);
      actx.rotate(ang);
      actx.translate(t, 0);
      actx.fillStyle = pat;
      // Screen (x, y) lands at (x·cos + y·sin, −x·sin + y·cos) in the rotated
      // frame; the canvas's corners bound it at x ∈ [0, w·cos + h·sin] and
      // y ∈ [−w·sin, h·cos].
      actx.fillRect(-t - 8, -ac.width * sn - 8,
                    ac.width * cs + ac.height * sn + 16, ac.width * sn + ac.height * cs + 16);
      actx.restore();
      actx.globalCompositeOperation = "destination-in";
      actx.drawImage(ring, 0, 0);
      actx.globalCompositeOperation = "source-over";
    }

    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    const c = cursorRef.current;
    placeRing(c.x, c.y, c.over);
  }, [tool, spaceHand, altHeld, tips, scale, placeRing]);

  // ---- undo / redo ----
  const captureSnap = (): Snap => ({
    pixels: cloneCanvas(pixelRef.current),
    mask: cloneCanvas(maskRef.current),
    dims: { ...dims },
    hasSelection,
    id: stateId.current,
  });

  // Call before any destructive mutation (brush stroke, fill, rotate, crop).
  // Trim oldest entries to keep the (full-resolution) snapshots within a memory
  // budget, so undo on very large images can't exhaust the tab.
  const HISTORY_BUDGET = 512 * 1024 * 1024; // ~512 MB
  const snapBytes = (s: Snap) => (s.pixels.width * s.pixels.height + s.mask.width * s.mask.height) * 4;
  const pushHistory = () => {
    undoStack.current.push(captureSnap());
    stateId.current = nextStateId.current++;
    let total = undoStack.current.reduce((a, s) => a + snapBytes(s), 0);
    while (undoStack.current.length > 1 && total > HISTORY_BUDGET) {
      total -= snapBytes(undoStack.current.shift()!);
    }
    redoStack.current = [];
    setHistVer((v) => v + 1);
    setDirty(true);
  };

  /** A SELECTION CHANGE IS UNDOABLE TOO — and it is NOT an edit.
   *
   *  The snapshot has always carried the mask (that is what makes undoing a
   *  fill put its selection back), but only a pixel mutation ever pushed
   *  one, so a marquee that landed a hair off, a wand click that took half
   *  the page or a Clear had no way back. This pushes the same snapshot
   *  WITHOUT `setDirty`: nothing about the saved file changed, and a Save
   *  button lighting up because you drew a rectangle would be a lie. It also
   *  skips a push when the mask is untouched — a click that only deselects
   *  where there was nothing selected is not a step in the history.
   */
  const selRedoBefore = useRef<Snap[]>([]);
  const pushSelectionHistory = (): boolean => {
    if (floatRef.current) return false;   // the float has its own cancel
    undoStack.current.push(captureSnap());
    // NO NEW STATE ID, unlike `pushHistory`. The id is the identity of the
    // BUFFER, and what makes Save light up is that it differs from the saved
    // one — so minting a fresh one here made undoing a marquee report unsaved
    // changes to a picture nobody had touched.
    let total = undoStack.current.reduce((a, s) => a + snapBytes(s), 0);
    while (undoStack.current.length > 1 && total > HISTORY_BUDGET) {
      total -= snapBytes(undoStack.current.shift()!);
    }
    // What the drop below has to put back: clearing the redo stack is part
    // of pushing, so a gesture that turns out to be nothing would otherwise
    // throw away a redo it never earned.
    selRedoBefore.current = redoStack.current;
    redoStack.current = [];
    setHistVer((v) => v + 1);
    // Deliberately no `setDirty(true)`. The buffer is what gets saved, and a
    // selection is not in it.
    return true;
  };

  /** Take back the entry a gesture pushed at its mousedown, for a gesture
   *  that turned out to change nothing — a click on empty canvas with
   *  nothing selected. Whether it will change anything is not knowable at
   *  the press (a click and a drag start identically), so the honest order
   *  is push, then drop. */
  const dropSelectionHistory = () => {
    undoStack.current.pop();
    redoStack.current = selRedoBefore.current;
    setHistVer((v) => v + 1);
  };

  const restore = (s: Snap) => {
    pixelRef.current = cloneCanvas(s.pixels);
    maskRef.current = cloneCanvas(s.mask);
    setDims({ ...s.dims });
    setHasSelection(s.hasSelection);
    stateId.current = s.id;
    setDirty(s.id !== savedStateId.current);
    setTimeout(() => redrawRef.current(), 0);
  };

  const undo = () => {
    // Mid-move/transform, undo = cancel the float. The buffer currently has
    // a hole punched under the lifted pixels — snapshotting THAT onto the
    // redo stack (as a plain undo would) corrupts history.
    if (floatRef.current) { cancelFloat(); return; }
    if (!undoStack.current.length) return;
    redoStack.current.push(captureSnap());
    restore(undoStack.current.pop()!);
    setHistVer((v) => v + 1);
  };

  const redo = () => {
    if (floatRef.current) return; // lifting cleared the redo stack anyway
    if (!redoStack.current.length) return;
    undoStack.current.push(captureSnap());
    restore(redoStack.current.pop()!);
    setHistVer((v) => v + 1);
  };

  // ---- selection commit ----
  const commitSelection = (shape: { pts: { x: number; y: number }[]; rect?: Rect },
                           mode: SelMode, asStyle?: SelStyle) => {
    const mctx = maskRef.current.getContext("2d")!;
    if (mode === "replace") mctx.clearRect(0, 0, dims.w, dims.h);
    mctx.save();
    // INTERSECT keeps the destination only where the shape covers it, which is
    // what `destination-in` does with a filled path: outside the path the
    // source is transparent, so what was selected there goes.
    mctx.globalCompositeOperation = mode === "subtract" ? "destination-out"
      : mode === "intersect" ? "destination-in" : "source-over";
    mctx.fillStyle = "#fff";
    mctx.beginPath();
    // The STYLE is normally the bar's, but a caller may name one: the
    // text-select tool commits an engine's four-point quad, which is a
    // polygon whatever the marquee happens to be set to (an upright
    // rectangle over slanted text selects the art either side of the words).
    const selStyleNow = asStyle ?? selStyle;
    if (selStyleNow === "lasso") {
      if (shape.pts.length < 3) { mctx.restore(); return; }
      mctx.moveTo(shape.pts[0].x, shape.pts[0].y);
      for (const pt of shape.pts) mctx.lineTo(pt.x, pt.y);
      mctx.closePath();
    } else if (shape.rect) {
      const r = shape.rect;
      if (selStyleNow === "ellipse") {
        mctx.ellipse(r.x + r.w / 2, r.y + r.h / 2, r.w / 2, r.h / 2, 0, 0, Math.PI * 2);
      } else {
        // Box selections snap to pixel edges: round each edge independently so
        // the mask covers whole pixels with hard (non-antialiased) borders.
        const x0 = Math.round(r.x), y0 = Math.round(r.y);
        mctx.rect(x0, y0, Math.round(r.x + r.w) - x0, Math.round(r.y + r.h) - y0);
      }
    }
    mctx.fill();
    mctx.restore();
    // An INTERSECT of two areas that do not overlap is empty, which is an
    // ordinary outcome of the gesture rather than a mistake — so that one is
    // asked of the mask rather than assumed.
    setHasSelection(mode === "intersect" ? maskBBox() != null
      : mode === "subtract" ? hasSelection : true);
  };

  /** Close the lasso being built by clicks and commit it — three corners
   *  make a shape; fewer is a cancel. Answers whether there was one. */
  const finishPoly = (): boolean => {
    const poly = polyRef.current;
    const shape = pending.current;
    if (!poly) return false;
    if (shape && shape.pts.length >= 3) commitSelection(shape, poly.mode);
    else if (!poly.hadSel && poly.pushed) dropSelectionHistory();
    polyRef.current = null;
    pending.current = null;
    setGestureMode(null);
    redraw();
    return true;
  };
  /** Throw the lasso being built away. The mask was never touched, so the
   *  history entry the first click pushed is simply taken back. */
  const cancelPoly = (): boolean => {
    const poly = polyRef.current;
    if (!poly) return false;
    if (poly.pushed) dropSelectionHistory();
    polyRef.current = null;
    pending.current = null;
    setGestureMode(null);
    redraw();
    return true;
  };

  /** THE PIPETTE: the buffer's pixel under the pointer becomes the paint
   *  colour, or the background colour with Alt. Read through a 1x1 PROBE
   *  canvas rather than off the buffer itself — `getImageData` on a canvas
   *  takes it off the GPU path for good (the stroke-layer benchmark's trap),
   *  and the buffer is the one canvas every stroke composites through. A
   *  fully transparent pixel picks nothing: there is no colour there to
   *  take, and "transparent" is a background the swatch's own ✕ already
   *  offers. */
  const probeRef = useRef<HTMLCanvasElement | null>(null);
  // What this gesture has picked, for the picker's **recent colours**. A
  // colour taken off the picture is exactly the kind that row is for — it is
  // the one you cannot get back by remembering a number — but it is recorded
  // at the END of the gesture and not per pick: the pipette picks again on
  // every mousemove of a drag, and twelve slots of one sweep across a
  // photograph is the row emptied of everything worth keeping. The popover's
  // own rule, which records on close rather than per slider move.
  const lastPick = useRef<string | null>(null);
  /** `keepOpacity`: the brush's own Alt-pick, which takes the COLOUR off the
   *  picture and leaves the Opacity slider where it was — Photoshop's rule,
   *  and the one that makes sampling a flat area not reset a 30% brush. */
  const pickColor = (img: { x: number; y: number }, background: boolean, keepOpacity = false) => {
    const x = Math.floor(img.x), y = Math.floor(img.y);
    if (x < 0 || y < 0 || x >= dims.w || y >= dims.h) return;
    let probe = probeRef.current;
    if (!probe) {
      probe = document.createElement("canvas");
      probe.width = 1; probe.height = 1;
      probeRef.current = probe;
    }
    const pc = probe.getContext("2d", { willReadFrequently: true })!;
    pc.clearRect(0, 0, 1, 1);
    pc.drawImage(pixelRef.current, x, y, 1, 1, 0, 0, 1, 1);
    const [r, g, b, a] = pc.getImageData(0, 0, 1, 1).data;
    if (a === 0) return;
    const hex2 = (v: number) => v.toString(16).padStart(2, "0");
    const hex = `#${hex2(r)}${hex2(g)}${hex2(b)}${a < 255 ? hex2(a) : ""}`;
    if (background) setBgColor(hex);
    else if (keepOpacity) setColor((c) => withAlpha(splitAlpha(hex).rgb, splitAlpha(c).a));
    else setColor(hex);
    lastPick.current = hex;
  };

  /** End of a pipette gesture: the colour it ended on joins the recents. */
  const endPick = () => {
    if (lastPick.current) recordRecentColor(lastPick.current);
    lastPick.current = null;
  };

  const clearSelection = (record = true) => {
    // Nothing selected → nothing to take back (a click on empty canvas with
    // the marquee is this, and it must not fill the history with no-ops).
    // `record: false` is for a gesture that ALREADY pushed at its mousedown
    // and then turned out to be a deselecting click — one act, one entry.
    if (record && hasSelection) pushSelectionHistory();
    maskRef.current.getContext("2d")!.clearRect(0, 0, dims.w, dims.h);
    setHasSelection(false);
    redraw();
  };

  // Invert the selection: unselected areas become selected (full-canvas white
  // minus the current mask, so soft edges invert to their complement).
  const invertSelection = () => {
    pushSelectionHistory();
    const m = maskRef.current;
    const tmp = cloneCanvas(m);
    const mctx = m.getContext("2d")!;
    mctx.clearRect(0, 0, m.width, m.height);
    mctx.fillStyle = "#fff";
    mctx.fillRect(0, 0, m.width, m.height);
    mctx.globalCompositeOperation = "destination-out";
    mctx.drawImage(tmp, 0, 0);
    mctx.globalCompositeOperation = "source-over";
    setHasSelection(true);
    redraw();
  };

  // ---- floating selection (move / transform) ----
  // The tight bounding box of the current mask, in image pixels (null if empty).
  const maskBBox = (): { x: number; y: number; w: number; h: number } | null => {
    const w = maskRef.current.width, h = maskRef.current.height;
    if (!w || !h) return null;
    const data = maskRef.current.getContext("2d")!.getImageData(0, 0, w, h).data;
    let minx = w, miny = h, maxx = -1, maxy = -1;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (data[(y * w + x) * 4 + 3] > 10) {
          if (x < minx) minx = x; if (x > maxx) maxx = x;
          if (y < miny) miny = y; if (y > maxy) maxy = y;
        }
      }
    }
    if (maxx < 0) return null;
    return { x: minx, y: miny, w: maxx - minx + 1, h: maxy - miny + 1 };
  };

  // Lift the selected pixels off the buffer into a floating layer (leaving a
  // transparent hole), so they can be dragged / scaled / rotated.
  const beginFloat = (transforming: boolean): Floating | null => {
    if (floatRef.current) {
      if (transforming && !floatRef.current.transforming) updateFloat({ transforming: true });
      return floatRef.current;
    }
    if (!hasSelection) return null;
    const bb = maskBBox();
    if (!bb) return null;
    pushHistory();
    const fc = document.createElement("canvas");
    fc.width = bb.w; fc.height = bb.h;
    const fctx = fc.getContext("2d")!;
    fctx.drawImage(pixelRef.current, bb.x, bb.y, bb.w, bb.h, 0, 0, bb.w, bb.h);
    fctx.globalCompositeOperation = "destination-in";
    fctx.drawImage(maskRef.current, bb.x, bb.y, bb.w, bb.h, 0, 0, bb.w, bb.h);
    // Lift the selection SHAPE alongside the pixels (see Floating.mask).
    const mc = document.createElement("canvas");
    mc.width = bb.w; mc.height = bb.h;
    mc.getContext("2d")!.drawImage(maskRef.current, bb.x, bb.y, bb.w, bb.h, 0, 0, bb.w, bb.h);
    const orig = document.createElement("canvas");
    orig.width = bb.w; orig.height = bb.h;
    orig.getContext("2d")!.drawImage(pixelRef.current, bb.x, bb.y, bb.w, bb.h, 0, 0, bb.w, bb.h);
    const f: Floating = {
      canvas: fc, mask: mc, w0: bb.w, h0: bb.h,
      cx: bb.x + bb.w / 2, cy: bb.y + bb.h / 2,
      homeX: bb.x, homeY: bb.y,
      scaleX: 1, scaleY: 1, rot: 0, transforming, keep: keepOriginalRef.current, orig,
    };
    // Punch the hole in the buffer under the selection — unless the original
    // is being kept, in which case the buffer is left exactly as it was.
    if (!f.keep) placeHome(f, false);
    floatRef.current = f;
    setFloating(f);
    setTimeout(() => redrawRef.current(), 0);
    return f;
  };

  /** The buffer under a float's HOME: the original put back exactly (keep)
   *  or the hole punched through it with the lifted selection shape. */
  const placeHome = (f: Floating, keep: boolean) => {
    if (!f.orig) return;
    const pctx = pixelRef.current.getContext("2d")!;
    pctx.save();
    pctx.globalCompositeOperation = "copy";
    pctx.beginPath();
    pctx.rect(f.homeX, f.homeY, f.w0, f.h0);
    pctx.clip();
    pctx.drawImage(f.orig, f.homeX, f.homeY);
    pctx.restore();
    if (keep) return;
    pctx.save();
    pctx.globalCompositeOperation = "destination-out";
    pctx.drawImage(f.mask, f.homeX, f.homeY);
    pctx.restore();
  };

  // Bake the floating layer back into the buffer and re-derive the selection
  // mask from its transformed silhouette (so it stays selected in place).
  // With Keep original the buffer under the float already IS the original
  // (`placeHome`), so the copy simply lands on top of it.
  const commitFloat = () => {
    const f = floatRef.current;
    if (!f) return;
    const apply = (c: CanvasRenderingContext2D, src: HTMLCanvasElement) => {
      c.save();
      c.translate(f.cx, f.cy);
      c.rotate(f.rot);
      c.scale(f.scaleX, f.scaleY);
      c.drawImage(src, -f.w0 / 2, -f.h0 / 2);
      c.restore();
    };
    apply(pixelRef.current.getContext("2d")!, f.canvas);
    // The new mask is the transformed SELECTION shape (f.mask) — using the
    // content's alpha here would deselect transparent pixels.
    const mctx = maskRef.current.getContext("2d")!;
    mctx.clearRect(0, 0, dims.w, dims.h);
    apply(mctx, f.mask);
    // Force the mask to solid white where the silhouette has any alpha.
    mctx.save();
    mctx.globalCompositeOperation = "source-in";
    mctx.fillStyle = "#fff";
    mctx.fillRect(0, 0, dims.w, dims.h);
    mctx.restore();
    floatRef.current = null;
    setFloating(null);
    setFloatCursor(null);
    setHasSelection(true);
    setTimeout(() => redrawRef.current(), 0);
  };

  // Drop the floating layer and restore the pre-lift buffer (the snapshot
  // `beginFloat` pushed) — popped straight off the undo stack so no holed
  // intermediate state ever lands on the redo stack.
  const cancelFloat = () => {
    if (!floatRef.current) return;
    floatRef.current = null;
    setFloating(null);
    setFloatCursor(null);
    const snap = undoStack.current.pop();
    if (snap) restore(snap);
    setHistVer((v) => v + 1);
  };

  // Switching tools bakes any floating selection first (so it isn't lost).
  const pickTool = (id: Tool) => {
    if (floatRef.current) commitFloat();
    setTool(id);
  };

  // Roll the buffer back to the last saved (or freshly loaded) state — the
  // newest undo snapshot carrying the saved state id. Undoable itself (the
  // current state is pushed first).
  const revertToSaved = () => {
    if (floatRef.current) cancelFloat();
    const stack = undoStack.current;
    for (let i = stack.length - 1; i >= 0; i--) {
      if (stack[i].id === savedStateId.current) {
        pushHistory();
        restore(stack[i]);
        return;
      }
    }
  };
  // Whether such a snapshot exists (drives the menu entry's enabled state).
  const canRevert = dirty && undoStack.current.some((s) => s.id === savedStateId.current);

  // ---- selection clipboard (⌘/Ctrl+X/C/V) ----
  // Copy the selected pixels (and the selection shape) into the clipboard.
  // With a float active its content is copied as-is; otherwise the selection
  // is cut out of the buffer bbox-tight, like beginFloat does.
  const copySelection = (): boolean => {
    const f = floatRef.current;
    if (f) {
      SEL_CLIPBOARD = { canvas: cloneCanvas(f.canvas), mask: cloneCanvas(f.mask) };
      return true;
    }
    const bb = maskBBox();
    if (!bb) return false;
    const cut = document.createElement("canvas");
    cut.width = bb.w; cut.height = bb.h;
    const cctx = cut.getContext("2d")!;
    cctx.drawImage(pixelRef.current, bb.x, bb.y, bb.w, bb.h, 0, 0, bb.w, bb.h);
    cctx.globalCompositeOperation = "destination-in";
    cctx.drawImage(maskRef.current, bb.x, bb.y, bb.w, bb.h, 0, 0, bb.w, bb.h);
    const mc = document.createElement("canvas");
    mc.width = bb.w; mc.height = bb.h;
    mc.getContext("2d")!.drawImage(maskRef.current, bb.x, bb.y, bb.w, bb.h, 0, 0, bb.w, bb.h);
    SEL_CLIPBOARD = { canvas: cut, mask: mc };
    return true;
  };

  // Cut = copy + punch the selection out of the buffer (the selection itself
  // stays active, Photoshop-style). An active float is baked first so the cut
  // always works on committed pixels.
  const cutSelection = () => {
    if (floatRef.current) commitFloat();
    if (!copySelection()) return;
    pushHistory();
    const pctx = pixelRef.current.getContext("2d")!;
    pctx.save();
    pctx.globalCompositeOperation = "destination-out";
    pctx.drawImage(maskRef.current, 0, 0);
    pctx.restore();
    setTimeout(() => redrawRef.current(), 0);
  };

  // Paste the clipboard as a NEW floating selection in transform mode,
  // centered in the visible viewport. There is no hole under a pasted float,
  // so keep=false and Cancel simply pops the history pushed here.
  const pasteSelection = () => {
    const clip = SEL_CLIPBOARD;
    if (!clip) return;
    if (floatRef.current) commitFloat();
    pushHistory();
    setTool("select"); // float interactions live on the select tool
    const w0 = clip.canvas.width, h0 = clip.canvas.height;
    const cx = Math.max(0, Math.min(dims.w, (INSET.l + safeW / 2 - originX()) / scale));
    const cy = Math.max(0, Math.min(dims.h, (INSET.t + safeH / 2 - originY()) / scale));
    const f: Floating = {
      canvas: cloneCanvas(clip.canvas), mask: cloneCanvas(clip.mask),
      w0, h0, cx, cy, homeX: cx - w0 / 2, homeY: cy - h0 / 2,
      scaleX: 1, scaleY: 1, rot: 0, transforming: true, keep: false, pasted: true,
    };
    floatRef.current = f;
    setFloating(f);
    setTimeout(() => redrawRef.current(), 0);
  };

  // ---- brush / erase strokes (Photoshop-style stamping) ----
  // A stroke stamps a pre-rendered soft brush tip along the path at a spacing
  // fraction of the tip size (plus a dwell timer while the cursor rests), all
  // into an offscreen stroke layer. Soft tips stamp at a "flow" alpha < 1, so
  // self-crossings and dwelling genuinely build up — like Photoshop — while
  // the color's own alpha acts as the per-stroke opacity CAP (applied once
  // when the whole layer is composited, so a 50%-alpha stroke never exceeds
  // 50%). Hard tips stamp opaque (a flow < 1 would show the individual
  // stamp discs). The live preview composites the layer in redraw();
  // mouseup bakes it.
  const strokeRef = useRef<null | {
    /** THE ACCUMULATED COVERAGE, one byte a pixel, and the MAXIMUM of the
     *  stamps rather than their sum — which is the whole of what "opacity"
     *  means on a brush: one pass of the tip lays the tip's own profile, and
     *  passing over the same place again inside one stroke does not darken
     *  it. Under the old source-over accumulation a soft tip had to stamp at
     *  a flow far below 1 or its overlapping rims would build into a hard
     *  edge — so a soft stroke could never get past a third of the colour
     *  (measured: 32.5% at the default hardness 80, 28% at 50, and 100% only
     *  at a hardness of 100, where the flow was 1 because a hard tip has no
     *  rim to build up). A max cannot compound, so the flow is gone and the
     *  tip is stamped as drawn.
     *
     *  On the CPU because canvas has no max-alpha composite: `lighten` is a
     *  maximum of the colour channels and leaves alpha the ordinary union,
     *  and the coverage lives in alpha. One byte a pixel, reused across
     *  strokes (`coverRef`) — the full-size CANVAS this replaced was
     *  allocated fresh at every mousedown and never reused, which is 50 MB
     *  of garbage a stroke on a 12 MP page. */
    cover: Uint8ClampedArray;
    /** The tip's own alpha profile, `tipSize` square. */
    tip: Uint8ClampedArray;
    tipSize: number;
    rgb: string;                 // paint color, applied ONCE at composite time
    spacing: number;             // distance between stamps (image px)
    /** Distance travelled since the last stamp. A stroke is stamped every
     *  `spacing` pixels of TRAVEL, and the remainder has to survive to the
     *  next pointer event or the density becomes a fact about how fast the
     *  browser delivers mousemoves. */
    carry: number;
    erase: boolean;              // erase stroke: REPLACES pixels (knockout + bg)
    toTransparent: boolean;      // erase with no background color set
    alpha: number;               // opacity cap = the paint color's alpha
    last: { x: number; y: number }; // last stamp position
    /** WHAT HAS BEEN STAMPED SINCE THE LAYER WAS LAST COMPOSITED, in image
     *  pixels. `strokeLayer` recomposites only this and then EMPTIES it,
     *  which is what keeps a brush on an 8192² page as fast as one on a
     *  thumbnail. It used to be the union of every stamp of the whole stroke,
     *  which grows: a long diagonal drag across the page ends up
     *  recompositing (and, with a selection, re-masking) most of the picture
     *  on every pointer move, so the brush got slower the longer you drew.
     *  Incremental is correct because the layer is never cleared outside the
     *  rect being redrawn, so what was composited earlier is still right —
     *  and a stamp overlapping older ink is inside this rect by definition.
     *  Measured on a 200-stamp diagonal across a 4000×3000 page with a
     *  selection: 1.12 → 0.39 ms per move on average, 1.20 → 0.50 ms for the
     *  LAST move (the one the monotonic rect had grown worst for), and the
     *  finished layer is identical to the pixel. */
    dirty: { x0: number; y0: number; x1: number; y1: number };
  }>(null);
  /** The scratch the stroke layer is composited into, reused for the length
   *  of a stroke: a fresh image-sized canvas per pointer move measured ~24 ms
   *  at 8192² before the compositing even started. */
  const layerRef = useRef<HTMLCanvasElement | null>(null);
  /**
   * WHERE THE SELECTION IS BEING DRAGGED TO, while it is being dragged.
   *
   * Moving a selection changes nothing about the mask except where it sits, so
   * the mask is left alone for the length of the gesture and the veil and the
   * ants are drawn at this offset instead; mouseup bakes it in, once. It used
   * to clone the whole mask at the press and then CLEAR AND REDRAW the
   * full-size mask canvas on every pointer move — three image-sized canvas
   * operations per move, plus the veil's own downscale of the full-resolution
   * mask, for a picture that had not changed a pixel.
   */
  const maskShift = useRef<{ x: number; y: number } | null>(null);
  /** The mask at SCREEN scale, so a move blits that instead of scaling the
   *  full-resolution mask down on every frame. Keyed like the veil. */
  const shiftMaskRef = useRef<HTMLCanvasElement | null>(null);
  const shiftKeyRef = useRef("");
  /** Scratch for baking the move in (mouseup), so nothing is allocated. */
  const maskBakeRef = useRef<HTMLCanvasElement | null>(null);
  /** The scratch `strokeLayer` builds its rect of coloured coverage in. */
  const inkRef = useRef<ImageData | null>(null);
  /** The stroke coverage (one byte a pixel) and the box the LAST stroke wrote
   *  in it, so the next one wipes that much and not the whole picture. */
  const coverRef = useRef<Uint8ClampedArray | null>(null);
  const coveredRef = useRef({ x0: 0, y0: 0, x1: 0, y1: 0 });
  /** The scratch the selection's dim veil is composited in — reused for the
   *  same reason. */
  const dimRef = useRef<HTMLCanvasElement | null>(null);
  /** The checker + picture at the current transform, and the scratch the
   *  erase preview composites in — both reused for the same reason. */
  const backRef = useRef<HTMLCanvasElement | null>(null);
  const eraseRef = useRef<HTMLCanvasElement | null>(null);
  /** The view transform `dimRef` / `backRef` currently hold their picture for.
   *  Empty means "nothing cached"; see `redraw` for when they may be trusted. */
  const veilKeyRef = useRef("");
  const backKeyRef = useRef("");
  /** Throw the cached backdrop and veil away. Called from ONE place — the top
   *  of `onDown` — so a gesture's own first frame rebuilds from the picture
   *  and the mask as they stand. That is what makes the caches depend on
   *  nothing but the mousedown handler, rather than on every one of the dozens
   *  of places that write the pixel buffer or the mask remembering to redraw
   *  afterwards. */
  const gestureCacheRefresh = () => {
    veilKeyRef.current = "";
    backKeyRef.current = "";
    // NOT `ringDirty`: the veil rebuild this forces marks the ring itself
    // whenever an outline is showing (and a float marks it every redraw),
    // and `onSelectionBorder` reads the flag as "the ring is not a picture
    // of the mask" — which at the press it still is.
  };
  /** The marching-ants ring needs rebuilding. Set wherever the veil is
   *  rebuilt — the two are pictures of the same mask at the same transform,
   *  so one rule keeps them from disagreeing about what is selected. Read
   *  by `onSelectionBorder` as "the ring is stale". */
  const ringDirty = useRef(true);
  /** Bumped where the mask may have CHANGED (the veil rebuilt outside a
   *  gesture that leaves it alone), never by a pan, a zoom or a selection
   *  being dragged. What the zoomed-out outline's pyramid is keyed on: it is
   *  work in proportion to the PICTURE, and a pan asking for it again on
   *  every frame was 85 ms a frame on a 64 MP page in Safari. */
  const maskGen = useRef(0);
  /** The view transform the ants canvas currently HOLDS, or "" when it holds
   *  nothing. It is what lets a gesture freeze the dashes without freezing
   *  them through a pan: same key, same picture, nothing to redraw. */
  const antsKey = useRef("");
  /** The marching-ants RING as the loop last rasterised it — the selection
   *  outline at screen scale, one CSS pixel wide — with a count of its
   *  rebuilds and a CPU copy of its alpha taken on demand. What
   *  `onSelectionBorder` samples instead of the mask. */
  const antsRing = useRef<HTMLCanvasElement | null>(null);
  const antsRingGen = useRef(0);
  const antsRingPixels = useRef<{ gen: number; w: number; h: number; a: Uint8ClampedArray } | null>(null);
  /** True strictly BETWEEN the mousedown that starts a gesture and the mouseup
   *  that ends it — the only window in which the two caches may be reused.
   *  It is not `drag.current != null`, and that difference is the whole of the
   *  correctness argument: `onUp` bakes the stroke into the pixel buffer and
   *  commits the selection into the mask while `drag.current` is still set, so
   *  reading that ref would blit a backdrop without the stroke that had just
   *  been painted and a veil showing the selection that had just been
   *  replaced. */
  const gestureRef = useRef(false);

  const beginStroke = (toolId: "brush" | "erase", x: number, y: number) => {
    const tip = tips[toolId];
    const rad = Math.max(0.5, tip.size / 2);
    const h = tip.hardness / 100;
    // The color's alpha is NOT stamped — it is the opacity cap applied once
    // when the whole layer is composited (see strokeRef.alpha).
    const { rgb, a } = splitAlpha(toolId === "brush" ? color : bgColor ?? "#000000");
    // Pre-render the brush tip: opaque out to hardness·radius, smooth falloff
    // to the radius. Soft tips stamp at flow < 1 so overlaps build up; a hard
    // tip stamps opaque (flow banding would show the individual discs).
    //
    // The tip is PURE WHITE and rendered by hand (ImageData), and the layer
    // only ever accumulates this white coverage — the paint color is applied
    // once in strokeLayer(). Stamping a COLORED low-alpha tip dozens of times
    // lets 8-bit premultiplied compositing round R/G/B/A independently, and
    // the per-channel drift shows as faint colored streak lines inside soft
    // strokes (the gradient shader seeds it too — it interpolates channels
    // separately in premultiplied space). With every channel byte identical
    // (white), rounding hits them identically and the streaks can't form.
    // STAMPED AT ITS FULL PROFILE. The coverage is a MAXIMUM (see `cover`),
    // so overlapping stamps cannot compound and there is nothing for a flow
    // below 1 to protect: one pass lays exactly the tip, centre included.
    // The step stays fine for a soft tip — it is what keeps the union of the
    // discs smooth along the stroke rather than scalloped.
    const spacing = Math.max(1, rad * (h >= 0.99 ? 0.6 : 0.2));
    const sr = Math.ceil(rad * 2) + 2;
    const tipA = new Uint8ClampedArray(sr * sr);
    const inner = rad * Math.min(0.99, h);
    for (let py = 0; py < sr; py++) {
      for (let px2 = 0; px2 < sr; px2++) {
        const dd = Math.hypot(px2 + 0.5 - sr / 2, py + 0.5 - sr / 2);
        let f = dd <= inner ? 1 : dd >= rad ? 0 : 1 - (dd - inner) / (rad - inner);
        f = f * f * (3 - 2 * f);           // smoothstep falloff
        tipA[py * sr + px2] = Math.round(255 * f);
      }
    }
    // THE DWELL TIMER IS GONE WITH THE FLOW. It re-stamped in place twice a
    // second so a soft stroke built up like an airbrush while the pointer
    // rested; under a maximum, stamping the same place again is by
    // construction a no-op, so it was an interval per stroke that could not
    // change a pixel.
    // Reused across strokes, and wiped only where the last one went.
    const n = dims.w * dims.h;
    let cover = coverRef.current;
    if (!cover || cover.length !== n) {
      cover = new Uint8ClampedArray(n);
      coverRef.current = cover;
    } else {
      const b = coveredRef.current;
      if (b.x1 > b.x0) {
        for (let y = b.y0; y < b.y1; y++) cover.fill(0, y * dims.w + b.x0, y * dims.w + b.x1);
      }
    }
    coveredRef.current = { x0: dims.w, y0: dims.h, x1: 0, y1: 0 };
    strokeRef.current = {
      cover, tip: tipA, tipSize: sr, rgb,
      spacing,
      // Travel left over from the last pointer event — see the move
      // handler. Zero at the press, where the first stamp lands.
      carry: 0,
      erase: toolId === "erase",
      toTransparent: toolId === "erase" && !bgColor,
      alpha: a,
      last: { x, y },
      // EMPTY, and filled by the `strokeStamp` below: the rect means "what is
      // waiting to be composited", so a stroke that has stamped nothing since
      // the last frame must recomposite nothing.
      dirty: { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity },
    };
    // WIPE THE SCRATCH, once per stroke. It is reused across strokes, and
    // everything below draws the WHOLE layer into the buffer — so anything
    // left outside this stroke's dirty rect would be the previous stroke,
    // painted a second time.
    const lay = layerRef.current;
    if (lay && lay.width === dims.w && lay.height === dims.h) {
      lay.getContext("2d")!.clearRect(0, 0, lay.width, lay.height);
    } else {
      layerRef.current = null;
    }
    strokeStamp(x, y);
  };

  const strokeStamp = (x: number, y: number) => {
    const st = strokeRef.current;
    if (!st) return;
    // Pen pressure scales the stamp: lighter pressure = smaller AND fainter
    // (size and strength both follow the pen; a mouse always presses 1).
    const pr = pressureRef.current;
    const sr = st.tipSize;
    const w = Math.max(2, Math.round(sr * pr));
    const str = Math.max(0.05, pr);
    const W = dims.w, H = dims.h;
    const dx0 = Math.round(x - w / 2), dy0 = Math.round(y - w / 2);
    // The tip, at whatever size the pressure asks for, MAXED into the
    // coverage. Nearest-neighbour up or down: the tip is a smooth radial
    // falloff, so there is nothing in it for a better filter to preserve.
    const cover = st.cover, tip = st.tip;
    const jy0 = Math.max(0, -dy0), jy1 = Math.min(w, H - dy0);
    const jx0 = Math.max(0, -dx0), jx1 = Math.min(w, W - dx0);
    for (let j = jy0; j < jy1; j++) {
      const ty = Math.min(sr - 1, ((j * sr) / w) | 0);
      const row = (dy0 + j) * W + dx0;
      const trow = ty * sr;
      for (let i = jx0; i < jx1; i++) {
        const v = tip[trow + Math.min(sr - 1, ((i * sr) / w) | 0)] * str;
        const k = row + i;
        if (v > cover[k]) cover[k] = v;
      }
    }
    st.last = { x, y };
    // What the NEXT stroke has to wipe.
    const b = coveredRef.current;
    if (dx0 < b.x0) b.x0 = Math.max(0, dx0);
    if (dy0 < b.y0) b.y0 = Math.max(0, dy0);
    if (dx0 + w > b.x1) b.x1 = Math.min(W, dx0 + w);
    if (dy0 + w > b.y1) b.y1 = Math.min(H, dy0 + w);
    // Grow the dirty rect by this stamp (one pixel of slack for the tip's
    // antialiased rim).
    const d = st.dirty;
    d.x0 = Math.min(d.x0, x - w / 2 - 1);
    d.y0 = Math.min(d.y0, y - w / 2 - 1);
    d.x1 = Math.max(d.x1, x + w / 2 + 1);
    d.y1 = Math.max(d.y1, y + w / 2 + 1);
  };

  // The stroke layer as it will hit the pixels: the accumulated stamps,
  // clipped to the selection. Softness lives in the stamps themselves, so no
  // per-frame blur is needed (fast everywhere, including Safari's CPU path).
  const strokeLayer = (): HTMLCanvasElement => {
    const st = strokeRef.current!;
    // REUSED, and recomposited only where the stroke HAS BEEN. This runs on
    // every pointer move, and it used to do three full-image passes on a
    // fresh canvas each time — allocate, colourize, and (with a selection)
    // multiply the whole mask through it. Measured at 8192²: ~24 ms for the
    // allocation and colourize, ~17 ms more for the mask, per move. That is
    // the whole of "the brush is much slower when there is a selection", and
    // none of it was work: a stroke touches a few hundred pixels.
    let tmp = layerRef.current;
    if (!tmp || tmp.width !== dims.w || tmp.height !== dims.h) {
      tmp = document.createElement("canvas");
      tmp.width = dims.w;
      tmp.height = dims.h;
      layerRef.current = tmp;
      // A FRESH scratch holds none of this stroke's earlier composites, so the
      // incremental rect below would leave them out. Ask for everything once.
      st.dirty = { x0: 0, y0: 0, x1: tmp.width, y1: tmp.height };
    }
    const t = tmp.getContext("2d")!;
    const d = st.dirty;
    const x0 = Math.max(0, Math.floor(d.x0));
    const y0 = Math.max(0, Math.floor(d.y0));
    const x1 = Math.min(tmp.width, Math.ceil(d.x1));
    const y1 = Math.min(tmp.height, Math.ceil(d.y1));
    const w = Math.max(0, x1 - x0), h = Math.max(0, y1 - y0);
    if (w && h) {
      // Under a CLIP, so the two global composites below touch nothing
      // outside the rect — that is what makes them cost the stroke's area
      // rather than the picture's.
      // THE COVERAGE GOES IN ALREADY COLOURED, in one write. It used to be
      // three: clear the rect, draw the white coverage canvas into it, then
      // fill the paint colour through `source-in`. `putImageData` REPLACES
      // what is under it — no compositing, no clearing first — so the three
      // are one pass over the rect, and the full-size coverage canvas they
      // read from is gone with them.
      const px = st.rgb;
      const r8 = parseInt(px.slice(1, 3), 16), g8 = parseInt(px.slice(3, 5), 16);
      const b8 = parseInt(px.slice(5, 7), 16);
      let ink = inkRef.current;
      if (!ink || ink.width !== w || ink.height !== h) {
        ink = t.createImageData(w, h);
        inkRef.current = ink;
      }
      const d8 = ink.data, cover = st.cover, W = dims.w;
      for (let yy = 0; yy < h; yy++) {
        let o = yy * w * 4;
        let k = (y0 + yy) * W + x0;
        for (let xx = 0; xx < w; xx++, o += 4, k++) {
          d8[o] = r8; d8[o + 1] = g8; d8[o + 2] = b8; d8[o + 3] = cover[k];
        }
      }
      t.putImageData(ink, x0, y0);
      if (hasSelection) {
        // Under a CLIP, so the composite below touches nothing outside the
        // rect — that is what makes it cost the stroke's area rather than the
        // picture's. (`putImageData` above ignores clips and needs none.)
        t.save();
        t.beginPath();
        t.rect(x0, y0, w, h);
        t.clip();
        // The mask is applied to the FINISHED coverage, not per stamp: with
        // a feathered selection the two differ (per stamp compounds the
        // edge), and the end-mask is the one that means "paint, then keep
        // what is selected".
        t.globalCompositeOperation = "destination-in";
        t.drawImage(maskRef.current, x0, y0, w, h, x0, y0, w, h);
        t.restore();
        t.globalCompositeOperation = "source-over";
      }
    }
    // Spent. Anything stamped from here on is what the next frame redraws.
    st.dirty = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    return tmp;
  };

  // Bake the finished stroke into the pixel buffer (mouseup); the history
  // snapshot was pushed at stroke start.
  const endStroke = () => {
    const st = strokeRef.current;
    if (!st) return;
    const layer = strokeLayer();
    const pctx = pixelRef.current.getContext("2d")!;
    pctx.save();
    if (st.erase) {
      // Erase REPLACES: knock the stroke area out entirely, then lay the
      // background color in at its own alpha — a 50%-alpha background leaves
      // a 50%-transparent result, a transparent one leaves a hole.
      pctx.globalCompositeOperation = "destination-out";
      pctx.drawImage(layer, 0, 0);
      if (!st.toTransparent) {
        // ADDITIVE, not source-over: the knockout already removed the
        // stroke's share L of the destination, so adding bg·α·L yields the
        // exact lerp dst·(1−L) + bg·α·L. Source-over would attenuate the
        // remaining destination by (1−α·L) AGAIN, leaving soft edges
        // partially transparent even with a fully opaque background.
        pctx.globalCompositeOperation = "lighter";
        pctx.globalAlpha = st.alpha;
        pctx.drawImage(layer, 0, 0);
      }
    } else {
      pctx.globalAlpha = st.alpha;
      pctx.drawImage(layer, 0, 0);
    }
    pctx.restore();
    strokeRef.current = null;
  };

  // ---- blur brush ----
  // One blur stamp: a gaussian-blurred copy of the local region, masked to the
  // (soft) brush circle and pasted back — repeated stamps blur further, like
  // Photoshop's blur tool. Honors an active selection like the paint brush.
  //
  // THE CIRCLE IS CUT BEFORE THE BLUR, NOT AFTER, so only pixels the brush is
  // actually over can reach the result. Blurring first and masking second
  // averages in whatever lies outside the circle — brush along the edge of a
  // red field beside a blue one and the blue arrives 15 px inside the red
  // (measured: 28/255 of blue ten pixels in, 9/255 fifteen pixels in, with a
  // radius of 30 and a strength of 8). Cutting first is a NORMALIZED
  // convolution and costs nothing extra: a canvas blurs in premultiplied
  // alpha, so the un-premultiplied result is already sum(colour x weight) over
  // sum(weight) with the weights being the brush itself, and the pixel
  // fallback in `canvasBlur` premultiplies for the same reason. Same measured
  // scene afterwards: no blue at all on the red side.
  const stampBlur = (x: number, y: number) => {
    const rad = tips.blur.size / 2;
    const blurPx = blurStrength;
    const pad = Math.ceil(rad + blurPx * 3);
    const x0 = Math.round(x) - pad, y0 = Math.round(y) - pad;
    const s = pad * 2;
    const rx0 = Math.max(0, x0), ry0 = Math.max(0, y0);
    const rx1 = Math.min(dims.w, x0 + s), ry1 = Math.min(dims.h, y0 + s);
    if (rx1 <= rx0 || ry1 <= ry0) return;
    // Copy the region, then blur it via blurredCanvas (which also works where
    // ctx.filter doesn't — the blur tool was a silent no-op in Safari).
    const region = document.createElement("canvas");
    region.width = s; region.height = s;
    const rctx = region.getContext("2d")!;
    rctx.drawImage(
      pixelRef.current, rx0, ry0, rx1 - rx0, ry1 - ry0,
      rx0 - x0, ry0 - y0, rx1 - rx0, ry1 - ry0);
    // The (soft-edged) brush circle. Cap the inner radius below the outer one
    // — equal radii make the gradient degenerate (paints nothing) at 100%
    // hardness. Drawn twice: once as the WEIGHTS the blur averages over, and
    // again at the end as the shape that is pasted back.
    const circle = (c: CanvasRenderingContext2D) => {
      const g = c.createRadialGradient(
        pad, pad, rad * Math.min(0.99, tips.blur.hardness / 100), pad, pad, rad);
      g.addColorStop(0, "rgba(0,0,0,1)");
      g.addColorStop(1, "rgba(0,0,0,0)");
      c.globalCompositeOperation = "destination-in";
      c.fillStyle = g;
      c.fillRect(0, 0, s, s);
      c.globalCompositeOperation = "source-over";
    };
    circle(rctx);
    const tmp = blurredCanvas(region, blurPx);
    const tctx = tmp.getContext("2d")!;
    // The blur leaves the alpha as the circle SMEARED — so the stamp would
    // land at a fraction of its strength and the picture underneath would
    // read through it (measured on fine stripes: contrast 16 left of 160,
    // against 0 for the old full-strength stamp). Compositing the copy over
    // itself drives the alpha towards 1 and leaves the colour exactly where
    // it is, and three rounds are enough (contrast 1). A canvas may be its
    // own drawing source — the source is snapshotted first.
    for (let i = 0; i < 3; i++) tctx.drawImage(tmp, 0, 0);
    circle(tctx);
    if (hasSelection) applyClipped((c) => c.drawImage(tmp, x0, y0));
    else pixelRef.current.getContext("2d")!.drawImage(tmp, x0, y0);
  };

  // Render `paint` into a temp layer, keep only the masked part, blit to pixels.
  const applyClipped = (paint: (c: CanvasRenderingContext2D) => void,
                        op: GlobalCompositeOperation = "source-over") => {
    const tmp = document.createElement("canvas");
    tmp.width = dims.w; tmp.height = dims.h;
    const tctx = tmp.getContext("2d")!;
    paint(tctx);
    tctx.globalCompositeOperation = "destination-in";
    tctx.drawImage(maskRef.current, 0, 0);
    const p = pixelRef.current.getContext("2d")!;
    p.save();
    p.globalCompositeOperation = op;
    p.drawImage(tmp, 0, 0);
    p.restore();
  };

  /** Render `e` from the snapshot into the live buffer. Always from the
   *  SNAPSHOT: dragging a slider back and forth never compounds, and Cancel
   *  is a restore. With a selection, the effect reads the whole picture and
   *  writes only inside the mask — a blur that could see nothing outside the
   *  selection would darken towards its own edge, and a sharpen would find an
   *  edge there that is not in the picture. */
  const drawEffect = (e: Effect) => {
    const base = effectBase.current;
    if (!base) return;
    const p = pixelRef.current.getContext("2d")!;
    p.save();
    p.globalCompositeOperation = "source-over";
    p.clearRect(0, 0, dims.w, dims.h);
    p.drawImage(base, 0, 0);          // untouched, and outside any selection
    if (!effectIsNeutral(e)) {
      let out: HTMLCanvasElement;
      if (e.kind === "adjust") {
        out = document.createElement("canvas");
        out.width = dims.w; out.height = dims.h;
        drawAdjusted(out.getContext("2d")!, base, dims.w, dims.h, e.adjust);
      } else if (e.kind === "blur") {
        out = blurredImage(base, e.radius);
      } else {
        out = sharpenedImage(base, e.radius, e.amount);
      }
      if (hasSelection) {
        const tmp = document.createElement("canvas");
        tmp.width = dims.w; tmp.height = dims.h;
        const tc = tmp.getContext("2d")!;
        tc.drawImage(out, 0, 0);
        tc.globalCompositeOperation = "destination-in";
        tc.drawImage(maskRef.current, 0, 0);
        out = tmp;
      }
      p.drawImage(out, 0, 0);
    }
    p.restore();
    redraw();
  };

  // A full-resolution gaussian is heavy enough to outrun a slider drag — and
  // where `ctx.filter` is a no-op it is the pixel loop in `canvasBlur` rather
  // than the GPU, with the unsharp mask's own pass on top of it — so the
  // renders are COALESCED: the number moves on the event, the picture on the
  // next frame, at the last value asked for. (The four adjustments are cheap
  // enough not to need it and lose nothing by it.)
  const effectFrame = useRef<number | null>(null);
  const effectWanted = useRef<Effect | null>(null);
  /** Take `e` as the panel's state AND put it on screen. */
  const previewEffect = (e: Effect) => {
    setEffect(e);
    effectWanted.current = e;
    if (effectFrame.current != null) return;
    effectFrame.current = requestAnimationFrame(() => {
      effectFrame.current = null;
      if (effectWanted.current) drawEffect(effectWanted.current);
    });
  };
  const settleEffect = () => {
    if (effectFrame.current != null) cancelAnimationFrame(effectFrame.current);
    effectFrame.current = null;
  };

  /** Open one of the effect panels on the buffer as it stands.
   *
   *  Opening is also where an effect ALREADY open is committed: there is one
   *  snapshot, so a second panel over a live preview would snapshot the
   *  preview and leave the first with nothing to cancel back to. Keeping what
   *  is on screen is what somebody going from one to the other means. */
  const openEffect = (kind: Effect["kind"]) => {
    closeEffect(true);
    const snap = document.createElement("canvas");
    snap.width = dims.w; snap.height = dims.h;
    snap.getContext("2d")!.drawImage(pixelRef.current, 0, 0);
    effectBase.current = snap;
    previewEffect(freshEffect(kind));
  };

  const closeEffect = (keep: boolean) => {
    settleEffect();
    const base = effectBase.current;
    const e = effect;
    if (base && e) {
      // Undo has to capture the picture as it was BEFORE the effect, and the
      // buffer holds the preview — so put the snapshot back, record that,
      // then re-apply.
      const p = pixelRef.current.getContext("2d")!;
      p.clearRect(0, 0, dims.w, dims.h);
      p.drawImage(base, 0, 0);
      if (keep && !effectIsNeutral(e)) {
        pushHistory();
        drawEffect(e);
        rememberEffect(e);
      } else {
        redraw();
      }
    }
    effectBase.current = null;
    setEffect(null);
  };

  const fillSelection = () => {
    pushHistory();
    const paint = (c: CanvasRenderingContext2D) => { c.fillStyle = color; c.fillRect(0, 0, dims.w, dims.h); };
    if (hasSelection) applyClipped(paint);
    else paint(pixelRef.current.getContext("2d")!);
    redraw();
  };

  // ---- flood fill / magic wand ----
  // Both tools share one gesture: the click seeds a flood, and DRAGGING with
  // the button down re-runs that same flood at a tolerance driven by the drag
  // distance, so the filled/selected area grows and shrinks live. The source
  // pixels and the pre-gesture buffer/mask are captured once at mousedown, so
  // every re-run starts from the same base (no compounding) and a single undo
  // entry covers the whole gesture.
  const floodDrag = useRef<null | {
    kind: "fill" | "wand";
    x0: number; y0: number;          // seed pixel
    src: Uint8ClampedArray;          // pixels the flood tests against
    baseTol: number;                 // tolerance when the gesture started
    tol: number;                     // tolerance currently APPLIED
    pendingTol: number;              // tolerance the drag asks for (next frame)
    basePixels?: ImageData;          // fill: buffer before the gesture
    baseMask?: HTMLCanvasElement;    // wand: mask before the gesture
    maskData?: Uint8ClampedArray | null; // fill: selection clip, if any
    mode: SelMode;                   // wand: how it merges with the selection
    grow: number;                    // wand: pixels to grow (or shrink) the find by
    // How far each pixel is from the seed's colour. Built on the FIRST DRAG
    // FRAME and not before: it is a pass over the whole picture, which a click
    // would pay for nothing, and from then on it is the entire colour test
    // (see `floodRegion.ts`).
    dist: Uint8Array | null;
    scratch: ImageData;              // reused output buffer (no per-frame alloc)
    regionCanvas: HTMLCanvasElement; // wand: reused region raster
    moved: boolean;
  }>(null);
  const floodRaf = useRef(0);

  // Re-run the active gesture's flood at `tol` and apply it from the base.
  //
  // `settled` is "this is the result, not a preview of one": the press that
  // starts the gesture, and the release that ends it. The frames of a DRAG are
  // not, and the wand's Grow is the one thing that waits for them — it is a
  // morphology over the whole picture, and the point of the drag is to judge
  // the tolerance, which the raw find shows better than a padded one anyway.
  const applyFlood = (tol: number, settled: boolean) => {
    const g = floodDrag.current;
    if (!g) return;
    const w = dims.w, h = dims.h;
    g.tol = tol;
    // The distance map is the whole colour test once it exists; it is built on
    // the first drag frame, so a click never pays for it.
    const region = g.dist
      ? floodFromDistances(g.dist, w, h, g.x0, g.y0, tol)
      : floodFromPixels(g.src, w, h, g.x0, g.y0, tol);
    if (g.kind === "fill") {
      const { rgb, a } = splitAlpha(color);
      const n = parseInt(rgb.slice(1), 16);
      const fr = (n >> 16) & 255, fg = (n >> 8) & 255, fb = n & 255;
      const d = g.scratch.data;
      d.set(g.basePixels!.data);           // always start from the pre-fill buffer
      const mdata = g.maskData;
      for (let i = 0; i < w * h; i++) {
        if (!region[i] || (mdata && mdata[i * 4 + 3] <= 10)) continue;
        const j = i * 4;
        // source-over blend, so a semi-transparent fill color composites.
        const da = d[j + 3] / 255;
        const oa = a + da * (1 - a);
        if (oa <= 0) { d[j + 3] = 0; continue; }
        d[j] = Math.round((fr * a + d[j] * da * (1 - a)) / oa);
        d[j + 1] = Math.round((fg * a + d[j + 1] * da * (1 - a)) / oa);
        d[j + 2] = Math.round((fb * a + d[j + 2] * da * (1 - a)) / oa);
        d[j + 3] = Math.round(oa * 255);
      }
      pixelRef.current.getContext("2d")!.putImageData(g.scratch, 0, 0);
    } else {
      regionToMask(region, g.scratch.data);
      g.regionCanvas.getContext("2d")!.putImageData(g.scratch, 0, 0);
      // BEFORE the merge, so it is the find that is grown and not the
      // selection: `extend` adds a grown region to an untouched mask.
      if (settled && g.grow) growMaskBy(g.regionCanvas, g.grow);
      const mctx = maskRef.current.getContext("2d")!;
      mctx.clearRect(0, 0, w, h);
      if (g.mode !== "replace") mctx.drawImage(g.baseMask!, 0, 0);
      mctx.save();
      if (g.mode === "subtract") mctx.globalCompositeOperation = "destination-out";
      else if (g.mode === "intersect") mctx.globalCompositeOperation = "destination-in";
      mctx.drawImage(g.regionCanvas, 0, 0);
      mctx.restore();
      // A shrink can rub the whole find out, so the mask has to be ASKED
      // whether anything is left — as it already is when subtracting. Only
      // once it has actually been shrunk, and never on a drag frame: the ask
      // reads the whole mask back off the GPU.
      setHasSelection(g.mode === "subtract" || g.mode === "intersect" || (settled && g.grow < 0)
        ? maskBBox() != null : true);
    }
    redraw();
  };

  // Start a fill/wand gesture at an image point. Returns false when the click
  // is a no-op (outside the image, or outside an active selection for fill).
  const beginFlood = (kind: "fill" | "wand", ix: number, iy: number, mode: SelMode): boolean => {
    const w = dims.w, h = dims.h;
    const x0 = Math.floor(ix), y0 = Math.floor(iy);
    if (x0 < 0 || y0 < 0 || x0 >= w || y0 >= h) return false;
    if (kind === "fill" && hasSelection && !pointInSelection(x0, y0)) return false;
    const pctx = pixelRef.current.getContext("2d")!;
    const base = pctx.getImageData(0, 0, w, h);
    const scratch = pctx.createImageData(w, h);
    const region = document.createElement("canvas");
    region.width = w; region.height = h;
    // One undo entry per gesture: the pre-fill buffer is snapshotted here and
    // every drag update re-fills from `basePixels`, never from the live one.
    if (kind === "fill") pushHistory();
    floodDrag.current = {
      kind, x0, y0,
      src: base.data,
      baseTol: kind === "fill" ? fillTolerance : wandTolerance,
      tol: kind === "fill" ? fillTolerance : wandTolerance,
      pendingTol: kind === "fill" ? fillTolerance : wandTolerance,
      basePixels: kind === "fill" ? base : undefined,
      baseMask: kind === "wand" ? cloneCanvas(maskRef.current) : undefined,
      maskData: kind === "fill" && hasSelection
        ? maskRef.current.getContext("2d")!.getImageData(0, 0, w, h).data
        : null,
      grow: kind === "wand" ? wandGrow : 0,
      dist: null,
      mode, scratch, regionCanvas: region, moved: false,
    };
    applyFlood(floodDrag.current.tol, true);
    return true;
  };

  // Dragging adjusts the tolerance: right/up widens the flood, left/down
  // narrows it (3 screen px per percent, so a full sweep covers the range).
  const dragFlood = (dx: number, dy: number) => {
    const g = floodDrag.current;
    if (!g) return;
    const tol = Math.max(0, Math.min(100, Math.round(g.baseTol + (dx - dy) / 3)));
    if (tol === g.pendingTol) return;
    g.pendingTol = tol;
    g.moved = true;
    // Coalesce to one re-flood per frame — the BFS runs over the whole image.
    if (floodRaf.current) return;
    floodRaf.current = requestAnimationFrame(() => {
      floodRaf.current = 0;
      const cur = floodDrag.current;
      if (!cur || cur.pendingTol === cur.tol) return;
      // One pass over the picture, here rather than at the press: from now on
      // every frame reads one byte a pixel instead of four (`floodRegion.ts`).
      if (!cur.dist) cur.dist = seedDistances(cur.src, dims.w, dims.h, cur.x0, cur.y0);
      applyFlood(cur.pendingTol, false);
    });
  };

  // End the gesture, keeping the dragged tolerance as the tool's new setting.
  const endFlood = () => {
    const g = floodDrag.current;
    if (!g) return;
    if (floodRaf.current) { cancelAnimationFrame(floodRaf.current); floodRaf.current = 0; }
    // A frame may still have been pending — apply the final tolerance now, so
    // releasing right after a fast drag never leaves an intermediate result.
    // And this is where a dragged gesture gets its Grow: the drag previewed the
    // raw find, the release is the answer.
    if (g.pendingTol !== g.tol || (g.moved && g.grow)) applyFlood(g.pendingTol, true);
    if (g.moved) {
      if (g.kind === "fill") setFillTolerance(g.tol); else setWandTolerance(g.tol);
    }
    floodDrag.current = null;
  };

  // Grow (positive) or shrink (negative) the selection by N whole pixels, and
  // this is the ONE definition of what that means here: the wand's own find
  // goes through it too, so a "grow by 3" cannot mean one shape from the menu
  // and another from the tool.
  const growShrinkSelection = (mode: "grow" | "shrink", amount: number) => {
    if (!hasSelection || amount <= 0) return;
    pushSelectionHistory();
    growMaskBy(maskRef.current, mode === "grow" ? amount : -amount);
    setHasSelection(mode === "grow" ? true : maskBBox() != null);
    redraw();
  };

  /**
   * SOFTEN THE SELECTION'S OWN EDGE — the mask is blurred, not the picture.
   *
   * Photoshop calls it feathering. What it is FOR here is inpainting and every
   * other "do something to this area" verb: a hard mask edge leaves the seam
   * of whatever was done visible as a line, and a soft one lets the result
   * fade into what was already there. Everything downstream already honours a
   * partially-selected pixel — the brush multiplies its coverage by the mask,
   * the veil cuts by alpha, fill and the model actions clip through it — so
   * this needs no other change anywhere.
   *
   * The blur spreads the edge BOTH ways, as a feather does: the selection
   * loses a little at its rim and gains a little beyond it.
   */
  const blurSelectionEdge = (px: number) => {
    if (!hasSelection || px <= 0) return;
    pushSelectionHistory();
    const m = maskRef.current;
    const soft = blurredCanvas(m, px);
    const mctx = m.getContext("2d")!;
    mctx.clearRect(0, 0, m.width, m.height);
    mctx.drawImage(soft, 0, 0);
    // A blur cannot empty a selection that had anything in it, but it can
    // leave it below what counts as selected at the very smallest sizes.
    setHasSelection(maskBBox() != null);
    redraw();
  };

  // Delete/Backspace "remove": REPLACE the selection (or whole image) with
  // the background color — the area is knocked out first, so the color's own
  // alpha survives (50%-alpha background → 50%-transparent result;
  // transparency when none is set).
  const eraseSelection = () => {
    pushHistory();
    const pctx = pixelRef.current.getContext("2d")!;
    if (hasSelection) {
      pctx.save();
      pctx.globalCompositeOperation = "destination-out";
      pctx.drawImage(maskRef.current, 0, 0);
      pctx.restore();
    } else {
      pctx.clearRect(0, 0, dims.w, dims.h);
    }
    if (bgColor) {
      const paint = (c: CanvasRenderingContext2D) => { c.fillStyle = bgColor; c.fillRect(0, 0, dims.w, dims.h); };
      // Additive over the knocked-out area (mask edges would otherwise be
      // attenuated twice — see endStroke); over the cleared whole image a
      // plain fill is already exact.
      if (hasSelection) applyClipped(paint, "lighter");
      else paint(pctx);
    }
    redraw();
  };

  /**
   * PUT A SOLID COLOUR BEHIND THE PICTURE — the background colour, over the
   * whole picture or, where there is one, the selection.
   *
   * `destination-over` is the whole of it: the fill lands UNDER what is
   * already there, so a photograph is unchanged and a cut-out's transparency
   * becomes the colour. Half-transparent pixels blend, which is what makes it
   * the answer to a soft-edged cut-out on a white page — and a colour with an
   * alpha of its own is honoured, so it can be laid on as a wash.
   */
  const applyBackground = (hex: string) => {
    pushHistory();
    const paint = (c: CanvasRenderingContext2D) => {
      c.fillStyle = hex;
      c.fillRect(0, 0, dims.w, dims.h);
    };
    if (hasSelection) {
      applyClipped(paint, "destination-over");
    } else {
      const p = pixelRef.current.getContext("2d")!;
      p.save();
      p.globalCompositeOperation = "destination-over";
      paint(p);
      p.restore();
    }
    redraw();
  };

  /**
   * The menu's **Apply background color**. With no background colour set
   * there is nothing to put behind anything — `bgColor` is null, which is
   * what the swatch's slash means — so the action ASKS, by opening that
   * swatch's own picker with a line saying what the answer is for, and
   * applies when the picker closes on a colour. The picker is where the
   * background colour is chosen anyway; a dialog of its own would be a
   * second colour picker to keep in step with the first.
   *
   * Closing it without picking (Escape, or a press outside) leaves the
   * colour transparent and does nothing, which is the way out.
   */
  const [bgAsked, setBgAsked] = useState(false);
  const requestApplyBackground = () => {
    if (bgColor) { applyBackground(bgColor); return; }
    setBgAsked(true);
    setPickerFor("bg");
  };

  // ---- inpaint (LaMa) ----
  // The big-lama weights must be downloaded for the tool to run; gate on that.
  const { data: modelCache } = useQuery({ queryKey: ["model-cache"], queryFn: api.modelCache });
  const inpaintReady = !!(modelCache?.models ?? []).find((m) => m.key === "big_lama")?.cached;
  // Anime/illustration LaMa fine-tune — a second inpaint variant.
  const animeInpaintReady = !!(modelCache?.models ?? []).find((m) => m.key === "anime_lama")?.cached;
  const toBlob = (c: HTMLCanvasElement) =>
    new Promise<Blob>((res) => c.toBlob((b) => res(b!), "image/png"));
  // Send the pixel buffer + the selection mask to the backend; LaMa fills only the
  // masked region and returns the composited image, which replaces the buffer.
  const inpaintSelection = async (model: "big_lama" | "anime_lama" = "big_lama") => {
    if (!hasSelection || busy) return;
    setOpErr("");
    setBusy(true);
    try {
      const [imgBlob, maskBlob] = await Promise.all([toBlob(pixelRef.current), toBlob(maskRef.current)]);
      const result = await api.inpaint(imgBlob, maskBlob, model);
      const bmp = await createImageBitmap(result);
      pushHistory();
      const pctx = pixelRef.current.getContext("2d")!;
      pctx.clearRect(0, 0, dims.w, dims.h);
      pctx.drawImage(bmp, 0, 0);
      bmp.close?.();
      redraw();
    } catch (e) {
      setOpErr((e as Error).message || "Inpaint failed");
    } finally {
      setBusy(false);
    }
  };

  // ---- Image menu: size dialogs + buffer-level AI actions ----
  // Swap the pixel buffer for a new canvas (undoable); the mask resets and the
  // selection clears — a size change invalidates it anyway.
  const replaceBuffer = (next: HTMLCanvasElement) => {
    pushHistory();
    pixelRef.current = next;
    maskRef.current.width = next.width;
    maskRef.current.height = next.height;
    setDims({ w: next.width, h: next.height });
    setHasSelection(false);
    setTimeout(() => redrawRef.current(), 0);
  };

  const resizeImage = (w: number, h: number) => {
    if (w === dims.w && h === dims.h) return;
    const out = document.createElement("canvas");
    out.width = w; out.height = h;
    const octx = out.getContext("2d")!;
    octx.imageSmoothingEnabled = true;
    octx.imageSmoothingQuality = "high";
    octx.drawImage(pixelRef.current, 0, 0, w, h);
    // A pure resample shows the same region of the source, so the crop
    // tracking (normalized) stays valid.
    replaceBuffer(out);
  };

  const resizeCanvas = (w: number, h: number, anchor: [number, number]) => {
    if (w === dims.w && h === dims.h) return;
    const out = document.createElement("canvas");
    out.width = w; out.height = h;
    out.getContext("2d")!.drawImage(
      pixelRef.current,
      Math.round((w - dims.w) * anchor[0]),
      Math.round((h - dims.h) * anchor[1]));
    // The canvas no longer shows exactly the source region — drop the
    // tag-box crop tracking for this buffer.
    cropAcc.current = null;
    replaceBuffer(out);
  };

  // Run an image-to-image model on the buffer (synchronous /api/ml/apply)
  // and replace the buffer with the result (undoable).
  // A reference-guided model (example-based colorization) first opens the
  // reference picker; picking an image re-enters applyModel with its id.
  const [refPick, setRefPick] = useState<null | { kind: JobKind; model: string }>(null);
  const applyModel = async (kind: JobKind, model: string, reference = "") => {
    if (busy) return;
    setOpErr("");
    setBusy(true);
    try {
      const blob = await toBlob(pixelRef.current);
      const result = await api.mlApply(kind, model, blob, reference);
      const bmp = await createImageBitmap(result);
      const out = document.createElement("canvas");
      out.width = bmp.width; out.height = bmp.height;
      out.getContext("2d")!.drawImage(bmp, 0, 0);
      bmp.close?.();
      replaceBuffer(out);
    } catch (e) {
      setOpErr((e as Error).message || "The action failed");
    } finally {
      setBusy(false);
    }
  };

  // Detect text / watermark regions and turn them into the selection.
  const selectRegions = async (kind: "text" | "watermark") => {
    if (busy) return;
    setOpErr("");
    setBusy(true);
    try {
      const blob = await toBlob(pixelRef.current);
      const { regions } = await api.mlDetectRegions(kind, blob);
      if (!regions.length) {
        setOpErr(kind === "text" ? "No text found" : "No watermark found");
        return;
      }
      const mctx = maskRef.current.getContext("2d")!;
      mctx.clearRect(0, 0, dims.w, dims.h);
      mctx.fillStyle = "#fff";
      for (const poly of regions) {
        if (poly.length < 3) continue;
        mctx.beginPath();
        mctx.moveTo(poly[0][0] * dims.w, poly[0][1] * dims.h);
        for (const [px, py] of poly) mctx.lineTo(px * dims.w, py * dims.h);
        mctx.closePath();
        mctx.fill();
      }
      setHasSelection(true);
      redraw();
    } catch (e) {
      setOpErr((e as Error).message || "Detection failed");
    } finally {
      setBusy(false);
    }
  };

  // ---- rotate 90 ----
  const rotate90 = (dir: 1 | -1) => {
    pushHistory();
    const src = pixelRef.current;
    const out = paintedCanvas(src.height, src.width, (octx) => {
      octx.translate(src.height / 2, src.width / 2);
      octx.rotate((dir * 90 * Math.PI) / 180);
      octx.drawImage(src, -src.width / 2, -src.height / 2);
    });
    pixelRef.current = out;
    maskRef.current.width = out.width; maskRef.current.height = out.height;
    setDims({ w: out.width, h: out.height });
    setHasSelection(false);
    setTimeout(() => redrawRef.current(), 0);
  };

  // Set the crop rect to the selection's bounding box (crop tool button and
  // the Selection menu's "Crop to selection" — the latter also switches to the
  // crop tool so the rect is visible and adjustable).
  const cropToSelection = (switchTool = false) => {
    const bb = maskBBox();
    if (!bb) return;
    setCropAngle(0);
    // The bounding box is a request, not a shape: with a ratio locked the crop
    // is the largest one of that shape inside it.
    setCropRect(fitRectToAspect(
      { x: bb.x / dims.w, y: bb.y / dims.h, w: bb.w / dims.w, h: bb.h / dims.h },
      cropAspect, dims));
    if (switchTool) setTool("crop");
  };

  // ---- apply crop (with angle) ----
  // Parametrized so both the crop tool (state rect) and the immediate
  // crop-to-selection path share one implementation.
  const applyCropRect = (r: Rect, angle: number) => {
    pushHistory();
    // Track the buffer's region within the source file (axis-aligned crops
    // only); a rotated crop can't be expressed as a box, so drop the tracking.
    if (angle % 360 === 0 && cropAcc.current) {
      const a = cropAcc.current;
      cropAcc.current = {
        x: a.x + r.x * a.w, y: a.y + r.y * a.h,
        w: r.w * a.w, h: r.h * a.h,
      };
    } else {
      cropAcc.current = null;
    }
    const cw = Math.max(1, Math.round(r.w * dims.w));
    const ch = Math.max(1, Math.round(r.h * dims.h));
    const centerX = (r.x + r.w / 2) * dims.w;
    const centerY = (r.y + r.h / 2) * dims.h;
    const src = pixelRef.current;
    const out = paintedCanvas(cw, ch, (octx) => {
      octx.translate(cw / 2, ch / 2);
      octx.rotate((-angle * Math.PI) / 180);
      octx.translate(-centerX, -centerY);
      octx.drawImage(src, 0, 0);
    });
    pixelRef.current = out;
    maskRef.current.width = cw; maskRef.current.height = ch;
    setDims({ w: cw, h: ch });
    setHasSelection(false);
    setCropRect(null);
    setCropAngle(0);
    setTimeout(() => redrawRef.current(), 0);
  };
  const applyCrop = () => {
    if (cropRect) applyCropRect(cropRect, cropAngle);
  };
  // Crop the image to the selection's bounding box IMMEDIATELY (Selection
  // menu + the select tool's Crop button) — no detour through the crop tool.
  const cropSelectionNow = () => {
    const bb = maskBBox();
    if (!bb) return;
    applyCropRect({ x: bb.x / dims.w, y: bb.y / dims.h, w: bb.w / dims.w, h: bb.h / dims.h }, 0);
  };

  // Render the current crop into a PENDING new-item tab (leaving this buffer
  // untouched). The item is NOT created yet — only saving the new tab calls
  // the API; discarding the tab creates nothing. A rotated crop can't be
  // expressed as a box, so the eventual link simply carries none.
  const cropToNewItem = () => {
    if (!cropRect || !item) return;
    const r = cropRect;
    const cw = Math.max(1, Math.round(r.w * dims.w));
    const ch = Math.max(1, Math.round(r.h * dims.h));
    const centerX = (r.x + r.w / 2) * dims.w;
    const centerY = (r.y + r.h / 2) * dims.h;
    const src = pixelRef.current;
    const out = paintedCanvas(cw, ch, (octx) => {
      octx.translate(cw / 2, ch / 2);
      octx.rotate((-cropAngle * Math.PI) / 180);
      octx.translate(-centerX, -centerY);
      octx.drawImage(src, 0, 0);
    });
    // The crop's region within the source file (for the link's bbox); only an
    // un-rotated crop maps to an axis box.
    let box: { x: number; y: number; w: number; h: number } | null = null;
    if (cropAngle % 360 === 0 && cropAcc.current) {
      const a = cropAcc.current;
      box = { x: a.x + r.x * a.w, y: a.y + r.y * a.h, w: r.w * a.w, h: r.h * a.h };
    }
    const pid = nextPendingId--;
    pendingCrops.set(pid, {
      canvas: out,
      sourceItemId: item.id,
      sourceFileId: loadedFileId!,
      box,
    });
    setCropRect(null);
    setCropAngle(0);
    setEditorItem(pid);
  };

  // ---- pointer handling ----
  const drag = useRef<null | { tool: Tool; last: { x: number; y: number }; panFrom: { x: number; y: number }; startClient: { x: number; y: number } }>(null);

  // Screen (canvas-pixel) point → the float's unrotated, center-relative frame.
  const localToFloat = (f: Floating, sx: number, sy: number) => {
    const xf = xformRef.current;
    const cxS = xf.ox + f.cx * xf.scale, cyS = xf.oy + f.cy * xf.scale;
    const dx = sx - cxS, dy = sy - cyS;
    const c = Math.cos(-f.rot), s = Math.sin(-f.rot);
    return { x: dx * c - dy * s, y: dx * s + dy * c };
  };
  type HandleId = "nw" | "ne" | "se" | "sw" | "n" | "s" | "e" | "w" | "rot" | "move";
  // Per-handle outward direction (zero component = that axis is unaffected;
  // edge handles move only their own edge).
  const HANDLE_SIGN: Record<string, { x: number; y: number }> = {
    nw: { x: -1, y: -1 }, ne: { x: 1, y: -1 }, se: { x: 1, y: 1 }, sw: { x: -1, y: 1 },
    n: { x: 0, y: -1 }, s: { x: 0, y: 1 }, e: { x: 1, y: 0 }, w: { x: -1, y: 0 },
  };
  const hitHandle = (sx: number, sy: number): HandleId | null => {
    const f = floatRef.current;
    if (!f || !f.transforming) return null;
    const xf = xformRef.current;
    // Absolute extents: a flipped float (negative scale) must keep positive
    // half-sizes or every containment/handle test silently fails.
    const halfW = Math.abs(f.w0 * f.scaleX * xf.scale) / 2, halfH = Math.abs(f.h0 * f.scaleY * xf.scale) / 2;
    const loc = localToFloat(f, sx, sy);
    const near = (ax: number, ay: number) => Math.hypot(loc.x - ax, loc.y - ay) <= 10;
    if (near(0, -(halfH + 22))) return "rot";
    if (near(-halfW, -halfH)) return "nw";
    if (near(halfW, -halfH)) return "ne";
    if (near(halfW, halfH)) return "se";
    if (near(-halfW, halfH)) return "sw";
    if (near(0, -halfH)) return "n";
    if (near(0, halfH)) return "s";
    if (near(halfW, 0)) return "e";
    if (near(-halfW, 0)) return "w";
    if (Math.abs(loc.x) <= halfW && Math.abs(loc.y) <= halfH) return "move";
    return null;
  };
  const insideFloat = (sx: number, sy: number): boolean => {
    const f = floatRef.current;
    if (!f) return false;
    const xf = xformRef.current;
    const halfW = Math.abs(f.w0 * f.scaleX * xf.scale) / 2, halfH = Math.abs(f.h0 * f.scaleY * xf.scale) / 2;
    const loc = localToFloat(f, sx, sy);
    return Math.abs(loc.x) <= halfW && Math.abs(loc.y) <= halfH;
  };
  const pointInSelection = (ix: number, iy: number): boolean => {
    if (ix < 0 || iy < 0 || ix >= dims.w || iy >= dims.h) return false;
    return maskRef.current.getContext("2d")!.getImageData(Math.floor(ix), Math.floor(iy), 1, 1).data[3] > 10;
  };
  /** Whether a SCREEN point (CSS px of the view) sits on the selection
   *  outline — dragging from there repositions the mask.
   *
   *  ASKED ON EVERY HOVER OF THE SELECT TOOL, so it must not touch the mask.
   *  It used to sample nine points of it through `getImageData`, and each
   *  of those is a round trip to the GPU that waits for everything queued
   *  ahead of it: 7 ms apiece on a 28-megapixel page, 64 ms a mousemove and
   *  64 more at the press — "the select tool goes slow once something is
   *  selected". The marching-ants loop already rasterises the outline at
   *  screen scale as a one-pixel ring; that ring is read back ONCE per
   *  rebuild, only when this is asked, and sampled here on the CPU: a hit
   *  is any ring pixel within the reach the nine samples had (four screen
   *  pixels, never under two picture pixels). Between a mask change and
   *  the frame that rebuilds the ring (`ringDirty`) the copy is stale: a
   *  hover answers "no" rather than guess — one frame, and it asks again on
   *  the next move — while a PRESS (`exact`) pays the nine readbacks that
   *  one time, since what it decides is whether this drag moves the mask. */
  const onSelectionBorder = (sx: number, sy: number, exact = false): boolean => {
    if (!hasSelection || floatRef.current) return false;
    const ring = antsRing.current;
    if (!ring || ringDirty.current) {
      if (!exact) return false;
      const ix = (sx - originX()) / scale, iy = (sy - originY()) / scale;
      const d = Math.max(2, 4 / scale);
      let ins = 0, outs = 0;
      for (const [ox2, oy2] of [[0, 0], [d, 0], [-d, 0], [0, d], [0, -d], [d, d], [-d, -d], [d, -d], [-d, d]] as const) {
        if (pointInSelection(ix + ox2, iy + oy2)) ins++; else outs++;
      }
      return ins > 0 && outs > 0;
    }
    let px = antsRingPixels.current;
    if (!px || px.gen !== antsRingGen.current) {
      const w = ring.width, h = ring.height;
      if (!w || !h) return false;
      px = { gen: antsRingGen.current, w, h, a: ring.getContext("2d")!.getImageData(0, 0, w, h).data };
      antsRingPixels.current = px;
    }
    const r = Math.ceil(Math.max(4, 2 * scale));
    const cx = Math.floor(sx), cy = Math.floor(sy);
    const x0 = Math.max(0, cx - r), x1 = Math.min(px.w - 1, cx + r);
    const y0 = Math.max(0, cy - r), y1 = Math.min(px.h - 1, cy + r);
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) if (px.a[(y * px.w + x) * 4 + 3] > 0) return true;
    }
    return false;
  };

  // ---- crop-rect geometry (image px; the rect rotates about its center) ----
  type CropHandle = "nw" | "ne" | "se" | "sw" | "n" | "s" | "e" | "w" | "rot" | "move";
  const cropGeomOf = (r: Rect, angleDeg: number) => ({
    cx: (r.x + r.w / 2) * dims.w, cy: (r.y + r.h / 2) * dims.h,
    hw: (r.w * dims.w) / 2, hh: (r.h * dims.h) / 2,
    th: (angleDeg * Math.PI) / 180,
  });
  type CropGeom = ReturnType<typeof cropGeomOf>;
  const toCropLocal = (g: CropGeom, ix: number, iy: number) => {
    const dx = ix - g.cx, dy = iy - g.cy;
    const c = Math.cos(-g.th), s = Math.sin(-g.th);
    return { x: dx * c - dy * s, y: dx * s + dy * c };
  };
  const fromCropLocal = (g: CropGeom, lx: number, ly: number) => {
    const c = Math.cos(g.th), s = Math.sin(g.th);
    return { x: g.cx + lx * c - ly * s, y: g.cy + lx * s + ly * c };
  };
  const hitCropHandle = (ix: number, iy: number): CropHandle | null => {
    if (!cropRect) return null;
    const g = cropGeomOf(cropRect, cropAngle);
    const tol = 10 / scale;                      // handle radius in image px
    const loc = toCropLocal(g, ix, iy);
    if (Math.hypot(loc.x, loc.y + g.hh + 22 / scale) <= tol) return "rot";
    const handles: [CropHandle, number, number][] = [
      ["nw", -g.hw, -g.hh], ["ne", g.hw, -g.hh], ["se", g.hw, g.hh], ["sw", -g.hw, g.hh],
      ["n", 0, -g.hh], ["s", 0, g.hh], ["e", g.hw, 0], ["w", -g.hw, 0]];
    for (const [id, x, y] of handles) {
      if (Math.hypot(loc.x - x, loc.y - y) <= tol) return id;
    }
    if (Math.abs(loc.x) <= g.hw && Math.abs(loc.y) <= g.hh) return "move";
    return null;
  };
  // Rect from a fresh crop drag. With an angle set, the two drag points are
  // opposite CORNERS of the rotated rect (not of its axis-aligned bounds).
  const cropDragRect = (a: { x: number; y: number }, b: { x: number; y: number }): Rect => {
    if (cropAngle % 360 === 0) {
      return cropAspect ? aspectDragRect(a, b, dims, cropAspect) : rectNorm(a, b, dims);
    }
    const th = (cropAngle * Math.PI) / 180;
    const c = Math.cos(-th), s = Math.sin(-th);
    const dx = b.x - a.x, dy = b.y - a.y;
    let lx = Math.abs(dx * c - dy * s), ly = Math.abs(dx * s + dy * c);
    // The ratio applies in the rect's OWN frame — a rotated 16:9 crop is still
    // 16:9 in the picture it will produce.
    if (cropAspect) ({ lx, ly } = fitExtents(lx, ly, cropAspect));
    const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
    return { x: (cx - lx / 2) / dims.w, y: (cy - ly / 2) / dims.h, w: lx / dims.w, h: ly / dims.h };
  };
  const updateFloat = (patch: Partial<Floating>) => {
    const cur = floatRef.current;
    if (!cur) return;
    const nf = { ...cur, ...patch };
    floatRef.current = nf;
    // Only the transforming/keep flags affect the UI (props bar); position and
    // scale changes stay ref-only so a drag never re-renders per mousemove.
    if (patch.keep !== undefined && patch.keep !== cur.keep) {
      placeHome(nf, nf.keep);
      if (!nf.pasted) {
        keepOriginalRef.current = nf.keep;
        APP_PREFS.editorKeepOriginal.write(nf.keep);
      }
    }
    if (patch.transforming !== undefined || patch.keep !== undefined) setFloating(nf);
    redrawRef.current();
  };

  const onDown = (e: React.MouseEvent) => {
    e.preventDefault();
    // A PRESS ON THE PICTURE TAKES THE KEYBOARD BACK. The `preventDefault`
    // above is what stops a drag selecting the page around the canvas — and
    // it also cancels the focus change a mousedown makes, so a props-bar
    // field that had been typed in (the wand's Grow, either Tolerance box, a
    // brush size, a crop ratio) went on holding focus for the rest of the
    // session, however many times the canvas was pressed afterwards. Every
    // window shortcut asks `isTypingTarget` and stands down over a field, so
    // Space stopped panning and M, W, ⌘Z and Delete stopped working, with
    // nothing on screen saying why: the caret is in the bar, not where the
    // eye is. Blurring commits the field, which is what clicking away means.
    const focused = document.activeElement as HTMLElement | null;
    if (focused && isTypingTarget({ target: focused })) focused.blur();
    // A GESTURE BEGINS: the cached backdrop and veil in `redraw` are only
    // ever reused within one, so this single line is the whole of their
    // invalidation. Everything the gesture then does — paint, drag a
    // marquee, pan, crop — leaves the picture and the mask alone until it
    // ends, and the two that do not are named there.
    gestureCacheRefresh();
    gestureRef.current = true;
    const img = toImg(e.clientX, e.clientY);
    // Middle mouse button pans (same as the hand tool / holding Space).
    if (e.button === 1) {
      drag.current = { tool: "hand", last: img, panFrom: { ...pan }, startClient: { x: e.clientX, y: e.clientY } };
      return;
    }
    const r = viewRef.current!.getBoundingClientRect();
    const sx = e.clientX - r.left, sy = e.clientY - r.top;

    // Floating-selection interactions take priority over the active tool.
    if (floatRef.current?.transforming) {
      const hh = hitHandle(sx, sy);
      if (hh) {
        drag.current = { tool, last: img, panFrom: { ...pan }, startClient: { x: e.clientX, y: e.clientY } };
        (drag.current as any).kind = "xform";
        (drag.current as any).handle = hh;
        (drag.current as any).startImg = img;
        (drag.current as any).cx0 = floatRef.current.cx;
        (drag.current as any).cy0 = floatRef.current.cy;
        // Corner scaling: center-relative grab point + start scales for the
        // Alt (scale-from-center) path…
        (drag.current as any).loc0 = localToFloat(floatRef.current, sx, sy);
        (drag.current as any).sx0 = floatRef.current.scaleX;
        (drag.current as any).sy0 = floatRef.current.scaleY;
        // …and the OPPOSITE corner/edge (image px), which stays fixed by
        // default (Photoshop-style — resizing never happens about the center
        // unless Alt is held). Edge handles anchor the opposite edge's
        // midpoint and move only their own axis.
        if (hh !== "rot" && hh !== "move") {
          const f0 = floatRef.current;
          const sign = HANDLE_SIGN[hh];
          const hwI = (f0.w0 * f0.scaleX) / 2, hhI = (f0.h0 * f0.scaleY) / 2;
          const c = Math.cos(f0.rot), s = Math.sin(f0.rot);
          const lx = -sign.x * hwI, ly = -sign.y * hhI;
          (drag.current as any).csign = sign;
          (drag.current as any).fixImg = {
            x: f0.cx + lx * c - ly * s,
            y: f0.cy + lx * s + ly * c,
          };
        }
        return;
      }
      // Clicking outside the box bakes the transform, then the click proceeds.
      commitFloat();
    }
    // The hand tool (or held Space) only pans — Photoshop-style; moving a
    // floated selection happens through its transform box instead.
    // `e.altKey` as well as the held flag: an Alt pressed while a field had
    // the focus never reached the key handler.
    const altPick = !spaceHand && altPicks(tool) && (altHeld || e.altKey);
    const at: Tool = altPick ? "pipette" : activeTool;
    // Starting a new selection while floating bakes the current float first.
    if (isSelectTool(at) && floatRef.current) commitFloat();

    drag.current = { tool: at, last: img, panFrom: { ...pan }, startClient: { x: e.clientX, y: e.clientY } };
    if (at === "brush" || at === "erase") { pushHistory(); beginStroke(at, img.x, img.y); redraw(); }
    if (at === "blur") { pushHistory(); stampBlur(img.x, img.y); redraw(); }
    // Paint-bucket behavior: a fill-tool click flood-fills the contiguous
    // similar-colored area under the cursor; dragging then widens/narrows the
    // tolerance live (see beginFlood/dragFlood).
    if (at === "fill") { beginFlood("fill", img.x, img.y, "replace"); return; }
    if (at === "pipette") {
      (drag.current as { altPick?: boolean }).altPick = altPick;
      // The pipette's own Alt picks the BACKGROUND; the brush's Alt IS the
      // pipette, and picks the paint colour.
      pickColor(img, !altPick && e.altKey, altPick && tool === "brush");
      return;
    }
    // Wand: flood-SELECT the similar-colored area; Shift extends and Alt
    // subtracts, overriding the bar's mode for this click.
    if (at === "wand") {
      const mode: SelMode = modeFor(e, wandMode);
      setGestureMode(mode);
      // Clicking INSIDE the current selection (in replace mode) clears it —
      // the quick way out after a wand pick, mirroring the marquee's
      // click-to-deselect.
      if (mode === "replace" && hasSelection && pointInSelection(img.x, img.y)) {
        clearSelection();
        return;
      }
      pushSelectionHistory();
      beginFlood("wand", img.x, img.y, mode);
      return;
    }
    if (isSelectTool(at)) {
      // A polygon in progress takes EVERY press as its own — a click adds a
      // corner, a drag a freehand stretch — before the border test below,
      // which would otherwise read a corner placed near the outline of the
      // selection being replaced as a request to move that selection.
      if (polyRef.current && selStyle === "lasso" && pending.current) {
        (drag.current as any).polyStep = pending.current.pts.length;
        return;
      }
      // Dragging from the selection outline repositions the mask itself
      // (Photoshop's marquee-move) instead of starting a new selection.
      if (!e.shiftKey && !e.altKey && onSelectionBorder(sx, sy, true)) {
        (drag.current as any).kind = "maskmove";
        (drag.current as any).startImg = img;
        // No clone, and no writes to the mask until the release — see
        // `maskShift`. The cached screen-scale copy is invalidated here
        // because the mask may have changed since the last move.
        maskShift.current = { x: 0, y: 0 };
        shiftKeyRef.current = "";
        return;
      }
      const effMode: SelMode = modeFor(e, selMode);
      setGestureMode(effMode);
      // ONE history entry per GESTURE, pushed at the press — including the
      // FIRST selection on a clean canvas, whose "before" is "nothing
      // selected" and is exactly the state undo has to be able to return to.
      // `hadSel` is what lets a click that changed nothing drop it again.
      (drag.current as any).hadSel = hasSelection;
      (drag.current as any).pushed = pushSelectionHistory();
      pending.current = { pts: [img], rect: { x: img.x, y: img.y, w: 0, h: 0 } };
      (drag.current as any).mode = effMode;
      // WHAT WAS ALREADY DOWN — a latch, not a fact about the whole drag.
      // Each modifier has two jobs: held at the press, Alt is "subtract" and
      // Shift is "extend" (both above); pressed AFTER the drag has begun they
      // ask for the SHAPE instead — Alt draws out from the centre, Shift
      // constrains to a square. `e.altKey` in the move handler cannot tell a
      // key that was held from one just pressed, so the press records which
      // were spent on the mode — and `onKeyUp` clears the latch the moment one
      // is let go, which is what lets the same key be pressed again for the
      // shape.
      (drag.current as any).altAtStart = e.altKey;
      (drag.current as any).shiftAtStart = e.shiftKey;
    }
    if (at === "text") {
      // The same three modifiers as the marquee, for the same reason: the
      // bar's mode is what you set for a run of picks, Shift and Alt are for
      // the one you are making now.
      (drag.current as any).mode = modeFor(e, selMode);
      setGestureMode((drag.current as any).mode);
      (drag.current as any).hadSel = hasSelection;
      (drag.current as any).pushed = pushSelectionHistory();
      pending.current = { pts: [img], rect: { x: img.x, y: img.y, w: 0, h: 0 } };
    }
    if (at === "crop") {
      pending.current = null;
      // Grabbing a handle of the existing rect adjusts it; anywhere else
      // starts drawing a new rect.
      const ch = hitCropHandle(img.x, img.y);
      if (ch && cropRect) {
        (drag.current as any).kind = "cropadj";
        (drag.current as any).cropHandle = ch;
        (drag.current as any).startImg = img;
        (drag.current as any).rect0 = { ...cropRect };
        (drag.current as any).angle0 = cropAngle;
        return;
      }
      setCropRect(cropDragRect(img, img));
      (drag.current as any).draw = "crop";
    }
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = drag.current;
      if (!d) return;
      // Fill/wand: the drag adjusts the flood tolerance instead of painting.
      if (floodDrag.current) {
        dragFlood(e.clientX - d.startClient.x, e.clientY - d.startClient.y);
        return;
      }
      const img = toImg(e.clientX, e.clientY);
      const kind = (d as any).kind as string | undefined;
      // Move / transform a floating selection.
      if (kind === "floatmove") {
        const f = floatRef.current;
        let cx = (d as any).cx0 + (img.x - (d as any).startImg.x);
        let cy = (d as any).cy0 + (img.y - (d as any).startImg.y);
        // Same whole-pixel snap as the transform box's move (no blur on apply).
        if (f && f.rot === 0) {
          const w = f.w0 * f.scaleX, h = f.h0 * f.scaleY;
          cx = Math.round(cx - w / 2) + w / 2;
          cy = Math.round(cy - h / 2) + h / 2;
        }
        updateFloat({ cx, cy });
        return;
      }
      // Repositioning the selection mask (drag started on its outline). The
      // mask is not touched — only where it is DRAWN moves, until the release.
      if (kind === "maskmove") {
        maskShift.current = {
          x: Math.round(img.x - (d as any).startImg.x),
          y: Math.round(img.y - (d as any).startImg.y),
        };
        redraw();
        return;
      }
      // Adjusting the crop rect via its handles (resize / rotate / move).
      if (kind === "cropadj") {
        const ch = (d as any).cropHandle as CropHandle;
        const r0 = (d as any).rect0 as Rect;
        const a0 = (d as any).angle0 as number;
        const g0 = cropGeomOf(r0, a0);
        if (ch === "move") {
          let nx = r0.x + (img.x - (d as any).startImg.x) / dims.w;
          let ny = r0.y + (img.y - (d as any).startImg.y) / dims.h;
          if (a0 % 360 === 0) {
            nx = Math.min(1 - r0.w, Math.max(0, nx));
            ny = Math.min(1 - r0.h, Math.max(0, ny));
          }
          setCropRect({ ...r0, x: nx, y: ny });
        } else if (ch === "rot") {
          let deg = (Math.atan2(img.y - g0.cy, img.x - g0.cx) + Math.PI / 2) * 180 / Math.PI;
          while (deg > 180) deg -= 360;
          while (deg < -180) deg += 360;
          setCropAngle(Math.max(-45, Math.min(45, Math.round(deg * 10) / 10)));
        } else {
          // Corner/edge drag: the opposite corner (resp. edge) stays fixed in
          // the rect's own (rotated) frame; the cursor defines the new
          // diagonal — an edge handle only moves its own axis.
          const sx = ch === "ne" || ch === "se" || ch === "e" ? 1
            : ch === "nw" || ch === "sw" || ch === "w" ? -1 : 0;
          const sy = ch === "se" || ch === "sw" || ch === "s" ? 1
            : ch === "ne" || ch === "nw" || ch === "n" ? -1 : 0;
          const fixed = { x: -sx * g0.hw, y: -sy * g0.hh };
          const loc = toCropLocal(g0, img.x, img.y);
          // A zero sign keeps that axis's center and extent untouched — unless
          // a ratio is locked, where an edge handle has to move the other pair
          // of edges too. `resizeLocal` owns both rules.
          // The picture's edges in the rect's own frame, so a locked resize
          // stops at them (only meaningful un-rotated, which is also the only
          // case below that clamps).
          const bounds = a0 % 360 === 0
            ? { minX: -g0.cx, maxX: dims.w - g0.cx, minY: -g0.cy, maxY: dims.h - g0.cy }
            : undefined;
          const { w, h, midX, midY } = resizeLocal(sx, sy, g0.hw, g0.hh, loc, cropAspect, bounds);
          const mid = fromCropLocal(g0, midX, midY);
          let rect: Rect = {
            x: (mid.x - w / 2) / dims.w, y: (mid.y - h / 2) / dims.h,
            w: w / dims.w, h: h / dims.h,
          };
          if (a0 % 360 === 0) {
            // Held inside the picture ABOUT THE FIXED SIDE, so a locked crop
            // shrinks against the edge instead of being clipped out of shape.
            const anchor = fromCropLocal(g0, fixed.x, fixed.y);
            rect = clampRect(rect, cropAspect,
              { x: anchor.x / dims.w, y: anchor.y / dims.h });
          }
          setCropRect(rect);
        }
        return;
      }
      if (kind === "xform") {
        const f = floatRef.current;
        if (!f) return;
        const handle = (d as any).handle as HandleId;
        const xf = xformRef.current;
        const r = viewRef.current!.getBoundingClientRect();
        const sx = e.clientX - r.left, sy = e.clientY - r.top;
        if (handle === "move") {
          let cx = (d as any).cx0 + (img.x - (d as any).startImg.x);
          let cy = (d as any).cy0 + (img.y - (d as any).startImg.y);
          // Snap the (un-rotated) float's top-left to whole pixels, so the
          // moved content doesn't land between pixels and blur when applied.
          if (f.rot === 0) {
            const w = f.w0 * f.scaleX, h = f.h0 * f.scaleY;
            cx = Math.round(cx - w / 2) + w / 2;
            cy = Math.round(cy - h / 2) + h / 2;
          }
          updateFloat({ cx, cy });
        } else if (handle === "rot") {
          const cxS = xf.ox + f.cx * xf.scale, cyS = xf.oy + f.cy * xf.scale;
          updateFloat({ rot: Math.atan2(sy - cyS, sx - cxS) + Math.PI / 2 });
        } else if (e.altKey || !(d as any).fixImg) {
          // Alt: scale about the CENTER — the per-axis ratio of the current
          // grab distance to the initial one.
          const loc = localToFloat(f, sx, sy);
          const l0 = (d as any).loc0 as { x: number; y: number };
          let rx = Math.abs(l0.x) > 2 ? Math.abs(loc.x / l0.x) : 1;
          let ry = Math.abs(l0.y) > 2 ? Math.abs(loc.y / l0.y) : 1;
          if (e.shiftKey) rx = ry = Math.max(rx, ry);
          updateFloat({
            cx: (d as any).cx0, cy: (d as any).cy0,
            scaleX: Math.max(0.02, (d as any).sx0 * rx),
            scaleY: Math.max(0.02, (d as any).sy0 * ry),
          });
        } else {
          // Default (Photoshop-style): the OPPOSITE corner/edge stays fixed;
          // the dragged handle follows the cursor. Work in the float's
          // rotated frame anchored at that fixed point. Edge handles (one
          // zero sign component) move only their own axis.
          const fix = (d as any).fixImg as { x: number; y: number };
          const sign = (d as any).csign as { x: number; y: number };
          const edgeY = sign.x === 0;   // n/s: width untouched
          const edgeX = sign.y === 0;   // e/w: height untouched
          const c = Math.cos(-f.rot), s = Math.sin(-f.rot);
          const vx = img.x - fix.x, vy = img.y - fix.y;
          let dx = vx * c - vy * s;
          let dy = vx * s + vy * c;
          // Snap the dragged handle to whole pixels while un-rotated, so a
          // resize keeps every edge on the pixel grid (no blur on apply).
          if (f.rot === 0) { dx = Math.round(dx); dy = Math.round(dy); }
          // Work with ABSOLUTE sizes; a flip (negative scale) is re-applied
          // to the resulting scales below so resizing never unflips a
          // mirrored float.
          let w = edgeY ? Math.abs(f.w0 * f.scaleX) : Math.max(1, Math.abs(dx));
          let h = edgeX ? Math.abs(f.h0 * f.scaleY) : Math.max(1, Math.abs(dy));
          if (e.shiftKey && !edgeX && !edgeY) {
            const u = Math.max(w / f.w0, h / f.h0);
            w = u * f.w0; h = u * f.h0;
          }
          // Keep the box on the cursor's side of the anchor (no mirror). An
          // edge anchor is the opposite edge's MIDPOINT, so the untouched
          // axis contributes no center offset.
          const sgx = edgeY ? 0 : (dx === 0 ? sign.x : Math.sign(dx));
          const sgy = edgeX ? 0 : (dy === 0 ? sign.y : Math.sign(dy));
          const cc = Math.cos(f.rot), cs = Math.sin(f.rot);
          const lx = sgx * (w / 2), ly = sgy * (h / 2);
          updateFloat({
            cx: fix.x + lx * cc - ly * cs,
            cy: fix.y + lx * cs + ly * cc,
            scaleX: (f.scaleX < 0 ? -1 : 1) * Math.max(0.02, w / f.w0),
            scaleY: (f.scaleY < 0 ? -1 : 1) * Math.max(0.02, h / f.h0),
          });
        }
        return;
      }
      if (d.tool === "hand") {
        setPan({ x: d.panFrom.x + (e.clientX - d.startClient.x), y: d.panFrom.y + (e.clientY - d.startClient.y) });
        return;
      }
      if (d.tool === "zoom") {
        setZoomRect(normRect(d.last, img));
        return;
      }
      if (d.tool === "pipette") {
        const altPick = !!(d as { altPick?: boolean }).altPick;
        pickColor(img, !altPick && e.altKey, altPick && tool === "brush");
        return;
      }
      if (d.tool === "brush" || d.tool === "blur" || d.tool === "erase") {
        // A STAMP EVERY `spacing` PIXELS OF TRAVEL, with the remainder carried
        // to the next event. It used to be `max(1, distance / spacing)` stamps
        // spread over each move, which makes the paint a fact about how many
        // mousemoves the browser delivers rather than about where the pointer
        // went: a move SHORTER than the spacing still got a stamp (so a slow
        // or jittery hand piled them up and the stroke went blotchy), and a
        // move LONGER than it got `floor()` stamps spread over the whole
        // distance (so a fast one thinned out, up to half density). Neither
        // was noticeable while the editor dropped frames and the pointer
        // events arrived coalesced and evenly spaced; the moment it kept up,
        // it painted whatever the event rate happened to be.
        const put = d.tool === "blur" ? stampBlur : strokeStamp;
        const st = strokeRef.current;
        const spacing = d.tool === "blur"
          ? Math.max(1, tips.blur.size / 4)
          : Math.max(1, st?.spacing ?? tips[d.tool].size / 3);
        const dx = img.x - d.last.x, dy = img.y - d.last.y;
        const dist = Math.hypot(dx, dy);
        // The blur tool has no `strokeRef`, so its remainder lives on the drag.
        const carried = (d.tool === "blur" ? (d as any).carry : st?.carry) ?? 0;
        let travelled = carried + dist;
        for (let at = spacing - carried; travelled >= spacing; at += spacing) {
          put(d.last.x + (dx * at) / dist, d.last.y + (dy * at) / dist);
          travelled -= spacing;
        }
        if (d.tool === "blur") (d as any).carry = travelled;
        else if (st) st.carry = travelled;
        d.last = img;
        redraw();
        return;
      }
      if (isSelectTool(d.tool)) {
        if (selStyle === "lasso") pending.current!.pts.push(img);
        // `marqueeRect` is the four shapes the two modifiers make between
        // them; which key means which is decided here, from what was held at
        // the press.
        else pending.current!.rect = marqueeRect(d.last, img, {
          fromCentre: e.altKey && !(d as any).altAtStart,
          square: e.shiftKey && !(d as any).shiftAtStart,
        });
        redraw();
        return;
      }
      if (d.tool === "text") {
        // The band, in the same shape the select tool drags — it is drawn
        // (the rubber band) but never committed: what lands in the mask is
        // the BOXES it touched.
        pending.current!.rect = normRect(d.last, img);
        redraw();
        return;
      }
      if (d.tool === "crop") {
        setCropRect(cropDragRect(d.last, img));
        return;
      }
    };
    const onUp = (e: MouseEvent) => {
      // The control goes back to reporting what the KEYS would do — unless a
      // lasso is still being built out of clicks, which is one gesture across
      // several presses and keeps the mode its first click chose.
      if (!polyRef.current) setGestureMode(null);
      // THE GESTURE IS OVER BEFORE ANYTHING BELOW RUNS. What follows bakes the
      // stroke and commits the selection, and every redraw it triggers must
      // see the new picture and the new mask rather than the caches.
      gestureRef.current = false;
      const d = drag.current;
      if (floodDrag.current) { endFlood(); drag.current = null; return; }
      // Crop tool: a click that never dragged clears the crop rect (the
      // mousedown seeded a zero-size rect at the click point).
      if (d && d.tool === "crop" && !(d as any).kind) {
        const moved = Math.hypot(e.clientX - d.startClient.x, e.clientY - d.startClient.y) > 3;
        if (!moved) setCropRect(null);
      }
      // Float move/transform drags (kind "floatmove"/"xform") just end — the
      // result stays live until Apply/Enter or a click outside the box. They
      // must NOT fall into the select branch below: its commitSelection call
      // would dereference the null pending shape, and the throw would leave
      // drag.current armed forever (every later mousemove kept transforming).
      if (d && (d as any).kind === "maskmove") {
        // Bake the move into the mask, once, through a reused scratch: a
        // canvas cannot be cleared and then redrawn from itself.
        const sh = maskShift.current;
        maskShift.current = null;
        drag.current = null;
        if (sh && (sh.x || sh.y)) {
          // UNDOABLE, like every other selection change — and pushed HERE
          // rather than at the press, which is the whole reason it is cheap:
          // the mask is not touched until this moment, so at the release it
          // still holds the pre-move selection and the snapshot is the state
          // undo has to return to. Pushing at the press would have meant
          // taking the snapshot before knowing whether the gesture moved
          // anything at all, and `captureSnap` clones the picture as well as
          // the mask.
          pushSelectionHistory();
          const m = maskRef.current;
          let bake = maskBakeRef.current;
          if (!bake || bake.width !== m.width || bake.height !== m.height) {
            bake = document.createElement("canvas");
            bake.width = m.width; bake.height = m.height;
            maskBakeRef.current = bake;
          }
          const bc = bake.getContext("2d")!;
          bc.clearRect(0, 0, bake.width, bake.height);
          bc.drawImage(m, sh.x, sh.y);
          // SWAPPED, not copied back: the moved mask IS the mask now and the
          // old one becomes the next move's scratch — two image-sized
          // operations at the release instead of four. Replacing `maskRef`
          // wholesale is what restoring a selection from history already does.
          maskRef.current = bake;
          maskBakeRef.current = m;
        }
        redraw();
        return;
      }
      if (d && (d as any).kind) {
        drag.current = null;
        return;
      }
      if (d && d.tool === "pipette") endPick();
      if (d && (d.tool === "brush" || d.tool === "erase")) {
        endStroke();
        redraw();
      }
      if (d && isSelectTool(d.tool)) {
        const moved = Math.hypot(e.clientX - d.startClient.x, e.clientY - d.startClient.y) > 3;
        const shape = pending.current!;
        if ((d as any).polyStep != null) {
          // A step of a polygon in progress. A drag left its freehand points
          // on the outline already; a click is a corner — placed ONCE, at the
          // press, with the jitter the move handler recorded under the click
          // threshold taken off again — unless it is the click that CLOSES:
          // the second of a double-click (its first already placed the
          // corner), or one landing on the first corner.
          if (moved) { drag.current = null; redraw(); return; }
          shape.pts.length = (d as any).polyStep;
          const first = shape.pts[0];
          const sx = originX() + first.x * scale, sy = originY() + first.y * scale;
          const onFirst = shape.pts.length >= 3
            && Math.hypot(e.clientX - viewRef.current!.getBoundingClientRect().left - sx,
                          e.clientY - viewRef.current!.getBoundingClientRect().top - sy)
               <= POLY_CLOSE_PX;
          if (e.detail >= 2 || onFirst) finishPoly();
          else { shape.pts.push(toImg(e.clientX, e.clientY)); redraw(); }
          drag.current = null;
          return;
        }
        if (!moved && selStyle === "lasso") {
          // The first corner of a lasso built by clicks (see `polyRef`). The
          // clear at the top of this handler ran before there was a polygon to
          // see, so the lock is taken again here: the outline is one gesture
          // however many presses it takes, and its mode is this click's.
          polyRef.current = { mode: (d as any).mode, hadSel: (d as any).hadSel,
                              pushed: (d as any).pushed };
          setGestureMode((d as any).mode);
          shape.pts.length = 1;
          redraw();
          drag.current = null;
          return;
        }
        if (!moved) clearSelection(false);
        else commitSelection(shape, (d as any).mode);
        // A click on empty canvas with nothing selected changed nothing.
        if (!moved && !(d as any).hadSel && (d as any).pushed) dropSelectionHistory();
        pending.current = null;
        redraw();
      }
      if (d && d.tool === "text") {
        // A CLICK takes the box under the pointer, a DRAG every box the band
        // touched — the select tool's two gestures, told apart the same way.
        // What they produce is an ordinary selection: the boxes are simply
        // where it comes from, so Fill, Inpaint and Crop work on it exactly
        // as they do on one drawn by hand.
        const moved = Math.hypot(e.clientX - d.startClient.x,
                                 e.clientY - d.startClient.y) > 3;
        // The band is in image PIXELS and a box is in fractions of the file.
        const px = pending.current?.rect ?? null;
        const band = px && { x: px.x / dims.w, y: px.y / dims.h,
                             w: px.w / dims.w, h: px.h / dims.h };
        const at = toImg(e.clientX, e.clientY);
        const hits = textLeavesRef.current.filter((leaf) => moved
          ? band != null && quadTouchesRect(leaf.quad, band)
          : inQuad(at.x / dims.w, at.y / dims.h, leaf.quad));
        const mode: SelMode = (d as any).mode;
        if (!moved && !hits.length && mode === "replace") clearSelection(false);
        else if (hits.length) {
          // A RUN OF BOXES IS ONE SHAPE, and for INTERSECT that distinction is
          // the whole answer: the boxes are unioned first and the selection
          // meets that union once. Intersecting box by box would meet each box
          // with what the box before it left, and two boxes that do not
          // overlap each other leave nothing at all.
          const before = mode === "intersect" && hits.length > 1
            ? cloneCanvas(maskRef.current) : null;
          hits.forEach((leaf, i) => commitSelection(
            { pts: leaf.quad.map(([x, y]) => ({ x: x * dims.w, y: y * dims.h })) },
            // ONE commit for the run: `replace` clears the mask, so committing
            // box by box in that mode would leave only the last one. After the
            // first, every box ADDS; subtract stays itself (each box has to
            // meet the mask the run started from).
            i === 0 ? (before ? "replace" : mode)
              : (mode === "subtract" ? "subtract" : "extend"),
            // A POLYGON, whatever the marquee is set to. Without this the
            // commit took the rect branch, found no `rect`, drew nothing —
            // and still flipped `hasSelection`, so the canvas dimmed for a
            // selection that was not there.
            "lasso"));
          if (before) {
            const mctx = maskRef.current.getContext("2d")!;
            mctx.save();
            mctx.globalCompositeOperation = "destination-in";
            mctx.drawImage(before, 0, 0);
            mctx.restore();
            setHasSelection(maskBBox() != null);
          }
        }
        if (!hits.length && !moved && !(d as any).hadSel && (d as any).pushed) {
          dropSelectionHistory();
        }
        pending.current = null;
        redraw();
      }
      if (d && d.tool === "zoom") {
        // Click = step zoom at the point (Alt zooms out); drag = zoom into the
        // marquee (Alt: step out from its center) — Photoshop-style.
        const moved = Math.hypot(e.clientX - d.startClient.x, e.clientY - d.startClient.y) > 4;
        const rect = viewRef.current!.getBoundingClientRect();
        if (!moved) {
          zoomAt({ x: d.startClient.x - rect.left, y: d.startClient.y - rect.top },
                 e.altKey ? 0.5 : 2);
        } else {
          const r = normRect(d.last, toImg(e.clientX, e.clientY));
          if (e.altKey) {
            const cx = originX() + (r.x + r.w / 2) * scale;
            const cy = originY() + (r.y + r.h / 2) * scale;
            zoomAt({ x: cx, y: cy }, 0.5);
          } else {
            zoomToRect(r);
          }
        }
        setZoomRect(null);
      }
      drag.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    // `cropAspect` belongs here for the reason `cropAngle` does: the drag
    // handlers read it, so a listener registered before the ratio changed
    // would go on cropping to the old shape.
  }, [tool, selStyle, tips, blurStrength, color, hasSelection, dims, scale, pan, cropAngle, cropAspect]);

  // Wheel zoom pivots on the cursor: the image point under the mouse stays
  // put (zoomAt adjusts the pan accordingly), instead of zooming from center.
  // The canvas has nothing of its own to scroll, so EVERY wheel over it is the
  // picture's — including a ctrl+wheel, which the browser would otherwise read
  // as "zoom the page" (`useWheel` is what makes the refusal stick).
  useWheel(canvasBoxRef, (e) => {
    e.preventDefault();
    const r = canvasBoxRef.current?.getBoundingClientRect();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    if (r) zoomAt({ x: e.clientX - r.left, y: e.clientY - r.top }, factor);
    else setZoom((z) => Math.max(0.1, Math.min(8, z * factor)));
  });

  // ---- keyboard ----
  // Keep the latest handlers in a ref so the once-mounted listener never goes
  // stale (undo/redo close over fresh state each render).
  // Held-tool-shortcut state for spring-loaded tool switching.
  const springRef = useRef<{ key: string; prev: Tool; at: number } | null>(null);
  const save = () => { if (dirtyRef.current && !busy) void doSave(); };
  const hasCrop = tool === "crop" && cropRect != null;
  const clearCrop = () => { setCropRect(null); setCropAngle(0); };
  // Picking a ratio RESHAPES the rectangle that is already there rather than
  // waiting for the next drag: the point of choosing one is the crop on
  // screen, and a lock that only takes effect later reads as one that does
  // nothing. Going back to Free leaves the rect exactly as it stands.
  const pickCropAspect = (id: string, custom?: CustomAspect) => {
    setCropAspectId(id);
    if (custom) setCropCustom(custom);
    const ratio = aspectRatio(id, dims, custom ?? cropCustom);
    if (cropRect && ratio) setCropRect(fitRectToAspect(cropRect, ratio, dims));
  };
  // Picking Custom over an existing rect SEEDS the fields from the shape on
  // screen rather than emptying them: the rectangle you are looking at is
  // the likeliest thing you want to hold, and two blank fields ask a
  // question the crop has already answered.
  const seedCustom = (): CustomAspect => {
    const r = cropRect;
    if (!r || !(r.w > 0) || !(r.h > 0)) return cropCustom;
    return { w: String(Math.round(r.w * dims.w)),
             h: String(Math.round(r.h * dims.h)) };
  };
  /** The rect the typed ratio is applied TO, beside the rect that produced.
   *
   *  EVERY keystroke reshapes from the base, never from the last preview —
   *  the adjust panel's snapshot rule, and here it is the difference
   *  between a usable field and one that eats the crop: `fitRectToAspect`
   *  fits INSIDE what it is given, so typing "1920" then "1080" would
   *  shrink the rectangle once per digit and leave a sliver.
   *
   *  What says the snapshot is still good is the rect ON SCREEN being the
   *  one this last produced. That covers the whole edit rather than one
   *  field — moving from the width box to the height box is the middle of
   *  one ratio, not the end of an edit — and it re-snapshots by itself the
   *  moment the crop changes any other way (a fresh drag, a handle, To
   *  Selection), with no call site having to remember to say so. */
  const customBase = useRef<{ base: Rect; out: Rect } | null>(null);
  const sameRect = (a: Rect, b: Rect) =>
    a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
  const typeCustom = (next: CustomAspect) => {
    setCropCustom(next);
    const ratio = aspectRatio(CUSTOM_ID, dims, next);
    const mem = customBase.current;
    const base = mem && cropRect && sameRect(cropRect, mem.out)
      ? mem.base : cropRect;
    if (!base || !ratio) return;
    const out = fitRectToAspect(base, ratio, dims);
    customBase.current = { base, out };
    setCropRect(out);
  };
  // Closing the ACTIVE TAB — the same thing its own ✕ does, guard and all,
  // rather than a second idea of what closing a tab means.
  const closeActiveTab = useCallback(() => {
    if (editorItemId == null) return;
    const id = editorItemId;
    // The active tab holds the live (possibly unsaved) buffer, so it takes the
    // save/discard/cancel prompt — exactly as pressing its own ✕ does.
    guardedClose(() => { pendingCrops.delete(id); closeEditorTab(id); });
  }, [editorItemId, closeEditorTab, guardedClose]);

  // Closing the WINDOW (Escape). With a second tab open that is a question
  // rather than an action — ⌘W used to answer it and could not be relied on
  // to arrive at all — so it is asked. With one tab the window is the tab, and
  // this is the guarded whole-editor close it always was.
  const requestClose = useCallback(() => {
    if (editorTabs.length > 1 && editorItemId != null) setCloseAsk(true);
    else closeGuardedAll();
  }, [editorTabs, editorItemId, closeGuardedAll]);

  const keyHandlers = useRef({ undo, redo, fill: eraseSelection, setTool: pickTool, close: requestClose, commitFloat, cancelFloat, save, tool, copySelection, cutSelection, pasteSelection, hasCrop, applyCrop, clearCrop, hasSelection, clearSelection, closeActiveTab, finishPoly, cancelPoly });
  keyHandlers.current = { undo, redo, fill: eraseSelection, setTool: pickTool, close: requestClose, commitFloat, cancelFloat, save, tool, copySelection, cutSelection, pasteSelection, hasCrop, applyCrop, clearCrop, hasSelection, clearSelection, closeActiveTab, finishPoly, cancelPoly };
  // Leaving the tool or the lasso style throws a half-built polygon away:
  // its corners are drawn in lasso style by the select tool and mean
  // nothing anywhere else.
  useEffect(() => { cancelPoly(); }, [tool, selStyle]);  // eslint-disable-line react-hooks/exhaustive-deps
  const modalOpenRef = useRef(false);
  modalOpenRef.current = refPick != null || closePrompt != null || pickerFor != null || growShrink != null || closeAsk;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // While typing in a text field (e.g. the add-tag input), let the field
      // handle every key itself — no tool shortcuts, and crucially no Backspace
      // firing the destructive fill/erase on the current selection.
      if (typingInEditor(e)) return;
      // A button or slider the mouse left focused must not take Space or
      // Enter for itself (Space would press it instead of panning, Enter
      // press it as well as applying): it gives the focus back first.
      if ((e.key === " " || e.key === "Enter") && isNonTextControl(e.target)) {
        e.preventDefault();
        e.target.blur();
      }
      // While a modal (reference picker, save prompt) is up, it owns the
      // keyboard — especially Escape, which must not also close the editor.
      if (modalOpenRef.current) return;
      const h = keyHandlers.current;
      // Held Space = temporary hand tool (pan), like Photoshop.
      if (e.key === " ") {
        e.preventDefault();
        if (!e.repeat) setSpaceHand(true);
        return;
      }
      if (e.key === "Alt") setAltHeld(true);
      if (e.key === "Shift") setShiftHeld(true);
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        e.shiftKey ? h.redo() : h.undo();
        return;
      }
      if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); h.redo(); return; }
      // ⌘/Ctrl+S saves (as a new file on the item); always swallow the
      // browser's own save dialog, even with nothing to save.
      if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); h.save(); return; }
      // ⌘/Ctrl+X/C/V: cut/copy the current selection, paste as a floating
      // selection in transform mode.
      if (mod && e.key.toLowerCase() === "c") { e.preventDefault(); h.copySelection(); return; }
      if (mod && e.key.toLowerCase() === "x") { e.preventDefault(); h.cutSelection(); return; }
      if (mod && e.key.toLowerCase() === "v") { e.preventDefault(); h.pasteSelection(); return; }
      if (mod) return; // leave other shortcuts alone
      // Enter bakes a floating selection (or applies a pending crop); Escape
      // cancels the transform (or clears the crop rect) — only with neither
      // active does it close the editor, guarding every tab's unsaved state.
      if (e.key === "Enter") {
        if (h.finishPoly()) { e.preventDefault(); }
        else if (floatRef.current) { e.preventDefault(); h.commitFloat(); }
        else if (h.hasCrop) { e.preventDefault(); h.applyCrop(); }
        return;
      }
      if (e.key === "Escape") {
        if (h.cancelPoly()) { e.preventDefault(); }
        else if (floatRef.current) { e.preventDefault(); h.cancelFloat(); }
        else if (h.hasCrop) { e.preventDefault(); h.clearCrop(); }
        else if (h.hasSelection) { e.preventDefault(); h.clearSelection(); }
        else h.close();
        return;
      }
      if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); h.fill(); return; }
      const t = TOOLS.find((t) => t.key.toLowerCase() === e.key.toLowerCase());
      if (t) {
        // Spring-loaded tools (Photoshop-style): a quick tap switches for
        // good; HOLDING the key uses the tool only while pressed — releasing
        // after >300 ms returns to the previous tool.
        if (!e.repeat && t.id !== h.tool && !springRef.current) {
          springRef.current = { key: e.key.toLowerCase(), prev: h.tool, at: Date.now() };
        }
        h.setTool(t.id);
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === " ") setSpaceHand(false);
      if (e.key === "Alt") setAltHeld(false);
      if (e.key === "Shift") setShiftHeld(false);
      // LETTING A MODIFIER GO MID-DRAG RE-ARMS IT. A key held at the press
      // chose the mode and is spent for that; once it has been RELEASED it is
      // free again, so pressing it a second time asks for the shape like any
      // other key pressed during the drag. Without this a marquee begun with
      // Shift (extend) could never be squared, and one begun with Alt
      // (subtract) could never be drawn from its centre — the one case where
      // the two jobs are genuinely both wanted.
      //
      // On the KEY event rather than the next mousemove: a hand that lets go
      // and presses again without moving would otherwise arm nothing, and
      // that is the natural way to do it.
      const d = drag.current as { altAtStart?: boolean; shiftAtStart?: boolean } | null;
      if (d) {
        if (e.key === "Alt") d.altAtStart = false;
        if (e.key === "Shift") d.shiftAtStart = false;
      }
      const sp = springRef.current;
      if (sp && e.key.toLowerCase() === sp.key) {
        springRef.current = null;
        if (Date.now() - sp.at > 300) keyHandlers.current.setTool(sp.prev);
      }
    };
    // Releasing keys outside the window (e.g. after ⌘-Tab) never fires keyup —
    // clear the held-key overrides when focus leaves.
    const onBlur = () => {
      setSpaceHand(false); setAltHeld(false); setShiftHeld(false);
      // Focus left with keys down, so they are released as far as this window
      // knows — including the mid-drag re-arm above, or a modifier the drag
      // began with would stay spent for the rest of it.
      const d = drag.current as { altAtStart?: boolean; shiftAtStart?: boolean } | null;
      if (d) { d.altAtStart = false; d.shiftAtStart = false; }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  // ---- save ----
  const doSave = async (mode: "overwrite" | "derived" = "overwrite"): Promise<boolean> => {
    // An effect still being previewed is what is on screen, so it is what a
    // save means — but the preview lives in the buffer with no undo entry
    // behind it. Commit it the way OK does, so the file and the history agree
    // about what was saved. (With no panel open this does nothing.)
    closeEffect(true);
    // A pending crop tab: the first save CREATES the item (discarding the
    // tab never creates anything).
    if (editorItemId != null && editorItemId < 0) {
      const pend = pendingCrops.get(editorItemId);
      if (!pend) return false;
      if (floatRef.current) commitFloat();
      setBusy(true);
      try {
        const blob: Blob = await new Promise((res) =>
          pixelRef.current.toBlob((b) => res(b!), "image/png")
        );
        // Compose the original crop box with any further un-rotated crops
        // made inside this tab (cropAcc tracks them within this buffer).
        let box = pend.box;
        if (box && cropAcc.current) {
          const a = cropAcc.current;
          box = { x: box.x + a.x * box.w, y: box.y + a.y * box.h, w: a.w * box.w, h: a.h * box.h };
        } else if (!cropAcc.current) {
          box = null;
        }
        const res = await api.cropToItem(pend.sourceItemId, blob, {
          source_file_id: pend.sourceFileId,
          box,
        });
        qc.invalidateQueries({ queryKey: ["items"] });
        qc.invalidateQueries({ queryKey: ["item"] });
        bumpLibrary();
        const pid = editorItemId;
        pendingCrops.delete(pid);
        setEditorItem(res.item_id);
        closeEditorTab(pid);
        setDirty(false);
        return true;
      } finally {
        setBusy(false);
      }
    }
    if (!item) return false;
    if (floatRef.current) commitFloat();
    setBusy(true);
    try {
      const blob: Blob = await new Promise((res) =>
        pixelRef.current.toBlob((b) => res(b!), "image/png")
      );
      const res = await api.editRaster(item.id, blob, {
        source_file_id: loadedFileId!,
        // A plain save adds a *new file* to this item and makes it active (the
        // prior version is kept intact); "Save to a new item" is the other
        // half the backend has always had — a standalone item linked back to
        // this one as its edit — which nothing offered until now.
        save_mode: mode,
        // The saved buffer's region within the source file, so the new file
        // records its crop and tag boxes stay aligned.
        crop: cropAcc.current,
      });
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["item"] });
      // Tell the main app window (and any others) to refresh, since they hold a
      // separate query cache.
      bumpLibrary();
      // Stay open on the item; it reloads with the new active file (which resets
      // the dirty flag via the load effect). Drop any file override so the
      // editor follows the just-saved file instead of re-loading the old one.
      setFileOverride(null);
      setEditorItem(res.item_id);
      savedStateId.current = stateId.current;
      setDirty(false);
      return true;
    } finally {
      setBusy(false);
    }
  };

  // The Inpaint action button (shared by the Select options and the Inpaint
  // tool). Disabled until the model is downloaded and there's a selection.
  // ONE Inpaint button; its dropdown picks the model — photographic big-lama
  // or the anime/illustration fine-tune (better line-art/tone continuation).
  // Anchor rect for the dropdown: the props bar clips overflow (it scrolls
  // horizontally), so the menu renders position:fixed at the button instead.
  const [inpaintMenu, setInpaintMenu] = useState(false);
  const inpaintMenuAnchor = useRef<HTMLButtonElement>(null);
  const inpaintMenuRect = useAnchorRect(inpaintMenuAnchor, inpaintMenu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(inpaintMenu, () => setInpaintMenu(false), { within: [inpaintMenuAnchor] });
  // ---- Detect text, from the tool's own bar --------------------------------
  // The engines that could read THIS file, with what is already happening to
  // it: a run that has finished (the tick), one in flight (its progress),
  // or nothing yet (press to start). Reading is a background JOB, not a
  // synchronous call like inpaint — a page takes seconds and the window must
  // stay usable — so the bar watches the job list rather than blocking.
  const { data: mlJobsData } = useQuery({
    queryKey: ["ml-jobs"], queryFn: api.mlJobs,
    // Poll only while something of ours is in flight; the enqueue below
    // invalidates this query, which is what starts the polling at all.
    refetchInterval: (q) => {
      const jobs = (q.state.data as { jobs: JobOut[] } | undefined)?.jobs ?? [];
      return jobs.some((j) => j.kind === "ocr"
        && (j.status === "queued" || j.status === "running")) ? 1200 : false;
    },
    // IN THE BACKGROUND TOO. React Query pauses an interval while the window
    // is unfocused, and reading a page is exactly the wait you spend
    // somewhere else — measured: the button stayed on "Reading…" long after
    // the job had finished, because nothing asked again (the same trap the
    // video render's progress records).
    refetchIntervalInBackground: true,
  });
  /** A queued/running OCR job over this item, by model. */
  const ocrJobFor = (model: string): JobOut | null =>
    (mlJobsData?.jobs ?? []).find((j) => j.kind === "ocr" && j.model === model
      && j.item_id === editorItemId
      && (j.status === "queued" || j.status === "running")) ?? null;
  // WHEN A READING FINISHES, the boxes have to arrive. The library's own
  // sweep runs off `JobList`, which is a component this window covers and
  // does not contain — so the editor watches its own count of in-flight OCR
  // jobs and refetches the tree the moment it drops. Without it the tool sat
  // on the reading it had when the window opened.
  const ocrBusyCount = (mlJobsData?.jobs ?? []).filter(
    (j) => j.kind === "ocr" && j.item_id === editorItemId
      && (j.status === "queued" || j.status === "running")).length;
  const ocrBusyWas = useRef(0);
  useEffect(() => {
    if (ocrBusyCount < ocrBusyWas.current) {
      qc.invalidateQueries({ queryKey: ["text", editorItemId] });
      qc.invalidateQueries({ queryKey: ["item", editorItemId] });
      bumpLibrary();
    }
    ocrBusyWas.current = ocrBusyCount;
  }, [ocrBusyCount, editorItemId, qc]);
  const [detectMenu, setDetectMenu] = useState(false);
  const detectMenuAnchor = useRef<HTMLButtonElement>(null);
  const detectMenuRect = useAnchorRect(detectMenuAnchor, detectMenu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(detectMenu, () => setDetectMenu(false), { within: [detectMenuAnchor] });
  const ocrModels = useMemo(
    () => (mlModelList?.tasks ?? []).find((tk) => tk.kind === "ocr")?.models ?? [],
    [mlModelList]);
  const startDetect = async (model: string) => {
    if (editorItemId == null || editorItemId < 0) return;
    setDetectMenu(false);
    try {
      await api.enqueueJobs("ocr" as JobKind, model, [editorItemId]);
      // Starting the poll above, and the sweep that lands the result: the
      // job list is what notices a finish (`AiActionButtons`' lesson).
      qc.invalidateQueries({ queryKey: ["ml-jobs"] });
    } catch (e) {
      setOpErr((e as Error).message || "Could not start the reading");
    }
  };
  const detectButton = () => {
    const running = ocrModels.map((m) => ocrJobFor(m.id)).filter(Boolean) as JobOut[];
    const busyOne = running[0] ?? null;
    return (
      <div key="detect">
        <button ref={detectMenuAnchor}
          onClick={() => setDetectMenu((v) => !v)}
          title="Read the text on this picture"
          style={{ display: "flex", alignItems: "center", gap: 6, height: 34, padding: "0 12px", borderRadius: "var(--r-4)", border: "none", background: "var(--bg-deep)", color: "var(--text-2)", fontSize: "var(--fs-3)", cursor: "pointer" }}>
          <Icon name={busyOne ? "progress_activity" : "document_scanner"} size={17}
            spin={!!busyOne} />
          {busyOne
            ? (busyOne.progress > 0 ? `Reading… ${busyOne.progress}%` : "Reading…")
            : "Detect text"}
          <Icon name="expand_more" size={14} style={{ opacity: 0.7 }} />
        </button>
        {detectMenu && (
            <AnchoredDropdown rect={detectMenuRect} minWidth={280}>
              {ocrModels.length === 0 && (
                <div style={{ padding: "7px 9px", fontSize: "var(--fs-3)", color: "var(--muted)" }}>
                  No OCR engine is set up yet
                </div>
              )}
              {ocrModels.map((m) => {
                const job = ocrJobFor(m.id);
                const done = textEngines.includes(m.id);
                const ready = m.available;
                return (
                  <div
                    key={m.id}
                    className={ready && !job ? "hoverable" : undefined}
                    title={!ready ? "Set this model up in Settings → Actions"
                      : job ? "This reading is already running" : m.note}
                    // A RUNNING job is not a second offer. Pressing it again
                    // would queue an identical run over the same file, and
                    // the app would go on to reconcile a reading with itself.
                    onClick={() => { if (ready && !job) void startDetect(m.id); }}
                    style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 9px", borderRadius: "var(--r-2)", cursor: ready && !job ? "pointer" : "default", opacity: ready ? 1 : 0.5 }}
                  >
                    <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
                      <span style={{ fontSize: "var(--fs-3)", color: "var(--text-2)", fontWeight: 500 }}>
                        {m.variant || m.name}
                      </span>
                      {m.note && <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>{m.note}</span>}
                    </span>
                    {job ? (
                      <span style={{ flex: "0 0 auto", display: "flex", alignItems: "center", gap: 4, fontSize: "var(--fs-1)", color: "var(--accent)" }}>
                        <Icon name="progress_activity" size={14} spin />
                        {job.status === "running"
                          ? (job.progress > 0 ? `${job.progress}%` : "Reading…")
                          : "Queued"}
                      </span>
                    ) : done ? (
                      // Read already — shown, never disabled: re-reading is
                      // safe (reconciliation never loses a correction) and
                      // is the normal next step after editing the picture.
                      <Icon name="check" size={14} color="var(--muted-2)" />
                    ) : null}
                  </div>
                );
              })}
            </AnchoredDropdown>
          
)}
      </div>
    );
  };

  const inpaintButton = () => {
    const anyReady = inpaintReady || animeInpaintReady;
    // A MISSING MODEL DOES NOT DISABLE THE BUTTON. With nothing downloaded
    // the whole offer used to be a dead grey word — no menu, and nothing
    // saying that the two models exist or where to get them. It opens, and
    // each row inside says for itself whether it can run (the same rows the
    // Selection menu shows). What DOES disable it is having nothing to
    // inpaint: with no selection there is no area to fill, which is about
    // this picture rather than about this machine.
    const off = busy || !hasSelection;
    const title = !hasSelection ? "Make a selection first"
      : !anyReady ? "No inpainting model is downloaded yet"
      : "Fill the selected area — pick the model";
    const menuRow = (label: string, note: string, model: "big_lama" | "anime_lama", ready: boolean) => (
      <div
        key={model}
        className={ready ? "hoverable" : undefined}
        title={ready ? undefined : "Download this model in Settings → Actions"}
        onClick={() => { if (!ready) return; setInpaintMenu(false); void inpaintSelection(model); }}
        style={{ display: "flex", flexDirection: "column", gap: 1, padding: "6px 9px", borderRadius: "var(--r-2)", cursor: ready ? "pointer" : "default", opacity: ready ? 1 : 0.5 }}
      >
        <span style={{ fontSize: "var(--fs-3)", color: "var(--text-2)", fontWeight: 500 }}>{label}</span>
        <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>{note}</span>
      </div>
    );
    return (
      <div key="inpaint">
        <button ref={inpaintMenuAnchor}
          onClick={() => setInpaintMenu((v) => !v)}
          disabled={off} title={title}
          style={{ display: "flex", alignItems: "center", gap: 6, height: 34, padding: "0 12px", borderRadius: "var(--r-4)", border: "none", background: "var(--bg-deep)", color: off ? "var(--muted-3)" : "var(--text-2)", fontSize: "var(--fs-3)", cursor: off ? "default" : "pointer", opacity: off ? 0.6 : 1 }}>
          <Icon name="auto_fix_high" size={17} />{busy ? "Inpainting…" : "Inpaint"}
          <Icon name="expand_more" size={14} style={{ opacity: 0.7 }} />
        </button>
        {/* Portaled to <body>: the props bar is transformed (centering) and
            scrollable, which would both clip and re-anchor a fixed child. */}
        {inpaintMenu && (
            <AnchoredDropdown rect={inpaintMenuRect} minWidth={230}>
              {menuRow("Photo (big-lama)", "General-purpose LaMa inpainting", "big_lama", inpaintReady)}
              {menuRow("Anime / illustration", "Line-art & screentone fine-tune", "anime_lama", animeInpaintReady)}
            </AnchoredDropdown>
          
)}
      </div>
    );
  };

  const seg = (active: boolean): React.CSSProperties => ({
    width: 30, height: 28, borderRadius: "var(--r-2)", border: "none",
    background: active ? "var(--accent)" : "transparent",
    color: active ? "var(--on-accent)" : "var(--muted)", cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
  });
  /**
   * The tip-size slider, LOGARITHMIC — a brush runs 1…200 px and the small end
   * is where the choosing happens, so each doubling gets the same length of
   * track instead of the first twenty sizes sharing a tenth of it. The range
   * input works in track units; the number field beside it stays in PIXELS,
   * which is what `SliderProp`'s `inputValue`/`onInput` are for.
   */
  const sizeSlider = (key: "brush" | "erase" | "blur") => (
    <SliderProp label="Size" unit="px"
      value={logSliderPos(tips[key].size, SIZE_MIN, SIZE_MAX)} min={0} max={LOG_STEPS}
      onChange={(pos) => setTip(key, { size: logSliderValue(pos, SIZE_MIN, SIZE_MAX) })}
      inputValue={tips[key].size} inputMin={SIZE_MIN} inputMax={SIZE_MAX}
      onInput={(v) => setTip(key, { size: v })} />
  );

  /**
   * The selection-mode segmented control, drawn for the marquee, the text tool
   * and the wand off the one `SEL_MODES` table.
   *
   * IT SHOWS WHAT THE NEXT PRESS WOULD DO, not only what is set: hold Shift
   * and the lit button moves to Add, hold both and it moves to Intersect, and
   * letting go puts it back. The keys are then legible in the same place the
   * setting is, instead of being something to remember. A gesture in flight
   * LOCKS it (`gestureMode`) — from the press onwards those keys mean the
   * shape, so a control still following them would say the opposite of what
   * the drag is doing. Clicking still sets the real mode, whatever is held.
   */
  const modeButtons = (bar: SelMode, pick: (m: SelMode) => void) => {
    const shown = gestureMode
      ?? modeFor({ shiftKey: shiftHeld, altKey: altHeld }, bar);
    return (
      <div style={{ display: "flex", gap: 2, padding: 3, background: "var(--bg-deep)", borderRadius: "var(--r-4)" }}>
        {SEL_MODES.map((m) => (
          <button key={m.id} title={m.title} onClick={() => pick(m.id)} style={seg(shown === m.id)}>
            <Icon name={m.icon} size={18} />
          </button>
        ))}
      </div>
    );
  };

  // Floating overlays over the canvas (hint box, zoom controls). Uses themed
  // tokens so they read correctly in the editor's light and dark themes.
  const overlayBox: React.CSSProperties = {
    position: "absolute", display: "flex", alignItems: "center",
    background: "var(--surface-float)", border: "1px solid var(--border)",
    borderRadius: "var(--r-4)", boxShadow: "var(--shadow-1)",
  };
  // 100% is one picture pixel on one DEVICE pixel. A browser measures in CSS
  // pixels, so on a retina display a scale of 1 spreads each pixel over two of
  // the screen's — which is what made 100% look like 200%.
  const atActualSize = Math.abs(scale * dpr - 1) < 0.005;
  const actualZoom = 1 / (fit * dpr);

  return (
    <div style={{ position: "absolute", inset: 0, zIndex: 50, background: "var(--bg-deep)", display: "flex", flexDirection: "column" }}>
      {/* Tab bar (Photoshop-style), above the actions bar — HIDDEN for a single
          tab, like the annotator's. It was shown then too, on the argument
          that it is where the window says which item it is on and carries the
          ✕ that closes it; but the header says the name already (with the size
          under it), so on a one-item window the strip was a second copy of the
          title in a 34 px band across the top. The ✕ is in the header
          (`WindowCloseBtn`), which is what makes dropping this safe.
          The bottom line is an INSET shadow, not a border: the active tab's
          opaque background (same color as the header below) paints over it,
          so tab and header merge seamlessly while the line stays under the
          inactive tabs and the empty remainder of the bar. */}
      {editorTabs.length > 1 && (
        <div style={{ display: "flex", alignItems: "stretch", height: 34, flex: "0 0 34px", background: "var(--bg)", boxShadow: "inset 0 -1px 0 var(--border-soft)", overflowX: "auto" }}>
          {editorTabs.map((id) => (
            <EditorTab
              key={id}
              id={id}
              active={id === editorItemId}
              unsaved={id < 0 || (id === editorItemId && dirty)}
              onSelect={() => setEditorItem(id)}
              onClose={() => {
                const act = () => {
                  pendingCrops.delete(id);   // discarding a pending crop creates nothing
                  return editorTabs.length <= 1 ? closeEditor() : closeEditorTab(id);
                };
                // Only the active tab holds the live (possibly unsaved) buffer,
                // so guard just that one; other tabs close straight away.
                if (id === editorItemId) guardedClose(act); else act();
              }}
            />
          ))}
        </div>
      )}
      {/* actions bar */}
      <div style={{ height: 48, flex: "0 0 48px", background: "var(--panel)", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", padding: "0 12px", gap: 8 }}>
        {/* Undo/redo has left the header — it acts on the PICTURE, like the
            Image and Selection menus it used to sit apart from, so it belongs
            with them over the canvas (`CanvasBars`) and the header is left
            saying what the window is. It leads that row: an undo is the
            commonest thing done to a picture and the first thing reached for
            after anything else in it. */}
        {/* The window's two halves, BEFORE the name. It sat at the very end of
            the row, past Save, which put the control that changes everything
            below the header behind the one you reach for most — and left the
            header naming a mode only after it had offered actions on it.

            Leaving EDIT is the direction that can lose work, so it goes
            through the same save/discard/cancel prompt closing a dirty tab
            does — `guardedClose` is that prompt, and the "proceed" it runs is
            the mode switch. */}
        {editorItemId != null && (
          <>
            <ModeSwitch
              mode="edit"
              onPick={(m) => {
                if (m === "annotate" && editorItemId != null) {
                  guardedClose(() => setEditorMode(editorItemId, "annotate"),
                               "leave");
                }
              }}
              editIcon="edit"
              t={english}
            />
            <Divider />
          </>
        )}
        {/* The item's name, its size and the file chip. The ⋯ that used to
            follow them held one entry — Show in library — and closing the
            window already goes back there, so it was a menu for what the ✕
            beside it does. `HeaderActions` stays: it is what measures the name
            against the space the fixed sides leave over. */}
        <HeaderActions t={english} alwaysFolded actions={[]}>
          {/* Item name, with the size of the buffer UNDER it, then the
              file-number chip; clicking the CHIP opens the menu of all the
              item's files (picking one loads it, guarding unsaved edits).
              The size is the live buffer's, so it follows a crop or a resize
              as it is made. */}
          <ItemTitle
            name={isPending ? "New crop (unsaved)" : (item?.name ?? "")}
            title={isPending ? "New crop (unsaved)" : item?.name}
            subtitle={`${dims.w}×${dims.h}`}
          />
          {/* PORTALLED (`FileChip`): the header's lead clips its overflow so
              the name can ellipsise, and the menu — an absolutely-positioned
              child of it — was clipped to the chip, so clicking it looked like
              it did nothing. Films are left out: this editor cannot open one.
              A pending crop has no files at all yet. */}
          {!isPending && item && (
            <FileChip
              files={item.files.filter((f) => f.duration == null)}
              currentId={loadedFileId}
              onPick={(id: number) => guardedClose(() => setFileOverride(id))}
              t={english}
            />
          )}
        </HeaderActions>
        {/* Editor theme: follow the app, or hold this window light or dark —
            judging an image against the other background is why it exists. */}
        <ThemeMenu t={english} value={edTheme} onChange={setEdTheme} />
        <Divider />
        {/* Save (greyed until there are unsaved edits) with a chevron menu
            holding revert/close — there is no separate close button anymore
            (Escape and the window's own close still work). Saving always adds
            a new file and keeps the editor open. */}
        <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 1 }}>
          <button onClick={() => void doSave()} disabled={busy || !dirty} title={!dirty ? "No changes to save" : "Save as a new file"}
            style={{ display: "flex", alignItems: "center", gap: 6, height: 32, padding: "0 14px", borderRadius: "8px 0 0 8px", border: "none", background: (busy || !dirty) ? "var(--border-soft)" : "var(--accent)", color: (busy || !dirty) ? "var(--muted-3)" : "var(--on-accent)", fontWeight: 600, fontSize: "var(--fs-3)", cursor: (busy || !dirty) ? "default" : "pointer" }}>
            <Icon name="save" size={18} />{busy ? "Saving…" : "Save"}
          </button>
          <RowMenu always icon="expand_more" title="More save options" minWidth={230}
            buttonStyle={{ width: 24, height: 32, borderRadius: "0 8px 8px 0",
              background: (busy || !dirty) ? "var(--border-soft)" : "var(--accent)",
              color: (busy || !dirty) ? "var(--muted)" : "var(--on-accent)" }}
            actions={[
              // The other half of what a save can mean, and the backend has
              // had it all along (`save_mode: "derived"`): a standalone new
              // item carrying the edit, linked back to this one, in the same
              // groups. The plain Save adds a file to THIS item; this leaves
              // the original entirely alone. It opens as its own tab, so the
              // original stays where it was.
              { icon: "library_add", label: "Save to a new item",
                disabled: busy || isPending,
                hint: isPending
                  ? "This tab already becomes a new item when you save it"
                  : "Save the edits as a NEW item linked to this one, leaving the original untouched",
                onClick: () => void doSave("derived") },
              { icon: "history", label: "Revert to saved", disabled: !canRevert,
                hint: canRevert ? "Throw away the unsaved edits and return to the last saved state" : "No unsaved changes to revert",
                onClick: revertToSaved },
              // NO CLOSE AT ALL, destructive or otherwise. A plain "Close" went
              // first, for being a third way to do what the tab's ✕ and the
              // window's own control already do; "Discard changes & close" is
              // the same objection with a louder colour. This is a menu about
              // what happens to the EDITS — save them elsewhere, throw them
              // away — and the way OUT is the ✕, which asks about unsaved work
              // anyway and offers discarding there, at the moment it is
              // actually the question.
            ]} />
        </div>
        {/* The window's own ✕, LAST and with no divider before it: it ends the
            row rather than starting a group. This is the only visible way out
            now that a single tab shows no strip, so it asks what Escape asks
            (`requestClose`): with a second tab open, whether to close the
            WINDOW or just this tab. It used to close the window outright —
            the same press, on the same control, meaning "close everything" to
            the mouse and "which of them?" to the keyboard, and with several
            pictures open the mouse answer was the destructive one. Either
            answer still guards every unsaved buffer on its way out. */}
        <WindowCloseBtn t={english} onClose={requestClose} />
      </div>

      {/* body: canvas with the tool palette floating over it */}
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
        <div
          ref={canvasBoxRef}
          // Solid backdrop: the checkerboard is drawn only within the image's
          // bounds (see redraw), so the image's size/edges stay visible.
          style={{ flex: 1, position: "relative", overflow: "hidden", minHeight: 0, background: "var(--bg-deep)" }}
        >
          {/* Floating tool-properties bar (top, right of the vertical bars;
              hidden when the active tool has no props — the hand's help
              lives in the bottom bar). */}
          {(floating || TOOLS_WITH_PROPS.includes(tool)) && (
          <div
            className="mc-props-bar"
            onMouseDown={(e) => e.stopPropagation()}
            style={{
              // padding 4 on ALL edges; outer radius 12 = the children's
              // radius 8 + that padding, so the rounded corners run
              // concentric. height 42 = the tallest child (34) + 2×4.
              // Centred in what is LEFT of the top strip, not in the canvas:
              // the section bars (undo/redo, the menus) are pinned at the top
              // left now, and a bar centred on the whole width runs straight
              // into them on a narrow window — the one thing neither of two
              // floating things can notice about the other. `propsFrom` is
              // where the free space starts; the right margin stays 16.
              position: "absolute", top: 12,
              left: (propsFrom + Math.max(propsFrom + 80, box.w - 16)) / 2,
              transform: "translateX(-50%)",
              zIndex: 10, height: 42,
              boxSizing: "border-box",
              maxWidth: Math.max(80, box.w - 16 - propsFrom), overflowX: "auto",
              // gap matches the bar's own inset so the spacing reads even.
              display: "flex", alignItems: "center", padding: 4, gap: 4,
              background: "var(--surface-float)", border: "1px solid var(--border)",
              borderRadius: "var(--r-7)", boxShadow: "var(--shadow-2)",
            }}
          >
        {/* Floating-selection controls: bake or discard the move/transform. */}
        {floating && (
          <>
            <PropBtn icon="check" label="Apply" color="var(--green-text)" onClick={commitFloat} />
            <PropBtn icon="close" label="Cancel" color="var(--red-text)" onClick={cancelFloat} />
            <div style={{ width: 1, height: 24, flex: "0 0 1px", background: "var(--border-strong)" }} />
            {!floating.transforming && (
              <PropBtn icon="transform" label="Transform" onClick={() => updateFloat({ transforming: true })} />
            )}
            {/* Copy mode: the original pixels stay in place; the float becomes
                a duplicate instead of a cut-out. Meaningless for a pasted
                float — there is no original underneath. */}
            {!floating.pasted && (
            <PropBtn
              icon={floating.keep ? "check_box" : "check_box_outline_blank"}
              label="Keep original"
              title="Copy instead of cut — the source pixels stay in place when you apply"
              onClick={() => updateFloat({ keep: !floatRef.current?.keep })}
            />
            )}
            {floating.transforming && (
              <>
                <PropBtn icon="flip" label="Flip H" title="Mirror horizontally"
                  onClick={() => updateFloat({ scaleX: -(floatRef.current?.scaleX ?? 1) })} />
                <PropBtn icon="flip" iconRot={90} label="Flip V" title="Mirror vertically"
                  onClick={() => updateFloat({ scaleY: -(floatRef.current?.scaleY ?? 1) })} />
                <PropBtn icon="rotate_90_degrees_ccw" label="Rotate Left" title="Rotate a quarter turn counter-clockwise"
                  onClick={() => updateFloat({ rot: (floatRef.current?.rot ?? 0) - Math.PI / 2 })} />
                <PropBtn icon="rotate_90_degrees_cw" label="Rotate Right" title="Rotate a quarter turn clockwise"
                  onClick={() => updateFloat({ rot: (floatRef.current?.rot ?? 0) + Math.PI / 2 })} />
              </>
            )}
          </>
        )}
        {!floating && isSelectTool(tool) && (
          <>
            {/* The shape, for the MARQUEE alone: the lasso is a tool of its
                own now, so a third button here would be a second way to
                reach it that left the palette saying something else. */}
            {tool === "select" && (
            <div style={{ display: "flex", gap: 2, padding: 3, background: "var(--bg-deep)", borderRadius: "var(--r-4)" }}>
              {(["rect", "ellipse"] as const).map((st) => (
                <button key={st} title={st} onClick={() => setMarqueeStyle(st)} style={seg(marqueeStyle === st)}>
                  <Icon name={st === "rect" ? "crop_square" : "circle"} size={18} />
                </button>
              ))}
            </div>
            )}
            {modeButtons(selMode, setSelMode)}
            {hasSelection && <PropBtn icon="transform" label="Transform" onClick={() => beginFloat(true)} />}
            <PropBtn icon="flip" label="Invert" onClick={invertSelection} disabled={!hasSelection} title={hasSelection ? "Invert the selection (unselected areas become selected)" : "Make a selection first"} />
            <PropBtn icon="deselect" label="Clear" onClick={clearSelection} disabled={!hasSelection} title={hasSelection ? "Clear the selection" : "No selection"} />
            {/* Content-changing actions grouped at the end, behind a divider. */}
            <div style={{ width: 1, height: 24, flex: "0 0 1px", background: "var(--border-strong)" }} />
            <PropBtn icon="format_color_fill" label="Fill" onClick={fillSelection} />
            {inpaintButton()}
            <PropBtn icon="crop" label="Crop" onClick={cropSelectionNow} disabled={!hasSelection} title={hasSelection ? "Crop the image to the selection's bounding box" : "Make a selection first"} />
          </>
        )}
        {!floating && tool === "text" && (
          <>
            {/* READ IT, if nothing has — and the way to read it AGAIN with
                another engine. A tool that could only work on a page
                somebody had already been to the Text tab for was a tool
                that answered "nothing here" and left you to guess why. */}
            {detectButton()}
            {/* WHICH READING, when two engines have read the page — the Text
                tab's own control, in the Text tab's own words. One engine
                needs no dropdown. */}
            {textEngines.length > 1 && (
              <select
                value={textModel}
                onChange={(e) => {
                  setTextEngine(e.target.value);
                  // Remembered for the ITEM, so the sidebar and the
                  // annotator show the reading you just switched to.
                  rememberEngine(editorItemId, e.target.value);
                  e.target.blur();
                }}
                title="Show another model's reading"
                style={{
                  height: 34, borderRadius: "var(--r-4)", padding: "0 8px",
                  border: "none", background: "var(--bg-deep)",
                  color: "var(--text-2)", fontSize: "var(--fs-3)",
                }}>
                {textEngines.map((m) => (
                  <option key={m} value={m}>{mlLabel(m)}</option>
                ))}
              </select>
            )}
            {/* WHICH LEVEL is pickable, when the reading has more than one.
                "Smallest" is the default and stays first: it is what the
                removal mask uses, and on a mixed page it is the only answer
                that is right everywhere. */}
            {textLevels.length >= 1 && (
              <div style={{ display: "flex", gap: 2, padding: 3, background: "var(--bg-deep)", borderRadius: "var(--r-4)" }}>
                <button title="The smallest box each piece of text has"
                  onClick={() => setTextLevel(null)} style={seg(textLevel === null)}>
                  <span style={{ fontSize: "var(--fs-2)", fontWeight: 600, padding: "0 3px" }}>
                    Word
                  </span>
                </button>
                {textLevels.map((l) => (
                  <button key={l} title={LEVEL_TITLE[l]}
                    onClick={() => setTextLevel(l)} style={seg(textLevel === l)}>
                    <span style={{ fontSize: "var(--fs-2)", fontWeight: 600, padding: "0 3px" }}>
                      {LEVEL_LABEL[l]}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {modeButtons(selMode, setSelMode)}
            <PropBtn icon="select_all" label="All text"
              disabled={!hasText}
              title={hasText ? "Select every text box on this reading"
                : "Nothing has read this picture yet"}
              onClick={() => {
                pushSelectionHistory();
                textLeaves.forEach((leaf, i) => commitSelection(
                  { pts: leaf.quad.map(([x, y]) => ({ x: x * dims.w, y: y * dims.h })) },
                  i === 0 ? "replace" : "extend", "lasso"));
                redraw();
              }} />
            <PropBtn icon="deselect" label="Clear" onClick={clearSelection}
              disabled={!hasSelection}
              title={hasSelection ? "Clear the selection" : "No selection"} />
            {/* The reason to select text in the first place: paint it out.
                Same button as the select tool's, same warm LaMa endpoint. */}
            <div style={{ width: 1, height: 24, flex: "0 0 1px", background: "var(--border-strong)" }} />
            {inpaintButton()}
          </>
        )}
        {tool === "fill" && !floating && (
          <SliderProp label="Tolerance" value={fillTolerance} min={0} max={100} unit="%" onChange={setFillTolerance} />
        )}
        {tool === "wand" && !floating && (
          <>
            {modeButtons(wandMode, setWandMode)}
            <SliderProp label="Tolerance" value={wandTolerance} min={0} max={100} unit="%" onChange={setWandTolerance} />
            <NumberProp label="Grow" value={wandGrow} min={-500} max={500} unit="px"
              title={"Grow what the wand picks up by this many pixels before it "
                + "joins the selection — a negative number shrinks it. Only the "
                + "NEW area is grown: extending a selection leaves what was "
                + "already in it alone."}
              onChange={setWandGrow} />
            {/* The reason to wand-select a patch of sky, a speech balloon or
                a logo's background in the first place: paint it out. Same
                button as the select and text tools', same warm LaMa
                endpoint, behind the same divider that separates what
                changes PIXELS from what only changes the selection. */}
            <div style={{ width: 1, height: 24, flex: "0 0 1px", background: "var(--border-strong)" }} />
            {inpaintButton()}
          </>
        )}
        {tool === "brush" && (
          <>
            {sizeSlider("brush")}
            <SliderProp label="Hardness" value={tips.brush.hardness} min={0} max={100} unit="%" onChange={(v) => setTip("brush", { hardness: v })} />
            {/* OPACITY IS THE PAINT COLOUR'S ALPHA, not a second number beside
                it: the stroke is capped at the colour's alpha (see
                `strokeRef.alpha`), so a slider of its own would have been a
                duplicate that could disagree with the swatch. Moving this
                moves what the colour picker shows, and the other way about. */}
            <SliderProp label="Opacity" value={Math.round(splitAlpha(color).a * 100)}
              min={0} max={100} unit="%"
              onChange={(v) => setColor(withAlpha(color, v / 100))} />
          </>
        )}
        {tool === "erase" && (
          <>
            {sizeSlider("erase")}
            <SliderProp label="Hardness" value={tips.erase.hardness} min={0} max={100} unit="%" onChange={(v) => setTip("erase", { hardness: v })} />
          </>
        )}
        {tool === "blur" && (
          <>
            {sizeSlider("blur")}
            <SliderProp label="Hardness" value={tips.blur.hardness} min={0} max={100} unit="%" onChange={(v) => setTip("blur", { hardness: v })} />
            <SliderProp label="Strength" value={blurStrength} min={1} max={30} unit="px" onChange={setBlurStrength} />
          </>
        )}
        {tool === "crop" && (
          <>
            {/* WHAT SHAPE the crop is held to. Before the Angle slider,
                because it decides what a drag can even produce, where the
                angle only turns whatever was drawn. */}
            <SelectProp
              label="Ratio"
              value={cropAspectId}
              onChange={(id) => pickCropAspect(
                id, id === CUSTOM_ID ? seedCustom() : undefined)}
              title="Limit the crop to a fixed width-to-height ratio"
              options={CROP_ASPECTS.map((a) => ({
                value: a.id,
                // "Original" is the picture's own shape, so it says which.
                label: a.id === "original" && dims.w > 0 && dims.h > 0
                  ? `Original (${ratioLabel(dims.w, dims.h)})` : a.label,
              }))}
            />
            {/* The two fields appear only for Custom — a pair of numbers
                standing beside a dropdown that is not asking for them is
                two controls saying nothing. They take a bare ratio (16 : 9)
                as readily as a size (1920 : 1080): what is read off them is
                the quotient, so both spellings mean the same shape. */}
            {cropAspectId === CUSTOM_ID && (
              <div style={{ display: "flex", alignItems: "center", gap: 6, height: 34, flex: "0 0 auto", boxSizing: "border-box", padding: "0 10px", background: "var(--bg-deep)", borderRadius: "var(--r-4)" }}>
                <RatioField value={cropCustom.w} title="Width side of the ratio"
                  onChange={(w) => typeCustom({ ...cropCustom, w })} />
                <span style={{ fontSize: "var(--fs-3)", color: "var(--muted)" }}>:</span>
                <RatioField value={cropCustom.h} title="Height side of the ratio"
                  onChange={(h) => typeCustom({ ...cropCustom, h })} />
              </div>
            )}
            <SliderProp label="Angle" value={cropAngle + 45} min={0} max={90} unit="°" onChange={(v) => setCropAngle(v - 45)} inputValue={cropAngle} inputMin={-45} inputMax={45} onInput={setCropAngle} />
            <PropBtn
              icon="highlight_alt"
              label="To Selection"
              disabled={!hasSelection}
              title={hasSelection ? "Set the crop to the selection's bounding box" : "Make a selection first"}
              onClick={() => cropToSelection()}
            />
            <PropBtn icon="crop" label="Crop" onClick={applyCrop} />
            <PropBtn icon="add_photo_alternate" label="Duplicate & Crop" onClick={cropToNewItem} />
          </>
        )}
        {tool === "zoom" && (
          <>
            <PropBtn icon="fit_screen" label="Fit" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }} />
            <PropBtn icon="crop_original" label="100%" onClick={() => { setZoom(actualZoom); setPan({ x: 0, y: 0 }); }} />
          </>
        )}
      </div>
      )}
          {/* What you do TO the picture, floating over it: undo/redo, then the
              menus. One pill per group — undoing is not the same kind of act
              as opening a menu of transformations, and a single pill with a
              divider in it says they are. They start past the tool palette,
              which used to be pinned in this corner and now starts below
              them — a tool's hover tooltip opens to its RIGHT, straight into
              a bar sitting alongside it, and the bars are what a pointer
              reaches for first. */}
          <CanvasBarRow left={12} onWidth={(w) => setBarsW(w)}>
            <CanvasBar>
              <UndoRedoButtons
                canUndo={undoStack.current.length > 0}
                canRedo={redoStack.current.length > 0}
                onUndo={undo} onRedo={redo} t={english}
              />
            </CanvasBar>
            <CanvasBar>
              <EditorMenus
                dims={dims}
                busy={busy}
                hasSelection={hasSelection}
                onRotate={rotate90}
                onResizeImage={resizeImage}
                onResizeCanvas={resizeCanvas}
                onAdjust={() => openEffect("adjust")}
                onBlurImage={() => openEffect("blur")}
                onSharpenImage={() => openEffect("sharpen")}
                onApplyBackground={requestApplyBackground}
                onApplyModel={(kind, model, needsReference) => {
                  if (needsReference) setRefPick({ kind, model });
                  else void applyModel(kind, model);
                }}
                onSelectRegions={(kind) => void selectRegions(kind)}
                onCropToSelection={cropSelectionNow}
                onFillSelection={fillSelection}
                onGrowSelection={() => setGrowShrink("grow")}
                onBlurSelection={() => setGrowShrink("blur")}
                onShrinkSelection={() => setGrowShrink("shrink")}
                onInvertSelection={invertSelection}
                onTransformSelection={() => { pickTool("select"); beginFloat(true); }}
                onClearSelection={clearSelection}
                onInpaintSelection={(m) => void inpaintSelection(m)}
                inpaintReady={inpaintReady}
                animeInpaintReady={animeInpaintReady}
              />
            </CanvasBar>
          </CanvasBarRow>
          {/* Floating tool palette + separate color bar (over the canvas,
              left edge, flush with the top) — two rounded panels with a small
              gap. */}
          <div
            ref={sideBarsRef}
            onMouseDown={(e) => e.stopPropagation()}
            style={{ position: "absolute", left: 12, top: 12 + CANVAS_BAR_H + 8, zIndex: 10, display: "flex", flexDirection: "column", gap: 8, alignItems: "center" }}
          >
            <div style={{ width: 48, boxSizing: "border-box", display: "flex", flexDirection: "column", alignItems: "center", gap: 3, padding: 5, background: "var(--surface-float)", border: "1px solid var(--border)", borderRadius: "var(--r-7)", boxShadow: "var(--shadow-2)" }}>
              {/* The text tool is offered on any PICTURE, read or not: with
                  no reading it is where you make one (its bar runs the
                  engines), which is the answer to "why is this greyed out"
                  that a missing button cannot give. */}
              {TOOLS.map((t) => (
                <button key={t.id} className="mc-tool-btn" onClick={() => pickTool(t.id)} style={{ position: "relative", width: 36, height: 36, borderRadius: "var(--r-5)", border: "none", background: tool === t.id ? "var(--accent)" : "transparent", color: tool === t.id ? "var(--on-accent)" : "var(--text-3)", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  {/* The zoom_in glyph draws optically smaller than its
                      siblings at the same font size — bump it to match. */}
                  <Icon name={t.icon} size={t.id === "zoom" ? 23 : 20} />
                  {/* Instant tooltip (native titles have an OS hover delay);
                      the shortcut key reads secondary. */}
                  <span className="mc-tool-tip">
                    {t.name}
                    <span style={{ color: "var(--muted-2)", marginLeft: 5 }}>{t.key}</span>
                  </span>
                </button>
              ))}
            </div>
            {/* padding 8 = the swatches' horizontal inset ((48 − 2 border −
                30 swatch) / 2), so the vertical inset matches it exactly. */}
            <div style={{ position: "relative", width: 48, boxSizing: "border-box", display: "flex", flexDirection: "column", alignItems: "center", gap: 4, padding: 8, background: "var(--surface-float)", border: "1px solid var(--border)", borderRadius: "var(--r-7)", boxShadow: "var(--shadow-2)" }}>
              {/* The picker popover renders INSIDE the swatch it belongs to
                  (aligned to it), and that swatch gets an accent ring. */}
              <div className="mc-tool-btn" style={{ position: "relative" }}>
                <button
                  ref={fgSwatch}
                  onClick={() => setPickerFor(pickerFor === "fg" ? null : "fg")}
                  style={{ width: 30, height: 30, borderRadius: "var(--r-4)", border: `2px solid ${pickerFor === "fg" ? "var(--accent)" : "var(--border-strong)"}`, background: color, cursor: "pointer", display: "block", padding: 0 }}
                />
                {pickerFor !== "fg" && <span className="mc-tool-tip">Foreground color</span>}
                {pickerFor === "fg" && (
                  <ColorPickerPopover
                    value={color}
                    onPick={setColor}
                    onClose={() => setPickerFor(null)}
                    anchor={fgSwatch}
                  />
                )}
              </div>
              {/* Background/secondary color — what removing (erase / Delete)
                  paints. Transparent by default; a fully transparent color is
                  the same thing, so there is no separate reset button. */}
              <div className="mc-tool-btn" style={{ position: "relative" }}>
                <button
                  onClick={() => {
                    setBgAsked(false);
                    setPickerFor(pickerFor === "bg" ? null : "bg");
                  }}
                  style={{
                    width: 30, height: 30, borderRadius: "var(--r-4)", padding: 0,
                    border: `2px solid ${pickerFor === "bg" ? "var(--accent)" : "var(--border-strong)"}`,
                    background: bgColor
                      ? `linear-gradient(${bgColor}, ${bgColor}), repeating-conic-gradient(var(--checker-b) 0% 25%, var(--checker-a) 0% 50%) 0 / 10px 10px`
                      : "repeating-conic-gradient(var(--checker-b) 0% 25%, var(--checker-a) 0% 50%) 0 / 10px 10px",
                    cursor: "pointer", display: "block", position: "relative", overflow: "hidden",
                  }}
                >
                  {!bgColor && (
                    <span style={{ position: "absolute", left: -4, right: -4, top: "50%", height: 2, background: "var(--red)", transform: "rotate(-45deg)" }} />
                  )}
                </button>
                {pickerFor !== "bg" && <span className="mc-tool-tip">Background color</span>}
                {pickerFor === "bg" && (
                  <ColorPickerPopover
                    value={bgColor ?? "#ffffff00"}
                    // A fully transparent pick is the RESET: `null` is what the
                    // swatch's slash and the erase-to-transparent path key on,
                    // and an `#rrggbb00` stored verbatim reached neither.
                    onPick={(c) => setBgColor(/00$/i.test(c) ? null : c)}
                    onClose={() => {
                      setPickerFor(null);
                      // The picker was opened BY the action: a colour is the
                      // answer, a transparent close is "never mind".
                      if (bgAsked && bgColor) applyBackground(bgColor);
                      setBgAsked(false);
                    }}
                    note={bgAsked
                      ? "Pick a color to put behind the picture."
                      : undefined}
                  />
                )}
              </div>
            </div>
          </div>
          <canvas
            ref={viewRef}
            onMouseDown={onDown}
            onPointerDown={(e) => {
              pressureRef.current = e.pointerType === "pen" ? (e.pressure || 0.5) : 1;
            }}
            onPointerMove={(e) => {
              pressureRef.current = e.pointerType === "pen" ? (e.pressure || 0.5) : 1;
            }}
            onMouseMove={(e) => {
              const r = viewRef.current!.getBoundingClientRect();
              const sx = e.clientX - r.left, sy = e.clientY - r.top;
              cursorRef.current = { x: sx, y: sy, over: true };
              placeRing(sx, sy, true);
              // A lasso built by clicks draws its next edge to the pointer.
              if (polyRef.current && !drag.current) redraw();
              // Transform-mode hover feedback: resize arrows over the corner
              // handles, rotate over the rotation handle, move inside the box
              // (kept as-is while a drag is running).
              if (!drag.current) {
                const f = floatRef.current;
                const hh = f?.transforming ? hitHandle(sx, sy) : null;
                let want = hh == null ? null
                  : hh === "move" ? "move"
                  : hh === "rot" ? CURSOR_ROTATE
                  : hh === "n" || hh === "s" ? "ns-resize"
                  : hh === "e" || hh === "w" ? "ew-resize"
                  : hh === "nw" || hh === "se" ? "nwse-resize"
                  : "nesw-resize";
                if (want == null && !f) {
                  if (activeTool === "crop" && cropRect) {
                    const img2 = toImg(e.clientX, e.clientY);
                    const ch = hitCropHandle(img2.x, img2.y);
                    want = ch == null ? null
                      : ch === "move" ? "move"
                      : ch === "rot" ? CURSOR_ROTATE
                      : ch === "n" || ch === "s" ? "ns-resize"
                      : ch === "e" || ch === "w" ? "ew-resize"
                      : ch === "nw" || ch === "se" ? "nwse-resize"
                      : "nesw-resize";
                  } else if (isSelectTool(activeTool) && onSelectionBorder(sx, sy)) {
                    want = "move";
                  }
                }
                setFloatCursor((p) => (p === want ? p : want));
              }
            }}
            onMouseLeave={() => {
              cursorRef.current.over = false;
              placeRing(0, 0, false);
              setFloatCursor((p) => (p == null ? p : null));
            }}
            style={{
              position: "absolute", inset: 0, width: "100%", height: "100%",
              cursor: floatCursor ?? (activeTool === "hand" ? "grab"
                : activeTool === "zoom" ? (altHeld ? CURSOR_ZOOM_OUT : CURSOR_ZOOM_IN)
                : activeTool === "brush" || activeTool === "blur" || activeTool === "erase" ? "none"
                : activeTool === "fill" ? CURSOR_FILL
                : activeTool === "wand" ? CURSOR_WAND
                : activeTool === "crop" ? CURSOR_CROP
                : isSelectTool(activeTool) ? "crosshair"
                : activeTool === "text" ? "crosshair"
                : activeTool === "pipette" ? "crosshair"
                : "default"),
            }}
          />
          {/* The brush/eraser/blur tip preview — see `placeRing`. */}
          <div
            ref={ringRef}
            style={{
              position: "absolute", left: 0, top: 0, display: "none",
              borderRadius: "50%", pointerEvents: "none", zIndex: 2,
              border: "1px solid var(--on-scrim)",
              boxShadow: "0 0 0 1px var(--scrim-4), inset 0 0 0 1px var(--scrim-4)",
              boxSizing: "border-box",
            }}
          />
          {/* Marching-ants overlay (animated selection outline), above the view
              canvas but transparent to pointer events. */}
          <canvas
            ref={antsRef}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
          />
          {/* Help bar (bottom-left): the active tool/mode name + its hint —
              the single place for help text (the props bar carries none).
              In a short window it moves right, clear of the vertical bars
              (12 top offset + their height + ~41px of bar + margins). */}
          <div style={{ ...overlayBox, left: box.h < 12 + sideBarsH + 49 ? 72 : 14, bottom: 12, gap: 8, padding: "6px 11px", fontSize: "var(--fs-2)", color: "var(--muted)" }}>
            <span style={{ fontSize: "var(--fs-1)", fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: "var(--text-3)" }}>
              {floating ? (floating.transforming ? "Transform" : "Move") : TOOLS.find((t) => t.id === tool)?.name}
            </span>
            {floating
              ? (floating.transforming
                ? "Drag handles to scale · Shift keeps aspect · Alt from center · arc rotates · Enter applies · Esc cancels"
                : "Drag to move · Enter to apply · Esc to cancel")
              : hintFor(tool, selStyle)}
          </div>
          {/* WHERE EVERY EDITOR ERROR IS SAID: a capsule over the picture,
              top-centre, with an ✕. The inpaint failures used to appear in
              the properties bar instead — at the end of a row of controls
              that is centred in what the floating menus leave, so a long
              message was ellipsised to nothing or pushed off screen
              entirely, and the one time it mattered (no model, no torch) it
              was invisible. One channel, one place, and it does not
              disappear on its own: an error you did not manage to read is
              the same as no error at all. */}
          {opErr && (
            <div style={{
              ...overlayBox,
              // UNDER the top strip, not in it. At `top: 12` this sat exactly
              // where the properties bar is — the widest thing in the window
              // and the one always on screen — so the message it exists to
              // deliver was behind it. Below the strip and left of the
              // palette's column it can overlap nothing: the only other
              // floating things are at the BOTTOM edge. `zIndex` above the
              // bars for the same reason a portalled menu needs one.
              left: (propsFrom + Math.max(propsFrom + 80, box.w - 16)) / 2,
              transform: "translateX(-50%)",
              top: 12 + 42 + 10, zIndex: 20,
              gap: 8, padding: "7px 8px 7px 12px", fontSize: "var(--fs-3)",
              color: "var(--red-text)",
              maxWidth: Math.max(160, box.w - 16 - propsFrom),
              alignItems: "flex-start",
            }}>
              <Icon name="error" size={15} color="var(--red-text)" style={{ flex: "0 0 auto", marginTop: 1 }} />
              {/* WRAPS, up to a few lines: a model's own message names a
                  package and a place to get it, and one line of it is a
                  sentence cut in half. */}
              <span style={{ overflowWrap: "anywhere", lineHeight: 1.35 }}>{opErr}</span>
              <IconButton icon="close" size={20} glyph={14} tone="muted" shape="round"
                onClick={() => setOpErr("")}
                title="Dismiss" style={{ flex: "0 0 auto" }} />
            </div>
          )}
          {/* Busy veil while a menu AI action runs on the buffer. */}
          {busy && (
            <div style={{ ...overlayBox, right: 14, top: 12, gap: 7, padding: "7px 12px", fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
              <Icon name="progress_activity" size={15} color="var(--accent)" spin />
              Working…
            </div>
          )}
          {/* The live effects all draw through ONE panel over the top-right
              of the canvas — see `Effect`. Not a modal: the picture
              underneath stays pannable and zoomable, which is the only way to
              judge any of them on the part that matters. */}
          {effect && (
            <EffectPanel
              icon={EFFECT_PANEL[effect.kind].icon}
              title={EFFECT_PANEL[effect.kind].title}
              onSelection={hasSelection}
              sliders={effectSliders(effect, previewEffect)}
              neutral={effectIsNeutral(effect)}
              onReset={() => previewEffect(resetEffect(effect))}
              onCancel={() => closeEffect(false)}
              onOk={() => closeEffect(true)}
            />
          )}

          {/* Zoom controls, overlaid at the bottom-right. The reset button shows
              "100%" (jump to actual size) or, once already at 100%, "Fit" (scale
              the image to fill the available space). */}
          <div style={{ ...overlayBox, right: 14, bottom: 12, gap: 4, padding: "4px 6px" }}>
            <IconBtn icon="remove" title="Zoom out" onClick={() => zoomAt(null, 0.85)} small />
            <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-3)", color: "var(--text-2)", width: 44, textAlign: "center" }}>{Math.round(scale * dpr * 100)}%</span>
            <IconBtn icon="add" title="Zoom in" onClick={() => zoomAt(null, 1.15)} small />
            {atActualSize ? (
              <IconBtn icon="fit_screen" title="Fit the image to the available space" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }} small />
            ) : (
              <IconBtn icon="crop_original" title="Zoom to 100% (actual size, centered)" onClick={() => { setZoom(actualZoom); setPan({ x: 0, y: 0 }); }} small />
            )}
          </div>
          {!loaded && (
            <Loading label="Loading…"
                     style={{ position: "absolute", inset: 0, justifyContent: "center", padding: 0 }} />
          )}
        </div>
        </div>
      </div>

      {/* Reference picker for a reference-guided model from the Image menu
          (example-based colorization): pick → apply with that reference. */}
      {refPick && (
        <RefPickerOverlay
          onConfirm={(refId) => {
            const p = refPick;
            setRefPick(null);
            void applyModel(p.kind, p.model, refId);
          }}
          onClose={() => setRefPick(null)}
        />
      )}

      {/* Unsaved-changes prompt shown when closing the editor or a tab with
          pending edits: save (then close), discard (close), or cancel. */}
      {growShrink && (
        <GrowShrinkDialog
          mode={growShrink}
          onCancel={() => setGrowShrink(null)}
          onApply={(n) => {
            const which = growShrink;
            setGrowShrink(null);
            (which === "grow" ? APP_PREFS.growSelectionPx
              : which === "shrink" ? APP_PREFS.shrinkSelectionPx
              : APP_PREFS.blurSelectionPx).write(n);
            if (which === "blur") blurSelectionEdge(n);
            else growShrinkSelection(which, n);
          }}
        />
      )}
      {/* Escape with several tabs open: window, tab, or neither. Asked before
          the unsaved-changes prompt, since which of them even applies depends
          on the answer. */}
      {closeAsk && (
        <ConfirmModal t={english}
          {...closeChoice(english, isPending ? "New crop (unsaved)" : item?.name)}
          onResult={(r) => {
            setCloseAsk(false);
            if (r === "answer") closeGuardedAll();
            else if (r === "plain") closeActiveTab();
          }}
        />
      )}
      {closePrompt && (
        <ConfirmModal t={english}
          title="Unsaved changes"
          body={closePrompt.going === "leave"
            ? "This image has changes that haven't been saved. Save them before switching to Annotate?"
            : "This image has changes that haven't been saved. Save them before closing?"}
          plain={{ label: "Discard", danger: true }}
          answer={{ label: "Save", busy: "Saving…",
                    run: async () => { if (!(await doSave())) throw new Error("not saved"); } }}
          onResult={(r) => {
            const p = closePrompt.proceed;
            if (r === null) { closingRef.current = false; setClosePrompt(null); return; }
            setClosePrompt(null);
            p();
          }} />
      )}
    </div>
  );
}

/** One tab in the editor's tab bar: the item's name plus a close button.
 * Tabs size to their full name (no truncation — widths differ per tab);
 * `unsaved` appends a star, Photoshop-style. */
function EditorTab({ id, active, unsaved, onSelect, onClose }: { id: number; active: boolean; unsaved?: boolean; onSelect: () => void; onClose: () => void }) {
  const { data } = useQuery({ queryKey: ["item", id], queryFn: () => api.item(id), enabled: id >= 0 });
  const label = id < 0 ? "New crop" : data?.name;
  return (
    <div
      onClick={onSelect}
      title={label}
      style={{
        display: "flex", alignItems: "center", gap: 6, padding: "0 8px 0 12px",
        flex: "0 0 auto", cursor: "pointer",
        borderRight: "1px solid var(--border-soft)",
        background: active ? "var(--panel)" : "transparent",
        color: active ? "var(--text-bright)" : "var(--muted)",
        borderTop: `2px solid ${active ? "var(--accent)" : "transparent"}`,
      }}
    >
      <span style={{ whiteSpace: "nowrap", fontSize: "var(--fs-3)", fontFamily: "var(--mono)" }}>
        {label ?? "…"}{unsaved ? " *" : ""}
      </span>
      <IconButton icon="close" size={18} glyph={14} reveal="hover"
        onClick={(e) => { e.stopPropagation(); onClose(); }}
        title="Close tab" />
    </div>
  );
}

// ---- helpers ----
// Split an 8-digit hex color into its opaque part + alpha (1 for #rrggbb).
function splitAlpha(hex: string): { rgb: string; a: number } {
  const m = hex.replace("#", "");
  if (m.length === 8) return { rgb: "#" + m.slice(0, 6), a: parseInt(m.slice(6, 8), 16) / 255 };
  return { rgb: hex, a: 1 };
}
/**
 * The colour with its alpha replaced, in the COLOUR PICKER'S OWN SPELLING: at
 * full opacity the suffix is left off entirely, which is what `splitAlpha`
 * reads back as 1. The brush's Opacity slider and the picker's alpha are two
 * controls over one value, so they have to write the same string for the same
 * colour or a round trip through either would keep rewriting it.
 */
function withAlpha(hex: string, a: number): string {
  const { rgb } = splitAlpha(hex);
  const clamped = Math.max(0, Math.min(1, a));
  return clamped >= 1 ? rgb
    : rgb + Math.round(clamped * 255).toString(16).padStart(2, "0");
}
function normRect(a: { x: number; y: number }, b: { x: number; y: number }): Rect {
  return { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) };
}
/** Whether a text box (FRACTIONS) is touched by a band drawn in image PIXELS
 *  — the text tool's marquee test. Bounding boxes, deliberately: a band is a
 *  rough gesture over a page of small boxes, and refusing one whose corner
 *  clips a slanted quad would read as the drag having missed. */
function quadTouchesRect(quad: [number, number][], band: Rect,
                         ): boolean {
  if (!quad.length) return false;
  const xs = quad.map(([x]) => x), ys = quad.map(([, y]) => y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  return x1 >= band.x && x0 <= band.x + band.w
      && y1 >= band.y && y0 <= band.y + band.h;
}
function rectNorm(a: { x: number; y: number }, b: { x: number; y: number }, dims: { w: number; h: number }): Rect {
  // Clamp the drag points to the image so a crop can never extend the canvas.
  const cl = (p: { x: number; y: number }) => ({
    x: Math.min(dims.w, Math.max(0, p.x)),
    y: Math.min(dims.h, Math.max(0, p.y)),
  });
  const r = normRect(cl(a), cl(b));
  return { x: r.x / dims.w, y: r.y / dims.h, w: r.w / dims.w, h: r.h / dims.h };
}
function hexA(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}
/** How close (screen px) a click must land to the first corner to close a
 *  lasso built by clicks; also the size that corner is drawn at. */
const POLY_CLOSE_PX = 8;

function hintFor(tool: Tool, selStyle?: SelStyle): string {
  switch (tool) {
    case "hand": return "Drag to pan · scroll to zoom · hold Space in any tool";
    case "zoom": return "Click to zoom in · Alt-click to zoom out · drag an area to zoom into it";
    case "lasso": return "Drag to draw · click to place corners · double-click, the first corner or Enter closes · Esc cancels · Shift extend · Alt subtract · Shift+Alt intersect";
    case "select": return "Drag to select · Shift extend · Alt subtract · Shift+Alt intersect · while dragging, Shift makes it square and Alt draws from the centre · Transform to scale/rotate";
    case "text": return "Click a text box to select it · drag across several · Shift add · Alt remove";
    case "brush": return "Paint with the active color · Alt picks a color · affects the selection only";
    case "erase": return "Erase to the background color (transparent by default) · affects the selection only";
    case "blur": return "Paint to blur · repeated strokes blur further · affects the selection only";
    case "fill": return "Click to fill similar colors · drag to widen/narrow the tolerance · Alt picks a color · affects the selection only";
    case "pipette": return "Click to pick the color under the pointer · drag to keep picking · Alt-click picks the background color";
    case "wand": return "Click to select similar colors · drag to widen/narrow · Grow pads what it finds (negative shrinks) · Shift add · Alt remove · Shift+Alt intersect · click inside to deselect";
    case "crop": return "Drag a crop · Angle slider rotates · Enter crops";
  }
}
function PropBtn({ icon, label, onClick, disabled, title, iconRot, color }: { icon: string; label: string; onClick: () => void; disabled?: boolean; title?: string; iconRot?: number; color?: string }) {
  return (
    <button onClick={onClick} disabled={disabled} title={title} style={{ display: "flex", alignItems: "center", gap: 6, height: 34, padding: "0 12px", borderRadius: "var(--r-4)", border: "none", background: "var(--bg-deep)", color: disabled ? "var(--muted-3)" : (color ?? "var(--text-2)"), fontSize: "var(--fs-3)", cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.6 : 1 }}>
      <Icon name={icon} size={17} style={iconRot ? { transform: `rotate(${iconRot}deg)` } : undefined} />{label}
    </button>
  );
}
/** A labelled dropdown in the properties bar, at `SliderProp`'s metrics so a
 *  bar holding both reads as one row of controls. */
function SelectProp({ label, value, options, onChange, title }: {
  label: string; value: string; title?: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div title={title} style={{ display: "flex", alignItems: "center", gap: 8, height: 34, flex: "0 0 auto", boxSizing: "border-box", padding: "0 10px", background: "var(--bg-deep)", borderRadius: "var(--r-4)" }}>
      <span style={{ fontSize: "var(--fs-2)", color: "var(--muted)" }}>{label}</span>
      <select
        value={value}
        // A picked option hands the keyboard back to the editor's shortcuts.
        onChange={(e) => { onChange(e.target.value); e.target.blur(); }}
        style={{ height: 24, borderRadius: "var(--r-2)", border: "none", background: "var(--panel-2)", color: "var(--text-2)", padding: "0 4px", fontSize: "var(--fs-2)", cursor: "pointer" }}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}
/** A labelled NUMBER, typed rather than dragged, at `SliderProp`'s metrics.
 *  For a value whose useful range is a handful of pixels either side of zero,
 *  where a slider spends its whole length on numbers nobody wants and lands on
 *  the one they do by luck. The sign is part of the value, so the field takes
 *  a leading "-"; the draft is local until blur/Enter, the same rule
 *  `SliderProp`'s own field follows (and the same arithmetic: "8-2" is 6). */
function NumberProp({ label, value, min, max, unit, onChange, title }: {
  label: string; value: number; min: number; max: number; unit: string;
  title?: string; onChange: (n: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => { setDraft(String(value)); }, [value]);
  const commitDraft = () => {
    const n = evalExpr(draft);
    if (n == null) { setDraft(String(value)); return; }
    const v = Math.max(min, Math.min(max, Math.round(n)));
    setDraft(String(v));
    onChange(v);
  };
  return (
    <div title={title} style={{ display: "flex", alignItems: "center", gap: 8, height: 34, flex: "0 0 auto", boxSizing: "border-box", padding: "0 10px", background: "var(--bg-deep)", borderRadius: "var(--r-4)" }}>
      <span style={{ fontSize: "var(--fs-2)", color: "var(--muted)" }}>{label}</span>
      <input
        type="text"
        inputMode="numeric"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          const n = Math.round(Number(e.target.value));
          // A lone "-" (on the way to "-3") is not a number and is left in the
          // field until it becomes one, rather than being committed as 0.
          if (e.target.value.trim() !== "" && Number.isFinite(n) && n >= min && n <= max) onChange(n);
        }}
        onBlur={commitDraft}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitDraft(); (e.target as HTMLInputElement).blur(); } }}
        style={{ width: 46, height: 24, borderRadius: "var(--r-2)", border: "none", background: "var(--panel-2)", color: "var(--text-2)", padding: "0 5px", fontFamily: "var(--mono)", fontSize: "var(--fs-2)", textAlign: "right" }}
      />
      <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted)", width: 18 }}>{unit}</span>
    </div>
  );
}

/** One side of the typed ratio. It REJECTS the keystroke rather than storing
 *  something no ratio can be read out of — the metadata value field's rule,
 *  which the crop's own Angle field learned the hard way — while allowing the
 *  half-typed states a decimal passes through ("", "1.", ".5"). */
function RatioField({ value, title, onChange }: {
  value: string; title: string; onChange: (v: string) => void;
}) {
  return (
    <input
      type="text"
      inputMode="decimal"
      value={value}
      title={title}
      onChange={(e) => {
        const v = filterNumeric(e.target.value);
        if (v == null) return;
        onChange(v);
      }}
      style={{ width: 42, height: 24, borderRadius: "var(--r-2)", border: "none", background: "var(--panel-2)", color: "var(--text-2)", padding: "0 5px", fontFamily: "var(--mono)", fontSize: "var(--fs-2)", textAlign: "right" }}
    />
  );
}
/** "1920 x 1080" as "16:9" — the smallest whole-number pair, so the label
 *  says the SHAPE rather than repeating the size the header already gives. */
function ratioLabel(w: number, h: number): string {
  const a = Math.round(w), b = Math.round(h);
  if (!(a > 0) || !(b > 0)) return "";
  const gcd = (m: number, n: number): number => (n === 0 ? m : gcd(n, m % n));
  const g = gcd(a, b);
  const rw = a / g, rh = b / g;
  // An odd size reduces to nothing anybody reads (4001:3000), so past two
  // digits it is said as a decimal against 1.
  if (rw > 99 || rh > 99) return `${(a / b).toFixed(2)}:1`;
  return `${rw}:${rh}`;
}
function SliderProp({ label, value, min, max, unit, onChange, inputValue, inputMin, inputMax, onInput }: {
  label: string; value: number; min: number; max: number; unit: string;
  onChange: (n: number) => void;
  // When the slider's raw value isn't the user-facing number (the crop angle
  // slider is offset), these map the editable field to the true value.
  inputValue?: number; inputMin?: number; inputMax?: number;
  onInput?: (n: number) => void;
}) {
  const shown = inputValue ?? value;
  const commit = onInput ?? onChange;
  const lo = inputMin ?? min;
  const hi = inputMax ?? max;
  // Local draft so partially-typed numbers ("1" on the way to "15", a lone
  // "-") don't get clamped mid-keystroke; blur / Enter snaps into range.
  // The commit evaluates simple arithmetic ("500+10" → 510), so the input is
  // a text field, not a number field (which would reject the operators).
  const [draft, setDraft] = useState(String(shown));
  useEffect(() => { setDraft(String(shown)); }, [shown]);
  const commitDraft = () => {
    const n = evalExpr(draft);
    if (n != null) {
      const v = Math.max(lo, Math.min(hi, Math.round(n)));
      // Sync the draft explicitly — committing an expression that evaluates
      // to the CURRENT value never re-renders `shown`, which would leave the
      // raw expression text sitting in the field.
      setDraft(String(v));
      commit(v);
    } else {
      setDraft(String(shown));
    }
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, height: 34, boxSizing: "border-box", padding: "0 10px", background: "var(--bg-deep)", borderRadius: "var(--r-4)" }}>
      <span style={{ fontSize: "var(--fs-2)", color: "var(--muted)" }}>{label}</span>
      <input type="range" min={min} max={max} value={value} onChange={(e) => onChange(+e.target.value)} style={{ width: 90, accentColor: "var(--accent)", cursor: "pointer" }} />
      <input
        type="text"
        inputMode="decimal"
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          const n = Math.round(Number(e.target.value));
          if (e.target.value.trim() !== "" && Number.isFinite(n) && n >= lo && n <= hi) commit(n);
        }}
        onBlur={commitDraft}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitDraft(); (e.target as HTMLInputElement).blur(); } }}
        style={{ width: 46, height: 24, borderRadius: "var(--r-2)", border: "none", background: "var(--panel-2)", color: "var(--text-2)", padding: "0 5px", fontFamily: "var(--mono)", fontSize: "var(--fs-2)" }}
      />
      <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted)", width: 18 }}>{unit}</span>
    </div>
  );
}

/**
 * The floating panel a LIVE EFFECT is judged on: Adjustments' four sliders and
 * the Image menu's blur are the same thing with a different list of numbers on
 * it, so they are one drawing. It sits over the top-right of the canvas rather
 * than in a modal, and it says when the effect is confined to the selection.
 *
 * Each slider returns to neutral on a DOUBLE-CLICK — the usual way out of "I
 * have gone too far on this one" — and the panel's own Reset takes all of
 * them there at once. Cancel puts the picture back; OK applies the lot as one
 * undoable step.
 */
function EffectPanel({ icon, title, onSelection, sliders, neutral, onReset, onCancel, onOk }: {
  icon: string;
  title: string;
  /** Whether the effect is confined to a selection — the panel says so. */
  onSelection: boolean;
  sliders: EffectSlider[];
  /** True while the effect changes nothing — Reset has nothing to do. */
  neutral: boolean;
  onReset: () => void;
  onCancel: () => void;
  onOk: () => void;
}) {
  const btn: React.CSSProperties = {
    height: 26, borderRadius: "var(--r-3)", fontSize: "var(--fs-2)",
    fontFamily: "inherit", border: "1px solid var(--border-strong)",
    background: "transparent", color: "var(--text-2)",
  };
  return (
    <div style={{
      position: "absolute", right: 14, top: 12, zIndex: 60, width: 250,
      background: "var(--surface-float)", border: "1px solid var(--border)",
      borderRadius: "var(--r-6)", boxShadow: "var(--shadow-2)",
      padding: "10px 12px 12px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <Icon name={icon} size={16} color="var(--accent)" />
        <span style={{ fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text-bright)" }}>
          {title}
        </span>
        <span style={{ flex: 1 }} />
        {onSelection && (
          <span style={{ fontSize: "var(--fs-1)", color: "var(--accent)" }}>selection</span>
        )}
      </div>
      {sliders.map((s) => (
        <div key={s.key} style={{ marginBottom: 7 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
            <span style={{ flex: 1, fontSize: "var(--fs-2)", color: "var(--muted)" }}>{s.label}</span>
            <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
              color: s.value ? "var(--text-2)" : "var(--muted-3)" }}>
              {s.text}
            </span>
          </div>
          <input
            type="range" min={s.min} max={s.max} step={1} value={s.value}
            onChange={(e) => s.onChange(Number(e.target.value))}
            onDoubleClick={s.onRest}
            style={{ width: "100%", accentColor: "var(--accent)" }}
          />
        </div>
      ))}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10 }}>
        <button
          onClick={onReset}
          disabled={neutral}
          style={{ ...btn, padding: "0 9px", cursor: neutral ? "default" : "pointer",
            color: neutral ? "var(--muted-3)" : "var(--text-2)" }}
        >
          Reset
        </button>
        <span style={{ flex: 1 }} />
        <button onClick={onCancel} style={{ ...btn, padding: "0 11px", cursor: "pointer" }}>
          Cancel
        </button>
        <button
          onClick={onOk}
          style={{ ...btn, padding: "0 13px", fontWeight: 600, cursor: "pointer",
            border: "1px solid var(--accent)", background: "var(--accent)",
            color: "var(--on-accent)" }}
        >
          OK
        </button>
      </div>
    </div>
  );
}

/** Small modal asking for the Grow/Shrink-selection amount in pixels. */
function GrowShrinkDialog({ mode, onApply, onCancel }: {
  mode: "grow" | "shrink" | "blur";
  onApply: (px: number) => void;
  onCancel: () => void;
}) {
  // Each verb keeps its own number: growing by two and shrinking by one are
  // different habits, and one shared amount would make each press retype the
  // other's.
  const [draft, setDraft] = useState(() => String(
    (mode === "grow" ? APP_PREFS.growSelectionPx
      : mode === "shrink" ? APP_PREFS.shrinkSelectionPx
      : APP_PREFS.blurSelectionPx).read()));
  const commit = () => {
    const n = evalExpr(draft);
    if (n != null && Math.round(n) > 0) onApply(Math.min(500, Math.round(n)));
  };
  return (
    <ConfirmModal t={english}
      title={mode === "grow" ? "Grow selection" : mode === "shrink" ? "Shrink selection" : "Blur selection"}
      body={
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
          {mode === "grow" ? "Expand by" : mode === "shrink" ? "Contract by" : "Soften by"}
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
            onFocus={(e) => e.target.select()}
            style={{ width: 64, height: 28, borderRadius: "var(--r-3)", border: "1px solid var(--border-strong)", background: "var(--bg-deep)", color: "var(--text-2)", padding: "0 8px", fontSize: "var(--fs-3)", fontFamily: "var(--mono)" }}
          />
          px
        </label>
      }
      answer={{ label: mode === "grow" ? "Grow" : mode === "shrink" ? "Shrink" : "Blur" }}
      onResult={(r) => { if (r === "answer") commit(); else onCancel(); }} />
  );
}
