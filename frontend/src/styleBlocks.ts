/** SOURCE-LEVEL HELPERS FOR THE LAYER RATCHETS — pure string work over a
 *  TSX file, shared by `menuLayers.test.ts` and `backdropDismiss.test.ts`.
 *  Here rather than in either test so the two read the same blocks. */

export interface StyleBlock {
  /** Offset of `style={{` in the source. */
  at: number;
  /** The text between the braces. */
  text: string;
}

/** Every `style={{ … }}` block, brace-matched. */
export function styleBlocks(src: string): StyleBlock[] {
  const out: StyleBlock[] = [];
  let i = 0;
  for (;;) {
    const at = src.indexOf("style={{", i);
    if (at < 0) break;
    let depth = 0, j = at + "style={".length;
    for (; j < src.length; j++) {
      if (src[j] === "{") depth++;
      else if (src[j] === "}" && --depth === 0) break;
    }
    out.push({ at, text: src.slice(at + "style={{".length, j) });
    i = j;
  }
  return out;
}

/** A full-window sheet: fixed or absolute, `inset: 0`. */
export function coversWindow(block: string): boolean {
  return /position:\s*"(?:fixed|absolute)"/.test(block) && /\binset:\s*0\b/.test(block);
}

/** …painted dim: a scrim token. (A translucent black spelled out was the
 *  old form; `colorLiterals.test` keeps every one of those on a token now.
 *  Quick Look's `--preview-backdrop` follows the theme and is not counted,
 *  as it never was: its arrows and its stack of two layers are its own.) */
export const DIM = /background:\s*"var\(--scrim-[1-4]\)"/;

/** The JSX opening tag a `style={{` sits in — from its `<` to the `>` that
 *  closes the tag (or the `/>`). Empty where the style is not in a tag (a
 *  `const x: React.CSSProperties = {…}` is `= {`, not `style={{`). */
export function openingTag(src: string, at: number): string {
  // Back to the tag's `<`: the last one with no `>` between it and `at`.
  let lt = src.lastIndexOf("<", at);
  while (lt >= 0 && src.slice(lt, at).includes(">")) lt = src.lastIndexOf("<", lt - 1);
  if (lt < 0) return "";
  // Forward to the tag's end, skipping braces.
  let depth = 0, j = at;
  for (; j < src.length; j++) {
    const c = src[j];
    if (c === "{") depth++;
    else if (c === "}") depth--;
    else if (c === ">" && depth === 0) break;
  }
  return src.slice(lt, j + 1);
}
