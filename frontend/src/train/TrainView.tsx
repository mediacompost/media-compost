// The Train tab: GPU stats + sectioned job list on the left (Running / Queued
// / Finished), job detail or editor on the right.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { dropHalf } from "../shared/useDragRow";
import { storage } from "../shared/storage";
import { SectionHeading } from "../shared/SectionHeading";
import { Button } from "../shared/Button";
import { EmptyState } from "../shared/EmptyState";
import { useEscapeClears } from "../shared/escapeClears";
import { pickNext } from "../shared/pickList";
import { Select } from "../shared/Select";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, TrainingJobSummary } from "./api";
import { Icon } from "../shared/Icon";
import { confirm } from "../shared/ConfirmModal";
import { useT } from "./i18n";
import { GpuStatsBar } from "./GpuStatsBar";
import { TrainSetupBanner } from "./TrainSetupBanner";
import { TrainJobCard } from "./TrainJobCard";
import { TrainJobDetail } from "./TrainJobDetail";
import { SidebarSplit } from "../shared/SidebarSplit";
import { TrainJobEditor } from "./TrainJobEditor";
import { invalidateJob } from "./invalidate";
import { anyJobActive, errText } from "./util";
import { SELECTION_BAR_GAP, SELECTION_BAR_H, SelectionBar }
  from "../shared/SelectionBar";

function SectionHeader({ label, count, trailing }: {
  label: string; count: number; trailing?: React.ReactNode;
}) {
  return (
    <SectionHeading style={{ display: "flex", alignItems: "center", gap: 7, padding: "12px 2px 6px" }}>
      {label}
      <span style={{
        minWidth: 17, height: 17, padding: "0 5px", borderRadius: "var(--r-5)",
        background: "var(--panel-3)", color: "var(--text-2)",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        fontSize: "var(--fs-1)", letterSpacing: 0,
      }}>
        {count}
      </span>
      {trailing && <span style={{ marginLeft: "auto" }}>{trailing}</span>}
    </SectionHeading>
  );
}

/** HOW THE DRAFTS ARE ORDERED, remembered per browser. `date` is what the
 *  section always did — newest first — and `manual` is the order somebody
 *  drags them into, which the queue above has always had.
 *
 *  It is stored server-side in `queued_at`, the same stamp the queue is
 *  ordered by: `reorder_queue` covers every WAITING status, so a draft has
 *  carried a position all along and nothing here is a new field. */
/** On the GPU right now — never removed, and dropped from any list handed
 *  to `removeJobs`. */
const RUNNING = ["running", "pausing"];

type HeldSort = "date" | "manual";
const HELD_SORT_KEY = "mc.train.draftsOrder";
/** Where the job list's width is remembered (`SidebarSplit`). */
const SIDEBAR_KEY = "mc.train.sidebarW";

function loadHeldSort(): HeldSort {
  try {
    return storage.get(HELD_SORT_KEY) === "manual" ? "manual" : "date";
  } catch { return "date"; }
}

/** The Drafts header's order control. A `<select>` rather than a menu: two
 *  states, named, in a header that is 11 px of uppercase — the shape the
 *  train tab's other inline choices already use. */
function HeldSortSelect({ value, onChange }: {
  value: HeldSort; onChange: (v: HeldSort) => void;
}) {
  const t = useT();
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 3,
                   color: "var(--text-2)" }}
          title={t("How the drafts below are ordered")}>
      <Select bare
        value={value}
        onChange={(v) => onChange(v as HeldSort)}
        style={{ fontSize: "var(--fs-1)", fontWeight: 600, letterSpacing: "0.05em",
                 textTransform: "uppercase" }}>
        <option value="date">{t("Newest first")}</option>
        <option value="manual">{t("Manual order")}</option>
      </Select>
      <Icon name="expand_more" size={14} color="var(--muted-2)" />
    </span>
  );
}

/** The pill both section headers use. */
function queuePill(accent: boolean): React.CSSProperties {
  return {
    display: "inline-flex", alignItems: "center", gap: 4,
    height: 22, padding: "0 9px 0 6px", borderRadius: 11,
    border: accent ? "none" : "1px solid var(--border-strong)",
    background: accent ? "var(--accent)" : "transparent",
    color: accent ? "var(--on-accent)" : "var(--text-2)",
    fontSize: "var(--fs-1)", fontWeight: 600, letterSpacing: "0.05em",
    cursor: "pointer", fontFamily: "inherit", textTransform: "uppercase",
  };
}

/** STOP, in the RUNNING section's header — beside the thing it stops.
 *  It used to share the Up next header with Run, which put the control for
 *  what is happening NOW on the list of what happens NEXT, and made one
 *  corner of the sidebar mean two different things depending on the state. */
function PauseControl({ running }: { running: TrainingJobSummary[] }) {
  const t = useT();
  const qc = useQueryClient();
  if (!running.length) return null;
  const pauseAll = () =>
    void Promise.allSettled(running.map((j) => api.trainPause(j.uid)))
      .then(() => qc.invalidateQueries({ queryKey: ["train-jobs"] }));
  return (
    <button onClick={pauseAll} style={queuePill(false)}
      title={t("Pause — checkpoints and stops the running job; the queue stops with it.")}>
      <Icon name="pause" size={14} />
      {t("Pause")}
    </button>
  );
}

/** RUN, in the Up next header: queueing a job never starts it, so this is what
 *  sets the queue working. Absent while anything runs — the queue is already
 *  going, and the way to stop it is in the Running header above. */
function RunControl({ running, queued }: {
  running: number; queued: number;
}) {
  const t = useT();
  const qc = useQueryClient();
  if (running > 0 || !queued) return null;
  return (
    <button style={queuePill(true)}
      onClick={() => void api.trainQueueRun()
        .then(() => qc.invalidateQueries({ queryKey: ["train-jobs"] }))}
      title={t("Run the queue — jobs start in this order, one per GPU, until it is empty.")}>
      <Icon name="play_arrow" size={14} />
      {t("Run")}
    </button>
  );
}

/** WHAT ACCEPTS A DROP: a canceled `dragenter`/`dragover` with the effect
 *  named. Both halves matter — canceling `dragover` alone is enough in
 *  Chromium and is not the rule everywhere, and a target that never names
 *  `dropEffect` leaves the cursor saying "no drop" over a target that would
 *  in fact take it (the group tree's rule, one sidebar along). */
const accept = (on: boolean) => (e: React.DragEvent) => {
  if (!on) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
};

/** THE WHOLE SECTION TAKES THE DROP — its heading and the gaps around its
 *  panel, not only the rows.
 *
 * The rows were the only drop target, so a drag aimed at "Drafts" was
 * refused everywhere except directly on top of another job: over the
 * heading, in the margin above the panel and past its last row the cursor
 * said no, and a section that already held rows drew no feedback anywhere
 * even where it would have taken the drop. That reads as a drag that cannot
 * be made at all — which is how it was reported. A row still answers first
 * (it is the one that knows the slot); this is what everything around it
 * means.
 *
 * The outline is set ONCE per drag, off `hint` — never per pointer sample,
 * which is the sidebar's rule and for its reason: a state write per
 * `dragover` is a render per sample, and WebKit fires those continuously
 * even under a stationary pointer.
 */
function DropSection({ active, hint, onDrop, children }: {
  /** Whether a drop here would mean anything. */
  active: boolean;
  /** Draw the dashed accent — an INCOMING drag only, so reordering inside a
   *  section does not wrap it in a box that says nothing. */
  hint?: boolean;
  onDrop: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      onDragEnter={accept(active)}
      onDragOver={accept(active)}
      onDrop={active ? (e) => { e.preventDefault(); onDrop(); } : undefined}
      style={{
        borderRadius: "var(--r-7)",
        outline: hint ? "1px dashed var(--accent)" : undefined,
        outlineOffset: 5,
      }}
    >
      {children}
    </div>
  );
}

/** A drag in progress, shared across the panels: rows can move between the
 *  Next up and Jobs sections, not only within one. */
type JobDrag = {
  uid: string | null;
  start: (uid: string) => void;
  end: () => void;
};

function JobPanel({ jobs, drag, onDropAt, insertable,
                    dragTitle, evalBusy, queueActive, picked, onPick,
                    onRefused }: {
  jobs: TrainingJobSummary[];
  /** An Evaluate generation holds the GPU, so queued rows are waiting on it. */
  evalBusy?: boolean;
  /** Whether the queue is working — the row's start button says which of its
   *  two jobs it is about to do (start the queue, or preempt what runs). */
  queueActive?: boolean;
  /** Present when this panel's rows can be dragged (handle-only). */
  drag?: JobDrag;
  /** A dragged job dropped on this panel lands at this insertion index;
   *  panels without an order pass -1 (no insertion line is drawn). */
  onDropAt?: (index: number) => void;
  insertable?: boolean;
  dragTitle?: string;
  /** THE selection — what a bulk action would act on, and (at exactly one
   *  row) what the detail pane shows. */
  picked?: string[];
  onPick?: (uid: string, mods: { meta: boolean; shift: boolean }) => void;
  /** What the server said when a row's button was refused. */
  onRefused?: (message: string) => void;
}) {
  // Same drag pattern as the sequence-member list: only the handle starts a
  // drag, an insertion line marks the slot, and the drop reads its own
  // coordinates rather than the hover state.
  const [dropAt, setDropAt] = useState<number | null>(null);
  useEffect(() => {
    if (!drag?.uid) setDropAt(null);
  }, [drag?.uid]);

  return (
    <div style={{
      background: "var(--panel)", border: "1px solid var(--border)",
      borderRadius: "var(--r-7)", overflow: "hidden",
    }}>
      {jobs.map((j, i) => (
        <div
          key={j.uid}
          style={{
            ...(i === jobs.length - 1 ? { marginBottom: -1 } : undefined),
            position: "relative",
          }}
          onDragEnter={drag && onDropAt ? accept(!!drag.uid) : undefined}
          onDragOver={drag && onDropAt ? (e) => {
            if (!drag.uid) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            if (!insertable) return;
            setDropAt(i + (dropHalf(e) === "after" ? 1 : 0));
          } : undefined}
          onDrop={drag && onDropAt ? (e) => {
            if (!drag.uid) return;
            e.preventDefault();
            // The whole SECTION takes drops too (`DropSection`), and this row
            // is inside it — so the precise answer keeps the event.
            e.stopPropagation();
            const half = dropHalf(e);
            setDropAt(null);
            onDropAt(insertable ? i + (half === "after" ? 1 : 0) : -1);
          } : undefined}
        >
          {dropAt != null && (dropAt === i || dropAt === i + 1) && (
            <div style={{
              position: "absolute", left: 8, right: 8, height: 2,
              background: "var(--accent)", borderRadius: 1, zIndex: 2,
              top: dropAt === i ? -1 : undefined,
              bottom: dropAt === i + 1 ? -1 : undefined,
            }} />
          )}
          <TrainJobCard job={j} selected={!!picked?.includes(j.uid)}
            evalBusy={evalBusy}
            queueActive={queueActive}
            onRefused={onRefused}
            onSelect={(mods) => onPick?.(j.uid, mods)}
            dragHandle={drag ? {
              title: dragTitle,
              onDragStart: () => drag.start(j.uid),
              onDragEnd: () => { drag.end(); setDropAt(null); },
            } : undefined} />
        </div>
      ))}
    </div>
  );
}


export function TrainView({ jobUid, onSelectJob }: {
  /** The selected job, owned by the APP's store (it is routing state — the
   *  `?job=` parameter — and this package may not import the app's store, so
   *  it arrives through the lazy entry as props). */
  jobUid: string | null;
  onSelectJob: (uid: string | null) => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  // null = closed; "" = create new; uid = edit that job.
  const [editorFor, setEditorFor] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["train-jobs"],
    queryFn: api.trainJobs,
    refetchInterval: (q) => (anyJobActive(q.state.data?.jobs) ? 1500 : false),
  });
  const jobs = data?.jobs ?? [];
  // While something is waiting, WHY it is waiting can change under us — the
  // generation holding the GPU finishes and the job starts — so this follows
  // the queue rather than sitting on whatever was true when the tab opened.
  const anyQueued = jobs.some((j) => j.status === "queued");
  const { data: status } = useQuery({
    queryKey: ["train-status"], queryFn: api.trainStatus,
    refetchInterval: anyQueued ? 4000 : false,
  });
  // The Evaluate tab holds the GPU while it renders, and a training job
  // pinned to that device waits rather than starting.
  const evalBusy = !!status?.evaluating_device;

  const refreshJobs = () =>
    qc.invalidateQueries({ queryKey: ["train-jobs"] });

  /** WHY THE LAST ACTION DID NOTHING. Every button on a job row and every
   *  drag between the sections can be refused for a reason only the server
   *  knows — a model that still has to be downloaded while downloads are
   *  switched off, a device already busy, a config that cannot be queued —
   *  and all of it was being thrown away, so a refusal was indistinguishable
   *  from a dead control. One line for the whole list rather than a message
   *  per row: a 34 px row has nowhere to put a sentence, and the drag has no
   *  row of its own to put it in. */
  const [refused, setRefused] = useState("");

  const [heldSort, setHeldSort] = useState<HeldSort>(loadHeldSort);
  const sections = useMemo(() => {
    const running = jobs.filter((j) => j.status === "running" || j.status === "pausing");
    // Queued = the jobs that WILL run, in this order; paused and draft jobs
    // sit on hold in their own section until they are put in. That is what
    // makes the queue a plan rather than a pile: not every unfinished job is
    // meant to run, and the ones that are can all be dragged.
    const queued = jobs.filter((j) => j.status === "queued");
    const held = jobs.filter((j) => j.status === "draft" || j.status === "paused");
    const finished = jobs.filter((j) => ["completed", "failed", "canceled"]
      .includes(j.status));
    queued.sort((a, b) =>
      (a.queued_at ?? a.created_at ?? 0) - (b.queued_at ?? b.created_at ?? 0));
    // Newest first, or the order somebody dragged them into — which is
    // `queued_at`, the stamp the queue above is ordered by. A draft that has
    // never been queued has none, so it falls back to when it was made;
    // switching TO manual stamps the list as it stands, so the order never
    // reshuffles into one nobody chose.
    held.sort(heldSort === "manual"
      ? (a, b) => ((a.queued_at ?? a.created_at ?? 0)
                   - (b.queued_at ?? b.created_at ?? 0))
      : (a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
    finished.sort((a, b) => (b.finished_at ?? 0) - (a.finished_at ?? 0));
    return { running, queued, held, finished };
  }, [jobs, heldSort]);

  // THE SELECTION, and there is only one. It used to be two — `picked` for
  // what a bulk action would act on, and the `?job=` route parameter for what
  // the detail pane showed — which is the library sidebar's split and does not
  // survive being tried: the rows are the same rows and the gesture is the
  // same gesture, so ⌘-clicking a second job left the pane showing the first
  // and a bar counting two, with two different tints saying so.
  //
  // So the pane follows the selection: exactly one row shows that job,
  // anything else (none, or several) shows a placeholder. The route is the
  // OUTPUT — the single selected uid, or nothing — which keeps `?job=`
  // reloadable and linkable while the browser's Back button still lands on a
  // job. The gestures are the library's: a plain click replaces, ⌘/Ctrl adds
  // and removes, shift extends from the last pick, and a plain click on the
  // only picked row puts it down again.
  const [picked, setPicked] = useState<string[]>(() => (jobUid ? [jobUid] : []));
  const one = picked.length === 1 ? picked[0] : null;
  // Selection -> route. Not `onSelectJob` in the deps: it is a fresh function
  // on every render of the app above, which would make this fire forever.
  useEffect(() => {
    if (one !== jobUid) onSelectJob(one);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [one]);
  // Route -> selection, for the ways the route moves on its own: Back and
  // Forward, and a link into a job. Only ever ADOPTS a uid; the route going
  // null is this component's own doing (several rows picked, or none), and
  // reading it back would clear the very selection that set it.
  useEffect(() => {
    if (jobUid && jobUid !== one) setPicked([jobUid]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobUid]);
  const pickAnchor = useRef<string | null>(null);
  useEscapeClears(true, picked.length > 0, () => { setPicked([]); pickAnchor.current = null; });
  // Reading order across the sections, so a shift-range picks the run the eye
  // actually sees rather than whatever order the jobs arrived in.
  const order = useMemo(() => [
    ...sections.running, ...sections.queued, ...sections.held,
    ...sections.finished,
  ].map((j) => j.uid), [sections]);
  // A job that finishes, is deleted or moves section must not leave a ghost in
  // the selection — the bar would then count rows nobody can see. NOT while
  // the list is still loading: an empty `order` is "nothing has arrived yet",
  // and pruning against it dropped the selection seeded from `?job=` before
  // the first page of jobs came back — which took the parameter out of the
  // address with it, so a reload landed on an unselected list every time.
  useEffect(() => {
    if (!data) return;
    setPicked((cur) => {
      const keep = cur.filter((u) => order.includes(u));
      return keep.length === cur.length ? cur : keep;
    });
  }, [order, data]);

  // The one click rule (`shared/pickList.ts`): shift REPLACES with the run.
  const pick = (uid: string, m: { meta: boolean; shift: boolean }) => {
    setPicked((cur) => {
      const r = pickNext(cur, uid, m, order, pickAnchor.current);
      pickAnchor.current = r.anchor;
      return r.next;
    });
  };

  const pickedJobs = picked
    .map((u) => jobs.find((j) => j.uid === u))
    .filter((j): j is TrainingJobSummary => !!j);
  // A running job is not removable, and the bar must not offer to do half of
  // what it says: what it counts is what it will act on.
  const removable = pickedJobs.filter((j) => !RUNNING.includes(j.status));
  const queueable = pickedJobs.filter(
    (j) => j.status === "draft" || j.status === "paused");
  const dequeueable = pickedJobs.filter((j) => j.status === "queued");

  const runAll = (fn: (uid: string) => Promise<unknown>, uids: string[]) =>
    void Promise.allSettled(uids.map(fn)).then(() => {
      setPicked([]);
      pickAnchor.current = null;
      refreshJobs();
    });

  /** REMOVING JOBS, wherever it is asked for — the selection bar, the
   *  Finished section's Clear, the open job's own header. One helper because
   *  the question is the same one every time, and a second copy of that
   *  sentence is a second thing to keep true.
   *
   *  A RUNNING job is never removed and is dropped from the list rather than
   *  refused: the callers all offer this over a set that may hold one, and
   *  "stop it first" is a different action from the one being pressed. */
  const removeJobs = async (list: TrainingJobSummary[]) => {
    const gone = list.filter((j) => !RUNNING.includes(j.status));
    if (!gone.length) return;
    // LOCKED weights are the exception, and the sentence says so: they move
    // into the Models tab's LoRA list rather than going with the job, which
    // is what a lock is for.
    if (!(await confirm({
      title: gone.length === 1
        ? t("Remove the training job “{name}”?", { name: gone[0].name })
        : t("Remove {n} training jobs?", { n: String(gone.length) }),
      body: gone.length === 1
        ? t("Its checkpoints, test samples and trained result are deleted with it — except anything locked, which is kept in the LoRAs list. This cannot be undone.")
        : t("Their checkpoints, test samples and trained results are deleted with them — except anything locked, which is kept in the LoRAs list. This cannot be undone."),
      answer: { label: t("Remove"), danger: true },
    }))) return;
    runAll((u) => api.trainDelete(u), gone.map((j) => j.uid));
  };

  const removePicked = () => removeJobs(removable);

  const selected = one ? (jobs.find((j) => j.uid === one) ?? null) : null;

  // One drag shared by both waiting sections, so a row can move between them:
  // into Next up = queue it at that slot, out of it = put it on hold.
  const [dragUid, setDragUid] = useState<string | null>(null);
  const drag: JobDrag = {
    uid: dragUid, start: setDragUid, end: () => setDragUid(null),
  };
  const queuedUids = sections.queued.map((j) => j.uid);
  const draggingQueued = !!dragUid && queuedUids.includes(dragUid);

  const dropToQueue = (index: number) => {
    const uid = dragUid;
    setDragUid(null);
    if (!uid) return;
    const from = queuedUids.indexOf(uid);
    const order = queuedUids.filter((u) => u !== uid);
    order.splice(from >= 0 && from < index ? index - 1 : index, 0, uid);
    const apply = async () => {
      if (from < 0) await api.trainQueue(uid);  // dragged in from Jobs
      await api.trainReorderQueue(order);
    };
    setRefused("");
    // A refused drag looked exactly like a drag that missed: the row went
    // back where it was and the reason — a model that still has to be
    // downloaded, a config that cannot be queued — was dropped here.
    void apply().then(() => setRefused(""), (e) => setRefused(errText(e)))
      .finally(refreshJobs);
  };

  const heldUids = sections.held.map((j) => j.uid);

  /** A drop in the Drafts band. Two things can be true at once, and the
   *  index is what tells them apart: a QUEUED row landing here comes out of
   *  the queue (`pause` returns it to paused-or-draft), and under a manual
   *  order it also lands at the slot it was dropped on. A row already held,
   *  under the date order, has nothing to change — there is no manual order
   *  for it to move within, which is why the section only draws an insertion
   *  line in the other mode. */
  const dropToHeld = (index?: number) => {
    const uid = dragUid;
    setDragUid(null);
    if (!uid) return;
    const wasQueued = queuedUids.includes(uid);
    const manual = heldSort === "manual";
    if (!wasQueued && !manual) return;
    const from = heldUids.indexOf(uid);
    // `-1` is the panel's "no slot" — what a drop on a row reports when the
    // section is not insertable, and what the whole-band drop means. Both
    // mean the end of the list.
    const at = index == null || index < 0 ? heldUids.length : index;
    const order = heldUids.filter((u) => u !== uid);
    order.splice(from >= 0 && from < at ? at - 1 : at, 0, uid);
    setRefused("");
    const apply = async () => {
      if (wasQueued) await api.trainPause(uid);
      // Only the drafts are named, so the queued jobs above become the
      // "rest" the server stamps after them — in their own order, which is
      // what keeps the queue's display untouched by a draft being moved.
      if (manual) await api.trainReorderQueue(order);
    };
    void apply().then(() => setRefused(""), (e) => setRefused(errText(e)))
      .finally(refreshJobs);
  };

  /** Switching TO manual writes the order that is ON SCREEN, so the list
   *  does not jump the moment the mode changes: a draft that has never been
   *  queued carries no stamp, and ordering by the ones that do would be an
   *  order nobody arranged. */
  const changeHeldSort = (mode: HeldSort) => {
    setHeldSort(mode);
    try { storage.set(HELD_SORT_KEY, mode); } catch { /* ignore */ }
    if (mode !== "manual" || heldUids.length < 2) return;
    void api.trainReorderQueue(heldUids).then(() => setRefused(""),
                                              (e) => setRefused(errText(e)))
      .finally(refreshJobs);
  };

  return (
    <>
    {/* The two columns, with the divider between them. The editor is not one
        of them — it is an overlay over the whole page — so it sits outside
        the split rather than as a third child of a two-column grid. */}
    <SidebarSplit widthKey={SIDEBAR_KEY} initial={400} t={t}>
      {/* Left: the job list, with the system stats pinned to the bottom as a
          collapsible footer (the library sidebar's pattern). */}
      <div style={{
        minHeight: 0, display: "flex", flexDirection: "column",
        borderRight: "1px solid var(--border)",
      }}>
      {/* The scroller sits in a NON-SCROLLING frame, because the selection bar
          is positioned against that frame rather than against the content —
          the library sidebar's shape, and for its reason: at the end of the
          list the bar is only on screen once you have scrolled to the bottom,
          which is exactly when a long list does not need it. */}
      <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
      <div style={{ position: "absolute", inset: 0, overflowY: "auto",
                    padding: 14 }}>
        {status && !status.env_ready && <TrainSetupBanner />}
        <Button variant="primary" size="md" block
     onClick={() => setEditorFor("")}>
          <Icon name="add" size={18} />
          {t("New training job")}
        </Button>

        {/* WHY THE LAST ACTION DID NOTHING — at the top of the list, where
            both a row's button and a drag between the sections can put it.
            It stays until the next action succeeds or it is dismissed: a
            refusal that faded would be one more thing nobody read. */}
        {refused && (
          <div style={{
            display: "flex", alignItems: "flex-start", gap: 8,
            border: "1px solid var(--red)", borderRadius: "var(--r-6)",
            background: "var(--danger-dim)",
            // Top margin as well as bottom: the box sits directly under the
            // New-job button, which has none of its own, so without it the
            // red edge touched the accent one.
            padding: "8px 10px", margin: "10px 0",
            fontSize: "var(--fs-2)", lineHeight: 1.5, color: "var(--red-text)",
          }}>
            <Icon name="error" size={14} />
            <span style={{ flex: 1, minWidth: 0 }}>{refused}</span>
            <span className="hoverable" onClick={() => setRefused("")}
              title={t("Dismiss")}
              style={{ cursor: "pointer", display: "flex" }}>
              <Icon name="close" size={14} />
            </span>
          </div>
        )}

        {jobs.length === 0 && (
          <EmptyState style={{ padding: "26px 18px 0", fontSize: "var(--fs-3)", lineHeight: 1.6 }}
            line={t("No training jobs yet. Create one to fine-tune a model (LoRA or full) on images selected straight from your library.")} />
        )}

        {sections.running.length > 0 && (
          <>
            <SectionHeader label={t("Running")} count={sections.running.length}
              trailing={<PauseControl running={sections.running} />} />
            <JobPanel onRefused={setRefused} queueActive={!!data?.queue_active} jobs={sections.running}
              picked={picked} onPick={pick} />
          </>
        )}
        {/* Up next is the run order, not a trigger: nothing starts until the
            queue's Run button is pressed, and a job you don't want run stays
            under Jobs. The section is always on screen — when empty it is a
            drop target explaining itself — and rows drag between the two
            sections as well as within the queue. */}
        {jobs.length > 0 && (
          // A drop anywhere in the band means "queue it, at the end"; a drop
          // on a row means the slot that row is in.
          <DropSection active={!!dragUid} hint={!!dragUid && !draggingQueued}
            onDrop={() => dropToQueue(sections.queued.length)}>
            <SectionHeader label={t("Up next")} count={sections.queued.length}
              trailing={<RunControl running={sections.running.length}
                queued={sections.queued.length} />} />
            {sections.queued.length > 0 ? (
              <JobPanel onRefused={setRefused} queueActive={!!data?.queue_active} jobs={sections.queued} evalBusy={evalBusy}
                picked={picked} onPick={pick}
                drag={drag} onDropAt={dropToQueue}
                insertable
                dragTitle={t("Drag to change the run order — or out of Up next to put the job on hold")} />
            ) : (
              <div
                onDragEnter={accept(!!dragUid)}
                onDragOver={accept(!!dragUid)}
                onDrop={dragUid ? (e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  dropToQueue(0);
                } : undefined}
                style={{
                  border: `1px dashed ${dragUid
                    ? "var(--accent)" : "var(--border-strong)"}`,
                  borderRadius: "var(--r-7)", padding: "14px 16px", textAlign: "center",
                  fontSize: "var(--fs-2)", color: "var(--muted)", lineHeight: 1.55,
                  background: dragUid ? "var(--accent-soft)" : "transparent",
                }}
              >
                {t("The queue is empty. Drag jobs here (or use their queue button) — they run in this order once the queue is started.")}
              </div>
            )}
          </DropSection>
        )}
        {(sections.held.length > 0 || draggingQueued) && (
          <DropSection active={draggingQueued} hint={draggingQueued}
            onDrop={dropToHeld}>
            {/* "Drafts": everything waiting outside the queue — a job never
                run, and one paused out of it. "Jobs" said nothing, since
                every section here holds jobs. */}
            <SectionHeader label={t("Drafts")} count={sections.held.length}
              trailing={sections.held.length > 1
                ? <HeldSortSelect value={heldSort} onChange={changeHeldSort} />
                : undefined} />
            {sections.held.length > 0 ? (
              <JobPanel onRefused={setRefused} queueActive={!!data?.queue_active} jobs={sections.held}
                picked={picked} onPick={pick}
                drag={drag} onDropAt={dropToHeld}
                insertable={heldSort === "manual"}
                dragTitle={heldSort === "manual"
                  ? t("Drag to reorder — or into Up next to queue the job")
                  : t("Drag into Up next to queue the job")} />
            ) : (
              // Appears only while a queued row is being dragged, so pulling
              // the last job out of the queue always has somewhere to land.
              <div
                onDragEnter={accept(true)}
                onDragOver={accept(true)}
                onDrop={(e) => { e.preventDefault(); e.stopPropagation();
                                 dropToHeld(); }}
                style={{
                  border: "1px dashed var(--accent)", borderRadius: "var(--r-7)",
                  padding: "14px 16px", textAlign: "center", fontSize: "var(--fs-2)",
                  color: "var(--muted)", background: "var(--accent-soft)",
                }}
              >
                {t("Drop here to put the job on hold.")}
              </div>
            )}
          </DropSection>
        )}
        {sections.finished.length > 0 && (
          <>
            {/* CLEAR, in the header of the section it clears — the same
                place Run and Pause sit for the sections they act on. It goes
                through `removeJobs`, so it asks the one question that
                deletion asks here and says what a lock keeps. */}
            <SectionHeader label={t("Finished")} count={sections.finished.length}
              trailing={
                <button
                  onClick={() => removeJobs(sections.finished)}
                  title={t("Remove every finished job, with its checkpoints and samples")}
                  style={{ ...queuePill(false), gap: 5,
                           padding: "0 9px 0 7px" }}>
                  <Icon name="delete_sweep" size={14} />
                  {t("Clear")}
                </button>
              } />
            <JobPanel onRefused={setRefused} queueActive={!!data?.queue_active} jobs={sections.finished}
              picked={picked} onPick={pick} />
          </>
        )}
        {/* The bar takes no layout space, so the content reserves its height
            here — the last row has to be scrollable clear of it. */}
        {jobs.length > 0 && (
          <div style={{ height: SELECTION_BAR_H + SELECTION_BAR_GAP * 2 }} />
        )}
      </div>
      {/* WHAT IS PICKED, and what to do with it — the library sidebar's bar,
          from the same component, pinned near the bottom of the sidebar and
          floating over the list. It shows whenever there are jobs at all
          rather than only once one is picked: with nothing selected it says
          so and offers Select all, which is where that action lives. */}
      {jobs.length > 0 && (
        <div style={{ position: "absolute", left: 14, right: 14,
                      bottom: SELECTION_BAR_GAP, zIndex: 5,
                      pointerEvents: "none" }}>
          <SelectionBar
            t={t}
            floating
            // Positioned by the frame, so it must take its real height here:
            // the floating variant's negative `marginBottom` is how it costs
            // the SCROLL content nothing, and inside the overlay it would
            // only hang the bar out of it. LONGHANDS, or a `margin: 0`
            // shorthand and the component's own longhand race.
            style={{ position: "static", marginTop: 0, marginBottom: 0,
                     pointerEvents: "auto" }}
            count={picked.length}
            total={order.length}
            onSelectAll={() => {
              setPicked(order);
              pickAnchor.current = order[order.length - 1] ?? null;
            }}
            onClear={() => { setPicked([]); pickAnchor.current = null; }}
            onRemove={removePicked}
            removeIcon="delete"
            removeLabel={t("Remove")}
            // What it will ACT on, which is not always what is picked: a
            // running job cannot be removed. With none removable the button
            // is not drawn at all — "Remove 1" over a running job was an
            // offer that did nothing when pressed.
            removeCount={removable.length}
            removeTitle={removable.length < picked.length
              ? t("Remove the selected jobs — a running job is left alone")
              : t("Remove the selected jobs, with their checkpoints and samples")}
          />
        </div>
      )}
      </div>
        <GpuStatsBar />
      </div>

      {/* Right: detail / empty state */}
      <div style={{ minHeight: 0, overflowY: "auto" }}>
        {selected ? (
          <TrainJobDetail
            uid={selected.uid}
            onEdit={() => setEditorFor(selected.uid)}
            onDelete={() => removeJobs([selected])}
          />
        ) : (
          <div style={{
            height: "100%", display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", gap: 10,
            color: "var(--muted)",
          }}>
            <Icon name="model_training" size={42} color="var(--border-strong)" />
            {/* SEVERAL rows picked is its own answer, not the empty one: what
                is on the left is a selection a bulk action is about, and a
                pane reading "select a job" over it looks like the clicks did
                not register. */}
            <div style={{ fontSize: "var(--fs-3)", textAlign: "center", maxWidth: 320 }}>
              {picked.length > 1
                ? t("{n} jobs selected. One at a time shows its progress, samples and settings.",
                    { n: picked.length })
                : t("Select a job to see its progress, samples and settings.")}
            </div>
          </div>
        )}
      </div>

    </SidebarSplit>

      {editorFor !== null && status && (
        <TrainJobEditor
          uid={editorFor || null}
          models={status.models}
          onClose={(createdUid) => {
            setEditorFor(null);
            if (createdUid) setPicked([createdUid]);
            // The whole job, not just the list: a save writes an "edited"
            // entry into the job's own TIMELINE, and on a paused job
            // nothing polls — so sweeping `train-jobs` alone left the pane
            // showing the timeline as it was until the job was deselected
            // and picked again.
            invalidateJob(qc, createdUid || editorFor || null);
          }}
        />
      )}
    </>
  );
}
