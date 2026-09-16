/** ESCAPE CLEARS A SELECTION — when nothing else has the key.
 *
 *  A list's picks are the one thing on a page Escape has nothing to do
 *  with while a menu, a dialog or a preview is up (those own the key, on
 *  the escape stack) and the only thing it can mean when nothing is. It
 *  DEFERS to the stack rather than sitting in it: a page may hold several
 *  lists and the key must clear all of them, not the last one mounted. */
import { useEffect, useRef } from "react";
import { escapeDepth } from "./escapeStack";
import { overlayIsOpen } from "./overlayCount";
import { isTypingTarget } from "./typingTarget";

export function useEscapeClears(enabled: boolean, hasPicks: boolean, clear: () => void): void {
  const clearRef = useRef(clear);
  clearRef.current = clear;
  const picksRef = useRef(hasPicks);
  picksRef.current = hasPicks;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (escapeDepth() > 0 || overlayIsOpen() || isTypingTarget(e)) return;
      if (!picksRef.current) return;
      e.preventDefault();
      clearRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
