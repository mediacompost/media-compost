/** WHO OWNS THE ESCAPE KEY when several things listen for it.
 *
 *  Every dialog, menu, popover and preview used to put its own keydown
 *  listener on the window, and which one won depended on the order they had
 *  been registered in and on which propagation trick its author had copied —
 *  plain, capture + stopPropagation, or capture + stopImmediatePropagation.
 *  A preview opened over a dialog closed both with one press; a menu inside a
 *  dialog closed the dialog under it.
 *
 *  This is a STACK: whatever opened last is on top, and Escape goes to the
 *  top entry only. One capture-phase listener on the window, installed on the
 *  first push, so the page's own bubble-phase handlers (the sessions, the
 *  editors' cascades) see the key only when nothing is stacked over them. An
 *  entry that does not want the key while somebody is typing (the default:
 *  a field's own Escape — an autocomplete's list, an inline rename — comes
 *  first) declines it and lets it propagate to the field.
 *
 *  Pure, no React and no imports: `useEscape` (`shared/useEscape.ts`) is
 *  the hook and installs the one window listener; the tests drive
 *  `dispatchEscape` directly. Lives in `shared/` because every
 *  package needs it and the boundary runs that way.
 */
export type EscapeEntry = {
  handler: (e: KeyboardEvent) => void;
  /** Take the key even when a field has focus. */
  overFields: boolean;
};

type EscapeLike = {
  key: string; target: EventTarget | null;
  preventDefault(): void; stopPropagation(): void;
};

const stack: EscapeEntry[] = [];

/** Push an owner; the returned function pops it (idempotent, and it removes
 *  THAT entry wherever it sits, so an unmount out of order is harmless). */
export function pushEscape(entry: EscapeEntry): () => void {
  stack.push(entry);
  let done = false;
  return () => {
    if (done) return;
    done = true;
    const i = stack.lastIndexOf(entry);
    if (i >= 0) stack.splice(i, 1);
  };
}

export function escapeDepth(): number {
  return stack.length;
}

/** Offer an event to the top of the stack. True when it was taken. `typing`
 *  is `isTypingTarget(e)`, answered by the caller: this module imports
 *  nothing, so it loads under node for its tests. */
export function dispatchEscape(e: EscapeLike, typing = false): boolean {
  if (e.key !== "Escape") return false;
  const top = stack[stack.length - 1];
  if (!top) return false;
  if (!top.overFields && typing) return false;
  e.preventDefault();
  e.stopPropagation();
  top.handler(e as KeyboardEvent);
  return true;
}
