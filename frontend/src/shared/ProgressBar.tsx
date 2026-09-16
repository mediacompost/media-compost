// ONE PROGRESS BAR. Nine bars were drawn by hand — a track and a fill at
// heights of three to eleven pixels, four track colours, three easings, and
// two of them raising a floor so a 0.3% job shows as a sliver rather than
// nothing. The floor is the one rule worth keeping and it is here once:
// anything under way is at least `floor` percent wide.
import React from "react";

export const PROGRESS_FLOOR_PCT = 2;

export function ProgressBar({ value, height = 6, width = "100%", color = "var(--accent)",
                              track = "var(--panel-3)", floor = PROGRESS_FLOOR_PCT,
                              bordered, transitionMs = 200, style }: {
  /** 0–100; clamped. */
  value: number;
  height?: number;
  width?: number | string;
  /** The fill — a token, or a computed colour for a gauge. */
  color?: string;
  track?: string;
  /** Least width, in percent, of a fill that is not zero. */
  floor?: number;
  bordered?: boolean;
  transitionMs?: number;
  style?: React.CSSProperties;
}) {
  const pct = Math.max(0, Math.min(100, value));
  const shown = pct > 0 ? Math.max(floor, pct) : 0;
  return (
    <span style={{
      display: "block", width, height, borderRadius: height / 2, background: track,
      overflow: "hidden", flex: "0 0 auto", boxSizing: "border-box",
      border: bordered ? "1px solid var(--border)" : undefined, ...style,
    }}>
      <span style={{
        display: "block", height: "100%", width: `${shown}%`, background: color,
        borderRadius: height / 2,
        // The colour crossfades too, so a gauge hovering on a threshold does
        // not strobe between two colours.
        transition: `width ${transitionMs}ms ease, background ${transitionMs}ms ease`,
      }} />
    </span>
  );
}
