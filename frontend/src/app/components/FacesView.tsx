/** The FACES tab: which crops are one person.
 *
 *  A GRID OF CLUSTERS, named and unnamed together, biggest first. A card is
 *  a cover crop, the person's display name or an empty name slot, and how
 *  many faces the cluster really holds. Named and unnamed sit in ONE grid
 *  because the question the page answers is the same for both — is this one
 *  person, and who — and two lists made you carry a crop from one to the
 *  other to say so.
 *
 *  THE TAB IS TWO COLUMNS: the clusters in a sidebar of their own, the
 *  picked cluster's crops on the right (see CLAUDE.md, "THE FACES TAB IS
 *  TWO COLUMNS"). A drill-in with a breadcrumb bar and, before it, a
 *  bottom drawer both preceded this; neither is here any more.
 *
 *  WHAT IS NOT HERE: a subject's comment, since-date, meta tags,
 *  description, delete and merge. This page is about which crops are one
 *  person, not about who that person is — the card's name links to that
 *  tag's row in the Items list, which is where the rest lives. */
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { SearchField } from "../../shared/SearchField";
import { Chip } from "../../shared/Chip";
import { IconButton } from "../../shared/IconButton";
import { EmptyState } from "../../shared/EmptyState";
import { useWindowedList } from "../useWindowedList";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type FaceRow, type SimilarFaceRow, type SubjectRow } from "../api";
import { useT, useTn } from "../i18n";
import { modalIsOpen, useUI } from "../store";
import { Icon } from "../../shared/Icon";
import { flatGroup, groupByTags, groupBySequence, groupFaces, narrowByTags,
         noFacts, type FaceFacts,
         type FaceGrouping } from "../subjects/faceGroups";
import { freshOrder, stableGroups } from "../subjects/faceOrder";
import { ClusterNamer, FaceThumb, MoveFacesOverlay, faceMenuActions,
         isGuessed, offerBack, useFaceIndex } from "./SubjectFaces";
import { ActionToast } from "./shared/ActionToast";
import { UndoRunnerSlot, useUndoBar } from "./shared/useUndoBar";
import { FilterMenu } from "./FilterMenu";
import { SubjectMergeOverlay } from "./SubjectMergeOverlay";
import { PointerMenu, RowMenu, type RowAction } from "./shared/RowMenu";
import { useRowSelect } from "./shared/useRowSelect";
import { FacePreviewOverlay, FloatingFaceInPicture } from "./shared/FaceInPicture";
import { useAnchorRect } from "../../shared/AnchoredDropdown";
import { CardGrid, GridSizeControl } from "../../shared/CardGrid";
import { columnsFor } from "../../shared/gridGeom";
import { PAGE_PAD, TagsPanes, usePaneHeight } from "./TagsPanes";
import { WhenEditor } from "./PeopleSection";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { isTypingTarget } from "../../shared/typingTarget";

/** A cluster row, gap included — the windowed list's stride. */
const CLUSTER_ROW_H = 52;

/** WHAT A TICKED TAG DOES to the grid. One set of capsules, three questions
 *  — which is a choice in front of them rather than three rows of them. */
export type TagMode = "group" | "filter" | "exclude";

//: A TABLE THE I18N HARVEST CANNOT SEE — it reads `t("…")` literals, and
//  these reach `t` as variables. Their catalog entries are added BY HAND,
//  the import overlay's ignore-rule labels' rule.
const TAG_MODES: { id: TagMode; label: string; icon: string; hint: string }[] = [
  { id: "group", label: "Group by", icon: "workspaces",
    hint: "One section per combination the crops carry" },
  { id: "filter", label: "Filter", icon: "filter_alt",
    hint: "Only the crops carrying every ticked tag" },
  { id: "exclude", label: "Exclude", icon: "filter_alt_off",
    hint: "Drop every crop carrying any ticked tag" },
];

/** THE TAGS THE GRID CAN BE GROUPED BY, as a row of ticks.
 *
 *  One row tall until it is opened. A tagged library answers with up to a
 *  hundred and fifty of these (the server caps it, and drops any tag on a
 *  single crop — a group of one is not a grouping), and a wall of capsules
 *  over the grid is a wall in front of what the page is for. Opened, it
 *  grows to a few rows and scrolls; the ticked ones lead the list, so the
 *  reason the grid is laid out the way it is never scrolls out of sight.
 *
 *  The chevron is drawn only when there IS more than a row — measured, not
 *  guessed from the count: a capsule's width is its tag's name. */
function TagCapsules({ rows, picked, open, onOpen, onToggle, mode, onMode, t }: {
  rows: { name: string; faces: number }[];
  picked: string[];
  open: boolean;
  onOpen: (v: boolean) => void;
  onToggle: (name: string) => void;
  mode: TagMode;
  onMode: (m: TagMode) => void;
  t: (s: string) => string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // `scrollHeight` is the whole content whether or not it is clipped, so
    // this answers the same while open as while shut and the chevron does
    // not flicker away the moment it is used.
    const read = () => setMore(el.scrollHeight > ROW_H + 2);
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, [rows]);
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 8,
                  minWidth: 0 }}>
      {/* THE VERB, THEN ITS OBJECTS. In front of the first row and never
          wrapping, so the bar reads as one sentence however many capsules
          follow it. */}
      <RowMenu
        always icon="arrow_drop_down" color="var(--muted-2)"
        title={t("What the ticked tags do")}
        label={<span style={{ fontSize: "var(--fs-2)", fontWeight: 600 }}>
          {t(TAG_MODES.find((m) => m.id === mode)!.label)}
        </span>}
        // THE GLYPH LEADS AND THE WORD FOLLOWS (`RowMenu`'s order), so the
        // wide side of the padding is the right one — it was on the left,
        // and the word sat against the capsule's edge.
        buttonStyle={{ width: "auto", height: ROW_H, padding: "0 9px 0 5px",
                       gap: 2, borderRadius: "var(--r-round)", flex: "0 0 auto",
                       border: "1px solid var(--border-strong)",
                       background: "var(--panel-2)", color: "var(--text-2)" }}
        actions={TAG_MODES.map((m) => ({
          icon: m.icon, label: t(m.label), hint: t(m.hint),
          active: m.id === mode,
          onClick: () => onMode(m.id),
        }))} />
      <div ref={ref}
           style={{ display: "flex", flexWrap: "wrap", gap: 6, flex: 1,
                    minWidth: 0,
                    maxHeight: open ? ROW_H * 5 + 24 : ROW_H,
                    overflowY: open ? "auto" : "hidden" }}>
        {rows.map((r) => {
          const on = picked.includes(r.name);
          return (
            <Chip key={r.name} size="lg" round bordered tone={on ? "accent" : "neutral"}
                  onClick={() => onToggle(r.name)}
                  title={on ? t("Stop grouping by this tag")
                            : t("Group the crops by this tag")}
                  style={{ height: ROW_H, minWidth: 0,
                           ...(on ? null : { color: "var(--text-2)", borderColor: "var(--border-strong)" }) }}>
              {/* `overflow: hidden` on a span whose line box is the chip's
                  `lineHeight: 1` clips the descenders — the bottom of a "g"
                  went with it. A taller line box keeps the ellipsis and the
                  whole glyph. */}
              <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap", maxWidth: 220,
                             lineHeight: 1.4 }}>
                {r.name}
              </span>
              <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                             color: on ? "var(--accent)" : "var(--muted-2)" }}>
                {r.faces}
              </span>
            </Chip>
          );
        })}
      </div>
      {more && (
        <span onClick={() => onOpen(!open)} className="hoverable"
              title={open ? t("Show fewer tags") : t("Show every tag")}
              style={{ display: "flex", alignItems: "center",
                       justifyContent: "center", flex: "0 0 auto",
                       width: ROW_H, height: ROW_H, borderRadius: "var(--r-2)",
                       cursor: "pointer", color: "var(--muted-2)" }}>
          <Icon name={open ? "expand_less" : "expand_more"} size={16} />
        </span>
      )}
    </div>
  );
}

/** One capsule's height — and therefore the collapsed bar's. */
const ROW_H = 22;

/** ONE BUTTON OF THE ROW ABOVE THE GRID. Drawn even when it has nothing to/** ONE BUTTON OF THE ROW ABOVE THE GRID. Drawn even when it has nothing to
 *  act on — dimmed and inert rather than gone, so the row's shape does not
 *  move under the pointer as crops are picked and let go. */
function BarButton({ icon, label, count, danger, disabled, onClick }: {
  icon: string;
  label: string;
  /** How many it is about, as the verb's own secondary text. */
  count?: number;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button variant={danger ? "danger" : "soft"} size="sm" onClick={disabled ? undefined : onClick} title={label}
      disabled={disabled}>
      <Icon name={icon} size={15} />
      {label}
      {count != null && (
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                       color: "var(--muted-2)" }}>{count}</span>
      )}
    </Button>
  );
}

/** One card. `subjectId` is null for a cluster nobody has named — which is
 *  most of them, and the reason the page exists. */
interface Cluster {
  key: string;
  subjectId: number | null;
  name: string;
  /** SOMEBODY ANSWERED "with no name" — a background character, an extra.
   *  Not the same as `name === ""`, which is a cluster nobody has looked at
   *  (UNKNOWN): this one has been answered, and the answer had no name in
   *  it. `db.Subject.unnamed`. */
  unnamed: boolean;
  faces: FaceRow[];
  total: number;
  grouped: boolean;
  guesses: number;
}

/** The block under a card's square crop — the name and one quiet line under
 *  it, the library grid's own (which is where the number 40 comes from).
 *
 *  THE CARD IS EXACTLY `cellW + META_H` TALL, and that is not decoration: the
 *  grid places every row at `pad + row * (cellW + META_H + gap)` and hit-tests
 *  a dragged box against the same arithmetic, so a card whose real height is a
 *  few pixels more drifts a whole row out by the seventh — which reads as the
 *  box selecting the row under the one it is over. The card's own padding and
 *  the name row's height are what add up to this. */
const META_H = 40;

/** The gap between the offered crops — the grid's own, so the strip's cards
 *  line up with the ones under it. */
const STRIP_GAP = 16;

/** The grid's own inset, so the strip above it starts where its cards do. */
const GRID_PAD = 18;

/** The page's own padding above the two columns (`FacesPage`) — the tab's
 *  inset, which is the same on every side. Both columns PIN, and a sticky
 *  box travels its own offset before it catches, so each cancels this and
 *  carries it inside instead. */
const PAGE_PAD_TOP = PAGE_PAD;

/** The two verbs that only LOOK at the picture, by the glyph each wears
 *  (`faceMenuActions`' `look` pair). They belong to the crop's menu; the bar
 *  is for what changes something. */
const LOOK_ONLY = new Set(["grid_view", "visibility"]);

/** Where the Faces tab's own column remembers its width. Not the Tags
 *  sidebar's key: a list of clusters and a tree of categories are different
 *  columns beside different things. */
const FACES_W_KEY = "mc.faces.sidebarW";

/** WHAT FOUND A FACE, in words. `Face.model` holds the EMBEDDER's key, which
 *  is not a plugin key and so has no label in the model registry; these three
 *  are what this app writes. A key it has never heard of is shown as it is —
 *  better a raw name than a wrong one. */
const MODEL_NAMES: Record<string, string> = {
  anime_face_magi: "Magi (drawn)",
  insightface_buffalo_l: "InsightFace (photographs)",
  anime_face: "Anime face (old)",
};
const modelLabel = (m: string) => MODEL_NAMES[m] ?? m;

/** Which cards to show. One axis: what the page is FOR is answering the
 *  unnamed ones, so that is the narrowing worth having. */
//: THREE STATES, NOT TWO (owner 2026-09). A cluster is NAMED, it is
//  UNKNOWN — nobody has said who it is, which is the queue this page is for
//  — or it has been answered "somebody, with no name": a background
//  character, an extra. The last is not a name and not a question, so it is
//  its own row here.
const VIEWS = [
  { id: "all", label: "Everyone", icon: "group" },
  { id: "named", label: "Named", icon: RECORD_ICON.subject },
  { id: "unnamed", label: "Unnamed", icon: "person_off" },
  { id: "unknown", label: "Unknown", icon: "person_search" },
  { id: "guess", label: "With a guess waiting", icon: "help" },
] as const;
type View = (typeof VIEWS)[number]["id"];

/** THE PAGE AROUND THE LIST — the scroller, the padding and the title.
 *
 *  `FacesView` cannot make its own scroller: the crop grid windows itself
 *  against the thing that actually moves, and the sticky cluster column is
 *  measured against it too (`usePaneHeight`), so the element has to exist
 *  above both of them. That was the Tags tab's job while this was a sub-tab
 *  of it; it is four lines, and they belong with the page they wrap rather
 *  than in `App`, which knows about views and not about padding. */
/** NO TITLE AND NO COUNT LINE (owner 2026-09), the Tags tab's rule: the tab
 *  is named in the top bar a few pixels above, the count is the list's own
 *  and the filter menu beside it already carries one per answer, and what
 *  the two lines really did was push the work down the page. */
export function FacesPage() {
  const scrollRef = useRef<HTMLDivElement>(null);
  return (
    // THE GUTTER IS RESERVED WHETHER OR NOT THERE IS A BAR, the library
    // grid's rule — and a grid of cards is why the rule exists.
    //
    // A card's width is the track's, divided. So a bar appearing takes its
    // width off the track, off every cell, and — times the rows — enough
    // off the CONTENT HEIGHT to make it fit, which takes the bar away,
    // which makes it too tall again. Measured in Safari with space-taking
    // scrollbars: the width alternated on 89 of 90 frames, the grid
    // visibly buzzing between two sizes, at every viewport height in a
    // band tens of pixels wide. `columnsFor`'s hysteresis cannot see this
    // one — the column COUNT is not what moves.
    //
    // What the gutter does is REVERSE THE SIGN of that feedback, which is
    // the part worth knowing: Safari reserves 17 px and then draws a 10 px
    // bar, so the track is WIDER with a bar than without, not narrower.
    // "Bar" and "no bar" are then each self-consistent — bistable at worst,
    // where before neither state could hold. (Chromium reserves exactly
    // what it draws, so there the track simply never moves.)
    <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", minHeight: 0,
                                  scrollbarGutter: "stable",
                                  background: "var(--bg)" }}>
      {/* NO TOP PADDING HERE: both columns pin, and each carries this
          page's own inset inside its sticky box so neither travels before
          catching (`PAGE_PAD_TOP`). */}
      <div style={{ padding: PAGE_PAD }}>
        <FacesView scrollRef={scrollRef} />
      </div>
    </div>
  );
}

export function FacesView({ scrollRef }: {
  /** The PAGE's scroller — what the grid windows itself against. Every card
   *  here scrolls with the page rather than in a box of its own, so the
   *  window has to be measured against the thing that actually moves. */
  scrollRef: React.RefObject<HTMLDivElement | null>;
}) {
  const t = useT();
  const tn = useTn();
  const faces = useFaceIndex();
  const qc = useQueryClient();
  const setView = useUI((s) => s.setView);
  const setTagsMode = useUI((s) => s.setTagsMode);
  //: The LIBRARY's search box — what "show in library" narrows to. Not
    //  this page's own field below.
  const setLibrarySearch = useUI((s) => s.setSearch);
  const showAllItems = useUI((s) => s.showAllItems);
  const setSelectedItems = useUI((s) => s.setSelectedItems);
  const { data: subjects } = useQuery({
    queryKey: ["subjects"], queryFn: api.subjects });
  const nameOf = useMemo(() => {
    const m = new Map<number, SubjectRow>();
    for (const s of subjects ?? []) m.set(s.id, s);
    return m;
  }, [subjects]);

  const [view, setViewFilter] = useState<View>("all");
  //: WHAT THE PAGE IS SEARCHED FOR — a name, since that is the only thing a
  //  cluster says in words. An unnamed one matches nothing, which is the
  //  answer: it has no name to look for yet.
  const [search, setSearch] = useState("");
  //: The grid's S/M/L, the library grid's own control and its own store
  //  field — a crop is not a photograph, so the size that reads well here is
  //  not the one that reads well there.
  const faceSize = useUI((s) => s.faceSize);
  const setFaceSize = useUI((s) => s.setFaceSize);
  //: HOW TALL THE PINNED COLUMN MAY BE — the Tags tab's own measurement
  //  (`usePaneHeight`), whose STICKY answer is the one a column pinned to
  //  the top of the scroller wants.
  const columnsRef = useRef<HTMLDivElement | null>(null);
  const paneH = usePaneHeight(scrollRef, columnsRef);
  //: WHAT THE SELECTION WAS when a box began, for a ⌘/shift box: the grid
  //  reports what the box covers on every frame, and an additive sweep is
  //  that union with what was already picked.
  const boxBase = useRef<string[]>([]);
  //: WHICH DETECTOR FOUND THEM (owner 2026-09): "" is any. A library holds
  //  drawn faces and photographed ones, and which detector found a face is
  //  the closest thing there is to saying which it is — so it cuts the LIST
  //  rather than being a fact on a row. Read off the crops a cluster carries,
  //  which for a big named one is its first page: a cluster whose only
  //  InsightFace crop is the four-hundredth answers "no" here, and the cut is
  //  a way of finding things rather than a count.
  const [model, setModel] = useState("");
  //: WHAT IS BEING CARRIED, and onto which row it would land. The two halves
  //  of the page trade in both directions — crops onto a cluster, a cluster
  //  onto a cluster — so the row has to know which it is being offered.
  //
  //  A REF, not state: `dragover` is what decides whether a row is a target,
  //  and it fires on the very next frame after `dragstart` — before a state
  //  set from that `dragstart` has been rendered. Which row is LIT is state,
  //  since that is a thing on screen.
  const dragKind = useRef<"faces" | "clusters" | null>(null);
  const [dropKey, setDropKey] = useState<string | null>(null);
  const setDragging = (k: "faces" | "clusters" | null) => { dragKind.current = k; };
  const [menu, setMenu] = useState<
    { x: number; y: number; actions: RowAction[]; heading?: string } | null>(null);
  const [preview, setPreview] = useState<FaceRow[] | null>(null);
  /** THE CROPS ON THEIR WAY SOMEWHERE ELSE — "this is someone else" asks
   *  who before it writes (`MoveFacesOverlay`). */
  const [moving, setMoving] = useState<FaceRow[] | null>(null);
  //: HOW OLD SOMEBODY IS IN THIS PICTURE — the crop whose appearance dates
  //  are being edited. It went missing when the drawer became the grid: the
  //  fact lives on the APPEARANCE, the annotator's People section has always
  //  had it, and there was no door to it here at all.
  const [dating, setDating] = useState<FaceRow | null>(null);
  //: "WHO IS THIS?" ASKED FROM THE LIST. A bumped counter rather than a
  //  second dialog: the field lives on the open cluster's title, and the
  //  menu row picks the cluster and asks in one event.
  const [nameSignal, setNameSignal] = useState(0);
  //: …AND ASKED ON THE ROW ITSELF (owner 2026-09). The field lived only on
  //  the open cluster's title, over on the other side of the page, so
  //  correcting a name meant crossing the whole window and coming back. A
  //  row is where the name IS, and a hover pencil there is the gesture
  //  every other list in this app already has. Which row, by key — one at
  //  a time, since one cluster is open at a time.
  const [namingKey, setNamingKey] = useState<string | null>(null);
  //: …AND WHAT THEY SAY ABOUT THE ONES LEFT (owner 2026-09). A correction is
  //  evidence: the cluster was built with those crops in it, so whatever was
  //  only in it BECAUSE of them is still there. The ids that just left are
  //  kept for as long as the cluster stays open, and the server is asked
  //  which of the rest lean their way.
  const [movedOut, setMovedOut] = useState<number[]>([]);
  /** The people being folded together, when two NAMED clusters are merged. */
  const [mergingSubjects, setMergingSubjects] = useState<SubjectRow[] | null>(null);

  // ---- the clusters ---------------------------------------------------------
  const clusters = useMemo<Cluster[]>(() => {
    const out: Cluster[] = [];
    for (const [sid, rows] of faces.bySubject) {
      const who = nameOf.get(sid);
      out.push({
        key: `s${sid}`, subjectId: sid,
        name: who?.display_name || who?.tag || "",
        unnamed: !!who?.unnamed,
        faces: rows, total: faces.totalBySubject.get(sid) ?? rows.length,
        grouped: true,
        guesses: faces.guessesBySubject.get(sid) ?? 0,
      });
    }
    for (const c of faces.unnamed) {
      if (!c.faces.length) continue;
      out.push({
        // Keyed by the FIRST face rather than by a subject: a loose cluster
        // has none, and the id has to survive a re-clustering that keeps the
        // same faces together.
        // Every cluster of the UNKNOWN queue is by definition unanswered:
        // the one that has been marked is in the list above, holding the
        // subject that carries the mark.
        key: `c${c.faces[0].id}`, subjectId: c.subject_id ?? null, name: "",
        unnamed: false,
        faces: c.faces, total: c.total || c.faces.length,
        grouped: c.grouped, guesses: c.guesses,
      });
    }
    // BIGGEST FIRST: the cluster with forty crops in it is both the one most
    // worth naming and the one whose mistakes cost most.
    return out.sort((a, b) => b.total - a.total
      || a.name.localeCompare(b.name));
  }, [faces.bySubject, faces.totalBySubject, faces.guessesBySubject,
      faces.unnamed, nameOf]);

  const needle = search.trim().toLowerCase();
  //: WHICH CLUSTER IS OPEN, one render behind — `drill` is derived from the
  //  selection, which is derived from this list, so the order cannot ask it
  //  directly. A render's delay costs nothing: opening a cluster does not
  //  move the list, and what the freeze is for is the answer AFTER it.
  const [openKey, setOpenKey] = useState("");
  const narrowed = useMemo(() => clusters.filter((c) =>
    (view === "all" ? true
     : view === "named" ? !!c.name
     : view === "unnamed" ? c.unnamed
     : view === "unknown" ? !c.name && !c.unnamed
     : c.guesses > 0)
    // WHICH DETECTOR FOUND THEM: a cluster is kept where any of the crops it
    // carries lists that model. `Face.model` is a comma list in first-found
    // order, so a face both detectors found answers to either.
    && (!model || c.faces.some((f) => f.models.includes(model)))
    && (!needle || c.name.toLowerCase().includes(needle))),
    [clusters, view, needle, model]);

  //: AND THE LIST HOLDS STILL WHILE A CLUSTER IS OPEN (owner 2026-09), for
  //  the grid's reason one level up: the rows are sorted by size, so an
  //  answer that moves a crop between clusters re-sorts the column the
  //  pointer is in — and the row being worked on can slide out from under
  //  it. While one is open the order it was opened with is kept and new
  //  rows go on the end; with nothing open (which is when somebody is
  //  looking for the next cluster rather than working one) it sorts freely
  //  again. A row that GOES simply goes: unlike a crop, there is no place
  //  to leave it — it is not a thing that was answered, it is a grouping
  //  that no longer exists.
  const rowOrder = useRef<{ key: string; at: Map<string, number> }>(
    { key: "", at: new Map() });
  const shown = useMemo(() => {
    const open = openKey;
    const ref = rowOrder.current;
    if (!open) { rowOrder.current = { key: "", at: new Map() }; return narrowed; }
    const at = ref.key === open ? new Map(ref.at) : new Map<string, number>();
    let next = at.size ? Math.max(...at.values()) + 1 : 0;
    for (const c of narrowed) if (!at.has(c.key)) at.set(c.key, next++);
    rowOrder.current = { key: open, at };
    return [...narrowed].sort(
      (a, b) => (at.get(a.key) ?? 0) - (at.get(b.key) ?? 0));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [narrowed, openKey]);

  //: THE KEYS IN THE ORDER THE EYE SEES — memoized, since `useRowSelect`
  //  prunes on the array's identity and the list is rebuilt every render.
  const clusterKeys = useMemo(() => shown.map((c) => c.key), [shown]);
  const sel = useRowSelect(clusterKeys, { escapeClears: true });
  const listScroll = useRef<HTMLDivElement>(null);
  const win = useWindowedList({ count: shown.length, rowHeight: CLUSTER_ROW_H,
                                scrollRef: listScroll, minCount: 80 });
  const picked = useMemo(
    () => shown.filter((c) => sel.has(c.key)), [shown, sel]);

  // ---- the drilled-in cluster ----------------------------------------------
  //
  // The grid carries a first-page-sized slice of each cluster (the server
  // caps how many crops ride along), so opening one asks for the whole set.
  /** WHICH CLUSTER IS OPEN: the one picked in the list, when exactly one
   *  is. Several picked is a selection to act on, not a place to be — the
   *  train sidebar's rule, for the same reason. DERIVED rather than held, so
   *  the crops on the right are the cluster's as it is NOW: answering one of
   *  them regroups the rest, and a snapshot taken when it was opened showed
   *  a dismissal doing nothing at all. */
  const drill = picked.length === 1 ? picked[0] : null;
  //: THE FIELD IS ONLY EVER OPEN ON THE OPEN CLUSTER, which is what lets it
  //  name `allDrillFaces` — the whole person. A named cluster's ROW carries
  //  a first strip of its crops and nothing more (`PER_STRIP`), so a field
  //  left open on a row while another was opened would have named the strip
  //  and left the rest of the person behind. It is also how the field shuts
  //  when a filter, a search or an answered crop takes its row away: the
  //  row leaves, the selection empties, and there is no open cluster left
  //  to be naming.
  useEffect(() => {
    setNamingKey((k) => (k != null && k !== drill?.key ? null : k));
  }, [drill?.key]);
  //: …AND A CLUSTER NOBODY HAS NAMED IS KEYED BY ITS FIRST FACE, which
  //  answering one can change. The ids of what is open ride in a ref, and
  //  when the key they were picked under disappears the row holding most of
  //  them is picked instead — otherwise every correction closed the cluster
  //  it was made in.
  const openIds = useRef<number[]>([]);
  if (drill) openIds.current = drill.faces.map((f) => f.id);
  useEffect(() => { setOpenKey(drill?.key ?? ""); }, [drill?.key]);
  useEffect(() => {
    if (picked.length || !openIds.current.length || !faces.loaded) return;
    const want = new Set(openIds.current);
    let best: Cluster | null = null;
    let most = 0;
    for (const c of shown) {
      const n = c.faces.reduce((k, f) => k + (want.has(f.id) ? 1 : 0), 0);
      if (n > most) { most = n; best = c; }
    }
    if (best) sel.set([best.key]);
    else openIds.current = [];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, picked.length, faces.loaded]);

  const openFaces = useQuery({
    queryKey: ["faces", "subject", drill?.subjectId],
    queryFn: () => api.subjectFaces(drill!.subjectId as number),
    enabled: drill?.subjectId != null,
  });
  const allDrillFaces: FaceRow[] = drill == null ? []
    : drill.subjectId != null ? (openFaces.data ?? drill.faces)
    : drill.faces;
  //: HOW THE GRID IS LAID OUT (owner 2026-09). Age is what it has always
  //  done; the other two are the same crops answering different questions —
  //  which book a page came from, and what the pictures are tagged.
  const [grouping, setGrouping] = useState<FaceGrouping>("age");
  //: WHETHER THE OFFERS ROW IS DRAWN (owner 2026-09). It is the page's own
  //  suggestion — "might be the same person" — and somebody working down a
  //  cluster they have already judged does not want to be asked again on
  //  every one. Turning it off also stops ASKING: each answer is a fresh
  //  run over every unanswered crop, so a row nobody is reading is a run
  //  nobody is reading.
  const [showNear, setShowNear] = useState(true);
  //: …AND THE TAGS SOMEBODY TICKED. Kept as NAMES across clusters, not
  //  reset with the open one: grouping by "smile" is a way of working, and
  //  a tag the next cluster's pictures do not carry simply offers no
  //  capsule and groups nothing.
  const [pickedTags, setPickedTags] = useState<string[]>([]);
  const [tagsOpen, setTagsOpen] = useState(false);
  //: …AND WHAT THE TICKS MEAN (owner 2026-09). The same set of tags answers
  //  three different questions about the grid, and which one is a choice
  //  rather than three controls: lay the crops out by them, keep only the
  //  crops carrying ALL of them, or drop every crop carrying ANY of them.
  //  The picker sits in FRONT of the capsules, so the row reads as a
  //  sentence: "Exclude — smile, frown".
  const [tagMode, setTagMode] = useState<TagMode>("group");
  //: WHAT THE OPEN CLUSTER'S PICTURES SAY. One request for both facts,
  //  because they are one question — how should these be laid out — and it
  //  is asked only of the cluster that is OPEN, which is at most a few
  //  hundred crops. Keyed on the ids, so answering one crop re-asks and a
  //  crop that arrived gets its facts.
  const groupIds = useMemo(
    () => allDrillFaces.map((f) => f.id), [allDrillFaces]);
  const { data: groupFacts } = useQuery({
    queryKey: ["faces", "grouping", drill?.key ?? "", groupIds],
    queryFn: () => api.faceGrouping(groupIds),
    enabled: groupIds.length > 0,
    placeholderData: (prev) => prev,
  });
  const facts: FaceFacts = useMemo(() => {
    const out = noFacts();
    const g = groupFacts;
    if (!g) return out;
    g.face_ids.forEach((id, i) => {
      out.sequence.set(id, g.sequences[i] ?? "");
      out.tags.set(id, new Set((g.tags[i] ?? []).map((k) => g.tag_names[k])));
    });
    return out;
  }, [groupFacts]);
  //: THE CAPSULE BAR — the tags worth grouping by, most crops first, and
  //  the ORDER DOES NOT MOVE WHEN ONE IS TICKED (owner 2026-09). A control
  //  whose buttons rearrange themselves under the pointer is one you have
  //  to re-read before every press, and ticking a second tag is exactly
  //  when you are still reading the first.
  //
  //  A tick whose tag the server no longer offers keeps its capsule, on the
  //  end — the next cluster's pictures may not carry it, and a control that
  //  vanishes takes its own way out with it.
  const tagBar = useMemo(() => {
    const rows = (groupFacts?.tag_names ?? []).map((name, i) => ({
      name, faces: groupFacts?.tag_faces[i] ?? 0 }));
    const have = new Set(rows.map((r) => r.name));
    return [...rows,
            ...pickedTags.filter((n) => !have.has(n))
              .map((name) => ({ name, faces: 0 }))];
  }, [groupFacts, pickedTags]);
  /** The ticks in the BAR's order — so the sections read top to bottom as
   *  the capsules read left to right, whichever order they were ticked in. */
  const tagsOn = useMemo(
    () => tagBar.map((r) => r.name).filter((n) => pickedTags.includes(n)),
    [tagBar, pickedTags]);

  //: THE OPEN CLUSTER'S OWN NARROWING (owner 2026-09): which of these crops
  //  carry a name nobody has agreed with yet. Two answers, so `FilterMenu`
  //  draws it as one tick. Reset when another cluster is opened — a filter
  //  that follows you into a cluster it empties reads as a cluster with
  //  nothing in it.
  const [faceView, setFaceView] = useState<"all" | "guess">("all");
  useEffect(() => { setFaceView("all"); setMovedOut([]); }, [drill?.key]);
  //: WHAT THE GRID IS SHOWING. The guess narrowing, and then the ticked
  //  tags where they are narrowing rather than grouping. `allDrillFaces`
  //  stays the whole cluster: the namer must name the whole person, and the
  //  capsule counts are over every crop so a capsule says what it WOULD do
  //  rather than what is left after the last one.
  const drillFaces = useMemo(() => {
    const base = faceView === "guess"
      ? allDrillFaces.filter(isGuessed) : allDrillFaces;
    if (tagMode === "group") return base;
    return narrowByTags(base, tagsOn, facts, tagMode);
  }, [allDrillFaces, faceView, tagsOn, tagMode, facts]);
  const since = drill?.subjectId != null
    ? (nameOf.get(drill.subjectId)?.since_date ?? null) : null;

  const rawGroups = useMemo(
    () => (tagsOn.length && tagMode === "group"
           ? groupByTags(drillFaces, tagsOn, facts)
           : grouping === "sequence" ? groupBySequence(drillFaces, facts)
           : grouping === "none" ? flatGroup(drillFaces)
           : groupFaces(drillFaces, since)),
    [drillFaces, since, grouping, tagsOn, tagMode, facts]);
  //: AND THE ORDER IS FROZEN WHILE THE CLUSTER IS OPEN (owner 2026-09).
  //  The unnamed list is DERIVED, so every answer re-clusters and the crops
  //  come back in another order — the grid rearranging itself under the
  //  pointer, which is the opposite of what a queue of small decisions
  //  needs. `faceOrder.stableGroups` keeps the order the cluster opened
  //  with: an answered crop stays where it was as a GHOST, an arrival is
  //  appended rather than inserted, and the whole thing is forgotten when
  //  another cluster is opened. The ref is written during the memo on
  //  purpose — the answer IS the new order, and a render that throws its
  //  result away leaves the frozen one untouched (it is rebuilt, never
  //  mutated).
  const frozen = useRef(freshOrder());
  //: …AND THE LAYOUT IS PART OF WHAT IT IS FROZEN TO. The frozen order
  //  pins each crop to "the group it was first seen in", so a key of the
  //  cluster alone survived a change of AXIS: the crops stayed pinned to
  //  their age groups, the tag groups had no slots to put them in, and the
  //  grid drew nothing at all. Re-laying the grid out is the same kind of
  //  moment as opening another cluster — the order stops being the one
  //  somebody was working down — so it starts over too.
  //: …AND SO IS EVERY NARROWING. The frozen order leaves a crop that went
  //  in place as a GHOST, which is right for an ANSWER (the crop left the
  //  cluster) and wrong for a FILTER (the crop is still there, just not
  //  shown): "With a guess waiting" greyed out every crop it hid. A change
  //  of narrowing starts the order over, like a change of axis.
  const orderKey = [drill?.key ?? "", faceView,
                    tagsOn.length ? `${tagMode}:${tagsOn.join(",")}` : "",
                    grouping].join("|");
  const stable = useMemo(() => {
    const out = stableGroups(rawGroups, frozen.current, orderKey);
    frozen.current = out.frozen;
    return out.groups;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawGroups, orderKey]);
  //: THE AGE GROUPS AS THE GRID'S SECTIONS — a flat order plus a run per
  //  group, which is exactly the shape the library's own grouping takes.
  const flatCards = useMemo(() => stable.flatMap((g) => g.faces), [stable]);
  /** The crops that are still THERE — what a selection, a count and every
   *  verb are about. A ghost is a drawing, not a member. */
  const flatFaces = useMemo(
    () => flatCards.filter((c) => !c.gone).map((c) => c.face), [flatCards]);
  const faceRuns = useMemo(
    () => stable.map((g) => ({ key: g.key, count: g.faces.length })), [stable]);
  const labelOf = useMemo(
    () => new Map(stable.map((g) => [g.key, g.label])), [stable]);
  //: KEYED BY WHAT IS DRAWN, NOT BY WHAT WAS FETCHED. `useRowSelect` extends
  //  a shift-range along the order it is handed, and this grid draws its
  //  crops GROUPED — biggest first inside each age. Keyed by the fetch's own
  //  order, a shift-range therefore picked a run nobody was shown: the two
  //  ends were right and everything between them was some other set of
  //  crops, which is what "random other items get selected" was.
  const faceKeys = useMemo(
    () => flatFaces.map((f) => String(f.id)), [flatFaces]);
  const faceSel = useRowSelect(faceKeys);
  const pickedFaces = useMemo(
    () => flatFaces.filter((f) => faceSel.has(String(f.id))),
    [flatFaces, faceSel]);

  //: THE CROPS MOST LIKE THE OPEN CLUSTER (owner 2026-09). Asked of the
  //  SUBJECT where the cluster has one (a named cluster is three hundred
  //  crops and a URL is not where those belong) and of its face ids where it
  //  does not, which is what a loose cluster is. FACES rather than clusters:
  //  "is this crop one of these?" is the question, and a cover crop standing
  //  for forty others answered a different one.
  //: NAMED so the write that answers with a new strip can put it straight
  //  in, rather than asking for the same computation a second time — and on
  //  a key of ITS OWN rather than under `["faces", …]`, so a sweep of the
  //  face lists does not throw that answer away and ask for it again. Each
  //  of these costs a fresh run over every unanswered crop.
  //: KEYED BY THE SUBJECT ALONE where the cluster has one: its crops move
  //  under every answer, and a key carrying them asked for the strip twice
  //  per add (once as the write's answer landed, once as the lists came
  //  back). The invalidation is what refreshes it then. A loose cluster
  //  has nothing but its crops to be keyed by.
  const nearKey = ["faces-near", drill?.subjectId ?? null,
                   drill?.subjectId != null ? ""
                     : drill?.faces.map((f) => f.id).join(",") ?? ""];
  const near = useQuery({
    queryKey: nearKey,
    queryFn: () => api.similarFaces(
      drill?.subjectId != null ? { subject: drill.subjectId }
        : { faces: (drill?.faces ?? []).map((f) => f.id) }, 40),
    enabled: drill != null && showNear,
    //: THE ROW STAYS WHILE THE NEXT ANSWER LOADS — "nothing blinks", the
    //  rule the index, the window's rows and the item detail already keep.
    //
    //  It matters more here than anywhere else, because this row sits ABOVE
    //  the grid: the key carries the cluster's first crops, so answering one
    //  of them is a NEW key with nothing cached, `data` is undefined for a
    //  frame or two, the whole panel unmounts — and every card below jumps
    //  up 201 px and back, which is more than a grid row's 154 px stride.
    //  Which crop you answer decides whether it happens at all, so it read
    //  as "sometimes the grid scrolls by a row".
    placeholderData: (prev) => prev,
  });
  //: AS MANY AS FIT IN ONE ROW, AT THE GRID'S OWN SIZE (owner 2026-09). The
  //  strip used to scroll sideways at a size of its own, which made it a
  //  second list with its own rules under a grid; it is the grid's first row
  //  of offers now, and what does not fit is simply not offered. The column
  //  arithmetic is the grid's (`gridGeom.columnsFor`), so the two agree
  //  about how many fit and how wide they are.
  //: MEASURED ON THE COLUMN, not on the strip itself: the strip is drawn
  //  only once there is something to offer, so a ref on it is null exactly
  //  when the first measurement would have been taken — and the effect that
  //  would re-take it has no reason to run again. The column is always
  //  there, and the grid's own inset (`CardGrid`'s `pad`) comes off it, so
  //  the offered crops line up with the ones under them.
  const stripRef = useRef<HTMLDivElement | null>(null);
  const [colW, setColW] = useState(0);
  useEffect(() => {
    const el = stripRef.current;
    if (!el) return;
    const read = () => setColW(el.clientWidth);
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const stripTrack = Math.max(0, colW - GRID_PAD * 2);
  const stripFits = Math.max(1, columnsFor(stripTrack, faceSize, STRIP_GAP, 0));
  const stripW = stripTrack > 0
    ? (stripTrack - (stripFits - 1) * STRIP_GAP) / stripFits : faceSize;
  const nearFaces = near.data ?? [];
  //: THE OFFERS SELECT LIKE THE GRID (owner 2026-09): click, ⌘-click,
  //  shift and paint over the row, Space previews what is picked, and the
  //  bar carries Add / Not this person over the lot. ONE SELECTION AT A
  //  TIME between the row and the grid under it — a pick on either side
  //  clears the other, since the bar's verbs are about one or the other
  //  and a bar answering to both would say two things.
  const nearShown = useMemo(
    () => nearFaces.slice(0, stripFits), [nearFaces, stripFits]);
  const nearKeys = useMemo(
    () => nearShown.map((n) => String(n.face.id)), [nearShown]);
  const nearSel = useRowSelect(nearKeys, { escapeClears: true });
  const nearPicked = useMemo(
    () => nearShown.filter((n) => nearSel.has(String(n.face.id))),
    [nearShown, nearSel]);
  const clearNear = nearSel.clear;
  useEffect(() => { clearNear(); }, [drill?.key, clearNear]);
  //: DOUBLE-CLICKING AN OFFER GOES TO ITS CLUSTER (owner 2026-09): the row
  //  in the list is picked — which opens it, one picked row being the open
  //  cluster — and scrolled into view. Which row is found by the cover
  //  crop (a loose cluster is keyed by its biggest face, which the cover
  //  is, but the two sorts can differ on a tie) or by the subject a named
  //  cluster's row stands for; a narrowing that hides the row is cleared,
  //  since "go to that cluster" means it has to be there.
  const [revealKey, setRevealKey] = useState<string | null>(null);
  const goToOffer = (n: SimilarFaceRow) => {
    const byFace = clusters.find((c) => c.faces.some((f) => f.id === n.face.id));
    const bySubject = n.subject_id != null
      ? clusters.find((c) => c.subjectId === n.subject_id) : undefined;
    const key = byFace?.key ?? bySubject?.key ?? `c${n.face.id}`;
    if (!narrowed.some((c) => c.key === key)) {
      setViewFilter("all"); setModel(""); setSearch("");
    }
    nearSel.clear();
    sel.set([key]);
    setRevealKey(key);
  };
  useEffect(() => {
    if (!revealKey) return;
    const at = shown.findIndex((c) => c.key === revealKey);
    if (at < 0) {
      if (!clusters.some((c) => c.key === revealKey)) setRevealKey(null);
      return;
    }
    const el = listScroll.current;
    if (el) {
      const top = at * CLUSTER_ROW_H;
      if (top < el.scrollTop || top + CLUSTER_ROW_H > el.scrollTop + el.clientHeight)
        el.scrollTop = Math.max(0, top - (el.clientHeight - CLUSTER_ROW_H) / 2);
    }
    setRevealKey(null);
  }, [revealKey, shown, clusters]);

  //: WHICH OF THE ONES LEFT NO LONGER FIT. A correction is evidence: the
  //  cluster was built with the departed crops in it, so whatever was only
  //  in it BECAUSE of them is still there.
  const odd = useQuery({
    queryKey: ["faces", "odd", drill?.key ?? "", movedOut.join(",")],
    queryFn: () => api.oddOnesOut(allDrillFaces.map((f) => f.id), movedOut),
    enabled: drill != null && movedOut.length > 0 && allDrillFaces.length > 1,
  });
  const oddFaces = useMemo(() => {
    const want = new Set(odd.data ?? []);
    return allDrillFaces.filter((f) => want.has(f.id));
  }, [odd.data, allDrillFaces]);

  //: EVERY DETECTOR THAT FOUND ANYTHING HERE, for the list's second cut.
  //  Read off the crops the page carries — there is no endpoint that
  //  answers "which detectors has this library used", and the answer is
  //  only ever used to draw two or three rows of a menu.
  const models = useMemo(() => {
    const out = new Set<string>();
    for (const c of clusters) for (const f of c.faces) {
      for (const m of f.models) out.add(m);
    }
    return [...out].sort();
  }, [clusters]);

  /** PUT THESE CROPS IN THAT CLUSTER. Both halves of the page ask for it —
   *  the ✚ on an offered face, and a carry from the grid onto a row — and
   *  it is one write either way: onto the cluster's own person where it has
   *  one, and otherwise a merge, which mints the nameless subject that holds
   *  the two together. */
  const moveFacesTo = async (ids: number[], to: Cluster) => {
    const mine = new Set(to.faces.map((f) => f.id));
    const want = ids.filter((id) => !mine.has(id));
    if (!want.length) return;
    await undo.run(
      to.name ? `${t("Moved to")} ${to.name}` : t("Merge"),
      () => (to.subjectId != null
        ? api.nameFaceCluster({ face_ids: want, subject_id: to.subjectId })
        : api.mergeFaceClusters([...to.faces.map((f) => f.id), ...want]))
        .then((rows) => {
          //: THE WRITE ANSWERS WITH THE QUEUE, at the page's own size, so
          //  it goes straight into the cache and nothing asks for the same
          //  clustering again a round trip later (2026-09: an add paid for
          //  the clustering twice and for a sweep of every library query).
          //  And the sweep is only what moved: crops merged into an
          //  UNNAMED cluster put no tag on any picture, so the tags, the
          //  items and the coalesced edit sweep have nothing to re-read —
          //  a naming does assign the person's tag, and sweeps them.
          qc.setQueryData(["faces-unnamed"], rows);
          if (to.name) faces.refresh(true);
          else faces.refreshFaces(false, true);
        }));
    faceSel.clear();
    nearSel.clear();
  };
  const addToCluster = (ids: number[]) => {
    if (drill) void moveFacesTo(ids, drill);
  };
  /** "NOT THIS PERSON", said of one offered crop. It has to STICK or the
   *  next fetch offers it again — the row has no threshold, so most of what
   *  it holds is wrong — and a statement needs an identity per side, which
   *  is why saying it holds that crop on its own (the consequence a split
   *  has, and right once somebody has said something about it). */
  const notMatching = async (ns: SimilarFaceRow[]) => {
    if (!drill || !ns.length) return;
    //: THE WRITE ANSWERS WITH THE STRIP, so nothing asks for it again. The
    //  endpoint returns the offers as they now are — that is what it is
    //  for — and refetching on top of it paid for a second run of the same
    //  computation over a cache the write had just emptied. Several offers
    //  travel as several clusters, each held on its own.
    await undo.run(t("Not this person"), () => api.clustersNotMatching(
      allDrillFaces.map((f) => f.id), ns.map((n) => n.faces.map((f) => f.id)))
      .then((rows) => { qc.setQueryData(nearKey, rows); }));
    nearSel.clear();
    //: AND ONLY THE FACE LISTS ARE SWEPT. Saying two crops are not one
    //  person writes a `SubjectCannotLink` and, where a cluster had no
    //  identity, a nameless subject to hang it on — it puts no tag on any
    //  picture, so the library's tags and items are what they were, and
    //  invalidating them made every one of those queries pay for a
    //  statement about two crops.
    faces.refreshFaces(true);
  };

  // SPACE PREVIEWS WHATEVER IS PICKED — the Library's own gesture for "show
  // me this", and the one thing a grid of small crops cannot answer by
  // itself. Not Enter: Enter in a list means "open", and opening a cluster is
  // the double-click.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Not while something is over this page (`modalIsOpen` composes the
      // overlay count, the item window and the full-window sessions).
      if (modalIsOpen()) return;
      if (e.code !== "Space" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e)) return;
      // Inside a cluster it is the picked CROPS; over the grid it is the
      // cover of each picked cluster, which is what "show me this" means
      // there.
      // …and the picked OFFERS ahead of both: an offered cluster previews
      // as the whole cluster, which the preview walks with the arrows.
      const shown = nearPicked.length
        ? nearPicked.flatMap((n) => n.faces)
        : drill
        ? pickedFaces
        : picked.map((c) => c.faces[0]).filter(Boolean);
      if (!shown.length) return;
      e.preventDefault();
      setPreview(shown);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drill, pickedFaces, picked, nearPicked]);

  //: EVERY CHANGE MADE HERE IS OFFERED BACK (owner 2026-09). Naming a
  //  cluster, splitting a crop off, dismissing one, deleting one: each is
  //  logged and revertible and always has been, but nobody is looking at the
  //  History tab at the moment a crop leaves the grid — and "This is someone
  //  else" in particular puts it in a cluster of its own, which on a page of
  //  a hundred cards reads as the crop vanishing. The toast says what
  //  happened and hands it back. ONE scope for the whole tab: drilling into
  //  a cluster and back out is not a different page, and the offer is still
  //  about the same crops.
  const undo = useUndoBar("faces", () => faces.refresh());

  const changed = (kept?: boolean) => {
    faces.refresh();
    if (!kept) faceSel.clear();
  };

  // ---- the verbs ------------------------------------------------------------
  //
  // THE THREE THINGS A CLUSTER CAN HAVE DONE TO IT are the toolbar's buttons
  // AND the context menu's rows, so each one is written once here and worn
  // twice. The menu has a fourth (Show tag), which the bar does not: it is
  // about who somebody IS rather than about which crops are them, which is
  // the one question this page does not answer.

  /** MERGING IS THREE DIFFERENT ACTS, and which one it is depends on how many
   *  of the picked clusters have a NAME. Getting this wrong loses one:
   *  folding two named people with `mergeFaceClusters` would put both into a
   *  nameless cluster and throw away both names. */
  const mergeClusters = (cs: Cluster[]) =>
    void undo.run(t("Merge"), async () => { await merging(cs); });
  const merging = (cs: Cluster[]): Promise<unknown> | undefined => {
    const ids = [...new Set(cs.flatMap((c) => c.faces.map((f) => f.id)))];
    const named = cs.filter((c) => c.subjectId != null && c.name);
    // TWO PEOPLE: which name survives is a question, and the answer moves the
    // appearances and the faces before it merges the tags
    // (`ops.subjects.merge`) — a plain tag merge would orphan them.
    if (named.length >= 2) {
      // The dialog does the work, and offers its own way back through the
      // same runner — there is nothing to watch for here.
      setMergingSubjects(named.map((c) => nameOf.get(c.subjectId as number))
        .filter(Boolean) as SubjectRow[]);
      return undefined;
    }
    // ONE PERSON AND SOME STRAYS: the strays are them. NOBODY NAMED: one
    // cluster, still waiting for a name — there is no name to lose, so
    // nothing has to be asked.
    const call = named.length === 1
      ? api.nameFaceCluster({ face_ids: ids,
                              subject_id: named[0].subjectId as number })
      : api.mergeFaceClusters(ids);
    return call.then(() => { faces.refresh(); sel.clear(); });
  };

  /** DELETING IS NOT "NOT A FACE" (owner asked, 2026-09), and the two live
   *  side by side because they answer different questions. Deleting takes the
   *  crops out of the library: nothing remembers they were ever found, so the
   *  next run of the same detector finds them again. Marking them NOT FACES
   *  keeps the rows and remembers the answer — `faces.reconcile` absorbs a
   *  detection that lands on a dismissed box, so a re-run stays quiet. Junk
   *  boxes want the second; a face somebody DREW by hand has no detector to
   *  answer, so it wants the first. */
  const deleteClusters = (cs: Cluster[]) => {
    const ids = [...new Set(cs.flatMap((c) => c.faces.map((f) => f.id)))];
    void undo.run(t("Delete"), () => Promise.all(ids.map((id) => api.deleteFace(id)))
      .then(() => { faces.refresh(); sel.clear(); }));
  };

  const dismissClusters = (cs: Cluster[]) => {
    const ids = [...new Set(cs.flatMap((c) => c.faces
      .filter((f) => f.models.length > 0).map((f) => f.id)))];
    if (!ids.length) return;
    void undo.run(t("Not faces"),
      () => Promise.all(ids.map((id) => api.updateFace(id, { dismissed: true })))
        .then(() => { faces.refresh(); sel.clear(); }));
  };

  /** WHAT THE MENU IS ABOUT, as its title (owner 2026-09): both counts, once,
   *  rather than a number beside each row — five rows each carrying "3" said
   *  the same thing five times and still left the delete reading as if it
   *  were about three crops rather than three clusters' worth. */
  const clusterHeading = (cs: Cluster[]) =>
    `${tn({ one: "{n} cluster", other: "{n} clusters" }, cs.length)} · `
    + tn({ one: "{n} face", other: "{n} faces" },
         cs.reduce((n, c) => n + c.total, 0));

  const clusterActions = (cs: Cluster[]): RowAction[] => {
    const out: RowAction[] = [];
    const named = cs.filter((c) => c.subjectId != null && c.name);
    // THE POINT OF THE PAGE, so it leads. The field itself is the open
    // cluster's title — this picks the row and asks, which is why it is
    // offered for ONE cluster only: "who are these four people" is not a
    // question with an answer.
    if (cs.length === 1) {
      out.push({
        icon: "person_edit",
        label: cs[0].name ? t("Change who this is") : t("Who is this?"),
        onClick: () => { sel.set([cs[0].key]); setNameSignal((n) => n + 1); },
      });
    }
    if (cs.length >= 2) {
      out.push({ icon: "merge", label: t("Merge"), separated: out.length > 0,
                 onClick: () => mergeClusters(cs) });
    }
    if (named.length === 1) {
      out.push({
        icon: "sell", separated: out.length > 0,
        label: t("Show tag"),
        // The ITEMS list, not the library: this page is about which crops
        // are one person, and everything else about who they are — the
        // comment, the since-date, the meta tags, the category — is on that
        // tag's row.
        // `setTagsMode` says WHICH page of the Tags tab, never that the Tags
        // tab is the one to be on — which was invisible while this list was
        // itself inside that tab, and is a silent no-op now that it is not.
        onClick: () => {
          const tag = nameOf.get(named[0].subjectId as number)?.tag;
          if (tag) { setTagsMode("items", tag); setView("tags"); }
        },
      });
    }
    // The two answers to a cluster of junk, in the order the crop's own menu
    // puts them: the one that remembers, then the one that forgets.
    if (cs.some((c) => c.faces.some((f) => f.models.length > 0))) {
      out.push({
        icon: "face_retouching_off", separated: out.length > 0,
        label: t("Not faces"),
        onClick: () => dismissClusters(cs),
      });
    }
    out.push({
      icon: "delete", danger: true, separated: out.length > 0,
      label: t("Delete"),
      onClick: () => deleteClusters(cs),
    });
    return out;
  };

  /** A face's own menu, plus the one verb the drawer never had: SAY IT IS
   *  SOMEBODY ELSE. Splitting it off makes a cluster of its own — "not this
   *  person, and I do not yet know who" — which is the answer a wrong crop
   *  in a strip of twenty usually wants. */
  const faceActions = (fs: FaceRow[]): RowAction[] => ([
    ...faceMenuActions(t, fs, drill?.subjectId != null, changed,
      fs.length === 1 ? () => setPreview([fs[0]]) : undefined,
      // ONE face only: nine crops are nine different pictures, and there is
      // no "that picture" to go to.
      fs.length === 1 ? () => {
        // `INFO:id=<uid>`, never a bare `id:` — that parses as a tag called
        // "id" and quietly matches nothing (`FaceThumb.openItem`'s rule).
        showAllItems();
        setLibrarySearch(fs[0].item_uid ? `INFO:id=${fs[0].item_uid}` : "");
        setSelectedItems([fs[0].item_id]);
        setView("library");
      } : undefined),
    //: WHEN THIS IS — offered for ONE crop that somebody is on, because the
    //  date belongs to the appearance and "these nine crops" are nine of
    //  them, in nine different pictures. Saying it also AGREES with a guess
    //  (the editor's own rule): nobody dates a name they are about to
    //  reject.
    ...(fs.length === 1 && fs[0].subjects.length > 0 ? [{
      icon: "schedule",
      label: fs[0].subjects.some((x) => x.when_date || x.when_age != null)
        ? t("Change the date or age") : t("Set the date or age"),
      short: t("Date"),
      separated: true,
      onClick: () => setDating(fs[0]),
    }] : []),
    //: "SOMEONE ELSE" ONLY WHERE THERE IS NOTHING TO REJECT (owner 2026-09).
    //  It and *Reject* / *Not this person* overlapped: both take the name
    //  off, and the difference is only where the crop lands — back in the
    //  queue, or wherever you say. So on a crop that HAS a name the one-click
    //  reject is the verb, and the offer to carry it further ("Say who")
    //  rides in the toast that reject puts up. On a crop in a cluster nobody
    //  has named there is no name to reject, nothing to overlap with, and
    //  this is the only way to say it is somebody — so it stays.
    ...(fs.some((f) => f.subjects.length > 0) ? [] : [{
      icon: "call_split", separated: true,
      label: t("This is someone else"), short: t("Someone else"),
      ...(fs.length > 1 ? { trailing: String(fs.length) } : {}),
      //: AND IT ASKS WHO (owner 2026-09). "Somebody else" had one answer —
      //  a new person with no name — which is right where you do not know
      //  yet and wrong the rest of the time: the crops left the cluster and
      //  landed where nobody was looking. The overlay offers the catalog, a
      //  name nobody has used yet, "somebody with no name" and "nobody
      //  yet", which is the old answer kept as one of them. It also leaves
      //  you WHERE YOU WERE: the correction is made while reading a
      //  cluster, and closing it to answer threw away the place.
      onClick: () => setMoving(fs),
    }]),
  ]).map((a) => (a.icon === "person_off"
    // TAKING A NAME OFF IS HALF AN ANSWER, and the toast offers the other
    // half: the crop is back in the queue, and for somebody who knows who
    // it really is, one press opens the dialog that puts it there.
    ? offerBack(a, (label, act) => undo.run(label, act, {
        label: t("Say who"), icon: "call_split",
        onClick: () => setMoving(fs),
      }))
    : offerBack(a, undo.run)));

  const openMenu = (e: React.MouseEvent, actions: RowAction[], heading?: string) => {
    e.preventDefault();
    if (actions.length) setMenu({ x: e.clientX, y: e.clientY, actions, heading });
  };

  // ---- the sidebar's rows ---------------------------------------------------
  //
  // A CLUSTER IS A ROW NOW, NOT A CARD (owner 2026-09). The page was a grid
  // of clusters that you drilled into and came back out of, which made every
  // correction a round trip: open, fix, back, find the next one. It is two
  // columns instead — the clusters on the left, the open one's crops on the
  // right — so moving a crop from one person to another is a drag across the
  // page rather than a journey. The split is the Tags tab's own
  // (`TagsPanes`), with a width of its own to remember.
  const clusterRow = (c: Cluster) => {
    const on = sel.has(c.key);
    const cover = c.faces[0];
    const rowProps = sel.props(c.key);
    //: THE ROW IS ASKING WHO THIS IS. The pencil PICKS the row first, so
    //  the cluster being named is the OPEN one — see the invariant beside
    //  `drill`. It also puts that cluster's crops on screen beside the
    //  field, which is the evidence the question is about.
    const editing = namingKey === c.key;
    return (
      <div key={c.key} {...rowProps} className="hoverable"
        onContextMenu={(e) => {
          const cs = on && picked.length > 1 ? picked : [c];
          openMenu(e, clusterActions(cs), clusterHeading(cs));
        }}
        // ONLY A PICKED ROW DRAGS, the tags list's rule: the press-and-drag
        // that paints a selection owns an unpicked one, and a native drag
        // decides at the first pixel and cannot be called off. A row with
        // the field open drags NOWHERE: a drag from inside a text field is
        // the browser's own selection gesture, not this list's.
        draggable={on && !editing}
        onDragStart={(e) => {
          const keys = picked.length > 1 && on ? picked.map((x) => x.key) : [c.key];
          e.dataTransfer.setData("text/plain", `clusters:${keys.join(" ")}`);
          e.dataTransfer.effectAllowed = "move";
          sel.cancelPress();
          setDragging("clusters");
        }}
        onDragEnd={() => { setDragging(null); setDropKey(null); }}
        onDragOver={(e) => {
          if (!dragKind.current) return;
          // Nothing is dropped on itself, and a cluster being carried is not
          // a target for the carry it is part of.
          if (dragKind.current === "clusters" && on) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
          if (dropKey !== c.key) setDropKey(c.key);
        }}
        onDragLeave={() => setDropKey((k) => (k === c.key ? null : k))}
        onDrop={(e) => {
          e.preventDefault();
          const data = e.dataTransfer.getData("text/plain");
          setDropKey(null);
          setDragging(null);
          if (data.startsWith("faces:")) {
            const ids = data.slice(6).split(",").map(Number).filter(Boolean);
            void moveFacesTo(ids, c);
          } else if (data.startsWith("clusters:")) {
            const keys = data.slice(9).split(" ").filter(Boolean);
            const from = clusters.filter((x) => keys.includes(x.key)
                                                && x.key !== c.key);
            if (from.length) mergeClusters([c, ...from]);
          }
        }}
        style={{
          // `relative` for the pencil: a reveal that took a column of its
          // own would shift every name sideways on hover, so it is OVERLAID
          // on the row's right edge (the tags list's rule).
          position: "relative",
          display: "flex", alignItems: "center", gap: 9, padding: "6px 8px",
          height: CLUSTER_ROW_H - 2, boxSizing: "border-box", flex: "0 0 auto",
          borderRadius: "var(--r-5)", cursor: "pointer", minWidth: 0,
          background: dropKey === c.key ? "var(--accent-dim)"
            : on ? "var(--accent-dim)" : undefined,
          border: `1px solid ${dropKey === c.key ? "var(--accent)"
            : on ? "var(--accent)" : "transparent"}`,
        }}>
        {cover ? (
          <img src={api.faceCropUrl(cover, 96)} alt="" draggable={false}
               loading="lazy" width={38} height={38}
               style={{ width: 38, height: 38, objectFit: "cover",
                        borderRadius: "var(--r-3)", flex: "0 0 auto",
                        border: "1px solid var(--border)" }} />
        ) : (
          <span style={{ width: 38, height: 38, borderRadius: "var(--r-3)",
                         flex: "0 0 auto", background: "var(--panel-3)" }} />
        )}
        {editing ? (
          //: THE FIELD IN PLACE OF THE NAME — the same `ClusterNamer` the
          //  grid's title carries, so there is one answer to "who is this?"
          //  wherever it is asked. It takes the name AND the counts' line:
          //  a field squeezed beside "26 faces" in a column somebody may
          //  have dragged to 180 px is a field you cannot read what you
          //  typed in.
          //
          //  Every pointer event stops here. The row under it paints a
          //  selection on mousedown and opens a cluster on click, and a
          //  press in a text field must do neither — least of all a
          //  double-click to pick a word, which the row would read as two
          //  presses on itself.
          <span style={{ flex: 1, minWidth: 0 }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => e.stopPropagation()}>
            <ClusterNamer
              cluster={{ faces: allDrillFaces, total: c.total,
                         subject_id: c.subjectId, grouped: c.grouped,
                         guesses: c.guesses }}
              subjects={subjects ?? []}
              onNamed={() => { faces.refresh(); sel.clear(); }}
              onClose={() => setNamingKey(null)}
              // Mounted BECAUSE the pencil was pressed, so it opens at
              // once: the signal is a request, and this mount is the
              // request (see `openSignal`).
              openSignal={1}
              width="100%"
            />
          </span>
        ) : (<>
        <span style={{ display: "flex", flexDirection: "column", gap: 1,
                       minWidth: 0, flex: 1 }}>
          {/* THE TITLE IS THE NAME, AND WHERE THERE IS NONE IT IS THE WORD
              FOR WHY — Unknown is the question nobody has answered, Unnamed
              the answer that had no name in it. */}
          <span style={{ fontSize: "var(--fs-3)", fontWeight: 500, overflow: "hidden",
                         textOverflow: "ellipsis", whiteSpace: "nowrap",
                         color: c.name ? "var(--text-bright)"
                                       : "var(--muted-2)" }}>
            {c.name || (c.unnamed ? t("Unnamed") : t("Unknown"))}
          </span>
          {/* …AND THE SUBTITLE IS HOW MANY, with the waiting guesses beside
              it in the amber every guess wears. */}
          <span style={{ display: "flex", gap: 5, fontFamily: "var(--mono)",
                         fontSize: "var(--fs-1)", color: "var(--muted-2)",
                         overflow: "hidden", whiteSpace: "nowrap" }}>
            <span>{tn({ one: "{n} face", other: "{n} faces" }, c.total)}</span>
            {c.guesses > 0 && (
              <span style={{ color: "var(--yellow)" }}>
                {tn({ one: "{n} guess", other: "{n} guesses" }, c.guesses)}
              </span>
            )}
          </span>
        </span>
        {/* THE PENCIL, quiet until the row is hovered and taking no space
            until then. `visibility`, never a fade: Safari leaves a fading
            element painted. It wears the row's own fill so it reads over
            the tail of a long name rather than through it. */}
        <IconButton icon="person_edit" size={24} glyph={15} reveal="fixed" active={on}
              title={c.name ? t("Change who this is") : t("Who is this?")}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                // PICK FIRST, THEN ASK — see `editFaces` above.
                sel.set([c.key]);
                setNamingKey(c.key);
              }} style={{ position: "absolute", top: "50%", right: 6, transform: "translateY(-50%)" }} />
        </>)}
      </div>
    );
  };

  const sidebar = (
    <div style={{ display: "flex", flexDirection: "column", gap: 8,
                  minHeight: 0, maxHeight: paneH.sticky - 10 }}>
      {/* WHAT THE LIST HOLDS, and the way to cut it down. The search is the
          CLUSTERS' own — a name is the only thing a cluster says in words —
          so it belongs over them rather than over the crops on the right.
          TWO LINES, THE FILTER OVER THE FIELD (owner 2026-09): this column
          is as narrow as somebody cares to drag it, and beside a menu whose
          label grows with its own answer ("Unknown (912)") the field was
          down to a few characters — and it is the one control here that
          needs room for what is typed into it. */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <FilterMenu t={t} title={t("Show")}
          sections={[{
            title: t("Show"),
            views: VIEWS.map((v) => ({ id: v.id, label: t(v.label), icon: v.icon })),
            value: view,
            suffix: (id) => ` (${
              id === "all" ? clusters.length
              : id === "named" ? clusters.filter((c) => c.name).length
              : id === "unnamed" ? clusters.filter((c) => c.unnamed).length
              : id === "unknown"
                ? clusters.filter((c) => !c.name && !c.unnamed).length
              : clusters.filter((c) => c.guesses > 0).length})`,
            onPick: (id) => { setViewFilter(id as View); sel.clear(); },
          },
          // WHICH DETECTOR FOUND THEM (owner 2026-09). A library holds drawn
          // faces and photographed ones, and the two detectors that find
          // them are the closest thing there is to saying which is which —
          // so it is a cut through the list, not a fact about a cluster.
          ...(models.length > 1 ? [{
            title: t("Found by"),
            views: [{ id: "", label: t("Any detector"), icon: "filter_alt" },
                    ...models.map((m) => ({ id: m, label: modelLabel(m),
                                            icon: "center_focus_strong" }))],
            value: model,
            onPick: (id: string) => { setModel(id); sel.clear(); },
          }] : [])]} />
      </div>
      <SearchField size="md" value={search} onChange={setSearch} placeholder={t("Search names…")}
                   clearTitle={t("Clear")} />
      {/* THE CLUSTERS. A press-and-drag paints a run of them, a picked one
          carries onto another to merge, and crops carried from the grid land
          on the row they are moved to. */}
      <div ref={listScroll}
           style={{ overflowY: "auto", minHeight: 0, paddingRight: 2 }}>
        {/* WINDOWED past a screenful (`useWindowedList`): a library's
            clusters are thousands of rows, and mounting every one of them
            made a scroll of this column a layout of all of it. The rows are
            a fixed height (`CLUSTER_ROW_H`, gap included), so the window is
            exact. */}
        <div ref={win.containerRef}
             style={{ display: "flex", flexDirection: "column", gap: 2,
                      ...(win.windowed ? { height: win.totalHeight, boxSizing: "border-box",
                                           paddingTop: win.topOffset } : null) }}>
          {(win.windowed ? shown.slice(win.start, win.end) : shown).map((c) => clusterRow(c))}
        </div>
        {shown.length === 0 && (
          <EmptyState dense style={{ padding: "18px 4px", fontSize: "var(--fs-3)" }}
            line={clusters.length === 0
              ? t("No faces yet. Run a face detector over some pictures.")
              : t("Nothing here under this filter.")} />
        )}
      </div>
    </div>
  );

  //: THE ROW ABOVE THE GRID: what can be done to the crops picked in it on
  //  the left, what the grid itself is on the right. The cluster verbs are
  //  not here — they belong to the list beside it, which is where the rows
  //  they act on are (its right-click, and the sidebar's own selection).
  const bar = (
    // PINNED, like the column of clusters beside it (owner 2026-09): the
    // grid scrolls with the PAGE, so a hundred crops down its verbs — the
    // namer, what the picked ones can be done to, the narrowing, the card
    // size — had all scrolled away, and answering a crop meant scrolling
    // back up for the button and back down for the next one. The negative
    // side margins are the Tags toolbar's: the band paints over the page
    // padding so cards do not slide past visibly at its edges.
    // IT DOES NOT MOVE FIRST. A sticky box starts wherever the flow put it
    // and only pins once it reaches `top`, so with the page's own 16 px of
    // padding above it the bar slid 18 px up before catching — a header
    // that jumps as you start scrolling. The padding comes INSIDE the box
    // instead (cancelled by the matching negative margin), so its top edge
    // is already at the scroller's origin and there is nothing to travel.
    <div style={{ position: "sticky", top: 0, zIndex: 3,
                  background: "var(--bg)",
                  margin: `-${PAGE_PAD_TOP}px -${PAGE_PAD}px 12px 0`,
                  padding: `${PAGE_PAD_TOP + 2}px ${PAGE_PAD}px 10px 0`,
                  // THE BAND IS A COLUMN OF ROWS, the Tags toolbar's shape:
                  // the verbs and the menus are one row, and what the grid
                  // is GROUPED BY is a row under them. The tags are a set,
                  // not a button, and they need the width.
                  display: "flex", flexDirection: "column",
                  alignItems: "stretch", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10,
                    minHeight: 34 }}>
      {drill && (
        <span style={{ display: "flex", alignItems: "baseline", gap: 7,
                       minWidth: 0, marginRight: 2 }}>
          {/* THE TITLE IS THE CONTROL: pressing it asks who this is (owner
              2026-09). It was the empty name slot on the cluster CARD, and
              the cards became rows when this tab went to two columns — the
              namer came with the import and nothing mounted it, so there
              was no door left to name a cluster or change who it is. A row
              is a paint-and-drag target and a selection key, so an inline
              field belongs in the header of the OPEN cluster rather than in
              the list: one cluster is open at a time, and it is the one
              being read.
              `allDrillFaces`, not `drill.faces`: a named cluster's row
              carries a first-strip slice of its crops, and naming the slice
              would leave the rest behind. */}
          <ClusterNamer
            cluster={{ faces: allDrillFaces, total: drill.total,
                       subject_id: drill.subjectId, grouped: drill.grouped,
                       guesses: drill.guesses }}
            subjects={subjects ?? []}
            onNamed={() => { faces.refresh(); sel.clear(); }}
            openSignal={nameSignal}
            trigger={(open) => (
              <span onClick={open} className="hoverable"
                    title={drill.name ? t("Change who this is")
                                      : t("Who is this?")}
                    style={{ fontSize: "var(--fs-4)", fontWeight: 600, minWidth: 0,
                             overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap", cursor: "pointer",
                             borderRadius: "var(--r-2)", padding: "1px 5px",
                             margin: "0 -5px",
                             color: drill.name ? "var(--text-bright)"
                                               : "var(--muted)" }}>
                {drill.name || (drill.unnamed ? t("Unnamed") : t("Unknown"))}
              </span>
            )} />
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                         color: "var(--muted-2)" }}>
            {allDrillFaces.length}
          </span>
        </span>
      )}
      {/* THE BAR CARRIES WHAT CHANGES SOMETHING (owner 2026-09). Show in
          library and Preview write nothing and answer "which one is this?",
          which the crop itself already answers on hover and on a press —
          and they are offered ONLY for a single crop, so the bar grew and
          shrank by two buttons as the selection changed, moving every verb
          beside them under the pointer. Both stay in the crop's own menu,
          where they were reached from anyway. */}
      {drill && pickedFaces.length > 0
        && faceActions(pickedFaces).filter((a) => !LOOK_ONLY.has(a.icon ?? ""))
             .map((a) => (
        <BarButton key={a.label} icon={a.icon ?? "chevron_right"}
                   label={a.short ?? a.label} danger={a.danger}
                   count={pickedFaces.length > 1 ? pickedFaces.length : undefined}
                   onClick={a.onClick} />
      ))}
      {/* THE OFFERS' OWN TWO VERBS over what is picked in their row — the
          ✚ and the ✕ every card carries, said of several at once. Never
          beside the grid's verbs: a pick on either side clears the other. */}
      {drill && nearPicked.length > 0 && (<>
        <BarButton icon="add" label={t("Add to this cluster")}
                   count={nearPicked.length > 1 ? nearPicked.length : undefined}
                   onClick={() => void addToCluster(
                     nearPicked.flatMap((n) => n.faces.map((f) => f.id)))} />
        <BarButton icon="close" label={t("Not this person")}
                   count={nearPicked.length > 1 ? nearPicked.length : undefined}
                   onClick={() => void notMatching(nearPicked)} />
      </>)}
      <span style={{ flex: 1 }} />
      {/* THE OPEN CLUSTER'S OWN NARROWING: which of these crops are still
          waiting to be agreed with. Two answers, so the menu draws it as a
          single tick. */}
      {drill && (
        <FilterMenu t={t} title={t("Show")}
          sections={[{
            title: t("Show"),
            views: [
              { id: "all", label: t("Every face"), icon: "group" },
              { id: "guess", label: t("With a guess waiting"), icon: "help" },
            ],
            value: faceView,
            suffix: (id) => ` (${id === "all" ? allDrillFaces.length
              : allDrillFaces.filter(isGuessed).length})`,
            onPick: (id) => {
              setFaceView(id as "all" | "guess");
              faceSel.clear();
            },
          },
          // THE PAGE'S OWN SUGGESTION, on or off — in the same menu as the
          // narrowing because "what is on this page" is one question, but
          // a QUIET switch (owner 2026-09): the row being off narrows
          // nothing, so it never lights the button or names itself on it.
          // The tick says the row is shown.
          {
            quiet: true,
            views: [
              { id: "on", label: t("Might be the same person"),
                icon: "person_search" },
              { id: "off", label: t("No offers"), icon: "person_search" },
            ],
            value: showNear ? "on" : "off",
            onPick: (id) => setShowNear(id === "on"),
          },
          // HOW THE CROPS ARE LAID OUT. One axis at a time: the tag
          // capsules under this bar take over whenever anything is ticked,
          // so this says what happens when nothing is — which is why it is
          // dimmed rather than hidden then (the answer still applies the
          // moment the last tick comes off).
          {
            title: t("Grouped by"),
            views: [
              { id: "age", label: t("Age"), icon: "cake" },
              { id: "sequence", label: t("Sequence"), icon: "auto_stories" },
              { id: "none", label: t("Nothing"), icon: "grid_view" },
            ],
            value: grouping,
            onPick: (id) => setGrouping(id as FaceGrouping),
          }]} />
      )}
      <GridSizeControl size={faceSize} onSize={setFaceSize} t={t} />
      </div>
      {/* WHAT THE PICTURES ARE TAGGED, as a set of ticks (owner 2026-09).
          Ticking one or more lays the grid out by them — and by the
          COMBINATION each crop carries, so a crop is in exactly one
          section: with `smile` and `frown` on, the sections are
          "smile, frown", "smile", "frown" and the rest.

          One row until it is opened, because this is a bar of up to a
          hundred and fifty capsules on a tagged library and the grid is
          what the page is for. */}
      {drill && tagBar.length > 0 && (
        <TagCapsules rows={tagBar} picked={pickedTags} open={tagsOpen}
          onOpen={setTagsOpen} t={t}
          mode={tagMode}
          onMode={(m) => { faceSel.clear(); setTagMode(m); }}
          onToggle={(name) => {
            faceSel.clear();
            setPickedTags((p) => p.includes(name)
              ? p.filter((x) => x !== name) : [...p, name]);
          }} />
      )}
    </div>
  );

  return (
    // EVERY VERB UNDER HERE OFFERS ITS WAY BACK — the crop's own ✕, its
    // right-click menu, the namer on a card — by asking the runner for it
    // rather than by being handed a callback each (`useUndoRun`).
    <UndoRunnerSlot run={undo.run}>
    <TagsPanes columnsRef={columnsRef} widthKey={FACES_W_KEY}>
      {/* THE CLUSTERS, PINNED: the grid beside them scrolls with the page,
          so the column that says which cluster is open has to stay. The
          page's top padding rides inside it for the bar's reason — a column
          that slides 18 px before catching is a column that jumps. */}
      <div style={{ position: "sticky", top: 0, alignSelf: "start",
                    marginTop: -PAGE_PAD_TOP,
                    paddingTop: PAGE_PAD_TOP + 2 }}>
        {sidebar}
      </div>
      <div style={{ minWidth: 0 }} ref={stripRef}>
      {bar}
      {/* NOTHING PICKED, NOTHING TO SHOW. Two columns make the question
          "which of these" rather than "where am I", so the right half says
          what to do rather than drawing a second list of the same rows. */}
      {!drill && (
        <div style={{ display: "flex", flexDirection: "column",
                      alignItems: "center", gap: 14,
                      color: "var(--muted)", fontSize: "var(--fs-4)", padding: "40px 0",
                      textAlign: "center" }}>
          <span>
            {picked.length > 1
              ? tn({ one: "{n} cluster picked", other: "{n} clusters picked" },
                   picked.length)
              : faces.loaded && clusters.length === 0
              ? t("No faces yet. Run a face detector over some pictures.")
              : t("Pick a cluster to see its faces.")}
          </span>
          {/* WHAT SEVERAL PICKED CLUSTERS ARE FOR — the verbs that only make
              sense over more than one, where the answer to "and now what"
              belongs: the list beside them has no room for a row of buttons,
              and its right-click holds the same ones for a single row. */}
          {picked.length > 1 && (
            <div style={{ display: "flex", gap: 8 }}>
              {clusterActions(picked).map((a) => (
                <BarButton key={a.label} icon={a.icon ?? "chevron_right"}
                           label={a.short ?? a.label} danger={a.danger}
                           onClick={a.onClick} />
              ))}
            </div>
          )}
        </div>
      )}
      {/* THE FACES MOST LIKE THIS CLUSTER'S (owner 2026-09), one row and no
          scrolling: as many as fit, at the grid's own card size, each one a
          FACE rather than a cluster — "is this crop one of these?" is the
          question, and a cover crop standing for forty others answered a
          different one. Pressing the ✚ takes it into the open cluster;
          pressing the ✕ says it is not this person, which sticks.
          A CARD HERE IS A CARD IN THE GRID (owner 2026-09): same crop, same
          hover thumbnail of the whole picture, and NO NAME under it — every
          offer is a crop nobody has answered, so the line said "Unknown"
          under all of them and cost the row a line to say nothing. The
          likeness moves onto the crop's bottom corner, where it is read
          against the face it is about.
          AND THE ROW IS FENCED: a rounded panel with the heading inside it,
          because these are not this cluster's crops — everything below the
          fence is what somebody has already said is this person, and
          everything inside it is a question. */}
      {drill && showNear && nearFaces.length > 0 && (
        // THE FENCE SITS OUTSIDE THE CARD TRACK. `stripW` is measured
        // against the grid's own track (`colW` less `GRID_PAD` either side)
        // so the offers line up with the cards below them — so the panel's
        // own padding has to come out of its margin, or every offer would
        // stand 12 px in from the column it belongs to.
        <div style={{ margin: `0 ${GRID_PAD - 12}px 14px`, padding: "10px 12px 12px",
                      border: "1px solid var(--border)", borderRadius: "var(--r-7)",
                      background: "var(--panel-2)" }}>
          <div style={{ fontSize: "var(--fs-3)", fontWeight: 600, marginBottom: 8,
                        color: "var(--text)" }}>
            {t("Might be the same person")}
          </div>
          <div style={{ display: "flex", gap: 16 }}>
            {nearShown.map((n) => {
              const key = String(n.face.id);
              const props = nearSel.props(key);
              return (
                <NearFaceCard key={n.face.id} near={n} size={stripW} t={t}
                              picked={nearSel.has(key)}
                              onDown={(e) => { faceSel.clear(); props.onMouseDown(e); }}
                              onEnter={props.onMouseEnter}
                              onPick={props.onClick}
                              onOpen={() => goToOffer(n)}
                              onAdd={() => void addToCluster(n.faces.map((f) => f.id))}
                              onNo={() => void notMatching([n])} />
              );
            })}
          </div>
        </div>
      )}
      {/* WHAT THE CORRECTION LEAVES BEHIND (owner 2026-09). Taking crops out
          of a cluster says something about the ones that stayed: whatever
          was only in it because of them is still in it. This row is those —
          the ones that look more like what just left than like what remains
          — offered together, since finding them one at a time is the work
          the correction was supposed to save. An OFFER: press Move them, or
          ignore it and it goes when the cluster closes. */}
      {drill && oddFaces.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8,
                        marginBottom: 6 }}>
            <span style={{ fontSize: "var(--fs-3)", fontWeight: 600,
                           color: "var(--text)" }}>
              {t("These look more like the ones you moved")}
            </span>
            <BarButton icon="call_split" label={t("Move them too")}
                       count={oddFaces.length}
                       onClick={() => setMoving(oddFaces)} />
            <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
            <IconButton icon="close" size={20} reveal="hover" title={t("Put this message away")}
                  onClick={() => setMovedOut([])} />
          </div>
          <div style={{ display: "flex", gap: 8, overflowX: "auto",
                        paddingBottom: 4 }}>
            {oddFaces.slice(0, 24).map((f) => (
              <img key={f.id} src={api.faceCropUrl(f, 96)} alt=""
                   width={72} height={72} loading="lazy"
                   title={t("Move them too")}
                   onClick={() => setMoving([f])}
                   style={{ width: 72, height: 72, objectFit: "cover",
                            borderRadius: "var(--r-4)", cursor: "pointer",
                            border: "1px solid var(--border)",
                            outline: "2px solid var(--yellow)",
                            outlineOffset: 3, flex: "0 0 auto" }} />
            ))}
          </div>
        </div>
      )}
      {/* THE OPEN CLUSTER'S CROPS — the library's own grid, the age groups
          as its SECTIONS. */}
      {drill && (
        <CardGrid
          count={flatCards.length} size={faceSize} gap={STRIP_GAP} pad={GRID_PAD}
          scrollRef={scrollRef}
          // ONE SECTION IS NOT A SECTION (owner 2026-09): a single heading
          // over every crop in the cluster names nothing the list beside it
          // has not already said. Several, and the catch-all is "Other" —
          // these are AGES, and "Undated" was answering a question about
          // dates that this grouping does not ask.
          runs={faceRuns.length > 1 ? faceRuns : null}
          headerH={34} groupGap={18}
          renderHeader={(run) => (<>
            <span style={{ fontSize: "var(--fs-4)", fontWeight: 600, color: "var(--text)",
                           whiteSpace: "nowrap", overflow: "hidden",
                           textOverflow: "ellipsis" }}>
              {labelOf.get(run.key) || t("Other")}
            </span>
            <span style={{ fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
              {run.count}
            </span>
            <span style={{ flex: 1, height: 1, background: "var(--border)" }} />
          </>)}
          onMarqueeStart={() => { boxBase.current = faceSel.selected; nearSel.clear(); }}
          onMarquee={(hits, additive) => {
            // A GHOST TAKES NO PART: it is where a crop WAS, so a marquee
            // drawn over it selects the live crops it crosses and nothing
            // else.
            const keys = hits
              .map((i) => flatCards[i] && !flatCards[i].gone
                && String(flatCards[i].face.id))
              .filter(Boolean) as string[];
            faceSel.set(additive
              ? [...new Set([...boxBase.current, ...keys])] : keys);
          }}
          renderCard={(i, geom) => {
            const card = flatCards[i];
            if (!card) return <div key={i} />;
            const f = card.face;
            const on = !card.gone && faceSel.has(String(f.id));
            // WHERE A CROP WAS. Drawn in place, faded and inert — the answer
            // is visible where the eye already is, rather than as a hole
            // that pulls every crop after it forward. It goes when the
            // cluster is left; until then the way back is the undo bar.
            if (card.gone) {
              return (
                <div key={f.id} data-card="" title={t("Answered — it is no longer in this cluster")}
                     style={{ display: "flex", opacity: 0.28,
                              pointerEvents: "none", filter: "grayscale(1)" }}>
                  <img src={api.faceCropUrl(f, 224)} alt="" loading="lazy"
                       draggable={false}
                       style={{ width: geom.cellW, height: geom.cellW,
                                objectFit: "cover", boxSizing: "border-box",
                                borderRadius: "var(--r-4)", display: "block",
                                border: "1px dashed var(--border-strong)" }} />
                </div>
              );
            }
            return (
              <div key={f.id} data-card="" style={{ display: "flex" }}
                // ANY CROP CARRIES ONTO A CLUSTER in the list beside the
                // grid (owner 2026-09): a picked one takes the whole pick
                // with it, an unpicked one goes alone — the library grid's
                // own rule. The paint gesture yields: a native drag decides
                // at the first pixel, so a press on a crop and a move is a
                // carry, and a run is picked with a box, shift or ⌘.
                draggable
                onDragStart={(e) => {
                  const ids = on && pickedFaces.length
                    ? pickedFaces.map((x) => x.id) : [f.id];
                  e.dataTransfer.setData("text/plain", `faces:${ids.join(",")}`);
                  e.dataTransfer.effectAllowed = "move";
                  faceSel.cancelPress();
                  setDragging("faces");
                }}
                onDragEnd={() => { setDragging(null); setDropKey(null); }}>
                <FaceThumb face={f} size={geom.cellW}
                  unname={drill.subjectId != null}
                  onChanged={changed}
                  picked={on}
                  onPick={faceSel.props(String(f.id)).onClick}
                  onDown={(_id, e) => {
                    nearSel.clear();
                    faceSel.props(String(f.id)).onMouseDown?.(e);
                  }}
                  onEnter={() => faceSel.props(String(f.id)).onMouseEnter?.()}
                  onMenu={(face, at) => setMenu({
                    x: at.x, y: at.y,
                    heading: faceSel.has(String(face.id)) && pickedFaces.length > 1
                      ? tn({ one: "{n} face", other: "{n} faces" }, pickedFaces.length)
                      : undefined,
                    actions: faceActions(
                      faceSel.has(String(face.id)) && pickedFaces.length > 1
                        ? pickedFaces : [face]),
                  })} />
              </div>
            );
          }} />
      )}
      </div>
    </TagsPanes>
    {menu && (
      <PointerMenu at={{ x: menu.x, y: menu.y }} heading={menu.heading}
                   actions={menu.actions} onClose={() => setMenu(null)} />
    )}
    {dating && (
      <FaceWhenOverlay face={dating} t={t}
        onClose={() => setDating(null)}
        onSaved={() => { setDating(null); faces.refresh(); }} />
    )}
    {moving && moving.length > 0 && (
      <MoveFacesOverlay
        faces={moving}
        subjects={subjects ?? []}
        onClose={() => setMoving(null)}
        onMoved={() => {
          faces.refresh();
          faceSel.clear();
          // WHAT LEFT IS THE QUESTION ASKED OF WHAT STAYED.
          setMovedOut(moving.map((f) => f.id));
        }} />
    )}
    {mergingSubjects && mergingSubjects.length >= 2 && (
      <SubjectMergeOverlay
        sources={mergingSubjects}
        onClose={() => setMergingSubjects(null)}
        onMerged={() => {
          setMergingSubjects(null);
          faces.refresh();
          sel.clear();
        }} />
    )}
    {preview && preview.length > 0 && (
      <FacePreviewOverlay faces={preview} title={t("Preview")}
                          onClose={() => setPreview(null)} />
    )}
    {undo.state && (
      <ActionToast
        text={undo.state.undone ? t("That was undone") : undo.state.label}
        actionLabel={undo.state.undone ? t("Redo") : t("Undo")}
        actionTitle={undo.state.undone ? t("Do it again")
                                       : t("Put it back the way it was")}
        icon={undo.state.undone ? "redo" : "undo"}
        dismissTitle={t("Put this message away")}
        extra={undo.state.undone ? undefined : undo.state.extra}
        onAction={() => void undo.toggle()}
        onDismiss={undo.dismiss}
      />
    )}
    </UndoRunnerSlot>
  );
}

/** ONE OFFER: a crop — or a whole unanswered cluster — that might be this
 *  person. The grid's own card: the same crop at the same size, the same
 *  whole-picture thumbnail on hover, which is the thing that answers "is
 *  this them?" for twenty crops of one haircut. What it does NOT carry is a
 *  name: every offer is a face nobody has answered, so the line read
 *  "Unknown" under all of them.
 *
 *  A CLUSTER IS ONE CARD (owner 2026-09): its cover crop, with how many
 *  crops it holds in the bottom-left corner and the likeness in the right —
 *  a cluster of one is simply a face. A press picks it (the grid's own
 *  gesture: paint, ⌘, shift), Space opens the preview, which walks every
 *  crop of the cluster, and a double-click goes to the cluster's row.
 *
 *  Its own component for the hover state: `useAnchorRect` needs a ref per
 *  card, and a hook cannot live inside a `.map`. */
function NearFaceCard({ near, size, t, picked, onDown, onEnter, onPick, onOpen,
                        onAdd, onNo }: {
  near: SimilarFaceRow;
  size: number;
  t: (s: string) => string;
  picked: boolean;
  /** The press-and-drag pair and the click — `useRowSelect`'s handlers,
   *  the grid's own. */
  onDown: (e: React.MouseEvent) => void;
  onEnter: () => void;
  onPick: (e: React.MouseEvent) => void;
  /** A DOUBLE-CLICK GOES TO THE OFFER'S OWN CLUSTER in the list — picked
   *  and scrolled to, so what it holds is on the right (owner 2026-09).
   *  Space previews what is picked; the hover thumbnail says which picture
   *  a crop came from. */
  onOpen: () => void;
  onAdd: () => void;
  onNo: () => void;
}) {
  const [hover, setHover] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const rect = useAnchorRect(box, hover);
  const badge: React.CSSProperties = {
    position: "absolute", bottom: 5,
    fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
    padding: "1px 5px", borderRadius: "var(--r-1)",
    // The panel fill the ✚ and ✕ above it wear, not a black scrim: three
    // marks on one crop, drawn three ways, is three things to read where
    // there is one.
    background: "var(--panel)", color: "var(--muted-2)",
    pointerEvents: "none", display: "flex", alignItems: "center", gap: 3,
  };
  return (
    <div ref={box} className="hoverable" data-rowsel={String(near.face.id)}
         onMouseDown={(e) => { e.stopPropagation(); onDown(e); }}
         onMouseEnter={() => { setHover(true); onEnter(); }}
         onMouseLeave={() => setHover(false)}
         style={{ position: "relative", flex: "0 0 auto", width: size }}>
      <img src={api.faceCropUrl(near.face, 256)} alt="" loading="lazy"
           draggable={false}
           onClick={onPick}
           onDoubleClick={onOpen}
           title={t("Click to pick · double-click to go to its cluster")}
           style={{ width: size, height: size, objectFit: "cover",
                    boxSizing: "border-box", borderRadius: "var(--r-4)", display: "block",
                    cursor: "pointer",
                    border: "1px solid var(--border)",
                    // THE GRID'S RING: two pixels three pixels outside the
                    // crop, the same way a picked crop below says so.
                    outline: picked ? "2px solid var(--accent)" : "none",
                    outlineOffset: 3 }} />
      {/* HOW MANY CROPS THIS OFFER IS, bottom-left, where a cluster is one
          card — a cluster of one says nothing there. */}
      {near.count > 1 && (
        <span style={{ ...badge, left: 5 }}>
          <Icon name="group" size={11} />{near.count}
        </span>
      )}
      {/* HOW ALIKE, on the library setting's own scale — never a raw cosine,
          since two detectors' bands do not overlap and one number has to
          mean one thing. On the crop rather than under it: it is a fact
          about this face, and a line under the card put it where the grid
          below has nothing. */}
      <span style={{ ...badge, right: 5 }}>
        {Math.round(near.score * 100)}%
      </span>
      <IconButton icon="add" size={22} glyph={14} reveal="fixed" tone="accent" fill="panel" title={t("Add to this cluster")}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); onAdd(); }}
            style={{ position: "absolute", top: 6, left: 6 }} />
      <IconButton icon="close" size={22} glyph={14} reveal="fixed" fill="panel" title={t("Not this person")}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); onNo(); }}
            style={{ position: "absolute", top: 6, right: 6 }} />
      {/* The whole picture on hover, exactly as a crop in the grid below
          does it — the offers ARE that grid's first row. */}
      {hover && <FloatingFaceInPicture face={near.face} rect={rect} />}
    </div>
  );
}

/** HOW OLD SOMEBODY IS IN THIS PICTURE, asked of one crop.
 *
 *  A face can be two people — a character and the actor playing them — and
 *  each is an APPEARANCE with a date of its own, so the dialog is a row per
 *  person rather than one pair of fields. The fields themselves are the
 *  annotator's (`PeopleSection.WhenEditor`), which is also where the rule
 *  that saving CONFIRMS a guess is written: two editors for one field is
 *  how that rule ends up in one of them only. */
function FaceWhenOverlay({ face, t, onClose, onSaved }: {
  face: FaceRow;
  t: (s: string, vars?: Record<string, string>) => string;
  onClose: () => void;
  onSaved: () => void;
}) {
  return (
    <Overlay icon="schedule" title={t("Date or age")} width={420}
      subtitle={t("How old they are in this picture — dating a guess agrees with it.")}
      onClose={onClose}
      footer={<Button variant="ghost" onClick={onClose}>{t("Close")}</Button>}>
      <div style={{ padding: 18, display: "flex", flexDirection: "column",
                    gap: 14 }}>
        {face.subjects.map((sub) => (
          <div key={sub.id} style={{ display: "flex", flexDirection: "column",
                                     gap: 4 }}>
            <span style={{ fontSize: "var(--fs-3)", color: "var(--text)" }}>
              {sub.name || sub.tag}
            </span>
            <WhenEditor
              // `FaceSubject` is the same appearance the annotator edits,
              // flattened on the wire — its `id` IS the appearance's.
              appearance={{ id: sub.id, face_id: face.id,
                            when: { date: sub.when_date, age: sub.when_age },
                            when_derived: sub.when_derived,
                            assigned_by: sub.assigned_by,
                            match_score: sub.match_score }}
              since={sub.since_date}
              onDone={onSaved}
              t={t} />
          </div>
        ))}
      </div>
    </Overlay>
  );
}
