import React, { useCallback, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { TagsPageSwitch } from "./TagsPageSwitch";
import { storage } from "../../shared/storage";
import { RECORD_ICON } from "../../shared/metaEnums";
import { SearchField } from "../../shared/SearchField";
import { rowBackground } from "../../shared/Row";
import { Chip } from "../../shared/Chip";
import { IconButton } from "../../shared/IconButton";
import { Button } from "../../shared/Button";
import { EmptyState } from "../../shared/EmptyState";
import { fieldStyleSm } from "../../shared/Field";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { confirm } from "../../shared/ConfirmModal";
import { api, EventRow, FaceRow, LinkTagRow, PlaceRow, RankingItemRef, SubjectRow, TagRow, TagSetCategoryOut, TagSetEntryOut, TagSetOut, TagSetText } from "../api";
import { TagsSidebar, TOOLBAR_GAP, TOOLBAR_TOP, toolbarBtn, useCategoryTree,
         type TagsNarrowing } from "./TagsSidebar";
import { PAGE_PAD } from "./TagsPanes";
import { TagsPanes, usePaneHeight } from "./TagsPanes";
import { useCategoryDrag, useCategoryOps } from "./categoryOps";
import { freeSetName, makeEditableCopy, TagSetShelf } from "./TagSetShelf";
import { bumpEdits } from "../invalidation";
import { MetaTagsEmpty, TagSetMetaList } from "./TagSetMetaList";
import { LOOSE_DROP } from "./TagsTree";
import { CategoryTrail, trailLabel } from "./CategoryTrail";
import { Icon } from "../../shared/Icon";
import { TagsGrouping, TagsModeAsked, TagsRelation, TagsScope, TagsSuggest,
         modalIsOpen, useUI } from "../store";
import { useErrText, useLang, useT, useTn } from "../i18n";
import { compactCount } from "../format";
import { sanitizeLinkTagInput, tagFieldInput, tagFieldName } from "../tags";
import { chunks } from "../bulk";
import { exactFirst } from "../exactFirst";
import { TagCsvButtons } from "./TagCsvOverlay";
import { TagEditOverlay, AddMenu, AddTagMenu, AliasCreateOverlay } from "./TagEditOverlay";
import { TagMergeOverlay } from "./TagMergeOverlay";
import { RowAction, RowMenu } from "../../shared/RowMenu";
import { useRowSelect } from "./shared/useRowSelect";
import { downloadBlob } from "../csv";
import { MetaTagEditOverlay, MetaTagMergeOverlay } from "./MetaTagEditOverlay";
import { formatDate } from "../../query/subjects/when";
import { spanLabel } from "./EventsSection";
import { placeLabel, shortPlace } from "../../query/places/formats";
import { TagAutocomplete } from "./TagAutocomplete";
import { MetaCapsules } from "./MetaCapsules";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { FieldLabel, GhostButton, Overlay, PrimaryButton, fieldStyle }
  from "../../shared/Overlay";
import { DescriptionMark } from "./DescribedFields";
import { FilterMenu, type FilterSection } from "./FilterMenu";
import { Mark } from "./Mark";
import { ActionToast } from "./shared/ActionToast";
import { useUndoBar } from "./shared/useUndoBar";
import { PointerMenu } from "../../shared/RowMenu";
import { MediaKindMenu } from "./shared/MediaKindMenu";
import { SearchKind, useSearchActions } from "./shared/searchActions";

/** What a row offers of its OWN, beside the shared search entries: its
 *  editor (the context menu's first entry), any further entries (a tag's
 *  record editors), and its deletion. */
interface RowOwn {
  edit?: () => void;
  more?: RowAction[];
  remove?: () => void;
}
import { useWindowedList } from "../useWindowedList";
import { ancestorsOf, flattenTree } from "../treeRows";
import { namespacedRows, nestAliases, type ItemsListEntry } from "../tagNamespaceRows";
import { tagCount, tagNamespace } from "../tags";
import { CHECK_W, columnsFor, gridTemplate, shownColumns } from "../tagSetColumns";
import { useTagSetVerbs } from "./tagSetVerbs";
import { AliasOverlay, CategoryEditOverlay, EntryEditOverlay } from "./TagSetsView";
import { TagSetCsvOverlay } from "./TagSetCsvOverlay";

type Mode = "items" | "links" | "tagsets";

//: WHAT THE LIST IS SORTED BY. The name and the comment, then one per
//  NUMERIC COLUMN of the tag set on screen (`tagSetColumns.ts`:
//  positive/implicit/negative, or an imported set's library/count),
//  plus a set's two orders of its own — where the file put the name,
//  and the category it is filed in. The Meta list has its four
//  carriers. A string, since the columns are a table now.
type SortKey = string;
type SortDir = "asc" | "desc";

// Column templates: checkbox, then the mode's columns. What a tag implies has
// no column of its own — it reads under the tag's own name, where it belongs
// (a column of chips left the table lopsided and the names cramped). The
// implicit count DOES have one: it is a number among numbers, and in brackets
// beside the positive one it could not be sorted by or read down the column.
// Tag, Comment, Positive, [Implicit], Negative — the bracketed one APPEARS
// ONLY WHEN SOMETHING USES IT. A column of blanks is a column that says
// nothing; the count columns are narrow, so its absence is what gives the
// name and the comment room. (There USED to be an [Offset] column here too —
// the tag-level count offset. What a tag has elsewhere lives per META-TAG
// assignment now and rides the capsules behind the name, "tumblr 900".)
/** THE FOLD COLUMN. Every row of a tag list reserves it, chevron or no
 *  chevron: a name that shifts sideways depending on whether its row folds
 *  something is a list whose left edge moves as you scroll. A namespace
 *  parent folds its names, a tag folds its other spellings, everything else
 *  leaves the slot empty. */
const FOLD_W = 15;

/** HOW MANY LEADING ROWS THE INDEX CARRIES WHOLE.
 *
 *  A window is tens of rows and `windowIds` pads twenty either side, so this
 *  covers the screenful a narrowing opens on with room to spare — and it is
 *  what lets that listing arrive with its comments, trails and capsules
 *  already on it instead of gaining them a round trip later. Past it the
 *  band fetch does what it has always done. */
const INDEX_ROWS = 120;
const FOLD_GAP = 4;
/** WHERE THE NAME STARTS inside its cell — the fold column every row
 *  reserves, its own margin, and the name LINE's flex `gap` after it. The
 *  subtitles under it (what a tag implies, what a record's row says) are
 *  siblings of that line rather than of the name, so left alone they begin
 *  at the cell's edge and hang out to the left of the name they belong to.
 *  MEASURED, not eyeballed: the first attempt left the gap out and was six
 *  pixels short, which reads as a wobble rather than as an indent. */
const NAME_INDENT = FOLD_W + (FOLD_GAP - 6) + 6;
/** How far a child sits in from its parent — one step, on top of the fold
 *  column both of them reserve, so a child's name starts exactly one indent
 *  past its parent's rather than under its parent's chevron. */
const INDENT = 16;

const itemGrid = (implicit: boolean) =>
  ["26px", "minmax(0, 2fr)", "88px",
   ...(implicit ? ["88px"] : []),
   "88px"].join(" ");
// One count per CARRIER of the meta namespace, not one "uses" total: the three
// are what the namespace is, and a rename that strands one of them is exactly
// what the split makes visible.
const LINK_GRID = `${CHECK_W}px minmax(0, 3.3fr) 78px 78px 86px 78px`;
// Tag Comment Links Captions Groups Tags — one column per CARRIER of the
// namespace, so "used 7 times" never has to stand for four different things.
// A subject row is a tag row with an identity in front of it: the name people
// use, the comment that tells namesakes apart, the slug items actually carry.
// A place row is its address line, the identity tag, and the count.
// An event row is its name (with its venues underneath — a chips column
// would leave the table lopsided, the way the implications one did), the
// span of days, the identity tag, and the count.
// The unnamed clusters are a list of their own: no name, no comment and no
// tag to put in a column, so it holds only what a cluster actually has.

export function TagsView() {
  const { data: linkRows } = useQuery({ queryKey: ["link-tag-rows"], queryFn: api.linkTagRows });
  const { data: stats } = useQuery({ queryKey: ["library-stats"], queryFn: api.libraryStats });
  const { data: subjectRows } = useQuery({ queryKey: ["subjects"], queryFn: api.subjects });
  const { data: placeRows } = useQuery({ queryKey: ["places"], queryFn: api.places });
  const { data: eventRows } = useQuery({ queryKey: ["events"], queryFn: api.events });
  const { data: tagSetRows } = useQuery({
    queryKey: ["tag-sets"], queryFn: api.tagSets });
  // NOTHING IN THIS LIST IS LOCKED. A ranking used to own a namespace, and
  // its minted rows offered no pencil, no context menu and were skipped by
  // Delete, because the backend refused every one of those edits on a
  // derived name. A ranking owns no names (rung v31), so every row here is
  // somebody's tag and every verb applies to it.
  const tr = useT();
  const tn = useTn();
  const lang = useLang();
  const qc = useQueryClient();
  // WHICH NAMESPACES THE AUTOCOMPLETE SKIPS — a setting rather than rows, so
  // the parent rows have to be told. Cheap and rarely changing; invalidated
  // with the rest of `["tags"]` when one is hidden.
  const { data: hiddenNsData } = useQuery({
    queryKey: ["tags", "hidden-namespaces"],
    queryFn: api.hiddenNamespaces,
  });
  const hiddenNs = hiddenNsData ?? [];
  const setLibrarySearch = useUI((s) => s.setSearch);
  const setSelectedItems = useUI((s) => s.setSelectedItems);
  const setView = useUI((s) => s.setView);
  const showAllItems = useUI((s) => s.showAllItems);

  // Which sub-tab, and how it is narrowed, live in the STORE: this view is
  // unmounted whenever another tab is showing, and rebuilding the narrowing
  // every time you come back is exactly what made it tiresome. Read as
  // primitives — an object selector would be a new object per render.
  const mode = useUI((s) => s.tagsView.mode);
  const kind = useUI((s) => s.tagsView.kind);
  const media = useUI((s) => s.tagsView.media);
  const relation = useUI((s) => s.tagsView.relation);
  const scope = useUI((s) => s.tagsView.scope);
  const grouping = useUI((s) => s.tagsView.grouping);
  const showReps = useUI((s) => s.tagsView.reps);
  const suggest = useUI((s) => s.tagsView.suggest);
  const metaTag = useUI((s) => s.tagsView.metaTag);
  const countRanges = useUI((s) => s.tagsView.counts);
  // THE SIDEBAR'S TWO AXES. The category selection IS the narrowing — one
  // state, so the tree's highlight and the list can never disagree — and the
  // namespace is the derived one beside it.
  const catPicked = useUI((s) => s.tagsView.category);
  const uncategorizedOnly = useUI((s) => s.tagsView.uncategorized);
  const nsPicked = useUI((s) => s.tagsView.namespaces);
  const catKey = catPicked.join(",");
  const nsKey = nsPicked.join(",");
  // THE TWO LISTS THE LEFT PANE LEADS TO: the library's names, and the
  // labels ON them. Meta was a sub-tab of its own until 2026-09; it is a
  // row of the pane now (see `TagsSidebar`), so both modes draw the pane
  // and everything it needs has to be fetched for both.
  //: THE LIST IS ONE LIST (owner 2026-09): the library's own names and an
  //  imported set's are the same page with the same two columns, and which
  //  tag set is on screen is a pill above them. `withSidebar` is "this
  //  mode draws the way IN beside its list".
  const withSidebar = mode === "items" || mode === "links"
    || mode === "tagsets";
  /** …and this one is "the list proper", either tag set — as against
   *  the Meta list beside it, which is its own three columns. */
  const isTagList = mode === "items" || mode === "tagsets";
  //: The new-category dialog, which is also what makes the library's set
  //  row the first time (`POST /api/tags/categories`).
  const [addingCategory, setAddingCategory] = useState(false);
  //: The two columns' own box, so the panes beside it can be measured
  //  against what sits above them (`usePaneHeight`).
  const columnsRef = useRef<HTMLDivElement>(null);
  // THE ROW OF PILLS, on this half of the tab too. One row across both — the
  // library first, then the tag sets — is what makes the Items list and
  // a set's entry list read as one page rather than two sub-tabs.
  //
  // The verbs a set's pill carries live where that set is EDITED, so picking
  // one goes there; the library's own pill offers the one verb this page can
  // serve, which is the export that is the point of calling it a set.
  const setTagSetId = useUI((st) => st.setTagSetId);
  const openSetId = useUI((st) => st.tagSetId);
  // WHAT THE SIDEBAR DRAWS. The library's own set holds the categories its
  // tags are filed in; it is LAZY, so until something files a tag there is
  // no set, no tree and nothing to fetch — which is exactly the state a new
  // library is in and reads as an empty Categories block.
  const setsQuery = useQuery({
    queryKey: ["tag-sets"], queryFn: api.tagSets,
    enabled: withSidebar });
  /** The set whose page is open, for the subtitle.
   *
   *  THE FALLBACK PREFERS A SET THAT IS SWITCHED ON. Every library now holds
   *  the app's own built-in sets, switched OFF and holding nothing until
   *  somebody wants them, and the first row by position is one of those on a
   *  fresh library — so a bare "the first set there is" opened the tab on an
   *  empty list nobody asked for. A set picked BY ID still opens whatever it
   *  is, switched on or not. */
  const openSet = useMemo(
    () => (setsQuery.data ?? []).find((x) => x.id === openSetId && !x.library)
      ?? (setsQuery.data ?? []).find((x) => !x.library && x.enabled)
      ?? (setsQuery.data ?? []).find((x) => !x.library) ?? null,
    [setsQuery.data, openSetId]);
  /** WHICH TAG SET THE LIST IS SHOWING: null is the library's own names,
   *  an id is that imported set's.
   *
   *  ONE LIST, ONE PATH (owner 2026-09). Picking a pill does not switch to
   *  another component any more — it changes which tag set this one is
   *  about, and the server answers `/api/tags/index` for either. */
  const shownSetId = mode === "tagsets" ? (openSet?.id ?? null) : null;
  const librarySet = useMemo(
    () => setsQuery.data?.find((x) => x.library) ?? null, [setsQuery.data]);
  const librarySetId = librarySet?.id ?? null;
  /** THE TAG SET THE PANE IS ABOUT, as a set row — an imported set, or
   *  the library's own (lazy) one. What a category dialog opens over. */
  const openTagSet = shownSetId != null ? openSet : librarySet;
  /** THE SET ON SCREEN IS ONE OF THE APP'S OWN, so nothing here may write
   *  it: no entry, no category, no spelling. Keyed off `shownSetId` and
   *  never `paneSetId` — that one falls back to the LIBRARY's set, which is
   *  never built-in and whose categories stay the person's to edit. */
  const readOnly = shownSetId != null && !!openSet?.builtin;
  /** MAKE EDITABLE, in the read-only set's toolbar where Add category is
   *  on an editable one (`makeEditableCopy`): the copy is opened once it
   *  stands in the list, and a refusal is said on the button. */
  const errText = useErrText();
  const [makeEditableError, setMakeEditableError] = useState("");
  const makeEditable = useMutation({
    mutationFn: (src: TagSetOut) => {
      const sets = setsQuery.data ?? [];
      return makeEditableCopy(sets, src,
        freeSetName(sets, tr("{name} (copy)", { name: src.name })));
    },
    onSuccess: (made) => {
      setMakeEditableError("");
      setTagSetId(made.id);
      qc.invalidateQueries({ queryKey: ["tag-sets"] });
      qc.invalidateQueries({ queryKey: ["tags"] });
      bumpEdits();
    },
    // Whatever got as far as the server stands (each step is its own
    // request), so the list is re-read either way.
    onError: (e) => {
      setMakeEditableError(errText(e));
      qc.invalidateQueries({ queryKey: ["tag-sets"] });
    },
  });
  /** THE SET WHOSE CATEGORIES, NAMESPACES AND COUNTS THE PANE IS ABOUT —
   *  the picked tag set's own. The library files its tags in its own
   *  (lazy) set's categories, an imported set in its own; same rows, same
   *  endpoints, one id. */
  const paneSetId = shownSetId ?? librarySetId;
  const libraryDetail = useQuery({
    queryKey: ["tag-sets", paneSetId],
    queryFn: () => api.tagSet(paneSetId as number),
    enabled: paneSetId != null,
  });
  //: A TAG SET'S OWN META TAGS — the labels it puts on its names. The
  //  LIBRARY's are `linkRows`; an imported set carries its own, which
  //  travel in its file.
  const { data: setMetaRows } = useQuery({
    queryKey: ["tag-sets", shownSetId ?? 0, "meta-tags"],
    queryFn: () => api.tagSetMetaTags(shownSetId as number),
    enabled: shownSetId != null });
  const namespaceRows = useQuery({
    queryKey: ["tags", "namespaces", shownSetId ?? 0],
    queryFn: () => (shownSetId == null ? api.tagNamespaces()
                    : api.tagSetNamespaces(shownSetId)),
    enabled: withSidebar });
  //: THE SIDEBAR'S TREE — its expansion, its search and its scroller, held
  //  here because landing on a category (a `?` popover's "in the set", a
  //  row's category trail) has to open the ancestors and pick the row in
  //  one event.
  const libCats = libraryDetail.data?.category_rows ?? [];
  const libCatsRef = useRef(libCats);
  libCatsRef.current = libCats;
  const catAncestors = useCallback(
    (id: number) => ancestorsOf(libCatsRef.current, id), []);
  const catTree = useCategoryTree(libCats, catAncestors);
  const catOps = useCategoryOps(paneSetId, libCats);
  // DRAGGING THE TREE, and dragging rows onto it — `useCategoryDrag`, the
  // Sets tab's own gesture and the same code: the library's categories are
  // the same rows behind the same endpoints, so reordering one is the same
  // request. Only a PICKED row is a drag SOURCE for the payload: the paint
  // gesture owns an unpicked one and a native drag would swallow it.
  const catDrag = useCategoryDrag({
    setId: paneSetId, cats: libCats,
    onDropPayload: (ids, categoryId) => {
      if (!ids.length) return;
      void api.setTagCategory(ids, categoryId, shownSetId).then(() => {
        qc.invalidateQueries({ queryKey: ["tags"] });
        qc.invalidateQueries({ queryKey: ["tag-sets"] });
      });
    },
    onChanged: () => {
      qc.invalidateQueries({ queryKey: ["tag-sets"] });
    },
  });
  //: The category the dialog is open on — a row, or a fresh one inside it
  //  (id -1). ONE dialog for both tag sets, since a category is the same
  //  row in either: the library files its tags in its own set's, an
  //  imported set in its own.
  const [editingCat, setEditingCat] = useState<TagSetCategoryOut | null>(null);
  //: Whether the pane's Meta row is what is on screen, for a SET. The
  //  library's own labels are a mode (`links`); a set's are this list
  //  standing aside for `TagSetMetaList`, which is what its Meta row is.
  const [setMetaOpen, setSetMetaOpen] = useState(false);
  //: THE LIBRARY ALIAS whose two fields are open — its name and what it
  //  stands for, which is the whole of what an alias is.
  const [editingAlias, setEditingAlias] = useState<TagRow | null>(null);
  //: …and a SET's spelling being pointed somewhere else: the spelling, and
  //  the name it spells today.
  const [retarget, setRetarget] = useState<
    { alias: string; fromName: string } | null>(null);
  useEffect(() => { setSetMetaOpen(false); }, [shownSetId]);
  const setCategoriesHidden = (ids: number[], hidden: boolean) => {
    void catOps.setHidden(ids, hidden).then(() => {
      qc.invalidateQueries({ queryKey: ["tag-sets"] });
      qc.invalidateQueries({ queryKey: ["tags"] });
    });
  };
  // ONE MENU PER ROW, AND ON A PICKED ROW IT IS THE SELECTION'S. A
  // right-click on one of several picked rows is about the several — the
  // list's own rule — so the single-row verbs (edit it, add one inside it)
  // stand down: neither means anything for five rows at once. A right-click
  // on an UNPICKED row stays about that row and leaves the selection alone.
  const catActions = (c: TagSetCategoryOut): RowAction[] => {
    const many = catPicked.includes(c.id) && catPicked.length > 1;
    if (many) {
      const anyShown = catPicked.some(
        (id) => !libCats.find((x) => x.id === id)?.hidden);
      return [
        { icon: anyShown ? "visibility_off" : "visibility",
          label: anyShown ? tr("Hide from the autocomplete")
                          : tr("Show in the autocomplete"),
          onClick: () => setCategoriesHidden(catPicked, anyShown) },
        { icon: "delete", danger: true, separated: true, label: tr("Delete"),
          hint: tr("Everything under them goes too; the entries stay, uncategorized."),
          onClick: () => void deleteCategories(catPicked) },
      ];
    }
    return [
      { icon: "edit", label: tr("Edit category"),
        onClick: () => setEditingCat(c) },
      { icon: "create_new_folder", label: tr("Add a category inside"),
        onClick: () => setEditingCat({ ...c, id: -1, parent_id: c.id,
                                       name: "", trail: [] }) },
      { icon: c.hidden ? "visibility" : "visibility_off",
        label: c.hidden ? tr("Show in the autocomplete")
                        : tr("Hide from the autocomplete"),
        onClick: () => setCategoriesHidden([c.id], !c.hidden) },
      { icon: "delete", label: tr("Delete category"), danger: true,
        separated: true,
        hint: tr("Everything under it goes too; the entries stay, uncategorized."),
        onClick: () => void deleteCategories([c.id]) },
    ];
  };
  const deleteCategories = async (ids: number[]) => {
    if (!await catOps.remove(ids)) return;
    // The selection goes with the rows — and with it the list's narrowing,
    // which IS that selection.
    patch({ category: [] });
    qc.invalidateQueries({ queryKey: ["tag-sets"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
  };
  //: The bounds as the wire takes them — only what somebody typed, so an
  //  absent end is no bound rather than a zero.
  const rangeParams = useMemo(() => {
    const p: Record<string, number> = {};
    //: A COLUMN'S KEY ON THE WIRE. The three-letter prefixes are what the
    //  endpoint has always taken; a set's two are their own names.
    const wire: Record<string, string> = {
      positive: "pos", implicit: "ind", negative: "neg",
      library: "lib", count: "cnt" };
    for (const [col, key] of Object.entries(wire)) {
      const r = countRanges?.[col];
      if (r?.lo != null) p[`${key}_min`] = r.lo;
      if (r?.hi != null) p[`${key}_max`] = r.hi;
    }
    return p;
  }, [countRanges]);
  const rangeKey = JSON.stringify(rangeParams);
  const setRange = (col: string,
                    r: { lo: number | null; hi: number | null }) =>
    patch({ counts: { ...countRanges, [col]: r } });
  // WHICH NAMESPACE GROUPS ARE FOLDED — per browser, like the sidebar's
  // remembered heights: which groups you keep closed is working state, not a
  // fact about the library.
  const [collapsedNs, setCollapsedNs] = useState<Set<string>>(() => {
    try {
      return new Set<string>(
        JSON.parse(storage.get("mc.tags.collapsedNs") || "[]"));
    } catch { return new Set<string>(); }
  });
  const collapsedNsRef = useRef(collapsedNs);
  collapsedNsRef.current = collapsedNs;
  useEffect(() => {
    storage.set("mc.tags.collapsedNs",
                         JSON.stringify([...collapsedNs].sort()));
  }, [collapsedNs]);
  const toggleNs = (ns: string) => setCollapsedNs((cur) => {
    const next = new Set(cur);
    if (next.has(ns)) next.delete(ns); else next.add(ns);
    return next;
  });
  //: …AND WHICH TAGS HAVE THEIR SPELLINGS FOLDED AWAY, by the tag's own
  //  lowercased name. A namespace's chevron and a tag's are the same
  //  gesture over the same kind of thing — the rows drawn under this one —
  //  so they are remembered the same way: per browser, since which groups
  //  you keep closed is working state rather than a fact about the library.
  const [collapsedAlias, setCollapsedAlias] = useState<Set<string>>(() => {
    try {
      return new Set<string>(
        JSON.parse(storage.get("mc.tags.collapsedAliases") || "[]"));
    } catch { return new Set<string>(); }
  });
  useEffect(() => {
    storage.set("mc.tags.collapsedAliases",
                         JSON.stringify([...collapsedAlias].sort()));
  }, [collapsedAlias]);
  const toggleAliases = (name: string) => setCollapsedAlias((cur) => {
    const next = new Set(cur);
    const key = name.toLowerCase();
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const search = useUI((s) => s.tagsView.search);
  // The LISTS follow the search a beat behind the field. Filtering, sorting
  // and the namespace weave are a few hundred milliseconds over a six-figure
  // catalog even with the cached collator, and run synchronously inside the
  // render — deferred, the keystroke paints first and one settled pipeline
  // pass follows, instead of every character blocking the input for its own
  // full pass.
  const dSearch = useDeferredValue(search);
  const sortKey = useUI((s) => s.tagsView.sortKey);
  const sortDir = useUI((s) => s.tagsView.sortDir);
  const patch = useUI((s) => s.setTagsView);
  // Switching sub-tab resets that sub-tab's filters (they mean different things
  // in each), which is why this is an action rather than an effect on `mode`:
  // an effect fires on every remount too, and would undo what is being kept.
  const setMode = useUI((s) => s.setTagsMode);
  const setKind = (v: typeof kind) => patch({ kind: v });
  // What each narrowing asks for, named once. `scope` is one axis in every
  // list, so every list reads it the same way.
  const unassignedOnly = scope === "unassigned";
  const aliasesOnly = relation === "aliases";
  const impliesOnly = relation === "implies";

  // THE ITEMS LIST IS AN INDEX PLUS A WINDOW, not a catalog.
  //
  // `/api/tags` is every row of the tag set — 60 MB and 4.2 s at 250,000
  // tags — and this list showed sixty of them at a time. What it needs about
  // ALL of them is what its own machinery asks: the name (grouping, folding,
  // jumping, select-all) and the counts (the parents' totals, the count
  // columns, "unassigned"). That is the INDEX, 10 MB and 1.0 s, and every
  // filter and sort that used to run in the browser runs in the query that
  // produces it. The rest of a row — its comment, its implications, its meta
  // capsules — is fetched for the window on screen (`useTagDetails`).
  const indexQuery = useQuery({
    queryKey: ["tags", "index", shownSetId ?? 0, dSearch, sortKey, sortDir,
               kind, media.join(","),
               aliasesOnly, impliesOnly, unassignedOnly, suggest,
               metaTag, rangeKey, catKey, uncategorizedOnly, nsKey],
    queryFn: () => api.tagIndex({
      q: dSearch.trim(), sort: sortKey, dir: sortDir, kind, media: media.join(","),
      aliases: aliasesOnly, implies: impliesOnly, unassigned: unassignedOnly,
      suggest, meta: metaTag,
      // WHICH TAG SET. One endpoint, one index, one list.
      ...(shownSetId == null ? {} : { set_id: shownSetId }),
      // THE SIDEBAR'S TWO AXES. They intersect: a category is authored and
      // a namespace is read off the name, so `artist:kantoku` is under
      // `artist:` whatever it is filed in.
      category: catKey, uncategorized: uncategorizedOnly, namespaces: nsPicked,
      ...rangeParams,
      // …AND THE FIRST SCREENFUL WHOLE, so a listing arrives with its
      // comments, trails and capsules already on it (`INDEX_ROWS`).
      rows: INDEX_ROWS,
    }),
    // Keep the previous answer while a new one loads: the filter is typed
    // into, and a list that empties between keystrokes reads as broken.
    placeholderData: (prev) => prev,
    enabled: isTagList,
  });
  const tags = useMemo<TagRow[] | undefined>(() => {
    const d = indexQuery.data;
    if (!d) return undefined;
    const hidden = new Set(d.hidden ?? []);
    const byNs = new Set(d.hidden_ns ?? []);
    return d.ids.map((id, i) => ({
      id, name: d.names[i],
      // THE NUMERIC COLUMNS THIS TAG SET HAS, whichever they are — the
      // library's three counts of pictures or an imported set's pair. The
      // list draws `columns` and reads `numbers[key]`, so a column added on
      // either side needs nothing here.
      numbers: Object.fromEntries(
        Object.entries(d.numbers ?? {}).map(([k, v]) => [k, v[i]])),
      alias_of: d.alias_of[i] || null,
      // KNOWN FOR EVERY ROW, from the index — the mark is not something to
      // wait for a detail fetch to learn.
      hidden: hidden.has(i),
      hidden_ns: byNs.has(i),
      // What only the window needs — filled in from `details` at render.
      comment: "", implies: [], meta_tags: [],
      meta_counts: {}, tag_sets: [], descriptions: null,
    }));
  }, [indexQuery.data]);
  /** THE LEADING ROWS THE INDEX ITSELF CARRIED, by id.
   *
   *  Built during the RENDER, not filled in by an effect: an effect runs
   *  after the commit, so the first paint of a new listing would still be
   *  the names alone and the row would grow its comment one render later —
   *  which is the jump this exists to end. `detailsRef` still wins, since a
   *  band refetched after an edit is the fresher answer. */
  const indexRows = useMemo(() => {
    const m = new Map<number, TagRow>();
    for (const r of indexQuery.data?.rows ?? []) m.set(r.id, r);
    return m;
  }, [indexQuery.data]);
  //: THE NUMERIC COLUMNS THIS LIST DRAWS — the tag set's own, less the
  //  ones no row has a figure in (`tagSetColumns.ts`). Over the INDEX rather
  //  than the filtered rows: a column that came and went as you typed in
  //  the search field would move every number under the cursor.
  const numCols = useMemo(
    () => shownColumns(columnsFor(shownSetId), tags ?? []),
    [shownSetId, tags]);
  //: A SORT THE TAG SET ON SCREEN HAS NO COLUMN FOR falls back to its
  //  FIRST — switching from the library's Positive to a set, which counts
  //  no pictures, otherwise left the list ordered by a column that is not
  //  there and no heading lit.
  useEffect(() => {
    const cols = columnsFor(shownSetId).map((c) => c.key);
    const known = ["name", "comment", "category", "position", ...cols];
    if (!known.includes(sortKey)) {
      patch({ sortKey: cols[0] ?? "name", sortDir: "desc" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shownSetId, sortKey]);
  const showImplicit = numCols.some((c) => c.key === "implicit");
  const setSearch = (v: string) => patch({ search: v });
  const setSortKey = (v: SortKey) => patch({ sortKey: v });
  const setSortDir = (v: SortDir | ((p: SortDir) => SortDir)) =>
    patch({ sortDir: typeof v === "function" ? v(sortDir) : v });

  // The right-clicked row's menu. Every one of these four lists is a list of
  // TAGS, so every row answers the same two questions about the Library — and
  // one menu serves all of them rather than one per list.
  const [rowMenu, setRowMenu] = useState<
    { at: { x: number; y: number }; kind: SearchKind; name: string;
      label?: string; own?: RowOwn;
      /** The menu is about the whole SELECTION, not one row. */
      selection?: boolean } | null>(null);
  const searchActions = useSearchActions();
  // THE ROW'S MENU IS ONE LIST, whichever door opens it. The ⋯ on a row and
  // the right-click on it used to hold different things — the search
  // entries in one, the record editors in the other — and a menu that
  // changes with the button reads as unreliable. `rowActionsFor` builds the
  // list once: the row's own entries (the record editors on a tag), the two
  // search entries, and Delete last behind a rule; the context menu puts Edit
  // on top, since the pencil is not under the pointer there.
  /** WHAT AN IMPORTED SET'S ROW OFFERS. A library tag is renamed, merged
   *  and assigned; a set's name is ADVICE, so its row offers to make the
   *  library's tag say what the set says, or to make the tag at all
   *  (`tagSetVerbs.tsx`). One list, one row, two sets of verbs — which is
   *  the only thing about the two lists that was ever really different. */
  /** A ROW OF THE ONE LIST, as a set's ENTRY. The two shapes are the same
   *  facts under two names — the row carries the tag set's numbers in a
   *  map where the entry has them as fields — and this is the one place
   *  that says so, for the editor a set's names share with the Sets file
   *  and the CSV. */
  const asEntry = (t: TagRow): TagSetEntryOut => ({
    id: t.id, name: t.name, description: t.description ?? "",
    count: t.numbers?.count ?? null,
    category_id: t.category_id ?? null,
    category_trail: t.category_trail ?? [],
    position: t.position ?? 0, alias_of: t.alias_of ?? null,
    aliases: t.aliases ?? [], implies: t.implies ?? [],
    meta: t.meta_tags ?? [],
    missing_implies: t.missing_implies ?? [],
    implications_off: !!t.implications_off,
    in_library: !!t.in_library,
    library_count: t.numbers?.library ?? null,
    comment: t.comment ?? "",
    subject: t.subject ?? null, place: t.place ?? null, event: t.event ?? null,
    missing_records: t.missing_records ?? [],
  });
  /** A SET AS THE FILE IT CAME FROM — what its toolbar's Export does, and
   *  what its pill's ⋯ offers, one definition apart. */
  const exportSet = async (st: { id: number; key: string }) => {
    const text = await api.exportTagSet(st.id);
    downloadBlob(`${st.key}.json`,
                 new Blob([text], { type: "application/json" }));
  };
  //: A CSV read INTO the set on screen, as against one that becomes a set
  //  of its own (the "+" pill's).
  const [csvIntoSet, setCsvIntoSet] = useState(false);
  const csvIntoRef = useRef<HTMLInputElement>(null);
  const [csvFileForSet, setCsvFileForSet] = useState<File | null>(null);
  useEffect(() => {
    if (csvIntoSet) { csvIntoRef.current?.click(); setCsvIntoSet(false); }
  }, [csvIntoSet]);
  const setVerbs = useTagSetVerbs(shownSetId, () => {
    qc.invalidateQueries({ queryKey: ["tags"] });
  }, readOnly);
  const rowActionsFor = (kind: SearchKind, name: string, label?: string,
                         own?: RowOwn, withEdit = false): RowAction[] => {
    const out: RowAction[] = [];
    if (withEdit && own?.edit) out.push({ icon: "edit", label: tr("Edit…"), onClick: own.edit });
    // Edit stands alone above a rule: it is about THIS row's record, where
    // everything under it is about what the tag might be or where it is.
    const more = own?.more ?? [];
    if (more.length) out.push({ ...more[0], separated: out.length > 0 }, ...more.slice(1));
    const search = name ? searchActions(kind, name, label) : [];
    if (search.length) {
      search[0] = { ...search[0], separated: out.length > 0 };
      out.push(...search);
    }
    if (own?.remove) {
      out.push({ icon: "delete", label: tr("Delete"), danger: true, separated: out.length > 0,
                 onClick: own.remove });
    }
    return out;
  };
  // What a TAG row itself offers: the record it might be (subject, place,
  // event — edit the one it is, add the one it is not), and its deletion.
  //: NO "FILE UNDER" IN EITHER MENU (owner 2026-09). It was a submenu of
  //  every category the library has — on a row's ⋯, on its right-click and
  //  over a selection — and filing is a DRAG now: a picked row carries onto
  //  a category in the tree beside the list (`categoryOps.useCategoryDrag`),
  //  which is the gesture the Sets tab always had. A menu that lists four
  //  hundred categories to do what the pointer does in one move is the
  //  longer way round, and it was the one thing in these menus that grew
  //  with the tag set.

  const tagRowOwn = (t: TagRow, key: string): RowOwn => {
    return {
      edit: t.alias_of == null ? () => setEditing(t) : undefined,
      more: [
        // NO "Add subject / place / event" HERE (owner 2026-09). All three
        // were one editor opened at one of its sections, and that editor is
        // what Edit… opens: three entries on every row of a 200,000-name
        // list, saying what the dialog above them already says, for a
        // question most rows never answer. What a row IS is still on the
        // row — the record marks after the name — and the sidebar's three
        // rows are how you find the ones that are.
        // KEPT OUT OF THE AUTOCOMPLETE, or put back. A booru dump puts a
        // hundred thousand names in front of every field somebody types in,
        // while most of a library's own work happens in a few hundred of
        // them. Not a deletion and not a scope: the tag assigns, searches,
        // counts and stays in this list — it stops being SUGGESTED.
        { icon: t.hidden ? "visibility" : "visibility_off", separated: true,
          label: t.hidden ? tr("Suggest again") : tr("Hide from suggestions"),
          onClick: () => void hideTags([t.name], !t.hidden) },
      ],
      remove: () => void deleteKeys([key]),
    };
  };
  /** WHAT A NAMESPACE ROW OFFERS — one verb, in the ⋯ and in the
   *  right-click alike, so the two doors cannot say different things. Its
   *  tags have no row in common to flag, so this is a SETTING, which is
   *  what makes it the useful verb: it takes the names made LATER with the
   *  namespace as well as the ones here now, and a dump's `artist:` names
   *  keep arriving. */
  const nsActions = (ns: string): RowAction[] => {
    const off = hiddenNs.includes(ns.toLowerCase());
    return [{
      icon: off ? "visibility" : "visibility_off",
      label: off ? tr("Suggest this namespace again")
                 : tr("Hide this namespace from suggestions"),
      onClick: () => void hideNamespace(ns, !off),
    }];
  };
  /** Hide (or unhide) these tags, then refresh: the flag rides on the ROW,
   *  and the autocomplete reads it server-side. */
  const hideTags = async (names: string[], hidden: boolean) => {
    await api.setTagsHidden(names, hidden);
    qc.invalidateQueries({ queryKey: ["tags"] });
  };
  /** …and the same for a whole NAMESPACE, which is a setting rather than
   *  rows: hiding one takes the tags made LATER with it as well as the ones
   *  there now, which is the point — a dump's `artist:` names keep coming. */
  const hideNamespace = async (ns: string, hidden: boolean) => {
    const clean = ns.replace(/:$/, "").toLowerCase();
    const cur = await api.hiddenNamespaces();
    const next = hidden
      ? (cur.includes(clean) ? cur : [...cur, clean])
      : cur.filter((n: string) => n !== clean);
    await api.setHiddenNamespaces(next);
    qc.invalidateQueries({ queryKey: ["tags"] });
  };
  // A RIGHT-CLICK ON A SELECTED ROW, WITH SEVERAL SELECTED, IS ABOUT THE
  // SELECTION — the grid's context-menu rule: the row's own entries (edit,
  // add a subject, search) mean nothing over five rows, and what does is
  // what the toolbar offers the selection — Merge and Delete, with the
  // counts the toolbar's buttons carry. A right-click on an UNSELECTED row
  // stays about that row alone and leaves the selection as it is.
  //
  // ONE DEFINITION, and the toolbar's ⋯ opens it too. The toolbar used to
  // grow a button per verb — Delete, then Merge, then whatever came next —
  // which meant deciding which verbs were worth a button, in a strip that
  // also holds the search field and the filters; and the context menu, built
  // separately, then said something else about the same rows.
  // The rows the list holds, for Select all — filled in where they are
  // computed below, since the menu is built above them.
  const rowKeysRef = useRef<string[]>([]);
  const selectionActions = (): RowAction[] => {
    const out: RowAction[] = [];
    // SELECT ALL — every row the list holds, the bar's own offer, here too
    // for the menu that opens on a pick.
    if (selKeys.length < rowKeysRef.current.length) {
      out.push({ icon: "select_all", label: tr("Select all"),
                 onClick: () => setSelKeys([...rowKeysRef.current]) });
    }
    // MERGE is a different verb per list, and two lists do not have it:
    // a place's data is per tag (folding two means folding their tags,
    // which is the Items list's job), and an event has no fold at all.
    const merge: null | { label: string; hint: string; go: () => void } =
      selKeys.length < 2 ? null
      : isTagList
        ? (selectedTags.length < 2 ? null
           : { label: `${tr("Merge")} ${selectedTags.length}…`,
               hint: tr("Fold the selected tags into one"),
               go: () => setMerging(selectedTags) })
      : mode === "links"
        ? { label: `${tr("Merge")} ${selectedMetaTags.length}`,
            hint: tr("Fold the selected tags into one"),
            go: () => setMergingMeta(selectedMetaTags) }
      : null;
    if (merge) {
      out.push({ icon: "merge", label: merge.label, hint: merge.hint,
                 onClick: merge.go });
    }
    // KEPT OUT OF THE AUTOCOMPLETE, over the selection — the row's own verb
    // at the grain the list is picked at, since a booru dump is hidden a
    // hundred rows at a time and never one. The direction is the MAJORITY's
    // opposite: pick a run that is mostly shown and the menu offers to hide
    // it, and the mixed case then lands on one answer rather than toggling
    // each row into disagreement with its neighbours.
    if (isTagList && selHiddenRows.length > 0) {
      const shown = selHiddenRows.filter((t) => !t.hidden).length;
      const hide = shown * 2 >= selHiddenRows.length;
      const n = hide ? shown : selHiddenRows.length - shown;
      out.push({
        icon: hide ? "visibility_off" : "visibility",
        separated: out.length > 0,
        label: hide ? `${tr("Hide from suggestions")} ${n}`
                    : `${tr("Suggest again")} ${n}`,
        hint: hide
          ? tr("They still assign, search and count — they stop being offered")
          : tr("They are offered by the autocomplete again"),
        onClick: () => void hideTags(
          selHiddenRows.filter((t) => !t.hidden === hide).map((t) => t.name),
          hide),
      });
    }
    if (deletableCount > 0) {
      out.push({ icon: "delete", label: `${tr("Delete")} ${deletableCount}`,
                 danger: true, separated: out.length > 0,
                 hint: deletableCount < selKeys.length
                   ? tr("Score tags are derived from ratings and stay — the rest are deleted")
                   : selHasIdentity
                   ? tr("Deleting an identity tag also deletes its subject, place or event")
                   : undefined,
                 disabled: deleting,
                 onClick: () => void deleteSelected() });
    }
    return out;
  };
  /** AN IMPORTED SET'S SELECTION has its own verbs (`tagSetVerbs.tsx`):
   *  what the library's tags offer — rename, merge, hide from the
   *  autocomplete — is about tags this tag set does not own. Absent for the
   *  library's own list. */
  const setSelectionActions = (): RowAction[] | null => {
    if (shownSetId == null) return null;
    const ids = selKeys.map(Number).filter((n) => n > 0);
    const idSet = new Set(ids);
    const rows = (tags ?? []).filter((t) => idSet.has(t.id))
      .map((t) => withDetail(t));
    return setVerbs.selectionActions(ids, rows);
  };
  /** What the toolbar's ⋯ and a right-click on a picked row both open:
   *  the set's verbs over a set, the library's over its own list. ONE
   *  definition — the toolbar offered the library's Delete over a set's
   *  entries, which would have deleted library tags by the entries' ids. */
  const menuActions = (): RowAction[] =>
    setSelectionActions() ?? selectionActions();
  const openSelectionMenu = (e: React.MouseEvent) => {
    const own = setSelectionActions();
    if (own) {
      e.preventDefault();
      setRowMenu({ at: { x: e.clientX, y: e.clientY }, kind: "tag", name: "",
                   own: { more: own } });
      return;
    }
    if (selectionActions().length === 0) return;
    e.preventDefault();
    setRowMenu({ at: { x: e.clientX, y: e.clientY }, kind: "tag", name: "",
                 selection: true });
  };
  const openRowMenu = (e: React.MouseEvent, kind: SearchKind, name: string,
                       label?: string, own?: RowOwn) => {
    // A row with no identity tag (an unnamed place, a cluster nobody has
    // named) names nothing the grid can be narrowed to — but it can still be
    // edited and deleted, so the menu opens whenever there is anything in it.
    if (!name && !own) return;
    e.preventDefault();
    setRowMenu({ at: { x: e.clientX, y: e.clientY }, kind, name, label, own });
  };

  // A RECORD's deletion asks a second question — does its tag go too? — so
  // it is a dialog rather than a confirm: the keys waiting on the answer,
  // and how many of those records are on pictures.
  // Transient highlight for the row we just jumped to (from an implication).
  const [flashName, setFlashName] = useState<string | null>(null);
  const flashTimer = useRef<number>();
  const settleTimer = useRef<number>();
  // The page's one scroll box — what the windowed lists watch.
  const scrollRef = useRef<HTMLDivElement>(null);
  //: How tall the sidebar's pane may be — measured against the page's own
  //  scroller, the Sets list's rule and now this one's.
  const paneH = usePaneHeight(scrollRef, columnsRef, [mode]);
  // Row multi-selection keyed by a string (item tag id, or link-tag name).
  const [selKeys, setSelKeys] = useState<string[]>([]);
  // Inline editors.
  // The tag whose editor overlay is open (name, comment, implications).
  const [editing, setEditing] = useState<TagRow | null>(null);
  // The tags the merge overlay is folding together.
  const [merging, setMerging] = useState<TagRow[] | null>(null);
  // The same two for the meta namespace, which has its own overlays (no
  // implications, no aliases — and carriers instead of item assignments).
  const [editingMeta, setEditingMeta] = useState<LinkTagRow | null>(null);
  // A NEW meta tag opens the same dialog with nothing filled in — a meta tag
  // is a name, a comment and a description, and the inline strip this
  // replaced could take only the name.
  const [creatingMeta, setCreatingMeta] = useState(false);
  const [mergingMeta, setMergingMeta] = useState<LinkTagRow[] | null>(null);
  // The two things the item-tag list can add, each in its own dialog.
  const [creatingTag, setCreatingTag] = useState(false);
  // The Add menu's Import entry opens the file picker `TagCsvButtons` owns —
  // that component keeps the input, the parsing and both overlays, and fills
  // this ref with its opener.
  const importOpen = useRef<(() => void) | null>(null);
  const [creatingAlias, setCreatingAlias] = useState(false);

  // Drop what names a ROW when the sub-tab changes — a selection or an open
  // editor from the tag list means nothing in the places list. The filters are
  // reset by `setTagsMode` instead, so that remounting this view (coming back
  // to the tab) restores them rather than clearing them.
  useEffect(() => {
    setSelKeys([]); setEditing(null);
    setEditingMeta(null); setMergingMeta(null); setMerging(null);
  }, [mode]);

  // The new tag's name, by the same rules every other tag field applies. This
  // form used to do half of them — whitespace to underscores and nothing else
  // — so "A:B:C" went to an API that refuses it and the `catch` below swallowed
  // the 400 with no message at all.
  const norm = (v: string) => tagFieldName(v);
  // An alias TARGET is matched against names that already exist, so it is only
  // tidied, never lowercased: a library can hold a mixed-case tag from an
  // import, and folding the case here would make it unaliasable.
  const normTarget = (v: string) => v.trim().replace(/\s+/g, "_");
  // Existing tag names an implication or an alias can point at (never aliases).
  // (What an implication or an alias may point at used to be built from the
  //  whole catalog held in the browser. Nothing holds it any more — the
  //  Items list is an index plus a window — and nothing needs to: every one
  //  of those fields is a `TagAutocomplete`, whose remote source is
  //  `/api/tags/names`, the one place this app answers "which tags are
  //  called something like this".)

  // The selection as a Set: rows ask "am I selected?" once per row per render,
  // and `selKeys.includes` made that O(rows × selection).
  const selSet = useMemo(() => new Set(selKeys), [selKeys]);
  // Deleting the IDENTITY tag of a subject, place or event deletes the
  // record with it (server-side cascade) — never the silent SET-NULL orphan
  // a select-all sweep once left a whole library in. The set exists so the
  // Delete button can SAY so when the selection includes one.
  const identityTagNames = useMemo(
    () => new Set([...(subjectRows ?? []), ...(placeRows ?? []),
                   ...(eventRows ?? [])].map((r) => r.tag).filter(Boolean)),
    [subjectRows, placeRows, eventRows]);
  // Every picked row deletes: nothing in this list is locked any more (a
  // ranking owned names until rung v31, and its own were skipped here).
  const deletableCount = selKeys.length;
  /** THE ROWS BY KEY, BUILT ONCE PER INDEX — and not at all until something
   *  is picked. Three of the memos below want to look a handful of selected
   *  keys up in the list, and each built its own `Map` over every row: at
   *  132,255 names that is three maps and 400,000 `String()` calls on every
   *  keystroke of the search, for a selection that is usually EMPTY. */
  const rowsByKey = useMemo(() => {
    const out = new Map<string, TagRow>();
    if (selKeys.length === 0) return out;
    for (const t of tags ?? []) out.set(String(t.id), t);
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tags, selKeys.length === 0]);
  const selHasIdentity = useMemo(() => {
    if (mode !== "items") return false;
    return selKeys.some((k) => {
      const t = rowsByKey.get(k);
      return !!t && identityTagNames.has(t.name);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, selKeys, rowsByKey, identityTagNames]);
  /** The picked TAG rows, whatever they are — the hide verb is about a
   *  NAME being offered, so an alias is as hideable as any other. */
  const selHiddenRows = useMemo(
    () => selKeys.map((k) => rowsByKey.get(k)).filter((t): t is TagRow => !!t),
    [selKeys, rowsByKey]);
  /** The picked rows' TAG IDS. `selKeys` is one flat string namespace over
   *  every list in this tab — a record id here, `c<faceId>` there, a tag
   *  NAME for the meta list — and only the items list's keys are tag ids. */
  const selectedTagIds = useMemo(
    () => (isTagList
      ? selKeys.map(Number).filter((n) => Number.isFinite(n) && n > 0) : []),
    [isTagList, selKeys]);
  const selectedTags = useMemo(
    () => selKeys.map((k) => rowsByKey.get(k))
      // An alias cannot merge — filtered here so the Merge button's count
      // says what it will actually fold.
      .filter((t): t is TagRow => !!t && t.alias_of == null),
    [selKeys, rowsByKey]);
  const selectedMetaTags = useMemo(() => {
    const byName = new Map((linkRows ?? []).map((r) => [r.name, r]));
    return selKeys.map((k) => byName.get(k))
      .filter((r): r is LinkTagRow => !!r);
  }, [selKeys, linkRows]);
  const nameTaken = (name: string) => (tags ?? []).some((t) => t.name === name);
  //: THE ROWS SELECT LIKE EVERY OTHER LIST IN THIS TAB (owner 2026-09;
  //  `useRowSelect`, which the rankings list and the Sets tab's entries have
  //  always used, declared with the row keys further down): a click picks
  //  ONE row, ⌘/Ctrl adds and removes, shift extends the run, and a
  //  press-and-drag paints. This list had a dialect of its own — a checkbox
  //  per row and a click that TOGGLED — which is the one gesture nobody
  //  brings with them from a file list, and it cost every row 26 px of the
  //  tag column to say so.

  const filterByCount = (name: string, negative: boolean) => {
    showAllItems();
    setLibrarySearch(negative ? `-${name}` : name);
    setView("library");
  };


  // Scroll a tag's own row into view and briefly highlight it — used by the
  // implication chips' jump button and by an arrival from another sub-tab.
  // Returns whether the row was there to jump to; a caller that has just
  // switched lists may be asking before the rows have loaded.
  /** GO TO A TAG, from a row that only NAMES it — an implied tag on the
   *  subtitle, and the same landing the category trail beside it makes.
   *
   *  A jump alone is not enough: the name a row points at is routinely not
   *  in the listing at all (a franchise while a character's category is
   *  picked, a tag the search or the kind filter drops), and `jumpToRow`
   *  can only aim at a row the list already holds. So where it is not here,
   *  the narrowings that could be hiding it are cleared and the NAME goes
   *  in the search box — the list is server-sorted and windowed, so there
   *  is no offset to scroll to and the search is what fetches the row. The
   *  `focus` effect then lands it once the new index arrives, which is the
   *  same road an arrival from another tab takes.
   */
  const goToTag = (name: string) => {
    if (jumpToRow(name)) return;
    // EVERY NARROWING GOES, because any of them can be what is hiding it —
    // the tag pointed at is routinely a different KIND (a character's row
    // points at its franchise, which is not somebody), filed in a different
    // category, and outside whatever is in the search box.
    //
    // And NO search is put in its place: the list holds the whole index, so
    // the row can be scrolled to where it belongs, among its neighbours,
    // which is what "go to that tag" means. (The deleted Sets tab did
    // search for it — it was server-paged with no index, so there was no
    // offset to scroll to. This one has one.)
    patch({
      search: "", category: [], namespaces: [], uncategorized: false,
      kind: "all", relation: "all", scope: "all", metaTag: "",
      suggest: "all", counts: {},
      focus: name,
    });
  };

  const jumpToRow = (name: string): boolean => {
    // A target inside a FOLDED group: unfold it, let the row mount, aim then.
    const ns = tagNamespace(name);
    if (isTagList && ns && collapsedNsRef.current.has(ns)
        && itemEntries.some((e) => e.kind === "tag" && e.row.name === name)) {
      setCollapsedNs((cur) => {
        const next = new Set(cur);
        next.delete(ns);
        return next;
      });
      window.setTimeout(() => jumpToRow(name), 50);
      return true;
    }
    // The row's INDEX in the active list, not its DOM node: the list is
    // windowed, so an off-screen target may not be mounted at all. A found
    // index means the row exists — scroll the window to it first (which
    // mounts it on the next render), then let the aims below centre the real
    // element and the flash find it.
    const idx = rowIndexOf(name);
    if (idx < 0) return false;
    if (mainWin.windowed) mainWin.scrollToIndex(idx);
    const find = () =>
      document.querySelector(`[data-tagrow="${CSS.escape(name)}"]`);
    if (!mainWin.windowed && !find()) return false;
    // RE-AIMED as the page settles. The first jump into a freshly mounted
    // Subjects list scrolled nowhere: the rows above the target had not got
    // their heights yet (the face strips measure themselves, and their crops
    // were still loading), so at that instant the target WAS near the top and
    // the scroll was correct about a layout that lasted one frame. Coming back
    // a second time found everything measured and worked, which is exactly how
    // it was reported. Two frames and a beat later, aim again.
    const aim = (smooth: boolean) => find()?.scrollIntoView(
      { block: "center", behavior: smooth ? "smooth" : "auto" });
    aim(true);
    requestAnimationFrame(() => requestAnimationFrame(() => aim(false)));
    window.clearTimeout(settleTimer.current);
    settleTimer.current = window.setTimeout(() => aim(false), 350);
    // Off and on across a frame, or a second jump to the SAME row leaves the
    // class where it was and the animation never restarts.
    setFlashName(null);
    requestAnimationFrame(() => setFlashName(name));
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlashName(null), 1800);
    return true;
  };

  // ---- items mode helpers -------------------------------------------------
  const removeAlias = async (t: TagRow) => {
    await api.deleteTag(t.id);
    qc.invalidateQueries({ queryKey: ["tags"] });
  };

  // ---- links mode helpers -------------------------------------------------
  // ALL FOUR editors can now mint a meta tag (putting one on a tag registers
  // the name), so every one of them has to sweep the namespace's own queries
  // — else the Meta list's counts and the autocomplete lag a reload behind.
  const invalidateMetaNames = () => {
    qc.invalidateQueries({ queryKey: ["link-tags"] });
    qc.invalidateQueries({ queryKey: ["link-tag-rows"] });
  };
  // ---- subjects mode helpers ----------------------------------------------
  const invalidateSubjects = () => {
    qc.invalidateQueries({ queryKey: ["subjects"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    qc.invalidateQueries({ queryKey: ["items"] });
    qc.invalidateQueries({ queryKey: ["item"] });
    qc.invalidateQueries({ queryKey: ["facets"] });
    invalidateMetaNames();
  };
  const invalidatePlaces = () => {
    qc.invalidateQueries({ queryKey: ["places"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    qc.invalidateQueries({ queryKey: ["items"] });
    qc.invalidateQueries({ queryKey: ["item"] });
    // A venue's address is read by the sidebar's offered rows too.
    qc.invalidateQueries({ queryKey: ["item-suggestions"] });
    invalidateMetaNames();
  };

  const invalidateEvents = () => {
    qc.invalidateQueries({ queryKey: ["events"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    qc.invalidateQueries({ queryKey: ["items"] });
    qc.invalidateQueries({ queryKey: ["item"] });
    // Editing an event's span or its venues changes what is offered.
    qc.invalidateQueries({ queryKey: ["item-suggestions"] });
    invalidateMetaNames();
  };

  const invalidateLinks = () => {
    qc.invalidateQueries({ queryKey: ["link-tag-rows"] });
    qc.invalidateQueries({ queryKey: ["link-tags"] });
    qc.invalidateQueries({ queryKey: ["relationships"] });
    // Captions and per-item tag groups carry the same namespace, so a rename
    // reaches the open item's detail too.
    qc.invalidateQueries({ queryKey: ["item"] });
  };

  // ---- shared: delete (with an undo) --------------------------------------
  // A count beside a filter promises how many rows choosing it leaves, so it
  // has to be counted over the rows this list can SHOW. The Subjects count was
  // not: it included the nameless subjects that only hold a merged cluster
  // together, which the list hides on purpose — so "Unassigned (14)" would
  // leave three rows on screen.
  const unassignedCount = isTagList
    // From the index, which counts it over the rows this view can show —
    // the browser is not given the rows to count for itself any more.
    ? (indexQuery.data?.unassigned_total ?? 0)
    : (linkRows ?? []).filter((r) => r.count === 0).length;
  // TWO NARROWINGS, and only two: "everything" and "on no item". The three
  // that were about a record — with faces, with a guess waiting, without a
  // tag — went with the sub-tabs that asked them. Faces are their own tab
  // now, and a record without a tag cannot exist.
  const scopeViews = SCOPE_VIEWS.filter(
    (v) => v.id === "all" || v.id === "unassigned");

  // One deletion path for the bulk button and for a single row's menu: the
  // same confirms, the same undo, the same invalidation.
  const deleteSelected = () => deleteKeys(selKeys);
  const deleteKeys = async (selKeys: string[]) => {
    if (deleting) return;
    if (isTagList) {
      const byId = new Map((tags ?? []).map((t) => [String(t.id), t]));
      const keys = selKeys;
      if (keys.length === 0) return;
      const assigned = keys.filter((k) => { const t = byId.get(k); return t && tagCount(t) + tagCount(t, "negative") > 0; }).length;
      if (assigned > 0 && !(await confirm({
        title: tn({ one: "Delete 1 tag?", other: "Delete {n} tags?" }, keys.length),
        body: tr("{assigned} of these {n} tags are assigned to items — deleting removes them from those items.",
                 { assigned, n: keys.length }),
        answer: { label: tr("Delete"), danger: true },
      }))) return;
      // Every event the deletion logged — the per-item removals as well as the
      // tag rows themselves — so the Undo below can put all of it back. ONE
      // request for the whole selection: a request per tag ran a 32k-row
      // Delete for the better part of an hour, invisibly, and a reload
      // partway left the library half-deleted.
      const events: number[] = [];
      setDeleting(true);
      try {
        for (const batch of chunks(keys.map(Number), 5000)) {
          const res = await api.bulkDeleteTags(batch);
          events.push(...(res.event_ids ?? []));
        }
      } finally {
        setDeleting(false);
      }
      undoKind.current = "delete";
      undo.offer(`${tr("Deleted")} ${keys.length}`, events);
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
    } else {
      const inUse = new Set((linkRows ?? []).filter((r) => r.count > 0)
        .map((r) => r.name));
      const used = selKeys.filter((k) => inUse.has(k)).length;
      if (used > 0 && !(await confirm({
        title: tn({ one: "Delete 1 meta tag?", other: "Delete {n} meta tags?" }, selKeys.length),
        body: tr("{used} of these {n} meta tags are in use — deleting removes them from every link, caption, tag group and tag that carries them.",
                 { used, n: selKeys.length }),
        answer: { label: tr("Delete"), danger: true },
      }))) return;
      for (const k of selKeys) await api.deleteLinkTag(k);
      invalidateLinks();
    }
    // A SET, not `includes`: the whole Characters set picked and deleted is
    // a hundred thousand keys against a hundred thousand.
    const gone = new Set(selKeys);
    setSelKeys((prev) => prev.filter((k) => !gone.has(k)));
  };
  // What the last deletion or merge did, offered back in a toast at the
  // bottom of the window — the sidebar's undo bar, since it is the same log
  // underneath. The event ids are HANDED to it (`offer`): every write here
  // returns them, and a 17k-row deletion outruns the watermark poll.
  const undoKind = useRef<"delete" | "merge">("delete");
  const undo = useUndoBar(isTagList ? "tags" : "meta", () => {
    invalidateSubjects();
    invalidateLinks();
  });
  // A big deletion is one request but not an instant one — the button says
  // it is working instead of appearing to do nothing.
  const [deleting, setDeleting] = useState(false);

  // ---- filtered + sorted rows ---------------------------------------------
  // (The items list's comparators used to live here. Every column it sorts
  //  by is a sort `/api/tags/index` understands now — including the highest
  //  per-meta count that breaks a tie on the positive column, which the
  //  browser cannot see any more because it is not given the meta marks.)


  // Which tag names carry subject / location data — the Kind filter reads
  // these, since a tag itself does not know what has been attached to it.
  const subjectTagNames = useMemo(
    () => new Set((subjectRows ?? []).map((r) => r.tag).filter(Boolean)),
    [subjectRows]
  );
  const placeTagNames = useMemo(
    () => new Set((placeRows ?? []).map((r) => r.tag).filter(Boolean)),
    [placeRows]
  );
  // The rows themselves, for the markers: a slug says a tag exists, not what
  // it names, and the display name and address are what tell two of them apart.
  const subjectByTag = useMemo(
    () => new Map((subjectRows ?? []).filter((r) => r.tag).map((r) => [r.tag, r])),
    [subjectRows]
  );
  const placeByTag = useMemo(
    () => new Map((placeRows ?? []).filter((r) => r.tag).map((r) => [r.tag, r])),
    [placeRows]
  );
  const eventTagNames = useMemo(
    () => new Set((eventRows ?? []).map((r) => r.tag).filter(Boolean)),
    [eventRows]
  );
  /** THE RECORD SHAPE, when the list is narrowed to exactly one kind.
   *
   *  `lead` is what the row says FIRST — the record's own name, with its
   *  spaces and capitals, since "San Diego Comic-Con 2014" is not a slug and
   *  a list of slugs is not a list of events. `facts` is what the retired
   *  Subjects, Places and Events lists put in their own columns: a subject's
   *  since-date, a place's coordinates and what it is inside, an event's
   *  span and what it is part of.
   *
   *  **IT IS THE LIBRARY'S RECORD, AND OVER A SET IT IS THE SET'S OWN**
   *  (owner 2026-09, reversing the library-only rule of the same month:
   *  "i don't see the subject names in the tags list, only the tag names,
   *  even when in the subjects tab of the characters tag set"). A set's
   *  entries have no library record until somebody assigns the tag, so the
   *  list of a 102,215-character set was a column of slugs — `hatsune_miku`
   *  — with the one thing the set is shipped FOR, the name she goes by,
   *  nowhere on the page.
   *
   *  The old rule had two reasons and both are spent. "It would read as the
   *  library's answer" is about a row where the two could be confused;
   *  inside a SET's own list every row is the set talking and there is no
   *  library record to confuse it with. And "a set-fed lead would blink in
   *  one window at a time" was true while the records rode the detail band
   *  alone — the index carries the first screenful whole now, so the name
   *  arrives in the same paint as the row.
   *
   *  Null while the detail band is still in flight, which is what a row
   *  scrolled to ahead of its band looks like for a few milliseconds: the
   *  row draws as soon as it is on screen, so this must survive being asked
   *  early. */
  const recordShape = (t: TagRow):
      { lead: string; facts: string[] } | null => {
    const k = asKind(kind);
    if (!k) return null;
    const name = t.name;
    // A SET'S OWN, where the list is a set's. The shapes differ — a set
    // names a parent by its TAG where the library has a row id — so each
    // kind reads its own, and an EMPTY record (`{}`, which is the whole of
    // what a set often knows) still leads with the tag rather than nothing.
    if (shownSetId != null) {
      if (k === "subject") {
        const r = t.subject;
        if (!r) return null;
        return { lead: r.name || name,
                 facts: r.since ? [`* ${formatDate(r.since, lang)}`] : [] };
      }
      if (k === "place") {
        const r = t.place;
        if (!r) return null;
        return {
          lead: r.name || name,
          facts: [
            ...(r.lat != null && r.lon != null
              ? [`${r.lat.toFixed(4)}, ${r.lon.toFixed(4)}`] : []),
            ...(r.parent ? [tr("in {place}", { place: r.parent })] : []),
          ],
        };
      }
      const r = t.event;
      if (!r) return null;
      return {
        lead: r.name || name,
        facts: [
          ...(r.start ? [spanLabel(r.start, r.end ?? null, lang)] : []),
          ...(r.parent ? [tr("part of {event}", { event: r.parent })] : []),
        ],
      };
    }
    if (k === "subject") {
      const r = subjectByTag.get(name);
      if (!r) return null;
      return { lead: r.display_name || name,
               facts: r.since_date ? [`* ${formatDate(r.since_date, lang)}`] : [] };
    }
    if (k === "place") {
      const r = placeByTag.get(name);
      if (!r) return null;
      const parent = r.parent_id != null
        ? (placeRows ?? []).find((p) => p.id === r.parent_id) : undefined;
      return {
        lead: placeLabel(r) || name,
        facts: [
          ...(r.lat != null && r.lon != null
            ? [`${r.lat.toFixed(4)}, ${r.lon.toFixed(4)}`] : []),
          ...(parent ? [tr("in {place}", { place: shortPlace(parent) })] : []),
        ],
      };
    }
    const r = eventByTag.get(name);
    if (!r) return null;
    const parent = r.parent_id != null
      ? (eventRows ?? []).find((e) => e.id === r.parent_id) : undefined;
    return {
      lead: r.display_name || name,
      facts: [
        ...(r.start_date ? [spanLabel(r.start_date, r.end_date, lang)] : []),
        ...((r.places ?? []).length
          ? [(r.places ?? []).map(shortPlace).join(" · ")] : []),
        ...(parent ? [tr("part of {event}", { event: parent.display_name })] : []),
      ],
    };
  };

  const eventByTag = useMemo(
    () => new Map((eventRows ?? []).filter((r) => r.tag).map((r) => [r.tag, r])),
    [eventRows]
  );
  // The same three, for the CSV export — the ROWS, not lines of text made out
  // of them. They used to arrive here pre-formatted, one summary line per
  // kind, which is exactly what could not be read back: nothing parses a
  // formatted address. The overlay takes the fields and writes a column each.
  const tagRecords = useMemo(() => {
    // A parent is a row id here and a NAME in a file — an id means nothing in
    // another library — so the export is handed the mapping.
    const placeById = new Map((placeRows ?? []).map((p) => [p.id, p]));
    const eventById = new Map((eventRows ?? []).map((e) => [e.id, e]));
    const placeParentTag = new Map<string, string>();
    for (const p of placeRows ?? []) {
      const up = p.parent_id != null ? placeById.get(p.parent_id) : undefined;
      if (p.tag && up?.tag) placeParentTag.set(p.tag, up.tag);
    }
    const eventParentTag = new Map<string, string>();
    for (const e of eventRows ?? []) {
      const up = e.parent_id != null ? eventById.get(e.parent_id) : undefined;
      if (e.tag && up?.tag) eventParentTag.set(e.tag, up.tag);
    }
    return { subjects: subjectByTag, places: placeByTag, events: eventByTag,
             placeParentTag, eventParentTag };
  }, [subjectByTag, placeByTag, eventByTag, placeRows, eventRows]);

  const filteredItems = useMemo(
    // ALREADY FILTERED. Every narrowing this list offers — the search, the
    // kind, aliases-only, implies-only, unassigned — is applied by the query
    // that built the index (`/api/tags/index`), because that is the whole
    // point of the index: what leaves the server is what the view lists.
    () => tags ?? [], [tags]);

  // Sorted item rows. Aliases carry no count of their own, so sorting by a count
  // column (Positive/Negative) would scatter them meaninglessly — instead order
  // the real tags by the count and slot each alias directly beneath the tag it
  // references. Other columns (name/comment) sort aliases like any row.
  const itemRowsToRender = useMemo(() => {
    if (!isTagList) return [];
    // ALREADY SORTED AND ALREADY SLOTTED, by the same query that filtered:
    // every column this list offers is a sort the index understands, and an
    // alias stands under the name it spells in every order but the
    // alphabetical one — done server-side, because the same list pages an
    // imported set and a client cannot slot across a page it has not got.
    return filteredItems;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredItems, isTagList]);

  // The Items list with its namespace PARENTS woven in — a view-level row per
  // shared `<namespace>:` prefix (two tags or more), the Places/Events tree
  // presentation. Pure math in `tagNamespaceRows.ts`.
  /** THE RECORD'S OWN HIERARCHY, in place of the namespace grouping.
   *
   *  A place is inside another place and an event is part of another event,
   *  and those two lists were TREES before this one absorbed them. The tree
   *  is built over the whole filtered list rather than over the window —
   *  exactly as the namespace parents are — by mapping each tag row to its
   *  record, flattening on the record's `parent_id`, and mapping back.
   *
   *  A record whose parent is not in the list (filtered out, or the parent
   *  is a tag this narrowing dropped) becomes a ROOT: `flattenTree`'s rule,
   *  and a row nobody can see is worse than a row at the wrong depth.
   *
   *  Subjects have no hierarchy, so they stay a flat list.
   */
  const recordTree = (rows: TagRow[]): ItemsListEntry[] | null => {
    const k = asKind(kind);
    if (k !== "place" && k !== "event") return null;
    const by = k === "place" ? placeByTag : eventByTag;
    const seen = new Map<number, TagRow>();
    const nodes: { id: number; parent_id: number | null }[] = [];
    for (const row of rows) {
      const rec = by.get(row.name);
      if (!rec) continue;
      if (seen.has(rec.id)) continue;
      seen.set(rec.id, row);
      nodes.push({ id: rec.id, parent_id: rec.parent_id ?? null });
    }
    // A row whose record this narrowing does not carry still belongs in the
    // list; it simply has no place in the tree.
    const loose = rows.filter((row) => {
      const rec = by.get(row.name);
      return !rec || seen.get(rec.id) !== row;
    });
    return [
      ...flattenTree(nodes).map(({ row, depth }) => ({
        kind: "tag" as const, row: seen.get(row.id) as TagRow,
        depth: (depth > 0 ? 1 : 0) as 0 | 1,
      })),
      ...loose.map((row) => ({ kind: "tag" as const, row, depth: 0 as const })),
    ];
  };

  const itemEntriesRaw = useMemo(
    () => (isTagList
      // A PICKED NAMESPACE FLATTENS THE LIST, whatever the layout toggle
      // says: every row then shares that prefix, so one parent row over the
      // whole list is a heading that says nothing. The toggle keeps its own
      // value — this is what the sidebar is doing, not a setting somebody
      // changed — and the list groups again the moment the namespace is let
      // go.
      // NARROWED TO ONE RECORD KIND, the rows nest on the RECORD's own
      // hierarchy instead — a place is inside another place — and the
      // namespace parents stand down: two groupings over one list is one
      // too many, and the one that says something here is containment.
      ? (recordTree(itemRowsToRender)
         ?? (grouping === "flat" || nsPicked.length > 0
         // The flat list the filter menu can ask for: the rows exactly as
         // filtered and sorted, no parents woven in — including the server's
         // own hoist of an exact search match to the front, which the
         // grouped branch has to redo because it re-sorts.
         ? itemRowsToRender.map((row) => (
             { kind: "tag", row, depth: 0 } as const))
         : namespacedRows(itemRowsToRender, sortKey, sortDir,
                          numCols.map((c) => c.key),
                          dSearch.trim().toLowerCase())))
      : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, kind, grouping, nsPicked, itemRowsToRender, sortKey, sortDir,
     dSearch, placeByTag, eventByTag]);
  //: …AND AN ALIAS ROW NESTS UNDER THE NAME IT SPELLS, one indent past
  //  whatever its target sits at — the namespace parents' shape, for the
  //  same reason: the row belongs to that tag and nothing else on it says
  //  so as plainly as where it is drawn. (The server put it there; this is
  //  the other half.)
  const itemEntries = useMemo(
    () => nestAliases(itemEntriesRaw as ItemsListEntry[]), [itemEntriesRaw]);
  /** Lowercased tag name -> how many spellings are drawn under it. One pass
   *  over the entries, so a row does not have to look for its own children. */
  const aliasChildren = useMemo(() => {
    const out = new Map<string, number>();
    for (const e of itemEntries) {
      if (e.kind !== "tag" || !e.row.alias_of) continue;
      const key = e.row.alias_of.toLowerCase();
      out.set(key, (out.get(key) ?? 0) + 1);
    }
    return out;
  }, [itemEntries]);
  const itemEntryRows = useMemo(
    () => itemEntries.filter((e) => e.kind === "tag"), [itemEntries]);
  // A collapsed group keeps its parent row (totals, select-all, the mark)
  // and drops its children from the flow — the windowing counts what is
  // actually rendered, so the two cannot disagree about row indexes.
  const shownItemEntries = useMemo(
    () => itemEntries.filter((e) => {
      if (e.kind === "namespace") return true;
      // A SPELLING FOLDED AWAY BY THE TAG IT SPELLS.
      if (e.row.alias_of
          && collapsedAlias.has(e.row.alias_of.toLowerCase())) return false;
      if (e.depth === 0) return true;
      // …and a namespace folded away takes the names made with it, its own
      // spellings among them (an alias is drawn under its tag, so a group
      // closed on the tag has to take it).
      return !collapsedNs.has(tagNamespace(e.row.alias_of || e.row.name));
    }),
    [itemEntries, collapsedNs, collapsedAlias]);

  // WHICH COUNT COLUMNS ARE WORTH A COLUMN. Read off the whole tag list
  // rather than the filtered rows: a column that came and went as you typed
  // in the search field would move every number under the cursor.


  const linkTagRows = useMemo(() => {
    const q = dSearch.trim().toLowerCase();
    const filtered = (linkRows ?? []).filter(
      (r) => (!unassignedOnly || r.count === 0) &&
        (!q || r.name.toLowerCase().includes(q) || r.comment.toLowerCase().includes(q))
    );
    const dir = sortDir === "asc" ? 1 : -1;
    return exactFirst([...filtered].sort((a, b) => {
      let c: number;
      if (sortKey === "name") c = a.name.localeCompare(b.name);
      else if (sortKey === "comment") c = a.comment.localeCompare(b.comment);
      else if (sortKey === "captions") c = a.captions - b.captions;
      else if (sortKey === "tag_groups") c = a.tag_groups - b.tag_groups;
      else if (sortKey === "tags") c = a.tags - b.tags;
      else c = a.links - b.links;
      return c * dir;
    }), q, (r) => [r.name]);
  }, [linkRows, dSearch, sortKey, sortDir, unassignedOnly]);

  const rowKeys = useMemo(() => (
    // Items: the TAG entries in namespace-grouped order — parent rows are
    // structure, not rows a shift-range can land on.
    isTagList
      ? itemEntryRows.map((e) => String((e as { row: TagRow }).row.id))
      : linkTagRows.map((r) => r.name)
  ), [isTagList, itemEntryRows, linkTagRows]);
  rowKeysRef.current = rowKeys;
  //: CONTROLLED, so the selection stays the state the rest of this file
  //  reads: `selKeys` is declared far above, where the menus, the counts and
  //  the delete all take it during a render, and a hook declared down here
  //  cannot be what they read.
  const sel = useRowSelect(rowKeys,
                           { selected: selKeys, onChange: setSelKeys, escapeClears: true });
  /** The checkbox's own verb: ADD these rows, or take them out, without
   *  touching the rest of the selection — the ⌘-click, without the key.
   *  Through Sets, since the header's box is asked over the whole list. */
  const toggleKeys = useCallback((keys: string[], on: boolean) => {
    setSelKeys((prev) => {
      if (on) {
        const have = new Set(prev);
        return [...prev, ...keys.filter((k) => !have.has(k))];
      }
      const drop = new Set(keys);
      return prev.filter((k) => !drop.has(k));
    });
  }, []);
  //: THE HEADER'S BOX: every row the list holds. The selection is pruned to
  //  the rows, so "all" is a comparison of two lengths rather than a walk.
  const allOn = rowKeys.length > 0 && selKeys.length >= rowKeys.length;
  //: A NAMESPACE PARENT'S BOX is over the names under it — the rows a
  //  shift-range over them would pick, in one press. One pass over the
  //  entries, keyed by the parent's name.
  const nsChildren = useMemo(() => {
    const out = new Map<string, string[]>();
    let cur: string[] | null = null;
    for (const e of itemEntries) {
      if (e.kind === "namespace") { cur = []; out.set(e.name, cur); continue; }
      if (e.depth === 1 && cur) cur.push(String(e.row.id));
      else cur = null;
    }
    return out;
  }, [itemEntries]);

  // ---- windowed rows ------------------------------------------------------
  // Only a viewport's worth of rows mounts once a list is long. The row
  // heights are ESTIMATES (a wrapped implication line, a face strip): rows
  // still render at natural height inside the window, and lists under the
  // threshold render the plain flow, exactly as before.
  const mainCount = isTagList ? shownItemEntries.length : rowKeys.length;
  // The items list with the REPRESENTATIVE strips on: a row grows by a
  // strip's height where the tag has a picture to show — the subject
  // rows' own estimate, over the tags that carry anything.
  const itemRowH = useMemo(() => {
    if (mode !== "items" || !showReps) return 51;
    let tags = 0, strips = 0;
    for (const e of shownItemEntries) {
      if (e.kind !== "tag") continue;
      tags++;
      if (tagCount(e.row) > 0 && e.row.alias_of == null) strips++;
    }
    return tags === 0 ? 51 : 51 + Math.round((strips / tags) * REP_STRIP_H);
  }, [mode, showReps, shownItemEntries]);
  const mainWin = useWindowedList({
    count: mainCount, rowHeight: itemRowH, scrollRef, minCount: 150,
  });
  // ---- the window's own rows ----------------------------------------------
  //
  // The index says which tags and in what order; the REST of a row — its
  // comment, its implications, its meta capsules, what the sets say — is
  // fetched for what is on screen. A window is tens of rows, so this is
  // milliseconds (measured: 2.9 ms for a hundred), and it is what lets the
  // index be the small thing it is.
  //
  // Padded either side of the visible band so a scroll of one row does not
  // land on a skeleton, and keyed on the ids themselves so scrolling back
  // over a band already fetched costs nothing.
  const windowIds = useMemo(() => {
    if (!isTagList) return [];
    const lo = Math.max(0, mainWin.start - 20);
    const hi = Math.min(shownItemEntries.length, mainWin.end + 20);
    const out: number[] = [];
    for (let i = lo; i < hi; i++) {
      const e = shownItemEntries[i];
      if (e.kind === "tag") out.push(e.row.id);
    }
    return out;
  }, [mode, isTagList, shownItemEntries, mainWin.start, mainWin.end]);
  //: …LESS WHAT THE INDEX ALREADY BROUGHT. The first screenful is on the
  //  index (`INDEX_ROWS`), so the listing every narrowing opens with fetches
  //  nothing at all, and a scroll asks only for the band below it.
  const needIds = useMemo(
    () => windowIds.filter((id) => !indexRows.has(id)),
    [windowIds, indexRows]);
  const { data: windowRows } = useQuery({
    queryKey: ["tags", "rows", shownSetId ?? 0, needIds],
    queryFn: () => api.tagRows(needIds, shownSetId),
    enabled: isTagList && needIds.length > 0,
    placeholderData: (prev) => prev,
  });
  // Everything fetched so far, so a row keeps what it had while the next
  // band loads — a comment that blinked out on every scroll would read as
  // the list losing it.
  const detailsRef = useRef(new Map<number, TagRow>());
  const [detailsVersion, setDetailsVersion] = useState(0);
  // THE WINDOW'S STRIPS, fetched beside its rows while the option is on —
  // the same padded band, the same keep-what-arrived cache, so a strip a
  // scroll has already shown never blinks out. The endpoint tops short
  // tags up on the way, which is why the fetch is per window rather than
  // once: a settled library answers in one indexed count per tag.
  const { data: windowReps } = useQuery({
    queryKey: ["tags", "reps", windowIds],
    queryFn: () => api.tagRepresentatives(windowIds),
    // A REPRESENTATIVE IS A PICTURE CARRYING THE TAG, so only the library
    // has any: an imported set's names are advice about tags that may not
    // exist here at all.
    enabled: mode === "items" && showReps && windowIds.length > 0,
    placeholderData: (prev) => prev,
  });
  const repsRef = useRef(new Map<number, RankingItemRef[]>());
  /** A refusal answers with the tag's strip as it now is: shown at once,
   *  and the window's query refetched behind it so the cache agrees. */
  const onRepsRefused = (tagId: number, next: RankingItemRef[]) => {
    repsRef.current.set(tagId, next);
    setDetailsVersion((v) => v + 1);
    void qc.invalidateQueries({ queryKey: ["tags", "reps"] });
  };
  // ONE PASS: DROP WHAT THE LAST INDEX SAID, THEN KEEP WHAT THIS ONE BROUGHT.
  //
  // A tag EDIT changes what a row says, so the cache it says it from has to
  // go with the query it came from — and this was three effects, two filling
  // the caches and one emptying them on a new index. React runs effects in
  // the order they are DECLARED, so a commit where the index AND the
  // window's rows both arrived filled the map and then cleared it. Every row
  // fell back to the index's own answer, which knows a name and its counts
  // and nothing else: no comment, no implications, and no meta capsules,
  // until a scroll moved the window and fetched a band again. Narrowing to a
  // meta tag and clearing it again are exactly the two gestures that move
  // both at once, which is where it showed.
  //
  // Emptying HERE also covers what a dependency cannot: the window's query
  // is keyed by the ids it asks for, so a narrowing that leaves the same
  // ids on screen answers from the cache with the SAME array, and an effect
  // watching that array alone would never run again.
  const detailsGen = useRef(indexQuery.dataUpdatedAt);
  useEffect(() => {
    if (detailsGen.current !== indexQuery.dataUpdatedAt) {
      detailsGen.current = indexQuery.dataUpdatedAt;
      detailsRef.current.clear();
      repsRef.current.clear();
    }
    for (const r of windowRows ?? []) detailsRef.current.set(r.id, r);
    if (windowReps) {
      for (const [k, v] of Object.entries(windowReps.reps))
        repsRef.current.set(Number(k), v);
    }
    setDetailsVersion((v) => v + 1);
  }, [windowRows, windowReps, indexQuery.dataUpdatedAt]);
  /** One row as it renders: the index's own answer, plus whatever the
   *  window has fetched about it. */
  // THE COUNTS ARE THE INDEX'S, WHATEVER THE DETAIL SAYS. The detail rows
  // (`/api/tags/rows`) carry whole-library counts, while the index's answer
  // to the media button is narrowed — so taking the detail row whole put the
  // library's figures back the moment a band landed, and only a second
  // fetch (cached, so never landing) showed the narrowed ones: "hundreds of
  // videos in a library with none, and zeros on the second try".
  const withDetail = (t: TagRow): TagRow => {
    const d = detailsRef.current.get(t.id) ?? indexRows.get(t.id);
    // The COUNTS and the hidden mark stay the index's: the index is what
    // every filter and sort was applied to, and it knows both for every row
    // — a detail band that has not landed yet must not take either away.
    return d ? { ...d, numbers: t.numbers, hidden: t.hidden,
                 hidden_ns: t.hidden_ns } : t;
  };
  void detailsVersion;   // re-render when a band lands

  // Where a named row sits in the ACTIVE list — what the jump scrolls to.
  const rowIndexOf = (name: string): number =>
    isTagList
      ? shownItemEntries.findIndex((e) => e.kind === "tag" && e.row.name === name)
      : linkTagRows.findIndex((r) => r.name === name);

  // Somebody arrived here from an icon in another list, asking for one row. The
  // jump is retried on every change to what is rendered, because a switch of
  // sub-tab arrives long before that list's rows do — and it is cleared only
  // once it has actually happened, so a slow query still lands.
  const focus = useUI((s) => s.tagsView.focus);
  //: IS THE LIST THE ONE THAT WAS ASKED FOR? Two ways it is not, and both
  //  put a DIFFERENT list on screen for a moment: the search is deferred, so
  //  a narrowing cleared in the same breath as the focus reaches the query a
  //  render later; and the index query holds the previous answer while the
  //  new one loads (`placeholderData`), which is the whole reason the list
  //  does not blink.
  const listSettled = dSearch === search && !indexQuery.isPlaceholderData;
  useEffect(() => {
    if (!focus) return;
    // A JUMP MAY NOT BE SPENT ON A LIST THAT IS ON ITS WAY OUT. It was:
    // clicking an implied tag while the Subjects listing was up found the
    // name in the whole-set index that arrived first, scrolled to its place
    // among 132,255 rows, and CLEARED the focus — and then the narrowed
    // answer landed, the content shrank from five million pixels to fifty
    // thousand, the browser clamped the scroll to the bottom, and nothing
    // was left asking to be shown.
    if (!listSettled) return;
    if (jumpToRow(focus)) patch({ focus: null });
    // The memoized rowKeys array stands in for the O(N) joined signature this
    // effect used to hang on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, rowKeys, listSettled]);
  const rowCount = rowKeys.length;
  const totalCount = isTagList ? (tags?.length ?? 0)
    : (linkRows?.length ?? 0);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir(key === "name" || key === "comment" ? "asc" : "desc");
    }
  };
  // The toolbar sticks to the top and the heading row sticks under it, so a
  // long list keeps both the selection's verbs and the column names
  // reachable. How tall the toolbar is has to be MEASURED — it grows a chip
  // when a meta tag is narrowing and loses one when it is not, and a
  // hardcoded offset would either overlap the headings or leave a gap.
  const toolbarRef = useRef<HTMLDivElement>(null);
  const [toolbarH, setToolbarH] = useState(0);
  useLayoutEffect(() => {
    const el = toolbarRef.current;
    if (!el) return;
    const measure = () => setToolbarH(el.getBoundingClientRect().height);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /** WHERE THE TAG SET FILES EACH NAME — its own column, drawn wherever
   *  the tag set has categories and the rows can differ. It stands down
   *  under exactly one picked LEAF category: every row would then say the
   *  same thing the heading above them says.
   *
   *  It was a set's column alone, though the library files its tags in
   *  categories of its own and shows the same tree beside the list. */
  const showCategory = isTagList && libCats.length > 0
    && (catPicked.length !== 1
        || libCats.some((c) => c.parent_id === catPicked[0]));
  /** How wide the trail column is: the widest one on screen, capped, and
   *  never narrower than its own heading. */
  const catW = useMemo(() => {
    if (!showCategory) return 0;
    let n = 0;
    for (const t of tags ?? [])
      n = Math.max(n, (t.category_trail ?? []).join("  ").length);
    for (const [, d] of detailsRef.current)
      n = Math.max(n, (d.category_trail ?? []).join("  ").length);
    return Math.max(74, Math.round(Math.min(n, 30) * 6.6 + 18));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showCategory, tags, detailsVersion]);
  /** A category by its TRAIL — what a row's Category cell has in hand, and
   *  what picking one needs an id for. NUL-joined: a category name may hold
   *  any character a person can type, `/` included. */
  const catByTrail = useMemo(() => {
    const out = new Map<string, number>();
    for (const c of libraryDetail.data?.category_rows ?? [])
      out.set((c.trail ?? [c.name]).join("\u0000"), c.id);
    return out;
  }, [libraryDetail.data]);
  const GRID = mode === "links" ? LINK_GRID
    : gridTemplate(numCols, { category: showCategory ? catW : null });

  //: THE PAGE HEAD, and there is no sub-tab strip beside it any more.
  //
  //  There were SEVEN. Subjects, Places and Events were this list cut three
  //  ways — a subject, a place and an event are extra data ON a tag, and
  //  their counts came from the same resolver — so they are the list's `kind`
  //  filter and the left column's three rows. META went the same way, to a
  //  row of that column: a meta tag is a name in the same tag set, the same
  //  `tags` rows one kind along, and as a button it read as a kind of work
  //  rather than the other list a tag set holds. FACES left the tab entirely
  //  — which crops are one person is not a question about a row in a list of
  //  names. RANKINGS left last, to the LIBRARY, where the standings it
  //  produces are the grid's own sections.
  //

  return (
    // THE SCROLLBAR IS ALWAYS THERE, as on the Faces page (see `FacesPage`):
    // the two pages share a top line whose right end is the Tags / Faces
    // switch, and a bar that came and went with the content — or a reserved
    // gutter, which Safari reserves at 17 px and draws in at 10 — moved the
    // switch sideways.
    <div ref={scrollRef} style={{ flex: 1, overflowY: "scroll", minHeight: 0,
                                  background: "var(--bg)" }}>
      {/* NO WIDTH CAP (owner 2026-09). A tag list is a table of counts and
          a left column of categories beside it, and both are better for the
          room: at 1040 px on a wide screen the names truncated while half
          the window stood empty. Reading-width caps are for prose. */}
      <div style={{ padding: PAGE_PAD }}>
        {/* THE PILLS STAY UP ON THE META LIST TOO. They are the row of
            TAG SETS this page is about, and the Meta row is one of the
            two lists a tag set holds — so the pills went away exactly
            where "which tag set am I looking at" is the question. */}
        {/* NOTHING UNDER THE PILLS. The toolbar band below opens with its
            own 10 px, and two insets stacked read as a gap somebody left
            rather than as the row of sets standing off the page. */}
        {withSidebar && (
          // THE TAB'S PAGE SWITCH at the right end of this row (owner
          // 2026-09), the pills taking what is left and wrapping in it.
          <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <TagSetShelf
              sets={setsQuery.data ?? []}
              // WHICH TAG SET IS LIT. The library's pill has no id of
              // its own until something files a tag, so 0 stands for it
              // while the row is still lazy.
              setId={shownSetId ?? librarySetId ?? 0}
              // PICKING A PILL IS PICKING A TAG SET, not a page: the
              // same list draws either, so the library's own pill comes
              // back to the same two columns rather than opening anything.
              onPick={(id) => {
                if (id == null) { setMode("items"); return; }
                setTagSetId(id);
                setMode("tagsets");
              }}
              onChanged={() => {
                qc.invalidateQueries({ queryKey: ["tags"] });
              }} />
          </div>
          <TagsPageSwitch />
          </div>
        )}
        {/* TWO COLUMNS ON THE ITEMS LIST: the way IN on the left, the list
            on the right — `TagsPanes`, the same split the Sets list has,
            with the same draggable divider and the same remembered width.
            The sidebar carries the authored categories and the derived
            namespaces (see `TagsSidebar`) and STICKS: the list still scrolls
            with the page, which is what its window, its sticky heading row
            and its jump landing are all measured against, so the column
            beside it has to follow rather than sit still. */}
        <TagsPanes split={withSidebar} columnsRef={columnsRef}>
        {withSidebar && (
          <div style={{ position: "sticky", top: 0, alignSelf: "start",
                        paddingTop: TOOLBAR_TOP }}>
            <TagsSidebar
              // THE STICKY ANSWER: this column is pinned to the top of the
              // scroller, so once the page has scrolled past its heading it
              // has the whole window to stand in.
              maxHeight={paneH.sticky - TOOLBAR_TOP}
              // THE BAND OVER THE TREE IS THE LIST'S BAND, MEASURED. The
              // list's toolbar grows a row when a meta tag is narrowing it,
              // and a sidebar standing off by a constant would then start
              // its tree above the list's first row rather than beside it.
              bandH={toolbarH ? toolbarH - TOOLBAR_TOP - TOOLBAR_GAP
                              : undefined}
              tree={catTree}
              // WHAT THE WHOLE TAG SET HOLDS, not what the narrowing
              // leaves — this is the row you press to get back out, so a
              // count that shrank with the filter would say the way back led
              // somewhere smaller. (The page's own subtitle is the narrowed
              // number; that is the question it answers.)
              total={shownSetId != null ? (openSet?.entries ?? 0)
                     : (librarySet?.entries ?? stats?.tags)}
              // HOW MANY OF ITS NAMES ARE PEOPLE, PLACES, OCCASIONS. The
              // LIBRARY's are counted from the record lists rather than
              // from its set's detail — that row is lazy, so a library that
              // has never filed a tag has no detail to read and can still
              // be full of people; an imported SET says so on its own rows,
              // which is what its detail counts.
              recordCounts={shownSetId != null
                ? (libraryDetail.data?.record_counts ?? {})
                : {
                subject: (subjectRows ?? []).filter((r) => r.tag).length,
                place: (placeRows ?? []).filter((r) => r.tag).length,
                event: (eventRows ?? []).filter((r) => r.tag).length,
              }}
              categories={libraryDetail.data?.category_rows ?? []}
              uncategorized={libraryDetail.data?.uncategorized}
              namespaces={namespaceRows.data ?? []}
              narrowing={{ category: catPicked, namespaces: nsPicked,
                           uncategorized: uncategorizedOnly,
                           record: kind === "subjects" ? "subject"
                             : kind === "places" ? "place"
                             : kind === "events" ? "event" : null }}
              // HOW MANY LABELS THE LIBRARY HAS, and whether they are what
              // is on screen. Picking the row IS the switch between the two
              // lists — the sub-tab it replaced parked its state the same
              // way, so coming back finds the tag list as it was left.
              // A TAG SET'S META TAGS — the LIBRARY's labels, or the ones
              // an imported set puts on its own names.
              metaCount={shownSetId != null ? (setMetaRows?.length ?? 0)
                                            : linkRows?.length}
              metaPicked={mode === "links" || setMetaOpen}
              onMeta={() => {
                // A TAG SET'S OWN LABELS. The library's are their own
                // list (`mode === "links"`); an imported set carries its
                // own, which travel in its file — the same row of the same
                // pane, one tag set along.
                if (shownSetId != null) { setSetMetaOpen(true); return; }
                setMode("links");
              }}
              onNarrow={(n: TagsNarrowing) => {
                // Any row above is a row of the NAMES, so picking one puts
                // the labels away.
                setSetMetaOpen(false);
                // A ROW ABOVE IS A ROW OF THE TAG LIST, so picking one goes
                // back to it — the pane cannot narrow a list it is not on.
                if (!isTagList) setMode("items");
                patch({
                category: n.category, uncategorized: n.uncategorized,
                namespaces: n.namespaces,
                // The record rows ARE the `kind` filter — one narrowing, so
                // the tree's highlight and the filter menu's tick cannot
                // disagree about the same question.
                kind: n.record === "subject" ? "subjects"
                  : n.record === "place" ? "places"
                  : n.record === "event" ? "events" : "all",
                });
              }}
              // A CATEGORY'S OWN VERBS, in the ⋯ and in the right-click
              // alike. They were a set's alone, though the library files
              // its tags in categories of its own and shows the same tree.
              // A BUILT-IN SET'S TREE IS READ, NOT EDITED, and the sidebar
              // already declares each of these optional and draws nothing
              // where one is missing — so the gate is passing none.
              onCategoryMenu={readOnly ? undefined : (ev, c) => {
                ev.preventDefault();
                setRowMenu({ at: { x: ev.clientX, y: ev.clientY },
                             kind: "tag", name: "",
                             own: { more: catActions(c) } });
              }}
              onAddCategory={readOnly ? undefined
                             : () => setAddingCategory(true)}
              onMakeEditable={readOnly && openSet
                ? () => makeEditable.mutate(openSet) : undefined}
              makingEditable={makeEditable.isPending}
              makeEditableError={makeEditableError}
              onDeleteCategories={readOnly ? undefined
                                  : (ids) => void deleteCategories(ids)}
              // A NAMESPACE ROW OFFERS WHAT ITS PARENT ROW IN THE LIST DOES
              // — one verb, hiding the names made with it from the
              // autocomplete — so the two doors cannot say different things.
              onNamespaceMenu={(ev, ns) => {
                ev.preventDefault();
                setRowMenu({ at: { x: ev.clientX, y: ev.clientY },
                             kind: "tag", name: "",
                             own: { more: nsActions(ns.name) } });
              }}
              categoryDrag={readOnly ? undefined : catDrag.categoryDrag}
              looseDrag={readOnly ? undefined : catDrag.looseDrag}
            />
          </div>
        )}
        <div style={{ minWidth: 0 }}>
        {/* A SET'S OWN LABELS, in place of its names — the same row of the
            same pane the library's Meta row is, one tag set along. */}
        {setMetaOpen && shownSetId != null ? (
          <TagSetMetaList setId={shownSetId} readOnly={readOnly}
                          maxHeight={paneH.flow - 10} />
        ) : (<>


        {/* Toolbar: actions on the left, view controls + search on the right.
            Sticky, with negative side margins so its background covers the
            page padding — otherwise rows slide past visibly at the edges. */}
        <div ref={toolbarRef} style={{
          position: "sticky", top: 0, zIndex: 3, background: "var(--bg)",
          // THE BLEED IS THE PAGE'S, NOT THE COLUMN'S. On a single-column
          // list the toolbar reaches into the page padding so rows do not
          // slide past visibly at the edges; beside a sidebar that same
          // negative margin would paint over the column next to it.
          // The bottom is `TOOLBAR_GAP`: it is what this band leaves under
          // itself, and the tree beside it stands its column off by the
          // same, so the two panels start on one line.
          ...(withSidebar
            ? { margin: `0 -${PAGE_PAD}px 0 0`,
                padding: `${TOOLBAR_TOP}px ${PAGE_PAD}px ${TOOLBAR_GAP}px 0` }
            : { margin: `0 -${PAGE_PAD}px`,
                padding: `${TOOLBAR_TOP}px ${PAGE_PAD}px ${TOOLBAR_GAP}px` }),
          // THE BAND IS A COLUMN OF ROWS. The controls are one row; what
          // the list is NARROWED to is a row under them, since a narrowing
          // is a state the page is in rather than a button to press, and
          // squeezed in among the buttons it was the first thing to be
          // pushed off a narrow window.
          display: "flex", flexDirection: "column", alignItems: "stretch",
          gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center",
                        justifyContent: "space-between", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {/* ADD AND EXPORT LEAD, whatever is selected. They used to step
                aside for the selection's own actions — "the toolbar is about
                THEM" — which made the two things you reach for most come and
                go with a click on a row. They are also FIRST: the library's
                own actions are always there, so they are what the eye can
                learn a position for, and what a selection adds then grows to
                the RIGHT of them rather than pushing them along. A rule keeps
                the two groups legible. */}
            <>
            {/* ITEM TAGS ADD TWO DIFFERENT THINGS, so that one asks which. A
                tag and an alias are not variants of one form: a tag is a name
                with a comment, an offset, implications and other names, and an
                alias is a name pointing at a tag that already exists. The
                inline strip tried to be both — a name field, then "alias of
                (optional)" — which put the whole tag editor's worth of fields
                out of reach and made every plain tag read past a question
                about aliases. */}
            {/* NOTHING IS ADDED TO ONE OF THE APP'S OWN SETS, and the gate
                goes OUTSIDE this ternary rather than into its condition:
                the else branch is the records lists' own Add, so a
                `!readOnly` in the test would have swapped one menu for
                another rather than taking the button away. */}
            {readOnly ? null : isTagList ? (
              // THE SAME MENU FOR EITHER TAG SET: a name, a spelling of
              // one, or a file. What each makes is the tag set's own —
              // a library tag, or an entry of the set on screen.
              <AddTagMenu
                t={tr}
                buttonStyle={toolbarBtn()}
                onTag={() => shownSetId != null ? setVerbs.setCreating(true)
                                                : setCreatingTag(true)}
                onAlias={() => shownSetId != null
                  ? setVerbs.setAddingAlias(true) : setCreatingAlias(true)}
                onImport={() => shownSetId != null ? setCsvIntoSet(true)
                                                   : importOpen.current?.()}
              />
            ) : (
              // Every list's Add is a MENU now: the one thing it creates —
              // a subject is a name, a comment, a since-date and an identity
              // tag, the editor's own four fields, so the inline strip is
              // long gone — and, behind a rule, the import that used to be
              // a button of its own beside Export. Adding by hand and adding
              // from a file are the same intent at two scales.
              <AddMenu
                t={tr}
                buttonStyle={toolbarBtn()}
                title={tr("Add or import")}
                entries={[
                  // A bare noun, the items tab's style — the menu hangs off
                  // a button already reading "Add".
                  { icon: "link", label: tr("Meta tag"),
                    run: () => setCreatingMeta(true) },
                  { icon: "upload_file", label: tr("Import from CSV"),
                    separated: true, run: () => importOpen.current?.() },
                ]}
              />
            )}
            {/* Both lists import and export the same Tags file — a subject,
                a place and an event are rows of it, and the Items list's own
                kind narrowing is how you get at one kind of them. Importing
                is the Add menu's entry (above); this renders the Export
                button and owns the file input and both overlays. */}
            {/* A SET EXPORTS ITSELF, as the file it was imported from —
                the library's own list exports the Tags CSV beside it, and
                both are "take this tag set away with you". */}
            {shownSetId != null && openSet ? (
              <button onClick={() => void exportSet(openSet)}
                      style={toolbarBtn()} title={tr("Export")}>
                <Icon name="download" size={15} />
                <span>{tr("Export")}</span>
              </button>
            ) : (
            <TagCsvButtons
                importOpenRef={importOpen}
                tags={tags ?? []}
                metaTags={mode === "links" ? (linkRows ?? []) : undefined}
                records={tagRecords}
                exportFilter="all"
                buttonStyle={toolbarBtn()}
                onImported={() => {
                  qc.invalidateQueries({ queryKey: ["tags"] });
                  qc.invalidateQueries({ queryKey: ["items"] });
                  qc.invalidateQueries({ queryKey: ["facets"] });
                  qc.invalidateQueries({ queryKey: ["link-tag-rows"] });
                  qc.invalidateQueries({ queryKey: ["link-tags"] });
                  qc.invalidateQueries({ queryKey: ["subjects"] });
                  qc.invalidateQueries({ queryKey: ["places"] });
                  qc.invalidateQueries({ queryKey: ["events"] });
                }}
              />
            )}
            </>
            {selKeys.length > 0 && (
              <span style={{ width: 1, height: 22, flex: "0 0 auto",
                             background: "var(--border)" }} />
            )}
            {selKeys.length >= 1 && menuActions().length > 0 && (
              // ONE BUTTON FOR THE SELECTION, holding exactly what a
              // right-click on a picked row opens (`selectionActions`). The
              // strip carries the search field and the filters too, so a
              // button per verb was the selection pushing them off the end —
              // and a toolbar built separately from the context menu had
              // already come to say different things about the same rows.
              // `width: auto`: `RowMenu`'s trigger is a 20 px glyph square by
              // default, and a toolbar button is a pill.
              <RowMenu always icon="more_horiz"
                buttonStyle={{ ...toolbarBtn(), width: "auto" }}
                title={tr("What to do with the selection")}
                label={<span>{deleting ? tr("Deleting…")
                              : tn({ one: "{n} selected", other: "{n} selected" },
                                   selKeys.length)}</span>}
                actions={menuActions()} />
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {/* Every way a list narrows, in as few buttons as its questions
                are separable. There used to be three controls of three
                different shapes — a "No tag" toggle, a five-way menu and an
                "Unassigned (N)" toggle — and two of them looked like the same
                question asked twice, because a row with no identity tag is on
                no picture either.
                The Subjects list asks TWO questions that are not about the
                same thing: which lists to show, and how to narrow the people
                in the first of them. As sections of one menu they read as one
                setting with a rule between them; as two buttons the second can
                also go DIM when the first has hidden everything it applies
                to. */}
            {/* WHICH ITEMS THE COUNTS ARE OVER — every kind, or any subset of
                images, videos and sequences: the grid's own media button, so
                the two questions read the same way. A filter on the NUMBERS
                rather than on the rows: the list stays the whole tag set,
                and each row says how often it is on a film. */}
            {mode === "items" && (
              <MediaKindMenu selected={media} title={tr("Which items the counts are over")}
                onToggle={(k) => patch({ media: media.includes(k)
                  ? media.filter((x) => x !== k) : [...media, k] })} />
            )}
            <FilterMenu
              sections={[
                // WHAT A NAME IS, HOW IT RELATES AND HOW THE LIST IS LAID
                // OUT are questions about a TAG SET, so either list
                // answers them: "is a person" is a record row in the
                // library and a flag on a set's entry, and both are read
                // by one filter.
                ...(isTagList ? [
                  { title: "What it names", views: KIND_VIEWS, value: kind,
                    onPick: (v: string) => setKind(v as typeof kind) },
                  { title: "How it relates", views: RELATION_VIEWS,
                    value: relation,
                    onPick: (v: string) => patch({ relation: v as TagsRelation }) },
                  { title: "Laid out", views: GROUP_VIEWS, value: grouping,
                    onPick: (v: string) =>
                      patch({ grouping: v as TagsGrouping }) },
                ] : []),
                // …and these two are about the LIBRARY: a representative is
                // a picture carrying the tag, and the autocomplete offers
                // the library's names. An imported set has neither.
                ...(mode === "items" ? [
                  { title: "Under each row", views: REPS_VIEWS,
                    value: showReps ? "reps" : "none",
                    onPick: (v: string) => patch({ reps: v === "reps" }) },
                  // WHICH NAMES THE FIELDS OFFER. Its own axis: hiding a
                  // name is neither a scope nor a deletion — the tag goes
                  // on assigning, searching and counting — so the list has
                  // to be able to ask "which ones did I take out", which
                  // nothing else on this menu answers.
                  { title: "In the autocomplete", views: SUGGEST_VIEWS,
                    value: suggest,
                    onPick: (v: string) =>
                      patch({ suggest: v as TagsSuggest }) },
                ] : []),
                { title: "Narrowed to",
                  views: scopeViews,
                  value: scope,
                  onPick: (v: string) => patch({ scope: v as TagsScope }),
                  suffix: (v: string) =>
                    v === "unassigned" ? ` (${unassignedCount})` : "" },
              ]}
              t={tr}
              title={tr("Narrow the list")}
            />
            {/* THE ONE ELASTIC THING IN THE ROW. Everything else is a button
                that must not wrap, so on a narrow window this is what gives —
                220 px when there is room, never past half of it. */}
            <SearchField size="lg" value={search} onChange={setSearch} clearTitle={tr("Clear")}
                         placeholder={isTagList ? tr("Search tags") : tr("Search meta tags")}
                         style={{ flex: "0 1 220px", minWidth: 110 }} />
          </div>
          </div>

          {/* WHAT THE LIST IS NARROWED TO, on a row of its own — the
              History tab's filter capsule, which says the same kind of
              thing about the same kind of list.

              It has to be VISIBLE and it has to be clearable: the control
              that set it is a capsule on one row among two hundred
              thousand, and scrolling away from it would leave the list
              narrowed by something with nothing on screen to say so. */}
          {mode === "items" && metaTag && (
            <div style={{ display: "flex", minWidth: 0 }}>
              <Chip tone="accent" size="lg" round bordered icon="filter_alt"
                    onClick={() => patch({ metaTag: "" })}
                    title={tr("Stop narrowing to this meta tag")}
                    style={{ maxWidth: "100%", minWidth: 0 }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                               whiteSpace: "nowrap" }}>
                  {tr("Only tags labelled {name}", { name: metaTag })}
                </span>
                <Icon name="close" size={14} />
              </Chip>
            </div>
          )}
        </div>

        {/* No text selection inside the table: rows are selected by clicking
            them, and a shift-click for a range would otherwise highlight
            every name it swept over. */}
        <div style={{
          background: "var(--panel)", border: "1px solid var(--border)",
          borderRadius: "var(--r-7)", overflow: "visible", userSelect: "none",
        }}>
          <div
            style={{
              display: "grid", gridTemplateColumns: GRID, padding: "0 16px", height: 40,
              borderBottom: "1px solid var(--border)", background: "var(--panel-3)",
              alignItems: "center", fontSize: "var(--fs-1)", fontWeight: 600, letterSpacing: "0.06em",
              textTransform: "uppercase", color: "var(--muted)",
              position: "sticky", top: toolbarH, zIndex: 2,
              // The panel around this is rounded, and a square filled rectangle
              // inside it paints over the curve. `overflow: hidden` on the panel
              // would clip it — and would also stop the header sticking, since
              // that makes the panel the scroll box and the panel never
              // scrolls. So the header carries the same curve itself, one pixel
              // tighter for the panel's border.
              borderRadius: "11px 11px 0 0",
            }}
          >
            <RowCheck checked={allOn} mixed={selKeys.length > 0}
              title={allOn ? tr("Clear the selection") : tr("Select all")}
              onToggle={() => setSelKeys(allOn ? [] : [...rowKeys])} />
            <Heading label={tr("Tag")}
              col={"name"} active={sortKey} dir={sortDir} onClick={toggleSort} />
            {mode !== "links" ? (
              // ONE HEADING PER COLUMN OF THE TAG SET. Every one sorts
              // and every one takes a range, whichever list this is: the
              // table is `tagSetColumns.ts` and nothing here names a column.
              <>
                {showCategory && (
                  <Heading label={tr("Category")} col="category"
                    active={sortKey} dir={sortDir} onClick={toggleSort} />
                )}
                {numCols.map((c) => (
                  <Heading key={c.key} label={tr(c.label)} col={c.key}
                    active={sortKey} dir={sortDir} onClick={toggleSort}
                    align="right"
                    range={countRanges?.[c.key]}
                    onRange={(r) => setRange(c.key, r)} t={tr} />
                ))}
              </>
            ) : (
              <>
                <Heading label={tr("Links")} col="links" active={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                <Heading label={tr("Captions")} col="captions" active={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                <Heading label={tr("Tag groups")} col="tag_groups" active={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
                <Heading label={tr("Tags")} col="tags" active={sortKey} dir={sortDir} onClick={toggleSort} align="right" />
              </>
            )}
          </div>

          {/* The windowed body: the sticky heading row above stays in flow,
              only the rows are sliced. Under the threshold both wrappers are
              styleless and the rows render exactly as they always did. */}
          <div
            ref={mainWin.containerRef}
            style={mainWin.windowed
              ? { height: mainWin.totalHeight, position: "relative" }
              : undefined}
          >
          <div style={mainWin.windowed
            ? { position: "absolute", top: mainWin.topOffset, left: 0, right: 0 }
            : undefined}
          >
          {isTagList ? shownItemEntries.slice(mainWin.start, mainWin.end).map((entry, j) => {
            const i = mainWin.start + j;
            if (entry.kind === "namespace") {
              // A NAMESPACE PARENT: a view-level row over the tags sharing
              // its prefix, never a tag entry — so it is not one of the rows
              // a selection lands on (its children are, and a shift-range
              // over them is how a whole prefix is picked). The chevron and
              // the name FOLD the group: the children leave the flow, the
              // parent's totals keep counting for them.
              const folded = collapsedNs.has(entry.name);
              // A folded parent can be the LAST visible row, where its
              // hover wash has to carry the panel's curve like any row.
              const nsLast = i === shownItemEntries.length - 1;
              const nsHidden = hiddenNs.includes(entry.name.toLowerCase());
              return (
                <div key={`ns:${entry.name}`} className="hoverable"
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setRowMenu({ at: { x: e.clientX, y: e.clientY },
                                 kind: "tag", name: "",
                                 own: { more: nsActions(entry.name) } });
                  }}
                  style={rowStyle(GRID, false, nsLast, 44)}>
                  {(() => {
                    const kids = nsChildren.get(entry.name) ?? [];
                    const on = kids.filter((k) => selSet.has(k)).length;
                    return (
                      <RowCheck checked={kids.length > 0 && on === kids.length}
                        mixed={on > 0}
                        title={on === kids.length ? tr("Clear the selection")
                                                  : tr("Select all")}
                        onToggle={() => toggleKeys(kids, on < kids.length)} />
                    );
                  })()}
                  <span
                    onClick={() => toggleNs(entry.name)}
                    title={folded ? tr("Show this group's tags")
                                  : tr("Fold this group away")}
                    style={{ display: "flex", alignItems: "center",
                             gap: FOLD_GAP,
                             minWidth: 0, paddingRight: 8,
                             cursor: "pointer" }}>
                    <span style={{ display: "flex", alignItems: "center",
                                   justifyContent: "center", flex: "0 0 auto",
                                   width: FOLD_W }}>
                      <Icon name={folded ? "chevron_right" : "expand_more"}
                        size={15} color="var(--muted-2)" />
                    </span>
                    {/* NOT BOLD (owner 2026-09): a namespace has no row of
                        its own in the catalog — it is the text before a
                        name's first colon, and this row is a heading over
                        the names made with it. Drawn heavier than the tags
                        under it, it read as the biggest tag on the page. */}
                    <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-4)",
                                   fontWeight: 400, color: "var(--text-2)",
                                   overflow: "hidden",
                                   textOverflow: "ellipsis",
                                   whiteSpace: "nowrap",
                                   marginRight: 6 }}>
                      {entry.name}:
                    </span>
                    <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
                      {tn({ one: "1 tag", other: "{n} tags" },
                          entry.rows.length)}
                    </span>
                    {/* No ranking mark here: the namespace is a view-level
                        grouping, and only the MINTED score rows inside it are
                        the ranking's — each of those carries the mark. */}
                    {/* OUT OF THE AUTOCOMPLETE, and the row says so — its
                        tags each wear the quiet mark, and the row they hang
                        under wears the plain one, since this is the row the
                        rule belongs to. It does NOTHING when pressed, as
                        every mark in this app does: showing the namespace
                        again is this row's ⋯ and its right-click, which are
                        one definition (`nsActions`). */}
                    {nsHidden && (
                      <span
                        title={tr("Not offered by the autocomplete")}
                        style={{ display: "flex", alignItems: "center",
                                 flex: "0 0 auto", color: "var(--muted-2)" }}>
                        <Icon name="visibility_off" size={13} />
                      </span>
                    )}
                    {/* THE MENU AT THE COLUMN'S RIGHT EDGE, where every
                        tag row's sits — after the name it landed wherever
                        the count happened to end, a different place on
                        every row. Inside this cell, not beside it: the
                        columns after it are the counts. */}
                    <span style={{ flex: 1 }} />
                    <span className="tag-edit-btn"
                      onClick={(e) => e.stopPropagation()}
                      style={{ alignItems: "center", flex: "0 0 auto" }}>
                      <RowMenu title={tr("What to do with this namespace")}
                        always color="var(--muted-2)"
                        actions={nsActions(entry.name)} />
                    </span>
                  </span>
                  {/* A namespace holds names from any shelf, so its parent
                      row says nothing under Category. */}
                  {showCategory && <span />}
                  {/* Quiet totals — the group's aggregate per column of
                      the tag set, muted so a parent never reads as one
                      more tag. */}
                  {numCols.map((c) => (
                    <CountCell key={c.key} base={entry.numbers?.[c.key] || null}
                      color="var(--muted)" />
                  ))}
                </div>
              );
            }
            // The index's row, plus whatever the window has fetched about
            // it — a row draws with its name and counts from the moment it
            // is on screen, and gains its comment, implications and capsules
            // when the band lands.
            const t = withDetail(entry.row);
            //: HOW MANY SPELLINGS HANG UNDER THIS ROW, and whether they are
            //  folded away. Counted off the entries themselves rather than
            //  off `t.aliases`, which only a set's rows carry and only for
            //  the window that has been fetched.
            const aliasKids = aliasChildren.get(t.name.toLowerCase()) ?? 0;
            const aliasFolded = collapsedAlias.has(t.name.toLowerCase());
            const shape = recordShape(t);
            const key = String(t.id);
            const last = i === shownItemEntries.length - 1;
            const strip = showReps && t.alias_of == null
              ? repsRef.current.get(t.id) : undefined;
            return (
              // The wrapper IS the row — the subject rows' shape: the strip
              // of representative pictures under the name is part of the
              // same tag, so it takes the same selection wash and answers a
              // click on its empty background the same way.
              <div key={t.id} data-tagrow={t.name}
                onContextMenu={(e) => {
                  if (selSet.has(key) && selKeys.length > 1) openSelectionMenu(e);
                  else if (shownSetId != null) {
                    e.preventDefault();
                    setRowMenu({ at: { x: e.clientX, y: e.clientY },
                                 kind: "tag", name: t.name,
                                 own: { more: setVerbs.rowActions(t, [t.id]) } });
                  } else openRowMenu(e, "tag", t.name, undefined,
                                     tagRowOwn(t, key));
                }}
                className={flashName === t.name ? "hoverable mc-flash" : "hoverable"}
                // The row's own background is the target: everything in it
                // that does something stops the click itself.
                {...sel.props(key)}
                // ONLY A PICKED ROW DRAGS. The paint gesture owns an
                // unpicked one — a press and a move across rows is how a run
                // is selected — and a native drag decides at the first pixel
                // and cannot be called off, so it would swallow that. Pick
                // first, then carry: the Sets tab's rule for its own rows.
                draggable={!readOnly && selSet.has(key)}
                onDragStart={(e) => {
                  const ids = selectedTagIds.length ? selectedTagIds : [t.id];
                  e.dataTransfer.setData("text/plain", `tags:${ids.join(",")}`);
                  e.dataTransfer.effectAllowed = "move";
                  // The press has to be ended by hand: Chrome sends
                  // `dragend` and never the `mouseup` the paint ends on, so
                  // the press would outlive the drag and the next hover
                  // would paint.
                  sel.cancelPress();
                  catDrag.begin(ids);
                }}
                onDragEnd={() => catDrag.end()}
                style={{
                  borderBottom: last ? "none" : "1px solid var(--border-soft)",
                  background: rowBackground(selSet.has(key), "transparent"),
                  borderRadius: last ? "0 0 11px 11px" : undefined,
                  cursor: "default",
                }}>
              <div style={rowStyle(GRID, false, true, 50)}>
                <RowCheck checked={selSet.has(key)}
                  onToggle={() => toggleKeys([key], !selSet.has(key))} />
                {/* What the tag IS: its name, and under it what assigning it
                    also assigns — a plain subtitle, not a row of controls. The
                    pencil on hover opens the editor overlay, which is where
                    the name, the comment and the implications are changed. An
                    alias entails nothing (assigning it redirects to its
                    target), so it shows the tag it stands for instead. */}
                <span style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 1, minWidth: 0, paddingRight: 8, paddingLeft: entry.depth * INDENT }}>
                  {/* The name line has a FIXED height: the pencil is taller
                      than the text, so without one it grew on hover and nudged
                      the subtitle down every time the pointer crossed a row. */}
                  <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, overflow: "hidden", height: 20, fontFamily: shape ? "var(--sans)" : "var(--mono)", fontSize: "var(--fs-4)", color: "var(--text)", fontWeight: shape ? 600 : 500 }}>
                    {/* THE FOLD COLUMN, reserved on every row. A tag with
                        other spellings folds them the way a namespace folds
                        its names — the same gesture over the same kind of
                        thing, the rows drawn under this one. A row with
                        nothing to fold leaves the slot empty rather than
                        closing it up: a name that shifts sideways depending
                        on what its row happens to hold is a list whose left
                        edge moves as you scroll. */}
                    <span
                      onClick={aliasKids > 0
                        ? (e) => { e.stopPropagation(); toggleAliases(t.name); }
                        : undefined}
                      onMouseDown={aliasKids > 0
                        ? (e) => e.stopPropagation() : undefined}
                      title={aliasKids > 0
                        ? (aliasFolded
                             ? tn({ one: "Show its other spelling",
                                    other: "Show its {n} other spellings" },
                                  aliasKids)
                             : tr("Fold its other spellings away"))
                        : undefined}
                      style={{ display: "flex", alignItems: "center",
                               justifyContent: "center", flex: "0 0 auto",
                               width: FOLD_W, marginRight: FOLD_GAP - 6,
                               cursor: aliasKids > 0 ? "pointer" : "default",
                               color: "var(--muted-2)" }}>
                      {aliasKids > 0 && (
                        <Icon name={aliasFolded ? "chevron_right" : "expand_more"}
                              size={15} />
                      )}
                    </span>
                    {/* NARROWED TO ONE KIND, THE RECORD'S OWN NAME LEADS and
                        the tag drops to the subtitle: "San Diego Comic-Con
                        2014" is not a slug, and a list of slugs is not a list
                        of events. The Sets tab's rule, over the library's own
                        tags — and what makes the retired Subjects, Places and
                        Events lists this list narrowed. */}
                    {/* A SPELLING YIELDS BEFORE THE CONTROLS DO (owner
                        2026-09). The name is rigid on a tag's row — the
                        capsule strip beside it is what gives — but a
                        spelling's row is name, arrow, target and nothing
                        else, so on a long one the hover buttons were pushed
                        out of the cell and CLIPPED: the pencil and the ⋯
                        were simply missing from the rows that had the most
                        name to read. It ellipsises instead, and they stay on
                        the column's right edge where a tag's are. */}
                    <span style={{ flex: t.alias_of != null ? "0 1 auto" : "0 0 auto",
                                   minWidth: 0, maxWidth: "100%", overflow: "hidden",
                                   textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      <Mark text={shape ? shape.lead : t.name} q={search} />
                    </span>
                    {/* KEPT OUT OF THE AUTOCOMPLETE. Not a state of the tag
                        so much as a state of the FIELDS — it assigns,
                        searches and counts exactly as before — so it is a
                        quiet mark rather than a dimmed row. Only in this
                        list: the namespace rule that hides a whole dump's
                        worth is a setting, and a mark on every one of its
                        rows would be noise about a decision made once.
                        IT DOES NOTHING WHEN PRESSED (owner 2026-09), like
                        the namespace's mark beside it and the tag set
                        pill's: a mark that reads as a state and acts as a
                        button is one an aimed click undoes by accident,
                        and the row is a selection target under it. Showing
                        the tag again is the row's own menu. */}
                    {t.hidden ? (
                      <span
                        title={tr("Not offered by the autocomplete")}
                        style={{ display: "flex", alignItems: "center",
                                 flex: "0 0 auto", color: "var(--muted-2)" }}>
                        <Icon name="visibility_off" size={13} />
                      </span>
                    ) : t.hidden_ns ? (
                      // HIDDEN BY ITS NAMESPACE, which is a different fact
                      // and a different mark: quieter, and it does nothing
                      // when pressed, because the rule is a setting over a
                      // prefix and this row cannot undo it — the namespace's
                      // own row can.
                      <span
                        title={tr("Not offered by the autocomplete: the whole “{ns}” namespace is hidden",
                                  { ns: tagNamespace(t.name) ?? "" })}
                        style={{ display: "flex", alignItems: "center",
                                 flex: "0 0 auto", color: "var(--muted-3)",
                                 opacity: 0.75 }}>
                        <Icon name="visibility_off" size={12} />
                      </span>
                    ) : null}
                    {/* What this tag NAMES, where a slug cannot say it:
                        `kaguya_shinomiya` reads the same whether it is a
                        person, a style or a place somebody photographed. */}
                    <KindMark
                      subject={subjectByTag.get(t.name)}
                      place={placeByTag.get(t.name)}
                      event={eventByTag.get(t.name)}
                      // …and what the SET says, where the library says
                      // nothing — which over a set's own entries is every
                      // row of it.
                      says={shownSetId == null ? undefined : t}
                      // The tag rides along: switching list alone leaves you to
                      // find, in a hundred rows, the thing you just clicked.
                      onGo={(m) => setMode(m, t.name)}
                      t={tr}
                    />
                    {/* AN ALIAS SAYS NOTHING OF ITS OWN — it is a second
                        NAME for a tag, and the target's comment and
                        annotations are the ones that apply. So the arrow
                        follows the name IMMEDIATELY: the pair, the capsules
                        and the space-claiming strip between them belong to a
                        tag, and on an alias row they left a gap the width of
                        the column between `alias` and `→ test123`. */}
                    {t.alias_of != null ? (
                      <>
                        <Icon name="arrow_forward" size={13} color="var(--muted-2)" />
                        <span
                          onClick={(e) => { e.stopPropagation(); jumpToRow(t.alias_of as string); }}
                          title={`${tr("Jump to")} ${t.alias_of}`}
                          style={{ color: "var(--accent)", cursor: "pointer", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        >
                          <Mark text={t.alias_of || "(none)"} q={search} />
                        </span>
                        {/* …AND THE REST OF THE COLUMN IS SPACE (owner
                            2026-09). A tag's row ends in the capsule strip,
                            which claims what is left and puts the hover
                            buttons on the column's right edge; a spelling has
                            no strip, so its buttons sat against the name and
                            the two rows' pencils were in different places. */}
                        <span style={{ flex: "1 1 0", minWidth: 0 }} />
                      </>
                    ) : (
                      <>
                        {/* What it IS, at both lengths — the same pair, in
                            the same order, the autocomplete shows.

                            A SET'S ROW IS DESCRIBED BY ITS SET, not by the
                            library: what the `?` opens on is that set's
                            own frame — its words, its count, its other
                            spellings, what it entails and what it says the
                            tag IS. Passing it as the LIBRARY's frame made
                            the mark appear only where somebody had written
                            prose, since that is the rule a library frame
                            follows; a set is worth a `?` for KNOWING the
                            name, which is most of what a dump has to say. */}
                        <Described comment={t.comment} name={t.name}
                                   descriptions={shownSetId != null
                                     ? [{ key: openSet?.key ?? "",
                                          text: t.description ?? "",
                                          trail: t.category_trail ?? [],
                                          count: t.numbers?.count ?? null,
                                          aliases: t.aliases ?? [],
                                          implies: t.implies ?? [],
                                          comment: t.comment ?? "",
                                          subject: t.subject ?? null,
                                          place: t.place ?? null,
                                          event: t.event ?? null }]
                                     : (t.descriptions ?? undefined)}
                                   library={shownSetId != null ? undefined
                                     : { text: t.description,
                                         comment: t.comment,
                                         trail: t.category_trail }}
                                   q={search} />
                        <MetaCapsules names={t.meta_tags}
                          counts={t.meta_counts} tagSets={t.tag_sets}
                          tinted={selSet.has(key)}
                          // CLICKING A CAPSULE NARROWS TO IT. A meta tag is
                          // the mark a bulk import left, which makes it the
                          // one cut through a catalog of 200,000 names that
                          // nobody has to type — and it is written right
                          // there on the row. Clicking the one already in
                          // force clears it, so the capsule is the way back
                          // as well as the way in.
                          onPickMeta={(m) => patch({
                            metaTag: metaTag.toLowerCase() === m.toLowerCase()
                              ? "" : m })} />
                      </>
                    )}
                    {/* THE PENCIL IS ON EVERY ROW, a spelling included. What
                        it opens differs, because what there is to edit
                        differs: a library alias is a tag row (its name, and
                        what it points at), and a set's spelling is
                        retargeted in the dialog that does exactly that. On
                        one of the app's own sets there is no pencil at all —
                        the row is read. */}
                    {readOnly ? null : (t.alias_of == null || shownSetId == null) ? (
                      <span
                        className="tag-edit-btn"
                        onClick={(e) => { e.stopPropagation();
                          // AN ALIAS IS TWO FIELDS — what it is called and
                          // what it stands for — and that is its own small
                          // dialog, not the tag form with everything an
                          // alias does not have greyed out.
                          if (t.alias_of != null) setEditingAlias(t);
                          // …AND A SET'S ENTRY IS EDITED BY THE SET'S OWN
                          // FORM. `editing` opens `TagEditOverlay`, which is
                          // rendered only while the LIBRARY's list is up, so
                          // on a set's row the pencil set a state nothing
                          // was watching: no dialog, no error, and the
                          // click fell through to the row, which selected
                          // itself. The set's editor watches its own state
                          // (`setVerbs.editing`), which until now only the
                          // row's ⋯ ever set — though its Edit entry is
                          // written to send you back here for exactly this.
                          else if (shownSetId != null) setVerbs.setEditing(t);
                          else setEditing(t); }}
                        title={t.alias_of == null ? tr("Edit this tag")
                                                  : tr("Edit this alias")}
                        style={{
                          alignItems: "center", justifyContent: "center", flex: "0 0 auto",
                          width: 20, height: 20, borderRadius: "var(--r-1)",
                          color: "var(--muted-2)", cursor: "pointer",
                        }}
                      >
                        <Icon name="edit" size={14} />
                      </span>
                    ) : (
                      <span
                        className="tag-edit-btn"
                        onClick={(e) => { e.stopPropagation();
                          setRetarget({ alias: t.name,
                                        fromName: t.alias_of ?? "" }); }}
                        title={tr("Point it at another tag…")}
                        style={{
                          alignItems: "center", justifyContent: "center", flex: "0 0 auto",
                          width: 20, height: 20, borderRadius: "var(--r-1)",
                          color: "var(--muted-2)", cursor: "pointer",
                        }}
                      >
                        <Icon name="swap_horiz" size={14} />
                      </span>
                    )}
                    {/* The tag's RECORDS, beside the pencil: what this tag
                        IS (or could be) — a person, a place, an event. Edit
                        where the record exists, Add where it does not (the
                        create overlay opens over this tag and adopts it). */}
                    {(() => {
                      const acts = shownSetId != null
                        ? rowActionsFor("tag", t.name, undefined,
                                        { more: setVerbs.rowActions(t, [t.id]) })
                        : rowActionsFor("tag", t.name, undefined,
                                        tagRowOwn(t, key));
                      // NO GLYPH OVER AN EMPTY MENU. `RowMenu always` draws
                      // its ⋯ whatever it holds, and on one of the app's own
                      // sets a row whose tag is already in the library and
                      // entails nothing is left with nothing to offer.
                      if (!acts.length) return null;
                      return (
                        <span className="tag-edit-btn"
                          style={{ alignItems: "center", flex: "0 0 auto" }}>
                          <RowMenu
                            title={tr("More")}
                            always
                            color="var(--muted-2)"
                            actions={acts}
                          />
                        </span>
                      );
                    })()}
                  </span>
                  {/* Wraps rather than truncating: what a tag implies is the
                      point of the line, and a row that grows to say all of it
                      beats one that stops mid-name. */}
                  {shape && (
                    // THE SUBTITLE THE RECORD LISTS HAD AS COLUMNS: the tag
                    // itself (still what is assigned, so still worth
                    // reading), then what only that kind knows.
                    <span style={{ minWidth: 0, display: "flex", gap: 8,
                                   paddingLeft: NAME_INDENT,
                                   fontSize: "var(--fs-1)", lineHeight: 1.45,
                                   color: "var(--muted-2)", overflow: "hidden",
                                   whiteSpace: "nowrap" }}>
                      <span style={{ fontFamily: "var(--mono)", flex: "0 1 auto",
                                     overflow: "hidden",
                                     textOverflow: "ellipsis" }}>
                        <Mark text={t.name} q={search} />
                      </span>
                      {shape.facts.map((f, n) => (
                        <span key={n} style={{ flex: "0 1 auto", overflow: "hidden",
                                               textOverflow: "ellipsis" }}>{f}</span>
                      ))}
                    </span>
                  )}
                  {(t.implies ?? []).length > 0 && (
                    // EVERY IMPLIED NAME IS A WAY TO IT (owner 2026-09).
                    // The line was one joined string, which on a character
                    // set is the franchise every row of the page points at
                    // and no way to open it — the category trail beside it
                    // had been a set of controls for a year. `goToTag` is
                    // the trail's own landing: it clears whatever would
                    // hide the row and puts the name in the search.
                    <span style={{ minWidth: 0, paddingLeft: NAME_INDENT,
                                   fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                                   lineHeight: 1.45, color: "var(--muted-2)",
                                   overflowWrap: "anywhere" }}>
                      → {(t.implies ?? []).map((n, i) => {
                        // AND WHICH OF THEM THE LIBRARY HAS NOT ACTED ON,
                        // struck through — the mark `missing_implies` has
                        // always been for, and which the one list lost when
                        // it replaced the Sets tab's own.
                        const gap = (t.missing_implies ?? []).includes(n);
                        return (
                          <span key={n}>
                            {i > 0 && ", "}
                            <span
                              onClick={(e) => { e.stopPropagation(); goToTag(n); }}
                              title={gap
                                ? tr("{name} — the library's tag does not entail it yet",
                                     { name: n })
                                : `${tr("Jump to")} ${n}`}
                              style={{ cursor: "pointer",
                                       textDecoration: gap ? "line-through" : undefined,
                                       opacity: gap ? 0.75 : undefined }}>
                              <Mark text={n} q={search} />
                            </span>
                          </span>
                        );
                      })}
                    </span>
                  )}
                </span>
                {/* WHERE THE TAG SET FILES IT, and every name of the
                    trail is a way into that shelf: pressing one picks the
                    category in the tree, which is what narrows this list.
                    Each stops its own press, or the click would toggle the
                    row's selection on its way past. A drawn chevron, not a
                    slash: a category may be CALLED `and/or`. */}
                {showCategory && (
                  <span title={trailLabel(t.category_trail ?? [])}
                        style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                                 color: "var(--muted-2)", minWidth: 0,
                                 overflow: "hidden", textOverflow: "ellipsis",
                                 whiteSpace: "nowrap" }}>
                    <CategoryTrail trail={t.category_trail ?? []}
                      pickTitle={tr("Show this category")}
                      onPick={(n) => {
                        const trail = t.category_trail ?? [];
                        const hit = catByTrail.get(
                          trail.slice(0, n + 1).join("\u0000"));
                        if (hit != null) patch({ category: [hit],
                                                 uncategorized: false });
                      }} />
                  </span>
                )}
                {/* ONE CELL PER COLUMN OF THE TAG SET — the library's
                    three counts of pictures, an imported set's pair. The
                    table is `tagSetColumns.ts`; nothing here knows which
                    list it is drawing, which is the point.

                    AN ALIAS ROW IS BLANK across all of them: the numbers
                    are the TAG's, and a spelling's tag is the one it points
                    at. Its own verbs are in its row menu, where the other
                    rows' are — a delete button in the last column was one
                    list saying it a second way. */}
                {numCols.map((c) => {
                  const n = t.alias_of != null ? null : (t.numbers?.[c.key] ?? null);
                  const press = c.press && n ? () => filterByCount(
                    t.name, c.press === "negative") : undefined;
                  return (
                    <CountCell
                      key={c.key}
                      base={n}
                      color={c.color}
                      onClick={press}
                      title={
                        n == null ? undefined
                        : c.press === "positive"
                          ? `Show items tagged +${t.name}`
                        : c.press === "negative"
                          ? `Show items tagged −${t.name}`
                        : c.key === "implicit"
                          ? `Of the ${tagCount(t)} items, this many are implied, inherited or carried by a sequence rather than tagged ${t.name} directly`
                        : c.key === "library"
                          ? tr("{n} in this library", { n: String(n) })
                        : undefined}
                    />
                  );
                })}
              </div>
              {strip && strip.length > 0 && (
                <RepStrip tagId={t.id} reps={strip} indent={26}
                  onRefused={onRepsRefused} t={tr} />
              )}
              </div>
            );
          }) : linkTagRows.slice(mainWin.start, mainWin.end).map((r, j) => {
            const i = mainWin.start + j;
            const key = r.name;
            const last = i === linkTagRows.length - 1;
            return (
              <div key={r.name} className="hoverable" {...sel.props(key)}
                style={rowStyle(GRID, selSet.has(key), last)}>
                <RowCheck checked={selSet.has(key)}
                  onToggle={() => toggleKeys([key], !selSet.has(key))} />
                {/* Same fixed-height name line as an item tag's, so the pencil
                    that appears on hover cannot resize the row. */}
                <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, height: 20, fontFamily: "var(--mono)", fontSize: "var(--fs-4)", color: "var(--text)", fontWeight: 500 }}>
                  {/* The name keeps its natural width and only ellipsises
                      when it is too long for the whole cell — the four other
                      lists' rule, because shrink is proportional to base size
                      and a name is the smallest thing on the line. */}
                  <span style={{ flex: "0 0 auto", maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    <Mark text={r.name} q={search} />
                  </span>
                  <Described comment={r.comment} description={r.description}
                             q={search} />
                  {/* LAST, as in the item-tag list: the pencil is what you
                      reach for after reading the row, and between the name
                      and its comment it split the one thing the row says.
                      `marginLeft: auto` parks it at the cell's right edge —
                      the other four lists get that from their capsule strip
                      claiming the leftover width, and this list has none. */}
                  <span
                    className="tag-edit-btn"
                    onClick={(e) => { e.stopPropagation(); setEditingMeta(r); }}
                    title={tr("Edit this meta tag — name, comment and description")}
                    style={{
                      alignItems: "center", justifyContent: "center", flex: "0 0 auto",
                      marginLeft: "auto",
                      width: 20, height: 20, borderRadius: "var(--r-1)",
                      color: "var(--muted-2)", cursor: "pointer",
                    }}
                  >
                    <Icon name="edit" size={14} />
                  </span>
                </span>
                {/* One cell per carrier. A zero is greyed rather than blanked:
                    reading down a column, "0" and "nothing here" are not the
                    same statement. */}
                {([r.links, r.captions, r.tag_groups, r.tags] as number[]).map((n, ci) => (
                  <span key={ci} style={{ textAlign: "right", fontFamily: "var(--mono)", fontSize: "var(--fs-3)", color: n > 0 ? "var(--text-3)" : "var(--muted-3)" }}>
                    {n}
                  </span>
                ))}
              </div>
            );
          })}
          </div>
          </div>

          {/* AND WHAT ONE IS, where there are none (owner 2026-09) — the
              same card a tag set's own Meta list opens on, so the word is
              explained once and the same way wherever it is first met. */}
          {rowCount === 0 && !totalCount && !isTagList && (
            <MetaTagsEmpty t={tr} line={tr("No meta tags yet.")} />
          )}
          {rowCount === 0 && (totalCount > 0 || isTagList) && (
            <EmptyState line={totalCount ? tr("No tags match your filter.") : tr("No tags yet.")} />
          )}
        </div>
        </>)}

        </div>
        </TagsPanes>

      </div>
      {merging && (
        <TagMergeOverlay
          sources={merging}
          allTags={tags ?? []}
          onClose={() => setMerging(null)}
          onMerged={(into, events) => {
            undoKind.current = "merge";
            undo.offer(`${tr("Merged")} → ${into}`, events);
            setSelKeys([]);
            qc.invalidateQueries({ queryKey: ["tags"] });
            qc.invalidateQueries({ queryKey: ["items"] });
            qc.invalidateQueries({ queryKey: ["facets"] });
          }}
        />
      )}
      {/* ONE EDITOR FOR ALL OF IT. A subject, a place and an event are extra
          data on a tag, so the pencil opens the one dialog that holds the
          tag AND its three records. */}
      {/* A SET'S NAME HAS ITS OWN EDITOR — what an entry says is what the
          set claims (its description, its count, its category, what it
          entails and what it says the library's tag IS), where the
          library's dialog edits the tag itself. */}
      {/* THE FILE A SET'S CSV IMPORT READS. Hidden, opened by the Add
          menu's own row — the same shape the library's Tags CSV has. */}
      <input ref={csvIntoRef} type="file" accept=".csv,text/csv"
             style={{ display: "none" }}
             onChange={(e) => {
               const f = e.target.files?.[0];
               e.target.value = "";
               if (f) setCsvFileForSet(f);
             }} />
      {csvFileForSet && openSet && !readOnly && (
        <TagSetCsvOverlay file={csvFileForSet} into={openSet}
          taken={(setsQuery.data ?? []).map((x) => x.name.trim().toLowerCase())}
          onClose={() => setCsvFileForSet(null)}
          onDone={() => {
            setCsvFileForSet(null);
            qc.invalidateQueries({ queryKey: ["tags"] });
            qc.invalidateQueries({ queryKey: ["tag-sets"] });
          }} />
      )}
      {/* ADDING A NAME TO A SET is the same dialog editing one opens, over
          nothing — and adding a SPELLING is the other door of the Add
          menu, exactly as the library's alias is. */}
      {shownSetId != null && setVerbs.creating && openSet && !readOnly && (
        <EntryEditOverlay set={openSet} cats={libCats} entry={null}
          defaultCategoryId={catPicked.length === 1 ? catPicked[0] : null}
          onClose={() => setVerbs.setCreating(false)}
          onSaved={() => {
            setVerbs.setCreating(false);
            qc.invalidateQueries({ queryKey: ["tags"] });
            qc.invalidateQueries({ queryKey: ["tag-sets"] });
          }} />
      )}
      {editingAlias && (
        <AliasCreateOverlay allTags={tags ?? []} editing={editingAlias}
          onClose={() => setEditingAlias(null)}
          onCreated={() => {
            setEditingAlias(null);
            qc.invalidateQueries({ queryKey: ["tags"] });
          }} />
      )}
      {shownSetId != null && retarget && openSet && !readOnly && (
        <AliasOverlay set={openSet} alias={retarget.alias}
          fromName={retarget.fromName}
          onClose={() => setRetarget(null)}
          onSaved={() => {
            setRetarget(null);
            qc.invalidateQueries({ queryKey: ["tags"] });
            qc.invalidateQueries({ queryKey: ["tag-sets"] });
          }} />
      )}
      {shownSetId != null && setVerbs.addingAlias && openSet && !readOnly && (
        <AliasOverlay set={openSet} alias="" fromName={null}
          onClose={() => setVerbs.setAddingAlias(false)}
          onSaved={() => {
            setVerbs.setAddingAlias(false);
            qc.invalidateQueries({ queryKey: ["tags"] });
            qc.invalidateQueries({ queryKey: ["tag-sets"] });
          }} />
      )}
      {shownSetId != null && setVerbs.editing && openSet && !readOnly && (
        <EntryEditOverlay set={openSet} cats={libCats}
          entry={asEntry(setVerbs.editing)}
          defaultCategoryId={catPicked.length === 1 ? catPicked[0] : null}
          onClose={() => setVerbs.setEditing(null)}
          onSaved={() => {
            setVerbs.setEditing(null);
            qc.invalidateQueries({ queryKey: ["tags"] });
            qc.invalidateQueries({ queryKey: ["tag-sets"] });
          }} />
      )}
      {shownSetId == null && (editing || creatingTag) && (
        <TagEditOverlay
          tag={editing ?? null}
          allTags={tags ?? []}
          onClose={() => { setEditing(null); setCreatingTag(false); }}
          // ALL THREE, whatever was edited: one dialog can make this tag a
          // person and take a place away in the same save, so the sweep is
          // the union rather than a guess at which half was touched.
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ["facets"] });
            invalidateSubjects();
            invalidatePlaces();
            invalidateEvents();
          }}
          onMerged={(into, events) => {
            // A merge deletes the tag, so it gets the same Undo a deletion does.
            undoKind.current = "merge";
            undo.offer(`${tr("Merged")} ${editing?.name ?? ""} → ${into}`, events);
            qc.invalidateQueries({ queryKey: ["tags"] });
            qc.invalidateQueries({ queryKey: ["items"] });
            qc.invalidateQueries({ queryKey: ["facets"] });
          }}
        />
      )}
      {/* THE CATEGORY DIALOG — its name, its icon, whether it is hidden,
          and (for an imported set) the two switches that turn its aliases
          and its implications off. One dialog for both tag sets. */}
      {editingCat && paneSetId != null && openTagSet && !readOnly && (
        <CategoryEditOverlay set={openTagSet} cats={libCats}
          cat={editingCat.id === -1 ? { ...editingCat, id: 0 } : editingCat}
          onClose={() => setEditingCat(null)}
          onSaved={() => {
            setEditingCat(null);
            qc.invalidateQueries({ queryKey: ["tag-sets"] });
            qc.invalidateQueries({ queryKey: ["tags"] });
          }} />
      )}
      {addingCategory && !readOnly && (
        <CategoryNameOverlay
          taken={(libraryDetail.data?.category_rows ?? [])
            .filter((c) => c.parent_id == null).map((c) => c.name)}
          onClose={() => setAddingCategory(false)}
          onSave={async (name) => {
            // The one bootstrap: this call makes the library's SET row too,
            // the first time, since it is lazy and there is no id to post to
            // until something needs one.
            await api.createLibraryCategory({ name });
            setAddingCategory(false);
            qc.invalidateQueries({ queryKey: ["tag-sets"] });
          }}
        />
      )}
      {creatingAlias && (
        <AliasCreateOverlay
          allTags={tags ?? []}
          onClose={() => setCreatingAlias(false)}
          onCreated={() => qc.invalidateQueries({ queryKey: ["tags"] })}
        />
      )}
      {(editingMeta || creatingMeta) && (
        <MetaTagEditOverlay
          tag={editingMeta}
          allTags={linkRows ?? []}
          onClose={() => { setEditingMeta(null); setCreatingMeta(false); }}
          onChanged={invalidateLinks}
          onMerged={invalidateLinks}
        />
      )}
      {mergingMeta && (
        <MetaTagMergeOverlay
          sources={mergingMeta}
          allTags={linkRows ?? []}
          onClose={() => setMergingMeta(null)}
          onMerged={() => { setSelKeys([]); invalidateLinks(); }}
        />
      )}
      {rowMenu && (
        <PointerMenu
          at={rowMenu.at}
          onClose={() => setRowMenu(null)}
          actions={rowMenu.selection ? selectionActions()
            : rowActionsFor(rowMenu.kind, rowMenu.name, rowMenu.label, rowMenu.own, true)}
        />
      )}
      {undo.state && (
        <ActionToast
          text={undo.state.undone
            ? (undoKind.current === "merge"
                ? tr("The merge was undone") : tr("The deletion was undone"))
            : undo.state.label}
          actionLabel={undo.state.undone ? tr("Redo") : tr("Undo")}
          actionTitle={undo.state.undone
            ? (undoKind.current === "merge"
                ? tr("Fold them together again")
                : tr("Delete them again"))
            : (undoKind.current === "merge"
                ? tr("Split the tags apart again, with their assignments")
                : tr("Put the deleted tags back, with their assignments"))}
          icon={undo.state.undone ? "redo" : "undo"}
          dismissTitle={tr("Put this message away")}
          onAction={() => void undo.toggle()}
          onDismiss={undo.dismiss}
        />
      )}
    </div>
  );
}


/** The vertical padding is the room a ONE-line row has to spare. A row that
 *  stays inside `minHeight` is centred and needs no padding, so there was none
 *  — and a wrapped implication subtitle, the one thing that outgrows the
 *  minimum, ended up with its text against the row's edges. Padding it by the
 *  slack a one-line row still has (its name line, the column gap and one
 *  subtitle line, against the 50 px minimum) gives every taller row that same
 *  breathing room top and bottom, while leaving rows with no subtitle or one
 *  line of it at exactly the height they had. `minHeight` is a border-box
 *  measure, so the row's own bottom border comes out of the same budget — miss
 *  it and the one-line row grows by that pixel. Rounded DOWN a tenth so no
 *  sub-pixel rounding can nudge it over either. */
const ROW_PAD_Y = Math.floor((50 - 1 - (20 + 1 + 10.5 * 1.45)) / 2 * 10) / 10;

/** `minHeight` is what keeps an item row from resizing as its second line comes
 *  and goes: 50 clears the tallest thing that line can hold — the "+ implies"
 *  autocomplete (26) under the name (18) — so opening it, hovering the row, or
 *  a tag gaining its first implication all leave the table exactly where it
 *  was. Only wrapped implication chips make a row genuinely taller. */
function rowStyle(grid: string, selected: boolean, last: boolean,
                  minHeight = 46): React.CSSProperties {
  return {
    display: "grid", gridTemplateColumns: grid, padding: `${ROW_PAD_Y}px 16px`, minHeight,
    alignItems: "center", borderBottom: last ? "none" : "1px solid var(--border-soft)",
    background: selected ? "var(--accent-dim)" : undefined,
    // The panel is rounded and `overflow: visible` (sticky headers), so the
    // LAST row's own hover/selection wash must carry the curve itself or it
    // paints square over the corners — the header's rule, mirrored.
    borderRadius: last ? "0 0 11px 11px" : undefined,
    cursor: "default",
  };
}

/** Text with every occurrence of the search query picked out, so a hit in a
 *  long list is visible rather than merely present. */
/** The Subjects list's one filter, as a menu.
 *
 * Five named views rather than two cycles: a control that steps through more
 * than two states never shows you where it can go, and multiplying the two
 * together produced combinations that meant nothing ("subjects only, unnamed
 * faces" describes an empty list).
 */
/** The two relations a tag can stand in — mutually exclusive, because an
 *  alias entails nothing, so asking for both could only ever show an empty
 *  table. That exclusion used to be enforced by each toggle switching the
 *  other off; as one section it is simply what a section is. */
const RELATION_VIEWS: { id: "all" | "aliases" | "implies";
                        label: string; icon: string }[] = [
  { id: "all", label: "Any relation", icon: "filter_list" },
  { id: "aliases", label: "Aliases", icon: "alt_route" },
  { id: "implies", label: "Implications", icon: "arrow_right_alt" },
];

/** What a tag NAMES — the same four the item-tag list can hold, since a
 *  subject and a place are ordinary tags carrying extra data. */
const GROUP_VIEWS: { id: "grouped" | "flat"; label: string;
                     icon: string }[] = [
  { id: "grouped", label: "Grouped by namespace", icon: "account_tree" },
  { id: "flat", label: "Flat list", icon: "format_list_bulleted" },
];


/** Whether the items list draws a strip of REPRESENTATIVE items under
 *  each tag — "Names only" is the list as it always was. */
const REPS_VIEWS: { id: "none" | "reps"; label: string; icon: string }[] = [
  { id: "none", label: "Names only", icon: "view_list" },
  { id: "reps", label: "Representative items", icon: "image" },
];

/** A strip's height beyond the row: the thumbnail plus its padding — what
 *  the windowed list's estimate adds per tag with a picture to show. */
const REP_STRIP_H = 78;

/** A ranking's minted rows, in the list or out of it. They are ordinary tags
 *  and belong in the catalog; they are also the only tags in it that nobody
 *  wrote, and a 0-100 ranking puts a hundred of them between everything
 *  else. */
/** KEPT OUT OF THE AUTOCOMPLETE, or not. The tag's OWN flag: the namespace
 *  rule that hides a whole dump's worth is a setting with its own control,
 *  and a list narrowed by it would be a list of the dump. */
const SUGGEST_VIEWS: { id: TagsSuggest; label: string; icon: string }[] = [
  { id: "all", label: "Offered or not", icon: "filter_list" },
  { id: "shown", label: "Offered", icon: "visibility" },
  { id: "hidden", label: "Hidden from suggestions", icon: "visibility_off" },
];

const REP_CROP = 64;

/** THE REPRESENTATIVE PICTURES OF ONE TAG — the Subjects list's face strip,
 *  for tags: up to a handful of thumbnails under the row, each with a
 *  hover ✕ that says "not this one" (the item stops standing for the tag,
 *  is never picked for it again while it carries the tag, and another
 *  takes its place — `representatives.py`). A CLICK opens the preview
 *  overlay on it — the rankings' sample strips' rule, one list along —
 *  over the tag's whole strip IN THE ROW'S ORDER, positioned at the one
 *  clicked (the last thumbnail reads "8 / 8"), so ‹ › step through its
 *  other representatives; a double-click shows the item in the library. A thumbnail stops the row's own click; the strip's empty
 *  background still selects the row. */
function RepStrip({ tagId, reps, indent, onRefused, t }: {
  tagId: number;
  reps: RankingItemRef[];
  indent: number;
  onRefused: (tagId: number, reps: RankingItemRef[]) => void;
  t: (s: string) => string;
}) {
  const show = useUI((s) => s.showItemInLibrary);
  const openQuickLook = useUI((s) => s.openQuickLook);
  const [busy, setBusy] = useState<number | null>(null);
  // The ✕ is the THUMBNAIL's, revealed by its own hover — not the row's
  // (`.row-actions` under any hovered `.hoverable` ancestor), which showed
  // eight crosses the moment the pointer crossed the row.
  const [over, setOver] = useState<number | null>(null);
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 7,
                  padding: `2px 16px 12px ${16 + indent}px` }}>
      {reps.map((r, i) => (
        <span key={r.item_id}
          title={r.name || r.uid}
          onMouseEnter={() => setOver(r.item_id)}
          onMouseLeave={() => setOver((cur) => cur === r.item_id ? null : cur)}
          onClick={(e) => { e.stopPropagation();
            openQuickLook(reps.map((x) => x.item_id), { start: i }); }}
          onMouseDown={(e) => e.stopPropagation()}
          onDoubleClick={(e) => { e.stopPropagation(); show(r.item_id, r.uid); }}
          style={{ position: "relative", width: REP_CROP, height: REP_CROP,
                   borderRadius: "var(--r-4)", overflow: "hidden",
                   background: "var(--panel-3)",
                   border: "1px solid var(--border)",
                   opacity: busy === r.item_id ? 0.4 : 1,
                   display: "flex", alignItems: "center",
                   justifyContent: "center", cursor: "pointer" }}>
          {r.file_id != null ? (
            <img src={api.thumbUrl(r.file_id, 0, r.thumb_token)}
              alt="" draggable={false}
              style={{ width: "100%", height: "100%", objectFit: "cover",
                       display: "block" }} />
          ) : (
            <Icon name="image" size={20} color="var(--muted-2)" />
          )}
          {/* "Not this one" — revealed on hover, like a face crop's ✕. */}
          <span
            onClick={(e) => {
              e.stopPropagation();
              if (busy != null) return;
              setBusy(r.item_id);
              api.refuseRepresentative(tagId, r.item_id)
                .then((res) => onRefused(tagId, res.reps))
                .finally(() => setBusy(null));
            }}
            title={t("Not representative — another picture takes its place")}
            style={{ position: "absolute", top: 3, right: 3, width: 18,
                     height: 18, borderRadius: "var(--r-1)", cursor: "pointer",
                     display: over === r.item_id ? "flex" : "none",
                     alignItems: "center", justifyContent: "center",
                     background: "var(--surface-float)",
                     border: "1px solid var(--border-strong)",
                     color: "var(--text)" }}>
            <Icon name="close" size={13} />
          </span>
        </span>
      ))}
    </div>
  );
}

const KIND_VIEWS: { id: "all" | "plain" | "subjects" | "places" | "events";
                    label: string; icon: string }[] = [
  { id: "all", label: "Any kind", icon: "filter_list" },
  { id: "plain", label: "Plain", icon: "sell" },
  { id: "subjects", label: "Subjects", icon: RECORD_ICON.subject },
  { id: "places", label: "Places", icon: RECORD_ICON.place },
  { id: "events", label: "Events", icon: RECORD_ICON.event },
];

/** What narrows the rows — one axis, so one group.
 *
 *  TWO ANSWERS, where there were five. *With faces* and *With a guess
 *  waiting* were about a person, and people are the Faces tab now; *Without
 *  a tag* was about a record that had none, which cannot exist. */
const SCOPE_VIEWS: { id: TagsScope; label: string; icon: string }[] = [
  { id: "all", label: "Everything", icon: "filter_list" },
  { id: "unassigned", label: "On no item", icon: "hide_image" },
];


/** The person / place icons after a tag's name in the item-tag list.
 *
 *  A subject and a place ARE ordinary tags carrying extra data, which is what
 *  makes the whole design work — and also what makes them invisible in a list
 *  of slugs. The marker says which is which, names it in the tooltip (a slug
 *  cannot hold "Michael Jordan · basketball" or a street address), and takes
 *  you to the list where that half of it is edited.
 */
function KindMark({ subject, place, event, says, onGo, t }: {
  subject?: SubjectRow;
  place?: PlaceRow;
  event?: EventRow;
  /** WHAT A TAG SET'S OWN ENTRY SAYS THE NAME IS — the row's three optional
   *  records, drawn where the list is a SET's and the library therefore has
   *  nothing to show (owner 2026-09: "for tag sets, show the subject /
   *  event / place icons when attached to a tag, same as when showing the
   *  list for the library"). Without them a 110,868-row set was a column in
   *  which every name looked alike, and the 8,653 that are a FRANCHISE
   *  rather than a person were indistinguishable from the 102,215 that are.
   *
   *  QUIET, and dimmer than the library's: there is no list to go to (the
   *  library has no such record — that is what makes this the set talking),
   *  and this app's rule is that a mark which reads as a state and acts as a
   *  button is one an aimed click undoes by accident. */
  says?: { subject?: unknown; place?: unknown; event?: unknown };
  /** WHICH LIST TO SHOW. It names a retired sub-tab on purpose: the store
   *  turns the ask into the Items list narrowed to that kind, which is what
   *  those pages were, and saying "places" here reads as what the mark is
   *  about rather than as a filter value. */
  onGo: (m: TagsModeAsked) => void;
  t: (s: string) => string;
}) {
  const lang = useLang();
  const mark = (icon: string, label: string, mode: TagsModeAsked) => (
    <span
      onClick={(e) => { e.stopPropagation(); onGo(mode); }}
      title={label}
      style={{
        flex: "0 0 auto", display: "flex", alignItems: "center",
        color: "var(--muted-2)", cursor: "pointer",
      }}
    >
      <Icon name={icon} size={13} />
    </span>
  );
  const quiet = (icon: string, label: string) => (
    <span title={label}
          style={{ flex: "0 0 auto", display: "flex", alignItems: "center",
                   color: "var(--muted-3)", opacity: 0.85 }}>
      <Icon name={icon} size={13} />
    </span>
  );
  /** What the set says, as a line: its display name where it gave one.
   *  The LABEL arrives translated — the harvest reads `t("…")` literals and
   *  cannot see a string handed through an argument. */
  const said = (rec: unknown, label: string) => {
    const name = (rec as { name?: string } | null)?.name;
    return name ? `${label}: ${name}` : label;
  };
  if (subject || place || event) {
    return (
      <>
        {subject && mark(RECORD_ICON.subject,
          [subject.display_name || subject.tag, subject.comment]
            .filter(Boolean).join(" · ") + ` — ${t("show the Subjects list")}`,
          "subjects")}
        {place && mark(RECORD_ICON.place,
          placeLabel(place)
            + ` — ${t("show the Places list")}`,
          "places")}
        {event && mark(RECORD_ICON.event,
          [event.display_name || event.tag,
           spanLabel(event.start_date, event.end_date, lang)]
            .filter(Boolean).join(" · ") + ` — ${t("show the Events list")}`,
          "events")}
      </>
    );
  }
  if (!says || (!says.subject && !says.place && !says.event)) return null;
  return (
    <>
      {says.subject != null
        && quiet(RECORD_ICON.subject,
                 said(says.subject, t("The tag set says this is somebody")))}
      {says.place != null
        && quiet(RECORD_ICON.place,
                 said(says.place, t("The tag set says this is a place")))}
      {says.event != null
        && quiet(RECORD_ICON.event,
                 said(says.event, t("The tag set says this is an event")))}
    </>
  );
}

/**
 * WHAT THE TAG SET SAYS about a tag, behind its name.
 *
 * A meta tag on a tag says something about the TAG — "noflip", "character",
 * "from a booru" — and never about the pictures carrying it, which is why it
 * appears here and in the four edit overlays and nowhere else in the app: a
 * capsule on a picture's tag row would read as a label on the picture.
 *
 * They read rather than invite: adding and removing one is in the tag's own
 * editor, where the rest of what a tag IS is changed. Capsules rather than a
 * comma line, because they are a SET of short names and the eye counts
 * capsules; muted rather than accent, because nothing here is clickable.
 *
 * AT MOST `SHOWN` OF THEM, then a "+N". A capsule refuses to shrink, and a
 * `fr` grid track has an implicit `min-width: auto` — so a tag with thirteen
 * of them widened its own track past its share, which widened the grid, which
 * pushed the counts off the panel and put a scrollbar under the whole page.
 * The name is what a row is FOR, so it is the capsules that yield: the strip
 * caps its count and clips whatever still does not fit.
 */
/**
 * The one-liner beside a name, and the ? that opens the long form.
 *
 * The same pair the tag autocomplete shows, in the same order, because they
 * are the same two fields answering the same two questions: what is this, in
 * a glance — and, if that is not enough, what is this at length. A row is one
 * line, so the comment ELLIPSISES and the long form is not on it at all; the
 * ? is how a paragraph reaches a list without turning the list into
 * paragraphs. For a tag row the long form is what the enabled TAG SETS say
 * (`descriptions`); a meta tag still carries a `description` of its own.
 */
function Described({ comment, description, descriptions, library, name, q }: {
  comment?: string; description?: string; descriptions?: TagSetText[];
  /** What the LIBRARY says about this tag — its own long form and where it
   *  files it. The library is a tag set now, so this is the popover's first
   *  frame; built from the row rather than fetched, since the row already
   *  carries it. */
  library?: { text?: string; comment?: string; trail?: string[] };
  /** The tag the row is about, so the popover can offer to show it where
   *  its set files it. */
  name?: string;
  q?: string;
}) {
  return (
    <>
      {!!comment && (
        <span style={{
          flex: "0 1 auto", minWidth: 0, overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap",
          fontFamily: "var(--sans)", fontSize: "var(--fs-2)", color: "var(--muted-2)",
        }}>
          <Mark text={comment} q={q ?? ""} />
        </span>
      )}
      <DescriptionMark description={description} descriptions={descriptions}
                       library={library} name={name} />
    </>
  );
}



/** How wide the Tags tab's left column is. Not draggable yet — the Sets
 *  tab's split is, and the two become one column when the tab is merged. */
const SIDEBAR_W = 220;

/** WHICH RECORD KIND THE LIST IS NARROWED TO, or null.
 *
 *  Exactly one, which is what changes the rows' SHAPE: with several ticked
 *  (or none) a row is a tag and the name IS the answer, so there is nothing
 *  to lead with. The Sets tab's `asKind` rule, over the library's own tags. */
function asKind(kind: string): "subject" | "place" | "event" | null {
  return kind === "subjects" ? "subject" : kind === "places" ? "place"
    : kind === "events" ? "event" : null;
}

/** NAMING THE FIRST CATEGORY IS WHAT MAKES THE LIBRARY'S SET.
 *
 *  A name and nothing else: an icon, a parent and the two advice switches
 *  are the category dialog's, opened from the row afterwards. This one
 *  exists because there is no row yet — and because the library's set is
 *  lazy, so this call is also the one that brings it into being. */
function CategoryNameOverlay({ taken, onClose, onSave }: {
  taken: string[]; onClose: () => void; onSave: (name: string) => Promise<void>;
}) {
  const t = useT();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const clash = taken.some((n) => n.trim().toLowerCase() === name.trim().toLowerCase());
  const ok = !!name.trim() && !clash && !busy;
  const save = async () => {
    if (!ok) return;
    setBusy(true);
    try { await onSave(name.trim()); } finally { setBusy(false); }
  };
  return (
    <Overlay icon="create_new_folder" title={t("Add category")}
             onClose={onClose} width={420}
             unsaved={{ dirty: !!name.trim(), onSave: () => void save(), t }}
             footer={<>
               <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
               <Button variant="primary" icon="check" onClick={() => void save()}
                              disabled={!ok}>
                 {t("Save")}
               </Button>
             </>}>
      <div style={{ padding: 18 }}>
        <FieldLabel>{t("Name")}</FieldLabel>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") void save(); }}
               style={fieldStyle} />
        {clash && (
          <div style={{ color: "var(--red-text)", fontSize: "var(--fs-3)", marginTop: 6 }}>
            {t("A category with that name is already here.")}
          </div>
        )}
      </div>
    </Overlay>
  );
}


/** A heading row's select-all, over ITS OWN rows.
 *
 *  With two lists on the page each one answers for its own: the subjects
 *  header ticking every unnamed cluster as well would be a box that selects
 *  things nobody can see from it. The selection itself still spans both — this
 *  only adds and removes its own keys. */
/** A right-aligned count cell. The value is the tag's effective (resolution-
 *  aware) count — items where the tag is assigned directly or indirectly. */
function CountCell({
  base, color, onClick, title,
}: {
  base: number | null;
  color: string;
  onClick?: () => void;
  title?: string;
}) {
  return (
    <span style={{ textAlign: "right", fontFamily: "var(--mono)", fontSize: "var(--fs-3)" }}>
      <span
        onClick={onClick ? (e) => { e.stopPropagation(); onClick(); } : undefined}
        title={title}
        style={{ color, cursor: onClick ? "pointer" : "default" }}
      >{base == null ? "" : base}</span>
    </span>
  );
}

/** THE CHECKBOX ON A ROW (owner 2026-09, back after a month away). The rows
 *  select by click, ⌘-click, shift and paint like every other list here,
 *  and a box beside each is the one gesture that ADDS a row without
 *  disturbing the run already picked — and, in the header, the one way a
 *  list of a hundred thousand names is picked WHOLE where a drag cannot
 *  reach. The press and the click stop here: the row behind it would
 *  otherwise arm its paint and then replace the selection with this row.
 *  `mixed` is the header's and a namespace parent's third state. */
function RowCheck({ checked, mixed, title, onToggle }: {
  checked: boolean; mixed?: boolean; title?: string; onToggle: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = !!mixed && !checked;
  }, [mixed, checked]);
  return (
    <span onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
          onDoubleClick={(e) => e.stopPropagation()}
          style={{ display: "flex", alignItems: "center", height: 20,
                   width: CHECK_W, marginLeft: -4 }}>
      <input ref={ref} type="checkbox" checked={checked} onChange={onToggle}
             title={title} aria-label={title}
             style={{ margin: 0, cursor: "pointer", accentColor: "var(--accent)" }} />
    </span>
  );
}

function Heading({
  label, col, active, dir, onClick, align, range, onRange, t,
}: {
  label: string;
  col: SortKey;
  active: SortKey;
  dir: SortDir;
  onClick: (c: SortKey) => void;
  align?: "right";
  /** A COUNT COLUMN CAN BE NARROWED BY ITS OWN NUMBERS. Passed only for the
   *  count columns; the name and comment headings just sort. */
  range?: { lo: number | null; hi: number | null };
  onRange?: (r: { lo: number | null; hi: number | null }) => void;
  t?: (s: string) => string;
}) {
  const isActive = active === col;
  const [open, setOpen] = useState(false);
  // ITS OWN HOVER. The reveal class every ROW action uses is scoped to a
  // `.hoverable` ancestor (`tokens.css`), and a heading is not one — so the
  // button was `visibility: hidden` with nothing that could ever show it.
  const [over, setOver] = useState(false);
  const anchor = useRef<HTMLSpanElement>(null);
  const rect = useAnchorRect(anchor, open);
  const on = !!range && (range.lo != null || range.hi != null);
  const tr = t ?? ((x: string) => x);
  const num = (v: string): number | null => {
    const n = parseInt(v, 10);
    return v.trim() === "" || Number.isNaN(n) ? null : Math.max(0, n);
  };
  // The shared dense field, one step shorter and narrow: a number in a
  // column heading.
  const rangeField: React.CSSProperties = {
    ...fieldStyleSm, width: 62, height: 26, borderRadius: "var(--r-3)", padding: "0 7px",
    background: "var(--panel-2)",
  };
  /* THE RANGE LIVES ON THE COLUMN IT IS ABOUT. These columns are what the
     list is READ for — "which tags am I using twice" is a question about a
     number in a cell — so the control belongs at the top of that cell's
     column rather than in a menu that has to name it again. It shows only
     when the column HAS one or the pointer is here, and lights up while it
     does. */
  const button = range && onRange ? (
    <IconButton icon={on ? "filter_alt" : "filter_alt_off"} size={20} glyph={14} reveal="hover" color={on ? "var(--accent)" : "var(--muted-2)"} ref={anchor}
      title={tr("Narrow this column to a range")}
      onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }} style={{ visibility: on || over || open ? "visible" : "hidden" }} />
  ) : null;
  return (
    <span
      onMouseEnter={() => setOver(true)}
      onMouseLeave={() => setOver(false)}
      style={{ display: "flex", alignItems: "center", gap: 3,
               justifyContent: align === "right" ? "flex-end" : "flex-start" }}>
      {/* ON A RIGHT-ALIGNED COLUMN THE BUTTON GOES FIRST, so the LABEL keeps
          the right edge — the cells under it are right-aligned numbers, and
          a button after the label pushed every heading a glyph's width left
          of the column it names. */}
      {align === "right" && button}
      <span
        onClick={() => onClick(col)}
        style={{
          display: "flex", alignItems: "center", gap: 3, cursor: "pointer",
          userSelect: "none", color: isActive ? "var(--text-3)" : undefined,
        }}
      >
        {label}
        {isActive && (
          <Icon name={dir === "asc" ? "arrow_upward" : "arrow_downward"} size={14} />
        )}
      </span>
      {align !== "right" && button}
      {open && range && onRange && (
        <AnchoredDropdown rect={rect} minWidth={170}>
          <div onClick={(e) => e.stopPropagation()}
               style={{ display: "flex", alignItems: "center", gap: 6,
                        padding: 6, textTransform: "none", letterSpacing: 0,
                        fontWeight: 400 }}>
            <input type="number" min={0} placeholder={tr("Least")}
              value={range.lo ?? ""} style={rangeField}
              onChange={(e) => onRange({ ...range, lo: num(e.target.value) })} />
            <span style={{ color: "var(--muted-2)" }}>–</span>
            <input type="number" min={0} placeholder={tr("Most")}
              value={range.hi ?? ""} style={rangeField}
              onChange={(e) => onRange({ ...range, hi: num(e.target.value) })} />
            <span role="button" title={tr("Clear")}
              onClick={() => { onRange({ lo: null, hi: null }); setOpen(false); }}
              style={{ display: "flex", cursor: "pointer", color: "var(--muted-2)" }}>
              <Icon name="close" size={16} />
            </span>
          </div>
        </AnchoredDropdown>
      )}
    </span>
  );
}
