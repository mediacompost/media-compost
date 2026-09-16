import { useEffect, useRef } from "react";
import { dispatchEscape, pushEscape } from "./escapeStack";
import { isTypingTarget } from "./typingTarget";

let installed = false;
/** The ONE capture-phase listener, installed on the first owner. */
function install(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("keydown", (e) => { dispatchEscape(e, isTypingTarget(e)); }, true);
}

/** Own the Escape key while `enabled` — pushed onto the stack on enable,
 *  popped on disable or unmount, so what opened last answers first. The
 *  handler rides in a ref: it may read state that changes every render (a
 *  dialog's `dirty`) without re-registering. */
export function useEscape(handler: (e: KeyboardEvent) => void,
                          opts: { enabled?: boolean; overFields?: boolean } = {}): void {
  const { enabled = true, overFields = false } = opts;
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!enabled) return;
    install();
    return pushEscape({ handler: (e) => ref.current(e), overFields });
  }, [enabled, overFields]);
}
