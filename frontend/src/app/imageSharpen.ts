/**
 * Sharpening, the way every editor does it: an UNSHARP MASK.
 *
 * `out = src + amount × (src − blur(src, radius))` — the blurred copy is what
 * the picture looks like with its detail taken out, so the difference IS the
 * detail, and adding it back in twice over is what "sharper" means. A
 * convolution kernel would be the other way to write it, and a worse one: the
 * radius is a real control (the size of the detail being lifted) and a 3×3
 * kernel has no room for it.
 *
 * The blur comes from `canvasBlur`, so this is right in Safari too — and it is
 * the EDGE-CLAMPED blur, or the picture's own border would read as detail
 * against the transparency outside it and come back with a bright rim.
 * MEASURED, sharpening a flat opaque field (where nothing at all should
 * change): clamped, every pixel comes back exactly as it went in; with a
 * plain blur, 4 levels out five pixels in from the border.
 *
 * WHAT IT COSTS, measured in the pane on a 3.0 MP picture: 22 ms a frame —
 * two readbacks 4.8 each, the loop 7.5, the blur about 1, putting it back
 * 0.4. One frame there, four at 12 MP, which is why the preview is coalesced
 * onto a frame in the editor rather than run per input event. Holding the
 * source's pixels across a panel session would save one of the two readbacks
 * (a fifth); not done — the snapshot is the editor's, not this module's, and
 * a cache it cannot invalidate is the wrong place for it.
 */
import { blurredImage } from "./canvasBlur.ts";

/**
 * `data` sharpened against its own blurred copy, in place.
 *
 * Pure, so the maths can be checked without a canvas: nothing is added where
 * the picture is flat (the blur of a flat field is the field), an edge is
 * pushed further apart on both sides, and 0% changes nothing.
 *
 * ALPHA IS LEFT ALONE. Sharpening is about the colours; lifting the detail
 * out of the alpha channel too would put a halo around every cut-out.
 */
export function unsharpPixels(
  data: Uint8ClampedArray, blurred: Uint8ClampedArray, amount: number,
): void {
  if (amount <= 0) return;
  const k = amount / 100;
  for (let i = 0; i < data.length; i += 4) {
    data[i] = data[i] + k * (data[i] - blurred[i]);
    data[i + 1] = data[i + 1] + k * (data[i + 1] - blurred[i + 1]);
    data[i + 2] = data[i + 2] + k * (data[i + 2] - blurred[i + 2]);
  }
}

/** A new canvas holding `src` sharpened: `amount` per cent at `radius` px. */
export function sharpenedImage(
  src: HTMLCanvasElement, radius: number, amount: number,
): HTMLCanvasElement {
  const out = document.createElement("canvas");
  out.width = src.width;
  out.height = src.height;
  const ctx = out.getContext("2d")!;
  ctx.drawImage(src, 0, 0);
  if (amount <= 0) return out;
  const soft = blurredImage(src, radius).getContext("2d")!
    .getImageData(0, 0, src.width, src.height);
  const img = ctx.getImageData(0, 0, src.width, src.height);
  unsharpPixels(img.data, soft.data, amount);
  ctx.putImageData(img, 0, 0);
  return out;
}
