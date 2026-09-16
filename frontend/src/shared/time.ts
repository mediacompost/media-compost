// Date/time formatting driven by the user's explicit Language & Region settings
// (a chosen date-format pattern + a 24-hour toggle), not the OS/browser locale.
//
// This is the REACT half — the hook that binds the settings query to the
// renderers. The renderers themselves are `shared/dateFormat.ts`, which
// imports nothing and so can be tested by `node --test`; they are re-exported
// from here, where every caller already looks for them.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { normalizeLang } from "./i18nCore";
import {
  DATE_FORMAT_OPTIONS, DEFAULT_FORMAT, renderDate, renderTime,
} from "./dateFormat";

export {
  DATE_FORMAT_OPTIONS, fmtDuration, renderDate, renderTime,
} from "./dateFormat";

export interface DateFormatters {
  /** Numeric date per the chosen pattern (sidebar callers pass shortYear). */
  formatDate: (v: string | number | Date, opts?: { shortYear?: boolean }) => string;
  /** Time honoring the 24-hour toggle. */
  formatTime: (v: string | number | Date) => string;
  /** Date + time (sidebar callers pass shortYear). */
  formatDateTime: (v: string | number | Date, opts?: { shortYear?: boolean }) => string;
  /** Date + time from a **unix-seconds** stamp (what the training and
   *  evaluation APIs return, being file-based rather than DB-backed); empty
   *  string for a missing one, so callers can render it unguarded. */
  formatUnix: (ts: number | null | undefined, opts?: { shortYear?: boolean }) => string;
  /** Weekday-prefixed full date for day headers, e.g. "Thursday, 9 Jul 2026". */
  formatDayHeader: (v: string | number | Date) => string;
  /** How long ago, in words: "5 minutes ago", "yesterday", "vor 3 Stunden".
   *  Unix SECONDS (what the file-based training APIs report); "" for none. */
  formatAgo: (ts: number | null | undefined) => string;
  /** The raw 24-hour-clock preference (for building time controls). */
  time24h: boolean;
}

/** Build the formatters bound to the current Language & Region settings. Reads
 *  the shared `["settings"]` query, so changing the setting re-renders and
 *  re-formats live; falls back to the defaults until settings load. */
export function useDateFormatters(): DateFormatters {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const pattern = data?.date_format ?? DEFAULT_FORMAT;
  const time24h = data?.time_24h ?? false;
  // Relative wording is a translation problem the platform has already
  // solved ("yesterday" / "gestern", plural rules and all), so it comes from
  // Intl rather than from the i18n map. `normalizeLang`, not a hand-rolled
  // narrowing — a second copy of "which languages exist" is how this hook
  // silently stayed bilingual once.
  const lang = normalizeLang(data?.language);
  return useMemo<DateFormatters>(() => {
    const formatDate = (v: string | number | Date, o?: { shortYear?: boolean }) =>
      renderDate(v, pattern, { ...o, locale: lang });
    const formatTime = (v: string | number | Date) => renderTime(v, time24h);
    const formatDateTime = (v: string | number | Date,
                            o?: { shortYear?: boolean }) => {
      const dt = formatDate(v, o);
      const t = formatTime(v);
      return dt && t ? `${dt} ${t}` : dt || t;
    };
    return {
      formatDate,
      formatTime,
      formatDateTime,
      formatUnix: (ts, o) => (ts ? formatDateTime(ts * 1000, o) : ""),
      formatDayHeader: (v) => {
        const weekday = new Date(
          v instanceof Date ? v.getTime() : new Date(v).getTime()
        ).toLocaleDateString(lang, { weekday: "long" });
        const date = formatDate(v);
        return date ? `${weekday}, ${date}` : "";
      },
      formatAgo: (ts) => {
        if (!ts) return "";
        const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
        // Seconds into the past. `numeric: "auto"` is what turns -1 day into
        // "yesterday" and 0 into "now" instead of "in 0 seconds".
        let v = Math.round(Date.now() / 1000 - ts);
        const units: [Intl.RelativeTimeFormatUnit, number][] = [
          ["second", 60], ["minute", 60], ["hour", 24],
          ["day", 7], ["week", 4.35], ["month", 12], ["year", Infinity],
        ];
        for (const [unit, size] of units) {
          if (Math.abs(v) < size || unit === "year") {
            return rtf.format(-Math.round(v), unit);
          }
          v /= size;
        }
        return "";
      },
      time24h,
    };
  }, [pattern, time24h, lang]);
}
