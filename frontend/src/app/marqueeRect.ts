/**
 * THE RECTANGLE A MARQUEE DRAG IS ASKING FOR — the whole of it, in one place.
 *
 * Two modifiers change what a drag from A to B means, and they compose, so
 * there are four answers and the point of a function is that they are written
 * down once rather than as nested branches in the pointer handler:
 *
 *   plain            the box runs from the press to the pointer
 *   square           its sides are equal, taking the LARGER of the two
 *                    distances, and it still grows the way the drag went
 *   from the centre   the press is the middle, so it grows both ways
 *   both             a square centred on the press
 *
 * The ellipse style draws inside the same rectangle, so "square" is what makes
 * a circle — there is nothing to say about it separately.
 *
 * WHICH MODIFIER MEANS WHICH IS NOT THIS FUNCTION'S BUSINESS. Shift and Alt
 * each already mean something when they are held at the PRESS (extend the
 * selection, subtract from it), and it is only pressing them AFTER the drag
 * has begun that asks for these shapes — Photoshop's rule, and the caller's,
 * which is the only place that knows what was down when.
 */
export interface MarqueeRect { x: number; y: number; w: number; h: number }

export function marqueeRect(
  anchor: { x: number; y: number },
  at: { x: number; y: number },
  { fromCentre = false, square = false }: { fromCentre?: boolean; square?: boolean } = {},
): MarqueeRect {
  let dx = at.x - anchor.x;
  let dy = at.y - anchor.y;
  if (square) {
    // The LARGER distance, so the box follows the hand rather than being
    // pinned back to whichever axis moved least. A drag straight along one
    // axis has no direction on the other; it takes the positive one, which is
    // what every editor does with that degenerate case.
    const m = Math.max(Math.abs(dx), Math.abs(dy));
    dx = dx < 0 ? -m : m;
    dy = dy < 0 ? -m : m;
  }
  if (fromCentre) {
    const hw = Math.abs(dx), hh = Math.abs(dy);
    return { x: anchor.x - hw, y: anchor.y - hh, w: hw * 2, h: hh * 2 };
  }
  return {
    x: Math.min(anchor.x, anchor.x + dx),
    y: Math.min(anchor.y, anchor.y + dy),
    w: Math.abs(dx),
    h: Math.abs(dy),
  };
}
