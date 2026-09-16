// ONE MENU ROW. Forty rows in menus and pickers were six paddings and
// three radii for one thing: a line in a floating panel that lights under
// the pointer and marks the one that is on. `padding: 6px 9px`, radius 6,
// the plurality's numbers. `RowMenuItem` is this plus its flyout; the
// filter menus, the pickers and the theme menu draw their rows with it
// and put their own content inside.
import React from "react";
import { Icon } from "./Icon";
import { rowBackground } from "./Row";

export interface MenuRowProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  icon?: string;
  /** A tick gutter: drawn when true, held empty when false, absent when undefined. */
  checked?: boolean;
  label?: React.ReactNode;
  hint?: React.ReactNode;
  /** A figure at the right edge. */
  trailing?: React.ReactNode;
  kbd?: string;
  trailingIcon?: string;
  /** The row opens a SUBMENU: a chevron at its end, after the label — the
   *  label and hint are drawn as ever. (It was passed as `children`, which
   *  REPLACES the body, so every row with a submenu — the grid's Find
   *  similar, the Edit / Detect / Generate sections — drew its icon and
   *  chevron and no name at all.) */
  submenu?: boolean;
  danger?: boolean;
  /** The one that is on. */
  active?: boolean;
  disabled?: boolean;
  /** Under the pointer or reached by the keys — the menu's own highlight,
   *  for a panel that tracks it itself; a plain `.hoverable` row otherwise. */
  hi?: boolean;
  title?: string;
  /** The body is drawn from `label`/`hint` unless children are given. */
  children?: React.ReactNode;
  /** Aligns a two-line body to its top. */
  top?: boolean;
}

export const MenuRow = React.forwardRef<HTMLDivElement, MenuRowProps>(function MenuRow(
  { icon, checked, label, hint, trailing, kbd, trailingIcon, submenu, danger, active, disabled, hi,
    top, className, style, children, onClick, ...rest }, ref,
) {
  const fg = disabled ? "var(--muted-3)" : danger ? "var(--danger)" : "var(--text-2)";
  const tracked = hi !== undefined;
  const cls = [tracked ? "" : "hoverable", className ?? ""].filter(Boolean).join(" ") || undefined;
  return (
    <div ref={ref} role="menuitem" aria-disabled={disabled || undefined} className={cls}
         onClick={disabled ? undefined : onClick}
         style={{
           display: "flex", alignItems: top ? "flex-start" : "center", gap: 8,
           padding: "6px 9px", borderRadius: "var(--r-2)", fontSize: "var(--fs-3)",
           cursor: disabled ? "default" : "pointer",
           color: active ? "var(--selected-text)" : fg,
           background: hi && !disabled
             ? (danger ? "var(--danger-dim)" : "var(--panel-2)")
             : rowBackground(active, "transparent"),
           ...style,
         }} {...rest}>
      {checked !== undefined ? (
        // The gutter is held whether the tick is drawn or not, or the label
        // would step left and right as the state changes.
        <Icon name="check" size={16} style={{ visibility: checked ? "visible" : "hidden" }} />
      ) : icon ? (
        <Icon name={icon} size={16} />
      ) : children ? null : (
        <span style={{ width: 16, flex: "0 0 auto" }} />
      )}
      {children ?? (
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ fontWeight: 500 }}>{label}</span>
          {hint && (
            <span style={{ display: "block", marginTop: 2, fontSize: "var(--fs-1)",
                           fontWeight: 400, color: "var(--muted-2)", lineHeight: 1.35 }}>
              {hint}
            </span>
          )}
        </span>
      )}
      {trailing && (
        <span style={{ flex: "0 0 auto", fontSize: "var(--fs-2)", fontVariantNumeric: "tabular-nums",
                       color: active ? "var(--selected-text)" : "var(--muted-2)",
                       opacity: active ? 0.8 : 1 }}>
          {trailing}
        </span>
      )}
      {kbd && (
        <span style={{ flex: "0 0 auto", padding: "1px 7px", borderRadius: "var(--r-1)",
                       border: "1px solid var(--border-strong)",
                       fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted)" }}>
          {kbd}
        </span>
      )}
      {trailingIcon && <Icon name={trailingIcon} size={14} style={{ flex: "0 0 auto", opacity: 0.8 }} />}
      {submenu && (
        <Icon name="chevron_right" size={16}
              style={{ flex: "0 0 auto", color: "var(--muted-2)" }} />
      )}
    </div>
  );
});
