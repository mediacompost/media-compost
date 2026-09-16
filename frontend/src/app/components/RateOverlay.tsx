/** Rate pairs from the keyboard, and from almost nothing else.
 *
 * The grid's quick-actions **"Rate batch…"** row (and the context menu's
 * per-ranking rows) opens two pictures over a dimmed library — a member of
 * the keyboard-overlay family beside T, Q and the Tag batch overlay, built
 * for the same rhythm: a judgment should take about a second, so ←/→ decide,
 * Space sets a pair aside (can't tell — it is not offered again soon), ↑ (or
 * U) takes the last judgment back, and Escape ends the session. It had an R
 * binding once; two session overlays each claiming a letter was a keyboard
 * nobody could learn, so both open from the menu now. There is no equal button
 * (near-equal forced picks still inform — they land ~50/50, which the fit
 * reads as "close" — where an equal key becomes the escape hatch that gets
 * overused) and no confirmation anywhere: every judgment advances instantly.
 *
 * The SESSION'S POOL is what T and Q already mean by scope: a selection if
 * one is held, else the view the grid is showing, sent as the same search
 * body the grid pages with — intersected server-side with the ranking's own
 * stored scope. Closing ends the session and the scores refresh by
 * themselves; the transient note says so, and there is no update button and
 * no stale state anywhere.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { patchRow, useItemPatches } from "./shared/useItemPatches";
import { storage } from "../../shared/storage";
import { rowBackground } from "../../shared/Row";
import { Button } from "../../shared/Button";
import { useSessionUndo } from "./shared/useSessionUndo";
import { ActionToast } from "./shared/ActionToast";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RankingItemRef, RankingPairOut, RankingRow } from "../api";
import { Icon } from "../../shared/Icon";
import { LAYER } from "../../shared/layers";
import { loadFlag, saveFlag, useUI } from "../store";
import { useErrText, useT, useTn } from "../i18n";
import { useViewScope } from "../useItems";
import { bumpLibrary } from "../invalidation";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { Cap, JudgeCard } from "./shared/JudgeCard";
import { useSessionKeys } from "./shared/useSessionKeys";
import { SessionTrouble } from "./shared/SessionStates";
import { Overlay } from "../../shared/Overlay";
import { card, OptionRow, sectionLabel } from "./ImportOverlay";
import { RankingEditOverlay } from "./RankingEditOverlay";
import { ConfirmModal } from "../../shared/ConfirmModal";

/** The last rankings rated, with the pools picked for each — what the
 *  chooser opens on. Written as `"3:1,2;5:7"` (`rankingId[:poolIds]`,
 *  `;`-joined); an older value is a plain CSV of ranking ids and reads
 *  unchanged (`parseLast`). */
const LAST_KEY = "mc.rateRanking";

/** WHICH LEAGUES of each ranking a session writes into, by ranking id — and
 *  a ranking absent from the map has not been chosen for, which is its
 *  DEFAULT pool alone (`poolsFor`). The session materializes the list
 *  before it starts. */
type PoolPick = Record<number, number[]>;

/** The pools last chosen for a ranking, WHATEVER was rated since — same
 *  spelling as `LAST_KEY`'s pool half (`3:1,2;5:7`).
 *
 *  Its own key because `LAST_KEY` remembers the last SESSION: it holds the
 *  rankings that were rated and their pools, so rating a different axis
 *  drops what the first one was set to. This is the answer to "which
 *  pools does this ranking mean", which does not stop being true because
 *  something else was rated in between. */
const POOLS_KEY = "mc.ratePools";

function loadPoolMemory(rows: RankingRow[]): PoolPick {
  try {
    return parseLast(storage.get(POOLS_KEY) || "", rows).pools;
  } catch { return {}; }
}

/** Remember what was chosen, MERGED over what is already remembered — a
 *  session picks one or two axes and must not forget the rest. */
function savePoolMemory(rows: RankingRow[], picked: PoolPick): void {
  const all = { ...loadPoolMemory(rows), ...picked };
  const ids = Object.keys(all).map(Number).filter((id) => all[id]?.length);
  try {
    storage.set(POOLS_KEY, formatLast(ids, all));
  } catch { /* ignore */ }
}

/** Read `LAST_KEY` back against the rankings that exist. Pool ids are
 *  filtered to the ranking's own; none left means "all", the default. */
function parseLast(raw: string, rows: RankingRow[]):
    { picked: number[]; pools: PoolPick } {
  const picked: number[] = [];
  const pools: PoolPick = {};
  if (!raw) return { picked, pools };
  for (const part of raw.split(";")) {
    const [idText, setText] = part.split(":");
    const id = Number(idText);
    const row = rows.find((r) => r.id === id);
    if (!row || picked.includes(id)) continue;
    picked.push(id);
    if (setText) {
      const ids = setText.split(",").map(Number)
        .filter((n) => (row.pools ?? []).some((l) => l.id === n));
      if (ids.length) pools[id] = ids;
    }
  }
  return { picked, pools };
}

function formatLast(picked: number[], pools: PoolPick): string {
  return picked.map((id) => (pools[id]?.length
    ? `${id}:${pools[id].join(",")}` : String(id))).join(";");
}

/** The pools a session on ranking `r` writes into: the chooser's pick,
 *  else its FIRST — which is its default pool, the one a ranking is born
 *  with and the one the server writes into when a request names none.
 *
 *  It used to fall back to ALL of them, which is the wrong default in the
 *  direction that costs something: a judgement is written to every pool
 *  picked, so an untouched multi-pool ranking silently rated into
 *  populations somebody had deliberately kept apart. Picking more is one
 *  click; unpicking what you did not ask for is one click you have to know
 *  to make.
 *
 *  EMPTY for a single-pool ranking — the server reads that as its default
 *  pool, which is what every session before pools existed meant. */
function poolsFor(r: RankingRow, picked: PoolPick): number[] {
  if ((r.pools?.length ?? 0) <= 1) return [];
  return picked[r.id] ?? [r.pools[0].id];
}
/** Whether the chooser leaves sequence members out, across sessions. */
const SKIP_SEQ_KEY = "mc.rateSkipSequenced";

/** One step of the session, in the order it happened — what ↑ / U walks
 *  back over.
 *
 *  A "not applicable" is a step too. It was not, so the mark was the one
 *  thing in this overlay with no way back: a picture ticked by accident had
 *  LEFT THE AXIS, permanently and silently, and the only cure was to find it
 *  again in the rankings list. It is a real, reversible state
 *  (`rankingUndismiss`), so it belongs in the same history as everything
 *  else. */
type Step =
  | { kind: "judge"; rankingId: number; a: RankingItemRef; b: RankingItemRef;
      /** One event per pool the judgement was written into — undo
       *  reverts the whole fan. */
      eventIds: number[] }
  | { kind: "mark"; rankingId: number; a: RankingItemRef; b: RankingItemRef;
      itemId: number };

/** One clickable entry of the keycap footer — the same words, reachable with
 *  the pointer. Dim and inert where its key would be refused. */
function KeyAction({ children, onClick, disabled, lit }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean;
  /** The one live way on — accented while everything beside it is refused. */
  lit?: boolean;
}) {
  return (
    <span className={disabled ? undefined : "hoverable"}
      onClick={disabled ? undefined : onClick}
      style={{ padding: "2px 6px", borderRadius: "var(--r-2)",
               cursor: disabled ? "default" : "pointer",
               opacity: disabled ? 0.4 : 1,
               color: lit ? "var(--selected-text)" : undefined,
               background: rowBackground(lit, "transparent"),
               border: `1px solid ${lit ? "var(--accent)" : "transparent"}` }}>
      {children}
    </span>
  );
}


export function RateOverlay() {
  const t = useT();
  const tn = useTn();
  const errText = useErrText();
  const qc = useQueryClient();
  const rankingId = useUI((s) => s.rateRankingId);
  const setRateRanking = useUI((s) => s.setRateRanking);
  const inLibrary = useUI((s) => s.view) === "library";
  const view = useViewScope(inLibrary);
  const { data: rankings } = useQuery({ queryKey: ["rankings"],
                                        queryFn: () => api.rankings() });

  const [pair, setPair] = useState<RankingPairOut | null>(null);
  //: THE TWO CARDS FOLLOW THEIR ITEMS (`useItemPatches`): a turn made in
  //  the preview over the session reaches the pair's rows.
  useItemPatches((d) => setPair((cur) => {
    if (!cur) return cur;
    const a = cur.a && patchRow(cur.a, d), b = cur.b && patchRow(cur.b, d);
    return a === cur.a && b === cur.b ? cur : { ...cur, a, b };
  }));
  // The standings, shown INSTEAD of the pair: filled by an exhausted pool,
  // by the header's summary button, or by Esc — which shows it first and
  // only closes from it.
  const [summary, setSummary] = useState<RankingPairOut["summary"] | null>(null);
  const [session, setSession] = useState(0);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // The last pair fetch's failure — shown with a Try again where the pair
  // would be. It used to be swallowed, and the session sat on "Loading…".
  const [failed, setFailed] = useState<string | null>(null);
  // What the session just showed / judged, for `recent` and for U.
  const recent = useRef<number[][]>([]);
  const judged = useSessionUndo<Step>();
  // The pool is CAPTURED when the overlay opens: a selection if one is held,
  // else the view — rating must not chase the grid underneath it. The whole
  // request travels, so the view's own kind filter (Videos, Sequences)
  // decides what a session rates.
  const scopeRef = useRef<Record<string, unknown> | null>(null);
  const cameFrom = useRef<HTMLElement | null>(null);

  const open = rankingId != null;
  const ranking = (rankings ?? []).find((r) => r.id === rankingId) ?? null;
  // EVERY ranking is offered. The switch a row can be turned off with says
  // whether the standings are written out as score tags, not whether the
  // axis exists — an axis rated for its own sake, or read through the
  // standings alone, is still an axis to rate on.
  const enabledRows = useMemo(() => rankings ?? [], [rankings]);

  // NO opening key any more — the overlay opens from the grid's
  // quick-actions "Rate batch…" row and the context menu's per-ranking rows
  // (an R binding existed and was removed with the Tag batch overlay's
  // arrival: two session overlays each claiming a letter was a keyboard
  // nobody could learn, and the menu is where both are findable). The
  // return-focus target is therefore captured when the overlay OPENS rather
  // than at a keypress.
  const rowsRef = useRef(enabledRows);
  rowsRef.current = enabledRows;
  /** WHICH KIND this session asks about — the Tag batch chooser's own
   *  option, for the same reason: a session is a rhythm and the two do not
   *  share one. A picture is judged at a glance; a film has to be watched,
   *  so every video in a run of stills is a stall. It rides as the scope's
   *  own `kind`, OVERRIDING whatever the view was filtered to, because the
   *  session says what it asks about. */
  const [askKind, setAskKind] = useState<"image" | "video">("image");
  /** Leave out pictures that are members of a sequence — the tag grid's
   *  switch, remembered like the kind is not: a book's pages are the same
   *  decision every session. */
  const [skipSeq, setSkipSeq] = useState(() => loadFlag(SKIP_SEQ_KEY, false));
  /** WHICH AXES the chooser is on, IN ORDER — a pick, not a start: the
   *  chooser is an ordinary dialog and only its Start button opens the
   *  full-screen session (the Tag batch's shape, so the two read as one
   *  app).
   *
   *  SEVERAL, because a pair is worth more than one question: the same two
   *  pictures are judged on each axis in turn before the next pair comes
   *  up, which is the whole cost of rating (finding a pair worth comparing,
   *  and looking at it) paid once for three answers. The ORDER is the
   *  order they are asked in, so it is editable rather than whatever the
   *  rows happen to be sorted by. */
  const [picked, setPicked] = useState<number[]>([]);
  /** WHICH LEAGUES of each picked ranking — offered only where a ranking
   *  has more than one; absent means all of them. */
  const [pickedPools, setPickedPools] = useState<PoolPick>({});
  useEffect(() => {
    if (rankingId !== -1) return;
    const rows = rowsRef.current;
    // A ranking JUST MADE in this dialog keeps the pick it was added to —
    // this effect is only re-running because the catalog grew.
    if (addedRanking.current != null) {
      addedRanking.current = null;
      return;
    }
    // A SEEDED chooser — the context menu's door for a ranking with several
    // pools, where "Rate on X" has to ask which — opens on that ranking
    // with every pool ticked, and spends the seed.
    const seed = useUI.getState().rateChooserSeed;
    if (seed != null) {
      useUI.getState().setRateChooserSeed(null);
      if (rows.some((r) => r.id === seed)) {
        setPicked([seed]);
        // Its OWN remembered pools, not a blank slate: the seed says
        // which ranking to open on, and clearing the pick here made "Rate
        // on X" the one door that forgot what X means.
        setPickedPools(loadPoolMemory(rows));
        return;
      }
    }
    // Seeded with the axes last rated, which is what somebody coming back
    // to this dialog almost always wants; otherwise the first row. The
    // stored value is a LIST now and reads an older single id unchanged.
    const last = parseLast(storage.get(LAST_KEY) || "", rows);
    setPicked(last.picked.length ? last.picked
      : (rows[0] ? [rows[0].id] : []));
    // The last SESSION's pools win where it had any, over the standing
    // per-ranking memory for everything else — so re-ticking a ranking the
    // last session did not rate still opens on what it was last set to.
    setPickedPools({ ...loadPoolMemory(rows), ...last.pools });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rankingId, enabledRows.length]);

  /** THE SESSION'S OWN LIST, and its cursor.
   *
   *  The store holds ONE `rateRankingId` — the session's identity, and what
   *  every `rateIsOpen()` guard reads — so the rest of the queue lives
   *  here. A session opened straight onto a named axis (the grid's context
   *  menu) has no queue at all and falls back to that one id, which is what
   *  keeps the single-ranking behaviour exactly what it was. */
  const [queue, setQueue] = useState<number[]>([]);
  /** The session's pools per axis, MATERIALIZED (a multi-pool ranking
   *  always has a list here; a single-pool one sends none). */
  const [queuePools, setQueuePools] = useState<PoolPick>({});
  const [cursor, setCursor] = useState(0);
  /** ENDING IS ASKED ABOUT, ONCE SOMETHING HAS BEEN ANSWERED. Escape used
   *  to show the standings and only leave on a second press, which made the
   *  standings a thing you passed THROUGH rather than looked at (Tab is the
   *  toggle now) and left no single gesture that means "I am done". This is
   *  that gesture, with the one question worth asking in front of it: a
   *  session is a rhythm and Escape is next to the keys that keep it. */
  const [confirmEnd, setConfirmEnd] = useState(false);
  /** The chooser again, over a RUNNING session — the tag batch's Settings
   *  button: axes, kind and the sequence rule all changeable mid-run, and
   *  Continue takes over from the next pair. */
  const [configuring, setConfiguring] = useState(false);
  /** MAKING OR EDITING AN AXIS, FROM THE CHOOSER — `{row: null}` is a new
   *  one, `{row}` an edit. The chooser used to point at another tab for
   *  both ("make one in Tags → Rankings"), which is an errand in the middle
   *  of setting up a session: what somebody notices HERE is that the axis
   *  they want does not exist yet, or that the one they are ticking is
   *  named or ranged wrong.
   *
   *  It is the Rankings tab's own dialog, so there is one editor for one
   *  job. The chooser UNMOUNTS while it is up rather than stacking two
   *  sheets: both are `Overlay`s at one layer, and each puts an Escape
   *  listener on `window` — where `stopPropagation` cannot arbitrate, so
   *  one press would close both. (The Tag batch's own mid-session chooser
   *  makes the same split.) */
  const [editing, setEditing] = useState<{ row: RankingRow | null } | null>(
    null);
  /** The ids the chooser knew before the editor opened: `create` answers
   *  with the WHOLE catalog, so the row just made is the one that was not
   *  there — the grid's Rate-batch door resolves it the same way. */
  const knownIds = useRef<Set<number>>(new Set());
  const openEditor = (row: RankingRow | null) => {
    knownIds.current = new Set((rankings ?? []).map((r) => r.id));
    setEditing({ row });
  };
  /** A ranking made here JOINS the pick rather than replacing it, and is
   *  asked LAST — it is the axis somebody just went to the trouble of
   *  making. The ref is what stops the seeding effect above from undoing
   *  that: creating a row changes `enabledRows.length`, which is one of its
   *  deps, so it would otherwise re-seed from `LAST_KEY` a moment later and
   *  drop the tick. */
  const addedRanking = useRef<number | null>(null);
  const axes = queue.length ? queue
    : (rankingId != null && rankingId > 0 ? [rankingId] : []);
  const activeId = axes.length
    ? axes[Math.min(cursor, axes.length - 1)] : null;
  const activeRanking =
    (rankings ?? []).find((r) => r.id === activeId) ?? null;
  // What the fetch and the judge read without re-arming their effects.
  const axesRef = useRef(axes);
  axesRef.current = axes;
  const poolsRef = useRef(queuePools);
  poolsRef.current = queuePools;
  const cursorRef = useRef(cursor);
  cursorRef.current = cursor;
  /** The pools the session writes into on each axis — see `poolsFor`. */
  const sessionPools = (rows: RankingRow[], ids: number[],
                          pick: PoolPick): PoolPick => {
    const out: PoolPick = {};
    for (const id of ids) {
      const r = rows.find((x) => x.id === id);
      const lids = r ? poolsFor(r, pick) : [];
      if (lids.length) out[id] = lids;
    }
    return out;
  };
  /** How many pairs this session has shown — the ROTATION, so every axis
   *  gets a turn at choosing what to compare. Which axis picks matters:
   *  `next_pair` orders by that ranking's own least-judged items and pairs
   *  them by nearest standing, so leaving the choice to the first axis
   *  forever would let it drive the other two's coverage. */
  const shown = useRef(0);

  /** Start on one axis, from the CHOOSER — which is the one door that asks
   *  about the kind, so it is the one that stamps it. A session opened
   *  straight onto a named axis (the grid's context menu) inherits the
   *  view's own filter, exactly as it always did: nobody was asked there,
   *  and answering for them would rate pictures over a Videos category. The
   *  scope is captured when the overlay OPENS — the axis is picked a moment
   *  later, and the kind after that — so this is stamped on the way in. */
  const startOn = (ids: number[]) => {
    if (!ids.length) return;
    if (scopeRef.current) {
      scopeRef.current.kind = askKind;
      if (skipSeq) scopeRef.current.hide_sequenced = true;
    }
    setQueue(ids);
    const lg = sessionPools(rowsRef.current, ids, pickedPools);
    setQueuePools(lg);
    poolsRef.current = lg;
    setCursor(0);
    // The store takes the FIRST — it is the session's identity, and the
    // reset effect below is keyed on it, so it must be set last and once.
    setRateRanking(ids[0]);
  };

  // Capture the session scope the moment it opens, then fetch the first pair.
  useEffect(() => {
    if (!open || rankingId == null) return;
    // The pool is captured at OPEN — chooser included, so the axis picked a
    // moment later rates what was on screen when the menu row was clicked.
    if (scopeRef.current == null) {
      cameFrom.current = document.activeElement as HTMLElement | null;
      // The POOL is always the view — a selection never fences it in (two
      // selected items used to make a one-pair session that ended at once).
      // What a selection means is PRIORITY: `items` rides beside the search
      // body and the server compares those pictures first, each against
      // partners from the whole pool.
      const sel = useUI.getState().selectedItems;
      scopeRef.current = {
        ...(useUI.getState().view === "library"
          ? ({ ...view.req } as unknown as Record<string, unknown>) : {}),
        ...(sel.length > 0 ? { items: sel } : {}),
      };
    }
    recent.current = [];
    judged.clear();
    pool.current = null;
    shown.current = 0;
    setFailed(null);
    setSession(0);
    setPair(null);
    setSummary(null);
    setCursor(0);
    setConfirmEnd(false);
    if (rankingId != null && rankingId > 0) {
      storage.set(LAST_KEY,
                           formatLast(axesRef.current, poolsRef.current));
      // The session's MATERIALIZED pools, so a run started straight from
      // the context menu — which never opens the chooser — is remembered
      // too, and the next chooser opens on what was actually rated.
      savePoolMemory(rowsRef.current, poolsRef.current);
      void fetchPair();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rankingId]);

  /** The pool's size, asked for ONCE a session.
   *
   * It is a `count(*)` over everything the scope admits — 200 ms at a
   * million items — and the scope is captured when the overlay opens, so
   * the number cannot move: judging changes what is KNOWN about the pool,
   * never what is in it. Asking again per keypress was most of what a
   * judgement cost on a big library.
   */
  const pool = useRef<number | null>(null);

  /** THE NEXT PAIR, and the axis that chose it goes back to the front.
   *
   *  One pair is judged on every axis in turn, so only ONE of them picks
   *  it — and they take that turn in rotation (`shown`), because
   *  `next_pair` orders by the asking ranking's own least-judged items:
   *  leaving the choice to the first axis forever would let it drive what
   *  the others ever see. An axis with nothing left to offer hands the turn
   *  on rather than ending the session, so the run lasts as long as ANY of
   *  them still has a pair; the standings shown when they are all out are
   *  the last axis asked. */
  const fetchPair = async () => {
    setFailed(null);
    try {
      await fetchPairInner();
    } catch (e) {
      setFailed(errText(e));
    }
  };
  const fetchPairInner = async () => {
    const list = axesRef.current;
    if (!list.length) return;
    const scope = scopeRef.current ?? {};
    let last: RankingPairOut | null = null;
    for (let n = 0; n < list.length; n++) {
      const at = (shown.current + n) % list.length;
      const got = await api.rankingPair(list[at], {
        ...(scope as object),
        pool_ids: poolsRef.current[list[at]] ?? [],
        want_pool: pool.current == null,
        // The WHOLE session's shown pairs, not a tail: a pair judged this
        // session is done for this session, which is what lets a session
        // END — and the summary appear — instead of recycling the same
        // matchups forever. A fresh session re-offers them (repeats are
        // evidence). Shared across the axes, because the pair is.
        recent: recent.current,
      });
      last = got;
      if (got.pool != null) pool.current = got.pool;
      if (got.a && got.b) {
        shown.current += 1;
        setCursor(0);
        setPair(got);
        recent.current.push([got.a.item_id, got.b.item_id]);
        return;
      }
    }
    // Nothing anywhere: the last answer carries the standings to show.
    setPair(last);
    if ((last?.summary?.length ?? 0) > 0) setSummary(last!.summary);
  };

  /** CONTINUE, from the Settings dialog: what the session has answered
   *  stays (its count, its undo stack, its shown-pairs memory); the pair
   *  on screen goes, since it was picked under the old settings and may
   *  not even be in the new scope, and the pool is asked for again. The
   *  store's own id is left alone — it is the session's identity, and the
   *  reset effect is keyed on it. */
  const applyConfig = () => {
    if (!picked.length) return;
    if (scopeRef.current) {
      scopeRef.current.kind = askKind;
      if (skipSeq) scopeRef.current.hide_sequenced = true;
      else delete scopeRef.current.hide_sequenced;
    }
    storage.set(LAST_KEY, formatLast(picked, pickedPools));
    savePoolMemory(rowsRef.current, pickedPools);
    setQueue(picked);
    axesRef.current = picked;
    const lg = sessionPools(rowsRef.current, picked, pickedPools);
    setQueuePools(lg);
    poolsRef.current = lg;
    setCursor(0);
    cursorRef.current = 0;
    setDismissed(new Set());
    pool.current = null;
    setSummary(null);
    setPair(null);
    setConfiguring(false);
    void fetchPair();
  };

  /** ON TO THE NEXT QUESTION — the next axis for this same pair, or the
   *  next pair once every axis has had its answer. Every way of answering
   *  goes through here (a pick, a tie, a skip, and both sides marked), or
   *  they would drift into different ideas of what "done with this pair"
   *  means. */
  const advance = async () => {
    const list = axesRef.current;
    if (cursorRef.current + 1 < list.length) {
      setCursor(cursorRef.current + 1);
      setDismissed(new Set());
      return;
    }
    await fetchPair();
  };

  // The standings on demand — the header button and Esc, while pairs are
  // still being offered. `summary_only` skips the pair pick server-side.
  const openSummary = async () => {
    if (activeId == null || activeId < 0) return;
    const scope = scopeRef.current ?? {};
    const got = await api.rankingPair(activeId, {
      ...(scope as object),
      pool_ids: poolsRef.current[activeId] ?? [],
      summary_only: true });
    setSummary(got.summary ?? []);
  };

  const close = async () => {
    // EVERY axis the session was on, not the one on screen — each holds its
    // own judgments, and each detail has to be re-read.
    const ids = axes.filter((x) => x > 0);
    const n = session;
    const first = (rankings ?? []).find((r) => r.id === ids[0]);
    const name = first?.name || "";
    setRateRanking(null);
    setQueue([]);
    setPair(null);
    setConfiguring(false);
    scopeRef.current = null;
    if (ids.length) {
      // The standings are FITTED ON READ, so ending a session is nothing
      // but dropping what it was showing: there is no refresh to run and
      // no stale state to leave behind. The note is the only trace.
      for (const id of ids) {
        qc.invalidateQueries({ queryKey: ["ranking-detail", id] });
      }
      qc.invalidateQueries({ queryKey: ["rankings"] });
      bumpLibrary();
      if (n > 0) {
        // One axis is named; several are counted, since a list of three
        // names in a toast is a sentence nobody finishes reading.
        setNote(ids.length === 1
          ? tn({ one: "{n} comparison on {name} — scores updated",
                 other: "{n} comparisons on {name} — scores updated" },
               n, { name })
          : tn({ one: "1 comparison — scores updated",
                 other: "{n} comparisons — scores updated" }, n));
      }
    }
  };

  /** EVERY WAY OUT GOES THROUGH ONE GUARD — Escape, the header's ✕ and the
   *  backdrop are the same "I am done", and a question asked by one of them
   *  and not the others reads as unreliable rather than as scoped. A
   *  session that has answered NOTHING skips it: there is no rhythm to
   *  interrupt and nothing to confirm. */
  const askClose = () => {
    if (session === 0) { void close(); return; }
    setConfirmEnd(true);
  };

  // Hand the focus back on the way out (the T overlay's rule).
  useEffect(() => {
    if (open) return;
    const el = cameFrom.current;
    cameFrom.current = null;
    if (el && el.isConnected) el.focus();
  }, [open]);


  const decide = async (outcome: "a" | "b" | "tie" | "skip") => {
    if (busy || activeId == null || !pair?.a || !pair.b) return;
    // A picture marked "not applicable" has left the axis, so there is
    // nothing to compare it with. SKIP still works — it is how you leave a
    // pair you have said that about, and it records nothing either way.
    if (outcome !== "skip" && dismissed.size) return;
    setBusy(true);
    try {
      // ONE judgement, into every pool picked for this axis — one row and
      // one event per pool, and the whole fan is what ↑ takes back.
      const res = await api.rankingJudge(
        activeId, pair.a.item_id, pair.b.item_id, outcome,
        poolsRef.current[activeId] ?? []);
      const eventIds = (res.event_ids ?? [res.event_id])
        .filter((x): x is number => x != null);
      judged.push({ kind: "judge", rankingId: activeId,
                    a: pair.a, b: pair.b, eventIds });
      setSession((n) => n + 1);
      await advance();
    } finally {
      setBusy(false);
    }
  };

  const undo = async () => {
    if (busy || rankingId == null) return;
    const last = judged.pop();
    if (!last) return;
    setBusy(true);
    try {
      if (last.kind === "judge") {
        await judged.revert(last.eventIds);
        setSession((n) => Math.max(0, n - 1));
        setDismissed(new Set());
      } else {
        // Putting a picture BACK on the axis, and back on screen with the
        // pair it was ticked in — the tick is what the step was.
        await api.rankingUndismiss(last.rankingId, last.itemId);
        setDismissed((cur) => {
          const next = new Set(cur);
          next.delete(last.itemId);
          return next;
        });
      }
      // …and back onto the AXIS it answered, which is not always the one on
      // screen: a pair is judged on each of them in turn, so the step
      // before this one is usually the axis before this one.
      const at = axesRef.current.indexOf(last.rankingId);
      if (at >= 0) setCursor(at);
      // The pair comes back, exactly as it was — leaving the summary,
      // which no longer describes the standings the revert just moved.
      setSummary(null);
      setPair({ a: last.a, b: last.b, reason: "",
                pool: pool.current, judgments: pair?.judgments ?? 0 });
    } finally {
      setBusy(false);
    }
  };

  /** WHICH OF THE PAIR HAVE BEEN MARKED "not applicable" — a TOGGLE now,
   *  not a button that acts and moves on.
   *
   *  It was a link that dismissed its side and fetched the next pair at
   *  once, so saying it about BOTH pictures — which is the ordinary case, a
   *  pair of screenshots on a "composition" axis — meant marking one, taking
   *  whatever pair came back, and hunting for the other picture again. The
   *  mark is a real state and reversible either way (`rankingUndismiss`), so
   *  it is a checkbox: tick both, and the pair leaves by itself because
   *  there is nothing left in it to compare.
   */
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  useEffect(() => { setDismissed(new Set()); }, [pair?.a?.item_id,
                                                 pair?.b?.item_id, cursor]);

  const toggleDismiss = async (side: RankingItemRef) => {
    if (busy || activeId == null) return;
    const on = !dismissed.has(side.item_id);
    setBusy(true);
    try {
      // PER AXIS: a dismissal is a fact about one ranking ("composition
      // does not apply to this picture"), so it is written for the axis
      // being asked and says nothing about the next one.
      if (on) await api.rankingDismiss(activeId, side.item_id);
      else await api.rankingUndismiss(activeId, side.item_id);
      if (on && pair?.a && pair.b) {
        judged.push({ kind: "mark", rankingId: activeId,
                      a: pair.a, b: pair.b, itemId: side.item_id });
      } else {
        // Unticking IS the undo of the tick, so it spends that step rather
        // than leaving one ↑ would perform a second time.
        judged.drop((step) => step.kind === "mark" && step.itemId === side.item_id);
      }
      const next = new Set(dismissed);
      if (on) next.add(side.item_id); else next.delete(side.item_id);
      // BOTH marked: there is nothing left to judge ON THIS AXIS, so the
      // question moves on — the next axis for the same pair, or the next
      // pair. With one marked it stays: the other picture is still a
      // picture, and leaving is the ordinary Space.
      if (next.size === 2 && pair?.a && pair.b) {
        setDismissed(new Set());
        await advance();
      } else {
        setDismissed(next);
      }
    } finally {
      setBusy(false);
    }
  };

  // THE KEYBOARD is the sessions' one spine (`useSessionKeys`): the gates,
  // Escape through the stack, Tab, undo, Space and S are its; what is the
  // rating's own is the four judging keys.
  useSessionKeys({
    isOpen: () => open,
    // Escape only while the SESSION is on top: the chooser and the settings
    // sheet are `Overlay`s with Escape of their own, and the ranking editor
    // is a dialog of its own with its own fields.
    escape: open && rankingId !== -1 && !configuring && !editing,
    standDown: () => editing != null || confirmEnd,
    preface: (e) => {
      if (rankingId !== -1 && !configuring) return false;
      // THE CHOOSER: Enter starts; the axes are PICKED with the pointer. A
      // digit used to name one, and that went when the pick became a LIST
      // WITH AN ORDER: what a digit would mean there (add it? move it? make
      // it first?) is three answers, and a key that quietly does one of
      // them over a list somebody has arranged is worse than no key.
      if (e.key === "Enter" && picked.length) {
        e.preventDefault();
        if (configuring) applyConfig(); else startOn(picked);
      }
      return true;
    },
    onEscape: askClose,
    // TAB IS THE STANDINGS, both ways. They are a thing to LOOK at
    // mid-session — is this axis coming out the way I meant? — which is a
    // MODE rather than a step, so it toggles. Escape passed through them on
    // the way out instead, which made them something you dismissed rather
    // than read.
    onTab: () => {
      if (summary != null) { if (pair?.a && pair.b) setSummary(null); }
      else void openSummary();
    },
    summaryOpen: () => summary != null,
    // ↑ undoes, which is what the FOOTER says and what the tag session's
    // own footer has always said — the two sessions share one hand. U
    // still works and is deliberately unadvertised: it was the cap here
    // for a while, so anybody who learnt it keeps it, and one keycap per
    // action is what the row is for.
    undo: { match: (e) => e.key === "u" || e.key === "U" || e.key === "ArrowUp",
            run: () => void undo() },
    // SPACE IS THE PREVIEW — the pair, large, with the preview's own zoom
    // (the card's went with it); ←/→ step between the two there.
    preview: () => {
      const st = useUI.getState();
      if (st.quickLook) st.setQuickLook(false);
      else if (pair?.a && pair.b) st.openQuickLook([pair.a.item_id, pair.b.item_id]);
    },
    skip: () => void decide("skip"),
    keys: [
      // SHIFT+ARROW TICKS THAT SIDE'S "not applicable" — the same two keys
      // that answer the pair, saying the other thing about it. The pointer
      // had the only way to it, which on a session run entirely from the
      // keyboard means leaving the keyboard for the one answer that is not
      // a comparison; ⇧ is the modifier because the arrow already NAMES the
      // side, so nothing has to be learnt but the shift.
      { match: (e) => e.shiftKey && (e.key === "ArrowLeft" || e.key === "ArrowRight"),
        run: (e) => {
          const side = e.key === "ArrowLeft" ? pair?.a : pair?.b;
          if (side) void toggleDismiss(side);
        } },
      { match: (e) => e.key === "ArrowLeft", run: () => void decide("a") },
      { match: (e) => e.key === "ArrowRight", run: () => void decide("b") },
      // ↓ rather than ↑: a tie "settles the pair down", and the up arrow
      // kept being read as "the top one".
      { match: (e) => e.key === "ArrowDown", run: () => void decide("tie") },
    ],
  });

  const backdrop = useBackdropDismiss(() => askClose());

  const frameRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    // Take the FOCUS: the grid scroller keeps it otherwise, and its own
    // key handler is on the element — the window guards are the belt, this
    // is the braces.
    if (open) frameRef.current?.focus();
  }, [open, rankingId]);

  if (!open && !note) return null;

  const canStart = picked.length > 0;
  /** Tick an axis in or out. THE ORDER IS THE ORDER THEY WERE PICKED — the
   *  order they will be asked in, and the number on each row says it.
   *
   *  Two chevrons sat here to move a row within that list and were removed:
   *  the rows never move (the list is the catalog's own order, so the tick
   *  and the number are what change), and an up-arrow that leaves the row
   *  where it is and edits a digit beside it is a control saying one thing
   *  and doing another. Re-picking is the edit — untick, tick, and the
   *  number follows the click. */
  const togglePick = (id: number) => setPicked((cur) =>
    cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]);
  /** Tick a pool in or out for one ranking. At least one stays: a
   *  ranking with no pool picked is a ranking the session cannot write
   *  into, so the last tick refuses rather than emptying the list. Kept in
   *  the ranking's own order — the click order means nothing here. */
  const togglePool = (r: RankingRow, lid: number) =>
    setPickedPools((cur) => {
      // From what the row currently SHOWS — `poolsFor`, the one rule —
      // or the first click on an untouched ranking would start from every
      // pool rather than from the one ticked in front of it.
      const have = poolsFor(r, cur);
      const next = have.includes(lid)
        ? have.filter((x) => x !== lid) : [...have, lid];
      if (!next.length) return cur;
      return { ...cur,
               [r.id]: r.pools.map((l) => l.id).filter((x) => next.includes(x)) };
    });
  /** THE CHOOSER IS AN ORDINARY DIALOG — header, ✕, footer, one Start — and
   *  only Start opens the full-screen session over the library. It used to
   *  BE the session overlay with a list in the middle of it, which put a
   *  question that has not been asked yet behind a black full-window sheet
   *  and gave the axes no room for anything but their own names. The Tag
   *  batch chooser's shape, down to the import overlay's card chrome, so
   *  the two sessions read as one app. */
  const chooser = open && !editing && (rankingId === -1 || configuring) && (
    <Overlay icon={configuring ? "tune" : "leaderboard"}
      title={configuring ? t("Session settings") : t("Rate items")}
      subtitle={configuring
        ? t("Changes take over from the next pair.")
        : t("What do you want to rate?")}
      width={560}
      onClose={() => { if (configuring) setConfiguring(false);
                       else void close(); }}
      footer={<>
        {enabledRows.length === 0 && (
          <span style={{ fontSize: "var(--fs-2)", marginRight: "auto", minWidth: 0,
                         color: "var(--muted-2)" }}>
            {t("No ranking to rate on yet — add one above.")}
          </span>
        )}
        <Button variant="primary" size="md"
     onClick={canStart
      ? (configuring ? applyConfig : () => startOn(picked)) : undefined}>
          <Icon name={configuring ? "check" : "play_arrow"} size={16} />
          {" "}{configuring ? t("Continue") : t("Start")}
        </Button>
      </>}>
      {/* THE BODY PADS ITSELF — `Overlay` gives its children none, on
          purpose (the import overlay's preview grid wants the full width),
          so a dialog that forgets it has its cards against the panel's own
          edges. 18, the Tag batch chooser's. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16,
                    padding: 18, color: "var(--text)" }}>
        <div>
          <div style={sectionLabel}>{t("Rankings")}</div>
          <div style={card}>
            {/* CHECKBOXES, and the ticked ones are NUMBERED: a pair is
                asked on each of them in turn, so the list has an order and
                the number is it. Reordering is re-picking — the click order
                IS the order. */}
            {enabledRows.map((r) => {
              const at = picked.indexOf(r.id);
              const on = at >= 0;
              // WHICH LEAGUES, under a ticked ranking that has more than
              // one — with one there is nothing to choose and nothing is
              // shown, so a library that never made a second pool sees
              // the dialog it always had.
              const poolRows = on && (r.pools?.length ?? 0) > 1
                ? r.pools : [];
              const lit = poolsFor(r, pickedPools);
              return (
                <React.Fragment key={r.id}>
                <div className="hoverable"
                  onClick={() => togglePick(r.id)}
                  style={{ position: "relative",
                           display: "flex", alignItems: "center", gap: 10,
                           padding: "9px 14px", cursor: "pointer",
                           // Every row rules off now: the card always ends
                           // with the "New ranking…" row below.
                           borderBottom: "1px solid var(--border-soft)",
                           background: rowBackground(on, "transparent"),
                           color: on ? "var(--selected-text)" : undefined }}>
                  <Icon name={on ? "check_box" : "check_box_outline_blank"}
                        size={17}
                        color={on ? "var(--accent)" : "var(--muted-2)"} />
                  {/* WHICH QUESTION COMES WHEN. An unticked row keeps the
                      slot empty rather than closing it up, or every row
                      steps sideways as the ticks change. */}
                  <span style={{ width: 16, flex: "0 0 auto", fontSize: "var(--fs-2)",
                                 fontWeight: 700, textAlign: "center",
                                 fontVariantNumeric: "tabular-nums",
                                 color: on ? "var(--accent)" : "transparent" }}>
                    {on ? at + 1 : "0"}
                  </span>
                  <span style={{ fontSize: "var(--fs-4)", fontWeight: 600,
                                 overflow: "hidden",
                                 textOverflow: "ellipsis",
                                 whiteSpace: "nowrap" }}>
                    {r.name}
                  </span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                                 opacity: 0.65, whiteSpace: "nowrap" }}>
                    {r.bucket_lo}…{r.bucket_hi}
                  </span>
                  <span style={{ flex: 1 }} />
                  {/* Both counts, each with its noun — how much evidence
                      the axis holds, and how many pictures it has placed. */}
                  <span style={{ fontSize: "var(--fs-2)", opacity: 0.7,
                                 fontVariantNumeric: "tabular-nums",
                                 whiteSpace: "nowrap" }}>
                    {tn({ one: "1 comparison", other: "{n} comparisons" },
                        r.judgments)}
                    {" · "}
                    {tn({ one: "1 item rated", other: "{n} items rated" },
                        r.items)}
                  </span>
                  {/* The Rankings tab's own hover pencil, in this dialog's
                      terms — same action, same glyph, so it reads as the one
                      control it is. It stops the click: the row's own is the
                      tick.

                      OVERLAID ON THE ROW'S RIGHT EDGE, not in its flow —
                      the tag rows' own shape, and for their reason: in flow
                      it takes width from the counts when it appears and
                      height from the row, so the whole row moves under the
                      pointer that is reaching for it. Absolute, it costs the
                      row nothing at all. The backdrop is the row's own
                      background with a soft left fade, so what it covers
                      fades out rather than showing through the glyph. */}
                  <span
                    className="tag-edit-btn"
                    onClick={(e) => { e.stopPropagation(); openEditor(r); }}
                    title={t("Edit this ranking")}
                    style={{ position: "absolute", right: 6, top: "50%",
                             transform: "translateY(-50%)",
                             alignItems: "center", justifyContent: "center",
                             width: 20, height: 20, borderRadius: "var(--r-1)",
                             color: "var(--muted-2)", cursor: "pointer",
                             background: on
                               ? "linear-gradient(var(--accent-dim), var(--accent-dim)), var(--panel-2)"
                               : "var(--panel-2)",
                             boxShadow: `-7px 0 7px 0 ${on
                               ? "var(--accent-dim)" : "var(--panel-2)"}` }}>
                    <Icon name="edit" size={14} />
                  </span>
                </div>
                {poolRows.map((lg) => {
                  const lgOn = lit.includes(lg.id);
                  return (
                    <div key={lg.id} className="hoverable"
                      onClick={(e) => { e.stopPropagation();
                                        togglePool(r, lg.id); }}
                      title={lgOn && lit.length === 1
                        ? t("At least one pool stays picked") : undefined}
                      style={{ display: "flex", alignItems: "center", gap: 10,
                               padding: "6px 14px 6px 57px", cursor: "pointer",
                               borderBottom: "1px solid var(--border-soft)",
                               background: "var(--panel-2)" }}>
                      <Icon name={lgOn ? "check_box" : "check_box_outline_blank"}
                            size={15}
                            color={lgOn ? "var(--accent)" : "var(--muted-2)"} />
                      <span style={{ fontSize: "var(--fs-3)", overflow: "hidden",
                                     textOverflow: "ellipsis",
                                     whiteSpace: "nowrap",
                                     color: lgOn ? "var(--text)" : "var(--muted)" }}>
                        {lg.name || t("Default")}
                      </span>
                      <span style={{ flex: 1 }} />
                      <span style={{ fontSize: "var(--fs-2)", opacity: 0.7,
                                     fontVariantNumeric: "tabular-nums",
                                     whiteSpace: "nowrap" }}>
                        {tn({ one: "1 comparison", other: "{n} comparisons" },
                            lg.judgments)}
                      </span>
                    </div>
                  );
                })}
                </React.Fragment>
              );
            })}
            {/* MAKING ONE IS A ROW OF THE LIST IT JOINS, last and quieter
                than the axes above it — which is also what gives the card
                something to hold when there are no rankings at all, where
                it used to be an empty box under a heading. */}
            <div className="hoverable"
              onClick={() => openEditor(null)}
              style={{ display: "flex", alignItems: "center", gap: 10,
                       padding: "9px 14px", cursor: "pointer",
                       color: "var(--muted)", fontSize: "var(--fs-3)" }}>
              <Icon name="add" size={17} color="var(--muted-2)" />
              {t("New ranking…")}
            </div>
          </div>
        </div>
        <div>
          <div style={sectionLabel}>{t("Options")}</div>
          <div style={card}>
            {/* WHICH KIND, and never both — the Tag batch chooser's own
                option, for the same reason: a session is a rhythm and the
                two do not share one, so every film was a stall in a run of
                stills. It OVERRIDES the view's own filter, because the
                session is what says which kind it asks about. */}
            <div style={{ padding: "12px 14px", display: "flex",
                          alignItems: "center", gap: 14,
                          borderBottom: "1px solid var(--border-soft)" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: "var(--fs-4)" }}>{t("Ask about")}</div>
                <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)",
                              marginTop: 3, lineHeight: 1.45 }}>
                  {t("One kind per session — a picture is judged at a glance and a film has to be watched.")}
                </div>
              </div>
              <div style={{ display: "flex", flex: "0 0 auto",
                            border: "1px solid var(--border-strong)",
                            borderRadius: "var(--r-4)", overflow: "hidden" }}>
                {([["image", t("Images")], ["video", t("Videos")]] as const)
                  .map(([k, label]) => (
                  <button key={k} type="button"
                    onClick={() => setAskKind(k)}
                    style={{ height: 28, padding: "0 12px", border: "none",
                             cursor: "pointer", fontSize: "var(--fs-3)",
                             fontFamily: "inherit",
                             background: askKind === k
                               ? "var(--accent)" : "transparent",
                             color: askKind === k
                               ? "var(--on-accent)" : "var(--text-2)" }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <OptionRow
              title={t("Skip pictures in sequences")}
              desc={t("Pages of a book and frames of a GIF are left out.")}
              checked={skipSeq}
              onToggle={() => setSkipSeq((v) => {
                saveFlag(SKIP_SEQ_KEY, !v); return !v; })}
              last
            />
          </div>
        </div>
      </div>
    </Overlay>
  );

  return createPortal(
    <>
      {chooser}
      {editing && (
        <RankingEditOverlay ranking={editing.row}
          onClose={() => setEditing(null)}
          onSaved={(rows) => {
            const wasNew = editing.row === null;
            setEditing(null);
            qc.invalidateQueries({ queryKey: ["rankings"] });
            if (!wasNew) return;
            // The row just made is the one the chooser had not seen.
            const made = (rows ?? []).find(
              (r) => !knownIds.current.has(r.id));
            if (!made) return;
            addedRanking.current = made.id;
            setPicked((cur) => cur.includes(made.id)
              ? cur : [...cur, made.id]);
          }} />
      )}
      {open && rankingId !== -1 && !configuring && (
        <div {...backdrop} ref={frameRef} tabIndex={-1}
          style={{ position: "fixed", inset: 0, zIndex: LAYER.session,
                   outline: "none",
                   background: "var(--scrim-3)", display: "flex",
                   flexDirection: "column", padding: "28px 36px" }}>
          {/* Header: which axis, loudly — the pace makes everything else
              ambient, but which question is being asked must never be. */}
          <div onMouseDown={(e) => e.stopPropagation()}
            style={{ display: "flex", alignItems: "center", gap: 12,
                     color: "var(--on-scrim)", marginBottom: 16 }}>
            <Icon name="leaderboard" size={18} />
            {/* WHAT THE SESSION HAS DONE stays up here; WHICH QUESTION IS
                BEING ASKED moved down between the pictures and the keys —
                see the label below. The two were side by side and read as
                one string, and the one that matters at every press is the
                question. */}
            {/* Two different units, so each carries its own noun. The
                session counts what it has ANSWERED — which is pairs while
                one axis is asked and comparisons once several are, since
                one pair is then three of them. */}
            <span style={{ fontSize: "var(--fs-3)", opacity: 0.75,
                           fontVariantNumeric: "tabular-nums" }}>
              {axes.length > 1
                ? tn({ one: "1 comparison this session",
                       other: "{n} comparisons this session" }, session)
                : tn({ one: "1 pair this session",
                       other: "{n} pairs this session" }, session)}
              {pair && pool.current != null
                ? ` · ${tn({ one: "1 item to compare",
                             other: "{n} items to compare" },
                           pool.current)}` : ""}
            </span>
            <span style={{ flex: 1 }} />
            {rankingId !== -1 && summary == null && (
              // EVERY setting, mid-session: the chooser again, over the run,
              // and Continue takes over from the next pair. The sheet steps
              // aside while it is up — the dialog layer sits under the
              // session's, so it cannot be shown over it. The chooser is
              // seeded from the session: its axes, and the kind the scope
              // was stamped with (a session opened straight onto an axis
              // was never asked, and reads as pictures).
              <span className="hoverable"
                onClick={() => {
                  setPicked(axes.filter((x) => x > 0));
                  setPickedPools({ ...poolsRef.current });
                  const k = scopeRef.current?.kind;
                  if (k === "image" || k === "video") setAskKind(k);
                  setConfiguring(true);
                }}
                title={t("Change this session's settings")}
                style={{ display: "flex", alignItems: "center", gap: 5,
                         padding: "4px 10px", borderRadius: "var(--r-3)",
                         cursor: "pointer", color: "var(--on-scrim)", fontSize: "var(--fs-3)",
                         border: "1px solid var(--on-scrim-4)" }}>
                <Icon name="tune" size={14} />
                {t("Settings")}
              </span>
            )}
            {rankingId !== -1 && pair?.a && pair.b && (
              // The standings without ending the session — what Tab also
              // toggles. A TOGGLE, lit while they are up: the way back is
              // the button that opened them.
              <span className="hoverable"
                onClick={() => {
                  if (summary != null) setSummary(null);
                  else void openSummary();
                }}
                title={t("Show or hide the standings (Tab)")}
                style={{ display: "flex", alignItems: "center", gap: 5,
                         padding: "4px 10px", borderRadius: "var(--r-3)",
                         cursor: "pointer", color: "var(--on-scrim)", fontSize: "var(--fs-3)",
                         background: summary != null
                           ? "var(--overlay-wash)" : "transparent",
                         border: "1px solid var(--on-scrim-4)" }}>
                <Icon name="format_list_numbered" size={14} />
                {t("Standings")}
              </span>
            )}
            <span className="hoverable" onClick={() => askClose()}
              title={t("End the session (Esc)")}
              style={{ display: "flex", padding: 6, borderRadius: "var(--r-3)",
                       cursor: "pointer", color: "var(--on-scrim)" }}>
              <Icon name="close" size={18} />
            </span>
          </div>

          {summary != null ? (

            /* THE STANDINGS: how the pool stands, best first — reached by an
               exhausted pool, the header's button, or Esc. The scores are
               still stamped at close; this is the read-only preview of what
               the next Esc is about to make true. */
            <div onMouseDown={(e) => e.stopPropagation()}
              style={{ flex: 1, minHeight: 0, overflowY: "auto",
                       display: "flex", flexDirection: "column",
                       alignItems: "center", gap: 14, paddingTop: 6 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12,
                            color: "var(--on-scrim)", fontSize: "var(--fs-4)", opacity: 0.85 }}>
                {pair?.a && pair.b
                  ? t("How this ranking stands so far — best first.")
                  : t("Every pair is judged — here is how they stand.")}
                {pair?.a && pair.b && (
                  <span className="hoverable"
                    onClick={() => setSummary(null)}
                    style={{ display: "flex", alignItems: "center", gap: 5,
                             padding: "3px 10px", borderRadius: "var(--r-3)",
                             cursor: "pointer", fontSize: "var(--fs-3)",
                             border: "1px solid var(--on-scrim-4)" }}>
                    <Icon name="arrow_back" size={14} />
                    {t("Keep rating")} <Cap>Tab</Cap>
                  </span>
                )}
              </div>
              {/* GROUPED BY RATING, best bucket first (the reply's own
                  order): the tag said once per group, not once per card. */}
              {(() => {
                // Per LEAGUE first (the reply's own order), then by
                // rating: a session writing into two pools has two sets of
                // standings, and the pool is said once above each.
                type Group = { bucket: number; rows: NonNullable<typeof summary> };
                const pools: { id: number; name: string; groups: Group[] }[] = [];
                for (const e2 of summary ?? []) {
                  let lg = pools[pools.length - 1];
                  if (!lg || lg.id !== e2.pool_id) {
                    lg = { id: e2.pool_id, name: e2.pool, groups: [] };
                    pools.push(lg);
                  }
                  const last = lg.groups[lg.groups.length - 1];
                  if (last && last.bucket === e2.bucket) last.rows.push(e2);
                  else lg.groups.push({ bucket: e2.bucket, rows: [e2] });
                }
                return pools.flatMap((lg) => [
                  pools.length > 1 ? (
                    <div key={`pool:${lg.id}`}
                      style={{ color: "var(--on-scrim)", fontSize: "var(--fs-4)", fontWeight: 600,
                               opacity: 0.9, marginTop: 6 }}>
                      {lg.name || t("Default")}
                    </div>
                  ) : null,
                  ...lg.groups.map((g) => (
                  <div key={`${lg.id}:${g.bucket}`}
                    style={{ display: "flex", alignItems: "flex-start",
                             gap: 14, maxWidth: 900, width: "100%",
                             justifyContent: "center" }}>
                    {/* A fixed chip COLUMN with the chip pushed to its right
                        edge — chips of different widths otherwise stagger
                        down the page, since each row centres as a whole. */}
                    <span style={{ flex: "0 0 130px", minWidth: 0,
                                   display: "flex",
                                   justifyContent: "flex-end",
                                   marginTop: 34 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-3)",
                                     color: "var(--on-scrim)",
                                     background: "var(--overlay-wash)",
                                     borderRadius: "var(--r-1)", padding: "2px 8px",
                                     maxWidth: "100%", overflow: "hidden",
                                     textOverflow: "ellipsis",
                                     whiteSpace: "nowrap" }}>
                        {g.bucket}
                      </span>
                    </span>
                    {/* `flex: 1` so every row spans the same width — a row
                        sized to its own thumbs re-centres, and the chip
                        column drifts with it. */}
                    <div style={{ display: "flex", flexWrap: "wrap",
                                  gap: 10, flex: 1, minWidth: 0 }}>
                      {g.rows.map((e2) => (
                        <div key={`${e2.pool_id}:${e2.ref.item_id}`}
                          style={{ display: "flex",
                                   flexDirection: "column",
                                   alignItems: "center", gap: 4,
                                   width: 118 }}>
                          {e2.ref.file_id != null && (
                            <img
                              src={api.thumbUrl(e2.ref.file_id, 0,
                                                e2.ref.thumb_token)}
                              style={{ width: 118, height: 90,
                                       objectFit: "cover", borderRadius: "var(--r-5)",
                                       border:
                                         "1px solid var(--on-scrim-4)"
                                     }} />
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                  )),
                ]);
              })()}
            </div>
          ) : pair && pair.a && pair.b ? (
            <div onMouseDown={(e) => e.stopPropagation()}
              style={{ flex: 1, minHeight: 0, display: "flex", gap: 18 }}>
              <RateCard side={pair.a} keycap="←" busy={busy}
                marked={dismissed.has(pair.a.item_id)}
                anyMarked={dismissed.size > 0}
                onPick={() => void decide("a")}
                onRotated={() => bumpLibrary()}
                onDismiss={() => void toggleDismiss(pair.a as RankingItemRef)} />
              <RateCard side={pair.b} keycap="→" busy={busy}
                marked={dismissed.has(pair.b.item_id)}
                anyMarked={dismissed.size > 0}
                onPick={() => void decide("b")}
                onRotated={() => bumpLibrary()}
                onDismiss={() => void toggleDismiss(pair.b as RankingItemRef)} />
            </div>
          ) : (
            <div onMouseDown={(e) => e.stopPropagation()}
              style={{ flex: 1, display: "flex", alignItems: "center",
                       justifyContent: "center", color: "var(--on-scrim)",
                       fontSize: "var(--fs-4)", opacity: 0.85, textAlign: "center" }}>
              {failed != null ? (
                <SessionTrouble
                  message={t("The next pair could not be loaded.")}
                  detail={failed} onRetry={() => void fetchPair()} t={t} />
              ) : pair == null ? t("Loading…")
                : t("Nothing to compare here — this scope holds fewer than two items to rate.")}
            </div>
          )}

          {/* WHICH QUESTION IS BEING ASKED, centred between the pictures and
              the keys that answer it — where the eye already is at the
              moment of pressing one, and where it cannot be read as part of
              the session's own counters. Loud, because the pace makes
              everything else ambient and this never may be: on a run of
              three axes the same pair comes back twice looking identical,
              and the axis is the whole of what changed.
              Not a switcher: the order was chosen in the chooser, and
              picking an axis by hand mid-pair would leave the others
              unanswered for it. */}
          <div onMouseDown={(e) => e.stopPropagation()}
            style={{ display: "flex", justifyContent: "center",
                     alignItems: "center", gap: 10, marginTop: 14,
                     color: "var(--on-scrim)" }}>
            <span style={{ fontSize: "var(--fs-5)", fontWeight: 600 }}>
              {activeRanking?.name}
            </span>
            {/* WHICH LEAGUES the judgement lands in, where the ranking has
                more than one — the pool is part of the question. */}
            {activeRanking && activeId != null
              && (activeRanking.pools?.length ?? 0) > 1 && (
              <span style={{ fontSize: "var(--fs-3)", opacity: 0.75 }}>
                {(poolsRef.current[activeId] ?? []).map((lid) =>
                  activeRanking.pools.find((l) => l.id === lid)?.name
                    || t("Default")).join(", ")}
              </span>
            )}
            {/* THE OTHER AXES THIS PAIR IS STILL DUE, one pip each: what is
                being asked now, what has been answered for it, and how much
                is left. A row of names would say the same thing and take the
                width, so the names are the tooltip. */}
            {axes.length > 1 && (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}
                title={axes.map((x) => {
                  const r = (rankings ?? []).find((y) => y.id === x);
                  const lids = poolsRef.current[x] ?? [];
                  const names = lids.map((lid) =>
                    r?.pools.find((l) => l.id === lid)?.name || t("Default"));
                  return (r?.name || "")
                    + (names.length ? ` (${names.join(", ")})` : "");
                }).join(" → ")}>
                {axes.map((x, i) => (
                  <span key={x} style={{
                    width: i === cursor ? 16 : 6, height: 6, borderRadius: 3,
                    background: i === cursor ? "var(--accent)" : "var(--on-scrim)",
                    opacity: i === cursor ? 1 : (i < cursor ? 0.75 : 0.3) }} />
                ))}
                <span style={{ fontSize: "var(--fs-3)", opacity: 0.8, marginLeft: 4,
                               fontVariantNumeric: "tabular-nums" }}>
                  {cursor + 1} / {axes.length}
                </span>
              </span>
            )}
          </div>

          {/* The keycap footer: a shortcut that lives only in a tooltip is
              one nobody finds. Only the keys that DO something in the
              current state — a cap for a dead key teaches a lie.
              CLICKABLE, which is not decoration: with a picture ticked "not
              applicable" the arrows are refused (there is nothing left in
              the pair to compare) and Space is the only way on, so the one
              way on has to be reachable with the hand that ticked the box.
              A cap with no action stays plain text. */}
          <div onMouseDown={(e) => e.stopPropagation()}
            style={{ display: "flex", justifyContent: "center", gap: 22,
                     marginTop: 10, color: "var(--on-scrim-2)",
                     fontSize: "var(--fs-3)" }}>
            {summary == null && pair && pair.a && pair.b ? (<>
              {/* A CAP FOR A REFUSED KEY IS A LIE, so the arrows dim with
                  everything else the moment a picture is ticked "not
                  applicable" — and the one key that still does something
                  takes the accent and says what it is FOR. Ticking one side
                  left a screen on which nothing responded: the pictures
                  refuse the click, the arrows and the tie refuse the press,
                  and the way on was a keycap somebody had to know already. */}
              <span style={{ opacity: dismissed.size > 0 ? 0.4 : 1 }}>
                <Cap>←</Cap> <Cap>→</Cap> {t("pick the better one")}
              </span>
              <KeyAction onClick={() => void decide("tie")} disabled={dismissed.size > 0}>
                <Cap>↓</Cap> {t("tie")}
              </KeyAction>
              {/* The same two keys, saying the other thing about a side —
                  which is why it is a MODIFIER and not a letter of its own:
                  the arrow already names which picture. Never refused, and
                  never dim: it is the one answer a ticked pair still has. */}
              <span><Cap>⇧ ←</Cap> <Cap>⇧ →</Cap>{" "}
                {t("not applicable")}</span>
              <KeyAction onClick={() => void decide("skip")}
                lit={dismissed.size > 0}>
                <Cap>S</Cap>{" "}
                {dismissed.size === 0 ? t("skip")
                  : cursor + 1 < axes.length ? t("next ranking")
                    : t("next pair")}
              </KeyAction>
              <KeyAction onClick={() => useUI.getState().openQuickLook(
                  [pair.a!.item_id, pair.b!.item_id])}>
                <Cap>Space</Cap> {t("preview")}
              </KeyAction>
              <KeyAction onClick={() => void undo()}
                disabled={judged.size === 0}>
                <Cap>↑</Cap> {t("undo")}
              </KeyAction>
              <KeyAction onClick={() => void openSummary()}>
                <Cap>Tab</Cap> {t("standings")}
              </KeyAction>
              <KeyAction onClick={() => askClose()}>
                <Cap>Esc</Cap> {t("end")}
              </KeyAction>
            </>) : (<>
              {judged.size > 0 && (
                <KeyAction onClick={() => void undo()}>
                  <Cap>↑</Cap> {t("undo")}
                </KeyAction>
              )}
              {pair?.a && pair.b && (
                <KeyAction onClick={() => setSummary(null)}>
                  <Cap>Tab</Cap> {t("keep rating")}
                </KeyAction>
              )}
              <KeyAction onClick={() => askClose()}>
                <Cap>Esc</Cap> {t("end")}
              </KeyAction>
            </>)}
          </div>

          {/* THE ONE QUESTION IN FRONT OF THE WAY OUT — the shared sheet. Nothing
              is lost by ending (every answer was written as it was given), so
              the sentence says what ending does rather than warning. */}
          {confirmEnd && (
            <ConfirmModal t={t}
              title={t("End this session?")}
              body={tn({ one: "1 comparison is recorded. The scores update when the session ends.",
                        other: "{n} comparisons are recorded. The scores update when the session ends." },
                      session)}
              cancel={t("Keep rating")}
              answer={{ label: t("End session") }}
              onResult={(r) => { setConfirmEnd(false); if (r === "answer") void close(); }} />
          )}
        </div>
      )}
      {note && (
        <ActionToast text={note} autoDismissMs={4000} onDismiss={() => setNote(null)} />
      )}
    </>,
    document.body,
  );
}

function RateCard({ side, keycap, busy, marked, anyMarked, onPick,
                    onDismiss, onRotated }: {
  side: RankingItemRef;
  keycap: string;
  busy: boolean;
  /** This picture is marked "not applicable" — a TICK, not an act. */
  marked: boolean;
  /** Either of the pair is marked, so there is no comparison left to make. */
  anyMarked: boolean;
  onPick: () => void;
  onDismiss: () => void;
  /** Refresh the library after a rotation — the card carries the buttons. */
  onRotated: () => void;
}) {
  const t = useT();
  // The PICTURE half is the shared JudgeCard (one card for both session
  // overlays); what this wraps around it is the rating footer — the keycap,
  // the name, and the Not applicable checkbox.
  return (
    <div style={{ flex: "1 1 0", minWidth: 0, display: "flex",
                  flexDirection: "column", gap: 8,
                  // A marked picture recedes: it is still on screen (that is
                  // how it is un-marked) and it is no longer in the running.
                  opacity: marked ? 0.65 : 1 }}>
      <JudgeCard side={side} busy={busy || anyMarked} onPick={onPick}
        onRotated={onRotated}
        title={anyMarked
          ? t("Not applicable is ticked — untick it, or skip with S")
          : t("This one is better")} />
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    color: "var(--on-scrim-2)", fontSize: "var(--fs-3)" }}>
        <Cap>{keycap}</Cap>
        <span style={{ flex: 1, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {side.name || side.uid}
        </span>
        {/* A CHECKBOX, so both pictures can carry it at once — which is the
            ordinary case (a pair the axis says nothing about) and used to
            mean marking one, taking whatever pair came back, and hunting for
            the other one again. Ticking both leaves the pair by itself. */}
        <span className="hoverable" role="checkbox" aria-checked={marked}
          onClick={busy ? undefined : onDismiss}
          title={t("This axis does not apply to this picture — never offer it again")}
          style={{ display: "flex", alignItems: "center", gap: 5,
                   padding: "3px 8px", borderRadius: "var(--r-2)", cursor: "pointer",
                   color: marked ? "var(--selected-text)" : undefined,
                   background: rowBackground(marked, "transparent"),
                   border: `1px solid ${marked ? "var(--accent)"
                                              : "var(--on-scrim-4)"}` }}>
          <Icon name={marked ? "check_box" : "check_box_outline_blank"}
                size={14} />
          {t("Not applicable")}
        </span>
      </div>
    </div>
  );
}
