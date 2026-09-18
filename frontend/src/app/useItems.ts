// The grid's data model: independent per-page queries over the current view,
// windowed to the pages that intersect what is on screen (plus one page of
// overscan each side), instead of one unbounded infinite query that
// accumulated every page ever scrolled past. Page 1 is always mounted so
// `total` exists before any scrolling; invalidating ["items"] refetches only
// the MOUNTED page queries, and pages that scrolled away are dropped after a
// minute (gcTime).
//
// Consumers that only want "whatever items of the current view are loaded"
// (the properties panel's per-item maps, QuickLook, Quick Assign) read the
// cached pages reactively through useLoadedViewItems — they never mount page
// queries of their own.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api, GroupRun, ItemOut, ItemPage, ItemSearchBody, QueryGroup,
} from "./api";
import { useCoveredByWindow, useUI } from "./store";
import { reportLibraryRev } from "./invalidation";
import { tryParse, toRequest } from "../query/tree";
import { useDebouncedValue } from "../shared/useDebounced";
import { keepsPreviousPage, keepsPreviousRuns } from "./viewPlaceholder";

export const PAGE_SIZE = 60;
// Pages fetched beyond the visible index range, each side.
const OVERSCAN_PAGES = 1;

/** The current view's request body plus its cache-key parts. Every hook here
 *  derives the view through this one helper, so they all mean the same view
 *  and share one cache namespace: ["items", filtersKey, treeKey, sort, page]. */
/** The scope the grid is showing, as the search body every whole-view
 *  request sends. Exported for the one caller that needs the BODY without
 *  a page of rows: a shift+click asking which ids lie between two
 *  positions (`api.itemIdRange`). */
export function useViewRequest(): {
  req: ItemSearchBody;
  filtersKey: string;
  treeKey: string;
  sort: string;
} {
  const selectedGroups = useUI((s) => s.selectedGroups);
  const ungrouped = useUI((s) => s.ungrouped);
  const untagged = useUI((s) => s.untagged);
  const trashView = useUI((s) => s.trashView);
  const hiddenView = useUI((s) => s.hiddenView);
  const pendingView = useUI((s) => s.pendingView);
  const pendingKind = useUI((s) => s.pendingKind);
  const sequenceView = useUI((s) => s.sequenceView);
  const rankingView = useUI((s) => s.rankingView);
  const rankingPool = useUI((s) => s.rankingPool);
  const rankingDismissed = useUI((s) => s.rankingDismissed);
  const rankedView = useUI((s) => s.rankedView);
  const mediaKinds = useUI((s) => s.mediaKinds);
  const foldSequenced = useUI((s) => s.foldSequenced);
  const showHiddenItems = useUI((s) => s.showHiddenItems);
  const search = useUI((s) => s.search);
  const sortField = useUI((s) => s.sortField);
  const sortDir = useUI((s) => s.sortDir);
  const sortSeed = useUI((s) => s.sortSeed);

  const pendingKindParam = pendingView ? (pendingKind ?? undefined) : undefined;
  // The token is `<field>_<direction>`, and a shuffle puts its SEED where the
  // direction goes: it is what the backend needs and the only thing a random
  // order has to say about itself, so nothing else on this path — the page
  // request, the group runs, the facets — learns that a new kind of sort
  // exists. Every page of one view then carries the same seed and so agrees
  // with the others about the order.
  const sort = sortField === "random"
    ? `random_${sortSeed}` : `${sortField}_${sortDir}`;
  // The media-kind filter doesn't apply inside a single sequence's member view.
  const kind = sequenceView != null ? "" : [...mediaKinds].sort().join(",");
  // FOLD SEQUENCES — a member gives way to its own sequence where both would
  // be in the view. Which members those are is the server's question (it is
  // the view asked again, of the containers); all that travels is the flag.
  // Inside a sequence's own member view there is nothing to fold: every item
  // shown is a member of the one sequence and its container is not in the
  // view at all.
  const foldSeq = sequenceView == null && foldSequenced;

  // The whole query lives in `search` as the serialized string; the store keeps
  // it keystroke-fresh for the input, and this DEBOUNCED copy is what drives
  // fetching — a burst of typing costs one request, not one per keystroke.
  const debSearch = useDebouncedValue(search, 250);

  // Parse the debounced string to the condition tree here and POST that — the
  // backend never parses a query string. A string that doesn't parse (mid-edit,
  // e.g. an unclosed quote surviving the debounce) HOLDS THE LAST GOOD TREE
  // rather than falling back to null: null means "match everything", so the old
  // fallback fetched the entire unfiltered library on unparsable intermediate
  // states. tryParse returns null on failure, which makes hold-last-good a
  // one-ref affair; the ref only ever advances on a successful parse, so the
  // query key (below) doesn't change and no fetch fires until the text parses
  // again.
  const lastGoodTree = useRef<QueryGroup | null>(null);
  const tree = useMemo(() => {
    const g = tryParse(debSearch);
    if (g) lastGoodTree.current = toRequest(g);
    return lastGoodTree.current;
  }, [debSearch]);
  // The canonical key: two strings that parse to the same tree (whitespace,
  // held-last-good states) share one cache entry and one request.
  const treeKey = useMemo(() => JSON.stringify(tree), [tree]);

  // One canonical string for every non-search filter, so the page query keys
  // stay flat and the loaded-items readers can match the namespace cheaply.
  const filtersKey = useMemo(
    () =>
      JSON.stringify([
        selectedGroups, ungrouped, untagged, trashView, hiddenView, pendingView,
        pendingKindParam ?? null, sequenceView, rankingView, rankingPool,
        rankingDismissed, rankedView,
        kind, foldSeq, showHiddenItems,
      ]),
    [selectedGroups, ungrouped, untagged, trashView, hiddenView, pendingView,
     pendingKindParam, sequenceView, rankingView, rankingPool, rankingDismissed,
     rankedView, kind, foldSeq,
     showHiddenItems]
  );

  const req = useMemo<ItemSearchBody>(
    () => ({
      query: tree,
      groups: selectedGroups, ungrouped, untagged, trash: trashView,
      hidden: hiddenView, pending: pendingView, pending_kind: pendingKindParam,
      show_hidden: showHiddenItems, sequence: sequenceView, kind,
      ranking: rankingView, ranking_pool: rankingPool,
      ranking_dismissed: rankingDismissed,
      fold_sequenced: foldSeq, sort,
    }),
    // filtersKey covers every scope field by VALUE (the arrays inside change
    // identity without changing meaning).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filtersKey, treeKey, sort]
  );

  return { req, filtersKey, treeKey, sort };
}

export interface GroupRunsView {
  runs: GroupRun[];
  /** Sum of the run counts — the index space the grouped layout describes.
   *  May differ from the page query's `total` for one refetch after an edit;
   *  see the note in ItemGrid on why neither gates the other. */
  total: number;
  ready: boolean;
  isFetching: boolean;
  error: Error | null;
}

/** THE RANKINGS INDEX SHOWS NO ITEMS, so it fetches none.
 *
 *  The sidebar's Rankings row opens a card per RANKING (`ItemGrid`'s
 *  `RankingsIndex`), not a grid of their pictures — so the page queries, the
 *  grouped layout and the whole-view panel's own page-1 read have nothing to
 *  answer there. Gated in one place rather than three, beside
 *  `useCoveredByWindow`, which is the same kind of fact: a grid nobody is
 *  looking at costs requests nobody asked for. */
function useShowsItems(): boolean {
  return !useUI((s) => s.rankedView);
}

/**
 * The grid's SECTIONS for the current view.
 *
 * Built on the same `useViewRequest()` as the pages, so it can only ever mean
 * the same view. Its own cache root — NOT under ["items"], whose prefix
 * matchers read `k[4]` as a page number and would start seeing this entry
 * ride along in every match.
 *
 * `placeholderData` keeps the previous runs across a sort or search change,
 * matching what the page queries already do: for that frame the layout is
 * stale and so are the items, which is mutually consistent and flips
 * together. Letting the runs go undefined instead would collapse the content
 * height to the ungrouped one for a frame and throw the scroll position.
 * NOT across a SCOPE change, for the reason the page queries do not either —
 * see `viewPlaceholder.ts`; there the two stale halves would agree with each
 * other about a view nobody is looking at.
 */
export function useGroupRuns(groupBy: string): GroupRunsView {
  const { req, filtersKey, treeKey, sort } = useViewRequest();
  // …and not while the item window covers the grid: see `useCoveredByWindow`.
  //
  // CALLED UNCONDITIONALLY, and that is the whole point of the extra line:
  // `groupBy !== "none" && !useCoveredByWindow()` SHORT-CIRCUITS, so the hook
  // ran on a grouped render and not on an ungrouped one. React then compares
  // the next render's hook deps against a slot that belongs to a different
  // hook — "Cannot read properties of undefined (reading 'length')" out of
  // `areHookInputsEqual`, and the whole tab on its error boundary. Latent
  // until something made the first render grouped and the next not.
  const covered = useCoveredByWindow();
  const showsItems = useShowsItems();
  const enabled = groupBy !== "none" && !covered && showsItems;
  const q = useQuery({
    queryKey: ["item-groups", filtersKey, treeKey, sort, groupBy] as const,
    queryFn: ({ signal }) =>
      api.itemGroupRuns({ ...req, group_by: groupBy }, signal),
    enabled,
    placeholderData: (prev, prevQuery) =>
      keepsPreviousRuns(prevQuery?.queryKey, filtersKey) ? prev : undefined,
    gcTime: 60_000,
  });
  // The layout must describe the same library state as the pages — its rev
  // joins the same mismatch detection (see useItemView).
  useEffect(() => {
    reportLibraryRev(q.data?.rev);
  });
  const runs = enabled ? (q.data?.runs ?? []) : [];
  return {
    runs,
    total: enabled ? (q.data?.total ?? 0) : 0,
    ready: enabled && q.data != null,
    isFetching: q.isFetching,
    error: (q.error as Error) ?? null,
  };
}

export interface ItemView {
  /** Total item count of the view (0 until page 1 answers). */
  total: number;
  /** True once page 1 has data (possibly kept from the previous view). */
  ready: boolean;
  /** Initial load of page 1 (nothing to show yet). */
  isLoading: boolean;
  /** Any mounted page query fetching. */
  isFetching: boolean;
  error: Error | null;
  /** Ask every mounted page again — the way out of `error`. */
  refetch: () => void;
  /** The item at a flat view index, or undefined while its page is unloaded. */
  getItem: (index: number) => ItemOut | undefined;
  getIdAt: (index: number) => number | undefined;
  /** Flat view index of a loaded id, or -1 when it isn't loaded. */
  indexOfId: (id: number) => number;
  /** Ids of every loaded page, in view order. */
  loadedIds: number[];
  /** Items of every loaded page, in view order. */
  loadedItems: ItemOut[];
  /** Every item of the CURRENT view, page by page — the ZIP export walks this
   *  so RAM never holds more than a page of metadata at once. */
  iterate: (pageSize?: number) => AsyncGenerator<ItemOut, void, void>;
  /** Compat wrapper over `iterate` collecting the whole view into one array. */
  fetchAllItems: () => Promise<ItemOut[]>;
}

/**
 * Windowed item view: mounts one query per page intersecting
 * [range.start - overscan, range.end + overscan] (flat item indices),
 * plus page 1 for `total`. The visible range drives all fetching — there is
 * no "fetch next page" anymore.
 */
/** How long a JUMP in the visible range waits before it fetches. */
export const JUMP_SETTLE_MS = 150;

/** A JUMP SETTLES BEFORE IT FETCHES; ordinary scrolling fetches at once.
 *
 *  The visible range follows every scroll event, and so did the pages
 *  mounted for it — so dragging the scrollbar across a million-item view
 *  fired a page request for every position the thumb passed through. Each
 *  of those is a deep `OFFSET` walk on the server, the browser aborts them
 *  but the server still runs them, and a couple of dozen in flight is more
 *  than the engine's connection pool holds: every later request then waited
 *  the pool's 30 s and failed, which read as "the server stops responding".
 *
 *  So a range that OVERLAPS the one last fetched for (a wheel step, an arrow
 *  key, a slow drag) is taken at once, and one that does not — a jump — is
 *  taken only once it has held still for `JUMP_SETTLE_MS`. The cards for the
 *  in-between positions render as placeholders, which is what a fast drag
 *  shows anyway. */
function useSettledRange(range: { start: number; end: number }) {
  const [settled, setSettled] = useState(range);
  const settledRef = useRef(range);
  useEffect(() => {
    const cur = settledRef.current;
    const take = () => { settledRef.current = range; setSettled(range); };
    if (range.start <= cur.end && range.end >= cur.start) { take(); return; }
    const t = window.setTimeout(take, JUMP_SETTLE_MS);
    return () => window.clearTimeout(t);
  }, [range.start, range.end]);
  return settled;
}

export function useItemView(visible: { start: number; end: number }): ItemView {
  const { req, filtersKey, treeKey, sort } = useViewRequest();
  const qc = useQueryClient();
  const range = useSettledRange(visible);

  // Clamp the mounted pages by the last-known total (page 1's cached reply),
  // so a stale scroll position can't mount queries past the view's end.
  const cachedFirst = qc.getQueryData<ItemPage>([
    "items", filtersKey, treeKey, sort, 1,
  ]);
  const maxPage = cachedFirst
    ? Math.max(1, Math.ceil(cachedFirst.total / PAGE_SIZE))
    : null;

  const pages = useMemo(() => {
    const lo = Math.max(
      1,
      Math.floor(Math.max(0, range.start) / PAGE_SIZE) + 1 - OVERSCAN_PAGES
    );
    let hi =
      Math.floor(Math.max(0, range.end) / PAGE_SIZE) + 1 + OVERSCAN_PAGES;
    if (maxPage != null) hi = Math.min(hi, maxPage);
    const out = [1]; // always, so `total` exists before scrolling
    for (let p = Math.max(2, lo); p <= hi; p++) out.push(p);
    return out;
  }, [range.start, range.end, maxPage]);

  // Nothing is fetched while the item window is over the grid — the pages
  // stay in the cache, go stale as edits land, and refetch once when the
  // window closes. See `useCoveredByWindow` for what that was costing.
  const covered = useCoveredByWindow();
  const showsItems = useShowsItems();
  const results = useQueries({
    queries: pages.map((page) => ({
      queryKey: ["items", filtersKey, treeKey, sort, page] as const,
      enabled: !covered && showsItems,
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.itemsQuery({ ...req, page, page_size: PAGE_SIZE }, signal),
      // Keep the previous data while the new answer loads, so the grid swaps
      // content in rather than flashing empty — under the two conditions
      // `viewPlaceholder.keepsPreviousPage` states and explains: the same page
      // number, and the same SCOPE. The second is a guard rather than a
      // repair; what it rules out, and what was ruled out with it, is written
      // there.
      placeholderData: (
        prev: ItemPage | undefined,
        prevQuery: { queryKey: readonly unknown[] } | undefined
      ) => (keepsPreviousPage(prevQuery?.queryKey, filtersKey, page)
              ? prev : undefined),
      // Pages that scroll away unmount; let their data go after a minute
      // rather than piling up page arrays across a long browse.
      gcTime: 60_000,
    })),
  });

  // A window assembled from two library revisions is describing an ordering
  // that no longer exists (an external importer shifts a newest-first view
  // under these offsets, and sends no invalidation) — report every page's
  // rev; a mismatch triggers one coalesced re-sync. In an effect, not the
  // render: the report can invalidate, which sets state.
  useEffect(() => {
    for (const r of results) reportLibraryRev(r.data?.rev);
  });

  // Loaded items per page number. `results` keeps element identity through
  // structural sharing, so downstream memos only move when data really does.
  const byPage = useMemo(() => {
    const m = new Map<number, ItemOut[]>();
    for (let i = 0; i < pages.length; i++) {
      const d = results[i]?.data;
      if (d) m.set(pages[i], d.items);
    }
    return m;
  }, [results, pages]);

  const loadedItems = useMemo(() => {
    const ps = [...byPage.keys()].sort((a, b) => a - b);
    const out: ItemOut[] = [];
    for (const p of ps) out.push(...byPage.get(p)!);
    return out;
  }, [byPage]);

  const loadedIds = useMemo(() => loadedItems.map((it) => it.id), [loadedItems]);

  const indexById = useMemo(() => {
    const m = new Map<number, number>();
    for (const [p, arr] of byPage) {
      for (let j = 0; j < arr.length; j++) {
        m.set(arr[j].id, (p - 1) * PAGE_SIZE + j);
      }
    }
    return m;
  }, [byPage]);

  const getItem = useCallback(
    (index: number): ItemOut | undefined => {
      if (index < 0) return undefined;
      const arr = byPage.get(Math.floor(index / PAGE_SIZE) + 1);
      return arr?.[index % PAGE_SIZE];
    },
    [byPage]
  );
  const getIdAt = useCallback(
    (index: number) => getItem(index)?.id,
    [getItem]
  );
  const indexOfId = useCallback(
    (id: number) => indexById.get(id) ?? -1,
    [indexById]
  );

  const first = results[0];
  const total = first?.data?.total ?? 0;
  const ready = first?.data != null;

  const iterate = useCallback(
    async function* (pageSize = 500): AsyncGenerator<ItemOut, void, void> {
      for (let page = 1; ; page++) {
        const res = await api.itemsQuery({
          ...req, page, page_size: pageSize,
        });
        for (const it of res.items) yield it;
        if (page * pageSize >= res.total || res.items.length === 0) break;
      }
    },
    [req]
  );

  const fetchAllItems = useCallback(async (): Promise<ItemOut[]> => {
    const out: ItemOut[] = [];
    for await (const it of iterate()) out.push(it);
    return out;
  }, [iterate]);

  const refetch = useCallback(() => {
    for (const r of results) void r.refetch();
  }, [results]);

  return {
    total,
    ready,
    isLoading: !ready && (first?.isLoading ?? true),
    isFetching: results.some((r) => r.isFetching),
    error: (results.find((r) => r.error)?.error as Error | undefined) ?? null,
    refetch,
    getItem,
    getIdAt,
    indexOfId,
    loadedIds,
    loadedItems,
    iterate,
    fetchAllItems,
  };
}

// Element-wise identity compare — structural sharing keeps unchanged ItemOut
// objects identical across refetches, so this is the cheap "did anything
// actually change" check.
function sameArray<T>(a: T[], b: T[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/**
 * Whatever items of the CURRENT view are loaded in the cache (every cached
 * page, in view order), updating as the grid loads more. Read-only: mounts no
 * page queries of its own — consumers that need per-item lookups (the
 * properties panel's maps, QuickLook, Quick Assign) degrade gracefully via
 * Map.get for items whose page isn't loaded.
 */
/**
 * THE WHOLE VIEW, for something that means "everything the grid is showing".
 *
 * `req` is the scope to send (never the ids — the view can be the entire
 * library), `total` is how many items are in it and `first` is the first page
 * of them, which is all a preview of "everything" can show anyway.
 *
 * It reads page 1 under the SAME key the grid's own pages use, so with a grid
 * on screen this costs nothing at all and cannot disagree with it about what
 * the view is.
 */
export function useViewScope(enabled = true): {
  req: ItemSearchBody;
  total: number | null;
  first: ItemOut[];
} {
  const { req, filtersKey, treeKey, sort } = useViewRequest();
  // Its callers are library-view components (the two keyboard overlays, the
  // whole-view action panel), so while the item window covers them this asks
  // nothing — the same page under the same key the gated grid pages use, and
  // leaving it live was the last thing still refetching the view per edit.
  const covered = useCoveredByWindow();
  const showsItems = useShowsItems();
  const { data } = useQuery({
    queryKey: ["items", filtersKey, treeKey, sort, 1] as const,
    queryFn: () => api.itemsQuery({ ...req, page: 1, page_size: PAGE_SIZE }),
    enabled: enabled && !covered && showsItems,
  });
  return { req, total: data?.total ?? null, first: data?.items ?? [] };
}

export function useLoadedViewItems(): ItemOut[] {
  const { filtersKey, treeKey, sort } = useViewRequest();
  const qc = useQueryClient();
  const [items, setItems] = useState<ItemOut[]>([]);

  useEffect(() => {
    let raf = 0;
    const read = () => {
      const entries = qc.getQueriesData<ItemPage>({
        queryKey: ["items", filtersKey, treeKey, sort],
      });
      const withPage: [number, ItemPage][] = [];
      for (const [key, data] of entries) {
        const page = key[4];
        if (data && typeof page === "number") withPage.push([page, data]);
      }
      withPage.sort((a, b) => a[0] - b[0]);
      const out: ItemOut[] = [];
      for (const [, d] of withPage) out.push(...d.items);
      setItems((prev) => (sameArray(prev, out) ? prev : out));
    };
    // Re-read on any cache event for this view's pages, coalesced to a frame
    // (a refetch sweep touches several pages back to back).
    const unsub = qc.getQueryCache().subscribe((event) => {
      const k = event.query.queryKey;
      if (
        !Array.isArray(k) || k[0] !== "items" || k[1] !== filtersKey ||
        k[2] !== treeKey || k[3] !== sort
      ) {
        return;
      }
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(read);
    });
    read();
    return () => {
      cancelAnimationFrame(raf);
      unsub();
    };
  }, [qc, filtersKey, treeKey, sort]);

  return items;
}
