import type React from "react";

/**
 * Transparency checkerboard shared by the image editor's canvas and the tag
 * annotator's image frame, so the two windows show the same pattern under a
 * transparent image. The editor paints it into a canvas pattern; the annotator
 * (which shows an `<img>`, not a canvas) uses `checkerCss` as a CSS background
 * on its scaled frame div while the viewport around it stays a solid color.
 */

// Checker cell size in CSS/canvas pixels (one light + one dark square span two
// cells; the conic gradient below repeats every `CHECKER_CELL` px).
export const CHECKER_CELL = 22;

// Canvas checkerboard pattern for the *image area only* (transparency shows
// through it; the canvas around the image keeps a solid background). Rebuilt
// when the theme's checker colors change.
let _checkerCache: { key: string; pattern: CanvasPattern } | null = null;
export function checkerPattern(ctx: CanvasRenderingContext2D, a: string, b: string): CanvasPattern {
  const key = `${a}|${b}`;
  if (_checkerCache?.key === key) return _checkerCache.pattern;
  const half = CHECKER_CELL / 2;
  const c = document.createElement("canvas");
  c.width = CHECKER_CELL; c.height = CHECKER_CELL;
  const cc = c.getContext("2d")!;
  cc.fillStyle = a; cc.fillRect(0, 0, CHECKER_CELL, CHECKER_CELL);
  cc.fillStyle = b; cc.fillRect(0, 0, half, half); cc.fillRect(half, half, half, half);
  const pattern = ctx.createPattern(c, "repeat")!;
  _checkerCache = { key, pattern };
  return pattern;
}

// CSS background matching `checkerPattern`, using the editor checker theme vars.
// Applied to the annotator's frame div so transparency checkers only within the
// image's bounds.
export const checkerCss: React.CSSProperties = {
  background: `repeating-conic-gradient(var(--editor-checker-a) 0% 25%, var(--editor-checker-b) 0% 50%) 50% / ${CHECKER_CELL}px ${CHECKER_CELL}px`,
};
