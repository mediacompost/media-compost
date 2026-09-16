// ONE SECTION HEADING. Sixty-five small uppercase labels were forty
// recipes — sizes from 9 to 11, four trackings, five colours — for one
// thing: the quiet word over a block. Two sizes remain: the ordinary one
// and `sm` for a heading inside a menu or a dense tree.
import React from "react";

export const SECTION_LABEL: React.CSSProperties = {
  fontSize: "var(--fs-2)", fontWeight: 600, letterSpacing: "0.06em",
  textTransform: "uppercase", color: "var(--muted)",
};
export const SECTION_LABEL_SM: React.CSSProperties = {
  ...SECTION_LABEL, fontSize: "var(--fs-1)", color: "var(--muted-3)",
};

export function SectionHeading({ sm, action, copy, children, style, className, ...rest }: {
  sm?: boolean;
  /** A control at the heading's right edge. */
  action?: React.ReactNode;
  /** Selectable text (`.mc-copy`) — for a heading that is a name. */
  copy?: boolean;
  children: React.ReactNode;
} & React.HTMLAttributes<HTMLDivElement>) {
  const cls = [copy ? "mc-copy" : "", className ?? ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cls}
         style={{ ...(sm ? SECTION_LABEL_SM : SECTION_LABEL),
                  ...(action ? { display: "flex", alignItems: "center", gap: 8 } : null),
                  ...style }} {...rest}>
      {action ? <span style={{ flex: 1, minWidth: 0 }}>{children}</span> : children}
      {action}
    </div>
  );
}
