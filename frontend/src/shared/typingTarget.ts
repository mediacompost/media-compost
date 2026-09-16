/**
 * "Is this key being typed into a field?" — the ONE answer.
 *
 * Every window-level shortcut has to stand down while somebody is typing,
 * and seventeen handlers each spelled the test out by hand: nine of them
 * forgot `SELECT`, so W stood down over a focused dropdown and ⌘A on the
 * same grid did not, and two sessions had no test at all and relied on one
 * field remembering to stop propagation. One predicate, read from the
 * event's own target first (a listener on the window sees the element the
 * key went to; `activeElement` is the fallback for a synthetic call).
 * Guarded for a DOM-less run: the escape stack's tests call it under node.
 */
export function isTypingTarget(e: { target: EventTarget | null }): boolean {
  const el = (typeof HTMLElement !== "undefined" && e.target instanceof HTMLElement)
    ? e.target
    : (typeof document !== "undefined" ? document.activeElement : null) as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}
