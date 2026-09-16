/** Making up a tag name that is free.
 *
 * A subject, a place and an event each derive a slug from what they are called,
 * and two people called Maria, two cafés on the same street and two conventions
 * in the same city all derive the same one. The record is allowed to repeat —
 * a display name is not an identity — but the TAG is what everything else keys
 * off, so it cannot.
 *
 * So an INVENTED slug is uniquified by counting up (`maria`, `maria_2`,
 * `maria_3`), the same rule `subjects.free_slug` follows on the server. A slug
 * somebody TYPES is never touched: they asked for that one, and quietly saving
 * something else is worse than refusing.
 *
 * Pure and dependency-free so `node --test` can exercise it.
 */

/** `base`, or `base_2` / `base_3`… when it is taken. */
export function freeSlug(base: string, taken: Iterable<string>): string {
  if (!base) return "";
  const used = new Set<string>();
  for (const t of taken) used.add(t.toLowerCase());
  if (!used.has(base.toLowerCase())) return base;
  // From 2: the first one has no number, so the second is "_2", which reads as
  // the second rather than as an index.
  for (let n = 2; n < 1000; n += 1) {
    const next = `${base}_${n}`;
    if (!used.has(next.toLowerCase())) return next;
  }
  return base;
}

/** Whether a typed slug already names something. Case-insensitive, like the
 *  suggestion above and like the server's own lookup. */
export function slugTaken(slug: string, taken: Iterable<string>,
                          except = ""): boolean {
  const want = slug.trim().toLowerCase();
  if (!want || want === except.trim().toLowerCase()) return false;
  for (const t of taken) if (t.toLowerCase() === want) return true;
  return false;
}

/** A tag name as a display name would be written: lowercase, underscores.
 *  The backend does the same; deriving it here is what keeps the slug from
 *  being a surprise. (It was a private copy in each of the three record
 *  overlays.) */
export function slugifyName(name: string): string {
  return name.trim().toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, "_").replace(/^_|_$/g, "");
}

/** "Traveler (Genshin Impact)" → name "Traveler", comment "Genshin Impact".
 *
 *  The booru convention writes the disambiguator in trailing brackets, and
 *  this app's own field for "what tells them apart" is the COMMENT — so a
 *  bracketed string typed into an add-a-subject/place/event field lands as
 *  the two fields it means. Only a TRAILING bracket splits (a bracket in the
 *  middle is part of the name), and a string without one comes back whole.
 */
export function splitBracketed(typed: string): { name: string; comment: string } {
  const m = /^(.*\S)\s*\(([^()]+)\)$/.exec(typed.trim());
  if (!m) return { name: typed.trim(), comment: "" };
  return { name: m[1].trim(), comment: m[2].trim() };
}

/** The slug such a split derives: `traveler_(genshin_impact)` — the comment
 *  in brackets, booru-style, so the tag still says which one it is. */
export function bracketSlug(name: string, comment: string): string {
  const base = slugifyName(name);
  if (!base) return "";
  const c = slugifyName(comment);
  return c ? `${base}_(${c})` : base;
}
