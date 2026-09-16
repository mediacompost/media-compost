// A PAGE MADE OF A SIDEBAR AND THE REST OF IT, with the divider between them
// draggable and the width remembered.
//
// The library has had this since the beginning and the Tags tab since its two
// columns became one component; the Train and Evaluate tabs were the two
// pages left with a number typed into the layout. The same shape lives here
// rather than in `app/`, because `train/` may not import that side (the
// bundle boundary `src/boundaries.test.ts` holds) — and a second
// implementation of "drag the edge, remember it" is how two pages end up
// disagreeing about what a sidebar may be.
//
// Exactly two children: the sidebar, then what it narrows. The handle
// straddles the border rather than sitting beside it (the library's own
// 6 px), and `body.resizing` is what stops the drag selecting text through
// the page — a class, not inline styles, since children set their own
// `user-select` and Safari needs the prefixed property too.
import React, { useRef } from "react";
import { SplitHandle, useSplit } from "./Split";
import { numPref } from "./storage";
import { storage } from "../shared/storage";

/** Narrower than this and the sidebar stops being one; wider and the page it
 *  narrows does. The maximum yields to the window: a sidebar dragged past
 *  what is there cannot leave the other half less than `REST_MIN`. */
export const SIDEBAR_MIN = 280;
export const SIDEBAR_MAX = 760;
const REST_MIN = 420;

export function SidebarSplit({ widthKey, initial, t, children }: {
  /** Where this page remembers its width. One key per page: the Train tab's
   *  job list and the Evaluate tab's form are different columns beside
   *  different things. */
  widthKey: string;
  /** The width before anybody has dragged it — what the page had typed in. */
  initial: number;
  /** Required, like every other piece of shared chrome: a package that
   *  fetched its own translations would be one the app cannot keep in step. */
  t: (s: string) => string;
  children: React.ReactNode;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const split = useSplit({
    pref: numPref(widthKey, { def: initial, min: SIDEBAR_MIN, max: SIDEBAR_MAX }),
    min: SIDEBAR_MIN, max: SIDEBAR_MAX, axis: "x", from: "start",
    restMin: REST_MIN, frameRef: frame,
  });
  const w = split.size;

  return (
    <div ref={frame} style={{
      flex: 1, minHeight: 0, display: "grid", position: "relative",
      // `minmax(0, 1fr)` and not `1fr`: a grid track's default minimum is its
      // content, so one wide child (a graph, a contact sheet) would push the
      // column past the window instead of scrolling inside it.
      gridTemplateColumns: `${w}px minmax(0, 1fr)`,
    }}>
      {children}
      <SplitHandle split={split} title={t("Drag to resize the sidebar")} style={{ left: w - 3 }} />
    </div>
  );
}
