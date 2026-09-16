import { useEffect, useRef } from "react";

/**
 * A WHEEL LISTENER THAT CAN REFUSE THE BROWSER'S OWN ZOOM.
 *
 * React registers `wheel` at the root container PASSIVELY (as it does
 * `touchstart` and `touchmove`), so `e.preventDefault()` inside an `onWheel`
 * prop does nothing whatever: the timeline's ctrl+wheel branch had called it
 * since the scale was written, and Firefox went on zooming the whole PAGE
 * underneath the zoom the timeline had just done. Over the editors' canvases
 * the page zoom is pure accident — a ctrl held for a shortcut and a wheel turn
 * meant for the picture — and it leaves the app at 110% with nothing on screen
 * saying so or offering the way back. (On a Mac a trackpad's pinch arrives as
 * a ctrl+wheel too, which is the gesture this makes zoom the picture.)
 *
 * So every wheel zoom here goes through a NATIVE listener registered
 * `{ passive: false }`, where preventDefault is honoured. WHETHER to call it is
 * the handler's own decision: over a picture the wheel always means the picture
 * (the surface has nothing of its own to scroll), while a timeline's plain
 * wheel must still reach the scroller the browser is already scrolling.
 *
 * Bound on EVERY render and re-attached only when the element identity changes
 * — the trap `useZoomPan`'s observer documents, for the same reason and in the
 * same windows: a window that renders its viewport only once the item detail
 * has loaded has no element at mount, and a `[]`-dep effect would return there
 * and never run again.
 */
export function useWheel(
  ref: React.RefObject<HTMLElement>,
  onWheel: (e: WheelEvent) => void,
): void {
  const handler = useRef(onWheel);
  handler.current = onWheel;
  const bound = useRef<HTMLElement | null>(null);
  const unbind = useRef<(() => void) | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (el === bound.current) return;
    unbind.current?.();
    bound.current = el;
    if (!el) { unbind.current = null; return; }
    const fn = (e: WheelEvent) => handler.current(e);
    el.addEventListener("wheel", fn, { passive: false });
    unbind.current = () => el.removeEventListener("wheel", fn);
  });
  useEffect(() => () => { unbind.current?.(); unbind.current = null; }, []);
}
