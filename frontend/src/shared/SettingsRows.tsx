/** THE SETTINGS ROW FAMILY — a section, a row, and the two rows every
 *  settings page has: a preference with a dropdown, a switch.
 *
 *  The General page, the Storage page, the training form and the tag-set
 *  dialogs each drew these — four sections with three heading styles, four
 *  toggle rows, three preference rows, two "keep / choice" rows — and no
 *  two agreed on the padding. One family; a page that needs something
 *  beside the label (the training form's `?` and its Unsupported chip)
 *  passes it as `extra`.
 */
import React from "react";
import { Select } from "./Select";
import { Switch } from "./Switch";
import { SECTION_LABEL } from "./SectionHeading";

/** A section's heading: `shared/SectionHeading`'s recipe. */
export { SECTION_LABEL };

/** A titled panel of rows, hairlines between them rather than gaps. */
export function Section({ title, hint, action, bare, children, style }: {
  title?: React.ReactNode;
  hint?: string;
  /** At the heading's right — a button that acts on the whole section. */
  action?: React.ReactNode;
  /** No panel around the children — for a section whose content brings
   *  its own boxes, where the panel would be a border around borders. */
  bare?: boolean;
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, ...style }}>
      {(title || action) && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="mc-copy" style={{ ...SECTION_LABEL, flex: 1, minWidth: 0 }}>
            {title}
          </div>
          {action}
        </div>
      )}
      {hint && (
        <div className="mc-copy" style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)",
                                          marginTop: title ? -4 : 0 }}>
          {hint}
        </div>
      )}
      {bare ? children : (
        // `flexShrink: 0` keeps the panel at its content height: with
        // `overflow: hidden` a flex item's min-height collapses to 0, which
        // lets it compress and clip its bottom rows instead of letting the
        // page scroll.
        <div style={{ flexShrink: 0, background: "var(--panel)",
                      border: "1px solid var(--border)", borderRadius: "var(--r-7)",
                      overflow: "hidden" }}>
          {children}
        </div>
      )}
    </div>
  );
}

/** One row: the label (and what sits beside it), the control at the right,
 *  the hint under both. */
export function RowShell({ label, hint, last, lead, extra, onClick, pad = "10px 16px",
                           children, style, disabled }: {
  label: React.ReactNode;
  hint?: React.ReactNode;
  /** The last row draws no hairline under itself. */
  last?: boolean;
  /** Before the label — a drag handle. */
  lead?: React.ReactNode;
  /** Beside the label — a `?`, a chip. */
  extra?: React.ReactNode;
  /** The whole row is the control. */
  onClick?: () => void;
  pad?: string;
  children?: React.ReactNode;
  style?: React.CSSProperties;
  /** Its precondition is off: dimmed, the words and the control alike. */
  disabled?: boolean;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: pad,
        borderBottom: last ? "none" : "1px solid var(--border-soft)",
        cursor: onClick && !disabled ? "pointer" : undefined,
        opacity: disabled ? 0.45 : 1,
        ...style,
      }}
    >
      <div style={{ display: "flex", alignItems: "center",
                    justifyContent: "space-between", gap: 16, minHeight: 32 }}>
        {lead}
        <div style={{ display: "flex", alignItems: "center", gap: 5,
                      flex: "1 1 auto", minWidth: 0 }}>
          {/* Copyable: setting names get pasted into searches and chats. */}
          <div className="mc-copy" style={{ fontSize: "var(--fs-3)", color: "var(--text-2)",
                                            minWidth: 0 }}>
            {label}
          </div>
          {extra}
        </div>
        {children}
      </div>
      {hint && (
        <div className="mc-copy" style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)",
                                          marginTop: 4, maxWidth: 520, lineHeight: 1.45 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

/** A preference: the label, a dropdown at the right. */
export function PrefRow({ label, hint, value, onChange, options, last, minWidth = 180,
                          extra }: {
  label: React.ReactNode;
  hint?: React.ReactNode;
  value: string;
  onChange: (v: string) => void;
  options: readonly (readonly [string, string])[];
  last?: boolean;
  minWidth?: number;
  extra?: React.ReactNode;
}) {
  return (
    <RowShell label={label} hint={hint} last={last} extra={extra}>
      <Select value={value} onChange={onChange} options={options} minWidth={minWidth} />
    </RowShell>
  );
}

/** A switch: the label, the knob at the right. `title` is the knob's own
 *  words; the label serves where a caller has nothing more to say. */
export function ToggleRow({ label, hint, checked, onChange, last, disabled, title,
                            extra }: {
  label: string;
  hint?: React.ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  last?: boolean;
  disabled?: boolean;
  title?: string;
  extra?: React.ReactNode;
}) {
  return (
    <RowShell label={label} hint={hint} last={last} extra={extra} disabled={disabled}>
      <Switch checked={checked} onChange={onChange} disabled={disabled}
              title={title ?? label} />
    </RowShell>
  );
}
