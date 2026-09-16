/** THE DROPDOWN — one drawing of a `<select>`.
 *
 *  A native select's arrow is a different size and colour in every browser,
 *  so ten of them each took `appearance: none` and drew their own chevron,
 *  with their own height, padding and radius. One here: the field's height
 *  and radius (`shared/Field.tsx`'s), the chevron at the right, `bare` for
 *  the ones that sit inline in a heading with no box at all. The options are
 *  `[value, label]` pairs, headed `groups`, or `children` for a caller that
 *  builds its own (a disabled option with a reason after its label).
 */
import React from "react";
import { Icon } from "./Icon";

export function Select({ value, onChange, options, groups, children, disabled,
                         minWidth = 170, height = 32, bare, style, title,
                         ariaLabel, leading, wrapStyle }: {
  value: string;
  onChange: (v: string) => void;
  options?: readonly (readonly [string, string])[];
  /** Headed sections; a group with an empty heading renders its entries bare. */
  groups?: readonly (readonly [string, readonly (readonly [string, string])[]])[];
  children?: React.ReactNode;
  disabled?: boolean;
  minWidth?: number;
  height?: number;
  /** No box and no chevron — a choice inline in a heading. */
  bare?: boolean;
  style?: React.CSSProperties;
  title?: string;
  ariaLabel?: string;
  /** A glyph inside the box, before the text (the grid's group-by). */
  leading?: React.ReactNode;
  wrapStyle?: React.CSSProperties;
}) {
  const opt = ([v, label]: readonly [string, string]) => (
    <option key={v} value={v}>{label}</option>
  );
  const body = children ?? (groups
    ? groups.map(([heading, entries]) => heading
      ? <optgroup key={heading} label={heading}>{entries.map(opt)}</optgroup>
      : entries.map(opt))
    : (options ?? []).map(opt));
  const select = (
    <select
      value={value}
      disabled={disabled}
      title={title}
      aria-label={ariaLabel}
      onChange={(e) => onChange(e.target.value)}
      style={{
        appearance: "none", WebkitAppearance: "none", MozAppearance: "none",
        fontFamily: "inherit", outline: "none",
        cursor: disabled ? "default" : "pointer",
        ...(bare
          ? { border: "none", background: "transparent", padding: 0, color: "inherit" }
          : { height, padding: "0 30px 0 12px", minWidth,
              background: "var(--bg)", border: "1px solid var(--border-strong)",
              borderRadius: "var(--r-4)", color: "var(--text)", fontSize: "var(--fs-3)" }),
        ...style,
      }}
    >
      {body}
    </select>
  );
  if (bare) return select;
  return (
    <div title={title} style={{ position: "relative", display: "inline-flex",
                                alignItems: "center", opacity: disabled ? 0.5 : 1,
                                ...wrapStyle }}>
      {leading}
      {select}
      <Icon name="expand_more" size={16} color="var(--muted-2)"
            style={{ position: "absolute", right: 8, top: "50%",
                     transform: "translateY(-50%)", pointerEvents: "none" }} />
    </div>
  );
}
