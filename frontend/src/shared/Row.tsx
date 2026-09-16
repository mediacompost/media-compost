// ONE SELECTABLE ROW, AND THE ONE REASON A ROW STOPPED ANSWERING HOVER.
//
// `tokens.css` tints a `.hoverable` row on hover with a plain background
// rule — which any INLINE `background:` beats, tint or "transparent". So
// every list that painted its rows inline (a selected row's accent wash,
// a panel fill, even `"transparent"`) had rows that never tinted under the
// pointer, and the tags tree alone had worked around it by stacking the
// wash on top of its tint. `rowBackground` is that stack for everybody:
// the hover wash (`--row-wash`, which the hover rule sets) over the accent
// wash over the base, so a picked row answers the pointer like an unpicked
// one and an unpicked one answers it at all.
import React from "react";

/** The background of a row that can be picked, hover wash included. */
export function rowBackground(selected: boolean | undefined, base: string = "transparent"): string {
  return "linear-gradient(var(--row-wash), var(--row-wash)), "
    + (selected ? "linear-gradient(var(--accent-dim), var(--accent-dim)), " : "")
    + base;
}

/** The corner radius of a run of picked rows: squared where two join. */
export function rowRadius(radius: number, selected?: boolean, joinAbove?: boolean, joinBelow?: boolean): number | string {
  if (!selected || (!joinAbove && !joinBelow)) return radius;
  const top = joinAbove ? 0 : radius; const bottom = joinBelow ? 0 : radius;
  return `${top}px ${top}px ${bottom}px ${bottom}px`;
}

export interface RowProps extends React.HTMLAttributes<HTMLDivElement> {
  selected?: boolean;
  joinAbove?: boolean;
  joinBelow?: boolean;
  height?: number;
  radius?: number;
  /** What the row sits on, for the wash to stack over. */
  base?: string;
  hoverable?: boolean;
}

/** A 30 px flex row that can be picked — the sidebars' rows. */
export const Row = React.forwardRef<HTMLDivElement, RowProps>(function Row(
  { selected, joinAbove, joinBelow, height = 30, radius = 7, base, hoverable = true,
    className, style, children, ...rest }, ref,
) {
  const cls = [hoverable ? "hoverable" : "", className ?? ""].filter(Boolean).join(" ") || undefined;
  return (
    <div ref={ref} className={cls}
         style={{ display: "flex", alignItems: "center", gap: 6, height, boxSizing: "border-box",
                  padding: "0 6px", cursor: "pointer", fontSize: "var(--fs-3)",
                  borderRadius: rowRadius(radius, selected, joinAbove, joinBelow),
                  color: "var(--text-2)", ...style,
                  background: rowBackground(!!selected, base),
                  ...(selected ? { color: "var(--selected-text)" } : null) }}
         {...rest}>
      {children}
    </div>
  );
});
