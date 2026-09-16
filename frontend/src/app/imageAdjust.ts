/**
 * Brightness / contrast / saturation / hue, the four adjustments every image
 * editor has.
 *
 * The browser can do all four in one `drawImage` through `ctx.filter`, which is
 * what makes a live preview of a full-resolution photo possible at all. But
 * Safari PARSES that property and then ignores it while rendering (the same
 * trap `canvasBlur.ts` documents), so the filter is feature-detected by drawing
 * through it and looking at the result — and there is a pixel loop behind it
 * for where it is a no-op.
 *
 * Both paths apply the four in the SAME order as CSS does, left to right, or
 * the preview and the committed image would not match on Safari.
 */

export interface Adjust {
  /** Percent offsets, 0 = unchanged. Brightness/contrast/saturation are
   *  −100…100; hue is a rotation in degrees, −180…180. */
  brightness: number;
  contrast: number;
  saturation: number;
  hue: number;
}

export const NO_ADJUST: Adjust = {
  brightness: 0, contrast: 0, saturation: 0, hue: 0,
};

export function isIdentity(a: Adjust): boolean {
  return a.brightness === 0 && a.contrast === 0
    && a.saturation === 0 && a.hue === 0;
}

/** The equivalent CSS filter — the fast path, and the definition the pixel
 *  loop below matches. */
export function cssFilter(a: Adjust): string {
  const parts: string[] = [];
  if (a.brightness) parts.push(`brightness(${(100 + a.brightness) / 100})`);
  if (a.contrast) parts.push(`contrast(${(100 + a.contrast) / 100})`);
  if (a.saturation) parts.push(`saturate(${(100 + a.saturation) / 100})`);
  if (a.hue) parts.push(`hue-rotate(${a.hue}deg)`);
  return parts.length ? parts.join(" ") : "none";
}

// Luminance weights — the ones the SVG/CSS saturate and hue-rotate matrices
// are built from, so the fallback lands on the same colours.
const LR = 0.213, LG = 0.715, LB = 0.072;

/**
 * The same four adjustments over premultiplied-free RGBA bytes, in place.
 *
 * Pure, so the maths can be checked without a canvas: `node --test` exercises
 * the identities (nothing set changes nothing, saturation −100 is greyscale,
 * a full turn of hue comes home).
 */
export function adjustPixels(data: Uint8ClampedArray, a: Adjust): void {
  if (isIdentity(a)) return;
  const b = (100 + a.brightness) / 100;
  const c = (100 + a.contrast) / 100;
  const s = (100 + a.saturation) / 100;
  const rad = (a.hue * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);

  // saturate(s) as a 3x3 matrix, then hue-rotate(θ) — composed once here
  // rather than per pixel.
  const sat = [
    LR + (1 - LR) * s, LG - LG * s, LB - LB * s,
    LR - LR * s, LG + (1 - LG) * s, LB - LB * s,
    LR - LR * s, LG - LG * s, LB + (1 - LB) * s,
  ];
  const hue = [
    LR + cos * (1 - LR) + sin * (-LR),
    LG + cos * (-LG) + sin * (-LG),
    LB + cos * (-LB) + sin * (1 - LB),
    LR + cos * (-LR) + sin * 0.143,
    LG + cos * (1 - LG) + sin * 0.140,
    LB + cos * (-LB) + sin * -0.283,
    LR + cos * (-LR) + sin * (-(1 - LR)),
    LG + cos * (-LG) + sin * LG,
    LB + cos * (1 - LB) + sin * LB,
  ];
  // m = hue · sat
  const m = new Array(9);
  for (let r = 0; r < 3; r++) {
    for (let col = 0; col < 3; col++) {
      m[r * 3 + col] = hue[r * 3] * sat[col]
        + hue[r * 3 + 1] * sat[3 + col]
        + hue[r * 3 + 2] * sat[6 + col];
    }
  }

  for (let i = 0; i < data.length; i += 4) {
    // brightness, then contrast — both per channel, in 0..1.
    let R = (data[i] / 255) * b;
    let G = (data[i + 1] / 255) * b;
    let B = (data[i + 2] / 255) * b;
    R = (R - 0.5) * c + 0.5;
    G = (G - 0.5) * c + 0.5;
    B = (B - 0.5) * c + 0.5;
    // then the colour matrix (saturation followed by hue).
    const nr = m[0] * R + m[1] * G + m[2] * B;
    const ng = m[3] * R + m[4] * G + m[5] * B;
    const nb = m[6] * R + m[7] * G + m[8] * B;
    data[i] = nr * 255;
    data[i + 1] = ng * 255;
    data[i + 2] = nb * 255;
    // alpha untouched: none of the four says anything about transparency.
  }
}

/** Whether `ctx.filter` actually renders (see the module comment). */
export function filterWorks(): boolean {
  if (_filterOk === null) _filterOk = probe();
  return _filterOk;
}

let _filterOk: boolean | null = null;

function probe(): boolean {
  try {
    if (typeof document === "undefined") return false;
    const c = document.createElement("canvas");
    c.width = 1; c.height = 1;
    const ctx = c.getContext("2d");
    if (!ctx) return false;
    ctx.fillStyle = "#808080";
    ctx.fillRect(0, 0, 1, 1);
    const before = ctx.getImageData(0, 0, 1, 1).data[0];
    ctx.filter = "brightness(2)";
    ctx.fillStyle = "#808080";
    ctx.fillRect(0, 0, 1, 1);
    return ctx.getImageData(0, 0, 1, 1).data[0] > before + 20;
  } catch {
    return false;
  }
}

/**
 * Draw `src` onto `dst` with the adjustments applied, by whichever route this
 * browser supports.
 */
export function drawAdjusted(
  dst: CanvasRenderingContext2D,
  src: CanvasImageSource,
  w: number, h: number, a: Adjust,
): void {
  if (filterWorks()) {
    dst.save();
    dst.filter = cssFilter(a);
    dst.drawImage(src, 0, 0, w, h);
    dst.restore();
    return;
  }
  dst.drawImage(src, 0, 0, w, h);
  const img = dst.getImageData(0, 0, w, h);
  adjustPixels(img.data, a);
  dst.putImageData(img, 0, 0);
}
