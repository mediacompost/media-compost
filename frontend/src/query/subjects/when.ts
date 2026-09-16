/**
 * Dates that know how much of themselves is known, and the age that follows.
 *
 * "Born 1879", "built July 1999", "taken 14 March 1879" are all dates, and a
 * subject's timeline needs whichever the user actually has. They are encoded as
 * the sortable number **YYYYMMDD with zeros for the unknown parts** —
 * `19750000` is the year, `19990700` the month, `18790314` one day — so the
 * encoding carries its own precision and a range comparison stays arithmetic.
 *
 * The backend mirrors this in `partialdate.py`, for the same reason
 * `numTolerance` is mirrored there: the rule has to hold on both sides of the
 * wire. Pure and dependency-free so `node --test` can exercise it.
 */

export type Precision = "year" | "month" | "day" | "none";

export function encode(year: number, month = 0, day = 0): number {
  return year * 10000 + month * 100 + day;
}

export function decode(value: number): [number, number, number] {
  return [Math.floor(value / 10000), Math.floor(value / 100) % 100, value % 100];
}

export function precisionOf(value?: number | null): Precision {
  if (!value) return "none";
  const [, m, d] = decode(value);
  return d ? "day" : m ? "month" : "year";
}

/** Whether a value is a date that could exist (a day needs a month). */
export function isValid(value?: number | null): boolean {
  if (!value) return false;
  const [y, m, d] = decode(value);
  if (y < 1 || y > 9999 || m > 12 || d > 31) return false;
  return !(d && !m);
}

/** The [first, last] a partial date covers — what makes "1975" mean the year. */
export function bounds(value: number): [number, number] {
  const [y, m, d] = decode(value);
  if (!m) return [encode(y, 1, 1), encode(y, 12, 31)];
  if (!d) return [encode(y, m, 1), encode(y, m, 31)];
  return [value, value];
}

/**
 * Whole years between two partial dates, or null when either is missing.
 *
 * Unknown months and days read as "the start of what is known", the only
 * reading that cannot overstate an age: a subject that exists since 1975 is 0
 * during 1975, not 1.
 */
export function ageAt(since?: number | null, when?: number | null): number | null {
  if (!since || !when) return null;
  const [sy, sm, sd] = decode(since);
  const [wy, wm, wd] = decode(when);
  let years = wy - sy;
  if (wm * 100 + wd < sm * 100 + sd) years -= 1;
  return years >= 0 ? years : null;
}

/** The year a subject reached `age` — year precision, since an age says
 *  nothing about the month. */
export function dateFromAge(since?: number | null, age?: number | null): number | null {
  if (!since || age == null || age < 0) return null;
  return encode(decode(since)[0] + age);
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** A locale's month names (long and short), longest first, cached — what
 *  `parseDate` recognizes so `formatDate`'s output reads back. */
const MONTH_CACHE = new Map<string, [string, number][]>();
function localeMonths(locale: string): [string, number][] {
  let out = MONTH_CACHE.get(locale);
  if (out) return out;
  out = [];
  try {
    for (const style of ["long", "short"] as const) {
      const fmt = new Intl.DateTimeFormat(locale, { month: style, timeZone: "UTC" });
      for (let m = 0; m < 12; m++)
        out.push([fmt.format(new Date(Date.UTC(2000, m, 1))), m]);
    }
  } catch { /* unknown locale: nothing extra to recognize */ }
  out.sort((a, b) => b[0].length - a[0].length);
  MONTH_CACHE.set(locale, out);
  return out;
}

/**
 * Parse what someone typed into a partial date: `1975`, `7/1999`, `1999-07`,
 * `14.3.1879`, `1879-03-14`, `March 1879`, `14 March 1879`.
 *
 * Deliberately forgiving about separators and order-agnostic only where it is
 * unambiguous (a 4-digit part is the year). **Month names are understood
 * because `formatDate` writes them** — a field prefilled with its own output
 * has to read back, or the editor flags the value it just showed you.
 * Returns null when it cannot tell.
 */
export function parseDate(text: string, locale?: string): number | null {
  let t = text.trim();
  if (!t) return null;
  // A month NAME pins the month outright — no order left to guess, which is
  // what makes "March 14, 1879" (month first) and "14 March 1879" (day
  // first) both read. A LOCALIZED name is tried first: `formatDate(v,
  // locale)` writes these, so without it localizing the display broke the
  // round trip the docstring above promises. Substring match, longest name
  // first — CJK month names ("3月") contain no Latin word for the regex to
  // find, and one name may prefix another.
  let namedMonth = 0;
  if (locale) {
    for (const [name, idx] of localeMonths(locale)) {
      const at = t.indexOf(name);
      if (at >= 0) {
        namedMonth = idx + 1;
        t = t.slice(0, at) + " " + t.slice(at + name.length);
        break;
      }
    }
  }
  // An ENGLISH month name is still understood in any locale — the query bar
  // and older saved values write these.
  if (!namedMonth) {
    const named = t.match(/[A-Za-zÀ-ÿ]{3,}/);
    if (named) {
      const low = named[0].toLowerCase();
      const idx = MONTHS.findIndex(
        (m) => m.toLowerCase() === low || m.toLowerCase().startsWith(low.slice(0, 3)));
      if (idx < 0) return null;   // a word that is not a month is not a date
      namedMonth = idx + 1;
      t = t.replace(named[0], " ");
    }
  }
  const parts = t.split(/[^\d]+/).filter(Boolean).map(Number);
  if (parts.some((n) => !Number.isFinite(n))) return null;
  const yearAt = parts.findIndex((n) => n >= 1000);
  if (yearAt < 0) return null;
  const year = parts[yearAt];
  const rest = parts.filter((_, i) => i !== yearAt);
  let month: number, day: number;
  if (namedMonth) {
    month = namedMonth;
    day = rest[0] ?? 0;
    if (rest.length > 1) return null;   // "14 March 3 1879" is not a date
  } else {
    // Numbers only: the rest keep their written order — year first reads
    // Y-M-D, year last reads D-M-Y.
    const [a, b] = yearAt === 0 ? rest : [...rest].reverse();
    month = a ?? 0;
    day = b ?? 0;
  }
  const value = encode(year, month, day);
  return isValid(value) ? value : null;
}

/**
 * A partial date as text, at whatever precision it has.
 *
 * `locale` picks the month name and the day/month order; passing none gives
 * the English form the query bar and the tests use.
 */
export function formatDate(value?: number | null, locale?: string): string {
  if (!value) return "";
  const [y, m, d] = decode(value);
  if (!m) return String(y);
  if (!locale) return d ? `${d} ${MONTHS[m - 1]} ${y}` : `${MONTHS[m - 1]} ${y}`;
  const date = new Date(Date.UTC(y, m - 1, d || 1));
  return new Intl.DateTimeFormat(locale, {
    year: "numeric", month: "long", ...(d ? { day: "numeric" } : {}),
    timeZone: "UTC",
  }).format(date);
}

/** What a subject's `when` chip says: the date, the age, or both. */
export function whenLabel(
  when: { date?: number | null; age?: number | null } | null | undefined,
  since?: number | null,
  locale?: string,
  ageText?: (age: number) => string,
): string {
  if (!when) return "";
  const date = when.date ?? dateFromAge(since, when.age);
  const age = when.age ?? ageAt(since, when.date);
  const left = when.date ? formatDate(when.date, locale) : "";
  // "age 12", not "(12)". The brackets were the short form for a chip squeezed
  // onto the subject's own line; on a line of its own there is room to say
  // which number this is, and a bracketed number next to a year read as a
  // footnote rather than an age. The wording comes from the caller when it
  // has a translator (`query/` cannot import React) — Japanese wants "{n}歳".
  const right = age != null ? (ageText ? ageText(age) : `age ${age}`) : "";
  if (left && right) return `${left} · ${right}`;
  if (left) return left;
  if (right) return right;
  return date ? formatDate(date, locale) : "";
}
