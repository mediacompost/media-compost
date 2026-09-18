import React, { useEffect, useMemo, useRef, useState } from "react";
import { APP_PREFS } from "../prefs";
import { isTypingTarget } from "../../shared/typingTarget";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ItemOut, TagBox, TagInstance } from "../api";
import { Icon } from "../../shared/Icon";
import { Chip } from "../../shared/Chip";
import { modalIsOpen, quickLookIsCovered, tagGridIsOpen, useUI } from "../store";
import { LAYER } from "../../shared/layers";
import { useEscape } from "../../shared/useEscape";
import { useLoadedViewItems } from "../useItems";
import { keepsPreviousPreview } from "../viewPlaceholder";
import { bumpLibrary } from "../invalidation";
import { useLang, useT, useTn } from "../i18n";
import { mpLabel } from "../format";
import { useZoomPan } from "../useZoomPan";
import { useWheel } from "../useWheel";
import { panLimit } from "../zoomPivot";
import { nextDistinctIndex, occurrenceIndex } from "../viewWalk";
import { previewArrow } from "../previewKeys";
import { ZoomControls } from "./shared/ZoomControls";
import { useRotate } from "./shared/useRotate";
import { groupTagInstances, ItemInfoPanel } from "./shared/ItemInfoPanel";

// Whether the tags/captions side panel is open, across reloads.

// macOS-Finder-style "QuickLook": press Space to show a large preview of the
// current selection, Space (or Escape) again to close, ←/→ to step through a
// multi-item selection. Always mounted so it can catch the opening Space.
export function QuickLook() {
  const previewFooter = useUI((st) => st.previewFooter);
  const tr = useT();
  const lang = useLang();
  const tn = useTn();
  const qc = useQueryClient();
  const quickLook = useUI((s) => s.quickLook);
  const setQuickLook = useUI((s) => s.setQuickLook);
  const showItemInLibrary = useUI((s) => s.showItemInLibrary);
  const toggleQuickLook = useUI((s) => s.toggleQuickLook);
  const liveSelectedItems = useUI((s) => s.selectedItems);
  const quickLookItems = useUI((s) => s.quickLookItems);
  const quickLookStart = useUI((s) => s.quickLookStart);
  // A specific source file to preview (the Files list's preview button)
  // instead of the item's active file.
  const quickLookFile = useUI((s) => s.quickLookFile);
  // What the OPENER knew and the item does not: the moment a `frame` link
  // names, and the region a crop link was cut from.
  const raised = useUI((s) => s.quickLookRaised);
  const quickLookAt = useUI((s) => s.quickLookAt);
  const quickLookBoxes = useUI((s) => s.quickLookBoxes);
  // Preview the live grid selection by default (so Space works on the grid even
  // while the sidebar is pinned elsewhere); the sidebar preview button passes an
  // explicit target via `quickLookItems` to preview the pinned sidebar item.
  const selectedItems = quickLookItems ?? liveSelectedItems;
  const anchorItem = useUI((s) => s.anchorItem);
  const visibleItemIds = useUI((s) => s.visibleItemIds);
  // Whatever pages of the view are loaded — off-grid items already fall back
  // to their own detail fetch below, and an unloaded page's items do the same.
  const items = useLoadedViewItems();

  const byId = useMemo(() => {
    const m = new Map<number, ItemOut>();
    for (const it of items) m.set(it.id, it);
    return m;
  }, [items]);

  // The selection to preview: items present in the grid first (in grid order),
  // then any selected items that aren't in the current view (e.g. one reached via
  // a sidebar link) appended — so QuickLook works even for off-grid items.
  // DEDUPED, and that is a fix rather than tidiness: in a SEQUENCE view the
  // grid draws one card per POSITION, so `visibleItemIds` holds a repeated
  // page once per occurrence — and a page that appears three times in a book
  // made the preview offer ‹ › arrows that stepped three times through the
  // same picture. Three occurrences of one picture are one picture.
  const ordered = useMemo(() => {
    const sel = new Set(selectedItems);
    const inGrid = visibleItemIds.filter((id) => sel.has(id));
    const seen = new Set(inGrid);
    const offGrid = selectedItems.filter((id) => !seen.has(id));
    return [...new Set([...inGrid, ...offGrid])];
  }, [selectedItems, visibleItemIds]);

  const [idx, setIdx] = useState(0);
  // Optional side panel listing the item's tags (by group) + captions.
  // Remembered per browser: whether the panel is wanted is a way of using the
  // preview, not a fact about any one open of it — so EVERY open reads the
  // remembered answer (owner 2026-09), and Tab and the button write it.
  // Read at open rather than at mount alone: the preview over a session is
  // an instance of its own, and the one over the library stays mounted
  // across opens, so the two would otherwise drift apart.
  const [showInfo, setShowInfo] = useState(() => APP_PREFS.quickLookInfo.read());
  useEffect(() => {
    if (quickLook) setShowInfo(APP_PREFS.quickLookInfo.read());
  }, [quickLook]);
  // The spatial boxes to overlay on the preview (a hovered tag's bounding boxes).
  const [hoverBoxes, setHoverBoxes] = useState<TagBox[] | null>(null);

  // ESCAPE IS THE STACK'S: opened last, this preview is on top of whatever
  // it was opened over — a dialog included (`raised`) — and a dialog opened
  // over IT is on top of this. One press, one thing closes.
  useEscape(() => setQuickLook(false), { enabled: !!quickLook });

  // Toggle on Space (unless typing / focused in a form control); the opening
  // Space is ignored when there's nothing selected.
  //
  // ⇧SPACE IS THE OTHER LOOK (owner 2026-09): the PINNED preview — the
  // picture over the grid pane with the sidebars left alone, which the grid
  // menu's **Pin Preview** opens — rather than a second way into the
  // full-window one. And while a pinned preview is up, ANY Space puts it
  // down, modifier or not: it is what is on screen, so it is what the key is
  // about, and having to remember which Space unpinned it would be a rule
  // about a picture.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Not while anything is over the page — the item window, the T / Q
      // overlays, which paint on top of this preview and own the keyboard,
      // or one of the three judging sessions: their Space opens THIS
      // preview over themselves (`useSessionKeys`), and closes it, so the
      // key is theirs while they are up.
      if (modalIsOpen()) return;
      if (e.code !== "Space") return;
      if (isTypingTarget(e)) return;
      const st = useUI.getState();
      // Closing is always allowed — whichever of the two looks is up.
      if (st.quickLook) { e.preventDefault(); toggleQuickLook(); return; }
      if (st.captionPreview != null) {
        e.preventDefault();
        st.setCaptionPreview(null);
        return;
      }
      // Space previews the live grid SELECTION, so it only opens over the
      // grid: the overlay is mounted in the Tags tab too (the rankings list
      // opens it on a thumbnail), and there the key would preview whatever
      // the library happened to be holding.
      if (st.view !== "library" || st.selectedItems.length === 0) return;
      e.preventDefault(); // no page scroll, no activating a focused button
      if (e.shiftKey) {
        // ONE picture is pinned — the look is one big picture over the grid —
        // so it is the one the selection was aimed at (the anchor), and the
        // first of them when that says nothing.
        const anchor = st.anchorItem;
        st.setCaptionPreview(
          anchor != null && st.selectedItems.includes(anchor)
            ? anchor : st.selectedItems[0]);
        return;
      }
      toggleQuickLook();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleQuickLook]);

  // When opening, start where the opener said (a strip's clicked
  // thumbnail — the list is the row, in the row's order, and the counter
  // reads its position), else at the anchor item, else the first.
  useEffect(() => {
    if (!quickLook) return;
    const start = quickLookStart != null ? quickLookStart
      : anchorItem != null ? ordered.indexOf(anchorItem) : 0;
    setIdx(start >= 0 && start < Math.max(1, ordered.length) ? start : 0);
  }, [quickLook]); // eslint-disable-line react-hooks/exhaustive-deps

  // Close automatically if the selection empties while open.
  useEffect(() => {
    if (quickLook && ordered.length === 0) setQuickLook(false);
  }, [quickLook, ordered.length, setQuickLook]);

  // THE ENTRY the preview is on — which is not always what is on SCREEN: a
  // sequence has no picture of its own, so previewing one turns its pages
  // (`pages` below) and the entry stays the chapter while the member shows.
  const entryId = ordered.length
    ? ordered[Math.min(idx, ordered.length - 1)] : null;
  const entryInGrid = entryId != null ? byId.get(entryId) : undefined;
  // Under the SAME key the shown item's detail uses, so where the two
  // coincide (everywhere but inside a sequence) React Query dedupes them and
  // this costs no request at all.
  const { data: entryFetched } = useQuery({
    queryKey: ["item", entryId],
    queryFn: () => api.item(entryId as number),
    enabled: quickLook && entryId != null && !entryInGrid,
  });
  const entry = entryInGrid ?? entryFetched;
  const seqId = entry?.kind === "sequence" ? entry.sequence_id ?? null : null;
  const { data: seq } = useQuery({
    queryKey: ["sequence", seqId],
    queryFn: () => api.sequence(seqId as number),
    enabled: quickLook && seqId != null,
  });
  /** The pages a sequence entry is walked by, deduped like `ordered` and for
   *  the same reason: a book's three blank pages are one picture, and turning
   *  onto the same one twice reads as a key that did nothing. */
  const pages = useMemo(() => (
    seq && seq.id === seqId && seq.members.length
      ? [...new Set(seq.members.map((m) => m.item_id))] : null
  ), [seq, seqId]);
  const [page, setPage] = useState(0);
  // Which way the last step went, so ARRIVING at a sequence backwards lands
  // on its last page: the walk has to read the same in both directions or
  // ← from the item after a chapter would drop you at its front cover.
  const back = useRef(false);
  useEffect(() => {
    setPage(pages && back.current ? pages.length - 1 : 0);
  }, [entryId, pages?.length]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Escape closes. Arrow keys own navigation while open (the grid ignores them).
  // Up/Left = "previous", Down/Right = "next", and there are three things they
  // can step, tried in this order:
  //
  //   1. THE PAGES of a sequence, when the preview is on one. Previewing a
  //      chapter and turning it is what anybody reaches for, and off either
  //      end the key falls through to (2) or (3) — the chapter is left the way
  //      any other item is left. SHIFT SKIPS THIS ONE (owner 2026-09):
  //      ⇧←/⇧→ leave the chapter at once rather than turning its two hundred
  //      pages to get out of it, which is the same fall-through asked for
  //      outright. Whose shift it is, is `previewKeys.previewArrow`.
  //   2. THE SELECTION, when several items are previewed (the ‹ › buttons are
  //      showing): the preview index moves and the grid selection is untouched.
  //   3. THE GRID, for a single selection: the selection moves to the previous
  //      or next item in the view's order and the preview follows.
  //
  // (3) STEPS ONE CARD OF THE VIEW — the occurrence, not the item, which is
  // a distinction only a sequence view makes (`viewWalk`). It draws a
  // repeated page once per POSITION, so an item id cannot say where the walk
  // is: `indexOf` answers that page's FIRST appearance however far into the
  // book you are, so from its second the walk stepped as though from its
  // first. The membership row the selection names (`selMembers`) says which
  // copy, and the step is one card from THERE — over a RUN of the same
  // picture, since a book's three blank pages in a row are one picture and a
  // key that redraws it reads as a key that did nothing. The occurrence it
  // lands on is named in turn, so the grid's ring and its own arrows carry
  // on from where the preview left off.
  const stepSelection = (delta: number) => {
    // An explicit target (sidebar preview) steps its own list, never the grid.
    if (useUI.getState().quickLookItems) return false;
    const st = useUI.getState();
    const sel = st.selectedItems;
    if (sel.length !== 1) return false; // multi: don't touch the grid selection
    const order = st.visibleItemIds;
    const members = items.map((it) => it.member_id ?? null);
    const named = st.selMembers.size === 1 ? [...st.selMembers][0] : null;
    const cur = occurrenceIndex(order, members, sel[0], named);
    if (cur === -1) return false;
    const next = nextDistinctIndex(order, cur, delta);
    if (next === -1) return true; // at an end: absorb key
    st.setSelectedItems([order[next]]);
    const m = members[next];
    if (m != null) st.setSelMembers(new Set([m]));
    return true;
  };

  useEffect(() => {
    if (!quickLook) return;
    const onKey = (e: KeyboardEvent) => {
      // Not while the item window is over us (see `itemWindowIsOpen`) — nor
      // the T / Q overlays, which open ON TOP of this preview and own the
      // keyboard while they are up: their autocomplete's arrow keys used to
      // ALSO step the grid selection underneath, and their Escape closed
      // this preview along with themselves. NOT `modalIsOpen`: the tag-grid
      // session sits UNDER this preview and opens it over its own cards, so
      // it is the one overlay that must not silence these keys.
      if (quickLookIsCovered()) return;
      // TAB toggles the side panel — the browser's own focus walk means
      // nothing here (this overlay has three buttons and owns the keyboard),
      // and the panel is the one thing about the preview that is a MODE
      // rather than a step. Modifiers are somebody else's: ⇧⇥ and ⌘⇥ are the
      // page's and the system's.
      if (e.key === "Tab" && !e.shiftKey && !e.metaKey && !e.ctrlKey
          && !e.altKey) {
        e.preventDefault();
        setShowInfo((v) => { APP_PREFS.quickLookInfo.write(!v); return !v; });
        return;
      }
      // Up mirrors Left (previous); Down mirrors Right (next), and SHIFT
      // asks for the next ITEM — unless the tag-grid session under us owns
      // that press (`sessionKeys`' `underPreview`), which is the one rule
      // `previewArrow` exists to state.
      const arrow = previewArrow(e, { sessionOwnsShift: tagGridIsOpen() });
      if (!arrow) return;
      e.preventDefault();
      stepRef.current(arrow.dir, arrow.whole);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [quickLook, ordered.length, setQuickLook]);

  /** One step of the walk — what the arrow KEYS and the ‹ › buttons both do.
   *  Two controls for one gesture have to mean the same thing, and the
   *  fall-through off a sequence's ends is exactly where they would drift.
   *
   *  `whole` is Shift: the chapter is ONE THING to step over, so the pages
   *  are skipped and the entry is left exactly as the last page's own step
   *  would leave it — the same fall-through, reached without walking there. */
  const step = (dir: number, whole = false) => {
    back.current = dir < 0;
    if (pages && !whole) {
      const next = page + dir;
      if (next >= 0 && next < pages.length) { setPage(next); return; }
      // …and off either end, the chapter is left the way any item is left.
    }
    if (!stepSelection(dir)) {
      setIdx((i) => Math.max(0, Math.min(i + dir, ordered.length - 1)));
    }
  };
  // The key handler is registered ONCE (its effect must not re-arm per
  // render), so it reads the current `step` through a ref rather than
  // closing over the first one — the `useReportSelection` rule.
  const stepRef = useRef(step);
  stepRef.current = step;

  // The item currently shown — the PAGE inside a sequence, the entry
  // everywhere else (for the optional info panel's detail fetch).
  const curId = pages ? pages[Math.min(page, pages.length - 1)] : entryId;
  const haveInGrid = curId != null && byId.has(curId);
  // Fetch the item's detail when the info panel is open, OR when the item isn't
  // in the loaded grid page (so an off-grid, sidebar-selected item still has a
  // preview source — active file, kind, rotation, name).
  // WHICH ITEM THE FRAME IS REALLY DRAWING — the only one whose detail may
  // stand in for the next (`keepsPreviousPreview`). Null while the preview
  // is closed, so an open starts from nothing rather than from whatever was
  // last looked at.
  const onScreenRef = useRef<number | null>(null);
  const { data: detail, isPlaceholderData, isFetching: detailLoading } = useQuery({
    queryKey: ["item", curId],
    queryFn: () => api.item(curId as number),
    enabled: quickLook && curId != null && (showInfo || !haveInGrid),
    // THE PICTURE ON SCREEN STAYS WHILE THE NEXT LOADS — and nothing else
    // does. Stepping through a sequence's pages, every page is a fresh
    // detail fetch, and for its length `item` was undefined — so `src` was
    // null and the "No preview" box flashed up between two pictures. The
    // picture being looked at holds until the new one is here, and the frame
    // below swaps only once it has loaded. But held across an OPEN that is
    // the LAST VISIT's picture, on screen over the card just pressed for as
    // long as the fetch takes; `keepsPreviousPreview` is where the two cases
    // are told apart.
    placeholderData: (prev, prevQuery) =>
      keepsPreviousPreview(prevQuery?.queryKey, onScreenRef.current)
        ? prev : undefined,
  });
  // Advanced only once this item is really what the frame has — the grid
  // already had it, or its own detail has landed — so the stand-in never
  // steps forward onto a picture nobody has seen. It must NOT be cleared
  // while a step is in flight: the callback above runs on every render, and
  // forgetting mid-flight would take the held picture off the screen.
  const onScreenNow = quickLook && curId != null
    && (haveInGrid || (detail !== undefined && !isPlaceholderData));
  useEffect(() => {
    if (!quickLook) { onScreenRef.current = null; return; }
    if (onScreenNow && curId != null) onScreenRef.current = curId;
  }, [quickLook, onScreenNow, curId]);
  // Track list for the shown item, used to flag a video that carries no audio.
  const curIsVideo = curId != null && (byId.get(curId) ?? detail)?.kind === "video";
  const { data: tracks } = useQuery({
    queryKey: ["tracks", curId],
    queryFn: () => api.itemTracks(curId as number),
    enabled: quickLook && curIsVideo && curId != null,
  });
  const videoMuted = curIsVideo && tracks != null && !tracks.tracks.some((t) => t.kind === "audio");
  // Reset the box overlay when the shown item changes.
  useEffect(() => { setHoverBoxes(null); }, [curId]);
  // The element the thumbnail button reads its frame off, and WHICH MOMENT was
  // last made the thumbnail — the confirmation is the only thing that says so,
  // since the picture on screen does not change. A moment rather than a flag,
  // because the claim is about the frame you are looking at: moving the
  // playhead makes it untrue, and a flag went on saying "set" over a frame
  // nobody had chosen. Cleared with the item and with the overlay, since it is
  // a fact about this visit rather than about the film.
  const videoEl = useRef<HTMLVideoElement>(null);
  const [thumbAt, setThumbAt] = useState<number | null>(null);
  useEffect(() => { setThumbAt(null); }, [curId, quickLook]);
  const thumbIsHere = thumbAt != null;

  // The item's tag instances grouped by tag group (Ungrouped first), for the
  // info panel — the panel's own rule, so the preview and the tag-batch
  // session cannot end up with two ideas of what a group is.
  const groupedTags = useMemo(() => groupTagInstances(detail), [detail]);

  // TURNING THE PICTURE FROM THE PREVIEW (`shared/useRotate`, the session
  // card's own buttons in this window's terms): a sideways photograph is not
  // one anybody can look at, and leaving the preview to fix it is leaving
  // the preview. The ITEM's picture only — a specific-file preview shows one
  // file's bytes and the rotate turns the active file; a film is the video
  // editor's, applied to a render; a sequence container has no picture of its
  // own (inside a sequence `curId` is the PAGE, which is what turns).
  // THE SLOT'S INSET — where the picture is fitted while it covers the whole
  // overlay. Measured, because it is whatever the column's layout leaves
  // between the header, the caption and the panel, and re-measured whenever
  // the slot or the overlay changes size.
  const rootRef = useRef<HTMLDivElement>(null);
  const slotRef = useRef<HTMLDivElement>(null);
  const [slotInset, setSlotInset] = useState<{ l: number; t: number; r: number; b: number }>();
  useEffect(() => {
    const root = rootRef.current, slot = slotRef.current;
    if (!root || !slot) { setSlotInset(undefined); return; }
    const measure = () => {
      const R = root.getBoundingClientRect(), r = slot.getBoundingClientRect();
      const next = { l: Math.max(0, r.left - R.left), t: Math.max(0, r.top - R.top),
                     r: Math.max(0, R.right - r.right), b: Math.max(0, R.bottom - r.bottom) };
      setSlotInset((cur) => cur && cur.l === next.l && cur.t === next.t
                            && cur.r === next.r && cur.b === next.b ? cur : next);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(root); ro.observe(slot);
    return () => ro.disconnect();
  });
  // Above the early return below: a hook may not follow one.
  const shownForRotate = (curId != null ? byId.get(curId) : undefined) ?? detail ?? undefined;
  const rotatableId = !quickLookFile && shownForRotate?.kind === "image" && curId != null
    ? curId : null;
  const { rotate, css: rotateCss } = useRotate(
    rotatableId, shownForRotate?.rotation ?? 0,
    () => {
      qc.invalidateQueries({ queryKey: ["items"] });
      if (curId != null) qc.invalidateQueries({ queryKey: ["item", curId] });
      bumpLibrary();
    });
  if (!quickLook || ordered.length === 0) return null;

  const clamped = Math.min(idx, ordered.length - 1);
  // Prefer the grid's loaded item; fall back to the fetched detail for an item
  // that isn't in the current grid view. `curId` rather than `ordered[clamped]`
  // — inside a sequence they differ, and what is SHOWN is the page.
  const item = (curId != null ? byId.get(curId) : undefined) ?? detail ?? undefined;
  // A box with geometry. Typed on the four fields it READS rather than on
  // `TagBox`: the same rectangles arrive from a tag (which also carries a time
  // range) and from a link (which does not), and the drawing cares about
  // neither difference.
  type Rect = { x?: number | null; y?: number | null;
                w?: number | null; h?: number | null };
  const spatial = (boxes: Rect[]) =>
    boxes.filter((b) => b.x != null && b.y != null && b.w != null && b.h != null);
  // Prefer the full-resolution file for a crisp image; fall back to the
  // thumbnail for videos/sequences (whose active file isn't a still image).
  const fid =
    item == null ? null
      : item.kind === "sequence" ? (item.member_thumbs[0] ?? null)
      : item.active_file_id;
  const isVideo = quickLookFile ? quickLookFile.video : item?.kind === "video";
  // Videos play back from their full file (autoplaying below); images use the
  // full-resolution file, everything else falls back to the thumbnail. A
  // specific-file preview always shows that file's own bytes.
  const videoSrc = quickLookFile
    ? (quickLookFile.video ? api.fileUrl(quickLookFile.fileId) : null)
    : isVideo && item?.active_file_id != null ? api.fileUrl(item.active_file_id) : null;
  const src = quickLookFile
    ? (quickLookFile.video ? null : api.fileUrl(quickLookFile.fileId))
    : item && item.kind === "image" && item.active_file_id != null
      ? api.fileUrl(item.active_file_id, item.rotation)
      : fid != null ? api.thumbUrl(fid, item?.rotation ?? 0) : null;
  // The item is not known yet — the detail is still on its way. Distinct
  // from "this item has no preview", which is what the box says.
  const awaitingItem = item == null && curId != null && detailLoading;
  const turnBtn = (dir: "left" | "right", icon: string, label: string) => (
    <span className="hoverable" title={label}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => { e.stopPropagation(); rotate(dir); }}
      style={{ width: 30, height: 30, borderRadius: "var(--r-4)", cursor: "pointer",
               display: "flex", alignItems: "center", justifyContent: "center",
               background: "var(--overlay-chrome)", color: "var(--on-scrim)",
               border: "1px solid var(--overlay-hairline)",
               backdropFilter: "blur(3px)" }}>
      <Icon name={icon} size={17} />
    </span>
  );
  const rotateCorner = rotatableId != null ? (
    <div style={{ display: "flex", gap: 6 }}>
      {turnBtn("left", "rotate_left", tr("Rotate left"))}
      {turnBtn("right", "rotate_right", tr("Rotate right"))}
    </div>
  ) : null;
  // The raw file behind the preview, offered as a plain link in the overlay.
  const rawFileId = quickLookFile ? quickLookFile.fileId
    : item?.active_file_id ?? null;
  // The ‹ › arrows: several items to step through, or a sequence's pages.
  // `walkAt` / `walkOf` are which of the two the buttons are counting, so
  // their ends are the ends of the thing on screen.
  const walkOf = pages ? pages.length : ordered.length;
  const walkAt = pages ? Math.min(page, pages.length - 1) : clamped;
  const multi = walkOf > 1;

  // What is drawn ON the picture, in the picture's own frame — so it travels
  // with the zoom rather than being pinned to the viewport. Built here because
  // it reads half this component's state; the preview only has to place it.
  // HOW MANY PAGES, on a sequence's preview. A sequence has no picture of its
  // own — what is shown is its first member's — so without the badge the
  // preview is indistinguishable from that member opened on its own. The grid
  // says it the same way, in the same corner, with the same glyph.
  //
  // Handed over SEPARATELY from the boxes because the two answer to the zoom
  // differently: a box marks a region and must grow with the picture, while
  // this is chrome and must not (see `ZoomablePreview`).
  const badge = item?.kind === "sequence" && item.seq_total > 0 ? (
    <Chip tone="overlay" size="lg" mono
      title={tn({ one: "1 item in this sequence",
                  other: "{n} items in this sequence" }, item.seq_total)}
      style={{ fontSize: "var(--fs-3)", height: 24, pointerEvents: "none" }}>
      <Icon name="collections_bookmark" size={15} />
      {item.seq_total}
    </Chip>
  ) : null;

  const overlays = (
    <>
      {/* Bounding boxes, as fractions of the frame: whatever tag row the
          pointer is over, else whatever the opener asked for (a crop link's
          region). Hovering WINS — it is the live question. */}
      {(hoverBoxes ?? quickLookBoxes) && spatial(hoverBoxes ?? quickLookBoxes ?? []).map((b, i) => (
        <div
          key={i}
          style={{
            position: "absolute", left: `${b.x! * 100}%`, top: `${b.y! * 100}%`,
            width: `${b.w! * 100}%`, height: `${b.h! * 100}%`,
            border: "2px solid var(--accent)", borderRadius: 2,
            boxShadow: "var(--ring-shadow)", pointerEvents: "none",
          }}
        />
      ))}
    </>
  );

  return (
    <div
      ref={rootRef}
      onMouseDown={() => setQuickLook(false)}
      style={{
        position: "fixed", inset: 0,
        // RAISED when it was opened from inside a dialog: a dialog is 500,
        // so the ordinary 200 would put the picture behind the thing that
        // asked for it.
        zIndex: raised ? LAYER.previewRaised : LAYER.preview,
        background: "var(--preview-backdrop)", backdropFilter: "blur(6px)",
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        padding: 40, gap: 14,
      }}
    >
      {/* THE PICTURE COVERS THE WHOLE OVERLAY and is FITTED to the slot the
          column below leaves for it (`slotInset`, measured): zoomed in, it
          passes under the caption, the arrows, the buttons and the panel
          rather than being cut off at an invisible frame, while at fit zoom
          it sits exactly where it always did. Everything laid over it is
          stacked above (`zIndex: 1`) and takes the pointer only where it has
          something to take it for — the column itself lets presses, wheels
          and drags fall through to the viewport underneath. */}
      {src && !videoSrc && (
        <ZoomablePreview src={src} t={tr} badge={badge} fill inset={slotInset}
          corner={rotateCorner} rotateCss={rotateCss}
          // THE RECORDED PIXEL SIZE, where the source is the item's own
          // active file: an EXIF-oriented JPEG reports its ORIENTED
          // size as `naturalWidth`, while every `img` here draws the
          // pixels as stored (`image-orientation: none`) — so a frame
          // sized from the element squeezed a landscape picture into a
          // portrait box. The library records the raw dimensions.
          size={!quickLookFile && item && item.kind === "image"
                && item.width > 0 && item.height > 0
            ? { w: item.width, h: item.height } : undefined}>
          {overlays}
        </ZoomablePreview>
      )}
      {/* Close button (top-right). */}
      <button
        onMouseDown={(e) => { e.stopPropagation(); setQuickLook(false); }}
        title="Close (Space or Esc)"
        style={{
          position: "fixed", zIndex: 1, top: 16, right: 16, width: 36, height: 36, borderRadius: "var(--r-6)",
          display: "flex", alignItems: "center", justifyContent: "center",
          border: "1px solid var(--border-strong)", ...CHROME,
          color: "var(--text-2)", cursor: "pointer",
        }}
      >
        <Icon name="close" size={20} />
      </button>

      {/* WHICH FRAME REPRESENTS THE FILM. A video's thumbnail is extracted at
          its midpoint, which is a guess and is often black, a logo or a title
          card — and this overlay is the one place you are already watching the
          film and can see a frame worth choosing.

          In the OVERLAY's top-left corner, not the picture's: over the video
          it sat on top of macOS's own playback controls, which are the first
          thing a pointer goes for there. Out here it is beside the overlay's
          other buttons, and the wording says which frame it means, since it no
          longer sits on the one it is about. */}
      {curIsVideo && curId != null && (
        <button
          onMouseDown={(e) => e.stopPropagation()}
          onClick={() => {
            const at = videoEl.current?.currentTime;
            if (at == null) return;
            setThumbAt(null);
            void api.setThumbnailFrame(curId, at).then(() => {
              setThumbAt(videoEl.current?.currentTime ?? at);
              qc.invalidateQueries({ queryKey: ["items"] });
              qc.invalidateQueries({ queryKey: ["item", curId] });
              bumpLibrary();
            });
          }}
          title={tr("Make the frame on screen this video's thumbnail")}
          style={{
            position: "fixed", left: 16, top: 16, zIndex: 1,   // above the preview column, like the arrows
            display: "flex", alignItems: "center", gap: 6, height: 36,
            padding: "0 12px", borderRadius: "var(--r-6)",
            ...CHROME, background: thumbIsHere ? "var(--accent-dim)" : "var(--preview-backdrop)",
            border: `1px solid ${thumbIsHere ? "var(--accent)" : "var(--border-strong)"}`,
            color: thumbIsHere ? "var(--accent)" : "var(--text-2)",
            fontSize: "var(--fs-3)", fontWeight: 600, fontFamily: "inherit",
            cursor: "pointer",
          }}
        >
          <Icon name={thumbIsHere ? "check" : "image"} size={17} />
          {thumbIsHere
            ? tr("This frame is the thumbnail")
            : tr("Use this frame as the thumbnail")}
        </button>
      )}

      {/* Open the raw file in a new tab (the preview never links it directly). */}
      {rawFileId != null && (
        <a
          href={api.fileUrl(rawFileId)}
          target="_blank"
          rel="noreferrer"
          onMouseDown={(e) => e.stopPropagation()}
          title="Open the raw file in a new tab"
          style={{
            position: "fixed", zIndex: 1, top: 16, right: 108, width: 36, height: 36, borderRadius: "var(--r-6)",
            display: "flex", alignItems: "center", justifyContent: "center",
            border: "1px solid var(--border-strong)", ...CHROME,
            color: "var(--text-2)", cursor: "pointer", textDecoration: "none",
          }}
        >
          <Icon name="open_in_new" size={18} />
        </a>
      )}

      {/* WHERE THIS PICTURE IS. The preview opens from lists that are not the
          grid — a ranking's buckets, its not-applicable shelf — and from
          there the item has no other address: the overlay says what it is
          and the library is where anything is DONE with it. */}
      {curId != null && (
        <button
          onMouseDown={(e) => {
            e.stopPropagation();
            const uid = (byId.get(curId) ?? detail)?.uid ?? null;
            // Over a session the picture opens in another window and this
            // one is unchanged, so the preview stays where it was.
            if (!showItemInLibrary(curId, uid)) setQuickLook(false);
          }}
          title={tr("Show in library")}
          style={{
            position: "fixed", zIndex: 1, top: 16, right: 154, width: 36, height: 36,
            borderRadius: "var(--r-6)", display: "flex", alignItems: "center",
            justifyContent: "center", border: "1px solid var(--border-strong)",
            ...CHROME, color: "var(--text-2)",
            cursor: "pointer",
          }}
        >
          <Icon name="image_search" size={18} />
        </button>
      )}

      {/* Toggle the tags/captions side panel — placed at the top-right, on the
          same side the panel opens, just left of the close button. */}
      <button
        onMouseDown={(e) => {
          e.stopPropagation();
          const v = !showInfo;
          setShowInfo(v);
          APP_PREFS.quickLookInfo.write(v);
        }}
        title={showInfo ? "Hide tags & captions" : "Show tags & captions"}
        style={{
          position: "fixed", zIndex: 1, top: 16, right: 62, width: 36, height: 36, borderRadius: "var(--r-6)",
          display: "flex", alignItems: "center", justifyContent: "center",
          border: `1px solid ${showInfo ? "var(--accent)" : "var(--border-strong)"}`,
          ...CHROME, background: showInfo ? "var(--accent-dim)" : "var(--preview-backdrop)",
          color: showInfo ? "var(--accent)" : "var(--text-2)", cursor: "pointer",
        }}
      >
        <Icon name="toc" size={20} />
      </button>

      {/* Previous / next arrows for a multi-item selection. */}
      {multi && (
        <>
          {/* Both go through `step`, which is what the arrow KEYS do: two
              controls for one gesture have to mean the same thing, and off a
              sequence's ends — where the walk leaves the chapter for the item
              beside it — is exactly where they would drift. Dimmed at an end
              only when there is nothing to step ON to. */}
          <button
            onMouseDown={(e) => { e.stopPropagation(); step(-1, e.shiftKey); }}
            disabled={walkAt <= 0 && !pages && clamped <= 0}
            title={pages ? "Previous (←, ⇧← leaves the sequence)"
                         : "Previous (←)"}
            style={{ ...arrowBtn, left: 16,
                     opacity: walkAt <= 0 && !pages ? 0.35 : 1 }}
          >
            <Icon name="chevron_left" size={26} />
          </button>
          <button
            onMouseDown={(e) => { e.stopPropagation(); step(1, e.shiftKey); }}
            disabled={walkAt >= walkOf - 1 && !pages}
            title={pages ? "Next (→, ⇧→ leaves the sequence)" : "Next (→)"}
            // CLEAR OF THE PANEL: with the info panel open the window's
            // right edge is the panel's, so the arrow sits just outside the
            // measured slot instead — `slotInset.r` is the panel, the row's
            // gap and the padding together; with nothing there it is the
            // padding alone and the arrow stays where it always was.
            style={{ ...arrowBtn,
                     right: showInfo && slotInset ? slotInset.r - 6 : 16,
                     opacity: walkAt >= walkOf - 1 && !pages ? 0.35 : 1 }}
          >
            <Icon name="chevron_right" size={26} />
          </button>
        </>
      )}

      {/* Preview column + (optional) info panel, side by side — ABOVE the
          picture, and transparent to the pointer except where a child says
          otherwise (the caption, the footer, the panel). */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 18, width: "100%", flex: 1, minHeight: 0,
                    position: "relative", zIndex: 1, pointerEvents: "none" }}>
        {/* HEIGHT 100%, not content-sized. The preview inside is `flex: 1` and
            fits the picture to what it is GIVEN, so a column sized by its own
            content would be asking the picture how big the box it is being
            fitted into should be. */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, flex: 1, minWidth: 0, height: "100%" }}>
          {/* The preview itself (checkerboard shows through transparency).

              A STILL PICTURE ZOOMS; the video does not. Zooming is for
              looking closely at what is IN the picture — a face, a signature,
              a piece of text somebody is about to tag — and a film already
              owns the pointer through its own transport, where a drag means
              scrub and a wheel means volume. */}
          {videoSrc ? (
            <div
              className="mc-checker"
              onMouseDown={(e) => e.stopPropagation()}
              style={{
                position: "relative", maxWidth: "100%", maxHeight: "calc(100vh - 150px)", borderRadius: "var(--r-7)",
                pointerEvents: "auto",
                overflow: "hidden", border: "1px solid var(--border-strong)",
                boxShadow: "var(--shadow-3)", display: "flex",
              }}
            >
              <video
                key={videoSrc}
                ref={videoEl}
                src={videoSrc}
                autoPlay
                controls
                loop
                playsInline
                // START AT THE MOMENT THE LINK NAMES. On `loadedmetadata`,
                // because before it there is no duration to seek within — the
                // same rule the annotator's playback memory follows. Paused
                // there rather than playing on: the question the button asked
                // is "which frame is this", and a film that runs off answers it
                // for a quarter of a second.
                onLoadedMetadata={(e) => {
                  if (quickLookAt == null) return;
                  e.currentTarget.currentTime = quickLookAt;
                  e.currentTarget.pause();
                }}
                // The confirmation is about the frame ON SCREEN, so moving off
                // it takes the confirmation with it. Within a twentieth of a
                // second, because the element reports its own rounded position
                // and an exact test would answer "moved" the instant the seek
                // settled. Only ever clears — one render, and none at all in
                // the ordinary case where nothing has been set.
                onTimeUpdate={(e) => {
                  if (thumbAt != null
                      && Math.abs(e.currentTarget.currentTime - thumbAt) >= 0.05) {
                    setThumbAt(null);
                  }
                }}
                style={{ display: "block", maxWidth: "100%", maxHeight: "calc(100vh - 150px)", objectFit: "contain" }}
              />
            </div>
          ) : src ? (
            // The SLOT the picture is fitted to: what the ZoomablePreview
            // above the column measures itself against. Empty on purpose.
            <div ref={slotRef} style={{ flex: 1, minHeight: 0, width: "100%",
                                        alignSelf: "stretch" }} />
          ) : awaitingItem ? (
            // NOTHING IS KNOWN YET, so nothing is said. A fresh open no
            // longer stands the last visit's picture in while the detail
            // loads (`keepsPreviousPreview`), and the box below is an
            // ANSWER — "there is nothing to show here" — which would flash
            // up as one in the moment before the item has arrived.
            <div style={{ flex: 1, minHeight: 0, width: "100%",
                          alignSelf: "stretch" }} />
          ) : (
            <div
              className="mc-checker"
              onMouseDown={(e) => e.stopPropagation()}
              style={{
                position: "relative", borderRadius: "var(--r-7)", overflow: "hidden",
                border: "1px solid var(--border-strong)", pointerEvents: "auto",
                boxShadow: "var(--shadow-3)", display: "flex",
              }}
            >
              <div style={{ width: 320, height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", background: "var(--panel-3)" }}>
                No preview
              </div>
            </div>
          )}

          {/* Caption: name + (position within the selection). Sits directly on
              the backdrop, so it takes the backdrop's OWN text tokens — a
              dark theme dims with black and reads light, the light theme dims
              with white and reads dark (`--preview-*` in tokens.css). */}
          {/* ON A PILL of the backdrop's own colour, blurred behind: the
              picture can be anywhere under the caption now, so the name
              stands on its own ground. Hard-edged (owner decision — a glow
              feathering the edge was tried and taken off). */}
          <div
            onMouseDown={(e) => e.stopPropagation()}
            style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, color: "var(--preview-text)", fontSize: "var(--fs-4)", maxWidth: "100%",
                     pointerEvents: "auto", padding: "7px 18px", borderRadius: 14,
                     ...CHROME }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, maxWidth: "100%" }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {item?.name ?? "…"}
              </span>
              {videoMuted && (
                <span title="No audio" style={{ display: "flex", flex: "0 0 auto" }}>
                  <Icon name="volume_off" size={16} color="var(--preview-text-2)" />
                </span>
              )}
              {multi && (
                <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-3)", color: "var(--preview-text-2)", flex: "0 0 auto" }}>
                  {walkAt + 1} / {walkOf}
                </span>
              )}
            </div>
            {/* The grid card's second line, repeated here: what the picture
                MEASURES, under what it is called. */}
            {item && item.kind !== "sequence" && item.width > 0 && (
              <div style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--preview-text-3)" }}>
                {item.width}×{item.height}
                <span style={{ margin: "0 6px", color: "var(--preview-text-4)" }}>·</span>
                {mpLabel(item.width, item.height, lang)}
              </div>
            )}
          </div>
          {/* WHAT A SESSION LENDS THE PREVIEW: the tag grid's answer
              capsule for the card on screen, under the picture rather
              than on it. */}
          {previewFooter && (
            <div onMouseDown={(e) => e.stopPropagation()}
              style={{ display: "flex", justifyContent: "center", pointerEvents: "auto" }}>
              {previewFooter}
            </div>
          )}
        </div>

        {/* Tags (by group) + captions panel — shared with the tag-batch
            session, which opens the same panel on the same key. */}
        {showInfo && (
          <div style={{ display: "contents", pointerEvents: "auto" }}>
            {/* A `contents` wrapper has no box of its own, but pointer-events
                INHERITS, so this is what gives the panel the pointer back
                inside the row that lets everything else fall through. */}
            <ItemInfoPanel detail={detail} groupedTags={groupedTags}
              onHoverBoxes={setHoverBoxes} style={CHROME}
              onChanged={() => {
                if (curId != null) {
                  qc.invalidateQueries({ queryKey: ["item", curId] });
                  qc.invalidateQueries({ queryKey: ["faces", curId] });
                }
                qc.invalidateQueries({ queryKey: ["items"] });
                bumpLibrary();
              }} />
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * The still preview, zoomable.
 *
 * `useZoomPan` is the same model the three editor windows use, so a wheel, the
 * +/- pair and the fit ↔ actual-size toggle mean here exactly what they mean
 * there — including "100%" being one picture pixel per DEVICE pixel rather
 * than per CSS pixel.
 *
 * The intrinsic size comes from the ELEMENT (`naturalWidth`), not from the
 * item: the preview is sometimes a thumbnail (a sequence's first member) and
 * sometimes one named source file rather than the active one, and neither
 * carries the item's own dimensions. Until it has loaded there is nothing to
 * fit, so the frame is hidden rather than drawn at a guessed size — an
 * `<img>` still loads while invisible, which is what makes that free.
 *
 * Its own component so the hooks are safe: everything the parent knows about
 * which item is shown is computed after its early return.
 */
export function ZoomablePreview(
  { src, t, children, badge, corner, rotateCss = 0, size, controlsStyle,
    onViewportDown, fill = false, inset }: {
    src: string; t: (s: string) => string;
    /** Cover the whole positioned parent instead of taking a flex slot — the
     *  picture then zooms and pans over the entire overlay, nothing clipping
     *  it short of the window. QuickLook's. */
    fill?: boolean;
    /** What the picture is FITTED to, as a margin inside the viewport: with
     *  `fill` the viewport is the overlay and this is the old frame — the
     *  header, the caption and the panel stay clear at fit zoom (`useZoomPan`'s
     *  own `inset`, the editors' safe area). */
    inset?: { l?: number; t?: number; r?: number; b?: number };
    /** Drawn in the picture's TOP-RIGHT corner at a constant size, and only
     *  while the pointer is over the picture: the rotate buttons. */
    corner?: React.ReactNode;
    /** Degrees the picture should show turned beyond what its bytes are —
     *  `useRotate`'s optimistic gap, collapsing to 0 once the server has
     *  baked the turn and a re-fitted file has loaded. */
    rotateCss?: number;
    /** Drawn in the PICTURE's frame, so it travels with the zoom: boxes. */
    children?: React.ReactNode;
    /** Drawn in its corner at a constant size, whatever the zoom: chrome. */
    badge?: React.ReactNode;
    /** The picture's pixel size as RECORDED, when the caller knows it —
     *  it beats the element's own answer, which for an EXIF-oriented file
     *  is the turned size while the pixels are drawn as stored. */
    size?: { w: number; h: number };
    /** Where the zoom cluster sits. QuickLook's own is `fixed` in the
     *  WINDOW's corner, which is right for a full-window overlay and wrong
     *  for a preview that occupies one pane — the caption preview passes an
     *  absolute one so the cluster stays inside the grid. */
    controlsStyle?: React.CSSProperties;
    /** A press on the viewport itself (the margin around the picture).
     *  QuickLook lets it bubble, so the backdrop dismisses; a caller with no
     *  backdrop passes its own. */
    onViewportDown?: () => void;
  }
) {
  // DOUBLE-BUFFERED: the picture ON SCREEN is `shown`, and a new `src` is
  // loaded off screen first (an `Image()` the browser then has cached), the
  // swap happening in its `onload`. The frame used to hide itself the moment
  // `src` changed and show again when the new picture had loaded, which on
  // a quick walk through a sequence was the whole preview blinking off and
  // on between every two pages.
  const [shown, setShown] = useState<{ src: string; w: number; h: number } | null>(null);
  useEffect(() => {
    if (shown && shown.src === src) return;
    const im = new Image();
    let alive = true;
    im.onload = () => { if (alive) setShown({ src, w: im.naturalWidth, h: im.naturalHeight }); };
    im.src = src;
    return () => { alive = false; };
  }, [src]);  // eslint-disable-line react-hooks/exhaustive-deps
  // The recorded size belongs to the CURRENT item; while the previous
  // picture is still the one shown, its own measured size is the truth.
  const nat = shown ? (shown.src === src && size ? size : { w: shown.w, h: shown.h }) : null;
  const zp = useZoomPan(nat?.w ?? 0, nat?.h ?? 0, {
    fitKey: `${shown?.src ?? ""}:${nat?.w ?? 0}x${nat?.h ?? 0}`,
    inset,
  });
  const zoomed = Math.abs(zp.zoom - 1) > 0.001;
  const [hover, setHover] = useState(false);
  // A quarter turn shown in CSS inside a frame still sized for the old
  // orientation: scaled down by the aspect so the turned picture stays
  // inside it (letterboxed) for the moment before the baked file arrives.
  const quarter = ((rotateCss % 180) + 180) % 180 !== 0;
  const turnScale = quarter && nat ? Math.min(nat.w / nat.h, nat.h / nat.w) : 1;

  // Panning is the picture's own gesture, so it hangs off the FRAME and not
  // the viewport: the dark area around it is the backdrop, and a press there
  // still closes the overlay (which is why the frame stops its own mousedown
  // and the viewport does not).
  const startPan = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (e.button !== 0) return;
    const from = { x: e.clientX, y: e.clientY };
    const pan0 = zp.pan;
    // CLAMPED, unlike the editors' own pan: `panLimit` is "the picture never
    // leaves a gap it does not have to", which is the whole of what this
    // window shows — there is no panel here to drag it aside for, and a
    // preview dragged off its own viewport is a preview of nothing.
    const lim = { x: panLimit(zp.safe.w, zp.frameW), y: panLimit(zp.safe.h, zp.frameH) };
    const clamp = (v: number, l: number) => Math.max(-l, Math.min(l, v));
    const move = (ev: MouseEvent) => {
      zp.setPan({ x: clamp(pan0.x + (ev.clientX - from.x), lim.x),
                  y: clamp(pan0.y + (ev.clientY - from.y), lim.y) });
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  // Every wheel over the viewport is the picture's, ctrl held or not — see
  // `useWheel`, which is what lets the browser's own page zoom be refused.
  useWheel(zp.viewportRef, (e) => {
    e.preventDefault();
    const r = zp.viewportRef.current?.getBoundingClientRect();
    zp.zoomAt(r ? e.clientX - r.left : zp.vp.w / 2,
              r ? e.clientY - r.top : zp.vp.h / 2,
              e.deltaY < 0 ? 1.1 : 0.9);
  });

  return (
    <div
      ref={zp.viewportRef}
      // A press on the viewport ITSELF is a press on the backdrop and closes
      // the overlay, exactly as the dark margin around it does. A press on
      // anything IN it — the picture, the zoom cluster — is not: the cluster
      // is a child of this box rather than of the frame, so without this rule
      // its first click dismissed the preview it was zooming.
      onMouseDown={(e) => {
        if (e.target !== e.currentTarget) { e.stopPropagation(); return; }
        onViewportDown?.();
      }}
      style={{
        ...(fill
          ? { position: "absolute", inset: 0 }
          : { position: "relative", flex: 1, minHeight: 0, width: "100%" }),
        display: "flex", alignItems: "center", justifyContent: "center",
        // CLIPPED ONLY WHILE ZOOMED. Fitted, the picture touches the
        // viewport's edge in one dimension, so a clip there cut its shadow
        // off flat along that side — invisible on the dark backdrop, plain
        // on the light one. Fitted, nothing overflows and the shadow is
        // free; zoomed in, the picture fills the viewport and the clip is
        // what keeps it off the caption and the buttons.
        overflow: zoomed ? "hidden" : "visible",
      }}
    >
      <div
        className="mc-checker"
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        onMouseDown={startPan}
        onDoubleClick={(e) => {
          e.stopPropagation();
          zp.atActualSize ? zp.fitToScreen() : zp.actualSize();
        }}
        style={{
          position: "relative",
          // NO SHRINKING. The frame is a flex item in a centring viewport, so
          // its default `flex-shrink: 1` squeezed a zoomed-in picture back to
          // the viewport's width — the height grew, the width did not, and the
          // picture was quietly distorted.
          width: zp.frameW, height: zp.frameH, flex: "0 0 auto",
          transform: `translate(${zp.pan.x + zp.origin.x}px, ${zp.pan.y + zp.origin.y}px)`,
          borderRadius: "var(--r-7)", overflow: "hidden",
          border: "1px solid var(--border-strong)",
          boxShadow: "var(--shadow-3)",
          visibility: nat ? "visible" : "hidden",
          cursor: zoomed ? "grab" : "default",
        }}
      >
        <img
          src={shown?.src ?? src}
          alt=""
          draggable={false}
          style={{ display: "block", width: "100%", height: "100%",
                   transform: rotateCss
                     ? `rotate(${rotateCss}deg) scale(${turnScale})` : undefined,
                   transition: "transform 0.12s ease" }}
        />
        {children}
        {/* ON HOVER, top-right: chrome about the ITEM, in the picture's own
            corner so it travels with the pan — at a constant size, for the
            badge's reason above. */}
        {corner && hover && (
          <div onMouseDown={(e) => e.stopPropagation()}
            style={{ position: "absolute", top: 10, right: 10, cursor: "default" }}>
            {corner}
          </div>
        )}
        {/* In the picture's own corner — where it belongs, and where it stays
            as the picture is panned — at a CONSTANT size: the frame is SIZED
            to the zoom (`width: zp.frameW`), never transformed, so its
            children do not scale with it and need no counter-scale. One was
            here (`scale(1/zoom)`), on the belief that they did, and it was
            what made this badge and the rotate buttons shrink as the picture
            grew and swell as it shrank. */}
        {badge && (
          <div style={{ position: "absolute", bottom: 10, right: 10 }}>
            {badge}
          </div>
        )}
      </div>
      {/* In the OVERLAY's corner, not the picture area's: the close and
          panel buttons live top-right of the overlay, and the zoom cluster
          is the same kind of thing at the other end of the same edge. */}
      {/* `zIndex: 1` like the arrows and the header buttons: the caption's
          strip is a later sibling of this viewport and painted over the
          cluster otherwise — which is what hid it. */}
      {nat && <ZoomControls zp={zp} t={t}
                style={controlsStyle
                  ?? { position: "fixed", right: 16, bottom: 16, zIndex: 1,
                       border: "1px solid var(--border-strong)", ...CHROME }} />}
    </div>
  );
}

/** THE OVERLAY'S ONE GROUND for everything laid over the picture — the
 *  caption pill, the header buttons, the arrows, the zoom cluster, the info
 *  panel: the backdrop's own colour with the picture blurred behind it, so
 *  every piece of chrome reads the same way wherever the zoomed picture has
 *  ended up under it (owner request, 2026-09). */
const CHROME: React.CSSProperties = {
  background: "var(--preview-backdrop)",
  backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)",
};

const arrowBtn: React.CSSProperties = {
  // ABOVE the preview column. The arrows come before it in the DOM and both
  // are positioned, so the column — `flex: 1`, spanning the window's width —
  // painted over the inner half of each arrow: a click there landed on the
  // zoom viewport and did nothing, which read as a button that only worked
  // on its outer half.
  position: "fixed", zIndex: 1, top: "50%", transform: "translateY(-50%)",
  width: 44, height: 44, borderRadius: "50%",
  display: "flex", alignItems: "center", justifyContent: "center",
  border: "1px solid var(--border-strong)", ...CHROME,
  color: "var(--text-2)", cursor: "pointer",
};
