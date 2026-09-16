/** Caption the selection from the keyboard.
 *
 * **C** is T's cousin one field along: one box over a dimmed library, no
 * chrome, no buttons, nothing to reach the mouse for. What differs is what a
 * caption IS — a sentence rather than a list of words — so the field is a
 * TEXTAREA and the keys swap round: **Enter is a newline** and
 * **⌘/Ctrl+Enter applies**, because a caption that ended on the first Return
 * would be a caption nobody could write a second line of. Escape throws it
 * away.
 *
 * **It needs a SELECTION, and pressing C with nothing selected does
 * nothing.** T means the whole view there, and deliberately: "tag everything
 * I am looking at" is a real thing to want. One sentence about every picture
 * in a library is not — a caption is a description of a particular picture,
 * and the bulk endpoint says the same thing by capping at 500 items.
 *
 * **Captions only, never instructions.** An instruction is about how a
 * picture was MADE from other pictures, so it is nothing without its
 * references — and there is nowhere here to name them. The Instructions tab
 * is where one is written, with a grid to drag them in from.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ItemOut } from "../api";
import { LAYER } from "../../shared/layers";
import { ActionToast } from "./shared/ActionToast";
import { overPageExcept, useUI } from "../store";
import { useT, useTn } from "../i18n";
import { ThumbStrip, STRIP_MAX } from "./ThumbStrip";
import { useLoadedViewItems } from "../useItems";
import { bumpEdits, bumpItem } from "../invalidation";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { isTypingTarget } from "../../shared/typingTarget";

/** What one request may carry — the server's own cap, said here so the
 *  overlay can explain itself rather than answering 413. */
const BULK_CAP = 500;

export function QuickCaptionOverlay() {
  const selectedItems = useUI((s) => s.selectedItems);
  const anchorItem = useUI((s) => s.anchorItem);
  const t = useT();
  const tn = useTn();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const cameFrom = useRef<HTMLElement | null>(null);

  /** Open it, from the key or from the menu — one place, so the two cannot
   *  drift into two ideas of when it may appear. */
  const start = () => {
    if (useUI.getState().selectedItems.length === 0) return;
    cameFrom.current = document.activeElement as HTMLElement | null;
    setText("");
    setOpen(true);
  };
  const startRef = useRef(start);
  startRef.current = start;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Not over anything — a dialog, the item window, a session, one of
      // the other keyboard overlays: this one holds a field, so it may not
      // open under or over another that does.
      if (overPageExcept("quickCaption")()) return;
      if (e.key !== "c" && e.key !== "C") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e)) return;
      if (useUI.getState().selectedItems.length === 0) return;
      e.preventDefault();
      startRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The quick-actions menu opens it through a bumped counter, T's rule and
  // T's trap: the counter OUTLIVES this component (the overlay is mounted
  // only over the library), so what the effect answers to is a CHANGE and
  // never the value — seeded from the current one, a fresh mount reads a
  // standing request as one it has already served.
  const signal = useUI((s) => s.quickCaptionSignal);
  const served = useRef(signal);
  useEffect(() => {
    if (signal === served.current) return;
    served.current = signal;
    if (overPageExcept("quickCaption")()) return;
    startRef.current();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signal]);

  // Hand the focus back on the way out, however it was dismissed — the field
  // takes it while this is open, and on unmount it falls to the body, which
  // is how the grid went deaf to its own arrow keys.
  useEffect(() => {
    if (open) return;
    const el = cameFrom.current;
    cameFrom.current = null;
    if (el && el.isConnected) el.focus();
  }, [open]);

  const setQuickCaptionOpen = useUI((s) => s.setQuickCaptionOpen);
  useEffect(() => {
    setQuickCaptionOpen(open);
    return () => setQuickCaptionOpen(false);
  }, [open, setQuickCaptionOpen]);


  // The selection emptying under it (a delete elsewhere) leaves it aimed at
  // nothing.
  useEffect(() => {
    if (open && selectedItems.length === 0) setOpen(false);
  }, [open, selectedItems.length]);

  const count = selectedItems.length;
  const tooMany = count > BULK_CAP;
  // The anchor is what a click last landed on, so it is the one the person is
  // thinking of; the first selected stands in for a selection made otherwise.
  const targetId = selectedItems.includes(anchorItem ?? -1)
    ? (anchorItem as number) : selectedItems[0];
  const loaded = useLoadedViewItems();
  const inGrid = useMemo(
    () => loaded.find((i) => i.id === targetId) ?? null, [loaded, targetId]);
  const { data: fetched } = useQuery({
    queryKey: ["item", targetId],
    queryFn: () => api.item(targetId as number),
    enabled: open && count === 1 && targetId != null && !inGrid,
  });
  const item: ItemOut | null = inGrid ?? fetched ?? null;
  const stripItems = useMemo(() => {
    const by = new Map(loaded.map((i) => [i.id, i]));
    const out: ItemOut[] = [];
    for (const id of selectedItems) {
      const it = by.get(id);
      if (it) out.push(it);
      if (out.length >= STRIP_MAX) break;
    }
    return out;
  }, [loaded, selectedItems]);

  // ONE item gets the FULL-RESOLUTION picture — the preview is what somebody
  // reads before describing it, and a thumbnail blown up to this size is a
  // guess. A film keeps the thumb; its file is not something an <img> shows.
  const thumb = item?.active_file_id != null
    ? (item.kind === "video"
        ? api.thumbUrl(item.active_file_id, item.rotation, item.thumb_token)
        : api.fileUrl(item.active_file_id, item.rotation))
    : null;

  const apply = async () => {
    if (busy) return;
    const ids = selectedItems.slice(0, BULK_CAP);
    const body = text.trim();
    setOpen(false);
    if (!ids.length || !body) return;
    setBusy(true);
    try {
      await api.addCaptionBulk(ids, body);
    } finally {
      setBusy(false);
      for (const id of ids) bumpItem(id);
      bumpEdits();
      setNote(tn({ one: "Captioned 1 item", other: "Captioned {n} items" },
                 ids.length));
    }
  };

  const backdrop = useBackdropDismiss(() => setOpen(false));

  if (!open) {
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
            maxWidth: "min(82vw, 720px)", maxHeight: "38vh",
            borderRadius: "var(--r-7)", boxShadow: "var(--shadow-3)",
            background: "var(--panel-2)",
          }}
        />
      )}
      {count !== 1 && (
        <ThumbStrip items={stripItems} total={count} label={t("items")}
                    size={96} />
      )}
      <div style={{ width: "min(90vw, 560px)", position: "relative" }}>
        <textarea
          ref={boxRef}
          autoFocus
          value={text}
          rows={4}
          placeholder={t("A sentence about this picture…")}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // ⌘/Ctrl+Enter applies; a plain Enter is a newline, which is the
            // whole reason this is a textarea. Escape closes — and stops
            // there, or the grid behind would take it as "clear the
            // selection" the moment the overlay let go of it.
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void apply();
            } else if (e.key === "Escape") {
              e.preventDefault();
              e.stopPropagation();
              setOpen(false);
            } else {
              // Every other key is the field's, including the plain letters
              // that are shortcuts out there.
              e.stopPropagation();
            }
          }}
          style={{
            width: "100%", boxSizing: "border-box", resize: "vertical",
            padding: "12px 14px", borderRadius: "var(--r-7)",
            border: "1px solid var(--border)", background: "var(--panel)",
            color: "var(--text)", fontSize: "var(--fs-5)", lineHeight: 1.45,
            fontFamily: "inherit",
            boxShadow: "var(--shadow-3)", outline: "none",
          }}
        />
        {/* The one line of chrome there is: what the keys do, and — only
            when it applies — that the selection is longer than one request
            may carry. A hint under the field rather than a button row: the
            hands are on the keyboard, which is the point of the overlay. */}
        <div style={{
          marginTop: 8, display: "flex", gap: 10, alignItems: "baseline",
          fontSize: "var(--fs-2)", color: "var(--muted)",
        }}>
          <span>{t("⌘/Ctrl+Enter adds it · Enter is a new line · Esc cancels")}</span>
          {tooMany && (
            <span style={{ color: "var(--yellow-text)" }}>
              {t("The first {n} of the selection", { n: String(BULK_CAP) })}
            </span>
          )}
        </div>
      </div>
    </div>,
    document.body);
}
