// WHEN THE GRID MAY GO ON SHOWING THE PREVIOUS ANSWER — pure, unit-tested.
//
// The page queries are keyed `["items", filtersKey, treeKey, sort, page]` and
// keep the previous key's data as `placeholderData` while the new one loads,
// so a change swaps content in rather than flashing an empty grid. What that
// is right for is a change of QUESTION over the same set of pictures: a search
// being typed, a sort being flipped. The items on screen are then a stale
// answer to a live question, which reads as exactly what it is.
//
// It is NOT right across a change of SCOPE, and the Trash is where that gets
// reported. `filtersKey` holds the scope — trash / hidden / pending / the
// selected groups / a sequence — and across one of those the previous items
// are not a stale answer, they are somebody else's answer. Shown under the
// Trash heading they say the library has thrown those pictures away.
//
// Which is precisely how it was found: an import touches `last_imported_at`
// on every item it lands on (a re-imported duplicate floats to the top of the
// default Imported ↓ order), so the library's page 1 was suddenly *led* by the
// items the import had just matched. Opening the Trash then showed those items
// — the reporter's two pictures — until the trash query answered, and until it
// did there was nothing to say they were not really in there. A reload cleared
// them because a cold query has no previous data to stand in for it.
//
// The window is normally short. It is not short after an import (the writer
// holds the database, so the read queues), and it does not close at all if the
// query fails — React Query keeps showing the placeholder in an error state.

/** May a page slot keep `prev`, given the key it was fetched under?
 *
 *  Two things have to hold: the same PAGE NUMBER (a slot re-aimed by
 *  scrolling must show placeholders, not another page's items at these
 *  indices), and the same SCOPE (see above).
 *
 *  `page` lives at index 4 of the key and `filtersKey` at index 1. Both are
 *  read positionally because that is how the key is built; a key of another
 *  shape simply fails the test and the slot goes empty, which is the safe
 *  direction.
 */
export function keepsPreviousPage(
  prevKey: readonly unknown[] | undefined,
  filtersKey: string,
  page: number,
): boolean {
  if (!prevKey) return false;
  return prevKey[4] === page && prevKey[1] === filtersKey;
}

/** The same rule for the grouped layout's runs, which carry no page number:
 *  the sections of one scope must not be drawn over another's items. */
export function keepsPreviousRuns(
  prevKey: readonly unknown[] | undefined,
  filtersKey: string,
): boolean {
  return !!prevKey && prevKey[1] === filtersKey;
}

/** THE PREVIEW'S OWN VERSION OF THE RULE, whose "same scope" is "the picture
 *  is already on screen".
 *
 *  Quick Look's detail query is keyed `["item", id]` and holds the previous
 *  item's detail while the next one loads — which is what keeps a walk
 *  through a sequence from flashing the "No preview" box between two pages,
 *  and what the frame's own double buffer is built around. That is right
 *  while the held-over picture is the one being LOOKED at: it is on screen,
 *  and it stays there one beat longer.
 *
 *  It is not right across an OPEN. The preview closes, another picture is
 *  pointed at, and the first thing the overlay drew was the last item it had
 *  been shown — a picture from a previous visit, held for as long as the
 *  fetch took, over the card the person had just pressed. The tag grid is
 *  where that is worst: its cards are rarely in the library page underneath,
 *  so EVERY open goes through this fetch.
 *
 *  So the caller says which item is on screen — null while the preview is
 *  closed, and only advanced once the frame is really drawing that item —
 *  and nothing else may stand in. `prevKey[1]` is the id the previous data
 *  was fetched under, read positionally like the keys above.
 */
export function keepsPreviousPreview(
  prevKey: readonly unknown[] | undefined,
  onScreenId: number | null,
): boolean {
  return !!prevKey && onScreenId != null && prevKey[1] === onScreenId;
}
