/** The shape of a tag suggestion list, and where its highlight starts — the
 *  pure half of `TagSuggestList`, so the keyboard rule is a test rather than
 *  a behaviour somebody notices.
 *
 *  THE CREATE ROW IS FIRST AND THE FIRST MATCH IS THE DEFAULT. Where the row
 *  goes and where the highlight starts are two questions: it stays at the
 *  top, because a name that has just been typed and matches nothing is the
 *  one thing that must not sit below the fold of thirty rows — but the
 *  highlight starts on the first MATCH under it (owner decision, 2026-09:
 *  it was the default for a round). Enter then completes, which is what a
 *  tag field is for, and Create is one ArrowUp away — the direction with
 *  nothing else in it, since the first match is the top of the list the
 *  arrows walk down. */

/** A row that is neither a match nor a Create — an ANSWER of its own that
 *  the list offers alongside the names.
 *
 *  The one so far is the face namer's **Unnamed**: "somebody, with no name",
 *  which is an answer to "who is this" that no name in the catalog can
 *  stand for. It belongs in the list rather than beside it, because that is
 *  where the other answers are and where the keyboard already is. */
export interface SuggestAction {
  /** What the host reads back to know which one was picked. */
  id: string;
  label: string;
  /** The quiet line under it — what picking it means. */
  hint?: string;
  icon?: string;
}

export type SuggestRow<T> =
  | { kind: "action"; action: SuggestAction }
  | { kind: "create"; name: string }
  | { kind: "match"; item: T };

/** Which rows the keyboard and the mouse may land on. A list may hold rows
 *  that are neither — the T overlay's section titles — and they are stepped
 *  OVER rather than through. Everything is selectable unless a host says
 *  otherwise. */
export type Selectable = (i: number) => boolean;

const ALL: Selectable = () => true;

/** The first selectable index from `from` walking in `dir`, or null. */
function seek(count: number, from: number, dir: 1 | -1, ok: Selectable): number | null {
  for (let i = from; i >= 0 && i < count; i += dir) if (ok(i)) return i;
  return null;
}

/** `[action?, create?, ...matches]` — the answers that are not names first,
 *  when there are any. */
export function buildSuggestRows<T>(
  matches: readonly T[], create: string | null,
  actions: readonly SuggestAction[] = [],
): SuggestRow<T>[] {
  const rows: SuggestRow<T>[] = [];
  for (const action of actions) rows.push({ kind: "action", action });
  if (create) rows.push({ kind: "create", name: create });
  for (const item of matches) rows.push({ kind: "match", item });
  return rows;
}

/** Where the highlight starts: the first selectable row that is neither an
 *  ACTION nor the Create row — those only when there is no match under
 *  them. Both are answers a person came to the field meaning to give, and
 *  neither may be what Enter does to a half-typed name. */
export function defaultHighlight<T>(
  rows: readonly SuggestRow<T>[], ok: Selectable = ALL,
): number {
  const lead = rows.findIndex((r) => r.kind === "match");
  if (lead > 0) {
    const match = seek(rows.length, lead, 1, ok);
    if (match != null) return match;
  }
  // NO MATCH: THE CREATE ROW, NEVER AN ACTION. A name typed out in full
  // that the catalog has never seen is still a name somebody typed; an
  // action is offered, never typed. Falling to the first selectable row
  // put the highlight on the ACTION — so in the face namer, typing a new
  // person's name and pressing Enter marked the cluster "somebody with no
  // name" instead of naming them, which is the opposite answer to the one
  // being given and takes the typing with it.
  const create = rows.findIndex((r) => r.kind === "create");
  if (create >= 0 && ok(create)) return create;
  return seek(rows.length, 0, 1, ok) ?? 0;
}

/** One arrow press. Clamped at both ends, never wrapping — no host has ever
 *  wrapped, and a list that jumps from its last row to Create on one more
 *  ArrowDown is a list that creates tags by accident. Rows the host calls
 *  unselectable are stepped over. */
export function stepHighlight(
  hi: number, delta: -1 | 1, count: number, ok: Selectable = ALL,
): number {
  if (count <= 0) return 0;
  const next = seek(count, hi + delta, delta, ok);
  if (next != null) return next;
  return ok(hi) ? hi : (seek(count, 0, 1, ok) ?? 0);
}

/** The effective highlight: `null` means "wherever the default is" (the
 *  state a fresh list starts in and returns to whenever its rows change), a
 *  number is clamped to the rows that exist and nudged off an unselectable
 *  one. */
export function clampHighlight<T>(
  raw: number | null, rows: readonly SuggestRow<T>[], ok: Selectable = ALL,
): number {
  if (raw == null) return defaultHighlight(rows, ok);
  const i = Math.max(0, Math.min(rows.length - 1, raw));
  if (ok(i)) return i;
  return seek(rows.length, i, 1, ok) ?? seek(rows.length, i, -1, ok) ?? 0;
}

/** How many rows a suggestion list offers — every host's cap, so a name
 *  past it is past it everywhere. Ranking happens BEFORE the cut
 *  (`app/tagRank.ts`), which is what made an existing "test" addable. */
export const SUGGEST_CAP = 30;

/** WHAT A KEY IN THE FIELD MEANS, given the list's state — the pure half
 *  of `useSuggestList`'s `input` option. Arrows step (and ask a dismissed
 *  list back), Enter picks the highlighted row while the list is up and
 *  commits the typed name when it is not, Tab picks where a host says so,
 *  and Escape is TWO-STAGE: it closes the list first (keeping the text)
 *  and cancels the field only when there was no list to close. */
export type InputKeyAction =
  | "step" | "pick" | "commitTyped" | "dismiss" | "cancel" | "none";

export function inputKeyAction(
  e: { key: string; shiftKey: boolean },
  s: { listOpen: boolean; hasRows: boolean; alsoOpen?: boolean; tabPicks?: boolean },
): InputKeyAction {
  switch (e.key) {
    case "ArrowDown": case "ArrowUp": return "step";
    case "Enter": return s.listOpen && s.hasRows ? "pick" : "commitTyped";
    case "Tab":
      return !e.shiftKey && s.tabPicks && s.listOpen && s.hasRows ? "pick" : "none";
    case "Escape": return s.listOpen || s.alsoOpen ? "dismiss" : "cancel";
    default: return "none";
  }
}
