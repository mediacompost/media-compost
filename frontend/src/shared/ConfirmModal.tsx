/**
 * THE ONE CONFIRM SHEET.
 *
 * A title, a sentence, Cancel, and one or two answers — the deliberate one
 * drawn filled and last, an optional plain one beside it (Discard beside
 * Save, Close tab beside Close all). It replaced five hand-drawn sheets, the
 * `Overlay`'s own discard prompt, and every `window.confirm` in the app, so
 * that "are you sure?" is asked in one shape, one red, and one language.
 *
 * Two doors: `ask()` / `confirm()` from `./confirm` for an imperative
 * question (the `ConfirmHost` in App draws it), or the component itself for a
 * sheet tied to a component's own state — a body with fields, a busy label
 * that follows a mutation.
 *
 * Portalled at `LAYER.modalConfirm`: above every dialog (a discard prompt is
 * asked OVER the dialog being closed) and the item window. It counts as an
 * open sheet, so the page's shortcuts stand down; it owns Escape through the
 * stack, so it takes the press before whatever it is over; and the backdrop
 * dismisses on both ends, like every dim here.
 */
import React, { useEffect, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { useBackdropDismiss } from "./Backdrop";
import { LAYER } from "./layers";
import { useEscape } from "./useEscape";
import { useOverlayMount } from "./overlayCount";
import { isTypingTarget } from "./typingTarget";
import { useT } from "./i18n";
import { pending, settle, subscribe } from "./confirm";
import type { ConfirmAnswer, ConfirmResult, ConfirmSpec } from "./confirm";

export type { ConfirmAnswer, ConfirmResult, ConfirmSpec } from "./confirm";
export { ask, confirm } from "./confirm";

const BTN: React.CSSProperties = {
  height: 32, padding: "0 14px", borderRadius: "var(--r-4)",
  border: "1px solid var(--border-strong)", background: "transparent",
  color: "var(--text-2)", fontSize: "var(--fs-3)", fontWeight: 600,
  fontFamily: "inherit", cursor: "pointer",
};

export function ConfirmModal({
  title, body, cancel, answer, plain, enter, dismissable = true, onResult, t,
}: Omit<ConfirmSpec, "body"> & {
  body?: React.ReactNode;
  onResult: (r: ConfirmResult) => void;
  t: (s: string) => string;
}) {
  const [busy, setBusy] = useState<ConfirmAnswer | null>(null);
  useOverlayMount();
  const cancelIt = () => { if (dismissable && !busy) onResult(null); };
  const backdrop = useBackdropDismiss(cancelIt);
  useEscape(cancelIt);

  const press = async (which: ConfirmAnswer, r: ConfirmResult) => {
    if (busy || which.disabled) return;
    if (which.run) {
      setBusy(which);
      try {
        await which.run();
      } catch {
        // The caller's own surface says what went wrong; the question stays.
        setBusy(null);
        return;
      }
      setBusy(null);
    }
    onResult(r);
  };

  // Enter presses the deliberate answer — unless it destroys something, or
  // the key is being typed into a field in the body.
  const enterPresses = enter ?? !answer.danger;
  useEffect(() => {
    if (!enterPresses) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || isTypingTarget(e)) return;
      e.preventDefault();
      e.stopPropagation();
      void press(answer, "answer");
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  const drawn = (a: ConfirmAnswer, filled: boolean): React.CSSProperties => ({
    ...BTN,
    ...(a.danger
      ? { border: "1px solid transparent", background: "var(--danger-dim)",
          color: "var(--danger)" }
      : filled
        ? { border: "none", background: "var(--accent)", color: "var(--on-accent)" }
        : {}),
    ...(busy ? { opacity: busy === a ? 1 : 0.5, cursor: "default" }
        : a.disabled ? { opacity: 0.5, cursor: "default" } : {}),
  });

  return createPortal(
    <div {...backdrop}
      style={{ position: "fixed", inset: 0, zIndex: LAYER.modalConfirm,
               background: "var(--scrim-2)", display: "flex",
               alignItems: "center", justifyContent: "center" }}>
      <div role="dialog" aria-modal="true"
        style={{ width: 400, maxWidth: "94vw", background: "var(--surface-float)",
                 border: "1px solid var(--border-strong)", borderRadius: "var(--r-7)",
                 padding: 20, boxShadow: "var(--shadow-3)" }}>
        <div style={{ fontSize: "var(--fs-4)", fontWeight: 600, color: "var(--text-bright)",
                      marginBottom: body ? 6 : 18 }}>
          {title}
        </div>
        {body && (
          <div style={{ fontSize: "var(--fs-3)", color: "var(--muted)", lineHeight: 1.5,
                        marginBottom: 18, whiteSpace: "pre-line" }}>
            {body}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          {dismissable && (
            <button style={BTN} onClick={cancelIt} disabled={!!busy}>
              {cancel ?? t("Cancel")}
            </button>
          )}
          {plain && (
            <button style={drawn(plain, false)} disabled={!!busy || plain.disabled}
                    onClick={() => void press(plain, "plain")}>
              {busy === plain && plain.busy ? plain.busy : plain.label}
            </button>
          )}
          <button style={drawn(answer, true)} disabled={!!busy || answer.disabled}
                  onClick={() => void press(answer, "answer")}>
            {busy === answer && answer.busy ? answer.busy : answer.label}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Draws whatever `ask()` has queued. Mounted ONCE, in App. */
export function ConfirmHost() {
  const p = useSyncExternalStore(subscribe, pending, pending);
  const t = useT();
  if (!p) return null;
  return <ConfirmModal {...p.spec} t={t} onResult={(r) => settle(p, r)} />;
}
