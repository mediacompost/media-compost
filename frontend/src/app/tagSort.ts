/** The tag-batch session's rules, pure — everything the overlay decides that
 *  is not DOM lives here so `node --test` can state it as tests.
 *
 *  THE SET IS A LIST OF GROUPS, never fewer than one, and every tag is in
 *  one of them (a root level holding bare tags was tried and taken out: it
 *  was a group with both switches off, spelled a second way). A group with
 *  no tag in it has no effect. Each group carries its own two settings —
 *  MUTUALLY EXCLUSIVE (at most one of its tags may be lit on a picture:
 *  lighting another puts the lit one out) and ASSIGN NEGATIVE TAGS (its
 *  unlit tags are written negatively when the picture is committed) — and
 *  under that switch each tag says WHAT its negative is: itself, negatively
 *  (the default), or a COUNTER tag assigned POSITIVELY in its place (the
 *  tag grid's "doesn't fit" tag, per tag: `low_quality` beside
 *  `high_quality`). Those two replaced one session-wide pair of switches,
 *  which could not say "one of these three, and any of those two" in one
 *  session.
 *
 *  The MODE is derived, never stored: exactly one tag in the whole set is a
 *  yes/no session, more are digits — and the digits TOGGLE, always; ↓
 *  commits the picture as it stands. (An exclusive set used to file-and-
 *  advance on the digit; exclusivity is the group's rule about what may be
 *  lit at once now, and nothing about it advances.)
 *
 *  A COMMIT PLAN is what one answer writes: the positive names and the
 *  negative names, or null for "nothing — this is a skip in effect". The
 *  overlay turns a plan into assign calls (one per name, each returning its
 *  event fan) and `↑` reverts the whole fan together.
 */

/** One ROW of the set, wherever it sits: a tag, or a LIBRARY GROUP.
 *
 *  A group row is answered exactly like a tag — it takes a digit, it lights
 *  and unlights, it sits in a question beside the tags — and what it WRITES
 *  is a membership rather than an assignment. It has no negative form: a
 *  tag left unlit can be marked as not applying, while "this picture is not
 *  in that group" is not a thing to record, only a thing that is true. So a
 *  group row is skipped by the negatives switch and offers no counter tag.
 *
 *  Its `name` is a SYNTHETIC key (`groupRowName`) rather than the group's
 *  name, because a group's name is not its identity — two groups may share
 *  one — and every digit, toggle and summary in this file is keyed by
 *  `name`. `label` is what the eye sees. */
export interface TagSortTag {
  name: string;
  /** WHAT "doesn't fit" WRITES, under the group's negatives switch: "" is
   *  the default — the tag itself, negatively — and a name is a COUNTER
   *  tag assigned POSITIVELY in its place (`low_quality` beside
   *  `high_quality`). The switch off, neither is written. */
  negative: string;
  /** The LIBRARY GROUP this row assigns, if it is a group row. */
  group?: number;
  /** The group's name when it was picked — display only, refreshed from
   *  the library wherever the editor has the tree to hand. */
  label?: string;
}

/** The `name` a library-group row is filed under. NUL cannot be typed into
 *  a tag field, so it cannot collide with a tag somebody has. */
export const GROUP_ROW_PREFIX = "\u0000g";

export function groupRowName(id: number): string {
  return `${GROUP_ROW_PREFIX}${id}`;
}

export function isGroupRow(t: TagSortTag): boolean {
  return typeof t.group === "number";
}

export interface TagSortGroup {
  /** Session-local identity — the React key, and what a toggle is scoped
   *  by. Minted on creation and on read. A group has no NAME: it is what
   *  its tags and its two switches say, and a label over that was a field
   *  nobody filled in. */
  id: string;
  /** At most one lit at a time. */
  exclusive: boolean;
  /** Unlit member tags are written negatively on commit (a member with a
   *  counter tag writes that instead, either way). */
  negatives: boolean;
  /** OFF means the group is not in the session at all: its tags are not
   *  offered, take no digit, and nothing is written for them. On by
   *  default and OPTIONAL on the wire, so a stored setup — and every
   *  comparison against a fresh config — is unchanged by its arrival.
   *
   *  Not the same as removing it: a set kept for another pass stays
   *  written down, with its digits, ready to come back. */
  enabled?: boolean;
  /** Answering a tag in this group MOVES ON to the next picture. Per group
   *  because it is a property of the question: a one-tag "is this a
   *  screenshot" is answered and done, while a group of nine costume tags
   *  wants several presses before the picture is finished with. */
  advance?: boolean;
  tags: TagSortTag[];
}

export interface TagSortConfig {
  /** The set, in reading order. AT LEAST ONE, always — the parser, Clear
   *  and the group remove all keep one, empty if need be, because the one
   *  place a tag can be added is inside a group. */
  groups: TagSortGroup[];
  /** Classifier-assisted ordering — likely matches first, learned from the
   *  answers. An OPTION so a session can run in plain order deliberately;
   *  the chooser disables it (rather than hiding it) while no embedding
   *  model is set up. */
  smart: boolean;
  /** Which embedding model orders the queue (a plugin model id — DINOv2 or
   *  CLIP). The chooser offers what the machine's plugin registry lists and
   *  falls back to the first listed model when a stored id has gone. */
  embedder: string;
  /** WHICH KIND the session asks about — "image" or "video", never both.
   *
   * A tag session is a rhythm, and the two kinds do not share one: a picture
   * is answered at a glance and a film has to be watched. Mixing them makes
   * every video a stall in a run of stills. It is also what the classifier
   * can and cannot help with — only pictures carry a vector, so a mixed pool
   * reported a coverage figure it could never fill, counting films that no
   * embedder here will ever index.
   *
   * It narrows the session's SCOPE like the grid's own kind filter, so a
   * sequence's pages are reached by opening the sequence, exactly as
   * everywhere else. */
  kind: "image" | "video";
  /** Leave out pictures that are members of a sequence. */
  skipSequenced: boolean;
  /** Which DIGIT each tag answers to, by name — set from the chooser's
   *  number box. A tag with no entry takes its position; several tags may
   *  share a digit (the key then toggles them all), and the list's order
   *  says nothing about the keys once one is set by hand. Groups carry no
   *  digit: the keys are the tags'. */
  keys: Record<string, number>;
}

export const TAGSORT_KEY = "mc.tagSort";

/** The pseudo-embedder that means "every listed model, fused": each
 *  space fit and scored on its own, an item's score the mean of the spaces
 *  it is indexed in. THE DEFAULT, measured: on 1,000 hand-labelled crawl
 *  photographs the fused pair was the best or joint-best space on five of
 *  six tags and never the worst — CLIP carries the semantic tags (text,
 *  person, a rare animal), DINOv2 the style ones (illustration, food) —
 *  where either alone lost badly somewhere. With one model installed it
 *  resolves to that one. */
export const FUSED = "fused";

export const DEFAULT_EMBEDDER = FUSED;

/** Which embed models a choice names: `FUSED` is every model there is,
 *  anything else is itself when listed and the first model otherwise (a
 *  stored id whose plugin has gone must not ride into a request). */
export function embeddersOf(choice: string, available: readonly string[],
                            ): string[] {
  if (available.length === 0) return [];
  if (choice === FUSED) return [...available];
  return available.includes(choice) ? [choice] : [available[0]];
}

/** The id of the group a fresh config starts with — fixed rather than
 *  minted, so two fresh configs compare equal; ids only have to be unique
 *  WITHIN a config. */
export const FIRST_GROUP_ID = "g0";

/** A group with nothing in it yet, exclusive and writing negatives —
 *  what the old one-switch default did. */
export function emptyGroup(id: string = mintId()): TagSortGroup {
  return { id, exclusive: true, negatives: true, tags: [] };
}

export const DEFAULT_CONFIG: TagSortConfig = {
  groups: [emptyGroup(FIRST_GROUP_ID)], smart: true,
  embedder: DEFAULT_EMBEDDER, kind: "image", skipSequenced: false,
  keys: {},
};

/** How many tags a session may hold, wherever they sit — the digit keys
 *  are the cap. */
export const MAX_TAGS = 9;

export type TagSortMode = "single" | "multi";

// ---- reading the set -------------------------------------------------------

/** Every tag of the set in reading order — group by group. What the
 *  digits, the summary and the wire count over. */
export function tagNames(cfg: TagSortConfig): string[] {
  return setTags(cfg).map((x) => x.tag.name);
}

/** The TAG names alone — no library-group rows. What the classifier is
 *  told about, what the pool is decided by, and what a field's "already in
 *  the set" check reads: a group row is something an answer also writes,
 *  never something the ordering knows about. */
export function plainTags(cfg: TagSortConfig): string[] {
  return setTags(cfg).filter((x) => !isGroupRow(x.tag)).map((x) => x.tag.name);
}

/** WHAT A ROW IS CALLED ON SCREEN: a tag's name is its own, a library
 *  group's row is named by its id and reads as its label. Every place that
 *  prints the set — the legend, the header, the summary, a preset's default
 *  name — goes through this, or a group row prints its key. */
export function rowLabel(cfg: TagSortConfig, name: string): string {
  const hit = setTags(cfg).find((x) => x.tag.name === name);
  return hit && isGroupRow(hit.tag)
    ? (hit.tag.label || `#${hit.tag.group}`) : name;
}

/** Every row's label, in reading order. */
export function rowLabels(cfg: TagSortConfig): string[] {
  return setTags(cfg).map(({ tag }) => isGroupRow(tag)
    ? (tag.label || `#${tag.group}`) : tag.name);
}

/** The same walk with each tag's group beside it. */
export function setTags(cfg: TagSortConfig): { tag: TagSortTag;
                                               group: TagSortGroup }[] {
  const out: { tag: TagSortTag; group: TagSortGroup }[] = [];
  for (const group of cfg.groups) {
    // A DISABLED GROUP IS NOT IN THE SESSION. This is the one reader — the
    // digits, the summary, the wire and the commit all count through it —
    // so skipping here is the whole of "does not show up and takes no key
    // number". The EDITOR walks `cfg.groups` directly and still shows it,
    // which is the point: it is set aside, not deleted.
    if (group.enabled === false) continue;
    for (const tag of group.tags) out.push({ tag, group });
  }
  return out;
}

export function groupOf(cfg: TagSortConfig, name: string,
                        ): TagSortGroup | null {
  return setTags(cfg).find((x) => x.tag.name === name)?.group ?? null;
}

/** The counter tag a tag's "doesn't fit" writes, or "" for none. */
export function counterOf(cfg: TagSortConfig, name: string): string {
  return setTags(cfg).find((x) => x.tag.name === name)?.tag.negative.trim()
    ?? "";
}

/** Whether a tag left unlit WRITES anything when the picture is committed
 *  — its group's negatives switch, whichever of the two things it writes.
 *  A tag that does not is an implicit negative the fit is told about and
 *  the library never is. */
export function writesUnlit(cfg: TagSortConfig, name: string): boolean {
  const hit = setTags(cfg).find((x) => x.tag.name === name);
  return hit != null && !isGroupRow(hit.tag) && hit.group.negatives;
}

export function modeOf(cfg: TagSortConfig): TagSortMode {
  return tagNames(cfg).length <= 1 ? "single" : "multi";
}

// ---- editing the set -------------------------------------------------------

function mintId(): string {
  return `g${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

/** The set with `name` appended to the group named by `groupId` (the last
 *  group when none is named) and keyed. A name already in the set anywhere
 *  is left where it is; a full set (`MAX_TAGS`) takes nothing more. */
export function withTag(cfg: TagSortConfig, name: string,
                        groupId: string | null = null): TagSortConfig {
  const names = tagNames(cfg);
  if (names.includes(name) || names.length >= MAX_TAGS) return cfg;
  const target = groupId ?? cfg.groups[cfg.groups.length - 1]?.id;
  if (target == null) return cfg;
  const tag: TagSortTag = { name, negative: "" };
  const groups = cfg.groups.map((g) => g.id === target
    ? { ...g, tags: [...g.tags, tag] } : g);
  // NO KEY IS WRITTEN. `cfg.keys` holds the digits somebody CHOSE, and an
  // entry there is what makes a digit stick through a reorder; a tag that
  // has never been re-keyed answers to its POSITION (`keyOf`), so moving
  // rows about renumbers exactly the rows nobody has an opinion about.
  // Writing a key here made every tag opinionated the moment it was added,
  // which is why dragging a row used to leave the keyboard behind.
  return { ...cfg, groups };
}

/** A LIBRARY GROUP appended as a row of `groupId`'s question — the same
 *  rules as `withTag`, keyed by the group's id rather than by a name. */
export function withGroupRow(cfg: TagSortConfig, id: number, label: string,
                             groupId: string | null = null): TagSortConfig {
  const name = groupRowName(id);
  const names = tagNames(cfg);
  if (names.includes(name) || names.length >= MAX_TAGS) return cfg;
  const target = groupId ?? cfg.groups[cfg.groups.length - 1]?.id;
  if (target == null) return cfg;
  const tag: TagSortTag = { name, negative: "", group: id, label };
  return { ...cfg, groups: cfg.groups.map((g) => g.id === target
    ? { ...g, tags: [...g.tags, tag] } : g) };
}

/** A fresh, empty group at the end. */
export function withGroup(cfg: TagSortConfig): TagSortConfig {
  return { ...cfg, groups: [...cfg.groups, emptyGroup()] };
}

export function withoutTag(cfg: TagSortConfig, name: string): TagSortConfig {
  const groups = cfg.groups.map(
    (g) => ({ ...g, tags: g.tags.filter((t) => t.name !== name) }));
  const keys = { ...cfg.keys };
  delete keys[name];
  return { ...cfg, groups, keys };
}

/** The set without that group and its tags — and never without a group:
 *  removing the last one leaves a fresh empty one in its place. */
export function withoutGroup(cfg: TagSortConfig, id: string): TagSortConfig {
  const gone = cfg.groups.find((g) => g.id === id);
  const keys = { ...cfg.keys };
  if (gone) for (const t of gone.tags) delete keys[t.name];
  const groups = cfg.groups.filter((g) => g.id !== id);
  return { ...cfg, keys, groups: groups.length ? groups : [emptyGroup()] };
}

/** The set with a group's switches changed. */
export function updateGroup(cfg: TagSortConfig, id: string,
                            patch: Partial<Omit<TagSortGroup, "id" | "tags">>,
                            ): TagSortConfig {
  return { ...cfg, groups: cfg.groups.map(
    (g) => g.id === id ? { ...g, ...patch } : g) };
}

/** A tag's counter tag set (or cleared with "" — the default negative
 *  again). The tag's own name is no counter. */
export function withCounter(cfg: TagSortConfig, name: string,
                            negative: string): TagSortConfig {
  const clean = negative.trim() === name ? "" : negative.trim();
  const fix = (t: TagSortTag) =>
    t.name === name ? { ...t, negative: clean } : t;
  return { ...cfg, groups: cfg.groups.map(
    (g) => ({ ...g, tags: g.tags.map(fix) })) };
}

/** A tag RENAMED in place — its slot, its group, its digit and its counter
 *  tag all kept. An empty name, or one the set already holds, changes
 *  nothing; a counter equal to the new name becomes the default again. */
export function renameTag(cfg: TagSortConfig, from: string,
                          to: string): TagSortConfig {
  const next = to.trim();
  if (!next || next === from || tagNames(cfg).includes(next)) return cfg;
  if (!plainTags(cfg).includes(from)) return cfg;
  const keys = { ...cfg.keys };
  if (from in keys) { keys[next] = keys[from]; delete keys[from]; }
  return { ...cfg, keys, groups: cfg.groups.map((g) => ({
    ...g, tags: g.tags.map((t) => t.name === from
      ? { name: next, negative: t.negative === next ? "" : t.negative } : t),
  })) };
}

/** The set emptied — the chooser's Clear: one fresh group, nothing in it.
 *  The other settings stay. */
export function clearTags(cfg: TagSortConfig): TagSortConfig {
  return { ...cfg, groups: [emptyGroup()], keys: {} };
}

/** A group moved within the list — the chooser's group drag. */
export function moveGroup(cfg: TagSortConfig, from: number,
                          to: number): TagSortConfig {
  return { ...cfg, groups: moveEntry(cfg.groups, from, to) };
}

/** A tag moved to SLOT `at` of the group named — its own group (a
 *  reorder) or another (a move between groups), the chooser's tag drag.
 *  `at` counts slots in the target's list AS IT IS, so a row's index (or
 *  one past it, for "after") is what a drop hands over; the tag leaving
 *  its own list first is accounted for here. Nothing named, nothing moves. */
export function moveTagTo(cfg: TagSortConfig, name: string, groupId: string,
                          at: number): TagSortConfig {
  const from = groupOf(cfg, name);
  const target = cfg.groups.find((g) => g.id === groupId);
  if (!from || !target) return cfg;
  const tag = from.tags.find((t) => t.name === name)!;
  const fromIdx = from.tags.indexOf(tag);
  let slot = Math.max(0, Math.min(at, target.tags.length));
  if (from.id === target.id && fromIdx < slot) slot -= 1;
  if (from.id === target.id && slot === fromIdx) return cfg;
  return { ...cfg, groups: cfg.groups.map((g) => {
    let tags = g.id === from.id ? g.tags.filter((t) => t !== tag) : g.tags;
    if (g.id === target.id) {
      tags = [...tags.slice(0, slot), tag, ...tags.slice(slot)];
    }
    return tags === g.tags ? g : { ...g, tags };
  }) };
}

/** Move one entry within a list — the chooser's drag. Out-of-range indexes
 *  leave the list exactly as it is. */
export function moveEntry<T>(list: readonly T[], from: number,
                             to: number): T[] {
  const out = list.slice();
  if (from < 0 || from >= out.length || to < 0 || to >= out.length
      || from === to) return out;
  const [moved] = out.splice(from, 1);
  out.splice(to, 0, moved);
  return out;
}

// ---- the digits --------------------------------------------------------------

/** The digit a tag answers to: its own entry, else its position — so a
 *  list nobody re-keyed is the keyboard it always was. */
export function keyOf(cfg: TagSortConfig, tag: string): number {
  const k = cfg.keys?.[tag];
  if (Number.isInteger(k) && k >= 1 && k <= 9) return k;
  return tagNames(cfg).indexOf(tag) + 1;
}

/** Every set tag on a digit, in list order. */
export function tagsForKey(cfg: TagSortConfig, digit: number): string[] {
  return tagNames(cfg).filter((tag) => keyOf(cfg, tag) === digit);
}

/** The largest digit any set tag answers to — what the footer's `1`–`N`
 *  says. */
export function maxKey(cfg: TagSortConfig): number {
  return tagNames(cfg).reduce((m, tag) => Math.max(m, keyOf(cfg, tag)), 0);
}

/** Every tag with a digit: the ones set by hand kept, the rest given
 *  their position — the keyboard an untouched list always was. */
export function fillKeys(keys: Record<string, number>,
                         tags: readonly string[]): Record<string, number> {
  const out = { ...keys };
  tags.forEach((tag, i) => { if (!(tag in out)) out[tag] = i + 1; });
  return out;
}

/** The lowest digit no set tag answers to, else 9.
 *
 *  NOT used when a tag is added any more — a new tag takes its position and
 *  follows a reorder (`withTag`). What is left of it is the KeyPicker's
 *  suggestion and the tests' reading of "which digit is free". */
export function nextFreeKey(cfg: TagSortConfig): number {
  const used = new Set(tagNames(cfg).map((tag) => keyOf(cfg, tag)));
  for (let d = 1; d <= 9; d++) if (!used.has(d)) return d;
  return 9;
}

function parseKeys(raw: unknown, tags: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  if (!raw || typeof raw !== "object") return out;
  for (const [tag, k] of Object.entries(raw as Record<string, unknown>)) {
    const n = Number(k);
    if (tags.includes(tag) && Number.isInteger(n) && n >= 1 && n <= 9) {
      out[tag] = n;
    }
  }
  return out;
}

// ---- the codec ----------------------------------------------------------------

function parseTag(raw: unknown): TagSortTag | null {
  if (typeof raw === "string") {
    return raw ? { name: raw, negative: "" } : null;
  }
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  // A LIBRARY GROUP ROW is named by its ID, so it survives the group being
  // renamed; `label` is only what was on screen when it was picked.
  const gid = typeof o.group === "number" && Number.isInteger(o.group)
    && o.group > 0 ? o.group : null;
  if (gid != null) {
    return { name: groupRowName(gid), negative: "", group: gid,
             label: typeof o.label === "string" ? o.label : "" };
  }
  if (typeof o.name !== "string" || !o.name) return null;
  return { name: o.name,
           negative: typeof o.negative === "string" ? o.negative.trim() : "" };
}

function parseGroups(o: Record<string, unknown>): TagSortGroup[] {
  const out: TagSortGroup[] = [];
  const seen = new Set<string>();
  const ids = new Set<string>();
  const take = (t: TagSortTag | null): TagSortTag | null => {
    if (!t || seen.has(t.name) || seen.size >= MAX_TAGS) return null;
    seen.add(t.name);
    return t;
  };
  const group = (r: Record<string, unknown>, rawTags: unknown,
                 exclusive: boolean, negatives: boolean) => {
    // Both new flags are ABSENT-MEANS-DEFAULT, so an older stored setup
    // parses to exactly what it always did.
    const enabled = r.enabled === false ? false : undefined;
    const advance = r.advance === true ? true : undefined;
    const tags: TagSortTag[] = [];
    if (Array.isArray(rawTags)) {
      for (const t of rawTags as unknown[]) {
        const tag = take(parseTag(t));
        if (tag) tags.push(tag);
      }
    }
    let id = typeof r.id === "string" && r.id ? r.id : mintId();
    if (ids.has(id)) id = mintId();
    ids.add(id);
    out.push({ id, exclusive, negatives, tags,
               ...(enabled === false ? { enabled } : {}),
               ...(advance ? { advance } : {}) });
  };
  for (const e of (Array.isArray(o.groups) ? o.groups : []) as unknown[]) {
    if (!e || typeof e !== "object") continue;
    const r = e as Record<string, unknown>;
    group(r, r.tags, r.exclusive !== false, r.negatives !== false);
  }
  return out.length ? out : [emptyGroup(FIRST_GROUP_ID)];
}

/** localStorage codec — tolerant on the way in (the store is writable by
 *  anything), exact on the way out. */
export function parseTagSortConfig(raw: string | null): TagSortConfig {
  if (!raw) return { ...DEFAULT_CONFIG };
  try {
    const o = JSON.parse(raw) as Record<string, unknown>;
    if (!o || typeof o !== "object") return { ...DEFAULT_CONFIG };
    const groups = parseGroups(o);
    const names = groups.flatMap((g) => g.tags.map((t) => t.name));
    return {
      groups,
      smart: o.smart !== false,
      embedder: typeof o.embedder === "string" && o.embedder
        ? o.embedder : DEFAULT_EMBEDDER,
      // A config written before the option existed asked about everything;
      // pictures are what it was almost always used for and what the
      // classifier can order, so that is what it becomes.
      kind: o.kind === "video" ? "video" : "image",
      skipSequenced: o.skipSequenced === true,
      // MATERIALIZED: every tag gets its digit written down on read, so a
      // reorder can never move one — a config from before the keys took
      // its positions, which is what they were.
      keys: fillKeys(parseKeys(o.keys, names), names),
    };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

/** One row on the way out. A library-group row is written by its ID — a
 *  name would break the moment the group was renamed — and its `label` is
 *  only what to draw before the tree is fetched. */
function serializeTag(t: TagSortTag): Record<string, unknown> {
  return t.group != null
    ? { group: t.group, label: t.label ?? "" }
    : { name: t.name, negative: t.negative };
}

export function serializeTagSortConfig(cfg: TagSortConfig): string {
  return JSON.stringify({
    groups: cfg.groups.map((g) => ({
      id: g.id, exclusive: g.exclusive, negatives: g.negatives,
      ...(g.enabled === false ? { enabled: false } : {}),
      ...(g.advance ? { advance: true } : {}),
      tags: g.tags.map(serializeTag) })),
    smart: cfg.smart,
    embedder: cfg.embedder,
    kind: cfg.kind,
    skipSequenced: cfg.skipSequenced,
    keys: cfg.keys });
}

// ---- presets ---------------------------------------------------------------
//
// Named TAG SETUPS, remembered in the browser — the train job editor's
// presets in this dialog's terms. A preset holds the SET only — the groups
// with their switches, their tags with their counter tags, and the digits —
// and loading one replaces exactly that: which kind is asked about, the
// ordering and the sequence rule are the session's and stay as they are.

export interface TagSortPreset {
  /** `id` rather than the name identifies a preset, so renaming one — and two
   *  presets ending up with the same name — can't overwrite the wrong entry. */
  id: string;
  name: string;
  groups: TagSortGroup[];
  keys: Record<string, number>;
}

export const TAGSORT_PRESETS_KEY = "mc.tagSortPresets";

/** The preset a config's set makes. */
export function presetOf(cfg: TagSortConfig, id: string,
                         name: string): TagSortPreset {
  const back = parseTagSortConfig(serializeTagSortConfig(cfg));
  return { id, name, groups: back.groups, keys: back.keys };
}

/** The config with a preset's set in place of its own. */
export function applyPreset(cfg: TagSortConfig,
                            preset: TagSortPreset): TagSortConfig {
  const names = preset.groups.flatMap((g) => g.tags.map((t) => t.name));
  return { ...cfg, groups: preset.groups.map((g) => ({ ...g, tags: [...g.tags] })),
           keys: fillKeys(preset.keys, names) };
}

/** Tolerant like `parseTagSortConfig` — the store is writable by anything.
 *  A preset stored as a whole CONFIG (the shape before presets narrowed
 *  to the set) is read for its set alone. */
export function parseTagSortPresets(raw: string | null): TagSortPreset[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    if (!Array.isArray(v)) return [];
    return v
      .filter((p) => p && typeof p.name === "string" && p.groups)
      .map((p, i) => {
        const set = parseTagSortConfig(JSON.stringify(
          { groups: p.groups, keys: p.keys }));
        return {
          id: typeof p.id === "string" ? p.id : `p${i}-${p.name}`,
          name: p.name as string,
          groups: set.groups, keys: set.keys,
        };
      });
  } catch { return []; }
}

export function serializeTagSortPresets(list: TagSortPreset[]): string {
  return JSON.stringify(list.map((p) => ({
    id: p.id, name: p.name,
    groups: p.groups.map((g) => ({
      id: g.id, exclusive: g.exclusive, negatives: g.negatives,
      ...(g.enabled === false ? { enabled: false } : {}),
      ...(g.advance ? { advance: true } : {}),
      tags: g.tags.map(serializeTag) })),
    keys: p.keys,
  })));
}

// ---- the wire ----------------------------------------------------------------

/** What the feed is told about the set's shape: every group with a tag in
 *  it (its tags, with its switch) and every counter tag a session would
 *  write — a group's switch off, its counters are not. */
export function wireGroups(cfg: TagSortConfig,
                           ): { tags: string[]; exclusive: boolean }[] {
  return cfg.groups
    .map((g) => ({ tags: g.tags.filter((t) => !isGroupRow(t))
                     .map((t) => t.name),
                   exclusive: g.exclusive }))
    .filter((g) => g.tags.length > 0);
}

export function wireCounters(cfg: TagSortConfig): Record<string, string> {
  const out: Record<string, string> = {};
  for (const { tag, group } of setTags(cfg)) {
    if (isGroupRow(tag)) continue;
    const c = tag.negative.trim();
    if (group.negatives && c && c !== tag.name) out[tag.name] = c;
  }
  return out;
}

// ---- the answers -------------------------------------------------------------

/** What one answer writes, or null for "nothing" (a skip in effect). */
export interface CommitPlan {
  positive: string[];
  negative: string[];
  /** LIBRARY GROUPS the answer puts the picture in — the lit group rows.
   *  Nothing is ever taken OUT: an unlit group row writes nothing. */
  groups: number[];
}

/** A digit (or a chip): every named tag flipped, in order — and lighting
 *  a tag in a MUTUALLY EXCLUSIVE group puts the group's other lit tags out.
 *  Pressing a lit tag's digit puts it out, which is how "none of this
 *  group" is said. Names the set does not hold are ignored. */
export function toggleTags(cfg: TagSortConfig, lit: ReadonlySet<string>,
                           names: readonly string[]): Set<string> {
  const next = new Set(lit);
  for (const name of names) {
    const hit = setTags(cfg).find((x) => x.tag.name === name);
    if (!hit) continue;
    if (next.has(name)) { next.delete(name); continue; }
    if (hit.group.exclusive) {
      for (const t of hit.group.tags) next.delete(t.name);
    }
    next.add(name);
  }
  return next;
}

/** ↓ — the picture as it stands: the lit tags positive (in the list's
 *  order), then for every UNLIT tag of a group that writes negatives its
 *  counter tag positive where it has one, else itself negative — a tag of
 *  a group without the switch writes nothing for "unlit". Nothing at all
 *  is null — a skip in effect, but deliberate.
 *
 *  Lit tags are named, not numbered, for the reason `JudgedEntry.chosen`
 *  is: the list can be edited mid-session, and a toggle held over a reorder
 *  must still mean the tag it was set on. A name the list no longer holds is
 *  simply not in it, so removing a lit tag un-lights it. */
export function planCommit(cfg: TagSortConfig,
                           lit: ReadonlySet<string>): CommitPlan | null {
  const walk = setTags(cfg);
  // The lit tags lead, in the list's order; what "unlit" writes follows.
  const positive = walk.filter((x) => !isGroupRow(x.tag))
    .map((x) => x.tag.name).filter((n) => lit.has(n));
  // A LIT GROUP ROW is a membership, in the list's order beside them.
  const groups = walk.filter((x) => isGroupRow(x.tag) && lit.has(x.tag.name))
    .map((x) => x.tag.group as number);
  const negative: string[] = [];
  for (const { tag, group } of walk) {
    if (lit.has(tag.name) || !group.negatives || isGroupRow(tag)) continue;
    const counter = tag.negative.trim();
    if (counter && counter !== tag.name) {
      if (!positive.includes(counter)) positive.push(counter);
    } else {
      negative.push(tag.name);
    }
  }
  // A name lit and also somebody's counter is positive, once; a name that
  // is both a positive and a negative here is a set contradicting itself,
  // and the positive — the thing somebody lit — wins.
  const neg = negative.filter((n) => !positive.includes(n));
  if (positive.length === 0 && neg.length === 0 && groups.length === 0) {
    return null;
  }
  return { positive, negative: neg, groups };
}

/** Single mode: → is yes, ←/↓ is "not chosen" — which writes the counter
 *  tag or the group's negative, or nothing. */
export function planSingle(cfg: TagSortConfig,
                           positive: boolean): CommitPlan | null {
  const tag = tagNames(cfg)[0];
  if (!tag) return null;
  return planCommit(cfg, new Set(positive ? [tag] : []));
}

/** "None of these" — ↓ with nothing lit, and the `0` key. */
export function planNone(cfg: TagSortConfig): CommitPlan | null {
  return planCommit(cfg, new Set());
}

/** The lit names in the LIST's order — what an answer records as chosen. */
export function chosenOf(cfg: TagSortConfig,
                         lit: ReadonlySet<string>): string[] {
  return tagNames(cfg).filter((n) => lit.has(n));
}

/** Merge a background refetch into the local queue: the item ON SCREEN stays
 *  exactly where it is, the unshown tail is replaced by the fresh ordering,
 *  minus anything already shown or currently queued ahead. */
export function mergeQueue<T extends { item_id: number }>(
  current: T[], incoming: T[], shown: ReadonlySet<number>): T[] {
  const head = current.length > 0 ? [current[0]] : [];
  const headIds = new Set(head.map((r) => r.item_id));
  const tail = incoming.filter(
    (r) => !shown.has(r.item_id) && !headIds.has(r.item_id));
  return [...head, ...tail];
}

/** One decided item on the session's stack — what `↑` pops. */
export interface JudgedEntry<T = unknown> {
  ref: T;
  /** The tag NAMES answered positive (single mode: the one tag, for yes).
   *
   *  Names rather than positions, because the session's tag list is
   *  EDITABLE: a position is not an identity once rows can be reordered or
   *  removed, and the summary read off one would file every earlier answer
   *  under whatever tag now sits at that number. A name that has since left
   *  the list simply matches nothing, which is the honest answer — the
   *  assignment it wrote is still in the library and still revertible. */
  chosen: string[];
  /** Whether anything was WRITTEN (a skip records nothing and is not on the
   *  stack at all; a commit whose plan was null is not either). */
  eventIds: number[];
}

/** The implicit negatives the fit is told about and the library never is:
 *  per tag whose "unlit" writes nothing, the items committed without it.
 *  (`TagSortNextRequest.session_negatives`.) */
export function sessionNegatives(cfg: TagSortConfig,
                                 judged: readonly JudgedEntry<{ item_id: number }>[],
                                 ): Record<string, number[]> | undefined {
  const silent = plainTags(cfg).filter((n) => !writesUnlit(cfg, n));
  if (silent.length === 0) return undefined;
  const out: Record<string, number[]> = {};
  for (const j of judged) {
    const chosen = new Set(j.chosen);
    for (const tag of silent) {
      if (!chosen.has(tag)) (out[tag] ??= []).push(j.ref.item_id);
    }
  }
  return Object.keys(out).length ? out : undefined;
}

/** The close toast's numbers: how many items were decided, and per outcome.
 *  `perTag` is aligned to `tags`, so a tag added mid-session simply starts
 *  at zero and one removed takes its column with it. Skips are deliberately
 *  absent — nothing was written for them. */
export function summarize(judged: readonly JudgedEntry[],
                          tags: readonly string[]): {
  decided: number; perTag: number[]; none: number;
} {
  const at = new Map(tags.map((tag, i) => [tag, i]));
  const perTag = tags.map(() => 0);
  let none = 0;
  for (const j of judged) {
    if (j.chosen.length === 0) none += 1;
    for (const name of j.chosen) {
      const i = at.get(name);
      if (i != null) perTag[i] += 1;
    }
  }
  return { decided: judged.length, perTag, none };
}
