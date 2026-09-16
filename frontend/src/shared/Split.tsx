// ONE DRAGGABLE DIVIDER. Six dividers in four implementations: the
// library's two (window listeners armed for the life of the page), the
// Tags tab's (writing localStorage on every mousemove), the Train and
// Evaluate tabs' (`SidebarSplit`, the best of them), the annotator's two
// and the sidebar's quick-assign drawer. This is the mechanics once:
// listeners for the drag only, `body.resizing` (or `resizing-v`) so the
// drag selects no text through the page, a clamp against the room the
// frame leaves, and the size written to its pref at mouseup, never per
// sample. Pure `clampSplit` is tested.
import React, { useCallback, useEffect, useRef, useState } from "react";
import type { Pref } from "./storage";
import { clampSplit } from "./splitMath";

export { clampSplit };


export interface SplitOptions {
  /** Where the size is remembered; absent = not remembered. */
  pref?: Pref<number>;
  /** A size to start from instead of the pref's (a legacy key read once). */
  initial?: number;
  min: number;
  /** A number, or a function for a bound that depends on the window. */
  max: number | (() => number);
  axis: "x" | "y";
  /** Which edge the divider is measured from: a sidebar at the left grows
   *  with the pointer (start); a panel at the right or a drawer at the
   *  bottom grows against it (end). */
  from: "start" | "end";
  /** What the other side must keep. */
  restMin?: number;
  /** The element the room is measured in; the window otherwise. */
  frameRef?: React.RefObject<HTMLElement | null>;
  /** Re-clamp when the window changes size (a drawer capped at half of it). */
  reclampOnResize?: boolean;
}

export interface Split {
  size: number;
  setSize: React.Dispatch<React.SetStateAction<number>>;
  dragging: boolean;
  /** The handle's mousedown. */
  start: (e: React.MouseEvent) => void;
  axis: "x" | "y";
}

export function useSplit(o: SplitOptions): Split {
  const { axis, from, min, restMin = 0 } = o;
  const maxOf = () => (typeof o.max === "function" ? o.max() : o.max);
  const room = () => {
    const el = o.frameRef?.current;
    if (axis === "x") return el ? el.clientWidth : window.innerWidth;
    return el ? el.clientHeight : window.innerHeight;
  };
  const clamp = (v: number) => clampSplit(v, { min, max: maxOf(), room: room(), restMin });
  const [size, setSize] = useState(() => clamp(o.initial ?? o.pref?.read() ?? min));
  const [dragging, setDragging] = useState(false);
  const live = useRef({ o, clamp });
  live.current = { o, clamp };

  useEffect(() => {
    if (!o.reclampOnResize) return;
    const onResize = () => setSize((s) => live.current.clamp(s));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [o.reclampOnResize]);

  const start = useCallback((e: React.MouseEvent) => {
    e.preventDefault();   // or the mousedown begins a text selection
    e.stopPropagation();
    const at = axis === "x" ? e.clientX : e.clientY;
    let cur = 0;
    setSize((s) => { cur = s; return s; });
    const startSize = cur;
    const cls = axis === "x" ? "resizing" : "resizing-v";
    document.body.classList.add(cls);
    setDragging(true);
    const move = (ev: MouseEvent) => {
      const d = (axis === "x" ? ev.clientX : ev.clientY) - at;
      cur = live.current.clamp(startSize + (from === "start" ? d : -d));
      setSize(cur);
    };
    const up = () => {
      document.body.classList.remove(cls);
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      setDragging(false);
      // Written at the END of the drag, not per sample: localStorage is
      // synchronous, and the library's own divider learnt that first.
      live.current.o.pref?.write(cur);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }, [axis, from]);

  return { size, setSize, dragging, start, axis };
}

/** The strip somebody grabs: absolute across the frame by default (the
 *  caller positions it with `style`), or in the flow beside what it sizes
 *  (`inFlow`), with an optional hairline drawn down its middle. */
export function SplitHandle({ split, title, thickness = 6, inFlow, hairline, style }: {
  split: Split;
  title?: string;
  thickness?: number;
  inFlow?: boolean;
  hairline?: boolean;
  style?: React.CSSProperties;
}) {
  const x = split.axis === "x";
  const cursor = x ? "col-resize" : "row-resize";
  if (inFlow) {
    return (
      <div onMouseDown={split.start} title={title}
           style={{ flex: "0 0 auto", [x ? "width" : "height"]: thickness, cursor,
                    display: "flex", justifyContent: "center", alignItems: "center", ...style }}>
        {hairline && (
          <div style={{ [x ? "width" : "height"]: 1, alignSelf: "stretch", flex: x ? undefined : 1,
                        background: "var(--border)" }} />
        )}
      </div>
    );
  }
  return (
    <div onMouseDown={split.start} title={title}
         style={{ position: "absolute", ...(x ? { top: 0, bottom: 0, width: thickness }
                                              : { left: 0, right: 0, height: thickness }),
                  cursor, zIndex: 5, ...style }} />
  );
}
