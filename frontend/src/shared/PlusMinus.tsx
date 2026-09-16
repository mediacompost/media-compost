// THE + AND − DRAWN RATHER THAN TYPED. The symbol font shipped here is a
// static 400 weight whose `add`/`remove` glyphs read thinner beside a
// tag's outline, and it has no weight axis to turn up; a typed "+" is a
// different face again. Two rounded strokes at the tag glyph's visual
// weight — the tag grid's answer capsule stated the reason first, and the
// query builder's row buttons are the same two marks.
import React from "react";

export function PlusMinus({ kind, size = 18, style }: {
  kind: "plus" | "minus" | "both";
  size?: number;
  style?: React.CSSProperties;
}) {
  // ± for "both": the plus over the minus, at the same stroke.
  const d = kind === "both" ? "M5 9h14M12 2v14M5 20h14"
    : kind === "plus" ? "M5 12h14M12 5v14" : "M5 12h14";
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden
         style={{ display: "block", ...style }}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth={2.8} strokeLinecap="round" />
    </svg>
  );
}
