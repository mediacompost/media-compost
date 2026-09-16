// ONE GLYPH BUTTON. Seventy-nine `.row-action` spans and fifty square
// `<button>`s each drew a glyph in a box of their own size, radius and
// colour. Here the radius follows the size (a quarter of it), the glyph
// follows the size (the table below), and the three ways a glyph button
// is shown are named: always, on ROW HOVER taking no space until then
// (`reveal="hover"`, the sidebar's ⋯ and ✕), or on row hover WITHOUT
// reflowing the row (`reveal="fixed"`, `visibility` — Safari leaves a
// fading element painted, which is why it is not opacity; the rules are
// in tokens.css).
//
// A revealed one is a `span role="button"`: the rows it sits in are
// mousedown-driven, and a real <button> steals focus and Enter.
import React from "react";
import { Icon } from "./Icon";

export type IconTone = "default" | "muted" | "text" | "accent" | "danger";

const GLYPH: Record<number, number> = {
  16: 12, 18: 13, 20: 15, 22: 15, 24: 16, 26: 17, 28: 17, 30: 18, 32: 19,
  34: 19, 36: 20, 40: 22,
};

export interface IconButtonProps extends Omit<React.HTMLAttributes<HTMLElement>, "color"> {
  icon: string;
  /** Required: a glyph alone says nothing to a screen reader or a hover. */
  title: string;
  size?: number;
  tone?: IconTone;
  /** A colour of the caller's own — a conditional, a signal colour. */
  color?: string;
  shape?: "square" | "round";
  bordered?: boolean;
  /** A panel fill behind it (the sidebar's), the floating surface's, or the
   *  blurred chrome over a picture (on-scrim text). */
  fill?: "panel" | "float" | "chrome";
  /** Shown on row hover only — see the file comment. */
  reveal?: "hover" | "fixed";
  /** On an accent fill: the hover wash is white rather than the accent. */
  onAccent?: boolean;
  /** Lit: the accent wash, for a toggle that is on. */
  active?: boolean;
  /** The glyph's size, where the table's answer is wrong. */
  glyph?: number;
  disabled?: boolean;
  spin?: boolean;
}

/** The recipe as a style object, for the two menus that draw their own
 *  trigger from a style (`RowMenu`, `ThemeMenu`). */
export function iconButtonStyle({ size = 24, bordered, fill, shape, active, tone = "default", color }: {
  size?: number; bordered?: boolean; fill?: "panel" | "float" | "chrome"; shape?: "square" | "round";
  active?: boolean; tone?: IconTone; color?: string;
}): React.CSSProperties {
  const fg = color ?? (
    fill === "chrome" ? "var(--on-scrim)"
    : active ? "var(--accent)"
    : tone === "accent" ? "var(--accent)"
    : tone === "muted" ? "var(--muted)"
    : tone === "text" ? "var(--text-2)"
    : "var(--muted-2)");
  return {
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    flex: "0 0 auto", width: size, height: size, padding: 0, boxSizing: "border-box",
    borderRadius: shape === "round" ? 999 : Math.round(size / 4),
    border: bordered ? "1px solid var(--border-strong)" : "1px solid transparent",
    background: active ? "var(--accent-dim)"
      : fill === "panel" ? "var(--panel-2)"
      : fill === "float" ? "var(--surface-float)"
      : fill === "chrome" ? "var(--overlay-chrome)" : "transparent",
    color: fg, cursor: "pointer", fontFamily: "inherit", lineHeight: 1,
  };
}

export const IconButton = React.forwardRef<HTMLElement, IconButtonProps>(function IconButton(
  { icon, title, size = 24, tone = "default", color, shape, bordered, fill, reveal, onAccent,
    active, glyph, disabled, spin, className, style, onClick, ...rest }, ref,
) {
  const cls = [
    "icon-btn",
    reveal === "hover" ? "row-action" : reveal === "fixed" ? "row-action row-action-fixed" : "",
    tone === "danger" ? "danger" : "", onAccent ? "on-accent" : "", className ?? "",
  ].filter(Boolean).join(" ");
  const base = iconButtonStyle({ size, bordered, fill, shape, active, tone, color });
  const styles: React.CSSProperties = {
    ...base, ...(disabled ? { opacity: 0.45, cursor: "default" } : null), ...style,
  };
  const g = <Icon name={icon} size={glyph ?? GLYPH[size] ?? Math.round(size * 0.6)} spin={spin} />;
  if (reveal) {
    return (
      <span ref={ref as React.Ref<HTMLSpanElement>} role="button" title={title} className={cls}
            style={styles} onClick={disabled ? undefined : onClick} {...rest}>
        {g}
      </span>
    );
  }
  return (
    <button ref={ref as React.Ref<HTMLButtonElement>} type="button" title={title} className={cls}
            style={styles} disabled={disabled} onClick={onClick} {...rest}>
      {g}
    </button>
  );
});
