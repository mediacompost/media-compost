/** THE SESSIONS' KEYBOARD — one hook over `sessionKeys.ts`'s rule.
 *
 *  The gates every session had written in its own order, in ONE order:
 *  not open, a key somebody already consumed, a confirm sheet up, the
 *  session's own stand-down (the T field over it, its chooser, its
 *  dialog), a field with focus, then the session's `preface` (the rate
 *  chooser's Enter), then the rule. Escape is the stack's (`useEscape`):
 *  enabled only while the session itself is the thing on top — its chooser
 *  and its dialogs are `Overlay`s with entries of their own, so the session
 *  stands down from the stack while one is up rather than sitting above it.
 */
import { useEffect, useRef } from "react";
import { useEscape } from "../../../shared/useEscape";
import { isTypingTarget } from "../../../shared/typingTarget";
import { pending } from "../../../shared/confirm";
import { useUI } from "../../store";
import { sessionKeyAction, type SessionKeyRule } from "./sessionKeys";

export interface SessionKey extends SessionKeyRule<KeyboardEvent> {
  run: (e: KeyboardEvent) => void;
}

export interface SessionKeysSpec {
  /** The session hears the keyboard. */
  isOpen: () => boolean;
  /** …and answers Escape: open, and nothing of its own (a chooser, a
   *  settings sheet, an editor) over it. */
  escape: boolean;
  /** Something of the session's own is over it (the T field, its chooser,
   *  its confirm sheet): every key is that thing's. */
  standDown?: () => boolean;
  /** Runs before the rule; true means the key was the preface's. */
  preface?: (e: KeyboardEvent) => boolean;
  onEscape: () => void;
  onTab?: () => void;
  undo?: { match: (e: KeyboardEvent) => boolean; run: () => void };
  /** Space — open the preview over what is on screen, or close it. */
  preview?: () => void;
  /** S. */
  skip?: () => void;
  keys: SessionKey[];
  /** Defaults to Quick Look. */
  previewOpen?: () => boolean;
  summaryOpen?: () => boolean;
}

export function useSessionKeys(spec: SessionKeysSpec): void {
  const ref = useRef(spec);
  ref.current = spec;
  useEscape(() => {
    const s = ref.current;
    if (!s.isOpen() || pending() || s.standDown?.()) return;
    s.onEscape();
  }, { enabled: spec.escape });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = ref.current;
      if (!s.isOpen() || e.defaultPrevented || pending() || s.standDown?.()) return;
      if (isTypingTarget(e)) return;
      if (s.preface?.(e)) return;
      const action = sessionKeyAction({
        hasTab: !!s.onTab, undo: s.undo?.match,
        hasPreview: !!s.preview, hasSkip: !!s.skip, keys: s.keys,
      }, e, {
        preview: s.previewOpen?.() ?? useUI.getState().quickLook,
        summary: s.summaryOpen?.() ?? false,
      });
      if (!action) return;
      e.preventDefault();
      switch (action.kind) {
        case "tab": s.onTab?.(); break;
        case "undo": s.undo?.run(); break;
        case "preview": s.preview?.(); break;
        case "skip": s.skip?.(); break;
        case "key": s.keys[action.index].run(e); break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
