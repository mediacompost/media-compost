/** OPTIMISTIC ITEM ROTATION, for every place a picture can be turned.
 *
 * Rotating is a server write that rewrites a file's bytes, so the answer
 * arrives long after the click — and the click is one somebody makes four
 * times in a row on a sideways photograph. So the picture turns AT ONCE, in
 * CSS, while the writes drain behind it: `angle` is the target somebody has
 * asked for and `css` is the gap between that target and the angle the
 * server has actually baked, which collapses to 0 the moment the two agree.
 *
 * The queue is a NET COUNT of quarter turns rather than a list of requests:
 * four fast clicks are four writes, but a click and its undo cancel before
 * either is sent.
 *
 * One implementation, because there are two callers — the properties panel's
 * preview and the session overlays' card — and a picture that turned
 * instantly in one place and after a round trip in the other would be one
 * behaviour wearing two.
 */
import { useEffect, useRef, useState } from "react";

import { api } from "../../api";

const norm = (d: number) => ((d % 360) + 360) % 360;

export function useRotate(
  itemId: number | null,
  /** The angle the SERVER has baked in — the item's own `rotation`. */
  rotation: number,
  /** Called after each write lands, so the caller can refresh what it draws
   *  (the baked thumbnail catches up progressively). */
  onRotated: () => void,
) {
  const [target, setTarget] = useState<number | null>(null);
  const pending = useRef(0);      // net quarter-turns queued but not yet sent
  const running = useRef(false);  // a drain loop is in flight

  // Drop the override once the server angle matches the target and the queue
  // has drained, or a residual CSS transform would sit on top of a picture
  // that is already turned.
  useEffect(() => {
    if (target !== null && pending.current === 0
        && norm(target) === norm(rotation)) setTarget(null);
  }, [rotation, target]);

  // A different item is a different question: the queue and the override
  // belong to the picture that was on screen.
  useEffect(() => { pending.current = 0; setTarget(null); }, [itemId]);

  const drain = async () => {
    if (running.current || itemId == null) return;
    running.current = true;
    try {
      while (pending.current !== 0) {
        const dir = pending.current > 0 ? "right" : "left";
        pending.current += pending.current > 0 ? -1 : 1;
        try { await api.rotateItem(itemId, dir); } catch { /* keep draining */ }
        onRotated();
      }
    } finally {
      running.current = false;
    }
  };

  const rotate = (dir: "left" | "right") => {
    if (itemId == null) return;
    setTarget((prev) => (prev ?? rotation) + (dir === "right" ? 90 : -90));
    pending.current += dir === "right" ? 1 : -1;
    void drain();
  };

  return { rotate, css: target === null ? 0 : target - rotation };
}
