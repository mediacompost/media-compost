/** THE TAGS TAB'S TWO COLUMNS, and the split between them.
 *
 *  The way IN on the left, the list on the right — for the LIBRARY'S own
 *  tag set and for an imported set alike, because they are the same two
 *  columns showing the same kind of thing. This file owns the parts that are
 *  about the LAYOUT rather than about either list: the divider that drags,
 *  the width it remembers, and how tall a pane beside a scrolling page may
 *  be.
 *
 *  It was written twice before this — the Sets tab had a draggable divider
 *  and a measured pane height, the library's list had a fixed 220 px sticky
 *  column — which is exactly the drift one component is for. */
import React, { useEffect, useRef, useState } from "react";
import { numPref } from "../../shared/storage";
import { SplitHandle, useSplit } from "../../shared/Split";
import { storage } from "../../shared/storage";

import { useT } from "../i18n";

/** Where the divider's width is remembered. One key for both lists: it is
 *  one sidebar in one tab, and a width that changed when the pill above it
 *  changed would read as the column jumping. (The Sets tab's own key is read
 *  once, so a width somebody had already dragged is kept.) */
const W_KEY = "mc.tags.sidebarW";
export const SIDEBAR_W_MIN = 180, SIDEBAR_W_MAX = 560;
/** What the list beside it may never be squeezed under. */
const LIST_W_MIN = 360;
/** How much of the window a PINNED pane leaves under itself. */
const STICKY_EDGE = 6;

/** THE PAGE'S INSET, THE SAME ON EVERY SIDE (owner 2026-09). The Tags tab
 *  and the Faces tab are two columns of rows and cards, and 32 px down
 *  either side of them was reading-width padding on a page that has no
 *  prose in it — while the bottom carried 60, room left over from when the
 *  list ended in a floating bar. One number, small, and the same all round:
 *  the content is what the eye follows, and an inset that differs per edge
 *  is one more thing drawing it.
 *
 *  EVERY BLEED IS MEASURED AGAINST IT. Both tabs have a sticky band that
 *  paints over this padding (negative margin out, the same padding back in)
 *  so rows do not slide past visibly at the edges — spelled from here, so
 *  the band and the page cannot disagree. */
export const PAGE_PAD = 12;

function readWidth(key: string): number {
  try {
    const v = Number(storage.get(key));
    if (v >= SIDEBAR_W_MIN) return Math.min(v, SIDEBAR_W_MAX);
  } catch { /* private mode */ }
  return 260;
}

/** HOW TALL A PANE BESIDE THE PAGE MAY BE: what is left of the scroller
 *  under whatever sits above the columns, less the page shell's own bottom
 *  padding. Guessing either left the content exactly that much taller than
 *  the scroller — a page scrollbar beside the inner ones, which is the one
 *  thing the panes exist to avoid.
 *
 *  TWO ANSWERS, because a pane that STICKS has a different amount of room
 *  once it is stuck (owner 2026-09). `flow` is for a pane that scrolls away
 *  with the page: it starts `above` px down the scroller, so that is what it
 *  gives up. `sticky` is for one pinned to the scroller's top edge, where
 *  what it gives up is only so much of `above` as has not been scrolled past
 *  — nothing, once the page has scrolled that far. The sidebar used `flow`
 *  and therefore kept a gap at the bottom the whole height of the page's
 *  heading, which grew as the list beside it grew: the taller the page, the
 *  further down the column was pinned and the more room it was still
 *  refusing to use.
 *
 *  A HEIGHT FROM THE FIRST PAINT, never `undefined`: an unbounded pane is a
 *  scroller as tall as its own content, and a windowed list sized against
 *  that mounts every row it has before the real height arrives. */
export function usePaneHeight(scroller: React.RefObject<HTMLElement | null>,
                              columns: React.RefObject<HTMLElement | null>,
                              deps: React.DependencyList = []) {
  const first = typeof window === "undefined"
    ? 600 : Math.max(220, window.innerHeight);
  const [h, setH] = useState<{ flow: number; sticky: number }>(
    () => ({ flow: first, sticky: first }));
  useEffect(() => {
    const sc = scroller.current;
    if (!sc) return;
    const read = () => {
      const cols = columns.current;
      if (!cols) return;
      const above = cols.getBoundingClientRect().top
        - sc.getBoundingClientRect().top + sc.scrollTop;
      let below = 0;
      for (let el = cols.parentElement; el && el !== sc; el = el.parentElement) {
        const cs = getComputedStyle(el);
        below += parseFloat(cs.paddingBottom) || 0;
        below += parseFloat(cs.marginBottom) || 0;
      }
      // `Math.max` keeps a very short window from producing a pane with no
      // rows in it at all.
      const flow = Math.max(220, sc.clientHeight - above - below);
      // The PAGE's bottom padding is what `flow` gives up, because a pane in
      // the flow sits inside it. A PINNED one stands against the window,
      // where that padding is somewhere else entirely — so it keeps only a
      // hairline of its own, and reaches almost the bottom edge.
      const sticky = Math.max(
        220, sc.clientHeight - Math.max(0, above - sc.scrollTop) - STICKY_EDGE);
      // Only when it CHANGES: this runs on every scroll event, and once the
      // column is pinned the answer stops moving — so a page being scrolled
      // through re-renders the list twice, at the two ends of the heading.
      setH((cur) => cur.flow === flow && cur.sticky === sticky
        ? cur : { flow, sticky });
    };
    read();
    const ro = new ResizeObserver(read);
    ro.observe(sc);
    if (columns.current) ro.observe(columns.current);
    sc.addEventListener("scroll", read, { passive: true });
    return () => {
      ro.disconnect();
      sc.removeEventListener("scroll", read);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scroller, columns, ...deps]);
  return h;
}

/** The two columns, with the divider between them.
 *
 *  Exactly two children: the sidebar, then the list. The grid's own box is
 *  handed back through `columnsRef` so the host can measure its panes
 *  against it (`usePaneHeight`) — the height is a fact about what sits ABOVE
 *  the columns, which only the page knows. */
export function TagsPanes({ columnsRef, split = true, widthKey, children }: {
  columnsRef?: React.MutableRefObject<HTMLDivElement | null>;
  /** Where THIS split remembers its width. The Tags tab's two lists share
   *  one (it is one sidebar in one tab, and a width that changed with the
   *  pill above it would read as the column jumping); the Faces tab's
   *  clusters are a different column beside a different thing, so they
   *  remember their own. */
  widthKey?: string;
  /** False draws ONE column and no divider — the sub-tabs that have no
   *  sidebar. The list is the same list either way, so this is a prop
   *  rather than a second layout around it. */
  split?: boolean;
  children: React.ReactNode;
}) {
  const t = useT();
  const own = useRef<HTMLDivElement | null>(null);
  const ref = columnsRef ?? own;
  const key = widthKey ?? W_KEY;
  const divider = useSplit({
    pref: numPref(key, { def: 260, min: SIDEBAR_W_MIN, max: SIDEBAR_W_MAX }),
    initial: readWidth(key), min: SIDEBAR_W_MIN, max: SIDEBAR_W_MAX,
    axis: "x", from: "start", restMin: LIST_W_MIN, frameRef: ref,
  });
  const w = divider.size;

  return (
    <div ref={ref}
         style={{ display: "grid",
                  gridTemplateColumns: split
                    ? `${w}px minmax(0, 1fr)` : "minmax(0, 1fr)",
                  // The columns stand the page's own inset apart: a way IN
                  // beside the list it narrows is one thing on one page, and
                  // a wider channel between them than around them read as
                  // two panels sharing a window.
                  gap: PAGE_PAD, alignItems: "start", position: "relative" }}>
      {/* A 6 px handle in the gap between the columns — the width remembered
          per browser, clamped so neither column can be dragged out of
          usefulness. */}
      {split && (
        <SplitHandle split={divider} title={t("Drag to resize the columns")} style={{ left: w + 5 }} />
      )}
      {children}
    </div>
  );
}
