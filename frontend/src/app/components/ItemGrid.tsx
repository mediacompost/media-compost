import React, { useEffect, useMemo, useRef, useState } from "react";
import { useEscape } from "../../shared/useEscape";
import { MenuRow } from "../../shared/MenuRow";
import { storage } from "../../shared/storage";
import { RECORD_ICON } from "../../shared/metaEnums";
import { Chevron } from "../../shared/Chevron";
import { Chip } from "../../shared/Chip";
import { IconButton, iconButtonStyle } from "../../shared/IconButton";
import { Loading, Trouble } from "../../shared/Loading";
import { EmptyState } from "../../shared/EmptyState";
import { escapeDepth } from "../../shared/escapeStack";
import { LAYER } from "../../shared/layers";
import { Select } from "../../shared/Select";
import { isTypingTarget } from "../../shared/typingTarget";
import { confirm } from "../../shared/ConfirmModal";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fmtDuration, GroupNode, ItemOut, ItemPage, ItemSearchBody, ItemSlim, JobKind, TaskInfo } from "../api";
import { chunks } from "../bulk";
import { Icon } from "../../shared/Icon";
import { MediaKindMenu } from "./shared/MediaKindMenu";
import { ZoomablePreview } from "./QuickLook";
import { QueryBuilder } from "../../query/QueryBuilder";
import { groupOptionsFor, modalIsOpen, useCoveredByWindow, type GroupBy, type SortDir, type SortField, useUI } from "../store";
import { useLang, useT, useTn , useNum } from "../i18n";
import { setDraggedItems } from "../dragState";
import { DETECT_WITH } from "../detectAndRemove";
import { bumpEdits, bumpItem } from "../invalidation";
import { useGroupRuns, useItemView, useViewRequest } from "../useItems";
import { itemHasAllQaTags } from "../qaSets";
import {
  cardBox, columnsFor, gridWindow, groupLayout, groupWindow,
  marqueeHits, marqueeHitsGrouped, scrollScale, stepIndex,
  type GroupLayout, type GroupRun,
} from "../../shared/gridGeom";
import { groupLabel, groupSwatch, jumpGroups } from "../gridGroups";
import { GridSizeControl } from "../../shared/CardGrid";
import { useCardGrid } from "../../shared/useCardGrid";
import { GridExportButton } from "./GridExport";
import { RankingEditOverlay } from "./RankingEditOverlay";
import { ActionToast } from "./shared/ActionToast";
import {
  aiActionRows, readPanelsSequence, readyModel, targetsTake, taskSections,
} from "../aiActionSections";
import {
  LAST_ACTION_KEY, offeredLastAction, parseLastAction, serializeLastAction,
  type LastAction,
} from "../ctxLastUsed";
import { mpLabel } from "../format";
import { useMenuDismiss } from "../../shared/useMenuDismiss";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { PointerMenu, RowMenu, type RowAction } from "../../shared/RowMenu";

// Sort fields for the grid's order dropdown; the direction is a separate
// toggle. The values ARE `SortField` — `groupOptionsFor` in the store is keyed
// by them, and the backend refuses a (sort, group) pair it does not know.
// The ORDER is how often each is reached for. Imported first: it is what a
// library that is being filled is looked at by, and it is the default. The
// three dates lead, with the one somebody has to have TYPED (or a camera
// recorded) last of them, since most pictures carry none. Then the two read
// off the picture itself, name before the two measured ones.
const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "recent", label: "Imported" },
  { value: "modified", label: "Modified" },
  { value: "taken", label: "Date Taken" },
  { value: "name", label: "Name" },
  { value: "color", label: "Color" },
  { value: "resolution", label: "Resolution" },
  { value: "random", label: "Random" },
];

// The label for each coarsening. "none" is the un-grouped state and reads as
// the absence of grouping rather than as a choice named after one.
const GROUP_LABELS: Record<GroupBy, string> = {
  none: "No groups",
  day: "Day",
  month: "Month",
  year: "Year",
  initial: "First letter",
  mp: "Megapixels",
  band: "Color",
  bucket: "Rating",
};

// The media kinds offered by the toolbar's multi-select filter dropdown.

// The grid context menu's copy/paste clipboard. Module-level on purpose:
// survives re-renders and view switches, but is not persisted — a reload
// starts empty.
//
// Subjects, places and events are TAG NAMES, because that is what each of them
// is: extra data on a tag, whose assignment is the tag's. So pasting one is
// assigning that tag — idempotent, and everything downstream (search, counts,
// the sidebar's own rows) learns nothing new.
const CTX_CLIPBOARD: {
  // Each copied tag keeps the per-item tag-group names it was placed in on the
  // source item(s); null = the ungrouped default. Paste matches (or creates)
  // the groups by name on the target.
  tags?: { name: string; negative: boolean; groups: (string | null)[] }[];
  groups?: number[];
  captions?: string[];
  subjects?: string[];
  places?: string[];
  events?: string[];
  // An instruction is its text AND the ordered items it was made from — one
  // without the other is a different statement, so they travel together.
  instructions?: { text: string; refs: number[] }[];
  links?: { other: number; outgoing: boolean; kind: string; tags: string[] }[];
} = {};

/** What the copy/paste rows can carry — one kind per menu row. */
type ClipKind = "tags" | "groups" | "captions" | "subjects" | "places"
  | "events" | "instructions" | "links";

/** The item ids a copy also puts on the SYSTEM clipboard, so they can be
 *  pasted where an id is what is wanted — the query builder's "Similar to"
 *  field, a note, a script. One uid per line; for one item that is one line.
 *  Best-effort: a browser that refuses the clipboard is not a reason for the
 *  copy inside the app to fail. */
function copyUids(uids: string[]): void {
  try { void navigator.clipboard?.writeText(uids.join("\n")); }
  catch { /* no clipboard permission — the in-app copy still happened */ }
}

// Grid geometry (kept in sync with the layout below so windowing math is exact).
const PAD = 18; // padding around the grid
const GAP = 16; // gap between cards
const META_H = 40; // fixed height of the name/dimensions block under each thumb
const ROW_BUFFER = 3; // extra rows rendered above/below the viewport
// A section header's height, INCLUDING its own bottom spacing. Hard-fixed and
// clipped: the windowing math places every row from it, so a header that
// could wrap would be a layout that lies — the same rule PlaceholderCard
// already keeps for cards.
const HEADER_H = 34;
const GROUP_GAP = 18; // between one section's last row and the next header

// A custom drag preview: a rounded thumbnail, or a small fanned stack (with a
// count badge) when several images are dragged at once. Returned element must be
// in the DOM when handed to setDragImage, then removed on the next tick.
const GHOST_THUMB = 84;
//: WHERE THE CURSOR SITS IN IT — the hotspot, and therefore where the element
//  is put on screen: the two are one number so they cannot disagree.
const GHOST_HOTSPOT = 46;
//: THE CARDS' OWN URLS (2026-09): the ghost is snapshotted the moment
//  `setDragImage` is called, so its pictures have to be in the browser's
//  cache already — and only the exact URL the card drew is. Asked for by
//  file id alone (no rotation, no thumb token) the URL differed, and the
//  ghost was blank for any card the sidebar had not also shown at that
//  spelling, which is every card that was not selected.
//: AND IT IS BUILT WHERE THE CURSOR IS, NOT PARKED OFF-SCREEN (2026-09).
//  It used to sit at `top:-1000px; left:-1000px`, which is the one thing every
//  other drag in this app deliberately does not do — the rows hand
//  `setDragImage` a LIVE, on-screen element (`shared/useDragRow`,
//  `TrainJobCard`), and the note there says why: a clone parked off-viewport
//  is not the form Safari renders reliably. It is also where the platform
//  thinks the picture CAME FROM, and a drag that ends with no drop animates
//  it back there — so an ordinary click, which is a drag here (a ONE-PIXEL
//  move between press and release fires `dragstart`, and the `dragend` that
//  follows carries `dropEffect: "none"`), flung the preview off towards a
//  corner of the screen. "Sometimes when clicking in the grid I see the drag
//  preview briefly animating from the top right corner" (owner 2026-09).
//  At the cursor, less the hotspot, the element sits exactly where the
//  platform is about to draw the drag image: there is nothing to animate,
//  and a frame of it painted before the removal is the drag image arriving.
function buildDragGhost(items: Array<{ active_file_id: number | null; rotation?: number;
                                        thumb_token?: string }>,
                        at: { x: number; y: number }): HTMLDivElement | null {
  const fileIds = items.filter((it) => it.active_file_id != null);
  if (fileIds.length === 0) return null;
  const wrap = document.createElement("div");
  wrap.style.cssText =
    `position:fixed; left:${at.x - GHOST_HOTSPOT}px; top:${at.y - GHOST_HOTSPOT}px;`
    + ` z-index:${LAYER.dragGhost}; width:${GHOST_THUMB + 28}px;`
    + ` height:${GHOST_THUMB + 28}px; pointer-events:none;`;
  const stack = fileIds.slice(0, 3);
  // Draw back-to-front so the primary image (index 0) sits on top, upright.
  for (let i = stack.length - 1; i >= 0; i--) {
    const off = i * 7;
    const rot = i === 0 ? 0 : (i % 2 === 1 ? 1 : -1) * (2 + i);
    const img = document.createElement("img");
    const it = stack[i];
    img.src = api.thumbUrl(it.active_file_id as number, it.rotation, it.thumb_token);
    img.style.cssText =
      `position:absolute; left:${6 + off}px; top:${6 + off}px;` +
      ` width:${GHOST_THUMB}px; height:${GHOST_THUMB}px; object-fit:cover;` +
      ` border-radius:10px; border:2px solid var(--border); background:var(--surface-float);` +
      ` box-shadow:var(--shadow-2); transform:rotate(${rot}deg);`;
    wrap.appendChild(img);
  }
  if (fileIds.length > 1) {
    const badge = document.createElement("div");
    badge.textContent = String(fileIds.length);
    badge.style.cssText =
      "position:absolute; right:0; top:0; min-width:20px; height:20px; padding:0 5px;" +
      " border-radius:10px; background:var(--accent); color:var(--on-accent);" +
      " font:700 11px/20px ui-monospace,monospace; text-align:center;" +
      " box-shadow:var(--shadow-1);";
    wrap.appendChild(badge);
  }
  return wrap;
}

// Root-to-target path through the (nested) group tree; null if not found.
function findGroupPath(nodes: GroupNode[], id: number, trail: GroupNode[] = []): GroupNode[] | null {
  for (const n of nodes) {
    const next = [...trail, n];
    if (n.id === id) return next;
    const deep = findGroupPath(n.children, id, next);
    if (deep) return deep;
  }
  return null;
}

export function ItemGrid() {
  // Individual primitive selectors, NOT a whole-store destructure: `useUI()`
  // subscribes to every store change (each marquee frame, each unrelated
  // panel's write), and an object selector would be a new object per render.
  const selectedGroups = useUI((s) => s.selectedGroups);
  const ungrouped = useUI((s) => s.ungrouped);
  const untagged = useUI((s) => s.untagged);
  const trashView = useUI((s) => s.trashView);
  const hiddenView = useUI((s) => s.hiddenView);
  const pendingView = useUI((s) => s.pendingView);
  const pendingKind = useUI((s) => s.pendingKind);
  const showPending = useUI((s) => s.showPending);
  const sequenceView = useUI((s) => s.sequenceView);
  const rankingView = useUI((s) => s.rankingView);
  const rankedView = useUI((s) => s.rankedView);
  const rankingPool = useUI((s) => s.rankingPool);
  const rankingDismissed = useUI((s) => s.rankingDismissed);
  const showRanking = useUI((s) => s.showRanking);
  const showRanked = useUI((s) => s.showRanked);
  const showAllItems = useUI((s) => s.showAllItems);
  const showKind = useUI((s) => s.showKind);
  const showSequence = useUI((s) => s.showSequence);
  const mediaKinds = useUI((s) => s.mediaKinds);
  const toggleMediaKind = useUI((s) => s.toggleMediaKind);
  const foldSequenced = useUI((s) => s.foldSequenced);
  const toggleFoldSequenced = useUI((s) => s.toggleFoldSequenced);
  const showHiddenItems = useUI((s) => s.showHiddenItems);
  const toggleShowHiddenItems = useUI((s) => s.toggleShowHiddenItems);
  const selectedItems = useUI((s) => s.selectedItems);
  const selectedSet = useUI((s) => s.selectedSet);
  const pointedItemIds = useUI((s) => s.pointedItemIds);
  const anchorItem = useUI((s) => s.anchorItem);
  const search = useUI((s) => s.search);
  const gridSize = useUI((s) => s.gridSize);
  const bookmarks = useUI((s) => s.bookmarks);
  const toggleBookmark = useUI((s) => s.toggleBookmark);
  const removeBookmark = useUI((s) => s.removeBookmark);
  const goToBookmark = useUI((s) => s.goToBookmark);
  const scrollToItem = useUI((s) => s.scrollToItem);
  const clearScrollToItem = useUI((s) => s.clearScrollToItem);
  const sortField = useUI((s) => s.sortField);
  const setSortField = useUI((s) => s.setSortField);
  const sortDir = useUI((s) => s.sortDir);
  const sortDirs = useUI((s) => s.sortDirs);
  const toggleSortDir = useUI((s) => s.toggleSortDir);
  const shuffle = useUI((s) => s.shuffle);
  const groupBy = useUI((s) => s.groupBy);
  const setGroupBy = useUI((s) => s.setGroupBy);
  // Dates and colour names are localized at the render site, not on the wire.
  const lang = useLang();
  const num = useNum();
  // The section a jump just landed on, flashed once with `.mc-flash`.
  const [flashKey, setFlashKey] = useState<string | null>(null);
  const [jumpOpen, setJumpOpen] = useState(false);
  const [marksOpen, setMarksOpen] = useState(false);
  const marksBtn = useRef<HTMLButtonElement>(null);
  const marksRect = useAnchorRect(marksBtn, marksOpen);
  const jumpBtn = useRef<HTMLButtonElement>(null);
  const jumpRect = useAnchorRect(jumpBtn, jumpOpen);
  useMenuDismiss(jumpOpen, () => setJumpOpen(false), { within: [jumpBtn] });
  useMenuDismiss(marksOpen, () => setMarksOpen(false), { within: [marksBtn] });
  const flashTimer = useRef<number | undefined>(undefined);
  const tagHighlight = useUI((s) => s.tagHighlight);
  const groupHighlight = useUI((s) => s.groupHighlight);
  const setSearch = useUI((s) => s.setSearch);
  const setGridSize = useUI((s) => s.setGridSize);
  const selectItem = useUI((s) => s.selectItem);
  const clearItemSelection = useUI((s) => s.clearItemSelection);
  const setSelectedItems = useUI((s) => s.setSelectedItems);
  const setVisibleItemIds = useUI((s) => s.setVisibleItemIds);
  const selectGroup = useUI((s) => s.selectGroup);
  const clearGroupSelection = useUI((s) => s.clearGroupSelection);
  const openEditor = useUI((s) => s.openEditor);
  const openEditorMulti = useUI((s) => s.openEditorMulti);
  const openAnnotator = useUI((s) => s.openAnnotator);
  const openAnnotatorMulti = useUI((s) => s.openAnnotatorMulti);
  const qaMode = useUI((s) => s.qaMode);
  const qaSets = useUI((s) => s.qaSets);
  const qaSelected = useUI((s) => s.qaSelected);
  const setQuickLook = useUI((s) => s.setQuickLook);
  const setOverlay = useUI((s) => s.setOverlay);
  const t = useT();
  const tn = useTn();
  // Right-click context menu on a grid card: screen position + target ids.
  // Targets: the clicked item when it is NOT part of the selection (the
  // selection is left untouched); otherwise the whole selection.
  const [ctxMenu, setCtxMenu] = useState<null | { x: number; y: number; ids: number[]; clickedId: number }>(null);
  // Re-render after a copy, a clipboard clear or an extra-output flip: the
  // menu is rebuilt from what those changed.
  const [clipTick, setClipTick] = useState(0);
  // The targets' slim details, fetched ONCE when the menu opens: which copy
  // rows to offer is read off them, and what number each row carries.
  const [ctxDetails, setCtxDetails] = useState<ItemSlim[] | null>(null);
  // Past the endpoint's 500-id cap the probe covers the FIRST 500 only — one
  // request, whatever the selection. It is enough to decide which rows are
  // worth offering; it is not the whole answer, so those rows show no count
  // and a copy re-reads every target (see `ctxCopy`).
  const ctxSampled = !!ctxMenu && ctxMenu.ids.length > 500;
  // The Actions tab's AI actions, offered in the menu too — READY ones only
  // (an action still needing setup or a download stays a sidebar affair,
  // where its chip can explain itself). Queried only while a menu is open.
  const { data: ctxModels } = useQuery({
    queryKey: ["ml-models"], queryFn: api.mlModels, enabled: ctxMenu != null,
  });
  const { data: ctxCache } = useQuery({
    queryKey: ["model-cache"], queryFn: api.modelCache, enabled: ctxMenu != null,
  });
  //: THE LAST USED ACTION (`ctxLastUsed.ts`), remembered per browser and
  //  held here too so the quick-actions menu's row and the L key can offer
  //  it again the moment it changes.
  const [lastRaw, setLastRaw] = useState<string | null>(() => {
    try { return storage.get(LAST_ACTION_KEY); } catch { return null; }
  });
  const rememberLast = (a: LastAction) => {
    const raw = serializeLastAction(a);
    try { storage.set(LAST_ACTION_KEY, raw); } catch { /* ignore */ }
    setLastRaw(raw);
  };
  /** One run, however it was asked for — the context menu, W, L. */
  const enqueueFor = async (ids: number[], kind: JobKind, model: string,
                            task: TaskInfo, name: string) => {
    if (!ids.length) return;
    rememberLast({ kind, model, task: task.label, name });
    // The panels task's "into a sequence" switch mirrors the sidebar's
    // remembered choice — the one reader (`readPanelsSequence`) the split
    // button and both context menus share, so no two of them can answer a
    // run differently.
    const intoSequence = task.sequence_option && readPanelsSequence();
    // A "read it, then remove" row rides its OCR engine on the model id;
    // split the rider off and send it as `detect_with`.
    const [realModel, detectWith] = model.split(DETECT_WITH);
    await api.enqueueJobs(kind, realModel, ids, intoSequence, "", false,
                          detectWith ?? "");
    qc.invalidateQueries({ queryKey: ["ml-jobs"] });
  };
  const ctxEnqueue = async (kind: JobKind, model: string, task: TaskInfo,
                            name: string) => {
    const ids = ctxMenu?.ids ?? [];
    setCtxMenu(null);
    await enqueueFor(ids, kind, model, task, name);
  };
  /** W: REMOVE WATERMARKS from the selected images with the first READY
   *  remover — the context menu's Edit → Remove watermark, as one key. The
   *  models are fetched on the press (the menu's own query runs only while
   *  a menu is open) and readiness is the menu's rule: available, and every
   *  source cached. With nothing ready, or nothing selected that a remover
   *  can act on, the toast says so rather than the key doing nothing. */
  const removeWatermarks = async () => {
    const ids = useUI.getState().selectedItems
      .filter((id) => itemById.get(id)?.kind === "image");
    if (!ids.length) {
      setSelNote(t("Select the images to remove watermarks from first"));
      return;
    }
    const [models, cache] = await Promise.all([
      qc.fetchQuery({ queryKey: ["ml-models"], queryFn: api.mlModels }),
      qc.fetchQuery({ queryKey: ["model-cache"], queryFn: api.modelCache }),
    ]);
    const task = (models?.tasks ?? []).find((tk) => tk.kind === "watermark_removal");
    const model = (task?.models ?? []).find(readyModel(cache?.models));
    if (!task || !model) {
      setSelNote(t("No watermark remover is set up yet — see Settings → Models"));
      return;
    }
    await enqueueFor(ids, task.kind, model.id, task, model.family || model.name);
  };
  const removeWatermarksRef = useRef(removeWatermarks);
  removeWatermarksRef.current = removeWatermarks;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "w" && e.key !== "W") return;
      if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
      if (isTypingTarget(e)) return;
      // The page-level rule: nothing over the page — the item window, a
      // session, a dialog — may hear the grid's own letters.
      if (modalIsOpen()) return;
      e.preventDefault();
      void removeWatermarksRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    setCtxDetails(null);
    if (!ctxMenu) return;
    let alive = true;
    void api.itemDetails(ctxMenu.ids.slice(0, 500)).catch(() => null)
      .then((r) => { if (alive && r) setCtxDetails(r.items); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctxMenu?.ids.join(",")]);
  // The three catalogs that say which of an item's tags are a person, a place
  // or an event. Only while a menu is open — the answer is a tag-name set, and
  // the queries are the ones the sidebar already caches.
  const { data: allSubjects } = useQuery({
    queryKey: ["subjects"], queryFn: api.subjects, enabled: !!ctxMenu });
  const { data: ctxPlaces } = useQuery({
    queryKey: ["places"], queryFn: api.places, enabled: !!ctxMenu });
  const { data: ctxEvents } = useQuery({
    queryKey: ["events"], queryFn: api.events, enabled: !!ctxMenu });
  /** The identity tags of one of the three, as a set. */
  const kindTags = (what: "subjects" | "places" | "events"): Set<string> => {
    const rows = what === "subjects" ? allSubjects
      : what === "places" ? ctxPlaces : ctxEvents;
    return new Set((rows ?? []).map((r) => r.tag).filter(Boolean));
  };
  /** The targets' positive, non-pending direct tag names that `what` claims. */
  const ctxKindNames = (what: "subjects" | "places" | "events",
                        details: ItemSlim[]): string[] => {
    const wanted = kindTags(what);
    const out: string[] = [];
    for (const d of details) {
      for (const inst of d.tag_instances) {
        if (inst.negative || inst.pending) continue;
        if (wanted.has(inst.name) && !out.includes(inst.name)) out.push(inst.name);
      }
    }
    return out;
  };

  /** The slim details for a batch of ids — chunked at the endpoint's 500-id
   *  cap, sequential, items that failed simply absent (like the per-item
   *  `.catch(() => null)` this replaces). */
  const fetchDetails = async (ids: number[]): Promise<ItemSlim[]> => {
    const out: ItemSlim[] = [];
    for (const part of chunks(ids, 500)) {
      const r = await api.itemDetails(part).catch(() => null);
      if (r) out.push(...r.items);
    }
    return out;
  };

  // ---- context-menu actions ------------------------------------------------
  // Loaded items by id (memoized on the loaded pages — `itemById` below), so
  // menu rendering and its actions do O(1) lookups instead of a find() per id.
  const ctxTargets = (): ItemOut[] =>
    (ctxMenu?.ids ?? [])
      .map((id) => itemById.get(id))
      .filter((i): i is ItemOut => i != null);

  /** Copy one kind, or several — Copy all is the same call with every kind
   *  the targets carry, so the two can never disagree about what a copy of
   *  something IS. */
  const ctxCopy = async (kinds: ClipKind[]) => {
    const targets = ctxTargets();
    const ids = ctxMenu?.ids ?? [];
    setCtxMenu(null);
    // The menu's probe already read these, unless it only SAMPLED them (see
    // `ctxSampled`) — a copy always covers every target, so that case pays
    // for the full read here, once for the whole list of kinds.
    const details = (ctxSampled || !ctxDetails)
      ? await fetchDetails(ids) : ctxDetails;
    for (const what of kinds) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (CTX_CLIPBOARD as any)[what] = copyOne(what, details, targets);
    }
    // And the ids, on the SYSTEM clipboard. The app's own clipboard cannot
    // leave the page, and what somebody reaches for after copying a picture
    // is often its id — for the "Similar to" field, or somewhere else
    // entirely.
    copyUids(targets.map((i) => i.uid).filter(Boolean));
    setClipTick((t) => t + 1);
  };

  /** WHAT a copy of one kind would put on the clipboard.
   *
   *  Returned rather than assigned, because the menu needs the same answer to
   *  decide whether to offer the row at all and what number to put on it —
   *  and a row that says "Copy tags (4)" and then copies something else would
   *  be two implementations of one idea. */
  const copyOne = (what: ClipKind, details: ItemSlim[],
                   targets: ItemOut[]): unknown[] => {
    if (what === "tags") {
      // Union of the targets' DIRECT tags (first occurrence wins the sign),
      // keeping each tag's placements into the item's tag groups (by group
      // name; null = ungrouped). Needs the item detail — the grid rows carry
      // no tag-group info. Pending machine tags and the system Pending group
      // are skipped, like pending captions are.
      const seen = new Map<string, { negative: boolean; groups: Set<string | null> }>();
      for (const d of details) {
        const groupsById = new Map(d.tag_groups.map((g) => [g.id, g]));
        for (const inst of d.tag_instances) {
          if (inst.pending) continue;
          const g = inst.group_id != null ? groupsById.get(inst.group_id) : null;
          if (g?.system) continue;
          let e = seen.get(inst.name);
          if (!e) { e = { negative: inst.negative, groups: new Set() }; seen.set(inst.name, e); }
          e.groups.add(g ? g.name : null);
        }
      }
      return Array.from(seen, ([name, e]) => ({
        name, negative: e.negative, groups: Array.from(e.groups),
      }));
    }
    if (what === "groups") {
      return Array.from(new Set(targets.flatMap((i) => i.group_ids)));
    }
    if (what === "captions") {
      const texts: string[] = [];
      for (const d of details) {
        for (const c of d.captions) {
          if (c.pending || (c.kind ?? "caption") !== "caption") continue;
          if (!texts.includes(c.text)) texts.push(c.text);
        }
      }
      return texts;
    }
    if (what === "instructions") {
      // Text AND the ordered sources: an instruction says how the picture was
      // made FROM those items, so one without the other is a different claim.
      const out: { text: string; refs: number[] }[] = [];
      for (const d of details) {
        for (const c of d.captions) {
          if (c.pending || c.kind !== "instruction") continue;
          const refs = (c.refs ?? []).map((r) => r.item_id);
          const key = JSON.stringify([c.text, refs]);
          if (out.some((o) => JSON.stringify([o.text, o.refs]) === key)) continue;
          out.push({ text: c.text, refs });
        }
      }
      return out;
    }
    if (what === "links") {
      // Both directions, deduped by (other item, direction, kind). A link to
      // one of the copied items is kept — the paste is what drops the ones
      // that would point an item at itself.
      const seen = new Set<string>();
      const out: NonNullable<typeof CTX_CLIPBOARD.links> = [];
      for (const d of details) {
        for (const l of d.links ?? []) {
          const key = `${l.other_item_id}:${l.outgoing}:${l.kind}`;
          if (seen.has(key)) continue;
          seen.add(key);
          out.push({ other: l.other_item_id, outgoing: l.outgoing,
                     kind: l.kind, tags: l.tags });
        }
      }
      return out;
    }
    return ctxKindNames(what, details);
  };

  // Post-edit invalidation, narrowed: the touched items' details refresh
  // immediately; the list/catalog queries go through the short-wait coalescer
  // so pasting onto (or hiding/trashing) a big selection sweeps once.
  const ctxInvalidate = (ids: number[]) => {
    for (const id of ids) bumpItem(id);
    bumpEdits();
  };

  const ctxPaste = async (kinds: ClipKind[]) => {
    const ids = ctxMenu?.ids ?? [];
    setCtxMenu(null);
    // Items at the far end of a pasted link also change (their own Linked-by
    // list gains a row), so they are refreshed alongside the targets.
    const touched = new Set(ids);
    for (const id of ids) for (const what of kinds) {
      if (what === "tags") {
        const tags = CTX_CLIPBOARD.tags ?? [];
        // Recreate the copied tag-group structure: match the target's existing
        // tag groups by name, create the missing ones once, then place each
        // tag into the same groups it came from (null = ungrouped default).
        const groupIds = new Map<string, number>();
        if (tags.some((t) => t.groups.some((g) => g !== null))) {
          const d = await api.item(id).catch(() => null);
          for (const g of d?.tag_groups ?? []) {
            if (!g.system && !groupIds.has(g.name)) groupIds.set(g.name, g.id);
          }
        }
        for (const t of tags) {
          const placements = t.groups.length > 0 ? t.groups : [null];
          const grouped = placements.some((g) => g !== null);
          for (const g of placements) {
            if (g === null) {
              // Plain assign unless the tag ALSO lives in groups — then the
              // ungrouped instance needs an explicit placement row (an
              // implicit one only renders while no placements exist).
              if (grouped) await api.addTagToGroup(id, t.name, null, t.negative);
              else await api.assignItemTag(id, t.name, t.negative);
              continue;
            }
            let gid = groupIds.get(g);
            if (gid == null) {
              gid = (await api.createTagGroup(id, g)).id;
              groupIds.set(g, gid);
            }
            await api.addTagToGroup(id, t.name, gid, t.negative);
          }
        }
      } else if (what === "groups") {
        for (const g of CTX_CLIPBOARD.groups ?? []) await api.addItemGroup(id, g);
      } else if (what === "captions") {
        for (const tx of CTX_CLIPBOARD.captions ?? []) await api.addCaption(id, tx);
      } else if (what === "instructions") {
        for (const ins of CTX_CLIPBOARD.instructions ?? []) {
          const made = await api.addCaption(id, ins.text, "instruction")
            .catch(() => null);
          if (!made) continue;
          // An instruction lives on the RESULT with its sources as refs, so a
          // reference to the target itself is dropped rather than pasted.
          const refs = ins.refs.filter((r) => r !== id);
          if (refs.length) await api.setCaptionRefs(id, made.id, refs)
            .catch(() => null);
        }
      } else if (what === "links") {
        for (const l of CTX_CLIPBOARD.links ?? []) {
          if (l.other === id) continue; // an item pointing at itself
          const rel = await api.addRelationship(
            l.outgoing ? id : l.other, l.outgoing ? l.other : id, l.kind,
          ).catch(() => null); // refused as a cycle, or the other item is gone
          if (!rel) continue;
          touched.add(l.other);
          for (const name of l.tags) {
            await api.addLinkTag(rel.id, name).catch(() => null);
          }
        }
      } else {
        // A subject, a place and an event are each a tag, so pasting one is
        // assigning that tag — idempotent, and nothing downstream is new.
        for (const name of CTX_CLIPBOARD[what] ?? []) {
          await api.assignItemTag(id, name, false).catch(() => null);
        }
      }
    }
    ctxInvalidate(Array.from(touched));
  };

  const ctxHide = async (hide: boolean) => {
    const ids = ctxMenu?.ids ?? [];
    setCtxMenu(null);
    await api.hideItems(ids, hide);
    ctxInvalidate(ids);
  };

  const ctxTrash = async () => {
    const ids = ctxMenu?.ids ?? [];
    setCtxMenu(null);
    await api.trashItems(ids);
    setSelectedItems(selectedItems.filter((id) => !ids.includes(id)));
    ctxInvalidate(ids);
  };
  /** THE TRASH'S OWN VERB. Everywhere else the red row says "Move to trash"
   *  and does exactly that — the name it always should have had, since what
   *  it does is reversible and "Delete" is what people expect not to be.
   *
   *  In the Trash that row was still labelled "Delete" and still called
   *  `trashItems` on items that are already in there: a menu entry that did
   *  nothing at all, on the one screen where "delete" is the thing you came
   *  to do. Here it is the real one, and it asks first, in the same words the
   *  sidebar's Delete asks in — this is the only removal in the app with no
   *  way back. */
  const ctxDeleteForever = async () => {
    const ids = ctxMenu?.ids ?? [];
    setCtxMenu(null);
    if (ids.length === 0) return;
    if (!(await confirm({
      title: tn({ one: "Permanently delete 1 item?",
                  other: "Permanently delete {n} items?" }, ids.length),
      body: tn({
        one: "This removes the image and all its versions, tags and captions. This cannot be undone.",
        other: "This removes the images and all their versions, tags and captions. This cannot be undone.",
      }, ids.length),
      answer: { label: t("Delete"), danger: true },
    }))) return;
    await api.deleteItems(ids);
    setSelectedItems(selectedItems.filter((id) => !ids.includes(id)));
    ctxInvalidate(ids);
  };

  // ---- windowed geometry (declared before the data hook: the visible range
  // is what drives which pages are fetched). The geometry and the box are
  // `useCardGrid` — the same hook the Faces grid draws with — and what is
  // this grid's own is below it: the ids behind the indices, the pages, the
  // keyboard walk and the scroll anchoring.
  const scrollRef = useRef<HTMLDivElement>(null);
  // THE COUNT THE LAYOUT IS BUILT FROM, READ OUT OF THE CACHE.
  //
  // The window drives the fetch and the fetch answers the total, so this
  // cannot be `view.total`: the view hook is declared BELOW, because it takes
  // the window. It used to be a REF written just after that hook — which the
  // geometry had already read, so the layout was always one render behind the
  // count, and after a scope change nothing guarantees that render: the fetch
  // range is computed from the SCROLL, not from the count, so the settled
  // range never changes and nothing else re-renders. The grid then sat at
  // count ZERO with every page loaded and drew nothing at all, until a
  // resize, a scroll or any other render happened to come along — "the grid
  // stays empty until I reload the page" (owner 2026-09; the tell was that
  // opening the inspector, which resizes the pane, made the cards appear).
  //
  // Page 1 has already put the answer in the CACHE by the time this component
  // re-renders for it — the page queries below are what triggered the render —
  // so reading it here is the same answer in the same frame, no lag and no
  // extra render. It is not a subscription, and it does not need to be: the
  // hook below is the subscriber.
  const qc = useQueryClient();
  const { req: viewReq, filtersKey, treeKey, sort: viewSort } = useViewRequest();
  // While the new view's page 1 is still in flight the cache has nothing, and
  // the layout keeps the size it last KNEW rather than collapsing to nothing
  // for the wait — the cards are placeholders either way, and an empty grid
  // that then has to grow back is a flash of "there is nothing here".
  const lastTotal = useRef(0);
  const cachedTotal = qc.getQueryData<ItemPage>(
    ["items", filtersKey, treeKey, viewSort, 1])?.total;
  if (cachedTotal != null) lastTotal.current = cachedTotal;
  const layoutCount = lastTotal.current;
  // ---- sections ------------------------------------------------------------
  // Grouping is meaningless inside a sequence view, whose order is the
  // sequence's own. DERIVED rather than written to the store, mirroring
  // `sortDisabled` below — so leaving the sequence restores the grouping you
  // had.
  //
  // A RANKING VIEW ARRIVES GROUPED, which no other view does: its sections
  // are the standings' own buckets, and that is the overview the histogram on
  // the old rankings page used to be — the pictures themselves at the size
  // you judge them, under headings you can scroll and jump between. The
  // store's `groupBy` is a date/name/colour answer that means nothing here,
  // so it is DERIVED past rather than written over — leaving the ranking
  // restores the grouping you had, the sequence view's own rule.
  // A RANKING VIEW ARRIVES GROUPED, which no other view does: its sections
  // are the standings' own buckets, which is the overview the rankings page's
  // histogram used to be — except made of the pictures themselves, at the
  // size somebody actually judges them at.
  //
  // AN EFFECT ON THE RANKING, not a write inside `showRanking`: there are
  // three doors into this view — the sidebar row, an address pasted or
  // reloaded, and Back — and only the first goes through that setter. The
  // other two would have arrived ungrouped. Keyed on which ranking, so
  // turning the sections off stays off while you are in one and switching to
  // another is a new view.
  useEffect(() => {
    if (rankingView != null && !rankingDismissed) setGroupBy("bucket");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rankingView, rankingPool, rankingDismissed]);
  const effGroupBy: GroupBy =
    sequenceView != null ? "none"
      : rankingView != null && !rankingDismissed
        ? (groupBy === "none" ? "none" : "bucket")
      // AND `bucket` NEVER LEAKS OUT of a ranking view: it is the grouping
      // `showRanking` arrives with, and the backend REFUSES a grouping that
      // is not a coarsening of the sort — so carrying it into a date-sorted
      // library view would 400 the section query rather than degrade.
      : groupOptionsFor(sortField).includes(groupBy) ? groupBy : "none";
  const runsView = useGroupRuns(effGroupBy);
  // While the runs are still in flight the grid lays out UNGROUPED: it is the
  // same items in the same order, so this is correct rather than a guess —
  // grouping is purely a re-layout. The cost is one reflow when they land,
  // which `groupBy` in the scroll-reset deps puts at scrollTop 0.
  const grid = useCardGrid({
    count: layoutCount, size: gridSize, metaH: META_H, gap: GAP, pad: PAD, scrollRef,
    runs: effGroupBy !== "none" && runsView.ready ? runsView.runs : null,
    headerH: HEADER_H, groupGap: GROUP_GAP, rowBuffer: ROW_BUFFER,
    cardSelector: "[data-item-card]",
    onMarqueeStart: (e) => {
      // Take keyboard focus so arrow-key selection works right after a click.
      scrollRef.current?.focus({ preventScroll: true });
      const additive = e.shiftKey || e.metaKey || e.ctrlKey;
      boxBase.current = {
        base: additive ? selectedItems : [],
        // The store's lockstep Set — never mutated in place, safe to hold.
        baseSet: additive ? selectedSet : new Set<number>(),
        baseMembers: (additive ? selMembers : new Set<number>()) as ReadonlySet<number>,
        lastHits: null,
      };
    },
    onMarquee: (idxs, additive) => {
      // Hit-test in index space (pure, tested), then resolve to LOADED ids —
      // an index whose page isn't loaded can't be selected by a marquee.
      const hit: number[] = [];
      for (const i of idxs) {
        const id = getIdAt(i);
        if (id != null) hit.push(id);
      }
      const bb = boxBase.current;
      // The rect only crosses a card boundary now and then — when this
      // frame's hits match the last frame's, skip the store entirely.
      const prev = bb.lastHits;
      if (prev && prev.length === hit.length && prev.every((v, i) => v === hit[i])) return;
      bb.lastHits = hit;
      // Additive union off the base captured at the press.
      setSelectedItems(additive ? bb.base.concat(hit.filter((id) => !bb.baseSet.has(id))) : hit);
      // The sweep names the occurrences it crossed (sequence view).
      if (sequenceView != null) {
        const ms = new Set<number>(additive ? bb.baseMembers : undefined);
        for (const i of idxs) {
          const m = getItem(i)?.member_id;
          if (m != null) ms.add(m);
        }
        setSelMembers(ms);
      }
    },
    // A press on the background that never became a box clears the selection.
    onBackgroundClick: (additive) => { if (!additive) clearItemSelection(); },
    onScroll: (top) => rememberAnchorRef.current(top),
  });
  const { columns, cellW, rowStride, layout, win, gwin, physH, yShift, toVirt, toPhys,
          scrollTop, vpH, box: marquee, dragMoved: dragMovedRef } = grid;
  const cardH = cellW + META_H;
  // What the box captured at its press, read by the hit callback per frame.
  const boxBase = useRef<{ base: number[]; baseSet: ReadonlySet<number>;
                           baseMembers: ReadonlySet<number>; lastHits: number[] | null }>(
    { base: [], baseSet: new Set(), baseMembers: new Set(), lastHits: null });

  // The fetch range: rows near the viewport as flat indices, deliberately NOT
  // clamped by the (possibly still unknown) total — useItemView clamps to the
  // view's real page count itself. Grouped, the window IS the fetch range;
  // it stays one contiguous span (see `groupWindow`), so nothing below here
  // learns that sections exist.
  const fetchFirstRow = Math.max(0, Math.floor((scrollTop - PAD) / rowStride) - ROW_BUFFER);
  const fetchRows = Math.ceil(vpH / rowStride) + ROW_BUFFER * 2;

  // ---- data: windowed per-page queries driven by the visible index range ----
  // NOTE `end` is INCLUSIVE here (useItemView reads the page CONTAINING it),
  // while the window's endIdx is exclusive.
  const view = useItemView(gwin
    ? { start: gwin.startIdx, end: Math.max(gwin.startIdx, gwin.endIdx - 1) }
    : {
      start: fetchFirstRow * columns,
      end: (fetchFirstRow + fetchRows + 1) * columns - 1,
    });
  const { total, getItem, getIdAt, indexOfId, indexOfMember, loadedIds,
          loadedItems } = view;

  // Loaded items by id: context-menu targets, drag ghosts, double-click prefs.
  const itemById = useMemo(() => {
    const m = new Map<number, ItemOut>();
    for (const it of loadedItems) m.set(it.id, it);
    return m;
  }, [loadedItems]);

  // Cmd+A over a partially-loaded view selects what is loaded; this note says
  // so once (auto-dismissing — it is information, not an undo affordance).
  const [selNote, setSelNote] = useState<string | null>(null);
  /** L: THE LAST USED ACTION AGAIN, over the selection — the context menu's
   *  "Last used" row as one key, and the quick-actions menu's row. Offered
   *  only while the menu would offer it for these pictures (the kind gate
   *  and a READY model, `offeredLastAction`); the models are read off the
   *  same cached keys the menus use. */
  const { data: allModels } = useQuery({
    queryKey: ["ml-models"], queryFn: api.mlModels, staleTime: 60_000 });
  const { data: allCache } = useQuery({
    queryKey: ["model-cache"], queryFn: api.modelCache, staleTime: 60_000 });
  const lastAction = useMemo(() => parseLastAction(lastRaw), [lastRaw]);
  const lastOffered = useMemo(() => {
    if (!lastAction || trashView) return null;
    const kinds = selectedItems.map((id) => itemById.get(id)?.kind ?? "image");
    const rows = taskSections(allModels?.tasks, readyModel(allCache?.models),
                              targetsTake(kinds)).flatMap((s) => s.rows);
    return offeredLastAction(lastAction, rows);
  }, [lastAction, allModels, allCache, selectedItems, itemById, trashView]);
  const repeatLast = async () => {
    const ids = useUI.getState().selectedItems;
    if (!lastAction) {
      setSelNote(t("Nothing to repeat yet — run an action from an item's context menu first"));
      return;
    }
    if (!ids.length) { setSelNote(t("Select the items first")); return; }
    if (!lastOffered) {
      setSelNote(t("{action} is not offered for the selected items",
                   { action: `${t(lastAction.task)} · ${lastAction.name}` }));
      return;
    }
    await enqueueFor(ids, lastOffered.row.tk.kind as JobKind, lastAction.model,
                     lastOffered.row.tk, lastAction.name);
  };
  const repeatLastRef = useRef(repeatLast);
  repeatLastRef.current = repeatLast;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "l" && e.key !== "L") return;
      if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
      if (isTypingTarget(e)) return;
      if (modalIsOpen()) return;
      e.preventDefault();
      void repeatLastRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Stamp (or strip) the SELECTED Quick-Assign set onto a single item. The
  // tick and the click-to-assign mode both follow the drawer's selection —
  // with no set selected there is nothing to stamp and nothing to tick.
  const qaSel = qaSelected != null ? qaSets[qaSelected] ?? null : null;
  const qaPos = qaSel?.pos ?? [];
  const qaNeg = qaSel?.neg ?? [];
  const qaGroups = qaSel?.groups ?? [];
  const qaActive = qaPos.length > 0 || qaNeg.length > 0
    || qaGroups.length > 0;
  const runQuick = async (itemId: number, remove: boolean) => {
    if (!qaActive) return;
    await api.quickAssign({
      item_ids: [itemId], positive: qaPos, negative: qaNeg,
      assign_groups: qaGroups, remove,
    });
    // Quick-Assign is the rapid-fire path (one click per item down a grid row)
    // — exactly what the coalescer exists for.
    bumpItem(itemId);
    bumpEdits();
  };

  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const { data: allGroups } = useQuery({ queryKey: ["groups"], queryFn: api.groups });
  const { data: allSequences } = useQuery({ queryKey: ["sequences"], queryFn: api.sequences });
  // The ranking rows, for the breadcrumb's name and its pool's — fetched
  // only while a ranking view is what is on screen.
  const { data: rankingRows } = useQuery({
    queryKey: ["rankings"], queryFn: () => api.rankings(),
    enabled: rankingView != null || rankedView });
  // The open sequence, fetched directly so the breadcrumb always resolves its
  // name even if it isn't (yet) in the cached list query.
  const { data: openSequence } = useQuery({
    queryKey: ["sequence", sequenceView],
    queryFn: () => api.sequence(sequenceView as number),
    enabled: sequenceView != null,
  });

  // ---- which OCCURRENCES the selection gestures touched (sequence view) ----
  // The SELECTION stays by item id — a repeated page picked anywhere is one
  // picture, and the next action happens to it once — but the grid still says
  // which copy you MEANT: that occurrence keeps the solid ring and the other
  // copies of the same item wear a grey one. Tracked as membership-row ids;
  // a selection made by something that names no occurrence (a link pick, the
  // menu's Preview) leaves an item with no tracked member, and such an item's
  // copies are all primary — the old look, which is also the honest one.
  // STORE state, not local: the sidebar's "Remove from sequence" reads it to
  // take only the copies the gesture named.
  const selMembers = useUI((s) => s.selMembers);
  const setSelMembers = useUI((s) => s.setSelMembers);
  const memberAnchorIdx = useRef<number | null>(null);
  useEffect(() => {
    setSelMembers(new Set());
    memberAnchorIdx.current = null;
  }, [sequenceView]);
  /** Member ids of the loaded occurrences between two flat indices. */
  const membersInRange = (a: number, b: number): number[] => {
    const out: number[] = [];
    for (let i = Math.min(a, b); i <= Math.max(a, b); i++) {
      const m = getItem(i)?.member_id;
      if (m != null) out.push(m);
    }
    return out;
  };
  // Items with at least one tracked occurrence — the ones whose OTHER copies
  // go dashed. Null = no tracking in force (every copy primary).
  const memberTracked = useMemo(() => {
    if (sequenceView == null || selMembers.size === 0) return null;
    const s = new Set<number>();
    for (const it of loadedItems) {
      if (it.member_id != null && selMembers.has(it.member_id)) s.add(it.id);
    }
    return s;
  }, [sequenceView, selMembers, loadedItems]);

  // ---- reordering a sequence by dragging its cards --------------------------
  // The dragged card's MEMBERSHIP row (an occurrence, not the item — a
  // repeated page moves one copy); the drop inserts before/after the card
  // under the pointer, by which half of it the pointer is in.
  const reorderMember = useRef<number | null>(null);
  const [dropMark, setDropMark] = useState<{ member: number; after: boolean } | null>(null);
  const reorderTo = async (target: number, after: boolean) => {
    const dragged = reorderMember.current;
    reorderMember.current = null;
    setDropMark(null);
    if (sequenceView == null || dragged == null || dragged === target) return;
    // The FULL member list, from the open sequence's own query — the grid is
    // windowed, so its loaded pages cannot stand in for the whole order.
    const members = openSequence?.members;
    if (!members) return;
    const ids = members.map((m) => m.id).filter((id) => id !== dragged);
    const at = ids.indexOf(target);
    if (at < 0) return;
    ids.splice(at + (after ? 1 : 0), 0, dragged);
    await api.reorderSequence(sequenceView, ids);
    // WRITE THE CONFIRMED ORDER INTO THE CACHE BEFORE INVALIDATING. The next
    // drag can begin before the refetches land, and this function computes
    // the FULL order from that cache — left stale, a quick second reorder is
    // built on the PRE-drag base and sends an order that quietly undoes or
    // garbles the first (measured live: two back-to-back reorders, the
    // second's request bore no resemblance to its gesture). With the cache
    // current the refetch also arrives byte-identical to what is rendered,
    // so React moves no card nodes under a drag already in progress — a
    // moved DOM node is a cancelled native drag.
    qc.setQueryData(["sequence", sequenceView],
      (old: { members?: { id: number }[] } | undefined) => {
        if (!old?.members || old.members.length !== ids.length) return old;
        const by = new Map(old.members.map((m) => [m.id, m]));
        const members = ids.map((id) => by.get(id));
        return members.every(Boolean) ? { ...old, members } : old;
      });
    qc.invalidateQueries({ queryKey: ["sequence"] });
    bumpEdits(); // sweeps the item pages, which is where the new order shows
  };

  // Feed the editor's next/prev navigation with the loaded ids in view order
  // (the loaded pages — `loadedIds` keeps its identity while nothing changes).
  useEffect(() => {
    setVisibleItemIds(loadedIds);
  }, [loadedIds, setVisibleItemIds]);

  // WHERE THE ANCHOR SITS IN THE VIEW, remembered when it is clicked.
  //
  // A shift+click's range is between two POSITIONS, and the grid can only
  // look an id's position up while its page is loaded — so scrolling far
  // enough for the anchor to fall out of the window made the range
  // unanswerable and the click collapsed to selecting one item. The index
  // does not fall out: it is what the grid pages by.
  const anchorIdx = useRef<number | null>(null);

  // Keep the keyboard cursor aligned with the anchor: a click (which sets the
  // anchor) reseats the cursor there, so the next arrow starts from what was
  // clicked. Shift+Arrow leaves the anchor untouched, so the cursor keeps moving.
  useEffect(() => {
    cursorRef.current = anchorItem;
    // WHICH CARD, kept with it. An arrow has just named the one it stepped
    // to; anything else that moved the anchor is a click, which named the
    // card it was on. `cursorIdx` verifies whichever this is before
    // believing it, so a stale index costs nothing.
    const at = cursorIdxRef.current;
    if (at == null || getIdAt(at) !== anchorItem) {
      cursorIdxRef.current = anchorIdx.current;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorItem]);

  /** WHERE THE ANCHOR SITS, as a flat position.
   *
   *  The card it was set on while the pages still hold that item there — an
   *  id lookup cannot tell two copies of a repeated page apart, and in a
   *  sequence view it answers with whichever copy the index map wrote last —
   *  else what the loaded pages say, else where it was when it was set. */
  const anchorIndex = (): number | null => {
    const at = anchorIdx.current;
    if (at != null && getIdAt(at) === anchorItem) return at;
    const known = anchorItem != null ? indexOfId(anchorItem) : -1;
    return known !== -1 ? known : anchorIdx.current;
  };

  /** Select the stretch between two flat POSITIONS — what a shift gesture
   *  means, for the mouse and the arrow keys alike. The ids come from the
   *  loaded pages when they cover the range (the common case, no request),
   *  and from the server when they do not, which is the one question the
   *  grid cannot answer about its own view. False when neither could. */
  const selectRange = async (from: number, to: number): Promise<boolean> => {
    const lo = Math.min(from, to);
    const hi = Math.max(from, to);
    const want = hi - lo + 1;
    const local: number[] = [];
    for (let i = lo; i <= hi && local.length === i - lo; i++) {
      const at = getIdAt(i);
      if (at != null) local.push(at);
    }
    if (local.length === want) {
      setSelectedItems(local);
      return true;
    }
    try {
      const got = await api.itemIdRange(viewReq, lo, want);
      if (got.ids.length) { setSelectedItems(got.ids); return true; }
    } catch { /* the caller falls back to its own answer */ }
    return false;
  };

  /** One click's selection — and a SHIFT range is between two POSITIONS.
   *
   * It used to be `ordered.indexOf(anchor)` over the loaded ids, which is
   * wrong in two ways once the other end has been scrolled away from. The
   * loaded pages are the ones near the viewport plus whatever React Query
   * still holds, so that list is **not contiguous**: with page 1 and page
   * 167 both in it, the "range" between them was the hundred-odd ids that
   * happen to sit between them in an array with a hole in the middle. And
   * when the anchor's page HAS been dropped, `indexOf` answers -1 and the
   * click collapsed to selecting one item. Both go away by working in flat
   * indices (`anchorIndex`, `selectRange`), which is what the grid pages by
   * and what does not fall out of the window.
   */
  const clickSelect = async (id: number, index: number,
                             shift: boolean, meta: boolean) => {
    const from = anchorIndex();
    if (shift && !meta && from != null && await selectRange(from, index)) {
      return;
    }
    // A REPEATED PAGE IS SEVERAL CARDS OF ONE ITEM, so a plain click on
    // another of its cards is not the click that lets a selection go —
    // `selectItem`'s way out, which every list here has — but a move to a
    // different occurrence of the same picture. What moved is the card.
    const otherCopy = !shift && !meta && selectedItems.length === 1
      && selectedItems[0] === id && anchorIndex() !== index;
    if (!otherCopy) selectItem(id, { meta, shift }, loadedIds);
    // The anchor moved unless this was a shift-extend, which keeps it —
    // and with it the card an arrow key carries on from.
    if (!shift) {
      anchorIdx.current = index;
      cursorIdxRef.current = index;
    }
  };

  // Cmd/Ctrl+A selects every LOADED grid item — unless the user is typing in a
  // text field (where it should select the field's text as usual). With
  // windowed pages "loaded" may be less than the whole view; the note says so.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Not while the item window is over us (see `itemWindowIsOpen`).
      // Nothing over the page may be typed THROUGH: with a dialog open,
      // Delete used to trash the selection behind it.
      if (modalIsOpen()) return;
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "a") return;
      if (isTypingTarget(e)) return;
      e.preventDefault();
      setSelectedItems(loadedIds);
      // Select-all names every loaded occurrence, so every copy is primary.
      if (sequenceView != null) {
        setSelMembers(new Set(loadedItems
          .map((it) => it.member_id)
          .filter((m): m is number => m != null)));
      }
      if (total > loadedIds.length) {
        setSelNote(t("Selected the {n} loaded items of {total} in this view.", {
          n: num(loadedIds.length),
          total: num(total),
        }));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // `t` is a fresh closure every render and the listener would re-subscribe on
    // every marquee frame with it in the deps; the strings it produces here
    // only matter at keypress time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedIds, loadedItems, total, setSelectedItems, sequenceView]);

  // ---- breadcrumb ----
  const KIND_LABEL: Record<string, string> = { image: "Images", video: "Videos", sequence: "Sequences" };
  const scopeAllItems = selectedGroups.length === 0 && !ungrouped && !untagged && !trashView && !hiddenView && !pendingView && sequenceView == null && rankingView == null && !rankedView;
  const onlyKind = mediaKinds.length === 1 ? mediaKinds[0] : null;
  // A sequence view is always shown in the sequence's own order, so sorting
  // off — and a RANKING view for the same reason: its order IS the ranking,
  // which is the whole of what the view is for.
  // ...but NOT the set-aside pictures: they have no standing, so that view
  // sorts and groups like any other.
  const sortDisabled = sequenceView != null
    || (rankingView != null && !rankingDismissed);
  // A sort with only ONE legal coarsening has nothing to offer: the dropdown
  // could only be set to what it already is. That is the shuffle, whose
  // sections would hold whatever it happened to put next to each other.
  // ...but a ranking view still GROUPS, by the standings' own buckets: a
  // bucket is a contiguous run of that order, which is the one rule a
  // grouping has to satisfy. So the group control is asked about the ranking
  // rather than about the (disabled) sort.
  const groupDisabled = rankingView != null && !rankingDismissed
    ? false
    : sortDisabled || groupOptionsFor(sortField).length < 2;
  // Segments after the "All Items" (or "Trash") root. A `kind` crumb re-applies a
  // media-kind filter on click; a group crumb navigates to that group.
  type Crumb = { id: number; name: string; clickable: boolean; kind?: string; onClick?: () => void };
  // WHICH ROOT THE CRUMB BAR STARTS FROM: a ranking's own view and the index
  // above it both hang off Rankings, not off All Items.
  const rankedRoot = rankedView || rankingView != null;
  const crumbs: Crumb[] = (() => {
    if (sequenceView != null) {
      const seq = allSequences?.find((s) => s.id === sequenceView);
      const name = openSequence?.name ?? seq?.name ?? "Sequence";
      return [
        { id: -5, name: "Sequences", clickable: true, kind: "sequence" },
        { id: -4, name, clickable: false },
      ];
    }
    if (trashView) return []; // "Trash" is the root crumb itself
    if (hiddenView) return []; // "Hidden" is the root crumb itself
    if (rankingView != null) {
      // MIRRORS THE NESTING, the way Pending's does — a ranking hangs off a
      // row above it in the sidebar, so "Rankings › Quality › Portraits".
      // Not a root of its own like Trash and Hidden: those ARE the top of
      // what they show.
      const rk = rankingRows?.find((r) => r.id === rankingView);
      const lg = rankingPool != null
        ? rk?.pools?.find((l) => l.id === rankingPool) : null;
      // The ranking's own row leads back to its placed pictures.
      const out: Crumb[] = [
        // "Rankings" is the ROOT here, not a crumb — a ranking is its own
        // place rather than a way of looking at All Items.
        { id: -11, name: rk?.name ?? "Ranking", clickable: lg != null,
          onClick: lg != null ? () => showRanking(rankingView) : undefined },
      ];
      if (lg) out.push({ id: -12, name: lg.name || "Default", clickable: false });
      if (rankingDismissed) {
        out[0].clickable = true;
        out[0].onClick = () => showRanking(rankingView);
        out.push({ id: -13, name: "Not applicable", clickable: false });
      }
      return out;
    }
    // THE INDEX ITSELF IS THE ROOT (see the crumb bar below), so there is
    // nothing under it to name.
    if (rankedView) return [];
    if (pendingView) {
      // Pending lives under All Items: "All Items › Pending [› Tags/Captions/Faces]".
      return pendingKind
        ? [
            { id: -8, name: "Pending", clickable: true, onClick: () => showPending() },
            { id: -7, name: pendingKind === "tags" ? "Tags"
              : pendingKind === "faces" ? "Faces" : "Captions", clickable: false },
          ]
        : [{ id: -8, name: "Pending", clickable: false }];
    }
    if (ungrouped) return [{ id: -2, name: "Ungrouped", clickable: false }];
    if (untagged) return [{ id: -3, name: "Untagged", clickable: false }];
    if (scopeAllItems && onlyKind) {
      return [{ id: -6, name: KIND_LABEL[onlyKind], clickable: false }];
    }
    if (selectedGroups.length === 1 && allGroups) {
      const path = findGroupPath(allGroups, selectedGroups[0]);
      if (path) return path.map((n) => ({ id: n.id, name: n.name, clickable: true }));
    }
    if (selectedGroups.length > 1) {
      return [{ id: -1, name: `${selectedGroups.length} groups selected`, clickable: false }];
    }
    return [];
  })();

  // The moving end of a keyboard (arrow-key) selection. The fixed end is the
  // store's `anchorItem`; this tracks where the cursor currently sits so
  // successive Shift+Arrow presses extend from the last cursor, not the anchor.
  const cursorRef = useRef<number | null>(null);
  // WHICH CARD THAT IS — the flat index, because in a SEQUENCE VIEW the item
  // id does not say: the grid draws a repeated page once per position and
  // `indexOfId` answers with whichever copy was written to the map last. A
  // blank page at positions 2 and 30 therefore stepped 2 → 31, the card after
  // its OTHER appearance. The index is checked against the id before it is
  // believed, so a view that moved underneath falls back to the lookup.
  const cursorIdxRef = useRef<number | null>(null);

  /** WHICH CARD a walk through the view is on, in flat indices.
   *
   *  Three answers, in the order that can tell two copies of one page apart:
   *  the remembered card while it still holds that item; the OCCURRENCE the
   *  selection names (`selMembers`), which is how a step taken in the
   *  preview is carried on from here; and last the id's own lookup, exact
   *  everywhere but a sequence view. */
  const cursorIdx = (id: number | null | undefined): number => {
    const at = cursorIdxRef.current;
    if (id != null && at != null && getIdAt(at) === id) return at;
    if (sequenceView != null && selMembers.size === 1) {
      const m = indexOfMember([...selMembers][0]);
      if (m !== -1 && (id == null || getIdAt(m) === id)) return m;
    }
    return id != null ? indexOfId(id) : -1;
  };

  // Reset scroll to the top whenever the underlying query changes.
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    // `groupBy` is in here because turning grouping on or off changes the
    // content height by every header and gap at once, so the same offset
    // lands in a different section. It also puts the one reflow the
    // ungrouped fallback costs at the top, where nothing can see it.
  }, [selectedGroups, ungrouped, untagged, trashView, hiddenView, sequenceView,
      search, groupBy]);

  // A runs REFETCH — an import finished, a selection was trashed — moves every
  // section below the first changed one, and the preserved scrollTop then
  // points somewhere arbitrary. Remember where the current section's header
  // sat relative to the scroll and put it back. Keyed on `columns` too: a
  // column change re-rounds EVERY section's row count, and those roundings do
  // not cancel the way one flat `ceil(total/columns)` does.
  const anchorRef = useRef<{ key: string; delta: number } | null>(null);
  // Captured while SCROLLING, not while rendering: by the render that rebuilds
  // the layout the old sections are already gone, so an anchor taken there
  // would describe the new positions and restore nothing.
  const rememberAnchorRef = useRef<(top: number) => void>(() => {});
  const rememberAnchor = (top: number) => {
    if (!layout || !gwin || gwin.currentSection < 0) { anchorRef.current = null; return; }
    const s = layout.sections[gwin.currentSection];
    if (s) anchorRef.current = { key: s.key, delta: top - s.headerTop };
  };
  rememberAnchorRef.current = rememberAnchor;
  useEffect(() => {
    const el = scrollRef.current;
    const a = anchorRef.current;
    if (!el || !a || !layout) return;
    const s = layout.sections.find((x) => x.key === a.key);
    if (!s) return;
    const want = Math.max(0, s.headerTop + a.delta);
    if (Math.abs(want - toVirt(el.scrollTop)) < 1) return;
    el.scrollTop = toPhys(want);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runsView.runs, columns]);

  // (No "fetch next page near the end" effect anymore: the visible index range
  // handed to useItemView is what drives fetching.)

  // Arrow-key selection when the grid is focused. Left/Right step by one within
  // the flat order (wrapping across rows); Up/Down move by a full row. Holding
  // Shift extends the selection from the anchor instead of replacing it. The
  // cursor is kept scrolled into view.
  // Scroll the grid so the card at flat index `i` is within the viewport.
  const scrollRowIntoView = (i: number) => {
    const scEl = scrollRef.current;
    if (!scEl || columns < 1) return;
    // Grouped, a card's y comes from its SECTION — `PAD + row * rowStride`
    // stops being true the moment there is a header above it.
    const box = layout ? cardBox(layout, i) : null;
    const top = box ? box.top : PAD + Math.floor(i / columns) * rowStride;
    const bottom = top + cardH;
    const virtTop = toVirt(scEl.scrollTop);
    if (top < virtTop) scEl.scrollTop = toPhys(top - PAD);
    else if (bottom > virtTop + scEl.clientHeight)
      scEl.scrollTop = toPhys(bottom - scEl.clientHeight + PAD);
  };

  /**
   * BRINGING A BOOKMARK INTO VIEW. The store has put its scope back and
   * selected the picture; the row it is on is the grid's half of the answer,
   * and usually not one the grid knows — the loaded pages are the ones near
   * the viewport, and the mark is somewhere else. So: the pages first (free,
   * and the common case for a mark in the view you are already in), then the
   * server, which is the only thing that can say where an item sits in an
   * order it did not draw.
   *
   * It waits for the view to be READY: the scope change re-queries, and a
   * scroll computed against the old total would land nowhere. Cleared
   * whatever the answer is, including "this view does not hold it" — an
   * unanswered request that stayed armed would fire again on the next
   * layout change.
   */
  useEffect(() => {
    if (scrollToItem == null || !view.ready || columns < 1) return;
    let alive = true;
    const at = view.indexOfId(scrollToItem);
    if (at >= 0) {
      scrollRowIntoView(at);
      clearScrollToItem();
      return;
    }
    void api.itemIndexes(viewReq, [scrollToItem])
      .then((got) => {
        if (!alive) return;
        const idx = got.indices[0];
        if (idx != null) scrollRowIntoView(idx);
      })
      .catch(() => { /* no answer is no scroll */ })
      .finally(() => { if (alive) clearScrollToItem(); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollToItem, view.ready, columns, layout]);

  // THE ONE ORDINARY GROUP THE VIEW IS SCOPED TO, or null. The Delete key
  // and the context menu's "Remove from …" row both ask this, so the two
  // cannot disagree about when taking a picture out of a group is a thing
  // to offer. Null for every special scope — All items, Ungrouped,
  // Untagged, Trash, Hidden, a ranking all pick no group at all — and for
  // a smart group, whose membership is a rule rather than an answer.
  const scopeGroup = useMemo(() => {
    if (selectedGroups.length !== 1 || !allGroups) return null;
    const path = findGroupPath(allGroups, selectedGroups[0]);
    const g = path?.[path.length - 1];
    return g && !g.smart ? g : null;
  }, [selectedGroups, allGroups]);

  const removeFromGroup = async (ids: number[], groupId: number, name: string) => {
    if (!ids.length) return;
    if (!(await confirm({
      title: tn({ one: "Remove this item from “{group}”?",
                  other: "Remove {n} items from “{group}”?" }, ids.length, { group: name }),
      body: t("They stay in the library and in every other group."),
      answer: { label: t("Remove") },
    }))) return;
    await api.bulkGroupMembership(ids, [], [groupId]);
    // The pictures leave THIS view, so they leave the selection with it —
    // the ids, not the whole selection: from the context menu the targets
    // can be one unselected card, and clearing everything would be the
    // menu answering for pictures it was not opened on.
    setSelectedItems(useUI.getState().selectedItems.filter((id) => !ids.includes(id)));
    // ONE sweep: `bumpEdits` already covers "items" and "groups", and the
    // two explicit invalidations beside it were a second round of the same
    // page fetches.
    ctxInvalidate(ids);
  };
  const onGridKeyDown = (e: React.KeyboardEvent) => {
    // ESCAPE CLEARS THE SELECTION when nothing above the page has the key —
    // every list here does it (`useEscapeClears`), and the grid is a list.
    if (e.key === "Escape") {
      if (useUI.getState().quickLook || modalIsOpen() || escapeDepth() > 0) return;
      if (isTypingTarget(e) || selectedItems.length === 0) return;
      e.preventDefault();
      setSelectedItems([]);
      return;
    }
    // DELETE OVER A GROUP'S VIEW ASKS TO TAKE THE PICTURES OUT OF IT (owner
    // 2026-09): with one group picked in the sidebar and items picked in
    // the grid, the key means "not in here" rather than "gone", and it
    // asks first. Nothing else: a smart group's members are a rule, and
    // outside a group's view the key has no answer it could mean.
    if (e.key === "Delete" || e.key === "Backspace") {
      if (useUI.getState().quickLook || modalIsOpen() || isTypingTarget(e)) return;
      const ids = useUI.getState().selectedItems;
      if (!ids.length || !scopeGroup) return;
      e.preventDefault();
      void removeFromGroup(ids, scopeGroup.id, scopeGroup.name);
      return;
    }
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
    // While the QuickLook overlay is open it owns the arrow keys (it steps the
    // preview / selection itself), so the grid must not also react. Same for
    // anything else over the page — the rating session, whose arrows are the
    // judgment, but equally the tag batch's digits and a dialog's fields:
    // the grid scroller keeps the FOCUS while they are up, so this handler
    // fires too and every ←/→ silently moved the selection under the dim.
    if (useUI.getState().quickLook || modalIsOpen()) return;
    if (isTypingTarget(e)) return;
    if (total === 0) return;
    e.preventDefault();
    // Index space covers the whole view; the id lookups only answer for loaded
    // pages. A step onto an unloaded index scrolls there (which loads it) and
    // leaves the selection alone until the next press.
    const curId = cursorRef.current ?? anchorItem ??
      (selectedItems.length ? selectedItems[selectedItems.length - 1] : getIdAt(0));
    let cur = cursorIdx(curId);
    if (cur === -1) cur = 0;
    // Grouped, `cur ± columns` is wrong rather than merely imprecise: a
    // section's startIdx is generally not a multiple of `columns`, so the
    // cursor slides sideways at every boundary and never round-trips.
    const dir = e.key === "ArrowRight" ? "right" : e.key === "ArrowLeft"
      ? "left" : e.key === "ArrowDown" ? "down" : "up";
    let next = cur;
    if (layout) next = stepIndex(layout, cur, dir);
    else if (dir === "right") next = Math.min(cur + 1, total - 1);
    else if (dir === "left") next = Math.max(cur - 1, 0);
    else if (dir === "down") next = Math.min(cur + columns, total - 1);
    else next = Math.max(cur - columns, 0);
    const nextId = getIdAt(next);
    scrollRowIntoView(next);
    if (nextId == null) return; // page not loaded yet — scrolled it into reach
    cursorRef.current = nextId;
    cursorIdxRef.current = next;
    // Shift extends from the store anchor; a plain arrow selects one and
    // resets it. BETWEEN TWO POSITIONS, the way a shift+click's range is —
    // an id lookup would take the range to the wrong copy of a repeated
    // page, and the occurrences the ring names (below) would then cover a
    // different stretch to the items selected.
    const from = e.shiftKey ? anchorIndex() : null;
    if (from != null) {
      void selectRange(from, next);
    } else if (selectedItems.length === 1 && selectedItems[0] === nextId
               && !e.shiftKey) {
      // The step landed on ANOTHER CARD OF THE SAME ITEM — a repeated page.
      // `selectItem` reads that as the click on the only picked card, which
      // is the way back out of a selection, and would let it go under an
      // arrow key. What moved is the card, not the selection.
    } else {
      selectItem(nextId, { meta: false, shift: e.shiftKey }, loadedIds);
    }
    if (sequenceView != null) {
      if (e.shiftKey && memberAnchorIdx.current != null) {
        setSelMembers(new Set(membersInRange(memberAnchorIdx.current, next)));
      } else {
        const m = getItem(next)?.member_id;
        if (m != null) {
          setSelMembers(new Set([m]));
          memberAnchorIdx.current = next;
        }
      }
    }
  };

  // When QuickLook steps the (single) grid selection while open, keep that item
  // scrolled into view so it's visible once the overlay closes.
  useEffect(() => {
    if (!useUI.getState().quickLook || selectedItems.length !== 1) return;
    // Through `cursorIdx`, so a repeated page scrolls to the copy the
    // preview actually stepped onto rather than to another of its cards.
    const idx = cursorIdx(selectedItems[0]);
    if (idx >= 0) scrollRowIntoView(idx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedItems]);

  // Land on a section and flash its header once.
  //
  // Deliberately NOT the tag list's triple re-aim (`TagsView.jumpToRow`):
  // that exists because tag rows measure themselves and their heights are not
  // known at jump time. Here `headerTop` comes straight from `groupLayout`
  // and depends on nothing that measures itself, so one assignment is right
  // and re-aiming would only fight the user's own scrolling.
  const jumpToGroup = (key: string) => {
    const el = scrollRef.current;
    const s = layout?.sections.find((x) => x.key === key);
    if (!el || !s) return;
    el.scrollTop = toPhys(Math.max(0, s.headerTop - PAD));
    // Off and on across a frame, or a second jump to the same section would
    // not restart the animation.
    setFlashKey(null);
    requestAnimationFrame(() => setFlashKey(key));
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlashKey(null), 1800);
  };
  useEffect(() => () => window.clearTimeout(flashTimer.current), []);

  // A window assembled while an external writer shifts the order can hold the
  // SAME item on two pages (offset pagination: a stale page and a fresh one
  // overlap until the rev-mismatch resync heals them). Rendered both, they are
  // two children with ONE React key — and duplicate keys corrupt
  // reconciliation: updates patch the wrong fiber, which is how a card came to
  // wear the selection ring over another item's thumbnail and name. So each
  // key renders ONCE per pass and any later slot claiming it is a placeholder
  // — the geometry holds, the resync replaces it with the true occupant
  // moments later, and the ring can only ever sit on the item it means.
  // Keyed on the OCCURRENCE key (member_id ?? id), because a sequence view's
  // repeated member is legitimately several cards of one item.
  const renderedCardKeys = new Set<number>();
  const cardAt = (idx: number) => {
    const it = getItem(idx);
    if (!it) return <PlaceholderCard key={`ph-${idx}`} cellW={cellW} />;
    const k = it.member_id ?? it.id;
    if (renderedCardKeys.has(k))
      return <PlaceholderCard key={`dup-${idx}`} cellW={cellW} />;
    renderedCardKeys.add(k);
    return renderCard(it, idx);
  };

  // ONE definition of a card, shared by the grouped and ungrouped branches:
  // the two differ only in how they place blocks, and a second copy of ~90
  // lines of handlers is a second place for a click to behave differently.
  const bookmarked = useMemo(() => new Set(bookmarks), [bookmarks]);
  const renderCard = (it: ItemOut, idx: number) => (
              <ItemCard
                // The OCCURRENCE, inside a sequence view: a book's repeated
                // blank page is several cards of one item, so the item id is
                // not a key there (React would see one card and drop the
                // rest). It stays the key everywhere else, where a card IS
                // an item. Selection is deliberately still by item id — one
                // copy picked lights them all, because they are one picture
                // and whatever you do next happens to it once; which copy the
                // gesture NAMED is tracked separately (`selMembers`) and only
                // decides which ring each copy wears.
                key={it.member_id ?? it.id}
                item={it}
                cellW={cellW}
                selected={selectedSet.has(it.id)}
                secondary={
                  it.member_id != null && memberTracked != null &&
                  memberTracked.has(it.id) && !selMembers.has(it.member_id)
                }
                dropSide={
                  dropMark != null && it.member_id === dropMark.member
                    ? (dropMark.after ? "after" : "before")
                    : null
                }
                pointed={pointedItemIds.includes(it.id)}
                bookmarked={bookmarked.has(it.id)}
                // A ROW IN THE SIDEBAR IS ABOUT THIS CARD. Every tag
                // currently selected in the sidebar's tag list, *with the
                // same sign* — counting group-inherited tags too (eff_tags /
                // eff_neg), not just direct — or every GROUP picked in its
                // Groups list, which is DIRECT membership because that is
                // what those rows say (a group's subtree is the tree's own
                // claim). Both are the same question, so both draw the same
                // ring; ALL of them, like the tags, so a second pick narrows
                // rather than widens.
                rowMatch={
                  (tagHighlight.length > 0 &&
                   tagHighlight.every((t) =>
                     (t.negative ? it.eff_neg : it.eff_tags).includes(t.name)
                   ))
                  || (groupHighlight.length > 0 &&
                      groupHighlight.every((g) => (it.group_ids ?? []).includes(g)))
                }
                // The tick shows whenever there IS a set and the item carries
                // it — "which of these already have it" is the question the
                // set poses, and it was only answerable from inside the
                // click-to-assign mode. Clicking it takes the set off in
                // either mode: the toggle decides what a click on the
                // PICTURE does, not whether the answer can be undone.
                qaAssigned={
                  qaActive && itemHasAllQaTags(it.direct_tags, qaPos, qaNeg,
                                               qaGroups, it.group_ids ?? [])
                }
                onClick={(e) => {
                  e.stopPropagation();
                  // A press that turned into a box-drag emits a trailing click; ignore it.
                  if (dragMovedRef.current) {
                    dragMovedRef.current = false;
                    return;
                  }
                  // In Quick-Assign mode a click stamps the tags instead of
                  // selecting — but only while there's actually a set to stamp;
                  // with no tags the mode is inert and a click selects as usual.
                  if (qaMode && qaActive) {
                    runQuick(it.id, false);
                    return;
                  }
                  void clickSelect(it.id, idx, e.shiftKey,
                                   e.metaKey || e.ctrlKey);
                  // Track the OCCURRENCE the gesture named (sequence view):
                  // a shift range covers the occurrences between the member
                  // anchor and this card, mirroring what the range looks like.
                  if (sequenceView != null && it.member_id != null) {
                    const m = it.member_id;
                    if (e.shiftKey && memberAnchorIdx.current != null) {
                      setSelMembers(
                        new Set(membersInRange(memberAnchorIdx.current, idx)));
                    } else if (e.metaKey || e.ctrlKey) {
                      // The store setter takes a value, not an updater — the
                      // click is a discrete event, so the read is current.
                      const s = new Set(selMembers);
                      if (s.has(m)) s.delete(m); else s.add(m);
                      setSelMembers(s);
                      memberAnchorIdx.current = idx;
                    } else {
                      setSelMembers(new Set([m]));
                      memberAnchorIdx.current = idx;
                    }
                  }
                }}
                onDoubleClickCard={() => {
                  // Sequences always open in the grid. Images/videos follow the
                  // configurable General → double-click preferences.
                  if (it.kind === "sequence" && it.sequence_id != null) {
                    showSequence(it.sequence_id);
                    return;
                  }
                  const pref = it.kind === "image"
                    ? (settings?.dblclick_image ?? "quicklook")
                    : (settings?.dblclick_video ?? "quicklook");
                  if (pref === "quicklook") {
                    // Show the double-clicked item on its own in Quick Look.
                    setSelectedItems([it.id]);
                    if (it.member_id != null) setSelMembers(new Set([it.member_id]));
                    setQuickLook(true);
                  } else if (pref === "annotate") {
                    openAnnotator(it.id);
                  } else if (pref === "editor") {
                    openEditor(it.id);
                  }
                }}
                onQaRemove={() => runQuick(it.id, true)}
                onContextMenuCard={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  // CTRL+LEFT-CLICK IS A SELECTION TOGGLE, NOT A MENU. On
                  // macOS ctrl+click IS the secondary click, so the toggle
                  // every other platform gets from ctrl never happened here
                  // — the card opened its menu instead. `button === 0` is
                  // exactly the discriminator: a real right-click is 2, and
                  // on Windows a ctrl+LEFT-click never reaches this handler
                  // at all, so nothing there changes.
                  if (e.ctrlKey && e.button === 0) {
                    void clickSelect(it.id, idx, e.shiftKey, true);
                    return;
                  }
                  const ids = selectedSet.has(it.id) && selectedItems.length > 0
                    ? [...selectedItems]
                    : [it.id];
                  setCtxMenu({ x: e.clientX, y: e.clientY, ids, clickedId: it.id });
                }}
                onDragStartCard={(e) => {
                  // Drag the whole selection if this card is part of it, else
                  // just this one image. Group rows read this payload on drop.
                  const ids =
                    selectedSet.has(it.id) && selectedItems.length > 0
                      ? selectedItems
                      : [it.id];
                  e.dataTransfer.setData("application/x-mc-items", JSON.stringify(ids));
                  e.dataTransfer.effectAllowed = "copy";
                  // Inside a sequence the same drag can also REORDER: remember
                  // the occurrence being carried, so a drop on another card
                  // moves this copy (a drop on a group row still assigns).
                  reorderMember.current =
                    sequenceView != null ? it.member_id ?? null : null;
                  // Share the dragged ids so drop targets (e.g. the Links section)
                  // can validate the drag before the drop.
                  setDraggedItems(ids);
                  // Rounded (stacked, for multi-select) drag preview. Keep the
                  // dragged card first so its thumbnail is the one on top.
                  const ghost = buildDragGhost(
                    [it.id, ...ids.filter((x) => x !== it.id)]
                      .map((id) => itemById.get(id))
                      .filter((x): x is NonNullable<typeof x> => x != null),
                    { x: e.clientX, y: e.clientY });
                  if (ghost) {
                    document.body.appendChild(ghost);
                    e.dataTransfer.setDragImage(ghost, GHOST_HOTSPOT, GHOST_HOTSPOT);
                    setTimeout(() => ghost.remove(), 0);
                  }
                }}
                onDragOverCard={(e) => {
                  if (reorderMember.current == null || it.member_id == null) return;
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "move";
                  const r = e.currentTarget.getBoundingClientRect();
                  const after = e.clientX - r.left > r.width / 2;
                  setDropMark((prev) =>
                    prev != null && prev.member === it.member_id && prev.after === after
                      ? prev
                      : { member: it.member_id as number, after });
                }}
                onDropCard={(e) => {
                  if (reorderMember.current == null || it.member_id == null) return;
                  e.preventDefault();
                  const r = e.currentTarget.getBoundingClientRect();
                  const after = e.clientX - r.left > r.width / 2;
                  void reorderTo(it.member_id, after);
                }}
                // dragend fires on the SOURCE card however the drag ends —
                // dropped elsewhere, cancelled, or completed — so it is the
                // one reliable place to put the marker down.
                onDragEndCard={() => {
                  reorderMember.current = null;
                  setDropMark(null);
                }}
              />
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0, background: "var(--bg)", position: "relative" }}>
      {/* The picture, large, while a caption for it is being typed in the
          sidebar. Over the WHOLE column rather than only the scroll area: the
          grid is what a caption is being written instead of looking at, and
          leaving the toolbar visible under it would say the header is still
          for using. `pointerEvents: none` throughout — this is a thing to
          look at while the hands are in the sidebar, and a click on it must
          fall through to the grid it is covering rather than selecting
          whatever happens to be underneath. */}
      <CaptionPreview />
      {/* breadcrumb + search + toolbar */}
      <div style={{ flex: "0 0 auto", borderBottom: "1px solid var(--border-soft)" }}>
        <div style={{ height: 44, display: "flex", alignItems: "center", gap: 10, padding: "0 16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5, color: "var(--text-3)", fontSize: "var(--fs-3)", overflow: "hidden", minWidth: 0 }}>
            {/* THE ROOT IS WHAT THE VIEW HANGS OFF, and RANKINGS is one of
                those — a ranking is not a way of looking at All Items, it is
                its own place, the way the Trash and Hidden are. It stays
                pressable there (unlike those two): it leads back to the
                index of rankings, which is a view of its own. */}
            <span
              onClick={() => (trashView || hiddenView ? undefined
                : rankedRoot ? showRanked() : showAllItems())}
              style={{
                display: "flex", alignItems: "center", gap: 5,
                cursor: trashView || hiddenView ? "default" : "pointer",
                color: crumbs.length ? "var(--muted)" : "var(--text)",
                fontWeight: crumbs.length ? 400 : 600, flex: "0 0 auto",
              }}
            >
              <Icon
                name={hiddenView ? "visibility_off" : trashView ? "delete"
                  : rankedRoot ? "leaderboard" : "inbox"}
                size={16}
                color="var(--muted-2)"
              />
              {hiddenView ? t("Hidden") : trashView ? t("Trash")
                : rankedRoot ? t("Rankings") : t("All Items")}
            </span>
            {crumbs.map((c, i) => {
              const last = i === crumbs.length - 1;
              return (
                <React.Fragment key={`${c.id}-${i}`}>
                  <Icon name="chevron_right" size={15} color="var(--muted-3)" />
                  <span
                    onClick={
                      !c.clickable ? undefined
                        : c.onClick ? c.onClick
                        : c.kind ? () => showKind(c.kind as import("../store").Kind)
                        : () => selectGroup(c.id, false)
                    }
                    style={{
                      cursor: c.clickable ? "pointer" : "default",
                      color: last ? "var(--text)" : "var(--muted)",
                      fontWeight: last ? 600 : 400,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}
                  >
                    {c.name}
                  </span>
                </React.Fragment>
              );
            })}
          </div>
          <div style={{ flex: 1 }} />
          {/* Download the whole current view as ZIP archives (built in the
              browser — see GridExport). */}
          {view.ready && total > 0 && !rankedView && (
            <GridExportButton items={loadedItems} total={total} iterate={view.iterate} />
          )}
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
            {/* THE INDEX COUNTS RANKINGS, because that is what it shows. */}
            {rankedView
              ? tn({ one: "1 ranking", other: "{n} rankings" },
                   (rankingRows ?? []).length)
              : view.ready
                ? tn({ one: "1 item", other: "{n} items" }, total) : "…"}
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "0 16px 12px", position: "relative" }}>
          {/* The Finder-style predicate builder — replaces the old search field,
              Filters button, range sliders and condition tokens. */}
          <QueryBuilder search={search} setSearch={setSearch} announceFiltering />

          {/* Controls row: sort, filters, grid size — below the search field.
              Wraps to a second line rather than overflowing into the right
              sidebar when the window is narrow. */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", rowGap: 8, minWidth: 0 }}>
          {/* ONE control for the order: which field, and which way. They were
              a dropdown and a button beside it, which is two controls for one
              question and — worse — one shared direction, so every switch of
              field was a second click to put the arrow back. The direction is
              remembered PER field now (`sortDirs`), the arrow rides on the
              button, and picking the field already selected flips it.

              Disabled in a sequence view, which is always shown in the
              sequence's own order. */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, opacity: sortDisabled ? 0.5 : 1 }}>
            <SortMenu
              field={sortField}
              dir={sortDir}
              dirs={sortDirs}
              disabled={sortDisabled}
              fixedLabel={rankingView != null ? t("Ranking order")
                                              : t("Sequence order")}
              onPick={(f: SortField) => {
                if (f === sortField) toggleSortDir(); else setSortField(f);
              }}
              t={t}
            />
            {/* The DICE is not a direction, so it does not belong inside the
                control above — it deals a new shuffle, which is the one thing
                a random order has to offer, and it exists only while there is
                one. */}
            {!sortDisabled && sortField === "random" && (
              <IconButton icon="casino" size={34} glyph={18} tone="text" bordered fill="panel"
                onClick={shuffle}
                title={t("Shuffle again")} />
            )}
          </div>

          {/* GROUP BY — always a coarsening of the sort above it, which is
              what lets the backend prepend it to the same ORDER BY and so
              make every section a contiguous run of the page order. Its
              options therefore follow the sort, and `setSortField` normalizes
              the pair rather than letting an impossible one reach the API. */}
          <div style={{ display: "flex", alignItems: "center", gap: 6,
                        opacity: groupDisabled ? 0.5 : 1 }}>
              <Select
                value={effGroupBy}
                disabled={groupDisabled}
                onChange={(v) => setGroupBy(v as GroupBy)}
                title={rankingView != null ? t("Group by")
                  : sortDisabled ? t("Sorted by sequence order")
                  : groupDisabled ? t("A shuffle has no sections")
                  : t("Group by")}
                height={34} minWidth={0}
                leading={<Icon name="view_agenda" size={17}
                               style={{ position: "absolute", left: 10, color: "var(--muted-2)",
                                        pointerEvents: "none" }} />}
                style={{
                  padding: "0 28px 0 32px", borderRadius: "var(--r-5)",
                  background: effGroupBy !== "none" ? "var(--accent-dim)" : "var(--panel-2)",
                  color: "var(--text-3)", fontSize: "var(--fs-3)",
                }}
              >
                {/* A RANKING VIEW STILL GROUPS, though its sort stands
                    down: the sections are the standings' own buckets, which
                    is the one coarsening that means anything over that
                    order. So the options are asked of the RANKING and not of
                    the (disabled) sort. */}
                {rankingView != null ? (
                  groupOptionsFor("recent", true).map((g) => (
                    <option key={g} value={g}>{t(GROUP_LABELS[g])}</option>
                  ))
                ) : sortDisabled ? (
                  <option>{t("Sequence order")}</option>
                ) : (
                  groupOptionsFor(sortField).map((g) => (
                    <option key={g} value={g}>{t(GROUP_LABELS[g])}</option>
                  ))
                )}
              </Select>
            {/* Jump to a section. Only once there is something to jump to —
                a button that opens an empty list is a button that does
                nothing. */}
            {effGroupBy !== "none" && layout && layout.sections.length > 1 && (
              <div style={{ position: "relative" }}>
                <IconButton icon="low_priority" size={34} glyph={18} tone="text" bordered active={jumpOpen}
                  ref={jumpBtn}
                  onClick={() => setJumpOpen((v) => !v)}
                  title={t("Jump to")} />
                {jumpOpen && (
                  <JumpMenu
                    groupBy={effGroupBy}
                    runs={runsView.runs}
                    lang={lang}
                    t={t}
                    rect={jumpRect}
                    onPick={(key) => { setJumpOpen(false); jumpToGroup(key); }}
                  />
                )}
              </div>
            )}
          </div>

          {/* THE BOOKMARKS — beside the order controls, because that is what
              they are about: not what the view holds, but a place in it
              somebody marked. Icon only, and only while there is one to
              show: a control that opens an empty list is a control that
              does nothing. */}
          {bookmarks.length > 0 && (
            <div style={{ position: "relative" }}>
              {/* A DROPDOWN SAYS SO. The recipe is `iconButtonStyle`'s —
                  the sanctioned way for a menu to draw its own trigger —
                  with the chevron every other menu button here carries. */}
              <button
                ref={marksBtn}
                onClick={() => setMarksOpen((v) => !v)}
                title={t("Bookmarks")}
                style={{
                  ...iconButtonStyle({ size: 34, bordered: true, fill: "panel",
                                       tone: "text", active: marksOpen }),
                  width: "auto", gap: 4, padding: "0 8px",
                }}
              >
                <Icon name="bookmarks" size={18} />
                <Chevron />
              </button>
              {marksOpen && (
                <BookmarksMenu
                  rect={marksRect}
                  bookmarks={bookmarks}
                  req={viewReq}
                  t={t}
                  onPick={(id) => { setMarksOpen(false); goToBookmark(id); }}
                  onRemove={(id) => removeBookmark(id)}
                />
              )}
            </div>
          )}

          {/* Flexible gap: sort stays left, media + filters + size push right. */}
          <div style={{ flex: 1 }} />

          {/* The keyboard actions (T / Q / R), findable with a mouse. */}
          <QuickActionsMenu t={t} onRemoveWatermarks={() => void removeWatermarks()}
            lastAction={lastAction} lastAvailable={lastOffered != null}
            onRepeatLast={() => void repeatLast()} />

          {/* Media-kind multi-select dropdown (images / videos / sequences),
              plus the "hide sequenced" and "show hidden" grid toggles. */}
          <MediaKindMenu
            selected={mediaKinds}
            onToggle={(k) => toggleMediaKind(k)}
            title={t("Filter by media kind")}
            extra={[
              { label: "Fold sequences", on: foldSequenced, toggle: toggleFoldSequenced, icon: "layers" },
              { label: "Show hidden", on: showHiddenItems, toggle: toggleShowHiddenItems, icon: "visibility" },
            ]}
          />

          {/* Grid size: S / M / L — `GridSizeControl`, the same control the
              Faces grid has, so the two cannot drift into two shapes. */}
          <GridSizeControl size={gridSize} onSize={setGridSize} t={t} />
          </div>
        </div>

      </div>

      {/* grid (infinite scroll + windowed) */}
      <div
        ref={scrollRef}
        tabIndex={0}
        onKeyDown={onGridKeyDown}
        // Reserve the scrollbar gutter always, so switching to a view with few
        // items (e.g. Hidden) — where the vertical scrollbar disappears — doesn't
        // widen the track and resize/reflow every card (or push the last column
        // under the right sidebar).
        style={{ flex: 1, overflowY: "auto", minHeight: 0, position: "relative", userSelect: "none", outline: "none", scrollbarGutter: "stable" }}
      >
        {/* THE RANKINGS VIEW SHOWS RANKINGS, not their pictures — one
            card per ranking, the same rows the sidebar lists under that
            chevron. Everything below is about items and has nothing to
            draw here. */}
        {rankedView ? (
          <RankingsIndex columns={columns} cellW={cellW} />
        ) : (<>
        {view.error && (
          <Trouble message={t("The items could not be loaded.")}
                   detail={String(view.error.message)}
                   onRetry={view.refetch} retryLabel={t("Try again")} />
        )}
        {view.isLoading && <Loading label={t("Loading…")} />}
        {/* Nothing to show, and a way out of it. The two empty states have
            different causes and so different answers: with a query set, the
            likely mistake is the query, and the button clears it without
            hunting for the ✕ in a field full of text; with no query, the
            library simply has nothing here yet, and the answer is to import.
            The Trash and the sequences list say their piece and offer neither
            — clearing a query you did not set explains nothing. */}
        {!view.isLoading && total === 0 && (
          <EmptyState line={trashView
              ? t("Trash is empty.")
              : onlyKind === "sequence"
                ? t("No sequences yet. Import a comic archive or a video, or create one from a multi-selection.")
                : search.trim()
                  ? t("No items match this query.")
                  // A RANKING NOBODY HAS RATED ON is empty for a reason of
                  // its own, and "Nothing here yet" with a button offering
                  // to IMPORT FILES is the wrong answer to it — the pictures
                  // are already there; what is missing is the comparisons.
                  // The sentence is the one its own card says.
                  : rankingView != null
                    ? t("Nothing placed yet — compare a few pairs and they appear here, best first.")
                    : t("Nothing here yet.")}
            action={!trashView && onlyKind !== "sequence" && rankingView == null
              ? { label: search.trim() ? t("Clear the query") : t("Import files"),
                  icon: search.trim() ? "close" : "upload_file",
                  onClick: () => (search.trim() ? setSearch("") : setOverlay("import")) }
              : undefined} />
        )}
        {/* The geometry's wrapper: where a box may begin (it reaches the
            bottom of the scroller), and the coordinate space the box is
            measured in. */}
        <div ref={grid.wrapRef} onMouseDown={grid.onMouseDown}
             style={{ position: "relative", minHeight: grid.fillH }}>
        {/* THE PINNED CURRENT-SECTION PILL. A zero-height sticky wrapper, and
            the `height: 0` is the whole trick: it takes no flow space, so the
            spacer below keeps starting exactly where `groupLayout` says, while
            sticky still resolves against the scroller's own content box.
            Anything with real height added here shifts the spacer and silently
            offsets the marquee rect from the coordinates it is computed in. */}
        {layout && gwin && gwin.currentSection >= 0
          && !gwin.currentHeaderOnScreen && (
          <div style={{ position: "sticky", top: 0, height: 0, zIndex: 6,
                        pointerEvents: "none" }}>
            <div style={{
              position: "absolute", top: 8, left: PAD,
              display: "flex", alignItems: "center", gap: 7,
              padding: "4px 11px", borderRadius: "var(--r-round)",
              background: "var(--panel)", border: "1px solid var(--border)",
              boxShadow: "var(--shadow-1)",
              fontSize: "var(--fs-3)", color: "var(--text)", pointerEvents: "auto",
            }}>
              {(() => {
                const s = layout.sections[gwin.currentSection];
                const sw = groupSwatch(effGroupBy, s.key);
                return (<>
                  {sw && <span style={{
                    width: 10, height: 10, borderRadius: 3, background: sw,
                    border: "1px solid var(--border)", flex: "0 0 auto" }} />}
                  <span>{groupLabel(effGroupBy, s.key, lang, t)}</span>
                  <span style={{ opacity: 0.55 }}>{s.count}</span>
                </>);
              })()}
            </div>
          </div>
        )}
        <div style={{ height: physH, position: "relative" }}>
          {layout && gwin && gwin.slices.map((sl) => {
            const s = layout.sections[sl.section];
            const sw = groupSwatch(effGroupBy, s.key);
  return (
              <React.Fragment key={s.key}>
                {sl.header && (
                  // Outside the card grid, and a HARD height with overflow
                  // hidden: a header that could wrap would change the grid's
                  // implicit rows and desync rowStride from what is drawn.
                  <div
                    data-groupheader={s.key}
                    className={flashKey === s.key ? "mc-flash" : undefined}
                    style={{
                      position: "absolute", top: s.headerTop + yShift,
                      left: PAD, right: PAD,
                      height: HEADER_H, overflow: "hidden",
                      display: "flex", alignItems: "center", gap: 8,
                      borderRadius: "var(--r-2)",
                    }}
                  >
                    {sw && <span style={{
                      width: 12, height: 12, borderRadius: 3, background: sw,
                      border: "1px solid var(--border)", flex: "0 0 auto" }} />}
                    <span style={{ fontSize: "var(--fs-4)", fontWeight: 600,
                                   color: "var(--text)", whiteSpace: "nowrap",
                                   overflow: "hidden", textOverflow: "ellipsis" }}>
                      {groupLabel(effGroupBy, s.key, lang, t)}
                    </span>
                    <span style={{ fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
                      {s.count}
                    </span>
                    <span style={{ flex: 1, height: 1,
                                   background: "var(--border)" }} />
                  </div>
                )}
                {sl.endIdx > sl.startIdx && (
                  // ONE absolutely-positioned grid block PER SECTION. A single
                  // block for everything would flow the next section's first
                  // card into the previous section's partial last row.
                  <div style={{
                    position: "absolute", top: sl.offsetTop + yShift,
                    left: PAD, right: PAD,
                    display: "grid",
                    gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
                    gap: GAP, alignContent: "start",
                  }}>
                    {Array.from({ length: sl.endIdx - sl.startIdx }, (_, k) =>
                      cardAt(sl.startIdx + k))}
                  </div>
                )}
              </React.Fragment>
            );
          })}
          {!layout && (
          <div
            style={{
              position: "absolute", top: win.offsetTop + yShift,
              left: PAD, right: PAD,
              // minmax(0, 1fr) — NOT plain 1fr (= minmax(auto, 1fr)): the auto
              // minimum is each card's content min-width (the thumbnail's
              // intrinsic size), so a fully-populated row could exceed the track
              // and overflow the grid horizontally, clipping the last column
              // under the right sidebar. A 0 minimum lets every column shrink to
              // its equal share instead.
              display: "grid", gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
              gap: GAP, alignContent: "start",
            }}
          >
            {/* An index whose page hasn't loaded renders a placeholder of the
                EXACT card dimensions, so the geometry (marquee, windowing,
                scroll anchoring) holds while the page arrives. */}
            {Array.from({ length: Math.max(0, win.endIdx - win.startIdx) }, (_, k) =>
              cardAt(win.startIdx + k))}
          </div>
          )}
          {marquee && (
            <div
              style={{
                position: "absolute", left: marquee.left,
                top: marquee.top + yShift,
                width: marquee.width, height: marquee.height,
                background: "var(--accent-dim)", border: "1px solid var(--accent)",
                borderRadius: 2, pointerEvents: "none", zIndex: 5,
              }}
            />
          )}
          </div>{/* end of the geometry's wrapper — the spacer above closes next */}
          {ctxMenu && (() => {
            const targets = ctxTargets();
            const n = ctxMenu.ids.length;
            const allHidden = targets.length > 0 && targets.every((i) => i.hidden);
            void clipTick; // re-render dependency: paste rows enable after a copy
            // HOW MANY a copy of each kind would put on the clipboard —
            // `copyOne`'s own answer, so the number on the row and what the
            // row then copies cannot be two different things. A kind with
            // nothing to copy has no row at all: an action that would copy
            // nothing is worse than no action, since pressing it looks like
            // it worked. While the probe is in flight there are no counts and
            // so no rows; a SAMPLED probe (past 500 targets) knows only that
            // there is something, which is why its rows carry no number.
            const found = (k: ClipKind): number =>
              ctxDetails == null && k !== "groups"
                ? 0 : copyOne(k, ctxDetails ?? [], targets).length;
            const held = (k: ClipKind): number => (CTX_CLIPBOARD[k] ?? []).length;
            // Copy and paste offer the SAME kinds in the same order, so the two
            // halves of the menu read as one list twice rather than as two.
            const KINDS: { key: ClipKind; icon: string; copy: string; paste: string }[] = [
              { key: "tags", icon: "sell", copy: "Copy tags", paste: "Paste tags" },
              { key: "subjects", icon: RECORD_ICON.subject, copy: "Copy subjects", paste: "Paste subjects" },
              { key: "places", icon: RECORD_ICON.place, copy: "Copy places", paste: "Paste places" },
              { key: "events", icon: RECORD_ICON.event, copy: "Copy events", paste: "Paste events" },
              { key: "groups", icon: "folder", copy: "Copy groups", paste: "Paste groups" },
              { key: "captions", icon: "notes", copy: "Copy captions", paste: "Paste captions" },
              { key: "instructions", icon: "swap_horiz", copy: "Copy instructions", paste: "Paste instructions" },
              { key: "links", icon: "link", copy: "Copy links", paste: "Paste links" },
            ];
            const copyKinds = KINDS.filter((k) => found(k.key) > 0);
            const pasteKinds = KINDS.filter((k) => held(k.key) > 0);
            // ---- THE ACTIONS TAB'S AI ACTIONS, from the one builder
            // (`app/aiActionSections.ts`) — running a model is the other
            // thing a right-click on a picture is for, and reaching the
            // sidebar's tab first is a journey. Which kinds the TARGETS can
            // take is this menu's own question: a video takes no editor,
            // and a sequence container only the batch kinds. ---------------
            const aiKinds = ctxMenu.ids.map(
              (id) => itemById.get(id)?.kind ?? "image");
            const aiSections = trashView ? [] : taskSections(
              ctxModels?.tasks, readyModel(ctxCache?.models), targetsTake(aiKinds));
            const aiRows = aiSections.flatMap((sec) => sec.rows);
            const aiRun = (kind: string, model: string, name: string) => {
              const row = aiRows.find((r) => r.tk.kind === kind);
              if (row) void ctxEnqueue(kind as JobKind, model, row.tk, name);
            };
            const clicked = itemById.get(ctxMenu.clickedId);
            const inOrder = [ctxMenu.clickedId,
                             ...ctxMenu.ids.filter((id) => id !== ctxMenu.clickedId)];
            // Multi-target: every IMAGE in the selection opens as a tab of
            // one editor window (the clicked one active).
            const editIds = n > 1
              ? inOrder.filter((id) => itemById.get(id)?.kind === "image")
              : [ctxMenu.clickedId];
            // Annotating opens its own window, and a multi-target annotate
            // opens the selection AS TABS of one — the same shape as Edit
            // images. A sequence has no picture to draw on.
            const annotateIds = (n > 1 ? inOrder : [ctxMenu.clickedId])
              .filter((id) => itemById.get(id)?.kind !== "sequence");
            const actions: RowAction[] = [];
            actions.push(n > 1 ? {
              icon: "edit", label: t("Edit images"),
              trailing: String(editIds.length),
              disabled: editIds.length === 0,
              onClick: () => openEditorMulti(editIds),
            } : {
              icon: clicked?.kind === "video" ? "movie_edit" : "edit",
              label: clicked?.kind === "video" ? t("Edit video") : t("Edit image"),
              disabled: clicked == null || clicked.kind === "sequence",
              onClick: () => openEditor(ctxMenu.clickedId),
            });
            actions.push({
              icon: "ads_click", label: t("Annotate"),
              trailing: n > 1 ? String(annotateIds.length) : undefined,
              disabled: annotateIds.length === 0,
              onClick: () => {
                if (annotateIds.length > 1) openAnnotatorMulti(annotateIds);
                else if (annotateIds.length === 1) openAnnotator(annotateIds[0]);
              },
            });
            actions.push({
              icon: "visibility", label: t("Preview"),
              onClick: () => {
                setSelectedItems(ctxMenu.ids);
                setSelMembers(new Set()); // names items, not occurrences
                setQuickLook(true);
              },
            });
            // THE PICTURE, BIG, OVER THE GRID AREA (owner 2026-09) — exactly
            // the look the sidebar's caption editor puts up while a caption
            // is typed (`CaptionPreview`, `store.captionPreview`): over the
            // middle pane only, the sidebars untouched, its own ✕ and Escape
            // the way out. Not the full-window preview.
            actions.push({
              icon: "push_pin", label: t("Pin Preview"), kbd: "⇧Space",
              disabled: clicked == null || clicked.kind === "sequence",
              onClick: () => {
                setSelectedItems([ctxMenu.clickedId]);
                setSelMembers(new Set());
                useUI.getState().setCaptionPreview(ctxMenu.clickedId);
              },
            });
            // FIND WHAT IS COLOURED LIKE THIS. Composes a query and hands it
            // to the search field — the grid, the selection bar and quick
            // assign then all work on the result unchanged, which is the
            // whole reason likeness is a condition and not a sort. One image
            // only: likeness is pairwise, and a video carries no colour
            // signature. It NARROWS THE VIEW rather than replacing it: a
            // search composes with the scope by construction. (A "Find
            // visually similar" over the perceptual hash was beside it and
            // is gone: the importer FOLDS a re-encode, a crop and a rotation
            // onto the item they match, so on an imported library it
            // reliably found the picture itself and nothing else.)
            if (n === 1 && clicked?.kind === "image" && clicked.uid) {
              const uid = clicked.uid;
              actions.push({
                icon: "palette", label: t("Find similar colors"), separated: true,
                onClick: () => setSearch(`COLORLIKE:${uid}`),
              });
            }
            // ONE ROW PER SECTION — Edit, Detect, Generate — each opening its
            // action list beside it, each action its models (the macOS
            // shape; expanding in place grew the menu past the bottom of the
            // screen). Only ready models: anything needing setup, a download
            // or a reference picker stays a sidebar affair, where the chips
            // explain themselves.
            actions.push(...aiActionRows(aiSections, t, aiRun, {
              separatedFirst: true,
              onExtraOutput: () => setClipTick((v) => v + 1),
            }));
            // LAST USED — the action picked from this menu last time, at the
            // root beside the three sections it would otherwise sit two
            // boxes inside, and only while this menu would offer it anyway
            // (`offeredLastAction`).
            {
              let stored: string | null = null;
              try { stored = storage.get(LAST_ACTION_KEY); } catch { /* ignore */ }
              const hit = offeredLastAction(parseLastAction(stored), aiRows);
              if (hit) {
                const { last, row: r } = hit;
                actions.push({
                  icon: "history", label: `${t(last.task)} · ${last.name}`,
                  hint: t("Last used"),
                  onClick: () => void ctxEnqueue(
                    r.tk.kind as JobKind, last.model, r.tk, last.name),
                });
              }
            }
            // NO "Rate on …" here. A ranking session is a mode the whole
            // window enters — it takes the keyboard and covers the grid —
            // where every other row in this menu does something to the
            // pictures under the pointer and leaves you where you are. It is
            // started from the quick-actions menu's "Rate items…", where the
            // other full-window session lives too.
            //
            // ONE Copy. It was a row per kind — up to eight of them, each a
            // decision about something you would then decide about AGAIN
            // when pasting. Taking everything costs the same one request,
            // and the paste side still offers each kind on its own. The
            // tooltip says what it took. NAMED for what it takes, because a
            // bare "Copy" in a grid of pictures reads as copying the picture
            // — and it takes none of it. Not "Copy metadata", which would
            // name the one family it leaves behind (the Info tab's facts
            // about the FILE, which are not transferable at all).
            if (copyKinds.length > 0) {
              actions.push({
                icon: "content_copy", label: t("Copy labels and links"),
                separated: true,
                title: copyKinds.map((k) => ctxSampled
                  ? t(k.copy) : `${t(k.copy)} (${found(k.key)})`).join("\n"),
                onClick: () => void ctxCopy(copyKinds.map((k) => k.key)),
              });
            }
            // The ID alone, to the SYSTEM clipboard — what a picture is named
            // by outside this page. No paste row for it: what an id would be
            // pasted INTO is a text field, and those already take a paste.
            actions.push({
              icon: "tag", label: tn({ one: "Copy id", other: "Copy ids ({n})" }, n),
              separated: copyKinds.length === 0,
              onClick: () => copyUids(targets.map((i) => i.uid).filter(Boolean)),
            });
            if (pasteKinds.length > 1) {
              actions.push({
                icon: "content_paste", label: t("Paste all"),
                trailing: String(pasteKinds.length), separated: true,
                onClick: () => void ctxPaste(pasteKinds.map((k) => k.key)),
              });
            }
            pasteKinds.forEach((k, i) => actions.push({
              icon: k.icon, label: t(k.paste), trailing: String(held(k.key)),
              separated: i === 0 && pasteKinds.length <= 1,
              onClick: () => void ctxPaste([k.key]),
            }));
            // THE WAY OUT of a clipboard that is in the way. It holds
            // whatever was last copied for the rest of the session, so
            // without this the paste rows are on every menu until the page
            // is reloaded — and a Paste row is a click away from a Copy row.
            if (pasteKinds.length > 0) {
              actions.push({
                icon: "backspace", label: t("Clear the clipboard"),
                onClick: () => {
                  for (const k of Object.keys(CTX_CLIPBOARD)) {
                    delete (CTX_CLIPBOARD as Record<string, unknown>)[k];
                  }
                  setClipTick((v) => v + 1);
                },
              });
            }
            // MARK THIS PICTURE — and ONE PICTURE ONLY (owner 2026-09): a
            // bookmark is a place, and a place is one picture, so with
            // several of them in the menu the row is not offered at all.
            // Every other row here acts on the whole selection because what
            // it does is the same thing done N times; "come back to these
            // forty" is not that, and a row that quietly marked the one
            // under the pointer while the menu said "40 items" would be
            // answering a different question from the one on screen.
            // (Right-clicking a card OUTSIDE the selection is a menu about
            // that card alone — `ctxTargets` — so the row is offered there.)
            if (n === 1) {
              const one = targets[0];
              if (one) {
                const on = bookmarked.has(one.id);
                actions.push({
                  icon: on ? "bookmark_remove" : "bookmark_add",
                  label: on ? t("Remove bookmark") : t("Add bookmark"),
                  separated: true,
                  onClick: () => {
                    setCtxMenu(null);
                    toggleBookmark(one.id);
                  },
                });
              }
            }
            // OUT OF THIS GROUP — the Delete key made findable, which is
            // what this menu is for (owner 2026-09). Offered on exactly the
            // views the key answers on (`scopeGroup`): one ordinary group
            // picked in the sidebar, so a special scope — All items,
            // Ungrouped, Trash — has no group to name and offers nothing,
            // and a smart group's membership is a rule the row could not
            // change. It names the group, since from the grid the sidebar's
            // pick is the only thing saying which one "here" is.
            if (scopeGroup) {
              const g = scopeGroup;
              actions.push({
                icon: "folder_off", separated: true,
                label: t("Remove from “{group}”", { group: g.name }),
                onClick: () => {
                  const ids = ctxMenu.ids;
                  setCtxMenu(null);
                  void removeFromGroup(ids, g.id, g.name);
                },
              });
            }
            actions.push({
              icon: allHidden ? "visibility" : "visibility_off",
              label: allHidden ? t("Show") : t("Hide"), separated: true,
              onClick: () => void ctxHide(!allHidden),
            });
            actions.push(trashView
              ? { icon: "delete_forever", label: t("Delete"), danger: true,
                  separated: true, onClick: () => void ctxDeleteForever() }
              : { icon: "delete", label: t("Move to trash"), danger: true,
                  separated: true, onClick: () => void ctxTrash() });
            return (
              <PointerMenu
                at={ctxMenu}
                heading={n > 1 ? `${n} ${t("items")}` : undefined}
                actions={actions}
                onClose={() => setCtxMenu(null)}
              />
            );
          })()}
        </div>
        {view.isFetching && !view.isLoading && (
          <div style={{ padding: "14px 0 24px", textAlign: "center", color: "var(--muted-3)", fontFamily: "var(--mono)", fontSize: "var(--fs-2)" }}>
            Loading more…
          </div>
        )}
        </>)}
      </div>
      {/* Cmd+A over a partially-loaded view: say what was actually selected. */}
      {selNote && (
        <ActionToast autoDismissMs={5000}
          text={selNote}
          icon="check"
          actionLabel={t("OK")}
          onAction={() => setSelNote(null)}
          dismissTitle={t("Dismiss")}
          onDismiss={() => setSelNote(null)}
        />
      )}
    </div>
  );
}

// A card-shaped stand-in for an index whose page hasn't loaded yet. Must keep
// the EXACT dimensions of ItemCard (thumb box of height `cellW` + META_H meta
// block), or the windowing math above stops describing what is on screen.
function PlaceholderCard({ cellW }: { cellW: number }) {
  return (
    <div style={{ userSelect: "none" }}>
      <div
        style={{
          height: cellW, borderRadius: "var(--r-4)",
          background: "var(--panel-3)", border: "1px solid var(--border-soft)",
          opacity: 0.6,
        }}
      />
      <div style={{ height: META_H }} />
    </div>
  );
}

// Toolbar media-kind filter: a button + popover with a checkbox per kind. No
// selection means "all kinds".
/** WHICH ORDER THE GRID IS IN — the field and the direction, in one button.
 *
 *  The button says the field, and an arrow says which way; the menu lists
 *  every field with the arrow IT would be read in, because that is remembered
 *  per field and is the thing you are choosing between. Picking the field
 *  already selected flips it, which is what the separate direction button
 *  used to be for.
 *
 *  A shuffle has no direction and so carries none: its own re-deal is the
 *  dice beside this, since dealing again is an action rather than a way of
 *  reading the same order.
 */
function SortMenu({ field, dir, dirs, disabled, fixedLabel, onPick, t }: {
  field: SortField;
  dir: SortDir;
  dirs: Record<SortField, SortDir>;
  disabled: boolean;
  /** What the order IS while the control stands down. Two views fix their
   *  own order — a sequence is in the book's, a ranking is in the
   *  standings' — and a control that said "Sequence order" in a ranking was
   *  naming the wrong one of them. */
  fixedLabel: string;
  onPick: (f: SortField) => void;
  t: (s: string) => string;
}) {
  const label = disabled
    ? fixedLabel
    : t(SORT_OPTIONS.find((o) => o.value === field)?.label ?? "Imported");
  const arrow = disabled ? null
    : field === "random" ? null
    : dir === "desc" ? "arrow_downward" : "arrow_upward";
  const pill: React.CSSProperties = {
    width: "auto", height: 34, gap: 6, padding: "0 8px 0 10px", borderRadius: "var(--r-5)",
    border: "1px solid var(--border-strong)", background: "var(--panel-2)",
    color: "var(--text-3)", fontSize: "var(--fs-3)",
  };
  const face = <>
    {label}
    {arrow && <Icon name={arrow} size={16} color="var(--muted-2)" />}
    <Chevron />
  </>;
  if (disabled) {
    return (
      <button disabled title={t("Sorted by sequence order")}
        style={{ ...pill, display: "flex", alignItems: "center", cursor: "default" }}>
        <Icon name="swap_vert" size={17} color="var(--muted-2)" />{label}
      </button>
    );
  }
  // The arrow is only on the SELECTED row. Every row wearing one read as six
  // directions to choose between, where there is one — the direction the grid
  // is in. What the others remember is theirs to show once they are the one
  // selected.
  return (
    <RowMenu always icon="swap_vert" color="var(--muted-2)" title={t("Sort by")}
      buttonStyle={pill} label={face}
      actions={SORT_OPTIONS.map((o) => {
        const on = o.value === field;
        return {
          checked: on, label: t(o.label),
          trailingIcon: on && arrow ? arrow : undefined,
          hint: on ? t("Sorted by this — click to reverse") : undefined,
          onClick: () => onPick(o.value),
        };
      })} />
  );
}

/** The keyboard actions, findable with a mouse.
 *
 *  T, Q and R are full-window overlays a new user has no way to discover —
 *  a shortcut that lives nowhere visible is one nobody finds, the keycap
 *  rule the overlays' own footers already follow. So the toolbar carries a
 *  menu of the same three actions with their keys spelled as caps; picking a
 *  row does exactly what the key does, through the same guards.
 */
/** A big look at the item whose caption is being written, drawn over the
 *  grid. Mounted always and empty until the sidebar asks — the alternative
 *  is a conditional hook order in ItemGrid, and the query below is disabled
 *  while there is nothing to show, so an idle mount costs a render of null.
 *
 *  It fetches the item rather than reading the loaded pages: a caption is
 *  often being written for something reached from a link or a search that
 *  has since scrolled away, and "the picture, unless it happens to be on
 *  this page" is not a promise worth making. */
function CaptionPreview() {
  const t = useT();
  const id = useUI((s) => s.captionPreview);
  const { data: item } = useQuery({
    queryKey: ["item", id],
    queryFn: () => api.item(id as number),
    enabled: id != null,
  });
  // DISMISSED FOR THIS SITTING. A caption is often about a detail, so the
  // picture is worth having large — but it covers the grid, and sometimes
  // the grid is what you want. The ✕ puts it away without taking the caret
  // out of the box; it comes back the next time a caption field is focused,
  // because that is the moment the question "what is in this picture?" is
  // asked again. Reset on the ITEM, so moving to another picture shows it.
  const [hidden, setHidden] = useState(false);
  useEffect(() => { setHidden(false); }, [id]);
  // ESCAPE PUTS IT AWAY TOO (owner 2026-09) — the grid menu's "Pin"
  // opens this same look with no caption field to leave, so a key is the
  // way out beside the ✕. The stack skips a typing target, so a caption
  // being typed keeps its own Escape.
  const setCaptionPreview = useUI((s) => s.setCaptionPreview);
  useEscape(() => setCaptionPreview(null), { enabled: id != null && !hidden });
  if (id == null || hidden) return null;
  // A FILM PLAYS HERE, because captioning one means watching it — a still
  // frame answers almost nothing about a video, and leaving the sidebar to
  // find the player is leaving the caption half-written. It does NOT start
  // by itself: the box below is being typed into, and a film that ran off
  // the moment the caret arrived would take the attention the typing wants.
  // No zoom for it either, the rule QuickLook already follows — the
  // transport owns the pointer there, where a drag means scrub.
  const video = item?.kind === "video" && item.active_file_id != null;
  // A sequence container has no file of its own, in which case the dim alone
  // says the grid is standing aside.
  const src = item?.active_file_id != null
    ? api.fileUrl(item.active_file_id, item.rotation)
    : null;
  return (
    <div style={{
      // IT TAKES THE POINTER NOW. It used to be `pointerEvents: none` — a
      // thing to look at while the hands were in the sidebar — and that is
      // exactly what a zoom cannot be: the wheel and the drag are the
      // gesture. The ✕ is what the pass-through used to buy, and it is the
      // better trade, because a click that falls through to the grid
      // underneath selects something you cannot see.
      position: "absolute", inset: 0, zIndex: 20,
      // A COLUMN THAT STRETCHES, so the zoom viewport FILLS this box.
      // Centring here sized it to its content instead — 333x333 inside a
      // 381x520 pane — and the viewport is what the zoom cluster is
      // positioned against, so the cluster travelled with the picture as it
      // grew and was clipped by the viewport's own `overflow: hidden`. The
      // preview centres its frame internally; this only has to give it the
      // whole area to centre in.
      display: "flex", flexDirection: "column",
      padding: 24, background: "var(--bg)",
    }}>
      {src && video && (
        <video
          key={src}
          src={src}
          controls
          playsInline
          preload="metadata"
          // The POSTER is the thumbnail, so the frame is filled before
          // anything is fetched — `preload="metadata"` deliberately does not
          // fetch the picture, and an empty black rectangle over the grid
          // reads as a preview that failed rather than one waiting to play.
          poster={item && item.active_file_id != null
            ? api.thumbUrl(item.active_file_id, item.rotation, item.thumb_token)
            : undefined}
          style={{
            flex: 1, minHeight: 0, width: "100%",
            objectFit: "contain", borderRadius: "var(--r-4)",
          }}
        />
      )}
      {src && !video && (
        <ZoomablePreview
          src={src}
          t={t}
          controlsStyle={{ position: "absolute", right: 12, bottom: 12 }}
          // The picture's own size as RECORDED, for the reason QuickLook
          // gives: an EXIF-oriented file reports its turned size as
          // `naturalWidth` while every `img` here draws the pixels as
          // stored, so a frame sized from the element distorts it.
          size={item && item.kind === "image" && item.width && item.height
            ? { w: item.width, h: item.height } : undefined}
        />
      )}
      <IconButton icon="close" size={28} glyph={16} tone="text" bordered fill="float" shape="round"
        // …AND CLEARS THE REQUEST, so the same picture asked for again (the
        // menu's "Pin") comes back; a caption field sets it again on
        // its next focus, which is what the title promises.
        onClick={() => { setHidden(true); setCaptionPreview(null); }}
        title={t("Hide the picture (it comes back with the next caption)")} style={{ position: "absolute", top: 12, right: 12 }} />
    </div>
  );
}

function QuickActionsMenu({ t, onRemoveWatermarks, lastAction, lastAvailable,
                            onRepeatLast }: {
  t: (s: string, vars?: Record<string, string>) => string;
  onRemoveWatermarks: () => void;
  /** The last used model action (`ctxLastUsed.ts`), and whether the
   *  selection is one it can run over. */
  lastAction: LastAction | null;
  lastAvailable: boolean;
  onRepeatLast: () => void;
}) {
  const [addingRanking, setAddingRanking] = useState(false);
  // The ids that existed when the creation dialog opened — what makes the
  // row it wrote identifiable in the list the API answers with.
  const knownRankings = useRef<Set<number>>(new Set());
  const qc = useQueryClient();
  const qaEnabled = useUI((s) => s.qaEnabled);
  const selCount = useUI((s) => s.selectedItems.length);
  // The rankings exist or the Rate row has nothing to open — off the same
  // cached key every other reader uses.
  const { data: rankings } = useQuery({
    queryKey: ["rankings"], queryFn: () => api.rankings(), staleTime: 60_000 });
  // `kbd` is the key that does the same thing; a row with none is a session
  // that opens from here alone (each once claimed a letter; two overlays each
  // owning one was a keyboard nobody could learn). A row that cannot run says
  // why in its hint rather than going missing.
  const row = (icon: string, label: string, kbd: string,
               onPick: (() => void) | null, why?: string,
               separated = false): RowAction => ({
    icon, label, kbd: kbd || undefined, disabled: !onPick, hint: why, separated,
    onClick: onPick ?? (() => {}),
  });
  // EVERY ranking can be rated on. There is nothing to filter on: a ranking
  // tags nothing by itself (rung v31 took the namespace and the two enabled
  // switches with it), so an axis either exists or does not.
  const rateRows = rankings ?? [];
  const rate = () => {
    // With no axis to rate on the row MAKES one rather than refusing:
    // somebody reaching for it wants to rate, and a ranking is the one thing
    // in the way — a disabled row naming another tab is an errand. The
    // session then starts on what they just made, so the detour ends where
    // the row promised.
    if (!rateRows.length) {
      knownRankings.current = new Set((rankings ?? []).map((r) => r.id));
      setAddingRanking(true);
      return;
    }
    // ALWAYS the chooser, however few axes there are — the row's ellipsis
    // promises one, and it is where the session's own options live (which
    // kind it asks about), which a straight-in start could never offer.
    // Naming an axis outright is the context menu's job, and that door still
    // starts directly.
    useUI.getState().setRateRanking(-1);
  };
  // THREE GROUPS, and the rules are the divisions: the keyboard rows that act
  // on what is picked right now; the rating axis and what is spent on it;
  // the two ways of going through pictures for a tag. A menu of eight rows
  // in one run read as eight unrelated errands.
  const actions: RowAction[] = [
    // THE PREVIEW: Space is what the grid answers with, and the row is
    // where the key can be read from. It wants a selection, as Space does.
    // Its side panel is not a second row (owner 2026-09): the preview opens
    // the way it was last left, and Tab inside it is the switch.
    row("visibility", t("Preview"), "Space",
        selCount > 0 ? () => useUI.getState().openQuickLook(
          useUI.getState().selectedItems) : null,
        selCount > 0 ? undefined : t("Select the items to preview first")),
    row("sell", t("Quick tag…"), "T", () => useUI.getState().requestQuickTag(),
        undefined, true),
    // C needs a SELECTION — a caption is a sentence about a particular
    // picture, so unlike T it does not mean the whole view.
    row("notes", t("Quick caption…"), "C",
        selCount > 0 ? () => useUI.getState().requestQuickCaption() : null,
        selCount > 0 ? undefined : t("Select the items to caption first")),
    row("bolt", t("Quick assign…"), "Q",
        qaEnabled ? () => useUI.getState().setQaOverlay(true) : null,
        qaEnabled ? undefined : t("Quick assign is switched off in the sidebar drawer")),
    // W runs at once — no dialog, so no ellipsis: the first ready remover
    // over the selected images. It opens the rows that touch PIXELS rather
    // than what the library says about them, under a rule of their own.
    row("branding_watermark", t("Remove watermark"), "W",
        selCount > 0 ? onRemoveWatermarks : null,
        selCount > 0 ? undefined : t("Select the images to remove watermarks from first"),
        true),
    // L: THE LAST MODEL ACTION AGAIN (owner 2026-09) — the context menu's
    // "Last used" row, over the selection. Named after what it would run,
    // and disabled with the reason while it cannot.
    row("history",
        lastAction ? `${t(lastAction.task)} · ${lastAction.name}`
                   : t("Repeat the last action"), "L",
        lastAction && lastAvailable && selCount > 0 ? onRepeatLast : null,
        !lastAction ? t("Nothing to repeat yet — run an action from an item's context menu first")
          : selCount === 0 ? t("Select the items first")
          : !lastAvailable ? t("Not offered for the selected items")
          : t("Last used")),
    row("balance", t("Rate items…"), "", rate,
        rateRows.length ? undefined : t("No ranking yet — this makes one"), true),
    // Not a session: it spends a rating session's evidence in one bulk write
    // — so it sits directly under the row that GATHERS that evidence.
    row("query_stats", t("Assign ratings…"), "",
        rateRows.length ? () => useUI.getState().setEstimateOpen(true) : null,
        rateRows.length ? undefined : t("Rate some pictures on a ranking first")),
    row("new_label", t("Tag items one by one…"), "",
        () => useUI.getState().setTagSortOpen(true), undefined, true),
    row("grid_view", t("Tag items in a grid…"), "",
        () => useUI.getState().setTagGridOpen(true)),
  ];
  return (
    <>
      <RowMenu always icon="bolt" title={t("Keyboard actions — tag, assign a set, rate")}
        actions={actions} minWidth={230}
        buttonStyle={{
          width: "auto", height: 34, gap: 6, padding: "0 10px", borderRadius: "var(--r-5)",
          fontSize: "var(--fs-3)", border: "1px solid var(--border-strong)",
          background: "var(--panel-2)", color: "var(--text-3)",
        }}
        label={<Chevron />} />
      {addingRanking && (
        <RankingEditOverlay ranking={null}
          onClose={() => setAddingRanking(false)}
          onSaved={(rows) => {
            setAddingRanking(false);
            qc.invalidateQueries({ queryKey: ["rankings"] });
            // The create answers with the whole list, so the new row is the
            // one the menu had not seen; nothing is opened if it cannot be
            // told apart.
            const made = (rows ?? []).find(
              (r) => !knownRankings.current.has(r.id));
            if (!made) return;
            // Made with several pools, it needs the chooser (the
            // context menu's rule); with one it starts straight in.
            if ((made.pools?.length ?? 1) > 1) {
              useUI.getState().setRateChooserSeed(made.id);
              useUI.getState().setRateRanking(-1);
            } else {
              useUI.getState().setRateRanking(made.id);
            }
          }} />
      )}
    </>
  );
}

// The size (as CSS %) of an image's letterboxed fit box inside a square cell,
// so a checkerboard can be drawn exactly behind the rendered image.
function fitBox(w: number, h: number): { width: string; height: string } {
  if (!w || !h) return { width: "100%", height: "100%" };
  const r = w / h;
  return r >= 1
    ? { width: "100%", height: `${(100 / r).toFixed(3)}%` }
    : { width: `${(r * 100).toFixed(3)}%`, height: "100%" };
}

function ItemCard({
  item, cellW, selected, secondary, dropSide, pointed, rowMatch, qaAssigned,
  bookmarked,
  onClick, onDoubleClickCard, onQaRemove, onDragStartCard, onContextMenuCard,
  onDragOverCard, onDropCard, onDragEndCard,
}: {
  item: ItemOut;
  cellW: number;
  selected: boolean;
  /** A selected item's OTHER occurrence, inside a sequence view: the same
   *  picture, but not the copy the gesture named — it wears a dashed ring
   *  where the named copy keeps the solid one. */
  secondary?: boolean;
  /** A sequence reorder is about to insert on this side of the card. */
  dropSide?: "before" | "after" | null;
  /** The sidebar is POINTING at this item — currently the other end of a
   *  picked link. A ring, not the selection colour: the selection is what
   *  every panel is about, and this is a card being indicated from one row of
   *  one of them. */
  pointed?: boolean;
  /** A picked sidebar row — a tag, a person, a place, an event, a group —
   *  is about this picture. */
  rowMatch: boolean;
  qaAssigned: boolean;
  /** Marked to come back to — see `app/bookmarks.ts`. */
  bookmarked: boolean;
  onClick: (e: React.MouseEvent) => void;
  onDoubleClickCard: () => void;
  onQaRemove: (e: React.MouseEvent) => void;
  onDragStartCard: (e: React.DragEvent) => void;
  onContextMenuCard: (e: React.MouseEvent) => void;
  onDragOverCard?: (e: React.DragEvent) => void;
  onDropCard?: (e: React.DragEvent) => void;
  onDragEndCard?: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const lang = useLang();
  return (
    <div
      data-item-card
      draggable
      onDragStart={onDragStartCard}
      onDragOver={onDragOverCard}
      onDrop={onDropCard}
      onDragEnd={onDragEndCard}
      onContextMenu={onContextMenuCard}
      onClick={onClick}
      onDoubleClick={onDoubleClickCard}
      title={item.hidden ? "Hidden item" : undefined}
      style={{ cursor: "pointer", userSelect: "none", position: "relative" }}
    >
      {/* Where a sequence reorder would land: a bar in the gap beside the
          card, on the half of it the pointer is in. */}
      {dropSide && (
        <div
          style={{
            position: "absolute", top: 0, height: cellW, width: 3,
            [dropSide === "after" ? "right" : "left"]: -Math.ceil(GAP / 2) - 1,
            borderRadius: 2, background: "var(--accent)", zIndex: 2,
            pointerEvents: "none",
          }}
        />
      )}
      <div
        // Flat backdrop behind the (fit-scaled) thumbnail. The transparency
        // checkerboard is drawn only behind the rendered image's box (below), so
        // the letterbox stays flat while transparent images still show it.
        style={{
          position: "relative", height: cellW, borderRadius: "var(--r-4)",
          overflow: "hidden",
          background: "var(--panel-3)",
          border: "1px solid var(--border)",
          // A SEQUENCE reads as a stack at a glance: two sheet edges peeking
          // out bottom-right — each a bg-coloured silhouette (invisible fill)
          // rimmed by a border-coloured one a pixel larger, so only the edges
          // show. Inside the 16px gap, and under the selection ring's offset.
          boxShadow: item.kind === "sequence"
            ? "3px 3px 0 -1px var(--bg), 3px 3px 0 0 var(--border), " +
              "6px 6px 0 -2px var(--bg), 6px 6px 0 -1px var(--border)"
            : undefined,
          // A ring drawn 3px outside the thumbnail: the gap keeps the selection
          // readable even on images whose colors match the accent.
          //
          // ONE yellow ring for everything the sidebar is pointing at — the
          // item at the other end of a picked link or instruction, and the
          // pictures carrying a picked tag, person, place or event — or
          // sitting in a picked GROUP. They are the same claim ("this row is
          // about these pictures"), and the tag match used to say it with a
          // badge in the corner instead: a second tag set for one idea, in
          // the one place a badge cannot be seen from across the grid.
          //
          // A selected item's OTHER copies (a repeated page, in a sequence
          // view) go GREY: they are just as selected — one picture, one
          // action — but not the copy the gesture named. A colour, not a
          // dash: a dashed accent ring read as a broken state of the same
          // selection rather than as a second, quieter claim.
          outline: selected
            ? `2px solid ${secondary ? "var(--muted-2)" : "var(--accent)"}`
            : (pointed || rowMatch) ? "2px solid var(--yellow)" : "none",
          outlineOffset: 3,
        }}
      >
        {/* A sequence shows a 2×2 mosaic of its first four members; everything
            else shows the single active-file thumbnail. */}
        {item.kind === "sequence" && item.member_thumbs.length > 0 ? (
          <div
            style={{
              position: "absolute", inset: 0, display: "grid",
              // `minmax(0, 1fr)` (not plain `1fr`) so a portrait page can't force
              // its track past the container — keeps all four cells equal squares.
              gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)",
              gridTemplateRows: "minmax(0,1fr) minmax(0,1fr)",
              // A visible 2px breathing gap between the four member thumbs
              // (the card's background shows through it).
              gap: 2, background: "var(--panel-2)",
            }}
          >
            {Array.from({ length: 4 }).map((_, i) => {
              const fid = item.member_thumbs[i];
              return fid != null ? (
                <img
                  key={i}
                  src={api.thumbUrl(fid)}
                  alt=""
                  loading="lazy"
                  // Non-draggable so the card's custom drag ghost is used
                  // (Safari otherwise drags the raw image file).
                  draggable={false}
                  style={{ width: "100%", height: "100%", minWidth: 0, minHeight: 0, objectFit: "cover", display: "block" }}
                />
              ) : (
                <div key={i} style={{ background: "var(--panel-3)" }} />
              );
            })}
          </div>
        ) : item.active_file_id ? (
          <>
            {/* Checkerboard sized to the image's fit box (not the whole cell),
                so it shows through transparent images but the letterbox stays a
                flat colour. */}
            <div
              className="mc-checker"
              style={{
                position: "absolute", top: "50%", left: "50%",
                transform: "translate(-50%, -50%)",
                ...fitBox(item.width, item.height),
              }}
            />
            <img
              src={api.thumbUrl(item.active_file_id, item.rotation, item.thumb_token)}
              alt=""
              loading="lazy"
              // Non-draggable so the card's custom drag ghost is used (Safari
              // otherwise drags the raw image file as the preview).
              draggable={false}
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", display: "block" }}
            />
          </>
        ) : null}
        {/* THE TICK IS ALWAYS THE WAY BACK OFF. It used to be a live button
            only while "Assign on click" was on, and an inert label otherwise —
            so the one control saying "this picture has the set" answered a
            click in one mode and did nothing in the other, which reads as a
            broken button rather than a scoped one. Taking a set off is the
            same act whatever put it there, and it is not what the toggle is
            about: that decides whether a click on the PICTURE assigns. */}
        {qaAssigned && (
          <div
            className="qa-badge"
            onClick={(e) => { e.stopPropagation(); onQaRemove(e); }}
            title="Quick Assign tags applied — click to remove"
            style={{
              position: "absolute", left: 7, top: 7, width: 22, height: 22,
              display: "flex", alignItems: "center", justifyContent: "center",
              borderRadius: "var(--r-2)", boxShadow: "var(--shadow-1)",
              cursor: "pointer",
            }}
          >
            {/* Check by default; a close glyph on hover hints at the removal. */}
            <Icon name="check" size={16} className="qa-badge-check" />
            <Icon name="close" size={16} className="qa-badge-close" />
          </div>
        )}
        {/* MARKED TO COME BACK TO. Bottom-left, the one corner nothing else
            uses: the quick-assign tick is top-left, the file count top-right
            and the sequence/length badges bottom-right. A glyph and no
            number — what it says is yes. */}
        {bookmarked && (
          <Chip tone="overlay" size="md"
                title={t("Bookmarked")}
                style={{ position: "absolute", left: 7, bottom: 7 }}>
            <Icon name="bookmark" size={13} />
          </Chip>
        )}
        {/* Source-file count: the *total* number of selectable source files
            (active + alternates), so an item with 3 files shows "3". */}
        {item.alt_count > 0 && (
          <Chip tone="overlay" size="md" mono
            title={t("{n} source files", { n: item.alt_count + 1 })}
            style={{ position: "absolute", right: 7, top: 7 }}>
            <Icon name="description" size={12} />
            {item.alt_count + 1}
          </Chip>
        )}
        {/* Sequence badge (bottom-right): the "3 / 24" position within a
            sequence. In a sequence view that's the open sequence; otherwise the
            item's first (main) sequence — shown the same way whether the item is
            in one sequence or several. Nudged left of a video's length badge if
            both show. Not shown on sequence container items. No leading icon:
            the sequence glyph reads as "this is a sequence", which it isn't. */}
        {item.kind !== "sequence" && item.seq_total > 0 && item.seq_index != null && (
          <Chip tone="overlay" size="md" mono
            title={item.seq_count > 1
              ? t("In {n} sequences · position shown for the current one", { n: item.seq_count })
              : t("Position in its sequence")}
            style={{ position: "absolute", bottom: 7,
                     right: item.kind === "video" && item.duration != null ? 66 : 7 }}>
            {`${item.seq_index} / ${item.seq_total}`}
          </Chip>
        )}
        {/* Video length badge, bottom-right. */}
        {item.kind === "video" && item.duration != null && (
          <Chip tone="overlay" size="md" mono style={{ position: "absolute", bottom: 7, right: 7 }}>
            <Icon name="play_arrow" size={12} />
            {fmtDuration(item.duration)}
          </Chip>
        )}
        {/* Sequence (folder) badge: a stack icon + member count, bottom-right. */}
        {item.kind === "sequence" && (
          <div
            title={t("Sequence — double-click to open its pages")}
            style={{ position: "absolute", bottom: 7, right: 7 }}>
            <Icon name="collections_bookmark" size={13} />
            {item.seq_total}
          </div>
        )}
      </div>
      <div style={{ height: META_H, padding: "7px 3px 2px", overflow: "hidden", display: "flex", alignItems: "center", gap: 6 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: "var(--fs-2)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-bright)" }}>
            {item.name}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3, fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>
            {item.kind === "sequence" ? (
              <span>{tn({ one: "1 item", other: "{n} items" }, item.seq_total)}</span>
            ) : (
              <>
                <span>{item.width}×{item.height}</span>
                <span style={{ color: "var(--muted-3)" }}>·</span>
                <span>{mpLabel(item.width, item.height, lang)}</span>
              </>
            )}
          </div>
        </div>
        {/* Hidden-state indicator: a crossed-out eye right-aligned to the
            thumbnail edge, instead of dimming the whole card. */}
        {item.hidden && (
          <span title="Hidden item" style={{ flex: "0 0 auto", display: "flex", alignItems: "center", color: "var(--muted-2)" }}>
            <Icon name="visibility_off" size={16} />
          </span>
        )}
      </div>
    </div>
  );
}

/** THE RANKINGS THEMSELVES, as cards — what the sidebar's Rankings row
 *  opens (owner 2026-09).
 *
 *  It showed the union of every ranking's placed pictures for a day, which
 *  answered a question nobody had asked: the row is where a ranking is MET,
 *  and what belongs under it is the rankings. So this is an INDEX — one card
 *  per ranking, the same rows the sidebar lists under that chevron — drawn
 *  the way a sequence is drawn, because a ranking is the same kind of thing
 *  on this screen: a container you open, whose cover is a 2×2 mosaic of what
 *  is inside it. Its best four, since the standings are what a ranking has
 *  to show for itself.
 *
 *  The subtitle is about the RANKING, where a picture's says its size: the
 *  comparisons behind it and the scale they are spread over, which are the
 *  two numbers that say whether an axis is worth opening.
 *
 *  A click OPENS it, unlike a picture's card, which selects. There is
 *  nothing else a click could mean here — a ranking is not an item, so no
 *  action in this window takes one — and a double-click to open a thing
 *  that cannot be selected would be a gesture with no single-click half.
 */
/** Narrower than this and the card's line says the comparisons alone — two
 *  phrases and a separator do not fit a small card, and the one that has to
 *  survive is the count. (The medium card is 168 px.) */
const POOLS_FIT_AT = 150;

function RankingsIndex({ columns, cellW }: {
  columns: number; cellW: number;
}) {
  const t = useT();
  const tn = useTn();
  const showRanking = useUI((s) => s.showRanking);
  const covered = useCoveredByWindow();
  // ITS OWN QUERY KEY, because it asks for something the sidebar's does not:
  // the covers cost a fit per ranking, and the sidebar polls.
  const { data: rows, isLoading } = useQuery({
    queryKey: ["rankings", "cards"], queryFn: () => api.rankings(4),
    enabled: !covered });
  if (isLoading) return <Loading label={t("Loading…")} />;
  const list = rows ?? [];
  if (!list.length) return <EmptyState line={t("No rankings yet.")} />;
  return (
    <div style={{
      padding: PAD, display: "grid", gap: GAP,
      gridTemplateColumns: `repeat(${Math.max(1, columns)}, minmax(0, 1fr))`,
    }}>
      {list.map((r) => (
        <div
          key={r.id}
          onClick={() => showRanking(r.id)}
          title={t("Open this ranking")}
          style={{ cursor: "pointer", userSelect: "none" }}
        >
          <div style={{
            position: "relative", height: cellW, borderRadius: "var(--r-4)",
            overflow: "hidden", background: "var(--panel-3)",
            border: "1px solid var(--border)",
            // The sequence card's two sheet edges: a ranking is a container
            // on this screen too, and the stack is what says so at a glance.
            boxShadow: "3px 3px 0 -1px var(--bg), 3px 3px 0 0 var(--border), "
              + "6px 6px 0 -2px var(--bg), 6px 6px 0 -1px var(--border)",
          }}>
            {r.thumbs.length > 0 ? (
              <div style={{
                position: "absolute", inset: 0, display: "grid",
                gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)",
                gridTemplateRows: "minmax(0,1fr) minmax(0,1fr)",
                gap: 2, background: "var(--panel-2)",
              }}>
                {Array.from({ length: 4 }).map((_, i) => {
                  const fid = r.thumbs[i];
                  return fid != null ? (
                    <img key={i} src={api.thumbUrl(fid)} alt="" loading="lazy"
                         draggable={false}
                         style={{ width: "100%", height: "100%", minWidth: 0,
                                  minHeight: 0, objectFit: "cover",
                                  display: "block" }} />
                  ) : (
                    <div key={i} style={{ background: "var(--panel-3)" }} />
                  );
                })}
              </div>
            ) : (
              // NOTHING PLACED YET is a state a ranking is in for as long as
              // it takes to compare a few pairs, so the card says it rather
              // than drawing an empty box.
              <div style={{
                position: "absolute", inset: 0, display: "flex",
                flexDirection: "column", alignItems: "center",
                justifyContent: "center", gap: 8, color: "var(--muted-3)",
                textAlign: "center", padding: 12,
              }}>
                <Icon name="leaderboard" size={30} color="var(--border-strong)" />
                <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
                  {t("Nothing placed yet")}
                </span>
              </div>
            )}
            {/* The sequence badge's corner, with the number that means the
                same thing here: how many pictures are inside. */}
            <Chip tone="overlay" size="md" mono style={{ position: "absolute", bottom: 7, right: 7 }}>
              <Icon name="leaderboard" size={13} />
              {r.items}
            </Chip>
          </div>
          <div style={{ height: META_H, padding: "7px 3px 2px",
                        overflow: "hidden" }}>
            <div style={{ fontSize: "var(--fs-2)", fontWeight: 500, overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap",
                          color: "var(--text-bright)" }}>
              {r.name}
            </div>
            {/* WHAT IS THERE ROOM FOR. A picture's line is two numbers that
                always fit; a ranking's words do not, and at the small card
                size the pools ran off the card's own edge. So the COMPARISONS
                are always there — the number that says whether an axis is
                worth opening — and the pools join them where the card is wide
                enough to read both. (The scale was here too and is not: it is
                the same 0–9 on nearly every ranking, so it spent the line
                saying nothing.) The row clips rather than wraps, since
                `META_H` is a fixed height every card in the grid shares. */}
            <div style={{ display: "flex", alignItems: "center", gap: 8,
                          marginTop: 3, fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                          color: "var(--muted-2)", overflow: "hidden",
                          whiteSpace: "nowrap" }}>
              <span>{tn({ one: "1 comparison", other: "{n} comparisons" },
                         r.judgments)}</span>
              {r.pools.length > 1 && cellW >= POOLS_FIT_AT && (<>
                <span style={{ color: "var(--muted-3)" }}>·</span>
                <span>{tn({ one: "1 pool", other: "{n} pools" },
                          r.pools.length)}</span>
              </>)}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * The Jump-to popover.
 *
 * Date groupings stack year › month whatever the section granularity is —
 * grouping by day over fifteen years is thousands of sections, and a flat list
 * of those is the thing this exists not to be. Everything else lists flat,
 * because those tag sets are already short.
 *
 * Built from the SAME runs array the grid lays out, so it can never offer a
 * section the grid does not have.
 */
/**
 * THE BOOKMARKS DROPDOWN — the marks THIS VIEW HOLDS (owner 2026-09).
 *
 * Not all of them: a list of places you cannot get to from here is a list
 * that reads as broken, and the answer to "which of these are in this view"
 * is the same one request as "what row is this one on" — `POST
 * /api/items/index`, asked once when the menu opens, for every mark at once.
 * A mark whose picture the view does not hold comes back null and is left
 * out; the others carry their row with them, so picking one is a scroll and
 * not a second round trip.
 *
 * A MARK IS AN ITEM AND NOTHING ELSE, so the name and the thumbnail are read
 * from the item — through `["item", id]`, the key the sidebar's own detail
 * query uses, so a picture that has been looked at is already in hand and a
 * renamed one is never listed under its old name. Only for the rows that
 * are SHOWN: a mark outside this view is a row nobody will read.
 */
function BookmarksMenu({ rect, bookmarks, req, t, onPick, onRemove }: {
  rect: DOMRect | null;
  bookmarks: number[];
  /** The view as the page query asks it — the one the marks are tested
   *  against. */
  req: ItemSearchBody;
  t: (s: string) => string;
  onPick: (itemId: number) => void;
  onRemove: (itemId: number) => void;
}) {
  const { data, isPending } = useQuery({
    queryKey: ["bookmark-indexes", JSON.stringify(req), bookmarks.join(",")],
    queryFn: () => api.itemIndexes(req, bookmarks),
    // One answer per open: the view is not moving while the menu is over it.
    staleTime: 30_000,
  });
  const here = bookmarks.filter((_, i) => data?.indices[i] != null);
  const rows = useQueries({
    queries: here.map((id) => ({
      queryKey: ["item", id],
      queryFn: () => api.item(id),
      staleTime: 30_000,
    })),
  });
  return (
    <AnchoredDropdown rect={rect} minWidth={260}>
      <div style={{ maxHeight: 360, overflowY: "auto" }}>
        {isPending ? (
          <div style={{ padding: "8px 10px", color: "var(--muted)", fontSize: "var(--fs-2)" }}>
            {t("Looking…")}
          </div>
        ) : here.length === 0 ? (
          <div style={{ padding: "8px 10px", color: "var(--muted)", fontSize: "var(--fs-2)" }}>
            {t("No bookmarks in this view")}
          </div>
        ) : here.map((id, i) => {
          const it = rows[i]?.data;
          return (
            <MenuRow key={id} onClick={() => onPick(id)} title={it?.name}
                     trailing={
                       <IconButton icon="close" size={22} glyph={14} tone="muted"
                         title={t("Remove bookmark")}
                         onClick={(e) => { e.stopPropagation(); onRemove(id); }} />
                     }>
              {/* The picture is the row: a list of file names says far less
                  about "where was I" than the thumbnails do. */}
              {it?.active_file_id != null ? (
                <img src={api.thumbUrl(it.active_file_id, it.rotation ?? 0, it.thumb_token)}
                     alt=""
                     style={{ width: 28, height: 28, flex: "0 0 auto", objectFit: "cover",
                              borderRadius: "var(--r-2)", background: "var(--panel-3)" }} />
              ) : (
                <span style={{ width: 28, height: 28, flex: "0 0 auto", display: "flex",
                               alignItems: "center", justifyContent: "center",
                               borderRadius: "var(--r-2)", background: "var(--panel-3)",
                               color: "var(--muted-3)" }}>
                  <Icon name="collections_bookmark" size={15} />
                </span>
              )}
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                             textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {it?.name ?? "…"}
              </span>
            </MenuRow>
          );
        })}
      </div>
    </AnchoredDropdown>
  );
}

function JumpMenu({ groupBy, runs, lang, t, onPick, rect }: {
  groupBy: string;
  runs: GroupRun[];
  lang: string;
  t: (s: string) => string;
  onPick: (key: string) => void;
  /** The Jump button's rect, from `useAnchorRect`. */
  rect: DOMRect | null;
}) {
  const groups = useMemo(() => jumpGroups(groupBy, runs, lang, t),
                         [groupBy, runs, lang, t]);
  const dated = groupBy === "year" || groupBy === "month" || groupBy === "day";
  // The newest period open by default: it is where a date-sorted library is
  // usually being worked on, and an all-collapsed list needs a click before it
  // says anything.
  const [open, setOpen] = useState<string | null>(
    dated && groups.length ? groups[0].label : null);
  return (
    <AnchoredDropdown rect={rect} minWidth={220}>
      <div>
        {groups.map((g) => (
          <div key={g.label || "flat"}>
            {dated && g.label && (
              <button
                onClick={() => setOpen((v) => (v === g.label ? null : g.label))}
                style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%",
                  padding: "6px 8px", borderRadius: "var(--r-3)", cursor: "pointer",
                  border: "none", background: "transparent",
                  color: "var(--text)", fontSize: "var(--fs-4)", fontWeight: 600,
                  textAlign: "left",
                }}
              >
                <Icon name={open === g.label ? "expand_more" : "chevron_right"}
                      size={16} />
                <span style={{ flex: 1 }}>{g.label}</span>
                <span style={{ color: "var(--text-2)", fontWeight: 400 }}>
                  {g.count}
                </span>
              </button>
            )}
            {(!dated || !g.label || open === g.label) && g.entries.map((e) => (
              <button
                key={e.key}
                onClick={() => onPick(e.key)}
                className="hoverable"
                style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%",
                  padding: "6px 8px", paddingLeft: dated && g.label ? 30 : 8,
                  borderRadius: "var(--r-3)", cursor: "pointer", border: "none",
                  background: "transparent", color: "var(--text)",
                  fontSize: "var(--fs-3)", textAlign: "left",
                }}
              >
                {e.swatch && <span style={{
                  width: 11, height: 11, borderRadius: 3, background: e.swatch,
                  border: "1px solid var(--border)", flex: "0 0 auto" }} />}
                <span style={{ flex: 1, whiteSpace: "nowrap",
                               overflow: "hidden", textOverflow: "ellipsis" }}>
                  {e.label}
                </span>
                <span style={{ color: "var(--text-2)" }}>{e.count}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </AnchoredDropdown>
  );
}
