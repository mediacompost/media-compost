/** Compose the CURRENT VIEW into one query string — what "Smart group from
 * this search" seeds a rule with.
 *
 * The left sidebar's filters are part of what the grid is showing, so a rule
 * seeded from the search alone quietly dropped them: rating the Images
 * category with `portrait` typed meant "portrait images", and the smart
 * group held every portrait VIDEO too. Everything the grammar can say is
 * folded in as AND terms beside the typed search:
 *
 *   - the media-kind filter → `INFO:type=image` (several → an OR group)
 *   - Untagged              → `INFO:tag_count=0`
 *   - the selected group(s) → `GROUP:Name` (several → an OR group)
 *
 * What the grammar canNOT say is left out rather than approximated —
 * Ungrouped, the Pending/Hidden/Trash views — because a rule that silently
 * means something else is worse than one missing a term. HIDE-SEQUENCED is
 * left out on purpose too, though it could be spelled: it is a browsing
 * convenience, not part of what anybody means by their search, and folding
 * it in gave a "score 8+" rule a baffling `(INFO:type=sequence|…)` clause —
 * a membership rule is about the library, not a view (the sweeper's own
 * show_hidden rule). Atoms are built the way `tree.ts`'s serializer builds
 * them (escape, then quote the whole atom when it holds whitespace), so the
 * seeded string always parses back.
 */
import { escapeName } from "../query/tree.ts";

const quoteAtom = (atom: string) => (/\s/.test(atom) ? `"${atom}"` : atom);

const orGroup = (atoms: string[]): string =>
  atoms.length === 1 ? atoms[0] : `(${atoms.join("|")})`;

export function composeViewQuery(v: {
  search: string;
  /** The checked media kinds; empty (or all three) means no filter. */
  mediaKinds: string[];
  untagged: boolean;
  /** Names of the selected groups (already resolved from ids). */
  groupNames: string[];
}): string {
  const parts: string[] = [];
  const base = v.search.trim();
  const kinds = [...new Set(v.mediaKinds)].sort();
  if (kinds.length > 0 && kinds.length < 3) {
    parts.push(orGroup(kinds.map((k) => `INFO:type=${k}`)));
  }
  if (v.untagged) parts.push("INFO:tag_count=0");
  const groups = v.groupNames.filter((n) => n.trim());
  if (groups.length > 0) {
    parts.push(orGroup(groups.map((n) => quoteAtom(`GROUP:${escapeName(n)}`))));
  }
  if (base) {
    // Beside other terms the typed search is wrapped so an `a|b` keeps its
    // own grouping; alone it stays exactly what was typed.
    parts.unshift(parts.length > 0 ? `(${base})` : base);
  }
  return parts.join(" ");
}
