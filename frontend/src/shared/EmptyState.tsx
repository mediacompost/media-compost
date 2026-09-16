// ONE EMPTY STATE. A list with nothing in it said so in a dozen shapes — a
// centred block at 40 px, a muted line at 11.5 px inside a section, a card
// with a glyph — and each list decided its own colour and size. Two shapes
// remain: the FULL one for a view (centred, room around it, an optional way
// out) and the DENSE one for a section inside a panel, which is a line.
import React from "react";
import { Button } from "../shared/Button";
import { Icon } from "./Icon";

export function EmptyState({ line, hint, icon, action, dense, style }: {
  /** What is empty, in the caller's own words. */
  line: React.ReactNode;
  /** What one is, or what to do about it — a second, quieter paragraph. */
  hint?: React.ReactNode;
  icon?: string;
  /** The way out of the empty state, where there is one. */
  action?: { label: string; icon?: string; onClick: () => void };
  /** A line inside a section rather than a block in a view. */
  dense?: boolean;
  style?: React.CSSProperties;
}) {
  if (dense) {
    return (
      <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", lineHeight: 1.5, ...style }}>
        {line}
        {hint && <div style={{ color: "var(--muted-3)" }}>{hint}</div>}
      </div>
    );
  }
  return (
    <div className="mc-copy"
         style={{ padding: "40px 16px", textAlign: "center", color: "var(--muted-2)",
                  display: "flex", flexDirection: "column", alignItems: "center",
                  gap: 8, fontSize: "var(--fs-4)", ...style }}>
      {icon && <Icon name={icon} size={20} color="var(--muted-2)" />}
      <div style={{ maxWidth: 420 }}>{line}</div>
      {hint && (
        <div style={{ maxWidth: 420, fontSize: "var(--fs-3)", lineHeight: 1.6, color: "var(--muted-3)" }}>
          {hint}
        </div>
      )}
      {action && (
        <Button size="sm" active
     onClick={action.onClick} style={{ marginTop: 6 }}>
          {action.icon && <Icon name={action.icon} size={16} />}
          {action.label}
        </Button>
      )}
    </div>
  );
}
