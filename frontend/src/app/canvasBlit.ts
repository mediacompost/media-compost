/** WHICH PART OF AN IMAGE-SIZED CANVAS IS ON SCREEN — the pure half of the
 *  editor's zoomed-in drawing.
 *
 *  The editor caches the checker, the picture and the selection veil at the
 *  current zoom, drawn ONCE at the origin and blitted where the picture sits
 *  (`EditorOverlay.redraw`). That cache is the whole picture at the current
 *  scale in device pixels, which is the right shape while the picture is
 *  smaller than the screen and the wrong one the moment it is not: at 16x
 *  over a 4000x3000 page it asks for a 128 000 x 96 000 canvas — past what a
 *  browser will allocate at all, and short of that a multi-gigapixel scaled
 *  draw on every rebuild, i.e. on every pointer move outside a gesture. That
 *  was "the select tool and the brush go slow when zoomed in a lot".
 *
 *  Zoomed in, the cache buys nothing anyway — what is on screen is a small
 *  patch of the source, cheap to draw straight from it — so past `CACHE_MAX`
 *  device pixels the editor draws the VISIBLE patch only, through the mapping
 *  below: whole source pixels, so the blit lands exactly where the cached
 *  picture would have. */

export interface Blit {
  /** Source rectangle, in image pixels (integers, inside the image). */
  sx: number; sy: number; sw: number; sh: number;
  /** Destination rectangle, in viewport (CSS) pixels. */
  dx: number; dy: number; dw: number; dh: number;
}

/** Past this many device pixels the zoomed picture is drawn by visible patch
 *  rather than cached whole — about one 4K screen's worth, well under any
 *  browser's canvas cap, and at least the viewport at any dpr in use. */
export const CACHE_MAX_PX = 4096 * 4096;

/** The blit that draws the part of an `imgW` x `imgH` picture, laid out at
 *  `(ox, oy)` at `scale`, that falls inside a `vpW` x `vpH` viewport — or
 *  null when none of it does. Source bounds are rounded OUTWARD to whole
 *  pixels and the destination follows them, so the drawn patch is the same
 *  pixels the whole picture would have put there. */
export function visibleBlit(
  ox: number, oy: number, scale: number, imgW: number, imgH: number,
  vpW: number, vpH: number,
): Blit | null {
  if (scale <= 0 || imgW <= 0 || imgH <= 0) return null;
  const x0 = Math.max(0, Math.floor((0 - ox) / scale));
  const y0 = Math.max(0, Math.floor((0 - oy) / scale));
  const x1 = Math.min(imgW, Math.ceil((vpW - ox) / scale));
  const y1 = Math.min(imgH, Math.ceil((vpH - oy) / scale));
  if (x1 <= x0 || y1 <= y0) return null;
  return {
    sx: x0, sy: y0, sw: x1 - x0, sh: y1 - y0,
    dx: ox + x0 * scale, dy: oy + y0 * scale,
    dw: (x1 - x0) * scale, dh: (y1 - y0) * scale,
  };
}
