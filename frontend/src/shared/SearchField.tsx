// ONE SEARCH FIELD. Four lists had a field with a magnifier inset at the
// left and a ✕ at the right that appears with the text — each spelled
// out with its own inset, glyph size and padding. Escape clears it (and
// stops there, so the dialog behind does not close on the same press).
import React from "react";
import { Icon } from "./Icon";

const SIZE = {
  sm: { height: 26, radius: 7, fontSize: "var(--fs-2)", glyph: 15, inset: 8, padL: 28, padR: 26, pad: 8, clear: 14, border: "var(--border)" },
  md: { height: 30, radius: 8, fontSize: "var(--fs-3)", glyph: 15, inset: 9, padL: 30, padR: 28, pad: 10, clear: 14, border: "var(--border-strong)" },
  lg: { height: 34, radius: 9, fontSize: "var(--fs-3)", glyph: 17, inset: 10, padL: 34, padR: 30, pad: 12, clear: 16, border: "var(--border-strong)" },
} as const;

export function SearchField({ value, onChange, placeholder, clearTitle, size = "md", autoFocus,
                              inputRef, style, inputStyle, onKeyDown }: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  /** The ✕'s title — the caller translates. */
  clearTitle: string;
  size?: keyof typeof SIZE;
  autoFocus?: boolean;
  inputRef?: React.Ref<HTMLInputElement>;
  /** The wrapper's: where the field sits (margins, flex). */
  style?: React.CSSProperties;
  inputStyle?: React.CSSProperties;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
}) {
  const s = SIZE[size];
  return (
    <div style={{ position: "relative", minWidth: 0, ...style }}>
      <Icon name="search" size={s.glyph}
            style={{ position: "absolute", left: s.inset, top: "50%", transform: "translateY(-50%)",
                     color: "var(--muted-3)", pointerEvents: "none" }} />
      <input ref={inputRef} value={value} onChange={(e) => onChange(e.target.value)}
             placeholder={placeholder} autoFocus={autoFocus}
             onKeyDown={(e) => {
               if (e.key === "Escape") { e.stopPropagation(); onChange(""); return; }
               onKeyDown?.(e);
             }}
             style={{ width: "100%", height: s.height, boxSizing: "border-box",
                      padding: value ? `0 ${s.padR}px 0 ${s.padL}px` : `0 ${s.pad}px 0 ${s.padL}px`,
                      background: "var(--panel-2)", border: `1px solid ${s.border}`,
                      borderRadius: s.radius, color: "var(--text)", fontSize: s.fontSize,
                      fontFamily: "inherit", outline: "none", ...inputStyle }} />
      {value && (
        <span onClick={() => onChange("")} title={clearTitle}
              style={{ position: "absolute", right: s.inset - 2, top: "50%",
                       transform: "translateY(-50%)", display: "flex",
                       cursor: "pointer", color: "var(--muted-2)" }}>
          <Icon name="close" size={s.clear} />
        </span>
      )}
    </div>
  );
}
