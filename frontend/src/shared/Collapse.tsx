// THE HOUSE COLLAPSE: a grid row going 0fr → 1fr with a transition, the
// body clipped while it slides — height animated without measuring. Six
// panels each spelled the two divs; the inner `minHeight: 0; overflow:
// hidden` is the half that is easy to forget, and without it the row
// never closes.
import React from "react";

export function Collapse({ open, duration = 200, children, style, innerStyle }: {
  open: boolean;
  duration?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
  innerStyle?: React.CSSProperties;
}) {
  return (
    <div style={{ display: "grid", gridTemplateRows: open ? "1fr" : "0fr",
                  transition: `grid-template-rows ${duration}ms ease`, ...style }}>
      <div style={{ overflow: "hidden", minHeight: 0, ...innerStyle }}>{children}</div>
    </div>
  );
}
