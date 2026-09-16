/** A thing the app is OFFERING, with the two answers spelled out.
 *
 * Used for the venues an event implies and the events a picture's own date
 * implies. Nothing about a suggestion is stored — remove the event's tag and
 * the offer is gone with it — so the only thing that persists is the "no", and
 * it persists for good.
 *
 * Dashed and muted, so it never reads as something already assigned; the
 * REASON sits underneath, because a row that appears with no explanation is a
 * row nobody trusts. Both answers are explicit rather than hidden in a ⋯ menu:
 * a question with exactly two answers should not cost two clicks to agree
 * with — the same shape the face suggestion already uses ("Alice? · 87%").
 */
import React from "react";
import { SectionHeading } from "../../../shared/SectionHeading";
import { Icon } from "../../../shared/Icon";
import { useT } from "../../i18n";

export function SuggestedRow({ icon, label, title, reason, onAccept, onDismiss }: {
  icon: string;
  label: string;
  title?: string;
  /** Why it is being offered — "San Diego Comic-Con 2014 was here". */
  reason: string;
  onAccept: () => void;
  onDismiss: () => void;
}) {
  const t = useT();
  return (
    <div className="hoverable" style={{
      display: "flex", alignItems: "center", gap: 6,
      padding: "5px 6px 5px 8px", borderRadius: "var(--r-4)", minHeight: 26,
      background: "transparent",
      border: "1px dashed var(--border-strong)",
    }}>
      <Icon name={icon} size={15} color="var(--muted-3)" />
      <span style={{ minWidth: 0, flex: 1, display: "flex",
        flexDirection: "column", gap: 1 }}>
        <span title={title}
          style={{ fontSize: "var(--fs-3)", color: "var(--muted)", overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {label}
        </span>
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
          color: "var(--muted-3)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {reason}
        </span>
      </span>
      <span onClick={onAccept} title={t("Yes, add it")}
        style={{ flex: "0 0 auto", cursor: "pointer", display: "flex",
          color: "var(--accent)" }}>
        <Icon name="check" size={15} />
      </span>
      <span onClick={onDismiss} title={t("No — and stop offering it")}
        style={{ flex: "0 0 auto", cursor: "pointer", display: "flex",
          color: "var(--muted-2)" }}>
        <Icon name="close" size={15} />
      </span>
    </div>
  );
}

/** The heading above a run of them. Rendered only when there is one. */
export function SuggestedHeading({ children }: { children: React.ReactNode }) {
  return (
    <SectionHeading sm style={{ padding: "6px 0 2px" }}>
      {children}
    </SectionHeading>
  );
}
