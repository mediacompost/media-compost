/** Sort a BATCH of pictures for one tag on a fixed grid — the Tag grid.
 *
 * The tag batch's sibling for the mouse. Where that session shows one
 * picture and takes one key, this one shows a grid of pictures (columns ×
 * rows, the chooser says which) already sorted by the classifier — each
 * cell's BORDER says the answer: green fits, red doesn't fit, grey
 * undecided — and asks to be CORRECTED: every cell carries a capsule of
 * three fixed buttons on hover (+ / − / no tag) and an eye that opens the
 * preview, Next batch writes the borders as they stand, and the next batch
 * is refit from what was just written. Its OWN action with its own chooser,
 * feed and store flag; nothing here is a mode of `TagSortOverlay`, and the
 * two share only the classifier and the pool rules on the server.
 *
 * A CARD NEVER MOVES. Its position in the grid is the batch's score order
 * and it keeps it whatever its answer becomes — a card that jumped bands as
 * its border changed would move the very thing the pointer was over.
 *
 * NOTHING IS SELECTED UNTIL A KEY ASKS. The mouse is primary and a cursor
 * ring on a card nobody pointed at reads as a suggestion; the first arrow
 * press lands on the first card. Then: ↑/↓ walk the cards in reading order,
 * ←/→ turn the cursor's answer, 1/2/3 set it, Space opens Quick Look on it
 * (the ordinary preview — its sidebar, its T field — which is why this
 * session sits UNDER that overlay in `LAYER`), Enter is Next batch, U (or
 * ⌘Z) takes the previous batch back whole, T aims the quick tag field at
 * the cursor's card, Tab is the summary and Esc asks before ending.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { storage } from "../../shared/storage";
import { PlusMinus } from "../../shared/PlusMinus";
import { IconButton } from "../../shared/IconButton";
import { Button } from "../../shared/Button";
import { useSessionUndo } from "./shared/useSessionUndo";
import { ActionToast } from "./shared/ActionToast";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, TagGridItem, TagGridNextOut } from "../api";
import { patchRows, useItemPatches } from "./shared/useItemPatches";

/** How many pictures are fetched BEYOND the grid, to stand in for skipped
 *  cards without a round trip. */
const SPARES = 6;
import { EmbedModelPicker } from "./EmbedModelPicker";
import { Icon } from "../../shared/Icon";
import { LAYER } from "../../shared/layers";
import { quickTagIsOpen, useUI } from "../store";
import { useErrText, useT, useTn } from "../i18n";
import { useViewScope } from "../useItems";
import { bumpLibrary } from "../invalidation";
import { Overlay } from "../../shared/Overlay";
import { Cap } from "./shared/JudgeCard";
import { useSessionKeys } from "./shared/useSessionKeys";
import { SessionTrouble, SessionWait } from "./shared/SessionStates";
import { sessionBody } from "../sessionBody";
import { card, OptionRow, sectionLabel } from "./ImportOverlay";
import { fetchTagNameSuggestions, TagAutocomplete } from "./TagAutocomplete";
import { useDebouncedValue } from "../../shared/useDebounced";
import {
  canSayBoth, tagNames, wireTags, withCounter, withoutTag,
  withTag, renameTag, writeIsEmpty,
  Answers, ANSWERS, Assignment, batchSize, cycleAll, cycleAssignment, embeddersOf,
  FUSED, GRID_COLS, offered, startAnswer, writeFor,
  GRID_ROWS, parseTagGridConfig, serializeTagGridConfig, stepCursor,
  summarizeBatches, TAGGRID_KEY, TagGridConfig,
} from "../tagGrid";
import type { GridTag } from "../tagGrid";
import type { GroupNode } from "../api";
import { SignName } from "./TagSortOverlay";
import { flattenGroupTree } from "./GroupSelect";
import { ConfirmModal } from "../../shared/ConfirmModal";

interface Run {
  config: TagGridConfig;
  /** The resolved embed model ids — one, or every listed one for `FUSED`. */
  embedders: string[];
  /** The answers this session offers (`offered(config.answers)`). */
  allowed: Assignment[];
}

/** One committed batch: what was on screen, how it was answered, and the
 *  event fans the writes produced — everything U needs to take it back. */
interface BatchRecord {
  items: TagGridItem[];
  assign: Map<number, Assignment>;
  written: { id: number; eventIds: number[] }[];
}

/** The ring colours — what a cell SAYS. Opaque and saturated: the ring is
 *  drawn over the dark sheet, where the text tints read washed out. */
const COLOR: Record<Assignment, string> = {
  positive: "var(--green)",
  none: "var(--muted)",
  negative: "var(--red)",
  // Both tags at once — the only saturated token left, and the legend
  // names it; the amber-means-a-guess rule is about tag and face ROWS.
  both: "var(--yellow)",
};

/** The answers a config offers — "both" only where the negative answer
 *  writes something to have both of (`canSayBoth`). */
function allowedOf(cfg: TagGridConfig): Assignment[] {
  return offered(cfg.answers, cfg.bothAnswer && canSayBoth(cfg));
}

export function TagGridOverlay() {
  const t = useT();
  const tn = useTn();
  const errText = useErrText();
  const qc = useQueryClient();
  const open = useUI((s) => s.tagGridOpen);
  const setOpen = useUI((s) => s.setTagGridOpen);
  const inLibrary = useUI((s) => s.view) === "library";
  const view = useViewScope(inLibrary && open);

  // ---- configuration (the chooser) ----------------------------------------
  const [cfg, setCfg] = useState<TagGridConfig>(
    () => parseTagGridConfig(storage.get(TAGGRID_KEY)));
  const [running, setRunning] = useState<Run | null>(null);

  // ---- session state -------------------------------------------------------
  const [batch, setBatch] = useState<TagGridItem[]>([]);
  //: THE CARDS FOLLOW THE ITEM: a rotation made in the preview over this
  //  session lands in the item's detail, and the batch's rows (and the
  //  spares waiting behind them) take the new file, angle and thumb token
  //  from it — or the card kept the old thumbnail under a preview that had
  //  already turned.
  useItemPatches((d) => {
    setBatch((cur) => patchRows(cur, d));
    spare.current = patchRows(spare.current, d);
  });
  // THE SPARES: a few pictures fetched beyond the grid, so a card skipped
  // with its ✕ is replaced at once by the next one rather than by a hole or
  // a whole refetch. A REF — a skip must find the spare that is there now,
  // not the one a render ago — and every batch fetch refills it.
  const spare = useRef<TagGridItem[]>([]);
  // The answers and the cursor are REFS as well as state, written
  // synchronously: an arrow and an Enter in one tick (before React renders
  // between them) must agree about which card the Enter is aimed at.
  const [assign, setAssignState] = useState<Map<number, Assignment>>(
    new Map());
  const assignRef = useRef<Map<number, Assignment>>(new Map());
  const setAssign = (
    v: Map<number, Assignment>
      | ((cur: Map<number, Assignment>) => Map<number, Assignment>),
  ) => {
    const next = typeof v === "function" ? v(assignRef.current) : v;
    assignRef.current = next;
    setAssignState(next);
  };
  const [cursor, setCursorState] = useState<number | null>(null);
  const cursorRef = useRef<number | null>(null);
  const setCursor = (id: number | null) => {
    cursorRef.current = id;
    setCursorState(id);
  };
  const [loading, setLoading] = useState(false);
  // The last fetch's failure — shown with a Try again where the batch would
  // be, rather than swallowed (the tag batch's rule; see `sessionBody`).
  const [failed, setFailed] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ordered, setOrdered] = useState(false);
  const [batchNo, setBatchNo] = useState(0);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  /** The chooser again, over a RUNNING session — the tag batch's Settings
   *  button: every setting changeable mid-run, and Continue takes over
   *  from the next batch. */
  const [configuring, setConfiguring] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const pool0 = useRef<number | null>(null);
  // NULL until the first reply carries the figure — the header omits it
  // then, rather than calling an uncounted pool "0 left".
  const [pool, setPool] = useState<number | null>(null);
  const recent = useRef<number[]>([]);
  // THE SESSION'S OWN NEGATIVES — the cards answered "doesn't fit" whose
  // answer wrote NOTHING, which past one tag is all of them: a conjunction's
  // "no" is `NOT a OR NOT b` and names no tag to write it on (`writeFor`).
  // They ride every fetch as `session_negatives`, so the classifier learns
  // from them within the session even though the library never hears of
  // them — the tag batch's rule for the same situation. They leave with
  // their batch when U takes it back, exactly as `recent` does.
  const sessionNeg = useRef<number[]>([]);
  const history = useSessionUndo<BatchRecord>();
  const [decided, setDecided] = useState(0);
  const scopeRef = useRef<Record<string, unknown> | null>(null);
  const cameFrom = useRef<HTMLElement | null>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const live = useRef({ running, batch, busy, loading, summaryOpen,
                        confirmEnd, configuring });
  live.current = { running, batch, busy, loading, summaryOpen, confirmEnd,
                   configuring };

  const syncPool = () =>
    setPool(pool0.current == null ? null
      : Math.max(0, pool0.current - recent.current.length));
  const syncDecided = () => {
    const s = summarizeBatches(history.steps);
    setDecided(s.positive + s.negative + s.both);
  };

  // Capture the scope the moment it opens — the session overlays' rule: the
  // session must not chase the grid under it.
  useEffect(() => {
    if (!open) return;
    if (scopeRef.current == null) {
      cameFrom.current = document.activeElement as HTMLElement | null;
      const sel = useUI.getState().selectedItems;
      scopeRef.current = {
        ...(useUI.getState().view === "library"
          ? ({ ...view.req } as unknown as Record<string, unknown>) : {}),
        ...(sel.length > 0 ? { items: sel } : {}),
      };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (open) return;
    const el = cameFrom.current;
    cameFrom.current = null;
    scopeRef.current = null;
    if (el && el.isConnected) el.focus();
  }, [open]);


  /** The scope every request sends: the captured view, PICTURES only (a
   *  film carries no vector and a container no picture), and the
   *  chooser's sequence rule on top. */
  const scopeBody = (config: TagGridConfig) => ({
    ...(scopeRef.current as object ?? {}),
    kind: "image",
    ...(config.skipSequenced ? { hide_sequenced: true } : {}),
  });

  // ---- the embedders ---------------------------------------------------------
  const { data: mlModels } = useQuery({
    queryKey: ["ml-models"], queryFn: api.mlModels, enabled: open });
  const { data: modelCache } = useQuery({
    queryKey: ["model-cache"], queryFn: api.modelCache, enabled: open });
  const embedModels = useMemo(() => {
    const cached = new Map((modelCache?.models ?? [])
      .map((m) => [m.key, m.cached]));
    const task = (mlModels?.tasks ?? []).find((tk) => tk.kind === "embed");
    return (task?.models ?? []).map((m) => ({
      id: m.id, name: m.name, family: m.family,
      ready: m.available
        && (m.family_keys ?? []).every((k) => cached.get(k) !== false),
      key: m.family_keys?.[0] ?? null,
    }));
  }, [mlModels, modelCache]);
  const embedIds = embedModels.map((m) => m.id);
  // The picker's rows: every model, then — with two or more — the fused
  // option, which is every space at once (each fit on its own, the scores
  // averaged).
  const pickerModels = useMemo(() => {
    const rows = embedModels.map((m) => ({ id: m.id, name: m.name,
                                           family: m.family }));
    if (embedModels.length >= 2) {
      rows.push({ id: FUSED,
                  name: embedModels.map((m) => m.name).join(" + "),
                  family: "fused" });
    }
    return rows;
  }, [embedModels]);
  const embedders = embeddersOf(cfg.embedder, embedIds);
  const embedderChoice = cfg.embedder === FUSED && embedModels.length >= 2
    ? FUSED : (embedders[0] ?? cfg.embedder);
  const embedReady = embedders.length > 0 && embedders.every(
    (id) => embedModels.find((m) => m.id === id)?.ready);
  const chooserOpen = open && (running == null || configuring);
  const { data: jobsData } = useQuery({
    queryKey: ["ml-jobs"], queryFn: api.mlJobs,
    enabled: chooserOpen, refetchInterval: chooserOpen ? 2500 : false,
    refetchIntervalInBackground: true,
  });
  const embedJob = (jobsData?.jobs ?? []).find(
    (j) => j.kind === "embed"
      && (j.status === "running" || j.status === "queued")) ?? null;
  // The counter tag reaches the probe DEBOUNCED — the field writes the
  // config per keystroke, and a probe per keystroke is a request per
  // letter for a figure nobody reads mid-word.
  const probeTags = useDebouncedValue(
    JSON.stringify(wireTags(cfg, cfg.answers !== "no_negative")), 300);
  const probe = useQuery({
    queryKey: ["taggrid-probe", open, probeTags, embedders.join("|"),
               cfg.skipSequenced, cfg.includeTagged],
    enabled: chooserOpen && cfg.tags.length > 0,
    refetchInterval: chooserOpen && embedJob != null ? 3000 : false,
    refetchIntervalInBackground: true,
    // THE PREVIOUS ANSWER STAYS while a new key loads: without it every
    // option change emptied the probe, the coverage lines under the
    // sorting picker vanished and came back, and the dialog resized
    // around them for a frame.
    placeholderData: (prev) => prev,
    // The counter tag rides the probe as it rides the feed: its pictures
    // are decided (out of the pool's count) and its positives are labels
    // the fit learns from, so the coverage and the "assignments to learn
    // from" line must count them the way the session will.
    queryFn: () => api.tagGridNext({
      ...scopeBody(cfg), tags: JSON.parse(probeTags), count: 0, embedders,
      include_tagged: cfg.includeTagged,
    } as Parameters<typeof api.tagGridNext>[0])
      .then((r) => ({ ...r, total: r.total ?? 0 })),
  });
  const hadJob = useRef(false);
  useEffect(() => {
    if (embedJob != null) hadJob.current = true;
    else if (hadJob.current) {
      hadJob.current = false;
      void qc.invalidateQueries({ queryKey: ["taggrid-probe"] });
    }
  }, [embedJob != null, qc]);

  // ---- the batch ---------------------------------------------------------------
  const fetchBatch = async (run: Run) => {
    setLoading(true);
    setFailed(null);
    try {
      const got: TagGridNextOut = await api.tagGridNext({
        include_tagged: run.config.includeTagged,
        ...scopeBody(run.config),
        tags: wireTags(run.config, run.allowed.includes("negative")),
        count: batchSize(run.config) + SPARES,
        embedders: run.embedders, boundary: run.config.boundary,
        recent: recent.current,
        session_negatives: sessionNeg.current,
        want_pool: pool0.current == null,
      } as Parameters<typeof api.tagGridNext>[0]);
      if (got.pool != null) pool0.current = got.pool + recent.current.length;
      syncPool();
      setOrdered(got.ordered);
      // The grid takes its size; what is left over waits as the spares.
      const queue = got.queue.slice(0, batchSize(run.config));
      spare.current = got.queue.slice(batchSize(run.config));
      setBatch(queue);
      setAssign(new Map(queue.map(
        (q) => [q.item_id, startAnswer(q.bucket, run.allowed, q.existing)])));
      setCursor(null);
      setBatchNo((n) => n + 1);
      return queue;
    } catch (e) {
      setFailed(errText(e));
      return undefined;
    } finally {
      setLoading(false);
    }
  };

  /** THE ✕ ON A CARD: skip this picture — nothing written, out of the
   *  session's pool through `recent` (Space's rule in the tag batch) — and
   *  put the next spare in its PLACE, so the grid stays full and nothing
   *  else moves. With the spares gone a handful more are fetched, excluding
   *  everything on screen; a skip with nothing left anywhere leaves a hole. */
  const skip = async (itemId: number) => {
    const st = live.current;
    if (!st.running || st.busy) return;
    const run = st.running;
    recent.current.push(itemId);
    syncPool();
    if (spare.current.length === 0) {
      try {
        const got: TagGridNextOut = await api.tagGridNext({
          include_tagged: run.config.includeTagged,
          ...scopeBody(run.config),
          tags: wireTags(run.config, run.allowed.includes("negative")),
          count: SPARES,
          embedders: run.embedders, boundary: run.config.boundary,
          recent: [...recent.current,
                   ...live.current.batch.map((it) => it.item_id)],
          session_negatives: sessionNeg.current,
          want_pool: false,
        } as Parameters<typeof api.tagGridNext>[0]);
        spare.current = got.queue;
      } catch (e) {
        setFailed(errText(e));
      }
    }
    const repl = spare.current.shift();
    const cur = live.current.batch;
    const at = cur.findIndex((it) => it.item_id === itemId);
    if (at < 0) return;
    const nextBatch = [...cur];
    if (repl) nextBatch[at] = repl; else nextBatch.splice(at, 1);
    setBatch(nextBatch);
    setAssign((m) => {
      const n = new Map(m);
      n.delete(itemId);
      if (repl) n.set(repl.item_id, startAnswer(repl.bucket, run.allowed, repl.existing));
      return n;
    });
    if (cursorRef.current === itemId) setCursor(repl ? repl.item_id : null);
  };

  const start = () => {
    if (cfg.tags.length === 0 || embedders.length === 0) return;
    const config = { ...cfg, embedder: embedderChoice };
    storage.set(TAGGRID_KEY, serializeTagGridConfig(config));
    history.clear();
    recent.current = [];
    sessionNeg.current = [];
    pool0.current = null;
    setPool(null);
    setFailed(null);
    setDecided(0);
    setBatch([]);
    setAssign(new Map());
    setCursor(null);
    setBatchNo(0);
    setSummaryOpen(false);
    const run = { config, embedders, allowed: allowedOf(config) };
    setRunning(run);
    void fetchBatch(run);
  };

  /** CONTINUE, from the Settings dialog: the session's history (its undo
   *  stack, its count, its shown-cards memory) stays, and the batch on
   *  screen — never written, never in `recent` — is simply replaced by
   *  one sorted under the new settings; its cards come round again. The
   *  pool is asked for again, since the tag or the sequence rule may have
   *  changed it. */
  const applyConfig = () => {
    if (cfg.tags.length === 0 || embedders.length === 0) return;
    const config = { ...cfg, embedder: embedderChoice };
    storage.set(TAGGRID_KEY, serializeTagGridConfig(config));
    const run = { config, embedders, allowed: allowedOf(config) };
    setRunning(run);
    setConfiguring(false);
    setSummaryOpen(false);
    pool0.current = null;
    void fetchBatch(run);
  };

  /** Give a card an answer — the capsule, ←/→ and the 1/2/3 keys. The
   *  card the pointer answered becomes the cursor, so the keys carry on
   *  from where the mouse left off. */
  const place = (id: number, a: Assignment) => {
    if (!(live.current.running?.allowed ?? []).includes(a)) return;
    setAssign((cur) => { const n = new Map(cur); n.set(id, a); return n; });
    setCursor(id);
  };

  /** Next batch: write the borders as they stand, then fetch a batch refit
   *  from what was just written. Fits and doesn't fit are ordinary tag
   *  assignments; undecided writes nothing and only leaves the session's
   *  pool through `recent`. */
  const next = async (more = true) => {
    const st = live.current;
    if (!st.running || st.busy || st.loading || st.batch.length === 0) return;
    setBusy(true);
    try {
      const answers = new Map(assignRef.current);
      const written: BatchRecord["written"] = [];
      for (const it of st.batch) {
        const a = answers.get(it.item_id) ?? "none";
        // A "doesn't fit" THE LIBRARY WILL NOT HEAR ABOUT is kept for the
        // fit instead: past one tag the answer writes nothing (a
        // conjunction's "no" names no tag to write it on), and without
        // this the session would ask the same question of the same
        // picture batch after batch and never get any better at it. What
        // the diff below still does on such a card is take BACK what it
        // came in with — a retraction, not a claim, and only reachable in
        // an `includeTagged` session, where a card can arrive carrying the
        // whole set.
        if (a === "negative"
            && writeIsEmpty(writeFor(st.running.config, "negative"))) {
          sessionNeg.current.push(it.item_id);
        }
        // WHAT CHANGES is written, and nothing else: a picture that came in
        // carrying a tag (`existing`, a session including the tagged) and
        // leaves on the same answer writes nothing, one moved to "undecided"
        // has its tags taken off, and every other move is the difference
        // between what it carried and what it says now. The event fans of
        // all of a card's writes ride one entry, so U takes them back
        // together.
        const cur: Assignment = it.existing ?? "none";
        if (a === cur) continue;
        const eventIds: number[] = [];
        const add = async (name: string, negative: boolean) => {
          const r = await api.assignItemTag(it.item_id, name, negative);
          eventIds.push(...(r.event_ids ?? []));
        };
        const drop = async (name: string) => {
          const r = await api.unassignItemTag(it.item_id, name);
          eventIds.push(...(r.event_ids ?? []));
        };
        // WHAT THE TWO ANSWERS WRITE, resolved and DIFFED. One tag with a
        // sign is the ordinary case and still what `writeFor` answers when
        // nothing else is configured; a set of tags (with their signs, and
        // groups to join) is the same question asked of more than one name
        // at once. Diffing is what keeps the rule the same either way: only
        // what CHANGED is written, so a card that came in carrying an
        // answer and leaves on it writes nothing.
        const was = writeFor(st.running.config, cur);
        const now = writeFor(st.running.config, a);
        const sign = (w: typeof was) => {
          const m = new Map<string, boolean>();
          for (const n of w.neg) m.set(n, true);
          for (const n of w.pos) m.set(n, false);   // positive wins a clash
          return m;
        };
        const before = sign(was);
        const after = sign(now);
        for (const [name, negative] of after) {
          if (before.get(name) !== negative) await add(name, negative);
        }
        for (const name of before.keys()) {
          if (!after.has(name)) await drop(name);
        }
        const gAdd = now.groups.filter((g) => !was.groups.includes(g));
        const gDrop = was.groups.filter((g) => !now.groups.includes(g));
        if (gAdd.length || gDrop.length) {
          const r = await api.bulkGroupMembership([it.item_id], gAdd, gDrop);
          eventIds.push(...(r.event_ids ?? []));
        }
        if (eventIds.length === 0) continue;
        written.push({ id: it.item_id, eventIds });
        void qc.invalidateQueries({ queryKey: ["item", it.item_id] });
      }
      recent.current.push(...st.batch.map((it) => it.item_id));
      syncPool();
      history.push({ items: st.batch, assign: answers, written });
      syncDecided();
      if (!more) {
        // END: the grid is written and the session is over — the summary,
        // as if the pool had run out, with nothing fetched behind it.
        spare.current = [];
        setBatch([]);
        setAssign(new Map());
        setCursor(null);
        if (useUI.getState().quickLook) useUI.getState().setQuickLook(false);
        setSummaryOpen(true);
        return;
      }
      const queue = await fetchBatch(st.running);
      // A batch finished while the preview is up: it moves on to the new
      // batch's first card, or it would go on showing a picture that has
      // just been written and left the grid. A backstop — Enter under the
      // preview closes it and every button that writes a batch is behind
      // it — kept so nothing that reaches `next()` can strand the preview.
      if (useUI.getState().quickLook && queue?.[0]) {
        setCursor(queue[0].item_id);
        useUI.getState().openQuickLook([queue[0].item_id]);
      }
    } finally {
      setBusy(false);
    }
  };

  /** U — the previous batch back on screen, its every write reverted. The
   *  batch on screen (unwritten) is simply dropped: its cards were never in
   *  `recent`, so they come round again. */
  const undo = async () => {
    const st = live.current;
    if (!st.running || st.busy || st.loading) return;
    const rec = history.peek();
    if (!rec) return;
    setBusy(true);
    try {
      history.pop();
      await history.revert(rec.written.flatMap((w) => w.eventIds),
                           rec.written.map((w) => w.id));
      const gone = new Set(rec.items.map((it) => it.item_id));
      recent.current = recent.current.filter((i) => !gone.has(i));
      sessionNeg.current = sessionNeg.current.filter((i) => !gone.has(i));
      syncPool();
      syncDecided();
      setBatch(rec.items);
      setAssign(new Map(rec.assign));
      setCursor(null);
      setBatchNo((n) => Math.max(1, n - 1));
      setSummaryOpen(false);
    } finally {
      setBusy(false);
    }
  };

  /** A summary thumbnail is a way BACK: un-write that one card and put it in
   *  the first cell of the batch on screen, undecided. */
  const reopen = async (itemId: number) => {
    const st = live.current;
    if (!st.running || st.busy || st.loading) return;
    const rec = history.steps.find(
      (r) => r.items.some((it) => it.item_id === itemId));
    if (!rec) return;
    setBusy(true);
    try {
      const w = rec.written.find((x) => x.id === itemId);
      await history.revert(w?.eventIds ?? [], [itemId]);
      const item = rec.items.find((it) => it.item_id === itemId)!;
      rec.items = rec.items.filter((it) => it.item_id !== itemId);
      rec.assign.delete(itemId);
      rec.written = rec.written.filter((x) => x.id !== itemId);
      if (rec.items.length === 0) history.drop((r) => r === rec);
      const r = recent.current.lastIndexOf(itemId);
      if (r >= 0) recent.current.splice(r, 1);
      sessionNeg.current = sessionNeg.current.filter((i) => i !== itemId);
      syncPool();
      syncDecided();
      setBatch((cur) => [item, ...cur.filter((it) => it.item_id !== itemId)]);
      setAssign((cur) => { const n = new Map(cur); n.set(itemId, "none");
                           return n; });
      setCursor(null);
      setSummaryOpen(false);
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    // Through the live ref, never the closure: the key handler is
    // registered once and captured the first render's `running` (null), so
    // an Esc-close read "no session" and skipped the note the ✕ showed.
    const run = live.current.running;
    const s = summarizeBatches(history.steps);
    const n = s.positive + s.negative + s.both;
    setOpen(false);
    setRunning(null);
    setSummaryOpen(false);
    setConfirmEnd(false);
    setConfiguring(false);
    setBatch([]);
    if (useUI.getState().quickLook) useUI.getState().setQuickLook(false);
    if (run && n > 0) {
      bumpLibrary();
      qc.invalidateQueries({ queryKey: ["tags"] });
      setNote(tn(
        { one: "{n} decided on {tag} — {yes} fit · {no} don't",
          other: "{n} decided on {tag} — {yes} fit · {no} don't" },
        // A "both" picture is a yes AND a no.
        n, { tag: tagNames(run.config).join(" · "),
             yes: String(s.positive + s.both),
             no: String(s.negative + s.both) }));
    }
  };

  /** EVERY WAY OUT GOES THROUGH ONE GUARD — Escape, the header's ✕ — the
   *  rate session's rule. A session that has DECIDED nothing skips the
   *  question: there is nothing to confirm. */
  const askClose = () => {
    const s = summarizeBatches(history.steps);
    if (s.positive + s.negative + s.both === 0) { close(); return; }
    setConfirmEnd(true);
  };

  // ---- keyboard ------------------------------------------------------------
  // The sessions' one spine (`useSessionKeys`): the gates, Escape through
  // the stack, Tab, undo and Space are its; the grid's walk and its answers
  // are this session's own.
  //
  // WHILE THE PREVIEW IS UP, THE SESSION STANDS DOWN — except for the keys
  // that are about the card on screen (`underPreview`): the arrows walk the
  // preview and turn that card's answer (the capsule under the picture),
  // Space closes it (the key that opened it), T opens the quick tag field
  // over it (the preview's own T is refused while the session is up, so
  // the session opens it, on the cursor's card), and Enter closes it, since
  // a batch is not a thing to write from behind a picture. Escape and Tab
  // are the preview's there.
  const plain = (e: KeyboardEvent) => !e.metaKey && !e.ctrlKey && !e.altKey;
  useSessionKeys({
    isOpen: () => useUI.getState().tagGridOpen && live.current.running != null,
    escape: open && running != null && !configuring,
    // While the T field floats over the session, every key is the field's
    // — and while the chooser is over it, the chooser's.
    standDown: () => quickTagIsOpen() || live.current.configuring
      || live.current.confirmEnd,
    onEscape: askClose,
    onTab: () => setSummaryOpen((v) => !v),
    summaryOpen: () => live.current.summaryOpen,
    undo: { match: (e) => ((e.key === "u" || e.key === "U") && plain(e))
              || ((e.key === "z" || e.key === "Z") && (e.metaKey || e.ctrlKey)
                  && !e.shiftKey),
            run: () => void undo() },
    // SPACE: the cursor's card, large — or, with nothing selected, the
    // FIRST card: Space is "show me", and a key that did nothing until an
    // arrow had been pressed was a key that looked broken. Up, it closes.
    preview: () => {
      const st = useUI.getState();
      if (st.quickLook) { st.setQuickLook(false); return; }
      const id = cursorRef.current ?? live.current.batch[0]?.item_id ?? null;
      if (id != null) {
        setCursor(id);
        st.openQuickLook([id]);
      }
    },
    keys: [
      // ⇧⌥ + ← / → turn EVERY card's answer at once. `cycleAll` is the
      // rule: a batch that agrees steps together, one that differs is
      // first ALIGNED onto the first card's answer. The cursor stays where
      // it is — this key is about the batch.
      { match: (e) => e.shiftKey && e.altKey && !e.metaKey && !e.ctrlKey
          && (e.key === "ArrowRight" || e.key === "ArrowLeft"),
        underPreview: true,
        run: (e) => {
          const st = live.current;
          const ids = st.batch.map((it) => it.item_id);
          const a = cycleAll(ids.map((id) => assignRef.current.get(id) ?? "none"),
                             e.key === "ArrowLeft", st.running!.allowed);
          if (ids.length && st.running!.allowed.includes(a)) {
            setAssign(new Map(ids.map((id) => [id, a])));
          }
        } },
      { match: (e) => (e.key === "t" || e.key === "T") && plain(e)
          && cursorRef.current != null,
        underPreview: true,
        run: () => useUI.getState().requestQuickTag([cursorRef.current as number]) },
      // ENTER IS NEXT BATCH, from anywhere on the grid: the answers are on
      // the borders already, so the one key that finishes a batch does
      // not need to be aimed. UNDER THE PREVIEW, ENTER CLOSES IT — the
      // batch is not what the key is about there (owner decision, 2026-09:
      // it was Next batch here too, the preview then moving on to the new
      // batch's first card). Escape closes it as well; Enter is the key
      // the hand is already on.
      { match: (e) => e.key === "Enter" && plain(e), underPreview: true,
        run: () => {
          if (useUI.getState().quickLook) { useUI.getState().setQuickLook(false); return; }
          void next();
        } },
      // ⇧ + ← / → turn the cursor's answer, the capsule read as a ring.
      { match: (e) => e.shiftKey && plain(e)
          && (e.key === "ArrowRight" || e.key === "ArrowLeft"),
        underPreview: true,
        run: (e) => {
          const cur = cursorRef.current;
          if (cur != null) {
            place(cur, cycleAssignment(assignRef.current.get(cur) ?? "none",
                                       e.key === "ArrowLeft",
                                       live.current.running!.allowed));
          }
        } },
      // The bare arrows are the GRID's — → / ← the next and previous card
      // in reading order (off a row's end, the next row's first), ↓ / ↑
      // the card below and above. UNDER THE PREVIEW the walk is
      // ONE-dimensional — a picture at a time, ↓/→ the next and ↑/← the
      // previous — since the grid's rows are not on screen to walk by, and
      // the preview FOLLOWS the cursor.
      { match: (e) => e.key.startsWith("Arrow") && plain(e) && !e.shiftKey,
        underPreview: true,
        run: (e) => {
          const st = live.current;
          const preview = useUI.getState().quickLook;
          const fwd = e.key === "ArrowRight" || e.key === "ArrowDown";
          const dir = preview ? (fwd ? "right" : "left")
            : e.key === "ArrowRight" ? "right" : e.key === "ArrowLeft"
            ? "left" : e.key === "ArrowDown" ? "down" : "up";
          const nx = stepCursor(st.batch.map((it) => it.item_id), cursorRef.current,
                                dir, st.running!.config.cols);
          if (nx != null) {
            setCursor(nx);
            if (preview) useUI.getState().openQuickLook([nx]);
          }
        } },
    ],
  });

  useEffect(() => {
    if (open && running != null && !configuring) frameRef.current?.focus();
  }, [open, running, configuring]);

  // THE CAPSULE UNDER THE PREVIEW: while the session's preview is up over
  // the cursor's card, the preview draws that card's answer under the
  // picture, and ←/→ or a click there turn it exactly as on the cell.
  const previewOpen = useUI((s) => s.quickLook);
  useEffect(() => {
    const st = useUI.getState();
    if (!open || running == null || !previewOpen || cursor == null) {
      if (st.previewFooter) st.setPreviewFooter(null);
      return;
    }
    st.setPreviewFooter(
      <AnswerCapsule assignment={assign.get(cursor) ?? "none"}
        offered={running.allowed} onPlace={(a) => place(cursor, a)} t={t} />);
    return () => useUI.getState().setPreviewFooter(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, running, previewOpen, cursor, assign]);

  if (!open && !note) return null;

  // What the body shows with no batch on screen is `sessionBody`'s rule —
  // a fetch in flight is LOADING and a failed one is an ERROR, and only
  // what is left is an exhausted pool.
  const body = running == null ? null
    : sessionBody({ loading, failed: failed != null, queued: batch.length });
  const exhausted = body === "exhausted";
  const showSummary = running != null && (summaryOpen || exhausted);
  const scopeEmpty = probe.data != null && probe.data.total === 0;
  const canStart = cfg.tags.length > 0 && !scopeEmpty
    && embedders.length > 0;

  const chooser = open && (running == null || configuring) && (
    <Overlay icon={configuring ? "tune" : "grid_view"}
      title={configuring ? t("Session settings") : t("Tag items in a grid")}
      subtitle={configuring
        ? t("Changes take over from the next batch.")
        : t("Sort a grid of pictures into fits / doesn't fit")}
      width={560}
      onClose={() => { if (configuring) setConfiguring(false); else close(); }}
      footer={<>
        {scopeEmpty && (
          <span style={{ fontSize: "var(--fs-2)", minWidth: 0, marginRight: "auto",
                         color: "var(--muted-2)" }}>
            {t("Nothing left to decide in this scope.")}
          </span>
        )}
        {/* NOT EVERY PICTURE IS INDEXED, said where Start is: the coverage
            line up in the options says the numbers, this says what they
            mean for the session about to begin. Amber, the app's colour for
            "a machine has not looked at this yet". */}
        {(() => {
          const p = probe.data;
          if (scopeEmpty || !embedReady || p == null || p.total <= 0) return null;
          const missing = Math.max(0, ...embedders.map(
            (id) => p.total - (p.coverage?.[id] ?? 0)));
          if (missing <= 0) return null;
          return (
            <span style={{ display: "flex", alignItems: "center", gap: 5,
                           fontSize: "var(--fs-2)", minWidth: 0, marginRight: "auto",
                           color: "var(--yellow-text)" }}>
              <Icon name="warning" size={14} />
              {tn({ one: "1 of {total} pictures is not indexed yet — it will come last, unordered.",
                    other: "{n} of {total} pictures are not indexed yet — they will come last, unordered." },
                  missing, { total: String(p.total) })}
            </span>
          );
        })()}
        <Button variant="primary" size="md"
     onClick={canStart ? (configuring ? applyConfig : start) : undefined}>
          <Icon name={configuring ? "check" : "play_arrow"} size={16} />
          {" "}{configuring ? t("Continue") : t("Start")}
        </Button>
      </>}>
      <Chooser cfg={cfg} setCfg={setCfg}
        probe={probe.data ?? null} embedReady={embedReady}
        pickerModels={pickerModels} embedderChoice={embedderChoice}
        embedders={embedders}
        embedNames={new Map(embedModels.map((m) => [m.id, m.name]))}
        embedJob={embedJob} scopeBody={() => scopeBody(cfg)}
        onOpenModels={() => {
          const st = useUI.getState();
          const missing = embedders
            .map((id) => embedModels.find((m) => m.id === id))
            .find((m) => m && !m.ready);
          if (missing?.key) {
            st.setSettingsFocusModel(missing.key);
            st.setSettingsFocusWarning(false);
          }
          st.setSettingsPage("actions");
          st.setOverlay("settings");
          close();
        }}
        t={t} tn={tn} />
    </Overlay>
  );

  return (
    <>
      {chooser}
      {open && running != null && !configuring && (
      <div data-dismiss-anywhere style={{ position: "fixed", inset: 0, zIndex: LAYER.session,
                    background: "var(--scrim-4)", display: "flex",
                    flexDirection: "column", padding: "20px 28px", gap: 12,
                    color: "var(--on-scrim)" }}>
        <div ref={frameRef} tabIndex={-1}
          style={{ outline: "none", display: "flex", flexDirection: "column",
                   flex: 1, minHeight: 0, gap: 12 }}>
          {/* ---- header ---- */}
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ fontSize: "var(--fs-5)", fontWeight: 600 }}>
              {tagNames(running.config).join(" · ")}
            </div>
            <div style={{ fontSize: "var(--fs-3)", color: "var(--on-scrim-2)" }}>
              {tn({ one: "1 decided this session",
                    other: "{n} decided this session" }, decided)}
              {pool != null && (<>
                {" · "}
                {tn({ one: "1 left to decide",
                      other: "{n} left to decide" }, pool)}
              </>)}
              {batchNo > 0 && <span> · {t("batch {n}", { n: String(batchNo) })}</span>}
              {!ordered && batch.length > 0 && (
                <span> · {t("unsorted")}</span>
              )}
            </div>
            <span style={{ flex: 1 }} />
            {!showSummary && <Legend t={t} offered={running.allowed} />}
            {!showSummary && (
              // EVERY setting, mid-session: the chooser again, over the run,
              // and Continue takes over from the next batch. The sheet
              // steps aside while it is up — the dialog layer sits under
              // the session's, so it cannot be shown over it.
              <HeadBtn icon="tune" label={t("Settings")}
                title={t("Change this session's settings")}
                onClick={() => {
                  setCfg(running.config);
                  setConfiguring(true);
                }} />
            )}
            <HeadBtn icon="undo" label={t("Undo batch")}
              title={t("Take the previous batch back (U)")}
              disabled={history.size === 0 || busy}
              onClick={() => void undo()} />
            {/* A TOGGLE, lit while the summary is up — the way back is the
                button that opened it, and Tab. Exhausted, the summary is
                all there is and the toggle stays lit. */}
            <HeadBtn icon="format_list_numbered" label={t("Summary")}
              title={t("Show or hide the session summary (Tab)")}
              on={showSummary}
              onClick={() => { if (!exhausted) setSummaryOpen((v) => !v); }} />
            <span className="hoverable" onClick={() => askClose()}
              title={t("End the session (Esc)")}
              style={{ display: "flex", padding: 6, borderRadius: "var(--r-3)",
                       cursor: "pointer" }}>
              <Icon name="close" size={20} />
            </span>
          </div>

          {/* ---- body ---- */}
          {showSummary ? (
            <Summary history={history.steps}
              tag={tagNames(running.config).join(" · ")}
              onKeepGoing={!exhausted
                ? () => setSummaryOpen(false) : undefined}
              onReopen={(id) => void reopen(id)} t={t} tn={tn} />
          ) : body === "error" ? (
            <SessionTrouble
              message={t("The next batch could not be loaded.")}
              detail={failed} onRetry={() => void fetchBatch(running)} t={t} />
          ) : body === "loading" ? (
            <SessionWait label={t("Sorting the next batch…")} />
          ) : (
            // THE GRID IS FIXED: columns × rows from the chooser, each cell
            // holding the card the batch's score order put there, whatever
            // answer it carries now.
            <div style={{ flex: 1, minHeight: 0, display: "grid",
                          gridTemplateColumns:
                            `repeat(${running.config.cols}, minmax(0, 1fr))`,
                          gridTemplateRows:
                            `repeat(${running.config.rows}, minmax(0, 1fr))`,
                          gap: 16,
                          opacity: busy || loading ? 0.6 : 1,
                          transition: "opacity 0.15s" }}>
              {batch.map((it) => (
                <GridCell key={it.item_id} item={it}
                  assignment={assign.get(it.item_id) ?? "none"}
                  selected={cursor === it.item_id}
                  onSelect={() => setCursor(it.item_id)}
                  onPlace={(a) => place(it.item_id, a)}
                  offered={running.allowed}
                  onCycle={() => place(it.item_id, cycleAssignment(
                    assignRef.current.get(it.item_id) ?? "none", false,
                    running.allowed))}
                  onPreview={() => {
                    setCursor(it.item_id);
                    useUI.getState().openQuickLook([it.item_id]);
                  }}
                  onSkip={() => void skip(it.item_id)}
                  t={t} />
              ))}
            </div>
          )}

          {/* ---- footer ---- */}
          <div style={{ display: "flex", alignItems: "center", gap: 18,
                        fontSize: "var(--fs-3)", color: "var(--on-scrim-2)" }}>
            {showSummary ? (
              <>
                {history.size > 0 && (
                  <span><Cap>U</Cap> {t("undo batch")}</span>
                )}
                {!exhausted && <span><Cap>Tab</Cap> {t("back to the grid")}</span>}
                <span><Cap>Esc</Cap> {t("end")}</span>
              </>
            ) : (
              <>
                <span><Cap>←</Cap><Cap>↑</Cap><Cap>↓</Cap><Cap>→</Cap>{" "}
                  {t("move")}</span>
                <span><Cap>⇧ ←</Cap><Cap>⇧ →</Cap> {t("cycle")}</span>
                <span><Cap>⇧⌥ ←</Cap><Cap>⇧⌥ →</Cap> {t("cycle all")}</span>
                <span><Cap>Space</Cap> {t("preview")}</span>
                <span><Cap>T</Cap> {t("more tags")}</span>
                <span><Cap>U</Cap> {t("undo batch")}</span>
                <span><Cap>Tab</Cap> {t("summary")}</span>
                <span><Cap>Esc</Cap> {t("end")}</span>
                <span style={{ flex: 1 }} />
                <Button variant="scrim" size="md" onClick={() => void next(false)}
         disabled={busy || loading || batch.length === 0}
         title={t("Write the answers as they stand and end with the summary")}>
                  {t("End")}
                </Button>
                <Button variant="primary" size="md" onClick={() => void next()}
         disabled={busy || loading || batch.length === 0}
         title={t("Write the answers as they stand and sort the next batch (Enter)")}>
                  {t("Next batch")}
                  <span style={{ display: "flex", gap: 3, opacity: 0.85 }}>
                    <Cap>Enter</Cap>
                  </span>
                </Button>
              </>
            )}
          </div>
          {/* THE ONE QUESTION IN FRONT OF THE WAY OUT — the shared sheet. Nothing
              is lost by ending (every answer was written as it was given), so
              the sentence says what ending does rather than warning. */}
          {confirmEnd && (
            <ConfirmModal t={t}
              title={t("End this session?")}
              body={tn({ one: "1 picture is decided — every answer is already written.",
                        other: "{n} pictures are decided — every answer is already written." },
                      decided)}
              cancel={t("Keep sorting")}
              answer={{ label: t("End session") }}
              onResult={(r) => { setConfirmEnd(false); if (r === "answer") close(); }} />
          )}
        </div>
      </div>
      )}
      {note && (
        <ActionToast text={note} autoDismissMs={4000} onDismiss={() => setNote(null)} />
      )}
    </>
  );
}

// ---- the cells -----------------------------------------------------------------

/** What the three border colours mean, in the header — the one place the
 *  session says it in words. */
function Legend({ t, offered }: { t: (s: string) => string;
                                  offered: Assignment[] }) {
  const dot = (a: Assignment, label: string) => (
    <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <span style={{ width: 10, height: 10, borderRadius: 3,
                     border: `2px solid ${COLOR[a]}` }} />
      {label}
    </span>
  );
  return (
    <div style={{ display: "flex", gap: 14, fontSize: "var(--fs-2)",
                  color: "var(--on-scrim-2)", marginRight: 6 }}>
      {dot("positive", t("Fits"))}
      {offered.includes("negative") && dot("negative", t("Doesn't fit"))}
      {offered.includes("both") && dot("both", t("Both"))}
      {offered.includes("none") && dot("none", t("Undecided"))}
    </div>
  );
}

/** One cell: the library card's thumbnail box — a flat opaque backdrop
 *  with the transparency checkerboard drawn only behind the picture's own
 *  fit box — and the ANSWER as a ring drawn a few pixels outside it, the
 *  library selection ring's shape. Two things appear on hover (and while
 *  the cell is the cursor): an EYE in the top-left corner — the sidebar
 *  thumbnail's own preview button — and a CAPSULE inset at the bottom
 *  centre with the three answers, + / − / no tag, in the app's own
 *  iconography. Both are always laid out and flip `visibility`, so the
 *  same button is in the same place on every cell. THE CURSOR IS NOT A
 *  RING: a second ring beside the answer's would be two claims in one
 *  tag set, so the cursor shows as the controls, tinted. */
function GridCell({ item, assignment, selected, offered, onSelect, onPlace,
                    onCycle, onPreview, onSkip, t }: {
  item: TagGridItem;
  /** The session's answers on offer — the capsule draws only those. */
  offered: Assignment[];
  assignment: Assignment;
  selected: boolean;
  onSelect: () => void;
  onPlace: (a: Assignment) => void;
  onCycle: () => void;
  onPreview: () => void;
  /** The ✕ top-right: skip this picture, another takes its place. */
  onSkip: () => void;
  t: (s: string, vars?: Record<string, string>) => string;
}) {
  const [hover, setHover] = useState(false);
  const src = item.file_id != null
    ? api.thumbUrl(item.file_id, item.rotation, item.thumb_token) : undefined;
  const shown = hover || selected;
  const ratio = item.width > 0 && item.height > 0
    ? item.width / item.height : 1;
  // The cursor's tint: a darker, nearly opaque accent, so the tinted
  // controls read as a state rather than a sheen over the picture.
  const chrome = selected ? "var(--overlay-chrome-accent)" : "var(--scrim-3)";
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onMouseDown={(e) => { e.stopPropagation(); onSelect(); }}
      // A CLICK ON THE PICTURE CYCLES ITS ANSWER — the capsule spelled out
      // as the whole cell, for the hand that does not want to aim. The eye
      // is the only way to the preview: a double-click that opened it was a
      // preview one click past an answer nobody meant to give.
      onClick={(e) => { e.stopPropagation(); onCycle(); }}
      title={item.name || item.uid}
      style={{ position: "relative", minWidth: 0, minHeight: 0,
               borderRadius: "var(--r-4)", overflow: "hidden",
               background: "var(--panel-3)",
               border: "1px solid var(--border)",
               // The library selection ring's shape: 2px, 3px clear of the
               // box, so the answer reads even on a picture of its colour.
               outline: `2px solid ${COLOR[assignment]}`,
               outlineOffset: 3,
               // Container-query units size the checkerboard to the
               // picture's fit box below, whatever shape the cell is.
               containerType: "size",
               cursor: "default", userSelect: "none" }}>
      {/* The checkerboard behind the PICTURE's box only — the letterbox
          stays flat, and a transparent picture still shows it. */}
      <div className="mc-checker"
        style={{ position: "absolute", inset: 0, margin: "auto",
                 width: `min(100%, calc(100cqh * ${ratio}))`,
                 aspectRatio: String(ratio) }} />
      {src && (
        <img src={src} draggable={false}
          style={{ position: "absolute", inset: 0, width: "100%",
                   height: "100%", objectFit: "contain", display: "block" }} />
      )}
      <span title={t("Preview (Space)")}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => { e.stopPropagation(); onPreview(); }}
        style={{ position: "absolute", top: 8, left: 8, width: 30, height: 30,
                 display: "flex", alignItems: "center",
                 justifyContent: "center", borderRadius: 15,
                 background: "var(--scrim-3)", color: "var(--on-scrim)",
                 border: "1px solid var(--on-scrim-4)",
                 cursor: "pointer",
                 visibility: hover ? "visible" : "hidden" }}>
        <Icon name="visibility" size={16} />
      </span>
      <span title={t("Skip this picture — another takes its place")}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => { e.stopPropagation(); onSkip(); }}
        style={{ position: "absolute", top: 8, right: 8, width: 30, height: 30,
                 display: "flex", alignItems: "center",
                 justifyContent: "center", borderRadius: 15,
                 background: "var(--scrim-3)", color: "var(--on-scrim)",
                 border: "1px solid var(--on-scrim-4)",
                 cursor: "pointer",
                 visibility: hover ? "visible" : "hidden" }}>
        <Icon name="close" size={16} />
      </span>
      <div style={{ position: "absolute", bottom: 8, left: "50%",
                    transform: "translateX(-50%)",
                    visibility: shown ? "visible" : "hidden" }}>
        <AnswerCapsule assignment={assignment} onPlace={onPlace}
          offered={offered} chrome={chrome} t={t} />
      </div>
    </div>
  );
}

/** THE CAPSULE — the three answers, the chosen one FILLED with its ring's
 *  colour (the same colour saying the same thing twice, on the cell and
 *  here, where a translucent highlight was easy to miss) with a dark glyph
 *  on it, white on green or red being the lower-contrast pair. One
 *  component, because it is drawn twice: on a cell, and under the preview
 *  for the card being looked at. */
function AnswerCapsule({ assignment, onPlace, offered, chrome, t }: {
  assignment: Assignment;
  onPlace: (a: Assignment) => void;
  /** The session's answers on offer — a dropped one has no button. */
  offered: Assignment[];
  /** The capsule's own backing — the cursor's tint on a cell. */
  chrome?: string;
  t: (s: string) => string;
}) {
  const btn = (a: Assignment, glyph: React.ReactNode, title: string) => {
    const on = assignment === a;
    return (
      <span title={title}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => { e.stopPropagation(); onPlace(a); }}
        style={{ width: 34, height: 28, display: "flex",
                 alignItems: "center", justifyContent: "center",
                 cursor: "pointer", borderRadius: 14,
                 background: on ? COLOR[a] : "transparent",
                 color: on ? "var(--scrim-4)" : "var(--on-scrim)" }}>
        {glyph}
      </span>
    );
  };
  return (
    <div onMouseDown={(e) => e.stopPropagation()}
      style={{ display: "flex", gap: 2, padding: 2, borderRadius: 18,
               background: chrome ?? "var(--scrim-3)",
               border: "1px solid var(--on-scrim-4)" }}>
      {btn("positive", <PlusMinus kind="plus" />, t("Fits"))}
      {offered.includes("negative") && btn("negative", <PlusMinus kind="minus" />, t("Doesn't fit"))}
      {offered.includes("both") && btn("both", <PlusMinus kind="both" />, t("Both"))}
      {offered.includes("none")
        && btn("none", <Icon name="label_off" size={18} />, t("Undecided"))}
    </div>
  );
}


function HeadBtn({ icon, label, title, disabled, on, onClick }: {
  icon: string; label: string; title: string; disabled?: boolean;
  /** Lit — a toggle that is currently on. */
  on?: boolean;
  onClick: () => void;
}) {
  return (
    <span className={disabled ? undefined : "hoverable"}
      onClick={disabled ? undefined : onClick} title={title}
      style={{ display: "flex", alignItems: "center", gap: 5,
               padding: "4px 10px", borderRadius: "var(--r-3)",
               cursor: disabled ? "default" : "pointer",
               color: "var(--on-scrim)", fontSize: "var(--fs-3)", opacity: disabled ? 0.4 : 1,
               background: on ? "var(--overlay-wash)" : "transparent",
               border: "1px solid var(--on-scrim-4)" }}>
      <Icon name={icon} size={14} />{label}
    </span>
  );
}

// ---- the chooser -------------------------------------------------------------

const selectStyle: React.CSSProperties = {
  height: 28, padding: "0 8px", borderRadius: "var(--r-4)",
  border: "1px solid var(--border-strong)",
  background: "var(--panel-2)", color: "var(--text)",
  fontSize: "var(--fs-3)", fontFamily: "inherit",
};

/** WHAT ONE ANSWER WRITES, past its single tag: tags with their signs and
 *  groups to join, folded away until somebody wants them.
 *
 *  The question stays a single tag — that is what the classifier learns and
 *  orders by — so this is deliberately not a second way to ask the
 *  question, only a fuller answer. Empty is the plain behaviour, which is
 *  why it opens closed and says how many it holds when it is. */
/** ONE TAG OF THE SET: its name, and — while "doesn't fit" is offered —
 *  what that answer writes for it. The tag batch's row exactly, minus the
 *  digit and the question card: both names are edited IN PLACE (the
 *  sidebar's own signed-name pair), so correcting one is editing rather
 *  than removing and retyping. */
function GridTagRow({ cfg, row, setCfg, t }: {
  cfg: TagGridConfig;
  row: GridTag;
  setCfg: React.Dispatch<React.SetStateAction<TagGridConfig>>;
  t: (s: string, vars?: Record<string, string>) => string;
}) {
  const counter = row.negative.trim();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8,
                  padding: "5px 8px", borderRadius: "var(--r-4)",
                  background: "var(--panel-3)",
                  border: "1px solid var(--border)" }}>
      <span style={{ flex: 1, minWidth: 0, display: "flex",
                     alignItems: "center", gap: 8 }}>
        <SignName name={row.name} negative={false}
          title={t("Rename the tag")}
          onCommit={(v) => {
            const clean = v.trim(); // the field committed its own form
            if (clean) setCfg((c) => renameTag(c, row.name, clean));
          }} t={t} />
        {cfg.answers !== "no_negative" && (<>
          <span style={{ color: "var(--muted-2)", fontSize: "var(--fs-3)" }}>/</span>
          <SignName name={counter || row.name} negative={!counter}
            // PAST ONE TAG IT DESCRIBES NO WRITE: a conjunction's "doesn't
            // fit" writes nothing (`writeFor`), and the name here is only
            // what the feed READS as evidence against this tag.
            title={cfg.tags.length > 1
              ? t("The tag that means the opposite — its pictures count as evidence against this one. With several tags, “doesn't fit” writes nothing itself.")
              : t("What “doesn't fit” writes — a tag typed here is assigned positively in place of the negative; empty it for the negative again")}
            onCommit={(v) => {
              const clean = v.trim(); // the field committed its own form
              setCfg((c) => withCounter(c, row.name, clean));
            }} t={t} />
        </>)}
      </span>
      <IconButton icon="close" size={20} glyph={14} reveal="hover" tone="danger"
        onClick={() => setCfg((c) => withoutTag(c, row.name))}
        title={t("Remove")} />
    </div>
  );
}


function Chooser({ cfg, setCfg, probe,
                   embedReady, pickerModels, embedderChoice, embedders,
                   embedNames, embedJob, scopeBody, onOpenModels, t, tn }: {
  cfg: TagGridConfig;
  setCfg: React.Dispatch<React.SetStateAction<TagGridConfig>>;


  probe: (TagGridNextOut & { total: number }) | null;
  embedReady: boolean;
  pickerModels: { id: string; name: string; family?: string }[];
  embedderChoice: string;
  /** The resolved embed model ids the session will read. */
  embedders: string[];
  embedNames: Map<string, string>;
  embedJob: { progress: number; status: string; model: string } | null;
  scopeBody: () => Record<string, unknown>;
  onOpenModels: () => void;
  t: (s: string, vars?: Record<string, string>) => string;
  tn: (forms: { one: string; other: string }, n: number,
       vars?: Record<string, string>) => string;
}) {
  // THE GROUPS A "FITS" CAN JOIN. The sidebar's own tree, fetched here
  // because this is the only place in the session that offers one; smart
  // groups are left out by `flattenGroupTree` (their membership is a rule,
  // not an answer).
  const { data: tree } = useQuery({
    queryKey: ["groups"], queryFn: api.groups,
  });
  const groupOptions = useMemo(() => flattenGroupTree(tree ?? []), [tree]);
  // The adder's own text — a field that is not the question, just the way
  // into the list; the set is `cfg.tags`.
  const [adding, setAdding] = useState("");
  const qc = useQueryClient();
  // Bridges the click and the first job poll, so the button cannot be
  // pressed twice while the jobs have not shown up yet.
  const [starting, setStarting] = useState(false);
  useEffect(() => { if (embedJob != null) setStarting(false); }, [embedJob]);
  /** ONE button for every chosen space: a run per space that is short —
   *  the spaces are indexed independently and never mix, so this is
   *  several jobs, queued together — rather than a button per line, which
   *  under fusion was two buttons for one intent. */
  const runIndex = async (short: string[]) => {
    setStarting(true);
    let queued = 0;
    try {
      for (const embedder of short) {
        const got = await api.tagSortIndex({
        ...scopeBody(),
          embedder,
        } as Parameters<typeof api.tagSortIndex>[0]);
        queued += got.queued;
      }
    } catch {
      setStarting(false);
      return;
    }
    // Nothing indexABLE left (the remainder is videos): no job was made,
    // so no job poll will ever clear the spinner.
    if (!queued) { setStarting(false); return; }
    // The AiActionButtons rule: whoever enqueues invalidates ["ml-jobs"] —
    // JobList polls only while it can SEE something active, so without this
    // the run existed and nothing in the app ever learnt about it.
    void qc.invalidateQueries({ queryKey: ["ml-jobs"] });
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14,
                  padding: 18, color: "var(--text)" }}>
      <div>
        <div style={sectionLabel}>{t("Tag")}</div>
        <div style={card}>
          {/* WHICH ANSWERS the capsule offers. "Fits" is always one; the
              other two can each be dropped — a session that only ever adds
              the tag, or one where every card gets a decision (an
              undecided card then writes the negative). */}
          <div style={{ padding: "12px 14px", display: "flex",
                        alignItems: "center", gap: 14,
                        borderBottom: "1px solid var(--border-soft)" }}>
            <div style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-4)" }}>
              {t("Mode")}
            </div>
            <select value={cfg.answers} style={selectStyle}
              onChange={(e) => setCfg((c) => ({
                ...c, answers: e.target.value as Answers }))}>
              {ANSWERS.map((a) => (
                <option key={a} value={a}>
                  {a === "all" ? t("Fits, doesn't fit, undecided")
                    : a === "no_none" ? t("Fits, doesn't fit")
                    : t("Fits, undecided")}
                </option>
              ))}
            </select>
          </div>
          {/* THE QUESTION IS A LIST, and the same list is what an answer
              WRITES. It was a tag field with a folded "also write" section
              under it and a second pair for "doesn't fit" — four controls
              saying two things, and the split between "the tag" and "the
              other tags" was a distinction the session did not have. Every
              row is a tag with its own "doesn't fit" spelling, and a
              picture FITS when it carries all of them. */}
          <div style={{ padding: "12px 14px",
                        borderBottom: "1px solid var(--border-soft)" }}>
            <div style={{ fontSize: "var(--fs-4)" }}>{t("Tags")}</div>
            <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)",
                          marginTop: 3, marginBottom: 8, lineHeight: 1.45 }}>
              {cfg.tags.length > 1
                ? t("A picture fits when it carries all of these; anything said against one of them makes it a “doesn't fit”. With several tags that answer writes nothing — a picture that is not both may still be one of them — and only sorts the rest of the session.")
                : t("What the session asks about — and what a “fits” writes.")}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {cfg.tags.map((row) => (
                <GridTagRow key={row.name} cfg={cfg} row={row}
                  setCfg={setCfg} t={t} />
              ))}
              <TagAutocomplete
                value={adding} onChange={setAdding}
                onCommit={(name) => {
                  // Already the field's committed form — the field is the
                  // one place a name is normalised.
                  if (name) setCfg((c) => withTag(c, name));
                  setAdding("");
                }}
                // The library's GROUPS in the empty field's own section —
                // a "fits" puts the picture in them, and nothing ever
                // takes it out.
                groups={groupOptions.filter(
                  (g) => !cfg.groups.includes(g.id))}
                onPickGroup={(id) => {
                  setCfg((c) => ({ ...c,
                    groups: [...new Set([...c.groups, id])] }));
                  setAdding("");
                }}
                fetchSuggestions={fetchTagNameSuggestions}
                existing={cfg.tags.map((x) => x.name)}
                placeholder={cfg.tags.length === 0
                  ? t("Which tag do you want to sort by?")
                  : t("Add another tag or group…")}
                minWidth={220}
              />
              {cfg.groups.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {cfg.groups.map((gid) => {
                    const g = groupOptions.find((o) => o.id === gid);
                    return (
                      <span key={gid}
                        title={t("A picture that fits joins this group")}
                        style={{ display: "flex", alignItems: "center",
                                 gap: 4, padding: "4px 6px", borderRadius: "var(--r-3)",
                                 border: "1px solid var(--accent-soft)",
                                 background: "var(--accent-dim)",
                                 color: "var(--accent)", fontSize: "var(--fs-2)",
                                 fontFamily: "var(--mono)" }}>
                        <Icon name="folder" size={14} />
                        {g?.name ?? `#${gid}`}
                        {g && g.trail && g.trail.length > 0 && (
                          <span style={{ color: "var(--muted-2)",
                                         fontSize: "var(--fs-1)" }}>
                            {g.trail.join(" › ")}
                          </span>
                        )}
                        <span className="hoverable" title={t("Remove")}
                          onClick={() => setCfg((c) => ({ ...c,
                            groups: c.groups.filter((x) => x !== gid) }))}
                          style={{ display: "flex", cursor: "pointer" }}>
                          <Icon name="close" size={13} />
                        </span>
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
          {/* "BOTH" — the picture gets the tag AND the "doesn't fit" tag:
              a tag that holds for one subject in the picture and not
              another. Only where "doesn't fit" is a tag of its own (the
              tag's negative beside its positive is a contradiction) and
              only for a set of ONE: past that "doesn't fit" writes
              nothing, so "both" would be a fourth button spelling
              "fits". */}
          {cfg.answers !== "no_negative" && canSayBoth(cfg) && (
            <OptionRow
              title={t("Offer “both”")}
              desc={t("Assigns both tags to the picture.")}
              checked={cfg.bothAnswer}
              onToggle={() => setCfg((c) => ({ ...c, bothAnswer: !c.bothAnswer }))}
              last
            />
          )}
        </div>
      </div>

      <div>
        <div style={sectionLabel}>{t("Options")}</div>
        <div style={card}>
          {/* The grid's shape, as two numbers and a ×: what they are is
              what they look like on screen, and a sentence under them
              would only say "columns and rows". */}
          <div style={{ padding: "12px 14px", display: "flex",
                        alignItems: "center", gap: 14,
                        borderBottom: "1px solid var(--border-soft)" }}>
            <div style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-4)" }}>
              {t("Grid")}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <select value={cfg.cols} style={selectStyle}
                title={t("Columns")}
                onChange={(e) => setCfg((c) => ({
                  ...c, cols: Number(e.target.value) }))}>
                {GRID_COLS.map((n) => (
                  <option key={n} value={n}>{String(n)}</option>
                ))}
              </select>
              <span style={{ color: "var(--muted-2)" }}>×</span>
              <select value={cfg.rows} style={selectStyle}
                title={t("Rows")}
                onChange={(e) => setCfg((c) => ({
                  ...c, rows: Number(e.target.value) }))}>
                {GRID_ROWS.map((n) => (
                  <option key={n} value={n}>{String(n)}</option>
                ))}
              </select>
            </div>
          </div>
          <OptionRow
            title={t("Prioritize uncertain pictures")}
            desc={t("Half of each batch is what the model is least sure about.")}
            checked={cfg.boundary}
            onToggle={() => setCfg((c) => ({ ...c, boundary: !c.boundary }))}
          />
          <OptionRow
            title={t("Skip pictures in sequences")}
            desc={t("Pages of a book and frames of a GIF are left out.")}
            checked={cfg.skipSequenced}
            onToggle={() => setCfg((c) => ({
              ...c, skipSequenced: !c.skipSequenced }))}
          />
          {/* THE TAGGED STAY IN: a session over pictures the tag is already
              on, each starting on what it carries rather than on the
              classifier's guess — a way to check tags already given. Next
              batch then writes only what was changed. */}
          <OptionRow
            title={t("Include already tagged pictures")}
            desc={t("They start on their tags, not the classifier's guess — to check tags already given.")}
            checked={cfg.includeTagged}
            onToggle={() => setCfg((c) => ({
              ...c, includeTagged: !c.includeTagged }))}
            last
          />
        </div>
      </div>

      <div>
        <div style={sectionLabel}>{t("Sorting")}</div>
        <div style={card}>
          <div style={{ padding: "12px 14px" }}>
            {/* A TITLE over the picker, in the option rows' own type: the
                card is the one in this dialog with no switch and no row,
                and a bare dropdown at the top of it read as a control that
                had lost its label. */}
            <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)",
                          fontWeight: 500 }}>
              {t("Sort by likeness")}
            </div>
            <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 3,
                          marginBottom: 10, lineHeight: 1.45 }}>
              {t("Which kind of likeness orders every batch. Each space is indexed on its own.")}
            </div>
            {/* Every model, plus BOTH at once: each space fit on its own and
                the scores averaged, so a picture indexed in either space is
                scored, and the cuts calibrate on the fused scale. No switch
                to turn the sorting off — it is what the session is for. */}
            <EmbedModelPicker models={pickerModels} value={embedderChoice}
              onChange={(id) => setCfg((c) => ({ ...c, embedder: id }))}
              t={t} />
            {!embedReady ? (
              <button
                onClick={(e) => { e.stopPropagation(); onOpenModels(); }}
                style={{ display: "flex", alignItems: "center", gap: 5,
                         marginTop: 8, height: 26, padding: "0 10px",
                         borderRadius: "var(--r-3)",
                         border: "1px solid var(--border-strong)",
                         background: "var(--panel-2)", color: "var(--text-2)",
                         cursor: "pointer", fontFamily: "inherit",
                         fontSize: "var(--fs-2)" }}>
                <Icon name="download" size={14} />
                {t("Set up in Settings → Models")}
              </button>
            ) : probe != null ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 4,
                            marginTop: 8, fontSize: "var(--fs-2)",
                            color: "var(--muted-2)" }}>
                {(() => {
                  const short = embedders.filter(
                    (id) => (probe.coverage?.[id] ?? 0) < probe.total);
                  // ANY embed job over a chosen space, not only the one
                  // this dialog queued: a run started elsewhere is the
                  // same wait.
                  const indexing = starting
                    || (embedJob != null
                        && (embedJob.model == null
                            || embedders.includes(embedJob.model)));
                  // The coverage lines stacked on the left, the ONE action
                  // for all of them to their right.
                  return (
                    <div style={{ display: "flex", alignItems: "center",
                                  gap: 10 }}>
                      <div style={{ flex: 1, display: "flex",
                                    flexDirection: "column", gap: 4 }}>
                        {embedders.map((id) => (
                          <div key={id}>
                            {t("{a} of {b} in this scope are indexed for {model}",
                               { a: String(probe.coverage?.[id] ?? 0),
                                 b: String(probe.total),
                                 model: embedNames.get(id) ?? id })}
                          </div>
                        ))}
                      </div>
                      {indexing ? (
                        <span style={{ display: "flex", alignItems: "center",
                                       gap: 5 }}>
                          <Icon name="progress_activity" size={13}
                            spin />
                          {t("Indexing… {p}%",
                             { p: String(Math.max(0, embedJob?.progress ?? 0)) })}
                        </span>
                      ) : short.length > 0 ? (
                        <button
                          onClick={() => void runIndex(short)}
                          title={t("Index the unindexed items as a background task")}
                          style={{ height: 24, padding: "0 10px",
                                   borderRadius: "var(--r-3)",
                                   border: "1px solid var(--border-strong)",
                                   background: "var(--panel-2)",
                                   color: "var(--text-2)", cursor: "pointer",
                                   fontFamily: "inherit", fontSize: "var(--fs-2)" }}>
                          {t("Index remaining")}
                        </button>
                      ) : null}
                    </div>
                  );
                })()}
                {probe.labeled[0] + probe.labeled[1] > 0 && (
                  <div>
                    {tn({ one: "{tag} has 1 assignment to learn from",
                          other: "{tag} has {n} assignments to learn from" },
                        probe.labeled[0] + probe.labeled[1],
                        { tag: tagNames(cfg).join(" · ") })}
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- the summary -------------------------------------------------------------

function Summary({ history, tag, onKeepGoing, onReopen, t, tn }: {
  history: readonly BatchRecord[];
  tag: string;
  onKeepGoing?: () => void;
  onReopen: (itemId: number) => void;
  t: (str: string, vars?: Record<string, string>) => string;
  tn: (forms: { one: string; other: string }, n: number,
       vars?: Record<string, string>) => string;
}) {
  const groups: { key: Assignment; label: string; refs: TagGridItem[] }[] =
    [];
  for (const k of ["positive", "negative", "both", "none"] as const) {
    const refs: TagGridItem[] = [];
    for (const rec of history) {
      for (const it of rec.items) {
        if ((rec.assign.get(it.item_id) ?? "none") === k) refs.push(it);
      }
    }
    if (refs.length) {
      groups.push({ key: k, refs,
                    label: k === "positive" ? t("Fits")
                      : k === "negative" ? t("Doesn't fit")
                      : k === "both" ? t("Both")
                      : t("Undecided") });
    }
  }
  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: "auto",
                  margin: "0 auto", width: "min(820px, 100%)",
                  display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ textAlign: "center", fontSize: "var(--fs-3)",
                    color: "var(--on-scrim-3)" }}>
        {tag}
      </div>
      {groups.length === 0 && (
        <div style={{ textAlign: "center", fontSize: "var(--fs-4)",
                      color: "var(--on-scrim-2)" }}>
          {t("Nothing decided yet.")}
        </div>
      )}
      {groups.map((g) => (
        <div key={g.key} style={{ display: "flex", gap: 12 }}>
          <div style={{ flex: "0 0 140px", fontSize: "var(--fs-3)", textAlign: "right",
                        color: COLOR[g.key] }}>
            {g.label}
            <div style={{ fontSize: "var(--fs-2)", color: "var(--on-scrim-3)" }}>
              {tn({ one: "1 picture", other: "{n} pictures" }, g.refs.length)}
            </div>
          </div>
          <div style={{ flex: 1, display: "flex", flexWrap: "wrap", gap: 6 }}>
            {g.refs.map((r) => (
              <img key={r.item_id}
                src={r.file_id != null
                  ? api.thumbUrl(r.file_id, r.rotation, r.thumb_token)
                  : undefined}
                // An UNDECIDED picture is a click away too: nothing was
                // written for it, so there is nothing to revert, but it left
                // the pool with the batch and the summary is the one place it
                // can still be found — reopening puts it back in the first
                // cell to be answered like any other.
                title={g.key === "none"
                  ? t("{name} — nothing was written for it; click to answer it",
                      { name: r.name || r.uid })
                  : t("{name} — click to answer it again",
                      { name: r.name || r.uid })}
                onClick={() => onReopen(r.item_id)}
                style={{ width: 84, height: 64, objectFit: "cover",
                         borderRadius: "var(--r-2)", cursor: "pointer",
                         border: "1px solid var(--overlay-hairline)" }} />
            ))}
          </div>
        </div>
      ))}
      {onKeepGoing && (
        <div style={{ display: "flex", justifyContent: "center" }}>
          <Button variant="scrim" size="sm" onClick={onKeepGoing}>
            {t("Keep sorting")}
          </Button>
        </div>
      )}
    </div>
  );
}
