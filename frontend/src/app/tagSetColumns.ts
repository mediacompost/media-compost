/** WHAT A COLUMN OF THE TAGS TAB'S LIST IS — for either tag set.
 *
 *  The library's list and an imported set's are ONE list (owner 2026-09).
 *  They hold the same kind of thing — a name, what it is called besides,
 *  what it means, what it entails, what KIND of thing it is and where it is
 *  filed — and were two components with two row renderers, two toolbars and
 *  two ideas of what a count column is, which is the drift one list exists
 *  to end.
 *
 *  What genuinely differs is the NUMBERS. A library row says how many
 *  pictures carry the tag, three ways; an imported set's row says what its
 *  file claimed the name was worth and what this library has under it. So
 *  the columns are a TABLE, the wire answers `TagIndex.columns` with the
 *  keys of the tag set it is showing, and every sort, every range filter
 *  and every cell speaks those keys.
 *
 *  Pure: no React, no fetching. `tagSetColumns.test.ts` holds it.
 */

/** A NUMERIC column of the list. */
export interface TagSetColumn {
  /** The key in `TagIndex.numbers` / `TagRow.numbers`, and the name of the
   *  sort. What the server calls it. */
  key: string;
  /** The heading, in English — the caller translates it. */
  label: string;
  /** The track's width, in px. */
  width: number;
  /** What the figure is drawn in. */
  color: string;
  /** A press on the figure narrows the LIBRARY to the items it counts —
   *  which only a column that counts pictures can offer. */
  press?: "positive" | "negative";
  /** Drawn only where some row has a figure: a column of blanks says
   *  nothing, and these are narrow, so its absence is what gives the name
   *  its room. */
  onlyWhenUsed?: boolean;
}

/** THE LIBRARY'S OWN: how many pictures carry the tag, three ways. */
export const LIBRARY_COLUMNS: TagSetColumn[] = [
  { key: "positive", label: "Positive", width: 88, color: "var(--green)",
    press: "positive" },
  // How much of the positive count nobody assigned — implied by another
  // tag, inherited from a group, or carried by a sequence member. Its own
  // column: a number among numbers, sortable and readable down the page;
  // in brackets beside the positive one it was neither.
  { key: "implicit", label: "Implicit", width: 88, color: "var(--muted)",
    onlyWhenUsed: true },
  { key: "negative", label: "Negative", width: 88, color: "var(--red)",
    press: "negative" },
];

/** AN IMPORTED SET'S: what this library has under the name, and what the
 *  file claimed. Neither counts anything of the SET's, because a set holds
 *  no pictures — it is advice about names. */
export const SET_COLUMNS: TagSetColumn[] = [
  { key: "library", label: "Library", width: 84, color: "var(--text)" },
  { key: "count", label: "Count", width: 84, color: "var(--muted-3)" },
];

/** The columns of the tag set being shown — the library's own when no
 *  set is picked. */
export function columnsFor(setId: number | null): TagSetColumn[] {
  return setId == null ? LIBRARY_COLUMNS : SET_COLUMNS;
}

/** THE COLUMNS THIS LIST ACTUALLY DRAWS: `columnsFor` less the ones no row
 *  has a figure in. */
export function shownColumns(cols: TagSetColumn[],
                             rows: readonly { numbers?: Record<string, number | null> }[]
                             ): TagSetColumn[] {
  return cols.filter((c) => !c.onlyWhenUsed
                     || rows.some((r) => (r.numbers?.[c.key] ?? 0) > 0));
}

/** The grid template for a row: the name, an optional CATEGORY track, then
 *  one track per numeric column.
 *
 *  THE CHECKBOX TRACK LEADS (owner 2026-09, twice: it went when the rows
 *  started selecting by click, ⌘-click, shift and paint like every other
 *  list here, and came back because a list of a hundred thousand names
 *  needs a "select all" a person can SEE — the header's box — and a row's
 *  box is the one gesture that adds a row without disturbing the run
 *  already picked). `CHECK_W` is the track; the links list spells the same
 *  width in its own template.
 *
 *  The category track is `minmax(0, …)` so IT is what gives on a narrow
 *  window — a path is a hint, the name is the row — and the name track is
 *  never narrower than its own content asked for. */
export const CHECK_W = 26;

export function gridTemplate(cols: TagSetColumn[], opts: {
  category?: number | null; tagMin?: number } = {}): string {
  return [`${CHECK_W}px`,
          `minmax(${opts.tagMin ? `${opts.tagMin}px` : "0"}, 2fr)`,
          ...(opts.category ? [`minmax(0, ${opts.category}px)`] : []),
          ...cols.map((c) => `${c.width}px`)].join(" ");
}
