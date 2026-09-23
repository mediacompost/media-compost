import React, { useEffect, useMemo, useRef, useState } from "react";
import { Collapse } from "../../shared/Collapse";
import { useDragEndReset } from "../../shared/useDragRow";
import { APP_PREFS } from "../prefs";
import { SearchField } from "../../shared/SearchField";
import { Row, rowBackground } from "../../shared/Row";
import { SectionHeading } from "../../shared/SectionHeading";
import { IconButton } from "../../shared/IconButton";
import { Count } from "../../shared/CountBadge";
import { SelectionBar } from "../../shared/SelectionBar";
import { pickNext } from "../../shared/pickList";
import { isTypingTarget } from "../../shared/typingTarget";
import { ask, confirm } from "../../shared/ConfirmModal";
import { BIG_EDIT } from "../bulk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { composeViewQuery } from "../viewQuery";
import { api, GroupNode, RankingRow } from "../api";
import { SKIP_DONE_KINDS } from "../actionSections";
import { aiActionRows, readPanelsSequence, readyModel, taskSections } from "../aiActionSections";
import { Icon } from "../../shared/Icon";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { JobList } from "./JobList";
import { modalIsOpen, useCoveredByWindow, useUI } from "../store";
import { DETECT_WITH } from "../detectAndRemove";
import { useLang, useT, useTn , useNum } from "../i18n";
import { diskLevel, formatBytes, type DiskLevel } from "../format";
import { useWindowedList } from "../useWindowedList";
import { useViewScope } from "../useItems";
import { chunks, runBulk } from "../bulk";
import { getDraggedItems } from "../dragState";
import { PointerMenu, type RowAction } from "../../shared/RowMenu";
import { ActionToast } from "./shared/ActionToast";
import { useUndoBar } from "./shared/useUndoBar";
import { RankingEditOverlay } from "./RankingEditOverlay";
import { useMenuDismiss } from "../../shared/useMenuDismiss";

// A group row is exactly this tall (no margins), so the windowed tree's
// arithmetic is exact.
const GROUP_ROW_H = 30;

interface FlatRow {
  node: GroupNode;
  depth: number;
  hasChildren: boolean;
  isOpen: boolean;
  // Unique per row occurrence. A group with multiple parents (the DAG allows
  // it, e.g. after a copy) appears more than once, so keying by node id alone
  // collides and React renders rows in the wrong place.
  path: string;
}


function iconColor(_icon: string, selected: boolean, color: string | null): string {
  // A GROUP'S OWN COLOUR WINS, selected or not. Selection used to replace it
  // with the accent, which took the one thing that tells a row apart at a
  // glance away from exactly the row being looked at — and said nothing the
  // row was not already saying with its tint, its text colour and its weight.
  // The accent is what a group with NO colour of its own turns while selected,
  // which is the whole of what that rule was for. (`GroupSelect` has always
  // read it this way round; the two now agree.)
  if (color) return color;
  if (selected) return "var(--accent)";
  // All group icons share the same default tint.
  return "var(--muted)";
}

/** The library-path row in the expanded footer stats, with a copy button. */
/** Text colour for a disk-space level (null = the ordinary value colour). */
function diskColor(level: DiskLevel): string | null {
  if (level === "critical") return "var(--red-text)";
  if (level === "low") return "var(--yellow-text)";
  return null;
}

function LibraryPathRow({ path, label, copyTitle }: { path: string; label: string; copyTitle: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    try {
      navigator.clipboard?.writeText(path);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch { /* ignore */ }
  };
  return (
    <div style={{ marginTop: 3, paddingTop: 6, borderTop: "1px solid var(--border-soft)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 2 }}>
        <span>{label}</span>
        <span
          className="hoverable"
          onClick={copy}
          title={copied ? "Copied" : copyTitle}
          style={{ flex: "0 0 auto", width: 20, height: 20, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "var(--r-1)", cursor: "pointer", color: copied ? "var(--green-text)" : "var(--muted-2)", userSelect: "none" }}
        >
          <Icon name={copied ? "check" : "content_copy"} size={13} />
        </span>
      </div>
      <div
        title={path}
        style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--text-3)", wordBreak: "break-all", lineHeight: 1.4, userSelect: "text", WebkitUserSelect: "text" }}
      >
        {path}
      </div>
    </div>
  );
}

export function GroupTree() {
  const qc = useQueryClient();
  const t = useT();
  const tn = useTn();
  const lang = useLang();
  const num = useNum();
  const humanSize = (b: number) => formatBytes(b, lang);
  const { data: tree } = useQuery({ queryKey: ["groups"], queryFn: api.groups });
  // NOT WHILE THE ITEM WINDOW COVERS THE SIDEBAR. These four are counts on
  // rows nobody can see then, and every edit made in the annotator
  // invalidates all of them — see `useCoveredByWindow`. They keep their data,
  // go stale, and refetch once when the window closes.
  const covered = useCoveredByWindow();
  const { data: stats } = useQuery({ queryKey: ["library-stats"], queryFn: api.libraryStats,
                                     enabled: !covered });
  const { data: sequences } = useQuery({ queryKey: ["sequences"], queryFn: api.sequences });
  const {
    selectedGroups, setSelectedGroups, clearGroupSelection, setOverlay,
    openGroupEditor, ungrouped, showUngrouped, untagged, showUntagged, trashView, showTrash,
    hiddenView, showHidden, pendingView, pendingKind, showPending,
    sequenceView, rankingView, showAllItems, showKind, mediaKinds,
    expanded, toggleGroupExpanded, setGroupsExpanded,
    selectedItems,
  } = useUI();
  // "All Items" scope = no group / ungrouped / untagged / trash / hidden /
  // pending / open sequence / open ranking / the rankings index. `ItemGrid`
  // computes this a second time for the breadcrumb, and the two have to
  // agree about every scope — with the ranking missing here, All Items
  // stayed lit under a ranking view, and with the INDEX missing it stayed
  // lit under that. Every scope this list can be in belongs in this line.
  const rankedView = useUI((s) => s.rankedView);
  const scopeAllItems =
    selectedGroups.length === 0 && !ungrouped && !untagged && !trashView
    && !hiddenView && !pendingView && sequenceView == null
    && rankingView == null && !rankedView;
  const onlyKind = mediaKinds.length === 1 ? mediaKinds[0] : null;
  const allItemsActive = scopeAllItems && mediaKinds.length === 0;
  const kindActive = (k: string) =>
    (scopeAllItems && onlyKind === k) || (k === "sequence" && sequenceView != null);
  // Collapsible state for the All Items sub-filters (Images/Videos/Sequences).
  const [kindsOpen, setKindsOpen] = useState(() => APP_PREFS.kindsOpen.read());
  const toggleKindsOpen = () =>
    setKindsOpen((v) => { APP_PREFS.kindsOpen.write(!v); return !v; });
  // Collapsible state for the Pending row's Tags/Captions sub-filters.
  const [pendingOpen, setPendingOpen] = useState(() => APP_PREFS.pendingOpen.read());
  const togglePendingOpen = () =>
    setPendingOpen((v) => { APP_PREFS.pendingOpen.write(!v); return !v; });
  const KIND_CHILDREN = [
    { kind: "image", label: "Images", icon: "image" },
    { kind: "video", label: "Videos", icon: "movie" },
    { kind: "sequence", label: "Sequences", icon: "collections_bookmark" },
  ] as const;
  // Trashed item count for the sidebar badge; shares the "facets" prefix so the
  // trash/restore mutations' invalidateQueries(["facets"]) refreshes it.
  const { data: trashFacets } = useQuery({
    queryKey: ["facets", "trash"],
    queryFn: () => api.itemFacets({ trash: true }),
    enabled: !covered,
    // A badge count: invalidation still refetches it, but remounts/refocus
    // within half a minute reuse the cached figure instead of an O(total) scan.
    staleTime: 30_000,
  });
  const trashCount = trashFacets?.count ?? 0;
  // Count of items in no group, for the Ungrouped row badge. Shares the "facets"
  // prefix so group-assignment mutations' invalidateQueries(["facets"]) refresh
  // it alongside the trash badge.
  const { data: ungroupedFacets } = useQuery({
    queryKey: ["facets", "ungrouped"],
    queryFn: () => api.itemFacets({ ungrouped: true }),
    enabled: !covered,
    staleTime: 30_000,
  });
  const ungroupedCount = ungroupedFacets?.count ?? 0;
  // Count of items with no tags, for the Untagged row badge. Shares the "facets"
  // prefix so tag-assignment mutations' invalidateQueries(["facets"]) refresh it.
  const { data: untaggedFacets } = useQuery({
    queryKey: ["facets", "untagged"],
    queryFn: () => api.itemFacets({ untagged: true }),
    enabled: !covered,
    staleTime: 30_000,
  });
  const untaggedCount = untaggedFacets?.count ?? 0;

  // Anchor for shift-range selection (the last row clicked without shift).
  const anchorRef = useRef<number | null>(null);

  // Drag-and-drop reparenting. A group is identified internally by its id, but
  // the same group can appear at several tree positions (the DAG allows multiple
  // parents). So drag *visuals* are keyed by the unique row path — otherwise
  // every occurrence of a group would highlight at once — while the drop
  // *operation* uses the group id. `dragId` is the dragged group; `dragPath` is
  // the specific row it started from; `dropTarget` is the targeted row path, or
  // the sentinel "root" for the top-level ("All Items") drop zone.
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragPath, setDragPath] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  // Whether the footer is expanded to show the full library statistics.
  const [statsOpen, setStatsOpen] = useState(false);
  // Highlighted group row while dragging images (from the grid) over it.
  const [itemDropTarget, setItemDropTarget] = useState<string | null>(null);
  // While images from the grid are being dragged the tree grows one more row at
  // its end — the empty space under the groups — and dropping them there opens
  // the group creator seeded with them. `itemDragCount` is how many the drag
  // carries (null = no such drag in flight) and `newDropHover` is whether that
  // row is the current target.
  //
  // IT IS SET ONCE PER DRAG, AT `dragstart`, AND NOT WHILE THE POINTER MOVES.
  // Deciding it from `dragover` is the obvious spelling and it costs a state
  // write per pointer sample — on a platform whose drag loop is already the
  // slow part, that reads as a sidebar lagging behind the cursor. Spanning the
  // whole drag also says the option exists from the moment the images are
  // picked up (the tag list's own new-group zone works exactly this way)
  // rather than only once the pointer has found the empty part. The count
  // comes from `dragState`, because `dataTransfer` is unreadable until the
  // drop. `dragend` clears it, with the other drag highlights.
  const [itemDragCount, setItemDragCount] = useState<number | null>(null);
  const [newDropHover, setNewDropHover] = useState(false);
  const newDropHoverRef = useRef(false);
  // The same shape for a GROUP drag: a last row that takes it OUT of whatever
  // it is nested in. "All Items" has always been that drop target and still
  // is — but it is one fixed row at the very top of the sidebar, so on a tree
  // long enough to scroll it is not on screen at the moment somebody is
  // holding a group, and a gesture you cannot reach is a gesture that does
  // not exist. `dropTarget === "root"` is the one flag both zones set, so
  // they cannot light up at once or disagree about what a drop means.
  const [rootDropHover, setRootDropHover] = useState(false);
  const rootDropHoverRef = useRef(false);
  // WebKit fires `dragover` about 1400 times a second and paints 60 — measured
  // at 5771 events across 245 frames of one drag — and it keeps firing while
  // the pointer is STILL. So every handler below does the two things that must
  // happen per event (preventDefault, dropEffect: they are what accepts the
  // drop and what the cursor reads) and then asks whether the pointer actually
  // moved before doing anything else at all.
  const lastOver = useRef({ x: -1, y: -1 });
  const pointerMoved = (e: React.DragEvent) => {
    if (e.clientX === lastOver.current.x && e.clientY === lastOver.current.y) return false;
    lastOver.current.x = e.clientX;
    lastOver.current.y = e.clientY;
    return true;
  };
  const setRootDropHovered = (on: boolean) => {
    if (rootDropHoverRef.current === on) return;
    rootDropHoverRef.current = on;
    setRootDropHover(on);
  };
  const setNewDropHovered = (on: boolean) => {
    if (newDropHoverRef.current === on) return;
    newDropHoverRef.current = on;
    setNewDropHover(on);
  };
  // A GROUP DRAG IS A MOVE. It used to be two: a row grew a "duplicate" pill
  // while something was dragged over it, and Shift forced the same thing
  // where the browser reported the key (Safari reports nothing mid-drag,
  // which is why the pill existed at all). Both are gone — duplicating is
  // the context menu's **Duplicate**, which works the same in every browser
  // and needs no second target inside the row it is aimed at. What the pill
  // cost while it was there is the row itself: it appeared exactly where the
  // count and the row actions are, so hovering a group to drop INTO it
  // rearranged the thing being aimed at.

  const refreshTree = () => {
    // Reparenting/duplication/deletion changes group counts AND which items fall
    // under a selected ancestor group, so refresh both queries.
    qc.invalidateQueries({ queryKey: ["groups"] });
    qc.invalidateQueries({ queryKey: ["items"] });
  };

  // WHICH ROW IS BEING RENAMED WHERE IT STANDS. A group's name is one line,
  // and the only way to change it was a dialog over the tree with four other
  // fields in it — so the row takes the edit itself, with ✓ and ✕ beside the
  // field (Enter and Escape do the same, but a gesture that only exists on
  // the keyboard is one half the people using it never find). The full
  // editor — icon, colour, rule, parent — is still the menu's **Edit group**.
  const [renaming, setRenaming] = useState<number | null>(null);
  const commitRename = async (id: number, name: string) => {
    setRenaming(null);
    await api.updateGroup(id, { name });
    refreshTree();
  };
  // A NEW GROUP INSIDE THIS ONE: made empty, on the spot, and named in place.
  // The creator dialog is what the sidebar's own New group button opens and
  // what every seeded creation goes through (a rule, members, child groups);
  // an empty child of the group you just pointed at needs none of it, and the
  // one thing it does need — a name — the row can take.
  const newChildGroup = async (parentId: number) => {
    const g = await api.createGroup({ name: t("New group"), parent_id: parentId });
    setGroupsExpanded([parentId], true);
    await qc.invalidateQueries({ queryKey: ["groups"] });
    setSelectedGroups([g.id]);
    setRenaming(g.id);
  };

  // A drag cancelled with Escape (or dropped on an invalid target) fires no
  // dragleave/drop on the hovered row, so its highlight would stay stuck. The
  // `dragend` event always fires on the drag source when the gesture ends —
  // including on cancel — and bubbles to the window, so clear every drag
  // highlight there (covers both grid-image drags and internal group drags).
  useDragEndReset(() => {
    setItemDropTarget(null);
    setDropTarget(null);
    setDragId(null);
    setDragPath(null);
    setItemDragCount(null);
    setNewDropHovered(false);
  });
  useEffect(() => {
    // A grid drag is announced ONCE, here: its dragstart bubbles to the window
    // after React has run the grid's own handler, so by then the payload is
    // set and `dragState` knows how many images are being carried.
    const start = (e: DragEvent) => {
      const types = e.dataTransfer?.types;
      if (types && Array.from(types).includes("application/x-mc-items")) {
        setItemDragCount(getDraggedItems().length);
      }
    };
    window.addEventListener("dragstart", start);
    return () => window.removeEventListener("dragstart", start);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Apply the drag drop to every group being dragged. Chunk size 1 keeps the
  // requests sequential so the writes don't race on the single SQLite
  // connection.
  /** DUPLICATE — a copy of the group beside the original, subtree, items and
   *  granted tags and all. It used to be a drop zone inside the row a drag
   *  was aimed at (and a Shift the browser did not always report); as a menu
   *  row it says what it does, works in every browser, and needs no second
   *  target hidden in the row it would be dropped on.
   *
   *  Into the SAME parent, which is what "duplicate" means everywhere else in
   *  this app: a copy of the thing where the thing is. The name is made
   *  unique among its new siblings by the server, so the copy arrives as
   *  "Trips 2" rather than as a second row nobody can tell apart. */
  const duplicateGroups = useMutation({
    mutationFn: async (v: { ids: number[] }) => {
      const parentOf = new Map<number, number | null>();
      const walk = (nodes: GroupNode[], parent: number | null) => {
        for (const g of nodes) {
          parentOf.set(g.id, parent);
          walk(g.children ?? [], g.id);
        }
      };
      walk(tree ?? [], null);
      await runBulk(v.ids,
        (id) => api.duplicateGroup(id, parentOf.get(id) ?? null),
        { chunk: 1 });
    },
    onSuccess: refreshTree,
  });

  const applyDrop = useMutation({
    mutationFn: async (v: { ids: number[]; parent: number | null }) => {
      await runBulk(v.ids, (id) => api.moveGroup(id, v.parent), { chunk: 1 });
    },
    onSuccess: refreshTree,
  });
  //: A MOVE IS OFFERED BACK (owner 2026-09): dropping groups onto another
  //  re-nests a whole branch in one gesture, and a drop that landed one row
  //  off had no way back but the History tab. The sidebar's own undo bar
  //  (`useUndoBar`, the watermark rule) wraps the move and the toast below
  //  carries Undo / Redo, as the Faces tab's does.
  const undo = useUndoBar("groups", refreshTree);

  // Create a new group. If exactly one group is selected it becomes the parent
  // (and is expanded); otherwise the new group is created at the top level. The
  // group editor opens immediately so the user can name/style it.
  // ---- the New group button's menu ----------------------------------------
  //
  // With items in the grid the button offers what the group should START
  // with: nothing, everything the grid is showing, or the grid selection.
  // With an empty grid there is only one answer, so no menu — the button
  // creates the empty group directly, as it always did.
  //
  // "The current items" is the VIEW, which can be the whole library — so it
  // travels as a SCOPE (`api.assignGroupView`), the same shape quick-tagging
  // with nothing selected uses, and the server resolves it through the same
  // search the grid pages through. The selection is ids and goes through the
  // same bulk membership the drag-onto-a-group path uses.
  const [newMenu, setNewMenu] = useState(false);
  const newGroupBtn = useRef<HTMLButtonElement>(null);
  const newMenuRef = useRef<HTMLDivElement>(null);
  const newMenuRect = useAnchorRect(newGroupBtn, newMenu);
  // Read under the grid's own page-1 query key, so with a grid on screen this
  // costs nothing and cannot disagree with it about what the view is.
  const view = useViewScope();

  useMenuDismiss(newMenu, () => setNewMenu(false), { within: [newMenuRef, newGroupBtn] });

  // NOTHING IS CREATED FROM THE MENU. Every entry opens the group dialog in
  // CREATE mode with a seed — what the entry means, captured at the click —
  // and only the dialog's Create makes the group; Cancel makes nothing. The
  // menu used to create first and edit after, which left a "New Group" in
  // the tree for every Cancel.
  const openGroupCreator = useUI((s) => s.openGroupCreator);
  const createFrom = (src: "empty" | "view" | "selection") => {
    setNewMenu(false);
    const parent = selectedGroups.length === 1 ? selectedGroups[0] : null;
    openGroupCreator({
      smart: false, smartQuery: "", parent,
      members: src === "selection" ? { ids: [...selectedItems] }
        : src === "view" ? { view: { ...view.req } } : null,
    });
  };

  // The empty-space drop: the same creator, seeded with the images that were
  // dropped — nothing is made until its Create button, exactly as the add
  // menu's entries. The parent is null whatever is selected, because the row
  // sits at the ROOT of the tree: the gesture says "a new group here", not
  // "one inside that one".
  const dropNewGroup = (e: React.DragEvent) => {
    setItemDragCount(null);
    setNewDropHovered(false);
    const ids = itemDragIds(e);
    if (!ids.length) return;
    openGroupCreator({ smart: false, smartQuery: "", parent: null,
                       members: { ids } });
  };

  // SMART creation is its own pair of entries: born smart (the identity is
  // fixed at creation), with an empty rule to fill in, or seeded from the
  // VIEW the grid is running right now — the typed search plus the sidebar's
  // filters, composed by `composeViewQuery` so the rule means what the grid
  // was showing rather than the search alone.
  const librarySearch = useUI((s) => s.search);
  const untaggedView = useUI((s) => s.untagged);
  const createSmart = (query: string) => {
    setNewMenu(false);
    const parent = selectedGroups.length === 1 ? selectedGroups[0] : null;
    openGroupCreator({ smart: true, smartQuery: query, parent,
                       members: null });
  };

  const onNewGroup = () => {
    // Always a menu now: the smart entries mean there is never just one
    // answer, even over an empty grid.
    setNewMenu((v) => !v);
  };

  // Assign a set of images (dragged from the grid) to a group — one bulk
  // request per (up to) 1000 items, sequential so the writes don't race on
  // the single SQLite connection. The server logs the same per-item events
  // the single endpoint does, so History and revert are unchanged.
  const assignItemsToGroup = useMutation({
    mutationFn: async (v: { ids: number[]; group: number }) => {
      await runBulk(chunks(v.ids, 1000),
                    (ids) => api.bulkGroupMembership(ids, [v.group], []),
                    { chunk: 1 });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["groups"] });
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["item"] });
    },
  });

  // True when a drag carries images from the grid (vs. an internal group drag).
  // Only the DROP asks this — once per gesture. The per-event path reads
  // `itemDragCount`, which was settled at dragstart.
  const isItemDrag = (e: React.DragEvent) =>
    Array.from(e.dataTransfer.types).includes("application/x-mc-items");

  // The dropped item ids, or [] for a payload that is missing or malformed.
  const itemDragIds = (e: React.DragEvent): number[] => {
    const raw = e.dataTransfer.getData("application/x-mc-items");
    if (!raw) return [];
    try {
      const ids = JSON.parse(raw);
      return Array.isArray(ids) ? ids : [];
    } catch {
      return [];
    }
  };

  const dropItemsOn = async (e: React.DragEvent, groupId: number) => {
    setItemDropTarget(null);
    const ids = itemDragIds(e);
    if (ids.length) {
      // A drop can carry the whole grid selection; past a thousand items it is
      // worth a question before a thousand writes.
      if (ids.length > BIG_EDIT && !(await confirm({
        title: t("Add {n} items to this group?", { n: String(ids.length) }),
        answer: { label: t("Add") } }))) return;
      assignItemsToGroup.mutate({ ids, group: groupId });
      if (!expanded[groupId]) toggleGroupExpanded(groupId);
    }
  };

  const deleteGroups = useMutation({
    mutationFn: async ({ ids, assignTags, keepChildren }: {
      ids: number[]; assignTags: boolean; keepChildren?: boolean;
    }) => {
      for (const id of ids) await api.deleteGroup(id, assignTags, keepChildren);
    },
    onSuccess: () => {
      clearGroupSelection();
      refreshTree();
      // Baking group tags onto items changes item tags/facets.
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["item"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
    },
  });

  const mergeGroups = useMutation({
    mutationFn: ({ dest, sources }: { dest: number; sources: number[] }) =>
      api.mergeGroups(dest, sources),
    // THE DESTINATION IS SELECTED AFTERWARDS, not nothing. Every source row
    // has just been deleted, so the selection cannot survive as it was — and
    // clearing it left the view on the whole library at the moment somebody
    // had gathered several groups into one, which is the group they are
    // looking at. It is the one row the merge leaves standing.
    onSuccess: (_data, { dest }) => {
      setSelectedGroups([dest]);
      refreshTree();
      // Memberships moved, so anything counting them is stale.
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["item"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
    },
  });

  // Collect every node (flattened) so a delete can inspect a group's tags.
  const allNodes = useMemo(() => {
    const out: GroupNode[] = [];
    const walk = (ns: GroupNode[]) => ns.forEach((n) => { out.push(n); walk(n.children ?? []); });
    walk(tree ?? []);
    return out;
  }, [tree]);
  // A GROUP IS NAMED BY ITS FULL PATH (owner 2026-09, `grouppath`): a bare
  // name is the root-level group of that name, so a picked "abc" under
  // "foo" has to be written `foo/abc` or the query means the other one.
  const pathById = useMemo(() => {
    const out = new Map<number, string>();
    const walk = (ns: GroupNode[], prefix: string) => ns.forEach((n) => {
      const p = prefix ? `${prefix}/${n.name}` : n.name;
      out.set(n.id, p);
      walk(n.children ?? [], p);
    });
    walk(tree ?? [], "");
    return out;
  }, [tree]);
  const viewQuery = useMemo(() => composeViewQuery({
    search: librarySearch,
    mediaKinds: sequenceView != null ? [] : mediaKinds,
    untagged: untaggedView,
    groupNames: selectedGroups.map((id) => pathById.get(id) ?? "").filter(Boolean),
  }), [librarySearch, mediaKinds, untaggedView, selectedGroups, pathById,
       sequenceView]);
  // Ask (only when tags are involved) whether to bake the groups' tags onto their
  // items before deletion, so the items keep the tags they were inheriting.
  // Every group that is going, not only the ones that were picked: a
  // deletion takes the subtree now, so a CHILD's granted tags are as much at
  // stake as its parent's and the question has to count them.
  const withDescendants = (nodes: GroupNode[]): GroupNode[] => {
    const out: GroupNode[] = [];
    const seen = new Set<number>();
    const walk = (ns: GroupNode[]) => {
      for (const n of ns) {
        if (seen.has(n.id)) continue;
        seen.add(n.id);
        out.push(n);
        walk(n.children ?? []);
      }
    };
    walk(nodes);
    return out;
  };
  /** Whether to bake the groups' tags onto their items before the delete:
   *  true, false, or null when the sheet was cancelled (the delete is off). */
  const askAssignTags = async (picked: GroupNode[]): Promise<boolean | null> => {
    const nodes = withDescendants(picked);
    const tagged = nodes.filter((n) => (n.tags?.length ?? 0) > 0);
    if (tagged.length === 0) return false;
    const total = tagged.reduce((sum, n) => sum + (n.tags?.length ?? 0), 0);
    const which = tagged.length === 1
      ? tn({ one: "“{name}” assigns 1 tag",
             other: "“{name}” assigns {n} tags" }, total,
           { name: tagged[0].name })
      : tn({ one: "{groups} of these groups assign 1 tag",
             other: "{groups} of these groups assign {n} tags" }, total,
           { groups: tagged.length });
    const r = await ask({
      title: t("{which} to their items. Assign those tags directly to the items before deleting, so they aren't lost?", { which }),
      plain: { label: t("Delete without assigning"), danger: true },
      answer: { label: t("Assign, then delete") },
    });
    return r === null ? null : r === "answer";
  };

  const doDelete = async () => {
    const n = selectedGroups.length;
    if (n === 0) return;
    if (!(await confirm({
      title: tn({ one: "Delete 1 group and everything inside it?",
                  other: "Delete {n} groups and everything inside them?" }, n),
      body: t("The items stay in the library."),
      answer: { label: t("Delete"), danger: true },
    }))) return;
    const nodes = allNodes.filter((g) => selectedGroups.includes(g.id));
    const assignTags = await askAssignTags(nodes);
    if (assignTags == null) return;
    deleteGroups.mutate({ ids: selectedGroups, assignTags });
  };

  // Delete/Backspace removes the selected groups, unless the user is typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Not while the item window is over us (see `itemWindowIsOpen`).
      // …including a dialog: Delete here removes GROUPS, and it was doing
      // it through whatever was open on top.
      if (modalIsOpen()) return;
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      if (isTypingTarget(e)) return;
      if (selectedGroups.length === 0) return;
      e.preventDefault();
      doDelete();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGroups]);

  // Parent per group id. Subtree membership ("is this row under the dragged
  // group?") walks parents upward in O(depth) — the per-node descendant Sets
  // this replaces cost O(n²) memory/build on a big tree and were only ever
  // asked yes/no questions during a drag.
  const parentOf = useMemo(() => {
    const map = new Map<number, number | null>();
    const walk = (ns: GroupNode[], parent: number | null) => {
      for (const n of ns) {
        map.set(n.id, parent);
        walk(n.children ?? [], n.id);
      }
    };
    walk(tree ?? [], null);
    return map;
  }, [tree]);

  /** True when `id` is `root` or sits anywhere under it. */
  const isInSubtree = (id: number, root: number): boolean => {
    for (let cur: number | null | undefined = id; cur != null; cur = parentOf.get(cur)) {
      if (cur === root) return true;
    }
    return false;
  };

  /** The ids of a node's whole subtree (itself included) — used by Alt+click
   *  expand/collapse, computed on demand for the one node asked about. */
  const subtreeIds = (n: GroupNode): number[] => {
    const out: number[] = [];
    const walk = (x: GroupNode) => {
      out.push(x.id);
      (x.children ?? []).forEach(walk);
    };
    walk(n);
    return out;
  };

  // The groups a drag actually moves: if the grabbed group is part of the
  // current selection, drag the whole selection; otherwise just that one group
  // (even if others are selected).
  const draggedIds = (): number[] => {
    if (dragId === null) return [];
    return selectedGroups.includes(dragId) ? selectedGroups : [dragId];
  };

  const smartIds = useMemo(() => {
    const out = new Set<number>();
    const walk = (nodes: GroupNode[]) => {
      for (const n of nodes) {
        if (n.smart) out.add(n.id);
        walk(n.children);
      }
    };
    walk(tree ?? []);
    return out;
  }, [tree]);

  /** Is anything in the drag actually nested? A root group promoted to the
   *  root is a move that changes nothing, and a row offering it is noise. */
  const nestedDrag = dragId !== null
    && draggedIds().some((id) => parentOf.get(id) != null);

  const canDrop = (targetId: number) => {
    // A smart group cannot hold child groups (server-enforced too).
    if (smartIds.has(targetId)) return false;
    const ids = draggedIds();
    if (ids.length === 0 || ids.includes(targetId)) return false;
    return !ids.some((id) => isInSubtree(targetId, id));
  };

  const endDrag = () => {
    setDragId(null);
    setDragPath(null);
    setDropTarget(null);
    setRootDropHovered(false);
  };

  const drop = async (parent: number | null) => {
    const ids = draggedIds();
    if (ids.length === 0) return;
    if (parent !== null && !canDrop(parent)) return endDrag();
    if (ids.length > BIG_EDIT && !(await confirm({
      title: t("Move {n} groups?", { n: String(ids.length) }),
      answer: { label: t("Move") } }))) return endDrag();
    void undo.run(tn({ one: "Moved 1 group", other: "Moved {n} groups" }, ids.length),
                  () => applyDrop.mutateAsync({ ids, parent }));
    if (parent !== null && !expanded[parent]) toggleGroupExpanded(parent);
    endDrag();
  };

  // NARROWING the tree, not the selection: the filter decides which rows
  // are drawn and nothing else — a selected group filtered out of sight
  // stays selected, exactly as a scrolled-away one does.
  const [groupFilter, setGroupFilter] = useState("");
  const filterNeedle = groupFilter.trim().toLowerCase();
  // Which groups a filtered tree KEEPS: every match, and every ancestor of
  // one (a match deep in a branch needs its path to hang from).
  const filterKeep = useMemo(() => {
    if (!filterNeedle || !tree) return null;
    const keep = new Set<number>();
    const walk = (nodes: GroupNode[], trail: number[]) => {
      for (const n of nodes) {
        if (n.name.toLowerCase().includes(filterNeedle)) {
          keep.add(n.id);
          for (const a of trail) keep.add(a);
        }
        walk(n.children ?? [], [...trail, n.id]);
      }
    };
    walk(tree, []);
    return keep;
  }, [filterNeedle, tree]);

  const rows = useMemo(() => {
    const out: FlatRow[] = [];
    const walk = (nodes: GroupNode[], depth: number, prefix: string) => {
      for (const n of [...nodes].sort((a, b) => a.name.localeCompare(b.name))) {
        if (filterKeep && !filterKeep.has(n.id)) continue;
        const hasChildren = n.children.length > 0;
        // While filtering, a branch holding a match is FORCED open — the
        // match is what was asked for, and a collapsed ancestor would hide
        // it. The stored expansion is untouched.
        const isOpen = filterKeep ? true : !!expanded[n.id];
        const path = `${prefix}/${n.id}`;
        out.push({ node: n, depth, hasChildren, isOpen, path });
        if (hasChildren && isOpen) walk(n.children, depth + 1, path);
      }
    };
    if (tree) walk(tree, 0, "");
    return out;
  }, [tree, expanded, filterKeep]);

  // Windowed tree rows: thousands of groups mount only a viewport's worth.
  // Rows are a fixed 30 px, so the arithmetic is exact; small trees render
  // the plain flow.
  const treeScrollRef = useRef<HTMLDivElement>(null);
  const rowsWin = useWindowedList({
    count: rows.length, rowHeight: GROUP_ROW_H, scrollRef: treeScrollRef,
    minCount: 100,
  });

  // ---- revealing a group somebody asked for from elsewhere ---------------
  //
  // The right sidebar's Groups list says which groups a picture is in; its
  // "Select this group" sets the selection (which is the whole of what a
  // click on a row here does — the view follows it) and leaves the REVEALING
  // to this, because only the tree knows its own shape: which rows exist,
  // which branches are open, where the scroller is, and whether the filter
  // box is hiding the target.
  //
  // Two passes on purpose. Expanding the ancestors CHANGES `rows`, and the
  // target's row does not exist until that render has happened — so the
  // first pass opens the branch and returns, and the second finds the row,
  // scrolls to it and flashes it. `groupFocus` is cleared only once it has
  // landed; a stale id would flash a row the next time this tree rendered.
  const groupFocus = useUI((s) => s.groupFocus);
  const setGroupFocus = useUI((s) => s.setGroupFocus);
  const [flashGroup, setFlashGroup] = useState<number | null>(null);
  const flashTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(flashTimer.current), []);
  useEffect(() => {
    if (groupFocus == null || !tree) return;
    // The path of ancestors, root-first — and whether the group is in this
    // tree at all (a deleted one, or a stale id from another library).
    const trail: number[] = [];
    const find = (nodes: GroupNode[], acc: number[]): number[] | null => {
      for (const n of nodes) {
        if (n.id === groupFocus) return acc;
        const deeper = find(n.children ?? [], [...acc, n.id]);
        if (deeper) return deeper;
      }
      return null;
    };
    const found = find(tree, trail);
    if (!found) { setGroupFocus(null); return; }
    // A filter narrowing the tree past the target would leave nothing to
    // scroll to. Clearing it is what the jump means — the same rule the Tags
    // tab follows when it unfolds a collapsed namespace to land in it.
    if (filterKeep && !filterKeep.has(groupFocus)) { setGroupFilter(""); return; }
    const shut = found.filter((id) => !expanded[id]);
    if (shut.length) { setGroupsExpanded(shut, true); return; }
    const idx = rows.findIndex((r) => r.node.id === groupFocus);
    if (idx < 0) return;
    if (rowsWin.windowed) rowsWin.scrollToIndex(idx);
    const aim = () => document
      .querySelector(`[data-grouprow="${groupFocus}"]`)
      ?.scrollIntoView({ block: "nearest" });
    aim();
    requestAnimationFrame(aim);
    // Off and on across a frame, or asking for the SAME group twice leaves
    // the class where it is and the animation never restarts.
    setFlashGroup(null);
    requestAnimationFrame(() => setFlashGroup(groupFocus));
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlashGroup(null), 1800);
    setGroupFocus(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupFocus, tree, expanded, rows, filterKeep]);

  // Selection with file-manager semantics — the one click rule
  // (`shared/pickList.ts`) over the visible rows: plain = single (and the
  // only picked row, clicked again, is put down), cmd/ctrl = toggle, shift =
  // the run from the anchor.
  const selectRow = (id: number, e: React.MouseEvent) => {
    const order = rows.map((r) => r.node.id);
    const r = pickNext(selectedGroups, id, { meta: e.metaKey || e.ctrlKey, shift: e.shiftKey },
                       order, anchorRef.current);
    anchorRef.current = r.anchor;
    setSelectedGroups(r.next);
  };

  // ---- right-click on a group ---------------------------------------------
  //
  // The row's own ⋯ button opens THIS menu, so there is one list of what a
  // group can be asked rather than two glyphs on the row and the rest behind
  // a right-click nobody is told about.
  //
  // Right-clicking a row that is NOT selected acts on that row alone and
  // leaves the selection where it is — the grid's context-menu rule, and the
  // one that stops a right-click quietly re-aiming a Delete.
  const [menu, setMenu] = useState<{ x: number; y: number; ids: number[];
    /** WHICH row was right-clicked. The menu usually acts on the whole
     *  selection, but merging has to know which of them survives — and the
     *  answer a person expects is the row they pointed at. */
    clicked?: number; special?: SpecialScope } | null>(null);
  // What the menu's last run queued — said here, since the menu closes on
  // the pick and the server answers after. Information, not an undo, so it
  // goes away by itself.
  const [queueNote, setQueueNote] = useState<string | null>(null);
  useEffect(() => {
    if (!queueNote) return;
    const id = setTimeout(() => setQueueNote(null), 5000);
    return () => clearTimeout(id);
  }, [queueNote]);
  /** Right-click on one of the FIXED entries: open the same menu the groups
   *  get, aimed at that row's scope (resolved server-side, like a group's
   *  subtree — see `EnqueueScope.view`). */
  const openSpecialMenu = (e: React.MouseEvent, special: SpecialScope) => {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ x: e.clientX, y: e.clientY, ids: [], special });
  };
  const openMenu = (id: number, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ x: e.clientX, y: e.clientY, clicked: id,
              ids: selectedGroups.includes(id) ? selectedGroups : [id] });
  };

  return (
    <div
      style={{
        background: "var(--panel)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      <div
        style={{
          height: 40,
          flex: "0 0 40px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 10px 0 14px",
          borderBottom: "1px solid var(--border-soft)",
        }}
      >
        <SectionHeading>
          {t("Library")}
        </SectionHeading>
        <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
          <IconButton icon="create_new_folder" size={26} glyph={19} color={newMenu ? "var(--accent)" : "var(--text-3)"} active={newMenu}
            ref={newGroupBtn}
            title={t("New group")}
            onClick={onNewGroup} />
          {newMenu && (
            <AnchoredDropdown rect={newMenuRect} minWidth={230}>
              <div ref={newMenuRef}>
                {([
                  { src: "empty" as const, icon: "create_new_folder",
                    label: "Empty group", count: null },
                  { src: "view" as const, icon: "grid_view",
                    label: "From the current items", count: view.total ?? 0 },
                  ...(selectedItems.length > 0
                    ? [{ src: "selection" as const, icon: "check_box",
                         label: "From the selection",
                         count: selectedItems.length }]
                    : []),
                  { src: "smart" as const, icon: "filter_alt",
                    label: "Smart group", count: null },
                  ...(viewQuery
                    ? [{ src: "smart-search" as const, icon: "filter_alt",
                         label: "Smart group from this search", count: null }]
                    : []),
                ]).map((o) => (
                  <div
                    key={o.src}
                    className="hoverable"
                    onClick={() => o.src === "smart" ? createSmart("")
                      : o.src === "smart-search" ? createSmart(viewQuery)
                      : createFrom(o.src)}
                    style={{
                      display: "flex", alignItems: "center", gap: 8,
                      padding: "7px 10px", borderRadius: "var(--r-2)", cursor: "pointer",
                      fontSize: "var(--fs-3)", color: "var(--text-2)", whiteSpace: "nowrap",
                    }}
                  >
                    <Icon name={o.icon} size={16} color="var(--muted)" />
                    <span style={{ flex: 1 }}>{t(o.label)}</span>
                    {o.count != null && (
                      <Count n={o.count} />
                    )}
                  </div>
                ))}
              </div>
            </AnchoredDropdown>
          )}
          <IconButton icon="upload" size={26} glyph={19} tone="text"
            title={t("Import files")}
            onClick={() => setOverlay("import")} />
        </div>
      </div>

      <div
        ref={treeScrollRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: 6,
          // Without this, Shift+mousedown starts a text selection (esp. Safari)
          // and the drag never begins.
          userSelect: "none",
          WebkitUserSelect: "none",
        }}
      >
        {/* All Items — resets to the full library (and clears any kind filter);
            also the drop zone for promoting a dragged group to the top level. Its
            Images / Videos / Sequences children are kind sub-filters. */}
        <div
          className="hoverable"
          onClick={() => showAllItems()}
          onContextMenu={(e) => openSpecialMenu(e, {
            view: "all", label: t("All Items"),
            count: stats?.items ?? null })}
          onDragOver={(e) => {
            if (dragId === null) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            if (!pointerMoved(e)) return;
            if (dropTarget !== "root") setDropTarget("root");
          }}
          onDragLeave={(e) => {
            if (dropTarget === "root" && e.currentTarget === e.target) setDropTarget(null);
          }}
          onDrop={(e) => {
            e.preventDefault();
            drop(null);
          }}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            height: 30,
            padding: "0 6px",
            borderRadius: "var(--r-3)",
            cursor: "pointer",
            fontSize: "var(--fs-3)",
            marginBottom: 2,
            color: allItemsActive ? "var(--selected-text)" : "var(--text-2)",
            background:
              dropTarget === "root"
                ? "var(--accent-dim)"
                : allItemsActive ? "var(--accent-dim)" : "transparent",
            outline: dropTarget === "root" ? "1px solid var(--accent)" : "none",
            outlineOffset: -1,
            fontWeight: allItemsActive ? 600 : 400,
          }}
        >
          <span
            onClick={(e) => { e.stopPropagation(); toggleKindsOpen(); }}
            title={kindsOpen ? "Collapse" : "Expand"}
            style={{ width: 16, flex: "0 0 16px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted-2)" }}
          >
            <Icon name={kindsOpen ? "expand_more" : "chevron_right"} size={18} />
          </span>
          <Icon
            name="inbox"
            size={18}
            color={allItemsActive ? "var(--accent)" : "var(--muted)"}
          />
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {t("All Items")}
          </span>
          {stats?.items != null && stats.items > 0 && (
            <Count n={stats.items} pad />
          )}
        </div>

        {/* Kind sub-filters (children of All Items), indented + collapsible. */}
        {kindsOpen && KIND_CHILDREN.map((c) => {
          const active = kindActive(c.kind);
          const count =
            c.kind === "image" ? stats?.images ?? null
            : c.kind === "video" ? stats?.videos ?? null
            : sequences?.length ?? 0;
          return (
            <div
              key={c.kind}
              className="hoverable"
              onClick={() => showKind(c.kind)}
              // Every fixed row is a group in all but id — the actions menu
              // is offered where every group offers one, over that row's own
              // scope (resolved server-side, the grid's semantics).
              onContextMenu={(e) => openSpecialMenu(e, {
                view: c.kind, label: t(c.label), count })}
              style={{
                display: "flex", alignItems: "center", gap: 4, height: 30,
                // Indent to match a depth-1 group row (6 + 1*12 left pad, plus the
                // hidden 16px chevron gutter groups reserve).
                padding: "0 6px 0 18px", borderRadius: "var(--r-3)", cursor: "pointer",
                fontSize: "var(--fs-3)", marginBottom: 1,
                color: active ? "var(--selected-text)" : "var(--text-2)",
                background: rowBackground(active, "transparent"),
                fontWeight: active ? 600 : 400,
              }}
            >
              <span style={{ width: 16, flex: "0 0 16px" }} />
              <Icon name={c.icon} size={18} color={active ? "var(--accent)" : "var(--muted)"} />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {t(c.label)}
              </span>
              {count != null && count > 0 && (
                <Count n={count} size={10} pad />
              )}
            </div>
          );
        })}

        {/* Pending — items with unapproved AI tags/captions. A collapsible child
            of All Items (between Sequences and Ungrouped), shown only while some
            exist. Its Tags / Captions subgroups appear beneath when expanded. */}
        {kindsOpen && (stats?.pending ?? 0) > 0 && (() => {
          const wholeActive = pendingView && pendingKind == null;
          const subs = [
            { kind: "tags" as const, label: "Tags", icon: "sell", count: stats?.pending_tags ?? 0 },
            { kind: "captions" as const, label: "Captions", icon: "notes", count: stats?.pending_captions ?? 0 },
            // A face a detector named by itself: reviewing it means looking at
            // a crop and saying who that is, which is not the same job as
            // reading a list of guessed labels.
            { kind: "faces" as const, label: "Faces", icon: "face", count: stats?.pending_faces ?? 0 },
          ].filter((sub) => sub.count > 0);
          return (
            <>
              <div
                className="hoverable"
                onClick={() => showPending()}
                onContextMenu={(e) => openSpecialMenu(e, {
                  view: "pending", label: t("Pending"),
                  count: stats?.pending ?? null })}
                title="Items with machine-generated tags or captions awaiting your review"
                style={{
                  display: "flex", alignItems: "center", gap: 4, height: 30,
                  padding: "0 6px 0 18px", borderRadius: "var(--r-3)", cursor: "pointer", fontSize: "var(--fs-3)",
                  marginBottom: 1,
                  color: wholeActive ? "var(--selected-text)" : "var(--text-2)",
                  background: rowBackground(wholeActive, "transparent"),
                  fontWeight: wholeActive ? 600 : 400,
                }}
              >
                {subs.length > 0 ? (
                  <span
                    onClick={(e) => { e.stopPropagation(); togglePendingOpen(); }}
                    title={pendingOpen ? "Collapse" : "Expand"}
                    style={{ width: 16, flex: "0 0 16px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted-2)" }}
                  >
                    <Icon name={pendingOpen ? "expand_more" : "chevron_right"} size={18} />
                  </span>
                ) : (
                  <span style={{ width: 16, flex: "0 0 16px" }} />
                )}
                <Icon name="auto_awesome" size={18} color={pendingView ? "var(--accent)" : "var(--muted)"} />
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {t("Pending")}
                </span>
                <Count n={stats?.pending ?? 0} pad />
              </div>
              {pendingOpen && subs.map((sub) => {
                const active = pendingView && pendingKind === sub.kind;
                return (
                  <div
                    key={sub.kind}
                    className="hoverable"
                    onClick={() => showPending(sub.kind)}
                    title={`Items with pending ${sub.label.toLowerCase()}`}
                    style={{
                      display: "flex", alignItems: "center", gap: 4, height: 30,
                      // Depth-2: indented under the Pending row.
                      padding: "0 6px 0 30px", borderRadius: "var(--r-3)", cursor: "pointer", fontSize: "var(--fs-3)",
                      marginBottom: 1,
                      color: active ? "var(--selected-text)" : "var(--text-2)",
                      background: rowBackground(active, "transparent"),
                      fontWeight: active ? 600 : 400,
                    }}
                  >
                    <span style={{ width: 16, flex: "0 0 16px" }} />
                    <Icon name={sub.icon} size={18} color={active ? "var(--accent)" : "var(--muted)"} />
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {t(sub.label)}
                    </span>
                    <Count n={sub.count} size={10} pad />
                  </div>
                );
              })}
            </>
          );
        })()}

        {/* Untagged — items with no tags. A child of All Items, indented +
            collapsible with the other kind sub-filters, sitting just above
            Ungrouped. */}
        {kindsOpen && (
          <div
            className="hoverable"
            onClick={() => showUntagged()}
            onContextMenu={(e) => openSpecialMenu(e, {
              view: "untagged", label: t("Untagged"),
              count: untaggedCount ?? null })}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              height: 30,
              padding: "0 6px 0 18px",
              borderRadius: "var(--r-3)",
              cursor: "pointer",
              fontSize: "var(--fs-3)",
              marginBottom: 1,
              color: untagged ? "var(--selected-text)" : "var(--text-2)",
              background: rowBackground(untagged, "transparent"),
              fontWeight: untagged ? 600 : 400,
            }}
          >
            <span style={{ width: 16, flex: "0 0 16px" }} />
            <Icon
              name="label_off"
              size={18}
              color={untagged ? "var(--accent)" : "var(--muted)"}
            />
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {t("Untagged")}
            </span>
            {untaggedCount > 0 && (
              <Count n={untaggedCount} size={10} pad />
            )}
          </div>
        )}

        {/* Ungrouped — items with no group assigned. A child of All Items,
            indented + collapsible with the other kind sub-filters. */}
        {kindsOpen && (
          <div
            className="hoverable"
            onClick={() => showUngrouped()}
            onContextMenu={(e) => openSpecialMenu(e, {
              view: "ungrouped", label: t("Ungrouped"),
              count: ungroupedCount ?? null })}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              height: 30,
              padding: "0 6px 0 18px",
              borderRadius: "var(--r-3)",
              cursor: "pointer",
              fontSize: "var(--fs-3)",
              marginBottom: 1,
              color: ungrouped ? "var(--selected-text)" : "var(--text-2)",
              background: rowBackground(ungrouped, "transparent"),
              fontWeight: ungrouped ? 600 : 400,
            }}
          >
            <span style={{ width: 16, flex: "0 0 16px" }} />
            <Icon
              name="folder_off"
              size={18}
              color={ungrouped ? "var(--accent)" : "var(--muted)"}
            />
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {t("Ungrouped")}
            </span>
            {ungroupedCount > 0 && (
              <Count n={ungroupedCount} size={10} pad />
            )}
          </div>
        )}

        {/* RANKINGS — an axis you rated pictures on, and what it made of
            them. Between Ungrouped and Hidden: Hidden and Trash are the two
            "set aside" rows and stay adjacent at the bottom.

            A ranking is a WAY OF LOOKING AT THE LIBRARY. Since rung v31 it
            mints no tags and its standings are fitted on read, so the order
            it produces had nowhere to be seen except a histogram on a page
            of its own; picking a row here makes the GRID that order.

            Shown only while there is one — the count conditional Hidden,
            Trash and Pending already use — and the parent row scopes to
            every placed picture across all of them, which is the same thing
            picking several does, so no row in this column is inert. */}
        <RankingRows />

        {/* Hidden — items excluded from the grid/counts; only shown when some
            exist. Sits just above the Trash. */}
        {(stats?.hidden ?? 0) > 0 && (
          <div
            className="hoverable"
            onClick={() => showHidden()}
            onContextMenu={(e) => openSpecialMenu(e, {
              view: "hidden", label: t("Hidden"),
              count: stats?.hidden ?? null })}
            style={{
              display: "flex", alignItems: "center", gap: 4, height: 30,
              padding: "0 6px", borderRadius: "var(--r-3)", cursor: "pointer", fontSize: "var(--fs-3)",
              marginTop: 4,
              color: hiddenView ? "var(--selected-text)" : "var(--text-2)",
              background: rowBackground(hiddenView, "transparent"),
              fontWeight: hiddenView ? 600 : 400,
            }}
          >
            <span style={{ width: 16, flex: "0 0 16px" }} />
            <Icon name="visibility_off" size={18} color={hiddenView ? "var(--accent)" : "var(--muted)"} />
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {t("Hidden")}
            </span>
            <Count n={stats?.hidden ?? 0} pad />
          </div>
        )}

        {/* Trash — soft-deleted items, restorable from the properties panel.
            Hidden while empty (it reappears as soon as an item is trashed), but
            kept visible while the Trash view is open so it doesn't vanish mid-use
            after the last item is restored or permanently deleted. */}
        {(trashCount > 0 || trashView) && (
        <div
          className="hoverable"
          onClick={() => showTrash()}
          onContextMenu={(e) => openSpecialMenu(e, {
            trash: true, label: t("Trash"), count: trashCount })}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            height: 30,
            padding: "0 6px",
            borderRadius: "var(--r-3)",
            cursor: "pointer",
            fontSize: "var(--fs-3)",
            marginTop: 4,
            marginBottom: 4,
            color: trashView ? "var(--selected-text)" : "var(--text-2)",
            background: rowBackground(trashView, "transparent"),
            fontWeight: trashView ? 600 : 400,
          }}
        >
          <span style={{ width: 16, flex: "0 0 16px" }} />
          <Icon
            name="delete"
            size={18}
            color={trashView ? "var(--accent)" : "var(--muted)"}
          />
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {t("Trash")}
          </span>
          {trashCount > 0 && (
            <Count n={trashCount} pad />
          )}
        </div>
        )}

        {/* Divider separating the fixed All Items / Ungrouped rows from the
            user's group tree below. */}
        <div style={{ height: 1, background: "var(--border-soft)", margin: "4px 4px 6px" }} />

        {/* Narrow the TREE — never the selection. Only with a group to
            narrow: over an empty tree it is a field about nothing. */}
        {(tree?.length ?? 0) > 0 && (
          <SearchField size="sm" value={groupFilter} onChange={setGroupFilter} placeholder={t("Filter groups")}
                       clearTitle={t("Clear")} style={{ margin: "0 4px 6px" }} />
        )}

        <div
          ref={rowsWin.containerRef}
          style={rowsWin.windowed
            ? { height: rowsWin.totalHeight, position: "relative" }
            : undefined}
        >
        <div style={rowsWin.windowed
          ? { position: "absolute", top: rowsWin.topOffset, left: 0, right: 0 }
          : undefined}
        >
        {rows.slice(rowsWin.start, rowsWin.end).map(({ node, depth, hasChildren, isOpen, path }, j) => {
          const i = rowsWin.start + j;
          const selected = selectedGroups.includes(node.id);
          const isDropTarget = dropTarget === path;
          const isItemDropTarget = itemDropTarget === path;
          const droppable = canDrop(node.id);
          // System-tooltip text for the tag icon: positive then negative tags.
          // Guard against an older backend that omits `tags` (avoids a crash).
          const nodeTags = node.tags ?? [];
          const tagTitle = (() => {
            const pos = nodeTags.filter((t) => !t.negative).map((t) => t.name);
            const neg = nodeTags.filter((t) => t.negative).map((t) => t.name);
            const parts: string[] = [];
            if (pos.length) parts.push(`Assigns ${pos.join(", ")}`);
            if (neg.length) parts.push(`Removes ${neg.join(", ")}`);
            return parts.join(" · ");
          })();
          // Round only the outer edges of a contiguous run of selected rows, so
          // adjacent selections read as one block instead of separate pills.
          const prevSel = i > 0 && selectedGroups.includes(rows[i - 1].node.id);
          const nextSel =
            i < rows.length - 1 &&
            selectedGroups.includes(rows[i + 1].node.id);
          const radius =
            selected && !isDropTarget
              ? `${prevSel ? 0 : 7}px ${prevSel ? 0 : 7}px ` +
                `${nextSel ? 0 : 7}px ${nextSel ? 0 : 7}px`
              : "7px";
          // Dim the grabbed row, plus the rest of the selection when the grabbed
          // group is itself selected (so a multi-drag reads as one gesture).
          const dragging =
            dragPath === path ||
            (dragId !== null && selectedGroups.includes(dragId) && selected);
          return (
            <div
              key={path}
              data-grouprow={node.id}
              className={flashGroup === node.id ? "hoverable mc-flash" : "hoverable"}
              // A row that takes dropped images says so, and `tokens.css` then
              // lets the BROWSER light it under the pointer (see the
              // `mc-dragging-items` rule). A smart group takes no drops, so it
              // carries no marker and stays unlit.
              data-itemdrop={node.smart ? undefined : "1"}
              // A row being renamed is a form: it does not drag (a press in
              // the field would start one) and its click does not re-pick.
              draggable={renaming !== node.id}
              onDragStart={(e) => {
                setDragId(node.id);
                setDragPath(path);
                e.dataTransfer.effectAllowed = "copyMove";
                e.dataTransfer.setData("text/plain", String(node.id));
              }}
              onDragEnd={endDrag}
              onDragOver={(e) => {
                // `itemDragCount` already says whether this drag carries
                // images — read at dragstart, once — so the per-event path
                // never inspects `dataTransfer.types` (an allocation, 1400
                // times a second).
                if (itemDragCount !== null) {
                  // A SMART group takes no item drops — its search decides
                  // its members. No preventDefault is what makes the cursor
                  // say so (the pending-group rule).
                  if (node.smart) return;
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "copy";
                  if (!pointerMoved(e)) return;
                  if (itemDropTarget !== path) setItemDropTarget(path);
                  return;
                }
                // Over a non-droppable row (the dragged group itself or one of
                // its descendants): clear any stale highlight rather than leave
                // the previously-hovered row lit up.
                if (!droppable) {
                  if (dropTarget !== null) setDropTarget(null);
                  return;
                }
                e.preventDefault();
                if (!pointerMoved(e)) return;
                e.dataTransfer.dropEffect = "move";
                if (dropTarget !== path) setDropTarget(path);
              }}
              onDragLeave={(e) => {
                if (e.currentTarget !== e.target) return;
                if (itemDropTarget === path) setItemDropTarget(null);
                if (dropTarget === path) setDropTarget(null);
              }}
              onDrop={(e) => {
                if (isItemDrag(e)) {
                  if (node.smart) return;
                  e.preventDefault();
                  dropItemsOn(e, node.id);
                  return;
                }
                if (!droppable) return;
                e.preventDefault();
                drop(node.id);
              }}
              onClick={(e) => { if (renaming !== node.id) selectRow(node.id, e); }}
              onContextMenu={(e) => { if (renaming !== node.id) openMenu(node.id, e); }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 4,
                height: 30,
                padding: `0 2px 0 ${6 + depth * 12}px`,
                borderRadius: radius,
                cursor: "pointer",
                fontSize: "var(--fs-3)",
                opacity: dragging ? 0.4 : 1,
                color: selected ? "var(--selected-text)" : "var(--text-2)",
                background: isDropTarget || isItemDropTarget
                  ? "var(--accent-dim)"
                  : selected ? "var(--accent-dim)" : "transparent",
                outline: isDropTarget || isItemDropTarget ? "1px solid var(--accent)" : "none",
                outlineOffset: -1,
                fontWeight: selected ? 600 : 400,
              }}
            >
              <span
                title={hasChildren ? "Click to expand · Alt+click for the whole subtree" : undefined}
                onClick={(e) => {
                  e.stopPropagation();
                  // Alt+click expands/collapses this group and every descendant.
                  if (e.altKey) {
                    setGroupsExpanded(subtreeIds(node), !isOpen);
                  } else {
                    toggleGroupExpanded(node.id);
                  }
                }}
                style={{
                  width: 16,
                  flex: "0 0 16px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--muted-2)",
                  visibility: hasChildren ? "visible" : "hidden",
                  cursor: "pointer",
                }}
              >
                <Icon name={isOpen ? "expand_more" : "chevron_right"} size={18} />
              </span>
              <Icon
                name={node.icon}
                size={18}
                color={iconColor(node.icon, selected, node.color)}
              />
              {renaming === node.id ? (
                <InlineRename
                  value={node.name}
                  confirmTitle={t("Save the name")}
                  cancelTitle={t("Leave the name as it was")}
                  onCommit={(name) => void commitRename(node.id, name)}
                  onCancel={() => setRenaming(null)}
                />
              ) : (<>
              <span
                style={{
                  flex: 1,
                  minWidth: 0,
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {node.name}
                </span>
                {/* The smart marker sits OUTSIDE the truncating span, so the
                    kind stays readable however long the name is. */}
                {node.smart && (
                  <span
                    title="Smart group — its search decides the members"
                    style={{
                      flex: "0 0 auto",
                      display: "flex",
                      alignItems: "center",
                      color: selected ? "var(--accent)" : "var(--muted-2)",
                    }}
                  >
                    <Icon name="filter_alt" size={12} />
                  </span>
                )}
                {nodeTags.length > 0 && (
                  <span
                    title={tagTitle}
                    style={{
                      flex: "0 0 auto",
                      display: "flex",
                      alignItems: "center",
                      color: selected ? "var(--accent)" : "var(--muted-2)",
                    }}
                  >
                    <Icon name="sell" size={12} />
                  </span>
                )}
              </span>
              {/* The count and the row actions used to be swapped out for a
                  "duplicate" pill while something hovered the row — with the
                  pill gone there is nothing to make room for, so the row
                  stops rearranging itself under the drag. */}
              {(
                <>
                  {node.count > 0 && (
                    <Count n={node.count} pad className="row-count" />
                  )}
                  {/* ONE ⋯ opening the row's OWN context menu, rather than
                      an edit and a delete: that menu already holds both of
                      them and everything else a group can be asked — merge,
                      duplicate, delete keeping the children, the AI runs —
                      so the two glyphs were whichever pair had happened to
                      fit, in a 20px square each, with the rest reachable
                      only by knowing to right-click. */}
                  <span className="row-actions" style={{ flex: "0 0 auto", marginRight: 2 }}>
                    <IconButton icon="more_horiz" size={20} reveal="hover"
                      title={t("More actions")}
                      onClick={(e) => openMenu(node.id, e)} />
                  </span>
                </>
              )}
              </>)}
            </div>
          );
        })}
        </div>
        </div>

        {/* THE EMPTY SPACE UNDER THE TREE IS A DROP ZONE while images are
            dragged from the grid: a last row that makes a new group out of
            them. Dropping on a group row adds the items to a group that
            exists; there was no gesture for the other half of that sentence,
            and the space the tree leaves over is exactly where "not one of
            these" is aimed. It is a row in the flow rather than something
            pinned over the list, so it appears where the empty space begins —
            with a tree long enough to fill the pane there is no empty part and
            the row simply waits at the end of it. */}
        {/* …and while a GROUP is dragged, the same space takes it out to the
            top level. `nested` is the gate: a group already at the root has
            nowhere to be promoted to, so the row would be offering a move
            that changes nothing. */}
        {nestedDrag && (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
              if (!pointerMoved(e)) return;
                if (dropTarget !== "root") setDropTarget("root");
              setRootDropHovered(true);
            }}
            onDragLeave={() => {
              setRootDropHovered(false);
              if (dropTarget === "root") setDropTarget(null);
            }}
            onDrop={(e) => { e.preventDefault(); drop(null); }}
            style={{
              display: "flex", alignItems: "center", gap: 4, height: 30,
              boxSizing: "border-box", padding: "0 6px", marginTop: 4,
              borderRadius: "var(--r-3)", fontSize: "var(--fs-3)",
              border: `1px dashed ${rootDropHover ? "var(--accent)" : "var(--border-strong)"}`,
              background: rootDropHover ? "var(--accent-dim)" : "transparent",
              color: rootDropHover ? "var(--selected-text)" : "var(--text-3)",
              fontWeight: 400,
            }}
          >
            {/* Inert contents, for the reason the row above says: a dragleave
                fired by crossing onto the icon is one the row cannot tell
                from the pointer leaving. */}
            <div style={{
              display: "flex", alignItems: "center", gap: 4, flex: 1,
              minWidth: 0, pointerEvents: "none",
            }}>
              <span style={{ width: 16, flex: "0 0 16px" }} />
              <Icon name="drive_file_move_outline" size={18}
                    color={rootDropHover ? "var(--accent)" : "var(--muted-2)"} />
              <span style={{ flex: 1, overflow: "hidden",
                             textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {t("Move to the top level")}
              </span>
            </div>
          </div>
        )}
        {itemDragCount !== null && (
          <div
            data-itemdrop="1"
            onDragOver={(e) => {
              // preventDefault + dropEffect on every event (that is what makes
              // the row accept the drop and the cursor say so); everything
              // else only once the pointer has actually moved.
              e.preventDefault();
              e.dataTransfer.dropEffect = "copy";
              if (!pointerMoved(e)) return;
              setNewDropHovered(true);
            }}
            onDragLeave={() => setNewDropHovered(false)}
            onDrop={(e) => {
              e.preventDefault();
              dropNewGroup(e);
            }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              height: 30,
              boxSizing: "border-box",
              padding: "0 6px",
              marginTop: 4,
              borderRadius: "var(--r-3)",
              fontSize: "var(--fs-3)",
              border: `1px dashed ${newDropHover ? "var(--accent)" : "var(--border-strong)"}`,
              background: newDropHover ? "var(--accent-dim)" : "transparent",
              color: newDropHover ? "var(--selected-text)" : "var(--text-3)",
              // Colour and border only: a weight change re-shapes the text,
              // which is a LAYOUT for a row the pointer is crossing at speed.
              fontWeight: 400,
            }}
          >
            {/* The contents take no pointer, so every drag event over the row
                targets the ROW itself: crossing from its padding onto the icon
                or the label is what otherwise fires a dragleave the row cannot
                tell from the pointer actually leaving, and the highlight
                flickers once per crossing. */}
            <div style={{
              display: "flex", alignItems: "center", gap: 4, flex: 1,
              minWidth: 0, pointerEvents: "none",
            }}>
              <span style={{ width: 16, flex: "0 0 16px" }} />
              <Icon
                name="create_new_folder"
                size={18}
                color={newDropHover ? "var(--accent)" : "var(--muted-2)"}
              />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {t("New group from these items")}
              </span>
              {itemDragCount > 0 && (
                <Count n={itemDragCount} pad />
              )}
            </div>
          </div>
        )}
      </div>

      {/* THE SELECTION BAR every other list has — Select all, Delete, the way
          out — in place of a Delete button of its own. Past ONE group: one
          picked group is the grid's scope, not a selection. */}
      {selectedGroups.length >= 2 && (
        <div style={{ flex: "0 0 auto", borderTop: "1px solid var(--border-soft)",
                      padding: "8px 10px" }}>
          <SelectionBar
            t={t}
            count={selectedGroups.length}
            total={rows.length}
            onSelectAll={() => setSelectedGroups(rows.map((r) => r.node.id))}
            onClear={() => setSelectedGroups([])}
            onRemove={doDelete}
            removeLabel={t("Delete")}
            removeIcon="delete"
            removeCount={selectedGroups.length}
            style={{ marginBottom: 0 }}
          />
        </div>
      )}

      {/* Background AI jobs (queued/running/recent) — cancel or clear here. */}
      <JobList />

      <div style={{ flex: "0 0 auto", borderTop: "1px solid var(--border-soft)" }}>
        {/* Expanded statistics panel — animated open/close (grid-rows 0fr→1fr,
            body clipped by overflow while it slides). */}
        <Collapse open={!!(statsOpen && stats)}>
            {stats && (
              <div style={{ padding: "10px 14px 4px", display: "flex", flexDirection: "column", gap: 5, fontSize: "var(--fs-2)", color: "var(--muted)" }}>
                {([
                  ["Images", num(stats.images)],
                  ["Videos", num(stats.videos)],
                  ["Sequences", num(stats.sequences)],
                  ["Groups", num(stats.groups)],
                  ["Tags", num(stats.tags)],
                  ["Source files", num(stats.files)],
                  ["Stored size", humanSize(stats.bytes)],
                ] as [string, string][]).map(([k, v]) => (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span>{t(k)}</span>
                    <span style={{ fontFamily: "var(--mono)", color: "var(--text-3)" }}>{v}</span>
                  </div>
                ))}
                {/* Free space on the volume the library lives on — what limits
                    the next import, so it is coloured once it runs short. */}
                {stats.disk_total > 0 && (
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span>{t("Free space")}</span>
                    <span
                      title={`${humanSize(stats.disk_free)} ${t("free of")} ${humanSize(stats.disk_total)}`}
                      style={{ fontFamily: "var(--mono)", color: diskColor(diskLevel(stats.disk_free, stats.disk_total)) ?? "var(--text-3)", fontWeight: diskLevel(stats.disk_free, stats.disk_total) === "none" ? 400 : 600 }}
                    >
                      {humanSize(stats.disk_free)} / {humanSize(stats.disk_total)}
                    </span>
                  </div>
                )}
                <LibraryPathRow path={stats.data_dir} label={t("Library path")} copyTitle={t("Copy library path")} />
              </div>
            )}
          </Collapse>
        {/* Summary line — click to expand/collapse the statistics. */}
        <div
          onClick={() => setStatsOpen((v) => !v)}
          title={statsOpen ? t("Hide library statistics") : t("Show library statistics")}
          style={{
            padding: "9px 14px",
            display: "flex",
            alignItems: "center",
            gap: 8,
            color: "var(--muted-2)",
            fontSize: "var(--fs-2)",
            cursor: "pointer",
          }}
        >
          <Icon name="database" size={16} />
          {/* Collapsed summary shows only the item count; the group count and
              stored size live in the expanded statistics panel above. */}
          <span style={{ fontFamily: "var(--mono)" }}>
            {tn({ one: "1 item", other: "{n} items" }, stats?.items ?? 0)}
          </span>
          {/* …except a disk warning, which has to be visible whether the panel
              is open or not — it is the one stat that is time-critical. */}
          {stats && diskLevel(stats.disk_free, stats.disk_total) !== "none" && (
            <span
              title={`${humanSize(stats.disk_free)} ${t("free of")} ${humanSize(stats.disk_total)}`}
              style={{
                display: "flex", alignItems: "center", gap: 3,
                color: diskColor(diskLevel(stats.disk_free, stats.disk_total)) ?? undefined,
                fontFamily: "var(--mono)", fontWeight: 600,
              }}
            >
              <Icon name="warning" size={13} />
              {!statsOpen && humanSize(stats.disk_free)}
            </span>
          )}
          <div style={{ flex: 1 }} />
          <Icon name={statsOpen ? "expand_more" : "expand_less"} size={16} />
        </div>
      </div>

      {queueNote && (
        <ActionToast
          text={queueNote}
          icon="check"
          actionLabel={t("OK")}
          onAction={() => setQueueNote(null)}
          dismissTitle={t("Dismiss")}
          onDismiss={() => setQueueNote(null)}
        />
      )}
      {!queueNote && undo.state && (
        <ActionToast
          text={undo.state.undone ? t("That was undone") : undo.state.label}
          actionLabel={undo.state.undone ? t("Redo") : t("Undo")}
          actionTitle={undo.state.undone ? t("Do it again")
                                         : t("Put it back the way it was")}
          icon={undo.state.undone ? "redo" : "undo"}
          dismissTitle={t("Put this message away")}
          onAction={() => void undo.toggle()}
          onDismiss={undo.dismiss}
        />
      )}
      {menu && (
        <GroupMenu
          at={menu}
          nodes={allNodes.filter((g) => menu.ids.includes(g.id))}
          special={menu.special ?? null}
          onEmptied={() => {
            qc.invalidateQueries({ queryKey: ["items"] });
            qc.invalidateQueries({ queryKey: ["stats"] });
            qc.invalidateQueries({ queryKey: ["facets"] });
          }}
          onClose={() => setMenu(null)}
          onNote={setQueueNote}
          onEdit={(id) => openGroupEditor(id)}
          onRename={(id) => setRenaming(id)}
          onNewChild={(id) => void newChildGroup(id)}
          onGroupTogether={(ids) => {
            // ONLY THE TOP-MOST of what was picked. A selection can hold a
            // group and something inside it, and moving the child in too
            // would pull it OUT of the parent that is travelling with it —
            // the one thing "group these" cannot have been asked to do.
            const tops = ids.filter(
              (id) => !ids.some((o) => o !== id && isInSubtree(id, o)));
            // Where the new group goes: where they all already were, when
            // that is one place. Mixed parents have no shared answer, so it
            // is a root and the dialog's Parent field is there to say
            // otherwise.
            const parents = new Set(tops.map((id) => parentOf.get(id) ?? null));
            openGroupCreator({
              smart: false, smartQuery: "", members: null,
              parent: parents.size === 1 ? [...parents][0] : null,
              childGroups: tops,
            });
          }}
          onMerge={async (dest, sources) => {
            const name = allNodes.find((g) => g.id === dest)?.name ?? "";
            if (!(await confirm({
              title: tn({
                one: "Move everything in {n} group into “{name}” and delete it?",
                other: "Move everything in {n} groups into “{name}” and delete them?",
              }, sources.length, { name }),
              answer: { label: t("Merge"), danger: true },
            }))) return;
            mergeGroups.mutate({ dest, sources });
          }}
          onDeleteKeepingChildren={async (node) => {
            const kids = node.children?.length ?? 0;
            if (!(await confirm({
              title: tn({
                one: "Delete “{name}” and move the group inside it up one level?",
                other: "Delete “{name}” and move the {n} groups inside it up one level?",
              }, kids, { name: node.name }),
              answer: { label: t("Delete"), danger: true },
            }))) return;
            // Only THIS group's tags are stopping — the subgroups survive and
            // go on granting their own — so the bake question is about it
            // alone, not about the subtree the plain delete would take.
            const assignTags = await askAssignTags([{ ...node, children: [] }]);
            if (assignTags == null) return;
            deleteGroups.mutate({ ids: [node.id], keepChildren: true, assignTags });
          }}
          onDuplicate={(ids) => duplicateGroups.mutate({ ids })}
          onDelete={async (ids) => {
            const nodes = allNodes.filter((g) => ids.includes(g.id));
            const n = ids.length;
            if (!(await confirm({
              title: tn({ one: "Delete 1 group and everything inside it?",
                          other: "Delete {n} groups and everything inside them?" }, n),
              body: t("The items stay in the library."),
              answer: { label: t("Delete"), danger: true },
            }))) return;
            const assignTags = await askAssignTags(nodes);
            if (assignTags == null) return;
            deleteGroups.mutate({ ids, assignTags });
          }}
        />
      )}
    </div>
  );
}

/** A GROUP'S NAME, EDITED WHERE IT STANDS — the row's own field, with ✓ and ✕
 *  beside it. Enter and Escape say the same two things, but a gesture that
 *  exists only on the keyboard is one half the people using it never find.
 *
 *  It holds the typed text ITSELF rather than handing it to the tree: a name
 *  in the tree's state would re-render every row of a windowed list on every
 *  keystroke, for a string one row is reading.
 *
 *  An empty name, or the name it already had, is a CANCEL: there is nothing
 *  to save, and refusing with a message would be an argument about a press
 *  that meant "leave it alone". */
function InlineRename({ value, confirmTitle, cancelTitle, onCommit, onCancel }: {
  value: string;
  confirmTitle: string;
  cancelTitle: string;
  onCommit: (name: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(value);
  const commit = () => {
    const clean = text.trim();
    if (!clean || clean === value) onCancel();
    else onCommit(clean);
  };
  return (
    <span
      // The row beneath is a drag source and a selection target; neither may
      // hear a press meant for the field or its two buttons.
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 2 }}
    >
      <input
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        onFocus={(e) => e.currentTarget.select()}
        onKeyDown={(e) => {
          // The page's own Delete/Backspace handler asks `isTypingTarget`, but
          // the tree's arrows and shortcuts are the row's — stop them here.
          e.stopPropagation();
          if (e.key === "Enter") { e.preventDefault(); commit(); }
          else if (e.key === "Escape") { e.preventDefault(); onCancel(); }
        }}
        style={{
          flex: 1, minWidth: 0, height: 22, padding: "0 6px",
          fontSize: "var(--fs-3)", color: "var(--text-bright)",
          background: "var(--bg)", border: "1px solid var(--accent)",
          borderRadius: "var(--r-2)", outline: "none",
        }}
      />
      <IconButton icon="check" size={20} glyph={14} title={confirmTitle}
                  onClick={commit} />
      <IconButton icon="close" size={20} glyph={14} title={cancelTitle}
                  onClick={onCancel} />
    </span>
  );
}

/** The group rows' right-click menu: the row actions for whatever is selected,
 *  and the one thing only worth offering over a whole group — running a face
 *  detector across every item in it.
 *
 *  Edit is offered for ONE group only: it opens an editor for a single group's
 *  name, icon and colour, and there is no meaning to opening five at once.
 *  Delete takes the lot.
 */
/** A FIXED sidebar entry's scope, for the context menu: either one of the
 *  server-resolvable views (`EnqueueScope.view` — the grid's own semantics),
 *  or the Trash, which offers no runs and instead the one action it has. */
type SpecialScope = {
  view?: "all" | "image" | "video" | "sequence" | "untagged" | "ungrouped"
    | "pending" | "hidden";
  trash?: boolean;
  label: string;
  count: number | null;
};

function GroupMenu({ at, nodes, special, onClose, onEdit, onRename, onNewChild,
                     onDelete,
                     onDeleteKeepingChildren, onDuplicate, onGroupTogether,
                     onMerge, onEmptied, onNote }: {
  at: { x: number; y: number; ids: number[]; clicked?: number };
  nodes: GroupNode[];
  /** A fixed entry's scope: no group ids exist for it, so the menu drops the
   *  group verbs (edit, delete) and the runs ask the server for the view's
   *  items instead of a subtree. */
  special?: SpecialScope | null;
  onClose: () => void;
  onEdit: (id: number) => void;
  /** Edit the name where it stands, in the row itself. */
  onRename: (id: number) => void;
  /** An empty group inside this one, named in place. */
  onNewChild: (id: number) => void;
  onDelete: (ids: number[]) => void;
  /** Delete this one and promote its direct subgroups to its own parent. */
  onDeleteKeepingChildren: (node: GroupNode) => void;
  /** A copy of each, beside the original. */
  onDuplicate: (ids: number[]) => void;
  /** Make a group AROUND these — the creator, seeded with them. */
  onGroupTogether: (ids: number[]) => void;
  onMerge: (dest: number, sources: number[]) => void;
  onEmptied: () => void;
  /** What a run queued (or why it did not) — the menu has closed by the
   *  time the server answers, so the host says it. */
  onNote: (text: string) => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  // The extra-output switch flips a stored preference the rows read
  // through; this only makes the menu draw the new state.
  const [, bump] = useState(0);
  const { data: models } = useQuery({ queryKey: ["ml-models"], queryFn: api.mlModels });
  const { data: cache } = useQuery({ queryKey: ["model-cache"], queryFn: api.modelCache });
  const count = special
    ? special.count ?? 0 : nodes.reduce((n, g) => n + g.count, 0);
  // THE ACTIONS TAB'S SECTIONS, in menu form, from the one builder the
  // grid's context menu uses (`app/aiActionSections.ts`): ready models
  // only, Remove text with its "read it, then remove" rows. The Trash
  // offers no runs.
  const sections = special?.trash
    ? [] : taskSections(models?.tasks, readyModel(cache?.models));

  /** ONE request: the server resolves the scope itself (the browser cannot
   *  cheaply know a big group's members, and a fixed row's view only the
   *  server can enumerate) and — for the kinds that record a per-item run —
   *  leaves out the items this model has already seen. */
  const run = async (kind: string, model: string) => {
    try {
      const skip = SKIP_DONE_KINDS.has(kind);
      // A "read it, then remove" row rides its OCR engine on the model id;
      // split the rider off and send it as `detect_with`.
      const [realModel, detectWith] = model.split(DETECT_WITH);
      const r = await api.enqueueScope(kind, realModel, at.ids, skip,
                                       special?.view ?? "", detectWith ?? "",
                                       kind === "panels"
                                         && readPanelsSequence());
      qc.invalidateQueries({ queryKey: ["ml-jobs"] });
      onNote(r.queued
        ? t("{n} queued", { n: String(r.queued) })
          + (r.skipped ? ` · ${t("{n} already done", { n: String(r.skipped) })}` : "")
        : r.skipped
          ? t("All of them were already done")
          : t("Nothing in there yet"));
    } catch {
      onNote(t("Could not queue that"));
    }
  };

  const one = nodes.length === 1 ? nodes[0] : null;
  const actions: RowAction[] = [];
  // Edit is offered for ONE group only: it opens an editor for a single
  // group's name, icon and colour, and there is no meaning to opening five
  // at once. Delete takes the lot.
  if (!special && one) {
    // RENAME first: it is the edit people come here for, and it happens in
    // the row rather than in a dialog. **Edit group** below it is the same
    // name plus everything else a group has.
    actions.push({ icon: "drive_file_rename_outline", label: t("Rename"),
                   onClick: () => onRename(one.id) });
    actions.push({ icon: "edit", label: t("Edit group"),
                   onClick: () => onEdit(one.id) });
    // …and the other thing a group is pointed at for: one more inside it.
    // A smart group holds no children (its rule decides its members), so it
    // is not offered one.
    if (!one.smart) {
      actions.push({ icon: "create_new_folder", label: t("New group inside"),
                     onClick: () => onNewChild(one.id) });
    }
  }
  // GROUP THESE — the one verb that only means anything over SEVERAL rows,
  // so it sits with Edit above the destructive pair rather than among them.
  // It creates nothing itself: it opens the group creator with these as its
  // starting contents, which is the rule every other way into that dialog
  // follows.
  if (!special && nodes.length > 1) {
    actions.push({ icon: "create_new_folder", label: t("Group these…"),
                   onClick: () => onGroupTogether(at.ids) });
  }
  // DUPLICATE — a copy beside the original, subtree and items and all.
  // Non-destructive, so it sits with Edit above the rule rather than among
  // the deletions, and it takes SEVERAL rows because duplicating five
  // folders is one gesture.
  if (!special && nodes.length > 0) {
    actions.push({ icon: "content_copy",
                   label: one ? t("Duplicate group") : t("Duplicate groups"),
                   onClick: () => onDuplicate(at.ids) });
  }
  // MERGE — the other verb that only means anything over several rows, and
  // the one that needs to know WHICH of them was pointed at: the destination
  // is the row the menu was opened on, and it is named in the label so the
  // direction is never a guess. Destructive (the others are deleted), so it
  // sits above the delete rows rather than with Edit.
  if (!special && nodes.length > 1 && at.clicked != null) {
    const dest = at.clicked;
    actions.push({
      icon: "merge",
      label: t("Merge into “{name}”", {
        name: nodes.find((g) => g.id === dest)?.name ?? "" }),
      onClick: () => onMerge(dest, at.ids.filter((i) => i !== dest)),
    });
  }
  if (!special) {
    actions.push({ icon: "delete", danger: true,
                   label: one ? t("Delete group") : t("Delete groups"),
                   onClick: () => onDelete(at.ids) });
  }
  // …and the same deletion WITHOUT the subtree. Offered only where there is
  // a subtree to keep, or it would be a second word for the row above it.
  // Second, because the plain one is what the tree has always meant by
  // Delete and a row that moved would be a row nobody finds.
  if (!special && one && (one.children?.length ?? 0) > 0) {
    actions.push({ icon: "folder_delete", danger: true,
                   label: t("Delete group, keep subgroups"),
                   onClick: () => onDeleteKeepingChildren(one) });
  }
  // The Trash's one useful action — the Empty Trash bar's, offered where the
  // row is right-clicked. Same confirmation: this is the permanent one.
  if (special?.trash) {
    actions.push({
      icon: "delete_forever", danger: true, label: t("Empty Trash"),
      onClick: async () => {
        if (!(await confirm({
          title: t("Permanently delete every item in the Trash?"),
          body: t("This cannot be undone."),
          answer: { label: t("Empty the Trash"), danger: true },
        }))) return;
        void api.emptyTrash().then(onEmptied);
      },
    });
  }
  // THE ACTIONS over this scope — one row per section, each opening its
  // tasks beside it, each task its models. Expanded in place, the full list
  // grew the menu past the bottom of the screen and left the group's own
  // verbs scrolled away above thirty rows of models. Each section row
  // carries the count a run would cover.
  actions.push(...aiActionRows(sections, t, (kind, model) => void run(kind, model), {
    separatedFirst: actions.length > 0,
    trailing: String(count),
    onExtraOutput: () => bump((n) => n + 1),
  }));

  return (
    <PointerMenu
      at={at}
      heading={special ? special.label
        : one ? one.name : t("{n} groups", { n: String(nodes.length) })}
      actions={actions}
      onClose={onClose}
    />
  );
}


//: Whether the Rankings block is expanded — beside `mc.kindsOpen` and
//  `mc.pendingOpen`, the two other fixed rows that hold children.

/** THE RANKINGS ROW, and a child per ranking under it.
 *
 *  A ranking is a WAY OF LOOKING AT THE LIBRARY. Since rung v31 it mints no
 *  tags and its standings are fitted on read and stored nowhere, so the order
 *  it produces had nowhere to be seen but a histogram on a page of its own —
 *  which is what this replaces: picking a row makes the GRID that order, best
 *  first, in sections by the standings' own buckets.
 *
 *  Shape and mechanics are Pending's, one level deeper: a parent that expands,
 *  shown only while the library has a ranking, and children each shown only
 *  when they hold something. Where Pending has two levels this has three — a
 *  ranking's own pools, and the pictures somebody set aside — which the group
 *  tree beside it makes unremarkable; what is new is that a fixed entry's
 *  child can itself expand.
 */
function RankingRows() {
  const t = useT();
  const qc = useQueryClient();
  const [open, setOpen] = useState(() => APP_PREFS.ranksOpen.read());
  const [openIds, setOpenIds] = useState<number[]>([]);
  const [editing, setEditing] = useState<RankingRow | null>(null);
  // The same dialog with nothing in it — its own flag, since `editing` holds
  // the ROW being edited and a new ranking has none.
  const [adding, setAdding] = useState(false);
  const [menu, setMenu] = useState<
    { x: number; y: number; actions: RowAction[] } | null>(null);
  const covered = useCoveredByWindow();
  const { data: rankings } = useQuery({
    queryKey: ["rankings"], queryFn: () => api.rankings(), enabled: !covered });
  const rankingView = useUI((s) => s.rankingView);
  const rankingPool = useUI((s) => s.rankingPool);
  const rankingDismissed = useUI((s) => s.rankingDismissed);
  const showRanking = useUI((s) => s.showRanking);
  const showRanked = useUI((s) => s.showRanked);
  const showRankingDismissed = useUI((s) => s.showRankingDismissed);
  const rankedOn = useUI((s) => s.rankedView);

  const rows = rankings ?? [];
  if (!rows.length) return null;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["rankings"] });
    qc.invalidateQueries({ queryKey: ["items"] });
  };
  /** The row's verbs. Rate on THIS ranking starts straight in, where the
   *  grid's menu always opens the chooser — that door promises a choice and
   *  this one has already made it. */
  const actionsFor = (r: RankingRow): RowAction[] => [
    { icon: "balance", label: t("Rate on this ranking…"),
      onClick: () => useUI.getState().setRateRanking(r.id) },
    { icon: "query_stats", label: t("Assign ratings…"),
      onClick: () => useUI.getState().setEstimateOpen(true) },
    { icon: "edit", label: t("Edit…"), separated: true,
      onClick: () => setEditing(r) },
    { icon: "delete", label: t("Delete"), danger: true, separated: true,
      onClick: async () => {
        if (!(await confirm({
          title: t("Delete “{name}” and its comparisons?", { name: r.name }),
          body: t("This cannot be undone."),
          answer: { label: t("Delete"), danger: true },
        }))) return;
        void api.deleteRanking(r.id).then(() => {
          if (rankingView === r.id) useUI.getState().showAllItems();
          refresh();
        });
      } },
  ];

  const rowStyle = (on: boolean, indent: number): React.CSSProperties => ({
    display: "flex", alignItems: "center", gap: 4, height: 30,
    padding: `0 6px 0 ${indent}px`, borderRadius: "var(--r-3)", cursor: "pointer",
    fontSize: "var(--fs-3)", marginBottom: 1,
    color: on ? "var(--selected-text)" : "var(--text-2)",
    background: on ? "var(--accent-dim)" : "transparent",
    fontWeight: on ? 600 : 400,
  });
  const count = (n: number | null | undefined) => (
    n == null || n <= 0 ? null : (
      <Count n={n} size={10} pad />
    )
  );

  return (
    <>
      {/* THE PARENT IS A VIEW TOO (owner 2026-09), like every other row in
          this column — and what it shows is THE RANKINGS, a card each, the
          same rows listed under it here. It only opened and closed at first,
          then scoped to the union of every ranking's placed pictures for a
          day: which answered a question nobody had asked, since a union
          across rankings has no order and no meaning of its own. This row is
          where a ranking is MET, so what belongs under it is the rankings.
          THE CHEVRON KEEPS THE OPENING to itself, so picking the row and
          folding it away are two gestures rather than one that has to
          guess. */}
      <div className="hoverable"
        onClick={() => showRanked()}
        // THE ROW'S OWN MENU. Every ranking under it has one; the row above
        // them is where the one verb that is about NO ranking belongs —
        // making another. (The grid's quick-actions reach it too, but only
        // through "Rate items…", which is a session rather than a catalog
        // verb: this is the way to add an axis without starting one.)
        onContextMenu={(e) => {
          e.preventDefault();
          setMenu({ x: e.clientX, y: e.clientY, actions: [
            { icon: "add", label: t("New ranking…"),
              onClick: () => setAdding(true) },
          ] });
        }}
        style={{ ...rowStyle(rankedOn, 6), marginTop: 4 }}>
        <span
          onClick={(e) => { e.stopPropagation();
            setOpen((v: boolean) => {
              APP_PREFS.ranksOpen.write(!v);
              return !v;
            }); }}
          style={{ width: 16, flex: "0 0 16px", display: "flex",
                   alignItems: "center", justifyContent: "center" }}>
          <Icon name={open ? "expand_more" : "chevron_right"} size={16}
                color="var(--muted-2)" />
        </span>
        <Icon name="leaderboard" size={18}
              color={rankedOn ? "var(--accent)" : "var(--muted)"} />
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>{t("Rankings")}</span>
        {/* THE BADGE COUNTS WHAT THE ROW OPENS, which every badge in this
            column does: the RANKINGS, since that is what this view shows —
            one card each, the same rows listed under it here. */}
        {count(rows.length)}
      </div>

      {open && rows.map((r) => {
        // PAST ONE POOL a ranking expands to them. The fit is PER POOL, so
        // "order by standing" is undefined for a multi-pool ranking until the
        // view names one — these rows are how it does.
        const pools = r.pools ?? [];
        // CHILDREN, each shown only when it holds something: a row per pool
        // past a single one, and the set-aside pictures where there are any.
        const kids = pools.length > 1 || r.dismissed > 0;
        const isOpen = openIds.includes(r.id);
        const on = rankingView === r.id && rankingPool == null
          && !rankingDismissed;
        return (
          <div key={r.id}>
            <div className="hoverable"
              onClick={() => showRanking(r.id)}
              onContextMenu={(e) => {
                e.preventDefault();
                setMenu({ x: e.clientX, y: e.clientY, actions: actionsFor(r) });
              }}
              style={rowStyle(on, 18)}>
              <span
                onClick={(e) => { e.stopPropagation();
                  if (kids) setOpenIds((v) => v.includes(r.id)
                    ? v.filter((x) => x !== r.id) : [...v, r.id]); }}
                style={{ width: 16, flex: "0 0 16px", display: "flex",
                         alignItems: "center", justifyContent: "center" }}>
                {kids && <Icon name={isOpen ? "expand_more" : "chevron_right"}
                               size={16} color="var(--muted-2)" />}
              </span>
              <Icon name="trending_up" size={18}
                    color={on ? "var(--accent)" : "var(--muted)"} />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}
                    // THE BADGE COUNTS ITEMS, like every other badge in this
                    // column — the comparisons go in the title, since the two
                    // numbers diverge wildly and one of them is what the grid
                    // will show.
                    title={t("{n} comparisons", { n: String(r.judgments) })}>
                {r.name}
              </span>
              {count(r.items)}
            </div>
            {kids && isOpen && pools.length > 1 && pools.map((lg) => (
              <div key={lg.id} className="hoverable"
                onClick={() => showRanking(r.id, lg.id)}
                style={rowStyle(rankingView === r.id && rankingPool === lg.id, 30)}>
                <span style={{ width: 16, flex: "0 0 16px" }} />
                <Icon name="inventory_2" size={17}
                      color={rankingPool === lg.id ? "var(--accent)" : "var(--muted)"} />
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                               whiteSpace: "nowrap" }}>
                  {lg.name || t("Default")}
                </span>
              </div>
            ))}
            {/* THE ONES SOMEBODY SET ASIDE. Ranking-wide, so it sits beside
                the pools rather than inside one, and only where there are
                any — the rule every other row in this column follows. They
                have no standing, so this view sorts like any other. */}
            {kids && isOpen && r.dismissed > 0 && (() => {
              const naOn = rankingView === r.id && rankingDismissed;
              return (
                <div className="hoverable"
                  onClick={() => showRankingDismissed(r.id)}
                  style={rowStyle(naOn, 30)}>
                  <span style={{ width: 16, flex: "0 0 16px" }} />
                  <Icon name="block" size={17}
                        color={naOn ? "var(--accent)" : "var(--muted)"} />
                  <span style={{ flex: 1, overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {t("Not applicable")}
                  </span>
                  {count(r.dismissed)}
                </div>
              );
            })()}
          </div>
        );
      })}
      {menu && (
        <PointerMenu at={{ x: menu.x, y: menu.y }} actions={menu.actions}
                     onClose={() => setMenu(null)} />
      )}
      {editing && (
        <RankingEditOverlay ranking={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh(); }} />
      )}
      {adding && (
        <RankingEditOverlay ranking={null}
          onClose={() => setAdding(false)}
          onSaved={(made) => {
            setAdding(false);
            refresh();
            // OPEN WHAT WAS JUST MADE, the way every other "create" in this
            // column ends: the create answers with the whole catalog, so the
            // new one is the row this list had not seen. Its view is empty
            // and says so — which is the one place that sentence belongs,
            // since the answer to "why is this empty" is "go and compare
            // some pairs".
            const before = new Set(rows.map((r) => r.id));
            const fresh = (made ?? []).find((r) => !before.has(r.id));
            if (fresh) showRanking(fresh.id);
          }} />
      )}
    </>
  );
}
