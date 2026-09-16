// Numeric VALUE tags — the `<name>:<number><unit>` convention.
//
// Any tag whose BASENAME is a number with an optional unit is a value tag:
// `people:3`, `height:172cm`, `height:1.72m`, `quality:7`. Parsing is
// derivation, not storage. Mirrors `media_compost/tagvalue.py` — both sides
// pure, and `tests/golden/value_corpus.json` keeps them equal, asserted by
// BOTH pytest and `node --test`.
//
// In `shared/` because both `query/` (the VALUE: condition row and the
// serializer) and `app/` (the namespace list, the comma-decimal nudge) read
// it, and `query/` may not import `app/`.

/** The convertible families, each unit as a factor to the family's base. */
export const FAMILIES: Record<string, Record<string, number>> = {
  length: { mm: 0.001, cm: 0.01, m: 1, km: 1000 },
  mass: { mg: 1e-6, g: 0.001, kg: 1 },
};

const UNIT_FAMILY = new Map<string, [string, number]>();
for (const [fam, units] of Object.entries(FAMILIES)) {
  for (const [u, f] of Object.entries(units)) UNIT_FAMILY.set(u, [fam, f]);
}

// A number (dot OR comma decimal — a restored tag can hold a comma, dot is
// what the app writes) followed by a free unit suffix. No digits in a unit:
// `1.2m2` would be ambiguous.
const VALUE = /^(-?\d+(?:[.,]\d+)?)([a-z%°µ]*)$/;

export interface TagValue {
  value: number;
  unit: string;
}

/** The value a tag basename holds, or null for an ordinary word. */
export function parseValue(basename: string): TagValue | null {
  const m = VALUE.exec(basename);
  if (!m) return null;
  return { value: Number(m[1].replace(",", ".")), unit: m[2] };
}

/** Which values a unit may be compared against: a convertible unit answers
 *  its FAMILY, an unknown one itself prefixed (`u:px`), no unit `""`. */
export function valueSpace(unit: string): string {
  if (!unit) return "";
  const fam = UNIT_FAMILY.get(unit);
  return fam ? fam[0] : "u:" + unit;
}

/** The value in its space's base unit — `172cm` and `1.72m` agree. */
export function canonValue(v: TagValue): [string, number] {
  const fam = UNIT_FAMILY.get(v.unit);
  return [valueSpace(v.unit), fam ? v.value * fam[1] : v.value];
}

const EPS = 1e-9;

function cmp(a: number, op: string, b: number, tol: number): boolean {
  if ((op === "=" || op === "!=") && tol > 0) {
    const inside = a >= b - tol && a < b + tol;
    return op === "=" ? inside : !inside;
  }
  if (op === "=") return Math.abs(a - b) < EPS;
  if (op === "!=") return Math.abs(a - b) >= EPS;
  if (op === ">") return a > b;
  if (op === ">=") return a >= b - EPS;
  if (op === "<") return a < b;
  if (op === "<=") return a <= b + EPS;
  return false;
}

/** Whether one tag basename satisfies `op value unit`. `tol` is in the
 *  literal's own unit (half its last typed decimal place) and converts with
 *  it. */
export function matchesValue(
  basename: string, op: string, value: number, unit: string, tol = 0,
): boolean {
  const v = parseValue(basename);
  if (v === null) return false;
  if (!unit) {
    // A unitless literal IGNORES units: the value's own number, as written —
    // `height:172cm` reads as 172 — so a namespace tagged in one consistent
    // unit searches without the unit spelled out.
    return cmp(v.value, op, value, tol);
  }
  const [sp, a] = canonValue(v);
  const [lsp, b] = canonValue({ value, unit });
  if (sp !== lsp) return false;
  const fam = UNIT_FAMILY.get(unit);
  return cmp(a, op, b, fam ? tol * fam[1] : tol);
}
