import React, { useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import { LAYER } from "./layers";

/** Did this press land inside an open dropdown's own portal? The test a
 *  menu's outside-click listener makes, since the content is portalled out
 *  of the anchor's subtree. */
export function pressedInsideDropdown(target: EventTarget | null): boolean {
  return target instanceof Element && !!target.closest("[data-dropdown]");
}

/** Track an anchor element's viewport rect while `open`, updating on scroll and
 *  resize so a portalled dropdown stays glued to it (rather than scrolling away
 *  with, or being clipped by, an overflow container). */
export function useAnchorRect(
  ref: React.RefObject<HTMLElement | null>,
  open: boolean
): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null);
  useLayoutEffect(() => {
    if (!open) { setRect(null); return; }
    const update = () => { if (ref.current) setRect(ref.current.getBoundingClientRect()); };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open, ref]);
  return rect;
}

/** Placement for a dropdown anchored to `rect`: prefers below the anchor, flips
 *  above when below is cramped, caps its height to the available space (with
 *  internal scrolling), and keeps it on-screen horizontally. Mirrors the model
 *  menu's placement so every popover behaves the same. */
const GAP = 4, MARGIN = 8;

/** Whether a dropdown on `rect` opens below it (else it flips above). One
 *  rule, exported for a menu whose rows are ordered away from the button. */
export function opensBelow(rect: DOMRect): boolean {
  const vh = window.innerHeight;
  const spaceBelow = vh - rect.bottom - MARGIN;
  const spaceAbove = rect.top - MARGIN;
  return spaceBelow >= 200 || spaceBelow >= spaceAbove;
}

function placement(rect: DOMRect, minWidth: number,
                   raised: boolean, fill: boolean): React.CSSProperties {
  const vw = window.innerWidth, vh = window.innerHeight;
  const spaceBelow = vh - rect.bottom - MARGIN;
  const spaceAbove = rect.top - MARGIN;
  const below = opensBelow(rect);
  const maxHeight = Math.max(120, (below ? spaceBelow : spaceAbove) - GAP);
  const width = Math.max(rect.width, minWidth);
  const left = Math.max(MARGIN, Math.min(rect.left, vw - width - MARGIN));
  return {
    position: "fixed", left, minWidth: width,
    // Capped to the space RIGHT of `left`, not the whole viewport: `left` is
    // clamped for `width`, so content wider than that (a long address, a long
    // tag) used to grow the box straight past the window's right edge.
    maxWidth: vw - left - MARGIN,
    maxHeight,
    // TWO SCROLLBARS, OR ONE. A dropdown whose content is plain rows scrolls
    // here. One whose content SCROLLS ITSELF (the autocompletes' suggest
    // list, which caps itself at about ten rows) must not: with less room
    // below the field than the list wants, the inner box grew to its own cap
    // and the outer scrolled it — an outer bar and an inner bar, on the same
    // list, moving different amounts. `fill` hands the height down instead:
    // this box is the column, the child grows into it, and the one scrollbar
    // is the child's.
    ...(fill ? { display: "flex", flexDirection: "column",
                 overflow: "hidden" as const }
             : { overflowY: "auto" as const }),
    ...(below ? { top: rect.bottom + GAP } : { bottom: vh - rect.top + GAP }),
    // Over the quick tag sheet when asked (`raised`), else the popover layer.
    zIndex: raised ? LAYER.quickTagPopover : LAYER.popover,
    background: "var(--surface-float)", border: "1px solid var(--menu-border)",
    borderRadius: "var(--r-5)", padding: 3, boxShadow: "var(--shadow-3)",
  };
}

/** Portals its children to `document.body`, positioned against `rect` (from
 *  {@link useAnchorRect}). Renders nothing until a rect is available.
 *
 *  **Mousedown is swallowed here, and that is load-bearing.** Every menu built
 *  on this closes itself on a mousedown outside its ANCHOR — and because the
 *  content is portalled to `document.body`, a click on an option is outside
 *  the anchor. Without stopping it, the menu unmounted while that same click
 *  was still travelling to the option, so picking anything silently did
 *  nothing: the filter menu, the ⋯ row menus and the crop menu all had it.
 *  Stopping propagation here fixes the family rather than each of them.
 *  (`preventDefault` alone only spares the anchor input its blur.) */
export function AnchoredDropdown({
  rect, minWidth = 0, raised = false, fill = false, focusable = false, children,
}: {
  rect: DOMRect | null;
  minWidth?: number;
  /** Hangs off a control INSIDE the quick tag overlay, which sits above the
   *  popover layer — so this one goes to `LAYER.quickTagPopover`. */
  raised?: boolean;
  /** The child SCROLLS ITSELF, so this box must not — see `placement`. Pass
   *  it with a child that grows to the column (`TagSuggestList fill`). */
  fill?: boolean;
  /** The content holds a FIELD of its own (a preset's rename), which the
   *  mousedown below would otherwise keep from taking the focus. The stop
   *  stays — it is what keeps the press from closing the menu. */
  focusable?: boolean;
  children: React.ReactNode;
}) {
  if (!rect) return null;
  return createPortal(
    <div
      // MARKED, so a menu's "did that press land outside me" can ask the
      // DOM. The portal puts the content outside the anchor's subtree, so
      // `anchor.contains(target)` is false for the menu's own items — which
      // was survivable only while the close listener ran on the bubble phase
      // and the `stopPropagation` below hid those presses from it. A row
      // that stops mousedown itself (the Sets tab's press-and-drag
      // selection) hid every OTHER press just as effectively, and the menus
      // stopped closing; the listeners moved to the capture phase and ask
      // this instead.
      data-dropdown=""
      onMouseDown={(e) => { if (!focusable) e.preventDefault(); e.stopPropagation(); }}
      style={placement(rect, minWidth, raised, fill)}
    >
      {children}
    </div>,
    document.body
  );
}
