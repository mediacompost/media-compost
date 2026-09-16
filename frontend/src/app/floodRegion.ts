/**
 * THE WAND AND THE FILL TOOL'S REGION: the run of pixels connected to the seed
 * and near enough its colour, as a 0/1 map. One definition, because the two
 * tools share one gesture — a click seeds the flood, and dragging re-runs it at
 * a tolerance driven by the drag — and a fill that took a different area from
 * the wand's selection would be two tools disagreeing about one word.
 *
 * "Near enough" is per CHANNEL, RGBA against the seed's own colour, at a
 * tolerance of 0–100 spread over a byte. Connectivity is 4-way. Both walks are
 * by RUNS rather than by pixels (Smith's span fill): one stack entry per
 * horizontal run instead of per pixel, which on a large region is an order of
 * magnitude fewer pushes and reads each row straight through.
 *
 * THE FLOOD IS WRITTEN TWICE, AND `floodRegion.test.ts` HOLDS THE TWO EQUAL.
 * A drag re-floods on every frame while the seed and the pixels stand still, so
 * all that changes between frames is one number — which is what makes
 * `seedDistances` worth a pass of its own: how far each pixel is from the
 * seed's colour IS the whole colour test, computed once and then read as a
 * single byte. Measured on a 2 MP page with a large region, that takes a frame
 * from 32 ms to 12, for 9 ms paid once. It is deliberately NOT built for a
 * plain click: the pass is the size of the PICTURE however small the region is,
 * so on a big picture it would make the cheap case — one click, a small blob —
 * several times dearer. Hence the second loop, and hence the test: one rule
 * written twice is a rule that can drift, and an assertion that they answer the
 * same is the only thing that stops it.
 *
 * One loop taking either source was tried and dropped: a single branch inside
 * the innermost test cost 56% of the win (18.3 ms a frame against 11.7).
 */

/** The tolerance a person sets, 0–100, as the per-channel byte difference. */
export function toleranceSteps(tolerance: number): number {
  return Math.round(tolerance * 2.55);
}

/**
 * How far every pixel is from the seed's colour: the LARGEST of the four
 * per-channel differences, which is exactly the test the other flood makes
 * (all four within `tol` ⟺ the largest within `tol`).
 */
export function seedDistances(
  data: Uint8ClampedArray, w: number, h: number, x0: number, y0: number,
): Uint8Array {
  const j0 = (y0 * w + x0) * 4;
  const r0 = data[j0], g0 = data[j0 + 1], b0 = data[j0 + 2], a0 = data[j0 + 3];
  const n = w * h;
  const dist = new Uint8Array(n);
  for (let i = 0, j = 0; i < n; i++, j += 4) {
    let m = data[j] - r0; if (m < 0) m = -m;
    let v = data[j + 1] - g0; if (v < 0) v = -v; if (v > m) m = v;
    v = data[j + 2] - b0; if (v < 0) v = -v; if (v > m) m = v;
    v = data[j + 3] - a0; if (v < 0) v = -v; if (v > m) m = v;
    dist[i] = m;
  }
  return dist;
}

/**
 * The region, reading the picture's own bytes — the path a single CLICK takes,
 * which is why the colour test is a plain function rather than the other one's
 * unrolled arithmetic: it runs once, and legibility is worth more there than
 * the fifth of a frame inlining it saves.
 */
export function floodFromPixels(
  data: Uint8ClampedArray, w: number, h: number,
  x0: number, y0: number, tolerance: number,
): Uint8Array {
  const tol = toleranceSteps(tolerance);
  const j0 = (y0 * w + x0) * 4;
  const r0 = data[j0], g0 = data[j0 + 1], b0 = data[j0 + 2], a0 = data[j0 + 3];
  const near = (i: number): boolean => {
    const j = i * 4;
    return Math.abs(data[j] - r0) <= tol && Math.abs(data[j + 1] - g0) <= tol
      && Math.abs(data[j + 2] - b0) <= tol && Math.abs(data[j + 3] - a0) <= tol;
  };
  const region = new Uint8Array(w * h);
  let stack = new Int32Array(1024);
  let sp = 0;
  const push = (x: number, y: number) => {
    if (sp + 2 > stack.length) { const s = new Int32Array(stack.length * 2); s.set(stack); stack = s; }
    stack[sp++] = x; stack[sp++] = y;
  };
  push(x0, y0);
  while (sp > 0) {
    const y = stack[--sp], x = stack[--sp];
    const row = y * w;
    // A run pushed here may have been swallowed by another before its turn.
    if (region[row + x] || !near(row + x)) continue;
    let xl = x;
    while (xl > 0 && !region[row + xl - 1] && near(row + xl - 1)) xl--;
    let xr = x;
    while (xr < w - 1 && !region[row + xr + 1] && near(row + xr + 1)) xr++;
    region.fill(1, row + xl, row + xr + 1);
    for (let k = 0; k < 2; k++) {
      const ny = k === 0 ? y - 1 : y + 1;
      if (ny < 0 || ny >= h) continue;
      const nrow = ny * w;
      let i = xl;
      while (i <= xr) {
        while (i <= xr && (region[nrow + i] || !near(nrow + i))) i++;
        if (i > xr) break;
        push(i, ny);
        while (i <= xr && !region[nrow + i] && near(nrow + i)) i++;
      }
    }
  }
  return region;
}

/** The same region, read off `seedDistances` — every frame of a drag. */
export function floodFromDistances(
  dist: Uint8Array, w: number, h: number,
  x0: number, y0: number, tolerance: number,
): Uint8Array {
  const tol = toleranceSteps(tolerance);
  const region = new Uint8Array(w * h);
  let stack = new Int32Array(1024);
  let sp = 0;
  const push = (x: number, y: number) => {
    if (sp + 2 > stack.length) { const s = new Int32Array(stack.length * 2); s.set(stack); stack = s; }
    stack[sp++] = x; stack[sp++] = y;
  };
  push(x0, y0);
  while (sp > 0) {
    const y = stack[--sp], x = stack[--sp];
    const row = y * w;
    if (region[row + x] || dist[row + x] > tol) continue;
    let xl = x;
    while (xl > 0 && !region[row + xl - 1] && dist[row + xl - 1] <= tol) xl--;
    let xr = x;
    while (xr < w - 1 && !region[row + xr + 1] && dist[row + xr + 1] <= tol) xr++;
    region.fill(1, row + xl, row + xr + 1);
    for (let k = 0; k < 2; k++) {
      const ny = k === 0 ? y - 1 : y + 1;
      if (ny < 0 || ny >= h) continue;
      const nrow = ny * w;
      let i = xl;
      while (i <= xr) {
        while (i <= xr && (region[nrow + i] || dist[nrow + i] > tol)) i++;
        if (i > xr) break;
        push(i, ny);
        while (i <= xr && !region[nrow + i] && dist[nrow + i] <= tol) i++;
      }
    }
  }
  return region;
}

/**
 * The region as an opaque-white RGBA raster, which is what the selection mask
 * is composed from. Branchless and 32 bits at a time: `-1` is every byte set,
 * so `-region[i]` is white-or-nothing without a test, and nothing has to be
 * cleared first — 5.3 ms a 2 MP frame became 1.6.
 */
export function regionToMask(region: Uint8Array, out: Uint8ClampedArray): void {
  const px = new Uint32Array(out.buffer, out.byteOffset, out.length >> 2);
  for (let i = 0; i < px.length; i++) px[i] = -region[i];
}
