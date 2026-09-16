// "SOME OF WHAT YOU PICKED IS UP THERE" — the edge marks a scrolling list
// shows when its selection has left the view.
//
// A selection you cannot see is a selection you forget you made: the Sets
// tab's two panes both act on one (delete these categories, move these
// entries), and in a 387-row tree or a 17,000-row list the picked rows are
// usually somewhere else by the time the button is pressed. The mark says
// which way, and clicking it goes there.
//
// The two lists answer "where are the picked rows" differently — the tree
// has every row in the DOM, the entry list is windowed and mostly does not —
// so the hook takes OFFSETS in the scroller's own content coordinates and
// leaves working them out to the caller. That is the only thing they would
// have disagreed about anyway.

import React from "react";

import { Icon } from "../../shared/Icon";

export interface OffscreenSel {
  /** A picked row sits above / below what the scroller shows. */
  above: boolean;
  below: boolean;
  /** Scroll the nearest one back into view. */
  goUp: () => void;
  goDown: () => void;
}

export function useOffscreenSelection(
  scroller: React.RefObject<HTMLElement | null>,
  /** Each picked row's top, in the scroller's content coordinates. MEMOIZE:
   *  the effect re-arms whenever this array's identity changes. */
  offsets: number[],
  rowH: number,
): OffscreenSel {
  const [state, setState] = React.useState({ above: false, below: false });
  // Read inside the scroll handler rather than closed over, so the handler is
  // installed once per scroller and not once per selection change.
  const live = React.useRef({ offsets, rowH });
  live.current = { offsets, rowH };

  React.useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    let queued = false;
    const read = () => {
      queued = false;
      const { offsets: os, rowH: h } = live.current;
      const top = el.scrollTop;
      const bottom = top + el.clientHeight;
      // `some`, not a count: the mark says which way, and a number nobody
      // asked for is a number that has to be kept right.
      setState({
        above: os.some((o) => o + h <= top + 1),
        below: os.some((o) => o >= bottom - 1),
      });
    };
    const onScroll = () => {
      // One read a frame: a fast drag fires scroll far more often than the
      // mark can change.
      if (queued) return;
      queued = true;
      requestAnimationFrame(read);
    };
    read();
    el.addEventListener("scroll", onScroll, { passive: true });
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => { el.removeEventListener("scroll", onScroll); ro.disconnect(); };
  }, [scroller, offsets, rowH]);

  const go = (up: boolean) => () => {
    const el = scroller.current;
    if (!el) return;
    const { offsets: os, rowH: h } = live.current;
    const top = el.scrollTop;
    const bottom = top + el.clientHeight;
    // The NEAREST one in that direction, put a third of the way down the
    // view — landing a row hard against the edge reads as "still off screen".
    const hit = up
      ? Math.max(...os.filter((o) => o + h <= top + 1))
      : Math.min(...os.filter((o) => o >= bottom - 1));
    if (Number.isFinite(hit)) {
      el.scrollTo({ top: Math.max(0, hit - el.clientHeight / 3), behavior: "smooth" });
    }
  };
  return { ...state, goUp: go(true), goDown: go(false) };
}

/** The marks themselves, over a scroller's top and bottom edges. The parent
 *  must be `position: relative`; the strip takes no pointer events so the
 *  rows under it stay clickable, and only the pill itself does. */
export function OffscreenSelectionMarks({ sel, title }: {
  sel: OffscreenSel; title: string;
}) {
  const pill = (dir: "up" | "down", onClick: () => void): React.ReactNode => (
    <div style={{
      position: "absolute", left: 0, right: 0, [dir === "up" ? "top" : "bottom"]: 0,
      display: "flex", justifyContent: "center", pointerEvents: "none", zIndex: 2,
    }}>
      <button type="button" title={title} onClick={onClick}
        style={{
          pointerEvents: "auto", display: "flex", alignItems: "center",
          border: "none", cursor: "pointer", color: "var(--on-accent)",
          background: "var(--accent)", padding: "0 6px", height: 14,
          lineHeight: 0,
          borderRadius: dir === "up" ? "0 0 7px 7px" : "7px 7px 0 0",
        }}>
        <Icon name={dir === "up" ? "keyboard_arrow_up" : "keyboard_arrow_down"}
              size={13} />
      </button>
    </div>
  );
  return (
    <>
      {sel.above && pill("up", sel.goUp)}
      {sel.below && pill("down", sel.goDown)}
    </>
  );
}
