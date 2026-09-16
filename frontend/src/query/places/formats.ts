/**
 * WHAT A PLACE READS AS — and there is almost nothing left to decide.
 *
 * This file used to be an address database: a fixed tag set of eight
 * components, a per-country table saying which of them existed, what each was
 * called and in what order the finished line read, and a formatter that put
 * them together (Germany writes "Invalidenstraße 43", the US "43 Invalid…").
 * Three facts refused to be derived from one another — reading direction,
 * postcode placement, street-vs-number order — so the table was the only
 * honest way to do it.
 *
 * A PLACE IS ONE LINE NOW. Whoever types the name knows how their country
 * writes one, nothing here has to be taught it, and "the corner of the old
 * market" is finally sayable. What is left is the pair of helpers that say
 * which of a place's own fields to show, and the coordinate text.
 */

/** What to call a place in a list — its name, then its tag.
 *
 * Written once because several call sites were each spelling a different half
 * of it. A place says ONE thing about itself now, so this is nearly trivial —
 * it stays because "what if neither is set" is still a question, and because
 * the answer belongs in one place. */
export function placeLabel(p: {
  name?: string | null;
  tag?: string | null;
}): string {
  return (p.name || "").trim() || (p.tag || "").trim();
}

/** The same, cut to one short line: a chip that has no room for a street.
 *  A place's line reads finest-first in most of the world, so the first
 *  component is the specific end of it. */
export function shortPlace(p: {
  name?: string | null;
  tag?: string | null;
}): string {
  const label = placeLabel(p);
  return label.split(",")[0].trim() || label;
}

/** What a search can usefully offer as a place value — the NAMES this
 * library actually holds, commonest first.
 *
 * The library IS the tag set: there is no address database here, and
 * offering a city nobody has tagged would promise matches that cannot exist.
 * The identity TAG is not offered, because a place condition no longer
 * searches one — that is the tag field's own question.
 */
export function placeValues(
  places: { name?: string | null }[],
): string[] {
  const seen = new Map<string, number>();
  for (const p of places) {
    const value = (p.name || "").trim();
    if (value) seen.set(value, (seen.get(value) ?? 0) + 1);
  }
  return [...seen].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name]) => name);
}

/** Parse "35.6812, 139.7671" (or with N/E suffixes) into coordinates. */
export function parseLatLon(text: string): { lat: number; lon: number } | null {
  const m = text.trim().match(
    /^(-?\d+(?:\.\d+)?)\s*°?\s*([NS])?[,;\s]+(-?\d+(?:\.\d+)?)\s*°?\s*([EW])?$/i);
  if (!m) return null;
  let lat = Number(m[1]);
  let lon = Number(m[3]);
  if (m[2]?.toUpperCase() === "S") lat = -lat;
  if (m[4]?.toUpperCase() === "W") lon = -lon;
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

/** Coordinates as text, at the precision a place deserves (~1 m). */
export function formatLatLon(lat?: number | null, lon?: number | null): string {
  if (lat == null || lon == null) return "";
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}
