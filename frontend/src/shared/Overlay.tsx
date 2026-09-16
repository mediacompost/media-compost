import React, { useState } from "react";
import { Button } from "./Button";
import { isTypingTarget } from "./typingTarget";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";
import { LAYER } from "./layers";
import { useBackdropDismiss } from "./Backdrop";
import { useEscape } from "./useEscape";
import { useOverlayMount } from "./overlayCount";
import { ConfirmModal } from "./ConfirmModal";

/** What a dialog needs to hand over for its ✕ to ask before throwing work
 *  away. It is ONE optional object rather than three props because the
 *  translator is part of the bargain: shared chrome that produces words takes
 *  a `t` (an optional one with an English fallback is how a component silently
 *  stays untranslated), and requiring one of every Overlay caller for a
 *  feature most of them do not want is the wrong trade. */
export type UnsavedGuard = {
  /** Is there anything to lose? */
  dirty: boolean;
  /** Save and close — the dialog's own Save, so the two cannot differ. */
  onSave: () => void;
  t: (s: string) => string;
};

export { overlayIsOpen } from "./overlayCount";

export function Overlay({
  icon,
  title,
  subtitle,
  width,
  height,
  onClose,
  children,
  footer,
  unsaved,
  onDragOver,
  onDragLeave,
  onDrop,
  error,
  onSubmit,
}: {
  icon: string;
  title: string;
  subtitle?: string;
  width: number;
  /** Fixed panel height (e.g. "88%") — for a dialog whose content expands
   *  and collapses, so the frame holds still. Default: fit the content. */
  height?: number | string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** Pass this and the ✕, the backdrop and Escape ask before discarding. */
  unsaved?: UnsavedGuard;
  // Optional drag handlers wired to the whole backdrop, so the entire window
  // (including the dimmed area around the modal) acts as a drop target.
  onDragOver?: React.DragEventHandler;
  onDragLeave?: React.DragEventHandler;
  onDrop?: React.DragEventHandler;
  /** What went wrong with the last attempt — the footer's left-hand line,
   *  in red, beside the buttons. Nine dialogs drew the same line by hand. */
  error?: string;
  /** Enter on a plain INPUT inside the panel presses the primary — the
   *  rule every dialog with a text field wants and six of them lacked.
   *  A field that takes Enter itself (an autocomplete picking a row)
   *  prevents the default and is left alone; a textarea is never it. */
  onSubmit?: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const submitOnEnter = (e: React.KeyboardEvent) => {
    if (!onSubmit || e.key !== "Enter" || e.defaultPrevented) return;
    if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
    const el = e.target as HTMLElement;
    if (el.tagName !== "INPUT") return;
    const type = (el as HTMLInputElement).type;
    if (type === "checkbox" || type === "radio" || type === "range") return;
    e.preventDefault();
    onSubmit();
  };
  // THE ✕ IS THE GESTURE THAT NEEDS ASKING, and Escape and the backdrop are
  // that same gesture: all three mean "close" and none of them says what to do
  // with what was typed. The footer's CANCEL is deliberately NOT guarded — it
  // is labelled, and a dialog that argued with a button reading "Cancel" would
  // be asking whether you meant the word you just pressed.
  const guarded = () => {
    if (unsaved?.dirty) setAsking(true);
    else onClose();
  };

  const backdrop = useBackdropDismiss(guarded);

  // Counted, so `overlayIsOpen` answers for the dialogs the page's own
  // shortcuts must yield to.
  useOverlayMount();

  // Escape closes the overlay — through the stack, so a preview or a menu
  // opened over this dialog takes the press first, and a field inside it
  // (an autocomplete's list, an inline rename) before either. The handler
  // reads `unsaved.dirty` fresh on every press.
  useEscape(() => guarded());

  // Portalled and FIXED. It used to be `absolute; inset: 0`, which sizes
  // against the nearest positioned ancestor — and the moment the Tags tab's
  // toolbar became sticky (a positioned element), the CSV dialogs opened
  // inside it as a sliver. A modal covers the window; saying so here is one
  // rule instead of every caller having to be mounted somewhere safe.
  return createPortal(
    <div
      // BOTH ENDS ON THE DIM, or it is not a dismissal — see `Backdrop`.
      // Selecting a field's text by dragging past the panel's edge releases
      // out here, and this is the dialog every editor in the app is built
      // on, so that gesture used to throw away whatever had been typed.
      {...backdrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        position: "fixed",
        inset: 0,
        // ABOVE THE ITEM WINDOW (300). A modal is portalled to `document.body`
        // and is therefore the item window's SIBLING, so at 40 every dialog
        // opened from inside the annotator — the place form, the event form,
        // the subject editor — rendered UNDERNEATH it: the button worked, the
        // dialog existed, and the screen did not change. That is what "creating
        // a place in the annotator does nothing" was. Below `AnchoredDropdown`
        // (1000) on purpose: these forms are full of autocompletes, and a
        // dropdown belonging to a field must open OVER its own dialog.
        zIndex: LAYER.modal,
        background: "var(--scrim-3)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          width,
          height,
          // No dialog wants to be wider than the window it is in — the widest
          // ones (import, settings) would otherwise run off both edges on a
          // laptop screen.
          maxWidth: "94vw",
          maxHeight: "88%",
          background: "var(--panel-2)",
          border: "1px solid var(--border-strong)",
          borderRadius: 16,
          boxShadow: "var(--shadow-3)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "18px 20px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            gap: 11,
          }}
        >
          <Icon name={icon} size={22} color="var(--accent)" />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: "var(--fs-5)", fontWeight: 600 }}>{title}</div>
            {subtitle && (
              <div style={{ fontSize: "var(--fs-2)", color: "var(--muted)", marginTop: 2 }}>
                {subtitle}
              </div>
            )}
          </div>
          <span
            onClick={guarded}
            style={{
              width: 30,
              height: 30,
              borderRadius: "var(--r-4)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--muted)",
              cursor: "pointer",
            }}
          >
            <Icon name="close" size={20} />
          </span>
        </div>
        {/* THE BODY IS THE PART THAT SCROLLS, and saying so here is one rule
            rather than one per dialog. The panel is a flex column capped at
            88% of the window, so a body taller than that used to push the
            FOOTER out of the panel — which is where Cancel and the button
            that does the thing are. (The CSV export grew twenty-one column
            rows and lost both.) `minWidth: 0` because a flex item's default
            is `auto`: a wide grid inside — the import's preview — otherwise
            sizes the whole dialog and pushes its own controls off screen. */}
        <div data-overlay-body="" onKeyDown={submitOnEnter}
             style={{ flex: "1 1 auto", minHeight: 0,
                      minWidth: 0,
                      overflowY: "auto", overflowX: "hidden" }}>
          {children}
        </div>
        {footer && (
          <div
            style={{
              padding: "16px 20px",
              borderTop: "1px solid var(--border)",
              display: "flex",
              justifyContent: "flex-end",
              gap: 10,
            }}
          >
            {error && (
              <div style={{ flex: 1, alignSelf: "center", fontSize: "var(--fs-2)",
                            color: "var(--red-text)", textAlign: "left" }}>
                {error}
              </div>
            )}
            {footer}
          </div>
        )}
      </div>
      {asking && unsaved && (
        // Discard / Save / Cancel, over a dialog being closed with something
        // typed in it. Three answers rather than two, because "are you sure?"
        // makes somebody who meant to save press Cancel and then hunt for the
        // button they already had. SAVE is the deliberate one and sits last:
        // the ✕ was pressed by a hand aiming at "get rid of this", and the
        // entry that keeps the work is the one worth pointing at.
        <ConfirmModal
          t={unsaved.t}
          title={unsaved.t("Discard your changes?")}
          body={unsaved.t("Nothing here has been saved yet.")}
          plain={{ label: unsaved.t("Discard"), danger: true }}
          answer={{ label: unsaved.t("Save") }}
          onResult={(r) => {
            setAsking(false);
            if (r === "plain") onClose();
            else if (r === "answer") unsaved.onSave();
          }}
        />
      )}
    </div>,
    document.body,
  );
}

/** The dialog footer's two buttons, as `shared/Button` spells them — kept
 *  under their names for the footers that read as "a ghost and a primary". */
export function GhostButton({ onClick, children, icon }: {
  onClick: () => void;
  children: React.ReactNode;
  icon?: string;
}) {
  return <Button variant="ghost" size="md" icon={icon} onClick={onClick}>{children}</Button>;
}

export function PrimaryButton({ onClick, icon, children, disabled, danger }: {
  onClick: () => void;
  icon: string;
  children: React.ReactNode;
  disabled?: boolean;
  /** The press deletes something with no way back: the danger tint. */
  danger?: boolean;
}) {
  return (
    <Button variant={danger ? "danger" : "primary"} size="md" icon={icon}
            onClick={onClick} disabled={disabled}>
      {children}
    </Button>
  );
}

// The field styles and the label live in `shared/Field.tsx` now; re-exported
// so the dialogs keep their spelling.
export { fieldStyle, FieldLabel } from "./Field";
