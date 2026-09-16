/** THE CARD GRID'S GEOMETRY AND BOX, AS A HOOK.
 *
 *  `CardGrid` is this plus a render; the library's grid is this plus paging,
 *  ids and a keyboard walk. Everything that is about WHERE a card sits and
 *  WHICH cards a dragged box covers lives here once: the sticky column
 *  count, the window (only rows near the viewport are mounted), the grouped
 *  layout, the scaled spacer a million-card grid needs, and the marquee —
 *  its click threshold, its one hit-test a frame, its auto-scroll near the
 *  scroller's edges. The pure arithmetic is `gridGeom.ts`.
 */
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  columnsFor, gridWindow, groupLayout, groupWindow, marqueeHits,
  marqueeHitsGrouped, scrollScale, type GroupLayout, type GroupRun,
} from "../gridGeom";

export interface CardGridOptions {
  /** How many cards there are, loaded or not. */
  count: number;
  /** The minimum column width — one of `GRID_SIZES`' px values. */
  size: number;
  /** A fixed block under the square thumb: part of the card's height. */
  metaH?: number;
  gap?: number;
  /** Inset from the wrapper's own edges; the marquee and the column
   *  arithmetic both have to agree about it. */
  pad?: number;
  /** The element that actually scrolls these cards. */
  scrollRef: React.RefObject<HTMLElement | null>;
  /** Sections, as runs of the flat order. Null is one block. */
  runs?: GroupRun[] | null;
  headerH?: number;
  groupGap?: number;
  /** Rows mounted above and below the viewport. */
  rowBuffer?: number;
  /** False where a box selection means nothing. */
  marquee?: boolean;
  /** What a press on a card looks like — such a press is never a box. */
  cardSelector?: string;
  /** A box was dragged over these indices; `additive` is shift/⌘ at the press. */
  onMarquee?: (indices: number[], additive: boolean) => void;
  /** The press that begins a box, before any hit is known. */
  onMarqueeStart?: (e: React.MouseEvent) => void;
  /** A press on the background that never became a box — a click on nothing. */
  onBackgroundClick?: (additive: boolean) => void;
  /** The scroller moved; `top` is the virtual scroll position of the grid. */
  onScroll?: (top: number) => void;
}

export interface CardGridState {
  wrapRef: React.RefObject<HTMLDivElement>;
  columns: number;
  cellW: number;
  rowStride: number;
  layout: GroupLayout | null;
  win: ReturnType<typeof gridWindow>;
  gwin: ReturnType<typeof groupWindow> | null;
  totalH: number;
  physH: number;
  vScale: number;
  yShift: number;
  /** The grid's own virtual scroll position and the viewport's height. */
  scrollTop: number;
  vpH: number;
  fillH: number;
  /** DOM ↔ virtual: a scaled scrollbar's reads and writes convert. */
  toVirt: (p: number) => number;
  toPhys: (v: number) => number;
  /** The box being dragged, in the grid's own coordinates. */
  box: { left: number; top: number; width: number; height: number } | null;
  onMouseDown: (e: React.MouseEvent) => void;
  /** True after a press that turned into a box — the click it still emits
   *  on mouseup is one to swallow. Cleared by the reader. */
  dragMoved: React.MutableRefObject<boolean>;
}

export function useCardGrid(o: CardGridOptions): CardGridState {
  const { count, size, metaH = 0, gap = 10, pad = 0, scrollRef, runs, headerH = 34,
          groupGap = 10, rowBuffer = 2, marquee = true, cardSelector = "[data-card]" } = o;
  const wrapRef = useRef<HTMLDivElement>(null);
  const [trackW, setTrackW] = useState(0);
  const [vpH, setVpH] = useState(0);
  // The scroller's own scrollTop, and where this grid's content box starts
  // inside it: the window is computed in the grid's own coordinates, so a
  // grid under a toolbar or a heading is windowed correctly.
  const [scrollTop, setScrollTop] = useState(0);
  const [gridTop, setGridTop] = useState(0);
  // Where a box may begin when the cards do not fill the screen: the
  // wrapper reaches the bottom of the scroller, less the page's padding.
  const [fillH, setFillH] = useState(0);
  const cb = useRef(o); cb.current = o;

  useLayoutEffect(() => {
    const el = wrapRef.current;
    const sc = scrollRef.current;
    if (!el) return;
    let raf = 0;
    const read = () => {
      setTrackW(Math.max(0, el.clientWidth - pad * 2));
      if (sc) {
        setVpH(sc.clientHeight);
        const top = el.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop;
        setGridTop(top);
        let below = 0;
        for (let n = el.parentElement; n && n !== sc; n = n.parentElement) {
          const cs = getComputedStyle(n);
          below += parseFloat(cs.paddingBottom) || 0;
          below += parseFloat(cs.marginBottom) || 0;
        }
        setFillH(Math.max(0, sc.clientHeight - top - below));
      } else {
        setVpH(window.innerHeight);
      }
    };
    read();
    // Measured on a frame: reading synchronously in the observer callback,
    // re-rendering and re-firing it can loop the column count.
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(read);
    });
    ro.observe(el);
    if (sc) ro.observe(sc);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, [scrollRef, pad, count, runs]);

  // ---- geometry ------------------------------------------------------------
  // The count is STICKY (`columnsFor`); a different card SIZE starts afresh.
  const lastColumns = useRef(0);
  const lastSize = useRef(size);
  if (lastSize.current !== size) { lastSize.current = size; lastColumns.current = 0; }
  const columns = columnsFor(trackW, size, gap, lastColumns.current);
  lastColumns.current = columns;
  const cellW = columns > 0 && trackW > 0 ? (trackW - (columns - 1) * gap) / columns : size;
  const rowStride = cellW + metaH + gap;

  const layout: GroupLayout | null = useMemo(
    () => (runs && runs.length
      ? groupLayout({ runs, columns, cellW, metaH, pad, gap, headerH, groupGap })
      : null),
    [runs, columns, cellW, metaH, pad, gap, headerH, groupGap]);

  const localTop = scrollTop - gridTop;
  const gwin = layout
    ? groupWindow({ layout, scrollTop: localTop, viewportH: vpH, buffer: rowBuffer })
    : null;
  const win = gridWindow({
    total: count, columns, cellW, metaH, pad, gap, scrollTop: localTop,
    viewportH: vpH, buffer: rowBuffer,
  });
  const totalH = layout ? layout.totalH : win.totalH;
  // THE SCALED SCROLLBAR (`scrollScale`): past the browser's element-height
  // cap the spacer is scaled and the content DRAWN shifted into it; the
  // window, the layout and the box stay in virtual space.
  const { physH, k: vScale } = scrollScale(totalH, vpH);
  const toVirt = (p: number) => (vScale === 1 ? p : p * vScale);
  const toPhys = (v: number) => (vScale === 1 ? v : v / vScale);
  const yShift = vScale === 1 ? 0 : toPhys(localTop) - localTop;

  useEffect(() => {
    const sc = scrollRef.current;
    if (!sc) return;
    const onScroll = () => {
      const top = vScaleRef.current === 1 ? sc.scrollTop : sc.scrollTop * vScaleRef.current;
      setScrollTop(top);
      cb.current.onScroll?.(top - gridTopRef.current);
    };
    onScroll();
    sc.addEventListener("scroll", onScroll, { passive: true });
    return () => sc.removeEventListener("scroll", onScroll);
  }, [scrollRef]);
  const vScaleRef = useRef(vScale); vScaleRef.current = vScale;
  const gridTopRef = useRef(gridTop); gridTopRef.current = gridTop;

  // ---- the box -------------------------------------------------------------
  const geomRef = useRef({ columns, cellW, rowStride, count, layout, metaH, vScale, yShift, pad, gap });
  geomRef.current = { columns, cellW, rowStride, count, layout, metaH, vScale, yShift, pad, gap };
  const [box, setBox] = useState<CardGridState["box"]>(null);
  const drag = useRef<{
    startX: number; startY: number; clientX: number; clientY: number;
    additive: boolean; moved: boolean; raf: number | null;
  } | null>(null);
  const dragMoved = useRef(false);

  useEffect(() => {
    const apply = () => {
      const d = drag.current;
      const el = wrapRef.current;
      if (!d || !d.moved || !el) return;
      // THE WRAPPER'S OWN RECT IS THE COORDINATE SPACE, and it moves with
      // the scroll; `yShift` is the only correction.
      const b = el.getBoundingClientRect();
      const g = geomRef.current;
      const curX = d.clientX - b.left;
      const curY = d.clientY - b.top - g.yShift;
      const rect = {
        left: Math.min(d.startX, curX), right: Math.max(d.startX, curX),
        top: Math.min(d.startY, curY), bottom: Math.max(d.startY, curY),
      };
      setBox({ left: rect.left, top: rect.top, width: rect.right - rect.left, height: rect.bottom - rect.top });
      const hits = g.layout
        ? marqueeHitsGrouped(g.layout, rect)
        : marqueeHits({ columns: g.columns, cellW: g.cellW, rowStride: g.rowStride,
                        total: g.count, pad: g.pad, gap: g.gap }, rect);
      cb.current.onMarquee?.(hits, d.additive);
    };
    const onMove = (e: MouseEvent) => {
      const d = drag.current;
      const el = wrapRef.current;
      if (!d || !el) return;
      d.clientX = e.clientX; d.clientY = e.clientY;
      if (!d.moved) {
        const b = el.getBoundingClientRect();
        const curX = e.clientX - b.left, curY = e.clientY - b.top - geomRef.current.yShift;
        if (Math.hypot(curX - d.startX, curY - d.startY) < 4) return; // a click, not a drag
        d.moved = true;
        dragMoved.current = true;
        // One hit-test a FRAME, not one per mousemove — and, while the
        // pointer sits near the scroller's top or bottom edge, a scroll.
        const loop = () => {
          const dd = drag.current;
          const sc = cb.current.scrollRef.current;
          if (!dd) return;
          if (sc) {
            const sb = sc.getBoundingClientRect();
            const vy = dd.clientY - sb.top;
            const EDGE = 40, SPEED = 22;
            if (vy < EDGE) sc.scrollTop -= SPEED * (1 - Math.max(0, vy) / EDGE);
            else if (vy > sb.height - EDGE) sc.scrollTop += SPEED * (1 - Math.max(0, sb.height - vy) / EDGE);
          }
          apply();
          dd.raf = requestAnimationFrame(loop);
        };
        d.raf = requestAnimationFrame(loop);
      }
      e.preventDefault();
    };
    const onUp = () => {
      const d = drag.current;
      if (!d) return;
      if (d.raf != null) cancelAnimationFrame(d.raf);
      document.body.style.userSelect = "";
      // A press that never moved is a click on nothing.
      if (!d.moved) cb.current.onBackgroundClick?.(d.additive);
      drag.current = null;
      setBox(null);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // A PRESS ON A CARD IS NOT A BOX: the card's own click, its native drag and
  // whatever paint gesture the host put on it all begin with a mousedown.
  const onMouseDown = (e: React.MouseEvent) => {
    if (!marquee || e.button !== 0) return;
    const el = wrapRef.current;
    if (!el) return;
    const sc = scrollRef.current;
    // A press in the scrollbar gutter is the scrollbar's.
    if (sc && e.clientX - sc.getBoundingClientRect().left >= sc.clientWidth) return;
    if ((e.target as HTMLElement).closest(cardSelector)) return;
    cb.current.onMarqueeStart?.(e);
    const b = el.getBoundingClientRect();
    e.preventDefault();
    document.body.style.userSelect = "none";
    dragMoved.current = false;
    drag.current = {
      startX: e.clientX - b.left,
      startY: e.clientY - b.top - geomRef.current.yShift,
      clientX: e.clientX, clientY: e.clientY,
      additive: e.shiftKey || e.metaKey || e.ctrlKey,
      moved: false, raf: null,
    };
  };

  return { wrapRef, columns, cellW, rowStride, layout, win, gwin, totalH, physH, vScale, yShift,
           scrollTop: localTop, vpH, fillH, toVirt, toPhys, box, onMouseDown, dragMoved };
}
