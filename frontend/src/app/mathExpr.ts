// Tiny arithmetic-expression evaluator for numeric form fields: "500+10"
// becomes 510 when the field commits (blur/Enter). Only digits, + - * / ( ),
// decimal points and spaces are allowed — anything else returns null.
export function evalExpr(input: string): number | null {
  const s = input.trim();
  if (s === "" || !/^[0-9+\-*/(). ]+$/.test(s)) return null;
  try {
    const v = Function(`"use strict"; return (${s});`)() as unknown;
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  } catch {
    return null;
  }
}
