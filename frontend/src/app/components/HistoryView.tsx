import React, { useMemo, useRef, useState } from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { Chip } from "../../shared/Chip";
import { SectionHeading } from "../../shared/SectionHeading";
import { IconButton } from "../../shared/IconButton";
import { Button } from "../../shared/Button";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { api, EventOut, SummaryVar } from "../api";
import { useUI } from "../store";
import { useT, useTn, type TFn, useNum } from "../i18n";
import { ActionMeta, metaFor } from "../historyActions";

/** An event's sentence, in the UI language where the row carries its
 *  template. `summary_key` + `summary_vars` are looked up and re-filled —
 *  a var may itself be a nested {key, vars, text} (the "Reverted: …" case),
 *  resolved one level at a time. A miss (or an old row with no template)
 *  falls back through `t` so a STATIC summary that is its own template
 *  still translates, and an unknown one reads as the stored English. */
function summaryText(e: EventOut, t: TFn): string {
  const resolve = (key: string, vars: Record<string, SummaryVar>): string => {
    const filled: Record<string, string> = {};
    for (const [k, v] of Object.entries(vars))
      filled[k] = typeof v === "string" ? v : resolve(v.key, v.vars);
    return t(key, filled);
  };
  if (e.summary_key) return resolve(e.summary_key, e.summary_vars ?? {});
  return t(e.summary || e.action);
}
import { Icon } from "../../shared/Icon";
import { ConfirmModal } from "../../shared/ConfirmModal";
import { useDateFormatters } from "../../shared/time";
import { useWindowedList } from "../useWindowedList";
import { useHoverGuard } from "./shared/useHoverGuard";
import { useBackdropDismiss } from "../../shared/Backdrop";

// Events per fetched page; "Load more" appends the next page.
const PAGE_SIZE = 500;
// Estimated stride of one list row (row minHeight + list gap) for the
// windowed list — rows keep their natural height, this only sizes the window.
const HIST_ROW_H = 46;

// Consecutive events of the same action + source within this many milliseconds
// collapse into a single summary row (expandable). "A short timeframe."
const GROUP_WINDOW_MS = 2 * 60 * 1000;


// Per-event icon/color. A set_hidden event's glyph reflects whether it hid or
// revealed the item, rather than a single fixed icon for both directions.
function iconFor(e: EventOut): { icon: string; color: string } {
  if (e.action === "set_hidden") {
    const hidden = !!e.data?.hidden;
    return { icon: hidden ? "visibility_off" : "visibility", color: "var(--muted)" };
  }
  const m = metaFor(e.action);
  return { icon: m.icon, color: m.color };
}

interface Group {
  key: string;
  action: string;
  source: string;
  username: string;
  events: EventOut[];
  firstTime: number;
  lastTime: number;
}

function groupEvents(events: EventOut[]): Group[] {
  const groups: Group[] = [];
  let cur: Group | null = null;
  for (const e of events) {
    const t = new Date(e.created_at).getTime();
    if (
      cur &&
      cur.action === e.action &&
      cur.source === e.source &&
      // Keep each user's run separate so a group's attribution is unambiguous.
      cur.username === (e.username || "") &&
      Math.abs(cur.lastTime - t) <= GROUP_WINDOW_MS
    ) {
      cur.events.push(e);
      cur.lastTime = t;
    } else {
      cur = { key: `${e.id}`, action: e.action, source: e.source, username: e.username || "", events: [e], firstTime: t, lastTime: t };
      groups.push(cur);
    }
  }
  return groups;
}

const dayKey = (iso: string) => new Date(iso).toDateString();
// A day-group label: "Today" / "Yesterday", else the formatted day header. Takes
// the settings-bound formatter (timestamps follow the user's date/time prefs).
const dayLabel = (iso: string, formatDayHeader: (v: string) => string, tr: (s: string) => string) => {
  const d = new Date(iso);
  const today = new Date();
  const yest = new Date();
  yest.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return tr("Today");
  if (d.toDateString() === yest.toDateString()) return tr("Yesterday");
  return formatDayHeader(iso);
};

function Checkbox({ checked, onChange, disabled }: { checked: boolean; onChange: () => void; disabled?: boolean }) {
  return (
    <span
      onClick={(e) => { e.stopPropagation(); if (!disabled) onChange(); }}
      title={disabled ? "Not revertible" : checked ? "Deselect" : "Select"}
      style={{
        width: 17, height: 17, flex: "0 0 auto", borderRadius: "var(--r-1)",
        border: `1px solid ${checked ? "var(--accent)" : "var(--border-strong)"}`,
        background: checked ? "var(--accent)" : "transparent",
        display: "flex", alignItems: "center", justifyContent: "center",
        cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.35 : 1,
      }}
    >
      {checked && <Icon name="check" size={12} color="var(--on-accent)" />}
    </span>
  );
}

function SourceBadge({ source }: { source: string }) {
  const t = useT();
  const cli = source === "cli";
  // The third source is a background AI job; it wore the browser's globe
  // and "Made in the app" for as long as only the CLI was told apart.
  const ai = source === "ai";
  return (
    <Chip size="sm" mono upper bordered
      title={cli ? t("Made by the CLI or a script") : ai ? t("Made by a background AI job") : t("Made in the app")}
    >
      <Icon name={cli ? "terminal" : ai ? "smart_toy" : "public"} size={11} /> {source}
    </Chip>
  );
}

// Who made the change. Only rendered when a username is known — so a single-user
// (anonymous) library looks exactly as before, and attribution surfaces only
// once multiple people share the library.
function UserBadge({ username }: { username: string }) {
  const t = useT();
  if (!username) return null;
  return (
    <span
      title={t("By {name}", { name: username })}
      style={{
        display: "inline-flex", alignItems: "center", gap: 3, maxWidth: 140,
        fontSize: "var(--fs-0)", fontFamily: "var(--mono)", letterSpacing: "0.02em",
        padding: "1px 6px", borderRadius: "var(--r-1)", border: "1px solid var(--border)",
        color: "var(--muted-2)", background: "var(--panel-2)", flex: "0 0 auto",
      }}
    >
      <Icon name={RECORD_ICON.subject} size={11} />
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {username}
      </span>
    </span>
  );
}

export function HistoryView() {
  const qc = useQueryClient();
  const tr = useT();
  const tn = useTn();
  const num = useNum();
  const { formatDayHeader } = useDateFormatters();
  const { setView, setSelectedItems, historyFilter, setHistoryFilter } = useUI();
  // Paged: the first 500 events load up front, "Load more" appends the next
  // page. Invalidating ["history"] (a revert does) refetches the loaded pages.
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ["history"],
    queryFn: ({ pageParam }) => api.history(PAGE_SIZE, pageParam as number),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      const loaded = all.reduce((n, p) => n + p.events.length, 0);
      return last.events.length === PAGE_SIZE && loaded < last.total
        ? loaded : undefined;
    },
  });
  const totalRecorded = data?.pages[data.pages.length - 1]?.total ?? 0;
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  // When set, the list is narrowed to one reverted event and the revert(s) that
  // undid it — driven by the hover button on a reverted row.
  const [revertFocus, setRevertFocus] = useState<number | null>(null);

  const allEvents = useMemo(
    () => (data?.pages ?? []).flatMap((p) => p.events), [data]);
  // Optional filter: only changes that touched one of the selected items.
  const filterSet = useMemo(() => new Set(historyFilter), [historyFilter]);
  const events = useMemo(() => {
    // A revert-pair focus takes precedence: show just the reverted event and the
    // revert event(s) referencing it.
    if (revertFocus != null) {
      return allEvents.filter(
        (e) => e.id === revertFocus ||
          (e.action === "revert" && e.data?.reverted_event_id === revertFocus)
      );
    }
    if (filterSet.size === 0) return allEvents;
    return allEvents.filter(
      (e) =>
        (e.entity_type === "item" && e.entity_id != null && filterSet.has(e.entity_id)) ||
        (typeof e.data?.item_id === "number" && filterSet.has(e.data.item_id as number))
    );
  }, [allEvents, filterSet, revertFocus]);
  const groups = useMemo(() => groupEvents(events), [events]);

  // The list flattened to one row per rendered block — a day header or a
  // group — so the window can slice it. Built once per data change, not
  // inline in the render.
  type HistRow =
    | { kind: "day"; key: string; iso: string }
    | { kind: "group"; key: string; g: Group };
  const flatRows = useMemo(() => {
    const out: HistRow[] = [];
    let lastDay = "";
    for (const g of groups) {
      const iso = g.events[0].created_at;
      if (dayKey(iso) !== lastDay) {
        lastDay = dayKey(iso);
        out.push({ kind: "day", key: `day-${lastDay}`, iso });
      }
      out.push({ kind: "group", key: g.key, g });
    }
    return out;
  }, [groups]);

  // Windowed rows: a long history mounts only a viewport's worth. The row
  // height is an estimate (day headers and expanded groups differ), which the
  // hook tolerates — rows render at natural height inside the window.
  const scrollRef = useRef<HTMLDivElement>(null);
  const win = useWindowedList({
    count: flatRows.length, rowHeight: HIST_ROW_H, scrollRef, minCount: 150,
  });

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const revertibleIds = (g: Group) => g.events.filter((e) => e.revertible).map((e) => e.id);
  const groupChecked = (g: Group) => {
    const ids = revertibleIds(g);
    return ids.length > 0 && ids.every((id) => selected.has(id));
  };
  const toggleGroup = (g: Group) =>
    setSelected((prev) => {
      const next = new Set(prev);
      const ids = revertibleIds(g);
      const all = ids.every((id) => next.has(id));
      ids.forEach((id) => (all ? next.delete(id) : next.add(id)));
      return next;
    });

  const openItem = (e: EventOut) => {
    if (e.entity_type === "item" && e.entity_id != null) {
      setSelectedItems([e.entity_id]);
      setView("library");
    }
  };

  const revert = async () => {
    if (selected.size === 0 || busy) return;
    setBusy(true);
    try {
      await api.revertEvents([...selected]);
    } finally {
      setBusy(false);
    }
    setSelected(new Set());
    // A revert changes items/tags/groups — and, since the face actions log and
    // revert too, the crops and the people they hang under. Refresh everything
    // the change could touch (plus the log itself).
    for (const k of ["history", "items", "item", "tags", "groups", "facets",
                     "library-stats", "faces", "faces-named", "faces-unnamed",
                     "subjects"])
      qc.invalidateQueries({ queryKey: [k] });
  };

  const selectableTotal = events.filter((e) => e.revertible).length;

  // `:hover` is resolved from pointer events, so scrolling this list under a
  // stationary cursor leaves the old row's action button lit. See the hook.
  useHoverGuard(scrollRef, [events.length]);

  const [clearing, setClearing] = useState<"asking" | "busy" | null>(null);
  const clearAll = async () => {
    setClearing("busy");
    try {
      await api.clearHistory();
      setSelected(new Set());
      setRevertFocus(null);
      await qc.invalidateQueries({ queryKey: ["history"] });
    } finally {
      setClearing(null);
    }
  };

  return (
    <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", minHeight: 0, background: "var(--bg)" }}>
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "28px 32px 80px" }}>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text-bright)" }}>{tr("History")}</div>
            <div style={{ fontSize: "var(--fs-3)", color: "var(--muted)", marginTop: 3 }}>
              {revertFocus != null
                ? tn({ one: "1 entry — a reverted change and its revert",
                       other: "{n} entries — a reverted change and its revert" },
                     events.length)
                : filterSet.size > 0
                ? tn({ one: "{changes} to 1 selected item",
                       other: "{changes} to {n} selected items" },
                     filterSet.size,
                     { changes: tn({ one: "1 change", other: "{n} changes" },
                                   events.length) })
                : allEvents.length === 0
                ? tr("No changes recorded yet.")
                : tn({ one: "1 change · newest first",
                       other: "{n} changes · newest first" },
                     totalRecorded || allEvents.length)}
            </div>
            {filterSet.size > 0 && revertFocus == null && (
              <Chip tone="accent" size="lg" round bordered icon="filter_alt" style={{ marginTop: 8 }}
                    onClick={() => setHistoryFilter([])}>
                {tr("Filtered to selected items")}
                <Icon name="close" size={14} />
              </Chip>
            )}
            {revertFocus != null && (
              <Chip tone="accent" size="lg" round bordered icon="filter_alt" style={{ marginTop: 8 }}
                    onClick={() => setRevertFocus(null)}>
                {tr("Showing a change and its revert")}
                <Icon name="close" size={14} />
              </Chip>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {/* Quiet, and only when there is something to clear. It is a
                destructive action nobody comes to this tab to perform, so it
                does not compete with Revert — which is what the tab is FOR
                and is drawn as the accent button beside it. */}
            {allEvents.length > 0 && revertFocus == null && (
              <Button variant="ghost" size="md"
        onClick={() => setClearing("asking")}
        disabled={busy || clearing === "busy"}
        title={tr("Delete every entry in the log")} style={{ color: "var(--muted)" }}>
                <Icon name="delete_sweep" size={16} />
                {tr("Clear history")}
              </Button>
            )}
            {selected.size > 0 && (
              <Button variant="primary" size="md"
        onClick={revert}
        disabled={busy}>
                <Icon name="undo" size={16} />
                {tr("Revert")} {selected.size} {tr("selected")}
              </Button>
            )}
          </div>
        </div>

        {clearing && (
          <ConfirmModal t={tr}
            title={tr("Clear the history?")}
            body={<>
              <div>
                {num(totalRecorded || allEvents.length)}{" "}
                {tr("entries will be deleted. Your items, tags, groups and files are not touched — only the record of how they got that way.")}
              </div>
              <div style={{ color: "var(--yellow-text)", marginTop: 8 }}>
                {tr("Undo works by reading these entries, so everything done up to now becomes permanent. This cannot itself be undone.")}
              </div>
            </>}
            answer={{ label: tr("Clear history"), danger: true, busy: tr("Clearing…"), run: clearAll }}
            onResult={() => setClearing(null)} />
        )}

        {events.length === 0 ? (
          <div
            style={{
              display: "flex", flexDirection: "column", alignItems: "center", gap: 10,
              padding: "60px 20px", color: "var(--muted-2)", textAlign: "center",
            }}
          >
            <Icon name="history" size={40} color="var(--muted-3)" />
            <div style={{ fontSize: "var(--fs-4)" }}>
              {filterSet.size > 0 ? (
                tn({ one: "No recorded changes for the selected item.",
                     other: "No recorded changes for the selected items." },
                   filterSet.size)
              ) : (
                <>
                  Changes you make — tagging, grouping, importing, deleting — will appear here,
                  <br />with the option to revert them.
                </>
              )}
            </div>
          </div>
        ) : (
          <div>
            {selectableTotal > 0 && (
              <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginBottom: 6 }}>
                {tn({ one: "1 revertible · select rows to revert them",
                      other: "{n} revertible · select rows to revert them" },
                    selectableTotal)}
              </div>
            )}
            <div
              ref={win.containerRef}
              style={win.windowed
                ? { height: win.totalHeight, position: "relative" }
                : undefined}
            >
              <div style={win.windowed
                ? { position: "absolute", top: win.topOffset, left: 0, right: 0,
                    display: "flex", flexDirection: "column", gap: 4 }
                : { display: "flex", flexDirection: "column", gap: 4 }}
              >
                {flatRows.slice(win.start, win.end).map((row, j) => {
                  const i = win.start + j;
                  if (row.kind === "day") {
                    return (
                      <SectionHeading sm key={row.key} style={{ margin: i ? "16px 0 4px" : "0 0 4px" }}>
                        {dayLabel(row.iso, formatDayHeader, tr)}
                      </SectionHeading>
                    );
                  }
                  const g = row.g;
                  return (
                    <GroupRow
                      key={row.key}
                      group={g}
                      expanded={expanded.has(g.key)}
                      onToggleExpand={() => setExpanded((p) => { const n = new Set(p); n.has(g.key) ? n.delete(g.key) : n.add(g.key); return n; })}
                      selected={selected}
                      onToggleEvent={toggle}
                      groupChecked={groupChecked(g)}
                      onToggleGroup={() => toggleGroup(g)}
                      onOpenItem={openItem}
                      onShowRevertPair={setRevertFocus}
                    />
                  );
                })}
              </div>
            </div>
            {/* Older pages, on request — loading tens of thousands of events
                up front was the whole page's cost. Hidden while a revert-pair
                focus or an item filter is narrowing the list: "more" there
                reads as "more matches", which one page cannot promise. */}
            {hasNextPage && revertFocus == null && filterSet.size === 0 && (
              <Button variant="soft" size="sm"
        onClick={() => void fetchNextPage()}
        disabled={isFetchingNextPage} style={{ marginTop: 12 }}>
                <Icon name="expand_more" size={15} />
                {isFetchingNextPage ? tr("Loading…") : tr("Load more")}
                <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>
                  {num(allEvents.length)} / {num(totalRecorded)}
                </span>
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// A word-level diff of two strings (LCS over whitespace-delimited tokens), used
// to show what changed in a caption edit.
type DiffPart = { t: "same" | "add" | "del"; s: string };
function wordDiff(oldText: string, newText: string): DiffPart[] {
  const a = oldText.split(/(\s+)/);
  const b = newText.split(/(\s+)/);
  const n = a.length, m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: DiffPart[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ t: "same", s: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: "del", s: a[i] }); i++; }
    else { out.push({ t: "add", s: b[j] }); j++; }
  }
  while (i < n) out.push({ t: "del", s: a[i++] });
  while (j < m) out.push({ t: "add", s: b[j++] });
  return out;
}

/** The full new caption text with the changed parts highlighted (removed words
 *  in struck-through red, added words in green). */
function CaptionDiff({ oldText, newText }: { oldText: string; newText: string }) {
  const parts = wordDiff(oldText, newText);
  return (
    <div style={{ margin: "1px 10px 4px 34px", padding: "7px 9px", background: "var(--panel-3)", border: "1px solid var(--border)", borderRadius: "var(--r-3)", fontSize: "var(--fs-2)", lineHeight: 1.6, whiteSpace: "pre-wrap", overflowWrap: "anywhere", userSelect: "text", WebkitUserSelect: "text" }}>
      {parts.map((p, i) =>
        p.t === "same" ? <span key={i} style={{ color: "var(--text-2)" }}>{p.s}</span>
          : p.t === "del" ? <span key={i} style={{ color: "var(--red-text)", textDecoration: "line-through" }}>{p.s}</span>
            : <span key={i} style={{ color: "var(--green-text)", background: "var(--green-dim)", borderRadius: 3 }}>{p.s}</span>
      )}
    </div>
  );
}



function EventRow({
  e, indent, source, selected, onToggle, onOpen, onShowRevertPair,
}: {
  e: EventOut; indent?: boolean; source?: string; selected: boolean; onToggle: () => void; onOpen: () => void;
  onShowRevertPair?: (id: number) => void;
}) {
  const tr = useT();
  const m = iconFor(e);
  const { formatTime } = useDateFormatters();
  const gotoItem = e.entity_type === "item" && e.entity_id != null;
  const [showDiff, setShowDiff] = useState(false);
  // Caption edits can show a full-text diff of the change.
  const canDiff = e.action === "edit_caption" && typeof e.data?.old_text === "string" && typeof e.data?.text === "string";
  // Clicking anywhere on the row toggles its revert-selection (when the event
  // can be reverted). Jumping to the item is a separate hover button so the two
  // actions don't collide. The hover buttons fade in via CSS (`.hoverable:hover
  // .row-action-fixed`) rather than a JS hover state — a JS onMouseLeave is
  // unreliable when the DOM updates under the cursor or focus shifts on click,
  // which left the button stuck visible after the pointer had left the row.
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
    <div
      className="hoverable"
      onClick={() => { if (e.revertible) onToggle(); }}
      style={{
        display: "flex", alignItems: "center", gap: 10, minHeight: 34,
        padding: "5px 10px", paddingLeft: indent ? 34 : 10, borderRadius: "var(--r-3)",
        background: selected ? "var(--accent-dim)" : indent ? "transparent" : "var(--panel-2)",
        border: `1px solid ${selected ? "var(--accent)" : indent ? "transparent" : "var(--border)"}`,
        cursor: e.revertible ? "pointer" : "default",
        opacity: e.reverted ? 0.5 : 1,
      }}
    >
      <Checkbox checked={selected} onChange={onToggle} disabled={!e.revertible} />
      <Icon name={m.icon} size={16} color={m.color} />
      <span
        style={{
          flex: 1, minWidth: 0, fontSize: "var(--fs-3)", color: "var(--text-2)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          textDecoration: e.reverted ? "line-through" : "none",
        }}
      >
        {summaryText(e, tr)}
      </span>
      {e.reverted && (
        <span style={{ fontSize: "var(--fs-0)", color: "var(--muted-2)", fontFamily: "var(--mono)", textTransform: "uppercase" }}>{tr("reverted")}</span>
      )}
      {/* On a reverted row, a hover button narrows the list to this change and
          the revert that undid it. */}
      {e.reverted && onShowRevertPair && (
        <IconButton icon="filter_alt" size={22} glyph={14} reveal="fixed" tone="accent" bordered fill="panel"
          onClick={(ev) => { ev.stopPropagation(); onShowRevertPair(e.id); }}
          title={tr("Show this change and its revert")} style={{ flex: "0 0 auto" }} />
      )}
      {gotoItem && (
        <IconButton icon="open_in_new" size={22} glyph={14} reveal="fixed" tone="accent" bordered fill="panel"
          onClick={(ev) => { ev.stopPropagation(); onOpen(); }}
          title={tr("Go to this item")} style={{ flex: "0 0 auto" }} />
      )}
      {/* A caption edit can expand to a full-text diff of the change. The diff
          button stays visible while the diff is open (inline opacity wins over
          the class), otherwise it fades in on row hover like the others. */}
      {canDiff && (
        <span
          className="row-action-fixed"
          onClick={(ev) => { ev.stopPropagation(); setShowDiff((v) => !v); }}
          title={showDiff ? tr("Hide the change") : tr("Show what changed")}
          style={{
            width: 22, height: 22, flex: "0 0 auto", borderRadius: "var(--r-2)",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: showDiff ? "var(--accent)" : "var(--muted-2)", cursor: "pointer",
            background: "var(--panel-3)", border: "1px solid var(--border)",
            ...(showDiff ? { opacity: 1 } : null),
          }}
        >
          <Icon name="difference" size={14} />
        </span>
      )}
      {/* Source + user badges sit left of the timestamp — the same place a
          grouped row shows them, so placement is consistent across row types. */}
      {source && <SourceBadge source={source} />}
      {source && <UserBadge username={e.username} />}
      <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", fontFamily: "var(--mono)", flex: "0 0 auto" }}>
        {formatTime(e.created_at)}
      </span>
    </div>
    {canDiff && showDiff && (
      <CaptionDiff oldText={String(e.data!.old_text)} newText={String(e.data!.text)} />
    )}
    </div>
  );
}

function GroupRow({
  group, expanded, onToggleExpand, selected, onToggleEvent, groupChecked, onToggleGroup, onOpenItem, onShowRevertPair,
}: {
  group: Group;
  expanded: boolean;
  onToggleExpand: () => void;
  selected: Set<number>;
  onToggleEvent: (id: number) => void;
  groupChecked: boolean;
  onToggleGroup: () => void;
  onOpenItem: (e: EventOut) => void;
  onShowRevertPair?: (id: number) => void;
}) {
  const tn = useTn();
  const { formatTime } = useDateFormatters();
  // A single-event group renders as a plain row (source badge lives inside the
  // row, left of the timestamp — same placement as the grouped header below).
  if (group.events.length === 1) {
    const e = group.events[0];
    return (
      <EventRow
        e={e}
        source={group.source}
        selected={selected.has(e.id)}
        onToggle={() => onToggleEvent(e.id)}
        onOpen={() => onOpenItem(e)}
        onShowRevertPair={onShowRevertPair}
      />
    );
  }

  const m = metaFor(group.action);
  const n = group.events.length;
  // Grouped hide/show toggles: a run may flip the same item on and off several
  // times, so "Hid N items" would be misleading. Summarize as a toggle count —
  // "Toggled hidden X times" for a single item, or "…for Y items" (unique items,
  // not the number of changes) when several were involved. The icon reflects the
  // last (newest) state; group.events[0] is newest.
  const newest = group.events[0];
  const uniqueItems = group.action === "set_hidden"
    ? new Set(group.events.map((e) => (e.data?.item_id ?? e.entity_id))).size
    : n;
  const headerIcon = group.action === "set_hidden" ? iconFor(newest) : { icon: m.icon, color: m.color };
  const headerLabel = group.action === "set_hidden"
    ? (uniqueItems > 1
        ? tn({ one: "Toggled hidden for 1 item",
               other: "Toggled hidden for {n} items" }, uniqueItems)
        : tn({ one: "Toggled hidden 1 time",
               other: "Toggled hidden {n} times" }, n))
    : tn(m.verb, n);
  const anyRevertible = group.events.some((e) => e.revertible);
  const allReverted = group.events.every((e) => e.reverted);
  return (
    <div>
      <div
        onClick={onToggleExpand}
        style={{
          display: "flex", alignItems: "center", gap: 10, minHeight: 36,
          padding: "5px 10px", borderRadius: "var(--r-3)", cursor: "pointer",
          background: "var(--panel-2)", border: "1px solid var(--border)",
          opacity: allReverted ? 0.5 : 1,
        }}
      >
        <Checkbox checked={groupChecked} onChange={onToggleGroup} disabled={!anyRevertible} />
        <Icon name={expanded ? "expand_more" : "chevron_right"} size={16} color="var(--muted-2)" />
        <Icon name={headerIcon.icon} size={16} color={headerIcon.color} />
        <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text-bright)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {headerLabel}
        </span>
        <SourceBadge source={group.source} />
        <UserBadge username={group.username} />
        <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", fontFamily: "var(--mono)", flex: "0 0 auto" }}>
          {(() => {
            // The formatter shows minute precision, so a group whose first and
            // last events fall in the same minute renders as a single time
            // rather than a "20:09–20:09" range.
            const start = formatTime(group.events[group.events.length - 1].created_at);
            const end = formatTime(group.events[0].created_at);
            return start === end ? start : `${start}–${end}`;
          })()}
        </span>
      </div>
      {expanded && (
        <div style={{ display: "flex", flexDirection: "column", gap: 1, marginTop: 2, marginBottom: 2 }}>
          {group.events.map((e) => (
            <EventRow key={e.id} e={e} indent selected={selected.has(e.id)} onToggle={() => onToggleEvent(e.id)} onOpen={() => onOpenItem(e)} onShowRevertPair={onShowRevertPair} />
          ))}
        </div>
      )}
    </div>
  );
}
