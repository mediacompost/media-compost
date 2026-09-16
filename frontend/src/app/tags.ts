// Tag-name helpers, and the NAMESPACE a colon reads out of a name.
//
// A namespace is not a thing: there is no field and no table, only the text
// before the first colon of an ordinary tag name. `costume:tiger` and
// `costume:dog` are two tags that happen to share a prefix, and search,
// facets, counts, implications and aliases all carry on knowing nothing about
// it. The lowercase `something:` space is free for this because the query
// grammar matches ITS keywords uppercase and case-sensitively (`PLACE:`,
// `SUBJECT:`) — that was the point of shouting them.
//
// Mirrors `media_compost/tagname.py`, the way `subjects/when.ts` mirrors
// `partialdate.py`: both sides pure, both unit-tested, one definition of what
// a tag name may look like.

const SEP = ":";

// THE FIELD RULES LIVE IN `shared/tagName.ts` — the query builder (which
// may not import `app/`) types tag names too, and one definition of what a
// field does per keystroke and at commit is the point. Re-exported here so
// the app's many importers keep their spelling.
export {
  sanitizeTagInput, normalizeTagName, tagFieldInput, tagFieldName,
  sanitizeLinkTagInput,
} from "../shared/tagName.ts";

/** The part before the first colon, or "" for a tag without one.
 *
 *  Total on purpose: a library restored from a sidecar written before these
 *  rules can hold anything, and `a:b:c` simply reads as namespace `a`. Case is
 *  preserved because tag names are, so `Costume:` and `costume:` are two
 *  namespaces — folding them together here would be this module deciding
 *  something the names do not say.
 *
 *  Nothing in the library READS a namespace today: it is a naming convention
 *  that `normalize` protects, and the lists that grouped by it (the tag
 *  autocomplete, the Tags tab's filter) were both taken out again. This is
 *  kept as the definition of what the colon rule is for. */
/** A ROW'S NUMBER IN ONE OF ITS TAG SET'S COLUMNS (`TagIndex.columns`).
 *
 *  The library counts pictures three ways — `positive`, `implicit`,
 *  `negative` — and an imported set carries `library` and `count`. One list
 *  draws whichever pair belongs to what it is showing, so a row's numbers
 *  are a MAP keyed by column rather than three named fields; this is the
 *  reader for the many places that are only ever about the library, where
 *  an absent figure means the tag is on no pictures.
 */
export const tagCount = (t: { numbers?: Record<string, number | null> },
                         col = "positive"): number =>
  t.numbers?.[col] ?? 0;

export const tagNamespace = (name: string): string => {
  const i = name.indexOf(SEP);
  return i > 0 ? name.slice(0, i) : "";
};

/** The part after the first colon, or the whole name when there is none. */
export const tagBaseName = (name: string): string => {
  const i = name.indexOf(SEP);
  return i > 0 ? name.slice(i + 1) : name;
};
