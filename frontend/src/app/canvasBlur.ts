// Gaussian blur for canvases that works everywhere.
//
// The editor's brush softness and blur tool need a gaussian blur of a canvas.
// `CanvasRenderingContext2D.filter` does that for free in Chromium/Firefox,
// but it is a silent no-op in Safari — strokes came out hard at any hardness
// and the blur tool did nothing there. This module feature-detects the filter
// and otherwise runs a 3-pass box blur on the pixels (a standard gaussian
// approximation), premultiplying alpha so soft edges don't fringe.

// Feature-detect `ctx.filter` FUNCTIONALLY: draw a one-pixel dot through a
// blur and check that ink actually spread. Merely reading the property back
// is not enough — Safari parses and stores the filter string (the getter
// returns it) while rendering still ignores it, which made the string
// read-back pass falsely and left brush softness and the blur tool dead
// no-ops on macOS Safari.
const FILTER_OK = (() => {
  try {
    const c = document.createElement("canvas");
    c.width = 9;
    c.height = 9;
    const ctx = c.getContext("2d");
    if (!ctx) return false;
    ctx.filter = "blur(2px)";
    ctx.fillStyle = "#fff";
    ctx.fillRect(4, 4, 1, 1);
    // A real blur spreads alpha ~3px from the dot; a no-op leaves it at 0.
    return ctx.getImageData(1, 4, 1, 1).data[3] > 0;
  } catch {
    return false;
  }
})();

/** Box sizes whose 3 successive passes approximate a gaussian of `sigma`
 *  (the classic boxes-for-gauss derivation). */
function boxesForGauss(sigma: number): [number, number, number] {
  const n = 3;
  const wIdeal = Math.sqrt((12 * sigma * sigma) / n + 1);
  let wl = Math.floor(wIdeal);
  if (wl % 2 === 0) wl--;
  const wu = wl + 2;
  const mIdeal = (12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4);
  const m = Math.round(mIdeal);
  return [0, 1, 2].map((i) => (i < m ? wl : wu)) as [number, number, number];
}

/** One horizontal box-blur pass over premultiplied RGBA float channels. */
function boxBlurH(src: Float32Array, dst: Float32Array, w: number, h: number, r: number) {
  const iarr = 1 / (r + r + 1);
  for (let y = 0; y < h; y++) {
    const row = y * w * 4;
    for (let c = 0; c < 4; c++) {
      let acc = 0;
      const first = src[row + c];
      const last = src[row + (w - 1) * 4 + c];
      for (let x = -r; x <= r; x++) {
        const cx = Math.min(w - 1, Math.max(0, x));
        acc += src[row + cx * 4 + c];
      }
      for (let x = 0; x < w; x++) {
        dst[row + x * 4 + c] = acc * iarr;
        const addX = x + r + 1;
        const subX = x - r;
        acc += (addX < w ? src[row + addX * 4 + c] : last)
             - (subX >= 0 ? src[row + subX * 4 + c] : first);
      }
    }
  }
}

/** One vertical box-blur pass over premultiplied RGBA float channels. */
function boxBlurV(src: Float32Array, dst: Float32Array, w: number, h: number, r: number) {
  const iarr = 1 / (r + r + 1);
  for (let x = 0; x < w; x++) {
    const col = x * 4;
    for (let c = 0; c < 4; c++) {
      let acc = 0;
      const first = src[col + c];
      const last = src[(h - 1) * w * 4 + col + c];
      for (let y = -r; y <= r; y++) {
        const cy = Math.min(h - 1, Math.max(0, y));
        acc += src[cy * w * 4 + col + c];
      }
      for (let y = 0; y < h; y++) {
        dst[y * w * 4 + col + c] = acc * iarr;
        const addY = y + r + 1;
        const subY = y - r;
        acc += (addY < h ? src[addY * w * 4 + col + c] : last)
             - (subY >= 0 ? src[subY * w * 4 + col + c] : first);
      }
    }
  }
}

function blurPixels(image: ImageData, sigma: number): void {
  const { width: w, height: h, data } = image;
  const n = w * h * 4;
  // Premultiply so transparent pixels don't bleed their (arbitrary) RGB into
  // soft edges.
  let a = new Float32Array(n);
  for (let i = 0; i < n; i += 4) {
    const al = data[i + 3] / 255;
    a[i] = data[i] * al;
    a[i + 1] = data[i + 1] * al;
    a[i + 2] = data[i + 2] * al;
    a[i + 3] = data[i + 3];
  }
  let b = new Float32Array(n);
  for (const box of boxesForGauss(sigma)) {
    const r = Math.max(0, (box - 1) / 2);
    boxBlurH(a, b, w, h, r);
    boxBlurV(b, a, w, h, r);
  }
  for (let i = 0; i < n; i += 4) {
    const al = a[i + 3];
    const inv = al > 0.01 ? 255 / al : 0;
    data[i] = Math.min(255, a[i] * inv);
    data[i + 1] = Math.min(255, a[i + 1] * inv);
    data[i + 2] = Math.min(255, a[i + 2] * inv);
    data[i + 3] = Math.min(255, al);
  }
}

// Test hook: force the pixel fallback even where ctx.filter works, so the
// Safari path can be exercised from a Chromium session.
declare global {
  interface Window { __mcForceNoCanvasFilter?: boolean }
}

/** A new canvas containing `src` gaussian-blurred by `radius` (the CSS
 *  `blur(Npx)` sigma). Uses `ctx.filter` where it works, else a 3-pass box
 *  blur of the pixels. */
export function blurredCanvas(src: HTMLCanvasElement, radius: number): HTMLCanvasElement {
  const out = document.createElement("canvas");
  out.width = src.width;
  out.height = src.height;
  const ctx = out.getContext("2d")!;
  if (radius < 0.3) {
    ctx.drawImage(src, 0, 0);
    return out;
  }
  if (FILTER_OK && !window.__mcForceNoCanvasFilter) {
    ctx.filter = `blur(${radius}px)`;
    ctx.drawImage(src, 0, 0);
    ctx.filter = "none";
    return out;
  }
  const sctx = src.getContext("2d")!;
  const img = sctx.getImageData(0, 0, src.width, src.height);
  blurPixels(img, radius);
  ctx.putImageData(img, 0, 0);
  return out;
}
