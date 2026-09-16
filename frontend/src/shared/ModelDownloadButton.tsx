import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";
import { formatNumber } from "./i18nCore";
import { LAYER } from "./layers";
import { useMenuDismiss } from "./useMenuDismiss";

/** "3.2 GB" / "480 MB" — the scale a download is actually discussed in.
 *  The optional locale localizes the decimal separator ("3,2 GB"). */
export function downloadSize(bytes: number, locale?: string): string {
  if (bytes >= 1e9) {
    const gb = bytes / 1e9;
    const digits = bytes < 1e10 ? 1 : 0;
    const body = locale
      ? formatNumber(locale, gb, { minimumFractionDigits: digits,
          maximumFractionDigits: digits, useGrouping: false })
      : gb.toFixed(digits);
    return `${body} GB`;
  }
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

/** How far along a running download is, in the terms the terminal uses:
 *  "3.2 GB of 7.1 GB". Empty when the total isn't known (the size lookup can
 *  fail), in which case the percentage is all there is. Translated through
 *  the whole-sentence key so "of" does not stay English word order. */
export function downloadDetail(
  done: number | undefined, total: number | undefined,
  t: (s: string, vars?: Record<string, string | number>) => string,
  locale?: string,
): string {
  if (!total || total <= 0) return "";
  return t("{done} of {total}", {
    done: downloadSize(done ?? 0, locale), total: downloadSize(total, locale),
  });
}

/** One entry in a split button's menu — an action, or a plain note line. */
export type SplitMenuItem =
  | { label: string; icon: string; onClick: () => void; danger?: boolean }
  | { note: string };

/** The colour of the button as a whole: the main part and the chevron always
 *  match, and the divider between them follows from the background. */
export type SplitTone = { bg: string; color: string };

/** Shared style for the main (left) part, so a caller's label, spinner or
 *  status text lines up with every other model button in the app. */
export const splitMainStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
  height: 30, padding: "0 12px", border: "none", background: "transparent",
  fontWeight: 600, fontSize: "var(--fs-3)", whiteSpace: "nowrap", fontFamily: "inherit",
};

/**
 * The model download control: a framed split button whose left half is the
 * primary action (download / progress / status) and whose right half opens a
 * menu with everything secondary — cancelling, deleting what is on disk, and
 * so on.
 *
 * It lives here rather than in either page because the Settings models page
 * and the Train tab's Models page must not merely resemble each other; sharing
 * the control is what keeps them identical as either one changes.
 */
export function SplitDownloadButton({
  main, tone, items, flex, marginLeft = 0, menuWidth = 190,
}: {
  /** The left half — a button, or a static status span. */
  main: React.ReactNode;
  tone: SplitTone;
  /** Menu entries; falsy ones are skipped so callers can inline conditions. */
  items: (SplitMenuItem | false | null | undefined)[];
  /** Flex of the whole control (a filling path field wants 1). */
  flex?: React.CSSProperties["flex"];
  marginLeft?: number;
  menuWidth?: number;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const entries = items.filter(Boolean) as SplitMenuItem[];

  useMenuDismiss(open, () => setOpen(false), { within: [rootRef], onResize: true });

  // Position the (portalled) menu at the button, flipping above when it would
  // overflow the viewport bottom, so it is never clipped by a scroll container.
  const toggle = () => {
    if (open) { setOpen(false); return; }
    const r = rootRef.current?.getBoundingClientRect();
    if (r) {
      const menuH = 32 * entries.length + 12;
      const top = window.innerHeight - r.bottom < menuH ? r.top - menuH - 4 : r.bottom + 4;
      setPos({ top, right: window.innerWidth - r.right });
    }
    setOpen(true);
  };

  const divider = tone.bg === "var(--accent)" ? "var(--on-scrim-4)" : "var(--border-strong)";

  return (
    <div ref={rootRef} style={{ position: "relative", display: "flex", flex: flex ?? "0 0 auto", marginLeft }}>
      <div style={{
        display: "flex", flex: 1, border: "1px solid var(--border-strong)",
        borderRadius: "var(--r-4)", overflow: "hidden", background: "var(--bg)",
      }}>
        {main}
        {/* No chevron when there is nothing behind it — a model with neither
            weights on disk nor a download in flight has no secondary action. */}
        {entries.length > 0 && <>
          <div style={{ width: 1, background: divider }} />
          <button
            onClick={toggle}
            title="More"
            style={{
              width: 26, border: "none", background: tone.bg, color: tone.color,
              cursor: "pointer", display: "flex", alignItems: "center",
              justifyContent: "center", flex: "0 0 auto",
            }}
          >
            <Icon name="expand_more" size={16} />
          </button>
        </>}
      </div>
      {open && pos && createPortal(
        // Rendered to <body> with fixed position so it isn't clipped by the
        // page's scroll container and can overflow its bounds.
        //
        // 1000, the layer `AnchoredDropdown` — every other portalled menu —
        // has always used. Portalling to <body> makes this a SIBLING of any
        // open dialog, so the number is the only thing keeping it in front:
        // at the 200 it carried, the menu opened underneath the Settings
        // overlay (500), which is present, positioned and hit-testable while
        // being completely invisible. That is the whole of "the chevron no
        // longer opens its menu" — it opened it every time. The Train tab's
        // Models page is not inside a dialog, which is why the same control
        // went on working there.
        <div
          onMouseDown={(e) => e.stopPropagation()}
          style={{
            position: "fixed", top: pos.top, right: pos.right, minWidth: menuWidth,
            zIndex: LAYER.popover, background: "var(--surface-float)",
            border: "1px solid var(--menu-border)", borderRadius: "var(--r-5)", padding: 4,
            boxShadow: "var(--shadow-3)",
          }}
        >
          {entries.map((it, i) => "note" in it ? (
            <div key={i} style={{ padding: "3px 10px 4px 34px", fontSize: "var(--fs-2)", color: "var(--muted)" }}>
              {it.note}
            </div>
          ) : (
            <div
              key={i}
              className="hoverable"
              onClick={() => { setOpen(false); it.onClick(); }}
              style={{
                display: "flex", alignItems: "center", gap: 8, padding: "7px 10px",
                borderRadius: "var(--r-2)", cursor: "pointer", fontSize: "var(--fs-3)",
                color: it.danger ? "var(--red-text)" : "var(--text-2)",
              }}
            >
              <Icon name={it.icon} size={15} /> {it.label}
            </div>
          ))}
        </div>,
        document.body,
      )}
    </div>
  );
}
