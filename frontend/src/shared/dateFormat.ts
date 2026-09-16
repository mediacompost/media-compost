/**
 * THE PURE HALF of date/time formatting: a pattern in, a string out.
 *
 * It lived in `shared/time.ts` beside `useDateFormatters`, which is a React
 * hook over `useQuery` — so the module could not be loaded by `node --test`
 * at all (the runner resolves no extensionless import and pulls in
 * react-query on the way), and the one funnel every user-visible date in the
 * app goes through had no test of any kind. Split for the same reason
 * `compose.py` and `zoomPivot.ts` are their own modules: the arithmetic is
 * testable, the hook around it is not.
 *
 * `time.ts` re-exports all of this, so nothing that already imports from
 * there has to change.
 *
 * A date-format pattern is a small template of tokens with literal
 * separators:
 *   YYYY  4-digit year      YY  2-digit year
 *   MMMM  full month name    MMM  short month name
 *   MM    2-digit month      M   month number
 *   DD    2-digit day        D   day number
 * Month/weekday *names* still come from the browser locale (there is nothing
 * to choose there), but order, separators and the clock are fully explicit.
 */

/** The date-format options offered in Settings (value = pattern). Kept in sync
 *  with the backend's `_DATE_FORMATS`; the first entry is the default. */
export const DATE_FORMAT_OPTIONS: readonly string[] = [
  "D MMM YYYY",
  "MMM D, YYYY",
  "D MMMM YYYY",
  "MMMM D, YYYY",
  "M/D/YYYY",
  "MM/DD/YYYY",
  "D/M/YYYY",
  "DD/MM/YYYY",
  "D.M.YYYY",
  "DD.MM.YYYY",
  "YYYY-MM-DD",
  "YYYY/MM/DD",
];
export const DEFAULT_FORMAT = DATE_FORMAT_OPTIONS[0];

// Tokens ordered longest-first so the scanner is greedy (YYYY before YY, etc.).
const TOKENS = ["YYYY", "YY", "MMMM", "MMM", "MM", "M", "DD", "D"] as const;

const pad2 = (n: number) => String(n).padStart(2, "0");

/** Render a date from a pattern. `shortYear` renders 2-digit years (YYYY→YY). */
export function renderDate(
  value: string | number | Date,
  pattern: string,
  opts?: { shortYear?: boolean; locale?: string }
): string {
  const d = value instanceof Date ? value : new Date(value);
  if (isNaN(d.getTime())) return "";
  const pat = opts?.shortYear ? pattern.replace(/YYYY/g, "YY") : pattern;
  const year = d.getFullYear();
  const month = d.getMonth() + 1;
  const day = d.getDate();
  // Month names in the APP language when a caller passes one — a Japanese UI
  // printing "9 Mar 2026" because the browser is en-US reads as a bug. With
  // no locale the browser decides, which keeps the pure function's tests and
  // any legacy caller exactly as they were.
  const monthName = (style: "long" | "short") =>
    d.toLocaleDateString(opts?.locale, { month: style });
  let out = "";
  for (let i = 0; i < pat.length; ) {
    const tok = TOKENS.find((t) => pat.startsWith(t, i));
    if (!tok) { out += pat[i]; i += 1; continue; }
    i += tok.length;
    switch (tok) {
      case "YYYY": out += String(year); break;
      case "YY": out += pad2(year % 100); break;
      case "MMMM": out += monthName("long"); break;
      case "MMM": out += monthName("short"); break;
      case "MM": out += pad2(month); break;
      case "M": out += String(month); break;
      case "DD": out += pad2(day); break;
      case "D": out += String(day); break;
    }
  }
  return out;
}

/** Render a time honoring the 24-hour toggle, e.g. "20:05" or "8:05 PM". */
export function renderTime(value: string | number | Date, time24h: boolean): string {
  const d = value instanceof Date ? value : new Date(value);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: !time24h });
}

// Format seconds as m:ss (or h:mm:ss) for badges/labels.
export function fmtDuration(sec: number): string {
  if (!isFinite(sec) || sec < 0) sec = 0;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const ss = String(s).padStart(2, "0");
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${ss}`;
  return `${m}:${ss}`;
}
