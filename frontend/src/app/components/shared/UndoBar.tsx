/**
 * "That is gone — here is the way back", pinned under the sidebar's scroll
 * area, directly above the selection bar.
 *
 * It is a plain block in the panel's FOOTER, not a floating overlay. Both were
 * tried: floating (sticky, with a negative bottom margin so it costs the
 * content no height) put it on top of the selection bar the moment the list
 * was short enough not to scroll — sticky only ever pulls an element back INTO
 * view, so with nothing to scroll both bars sat in the flow, and the negative
 * margin is precisely an instruction to let the next thing overlap. Below the
 * scroll area there is nothing to reserve, nothing to lift clear of, and no
 * arrangement of rows that can put the two in the same place.
 *
 * Quieter than the Tags tab's toast (`ActionToast`), deliberately. That one is
 * the accent, portalled to the middle of the window, because deleting a tag
 * takes it off every item in the library and there is nothing else on screen
 * saying so. This undoes one edit to the item you are looking at, next to the
 * list it happened in, where nothing has to shout to be found.
 */
import React from "react";
import { Icon } from "../../../shared/Icon";
import { SELECTION_BAR_H } from "../../../shared/SelectionBar";

/** The SAME height as the selection bar, which is the bar it sits directly
 *  above. Two bars of two heights, stacked, read as one of them being
 *  half-finished — and the difference was nothing but a different padding
 *  chosen in isolation. */
export const UNDO_BAR_H = SELECTION_BAR_H;

export function UndoBar({ label, undone, onToggle, onDismiss, t, style }: {
  label: string;
  undone: boolean;
  onToggle: () => void;
  onDismiss: () => void;
  t: (s: string) => string;
  style?: React.CSSProperties;
}) {
  return (
    <div
      // A control here must never be mistaken for the background: a mousedown
      // that reached the panel would put the selection down on the way to the
      // Undo button.
      onMouseDown={(e) => e.stopPropagation()}
      style={{
        display: "flex", alignItems: "center", gap: 6,
        minHeight: UNDO_BAR_H, boxSizing: "border-box",
        // Vertically the selection bar's padding; the extra on the LEFT is
        // because this bar starts with a sentence where that one starts with
        // a button, and text wants the inset a button already has.
        padding: "6px 7px 6px 9px", borderRadius: "var(--r-4)",
        // The accent tint the selection bar wears when something is picked:
        // this is the one way back from a deletion, and a message the same
        // shade as every surface behind it is one nobody looks at. (The Tags
        // tab's toast goes further and fills with the accent — it speaks for
        // the whole library from the middle of the window; this speaks for one
        // item from beside the list it happened in.)
        // The tint is translucent, and this floats over the rows — so the same
        // blur the selection bar uses, or the list reads straight through the
        // message. Layered over `--panel` for the same reason: on a light row
        // the tint alone is not a surface.
        background: "linear-gradient(var(--accent-dim), var(--accent-dim)), var(--panel)",
        border: "1px solid var(--accent)",
        backdropFilter: "blur(8px)",
        boxShadow: "var(--shadow-2)",
        marginBottom: 6,
        ...style,
      }}
    >
      <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-2)", color: "var(--text-2)",
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {undone ? t("Undone") : label}
      </span>
      <button
        onClick={onToggle}
        title={undone ? t("Do it again") : t("Put it back")}
        style={{
          flex: "0 0 auto", display: "flex", alignItems: "center", gap: 4,
          height: 24, padding: "0 8px", borderRadius: "var(--r-3)", cursor: "pointer",
          // Filled, since the bar itself is now accent-dim: an accent-dim
          // button on an accent-dim bar is not a button.
          border: "1px solid var(--accent)", background: "var(--accent)",
          color: "var(--on-accent)", fontFamily: "inherit", fontSize: "var(--fs-2)",
          fontWeight: 600,
        }}
      >
        <Icon name={undone ? "redo" : "undo"} size={14} />
        {undone ? t("Redo") : t("Undo")}
      </button>
      <span
        role="button"
        onClick={onDismiss}
        title={t("Put this message away")}
        style={{ flex: "0 0 auto", display: "flex", alignItems: "center",
          justifyContent: "center", width: 22, height: 22, borderRadius: "var(--r-2)",
          cursor: "pointer", color: "var(--muted-2)" }}
      >
        <Icon name="close" size={14} />
      </span>
    </div>
  );
}
