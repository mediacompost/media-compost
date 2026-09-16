/**
 * A MODAL'S DIM BACKING, and the one rule that makes it safe to click through.
 *
 * The obvious spelling — `onClick={onCancel}` on the backdrop, with the panel
 * stopping propagation — dismisses a dialog on a gesture that never meant to:
 * press inside the panel, drag, release outside it. A `click` is delivered to
 * the nearest common ancestor of the press and the release, which for that
 * gesture IS the backdrop, so the dialog closes. Selecting the text of a field
 * by dragging past the panel's edge is exactly that gesture, and it threw away
 * whatever had been typed.
 *
 * So a dismissal needs BOTH ends on the backdrop: the mousedown arms it, the
 * click spends it. (The target test alone is what the panel's own
 * `stopPropagation` was standing in for, and it is kept because it is the
 * honest half of the pair — a caller need not stop anything.)
 */
import React, { useRef } from "react";

export function useBackdropDismiss(onDismiss: () => void) {
  const armed = useRef(false);
  return {
    onMouseDown: (e: React.MouseEvent) => {
      armed.current = e.target === e.currentTarget;
    },
    onClick: (e: React.MouseEvent) => {
      const both = armed.current && e.target === e.currentTarget;
      armed.current = false;
      if (both) onDismiss();
    },
  };
}
