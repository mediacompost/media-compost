/**
 * FIND AND REPLACE over a plain string — the arithmetic behind the caption
 * editor's ⌘F bar, with no DOM in it.
 *
 * Pure, so `node --test` states the whole answer space: an empty needle, a
 * needle that overlaps itself, a replacement that contains the needle, and
 * what happens to the caret afterwards are all things a person will do
 * within a minute of finding the bar, and none of them is obvious enough to
 * leave to inspection.
 *
 * PLAIN TEXT, never a regex. A caption is prose somebody typed, and the
 * characters a regex owns — `.`, `(`, `?`, `*` — are ordinary punctuation in
 * it, so the one thing a search over captions must not do is treat them as
 * syntax.
 */

/** One match: where it starts, and how long it is. */
export interface Match {
  start: number;
  end: number;
}

/**
 * Every occurrence of `needle` in `text`, left to right and NON-OVERLAPPING.
 *
 * Non-overlapping is what makes "replace all" and "next match" agree: with
 * overlaps, `aa` in `aaa` finds two matches and replacing both would write
 * over the same characters twice. Empty needle finds nothing — there is no
 * useful answer, and "a match at every position" makes every other function
 * here nonsense.
 */
export function findMatches(text: string, needle: string,
                            caseSensitive = false): Match[] {
  if (!needle) return [];
  const hay = caseSensitive ? text : text.toLowerCase();
  const pin = caseSensitive ? needle : needle.toLowerCase();
  const out: Match[] = [];
  let at = 0;
  for (;;) {
    const i = hay.indexOf(pin, at);
    if (i < 0) return out;
    out.push({ start: i, end: i + pin.length });
    at = i + pin.length;          // non-overlapping
  }
}

/** Which match the caret is in or before — what "find next" starts from. */
export function matchAt(matches: Match[], caret: number): number {
  for (let i = 0; i < matches.length; i++) {
    if (matches[i].end > caret) return i;
  }
  return matches.length ? 0 : -1;   // past the last one wraps to the first
}

/** Step through the matches, WRAPPING at both ends — a search bar that
 *  stopped at the last match would need a "start over" nobody wants. */
export function stepMatch(count: number, current: number, by: 1 | -1): number {
  if (count <= 0) return -1;
  return ((current + by) % count + count) % count;
}

/** `text` with match `index` replaced, and where the caret lands after it.
 *
 *  The caret goes to the END of what was written, so typing continues after
 *  the replacement rather than inside it. Out-of-range index is a no-op,
 *  which is what a stale click after the text changed underneath amounts to.
 */
export function replaceOne(text: string, matches: Match[], index: number,
                           by: string): { text: string; caret: number } {
  const m = matches[index];
  if (!m) return { text, caret: 0 };
  return {
    text: text.slice(0, m.start) + by + text.slice(m.end),
    caret: m.start + by.length,
  };
}

/**
 * `text` with every match replaced, in ONE pass from the found positions.
 *
 * Not a loop of `replaceOne`, and not `String.replaceAll`: replacing left to
 * right shifts every later match, and re-searching after each replacement
 * finds the replacement itself when it contains the needle — `a` → `aa`
 * would never terminate. The matches are found once and spliced together,
 * so what is replaced is exactly what was highlighted.
 */
export function replaceAll(text: string, needle: string, by: string,
                           caseSensitive = false): string {
  const matches = findMatches(text, needle, caseSensitive);
  if (!matches.length) return text;
  const parts: string[] = [];
  let at = 0;
  for (const m of matches) {
    parts.push(text.slice(at, m.start), by);
    at = m.end;
  }
  parts.push(text.slice(at));
  return parts.join("");
}

/**
 * The text split into the runs a highlight layer draws: plain stretches and
 * matched ones, in order, with the matched runs numbered so the CURRENT one
 * can be drawn differently.
 *
 * A `<textarea>` cannot style a range of its own text, so the highlight is a
 * div behind it holding exactly the same string — which means this has to
 * return the WHOLE text, gaps included, or the two would not line up.
 */
export interface Run {
  text: string;
  /** The match's index, or -1 for the stretches between them. */
  match: number;
}

export function highlightRuns(text: string, matches: Match[]): Run[] {
  const out: Run[] = [];
  let at = 0;
  matches.forEach((m, i) => {
    if (m.start > at) out.push({ text: text.slice(at, m.start), match: -1 });
    out.push({ text: text.slice(m.start, m.end), match: i });
    at = m.end;
  });
  if (at < text.length) out.push({ text: text.slice(at), match: -1 });
  return out;
}
