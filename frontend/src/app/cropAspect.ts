/**
 * LOCKING THE CROP RECTANGLE'S SHAPE.
 *
 * The crop rect is stored as fractions of the picture, so its SHAPE is a fact
 * about pixels rather than about those four numbers: a half-wide, half-tall
 * rect is square only on a square picture. Everything here therefore works in
 * image PIXELS — which is also the frame the crop tool's handle arithmetic
 * already uses (`cropGeomOf` scales by `dims`), so a locked ratio composes
 * with the angle slider for free: the constraint is applied in the rect's own
 * rotated frame, where "wider than tall" still means what it says.
 *
 * The rule everywhere is EXPAND, not clip: a rectangle that has to change to
 * satisfy the ratio grows to the larger of the two implied sizes, so it still
 * reaches the cursor, and a rectangle that then falls outside the picture is
 * SHRUNK about its anchor rather than cut — cutting is what breaks the ratio,
 * and a lock that quietly stops holding at the edge of the picture is worse
 * than no lock.
 *
 * Pure, so the cases are stated as tests rather than as prose.
 */
export type Rect = { x: number; y: number; w: number; h: number }; // fractions 0..1
export type Dims = { w: number; h: number };                       // image pixels
export type Point = { x: number; y: number };
/** Which side of the rect a resize handle moves: -1 / 0 (this axis is not
 *  driven by the handle) / +1. */
export type Sign = -1 | 0 | 1;
/** The picture's own edges, in the rect's local frame (i.e. measured from the
 *  rect's centre). Only meaningful while the crop is un-rotated, which is the
 *  only case the editor clamps in. */
export type Bounds = { minX: number; maxX: number; minY: number; maxY: number };

/** The id of the two options that are not a fixed pair of numbers: the
 *  picture's own shape, and whatever was typed into the two fields. Both are
 *  resolved by `aspectRatio`, which is why neither carries a `ratio`. */
export const ORIGINAL_ID = "original";
export const CUSTOM_ID = "custom";

/** A typed ratio — the two numbers as TEXT, because a field somebody is
 *  halfway through typing has an empty side and a lone "." in it, and a
 *  number cannot hold either. */
export type CustomAspect = { w: string; h: string };

/** The ratios the crop bar offers. `ratio` is width / height in PIXELS; null
 *  is the unconstrained shape, and "original" / "custom" are resolved
 *  against the picture and the typed fields by `aspectRatio` below. */
export const CROP_ASPECTS: { id: string; label: string; ratio: number | null }[] = [
  { id: "free", label: "Free", ratio: null },
  { id: "original", label: "Original", ratio: null },
  { id: "1:1", label: "1:1", ratio: 1 },
  { id: "3:2", label: "3:2", ratio: 3 / 2 },
  { id: "2:3", label: "2:3", ratio: 2 / 3 },
  { id: "4:3", label: "4:3", ratio: 4 / 3 },
  { id: "3:4", label: "3:4", ratio: 3 / 4 },
  { id: "16:9", label: "16:9", ratio: 16 / 9 },
  { id: "9:16", label: "9:16", ratio: 9 / 16 },
  { id: "5:4", label: "5:4", ratio: 5 / 4 },
  { id: "4:5", label: "4:5", ratio: 4 / 5 },
  // LAST, because it is the one entry that answers with a question: picking
  // it reveals the two fields rather than reshaping the crop on the spot.
  { id: CUSTOM_ID, label: "Custom…", ratio: null },
];

/** The ratio two typed fields stand for, or null while they do not name one
 *  — an empty side, a zero, a negative, anything unparseable. Null is what
 *  makes a half-typed "16:" behave as Free rather than as a shape nothing
 *  can satisfy. */
export function customRatio(custom: CustomAspect | undefined): number | null {
  if (!custom) return null;
  const w = Number(custom.w), h = Number(custom.h);
  if (!Number.isFinite(w) || !Number.isFinite(h)) return null;
  if (!(w > 0) || !(h > 0)) return null;
  return w / h;
}

/** The pixel ratio an option stands for, or null for no constraint. An id
 *  nothing recognises is read as "free": a ratio nobody can name must not
 *  quietly reshape a crop. */
export function aspectRatio(id: string, dims: Dims,
                            custom?: CustomAspect): number | null {
  if (id === ORIGINAL_ID) {
    return dims.w > 0 && dims.h > 0 ? dims.w / dims.h : null;
  }
  if (id === CUSTOM_ID) return customRatio(custom);
  const found = CROP_ASPECTS.find((a) => a.id === id);
  return found && found.ratio && found.ratio > 0 ? found.ratio : null;
}

/** Two extents (image pixels) taken out to the ratio: whichever of them
 *  implies the larger rectangle wins, so the shape follows the cursor rather
 *  than retreating from it. */
export function fitExtents(lx: number, ly: number, aspect: number): { lx: number; ly: number } {
  if (!(aspect > 0)) return { lx, ly };
  if (lx >= ly * aspect) return { lx, ly: lx / aspect };
  return { lx: ly * aspect, ly };
}

/**
 * A fresh AXIS-ALIGNED crop drag from `a` to `b` (image pixels) at a locked
 * ratio. The anchor `a` stays put — it is the corner the drag started at —
 * and the rectangle is held inside the picture by shrinking toward it.
 */
export function aspectDragRect(a: Point, b: Point, dims: Dims, aspect: number): Rect {
  const cl = (v: number, hi: number) => Math.min(hi, Math.max(0, v));
  const ax = cl(a.x, dims.w), ay = cl(a.y, dims.h);
  const bx = cl(b.x, dims.w), by = cl(b.y, dims.h);
  const sx = bx >= ax ? 1 : -1, sy = by >= ay ? 1 : -1;
  let { lx, ly } = fitExtents(Math.abs(bx - ax), Math.abs(by - ay), aspect);
  // Room from the anchor in the direction of the drag, so the shrink keeps
  // the ratio where a clip would not.
  const roomX = sx > 0 ? dims.w - ax : ax;
  const roomY = sy > 0 ? dims.h - ay : ay;
  const s = Math.min(1, lx > 0 ? roomX / lx : 1, ly > 0 ? roomY / ly : 1);
  lx *= s; ly *= s;
  const x0 = sx > 0 ? ax : ax - lx;
  const y0 = sy > 0 ? ay : ay - ly;
  return { x: x0 / dims.w, y: y0 / dims.h, w: lx / dims.w, h: ly / dims.h };
}

/**
 * One handle drag, in the rect's OWN (rotated) frame: `hw`/`hh` are the
 * rectangle's half extents as the drag began, `loc` is the cursor in that
 * frame, and the answer is the new extents plus where the rect's centre goes,
 * measured from the old centre.
 *
 * With no ratio this is exactly what the free crop always did — the opposite
 * corner (resp. edge) stays fixed and an edge handle moves one axis only.
 * With one, a corner takes both axes out to the ratio while an EDGE derives
 * the other axis and grows it symmetrically about the rect's own centre line:
 * an edge handle names one edge, so the two the ratio forces it to move are
 * the ones the hand is not on.
 */
export function resizeLocal(
  sx: Sign, sy: Sign, hw: number, hh: number, loc: Point, aspect: number | null,
  bounds?: Bounds,
): { w: number; h: number; midX: number; midY: number } {
  const fixedX = -sx * hw, fixedY = -sy * hh;
  let w = sx === 0 ? hw * 2 : Math.abs(loc.x - fixedX);
  let h = sy === 0 ? hh * 2 : Math.abs(loc.y - fixedY);
  // Which way the moving side lies from the fixed one. Dragged past the fixed
  // side it flips, which is how a crop is turned inside out; a cursor exactly
  // on it keeps the handle's own side.
  let dirX: number = sx === 0 ? 0 : Math.sign(loc.x - fixedX) || sx;
  let dirY: number = sy === 0 ? 0 : Math.sign(loc.y - fixedY) || sy;
  if (aspect && aspect > 0) {
    if (sx === 0) { w = h * aspect; dirX = 0; }
    else if (sy === 0) { h = w / aspect; dirY = 0; }
    else { const f = fitExtents(w, h, aspect); w = f.lx; h = f.ly; }
    if (bounds) {
      // The picture is a wall, not a rail: a locked rect STOPS growing when
      // it reaches an edge, keeping the side the handle is not on. Sliding it
      // back in instead would move the corner the drag is holding fixed.
      const roomX = dirX === 0 ? 2 * Math.min(-bounds.minX, bounds.maxX)
        : dirX > 0 ? bounds.maxX - fixedX : fixedX - bounds.minX;
      const roomY = dirY === 0 ? 2 * Math.min(-bounds.minY, bounds.maxY)
        : dirY > 0 ? bounds.maxY - fixedY : fixedY - bounds.minY;
      // One scale for both axes, or the shrink itself would break the ratio.
      const s = Math.min(1, w > 0 ? roomX / w : 1, h > 0 ? roomY / h : 1);
      if (s < 1) { w *= Math.max(0, s); h *= Math.max(0, s); }
    }
  }
  return {
    w, h,
    midX: dirX === 0 ? 0 : fixedX + (dirX * w) / 2,
    midY: dirY === 0 ? 0 : fixedY + (dirY * h) / 2,
  };
}

/**
 * Hold an axis-aligned rect inside the picture. Without a ratio that is the
 * old clip; with one the rect is SHRUNK about `anchor` (a point in fractions,
 * the rect's centre by default) and then slid back inside, because clipping
 * one edge is exactly the thing a lock promises not to do.
 */
export function clampRect(rect: Rect, aspect: number | null, anchor?: Point): Rect {
  if (!aspect) {
    const x0 = Math.max(0, rect.x), y0 = Math.max(0, rect.y);
    const x1 = Math.min(1, rect.x + rect.w), y1 = Math.min(1, rect.y + rect.h);
    return { x: x0, y: y0, w: Math.max(0, x1 - x0), h: Math.max(0, y1 - y0) };
  }
  let { x, y, w, h } = rect;
  const s = Math.min(1, w > 0 ? 1 / w : 1, h > 0 ? 1 / h : 1);
  if (s < 1) {
    const ax = anchor ? anchor.x : x + w / 2;
    const ay = anchor ? anchor.y : y + h / 2;
    x = ax + (x - ax) * s; y = ay + (y - ay) * s;
    w *= s; h *= s;
  }
  return {
    x: Math.min(Math.max(x, 0), Math.max(0, 1 - w)),
    y: Math.min(Math.max(y, 0), Math.max(0, 1 - h)),
    w, h,
  };
}

/**
 * Reshape an existing rect to the ratio, keeping its centre. It fits INSIDE
 * what is already there rather than growing to it: the old rect was in the
 * picture, so the new one is too, and picking up a ratio never sends the crop
 * off an edge to be clamped back from.
 */
export function fitRectToAspect(rect: Rect, aspect: number | null, dims: Dims): Rect {
  if (!aspect || !(dims.w > 0) || !(dims.h > 0)) return rect;
  const wpx = rect.w * dims.w, hpx = rect.h * dims.h;
  if (!(wpx > 0) || !(hpx > 0)) return rect;
  const lx = Math.min(wpx, hpx * aspect), ly = lx / aspect;
  const cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2;
  const w = lx / dims.w, h = ly / dims.h;
  return clampRect({ x: cx - w / 2, y: cy - h / 2, w, h }, aspect);
}
