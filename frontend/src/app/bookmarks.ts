/**
 * BOOKMARKS: pictures worth coming back to.
 *
 * A mark is an ITEM AND NOTHING ELSE (owner 2026-09) — a picture is marked
 * or it is not. It carried the view it was made in for a day, back when
 * picking one put that view back; the dropdown lists only the marks the
 * view ON SCREEN holds, so there was never a view to restore and the stored
 * copy could only go stale. Everything else a row shows — the name, the
 * thumbnail — is read live from the item, which is also how a renamed
 * picture stops being listed under its old name.
 *
 * They live in the browser, beside the other `mc.` preferences: a bookmark
 * is a place somebody is in the middle of working through, not a fact about
 * the picture that the library should carry to another machine.
 */

/** What was stored, with anything unreadable dropped rather than thrown: a
 *  half-written list is still a list of the marks that survived. */
export function parseBookmarks(raw: string | null): number[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    if (!Array.isArray(v)) return [];
    const out: number[] = [];
    for (const id of v) {
      if (typeof id !== "number" || !Number.isInteger(id) || id <= 0) continue;
      if (!out.includes(id)) out.push(id);
    }
    return out;
  } catch {
    return [];
  }
}

export const serializeBookmarks = (ids: number[]): string => JSON.stringify(ids);

export const isBookmarked = (ids: number[], itemId: number): boolean =>
  ids.includes(itemId);

/** Mark the item, or take its mark off — what the one menu row does. NEWEST
 *  FIRST, because a mark just made is the one being looked for. */
export function toggleBookmark(ids: number[], itemId: number): number[] {
  const without = ids.filter((id) => id !== itemId);
  return without.length === ids.length ? [itemId, ...without] : without;
}

export const removeBookmark = (ids: number[], itemId: number): number[] =>
  ids.filter((id) => id !== itemId);
