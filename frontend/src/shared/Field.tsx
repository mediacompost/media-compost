/** THE DIALOGS' TEXT FIELD — one height, one label, one input.
 *
 *  Six dialogs carried a `const field: React.CSSProperties` of their own
 *  (heights 28, 30, 32 and 34; radii 7, 8 and 9) and three a `Label`, and
 *  two of them a `RecordField` apiece. These are the shapes: `fieldStyle`
 *  (34 px, mono — a tag name or a slug), `fieldStyleText` (34 px, the UI
 *  face) and `fieldStyleSm` (30 px, for a dense section), `FieldLabel`
 *  above them, and `Field` for the common case of the three together.
 */
import React from "react";
import { SectionHeading } from "../shared/SectionHeading";

const BASE: React.CSSProperties = {
  width: "100%", height: 34, padding: "0 11px", background: "var(--bg)",
  border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)",
  color: "var(--text)", fontSize: "var(--fs-4)", outline: "none",
  boxSizing: "border-box",
};

/** The edit overlays' standard text input (mono: these fields hold tag names
 *  and slugs). SubjectEditOverlay's variant is deliberately DIFFERENT (no
 *  mono, and its Label takes no hint — see the "no hint under a label" rule
 *  there), so it keeps its own. */
export const fieldStyle: React.CSSProperties = {
  ...BASE, fontFamily: "var(--mono)",
};

/** The same field in the UI face — a name, a path, a sentence. */
export const fieldStyleText: React.CSSProperties = { ...BASE, fontFamily: "inherit" };

/** A dense section's field. */
export const fieldStyleSm: React.CSSProperties = {
  ...BASE, height: 30, padding: "0 10px", fontSize: "var(--fs-3)", fontFamily: "inherit",
};

export function FieldLabel({ children, hint }: {
  children: React.ReactNode; hint?: string;
}) {
  return (
    <div style={{ marginBottom: 6 }}>
      <SectionHeading>
        {children}
      </SectionHeading>
      {hint && <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 3 }}>{hint}</div>}
    </div>
  );
}

/** A labelled input: the label, the field, and its state. */
export function Field({ label, value, onChange, placeholder, hint, mono, bad,
                        autoFocus, small, type, onKeyDown }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  /** A tag name or a slug. */
  mono?: boolean;
  /** The value does not parse — the border says so. */
  bad?: boolean;
  autoFocus?: boolean;
  /** The dense (30 px) size. */
  small?: boolean;
  type?: string;
  onKeyDown?: React.KeyboardEventHandler<HTMLInputElement>;
}) {
  return (
    <div>
      <FieldLabel hint={hint}>{label}</FieldLabel>
      <input
        value={value}
        placeholder={placeholder}
        autoFocus={autoFocus}
        type={type}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        style={{
          ...(small ? fieldStyleSm : fieldStyleText),
          ...(mono ? { fontFamily: "var(--mono)", fontSize: small ? 12 : 13 } : null),
          ...(bad ? { borderColor: "var(--red)" } : null),
        }}
      />
    </div>
  );
}
