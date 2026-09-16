/**
 * When a picture was taken — a date that may also carry a time.
 *
 * The same idea as `when.ts`, one level finer: the sortable number
 * **YYYYMMDDHHMMSS with zeros for the unknown parts**, so `20200000000000` is
 * "2020", `20200305000000` one day and `20200305143012` one second. The
 * encoding carries its own precision, which is what lets a search for the
 * first week of January find a picture dated only "2020".
 *
 * It is the encoding the metadata index already stores capture dates in, so
 * the override and what the camera said are the same kind of number and are
 * compared without conversion.
 *
 * Midnight and "no time given" are the same value. That is the price of an
 * encoding that carries its own precision, and the alternative — a second
 * field saying how much of the first is real — costs more than it saves for a
 * library of photographs.
 *
 * Pure and dependency-free so `node --test` can exercise it.
 */
import { formatDate, parseDate } from "./when.ts";

/**
 * "Somebody looked and this picture has no date", as opposed to a missing
 * value, which means nobody has said and the file and the events are read
 * instead. Mirrors `db.TAKEN_NONE`; every real value is positive, so one rule
 * covers both sides — `> 0` is a date, anything else is not.
 */
export const TAKEN_NONE = -1;

/** How much of a value is actually said. */
export type TakenPrecision =
  "none" | "year" | "month" | "day" | "hour" | "minute" | "second";

export function precisionOf(value?: number | null): TakenPrecision {
  if (!value) return "none";
  const d = String(Math.trunc(value)).padEnd(14, "0").slice(0, 14);
  if (d.slice(12, 14) !== "00") return "second";
  if (d.slice(10, 12) !== "00") return "minute";
  if (d.slice(8, 10) !== "00") return "hour";
  if (d.slice(6, 8) !== "00") return "day";
  if (d.slice(4, 6) !== "00") return "month";
  return "year";
}

/** The date half (YYYYMMDD), for the helpers in `when.ts`. */
export function datePart(value?: number | null): number | null {
  if (!value) return null;
  return Math.trunc(value / 1_000_000) || null;
}

/**
 * Parse what somebody typed: a date `when.ts` understands, optionally followed
 * by a time — `2020`, `March 2020`, `5 March 2020`, `5 March 2020 14:30`,
 * `2020-03-05 14:30:12`.
 *
 * The time is only read when a DAY is known: "March 2020 at 14:30" is not a
 * moment, and accepting it would store a precision nobody has.
 */
export function parseTaken(text: string, locale?: string): number | null {
  const raw = text.trim();
  if (!raw) return null;
  const time = raw.match(/(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$/);
  const datePartText = time ? raw.slice(0, time.index).trim() : raw;
  const date = parseDate(datePartText, locale);
  if (!date) return null;
  let value = date * 1_000_000;
  if (time && date % 100 !== 0) {
    const h = Number(time[1]), m = Number(time[2]), s = Number(time[3] ?? 0);
    if (h > 23 || m > 59 || s > 59) return null;
    value += h * 10_000 + m * 100 + s;
  }
  return value;
}

/** Write one back out, at exactly the precision it holds. */
export function formatTaken(value?: number | null, locale?: string): string {
  if (!value) return "";
  const date = formatDate(datePart(value), locale);
  const p = precisionOf(value);
  if (p === "year" || p === "month" || p === "day") return date;
  const d = String(Math.trunc(value)).padEnd(14, "0");
  const hh = d.slice(8, 10), mm = d.slice(10, 12), ss = d.slice(12, 14);
  return `${date} ${hh}:${mm}${p === "second" ? `:${ss}` : ""}`;
}

/** Whether a value is a moment that could exist. */
export function isValidTaken(value?: number | null): boolean {
  if (!value) return false;
  const d = String(Math.trunc(value)).padEnd(14, "0").slice(0, 14);
  const [y, mo, day, h, mi, s] = [
    +d.slice(0, 4), +d.slice(4, 6), +d.slice(6, 8),
    +d.slice(8, 10), +d.slice(10, 12), +d.slice(12, 14),
  ];
  if (y < 1 || mo > 12 || day > 31 || h > 23 || mi > 59 || s > 59) return false;
  // The same rule the date half has: a smaller component needs the one above
  // it to mean anything.
  if (day && !mo) return false;
  if ((h || mi || s) && !day) return false;
  return true;
}
