/** The faces half of the Subjects list — crops under the person they belong to.
 *
 * These used to be a sub-tab of their own, which put the two halves of one
 * question in two places: the Subjects list said who exists, the Faces list
 * said which crops were theirs, and neither could answer "is this face on the
 * right person" without switching. Under the row, a wrong face sits next to
 * twenty that belong, which is the only arrangement in which it is obvious.
 *
 * A cluster nobody has named has no row to sit under, so it becomes one.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { IconButton } from "../../shared/IconButton";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, FaceCluster, FaceRow, SubjectRow } from "../api";
import { bumpEdits } from "../invalidation";
import { Icon } from "../../shared/Icon";
import { useT, useTn } from "../i18n";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { useUI } from "../store";
import { TagAutocomplete } from "./TagAutocomplete";
import { useAnchorRect } from "../../shared/AnchoredDropdown";
import { PointerMenu, RowAction } from "./shared/RowMenu";
import { useUndoRun, type UndoRun } from "./shared/useUndoBar";
import { FacePreviewOverlay, FloatingFaceInPicture } from "./shared/FaceInPicture";
import { byRecent, rememberSubject, useRecentSubjects } from "../subjects/recent";

const CROP = 64;

/** How many crops a strip is sent per person. The list draws ONE row, and the
 *  widest row anybody can open is nowhere near this — so it is the cap that
 *  keeps a person in three hundred pictures from being three hundred crop URLs
 *  the page will never render, without ever being the reason a row looks short.
 *  What is left over is reached through the drawer, which loads that one
 *  subject in full. */
const PER_STRIP = 32;

/** Every face in the library, indexed the two ways the list reads it. */
export function useFaceIndex() {
  const qc = useQueryClient();
  // Offset 0 opts into the paged reply, whose `total` says how many people
  // exist — so the list can SAY it is showing the first thousand rather than
  // silently looking complete. (Paging further on scroll would have to reach
  // through the windowed list in TagsView; a bigger first page plus an honest
  // notice covers every real library for now.)
  const { data: named } = useQuery({
    queryKey: ["faces-named"], queryFn: () => api.namedFaces(1000, PER_STRIP, 0),
  });
  const { data: unnamed } = useQuery({
    queryKey: ["faces-unnamed"], queryFn: () => api.unnamedFaces(200),
  });
  const clusters = named?.clusters;

  // Keyed by the CLUSTER's subject, never by reading the face: a face named
  // twice over is emitted under BOTH people and still lists both in its own
  // row, so reading it would put it in one strip twice and the other never.
  const bySubject = useMemo(() => {
    const map = new Map<number, FaceRow[]>();
    for (const cluster of clusters ?? []) {
      const who = cluster.subject_id;
      if (who == null) continue;
      map.set(who, [...(map.get(who) ?? []), ...cluster.faces]);
    }
    return map;
  }, [clusters]);

  // HOW MANY OF EACH PERSON'S FACES ARE STILL A GUESS — the server's number,
  // for the same reason `total` is: the clusters carry a slice, and a guess
  // past the end of it is still a guess waiting.
  const guessesBySubject = useMemo(() => {
    const map = new Map<number, number>();
    for (const cluster of clusters ?? []) {
      const who = cluster.subject_id;
      if (who == null) continue;
      map.set(who, (map.get(who) ?? 0) + cluster.guesses);
    }
    return map;
  }, [clusters]);

  // How many they really have, which is what the strip's "+N" counts and what
  // decides whether the drawer has anything more to show.
  const totalBySubject = useMemo(() => {
    const map = new Map<number, number>();
    for (const cluster of clusters ?? []) {
      const who = cluster.subject_id;
      if (who == null) continue;
      map.set(who, (map.get(who) ?? 0) + cluster.total);
    }
    return map;
  }, [clusters]);

  //: WHAT A FACE VERB THAT TOUCHES NO TAG HAS TO SWEEP (owner 2026-09).
  //  The clusters, the strips and the people — and nothing else. Saying two
  //  crops are not one person, or that one is not a face, puts no tag on a
  //  picture and takes none off, so the library's tags, its items and the
  //  coalesced edit sweep were seven queries paying for a statement about
  //  one crop, several of them re-deriving the same clustering the write
  //  had just invalidated.
  const FACE_KEYS = ["faces-named", "faces-unnamed", "faces", "subjects"];
  /** `keepStrip` leaves the open cluster's offers alone, for a verb that
   *  ANSWERED with them: the ✕ on an offer returns the strip as it now is,
   *  and sweeping it here made the page ask for the same run again.
   *  `keepUnnamed` is the same for the unanswered queue: a merge and a
   *  naming answer with it, at the page's own size, and the caller has put
   *  that answer in the cache already. */
  const refreshFaces = (keepStrip = false, keepUnnamed = false) => {
    for (const key of FACE_KEYS) {
      if (keepUnnamed && key === "faces-unnamed") continue;
      qc.invalidateQueries({ queryKey: [key] });
    }
    if (!keepStrip) qc.invalidateQueries({ queryKey: ["faces-near"] });
  };
  const refresh = (keepUnnamed = false) => {
    refreshFaces(false, keepUnnamed);
    for (const key of ["tags", "items"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
    // Naming propagates: the server runs the suggestion pass over the
    // unnamed lookalikes there and then, so OTHER items gain amber faces
    // and pending tags — and dismissing/unnaming moves the pending counts
    // the sidebar's Pending rows show. The coalesced sweep covers both.
    bumpEdits();
  };

  // Every face by id, for the actions: a menu is handed a selection of ids
  // and has to know who each of them currently is.
  const byId = useMemo(() => {
    const map = new Map<number, FaceRow>();
    for (const c of [...(clusters ?? []), ...(unnamed ?? [])]) {
      for (const f of c.faces) map.set(f.id, f);
    }
    return map;
  }, [clusters, unnamed]);

  return {
    bySubject,
    totalBySubject,
    guessesBySubject,
    byId,
    unnamed: unnamed ?? [],
    // Counted by the SERVER over every named face. It cannot be summed here:
    // the clusters carry one row each now, and one credited face is listed
    // under the character and under the actor and is still one face.
    namedCount: named?.faces ?? 0,
    // How many people have faces at all vs. how many this page carries — when
    // they differ, the list is truncated and should say so.
    namedClusterTotal: named?.total ?? 0,
    namedClusterCount: named?.clusters.length ?? 0,
    unnamedCount: (unnamed ?? []).reduce((n, c) => n + c.faces.length, 0),
    loaded: named != null && unnamed != null,
    refresh,
    refreshFaces,
  };
}

const GAP = 7;


/** What the right-click menu on a crop offers, for ONE face or for a whole
 *  selection. Defined once: the wording is the same either way, and only the
 *  ids differ — a menu that said "not this person" while acting on nine would
 *  be a different bug in each place that spelled it out.
 *
 *  `unname` picks whether taking the name off is on offer at all: an unnamed
 *  cluster has no name to take.
 */

/** Whether a face is on somebody a MODEL guessed and nobody has agreed with.
 *  One definition: the crop's amber border, the menu's two answers and the
 *  drawer's buttons all ask the same question, and three spellings of it is
 *  three chances to disagree. */
export const isGuessed = (f: FaceRow) =>
  f.subjects.some((s) => s.assigned_by === "suggested");

/** Every still-pending assignment on these faces, as (appearance, face,
 *  subject) — accepting reads the first, rejecting the last two. */
const guesses = (faces: FaceRow[]) => faces.flatMap(
  (f) => f.subjects.filter((s) => s.assigned_by === "suggested")
    .map((s) => ({ appearance: s.id, face: f.id, subject: s.subject_id })));

export function faceMenuActions(
  t: (s: string) => string,
  faces: FaceRow[],
  unname: boolean,
  /** Something changed — reload. `kept` says the faces this acted on are still
   *  in the same list under the same person, which is true of ACCEPTING and of
   *  nothing else here: agreeing with a guess only clears its pending flag,
   *  while rejecting, unnaming, dismissing and deleting all take the crop out
   *  of the strip it was in. The caller uses it to decide whether the SELECTION
   *  survives — dropping it after an accept meant answering a row of guesses
   *  one crop at a time, re-picking the rest after every yes. */
  onChanged: (kept?: boolean) => void,
  /** Show the whole picture with this face outlined. Only offered when the
   *  menu is about ONE face — with nine picked there is no "that picture". */
  onPreview?: () => void,
  /** Take me to the picture in the Library. Also one face only, for the same
   *  reason: nine crops are nine different pictures. */
  onShowInLibrary?: () => void,
): RowAction[] {
  const ids = faces.map((f) => f.id);
  const n = ids.length;
  const many = n > 1;
  // `() => onChanged()` and never `.then(onChanged)`: Promise.all resolves to
  // an ARRAY, which would arrive as a truthy `kept` and keep a selection of
  // crops that are no longer there.
  const all = (body: Parameters<typeof api.updateFace>[1]) => () => {
    void Promise.all(ids.map((id) => api.updateFace(id, body)))
      .then(() => onChanged());
  };
  // The two ways of LOOKING at the picture, then a rule, then the ways of
  // changing it. They answer different questions — "which one is this?" is
  // over in a second, "where does this belong?" leaves you somewhere else —
  // and neither is undoable, unlike everything under the line.
  //
  // NO HINTS (owner 2026-09). Every verb here is a short sentence about
  // crops on screen, and a muted second line under each of five of them was
  // a paragraph in front of a menu somebody opens to answer one question.
  // HOW MANY the verb is about rides as `trailing` — the count at the item's
  // right edge — rather than in the label, so the same actions read as
  // buttons in the Faces bar with the number as secondary text.
  const look: RowAction[] = n === 1 ? [
    ...(onShowInLibrary ? [{
      icon: "grid_view",
      label: t("Show in library"),
      onClick: onShowInLibrary,
    }] : []),
    ...(onPreview ? [{
      icon: "visibility",
      label: t("Preview"),
      onClick: onPreview,
    }] : []),
  ] : [];
  const first = { separated: look.length > 0 };
  // The two answers to a guess, and only where there is one to answer. They
  // come FIRST among the changes: a strip of amber crops is a list of
  // questions, and agreeing is what most of them want.
  const pending = guesses(faces);
  const answers: RowAction[] = pending.length === 0 ? [] : [
    {
      ...first,
      icon: "check",
      label: t("Accept the guess"), short: t("Accept"),
      ...(pending.length > 1 ? { trailing: String(pending.length) } : {}),
      onClick: () => {
        // KEPT: the crops do not move — the guess simply stops being one — so
        // the selection stays and the next answer can be given straight away.
        void Promise.all(pending.map(
          (g) => api.editAppearance(g.appearance, { confirm: true })))
          .then(() => onChanged(true));
      },
    },
    {
      icon: "person_off",
      label: t("Reject the guess"), short: t("Reject"),
      ...(pending.length > 1 ? { trailing: String(pending.length) } : {}),
      onClick: () => {
        void Promise.all(pending.map(
          (g) => api.unnameFace(g.face, g.subject))).then(() => onChanged());
      },
    },
  ];
  // "Not this person" takes EVERY name off; "Reject the guess" takes off the
  // guessed ones. When those are the same set the two entries are one action
  // written twice, so only the more precise wording is offered.
  const named = faces.reduce((n, f) => n + f.subjects.length, 0);
  const sameThing = pending.length > 0 && pending.length === named;
  return [
    ...look,
    ...answers,
    ...(unname && !sameThing ? [{
      ...(answers.length ? {} : first),
      icon: "person_off",
      label: t("Not this person"),
      ...(many ? { trailing: String(n) } : {}),
      onClick: () => {
        // Every name on every picked crop: from a strip, "not this person" is
        // about whoever is on it, and a face may be more than one.
        void Promise.all(faces.flatMap((f) => f.subjects.map(
          (sub) => api.unnameFace(f.id, sub.subject_id))))
          .then(() => onChanged());
      },
    }] : []),
    {
      ...((unname && !sameThing) || answers.length ? {} : first),
      icon: "face_retouching_off",
      label: t("Not a face"),
      ...(many ? { trailing: String(n) } : {}),
      onClick: all({ dismissed: true }),
    },
    {
      icon: "delete",
      label: many ? t("Delete these faces") : t("Delete this face"),
      short: t("Delete"),
      ...(many ? { trailing: String(n) } : {}),
      danger: true,
      onClick: () => {
        void Promise.all(ids.map((id) => api.deleteFace(id)))
          .then(() => onChanged());
      },
    },
  ];
}

/** THE VERBS THAT CHANGE SOMETHING, wrapped so the way back is offered.
 *  The two ways of LOOKING at the picture are not among them: they write
 *  nothing, and a toast reading "Preview · Undo" is a button aimed at
 *  nothing. With no bar above (the strips in the annotator) the runner is a
 *  passthrough and the action simply happens. */
const LOOKING = new Set(["grid_view", "visibility"]);

export function offerBack(a: RowAction, run: UndoRun): RowAction {
  if (LOOKING.has(a.icon ?? "")) return a;
  const was = a.onClick;
  return { ...a, onClick: () => void run(a.short ?? a.label,
                                         async () => { was?.(); }) };
}

export function FaceThumb({ face, unname, onChanged, picked, onPick, onDown, onEnter,
                    onMenu, size }: {
  face: FaceRow;
  unname: boolean;
  /** The crop's edge, where the caller lays them out itself — the Faces
   *  tab's grid sizes its own cells (S/M/L) and hands the answer down.
   *  Absent is the strips' own fixed crop. */
  size?: number;
  onChanged: () => void;
  picked?: boolean;
  /** Given, a click PICKS the face instead of opening its picture — sorting
   *  faces out is what this list is for, and going to the item was a trip away
   *  from the work. Double-click still goes. */
  onPick?: (e: React.MouseEvent) => void;
  /** The press-and-drag pair: pressing arms a paint, entering another crop
   *  while the button is down applies it. Same gesture as the rows above. */
  onDown?: (id: number, e: React.MouseEvent) => void;
  onEnter?: (id: number) => void;
  onMenu?: (face: FaceRow, at: { x: number; y: number }) => void;
}) {
  const t = useT();
  const undoRun = useUndoRun();
  // Clicking a crop goes TO the picture rather than previewing it here. From a
  // list of everybody the question is which picture this is — and a preview
  // that has to be closed again answers it once per crop, where the Library
  // leaves you where the rest of the work happens.
  const setSearch = useUI((s) => s.setSearch);
  const setView = useUI((s) => s.setView);
  const showAllItems = useUI((s) => s.showAllItems);
  const setSelectedItems = useUI((s) => s.setSelectedItems);
  const openItem = () => {
    showAllItems();
    // The uid is intrinsic METADATA, so it is `INFO:id=…` — a bare `id:` parses
    // as a tag named "id" and quietly matches nothing. This narrows to the one
    // picture rather than selecting something buried in a listing that would
    // then have to be scrolled to.
    setSearch(face.item_uid ? `INFO:id=${face.item_uid}` : "");
    setSelectedItems([face.item_id]);
    setView("library");
  };
  // The whole picture, on hover. Twenty crops of the same haircut are only
  // tellable apart by where each came from, and a click into Quick Look to find
  // that out is a click back again for every one of them.
  const [hover, setHover] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [preview, setPreview] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const rect = useAnchorRect(box, hover);
  const guessed = isGuessed(face);
  return (
    <div ref={box} style={{ position: "relative" }}
      // What the list's press-and-drag looks for: still over a crop means the
      // gesture is painting a selection, off them means it is carrying one.
      data-face-crop=""
      onClick={(e) => e.stopPropagation()}
      // The press belongs to the crop, not to the row behind it — without this
      // the row's own paint arms too, and dragging across two people selected
      // both of them as well as their faces.
      onMouseDown={(e) => { e.stopPropagation(); onDown?.(face.id, e); }}
      onMouseEnter={() => { setHover(true); onEnter?.(face.id); }}
      onContextMenu={(e) => {
        e.preventDefault(); e.stopPropagation();
        // The LIST opens the menu when it owns a selection — the actions may
        // apply to nine crops in three strips, which a thumb cannot know.
        if (onMenu) onMenu(face, { x: e.clientX, y: e.clientY });
        else setMenu({ x: e.clientX, y: e.clientY });
      }}
      onMouseLeave={() => setHover(false)}>
      <img
        src={api.faceCropUrl(face, 224)}
        alt=""
        // Off-screen crops (a long drawer, a tall list) fetch only as they
        // scroll into view.
        loading="lazy"
        // The browser's own image drag fires the moment the pointer moves,
        // which is the middle of a paint or a carry — both of ours are mouse
        // events, and this is what keeps the two from running at once.
        draggable={false}
        onClick={onPick ?? openItem}
        onDoubleClick={onPick ? openItem : undefined}
        title={(onPick
          ? t("Click to pick this face · double-click to open the picture")
          : t("Open this item in the Library"))
          + (guessed ? `\n${t("A guess nobody has agreed with yet")}` : "")}
        // Never dimmed by confidence: a translucent crop reads as "this image
        // is faded", not "the detector was unsure", and it makes the one thing
        // the row is for harder to see. The score is words elsewhere.
        style={{
          display: "block", width: size ?? CROP, height: size ?? CROP,
          objectFit: "cover",
          // The border is INSIDE the box, or every crop is CROP + 2 wide and
          // the row fits one fewer than the measurement says — which is what
          // wrapped the chip onto a line of its own.
          boxSizing: "border-box",
          borderRadius: "var(--r-4)", cursor: "pointer",
          // THE CLUSTER CARD'S RING, DRAWN THE SAME WAY (owner 2026-09): two
          // pixels three pixels OUTSIDE the crop, accent for picked and
          // amber for a name nobody has agreed with yet — the colour every
          // guess in this app wears. It used to be drawn INSIDE the crop at
          // two different widths, so the grid of clusters and the grid of
          // one cluster's crops said "picked" in two visibly different ways
          // one double-click apart. The grid's gap leaves room for it.
          border: "1px solid var(--border)",
          outline: picked ? "2px solid var(--accent)"
            : guessed ? "2px solid var(--yellow)" : "none",
          outlineOffset: 3,
        }}
      />
      {hover && !menu && <FloatingFaceInPicture face={face} rect={rect} />}
      {/* A named face has no ✕. Under somebody's name a corner cross reads as
          "delete", and what it did was take the name off — the two most
          destructive readings of one 12 px glyph. An unnamed crop keeps it,
          where it means only "not a face". Everything either one can do is in
          the right-click menu, with words.
          Nor a face somebody DREW: dismissing stops a detector offering the
          same false positive again, and nothing ever offered this one. */}
      {!unname && face.models.length > 0 && (
        <IconButton icon="face_retouching_off" size={18} reveal="hover" tone="danger" bordered fill="panel" shape="round"
          onClick={() => void undoRun(t("Not a face"), () =>
            api.updateFace(face.id, { dismissed: true }).then(onChanged))}
          title={t("Not a face — stop offering it")} style={{ position: "absolute", top: -5, right: -5 }} />
      )}
      {menu && (
        <PointerMenu at={menu} onClose={() => setMenu(null)}
          actions={faceMenuActions(t, [face], unname, onChanged,
                                   () => setPreview(true), openItem)
                     .map((a) => offerBack(a, undoRun))} />
      )}
      {preview && (
        <FacePreviewOverlay faces={[face]} title={face.subjects[0]?.name || t("Face")}
          onClose={() => setPreview(false)} />
      )}
    </div>
  );
}

/** WHERE THESE CROPS GO — the answer to "this is someone else" (owner
 *  2026-09).
 *
 *  It used to be one verb with one answer: split them onto a new person with
 *  no name, which is the right answer when you do not yet know who they are
 *  and the wrong one the rest of the time — the crops left the cluster and
 *  landed somewhere nobody was looking. The verb ASKS now, over the same
 *  field the namer uses: a person already in the catalog, a name nobody has
 *  used yet, somebody with no name at all, or nobody yet.
 *
 *  Every answer is one of the writes that already existed; what is new is
 *  that the question is asked. They all go through the runner, so the toast
 *  offers the way back.
 */
export function MoveFacesOverlay({ faces, subjects, onClose, onMoved }: {
  faces: FaceRow[];
  subjects: SubjectRow[];
  onClose: () => void;
  /** Written — reload. */
  onMoved: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const undoRun = useUndoRun();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const recent = useRecentSubjects();
  const ids = faces.map((f) => f.id);
  //: WHOEVER THEY ARE ON NOW is not an answer — moving a crop to the person
  //  it is already credited to writes nothing and reads as the dialog
  //  ignoring the press.
  const already = new Set(faces.flatMap((f) => f.subjects.map((x) => x.subject_id)));
  const options = useMemo(
    () => byRecent(subjects
      .filter((s) => (s.display_name || s.tag) && !already.has(s.id))
      .map((s) => ({ name: s.display_name || s.tag, comment: s.comment,
                     uses: s.items })), recent),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subjects, recent, faces]);

  const run = async (label: string, write: () => Promise<unknown>) => {
    setBusy(true);
    await undoRun(label, write);
    onMoved();
    onClose();
  };
  const toName = (text: string) => {
    const wanted = text.trim();
    if (!wanted) return;
    const existing = subjects.find(
      (s) => (s.display_name || s.tag).toLowerCase() === wanted.toLowerCase());
    rememberSubject(wanted);
    void run(`${t("Moved to")} ${wanted}`, () => api.nameFaceCluster({
      face_ids: ids,
      ...(existing ? { subject_id: existing.id } : { display_name: wanted }),
    }));
  };

  return (
    <Overlay
      icon="call_split"
      title={tn({ one: "Move this crop", other: "Move {n} crops" }, ids.length)}
      subtitle={t("Who are they? Leave it open if you do not know yet.")}
      width={420}
      onClose={onClose}
      footer={<Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>}
    >
      <div style={{ padding: 18, opacity: busy ? 0.6 : 1,
                    pointerEvents: busy ? "none" : undefined }}>
        <TagAutocomplete
          value={typed}
          onChange={setTyped}
          onCommit={toName}
          onCancel={onClose}
          suggestions={options}
          placeholder={t("Who is this?")}
          freeText
          autoFocus
          minWidth={320}
        />
        {/* THE TWO ANSWERS NO NAME CAN STAND FOR, as BUTTONS rather than rows
            of the suggest list: a list that only opens once something is
            typed would have hidden both behind a keystroke, and in a dialog
            whose whole question is "which of these three" that is the one
            thing it may not do. */}
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <AnswerButton icon="person_off" label={t("Unnamed")}
            hint={t("somebody with no name")}
            onClick={() => void run(t("Somebody with no name"),
                                    () => api.setClusterUnnamed(ids))} />
          <AnswerButton icon="help" label={t("Nobody yet")}
            hint={t("a cluster of their own, still waiting")}
            onClick={() => void run(t("Someone else"),
                                    () => api.splitFaces(ids))} />
        </div>
      </div>
    </Overlay>
  );
}


/** One of the answers beside the name field: what it is, and one quiet line
 *  saying what it means. */
function AnswerButton({ icon, label, hint, onClick }: {
  icon: string; label: string; hint: string; onClick: () => void;
}) {
  return (
    <button onClick={onClick} title={hint}
      style={{ flex: 1, display: "flex", flexDirection: "column",
               alignItems: "flex-start", gap: 2, padding: "9px 11px",
               borderRadius: "var(--r-5)", cursor: "pointer", textAlign: "left",
               border: "1px solid var(--border-strong)",
               background: "var(--panel-2)", font: "inherit" }}>
      <span style={{ display: "flex", alignItems: "center", gap: 6,
                     fontSize: "var(--fs-3)", color: "var(--text)" }}>
        <Icon name={icon} size={15} color="var(--muted-2)" />
        {label}
      </span>
      <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>{hint}</span>
    </button>
  );
}

/** "Name all 14" — the point of the unnamed list. Naming one picture at a time
 *  is what kills face tagging in other tools; this turns "this person, fourteen
 *  times" into a tag on fourteen items, in one action and one event. */
export function ClusterNamer({ cluster, subjects, onNamed, onClose, trigger,
                              width, openSignal }: {
  cluster: FaceCluster;
  subjects: SubjectRow[];
  onNamed: () => void;
  /** THE FIELD IS SHUT — answered or abandoned. For a host that has put the
   *  field somewhere of its own and has to take it back out again: the
   *  cluster list opens it IN the row, and Escape there has to give the row
   *  its name and its counts back. (A host that only ever draws a trigger
   *  needs none of this: the trigger comes back by itself.) */
  onClose?: () => void;
  /** A BUMPED COUNTER IS A REQUEST TO OPEN THE FIELD — what the cluster
   *  list's own menu row presses, since a menu cannot hold an autocomplete
   *  and two dialogs asking "who is this?" is how two dialogs drift. Zero is
   *  "nobody has asked", so a plain mount opens nothing; any other value
   *  opens, INCLUDING on a fresh mount — the row's menu picks the cluster
   *  and asks in one event, and the asking must survive the mount that
   *  picking causes. */
  openSignal?: number;
  /** WHAT THE CLOSED STATE LOOKS LIKE, where a caller wants it to be
   *  something other than a button — the Faces grid's card draws the word
   *  "Unnamed" where a named cluster draws its name, and pressing THAT is
   *  what asks who this is. A blue button on every unnamed card (which is
   *  most of them) made a wall of buttons out of a wall of faces. */
  trigger?: (open: () => void) => React.ReactNode;
  /** The open field's width. A card is narrower than the default. */
  width?: number | string;
}) {
  const t = useT();
  const undoRun = useUndoRun();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  useEffect(() => { if (openSignal) setOpen(true); }, [openSignal]);

  // Most recently named first — see `subjects/recent.ts`.
  const recent = useRecentSubjects();
  const options = useMemo(
    () => byRecent(subjects.filter((s) => s.display_name || s.tag)
      .map((s) => ({ name: s.display_name || s.tag, comment: s.comment,
                     uses: s.items })), recent),
    [subjects, recent]
  );

  const name = async (text: string) => {
    const wanted = text.trim();
    if (!wanted) return;
    setOpen(false);
    setTyped("");
    onClose?.();
    const existing = subjects.find(
      (s) => (s.display_name || s.tag).toLowerCase() === wanted.toLowerCase());
    await undoRun(`${t("Named")} ${wanted}`, () => api.nameFaceCluster({
      face_ids: cluster.faces.map((f) => f.id),
      ...(existing ? { subject_id: existing.id } : { display_name: wanted }),
    }));
    rememberSubject(wanted);
    onNamed();
  };

  /** THE OTHER ANSWER. "Who is this" has one that no name in the catalog
   *  can stand for — nobody in particular, a background character, an extra
   *  — and inventing `unknown_person_3` for each of them puts junk in the
   *  catalog and in every prompt an export writes. So the list offers it as
   *  a row of its own, where the other answers are and where the keyboard
   *  already is. */
  const markUnnamed = async () => {
    setOpen(false);
    setTyped("");
    onClose?.();
    await undoRun(t("Somebody with no name"),
                  () => api.setClusterUnnamed(cluster.faces.map((f) => f.id)));
    onNamed();
  };

  if (open) {
    return (
      <div style={{ width: width ?? 240 }} onClick={(e) => e.stopPropagation()}>
        <TagAutocomplete
          value={typed}
          onChange={setTyped}
          onCommit={(text) => void name(text)}
          onCancel={() => { setOpen(false); setTyped(""); onClose?.(); }}
          suggestions={options}
          // EACH CLUSTER ANSWERED THIS WAY IS ITS OWN PERSON: the mark is a
          // flag on a nameless subject of its own, never one shared
          // "Unnamed" identity, so two background characters stay two.
          actions={[{ id: "unnamed", label: t("Unnamed"), icon: "person_off",
                      hint: t("somebody with no name") }]}
          onAction={(id) => { if (id === "unnamed") void markUnnamed(); }}
          placeholder={t("Who is this?")}
          freeText
          autoFocus
          minWidth={240}
        />
      </div>
    );
  }
  const start = () => { setOpen(true); setTyped(""); };
  if (trigger) return <>{trigger(start)}</>;
  return (
    <button
      onClick={(e) => { e.stopPropagation(); start(); }}
      style={{
        display: "flex", alignItems: "center", gap: 5, height: 26,
        padding: "0 10px", borderRadius: "var(--r-3)", cursor: "pointer",
        border: "1px solid var(--accent)", background: "var(--accent-dim)",
        color: "var(--accent)", fontFamily: "inherit", fontSize: "var(--fs-2)",
      }}
    >
      <Icon name="person_add" size={14} />
      {cluster.grouped ? `${t("Name all")} ${cluster.faces.length}` : t("Name")}
    </button>
  );
}
