/** The Tags tab's LEFT COLUMN — the way into the list beside it.
 *
 *  Four blocks, in one pane:
 *
 *    Everything                     12,480
 *      Subjects / Places / Events      312 …
 *      Uncategorized                 1,204
 *      Meta                             14
 *    CATEGORIES                  [+] [Delete 2] [search]
 *      the authored tree
 *    NAMESPACES
 *      the derived list
 *
 *  TWO KINDS OF ROW, ONE SELECTION. A CATEGORY is authored — somebody drags
 *  a row into it, it survives a rename, it nests, it has an icon — and is an
 *  ordinary `tag_set_categories` row; the three record rows above the tree
 *  are categories too, derived rather than authored (each holds exactly the
 *  tags of its kind). A NAMESPACE is the text before a tag's first colon: no
 *  row, no id, nothing to file into, and it answers whatever anybody files.
 *
 *  But a person picking one is asking the same question either way, so
 *  (owner 2026-09) A NAMESPACE READS AS A CATEGORY HOLDING THE NAMES MADE
 *  WITH IT: one row selection over both blocks, `useRowSelect`'s dialect
 *  throughout (plain click picks that row alone, ⌘ adds, shift takes the
 *  run, press-and-drag paints), and several picked are the UNION — a
 *  category and a namespace together list the tags in EITHER. They used to
 *  INTERSECT, which meant a plain click in the lower block emptied the list
 *  more often than not, and left two highlights on screen saying different
 *  things.
 *
 *  The pane is the same pane whichever pill is picked; only where the names
 *  come from differs (`tags` for the library, its own entries for an
 *  imported set), which is why the counts and the rows arrive as props. */
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { SearchField } from "../../shared/SearchField";
import { SECTION_LABEL_SM } from "../../shared/SectionHeading";

import { useT, useTn } from "../i18n";
import type { NamespaceRow, TagSetCategoryOut } from "../api";
import { Icon } from "../../shared/Icon";
import { Flat, flattenTree } from "../treeRows";
import { exactFirst } from "../exactFirst";
import { RECORD_ROWS, TreeRow, type RowDrag } from "./TagsTree";
import { useRowSelect, type RowSelect } from "./shared/useRowSelect";
import { useWindowedList } from "../useWindowedList";
import { OffscreenSelectionMarks, useOffscreenSelection } from "./OffscreenSelection";

/** THE TOOLBAR BAND IS ONE SHAPE ACROSS THIS TAB, so the panels under it
 *  start on the same line whichever column they are in. Three of them drew
 *  their own: the sidebar's buttons were 30 tall in a 34 band (two pixels
 *  low, four short), the Meta list's were 30 with no band at all (ten
 *  pixels high), and only the tag list's matched what the page was built
 *  around. `TOOLBAR_GAP` is what the list toolbar's own bottom padding
 *  leaves under it. */
export const TOOLBAR_H = 34;
export const TOOLBAR_TOP = 10;
export const TOOLBAR_GAP = 12;

/** A toolbar button. The one definition for all three bands — a pill of
 *  `TOOLBAR_H`, never shrinking and never wrapping: the row can hold the
 *  library's actions AND the selection's, and a button whose label wraps
 *  ("Delete" over "1") is taller than the row it is in. What yields
 *  instead is the search field, which is elastic. */
export function toolbarBtn(danger = false): React.CSSProperties {
  return {
    display: "flex", alignItems: "center", gap: 5, height: TOOLBAR_H,
    padding: "0 12px", borderRadius: "var(--r-5)", flex: "0 0 auto", whiteSpace: "nowrap",
    border: `1px solid ${danger ? "var(--danger-border)" : "var(--border-strong)"}`,
    background: danger ? "var(--danger-dim)" : "var(--panel-2)",
    color: danger ? "var(--danger)" : "var(--text-2)",
    cursor: "pointer", fontSize: "var(--fs-3)", fontWeight: danger ? 600 : 400,
  };
}
/** A tree row, for the offscreen-selection marks' arithmetic. */
const TREE_ROW_H = 30;

/** What the list is narrowed to. The row selection IS the narrowing — one
 *  state, so the highlight and the list can never disagree — and every part
 *  of it joins ONE union: "in Clothing, or filed nowhere, or called
 *  `artist:something`" is a thing somebody can pick. */
export interface TagsNarrowing {
  /** Picked category ids; each is taken with its subtree. */
  category: number[];
  /** Picked namespaces, without the colon. */
  namespaces: string[];
  uncategorized: boolean;
  /** Exactly one record kind, or none. The sidebar's rows set one; the
   *  filter menu is where several are ticked. */
  record: string | null;
}

/** The key a row wears in the one selection. Two namespaces cannot share a
 *  name and two categories cannot share an id, so the prefix is the whole of
 *  what keeps them apart. */
const catKey = (id: number) => `c${id}`;
const nsKey = (name: string) => `n${name.toLowerCase()}`;
const LOOSE_KEY = "u";

const blockLabel: React.CSSProperties = { ...SECTION_LABEL_SM, padding: "8px 8px 4px" };

/** THE TREE'S OWN STATE — which branches are shut, what it is searched for,
 *  and where its scroller is.
 *
 *  Held by the HOST rather than inside the sidebar because the host is what
 *  LANDS on a category: a `?` popover's "in the set", a row's category
 *  trail. Landing means opening the ancestors and clearing a search that
 *  hides the row IN THE SAME EVENT — a row the tree is not showing is a row
 *  `useRowSelect` prunes out of the selection. */
export interface CategoryTree {
  rows: Flat<TagSetCategoryOut>[];
  needle: string;
  search: string;
  setSearch: (v: string) => void;
  shut: Set<number>;
  /** Open or shut one category — and with `deep`, every category under it
   *  too, which is what alt/option on the chevron asks for (the library
   *  sidebar's own gesture, `GroupTree`). */
  toggle: (id: number, deep?: boolean) => void;
  scrollRef: React.MutableRefObject<HTMLDivElement | null>;
  /** Open everything above this category, clear a hiding search, and scroll
   *  to it. Whether it is then PICKED is the caller's business — the
   *  narrowing is not the tree's to write. */
  reveal: (id: number) => void;
  /** THE PANE THAT DRAWS THE TREE LENDS IT A WAY TO SCROLL TO A ROW. The
   *  tree is WINDOWED — a booru-sized set is four thousand rows and only
   *  twenty-five are ever on screen — so the row `reveal` is asked for is
   *  usually not in the DOM to be scrolled into view, and the arithmetic
   *  that would put it there belongs to the windowed list. */
  jump: React.MutableRefObject<((i: number) => void) | null>;
}

export function useCategoryTree(categories: TagSetCategoryOut[],
                                ancestorsOf: (id: number) => number[]): CategoryTree {
  const [shut, setShut] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const needle = search.trim().toLowerCase();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const jump = useRef<((i: number) => void) | null>(null);
  // WHICH ROW IS STILL BEING REVEALED. Opening the ancestors is a state
  // change, so the row `reveal` was asked for is not in `rows` yet when it
  // returns — the scroll is what the NEXT `rows` does about it.
  const [revealing, setRevealing] = useState<number | null>(null);

  // A SEARCH KEEPS THE MATCHES AND THEIR ANCESTORS, force-opens while it is
  // live, and leaves the stored expansion alone — the tree you were reading
  // is the tree you come back to.
  const rows: Flat<TagSetCategoryOut>[] = useMemo(() => {
    const kept = needle
      ? (() => {
          const hit = new Set<number>();
          const byId = new Map(categories.map((c) => [c.id, c]));
          for (const c of categories) {
            if (!c.name.toLowerCase().includes(needle)) continue;
            let cur: TagSetCategoryOut | undefined = c;
            while (cur && !hit.has(cur.id)) {
              hit.add(cur.id);
              cur = cur.parent_id == null ? undefined : byId.get(cur.parent_id);
            }
          }
          return categories.filter((c) => hit.has(c.id));
        })()
      : categories;
    return flattenTree(exactFirst(kept, needle, (c) => [c.name]),
                       needle ? new Set<number>() : shut);
  }, [categories, shut, needle]);

  //: WHO IS UNDER WHOM — built from `categories` rather than from `rows`,
  //  which holds only what the tree is SHOWING: a shut branch's children
  //  are exactly the ones a deep open has to reach.
  const kidsOf = useMemo(() => {
    const m = new Map<number, number[]>();
    for (const c of categories) {
      if (c.parent_id == null) continue;
      (m.get(c.parent_id) ?? m.set(c.parent_id, []).get(c.parent_id)!).push(c.id);
    }
    return m;
  }, [categories]);
  const toggle = useCallback((id: number, deep = false) => setShut((s) => {
    const n = new Set(s);
    // It is OPEN when it is not in the shut set, so the press means "shut".
    const shutting = !n.has(id);
    const reach: number[] = [id];
    if (deep) {
      for (let i = 0; i < reach.length && reach.length < 100_000; i++) {
        reach.push(...(kidsOf.get(reach[i]) ?? []));
      }
    }
    for (const cid of reach) {
      if (shutting) n.add(cid);
      else n.delete(cid);
    }
    return n;
  }), [kidsOf]);

  const reveal = useCallback((id: number) => {
    if (!categories.some((c) => c.id === id)) return;
    const up = new Set(ancestorsOf(id));
    setShut((cur) => {
      const n = new Set(cur);
      for (const a of up) n.delete(a);
      return n;
    });
    setSearch((cur) => {
      const nd = cur.trim().toLowerCase();
      const c = categories.find((x) => x.id === id);
      return nd && c && !c.name.toLowerCase().includes(nd) ? "" : cur;
    });
    // AND SCROLL THE TREE TO IT. Opening the ancestors is not enough: the
    // row it opened may be a hundred rows down a booru set's tree, and a
    // selection nobody can see reads as nothing having happened.
    setRevealing(id);
  }, [categories, ancestorsOf]);

  // …which the next `rows` answers: the ancestors are open by then, so the
  // row has an index, and the index is what a windowed list can scroll to.
  useEffect(() => {
    if (revealing == null) return;
    const i = rows.findIndex(({ row }) => row.id === revealing);
    setRevealing(null);
    if (i < 0) return;
    if (jump.current) jump.current(i);
    else document.querySelector(`[data-tagset-cat="${revealing}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [revealing, rows]);

  return { rows, needle, search, setSearch, shut, toggle, scrollRef, reveal,
           jump };
}

export function TagsSidebar({
  maxHeight, bandH, total, recordCounts, metaCount, metaPicked, onMeta,
  categories, uncategorized, namespaces,
  tree, narrowing, onNarrow,
  onAddCategory, onDeleteCategories, onCategoryMenu, onNamespaceMenu,
  categoryDrag, looseDrag, extraActions, onMakeEditable, makingEditable,
  makeEditableError,
}: {
  maxHeight?: number;
  /** HOW TALL THE BAND OVER THE TREE IS — the list's own toolbar band,
   *  measured, so the two columns start on one line whatever that band is
   *  carrying. It is `TOOLBAR_H` while the list holds one row of buttons,
   *  and taller while a row under them says what the list is narrowed to. */
  bandH?: number;
  /** The "Everything" count — the set's names, however many the filters
   *  leave. */
  total?: number;
  /** How many of them are a subject, a place, an event. A row is drawn only
   *  where there is something to draw: a tag set that says nobody is
   *  anybody keeps the rows it always had. */
  recordCounts?: Record<string, number>;
  /** THE TAG SET ABOUT THE TAG SET — how many META TAGS this one has.
   *  A meta tag labels a NAME ("character", "noflip") and never reaches a
   *  picture, so it is not one of the names above it and is deliberately
   *  NOT counted in Everything: it is a list beside them, not a slice of
   *  them. Undefined draws no row (a set with no labels keeps its rows). */
  metaCount?: number;
  /** The meta list is what is on screen. It is not a narrowing of the tag
   *  list — it is the other list — so it is its own flag rather than a
   *  member of `TagsNarrowing`, and picking any row above turns it off. */
  metaPicked?: boolean;
  onMeta?: () => void;
  categories: TagSetCategoryOut[];
  uncategorized?: number;
  namespaces: NamespaceRow[];
  tree: CategoryTree;
  narrowing: TagsNarrowing;
  onNarrow: (next: TagsNarrowing) => void;
  onAddCategory?: () => void;
  /** A READ-ONLY set's toolbar has no Add category; this stands in its place
   *  (owner 2026-09) — an editable copy of the set takes its place in the
   *  row, and the read-only one is switched off. `makingEditable` while the
   *  copy is being written, which on a big set takes seconds. */
  onMakeEditable?: () => void;
  makingEditable?: boolean;
  /** Why the last Make editable did not finish, shown as a mark on hover. */
  makeEditableError?: string;
  /** Delete the picked categories — the toolbar's second button, drawn only
   *  where something is picked and the host offers the verb. */
  onDeleteCategories?: (ids: number[]) => void;
  onCategoryMenu?: (e: React.MouseEvent, cat: TagSetCategoryOut) => void;
  onNamespaceMenu?: (e: React.MouseEvent, ns: NamespaceRow) => void;
  /** The tree's own drag, where the host offers one. `sel` rides along
   *  because a drag SOURCE has to end the paint gesture itself: Chrome
   *  sends `dragend` and never the `mouseup` the paint ends on. */
  categoryDrag?: (cat: TagSetCategoryOut, sel: RowSelect) => RowDrag | undefined;
  looseDrag?: RowDrag;
  /** Anything else the host wants in the toolbar. */
  extraActions?: React.ReactNode;
}) {
  const t = useT();
  const tn = useTn();
  const { rows, needle, search, setSearch, shut, toggle, scrollRef } = tree;
  // The needle a memo reads, so `keys` does not have to list it twice.
  const needleRef = useRef(needle);
  needleRef.current = needle;

  // ONE SELECTION FOR EVERY PICKABLE ROW, controlled by the narrowing:
  // `useRowSelect` is the tab's one row-selection dialect, and a sidebar
  // that invented its own would be a second one over the same kind of list.
  // IN READING ORDER, which is what a shift-range walks: Uncategorized is
  // a fixed row above the tree now, not its last one.
  const keys = useMemo(() => [
    ...(categories.length > 0 ? [LOOSE_KEY] : []),
    ...rows.map(({ row }) => catKey(row.id)),
    ...(needleRef.current
      ? namespaces.filter((ns) => ns.name.toLowerCase()
          .includes(needleRef.current)).map((ns) => nsKey(ns.name))
      : namespaces.map((ns) => nsKey(ns.name))),
  ], [rows, categories.length, namespaces, needle]);
  const selected = useMemo(() => [
    ...narrowing.category.map(catKey),
    ...(narrowing.uncategorized ? [LOOSE_KEY] : []),
    ...narrowing.namespaces.map(nsKey),
  ], [narrowing]);
  const nsByKey = useMemo(
    () => new Map(namespaces.map((ns) => [nsKey(ns.name), ns.name])),
    [namespaces]);
  // THE SEARCH IS THE PANE'S, NOT THE TREE'S. It narrows the categories
  // (`useCategoryTree`, which also opens the ancestors of what it keeps)
  // and the namespaces alike: they are one list of rows to a person
  // looking for one, and a field that visibly skipped half of them read as
  // broken. Same needle, same case-insensitive contains.
  const shownNs = useMemo(
    () => (tree.needle
      ? namespaces.filter((ns) => ns.name.toLowerCase().includes(tree.needle))
      : namespaces),
    [namespaces, tree.needle]);

  const sel = useRowSelect(keys, {
    escapeClears: true,
    selected,
    onChange: (next) => onNarrow({
      category: next.filter((k) => k.startsWith("c"))
        .map((k) => Number(k.slice(1))).filter((n) => Number.isFinite(n)),
      namespaces: next.filter((k) => k.startsWith("n"))
        .map((k) => nsByKey.get(k) ?? k.slice(1)),
      uncategorized: next.includes(LOOSE_KEY),
      // Picking a row is not picking a KIND: the pane sets one narrowing,
      // and the three record rows are the other answer to it.
      record: null,
    }),
  });

  const isAll = !metaPicked && !narrowing.category.length
    && !narrowing.namespaces.length
    && !narrowing.uncategorized && !narrowing.record;
  const none = (): TagsNarrowing =>
    ({ category: [], namespaces: [], uncategorized: false, record: null });

  // WHICH PICKED ROWS ARE OUT OF SIGHT, so the pane can say so rather than
  // leaving a count in the toolbar that nothing on screen accounts for. The
  // rows are a fixed 30 px and the scroller holds nothing above them, so a
  // row's offset is its index.
  const offsets = useMemo(() => {
    const picked = new Set(selected);
    const out: number[] = [];
    rows.forEach(({ row }, i) => {
      if (picked.has(catKey(row.id))) out.push(i * TREE_ROW_H);
    });
    return out;
  }, [rows, selected]);
  const offscreen = useOffscreenSelection(scrollRef, offsets, TREE_ROW_H);

  // THE COLUMN IS WINDOWED, because a tag set's tree is as long as the tag
  // set. The Characters set is 4,356 categories, and the pane mounted every
  // one of them: 4,473 rows and 45,000 DOM nodes, of which twenty-five were
  // on screen. Nothing was WRONG afterwards — which is why it survived — but
  // every render of the tab walked all of them, so moving the LIST's window
  // by one row cost 65 ms of blocked main thread and scrolling the names ran
  // at fifteen frames a second. The rows are a fixed `TREE_ROW_H` (the
  // offscreen marks' arithmetic already says so), so the window is exact
  // rather than an estimate. Two lists in one scroller: each measures its
  // own top inside it (`containerRef`), which is what lets the second sit
  // under the first's full height.
  const catWin = useWindowedList({
    count: rows.length, rowHeight: TREE_ROW_H, scrollRef, minCount: 60 });
  const nsWin = useWindowedList({
    count: shownNs.length, rowHeight: TREE_ROW_H, scrollRef, minCount: 60 });
  // …and the tree's `reveal` scrolls through it, since the row it wants is
  // usually not mounted.
  tree.jump.current = catWin.scrollToIndex;

  // THE LABELS GO WHEN THEY DO NOT FIT, and whether they fit is MEASURED.
  // The divider drags down to 180 px and two labelled buttons do not fit
  // that — they wrapped onto two rows and pushed the tree down. It was a
  // width in pixels for a while, and that was only ever right in English:
  // "Kategorie hinzufügen" is half again as wide as "Add category".
  const toolbarRef = useRef<HTMLDivElement>(null);
  const needW = useRef<Map<string, number>>(new Map());
  const picked = narrowing.category;
  const toolbarKey = `${onMakeEditable ? t("Make editable") : t("Add category")}|${picked.length > 0
    ? tn({ one: "Delete {n}", other: "Delete {n}" }, picked.length) : ""}`;
  const [, bumpToolbar] = useState(0);
  const need = needW.current.get(toolbarKey);
  const wide = need == null
    || (toolbarRef.current?.clientWidth ?? 9999) >= need;
  useLayoutEffect(() => {
    const el = toolbarRef.current;
    if (!el || !wide) return;
    // THE CHILDREN, SUMMED — not the row's `scrollWidth`, which for a flex
    // row that FITS is the row's own width: measured that way the answer was
    // always "one pixel too narrow", so the labels never came back once they
    // had gone, at any width. +2 for the row's own rounding, since a button
    // one pixel over wraps.
    const kids = Array.from(el.children) as HTMLElement[];
    const w = Math.ceil(kids.reduce((a, c) => a + c.offsetWidth, 0)
                        + 8 * Math.max(0, kids.length - 1)) + 2;
    if (needW.current.get(toolbarKey) !== w) {
      needW.current.set(toolbarKey, w);
      bumpToolbar((n) => n + 1);
    }
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: TOOLBAR_GAP,
                  maxHeight, minHeight: 0 }}>
      <div ref={toolbarRef}
           // THE BAND IS THE BUTTONS' OWN HEIGHT, and the gap under it is
           // what the list toolbar's bottom padding leaves — so the tree
           // and the list start on one line.
           style={{ display: "flex", alignItems: "center", gap: 8,
                    minHeight: Math.max(TOOLBAR_H, bandH ?? 0) }}>
        {onMakeEditable && (
          <button style={wide ? toolbarBtn()
                              : { ...toolbarBtn(), width: TOOLBAR_H, padding: 0,
                                  justifyContent: "center" }}
                  disabled={makingEditable}
                  title={t("Make an editable copy of this set, and switch this one off")}
                  onClick={onMakeEditable}>
            {makingEditable
              ? <Icon name="progress_activity" size={15} spin />
              : <Icon name="edit" size={15} />}
            {wide && (makingEditable ? t("Making editable…") : t("Make editable"))}
          </button>
        )}
        {onMakeEditable && makeEditableError && (
          <span title={makeEditableError} style={{ display: "inline-flex" }}>
            <Icon name="error" size={15} color="var(--red)" />
          </span>
        )}
        {onAddCategory && (
          <button style={wide ? toolbarBtn()
                              : { ...toolbarBtn(), width: TOOLBAR_H, padding: 0,
                                  justifyContent: "center" }}
                  title={t("Add category")} onClick={onAddCategory}>
            <Icon name="create_new_folder" size={15} />
            {wide && t("Add category")}
          </button>
        )}
        {/* The list's own shape: what the selection can be done to, over the
            thing it is selected in. */}
        {onDeleteCategories && picked.length > 0 && (
          <button style={{ ...toolbarBtn(true),
                           ...(wide ? { padding: "0 10px" }
                                    : { width: TOOLBAR_H, padding: 0,
                                        justifyContent: "center" }) }}
                  title={t("Their entries stay, uncategorized; their children move up.")}
                  onClick={() => onDeleteCategories(picked)}>
            <Icon name="delete" size={15} />
            {wide && tn({ one: "Delete {n}", other: "Delete {n}" }, picked.length)}
          </button>
        )}
        {extraActions}
      </div>

      {/* NO PANEL AROUND IT (owner 2026-09). The column is a WAY IN — a
          fixed head, then the categories and the namespaces — and a rounded
          card drawn round it made it a second list beside the list, boxed
          off from the page the way a dialog is. The rows keep their own
          hover and picked fills, which is what a tree here is read by. */}
      <div style={{ display: "flex", flexDirection: "column",
                    minHeight: 0, flex: "1 1 auto" }}>
        {/* THE FIXED HEAD does not scroll: these are the rows you go to in
            order to get back OUT of a category, and a way back that scrolls
            away is one you have to scroll back for. */}
        {/* NO INSET: the 4 px held the rows off the panel's border, and the
            panel has gone — the column's left edge is the page's now, so a
            row starts where the toolbar button above it does. */}
        <div style={{ flex: "0 0 auto", paddingTop: 2 }}>
          <TreeRow depth={0} kids={false} open selected={isAll}
                   icon="apps" label={t("Everything")} count={total}
                   onClick={() => onNarrow(none())} />
          {RECORD_ROWS.map(([kind, icon, label]) =>
            (recordCounts?.[kind] ?? 0) > 0 ? (
              <TreeRow key={kind} depth={0} kids={false} open
                       selected={narrowing.record === kind}
                       icon={icon} label={t(label)} count={recordCounts?.[kind]}
                       onClick={() => onNarrow({ ...none(), record: kind })} />
            ) : null)}
          {/* THE META TAGS, where this tag set has any. It was a sub-tab
              of its own for a while, one of four buttons at the top of the
              page — which read as a fourth kind of work, when what it is
              is the other list this same pane leads to: the names, and the
              labels ON the names. A tag set has both too, so the row is
              the pane's and not the library's. */}
          {/* UNCATEGORIZED IS A FIXED ROW, not the tree's last one. It is
              one of the ways OUT of a category — and it TAKES A DROP,
              which is how a name comes out of one — so it belongs with
              Everything rather than at the bottom of a booru set's four
              hundred rows, where reaching it meant scrolling past all of
              them. Drawn only where there ARE categories: with none, every
              name is uncategorized and the row is a second Everything. */}
          {categories.length > 0 && (() => {
            const rowProps = sel.props(LOOSE_KEY);
            return (
            <TreeRow depth={0} kids={false} open
                     selected={sel.has(LOOSE_KEY)}
                     icon="label_off" label={t("Uncategorized")}
                     count={uncategorized}
                     rowProps={rowProps}
                     onClick={rowProps.onClick}
                     drag={looseDrag} />
            );
          })()}
          {onMeta && (
            <TreeRow depth={0} kids={false} open selected={!!metaPicked}
                     icon="linked_services" label={t("Meta")}
                     count={metaCount}
                     onClick={onMeta} />
          )}
          {/* A SEARCH OVER BOTH BLOCKS, wherever there is a row in either
              to hunt through. `|| search` keeps it there once somebody is
              typing: a needle that matches nothing would otherwise take
              away the field holding it, with no way back to what was
              typed. */}
          {(categories.length + namespaces.length > 0 || search !== "") && (
            <>
              <div style={{ height: 1, background: "var(--border)", margin: "4px 4px" }} />
              <SearchField size="sm" value={search} onChange={setSearch} placeholder={t("Search the column…")}
                           clearTitle={t("Clear")} style={{ margin: "2px 0 6px" }} />
            </>
          )}
        </div>

        <div style={{ position: "relative", minHeight: 0, flex: "1 1 auto",
                      display: "flex" }}>
          <OffscreenSelectionMarks sel={offscreen}
                                   title={t("Scroll to the picked rows")} />
          <div ref={scrollRef}
               style={{ overflowY: "auto", overflowX: "hidden",
                        padding: "0 0 4px", minHeight: 0, flex: "1 1 auto" }}>
            {/* NO HEADING OVER AN EMPTY SECTION — a block that a search
                has emptied is a heading with nothing under it, which reads
                as a section that lost its rows rather than as one the
                needle does not match. (The other way it can be empty is a
                library that has filed nothing: the button that makes the
                first category is in the toolbar above.) */}
            {rows.length > 0 && (
              <div style={blockLabel}>{t("Categories")}</div>
            )}
            <div ref={catWin.containerRef}
                 style={{ position: "relative",
                          height: catWin.windowed ? catWin.totalHeight : undefined }}>
            <div style={catWin.windowed
                   ? { position: "absolute", top: catWin.topOffset,
                       left: 0, right: 0 }
                   : undefined}>
            {rows.slice(catWin.start, catWin.end).map(({ row: c, depth, kids }, j) => {
              const i = catWin.start + j;
              const key = catKey(c.id);
              const rowProps = sel.props(key);
              return (
              <TreeRow key={c.id} depth={depth} kids={kids} open={!shut.has(c.id)}
                catId={c.id} q={needle}
                // THE SELECTION IS THE NARROWING, one state, so the tint and
                // the list can never disagree about what is on screen.
                selected={sel.has(key)}
                // A RUN OF PICKED ROWS IS ONE BLOCK: the corners round at its
                // ends and are square in between, or adjacent rows read as a
                // stack of separate pills with the tint pinching between them.
                joinAbove={i > 0 && sel.has(catKey(rows[i - 1].row.id))}
                joinBelow={i < rows.length - 1
                           && sel.has(catKey(rows[i + 1].row.id))}
                icon={c.icon || "folder"} label={c.name} count={c.count}
                hidden={c.hidden}
                rowProps={rowProps}
                // `useRowSelect`'s dialect and nothing else: a plain click
                // picks this row alone (and so shows it), ⌘ adds one, shift
                // takes the run, press-and-drag paints — and a plain click on
                // the only picked row lets it go, which is the way back to
                // whichever fixed row was on.
                onClick={rowProps.onClick}
                // ALT/OPTION TAKES THE WHOLE BRANCH, the gesture the
                // library's group tree has always had.
                onToggle={(e) => toggle(c.id, e.altKey)}
                toggleTitle={t("Click to open · Alt-click for the whole branch")}
                onMenu={onCategoryMenu ? (ev) => onCategoryMenu(ev, c) : undefined}
                drag={categoryDrag?.(c, sel)} />
              );
            })}
            </div>
            </div>
            {shownNs.length > 0 && (
              <>
                <div style={blockLabel}>{t("Namespaces")}</div>
                <div ref={nsWin.containerRef}
                     style={{ position: "relative",
                              height: nsWin.windowed ? nsWin.totalHeight : undefined }}>
                <div style={nsWin.windowed
                       ? { position: "absolute", top: nsWin.topOffset,
                           left: 0, right: 0 }
                       : undefined}>
                {shownNs.slice(nsWin.start, nsWin.end).map((ns, j) => {
                  const i = nsWin.start + j;
                  const key = nsKey(ns.name);
                  const rowProps = sel.props(key);
                  return (
                  <TreeRow key={ns.name} depth={0} kids={false} open
                           selected={sel.has(key)}
                           joinAbove={i > 0 && sel.has(nsKey(shownNs[i - 1].name))}
                           joinBelow={i < shownNs.length - 1
                                      && sel.has(nsKey(shownNs[i + 1].name))}
                           icon="label" label={`${ns.name}:`} q={needle}
                           count={ns.count}
                           hidden={ns.hidden}
                           rowProps={rowProps}
                           onClick={rowProps.onClick}
                           onMenu={onNamespaceMenu
                             ? (ev) => onNamespaceMenu(ev, ns) : undefined} />
                  );
                })}
                </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
