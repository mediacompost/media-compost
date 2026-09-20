import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { DescriptionMark } from "./DescribedFields";
import { Collapse } from "../../shared/Collapse";
import { dropHalf, insertionIndex, useDragEndReset } from "../../shared/useDragRow";
import { SplitHandle, useSplit } from "../../shared/Split";
import { APP_PREFS } from "../prefs";
import { storage } from "../../shared/storage";
import { RECORD_ICON } from "../../shared/metaEnums";
import { rowBackground } from "../../shared/Row";
import { Chip } from "../../shared/Chip";
import { SectionHeading } from "../../shared/SectionHeading";
import { SECTION_LABEL } from "../../shared/SectionHeading";
import { IconButton, iconButtonStyle } from "../../shared/IconButton";
import { Button } from "../../shared/Button";
import { Count, CountBadge } from "../../shared/CountBadge";
import { EmptyState } from "../../shared/EmptyState";
import { Switch } from "../../shared/Switch";
import { GhostButton, Overlay, PrimaryButton } from "../../shared/Overlay";
import { useInlineEdit } from "../../shared/useInlineEdit";
import { isTypingTarget } from "../../shared/typingTarget";
import { confirm } from "../../shared/ConfirmModal";
import { bracketSlug, splitBracketed } from "../tagslug";
import { createPortal } from "react-dom";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  Caption,
  CaptionKind,
  FileNameEntry,
  FileVersion,
  fmtDuration,
  EventRow,
  FaceRow,
  GroupNode,
  ItemDetail,
  ItemSlim,
  MetadataField,
  JobKind,
  JobOut,
  ItemSearchBody,
  LinkTagRow,
  ModelInfo,
  PlaceRow,
  RelationshipOut,
  SequenceInfo,
  SubjectOnItem,
  TagAssignment,
  TagBox,
  TagInstance,
  RankingItemsBody,
} from "../api";
import { decodeMeta } from "../../shared/metaEnums";
import { Icon } from "../../shared/Icon";
import { AutoTextarea, FindableCaption } from "./CaptionEditor";
import { splitMainStyle } from "../../shared/ModelDownloadButton";
import { compactCount, formatBytes } from "../format";
import { artifactKind } from "../artifactKinds";
import { SKIP_DONE_ALWAYS, SKIP_DONE_KINDS } from "../actionSections";
import { readPanelsSequence, writePanelsSequence } from "../aiActionSections";
import { modalIsOpen, type TagHl, useUI } from "../store";
import { fetchTagNameSuggestions, TagSuggestion } from "./TagAutocomplete";
import { CombinedTagEditor } from "./CombinedTagEditor";
import { GroupOption, GroupSelect, flattenGroupTree } from "./GroupSelect";
import { ModelHelpOverlay } from "./ModelHelp";
import { MediaTracksView } from "./shared/MediaTracksView";
import { useRotate } from "./shared/useRotate";
import { RefPickerOverlay } from "./RefPicker";
import { useLoadedViewItems, useViewScope } from "../useItems";
import {
  HEAVY_SELECTION, QA_NUM_MAX, qaSetMatch, setIsEmpty,
} from "../qaSets";
import { sanitizeLinkTagInput } from "../tags";
import { rankTagMatches, SUGGEST_CAP } from "../tagRank";
import { TagSuggestList, useSuggestList } from "./TagSuggestList";
import { parseQuickWord } from "../quickTags";
import { useDateFormatters } from "../../shared/time";
import { useErrText, useLang, useT, useTn } from "../i18n";
import { getDraggedItems, clearDraggedItems } from "../dragState";
import { DETECT_WITH, detectAndRemoveRows } from "../detectAndRemove";
import { AnchoredDropdown, useAnchorRect, opensBelow } from "../../shared/AnchoredDropdown";
import { TagAutocomplete } from "./TagAutocomplete";
import { formatTimecode } from "../timecode";
import { FloatingFacesInPicture } from "./shared/FaceInPicture";
import { PlacesSection, placesOnItem } from "./PlacesSection";
import { placeLabel } from "../../query/places/formats";
import { EventsSection, eventsOnItem, spanLabel } from "./EventsSection";
import { UndoBar, UNDO_BAR_H } from "./shared/UndoBar";
import { UndoRunnerSlot, useUndoBar, useUndoRun } from "./shared/useUndoBar";
import { SELECTION_BAR_GAP, SELECTION_BAR_H, SelectionBar, SelectionBarSlot, SelectionReport,
         useReportSelection, useSelectionBarSlot } from "../../shared/SelectionBar";
import { TagRangeLine, useImpliedRangeLabel } from "./shared/TagRanges";
import { PointerMenu, RowAction, RowMenu } from "./shared/RowMenu";
import { useSearchActions } from "./shared/searchActions";
import { ActionToast } from "./shared/ActionToast";
import { useRowSelect, type RowSelect } from "./shared/useRowSelect";
import { usePeopleSelection } from "./shared/usePeopleSelection";
import { chunks, runBulk, BIG_EDIT } from "../bulk";
import { bumpEdits, bumpItem, bumpLibrary } from "../invalidation";
import { PeopleSection, rowKey } from "./PeopleSection";
import { TextSection } from "./TextSection";
import { LAYER } from "../../shared/layers";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { useMenuDismiss } from "../../shared/useMenuDismiss";



/** The Quick Assign sets list's height cap, kept inside the window: at least
 *  a row and a half, at most half the window (the face drawer's rule). */
const QA_HEIGHT_MIN = 80;
const qaHeightMax = () => Math.floor(window.innerHeight * 0.5);

/** The typing-driven tag suggestion source for this panel's add-tag fields —
 *  the one shared definition (see TagAutocomplete), aliased for this file's
 *  many call sites. The cheap rows carry no comment or alias; the annotator,
 *  which needs the full catalog anyway, keeps its static list. */
const fetchTagSuggestions = fetchTagNameSuggestions;


// The right sidebar groups its sections under tabs. A single click switches to a
// tab; ⌘/Ctrl-click toggles one without closing the others, so several tabs can
// be open at once (their sections stack in this order). The Sequence tab only
// appears when the selection is sequence-related (a member or a container).
type TabId = "item" | "general" | "metadata" | "sequence" | "ranking"
  | "groups" | "links" | "tags" | "subjects" | "places" | "events"
  | "captions" | "instructions" | "text";
// The Sequence tab leads when present (it only appears for sequence-related
// selections); Files stays the default open tab.
// Tags, then the three kinds of tag that carry a record — a slug, and then
// who, where and when it names. Instructions beside Captions: they are the
// same row type, and each is a list the other never shows. Text ends the
// prose run — it is prose IN the picture where the pair before it is prose
// ABOUT it — and cannot sit between the pair without splitting it.
const TAB_ORDER: readonly TabId[] = ["sequence", "ranking", "item", "general",
  "metadata", "links", "groups", "tags", "subjects", "places", "events",
  "captions", "instructions", "text"];
const TAB_META: Record<TabId, { icon: string; label: string }> = {
  // "item" = what you can DO with the item (edit, generate, merge, delete) —
  // the preview and the name that used to head it now sit above the tabs, so
  // the tab is called Actions for what is left. "general" = the source-file
  // list (labelled Files, badge = file count).
  item: { icon: "auto_awesome", label: "Actions" },
  general: { icon: "draft", label: "Files" },
  // "Info" rather than "Metadata": the tab holds the item's uid, its dates,
  // its dimensions and its EXIF — what the picture IS, which is the plainer
  // word for it. It also keeps the strip narrow; see the wrapping note below.
  metadata: { icon: "info", label: "Info" },
  sequence: { icon: "collections_bookmark", label: "Sequence" },
  ranking: { icon: "leaderboard", label: "Ranking" },
  groups: { icon: "folder", label: "Groups" },
  links: { icon: "link", label: "Links" },
  tags: { icon: "sell", label: "Tags" },
  // Each of these IS a tag with a record attached — but each is its own list
  // with its own count, and "who is in this" and "where was this" are not two
  // views of one question.
  subjects: { icon: RECORD_ICON.subject, label: "Subjects" },
  places: { icon: RECORD_ICON.place, label: "Places" },
  events: { icon: RECORD_ICON.event, label: "Events" },
  captions: { icon: "notes", label: "Captions" },
  // A caption says what the picture IS; an instruction says how it was made
  // from the pictures it lists. Two lists, because a run trains on one or the
  // other and never on both.
  instructions: { icon: "swap_horiz", label: "Instructions" },
  // A caption is what somebody said about the picture; this is what the
  // picture SAYS (what an OCR engine read off it). `document_scanner`, not
  // `notes` — that is Captions' glyph, and the two must not read as one.
  text: { icon: "document_scanner", label: "Text" },
};
const OPEN_TABS_KEY = "mc.sidebarTabs";
// Which tabs are kept OUT of the strip. Hidden is not closed: a hidden tab is
// still reachable (and still openable) from the ⋯ menu, which is the whole
// point of hiding one — eleven buttons for a library that only ever uses six.
const HIDDEN_TABS_KEY = "mc.sidebarTabsHidden";
// Whether the strip drops the tabs' names and shows their icons alone.
const ICON_TABS_KEY = "mc.sidebarTabsIconsOnly";
/** How tall the ⋯ menu would like to be, and the breathing room it keeps from
 *  the window edge. It scrolls past the first and never crosses the second. */

/** What a click has to MISS for it to count as landing on the background.
 *  Rows mark themselves (`useRowSelect` adds `data-rowsel`); the controls are
 *  excluded so that reaching for Detect faces or the add field does not quietly
 *  put the selection down on the way. */
const ROW_OR_CONTROL =
  "[data-rowsel],button,input,textarea,select,a,[role=button],[title]";

const IS_MAC = typeof navigator !== "undefined" &&
  /mac/i.test(navigator.platform || navigator.userAgent || "");

function loadOpenTabs(): Set<TabId> {
  try {
    const arr = JSON.parse(storage.get(OPEN_TABS_KEY) || "[]");
    if (Array.isArray(arr)) {
      const valid = arr.filter((x): x is TabId => TAB_ORDER.includes(x));
      if (valid.length) return new Set(valid);
    }
  } catch { /* ignore malformed */ }
  return new Set<TabId>(["item"]);
}
function saveOpenTabs(open: Set<TabId>): void {
  try { storage.set(OPEN_TABS_KEY, JSON.stringify([...open])); } catch { /* ignore */ }
}
function loadHiddenTabs(): Set<TabId> {
  try {
    const arr = JSON.parse(storage.get(HIDDEN_TABS_KEY) || "[]");
    if (Array.isArray(arr))
      return new Set(arr.filter((x): x is TabId => TAB_ORDER.includes(x)));
  } catch { /* ignore malformed */ }
  return new Set<TabId>();
}
function saveHiddenTabs(hidden: Set<TabId>): void {
  try { storage.set(HIDDEN_TABS_KEY, JSON.stringify([...hidden])); } catch { /* ignore */ }
}
function loadIconTabs(): boolean {
  try { return storage.get(ICON_TABS_KEY) === "1"; } catch { return false; }
}
function saveIconTabs(on: boolean): void {
  try { storage.set(ICON_TABS_KEY, on ? "1" : "0"); } catch { /* ignore */ }
}

/** The sidebar's tab strip. Plain click selects a single tab; ⌘/Ctrl-click keeps
 *  the others open too (multi-open). Only `tabs` (the currently available ones)
 *  are rendered, minus any the ⋯ menu has been told to hide. */
function SidebarTabs({ tabs, open, onPick, counts, warn, hidden, onHidden,
                      iconsOnly, onIconsOnly }: {
  tabs: TabId[];
  open: Set<TabId>;
  onPick: (id: TabId, additive: boolean) => void;
  // Optional per-tab count shown as a small badge (e.g. groups + links).
  counts?: Partial<Record<TabId, number>>;
  /** Per tab, whether its badge wears AMBER: something under it is a
   *  machine's claim waiting for an answer (owner 2026-09). */
  warn?: Partial<Record<TabId, boolean>>;
  hidden: Set<TabId>;
  onHidden: (next: Set<TabId>) => void;
  iconsOnly: boolean;
  onIconsOnly: (next: boolean) => void;
}) {
  const t = useT();
  const combo = IS_MAC ? "⌘" : "Ctrl";
  const [menu, setMenu] = useState(false);
  // WHAT THE MENU CHANGES APPLIES AT ONCE — you tick an eye and that tab
  // leaves the strip while you watch.
  //
  // It used to be held in a `draft` until the menu closed, and for a real
  // reason: both settings resize the strip, the ⋯ button is at the END of it,
  // and the menu was positioned relative to that button — so the first tick
  // moved the button, dragged the menu along with it, and the second tick
  // landed somewhere else. Deferring the changes fixed the symptom by making
  // the strip not move, at the price of a menu whose ticks did nothing until
  // it was dismissed.
  //
  // The cause was the ANCHORING, so that is what changed: the menu is placed
  // in viewport coordinates measured once, when it opens (`place`), and drawn
  // `position: fixed`. The button may now move as much as it likes underneath
  // it. Reopening measures again, so it comes back at the button's new home.
  const closeMenu = () => setMenu(false);
  // Drawn by `AnchoredDropdown` against the button's rect MEASURED WHEN IT
  // OPENED (`useAnchorRect` re-reads on scroll and resize, not on layout), so
  // the strip may reflow and the ⋯ move underneath it as tabs are hidden,
  // and the menu stays where the pointer left it. Reopening measures again.
  const anchor = useRef<HTMLButtonElement>(null);
  const rect = useAnchorRect(anchor, menu);
  useMenuDismiss(menu, closeMenu, { within: [anchor] });
  // REVERSED when it opens upwards, so the row order runs away from the
  // button in both directions: the first tab stays the one nearest the ⋯
  // you just pressed, which is where the eye already is.
  const up = !!rect && !opensBelow(rect);
  const shown = tabs.filter((id) => !hidden.has(id));
  // What the ⋯ button carries: the counts of the tabs it is standing in for.
  // A hidden tab still has things in it, and a strip that simply dropped it
  // would be hiding the fact as well as the button.
  const hiddenTotal = tabs
    .filter((id) => hidden.has(id))
    .reduce((n, id) => n + (counts?.[id] ?? 0), 0);
  return (
    // Each tab is as wide as its own label, and they WRAP. An equal-width grid
    // was tried first and its cost is that one long label sets the width of
    // every tab: "Instructions" makes "Info" three times wider than its word,
    // so a row of five held two and the strip ran to three lines with air in every
    // cell. Sized to content the same five fit in two, and the differing widths
    // are themselves a way back to a tab you have used before.
    // Top spacing matches the gap above the nav row above them.
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 4, padding: "4px 0 10px" }}>
      {shown.map((id) => {
        const active = open.has(id);
        const meta = TAB_META[id];
        const badge = !!counts?.[id];
        return (
          <button
            key={id}
            onClick={(e) => onPick(id, e.metaKey || e.ctrlKey)}
            title={`${t(meta.label)} — click to switch · ${combo}-click to keep several tabs open`}
            style={{
              // `0 0 auto` so a tab never stretches to fill the row it ends up
              // on; `maxWidth` so a long label in another language truncates
              // instead of pushing the strip wider than the sidebar.
              flex: "0 0 auto", maxWidth: "100%",
              minWidth: iconsOnly ? 30 : 0, height: 30, borderRadius: "var(--r-4)", cursor: "pointer",
              display: "flex", alignItems: "center",
              justifyContent: iconsOnly ? "center" : "flex-start",
              // Icon-only, a tab carrying a count is already wide; a bare one
              // is 16 px of glyph, so it gets the width back as padding or it
              // reads as a smaller button rather than the same button with
              // less in it.
              gap: 5,
              padding: !iconsOnly ? "0 8px" : badge ? "0 7px" : "0 11px",
              border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
              background: active ? "var(--accent-dim)" : "transparent",
              color: active ? "var(--accent)" : "var(--muted)",
              fontSize: "var(--fs-2)", fontWeight: 600,
            }}
          >
            <Icon name={meta.icon} size={16} style={{ flex: "0 0 auto" }} />
            {/* Without the label the `title` is the only thing left naming the
                tab — which it already was for the ⋯ button, and is why every
                one of these carries one. The COUNT stays either way: it is not
                a title, and it is the reason the badges exist at all. */}
            {!iconsOnly && (
              <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", flex: "0 1 auto", minWidth: 0 }}>
                {t(meta.label)}
              </span>
            )}
            {counts?.[id] ? <CountBadge n={counts[id]} active={active} warn={warn?.[id]} /> : null}
          </button>
        );
      })}
      {/* Every tab there is, hidden ones included — so hiding one is never a
          way to lose it. The row's LABEL opens the tab; the eye beside it is
          about the strip and nothing else. */}
      <div style={{ position: "relative", flex: "0 0 auto" }}>
        <button
          ref={anchor}
          onClick={() => setMenu((v) => !v)}
          title={t("All tabs")}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            height: 30, minWidth: 30, padding: hiddenTotal ? "0 7px" : 0,
            justifyContent: "center", borderRadius: "var(--r-4)", cursor: "pointer",
            border: `1px solid ${menu ? "var(--accent)" : "var(--border)"}`,
            background: menu ? "var(--accent-dim)" : "transparent",
            color: menu ? "var(--accent)" : "var(--muted)",
          }}
        >
          <Icon name="more_horiz" size={16} />
          {hiddenTotal ? <CountBadge n={hiddenTotal} active={menu} /> : null}
        </button>
        {menu && (
          <AnchoredDropdown rect={rect} minWidth={210}>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {(up ? [...tabs].reverse() : tabs).map((id) => {
                const active = open.has(id);
                const off = hidden.has(id);
                const meta = TAB_META[id];
                return (
                  <div
                    key={id}
                    style={{ display: "flex", alignItems: "center", gap: 6, borderRadius: "var(--r-3)", paddingRight: 2 }}
                  >
                    <button
                      className="hoverable"
                      onClick={(e) => { closeMenu(); onPick(id, e.metaKey || e.ctrlKey); }}
                      title={`${t(meta.label)} — click to switch · ${combo}-click to keep several tabs open`}
                      style={{ display: "flex", alignItems: "center", gap: 7, flex: 1, minWidth: 0, padding: "6px 8px", borderRadius: "var(--r-3)", border: "none", background: "transparent", cursor: "pointer", color: active ? "var(--accent)" : "var(--text-2)", fontSize: "var(--fs-3)", fontWeight: active ? 600 : 400, textAlign: "left" }}
                    >
                      <Icon name={meta.icon} size={15} color={active ? "var(--accent)" : "var(--muted-2)"} style={{ flex: "0 0 auto" }} />
                      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {t(meta.label)}
                      </span>
                      {counts?.[id] ? (
                        <span style={{ flex: "0 0 auto", fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>
                          {counts[id]}
                        </span>
                      ) : null}
                    </button>
                    <span
                      role="button"
                      className="hoverable"
                      title={off ? t("Show this tab in the bar") : t("Hide this tab from the bar")}
                      onClick={() => {
                        const next = new Set(hidden);
                        if (off) next.delete(id); else next.add(id);
                        onHidden(next);
                      }}
                      style={{ flex: "0 0 auto", display: "flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, borderRadius: "var(--r-2)", cursor: "pointer", color: off ? "var(--muted-3)" : "var(--muted)" }}
                    >
                      <Icon name={off ? "visibility_off" : "visibility"} size={15} />
                    </span>
                  </div>
                );
              })}
              {/* Below a rule, because it is about the STRIP rather than about
                  any one tab — the rows above each name a tab, this names the
                  bar they sit in. The tick rides in the eye's column (the other
                  toggle here) and keeps its width when off, or the label steps
                  sideways as the state changes. */}
              {/* The settings row stays LAST in reading order whichever way
                  the menu opens. Only the TABS reverse — that is what keeps
                  the first of them nearest the ⋯ you just pressed — and a
                  setting that moved to the top when the menu flipped would be
                  a third place for it to be. */}
              <div style={{ height: 1, background: "var(--menu-border)", margin: "5px 6px" }} />
              <div style={{ display: "flex", alignItems: "center", gap: 6, borderRadius: "var(--r-3)", paddingRight: 2 }}>
                <button
                  className="hoverable"
                  onClick={() => onIconsOnly(!iconsOnly)}
                  title={t("Show the tabs as icons alone, without their names")}
                  style={{ display: "flex", alignItems: "center", gap: 7, flex: 1, minWidth: 0, padding: "6px 8px", borderRadius: "var(--r-3)", border: "none", background: "transparent", cursor: "pointer", color: "var(--text-2)", fontSize: "var(--fs-3)", textAlign: "left" }}
                >
                  <Icon name="text_fields" size={15} color="var(--muted-2)" style={{ flex: "0 0 auto" }} />
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {t("Icons only")}
                  </span>
                </button>
                <span style={{ flex: "0 0 auto", display: "flex", alignItems: "center", justifyContent: "center", width: 24, height: 24 }}>
                  {iconsOnly && <Icon name="check" size={15} color="var(--accent)" />}
                </span>
              </div>
            </div>
          </AnchoredDropdown>
        )}
      </div>
    </div>
  );
}

/** A labeled sidebar section with a click-to-collapse header. The open/closed
 *  state persists per-section (keyed by `sk`) in localStorage so the user's
 *  chosen layout survives reloads. `actions` render on the right of the header
 *  and are hidden while collapsed (they operate on the hidden body).
 *  With `hideHeader` the title + collapse chevron are dropped and the body is
 *  always shown — used when the section is the sole content of a sidebar tab, so
 *  its heading would just duplicate the tab label (any `actions` still render). */
function CollapsibleSection({
  title,
  sk,
  actions,
  marginTop = 16,
  hideHeader = false,
  children,
}: {
  title: string;
  sk: string;
  actions?: React.ReactNode;
  marginTop?: number;
  hideHeader?: boolean;
  children: React.ReactNode;
}) {
  const t = useT();
  const storeKey = "mc.sec." + sk;
  const [open, setOpen] = useState(() => {
    try { return storage.get(storeKey) !== "0"; } catch { return true; }
  });
  const toggle = () =>
    setOpen((o) => {
      const next = !o;
      try { storage.set(storeKey, next ? "1" : "0"); } catch { /* ignore */ }
      return next;
    });
  if (hideHeader) {
    return (
      <div style={{ marginTop: 0 }}>
        {children}
        {/* BELOW the rows, not above them. A bulk action appears the moment a
            second row is selected — which is mid-gesture when the selection is
            being dragged out — and above the list that shifts every row down
            from under the pointer. */}
        {actions && (
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
            {actions}
          </div>
        )}
      </div>
    );
  }
  return (
    <div style={{ marginTop }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", minHeight: 22, marginBottom: open ? 8 : 0 }}>
        <button
          type="button"
          onClick={toggle}
          title={open ? "Collapse section" : "Expand section"}
          style={{
            display: "flex", alignItems: "center", gap: 3, minWidth: 0,
            background: "none", border: "none", padding: 0, margin: 0, cursor: "pointer",
          }}
        >
          <Icon
            name="chevron_right"
            size={16}
            style={{ color: "var(--muted-2)", marginLeft: -3, transition: "transform 0.12s ease", transform: open ? "rotate(90deg)" : "none" }}
          />
          <span style={{ ...SECTION_LABEL, letterSpacing: "0.04em", cursor: "pointer" }}>{t(title)}</span>
        </button>
        {open && actions}
      </div>
      {open && children}
    </div>
  );
}

/** Placeholder shown for very large selections, where
 *  the per-item aggregation is skipped (Quick Assign still applies to all). */
function HeavySelectionNote({ count }: { count: number }) {
  const tn = useTn();
  return (
    <div style={{ marginTop: 16, padding: "10px 12px", background: "var(--panel-3)", border: "1px solid var(--border)", borderRadius: "var(--r-5)", fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
      {tn({ one: "{n} item selected — tag and group details are hidden.", other: "{n} items selected — tag and group details are hidden." }, count)}
      Use Quick Assign below to tag them all at once.
    </div>
  );
}

// A tag's aggregate state across the current (possibly multi-item) selection.
type TagState = "pos" | "neg" | "mixed";

interface UnifiedTagRow {
  name: string;
  // For direct assignments: aggregate state across the selection. For inherited
  // tags: "pos"/"neg" as assigned by the group(s).
  state: TagState;
  // How many of the selected items carry this row's assignment (multi-item
  // aggregate only; rendered as "k/N" when not all of them do).
  count?: number;
  // The sign split behind a mixed row (multi-item aggregate only). With both
  // present the chip says "2+ 1−" instead of a coverage fraction: everyone
  // may well carry the tag, and what the selection disagrees about is the
  // SIGN — a yellow row with no numbers was the question "why do only some
  // rows count?".
  pos?: number;
  neg?: number;
  // True when the tag is inherited from a group (no direct remove button; the
  // flip button instead adds a direct override).
  inherited: boolean;
  // Names of the groups that contributed an inherited tag (empty for direct).
  groups: string[];
}

export function PropertiesPanel() {
  const { selectedItems: liveSelectedItems, clearItemSelection, setSelectedItems, openEditor, openAnnotator, showSequence, trashView, hiddenView, showHistoryFor } = useUI();
  const selPast = useUI((s) => s.selPast);
  const selFuture = useUI((s) => s.selFuture);
  const selectionBack = useUI((s) => s.selectionBack);
  const selectionForward = useUI((s) => s.selectionForward);
  const pinnedSelection = useUI((s) => s.pinnedSelection);
  const pinnedItems = useUI((s) => s.pinnedItems);
  const togglePinned = useUI((s) => s.togglePinned);
  const sequenceView = useUI((s) => s.sequenceView);
  // The occurrences the grid's selection gesture named (primary copies) —
  // what "Remove from sequence" takes for a repeated member.
  const selMembers = useUI((s) => s.selMembers);
  const qc = useQueryClient();
  const t = useT();
  const tn = useTn();
  // Date/time formatting per the user's Language & Region settings.
  const { formatDateTime } = useDateFormatters();
  // While pinned the sidebar operates on the frozen `pinnedItems`; otherwise it
  // follows the live grid selection. Everything below (detail query, actions,
  // tag/group sections) keys off this effective selection.
  const baseSelection = pinnedSelection ? pinnedItems : liveSelectedItems;
  // When a sequence is open in the grid and nothing is selected, act on the
  // sequence's own container item (so the sidebar shows the sequence itself).
  const { data: openSeq } = useQuery({
    queryKey: ["sequence", sequenceView],
    queryFn: () => api.sequence(sequenceView as number),
    // Whenever a sequence view is open (the grid mounts the same key, so this
    // is free): the container id with nothing selected, and the member list
    // the "Remove from sequence" row reads with a selection.
    enabled: sequenceView != null,
  });
  const seqContainerId = sequenceView != null ? openSeq?.item_id ?? null : null;
  const selectedItems = baseSelection.length === 0 && seqContainerId != null
    ? [seqContainerId]
    : baseSelection;
  const single = selectedItems.length === 1 ? selectedItems[0] : null;

  const { data: detail } = useQuery({
    queryKey: ["item", single],
    queryFn: () => api.item(single as number),
    enabled: single != null,
  });
  const { data: allGroups } = useQuery({ queryKey: ["groups"], queryFn: api.groups });

  // Per-item direct tags + group memberships for the current selection, so the
  // tag/group sections can aggregate across several images. Fed from whatever
  // pages of the view the grid has loaded (shared cache, no queries of its
  // own); items on unloaded pages simply miss from the maps, which every
  // consumer already tolerates via Map.get.
  const items = useLoadedViewItems();
  const itemsById = useMemo(() => {
    const m = new Map<number, { direct_tags: TagAssignment[]; group_ids: number[] }>();
    for (const it of items) m.set(it.id, { direct_tags: it.direct_tags, group_ids: it.group_ids });
    return m;
  }, [items]);
  // Hidden state per selected item (from the shared grid cache), used to decide
  // whether the Hide/Show toggle should offer to hide or to reveal.
  const hiddenById = useMemo(() => {
    const m = new Map<number, boolean>();
    for (const it of items) m.set(it.id, it.hidden);
    return m;
  }, [items]);
  // ARE THE ITEMS THIS PANEL IS ABOUT ACTUALLY IN THE TRASH?
  //
  // It used to ask the VIEW — "is the Trash open?" — and the sidebar does not
  // have to be showing what the grid is: PIN it and it keeps the items you
  // pinned while you browse anywhere, the Trash included. So opening the Trash
  // over a pinned selection put live library pictures under the Trash heading,
  // with **Restore** and a red **permanent delete** offered for them. That is
  // how two pictures come to "appear in the trash" and be gone after a reload
  // (a reload drops the pin), and the red button on that panel would have
  // erased a live picture for good.
  //
  // One item is exact — `ItemDetail.trashed` has been on the wire all along
  // and nothing read it. For several, the live selection in the Trash view
  // came from the trash grid so every member is trashed; a PINNED one is
  // trusted only where every member is in the loaded trash pages. Otherwise
  // it DECLINES: the panel would be guessing, and the guess it would be making
  // is offered next to a button with no way back.
  const loadedIds = useMemo(() => new Set(items.map((it) => it.id)), [items]);
  // WHICH RANKING'S VIEW this panel is standing in, for the Ranking tab —
  // a fact about the SCOPE, like `trashView` two lines down.
  const rankingView = useUI((s) => s.rankingView);
  const rankingPool = useUI((s) => s.rankingPool);
  const inTrash = single != null
    ? !!detail?.trashed
    : trashView && (!pinnedSelection
                    || selectedItems.every((id) => loadedIds.has(id)));

  // Sequence membership count per item (grid cache) — gates the Sequence tab.
  const seqCountById = useMemo(() => {
    const m = new Map<number, number>();
    for (const it of items) m.set(it.id, it.seq_count);
    return m;
  }, [items]);
  // Optimistic hidden state applied by the Hide/Show button. Once items are
  // hidden they leave the grid query (and thus `hiddenById`), so the button
  // couldn't otherwise tell they're now hidden — it would keep saying "Hide".
  // Reset whenever the selection changes (a fresh selection reads live state).
  const [hiddenOverride, setHiddenOverride] = useState<Record<number, boolean>>({});
  useEffect(() => { setHiddenOverride({}); }, [selectedItems]);

  // Tag suggestions are fetched as they are typed (`fetchTagSuggestions`
  // above) — this panel used to hold the whole catalog sorted by usage just
  // to feed its add-tag fields.

  // Post-edit invalidation, narrowed: the TOUCHED items' details refresh
  // immediately (exact ["item", id] via bumpItem — an edit to one item never
  // changes another's detail), while the list/catalog queries (items, tags,
  // groups, facets, library-stats, item-metadata, sequences) go through the
  // short-wait coalescer so a run of quick edits costs one refetch sweep.
  const invalidateAfterTagEdit = () => {
    for (const id of selectedItems) bumpItem(id);
    bumpEdits();
  };
  const invalidateAfterGroupEdit = () => {
    for (const id of selectedItems) bumpItem(id);
    bumpEdits();
  };
  const invalidateAfterLinkEdit = () => {
    for (const id of selectedItems) bumpItem(id);
    bumpEdits();
  };
  // Shared by the Captions and Instructions tabs — they are the same rows, so
  // an edit in either refreshes the same things.
  // The same two steps as the three above, and for the same reason: the keys
  // this used to name one by one — `library-stats` for the Pending count,
  // `item-metadata` for the item's "Modified" field, `item-slim-tags` for a
  // multi-selection's counts — are all in `EDIT_KEYS`, and naming them here
  // as well meant a second, immediate round of grid pages that the
  // coalescer's round aborted 150 ms later.
  const invalidateAfterCaptionEdit = () => {
    for (const id of selectedItems) bumpItem(id);
    bumpEdits();
  };

  const afterItemsChanged = () => {
    // Capture before clearing — the ids are what was just acted on.
    const touched = selectedItems;
    clearItemSelection();
    // A destructive action on a pinned selection consumes it — unpin so the
    // sidebar doesn't keep showing now-gone items.
    if (pinnedSelection) togglePinned();
    for (const id of touched) bumpItem(id);
    bumpEdits();
  };

  // Merge the selection into ONE item: every other picked item is folded into
  // the FIRST, which survives and stays selected. It used to be offered for
  // exactly two — but three pictures of the same thing is the same sentence
  // said twice, and the gesture that finds them (a marquee, a shift-click)
  // rarely stops at two. ONE CALL PER SOURCE: a merge is one logged,
  // revertible event per pair, and there is no bulk op behind it.
  const mergeSelected = async () => {
    if (selectedItems.length < 2) return;
    const [target, ...sources] = selectedItems;
    for (const source of sources) await api.mergeItems(source, target);
    afterItemsChanged();
    setSelectedItems([target]);
  };

  // Group the multi-selection into a new ordered sequence (button above the
  // Hide/Delete row; the resulting membership shows in the Sequence tab).
  const createSequenceFromSelection = async () => {
    if (selectedItems.length < 2) return;
    await api.createSequence("New sequence", selectedItems);
    qc.invalidateQueries({ queryKey: ["sequences"] });
    invalidateAfterGroupEdit();
  };

  // Moving to the Trash is reversible; erasing happens IN the Trash, from
  // `deleteForever` below. The button says which of the two it is.
  const trashSelected = async () => {
    if (selectedItems.length === 0) return;
    await api.trashItems(selectedItems);
    afterItemsChanged();
  };
  const restoreSelected = async () => {
    if (selectedItems.length === 0) return;
    await api.restoreItems(selectedItems);
    afterItemsChanged();
  };
  // Hide/unhide the selection (non-destructive). The selection is kept so the
  // item stays inspectable in the sidebar even after it leaves the grid.
  const setHidden = async (hide: boolean) => {
    if (selectedItems.length === 0) return;
    const ids = selectedItems;
    await api.hideItems(ids, hide);
    setHiddenOverride((o) => {
      const next = { ...o };
      for (const id of ids) next[id] = hide;
      return next;
    });
    for (const id of ids) bumpItem(id);
    bumpEdits();
  };
  const deleteForever = async () => {
    if (selectedItems.length === 0) return;
    const n = selectedItems.length;
    if (!(await confirm({
      title: tn({ one: "Permanently delete 1 item?",
                  other: "Permanently delete {n} items?" }, n),
      body: tn({
        one: "This removes the image and all its versions, tags and captions. This cannot be undone.",
        other: "This removes the images and all their versions, tags and captions. This cannot be undone.",
      }, n),
      answer: { label: t("Delete"), danger: true },
    }))) return;
    await api.deleteItems(selectedItems);
    afterItemsChanged();
  };

  // A "sequence" item is a folder-like container: open it (view its pages) or
  // remove it (delete the sequence, keeping the member items).
  const isSequence = single != null && detail?.kind === "sequence";
  // Sequences own no source files, so they can't be merged.
  const kindOf = (id: number) => items.find((it) => it.id === id)?.kind ?? "image";
  const selectionHasSequence = selectedItems.some((id) => kindOf(id) === "sequence");
  // Background/watermark removal operate on still images only — not videos.
  const selectionHasVideo = selectedItems.some((id) => kindOf(id) === "video");
  const removeSequenceItem = async () => {
    if (detail?.sequence_id == null) return;
    if (!(await confirm({
      title: t("Remove the sequence “{name}”?", { name: detail.name }),
      body: t("The images it contains stay in the library; only the sequence grouping is deleted."),
      answer: { label: t("Remove"), danger: true },
    }))) return;
    await api.removeSequence(detail.sequence_id);
    afterItemsChanged();
  };
  // A selected sequence container's members — the Detect actions are offered on
  // a sequence only when every member is a still image.
  const { data: selSeqInfo } = useQuery({
    queryKey: ["sequence", detail?.sequence_id],
    queryFn: () => api.sequence(detail?.sequence_id as number),
    enabled: isSequence && detail?.sequence_id != null,
  });
  const seqAllImages =
    (selSeqInfo?.members?.length ?? 0) > 0 &&
    (selSeqInfo?.members ?? []).every((m) => m.kind === "image");
  // SEVERAL sequences at once still detect: the server expands each container
  // into its pages (faces/ocr are batch kinds; panels walks a container
  // itself), so the section stays offered when EVERY selected item is a
  // sequence whose members are all stills. Member kinds come from one query
  // per container — capped, because a query storm is worse than a hidden
  // section on a selection nobody detects over anyway.
  const selectionAllSequences = selectedItems.length > 1
    && selectedItems.every((id) => kindOf(id) === "sequence");
  const selSeqIds = selectionAllSequences
    ? selectedItems
        .map((id) => items.find((it) => it.id === id)?.sequence_id)
        .filter((x): x is number => x != null)
        .slice(0, 25)
    : [];
  const seqInfos = useQueries({
    queries: selSeqIds.map((sid) => ({
      queryKey: ["sequence", sid] as const,
      queryFn: () => api.sequence(sid),
    })),
  });
  const seqsAllImages = selectionAllSequences
    && selSeqIds.length === selectedItems.length
    && seqInfos.length === selSeqIds.length
    && seqInfos.every((q) => (q.data?.members?.length ?? 0) > 0
        && (q.data?.members ?? []).every((m) => m.kind === "image"));

  // The AI "Generate tags" / "Generate caption" buttons live at the top of the
  // Tags and Captions sections (background removal stays by Edit). They apply to
  // real media only — never sequences or trashed items.
  const canRunAi = selectedItems.length > 0 && !inTrash && !isSequence && !selectionHasSequence;
  const onAiEnqueued = () => qc.invalidateQueries({ queryKey: ["ml-jobs"] });
  // Generate tags AND Detect watermarks: what a watermark run finds lands as
  // BOXES on the configured watermark tag, so it belongs where the tags are
  // — beside the button that writes the other kind of tag, and in the one
  // list that can then show you what it found. It used to be in the Actions
  // tab's Detect section, which is where a model producing a FILE lives.
  //
  // ONE COLUMN AT THE SECTION'S OWN GAP, not two blocks butted together.
  // `AiActionButtons` is itself a `column` flex with `gap: 6` and full-width
  // buttons, so two of them side by side in a fragment sat FLUSH — no space
  // at all between Generate tags and Detect watermarks, where the models
  // inside either one are 6 apart. The wrapper says the gap once.
  const genTagsButton = canRunAi ? (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <AiActionButtons itemIds={selectedItems} kinds={["tag"]}
                       onEnqueued={onAiEnqueued} />
      {!selectionHasVideo && (
        <AiActionButtons itemIds={selectedItems} kinds={["watermark_detect"]}
                         onEnqueued={onAiEnqueued} />
      )}
    </div>
  ) : null;
  const genCaptionButton = canRunAi ? (
    <AiActionButtons itemIds={selectedItems} kinds={["caption"]} onEnqueued={onAiEnqueued} />
  ) : null;
  // Detection stays offered even once faces have been found: a second run with
  // the OTHER detector is the normal next step in a mixed library, and
  // reconciliation is built so re-running never costs anything.
  //
  // Never on a VIDEO, though. A detector reads a PICTURE, and a film's active
  // file is not one — the job opened it with Pillow and died. Where a film's
  // faces are worth finding is on a STILL taken from it, which is an ordinary
  // image item with its own Subjects tab. (The Detect section further down has
  // always excluded videos; this button is the same offer in the Subjects tab
  // and had not.)
  const detectFacesButton = canRunAi && !selectionHasVideo ? (
    <AiActionButtons
      itemIds={selectedItems}
      kinds={["faces"]}
      doneModels={detail?.face_models ?? []}
      onEnqueued={() => {
        onAiEnqueued();
        qc.invalidateQueries({ queryKey: ["faces"] });
      }}
    />
  ) : null;
  /** A list's own Annotate button, with whatever else sits at the top of
   *  that list under it. Annotating is the same work with the picture in
   *  front of you, so every list offers it and each carries its OWN tab
   *  along; a sequence container has no picture to annotate, and neither
   *  does the Trash, where nothing is edited at all. */
  const annotateAnd = (tab: string, extra: React.ReactNode) => {
    const canAnnotate = single != null && !inTrash
      && (detail?.kind === "image" || detail?.kind === "video");
    if (!canAnnotate) return extra;
    return (<>
      <AnnotateButton itemId={single} tab={tab} />
      {extra}
    </>);
  };
  // Detect text — the same gates, for the same recorded reasons: an OCR
  // engine reads a PICTURE, and a film's text is read on a still.
  const detectTextButton = canRunAi && !selectionHasVideo ? (
    <AiActionButtons
      itemIds={selectedItems}
      kinds={["ocr"]}
      doneModels={detail?.text_models ?? []}
      onEnqueued={() => {
        onAiEnqueued();
        qc.invalidateQueries({ queryKey: ["text"] });
      }}
    />
  ) : null;
  // "Detect with X and remove" — one row per OCR engine that has NOT read
  // this file, appended to the Remove text menu (`detectAndRemoveRows`, the
  // one builder the two context menus share). An unread page has nothing for
  // the removal to paint out, so the engines are offered there, and what they
  // read is kept (it lands in the Text tab and can be corrected before a
  // second pass).
  const { data: mlModels } = useQuery({ queryKey: ["ml-models"], queryFn: api.mlModels });
  // The configured detection tag names (Settings → Tagging): which tag the
  // box-driven watermark removal reads, and where "detect watermarks" files
  // what it finds.
  const { data: appSettings } = useQuery({
    queryKey: ["settings"], queryFn: api.getSettings });
  const wmTag = appSettings?.watermark_tag || "watermark";
  // The TEXT tag is optional ("" = OCR writes regions only), which is why it
  // has no fallback: with none configured there are no boxes to paint out and
  // the tag-driven text removal is not offered at all.
  const textTag = appSettings?.text_tag || "";
  /** Does this item carry `name` with at least one box on it? The gate both
   *  box-driven removals share — each over its OWN configured name. */
  const hasBoxesOn = (name: string) => !!name && single != null
    && (detail?.tag_instances ?? []).some(
      (ti) => ti.name === name && ti.boxes.length > 0);

  const detectAndRemove = useMemo(() => {
    const rows = detectAndRemoveRows(mlModels?.tasks ?? [],
                                     detail?.text_models ?? []);
    return rows.length ? { text_removal: rows } : undefined;
  }, [mlModels, detail?.text_models]);

  // --- Right-sidebar tabs ---------------------------------------------------
  // Which tabs make sense for the current selection. General + Tags are always
  // available. (Sequence content lives at the top of the General tab,
  // self-gated to when the selection is sequence-related.)
  //
  // Captions, instructions and text are offered for ANY selection now. They
  // used to be single-item, on the reasoning that a list of eight pictures'
  // captions is eight statements about eight pictures — which is true, and
  // is why the multi view is NOT that list: it is the two counts plus the
  // two things worth doing to all of them (have the machine write the
  // missing ones, or put the same sentence on every one). The same
  // reasoning the who/where/when tabs already went through.
  const captionsAvail = selectedItems.length > 0;
  // The Sequence tab exists only for sequence-related selections: a sequence
  // container, or items that belong to at least one sequence (grid cache count,
  // with the single-item detail as fallback for items not in the grid).
  const sequenceAvail = !inTrash && (
    (single != null && detail?.kind === "sequence") ||
    selectedItems.some((id) => (seqCountById.get(id) ?? 0) > 0) ||
    (single != null && (detail?.seq_count ?? 0) > 0)
  );
  const availableTabs = useMemo<TabId[]>(() => TAB_ORDER.filter((id) =>
    id === "captions" || id === "instructions" ? captionsAvail
    : id === "metadata" ? single != null
    : id === "sequence" ? sequenceAvail
    // WHERE THIS PICTURE STANDS, offered only inside a ranking's own view —
    // gated like the Sequence tab, and for the same reason: it is about the
    // scope you came in through rather than about the item on its own. It is
    // also the half of a ranking that SURVIVES a selection; the scale, the
    // pools and the caveat are the whole-view panel's, and that unmounts the
    // moment a picture is picked, which here is the primary gesture.
    : id === "ranking" ? rankingView != null && selectedItems.length > 0
    : id === "links" || id === "groups" ? selectedItems.length > 0
    // Who, where and when are offered for ANY selection now. They used to be
    // single-item, on the reasoning that an identity's state IN a picture —
    // which face, how old, which venue — is not something a selection can
    // show. True, and it is not what a selection is asking: the question over
    // eight pictures is who is in them, which is the ASSIGNMENT, and that
    // aggregates exactly as tags and groups do. `MultiKindTags` shows that
    // half and nothing else.
    : id === "subjects" || id === "places" || id === "events"
      ? selectedItems.length > 0
    // Named POSITIVELY (the Import/Export lesson: "not subjects, not places"
    // silently gained a wrong entry when Events arrived): text is read off a
    // single IMAGE — a sequence has no picture and a film's text is read on
    // a still.
    // Text is read off a PICTURE — a sequence has no picture of its own and
    // a film's text is read on a still — so a selection qualifies when it
    // holds no video and, for one item, is an image.
    : id === "text" ? (single != null
        ? detail?.kind === "image"
        : selectedItems.length > 0 && !selectionHasVideo)
    // Files tab: only a single non-sequence item owns a source-file list.
    : id === "general" ? single != null && detail?.kind !== "sequence"
    : true
  ), [captionsAvail, selectedItems.length, single, sequenceAvail, detail?.kind,
      selectionHasVideo, rankingView]);
  // The slim bulk details for a MULTI-selection — what the caption, the
  // instruction and the text tabs count over. The SAME query key
  // `AssignedTags` uses, so the two share one request rather than asking
  // twice for the same rows.
  const { data: multiSlims } = useQuery({
    queryKey: ["item-slim-tags",
               [...selectedItems].sort((a, b) => a - b).join(",")],
    queryFn: () => api.itemDetails(selectedItems),
    enabled: selectedItems.length > 1 && selectedItems.length <= 500,
  });
  // Counts for the Groups / Links tab badges (single-item relationships).
  const { data: linksData } = useQuery({
    queryKey: ["relationships", single],
    queryFn: () => api.itemRelationships(single as number),
    enabled: single != null,
  });
  // The subject, place and event catalogs. Fetched whenever ANYTHING is
  // selected rather than when their tab is open, because the tab BADGES need
  // them — a count that only appears once you have looked is not a count.
  // (Subjects joined the three when those tabs started aggregating over a
  // multi-selection: `detail.subjects` answers for one item, and there is no
  // detail for eight.)
  const anySelected = selectedItems.length > 0;
  const { data: allSubjects } = useQuery({
    queryKey: ["subjects"], queryFn: api.subjects, enabled: anySelected });
  const { data: allPlaces } = useQuery({
    queryKey: ["places"], queryFn: api.places, enabled: anySelected });
  const { data: allEvents } = useQuery({
    queryKey: ["events"], queryFn: api.events, enabled: anySelected });
  // Each kind's catalog as `{tag, label}` — the label formatted by whoever
  // knows how (an address is not a slug), once, so the rows and the badge
  // read the same names.
  const subjectCatalog = useMemo(
    () => (allSubjects ?? []).filter((s) => s.tag)
      .map((s) => ({ tag: s.tag, label: s.display_name || s.tag,
                     comment: s.comment ?? "" })),
    [allSubjects]);
  const placeCatalog = useMemo(
    () => (allPlaces ?? []).filter((p) => p.tag)
      .map((p) => ({ tag: p.tag,
                     label: placeLabel(p),
                     comment: p.comment ?? "" })),
    [allPlaces]);
  const eventCatalog = useMemo(
    () => (allEvents ?? []).filter((e) => e.tag)
      .map((e) => ({ tag: e.tag, label: e.display_name || e.tag,
                     comment: e.comment ?? "" })),
    [allEvents]);
  //: WHAT IS WAITING FOR AN ANSWER, per tab (owner 2026-09): the badge on
  //  Tags goes amber over a pending tag group, on Subjects over a guessed
  //  face, on Captions over a generated caption — the colour every
  //  unanswered claim wears in this app, on the count that would otherwise
  //  say nothing about it. The faces are the item's own (the same query the
  //  Tags section reads for its marks, so it is fetched once).
  const { data: singleFaces } = useQuery({
    queryKey: ["faces", single],
    queryFn: () => api.faces(single as number),
    enabled: single != null && (detail?.subjects?.length ?? 0) > 0,
  });
  const tabWarn = useMemo<Partial<Record<TabId, boolean>>>(() => {
    if (single == null || !detail) return {};
    const caps = detail.captions ?? [];
    return {
      tags: (detail.tag_groups ?? []).some((g) => g.system),
      subjects: (singleFaces ?? []).some((f) => !f.dismissed
        && f.subjects.some((sub) => sub.assigned_by === "suggested")),
      captions: caps.some((c) => c.pending && (c.kind ?? "caption") === "caption"),
      instructions: caps.some((c) => c.pending && c.kind === "instruction"),
    };
  }, [single, detail, singleFaces]);
  const tabCounts = useMemo<Partial<Record<TabId, number>>>(() => {
    const groups = single != null ? (detail?.group_ids?.length ?? 0) : 0;
    const links = single != null ? (linksData?.length ?? 0) : 0;
    // TAGS counts every tag, the other three each count their own rows. A
    // subject IS a tag, so the numbers overlap — which is right: the Tags badge
    // answers "how many labels does this picture carry" and Subjects answers
    // "how many people are in it".
    const tags = single != null ? (detail?.tags?.length ?? 0) : 0;
    // Over a MULTI-selection each of the three counts the UNION — how many
    // people are in these pictures, not how many are in all of them. The
    // partial rows are the ones the yellow is about, and a badge that left
    // them out would be smaller than the list under it.
    const union = (catalog: { tag: string }[]) => {
      const want = new Set(catalog.map((c) => c.tag));
      const seen = new Set<string>();
      for (const id of selectedItems) {
        for (const a of itemsById.get(id)?.direct_tags ?? []) {
          if (!a.negative && want.has(a.name)) seen.add(a.name);
        }
      }
      return seen.size;
    };
    const subjects = single != null ? (detail?.subjects?.length ?? 0)
      : union(subjectCatalog);
    const places = single != null
      ? placesOnItem(allPlaces, detail ?? null).length : union(placeCatalog);
    const events = single != null
      ? eventsOnItem(allEvents, detail ?? null).length : union(eventCatalog);
    // Each caption is in exactly one of the two lists, so the two badges never
    // count the same row twice.
    const all = single != null ? (detail?.captions ?? []) : [];
    const captions = all.filter((c) => (c.kind ?? "caption") === "caption").length;
    const instructions = all.filter((c) => c.kind === "instruction").length;
    // Files tab badge: the item's source-file count (sequences own no files).
    const general = single != null && detail?.kind !== "sequence"
      ? (detail?.files?.length ?? 0) : 0;
    // Sequence tab badge: a sequence container shows its member count; a plain
    // item shows how many sequences it belongs to (replaces the "N items" text
    // that used to sit above the member list inside the tab).
    const sequence = single == null ? 0
      : detail?.kind === "sequence" ? (selSeqInfo?.total ?? selSeqInfo?.members?.length ?? 0)
      : (detail?.seq_count ?? seqCountById.get(single) ?? 0);
    // BLOCKS, not words: forty is a page's worth of text, nine hundred says
    // nothing. Off the detail, so the badge never pulls the whole tree.
    const text = single != null ? (detail?.text_count ?? 0) : 0;
    return { general, groups, links, tags, subjects, places, events, captions,
             instructions, sequence, text };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [single, detail, linksData, selSeqInfo, seqCountById, allPlaces, allEvents,
      selectedItems, itemsById, subjectCatalog, placeCatalog, eventCatalog]);

  const [openTabs, setOpenTabs] = useState<Set<TabId>>(loadOpenTabs);
  useEffect(() => { saveOpenTabs(openTabs); }, [openTabs]);
  // Which tabs the strip leaves out. Deliberately NOT tied to `openTabs`:
  // hiding one only takes its button away, and a hidden tab opened from the ⋯
  // menu still shows its sections — otherwise "can still be opened from the
  // menu" would be a promise the panel breaks.
  const [hiddenTabs, setHiddenTabs] = useState<Set<TabId>>(loadHiddenTabs);
  useEffect(() => { saveHiddenTabs(hiddenTabs); }, [hiddenTabs]);
  const [iconTabs, setIconTabs] = useState<boolean>(loadIconTabs);
  useEffect(() => { saveIconTabs(iconTabs); }, [iconTabs]);
  // The effective open set: drop tabs that aren't currently available, and never
  // show nothing — fall back to General (always available).
  const openSet = useMemo(() => {
    const o = new Set<TabId>([...openTabs].filter((id) => availableTabs.includes(id)));
    if (o.size === 0) o.add("item");
    return o;
  }, [openTabs, availableTabs]);
  // A section drops its own title when its tab is the only one open — the tab
  // above already says the word, and saying it twice over one list is noise.
  // But only while that tab is IN the strip: one hidden by the ⋯ menu can
  // still be opened from there, and then nothing on screen would name what you
  // are looking at.
  const soleTitledTab = useMemo(
    () => openSet.size === 1 && ![...openSet].some((id) => hiddenTabs.has(id)),
    [openSet, hiddenTabs],
  );
  // Which row the tab being jumped to should land on, set by a tag row's
  // person / pin / calendar marker. Switching tabs is only half the jump: a
  // list of eight people leaves you to find the one you clicked all over
  // again. One per tab rather than one shared, because the jump names a tab
  // AND a row, and a stale value on the tab you did not go to would flash
  // something the next time you opened it.
  const [focusSubject, setFocusSubject] = useState<string | null>(null);
  const [focusPlace, setFocusPlace] = useState<string | null>(null);
  const [focusEvent, setFocusEvent] = useState<string | null>(null);
  // The Subjects tab has two things to land on, and they are different rows.
  const [focusFace, setFocusFace] = useState<string | null>(null);
  const pickTab = (id: TabId, additive: boolean) => {
    setOpenTabs((prev) => {
      if (!additive) return new Set<TabId>([id]);
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        if (next.size === 0) next.add(id); // keep at least one open
      } else {
        next.add(id);
      }
      return next;
    });
  };
  const show = {
    item: openSet.has("item"),
    general: openSet.has("general"),
    metadata: openSet.has("metadata"),
    sequence: openSet.has("sequence"),
    ranking: openSet.has("ranking"),
    groups: openSet.has("groups"),
    links: openSet.has("links"),
    tags: openSet.has("tags"),
    subjects: openSet.has("subjects"),
    places: openSet.has("places"),
    events: openSet.has("events"),
    captions: openSet.has("captions"),
    instructions: openSet.has("instructions"),
    text: openSet.has("text"),
  };

  // What the item's events imply, and what its own date implies. Fetched ONCE
  // here rather than in each of the two sections that show half of it: two
  // owners of one key would make the accept/dismiss invalidation ordering
  // matter, for no gain. Only while a tab that SHOWS an offer is open — the
  // Places and Events sections draw them (the Tags list carries the item's
  // tags, which is where accepting one lands), and gating on the Tags tab
  // alone left both sections empty of offers, and Events saying "nothing in
  // particular was happening", whenever Tags happened to be closed.
  const { data: offers, refetch: refetchOffers } = useQuery({
    queryKey: ["item-suggestions", single],
    queryFn: () => api.itemSuggestions(single as number),
    enabled: single != null && (show.tags || show.places || show.events),
  });

  // ---- selecting rows, one selection per TAB -------------------------------
  //
  // Three, not one. They were shared on the argument that every row is a tag
  // assignment and the one action they share is taking it off — but with a tab
  // each, a selection made in Subjects and still counted while Places is
  // showing is a Remove aimed at rows nobody can see.
  //
  // The keys, the three selections, what removing one means and which picks
  // are still a guess — all of it in `usePeopleSelection`, because the
  // ANNOTATOR shows the same three lists and a second copy would be a second
  // dialect of the same rules.
  const afterPeopleEdit = () => {
    qc.invalidateQueries({ queryKey: ["subjects"] });
    qc.invalidateQueries({ queryKey: ["places"] });
    qc.invalidateQueries({ queryKey: ["events"] });
    qc.invalidateQueries({ queryKey: ["faces", single] });
    invalidateAfterTagEdit();
    void refetchOffers();
  };
  const people = usePeopleSelection({
    itemId: single,
    detail: detail ?? null,
    places: allPlaces,
    events: allEvents,
    tab: show.places ? "places" : show.events ? "events"
      : show.subjects ? "subjects" : null,
    onChanged: afterPeopleEdit,
    removeTitle: t("Remove them from this item"),
    // Worth saying, because it is the half that is not just an undo: a guess
    // taken off is remembered as wrong, so the next run stops offering it.
    removeTitleGuessed: t("Remove them from this item, and remember the wrong guesses"),
  });
  const { subjectSel, placeSel, eventSel, sel } = people;

  // WHICH PICTURES IN THE GRID CARRY WHAT IS PICKED HERE. A tag row, a person,
  // a place, an event — each is a tag, and the question a pick raises is the
  // same one every time: which of the pictures on screen have it too. The grid
  // rings them (`tagHighlight`), and it had stopped being told: the write went
  // missing when the tag list moved to the shared row selection, so the ring
  // simply never appeared for anything.
  const setTagHighlight = useUI((s) => s.setTagHighlight);
  const [tagRowHl, setTagRowHl] = useState<TagHl[]>([]);
  const peopleTags = Array.from(people.selectedTags).sort().join(",");
  useEffect(() => {
    const fromPeople: TagHl[] = Array.from(people.selectedTags)
      .map((name) => ({ name, negative: false }));
    const seen = new Set<string>();
    const all = [...tagRowHl, ...fromPeople].filter((h) => {
      const key = `${h.name}:${h.negative}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    setTagHighlight(all);
    // A ring around a card with no row behind it is a highlight nobody can
    // turn off, so it goes when this panel does.
    return () => setTagHighlight([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tagRowHl, peopleTags, setTagHighlight]);

  // ---- the one selection bar ----------------------------------------------
  //
  // The sections keep their own selections and their own idea of what removing
  // means, and REPORT here; the panel renders whichever has something in it.
  // A bar per section would stack them the moment two tabs were open with
  // picks in both. The panel's own (the people/places/events tabs) is not a
  // report — a component cannot consume its own provider — so it is simply
  // preferred when it has anything.
  // The bar MEASURES itself and says how tall it turned out — its buttons wrap
  // under the count in a narrow sidebar, so the inset the content reserves is
  // not a constant. Reserved whether the bar is showing or not, so appearing
  // costs the content no movement.
  const [reports, setReports] = useState<Record<string, SelectionReport | null>>({});
  const report = useCallback((id: string, r: SelectionReport | null) => {
    setReports((all) => (all[id] === r ? all : { ...all, [id]: r }));
  }, []);
  // Every selection in the panel, for the background click: whichever tabs are
  // open, a click on the empty space means "nothing is picked" for all of them.
  const clearPeople = people.clearAll;
  const clearAllSel = useCallback(() => {
    clearPeople();
    for (const r of Object.values(reports)) r?.onClear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reports]);
  // The bar shows whenever a selectable list is on screen — not only once
  // something is picked, and not only once the list has rows: it is where
  // Select all lives, and a control that only appears after you have already
  // done the thing by hand is a control nobody finds. Empty lists report too,
  // so an emptied tab keeps its bar saying "None selected" instead of the
  // bar flicking in and out with the rows.
  const rawBar: SelectionReport | null = (() => {
    // In TAB ORDER, and Sequence leads it — the trap the Links pair records
    // is forgetting to add a section here at all, which leaves a list that
    // selects and a bar that never mentions it.
    // `subjects`/`places`/`events` are the MULTI-selection lists; with one
    // item those three tabs report through `people` instead, and only one of
    // the two shapes is ever on screen.
    // ("files" is the Files tab, whose `TabId` is "general".)
    const rs = ["sequences", "files", "groups", "links", "linked-by", "tags",
                "subjects", "places", "events",
                "captions", "instructions", "text"]
      .map((id) => reports[id]).filter(Boolean) as SelectionReport[];
    // The panel's own three tabs first while they have rows; then, in tab
    // order, a section with something PICKED over one that merely has rows,
    // so the bar never offers "select all" for a list while another one on
    // the same tab is holding a selection. A list with NO rows only ever
    // owns the bar when nothing else on screen has any.
    return (people.report?.total ? people.report : null)
      ?? rs.find((r) => r.count)
      ?? rs.find((r) => r.total)
      ?? people.report
      ?? rs[0]
      ?? null;
  })();
  // The way back from whatever the bar's Remove just did. Wrapped HERE rather
  // than in each of the nine lists: they all remove through this one action,
  // so one interception covers links, groups, tags, tag groups, meta tags,
  // subjects, places, events and captions — and there is no ninth dialect of
  // "and now offer an undo" to keep in step.
  //
  // The offer is scoped to the open tab AND the item: it is about a list you
  // are looking at, and one that outlived either would be a button aimed at
  // rows nobody can see. `useUndoBar` clears on any change to that string.
  const [barH, setBarH] = useState(SELECTION_BAR_H);
  const undoScope = `${[...openSet].sort().join(",")}|${single ?? ""}`;
  // Nothing local to add: `useUndoBar` refreshes everything a revert can
  // touch. This list was hand-written here and copied — differently — into the
  // annotator, which is how one of them came to be missing the links.
  const undo = useUndoBar(undoScope);
  const bar: SelectionReport | null = rawBar && {
    ...rawBar,
    onRemove: () => void undo.run(
      // The label says what, in the words the button used — "Removed 3" reads
      // back the action rather than naming a table.
      `${t(rawBar.removeLabel ?? "Removed")} ${rawBar.count}`,
      async () => { await rawBar.onRemove(); }),
  };

  // WHO THE SELECTION IS, as one node: the editable name for a single item, a
  // count for several. It is handed to the preview where there is one, since
  // collapsed the preview and the name are one row and only the preview knows
  // it is collapsed; where there is none (a sequence, a file-less item, a
  // multi-selection) the panel draws it itself, one block lower.
  // The picture the header shows, and what stands in for it when there is
  // none. A DETAIL STILL LOADING GETS NEITHER — an empty tile says "not yet",
  // where a glyph would state what this is and then be replaced a frame
  // later, which is the flicker the always-rendered header exists to end.
  const previewFileId = single != null && detail && detail.kind !== "sequence"
    ? detail.active_file_id ?? null : null;
  const previewGlyph =
    selectedItems.length > 1 ? "photo_library"
      : detail?.kind === "sequence" ? "collections_bookmark"
        : previewFileId == null && detail ? "hide_image"
          : undefined;
  const nameRow = single != null && detail ? (
    inTrash ? (
      // No renaming in the Trash — show the name read-only, wrapping like the
      // editable one rather than ellipsising: this is the one place the item
      // is named.
      <span style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere",
        lineHeight: 1.35, padding: "3px 0" }}>
        {detail.name}
      </span>
    ) : (
      <EditableItemName
        key={single}
        itemId={single}
        name={detail.name}
        onSaved={() => {
          qc.invalidateQueries({ queryKey: ["item"] });
          qc.invalidateQueries({ queryKey: ["items"] });
          // A sequence item's name is also its sequence name, shown in its
          // members' "belongs to" panels.
          qc.invalidateQueries({ queryKey: ["sequences"] });
        }}
      />
    )
  ) : selectedItems.length === 1 ? (
    "…"
  ) : (
    `${selectedItems.length} items selected`
  );

  return (
    <div
      style={{
        background: "var(--panel)",
        borderLeft: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      {/* Fixed header — the selection nav buttons and the tab bar stay put while
          the tab content below them scrolls. */}
        {/* Back / forward through previous selections (e.g. after following a
            derived/original link), plus a pin to lock the selection. Rendered
            above the selection/placeholder split so the back/forward history nav
            stays available even when nothing is selected. */}
        {(selectedItems.length > 0 || selPast.length > 0 || selFuture.length > 0) && (
          <div style={{ padding: "14px 14px 0" }}>
            <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
              {([
                ["Back to the previous selection", "arrow_back", selPast.length > 0 && !pinnedSelection, selectionBack],
                ["Forward to the next selection", "arrow_forward", selFuture.length > 0 && !pinnedSelection, selectionForward],
              ] as const).map(([title, icon, enabled, onClick]) => (
                <button
                  key={icon}
                  onClick={() => enabled && onClick()}
                  disabled={!enabled}
                  title={title}
                  style={{
                    width: 30, height: 28, borderRadius: "var(--r-3)", display: "flex", alignItems: "center", justifyContent: "center",
                    border: "1px solid var(--border-strong)", background: "var(--panel-2)",
                    color: enabled ? "var(--text-2)" : "var(--muted-3)",
                    cursor: enabled ? "pointer" : "default", opacity: enabled ? 1 : 0.5,
                  }}
                >
                  <Icon name={icon} size={17} />
                </button>
              ))}
              <div style={{ flex: 1 }} />
              {selectedItems.length > 0 && (
                <button
                  onClick={() => showHistoryFor(selectedItems)}
                  title={`Show this selection's changes in the History tab${selectedItems.length > 1 ? ` (${selectedItems.length} items)` : ""}`}
                  style={{
                    width: 30, height: 28, borderRadius: "var(--r-3)", display: "flex", alignItems: "center", justifyContent: "center",
                    border: "1px solid var(--border-strong)", background: "var(--panel-2)",
                    color: "var(--text-2)", cursor: "pointer",
                  }}
                >
                  <Icon name="history" size={16} />
                </button>
              )}
              {selectedItems.length > 0 && (
                <button
                  onClick={togglePinned}
                  title={pinnedSelection
                    ? "Sidebar is pinned to this selection — keep browsing and selecting in the grid; click to unpin and follow the grid again"
                    : "Pin the sidebar to the current selection so it stays put while you browse and select other items in the grid"}
                  style={{
                    width: 30, height: 28, borderRadius: "var(--r-3)", display: "flex", alignItems: "center", justifyContent: "center",
                    border: `1px solid ${pinnedSelection ? "var(--accent)" : "var(--border-strong)"}`,
                    background: pinnedSelection ? "var(--accent-dim)" : "var(--panel-2)",
                    color: pinnedSelection ? "var(--accent)" : "var(--text-2)", cursor: "pointer",
                  }}
                >
                  <Icon name="push_pin" size={15} />
                </button>
              )}
            </div>
          </div>
        )}

        {/* The active file's preview, ABOVE the name and outside the tabs: what
            you are looking at should be visible whichever tab is open, not only
            while the Item tab happens to be. It is pinned like the name and the
            tab bar, so the sections scroll under it — hence the size toggle in
            its bottom-left corner, for when the picture is worth more (or less)
            than the room it takes. Sequences own no preview. */}
        {/* The header — see `RotatablePreview`. Rendered for EVERY selection,
            so it never appears and disappears as the selection moves; what
            it holds is the picture where there is one and the kind's glyph
            where there is not. THE NAME IS ITS TO PLACE: collapsed, the two
            are one row, so which of the two layouts is on screen has to be
            decided where the collapsed state lives. */}
        {selectedItems.length > 0 && (
          <RotatablePreview
            itemId={single}
            fileId={previewFileId}
            glyph={previewGlyph}
            rotation={detail?.rotation ?? 0}
            token={detail?.thumb_token}
            readOnly={inTrash}
            onRotated={() => {
              qc.invalidateQueries({ queryKey: ["item"] });
              qc.invalidateQueries({ queryKey: ["items"] });
              // Rotation bakes a new active file, bumping the Modified date.
              qc.invalidateQueries({ queryKey: ["item-metadata"] });
            }}
            name={nameRow}
          />
        )}

        {/* Item name / selection title — above the tab bar (and thus the scroll
            area) so the current item is always identified while its sections
            scroll. Editable for a single item; a summary for a multi-selection. */}

        {/* Tab bar — fixed above the scroll area, so it stays put while the
            selected item's sections scroll below it. */}
        {selectedItems.length > 0 && (
          <div style={{ padding: "8px 14px 0" }}>
            <SidebarTabs tabs={availableTabs} open={openSet} onPick={pickTab} counts={tabCounts}
                         warn={tabWarn}
                         hidden={hiddenTabs} onHidden={setHiddenTabs}
                         iconsOnly={iconTabs} onIconsOnly={setIconTabs} />
          </div>
        )}

      {/* Scrollable tab content, with the bars FLOATING over its bottom edge.
          The overlay is a sibling of the scroller rather than a child of it —
          absolutely positioned inside a scrolling box would scroll away with
          the rows — and it is absolute rather than sticky because `sticky`
          only ever pulls an element back INTO view: on a panel too short to
          scroll it left both bars sitting under the last row, halfway up the
          sidebar. Absolute at the bottom is the same place whatever the
          content does. The content keeps a reserve below it so the last rows
          can still be scrolled clear of them. */}
      <div style={{ position: "relative", flex: 1, minHeight: 0,
        display: "flex", flexDirection: "column" }}>
      <div
        // BACKGROUND is "not a row and not a control". Identity
        // (`target === currentTarget`) does not work here: each section wraps
        // its rows in divs of its own, so a click in the space beside a row
        // lands on one of those rather than on this. Controls are excluded so
        // that pressing Detect faces, or reaching for the add field, does not
        // quietly put the selection down on the way.
        onMouseDown={(e) => {
          const el = e.target as HTMLElement;
          if (el.closest(ROW_OR_CONTROL)) return;
          clearAllSel();
        }}
        style={{ flex: 1, overflowY: "auto", minHeight: 0, display: "flex", flexDirection: "column" }}>
        {selectedItems.length === 0 ? (
          <div style={{ flex: 1, minHeight: 0 }}>
            <ViewActions />
          </div>
        ) : (
        <SelectionBarSlot report={report}>
        <UndoRunnerSlot run={undo.run}>
        {/* A click that lands on the padding rather than on a row puts the
            selection down — the same escape the Tags tab's crops have, and the
            only one that does not mean aiming at a small button. Every row
            stops its own mousedown by being one, so this only ever fires on
            the background. */}
        <div
          // The reserve grows with the undo bar while it is showing, or the
          // last row ends up under it — the same reason the selection bar has
          // one. Padding on this INNER wrapper, never on the scroller: a
          // sticky `bottom` measures against the scroller's content box, so
          // padding there lifts both bars off the panel's edge by the reserve.
          // AT LEAST the panel's height, so the bars are pinned to the bottom
          // edge even when the list is three rows long. `sticky` does nothing
          // while the content is shorter than the scroll port — the bars sit
          // at their flow position, right under the last row — and that is not
          // just a placement quibble: the undo bar cancels its own height with
          // a negative bottom margin (so it costs the content nothing), which
          // unstuck puts the selection bar straight back on top of it. Filling
          // the height is what makes both `bottom` offsets mean anything.
          // Reserve exactly what floats over it, so the last row can always be
          // scrolled clear of the bars. Permanent for the selection bar (it
          // comes and goes with the selection, and the content must not move
          // when it does) and added for the undo bar only while it is showing.
          style={{ padding: `0 14px ${14 + barH + SELECTION_BAR_GAP
            + (undo.state ? UNDO_BAR_H + 6 : 0)}px` }}>

          {/* THE SECTIONS RENDER IN `TAB_ORDER` — the order the strip draws
              the buttons in — because two lists on screen at once have to
              agree with the row that says which two they are (the
              annotator's SIDE_TABS rule). It is the JSX order and nothing
              else, so a new section goes at its tab's place. */}

          {/* SEQUENCE tab: the sequences the selection belongs to, or — for a
              selected sequence container — its own member list. Keyed off the
              REAL selection, not the sequence-view fallback: when an item is
              deselected while a sequence is open, `selectedItems` falls back to
              the open sequence's container, and gating on that would keep the
              membership section mounted with stale placeholder data. */}
          {show.sequence && (<>
            {!inTrash && baseSelection.length > 0 && (
              <SequenceSection onChange={invalidateAfterGroupEdit}
                hideHeader={soleTitledTab} />
            )}
            {!inTrash && single != null && detail?.kind === "sequence" && detail.sequence_id != null && (
              <SequenceMembersSection
                sequenceId={detail.sequence_id}
                onChange={invalidateAfterGroupEdit}
                hideHeader={soleTitledTab}
              />
            )}
          </>)}

          {/* RANKING tab: where this picture stands on the axis whose view
              you are in. The half of a ranking that SURVIVES a selection —
              the scale, the pools and the caveat are the whole-view panel's,
              and that unmounts the moment a picture is picked, which in a
              ranking view is the primary gesture.

              PAST ONE PICTURE it is the VERBS without the standing: a
              standing is one picture's position and eight of them have
              nothing to say in one line, but "set these aside" is exactly
              what a selection is for — and it was the one thing this panel
              could not do to more than one picture at a time. */}
          {show.ranking && rankingView != null && single != null && (
            <RankingItemSection rankingId={rankingView} itemId={single}
                                hideHeader={soleTitledTab} />
          )}
          {show.ranking && rankingView != null && single == null
            && selectedItems.length > 0 && (
            <div style={{ marginBottom: 18 }}>
              {!soleTitledTab && (
                <label style={{ ...SECTION_LABEL, letterSpacing: "0.04em" }}>
                  Ranking
                </label>
              )}
              <div style={{ marginTop: 8 }}>
                <RankingVerbs rankingId={rankingView} items={selectedItems}
                              count={selectedItems.length}
                              onDone={() => {
                                qc.invalidateQueries({ queryKey: ["ranking-standing"] });
                                qc.invalidateQueries({ queryKey: ["rankings"] });
                                qc.invalidateQueries({ queryKey: ["ranking-detail"] });
                                bumpLibrary();
                              }} />
              </div>
            </div>
          )}

          {/* ITEM tab: name, action buttons, edit/generate sections, video
              tracks. The preview now sits above the name, outside the tabs
              (see above); the source-file list lives in the separate Files
              tab; sequence content in its own tab. */}
          {show.item && (<>
          {/* Trash / sequence action rows: these contexts have no AI actions,
              so their buttons stay above the section actions. */}
          {selectedItems.length > 0 && (inTrash || isSequence) && (
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              {inTrash ? (
                <>
                  <Button variant="soft" size="sm"
          onClick={restoreSelected}
          title="Move the selected items back to their original groups" style={{ flex: 1 }}>
                    <Icon name="restore_from_trash" size={16} />
                    Restore {selectedItems.length}
                  </Button>
                  <Button variant="danger" size="sm"
          onClick={deleteForever}
          title="Permanently delete (cannot be undone)" style={{ flex: "0 0 auto" }}>
                    <Icon name="delete_forever" size={16} />
                  </Button>
                </>
              ) : (
                <>
                  {/* Hide "Open" when this sequence is already the one open in
                      the grid — there's nowhere to navigate to. */}
                  {detail?.sequence_id !== sequenceView && (
                    <Button variant="soft" size="sm"
           onClick={() => detail?.sequence_id != null && showSequence(detail.sequence_id)}
           title="Open this sequence and view its pages" style={{ flex: 1 }}>
                      <Icon name="folder_open" size={16} />
                      Open
                    </Button>
                  )}
                  <Button variant="danger" size="sm"
          onClick={removeSequenceItem}
          title="Delete the sequence (its images stay in the library)" style={{ flex: 1 }}>
                    <Icon name="playlist_remove" size={16} />
                    Remove
                  </Button>
                </>
              )}
            </div>
          )}

          {/* Edit image / video (single item) — sits directly above the
              Hide/Delete row. Opens the image or video editor in a new window. */}
          {single != null && !inTrash && !isSequence && (
            <Button variant="soft" size="sm" block justify="start"
       onClick={() => openEditor(single)} style={{ marginTop: 10 }}>
              <Icon name={detail?.kind === "video" ? "movie_edit" : "edit"} size={16} />
              {detail?.kind === "video" ? t("Edit video") : t("Edit image")}
            </Button>
          )}

          {/* Annotate — the other own-window editor, so it belongs beside the
              first rather than only at the top of the Tags section, where it
              is easy to miss when you came to this tab to open something. */}
          {single != null && !inTrash && !isSequence && (
            <Button variant="soft" size="sm" block justify="start"
       onClick={() => openAnnotator(single)} style={{ marginTop: 6 }}>
              <Icon name="ads_click" size={16} />
              {t("Annotate")}
            </Button>
          )}

          {/* Merge — two or more selected, none of them a sequence. Sits
              directly above the Hide/Delete row. It is a SELECTION's verb, so
              it is not among the whole-view actions: "merge everything in this
              view into one item" is not a thing anybody means. */}
          {selectedItems.length >= 2 && !inTrash && !selectionHasSequence && (
            <Button variant="soft" size="sm" block
       onClick={mergeSelected}
       title="Combine the selected items into one — all files, groups, tags and captions are merged into the first" style={{ marginTop: 10 }}>
              <Icon name="merge" size={16} />
              {t("Merge into one item")} ({selectedItems.length})
            </Button>
          )}

          {/* Create sequence — group a multi-selection into an ordered sequence.
              Sits above the Hide/Delete row (moved out of the Sequence section). */}
          {selectedItems.length >= 2 && !inTrash && (
            <Button variant="soft" size="sm" block
       onClick={createSequenceFromSelection}
       title="Group the selected items into an ordered sequence" style={{ marginTop: 10 }}>
              <Icon name="format_list_numbered" size={16} />
              {t("Create sequence")} ({selectedItems.length})
            </Button>
          )}

          {/* REMOVE FROM SEQUENCE — only while that sequence is the open
              view, where "this sequence" is the one on screen. It takes the
              OCCURRENCES the selection gesture NAMED (the grid's primary,
              solid-ring copies — `selMembers`): a repeated page picked at
              rank 17 comes out at 17 and stays at 3, because 17 is the copy
              you pointed at. An item whose selection named no occurrence (a
              link pick, the menu's Preview) falls back to all of its copies —
              there every copy is primary. The items stay in the library,
              which is why it sits above the trash row rather than among the
              destructive verbs. The secondary text is those occurrences'
              ranks in the reading order — the same numbers the grid badges
              show. */}
          {sequenceView != null && selectedItems.length > 0 && !inTrash
            && !isSequence && (() => {
            const members = openSeq?.members ?? [];
            const selSet = new Set(selectedItems);
            // Which selected items have a NAMED occurrence in this sequence.
            const namedItems = new Set<number>();
            for (const m of members) {
              if (selSet.has(m.item_id) && selMembers.has(m.id)) {
                namedItems.add(m.item_id);
              }
            }
            const memberIds: number[] = [];
            const ranks: number[] = [];
            members.forEach((m, i) => {
              if (!selSet.has(m.item_id)) return;
              if (namedItems.has(m.item_id) && !selMembers.has(m.id)) return;
              memberIds.push(m.id);
              ranks.push(i + 1);
            });
            if (memberIds.length === 0) return null;
            const rankText = ranks.length > 8
              ? `${ranks.slice(0, 8).join(", ")}, … / ${members.length}`
              : `${ranks.join(", ")} / ${members.length}`;
            const remove = async () => {
              await api.removeSequenceMembers(sequenceView, memberIds);
              qc.invalidateQueries({ queryKey: ["sequence"] });
              qc.invalidateQueries({ queryKey: ["sequences"] });
              for (const id of selectedItems) bumpItem(id);
              bumpEdits();
            };
            return (
              <div style={{ marginTop: 10 }}>
                <Button variant="soft" size="sm" block
         onClick={() => void remove()}
         title={t("Take the selection out of this sequence — the items stay in the library")}>
                  <Icon name="playlist_remove" size={16} />
                  {t("Remove from sequence")}
                  <span style={{
                    fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                    color: "var(--muted-2)", fontWeight: 400,
                  }}>{rankText}</span>
                </Button>
              </div>
            );
          })()}

          {/* Hide/Show + Delete — directly below the name (outside the Trash and
              single sequences, which have their own rows above). Hide moves the
              selection out of the grid and counts (non-destructive); Show brings
              it back. */}
          {selectedItems.length > 0 && !inTrash && !isSequence && (() => {
            const n = selectedItems.length;
            // Fall back to `hiddenView` only when an item's real state is
            // unknown (not in the grid cache, no detail yet) — NOT as an
            // override. Forcing isHidden=true in the Hidden view meant that
            // after pressing Show the button never flipped back to Hide.
            const effHidden = (id: number) =>
              hiddenOverride[id] ?? hiddenById.get(id) ?? hiddenView;
            const isHidden =
              (single != null && detail != null)
                ? (hiddenOverride[single] ?? detail.hidden) === true
                : selectedItems.every((id) => effHidden(id) === true);
            return (
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <Button variant="soft" size="sm"
         onClick={() => setHidden(!isHidden)}
         title={isHidden
          ? "Reveal — bring the selection back into the grid and counts"
          : "Hidden items are kept in the library but excluded from the grid and category counts; links to them still work."} style={{ flex: 1 }}>
                  <Icon name={isHidden ? "visibility" : "visibility_off"} size={16} />
                  {isHidden ? (n > 1 ? `${t("Show")} ${n}` : t("Show")) : (n > 1 ? `${t("Hide")} ${n}` : t("Hide"))}
                </Button>
                <Button variant="danger" size="sm"
         onClick={trashSelected}
         title={t("Move to Trash — it can be restored from there")} style={{ flex: 1 }}>
                  <Icon name="delete" size={16} />
                  {/* SAYS WHAT IT DOES. It was "Delete", which is the word
                      people expect to be irreversible — and this is the
                      reversible one: the items go to the Trash and the Trash
                      is where they are deleted from. */}
                  {n === 1 ? t("Move to trash") : `${t("Move to trash")} ${n}`}
                </Button>
              </div>
            );
          })()}

          {/* Edit — Remove background/watermark, upscale, restore, colorize.
              Every one of these hands back a new source file of the SAME item,
              which is what the section means; splitting and detecting have
              their own sections below because they do not. Still images only.
              (Edit image / Merge / Create sequence live above the Hide/Delete
              row; captioning/tagging at the top of their tabs.) */}
          {selectedItems.length > 0 && !inTrash && !isSequence
            && !selectionHasSequence && !selectionHasVideo && (
            <CollapsibleSection title="Edit" sk="actions">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {/* Removing the background is its own button: it is the one
                    people reach for by name, and burying it in a menu with the
                    inpainting removers cost a click every time. */}
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["bg_removal"]}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
                {/* The inpainting removers — watermark and text — are TWO
                    buttons (they shared a combined "Remove elements" menu for
                    a round, which put them out of step with the whole-view
                    panel and both context menus, where they are separate).
                    Each has TWO ways in, and the pair is symmetric: a
                    box-driven variant that paints out the boxes on the tag
                    Settings → Tagging names for that thing (offered only
                    while this image actually carries that tag with boxes —
                    over an item with none it would paint out nothing), and a
                    reading-driven one. Text removal's reading is the TEXT
                    TAB, so its own model is offered only once something has
                    been read, with a "detect and remove" entry per engine
                    that has not read this file. */}
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["watermark_removal"]}
                  hideModelIds={hasBoxesOn(wmTag) ? [] : ["yolo11x_lama:boxes"]}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["text_removal"]}
                  hideModelIds={[
                    ...(hasBoxesOn(textTag) ? [] : ["lama_regions:boxes"]),
                    // Nothing read on this file: painting out no regions
                    // changes nothing, so offer the reading engines instead.
                    ...(single != null && !(detail?.text_count ?? 0)
                      ? ["lama_regions"] : []),
                  ]}
                  extraModels={detectAndRemove}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["upscale", "restore"]}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["colorize"]}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["descreen"]}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
              </div>
            </CollapsibleSection>
          )}

          {/* Detect — actions that FIND something in the picture rather than
              altering it. Neither hands back a new source file the way Edit's
              do: panels become items of their own, faces become records to be
              named in the Subjects tab.

              A SEQUENCE of still images gets the same section: a comic chapter
              is the natural thing to ask both questions of, and the two answer
              it differently on purpose. Panels takes the sequence itself and
              collects every page's panels into one new sequence; faces has
              nothing to read on a container, so the queue runs it over the
              pages — the same as selecting them all. Videos and mixed
              selections have no still to work on at all. */}
          {selectedItems.length > 0 && !inTrash && !selectionHasVideo
            && (isSequence ? single != null && seqAllImages
                : selectionAllSequences ? seqsAllImages
                : !selectionHasSequence) && (
            <CollapsibleSection title="Detect" sk="detect-actions">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <AiActionButtons
                  itemIds={isSequence && single != null ? [single] : selectedItems}
                  kinds={["panels"]}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
                {/* Faces, text and watermarks are HERE AND on the tabs that
                    show what they found — this tab is the complete list of
                    what can be done to the selection, which is what it is
                    for and what makes it match the whole-view panel, and
                    the button at the head of Subjects, Text or Tags is the
                    same action offered where you are already looking. Two
                    doors onto one action is right when one of them is the
                    index. */}
                <AiActionButtons
                  itemIds={isSequence && single != null ? [single] : selectedItems}
                  kinds={["faces"]}
                  doneModels={detail?.face_models ?? []}
                  onEnqueued={() => {
                    qc.invalidateQueries({ queryKey: ["ml-jobs"] });
                    qc.invalidateQueries({ queryKey: ["faces"] });
                  }}
                />
                {/* OCR is a batch kind like faces, so a sequence here means
                    its pages — which is the run anybody actually wants: read
                    the whole chapter. */}
                <AiActionButtons
                  itemIds={isSequence && single != null ? [single] : selectedItems}
                  kinds={["ocr"]}
                  doneModels={detail?.text_models ?? []}
                  onEnqueued={() => {
                    qc.invalidateQueries({ queryKey: ["ml-jobs"] });
                    qc.invalidateQueries({ queryKey: ["text"] });
                  }}
                />
                {/* What it finds lands as BOXES on the configured watermark
                    tag (Settings → Tagging) — exactly what the box-driven
                    removal in Edit consumes, which is what makes
                    detect-then-remove one reviewable workflow. */}
                <AiActionButtons
                  itemIds={isSequence && single != null ? [single] : selectedItems}
                  kinds={["watermark_detect"]}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
              </div>
            </CollapsibleSection>
          )}

          {/* Generate — what is MADE from the picture and was not in it: its
              tags, its caption, and the ControlNet control-image estimators
              (depth, pose, and edges — Canny + line art in one menu). The
              control images are stored as artifacts nested under the item's
              source file (see the Files section); the ml-jobs poll
              invalidates the item on completion so they appear there.

              Tags and captions are here AND at the head of their own tabs,
              for the Detect section's reason: this tab is the complete list
              of what can be done to the selection, and the tab's own button
              is the same action offered where you are already looking.
              Still images only. */}
          {selectedItems.length > 0 && !inTrash && !isSequence
            && !selectionHasSequence && !selectionHasVideo && (
            <CollapsibleSection title="Generate" sk="artifact-actions">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["tag"]}
                  onEnqueued={onAiEnqueued}
                />
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["caption"]}
                  onEnqueued={onAiEnqueued}
                />
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["depth"]}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["pose"]}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
                <AiActionButtons
                  itemIds={selectedItems}
                  kinds={["canny", "lineart"]}
                  combined={{ label: "Estimate Edges", icon: "show_chart" }}
                  onEnqueued={() => qc.invalidateQueries({ queryKey: ["ml-jobs"] })}
                />
              </div>
            </CollapsibleSection>
          )}

          </>)}

          {/* FILES tab: the source-file list (imported file variants) only.
              Sequences own no files, so the tab is hidden for them. */}
          {show.general && single != null && detail && detail.kind !== "sequence" && (
            <FilesSection
              itemId={single}
              files={detail.files}
              readOnly={inTrash}
              hideHeader={soleTitledTab}
              onChange={() => {
                qc.invalidateQueries({ queryKey: ["item"] });
                qc.invalidateQueries({ queryKey: ["items"] });
                qc.invalidateQueries({ queryKey: ["library-stats"] });
                // The metadata panel's intrinsic fields (dimensions, format,
                // resolution) come from the active file, so refresh it too when
                // the active source file changes.
                qc.invalidateQueries({ queryKey: ["item-metadata"] });
                // A text reading is per FILE, so the Text tab's tree and
                // badge follow the active file too.
                qc.invalidateQueries({ queryKey: ["text"] });
              }}
            />
          )}

          {/* INFO tab: dimensions/resolution + EXIF for images, length/frame
              rate/bitrate/audio for videos, uid/member count/dates for sequence
              containers. Rows are filterable via their hover button (except the
              purely informational ones). The section header is hidden when it is
              the sole open tab (the tab label already names it). */}
          {show.metadata && single != null && detail && (
            <MetadataSection itemId={single} uid={detail.uid} hideHeader={soleTitledTab} />
          )}
          {/* Video/audio/subtitle/attachment streams — under Info (moved from
              the Item tab), with the shared expandable per-track view. */}
          {show.metadata && single != null && detail?.kind === "video" && <TracksSection itemId={single} />}

          {/* LINKS tab: the versions this one derives from / is linked by.
              With SEVERAL items picked the two lists aggregate instead — the
              tab was offered for any selection and rendered for one item, so
              it was an empty tab with no way to add anything. */}
          {show.links && (<>
          {/* Links: the versions derived from this one (outgoing), then the
              items this one is derived from / linked by (incoming). */}
          {single != null ? (<>
            <RelatedSection
              itemId={single}
              incoming={false}
              hideHeader={soleTitledTab}
              onOpen={(id) => setSelectedItems([id])}
              onSelect={(ids) => setSelectedItems(ids)}
              onItemsChanged={afterItemsChanged}
              onChange={invalidateAfterLinkEdit}
            />
            <RelatedSection
              itemId={single}
              incoming={true}
              onOpen={(id) => setSelectedItems([id])}
              onSelect={(ids) => setSelectedItems(ids)}
              onItemsChanged={afterItemsChanged}
              onChange={invalidateAfterLinkEdit}
            />
          </>) : selectedItems.length > 0 ? (<>
            <MultiLinksSection
              itemIds={selectedItems}
              incoming={false}
              hideHeader={soleTitledTab}
              onOpen={(id) => setSelectedItems([id])}
              onChange={invalidateAfterLinkEdit}
            />
            <MultiLinksSection
              itemIds={selectedItems}
              incoming={true}
              onOpen={(id) => setSelectedItems([id])}
              onChange={invalidateAfterLinkEdit}
            />
          </>) : null}
          </>)}

          {/* GROUPS tab: the groups the selected image(s) belong to. In the
              Trash this instead shows where the item will be restored to. Skipped
              for very large selections (too slow to aggregate). */}
          {show.groups && selectedItems.length <= HEAVY_SELECTION && (
            <GroupsSection
              itemIds={selectedItems}
              single={single}
              detail={single != null ? detail ?? null : null}
              itemsById={itemsById}
              allGroups={allGroups ?? []}
              inTrash={inTrash}
              restoreGroups={single != null ? detail?.restore_groups ?? [] : []}
              hideHeader={soleTitledTab}
              onChange={invalidateAfterGroupEdit}
            />
          )}

          {/* TAGS tab: a single item shows tags organized into groups; a
              multi-selection uses the flat aggregate editor; a very large
              selection is too slow to aggregate, so it points to Quick Assign. */}
          {show.tags && (
            selectedItems.length > HEAVY_SELECTION ? (
              <HeavySelectionNote count={selectedItems.length} />
            ) : single != null && detail ? (
              <GroupedTags
                itemId={single}
                detail={detail}
                fetchSuggestions={fetchTagSuggestions}
                readOnly={inTrash}
                topAction={genTagsButton}
                // Headerless when it is the only tab open, like every other
                // section: the tab above already says "Tags", and repeating it
                // over the one list on screen says it twice. The comment this
                // replaces was written when the Tags tab held four lists —
                // there an unlabelled one above three labelled ones read as
                // part of the first of them, which is no longer the shape.
                hideHeader={soleTitledTab}
                // The people are in this same tab, a scroll away — so the
                // marker only says WHICH one to land on.
                // The tab, AND the row in it. `face` goes to the same tab as
                // `subject` but aims at the crop — "where is she in this
                // picture" is a different row from the one naming her.
                onShowKind={(what, tag) => {
                  if (what === "place") { setFocusPlace(tag); pickTab("places", false); }
                  else if (what === "event") { setFocusEvent(tag); pickTab("events", false); }
                  else {
                    if (what === "face") setFocusFace(tag); else setFocusSubject(tag);
                    pickTab("subjects", false);
                  }
                }}
                onHighlight={setTagRowHl}
                onChange={invalidateAfterTagEdit}
              />
            ) : (
              <AssignedTags
                itemIds={selectedItems}
                single={single}
                detail={single != null ? detail ?? null : null}
                itemsById={itemsById}
                fetchSuggestions={fetchTagSuggestions}
                readOnly={inTrash}
                topAction={genTagsButton}
                hideHeader={soleTitledTab}
                onChange={invalidateAfterTagEdit}
              />
            )
          )}

          {/* WHO, WHERE and WHEN — a tab each, because each is a list of its
              own with a count of its own, and the three are different
              questions rather than three views of one. They share the row
              SELECTION regardless: the rows are all tag assignments on this
              item and the one action they share is taking them off, so the
              toolbar above them is the same toolbar wherever it appears. */}
          {/* Who is in the picture. ONE section, faces included: the faces and
              the people were two lists answering the same question from two
              ends, and neither could say that a face is several people. */}
          {show.subjects && single == null && selectedItems.length > 0 && (
            <CollapsibleSection title="Subjects" sk="subjects"
              hideHeader={soleTitledTab}>
              <MultiKindTags kind="subject" itemIds={selectedItems}
                itemsById={itemsById} catalog={subjectCatalog}
                topAction={inTrash ? null : detectFacesButton}
                readOnly={inTrash} onChange={invalidateAfterTagEdit} />
            </CollapsibleSection>
          )}
          {show.subjects && single != null && detail && (
            <CollapsibleSection title="Subjects" sk="subjects"
              hideHeader={soleTitledTab}>
              <PeopleSection
                itemId={single}
                detail={detail}
                sel={subjectSel}
                topAction={annotateAnd("subjects",
                  detail.kind !== "sequence" ? detectFacesButton : null)}
                focusTag={focusSubject}
                focusFace={focusFace}
                onFocused={() => { setFocusSubject(null); setFocusFace(null); }}
                onChange={invalidateAfterTagEdit}
              />
            </CollapsibleSection>
          )}
          {/* `sk` stays "locations": it is the persisted collapsed state, not
              a label, and changing it would silently re-expand the section for
              everyone who had closed it. */}
          {show.places && single == null && selectedItems.length > 0 && (
            <CollapsibleSection title="Places" sk="locations"
              hideHeader={soleTitledTab}>
              <MultiKindTags kind="place" itemIds={selectedItems}
                itemsById={itemsById} catalog={placeCatalog}
                readOnly={inTrash} onChange={invalidateAfterTagEdit} />
            </CollapsibleSection>
          )}
          {show.places && single != null && detail && (
            <CollapsibleSection title="Places" sk="locations"
              hideHeader={soleTitledTab}>
              {annotateAnd("places", null)}
              <PlacesSection
                itemId={single}
                detail={detail}
                sel={placeSel}
                suggested={offers?.places ?? []}
                filePlace={offers?.file_place ?? null}
                focusTag={focusPlace}
                onFocused={() => setFocusPlace(null)}
                onChange={invalidateAfterTagEdit}
                onAnswered={refetchOffers}
              />
            </CollapsibleSection>
          )}
          {show.events && single == null && selectedItems.length > 0 && (
            <CollapsibleSection title="Events" sk="events"
              hideHeader={soleTitledTab}>
              <MultiKindTags kind="event" itemIds={selectedItems}
                itemsById={itemsById} catalog={eventCatalog}
                readOnly={inTrash} onChange={invalidateAfterTagEdit} />
            </CollapsibleSection>
          )}
          {show.events && single != null && detail && (
            <CollapsibleSection title="Events" sk="events"
              hideHeader={soleTitledTab}>
              {annotateAnd("events", null)}
              <EventsSection
                itemId={single}
                detail={detail}
                sel={eventSel}
                suggested={offers?.events ?? []}
                dated={offers?.dated ?? true}
                focusTag={focusEvent}
                onFocused={() => setFocusEvent(null)}
                onChange={invalidateAfterTagEdit}
                onAnswered={refetchOffers}
              />
            </CollapsibleSection>
          )}

          {/* CAPTIONS tab — the item's own list for one, the two counts and
              the two bulk verbs for several (`MultiCaptions` says why). */}
          {show.captions && selectedItems.length <= 1 && (
            <CaptionsSection
              itemId={single}
              captions={single != null ? detail?.captions ?? null : null}
              multi={false}
              readOnly={inTrash}
              topAction={annotateAnd("captions", genCaptionButton)}
              hideHeader={soleTitledTab}
              onChange={invalidateAfterCaptionEdit}
            />
          )}
          {show.captions && selectedItems.length > 1 && (
            <MultiCaptions
              kind="caption"
              itemIds={selectedItems}
              slims={multiSlims?.items ?? null}
              readOnly={inTrash}
              topAction={genCaptionButton}
              hideHeader={soleTitledTab}
              onChange={invalidateAfterCaptionEdit}
            />
          )}

          {/* INSTRUCTIONS tab — the same rows of the other kind. No Generate
              button: nothing writes an instruction for you. */}
          {show.instructions && selectedItems.length <= 1 && (
            <CaptionsSection
              itemId={single}
              captions={single != null ? detail?.captions ?? null : null}
              kind="instruction"
              multi={false}
              readOnly={inTrash}
              hideHeader={soleTitledTab}
              onChange={invalidateAfterCaptionEdit}
            />
          )}
          {show.instructions && selectedItems.length > 1 && (
            <MultiCaptions
              kind="instruction"
              itemIds={selectedItems}
              slims={multiSlims?.items ?? null}
              readOnly={inTrash}
              hideHeader={soleTitledTab}
              onChange={invalidateAfterCaptionEdit}
            />
          )}

          {/* TEXT tab — what the picture SAYS (detected text). The panel
              owns the CollapsibleSection wrapper because the annotator
              renders the same component under its own sideTitle. */}
          {show.text && single != null && detail && (
            <CollapsibleSection title="Text" sk="text"
                                hideHeader={soleTitledTab}>
              <TextSection
                itemId={single}
                detail={detail}
                readOnly={inTrash}
                topAction={annotateAnd("text", detectTextButton)}
                onChange={() => {
                  // The badge and the tick-list live on the item detail;
                  // tags and subjects have nothing to do with text.
                  qc.invalidateQueries({ queryKey: ["item", single] });
                  bumpEdits();
                }}
              />
            </CollapsibleSection>
          )}
          {show.text && selectedItems.length > 1 && (
            <MultiText
              itemIds={selectedItems}
              slims={multiSlims?.items ?? null}
              topAction={detectTextButton}
              hideHeader={soleTitledTab}
            />
          )}
        </div>
        </UndoRunnerSlot>
        </SelectionBarSlot>
        )}
      </div>

      {/* Inset to the rows' own 14 px. `pointerEvents: none` on the frame so
          the gap between the bars is not a dead strip over the list — each bar
          takes its own clicks back. */}
      {selectedItems.length > 0 && (undo.state || bar) && (
        <div style={{ position: "absolute", left: 14, right: 14,
          bottom: SELECTION_BAR_GAP, zIndex: 5, pointerEvents: "none" }}>
          {undo.state && (
            <UndoBar
              label={undo.state.label}
              undone={undo.state.undone}
              onToggle={() => void undo.toggle()}
              onDismiss={undo.dismiss}
              t={t}
              style={{ pointerEvents: "auto" }}
            />
          )}
          {/* LONGHANDS, not `margin: 0`: the floating variant sets
              `marginBottom` to minus its own height (its way of costing the
              scroll content nothing), and a shorthand handed to React
              alongside a longhand does not reliably win. In here it must take
              its real height, or it hangs out of the overlay. */}
          {bar && <SelectionBar {...bar} t={t} floating onHeight={setBarH}
                                style={{ position: "static", marginTop: 0,
                                         marginBottom: 0, pointerEvents: "auto" }} />}
        </div>
      )}
      </div>

      {/* In the Trash the Quick Assign panel is replaced by an Empty Trash
          action; otherwise it's pinned to the bottom, collapsible. */}
      {trashView ? (
        <EmptyTrashBar onEmptied={afterItemsChanged} />
      ) : (
        <QuickAssign />
      )}
    </div>
  );
}

/** WHAT THE SIDEBAR IS ABOUT WITH NOTHING SELECTED: everything in the view.
 *
 *  It used to be about nothing — a big grey icon and a line telling you to go
 *  and select something. But the sidebar is where an action on a set of items
 *  lives, and "the set I am looking at" is a set: the Quick Assign bar at the
 *  foot of this panel has stamped a whole view for a while, and the group
 *  tree's context menu runs models over a whole group. This is that offer for
 *  the grid's own scope.
 *
 *  **THE IDS NEVER COME HERE.** A view can be the entire library, so what
 *  travels to the server is the grid's own search body (`useViewScope`, which
 *  reads page 1 under the grid's own query key — so it costs nothing while a
 *  grid is on screen) and the server resolves it, in committed chunks. The
 *  count in the header and the strip of pictures are the same read: the total
 *  the grid already asked for, and its first page.
 *
 *  Everything destructive says HOW MANY before it runs, and the two that
 *  cannot be undone are not here at all: permanently deleting a library's
 *  worth of pictures stays the Trash's own button, where what is about to go
 *  can be looked at first.
 */
function ViewActions() {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const errText = useErrText();
  const trashView = useUI((s) => s.trashView);
  const rankingView = useUI((s) => s.rankingView);
  const rankingPool = useUI((s) => s.rankingPool);
  const rankedView = useUI((s) => s.rankedView);
  const view = useViewScope();
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [group, setGroup] = useState<number | null>(null);
  const { data: tree } = useQuery({ queryKey: ["groups"], queryFn: api.groups });
  const total = view.total;
  const scope = useMemo(
    () => ({ body: view.req, total }), [view.req, total]);

  // An inline line in the panel, not a toast: it sits under the buttons that
  // made it, so it keeps its own timer.
  useEffect(() => {
    if (!note) return;
    const id = setTimeout(() => setNote(null), 5000);
    return () => clearTimeout(id);
  }, [note]);

  // A WHOLE-VIEW WRITE TOUCHES ITEMS THIS PAGE HAS NEVER HEARD OF, so the
  // library sweep is what refreshes the grid — bumping the loaded ids would
  // refresh the handful that happen to be on screen and leave the rest
  // stale. (The quick-assign bar learned this first.)
  const run = async (what: () => Promise<{ count: number; total: number }>,
                     say: (n: number) => string) => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await what();
      bumpLibrary();
      bumpEdits();
      setNote(say(r.count));
    } catch (e) {
      setNote(errText(e));
    } finally {
      setBusy(false);
    }
  };

  // THE RANKINGS INDEX HOLDS NO ITEMS, so none of this is about anything:
  // it shows a card per ranking, and a panel offering to hide or trash "7
  // items" beside three cards would be claiming a scope that is not on
  // screen. What it says instead is the way on.
  if (rankedView) {
    return (
      <div style={{ height: "100%", minHeight: 260, padding: "40px 28px",
                    display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center",
                    textAlign: "center", gap: 12, color: "var(--muted-2)" }}>
        <Icon name="leaderboard" size={46} color="var(--muted-3)" />
        <div style={{ fontSize: "var(--fs-4)", fontWeight: 600, color: "var(--muted)" }}>
          {t("Rankings")}
        </div>
        <div style={{ fontSize: "var(--fs-3)", lineHeight: 1.5, maxWidth: 210 }}>
          {t("Open one to see what it placed, and what can be done to it.")}
        </div>
      </div>
    );
  }

  // Nothing to act on — and nothing to explain either, because an empty view
  // is its own answer. The Trash keeps the plain placeholder too: its one
  // whole-view action is Empty Trash, which is the bar at the foot of this
  // panel, and every action here means something else in there.
  //
  // A RANKING IS THE EXCEPTION, and it is the one view where empty has
  // something to say: a ranking somebody has just made has placed nothing,
  // and "nothing here" is the wrong answer to "why is this empty" when the
  // right one is "go and compare some pairs". So the scope panel below draws
  // for a ranking whatever its total.
  if (trashView || (total === 0 && rankingView == null))
    return <NoSelectionPlaceholder />;

  const onEnqueued = () => qc.invalidateQueries({ queryKey: ["ml-jobs"] });
  // A model reads a PICTURE. The view's kinds are not knowable without
  // enumerating it, so the server drops what it cannot run over
  // (`jobs._only_pictures`) and the buttons stay offered — the alternative is
  // hiding an action because the view MIGHT hold a film.
  const ai = (kinds: JobKind[]) => (
    <AiActionButtons itemIds={[]} scope={scope} kinds={kinds}
                     onEnqueued={onEnqueued} />
  );

  const groupName = group == null ? ""
    : flattenGroupTree(tree ?? []).find((o) => o.id === group)?.name ?? "";

  return (
    <div style={{ padding: "16px 14px 20px", display: "flex",
                  flexDirection: "column", gap: 16 }}>
      {rankingView != null && (
        <RankingScopeCard id={rankingView} pool={rankingPool}
                          scope={view.req} total={total} />
      )}
      {/* WHICH items, before what can be done to them — as a COUNT and a
          sentence, not as pictures. A strip of the first page's thumbnails
          was tried here and removed: over a view of any size it can only
          ever show a handful, so it read as "these ones" for an action that
          lands on all of them, and it spent the top of the panel saying
          less than the number does. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text)" }}>
          {t("Everything in this view")}
        </div>
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          {total == null ? t("Counting…")
            : tn({ one: "{n} item · nothing selected",
                   other: "{n} items · nothing selected" }, total)}
        </div>
        {/* WHAT AN ACTION JUST DID goes here, not at the foot of the panel:
            below the buttons it sits under the Quick Assign bar on any real
            window, so the count of what had been written had to be scrolled
            to. (A sentence explaining the scope stood here too and is gone —
            the heading and the count say it, and a paragraph of grey text
            over four sections says it a second time.) */}
        {note && (
          <div style={{ fontSize: "var(--fs-2)", color: "var(--text-2)",
                        background: "var(--accent-dim)", borderRadius: "var(--r-4)",
                        padding: "8px 10px" }}>
            {note}
          </div>
        )}
      </div>

      {/* THE TWO THAT CHANGE WHAT IS THERE, in a block of their own, behind
          a rule and asking first. Hiding is reversible from the Hidden view
          and trashing from the Trash, which is exactly why they can be
          offered over a scope nobody has enumerated — and why the permanent
          delete is not here at all.

          FIRST, not last. They are what a narrowed view is most often
          narrowed FOR — a search, then get rid of what it found — and below
          three sections of model runs they were a scroll away from the count
          that says how many they are about. The RULE is under them here
          rather than over them: it separates them from the runs that follow,
          where at the foot it separated them from what came before.

          NO HEADING: the panel's own header already says "Everything in this
          view", and a section repeating it four rows down read as a second,
          narrower scope. The single-selection row these two mirror carries no
          heading either — the rule is what separates them. */}
      <ViewSection rule="below">
        <div style={{ display: "flex", gap: 6 }}>
          <button
            disabled={busy || total == null}
            onClick={async () => {
              if (!(await confirm({
                title: tn({ one: "Hide 1 item?", other: "Hide {n} items?" }, total ?? 0),
                answer: { label: t("Hide") },
              }))) return;
              void run(() => api.viewHide(view.req, true),
                       (n) => tn({ one: "Hid 1 item", other: "Hid {n} items" }, n));
            }}
            style={{ ...viewBtn, flex: 1, opacity: busy ? 0.5 : 1 }}
          >
            <Icon name="visibility_off" size={14} /> {t("Hide")}
          </button>
          <button
            disabled={busy || total == null}
            onClick={async () => {
              if (!(await confirm({
                title: tn({ one: "Move 1 item to the Trash?",
                            other: "Move {n} items to the Trash?" }, total ?? 0),
                answer: { label: t("Move to Trash"), danger: true },
              }))) return;
              void run(() => api.viewTrash(view.req),
                       (n) => tn({ one: "Moved 1 item to the Trash",
                                   other: "Moved {n} items to the Trash" }, n));
            }}
            style={{ ...viewBtn, flex: 1, opacity: busy ? 0.5 : 1,
                     color: "var(--red-text)",
                     borderColor: "var(--red)" }}
          >
            <Icon name="delete" size={14} /> {t("Trash")}
          </button>
        </div>
      </ViewSection>

      {/* THE SAME SECTIONS A SELECTION GETS, UNDER THE SAME HEADINGS. They
          were the batch kinds only for a round (the ones that become ONE job
          with a progress bar), and "which actions batch" is the wrong line to
          draw in a menu: the answer a person wants from "everything in this
          view" is all of them, and what the per-item kinds cost is a QUESTION
          before they queue (`VIEW_RUN_CONFIRM`), not an action that is
          missing.

          THREE SECTIONS, and they are the two context menus' — one table
          (`app/actionSections.ts`) so a menu cannot disagree with this
          panel — grouped by what an action LEAVES BEHIND: a new source file
          (Edit), something FOUND in the picture (Detect), something MADE
          from it that was not in it (Generate). A SELECTION reaches most of
          these through the tab that shows what they found instead; this
          panel and a context menu are the two places with no tabs to put
          them in.

          `skip_done` rides on faces, text and watermarks server-side: over a
          whole library, re-running what a model has already seen is the
          difference between minutes and hours, and only those kinds record
          it.

          What is still absent is absent for a reason the sidebar can state:
          Adjustments is a live editor panel rather than a job, and Merge,
          Create sequence and Annotate each name a specific small set. */}
      <ViewSection title={t("Edit")}>
        {ai(["bg_removal"])}
        {ai(["watermark_removal", "text_removal"])}
        {ai(["upscale"])}
        {ai(["restore"])}
        {ai(["colorize"])}
        {ai(["descreen"])}
      </ViewSection>

      <ViewSection title={t("Detect")}>
        {ai(["panels"])}
        {ai(["faces"])}
        {ai(["ocr"])}
        {ai(["watermark_detect"])}
      </ViewSection>

      <ViewSection title={t("Generate")}>
        {ai(["tag"])}
        {ai(["caption"])}
        {ai(["depth"])}
        {ai(["pose"])}
        {ai(["canny", "lineart"])}
      </ViewSection>

      <ViewSection title={t("Groups")}>
        <GroupSelect tree={tree ?? []} value={group}
                     onChange={setGroup}
                     ungroupedLabel={t("Pick a group…")}
                     ungroupedIcon="folder" />
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <button
            disabled={busy || group == null}
            onClick={() => void run(
              () => api.viewGroupMembership(view.req, [group as number], []),
              (n) => tn({ one: "Added 1 item to “{name}”",
                          other: "Added {n} items to “{name}”" },
                        n, { name: groupName }))}
            style={{ ...viewBtn, flex: 1,
                     opacity: busy || group == null ? 0.5 : 1 }}
          >
            <Icon name="create_new_folder" size={14} /> {t("Add")}
          </button>
          <button
            disabled={busy || group == null}
            onClick={() => void run(
              () => api.viewGroupMembership(view.req, [], [group as number]),
              (n) => tn({ one: "Removed 1 item from “{name}”",
                          other: "Removed {n} items from “{name}”" },
                        n, { name: groupName }))}
            style={{ ...viewBtn, flex: 1,
                     opacity: busy || group == null ? 0.5 : 1 }}
          >
            <Icon name="folder_off" size={14} /> {t("Remove")}
          </button>
        </div>
      </ViewSection>

    </div>
  );
}

/** A block of whole-view actions. Untitled, it is set off by a rule instead
 *  — which is what the two that change the library get, since the panel's
 *  header has already named the scope. `rule` says which side that rule sits
 *  on, because it always separates the block from the SECTIONS: above when
 *  the block is last, below when it is first. */
function ViewSection({ title, rule = "above", children }: {
  title?: string; rule?: "above" | "below"; children: React.ReactNode;
}) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6,
      ...(title ? null : rule === "below" ? {
        borderBottom: "1px solid var(--border-soft)", paddingBottom: 14,
      } : {
        borderTop: "1px solid var(--border-soft)", paddingTop: 14,
      }),
    }}>
      {title && (
        <SectionHeading sm>
          {title}
        </SectionHeading>
      )}
      {children}
    </div>
  );
}

const viewBtn: React.CSSProperties = {
  height: 30, borderRadius: "var(--r-4)", display: "flex", alignItems: "center",
  justifyContent: "center", gap: 5, padding: "0 10px",
  border: "1px solid var(--border-strong)", background: "var(--panel-2)",
  color: "var(--text-2)", cursor: "pointer", fontSize: "var(--fs-3)", fontWeight: 600,
};

/** Shown in the sidebar's scroll area when nothing is selected: a big icon and
 *  a short line, instead of the (now empty) Properties/Groups/Tags sections. */
/** WHAT THIS RANKING IS, over its own view.
 *
 *  The scope's own facts — the scale it counts in, its pools and how much
 *  evidence each holds, and the caveat where that evidence cannot yet put
 *  its pictures in one order. NOT the standings: those are the GRID now,
 *  in sections, at the size somebody actually judges a picture at. The
 *  rankings page drew them as a row of 54px thumbnails whose own code
 *  conceded they were "not enough to answer the question the histogram is
 *  read to ask — whether this one really belongs at 9".
 */
function RankingScopeCard({ id, pool, scope, total }: {
  id: number; pool: number | null;
  /** The view's own search body — what the verbs below act on when nothing
   *  is picked. Its ids never travel; the scope does. */
  scope?: RankingItemsBody | null;
  total?: number | null;
}) {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["ranking-detail", id], queryFn: () => api.rankingDetail(id) });
  const { data: rows } = useQuery({
    queryKey: ["rankings"], queryFn: () => api.rankings() });
  const row = rows?.find((r) => r.id === id);
  if (!row) return null;
  const pools = (data?.pools ?? []).filter(
    (lg) => pool == null || lg.id === pool);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8,
                  padding: "10px 12px", borderRadius: "var(--r-6)",
                  border: "1px solid var(--border-soft)",
                  background: "var(--panel-2)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Icon name="leaderboard" size={15} color="var(--muted-2)" />
        <span style={{ fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text)",
                       overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap", flex: 1 }}>{row.name}</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                       color: "var(--muted-2)", flex: "0 0 auto" }}>
          {row.bucket_lo}–{row.bucket_hi}
        </span>
      </div>
      {/* NOTHING PLACED YET is the one thing an empty ranking view has to
          say, and the reason this card draws at a total of zero. */}
      {row.items === 0 ? (
        <div className="mc-copy" style={{ fontSize: "var(--fs-2)", color: "var(--muted)",
                                          lineHeight: 1.45 }}>
          {t("Nothing placed yet — compare a few pairs and they appear here, best first.")}
        </div>
      ) : pools.map((lg) => (
        <div key={lg.id} style={{ display: "flex", alignItems: "baseline",
                                  gap: 6, fontSize: "var(--fs-2)" }}>
          <span style={{ color: "var(--text-2)", overflow: "hidden",
                         textOverflow: "ellipsis", whiteSpace: "nowrap",
                         flex: 1 }}>
            {lg.name || t("Default")}
          </span>
          <span style={{ color: "var(--muted-2)", flex: "0 0 auto" }}>
            {tn({ one: "1 comparison", other: "{n} comparisons" }, lg.judgments)}
          </span>
          {/* Its pictures cannot all be put in one order yet, so the
              sections below say less than they look like they do. */}
          {lg.settled === false && lg.judgments > 0 && (
            <span title={t("Its pictures cannot all be put in one order yet, so the standings would say more than the comparisons do")}
                  style={{ color: "var(--yellow-text)", flex: "0 0 auto" }}>
              {t("(Too few comparisons)")}
            </span>
          )}
        </div>
      ))}
      {/* AND WHAT CAN BE DONE TO ALL OF THEM. The same three verbs the
          picked picture has, over the view — offered only where the view
          holds something, since "set aside nothing" is not a thing to
          press. */}
      {scope != null && (total ?? 0) > 0 && (
        <RankingVerbs rankingId={id} items={[]} view={scope}
                      count={total ?? 0}
                      onDone={() => {
                        qc.invalidateQueries({ queryKey: ["rankings"] });
                        qc.invalidateQueries({ queryKey: ["ranking-detail"] });
                        bumpLibrary();
                      }} />
      )}
    </div>
  );
}

function NoSelectionPlaceholder() {
  const t = useT();
  return (
    <div
      style={{
        height: "100%", minHeight: 260, padding: "40px 28px",
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        textAlign: "center", gap: 12, color: "var(--muted-2)",
      }}
    >
      <Icon name="deselect" size={46} color="var(--muted-3)" />
      <div style={{ fontSize: "var(--fs-4)", fontWeight: 600, color: "var(--muted)" }}>{t("Nothing selected")}</div>
      <div style={{ fontSize: "var(--fs-3)", lineHeight: 1.5, maxWidth: 200, color: "var(--muted-2)" }}>
        {t("Select one or more items in the grid to see their properties, tags and groups.")}
      </div>
    </div>
  );
}

/** Bottom bar shown in the Trash: permanently empties the whole Trash. */
function EmptyTrashBar({ onEmptied }: { onEmptied: () => void }) {
  const t = useT();
  const empty = async () => {
    if (!(await confirm({
      title: t("Permanently delete every item in the Trash?"),
      body: t("This cannot be undone."),
      answer: { label: t("Empty the Trash"), danger: true },
    }))) return;
    await api.emptyTrash();
    onEmptied();
  };
  return (
    <div style={{ flex: "0 0 auto", borderTop: "1px solid var(--border)", background: "var(--panel-3)", padding: 14 }}>
      <Button variant="danger" size="md" block
    onClick={empty}
    title="Permanently delete all trashed items">
        <Icon name="delete_forever" size={16} />
        Empty Trash
      </Button>
    </div>
  );
}

// Colors for a tag/group row given its aggregate state.
function stateColors(state: TagState): { dot: string; text: string; strike: boolean } {
  if (state === "neg") return { dot: "var(--red)", text: "var(--red-text)", strike: true };
  if (state === "mixed") return { dot: "var(--yellow)", text: "var(--yellow-text)", strike: false };
  return { dot: "var(--green)", text: "var(--text-bright)", strike: false };
}

/** The leading state indicator on a tag row: the green/red/yellow dot. The dot
 *  itself is the positive/negative toggle — clicking it flips the tag (no icon
 *  swap on hover; a hover ring signals it's clickable). */
function StateDot({
  color, dotOpacity = 1, flipTitle, onFlip,
}: {
  color: string;
  dotOpacity?: number;
  flipTitle?: string;
  onFlip?: () => void;
}) {
  return (
    <span
      className={onFlip ? "tag-state-toggle" : undefined}
      title={onFlip ? flipTitle : undefined}
      onClick={onFlip ? (e) => { e.stopPropagation(); onFlip(); } : undefined}
      style={{ flex: "0 0 16px", width: 16, height: 16, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "var(--r-1)", cursor: onFlip ? "pointer" : "default" }}
    >
      <span style={{ width: 9, height: 9, borderRadius: 2, background: color, opacity: dotOpacity }} />
    </span>
  );
}

/**
 * What a tag row shows when its tag is somebody: a person marker, and — when a
 * detector found them here — a face marker that previews the picture with the
 * boxes on it.
 *
 * Both are markers first and controls second. The slug alone cannot say that
 * `kaguya_shinomiya` is a person rather than a style, nor which of two people
 * with the same name it is, and the sidebar has no room to spell either out.
 */
/** What a tag IS besides a tag, and where to go to edit that half of it.
 *
 * The slug is all the row can say by itself — `kaguya_shinomiya` does not tell
 * you it is a person, let alone which one, and `san_diego` reads the same
 * whether somebody photographed it or an event happened there. Each marker
 * names it in full on hover and, clicked, opens the tab that half lives in and
 * flashes its row: switching tabs alone leaves you to find, in a list of
 * eight, the thing you just pointed at.
 *
 * The FACE marker is its own jump, not a decoration on the person's: the
 * question "where is she in this picture" is answered by the crop, and that is
 * a different row from the one naming her.
 */
function KindMarks({ subject, place, event, faces, onGo }: {
  subject: SubjectOnItem | null;
  place: PlaceRow | null;
  event: EventRow | null;
  faces: FaceRow[];
  /** Open that tab and land on this tag's row there. `face` means the same
   *  tab as `subject`, aiming at the crop instead of the name. */
  onGo?: (what: "subject" | "place" | "event" | "face") => void;
}) {
  const t = useT();
  const tn = useTn();
  const lang = useLang();
  const [hover, setHover] = useState(false);
  const anchor = useRef<HTMLSpanElement>(null);
  const rect = useAnchorRect(anchor, hover && faces.length > 0);
  if (!subject && !place && !event) return null;

  const mark = (icon: string, label: string,
                what: "subject" | "place" | "event") => (
    <span
      key={what}
      onClick={onGo ? (e) => { e.stopPropagation(); onGo(what); } : undefined}
      title={label}
      style={{
        flex: "0 0 auto", display: "flex", alignItems: "center",
        color: "var(--muted-2)", cursor: onGo ? "pointer" : "default",
      }}
    >
      <Icon name={icon} size={13} />
    </span>
  );

  const who = subject ? (subject.display_name || subject.tag) : "";
  return (
    <>
      {subject && mark(RECORD_ICON.subject,
        [who, subject.comment].filter(Boolean).join(" · "), "subject")}
      {place && mark(RECORD_ICON.place,
        placeLabel(place), "place")}
      {event && mark(RECORD_ICON.event,
        [event.display_name || event.tag,
         spanLabel(event.start_date, event.end_date, lang)]
          .filter(Boolean).join(" · "), "event")}
      {faces.length > 0 && (
        <span
          ref={anchor}
          onClick={onGo ? (e) => { e.stopPropagation(); onGo("face"); } : undefined}
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => setHover(false)}
          title={tn({ one: "One face found here",
                      other: "{n} faces found here" }, faces.length)}
          style={{ flex: "0 0 auto", display: "flex", alignItems: "center",
            color: "var(--muted-2)", cursor: onGo ? "pointer" : "default" }}
        >
          <Icon name="face" size={13} />
        </span>
      )}
      {hover && faces.length > 0 && (
        <FloatingFacesInPicture faces={faces} rect={rect} />
      )}
    </>
  );
}

/**
 * The key a tag row is selected by: its group ("u" = ungrouped), the time range
 * it stands for ("" = the whole instance), then the tag's name. Exported so the
 * annotator can address the same rows from the canvas side.
 *
 * A timed tag has ONE ROW PER RANGE — a film's tag is present in one stretch
 * and absent in another, and those are two different facts — so the box id is
 * part of a row's identity. The NAME comes last because it is the only part
 * that can contain anything, colons included.
 */
export function tagRowKey(groupId: number | null, name: string,
                          boxId?: number | null): string {
  return `${groupId ?? "u"}:${boxId ?? ""}:${name}`;
}

/** The tag name inside a row key (see `tagRowKey`). */
export function rowKeyName(key: string): string {
  const first = key.indexOf(":");
  const second = key.indexOf(":", first + 1);
  return second < 0 ? key.slice(first + 1) : key.slice(second + 1);
}

/** One selectable line of the tag panel: an instance, or one of its ranges. */
interface TagRow {
  inst: TagInstance;
  /** The time range this row stands for; null when the row is the instance. */
  range: TagBox | null;
  key: string;
}

/** Whether the tag list hides what this picture is said NOT to have, and
 *  whether the rows it is holding back are on show anyway. View preferences,
 *  so they live where the other per-browser list settings do rather than in
 *  the library — nobody else's list is changed by them.
 *
 *  The reveal is REMEMBERED, and that is what makes it one answer for the
 *  whole list rather than one per group: a per-item tag group's id means
 *  nothing on the next item, so a set of revealed ids could not survive the
 *  one thing it would have to survive to be worth keeping. Each group still
 *  COUNTS its own — the line says how many that box is holding — and they
 *  all answer to the one switch. */
const HIDE_NEG_KEY = "mc.hideNegativeTags";
const SHOW_NEG_KEY = "mc.showNegativeTags";

/**
 * Single-item tag view organized into named groups. Every direct tag lives in a
 * group — a default "Ungrouped" group plus any named ones. The same tag may
 * appear in several groups as separate instances, each with its own bounding
 * boxes. Instances can be dragged between groups (or moved into a new group via
 * the toolbar), and a tag's bbox icon opens the editor with that tag selected.
 */
export function GroupedTags({
  itemId,
  detail,
  suggestions,
  fetchSuggestions,
  readOnly,
  topAction,
  hideHeader,
  hideAnnotate,
  selectedKeys,
  onSelectedKeys,
  instanceFilter,
  rangeFilter,
  impliedFilter,
  onAddInstance,
  onShowKind,
  onHighlight,
  onChange,
}: {
  itemId: number;
  detail: ItemDetail;
  // The adders' suggestion source: a static catalog (the annotator holds one
  // anyway) or a typing-driven fetcher (the sidebar, which no longer fetches
  // the whole catalog just for this). Passed through to `TagAutocomplete`.
  suggestions?: TagSuggestion[];
  fetchSuggestions?: (q: string) => Promise<TagSuggestion[]>;
  readOnly?: boolean;
  // A "Generate tags" button rendered at the top of the section body.
  topAction?: React.ReactNode;
  // Drop the "Tags" heading when this is the sole content of the Tags tab.
  hideHeader?: boolean;
  // Hide the "Annotate" button — it opens the annotator, so it's redundant when
  // this panel is itself rendered inside the annotator.
  hideAnnotate?: boolean;
  // Row selection, normally the panel's own state. Passing both makes it
  // CONTROLLED, which is how the annotator keeps it in step with the boxes on
  // the canvas (selecting a box selects its tag row, and vice versa). Keys come
  // from `tagRowKey`.
  selectedKeys?: string[];
  onSelectedKeys?: (keys: string[]) => void;
  // Show only some of the item's tag instances (the annotator splits a video's
  // tags into whole-item ones and the ones live at the playhead). With a filter
  // set, groups left empty by it are dropped — except Ungrouped, which is the
  // section's default landing place.
  instanceFilter?: (i: TagInstance) => boolean;
  // Show only some of a timed tag's RANGES (the annotator's playhead section
  // shows the stretches covering the current frame, not every stretch of a tag
  // that happens to be live). A tag whose every range is filtered out shows no
  // row at all — the rows ARE its ranges.
  rangeFilter?: (b: TagBox) => boolean;
  /** Which ENTAILED tags to list, judged by the tags that entail them.
   *
   *  An implied tag carries no boxes of its own — it is not assigned at all —
   *  so `instanceFilter` cannot see it, and the "At this frame" list showed
   *  every implication of every tag in the film whatever the playhead was
   *  doing. An implication is live exactly when something implying it is, and
   *  only the caller knows what "live" means. A tag whose source is not
   *  recorded is dropped rather than kept: this list makes a claim about ONE
   *  frame, and an implication nothing can be traced to cannot support it. */
  impliedFilter?: (via: string[]) => boolean;
  // What "add a tag" means here, when it isn't just assigning it to the item
  // (the annotator's playhead section adds it AT the current time instead).
  onAddInstance?: (name: string, groupId: number | null, negative: boolean) => Promise<void> | void;
  // Show the Subjects tab, landing on this tag's subject. Given by the
  // properties panel, which has one; omitted by the annotator, which does not
  // — so the marker on a subject's tag stays a marker there instead of
  // promising a place to go.
  /** Open the tab that edits this half of a tag and land on its row.
   *  `face` means the Subjects tab, aiming at the crop rather than the name. */
  onShowKind?: (what: "subject" | "place" | "event" | "face",
                tag: string) => void;
  /** Report which tags are picked, so the grid can ring the pictures that
   *  carry them too. Given by the library's sidebar; the annotator passes
   *  none, since the grid it would ring is behind its own window. */
  onHighlight?: (tags: TagHl[]) => void;
  onChange: () => void;
}) {
  const qc = useQueryClient();
  const t = useT();
  const tn = useTn();
  // A row's own ✕ offers itself back exactly as the bar's Remove does — see
  // `useUndoRun`. Without a provider above it is a passthrough.
  const undoRun = useUndoRun();
  const openAnnotator = useUI((s) => s.openAnnotator);
  // Which of the item's tags are a subject's identity, and where that subject's
  // face was found. A tag row is the one place both are already in front of
  // you, and neither is derivable from the tag itself.
  const subjectByTag = useMemo(
    () => new Map((detail.subjects ?? []).map((sub) => [sub.tag, sub])),
    [detail.subjects]
  );
  // The same for the other two halves a tag can carry. Only the ones ON this
  // item, since the mark exists to say what THIS row is.
  const { data: allPlaces } = useQuery({ queryKey: ["places"], queryFn: api.places });
  const { data: allEvents } = useQuery({ queryKey: ["events"], queryFn: api.events });
  const placeByTag = useMemo(
    () => new Map(placesOnItem(allPlaces, detail).map((p) => [p.tag, p])),
    [allPlaces, detail]
  );
  const eventByTag = useMemo(
    () => new Map(eventsOnItem(allEvents, detail).map((e) => [e.tag, e])),
    [allEvents, detail]
  );
  const { data: itemFaces } = useQuery({
    queryKey: ["faces", itemId],
    queryFn: () => api.faces(itemId),
    enabled: subjectByTag.size > 0,
  });
  //: WHAT THE TAG SETS SAY about every tag on the item, in one request, for
  //  the `?` beside each name (owner 2026-09) — the Tags tab's own mark,
  //  which this list lacked. Read from the item's instances, so a tag
  //  arriving with an edit is described a render later.
  const describeNames = useMemo(
    () => [...new Set((detail.tag_instances ?? []).map((i) => i.name))].sort(),
    [detail.tag_instances]);
  const { data: described } = useQuery({
    queryKey: ["describe", describeNames.join(",")],
    queryFn: () => api.describeNames(describeNames),
    enabled: describeNames.length > 0, staleTime: 60_000,
  });
  const facesBySubject = useMemo(() => {
    const map = new Map<number, FaceRow[]>();
    for (const f of itemFaces ?? []) {
      if (f.dismissed) continue;
      // Under EVERY person on it: a face that is a character and the actor
      // belongs in both of their marks.
      for (const sub of f.subjects) {
        const list = map.get(sub.subject_id);
        if (list) list.push(f); else map.set(sub.subject_id, [f]);
      }
    }
    return map;
  }, [itemFaces]);
  // The right-clicked tag row's menu — where it was clicked, and which tag it
  // is about. One menu for the whole list: the actions are the same for every
  // row, and one per row would be one portal per tag.
  const [tagMenu, setTagMenu] = useState<
    { at: { x: number; y: number }; name: string } | null>(null);
  const searchActions = useSearchActions();
  /** A tag names one thing, and the most specific reading of it wins: a
   *  subject's tag is asked about with `SUBJECT:`, a place's with `PLACE`, an
   *  event's with `EVENT` — that is the statement being made, where the tag is
   *  merely how it is stored. */
  const searchActionsFor = (name: string): RowAction[] => {
    const sub = subjectByTag.get(name);
    const place = placeByTag.get(name);
    const event = eventByTag.get(name);
    if (sub) return searchActions("subject", name, sub.display_name || name);
    if (place) return searchActions("place", name);
    if (event) return searchActions("event", name, event.display_name || name);
    return searchActions("tag", name);
  };
  // What a group's add-field currently holds, normalized: the row already
  // carrying that exact tag highlights and scrolls into view, so "it is
  // already assigned" is shown while typing rather than discovered on
  // commit.
  const [typedHint, setTypedHint] =
    useState<{ gid: number | null; name: string } | null>(null);
  useEffect(() => {
    if (typedHint == null) return;
    document.querySelector('[data-typedhint="1"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [typedHint]);
  // Selected instance rows, keyed `${group ?? "u"}:${name}` — `useRowSelect`'s
  // (declared beside the row order below, which it needs), the panel's own
  // unless the caller controls it (see `selectedKeys`). Reached through a
  // ref from the handlers above that declaration.
  const selRef = useRef<RowSelect | null>(null);
  const setSelected = useCallback((next: string[] | ((cur: readonly string[]) => string[])) => {
    const cur = selRef.current;
    if (!cur) return;
    cur.set(typeof next === "function" ? next(cur.selected) : next);
  }, []);
  // Group id currently highlighted as a drop target ("u" = Ungrouped, "new" =
  // the create-a-new-group drop zone).
  const [dropGroup, setDropGroup] = useState<number | "u" | "new" | string | null>(null);
  // True while a handle drag is in progress (reveals the new-group drop zone).
  const [dragging, setDragging] = useState(false);
  // The instances being dragged (one, or the whole selection).
  const dragRef = useRef<{ name: string; from: number | null }[]>([]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setSelected([]); }, [itemId]);

  // HIDE THE TAGS THIS PICTURE IS SAID NOT TO HAVE. A negative assignment is
  // a real statement and worth keeping, but a library tagged that way ends up
  // with lists that are mostly absences — so this is a view option, per
  // browser like the other list preferences, and it touches only the ASSIGNED
  // rows: an implied tag is not something anybody said about this item.
  const [hideNeg, setHideNeg] = useState(() => {
    try { return storage.get(HIDE_NEG_KEY) === "1"; } catch { return false; }
  });
  const toggleHideNeg = () => setHideNeg((v) => {
    try { storage.set(HIDE_NEG_KEY, v ? "0" : "1"); } catch { /* ignore */ }
    return !v;
  });
  // ROWS THE HIDE RULE IS HOLDING OFF ON. Flipping a tag negative while the
  // option is on would otherwise take the row out from under the pointer that
  // flipped it — and with it the dot that is the only way back, so a slip
  // would be uncorrectable without switching the option off. The row stays
  // until the moment has passed: another item, a change of selection, or the
  // option being switched (leaving the tab takes the whole panel with it).
  const [reprieved, setReprieved] = useState<readonly string[]>([]);
  const reprieve = (key: string) =>
    setReprieved((cur) => (cur.includes(key) ? cur : [...cur, key]));
  // Whether the held-back rows are on show anyway — remembered, so the next
  // picture keeps the answer you last gave instead of folding them away again
  // behind a line you have already read.
  const [showNeg, setShowNeg] = useState(() => {
    try { return storage.get(SHOW_NEG_KEY) === "1"; } catch { return false; }
  });
  const toggleShowNeg = () => setShowNeg((v) => {
    try { storage.set(SHOW_NEG_KEY, v ? "0" : "1"); } catch { /* ignore */ }
    return !v;
  });
  useEffect(() => { setReprieved([]); }, [itemId, hideNeg]);

  const activeFile = detail.files.find((f) => f.active) ?? null;
  // Timecodes are frame-accurate, so they need the film's rate.
  const fileFps = activeFile?.frame_rate && activeFile.frame_rate > 0
    ? activeFile.frame_rate : 25;
  // THERE IS NO SCORES BOX ANY MORE (rung v31). A ranking used to
  // materialize its standings as score tags, and those derived rows
  // rendered apart — read-only, after the groups, out of the ordinary
  // selection — because nothing a person did to them would have survived
  // the next refit. A ranking writes nothing now; what an axis leaves on a
  // picture is an ordinary tag the Assign-ratings action put there, and it
  // lives among the ordinary rows with a pencil and a ✕ like any other.
  const instances = instanceFilter
    ? detail.tag_instances.filter(instanceFilter)
    : detail.tag_instances;

  // A ROW is a tag instance — or, for a tag that carries TIME RANGES, one row
  // per range. A film's tag is present in one stretch and pointedly absent in
  // another, and those are two different facts, each with its own sign; folding
  // them into one row could only show a count. (A range is a box with a time
  // and no geometry; a box that has geometry belongs to a moving subject and
  // rides along on the instance's own row as before.)
  const rangesOf = (i: TagInstance) => (i.boxes ?? [])
    .filter((b) => b.time_start != null && b.x == null)
    .sort((a, b) => (a.time_start ?? 0) - (b.time_start ?? 0));
  const rowsOf = (i: TagInstance): TagRow[] => {
    const gid = i.group_id ?? null;
    const all = rangesOf(i);
    if (all.length === 0) return [{ inst: i, range: null, key: tagRowKey(gid, i.name) }];
    return all.filter((b) => !rangeFilter || rangeFilter(b))
      .map((b) => ({ inst: i, range: b, key: tagRowKey(gid, i.name, b.id) }));
  };
  // A row is held back for being negative only when nothing has just happened
  // to it. Per ROW rather than per instance: over a film a tag is present in
  // one stretch and absent in another, and those are two rows with two signs.
  const heldBack = (row: TagRow) =>
    hideNeg
    && (row.range ? !!row.range.negative : row.inst.negative)
    && !reprieved.includes(row.key);
  const allRowsIn = (gid: number | null) =>
    instances.filter((i) => (i.group_id ?? null) === gid)
      .sort((a, b) => a.name.localeCompare(b.name))
      .flatMap(rowsOf);
  // The group's ORDINARY rows, and — separately — the ones the rule is
  // keeping back. Two lists rather than one filtered one, because revealing
  // does not mix them back in: they come back TOGETHER, under the line that
  // counts them, where a run of struck-through rows reads as the block it is
  // instead of scattering red through the alphabetical order.
  const rowsIn = (gid: number | null) =>
    allRowsIn(gid).filter((r) => !heldBack(r));
  const heldRowsIn = (gid: number | null) => allRowsIn(gid).filter(heldBack);
  // What the group shows, in READING order — which is the order a shift-range
  // has to walk, so the reveal has to be in it.
  const shownRowsIn = (gid: number | null) => showNeg
    ? [...rowsIn(gid), ...heldRowsIn(gid)] : rowsIn(gid);

  const groups: { id: number | null; name: string; system: boolean;
                  tags: string[]; subjects: number[] }[] = [
    { id: null, name: "Ungrouped", system: false, tags: [], subjects: [] },
    ...detail.tag_groups
      // `allRowsIn`, not `rowsIn`: a group emptied by the HIDE rule keeps its
      // box, because the box is where the count of what it is hiding lives.
      .filter((g) => (!instanceFilter && !rangeFilter)
                     || allRowsIn(g.id).length > 0)
      .map((g) => ({
        id: g.id as number | null, name: g.name, system: !!g.system,
        tags: g.tags ?? [], subjects: g.subjects ?? [],
      })),
  ];
  const approvePlacement = async (pid: number) => {
    await api.approvePlacement(pid);
    refresh();
  };
  // Accept / dismiss every pending tag in the auto-managed Pending group at once.
  const approveAllPending = async (rows: TagInstance[]) => {
    for (const inst of rows) {
      if (inst.placement_id != null) await api.approvePlacement(inst.placement_id);
    }
    setSelected([]);
    refresh();
  };
  const dismissAllPending = async (rows: TagInstance[]) => {
    for (const inst of rows) {
      if (inst.placement_id != null) await api.deleteTagPlacement(inst.placement_id);
      else await api.unassignItemTag(itemId, inst.name);
    }
    setSelected([]);
    refresh();
  };
  const keyOf = tagRowKey;

  const inGroup = (gid: number | null) =>
    instances.filter((i) => (i.group_id ?? null) === gid)
      .sort((a, b) => a.name.localeCompare(b.name));

  // Flat key order across all groups (Ungrouped first), for shift/drag
  // ranges.
  const orderKeys = useMemo(
    () => groups.flatMap((g) => shownRowsIn(g.id).map((r) => r.key)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [instances, detail.tag_groups, hideNeg, reprieved, showNeg]
  );
  // THE SELECTION — the one row selection every list here has: the paint,
  // the one click rule, the pruning. Controlled where the annotator hands
  // it over (and then never pruned here: the owner may show two filtered
  // panels over one selection, and each would prune the other's rows away).
  const sel = useRowSelect(orderKeys,
    selectedKeys !== undefined && onSelectedKeys
      ? { selected: selectedKeys, onChange: onSelectedKeys, prune: false }
      : undefined);
  selRef.current = sel;
  const selected = sel.selected;
  // The picked rows, as (name, sign) — what the grid needs to ring the
  // pictures carrying the same tags. Keyed on the selection's own string so a
  // re-render with the same picks reports nothing new.
  const selKey = selected.join("|");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setReprieved([]); }, [selKey]);
  const signByName = useMemo(
    () => new Map((detail.tags ?? []).map((t) => [t.name, !!t.negative])),
    [detail.tags]);
  useEffect(() => {
    if (!onHighlight) return;
    const seen = new Set<string>();
    const out: TagHl[] = [];
    for (const key of selected) {
      const name = rowKeyName(key);
      if (!name || seen.has(name)) continue;
      seen.add(name);
      out.push({ name, negative: signByName.get(name) ?? false });
    }
    onHighlight(out);
    return () => onHighlight([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selKey, signByName, onHighlight]);
  // The selected rows THIS panel shows. The annotator puts two filtered panels
  // over one selection (the film's tags, and the tags at the playhead), so a
  // panel must act on — and count — only its own rows; otherwise both offer to
  // delete the same selection and one of them cannot even resolve it.
  const mine = useMemo(
    () => selected.filter((k) => orderKeys.includes(k)),
    [selected, orderKeys]);

  // WHEN an implied tag applies, over a film: the stretches of whatever
  // entails it. An implication has no boxes of its own, so without this its
  // row read as "the whole film" while the `poodle` entailing it covered a
  // minute — see `videoTracks.coverageOfAll` for the rule, the contagious
  // whole-film case included.
  const impliedRangeLabel = useImpliedRangeLabel(detail);
  // Indirect tags (read-only) shown as their own group sections — one per
  // contributing library group, one for the tag hierarchy (parent-implied), and
  // one for a sequence's member tags. A tag the item also assigns directly is
  // kept but marked "overridden" (greyed + struck), never mixed into Ungrouped.
  const indirectSections = useMemo(() => {
    type IndTag = { name: string; negative: boolean; overridden: boolean; via: string[] };
    const byKey = new Map<string, { source: string; label: string; tags: Map<string, IndTag> }>();
    for (const g of detail.indirect) {
      const source = g.source ?? "group";
      const key = `${source}:${g.group_id}`;
      const label = source === "parent" ? "Tag hierarchy"
        : source === "sequence" ? "Sequence contents"
        : g.group_name;
      let sec = byKey.get(key);
      if (!sec) { sec = { source, label, tags: new Map() }; byKey.set(key, sec); }
      const ov = new Set(g.overridden ?? []);
      for (const name of g.tags) {
        const prev = sec.tags.get(name);
        sec.tags.set(name, {
          name,
          negative: (prev?.negative ?? false) || g.negative,
          overridden: (prev?.overridden ?? false) || ov.has(name),
          // The assigned tag(s) that entail this one (parent source only).
          via: g.sources?.[name] ?? prev?.via ?? [],
        });
      }
    }
    return [...byKey.values()].map((s) => ({
      source: s.source,
      label: s.label,
      tags: [...s.tags.values()]
        // Only the HIERARCHY section is time-aware: a library group's tags and
        // a sequence's are assigned for the whole item, and have no stretch to
        // be inside or outside of.
        .filter((x) => !impliedFilter || s.source !== "parent" || impliedFilter(x.via))
        .sort((a, b) => a.name.localeCompare(b.name)),
    })).filter((s) => s.tags.length > 0);
  }, [detail.indirect, impliedFilter]);

  // ONE SWEEP PER EDIT, AND IT IS THE CALLER'S. This used to fire four broad
  // invalidations of its own and then call `onChange`, which does the same
  // work properly — the item's own detail at once (`bumpItem`) and the
  // list/catalog keys through the short coalescer, `library-stats` and `tags`
  // among them. So every ✕ in this panel started two rounds of page fetches
  // 150 ms apart, the first aborted by the second; on a million-item library
  // that is a wasted half-second walk per mounted page, and the server cannot
  // see an abort (see `routers/items._slot_for`). The narrow half stays
  // immediate, which is what makes the row disappear on the spot.
  const refresh = () => {
    bumpItem(itemId);
    onChange();
  };
  // THE ADDER TAKES THE T FIELD'S PREFIXES on its one word — `-name` takes
  // the tag off the item, `!name` assigns it negatively — read by the same
  // `parseQuickWord` that reads the T field's line, so the two cannot mean
  // different things. A removal is the whole tag (every instance), the
  // unassign the row's ✕ makes.
  const addToGroup = async (raw: string, gid: number | null) => {
    const op = parseQuickWord(raw);
    if (!op) return;
    if (op.remove) await api.unassignItemTag(itemId, op.name);
    else if (onAddInstance) await onAddInstance(op.name, gid, op.negative);
    else await api.addTagToGroup(itemId, op.name, gid, op.negative);
    refresh();
  };
  const flip = async (inst: TagInstance, key: string) => {
    reprieve(key);
    // The row is an INSTANCE, and its dot flips that instance's own sign —
    // the same tag may be positive in one group and negative in another,
    // and the assignment re-derives server-side (any positive wins). Only
    // the implicit ungrouped row (no placement) still flips the tag itself,
    // because it IS the assignment.
    if (inst.placement_id != null) {
      await api.setPlacementSign(inst.placement_id, !inst.negative);
    } else {
      await api.assignItemTag(itemId, inst.name, !inst.negative);
    }
    refresh();
  };
  // A range's sign is its own — "present here" / "absent here" — so flipping it
  // touches that box, never the tag.
  const flipRange = async (range: TagBox, key: string) => {
    reprieve(key);
    if (range.id == null) return;
    await api.updateTagBox(range.id, { negative: !range.negative });
    refresh();
  };
  // Removing a range removes that stretch. When it was the tag's last one the
  // tag itself goes with it: a timed tag with no times reads as "the whole
  // film", which is not what removing its only range asked for.
  const removeRange = (inst: TagInstance, range: TagBox) =>
    undoRun(`${t("Removed")} ${inst.name}`, () => doRemoveRange(inst, range));
  const doRemoveRange = async (inst: TagInstance, range: TagBox) => {
    if (range.id == null) return;
    await api.deleteTagBox(range.id);
    const others = (inst.boxes ?? []).filter((b) => b.id !== range.id);
    if (others.length === 0) {
      if (inst.placement_id != null) await api.deleteTagPlacement(inst.placement_id);
      else await api.unassignItemTag(itemId, inst.name);
    }
    refresh();
  };
  const removeInstance = (inst: TagInstance) =>
    undoRun(`${t("Removed")} ${inst.name}`, () => doRemoveInstance(inst));
  const doRemoveInstance = async (inst: TagInstance) => {
    // A placement (an explicit instance in a group) is removed on its own; a
    // purely implicit ungrouped tag (no placement) is unassigned entirely.
    if (inst.placement_id != null) {
      await api.deleteTagPlacement(inst.placement_id);
    } else {
      await api.unassignItemTag(itemId, inst.name);
    }
    refresh();
  };
  // Remove every selected ROW this panel actually shows — a whole instance, or
  // a single time range, exactly as that row's own ✕ would. Resolving rows
  // (not instances) is what makes it work on a film, where a row is a stretch
  // and its key carries the box id.
  const removeSelected = async () => {
    const byKey = new Map(
      groups.flatMap((g) => rowsIn(g.id)).map((r) => [r.key, r]));
    const rows = mine.map((k) => byKey.get(k)).filter((r): r is TagRow => !!r);
    // Ranges first, and per instance, so "was that its last one?" is asked
    // after all of them are gone rather than once per row.
    const dropped = new Map<TagInstance, Set<number>>();
    for (const r of rows) {
      if (r.range?.id == null) continue;
      await api.deleteTagBox(r.range.id);
      const set = dropped.get(r.inst) ?? new Set<number>();
      set.add(r.range.id);
      dropped.set(r.inst, set);
    }
    for (const [inst, gone] of dropped) {
      const left = (inst.boxes ?? []).filter((b) => b.id != null && !gone.has(b.id));
      if (left.length === 0) {
        if (inst.placement_id != null) await api.deleteTagPlacement(inst.placement_id);
        else await api.unassignItemTag(itemId, inst.name);
      }
    }
    for (const r of rows) {
      if (r.range != null || dropped.has(r.inst)) continue;
      if (r.inst.placement_id != null) await api.deleteTagPlacement(r.inst.placement_id);
      else await api.unassignItemTag(itemId, r.inst.name);
    }
    setSelected(selected.filter((k) => !mine.includes(k)));
    refresh();
  };
  // Move a set of dragged instances into a target group (creating it first when
  // the target is the "new group" drop zone).
  const moveDraggedTo = async (target: number | null | "new" | { subject: SubjectOnItem }) => {
    const dragged = dragRef.current;
    dragRef.current = [];
    if (dragged.length === 0) return;
    let to: number | null;
    if (target === "new") {
      const g = await api.createTagGroup(itemId, "New group");
      to = g.id;
    } else if (typeof target === "object" && target !== null) {
      // Dropping on a subject creates the group already bound to them: the
      // groups you would want are the people in the picture, so they are
      // offered rather than named by hand afterwards.
      const g = await api.createTagGroup(itemId, target.subject.display_name);
      await api.addTagGroupSubject(g.id, target.subject.id);
      to = g.id;
    } else {
      to = target;
    }
    for (const d of dragged) {
      if (d.from !== to) await api.moveTagInstance(itemId, d.name, d.from, to);
    }
    setSelected([]);
    refresh();
  };

  // Selection helpers: the row props are `useRowSelect`'s (`sel.props`); a
  // press that begins on the drag handle starts an HTML5 move instead, and
  // the handle's dragstart ends the press (`cancelPress`).
  // On handle dragStart: drag the whole selection if the grabbed row is part of
  // it, otherwise just this one instance.
  const onHandleDragStart = (
    gid: number | null, name: string, e: React.DragEvent
  ) => {
    const key = keyOf(gid, name);
    const keys = selected.includes(key) ? selected : [key];
    dragRef.current = keys
      .map((k) => instances.find((i) => keyOf(i.group_id ?? null, i.name) === k))
      .filter((i): i is TagInstance => !!i)
      .map((i) => ({ name: i.name, from: i.group_id ?? null }));
    // A drag that sets NO data is a drag Chrome and Firefox may decline to
    // carry — Safari runs it anyway, which is why this looked browser-specific
    // rather than missing. What the payload says does not matter (the move
    // reads `dragRef`, since a tag instance is not a string), only that there
    // is one; `effectAllowed` is what makes the cursor say "move" rather than
    // "copy".
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", dragRef.current.map((d) => d.name).join(", ")); }
    catch { /* older browsers refuse setData outside a real drag */ }
    // Drag the ROW, not the grip. Without this the ghost is whatever carries
    // `draggable` — a 15 px handle glyph — so the thing following the pointer
    // did not look like the thing being moved. The row is on screen and stays
    // there, which is what `setDragImage` needs; the offset keeps it under the
    // pointer instead of jumping its top-left corner there.
    const row = (e.currentTarget as HTMLElement).closest("[data-rowsel]");
    if (row) {
      const r = row.getBoundingClientRect();
      e.dataTransfer.setDragImage(row, e.clientX - r.left, e.clientY - r.top);
    }
    // The press that began on the handle is not a paint.
    sel.cancelPress();
    setDragging(true);
  };
  const endDrag = () => { setDragging(false); setDropGroup(null); };

  const bulk = selected.length >= 1;

  // The same bar every other tab reports to, rather than a Delete button of its
  // own in the header: the gesture that picks these rows is the gesture that
  // picks a person or a caption, so what acts on them belongs in the same
  // place. It also brings Select all, which a header button that only appeared
  // at the SECOND pick could never offer.
  //
  // Only where a bar is listening. The annotator renders this panel with none,
  // and there the header button IS the only bulk action there is.
  const hasBar = useSelectionBarSlot();
  useReportSelection("tags", readOnly ? null : {
    count: mine.length,
    total: orderKeys.length,
    // Only ever this panel's own rows: the annotator lays two filtered panels
    // over ONE selection, so a select-all that took the lot would hand each of
    // them the other's rows.
    onSelectAll: () => setSelected((cur) =>
      [...cur.filter((k) => !orderKeys.includes(k)), ...orderKeys]),
    onRemove: () => void removeSelected(),
    onClear: () => setSelected((cur) => cur.filter((k) => !orderKeys.includes(k))),
    removeTitle: t("Remove them from this item"),
    options: [{
      label: t("Hide negative tags"),
      checked: hideNeg,
      onClick: toggleHideNeg,
    }],
  });

  return (
    <CollapsibleSection
      title="Tags"
      sk="tags"
      hideHeader={hideHeader}
      actions={!readOnly && !hasBar && mine.length >= 2 && (
        <button
          onClick={removeSelected}
          title={`Remove the ${mine.length} selected tags`}
          style={{ display: "flex", alignItems: "center", gap: 4, height: 22, padding: "0 8px", borderRadius: "var(--r-2)", border: "1px solid var(--danger-border)", background: "var(--danger-dim)", color: "var(--danger)", cursor: "pointer", fontSize: "var(--fs-2)", fontWeight: 600 }}
        >
          <Icon name="delete" size={15} />
          Delete {mine.length}
        </button>
      )}
    >

      {/* Annotate (draw tag boxes) — a big button at the top, above Generate
          tags. Creating a group / moving tags into a new group is done by
          dragging tags onto the "new group" drop zone below. */}
      {!readOnly && !hideAnnotate && (detail.kind === "image" || detail.kind === "video") && (
        <AnnotateButton itemId={itemId} tab="tags" />
      )}
      {topAction && <div style={{ marginBottom: 10 }}>{topAction}</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, userSelect: "none", WebkitUserSelect: "none" }}>
        {groups.map((grp) => {
          const gid = grp.id;
          const instRows = inGroup(gid);
          // An EMPTY system group is a stranded leftover (a dismissal path
          // that deleted the assignment without sweeping its Pending group)
          // — it has no rows to act on and no controls of its own, so a box
          // for it is furniture nobody can remove. The server sweeps them
          // now; this skip is the tolerance for the ones already stranded
          // in existing libraries.
          if (grp.system && instRows.length === 0) return null;
          const rows = rowsIn(gid);
          const heldRows = heldRowsIn(gid);
          const isDrop = dropGroup === (gid ?? "u");
          // A Pending group takes NO drops. It is the record of one generation
          // run — what that model said about this picture — so a tag dragged in
          // by hand would be filed as a machine's guess by the very gesture
          // that shows somebody meant it. Dragging OUT is the opposite and is
          // the whole point: the server clears `pending` with the last
          // placement to leave a system group (`_recompute_pending`), so
          // pulling a tag out of the group accepts it. No `preventDefault` on
          // the dragover is what says so — the cursor turns to "no drop".
          const noDrop = readOnly || grp.system;
          // WHO THE GROUPING IS ABOUT, as chips. They sit on their own line
          // UNDER the title rather than beside it: a group is about somebody
          // AND is called something ("Alice, in the rain"), and in a 280 px
          // sidebar the chips and the name were competing for one row — the
          // name truncating first, which is the half you cannot guess. The
          // ADD button stays up in the header, where the group's other
          // controls are.
          const subjectChips = (grp.subjects ?? []).map((sid) => {
            const sub = (detail.subjects ?? []).find((x) => x.id === sid);
            return (
              <span key={sid}
                title={readOnly ? undefined : "No longer about this subject"}
                onClick={readOnly || gid == null ? undefined : () => {
                  // Same offer as the meta tags beside it: this is one click
                  // on a small chip, and it is logged.
                  void undoRun(t("Tag group is no longer about them"),
                    () => api.removeTagGroupSubject(gid, sid).then(refresh));
                }}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 3,
                  height: 16, padding: "0 6px", borderRadius: "var(--r-1)",
                  background: "var(--accent-dim)", color: "var(--accent)",
                  fontSize: "var(--fs-1)", cursor: readOnly ? "default" : "pointer",
                  maxWidth: 160, overflow: "hidden", whiteSpace: "nowrap",
                }}
              >
                <Icon name={RECORD_ICON.subject} size={11} />
                {sub?.display_name || sub?.tag || "?"}
              </span>
            );
          });
          return (
            <div
              key={gid ?? "u"}
              onDragOver={noDrop ? undefined : (e) => { e.preventDefault(); setDropGroup(gid ?? "u"); }}
              onDragLeave={(e) => { if (e.currentTarget === e.target && dropGroup === (gid ?? "u")) setDropGroup(null); }}
              onDrop={noDrop ? undefined : (e) => {
                e.preventDefault();
                setDropGroup(null);
                setDragging(false);
                moveDraggedTo(gid);
              }}
              style={{
                // The amber sits on the GROUP, not on each row inside it: the
                // box already gathers exactly the tags one run suggested, and
                // outlining all fourteen of them said the same thing fourteen
                // times. A pending tag with no such group — what a face's guess
                // assigns — still wears it on its own row.
                border: `1px solid ${isDrop ? "var(--accent)"
                  : grp.system ? "var(--yellow)" : "var(--border)"}`,
                background: isDrop ? "var(--accent-dim)" : "var(--panel-3)",
                borderRadius: "var(--r-5)", padding: 8,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <Icon
                  name={grp.system ? "auto_awesome" : gid == null ? "label_off" : "folder"}
                  size={14}
                  color={grp.system ? "var(--yellow-text)" : "var(--muted-2)"}
                />
                {gid == null ? (
                  <span style={{ flex: 1, fontSize: "var(--fs-2)", fontWeight: 600, color: "var(--muted)" }}>{t("Ungrouped")}</span>
                ) : grp.system ? (
                  // An auto-managed pending group (one per tag-generation run,
                  // named after the model/mode): show its name, no rename/delete.
                  // Amber, like the rows inside it — accent is the app's own
                  // colour and said "interactive" where the fact is "a machine
                  // wrote these and nobody has agreed yet".
                  <span
                    style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-2)", fontWeight: 600, color: "var(--yellow-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={t("{name} — machine-generated tags awaiting your approval", { name: grp.name })}
                  >
                    {grp.name}
                  </span>
                ) : (
                  <EditableTagGroupName
                    key={gid}
                    name={grp.name}
                    readOnly={readOnly}
                    onSaved={(v) => { api.renameTagGroup(gid, v).then(refresh); }}
                  />
                )}
                {/* …and a way to ADD one. Dragging a tag onto a subject's
                    drop zone creates a group already bound to it, but nothing
                    could bind an existing group to a subject afterwards. */}
                {!readOnly && gid != null && (
                  <GroupSubjectAdder
                    subjects={detail.subjects ?? []}
                    already={grp.subjects ?? []}
                    onAdd={(sid) => void undoRun(t("Tag group is about them"),
                      () => api.addTagGroupSubject(gid, sid).then(refresh))}
                  />
                )}
                <Count n={rows.length} size={10} tone="muted-2" />
                {/* Bulk accept / dismiss for the auto-managed Pending group. */}
                {grp.system && !readOnly && instRows.length > 0 && (
                  // Icon-only so the header fits even in a narrow sidebar.
                  <>
                    <span
                      title="Accept all pending tags"
                      onClick={() => approveAllPending(instRows)}
                      style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 18, height: 18, borderRadius: "var(--r-1)", cursor: "pointer", color: "var(--green)", background: "var(--green-dim)" }}
                    >
                      <Icon name="done_all" size={13} />
                    </span>
                    <span
                      title="Dismiss all pending tags"
                      onClick={() => dismissAllPending(instRows)}
                      style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 18, height: 18, borderRadius: "var(--r-1)", cursor: "pointer", color: "var(--muted)", background: "var(--panel-2)" }}
                    >
                      <Icon name="close" size={13} />
                    </span>
                  </>
                )}
                {gid != null && !grp.system && !readOnly && (
                  <IconButton icon="close" size={18} reveal="hover" tone="danger"
                    title="Delete this group (its tags move to Ungrouped)"
                    onClick={() => void undoRun(
                      `${t("Deleted")} ${grp.name}`,
                      () => api.deleteTagGroup(gid).then(refresh))} />
                )}
              </div>

              {/* The subjects, on their own line under the title — see where
                  they are built. Indented to the name's own left edge (the
                  icon plus its gap), so the two read as one block. */}
              {subjectChips.length > 0 && (
                <div style={{
                  display: "flex", flexWrap: "wrap", gap: 4,
                  margin: "-2px 0 6px 20px",
                }}>
                  {subjectChips}
                </div>
              )}

              {/* Meta tags on the GROUPING — "main character", "to redraw" —
                  from the same catalog links and captions draw from. They say
                  something about this grouping, so they never become tags of
                  the item and never reach search or a training prompt. */}
              {gid != null && !grp.system && (
                <TagGroupMetaTags groupId={gid} tags={grp.tags}
                  readOnly={readOnly} onChange={refresh} />
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {/* The adder LEADS the group — adding is what a box is opened
                    for, and at the bottom of a long group the field sat below
                    the fold. The rows it appends land right under it. */}
                {!readOnly && !grp.system && (
                  <TagAdder
                    suggestions={suggestions}
                    fetchSuggestions={fetchSuggestions}
                    existing={instRows.map((r) => r.name)}
                    placeholder={gid == null ? t("Add a tag…") : t("Add to this group…")}
                    onAdd={(name) => addToGroup(name, gid)}
                    onText={(v) => {
                      const name = parseQuickWord(v)?.name ?? "";
                      setTypedHint(name ? { gid, name } : null);
                    }}
                    prefixes
                    flush
                  />
                )}
                {(() => {
                // ONE definition of a row, called for the ordinary run
                // and again for the held-back one under the reveal —
                // they are the same rows and must select, flip and drag
                // alike, which two copies of this JSX could not promise.
                const renderRow = ({ inst, range, key }: TagRow) => {
                  const isSel = selected.includes(key);
                  const typed = typedHint != null && typedHint.gid === gid
                    && inst.name.toLowerCase() === typedHint.name;
                  // A range row carries its OWN sign; an instance row the tag's.
                  const negative = range ? !!range.negative : inst.negative;
                  const c = stateColors(negative ? "neg" : "pos");
                  // A machine said this and nobody has agreed yet — the same
                  // amber a guessed face wears, so that claim looks the same
                  // wherever it is made. The NAME only takes it while the tag
                  // is positive: red-and-struck-through says something the
                  // amber does not, and the border still carries the pending
                  // half. Picked wins over both, as it does on a face crop.
                  // Only a placement-less one. `pending` is a fact about the
                  // (item, tag) PAIR, not about this copy of it, so a tag with
                  // one copy still in a Pending group and one dragged out to a
                  // real group is pending as a whole — and painting the copy
                  // somebody deliberately placed amber said the machine had
                  // guessed it. Inside a Pending group the box already says it
                  // once for all its rows; outside one, a placement IS the
                  // answer. What is left is the tag a face's guess assigns,
                  // which has no placement at all and no other way to say so.
                  const guess = !!inst.pending && inst.placement_id == null;
                  //: A GUESSED FACE'S TAG ANSWERS HERE TOO (owner 2026-09):
                  //  the amber row is a machine saying this person is in the
                  //  picture, and the two answers a face crop offers — agree,
                  //  or not this person — are on the row, so the Tags tab
                  //  can settle it without a trip to the Subjects tab or the
                  //  annotator. What is answered is the APPEARANCE (the tag
                  //  follows it: agreeing stops it being pending, rejecting
                  //  takes the guess and its tag back), never the tag row
                  //  itself — removing the tag would leave the guess standing.
                  const guessSub = guess ? subjectByTag.get(inst.name) : undefined;
                  const guessed = guessSub
                    ? (facesBySubject.get(guessSub.id) ?? []).flatMap((f) =>
                        f.subjects
                          .filter((sub) => sub.subject_id === guessSub.id
                                           && sub.assigned_by === "suggested")
                          .map((sub) => ({ face: f.id, appearance: sub.id })))
                    : [];
                  const answered = () => {
                    qc.invalidateQueries({ queryKey: ["faces", itemId] });
                    qc.invalidateQueries({ queryKey: ["faces"] });
                    refresh();
                  };
                  return (
                    <div
                      key={key}
                      className="hoverable"
                      // A ROW (`data-rowsel`, from `useRowSelect`), so the
                      // panel's background-click detector leaves it alone.
                      {...sel.props(key)}
                      data-typedhint={typed ? "1" : undefined}
                      onMouseDown={readOnly ? undefined : (e) => {
                        // A press on the handle starts an HTML5 move, not a paint.
                        if ((e.target as HTMLElement).closest("[data-handle]")) return;
                        sel.props(key).onMouseDown(e);
                      }}
                      onContextMenu={(e) => {
                        e.preventDefault();
                        setTagMenu({ at: { x: e.clientX, y: e.clientY },
                                     name: inst.name });
                      }}
                      style={{
                        // A range row is two lines (name over timecodes), so the
                        // height is a minimum rather than a fixed 30.
                        display: "flex", alignItems: "center", gap: 7,
                        // The hover actions overlay the right edge (below).
                        position: "relative",
                        minHeight: 30, padding: range ? "3px 6px 3px 4px" : "0 6px 0 4px",
                        boxSizing: "border-box", borderRadius: "var(--r-4)",
                        background: rowBackground(isSel, "var(--panel-2)"),
                        border: `1px solid ${isSel || typed ? "var(--accent)"
                          : guess ? "var(--yellow)" : "var(--border)"}`,
                        // "Already assigned, right here" — a ring beside the
                        // accent border, so it reads apart from a selection.
                        boxShadow: typed && !isSel
                          ? "0 0 0 1px var(--accent)" : undefined,
                        cursor: "pointer",
                      }}
                    >
                      {/* Drag handle — the only draggable part of the row. */}
                      {!readOnly && (
                        <span
                          data-handle
                          draggable
                          onMouseDown={(e) => e.stopPropagation()}
                          onDragStart={(e) => onHandleDragStart(gid, inst.name, e)}
                          onDragEnd={endDrag}
                          title={t("Drag to move to another group")}
                          style={{ flex: "0 0 auto", display: "flex", alignItems: "center", color: "var(--muted-3)", cursor: "grab" }}
                        >
                          <Icon name="drag_indicator" size={15} />
                        </span>
                      )}
                      <StateDot
                        color={c.dot}
                        flipTitle={negative ? t("Make positive") : t("Make negative")}
                        onFlip={readOnly ? undefined
                          : range ? () => flipRange(range, key)
                                  : () => flip(inst, key)}
                      />
                      {/* A range row says WHEN right there — one row is one
                          stretch, so there is a single pair of numbers and no
                          reason to hide them behind a hover. UNDER the name,
                          because a full timecode pair is wider than most tag
                          names and beside it the name had nowhere to go. */}
                      <span style={{ flex: "0 1 auto", minWidth: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 1 }}>
                        <span style={{ minWidth: 0, display: "flex", alignItems: "center", gap: 4, fontFamily: "var(--mono)", fontSize: "var(--fs-3)", color: guess && !negative ? "var(--yellow-text)" : c.text, textDecoration: c.strike ? "line-through" : "none" }}>
                          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {inst.name}
                          </span>
                          {/* A tag that is somebody. The slug is all the row
                              can say by itself — `kaguya_shinomiya` does not
                              tell you it is a person, let alone which one. */}
                          <KindMarks
                            subject={subjectByTag.get(inst.name) ?? null}
                            place={placeByTag.get(inst.name) ?? null}
                            event={eventByTag.get(inst.name) ?? null}
                            faces={facesBySubject.get(
                              subjectByTag.get(inst.name)?.id ?? -1) ?? []}
                            onGo={onShowKind
                              ? (what) => onShowKind(what, inst.name) : undefined}
                          />
                          <DescriptionMark descriptions={described?.[inst.name]?.descriptions}
                                           name={inst.name} size={13} />
                        </span>
                        {range && (
                          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)", whiteSpace: "nowrap" }}>
                            {formatTimecode(range.time_start as number, fileFps, true)}
                            {range.time_end != null && ` – ${formatTimecode(range.time_end, fileFps, true)}`}
                          </span>
                        )}
                      </span>
                      {/* Boxes with geometry only: the ranges are rows now. */}
                      {(inst.boxes ?? []).some((b) => b.x != null) && (
                        <TagAnnotation
                          boxes={(inst.boxes ?? []).filter((b) => b.x != null)}
                          activeFileId={detail.active_file_id}
                          activeFile={activeFile}
                          onOpen={() => openAnnotator(itemId, inst.name, inst.group_id ?? null)}
                        />
                      )}
                      {!readOnly && (
                        // OVER the content, not beside it: the name keeps the
                        // whole row's width, and the actions appearing cannot
                        // reflow it. The backdrop is the row's own background
                        // with a soft left fade (the caption card's shape), so
                        // whatever the ✕ covers fades out instead of showing
                        // through the glyph.
                        <span className="row-action-fixed" style={{
                          position: "absolute", right: 4, top: "50%",
                          transform: "translateY(-50%)",
                          display: "flex", alignItems: "center", gap: 1,
                          paddingLeft: 2, borderRadius: "var(--r-2)",
                          background: isSel
                            ? "linear-gradient(var(--accent-dim), var(--accent-dim)), var(--panel-2)"
                            : "var(--panel-2)",
                          boxShadow: `-6px 0 6px 0 ${isSel ? "var(--accent-dim)" : "var(--panel-2)"}`,
                        }}>
                          {/* Approving is about THIS instance, so the test is
                              which group it is in — `pending` is a fact about
                              the (item, tag) PAIR, and a tag can legitimately
                              have a pending copy here and an approved instance
                              somewhere else (a machine finding a box for a tag
                              you already placed, or a copy dragged out into a
                              real group). Reading the pair put a green "move
                              it out of Pending" on the row that was already
                              out of it. */}
                          {grp.system && inst.placement_id != null && (
                            <IconButton icon="check_circle" size={20} reveal="hover" color="var(--green)"
                              title="Approve this tag (move it out of Pending)"
                              onClick={(e) => { e.stopPropagation(); approvePlacement(inst.placement_id as number); }} />
                          )}
                          {guessed.length > 0 ? (<>
                            <IconButton icon="check_circle" size={20} reveal="hover" color="var(--green)"
                              title={t("Accept the guess")}
                              onClick={(e) => {
                                e.stopPropagation();
                                void undoRun(t("Accept the guess"), () => Promise.all(guessed.map(
                                  (g) => api.editAppearance(g.appearance, { confirm: true })))
                                  .then(answered));
                              }} />
                            <IconButton icon="person_off" size={20} reveal="hover" tone="danger"
                              title={t("Reject the guess")}
                              onClick={(e) => {
                                e.stopPropagation();
                                void undoRun(t("Reject the guess"), () => Promise.all(guessed.map(
                                  (g) => api.unnameFace(g.face, guessSub?.id as number)))
                                  .then(answered));
                              }} />
                          </>) : (
                          <IconButton icon="close" size={20} reveal="hover" tone="danger"
                            title={range ? t("Remove this time range")
                              : grp.system ? t("Dismiss this pending tag")
                              : inst.placement_id == null ? t("Remove tag") : t("Remove from this group")}
                            onClick={(e) => {
                              e.stopPropagation();
                              if (range) removeRange(inst, range); else removeInstance(inst);
                            }} />
                          )}
                        </span>
                      )}
                    </div>
                  );
                };
                return (<>
                  {rows.map(renderRow)}
                  {/* WHAT THE HIDE RULE IS KEEPING BACK, at the foot of the
                      group it belongs to — the media panel's hidden-tracks
                      reveal in the tag list's terms. Per GROUP, because a
                      single figure over the whole list could not say which
                      box to look in, and because revealing every group at
                      once is what switching the option off already does.
                      Revealed, they come back BELOW this line rather than
                      back among the others: they are a block, and the line
                      is its heading. They are ORDINARY rows there — they
                      select, flip and drag like any other, and `orderKeys`
                      puts them in the reading order so a shift-range walks
                      through them. */}
                  {heldRows.length > 0 && (
                    <button
                      onClick={toggleShowNeg}
                      style={{
                        marginTop: 2, alignSelf: "flex-start", fontSize: "var(--fs-2)",
                        color: "var(--accent)", background: "transparent",
                        border: "none", cursor: "pointer", padding: "2px 0",
                        display: "flex", alignItems: "center", gap: 4,
                      }}
                    >
                      <Icon name={showNeg ? "expand_less" : "expand_more"}
                        size={15} />
                      {showNeg
                        ? tn({ one: "Hide 1 negative tag",
                               other: "Hide {n} negative tags" }, heldRows.length)
                        : tn({ one: "Show 1 negative tag",
                               other: "Show {n} negative tags" }, heldRows.length)}
                    </button>
                  )}
                  {showNeg && heldRows.map(renderRow)}
                </>);
                })()}
              </div>
            </div>
          );
        })}

        {/* Read-only indirect tag groups: assigned by a library group, entailed
            by another tag's implications, or inherited from a sequence's
            members. Tags also assigned directly are greyed + struck (overridden). */}
        {indirectSections.map((sec) => (
          <div
            key={`ind:${sec.source}:${sec.label}`}
            style={{ border: "1px solid var(--border)", background: "var(--panel-3)", borderRadius: "var(--r-5)", padding: 8 }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
              <Icon
                name={sec.source === "parent" ? "account_tree" : sec.source === "sequence" ? "burst_mode" : "folder"}
                size={14}
                color="var(--muted-2)"
              />
              <span
                style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-2)", fontWeight: 600, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={sec.source === "parent" ? "Implied by another tag"
                  : sec.source === "sequence" ? "Inherited from the sequence's members"
                  : `Assigned by group ${sec.label}`}
              >
                {sec.label}
              </span>
              <Count n={sec.tags.length} size={10} tone="muted-2" />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {sec.tags.map((tag) => {
                // Active read-only tags look like normal tags (just no
                // controls); an overridden one is GREYED. Not struck through:
                // a strike says the tag does not apply, and an overridden
                // implication is a tag the item very much has — it is only
                // this row that is redundant, because a direct assignment says
                // the same thing louder. The strike is kept for a NEGATIVE
                // tag, where it means what it says.
                const c = stateColors(tag.negative ? "neg" : "pos");
                // Only the HIERARCHY section: a library group's tags and a
                // sequence's are assigned for the whole item and have no
                // stretch, which is the same reason `impliedFilter` is
                // parent-only.
                const when = sec.source === "parent"
                  ? impliedRangeLabel?.(tag.via) ?? null : null;
                return (
                  <div key={tag.name} style={{ display: "flex",
                    flexDirection: "column", minWidth: 0 }}>
                  <div
                    className="hoverable"
                    title={tag.overridden ? "Overridden by a direct assignment" : undefined}
                    style={{ display: "flex", alignItems: "center", gap: 9, height: 28, boxSizing: "border-box", padding: "0 6px 0 8px", borderRadius: "var(--r-4)", background: "var(--panel-2)", border: "1px solid var(--border)", opacity: tag.overridden ? 0.55 : 1 }}
                  >
                    <span style={{ width: 9, height: 9, borderRadius: 2, flex: "0 0 9px", background: c.dot, opacity: tag.overridden ? 0.5 : 1 }} />
                    <span style={{ flex: "0 1 auto", minWidth: 0, fontFamily: "var(--mono)", fontSize: "var(--fs-3)", color: tag.overridden ? "var(--muted-2)" : c.text, textDecoration: c.strike ? "line-through" : "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {tag.name}
                    </span>
                    {/* The assigned tag(s) that entail this one (hierarchy only). */}
                    {tag.via.length > 0 && (
                      <span
                        title={`Implied by ${tag.via.join(", ")}`}
                        style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 2, justifyContent: "flex-end", fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                      >
                        <Icon name="subdirectory_arrow_left" size={11} color="var(--muted-3)" />
                        {tag.via.join(", ")}
                      </span>
                    )}
                    {/* AN IMPLIED TAG CAN BE TAKEN OFF (owner 2026-09): the
                        entailment stands, so what the ✕ writes is the
                        item's own NO — a negative assignment of that tag,
                        which vetoes the implication for this picture and
                        moves the row up into the direct tags, struck. Only
                        the hierarchy's rows: a library group's tags and a
                        sequence's come from elsewhere and are answered
                        there. Nothing to say over one that is already
                        overridden or negative. */}
                    {!readOnly && sec.source === "parent" && !tag.overridden && !tag.negative && (
                      <IconButton icon="close" size={20} reveal="hover" tone="danger"
                        title={t("Remove — the item gets this tag negatively")}
                        onClick={(e) => {
                          e.stopPropagation();
                          void undoRun(`${t("Removed")} ${tag.name}`, () =>
                            api.assignItemTag(itemId, tag.name, true).then(() => refresh()));
                        }} />
                    )}
                  </div>
                  {/* Under the row, indented to its NAME (8px padding + the
                      9px dot + the 9px gap) — the subject, place and event
                      rows' own treatment, so one fact looks the same
                      wherever it is stated. */}
                  <TagRangeLine label={when} indent={26} />
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {/* One drop zone per SUBJECT on the item, beside the new-group one:
            a picture with two people wants a group each, and those are the
            groups worth offering. Dropping here creates the group already
            bound to that identity. */}
        {!readOnly && dragging && (detail.subjects ?? [])
          .filter((sub) => !(detail.tag_groups ?? [])
            .some((g) => (g.subjects ?? []).includes(sub.id)))
          .map((sub) => (
            <div
              key={`subj-${sub.id}`}
              onDragOver={(e) => { e.preventDefault(); setDropGroup(`s${sub.id}`); }}
              onDragLeave={(e) => { if (e.currentTarget === e.target && dropGroup === `s${sub.id}`) setDropGroup(null); }}
              onDrop={(e) => { e.preventDefault(); setDropGroup(null); setDragging(false); moveDraggedTo({ subject: sub }); }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                height: 36, borderRadius: "var(--r-5)", marginBottom: 6,
                border: `1px dashed ${dropGroup === `s${sub.id}` ? "var(--accent)" : "var(--border-strong)"}`,
                background: dropGroup === `s${sub.id}` ? "var(--accent-dim)" : "transparent",
                color: dropGroup === `s${sub.id}` ? "var(--accent)" : "var(--muted-2)",
                fontSize: "var(--fs-2)", fontWeight: 600,
              }}
            >
              <Icon name={RECORD_ICON.subject} size={15} />
              {sub.display_name || sub.tag}
            </div>
          ))}

        {/* A tag's own menu, at the pointer. The row carries a handle, a sign
            dot, its kind markers and a ✕ already, so a seventh control would
            not fit — and what belongs here is about the LIBRARY rather than
            about this item, which is exactly what a right-click is for. */}
        {tagMenu && (
          <PointerMenu
            at={tagMenu.at}
            onClose={() => setTagMenu(null)}
            actions={searchActionsFor(tagMenu.name)}
          />
        )}

        {/* New-group drop zone — appears while dragging tag instances.
            ABOVE the Scores box, because that is where the new group will
            actually land: the Scores render last, and a target below them
            promised a position the drop does not produce. */}
        {!readOnly && dragging && (
          <div
            onDragOver={(e) => { e.preventDefault(); setDropGroup("new"); }}
            onDragLeave={(e) => { if (e.currentTarget === e.target && dropGroup === "new") setDropGroup(null); }}
            onDrop={(e) => { e.preventDefault(); setDropGroup(null); setDragging(false); moveDraggedTo("new"); }}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
              height: 40, borderRadius: "var(--r-5)",
              border: `1px dashed ${dropGroup === "new" ? "var(--accent)" : "var(--border-strong)"}`,
              background: dropGroup === "new" ? "var(--accent-dim)" : "transparent",
              color: dropGroup === "new" ? "var(--accent)" : "var(--muted-2)",
              fontSize: "var(--fs-2)", fontWeight: 600,
            }}
          >
            <Icon name="create_new_folder" size={15} />
            Drop here to create a new group
          </div>
        )}


      </div>
    </CollapsibleSection>
  );
}

function EditableTagGroupName({
  name, readOnly, onSaved,
}: {
  name: string;
  readOnly?: boolean;
  onSaved: (v: string) => void;
}) {
  const [val, setVal] = useState(name);
  useEffect(() => setVal(name), [name]);
  const commit = () => {
    const v = val.trim();
    if (!v || v === name) { setVal(name); return; }
    onSaved(v);
  };
  // Enter leaves the field (the blur is the save); Escape puts the name
  // back and leaves without saving.
  const keys = useInlineEdit({ commit, cancel: () => setVal(name), blurOnEnter: true });
  return (
    <input
      value={val}
      readOnly={readOnly}
      onChange={(e) => setVal(e.target.value)}
      onBlur={keys.onBlur}
      onKeyDown={(e) => {
        keys.onKeyDown(e);
        if (e.key === "Escape") (e.target as HTMLInputElement).blur();
      }}
      style={{ flex: 1, minWidth: 0, background: "transparent", border: "none", color: "var(--text-bright)", fontSize: "var(--fs-2)", fontWeight: 600, fontFamily: "var(--sans)", outline: "none", padding: "2px 0" }}
    />
  );
}

/**
 * WHO, WHERE and WHEN over a MULTI-SELECTION.
 *
 * A subject, a place and an event are each extra data on a TAG, so across
 * several pictures they are exactly the aggregate the tag list already knows
 * how to show — and they read by the GROUPS rule: normal when every selected
 * picture carries it, YELLOW when only some do, with the count spelled out
 * beside it. "3 / 8" says how much of the work is left, where the colour
 * alone only says "not all".
 *
 * A component of its own rather than a mode of the three per-item sections,
 * because what those show is a different KIND of fact: an identity's state IN
 * one picture — which face is hers, how old she is in it, which of the
 * event's venues — is not something a selection has one answer for. What a
 * selection does share is the ASSIGNMENT, which is all this shows.
 *
 * One write for the whole selection (`quickAssign`), so adding somebody to
 * forty pictures is one request; the rows report to the selection bar like
 * every other list here, so Remove takes the tag off every one of them.
 */
function MultiKindTags({ kind, itemIds, itemsById, catalog, readOnly,
                        topAction, onChange }: {
  kind: "subject" | "place" | "event";
  itemIds: number[];
  itemsById: Map<number, { direct_tags: TagAssignment[]; group_ids: number[] }>;
  /** This kind's catalog, already labelled by whoever knows how to format one
   *  (an address is not a slug, and a person is not their tag). */
  catalog: { tag: string; label: string; comment?: string }[];
  readOnly?: boolean;
  /** What sits at the top of this list — Detect faces, on Subjects. The
   *  single-item sections take one too, and it is the same offer: a run over
   *  a selection is exactly what the batch job is for. */
  topAction?: React.ReactNode;
  onChange: () => void;
}) {
  const tr = useT();
  const undoRun = useUndoRun();
  // The record namespaces, for the bracket-split create below.
  const { data: speSettings } = useQuery({
    queryKey: ["settings"], queryFn: api.getSettings });
  const byTag = useMemo(
    () => new Map(catalog.map((c) => [c.tag, c.label])), [catalog]);
  const n = itemIds.length;
  // Past a thousand items an edit is worth a question before a thousand
  // writes; below that it just runs. GroupsSection's rule, verbatim.
  const confirmBig = async () =>
    n <= BIG_EDIT || confirm({ title: tr("Apply this to {n} items?", { n: String(n) }),
                               answer: { label: tr("Apply") } });

  const rows = useMemo(() => {
    const counts = new Map<string, number>();
    for (const id of itemIds) {
      for (const a of itemsById.get(id)?.direct_tags ?? []) {
        // A NEGATIVE assignment is the opposite claim, not a weaker one, so it
        // is not a partial anything — it simply does not put the person in the
        // picture.
        if (a.negative || !byTag.has(a.name)) continue;
        counts.set(a.name, (counts.get(a.name) ?? 0) + 1);
      }
    }
    return [...counts.entries()]
      .map(([tag, cnt]) => ({ tag, cnt, partial: cnt < n,
                              label: byTag.get(tag) ?? tag }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [itemIds, itemsById, byTag, n]);

  const sel = useRowSelect(rows.map((r) => `${kind}:${r.tag}`));
  const clearSel = sel.clear;
  // A selection that outlives the items it was about is a Remove aimed at
  // another picture's rows.
  useEffect(() => { clearSel(); }, [itemIds, clearSel]);

  const write = async (tags: string[], remove: boolean) => {
    if (!tags.length || !(await confirmBig())) return;
    // ONE bulk request per (up to) 1000 items rather than a write per (item,
    // tag) pair; the server logs the same per-item events, so History and
    // revert are unchanged. Sequential chunks keep the writes from racing on
    // the single SQLite connection.
    // The names go in `positive` in BOTH directions — `remove` deletes the
    // assignment whatever its sign, and it is the LISTS that say which tags
    // it is about. Sending an empty list with `remove: true` is a request
    // that means nothing and answers 200, which is how the first version of
    // this looked exactly like a Remove button that did not work.
    await runBulk(chunks(itemIds, 1000),
                  (ids) => api.quickAssign({ item_ids: ids, positive: tags,
                                             negative: [], remove }),
                  { chunk: 1 });
    onChange();
  };
  const removeSelected = async () => {
    const picked = sel.selected.map((k) => k.slice(kind.length + 1));
    if (!picked.length) return;
    clearSel();
    await write(picked, true);
  };
  // The id is the TAB's, so the bar names the list you are looking at — and
  // the per-item sections report through `usePeopleSelection` under the same
  // names, which is safe because only one of the two is ever on screen.
  useReportSelection(`${kind}s`, readOnly ? null : {
    count: sel.selected.length,
    total: rows.length,
    onSelectAll: sel.selectAll,
    onRemove: removeSelected,
    onClear: clearSel,
    removeTitle: tr("Take these off every selected item"),
  });

  const here = useMemo(() => new Set(rows.map((r) => r.tag)), [rows]);
  const options = useMemo(
    () => catalog.filter((c) => c.tag && !here.has(c.tag))
      // The comment leads — it is the human half; the tag is machinery.
      .map((c) => ({ name: c.label,
                     comment: [c.comment, c.tag].filter(Boolean).join(" · "),
                     uses: 0 })),
    [catalog, here]);
  const [adding, setAdding] = useState("");
  const qcMulti = useQueryClient();
  const add = async (text: string) => {
    const typed = text.trim();
    if (!typed) return;
    const low = typed.toLowerCase();
    const hit = catalog.find((c) => c.tag === typed
                                 || c.label.toLowerCase() === low);
    setAdding("");
    if (hit) {
      await write([hit.tag], false);
      return;
    }
    // CREATE from the typed text — the same parity the single-item sections
    // have (a subject from a name, a place from its address line, an event
    // from its name), then assign the minted tag to the whole selection.
    // The finer record data (faces, dates, coordinates) still lives in the
    // per-item sections and the editors.
    // A trailing bracket splits into name + comment, with the bracketed
    // slug — "Traveler (Genshin Impact)" lands as the two fields it means
    // and the tag keeps saying which one it is (the record overlays' rule).
    const sp = splitBracketed(typed);
    const pfx = (key: "subject" | "place" | "event") =>
      speSettings?.[`${key}_tag_prefix`] ?? "";
    const extra = (key: "subject" | "place" | "event") => sp.comment ? {
      comment: sp.comment,
      tag: `${pfx(key)}${bracketSlug(sp.name, sp.comment)}`,
    } : {};
    let tag = "";
    if (kind === "subject") {
      const rows = await api.createSubject({
        display_name: sp.name, ...extra("subject") });
      tag = rows.find((x) => x.display_name === sp.name)?.tag ?? "";
      qcMulti.invalidateQueries({ queryKey: ["subjects"] });
    } else if (kind === "place") {
      const rows = await api.createPlace({
        name: sp.name, ...extra("place") });
      tag = rows.find((x) => x.name === sp.name)?.tag ?? "";
      qcMulti.invalidateQueries({ queryKey: ["places"] });
    } else {
      const rows = await api.createEvent({
        display_name: sp.name, ...extra("event") });
      tag = rows.find((x) => x.display_name === sp.name)?.tag ?? "";
      qcMulti.invalidateQueries({ queryKey: ["events"] });
    }
    if (tag) await write([tag], false);
  };

  const icon = RECORD_ICON[kind];
  const empty = kind === "subject" ? tr("Nobody yet.")
    : kind === "place" ? tr("Nowhere in particular yet.") : tr("No event yet.");

  return (
    <div>
      {topAction && <div style={{ marginBottom: 10 }}>{topAction}</div>}
      {!readOnly && (
        <div style={{ marginBottom: 8 }}>
          <TagAutocomplete
            value={adding}
            onChange={setAdding}
            suggestions={options}
            // freeText is what lets a DISPLAY NAME be typed at all: the tag
            // field's sanitizer turned the space in "Alice Meyer" into an
            // underscore, so the list emptied on the first space of every
            // real name — which read as "the autocomplete is empty".
            freeText
            placeholder={kind === "subject" ? tr("Add a person…")
              : kind === "place" ? tr("Add a place…") : tr("Add an event…")}
            onCommit={(name) => void add(name)}
          />
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 4,
                    userSelect: "none" }}>
        {rows.map((r) => {
          const picked = sel.has(`${kind}:${r.tag}`);
          return (
            <div key={r.tag} {...sel.props(`${kind}:${r.tag}`)}
              className="hoverable"
              style={{
                display: "flex", alignItems: "center", gap: 9,
                position: "relative",
                height: 30, boxSizing: "border-box", padding: "0 6px 0 8px",
                borderRadius: "var(--r-4)", cursor: "pointer",
                background: rowBackground(picked, "var(--panel-3)"),
                border: `1px solid ${picked ? "var(--accent)" : "var(--border)"}`,
              }}>
              <Icon name={icon} size={15}
                color={r.partial ? "var(--yellow)" : "var(--muted-2)"} />
              <span title={r.tag} style={{
                flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                color: r.partial ? "var(--yellow-text)" : "var(--text-bright)",
                overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>{r.label}</span>
              {r.partial && (
                <span style={{ flex: "0 0 auto", fontFamily: "var(--mono)",
                               fontSize: "var(--fs-1)", color: "var(--yellow-text)" }}>
                  {r.cnt} / {n}
                </span>
              )}
              {!readOnly && (
                <span className="row-action-fixed" style={{
                  position: "absolute", right: 4, top: "50%",
                  transform: "translateY(-50%)",
                  display: "flex", alignItems: "center", gap: 1,
                  paddingLeft: 2, borderRadius: "var(--r-2)",
                  background: picked
                    ? "linear-gradient(var(--accent-dim), var(--accent-dim)), var(--panel-3)"
                    : "var(--panel-3)",
                  boxShadow: `-6px 0 6px 0 ${picked ? "var(--accent-dim)" : "var(--panel-3)"}`,
                }}>
                  {/* The yellow says the row is on only some of them; this is
                      the action that answers it, so it is offered exactly
                      where there is something left to give. */}
                  {r.partial && (
                    <IconButton icon="done_all" size={20} reveal="hover"
                      title={tr("Give it to all of them")}
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => { e.stopPropagation();
                                        void write([r.tag], false); }} />
                  )}
                  <IconButton icon="close" size={20} reveal="hover" tone="danger"
                    title={tr("Take it off every selected item")}
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation();
                      void undoRun(`${tr("Removed")} ${r.label}`,
                                   () => write([r.tag], true));
                    }} />
                </span>
              )}
            </div>
          );
        })}
        {rows.length === 0 && (
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>{empty}</div>
        )}
      </div>
    </div>
  );
}

/**
 * Editable list of directly-assigned tags for the current selection (one or
 * many images). Each row shows the aggregate state: green (all positive), red
 * (all negative), yellow (present on only some images or with mixed polarity).
 * Rows can be toggled positive/negative or removed on hover; all edits apply to
 * every selected image. When a single image is selected, tags inherited from
 * its groups are also listed (read-only, labelled with the group name), unless
 * that same tag is assigned directly (which overrides the group).
 */
function AssignedTags({
  itemIds,
  single,
  detail,
  itemsById,
  suggestions,
  fetchSuggestions,
  readOnly,
  topAction,
  hideHeader,
  onChange,
}: {
  itemIds: number[];
  single: number | null;
  detail: ItemDetail | null;
  itemsById: Map<number, { direct_tags: TagAssignment[]; group_ids: number[] }>;
  // The adder's suggestion source — a static catalog or a typing-driven
  // fetcher (see `GroupedTags`).
  suggestions?: TagSuggestion[];
  fetchSuggestions?: (q: string) => Promise<TagSuggestion[]>;
  readOnly?: boolean;
  // A "Generate tags" button rendered at the top of the section body.
  topAction?: React.ReactNode;
  // Drop the "Tags" heading when this is the sole content of the Tags tab.
  hideHeader?: boolean;
  onChange: () => void;
}) {
  const tr = useT();
  const setTagHighlight = useUI((s) => s.setTagHighlight);
  // The selection is `useRowSelect`'s, declared beside the row order below;
  // reached through a ref from the handlers above that declaration.
  const selRef = useRef<RowSelect | null>(null);
  const setSelected = (next: string[] | ((cur: string[]) => string[])) => selRef.current?.set(next);
  const listRef = useRef<HTMLDivElement>(null);

  // Direct-tag assignments per selected item. Prefer the fresh single-item
  // detail when available; fall back to the (shared) grid item cache otherwise.
  const directFor = (id: number): TagAssignment[] => {
    if (single != null && id === single && detail) return detail.direct_tags;
    return itemsById.get(id)?.direct_tags ?? [];
  };

  const n = itemIds.length;
  // A MULTI selection keeps the per-item TAG GROUPS rather than flattening
  // them away: the slim bulk details (`/api/items/details`) carry every
  // direct tag's placements, so the aggregate can show "Person A" holding
  // the union of what the selected items place there. The flat list below
  // stays as the fallback while this is in flight (and for one item, whose
  // grouped view is `GroupedTags`).
  const { data: slims } = useQuery({
    queryKey: ["item-slim-tags", [...itemIds].sort((a, b) => a - b).join(",")],
    queryFn: () => api.itemDetails(itemIds),
    enabled: n > 1 && n <= 500,
  });
  // Bounding-box / time-range annotations for the (single) item, keyed by tag
  // name, so a row can show a crop icon (with hover preview) and/or a time range.
  const boxesByName = useMemo(() => {
    const m = new Map<string, NonNullable<TagAssignment["boxes"]>>();
    if (single != null && detail) {
      for (const t of detail.tags) if (t.boxes?.length) m.set(t.name, t.boxes);
    }
    return m;
  }, [single, detail]);

  // All tag rows — direct and group-inherited — merged into one alphabetically
  // sorted list. Inherited tags are marked with the assigning group names and
  // can be flipped (which creates a direct override) but not directly removed.
  const rows = useMemo(() => {
    const counts = new Map<string, { pos: number; neg: number }>();
    for (const id of itemIds) {
      for (const t of directFor(id)) {
        const c = counts.get(t.name) ?? { pos: 0, neg: 0 };
        if (t.negative) c.neg += 1;
        else c.pos += 1;
        counts.set(t.name, c);
      }
    }
    const directNames = new Set(counts.keys());
    const out: UnifiedTagRow[] = [...counts.entries()].map(([name, c]) => {
      let state: TagState;
      if (c.pos === n && c.neg === 0) state = "pos";
      else if (c.neg === n && c.pos === 0) state = "neg";
      else state = "mixed";
      return { name, state, inherited: false, groups: [],
               ...(n > 1 ? { count: c.pos + c.neg, pos: c.pos, neg: c.neg }
                         : {}) };
    });

    if (single != null && detail) {
      const byName = new Map<string, { groups: string[]; negative: boolean }>();
      for (const g of detail.indirect) {
        for (const t of g.tags) {
          if (directNames.has(t)) continue; // a direct assignment overrides the group
          const cur = byName.get(t) ?? { groups: [], negative: g.negative };
          cur.groups.push(g.group_name);
          cur.negative = cur.negative || g.negative;
          byName.set(t, cur);
        }
      }
      for (const [name, info] of byName) {
        out.push({ name, state: info.negative ? "neg" : "pos", inherited: true, groups: info.groups });
      }
    }
    return out.sort((a, b) => a.name.localeCompare(b.name));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemIds, detail, itemsById, single, n]);

  // The grouped layout: (group name, tag) → in how many of the selected
  // items. A tag counts once per (item, group name); `null` is the
  // ungrouped section. States follow the flat rows' rule (pos when EVERY
  // selected item has it that way), with a k/N chip where k < N.
  const sections = useMemo(() => {
    if (!slims || n <= 1) return null;
    const byId = new Map(slims.items.map((it) => [it.id, it]));
    if (itemIds.some((id) => !byId.has(id))) return null;
    type Cell = { pos: number; neg: number };
    const cells = new Map<string, Map<string, Cell>>();  // group name → tag
    const sysNames = new Set<string>();
    for (const id of itemIds) {
      const it = byId.get(id)!;
      const gname = new Map(it.tag_groups.map((g) => [g.id, g.name]));
      for (const g of it.tag_groups) if (g.system) sysNames.add(g.name);
      const seen = new Set<string>();
      for (const inst of it.tag_instances) {
        const gn = inst.group_id != null
          ? gname.get(inst.group_id) ?? "" : "";
        const k = `${gn}\u0000${inst.name}`;
        if (seen.has(k)) continue;
        seen.add(k);
        const m = cells.get(gn) ?? new Map<string, Cell>();
        const c = m.get(inst.name) ?? { pos: 0, neg: 0 };
        if (inst.negative) c.neg += 1; else c.pos += 1;
        m.set(inst.name, c);
        cells.set(gn, m);
      }
    }
    const rowOf = (name: string, c: Cell): UnifiedTagRow => {
      let state: TagState;
      if (c.pos === n && c.neg === 0) state = "pos";
      else if (c.neg === n && c.pos === 0) state = "neg";
      else state = "mixed";
      return { name, state, count: c.pos + c.neg, pos: c.pos, neg: c.neg,
               inherited: false, groups: [] };
    };
    const named = [...cells.keys()].filter((g) => g !== "")
      // System (Pending) groups last — they are the machine's, not yours.
      .sort((a, b) => Number(sysNames.has(a)) - Number(sysNames.has(b))
        || a.localeCompare(b));
    return [
      { key: "", label: null as string | null, system: false,
        rows: [...(cells.get("") ?? new Map())].map(([nm, c]) => rowOf(nm, c))
          .sort((a, b) => a.name.localeCompare(b.name)) },
      ...named.map((g) => ({
        key: g, label: g, system: sysNames.has(g),
        rows: [...cells.get(g)!].map(([nm, c]) => rowOf(nm, c))
          .sort((a, b) => a.name.localeCompare(b.name)),
      })),
    ];
  }, [slims, itemIds, n]);

  // What the interaction machinery reads: the VISUAL order, keyed by
  // (group, name) — the row's identity, so a tag placed in two groups is two
  // rows that select apart. The FLIP and the sign still act on the NAME (a
  // sign is a fact about the assignment, not about one placement of it).
  const rowKeyOf = (secKey: string, name: string) => `${secKey}\u0000${name}`;
  const nameOfKey = (k: string) => k.slice(k.indexOf("\u0000") + 1);
  const secOfKey = (k: string) => k.slice(0, k.indexOf("\u0000"));
  const visRows = sections ? sections.flatMap((sec) => sec.rows) : rows;
  const order = sections
    ? sections.flatMap((sec) => sec.rows.map((r) => rowKeyOf(sec.key, r.name)))
    : rows.map((r) => rowKeyOf("", r.name));
  // THE SELECTION — the one row selection (`useRowSelect`): the paint, the
  // one click rule, the pruning; the rows' props are `sel.props`.
  const sel = useRowSelect(order);
  selRef.current = sel;
  const selected = sel.selected;

  // Reset selection whenever the displayed selection changes.
  useEffect(() => {
    setSelected([]);
  }, [itemIds]);

  // Mirror the selected tag rows into the store so the grid can highlight items
  // that carry the same tags *with the same sign*; clear on unmount. The
  // highlight is about NAMES — one entry per selected tag, however many of
  // its placements are picked.
  useEffect(() => {
    const stateByName = new Map(visRows.map((r) => [r.name, r.state]));
    setTagHighlight(
      [...new Set(selected.map(nameOfKey))]
        .map((name) => ({ name, negative: stateByName.get(name) === "neg" }))
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, setTagHighlight]);
  useEffect(() => () => setTagHighlight([]), [setTagHighlight]);


  // One quick-assign request covers the whole selection (the server loops the
  // item ids) — this used to be one request per item per tag.
  const add = async (name: string) => {
    if (itemIds.length === 0) return;
    await api.quickAssign({
      item_ids: itemIds, positive: [name], negative: [], remove: false });
    onChange();
  };
  const remove = async (keys: string[]) => {
    if (itemIds.length === 0 || keys.length === 0) return;
    if (sections && slims) {
      // A row is one PLACEMENT of a tag, so removing it follows the
      // single-item rule per selected item: a grouped row deletes that
      // item's placement in that group (the tag survives where it is
      // placed elsewhere), and an ungrouped row — a tag with no placement
      // — unassigns the tag from exactly the items holding it ungrouped.
      const wanted = keys.map((k) => ({ sec: secOfKey(k), name: nameOfKey(k) }));
      for (const it of slims.items) {
        if (!itemIds.includes(it.id)) continue;
        const gname = new Map(it.tag_groups.map((g) => [g.id, g.name]));
        for (const inst of it.tag_instances) {
          const gn = inst.group_id != null ? gname.get(inst.group_id) ?? "" : "";
          if (!wanted.some((w) => w.sec === gn && w.name === inst.name)) continue;
          if (inst.placement_id != null) {
            await api.deleteTagPlacement(inst.placement_id);
          } else {
            await api.unassignItemTag(it.id, inst.name);
          }
        }
      }
    } else {
      // Flat mode: removal deletes the assignment whatever its sign, so one
      // call takes every listed name off every selected item.
      await api.quickAssign({
        item_ids: itemIds, positive: keys.map(nameOfKey), negative: [],
        remove: true });
    }
    setSelected((sel) => sel.filter((k) => !keys.includes(k)));
    onChange();
  };
  const rowByName = useMemo(() => new Map(rows.map((r) => [r.name, r])), [rows]);
  // The direct sign a flip should write: a positive (or inherited-positive) tag
  // becomes negative; everything else becomes positive (which also "assigns to
  // all" for a mixed tag). Flipping an inherited tag writes a direct override
  // that then gains a remove button.
  const flipTarget = (r: UnifiedTagRow) =>
    r.inherited ? r.state !== "neg" : r.state === "pos";
  const flipRows = async (rawNames: string[]) => {
    const names = [...new Set(rawNames)];
    if (itemIds.length === 0 || names.length === 0) return;
    // Split by the sign each row flips TO, then one quick-assign carries both
    // lists for the whole selection.
    const positive: string[] = [];
    const negative: string[] = [];
    for (const nm of names) {
      const r = rowByName.get(nm);
      if (r) (flipTarget(r) ? negative : positive).push(nm);
    }
    if (positive.length + negative.length === 0) return;
    await api.quickAssign({ item_ids: itemIds, positive, negative, remove: false });
    onChange();
  };
  // Only direct tags can be removed; inherited ones have no direct assignment.
  const deletableSelected = selected.filter((k) => {
    const r = rowByName.get(nameOfKey(k));
    return sections != null || (r && !r.inherited);
  });

  const bulk = selected.length >= 2;
  // THE SAME BAR every other tab reports to — Select all, Delete, and the
  // flip as its extra verb — where one is listening; the header buttons
  // stay for the annotator, which renders this with no bar anywhere near.
  const hasBar = useSelectionBarSlot();
  useReportSelection("assigned-tags", readOnly ? null : {
    count: selected.length,
    total: order.length,
    onSelectAll: sel.selectAll,
    onClear: sel.clear,
    onRemove: () => remove(deletableSelected),
    removeLabel: tr("Delete"),
    removeTitle: tr("Delete the selected tags (inherited tags can't be removed here)"),
    removeIcon: "delete",
    removeCount: deletableSelected.length,
    extra: { icon: "swap_vert",
             title: tr("Flip positive / negative for the selected tags"),
             onClick: () => flipRows(selected.map(nameOfKey)) },
  });

  return (
    <CollapsibleSection
      title="Tags"
      sk="tags"
      hideHeader={hideHeader}
      actions={bulk && !readOnly && !hasBar && (
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button
            onClick={() => flipRows(selected.map(nameOfKey))}
            title={tr("Flip positive / negative for the selected tags")}
            style={{
              display: "flex", alignItems: "center", gap: 4, height: 22,
              padding: "0 8px", borderRadius: "var(--r-2)",
              border: "1px solid var(--border-strong)", background: "transparent",
              color: "var(--text-2)", cursor: "pointer", fontSize: "var(--fs-2)", fontWeight: 600,
            }}
          >
            <Icon name="swap_vert" size={15} />
            Flip {selected.length}
          </button>
          {deletableSelected.length > 0 && (
            <button
              onClick={() => remove(deletableSelected)}
              title={tr("Delete the selected tags (inherited tags can't be removed here)")}
              style={{
                display: "flex", alignItems: "center", gap: 4, height: 22,
                padding: "0 8px", borderRadius: "var(--r-2)",
                border: "1px solid var(--danger-border)",
                background: "var(--danger-dim)",
                color: "var(--danger)", cursor: "pointer",
                fontSize: "var(--fs-2)", fontWeight: 600,
              }}
            >
              <Icon name="delete" size={14} />
              Delete {deletableSelected.length}
            </button>
          )}
        </div>
      )}
    >
      {topAction && <div style={{ marginBottom: 10 }}>{topAction}</div>}
      {itemIds.length === 0 ? (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          Select one or more items to edit their tags.
        </div>
      ) : (
        <>
          {!readOnly && <TagAdder suggestions={suggestions}
            fetchSuggestions={fetchSuggestions}
            existing={[...new Set(visRows.map((r) => r.name))]} onAdd={add} />}

          <div
            ref={listRef}
            tabIndex={-1}
            onKeyDown={(e) => {
              if (readOnly) return;
              if ((e.key === "Delete" || e.key === "Backspace") && deletableSelected.length) {
                e.preventDefault();
                remove(deletableSelected);
              }
            }}
            style={{
              display: "flex", flexDirection: "column", gap: 4, outline: "none",
              userSelect: "none", WebkitUserSelect: "none",
            }}
          >
            {(sections
              ?? [{ key: "", label: null as string | null, system: false,
                    rows }]).map((sec) => (
              <React.Fragment key={sec.key || "~ungrouped"}>
                {sec.label != null && sec.rows.length > 0 && (
                  <div style={{ display: "flex", alignItems: "center", gap: 6,
                                marginTop: 6, padding: "0 2px",
                                fontSize: "var(--fs-1)", fontWeight: 600,
                                color: sec.system ? "var(--yellow-text)"
                                                  : "var(--muted)" }}>
                    <Icon name={sec.system ? "pending" : "folder"} size={12} />
                    {sec.label}
                  </div>
                )}
                {sec.rows.map((t) => renderRow(t, sec.key))}
              </React.Fragment>
            ))}

            {visRows.length === 0 && <EmptyState dense line={tr("No tags assigned.")} />}
          </div>
        </>
      )}
    </CollapsibleSection>
  );

  function renderRow(t: UnifiedTagRow, secKey: string) {
    {
      const rowKey = rowKeyOf(secKey, t.name);
      const isSel = selected.includes(rowKey);
              const c = stateColors(t.state);
              const flipTitle = t.inherited
                ? (t.state === "neg" ? tr("Add as positive on this image") : tr("Add as negative on this image"))
                : t.state === "mixed"
                  ? tr("Assign to all selected")
                  : t.state === "neg" ? tr("Make positive") : tr("Make negative");
      return (
                <div
                  key={rowKey}
                  className="hoverable"
                  {...sel.props(rowKey)}
                  onMouseDown={(e) => {
                    sel.props(rowKey).onMouseDown(e);
                    if (e.button !== 0 || e.shiftKey || e.metaKey || e.ctrlKey) return;
                    e.preventDefault();
                    // preventScroll: focusing a row that's scrolled out of view
                    // would otherwise yank the list to it, and the shift drags
                    // other rows under the cursor.
                    listRef.current?.focus({ preventScroll: true });
                  }}
                  title={t.inherited ? `Assigned via group ${t.groups.join(", ")}` : undefined}
                  style={{
                    display: "flex", alignItems: "center", gap: 9,
                    height: 30, boxSizing: "border-box", padding: "0 6px 0 8px",
                    borderRadius: "var(--r-4)",
                    background: rowBackground(isSel, "var(--panel-3)"),
                    border: `1px solid ${isSel ? "var(--accent)" : "var(--border)"}`,
                    cursor: "pointer",
                  }}
                >
                  <StateDot
                    color={c.dot}
                    dotOpacity={t.inherited ? 0.55 : 1}
                    flipTitle={flipTitle}
                    onFlip={readOnly ? undefined : () => flipRows([t.name])}
                  />
                  <span style={{ flex: "0 1 auto", minWidth: 0, fontFamily: "var(--mono)", fontSize: "var(--fs-3)", color: t.inherited ? "var(--text-3)" : c.text, textDecoration: c.strike ? "line-through" : "none", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {t.name}
                  </span>
                  {t.pos != null && t.neg != null
                   && t.pos > 0 && t.neg > 0 ? (
                    // MIXED SIGNS: the selection may well all carry the tag —
                    // what it disagrees about is the sign, so the numbers say
                    // the split rather than a coverage fraction ("3/3" would
                    // be true and say nothing).
                    <span style={{ flex: "0 0 auto", fontFamily: "var(--mono)",
                                   fontSize: "var(--fs-1)", color: "var(--muted-2)",
                                   whiteSpace: "nowrap" }}>
                      {t.pos}+ {t.neg}−
                    </span>
                  ) : t.count != null && t.count < n ? (
                    // PARTIAL COVERAGE, one sign: the same signed spelling —
                    // "2+" / "2−" — rather than a fraction, so the two chips
                    // read as one notation ("how many, which way") and the
                    // sign is visible without reading the dot.
                    <span style={{ flex: "0 0 auto", fontFamily: "var(--mono)",
                                   fontSize: "var(--fs-1)", color: "var(--muted-2)",
                                   whiteSpace: "nowrap" }}>
                      {t.pos != null && t.neg != null
                        ? (t.pos > 0 ? `${t.pos}+` : `${t.neg}−`)
                        : `${t.count}/${n}`}
                    </span>
                  ) : null}
                  {t.inherited && (
                    <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-1)", color: "var(--muted-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {t.groups.join(", ")}
                    </span>
                  )}
                  {!t.inherited && boxesByName.has(t.name) && detail && (
                    <TagAnnotation
                      boxes={boxesByName.get(t.name)!}
                      activeFileId={detail.active_file_id}
                      activeFile={detail.files.find((f) => f.active) ?? null}
                    />
                  )}
                  {/* Inherited tags have no direct assignment, so no remove
                      button; the flip control lives on the state dot (left). */}
                  {!readOnly && !t.inherited && (
                    <span className="row-actions" style={{ flex: "0 0 auto", marginLeft: "auto" }}>
                      <IconButton icon="close" size={20} reveal="hover" tone="danger"
                        title={tr("Remove tag")}
                        onClick={(e) => { e.stopPropagation(); remove([rowKey]); }} />
                    </span>
                  )}
                </div>
              );
    }
  }
}

/**
 * The groups the selected image(s) belong to. Mirrors the tag list: rows can be
 * multi-selected and removed on hover; an adder assigns any existing group. On
 * a multi-image selection a group present on only some images shows yellow, and
 * removing/adding applies to every selected image.
 */
function GroupsSection({
  itemIds,
  single,
  detail,
  itemsById,
  allGroups,
  inTrash,
  restoreGroups,
  hideHeader,
  onChange,
}: {
  itemIds: number[];
  single: number | null;
  detail: ItemDetail | null;
  itemsById: Map<number, { direct_tags: TagAssignment[]; group_ids: number[] }>;
  allGroups: GroupNode[];
  inTrash?: boolean;
  restoreGroups?: number[];
  hideHeader?: boolean;
  onChange: () => void;
}) {
  const tr = useT();
  // Past a thousand items an edit is worth a question before a thousand
  // writes; below that it just runs.
  const confirmBig = async () =>
    itemIds.length <= BIG_EDIT || confirm({
      title: tr("Apply this to {n} items?", { n: String(itemIds.length) }),
      answer: { label: tr("Apply") } });

  const groupsFor = (id: number): number[] => {
    if (single != null && id === single && detail) return detail.group_ids;
    return itemsById.get(id)?.group_ids ?? [];
  };

  const flat = useMemo(() => flattenGroupTree(allGroups), [allGroups]);
  const byId = useMemo(() => new Map(flat.map((g) => [g.id, g])), [flat]);
  // WHERE EACH GROUP SITS, and which names need saying so. `Group.name` is
  // not unique — a library can hold an "abc" inside an "abc" — so a row
  // showing the name alone can name two different groups, and this list is
  // where that bites: it says which groups a picture is IN, and two of them
  // reading the same is a list nobody can act on. The ancestors are only
  // drawn for a name more than one group in the library answers to, since
  // a path after every row is noise on the ordinary library where names are
  // already distinct.
  const paths = useMemo(() => {
    const out = new Map<number, string[]>();
    const names = new Map<string, number>();
    const walk = (nodes: GroupNode[], trail: string[]) => {
      for (const n of nodes) {
        out.set(n.id, trail);
        const k = n.name.toLowerCase();
        names.set(k, (names.get(k) ?? 0) + 1);
        walk(n.children ?? [], [...trail, n.name]);
      }
    };
    walk(allGroups, []);
    return { of: out, shared: names };
  }, [allGroups]);

  const n = itemIds.length;
  const rows = useMemo(() => {
    const counts = new Map<number, number>();
    for (const id of itemIds) {
      for (const gid of groupsFor(id)) counts.set(gid, (counts.get(gid) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([gid, cnt]) => {
        const g = byId.get(gid);
        const name = g?.name ?? `#${gid}`;
        const trail = paths.of.get(gid) ?? [];
        return {
          gid, partial: cnt < n,
          name,
          icon: g?.icon ?? "folder",
          color: g?.color ?? null,
          // Root-first, so it reads as the breadcrumb it is. Empty for a
          // top-level group — which is its own answer, and the only one it
          // has, next to a namesake that shows a path.
          trail: (paths.shared.get(name.toLowerCase()) ?? 0) > 1 ? trail : [],
        };
      })
      .sort((a, b) => a.name.localeCompare(b.name));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemIds, detail, itemsById, single, n, byId, paths]);

  // The SAME multi-select as the Subjects / Places / Events tabs: click,
  // ⌘-click, shift-range and press-and-drag, written once in `useRowSelect`.
  // This had its own click-or-⌘-click and nothing else, so a run of groups
  // could not be picked the way a run of people could — two dialects of one
  // gesture in one panel.
  const sel = useRowSelect(rows.map((r) => String(r.gid)));
  const selected = sel.selected.map(Number);
  // `useRowSelect` drops keys that are gone by itself, so only the change of
  // SUBJECT needs saying here: a selection that outlives the items it was
  // about is a Remove aimed at another picture's groups.
  const clearSel = sel.clear;
  useEffect(() => { clearSel(); }, [itemIds, clearSel]);
  useReportSelection("groups", {
    count: selected.length,
    total: rows.length,
    onSelectAll: sel.selectAll,
    onRemove: () => void removeGroups(selected),
    onClear: clearSel,
    removeTitle: "Take the selection out of these groups",
  });

  // WHICH PICTURES IN THE GRID ARE IN WHAT IS PICKED HERE — the tag list's
  // ring, one object along: picking a row raises the same question ("which
  // of the pictures on screen are in this too") and it should be answered
  // the same way. Keyed on the JOINED ids, since `selected` is a fresh array
  // every render; cleared on the way out, because a ring around a card with
  // no row behind it is a highlight nobody can turn off.
  const setGroupHighlight = useUI((s) => s.setGroupHighlight);
  const pickedKey = selected.join(",");
  useEffect(() => {
    setGroupHighlight(pickedKey ? pickedKey.split(",").map(Number) : []);
    return () => setGroupHighlight([]);
  }, [pickedKey, setGroupHighlight]);

  // "Select this group" — the row says the picture is in it; this is how you
  // get from there to the group itself. Setting the selection is the whole of
  // what a click in the tree does (the view follows it), and `groupFocus` is
  // the half the tree has to do for itself: expand the ancestors, scroll to
  // the row, flash it.
  const setSelectedGroups = useUI((s) => s.setSelectedGroups);
  const setGroupFocus = useUI((s) => s.setGroupFocus);
  const selectGroup = (gid: number) => {
    setSelectedGroups([gid]);
    setGroupFocus(gid);
  };

  const assignedIds = new Set(rows.map((r) => r.gid));

  // ONE bulk request per (up to) 1000 items instead of a write per (item,
  // group) pair; the server logs the same per-item events, so History and
  // revert are unchanged. Sequential chunks (runBulk chunk 1 over the runs)
  // keep the writes from racing on the single SQLite connection.
  const bulkMembership = (add: number[], remove: number[]) =>
    runBulk(chunks(itemIds, 1000),
            (ids) => api.bulkGroupMembership(ids, add, remove), { chunk: 1 });
  const addGroup = async (gid: number) => {
    if (!(await confirmBig())) return;
    await bulkMembership([gid], []);
    onChange();
  };
  // Create a brand-new top-level group and add the selection to it (mirrors the
  // "create tag" affordance in the tag adder).
  const createAndAdd = async (name: string) => {
    if (!(await confirmBig())) return;
    const g = await api.createGroup({ name: name.trim() });
    await bulkMembership([g.id], []);
    onChange();
  };
  const removeGroups = async (gids: number[]) => {
    if (gids.length === 0) return;
    if (!(await confirmBig())) return;
    await bulkMembership([], gids);
    sel.clear();
    onChange();
  };


  // In the Trash, groups can't be edited — instead show where the item(s) will
  // be restored to. For a single item that's the snapshot from `restoreGroups`;
  // for a multi-selection we don't have per-item snapshots, so keep it simple.
  if (inTrash) {
    const targets = (restoreGroups ?? [])
      .map((gid) => byId.get(gid))
      .filter((g): g is GroupOption => !!g)
      .sort((a, b) => a.name.localeCompare(b.name));
    return (
      <div style={{ marginTop: 16 }}>
        <label style={{ ...SECTION_LABEL, letterSpacing: "0.04em" }}>Restores to</label>
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
          {single == null ? (
            <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
              Select a single item to see where it will be restored.
            </div>
          ) : targets.length === 0 ? (
            <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
              Will be restored without any group.
            </div>
          ) : (
            targets.map((g) => (
              <div
                key={g.id}
                style={{
                  display: "flex", alignItems: "center", gap: 9,
                  height: 30, boxSizing: "border-box", padding: "0 8px",
                  borderRadius: "var(--r-4)", background: "var(--panel-3)", border: "1px solid var(--border)",
                }}
              >
                <Icon name={g.icon} size={15} color={g.color || "var(--muted-2)"} />
                <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)", color: "var(--text-bright)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {g.name}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    );
  }

  return (
    <CollapsibleSection title="Groups" sk="groups" hideHeader={hideHeader}>
      {itemIds.length === 0 ? (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          Select one or more items to edit their groups.
        </div>
      ) : (
        <>
          <GroupAdder options={flat} assigned={assignedIds} onAdd={addGroup} onCreate={createAndAdd} />
          <div style={{ display: "flex", flexDirection: "column", gap: 4, userSelect: "none" }}>
            {rows.map((r) => {
              const isSel = selected.includes(r.gid);
              return (
                <div
                  key={r.gid}
                  className="hoverable"
                  {...sel.props(String(r.gid))}
                  style={{
                    display: "flex", alignItems: "center", gap: 9,
                    height: 30, boxSizing: "border-box", padding: "0 6px 0 8px",
                    borderRadius: "var(--r-4)",
                    background: rowBackground(isSel, "var(--panel-3)"),
                    border: `1px solid ${isSel ? "var(--accent)" : "var(--border)"}`,
                    cursor: "pointer",
                  }}
                >
                  <Icon name={r.icon} size={15} color={r.partial ? "var(--yellow)" : (r.color || "var(--muted-2)")} />
                  {/* The name keeps its natural width and the PATH yields —
                      the Tags tab's name-row rule: flex shrinks items in
                      proportion to their own size, so a long path would
                      otherwise eat the name it exists to disambiguate. */}
                  <span style={{ flex: 1, minWidth: 0, display: "flex",
                                 alignItems: "baseline", gap: 6 }}>
                    <span style={{ flex: "0 0 auto", maxWidth: "100%", fontSize: "var(--fs-3)", color: r.partial ? "var(--yellow-text)" : "var(--text-bright)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {r.name}
                    </span>
                    {r.trail.length > 0 && (
                      <span
                        title={r.trail.join(" › ")}
                        style={{ flex: "0 20 auto", minWidth: 0, fontSize: "var(--fs-1)",
                                 color: "var(--muted-2)", overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                      >
                        {r.trail.join(" › ")}
                      </span>
                    )}
                  </span>
                  <span className="row-actions" style={{ flex: "0 0 auto", display: "flex", alignItems: "center" }}>
                    <span onClick={(e) => e.stopPropagation()}>
                      <RowMenu
                        title={tr("More")}
                        actions={[{
                          icon: "folder_open",
                          label: tr("Select this group"),
                          onClick: () => selectGroup(r.gid),
                        }]}
                      />
                    </span>
                    <IconButton icon="close" size={20} reveal="hover" tone="danger"
                      title="Remove from group"
                      onClick={(e) => { e.stopPropagation(); removeGroups([r.gid]); }} />
                  </span>
                </div>
              );
            })}
            {rows.length === 0 && <EmptyState dense line={tr("Not in any group.")} />}
          </div>
        </>
      )}
    </CollapsibleSection>
  );
}

/** Autocomplete input for adding the selection to an existing group — or, when
 *  the typed name matches none, creating a new group and adding to it. The
 *  list is the shared one (`useSuggestList`, `TagSuggestList`): a group name
 *  is not a tag, so the field takes no tag rule, and the Create row wears a
 *  folder. */
function GroupAdder({
  options,
  assigned,
  onAdd,
  onCreate,
}: {
  options: GroupOption[];
  assigned: Set<number>;
  onAdd: (id: number) => void;
  onCreate?: (name: string) => void;
}) {
  const t = useT();
  const [text, setText] = useState("");
  const q = text.trim().toLowerCase();
  const free = options.filter((o) => !assigned.has(o.id));
  // An empty field offers the whole (small) catalog.
  const matches = rankTagMatches(free, q, new Set<string>(), SUGGEST_CAP);
  // Offer to create a group when the exact name isn't already an option.
  const canCreate = !!onCreate && q.length > 0 &&
    !options.some((o) => o.name.toLowerCase() === q);
  const commit = (id: number) => { onAdd(id); setText(""); list.dismiss(); };
  const create = () => {
    if (!canCreate || !onCreate) return;
    onCreate(text.trim());
    setText("");
    list.dismiss();
  };
  const list = useSuggestList<GroupOption>({
    matches, create: canCreate ? text.trim() : null,
    onPick: (row) => {
      if (row.kind === "create") create();
      else if (row.kind === "match") commit(row.item.id);
    },
    // Escape with the list closed clears the field.
    input: { onCancel: () => setText("") },
  });
  const ref = useRef<HTMLInputElement>(null);
  const rect = useAnchorRect(ref, list.open);
  return (
    <div style={{ position: "relative", marginBottom: 8 }}>
      <input
        ref={ref}
        value={text}
        onChange={(e) => { setText(e.target.value); list.undismiss(); }}
        {...list.inputProps}
        placeholder={t("Add to a group…")}
        style={{
          width: "100%", height: 32, padding: "0 10px", background: "var(--bg)",
          border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)", color: "var(--text)",
          fontSize: "var(--fs-3)", outline: "none", boxSizing: "border-box",
        }}
      />
      {list.open && (
        <AnchoredDropdown rect={rect} minWidth={rect?.width ?? 220} fill>
          <TagSuggestList list={list} dense fill createIcon="create_new_folder"
            renderRow={(m) => (<>
              <Icon name={m.icon} size={14} color={m.color || "var(--muted-2)"}
                    style={{ marginLeft: m.depth * 12 }} />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.name}</span>
              {m.count > 0 && (
                <Count n={m.count} style={{ flex: "0 0 auto" }} />
              )}
            </>)} />
        </AnchoredDropdown>
      )}
    </div>
  );
}

/**
 * Editable captions for a single selected image: add, edit in place, delete,
 * and multi-select rows for bulk deletion. Captions are per-image, so this is
 * disabled when several images are selected.
 */

/** The meta-tag editor used by BOTH a link row and a caption: existing chips
 *  with a remove ✕, plus a capsule input with the arrow-key autocomplete of
 *  the shared meta-tag catalog (usage counts, and a Create "…" entry). Links
 *  and captions draw from one namespace, so they must also feel identical. */
function MetaTagAdder({ tags, tagOptions, onAdd, onRemove, readOnly, chipStyle }: {
  tags: string[];
  tagOptions: { name: string; count: number }[];
  onAdd: (name: string) => void;
  onRemove: (name: string) => void;
  readOnly?: boolean;
  /** "link" = accent pills (on a link row); "caption" = quieter chips. */
  chipStyle?: "link" | "caption";
}) {
  const tr = useT();
  const [tagInput, setTagInput] = useState("");
  const tagInputRef = useRef<HTMLInputElement>(null);
  const quiet = chipStyle === "caption";

  const addTag = (name: string) => {
    const v = sanitizeLinkTagInput(name.trim());
    if (v && !tags.includes(v)) onAdd(v);
    setTagInput("");
    list.dismiss();
  };
  const q = sanitizeLinkTagInput(tagInput.trim());
  // An empty field offers the whole catalog, less what the row carries.
  const matches = rankTagMatches(tagOptions, q, new Set(tags), SUGGEST_CAP);
  const canCreate = q.length > 0 && !tagOptions.some((o) => o.name.toLowerCase() === q) && !tags.includes(q);
  const list = useSuggestList<{ name: string; count: number }>({
    matches, create: canCreate ? q : null,
    onPick: (row) => {
      if (row.kind === "create") addTag(row.name);
      else if (row.kind === "match") addTag(row.item.name);
    },
    input: { onCommitTyped: () => { if (q) addTag(q); }, blurMs: 120 },
  });
  const acRect = useAnchorRect(tagInputRef, list.open);

  if (readOnly && tags.length === 0) return null;
  return (
    <div
      // Only what is IN the row swallows the click — a chip, its ✕, the add
      // field. The row itself is a full-width flex line, so stopping every
      // click here made the empty space after the tags a dead strip across the
      // bottom of the caption card: the one part of the card that looked most
      // like background was the one part that could not select it.
      onClick={(e) => { if (e.target !== e.currentTarget) e.stopPropagation(); }}
      style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 4 }}
    >
      {tags.map((t) => (
        <span
          key={t}
          style={{
            display: "inline-flex", alignItems: "center", gap: 2, height: 20,
            padding: "0 3px 0 8px", borderRadius: "var(--r-round)", fontSize: "var(--fs-1)",
            background: quiet ? "var(--panel-2)" : "var(--accent-dim)",
            color: quiet ? "var(--text-3)" : "var(--accent)",
            border: quiet ? "1px solid var(--border)" : "none",
          }}
        >
          {t}
          {!readOnly && (
            <span title={tr("Remove tag")} onClick={() => onRemove(t)} style={{ display: "flex", cursor: "pointer" }}>
              <Icon name="close" size={12} />
            </span>
          )}
        </span>
      ))}
      {!readOnly && (
      <span style={{ position: "relative", display: "inline-flex" }}>
        <input
          ref={tagInputRef}
          value={tagInput}
          onChange={(e) => { setTagInput(sanitizeLinkTagInput(e.target.value)); list.undismiss(); }}
          {...list.inputProps}
          placeholder={tr("+ tag")}
          style={{
            width: `${Math.max(4, tagInput.length + 3)}ch`, minWidth: 44, height: 20,
            padding: "0 8px", borderRadius: "var(--r-round)", outline: "none",
            border: "1px dashed var(--border-strong)", background: "var(--panel-2)",
            color: "var(--text-2)", fontSize: "var(--fs-1)",
          }}
        />
        {list.open && (
          <AnchoredDropdown rect={acRect} minWidth={150} fill>
            <TagSuggestList list={list} dense fill
              renderRow={(o) => (<>
                <span style={{ flex: 1, minWidth: 0 }}>{o.name}</span>
                <Count n={o.count} size={10} />
              </>)} />
          </AnchoredDropdown>
        )}
      </span>
      )}
    </div>
  );
}

/** One caption's meta tags — the SAME adder a link row uses, so the two
 *  (which share a namespace) also share their behaviour: chips with a ✕,
 *  a capsule input, arrow-key autocomplete with usage counts, Create "…". */
function CaptionTagRow({ itemId, caption, readOnly, onChange }: {
  itemId: number; caption: Caption; readOnly?: boolean; onChange: () => void;
}) {
  const { data: rows } = useQuery({
    queryKey: ["link-tag-rows"], queryFn: api.linkTagRows,
  });
  const options = (rows ?? []).map((r) => ({ name: r.name, count: r.count }));
  return (
    <div style={{ marginTop: 6 }}>
      <MetaTagAdder
        chipStyle="caption"
        readOnly={readOnly}
        tags={caption.tags ?? []}
        tagOptions={options}
        onAdd={(name) => {
          api.addCaptionTag(itemId, caption.id, name).then(onChange);
        }}
        onRemove={(name) => {
          api.removeCaptionTag(itemId, caption.id, name).then(onChange);
        }}
      />
    </div>
  );
}

/** A per-item tag group's meta tags — the SAME adder a link row and a caption
 *  use, since all three draw from one namespace. What it labels is the
 *  grouping ("Person A is the main character"), not the picture, which is why
 *  these never join the item's own tags. */
function TagGroupMetaTags({ groupId, tags, readOnly, onChange }: {
  groupId: number; tags: string[]; readOnly?: boolean; onChange: () => void;
}) {
  const tr = useT();
  const undoRun = useUndoRun();
  const { data: rows } = useQuery({
    queryKey: ["link-tag-rows"], queryFn: api.linkTagRows,
  });
  const options = (rows ?? []).map((r) => ({ name: r.name, count: r.count }));
  if (readOnly && tags.length === 0) return null;
  return (
    // Indented to the group NAME's left edge, exactly as the subject chips
    // above are (the header icon plus its gap). Both lines say something about
    // the GROUPING rather than listing its contents, so they are one block
    // under the title; at the box's own edge the meta tags lined up with the
    // tag rows below instead, which is the other claim.
    <div style={{ margin: "0 0 6px 20px" }}>
      <MetaTagAdder
        chipStyle="caption"
        readOnly={readOnly}
        tags={tags}
        tagOptions={options}
        // Logged and revertible on the server since they existed; what was
        // missing is that nothing offered them back.
        onAdd={(name) => void undoRun(tr("Tagged a tag group"),
          () => api.addTagGroupTag(groupId, name).then(onChange))}
        onRemove={(name) => void undoRun(tr("Untagged a tag group"),
          () => api.removeTagGroupTag(groupId, name).then(onChange))}
      />
    </div>
  );
}

//: The dataTransfer type a reference thumbnail carries. Distinct from the
//: grid's `application/x-mc-items`, because the two drops mean different
//: things: one ADDS pictures to an instruction, the other MOVES a reference
//: that already belongs to one.
const REF_MIME = "application/x-mc-caption-ref";

/** The reference being dragged right now, and everything the drop needs.
 *
 *  Module-level for the same reason the grid's own drag state is: a drop
 *  handler cannot read `dataTransfer` during dragover (the browser hides the
 *  payload until the drop), and the TARGET instruction has to know which
 *  caption the thumbnail came from and what that caption's list was — it is
 *  about to rewrite both ends. Cleared on dragend, and never read across a
 *  gesture. */
let CARRIED_REF: {
  captionId: number; itemId: number; index: number; from: number[];
} | null = null;

/** An instruction's reference images: the pictures it was made FROM, numbered,
 *  in the order the model is shown them.
 *
 *  Items are added by dropping them from the grid — the gesture the Links
 *  section already owns, down to reading `getDraggedItems()` during dragover
 *  (the dataTransfer payload is unreadable then) — and reordered by dragging a
 *  thumbnail, with an insertion line, like a sequence's members. A thumbnail
 *  dragged onto ANOTHER instruction MOVES it there: which pictures an
 *  instruction was made from is the thing being worked out, and doing that by
 *  removing from one list and re-adding to the other is two gestures for one
 *  idea. Both ends are rewritten in one runner, so one Undo puts both back.
 *  Every edit posts the WHOLE list: it is one ordered list, and taking all of
 *  it is what makes the undo "put the old one back".
 *
 *  Clicking a thumbnail SELECTS that picture in the grid — the same thing a
 *  Links row does, and the only way from a 52 px crop to the item it names.
 */
function InstructionRefs({ itemId, caption, readOnly, noGrid, onChange }: {
  itemId: number;
  caption: Caption;
  readOnly?: boolean;
  noGrid?: boolean;
  onChange: () => void;
}) {
  const tr = useT();
  const undoRun = useUndoRun();
  const refs = caption.refs ?? [];
  const [dropActive, setDropActive] = useState(false);
  const [error, setError] = useState("");
  // Which thumbnail is being carried, and where it would land. Local to the
  // gesture: the committed order is whatever the server last answered.
  const dragFrom = useRef<number | null>(null);
  const [dropAt, setDropAt] = useState<number | null>(null);
  // WHERE to draw the caret, in the strip's own coordinates. It used to be a
  // 2 px flex item between the thumbnails, which is 2 px plus another gap of
  // layout — so every picture after the pointer jumped sideways as the caret
  // appeared, moved and went, and the target kept sliding out from under the
  // cursor. Absolutely positioned, it costs nothing and nothing moves. The
  // point comes from the element the drag is over, so a strip that has
  // WRAPPED onto a second row marks the right one.
  const [dropMark, setDropMark] = useState<{ x: number; y: number } | null>(null);
  const stripRef = useRef<HTMLDivElement | null>(null);
  /** Remember the caret's place from the box it belongs beside. */
  const markAt = (box: DOMRect | null, side: "left" | "right") => {
    const strip = stripRef.current?.getBoundingClientRect();
    if (!strip || !box) { setDropMark(null); return; }
    setDropMark({
      // Centred in the gap, and 1 px back so the 2 px bar straddles it.
      x: (side === "left" ? box.left - 3 : box.right + 1) - strip.left,
      y: box.top - strip.top,
    });
  };
  /** The end of the list — the empty space after the last thumbnail. */
  const markAtEnd = () => {
    const last = stripRef.current?.querySelector<HTMLElement>(
      "[data-ref-thumb]:last-of-type");
    markAt(last?.getBoundingClientRect() ?? null, "right");
  };

  const flash = (msg: string) => {
    setError(msg);
    setTimeout(() => setError(""), 2600);
  };
  /** The insertion caret: a bar the height of a thumbnail, where the carried
   *  picture would land. Absolutely positioned (see `dropMark`) so it takes no
   *  layout, and `pointerEvents: none` so the position it marks stays
   *  reachable. */
  const dropCaret = dropMark && (
    <span aria-hidden style={{
      position: "absolute", left: dropMark.x, top: dropMark.y,
      width: 2, height: 52, borderRadius: 1,
      background: "var(--accent)", pointerEvents: "none",
    }} />
  );
  const write = (ids: number[], label: string) => void undoRun(
    label, () => api.setCaptionRefs(itemId, caption.id, ids).then(onChange));

  /** Take a reference off another instruction and put it in this one, at
   *  `at`. Both lists in ONE runner: it is one move, so it is one undo. */
  const takeFrom = (carried: NonNullable<typeof CARRIED_REF>, at: number) => {
    CARRIED_REF = null;
    dragFrom.current = null;
    setDropAt(null);
    setDropMark(null);
    if (carried.captionId === caption.id) return;
    if (carried.itemId === itemId) {
      flash(tr("An instruction cannot reference its own item."));
      return;
    }
    if (refs.some((r) => r.item_id === carried.itemId)) {
      flash(tr("Those pictures are already referenced."));
      return;
    }
    const mine = refs.map((r) => r.item_id);
    mine.splice(Math.max(0, Math.min(at, mine.length)), 0, carried.itemId);
    void undoRun(tr("Moved a reference"), async () => {
      await api.setCaptionRefs(
        itemId, carried.captionId,
        carried.from.filter((id) => id !== carried.itemId));
      await api.setCaptionRefs(itemId, caption.id, mine);
      onChange();
    });
  };

  /** A reference from ANOTHER instruction, mid-drag. */
  const foreign = () =>
    CARRIED_REF && CARRIED_REF.captionId !== caption.id ? CARRIED_REF : null;

  const addDropped = (dropped: number[]) => {
    const have = new Set(refs.map((r) => r.item_id));
    // The item itself is not one of its own sources, and an id already in the
    // list would only move it — which is what dragging a thumbnail is for.
    const fresh = dropped.filter((id) => id !== itemId && !have.has(id));
    if (!fresh.length) {
      flash(dropped.some((id) => id === itemId)
        ? tr("An instruction cannot reference its own item.")
        : tr("Those pictures are already referenced."));
      return;
    }
    write([...refs.map((r) => r.item_id), ...fresh], tr("Added references"));
  };

  const dragHasItems = (e: React.DragEvent) =>
    Array.from(e.dataTransfer.types).includes("application/x-mc-items");

  // A reorder committed once, on release, from the order the drag started on —
  // so nothing accumulates mid-gesture.
  const moveTo = (to: number) => {
    const from = dragFrom.current;
    dragFrom.current = null;
    setDropAt(null);
    setDropMark(null);
    if (from == null || to === from || to === from + 1) return;
    const ids = refs.map((r) => r.item_id);
    const [moved] = ids.splice(from, 1);
    ids.splice(to > from ? to - 1 : to, 0, moved);
    write(ids, tr("Reordered references"));
  };

  return (
    <div
      onClick={(e) => { if (e.target !== e.currentTarget) e.stopPropagation(); }}
      onDragOver={(e) => {
        if (readOnly) return;
        const own = dragFrom.current != null;
        if (!dragHasItems(e) && !foreign() && !own) return;
        e.preventDefault();
        setDropActive(true);
        // Past the last thumbnail there is only the strip itself — a
        // thumbnail stops its own dragover, so reaching here means the
        // pointer is in the empty space, and the end is what that means.
        if (own || foreign()) { setDropAt(refs.length); markAtEnd(); }
      }}
      onDragLeave={(e) => {
        // Only a real exit: dragleave also fires crossing into a child.
        if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
        setDropActive(false);
        setDropAt(null);
        setDropMark(null);
      }}
      onDrop={(e) => {
        setDropActive(false);
        if (readOnly) return;
        e.preventDefault();
        e.stopPropagation();
        const carried = foreign();
        if (carried) { takeFrom(carried, dropAt ?? refs.length); return; }
        if (dragFrom.current != null) { moveTo(dropAt ?? refs.length); return; }
        const raw = e.dataTransfer.getData("application/x-mc-items");
        if (!raw) return;
        try {
          const ids = JSON.parse(raw) as number[];
          if (Array.isArray(ids)) addDropped(ids);
        } catch { /* ignore malformed drag payload */ }
      }}
      style={{
        marginTop: 8, padding: refs.length ? 4 : "8px 10px", borderRadius: "var(--r-3)",
        border: `1px dashed ${dropActive ? "var(--accent)" : "var(--border)"}`,
        background: dropActive ? "var(--accent-dim)" : "transparent",
      }}
    >
      {refs.length === 0 ? (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          {noGrid ? tr("No reference images.")
                  : tr("Drop pictures here — the ones this was made from.")}
        </div>
      ) : (
        <div ref={stripRef}
          style={{ display: "flex", flexWrap: "wrap", gap: 4,
                   position: "relative" }}>
          {/* WHERE IT WOULD LAND, as a bar between the pictures — drawn OVER
              the strip rather than inside its flow, so nothing shifts as it
              appears and moves. It was a line inset into the thumbnail's own
              edge, which is 2 px of accent over whatever the picture happens
              to be there: invisible on a pale one, and part of the image
              rather than a gap opening up on any of them. */}
          {dropCaret}
          {refs.map((r, idx) => (
          <React.Fragment key={r.item_id}>
            <div
              data-ref-thumb=""
              title={r.name || undefined}
              draggable={!readOnly}
              onClick={(e) => {
                // The picture, in the grid. A reference is a 52 px crop with
                // a number on it, and this is the only way from it to the
                // item it names.
                e.stopPropagation();
                if (!noGrid) useUI.getState().setSelectedItems([r.item_id]);
              }}
              onDragStart={(e) => {
                dragFrom.current = idx;
                CARRIED_REF = {
                  captionId: caption.id, itemId: r.item_id, index: idx,
                  from: refs.map((x) => x.item_id),
                };
                e.dataTransfer.effectAllowed = "move";
                // The TYPE is what another instruction's dragover reads —
                // during a drag the payload itself is unreadable, so the
                // details ride in `CARRIED_REF`.
                e.dataTransfer.setData(REF_MIME, String(r.item_id));
                e.dataTransfer.setData("text/plain", String(r.item_id));
              }}
              onDragOver={(e) => {
                if (dragFrom.current == null && !foreign()) return;
                e.preventDefault();
                e.stopPropagation();
                const box = e.currentTarget.getBoundingClientRect();
                const before = e.clientX < box.left + box.width / 2;
                setDropAt(before ? idx : idx + 1);
                markAt(box, before ? "left" : "right");
              }}
              onDrop={(e) => {
                const carried = foreign();
                if (carried == null && dragFrom.current == null) return;
                e.preventDefault();
                e.stopPropagation();
                // Dropped ON a thumbnail, so it lands exactly there rather
                // than at the end — the order IS the training signal.
                if (carried) takeFrom(carried, dropAt ?? idx);
                else moveTo(dropAt ?? idx);
              }}
              onDragEnd={() => {
                dragFrom.current = null;
                CARRIED_REF = null;
                setDropAt(null);
                setDropMark(null);
              }}
              style={{
                position: "relative", width: 52, height: 52, borderRadius: "var(--r-2)",
                overflow: "hidden", background: "var(--panel-2)",
                border: "1px solid var(--border)",
                cursor: readOnly ? "default" : noGrid ? "grab" : "pointer",
                // Dimmed while it is the one being carried, so the caret
                // reads as where it is GOING rather than as a second copy.
                opacity: dragFrom.current === idx && dropAt != null ? 0.4 : 1,
              }}
            >
              {r.file_id != null && (
                <img
                  src={api.thumbUrl(r.file_id)}
                  alt=""
                  draggable={false}
                  style={{ width: "100%", height: "100%", objectFit: "cover" }}
                />
              )}
              {/* The ORDER is the training signal, so every thumbnail says
                  where it sits rather than leaving it to be counted. */}
              <span style={{
                position: "absolute", top: 0, left: 0, minWidth: 14,
                padding: "0 3px", borderBottomRightRadius: 5,
                background: "var(--panel)", color: "var(--text-2)",
                fontSize: "var(--fs-0)", fontWeight: 700, lineHeight: "14px",
                textAlign: "center",
              }}>{idx + 1}</span>
              {!readOnly && (
                <span
                  title={tr("Remove this reference")}
                  onClick={(e) => {
                    e.stopPropagation();
                    write(refs.filter((_, i) => i !== idx).map((x) => x.item_id),
                          tr("Removed a reference"));
                  }}
                  style={{
                    position: "absolute", top: 0, right: 0, width: 15, height: 15,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    background: "var(--panel)", borderBottomLeftRadius: 5,
                    color: "var(--muted-2)", cursor: "pointer",
                  }}
                >
                  <Icon name="close" size={11} />
                </span>
              )}
            </div>
          </React.Fragment>
          ))}
        </div>
      )}
      {error && (
        <div style={{ marginTop: 4, fontSize: "var(--fs-1)", color: "var(--yellow-text)" }}>
          {error}
        </div>
      )}
    </div>
  );
}

/** The words that differ between the two lists this one component renders.
 *  Spelled out per kind rather than assembled from a noun: "Add an
 *  instruction…" is not "Add a caption…" with a word swapped in every language
 *  this is translated into, and a translator needs the whole sentence. */
const CAPTION_WORDS = {
  caption: {
    title: "Captions",
    add: "Add caption",
    placeholder: "Add a caption…  (⌘/Ctrl+Enter)",
    empty: "No captions.",
    duplicate: "This caption already exists on this image.",
    editTitle: "Edit caption",
    deleteTitle: "Delete caption",
    removeTitle: "Delete the selected captions",
    pickOne: "Select a single item to edit captions.",
    pickAny: "Select an item to add captions.",
  },
  instruction: {
    title: "Instructions",
    add: "Add instruction",
    placeholder: "How was this made?…  (⌘/Ctrl+Enter)",
    empty: "No instructions.",
    duplicate: "This instruction already exists on this image.",
    editTitle: "Edit instruction",
    deleteTitle: "Delete instruction",
    removeTitle: "Delete the selected instructions",
    pickOne: "Select a single item to edit instructions.",
    pickAny: "Select an item to add instructions.",
  },
} as const;

/**
 * The CAPTIONS or INSTRUCTIONS tab over a MULTI-SELECTION: what the pictures
 * hold, as two numbers, and the two things worth doing to all of them at
 * once.
 *
 * Deliberately NOT the list. Eight pictures' captions are eight separate
 * statements about eight pictures — a flat run of them says nothing a
 * selection is asking, cannot be edited without knowing whose is whose, and
 * on a big selection is a wall. What a selection IS asking is how much of it
 * is described and how much is not, which is the pair of counts, and then
 * either to have the machine write the missing ones (Generate caption over
 * the lot) or to put the same sentence on every one of them.
 *
 * The add is one request writing one ordinary caption per item, so each
 * reverts on its own exactly as one typed into a single item does.
 */
function MultiCaptions({ kind, itemIds, slims, topAction, readOnly,
                         hideHeader, onChange }: {
  kind: CaptionKind;
  itemIds: number[];
  /** The bulk slim details the panel already fetches for a multi-selection;
   *  null while they are in flight or the selection is past the cap. */
  slims: ItemSlim[] | null;
  topAction?: React.ReactNode;
  readOnly?: boolean;
  hideHeader?: boolean;
  onChange: () => void;
}) {
  const tr = useT();
  const trn = useTn();
  const w = CAPTION_WORDS[kind];
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const trimmed = draft.trim();

  // The two numbers, off the rows the panel already has. `withAny` is the
  // one that answers "is this selection described yet"; the total says how
  // much there is to look at when you narrow to one.
  const { total, withAny } = useMemo(() => {
    let n = 0, items = 0;
    for (const it of slims ?? []) {
      const k = (it.captions ?? []).filter(
        (c: Caption) => (c.kind ?? "caption") === kind).length;
      n += k;
      if (k) items += 1;
    }
    return { total: n, withAny: items };
  }, [slims, kind]);

  const add = async () => {
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      await api.addCaptionBulk(itemIds, trimmed, kind);
      setDraft("");
      onChange();
    } finally {
      setBusy(false);
    }
  };

  return (
    <CollapsibleSection
      title={w.title}
      sk={kind === "instruction" ? "instructions" : "captions"}
      hideHeader={hideHeader}
    >
      {topAction && <div style={{ marginBottom: 10 }}>{topAction}</div>}
      <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", lineHeight: 1.5,
                    marginBottom: readOnly ? 0 : 8 }}>
        {slims == null ? tr("Counting…") : (
          <>
            {kind === "instruction"
              ? trn({ one: "1 instruction", other: "{n} instructions" }, total)
              : trn({ one: "1 caption", other: "{n} captions" }, total)}
            {" · "}
            {trn({ one: "on 1 of {k} pictures",
                   other: "on {n} of {k} pictures" },
                 withAny, { k: String(itemIds.length) })}
          </>
        )}
      </div>
      {!readOnly && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <AutoTextarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void add();
              }
            }}
            placeholder={tr(w.placeholder)}
            style={{
              width: "100%", padding: "8px 10px", background: "var(--bg)",
              border: "1px solid var(--border-strong)",
              borderRadius: "var(--r-4)", color: "var(--text)", fontSize: "var(--fs-3)",
              lineHeight: 1.45, outline: "none", boxSizing: "border-box",
              fontFamily: "inherit",
            }}
          />
          {trimmed.length > 0 && (
            <button
              onClick={() => void add()}
              disabled={busy}
              style={{
                alignSelf: "flex-start", height: 26, padding: "0 12px",
                borderRadius: "var(--r-3)", border: "none",
                background: busy ? "var(--border)" : "var(--accent)",
                color: busy ? "var(--muted)" : "var(--on-accent)",
                fontSize: "var(--fs-2)", fontWeight: 600,
                cursor: busy ? "default" : "pointer",
                display: "flex", alignItems: "center", gap: 5,
              }}
            >
              <Icon name="add" size={15} />
              {/* The button says WHO it writes to: over a selection this is
                  not "add a caption" but "add this one to all of them". */}
              {trn({ one: "Add to 1 picture", other: "Add to {n} pictures" },
                   itemIds.length)}
            </button>
          )}
        </div>
      )}
    </CollapsibleSection>
  );
}

/**
 * The TEXT tab over a multi-selection: how many of the pictures have been
 * read, and the button that reads the rest.
 *
 * The regions themselves are not shown, for `MultiCaptions`' reason and one
 * more of its own — a page's text is a TREE of blocks, lines and words in
 * the picture's own coordinates, which means nothing torn out of the picture
 * it was read from. What a selection can ask is how much of it has been
 * read, and `text_count` is on the wire for exactly that.
 */
function MultiText({ itemIds, slims, topAction, hideHeader }: {
  itemIds: number[];
  slims: ItemSlim[] | null;
  topAction?: React.ReactNode;
  hideHeader?: boolean;
}) {
  const tr = useT();
  const trn = useTn();
  const { total, withAny } = useMemo(() => {
    let n = 0, items = 0;
    for (const it of slims ?? []) {
      const k = it.text_count ?? 0;
      n += k;
      if (k) items += 1;
    }
    return { total: n, withAny: items };
  }, [slims]);
  return (
    <CollapsibleSection title="Text" sk="text" hideHeader={hideHeader}>
      {topAction && <div style={{ marginBottom: 10 }}>{topAction}</div>}
      <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", lineHeight: 1.5 }}>
        {slims == null ? tr("Counting…") : (
          <>
            {trn({ one: "1 text region", other: "{n} text regions" }, total)}
            {" · "}
            {trn({ one: "on 1 of {k} pictures",
                   other: "on {n} of {k} pictures" },
                 withAny, { k: String(itemIds.length) })}
          </>
        )}
      </div>
    </CollapsibleSection>
  );
}

/**
 * Both lists of an item's caption rows: the CAPTIONS that describe the picture
 * and the INSTRUCTIONS that say how it was made from others.
 *
 * One component with a `kind`, not two: the rows are the same row type with the
 * same meta tags, the same selection gesture and the same undo, and a second
 * copy is how two lists that are one list drift apart. What the kind changes is
 * the words, which list reports to the selection bar, and whether each card
 * carries its strip of reference images.
 */
export function CaptionsSection({
  itemId,
  captions,
  kind = "caption",
  multi,
  readOnly,
  noGrid,
  topAction,
  hideHeader,
  onChange,
}: {
  itemId: number | null;
  /** The item's WHOLE caption list; this section shows the rows of its kind. */
  captions: Caption[] | null;
  kind?: CaptionKind;
  multi: boolean;
  readOnly?: boolean;
  /** There is no item grid in this window (the annotator), so an instruction's
   *  empty reference strip stops telling somebody to drag pictures in from one.
   *  The drop handlers are left alone — no drag can start there. */
  noGrid?: boolean;
  // A "Generate caption" button rendered at the top of the section body.
  topAction?: React.ReactNode;
  // Drop the heading when this is the sole content of its own tab.
  hideHeader?: boolean;
  onChange: () => void;
}) {
  const tr = useT();
  const undoRun = useUndoRun();
  const w = CAPTION_WORDS[kind];
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [draft, setDraft] = useState("");
  /** What Duplicate last put in the box, so an untouched copy can stay quiet
   *  about being a duplicate. Null once anything else fills the draft. */
  const [prefill, setPrefill] = useState<string | null>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);

  // A caption row that predates the kind column reads as a description, which
  // is what it is.
  const rows = useMemo(
    () => (captions ?? []).filter((c) => (c.kind ?? "caption") === kind),
    [captions, kind]);

  // The SAME multi-select the other tabs have — click, ⌘-click, shift-range,
  // press-and-drag — rather than this section's own click-or-⌘-click. One
  // gesture, one definition.
  const sel = useRowSelect(rows.map((c) => String(c.id)));
  const selected = sel.selected.map(Number);
  const clearSel = sel.clear;
  useEffect(() => {
    clearSel();
    setEditingId(null);
  }, [itemId, clearSel]);

  // WHILE A CAPTION IS BEING TYPED, THE GRID SHOWS THE PICTURE LARGE.
  // Describing an image from a 200px sidebar thumbnail is describing it from
  // memory, and the one part of the window with room to show it is the grid
  // — which, while somebody is typing into the sidebar, is showing nothing
  // that is being used. The ask is a store field so the two panels need know
  // nothing about each other; the annotator renders this same section and
  // simply has no grid to read it, which is right, since the picture is
  // already on screen there.
  //
  // THE TRIGGER IS THE EDIT STATE — the very one Save and Cancel are drawn
  // from — and not FOCUS, which is what it was and which is too fragile to
  // hang a picture off: every click on a background, and every step between
  // search matches, is a blur, so the preview vanished and came back a frame
  // later. Writing a NEW caption counts too, and by the same rule: the draft
  // having text is state, where the add box merely having focus is not.
  //
  // A store field, so the two panels need know nothing about each other; the
  // annotator renders this same section and has no grid to read it, which is
  // right, since the picture is already on screen there.
  const setCaptionPreview = useUI((st) => st.setCaptionPreview);
  const wantPreview = itemId != null
    && (editingId != null || draft.trim() !== "");
  useEffect(() => {
    setCaptionPreview(wantPreview ? itemId : null);
  }, [wantPreview, itemId, setCaptionPreview]);
  // …and nothing may leave it standing over the grid.
  useEffect(() => () => setCaptionPreview(null), [setCaptionPreview]);
  // Two report ids, because both lists can be open at once and the second
  // would otherwise replace the first's report.
  useReportSelection(kind === "instruction" ? "instructions" : "captions",
                     readOnly ? null : {
    count: selected.length,
    total: rows.length,
    onSelectAll: sel.selectAll,
    onRemove: () => void removeCaptions(selected),
    onClear: clearSel,
    removeLabel: tr("Delete"),
    // A bin, because this one really does delete them — a ✕ over the word
    // "Delete" says two different things about the same button.
    removeIcon: "delete",
    removeTitle: tr(w.removeTitle),
  });

  // A picked INSTRUCTION points the grid at the pictures it was made from —
  // the same ring a picked link draws around the item at its other end, and
  // for the same reason: the references are 52 px crops, and "which of these
  // on screen is that?" is otherwise answerable only by opening one.
  const setPointed = useUI((s) => s.setPointedItemIds);
  const pointedRefs = useMemo(() => {
    if (kind !== "instruction") return [];
    const picked = new Set(selected);
    return Array.from(new Set(rows.filter((c) => picked.has(c.id))
      .flatMap((c) => (c.refs ?? []).map((r) => r.item_id))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, rows, selected.join(",")]);
  useEffect(() => {
    if (kind !== "instruction") return;
    setPointed(pointedRefs);
    // Nothing points at anything once this list is gone.
    return () => setPointed([]);
  }, [kind, pointedRefs, setPointed]);

  // Block adding a caption that already exists verbatim on this image.
  const trimmedDraft = draft.trim();
  const isDuplicate =
    trimmedDraft.length > 0 &&
    rows.some((c) => c.text.trim() === trimmedDraft);
  // …but do not SAY so while the box still holds exactly what Duplicate put
  // there. Of course it is a duplicate — that is what was asked for, and the
  // whole point of the copy is to edit it. Telling somebody their text clashes
  // before they have typed a character is scolding them for a button they
  // pressed. The Add button stays disabled throughout: the warning is about
  // when to speak, not about what is allowed.
  const untouchedCopy = prefill != null && draft === prefill;
  const warnDuplicate = isDuplicate && !untouchedCopy;

  const addCaption = async () => {
    const t = draft.trim();
    if (!t || itemId == null || isDuplicate) return;
    await api.addCaption(itemId, t, kind);
    setDraft("");
    onChange();
  };

  // Copy an existing caption into the add box so the user can tweak and add it.
  const duplicateToDraft = (text: string) => {
    setDraft(text);
    // Remembered rather than a "touched" flag: typing a character and taking
    // it back leaves the box holding the copy again, which is the same state
    // it started in and should read the same way.
    setPrefill(text);
    setTimeout(() => {
      const el = draftRef.current;
      if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
    }, 0);
  };
  // Block saving an edit that would duplicate another caption on this image.
  const trimmedEdit = editText.trim();
  const editIsDuplicate =
    editingId != null &&
    trimmedEdit.length > 0 &&
    rows.some((c) => c.id !== editingId && c.text.trim() === trimmedEdit);

  const saveEdit = async () => {
    if (editingId == null || itemId == null || editIsDuplicate) return;
    const t = editText.trim();
    if (t) await api.editCaption(itemId, editingId, t);
    setEditingId(null);
    onChange();
  };
  // ⌘/Ctrl+Enter saves, Escape leaves the caption as it was; a plain Enter
  // is a newline, and a blur is not a save.
  const editKeys = useInlineEdit<HTMLTextAreaElement>({
    commit: () => void saveEdit(), cancel: () => setEditingId(null),
    metaEnter: true, commitOnBlur: false, stop: true,
  });
  const removeCaptions = (ids: number[]) => undoRun(
    `${tr("Deleted")} ${ids.length}`, () => doRemoveCaptions(ids));
  const doRemoveCaptions = async (ids: number[]) => {
    if (itemId == null || ids.length === 0) return;
    if (ids.length > BIG_EDIT && !(await confirm({
      title: tr("Delete {n} captions?", { n: String(ids.length) }),
      answer: { label: tr("Delete"), danger: true } }))) return;
    await runBulk(ids, (id) => api.deleteCaption(itemId, id), { chunk: 25 });
    sel.clear();
    onChange();
  };


  return (
    <CollapsibleSection
      title={tr(w.title)}
      sk={kind === "instruction" ? "instructions" : "captions"}
      hideHeader={hideHeader}
    >
      {topAction && <div style={{ marginBottom: 10 }}>{topAction}</div>}
      {itemId == null ? (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          {tr(multi ? w.pickOne : w.pickAny)}
        </div>
      ) : (
        <>
          {/* Adder (hidden in the read-only Trash view) */}
          {!readOnly && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
            {/* ⌘F over the ADD box as well as over an edit: writing a
                caption and correcting one are the same job, and the box that
                is hardest to search by eye is the long one being written. */}
            <FindableCaption
              ref={draftRef}
              value={draft}
              onValue={setDraft}
              t={tr}
              borderColor={warnDuplicate ? "var(--yellow)" : "var(--border-strong)"}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); addCaption(); }
              }}
              placeholder={tr(w.placeholder)}
            />
            {warnDuplicate && (
              <span style={{ fontSize: "var(--fs-2)", color: "var(--yellow-text)" }}>{tr(w.duplicate)}</span>
            )}
            {trimmedDraft.length > 0 && (
              <button
                onClick={addCaption}
                disabled={isDuplicate}
                title={isDuplicate ? "This caption already exists on this image" : undefined}
                style={{
                  alignSelf: "flex-start", height: 26, padding: "0 12px", borderRadius: "var(--r-3)",
                  border: "none",
                  background: isDuplicate ? "var(--border)" : "var(--accent)",
                  color: isDuplicate ? "var(--muted)" : "var(--on-accent)",
                  fontSize: "var(--fs-2)", fontWeight: 600,
                  cursor: isDuplicate ? "default" : "pointer",
                  display: "flex", alignItems: "center", gap: 5,
                }}
              >
                <Icon name="add" size={15} />{tr(w.add)}</button>
            )}
          </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 6, userSelect: "none" }}>
            {rows.map((c) =>
              editingId === c.id && !readOnly ? (
                <div key={c.id} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {/* ⌘F searches THIS caption — the browser's own cannot,
                      because a textarea's value is not page text. */}
                  <FindableCaption
                    value={editText}
                    onValue={setEditText}
                    t={tr}
                    borderColor={editIsDuplicate ? "var(--yellow)" : "var(--accent)"}
                    autoFocus
                    onChange={(e) => setEditText(e.target.value)}
                    onKeyDown={editKeys.onKeyDown}
                  />
                  {editIsDuplicate && (
                    <span style={{ fontSize: "var(--fs-2)", color: "var(--yellow-text)" }}>
                      Another caption on this image already has this text.
                    </span>
                  )}
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      onClick={saveEdit}
                      disabled={editIsDuplicate}
                      title={editIsDuplicate ? "Another caption on this image already has this text" : undefined}
                      style={{
                        height: 24, padding: "0 10px", borderRadius: "var(--r-2)", border: "none",
                        background: editIsDuplicate ? "var(--border)" : "var(--accent)",
                        color: editIsDuplicate ? "var(--muted)" : "var(--on-accent)",
                        fontSize: "var(--fs-2)", fontWeight: 600,
                        cursor: editIsDuplicate ? "default" : "pointer",
                      }}
                    >{tr("Save")}</button>
                    <button
                      onClick={() => setEditingId(null)}
                      style={{ height: 24, padding: "0 10px", borderRadius: "var(--r-2)", border: "1px solid var(--border-strong)", background: "transparent", color: "var(--text-2)", fontSize: "var(--fs-2)", cursor: "pointer" }}
                    >{tr("Cancel")}</button>
                  </div>
                </div>
              ) : (
                <div
                  key={c.id}
                  className={readOnly ? undefined : "hoverable"}
                  {...(readOnly ? {} : sel.props(String(c.id)))}
                  style={{
                    // The caption text uses the full width; the hover actions are
                    // absolutely positioned and overlay the top-right corner (on
                    // a matching background so they stay legible) rather than
                    // reserving a permanent gutter that narrows the text.
                    position: "relative",
                    minHeight: 34,
                    padding: "9px 10px", borderRadius: "var(--r-4)",
                    background: rowBackground(selected.includes(c.id), "var(--panel-3)"),
                    // Amber for a caption nobody has agreed with yet — the same
                    // colour a guessed face and a pending tag wear. Picked wins
                    // over it: what the next action applies to matters more in
                    // that moment than why the card is here.
                    border: `1px solid ${selected.includes(c.id) ? "var(--accent)"
                      : c.pending ? "var(--yellow)" : "var(--border)"}`,
                    cursor: readOnly ? "default" : "pointer",
                  }}
                >
                  {c.pending && (
                    <Chip tone="warn" size="sm" upper icon="auto_awesome" style={{ marginBottom: 4 }}
                          title={tr("AI-generated caption awaiting your approval")}>
                      {tr("Pending")}
                    </Chip>
                  )}
                  {c.model && (
                    <span
                      title={c.edited ? `Generated by ${c.model}, then edited` : `Generated by ${c.model}`}
                      style={{
                        display: "flex", alignItems: "center", gap: 4, marginBottom: 4,
                        fontSize: "var(--fs-1)", color: "var(--muted-2)", fontFamily: "var(--mono)",
                      }}
                    >
                      <Icon name="smart_toy" size={11} /> {c.model}{c.edited ? " · edited" : ""}
                    </span>
                  )}
                  <span style={{ display: "block", fontSize: "var(--fs-4)", lineHeight: 1.5, color: "var(--text-2)", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                    {c.text}
                  </span>
                  {/* The pictures this one was made FROM, in the order the
                      model is shown them. Only an instruction has any. */}
                  {kind === "instruction" && itemId != null && (
                    <InstructionRefs
                      itemId={itemId} caption={c} readOnly={readOnly}
                      noGrid={noGrid} onChange={onChange}
                    />
                  )}
                  {/* Meta tags: the same namespace a link's tags use — notes
                      ABOUT the caption (its language, source, purpose). */}
                  {itemId != null && (
                    <CaptionTagRow
                      itemId={itemId} caption={c} readOnly={readOnly}
                      onChange={onChange}
                    />
                  )}
                  {!readOnly && (
                  <span className="row-actions" style={{ position: "absolute", top: 6, right: 6, display: "flex", alignItems: "center", paddingLeft: 2, borderRadius: "var(--r-2)", background: selected.includes(c.id) ? "var(--accent-dim)" : "var(--panel-3)", boxShadow: `-4px 0 6px 0 ${selected.includes(c.id) ? "var(--accent-dim)" : "var(--panel-3)"}` }}>
                    {c.pending && (
                      <IconButton icon="check_circle" size={20} reveal="hover" color="var(--green)"
                        title={tr("Approve this caption")}
                        onClick={(e) => { e.stopPropagation(); api.approveCaption(c.id).then(onChange); }} />
                    )}
                    <IconButton icon="content_copy" size={20} glyph={14} reveal="hover"
                      title={tr("Duplicate into the add box to edit")}
                      onClick={(e) => { e.stopPropagation(); duplicateToDraft(c.text); }} />
                    <IconButton icon="edit" size={20} glyph={14} reveal="hover"
                      title={tr(w.editTitle)}
                      onClick={(e) => { e.stopPropagation(); setEditingId(c.id); setEditText(c.text); }} />
                    <IconButton icon="close" size={20} reveal="hover" tone="danger"
                      title={tr(w.deleteTitle)}
                      onClick={(e) => { e.stopPropagation(); removeCaptions([c.id]); }} />
                  </span>
                  )}
                </div>
              )
            )}
            {captions && rows.length === 0 && (
              <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>{tr(w.empty)}</div>
            )}
          </div>
        </>
      )}
    </CollapsibleSection>
  );
}


/** One source card under a source file: an imported/added filename (file icon +
 *  name + relative path) or a web-URL source (link icon + URL + access date).
 *  On hover it offers rename/remove; the name/URL is editable inline. */
// Split a recorded source name into its folder path (during import) and the
// bare filename. Names without a slash have no relative path.
function splitSourceName(name: string): { path: string | null; file: string } {
  const i = name.lastIndexOf("/");
  return i === -1
    ? { path: null, file: name }
    : { path: name.slice(0, i + 1), file: name.slice(i + 1) };
}

function SourceNameCard({
  fileId, nameId, name, path, file, isUrl, accessedAt, readOnly, onChange,
  highlighted, hoverResetSignal,
}: {
  fileId: number;
  nameId: number;
  name: string;
  path: string | null;
  file: string;
  isUrl: boolean;
  accessedAt: string | null;
  readOnly?: boolean;
  onChange: () => void;
  // Briefly emphasized (just added, or the existing row a duplicate add hit);
  // the card also scrolls itself into view.
  highlighted?: boolean;
  // Bumped by the containing list on scroll: rows clear their hover state,
  // since Safari fires no mouseleave when a row scrolls out from under the
  // cursor — the action buttons would otherwise stay stuck visible.
  hoverResetSignal?: number;
}) {
  const { formatDateTime } = useDateFormatters();
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(name);
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (highlighted) cardRef.current?.scrollIntoView({ block: "nearest" });
  }, [highlighted]);
  const save = async () => {
    const v = val.trim();
    setEditing(false);
    if (v && v !== name) {
      try { await api.renameFileName(fileId, nameId, v); onChange(); }
      catch { /* e.g. duplicate — leave the original in place */ }
    }
  };
  // Enter saves, Escape puts the name back and closes; a blur saves too.
  const srcKeys = useInlineEdit({
    commit: () => void save(), cancel: () => { setVal(name); setEditing(false); },
  });
  const remove = async () => { await api.deleteFileName(fileId, nameId); onChange(); };
  // A single-line card (a filename with no path, or a URL with no access time)
  // centres its row against the action buttons; a two-line card top-aligns so the
  // icon and buttons sit level with the first line.
  const hasSubtitle = !editing && (isUrl ? !!accessedAt : !!path);
  // The reveal is driven by JS pointer state (not a CSS `:hover` rule) because
  // Safari fails to clear a pure-CSS hover — leaving these actions stuck visible
  // after the cursor leaves. Toggling inline opacity forces the repaint.
  const [hover, setHover] = useState(false);
  // Scrolling the list moves rows without any mouseleave (Safari) — clear the
  // hover state whenever the container reports a scroll.
  useEffect(() => { setHover(false); }, [hoverResetSignal]);
  return (
    <div
      ref={cardRef}
      onMouseEnter={readOnly ? undefined : () => setHover(true)}
      onMouseLeave={readOnly ? undefined : () => setHover(false)}
      style={{
        padding: "6px 8px", borderRadius: "var(--r-4)",
        background: highlighted ? "var(--accent-dim)" : "var(--panel-3)",
        border: `1px solid ${highlighted ? "var(--accent)" : "var(--border)"}`,
        // No transition — see the person row: a selection that fades in over
        // 400 ms reads as a click that has not registered.
        display: "flex", alignItems: hasSubtitle ? "flex-start" : "center", gap: 8,
      }}
    >
      <Icon name={isUrl ? "link" : "description"} size={14} color="var(--muted-2)" style={{ flex: "0 0 auto", marginTop: hasSubtitle ? 1 : 0 }} />
      {editing ? (
        <input
          autoFocus
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onBlur={srcKeys.onBlur}
          onKeyDown={srcKeys.onKeyDown}
          style={{ flex: 1, minWidth: 0, fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--text-bright)", background: "var(--panel-2)", border: "1px solid var(--border-strong)", borderRadius: "var(--r-1)", padding: "2px 6px", outline: "none" }}
        />
      ) : isUrl ? (
        <div style={{ flex: 1, minWidth: 0 }} title={name}>
          <a href={name} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
             style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--accent)", whiteSpace: "normal", overflowWrap: "anywhere", textDecoration: "none", display: "block" }}>{name}</a>
          {accessedAt && (
            <div style={{ marginTop: 2, fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>
              Accessed {formatDateTime(accessedAt)}
            </div>
          )}
        </div>
      ) : (
        <div style={{ flex: 1, minWidth: 0 }} title={name}>
          <div style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--text-bright)", whiteSpace: "normal", overflowWrap: "anywhere" }}>{file}</div>
          {path && (
            <div style={{ marginTop: 2, fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)", whiteSpace: "normal", overflowWrap: "anywhere" }}>{path}</div>
          )}
        </div>
      )}
      {/* The actions keep their layout space always (fading in via inline opacity
          on pointer state) so the text area's width — and thus the card height —
          never changes when they appear, even for a single-line card. */}
      {!readOnly && !editing && (
        <span style={{ flex: "0 0 auto", display: "flex", gap: 2, opacity: hover ? 1 : 0, transition: "opacity 0.1s", pointerEvents: hover ? "auto" : "none" }}>
          <IconButton icon="edit" size={20} glyph={13} reveal="hover"
            title="Edit this source name"
            onClick={() => { setVal(name); setEditing(true); }} />
          <IconButton icon="close" size={20} glyph={13} reveal="hover" tone="danger"
            title="Remove this source name"
            onClick={remove} />
        </span>
      )}
    </div>
  );
}

/** THE ROW'S SOURCES, WITH HOW MANY — beside Preview, where the count is the
 *  reason to press it. A file's recorded sources are the one thing on the row
 *  that has a NUMBER and is worth knowing at a glance (where a picture came
 *  from, and from how many places), and reading it meant opening a ⋯ menu to
 *  see a figure in a label.
 *
 *  ONE DOOR, chosen by whether there is anything behind it: a row with sources
 *  wears this button and the ⋯ menu drops the entry, a row with none keeps the
 *  entry (adding a first source has to be reachable) and wears no button.
 *  Both at once is the drift the shared chrome exists to prevent. */
function SourcesButton({ fileId, names, readOnly, onChange }: {
  fileId: number;
  names: FileNameEntry[];
  readOnly?: boolean;
  onChange: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const title = t("The filenames and URLs this file came from");
  return (
    <>
      <button
        type="button"
        className="icon-btn"
        title={title}
        aria-label={title}
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        style={{
          // The glyph box recipe, widened for the figure beside the glyph
          // (`width: "auto"`, the same note `RowMenu`'s trigger carries).
          ...iconButtonStyle({ size: 20 }),
          width: "auto", padding: "0 4px", gap: 3,
        }}
      >
        <Icon name="explore" size={14} />
        <Count n={names.length} tone="muted-2" />
      </button>
      {open && (
        <SourcesOverlay fileId={fileId} names={names} readOnly={readOnly}
          onClose={() => setOpen(false)} onChange={onChange} />
      )}
    </>
  );
}

/** The ⋯ actions menu for a source file row: Split / Delete when the item has
 *  more than one file, plus **Sources** for a file that has none recorded —
 *  the one that has some carries `SourcesButton` on the row instead. */
function SourceFileMenu({ fileId, names, canModify, readOnly, onSplit, onDelete, onChange }: {
  fileId: number;
  names: FileNameEntry[];
  canModify: boolean;
  readOnly?: boolean;
  onSplit: () => void;
  onDelete: () => void;
  onChange: () => void;
}) {
  const t = useT();
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const actions: RowAction[] = [
    ...(names.length === 0 && !readOnly ? [{
      icon: "explore", label: t("Sources"),
      hint: t("The filenames and URLs this file came from"),
      onClick: () => setSourcesOpen(true),
    }] : []),
    ...(!readOnly && canModify ? [
      { icon: "call_split", label: t("Split into its own item"), onClick: onSplit },
      { icon: "delete", label: t("Delete file"), danger: true, onClick: onDelete },
    ] : []),
  ];
  if (actions.length === 0) return null;
  return (
    <div style={{ display: "flex", flex: "0 0 auto" }}>
      <RowMenu always title={t("More actions")} actions={actions} />
      {sourcesOpen && (
        <SourcesOverlay fileId={fileId} names={names} readOnly={readOnly}
          onClose={() => setSourcesOpen(false)} onChange={onChange} />
      )}
    </div>
  );
}

/** ADDING A SOURCE — a filename+path, or a web URL with an access date/time —
 *  in a dialog of its OWN, over the list. It was a form inside the list, and
 *  a form there needs a Cancel, which in a list where every other edit lands
 *  the moment it is made reads as "put the sources back". A dialog's Cancel
 *  is about the dialog. Enter is the Overlay's `onSubmit`, which is why the
 *  fields carry no key handler of their own: two would submit twice. */
// Identifies one source row for the post-add highlight: its name plus, for a
// URL source, the access time in epoch ms (null = no recorded time).
type SourceKey = { name: string; accMs: number | null };

function AddSourceOverlay({ fileId, onClose, onAdded, onDuplicate }: {
  fileId: number;
  onClose: () => void;
  // Called with the added source's key so the list can highlight its row.
  onAdded: (key: SourceKey) => void;
  // The source already exists — the list highlights the existing row.
  onDuplicate: (key: SourceKey) => void;
}) {
  const t = useT();
  const [mode, setMode] = useState<"file" | "url">("file");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  // The access date/time is optional for a URL source.
  const [withTime, setWithTime] = useState(true);
  const [when, setWhen] = useState(() => {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  });
  const [busy, setBusy] = useState(false);
  const inputStyle: React.CSSProperties = {
    width: "100%", boxSizing: "border-box", fontFamily: "var(--mono)", fontSize: "var(--fs-3)",
    padding: "8px 10px", borderRadius: "var(--r-4)", border: "1px solid var(--border-strong)",
    background: "var(--panel-2)", color: "var(--text-bright)", outline: "none",
  };
  const submit = async () => {
    const useTime = mode === "url" && withTime && !!when;
    const body = mode === "url"
      ? (url.trim()
          ? { url: url.trim(), ...(useTime ? { accessed_at: new Date(when).toISOString() } : {}) }
          : null)
      : (name.trim() ? { name: name.trim() } : null);
    if (!body) return;
    const key: SourceKey = {
      name: (mode === "url" ? url : name).trim(),
      accMs: useTime ? new Date(when).getTime() : null,
    };
    setBusy(true);
    try {
      await api.addFileNameSource(fileId, body);
      onAdded(key);
    } catch (e) {
      // A 400 means the identical source is already recorded — hand the key
      // back so the existing row gets highlighted instead.
      if (String(e).includes("400")) onDuplicate(key);
    } finally { setBusy(false); }
  };
  const ready = (mode === "url" ? url : name).trim().length > 0;
  return (
    <Overlay icon="add_link" title={t("Add source")} width={420} onClose={onClose}
             onSubmit={() => void submit()}
             footer={<>
               <GhostButton onClick={onClose}>{t("Cancel")}</GhostButton>
               <PrimaryButton icon="add_link" disabled={busy || !ready}
                              onClick={() => void submit()}>
                 {t("Add")}
               </PrimaryButton>
             </>}>
    <div style={{ padding: "16px 20px" }}>
      <div style={{ display: "flex", gap: 4, background: "var(--bg-deep)", border: "1px solid var(--border)", borderRadius: "var(--r-4)", padding: 3, marginBottom: 10 }}>
        {(["file", "url"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)} style={{ flex: 1, height: 28, borderRadius: "var(--r-2)", border: "none", background: mode === m ? "var(--accent)" : "transparent", color: mode === m ? "var(--on-accent)" : "var(--muted)", fontSize: "var(--fs-3)", fontWeight: 600, cursor: "pointer" }}>
            {m === "file" ? t("File Path") : t("Web URL")}
          </button>
        ))}
      </div>
      {mode === "file" ? (
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
          placeholder="folder/name.jpg" style={inputStyle} />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/image.jpg" style={inputStyle} />
          <label style={{ fontSize: "var(--fs-2)", color: "var(--muted)", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={withTime} onChange={(e) => setWithTime(e.target.checked)} style={{ accentColor: "var(--accent)", cursor: "pointer" }} />
            {t("Record access date/time")}
          </label>
          {withTime && (
            <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} style={inputStyle} />
          )}
        </div>
      )}
    </div>
    </Overlay>
  );
}

/** Modal listing a source file's recorded sources — the filenames it was
 *  imported under and any web URLs — with add / edit / remove. Opened from the
 *  file row's Sources button (or its ⋯ menu, for a file with none).
 *
 *  Every edit here lands as it is made; the footer's **Add source** opens a
 *  dialog of its own.
 *  File-path sources sort by (directory, filename) — root-level names first —
 *  and URL sources follow, alphabetically, then newest access time first. A
 *  just-added row (or, on a duplicate, the already-existing row) is briefly
 *  highlighted and scrolled into view. */
function SourcesOverlay({ fileId, names, readOnly, onClose, onChange }: {
  fileId: number;
  names: FileNameEntry[];
  readOnly?: boolean;
  onClose: () => void;
  onChange: () => void;
}) {
  const t = useT();
  const tn = useTn();
  // ADDING IS ITS OWN DIALOG, over this one. Inline, its fields were a form
  // sitting above the list with a Cancel of its own — and in a list whose
  // every other edit is applied the moment it is made, a Cancel down there
  // read as "undo what I did to these sources". A dialog is allowed one,
  // because a dialog is the thing it cancels.
  const [adding, setAdding] = useState(false);
  // The row to flash (a just-added source, or the existing duplicate).
  const [highlight, setHighlight] = useState<SourceKey | null>(null);
  const highlightTimer = useRef<number | null>(null);
  // Bumped when the list scrolls, so rows can clear a stuck hover state
  // (Safari fires no mouseleave when a row scrolls out from under the cursor).
  const [scrollTick, setScrollTick] = useState(0);
  useEffect(() => () => {
    if (highlightTimer.current != null) window.clearTimeout(highlightTimer.current);
  }, []);
  const flash = (key: SourceKey) => {
    setHighlight(key);
    if (highlightTimer.current != null) window.clearTimeout(highlightTimer.current);
    highlightTimer.current = window.setTimeout(() => setHighlight(null), 1800);
  };
  const matches = (n: FileNameEntry) =>
    highlight != null && n.name === highlight.name && (
      highlight.accMs == null
        ? n.accessed_at == null
        : n.accessed_at != null && Date.parse(n.accessed_at) === highlight.accMs
    );

  // Display order: file paths first — by (directory, filename), so root-level
  // names lead (a.jpg, b.jpg, x/b.jpg, y/a.jpg, y/b.jpg) — then URLs,
  // alphabetically, with the newest access time first among equals.
  const sorted = useMemo(() => {
    const files = names.filter((n) => !n.is_url);
    const urls = names.filter((n) => n.is_url);
    const fileKey = (n: FileNameEntry) => {
      const { path, file } = splitSourceName(n.name);
      return [(path ?? "").toLowerCase(), file.toLowerCase()] as const;
    };
    files.sort((a, b) => {
      const ka = fileKey(a), kb = fileKey(b);
      if (ka[0] !== kb[0]) return ka[0] < kb[0] ? -1 : 1;
      if (ka[1] !== kb[1]) return ka[1] < kb[1] ? -1 : 1;
      return a.id - b.id;
    });
    urls.sort((a, b) => {
      const na = a.name.toLowerCase(), nb = b.name.toLowerCase();
      if (na !== nb) return na < nb ? -1 : 1;
      const ta = a.accessed_at ? Date.parse(a.accessed_at) : -Infinity;
      const tb = b.accessed_at ? Date.parse(b.accessed_at) : -Infinity;
      return tb - ta || a.id - b.id;
    });
    return [...files, ...urls];
  }, [names]);

  return (
    <Overlay icon="link" title={t("Sources")} width={460}
             // The figure is about the list, not part of its name: the header's
             // own secondary line, where every other dialog puts one.
             subtitle={tn({ one: "1 source", other: "{n} sources" }, names.length)}
             height="80%" onClose={onClose}
             footer={readOnly ? undefined : (
               <PrimaryButton icon="add_link" onClick={() => setAdding(true)}>
                 {t("Add source")}
               </PrimaryButton>
             )}>
      {/* The body carries the dialog's own padding — it had none, so the cards
          sat against all four edges. */}
      <div style={{ height: "100%", boxSizing: "border-box", padding: "16px 20px",
                    display: "flex", flexDirection: "column", gap: 8 }}>
        {adding && (
          <AddSourceOverlay
            fileId={fileId}
            onClose={() => setAdding(false)}
            onAdded={(key) => { setAdding(false); flash(key); onChange(); }}
            onDuplicate={(key) => { setAdding(false); flash(key); }}
          />
        )}
        {/* Scrollable source list. */}
        <div
          onScroll={() => setScrollTick((v) => v + 1)}
          style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto", overscrollBehavior: "contain", display: "flex", flexDirection: "column", gap: 6 }}
        >
          {names.length === 0 && (
            <EmptyState dense style={{ fontSize: "var(--fs-3)", padding: "6px 2px" }}
                        line={t("No sources recorded for this file.")} />
          )}
          {sorted.map((n) => {
            const { path, file } = splitSourceName(n.name);
            return (
              <SourceNameCard
                key={n.id}
                fileId={fileId}
                nameId={n.id}
                name={n.name}
                path={path}
                file={file}
                isUrl={n.is_url}
                accessedAt={n.accessed_at}
                readOnly={readOnly}
                onChange={onChange}
                highlighted={matches(n)}
                hoverResetSignal={scrollTick}
              />
            );
          })}
        </div>
      </div>
    </Overlay>
  );
}

/**
 * The imported files behind one image. Near-identical imports become alternative
 * "versions" (a radio picks which one is the library's source data); a truly
 * identical file imported under another name shows as an extra entry sharing the
 * same stored bytes. Each file can be previewed or deleted (never the last one).
 */
function FilesSection({
  itemId,
  files,
  readOnly,
  hideHeader,
  onChange,
}: {
  itemId: number;
  files: FileVersion[];
  readOnly?: boolean;
  // Hide the section header when Files is the only open tab (the tab label
  // already names it), like the other single-section tabs.
  hideHeader?: boolean;
  onChange: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const lang = useLang();
  const { formatDateTime } = useDateFormatters();
  // WHICH FILES ARE PICKED FOR A BULK VERB — the app's ONE row selection
  // (`useRowSelect`: a plain click picks that row alone, ⌘ toggles, ⇧ takes
  // the run), which this list was the single exception to. It had a tick per
  // row instead, on the grounds that the row's own click already meant
  // something else — it made that file the item's source data — but the
  // control that SAYS which file that is was sitting right there unpressed:
  // the RADIO takes that click now, and the row is a row like every other one
  // in the sidebar.
  //
  // Nothing to pick BETWEEN with one file, and nothing a pick could do in a
  // read-only view, so there is no selection at all rather than a dimmed one.
  const pickable = !readOnly && files.length > 1;
  // Files that have gone (a delete, a split, another tab) drop out of the pick:
  // `useRowSelect` prunes on the key array's IDENTITY, so it is memoized on the
  // joined ids rather than rebuilt every render.
  const idsKey = files.map((f) => f.id).join(",");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const keys = useMemo(() => files.map((f) => String(f.id)), [idsKey]);
  const sel = useRowSelect(keys);
  const picked = useMemo(() => sel.selected.map(Number), [sel.selected]);
  // One radio entry per file (unique stored data). A file may have been imported
  // under several names; each is listed (with its relative import path, if any)
  // in its own indented box directly below the radio entry, collapsible via the
  // chevron on the radio row.
  const setActive = async (fileId: number) => {
    if (readOnly) return;
    await api.updateItem(itemId, { active_file_id: fileId });
    onChange();
  };
  const del = async (fileId: number) => {
    if (files.length <= 1) return;
    // Deleting a source file removes the stored data for good — there's no
    // History revert for it — so confirm first, naming the file.
    const f = files.find((x) => x.id === fileId);
    const label = f?.names?.[0]?.name
      || (f ? `${f.format.toUpperCase()} ${f.width}×${f.height}` : "this file");
    // IS ANYTHING HERE DESCENDED FROM IT? An edited file records the number of
    // the file it came from, and `edit_chain` keeps the whole lineage even
    // where an intermediate was deleted — so this stays true after the middle
    // of a chain has already gone.
    const n = f?.number ?? null;
    const descendants = n == null ? 0 : files.filter((x) =>
      x.id !== fileId
      && (x.based_on === n || (x.edit_chain ?? []).some((step) => step.from === n))
    ).length;
    // Which is worth saying, because the loss is not only the bytes. This
    // file is what an IMPORT of the same picture would have matched against —
    // that is how a re-import lands back on this item instead of making a new
    // one. Delete it and the match has nothing to find: the picture comes
    // back as an item of its own, with none of the tagging that was done
    // here, and nothing at that moment says why.
    const extra = descendants > 0
      ? "\n\n" + tn({
          one: "1 other file here was edited from this one. It is also what a re-import of the same picture matches against, so if you import the original again later it may arrive as a NEW item rather than joining this one.",
          other: "{n} other files here were edited from this one. It is also what a re-import of the same picture matches against, so if you import the original again later it may arrive as a NEW item rather than joining this one.",
        }, descendants)
      : "";
    if (!(await confirm({
      title: t("Delete the source file “{name}”?", { name: label }),
      body: t("This permanently removes the stored file and cannot be undone.") + extra,
      answer: { label: t("Delete"), danger: true },
    }))) return;
    await api.deleteFile(fileId);
    onChange();
  };
  const split = async (fileId: number) => {
    if (files.length <= 1) return;
    await api.splitFile(fileId);
    onChange();
  };

  // WHAT A BULK VERB ACTS ON. An item keeps at least one file — both the
  // delete and the split refuse to take the last one — and the list used to
  // enforce that by OFFERING NOTHING the moment every row was picked, which on
  // a two-file item is the ordinary gesture: pick both, and the bar went
  // blank. So the rule is applied to the SELECTION instead of to the buttons:
  // a pick that is every file leaves the active one (the item's source data)
  // behind, and both buttons carry that real number, which is what their
  // "an item keeps at least one" has been promising all along.
  const actOn = useMemo(() => {
    if (picked.length < files.length) return picked;
    const keep = files.find((f) => f.active) ?? files[files.length - 1];
    return picked.filter((id) => id !== keep?.id);
  }, [picked, files]);

  // SEVERAL FILES LEAVE AS ONE ITEM. The row's own Split is one file into one
  // item, which repeated is one item each — the opposite of what somebody who
  // picked three of them meant. So the picks go out in a single call, and the
  // pictures that belonged together arrive together.
  const splitPicked = async () => {
    if (actOn.length === 0) return;
    await api.splitFiles(actOn);
    sel.clear();
    onChange();
  };
  const delPicked = async () => {
    if (actOn.length === 0) return;
    // What the single delete says by default, in the plural. (Its extra
    // paragraph is about ONE file's descendants and does not generalize.)
    if (!(await confirm({
      title: tn({ one: "Delete 1 source file?", other: "Delete {n} source files?" },
                actOn.length),
      body: tn({
        one: "This permanently removes the stored file and cannot be undone.",
        other: "This permanently removes the stored files and cannot be undone.",
      }, actOn.length),
      answer: { label: t("Delete"), danger: true },
    }))) return;
    for (const id of actOn) await api.deleteFile(id);
    sel.clear();
    onChange();
  };

  const delArtifact = async (artifactId: number, label: string) => {
    if (!(await confirm({ title: t("Remove the generated {label}?", { label }),
                          answer: { label: t("Remove"), danger: true } }))) return;
    await api.deleteArtifact(artifactId);
    onChange();
  };

  // THE SAME BAR every other tab reports to. Both verbs act on `actOn` — the
  // picks less the file the item has to keep — so they are offered whenever
  // anything is picked and each says how many it will really take.
  useReportSelection("files", pickable ? {
    count: picked.length,
    total: files.length,
    onSelectAll: () => sel.selectAll(),
    onClear: sel.clear,
    onRemove: delPicked,
    removeLabel: t("Delete"),
    removeTitle: t("Delete the selected files (an item keeps at least one)"),
    removeIcon: "delete",
    removeCount: actOn.length,
    ...(actOn.length > 0 ? {
      extra: {
        icon: "call_split",
        title: t("Split the selected files out into one new item"),
        onClick: splitPicked,
      },
    } : null),
  } : null);

  return (
    <CollapsibleSection title="Files" sk="source" hideHeader={hideHeader}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {files.map((f) => {
          // The file's recorded sources (imported filenames + URLs) live behind
          // the Sources count button on the row (opening an overlay); only its
          // generated artifacts are shown nested below the radio box.
          const hasNested = (f.artifacts?.length ?? 0) > 0;
          return (
            <div key={f.id} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {/* The file's row: PICKED like any other row in the sidebar,
                  with the radio — not the row — saying which file is the
                  item's source data. The accent TINT is the selection (the
                  one meaning it has everywhere else); the accent BORDER and
                  the filled radio are the active file. */}
              <div
                {...(pickable ? sel.props(String(f.id)) : {})}
                className={pickable ? "hoverable" : undefined}
                style={{
                  padding: "8px 6px 8px 8px", borderRadius: "var(--r-4)",
                  cursor: pickable ? "pointer" : "default",
                  background: rowBackground(pickable && sel.has(String(f.id)),
                                            "var(--panel-3)"),
                  border: `1px solid ${
                    f.active || (pickable && sel.has(String(f.id)))
                      ? "var(--accent)" : "var(--border)"}`,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  {/* Radio — the one control that makes this file the source
                      data. It stops the press as well as the click: the row's
                      selection paints on a press-and-drag, and a press that
                      landed here would start one. */}
                  <span
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => { e.stopPropagation(); if (!f.active) void setActive(f.id); }}
                    title={
                      f.active ? t("Source data for this image")
                      : readOnly ? undefined
                      : t("Use this file as the source data")
                    }
                    style={{
                      flex: "0 0 auto", width: 15, height: 15, borderRadius: "50%",
                      border: `2px solid ${f.active ? "var(--accent)" : "var(--muted-2)"}`,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      cursor: f.active || readOnly ? "default" : "pointer",
                    }}
                  >
                    {f.active && <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--accent)" }} />}
                  </span>
                  <div style={{ flex: 1, minWidth: 0, fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
                    {/* Stable per-item source-file number. */}
                    {f.number != null && (
                      <span style={{ fontWeight: 700, color: "var(--text-2)" }}>#{f.number} · </span>
                    )}
                    {f.source_kind === "video_frame"
                      ? `Video frame @ ${(f.source_start ?? 0).toFixed(2)}s`
                      : f.source_kind === "video_clip"
                      ? `Clip ${(f.source_start ?? 0).toFixed(2)}–${(f.source_end ?? 0).toFixed(2)}s`
                      : `${f.format.toUpperCase()} · ${f.width}×${f.height} · ${formatBytes(f.bytes, lang)}`}
                    {f.source_kind === "stored" && f.edited && (
                      <span style={{ marginLeft: 5, fontSize: "var(--fs-0)", color: "var(--yellow-text)" }}>edited</span>
                    )}
                    {/* Orientation of this source relative to the item's first
                        file: rotation angle and/or a horizontal flip. */}
                    {((f.rotation % 360) !== 0 || f.mirrored) && (
                      <span
                        title="Orientation relative to the first source file"
                        style={{ marginLeft: 5, display: "inline-flex", alignItems: "center", gap: 2, fontSize: "var(--fs-0)", color: "var(--accent)" }}
                      >
                        <Icon name={f.mirrored ? "flip" : "rotate_right"} size={11} />
                        {(f.rotation % 360) !== 0 ? `${f.rotation % 360}°` : ""}
                        {f.mirrored ? (((f.rotation % 360) !== 0 ? " · " : "") + "flipped") : ""}
                      </span>
                    )}
                    {/* Edit lineage: which file this one was derived from (the
                        originating source file's number). */}
                    {f.based_on != null && (
                      <div style={{ marginTop: 3, fontSize: "var(--fs-0)", lineHeight: 1.5, color: "var(--muted-2)", whiteSpace: "normal" }}>
                        based on <span style={{ fontWeight: 700, color: "var(--text-2)" }}>#{f.based_on}</span>
                      </div>
                    )}
                    {/* When the file's bytes were added (import) or last edited. */}
                    {f.created_at && (
                      <div style={{ marginTop: 3, fontSize: "var(--fs-0)", lineHeight: 1.5, color: "var(--muted-2)", whiteSpace: "normal" }}>
                        {f.edited ? t("Edited") : t("Added")} {formatDateTime(f.created_at)}
                      </div>
                    )}
                  </div>
                  {/* The row's own buttons. They stop the press and the click:
                      the row is a selection target now, and reaching for
                      Preview or ⋯ must not pick it on the way. */}
                  <span className="row-actions"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => e.stopPropagation()}
                    style={{ flex: "0 0 auto", display: "flex", alignItems: "center" }}>
                    <IconButton icon="visibility" size={20} glyph={14} reveal="hover"
                      title="Preview the file (Quick Look — the overlay links the raw file)"
                      onClick={(e) => {
                        e.stopPropagation();
                        // Clips/videos autoplay in the overlay; frames and
                        // stills preview as images.
                        const video = f.source_kind === "video_clip"
                          || f.duration != null;
                        useUI.getState().openQuickLookFile(itemId, f.id, video);
                      }} />
                    {/* The row's sources, with how many — only where there
                        are some; a file with none offers them in the ⋯ menu. */}
                    {f.names.length > 0 && (
                      <SourcesButton fileId={f.id} names={f.names}
                        readOnly={readOnly} onChange={onChange} />
                    )}
                    {/* ⋯ menu: Split / Delete (only with >1 file), plus Sources
                        for a file with none recorded. Renders nothing when it
                        would hold nothing — a read-only row, say. */}
                    <SourceFileMenu
                      fileId={f.id}
                      names={f.names}
                      canModify={files.length > 1}
                      readOnly={readOnly}
                      onSplit={() => split(f.id)}
                      onDelete={() => del(f.id)}
                      onChange={onChange}
                    />
                  </span>
                </div>
              </div>

              {/* Indented boxes nested under the source file: one per generated
                  artifact (depth map, pose overlay). No radio — auxiliary only.
                  (Recorded sources live behind the row's Sources button.) */}
              {hasNested && (
                <div style={{ marginLeft: 16, display: "flex", flexDirection: "column", gap: 6 }}>
                  {(f.artifacts ?? []).map(function artRow(a): React.ReactNode {
                    // One table for both views of these names (`artifactKinds.ts`); this
                    // one shows a single artifact, so it reads the singular.
                    const kindMeta = artifactKind(a.kind);
                    const meta = { icon: kindMeta.icon, label: kindMeta.name.one };
                    const kids = a.children ?? [];
                    return (
                      <div key={`art-${a.id}`}>
                      <div
                        style={{
                          padding: "6px 6px 6px 8px", borderRadius: "var(--r-4)",
                          background: "var(--panel-3)", border: "1px solid var(--border)",
                          display: "flex", alignItems: "center", gap: 8,
                        }}
                      >
                        <Icon name={meta.icon} size={15} color={a.stale ? "var(--yellow-text)" : "var(--accent)"} style={{ flex: "0 0 auto", opacity: a.stale ? 0.85 : 1 }} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 5, minWidth: 0 }}>
                            <span style={{ fontSize: "var(--fs-2)", color: "var(--text-bright)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {t(meta.label)}
                            </span>
                            {a.stale && (
                              <Chip tone="warn" size="sm" upper icon="warning"
                                    title="The source image was edited after this was generated, so it no longer matches — regenerate it.">
                                Stale
                              </Chip>
                            )}
                          </div>
                          {(() => {
                            // A file has one latent per bucket, plus mirrored
                            // and masked copies, so the row needs the size and
                            // variant to mean anything. Other artifacts just
                            // name their model.
                            const parts = a.kind === "latent"
                              ? [a.model, `${a.width}×${a.height}`, a.variant]
                              : [a.model];
                            const sub = parts.filter(Boolean).join(" · ");
                            return sub ? (
                              <div style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={sub}>
                                {sub}
                              </div>
                            ) : null;
                          })()}
                        </div>
                        <span className="row-actions" style={{ flex: "0 0 auto", display: "flex" }}>
                          <a
                            className="row-action"
                            href={api.artifactUrl(a.id)}
                            target="_blank"
                            rel="noreferrer"
                            title={`Open the ${meta.label.toLowerCase()}`}
                            style={{ width: 20, height: 20, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted-2)", cursor: "pointer", borderRadius: "var(--r-1)", textDecoration: "none" }}
                          >
                            <Icon name="open_in_new" size={14} />
                          </a>
                          {!readOnly && (
                            <IconButton icon="delete" size={20} glyph={14} reveal="hover" tone="danger"
                              title={`Remove the ${meta.label.toLowerCase()}`}
                              onClick={() => delArtifact(a.id, meta.label.toLowerCase())} />
                          )}
                        </span>
                      </div>
                      {/* Artifacts generated from THIS one rather than from the
                          source file — a degraded copy's own cached latents.
                          One level deeper, so the two-step provenance reads:
                          this file → this spoiled copy of it → what a run
                          encoded from that. */}
                      {kids.length > 0 && (
                        <div style={{
                          marginLeft: 16, marginTop: 6, display: "flex",
                          flexDirection: "column", gap: 6,
                        }}>
                          {kids.map(artRow)}
                        </div>
                      )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </CollapsibleSection>
  );
}

/** Video/audio/subtitle/attachment streams inside the active file (videos only),
 *  rendered with the shared expandable per-track view. */
function TracksSection({ itemId }: { itemId: number }) {
  const { data } = useQuery({
    queryKey: ["item-tracks", itemId],
    queryFn: () => api.itemTracks(itemId),
  });
  const tracks = data?.tracks ?? [];
  if (tracks.length === 0) return null;
  return (
    <CollapsibleSection title="Tracks" sk="tracks">
      <MediaTracksView tracks={tracks} />
    </CollapsibleSection>
  );
}

/** Image file metadata (EXIF etc.) for the active file, when present. Dimensions
 *  and resolution are passed in as ``leading`` rows (they live here rather than
 *  in Properties) and render without a grid-filter button. */
// A metadata value longer than this many characters is shown on its own line
// below the label (wrapping in full) instead of truncated to the right.
const META_LONG_VALUE = 22;

/** One Info-section row: a muted label, an optional hover action button (filter
 *  / copy), and the value. A short value sits right-aligned on the same line; a
 *  long one wraps in full on the line below the label. */
function MetaRow({ label, value, title, action, hoverable, sub, struck }: {
  label: string;
  value: string;
  title?: string;
  // A right-aligned action element (already styled as a `row-action`), or none.
  action?: React.ReactNode;
  // Adds the `.hoverable` class so a hover-revealed `action` shows on hover.
  hoverable?: boolean;
  // A second line under the row, for the one thing the value cannot say by
  // itself: WHICH file it came from, when the item's files disagree. A row
  // without one keeps its exact 22px — only rows with something to say grow.
  sub?: string;
  // The item ignores this value: shown, not used. A strike is right here — it
  // is the same claim a negative tag makes ("this does not apply") — where an
  // overridden implication is merely greyed.
  struck?: boolean;
}) {
  const long = value.length > META_LONG_VALUE;
  const base: React.CSSProperties = {
    boxSizing: "border-box", padding: "1px 2px", borderRadius: "var(--r-1)",
    fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
  };
  const valueStyle: React.CSSProperties = struck
    ? { textDecoration: "line-through", opacity: 0.55 }
    : {};
  const subLine = sub ? (
    <span style={{ color: "var(--muted-3)", fontSize: "var(--fs-1)", whiteSpace: "nowrap",
                   overflow: "hidden", textOverflow: "ellipsis" }}>
      {sub}
    </span>
  ) : null;
  if (long || sub) {
    return (
      <div className={hoverable ? "hoverable" : undefined}
           style={{ ...base, display: "flex", flexDirection: "column", gap: 2, padding: "3px 2px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, minHeight: 18 }}>
          <span style={{ color: "var(--muted-2)", whiteSpace: "nowrap" }}>{label}</span>
          {action && <span style={{ flex: "0 0 auto", marginLeft: "auto", display: "flex" }}>{action}</span>}
          {!long && (
            <span title={title ?? value}
                  style={{ flex: "0 1 auto", marginLeft: action ? undefined : "auto", minWidth: 0, color: "var(--text-3)", textAlign: "right", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", ...valueStyle }}>
              {value}
            </span>
          )}
        </div>
        {long && (
          <span title={title ?? value}
                style={{ color: "var(--text-3)", whiteSpace: "normal", overflowWrap: "anywhere", lineHeight: 1.45, ...valueStyle }}>
            {value}
          </span>
        )}
        {subLine}
      </div>
    );
  }
  return (
    <div className={hoverable ? "hoverable" : undefined}
         style={{ ...base, display: "flex", alignItems: "center", gap: 10, height: 22 }}>
      <span style={{ color: "var(--muted-2)", whiteSpace: "nowrap" }}>{label}</span>
      {/* The action button (when present) is pushed right, dragging the value to
          the right edge with it — the button sits immediately left of the value
          and keeps its slot so the value doesn't shift when it fades in. */}
      {action && <span style={{ flex: "0 0 auto", marginLeft: "auto", display: "flex" }}>{action}</span>}
      <span title={title ?? value}
            style={{ flex: "0 1 auto", marginLeft: action ? undefined : "auto", minWidth: 0, color: "var(--text-3)", textAlign: "right", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", ...valueStyle }}>
        {value}
      </span>
    </div>
  );
}

/** The item-uid row for the Info section: like a metadata field, but its hover
 *  button copies the uid (there's nothing to filter by) instead of the
 *  grid-filter button the other rows show. */
function UidMetaRow({ uid, onFilter }: { uid: string; onFilter: () => void }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const copy = () => {
    try {
      navigator.clipboard?.writeText(uid);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch { /* ignore */ }
  };
  return (
    <MetaRow
      label={t("ID")}
      value={uid}
      hoverable
      action={
        // Two buttons: copy the uid, and filter the grid down to this one item
        // (`INFO:id=<uid>` — useful for pasting an id from an export back in).
        <span style={{ display: "flex", flex: "0 0 auto" }}>
          <IconButton icon="filter_alt" size={20} glyph={14} reveal="fixed"
            title="Filter the grid by this item id"
            onClick={onFilter} />
          <IconButton icon={copied ? "check" : "content_copy"} size={20} glyph={13} reveal="fixed" color={copied ? "var(--green)" : "var(--muted-2)"}
            title="Copy item id"
            onClick={copy} />
        </span>
      }
    />
  );
}

/** One metadata row's hover actions: filter the grid by it, and the one verb
 *  that shapes what the item answers with.
 *
 *  Which verb depends on where the value came from, and the two are not each
 *  other's undo: a value you PROMOTED is un-pinned, one the active FILE gave
 *  you is muted, and a value only another file carries is pinned. So the row
 *  offers exactly one of them rather than a menu of three, two of which would
 *  do nothing. */
function MetaRowActions({ f, onFilter, onPin, onUnpin, onMute, onUnmute }: {
  f: MetadataField;
  onFilter?: () => void;
  onPin?: () => void;
  onUnpin?: () => void;
  onMute?: () => void;
  onUnmute?: () => void;
}) {
  const t = useT();
  const btn = (title: string, icon: string, onClick: () => void,
               color?: string) => (
    <IconButton icon={icon} size={20} glyph={14} reveal="fixed" color={color ?? "var(--muted-2)"}
      title={title}
      onClick={onClick} />
  );
  return (
    <span style={{ display: "flex", flex: "0 0 auto" }}>
      {onFilter && btn(t("Filter the grid by this metadata value"),
                       "filter_alt", onFilter)}
      {onPin && btn(t("Keep this for the item"), "add", onPin)}
      {onUnpin && btn(t("Stop keeping this for the item"), "close", onUnpin)}
      {onMute && btn(t("Ignore this for the item"), "visibility_off", onMute)}
      {onUnmute && btn(t("Use this for the item again"), "visibility",
                       onUnmute)}
    </span>
  );
}

/** The item's Info tab.
 *
 *  TWO lists, and the split is the whole feature. The MAIN section is what the
 *  item answers with — its own dates and dimensions, the values promoted to it,
 *  and what its ACTIVE file says. "Other files" is every value only a
 *  non-active file carries: OFFERED, never applied, because an item's several
 *  source files can disagree and which of them to believe is a decision rather
 *  than something to guess.
 *
 *  A promoted value is not marked with a colour. Amber in this app means "a
 *  machine said this and nobody has agreed yet", which is the opposite claim,
 *  and the accent means "what the next action applies to"; a person's own
 *  answer is the unmarked default here as it is under `TakenControl`. What a
 *  row DOES say, when there is more than one answer, is which file it came
 *  from — which is the only thing the value cannot say by itself. */
function MetadataSection({
  itemId,
  uid,
  leading = [],
  hideHeader = false,
}: {
  itemId: number;
  uid?: string;
  leading?: { key: string; value: string }[];
  hideHeader?: boolean;
}) {
  const t = useT();
  const { search, setSearch } = useUI();
  const { formatDateTime } = useDateFormatters();
  const [showOthers, setShowOthers] = useState(false);
  const { data } = useQuery({
    queryKey: ["item-metadata", itemId],
    queryFn: () => api.itemMetadata(itemId),
  });
  // Drop any EXIF field that duplicates a leading row (e.g. the image's own
  // "Dimensions" field, which we already show as a leading row).
  const leadKeys = new Set(leading.map((l) => l.key.toLowerCase()));
  const fields = (data?.fields ?? []).filter((f) => !leadKeys.has(f.key.toLowerCase()));
  const others = data?.others ?? [];

  // Append a metadata filter to the query (the uniform `INFO:name op value`
  // grammar). The backend serves both halves of the atom — the canonical name
  // and the value the INDEX holds — so there is no table here mapping display
  // keys back to catalog names, and no parser turning "4000 px" into 4000.
  const appendCond = (cond: string) => {
    const base = search.trim();
    setSearch(base ? `${base} ${cond}` : cond);
  };
  const quoteIf = (atom: string) => (/\s/.test(atom) ? `"${atom}"` : atom);
  const filterBy = (f: MetadataField) =>
    appendCond(quoteIf(`INFO:${f.name}=${f.filter_value}`));

  const run = async (p: Promise<unknown>) => {
    await p;
    // A pin or a mute changes what SEARCH answers, not just this panel — so
    // the grid, the facets and the metadata catalog all have to hear about it.
    bumpItem(itemId);
    bumpEdits();
  };

  /** The line under a row naming where its value came from — drawn only when
   *  the item has more than one answer for that name, since with one there is
   *  nothing to tell apart. */
  const sourceLine = (f: MetadataField, all: MetadataField[]) => {
    const siblings = all.filter((o) => o.name === f.name);
    if (siblings.length < 2 && !f.pinned) return undefined;
    const names = (f.sources ?? [])
      .map((s2: { number?: number | null }) => (s2.number != null ? `${s2.number}` : "?"))
      .join(", ");
    if (!names) return undefined;
    return f.pinned ? t("kept from file {n}", { n: names })
                    : t("from file {n}", { n: names });
  };

  const renderRow = (f: MetadataField, i: number,
                     all: MetadataField[], where: "main" | "other") => {
    const shown = f.iso ? formatDateTime(f.iso) : decodeMeta(f.name, f.value);
    const canFilter = !!(f.name && f.filter_value);
    return (
      <MetaRow
        key={`${f.key}-${f.value}-${i}`}
        label={f.key}
        value={shown}
        // The raw stored value in the tooltip wherever the display decodes it,
        // so the number an `INFO:flash=16` search wants is still readable.
        title={shown === f.value ? undefined : `${shown} (${f.value})`}
        sub={where === "main" ? sourceLine(f, all) : sourceLine(f, [f, f])}
        struck={f.muted}
        hoverable
        action={
          <MetaRowActions
            f={f}
            onFilter={canFilter ? () => filterBy(f) : undefined}
            onPin={where === "other" && f.name && f.sources?.[0]
              ? () => void run(api.pinItemMetadata(
                  itemId, f.name!, f.sources![0].file_id))
              : undefined}
            onUnpin={f.pinned && f.name
              ? () => void run(api.unpinItemMetadata(itemId, f.name!, f.value))
              : undefined}
            onMute={where === "main" && !f.pinned && !f.muted && f.name
                    && (f.sources ?? []).length > 0
              ? () => void run(api.muteItemMetadata(itemId, f.name!))
              : undefined}
            onUnmute={f.muted && f.name
              ? () => void run(api.unmuteItemMetadata(itemId, f.name!))
              : undefined}
          />
        }
      />
    );
  };

  return (
    <CollapsibleSection title="Info" sk="metadata" hideHeader={hideHeader}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {/* Item uid — always first, with a copy button (not a filter button). */}
        {uid && <UidMetaRow uid={uid} onFilter={() => appendCond(`INFO:id=${uid}`)} />}
        {/* Dimensions / resolution — always shown, no grid-filter button. */}
        {leading.map((f) => (
          <MetaRow key={`lead-${f.key}`} label={f.key} value={f.value} />
        ))}
        {fields.map((f, i) => renderRow(f, i, fields, "main"))}
        {others.length > 0 && (
          <>
            {/* Collapsed by default and behind a count, the shape Hidden faces
                already uses: this is context for the main list rather than part
                of it, and on a library where every item has one source file it
                is not there at all. */}
            <div
              onClick={() => setShowOthers((v) => !v)}
              style={{ marginTop: 6, padding: "2px 2px", cursor: "pointer",
                       display: "flex", alignItems: "center", gap: 4,
                       color: "var(--muted-2)", fontFamily: "var(--mono)",
                       fontSize: "var(--fs-2)" }}
            >
              <Icon name={showOthers ? "expand_more" : "chevron_right"} size={14} />
              {t("Other files say {n}", { n: others.length })}
            </div>
            {showOthers && others.map((f, i) => renderRow(f, i, others, "other"))}
          </>
        )}
      </div>
    </CollapsibleSection>
  );
}

/** Inline-editable item name; commits on blur or Enter, reverts on Escape. */
function EditableItemName({
  itemId,
  name,
  onSaved,
}: {
  itemId: number;
  name: string;
  onSaved: () => void;
}) {
  const [val, setVal] = useState(name);
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!focused) setVal(name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, itemId]);

  // A TEXTAREA THAT GROWS, not an input. A file name is regularly wider than a
  // 280 px sidebar, and an input can only ever cut one off — so the one place
  // the item is named showed `chapter-04-page-12-fin…` and the rest was a
  // tooltip. It wraps and takes as many lines as it needs, here and while it
  // is being edited; Enter still commits (a name has no lines in it), so the
  // only thing the element type changes is where the text is allowed to go.
  const fit = (el: HTMLTextAreaElement | null) => {
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };
  useEffect(() => { fit(inputRef.current); }, [val]);

  const commit = async () => {
    const v = val.trim();
    if (!v || v === name) {
      setVal(name);
      return;
    }
    await api.updateItem(itemId, { name: v });
    onSaved();
  };

  return (
    // Top-aligned: the pencil belongs beside the name's FIRST line, not
    // halfway down a name that runs to three.
    <div className="hoverable-name" style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "flex-start", gap: 3 }}>
      <textarea
        ref={inputRef}
        rows={1}
        value={val}
        title="Rename item"
        onChange={(e) => setVal(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => { setFocused(false); commit(); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            (e.target as HTMLTextAreaElement).blur();
          } else if (e.key === "Escape") {
            e.stopPropagation();
            setVal(name);
            (e.target as HTMLTextAreaElement).blur();
          }
        }}
        style={{
          // No left margin/padding, so the field's left edge (its focus box) and
          // the name text both line up flush-left with the thumbnail above it.
          // Only the border's 1px offsets the text, matching the preview's border.
          flex: 1, minWidth: 0, padding: "3px 6px 3px 0", marginLeft: 0,
          background: focused ? "var(--bg)" : "transparent",
          border: `1px solid ${focused ? "var(--border-strong)" : "transparent"}`,
          borderRadius: "var(--r-2)", color: "var(--text-bright)", fontWeight: 600, fontSize: "var(--fs-3)",
          fontFamily: "inherit", outline: "none",
          // It is a NAME, not a paragraph: it may take several lines, but it
          // may not be dragged to another size and it must never scroll inside
          // itself — `fit` gives it exactly the height its text needs.
          resize: "none", overflow: "hidden", lineHeight: 1.35,
          // A long unbroken name (no spaces, which most file names are) has to
          // be allowed to break mid-word or it simply overflows the sidebar.
          overflowWrap: "anywhere", whiteSpace: "pre-wrap",
        }}
      />
      {!focused && (
        <span
          title="Click the name to rename"
          onClick={() => inputRef.current?.focus()}
          style={{
            flex: "0 0 auto", display: "flex", alignItems: "center",
            height: 24, color: "var(--muted-2)", cursor: "pointer",
          }}
        >
          <Icon name="edit" size={13} />
        </span>
      )}
    </div>
  );
}

/** Autocomplete input for adding a tag to the assigned-tags list. The input and
 *  its list are `TagAutocomplete` (shared with the annotator); this only holds
 *  the text and clears it once the tag is added. */
function TagAdder({
  suggestions,
  fetchSuggestions,
  existing,
  onAdd,
  placeholder,
  shortcut,
  flush,
  onText, prefixes }: {
  suggestions?: TagSuggestion[];
  /** Typing-driven remote source — see `TagAutocomplete.fetchSuggestions`. */
  fetchSuggestions?: (q: string) => Promise<TagSuggestion[]>;
  existing: string[];
  onAdd: (name: string) => void;
  placeholder?: string;
  /** A key cap at the empty field's right end — the KEYBOARD way to do what
   *  this field does. Only the ungrouped adder shows it: that is the field
   *  the overlay stands in for, and one hint per panel is a hint rather than
   *  a decoration. */
  shortcut?: string;
  /** Inside a group box the column's own gap spaces the field, so the
   *  default margin would double it. */
  flush?: boolean;
  /** What is currently typed, as it changes — the group box highlights an
   *  already-assigned row matching it, so "it is already there" is shown
   *  rather than discovered on commit. */
  onText?: (v: string) => void;
  /** `TagAutocomplete`'s: `-`/`!` on the word, handed on in front of the
   *  committed name for `onAdd` to read. */
  prefixes?: boolean;
}) {
  const t = useT();
  const hint = placeholder ?? t("Add a tag…");
  const [text, setText] = useState("");
  return (
    <div style={{ marginBottom: flush ? 0 : 8, position: "relative" }}>
      <TagAutocomplete
        value={text}
        onChange={(v) => { setText(v); onText?.(v); }}
        onCommit={(name) => {
          if (name) { onAdd(name); setText(""); onText?.(""); }
        }}
        suggestions={suggestions}
        fetchSuggestions={fetchSuggestions}
        existing={existing}
        placeholder={hint}
        prefixes={prefixes}
      />
      {shortcut && text === "" && (
        // Gone the moment anything is typed: it is an offer, and over a name
        // being written it would be furniture. `pointerEvents: none`, so the
        // whole field is still a field.
        <kbd
          title={t("Tag the selection from the keyboard")}
          style={{
            position: "absolute", right: 7, top: 6, pointerEvents: "none",
            padding: "0 5px", borderRadius: "var(--r-1)",
            border: "1px solid var(--border-strong)",
            background: "var(--panel-2)", color: "var(--muted-2)",
            fontFamily: "var(--mono)", fontSize: "var(--fs-1)", fontWeight: 700,
            lineHeight: "16px",
          }}
        >{shortcut}</kbd>
      )}
    </div>
  );
}

/** Bind an existing tag group to a subject that is already on the item.
 *
 *  Only subjects ON THE ITEM are offered: a group is about somebody in this
 *  picture, and a list of every subject in the library would be a search box
 *  pretending to be a menu. */
function GroupSubjectAdder({ subjects, already, onAdd }: {
  subjects: { id: number; display_name: string; tag: string }[];
  already: number[];
  onAdd: (subjectId: number) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const free = subjects.filter((s) => !already.includes(s.id));
  const rect = useAnchorRect(ref, open && free.length > 0);
  if (free.length === 0) return null;
  return (
    <span style={{ position: "relative", display: "inline-flex" }}>
      <span
        ref={ref}
        className="row-action"
        onClick={() => setOpen((v) => !v)}
        title={t("Say who this group is about")}
        style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 16, height: 16, borderRadius: "var(--r-1)", cursor: "pointer",
          color: "var(--muted-2)", border: "1px dashed var(--border-strong)",
        }}
      >
        <Icon name="person_add" size={11} />
      </span>
      {open && (
        <AnchoredDropdown rect={rect} minWidth={170}>
          {free.map((s) => (
            <div key={s.id} className="hoverable"
              onMouseDown={(e) => { e.preventDefault(); onAdd(s.id); setOpen(false); }}
              style={{ display: "flex", alignItems: "center", gap: 7,
                padding: "6px 9px", borderRadius: "var(--r-2)", cursor: "pointer", fontSize: "var(--fs-3)" }}>
              <Icon name={RECORD_ICON.subject} size={14} color="var(--muted-2)" />
              {s.display_name || s.tag}
            </div>
          ))}
        </AnchoredDropdown>
      )}
    </span>
  );
}

/** The always-visible, collapsible Quick Assign panel pinned to the bottom.
 *
 * It manages the numbered TAG SETS (app/qaSets.ts): every row is a set, and
 * every row is its own live editor — there is no separate "current" editor,
 * because a set you cannot see while editing another is a set you re-open to
 * check. The number badge is the set's overlay key (a dropdown reassigns it),
 * SELECTING a row (a click on its background) is what arms the assign button,
 * `Shift+Q` and the click-to-assign mode, and with no row selected the button
 * becomes the way into the Q overlay, where every numbered set is one
 * keypress away. */
function QuickAssign() {
  const {
    selectedItems, qaSets, qaSelected, qaMode, qaEnabled,
    createQaSet, deleteQaSet, selectQaSet, setQaNumber,
    addQaTag, removeQaTag, flipQaTag, addQaGroup, removeQaGroup,
    toggleQaMode, toggleQaEnabled,
    setQaOverlay,
  } = useUI();
  // The group catalog, for the sets' membership chips and their adder.
  // `flattenGroupTree` skips smart groups — manual membership is exactly
  // what a smart group refuses.
  const { data: qaGroupTree } = useQuery({ queryKey: ["groups"],
                                           queryFn: api.groups });
  const qaGroupOptions = useMemo(
    () => flattenGroupTree(qaGroupTree ?? []), [qaGroupTree]);
  const t = useT();
  const tn = useTn();
  const [collapsed, setCollapsed] = useState(() => APP_PREFS.qaCollapsed.read());
  const toggle = () => {
    setCollapsed((c) => {
      const next = !c;
      APP_PREFS.qaCollapsed.write(next);
      return next;
    });
  };

  // HOW TALL THE SETS LIST MAY GROW — dragged at the drawer's top edge,
  // remembered like the face drawer's height, re-clamped on a window resize
  // (a window shrunk past it would leave the drawer taller than the sidebar).
  // A CAP rather than a height: a drawer of one set stays one set tall, and
  // past the cap the list SCROLLS instead of pushing the properties above it
  // off the panel.
  const drawer = useSplit({
    pref: APP_PREFS.qaHeight, min: QA_HEIGHT_MIN, max: qaHeightMax,
    axis: "y", from: "end", reclampOnResize: true,
  });
  const listMax = drawer.size;

  // FLIP the rows when a renumber re-sorts the list: remember where each row
  // (by its set's session id) last sat, and when a render moves one, animate
  // the difference away — an instant reorder reads as one row vanishing and
  // a stranger appearing, not as the move it is. Positions are `offsetTop`
  // (layout-relative), so scrolling the list or the panel above cannot fake
  // a move.
  const rowEls = useRef(new Map<number, HTMLDivElement>());
  const rowTops = useRef(new Map<number, number>());
  useLayoutEffect(() => {
    for (const [id, el] of rowEls.current) {
      const prev = rowTops.current.get(id);
      const now = el.offsetTop;
      if (prev != null && Math.abs(prev - now) > 1) {
        el.animate(
          [{ transform: `translateY(${prev - now}px)` },
           { transform: "translateY(0)" }],
          { duration: 180, easing: "ease" },
        );
      }
      rowTops.current.set(id, now);
    }
  });

  const items = useLoadedViewItems();
  const sel = qaSelected != null ? qaSets[qaSelected] ?? null : null;
  const qaActive = sel != null && !setIsEmpty(sel);

  // Memoized: rebuilding these maps on every render of the always-mounted
  // panel was pure waste — `items` only changes identity when loaded pages do.
  const byId = useMemo(
    () => new Map(items.map((it) => [it.id, it.direct_tags])),
    [items]
  );
  const groupsById = useMemo(
    () => new Map(items.map((it) => [it.id, it.group_ids ?? []])),
    [items]
  );
  // Whether every selected item already carries the whole selected set — the
  // button's toggle, asked through `qaSetMatch`, WHICH IS THE SAME QUESTION
  // THE OVERLAY'S ROWS COLOUR THEMSELVES BY.
  //
  // It was asked of the TAGS alone, and a set's GROUPS are part of what it
  // stamps: a set of one group answered "every item carries it" for any
  // selection at all — both tag lists are empty, so "every tag is there" is
  // vacuously true — and the button sat red, offering to remove a membership
  // it had never added. Skipped past HEAVY_SELECTION like every other
  // per-item aggregate in this panel; an item whose page is not loaded
  // counts as not carrying the set, which is what it has always done.
  const allSelectedHave =
    qaActive && sel != null &&
    selectedItems.length > 0 && selectedItems.length <= HEAVY_SELECTION &&
    qaSetMatch(selectedItems.map((id) => byId.get(id) ?? []), sel,
               selectedItems.map((id) => groupsById.get(id) ?? [])) === "full";

  // What the last apply did, said out loud. The button is at the BOTTOM of a
  // sidebar that may be collapsed and is nowhere near what you are looking at,
  // so a keyboard apply otherwise changed the library with nothing to see.
  const [note, setNote] = useState<string | null>(null);

  // The selection, or — with nothing selected — the VIEW, the same two scopes
  // the Q and T overlays stamp (`useViewScope` reads the grid's own page 1,
  // so this costs nothing while a grid is on screen).
  const view = useViewScope();
  const wholeView = selectedItems.length === 0;

  const applyQuick = async (remove: boolean) => {
    if (!sel || !qaActive) return;
    let n: number;
    if (wholeView) {
      if (!(view.total && view.total > 0)) return;
      // No toggle over the whole view: whether every item carries the set is
      // unknowable from loaded pages, so a whole-view press only assigns.
      const r = await api.quickAssignView({
        ...view.req, positive: sel.pos, negative: sel.neg,
        assign_groups: sel.groups, remove: false,
      });
      n = r.count;
      remove = false;
      // A whole-view write touches items this page has never heard of; the
      // library sweep is what refreshes the grid.
      bumpLibrary();
    } else {
      const r = await api.quickAssign({
        item_ids: selectedItems,
        positive: sel.pos,
        negative: sel.neg,
        // The set's GROUP memberships, stamped beside its tags — the overlay
        // and the grid's click-to-assign have always sent them, and this
        // button applied the tags alone, so a set holding a group did
        // nothing about that group however often it was pressed.
        assign_groups: sel.groups,
        remove,
      });
      n = r.count;
      for (const id of selectedItems) bumpItem(id);
    }
    bumpEdits();
    // One sentence per count: the map is keyed by the English source, so a
    // plural rule cannot live inside the interpolation.
    setNote(remove
      ? tn({ one: "Removed the quick assign set from 1 item",
             other: "Removed the quick assign set from {n} items" }, n)
      : tn({ one: "Applied the quick assign set to 1 item",
             other: "Applied the quick assign set to {n} items" }, n));
  };

  const disabled =
    !qaEnabled || !qaActive || (wholeView && !(view.total && view.total > 0));

  // SHIFT+Q APPLIES THE SELECTED SET — the button's own action, keyboard-side.
  // It is the one thing in this panel done over and over (a picture, a key,
  // the next picture), and reaching for a button at the bottom of the sidebar
  // between every two of them is the whole complaint. Bare Q opens the
  // OVERLAY, where any numbered set is a digit away; the modifier is what
  // keeps the rapid-fire path one keystroke. It does exactly what the button
  // does, REMOVE included — one action wearing two behaviours would be worse
  // than the button saying which it is about to do, which it does. With no
  // set selected this handler stands down and the overlay's own listener
  // reads Shift+Q as Q.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (modalIsOpen()) return;
      if (e.key !== "q" && e.key !== "Q") return;
      if (!e.shiftKey || e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e)) return;
      if (sel == null) return; // the overlay's listener owns this case
      if (disabled) return; // `disabled` folds in the ⋯ menu's master switch
      e.preventDefault();
      void applyQuick(allSelectedHave);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disabled, allSelectedHave, selectedItems, qaSets, qaSelected, view.total]);

  const kbdStyle: React.CSSProperties = {
    marginLeft: 2, padding: "1px 5px", borderRadius: "var(--r-1)",
    border: "1px solid currentColor", opacity: 0.55,
    fontFamily: "var(--mono)", fontSize: "var(--fs-1)", fontWeight: 700,
    lineHeight: "14px",
  };

  return (
    <div style={{ flex: "0 0 auto", borderTop: "1px solid var(--border)",
                  background: "var(--panel-3)", position: "relative" }}>
      {/* The drawer's top edge is the resize handle (the face drawer's
          gesture) — a thin strip straddling the border, so it steals no
          height from the header it sits over. */}
      {!collapsed && (
        <SplitHandle split={drawer} thickness={7} style={{ top: -3, zIndex: 1 }} />
      )}
      <div
        style={{
          display: "flex", alignItems: "center", gap: 7, padding: "11px 14px",
          cursor: "pointer",
        }}
        onClick={toggle}
      >
        <Icon name="bolt" size={18} color="var(--accent)" />
        <span style={SECTION_LABEL}>{t("Quick Assign")}</span>
        {/* NEW SET lives in the header, beside the chevron — inside the body
            it moved every time the list grew, and it is never refused: sets
            are unlimited, only the nine number keys are not. Hidden while the
            drawer is collapsed, because it would be making rows nobody can
            see. */}
        {!collapsed && qaEnabled && (
          <IconButton icon="add" size={22} glyph={20} reveal="hover" tone="muted"
            title={t("New set")}
            onClick={(e) => { e.stopPropagation(); createQaSet(); }}
            // Borderless, drawn like the chevron beside it — same glyph size
            // and weight, so the header reads as one row of quiet marks.
            style={{ marginLeft: "auto" }} />
        )}
        {/* The section's own switches, under a ⋯: the feature's master
            switch (nine bare digit keys that write tags want an off switch),
            and the click-to-assign mode — which used to hide behind the
            assign button's chevron, a menu of one entry. The mode's entry is
            DISABLED (shown, inert) while the master switch is off. */}
        {!collapsed && (
          <span onClick={(e) => e.stopPropagation()}
                style={{ display: "flex", alignItems: "center",
                         marginLeft: qaEnabled ? 0 : "auto" }}>
            <RowMenu
              always
              icon="more_horiz"
              // The header's plus and chevron are drawn in `--muted`; the
              // row default (`--muted-2`) read darker beside them.
              color="var(--muted)"
              title={t("Quick Assign options")}
              actions={[
                { checked: qaEnabled, label: t("Enabled"),
                  onClick: toggleQaEnabled },
                { checked: qaMode, label: t("Assign on click"),
                  disabled: !qaEnabled, onClick: toggleQaMode },
              ]}
            />
          </span>
        )}
        <Icon
          name={collapsed ? "expand_less" : "expand_more"}
          size={20}
          color="var(--muted)"
          style={{ marginLeft: collapsed ? "auto" : 0 }}
        />
      </div>

      {/* Animated expand/collapse (grid-rows 0fr→1fr; body clipped by overflow). */}
      <Collapse open={!collapsed}>
        {/* Greyed and inert while the ⋯ menu's master switch is off — the
            header stays live, since it holds the switch that comes back. */}
        <div style={{ padding: "0 14px 14px",
                      opacity: qaEnabled ? 1 : 0.45,
                      pointerEvents: qaEnabled ? undefined : "none" }}>

          {/* THE SETS, each row a live editor. Clicking a row's BACKGROUND
              selects it (the editor swallows only clicks that hit something
              in it — the MetaTagAdder rule); the selected row is what the
              assign button, Shift+Q and the click-to-assign mode stamp, and
              clicking it again puts it down. The list SCROLLS past the
              dragged cap rather than pushing the panel above off screen. */}
          <div style={{ display: "flex", flexDirection: "column", gap: 4,
                        maxHeight: listMax, overflowY: "auto" }}>
            {qaSets.map((set, i) => {
              const isSel = qaSelected === i;
              return (
                <div
                  // Keyed by the set's IDENTITY, not its position — the list
                  // is sorted by number, so a renumber moves rows, and index
                  // keys would remount them where the id lets them travel
                  // (and the FLIP above animate the trip).
                  key={set.id}
                  ref={(el) => {
                    if (el) rowEls.current.set(set.id, el);
                    else {
                      rowEls.current.delete(set.id);
                      rowTops.current.delete(set.id);
                    }
                  }}
                  onClick={() => selectQaSet(i)}
                  style={{
                    display: "flex", alignItems: "flex-start", gap: 7,
                    padding: 6, borderRadius: "var(--r-4)", cursor: "pointer",
                    background: isSel ? "var(--accent-dim)" : "var(--panel-2)",
                    border: `1px solid ${isSel ? "var(--accent)" : "var(--border)"}`,
                  }}
                >
                  <QaNumBadge num={set.num} selected={isSel}
                              onPick={(n) => setQaNumber(i, n)} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {/* One editor for the whole set: tag chips, then the
                        GROUP-membership chips (accent + folder), then the
                        two adders — the same field-plus-autocomplete for
                        both kinds. `flattenGroupTree` already skips smart
                        groups, exactly the ones manual membership
                        refuses. */}
                    <CombinedTagEditor
                      pos={set.pos}
                      neg={set.neg}
                      fetchSuggestions={fetchTagSuggestions}
                      onAdd={(tag) => addQaTag(i, tag)}
                      onFlip={(tag) => flipQaTag(i, tag)}
                      onRemove={(tag) => removeQaTag(i, tag)}
                      groups={set.groups}
                      groupOptions={qaGroupOptions}
                      onAddGroup={(gid) => addQaGroup(i, gid)}
                      onRemoveGroup={(gid) => removeQaGroup(i, gid)}
                      addersBelow
                    />
                  </div>
                  {/* No ✕ on the one set there must always be while it is
                      EMPTY: deleting it replaces it with an identical empty
                      set (`deleteQaSet` keeps at least one), so the button
                      did nothing. It comes back with the first tag, group or
                      second set — then it has something to take away. */}
                  {!(qaSets.length === 1 && set.pos.length === 0 && set.neg.length === 0
                     && set.groups.length === 0) && (
                  <IconButton icon="close" size={20} glyph={14} reveal="hover" tone="danger"
                    title={t("Delete this quick assign set")}
                    onClick={(ev) => { ev.stopPropagation(); deleteQaSet(i); }}
                    // marginTop centres the 20px button on the 25px chip
                    // line — fractional, like the badge's, or the rounding
                    // reads as extra padding above the row's content.
                    style={{ flex: "0 0 auto", marginTop: 2.5 }} />
                  )}
                </div>
              );
            })}
          </div>

          {/* ONE PLAIN BUTTON — it lost its chevron when "Assign on click"
              moved into the header's ⋯ menu, beside the feature's master
              switch, where a setting about the whole section belongs.

              IN THE MODE the button becomes the way OUT of it. Nothing else it
              could say is true while the mode is on — the grid is doing the
              applying, click by click — and a mode whose only exit is a menu
              is a mode people get stuck in.

              WITH NO SET SELECTED it is the way into the Q overlay instead —
              the same thing the bare shortcut does, which is why only this
              state wears the Q cap. */}
          <div style={{ marginTop: 12, display: "flex" }}>
            {qaMode && qaActive ? (
              <button
                onClick={toggleQaMode}
                title={t("Click images in the grid to stamp this quick assign set onto them")}
                style={{ ...splitMainStyle, flex: 1, height: 32, borderRadius: "var(--r-4)",
                  background: "var(--accent-dim)", color: "var(--accent)",
                  cursor: "pointer" }}
              >
                <Icon name="ads_click" size={16} />
                {t("Stop assigning on click")}
              </button>
            ) : sel == null ? (
              <button
                onClick={() => { if (qaEnabled) setQaOverlay(true); }}
                disabled={!qaEnabled}
                // The shortcut is named ON the button, which is the only
                // place somebody looking for it would think to look.
                title={qaEnabled
                  ? t("Shortcut: Q") : t("Quick Assign is disabled")}
                // The same green the apply states wear — a flat panel grey
                // here read as a disabled button, and this state is the
                // OPPOSITE of disabled: it is the way into the overlay.
                style={{
                  ...splitMainStyle, flex: 1, height: 32, fontSize: "var(--fs-3)",
                  borderRadius: "var(--r-4)",
                  background: qaEnabled ? "var(--green)" : "var(--border)",
                  color: qaEnabled ? "var(--on-accent)" : "var(--muted)",
                  cursor: qaEnabled ? "pointer" : "default",
                }}
              >
                <Icon name="bolt" size={16} />
                {t("Quick assign…")}
                {qaEnabled && <kbd style={kbdStyle}>Q</kbd>}
              </button>
            ) : (
              <button
                onClick={() => applyQuick(allSelectedHave)}
                disabled={disabled}
                title={
                  !qaEnabled ? t("Quick Assign is disabled")
                  : !qaActive ? t("Add at least one Quick Assign tag")
                  : wholeView && !(view.total && view.total > 0)
                    ? t("The view is empty")
                  : t("Shortcut: Shift+Q")
                }
                style={{
                  ...splitMainStyle, flex: 1, height: 32, fontSize: "var(--fs-3)",
                  borderRadius: "var(--r-4)",
                  // The remove state is the green button in red — the same
                  // solid weight, so it reads as the same control about to
                  // do the opposite thing (a dim wash read as disabled).
                  background: disabled ? "var(--border)"
                    : allSelectedHave ? "var(--red)" : "var(--green)",
                  color: disabled ? "var(--muted)" : "var(--on-accent)",
                  cursor: disabled ? "default" : "pointer",
                }}
              >
                <Icon name={allSelectedHave ? "backspace" : "bolt"} size={16} />
                {wholeView
                  ? tn({ one: "Apply to the 1 item in view",
                         other: "Apply to all {n} in view" }, view.total ?? 0)
                  : <>{allSelectedHave ? t("Remove from") : t("Apply to")} {selectedItems.length} {t("selected")}</>}
                {/* The KEY, on the button it presses. A shortcut that lives
                    only in a tooltip is one nobody finds; a step quieter
                    than the verb, because it names the same action rather
                    than a second one. */}
                {!disabled && <kbd style={kbdStyle}>⇧Q</kbd>}
              </button>
            )}
          </div>
        </div>
        </Collapse>
      {note && (
        <ActionToast autoDismissMs={4000}
          text={note}
          icon="check"
          actionLabel={t("OK")}
          onAction={() => setNote(null)}
          dismissTitle={t("Dismiss")}
          onDismiss={() => setNote(null)}
        />
      )}
    </div>
  );
}

/**
 * A set's number key, as a badge that is also the control that changes it:
 * clicking opens a dropdown of "–" (no number) and 1–9. Picking a number
 * another set carries EXCHANGES the two (`assignNumber`), so nothing is ever
 * refused; "–" takes the set out of the Q overlay until it gets a key again.
 */
function QaNumBadge({ num, onPick, selected }: {
  num: number | null;
  onPick: (n: number | null) => void;
  /** The set this badge belongs to is the selected one — the badge wears the
   *  row's accent too, or the row reads as picked everywhere but the one
   *  part of it that names the key. */
  selected?: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const rect = useAnchorRect(ref, open);
  // A click outside closes the menu instead of landing on (and selecting)
  // a set row — the one rule, not a click-catcher behind the panel.
  useMenuDismiss(open, () => setOpen(false), { within: [ref] });
  const options: (number | null)[] =
    [null, ...Array.from({ length: QA_NUM_MAX }, (_, i) => i + 1)];
  return (
    <>
      <span
        ref={ref}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        title={t("Change the set's number")}
        style={{
          flex: "0 0 auto", minWidth: 22, height: 22, boxSizing: "border-box",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          // Centred on the 25px chip line beside it — FRACTIONAL, because
          // (25 − 22) / 2 rounded up is what made the set row's inset read
          // bigger at the top than at the bottom.
          padding: "0 4px", borderRadius: "var(--r-2)", cursor: "pointer", marginTop: 1.5,
          border: `1px solid ${selected ? "var(--accent)" : "var(--border-strong)"}`,
          background: selected ? "var(--accent-dim)" : "var(--panel-2)",
          color: selected ? "var(--accent)"
            : num == null ? "var(--muted-2)" : "var(--text)",
          fontFamily: "var(--mono)", fontSize: "var(--fs-2)", fontWeight: 700,
        }}
      >
        {num ?? "–"}
      </span>
      {open && (
        <AnchoredDropdown rect={rect} minWidth={64}>
          {options.map((n) => (
            <div
              key={n ?? "none"}
              className="hoverable"
              onMouseDown={(e) => { e.preventDefault(); onPick(n); setOpen(false); }}
              style={{
                display: "flex", alignItems: "center", gap: 7,
                padding: "5px 9px", borderRadius: "var(--r-2)", cursor: "pointer",
                fontSize: "var(--fs-3)", fontFamily: "var(--mono)",
                color: n === num ? "var(--accent)" : undefined,
              }}
            >
              {n == null ? t("No number") : n}
              {n === num && (
                <Icon name="check" size={13} style={{ marginLeft: "auto" }} />
              )}
            </div>
          ))}
        </AnchoredDropdown>
      )}
    </>
  );
}

/**
 * A small crop icon (when a tag has a bounding box) with a hover preview of the
 * image showing the highlighted area, plus inline time-range text (for videos),
 * mirroring how inherited group names are shown after a tag name.
 */
export function TagAnnotation({
  boxes,
  activeFileId,
  activeFile,
  onOpen,
  inherited,
  title,
}: {
  boxes: NonNullable<TagAssignment["boxes"]>;
  activeFileId: number | null;
  activeFile: FileVersion | null;
  // When set, clicking the bbox icon opens the editor with this tag selected.
  onOpen?: () => void;
  /** The shape is INHERITED rather than the row's own — a person row
   *  falling back to its face's outline. Grey, so the icon says so. */
  inherited?: boolean;
  /** The icon's tooltip, where the caller's wording is finer than the
   *  default ("outlined" vs "has a region"). */
  title?: string;
}) {
  const tn = useTn();
  const t = useT();
  // Boxes are stored in the item's reference frame; map them into the active
  // file's frame (a cropped variant shows a sub-region), which may push a box
  // partly or fully outside [0,1] — that's fine, it's clipped visually.
  const cx = activeFile?.crop_x ?? 0, cy = activeFile?.crop_y ?? 0;
  const cw = activeFile?.crop_w ?? 1, ch = activeFile?.crop_h ?? 1;
  const toFile = (b: NonNullable<TagAssignment["boxes"]>[number]) => ({
    x: ((b.x ?? 0) - cx) / (cw || 1),
    y: ((b.y ?? 0) - cy) / (ch || 1),
    w: (b.w ?? 0) / (cw || 1),
    h: (b.h ?? 0) / (ch || 1),
  });
  // Fixed-position preview anchored to the left of the icon, so it isn't clipped
  // by the sidebar's edge / scroll overflow.
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  // Same for the time-range list, which hangs off its own icon.
  const [timePos, setTimePos] = useState<{ top: number; left: number } | null>(null);
  const bbox = boxes.filter((b) => b.x != null && b.w != null);
  const ranges = boxes
    .filter((b) => b.time_start != null)
    .sort((a, b) => (a.time_start ?? 0) - (b.time_start ?? 0));
  const fps = activeFile?.frame_rate && activeFile.frame_rate > 0 ? activeFile.frame_rate : 25;

  return (
    <span
      style={{ flex: "0 0 auto", display: "flex", alignItems: "center", gap: 5, marginLeft: 4, position: "relative" }}
    >
      {/* Timed tag: an icon, not a list of times. Spelled out inline the times
          crowded (and truncated) the row as soon as a tag had a few of them;
          they are all here on hover, at full frame-accurate timecode. */}
      {ranges.length > 0 && (
        <span
          onMouseEnter={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            setTimePos({ top: r.top + r.height / 2, left: r.left });
          }}
          onMouseLeave={() => setTimePos(null)}
          title={tn({ one: "Active at 1 time — hover to see it",
                      other: "Active at {n} times — hover to see them" },
                    ranges.length)}
          style={{ display: "flex", alignItems: "center", color: "var(--accent)", cursor: "help" }}
        >
          <Icon name="schedule" size={13} />
          {timePos && (
            <span
              style={{
                position: "fixed", top: timePos.top, left: timePos.left - 8,
                transform: "translate(-100%, -50%)", zIndex: 60,
                background: "var(--surface-float)", border: "1px solid var(--menu-border)",
                borderRadius: "var(--r-4)", padding: "5px 8px", boxShadow: "var(--shadow-3)",
                pointerEvents: "none", display: "flex", flexDirection: "column", gap: 2,
                maxHeight: 260, overflow: "hidden",
              }}
            >
              {ranges.slice(0, 12).map((b, i) => (
                <span key={i} style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--text-2)", whiteSpace: "nowrap" }}>
                  {formatTimecode(b.time_start as number, fps, true)}
                  {b.time_end != null && ` – ${formatTimecode(b.time_end, fps, true)}`}
                </span>
              ))}
              {ranges.length > 12 && (
                <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>+{ranges.length - 12} more</span>
              )}
            </span>
          )}
        </span>
      )}
      {bbox.length > 0 && (
        <span
          onMouseEnter={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            setPos({ top: r.top + r.height / 2, left: r.left });
          }}
          onMouseLeave={() => setPos(null)}
          onClick={onOpen ? (e) => { e.stopPropagation(); onOpen(); } : undefined}
          // "Region", not "bounding box": the shape may be a polygon now.
          title={onOpen ? t("Edit this tag's region in the editor")
            : title ?? t("Has a drawn region — hover to preview")}
          style={{ display: "flex", alignItems: "center",
            color: inherited ? "var(--muted-2)" : "var(--accent)",
            cursor: onOpen ? "pointer" : "help" }}
        >
          <Icon name="crop_free" size={13} />
          {pos && activeFileId != null && (
            <span
              style={{
                position: "fixed", top: pos.top, left: pos.left - 8,
                transform: "translate(-100%, -50%)", zIndex: 60,
                width: 280, background: "var(--surface-float)",
                border: "1px solid var(--menu-border)", borderRadius: "var(--r-4)",
                padding: 6, boxShadow: "var(--shadow-3)",
                pointerEvents: "none",
              }}
            >
              <span className="mc-checker" style={{ position: "relative", display: "block", overflow: "hidden", borderRadius: 4 }}>
                <img
                  src={api.thumbUrl(activeFileId)}
                  alt=""
                  style={{ width: "100%", borderRadius: 4, display: "block" }}
                />
                {bbox.map((raw, i) => {
                  const b = toFile(raw);
                  // A polygon draws its actual SHAPE, not its bounding box —
                  // the bbox covers plenty the outline deliberately leaves
                  // out, and the preview exists to show what was drawn.
                  if (raw.points?.length) {
                    const pts = raw.points.map(([px, py]) =>
                      `${(px - cx) / (cw || 1)},${(py - cy) / (ch || 1)}`)
                      .join(" ");
                    return (
                      <svg key={i} viewBox="0 0 1 1"
                        preserveAspectRatio="none"
                        style={{ position: "absolute", inset: 0,
                                 width: "100%", height: "100%",
                                 display: "block", overflow: "hidden" }}>
                        <polygon points={pts} fill="var(--accent-dim)"
                          stroke="var(--accent)" strokeWidth={2}
                          vectorEffect="non-scaling-stroke"
                          strokeLinejoin="round" />
                      </svg>
                    );
                  }
                  return (
                    <span
                      key={i}
                      style={{
                        position: "absolute",
                        left: `${b.x * 100}%`, top: `${b.y * 100}%`,
                        width: `${b.w * 100}%`, height: `${b.h * 100}%`,
                        border: "2px solid var(--accent)",
                        background: "var(--accent-dim)", borderRadius: 2,
                      }}
                    />
                  );
                })}
              </span>
            </span>
          )}
        </span>
      )}
    </span>
  );
}

// Member rows sit back-to-back (no gap) so a run of selected rows merges into
// one rounded block.
const SEQ_ROW = 27;

// HEAVY_SELECTION (the cap past which the sidebar skips per-item aggregations)
// lives in app/qaSets.ts now, shared with the Q overlay's match colours.

/**
 * Sequences the current selection belongs to — ONE ROW PER SEQUENCE,
 * deliberately without the member sublist each row used to expand into. A
 * sidebar about a PICTURE that listed every page of every book it is in
 * buried the answer it exists to give (which sequences, and where in them),
 * and the members already have two homes: the sequence-scoped grid, and the
 * member list shown when the container item itself is selected.
 *
 * A row is like every other row in this panel: it SELECTS (the shared
 * gestures — click, ⌘/Ctrl, shift, paint), reports to the selection bar and
 * gets its removal undone by the undo bar. It carries no hover ✕ of its own;
 * removing is the bar's job, which is what stops a list of rows behaving one
 * way here and another way in the tab beside it.
 *
 * WHERE THE PICTURE SITS IS A SUBTITLE, and it wraps. A page repeated
 * eighteen times names eighteen positions, and inline they pushed the
 * sequence's name off the row entirely — which is the one thing a row about
 * a sequence has to show.
 *
 * The name is READ-ONLY here. It is the container ITEM's name, and an item is
 * renamed where every other item is: in its own Item tab, from the sequence
 * you can reach in one click through the grid button.
 */
/** A full-width panel button, the shape the item sidebar's rows already
 *  have. Its own rather than the overlay footer's `GhostButton`: this column
 *  is 260px and the verbs here carry a sentence, so they stack. */
function ActionBtn({ icon, label, danger, onClick }: {
  icon: string; label: string; danger?: boolean; onClick: () => void;
}) {
  return (
    <Button variant={danger ? "danger" : "ghost"} size="sm" block justify="start" onClick={onClick} style={{ textAlign: "left" }}>
      <Icon name={icon} size={15} />
      <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}>{label}</span>
    </Button>
  );
}

/** THE RANKING'S THREE VERBS, over however many pictures they are aimed at.
 *
 *  The sidebar offers them at three sizes and they mean the same thing at
 *  each: the picked picture, a selection of them, and — with nothing picked —
 *  everything in the view. One component, because three copies of "set aside"
 *  would be three chances for them to stop agreeing about what it does, and
 *  one request either way: the ids travel for a selection, the SCOPE travels
 *  for a view (a view can be the whole library, and its ids are not something
 *  a browser should be holding).
 *
 *  BOTH DIRECTIONS ARE OFFERED past a single picture. One picture knows
 *  whether it is set aside and the button says the other thing; a selection
 *  is routinely a mix, and a button that guessed a direction from the
 *  majority would act on the ones it guessed wrong about.
 */
function RankingVerbs({ rankingId, items, view, count, onDone }: {
  rankingId: number;
  /** The pictures, when they are named. Empty with `view`. */
  items: number[];
  /** The view's own scope body — what "everything in this view" travels as. */
  view?: RankingItemsBody | null;
  /** How many pictures this is about, for the labels and the question. */
  count: number;
  onDone: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const errText = useErrText();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const body = items.length ? { items } : { ...(view ?? {}), view: true };
  const run = (verb: "dismiss" | "undismiss" | "remove",
               say: (n: number) => string) => {
    if (busy) return;
    setBusy(true);
    void api.rankingItemsVerb(rankingId, verb, body)
      .then((r) => { setNote(say(verb === "remove" ? r.judgments : r.count));
                     onDone(); })
      .catch((e) => setNote(errText(e)))
      .finally(() => setBusy(false));
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <ActionBtn
        icon="block"
        label={tn({ one: "Set 1 picture aside",
                    other: "Set {n} pictures aside" }, count)}
        onClick={() => run("dismiss", (n) =>
          tn({ one: "1 picture set aside", other: "{n} pictures set aside" }, n))}
      />
      <ActionBtn
        icon="undo"
        label={t("Rate them after all")}
        onClick={() => run("undismiss", (n) =>
          tn({ one: "1 picture back in the fit",
               other: "{n} pictures back in the fit" }, n))}
      />
      <ActionBtn
        icon="delete"
        danger
        label={t("Remove from this ranking")}
        onClick={async () => {
          // THE COMPARISONS ARE WHAT GOES, and the number of them is not
          // knowable before the walk over a view — so the question names the
          // pictures, which is what was asked for, and the answer names the
          // comparisons, which is what happened.
          if (!(await confirm({
            title: tn({ one: "Take this picture out of the ranking?",
                        other: "Take these {n} pictures out of the ranking?" }, count),
            body: tn({
              one: "The comparisons it was part of are deleted and the standings refit.",
              other: "The comparisons they were part of are deleted and the standings refit.",
            }, count),
            answer: { label: t("Remove"), danger: true },
          }))) return;
          run("remove", (n) =>
            tn({ one: "1 comparison deleted", other: "{n} comparisons deleted" }, n));
        }}
      />
      {note && (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>{note}</div>
      )}
    </div>
  );
}

/** WHERE THIS PICTURE STANDS on the ranking whose view you are in.
 *
 *  The ITEM half of a ranking. The scale, the pools and the too-few-
 *  comparisons caveat are the whole-view panel's (`RankingScopeCard`), and
 *  that unmounts the moment a picture is picked — which in a ranking view is
 *  the primary gesture, since the standings ARE the grid now and "is this
 *  really a 9" is answered by looking at the picture.
 *
 *  TWO VERBS THAT MUST NOT READ ALIKE. **Not applicable** sets the picture
 *  aside and is reversible — its judgments stay, it simply leaves the fit.
 *  **Remove from this ranking** DELETES every comparison it was part of and
 *  refits without it, which is why it carries the count and asks first.
 */
function RankingItemSection({ rankingId, itemId, hideHeader }: {
  rankingId: number;
  itemId: number;
  hideHeader?: boolean;
}) {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["ranking-standing", rankingId, itemId],
    queryFn: () => api.rankingItemStanding(rankingId, itemId) });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["ranking-standing"] });
    qc.invalidateQueries({ queryKey: ["rankings"] });
    qc.invalidateQueries({ queryKey: ["ranking-detail"] });
    bumpLibrary();
  };
  if (!data) return null;
  const row = (label: string, value: React.ReactNode) => (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8,
                  fontSize: "var(--fs-3)", padding: "3px 0" }}>
      <span style={{ color: "var(--muted-2)", flex: 1, overflow: "hidden",
                     textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
      <span style={{ color: "var(--text)", flex: "0 0 auto",
                     fontFamily: "var(--mono)" }}>{value}</span>
    </div>
  );
  return (
    <div style={{ marginBottom: 18 }}>
      {!hideHeader && (
        <label style={{ ...SECTION_LABEL, letterSpacing: "0.04em" }}>Ranking</label>
      )}
      <div style={{ marginTop: 8 }}>
        {data.placed.length > 0
          ? data.placed.map(([lid, name, bucket]) => (
              <div key={lid}>
                {row(name || t("Default"), `${bucket} / ${data.bucket_hi}`)}
              </div>
            ))
          : (
            <div className="mc-copy" style={{ fontSize: "var(--fs-2)",
                                              color: "var(--muted)" }}>
              {data.dismissed
                ? t("Set aside on this ranking — its comparisons are kept.")
                : t("Not placed on this ranking yet.")}
            </div>
          )}
        {data.judgments > 0 && row(
          t("Comparisons"), String(data.judgments))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6,
                    marginTop: 10 }}>
        <ActionBtn
          icon={data.dismissed ? "undo" : "block"}
          label={data.dismissed ? t("Rate it after all") : t("Not applicable")}
          onClick={() => void (data.dismissed
            ? api.rankingUndismiss(rankingId, itemId)
            : api.rankingDismiss(rankingId, itemId)).then(refresh)} />
        {data.judgments > 0 && (
          <ActionBtn
            icon="delete"
            danger
            label={t("Remove from this ranking")}
            onClick={async () => {
              if (!(await confirm({
                title: t("Take this picture out of the ranking?"),
                body: tn({
                  one: "Its 1 comparison is deleted and the standings refit.",
                  other: "Its {n} comparisons are deleted and the standings refit.",
                }, data.judgments),
                answer: { label: t("Remove"), danger: true },
              }))) return;
              void api.rankingRemoveItem(rankingId, itemId).then(refresh);
            }} />
        )}
      </div>
    </div>
  );
}

function SequenceSection({ onChange, hideHeader }: {
  onChange: () => void;
  // Drop the "Sequence" heading when this is the sole content of the Sequence
  // tab (the tab label already names it).
  hideHeader?: boolean;
}) {
  const qc = useQueryClient();
  const t = useT();
  const undoRun = useUndoRun();
  // Follow the same (pinned-aware) selection as the rest of the sidebar: while
  // pinned the section stays on the frozen pinned items rather than tracking the
  // grid selection.
  const liveSelectedItems = useUI((s) => s.selectedItems);
  const pinnedSelection = useUI((s) => s.pinnedSelection);
  const pinnedItems = useUI((s) => s.pinnedItems);
  const selectedItems = pinnedSelection ? pinnedItems : liveSelectedItems;
  const showSequence = useUI((s) => s.showSequence);
  const ids = useMemo(() => [...selectedItems].sort((a, b) => a - b), [selectedItems]);

  const { data: seqs } = useQuery({
    queryKey: ["sequences", ids],
    // One request per selected item — skip entirely for huge selections.
    enabled: ids.length > 0 && ids.length <= HEAVY_SELECTION,
    // Keep the previous list visible while refetching so a removal doesn't
    // collapse the section for a beat.
    placeholderData: (prev) => prev,
    queryFn: async () => {
      const per = await Promise.all(
        ids.map((id) => api.itemSequences(id).then((s) => ({ id, s })))
      );
      const byId = new Map<number, SequenceInfo>();
      for (const { s } of per)
        for (const seq of s) if (!byId.has(seq.id)) byId.set(seq.id, { ...seq, is_main: false });
      // Sequences are always shown in order of creation (by id); they can't be
      // reordered or promoted.
      return [...byId.values()].sort((a, b) => a.id - b.id);
    },
  });

  const list = seqs ?? [];
  const sel = useRowSelect(list.map((s) => `q:${s.id}`));

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["sequences"] });
    onChange();
  };

  // Taking the selected picture(s) out of the picked sequences. Every
  // OCCURRENCE goes: the item-id removal is the bulk tag set, and pointing
  // at one copy of a repeated page is the member list's job — a row that
  // names the sequence cannot say which copy.
  const removeSelected = () => {
    const picked = list.filter((s) => sel.has(`q:${s.id}`));
    if (!picked.length) return;
    void undoRun(`${t("Removed")} ${picked.length}`, async () => {
      for (const seq of picked) {
        const inSeq = selectedItems.filter((id) =>
          seq.members.some((m) => m.item_id === id));
        if (inSeq.length) await api.removeFromSequence(seq.id, inSeq);
      }
      sel.clear();
      refresh();
    });
  };

  useReportSelection("sequences", list.length === 0 ? null : {
    count: sel.selected.length,
    total: list.length,
    onSelectAll: sel.selectAll,
    onRemove: removeSelected,
    onClear: sel.clear,
    removeLabel: t("Remove"),
    removeTitle: t("Take the selected pictures out of these sequences"),
  });

  if (list.length === 0) return null;

  const single = selectedItems.length === 1 ? selectedItems[0] : null;

  return (
    <div style={{ marginBottom: 18 }}>
      {!hideHeader && (
        <label style={{ ...SECTION_LABEL, letterSpacing: "0.04em" }}>Sequence</label>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
        {list.map((seq) => {
          // Where the selected picture sits — every occurrence, since a
          // repeated page holds several. RANKS in the member list (what the
          // grid badge shows), never the stored `position`. Only for a single
          // selection: several pictures' places in one cell would name
          // nothing.
          const ranks: number[] = [];
          if (single != null) {
            seq.members.forEach((m, i) => {
              if (m.item_id === single) ranks.push(i + 1);
            });
          }
          const picked = sel.has(`q:${seq.id}`);
          return (
            <div
              key={seq.id}
              {...sel.props(`q:${seq.id}`)}
              className="hoverable"
              style={{
                display: "flex", alignItems: "flex-start", gap: 6,
                boxSizing: "border-box", padding: "5px 6px", borderRadius: "var(--r-3)",
                flex: "0 0 auto", cursor: "pointer",
                userSelect: "none", WebkitUserSelect: "none",
                border: `1px solid ${picked ? "var(--accent)" : "var(--border)"}`,
                background: rowBackground(picked, "var(--panel)"),
              }}
            >
              <span style={{ flex: 1, minWidth: 0, display: "flex",
                             flexDirection: "column", gap: 1 }}>
                {/* The COUNT rides behind the name — it is a fact about the
                    sequence, where the subtitle is about this picture's
                    places in it. The name shrinks first; the count never. */}
                <span style={{ display: "flex", alignItems: "baseline",
                               gap: 5, minWidth: 0 }}>
                  <span style={{
                    fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text-bright)",
                    overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap", minWidth: 0,
                  }}>{seq.name}</span>
                  <span style={{
                    fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                    color: "var(--muted-2)", flex: "0 0 auto",
                  }}>({seq.total})</span>
                </span>
                {/* The picture's places in the reading order. They WRAP —
                    eighteen of them are eighteen, and inline they would take
                    the name's place. */}
                {ranks.length > 0 && (
                  <span style={{
                    fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                    color: "var(--muted-2)", overflowWrap: "anywhere",
                  }}>
                    {ranks.join(", ")}
                  </span>
                )}
              </span>
              <span
                className="hoverable"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); showSequence(seq.id); }}
                title={t("Open this sequence in the grid")}
                style={{ display: "flex", alignItems: "center", padding: 2, borderRadius: "var(--r-1)", cursor: "pointer", color: "var(--muted-2)", flex: "0 0 auto" }}
              >
                <Icon name="grid_view" size={15} />
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * The members of a selected *sequence item* (folder-like). Lists the pages in
 * order with a thumbnail; clicking one selects it, and it can be reordered
 * (drag handle) or removed (hover ×) — removing keeps the image in the library.
 */
function SequenceMembersSection({
  sequenceId, onChange, hideHeader,
}: {
  sequenceId: number;
  onChange: () => void;
  // Drop the "Sequence" heading when this is the sole content of the Sequence
  // tab (the tab label already names it; the member count is the tab badge).
  hideHeader?: boolean;
}) {
  const t = useT();
  const qc = useQueryClient();
  const setSelectedItems = useUI((s) => s.setSelectedItems);
  const selectedItems = useUI((s) => s.selectedItems);
  const memberDrag = useRef<number | null>(null);
  const memberHalf = useRef<"before" | "after">("before");
  // Row index a reorder drag is hovering over, for the insertion indicator
  // (mirrors SequenceSection's dropAt).
  const [dropAt, setDropAt] = useState<number | null>(null);
  // Floating thumbnail preview for the hovered member row (mirrors the
  // SequenceSection list — no inline thumbnails).
  const [preview, setPreview] = useState<{ fileId: number; top: number; left: number } | null>(null);
  const { data: seq } = useQuery({
    queryKey: ["sequence", sequenceId],
    queryFn: () => api.sequence(sequenceId),
    placeholderData: (prev) => prev,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["sequence", sequenceId] });
    qc.invalidateQueries({ queryKey: ["items"] });
    qc.invalidateQueries({ queryKey: ["item"] });
    qc.invalidateQueries({ queryKey: ["sequences"] });
    onChange();
  };
  if (!seq) return null;
  const order = seq.members.map((m) => m.item_id);
  // Reorder speaks in MEMBERSHIP rows — a repeated item's copies each have
  // their own row, and an item-id list cannot say which copy moved.
  const rowOrder = seq.members.map((m) => m.id);
  // Persisted one-shot sort by member name (numeric-aware, so "2" < "10").
  const sortByName = async (dir: 1 | -1) => {
    const next = [...seq.members]
      .sort((a, b) => dir * a.name.localeCompare(b.name, undefined,
        { numeric: true, sensitivity: "base" }))
      .map((m) => m.id);
    await api.reorderSequence(seq.id, next);
    refresh();
  };
  return (
    <div style={{ marginBottom: 18 }}>
      {/* No member-count text here — the count lives in the Sequence tab's
          badge (like the Tags tab count). */}
      {!hideHeader && (
        <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
          <label style={{ ...SECTION_LABEL, letterSpacing: "0.04em" }}>Sequence</label>
        </div>
      )}
      <div style={{ background: "var(--panel-3)", border: "1px solid var(--border)", borderRadius: "var(--r-5)", padding: 8 }}>
        {/* Same layout as SequenceSection's member list, but the height is not
            capped — a sequence item's whole contents are shown. */}
        <div
          onMouseLeave={() => setPreview(null)}
          style={{ display: "flex", flexDirection: "column", userSelect: "none", WebkitUserSelect: "none" }}
        >
          {seq.members.map((m, idx) => {
            const isSel = selectedItems.includes(m.item_id);
            const prevSel = idx > 0 && selectedItems.includes(order[idx - 1]);
            const nextSel = idx < order.length - 1 && selectedItems.includes(order[idx + 1]);
            const radius = isSel
              ? `${prevSel ? 0 : 6}px ${prevSel ? 0 : 6}px ${nextSel ? 0 : 6}px ${nextSel ? 0 : 6}px`
              : "6px";
            return (
            <div
              key={m.id}
              className="hoverable"
              onDragOver={(e) => {
                e.preventDefault();
                if (memberDrag.current != null) {
                  setDropAt(idx);
                  memberHalf.current = dropHalf(e);
                }
              }}
              onDragEnd={() => { memberDrag.current = null; setDropAt(null); }}
              onDrop={async (e) => {
                e.stopPropagation();
                const from = memberDrag.current;
                memberDrag.current = null;
                setDropAt(null);
                if (from == null || from === idx) return;
                const next = [...rowOrder];
                const [moved] = next.splice(from, 1);
                // The lower half of a row lands AFTER it — this landed one
                // short whenever the row was dragged downward.
                next.splice(insertionIndex(from, idx, memberHalf.current), 0, moved);
                await api.reorderSequence(seq.id, next);
                refresh();
              }}
              onMouseEnter={(e) => {
                if (m.active_file_id != null) {
                  const r = e.currentTarget.getBoundingClientRect();
                  setPreview({ fileId: m.active_file_id, top: r.top, left: r.left });
                }
              }}
              onClick={() => setSelectedItems([m.item_id])}
              style={{
                display: "flex", alignItems: "center", gap: 8, height: SEQ_ROW,
                boxSizing: "border-box", padding: "0 4px", borderRadius: radius,
                cursor: "pointer", flex: "0 0 auto",
                background: rowBackground(isSel, "transparent"),
                // Insertion line while a reorder drag hovers this row.
                boxShadow: dropAt === idx ? "inset 0 2px 0 var(--accent)" : undefined,
              }}
            >
              <span
                draggable
                onMouseDown={(e) => e.stopPropagation()}
                onDragStart={() => (memberDrag.current = idx)}
                onClick={(e) => e.stopPropagation()}
                title="Drag to reorder"
                style={{ display: "flex", cursor: "grab", color: "var(--muted-3)" }}
              >
                <Icon name="drag_indicator" size={14} />
              </span>
              <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)", width: 20 }}>{m.position}</span>
              <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-2)", color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {m.name}
              </span>
              <span className="row-actions" style={{ flex: "0 0 auto" }}>
                <IconButton icon="close" size={18} reveal="hover" tone="danger"
                  title="Remove from sequence (keeps the image)"
                  onClick={async (e) => {
                    e.stopPropagation();
                    // THIS occurrence — a repeated page's other positions stay.
                    await api.removeSequenceMembers(seq.id, [m.id]);
                    refresh();
                  }} />
              </span>
            </div>
            );
          })}
        </div>
      </div>

      {/* Sorting reorders the whole sequence in one go — an action, like the
          ones in the Item tab, so it is shaped like them: full width, its own
          icon, a chevron for the menu. It used to be a small link-sized
          control tucked into a corner. */}
      <div style={{ marginTop: 10 }}>
        <RowMenu always icon="sort_by_alpha"
          title={t("Reorder every member of this sequence")}
          buttonStyle={{
            width: "100%", height: 32, borderRadius: "var(--r-4)", justifyContent: "flex-start",
            gap: 6, padding: "0 30px 0 12px", position: "relative",
            border: "1px solid var(--border-strong)", background: "var(--panel-2)",
            color: "var(--text-2)", fontSize: "var(--fs-3)", fontWeight: 600,
          }}
          label={<>
            <span>{t("Sort sequence")}</span>
            <Icon name="expand_more" size={16} style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", opacity: 0.7 }} />
          </>}
          actions={[
            { icon: "arrow_downward", label: t("Name ascending"), onClick: () => sortByName(1) },
            { icon: "arrow_upward", label: t("Name descending"), onClick: () => sortByName(-1) },
          ]} />
      </div>

      {/* Floating thumbnail preview for the hovered member (to the left of the
          panel so it doesn't cover the list). */}
      {preview && (
        <img
          className="mc-checker"
          src={api.thumbUrl(preview.fileId)}
          alt=""
          style={{
            position: "fixed", top: preview.top, left: preview.left - 10,
            transform: "translateX(-100%)",
            maxWidth: 280, maxHeight: 280, width: "auto", height: "auto",
            objectFit: "contain", borderRadius: "var(--r-4)", border: "1px solid var(--border-strong)",
            boxShadow: "var(--shadow-3)",
            zIndex: 60, pointerEvents: "none",
          }}
        />
      )}
    </div>
  );
}

/** Human label for how a derived item differs from its original — shown as the
 *  row subtitle in place of the raw relationship kind. */
/** A hover-thumbnail preview anchored to the left of the sidebar, shared by the
 *  modified-versions rows and the Properties "original" link. */
function HoverThumb({
  fileId,
  pos,
  boxes,
}: {
  fileId: number;
  pos: { top: number; left: number };
  // Optional link bounding boxes (fractions of the shown item's frame), drawn as
  // highlighted regions over the thumbnail.
  boxes?: { x: number; y: number; w: number; h: number }[];
}) {
  return (
    <span
      style={{
        position: "fixed", top: pos.top, left: pos.left - 8,
        transform: "translate(-100%, -50%)", zIndex: 60,
        width: 280, background: "var(--surface-float)",
        border: "1px solid var(--menu-border)", borderRadius: "var(--r-4)",
        padding: 6, boxShadow: "var(--shadow-3)",
        pointerEvents: "none",
      }}
    >
      <span className="mc-checker" style={{ position: "relative", display: "block", overflow: "hidden", borderRadius: 4 }}>
        <img
          src={api.thumbUrl(fileId)}
          alt=""
          style={{ width: "100%", borderRadius: 4, display: "block" }}
        />
        {(boxes ?? []).map((b, i) => (
          <span
            key={i}
            style={{
              position: "absolute",
              left: `${b.x * 100}%`, top: `${b.y * 100}%`,
              width: `${b.w * 100}%`, height: `${b.h * 100}%`,
              border: "2px solid var(--accent)",
              background: "var(--accent-dim)", borderRadius: 2,
            }}
          />
        ))}
      </span>
    </span>
  );
}

/** One linked-item row: a thumbnail, the item name with its structural subtitle,
 *  a hover preview, a free-form link-tag editor, and a ⋯ menu to merge the two
 *  items, swap the link direction, or remove the link. */
/**
 * The moments a `frame` link names, in order.
 *
 * A LIST from the first capture on: a still taken once is a list of one, so
 * the row has one shape to read and says the same thing however many moments
 * a frame link names.
 */
export function linkTimes(rel: RelationshipOut): number[] {
  if (rel.kind !== "frame") return [];
  const meta = rel.meta as { timestamps?: number[] };
  const list = Array.isArray(meta.timestamps) ? meta.timestamps : [];
  return list.filter((t) => typeof t === "number").sort((a, b) => a - b);
}

function RelatedRow({
  rel,
  picked,
  selProps,
  fileId,
  onOpen,
  onRemove,
  onSwap,
  onMergeIntoThis,
  onMergeIntoOther,
  tagOptions,
  onAddTag,
  onRemoveTag,
}: {
  rel: RelationshipOut;
  /** The shared row selection — the same gesture the other tabs have. */
  picked?: boolean;
  selProps?: {
    onMouseDown: (e: React.MouseEvent) => void;
    onMouseEnter: () => void;
    onClick: (e: React.MouseEvent) => void;
  };
  fileId: number | null;
  onOpen: () => void;
  onRemove: () => void;
  onSwap: () => void;
  // Merge folds one item into the other and deletes the emptied one. "IntoThis"
  // keeps the item whose sidebar this is; "IntoOther" keeps the linked item.
  onMergeIntoThis: () => void;
  onMergeIntoOther: () => void;
  tagOptions: LinkTagRow[];
  onAddTag: (name: string) => void;
  onRemoveTag: (name: string) => void;
}) {
  const tr = useT();
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  // Link boxes are stored in the ``to_item`` frame, so they only line up with the
  // shown thumbnail (the *other* item) on an outgoing row — where other = to_item.
  const linkBoxes = rel.outgoing ? rel.boxes ?? [] : [];
  const openQuickLook = useUI((s) => s.openQuickLook);
  return (
    <div
      className="hoverable"
      // Click SELECTS and double-click opens — the grid's rule, and now the
      // other sidebar tabs' too. Click-to-open was the odd one out here, and
      // it left no gesture for picking several links at once.
      {...(selProps ?? {})}
      onDoubleClick={onOpen}
      onMouseEnter={(e) => {
        selProps?.onMouseEnter();
        if (fileId == null) return;
        const r = e.currentTarget.getBoundingClientRect();
        setPos({ top: r.top + r.height / 2, left: r.left });
      }}
      onMouseLeave={() => setPos(null)}
      title={tr("A linked item — double-click to open it")}
      style={{
        display: "flex", alignItems: "flex-start", gap: 10,
        padding: "6px 8px", borderRadius: "var(--r-5)", cursor: "pointer",
        background: rowBackground(picked, "var(--panel-3)"),
        border: `1px solid ${picked ? "var(--accent)" : "var(--border)"}`,
      }}
    >
      {fileId != null ? (
        <img
          className="mc-checker"
          src={api.thumbUrl(fileId)}
          alt=""
          style={{ width: 32, height: 32, borderRadius: "var(--r-2)", objectFit: "cover", flex: "0 0 auto", border: "1px solid var(--border)" }}
        />
      ) : (
        <Icon name="subdirectory_arrow_right" size={16} color="var(--muted-2)" style={{ marginTop: 3, flex: "0 0 auto" }} />
      )}
      {/* Name + link tags stacked tightly, like a title and its subtitle. */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, minHeight: 20 }}>
          <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text-bright)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {rel.other_name}
          </span>
          {/* A link with bounding boxes (e.g. a detected panel's region) shows a
              crop icon after its name; the boxes are drawn on the hover thumbnail. */}
          {linkBoxes.length > 0 && (
            <span
              title={tr("Has a bounding box — hover the row to preview")}
              style={{ flex: "0 0 auto", display: "flex", alignItems: "center", color: "var(--accent)", cursor: "help" }}
            >
              <Icon name="crop_free" size={13} />
            </span>
          )}
          {/* Go to the linked item. The row has always opened it on a DOUBLE
              click, which is a gesture nothing on the row says it has — and
              the one thing you reliably want from a link is to look at what is
              on the other end. Spelled out beside the ⋯, so the menu keeps the
              things that CHANGE something and this stays what it is: a way
              across. */}
          {/* LOOK at the other end without leaving this item. The row's
              hover thumbnail is 200 px and gone the moment the pointer moves;
              this is the whole picture, and it carries what the LINK knows
              that the item does not — a film opens at the moment the still
              was taken at, and a crop's region is drawn on its original. */}
          <IconButton icon="visibility" size={22} reveal="hover"
            title={tr("Preview this item")}
            onClick={(e) => {
              e.stopPropagation();
              setPos(null);
              openQuickLook([rel.other_item_id], {
                // The moments belong to the FILM, so they are worth seeking to
                // only when the film is what is being opened.
                at: rel.outgoing ? linkTimes(rel)[0] ?? null : null,
                boxes: linkBoxes.length ? linkBoxes : null,
              });
            }} style={{ flex: "0 0 auto" }} />
          <IconButton icon="arrow_forward" size={22} reveal="hover"
            title={tr("Go to this item")}
            onClick={(e) => { e.stopPropagation(); onOpen(); }} style={{ flex: "0 0 auto" }} />
          {/* Actions menu: merge / swap direction / remove. */}
          <RowMenu always title={tr("More actions")}
            buttonStyle={{ width: 22, height: 22, borderRadius: "var(--r-2)" }}
            actions={[
              { icon: "merge", label: tr("Merge into this item"),
                hint: tr("Combine both into this item — the linked item is removed"),
                onClick: onMergeIntoThis },
              { icon: "merge", label: tr("Merge into linked item"),
                hint: tr("Combine both into the linked item — this item is removed"),
                onClick: onMergeIntoOther },
              { icon: "swap_vert", label: tr("Swap link direction"),
                hint: tr("Flip which item is the original and which the derived one"),
                onClick: onSwap },
              { icon: "link_off", label: tr("Remove link"), danger: true, onClick: onRemove },
            ]} />
      </div>
      {/* WHEN in the film this frame is — a still's whole provenance, and the
          one thing about a `frame` link that is not already in its name. */}
      {linkTimes(rel).length > 0 && (
        <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)", fontFamily: "var(--mono)" }}>
          {(() => {
            const ts = linkTimes(rel);
            const shown = ts.slice(0, 4).map(fmtDuration).join(", ");
            return `${rel.outgoing ? "In video" : "Frame"} @ ${shown}${ts.length > 4 ? " …" : ""}`;
          })()}
        </span>
      )}
      {/* Meta tags — free-form labels on the link (not item tags). */}
      <MetaTagAdder
        tags={rel.tags}
        tagOptions={tagOptions}
        onAdd={onAddTag}
        onRemove={onRemoveTag}
      />
      </div>
      {pos && fileId != null && <HoverThumb fileId={fileId} pos={pos} boxes={linkBoxes} />}
    </div>
  );
}

/** AI actions over the selection: background removal, captioning, tagging.
 *  Each is a button that opens a menu of models; picking one queues a background
 *  job per selected item (tracked in the left-sidebar job list). */
// Sentinel `openKind` for the combined (single-button) menu that lists several
// tasks together, grouped by task, under one trigger button.
const COMBINED_KIND = "__combined__" as JobKind;

/** Past this many items, a whole-view model run asks before it queues. Low
 *  enough that "everything in a small group" is still one click, high enough
 *  that the question is never idle. */
const VIEW_RUN_CONFIRM = 25;

/** The way into the annotator, from the list you are standing in.
 *
 *  Every list in this panel has one — subjects, places, events, captions,
 *  text, and the tags list that had it first. Annotating is the same work
 *  seen with the picture in front of you, and which LIST you pressed it in
 *  is which list you meant to go on working in: the button carries that tab
 *  along (`openAnnotatorAt`), so pressing it in Captions arrives in
 *  Captions rather than on Tags with the trip left to finish by hand.
 */
export function AnnotateButton({ itemId, tab, title }: {
  itemId: number;
  /** A `SIDE_TABS` id in the annotator — the tab this list corresponds to. */
  tab: string;
  title?: string;
}) {
  const t = useT();
  const openAnnotatorAt = useUI((s) => s.openAnnotatorAt);
  return (
    <Button variant="soft" size="sm" block justify="start"
   onClick={() => openAnnotatorAt(itemId, tab)}
   title={title ?? t("Open the annotator on this list")} style={{ marginBottom: 10 }}>
      <Icon name="frame_inspect" size={16} />
      {t("Annotate")}
    </Button>
  );
}

export function AiActionButtons({
  itemIds, scope, onEnqueued, kinds, hideModelIds, combined, doneModels,
  extraModels,
}: {
  itemIds: number[];
  /** THE WHOLE VIEW instead of a list of ids, for the sidebar with nothing
   *  selected. A view can be the entire library, so what travels is the
   *  grid's own search body and the server resolves it — `itemIds` is then
   *  only what the LABELS count (the first page's worth), never what is
   *  enqueued. `total` is how many the view holds, `null` while it is still
   *  being counted. */
  scope?: { body: ItemSearchBody; total: number | null };
  onEnqueued: () => void;
  /** Rows to append to a kind's own model list, keyed by kind — synthesized
   *  by the caller from something the registry cannot know (today: one
   *  "detect and remove" entry per OCR engine that has not read this file). */
  extraModels?: Partial<Record<JobKind, ModelInfo[]>>;
  /** Model ids already run over these items — ticked in the menu, so a second
   *  run is a choice rather than a guess. Face detection is the one that has
   *  a record of it (`ItemFaceRun`); everything else passes nothing. */
  doneModels?: string[];
  // Which action buttons to render. Defaults to all three; used to split the
  // buttons across the sidebar (background removal by Edit, captioning above the
  // Captions section, tagging above the Tags section).
  kinds?: JobKind[];
  // Model ids to hide from the menus (e.g. the box-driven watermark model unless
  // the item has a "watermark" tag with boxes).
  hideModelIds?: string[];
  // When set, render a *single* button (with this label + icon) whose menu
  // lists all `kinds`' tasks together, each as its own section — instead of one
  // button per task.
  combined?: { label: string; icon: string };
}) {
  const qc = useQueryClient();
  const t = useT();
  const tn = useTn();
  const setOverlay = useUI((s) => s.setOverlay);
  const setSettingsPage = useUI((s) => s.setSettingsPage);
  const setSettingsFocusModel = useUI((s) => s.setSettingsFocusModel);
  const setSettingsFocusWarning = useUI((s) => s.setSettingsFocusWarning);
  // Open Settings on the Models page (these chips are about model downloads).
  const openModelSettings = () => { setSettingsPage("actions"); setOverlay("settings"); };
  const { data: models } = useQuery({ queryKey: ["ml-models"], queryFn: api.mlModels });
  // Actions are served by the backend (no hardcoded list). Look tasks up by kind.
  const tasksByKind = useMemo(
    () => Object.fromEntries((models?.tasks ?? []).map((tk) => [tk.kind, tk])),
    [models]
  );
  // Per-model download/cache status, polled while any download is in progress.
  const { data: cache } = useQuery({
    queryKey: ["model-cache"],
    queryFn: api.modelCache,
    refetchInterval: (q) => {
      const ms = (q.state.data as { models: { downloading: boolean }[] } | undefined)?.models ?? [];
      return ms.some((m) => m.downloading) ? 1500 : false;
    },
  });
  const cacheByKey = Object.fromEntries((cache?.models ?? []).map((m) => [m.key, m]));
  const tokenAvailable = cache?.token_available ?? false;
  // The launch environment forces Hugging Face offline (e.g. HF_HUB_OFFLINE) —
  // downloads must be enabled in Settings first, same as the Settings cards gate.
  const envOffline = !!cache?.env_offline;
  // A model can be run only when its deps are present AND every weight family it
  // needs is downloaded (a model may require several — e.g. a detector + an
  // inpainter). A source with a cache entry that isn't cached blocks readiness.
  const requiredCaches = (m: ModelInfo) =>
    (m.family_keys ?? []).map((k) => cacheByKey[k]).filter(Boolean);
  const modelReady = (m: ModelInfo) => {
    if (!m.available) return false;
    return requiredCaches(m).every((ci) => ci.cached);
  };
  const [openKind, setOpenKind] = useState<JobKind | null>(null);
  // The panels task's "into a sequence" switch — the one extra output any
  // action still offers (every other result lands on the item it ran on).
  // The stored preference is read THROUGH (`readPanelsSequence`, shared with
  // both context menus); the counter only makes the switch redraw.
  const [, bumpToggle] = useState(0);
  const togglePanelsSequence = () => {
    writePanelsSequence(!readPanelsSequence());
    bumpToggle((n) => n + 1);
  };
  // The open menu is portalled to the body (so the sidebar's overflow can't clip
  // it); `anchor` is the trigger button's viewport rect used to place it.
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const [busy, setBusy] = useState(false);
  // The model whose install instructions are shown in the help overlay.
  const [help, setHelp] = useState<ModelInfo | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const closeMenu = () => { setOpenKind(null); setAnchor(null); };
  // Anchored to a captured rect, so a scroll of the page behind it would
  // misalign it — close then (a scroll INSIDE the menu must not).
  useMenuDismiss(!!openKind, closeMenu, { within: [ref, menuRef], onScroll: true, onResize: true });
  // A reference-guided model (needs_reference) first opens the reference
  // picker; the pending {kind, model} waits here until the user confirms.
  const [refPick, setRefPick] = useState<{ kind: JobKind; model: string } | null>(null);
  const enqueue = async (kind: JobKind, model: string, reference = "") => {
    setBusy(true);
    try {
      const intoSequence = !!tasksByKind[kind]?.sequence_option
        && readPanelsSequence();
      const [realModel, detectWith] = model.split(DETECT_WITH);
      if (scope) {
        // A WHOLE-VIEW RUN ASKS FIRST PAST A HANDFUL. Some kinds become one
        // job with a progress bar (tags, captions, faces, text); the ones
        // that produce a FILE per item become one job EACH, so "upscale
        // everything" over an unfiltered library is a million of them. The
        // question is the same either way — how many items — so the rule is
        // one threshold rather than a second table of which kinds batch.
        if (n > VIEW_RUN_CONFIRM && !(await confirm({
              title: tn({ one: "Run this over 1 item?",
                          other: "Run this over {n} items?" }, n),
              answer: { label: t("Run") } }))) {
          return;
        }
        // `skip_done` is the group menu's rule, and it matters far more here:
        // over a whole library, re-running what a model has already seen is
        // the difference between minutes and hours. Only the kinds that
        // RECORD a per-item run can answer it.
        const skip = SKIP_DONE_KINDS.has(kind);
        await api.enqueueJobsView(kind, realModel, scope.body, intoSequence,
                                  reference, skip, detectWith ?? "");
      } else {
        // Over an explicit SELECTION the ask is taken literally — "I picked
        // these" — with one exception: a caption this model has already
        // written is not worth writing again, because the result would be a
        // second, nearly identical description sitting beside the first with
        // nothing to tell them apart. `SKIP_DONE_ALWAYS` says why that is
        // caption's alone.
        await api.enqueueJobs(kind, realModel, itemIds, intoSequence, reference,
                              SKIP_DONE_ALWAYS.has(kind), detectWith ?? "");
      }
      // A JOB EXISTS NOW, and the one place that can be sure of it is here.
      // `JobList` polls only while it can SEE something active, and its poll
      // is what notices the finish and sweeps the content queries — so a
      // caller that forgot this invalidation queued a job the app never
      // learned about, and its result appeared only on the next reload. The
      // annotator's Detect text was exactly that; every other call site had
      // remembered, which is the drift this removes.
      qc.invalidateQueries({ queryKey: ["ml-jobs"] });
      onEnqueued();
    } finally {
      setBusy(false);
    }
  };
  const run = async (kind: JobKind, model: string) => {
    setOpenKind(null);
    const info = (tasksByKind[kind]?.models ?? []).find((m) => m.id === model);
    if (info?.needs_reference) {
      setRefPick({ kind, model });
      return;
    }
    await enqueue(kind, model);
  };
  // The action buttons (label + icon) come from the backend task list; a call
  // site may restrict to certain kinds via `kinds`.
  const hideSet = new Set(hideModelIds ?? []);
  // "Hide actions that need setting up" (a per-user setting, default off):
  // drop unready models here, at the one filter everything downstream reads —
  // so a task whose models are all unready loses its button and its section
  // too, rather than opening an empty menu.
  const { data: prefs } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const hideUnready = prefs?.hide_unready_actions ?? false;
  const visibleModels = (ms: ModelInfo[]) =>
    ms.filter((m) => !hideSet.has(m.id) && (!hideUnready || modelReady(m)));
  const ACTIONS = (models?.tasks ?? [])
    .filter((tk) => !kinds || kinds.includes(tk.kind))
    .map((tk) => {
      const extra = extraModels?.[tk.kind as JobKind];
      return extra?.length ? { ...tk, models: [...tk.models, ...extra] } : tk;
    });
  // What the buttons COUNT. Over a view that is the view's total (still
  // being counted reads as 1, so a label never says "0 items" while the
  // answer is on its way).
  const n = scope ? (scope.total ?? 1) : itemIds.length;
  // Group a kind's models by family, preserving order, so the menu shows one
  // header per family (JoyCaption, Florence-2, …) with its variants beneath —
  // instead of repeating the family name on every row.
  const grouped = (list: ModelInfo[]) => {
    const out: { family: string; models: ModelInfo[] }[] = [];
    for (const m of list) {
      const fam = m.family || m.name;
      const last = out[out.length - 1];
      if (last && last.family === fam) last.models.push(m);
      else out.push({ family: fam, models: [m] });
    }
    return out;
  };
  const chip = (opts: { label: string; icon: string; title: string; onClick?: (e: React.MouseEvent) => void; spin?: boolean; dim?: boolean }) => (
    <span
      title={opts.title}
      onClick={opts.onClick}
      style={{ flex: "0 0 auto", display: "flex", alignItems: "center", gap: 3, height: 22, padding: "0 8px", borderRadius: "var(--r-2)", cursor: opts.onClick ? "pointer" : "default", color: "var(--accent)", background: "var(--accent-dim)", fontSize: "var(--fs-1)", fontWeight: 600, opacity: opts.dim ? 0.6 : 1 }}
    >
      <Icon name={opts.icon} size={14} spin={opts.spin} />
      {opts.label}
    </span>
  );
  const setupBtn = (m: ModelInfo) =>
    chip({ label: "Set up", icon: "download", title: "Set up this model",
           onClick: (e) => { e.stopPropagation(); setOpenKind(null); setHelp(m); } });
  const download = async (key: string) => {
    try { await api.downloadModel(key); qc.invalidateQueries({ queryKey: ["model-cache"] }); }
    catch { /* surfaced in Settings */ }
  };
  // The set-up / download / status chip for a model that isn't runnable, or
  // null when it's ready. A model may need several weight families; the chip
  // stays "Download" until every one is cached and downloads all that are missing.
  const actionChip = (m: ModelInfo) => {
    if (!m.available) return setupBtn(m);  // dependencies missing
    const missing = requiredCaches(m).filter((ci) => !ci.cached);
    if (missing.length === 0) return null; // all downloaded → runnable
    const dl = missing.find((ci) => ci.downloading);
    if (dl)
      return chip({ label: dl.progress >= 0 ? `Downloading… ${dl.progress}%` : "Downloading…", icon: "progress_activity", title: "Download in progress", spin: true });
    if (missing.some((ci) => ci.gated) && !tokenAvailable)
      return chip({ label: "Set token", icon: "key_off", title: "Set a Hugging Face token in Settings to download this gated model",
                    onClick: (e) => { e.stopPropagation(); setOpenKind(null); openModelSettings(); } });
    // Environment forces offline: route to Settings (which has the "Enable
    // downloads" button) instead of starting a download, matching the Settings
    // cards' gating — don't silently start a download the env means to block.
    if (envOffline)
      return chip({ label: "Enable downloads", icon: "cloud_off", title: "Your environment forces Hugging Face offline — enable downloads in Settings first",
                    onClick: (e) => { e.stopPropagation(); setOpenKind(null); setSettingsFocusModel(missing[0].key); setSettingsFocusWarning(true); openModelSettings(); } });
    // Open Settings (where progress shows), scroll to the first missing model,
    // and kick off downloads for ALL still-missing weight families.
    return chip({ label: "Download", icon: "download", title: "Download this model's weights",
                  onClick: (e) => { e.stopPropagation(); setOpenKind(null); setSettingsFocusModel(missing[0].key); setSettingsFocusWarning(false); openModelSettings(); missing.forEach((ci) => download(ci.key)); } });
  };
  // Placement for the portalled menu: prefer below the trigger, flip above when
  // below is cramped and above is roomier, and cap the height to the available
  // space (with internal scrolling) so it never runs off-screen.
  const menuPlacement = (rect: DOMRect): React.CSSProperties => {
    const GAP = 4, MARGIN = 8;
    const vh = window.innerHeight;
    const spaceBelow = vh - rect.bottom - MARGIN;
    const spaceAbove = rect.top - MARGIN;
    const below = spaceBelow >= 240 || spaceBelow >= spaceAbove;
    const maxHeight = Math.max(140, (below ? spaceBelow : spaceAbove) - GAP);
    return {
      position: "fixed", left: rect.left, width: rect.width, maxHeight, overflowY: "auto",
      // Keep the menu's own scrolling from chaining to the page behind it —
      // a page scroll would misalign (and thus close) the anchored menu.
      overscrollBehavior: "contain",
      ...(below ? { top: rect.bottom + GAP } : { bottom: vh - rect.top + GAP }),
      zIndex: LAYER.popover,
      background: "var(--surface-float)", border: "1px solid var(--menu-border)",
      borderRadius: "var(--r-5)", padding: 4, boxShadow: "var(--shadow-3)",
    };
  };
  // From ACTIONS, not `tasksByKind` — the latter is the raw registry answer
  // and would drop the caller's extra rows in the single-kind menu while the
  // combined one showed them.
  const openList = openKind && openKind !== COMBINED_KIND
    ? visibleModels(ACTIONS.find((a) => a.kind === openKind)?.models ?? []) : [];

  // A model that has already been run over these items. Shown, not disabled:
  // re-running a detector over the same picture is the normal next step in a
  // part-drawn, part-photographed library and `reconcile` makes it cost
  // nothing — so this says "you have done this" and leaves the choice alone.
  const doneSet = new Set(doneModels ?? []);
  const doneTick = (
    <Icon name="check" size={14} color="var(--muted-2)" />
  );

  // A JOB ALREADY IN FLIGHT IS NOT A SECOND OFFER. Queueing the same model
  // over the same items again does the same work twice and then reconciles a
  // reading (or a detection) with itself — so the row says what is happening
  // instead, and does not run. Polled only while something is active; the
  // enqueue invalidates this query, which is what starts the polling.
  const { data: liveJobs } = useQuery({
    queryKey: ["ml-jobs"], queryFn: api.mlJobs,
    refetchInterval: (q) => {
      const js = (q.state.data as { jobs: JobOut[] } | undefined)?.jobs ?? [];
      return js.some((j) => j.status === "queued" || j.status === "running")
        ? 1200 : false;
    },
    // The menu is often open in a window that is not the focused one (the
    // annotator over the library), and a progress readout that stops
    // updating there is worse than none.
    refetchIntervalInBackground: true,
  });
  const wanted = new Set(itemIds);
  /** The queued/running job for this model over one of these items. A BATCH
   *  job (faces, ocr, tags over a selection) is ONE row naming its first
   *  item, and the wire does not carry the rest — deliberately, since a run
   *  over a group can hold thousands of ids. So a menu opened on a LATER
   *  item of a batch does not recognise it, and offers the run again; the
   *  server's own `skip_done` is what keeps that from costing anything. */
  const jobFor = (kind: JobKind, model: string): JobOut | null =>
    (liveJobs?.jobs ?? []).find((j) => j.kind === kind && j.model === model
      && (j.status === "queued" || j.status === "running")
      && j.item_id != null && wanted.has(j.item_id)) ?? null;
  const jobChip = (job: JobOut) => (
    <span style={{ flex: "0 0 auto", display: "flex", alignItems: "center",
                   gap: 3, fontSize: "var(--fs-1)", color: "var(--accent)" }}>
      <Icon name="progress_activity" size={14}
        spin />
      {job.status === "running"
        ? (job.progress > 0 ? `${job.progress}%` : t("Running"))
        : t("Queued")}
    </span>
  );

  // The grouped model rows for one task `kind` (families → variants), each row
  // running that kind. Shared by the single-kind menu and the combined menu.
  const modelGroups = (list: ModelInfo[], kind: JobKind) =>
    grouped(list).map(({ family, models: fam }) => {
      // "Ready" = deps present AND weights downloaded. A not-ready family can't
      // be run; it shows a set-up / download chip.
      const famReady = fam.some(modelReady);
      const famChip = actionChip(fam[0]);
      // A single-variant family renders as one clickable row (the family name is
      // the label); a multi-variant family gets a header (with the
      // set-up/download chip) + indented variant rows.
      if (fam.length === 1) {
        const m = fam[0];
        const job = jobFor(kind, m.id);
        const ready = modelReady(m) && !job;
        return (
          <div
            key={m.id}
            className={ready ? "hoverable" : undefined}
            onClick={() => ready && run(kind, m.id)}
            title={job ? t("This run is already going") : m.note}
            style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 9px", borderRadius: "var(--r-2)", cursor: ready ? "pointer" : "default" }}
          >
            <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 1, opacity: ready ? 1 : 0.55 }}>
              <span style={{ fontSize: "var(--fs-3)", color: "var(--text-2)", fontWeight: 500 }}>
                {family}{!m.available && " · unavailable"}
              </span>
              {m.note && <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>{m.note}</span>}
            </span>
            {job ? jobChip(job) : doneSet.has(m.id) && doneTick}
            {actionChip(m)}
          </div>
        );
      }
      return (
        <div key={family}>
          {/* Family header — with the set-up/download chip when the whole family
              isn't ready to run. */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 9px 3px" }}>
            <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-1)", fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: famReady ? "var(--muted)" : "var(--muted-2)" }}>
              {family}{!fam.some((m) => m.available) && " · unavailable"}
            </span>
            {!famReady && famChip}
          </div>
          {fam.map((m) => {
            const job = jobFor(kind, m.id);
            const ready = modelReady(m) && !job;
            return (
              <div
                key={m.id}
                className={ready ? "hoverable" : undefined}
                onClick={() => ready && run(kind, m.id)}
                title={job ? t("This run is already going") : m.note}
                style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 9px 6px 18px", borderRadius: "var(--r-2)", cursor: ready ? "pointer" : "default", opacity: ready ? 1 : 0.55 }}
              >
                <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
                  <span style={{ fontSize: "var(--fs-3)", color: "var(--text-2)", fontWeight: 500 }}>{m.variant || m.name}</span>
                  {m.note && <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>{m.note}</span>}
                </span>
                {job ? jobChip(job) : doneSet.has(m.id) && doneTick}
                {/* Per-variant chip only when deps are missing for this variant
                    while the family header shows none. */}
                {!m.available && famReady && setupBtn(m)}
              </div>
            );
          })}
        </div>
      );
    });

  // In combined mode a single button fronts every task; otherwise one per task.
  const combinedTotal = combined
    ? ACTIONS.reduce((s, a) => s + visibleModels(a.models).length, 0) : 0;
  const buttons = combined
    ? [{ kind: COMBINED_KIND, label: combined.label, icon: combined.icon, total: combinedTotal }]
    : ACTIONS.map((a) => ({ kind: a.kind, label: a.label, icon: a.icon, total: visibleModels(a.models).length }));

  // Sections of the combined menu. Canny + line art are folded into one
  // "Estimate Edges" heading (each model row still runs its own task kind);
  // every other task keeps its own section. Empty tasks are dropped.
  const EDGE_KINDS: JobKind[] = ["canny", "lineart"];
  const combinedSections: {
    key: string; label: string; icon: string;
    parts: { kind: JobKind; models: ModelInfo[] }[];
  }[] = [];
  for (const a of ACTIONS) {
    const list = visibleModels(a.models);
    if (list.length === 0) continue;
    if (EDGE_KINDS.includes(a.kind as JobKind)) {
      let edges = combinedSections.find((s) => s.key === "edges");
      if (!edges) {
        edges = { key: "edges", label: "Estimate Edges", icon: a.icon, parts: [] };
        combinedSections.push(edges);
      }
      edges.parts.push({ kind: a.kind as JobKind, models: list });
    } else {
      combinedSections.push({
        key: a.kind, label: a.label, icon: a.icon,
        parts: [{ kind: a.kind as JobKind, models: list }],
      });
    }
  }

  return (
    <div ref={ref} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {buttons.map((a) => {
        const open = openKind === a.kind;
        // With the hide-unready setting on, an action with nothing runnable
        // DISAPPEARS rather than sitting disabled — that is the setting's
        // whole promise. Without it, disabled stays: the chip inside the
        // menu is how a fresh install discovers what it could set up.
        if (hideUnready && a.total === 0) return null;
        return (
          <button
            key={a.kind}
            onClick={(e) => {
              if (open) closeMenu();
              else { setOpenKind(a.kind); setAnchor(e.currentTarget.getBoundingClientRect()); }
            }}
            disabled={busy || a.total === 0}
            title={tn({ one: "Choose a model and run on 1 item",
                        other: "Choose a model and run on {n} items" }, n)}
            style={{
              position: "relative",
              width: "100%", height: 32, borderRadius: "var(--r-4)", display: "flex", alignItems: "center", justifyContent: "flex-start", gap: 6,
              padding: "0 30px 0 12px", border: `1px solid ${open ? "var(--accent)" : "var(--border-strong)"}`,
              background: open ? "var(--accent-dim)" : "var(--panel-2)",
              color: open ? "var(--accent)" : "var(--text-2)", cursor: "pointer", fontSize: "var(--fs-3)", fontWeight: 600,
            }}
          >
            <Icon name={a.icon} size={16} />
            <span>{t(a.label)}{n > 1 ? ` (${n})` : ""}</span>
            {/* Dropdown affordance pinned right; the icon+title are left-aligned. */}
            <Icon name="expand_more" size={16} style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", opacity: 0.7 }} />
          </button>
        );
      })}
      {openKind && anchor && createPortal(
        <div ref={menuRef} style={menuPlacement(anchor)}>
          {/* The panels task's extra output, pinned at the top of its menu:
              gather the panels it cuts out into a sequence of their own. The
              only such switch left — an action's picture lands on the item it
              ran on, with nothing to choose — so the combined menu (Estimate
              Edges) never shows one. */}
          {(() => {
            const toggleTask = openKind && openKind !== COMBINED_KIND
              ? tasksByKind[openKind] : undefined;
            if (!toggleTask?.sequence_option) return null;
            const label = "Place panels in a sequence";
            return (
              <>
                <div
                  onClick={(e) => { e.stopPropagation(); togglePanelsSequence(); }}
                  className="hoverable"
                  title="Group the detected panels into a new sequence (one per page) instead of loose linked items"
                  style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 9px", borderRadius: "var(--r-2)", cursor: "pointer" }}
                >
                  <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)", color: "var(--text-2)" }}>{t(label)}</span>
                  <Switch checked={readPanelsSequence()} size="sm" title={t(label)} animate />
                </div>
                <div style={{ height: 1, background: "var(--border)", margin: "4px 2px" }} />
              </>
            );
          })()}
          {/* Colorize extra: snapshot the selected item into the small rolling
              reference store, so it can be picked as the color reference when
              colorizing other items. Single selection only. */}
          {openKind === "colorize" && itemIds.length === 1 && (
            <>
              <div
                className="hoverable"
                title="Remember this item's image as a color reference — it appears in the reference picker when colorizing other items"
                onClick={async (e) => {
                  e.stopPropagation();
                  closeMenu();
                  await api.mlRefFromItem(itemIds[0]);
                  qc.invalidateQueries({ queryKey: ["ml-refs"] });
                }}
                style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 9px", borderRadius: "var(--r-2)", cursor: "pointer" }}
              >
                <Icon name="colorize" size={15} color="var(--muted-2)" />
                <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
                  {t("Add as color reference")}
                </span>
              </div>
              <div style={{ height: 1, background: "var(--border)", margin: "4px 2px" }} />
            </>
          )}
          {openKind === COMBINED_KIND
            ? combinedSections.map((sec, i) => (
                <div key={sec.key}>
                  {i > 0 && <div style={{ height: 1, background: "var(--border)", margin: "4px 2px" }} />}
                  {/* Task section header, so several tasks read clearly in one
                      menu (Estimate depth / pose / Estimate Edges). */}
                  <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 9px 3px" }}>
                    <Icon name={sec.icon} size={14} color="var(--muted-2)" />
                    <SectionHeading sm>
                      {t(sec.label)}
                    </SectionHeading>
                  </div>
                  {sec.parts.map((p) => (
                    <div key={p.kind}>{modelGroups(p.models, p.kind)}</div>
                  ))}
                </div>
              ))
            : modelGroups(openList, openKind as JobKind)}
        </div>,
        document.body
      )}
      {help && <ModelHelpOverlay model={help} onClose={() => setHelp(null)} />}
      {refPick && createPortal(
        <RefPickerOverlay
          onClose={() => setRefPick(null)}
          onConfirm={async (refId) => {
            const pick = refPick;
            setRefPick(null);
            await enqueue(pick.kind, pick.model, refId);
          }}
        />,
        document.body
      )}
    </div>
  );
}

// What the preview is worth when nothing else says otherwise, and what the
// chevron expands to when there is no bigger size to go back to.
/** How the item's name is set, wherever it is drawn — under the preview, or
 *  beside it while the preview is collapsed. */
const NAME_ROW: React.CSSProperties = {
  display: "flex", alignItems: "flex-start", gap: 8,
  color: "var(--text-bright)", fontWeight: 600, fontSize: "var(--fs-3)",
};

const PREVIEW_DEFAULT = 240;
// A drag that ends this close to the floor IS a collapse: nobody aims for
// 83 px, and at that size the chevron has to offer the way back rather than
// another way down.
const PREVIEW_SNAP = 6;
// Tall enough that the two corner buttons cannot meet: 6 px of inset and a
// 30 px button at the top and the same at the bottom is 72, and at 64 the
// collapse chevron sat on top of the Quick Look button.
const PREVIEW_MIN = 80;
const PREVIEW_MAX = 640;
// The collapsed thumbnail's HEIGHT — the width follows the picture. A little
// under the floor above, because nothing is laid over it here: the row beside
// it holds the buttons.
const PREVIEW_THUMB = 64;

/**
 * THE SIDEBAR'S HEADER: what is selected, as a picture and a name.
 *
 * Full size it is the active file's preview with hover-overlay rotate
 * buttons (the rotation is non-destructive — stored as metadata, the
 * thumbnail baked and cache-busted via the rotation value) and the name
 * under it. COLLAPSED it is one row: a 64 px tile, the name beside it, the
 * chevron at the end.
 *
 * IT IS RENDERED FOR EVERY SELECTION, picture or not — a sequence, a
 * multi-selection, an item whose detail has not arrived yet — because the
 * alternative is a header that appears and disappears as the selection
 * moves. That was a visible flash: switching pictures in the grid took the
 * whole row out for the ~30 ms the next item's detail was loading and
 * everything below it jumped up and back. The tile is a fixed SQUARE for
 * the same reason: a tile that hugged its picture changed the row's width
 * with every selection, and the name re-wrapped each time.
 */
function RotatablePreview({
  itemId,
  fileId,
  rotation,
  token,
  readOnly,
  onRotated,
  name,
  glyph,
}: {
  /** null for a multi-selection: there is no one item to rotate or open. */
  itemId: number | null;
  /** null when there is no picture — a sequence, a file-less item, or a
   *  detail still loading. */
  fileId: number | null;
  rotation: number;
  /** The item's `thumb_token` — what makes the URL change when the thumbnail
   *  does. Without it, choosing a video's thumbnail left this preview showing
   *  the old frame: an `<img>` already in the DOM with an unchanged `src` does
   *  not re-request at all, however the response is cached. */
  token?: string;
  readOnly?: boolean;
  onRotated: () => void;
  /** The item's name. Drawn UNDER the picture at full size and BESIDE it
   *  while collapsed, which is why it is handed in rather than drawn by the
   *  panel: the two layouts are one decision and it is made here. */
  name?: React.ReactNode;
  /** What the collapsed tile shows when there is no picture: the kind's own
   *  glyph. Nothing at all while a detail is loading — an empty tile says
   *  "not yet", where a glyph would say what this is and then be replaced. */
  glyph?: string;
}) {
  const [hover, setHover] = useState(false);
  // Displayed aspect ratio (w/h) of the loaded thumbnail, so the transparency
  // checkerboard can be sized to the rendered image box (not the letterbox).
  const [ratio, setRatio] = useState<number | null>(null);
  // How much room the preview gets. It sits above the scroll area now, so this
  // is a trade against the sections below it — remembered, since which side of
  // that trade you want is a preference, not a per-item decision. The bottom
  // edge drags to any height; the chevron collapses to the smallest and back to
  // the height it collapsed away from — and a drag onto the floor is a collapse
  // like any other, so the chevron turns round with it.
  const [height, setHeight] = useState(() => APP_PREFS.sidebarPreviewH.read());
  const [small, setSmall] = useState(() => APP_PREFS.sidebarPreviewSmall.read());
  // The size the chevron goes back to: the height a collapse (by click or by
  // drag) left behind. Kept apart from `height`, which a drag to the floor
  // overwrites with the floor.
  const [back, setBack] = useState(() => APP_PREFS.sidebarPreviewBack.read());
  useEffect(() => {
    APP_PREFS.sidebarPreviewH.write(height);
    APP_PREFS.sidebarPreviewSmall.write(small);
    APP_PREFS.sidebarPreviewBack.write(back);
  }, [height, small, back]);
  // Dragged onto the floor counts as collapsed, so the chevron offers the way
  // back up instead of pointing further down at a preview that cannot shrink.
  const collapsed = small || height <= PREVIEW_MIN + PREVIEW_SNAP;
  const toggleSize = () => {
    if (collapsed) {
      // Back to the size collapsed away from — unless that was the floor too
      // (dragged all the way down twice), where the only useful answer left is
      // the default.
      setHeight(back > PREVIEW_MIN + PREVIEW_SNAP ? back : PREVIEW_DEFAULT);
      setSmall(false);
    } else {
      setBack(height);
      setSmall(true);
    }
  };
  // Live drag on the bottom edge. The height it starts from is the box's
  // CURRENT one, so a collapsed preview grows from where it actually is rather
  // than jumping to the remembered size first.
  const boxRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ y: number; h: number } | null>(null);
  useEffect(() => {
    const move = (ev: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      ev.preventDefault();
      setHeight(Math.max(PREVIEW_MIN, Math.min(PREVIEW_MAX, d.h + (ev.clientY - d.y))));
    };
    const up = () => { dragRef.current = null; };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, []);
  const startResize = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const from = boxRef.current?.getBoundingClientRect().height ?? height;
    dragRef.current = { y: e.clientY, h: from };
    // Where this drag started is what the chevron restores if it ends on the
    // floor — including when that was the floor as well, which is how the
    // "there is no bigger size to go back to" case arises.
    setBack(Math.round(from));
    setSmall(false); // dragging IS choosing a size
  };
  const openQuickLook = useUI((s) => s.openQuickLook);
  // Optimistic rotation — the picture turns at once and the writes drain
  // behind it (`shared/useRotate`, shared with the session overlays' card so
  // a picture cannot turn instantly in one place and after a round trip in
  // the other).
  const { rotate, css: cssRot } = useRotate(itemId, rotation, onRotated);
  const btn = (dir: "left" | "right", icon: string, title: string) => (
    <span
      title={title}
      onClick={(e) => { e.stopPropagation(); rotate(dir); }}
      style={{
        width: 30, height: 30, borderRadius: "var(--r-4)", cursor: "pointer",
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "var(--overlay-chrome)", color: "var(--on-scrim)",
        border: "1px solid var(--overlay-hairline)", backdropFilter: "blur(3px)",
      }}
    >
      <Icon name={icon} size={17} />
    </span>
  );
  const box = (
    <div
      ref={boxRef}
      onMouseEnter={collapsed ? undefined : () => setHover(true)}
      onMouseLeave={collapsed ? undefined : () => setHover(false)}
      onClick={collapsed && fileId != null && itemId != null
        ? () => openQuickLook([itemId]) : undefined}
      title={collapsed && fileId != null ? "Quick Look — open a large preview" : undefined}
      // Flat backdrop; the checkerboard (below) is sized to the rendered image so
      // the letterbox stays a solid colour while transparent images still show it.
      style={{
        position: "relative", isolation: "isolate", borderRadius: "var(--r-3)",
        overflow: "hidden", border: "1px solid var(--border)", background: "var(--panel-3)",
        // Collapsed, the box HUGS the picture at a fixed height rather than
        // taking the panel's width: that is what makes it read as a thumbnail
        // beside a name instead of a squashed preview, and it keeps the
        // checkerboard's own sizing exact (no letterbox to leave out).
        ...(collapsed
          ? { width: PREVIEW_THUMB, height: PREVIEW_THUMB, flex: "0 0 auto",
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: fileId != null ? "zoom-in" : "default" }
          : null),
      }}
    >
      {ratio != null && fileId != null && (
        <div
          className="mc-checker"
          style={{
            position: "absolute", top: "50%", left: "50%",
            transform: "translate(-50%, -50%)", zIndex: -1,
            aspectRatio: `${ratio}`,
            // Sized to the RENDERED picture, which in the collapsed square is
            // the letterboxed one: the long side fills, the short side
            // follows the ratio. Full size the box is width-bound, so height
            // is the side to drive it by.
            ...(collapsed && ratio >= 1
              ? { width: "100%", height: "auto" }
              : { height: "100%", width: "auto" }),
          }}
        />
      )}
      {fileId != null ? (
        <img
          src={api.thumbUrl(fileId, rotation, token)}
          alt=""
          onLoad={(e) => {
            const im = e.currentTarget;
            if (im.naturalWidth && im.naturalHeight) setRatio(im.naturalWidth / im.naturalHeight);
          }}
          style={{
            display: "block", objectFit: "contain",
            ...(collapsed
              ? { width: "100%", height: "100%" }
              : { width: "100%", height: "auto", maxHeight: height }),
            // Optimistic spin: rotate the preview instantly on click, animating to
            // the target while the server bakes the rotated file in the background.
            transform: cssRot ? `rotate(${cssRot}deg)` : undefined,
            transition: "transform 0.15s ease",
          }}
        />
      ) : glyph ? (
        <Icon name={glyph} size={26} color="var(--muted-3)" />
      ) : null}
      {/* The corner buttons belong to the FULL-SIZE preview: a thumbnail has
          no room for four of them (the floor is 80 px for exactly that
          reason), so collapsed they move into the row beside the name and
          the picture itself becomes the Quick Look button. */}
      {!collapsed && fileId != null && (
        <>
          {/* Quick Look launcher — top-left, opposite the rotate controls. Opens the
              full-size Space-bar preview of the current selection. */}
          <div
            style={{
              position: "absolute", top: 6, left: 6,
              opacity: hover ? 1 : 0, transition: "opacity 0.12s",
              pointerEvents: hover ? "auto" : "none",
            }}
          >
            <span
              title="Quick Look — open a large preview"
              onClick={(e) => { e.stopPropagation(); if (itemId != null) openQuickLook([itemId]); }}
              style={{
                width: 30, height: 30, borderRadius: "var(--r-4)", cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
                background: "var(--overlay-chrome)", color: "var(--on-scrim)",
                border: "1px solid var(--overlay-hairline)", backdropFilter: "blur(3px)",
              }}
            >
              <Icon name="visibility" size={17} />
            </span>
          </div>
          {/* Bottom-left: how tall the preview may be — chevrons, since this moves
              one edge up or down (the Quick Look button is the one that opens
              something). Opposite the rotate pair, on the corner nothing else
              uses. */}
          <div
            style={{
              position: "absolute", bottom: 6, left: 6,
              opacity: hover ? 1 : 0, transition: "opacity 0.12s",
              pointerEvents: hover ? "auto" : "none",
            }}
          >
            <span
              title="Collapse the preview"
              onClick={(e) => { e.stopPropagation(); toggleSize(); }}
              style={{
                width: 30, height: 30, borderRadius: "var(--r-4)", cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
                background: "var(--overlay-chrome)", color: "var(--on-scrim)",
                border: "1px solid var(--overlay-hairline)", backdropFilter: "blur(3px)",
              }}
            >
              <Icon name="keyboard_arrow_up" size={19} />
            </span>
          </div>
          {!readOnly && (
            <div
              style={{
                position: "absolute", top: 6, right: 6,
                display: "flex", gap: 6,
                opacity: hover ? 1 : 0, transition: "opacity 0.12s",
                pointerEvents: hover ? "auto" : "none",
              }}
            >
              {btn("left", "rotate_left", "Rotate left")}
              {btn("right", "rotate_right", "Rotate right")}
            </div>
          )}
        </>
      )}
      {/* The bottom edge itself resizes the preview — a grab strip the full
          width, so the drag is discoverable by the cursor alone. It stays on
          the thumbnail: dragging it down is the other way back up, and the
          layout turns into the full-size one as soon as the drag clears the
          floor. */}
      {fileId != null && (
        <div
          onMouseDown={startResize}
          title="Drag to resize the preview"
          style={{
            position: "absolute", left: 0, right: 0, bottom: 0, height: 7,
            cursor: "ns-resize",
          }}
        />
      )}
    </div>
  );

  if (collapsed) {
    return (
      <div
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{ padding: "10px 14px 0", display: "flex", alignItems: "flex-start", gap: 10 }}
      >
        {box}
        <div style={{ flex: 1, minWidth: 0, ...NAME_ROW, paddingTop: 1 }}>{name}</div>
        {/* The way back, and NOTHING ELSE. The rotate pair does not come
            along: it is an edit to the picture, judged by looking at the
            picture, and at 64 px there is nothing to judge — while the space
            it would hold (reserved, since a reveal may not reflow a row) is
            two of the name's five lines in a 300 px panel. Expanding is one
            click, and it is the click somebody about to turn a picture makes
            anyway. The chevron itself stays PUT rather than waiting for a
            hover: a collapsed preview has to say how to get back. */}
        {/* Nothing to expand where there is no picture — a sequence's tile
            is its glyph at any size — so the chevron waits for one rather
            than offering a bigger version of an icon. */}
        {fileId != null && (
          <IconButton
            icon="keyboard_arrow_down" size={24} glyph={18} tone="muted"
            title={back > PREVIEW_MIN + PREVIEW_SNAP ? "Back to the size you set" : "Expand the preview"}
            onClick={toggleSize}
            style={{ flex: "0 0 auto" }}
          />
        )}
      </div>
    );
  }

  return (
    <>
      {fileId != null && <div style={{ padding: "10px 14px 0" }}>{box}</div>}
      {name != null && <div style={{ padding: "6px 14px 0", ...NAME_ROW }}>{name}</div>}
    </>
  );
}

/** A single row in a small popup menu (icon + label, optional secondary hint). */

/**
 * The links of a MULTI-SELECTION, in one direction.
 *
 * The Links tab was offered for any selection and rendered only for a single
 * item, so with two pictures picked it was an empty tab with nothing in it and
 * no way to add anything — the tab said there was something to see and there
 * never was.
 *
 * A row here is the OTHER ITEM, not the relationship: eight pictures linked to
 * one page are eight relationship rows saying the same thing, and the question
 * a selection asks is which items these are linked to. So the rows aggregate
 * exactly as the Groups list does, and read the same way — normal when every
 * selected picture is linked to it, YELLOW with a count when only some are.
 *
 * `RelatedSection` stays as it is for one item, deliberately: its rows carry a
 * thumbnail, the link's meta tags, swap, and the two merge directions, and
 * every one of those is a statement about ONE relationship that a selection
 * cannot make ("merge this into that" over eight sources is eight different
 * edits). What a selection can do is link and unlink, which is what this is.
 */
function MultiLinksSection({
  itemIds, incoming, hideHeader, onOpen, onChange,
}: {
  itemIds: number[];
  incoming: boolean;
  hideHeader?: boolean;
  onOpen: (id: number) => void;
  onChange: () => void;
}) {
  const tr = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const undoRun = useUndoRun();
  const [dropActive, setDropActive] = useState(false);
  const [error, setError] = useState("");
  const flash = (msg: string) => { setError(msg); setTimeout(() => setError(""), 2600); };

  // One query per item, the keys the single-item section already uses — so a
  // link added here refreshes there and the two can never disagree. Capped
  // like every other aggregate in this panel: past `HEAVY_SELECTION` this
  // would be hundreds of requests to draw one list.
  const tooMany = itemIds.length > HEAVY_SELECTION;
  const results = useQueries({
    queries: (tooMany ? [] : itemIds).map((id) => ({
      queryKey: ["relationships", id],
      queryFn: () => api.itemRelationships(id),
    })),
  });
  const perItem = results.map((r) => r.data);
  // `results` is a fresh array every render, so the memo watches what it
  // CONTAINS — the ids and whether each answer has arrived.
  const stamp = perItem.map((d) => d?.length ?? -1).join(",");

  const n = itemIds.length;
  const rows = useMemo(() => {
    const by = new Map<number, {
      otherId: number; name: string; uid: string; relIds: number[];
      count: number;
    }>();
    for (const rels of perItem) {
      const seen = new Set<number>();
      for (const r of rels ?? []) {
        if (r.outgoing === incoming) continue;
        const cur = by.get(r.other_item_id) ?? {
          otherId: r.other_item_id, name: r.other_name,
          uid: r.other_item_uid, relIds: [], count: 0,
        };
        cur.relIds.push(r.id);
        // Counted per SOURCE item: two links from one picture to the same
        // other item (different kinds) are still one of the eight.
        if (!seen.has(r.other_item_id)) { cur.count += 1; seen.add(r.other_item_id); }
        by.set(r.other_item_id, cur);
      }
    }
    return [...by.values()]
      .map((r) => ({ ...r, partial: r.count < n }))
      .sort((a, b) => a.name.localeCompare(b.name));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp, itemIds, incoming, n]);

  const refresh = () => {
    for (const id of itemIds) {
      qc.invalidateQueries({ queryKey: ["relationships", id] });
    }
    onChange();
  };

  const sel = useRowSelect(rows.map((r) => String(r.otherId)));
  const clearSel = sel.clear;
  useEffect(() => { clearSel(); }, [itemIds, clearSel]);
  useReportSelection(incoming ? "linked-by" : "links", {
    count: sel.selected.length,
    total: rows.length,
    onSelectAll: sel.selectAll,
    onRemove: async () => {
      const picked = new Set(sel.selected);
      const ids = rows.filter((r) => picked.has(String(r.otherId)))
        .flatMap((r) => r.relIds);
      if (!ids.length) return;
      clearSel();
      await runBulk(ids, (id) => api.deleteRelationship(id), { chunk: 25 });
      refresh();
    },
    onClear: clearSel,
    removeLabel: tr("Unlink"),
    removeTitle: tr("Unlink these from every selected item"),
  });

  // Every selected item gets the link, which is the whole point of dropping
  // one onto a selection. A pair that is already linked is skipped rather
  // than reported: with eight sources some of them usually are, and that is
  // the state the drop was asking for anyway.
  const linkDropped = async (dropped: number[]) => {
    const pairs: [number, number][] = [];
    for (const src of itemIds) {
      const have = new Set((perItem[itemIds.indexOf(src)] ?? [])
        .map((r) => r.other_item_id));
      for (const id of dropped) {
        if (id === src || have.has(id)) continue;
        pairs.push(incoming ? [id, src] : [src, id]);
      }
    }
    if (!pairs.length) { flash(tr("Those items are already linked.")); return; }
    let cycles = 0;
    await runBulk(pairs, async ([from, to]) => {
      try { await api.addRelationship(from, to, "manual"); }
      catch (e) { if ((e as Error).message.includes("cycle")) cycles += 1; }
    }, { chunk: 10 });
    refresh();
    if (cycles > 0) flash(tn({
      one: "Skipped 1 link that would create a cycle.",
      other: "Skipped {n} links that would create a cycle." }, cycles));
  };

  const dragHasItems = (e: React.DragEvent) =>
    Array.from(e.dataTransfer.types).includes("application/x-mc-items");
  useDragEndReset(() => { setDropActive(false); clearDraggedItems(); });
  useEffect(() => {
    return () => {};
  }, []);

  return (
    <CollapsibleSection title={incoming ? "Linked by" : "Links"}
      sk={incoming ? "linkedby" : "related"} hideHeader={hideHeader}>
      {tooMany ? (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          {tr("Too many items selected to gather their links.")}
        </div>
      ) : (
      <div
        onDragOver={(e) => {
          if (!dragHasItems(e)) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
          setDropActive(true);
        }}
        onDragLeave={(e) => {
          const rt = e.relatedTarget as Node | null;
          if (!rt || !e.currentTarget.contains(rt)) setDropActive(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDropActive(false);
          const raw = e.dataTransfer.getData("application/x-mc-items");
          if (!raw) return;
          try {
            const ids = JSON.parse(raw) as number[];
            if (Array.isArray(ids)) void linkDropped(ids);
          } catch { /* ignore a malformed drag payload */ }
        }}
        style={{
          display: "flex", flexDirection: "column", gap: 3, borderRadius: "var(--r-5)",
          userSelect: "none",
          ...(dropActive
            ? { outline: "2px dashed var(--accent)", outlineOffset: 2 } : null),
        }}
      >
        {error && (
          <div style={{ fontSize: "var(--fs-1)", color: "var(--red-text)",
                        padding: "2px 2px 4px" }}>{error}</div>
        )}
        {rows.map((r) => {
          const picked = sel.has(String(r.otherId));
          return (
            <div key={r.otherId} {...sel.props(String(r.otherId))}
              className="hoverable"
              onDoubleClick={() => onOpen(r.otherId)}
              style={{
                display: "flex", alignItems: "center", gap: 9,
                height: 30, boxSizing: "border-box", padding: "0 6px 0 8px",
                borderRadius: "var(--r-4)", cursor: "pointer",
                background: rowBackground(picked, "var(--panel-3)"),
                border: `1px solid ${picked ? "var(--accent)" : "var(--border)"}`,
              }}>
              <Icon name="link" size={15}
                color={r.partial ? "var(--yellow)" : "var(--muted-2)"} />
              <span title={r.uid} style={{
                flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                color: r.partial ? "var(--yellow-text)" : "var(--text-bright)",
                overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>{r.name}</span>
              {r.partial && (
                <span style={{ flex: "0 0 auto", fontFamily: "var(--mono)",
                               fontSize: "var(--fs-1)", color: "var(--yellow-text)" }}>
                  {r.count} / {n}
                </span>
              )}
              <span className="row-actions" style={{ flex: "0 0 auto" }}>
                <IconButton icon="close" size={20} reveal="hover" tone="danger" title={tr("Unlink")}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={(e) => {
                    e.stopPropagation();
                    void undoRun(`${tr("Unlinked")} ${r.name}`, async () => {
                      await runBulk(r.relIds, (id) => api.deleteRelationship(id),
                                    { chunk: 25 });
                      refresh();
                    });
                  }} />
              </span>
            </div>
          );
        })}
        {rows.length === 0 && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8, padding: "10px",
            borderRadius: "var(--r-4)",
            border: `1px dashed ${dropActive ? "var(--accent)" : "var(--border-strong)"}`,
            color: "var(--muted-2)", fontSize: "var(--fs-2)",
          }}>
            <Icon name="link" size={15} color="var(--muted-3)" />
            <span>{incoming
              ? tr("Nothing links to these items. Drag items here to link them.")
              : tr("No links yet. Drag items here from the grid to link them.")}</span>
          </div>
        )}
      </div>
      )}
    </CollapsibleSection>
  );
}

/** The links of an item, in one direction. `incoming=false` is the "Links"
 *  section (items derived from this one — outgoing edges); `incoming=true` is the
 *  "Linked by" section (items this one is derived from / linked by — incoming
 *  edges). Both support dropping grid items to add a link, per-row merge/swap/
 *  remove, and free-form link tags.
 *
 *  Exported for the ANNOTATOR, which shows the same two lists on its own Links
 *  tab: a picture's links are a fact about the picture, and the window that is
 *  annotating it is where the page a panel came FROM is worth reaching.
 *  Dropping grid items to add a link is a grid gesture and there is no grid
 *  there, which costs nothing — `useLoadedViewItems` is simply empty and no
 *  drag ever starts. */
export function RelatedSection({
  itemId,
  incoming,
  hideHeader,
  noGrid,
  onOpen,
  onSelect,
  onItemsChanged,
  onChange,
}: {
  itemId: number;
  incoming: boolean;
  hideHeader?: boolean;
  /** There is no item grid in this window (the annotator). Only the empty
   *  state cares: it stops telling somebody to drag items in from a grid
   *  that is not there. The drop handlers are left alone — they can never
   *  fire, since no drag can start. */
  noGrid?: boolean;
  /** The linked item, and the LINK it was reached through — a `frame` link
   *  carries the moment of the film it names, and the annotator opens the film
   *  there rather than at its beginning. Callers that only need the item
   *  ignore the second argument. */
  onOpen: (id: number, rel: RelationshipOut) => void;
  onSelect: (ids: number[]) => void;
  onItemsChanged: () => void;
  onChange: () => void;
}) {
  const tr = useT();
  const tn = useTn();
  const undoRun = useUndoRun();
  const qc = useQueryClient();
  const { data: rels } = useQuery({
    queryKey: ["relationships", itemId],
    queryFn: () => api.itemRelationships(itemId),
  });
  const { data: tagOptions } = useQuery({ queryKey: ["link-tag-rows"], queryFn: api.linkTagRows });
  const items = useLoadedViewItems();
  const [dropActive, setDropActive] = useState(false);
  // When a drag can't be added at all, why — shown while hovering to reject it.
  const [dropReject, setDropReject] = useState<string | null>(null);
  const [error, setError] = useState("");
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["relationships", itemId] });
    qc.invalidateQueries({ queryKey: ["link-tags"] });
    qc.invalidateQueries({ queryKey: ["link-tag-rows"] });
    onChange();
  };

  const shown = (rels ?? []).filter((r) => r.outgoing === !incoming);
  // The same multi-select the other tabs have. Links had none at all, so
  // unlinking three meant three trips through a ⋯ menu.
  const sel = useRowSelect(shown.map((r) => String(r.id)));
  const clearLinks = sel.clear;
  // Both directions are on one tab, so they report under different names or
  // the second would replace the first's report.
  useReportSelection(incoming ? "linked-by" : "links", {
    count: sel.selected.length,
    total: shown.length,
    onSelectAll: sel.selectAll,
    onRemove: async () => {
      const ids = sel.selected.map(Number);
      if (ids.length > BIG_EDIT && !(await confirm({
        title: tr("Unlink {n} items?", { n: String(ids.length) }),
        answer: { label: tr("Unlink"), danger: true } }))) return;
      clearLinks();
      await runBulk(ids, (id) => api.deleteRelationship(id), { chunk: 25 });
      refresh();
    },
    onClear: clearLinks,
    removeLabel: tr("Unlink"),
    removeTitle: tr("Unlink the selected items"),
  });

  // Point the GRID at the other end of every picked link. A link row names an
  // item by a thumbnail the size of a stamp, and the question it raises —
  // which of these on screen is that? — was only answerable by opening it and
  // losing the row. Pointing is not selecting: selecting the linked item would
  // change what this very panel is about, and the row would be gone.
  const setPointed = useUI((s) => s.setPointedItemIds);
  const pickedItems = useMemo(
    () => {
      const picked = new Set(sel.selected);
      return shown.filter((r) => picked.has(String(r.id))).map((r) => r.other_item_id);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sel.selected, rels, incoming]);
  useEffect(() => {
    setPointed(pickedItems);
    // Nothing is pointed at once this list is gone — a ring around a card with
    // no row behind it is a highlight nobody can turn off.
    return () => setPointed([]);
  }, [pickedItems, setPointed]);

  // Active file id per item, so a related row can show a hover thumbnail.
  const fileByItem = useMemo(() => {
    const m = new Map<number, number | null>();
    for (const it of items) m.set(it.id, it.active_file_id);
    return m;
  }, [items]);

  // Items already touched by any link (in either direction) can't be linked
  // again — the server also rejects cycles, which we surface as an error.
  const linked = new Set((rels ?? []).map((r) => r.other_item_id));
  const flash = (msg: string) => { setError(msg); setTimeout(() => setError(""), 2600); };
  // Add links for items dropped from the grid, in this section's direction: an
  // outgoing edge (this -> dropped) for "Links", incoming (dropped -> this) for
  // "Linked by". New links get a plain "manual" kind; users categorize with tags.
  const linkDropped = async (ids: number[]) => {
    let added = false;
    let cycles = 0;
    for (const id of ids) {
      if (id === itemId || linked.has(id)) continue;
      const [from, to] = incoming ? [id, itemId] : [itemId, id];
      try {
        await api.addRelationship(from, to, "manual");
        added = true;
      } catch (e) {
        if ((e as Error).message.includes("cycle")) cycles += 1;
      }
    }
    if (added) refresh();
    if (cycles > 0) flash(tn({
      one: "Skipped 1 item that would create a cycle.",
      other: "Skipped {n} items that would create a cycle." }, cycles));
    else if (!added && ids.length > 0) flash(tr("Those items are already linked."));
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDropActive(false);
    const raw = e.dataTransfer.getData("application/x-mc-items");
    if (!raw) return;
    try {
      const ids = JSON.parse(raw) as number[];
      if (Array.isArray(ids)) linkDropped(ids);
    } catch { /* ignore malformed drag payload */ }
  };
  const dragHasItems = (e: React.DragEvent) =>
    Array.from(e.dataTransfer.types).includes("application/x-mc-items");
  // Validate a drag *before* the drop using the shared dragged-ids (dataTransfer
  // values aren't readable during dragover). Returns a rejection reason when
  // *none* of the dragged items can be linked here, else null (some can — the
  // drop skips the rest). Cycles can't be checked cheaply here; the server
  // rejects those on drop.
  const rejectReason = (): string | null => {
    const ids = getDraggedItems();
    if (ids.length === 0) return null;
    const addable = ids.filter((id) => id !== itemId && !linked.has(id));
    if (addable.length > 0) return null;
    if (ids.length === 1 && ids[0] === itemId) return "Can't link an item to itself";
    return "Already linked";
  };
  // Safety net: any drag that ends anywhere (dropped elsewhere, or cancelled
  // with Escape) clears the highlight, so it can never stick on.
  useDragEndReset(() => { setDropActive(false); setDropReject(null); clearDraggedItems(); });

  return (
    <CollapsibleSection title={incoming ? "Linked by" : "Links"} sk={incoming ? "linkedby" : "related"} hideHeader={hideHeader}>
      <div
        onDragOver={(e) => {
          if (!dragHasItems(e)) return;
          e.preventDefault();
          const reject = rejectReason();
          e.dataTransfer.dropEffect = reject ? "none" : "copy";
          setDropReject(reject);
          setDropActive(!reject);
        }}
        onDragLeave={(e) => {
          // Only clear when the pointer truly leaves the section — dragleave also
          // fires while moving between the section's child rows, where the entered
          // element (relatedTarget) is still inside the container.
          const rt = e.relatedTarget as Node | null;
          if (!rt || !e.currentTarget.contains(rt)) { setDropActive(false); setDropReject(null); }
        }}
        onDrop={(e) => { setDropReject(null); onDrop(e); }}
        style={{
          display: "flex", flexDirection: "column", gap: 3,
          borderRadius: "var(--r-5)",
          ...(dropReject
            ? { outline: "2px dashed var(--red)", outlineOffset: 2 }
            : dropActive ? { outline: "2px dashed var(--accent)", outlineOffset: 2 } : null),
        }}
      >
        {dropReject && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "var(--fs-1)", color: "var(--red-text)", padding: "2px 2px 4px" }}>
            <Icon name="block" size={13} color="var(--red)" />
            {dropReject}
          </div>
        )}
        {error && (
          <div style={{ fontSize: "var(--fs-1)", color: "var(--red-text)", padding: "2px 2px 4px" }}>{error}</div>
        )}
        {shown.map((r) => (
          <RelatedRow
            key={r.id}
            rel={r}
            picked={sel.has(String(r.id))}
            selProps={sel.props(String(r.id))}
            // Prefer the file id carried by the relationship (works for items
            // outside the loaded grid page); fall back to the grid cache.
            fileId={r.other_file_id ?? fileByItem.get(r.other_item_id) ?? null}
            tagOptions={tagOptions ?? []}
            onOpen={() => onOpen(r.other_item_id, r)}
            onRemove={() => undoRun(tr("Unlinked 1"), async () => {
              await api.deleteRelationship(r.id); refresh();
            })}
            onSwap={async () => { await api.flipRelationship(r.id); refresh(); }}
            onMergeIntoThis={async () => {
              // Fold the linked item into the current one; the current item
              // survives and stays selected.
              await api.mergeItems(r.other_item_id, itemId);
              onItemsChanged();
              onSelect([itemId]);
            }}
            onMergeIntoOther={async () => {
              // Fold the current item into the linked one; the linked item
              // survives — select it since the current item is now gone.
              await api.mergeItems(itemId, r.other_item_id);
              onItemsChanged();
              onSelect([r.other_item_id]);
            }}
            // Through the undo runner, like the row's own ✕: these are logged
            // and revertible now (they wrote nothing at all before), and a
            // meta tag typed onto the wrong link is exactly the edit somebody
            // wants back without going to find the History tab.
            onAddTag={async (name) => undoRun(tr("Tagged a link"), async () => {
              await api.addLinkTag(r.id, name); refresh();
            })}
            onRemoveTag={async (name) => undoRun(tr("Untagged a link"), async () => {
              await api.removeLinkTag(r.id, name); refresh();
            })}
          />
        ))}
        {/* Empty state — make it clear items can be dropped here to link them. */}
        {shown.length === 0 && (
          <div
            style={{
              display: "flex", alignItems: "center", gap: 8, padding: "10px 10px",
              borderRadius: "var(--r-4)", border: `1px dashed ${dropActive ? "var(--accent)" : "var(--border-strong)"}`,
              color: "var(--muted-2)", fontSize: "var(--fs-2)",
            }}
          >
            <Icon name="link" size={15} color="var(--muted-3)" />
            <span>
              {incoming
                ? (noGrid
                    ? tr("Nothing links to this item.")
                    : tr("Nothing links to this item. Drag items here to link them."))
                : (noGrid
                    ? tr("No links yet.")
                    : tr("No links yet. Drag items here from the grid to link them."))}
            </span>
          </div>
        )}
      </div>
    </CollapsibleSection>
  );
}
