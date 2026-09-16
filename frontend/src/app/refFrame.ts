/** Between the ITEM's reference frame and a FILE's.
 *
 * A box — a tag's, a face's, a text region's — is stored in the item's frame
 * (fractions 0..1 of the original picture), while every window draws one of
 * the item's FILES, which may be a crop of it (`crop_x/y/w/h`). These three
 * are that mapping, and they live here rather than in a window because both
 * the annotator and the image editor need them: two copies of an
 * affine transform are two chances to draw a box a few pixels off from the
 * pixels it names.
 */
import type { FileVersion } from "./api";

export function refToFile(
  b: { x: number | null; y: number | null; w: number | null; h: number | null },
  f: FileVersion | null
) {
  const cx = f?.crop_x ?? 0, cy = f?.crop_y ?? 0, cw = f?.crop_w ?? 1, ch = f?.crop_h ?? 1;
  return {
    x: ((b.x ?? 0) - cx) / (cw || 1),
    y: ((b.y ?? 0) - cy) / (ch || 1),
    w: (b.w ?? 0) / (cw || 1),
    h: (b.h ?? 0) / (ch || 1),
  };
}

/** A text region's QUAD takes the same mapping as its box — a click has to
 *  agree with what is drawn, and slanted text draws its quad. */
export function quadToFile(quad: [number, number][],
                           f: FileVersion | null): [number, number][] {
  const cx = f?.crop_x ?? 0, cy = f?.crop_y ?? 0,
        cw = f?.crop_w ?? 1, ch = f?.crop_h ?? 1;
  return quad.map(([x, y]) => [(x - cx) / (cw || 1), (y - cy) / (ch || 1)]);
}

/** A polygon's vertices, back into the item's frame — the inverse of
 *  `quadToFile`, for saving what was drawn. */
export function pointsToRef(pts: [number, number][],
                            f: FileVersion | null): [number, number][] {
  const cx = f?.crop_x ?? 0, cy = f?.crop_y ?? 0,
        cw = f?.crop_w ?? 1, ch = f?.crop_h ?? 1;
  return pts.map(([x, y]) => [cx + x * (cw || 1), cy + y * (ch || 1)]);
}

/** …and back: a window draws in the active file's frame, while what it
 *  SAVES is in the item's. */
export function fileToRef(
  b: { x: number; y: number; w: number; h: number },
  f: FileVersion | null
) {
  const cx = f?.crop_x ?? 0, cy = f?.crop_y ?? 0, cw = f?.crop_w ?? 1, ch = f?.crop_h ?? 1;
  return {
    x: cx + b.x * (cw || 1),
    y: cy + b.y * (ch || 1),
    w: b.w * (cw || 1),
    h: b.h * (ch || 1),
  };
}
