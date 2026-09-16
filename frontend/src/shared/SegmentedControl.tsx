/** ONE SEGMENTED CONTROL — a row of exclusive choices, one lit.
 *
 *  The item window's Annotate/Edit switch, the grid's S/M/L and the tag
 *  CSV dialog's kind tabs each drew their own: three paddings, three radii,
 *  three greys for the segment that is not chosen. One drawing; a caller
 *  says the options, which is lit, and whether the segments share the row
 *  (`stretch`) or sit at their own width.
 */
import React from "react";
import { Icon } from "./Icon";

export interface Segment<V extends string | number> {
  value: V;
  label?: React.ReactNode;
  icon?: string;
  title?: string;
  /** Drawn, muted, and inert — the state it holds stays readable. */
  disabled?: boolean;
  /** A fixed width for a segment that is a letter (S / M / L). */
  width?: number;
}

export function SegmentedControl<V extends string | number>({
  value, onChange, options, stretch, style,
}: {
  value: V;
  onChange: (v: V) => void;
  options: readonly Segment<V>[];
  /** The segments share the row equally (a dialog's tabs). */
  stretch?: boolean;
  style?: React.CSSProperties;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2, padding: 3,
                  borderRadius: "var(--r-5)", background: "var(--panel-2)",
                  border: "1px solid var(--border-strong)", flex: "0 0 auto",
                  ...style }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            title={o.title}
            aria-pressed={on}
            disabled={o.disabled}
            onClick={() => { if (!on && !o.disabled) onChange(o.value); }}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              gap: 5, height: 26, padding: o.width ? 0 : "0 10px",
              width: o.width, flex: stretch ? 1 : "0 0 auto",
              borderRadius: "var(--r-2)", border: "none", fontFamily: "inherit",
              fontSize: "var(--fs-3)", fontWeight: on ? 600 : 500, whiteSpace: "nowrap",
              background: on ? "var(--accent)" : "transparent",
              color: on ? "var(--on-accent)"
                : o.disabled ? "var(--muted-3)" : "var(--muted)",
              cursor: on || o.disabled ? "default" : "pointer",
            }}
          >
            {o.icon && <Icon name={o.icon} size={15} />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
