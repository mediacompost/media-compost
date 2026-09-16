// Shared list virtualization — the item grid's scrollTop→row-window approach
// (gridGeom.ts) generalized to any vertical list of same-height rows. No
// dependency: a hook that watches a scroll container and answers "which rows
// to mount, and where".
//
// Rendering pattern:
//
//   const win = useWindowedList({ count, rowHeight, scrollRef });
//   <div ref={win.containerRef}
//        style={{ height: win.totalHeight, position: "relative" }}>
//     <div style={{ position: "absolute", top: win.topOffset, left: 0, right: 0 }}>
//       {rows.slice(win.start, win.end).map(...)}
//     </div>
//   </div>
//
// The list does not have to sit at the top of the scroll content: the
// container's own offset inside the scroller is measured (containerRef), so a
// windowed list can follow headers, drop zones or another list.
//
// `rowHeight` is an ESTIMATE where rows can grow (a wrapped subtitle, a strip
// of face crops): rows inside the window still render at their natural height
// — only which slice mounts and the scrollbar's span are computed from the
// estimate. `minCount` keeps small lists out of the window entirely
// (windowed: false → render the plain flow), so exact layout is preserved
// wherever O(count) rendering is affordable anyway.

import { useCallback, useLayoutEffect, useRef, useState } from "react";

export interface WindowedList {
  /** First mounted row index. */
  start: number;
  /** One past the last mounted row index. */
  end: number;
  /** px from the list container's top to the first mounted row. */
  topOffset: number;
  /** Full height of the list (count × rowHeight). */
  totalHeight: number;
  /** False while `count` is under `minCount` — render the plain flow then. */
  windowed: boolean;
  /** Attach to the outer list container (the div taking `totalHeight`). */
  containerRef: (el: HTMLElement | null) => void;
  /** Scroll the container so row `i` sits near the middle of the viewport.
   *  The window recomputes immediately, so the row mounts on the very next
   *  render — a jump-to-row can then find it in the DOM. */
  scrollToIndex: (i: number) => void;
}

/** Which rows to mount, as arithmetic — pure, so the rule below can be
 *  stated in a test rather than only observed in a browser.
 *
 *  `rel` is the scroll position relative to the list's top; `clientHeight` is
 *  the scroller's; `viewportHeight` the window's.
 *
 *  **THE SCREEN IS THE BOUND, NOT THE SCROLLER.** A scroller is normally
 *  shorter than the window, and for a while this simply divided its
 *  `clientHeight` by the row height. But a scroller is only as short as
 *  whatever constrains it, and a pane whose `max-height` is MEASURED is
 *  unbounded until the measurement lands: for that one render its
 *  `clientHeight` is its whole content, and "how many rows fit" answers ALL
 *  OF THEM. On the Sets tab that mounted 17,245 rows — 375,000 DOM nodes and
 *  1.2 seconds of blocked main thread — before the pane's height arrived and
 *  it windowed back down to a screenful. Nothing can be visible past the
 *  window's own height, whatever the box says. */
export function windowRange({
  count, rowHeight, overscan, rel, clientHeight, viewportHeight,
}: {
  count: number; rowHeight: number; overscan: number;
  rel: number; clientHeight: number; viewportHeight: number;
}): { start: number; end: number } {
  const start = Math.min(
    Math.max(0, Math.floor(rel / rowHeight) - overscan),
    Math.max(0, count - 1));
  const box = Math.min(Math.max(0, clientHeight),
                       Math.max(0, viewportHeight) || clientHeight);
  const visible = Math.ceil(box / rowHeight) + overscan * 2;
  return { start, end: Math.min(count, start + visible) };
}

export function useWindowedList({
  count, rowHeight, scrollRef, overscan = 8, minCount = 0,
}: {
  count: number;
  rowHeight: number;
  scrollRef: React.RefObject<HTMLElement | null>;
  /** Extra rows mounted above and below the viewport. */
  overscan?: number;
  /** Below this many rows the list is not windowed at all. */
  minCount?: number;
}): WindowedList {
  const windowed = count >= Math.max(1, minCount) && rowHeight > 0;
  const elRef = useRef<HTMLElement | null>(null);
  const [win, setWin] = useState<{ start: number; end: number }>(
    { start: 0, end: Math.min(count, overscan * 2 + 1) });

  // The list's top edge in the scroller's CONTENT coordinates. Measured, not
  // assumed: headers, drop zones or a sibling list may sit above it.
  const listTop = () => {
    const sc = scrollRef.current;
    const el = elRef.current;
    if (!sc || !el) return 0;
    return el.getBoundingClientRect().top - sc.getBoundingClientRect().top
      + sc.scrollTop;
  };

  // Everything the window depends on, readable from inside stable callbacks.
  const geom = useRef({ count, rowHeight, overscan, windowed });
  geom.current = { count, rowHeight, overscan, windowed };

  const recompute = useCallback(() => {
    const { count: n, rowHeight: rh, overscan: over, windowed: on } = geom.current;
    if (!on) {
      setWin((p) => (p.start === 0 && p.end === n ? p : { start: 0, end: n }));
      return;
    }
    const sc = scrollRef.current;
    if (!sc) return;
    const next = windowRange({
      count: n, rowHeight: rh, overscan: over,
      rel: sc.scrollTop - listTop(),
      clientHeight: sc.clientHeight,
      viewportHeight: window.innerHeight,
    });
    setWin((p) => (p.start === next.start && p.end === next.end ? p : next));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollRef]);

  const containerRef = useCallback((el: HTMLElement | null) => {
    elRef.current = el;
    if (el) recompute();
  }, [recompute]);

  useLayoutEffect(() => {
    recompute();
    const sc = scrollRef.current;
    if (!sc) return;
    const onScroll = () => recompute();
    sc.addEventListener("scroll", onScroll, { passive: true });
    // Viewport height changes (window resize, panels opening) move the window
    // too; a ResizeObserver on the scroller covers both.
    const ro = new ResizeObserver(onScroll);
    ro.observe(sc);
    return () => {
      sc.removeEventListener("scroll", onScroll);
      ro.disconnect();
    };
  }, [recompute, scrollRef, count, rowHeight, windowed]);

  const scrollToIndex = useCallback((i: number) => {
    const sc = scrollRef.current;
    if (!sc) return;
    const { count: n, rowHeight: rh } = geom.current;
    const idx = Math.max(0, Math.min(n - 1, i));
    const target = listTop() + idx * rh - (sc.clientHeight - rh) / 2;
    sc.scrollTop = Math.max(0, target);
    recompute();
  }, [recompute, scrollRef]);

  const start = windowed ? Math.min(win.start, Math.max(0, count - 1)) : 0;
  const end = windowed ? Math.min(win.end, count) : count;
  return {
    start,
    end: Math.max(start, end),
    topOffset: start * rowHeight,
    totalHeight: count * rowHeight,
    windowed,
    containerRef,
    scrollToIndex,
  };
}
