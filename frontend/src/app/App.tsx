import React, { useEffect, useRef, useState } from "react";
import { SplitHandle, useSplit } from "../shared/Split";
import { APP_PREFS } from "./prefs";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { TopBar } from "./components/TopBar";
import { TrainingPages, useTrainingOffered } from "./training";
import { GroupTree } from "./components/GroupTree";
import { ItemGrid } from "./components/ItemGrid";
import { PropertiesPanel } from "./components/PropertiesPanel";
import { TagsView } from "./components/TagsView";
import { FacesPage } from "./components/FacesView";
import { HistoryView } from "./components/HistoryView";
import { ErrorBoundary } from "../shared/ErrorBoundary";
import { ConfirmHost } from "../shared/ConfirmModal";
import { ImportOverlay } from "./components/ImportOverlay";
import { GroupPropertiesOverlay } from "./components/GroupPropertiesOverlay";
import { SettingsOverlay } from "./components/SettingsOverlay";
import { QuickLook } from "./components/QuickLook";
import { QuickTagOverlay } from "./components/QuickTagOverlay";
import { QuickCaptionOverlay } from "./components/QuickCaptionOverlay";
import { QuickAssignOverlay } from "./components/QuickAssignOverlay";
import { RateOverlay } from "./components/RateOverlay";
import { TagSortOverlay } from "./components/TagSortOverlay";
import { EstimateOverlay } from "./components/EstimateOverlay";
import { TagGridOverlay } from "./components/TagGridOverlay";
import { ItemWindow } from "./components/ItemWindow";
import { tagsModeDefaults, useUI } from "./store";
import { catFromScope, placeUrl, readPlace, samePlace, scopeFromPlace } from "./location";
import { isRefPickerOpen } from "./dragState";
import { internalDragActive } from "../shared/dragBody";
import { useLang , useT } from "./i18n";

const SIDEBAR_MIN = 198;
const SIDEBAR_MAX = 520;

// The same floor the annotator's sidebar has (`ANNOTATOR_SIDEBAR_MIN`): it is
// the same panel, with the same rows in it, so a width one window allows and
// the other refuses is one component with two ideas of what it needs.
const RIGHT_MIN = 260;
const RIGHT_MAX = 560;

const clamp = (min: number, max: number, v: number) =>
  Math.min(max, Math.max(min, v));

const TRAINING_VIEWS = ["train", "evaluate", "models"];

export function App() {
  const t = useT();
  const view = useUI((s) => s.view);
  // A deployment that does not train has no Train / Evaluate / Models tabs —
  // but a bookmark, a reload or a link can still name one. Send it to the
  // library rather than rendering a page whose every request is refused.
  const trainingOffered = useTrainingOffered();
  const setView = useUI((s) => s.setView);
  useEffect(() => {
    if (!trainingOffered && TRAINING_VIEWS.includes(view)) setView("library");
  }, [trainingOffered, view, setView]);
  // AND THE FACES TAB CAN BE PUT AWAY (Settings → Faces), which is the same
  // errand with one difference: training is a launch-time fact, so its answer
  // cannot change under an open page, and this one can. Somebody who hides
  // the tab WHILE STANDING ON IT has to be moved, not just left on a page
  // whose tab has gone — so the effect answers to the value CHANGING rather
  // than only to the mount. `?? false` errs toward showing while the query is
  // in flight, the same direction `useTrainingOffered` defaults.
  const { data: uiPrefs } = useQuery({
    queryKey: ["settings"], queryFn: api.getSettings });
  const facesHidden = uiPrefs?.hide_faces_tab ?? false;
  useEffect(() => {
    if (facesHidden && view === "faces") setView("library");
  }, [facesHidden, view, setView]);
  const overlay = useUI((s) => s.overlay);
  // Reflect the chosen UI language on <html lang> for the whole document.
  const lang = useLang();
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);

  // Keep the address bar on the place you are looking at, and follow it back.
  // Each move is a history entry, so Back leaves a tab or closes an overlay
  // the way it closes a page — and a reload returns to the same place.
  // One primitive selector each: an object selector would be a new object on
  // every render, which is an infinite render loop with zustand's snapshot
  // check — the sort of bug that shows up as a blank page.
  const settingsPage = useUI((s) => s.settingsPage);
  const groupEditId = useUI((s) => s.groupEditId);
  const trainJobUid = useUI((s) => s.trainJobUid);
  const tagSetId = useUI((s) => s.tagSetId);
  // Library category + media filter + search, reflected in the URL (primitive
  // selectors only — an object selector re-renders every time and loops).
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
  const search = useUI((s) => s.search);
  const libCat = catFromScope({ selectedGroups, ungrouped, untagged, trashView, hiddenView, pendingView, pendingKind, sequenceView, rankingView, rankingPool, rankingDismissed, rankedView });
  // The Tags sub-tab is a page of its own (`/tags/subjects`), so it belongs in
  // the address like the view itself.
  const tagsMode = useUI((s) => s.tagsView.mode);
  // The item window is an overlay over all of this, so it is in the address
  // the same way — a parameter, and the view underneath keeps its own.
  const itemTabs = useUI((s) => s.editorTabs);
  const itemActive = useUI((s) => s.editorItemId);
  const itemModes = useUI((s) => s.editorModes);
  const itemDefaultMode = useUI((s) => s.editorMode);
  const shownItem = itemActive ?? itemTabs[0] ?? null;
  const url = placeUrl({
    // WRITING an address never names a legacy sub-tab: the three record
    // lists are the Items list narrowed, and `/tags` plus the filter is what
    // this build produces. `tagsKind` exists only to be READ.
    view, overlay, settingsPage, groupEditId, trainJobUid, tagsMode,
    tagsKind: "", tagSetId,
    libCat, libKinds: mediaKinds.join(","), search,
    itemIds: itemTabs, itemTab: itemActive,
    itemMode: (shownItem != null ? itemModes[shownItem] : undefined)
      ?? itemDefaultMode,
  });
  // Seeded with the address as it actually IS, not with the place's canonical
  // URL: the bare root (or a legacy query form) then differs from `url` on the
  // first run and is quietly replaced by the proper path.
  const shown = useRef(window.location.pathname + window.location.search);
  // Everything except the free-text search is a "navigation" that gets its own
  // history entry; the search box updates per keystroke, so a search-only change
  // REPLACES the current entry (the URL still updates for reload, without a
  // hundred history entries as you type).
  const structural = `${view}|${overlay}|${settingsPage}|${groupEditId}|${trainJobUid}|${tagsMode}|${tagSetId}|${libCat}|${mediaKinds.join(",")}|${itemTabs.join(",")}`;
  const prevStructural = useRef(structural);
  useEffect(() => {
    if (url === shown.current) return;
    const navigated = structural !== prevStructural.current;
    prevStructural.current = structural;
    shown.current = url;
    // The item window is an overlay, so its address is handled here too: the
    // OPEN tabs are part of `structural` (opening or closing the window is a
    // navigation), while the ACTIVE tab (`?tab=`) is not — switching tabs
    // updates the address without stacking a history entry per page turn.
    if (navigated) window.history.pushState(null, "", url);
    else window.history.replaceState(null, "", url);
  }, [url, structural]);
  useEffect(() => {
    const onPop = () => {
      const p = readPlace();
      shown.current = placeUrl(p);
      const st = useUI.getState();
      const at = st.editorItemId ?? st.editorTabs[0] ?? null;
      if (samePlace(p, {
        view: st.view, overlay: st.overlay, settingsPage: st.settingsPage,
        groupEditId: st.groupEditId, trainJobUid: st.trainJobUid,
        tagsMode: st.tagsView.mode, tagsKind: "", tagSetId: st.tagSetId,
        libCat: catFromScope(st), libKinds: st.mediaKinds.join(","), search: st.search,
        itemIds: st.editorTabs, itemTab: st.editorItemId,
        itemMode: (at != null ? st.editorModes[at] : undefined)
          ?? st.editorMode,
      })) return;
      useUI.setState({
        view: p.view, overlay: p.overlay, settingsPage: p.settingsPage,
        groupEditId: p.groupEditId, trainJobUid: p.trainJobUid,
        tagSetId: p.tagSetId,
        // Back closes the item window, or opens it again on the way forward.
        editorTabs: p.itemIds,
        editorItemId: p.itemTab ?? p.itemIds[0] ?? null,
        editorMode: p.itemMode,
        editorModes: Object.fromEntries(p.itemIds.map((id) => [id, p.itemMode])),
        // Back onto another sub-tab is a real navigation, and its filters are
        // that sub-tab's — so it takes the same reset a hand switch does.
        tagsView: p.tagsMode === st.tagsView.mode
          ? st.tagsView : tagsModeDefaults(p.tagsMode),
        ...scopeFromPlace(p), search: p.search,
      });
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // The two dividers: the sidebar grows with the pointer, the panel against it.
  const left = useSplit({ pref: APP_PREFS.sidebarWidth, min: SIDEBAR_MIN, max: SIDEBAR_MAX,
                          axis: "x", from: "start" });
  const right = useSplit({ pref: APP_PREFS.rightWidth, min: RIGHT_MIN, max: RIGHT_MAX,
                           axis: "x", from: "end" });
  const sidebarW = left.size, rightW = right.size;

  // When files are dragged anywhere over the window, pop the import overlay so
  // the user can drop them onto its drop zone. Internal drags (moving groups or
  // images) carry text/JSON payloads, not "Files", so they're ignored here. We
  // also swallow window-level drops to stop the browser from navigating to a
  // file when it's dropped outside the drop zone.
  useEffect(() => {
    // True while the import overlay is open *because of the current file drag*
    // (not opened via the import button). When such a drag leaves the window or
    // is cancelled without dropping, the overlay closes again — and dragging
    // back in simply reopens it via the dragover handler below.
    let openedByDrag = false;
    // No `Array.from`: this runs for EVERY dragover, and WebKit fires those
    // about 1400 times a second — an array allocated per event is rubbish to
    // collect in the middle of a gesture.
    const hasFiles = (e: DragEvent) => {
      const types = e.dataTransfer?.types;
      if (!types) return false;
      for (let i = 0; i < types.length; i++) if (types[i] === "Files") return true;
      return false;
    };
    const onDragOver = (e: DragEvent) => {
      // A drag the PAGE started carries items, a group or a tag — never files.
      // Asking a boolean first is what keeps thousands of events off the rest
      // of this handler.
      if (internalDragActive()) return;
      if (!hasFiles(e)) return;
      e.preventDefault();
      // The color-reference picker takes file drops itself — don't cover it
      // with the import overlay while it's open.
      if (isRefPickerOpen()) return;
      const { view, overlay } = useUI.getState();
      // Importing puts files in the library, so only offer it from the
      // library — dragging onto Train or Tags means something else, or
      // nothing. And never displace an overlay that is already open: it
      // would take over the window mid-task.
      if (view !== "library" || overlay !== null) return;
      useUI.getState().setOverlay("import");
      openedByDrag = true;
    };
    const onDragLeave = (e: DragEvent) => {
      // Only a *window exit* counts (relatedTarget is null / outside the
      // document); dragleave also fires when moving between child elements.
      const rt = e.relatedTarget as Node | null;
      if (rt != null && document.documentElement.contains(rt)) return;
      if (openedByDrag && useUI.getState().overlay === "import") {
        useUI.getState().setOverlay(null);
      }
      openedByDrag = false;
    };
    const onDrop = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
      // A drop happened — the overlay now shows the added files; keep it open.
      openedByDrag = false;
    };
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, []);


  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
      <TopBar />
      {/* The one confirm sheet `ask()` draws; see shared/confirm.ts. */}
      <ConfirmHost />
      {view === "library" ? (
        <ErrorBoundary key={view} what={t("The Library tab")} t={t}>
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: `${sidebarW}px 1fr ${rightW}px`, gridTemplateRows: "minmax(0, 1fr)", minHeight: 0, position: "relative" }}>
          <GroupTree />
          <ItemGrid />
          <PropertiesPanel />
          {/* Drag handle straddling the sidebar's right border. */}
          <SplitHandle split={left} title="Drag to resize sidebar" style={{ left: sidebarW - 3 }} />
          {/* Drag handle straddling the right panel's left border. */}
          <SplitHandle split={right} title="Drag to resize panel" style={{ right: rightW - 3 }} />
        </div>
        </ErrorBoundary>
      ) : view === "tags" ? (
        <ErrorBoundary key={view} what={t("The Tags tab")} t={t}><TagsView /></ErrorBoundary>
      ) : view === "faces" ? (
        <ErrorBoundary key={view} what={t("The Faces tab")} t={t}><FacesPage /></ErrorBoundary>
      ) : TRAINING_VIEWS.includes(view) ? (
        // One lazy door for all three (see app/training.tsx): the train UI
        // is its own chunk, fetched the first time one of these opens.
        // Their own boundary too — and keyed by the view, like every tab's,
        // so leaving a broken tab and coming back tries it afresh.
        <ErrorBoundary key={view} what={t("The training tabs")} t={t}>
          <TrainingPages view={view} />
        </ErrorBoundary>
      ) : view === "history" ? (
        <ErrorBoundary key={view} what={t("The History tab")} t={t}><HistoryView /></ErrorBoundary>
      ) : null}
      {/* EVERY VIEW IS NAMED ABOVE, POSITIVELY. History used to be the bare
          `else`, so a view with no branch of its own rendered the History
          page under somebody else's address, with the error boundary
          labelled for the wrong tab — a view added and half-wired looked
          like a working app showing the wrong thing. A missing branch is a
          blank page now, which is the loud failure. */}
      {overlay === "import" && <ImportOverlay />}
      {overlay === "group" && <GroupPropertiesOverlay />}
      {overlay === "settings" && <SettingsOverlay />}
      {/* The preview is the LIBRARY's (Space previews the grid selection) and
          the TAGS tab's: a ranking's histogram is a wall of 54 px thumbnails,
          and "is this really a 9?" is a question only the picture answers.
          Its Space guard is view-aware, so the key still belongs to the grid
          alone — here it opens on a click and nothing else. */}
      {(view === "library" || view === "tags") && <QuickLook />}
      {/* Tag the selection from the keyboard (T). Mounted beside Quick
          Look, and for the same reason: it has to be listening before
          the key that opens it is pressed. */}
      {view === "library" && <QuickTagOverlay />}
      {view === "library" && <QuickCaptionOverlay />}
      {/* Stamp a saved tag set from the keyboard (Q, then a digit) — the
          same rule: listening before its key is pressed. */}
      {view === "library" && <QuickAssignOverlay />}
      {/* The two SESSION overlays — rate pairs, and tag one image at a time.
          Both open from the grid's quick-actions menu (no letter of their
          own) and are mounted unconditionally so a close toast can outlive
          the view they were opened over. */}
      <RateOverlay />
      <TagSortOverlay />
      {/* The third session: a batch pre-sorted into three bands. Mounted
          like the other two — and INLINE rather than portalled, so it is a
          sibling of Quick Look above and stacks under it by `LAYER`. */}
      <TagGridOverlay />
      {/* Not a session — an ordinary dialog that makes one bulk write —
          but it opens from the same menu and is mounted with them. */}
      <EstimateOverlay />
      {/* THE ITEM WINDOW, over everything. It was a browser window of its own,
          which meant a second React app: its own query cache (so every write
          had to be broadcast back), its own store (so the grid order and the
          tag to focus were handed over through localStorage), and a walk up
          the opener chain to find this window again. As an overlay it simply
          reads the store the library reads.

          Its own boundary, like the tabs: it holds exactly the unsaved state —
          an editor buffer, half-drawn boxes — where a blank screen hurts most. */}
      {itemTabs.length > 0 && (
        <ErrorBoundary what={t("The item window")} t={t}>
          <ItemWindow />
        </ErrorBoundary>
      )}
    </div>
  );
}
