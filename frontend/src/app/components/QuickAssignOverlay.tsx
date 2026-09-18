/** Stamp a saved tag set from the keyboard: Q, then a digit — or, over a
 * selection, the bare digit alone.
 *
 * **Q** raises the numbered Quick-Assign sets over a dimmed library — the
 * QuickTagOverlay's shape, for the QuickTagOverlay's reason: the sidebar can
 * do all of this one mouse journey at a time, which is the wrong tool halfway
 * down a hundred pictures. Each row is a set under its number key; pressing
 * the digit (or clicking the row) stamps it on the selection and puts the
 * overlay away.
 *
 * THE COLOURS ANSWER THE QUESTION THE KEY IS ABOUT TO ACT ON: green means
 * every selected item already carries the whole set — so the press REMOVES it,
 * and the row says so — and yellow means some of the selection carries some of
 * it (the sidebar's mixed-state convention). Plain means the press simply
 * assigns. Both are computed from the loaded pages' `direct_tags`, so they are
 * skipped over a heavy selection, and over the WHOLE VIEW — with nothing
 * selected the overlay means everything the grid is showing, exactly like T,
 * where no colour can be honest (the view's items are mostly not loaded) and a
 * press only ever assigns.
 *
 * The sets themselves are made, edited and numbered in the sidebar's Quick
 * Assign panel; `Shift+Q` over there stamps the SELECTED set directly, and
 * falls through to this overlay when no set is selected.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Chip } from "../../shared/Chip";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api, GroupNode, ItemOut } from "../api";
import { LAYER } from "../../shared/layers";
import { Icon } from "../../shared/Icon";
import { ActionToast } from "./shared/ActionToast";
import { overPageExcept, useUI } from "../store";
import { useT, useTn } from "../i18n";
import { useLoadedViewItems, useViewScope } from "../useItems";
import { bumpEdits, bumpItem, bumpLibrary } from "../invalidation";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { ThumbStrip, STRIP_MAX } from "./ThumbStrip";
import {
  HEAVY_SELECTION, numberedSets, qaSetDone, qaSetMatch, setIsEmpty,
  type QaSet,
} from "../qaSets";
import { isTypingTarget } from "../../shared/typingTarget";

/** A set's tags as read-only chips — the drawer shows the same sets as live
 *  editors, so this compact form exists for the overlay's rows alone.
 *  `done` names the chips (by their "+name"/"-name"/"g<id>" key) the
 *  selection already carries whole: those go GREY — a solid grey, not a
 *  fainter copy — so a partially-matching row says what the press will
 *  actually add, a membership it would not have to write included.
 *  The text colours are the `-text` variants: these chips sit on the row's
 *  green and yellow surfaces, where the plain hues are hard to read. */
export function QaChipRow({ set, done, groupNames }: {
  set: QaSet; done?: Set<string>;
  /** Group id → name, for the set's membership chips. */
  groupNames?: Map<number, string>;
}) {
  const chip = (name: string, neg: boolean) => {
    const key = (neg ? "-" : "+") + name;
    const grey = done?.has(key) ?? false;
    return (
      <span
        key={key}
        style={{
          fontFamily: "var(--mono)", fontSize: "var(--fs-2)", padding: "1px 6px",
          borderRadius: "var(--r-1)",
          background: grey ? "var(--muted-dim)"
            : neg ? "var(--red-dim)" : "var(--green-dim)",
          color: grey ? "var(--muted-2)"
            : neg ? "var(--red-text)" : "var(--green-text)",
          whiteSpace: "nowrap",
          textDecoration: neg ? "line-through" : "none",
        }}
      >
        {name}
      </span>
    );
  };
  return (
    <span style={{ flex: 1, minWidth: 0, display: "flex", flexWrap: "wrap",
                   gap: 4, overflow: "hidden" }}>
      {set.pos.map((n) => chip(n, false))}
      {set.neg.map((n) => chip(n, true))}
      {/* Membership chips in the ACCENT tint — a group is not a tag, and the
          folder glyph plus the third colour is what says so at a glance. */}
      {set.groups.map((g) => (
        <Chip key={`g${g}`} size="md" icon="folder"
          tone={done?.has(`g${g}`) ? "neutral" : "accent"}>
          {groupNames?.get(g) ?? `#${g}`}
        </Chip>
      ))}
    </span>
  );
}

export function QuickAssignOverlay() {
  const t = useT();
  const tn = useTn();
  const open = useUI((s) => s.qaOverlay);
  const setQaOverlay = useUI((s) => s.setQaOverlay);
  const qaSets = useUI((s) => s.qaSets);
  const selectedItems = useUI((s) => s.selectedItems);
  const anchorItem = useUI((s) => s.anchorItem);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const cameFrom = useRef<HTMLElement | null>(null);
  const openedOnSelection = useRef(false);
  const wasOpen = useRef(false);

  // ---- WHAT IS BEING STAMPED ------------------------------------------------
  // The selection, or — with nothing selected — the VIEW, exactly as the T
  // overlay reads it (`useViewScope`: the scope to POST, never the ids).
  const view = useViewScope();
  const viewTotal = useRef<number | null>(null);
  viewTotal.current = view.total;
  const wholeView = selectedItems.length === 0;
  const count = wholeView ? (view.total ?? 0) : selectedItems.length;

  const loaded = useLoadedViewItems();
  const byId = useMemo(
    () => new Map(loaded.map((i) => [i.id, i.direct_tags])), [loaded]);
  const groupsById = useMemo(
    () => new Map(loaded.map((i) => [i.id, i.group_ids ?? []])), [loaded]);
  const { data: groupTree } = useQuery({ queryKey: ["groups"],
                                         queryFn: api.groups });
  const groupNames = useMemo(() => {
    const m = new Map<number, string>();
    const walk = (ns: GroupNode[]) => {
      for (const n2 of ns) { m.set(n2.id, n2.name); walk(n2.children ?? []); }
    };
    walk(groupTree ?? []);
    return m;
  }, [groupTree]);

  // The rows: only NUMBERED sets — a set without a number has no key to press,
  // so it stays a drawer-only thing until it is given one.
  const rows = useMemo(() => numberedSets(qaSets), [qaSets]);
  // One match per row — its state plus which of its tags the whole selection
  // already carries — or null where no colour can be honest: the whole view
  // (its items are mostly not loaded) and a heavy selection (the same cap
  // every per-item aggregate in the sidebar respects). Computed while the
  // overlay is CLOSED too: a bare digit stamps without opening it, and the
  // toggle (a fully-matching set's digit removes) reads the same answer.
  const matches = useMemo(() => {
    if (wholeView || selectedItems.length > HEAVY_SELECTION) return null;
    const per = selectedItems.map((id) => byId.get(id) ?? []);
    const perGroups = selectedItems.map((id) => groupsById.get(id) ?? []);
    return rows.map((r) => ({ state: qaSetMatch(per, r, perGroups),
                              done: qaSetDone(per, r, perGroups) }));
  }, [rows, wholeView, selectedItems, byId, groupsById]);

  // ---- open / close ---------------------------------------------------------
  // Registered ONCE; everything it needs is read imperatively (the store) or
  // through refs (`applyRef`), the same discipline every once-registered
  // window handler here follows.
  const applyRef = useRef<(num: number) => void>(() => {});
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const st = useUI.getState();
      // The feature's master switch (the drawer header's ⋯ menu): off, every
      // quick-assign key is inert — nine bare digits that write tags are
      // exactly the kind of thing that wants one.
      if (!st.qaEnabled) return;
      const isQ = e.key === "q" || e.key === "Q";
      if (!st.qaOverlay) {
        const isDigit = !e.shiftKey && e.key >= "1" && e.key <= "9";
        if (!isQ && !isDigit) return;
        if (overPageExcept("qa")()) return;
        if (isTypingTarget(e)) return;
        // A BARE DIGIT stamps its set without the overlay — the overlay is
        // where you look, the digits are what you press once you know the
        // numbers. Selection only: a digit over nothing must not quietly
        // mean the whole view, which only the overlay (or the button) may
        // offer with the scope said out loud.
        if (isDigit) {
          if (st.selectedItems.length === 0) return;
          e.preventDefault();
          applyRef.current(Number(e.key));
          return;
        }
        // Shift+Q with a selected set is the DIRECT stamp and belongs to the
        // drawer's handler; without one it means the same as Q, which is this.
        if (e.shiftKey && st.qaSelected != null) return;
        // Nothing selected is not nothing to stamp — it means the view, T's
        // rule — but a view with no items in it has nothing to aim at.
        if (st.selectedItems.length === 0
            && !(viewTotal.current && viewTotal.current > 0)) return;
        e.preventDefault();
        st.setQaOverlay(true);
        return;
      }
      // While open: Q and Escape close, a digit stamps its set.
      if (isQ || e.key === "Escape") {
        e.preventDefault();
        st.setQaOverlay(false);
        return;
      }
      if (e.key >= "1" && e.key <= "9") {
        e.preventDefault();
        applyRef.current(Number(e.key));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // WHERE THE KEYBOARD CAME FROM — recorded on open (nothing here takes the
  // focus, so at effect time the active element is still whatever had it when
  // the key was pressed, and for the drawer's button path it is the button).
  // Handed back on close, or the grid's arrow keys go deaf.
  useEffect(() => {
    if (open && !wasOpen.current) {
      cameFrom.current = document.activeElement as HTMLElement | null;
      openedOnSelection.current = useUI.getState().selectedItems.length > 0;
    }
    wasOpen.current = open;
    if (open) return;
    const el = cameFrom.current;
    cameFrom.current = null;
    if (el && el.isConnected) el.focus();
  }, [open]);

  // The SELECTION emptying under it leaves it aimed at nothing — but only when
  // it was aimed at a selection in the first place (T's rule).
  useEffect(() => {
    if (open && openedOnSelection.current && selectedItems.length === 0) {
      setQaOverlay(false);
    }
  }, [open, selectedItems.length, setQaOverlay]);


  // ---- the picture(s) above the rows (the T overlay's shape) ----------------
  const targetId = selectedItems.includes(anchorItem ?? -1)
    ? (anchorItem as number) : selectedItems[0];
  const inGrid = useMemo(
    () => loaded.find((i) => i.id === targetId) ?? null, [loaded, targetId]);
  const { data: fetched } = useQuery({
    queryKey: ["item", targetId],
    queryFn: () => api.item(targetId as number),
    enabled: open && !wholeView && targetId != null && !inGrid,
  });
  const item: ItemOut | null = inGrid ?? fetched ?? null;
  const stripItems = useMemo(() => {
    if (wholeView) return view.first.slice(0, STRIP_MAX);
    const by = new Map(loaded.map((i) => [i.id, i]));
    const out: ItemOut[] = [];
    for (const id of selectedItems) {
      const it = by.get(id);
      if (it) out.push(it);
      if (out.length >= STRIP_MAX) break;
    }
    return out;
  }, [wholeView, view.first, loaded, selectedItems]);

  // ---- the stamp ------------------------------------------------------------
  const apply = async (set: QaSet, match: "full" | "partial" | "none" | null) => {
    if (busy || setIsEmpty(set)) return;
    const ids = selectedItems;
    const scope = wholeView ? view.req : null;
    setQaOverlay(false);
    if (!scope && ids.length === 0) return;
    // Over a SELECTION a fully-matching set is removed — the toggle the drawer
    // button has always had, announced by the green row. Over the whole view
    // no match is known, so a press only ever assigns.
    const remove = !scope && match === "full";
    setBusy(true);
    let n = ids.length;
    try {
      const r = scope
        ? await api.quickAssignView({
            ...scope, positive: set.pos, negative: set.neg,
            assign_groups: set.groups, remove: false,
          })
        : await api.quickAssign({
            item_ids: ids, positive: set.pos, negative: set.neg,
            assign_groups: set.groups, remove,
          });
      n = r.count;
    } finally {
      setBusy(false);
      // A whole-view write touches items this page has never heard of, so the
      // per-item bump cannot cover it: the sweep is what refreshes the grid.
      if (scope) bumpLibrary(); else for (const id of ids) bumpItem(id);
      bumpEdits();
      setNote(remove
        ? tn({ one: "Removed the quick assign set from 1 item",
               other: "Removed the quick assign set from {n} items" }, n)
        : tn({ one: "Applied the quick assign set to 1 item",
               other: "Applied the quick assign set to {n} items" }, n));
    }
  };
  applyRef.current = (num: number) => {
    const i = rows.findIndex((r) => r.num === num);
    if (i < 0) return;
    void apply(rows[i], matches ? matches[i].state : null);
  };

  // ONE item gets the FULL-RESOLUTION picture, not its thumbnail — the quick
  // tag overlay's rule, and this is the same question one gesture along: what
  // the digits are about to stamp is what somebody is looking at, and a
  // ~300 px thumb blown up to the preview box was a guess. A film keeps the
  // thumb — its file is not something an <img> can show.
  const thumb = item?.active_file_id != null
    ? (item.kind === "video"
        ? api.thumbUrl(item.active_file_id, item.rotation, item.thumb_token)
        : api.fileUrl(item.active_file_id, item.rotation))
    : null;
  const backdrop = useBackdropDismiss(() => setQaOverlay(false));

  if (!open) {
    // The confirmation outlives the overlay: it is what says the write landed,
    // and by then there is nothing else on screen about it.
    return note ? (
      <ActionToast autoDismissMs={4000}
        text={note}
        icon="check"
        actionLabel={t("OK")}
        onAction={() => setNote(null)}
        dismissTitle={t("Dismiss")}
        onDismiss={() => setNote(null)}
      />
    ) : null;
  }

  return createPortal(
    <div
      {...backdrop}
      style={{
        position: "fixed", inset: 0, zIndex: LAYER.quickTag,
        background: "var(--scrim-3)", backdropFilter: "blur(3px)",
        display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "flex-start", paddingTop: "12vh", gap: 18,
      }}
    >
      {count === 1 && thumb && (
        <img
          src={thumb}
          alt=""
          style={{
            display: "block", flex: "0 0 auto",
            maxWidth: "min(82vw, 720px)", maxHeight: "42vh",
            borderRadius: "var(--r-7)", boxShadow: "var(--shadow-3)",
            background: "var(--panel-2)",
          }}
        />
      )}
      {count !== 1 && (
        <ThumbStrip items={stripItems} total={count} label={t("items")}
                    size={96} />
      )}
      {/* HOW MANY is the strip's own job and nothing else says it — one
          picture is one picture, and past what the row holds the +N tile
          carries the exact figure however few are loaded. A line of words
          under it said the number a second time and, at one item, said it
          about the picture directly above. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8,
                    width: "min(90vw, 560px)", maxHeight: "50vh",
                    overflowY: "auto" }}>
        {rows.length === 0 && (
          <div style={{ textAlign: "center", fontSize: "var(--fs-4)",
                        color: "var(--on-scrim-3)", padding: "12px 0" }}>
            {t("No numbered quick assign sets — assign numbers in Quick Assign")}
          </div>
        )}
        {rows.map((set, i) => {
          const match = matches ? matches[i] : null;
          const empty = setIsEmpty(set);
          const green = match?.state === "full";
          const yellow = match?.state === "partial";
          return (
            <div
              key={set.num}
              onClick={() => { if (!empty) void apply(set, match?.state ?? null); }}
              // What a colour means rides in the tooltip, not in a sentence
              // on the row — the green removal note used to be trailing text,
              // and it was the loudest thing on the list it explained.
              title={green
                ? t("Already on every selected item — press to remove")
                : yellow
                  ? t("Some selected items carry part of this set")
                  : undefined}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                boxSizing: "border-box", padding: "9px 12px", borderRadius: "var(--r-7)",
                // The tint is MIXED INTO the surface rather than laid over
                // the dim backdrop: a thin rgba wash there read as a broken
                // half-transparent row beside the plain rows' solid one, and
                // an empty row dimmed by whole-row `opacity` was a third
                // level of see-through. Every row is the same opaque
                // surface; only its colour differs.
                background: green
                  ? "color-mix(in srgb, var(--green) 24%, var(--surface-float))"
                  : yellow
                    ? "color-mix(in srgb, var(--yellow) 20%, var(--surface-float))"
                    : "var(--surface-float)",
                // No per-row shadow: eight rows each casting a large soft
                // black one smeared into a dark slab behind the list — over
                // a backdrop that is already dimmed, the border is enough.
                border: `1px solid ${green ? "var(--green)"
                  : yellow ? "var(--yellow)" : "var(--menu-border)"}`,
                cursor: empty ? "default" : "pointer",
              }}
            >
              {/* The key cap wears the row's colour too — it is the control
                  the colour is a claim about. */}
              <kbd style={{
                flex: "0 0 auto", minWidth: 22, textAlign: "center",
                padding: "2px 5px", borderRadius: "var(--r-2)",
                border: `1px solid ${green ? "var(--green)"
                  : yellow ? "var(--yellow)" : "var(--border-strong)"}`,
                background: green
                  ? "color-mix(in srgb, var(--green) 32%, var(--panel-2))"
                  : yellow
                    ? "color-mix(in srgb, var(--yellow) 28%, var(--panel-2))"
                    : "var(--panel-2)",
                color: empty ? "var(--muted-2)" : "var(--text)",
                fontFamily: "var(--mono)", fontSize: "var(--fs-3)", fontWeight: 700,
                lineHeight: "16px",
              }}>{set.num}</kbd>
              {empty ? (
                <span style={{ fontSize: "var(--fs-3)", color: "var(--muted-2)" }}>
                  {t("No tags yet")}
                </span>
              ) : (
                // Greying what is already carried is only said on a PARTIAL
                // row — on a green one every chip would be grey, which reads
                // as a disabled row rather than a removable one.
                <QaChipRow set={set} done={yellow ? match?.done : undefined}
                  groupNames={groupNames} />
              )}
            </div>
          );
        })}
      </div>
    </div>,
    document.body,
  );
}
