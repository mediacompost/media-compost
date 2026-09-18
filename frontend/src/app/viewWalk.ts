// WALKING A SEQUENCE VIEW IS WALKING OCCURRENCES, NOT ITEMS.
//
// The grid draws one card per POSITION, so a book's repeated blank page is
// several cards of one item — and an item id therefore cannot say where a
// walk IS. `indexOf` over the view's ids answers the FIRST copy and a Map
// keyed by id answers the LAST, which is how → came to step 0, 1, 2, 31: at
// the blank page it asked "where is item X" and got the position of its
// other appearance, then moved one on from there.
//
// So the walk's position is the occurrence — the membership row the card was
// drawn from — and an id lookup is only the fallback for a view that has no
// occurrences (every view but a sequence's own).

/** Where the walk is: the occurrence the selection names, else the item.
 *
 * `members[i]` is the membership row behind `ids[i]` — null outside a
 * sequence view, where an item appears once and the id is answer enough.
 */
export function occurrenceIndex(
  ids: readonly number[],
  members: readonly (number | null | undefined)[],
  itemId: number | null,
  memberId: number | null,
): number {
  if (memberId != null) {
    const at = members.indexOf(memberId);
    if (at !== -1) return at;
  }
  return itemId == null ? -1 : ids.indexOf(itemId);
}

/** One step from `at`, to the next occurrence showing a DIFFERENT picture;
 *  -1 off either end.
 *
 * The step is by occurrence, so the walk keeps the view's own order — and it
 * skips a RUN of the same picture, because a book's three blank pages in a
 * row are one picture and a key that redraws it reads as a key that did
 * nothing. A copy further along the book is a place of its own and is
 * stopped at like any other card.
 */
export function nextDistinctIndex(
  ids: readonly number[], at: number, delta: number,
): number {
  if (delta === 0 || at < 0 || at >= ids.length) return -1;
  const here = ids[at];
  for (let i = at + delta; i >= 0 && i < ids.length; i += delta) {
    if (ids[i] !== here) return i;
  }
  return -1;
}
