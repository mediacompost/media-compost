/** The one-line tag language the quick-tag overlay takes.
 *
 * A whole edit is typed as a list of words and applied in one go, so the
 * grammar has to fit in a sentence: a bare name ADDS it, `-` in front REMOVES
 * it, and `!` says the addition is a NEGATIVE assignment ("this picture is
 * pointedly not that"). `+` may lead any addition — it says out loud what a
 * bare name already means, which is what makes `-` readable as its opposite.
 *
 * Pure, so the whole answer space is stated as tests rather than as prose.
 * The names it returns are the committed form — `tagFieldName`, the rule every
 * tag field in the app commits by, lowercase included — because what comes
 * back goes straight to an API that refuses anything else.
 */
import { tagFieldName } from "./tags.ts";

export interface QuickTagOp {
  name: string;
  /** Take it off the item, whatever sign it had. */
  remove: boolean;
  /** Assign it as a negative. Meaningless on a removal. */
  negative: boolean;
}

/** Split what was typed into words. Whitespace AND commas: a tag name can
 *  hold neither, so both read as "next tag" and nobody has to remember. */
export function quickTagTokens(text: string): string[] {
  return text.split(/[\s,]+/).filter(Boolean);
}

/** The token the caret is inside — what the autocomplete is about.
 *
 *  Returned with its bounds, so picking a suggestion can replace exactly that
 *  word and leave the rest of the line alone. A caret sitting on a separator
 *  is at the START of the next word, which is where typing would put text.
 */
export function tokenAt(text: string, caret: number):
    { start: number; end: number; word: string } {
  const at = Math.max(0, Math.min(caret, text.length));
  const sep = /[\s,]/;
  let start = at;
  while (start > 0 && !sep.test(text[start - 1])) start--;
  let end = at;
  while (end < text.length && !sep.test(text[end])) end++;
  return { start, end, word: text.slice(start, end) };
}

/** The prefix a word carries, and the name under it. `-` wins over `!`: a
 *  removal takes the tag off whatever sign it had, so `-!x` is `-x`. */
export function splitPrefix(word: string): { prefix: string; rest: string } {
  const m = word.match(/^([+-]?!?|!)/);
  const prefix = m ? m[0] : "";
  return { prefix, rest: word.slice(prefix.length) };
}

/** What a typed line asks for, in the order it was typed.
 *
 *  A word that normalizes to nothing (a lone prefix, punctuation) is dropped
 *  rather than refused: it is a half-typed word, not a mistake. The LAST
 *  mention of a name wins — typing `cat -cat` is somebody changing their mind
 *  mid-line, and applying both would be one of them silently losing.
 */
export function parseQuickTags(text: string): QuickTagOp[] {
  const out: QuickTagOp[] = [];
  for (const word of quickTagTokens(text)) {
    const op = parseQuickWord(word);
    if (!op) continue;
    const name = op.name;
    const seen = out.findIndex((o) => o.name === name);
    if (seen >= 0) out[seen] = op; else out.push(op);
  }
  return out;
}

/** ONE word's op — the rule the T field's line is parsed by, word by word,
 *  and the rule the sidebar's single-tag field reads its one word with, so
 *  `-name` and `!name` mean the same thing in both. Null for a word that
 *  normalizes to nothing, which since a trailing colon became ordinary means
 *  a word that was only its own `-`/`!` prefix. */
export function parseQuickWord(word: string): QuickTagOp | null {
  const { prefix, rest } = splitPrefix(word);
  const name = tagFieldName(rest);
  if (!name) return null;
  return {
    name,
    remove: prefix.startsWith("-"),
    negative: !prefix.startsWith("-") && prefix.includes("!"),
  };
}

/** What a suggestion row is FOR under a prefix — how the list colours its
 *  icons: green for an assignment, red for a negative one, grey and slashed
 *  for a removal. The same reading of the prefix as `parseQuickWord`. */
export type TagTone = "positive" | "negative" | "remove";

export function toneOfPrefix(prefix: string): TagTone {
  if (prefix.startsWith("-")) return "remove";
  return prefix.includes("!") ? "negative" : "positive";
}

/** The same ops as the two calls that carry them out: what to assign (with
 *  its sign) and what to take off. */
export function quickTagPlan(ops: QuickTagOp[]):
    { positive: string[]; negative: string[]; remove: string[] } {
  return {
    positive: ops.filter((o) => !o.remove && !o.negative).map((o) => o.name),
    negative: ops.filter((o) => !o.remove && o.negative).map((o) => o.name),
    remove: ops.filter((o) => o.remove).map((o) => o.name),
  };
}
