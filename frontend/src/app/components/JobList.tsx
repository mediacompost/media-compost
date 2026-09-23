import { useEffect, useRef, useState } from "react";
import { SectionHeading } from "../../shared/SectionHeading";
import { IconButton } from "../../shared/IconButton";
import { Button } from "../../shared/Button";
import { ProgressBar } from "../../shared/ProgressBar";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, JobOut, ModelCacheInfo } from "../api";
import { Icon } from "../../shared/Icon";
import { useUI } from "../store";
import { ImportTaskList } from "./ImportTasks";
import { JobItemsOverlay } from "./JobItems";
import { useImportTasks, taskActive, taskDone, cancelImportTask, dismissImportTask, ownsImportJob } from "../importManager";
import { renderAnsi } from "../../shared/ansi";
import { bumpLibrary } from "../invalidation";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { RowMenu } from "../../shared/RowMenu";
import { useT, useTn } from "../i18n";
import { useEscape } from "../../shared/useEscape";
import { Overlay } from "../../shared/Overlay";

/** A task-kind -> {icon, label} map from the backend task list, so job rows
 *  aren't hardcoded to a fixed set of actions. Shares the cached ["ml-models"]
 *  query with the action buttons. */
function useKindMeta(): Record<string, { icon: string; label: string }> {
  const { data } = useQuery({ queryKey: ["ml-models"], queryFn: api.mlModels });
  return Object.fromEntries(
    // Both lists: the AI actions AND the background-job kinds that are not
    // actions (a video render). A row here needs a label whatever queued it,
    // and the fallback prints the kind — "video_edit" — at the user.
    [...(data?.tasks ?? []), ...(data?.job_kinds ?? [])]
      .map((t) => [t.kind, { icon: t.icon, label: t.label }]),
  );
}

const STATUS_COLOR: Record<string, string> = {
  queued: "var(--muted)",
  running: "var(--accent)",
  paused: "var(--yellow-text)",
  done: "var(--green)",
  warning: "var(--yellow-text)",
  failed: "var(--danger)",
  canceled: "var(--muted-3)",
};

const isActive = (j: JobOut) => j.status === "queued" || j.status === "running";
/** Held, not finished — so it keeps a cancel button and offers a resume, and
 *  is not something "Clear finished" sweeps away. It does NOT drive the poll:
 *  a paused job is the one state where nothing is going to change by itself. */
const isPaused = (j: JobOut) => j.status === "paused";
/** A job worth listing item by item: a batch covers a whole import now, so
 *  "1 / 4000" is the only thing the row itself can say. */
const hasItemList = (j: JobOut) => j.item_count > 1;

/** Bottom-of-left-sidebar list of background AI jobs. Polls while any job is
 *  active, lets the user cancel queued/running ones and clear finished ones, and
 *  refreshes the affected content queries when a job completes. */
export function JobList() {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const setSelectedItems = useUI((s) => s.setSelectedItems);
  const kindMeta = useKindMeta();
  const importTasks = useImportTasks();
  const activeImports = importTasks.filter(taskActive).length;
  // A failed task whose full error message is currently expanded.
  const [expandedId, setExpandedId] = useState<number | null>(null);
  // The task whose full-log overlay is open.
  const [logId, setLogId] = useState<number | null>(null);
  // The task whose per-item progress list is open.
  const [itemsId, setItemsId] = useState<number | null>(null);
  const { data } = useQuery({
    queryKey: ["ml-jobs"],
    queryFn: api.mlJobs,
    // Poll only while something is queued/running; otherwise idle until the next
    // enqueue invalidates this query.
    refetchInterval: (q) => {
      const jobs = (q.state.data as { jobs: JobOut[] } | undefined)?.jobs ?? [];
      return jobs.some(isActive) ? 1200 : false;
    },
  });
  // In-flight model downloads (from the settings' model-cache), surfaced here so
  // they appear alongside AI jobs. Poll while any model is downloading.
  const { data: cacheData } = useQuery({
    queryKey: ["model-cache"],
    queryFn: api.modelCache,
    refetchInterval: (q) => {
      const models = (q.state.data as { models: ModelCacheInfo[] } | undefined)?.models ?? [];
      return models.some((m) => m.downloading) ? 1200 : false;
    },
  });
  const downloads = (cacheData?.models ?? []).filter((m) => m.downloading);

  // IMPORTS THIS PAGE DOES NOT OWN. The browser holds the files, so a reload
  // throws its task list away — and an import that was still running (or that
  // then failed) would simply vanish from the app with the work still going
  // on, or gone wrong, on the server. The server keeps its own record; these
  // are the rows of it nobody is drawing. A cleanly finished one is dropped
  // like a plain "done" AI job; a failed one stays until it is cleared.
  const { data: importData } = useQuery({
    queryKey: ["import-jobs"],
    queryFn: api.importJobs,
    refetchInterval: (q) => {
      const rows = (q.state.data as { jobs: { status: string }[] } | undefined)?.jobs ?? [];
      return rows.some((j) => j.status === "running") ? 1500 : 8000;
    },
  });
  const orphanImports = (importData?.jobs ?? []).filter(
    (j) => !ownsImportJob(j.id) && j.status !== "done");

  const jobs = data?.jobs ?? [];
  const activeJobs = jobs.filter(isActive).length;
  const activeCount = activeJobs + downloads.length
    + orphanImports.filter((j) => j.status === "running").length;

  // When the active job count drops (a job finished), refresh everything a job
  // can touch so pending tags/captions, the Pending category and counts update.
  // (Downloads don't change item content, so they don't drive this.)
  const prevActive = useRef(activeJobs);
  useEffect(() => {
    if (activeJobs < prevActive.current) {
      // Coalesced sweep of everything a job can touch — relationships (a
      // background-removal's new linked item), sequences (panel detection's
      // new sequence), the face queries (a detection run filling the sidebar's
      // Faces section), and the item/tag/count queries. A batch of jobs
      // finishing close together costs one refetch burst, not one each.
      bumpLibrary();
    }
    prevActive.current = activeJobs;
  }, [activeJobs, qc]);

  if (jobs.length === 0 && downloads.length === 0 && importTasks.length === 0
      && orphanImports.length === 0) return null;

  const cancelDownload = async (key: string) => {
    await api.cancelDownload(key);
    qc.invalidateQueries({ queryKey: ["model-cache"] });
  };

  const cancel = async (id: number) => {
    await api.cancelJob(id);
    qc.invalidateQueries({ queryKey: ["ml-jobs"] });
  };
  const hold = async (j: JobOut) => {
    await (isPaused(j) ? api.resumeJob(j.id) : api.pauseJob(j.id));
    qc.invalidateQueries({ queryKey: ["ml-jobs"] });
  };
  const clearImport = async (id: string) => {
    await api.clearImportJob(id);
    qc.invalidateQueries({ queryKey: ["import-jobs"] });
  };
  const clearOne = async (id: number) => {
    await api.clearJob(id);
    qc.invalidateQueries({ queryKey: ["ml-jobs"] });
  };
  // Where did this job land? All Items scope, cleared search, the job's own
  // items selected — which is the way TO a failed job's items, whose row
  // click shows the error instead of selecting. The wire's JobOut carries
  // only a batch's FIRST item (deliberately — a run over a group can hold
  // thousands of ids), so the full list is fetched on demand.
  const showJobItems = async (j: JobOut) => {
    let ids = j.item_id == null ? [] : [j.item_id];
    try { ids = (await api.jobItems(j.id)).item_ids; } catch { /* keep the first */ }
    const s = useUI.getState();
    s.showAllItems();
    s.setSearch("");
    s.setSelectedItems(ids);
    s.setView("library");
  };
  // EVERY finished row this panel draws, whoever owns it. The three kinds are
  // three registries — AI jobs in the database, this page's own import tasks
  // in memory, and the SERVER's record of imports nobody here started — and
  // this used to sweep only the first two. So a failed import that had
  // outlived the page that started it could not be cleared by the one control
  // that says it clears everything, and, when it was the only finished row,
  // that control was not even drawn (see `hasFinished`): the row simply sat
  // there for the life of the server. Each kind is swept independently, so
  // one failing does not strand the others.
  const clearFinished = async () => {
    try {
      await api.clearFinishedJobs();
    } catch { /* keep going: the other two registries are still clearable */ }
    for (const j of orphanImports) {
      if (j.status === "running") continue;   // nowhere else to report itself
      try { await api.clearImportJob(j.id); } catch { /* ignore */ }
    }
    qc.invalidateQueries({ queryKey: ["ml-jobs"] });
    qc.invalidateQueries({ queryKey: ["import-jobs"] });
    for (const t of importTasks) if (!taskActive(t)) dismissImportTask(t.id);
  };
  // Cancel everything running/pending at once: AI jobs, model downloads, imports.
  const cancelAll = async () => {
    try { await api.cancelAllJobs(); } catch { /* ignore */ }
    for (const m of downloads) { try { await api.cancelDownload(m.key); } catch { /* ignore */ } }
    for (const t of importTasks.filter(taskActive)) cancelImportTask(t.id);
    qc.invalidateQueries({ queryKey: ["ml-jobs"] });
    qc.invalidateQueries({ queryKey: ["model-cache"] });
  };
  // A PAUSED job is not finished: "Clear finished" would not remove it, and
  // offering to is a button that does nothing. A finished SERVER-side import
  // counts — it is a row in this list with nothing else to remove it.
  const hasFinished = jobs.some((j) => !isActive(j) && !isPaused(j))
    || importTasks.some((t) => taskDone(t) && !taskActive(t))
    || orphanImports.some((j) => j.status !== "running");
  const hasActive = activeCount + activeImports > 0;

  return (
    <div style={{ flex: "0 0 auto", borderTop: "1px solid var(--border-soft)", maxHeight: 220, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 12px 4px" }}>
        <Icon name="smart_toy" size={15} color="var(--muted)" />
        <SectionHeading style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          Background Tasks{hasActive ? ` · ${activeCount + activeImports} active` : ""}
        </SectionHeading>
        {/* BOTH BULK VERBS LIVE IN THE ⋯, and the width is why.
            "Cancel all" and "Clear all" were two labelled buttons in a 265px
            header, which does not hold them and the section's own name: the
            heading clipped to "BACKGR…". What used to give was the CLEAR
            control — it collapsed to a bare 16px glyph whenever anything was
            active, which is exactly when the list is longest and there is
            most to clear, so the one control that empties it went wordless at
            the moment it was wanted and read as gone. A menu is the answer
            this app already uses for "several verbs, not enough width": both
            keep a readable label in every state, and the heading keeps its
            name. `always`, because the menu holds the only way to do either. */}
        {(hasActive || hasFinished) && (
          <RowMenu
            always
            icon="more_horiz"
            color="var(--muted)"
            title={t("Actions for all background tasks")}
            actions={[
              ...(hasFinished ? [{
                icon: "delete_sweep",
                label: t("Clear all"),
                hint: t("Removes every finished task from this list"),
                onClick: () => void clearFinished(),
              }] : []),
              ...(hasActive ? [{
                icon: "cancel",
                label: t("Cancel all"),
                hint: t("Stops everything running and pending"),
                danger: true,
                separated: hasFinished,
                onClick: () => void cancelAll(),
              }] : []),
            ]}
          />
        )}
      </div>
      <div style={{ overflowY: "auto", padding: "0 8px 8px", display: "flex", flexDirection: "column", gap: 3 }}>
        {/* File-import background tasks (each drop), above the model jobs. */}
        <ImportTaskList />
        {orphanImports.map((j) => {
          const failed = j.status === "error";
          const n = Number(j.stats?.imported ?? 0);
          return (
            <div
              key={`imp-${j.id}`}
              className="hoverable"
              title={failed ? j.message || t("The import failed")
                            : t("An import started before this page was loaded")}
              style={{ display: "flex", alignItems: "center", gap: 7, minHeight: 30, padding: "3px 6px", borderRadius: "var(--r-3)" }}
            >
              <Icon name={failed ? "error" : "cloud_upload"} size={15}
                    color={failed ? "var(--danger)" : "var(--accent)"}
                    spin={!failed} />
              <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
                <span style={{ fontSize: "var(--fs-2)", color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {j.label || t("Import")}
                </span>
                <span style={{ fontSize: "var(--fs-1)", color: failed ? "var(--danger)" : "var(--accent)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {failed
                    ? (j.message ? t("Import failed — {message}", { message: j.message })
                                 : t("Import failed"))
                    : (n ? t("Importing · {n} of {total}", { n, total: j.total })
                         : t("Importing…"))}
                </span>
              </span>
              {/* Only a finished one can be dismissed — a running import has
                  nowhere else to report its outcome. */}
              {j.status !== "running" && (
                <span className="row-action-fixed" style={{ display: "flex", alignItems: "center", gap: 1 }}>
                  <IconButton icon="close" size={20} glyph={14} reveal="hover"
                    onClick={() => void clearImport(j.id)}
                    title={t("Remove from list")} />
                </span>
              )}
            </div>
          );
        })}
        {downloads.map((m) => (
          <div
            key={`dl-${m.key}`}
            className="hoverable"
            title={t("Downloading {model}", { model: m.label })}
            style={{
              display: "flex", alignItems: "center", gap: 7, minHeight: 30,
              padding: "3px 6px", borderRadius: "var(--r-3)",
            }}
          >
            <Icon
              name="progress_activity"
              size={15}
              color="var(--accent)"
              spin
            />
            <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: "var(--fs-2)", color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {m.label}
              </span>
              <span style={{ fontSize: "var(--fs-1)", color: "var(--accent)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                Downloading{m.progress >= 0 ? ` · ${m.progress}%` : "…"}
              </span>
            </span>
            <span className="row-action-fixed" style={{ display: "flex", alignItems: "center", gap: 1 }}>
              <IconButton icon="close" size={20} glyph={14} reveal="hover" tone="danger"
                onClick={(e) => { e.stopPropagation(); cancelDownload(m.key); }}
                title={t("Cancel download")} />
            </span>
          </div>
        ))}
        {jobs.map((j) => {
          const m = kindMeta[j.kind] ?? { icon: "bolt", label: j.kind };
          const color = STATUS_COLOR[j.status] ?? "var(--muted)";
          const failed = j.status === "failed";
          const warn = j.status === "warning";
          const active = isActive(j);
          const held = isPaused(j);
          const expanded = expandedId === j.id;
          return (
            <div key={j.id}>
              <div
                className="hoverable"
                // A failed task expands to show its full error; anything else
                // selects the affected item.
                onClick={() =>
                  failed ? setExpandedId((id) => (id === j.id ? null : j.id))
                    // A job about no picture has nothing to select — an
                    // estimate covers a whole scope it never listed.
                    : j.item_id != null && setSelectedItems([j.item_id])}
                title={failed ? t("Click to show the full error") : `${m.label} · ${j.status}`}
                style={{
                  display: "flex", alignItems: "center", gap: 7, minHeight: 30,
                  padding: "3px 6px", borderRadius: "var(--r-3)", cursor: "pointer",
                }}
              >
                <Icon
                  name={j.status === "running" ? "progress_activity"
                    : held ? "pause_circle"
                    : failed ? "error" : warn ? "warning" : m.icon}
                  size={15}
                  color={color}
                  spin={j.status === "running"}
                />
                <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
                  <span style={{ fontSize: "var(--fs-2)", color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {j.item_count > 1 ? `${j.item_count} items`
                      : (j.item_name || (j.item_id == null ? m.label
                                         : `Item #${j.item_id}`))}
                  </span>
                  <span style={{ fontSize: "var(--fs-1)", color, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {/* A running multi-step job (e.g. sequence panel detection)
                        shows its live progress label; others show their status,
                        and warnings/errors append their message. */}
                    {/* …and the label is dropped where the line above is
                        already it: a job about no picture (an estimate over
                        a whole scope) has nothing else to put up there, so
                        printing the label twice was the whole row. */}
                    {j.item_id == null && j.item_count <= 1 ? "" : `${m.label} · `}
                    {j.status === "running" && j.message ? j.message : j.status}
                    {/* A batch is ONE job for a whole import now, so how far
                        through it is belongs on the row — but only where the
                        row is not already saying it: a RUNNING job's own
                        message is "Detecting faces — 5 / 14 items", and the
                        counter after it was the same figure twice. */}
                    {hasItemList(j) && (active || held)
                      && !(j.status === "running" && j.message)
                      ? ` · ${j.done_count} / ${j.item_count}` : ""}
                    {j.message && (warn || (failed && !expanded)) ? ` — ${j.message}` : ""}
                  </span>
                  {(j.status === "running" || held) && j.progress > 0 && (
                    <ProgressBar value={j.progress} height={3} transitionMs={300}
                                 color={held ? "var(--yellow-text)" : "var(--accent)"}
                                 style={{ marginTop: 3 }} />
                  )}
                </span>
                {/* An active task keeps its direct ✕ — cancelling is the
                    time-sensitive one. A finished task's actions live in a ⋯
                    menu instead: three of them (the way to the items, the
                    log, the removal) spelled out as hover icons was a row of
                    buttons, and the way to the items had no icon at all. */}
                {active || held ? (
                  <span className="row-action-fixed" style={{ display: "flex", alignItems: "center", gap: 1 }}>
                    {hasItemList(j) && (
                      <IconButton icon="list" size={20} reveal="hover"
                        onClick={(e) => { e.stopPropagation(); setItemsId(j.id); }}
                        title={t("View the items in this task")} />
                    )}
                    {/* Offered where the queue says it can be held — a
                        running single-item job has no boundary inside one
                        model run to stop at. */}
                    {(j.pausable || held) && (
                      <IconButton icon={held ? "play_arrow" : "pause"} size={20} reveal="hover"
                        onClick={(e) => { e.stopPropagation(); void hold(j); }}
                        title={held ? t("Resume this task") : t("Pause this task")} />
                    )}
                    <IconButton icon="close" size={20} glyph={14} reveal="hover" tone="danger"
                      onClick={(e) => { e.stopPropagation(); cancel(j.id); }}
                      title={t("Cancel task")} />
                  </span>
                ) : (
                  <RowMenu
                    title={t("Task actions")}
                    actions={[
                      // The way TO the items — for a failed job the row
                      // click shows the error, so this is the only route.
                      { icon: "photo_library",
                        label: j.item_count > 1
                          ? t("Show items in library") : t("Show item in library"),
                        hint: t("All Items, with this task's items selected"),
                        onClick: () => void showJobItems(j) },
                      ...(hasItemList(j) ? [{
                        icon: "checklist", label: t("View item progress"),
                        hint: t("What happened to each item of this task"),
                        onClick: () => setItemsId(j.id),
                      }] : []),
                      { icon: "description", label: t("View full log"),
                        onClick: () => setLogId(j.id) },
                      { icon: "delete", label: t("Remove from list"),
                        danger: true, separated: true,
                        onClick: () => void clearOne(j.id) },
                    ]}
                  />
                )}
              </div>
              {/* Full error, revealed by clicking a failed task. Selectable so
                  the user can copy parts of it to search for help. */}
              {failed && expanded && j.message && (
                <div style={{ margin: "1px 6px 4px 28px", padding: "6px 8px", background: "var(--panel-3)", border: "1px solid var(--border)", borderRadius: "var(--r-2)", fontSize: "var(--fs-1)", lineHeight: 1.5, color: "var(--red-text)", whiteSpace: "pre-wrap", overflowWrap: "anywhere", userSelect: "text", WebkitUserSelect: "text" }}>
                  {j.message}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {logId != null && (
        <JobLogOverlay
          job={jobs.find((j) => j.id === logId)}
          onClose={() => setLogId(null)}
        />
      )}
      {itemsId != null && jobs.some((j) => j.id === itemsId) && (() => {
        const j = jobs.find((x) => x.id === itemsId) as JobOut;
        return (
          <JobItemsOverlay
            job={j}
            label={kindMeta[j.kind]?.label ?? j.kind}
            onClose={() => setItemsId(null)}
          />
        );
      })()}
    </div>
  );
}

/** A task's complete captured log output, in a dialog. */
function JobLogOverlay({ job, onClose }: { job?: JobOut; onClose: () => void }) {
  const id = job?.id;
  const { data, isLoading } = useQuery({
    queryKey: ["ml-job-log", id],
    queryFn: () => api.jobLog(id as number),
    enabled: id != null,
  });
  const t = useT();
  const kindMeta = useKindMeta();
  const label = job ? (kindMeta[job.kind]?.label ?? job.kind) : t("Task");
  const log = (data?.log ?? "").trim();
  // Once the log arrives, scroll to the bottom so the last (usually most
  // relevant) message is visible.
  const preRef = useRef<HTMLPreElement>(null);
  useEffect(() => {
    const el = preRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log]);
  const subject = job && job.item_count > 1 ? `${job.item_count} items`
    : (job?.item_name || (job && job.item_id != null ? `Item #${job.item_id}` : ""));
  return (
    <Overlay icon="description" width={760} onClose={onClose}
      title={`${label}${subject ? ` · ${subject}` : ""}${job ? ` · ${job.status}` : ""}`}
      height="82%"
      footer={log ? (
        <Button variant="ghost" size="sm"
     onClick={() => { try { navigator.clipboard?.writeText(log); } catch { /* ignore */ } }}
     title={t("Copy log")}>
          <Icon name="content_copy" size={14} /> {t("Copy")}
        </Button>
      ) : undefined}>
      <pre
        ref={preRef}
        className="mc-copy"
        style={{
          margin: 0, height: "100%", overflow: "auto", padding: "10px 12px",
          background: "var(--bg-deep)", border: "1px solid var(--border)", borderRadius: "var(--r-5)",
          fontFamily: "var(--mono)", fontSize: "var(--fs-2)", lineHeight: 1.5, color: "var(--text-2)",
          whiteSpace: "pre-wrap", overflowWrap: "anywhere", boxSizing: "border-box",
        }}
      >
        {isLoading ? t("Loading…") : log ? renderAnsi(log) : t("No log output was captured for this task.")}
      </pre>
    </Overlay>
  );
}
