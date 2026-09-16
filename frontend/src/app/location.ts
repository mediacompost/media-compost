// Where you are, in the address bar — so reloading (or bookmarking, or the
// browser's Back button) keeps the tab and the overlay you had open instead of
// dropping you back on the library.
//
// The view is the PATH (`/train`), because that is what a "page" is; anything
// hanging off it — the settings overlay and its page, the group being edited,
// the selected training job — is a query parameter, because those are states of
// a page rather than pages of their own. The server serves index.html for any
// path (see server/app.py), so every one of these URLs survives a reload.
import type { ItemMode, Kind, Overlay, SettingsPage, TagsMode, View } from "./store";

// The settings pages, and the guard both this module and the store read a
// remembered/typed value through. It lives HERE rather than beside the type in
// `store.ts` because this module has to stay runtime-free of the store —
// `location.test.ts` loads it under `node --test`, where importing zustand is
// a module it cannot resolve. A type-only import is erased; a value one is not.
const SETTINGS_PAGES: SettingsPage[] = ["general", "actions", "tagging",
                                       "faces", "storage"];
export const isSettingsPage = (s: string | null): s is SettingsPage =>
  SETTINGS_PAGES.includes(s as SettingsPage);
export const readSettingsPage = (s: string | null): SettingsPage =>
  isSettingsPage(s) ? s : "general";

const KINDS: Kind[] = ["image", "video", "sequence"];

export interface Place {
  view: View;
  overlay: Overlay;
  settingsPage: SettingsPage;
  groupEditId: number | null;
  trainJobUid: string | null;
  // Tags view only: which sub-tab, as a second path segment (`/tags/subjects`).
  // A sub-tab IS a page — it lists different things and is what you were
  // looking at — so it belongs in the path rather than a query parameter.
  tagsMode: TagsMode;
  /** A record kind an OLD address named as a sub-tab (`/tags/places`), read
   *  back as the Items list's `kind` filter. Empty for every current
   *  address; the store applies it once on arrival. */
  tagsKind: string;
  // Tags → Sets only: the set that is open (`?set=`), so a reload lands on
  // the same set. A parameter, not a path segment: it is a state of that
  // sub-tab, the way a training job is a state of the Train tab.
  tagSetId: number | null;
  // Library view only: the selected sidebar category, the media-kind filter, and
  // the search string — so a reload keeps what you were looking at.
  libCat: string | null;   // "g<id>" | "ungrouped" | "untagged" | "trash" | "hidden" | "pending[-tags|-captions|-faces]" | "seq<id>" | null (All Items)
  libKinds: string;        // comma-joined media kinds, e.g. "image,video"
  search: string;
  // THE ITEM WINDOW, which is an overlay over whatever view is open — so it is
  // a PARAMETER, like the settings overlay and the group editor, and not a
  // path. It was a path (`/item/<ids>/<mode>`) while it was a browser window
  // of its own and had nothing behind it; over the library, a path would throw
  // away the category, filter and search you opened it from, and closing it
  // would land you somewhere you had never been.
  itemIds: number[];
  itemMode: ItemMode;
  itemTab: number | null;  // the active tab, when it is not the first
}

// The library scope fields these map to (subset of the UI store).
export interface LibScope {
  selectedGroups: number[];
  ungrouped: boolean;
  untagged: boolean;
  trashView: boolean;
  hiddenView: boolean;
  pendingView: boolean;
  pendingKind: "tags" | "captions" | "faces" | null;
  sequenceView: number | null;
  rankingView: number | null;
  rankingPool: number | null;
  rankingDismissed: boolean;
  rankedView: boolean;
  mediaKinds: Kind[];
}

/** The category token for a set of scope fields (null = All Items). */
export function catFromScope(s: {
  selectedGroups: number[]; ungrouped: boolean; untagged: boolean;
  trashView: boolean; hiddenView: boolean;
  pendingView: boolean; pendingKind: "tags" | "captions" | "faces" | null;
  sequenceView: number | null;
  rankingView: number | null; rankingPool: number | null;
  rankingDismissed: boolean;
  rankedView: boolean;
}): string | null {
  if (s.sequenceView != null) return `seq${s.sequenceView}`;
  // `rank7` is every pool the ranking holds; `rank7.2` is one of them —
  // the shape `g<ids>` and `seq<id>` already use, with the second half
  // optional because one pool is what a ranking usually has.
  if (s.rankingView != null) {
    // `.na` rather than a pool id: the set-aside ones are ranking-wide, and
    // a pool is never called that (the id is a number).
    if (s.rankingDismissed) return `rank${s.rankingView}.na`;
    return `rank${s.rankingView}`
      + (s.rankingPool != null ? `.${s.rankingPool}` : "");
  }
  // EVERY ranking at once — the row above them. `ranked` rather than a
  // `rank` with nothing after it, so the two cannot be confused by a reader
  // or by `scopeFromPlace`'s prefix test.
  if (s.rankedView) return "ranked";
  if (s.trashView) return "trash";
  if (s.hiddenView) return "hidden";
  if (s.untagged) return "untagged";
  if (s.ungrouped) return "ungrouped";
  if (s.pendingView) return s.pendingKind ? `pending-${s.pendingKind}` : "pending";
  // EVERY selected group, not just the first: picking three groups in the
  // sidebar is one scope, and an address naming one of them reloaded into a
  // narrower view than the one it was copied from — silently, because the grid
  // simply showed fewer items and nothing said why.
  if (s.selectedGroups.length) return `g${s.selectedGroups.join(",")}`;
  return null;
}

/** The scope fields a place's `libCat`/`libKinds` describe. */
export function scopeFromPlace(p: Place): LibScope {
  const base: LibScope = {
    selectedGroups: [], ungrouped: false, untagged: false, trashView: false,
    hiddenView: false, pendingView: false, pendingKind: null,
    sequenceView: null, rankingView: null, rankingPool: null,
    rankingDismissed: false, rankedView: false,
    mediaKinds: p.libKinds
      ? (p.libKinds.split(",").filter((k) => (KINDS as string[]).includes(k)) as Kind[])
      : [],
  };
  const c = p.libCat;
  if (!c) return base;
  if (c === "trash") return { ...base, trashView: true };
  if (c === "hidden") return { ...base, hiddenView: true };
  if (c === "untagged") return { ...base, untagged: true };
  if (c === "ungrouped") return { ...base, ungrouped: true };
  if (c.startsWith("pending")) return {
    ...base, pendingView: true,
    pendingKind: c === "pending-tags" ? "tags" : c === "pending-captions" ? "captions"
      : c === "pending-faces" ? "faces" : null,
  };
  if (c.startsWith("seq")) return { ...base, sequenceView: Number(c.slice(3)) || null };
  if (c === "ranked") return { ...base, rankedView: true };
  if (c.startsWith("rank")) {
    const [rk, lg] = c.slice(4).split(".");
    const id = Number(rk);
    if (!Number.isFinite(id) || id <= 0) return base;
    if (lg === "na") return { ...base, rankingView: id, rankingDismissed: true };
    const pool = lg != null && Number(lg) > 0 ? Number(lg) : null;
    return { ...base, rankingView: id, rankingPool: pool };
  }
  if (c.startsWith("g")) {
    const ids = c.slice(1).split(",")
      .map((v) => Number(v))
      .filter((n) => Number.isFinite(n) && n > 0);
    return ids.length ? { ...base, selectedGroups: ids } : base;
  }
  return base;
}

const idList = (s: string | null | undefined): number[] =>
  (s ?? "").split(",").map((v) => Number(v))
    .filter((n) => Number.isFinite(n) && n > 0);

/** FACES AND RANKINGS ARE NOT SUB-TABS ANY MORE — one is a tab of its own,
 *  the other a view of the library — and neither `/tags/faces` nor
 *  `/tags/rankings` is redirected: an unknown sub-segment already falls to
 *  the Items list below, which is a page rather than a blank and is where
 *  somebody arriving on an old address wants to be anyway. A cross-VIEW
 *  remap is a shape this file does not have (`LEGACY_TAGS_MODES` only moves
 *  a sub-tab WITHIN the tags view), and two addresses are not worth growing
 *  it for. */
const TAGS_MODES: TagsMode[] = ["items", "links", "tagsets"];

/** THE THREE RECORD SUB-TABS ARE THE ITEMS LIST, NARROWED.
 *
 *  A subject, a place and an event are extra data ON a tag, so their lists
 *  were this list cut three ways — the same rows, the same counts, the same
 *  resolver — and they are now the `kind` filter (and the sidebar's three
 *  rows, which set it). The addresses stay readable: a bookmark, a link in
 *  somebody's notes and every `Back` in an open window still land where they
 *  meant to, on the list narrowed to that kind. */
const LEGACY_TAGS_MODES: Record<string, { mode: TagsMode; kind: string }> = {
  subjects: { mode: "items", kind: "subjects" },
  places: { mode: "items", kind: "places" },
  events: { mode: "items", kind: "events" },
};

export const VIEW_PATHS: Record<View, string> = {
  library: "/library",
  tags: "/tags",
  faces: "/faces",
  history: "/history",
  train: "/train",
  evaluate: "/evaluate",
  models: "/models",
};

const PATH_VIEWS: Record<string, View> = {
  // "" keeps the bare root working (a bookmark, a hand-typed host); the app
  // rewrites it to /library on load so every tab has a path of its own.
  "": "library", library: "library", tags: "tags", faces: "faces",
  history: "history", train: "train", evaluate: "evaluate", models: "models",
};

/** The place the current URL names, falling back to the library. */
export function readPlace(): Place {
  const [seg, sub] = window.location.pathname
    .replace(/^\/+|\/+$/g, "").split("/");
  const q = new URLSearchParams(window.location.search);
  const settings = q.get("settings");
  const group = Number(q.get("group"));
  const itemIds = idList(q.get("item"));
  const itemMode: ItemMode = q.get("mode") === "edit" ? "edit" : "annotate";
  const tab = idList(q.get("tab"))[0] ?? null;
  return {
    itemIds,
    itemMode,
    itemTab: tab != null && itemIds.includes(tab) ? tab : null,
    view: PATH_VIEWS[seg] ?? "library",
    overlay: settings !== null ? "settings"
      : group > 0 ? "group" : null,
    settingsPage: readSettingsPage(settings),
    groupEditId: group > 0 ? group : null,
    trainJobUid: q.get("job") || null,
    tagsMode: (TAGS_MODES as string[]).includes(sub ?? "")
      ? (sub as TagsMode) : "items",
    tagsKind: "",
    tagSetId: Number(q.get("set")) > 0 ? Number(q.get("set")) : null,
    libCat: q.get("cat") || null,
    libKinds: q.get("kinds") || "",
    search: q.get("q") || "",
  };
}

/** The URL a place should have. Parameters that don't apply to the view are
 *  left out, so the address bar never carries stale state. */
export function placeUrl(p: Place): string {
  const q = new URLSearchParams();
  // The item window rides on whatever is behind it, so it is written FIRST and
  // the view keeps its own parameters — closing the window then leaves exactly
  // the address you opened it from.
  if (p.itemIds.length) {
    q.set("item", p.itemIds.join(","));
    q.set("mode", p.itemMode);
    if (p.itemTab != null && p.itemTab !== p.itemIds[0])
      q.set("tab", String(p.itemTab));
  }
  if (p.overlay === "settings") q.set("settings", p.settingsPage);
  // The import overlay is deliberately not in the URL: its content is a queue
  // of files this page was handed, which a reload cannot bring back.
  if (p.overlay === "group" && p.groupEditId) q.set("group", String(p.groupEditId));
  if (p.view === "train" && p.trainJobUid) q.set("job", p.trainJobUid);
  if (p.view === "tags" && p.tagsMode === "tagsets" && p.tagSetId)
    q.set("set", String(p.tagSetId));
  // The library category / media filter / search live in the URL only on the
  // library view, so switching to another tab never carries stale library state.
  if (p.view === "library") {
    if (p.libCat) q.set("cat", p.libCat);
    if (p.libKinds) q.set("kinds", p.libKinds);
    if (p.search) q.set("q", p.search);
  }
  const s = q.toString();
  const path = VIEW_PATHS[p.view]
    + (p.view === "tags" && p.tagsMode !== "items" ? `/${p.tagsMode}` : "");
  return path + (s ? `?${s}` : "");
}

export function samePlace(a: Place, b: Place): boolean {
  return placeUrl(a) === placeUrl(b);
}
