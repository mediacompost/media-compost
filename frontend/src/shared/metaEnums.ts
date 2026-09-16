/** Decoding the EXIF fields whose stored value is a CODE.
 *
 * `orientation`, `flash`, `metering_mode` and `white_balance` are indexed as
 * the integers the file holds, and this is the only place they become words.
 * That split is deliberate: a decoded label is English, so putting it in the
 * index would make a search term untranslatable and would silently change what
 * an existing `INFO:flash=16` matches. So the QUERY STRING keeps the number
 * everywhere — the filter button writes one, the builder stores one, `tree.ts`
 * serializes one — and only what is drawn on screen becomes words.
 *
 * In `shared/` rather than `app/` because both readers need it and they are in
 * different packages: the Info tab's rows, and the query builder's value
 * dropdown. `query/` may not import `app/` (`boundaries.test.ts`).
 *
 * Pure and dependency-free, so `node --test` covers the whole table.
 */

/** Flash is a BITFIELD, not an enumeration — bit 0 is "the flash fired" and
 *  the rest describe the mode — which is why `decodeMeta` falls back to
 *  reading that bit alone rather than answering "Unknown" for a combination
 *  nobody listed. These are the combinations EXIF actually defines; a camera
 *  may still write one that is not here. */
const FLASH: Record<number, string> = {
  0: "Did not fire",
  1: "Fired",
  5: "Fired, no return detected",
  7: "Fired, return detected",
  9: "Fired, compulsory",
  13: "Fired, compulsory, no return",
  15: "Fired, compulsory, return detected",
  16: "Off, did not fire",
  20: "Off, did not fire, no return",
  24: "Auto, did not fire",
  25: "Fired, auto",
  29: "Fired, auto, no return",
  31: "Fired, auto, return detected",
  32: "No flash function",
  48: "Off, no flash function",
  65: "Fired, red-eye reduction",
  69: "Fired, red-eye reduction, no return",
  71: "Fired, red-eye reduction, return detected",
  73: "Fired, compulsory, red-eye reduction",
  77: "Fired, compulsory, red-eye, no return",
  79: "Fired, compulsory, red-eye, return detected",
  89: "Fired, auto, red-eye reduction",
  93: "Fired, auto, red-eye, no return",
  95: "Fired, auto, red-eye, return detected",
};

const ORIENTATION: Record<number, string> = {
  1: "Normal",
  2: "Mirrored",
  3: "Rotated 180°",
  4: "Mirrored, rotated 180°",
  5: "Mirrored, rotated 90° CCW",
  6: "Rotated 90° CW",
  7: "Mirrored, rotated 90° CW",
  8: "Rotated 90° CCW",
};

const METERING: Record<number, string> = {
  0: "Unknown",
  1: "Average",
  2: "Centre-weighted",
  3: "Spot",
  4: "Multi-spot",
  5: "Pattern",
  6: "Partial",
  255: "Other",
};

const WHITE_BALANCE: Record<number, string> = { 0: "Auto", 1: "Manual" };

const TABLES: Record<string, Record<number, string>> = {
  orientation: ORIENTATION,
  flash: FLASH,
  metering_mode: METERING,
  white_balance: WHITE_BALANCE,
};

/** The words for a metadata value, or the value unchanged.
 *
 * Unchanged is the important half: a code this table does not know stays the
 * number it is, rather than becoming "Unknown" and claiming the file said
 * something it did not. */
export function decodeMeta(name: string | null | undefined,
                           value: string): string {
  const table = name ? TABLES[name] : undefined;
  if (!table) return value;
  // `Number("")` is 0, and 0 is a real code in three of these tables — so an
  // empty value decoded as "Did not fire", the app answering a question the
  // file never answered. Blank has to be rejected before the conversion.
  if (!value.trim()) return value;
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  const word = table[n];
  if (word) return word;
  // An unnamed FLASH code still says the one thing its low bit means, which is
  // the question anybody is actually asking of it.
  if (name === "flash" && Number.isInteger(n)) {
    return (n & 1) === 1 ? "Fired" : "Did not fire";
  }
  return value;
}

/** Whether this metadata name is one of the coded ones. */
export function hasMetaEnum(name: string | null | undefined): boolean {
  return !!name && name in TABLES;
}

/** The choices for a coded name, lowest code first — what the query builder
 *  puts in its value dropdown.
 *
 *  `value` is the STRING of the number, because that is what the condition
 *  carries and what the query string is serialized from; only `label` is
 *  words. A caller must still render a value that is NOT in this list (a code
 *  this table does not name, or one a query written elsewhere carries), the
 *  same rule the training editor's unsupported options follow — a `<select>`
 *  with no matching option silently shows the wrong one. */
export function metaEnumOptions(
  name: string | null | undefined,
): { value: string; label: string }[] {
  const table = name ? TABLES[name] : undefined;
  if (!table) return [];
  return Object.keys(table)
    .map(Number)
    .sort((a, b) => a - b)
    .map((n) => ({ value: String(n), label: table[n] }));
}

/** THE THREE RECORD GLYPHS — a subject, a place, an event — wherever the
 *  three sit together (the row marks, the editors' sections, the sidebar
 *  rows, the filter, the `?` popover). `person` is the outline bust at the
 *  same stroke as the pin and the calendar (`face` is the filled one and
 *  reads heavier; owner 2026-09). In `shared/` so `query/` may read it. */
export const RECORD_ICON = { subject: "person", place: "location_on", event: "event" } as const;
export type RecordIconKind = keyof typeof RECORD_ICON;
