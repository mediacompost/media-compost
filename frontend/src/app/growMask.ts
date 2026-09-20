/**
 * GROW OR SHRINK A MASK BY WHOLE PIXELS — the editor's Grow / Shrink
 * selection, and the wand's Grow field.
 *
 * One round is a dilation (the union of the eight shifts, the original kept)
 * or an erosion (their intersection), which grows or shrinks by that round's
 * step in the Chebyshev sense — a square neighbourhood, the same construction
 * the marching-ants outline uses for its one-pixel ring.
 *
 * Rounds COMPOSE, which is what makes `amount` affordable: dilation is
 * associative, so N rounds are one dilation by the sum of their elements, and
 * the steps can grow geometrically instead of going one pixel at a time (see
 * `growSteps`). It runs inside the wand's gesture, which re-floods the whole
 * picture on every frame of a tolerance drag.
 */

/** The eight neighbours. The identity is not in here: a dilation round draws
 *  these ON TOP of the mask, which already holds it. */
const MASK_SHIFTS = [[1, 0], [-1, 0], [0, 1], [0, -1],
                     [1, 1], [1, -1], [-1, 1], [-1, -1]] as const;

/**
 * The steps of the rounds that grow by exactly `n` pixels.
 *
 * A ROUND'S STEP IS BOUNDED BY WHAT HAS BEEN GROWN ALREADY. Shifting a shape
 * of radius `r` by `s` leaves what it covers CONNECTED only while `s <= 2r + 1`
 * — past that the copies land clear of each other and of the original, and
 * what comes back is not a bigger shape but several spaced ones. So the step
 * can at most triple the radius (`r -> 3r + 1`), and the schedule is
 * 1, 3, 9, 27, … with the last step cut to land on `n` exactly: seven rounds
 * cover 500 px where one round per pixel wants five hundred.
 *
 * IT USED TO BE THE BITS OF `n` — one round per set bit, at that bit's
 * offset — on the reasoning that squares compose and 8 + 32 is 40. They do
 * compose, but only in that order and only within the bound above: a round at
 * offset 8 applied to a ONE-PIXEL find is nine pixels eight apart, and the
 * round at 32 then makes eighty-one. That is the "wand selects a grid of
 * dots like a dice face" bug, and it hit any find smaller than the lowest set
 * bit — which for a wand on a photograph is any speckle it picks up. A grow
 * of 1 or 3 was fine, 2, 4, 8, 16 … were pure lattices, and 5, 6, 40 … were
 * lattices of little blocks.
 */
export function growSteps(n: number): number[] {
  const steps: number[] = [];
  let r = 0;
  while (r < n) {
    const s = Math.min(n - r, 2 * r + 1);
    steps.push(s);
    r += s;
  }
  return steps;
}

/**
 * Grow (`amount > 0`) or shrink (`amount < 0`) `mask` in place, by whole
 * pixels.
 *
 * Alpha is carried rather than thresholded (`destination-in` multiplies it),
 * so a soft-edged selection stays soft. The canvas edge is OUTSIDE the mask:
 * shifting brings transparency in, so a shrink eats in from the picture's own
 * border as it does from any other edge.
 */
export function growMaskBy(mask: HTMLCanvasElement, amount: number): void {
  const n = Math.abs(Math.round(amount));
  if (!n) return;
  const w = mask.width, h = mask.height;
  const mctx = mask.getContext("2d")!;
  const tmp = document.createElement("canvas");
  tmp.width = w; tmp.height = h;
  const tctx = tmp.getContext("2d")!;
  for (const step of growSteps(n)) {
    tctx.clearRect(0, 0, w, h);
    tctx.drawImage(mask, 0, 0);
    if (amount > 0) {
      for (const [dx, dy] of MASK_SHIFTS) mctx.drawImage(tmp, dx * step, dy * step);
    } else {
      mctx.save();
      mctx.globalCompositeOperation = "destination-in";
      for (const [dx, dy] of MASK_SHIFTS) mctx.drawImage(tmp, dx * step, dy * step);
      mctx.restore();
    }
  }
}
