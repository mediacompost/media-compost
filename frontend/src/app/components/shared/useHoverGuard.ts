/**
 * Keep CSS `:hover` honest inside a scrolling list.
 *
 * Row actions here fade in with `.hoverable:hover .row-action-fixed`, and that
 * is the right mechanism: it costs no React state and cannot get out of step
 * with the DOM the way a per-row `onMouseEnter`/`onMouseLeave` pair does (that
 * was tried, and left buttons stuck visible whenever the list re-rendered
 * under the cursor).
 *
 * What it cannot do by itself is notice that the CONTENT moved while the
 * pointer stood still. A browser recomputes `:hover` from pointer events, so
 * scrolling a list under a stationary cursor — or a row arriving, leaving or
 * being re-keyed underneath it — leaves the old row hovered until the mouse is
 * moved again. Safari is the one that shows it most: it holds the stale state
 * across a wheel scroll where Chromium re-resolves on the next frame. The
 * symptom is a "go to this item" button that stays lit on a row the pointer
 * has long left.
 *
 * So the pointer position is remembered and the answer re-derived — from
 * `elementFromPoint`, i.e. from where the pointer actually is — whenever the
 * container scrolls or its contents change. `nohover` on the container is what
 * that decision writes, and `tokens.css` gives it enough specificity to beat
 * the `:hover` rule. Leaving the container clears it outright.
 *
 * Deliberately NOT "hide everything while scrolling": that would blink the
 * button off every wheel tick even when the pointer really is still on its
 * row. The point is to answer the question correctly, not to duck it.
 */
import { useEffect } from "react";

export function useHoverGuard(
  ref: { current: HTMLElement | null },
  /** Anything that changes the rows, so the answer is re-derived after the
   *  list has re-rendered under a pointer that never moved. */
  deps: unknown[] = [],
) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Where the pointer was when we last heard from it. `seen` is false before
    // the first move and after the pointer leaves, and while it is false there
    // is nothing to re-derive — `elementFromPoint(-1, -1)` would answer for a
    // corner nobody is pointing at.
    let x = -1, y = -1, seen = false;

    const recheck = () => {
      if (!seen) return;
      const under = document.elementFromPoint(x, y);
      el.classList.toggle("nohover", !under || !under.closest(".hoverable"));
    };
    const onMove = (e: PointerEvent) => {
      x = e.clientX; y = e.clientY; seen = true;
      // A real pointer move is what the browser's own `:hover` is already
      // right about, so this only has to get out of the way.
      el.classList.remove("nohover");
    };
    const onLeave = () => { seen = false; el.classList.add("nohover"); };

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    el.addEventListener("scroll", recheck, { passive: true });
    // The rows themselves changing counts as the content moving.
    const obs = new MutationObserver(recheck);
    obs.observe(el, { childList: true, subtree: true });
    recheck();
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      el.removeEventListener("scroll", recheck);
      obs.disconnect();
      el.classList.remove("nohover");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, ...deps]);
}
