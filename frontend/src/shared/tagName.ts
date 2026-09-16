/** WHAT A TAG FIELD DOES TO WHAT IS TYPED — per keystroke, and at commit.
 *
 *  In `shared/` because the query builder types tag names too and may not
 *  import `app/` (`boundaries.test.ts`); `app/tags.ts` re-exports these for
 *  the app's own importers. Mirrors `media_compost/tagname.py`: both sides
 *  pure, both unit-tested, one definition of what a tag name may look like.
 */

/** What a field does on every KEYSTROKE.
 *
 *  Whitespace collapses to underscores (the rule that has always applied).
 *  INTERIOR colons are kept, however many: `costume:hat:straw` is a name
 *  somebody typed, and turning its second colon into an underscore was the
 *  app quietly storing something else (see `tagname.py:normalize`). A LEADING
 *  colon is kept too — `:o`, `:d` and `:3` are the booru tag set's
 *  most-used expression tags, and dropping the colon turned each into a
 *  letter (a name so spelled has no namespace; `tagNamespace` answers "").
 *
 *  A TRAILING colon is kept as well, and stays kept at commit: Danbooru
 *  spells three expression tags `d:`, `3:` and `c:`, and a rule that ate the
 *  colon turned each into a bare letter the app had decided it meant. The
 *  price is that a half-typed `costume:` now IS a name — a field offers to
 *  create exactly it (see `TagAutocomplete`). */
export const sanitizeTagInput = (s: string): string =>
  s.replace(/\s+/g, "_");

/** What a field sends when it COMMITS — `sanitizeTagInput` over the trimmed
 *  string. Nothing else: a colon is an ordinary character wherever it stands.
 *  Kept as its own name (rather than folded into `sanitizeTagInput`) because
 *  the two answer different questions — one runs per keystroke on what is
 *  shown, the other once on what is sent — and only this one trims. Mirrors
 *  the backend exactly, so a name this produced can never be one the API
 *  refuses. */
export const normalizeTagName = (s: string): string =>
  sanitizeTagInput(s.trim());

/** What a tag FIELD shows as you type, and what it sends when it commits.
 *
 *  The two rules above plus lowercase. That is a FIELD convention rather than
 *  a storage rule — the API accepts mixed case, because an import or a library
 *  older than any of this can hold it, and `normalize` on the backend is a
 *  mirror of `normalizeTagName` and stays one. But every tag this app creates
 *  from a typed name is lowercase, and two spellings of one word are two rows
 *  nobody meant to make.
 *
 *  Meta-tag names take exactly the same shape, so `sanitizeLinkTagInput` is
 *  this and not a second definition of it. */
export const tagFieldInput = (s: string): string =>
  sanitizeTagInput(s).toLowerCase();
export const tagFieldName = (s: string): string =>
  normalizeTagName(s).toLowerCase();

export const sanitizeLinkTagInput = tagFieldInput;
