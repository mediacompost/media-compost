/** Ranking a tag suggestion list's matches — the pure half, shared by every
 *  tag field (`TagAutocomplete`, `CombinedTagEditor`, the T overlay) through
 *  `TagSuggestList`. There used to be a second copy (`tagSuggest.ts`, tiers of
 *  exact / prefix / substring); this one's match POSITION is a strict
 *  refinement of those tiers, so it is the one that survived.
 *
 *  The server orders what it sends the same way, but the client re-filters
 *  against the LIVE fragment (the remote rows answered the debounced one, and
 *  a static `suggestions` catalog arrives ordered by count alone), so the
 *  rule has to be applied here to be true on screen:
 *
 *  1. The EXACT name first — the tag called `ball` beats `football` however
 *     their counts compare, because the person has finished typing it.
 *  2. Then WHERE the match sits, earlier first — `abc_123` before `123_abc`
 *     for the fragment `abc`, whatever their counts: a name that starts with
 *     what was typed is what was being reached for.
 *  3. Then the order the source came in, which carries the count ranking —
 *     `Array.prototype.sort` is stable, so ties keep it.
 *
 *  Rank over ALL matches and cap afterwards — capping first cut the exact
 *  match out of a list of more popular near-misses (an existing "test" lost
 *  its slot to "contest" and "cutest", and since the name existed the Create
 *  row stood down too: no way to pick it at all).
 */

/** How many rows a suggestion list shows. It was 6, which on a catalog of
 *  any size is a keyhole; the list scrolls, so this is about how far a hand
 *  is willing to arrow rather than about what fits. */
import { SUGGEST_CAP } from "../shared/suggestRows.ts";
export { SUGGEST_CAP };

export function rankTagMatches<T extends { name: string }>(
  source: readonly T[],
  needle: string,
  existing: readonly string[] | ReadonlySet<string>,
  cap: number = SUGGEST_CAP,
  /** What the needle is matched against — the name, unless a row carries
   *  more that is worth typing towards (a place's address beside its
   *  label). The name still decides `existing`. */
  text: (item: T) => string = (item) => item.name,
): T[] {
  const n = needle.toLowerCase();
  const taken = existing instanceof Set ? existing : new Set(existing);
  // AN EMPTY NEEDLE IS THE CATALOG, in its own order, less what is taken —
  // for a field that offers its whole (small) list on focus: the group
  // adder, the meta-tag adders, the CSV dialog's mark fields. A host over a
  // catalog too big to list guards `q` itself.
  if (!n) return source.filter((s) => !taken.has(s.name)).slice(0, cap);
  const hits: { s: T; pos: number; exact: number }[] = [];
  for (const s of source) {
    if (taken.has(s.name)) continue;
    const lower = text(s).toLowerCase();
    const pos = lower.indexOf(n);
    if (pos < 0) continue;
    hits.push({ s, pos, exact: lower === n ? 0 : 1 });
  }
  hits.sort((a, b) => a.exact - b.exact || a.pos - b.pos);
  return hits.slice(0, cap).map((h) => h.s);
}
