/**
 * Deterministic per-tag colors for annotation boxes: the same tag name always
 * maps to the same visually-distinct color, in every session and both windows,
 * so a box's tag is recognizable without reading its label. Pure + unit-tested
 * (`tagColor.test.ts`, run under `node --test`), so keep it free of DOM/React.
 */

export interface TagColor {
  /** Box border / label background. */
  stroke: string;
  /** Box fill (translucent). */
  fill: string;
  /** Readable text color on top of `stroke`. */
  text: string;
}

// FNV-1a over the name → 32-bit hash. Stable across runs (unlike a per-session
// counter) and well-spread, so nearby names don't collapse to the same hue.
function hashName(name: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < name.length; i++) {
    h ^= name.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

// Convert the hash to a hue. Multiplying by the golden-angle fraction spreads
// consecutive hash buckets around the wheel, so similar hashes land far apart.
function hueFor(name: string): number {
  return (hashName(name) * 0.61803398875) % 1 * 360;
}

/**
 * The color for a tag name. Fixed saturation/lightness keep every tag equally
 * legible; only the hue varies. Deterministic: `tagColor(x)` is always equal to
 * `tagColor(x)`.
 */
export function tagColor(name: string): TagColor {
  const h = hueFor(name);
  return {
    stroke: `hsl(${h.toFixed(1)}, 75%, 58%)`,
    fill: `hsla(${h.toFixed(1)}, 75%, 58%, 0.16)`,
    // A dark text sits readably on the mid-lightness stroke color.
    text: `hsl(${h.toFixed(1)}, 80%, 12%)`,
  };
}
