// WHAT THE LIBRARY GRID STANDS DOWN FOR.
//
// The grid stays mounted under every full-window overlay — deliberately, so
// a page turn keeps its scroll and its selection — which means every observer
// down there is still live, and every edit made above it invalidates its way
// through all of them. Measured once on ONE tag added in the item window: six
// `POST /api/items/query` (the grid's pages, invisible), six
// `/api/items/facets` (the sidebar's badges, invisible) and three
// `/api/library/stats`. Nobody is looking at any of it.
//
// A TAG BATCH SESSION MAKES AN EDIT PER KEYPRESS, so the invisible grid
// re-paged as fast as somebody could answer cards — and the page query is a
// gate of two slots that refuses with 503 once the queue behind it is deep
// (`routers/items._PAGE_QUERY_SLOTS`). That is where "a lot of 503s during a
// tag batch session" came from: not a slow library, a grid nobody could see
// asking for pages nobody had asked for.
//
// Covered queries simply do not run. React Query keeps their data and marks
// it stale; closing the overlay refetches once, which is the sweep those
// edits earned — one, rather than one per edit.

/** Only the fields the rule reads, so a caller can be a store or a test. */
export interface CoverState {
  editorTabs: unknown[];
  /** The tag batch (`TagSortOverlay`), the tag grid, and a rating session:
   *  each fills the window with its own feed and its own queries. */
  tagSortOpen: boolean;
  tagGridOpen: boolean;
  rateRankingId: number | null;
  /** The modal writes: they dim the window, act on a selection the grid
   *  already holds, and bump the library when they close. */
  quickTagOpen: boolean;
  quickCaptionOpen: boolean;
}

/** Is the library grid hidden behind something, and therefore not worth
 *  fetching for?
 *
 *  QUICK LOOK IS NOT ONE OF THEM, deliberately: its arrows STEP THE GRID
 *  (`QuickLook.step` walks the loaded pages), so a page it has not fetched
 *  is a step that goes nowhere. */
export function coveredByWindow(s: CoverState): boolean {
  return s.editorTabs.length > 0
    || s.tagSortOpen || s.tagGridOpen || s.rateRankingId != null
    || s.quickTagOpen || s.quickCaptionOpen;
}
