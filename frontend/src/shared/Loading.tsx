// WAITING AND FAILING, said once each. "Loading…" was a bare word in five
// places and a spinner in a sixth; a failed read was a red mono line in the
// grid and a centred sentence with a Try-again button in the sessions. Two
// tones: `page` sits in a panel or a view, `overlay` on the sessions' dark
// backdrop (their text is white whatever the theme, since the backdrop is).
import React from "react";
import { Button } from "../shared/Button";
import { Icon } from "./Icon";

type Tone = "page" | "overlay";

const CENTRE: React.CSSProperties = {
  flex: 1, minHeight: 0, display: "flex", flexDirection: "column",
  alignItems: "center", justifyContent: "center", gap: 8,
  color: "var(--on-scrim-2)", fontSize: "var(--fs-4)", textAlign: "center",
};

export function Loading({ label, tone = "page", style }: {
  label: string;
  tone?: Tone;
  style?: React.CSSProperties;
}) {
  if (tone === "overlay") {
    return (
      <div style={{ ...CENTRE, flexDirection: "row", ...style }}>
        <Icon name="progress_activity" size={16} spin />
        {label}
      </div>
    );
  }
  return (
    <div style={{ padding: 24, color: "var(--muted)", display: "flex",
                  alignItems: "center", gap: 8, fontSize: "var(--fs-4)", ...style }}>
      <Icon name="progress_activity" size={16} spin />
      {label}
    </div>
  );
}

export function Trouble({ message, detail, onRetry, retryLabel, tone = "page", style }: {
  /** What did not happen, in the caller's own words. */
  message: string;
  /** The server's reason, when there is one. */
  detail?: string | null;
  onRetry?: () => void;
  /** Required with `onRetry`; the caller translates. */
  retryLabel?: string;
  tone?: Tone;
  style?: React.CSSProperties;
}) {
  const overlay = tone === "overlay";
  return (
    <div onMouseDown={overlay ? (e) => e.stopPropagation() : undefined}
         style={overlay ? { ...CENTRE, ...style }
                        : { padding: 24, display: "flex", flexDirection: "column",
                            alignItems: "flex-start", gap: 8, fontSize: "var(--fs-4)", ...style }}>
      <div style={{ fontSize: "var(--fs-4)",
                    color: overlay ? "var(--on-scrim)" : "var(--red-text)" }}>
        {message}
      </div>
      {detail && (
        <div style={{ fontSize: "var(--fs-3)", maxWidth: 520, lineHeight: 1.5,
                      overflowWrap: "anywhere",
                      fontFamily: overlay ? undefined : "var(--mono)",
                      color: overlay ? undefined : "var(--muted-2)" }}>
          {detail}
        </div>
      )}
      {onRetry && (
        <Button variant={overlay ? "scrim" : "ghost"} size="sm" onClick={onRetry} style={{ marginTop: 6 }}>
          {retryLabel}
        </Button>
      )}
    </div>
  );
}
