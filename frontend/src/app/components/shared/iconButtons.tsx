import React from "react";
import { Icon } from "../../../shared/Icon";
import { IconButton, iconButtonStyle } from "../../../shared/IconButton";

/**
 * Small chrome buttons shared by the image editor and the tag annotator, so the
 * two windows keep an identical look. Moved verbatim out of `EditorOverlay.tsx`.
 */

export function LabelBtn({ icon, label, title, onClick, disabled }: {
  icon: string; label: string; title: string; onClick: () => void; disabled?: boolean;
}) {
  return (
    <button title={title} onClick={onClick} disabled={disabled} className={disabled ? undefined : "hoverable"} style={{ display: "flex", alignItems: "center", gap: 5, height: 32, padding: "0 10px", borderRadius: "var(--r-4)", border: "none", background: "transparent", color: disabled ? "var(--muted-3)" : "var(--text-2)", cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.5 : 1, fontSize: "var(--fs-3)", fontWeight: 600 }}>
      <Icon name={icon} size={17} />
      {label}
    </button>
  );
}

/** The editors' bordered glyph button: `shared/IconButton`, bordered. */
export function IconBtn({ icon, title, onClick, small, disabled }: {
  icon: string; title: string; onClick: () => void; small?: boolean; disabled?: boolean;
}) {
  return <IconButton icon={icon} title={title} onClick={onClick} disabled={disabled}
                     size={small ? 28 : 32} tone="text" bordered />;
}

/** The bordered 32 px square every one of the item window's chrome buttons is:
 *  the ⋯, the theme menu, and whatever else sits at the ends of the header —
 *  as a STYLE, for the two menus that draw their trigger from one. The
 *  recipe is `shared/IconButton`'s, so the two cannot drift. */
export const CHROME_BTN: React.CSSProperties =
  iconButtonStyle({ size: 32, bordered: true, tone: "text" });

/** The hairline between two groups of header controls. */
export function Divider() {
  return <div style={{ width: 1, height: 22, background: "var(--border)", margin: "0 4px", flex: "0 0 auto" }} />;
}

/**
 * The window's own ✕, at the far right of the header.
 *
 * It used to be argued against: the tab strip was always shown, so every tab
 * already carried a ✕, and a second bigger one beside them was two crosses in
 * one window meaning two different things. That argument died with the strip —
 * a window on ONE item no longer shows it, so without this there is no visible
 * way out at all and Escape is the only one, which nothing says.
 *
 * It carries NO divider on its left. A divider separates groups that do
 * different things, and this is the last control in the row rather than the
 * start of a group; the rule it would be drawing is one the window's edge
 * already draws.
 */
export function WindowCloseBtn({ onClose, t }: {
  onClose: () => void;
  /** REQUIRED so a caller cannot silently render English by forgetting it —
   *  the annotator's chrome shipped untranslated exactly that way once. A
   *  window that WANTS English (the image editor) passes an identity. */
  t: (s: string) => string;
}) {
  return (
    <IconButton icon="close" size={32} tone="text" bordered onClick={onClose}
                title={t("Close this window")} />
  );
}
