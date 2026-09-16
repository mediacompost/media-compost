import { useEffect, useRef, useState } from "react";
import { Icon } from "../../shared/Icon";
import { Overlay } from "../../shared/Overlay";
import { api, JobItem, JobOut } from "../api";
import { useWindowedList } from "../useWindowedList";

// One item row's stride (content + border + gap), for the windowed list.
const ROW_H = 30;
// One request's worth of items. A batch job can cover a whole library, so the
// list is paged and only the pages under the viewport are ever asked for.
const PAGE = 200;

const STATE_ICON: Record<string, { icon: string; color: string }> = {
  done: { icon: "check_circle", color: "var(--green)" },
  running: { icon: "sync", color: "var(--accent)" },
  pending: { icon: "schedule", color: "var(--muted-2)" },
};

/** Every item of a background job with what has happened to it — the AI
 *  queue's answer to the import task's file list.
 *
 *  It exists because a batch job is now ONE job for a whole import rather
 *  than one per uploaded batch: a single "1 / 4000" progress bar says how far
 *  the run has got and nothing about which pictures that covers.
 *
 *  Per-item state is derived server-side from the job's one cursor, so this
 *  costs no bookkeeping anywhere — see `GET /api/ml/jobs/{id}/progress`. */
export function JobItemsOverlay({ job, label, onClose }:
  { job: JobOut; label: string; onClose: () => void }) {
  const [total, setTotal] = useState(job.item_count);
  const [done, setDone] = useState(job.done_count);
  // offset -> that page's items. Kept across ticks so a poll repaints the
  // visible page instead of emptying the list under the pointer.
  const [pages, setPages] = useState<Record<number, JobItem[]>>({});
  const [tick, setTick] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const win = useWindowedList({
    count: total, rowHeight: ROW_H, scrollRef, minCount: 60,
  });
  const active = job.status === "running" || job.status === "queued";

  // While the job is moving, ask again — the answer for a given item changes
  // exactly once (pending → running → done), and only near the cursor.
  useEffect(() => {
    if (!active) return;
    const h = setInterval(() => setTick((n) => n + 1), 1500);
    return () => clearInterval(h);
  }, [active]);

  // Fetch the pages the viewport covers (plus the first, which carries the
  // totals). A page already held is re-fetched only on a tick.
  const first = Math.floor(win.start / PAGE) * PAGE;
  const last = Math.floor(Math.max(win.end - 1, 0) / PAGE) * PAGE;
  useEffect(() => {
    let dropped = false;
    const wanted = first === last ? [first] : [first, last];
    (async () => {
      for (const off of wanted) {
        try {
          const p = await api.jobProgress(job.id, off, PAGE);
          if (dropped) return;
          setTotal(p.total);
          setDone(p.done);
          setPages((prev) => ({ ...prev, [off]: p.items }));
        } catch { /* the row is still in the list; the next tick retries */ }
      }
    })();
    return () => { dropped = true; };
  }, [job.id, first, last, tick]);

  const rowAt = (i: number): JobItem | null => {
    const page = pages[Math.floor(i / PAGE) * PAGE];
    return page ? page[i % PAGE] ?? null : null;
  };
  const listStyle: React.CSSProperties = {
    display: "flex", flexDirection: "column", gap: 3,
  };
  const rows = [];
  for (let i = win.start; i < win.end; i++) rows.push(i);

  return (
    <Overlay
      icon="checklist"
      title={label}
      subtitle={`${done} of ${total} done${job.status === "paused" ? " · paused"
        : job.status === "running" ? " · running" : ""}`}
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
            {rows.map((i) => {
              const it = rowAt(i);
              const s = STATE_ICON[it?.status ?? "pending"] ?? STATE_ICON.pending;
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 8px", borderRadius: "var(--r-3)", background: "var(--panel-3)", border: "1px solid var(--border)" }}>
                  <Icon name={s.icon} size={15} color={s.color}
                        spin={it?.status === "running"} />
                  <div style={{ flex: 1, minWidth: 0, fontFamily: "var(--mono)", fontSize: "var(--fs-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: it ? "var(--text-3)" : "var(--muted-3)" }}>
                    {/* A row whose page has not arrived says so by being a
                        placeholder rather than by being absent — the list is
                        as long as the job, whatever has been fetched. */}
                    {it ? (it.name || `Item #${it.id}`) : "…"}
                  </div>
                  <span style={{ fontSize: "var(--fs-1)", color: s.color, flex: "0 0 auto", minWidth: 56, textAlign: "right" }}>
                    {it?.status ?? ""}
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
