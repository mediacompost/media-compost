import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useDevicePixelRatio } from "./dpr";
import { panForZoom, zoomPivot } from "./zoomPivot";

/**
 * Fit-based zoom/pan model for an image or video frame shown inside a centered
 * viewport, matching the image editor's semantics: `zoom` is a multiplier over
 * the fit scale (so `zoom === 1` fits the content edge-to-edge on its
 * constraining axis). "Actual size" is one picture pixel on one DEVICE pixel,
 * so it is `1 / (fit * dpr)` — on a retina display a CSS scale of 1 spreads
 * each pixel over two of the screen's, which is what made 100% look like 200%.
 * This replaces the
 * annotator's older absolute-scale model so the fit ↔ actual toggle behaves the
 * same in both windows.
 *
 * The content is expected to be centered in the viewport (flexbox), with `pan`
 * applied as an extra `translate` on the scaled frame.
 */
export interface ZoomPan {
  /** Ref to attach to the measured viewport element. */
  viewportRef: React.RefObject<HTMLDivElement>;
  /** Current fit multiplier (1 = fit-to-screen). */
  zoom: number;
  setZoom: (z: number) => void;
  pan: { x: number; y: number };
  setPan: (p: { x: number; y: number }) => void;
  /** The scale that fits the content in the current viewport (px per content px). */
  fit: number;
  /** Effective pixels-per-content-pixel (`fit * zoom`). */
  scale: number;
  /** Rendered content size in CSS px. */
  frameW: number;
  frameH: number;
  /** Measured viewport size. */
  vp: { w: number; h: number };
  /** The viewport MINUS the floating bars (see `inset`) — what the picture is
   *  actually fitted and centred in. */
  safe: { w: number; h: number };
  /** How far the safe area's centre sits from the viewport's. The caller adds
   *  this to the content's translate, since the content is centred in the
   *  VIEWPORT by flexbox and the fit is computed against the safe area. */
  origin: { x: number; y: number };
  /** Percentage shown in the zoom control (100% = one picture pixel per
   *  device pixel, so it is the display scale away from `scale`). */
  percent: number;
  /** True when within a hair of actual size. */
  atActualSize: boolean;
  fitToScreen: () => void;
  actualSize: () => void;
  zoomBy: (factor: number) => void;
  /** Wheel zoom keeping the given viewport-relative point fixed. */
  zoomAt: (vx: number, vy: number, factor: number) => void;
  /** Request a re-fit when the content changes (e.g. navigating items). */
  requestFit: () => void;
}

export function useZoomPan(
  iw: number,
  ih: number,
  opts?: {
    min?: number; max?: number; fitKey?: unknown;
    /**
     * WHAT THE FLOATING BARS COVER, on each edge of the viewport.
     *
     * The controls in these windows float OVER the picture — the undo/menu row
     * at the top left, the zoom cluster and the media bar at the bottom — so
     * without this a fitted picture runs underneath them and its corners are
     * unreachable. The image editor has always inset its own fit by hand; this
     * is that rule, moved into the model so the annotator and the video editor
     * get it too.
     */
    inset?: { l?: number; t?: number; r?: number; b?: number };
  }
): ZoomPan {
  const min = opts?.min ?? 0.02;
  const max = opts?.max ?? 16;
  const fitKey = opts?.fitKey;
  // Read out as numbers: an inset passed as an object literal is a new object
  // every render, and these are memo dependencies.
  const insL = opts?.inset?.l ?? 0;
  const insT = opts?.inset?.t ?? 0;
  const insR = opts?.inset?.r ?? 0;
  const insB = opts?.inset?.b ?? 0;
  const dpr = useDevicePixelRatio();
  const viewportRef = useRef<HTMLDivElement>(null);
  const [vp, setVp] = useState({ w: 800, h: 600 });
  const [zoom, setZoomRaw] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const pendingFit = useRef(true);

  const cw = iw || 1;
  const ch = ih || 1;
  // Never smaller than a token amount: a window narrower than its own bars
  // would otherwise fit the picture to nothing (or to a negative size).
  const safe = {
    w: Math.max(40, vp.w - insL - insR),
    h: Math.max(40, vp.h - insT - insB),
  };
  const origin = { x: (insL - insR) / 2, y: (insT - insB) / 2 };
  const fitFor = (w: number, h: number) => Math.min(w / cw, h / ch) || 1;
  const fit = fitFor(safe.w, safe.h);
  const scale = fit * zoom;
  const frameW = cw * scale;
  const frameH = ch * scale;

  // The limits are on the DISPLAYED zoom, so they mean the same thing on
  // every screen: `max: 16` is 1600% whatever the display scale is.
  const clampZoom = useCallback(
    (z: number) => Math.max(min / (fit * dpr), Math.min(max / (fit * dpr), z)),
    [fit, dpr, min, max]
  );
  const setZoom = useCallback((z: number) => setZoomRaw(clampZoom(z)), [clampZoom]);

  // Measure the viewport (before paint so the first fit uses the real size).
  //
  // Bound on EVERY render, not once on mount, and this is a FIX rather than
  // caution. The annotator does not render its viewport until the item detail
  // has loaded — it returns a bare rectangle before that — so at mount
  // `viewportRef.current` is null; a `[]`-dep effect returned there and never
  // ran again, leaving `vp` at the 800×600 it is INITIALISED to for the whole
  // life of the window. Everything downstream reads that: the fit scale, what
  // counts as "fits", where the content is thought to be, and so the pivot a
  // wheel zoom turns about — which is what made zooming feel like it was
  // aiming somewhere else. (The same trap `useVideoPlayback` documents for its
  // listeners, for the same reason and in the same window.)
  //
  // Cheap: it returns immediately unless the element identity actually
  // changed.
  const observed = useRef<HTMLDivElement | null>(null);
  const unobserve = useRef<(() => void) | null>(null);
  useLayoutEffect(() => {
    const el = viewportRef.current;
    if (el === observed.current) return;
    unobserve.current?.();
    observed.current = el;
    if (!el) { unobserve.current = null; return; }
    const measure = () => setVp({ w: el.clientWidth, h: el.clientHeight });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    window.addEventListener("resize", measure);
    unobserve.current = () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  });
  useEffect(() => () => { unobserve.current?.(); unobserve.current = null; }, []);

  // Request a re-fit whenever the content identity changes (e.g. navigating to
  // another item). Declared BEFORE the apply effect so that, in the commit where
  // `fitKey` changes, `pendingFit` is set true before the apply effect reads it.
  useEffect(() => { pendingFit.current = true; setPan({ x: 0, y: 0 }); }, [fitKey]);

  // Apply a pending fit once real content + viewport dimensions are known.
  useEffect(() => {
    if (pendingFit.current && cw > 1 && ch > 1 && vp.w > 1 && vp.h > 1) {
      pendingFit.current = false;
      setZoomRaw(1);
      setPan({ x: 0, y: 0 });
    }
  }, [cw, ch, vp.w, vp.h, fitKey]);

  const requestFit = useCallback(() => { pendingFit.current = true; }, []);

  const fitToScreen = useCallback(() => {
    const el = viewportRef.current;
    if (el) setVp({ w: el.clientWidth, h: el.clientHeight });
    setZoomRaw(1);
    setPan({ x: 0, y: 0 });
  }, []);

  const actualSize = useCallback(() => {
    setZoomRaw(clampZoom(1 / (fit * dpr)));
    setPan({ x: 0, y: 0 });
  }, [clampZoom, fit, dpr]);

  // Zoom about the right point — `zoomPivot.ts` is the rule and its tests are
  // where it is stated. In short: an axis where the picture FITS holds still
  // (so an off-centre picture grows where it stands and can be zoomed up and
  // back down to exactly where it was), an axis that overflows follows the
  // cursor, and the pan is then clamped so the picture never leaves a gap it
  // does not have to.
  //
  // `cursor` is relative to the viewport's top-left, and is null for the zoom
  // BUTTONS — they take the same path, or the +/- pair would drift a picture
  // the wheel holds still.
  const zoomTo = useCallback((z2: number, cursor: { x: number; y: number } | null) => {
    if (z2 === zoom) return;
    // In the SAFE area's coordinates, which is where `pan` already means what
    // it says: `pan` is measured from the safe area's centre (the caller adds
    // `origin` on top), so only the cursor has to be moved into that frame.
    const state = { vp: safe, frame: { w: frameW, h: frameH }, pan };
    const at = cursor ? { x: cursor.x - insL, y: cursor.y - insT } : null;
    setZoomRaw(z2);
    setPan(panForZoom(state, zoomPivot(state, at), z2 / zoom));
  }, [zoom, safe.w, safe.h, insL, insT, frameW, frameH, pan]);  // eslint-disable-line react-hooks/exhaustive-deps

  const zoomBy = useCallback((factor: number) => {
    zoomTo(clampZoom(zoom * factor), null);
  }, [zoomTo, clampZoom, zoom]);

  const zoomAt = useCallback((vx: number, vy: number, factor: number) => {
    zoomTo(clampZoom(zoom * factor), { x: vx, y: vy });
  }, [zoomTo, clampZoom, zoom]);

  const percent = Math.round(scale * dpr * 100);
  const atActualSize = Math.abs(scale * dpr - 1) < 0.005;

  return {
    viewportRef, zoom, setZoom, pan, setPan, fit, scale, frameW, frameH, vp,
    safe, origin,
    percent, atActualSize, fitToScreen, actualSize, zoomBy, zoomAt, requestFit,
  };
}
