/** THE INLINE EDIT'S KEYS AND BLUR, once.
 *
 *  Enter commits, Escape cancels, and a blur commits where the field is the
 *  kind that saves on its way out — EXCEPT the blur that Escape itself
 *  causes, which used to commit the text it had just been asked to drop in
 *  half the rename fields (the ones that blurred on Escape) and not the
 *  other half. `cancelled` is the flag; it lives for one blur.
 */
import { useRef } from "react";
import { inlineEditAction } from "./inlineEdit";

export function useInlineEdit<E extends HTMLElement = HTMLInputElement>(opts: {
  commit: () => void;
  cancel: () => void;
  /** A multi-line field: plain Enter is a newline, ⌘/Ctrl+Enter commits. */
  metaEnter?: boolean;
  /** A blur commits (a rename that saves on its way out). Default true. */
  commitOnBlur?: boolean;
  /** Keep every key from the handlers above (a field inside a session or
   *  a dialog whose window listener would otherwise hear it). */
  stop?: boolean;
  /** Enter also takes the focus away, which is how some fields close. */
  blurOnEnter?: boolean;
}): {
  onKeyDown: (e: React.KeyboardEvent<E>) => void;
  onBlur: () => void;
} {
  const { commit, cancel, metaEnter, commitOnBlur = true, stop, blurOnEnter } = opts;
  // Set by Escape (and by an Enter that already committed), read by the
  // blur that follows: neither may commit again.
  const settled = useRef(false);
  return {
    onKeyDown: (e) => {
      if (stop) e.stopPropagation();
      const action = inlineEditAction(e, { metaEnter });
      if (!action) return;
      e.preventDefault();
      if (action === "cancel") {
        if (!stop) e.stopPropagation();
        settled.current = true;
        cancel();
        return;
      }
      settled.current = true;
      commit();
      if (blurOnEnter) (e.currentTarget as HTMLElement).blur();
      // A commit that keeps the field (a save that leaves it open for the
      // next edit) must let a later blur commit again.
      if (!blurOnEnter) settled.current = false;
    },
    onBlur: () => {
      if (settled.current) { settled.current = false; return; }
      if (commitOnBlur) commit();
    },
  };
}
