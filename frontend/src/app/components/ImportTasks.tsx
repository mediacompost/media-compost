import React, { useRef, useState } from "react";
import { IconButton } from "../../shared/IconButton";
import { ProgressBar } from "../../shared/ProgressBar";
import { Icon } from "../../shared/Icon";
import { Overlay } from "../../shared/Overlay";
import {
  ImportFile, ImportTask, useImportTasks, taskProgress, taskCounts,
  taskActive, taskDone, taskResumable, cancelImportTask, dismissImportTask,
  resumeImportTask,
} from "../importManager";
import { formatBytes } from "../format";
import { useLang, useT } from "../i18n";
import { useWindowedList } from "../useWindowedList";

// Estimated stride of one file row (content + border + list gap) for the
// windowed list; rows keep their natural height, this only sizes the window.
const FILE_ROW_H = 33;

const FILE_ICON: Record<ImportFile["status"], { icon: string; color: string }> = {
  pending: { icon: "schedule", color: "var(--muted-2)" },
  uploading: { icon: "cloud_upload", color: "var(--accent)" },
  processing: { icon: "sync", color: "var(--accent)" },
  done: { icon: "check_circle", color: "var(--green)" },
  error: { icon: "error", color: "var(--red)" },
  canceled: { icon: "block", color: "var(--muted-3)" },
};

/** One import-task row (a background task): label, % progress, cancel/dismiss,
 *  and a hover button to view its files. */
export function ImportTaskRow({ task, onView }: { task: ImportTask; onView: () => void }) {
  const t = useT();
  const pct = Math.round(taskProgress(task) * 100);
  const c = taskCounts(task);
  const active = taskActive(task);
  const done = taskDone(task);
  // WHAT LANDED SOMEWHERE INVISIBLE gets said on the finished row, because
  // that is the whole point: the run worked, so nothing else here would ever
  // mention it, and the pictures are inside a hidden item or one in the Trash.
  const warn = done && !task.canceled && task.warnings > 0;
  const sub = task.canceled
    ? t("Canceled")
    : done
      // `skipped` and `ignored` are two answers, so they are two figures:
      // the library already had those bytes, against the run's own minimums
      // and type filter leaving them alone.
      ? [t("Imported {n}", { n: task.imported }),
         task.skipped ? t("{n} skipped", { n: task.skipped }) : "",
         task.ignored ? t("{n} ignored", { n: task.ignored }) : "",
         c.error ? t("{n} failed", { n: c.error }) : "",
         task.warnings ? t("{n} out of sight", { n: task.warnings }) : "",
        ].filter(Boolean).join(" · ")
      : t("{done}/{total} files", { done: c.done, total: c.total });
  return (
    <div
      className="hoverable"
      // Compact, borderless row — matches the model-job / download rows (but
      // keeps a progress bar).
      style={{ display: "flex", alignItems: "center", gap: 7, minHeight: 30, padding: "3px 6px", borderRadius: "var(--r-3)" }}
    >
      <span style={{ flex: "0 0 auto", display: "flex" }}
            title={warn ? t("Some files matched an item that is hidden or in the Trash") : undefined}>
        <Icon name={warn ? "warning"
                         : done && !c.error && !task.canceled ? "check_circle"
                         : "cloud_upload"} size={15}
              color={warn ? "var(--yellow-text)"
                          : done && !c.error && !task.canceled ? "var(--green)"
                          : "var(--accent)"} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "var(--fs-2)", color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {task.label}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
          <ProgressBar value={pct} height={4} track="var(--border)" style={{ flex: 1 }}
                       color={task.canceled ? "var(--muted-3)" : warn ? "var(--yellow-text)" : done && !c.error ? "var(--green)" : "var(--accent)"} />
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)", flex: "0 0 auto" }}>{sub}</span>
        </div>
      </div>
      <span className="row-actions" style={{ flex: "0 0 auto", display: "flex", alignItems: "center", gap: 2 }}>
        <IconButton icon="list" size={22} glyph={16} reveal="hover" title={t("View files in this import")} onClick={onView} />
        {active ? (
          <IconButton icon="stop_circle" size={22} glyph={16} reveal="hover" tone="danger" title={t("Cancel this import")} onClick={() => cancelImportTask(task.id)} />
        ) : (<>
          {/* A CANCEL IS NOT FINAL. The files it dropped are still held, so
              what is left to do is exactly known and the run picks up where
              it stopped — where before, the only way back was to drop the
              same folder again and let the whole of it dedup its way
              through what had already landed. */}
          {taskResumable(task) && (
            <IconButton icon="play_arrow" size={22} glyph={16} reveal="hover" tone="accent" title={t("Resume this import")}
                  onClick={() => resumeImportTask(task.id)} />
          )}
          <IconButton icon="close" size={22} glyph={16} reveal="hover" title={t("Dismiss")} onClick={() => dismissImportTask(task.id)} />
        </>)}
      </span>
    </div>
  );
}

/** A modal listing every file in an import task with its per-file status.
 *  The rows are windowed: a folder drop can stage tens of thousands of files,
 *  and only a viewport's worth of rows mounts at a time. */
export function ImportFilesOverlay({ task, onClose }: { task: ImportTask; onClose: () => void }) {
  const lang = useLang();
  const t = useT();
  const c = taskCounts(task);
  const scrollRef = useRef<HTMLDivElement>(null);
  const win = useWindowedList({
    count: task.files.length, rowHeight: FILE_ROW_H, scrollRef, minCount: 80,
  });
  const listStyle: React.CSSProperties = {
    display: "flex", flexDirection: "column", gap: 4,
  };
  return (
    <Overlay
      icon="upload_file"
      title={task.label}
      subtitle={[t("{n} imported", { n: c.done }), t("{n} in progress", { n: c.pending }),
                 c.error ? t("{n} failed", { n: c.error }) : "",
                 task.warnings ? t("{n} out of sight", { n: task.warnings }) : "",
                ].filter(Boolean).join(" · ")}
      width={560}
      onClose={onClose}
    >
      <div ref={scrollRef} style={{ padding: 16, maxHeight: "60vh", overflowY: "auto" }}>
        <div
          ref={win.containerRef}
          style={win.windowed ? { height: win.totalHeight, position: "relative" } : undefined}
        >
          <div style={win.windowed
            ? { ...listStyle, position: "absolute", top: win.topOffset, left: 0, right: 0 }
            : listStyle}
          >
            {task.files.slice(win.start, win.end).map((f) => {
              const s = FILE_ICON[f.status];
              // AMBER, the app's colour for "a machine did this and somebody
              // should look": the file imported, and where it landed is not
              // somewhere the grid will show it.
              const w = f.warning;
              return (
                <div key={f.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 8px", borderRadius: "var(--r-3)", background: w ? "var(--yellow-dim)" : "var(--panel-3)", border: `1px solid ${w ? "var(--yellow-text)" : "var(--border)"}` }}>
                  <Icon name={w ? "visibility_off" : s.icon} size={16}
                        color={w ? "var(--yellow-text)" : s.color}
                        spin={f.status === "processing"} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.rel}</div>
                    {f.status === "error" && f.message && (
                      <div style={{ fontSize: "var(--fs-1)", color: "var(--red-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.message}</div>
                    )}
                    {w && (
                      <div style={{ fontSize: "var(--fs-1)", color: "var(--yellow-text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {w === "trashed"
                          ? "It matched an item in the Trash"
                          : "It matched a hidden item"}
                      </div>
                    )}
                  </div>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)", flex: "0 0 auto" }}>{formatBytes(f.file.size, lang)}</span>
                  <span style={{ fontSize: "var(--fs-1)", color: s.color, flex: "0 0 auto", minWidth: 66, textAlign: "right" }}>
                    {f.status === "uploading" ? `${Math.round(f.progress * 100)}%` : f.status}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Overlay>
  );
}

/** The list of active/recent import tasks (background tasks), with a per-task
 *  files viewer. Shared by the left sidebar and the Import overlay. */
export function ImportTaskList({ empty }: { empty?: React.ReactNode }) {
  const tasks = useImportTasks();
  const [viewing, setViewing] = useState<number | null>(null);
  const viewingTask = tasks.find((t) => t.id === viewing) ?? null;
  if (tasks.length === 0) return <>{empty ?? null}</>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {tasks.map((t) => (
        <ImportTaskRow key={t.id} task={t} onView={() => setViewing(t.id)} />
      ))}
      {viewingTask && <ImportFilesOverlay task={viewingTask} onClose={() => setViewing(null)} />}
    </div>
  );
}
