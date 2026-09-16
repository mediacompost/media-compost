/**
 * THE ITEM WINDOW'S CONTROLS, FLOATING OVER THE PICTURE — one bar per group.
 *
 * Undo/redo and the Image / Selection / Video menus used to live in the
 * header, alongside the item's name, the window's own ways out, the theme
 * button and Save. That put two different kinds of thing in one row: what you
 * do TO the picture, and what this WINDOW is and how you leave it. The first
 * kind belongs over the picture — the image editor's tool palette, properties
 * bar, help line and zoom cluster are already there — and moving them there
 * leaves the header saying what it is for.
 *
 * ONE BAR PER GROUP rather than one bar holding everything: undoing is not the
 * same kind of act as opening a menu of transformations, and a single pill
 * with a divider in it says they are. Separate pills say it by being separate.
 *
 * They sit at the TOP LEFT of the picture area, in a row, and the row REPORTS
 * ITS WIDTH (`onWidth`) — the image editor's properties bar is centred up
 * there too and has to be centred in what is LEFT rather than in the whole
 * canvas, or the two overlap on a narrow window. That is the same rule the
 * annotator's hint bar follows around the zoom cluster: an overlap is the one
 * thing neither of two floating things can notice about the other.
 */
import React, { useEffect, useRef } from "react";

/** The height every floating bar up here shares, so the row reads level with
 *  the image editor's properties bar beside it. */
export const CANVAS_BAR_H = 42;

/**
 * WHAT THE FLOATING BARS COVER, on each edge of the canvas — the safe area the
 * picture is fitted into rather than under.
 *
 * The row above at the top (12 + its 42 px height + a gap) and the zoom cluster
 * and media bar along the bottom (12 + 32 + a gap), with the windows' own 14 px
 * margin either side. `useZoomPan` takes it as `inset`; the image editor has
 * one of its own, because a tool palette runs down its left edge.
 */
export const CANVAS_INSET = { l: 14, t: CANVAS_BAR_H + 22, r: 14, b: 54 };

/** One group of controls, as its own pill. */
export function CanvasBar({ children }: { children: React.ReactNode }) {
  return (
    <div
      onMouseDown={(e) => e.stopPropagation()}
      style={{
        // Padding 4 on every edge and an outer radius of 12 = the children's
        // 8 plus that padding, so the corners run concentric — the properties
        // bar's rule, because this is the same bar.
        height: CANVAS_BAR_H, boxSizing: "border-box", flex: "0 0 auto",
        display: "flex", alignItems: "center", padding: 4, gap: 4,
        background: "var(--surface-float)", border: "1px solid var(--border)",
        borderRadius: "var(--r-7)", boxShadow: "var(--shadow-2)",
        pointerEvents: "auto",
      }}
    >
      {children}
    </div>
  );
}

/**
 * The row they sit in, at the picture's top left.
 *
 * `left` clears whatever else is already pinned there — the image editor's
 * tool palette is a column in that corner, so its bars start past it.
 */
export function CanvasBarRow({ left = 12, top = 12, onWidth, children }: {
  left?: number;
  top?: number;
  /** The row's measured width, for a neighbour that has to keep clear of it. */
  onWidth?: (px: number) => void;
  children: React.ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const cb = useRef(onWidth);
  cb.current = onWidth;
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => cb.current?.(el.offsetWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div
      ref={box}
      style={{ position: "absolute", left, top, zIndex: 11, display: "flex",
        alignItems: "flex-start", gap: 8, pointerEvents: "none" }}
    >
      {children}
    </div>
  );
}
