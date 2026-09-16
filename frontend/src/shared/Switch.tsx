/** THE ON/OFF KNOB — one drawing, so a row on the General page, a row in
 *  the training form, a storage rule and the import overlay's options
 *  cannot drift into four switches (they had: three sizes, two disabled
 *  opacities, one that never animated).
 *
 *  Two sizes (`md` for a settings row, `sm` beside a title with a
 *  description under it) and two forms: with `onChange` it is a BUTTON that
 *  toggles itself; without, an INDICATOR for a row that owns the click (the
 *  import overlay's option rows, the sidebar's extra-output row) — the same
 *  drawing, so the two read as one control.
 *
 *  It animates only once somebody has touched it: a stored "on" arriving
 *  from the settings query after the first paint would otherwise slide
 *  off→on every time the overlay opened. An indicator's owner says when
 *  (`animate`), since the press lands on the row.
 *
 *  `title` is required and is the caller's words: the English "On"/"Off"
 *  the old default carried was an i18n hole. */
import React, { useState } from "react";

const SIZES = {
  md: { w: 40, h: 24, knob: 20, on: 18 },
  sm: { w: 36, h: 21, knob: 17, on: 17 },
} as const;

export function Switch({ checked, onChange, size = "md", disabled, title,
                         animate: animateIn, style }: {
  checked: boolean;
  /** Omit for an indicator whose row owns the click. */
  onChange?: (v: boolean) => void;
  size?: "md" | "sm";
  disabled?: boolean;
  title: string;
  /** For an indicator: the row has been touched, so the knob may slide. */
  animate?: boolean;
  style?: React.CSSProperties;
}) {
  const [touched, setTouched] = useState(false);
  const animate = animateIn ?? touched;
  const s = SIZES[size];
  const box: React.CSSProperties = {
    position: "relative", width: s.w, height: s.h, flex: "0 0 auto",
    borderRadius: "var(--r-round)", border: "none", padding: 0,
    cursor: onChange && !disabled ? "pointer" : undefined,
    opacity: disabled ? 0.45 : 1,
    background: checked ? "var(--accent)" : "var(--border-strong)",
    transition: animate ? "background 0.15s ease" : "none",
    ...style,
  };
  const knob = (
    <span
      style={{
        position: "absolute", top: 2, left: checked ? s.on : 2,
        width: s.knob, height: s.knob, borderRadius: "50%", background: "var(--on-accent)",
        boxShadow: "var(--shadow-1)",
        transition: animate ? "left 0.15s ease" : "none",
      }}
    />
  );
  if (!onChange) {
    return (
      <span role="switch" aria-checked={checked} title={title} style={box}>
        {knob}
      </span>
    );
  }
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(e) => { e.stopPropagation(); setTouched(true); onChange(!checked); }}
      title={title}
      style={box}
    >
      {knob}
    </button>
  );
}
