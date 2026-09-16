// A COUNT A PERSON READS. Every sidebar row, tab and section ends in one,
// and each was its own mono span with its own size and colour; the pill on
// a tab was another. Both go through `useNum` now, so a library of 1,234,567
// items is grouped the way the UI language groups it — `toLocaleString`
// was called at four sites and nowhere else.
import React from "react";
import { useNum } from "./i18n";

export function Count({ n, size = 10.5, tone = "muted-3", pad, className, style }: {
  n: number;
  size?: 10 | 10.5;
  tone?: "muted-2" | "muted-3";
  /** The sidebar rows' right-hand breathing room. */
  pad?: boolean;
  className?: string;
  style?: React.CSSProperties;
}) {
  const num = useNum();
  return (
    <span className={className} style={{ fontFamily: "var(--mono)", fontSize: size, color: `var(--${tone})`,
                   paddingRight: pad ? 4 : undefined, ...style }}>
      {num(n)}
    </span>
  );
}

/** The pill on a tab or a button: small, bold, on a wash of its own. */
export function CountBadge({ n, active, warn, style }: {
  n: number;
  active?: boolean;
  /** AMBER — something in what it counts is a machine's claim nobody has
   *  agreed with yet (a pending tag group, a guessed face, a generated
   *  caption). It wins over `active`: which tab is open is visible in the
   *  tab itself, and the fact the badge is there to say is this one. */
  warn?: boolean;
  style?: React.CSSProperties;
}) {
  const num = useNum();
  return (
    <span style={{
      flex: "0 0 auto", fontSize: "var(--fs-1)", fontWeight: 700, textAlign: "center",
      color: warn ? "var(--yellow-text)" : active ? "var(--accent)" : "var(--muted-2)",
      background: warn ? "var(--yellow-dim)" : active ? "var(--accent-dim)" : "var(--panel-2)",
      borderRadius: "var(--r-round)", padding: "0 5px", minWidth: 16, ...style,
    }}>
      {num(n)}
    </span>
  );
}
