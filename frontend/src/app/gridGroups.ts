// What a section's KEY means to a reader, and how the jump popover is stacked.
//
// The backend sends keys only — "202403", "a", a band index — because month
// and colour names have to be localized, and the date formatters and the
// colour tag set both live here. Pure and React-free, so `node --test`
// covers the whole answer space.

import type { GroupRun } from "./gridGeom";

/** The fixed colour tag set, indexed by the band packed into `color_key`'s
 *  high bits (see `backend/media_compost/colorkey.py`). The BOUNDARIES live
 *  only in the backend — this is a lookup joined by index, not a second
 *  implementation of the classification. */
export const COLOR_BANDS: { key: string; label: string; swatch: string }[] = [
  { key: "black", label: "Black", swatch: "#111114" },
  { key: "grey", label: "Gray", swatch: "#8b8b93" },
  { key: "white", label: "White", swatch: "#f2f2f4" },
  { key: "red", label: "Red", swatch: "#d4342c" },
  { key: "orange", label: "Orange", swatch: "#e8862a" },
  { key: "brown", label: "Brown", swatch: "#7a4b22" },
  { key: "yellow", label: "Yellow", swatch: "#e6d232" },
  { key: "green", label: "Green", swatch: "#3aa84f" },
  { key: "teal", label: "Teal", swatch: "#25a7a7" },
  { key: "blue", label: "Blue", swatch: "#3560d8" },
  { key: "purple", label: "Purple", swatch: "#8a37c4" },
  { key: "pink", label: "Pink", swatch: "#e055ac" },
];

/** Megapixel band upper bounds, mirroring `prefilter.MP_BANDS`. */
export const MP_BANDS = [1, 2, 4, 8, 16];

/** An empty key is the server's "nobody knows" bucket — a picture nothing
 *  dates, a file with no colour. It always sorts last. */
export const UNKNOWN_KEY = "";

/**
 * The words a section header shows.
 *
 * `t` translates the fixed phrases; dates go through `Intl` rather than the
 * i18n map, because month names per language are already solved there and a
 * hand-translated table would get the next language wrong.
 */
export function groupLabel(
  groupBy: string, key: string, lang: string,
  t: (s: string, vars?: Record<string, string | number>) => string,
): string {
  if (key === UNKNOWN_KEY) {
    if (groupBy === "band") return t("No color");
    if (groupBy === "initial") return t("Unnamed");
    if (groupBy === "bucket") return t("Unplaced");
    return t("Undated");
  }
  switch (groupBy) {
    case "year":
      return key;
    // A capture date's zeros are its PRECISION (`15030000000000` is "1503"),
    // so a month/day section can be coarser than its grouping: a year-only
    // date under Month grouping keys as "150300". Naming what IS known is the
    // honest label — fed to `Date`, the zero became month -1 / day 0 and the
    // section read "November 30, 1502".
    case "month": {
      if (key.slice(4, 6) === "00") return key.slice(0, 4);
      const d = new Date(+key.slice(0, 4), +key.slice(4, 6) - 1, 1);
      return new Intl.DateTimeFormat(lang, { year: "numeric", month: "long" })
        .format(d);
    }
    case "day": {
      if (key.slice(4, 6) === "00") return key.slice(0, 4);
      if (key.slice(6, 8) === "00") {
        const d = new Date(+key.slice(0, 4), +key.slice(4, 6) - 1, 1);
        return new Intl.DateTimeFormat(lang, { year: "numeric", month: "long" })
          .format(d);
      }
      const d = new Date(+key.slice(0, 4), +key.slice(4, 6) - 1, +key.slice(6, 8));
      return new Intl.DateTimeFormat(lang,
        { year: "numeric", month: "long", day: "numeric" }).format(d);
    }
    case "initial":
      return key === "#" ? t("Other") : key.toUpperCase();
    case "mp": {
      const i = Number(key);
      if (!Number.isFinite(i)) return key;
      if (i === 0) return `< ${MP_BANDS[0]} MP`;
      if (i >= MP_BANDS.length) return `${MP_BANDS[MP_BANDS.length - 1]}+ MP`;
      return `${MP_BANDS[i - 1]}–${MP_BANDS[i]} MP`;
    }
    case "band": {
      const b = COLOR_BANDS[Number(key)];
      return b ? t(b.label) : key;
    }
    // THE STANDING, SAID AS ONE (owner 2026-09). A section headed "7" over a
    // row of pictures is a number with nothing to hold it — every other
    // grouping here names what it is counting ("July 1969", "2–4 MP"), and
    // a ranking's own scale is the one place the bare figure could be read
    // as a count of something.
    case "bucket":
      return t("Score {n}", { n: key });
    default:
      return key;
  }
}

/** The swatch a colour-band header carries, or null for every other kind. */
export function groupSwatch(groupBy: string, key: string): string | null {
  if (groupBy !== "band" || key === UNKNOWN_KEY) return null;
  return COLOR_BANDS[Number(key)]?.swatch ?? null;
}

export interface JumpEntry {
  /** The section key to jump to — always a real section, so a click lands. */
  key: string;
  label: string;
  count: number;
  swatch?: string | null;
}

export interface JumpGroup {
  label: string;
  count: number;
  entries: JumpEntry[];
}

/**
 * The jump popover's contents.
 *
 * DATE groupings stack year › month whatever the section granularity is —
 * grouping by day over fifteen years is five thousand sections, and a flat
 * list of those is the thing the popover exists not to be. Every other kind
 * lists flat, because their tag sets are already short (26 initials, 6
 * megapixel bands, 12 colours).
 *
 * Built from the SAME runs array the grid lays out, so the popover cannot
 * disagree with what it scrolls to — and a jump always names a section that
 * exists, since every entry is derived from one.
 */
export function jumpGroups(
  groupBy: string, runs: readonly GroupRun[], lang: string,
  t: (s: string) => string,
): JumpGroup[] {
  const dated = groupBy === "year" || groupBy === "month" || groupBy === "day";
  if (!dated) {
    return [{
      label: "",
      count: runs.reduce((n, r) => n + r.count, 0),
      entries: runs.map((r) => ({
        key: r.key,
        label: groupLabel(groupBy, r.key, lang, t),
        count: r.count,
        swatch: groupSwatch(groupBy, r.key),
      })),
    }];
  }
  // Year › month. A day-grouped view collapses to the month its first day
  // section starts in, and the jump lands on that section — the nearest thing
  // to the period asked for that actually exists.
  const out: JumpGroup[] = [];
  const byYear = new Map<string, Map<string, { key: string; count: number }>>();
  const unknown: GroupRun[] = [];
  for (const r of runs) {
    if (r.key === UNKNOWN_KEY) { unknown.push(r); continue; }
    const year = r.key.slice(0, 4);
    const month = r.key.length >= 6 ? r.key.slice(0, 6) : year;
    let months = byYear.get(year);
    if (!months) { months = new Map(); byYear.set(year, months); }
    const at = months.get(month);
    // The first section of a month is the one a jump should land on.
    if (at) at.count += r.count;
    else months.set(month, { key: r.key, count: r.count });
  }
  for (const [year, months] of byYear) {
    const entries: JumpEntry[] = [];
    let total = 0;
    for (const [month, v] of months) {
      total += v.count;
      entries.push({
        key: v.key,
        label: groupBy === "year"
          ? year
          : groupLabel("month", month.padEnd(6, "0"), lang, t),
        count: v.count,
      });
    }
    out.push({ label: year, count: total, entries });
  }
  for (const r of unknown) {
    out.push({
      label: groupLabel(groupBy, r.key, lang, t),
      count: r.count,
      entries: [{ key: r.key, count: r.count,
                  label: groupLabel(groupBy, r.key, lang, t) }],
    });
  }
  return out;
}
