/** Which tag set's description a person sees FIRST — the pure half of the
 *  `?` popover's switcher.
 *
 *  Several enabled sets may describe one tag (a set made from the Booru
 *  template, an imported dump, one typed by hand), and the popover shows one at a time with
 *  a strip to switch. Which one comes first is a per-user PREFERENCE, kept
 *  as an ordered list of set keys (`/api/settings/tag-set-order`): the set
 *  somebody switched to last moves to the front, so "I trust Danbooru's
 *  wording over the shipped one" is one decision that then holds for every
 *  tag. Keys the preference does not name keep the order the server gave
 *  (the sets' global position). */

export interface Described { key: string }

/** `cands` in preference order: the preferred keys first, in the order the
 *  preference lists them, then everything else in the order given. */
export function orderTexts<T extends Described>(
  cands: readonly T[], pref: readonly string[],
): T[] {
  const rank = new Map(pref.map((k, i) => [k, i]));
  return cands
    .map((c, i) => ({ c, i }))
    .sort((a, b) => {
      const ra = rank.get(a.c.key), rb = rank.get(b.c.key);
      if (ra != null && rb != null) return ra - rb || a.i - b.i;
      if (ra != null) return -1;
      if (rb != null) return 1;
      return a.i - b.i;
    })
    .map((x) => x.c);
}

/** The preference after picking `key`: it moves to the front, the rest keep
 *  their order. Pure, so a click is exactly one list edit. */
export function moveToFront(pref: readonly string[], key: string): string[] {
  return [key, ...pref.filter((k) => k !== key)];
}
