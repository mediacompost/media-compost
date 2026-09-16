// ONE CHIP. A hundred and twenty-three small labelled boxes were ninety-
// eight recipes: badges on a thumbnail, the filter pills over a list, the
// "gated" and "unsupported" marks, the capsules on a tag row, a caption's
// "pending". The rule: a CHIP is read and is 26 px or under; a BUTTON is
// pressed and is 28 px or over (`shared/Button`). A chip with `onClick`
// is still a chip — a pill that clears a filter — and renders a <button>.
import React from "react";
import { Icon } from "./Icon";

export type ChipTone = "neutral" | "accent" | "warn" | "danger" | "green" | "overlay";
export type ChipSize = "sm" | "md" | "lg";

const SIZE = {
  sm: { height: 15, fontSize: "var(--fs-0)", pad: 6, radius: 5, gap: 3, glyph: 11 },
  md: { height: 20, fontSize: "var(--fs-1)", pad: 7, radius: 5, gap: 4, glyph: 13 },
  lg: { height: 26, fontSize: "var(--fs-2)", pad: 10, radius: 8, gap: 6, glyph: 14 },
} as const;

const TONE: Record<ChipTone, { bg: string; fg: string; border: string }> = {
  neutral: { bg: "var(--panel-2)", fg: "var(--muted-2)", border: "var(--border)" },
  accent: { bg: "var(--accent-dim)", fg: "var(--accent)", border: "var(--accent)" },
  warn: { bg: "var(--yellow-dim)", fg: "var(--yellow-text)", border: "var(--yellow-border)" },
  danger: { bg: "var(--danger-dim)", fg: "var(--danger)", border: "var(--danger-border)" },
  green: { bg: "var(--green-dim)", fg: "var(--green-text)", border: "var(--green-border)" },
  overlay: { bg: "var(--scrim-3)", fg: "var(--on-scrim)", border: "var(--overlay-hairline)" },
};

export interface ChipLook {
  tone?: ChipTone;
  size?: ChipSize;
  /** Fully round ends — a pill. */
  round?: boolean;
  /** The tone's border, rather than a transparent one of the same width. */
  bordered?: boolean;
  /** Tabular figures in the mono face — a count, a duration, a position. */
  mono?: boolean;
  /** A small uppercase MARK ("gated", "pending") rather than a word. */
  upper?: boolean;
}

/** The recipe as a style object, for the capsules that measure themselves. */
export function chipStyle({ tone = "neutral", size = "md", round, bordered, mono, upper }: ChipLook): React.CSSProperties {
  const s = SIZE[size]; const t = TONE[tone];
  return {
    display: "inline-flex", alignItems: "center", gap: s.gap, flex: "0 0 auto",
    height: s.height, padding: `0 ${s.pad}px`, boxSizing: "border-box",
    borderRadius: round ? 999 : s.radius, whiteSpace: "nowrap",
    fontSize: s.fontSize, lineHeight: 1,
    fontWeight: upper ? 700 : 600,
    fontFamily: mono ? "var(--mono)" : "inherit",
    ...(upper ? { textTransform: "uppercase", letterSpacing: "0.04em" } : null),
    background: t.bg, color: t.fg,
    border: `1px solid ${bordered ? t.border : "transparent"}`,
  };
}

export function Chip({ tone, size, round, bordered, mono, upper, icon, onClick, title, children,
                       style, className, ...rest }: ChipLook & {
  icon?: string;
  onClick?: React.MouseEventHandler<HTMLElement>;
  title?: string;
  children?: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
} & Omit<React.HTMLAttributes<HTMLElement>, "onClick" | "title" | "style" | "className" | "children">) {
  const s = SIZE[size ?? "md"];
  const look = { ...chipStyle({ tone, size, round, bordered, mono, upper }), ...style };
  const body = <>{icon && <Icon name={icon} size={s.glyph} />}{children}</>;
  if (onClick) {
    return (
      <button type="button" onClick={onClick} title={title} className={className}
              style={{ ...look, cursor: "pointer" }} {...rest}>
        {body}
      </button>
    );
  }
  return <span title={title} className={className} style={look} {...rest}>{body}</span>;
}
