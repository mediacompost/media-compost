/** The client slice everything may use: `req` and the library READS.
 *
 * `shared/` and `query/` may import neither `app/` nor `train/`, and both
 * need to talk to the server — the query builder for its catalogs and match
 * counts, the chrome for machine state (health, settings, the HF token).
 * This module is that surface, CUT out of the app's client rather than
 * declared a second time; `app/api.ts` spreads it back into its own `api`
 * so no app call site knows the difference.
 *
 * `itemsQuery` here is deliberately the LITE declaration — the handful of
 * fields a match count or a pivot preview reads. The grid's rich `ItemPage`
 * stays in the app, whose own `itemsQuery` overrides this one in the spread.
 */

import type { Group as QueryGroup } from "../query/tree";
import { apiFetch } from "./build";

/** A refusal from the API, with the STATUS still on it.
 *
 *  The message alone is what a person reads, but the number is what decides
 *  whether asking again could ever help: React Query retries a failed query
 *  three times with a growing pause, so a 400 — "this request is wrong" —
 *  spent about seven seconds being asked again, identically, before the error
 *  was allowed on screen. `main.tsx` reads this to stop retrying a 4xx. */
export class ApiError extends Error {
  readonly status: number;
  /** The refusal's unfilled English template and its slot values, when the
   *  server sent them (`detail_key`/`detail_vars` beside `detail`) — what
   *  lets `useErrText` say the refusal in the UI language. `message` stays
   *  the interpolated English and is always the fallback. */
  readonly key?: string;
  readonly vars?: Record<string, string>;
  constructor(message: string, status: number,
              key?: string, vars?: Record<string, string>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.key = key;
    this.vars = vars;
  }
}

/**
 * What went wrong, in words.
 *
 * The body is FastAPI's `{"detail": …}` — a sentence for a refusal we wrote,
 * a list of field errors for one Pydantic wrote. Every overlay shows what it
 * catches straight to the reader, so leaving it as raw JSON put
 * `422: {"detail":[{"type":"string_too_short",…}]}` in a dialog footer. Read
 * here, once, rather than in each of them.
 */
interface ErrorParts { text: string; key?: string; vars?: Record<string, string> }

async function errorParts(r: Response): Promise<ErrorParts> {
  const text = await r.text();
  try {
    const body = JSON.parse(text);
    const d = body?.detail;
    if (typeof d === "string" && d) {
      return typeof body?.detail_key === "string" && body.detail_key
        ? { text: d, key: body.detail_key, vars: body.detail_vars ?? {} }
        : { text: d };
    }
    if (Array.isArray(d) && d.length) {
      // A validation list: the message, and the field it is about where that
      // is not obvious from the message alone.
      return { text: d.map((e) => {
        const where = Array.isArray(e?.loc)
          ? e.loc.filter((x: unknown) => typeof x === "string" && x !== "body")
              .join(".")
          : "";
        return where ? `${where}: ${e?.msg ?? ""}` : String(e?.msg ?? "");
      }).filter(Boolean).join("; ") };
    }
    if (typeof body?.message === "string" && body.message)
      return { text: body.message };
  } catch { /* not JSON — the text itself is the best there is */ }
  return { text: text ? `${r.status}: ${text}` : `${r.status}` };
}

async function req<T>(url: string, opts?: RequestInit): Promise<T> {
  const r = await apiFetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    const e = await errorParts(r);
    throw new ApiError(e.text, r.status, e.key, e.vars);
  }
  return r.json() as Promise<T>;
}

export interface GroupNode {
  id: number;
  name: string;
  icon: string;
  color: string | null;
  /** A SMART group: membership derived from its stored search — no manual
   *  assignment, no child groups. */
  smart?: boolean;
  count: number;
  // Tags this group assigns (positive) or removes (negative) from its items.
  tags: { name: string; negative: boolean }[];
  children: GroupNode[];
}

export interface LibraryStats {
  items: number;
  files: number;
  bytes: number;
  images: number;
  videos: number;
  sequences: number;
  hidden: number;
  pending: number;
  pending_tags: number;
  pending_captions: number;
  pending_faces: number;
  /** Pictures SOME ranking has placed — the badge on the sidebar's Rankings
   *  row, which is a scope of its own. Distinct across rankings: a picture
   *  two of them placed is one picture in that grid. */
  ranked: number;
  groups: number;
  tags: number;
  data_dir: string;
  /** What this library calls a near-duplicate — the Hamming distance the
   *  `SIMILAR:` condition takes when it names none of its own. */
  phash_threshold: number;
  // Free / total bytes of the volume holding the library (0 = unreadable).
  disk_free: number;
  disk_total: number;
}

/** One line of the Storage page: a KEY the frontend words, and what it costs.
 *  The backend never sends a label — the words live in the catalogs, like
 *  every other string this UI shows. */
export interface StorageRow {
  key: string;
  count: number;
  bytes: number;
}

/** One artifact TYPE, which is the unit the page's delete button acts on:
 *  `kind` + `model` travel back to the delete endpoint verbatim. `cache` is
 *  what makes the question different — a latent is re-encoded by the next
 *  run, a depth map is a model run to do again. */
export interface StorageArtifactRow {
  kind: string;
  model: string;
  count: number;
  bytes: number;
  cache: boolean;
}

export interface StorageOut {
  data_dir: string;
  items: StorageRow[];
  artifacts: StorageArtifactRow[];
  other: StorageRow[];
  /** Already counted in `items` — a trashed item is still a stored one until
   *  it is deleted for good. */
  trashed: StorageRow;
  disk_free: number;
  disk_total: number;
}

/** The Storage page's file-prune rule. Both numbers are MINIMUMS a file must
 *  clear, so a file below either is removed; 0 means the threshold is not set.
 *  The two keep flags spare what the thresholds matched. */
export interface StoragePruneRule {
  keep_active: boolean;
  keep_edited: boolean;
  min_megapixels: number;
  min_short_edge: number;
  min_long_edge: number;
  /** "" is every kind; "image" or "video" confines the rule to one. A SCOPE
   *  rather than a threshold — it narrows what the rest of the rule is asked
   *  about, and never becomes another reason to remove a file. */
  kind: "" | "image" | "video";
}

/** What a prune did — or, from the preview, what it would do. `items` is the
 *  count left with no file at all and therefore deleted, which is the figure
 *  that says a rule aimed at duplicates is about to remove pictures. */
export interface StoragePruneOut {
  files: number;
  bytes: number;
  items: number;
}

/** A prune RUN. Removing gigabytes is minutes of work, so the request that
 *  starts it answers at once with this and the page polls it: `files` and
 *  `bytes` are the running totals, `total` the file count the preview
 *  promised — fixed at the start, because the rule matches fewer files with
 *  every committed chunk and a recomputed total would never be reached. */
export interface StoragePruneJob extends StoragePruneOut {
  id: string;
  status: "running" | "done" | "cancelled" | "error";
  total: number;
  /** The failure, when `status` is "error". */
  message: string;
}

/** WHICH tags the Tags tab lists and in what order — parallel arrays, one
 *  entry per tag, because the same 250,000 answers are 6 MB this way and
 *  60 MB as objects. See `api.tagIndex`. */
export interface TagIndex {
  ids: number[];
  names: string[];
  /** THE NUMERIC COLUMNS THIS TAG SET HAS, in the order the header draws
   *  them: the library counts pictures three ways (`positive`, `implicit`,
   *  `negative`); an imported set carries what this library has under the
   *  name (`library`) and what its file claimed (`count`). One list draws
   *  whichever pair belongs to what it is showing, and every sort and every
   *  range filter speaks these keys. */
  columns: string[];
  /** …and the numbers themselves, one array per column, parallel to
   *  `names`. `null` where the tag set has no figure at all, which is
   *  not zero: zero is a tag that exists and is on nothing. A library
   *  column is never null — a name with no assignments is on none. */
  numbers: Record<string, (number | null)[]>;
  /** The name of the tag an alias points at, "" for an ordinary tag. */
  alias_of: string[];
  /** POSITIONS in the arrays above of the tags the autocomplete does not
   *  offer — a handful of indices rather than a flag per row, since that is
   *  what it is in a catalog this size. On the INDEX because the mark is
   *  about every row: read off the per-window detail fetch it blinked out
   *  of the whole list on every filter change until the band landed. */
  hidden: number[];
  /** …and the ones the autocomplete does not offer because their NAMESPACE
   *  is hidden. A second list because it is not the same fact: only the
   *  row's own flag can be undone from the row. Disjoint from `hidden`. */
  hidden_ns: number[];
  total: number;
  /** How many rows the "unassigned" filter would leave, over everything else
   *  the view is narrowed by — the filter menu's count. */
  unassigned_total: number;
  /** THE FIRST SCREENFUL, WHOLE — the same rows `api.tagRows` answers, for
   *  the leading ids, so a fresh listing arrives complete.
   *
   *  The index is names and counts; everything else about a row used to be
   *  a second request for the band on screen, which meant a new listing
   *  drew twice — names, then a round trip later the comments, the trails
   *  and the capsules under them, moving every row on the page. Empty when
   *  the caller did not ask (`rows`). */
  rows?: TagRow[];
}

/** One TAG SET's claim on a name — the derived capsule behind it: the set's
 *  key and its popularity figure for the name (a booru's post count), null
 *  where the set counts nothing. Nothing is written for it; disabling the
 *  set takes every such capsule with it on the next fetch. */
export interface TagSetRef {
  key: string;
  /** The set's display name — what the chip says. */
  name: string;
  count: number | null;
}

/** One tag set's description of a name, for the `?` popover's switcher. */
export interface TagSetText {
  key: string;
  text: string;
  /** Where the set files the tag — the names down to its category,
   *  `["people", "girls"]`, empty for an uncategorized entry. */
  trail?: string[];
  /** The set's own popularity figure, where it has one. */
  count?: number | null;
  /** The entry's other spellings, what it entails, and — the same table read
   *  the other way — the entries of that set which entail it. */
  aliases?: string[];
  implies?: string[];
  implied_by?: string[];
  /** WHAT THE SET LABELS THE NAME WITH — its meta tags. Often the whole of
   *  what a bulk import knows about a name: which kind of name it is, what
   *  a dataset should do with it. */
  meta?: string[];
  /** THE ENTRY'S OWN NAME, where the name asked about is a SPELLING of it.
   *  Empty when they are the same. A set answers for an alias with its
   *  entry's row, so without this the popover showed a description for
   *  something it never named. */
  alias_of?: string;
  /** What the set says the TAG is — its one-liner, and whether the name is
   *  a subject, a place or an event. The popover is often the only place a
   *  name is met (a field, an autocomplete row), so "who is this" belongs
   *  in it and not only in the Sets tab's list. */
  comment?: string;
  subject?: { name?: string; since?: number | null } | null;
  place?: { name?: string; lat?: number | null; lon?: number | null;
            parent?: string } | null;
  event?: { name?: string; start?: number | null; end?: number | null;
            parent?: string } | null;
}

export interface TagSetSubject {
  /** The display name where it differs from the tag; "" is the tag's own. */
  name: string;
  /** A partial date — `YYYYMMDD` with zeros, the library's own encoding. */
  since: number | null;
}

export interface TagSetPlace {
  /** What it is CALLED — one line, an address or "Bob's house".
   *  `Location.name` in the library, and the same word everywhere else. */
  name: string;
  lat: number | null;
  lon: number | null;
  /** The place this one is IN, by its TAG name. */
  parent: string;
}

export interface TagSetEvent {
  name: string;
  start: number | null;
  end: number | null;
  parent: string;
}

export interface TagRow {
  id: number;
  name: string;
  comment: string;
  /** THE LONG FORM, the library's own. `descriptions` below is what the
   *  enabled foreign SETS say about the same name — a tag can be described
   *  twice now, and the `?` draws this one first, because the library is
   *  the tag set somebody is actually working in. */
  description?: string;
  /** Where the library FILES it — a category of its own set, null for
   *  uncategorized. Authored (a row is dragged into one) and so unrelated to
   *  the namespace, which is derived from the name and cannot be chosen.
   *  `category_trail` is the names down to it: a LIST, never a joined
   *  string, since a category name may contain a slash. */
  category_id?: number | null;
  category_trail?: string[];
  /** THIS ROW'S NUMBER IN EACH OF THE TAG SET'S COLUMNS (`TagIndex.
   *  columns`). An ALIAS answers with its target's, which is what the cell
   *  shows; `null` is a figure the tag set does not have. */
  numbers?: Record<string, number | null>;
  // When set, this tag is an alias for the named tag; positive/negative then
  // carry the linked tag's counts (the flat tag list shows them as empty).
  alias_of?: string | null;
  /** Kept out of the AUTOCOMPLETE. Not a deletion and not a scope: the tag
   *  assigns, searches, counts and is listed exactly as before — it just
   *  stops being suggested while somebody types. */
  hidden?: boolean;
  /** …not offered either, because its NAMESPACE is hidden. A different
   *  fact: the row cannot undo it (the rule is a setting over a prefix),
   *  so the mark it wears says so and does nothing when pressed. */
  hidden_ns?: boolean;
  /** Tags this one entails: assigning it also assigns these, transitively.
   *  Replaced the single parent — a tag may imply any number of others.
   *  Always empty for an alias (assigning it redirects to its target). */
  implies?: string[];
  /** What the TAG SET says about this tag — "noflip", "character" — in the
   *  same namespace links, captions and tag groups use. Shown as capsules
   *  behind the name in the tag / subject / place / event lists and NOWHERE
   *  else: it annotates the tag, not the pictures carrying it. */
  meta_tags?: string[];
  /** The NONZERO per-meta counts — pictures the tag has where each meta tag
   *  says ("tumblr": 50). Never folded into `positive`; the capsules show
   *  them and equal counts sort by the highest. Sparse: almost every
   *  assignment is a plain mark. */
  meta_counts?: Record<string, number>;
  /** What the enabled TAG SETS say about this name, derived per read. The
   *  whole-catalog listing carries `descriptions` as null ("not fetched");
   *  the window's rows carry every set's text for the popover. */
  tag_sets?: TagSetRef[];
  descriptions?: TagSetText[] | null;

  // ---- what only an imported SET's row says ------------------------------
  //
  // A set is ADVICE: it says what a name means, what it entails and what
  // the library's tag should BE, and the row says how much of that this
  // library has taken. Absent on the library's own rows, which are the
  // thing the advice is about.
  /** The OTHER SPELLINGS of this name. They are rows of the list in their
   *  own right (each with `alias_of` naming this one); the editor holds
   *  them as a field, so a save carries them through untouched. */
  aliases?: string[];
  /** The LIBRARY has this name (or an alias resolving to it). */
  in_library?: boolean;
  /** Those of `implies` the library does not entail — the row strikes them
   *  through: advice nothing acted on, since a set's implications reach the
   *  library only when the door CREATES the tag. */
  missing_implies?: string[];
  /** …and the same for the other kind: which of the comment and the three
   *  records the library's tag does not have. */
  missing_records?: string[];
  /** This entry's implications are switched off — by its category, one
   *  above it, or the whole set — so the row does not draw them at all. */
  implications_off?: boolean;
  /** The file's own order, which is one of the sorts. */
  position?: number;
  /** WHAT THE SET SAYS THE TAG IS. A record present but EMPTY says the
   *  kind and nothing more, which is the whole of what a tag set often
   *  knows, so `{}` and `null` are different answers. */
  subject?: TagSetSubject | null;
  place?: TagSetPlace | null;
  event?: TagSetEvent | null;
}

export interface SubjectRow {
  id: number;
  display_name: string;
  comment: string;
  tag: string;
  tag_id: number | null;
  /** Partial date: YYYYMMDD with zeros for what is unknown (see subjects/when). */
  since_date: number | null;
  items: number;
  implies: string[];
  /** SOMEBODY DECIDED THIS IDENTITY HAS NO NAME — a background character, an
   *  extra. Told apart from a subject nobody has looked at yet, which is
   *  what the Faces tab calls UNKNOWN: this one is an answer. */
  unnamed?: boolean;
}

// A place: where a picture is. Location data hangs off a TAG, so `tag` is the
// identity slug (empty for an unnamed place — a photo's bare GPS) and `items`
// is that tag's count.
export interface PlaceRow {
  id: number;
  tag: string;
  tag_id: number | null;
  /** WHAT IT IS CALLED — one free text line, and the only text a place
   *  carries: "Invalidenstraße 43, 10115 Berlin", "the corner of the old
   *  market", "Bob's house". It was eight typed components, a per-country
   *  form and a country field beside them. */
  name?: string;
  /** The place this one is IN — assigning it implies the parents. */
  parent_id?: number | null;
  /** What it IS beside where it is — the name answers "where" and never
   *  "which of the two on this street". The identity TAG's, so an unnamed
   *  place has none. */
  comment?: string;
  lat: number | null;
  lon: number | null;
  items: number;
}

// An event: what was happening. Like a subject and a place it is extra data on
// a TAG, so `tag` is the identity slug and `items` is that tag's count. The
// dates are PARTIAL (YYYYMMDD with zeros, see subjects/when.ts). Its places
// ride along whole because a row wants to show an address.
export interface EventRow {
  id: number;
  tag: string;
  tag_id: number | null;
  display_name: string;
  comment: string;
  /** The event this one is PART OF — assigning it implies its parents. */
  parent_id?: number | null;
  start_date: number | null;
  end_date: number | null;
  places: PlaceRow[];
  items: number;
}

/** The opt-in paging envelope several list endpoints share: without `limit`
 *  they answer the bare array they always have; with it, one page plus the
 *  FILTERED total, so a list can say how far it pages. */
export interface Paged<T> {
  rows: T[];
  total: number;
}

/** One autocomplete row from `GET /api/tags/names` — the cheap typing-driven
 *  source (substring match in SQL, ranked by direct count desc then name),
 *  so suggesting a tag never means fetching the whole catalog. */
export interface TagNameRow {
  name: string;
  /** What the row SAYS about the tag, in a line — the same comment the full
   *  tag list carries. The typing-driven path used to send none while the
   *  static one showed it, so one list said different things depending on
   *  where it was opened. The LONG form is a tag set's (`descriptions`). */
  comment?: string;
  positive: number;
  /** The tag this row is an ALIAS of, when it is one — the row is shown with
   *  an arrow to it, and picking it assigns the target. Absent for an
   *  ordinary tag. */
  alias_of?: string | null;
  /** The nonzero per-meta counts, for the hover — the ordering already used
   *  them server-side (equal counts sort by the highest). */
  meta_counts?: Record<string, number>;
  /** What the tag set says about the tag, for the row's capsules. Every
   *  name, counted or not — `meta_counts` is sparse and so cannot say which
   *  of them exist. */
  meta_tags?: string[];
  /** The enabled tag sets' claims on the name and their descriptions. A row
   *  the LIBRARY does not have yet (a set-only suggestion) has `positive` 0
   *  and at least one `tag_sets` entry; picking it creates the tag. */
  tag_sets?: TagSetRef[];
  descriptions?: TagSetText[];
}

// One filterable metadata name in the library catalog (intrinsic or indexed).
export interface MetadataCatalogEntry {
  name: string;
  mtype: "numeric" | "text" | "date";
  count: number;
  num_min?: number | null;
  num_max?: number | null;
  // For an enumerated text name (e.g. format / mode): the values present in the
  // library, so the builder offers a dropdown instead of a free-text field.
  values?: string[] | null;
}

// A named, persisted query (the serialized string form; the backend stores it
// opaquely and never parses it).
export interface SavedSearch {
  name: string;
  query: string;
}

// The POST body for a structured item search: scope + the parsed condition tree.
export interface ItemSearchBody {
  query: QueryGroup | null;
  groups?: number[];
  ungrouped?: boolean;
  untagged?: boolean;
  trash?: boolean;
  hidden?: boolean;
  show_hidden?: boolean;
  kind?: string;
  sequence?: number | null;
  /** Drop every item that belongs to a sequence — the sessions' "Skip
   *  pictures in sequences". */
  hide_sequenced?: boolean;
  /** FOLD SEQUENCES: drop a member exactly where a sequence holding it has
   *  its own item in this same view, so a chapter and its pages are not
   *  both on screen — and the pages stay wherever the chapter is not (a
   *  group holding them but not it, sequences unticked in the kinds). */
  fold_sequenced?: boolean;
  pending?: boolean;
  pending_kind?: string;
  /** A RANKING'S OWN VIEW: the items it has placed, in its standings order,
   *  best first — `ranking_pool` narrows that to one pool's fit. The
   *  order is the ranking's, so the sort control stands down for it, the way
   *  it does for a sequence. */
  ranking?: number | null;
  ranking_pool?: number | null;
  /** The ranking's SET-ASIDE pictures instead of its placed ones. No
   *  standing to order by, so the ordinary sort applies. */
  ranking_dismissed?: boolean;
  page?: number;
  page_size?: number;
  sort?: string;
}

export interface AppSettings {
  // Optional per-model-family local paths, keyed by family id.
  model_paths: Record<string, string>;
  // Double-click behavior. Image: "none" | "annotate" | "editor". Video: "none" | "editor".
  dblclick_image: string;
  dblclick_video: string;
  // Which Florence-2 checkpoint the action menus offer.
  florence_model: string;
  // Language & Region: UI language ("en" | "de"), date-display pattern (see
  // DATE_FORMAT_OPTIONS) and the 24-hour clock toggle.
  language: string;
  date_format: string;
  time_24h: boolean;
  /** Hide AI actions whose dependencies or weights are not ready, instead of
   *  offering them with a "needs download" chip. Server-wide; default off. */
  hide_unready_actions: boolean;
  /** Take the Faces tab out of the header. The TAB and nothing else:
   *  detection still runs and Pending → Faces still fills. Server-wide;
   *  default off. */
  hide_faces_tab: boolean;
  /** Prepended to the tag name INVENTED for a new subject ("subject:"). A tag
   *  typed by hand is never touched. Library-wide, not per user. */
  // Prepended to the tag INVENTED for a new subject / place / event, so each
  // kind gets a namespace of its own. A tag typed by hand is never touched.
  subject_tag_prefix: string;
  place_tag_prefix: string;
  event_tag_prefix: string;
  face_match_threshold: number;
  /** The tag detected watermarks are recorded under (boxes on it — what the
   *  box-driven removal consumes). Empty falls back to "watermark". */
  watermark_tag: string;
  /** OPTIONAL: a tag every OCR run additionally records its regions' boxes
   *  under. Empty = off. */
  text_tag: string;
}

// Progress of a runnable model setup (GET /api/ml/setup/{plugin_key}).
export interface SetupStatus {
  running: boolean;
  ok: boolean;
  error: string;
  log: string;
}

/** The fields of one search hit that the shared callers read (the pivot
 *  preview and the sample pickers); the app's `ItemPage` rows carry more. */
export interface ItemHit {
  id: number;
  uid: string;
  name: string;
  kind: string;
  active_file_id: number | null;
  thumb_token: string;
}

export const api = {
  groups: () => req<GroupNode[]>("/api/groups"),

  /** `namesOnly` skips every values array — pair it with `metadataValues`
   *  fetched on demand for the one name whose dropdown is open. */
  metadataCatalog: (namesOnly = false) =>
    req<MetadataCatalogEntry[]>(
      `/api/metadata/catalog${namesOnly ? "?names_only=true" : ""}`),

  /** Distinct text values for ONE metadata name (case-insensitive substring
   *  filter, limited in SQL) — the on-demand complement of `names_only`. */
  metadataValues: (name: string, q = "", limit = 50) => {
    const p = new URLSearchParams({ name, q, limit: String(limit) });
    return req<string[]>(`/api/metadata/values?${p.toString()}`);
  },

  savedSearches: () => req<SavedSearch[]>("/api/settings/saved-searches"),

  putSavedSearches: (list: SavedSearch[]) =>
    req<SavedSearch[]>("/api/settings/saved-searches", {
      method: "PUT",
      body: JSON.stringify(list),
    }),

  libraryStats: () => req<LibraryStats>("/api/library/stats"),

  /** What is using the library's disk, by type of item and of artifact. */
  libraryStorage: () => req<StorageOut>("/api/library/storage"),

  /** Delete every artifact of one type. `model` omitted means every model of
   *  that kind; `""` means the rows that name none — two different questions,
   *  so the parameter is only sent when it is being asked. */
  deleteStorageArtifacts: (kind: string, model?: string) => {
    const p = new URLSearchParams({ kind });
    if (model !== undefined) p.set("model", model);
    return req<{ ok: boolean; deleted: number; bytes: number }>(
      `/api/library/storage/artifacts?${p.toString()}`, { method: "DELETE" });
  },

  /** Throw away the copies the schema upgrades left behind. Only files named
   *  the way a backup is named — the folder is the app's, but anything else
   *  in it is somebody's. */
  deleteStorageBackups: () =>
    req<{ ok: boolean; deleted: number; bytes: number }>(
      "/api/library/storage/backups", { method: "DELETE" }),

  /** What the rule would remove. A read-only POST (see `READ_ONLY_POSTS`
   *  server-side): the rule is a body, and it counts without writing. */
  previewFilePrune: (rule: StoragePruneRule) =>
    req<StoragePruneOut>("/api/library/storage/file-prune/preview", {
      method: "POST",
      body: JSON.stringify(rule),
    }),

  /** Start removing every file the rule matches, and answer with the run to
   *  poll. Irreversible — an item left with no file goes with its last one.
   *  The everything-rule is still refused synchronously, with the 400 it has
   *  always had, since the rule is checked before the run exists. */
  runFilePrune: (rule: StoragePruneRule) =>
    req<StoragePruneJob>("/api/library/storage/file-prune", {
      method: "POST",
      body: JSON.stringify(rule),
    }),

  filePruneStatus: (id: string) =>
    req<StoragePruneJob>(`/api/library/storage/file-prune/${id}`),

  /** Stop after the chunk in flight. What is already committed stays
   *  removed — those bytes are gone. */
  cancelFilePrune: (id: string) =>
    req<StoragePruneJob>(`/api/library/storage/file-prune/${id}`,
                         { method: "DELETE" }),

  tags: () => req<TagRow[]>("/api/tags"),

  /** Cheap typing-driven autocomplete: names matching `q`, ranked by direct
   *  count desc then name — never the whole catalog. */
  tagNames: (q: string, limit = 50) => {
    const p = new URLSearchParams({ q, limit: String(limit) });
    return req<TagNameRow[]>(`/api/tags/names?${p.toString()}`);
  },

  /** The VALUE row's namespace source: every namespace holding value-shaped
   *  tags, with how many — its own endpoint, because a count-ranked sample
   *  of `/names` never surfaces them on a big library. */
  valueNamespaces: (q: string, limit = 50) => {
    const p = new URLSearchParams({ q, limit: String(limit) });
    return req<{ name: string; count: number }[]>(
      `/api/tags/value-namespaces?${p.toString()}`);
  },

  // ---- places ----
  places: () => req<PlaceRow[]>("/api/places"),

  // ---- events ----
  events: () => req<EventRow[]>("/api/events"),

  // ---- subjects ----
  subjects: () => req<SubjectRow[]>("/api/subjects"),

  linkTags: () => req<string[]>("/api/link-tags"),

  // ---- app settings ----
  getSettings: () => req<AppSettings>("/api/settings"),

  hfTokenStatus: () => req<{ token_available: boolean }>("/api/settings/hf-token"),

  setHfToken: (token: string) =>
    req<{ token_available: boolean }>("/api/settings/hf-token", {
      method: "PUT", body: JSON.stringify({ token }),
    }),

  clearOffline: () => req<{ env_offline: string }>("/api/ml/clear-offline", { method: "POST" }),

  setupStatus: (pluginKey: string) => req<SetupStatus>(`/api/ml/setup/${pluginKey}`),

  /** Up, plus the launch-time facts the UI needs before it draws. `training`
   *  false hides the Train / Evaluate / Models tabs, and the routes behind
   *  them are refused too. */
  health: () => req<{ ok: boolean; training: boolean }>("/api/health"),

  // A file's stored bytes are already in their final orientation. ``rotation``
  // is only used as a cache-busting query param: when a rotate replaces a
  // derived file's bytes in place (same file id), a changed value forces the
  // browser to re-fetch instead of serving the stale thumbnail.
  // `token` (a content hash) cache-busts on content changes at the same file id
  // (e.g. a reused rowid); `rotation` cache-busts an in-place rotate.
  thumbUrl: (fileId: number, rotation = 0, token = "") => {
    const p = [];
    if (rotation) p.push(`r=${rotation}`);
    if (token) p.push(`v=${token}`);
    return p.length ? `/api/files/${fileId}/thumb?${p.join("&")}` : `/api/files/${fileId}/thumb`;
  },
  // Structured search, narrowly typed (see ItemHit above). The `groups`
  // flattening matches the app's rich version — the wire is the same.
  itemsQuery: (body: ItemSearchBody, signal?: AbortSignal) =>
    req<{ items: ItemHit[]; total: number }>("/api/items/query", {
      signal,
      method: "POST",
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
};

export { req };
