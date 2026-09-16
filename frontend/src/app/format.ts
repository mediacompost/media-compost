// Display formatting shared across views, so the same value never reads
// differently in two places.
//
// Each formatter takes an optional trailing LOCALE (the app language) and
// localizes only its decimal/grouping separators — "6,1 GB" in German. With
// none they keep their historical English output, which is what the node
// tests pin and what any machine-facing caller must keep.

import { formatNumber } from "../shared/i18nCore.ts";

/** `v` to exactly `digits` fraction digits, in `locale` or plain English. */
function fixed(v: number, digits: number, locale?: string): string {
  if (!locale) return v.toFixed(digits);
  return formatNumber(locale, v, {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
    // A byte size or a megapixel count never wants grouping ("1.234,5 MB"
    // gains nothing over the unit step that should have happened instead).
    useGrouping: false,
  });
}

/**
 * `"0.6 MP"` — a resolution as the user sees it.
 *
 * Integer math on purpose. Formatting `w * h / 1e6` as a float rounds the
 * binary approximation of the value, and rounding it twice (once server-side,
 * once for display) made the same image read as 0.7 MP in the grid and 0.6 MP
 * in the metadata list. Mirrors `megapixel_label` in the backend's media.py.
 */
export function mpLabel(width: number, height: number, locale?: string): string {
  const tenths = Math.floor((width * height + 50_000) / 100_000);   // round half up
  // The integer math above owns the ROUNDING (the double-round trap in the
  // docstring); the locale only writes the one decimal it produced.
  return `${fixed(tenths / 10, 1, locale)} MP`;
}

/**
 * A byte count as a human size — the ONE formatter, so a file never reads
 * differently in two places. **Decimal (1000-based) with GB/MB/KB labels**, to
 * match what macOS Finder shows: Finder switched to decimal units in 2009, so a
 * 1024-based "GB" here always read smaller than the disk did. (Use GiB/MiB only
 * where a value is genuinely binary — none of ours is.)
 */
export function formatBytes(bytes: number, locale?: string): string {
  if (bytes >= 1e12) return fixed(bytes / 1e12, 1, locale) + " TB";
  if (bytes >= 1e9) return fixed(bytes / 1e9, 1, locale) + " GB";
  if (bytes >= 1e6) return fixed(bytes / 1e6, 1, locale) + " MB";
  if (bytes >= 1e3) return fixed(bytes / 1e3, 0, locale) + " KB";
  return bytes + " B";
}

/** How worried to be about the space left on the library's volume.
 *
 * An absolute floor decides it — what matters is whether the next import fits,
 * and that is measured in gigabytes, not percent. The percentage only *adds*
 * to the level, and only while the absolute figure is already smallish: a
 * nearly-full 4 TB disk with 80 GB left is worth a nudge, but the same 2% rule
 * unqualified would shout about a perfectly healthy 500 GB.
 *
 * `none` also covers "couldn't read it" — better silent than a scary 0 B.
 */
export type DiskLevel = "none" | "low" | "critical";

const GB = 1024 ** 3;

export function diskLevel(free: number, total: number): DiskLevel {
  if (!total || free <= 0) return "none";
  const frac = free / total;
  if (free < 2 * GB || (frac < 0.02 && free < 50 * GB)) return "critical";
  if (free < 10 * GB || (frac < 0.05 && free < 100 * GB)) return "low";
  return "none";
}

/**
 * A COUNT that has to fit in a small tile: `842`, `1.2k`, `48k`, `1.3M`.
 *
 * `toLocaleString` is right wherever there is room for it and wrong the moment
 * there is not — "+999,988" in a 52 px square is a number nobody can read,
 * printed over the picture it was meant to stand beside. One decimal below ten
 * of a unit and none above it, so the string is at most four characters.
 *
 * The unit steps up when the rounded value would otherwise read `1000k`, which
 * is both longer than the rule allows and a stranger way of writing 1M.
 */
export function compactCount(n: number, locale?: string): string {
  const abs = Math.abs(n);
  if (abs < 1000) return String(n);
  const units: [number, string][] = [[1e3, "k"], [1e6, "M"], [1e9, "B"]];
  let pick = 0;
  while (pick < units.length - 1 && abs / units[pick][0] >= 999.5) pick++;
  const [size, suffix] = units[pick];
  const v = n / size;
  // Only the decimal SEPARATOR localizes ("1,2k") — the compaction stays
  // hand-rolled, because the whole contract is "at most four characters in a
  // 52 px square" and Intl compact notation does not guarantee it (CJK also
  // groups by 10^4: 1.2万 — correct, but wider).
  const body = Math.abs(v) < 10
    ? fixed(v, 1, locale).replace(/[.,]0$/, "") : String(Math.round(v));
  return `${body}${suffix}`;
}
