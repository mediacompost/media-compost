// What just happened, and the way back — at the bottom of the window rather
// than in the toolbar.
//
// The Tags tab's Undo used to take the Delete button's place: the button you
// had just pressed became a different button, so the toolbar said something
// different depending on a thing that had already finished. A toast says it
// where a message belongs, leaves every control where it was, and can be put
// away with its own ✕.
//
// It is NOT self-dismissing BY DEFAULT. The way back from a deletion is
// worth more than the corner of the screen it occupies, and a countdown makes
// somebody read fast rather than think. A notice with NO way back — "3 tags
// added", "1 pair queued" — passes `autoDismissMs` and goes away by itself;
// nine call sites each ran that timer in an effect of their own, and three
// of the sessions drew a toast of their own to put it in.
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Icon } from "../../../shared/Icon";
import { LAYER } from "../../../shared/layers";

export function ActionToast({ text, actionLabel, actionTitle, icon, dismissTitle,
                              extra, onAction, onDismiss, autoDismissMs }: {
  text: string;
  /** The way back. Omitted for a notice that is only information. */
  actionLabel?: string;
  actionTitle?: string;
  icon?: string;
  /** Goes away by itself after this long — for a notice with no way back. */
  autoDismissMs?: number;
  /** ONE FURTHER THING THE ACTION COULD BE, offered beside the way back and
   *  quieter than it — outlined where that one is filled, since undo is what
   *  this message exists for and two equal buttons make a choice out of
   *  something that should read as an aside. */
  extra?: { label: string; icon: string; onClick: () => void };
  // Every word here is the caller's, translated there — this component owns
  // no strings of its own.
  dismissTitle?: string;
  onAction?: () => void;
  onDismiss?: () => void;
}) {
  // The callback rides in a ref: every host writes it inline, and a timer
  // that re-armed on each render of a session that renders per keypress
  // would never fire.
  const dismissRef = useRef(onDismiss);
  dismissRef.current = onDismiss;
  useEffect(() => {
    if (autoDismissMs == null) return;
    const id = window.setTimeout(() => dismissRef.current?.(), autoDismissMs);
    return () => window.clearTimeout(id);
  }, [text, autoDismissMs]);
  return createPortal(
    <div
      style={{
        position: "fixed", left: "50%", bottom: 24, transform: "translateX(-50%)",
        zIndex: LAYER.toast, display: "flex", alignItems: "center", gap: 12,
        padding: "10px 12px 10px 16px", borderRadius: "var(--r-7)",
        // The accent, not the panel colour: a message the same shade as every
        // surface behind it is one nobody looks at, and this one is the only
        // way back from a deletion.
        background: "var(--accent)", border: "1px solid var(--accent)",
        boxShadow: "var(--shadow-2)", maxWidth: "min(90vw, 640px)",
      }}
    >
      <span style={{ fontSize: "var(--fs-4)", color: "var(--on-accent)", whiteSpace: "nowrap",
                     overflow: "hidden", textOverflow: "ellipsis" }}>
        {text}
      </span>
      {extra && (
        <button
          onClick={extra.onClick}
          style={{
            display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
            padding: "5px 10px", borderRadius: "var(--r-4)", fontSize: "var(--fs-4)", fontWeight: 600,
            background: "transparent", color: "var(--on-accent)",
            border: "1px solid var(--on-accent)",
          }}
        >
          <Icon name={extra.icon} size={16} /> {extra.label}
        </button>
      )}
      {actionLabel && (
      <button
        onClick={onAction}
        title={actionTitle}
        style={{
          display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
          padding: "5px 10px", borderRadius: "var(--r-4)", fontSize: "var(--fs-4)", fontWeight: 600,
          background: "var(--on-accent)", color: "var(--accent)",
          border: "1px solid var(--on-accent)",
        }}
      >
        {icon && <Icon name={icon} size={16} />} {actionLabel}
      </button>
      )}
      {onDismiss && (
      <button
        onClick={onDismiss}
        title={dismissTitle}
        style={{
          display: "flex", alignItems: "center", cursor: "pointer",
          padding: 4, borderRadius: "var(--r-2)", border: "none",
          background: "transparent", color: "var(--on-accent)", opacity: 0.75,
        }}
      >
        <Icon name="close" size={16} />
      </button>
      )}
    </div>,
    document.body,
  );
}
