/**
 * Where a wheel zoom turns, and what pan that leaves — the geometry behind
 * `useZoomPan.zoomAt`, kept pure so `zoomPivot.test.ts` can state the rule
 * in cases rather than in prose.
 *
 * The content is CENTRED in the viewport and then panned, so its top-left is
 * `(vp - frame) / 2 + pan`. Everything here is in viewport coordinates, with
 * the origin at the viewport's top-left — which is what a mouse event gives
 * once the viewport's own bounding rect is subtracted.
 *
 * There are only TWO rules, one per function, and both are per axis: what
 * stays put while the picture scales, and how far off centre the picture is
 * allowed to end up. Everything the behaviour is supposed to do falls out of
 * those — zooming an off-centre picture up and down returns it exactly where
 * it was, an edge stops it, and a picture that filled the viewport comes back
 * centred.
 */

/** Half a pixel of slack, so "fits" survives the rounding that laying out a
 *  fractional scale produces. */
const EPS = 1;

export interface ZoomState {
  vp: { w: number; h: number };
  /** The content's displayed size right now. */
  frame: { w: number; h: number };
  pan: { x: number; y: number };
}

export interface Point { x: number; y: number }

/** The content's top-left in viewport coordinates. */
export function contentOrigin(s: ZoomState): Point {
  return {
    x: (s.vp.w - s.frame.w) / 2 + s.pan.x,
    y: (s.vp.h - s.frame.h) / 2 + s.pan.y,
  };
}

/** Is `p` over the content? */
export function overContent(s: ZoomState, p: Point): boolean {
  const o = contentOrigin(s);
  return p.x >= o.x && p.x <= o.x + s.frame.w
      && p.y >= o.y && p.y <= o.y + s.frame.h;
}

/**
 * The point a zoom turns about — decided per AXIS, because the two can be in
 * different situations at once (a wide, short picture overflows the width
 * while its height still fits).
 *
 * **The picture's own centre on an axis where the picture FITS.** Turning
 * about its own centre is the same thing as not moving it: the picture grows
 * where it stands, off centre or not. That is the point — a picture wholly on
 * screen has nothing to zoom *towards*, and one that drifted every time the
 * wheel moved could never be zoomed up and back down to where it was.
 *
 * **The cursor on an axis that OVERFLOWS**, as long as the cursor is over the
 * picture: past that point most of the picture is off screen and pointing at
 * a detail is exactly the gesture. Its own centre when the cursor is not over
 * it, since there is nothing being pointed at — its own centre rather than
 * the viewport's, because panned out to an edge those differ and turning
 * about the viewport's would drag the picture across the screen.
 */
export function zoomPivot(s: ZoomState, cursor: Point | null): Point {
  const o = contentOrigin(s);
  const centre = { x: o.x + s.frame.w / 2, y: o.y + s.frame.h / 2 };
  const at = cursor && overContent(s, cursor) ? cursor : centre;
  return {
    x: s.frame.w <= s.vp.w + EPS ? centre.x : at.x,
    y: s.frame.h <= s.vp.h + EPS ? centre.y : at.y,
  };
}

/**
 * How far off centre the picture may sit on one axis: `|vp - frame| / 2`.
 *
 * ONE expression covers both directions of the same idea — the picture never
 * leaves a gap it does not have to. Smaller than the viewport, that limit is
 * the point at which its far edge reaches the viewport's, so it stays wholly
 * visible; larger, it is the point at which its near edge would come inside,
 * so the viewport stays wholly covered. The two meet at zero: a picture
 * exactly the size of the viewport can only be centred, which is why zooming
 * one that filled the screen back down leaves it centred rather than parked
 * against whichever edge it was last dragged to.
 */
export function panLimit(vp: number, frame: number): number {
  return Math.abs(vp - frame) / 2;
}

/**
 * The pan that keeps `pivot` over the same part of the picture while the
 * picture scales by `ratio` — clamped by `panLimit` ONLY on an axis where
 * the picture, at its new size, FITS.
 *
 * There the clamp is what "it might get shifted to keep as much of it
 * visible as possible" means: growing an off-centre picture holds it still
 * (see `zoomPivot`) until an edge arrives, and from there the edge pushes it;
 * and a picture zoomed back down to fitting comes back wholly on screen.
 *
 * Where the picture OVERFLOWS the clamp is deliberately not applied, and it
 * used to be (owner decision, 2026-09): keeping the viewport covered meant
 * that zooming towards a corner of a magnified picture pinned the picture's
 * edge to the viewport's and slid the detail out from under the pointer —
 * "the image keeps sticking to the edge". Overflowing, the cursor is the
 * pivot and stays exactly the pivot; a gap it opens at the far side is the
 * price, and the drag clamps the viewers keep (`panLimit` both ways, in
 * QuickLook and the session card) put it back on the next drag.
 */
export function panForZoom(s: ZoomState, pivot: Point, ratio: number): Point {
  const o = contentOrigin(s);
  const w2 = s.frame.w * ratio;
  const h2 = s.frame.h * ratio;
  // Where the pivot sits WITHIN the content, as a fraction of it — which is
  // the thing that has to stay put, and needs no separate notion of scale.
  const fx = (pivot.x - o.x) / (s.frame.w || 1);
  const fy = (pivot.y - o.y) / (s.frame.h || 1);
  const x = pivot.x - fx * w2 - (s.vp.w - w2) / 2;
  const y = pivot.y - fy * h2 - (s.vp.h - h2) / 2;
  return {
    x: w2 <= s.vp.w + EPS ? clamp(x, panLimit(s.vp.w, w2)) : x + 0,
    y: h2 <= s.vp.h + EPS ? clamp(y, panLimit(s.vp.h, h2)) : y + 0,
  };
}

/** `+ 0` because clamping a negative value to a zero limit yields -0, which
 *  reads back as 0 everywhere except a strict comparison of the two. */
const clamp = (v: number, limit: number) =>
  Math.max(-limit, Math.min(limit, v)) + 0;
