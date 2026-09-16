/** The floating "where is it in the picture" SHELL — portal, placement,
 * viewport clamp — shared by the face preview and the text preview.
 *
 * It was welded into `FaceInPicture.tsx`; the text tab needed the same
 * arithmetic over a different drawer (rectangles and quads, not ellipses),
 * and a third copy of "above where there is room, below otherwise" is how
 * the two drift a pixel apart.
 */
import React from "react";
import { createPortal } from "react-dom";

import { LAYER } from "../../../shared/layers";

/** Floating beside `rect` — for a grid of crops or a row of glyphs, where
 *  the preview has to follow the one under the pointer rather than sit in a
 *  fixed place. `max` is the content's height budget, used to decide which
 *  side has room. */
export function FloatingInPicture({ rect, max = 240, children }: {
  rect: DOMRect | null;
  max?: number;
  children: React.ReactNode;
}) {
  if (!rect || children == null) return null;
  const MARGIN = 8, GAP = 8;
  // Above the anchor where there is room, below it otherwise — the preview
  // is taller than what it hangs off, so it would otherwise cover the row
  // being read.
  const above = rect.top - MARGIN > max + GAP;
  const left = Math.max(
    MARGIN,
    Math.min(rect.left + rect.width / 2 - max / 2,
             window.innerWidth - max - MARGIN)
  );
  return createPortal(
    <div style={{
      position: "fixed", left, zIndex: LAYER.popover, padding: 4,
      borderRadius: "var(--r-6)",
      pointerEvents: "none", background: "var(--surface-float)",
      border: "1px solid var(--border)", boxShadow: "var(--shadow-2)",
      ...(above
        ? { bottom: window.innerHeight - rect.top + GAP }
        : { top: rect.bottom + GAP }),
    }}>
      {children}
    </div>,
    document.body
  );
}
