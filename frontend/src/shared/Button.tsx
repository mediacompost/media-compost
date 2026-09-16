// ONE TEXT BUTTON. Sixty-odd `<button style={{…}}>` recipes drew the same
// five buttons at heights from 26 to 40 and radii from 6 to 10: the filled
// primary, the outlined ghost, the panel-filled one the sidebar uses, the
// tinted danger, and the outlined one that sits on a session's dark
// backdrop. Three sizes, and the radius follows the height.
//
// DANGER IS ONE TREATMENT: THE TINT (owner 2026-09). Seven sites drew it as
// a --danger-dim fill, three as a red outline and two as solid red; the tint
// is the majority, it is what `.row-action.danger:hover` in tokens.css says,
// a solid red beside a filled primary gives a dialog two primaries, and a
// one-pixel red outline is the weakest read on the dark theme. In a confirm
// the tinted danger is still the only filled-looking control beside a ghost
// Cancel.
//
// WORDING (owner 2026-09): a primary says CREATE when the dialog makes a
// top-level thing, and ADD when it appends to a list already on screen.
import React from "react";
import { Icon } from "./Icon";

export type ButtonVariant = "primary" | "ghost" | "soft" | "danger" | "scrim";
export type ButtonSize = "xs" | "sm" | "md";

const SIZE = {
  xs: { height: 28, radius: 7, fontSize: "var(--fs-3)", pad: 10, gap: 5, glyph: 15 },
  sm: { height: 32, radius: 8, fontSize: "var(--fs-3)", pad: 12, gap: 6, glyph: 16 },
  md: { height: 36, radius: 9, fontSize: "var(--fs-3)", pad: 16, gap: 7, glyph: 18 },
} as const;

export interface ButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "type"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** A leading glyph. */
  icon?: string;
  /** Fully round ends — a pill. */
  round?: boolean;
  /** Lit: the accent wash, for a toggle that is on. */
  active?: boolean;
  /** Fills its row. */
  block?: boolean;
  /** Where the label sits in a block button. */
  justify?: "center" | "start";
  type?: "button" | "submit";
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "ghost", size = "md", icon, round, active, block, justify = "center",
    disabled, style, children, type = "button", ...rest }, ref,
) {
  const s = SIZE[size];
  const look: React.CSSProperties =
    active ? { background: "var(--accent-dim)", border: "1px solid var(--accent)",
               color: "var(--accent)", fontWeight: 600 }
    : variant === "primary" ? {
        background: disabled ? "var(--border)" : "var(--accent)",
        border: "1px solid transparent",
        color: disabled ? "var(--muted)" : "var(--on-accent)", fontWeight: 600 }
    : variant === "soft" ? { background: "var(--panel-2)", border: "1px solid var(--border-strong)",
                             color: "var(--text-2)", fontWeight: 600 }
    : variant === "danger" ? { background: "var(--danger-dim)", border: "1px solid transparent",
                               color: "var(--danger)", fontWeight: 600 }
    : variant === "scrim" ? { background: "transparent", border: "1px solid var(--on-scrim-4)",
                              color: "var(--on-scrim)", fontWeight: 600 }
    : { background: "transparent", border: "1px solid var(--border-strong)",
        color: "var(--text-2)", fontWeight: size === "md" ? 500 : 600 };
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled}
      {...rest}
      style={{
        display: block ? "flex" : "inline-flex", alignItems: "center",
        justifyContent: justify === "start" ? "flex-start" : "center",
        gap: s.gap, height: s.height, padding: `0 ${s.pad}px`,
        borderRadius: round ? 999 : s.radius, fontSize: s.fontSize,
        fontFamily: "inherit", whiteSpace: "nowrap", boxSizing: "border-box",
        width: block ? "100%" : undefined,
        cursor: disabled ? "default" : "pointer",
        opacity: disabled && variant !== "primary" ? 0.45 : 1,
        ...look, ...style,
      }}
    >
      {icon && <Icon name={icon} size={s.glyph} />}
      {children}
    </button>
  );
});
