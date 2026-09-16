/** A NUMBER FIELD REJECTS THE KEYSTROKE, NEVER STORES `NaN` — the query
 *  builder's rule (`ConditionRow.wholeNumber`), spelled nine ways across the
 *  app: one regex per field, three of them stripping characters instead of
 *  refusing them, two with a digit cap and the rest without. One rule:
 *  `filterNumeric` answers the text as typed when it is a number or on its
 *  way to one ("", "1.", ".5"), and null when the keystroke should be
 *  refused. `useNumericText` is the hook for a field whose state is a
 *  NUMBER rather than the text. */
import { useState } from "react";

export interface NumericRule {
  /** Whole numbers only. */
  integer?: boolean;
  /** At most this many digits after the point (implies decimals allowed). */
  decimals?: number;
  /** At most this many digits BEFORE the point. */
  maxLen?: number;
  /** A leading minus is allowed. */
  negative?: boolean;
}

export function filterNumeric(text: string, rule: NumericRule = {}): string | null {
  const sign = rule.negative ? "-?" : "";
  const whole = rule.maxLen != null ? `\\d{0,${rule.maxLen}}` : "\\d*";
  const frac = rule.integer ? ""
    : rule.decimals != null ? `(?:\\.\\d{0,${rule.decimals}})?` : "(?:\\.\\d*)?";
  return new RegExp(`^${sign}${whole}${frac}$`).test(text) ? text : null;
}

/** The field's text over a numeric value: typing is filtered by the rule,
 *  and the number lands on every keystroke that parses (empty = null where
 *  `allowEmpty`, else the field's `empty` stand-in); the blur clamps to
 *  `min`/`max` and rounds to `decimals`. */
export function useNumericText(opts: {
  value: number | null;
  onChange: (n: number | null) => void;
  rule?: NumericRule;
  min?: number;
  max?: number;
  allowEmpty?: boolean;
}): {
  text: string;
  onChange: (e: { target: { value: string } }) => void;
  onBlur: () => void;
  inputMode: "numeric" | "decimal";
} {
  const { value, onChange, rule = {}, min, max, allowEmpty = true } = opts;
  const [text, setText] = useState(value == null ? "" : String(value));
  const clamp = (n: number) => {
    let v = n;
    if (min != null) v = Math.max(min, v);
    if (max != null) v = Math.min(max, v);
    if (rule.integer) v = Math.round(v);
    else if (rule.decimals != null) v = Number(v.toFixed(rule.decimals));
    return v;
  };
  return {
    text,
    inputMode: rule.integer ? "numeric" : "decimal",
    onChange: (e) => {
      const next = filterNumeric(e.target.value, rule);
      if (next == null) return;
      setText(next);
      if (next === "" || next === "-" || next === ".") {
        if (allowEmpty) onChange(null);
        return;
      }
      const n = Number(next);
      if (Number.isFinite(n)) onChange(n);
    },
    onBlur: () => {
      if (text === "" || text === "-" || text === ".") {
        if (!allowEmpty && value != null) setText(String(value));
        return;
      }
      const n = clamp(Number(text));
      setText(String(n));
      if (n !== value) onChange(n);
    },
  };
}
