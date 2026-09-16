/**
 * A CROP RECTANGLE UNDER A QUARTER TURN.
 *
 * The crop is stored as fractions of the ROTATED picture (`videoedit` takes it
 * on the rotated frame, because the rectangle was drawn on the picture as it
 * was being watched). So turning the picture changes what the same four numbers
 * mean, and a crop left alone across a rotation slides sideways and comes out
 * the wrong shape — which is what "the crop area changes its position and
 * stretches" was.
 *
 * It was CLEARED instead, on the argument that a rectangle drawn on the picture
 * as it was cannot be rotated into one meaning the same thing. It can: a
 * quarter turn is an exact map on normalized coordinates, and it is the one
 * below. Clearing threw away somebody's rectangle to avoid arithmetic worth
 * four lines.
 *
 * Pure, so the cases are stated as tests rather than as prose.
 */
export type CropRect = { x: number; y: number; w: number; h: number };

/** Turn a crop by `deg` (a multiple of 90; anything else is left alone).
 *  Positive is clockwise, matching ffmpeg's `transpose=1` and the editor's
 *  own Rotate right. */
export function rotateCrop(crop: CropRect | null, deg: number): CropRect | null {
  if (!crop) return null;
  // Normalize to one of 0 / 90 / 180 / 270 clockwise.
  const q = ((Math.round(deg / 90) % 4) + 4) % 4;
  const { x, y, w, h } = crop;
  // Clockwise, a point (x, y) of the picture lands at (1 - y, x): the top edge
  // becomes the right one. The rectangle's own width and height swap with it.
  if (q === 1) return { x: 1 - y - h, y: x, w: h, h: w };
  if (q === 2) return { x: 1 - x - w, y: 1 - y - h, w, h };
  if (q === 3) return { x: y, y: 1 - x - w, w: h, h: w };
  return crop;
}
