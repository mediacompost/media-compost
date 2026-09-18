// UI / selection state (server data lives in React Query).
import type { ReactNode } from "react";
import { storage } from "../shared/storage.ts";
import { APP_PREFS } from "./prefs.ts";
import { create } from "zustand";

import { coveredByWindow } from "./covered";
import { composeOverPage } from "./overPage";
import { overlayIsOpen } from "../shared/Overlay";
import { confirm } from "../shared/ConfirmModal";
import { activeLang, fillVars, translate } from "../shared/i18nCore";
import { isSettingsPage, readPlace, scopeFromPlace, VIEW_PATHS } from "./location";
import {
  HISTORY_CAP, HISTORY_MAX_ENTRY, navWindow, pushHistory, sameEntry,
  selectionUpdate,
} from "./selection";
import {
  assignNumber, lowestFreeNumber, newQaSet, parseQaSets, serializeQaSets,
  sortSets, type QaSet,
} from "./qaSets";

export type View = "library" | "tags" | "faces" | "history"
  | "train" | "evaluate" | "models";
/** The two halves of the item window: labelling the picture, or changing it.
 *  One window, one item, two things you can be doing to it. */
export type ItemMode = "annotate" | "edit";
// A tag to highlight in the grid, with the assignment sign to match.
export interface TagHl { name: string; negative: boolean }
export type Overlay = null | "import" | "editor" | "group" | "settings";

// The ONE writer of the selection pair: `selectedItems` (the public list —
// many consumers iterate it) and `selectedSet` (its lockstep Set, for O(1)
// membership in the grid's render/marquee paths) only ever change together,
// through selectionUpdate's allocation-free no-change check. Returns null when
// nothing changed, so callers can spread `...(selWrite(s, ids) ?? {})`.
function selWrite(
  s: { selectedItems: number[]; selectedSet: ReadonlySet<number> },
  next: number[]
): { selectedItems: number[]; selectedSet: ReadonlySet<number> } | null {
  const u = selectionUpdate(s.selectedItems, s.selectedSet, next);
  return u && { selectedItems: u.list, selectedSet: u.set };
}

// Category/filter navigation resets the (live) grid selection. The pinned
// selection is kept separately in `pinnedItems`, so browsing never disturbs it.
/** EVERY SCOPE FIELD, CLEARED — what each of the sidebar's scope setters
 *  starts from before naming the one it is about.
 *
 *  They each used to spell the whole tuple out, so a scope field ADDED to
 *  the store had to be remembered in eleven places, and the one that forgot
 *  would not fail: it would leave the OLD scope half-set under the new one
 *  (picking a group while a ranking was open, and getting both). The
 *  backend has the same rule one layer down, in `search.scope_of`.
 *
 *  `mediaKinds` is NOT here: it is an orthogonal FILTER rather than a scope,
 *  and the two setters that keep it say so themselves. */
const NO_SCOPE = {
  selectedGroups: [] as number[],
  ungrouped: false,
  untagged: false,
  trashView: false,
  hiddenView: false,
  pendingView: false,
  pendingKind: null as "tags" | "captions" | "faces" | null,
  sequenceView: null as number | null,
  rankingView: null as number | null,
  rankingPool: null as number | null,
  rankingDismissed: false,
  rankedView: false,
};

function keepSel(
  s: { selectedItems: number[]; selectedSet: ReadonlySet<number> }
): Partial<{ selectedItems: number[]; selectedSet: ReadonlySet<number> }> {
  return selWrite(s, []) ?? {};
}

// How many items a multi-open (editor/annotator tabs) will open at once — each
// id is a tab with its own detail fetch, and a window of hundreds of tabs is
// an accident, not a request.
const MULTI_OPEN_CAP = 30;

function confirmMultiOpen(count: number): Promise<boolean> {
  // The store has no `t`; the sheet's words are looked up the way a `t` would.
  const say = (s: string, vars?: Record<string, string | number>) =>
    fillVars(translate(activeLang(), s), vars);
  return confirm({
    title: say("Open the first {cap} of {n} selected items?",
               { cap: MULTI_OPEN_CAP, n: count }),
    answer: { label: say("Open") },
  });
}

// Grid sort: a field plus a direction (so any field can be flipped asc/desc).
// The backend takes them combined as "<field>_<dir>", e.g. "recent_desc".
// "taken" is when the picture was TAKEN (what somebody typed, else the file's
// own EXIF date — never the span of its events, which is a range, not a
// point); "recent" keys off the last-imported date, refreshed on every
// re-import. "color" orders by `File.color_key`, which is packed so that
// sorting by it reads as a gradient. Items with no answer at all — undated,
// or a video with no colour — sort LAST in both directions.
//
// "random" is the odd one out: it has no key to read off an item at all. It
// is a shuffle, deterministic per SEED so the pages of one view agree with
// each other, and the dice button is what draws a new seed. A direction over
// a shuffle would mean nothing, and so would a grouping.
export type SortField =
  "taken" | "recent" | "modified" | "resolution" | "name" | "color" | "random";
export type SortDir = "asc" | "desc";

/** Which way each sort field STARTS, before anybody has flipped it.
 *
 *  A direction is a property of the field, not of the grid: newest-first is
 *  what a date means to look at, A–Z is what a name means, and dark-to-light
 *  is what the colour ordering was built to read as. One shared direction made
 *  every switch a second click, and the pair is remembered per field from then
 *  on (`sortDirs`) so coming back to a field comes back to how you left it. */
const SORT_DIR_DEFAULTS: Record<SortField, SortDir> = {
  taken: "desc", recent: "desc", modified: "desc", resolution: "desc",
  name: "asc", color: "asc", random: "asc",
};

// HOW THE GRID'S FLAT ORDER IS CUT INTO SECTIONS. Always a coarsening of the
// active sort key, which is what lets the backend prepend it to the same
// ORDER BY and so make every group a contiguous run of the page order — the
// property the whole grouped layout is derived from.
export type GroupBy =
  "none" | "day" | "month" | "year" | "initial" | "mp" | "band" | "bucket";

/** The groupings legal for one sort field. ONE list, read by the toolbar's
 *  dropdown, by `setSortField`'s normalization and by the jump popover — the
 *  backend refuses a pair that is not in its own copy, so a third opinion
 *  here would show a choice that 400s. */
export function groupOptionsFor(f: SortField, ranking = false): GroupBy[] {
  // A RANKING VIEW ANSWERS ITS OWN, whatever the sort field says: its order
  // is the standings and the sort control stands down, so the only coarsening
  // that means anything over it is the standings' own BUCKETS — and that one
  // always does, which is why a ranking view arrives grouped where no other
  // view does.
  if (ranking) return ["none", "bucket"];
  switch (f) {
    case "taken": case "recent": case "modified":
      return ["none", "day", "month", "year"];
    case "name": return ["none", "initial"];
    case "resolution": return ["none", "mp"];
    case "color": return ["none", "band"];
    // A shuffle has no coarsening: every section would hold whatever the
    // shuffle happened to put next to each other, which is not a grouping.
    case "random": return ["none"];
  }
}

// Grid media-type filter. An empty `mediaKinds` array means "all kinds"; any
// non-empty subset restricts the grid to those kinds.
export type Kind = "image" | "video" | "sequence";

// Range-filter selections. `null` for a key means "no constraint" (full domain).

// ---- the Tags tab, as it was left -------------------------------------------
// Mirrors the sub-tab and filter types in `TagsView`; kept here because the tab
// is unmounted whenever another view is showing, and rebuilding the narrowing
// every time you come back is the whole complaint.
/** Item-tag list: the media kinds the counts are over; empty is every kind. */
export type TagsMedia = Kind[];
/** Which page of the Tags tab is open — and there is no sub-tab STRIP any
 *  more, because what is left is one list.
 *
 *  `items` is it. `links` is the same list one KIND along (the meta tags),
 *  reached from the left column's Meta row; `tagsets` is the same list
 *  again, pointed at an imported set by its pill. Neither is a page of its
 *  own; both are here because the tab remembers how you left each.
 *
 *  What LEFT: `faces` became a TAB (`View`) — which crops are one person is
 *  not a question about a row in a list of names — and `rankings` went to
 *  the LIBRARY, where the standings a ranking produces are the grid's own
 *  sections. Both had stopped being a variant of this list long before. */
export type TagsMode = "items" | "links" | "tagsets";

/** What a CALLER may ask for, which is not the same set.
 *
 *  `subjects`, `places` and `events` were sub-tabs and are not any more: a
 *  subject, a place and an event are extra data ON a tag, so each of those
 *  lists was the Items list cut one way, and the cut is the `kind` filter.
 *  An old address and an old caller may still ASK for one — both doors,
 *  `location.readPlace` and `setTagsMode`, turn the ask into the Items list
 *  narrowed to that kind — but nothing can put the store INTO one, which is
 *  why they are named here and not in `TagsMode`. */
export type TagsModeAsked = TagsMode | "subjects" | "places" | "events";

/** The settings overlay's pages. "tagging" is where what ENDS IN A TAG lives:
 *  the prefix on a tag the app invents for a new subject, place or event, and
 *  the tag names a detector writes its findings onto. It was sections of
 *  General once, and a page called "behaviors" before that; an address still
 *  naming that one lands here.
 *
 *  "faces" is the FACES TAB'S OWN PAGE (owner 2026-09): whether the tab is
 *  offered at all, and how alike two faces must be before the app names one
 *  by itself. That threshold had been read as a tagging setting — naming a
 *  face does assign that subject's tag — but it is the one number the face
 *  work turns on, and a page it shares with the tab's own switch says more
 *  about it than a page it shares with three prefixes. */
export type SettingsPage = "general" | "actions" | "tagging" | "faces"
  | "storage";
/** How a tag row relates to another tag — the item list's own axis. Mutually
 *  exclusive: an alias entails nothing, so both at once is an empty table. */
export type TagsRelation = "all" | "aliases" | "implies";
/** Item-tag list: whether the AUTOCOMPLETE offers the tag. */
export type TagsSuggest = "all" | "hidden" | "shown";

/** What is narrowed AWAY — one axis, so one single-choice group.
 *
 *  TWO ANSWERS, where there were five. `faces` and `pending` were about a
 *  person, and people are the Faces tab now; `untagged` was about a record
 *  with no identity tag, which cannot exist. */
export type TagsScope = "all" | "unassigned";
/** The item list's namespace parents: grouped (the default), or the flat
 *  list they replaced. */
export type TagsGrouping = "grouped" | "flat";
// `when` is the Events list's span column. The Places list borrows
// `tag_groups` for its tag — the same string column under a second name — but
// nothing here could plausibly mean a span of days, and a memo sorting by
// `start_date` under `comment` would be lying about what it sorts by.
//: The name and the comment, then one key per NUMERIC COLUMN of whichever
//  tag set is on screen (`tagSetColumns.ts`: the library's
//  positive/implicit/negative, an imported set's library/count), a set's
//  two orders of its own (`position`, the file's; `category`, where it is
//  filed) and the Meta list's four carriers. A string, because the columns
//  are a table the server names rather than a list spelled here twice.
export type TagsSortKey = string;
/** What the new-group dialog starts from — the menu entry's meaning,
 * captured at the click. Nothing is created until Save. */
export interface GroupCreateSeed {
  smart: boolean;
  smartQuery: string;
  parent: number | null;
  members:
    | { ids: number[] }
    | { view: Record<string, unknown> }
    | null;
  /** Groups to MOVE INSIDE the new one once it exists — "group these", the
   *  sidebar's context menu over a selection of several. The dialog is still
   *  what creates anything (nothing is created from a menu), so this rides on
   *  the seed exactly as the starting members do; the parent field then
   *  excludes these and their subtrees, since a new group inside one of them
   *  could not hold it. */
  childGroups?: number[];
}

export interface TagsViewState {
  mode: TagsMode;
  /** Item-tag list: which kind of tag (plain / subjects / places / events). */
  kind: "all" | "plain" | "subjects" | "places" | "events";
  /** Item-tag list: which MEDIA the counts are over — every item, or only
   *  the images, the videos or the sequences. */
  media: TagsMedia;
  /** Item-tag list: which relation between tags. */
  relation: TagsRelation;
  /** Every list: what it is narrowed to. */
  scope: TagsScope;
  /** Item-tag list: namespace parent rows on, or the flat list. */
  grouping: TagsGrouping;
  /** THE SIDEBAR'S AUTHORED AXIS — the categories the list is narrowed to.
   *  Several is the UNION, each taken with its subtree the way the tree's
   *  own counts take it, and `uncategorized` is the tree's last fixed row
   *  joining that same union. Empty with `uncategorized` off is
   *  "Everything". */
  category: number[];
  uncategorized: boolean;
  /** …and the DERIVED half beside it: the text before the first colon.
   *  A NAMESPACE READS AS A CATEGORY holding the names made with it (owner
   *  2026-09) — picked in the same list of rows, several being the union,
   *  and one picked beside a real category lists the tags in EITHER. (They
   *  intersected until then, which meant a plain click in the lower block
   *  usually emptied the list.) Picking any FLATTENS the list where every
   *  row shares one, since a parent row over the whole list says nothing.
   *  Empty is no narrowing. */
  namespaces: string[];
  /** Item-tag list: a strip of REPRESENTATIVE pictures under each tag —
   *  the Subjects list's face strips, for tags. */
  reps: boolean;
  /** Item-tag list: narrowed by whether the AUTOCOMPLETE offers the tag —
   *  "all", "hidden" or "shown". The tag's own flag, never the namespace
   *  rule: that one is a setting with its own control, and a list narrowed
   *  by it would simply be a list of the dump it was made for. */
  suggest: TagsSuggest;
  /** Item-tag list: narrowed to the tags carrying this META tag, "" for no
   *  narrowing. A meta tag is the mark a bulk import leaves, which makes it
   *  the one cut through a catalog of 200,000 names that nobody has to type
   *  — so the capsule on a row IS the control. */
  metaTag: string;
  /** Item-tag list: a MIN/MAX on a count column, `null` for no bound. The
   *  columns are what the list is read for — "which tags am I using twice"
   *  is a question about a number in a cell — so they are what it narrows
   *  by, and the control sits on the column it is about. */
  /** A range per NUMERIC COLUMN of the tag set on screen, keyed by the
   *  column (`tagSetColumns.ts`): the library's three counts of pictures,
   *  an imported set's `library` and `count`. Open-ended, so `{lo, hi}`
   *  with either half null. */
  counts: Record<string,
                 { lo: number | null; hi: number | null }>;
  /** SETS sub-tab: how the entry list is narrowed. Here rather than in
   *  `TagSetsView` for the reason the fields above are: a sub-tab's
   *  narrowing has to survive a look at another sub-tab, and a component
   *  that unmounts on the switch cannot keep it. */
  entryAliases: boolean;
  entryImplies: boolean;
  /** With a description, without one, or (null) either. */
  entryDescribed: boolean | null;
  /** Only what the LIBRARY has not caught up with. */
  entryBehind: boolean;
  /** …and the other kind of advice: entries whose comment or
   *  record the library's tag does not have. Both on is the
   *  union — anything the library has not caught up with. */
  entryBehindRecords: boolean;
  /** Only entries that ARE one of these — subject / place / event, any
   *  combination, and several is the union. The sidebar's three rows set
   *  exactly one; the filter menu ticks any. */
  entryRecords: string[];
  /** A tag name to land on: the row is scrolled into view and flashed once,
   *  then this is cleared. Switching sub-tab alone leaves you to find the thing
   *  you clicked in a list of a hundred. */
  focus: string | null;
  /** A tag set CATEGORY to land on, as the names down to it — the Sets tab
   *  resolves the trail against the set it is showing, opens its ancestors
   *  and picks it. By trail rather than by id because the caller is a
   *  description popover, which knows what a SET said and not what this
   *  library numbered it. Cleared the moment it lands. */
  focusCategory: string[] | null;
  /** Landing on the tag should also OPEN its entry editor — what the `?`
   *  popover's pencil asks for. Rides with `focus` and is cleared with it. */
  focusEdit: boolean;
  search: string;
  sortKey: TagsSortKey;
  sortDir: SortDir;
}

/** A sub-tab's starting point. Only `mode` differs between them; the sort does
 *  too, since a table of names and a table of counts want opposite defaults. */
export function tagsModeDefaults(mode: TagsMode): TagsViewState {
  const byName = mode === "tagsets";
  return {
    mode,
    kind: "all",
    media: [],
    relation: "all",
    scope: "all",
    grouping: "grouped",
    category: [],
    uncategorized: false,
    namespaces: [],
    reps: false,
    suggest: "all",
    metaTag: "",
    counts: { positive: { lo: null, hi: null },
              implicit: { lo: null, hi: null },
              negative: { lo: null, hi: null } },
    entryAliases: false,
    entryImplies: false,
    entryDescribed: null,
    entryBehind: false,
    entryBehindRecords: false,
    entryRecords: [],
    focus: null,
    focusCategory: null,
    focusEdit: false,
    search: "",
    sortKey: mode === "items" ? "positive" : byName ? "name" : "links",
    sortDir: byName ? "asc" : "desc",
  };
}

/** The state a sub-tab should be in on arrival: how it was left, or its
 *  defaults the first time. The one-shot landings (`focus` and friends) are
 *  the caller's to set, since they are the REASON for the arrival. */
function tagsModeState(s: { tagsView: TagsViewState;
                            tagsViewByMode: Partial<Record<TagsMode, TagsViewState>> },
                       mode: TagsMode): TagsViewState {
  if (s.tagsView.mode === mode) return s.tagsView;
  return { ...(s.tagsViewByMode[mode] ?? tagsModeDefaults(mode)), mode };
}

/** …and the half that parks the sub-tab being LEFT, so it is there next
 *  time. Nothing to park when the arrival is where we already are. */
function enterTagsMode(s: { tagsView: TagsViewState;
                            tagsViewByMode: Partial<Record<TagsMode, TagsViewState>> },
                       mode: TagsMode) {
  return s.tagsView.mode === mode ? {}
    : { tagsViewByMode: { ...s.tagsViewByMode, [s.tagsView.mode]: s.tagsView } };
}

interface UIState {
  view: View;
  // When set, the History tab shows only changes affecting these item ids.
  historyFilter: number[];
  overlay: Overlay;
  // The Settings overlay's currently-visible page (remembered across opens).
  settingsPage: SettingsPage;
  setSettingsPage: (p: SettingsPage) => void;
  // A model key to highlight (and scroll into view) when the Settings→Models page
  // opens (set when starting a download / enabling downloads from the Actions
  // menu). Cleared once scrolled to; the highlight lingers briefly after.
  settingsFocusModel: string | null;
  setSettingsFocusModel: (key: string | null) => void;
  // When true, scroll to the "enable downloads" warning banner rather than the
  // focused model's card (the model is still highlighted). Set when the focus was
  // triggered by an "Enable downloads" chip, whose action lives in that banner.
  settingsFocusWarning: boolean;
  setSettingsFocusWarning: (v: boolean) => void;
  selectedGroups: number[];
  ungrouped: boolean;
  // When true, the grid shows only items with no tags (analogous to ungrouped).
  untagged: boolean;
  // When true, the grid shows the Trash (soft-deleted items) instead of a group.
  trashView: boolean;
  // When true, the grid shows the Hidden items (analogous to trashView).
  hiddenView: boolean;
  // When true, the grid shows the "Pending" category: items with unapproved
  // AI-generated tags/captions (analogous to trashView).
  pendingView: boolean;
  // Narrows the Pending category to only pending tags or only pending captions
  // (null = both). Meaningful only while `pendingView` is true.
  pendingKind: "tags" | "captions" | "faces" | null;
  // When set, the grid shows the members of this sequence (in position order),
  // ignoring the group/ungrouped/trash scope. Cleared by any other navigation.
  sequenceView: number | null;
  // A RANKING'S OWN VIEW: which ranking, and which pool of it (null = every
  // pool it holds). The grid is then what that ranking has PLACED, in its
  // standings order — best first, and the sort control stands down, the way
  // it does for a sequence.
  rankingView: number | null;
  rankingPool: number | null;
  /** The Rankings row's own view: a card per ranking, not their pictures. */
  rankedView: boolean;

  // …or its SET-ASIDE pictures instead of its placed ones. Ranking-wide,
  // never per pool, and with no standing to order by — so the sort control
  // stays live here where the placed view disables it.
  rankingDismissed: boolean;
  // Grid media-kind filter (orthogonal). Empty = all kinds.
  mediaKinds: Kind[];
  // FOLD SEQUENCES: when on, a sequence's members give way to the sequence
  // itself wherever both would be in the view — and stay wherever it would
  // not be (a group holding the pages but not the chapter, sequences
  // unticked in the media kinds). The condition is the server's to answer;
  // all that travels is the flag (`fold_sequenced`). On by default.
  foldSequenced: boolean;
  // Overlay hidden items into the grid (dimmed); they stay out of all counts.
  showHiddenItems: boolean;
  expanded: Record<number, boolean>;
  selectedItems: number[];
  // The SAME selection as a Set, kept in lockstep with `selectedItems` (both
  // are only ever written through the internal `selWrite` helper). The grid
  // reads this for O(1) membership per card and per marquee frame.
  selectedSet: ReadonlySet<number>;
  // Anchor item for shift-range selection (the last item picked without shift).
  anchorItem: number | null;
  // Which OCCURRENCES (sequence membership rows) the selection gestures named,
  // inside a sequence view. Selection stays by ITEM id — a repeated page
  // picked anywhere is one picture — but the grid says which copy you MEANT
  // (that one keeps the solid ring) and the sidebar's "Remove from sequence"
  // takes only the copies the gesture named. The grid writes it; a selection
  // made by something that names no occurrence leaves an item untracked, and
  // such an item's copies are all primary.
  selMembers: ReadonlySet<number>;
  // Back/forward history of item selections (browser-style). A programmatic
  // navigation (e.g. clicking a derived/original link) pushes the prior
  // selection onto `selPast`; a fresh manual selection clears `selFuture`.
  selPast: number[][];
  selFuture: number[][];
  // When true, the right sidebar is pinned to `pinnedItems`: the grid selection
  // can still change freely (browse the grid), but the sidebar keeps showing the
  // pinned set until unpinned, at which point it follows the grid selection again.
  pinnedSelection: boolean;
  // The frozen selection the sidebar shows while pinned (empty when unpinned).
  pinnedItems: number[];
  gridSize: number;
  /** The FACES grid's own S/M/L. Its own field, not the library grid's: a
   *  crop is not a picture, and the size that reads well for a wall of
   *  128 px faces is not the one that reads well for photographs. */
  faceSize: number;
  sortField: SortField;
  sortDir: SortDir;
  /** How each field was last sorted — read when switching back to it. */
  sortDirs: Record<SortField, SortDir>;
  /** Which shuffle. Only read while `sortField` is "random"; the dice button
   *  draws a new one, which is the whole of "shuffle again". */
  sortSeed: number;
  shuffle: () => void;
  groupBy: GroupBy;
  search: string;
  // Tag names currently multi-selected in the sidebar's Assigned Tags list;
  // the grid highlights items that carry all of them with the matching sign.
  tagHighlight: TagHl[];
  /** Group ids currently picked in the right sidebar's Groups list. The grid
   *  rings the items that are in ALL of them — the tag rule one object along,
   *  and the same question a pick raises there: which of the pictures on
   *  screen are in this too. DIRECT membership, which is what the row says;
   *  a group's subtree is a different claim and belongs to the tree. */
  groupHighlight: number[];
  /** A group the left sidebar should REVEAL: expand its ancestors, scroll to
   *  it and flash it once. The tree clears it when it lands — a stale id
   *  would flash a row the next time that tree rendered. Set by the right
   *  sidebar's "Show in the sidebar", which cannot do the revealing itself:
   *  the tree owns its own shape and its own scroller. */
  groupFocus: number | null;
  editorItemId: number | null;
  /** Which half of the item window each TAB is showing — annotate or edit.
   *
   *  Per tab, because a window can hold a page you are labelling and a
   *  photograph you are retouching, and the mode is a fact about what you are
   *  doing to THAT item. Tabs with no entry take `editorMode` below, which is
   *  whichever half the window was opened on. */
  editorModes: Record<number, ItemMode>;
  /** What a tab with no answer of its own shows: the mode the window was
   *  opened in — the last segment of `/item/<ids>/<mode>`. */
  editorMode: ItemMode;
  setEditorMode: (id: number, mode: ItemMode) => void;
  setDefaultEditorMode: (mode: ItemMode) => void;
  // Item ids open as tabs in the image editor (Photoshop-style). The active tab
  // is ``editorItemId``. A tab bar appears when two or more are open.
  editorTabs: number[];
  visibleItemIds: number[];
  groupEditId: number | null;
  openGroupEditor: (id: number) => void;
  // A group being MADE — nothing exists until the dialog's Save creates it,
  // so Cancel creates nothing. `members` is captured at the menu click (the
  // rate overlay's scope rule: the dialog must not chase the grid).
  groupCreate: GroupCreateSeed | null;
  openGroupCreator: (seed: GroupCreateSeed) => void;
  // Quick-Assign tag sets (persisted; up to QA_NUM_MAX of them carry a number
  // key — see app/qaSets.ts for the rules). There is always at least one.
  qaSets: QaSet[];
  // The set the assign button, Shift+Q and qaMode stamp — a list index, or
  // null for none, which makes those surfaces open the Q overlay instead.
  qaSelected: number | null;
  // When true, clicking an image in the grid stamps the SELECTED set onto it
  // instead of selecting it. Independent of the selection: with no set (or an
  // empty one) the mode stays ARMED and a click simply selects as usual —
  // there is nothing to stamp — so picking a set later re-arms it in place.
  qaMode: boolean;
  // The feature's master switch (persisted): off, every quick-assign surface
  // is inert — Q, Shift+Q, the bare digit keys, the click-to-assign mode and
  // the assign button. Nine bare keys that write tags deserve an off switch.
  qaEnabled: boolean;
  // The Q overlay (QuickAssignOverlay), and a mirror of the T overlay's open
  // state — the two keyboard overlays refuse to stack, and each one's key
  // handler reads the other's state imperatively.
  qaOverlay: boolean;
  quickTagOpen: boolean;
  // The R overlay (RateOverlay): which ranking it is rating, or null. A third
  // member of the keyboard-overlay family, refusing to stack like the others.
  rateRankingId: number | null;
  /** A ranking the rate CHOOSER should open pre-ticked — the context menu's
   *  door for a ranking with several pools, where "Rate on X" cannot say
   *  which pool without asking. Consumed by the chooser's seeding. */
  rateChooserSeed: number | null;
  /** The tag-batch overlay (the fourth keyboard-overlay family member). */
  tagSortOpen: boolean;
  /** The tag-grid overlay — a batch of pictures pre-sorted into three bands
   *  for one tag. Its OWN action beside the tag batch, never a mode of it;
   *  it sits UNDER Quick Look (see `LAYER.session`), which is the preview
   *  its cards open. */
  tagGridOpen: boolean;
  /** The ESTIMATE dialog — a ranking's scale carried to the pictures it has
   *  never been shown, and tags written at thresholds somebody sets. Not a
   *  session: an ordinary dialog that makes one bulk write. */
  estimateOpen: boolean;
  // QuickLook-style large preview (toggled with Space). By default it previews
  // the live grid selection; `quickLookItems`, when set, overrides that with an
  // explicit target (used by the sidebar preview button so a *pinned* sidebar
  // item can be previewed while the grid selection is elsewhere).
  quickLook: boolean;
  quickLookItems: number[] | null;
  /** A strip the preview draws UNDER the picture while a session lends it
   *  one — the tag grid's answer capsule for the card being looked at. The
   *  session owns it (sets it while the preview is up, clears it after);
   *  the preview only renders whatever is there. */
  previewFooter: ReactNode | null;
  setPreviewFooter: (v: ReactNode | null) => void;
  // When set, QuickLook previews this specific source file (the Files list's
  // preview button) instead of the item's active file.
  quickLookFile: { itemId: number; fileId: number; video: boolean } | null;
  /** Opened from inside a dialog — see `openQuickLook`'s `raised`. */
  quickLookRaised: boolean;
  // WHERE IN THE PICTURE and WHEN IN THE FILM the preview is about — set by
  // the Links tab's preview button, which knows things the item itself does
  // not: a `frame` link carries the moment the still was taken at, and a crop
  // link carries the region it was cut from. Both are facts about the LINK, so
  // they travel with the open rather than being looked up inside the preview.
  quickLookAt: number | null;
  /** Where in `quickLookItems` the preview OPENS — a strip's clicked
   *  thumbnail, so "3 / 8" means the third of the row; null starts at the
   *  anchor item, else the first. */
  quickLookStart: number | null;
  quickLookBoxes: { x?: number | null; y?: number | null;
                    w?: number | null; h?: number | null }[] | null;
  setQuickLook: (v: boolean) => void;
  toggleQuickLook: () => void;
  // Open QuickLook for an explicit set of items (the sidebar preview button).
  /** `at` seeks a film to that second; `boxes` are drawn on the picture, in
   *  fractions of the frame like every other box here. */
  openQuickLook: (items: number[],
                  opts?: { at?: number | null;
                           boxes?: UIState["quickLookBoxes"];
                           start?: number;
                           /** Opened from inside a DIALOG, so it has to sit
                            *  above one (`LAYER.previewRaised`) and take the
                            *  Escape while it is up. */
                           raised?: boolean }) => void;
  // Open QuickLook on one specific source file of an item.
  openQuickLookFile: (itemId: number, fileId: number, video: boolean) => void;

  // Append a set (lowest free number, or none when all nine are taken) and
  // select it. Never refused — sets are unlimited.
  createQaSet: () => void;
  // Delete a set; deleting the last remaining one leaves a fresh empty set.
  deleteQaSet: (index: number) => void;
  // Toggle-select a set (selecting the selected one deselects). qaMode is
  // left alone either way — armed with nothing to stamp, it simply waits.
  selectQaSet: (index: number | null) => void;
  // Give a set a number key (or none). A taken number is exchanged.
  setQaNumber: (index: number, num: number | null) => void;
  // Per-set editing — every drawer row is its own live editor.
  addQaTag: (index: number, tag: string) => void;
  removeQaTag: (index: number, tag: string) => void;
  // Group memberships a set stamps beside its tags.
  addQaGroup: (index: number, groupId: number) => void;
  removeQaGroup: (index: number, groupId: number) => void;
  // Flip a tag between the set's positive and negative lists.
  flipQaTag: (index: number, tag: string) => void;
  toggleQaMode: () => void;
  // Turning the feature OFF also exits the click-to-assign mode — a mode of
  // a disabled feature is a click that does nothing.
  toggleQaEnabled: () => void;
  setQaOverlay: (v: boolean) => void;
  setQuickTagOpen: (v: boolean) => void;
  /** The item whose caption is being typed in the right sidebar, or null.
   *  The grid draws a big preview of it over itself while it is set —
   *  describing a picture from a 200px sidebar thumbnail is describing it
   *  from memory. Written by `CaptionsSection` (both kinds), read by the
   *  grid; the annotator renders the same section and simply has no grid to
   *  read it, which is right — the picture is already on screen there. */
  captionPreview: number | null;
  setCaptionPreview: (id: number | null) => void;
  quickCaptionOpen: boolean;
  setQuickCaptionOpen: (v: boolean) => void;
  /** A bumped counter the C overlay watches — the quick-actions menu opens
   *  it through this, exactly as the T one is opened. */
  quickCaptionSignal: number;
  requestQuickCaption: () => void;
  // A bumped counter the T overlay watches — the toolbar's Quick-actions
  // menu opens it through this, since the overlay's open state is its own.
  quickTagSignal: number;
  /** Explicit items for the requested quick tag — the tag-batch session's T,
   *  which aims at the picture ON SCREEN rather than the grid's selection.
   *  null = the ordinary rule (selection, else the view). */
  quickTagItems: number[] | null;
  requestQuickTag: (items?: number[]) => void;
  setRateRanking: (id: number | null) => void;
  setRateChooserSeed: (id: number | null) => void;
  setTagSortOpen: (open: boolean) => void;
  setTagGridOpen: (open: boolean) => void;
  setEstimateOpen: (open: boolean) => void;

  setView: (v: View) => void;
  // The training job selected in the Train tab's detail pane (survives tab
  // switches; null = empty state).
  trainJobUid: string | null;
  /** Tags → Sets: the set that is open (`?set=` in the address). */
  tagSetId: number | null;
  setTagSetId: (id: number | null) => void;
  setTrainJobUid: (uid: string | null) => void;
  // How the Tags tab was left — which sub-tab, and how that sub-tab was
  // narrowed. It lives here rather than in TagsView so that leaving the tab and
  // coming back does not undo the narrowing you set up to do the work; the
  // component's own transient state (selected rows, open editors) is not kept,
  // since it names rows that may be gone by then.
  tagsView: TagsViewState;
  setTagsView: (patch: Partial<TagsViewState>) => void;
  // EACH SUB-TAB REMEMBERS ITS OWN NARROWING. Switching used to reset to
  // defaults, on the reasoning that each sub-tab's filters mean different
  // things — true, and the reason they are kept APART rather than thrown
  // away: setting the Items list to show representative pictures, glancing
  // at Subjects and coming back is not a request to undo it. The state each
  // sub-tab was left in is parked here and handed back on return.
  //
  // (The reset used to be an effect on `mode`, which fired on every remount
  // and so wiped exactly what is now being kept. It is an ACTION for that
  // reason and stays one.)
  tagsViewByMode: Partial<Record<TagsMode, TagsViewState>>;
  setTagsMode: (mode: TagsModeAsked, focus?: string | null) => void;
  // Switch to the History tab filtered to the given items (empty = jump with no
  // filter). Used by the "View history" button in the right sidebar.
  showHistoryFor: (ids: number[]) => void;
  /** SHOW A TAG WHERE ITS SET FILES IT — from a description popover, which
   *  can be open anywhere (a sidebar field, an autocomplete list) and knows
   *  only the set and the name. One gesture: the Tags view, its Sets
   *  sub-tab, that set picked, and the name in `tagsView.focus` for the
   *  list to land on. */
  showTagInTagSet: (setId: number, name: string, edit?: boolean) => void;
  /** The same gesture for a CATEGORY: the Tags view, its Sets sub-tab, that
   *  set picked, and the trail for the tree to open and select. */
  showCategoryInTagSet: (setId: number, trail: string[]) => void;
  setHistoryFilter: (ids: number[]) => void;
  setOverlay: (o: Overlay) => void;
  setSearch: (s: string) => void;
  setGridSize: (n: number) => void;
  setFaceSize: (n: number) => void;
  setSortField: (f: SortField) => void;
  setSortDir: (d: SortDir) => void;
  setGroupBy: (g: GroupBy) => void;
  toggleSortDir: () => void;
  setTagHighlight: (tags: TagHl[]) => void;
  setGroupHighlight: (ids: number[]) => void;
  setGroupFocus: (id: number | null) => void;

  toggleMediaKind: (kind: Kind) => void;
  toggleFoldSequenced: () => void;
  toggleShowHiddenItems: () => void;

  selectGroup: (id: number, additive: boolean) => void;
  setSelectedGroups: (ids: number[]) => void;
  clearGroupSelection: () => void;
  showAllItems: () => void;
  showKind: (kind: Kind) => void;
  showUngrouped: () => void;
  showUntagged: () => void;
  showTrash: () => void;
  showHidden: () => void;
  showPending: (kind?: "tags" | "captions" | "faces" | null) => void;
  showRanking: (id: number, pool?: number | null) => void;
  showRanked: () => void;
  showRankingDismissed: (id: number) => void;
  showSequence: (id: number) => void;
  toggleGroupExpanded: (id: number) => void;
  // Expand or collapse many groups at once (used for Alt+click subtree toggles).
  setGroupsExpanded: (ids: number[], open: boolean) => void;
  clearItemSelection: () => void;
  selectItem: (
    id: number,
    mods: { meta: boolean; shift: boolean },
    ordered?: number[]
  ) => void;
  setSelectedItems: (ids: number[]) => void;
  setSelMembers: (m: ReadonlySet<number>) => void;
  selectionBack: () => void;
  selectionForward: () => void;
  togglePinned: () => void;
  /** Open the item window on a set of items, in one half or the other.
   *  The four named openers below are all this. */
  openItemWindow: (
    ids: number[], mode: ItemMode,
    focus?: { id: number; tag: string; group: number | null } | null,
  ) => void;
  openEditor: (id: number, focusTag?: string) => void;
  // Open several items at once as tabs of ONE item window (first id active).
  openEditorMulti: (ids: number[]) => void;
  // Open the item window's annotate half (optionally focusing a tag+group,
  // which seeds the header add-bar and its highlight).
  openAnnotator: (id: number, focusTag?: string, focusGroup?: number | null) => void;
  /** WHICH SIDEBAR TAB the annotator should land on, set by whatever opened
   *  it. Every list in the library sidebar offers Annotate now, and the one
   *  you pressed it in is the one you want to go on working in — arriving on
   *  Tags and having to find Captions again is the button not finishing its
   *  sentence. Consumed and cleared by the annotator on arrival, like
   *  `editorFocusTag`: a value left lying about would re-open that tab the
   *  next time the window opened for any reason at all. */
  annotateTab: string | null;
  openAnnotatorAt: (id: number, tab: string) => void;
  clearAnnotateTab: () => void;
  /** Open the annotator on a whole selection — one tab each, like the editor. */
  openAnnotatorMulti: (ids: number[]) => void;
  /** Close the item window: every tab, and the mode each was in. */
  closeItemWindow: () => void;
  /** Put the library BEHIND the item window on one item, and close the window.
   *
   *  "Show in library" means show me it there, so the overlay gets out of the
   *  way. It was a message on the `mc-sync` channel plus a walk up the opener
   *  chain to find which window was the library and a named-target open to
   *  raise it — none of which a state change in one document needs. */
  showItemInLibrary: (itemId: number, uid: string | null) => boolean;
  /** A tag the annotate half should land on, set by the caller that opened it.
   *  It was handed over in `localStorage` because the window it was going to
   *  was a different document; here it is simply state, read and cleared. */
  editorFocusTag: { id: number; tag: string; group: number | null } | null;
  clearEditorFocusTag: () => void;
  // Switch to a tab, adding it if it isn't open yet (also used to seed the
  // window's first tab).
  setEditorItem: (id: number) => void;
  // Navigate the *active* tab to another item (prev/next through the grid) —
  // replaces the current tab rather than opening a new one.
  navigateEditor: (id: number) => void;
  // Close an editor tab; activates a neighbour (or none when it was the last).
  closeEditorTab: (id: number) => void;
  setVisibleItemIds: (ids: number[]) => void;
  /** Items the sidebar is POINTING AT rather than selecting — currently the
   *  other end of a picked link. The grid rings them in a second colour, so
   *  "this row is that picture" is answered by looking rather than by
   *  navigating away from the row that asked. Never the selection: selecting
   *  them would change what every other panel is about. */
  pointedItemIds: number[];
  setPointedItemIds: (ids: number[]) => void;
}

const EXPANDED_KEY = "mc.expandedGroups";
// What the grid SHOWS, remembered like the other view settings: a library
// where the pages of every chapter are hidden is a different library to work
// in, and having to say so again on every visit is the kind of setting people
// stop using. Not in the URL — that says WHERE you are, and these two say how
// you like looking at it (the card size and the tag mode are stored the same
// way).

/** A remembered boolean, with its own default where nothing is stored. */
export function loadFlag(key: string, fallback: boolean): boolean {
  try {
    const raw = storage.get(key);
    return raw === null ? fallback : raw === "1";
  } catch {
    return fallback;
  }
}

export function saveFlag(key: string, on: boolean): void {
  try {
    storage.set(key, on ? "1" : "0");
  } catch {
    /* a full or disabled store just means no memory */
  }
}
const SETTINGS_PAGE_KEY = "mc.settingsPage";

// The Quick-Assign sets and which one is selected are personal working state,
// remembered like `mc.qaMode` — the old stash was in-memory only, so a reload
// threw away exactly the sets somebody had bothered to save.
const QA_SETS_KEY = "mc.qaSets";
const QA_SELECTED_KEY = "mc.qaSelected";

function loadQaSets(): QaSet[] {
  try {
    return parseQaSets(storage.get(QA_SETS_KEY));
  } catch {
    return parseQaSets(null);
  }
}

function saveQaSets(sets: QaSet[]): void {
  try {
    storage.set(QA_SETS_KEY, serializeQaSets(sets));
  } catch {
    /* a full or disabled store just means no memory */
  }
}

function loadQaSelected(len: number): number | null {
  try {
    const raw = storage.get(QA_SELECTED_KEY);
    if (raw === null) return null;
    const i = Number(raw);
    return Number.isInteger(i) && i >= 0 && i < len ? i : null;
  } catch {
    return null;
  }
}

function saveQaSelected(i: number | null): void {
  try {
    if (i == null) storage.remove(QA_SELECTED_KEY);
    else storage.set(QA_SELECTED_KEY, String(i));
  } catch {
    /* ignore */
  }
}

function loadExpanded(): Record<number, boolean> {
  try {
    return JSON.parse(storage.get(EXPANDED_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveExpanded(e: Record<number, boolean>) {
  try {
    storage.set(EXPANDED_KEY, JSON.stringify(e));
  } catch {
    /* ignore */
  }
}

// The address bar is the source of truth for "where you are" at startup: a
// reload, a bookmark or a Back button all land here (see location.ts).
const START = readPlace();
const START_SCOPE = scopeFromPlace(START);

const START_QA_SETS = loadQaSets();
const START_QA_SELECTED = loadQaSelected(START_QA_SETS.length);

/**
 * IS THE ITEM WINDOW OVER EVERYTHING RIGHT NOW?
 *
 * It used to be a browser window, so nothing behind it could hear a key. As an
 * OVERLAY the library is still mounted underneath with its window-level
 * shortcuts listening — Space would open Quick Look while the annotator was
 * playing a film, Delete would remove the selected groups behind an editor
 * buffer — so every one of those handlers asks this first.
 *
 * Read imperatively, INSIDE the handler, never subscribed: those listeners are
 * registered once on purpose and must not re-subscribe on every change.
 */
export const itemWindowIsOpen = (): boolean =>
  useUI.getState().editorTabs.length > 0;

/** THE SUBSCRIBED TWIN, for the queries rather than the key handlers: is the
 *  library BEHIND the item window?
 *
 *  The window is an overlay and the library stays mounted underneath it —
 *  deliberately, so a page turn keeps the grid's scroll and its selection —
 *  which means every observer down there is still live, and every edit made
 *  in the annotator invalidates its way through all of them. Measured on one
 *  tag added in the annotator: SIX `POST /api/items/query` (the grid's pages,
 *  invisible), six `/api/items/facets` (the sidebar's badges, invisible) and
 *  three `/api/library/stats`, on a small demo library. Nobody is looking at
 *  any of it.
 *
 *  So the covered queries simply do not run. React Query keeps their data and
 *  marks it stale; closing the window refetches once, which is the sweep the
 *  edits earned — one, rather than one per edit. Subscribed rather than read
 *  imperatively, because a query has to re-evaluate when the answer changes. */
export const useCoveredByWindow = (): boolean => useUI(coveredByWindow);

/** The two full-window keyboard overlays (T's quick tag, Q's quick assign)
 *  must not stack — each one's key handler asks for the other the same way
 *  those handlers ask `itemWindowIsOpen`: imperatively, inside the handler,
 *  because the listeners are registered once on purpose. */
export const quickTagIsOpen = (): boolean => useUI.getState().quickTagOpen;
/** C's quick caption — a third one, and it shares the layer and the rule:
 *  none of these three may stack on another. */
export const quickCaptionIsOpen = (): boolean =>
  useUI.getState().quickCaptionOpen;
export const qaOverlayIsOpen = (): boolean => useUI.getState().qaOverlay;
export const rateIsOpen = (): boolean =>
  useUI.getState().rateRankingId != null;
export const tagSortIsOpen = (): boolean => useUI.getState().tagSortOpen;
export const tagGridIsOpen = (): boolean => useUI.getState().tagGridOpen;

/** THE TABLE — every way something can be over the page, by name. Both
 *  questions derive from it (`app/overPage.ts`), and `keyGuards.test.ts`
 *  holds every `*IsOpen` the store exports to a row here. */
export const OVER_PAGE = {
  dialog: overlayIsOpen,
  itemWindow: itemWindowIsOpen,
  rate: rateIsOpen,
  tagSort: tagSortIsOpen,
  tagGrid: tagGridIsOpen,
  quickTag: quickTagIsOpen,
  quickCaption: quickCaptionIsOpen,
  qa: qaOverlayIsOpen,
};
const OVER = composeOverPage(OVER_PAGE);

/** IS ANYTHING OVER THE PAGE, NOT COUNTING MYSELF? — for a full-window
 *  overlay's OWN opener, which may not see itself. It used to be a tuple
 *  per overlay, and T's and Q's never learned that C exists. */
export const overPageExcept = OVER.except;

/** IS SOMETHING OVER QUICK LOOK? — the preview's own guard, for its keys
 *  while it is up. It is `modalIsOpen` LESS the three judging sessions,
 *  because they sit UNDER the preview (`LAYER.session` < `LAYER.preview`):
 *  their cards open Quick Look over themselves, and the preview's Escape,
 *  Tab and arrows have to keep working there. Everything else that can be
 *  over the page is over the preview too.
 *
 *  …UNLESS THE PREVIEW WAS OPENED RAISED, from inside a dialog: it is then
 *  at `LAYER.previewRaised`, above the dialog rather than under it, and the
 *  keys are its own. Escape is the stack's (`shared/escapeStack.ts`): opened
 *  last, the preview is on top — the two are the same fact from either side. */
export const quickLookIsCovered = (): boolean =>
  !useUI.getState().quickLookRaised
  && overPageExcept("rate", "tagSort", "tagGrid")();

/** IS ANYTHING OVER THE PAGE? — the one question a window-level shortcut has
 *  to ask before it acts.
 *
 *  The grid, the group tree, the tags view, the properties panel and Quick
 *  Look all register their keys ONCE on the window, so they go on hearing
 *  every keystroke whatever is on top. Each of them used to ask its own
 *  hand-written list of what might be, and every one of those lists was
 *  missing the DIALOGS — so with the import overlay open, Space still opened
 *  the preview behind it, Delete still trashed the selection, and the group
 *  tree's Delete still deleted groups.
 *
 *  One predicate instead, composed of every way something can be over the
 *  page: a dialog (counted by `Overlay` itself, which is what catches the
 *  ones held in local component state), the item window, and the four
 *  full-window keyboard overlays.
 *
 *  NOT for an overlay's OWN handler — each of those must not see itself.
 *  They keep their pairwise checks, which say which of them may stack.
 *
 *  Read imperatively, INSIDE the handler, never subscribed: those listeners
 *  are registered once on purpose and must not re-subscribe on every change.
 */
export const modalIsOpen = (): boolean => OVER.any();

export const useUI = create<UIState>((set) => ({
  view: START.view,
  historyFilter: [],
  overlay: START.overlay,
  selectedGroups: START_SCOPE.selectedGroups,
  ungrouped: START_SCOPE.ungrouped, untagged: START_SCOPE.untagged,
  trashView: START_SCOPE.trashView,
  hiddenView: START_SCOPE.hiddenView,
  pendingView: START_SCOPE.pendingView,
  pendingKind: START_SCOPE.pendingKind,
  sequenceView: START_SCOPE.sequenceView,
  rankingView: START_SCOPE.rankingView,
  rankingPool: START_SCOPE.rankingPool,
  rankingDismissed: START_SCOPE.rankingDismissed,
  rankedView: START_SCOPE.rankedView,
  mediaKinds: START_SCOPE.mediaKinds,
  foldSequenced: APP_PREFS.foldSequenced.read(),
  showHiddenItems: APP_PREFS.showHiddenItems.read(),
  expanded: loadExpanded(),
  selectedItems: [],
  selectedSet: new Set<number>(),
  selPast: [],
  selFuture: [],
  pinnedSelection: false,
  pinnedItems: [],
  anchorItem: null,
  selMembers: new Set<number>(),
  gridSize: 168, // "M" in the S/M/L control
  faceSize: 124, // "S": a face crop says what it is at a smaller size
  sortField: "recent",
  sortDir: "desc",
  sortDirs: { ...SORT_DIR_DEFAULTS },
  sortSeed: 1,
  groupBy: "none",
  search: START.search,
  tagHighlight: [],
  groupHighlight: [],
  groupFocus: null,
  // Seeded from the ADDRESS, like every other bit of "where you are": a reload
  // (or a bookmark, or a link somebody was sent) with `?item=` in it comes back
  // with the window open on the same items, in the same half, on the same tab.
  // Left at the defaults it wrote the parameter and never read it, so a reload
  // dropped you on the library and quietly rewrote the address to match.
  editorItemId: START.itemTab ?? START.itemIds[0] ?? null,
  editorTabs: START.itemIds,
  editorModes: Object.fromEntries(
    START.itemIds.map((id) => [id, START.itemMode])),
  editorMode: START.itemMode,
  editorFocusTag: null,
  setEditorMode: (id, mode) =>
    set((s) => ({ editorModes: { ...s.editorModes, [id]: mode } })),
  setDefaultEditorMode: (mode) => set({ editorMode: mode }),
  visibleItemIds: [],
  groupEditId: START.groupEditId,
  openGroupEditor: (id) => set({ overlay: "group", groupEditId: id,
                                 groupCreate: null }),
  groupCreate: null,
  openGroupCreator: (seed) => set({ overlay: "group", groupEditId: null,
                                    groupCreate: seed }),
  qaSets: START_QA_SETS,
  // A disabled feature holds no selection and no mode (turning it off clears
  // both); the load applies the same rule to whatever storage says.
  qaSelected: APP_PREFS.qaEnabled.read() ? START_QA_SELECTED : null,
  qaEnabled: APP_PREFS.qaEnabled.read(),
  qaMode: APP_PREFS.qaMode.read()
    && APP_PREFS.qaEnabled.read(),
  qaOverlay: false,
  quickTagOpen: false,
  rateRankingId: null,
  rateChooserSeed: null,
  tagSortOpen: false,
  tagGridOpen: false,
  estimateOpen: false,
  quickLook: false,
  quickLookItems: null,
  previewFooter: null,
  setPreviewFooter: (previewFooter) => set({ previewFooter }),
  quickLookFile: null,
  quickLookRaised: false,
  quickLookAt: null,
  quickLookStart: null,
  quickLookBoxes: null,
  // Closing always clears any explicit target so the next Space-open falls back
  // to the live grid selection.
  setQuickLook: (quickLook) =>
    set(quickLook ? { quickLook }
      : { quickLook: false, quickLookItems: null, quickLookFile: null,
          quickLookAt: null, quickLookBoxes: null }),
  toggleQuickLook: () =>
    set((s) =>
      s.quickLook
        ? { quickLook: false, quickLookItems: null, quickLookFile: null }
        : { quickLook: true, quickLookItems: null, quickLookFile: null }
    ),
  openQuickLook: (items, opts) =>
    set({ quickLook: true, quickLookItems: items, quickLookFile: null,
          quickLookAt: opts?.at ?? null, quickLookBoxes: opts?.boxes ?? null,
          quickLookStart: opts?.start ?? null,
          quickLookRaised: opts?.raised === true }),
  openQuickLookFile: (itemId, fileId, video) =>
    set({ quickLook: true, quickLookItems: [itemId],
          quickLookFile: { itemId, fileId, video },
          quickLookAt: null, quickLookBoxes: null, quickLookStart: null }),

  createQaSet: () =>
    set((s) => {
      const created = newQaSet(lowestFreeNumber(s.qaSets));
      // The list keeps its invariant order (by number), so the new set lands
      // where its key puts it rather than at the end.
      const qaSets = sortSets([...s.qaSets, created]);
      const qaSelected = qaSets.findIndex((e) => e.id === created.id);
      saveQaSets(qaSets);
      saveQaSelected(qaSelected);
      return { qaSets, qaSelected };
    }),

  deleteQaSet: (index) =>
    set((s) => {
      if (!s.qaSets[index]) return {} as Partial<UIState>;
      let qaSets = s.qaSets.filter((_, i) => i !== index);
      // THERE IS ALWAYS AT LEAST ONE SET — the drawer edits sets in place, so
      // deleting the last one leaves a fresh empty one to type into.
      if (qaSets.length === 0) qaSets = [newQaSet(1)];
      let qaSelected = s.qaSelected;
      if (qaSelected === index) {
        qaSelected = null;
      } else if (qaSelected != null && qaSelected > index) {
        qaSelected -= 1;
      }
      saveQaSets(qaSets);
      saveQaSelected(qaSelected);
      return { qaSets, qaSelected };
    }),

  selectQaSet: (index) =>
    set((s) => {
      const qaSelected =
        index != null && index !== s.qaSelected && s.qaSets[index] ? index : null;
      saveQaSelected(qaSelected);
      return { qaSelected };
    }),

  setQaNumber: (index, num) =>
    set((s) => {
      const renumbered = assignNumber(s.qaSets, index, num);
      if (renumbered === s.qaSets) return {} as Partial<UIState>;
      // Renumbering re-sorts the list; the set whose number just changed
      // becomes the SELECTION, so the row that moved is the highlighted one
      // wherever the sort put it.
      const moved = renumbered[index].id;
      const qaSets = sortSets(renumbered);
      const found = qaSets.findIndex((e) => e.id === moved);
      const qaSelected = found >= 0 ? found : null;
      saveQaSets(qaSets);
      saveQaSelected(qaSelected);
      return { qaSets, qaSelected };
    }),

  addQaTag: (index, tag) =>
    set((s) => {
      const cur = s.qaSets[index];
      const t = tag.trim().replace(/\s+/g, "_");
      if (!cur || !t || cur.pos.includes(t) || cur.neg.includes(t)) {
        return {} as Partial<UIState>;
      }
      const qaSets = s.qaSets.map((e, i) =>
        i === index ? { ...e, pos: [...e.pos, t] } : e);
      saveQaSets(qaSets);
      return { qaSets };
    }),

  addQaGroup: (index, groupId) =>
    set((s) => {
      const cur = s.qaSets[index];
      if (!cur || cur.groups.includes(groupId)) return {} as Partial<UIState>;
      const qaSets = s.qaSets.map((e, i) =>
        i === index ? { ...e, groups: [...e.groups, groupId] } : e);
      saveQaSets(qaSets);
      return { qaSets };
    }),

  removeQaGroup: (index, groupId) =>
    set((s) => {
      const cur = s.qaSets[index];
      if (!cur) return {} as Partial<UIState>;
      const qaSets = s.qaSets.map((e, i) =>
        i === index
          ? { ...e, groups: e.groups.filter((g) => g !== groupId) } : e);
      saveQaSets(qaSets);
      return { qaSets };
    }),

  removeQaTag: (index, tag) =>
    set((s) => {
      const cur = s.qaSets[index];
      if (!cur) return {} as Partial<UIState>;
      const qaSets = s.qaSets.map((e, i) =>
        i === index
          ? { ...e, pos: e.pos.filter((x) => x !== tag),
              neg: e.neg.filter((x) => x !== tag) }
          : e);
      saveQaSets(qaSets);
      return { qaSets };
    }),

  flipQaTag: (index, tag) =>
    set((s) => {
      const cur = s.qaSets[index];
      if (!cur) return {} as Partial<UIState>;
      let next: QaSet;
      if (cur.pos.includes(tag)) {
        next = { ...cur, pos: cur.pos.filter((x) => x !== tag),
                 neg: cur.neg.includes(tag) ? cur.neg : [...cur.neg, tag] };
      } else if (cur.neg.includes(tag)) {
        next = { ...cur, neg: cur.neg.filter((x) => x !== tag),
                 pos: cur.pos.includes(tag) ? cur.pos : [...cur.pos, tag] };
      } else {
        return {} as Partial<UIState>;
      }
      const qaSets = s.qaSets.map((e, i) => (i === index ? next : e));
      saveQaSets(qaSets);
      return { qaSets };
    }),

  toggleQaMode: () =>
    set((s) => {
      // Only the master switch refuses. The mode may be armed with no set
      // selected — a grid click then selects as usual, and picking a set
      // later re-arms the stamping without a trip back to the menu.
      if (!s.qaEnabled) return {} as Partial<UIState>;
      const qaMode = !s.qaMode;
      APP_PREFS.qaMode.write(qaMode);
      return { qaMode };
    }),

  toggleQaEnabled: () =>
    set((s) => {
      const qaEnabled = !s.qaEnabled;
      APP_PREFS.qaEnabled.write(qaEnabled);
      // Off takes the working state with it: the mode is deactivated and the
      // selection put down — a disabled feature holding a live selection
      // reads as one that will act the moment somebody looks away.
      const qaMode = qaEnabled ? s.qaMode : false;
      if (qaMode !== s.qaMode) APP_PREFS.qaMode.write(qaMode);
      if (!qaEnabled && s.qaSelected != null) {
        saveQaSelected(null);
        return { qaEnabled, qaMode, qaSelected: null };
      }
      return { qaEnabled, qaMode };
    }),

  setQaOverlay: (qaOverlay) => set({ qaOverlay }),
  setQuickTagOpen: (quickTagOpen) => set({ quickTagOpen }),
  captionPreview: null,
  setCaptionPreview: (captionPreview) => set({ captionPreview }),
  quickCaptionOpen: false,
  setQuickCaptionOpen: (quickCaptionOpen) => set({ quickCaptionOpen }),
  quickCaptionSignal: 0,
  requestQuickCaption: () =>
    set((s) => ({ quickCaptionSignal: s.quickCaptionSignal + 1 })),
  quickTagSignal: 0,
  quickTagItems: null,
  requestQuickTag: (items) =>
    set((s) => ({ quickTagSignal: s.quickTagSignal + 1,
                  quickTagItems: items ?? null })),
  setRateRanking: (rateRankingId) => set({ rateRankingId }),
  setRateChooserSeed: (rateChooserSeed) => set({ rateChooserSeed }),
  setTagSortOpen: (tagSortOpen) => set({ tagSortOpen }),
  setTagGridOpen: (tagGridOpen) => set({ tagGridOpen }),
  setEstimateOpen: (estimateOpen) => set({ estimateOpen }),

  setView: (view) => set({ view }),
  trainJobUid: START.trainJobUid,
  setTrainJobUid: (trainJobUid) => set({ trainJobUid }),
  tagSetId: START.tagSetId,
  setTagSetId: (tagSetId) => set({ tagSetId }),
  // AN OLD ADDRESS NAMING A RECORD SUB-TAB lands on the Items list narrowed
  // to that kind: `/tags/places` was a page, and it still is — this one.
  tagsView: {
    ...tagsModeDefaults(START.tagsMode),
    ...(START.tagsKind
      ? { kind: START.tagsKind as TagsViewState["kind"], sortKey: "name" as const,
          sortDir: "asc" as const }
      : {}),
  },
  tagsViewByMode: {},
  setTagsView: (patch) =>
    set((s) => ({ tagsView: { ...s.tagsView, ...patch } })),
  // `focus` is the REASON for the switch — "go to that list" and "go to that
  // row in it" are one gesture — so it is set on arrival whatever was
  // remembered, and the two other one-shot landings are cleared: they name a
  // row somebody asked for once, not a way the list is narrowed. Landing on
  // the tab you are already on still focuses, since the row may be off
  // screen.
  setTagsMode: (mode, focus = null) =>
    set((s) => {
      // THE THREE RETIRED SUB-TABS LAND ON THE ITEMS LIST, narrowed to that
      // kind. Asking for one is asking for the list of subjects, of places
      // or of events — which is this list with its `kind` filter set — and
      // routing it HERE catches every caller at once: the item sidebar's
      // kind marks, the tag rows' own, the annotator's, an old address.
      const kind = mode === "subjects" ? "subjects" as const
        : mode === "places" ? "places" as const
        : mode === "events" ? "events" as const : null;
      const to: TagsMode = kind ? "items" : (mode as TagsMode);
      // ASKING FOR A ROW MEANS ASKING FOR A LIST THAT HOLDS IT. The landing
      // scrolls to the row in the list as it is NARROWED, so a search, a
      // picked category or a count range left over from other work simply
      // hid it — and the jump then retried for ever against a list the row
      // was never in. Everything that can hide a row goes; the sort and the
      // layout, which cannot, stay.
      const clear = focus ? {
        search: "", category: [], namespaces: [], uncategorized: false,
        kind: "all" as const, relation: "all" as const, scope: "all" as const,
        suggest: "all" as const, metaTag: "",
        counts: { positive: { lo: null, hi: null },
                  implicit: { lo: null, hi: null },
                  negative: { lo: null, hi: null } },
      } : {};
      if (s.tagsView.mode === to && !kind) {
        return focus ? { tagsView: { ...s.tagsView, ...clear, focus } } : {};
      }
      return {
        ...enterTagsMode(s, to),
        tagsView: {
          ...tagsModeState(s, to), ...clear, focus,
          // A record list read by NAME, as those lists always did.
          ...(kind ? { kind, sortKey: "name" as const, sortDir: "asc" as const }
                   : {}),
          focusCategory: null, focusEdit: false,
        },
      };
    }),
  showHistoryFor: (ids) => set({ view: "history", historyFilter: ids }),
  showCategoryInTagSet: (setId, trail) =>
    set((s) => ({
      view: "tags",
      tagSetId: setId,
      ...enterTagsMode(s, "tagsets"),
      tagsView: { ...tagsModeState(s, "tagsets"), focusCategory: trail,
                  focus: null, focusEdit: false },
    })),
  showTagInTagSet: (setId, name, edit = false) =>
    set((s) => ({
      view: "tags",
      tagSetId: setId,
      // ARRIVING FROM ELSEWHERE IS A SUB-TAB SWITCH, so it goes through the
      // same two helpers `setTagsMode` does: the sub-tab being left is
      // parked, the one arrived at comes back as it was — `focus` (and the
      // edit it asks for) being the reason for the switch, set on top.
      ...enterTagsMode(s, "tagsets"),
      tagsView: { ...tagsModeState(s, "tagsets"), focus: name, focusEdit: edit,
                  focusCategory: null },
    })),
  setHistoryFilter: (ids) => set({ historyFilter: ids }),
  setOverlay: (overlay) => set({ overlay }),
  // A settings URL names its page; otherwise the last one used is remembered.
  settingsPage: START.overlay === "settings" ? START.settingsPage
    : isSettingsPage(storage.get(SETTINGS_PAGE_KEY))
      ? (storage.get(SETTINGS_PAGE_KEY) as SettingsPage)
      : "general",
  setSettingsPage: (settingsPage) => {
    storage.set(SETTINGS_PAGE_KEY, settingsPage);
    set({ settingsPage });
  },
  settingsFocusModel: null,
  setSettingsFocusModel: (settingsFocusModel) => set({ settingsFocusModel }),
  settingsFocusWarning: false,
  setSettingsFocusWarning: (settingsFocusWarning) => set({ settingsFocusWarning }),
  setSearch: (search) => set({ search }),
  setGridSize: (gridSize) => set({ gridSize }),
  setFaceSize: (faceSize) => set({ faceSize }),
  // Changing the sort must normalize the grouping with it: the backend
  // REFUSES a pair it does not recognise, so leaving "month" set while
  // switching to Name would 400 every request until somebody noticed.
  setSortField: (sortField) => set((s) => ({
    sortField,
    // Back to how that field was last read, which is why the pair is
    // remembered at all.
    sortDir: s.sortDirs[sortField] ?? "desc",
    groupBy: groupOptionsFor(sortField).includes(s.groupBy) ? s.groupBy : "none",
    // Arriving at the shuffle deals it a new hand.
    sortSeed: sortField === "random"
      ? 1 + Math.floor(Math.random() * 2_000_000_000) : s.sortSeed,
  })),
  setSortDir: (sortDir) => set((s) => ({
    sortDir, sortDirs: { ...s.sortDirs, [s.sortField]: sortDir },
  })),
  // A fresh shuffle. Switching TO random draws one as well (see
  // `setSortField`), or the first press of the dice would look like the
  // button doing nothing — the order was already this seed's.
  shuffle: () => set({ sortSeed: 1 + Math.floor(Math.random() * 2_000_000_000) }),
  setGroupBy: (groupBy) => set({ groupBy }),
  toggleSortDir: () => set((s) => {
    const sortDir: SortDir = s.sortDir === "asc" ? "desc" : "asc";
    return { sortDir, sortDirs: { ...s.sortDirs, [s.sortField]: sortDir } };
  }),
  setTagHighlight: (tagHighlight) => set({ tagHighlight }),
  setGroupHighlight: (groupHighlight) => set({ groupHighlight }),
  setGroupFocus: (groupFocus) => set({ groupFocus }),

  // Toggling a kind treats the empty array as "all kinds checked". Unchecking
  // the last remaining kind is a no-op (at least one media type must stay on),
  // and re-checking everything normalizes back to the empty ("All media") state.
  toggleMediaKind: (kind) =>
    set((s) => {
      const all: Kind[] = ["image", "video", "sequence"];
      const cur = s.mediaKinds.length === 0 ? [...all] : [...s.mediaKinds];
      let next = cur.includes(kind) ? cur.filter((k) => k !== kind) : [...cur, kind];
      if (next.length === 0) return {}; // can't uncheck them all
      if (next.length === all.length) next = []; // all on → "All media"
      return { mediaKinds: next };
    }),
  toggleFoldSequenced: () => set((s) => {
    const foldSequenced = !s.foldSequenced;
    APP_PREFS.foldSequenced.write(foldSequenced);
    return { foldSequenced };
  }),
  toggleShowHiddenItems: () => set((s) => {
    const showHiddenItems = !s.showHiddenItems;
    APP_PREFS.showHiddenItems.write(showHiddenItems);
    return { showHiddenItems };
  }),

  // Navigating to a group clears the (orthogonal) media-kind filter, so leaving
  // the Images/Videos/Sequences special entries drops their kind restriction.
  selectGroup: (id, additive) =>
    set((s) => {
      let g = additive ? [...s.selectedGroups] : [];
      if (g.includes(id)) g = g.filter((x) => x !== id);
      else g.push(id);
      return { ...NO_SCOPE, selectedGroups: g, mediaKinds: [], ...keepSel(s) };
    }),

  setSelectedGroups: (ids) =>
    set((s) => ({ ...NO_SCOPE, selectedGroups: ids, mediaKinds: [], ...keepSel(s) })),

  // Leaves the media-kind filter untouched (it is an orthogonal filter).
  clearGroupSelection: () =>
    set((s) => ({ ...NO_SCOPE, ...keepSel(s) })),

  // The sidebar "All Items" entry: reset scope *and* clear the kind filter.
  showAllItems: () =>
    set((s) => ({ ...NO_SCOPE, mediaKinds: [], ...keepSel(s) })),

  // The sidebar Images/Videos/Sequences entries: All Items scope, one kind.
  showKind: (kind) =>
    set((s) => ({ ...NO_SCOPE, mediaKinds: [kind], ...keepSel(s) })),

  showUngrouped: () =>
    set((s) => ({ ...NO_SCOPE, ungrouped: true, mediaKinds: [], ...keepSel(s) })),

  showUntagged: () =>
    set((s) => ({ ...NO_SCOPE, untagged: true, mediaKinds: [], ...keepSel(s) })),

  showTrash: () =>
    set((s) => ({ ...NO_SCOPE, trashView: true, mediaKinds: [], ...keepSel(s) })),

  showHidden: () =>
    set((s) => ({ ...NO_SCOPE, hiddenView: true, mediaKinds: [], ...keepSel(s) })),

  showPending: (kind = null) =>
    set((s) => ({ ...NO_SCOPE, pendingView: true, pendingKind: kind,
                  mediaKinds: [], ...keepSel(s) })),

  //: A RANKING'S OWN VIEW — what it has placed, in its standings order. A
  //  pool narrows that to one fit; null is every pool it holds, which is
  //  what one pool always meant.
  showRanking: (id, pool = null) =>
    set((s) => ({ ...NO_SCOPE, rankingView: id, rankingPool: pool,
                  mediaKinds: [], ...keepSel(s) })),

  //: THE RANKINGS THEMSELVES — the Rankings row itself, which opens a card
  //  per ranking rather than a grid of their pictures (`RankingsIndex`). Not
  //  the union of what they placed: two rankings share no scale, so a heap of
  //  their pictures in an arbitrary order answers nothing, where "which
  //  rankings are there" is exactly what the row is asked.
  showRanked: () =>
    set((s) => ({ ...NO_SCOPE, rankedView: true, mediaKinds: [],
                  ...keepSel(s) })),

  //: THE ONES SET ASIDE — its own row under the ranking, because they are a
  //  place to go and look rather than a fact hidden in a panel.
  showRankingDismissed: (id) =>
    set((s) => ({ ...NO_SCOPE, rankingView: id, rankingDismissed: true,
                  mediaKinds: [], ...keepSel(s) })),

  showSequence: (id) =>
    set((s) => ({ ...NO_SCOPE, sequenceView: id, ...keepSel(s) })),

  toggleGroupExpanded: (id) =>
    set((s) => {
      const expanded = { ...s.expanded, [id]: !s.expanded[id] };
      saveExpanded(expanded);
      return { expanded };
    }),

  setGroupsExpanded: (ids, open) =>
    set((s) => {
      const expanded = { ...s.expanded };
      for (const id of ids) expanded[id] = open;
      saveExpanded(expanded);
      return { expanded };
    }),

  // Clears the *grid* selection; the pinned sidebar selection is untouched. The
  // prior selection is pushed onto the back-history so Back can restore it.
  clearItemSelection: () =>
    set((s) => {
      if (s.selectedItems.length === 0) return {};
      return {
        ...keepSel(s), anchorItem: null,
        selPast: pushHistory(s.selPast, s.selectedItems), selFuture: [],
      };
    }),

  selectItem: (id, mods, ordered) =>
    set((s) => {
      // Compute the next selection for each click kind, then record the prior
      // one in the back-history (browser-style) so Back walks through the
      // selections the user visited — a plain click included, not just
      // programmatic link navigation.
      let next: number[];
      let anchor = s.anchorItem;
      if (mods.meta) {
        // Cmd/Ctrl+click toggles a single item and moves the range anchor to it.
        const sel = new Set(s.selectedSet);
        sel.has(id) ? sel.delete(id) : sel.add(id);
        next = [...sel];
        anchor = id;
      } else if (mods.shift && s.anchorItem != null && ordered && ordered.length) {
        // Shift+click selects the contiguous range from the anchor to this item.
        const a = ordered.indexOf(s.anchorItem);
        const b = ordered.indexOf(id);
        if (a !== -1 && b !== -1) {
          const [lo, hi] = a <= b ? [a, b] : [b, a];
          next = ordered.slice(lo, hi + 1);
        } else {
          next = [id];
          anchor = id;
        }
      } else if (s.selectedSet.size === 1 && s.selectedSet.has(id)) {
        // The click on the only picked card is the way back out — the one
        // click rule every list here follows (`shared/pickList.ts`).
        next = [];
        anchor = null;
      } else {
        next = [id];
        anchor = id;
      }
      const w = selWrite(s, next);
      if (!w) return { anchorItem: anchor };
      const selPast = s.selectedItems.length
        ? pushHistory(s.selPast, s.selectedItems) : s.selPast;
      return { ...w, anchorItem: anchor, selPast, selFuture: [] };
    }),

  // Programmatic selection (e.g. clicking a derived/original link): remember the
  // prior selection so the Back button can restore it.
  setSelectedItems: (ids) =>
    set((s) => {
      const w = selWrite(s, ids);
      if (!w) return {};
      const selPast = s.selectedItems.length
        ? pushHistory(s.selPast, s.selectedItems) : s.selPast;
      // Move the range anchor onto the new selection so the grid's arrow-key
      // navigation resumes from here (e.g. after QuickLook steps the selection),
      // rather than from whatever was selected before this programmatic change.
      return {
        ...w,
        anchorItem: ids.length ? ids[ids.length - 1] : null,
        selPast, selFuture: [],
      };
    }),
  setSelMembers: (m) => set({ selMembers: m }),
  // Pinning freezes the current grid selection into `pinnedItems` for the
  // sidebar; unpinning drops it so the sidebar follows the grid again.
  togglePinned: () =>
    set((s) =>
      s.pinnedSelection
        ? { pinnedSelection: false, pinnedItems: [] }
        : { pinnedSelection: true, pinnedItems: s.selectedItems }
    ),
  selectionBack: () =>
    set((s) => {
      // Skip entries equal to what is already selected: a selection cleared
      // and re-made leaves the same ids on top of the stack (the empty state
      // between them is deliberately not recorded), and Back landing on
      // exactly the current selection reads as a button that does nothing.
      let at = s.selPast.length - 1;
      while (at >= 0 && sameEntry(s.selPast[at], s.selectedItems)) at--;
      if (s.pinnedSelection || at < 0) return {};
      const prev = s.selPast[at];
      // The forward stack takes the same cap/size rules as `pushHistory`, just
      // from the front (newest first).
      const selFuture = s.selectedItems.length > HISTORY_MAX_ENTRY
        ? s.selFuture
        : [s.selectedItems, ...s.selFuture].slice(0, HISTORY_CAP);
      return {
        ...(selWrite(s, prev) ?? {}),
        anchorItem: prev.length ? prev[prev.length - 1] : null,
        selPast: s.selPast.slice(0, at),
        selFuture,
      };
    }),
  selectionForward: () =>
    set((s) => {
      // The mirror of Back's skip, for the same reason.
      let at = 0;
      while (at < s.selFuture.length
             && sameEntry(s.selFuture[at], s.selectedItems)) at++;
      if (s.pinnedSelection || at >= s.selFuture.length) return {};
      const next = s.selFuture[at];
      return {
        ...(selWrite(s, next) ?? {}),
        anchorItem: next.length ? next[next.length - 1] : null,
        selPast: pushHistory(s.selPast, s.selectedItems),
        selFuture: s.selFuture.slice(at + 1),
      };
    }),

  // ---- opening the ITEM WINDOW -------------------------------------------
  // It is an OVERLAY over the library now, not a browser window of its own, so
  // all four of these are one state change: seed the tabs, say which half each
  // opens in, and remember the grid order for the sequence walk.
  //
  // What went with the window: `window.open` and a per-item window NAME (so a
  // second Annotate would not open a second window over the same picture), a
  // grid-order and focus-tag hand-off through `localStorage` (the only channel
  // a different document had), and a walk up the opener chain to find the
  // library again. None of it has anything left to do — the overlay reads the
  // same store the library does.
  openItemWindow: async (ids, mode, focus) => {
    if (ids.length === 0) return;
    // A tab per id, each with its own detail fetch — cap runaway multi-opens.
    if (ids.length > MULTI_OPEN_CAP) {
      if (!(await confirmMultiOpen(ids.length))) return;
      ids = ids.slice(0, MULTI_OPEN_CAP);
    }
    set((s) => ({
      // Only a window of ids around the opened one, the way the hand-off used
      // to be trimmed: the sequence walk needs neighbours, not the whole view.
      visibleItemIds: navWindow(s.visibleItemIds, ids[0]),
      editorTabs: ids,
      editorItemId: ids[0],
      editorMode: mode,
      editorModes: Object.fromEntries(ids.map((id) => [id, mode])),
      editorFocusTag: focus ?? null,
    }));
  },
  openEditorMulti: (ids) => useUI.getState().openItemWindow(ids, "edit"),
  openEditor: (id, focusTag) => useUI.getState().openItemWindow(
    [id], "edit", focusTag ? { id, tag: focusTag, group: null } : null),
  openAnnotatorMulti: (ids) => useUI.getState().openItemWindow(ids, "annotate"),
  openAnnotator: (id, focusTag, focusGroup) => useUI.getState().openItemWindow(
    [id], "annotate",
    focusTag ? { id, tag: focusTag, group: focusGroup ?? null } : null),
  annotateTab: null,
  openAnnotatorAt: (id, tab) => {
    set({ annotateTab: tab });
    useUI.getState().openItemWindow([id], "annotate");
  },
  clearAnnotateTab: () => set({ annotateTab: null }),
  closeItemWindow: () =>
    set({ editorTabs: [], editorItemId: null, editorModes: {},
          editorFocusTag: null }),
  clearEditorFocusTag: () => set({ editorFocusTag: null }),
  showItemInLibrary: (itemId, uid) => {
    // The uid is intrinsic METADATA, so it is `INFO:id=…` — a bare `id:`
    // parses as a tag named "id" and quietly matches nothing. Narrowing to
    // the one picture beats selecting something buried in a listing that
    // would then have to be scrolled to.
    const q = uid ? `INFO:id=${uid}` : "";
    const s = useUI.getState();
    // A SESSION IS NOT LEFT (owner 2026-09). Under a tag grid, a tag batch
    // or a rating session the library is COVERED — its queries stand down
    // (`covered.ts`) — so setting its search and selection changed nothing
    // anybody could see, and closing the session to show one picture would
    // throw the session's work away. The picture opens in a NEW WINDOW
    // instead, at the library's own address for it; the session stays.
    // Answers true so the caller knows this window did not move.
    if (s.tagSortOpen || s.tagGridOpen || s.rateRankingId != null) {
      const url = new URL(VIEW_PATHS.library, window.location.href);
      if (q) url.searchParams.set("q", q);
      window.open(url.toString(), "_blank");
      return true;
    }
    s.closeItemWindow();
    s.showAllItems();
    s.setSearch(q);
    s.setSelectedItems([itemId]);
    s.setView("library");
    return false;
  },
  setEditorItem: (id) =>
    set((s) => ({
      editorItemId: id,
      editorTabs: s.editorTabs.includes(id) ? s.editorTabs : [...s.editorTabs, id],
    })),
  navigateEditor: (id) =>
    set((s) => {
      // Already open in another tab → just focus it. Otherwise swap the active
      // tab's item in place (so grid prev/next doesn't spawn tabs).
      if (s.editorTabs.includes(id)) return { editorItemId: id };
      const tabs = s.editorTabs.length
        ? [...s.editorTabs]
        : s.editorItemId != null
          ? [s.editorItemId]
          : [];
      const i = tabs.indexOf(s.editorItemId ?? -1);
      if (i >= 0) tabs[i] = id;
      else tabs.push(id);
      return { editorItemId: id, editorTabs: tabs };
    }),
  closeEditorTab: (id) =>
    set((s) => {
      const oldIdx = s.editorTabs.indexOf(id);
      const tabs = s.editorTabs.filter((t) => t !== id);
      let active = s.editorItemId;
      if (active === id)
        active = tabs.length ? tabs[Math.min(oldIdx, tabs.length - 1)] : null;
      return { editorTabs: tabs, editorItemId: active };
    }),
  setVisibleItemIds: (visibleItemIds) => set({ visibleItemIds }),
  pointedItemIds: [],
  setPointedItemIds: (pointedItemIds) => set({ pointedItemIds }),
}));
