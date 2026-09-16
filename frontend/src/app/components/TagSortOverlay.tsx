/** Tag images from the keyboard, one at a time — the Tag batch overlay.
 *
 * The grid's quick-actions **"Tag batch…"** row opens it over a dimmed
 * library, beside "Rate batch…" in the keyboard-overlay family (neither has
 * a letter of its own: two session overlays each claiming one was a keyboard
 * nobody could learn). ONE configuration step decides the mode: one tag is a
 * yes/no session, several become digits that TOGGLE, and ↓ commits. The set
 * is tags and GROUPS of tags (`tagSort.ts` says what each is): a mutually
 * exclusive group holds one lit tag at a time — lighting another puts the
 * lit one out — and a group's "assign negative tags" is what writes its
 * unlit tags negatively on commit; a tag may name a counter tag written
 * positively instead. Two keys advance and mean different things
 * everywhere: `Space` is the pure skip (nothing written, not shown again
 * this session), `↓` commits the image as it stands. `↑` reverts the
 * previous answer's whole event fan and returns to it.
 *
 * The SESSION'S POOL is the family's scope rule: a selection if one is held,
 * else the view the grid shows, captured at open. Every answer is an
 * ordinary revertible assignment written immediately; the classifier behind
 * `/api/tagsort/next` only ORDERS the queue — a coalesced background fetch
 * after each answer replaces the unshown tail, so the model's re-ranking
 * lands within one answer without ever blocking a keypress.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { dropHalf, gripProps, useDragEndReset } from "../../shared/useDragRow";
import { storage } from "../../shared/storage";
import { IconButton } from "../../shared/IconButton";
import { patchRows, useItemPatches } from "./shared/useItemPatches";
import { Button } from "../../shared/Button";
import { useSessionUndo } from "./shared/useSessionUndo";
import { ActionToast } from "./shared/ActionToast";
import { useInlineEdit } from "../../shared/useInlineEdit";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RankingItemRef, TagSortNextOut } from "../api";
import { EmbedModelPicker } from "./EmbedModelPicker";
import { Icon } from "../../shared/Icon";
import { LAYER } from "../../shared/layers";
import { loadFlag, quickTagIsOpen, saveFlag, useUI } from "../store";
import { useErrText, useT, useTn } from "../i18n";
import { useViewScope } from "../useItems";
import { bumpLibrary } from "../invalidation";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { Overlay } from "../../shared/Overlay";
import { Cap, JudgeCard } from "./shared/JudgeCard";
import { useSessionKeys } from "./shared/useSessionKeys";
import { card, OptionRow, sectionLabel } from "./ImportOverlay";
import { fetchTagNameSuggestions, TagAutocomplete } from "./TagAutocomplete";
import type { PickedCategory } from "./TagSetBrowse";
import { groupTagInstances, ItemInfoPanel } from "./shared/ItemInfoPanel";
import { SessionTrouble, SessionWait } from "./shared/SessionStates";
import { sessionBody } from "../sessionBody";
import {
  CommitPlan, JudgedEntry, MAX_TAGS, mergeQueue, modeOf, moveGroup,
  moveTagTo, parseTagSortConfig, chosenOf, clearTags, applyPreset,
  groupOf, presetOf, renameTag, keyOf, maxKey, parseTagSortPresets,
  planCommit, planNone,
  planSingle, serializeTagSortConfig, serializeTagSortPresets,
  sessionNegatives, summarize, tagNames, tagsForKey, toggleTags,
  TAGSORT_KEY, TAGSORT_PRESETS_KEY, TagSortConfig,
  TagSortGroup, TagSortPreset, updateGroup, wireCounters, wireGroups,
  withCounter, withGroup, withoutGroup, withoutTag, withTag, FUSED,
  embeddersOf, groupRowName, withGroupRow, plainTags, rowLabel, rowLabels,
} from "../tagSort";
import { flattenGroupTree } from "./GroupSelect";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import type { TagSetText } from "../api";
import { DescriptionMark } from "./DescribedFields";
import { ConfirmModal } from "../../shared/ConfirmModal";
import { useMenuDismiss } from "../../shared/useMenuDismiss";

/** How many refs one feed request returns — the local queue's depth. */
const QUEUE_COUNT = 12;

/** Whether the info panel is wanted, across reloads. Its OWN key rather than
 *  the preview's: whether you want the library's answer beside a picture you
 *  are judging is a different habit from wanting it beside one you are
 *  looking at, and one flag would make each overlay change the other. */
const INFO_KEY = "mc.tagSortInfo";

/** One step of the session — an answer with the events it wrote, or a skip
 *  (Space), which wrote nothing. ONE stack, newest last: ↑ takes back
 *  whichever happened last, which two stacks had to work out through the
 *  `recent` list's tail. */
type Step =
  | ({ kind: "judge" } & JudgedEntry<RankingItemRef>)
  | { kind: "skip"; ref: RankingItemRef };
type JudgeStep = Extract<Step, { kind: "judge" }>;

export function TagSortOverlay() {
  const t = useT();
  const tn = useTn();
  const errText = useErrText();
  const qc = useQueryClient();
  const open = useUI((s) => s.tagSortOpen);
  const setOpen = useUI((s) => s.setTagSortOpen);
  const inLibrary = useUI((s) => s.view) === "library";
  const view = useViewScope(inLibrary && open);

  // ---- configuration (the chooser) ----------------------------------------
  const [cfg, setCfg] = useState<TagSortConfig>(
    () => parseTagSortConfig(storage.get(TAGSORT_KEY)));
  // null = still configuring; once started, the running session's config is
  // frozen — and changed only through the Settings dialog, whose Continue
  // hands over a whole new config rather than editing this one in place.
  const [running, setRunning] = useState<TagSortConfig | null>(null);
  // The chooser over a RUNNING session — every setting changeable
  // mid-run, and Continue picks up from the picture on screen.
  const [configuring, setConfiguring] = useState(false);

  // ---- session state -------------------------------------------------------
  const [queue, setQueue] = useState<RankingItemRef[]>([]);
  //: THE CARD FOLLOWS THE ITEM (`useItemPatches`): a turn made in the
  //  preview over the session reaches the queue's row.
  useItemPatches((d) => setQueue((cur) => patchRows(cur, d)));
  // What the pool held when the session was handed its first figure — with
  // `shown` taken off it, that IS the pool (see `want_pool` below). Null
  // until the first reply carries one.
  const pool0 = useRef<number | null>(null);
  // NULL until that first reply — the header omits the figure then, rather
  // than reading a pool nobody has counted yet as "0 left".
  const [pool, setPool] = useState<number | null>(null);
  /** The header's figure, derived rather than fetched. `recent` is a ref (a
   *  render per keypress is not something the queue can afford), so every
   *  place that changes it says so here. */
  const syncPool = () =>
    setPool(pool0.current == null ? null
      : Math.max(0, pool0.current - recent.current.length));
  const [ordered, setOrdered] = useState(false);
  // Toggled tag NAMES, not positions: the list is editable mid-session, so a
  // position stops being an identity the moment a row moves.
  const [toggles, setToggles] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  // A fetch in flight, and the last one's failure — what the body shows
  // while there is no picture to show (`sessionBody`). A failed fetch used
  // to vanish, nothing having caught it, and the session then sat on its
  // empty summary reading "0 left in the pool".
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  // The session's side panel: the PREVIEW's info panel, on the preview's
  // own key — what the library already says about this picture is most of
  // what decides the answer. (A tag-list panel sat on the other side for a
  // while and is gone: the Settings dialog edits the set, and one place
  // for that is one set of rules.)
  const [showInfo, setShowInfo] = useState(() => loadFlag(INFO_KEY, false));
  const [note, setNote] = useState<string | null>(null);
  const steps = useSessionUndo<Step>();
  const judgedEntries = (): JudgeStep[] =>
    steps.steps.filter((s): s is JudgeStep => s.kind === "judge");
  const recent = useRef<number[]>([]);
  const scopeRef = useRef<Record<string, unknown> | null>(null);
  const cameFrom = useRef<HTMLElement | null>(null);
  const fetching = useRef(false);
  const wantRefetch = useRef(false);
  // A render-fresh view of the session for the once-registered key handler.
  const live = useRef({ running, queue, toggles, busy, summaryOpen,
                        confirmEnd, configuring });
  live.current = { running, queue, toggles, busy, summaryOpen, confirmEnd,
                   configuring };

  // Capture the scope (and the return-focus target) the moment it opens —
  // the rating overlay's rule: the session must not chase the grid under it.
  useEffect(() => {
    if (!open) return;
    if (scopeRef.current == null) {
      cameFrom.current = document.activeElement as HTMLElement | null;
      // The POOL is always the view — a selection never fences it in. What
      // a selection means is PRIORITY (the rankings' rule): `items` rides
      // beside the search body and those pictures lead the queue, one item
      // included.
      const sel = useUI.getState().selectedItems;
      scopeRef.current = {
        ...(useUI.getState().view === "library"
          ? ({ ...view.req } as unknown as Record<string, unknown>) : {}),
        ...(sel.length > 0 ? { items: sel } : {}),
      };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Hand the focus back on the way out.
  useEffect(() => {
    if (open) return;
    const el = cameFrom.current;
    cameFrom.current = null;
    scopeRef.current = null;
    if (el && el.isConnected) el.focus();
  }, [open]);


  const { data: mlModels } = useQuery({
    queryKey: ["ml-models"], queryFn: api.mlModels, enabled: open });
  const { data: modelCache } = useQuery({
    queryKey: ["model-cache"], queryFn: api.modelCache, enabled: open });
  // Every embed model the registry lists, each with its own readiness —
  // DINOv2 and CLIP index independent spaces, so "ready" is a fact about
  // the CHOSEN one, not about the family.
  const embedModels = useMemo(() => {
    const cached = new Map((modelCache?.models ?? [])
      .map((m) => [m.key, m.cached]));
    const task = (mlModels?.tasks ?? []).find((tk) => tk.kind === "embed");
    return (task?.models ?? []).map((m) => ({
      id: m.id, name: m.name, family: m.family,
      ready: m.available
        && (m.family_keys ?? []).every((k) => cached.get(k) !== false),
      // The Settings → Models row to land on when this embedder is missing
      // — its first cache key, which is what that page keys rows by.
      key: m.family_keys?.[0] ?? null,
    }));
  }, [mlModels, modelCache]);
  const embedIds = embedModels.map((m) => m.id);
  // The picker's rows: every model, then — with two or more — the fused
  // option (the grid's), which is every space at once: each fit on its
  // own, the scores averaged. It is the DEFAULT (`tagSort.FUSED` says why).
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
  // What every request names — the RESOLVED list: a stored id whose plugin
  // has gone falls back to the first listed model rather than a 400 by
  // name, and `FUSED` is every listed model.
  const embedders = embeddersOf(cfg.embedder, embedIds);
  const embedderChoice = cfg.embedder === FUSED && embedModels.length >= 2
    ? FUSED : (embedders[0] ?? cfg.embedder);
  const embedReady = embedders.length > 0 && embedders.every(
    (id) => embedModels.find((m) => m.id === id)?.ready);
  // The Settings → Models card to land on: the first of the chosen spaces
  // that is not set up.
  const embedKey = embedders
    .map((id) => embedModels.find((m) => m.id === id))
    .find((m) => m && !m.ready)?.key ?? null;
  const embedIdsRef = useRef<string[]>(embedIds);
  embedIdsRef.current = embedIds;
  // A running index job: the chooser polls the job list while it is open —
  // its own Detect-text lesson: the library's job-finish sweep lives in
  // JobList, which polls only while IT can see something active, so this
  // dialog watches for itself and shows the run's progress in place of the
  // button.
  const chooserOpen = open && (running == null || configuring);
  const { data: jobsData } = useQuery({
    queryKey: ["ml-jobs"], queryFn: api.mlJobs,
    enabled: chooserOpen, refetchInterval: chooserOpen ? 2500 : false,
    // The editor's Detect-text lesson: indexing is exactly the wait you
    // spend in another window, and without this the poll freezes there —
    // the run finishes and the dialog goes on saying "Indexing… 0%".
    refetchIntervalInBackground: true,
  });
  const embedJob = (jobsData?.jobs ?? []).find(
    (j) => j.kind === "embed"
      && (j.status === "running" || j.status === "queued")) ?? null;
  // The chooser's coverage probe — how much of the scope is indexed, and
  // whether an embed model is ready to index the rest. It follows a live
  // index run (the per-chunk commits make the count climb) and refreshes
  // once more when the run ends.
  const probe = useQuery({
    // Keyed on what can CHANGE THE ANSWER — the tags, the counter tags
    // (an item carrying one is decided), the spaces, the kind — and not on
    // a group's switches, which the probe never reads: keyed on those,
    // the first flip of a switch emptied the answer until the refetch
    // landed, and the Ordering row lost its coverage lines for a beat,
    // which resized the whole dialog under the pointer.
    queryKey: ["tagsort-probe", open, plainTags(cfg).join("|"),
               JSON.stringify(wireCounters(cfg)),
               embedders.join("|"), cfg.kind],
    enabled: chooserOpen && plainTags(cfg).length > 0,
    // And the previous answer HOLDS while a new one is on its way, for
    // the changes that do refetch — the figures move, the rows do not.
    placeholderData: (prev) => prev,
    refetchInterval: chooserOpen && embedJob != null ? 3000 : false,
    refetchIntervalInBackground: true,
    queryFn: () => api.tagSortNext({
      ...(scopeRef.current as object ?? {}),
      // The session's KIND overrides the view's own filter: a session asks
      // about one kind, and the coverage figure has to count what it will
      // actually be shown (a film carries no vector and never will).
      kind: cfg.kind,
      ...(cfg.skipSequenced ? { hide_sequenced: true } : {}),
      tags: plainTags(cfg), tag_groups: wireGroups(cfg),
      counter_tags: wireCounters(cfg), count: 0, embedders,
    } as Parameters<typeof api.tagSortNext>[0])
      // The coverage probe is the one call that always counts — `count: 0`
      // IS the request for those numbers — so it is the one place `total`
      // cannot be null.
      .then((r) => ({ ...r, total: r.total ?? 0 })),
  });
  const hadJob = useRef(false);
  useEffect(() => {
    if (embedJob != null) hadJob.current = true;
    else if (hadJob.current) {
      hadJob.current = false;
      void qc.invalidateQueries({ queryKey: ["tagsort-probe"] });
    }
  }, [embedJob != null, qc]);
  const fetchMore = async (config: TagSortConfig) => {
    if (fetching.current) { wantRefetch.current = true; return; }
    fetching.current = true;
    setLoading(true);
    setFailed(null);
    try {
      const got: TagSortNextOut = await api.tagSortNext({
        ...(scopeRef.current as object ?? {}),
        kind: config.kind,
        ...(config.skipSequenced ? { hide_sequenced: true } : {}),
        tags: plainTags(config), tag_groups: wireGroups(config),
        counter_tags: wireCounters(config),
        smart: config.smart,
        // The choice resolved against the models listed NOW — `FUSED` is
        // every one of them, a lone id itself.
        embedders: embeddersOf(config.embedder, embedIdsRef.current),
        recent: recent.current,
        // What is still held unshown: the last fit's best candidates, which
        // the server's fresh sample would otherwise drop and re-find only by
        // luck — carried, the ordering accumulates across answers.
        carry: live.current.queue.map((r) => r.item_id),
        // The implicit negatives — a tag whose "unlit" writes nothing —
        // are never written, so they travel to the fit as session data.
        session_negatives: sessionNegatives(config, judgedEntries()),
        count: QUEUE_COUNT,
        // ASKED ONCE. The pool's size is a count over everything the scope
        // admits minus what is decided — 750 ms at a million items, and it
        // was paid on every answer for a number the session already knows:
        // every item it is handed leaves the candidate set exactly once
        // (answered it is decided, skipped it is in `recent`), so what is
        // left is the figure it started with minus how many it has shown.
        want_pool: pool0.current == null,
      } as Parameters<typeof api.tagSortNext>[0]);
      if (got.pool != null) pool0.current = got.pool + recent.current.length;
      syncPool();
      setOrdered(got.ordered);
      // The item ON SCREEN stays put; the unshown tail takes the fresh
      // ordering — re-ranking lands without moving what you are looking at.
      const shown = new Set(recent.current);
      setQueue((cur) => mergeQueue(cur, got.queue, shown));
    } catch (e) {
      setFailed(errText(e));
    } finally {
      fetching.current = false;
      setLoading(false);
      if (wantRefetch.current) {
        wantRefetch.current = false;
        void fetchMore(config);
      }
    }
  };

  /** CONTINUE, from the chooser over a running session: the new settings
   *  take over from the picture on screen. The judged stack, the skip
   *  memory and the item on screen all stay; the pool is asked again (the
   *  kind or the sequence rule may have changed it) and the unshown tail
   *  is refetched under the new ordering. */
  const applyConfig = () => {
    if (plainTags(cfg).length === 0) return;
    const config = { ...cfg, embedder: embedderChoice };
    storage.set(TAGSORT_KEY, serializeTagSortConfig(config));
    setRunning(config);
    setConfiguring(false);
    setToggles(new Set());
    pool0.current = null;
    setQueue((cur) => cur.slice(0, 1));
    void fetchMore(config);
  };

  const start = () => {
    if (plainTags(cfg).length === 0) return;
    // The RESOLVED embedder id is frozen in — a stored id whose plugin has
    // gone must not ride into the session and 400 every fetch by name.
    const config = { ...cfg, embedder: embedderChoice };
    storage.set(TAGSORT_KEY, serializeTagSortConfig(config));
    steps.clear();
    recent.current = [];
    pool0.current = null;
    setPool(null);
    setFailed(null);
    setQueue([]);
    setToggles(new Set());
    setSummaryOpen(false);
    setRunning(config);
    void fetchMore(config);
  };


  const current: RankingItemRef | null = queue[0] ?? null;

  // What the library already says about the picture on screen — the same
  // query key the preview uses, so React Query serves one fetch to both.
  const { data: infoDetail } = useQuery({
    queryKey: ["item", current?.item_id],
    queryFn: () => api.item(current!.item_id),
    enabled: open && showInfo && current != null,
  });
  const infoGroups = useMemo(
    () => groupTagInstances(infoDetail), [infoDetail]);

  /** WHICH VISIT THIS IS — bumped wherever the head of the queue changes
   *  (answered, undone, reopened), which is what the card's zoom follows.
   *  The item's own id cannot: reopening one from the summary shows the
   *  same picture and is a fresh question, and a magnification left over
   *  from the last look at it is not what somebody correcting an answer is
   *  asking for. Not derived from the queue's length either — a prefetch
   *  appends to it while the same item is still being decided. */
  const [visit, setVisit] = useState(0);

  const advance = (config: TagSortConfig) => {
    setToggles(new Set());
    setVisit((v) => v + 1);
    setQueue((cur) => cur.slice(1));
    void fetchMore(config);
  };

  /** Write one answer's plan and move on. A null plan is a commit that says
   *  nothing — the item is set aside like a skip, but deliberately (↓). */
  const commit = async (plan: CommitPlan | null, chosen: string[]) => {
    const config = live.current.running;
    const ref = live.current.queue[0];
    if (!config || !ref || live.current.busy) return;
    setBusy(true);
    try {
      recent.current.push(ref.item_id);
      syncPool();
      if (plan == null) {
        steps.push({ kind: "skip", ref });
      } else {
        const fans: number[] = [];
        for (const name of plan.positive) {
          const res = await api.assignItemTag(ref.item_id, name, false);
          fans.push(...(res.event_ids ?? []));
        }
        for (const name of plan.negative) {
          const res = await api.assignItemTag(ref.item_id, name, true);
          fans.push(...(res.event_ids ?? []));
        }
        // THE LIT GROUP ROWS, in one request — the same per-item events the
        // sidebar writes, so ↑ takes them back with the tags.
        if (plan.groups.length > 0) {
          const res = await api.bulkGroupMembership([ref.item_id],
                                                    plan.groups, []);
          fans.push(...(res.event_ids ?? []));
        }
        steps.push({ kind: "judge", ref, chosen, eventIds: fans });
        // The Details panel reads this item's tags: with the item still on
        // screen (a ↑ away) a cached detail would show the answer that has
        // just been un-written, or miss the one just written.
        void qc.invalidateQueries({ queryKey: ["item", ref.item_id] });
      }
      advance(config);
    } finally {
      setBusy(false);
    }
  };

  const skip = () => {
    const config = live.current.running;
    const ref = live.current.queue[0];
    if (!config || !ref || live.current.busy) return;
    recent.current.push(ref.item_id);
    syncPool();
    steps.push({ kind: "skip", ref });
    advance(config);
  };

  /** ↑ — back to the previous item, un-writing its whole event fan. */
  const undo = async () => {
    const config = live.current.running;
    if (!config || live.current.busy) return;
    // Whichever happened LAST is what ↑ takes back — the stack's top.
    const last = steps.peek();
    if (!last) return;
    setBusy(true);
    try {
      steps.pop();
      // The Details panel reads this item's tags: with the item back on
      // screen a cached detail would show the answer just un-written.
      if (last.kind === "judge") await steps.revert(last.eventIds, [last.ref.item_id]);
      recent.current.pop();
      syncPool();
      const back = last.ref;
      setSummaryOpen(false);
      setToggles(new Set());
      setVisit((v) => v + 1);
      setQueue((cur) => [back, ...cur.filter(
        (r) => r.item_id !== back.item_id)]);
    } finally {
      setBusy(false);
    }
  };

  /** A summary thumbnail is a way BACK: un-write that item's whole fan and
   *  re-present it, so a wrong answer can be corrected without ↑-ing through
   *  everything decided since. */
  const reopen = async (itemId: number) => {
    if (live.current.busy) return;
    if (!judgedEntries().some((j) => j.ref.item_id === itemId)) return;
    setBusy(true);
    try {
      const entry = steps.drop(
        (s) => s.kind === "judge" && s.ref.item_id === itemId) as JudgeStep;
      await steps.revert(entry.eventIds, [itemId]);
      const r = recent.current.lastIndexOf(itemId);
      if (r >= 0) { recent.current.splice(r, 1); syncPool(); }
      setSummaryOpen(false);
      setToggles(new Set());
      setVisit((v) => v + 1);
      setQueue((cur) => [entry.ref,
                         ...cur.filter((x) => x.item_id !== itemId)]);
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    // Through the live ref, never the closure: the key handler is
    // registered once and captured the first render's `running` (null), so
    // an Esc-close read "no session" and skipped the note the ✕ showed.
    const config = live.current.running;
    const n = judgedEntries().length;
    setOpen(false);
    setRunning(null);
    setSummaryOpen(false);
    setConfirmEnd(false);
    setQueue([]);
    if (config && n > 0) {
      bumpLibrary();
      qc.invalidateQueries({ queryKey: ["tags"] });
      const names = rowLabels(config);
      if (names.length === 1) {
        const s = summarize(judgedEntries(), tagNames(config));
        setNote(tn(
          { one: "{n} decided on {tag} — {yes} yes · {no} no",
            other: "{n} decided on {tag} — {yes} yes · {no} no" },
          s.decided,
          { tag: names[0], yes: String(s.perTag[0]),
            no: String(s.decided - s.perTag[0]) }));
      } else {
        setNote(tn({ one: "{n} image filed across {k} tags",
                     other: "{n} images filed across {k} tags" },
                   n, { k: String(names.length) }));
      }
    }
  };

  /** EVERY WAY OUT GOES THROUGH ONE GUARD — Escape, the header's ✕ and the
   *  backdrop — the rate session's rule. A session that has ANSWERED
   *  nothing skips the question: there is nothing to confirm. */
  const askClose = () => {
    if (steps.size === 0) {
      close();
      return;
    }
    setConfirmEnd(true);
  };

  // ---- keyboard ------------------------------------------------------------
  // The sessions' one spine (`useSessionKeys`): the gates, Escape through
  // the stack, Tab, undo, Space and S are its; the answers are this
  // session's own. The chooser is an ordinary dialog and owns its own keys.
  const plain = (e: KeyboardEvent) => !e.metaKey && !e.ctrlKey && !e.altKey;
  useSessionKeys({
    isOpen: () => useUI.getState().tagSortOpen && live.current.running != null,
    escape: open && running != null && !configuring,
    // While the T field floats over the session, every key is the field's
    // — and while the chooser is over it, the chooser's.
    standDown: () => quickTagIsOpen() || live.current.configuring
      || live.current.confirmEnd,
    onEscape: askClose,
    // TAB toggles the SUMMARY — the rate overlay's standings key, and the
    // tag grid's: the summary is a mode rather than a step, so it is
    // reached and left by one key. (It used to toggle the info panel,
    // which is `I` now.)
    onTab: () => setSummaryOpen((v) => !v),
    summaryOpen: () => live.current.summaryOpen,
    undo: { match: (e) => e.key === "u" || e.key === "U" || e.key === "ArrowUp",
            run: () => void undo() },
    // SPACE IS THE PREVIEW — the picture on screen, large, with the
    // preview's own zoom (the card's went with it).
    preview: () => {
      const st = useUI.getState();
      if (st.quickLook) { st.setQuickLook(false); return; }
      const ref = live.current.queue[0];
      if (ref) st.openQuickLook([ref.item_id]);
    },
    skip,
    keys: [
      // I toggles the info panel: what the library already says about the
      // picture, beside it.
      { match: (e) => (e.key === "i" || e.key === "I") && plain(e),
        underSummary: true,
        run: () => setShowInfo((v) => { saveFlag(INFO_KEY, !v); return !v; }) },
      // T — more to say about THIS picture than the session's tags: the
      // quick tag field, aimed at the item on screen rather than at the grid.
      { match: (e) => (e.key === "t" || e.key === "T") && plain(e)
          && live.current.queue[0] != null,
        run: () => useUI.getState().requestQuickTag([live.current.queue[0].item_id]) },
      // The picture as it stands. In the LIST's order, not the order the
      // digits were pressed — the summary reads it, and the list is what
      // the summary groups by.
      { match: (e) => e.key === "ArrowDown",
        run: () => {
          const st = live.current;
          void commit(planCommit(st.running!, st.toggles),
                      chosenOf(st.running!, st.toggles));
        } },
      { match: (e) => modeOf(live.current.running!) === "single"
          && (e.key === "ArrowRight" || e.key === "y" || e.key === "Y"),
        run: () => {
          const st = live.current;
          void commit(planSingle(st.running!, true), [tagNames(st.running!)[0]]);
        } },
      // "No" — the counter tag, the group's negative, or (a bare root
      // tag) nothing: a skip in effect, but deliberate, like ↓.
      { match: (e) => modeOf(live.current.running!) === "single"
          && (e.key === "ArrowLeft" || e.key === "n" || e.key === "N"),
        run: () => void commit(planSingle(live.current.running!, false), []) },
      // A digit is EVERY tag keyed to it — one, or several sharing it
      // (a chip click stays about its own tag) — flipped; lighting a
      // tag in an exclusive group puts the group's others out.
      { match: (e) => modeOf(live.current.running!) !== "single"
          && e.key >= "1" && e.key <= "9"
          && tagsForKey(live.current.running!, Number(e.key)).length > 0,
        run: (e) => {
          const st = live.current;
          const names = tagsForKey(st.running!, Number(e.key));
          const next = toggleTags(st.running!, st.toggles, names);
          setToggles(next);
          // NEXT PICTURE ON ANSWER, where the group asked for it. It is a
          // property of the QUESTION rather than of the session: a one-tag
          // "is this a screenshot" is answered and done, while a group of
          // nine costume tags wants several presses before the picture is
          // finished with. Only where the press LIT something — putting a
          // tag out is a correction, and moving on from a correction takes
          // the picture away mid-thought.
          const grp = groupOf(st.running!, names[0]);
          const lit = names.some((n) => next.has(n) && !st.toggles.has(n));
          if (grp?.advance && lit) {
            void commit(planCommit(st.running!, next), chosenOf(st.running!, next));
          }
        } },
      // None of these — the commit with nothing lit.
      { match: (e) => modeOf(live.current.running!) !== "single" && e.key === "0",
        run: () => void commit(planNone(live.current.running!), []) },
    ],
  });

  // Grab the keyboard while open (the rating overlay's focus rule).
  const frameRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) frameRef.current?.focus();
  }, [open, running]);

  const backdrop = useBackdropDismiss(() => askClose());

  if (!open && !note) return null;

  const mode = running ? modeOf(running) : modeOf(cfg);
  // What the body shows with no picture queued is `sessionBody`'s rule: a
  // fetch in flight is LOADING and a failed one is an ERROR — neither is
  // the empty summary this used to put up the moment Start was pressed,
  // which on a big scope stood for as long as the first reply took.
  const body = running == null ? null
    : sessionBody({ loading, failed: failed != null, queued: queue.length });
  const exhausted = body === "exhausted";
  const showSummary = running != null && (summaryOpen || exhausted);
  const judgedNow = running ? judgedEntries() : [];
  const s = running ? summarize(judgedNow, tagNames(running)) : null;

  // An ANSWERED probe saying the scope holds nothing to decide disables
  // Start — a session over zero pictures is a full-screen empty state. Only
  // once answered: blocking on an in-flight probe would flicker the button.
  const scopeEmpty = probe.data != null && probe.data.total === 0;
  // AT LEAST ONE TAG, not merely one row: the queue is "pictures not yet
  // decided for these tags", ordered by what the classifier has learned
  // about them, and a session of nothing but group rows has neither a pool
  // nor an order to ask for. A group rides along with the tags; it cannot
  // be the whole question.
  const canStart = plainTags(cfg).length > 0 && !scopeEmpty;

  // The CHOOSER is an ordinary dialog — header, ✕, footer — and only Start
  // opens the full-screen session over the library.
  const chooser = open && (running == null || configuring) && (
    <Overlay icon={configuring ? "tune" : "new_label"}
      title={configuring ? t("Session settings") : t("Tag items one by one")}
      subtitle={configuring
        ? t("Changes take over from the picture on screen.")
        : t("What do you want to tag?")}
      width={560}
      onClose={() => { if (configuring) setConfiguring(false); else close(); }}
      footer={<>
        {/* The reason Start is dim, where the button is. The options column
            above must not grow and shrink as the answer changes — an "Ask
            about" flip moved every row under it. */}
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
          if (scopeEmpty || !embedReady || !cfg.smart || p == null || p.total <= 0) return null;
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
        presets={<TagSortPresets cfg={cfg}
          onLoad={(p) => setCfg((c) => applyPreset(c, p))} t={t} />}
        probe={probe.data ?? null} embedReady={embedReady}
        pickerModels={pickerModels} embedderChoice={embedderChoice}
        embedders={embedders}
        embedNames={new Map(embedModels.map((m) => [m.id, m.name]))}
        embedJob={embedJob}
        scopeRef={scopeRef}
        scopeEmpty={scopeEmpty}
        onOpenModels={() => {
          // Leaving to set the embedder up: land on the Models page with the
          // embedder's own card highlighted (the AiActionButtons pattern),
          // and close this dialog rather than stacking two modals.
          const st = useUI.getState();
          if (embedKey) {
            st.setSettingsFocusModel(embedKey);
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
      {createPortal(
    <>
      {open && running != null && !configuring && (
      <div {...backdrop}
        style={{ position: "fixed", inset: 0, zIndex: LAYER.session,
                 background: "var(--scrim-3)", display: "flex",
                 flexDirection: "column", padding: "28px 36px", gap: 14,
                 color: "var(--on-scrim)" }}>
        <div ref={frameRef} tabIndex={-1}
          onMouseDown={(e) => e.stopPropagation()}
          style={{ outline: "none", display: "flex", flexDirection: "column",
                   flex: 1, minHeight: 0, gap: 14 }}>
          {/* ---- header ---- */}
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ fontSize: "var(--fs-5)", fontWeight: 600 }}>
              {rowLabels(running).join(" · ")}
            </div>
            <div style={{ fontSize: "var(--fs-3)", color: "var(--on-scrim-2)" }}>
              {tn({ one: "1 decided this session",
                    other: "{n} decided this session" },
                  judgedNow.length)}
              {pool != null && (<>
                {" · "}
                {tn({ one: "1 left to decide",
                      other: "{n} left to decide" }, pool)}
              </>)}
              {/* "unordered" flags the SURPRISE (no vectors to order by) —
                  a session with smart ordering switched off chose this. */}
              {!ordered && queue.length > 0 && running.smart && (
                <span> · {t("unordered")}</span>
              )}
            </div>
            <span style={{ flex: 1 }} />
            {!showSummary && (
              // EVERY setting, mid-session: the chooser again, over the run,
              // and Continue picks up from the picture on screen. The sheet
              // steps aside while it is up — the dialog layer sits under
              // the session's, so it cannot be shown over it.
              <HeadBtn icon="tune" label={t("Settings")}
                title={t("Change this session's settings")}
                onClick={() => { setCfg(running); setConfiguring(true); }} />
            )}
            {!showSummary && current != null && (
              <HeadBtn icon="info" label={t("Details")} on={showInfo}
                title={t("Tags and captions already on this picture (I)")}
                onClick={() => setShowInfo((v) => {
                  saveFlag(INFO_KEY, !v); return !v; })} />
            )}
            {(current != null || showSummary) && (
              // The summary without ending the session — what Tab also
              // toggles (and what Esc shows first). A TOGGLE, lit while it
              // is up; exhausted, the summary is all there is.
              <HeadBtn icon="format_list_numbered" label={t("Summary")}
                on={showSummary}
                title={t("Show or hide the session summary (Tab)")}
                onClick={() => { if (!exhausted) setSummaryOpen((v) => !v); }} />
            )}
            <span className="hoverable" onClick={() => askClose()}
              title={t("End the session (Esc)")}
              style={{ display: "flex", padding: 6, borderRadius: "var(--r-3)",
                       cursor: "pointer" }}>
              <Icon name="close" size={20} />
            </span>
          </div>

          {/* ---- body ---- */}
          {showSummary ? (
            <Summary running={running} judged={judgedNow}
              skippedCount={steps.size - judgedNow.length} s={s!}
              onKeepGoing={!exhausted
                ? () => setSummaryOpen(false) : undefined}
              onReopen={(id) => void reopen(id)}
              t={t} tn={tn} />
          ) : current != null ? (
            // The card beside its panel — what is already known about the
            // picture. It takes room from the card rather than covering it:
            // a panel over the picture is a panel in the way of the answer.
            <div style={{ flex: 1, minHeight: 0, display: "flex", gap: 14 }}>
            <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex",
                          flexDirection: "column", gap: 10 }}>
              <JudgeCard side={current} busy={busy}
                onRotated={() => bumpLibrary()} />
              <div style={{ display: "flex", alignItems: "center", gap: 8,
                            color: "var(--on-scrim-2)", fontSize: "var(--fs-3)",
                            justifyContent: "center" }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                               whiteSpace: "nowrap" }}>
                  {current.name || current.uid}
                </span>
              </div>
              {mode !== "single" && running != null && (
                <Legend running={running} lit={toggles}
                  onToggle={(name) => setToggles(
                    (cur) => toggleTags(running, cur, [name]))} />
              )}
            </div>
            {showInfo && (
              <ItemInfoPanel detail={infoDetail} groupedTags={infoGroups}
                style={{ maxHeight: "100%" }}
                onChanged={() => {
                  if (infoDetail) qc.invalidateQueries({ queryKey: ["item", infoDetail.id] });
                  bumpLibrary();
                }} />
            )}
            </div>
          ) : body === "error" ? (
            <SessionTrouble
              message={t("The next picture could not be loaded.")}
              detail={failed} onRetry={() => void fetchMore(running)} t={t} />
          ) : (
            <SessionWait label={t("Loading…")} />
          )}

          {/* ---- keycap footer ---- */}
          <div style={{ display: "flex", gap: 18, justifyContent: "center",
                        fontSize: "var(--fs-3)", color: "var(--on-scrim-2)" }}>
            {showSummary ? (
              <>
                {(judgedNow.length > 0) && (
                  <span><Cap>↑</Cap> {t("undo")}</span>
                )}
                {!exhausted && <span><Cap>Tab</Cap> {t("keep tagging")}</span>}
                <span><Cap>Esc</Cap> {t("end")}</span>
              </>
            ) : (
              <>
                {/* ← before → — the keys read in keyboard order. A "no"
                    that writes nothing is ↓'s job, so ← is spelled out
                    only where it says something. */}
                {mode === "single" && running != null
                  && planSingle(running, false) != null && (
                  <span><Cap>←</Cap> {t("doesn't fit")}</span>
                )}
                {mode === "single" && (
                  <span><Cap>→</Cap> {t("fits")}</span>
                )}
                {mode === "multi" && (
                  <span><Cap>1</Cap>–<Cap>{String(maxKey(running!))}</Cap>{" "}
                    {t("toggle")}</span>
                )}
                <span><Cap>↓</Cap> {t("next")}</span>
                {mode === "multi" && running != null
                  && planNone(running) != null && (
                  <span><Cap>0</Cap> {t("none of these")}</span>
                )}
                <span><Cap>S</Cap> {t("skip")}</span>
                <span><Cap>Space</Cap> {t("preview")}</span>
                <span><Cap>↑</Cap> {t("undo")}</span>
                <span><Cap>T</Cap> {t("more tags")}</span>
                <span><Cap>I</Cap> {t("details")}</span>
                <span><Cap>Tab</Cap> {t("summary")}</span>
                <span><Cap>Esc</Cap> {t("end")}</span>
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
                      judgedNow.length)}
              cancel={t("Keep tagging")}
              answer={{ label: t("End session") }}
              onResult={(r) => { setConfirmEnd(false); if (r === "answer") close(); }} />
          )}
        </div>
      </div>
      )}
      {note && (
        <ActionToast text={note} autoDismissMs={4000} onDismiss={() => setNote(null)} />
      )}
    </>,
    document.body,
  )}
    </>
  );
}

/** A header toggle in the session's own chrome — the Summary button's shape,
 *  lit while its panel is open. */
function HeadBtn({ icon, label, on, title, onClick }: {
  icon: string; label: string; on?: boolean; title: string;
  onClick: () => void;
}) {
  return (
    <span className="hoverable" onClick={onClick} title={title}
      style={{ display: "flex", alignItems: "center", gap: 5,
               padding: "4px 10px", borderRadius: "var(--r-3)", cursor: "pointer",
               color: "var(--on-scrim)", fontSize: "var(--fs-3)",
               background: on ? "var(--overlay-wash)" : "transparent",
               border: "1px solid var(--on-scrim-4)" }}>
      <Icon name={icon} size={14} />{label}
    </span>
  );
}

/** THE SESSION'S LEGEND — one chip per tag, lit while it is toggled, in the
 *  set's own shape: each group's tags in a dashed cluster (its tooltip says
 *  which kind of group; nothing is drawn for it — a mark per cluster was
 *  chrome over the chips). A chip click is about its own tag, whatever
 *  digit it shares. */
function Legend({ running, lit, onToggle }: {
  running: TagSortConfig;
  lit: ReadonlySet<string>;
  onToggle: (name: string) => void;
}) {
  const t = useT();
  const chip = (name: string) => {
    const on = lit.has(name);
    const label = rowLabel(running, name);
    return (
      <span key={name} onClick={() => onToggle(name)}
        style={{ display: "flex", alignItems: "center", gap: 6,
                 padding: "4px 10px", borderRadius: "var(--r-4)", cursor: "pointer",
                 border: `1px solid ${on
                   ? "var(--accent)" : "var(--on-scrim-4)"}`,
                 background: on ? "var(--accent)" : "transparent",
                 fontSize: "var(--fs-3)" }}>
        <Cap>{String(keyOf(running, name))}</Cap>
        {label !== name && (
          <Icon name="folder" size={13}
                color={on ? "inherit" : "var(--accent)"} />
        )}
        {label}
      </span>
    );
  };
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8,
                  justifyContent: "center", alignItems: "stretch" }}>
      {running.groups.map((e) => e.tags.length === 0
        || e.enabled === false ? null : (
          <div key={e.id}
            title={e.exclusive ? t("Mutually exclusive — one of these")
                               : t("Any number of these")}
            style={{ display: "flex", alignItems: "center", gap: 6,
                     padding: "4px 6px", borderRadius: "var(--r-6)",
                     border: "1px dashed var(--on-scrim-4)" }}>
            {e.tags.map((tag) => chip(tag.name))}
          </div>
        ))}
    </div>
  );
}

/** What is in the hand, and where it would land. A TAG drags between
 *  groups as well as within one; a GROUP drags among the groups. */
type Drag = { kind: "tag"; name: string } | { kind: "group"; id: string };
type Over =
  | { kind: "tag"; name: string; after: boolean }
  | { kind: "group"; id: string; after: boolean }
  /** A tag over a group but not over one of its rows — its header, its
   *  adder, the gap — lands at the END of that group. */
  | { kind: "into"; id: string };

function sameOver(a: Over | null, b: Over | null): boolean {
  if (a === b) return true;
  if (!a || !b || a.kind !== b.kind) return false;
  if (a.kind === "tag") return b.kind === "tag" && a.name === b.name
    && a.after === b.after;
  if (a.kind === "group") return b.kind === "group" && a.id === b.id
    && a.after === b.after;
  return b.kind === "into" && a.id === b.id;
}

/** ONE DRAG for the whole editor, whichever list a row is in — a tag
 *  carried from one group to another is the same gesture as one reordered
 *  within its own, and the indicator is one piece of state that only ever
 *  changes when the answer does (never per pointer sample). */
function useSetDrag(setCfg: React.Dispatch<React.SetStateAction<TagSortConfig>>) {
  const [drag, setDrag] = useState<Drag | null>(null);
  const [over, setOverState] = useState<Over | null>(null);
  const overRef = useRef<Over | null>(null);
  const setOver = (next: Over | null) => {
    if (sameOver(overRef.current, next)) return;
    overRef.current = next;
    setOverState(next);
  };
  const end = () => { setDrag(null); setOver(null); };
  // THE INDICATOR GOES OUT THE MOMENT THE POINTER LEAVES A ROW. A row's
  // own `dragleave` cannot say so — Chrome and Safari leave `relatedTarget`
  // NULL on drag events — but `dragover` fires wherever the pointer is
  // over the document, so a window listener asks what it is over: not a
  // row, no indicator. Bound only while something is in the hand.
  useEffect(() => {
    if (!drag) return;
    const onOver = (e: DragEvent) => {
      const el = e.target instanceof Element ? e.target : null;
      if (!el || !el.closest("[data-tagrow]")) setOver(null);
    };
    window.addEventListener("dragover", onOver);
    return () => window.removeEventListener("dragover", onOver);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag != null]);
  useDragEndReset(() => { if (drag) end(); });
  /** THE GRIP is what drags — the row's own press stays the picker's and
   *  the ✕'s (`shared/useDragRow`: data, image, offset). */
  const grip = (d: Drag) => gripProps({
    payload: d.kind === "tag" ? d.name : d.id, rowAttr: "[data-tagrow]", stop: true,
    onStart: () => setDrag(d), onEnd: end,
  });
  const half = (e: React.DragEvent) => dropHalf(e) === "after";
  /** The tag row nearest the pointer inside the group the event is on, and
   *  which side of it the drop would land — measured from the DOM, because
   *  the gaps between rows are the group's own padding and have no row to
   *  ask. Null where the group has no rows at all. */
  const nearestRow = (e: React.DragEvent) => {
    const rows = [...(e.currentTarget as HTMLElement)
      .querySelectorAll<HTMLElement>("[data-tagname]")];
    if (rows.length === 0) return null;
    let best: { name: string; after: boolean; d: number } | null = null;
    for (const el of rows) {
      const r = el.getBoundingClientRect();
      const mid = r.top + r.height / 2;
      const d = Math.abs(e.clientY - mid);
      if (!best || d < best.d) {
        best = { name: el.dataset.tagname || "", after: e.clientY > mid, d };
      }
    }
    return best && best.name ? best : null;
  };
  /** A tag row: takes a TAG in the hand (before/after itself) and lets a
   *  group in the hand through to the group row around it. */
  const tagRowProps = (group: TagSortGroup, index: number, name: string) => ({
    onDragOver: (e: React.DragEvent) => {
      if (drag?.kind !== "tag") return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = "move";
      setOver({ kind: "tag", name, after: half(e) });
    },
    onDrop: (e: React.DragEvent) => {
      if (drag?.kind !== "tag") return;
      e.preventDefault();
      e.stopPropagation();
      const at = index + (half(e) ? 1 : 0);
      const moved = drag.name;
      setCfg((c) => moveTagTo(c, moved, group.id, at));
      end();
    },
  });
  /** A group row: takes a GROUP in the hand (before/after itself) and a
   *  TAG over anything of its own that is not a tag row (the end). */
  const groupRowProps = (group: TagSortGroup, index: number) => ({
    onDragOver: (e: React.DragEvent) => {
      if (!drag) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      if (drag.kind === "group") {
        if (drag.id === group.id) { setOver(null); return; }
        setOver({ kind: "group", id: group.id, after: half(e) });
      } else {
        // THE GAP BETWEEN TWO ROWS BELONGS TO THE NEARER ROW. A tag dragged
        // down a group crosses the padding between its rows, and that space
        // is the GROUP's — so the mark jumped from "after this row" to "at
        // the end of the group" and back on every gap it passed over. The
        // pointer has not left the run of rows, so the answer should not
        // leave it either: only a group with nothing in it (or a drag over
        // its header) is "into".
        const near = nearestRow(e);
        if (near) setOver({ kind: "tag", name: near.name, after: near.after });
        else setOver({ kind: "into", id: group.id });
      }
    },
    onDrop: (e: React.DragEvent, groups: TagSortGroup[]) => {
      if (!drag) return;
      e.preventDefault();
      if (drag.kind === "group") {
        const from = groups.findIndex((g) => g.id === drag.id);
        let to = index + (half(e) ? 1 : 0);
        if (to > from) to -= 1;
        if (from >= 0) setCfg((c) => moveGroup(c, from, to));
      } else {
        const moved = drag.name;
        // The same answer the mark was showing, or the end for a group with
        // nothing in it.
        const near = nearestRow(e);
        const at = near
          ? group.tags.findIndex((x) => x.name === near.name)
            + (near.after ? 1 : 0)
          : group.tags.length;
        setCfg((c) => moveTagTo(c, moved, group.id,
                                at < 0 ? group.tags.length : at));
      }
      end();
    },
  });
  return { drag, over, gripProps: grip, tagRowProps, groupRowProps };
}

type SetDrag = ReturnType<typeof useSetDrag>;

/** The insertion line, drawn as a shadow on the row's edge so nothing
 *  moves while the drag is in hand. */
function edgeShadow(after: boolean): string {
  return after ? "0 3px 0 0 var(--accent)" : "0 -3px 0 0 var(--accent)";
}

const gripStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", cursor: "grab",
  color: "var(--muted-2)", marginLeft: -2,
};

const rowActionStyle: React.CSSProperties = {
  width: 20, height: 20, display: "flex", alignItems: "center",
  justifyContent: "center", borderRadius: "var(--r-1)", cursor: "pointer",
  color: "var(--muted-2)",
};

/** A tag name with its SIGN BOX before it — the sidebar's tag row, in this
 *  dialog's terms: a green box and a bright name for a tag assigned
 *  positively, a red box and a red, struck-through name for one assigned
 *  negatively. Clicked, it becomes a FIELD in place (autocomplete, the text
 *  selected), and the field's answer is the caller's to interpret: Enter
 *  or blur commits, Escape puts the name back. */
/** A TAG NAME BEHIND ITS SIGN, edited in place — green for an assignment,
 *  red and struck through for a negative. Exported because the tag GRID's
 *  rows are the same pair: one spelling of "this tag, and this is what
 *  'doesn't fit' writes for it" rather than two. */
export function SignName({ name, negative, title, onCommit, t }: {
  name: string;
  negative: boolean;
  title: string;
  onCommit: (v: string) => void;
  t: (s: string, vars?: Record<string, string>) => string;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(name);
  const commit = (v: string) => { setEditing(false); onCommit(v); };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6,
                   minWidth: 0 }}>
      <span style={{ flex: "0 0 9px", width: 9, height: 9, borderRadius: 2,
                     background: negative ? "var(--red)" : "var(--green)" }} />
      {editing ? (
        <TagAutocomplete
          value={text}
          onChange={setText}
          onCommit={commit}
          onCancel={() => { setText(name); setEditing(false); }}
          commitOnBlur
          autoFocus
          autoSelect
          fetchSuggestions={fetchTagNameSuggestions}
          existing={[]}
          // AN EMPTY VALUE MEANS SOMETHING HERE — the tag's own negative,
          // the default this field resets to — and the tree opens over an
          // empty field with Enter picking a row, so it leads with a Close
          // row: put the tree away, then Enter submits the empty.
          browseClose
          placeholder={t("tag")}
          minWidth={200}
          inputStyle={{ height: 24, fontSize: "var(--fs-3)", padding: "0 6px",
                        width: 170, fontFamily: "var(--mono)" }}
        />
      ) : (
        <span className="hoverable" title={title}
          onClick={() => { setText(name); setEditing(true); }}
          style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-3)",
                   cursor: "text", padding: "1px 4px", margin: "-1px -4px",
                   borderRadius: 4, overflow: "hidden",
                   textOverflow: "ellipsis", whiteSpace: "nowrap",
                   color: negative ? "var(--red-text)" : "var(--text-bright)",
                   textDecoration: negative ? "line-through" : "none" }}>
          {name}
        </span>
      )}
    </span>
  );
}

/** ONE TAG OF THE SET: its grip, its digit, and its two names — the tag
 *  itself, and (while its group assigns negative tags) WHAT "doesn't fit"
 *  writes: the tag negatively by default (a red box, struck through), or a
 *  COUNTER tag assigned positively (a green box). Either name is edited in
 *  place by clicking it. Renaming the tag carries a default negative with
 *  it and leaves a counter alone; editing the negative side makes it a
 *  counter, which then no longer follows the tag; emptying that field puts
 *  the default back. The ✕ takes the tag out. */
function TagRow({ cfg, group, index, name, negative, setCfg, sd, t, says,
                  groupLabel, groupTrail }: {
  cfg: TagSortConfig;
  group: TagSortGroup;
  index: number;
  name: string;
  negative: string;
  setCfg: React.Dispatch<React.SetStateAction<TagSortConfig>>;
  sd: SetDrag;
  t: (s: string, vars?: Record<string, string>) => string;
  /** What the enabled tag sets say about each name in the set, by lowercase
   *  name — fetched once for the whole editor rather than per row. */
  says: Map<string, TagSetText[]>;
  /** A LIBRARY GROUP ROW's name, refreshed from the tree — null for a tag.
   *  Such a row is not renamed, describes nothing and takes no counter tag:
   *  it writes a membership, which has no negative form. */
  groupLabel: string | null;
  /** Its ancestors, outermost first — drawn after the name, because the row
   *  is out of the tree here and two groups may share a name. */
  groupTrail: string[];
}) {
  const over = sd.over?.kind === "tag" && sd.over.name === name
    ? sd.over : null;
  const inHand = sd.drag?.kind === "tag" && sd.drag.name === name;
  const counter = negative.trim();
  return (
    <div data-tagrow="" data-tagname={name} {...sd.tagRowProps(group, index, name)}
      style={{ display: "flex", alignItems: "center", gap: 8,
               padding: "5px 8px", borderRadius: "var(--r-4)",
               background: "var(--panel-3)",
               border: "1px solid var(--border)",
               opacity: inHand ? 0.4 : 1,
               boxShadow: over ? edgeShadow(over.after) : undefined }}>
      <span {...sd.gripProps({ kind: "tag", name })}
        title={t("Drag to reorder, or into another question")}
        style={gripStyle}>
        <Icon name="drag_indicator" size={16} />
      </span>
      <KeyPicker value={keyOf(cfg, name)}
        onPick={(d) => setCfg((c) => ({
          ...c, keys: { ...c.keys, [name]: d } }))} t={t} />
      <span style={{ flex: 1, minWidth: 0, display: "flex",
                     alignItems: "center", gap: 8 }}>
        {groupLabel != null ? (
          <span title={t("Answering this puts the picture in the group")}
            style={{ display: "flex", alignItems: "center", gap: 6,
                     minWidth: 0, fontSize: "var(--fs-3)" }}>
            <Icon name="folder" size={14} color="var(--accent)" />
            <span style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden",
                           textOverflow: "ellipsis",
                           whiteSpace: "nowrap" }}>{groupLabel}</span>
            {groupTrail.length > 0 && (
              <span style={{ flex: "0 20 auto", minWidth: 0,
                             overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap", fontSize: "var(--fs-2)",
                             color: "var(--muted-2)" }}>
                {groupTrail.join(" › ")}
              </span>
            )}
          </span>
        ) : (<>
        <SignName name={name} negative={false}
          title={t("Rename the tag")}
          onCommit={(v) => {
            const clean = v.trim(); // the field committed its own form
            if (clean) setCfg((c) => renameTag(c, name, clean));
          }} t={t} />
        {/* WHAT THE SETS SAY ABOUT IT, here as everywhere else. Setting up
            a batch is exactly when it matters whether `absurdres` means
            what you think — the name is being chosen, and the answer is a
            popover away in every other tag field in the app. Only where a
            set actually knows the name; `?` never appears on nothing. */}
        {(says.get(name.toLowerCase()) ?? []).length > 0 && (
          <DescriptionMark descriptions={says.get(name.toLowerCase())}
            name={name} size={13} raised />
        )}
        {group.negatives && (<>
          <span style={{ color: "var(--muted-2)", fontSize: "var(--fs-3)" }}>/</span>
          <SignName name={counter || name} negative={!counter}
            title={t("What “doesn't fit” writes — a tag typed here is assigned positively in place of the negative; empty it for the negative again")}
            onCommit={(v) => {
              const clean = v.trim(); // the field committed its own form
              setCfg((c) => withCounter(c, name, clean));
            }} t={t} />
        </>)}
        </>)}
      </span>
      <span className="row-action danger"
        onClick={() => setCfg((c) => withoutTag(c, name))}
        title={t("Remove")} style={rowActionStyle}>
        <Icon name="close" size={14} />
      </span>
    </div>
  );
}

/** ONE GROUP OF THE SET: its two switches — mutually exclusive, assign
 *  negative tags — and its tags as rows of their own with their own adder. The ✕ is offered only past one group: the set
 *  always holds one, and a ✕ that replaced the last group with an empty
 *  one would be a button that clears. */
function GroupRow({ cfg, group, index, setCfg, sd, t, says, groupOptions }: {
  cfg: TagSortConfig;
  group: TagSortGroup;
  index: number;
  setCfg: React.Dispatch<React.SetStateAction<TagSortConfig>>;
  sd: SetDrag;
  t: (s: string, vars?: Record<string, string>) => string;
  says: Map<string, TagSetText[]>;
  /** The library's assignable groups, for the adder's own section — with
   *  the tree's depth (the list indents by it) and each one's ancestors. */
  groupOptions: readonly { id: number; name: string; depth: number;
                           trail: string[] }[];
}) {
  const [adding, setAdding] = useState("");
  const full = tagNames(cfg).length >= MAX_TAGS;
  const rowProps = sd.groupRowProps(group, index);
  const over = sd.over;
  const edge = over?.kind === "group" && over.id === group.id ? over : null;
  const into = over?.kind === "into" && over.id === group.id;
  const inHand = sd.drag?.kind === "group" && sd.drag.id === group.id;
  const on = group.enabled !== false;
  const toggle = (label: string, key: "exclusive" | "negatives" | "advance",
                  title: string) => (
    <label title={title}
      style={{ display: "flex", alignItems: "center", gap: 5,
               fontSize: "var(--fs-2)", color: "var(--text-2)", cursor: "pointer",
               whiteSpace: "nowrap",
               // A DISABLED GROUP'S OWN SWITCHES GO QUIET, since none of
               // them is about anything until it is back in the session.
               opacity: on ? 1 : 0.45,
               pointerEvents: on ? undefined : "none" }}>
      <input type="checkbox" checked={key === "advance" ? !!group.advance
                                                        : group[key]}
        onChange={() => setCfg((c) => updateGroup(c, group.id,
          key === "advance" ? { advance: !group.advance }
                            : { [key]: !group[key] }))}
        style={{ margin: 0 }} />
      {label}
    </label>
  );
  return (
    <div data-tagrow="" onDragOver={rowProps.onDragOver}
      onDrop={(e) => rowProps.onDrop(e, cfg.groups)}
      style={{ display: "flex", flexDirection: "column", gap: 6,
               padding: "6px 8px 8px", borderRadius: "var(--r-6)",
               background: "var(--panel-2)",
               border: `1px solid ${into ? "var(--accent)"
                                         : "var(--border-strong)"}`,
               opacity: inHand ? 0.4 : 1,
               boxShadow: edge ? edgeShadow(edge.after) : undefined }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span {...sd.gripProps({ kind: "group", id: group.id })}
          title={t("Drag to reorder")} style={gripStyle}>
          <Icon name="drag_indicator" size={16} />
        </span>
        {/* IN OR OUT OF THE SESSION. Not the same as removing it: a set
            kept for another pass stays written down, with its digits,
            ready to come back — and the rows below stay legible so it can
            be read while it is set aside. */}
        {/* THE CHECKBOX SAYS WHAT IT DOES. A folder icon and the word
            "Group" said what the card already is — the row is visibly a
            group — while the switch beside them said nothing at all; the
            label belongs on the control. */}
        <label title={on ? t("Leave this question out of the session")
                         : t("Put this question back in the session")}
          style={{ display: "flex", alignItems: "center", gap: 5,
                   fontSize: "var(--fs-2)", cursor: "pointer", whiteSpace: "nowrap",
                   marginRight: 6, fontWeight: 600,
                   color: on ? "var(--text-2)" : "var(--muted-3)" }}>
          <input type="checkbox" checked={on}
            onChange={() => setCfg((c) => updateGroup(c, group.id,
              { enabled: on ? false : undefined }))}
            style={{ margin: 0, cursor: "pointer" }} />
          {t("Enabled")}
        </label>
        {toggle(t("Mutually exclusive"), "exclusive",
                t("At most one of these on a picture — lighting another puts the lit one out."))}
        {toggle(t("Assign negative tags"), "negatives",
                t("The tags of this question you don't pick are marked as not applying."))}
        {toggle(t("Next picture on answer"), "advance",
                t("Answering one of these tags moves on, instead of waiting for the next key."))}
        <span style={{ flex: 1 }} />
        {cfg.groups.length > 1 && (
          <span className="row-action danger"
            onClick={() => setCfg((c) => withoutGroup(c, group.id))}
            title={t("Remove the question and everything in it")} style={rowActionStyle}>
            <Icon name="close" size={14} />
          </span>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6,
                    paddingLeft: 22,
                    // Set aside, not deleted: the rows stay readable so the
                    // group can be recognised, and stop taking the pointer
                    // so nothing in it can be edited by accident.
                    opacity: on ? 1 : 0.45,
                    pointerEvents: on ? undefined : "none" }}>
        {group.tags.map((tag, i) => (
          <TagRow key={tag.name} cfg={cfg} group={group} index={i}
            name={tag.name} negative={tag.negative} setCfg={setCfg}
            sd={sd} t={t} says={says}
            groupLabel={tag.group != null
              ? (groupOptions.find((g) => g.id === tag.group)?.name
                 ?? tag.label ?? `#${tag.group}`)
              : null}
            groupTrail={tag.group != null
              ? (groupOptions.find((g) => g.id === tag.group)?.trail ?? [])
              : []} />
        ))}
        {!full && (
          <TagAutocomplete
            value={adding}
            onChange={setAdding}
            onCommit={(name) => {
              const clean = name.trim();
              if (clean) setCfg((c) => withTag(c, clean, group.id));
              setAdding("");
            }}
            // NO "all" ON A CATEGORY ROW (owner 2026-09). A tag set's
            // category seeds the question WHOLE, which for a question that
            // holds nine rows and a keyboard digit each is a hundred tags
            // into a cap of nine — and the button sat on every category row
            // of the tree, one keystroke from the row you meant to open.
            // Passing no `onPickCategory` is what takes it (and its ⇧Enter)
            // away; the field is a tag at a time here.
            // THE LIBRARY'S GROUPS, in the empty field's own section. One
            // answered like a tag writes a MEMBERSHIP; already-picked ones
            // are left out, as the tag rows are.
            groups={groupOptions.filter(
              (g) => !tagNames(cfg).includes(groupRowName(g.id)))}
            onPickGroup={(id, name) => {
              setCfg((c) => withGroupRow(c, id, name, group.id));
              setAdding("");
            }}
            fetchSuggestions={fetchTagNameSuggestions}
            existing={plainTags(cfg)}
            placeholder={group.tags.length === 0
              ? t("Which tag do you want to decide?")
              : t("Add another tag or group…")}
            minWidth={220}
          />
        )}
      </div>
    </div>
  );
}

/**
 * THE SESSION'S SET, in the one place it is edited.
 *
 * The chooser sets it up and the running session edits it through the
 * Settings dialog — the same rows, because they are the same set: what the
 * digits mean, and which of them belong together. It is GROUPS, never
 * fewer than one, each holding its tags (`GroupRow`); every row carries its
 * digit and its counter tag (`TagRow`); the section header carries Add
 * group and Clear.
 *
 * The ORDER is editable — by DRAGGING a row's grip: a group among the
 * groups, a tag within its group or into another — and it is only the
 * order: each tag's digit is its own (`TagSortConfig.keys`, chosen from the
 * number box and materialized on read), so moving a row moves nothing
 * about the keyboard.
 */
function SetEditor({ cfg, setCfg, t, presets }: {
  cfg: TagSortConfig;
  setCfg: React.Dispatch<React.SetStateAction<TagSortConfig>>;
  t: (s: string, vars?: Record<string, string>) => string;
  /** The saved-setup menu, drawn HERE rather than in the footer: it loads
   *  and saves this section and nothing else, and a control in the footer
   *  beside Start read as being about the session rather than about the
   *  set it sits over. */
  presets?: React.ReactNode;
}) {
  const sd = useSetDrag(setCfg);
  // WHAT THE SETS SAY, once for the whole editor. Setting up a batch is
  // exactly when it matters whether a name means what you think, and the
  // answer is a popover away in every other tag field in the app; asking
  // per ROW would be one request per tag on every keystroke.
  const names = useMemo(
    () => cfg.groups.flatMap((g) => g.tags.map((x) => x.name)), [cfg.groups]);
  const { data: described } = useQuery({
    queryKey: ["tags", "describe", names.join("\u0000")],
    queryFn: () => api.describeNames(names),
    enabled: names.length > 0,
  });
  const says = useMemo(() => {
    const m = new Map<string, TagSetText[]>();
    for (const [n, said] of Object.entries(described ?? {})) {
      if (said.descriptions.length) m.set(n.toLowerCase(), said.descriptions);
    }
    return m;
  }, [described]);
  // THE LIBRARY'S GROUPS, for the adders' own section — one fetch for the
  // whole editor, shared by every question's field. Smart groups are left
  // out by `flattenGroupTree`: their membership is a rule, not something an
  // answer can write.
  const { data: groupTree } = useQuery({ queryKey: ["groups"],
                                         queryFn: api.groups });
  const groupOptions = useMemo(
    () => flattenGroupTree(groupTree ?? []).map(
      (g) => ({ id: g.id, name: g.name, depth: g.depth,
                trail: g.trail ?? [] })), [groupTree]);
  const anything = cfg.groups.some((g) => g.tags.length > 0)
    || cfg.groups.length > 1;
  const headBtn: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 4, height: 22,
    padding: "0 8px", borderRadius: "var(--r-2)",
    border: "1px solid var(--border-strong)", background: "transparent",
    color: "var(--text-2)", fontSize: "var(--fs-2)", cursor: "pointer",
    fontFamily: "inherit", whiteSpace: "nowrap",
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {/* The section label, with ADD GROUP and CLEAR at its right — the
          one way to grow the set by a group, and the way to start a setup
          over without taking nine rows out one by one. */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <div style={{ ...sectionLabel, marginBottom: 0 }}>{t("Tags")}</div>
        <span style={{ flex: 1 }} />
        <button type="button"
          onClick={() => setCfg((c) => withGroup(c))}
          title={t("One question of the session: the tags and groups it offers, with its own mutually-exclusive and negative-tags settings")}
          style={headBtn}>
          <Icon name="create_new_folder" size={13} />{t("Add question")}
        </button>
        {anything && (
          <button type="button"
            onClick={() => setCfg((c) => clearTags(c))}
            title={t("Remove every question from the setup")}
            style={headBtn}>
            <Icon name="delete_sweep" size={13} />{t("Clear")}
          </button>
        )}
        {presets}
      </div>
      {cfg.groups.map((g, i) => (
        <GroupRow key={g.id} cfg={cfg} group={g} index={i} setCfg={setCfg}
          sd={sd} t={t} says={says} groupOptions={groupOptions} />
      ))}
    </div>
  );
}

/** THE NUMBER BOX IS A MENU: click it and pick the digit this tag answers
 *  to. Any digit, shared or not — two tags on one key are filed or toggled
 *  together by it, which is what somebody putting them there means. */
function KeyPicker({ value, onPick, t }: {
  value: number;
  onPick: (digit: number) => void;
  t: (s: string, vars?: Record<string, string>) => string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const rect = useAnchorRect(ref, open);
  useMenuDismiss(open, () => setOpen(false), { within: [ref] });
  return (
    <>
      <span ref={ref} className="hoverable"
        title={t("Which key this tag answers to")}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        style={{ display: "inline-flex", cursor: "pointer", borderRadius: "var(--r-1)" }}>
        <Cap>{String(value)}</Cap>
      </span>
      {open && (
        <AnchoredDropdown rect={rect} minWidth={56}>
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((d) => (
            <div key={d} className="hoverable"
              onClick={(e) => { e.stopPropagation(); onPick(d); setOpen(false); }}
              style={{ display: "flex", alignItems: "center", gap: 8,
                       padding: "5px 10px", borderRadius: "var(--r-3)", cursor: "pointer",
                       fontFamily: "var(--mono)", fontSize: "var(--fs-3)",
                       color: d === value ? "var(--accent)" : "var(--text)" }}>
              {String(d)}
            </div>
          ))}
        </AnchoredDropdown>
      )}
    </>
  );
}

/** Save the dialog's TAG SETUP under a name, load a saved one back — the
 *  train job editor's presets in this dialog's terms (same rows, same
 *  rename-in-place, same ✕). A preset is the set alone — the groups, their
 *  switches, their tags with counter tags and digits — never the kind, the
 *  ordering or the sequence rule, which are the session's; a fresh one is
 *  named by its tags, and loading one replaces the set. */
function TagSortPresets({ cfg, onLoad, t }: {
  cfg: TagSortConfig;
  onLoad: (preset: TagSortPreset) => void;
  t: (s: string, vars?: Record<string, string>) => string;
}) {
  const [presets, setPresets] = useState<TagSortPreset[]>(
    () => parseTagSortPresets(storage.get(TAGSORT_PRESETS_KEY)));
  const [menu, setMenu] = useState(false);
  const menuAnchor = useRef<HTMLButtonElement>(null);
  const menuRect = useAnchorRect(menuAnchor, menu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(menu, () => setMenu(false), { within: [menuAnchor] });
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const renameRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (renameId) renameRef.current?.select(); }, [renameId]);

  const commit = (next: TagSortPreset[]) => {
    setPresets(next);
    try {
      storage.set(TAGSORT_PRESETS_KEY, serializeTagSortPresets(next));
    } catch { /* ignore */ }
  };
  const commitRename = () => {
    if (!renameId) return;
    const v = renameVal.trim();
    if (v) commit(presets.map(
      (p) => (p.id === renameId ? { ...p, name: v } : p)));
    setRenameId(null);
  };
  const renameKeys = useInlineEdit({ commit: commitRename,
                                     cancel: () => setRenameId(null) });
  const canSave = tagNames(cfg).length > 0;
  const save = () => {
    if (!canSave) return;
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const name = rowLabels(cfg).join(" · ");
    commit([presetOf(cfg, id, name), ...presets]);
    setRenameId(id);
    setRenameVal(name);
  };
  const openMenu = () => setMenu((v) => !v);

  return (
    <div>
      {/* THE SECTION HEADER'S OWN BUTTON SHAPE — it sits in the row with Add
          question and Clear, and it kept the FOOTER's dimensions from where
          it used to live, which made it half again as tall as its
          neighbours. */}
      <button ref={menuAnchor} onClick={openMenu}
        title={t("Save these tags as a preset, or load one")}
        style={{ display: "flex", alignItems: "center", gap: 4, height: 22,
                 padding: "0 8px", borderRadius: "var(--r-2)",
                 border: "1px solid var(--border-strong)",
                 background: "transparent", color: "var(--text-2)",
                 fontSize: "var(--fs-2)", cursor: "pointer", whiteSpace: "nowrap",
                 fontFamily: "inherit" }}>
        <Icon name="bookmarks" size={13} />{t("Tag presets…")}
        <Icon name="expand_more" size={13} style={{ opacity: 0.7 }} />
      </button>
      {menu && (
          <AnchoredDropdown rect={menuRect} minWidth={280} focusable>
            <div className={canSave ? "hoverable" : undefined}
              onClick={canSave ? save : undefined}
              style={{ display: "flex", alignItems: "center", gap: 8,
                       padding: "6px 9px", borderRadius: "var(--r-3)", fontSize: "var(--fs-3)",
                       color: "var(--text-2)",
                       opacity: canSave ? 1 : 0.45,
                       cursor: canSave ? "pointer" : "default" }}>
              <Icon name="bookmark_add" size={14} color="var(--muted)" />
              <span style={{ flex: 1 }}>{t("Save these tags")}</span>
            </div>
            {presets.length > 0 && (
              <div style={{ height: 1, background: "var(--menu-border)",
                            margin: "4px 2px" }} />
            )}
            {presets.map((p) => (
              <div key={p.id}
                style={{ display: "flex", alignItems: "center", gap: 2,
                         minHeight: 34, borderRadius: "var(--r-3)" }}>
                {renameId === p.id ? (
                  <>
                    <input ref={renameRef} value={renameVal}
                      onChange={(e) => setRenameVal(e.target.value)}
                      onBlur={renameKeys.onBlur}
                      onKeyDown={renameKeys.onKeyDown}
                      placeholder={t("Name this preset")}
                      spellCheck={false}
                      style={{ flex: 1, minWidth: 0, margin: 2,
                               background: "var(--bg)",
                               border: "1px solid var(--accent)",
                               borderRadius: "var(--r-3)", padding: "5px 7px",
                               color: "var(--text)", fontSize: "var(--fs-3)",
                               fontWeight: 600, fontFamily: "inherit",
                               outline: "none" }} />
                    <IconButton icon="check" size={24} glyph={15} tone="accent"
                      onMouseDown={(e) => { e.preventDefault(); commitRename(); }}
                      title={t("Done")} style={{ flex: "none" }} />
                  </>
                ) : (
                  <>
                    <button className="hoverable"
                      onClick={() => { setMenu(false); onLoad(p); }}
                      title={t("Load this preset — it replaces the tags")}
                      style={{ flex: 1, minWidth: 0, display: "flex",
                               alignItems: "center", gap: 7,
                               textAlign: "left", background: "transparent",
                               border: "none", borderRadius: "var(--r-3)",
                               padding: "5px 7px", cursor: "pointer",
                               fontFamily: "inherit" }}>
                      <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                                     fontWeight: 600, color: "var(--text-2)",
                                     overflow: "hidden",
                                     textOverflow: "ellipsis",
                                     whiteSpace: "nowrap" }}>{p.name}</span>
                    </button>
                    <IconButton icon="edit" size={24} glyph={13}
                      onClick={() => { setRenameId(p.id); setRenameVal(p.name); }}
                      title={t("Rename")} style={{ flex: "none" }} />
                    <IconButton icon="close" size={24} glyph={14}
                      onClick={() => commit(presets.filter((x) => x.id !== p.id))}
                      title={t("Remove this preset")} style={{ flex: "none" }} />
                  </>
                )}
              </div>
            ))}
          </AnchoredDropdown>
        
)}
    </div>
  );
}

// ---- the chooser -------------------------------------------------------------

function Chooser({ cfg, setCfg, probe, embedReady,
                   pickerModels, embedderChoice, embedders, embedNames,
                   embedJob, scopeRef, scopeEmpty, onOpenModels, presets,
                   t, tn }: {
  cfg: TagSortConfig;
  setCfg: React.Dispatch<React.SetStateAction<TagSortConfig>>;
  /** The chooser's coverage probe — the one call that always counts,
   *  so its `total` is a number rather than the nullable one a feed
   *  comes back with (see `want_pool`). */
  probe: (TagSortNextOut & { total: number }) | null;
  embedReady: boolean;
  /** The picker's rows: every embed model, plus the fused row past one. */
  pickerModels: { id: string; name: string; family?: string }[];
  /** The RESOLVED choice — `FUSED`, or one model id. */
  embedderChoice: string;
  /** The saved setups' menu, drawn in the Tags section's header. */
  presets?: React.ReactNode;
  /** The spaces the choice names, each with a coverage line of its own. */
  embedders: string[];
  embedNames: Map<string, string>;
  /** A queued/running index job — its progress renders in place of THAT
   *  space's button (pressing again would queue an identical run). */
  embedJob: { progress: number; status: string; model?: string } | null;
  scopeRef: React.MutableRefObject<Record<string, unknown> | null>;
  /** The probe answered and the scope holds nothing to decide — Start is
   *  disabled, and this line is what says why. */
  scopeEmpty: boolean;
  /** The way to the Settings → Models page, embedder card highlighted. */
  onOpenModels: () => void;
  t: (s: string, vars?: Record<string, string>) => string;
  tn: (forms: { one: string; other: string }, n: number,
       vars?: Record<string, string>) => string;
}) {
  const qc = useQueryClient();
  // Bridges the click and the first job poll, so the button cannot be
  // pressed twice while the job has not shown up yet.
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
        // The same scope the coverage figure counted — indexing a kind the
        // session will not ask about is work for nothing.
        ...(scopeRef.current ?? {}), kind: cfg.kind,
        ...(cfg.skipSequenced ? { hide_sequenced: true } : {}),
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
      {/* One list decides the mode: one tag = yes/no, several = digits.
          WHY START IS DIM is in the FOOTER, beside the button it is about —
          here it was a line that appeared and disappeared inside the options
          column, so switching "Ask about" between images and videos moved
          every row under it while the pointer was on one. */}
      <SetEditor cfg={cfg} setCfg={setCfg} t={t} presets={presets} />

      {/* The options wear the import overlay's shape — section label, card,
          switch rows — so the two dialogs read as the same app. */}
      <div>
        <div style={sectionLabel}>{t("Options")}</div>
        <div style={card}>
          {/* WHICH KIND, and never both. A tag session is a rhythm and the
              two do not share one: a picture is answered at a glance and a
              film has to be watched, so every video was a stall in a run of
              stills. It is also what the classifier can help with — only
              pictures carry a vector, so a mixed pool reported a coverage
              figure it could never fill, counting films no embedder here
              will ever index. Two buttons rather than a switch: neither of
              them is "off". */}
          <div style={{ padding: "12px 14px",
                        borderBottom: "1px solid var(--border-soft)",
                        display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "var(--fs-4)" }}>{t("Ask about")}</div>
              <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)",
                            marginTop: 3, lineHeight: 1.45 }}>
                {t("One kind per session — a picture is answered at a glance and a film has to be watched.")}
              </div>
            </div>
            <div style={{ display: "flex", flex: "0 0 auto",
                          border: "1px solid var(--border-strong)",
                          borderRadius: "var(--r-4)", overflow: "hidden" }}>
              {([["image", t("Images")], ["video", t("Videos")]] as const)
                .map(([k, label]) => (
                <button key={k} type="button"
                  onClick={() => setCfg((c) => ({ ...c, kind: k }))}
                  style={{ height: 28, padding: "0 12px", border: "none",
                           cursor: "pointer", fontSize: "var(--fs-3)", fontFamily: "inherit",
                           background: cfg.kind === k
                             ? "var(--accent-dim)" : "var(--panel-2)",
                           color: cfg.kind === k
                             ? "var(--selected-text)" : "var(--text-2)" }}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <OptionRow
            title={t("Skip pictures in sequences")}
            desc={t("Pages of a book and frames of a GIF are left out.")}
            checked={cfg.skipSequenced}
            onToggle={() => setCfg((c) => ({
              ...c, skipSequenced: !c.skipSequenced }))}
            last
          />
        </div>
      </div>

      <div>
        <div style={sectionLabel}>{t("Ordering")}</div>
        <div style={card}>
          {/* Disabled (never hidden) while it cannot work: the switch's
              absence would take its explanation with it, and the reason it
              is off is exactly what the row has to say — with the way to
              fix it one click away. Two disabled states, two reasons: no
              embedder (→ Settings → Models), or nothing indexed yet
              (→ Index remaining, right here). */}
          {(() => {
            const nothingIndexed = probe != null && probe.embedded === 0;
            const smartUsable = embedReady && !nothingIndexed;
            return (
          <OptionRow
            title={t("Smart ordering")}
            desc={!embedReady
              ? t("Shows likely matches first, learning from your answers as the session goes. The selected model is not set up yet.")
              : nothingIndexed
                ? t("Shows likely matches first, learning from your answers as the session goes. Index the pictures once to enable it.")
                : t("Shows likely matches first, learning from your answers as the session goes. Unindexed pictures still appear — they simply come last.")}
            checked={smartUsable && cfg.smart}
            disabled={!smartUsable}
            onToggle={() => setCfg((c) => ({ ...c, smart: !c.smart }))}
            last
          >
            {/* WHICH space orders the queue — offered whenever there is a
                choice, ready or not: picking is also how you see the other
                model's state, and each indexes independently (the import
                overlay's face-detector select, in this row's terms). */}
            {/* Shown for ONE model too: the menu is then a formality,
                but the subtitle is what decides the choice and hiding it
                left this dialog saying nothing about what it indexes with. */}
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
                         fontSize: "var(--fs-2)", pointerEvents: "auto" }}>
                <Icon name="download" size={14} />
                {t("Set up in Settings → Models")}
              </button>
            ) : probe != null ? (
              // Shown whether or not the switch is on — the indexing
              // controls are how a disabled switch BECOMES usable. ONE
              // LINE PER SPACE (the grid's shape): under fusion each is
              // indexed on its own and each wants its own button.
              <div onClick={(e) => e.stopPropagation()}
                style={{ display: "flex", flexDirection: "column", gap: 4,
                         marginTop: 8, fontSize: "var(--fs-2)", cursor: "default",
                         color: "var(--muted-2)", pointerEvents: "auto" }}>
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
              </div>
            ) : null}
            {/* THE COLD START, said before it is paid for: a tag no picture
                carries yet has nothing to fit until the first "yes", and
                until then the queue is a random draw — on a rare tag, a
                long run of "no". A SELECTION is the way round it (it leads
                the queue and seeds the fit), so a session started over one
                needs no hint. */}
            {(() => {
              if (probe == null || !smartUsable || !cfg.smart) return null;
              const sel = (scopeRef.current?.items as number[] | undefined)
                ?.length ?? 0;
              const bare = plainTags(cfg)
                .filter((n) => (probe.labeled[n]?.[0] ?? 0) === 0);
              if (sel > 0 || bare.length === 0) return null;
              return (
                <div style={{ marginTop: 6, fontSize: "var(--fs-2)",
                              color: "var(--yellow-text)" }}>
                  {t("No picture carries {tags} yet — select a few examples in the library first; the session asks about them first and learns from them.",
                     { tags: bare.map((n) => `“${n}”`).join(", ") })}
                </div>
              );
            })()}
          </OptionRow>
            );
          })()}
        </div>
      </div>
    </div>
  );
}

// ---- the summary -------------------------------------------------------------

function Summary({ running, judged, skippedCount, s, onKeepGoing, onReopen,
                   t, tn }: {
  running: TagSortConfig;
  judged: readonly JudgedEntry<RankingItemRef>[];
  skippedCount: number;
  s: { decided: number; perTag: number[]; none: number };
  onKeepGoing?: () => void;
  /** Clicking a thumbnail un-writes that item's answer and re-presents it —
   *  the way to correct one without ↑-ing through everything since. */
  onReopen: (itemId: number) => void;
  t: (str: string, vars?: Record<string, string>) => string;
  tn: (forms: { one: string; other: string }, n: number,
       vars?: Record<string, string>) => string;
}) {
  const groups: { label: string; refs: RankingItemRef[] }[] = [];
  for (const tag of tagNames(running)) {
    const refs = judged.filter((j) => j.chosen.includes(tag))
      .map((j) => j.ref);
    if (refs.length) groups.push({ label: rowLabel(running, tag), refs });
  }
  const noneRefs = judged.filter((j) => j.chosen.length === 0)
    .map((j) => j.ref);
  if (noneRefs.length) {
    groups.push({
      label: tagNames(running).length === 1
        ? t("doesn't fit") : t("none of these"),
      refs: noneRefs,
    });
  }
  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: "auto",
                  margin: "0 auto", width: "min(760px, 100%)",
                  display: "flex", flexDirection: "column", gap: 14 }}>
      {groups.length === 0 && (
        <div style={{ textAlign: "center", fontSize: "var(--fs-4)",
                      color: "var(--on-scrim-2)" }}>
          {t("Nothing decided yet.")}
        </div>
      )}
      {groups.map((g) => (
        <div key={g.label} style={{ display: "flex", gap: 12 }}>
          <div style={{ flex: "0 0 140px", fontFamily: "var(--mono)",
                        fontSize: "var(--fs-3)", textAlign: "right",
                        color: "var(--on-scrim)" }}>
            {g.label}
            <div style={{ fontSize: "var(--fs-2)", color: "var(--on-scrim-3)" }}>
              {tn({ one: "1 picture", other: "{n} pictures" }, g.refs.length)}
            </div>
          </div>
          <div style={{ flex: 1, display: "flex", flexWrap: "wrap", gap: 6 }}>
            {g.refs.map((r) => (
              <img key={r.item_id}
                src={r.file_id != null
                  ? api.thumbUrl(r.file_id, 0, r.thumb_token) : undefined}
                title={t("{name} — click to answer it again",
                         { name: r.name || r.uid })}
                onClick={() => onReopen(r.item_id)}
                style={{ width: 84, height: 64, objectFit: "cover",
                         borderRadius: "var(--r-2)", cursor: "pointer",
                         border: "1px solid var(--overlay-hairline)" }} />
            ))}
          </div>
        </div>
      ))}
      {skippedCount > 0 && (
        <div style={{ textAlign: "center", fontSize: "var(--fs-3)",
                      color: "var(--on-scrim-3)" }}>
          {tn({ one: "1 skipped — nothing was written for it",
                other: "{n} skipped — nothing was written for them" },
              skippedCount)}
        </div>
      )}
      {onKeepGoing && (
        <div style={{ display: "flex", justifyContent: "center" }}>
          <Button variant="scrim" size="sm" onClick={onKeepGoing}>
            {t("Keep tagging")}
          </Button>
        </div>
      )}
    </div>
  );
}
