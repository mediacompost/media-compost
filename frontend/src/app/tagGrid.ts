/** The tag-grid session's pure rules — the cursor walk over a fixed grid,
 *  the configuration codec and the summary counts. Everything a test can
 *  state without React lives here; `TagGridOverlay.tsx` only renders it.
 *
 *  A batch is a FIXED GRID of pictures, columns × rows, each cell holding one
 *  of three answers about one tag — fits, doesn't fit, undecided — shown as
 *  the cell's border colour. A card never moves when its answer changes:
 *  the classifier's own answer (`bucket`) is only where a card STARTS, and
 *  what Next writes is whatever the borders say when it is pressed.
 */

/** A card's answer. "both" is the fourth, offered only with a tag for
 *  "doesn't fit" set: the picture gets BOTH tags — the tag holds for one
 *  subject in it and not another. */
export type Assignment = "positive" | "none" | "negative" | "both";

/** WHICH ANSWERS A SESSION OFFERS. "Fits" is always one; the chooser may
 *  drop "doesn't fit" (a session that only ever adds the tag) or
 *  "undecided" (every card gets a decision — an undecided card writes the
 *  negative). */
export type Answers = "all" | "no_none" | "no_negative";
export const ANSWERS: readonly Answers[] = ["all", "no_none", "no_negative"];

/** The answers on offer, in the capsule's order. `both` adds the fourth
 *  after "doesn't fit" — meaningful only where that answer is a tag of its
 *  own, so the caller passes it only then. */
export function offered(answers: Answers, both = false): Assignment[] {
  const out: Assignment[] = answers === "no_none" ? ["positive", "negative"]
    : answers === "no_negative" ? ["positive", "none"]
    : ["positive", "negative", "none"];
  if (both && out.includes("negative")) out.splice(out.indexOf("negative") + 1, 0, "both");
  return out;
}

const RING: readonly Assignment[] = ["none", "positive", "negative", "both"];
/** What a caller gets without saying: the three ordinary answers. */
const PLAIN: readonly Assignment[] = ["none", "positive", "negative"];

/** What → does to a card's answer: none → fits → doesn't fit → none — and
 *  ← the same ring the other way round — over the answers ON OFFER: a
 *  dropped answer is skipped, and an answer that is not offered (a card
 *  that started on it) steps onto the ring's first offered answer. */
export function cycleAssignment(a: Assignment, back = false,
                                allowed: readonly Assignment[] = PLAIN,
                                ): Assignment {
  const ring = RING.filter((x) => allowed.includes(x));
  if (ring.length === 0) return a;
  const i = ring.indexOf(a);
  if (i < 0) return ring[0];
  return ring[(i + (back ? ring.length - 1 : 1)) % ring.length];
}

/** What ⇧⌥→ (or ⇧⌥←) does to the WHOLE batch — the answer every card
 *  takes, from the cards' answers in grid order. Where they already agree
 *  the batch turns together, the first card's ring step; where they differ
 *  the first press only ALIGNS them onto the first card's answer, so a
 *  batch is never stepped past a state nobody saw. An empty batch answers
 *  "none", which the caller has no card to put it on anyway. */
export function cycleAll(current: readonly Assignment[], back = false,
                         allowed: readonly Assignment[] = PLAIN): Assignment {
  if (current.length === 0) return "none";
  const first = current[0];
  if (current.some((a) => a !== first)) return first;
  return cycleAssignment(first, back, allowed);
}

/** Where a card STARTS from the classifier's bucket, given what is on
 *  offer: a bucket that is offered as it is; an undecided card in a
 *  session without "undecided" starts on "doesn't fit" (every card gets a
 *  decision there); a "doesn't fit" card in a session without one starts
 *  undecided. */
export function startAnswer(bucket: Assignment,
                            allowed: readonly Assignment[],
                            existing?: Assignment | null): Assignment {
  // What the picture already CARRIES beats the classifier's guess: a
  // session including tagged pictures shows the tags as given.
  if (existing) bucket = existing;
  if (allowed.includes(bucket)) return bucket;
  if (bucket === "none" && allowed.includes("negative")) return "negative";
  if (allowed.includes("none")) return "none";
  return allowed[0] ?? "none";
}

/** One tag of the session's SET, and what its "doesn't fit" writes — the
 *  tag batch's row, without the digit and without a question around it. */
export interface GridTag {
  name: string;
  /** "" is the tag itself, negatively; a name is a COUNTER tag assigned
   *  POSITIVELY in its place (`small` beside `big`). */
  negative: string;
}

export interface TagGridConfig {
  /** THE QUESTION, and what an answer writes — one list, not two. A picture
   *  fits when it carries EVERY tag here; "doesn't fit" is evidence against
   *  ANY ONE of them, since a picture failing one conjunct is not an example
   *  of the conjunction whatever the others say. That is how the set is
   *  READ; what it WRITES is asymmetric past one tag (see `writeFor`). */
  tags: GridTag[];
  /** Groups a "fits" answer puts the picture in. Never taken away: "not in
   *  that group" is not something to record, only something that is true. */
  groups: number[];
  /** The grid's shape; a batch is `cols * rows` pictures. */
  cols: number;
  rows: number;
  /** An embed model id, or `FUSED` for every listed model at once. */
  embedder: string;
  /** Whether half of each batch is the pictures the model is least sure
   *  about (on), or simply the likeliest matches (off). */
  boundary: boolean;
  /** Leave out pictures that are members of a sequence. */
  skipSequenced: boolean;
  /** Which answers the capsule offers (see `Answers`). */
  answers: Answers;
  /** Offer "both" — the picture gets the tag AND its "doesn't fit"
   *  spelling. Read only while `canSayBoth`: a counter tag, and a set of
   *  one (past that the negative answer writes nothing to have both of). */
  bothAnswer: boolean;
  /** Keep pictures already tagged in the pool; they start on what they
   *  carry rather than on the classifier's guess — to check given tags. */
  includeTagged: boolean;
}

/** Whether any tag of the set has a counter — the other spelling of
 *  "doesn't fit". Read as EVIDENCE whatever the set's size: a picture
 *  called `small` is evidence against `big`, and against "big and blue"
 *  too. What it no longer decides on its own is whether "both" is on
 *  offer (see `canSayBoth`). */
export function hasCounter(cfg: TagGridConfig): boolean {
  return cfg.tags.some((t) => t.negative.trim() !== "");
}

/** Whether "both" is a thing this set can say. It is the two answers at
 *  once, so it needs a "doesn't fit" that writes something: a counter tag
 *  (or "both" would be the tag beside its own negative) AND a set of one,
 *  since past that the negative answer writes nothing and "both" would be
 *  a fourth button spelling "fits". */
export function canSayBoth(cfg: TagGridConfig): boolean {
  return hasCounter(cfg) && !writeIsEmpty(writeFor(cfg, "negative"));
}

/** What one answer writes: tags by sign, and groups to join. */
export interface GridWrite {
  pos: string[];
  neg: string[];
  groups: number[];
}

/** Nothing configured — the caller falls back to the plain behaviour. */
export function emptyWrite(): GridWrite {
  return { pos: [], neg: [], groups: [] };
}

export function writeIsEmpty(w?: GridWrite): boolean {
  return !w || (w.pos.length === 0 && w.neg.length === 0
                && w.groups.length === 0);
}

/** WHAT THIS ANSWER WRITES on a card, resolved — the configured set where
 *  there is one, else the single-tag behaviour this session always had.
 *  "both" is the two sets together; "none" writes nothing and is the state
 *  everything is diffed against. */
export function writeFor(cfg: TagGridConfig,
                         answer: "positive" | "negative" | "both" | "none",
                         ): GridWrite {
  const rows = cfg.tags.filter((t) => t.name.trim());
  const fits: GridWrite = {
    pos: [...new Set(rows.map((t) => t.name.trim()))],
    neg: [],
    groups: [...new Set(cfg.groups)],
  };
  // THE TWO ANSWERS ARE ASYMMETRIC, because a conjunction is. "Fits"
  // DECOMPOSES: the picture carries every tag of the set, and each conjunct
  // is a fact worth writing. "Doesn't fit" does not — it says `NOT a OR NOT
  // b`, and a disjunction is the one thing an assignment cannot spell.
  // Writing it on each tag separately claims far more than anybody said:
  // the picture may well be `a`, just not `a` AND `b`, and the session
  // would be filling the library with negatives nobody stated and nothing
  // can tell apart from stated ones. So past ONE tag it writes nothing at
  // all — not the counters either, since a counter positively is the same
  // claim about one conjunct in a different spelling — and the answer
  // travels to the fit as `session_negatives` instead (which is how the
  // ordering still learns from it). With one tag there is no disjunction
  // and nothing changes.
  const no: GridWrite = { pos: [], neg: [], groups: [] };
  if (rows.length === 1) {
    for (const t of rows) {
      const counter = t.negative.trim();
      if (counter && counter !== t.name.trim()) no.pos.push(counter);
      else no.neg.push(t.name.trim());
    }
  }
  no.pos = [...new Set(no.pos)];
  no.neg = [...new Set(no.neg)];
  if (answer === "positive") return fits;
  if (answer === "negative") return no;
  if (answer === "both") {
    return {
      pos: [...new Set([...fits.pos, ...no.pos])],
      neg: [...new Set([...fits.neg, ...no.neg])],
      groups: [...new Set([...fits.groups, ...no.groups])],
    };
  }
  return emptyWrite();
}

/** The set as the FEED takes it. With the "doesn't fit" answer off the
 *  counters go with it: a tag nothing will write must not decide the pool
 *  either. */
export function wireTags(cfg: TagGridConfig, counters = true,
                         ): { name: string; negative: string }[] {
  return cfg.tags.filter((t) => t.name.trim()).map(
    (t) => ({ name: t.name.trim(),
              negative: counters ? t.negative.trim() : "" }));
}

/** The tags' names, in order — what the session is CALLED on screen and
 *  what a query key hangs on. */
export function tagNames(cfg: TagGridConfig): string[] {
  return cfg.tags.map((t) => t.name.trim()).filter(Boolean);
}

/** The set with one tag added (positively, no counter), or unchanged where
 *  it is already there or the name is empty. */
export function withTag(cfg: TagGridConfig, name: string): TagGridConfig {
  const nm = name.trim();
  if (!nm || cfg.tags.some((t) => t.name === nm)) return cfg;
  return { ...cfg, tags: [...cfg.tags, { name: nm, negative: "" }] };
}

export function withoutTag(cfg: TagGridConfig, name: string): TagGridConfig {
  return { ...cfg, tags: cfg.tags.filter((t) => t.name !== name) };
}

/** A tag's counter set (or cleared with "" — its own negative again). The
 *  tag's own name is no counter. */
export function withCounter(cfg: TagGridConfig, name: string,
                            counter: string): TagGridConfig {
  const clean = counter.trim() === name ? "" : counter.trim();
  return { ...cfg, tags: cfg.tags.map(
    (t) => (t.name === name ? { ...t, negative: clean } : t)) };
}

/** A tag RENAMED in place — its slot and its counter kept. */
export function renameTag(cfg: TagGridConfig, from: string,
                          to: string): TagGridConfig {
  const nm = to.trim();
  if (!nm || nm === from || cfg.tags.some((t) => t.name === nm)) return cfg;
  return { ...cfg, tags: cfg.tags.map(
    (t) => (t.name === from
      ? { name: nm, negative: t.negative === nm ? "" : t.negative } : t)) };
}

/** The pseudo-embedder that means "every listed model, fused" — the tag
 *  batch's, re-exported so the two choosers cannot drift into two ideas
 *  of what "both" means. */
export { FUSED, embeddersOf } from "./tagSort.ts";

export const GRID_COLS: readonly number[] = [2, 3, 4, 5, 6, 7, 8];
export const GRID_ROWS: readonly number[] = [1, 2, 3, 4, 5, 6];

export const TAGGRID_KEY = "mc.tagGrid";

export const DEFAULT_CONFIG: TagGridConfig = {
  tags: [], groups: [], cols: 4, rows: 4, embedder: "fused", boundary: true,
  skipSequenced: false, answers: "all", bothAnswer: false,
  includeTagged: false,
};

/** THE SET, out of whatever a stored config holds.
 *
 *  Three shapes have written this key. The current one is `tags` plus
 *  `groups`. Before it, the question was ONE tag (`tag`) with an optional
 *  counter (`negativeTag`) and two separate write sets beside it
 *  (`fitsWrite`/`noWrite`); a config in that shape becomes the question tag
 *  with its counter, plus whatever ELSE "fits" wrote as rows of their own,
 *  and the groups it joined. What `noWrite` said past the counter cannot be
 *  carried: in this shape "doesn't fit" is what the rows say, not a second
 *  list — which is the whole point of the change. */
function parseTags(v: Record<string, unknown>): {
  tags: GridTag[]; groups: number[];
} {
  const tags: GridTag[] = [];
  const seen = new Set<string>();
  const push = (name: unknown, negative: unknown = "") => {
    const nm = typeof name === "string" ? name.trim() : "";
    if (!nm || seen.has(nm)) return;
    seen.add(nm);
    tags.push({ name: nm,
                negative: typeof negative === "string" ? negative.trim() : "" });
  };
  if (Array.isArray(v.tags)) {
    for (const raw of v.tags as unknown[]) {
      if (typeof raw === "string") push(raw);
      else if (raw && typeof raw === "object") {
        const o = raw as Record<string, unknown>;
        push(o.name, o.negative);
      }
    }
  } else {
    push(v.tag, v.negativeTag);
    const fits = (v.fitsWrite ?? {}) as Record<string, unknown>;
    if (Array.isArray(fits.pos)) for (const n of fits.pos) push(n);
  }
  const raw = Array.isArray(v.groups) ? v.groups
    : Array.isArray(((v.fitsWrite ?? {}) as Record<string, unknown>).groups)
      ? ((v.fitsWrite as Record<string, unknown>).groups as unknown[]) : [];
  const groups = [...new Set(raw.filter(
    (g): g is number => Number.isInteger(g)))];
  return { tags, groups };
}

export function batchSize(cfg: TagGridConfig): number {
  return cfg.cols * cfg.rows;
}

export function parseTagGridConfig(raw: string | null): TagGridConfig {
  if (!raw) return { ...DEFAULT_CONFIG };
  try {
    const v = JSON.parse(raw) as Partial<TagGridConfig> | null;
    if (!v || typeof v !== "object") return { ...DEFAULT_CONFIG };
    const cols = Number(v.cols);
    const rows = Number(v.rows);
    return {
      ...parseTags(v as unknown as Record<string, unknown>),
      cols: GRID_COLS.includes(cols) ? cols : DEFAULT_CONFIG.cols,
      rows: GRID_ROWS.includes(rows) ? rows : DEFAULT_CONFIG.rows,
      embedder: typeof v.embedder === "string" && v.embedder
        ? v.embedder : DEFAULT_CONFIG.embedder,
      boundary: v.boundary !== false,
      skipSequenced: v.skipSequenced === true,
      answers: ANSWERS.includes(v.answers as Answers)
        ? (v.answers as Answers) : "all",
      bothAnswer: v.bothAnswer === true,
      includeTagged: v.includeTagged === true,
    };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function serializeTagGridConfig(cfg: TagGridConfig): string {
  return JSON.stringify(cfg);
}

export type Step = "left" | "right" | "up" | "down";

/** Where the cursor goes from `cur` over a grid `cols` wide — TWO
 *  DIMENSIONS: → is the next card in reading order (the first of the next
 *  row after a row's last) and ← the previous, ↓ is the card below (the
 *  same column, next row) and ↑ the one above. The edges absorb: a row's
 *  last card has no ↓ when the row below is shorter, and the first row no
 *  ↑. With no cursor (or a stale one), any key lands on the FIRST card —
 *  nothing is selected until a key asks for it. */
export function stepCursor(ids: readonly number[], cur: number | null,
                           dir: Step, cols = 1): number | null {
  if (ids.length === 0) return null;
  if (cur == null || !ids.includes(cur)) return ids[0];
  const i = ids.indexOf(cur);
  const w = Math.max(1, cols);
  const j = dir === "right" ? i + 1 : dir === "left" ? i - 1
    : dir === "down" ? i + w : i - w;
  if (j < 0 || j >= ids.length) return cur;
  return ids[j];
}

/** The session's totals over every committed batch. */
export function summarizeBatches(
  batches: readonly { assign: ReadonlyMap<number, Assignment> }[],
): { positive: number; negative: number; none: number; both: number } {
  const s = { positive: 0, negative: 0, none: 0, both: 0 };
  for (const b of batches) for (const a of b.assign.values()) s[a] += 1;
  return s;
}
