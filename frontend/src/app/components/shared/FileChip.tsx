/**
 * WHICH OF THE ITEM'S FILES THIS WINDOW IS SHOWING — the `#N` chip in the item
 * window's header, and the menu of the others behind it.
 *
 * **The menu is PORTALLED, and that is the whole reason this exists.** Both
 * halves of the window spelled the chip out inline, with the menu as an
 * absolutely-positioned child — which worked until the name and the chip moved
 * into `HeaderActions`, whose lead is `overflow: hidden` so the name can
 * ellipsise. From that moment the menu was clipped to a 24 px chip and there
 * was nothing to see: the button toggled, the menu rendered, and clicking the
 * chip looked like it did nothing at all. Anchoring it to the body
 * (`AnchoredDropdown`) puts it outside every clipping ancestor, which is what
 * that component is for.
 *
 * One component rather than two, for the reason the rest of the shared chrome
 * is shared: this is the same chip in the same header, and the two copies had
 * already drifted (one filtered the list to still pictures, the other guarded
 * the switch against unsaved edits — both of which are now parameters).
 */
import React, { useEffect, useRef, useState } from "react";
import { FileVersion } from "../../api";
import { Icon } from "../../../shared/Icon";
import { AnchoredDropdown, useAnchorRect } from "../../../shared/AnchoredDropdown";
import { useMenuDismiss } from "../../../shared/useMenuDismiss";

/** The line a file shows in the menu: its number, then whatever names it. */
export function fileLabel(f: FileVersion): string {
  return `${f.number != null ? `${f.number} — ` : ""}${f.names[0]?.name
    || (f.edited ? `edited (${f.edit_action || "edit"})` : f.format)}`;
}

export function FileChip({ files, currentId, onPick, t }: {
  /** The files this window can show — the image editor passes only the still
   *  ones, since it has no way to open a film. */
  files: FileVersion[];
  currentId: number | null | undefined;
  /** Picking one that is not already shown. The image editor routes this
   *  through its unsaved-changes prompt. */
  onPick: (id: number) => void;
  /** REQUIRED — an optional translator is a silent-English hole. A
   *  deliberately-English window passes an identity. */
  t: (s: string) => string;
}) {
  const tr = t;
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const rect = useAnchorRect(btn, open);
  const current = files.find((f) => f.id === currentId);

  // Click-away, on the TARGET rather than on propagation: the menu is portalled
  // to the body, so a click on one of its rows is "outside" the chip and would
  // otherwise tear the row out from under the click choosing it (the rule every
  // menu built on `AnchoredDropdown` follows).
  useMenuDismiss(open, () => setOpen(false), { within: [menu, btn] });

  if (!files.length) return null;
  return (
    <>
      <button
        ref={btn}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => setOpen((v) => !v)}
        title={tr("Switch to another file of this item")}
        className="hoverable"
        style={{ display: "flex", alignItems: "center", gap: 3, flex: "0 0 auto",
          height: 24, padding: "0 8px 0 13px", borderRadius: "var(--r-7)", border: "none",
          background: open ? "var(--accent-dim)" : "var(--border-soft)",
          color: "var(--text-3)", fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
          fontWeight: 600, cursor: "pointer" }}
      >
        #{current?.number ?? "?"}
        <Icon name="expand_more" size={13} color="var(--muted)" />
      </button>
      {open && (
        <AnchoredDropdown rect={rect} minWidth={260}>
          <div ref={menu}>
            {files.map((f) => {
              const cur = f.id === currentId;
              return (
                <button
                  key={f.id}
                  className="hoverable"
                  onClick={() => { setOpen(false); if (!cur) onPick(f.id); }}
                  style={{ display: "flex", alignItems: "center", gap: 8,
                    width: "100%", padding: "6px 9px", borderRadius: "var(--r-3)",
                    border: "none", background: "transparent", cursor: "pointer",
                    color: "var(--text-2)", textAlign: "left",
                    fontFamily: "inherit" }}
                >
                  <Icon name={cur ? "radio_button_checked" : "radio_button_unchecked"}
                    size={15} color={cur ? "var(--accent)" : "var(--muted-2)"} />
                  <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-3)", flex: 1,
                    minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap" }}>
                    {fileLabel(f)}
                  </span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                    color: "var(--muted-2)", whiteSpace: "nowrap" }}>
                    {f.width}×{f.height}
                  </span>
                  {f.active && (
                    <span style={{ fontSize: "var(--fs-1)", fontWeight: 700,
                      color: "var(--accent)", textTransform: "uppercase",
                      letterSpacing: "0.04em" }}>{tr("active")}</span>
                  )}
                </button>
              );
            })}
          </div>
        </AnchoredDropdown>
      )}
    </>
  );
}
