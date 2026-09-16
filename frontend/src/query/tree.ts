/**
 * The search condition tree: types, plus parse (text -> tree) and serialize
 * (tree -> text). The frontend is the *only* parser — the backend receives the
 * structured tree and evaluates it, so this module is the single source of truth
 * for the query grammar and the two-way binding between the search bar and the
 * visual builder.
 *
 * **Keywords are UPPERCASE, and only uppercase.** `PLACE:`, `INFO:`, `TAG:`,
 * `SUBJECT:`, `EVENT:`, `GROUP:`, `GROUPONLY:`, `CAPTION:`, `LINK:`,
 * `LINKEDBY:` — anything in lower or mixed case is a TAG NAME, always. A tag
 * really can be called `place:berlin` (the Tagging settings namespace
 * subjects, places and events in exactly that shape by default), so a
 * case-insensitive keyword would swallow the tags the app itself invents.
 * Shouting the keywords hands the entire lowercase space back to tag names.
 *
 * Grammar (frontend serialization only):
 *   - Tag:   `name` (has, positive); `!name` (has-not); `-name` (negative
 *            assignment); `!-name` (has-not negative). `TAG:noflip,!draft`
 *            asks the same question of ANY tag the tag set marks that way
 *            (the `CAPTION:` shape), with the same four prefixes.
 *   - Info:  `INFO:name op value`  (op ∈ >= <= != !~ > < = ~). Names/values with
 *            spaces are wrapped in double quotes: `"INFO:Lens Model~canon"`.
 *   - Link:  `LINK:` / `LINKEDBY:` with `!` prefix for the negative directions,
 *            and a comma list of tags after the colon; a `!`-prefixed tag is
 *            *excluded*. E.g. `LINK:crop,!edit`.
 *   - Group: `GROUP:Name` (in that group or any group under it — what the
 *            sidebar shows for it) / `!GROUP:Name` (not in one) /
 *            `GROUPONLY:Name` (filed in the group itself, not in a group
 *            under it) / `!GROUPONLY:Name`. Matched by PATH,
 *            case-insensitively; quoted as a whole atom when the name
 *            contains spaces: `"GROUP:My Folder"`.
 *   - Place: `PLACE:value` (the address contains) / `PLACE=value` (is).
 *   - Subject: `SUBJECT:name[@year][#age]`.  Event: `EVENT:name[@year]`.
 *   - Caption: `CAPTION:tags`.
 *   - Bool:  whitespace = AND, `|` = OR, `( )` group, `!( … )` = None/negation.
 */

export type Sign = "pos" | "neg";
export type MetaType = "numeric" | "text" | "date";
export type LinkDir = "has" | "hasnot" | "linkedby" | "notlinkedby";
export type BoolOp = "and" | "or";

export interface TagCond {
  type: "tag";
  name: string;
  have: boolean; // false = "has not"
  sign: Sign;
  /** A tag described by what the TAG SET says about it rather than by its
   *  name: with any of these, `name` is not asked about at all and the
   *  condition means "a tag marked this way is on the picture". The
   *  required/excluded shape `CapCond` and `LinkCond` already use.
   *
   *  OPTIONAL, and left off entirely for an ordinary tag condition — which is
   *  what keeps every existing corpus row (and every saved search) exactly
   *  what it was. */
  meta_tags?: LinkTagRef[];
}
export interface LinkTagRef {
  name: string;
  exclude: boolean;
}
export interface LinkCond {
  type: "link";
  direction: LinkDir;
  link_tags: LinkTagRef[];
}
// Captions, optionally narrowed by meta tags — the caption twin of LinkCond
// (same tag namespace, same required/excluded semantics).
export type CapMode = "has" | "hasnot";
// WHICH list is being asked about: descriptions of the picture, or the
// instructions saying how it was made from others. One condition with a kind
// rather than two condition types — they are one row type carrying the same
// meta tags. The default is "caption", so a query written before instructions
// existed still means what it meant.
export type CapKind = "caption" | "instruction";
export interface CapCond {
  type: "caption";
  mode: CapMode;
  caption_kind: CapKind;
  caption_tags: LinkTagRef[];
}
export interface MetaCond {
  type: "meta";
  name: string;
  mtype: MetaType;
  op: string;
  value: number | string;
  // Half-width of the window a numeric "=" / "!=" accepts around `value`.
  // Computed here (see numTolerance) because precision is a property of the
  // typed text and a JSON number has already lost it — the backend only ever
  // sees the finished window. Absent/0 = compare exactly.
  tol?: number;
}
// Group membership by group path ("ingroup" because the boolean node already
// owns the "group" type tag). Case-insensitive. has = in that group or in
// any group under it, what selecting it in the sidebar shows; hasnot = its
// negation; only = filed in that group itself (`GROUPONLY:`); notonly = its
// negation.
export type GrpMode = "has" | "hasnot" | "only" | "notonly";
export interface GrpCond {
  type: "ingroup";
  name: string;
  mode: GrpMode;
}
// A subject on the item, optionally narrowed by the STATE of that assignment.
// A subject IS a tag, so "has this subject" is already a tag condition — this
// exists for what a tag cannot say: the year of the picture, or how old its
// subject was in it. Dates are partial (YYYYMMDD with zeros; see
// subjects/when.ts), ages are whole years.
export interface SubjCond {
  type: "subject";
  name: string;        // the identity tag's name; "" = any subject
  have: boolean;       // false = "has not"
  date_from?: number | null;
  date_to?: number | null;
  age_from?: number | null;
  age_to?: number | null;
}
// WHERE THE ITEM IS: a substring of the ADDRESS of a place it is at. One
// field, where there were eleven — the typed components went first, then the
// country, then the identity TAG, which was the tag search wearing a second
// spelling (a place IS a tag). Containment needs nothing here: a place inside
// another implies it, so an item tagged only `shibuya_crossing` answers
// "Tokyo" because it genuinely carries `tokyo`.
// An event on the item, optionally narrowed by when the EVENT was — not when
// the assignment says the picture is from, which is what `subject:` reads.
// Dates are partial (YYYYMMDD with zeros, see subjects/when.ts).
export interface EventCond {
  type: "event";
  name: string;        // the identity tag's name; "" = any event
  have: boolean;       // false = "has not"
  date_from?: number | null;
  date_to?: number | null;
}
// WHEN THE PICTURE WAS TAKEN — a window over the item's own capture date, or,
// for an item nobody dated, over the span of the events it carries. Values are
// partial YYYYMMDDHHMMSS (see subjects/taken.ts); the query string writes the
// shortest form that reads back the same.
export interface TakenCond {
  type: "taken";
  have: boolean;        // false = "nothing says when this was taken"
  date_from?: number | null;
  date_to?: number | null;
}
export interface PlaceCond {
  type: "place";
  op: "=" | "~";        // is | contains
  value: string;        // "" = has any location at all
  have: boolean;
}
// PICTURES WHOSE PALETTE IS LIKE ONE PARTICULAR PICTURE'S. Likeness is
// pairwise, so unlike every other condition this one names a pivot — which is
// also why it is a condition and not a sort: a sort has nowhere to put one.
// `by` has one value and the field survives because a stored tree carries it;
// there was a "visual" space over the perceptual hash, removed with the grid
// action that was its only door (the importer folds a re-encode or a crop
// onto the item it matches, so it found that item and nothing else).
// `tol` is a Hamming distance over the 56-bit colour signature; null means
// the backend's `DEFAULT_COLOR_TOL`.
export interface SimilarCond {
  type: "similar";
  by: "color";
  uid: string;
  tol?: number | null;
  have: boolean;
}
// TAGS READ AS NUMBERS — the `<name>:<number><unit>` convention. `name` is a
// NAMESPACE: `VALUE:height>190cm` matches an item carrying ANY `height:` tag
// whose basename parses as a value satisfying the comparison
// (shared/tagvalue.ts is the one definition of what parses and which units
// convert). `tol` is the metadata rule — half the last typed decimal place,
// computed here while the text still shows it, in the literal's own unit.
export interface ValueCond {
  type: "value";
  name: string;
  op: "=" | "!=" | ">" | ">=" | "<" | "<=";
  value: number;
  unit: string;
  tol?: number;
  have: boolean;
}
export interface Group {
  type: "group";
  op: BoolOp;
  neg: boolean;
  children: Node[];
}
export type Cond = TagCond | LinkCond | CapCond | MetaCond | GrpCond | SubjCond
  | PlaceCond | EventCond | TakenCond | SimilarCond | ValueCond;
export type Node = Group | Cond;

// Metadata operators, longest first so two-char ops win when scanning an atom.
export const META_OPS = [">=", "<=", "!=", "!~", ">", "<", "=", "~"] as const;

export const emptyGroup = (): Group => ({ type: "group", op: "and", neg: false, children: [] });

// ---- escaping --------------------------------------------------------------
//
// A tag name may legitimately contain the characters the grammar uses as
// syntax: a comma separates the tags of a link/caption list, and a leading
// `!` (or `-`) negates. A backslash escapes the next character, so
// `caption:test\,tag,abc` asks for the two tags "test,tag" and "abc", and
// `\!test` is the tag literally named "!test" rather than "not test".

/** Split on `sep`, honouring backslash escapes. The pieces come back STILL
 *  escaped — the caller strips its own prefixes (an exclusion `!`) first and
 *  unescapes after, or `\!name` would read as "exclude name". */
export function splitEscaped(s: string, sep = ","): string[] {
  const out: string[] = [];
  let cur = "";
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "\\" && i + 1 < s.length) { cur += c + s[i + 1]; i++; continue; }
    if (c === sep) { out.push(cur); cur = ""; continue; }
    cur += c;
  }
  out.push(cur);
  return out;
}

/** Drop one level of escaping (`\,` → `,`, `\\` → `\`). */
export function unescapeName(s: string): string {
  return s.replace(/\\(.)/g, "$1");
}

/** Escape a name so parsing reads it back verbatim. */
export function escapeName(s: string): string {
  let out = s.replace(/\\/g, "\\\\").replace(/,/g, "\\,");
  if (out.startsWith("!") || out.startsWith("-")) out = "\\" + out;
  return out;
}

// ---- serialize -------------------------------------------------------------

const needsQuote = (s: string) => /\s/.test(s);

function serializeCond(c: Cond): string {
  if (c.type === "tag") {
    const prefix = (c.have ? "" : "!") + (c.sign === "neg" ? "-" : "");
    if (c.meta_tags && c.meta_tags.length) {
      const tags = c.meta_tags
        .map((t) => (t.exclude ? "!" : "") + escapeName(t.name)).join(",");
      const atom = `${prefix}TAG:${tags}`;
      return needsQuote(atom) ? `"${atom}"` : atom;
    }
    return prefix + escapeName(c.name);
  }
  if (c.type === "meta") {
    const atom = `INFO:${c.name}${c.op}${metaValueText(c)}`;
    return needsQuote(atom) ? `"${atom}"` : atom;
  }
  if (c.type === "ingroup") {
    const neg = c.mode === "hasnot" || c.mode === "notonly" ? "!" : "";
    const kw = c.mode === "only" || c.mode === "notonly" ? "GROUPONLY" : "GROUP";
    const atom = `${neg}${kw}:${escapeName(c.name)}`;
    return needsQuote(atom) ? `"${atom}"` : atom;
  }
  if (c.type === "place") {
    // PLACE:Shibuya (contains) / PLACE=Tokyo (is) / !PLACE: (has none)
    const atom = `${c.have ? "" : "!"}PLACE${c.op === "=" ? "=" : ":"}${escapeName(c.value)}`;
    return needsQuote(atom) ? `"${atom}"` : atom;
  }
  if (c.type === "subject") {
    // subject:alice@1921 / @1910..1920 (dates) / #12 / #10..14 (ages).
    const d = spanText(c.date_from, c.date_to, true);
    const g = spanText(c.age_from, c.age_to);
    const atom = `${c.have ? "" : "!"}SUBJECT:${escapeName(c.name)}`
      + (d ? `@${d}` : "") + (g ? `#${g}` : "");
    return needsQuote(atom) ? `"${atom}"` : atom;
  }
  if (c.type === "event") {
    // event:sdcc / event:@2014 / event:@2014..2016 / !event: (has none).
    // No `#`: an event has no age, only a span of its own.
    const d = spanText(c.date_from, c.date_to, true);
    const atom = `${c.have ? "" : "!"}EVENT:${escapeName(c.name)}`
      + (d ? `@${d}` : "");
    return needsQuote(atom) ? `"${atom}"` : atom;
  }
  if (c.type === "taken") {
    // TAKEN:@2020 / TAKEN:@2020-01-01..2020-01-07 / !TAKEN: (nothing says).
    // The `@` matches `SUBJECT:` and `EVENT:`, so one mark means "when" in
    // every condition that has one.
    const d = spanText(c.date_from, c.date_to, true, true);
    const atom = `${c.have ? "" : "!"}TAKEN:` + (d ? `@${d}` : "");
    return needsQuote(atom) ? `"${atom}"` : atom;
  }
  if (c.type === "value") {
    // VALUE:height>190cm — the number re-renders with the decimals `tol`
    // implies (the metaValueText rule), so `VALUE:height=1.70m` round-trips.
    const num = c.tol
      ? c.value.toFixed(Math.max(0, Math.round(-Math.log10(c.tol * 2))))
      : String(c.value);
    const atom = `${c.have ? "" : "!"}VALUE:${escapeName(c.name)}${c.op}${num}${c.unit}`;
    return needsQuote(atom) ? `"${atom}"` : atom;
  }
  if (c.type === "similar") {
    // COLORLIKE:<uid>[~<tol>]. No `~n` when the tolerance is the default:
    // writing it out would freeze today's number into a saved search that
    // should follow it, and the two forms have to read back as different
    // trees.
    const atom = `${c.have ? "" : "!"}COLORLIKE:${escapeName(c.uid)}`
      + (c.tol === null || c.tol === undefined ? "" : `~${c.tol}`);
    return needsQuote(atom) ? `"${atom}"` : atom;
  }
  if (c.type === "caption") {
    const tags = c.caption_tags
      .map((t) => (t.exclude ? "!" : "") + escapeName(t.name)).join(",");
    const kw = c.caption_kind === "instruction" ? "INSTRUCTION" : "CAPTION";
    const atom = `${c.mode === "hasnot" ? "!" : ""}${kw}:${tags}`;
    return needsQuote(atom) ? `"${atom}"` : atom;
  }
  // link
  const kw = c.direction === "linkedby" || c.direction === "notlinkedby" ? "LINKEDBY" : "LINK";
  const neg = c.direction === "hasnot" || c.direction === "notlinkedby";
  const tags = c.link_tags
    .map((t) => (t.exclude ? "!" : "") + escapeName(t.name)).join(",");
  return `${neg ? "!" : ""}${kw}:${tags}`;
}

function serializeNode(n: Node, root: boolean): string {
  if (n.type !== "group") return serializeCond(n);
  const sep = n.op === "or" ? "|" : " ";
  const inner = n.children.map((c) => serializeNode(c, false)).join(sep);
  if (n.neg) return `!(${inner})`;
  if (root) return inner;
  return n.children.length > 1 ? `(${inner})` : inner;
}

/** The canonical query string for a tree (the text-bar / saved-search form). */
export function serialize(root: Group): string {
  return serializeNode(root, true);
}

// ---- parse -----------------------------------------------------------------

type Tok = { t: "atom"; v: string } | { t: "(" } | { t: ")" } | { t: "|" } | { t: "not" } | { t: "sep" };

function tokenize(src: string): Tok[] {
  const toks: Tok[] = [];
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i];
    if (/\s/.test(c)) { toks.push({ t: "sep" }); i++; continue; }
    if (c === "(") { toks.push({ t: "(" }); i++; continue; }
    if (c === ")") { toks.push({ t: ")" }); i++; continue; }
    if (c === "|") { toks.push({ t: "|" }); i++; continue; }
    // `!` is the NOT operator ONLY directly before a group; otherwise it is part
    // of an atom (has-not tag, negative link direction, or a != / !~ op).
    if (c === "!" && src[i + 1] === "(") { toks.push({ t: "not" }); i++; continue; }
    // Otherwise scan one atom. It runs until whitespace / paren / pipe and may
    // contain double-quoted segments; the quote isn't a token boundary, so a
    // prefix like `!`, `-`, `meta:` or `link:` stays *outside* the quotes
    // (`!"ball"`, `meta:"Lens Model"~canon`) rather than splitting off.
    //
    // A quote pair is a *wrapper* (stripped) only when it protects whitespace —
    // the sole reason the serializer ever quotes an atom. Around a
    // whitespace-free segment the quotes are literal characters, so a tag whose
    // name really contains quotes (`"ball"`) stays distinct from the plain tag
    // `ball` instead of collapsing onto it.
    let v = "";
    while (i < n && !/[\s()|]/.test(src[i])) {
      if (src[i] === '"') {
        let j = i + 1;
        while (j < n && src[j] !== '"') j++;
        const end = j < n ? j + 1 : n;
        const inner = src.slice(i + 1, j);
        v += /\s/.test(inner) ? inner : src.slice(i, end);
        i = end;
      } else {
        v += src[i];
        i++;
      }
    }
    toks.push({ t: "atom", v });
  }
  // Collapse separator runs and trim leading/trailing ones.
  const out: Tok[] = [];
  for (const t of toks) {
    if (t.t === "sep" && (out.length === 0 || out[out.length - 1].t === "sep")) continue;
    out.push(t);
  }
  while (out.length && out[0].t === "sep") out.shift();
  while (out.length && out[out.length - 1].t === "sep") out.pop();
  return out;
}

function isNumeric(v: string): boolean {
  return /^-?\d+(?:\.\d+)?$/.test(v);
}

/**
 * Half of the last decimal place a searched number was written to — the
 * window a numeric `=` accepts around it. `0.7` means "about 0.7" (±0.05),
 * `0.75` narrows that to ±0.005, and a whole number gets ±0.5 (a no-op for
 * integer-valued fields like width). Mirrors `num_tolerance` in query.py.
 */
export function numTolerance(raw: string): number {
  const dot = raw.indexOf(".");
  const decimals = dot < 0 ? 0 : raw.length - dot - 1;
  return 0.5 * Math.pow(10, -decimals);
}

/** Render a numeric value with the decimals its tolerance implies, so that
 *  a deliberate `0.70` survives the trip through the query string (and stays
 *  visible in the builder's value field). */
export function metaValueText(c: MetaCond): string {
  if (c.mtype !== "numeric" || typeof c.value !== "number" || !c.tol) return String(c.value);
  const decimals = Math.max(0, Math.round(-Math.log10(c.tol * 2)));
  return c.value.toFixed(decimals);
}

/** A typed date to the partial-date encoding the evaluator reads.
 *
 *  `2014` is a YEAR, and the encoding is YYYYMMDD with zeros for what is
 *  unknown — so it has to become 20140000. Writing the bare number through was
 *  a live bug in `subject:@1910`: the backend decoded it as year 0, month 19,
 *  day 10 and the query matched nothing, silently. Length is the precision:
 *  4 digits a year, 6 a month, 8 a day. */
function parseWhen(raw: string): number | null {
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return null;
  if (raw.length <= 4) return n * 10000;
  if (raw.length <= 6) return n * 100;
  return n;
}

/** The same for a capture date, which goes two levels finer: digits are read
 *  as YYYY[MM[DD[HH[MM[SS]]]]] and padded with zeros, so `2020` is the year and
 *  `20200305143012` one second. Separators are ignored, which is what lets a
 *  person type `2020-01-07` in the search field. */
function parseTakenValue(raw: string): number | null {
  const digits = raw.replace(/\D/g, "").slice(0, 14);
  if (digits.length < 4) return null;
  return Number(digits.padEnd(14, "0"));
}

/** The shortest form that reads back the same — `2020`, not
 *  `20200000000000`, and `2020-01-07` rather than fourteen digits. */
function formatTakenValue(v: number): string {
  const d = String(Math.trunc(v)).padStart(14, "0");
  let keep = 4;
  for (const start of [4, 6, 8, 10, 12]) {
    if (d.slice(start, start + 2) !== "00") keep = start + 2;
  }
  const head = [d.slice(0, 4), d.slice(4, 6), d.slice(6, 8)]
    .slice(0, Math.min(3, Math.ceil(keep / 2) - 1)).filter(Boolean).join("-");
  if (keep <= 8) return head;
  const time = [d.slice(8, 10), d.slice(10, 12), d.slice(12, 14)]
    .slice(0, (keep - 8) / 2).join(":");
  return `${head}T${time}`;
}

/** The shortest form that reads back as the same date — `2014`, not
 *  `20140000`. A query string is typed by hand as often as it is generated. */
function formatWhen(v: number): string {
  if (v % 10000 === 0) return String(Math.floor(v / 10000));
  if (v % 100 === 0) return String(Math.floor(v / 100));
  return String(v);
}

/** A `lo..hi` range, a bare value (both ends), or `..hi` / `lo..` (one open).
 *  Shared by `subject:`'s two spans and `event:`'s one. `when` says whether the
 *  values are partial DATES (they are, except for a subject's age in years). */
function parseSpan(raw: string | undefined,
                   when = false,
                   fine = false): [number | null, number | null] {
  if (!raw) return [null, null];
  const one = (s?: string) => {
    if (s === "" || s === undefined) return null;
    if (fine) return parseTakenValue(s);
    if (when) return parseWhen(s);
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };
  const [a, b] = raw.split("..");
  const lo = one(a);
  const hi = b === undefined ? lo : one(b);
  return [lo, hi];
}

/** The inverse, for one span. */
function spanText(a: number | null | undefined, b: number | null | undefined,
                  when = false, fine = false): string {
  const show = (v: number) =>
    (fine ? formatTakenValue(v) : when ? formatWhen(v) : String(v));
  if (a != null && b != null && a !== b) return `${show(a)}..${show(b)}`;
  if (a != null) return show(a);
  if (b != null) return `..${show(b)}`;
  return "";
}

/** Turn one atom token into a condition node.
 *
 *  Every keyword is UPPERCASE and matched case-SENSITIVELY: `PLACE:`,
 *  `SUBJECT:`, `EVENT:`, `GROUP:`, `GROUPONLY:`, `CAPTION:`, `LINK:`,
 *  `LINKEDBY:`, `INFO:`, `TAG:`. Anything else — lower or mixed case — is a
 *  tag name.
 *
 *  That is not decoration. A tag really can be called `place:berlin`: the
 *  Tagging settings put subjects, places and events in namespaces of exactly
 *  that shape by default, so a case-insensitive `place:` keyword would swallow
 *  the tag it created. Reserving the shouted form leaves the whole lowercase
 *  space to tag names, permanently. */
export function atomNode(tok: string): Cond {
  // Metadata: INFO:name<op>value.
  if (tok.startsWith("INFO:")) {
    const body = tok.slice(5);
    for (const op of META_OPS) {
      const idx = body.indexOf(op);
      if (idx > 0) {
        const name = body.slice(0, idx);
        const raw = body.slice(idx + op.length);
        const mtype: MetaType = op === "~" || op === "!~" ? "text" : isNumeric(raw) ? "numeric" : "text";
        if (mtype === "numeric") {
          return { type: "meta", name, mtype, op, value: Number(raw), tol: numTolerance(raw) };
        }
        return { type: "meta", name, mtype, op, value: raw };
      }
    }
    // No operator found — treat as an equality on the whole remainder.
    return { type: "meta", name: body, mtype: "text", op: "=", value: "" };
  }
  // Group membership: [!]GROUP:Name (the group and everything under it) /
  // [!]GROUPONLY:Name (the group itself).
  const om = tok.match(/^(!)?GROUPONLY:(.*)$/);
  if (om) {
    return { type: "ingroup", name: unescapeName(om[2]),
             mode: om[1] ? "notonly" : "only" };
  }
  const gm = tok.match(/^(!)?GROUP:(.*)$/);
  if (gm) {
    return { type: "ingroup", name: unescapeName(gm[2]),
             mode: gm[1] ? "hasnot" : "has" };
  }
  // Place: [!]PLACE(:|=)value — ":" contains, "=" is exactly. A place has
  // ONE searchable field, its name; to ask for one particular place, search
  // its TAG, which is what the item carries.
  const pm = tok.match(/^(!)?PLACE([:=])(.*)$/);
  if (pm) {
    return { type: "place", op: pm[2] === "=" ? "=" : "~",
             value: unescapeName(pm[3]), have: !pm[1] };
  }
  // Subject: [!]SUBJECT:name[@date][#age], each range either a single value
  // or lo..hi. An empty name asks for any subject at all.
  const sm = tok.match(/^(!)?SUBJECT:([^@#]*)(?:@([^#]*))?(?:#(.*))?$/);
  if (sm) {
    const [date_from, date_to] = parseSpan(sm[3], true);
    const [age_from, age_to] = parseSpan(sm[4]);
    return { type: "subject", name: unescapeName(sm[2]).toLowerCase(),
             have: !sm[1], date_from, date_to, age_from, age_to };
  }
  // Event: [!]EVENT:name[@date], the date range bounding the EVENT's own span.
  const em = tok.match(/^(!)?EVENT:([^@]*)(?:@(.*))?$/);
  if (em) {
    const [date_from, date_to] = parseSpan(em[3], true);
    return { type: "event", name: unescapeName(em[2]).toLowerCase(),
             have: !em[1], date_from, date_to };
  }
  // Taken: [!]TAKEN:[@window] — when the picture was taken.
  const tm = tok.match(/^(!)?TAKEN:(?:@(.*))?$/);
  if (tm) {
    const [date_from, date_to] = parseSpan(tm[2], true, true);
    return { type: "taken", have: !tm[1], date_from, date_to };
  }
  // Tags read as numbers: [!]VALUE:<namespace><op><number>[unit]. A comma
  // decimal is READ (a restored library can hold one); the serializer
  // writes the dot.
  const val = tok.match(/^(!)?VALUE:(.+?)(>=|<=|!=|=|>|<)(-?\d+(?:[.,]\d+)?)([a-z%°µ]*)$/);
  if (val) {
    const raw = val[4].replace(",", ".");
    return {
      type: "value", name: unescapeName(val[2]).toLowerCase(),
      op: val[3] as ValueCond["op"], value: Number(raw), unit: val[5],
      tol: numTolerance(raw), have: !val[1],
    };
  }
  // Palette likeness to a pivot item: [!]COLORLIKE:<uid>[~<tol>]. A
  // `SIMILAR:` keyword stood beside it over the perceptual hash and was
  // removed with the grid action that was its only door; the token is
  // nobody's keyword now and falls through to a tag name, which matches
  // nothing — a search that visibly finds no pictures rather than one
  // quietly answering something else.
  const sim = tok.match(/^(!)?COLORLIKE:([^~]*)(?:~(-?\d+))?$/);
  if (sim) {
    return {
      type: "similar",
      by: "color",
      uid: unescapeName(sim[2]),
      tol: sim[3] === undefined ? null : parseInt(sim[3], 10),
      have: !sim[1],
    };
  }
  // Caption: [!]CAPTION|INSTRUCTION:tags (empty tag list = "has any of them").
  // (parseTagRefs below splits on unescaped commas.)
  const cm = tok.match(/^(!)?(CAPTION|INSTRUCTION):(.*)$/);
  if (cm) {
    const caption_tags = parseTagRefs(cm[3]);
    return {
      type: "caption",
      mode: cm[1] ? "hasnot" : "has",
      caption_kind: cm[2] === "INSTRUCTION" ? "instruction" : "caption",
      caption_tags,
    };
  }
  // Link: [!]LINK|LINKEDBY:tags
  const lm = tok.match(/^(!)?(LINK|LINKEDBY):(.*)$/);
  if (lm) {
    const neg = !!lm[1];
    const incoming = lm[2] === "LINKEDBY";
    const direction: LinkDir = incoming ? (neg ? "notlinkedby" : "linkedby") : neg ? "hasnot" : "has";
    const link_tags = parseTagRefs(lm[3]);
    return { type: "link", direction, link_tags };
  }
  // A tag described by what the TAG SET says about it:
  // [!][-]TAG:meta,!meta — the CAPTION: shape, over the item's own tags.
  const tgm = tok.match(/^(!)?(-)?TAG:(.*)$/);
  if (tgm) {
    return { type: "tag", name: "", have: !tgm[1],
             sign: tgm[2] ? "neg" : "pos", meta_tags: parseTagRefs(tgm[3]) };
  }
  // Tag: [!][-]name — an escaped `\!` / `\-` is part of the NAME.
  let have = true;
  let sign: Sign = "pos";
  let name = tok;
  if (name.startsWith("!")) { have = false; name = name.slice(1); }
  if (name.startsWith("-")) { sign = "neg"; name = name.slice(1); }
  return { type: "tag", name: unescapeName(name).toLowerCase(), have, sign };
}

/** The tag list of a link/caption condition: comma-separated, `!` excludes,
 *  and both may be escaped with a backslash to appear in a name. */
function parseTagRefs(body: string): LinkTagRef[] {
  if (!body) return [];
  return splitEscaped(body)
    .map((x) => x.trim())
    .filter(Boolean)
    .map((x) => x.startsWith("!")
      ? { name: unescapeName(x.slice(1)), exclude: true }
      : { name: unescapeName(x), exclude: false });
}

/** Parse a query string into a root Group. Throws on malformed input. */
export function parse(src: string): Group {
  const toks = tokenize(src);
  let pos = 0;
  const peek = () => toks[pos];
  const eat = () => toks[pos++];

  const parseAtom = (): Node => {
    const t = peek();
    if (!t) throw new Error("unexpected end of query");
    if (t.t === "(") {
      eat();
      const inner = parseAnd();
      if (!peek() || peek().t !== ")") throw new Error("missing ')'");
      eat();
      return inner;
    }
    if (t.t === "not") {
      eat();
      const inner = parseAtom();
      if (inner.type === "group") return { ...inner, neg: !inner.neg };
      return { type: "group", op: "and", neg: true, children: [inner] };
    }
    if (t.t !== "atom") throw new Error(`unexpected token`);
    eat();
    return atomNode(t.v);
  };

  const parseOr = (): Node => {
    const items = [parseAtom()];
    while (peek() && peek().t === "|") { eat(); items.push(parseAtom()); }
    return items.length > 1 ? { type: "group", op: "or", neg: false, children: items } : items[0];
  };

  const parseAnd = (): Node => {
    const items = [parseOr()];
    while (peek() && peek().t === "sep") {
      eat();
      if (!peek() || peek().t === ")") break;
      items.push(parseOr());
    }
    return items.length > 1 ? { type: "group", op: "and", neg: false, children: items } : items[0];
  };

  if (toks.length === 0) return emptyGroup();
  const node = parseAnd();
  if (pos !== toks.length) throw new Error("unexpected trailing token");
  return node.type === "group" ? node : { type: "group", op: "and", neg: false, children: [node] };
}

/** Parse leniently: returns the tree, or null if the string doesn't parse (so
 *  the caller can keep the raw text while the user is mid-edit). */
export function tryParse(src: string): Group | null {
  try {
    return parse(src);
  } catch {
    return null;
  }
}

/** The JSON payload posted to the backend (the tree is already the wire shape;
 *  an empty tree becomes null = "match everything"). */
export function toRequest(root: Group): Group | null {
  return root.children.length ? root : null;
}
