// LINKS IN A TAG SET'S DESCRIPTION — Markdown's `[text](target)`, and the
// two kinds of target that mean something here.
//
//   [the wiki](https://…)      a WEB link, opened in a new window
//   [open_mouth](#open_mouth)  a TAG link, opened in the same popover
//
// The `#` is the ordinary "somewhere in this document" spelling, and a tag
// set IS the document: the target is an entry's name in the same set. It is
// resolved by NAME rather than by id, because that is how a set is keyed
// throughout — a set names tags the library has never heard of, and the link
// has to survive being exported and imported somewhere else.
//
// Anything else in the target position is left as PLAIN TEXT, brackets and
// all. A description is prose somebody wrote, and `[see also] (the wiki)` is
// far likelier to be a sentence than a broken link; turning it into a dead
// one would be the module guessing.
//
// Pure and tested (`descriptionLinks.test.ts`) so the auto-linker in the
// outer repo's `scripts/link_tagset_descriptions.py` and this renderer agree
// on one grammar.

export type DescSegment =
  | { kind: "text"; text: string }
  | { kind: "web"; text: string; href: string }
  | { kind: "tag"; text: string; name: string };

/** How far a balanced `(` … `)` run reaches from `open`, or -1.
 *
 *  Balanced rather than "to the first `)`", because booru tag names carry
 *  parentheses as a matter of course — `traveler_(genshin_impact)` — and a
 *  link to one is the case this exists for. */
function closingParen(s: string, open: number): number {
  let depth = 0;
  for (let i = open; i < s.length; i++) {
    if (s[i] === "(") depth++;
    else if (s[i] === ")") {
      depth--;
      if (depth === 0) return i;
    } else if (s[i] === "\n") return -1;   // a link does not span lines
  }
  return -1;
}

const WEB = /^https?:\/\/\S+$/;

/** A description as the pieces to draw. Never throws; anything it does not
 *  recognise comes back as text, so the worst case is the prose as written. */
export function parseDescription(text: string): DescSegment[] {
  const out: DescSegment[] = [];
  let plain = "";
  const flush = () => { if (plain) { out.push({ kind: "text", text: plain }); plain = ""; } };
  let i = 0;
  while (i < text.length) {
    const open = text.indexOf("[", i);
    if (open < 0) { plain += text.slice(i); break; }
    const close = text.indexOf("]", open + 1);
    if (close < 0 || text[close + 1] !== "(") {
      plain += text.slice(i, open + 1);
      i = open + 1;
      continue;
    }
    const end = closingParen(text, close + 1);
    const label = text.slice(open + 1, close);
    const target = end < 0 ? "" : text.slice(close + 2, end);
    if (end < 0 || !label || !target) {
      plain += text.slice(i, open + 1);
      i = open + 1;
      continue;
    }
    if (target.startsWith("#") && target.length > 1) {
      plain += text.slice(i, open);
      flush();
      out.push({ kind: "tag", text: label, name: target.slice(1) });
      i = end + 1;
    } else if (WEB.test(target)) {
      plain += text.slice(i, open);
      flush();
      out.push({ kind: "web", text: label, href: target });
      i = end + 1;
    } else {
      // A target this module does not know: the prose stands as written.
      plain += text.slice(i, open + 1);
      i = open + 1;
    }
  }
  flush();
  return out;
}

/** Every tag a description links to, in order, deduped — what an importer or
 *  a checker asks for. */
export function linkedTags(text: string): string[] {
  const names = parseDescription(text)
    .filter((s): s is Extract<DescSegment, { kind: "tag" }> => s.kind === "tag")
    .map((s) => s.name);
  return [...new Set(names)];
}

/** The link a linker WRITES for a tag, given the word it found. The one
 *  place the spelling lives on this side; the script mirrors it. */
export const tagLink = (label: string, name: string): string =>
  `[${label}](#${name})`;
