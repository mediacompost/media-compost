/**
 * HOW A MENU CLOSES when the press lands elsewhere — the ONE rule.
 *
 * Twenty-six menus each put their own mousedown listener on the window, and
 * they disagreed three ways. Most listened on the BUBBLE phase, which a row
 * handler that stops mousedown on its way up (the Sets tab's press-and-drag
 * selection) hides every press from — those menus simply stayed open there.
 * Some armed the listener a tick late so the click that opened the menu did
 * not close it again; the rest survived only because their trigger fires on
 * `click` while the listener waits for `mousedown`. And ten of them did not
 * answer Escape at all.
 *
 * So: CAPTURE phase, asking the DOM where the press landed rather than
 * relying on nobody stopping it; a press inside an open dropdown's portal
 * (`[data-dropdown]`) or inside any of `within` is not outside; armed a tick
 * late; Escape through the stack (`useEscape`), so a menu opened over a
 * dialog answers before the dialog does; and, where asked, a page scroll or
 * a resize closes it too (a menu anchored to a captured rect drifts away
 * from its row otherwise — but a scroll INSIDE it must not).
 */
import { useEffect, useRef } from "react";
import type { RefObject } from "react";
import { pressedInsideDropdown } from "./AnchoredDropdown";
import { useEscape } from "./useEscape";

export function useMenuDismiss(open: boolean, onClose: () => void, opts: {
  /** Elements whose subtree is "inside": the trigger (a press on it is the
   *  toggle's), a panel that is not portalled. */
  within?: readonly RefObject<HTMLElement | null>[];
  /** Close on a scroll outside the menu — for one anchored to a captured
   *  rect. */
  onScroll?: boolean;
  onResize?: boolean;
} = {}): void {
  const { within = [], onScroll = false, onResize = false } = opts;
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const withinRef = useRef(within);
  withinRef.current = within;
  useEscape(() => closeRef.current(), { enabled: open });
  useEffect(() => {
    if (!open) return;
    const inside = (target: EventTarget | null) =>
      pressedInsideDropdown(target)
      || (target instanceof Node
          && withinRef.current.some((r) => r.current?.contains(target)));
    const onDown = (e: MouseEvent) => { if (!inside(e.target)) closeRef.current(); };
    const onScrolled = (e: Event) => { if (!inside(e.target)) closeRef.current(); };
    const onResized = () => closeRef.current();
    // Deferred: the click that opened the menu is still travelling.
    const id = window.setTimeout(() => {
      window.addEventListener("mousedown", onDown, true);
      if (onScroll) window.addEventListener("scroll", onScrolled, true);
      if (onResize) window.addEventListener("resize", onResized);
    }, 0);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener("mousedown", onDown, true);
      window.removeEventListener("scroll", onScrolled, true);
      window.removeEventListener("resize", onResized);
    };
  }, [open, onScroll, onResize]);
}
