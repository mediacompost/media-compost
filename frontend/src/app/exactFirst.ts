// AN EXACT MATCH COMES FIRST, whatever the list is sorted by.
//
// Searching a 250,000-tag library for `a` and reading past `aardvark`,
// `abandoned`, `abs` to find the tag actually called `a` is the list making
// you check every row for the one you asked for by name. The autocomplete
// has always done this (`_merged_rows`' sort key leads with it); the Tags
// tab's lists sort five different ways in four different places, so the
// hoist is a pass over the sorted rows rather than a term in each key.
//
// STABLE, and the sort's own order is otherwise untouched: this only moves
// the rows that match exactly to the front, in the order they were already
// in. A row can match exactly on any of the names it is FOUND by — a
// subject's display name and its tag are both the row — so the caller says
// what to compare.

/** `rows`, with the ones whose name matches `q` exactly moved to the front.
 *
 *  `q` is compared case-insensitively and trimmed; an empty one is no
 *  search and the rows come back untouched (the same array, so a memo that
 *  depends on it is not invalidated for nothing). */
export function exactFirst<T>(
  rows: T[], q: string, namesOf: (row: T) => Array<string | null | undefined>,
): T[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return rows;
  const hit: T[] = [];
  const rest: T[] = [];
  for (const row of rows) {
    const names = namesOf(row);
    (names.some((n) => (n ?? "").toLowerCase() === needle) ? hit : rest).push(row);
  }
  return hit.length ? [...hit, ...rest] : rows;
}
