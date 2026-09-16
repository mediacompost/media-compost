/** Tag the selection from the keyboard, and from nothing else.
 *
 * **T** opens one text field over a dimmed library — the shape macOS uses for
 * Spotlight — and everything about it is arranged so a hand never leaves the
 * keyboard: a whole edit is typed as one line (`cat -dog !bird`), Enter
 * applies all of it at once and puts the overlay away, Escape throws it away.
 * The sidebar's tag adder can do the same work one field, one tag and one
 * mouse journey at a time, which is exactly what makes it the wrong tool
 * halfway down a hundred pictures.
 *
 * There is no chrome: no title, no buttons, no explanation. The PLACEHOLDER
 * carries the grammar, because that is where somebody is already looking, and
 * the preview above the field answers the only question the field cannot —
 * which pictures this is about. One of them gets its picture; several get a
 * ROW OF THUMBNAILS, because "12 items" over one of the twelve is the overlay
 * showing the wrong thing and saying so in a badge.
 *
 * **With nothing selected it means the VIEW** — every item the grid is
 * showing, loaded or not, which can be the whole library. That travels as a
 * SCOPE rather than as ids (`api.quickAssignView`); a million ids is not
 * something a request body can carry, and enumerating them in the browser
 * would mean paging the library first.
 *
 * The autocomplete is per WORD rather than per field (`tokenAt`), so the line
 * can hold several tags and still complete the one being typed. It behaves as
 * every other tag field in the app does — the first match is highlighted while
 * you type and Enter takes it — and picking one only WRITES it into the line:
 * nothing reaches the library until an Enter with the list closed, which is
 * what makes the list safe to walk with the arrow keys.
 *
 * **A TYPED SPACE IS AN UNDERSCORE**, as it is in every other tag field: a
 * name with a space in it is one the API refuses, and `tiny giant` typed here
 * used to become the two tags `tiny` and `giant` — silently, since both are
 * perfectly good names. What separates two tags is therefore COMMITTING one:
 * taking a suggestion, or taking the "Create" row, writes the space after the
 * name. The stored line is unchanged (whitespace still separates the words
 * `parseQuickTags` reads), and so is the key sequence — type, Enter to
 * complete, Enter to apply. Only the KEYSTROKE is rewritten, never the value:
 * running the rule over the whole field would turn the separators the list
 * has already written into underscores and weld the line into one name.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchTagNameSuggestions, useRemoteSuggestions } from "./TagAutocomplete";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ItemOut } from "../api";
import { LAYER } from "../../shared/layers";
import { ActionToast } from "./shared/ActionToast";
import { overPageExcept, useUI } from "../store";
import { useLang, useT, useTn } from "../i18n";
import { ThumbStrip, STRIP_MAX } from "./ThumbStrip";
import { useLoadedViewItems, useViewScope } from "../useItems";
import { bumpEdits, bumpItem, bumpLibrary } from "../invalidation";
import {
  parseQuickTags, quickTagPlan, splitPrefix, tokenAt, toneOfPrefix } from "../quickTags";
import { tagFieldInput } from "../tags";
import {
  pushHistoryLine, readQuickTagHistory, writeQuickTagHistory,
} from "../quickTagHistory";
import { compactCount } from "../format";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { SUGGEST_CAP, rankTagMatches } from "../tagRank";
import {
  TagSuggestList, TagSuggestionRow, pickedName, useSuggestList,
} from "./TagSuggestList";
import { TagSetBrowseList, useTagSetBrowse } from "./TagSetBrowse";
import { isTypingTarget } from "../../shared/typingTarget";

/** Between the field's bottom edge and the list under it. */
const LIST_GAP = 8;

export function QuickTagOverlay() {
  const selectedItems = useUI((s) => s.selectedItems);
  const anchorItem = useUI((s) => s.anchorItem);
  const t = useT();
  const tn = useTn();
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [caret, setCaret] = useState(0);
  // WHICH suggestion is highlighted is `TagSuggestList`'s: the first MATCH,
  // as in every other tag field in the app, so typing narrows the list and
  // Enter takes what is at the top of it — completing a name is the same two
  // keys here as it is in the sidebar. Enter with the list closed is what
  // applies the line — and the list closes the moment a name is taken, so
  // "cat, Enter, Enter" is type, complete, apply.
  //
  // Hides the list without closing the overlay — Escape, and picking a row.
  // Typing brings it back, which is the only time it has anything new to say.
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);
  // What the last apply did. The overlay is gone by then and a bulk write over
  // a selection changes nothing you can see, so it says so.
  const [note, setNote] = useState<string | null>(null);
  //: The suggestion box, so the highlighted row's popover can be put BESIDE
  //  it rather than over it.
  const listBox = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const cameFrom = useRef<HTMLElement | null>(null);
  // Explicit targets from `requestQuickTag(items)` — the tag-batch session's
  // T aims at the picture on screen there, not at the grid's selection.
  const [override, setOverride] = useState<number[] | null>(null);
  // THE LAST FEW LINES APPLIED, newest first (`quickTagHistory.ts`). Read
  // from storage at every open rather than once at mount: another tab's T
  // writes the same key, and this overlay is mounted for as long as the
  // library is.
  const [history, setHistory] = useState<string[]>([]);

  // T OPENS IT. Plain and unmodified like Space and Q, refused while a field
  // has the focus and while the item window is over the library. With nothing
  // selected it opens on the WHOLE VIEW rather than not opening: "tag
  // everything I am looking at" is a real thing to want, and it is the same
  // gesture.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Not over anything — a dialog, the item window, a session, one of
      // the other keyboard overlays. Not `modalIsOpen`, which is for the
      // page's own handlers: this one may not see itself.
      if (overPageExcept("quickTag")()) return;
      if (e.key !== "t" && e.key !== "T") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e)) return;
      // NOTHING SELECTED IS NOT NOTHING TO TAG: it means the view, which is
      // what the grid is showing. Only a view with no items in it has nothing
      // to aim at, and `viewTotal` is the last answer page 1 gave.
      if (useUI.getState().selectedItems.length === 0
          && !(viewTotal.current && viewTotal.current > 0)) return;
      e.preventDefault();
      // WHERE THE KEYBOARD CAME FROM. The field takes the focus while this is
      // open, and when it unmounts the focus falls to the document body — so
      // the grid, whose arrow keys are a handler on its own scroller, went
      // deaf the moment somebody used this and dismissed it.
      cameFrom.current = document.activeElement as HTMLElement | null;
      openedOnSelection.current = useUI.getState().selectedItems.length > 0;
      setOverride(null);
      setText("");
      setCaret(0);
      setDismissed(false);
      setHistory(readQuickTagHistory());
      setOpen(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // THE TOOLBAR'S QUICK-ACTIONS MENU OPENS IT TOO — through a bumped store
  // counter, because the open state is this component's own. Same guards as
  // the key, minus the ones about the keyboard itself.
  const quickTagSignal = useUI((s) => s.quickTagSignal);
  // THE COUNTER OUTLIVES THIS COMPONENT, so what the effect answers to is a
  // CHANGE and never the value. This overlay is mounted only over the library
  // (it has to be listening before its key is pressed), so switching to the
  // Tags tab UNMOUNTS it and switching back MOUNTS IT FRESH — with the effect
  // running once on mount against a counter that is still whatever the last
  // request left it at. So the overlay re-opened by itself on the way back
  // into the library, for anybody who had opened it from the quick-actions
  // menu at least once (the key does not touch the counter, which is what
  // made it "sometimes"). The ref is seeded from the CURRENT value, so a
  // fresh mount reads the standing request as one it has already served.
  const servedSignal = useRef(quickTagSignal);
  useEffect(() => {
    if (quickTagSignal === servedSignal.current) return;
    servedSignal.current = quickTagSignal;
    // A request naming its items comes from a session overlay's own key (the
    // tag batch T), so the "not over another overlay" guards do not apply —
    // the caller is that overlay, and the targets are explicit.
    const items = useUI.getState().quickTagItems;
    if (items == null) {
      if (overPageExcept("quickTag")()) return;
      if (useUI.getState().selectedItems.length === 0
          && !(viewTotal.current && viewTotal.current > 0)) return;
    } else if (items.length === 0) return;
    cameFrom.current = document.activeElement as HTMLElement | null;
    openedOnSelection.current =
      items == null && useUI.getState().selectedItems.length > 0;
    setOverride(items);
    setText("");
    setCaret(0);
    setDismissed(false);
    setHistory(readQuickTagHistory());
    setOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quickTagSignal]);

  // Hand the focus back on the way out, however it was dismissed — Enter,
  // Escape, the backdrop, or the selection emptying underneath it.
  useEffect(() => {
    if (open) return;
    setOverride(null);
    const el = cameFrom.current;
    cameFrom.current = null;
    if (el && el.isConnected) el.focus();
  }, [open]);

  // Mirror the open state into the store so the Q overlay's handler can
  // refuse its key while this one is up (and vice versa, above).
  const setQuickTagOpen = useUI((s) => s.setQuickTagOpen);
  useEffect(() => {
    setQuickTagOpen(open);
    return () => setQuickTagOpen(false);
  }, [open, setQuickTagOpen]);


  // The SELECTION emptying under it (a delete elsewhere) leaves it aimed at
  // nothing — but only when it was aimed at a selection in the first place.
  // Opened over the whole view there is no selection to lose.
  const openedOnSelection = useRef(false);
  useEffect(() => {
    if (open && openedOnSelection.current && selectedItems.length === 0) {
      setOpen(false);
    }
  }, [open, selectedItems.length]);

  // ---- WHAT IS BEING TAGGED ------------------------------------------------
  // The selection, or — with nothing selected — the VIEW: every item the grid
  // is showing, loaded or not. Those are two different things on the wire and
  // deliberately so (`api.quickAssignView`): a view can be the whole library,
  // and a million ids is not something a request body can carry.
  const view = useViewScope();
  const viewTotal = useRef<number | null>(null);
  viewTotal.current = view.total;
  const targetIds = override ?? selectedItems;
  const wholeView = targetIds.length === 0;
  const count = wholeView ? (view.total ?? 0) : targetIds.length;

  // ---- the picture(s) above the field --------------------------------------
  // The anchor is what a click last landed on, so it is the one the person is
  // thinking of; the first selected stands in for a selection made another way.
  const targetId = targetIds.includes(anchorItem ?? -1)
    ? (anchorItem as number) : targetIds[0];
  const loaded = useLoadedViewItems();
  const inGrid = useMemo(
    () => loaded.find((i) => i.id === targetId) ?? null, [loaded, targetId]);
  // Off-grid (selected from a link, or on a page that has since unloaded) it
  // fetches itself — the same fallback QuickLook makes.
  const { data: fetched } = useQuery({
    queryKey: ["item", targetId],
    queryFn: () => api.item(targetId as number),
    enabled: open && !wholeView && targetId != null && !inGrid,
  });
  const item: ItemOut | null = inGrid ?? fetched ?? null;

  // The pictures the STRIP shows, in the order they are being tagged. Only as
  // many as could ever fit in one row are worth resolving — the rest are the
  // "+N" — so this takes the first `STRIP_MAX` and looks them up among the
  // pages the grid has loaded. A selected item that is not in one of them is
  // simply skipped rather than fetched: the strip says what this is about, and
  // a request per crop to say it is a request too many.
  const stripItems = useMemo(() => {
    if (wholeView) return view.first.slice(0, STRIP_MAX);
    const by = new Map(loaded.map((i) => [i.id, i]));
    const out: ItemOut[] = [];
    for (const id of targetIds) {
      const it = by.get(id);
      if (it) out.push(it);
      if (out.length >= STRIP_MAX) break;
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wholeView, view.first, loaded, targetIds.join(",")]);

  // ---- the word under the caret, and what completes it ---------------------
  const tok = tokenAt(text, caret);
  const { prefix, rest } = splitPrefix(tok.word);
  const needle = tagFieldInput(rest);
  // THE ROWS ARE `useRemoteSuggestions`' — under ["tags", …], so a tag edit
  // sweeps them like every other tag read, and the previous page is held
  // while the next is fetched (React Query answers a NEW key with
  // `undefined`, and on a 200,000-tag catalog an emptied list is most of
  // the time somebody is typing). Fetched only while the sheet is up.
  const { rows, settled } = useRemoteSuggestions(
    open ? needle : "", fetchTagNameSuggestions);
  // The rows answered the DEBOUNCED fragment; re-ranking on the current one
  // keeps the in-flight keystrokes from showing rows that no longer match.
  // The names already on the line are out — except the word under the caret
  // itself, which the parse reads as a tag too and which is the very name
  // being completed.
  const existing = useMemo(() => {
    const s = new Set(parseQuickTags(text).map((o) => o.name));
    s.delete(needle);
    return s;
  }, [text, needle]);
  // THE ROWS SAY WHAT PICKING THEM DOES, read off the word's prefix: `-`
  // removes (grey, slashed), `!` assigns negatively (red), a bare word
  // assigns (green). Aliases stay listed under a removal (owner decision —
  // they were dropped for a round): a picked alias writes its TARGET, so
  // `-1female` picked as an alias removes `1girl`, which is exactly the tag
  // the picture carries.
  const removing = prefix.startsWith("-");
  const tone = toneOfPrefix(prefix);
  const matches = needle
    ? rankTagMatches(rows, needle, existing, SUGGEST_CAP)
    : [];
  // "Create" is offered for a name nothing matches — and picking it only puts
  // the list away. The tag is made by Enter, with the rest of the line.
  //
  // ONLY WHILE THE ANSWER IS THIS FRAGMENT'S. The rows above may be the
  // previous fragment's, held so the list does not blink; reading them for
  // "does this name exist" is a claim about a question nobody has answered
  // yet, and it offered to create tags the library already had — under a
  // list its own filter had just emptied, which is what made the offer the
  // only thing on screen.
  // NO CREATE ROW UNDER A REMOVAL. `-name` takes a tag OFF the pictures, and
  // a tag they cannot carry because it does not exist is not one to make on
  // the way to removing it.
  const canCreate = settled && needle.length > 0 && !prefix.startsWith("-")
    && !rows.some((r) => r.name === needle);
  const listOpen = open && !dismissed && (matches.length + (canCreate ? 1 : 0)) > 0;
  // THE TREE OPENS BY ITSELF ONLY OVER AN EMPTY LINE. Enter with the list
  // closed applies the line, and a tree standing under an empty WORD would
  // take that Enter — so with anything on the line the tree is ARMED by an
  // ArrowDown over an empty word and stands down the moment anything is
  // typed; over an empty line there is nothing Enter could apply, and the
  // sets' categories are what there is to choose from (every other tag
  // field's rule). Escape puts it away (`dismissed`), a pick puts it away.
  const [browseArmed, setBrowseArmed] = useState(false);
  useEffect(() => { if (!open) setBrowseArmed(false); }, [open]);
  const browseWanted = open && !dismissed && needle === ""
    && (browseArmed || text.trim() === "");
  const bro = useTagSetBrowse({
    active: browseWanted,
    // Writing the name is `takeName`'s, and so is what follows: the tree
    // back at its root for the next word.
    onPick: (name) => takeName(name),
    // The Close row at the tree's top: Escape's answer, reachable by Enter.
    // The tree opens by itself over an empty line and holds Enter while it
    // is up, so without it the keyboard's way out of the overlay from there
    // was Escape then Enter; with it, Enter puts the tree away and the next
    // Enter applies the (empty) line, which closes the overlay.
    onClose: () => { setBrowseArmed(false); setDismissed(true); },
    // THE HISTORY IS OFFERED OVER AN EMPTY FIELD AND NOWHERE ELSE. Over an
    // empty WORD halfway down a line (the state every pick leaves behind)
    // the line already says something, and a row that would replace it whole
    // is not one to arrow onto by accident.
    history: text.trim() === "" ? history : [],
    onPickHistory: (line) => takeLine(line),
    existing,
  });
  const browseOpen = browseWanted && bro.ready && bro.rows.length > 0;
  const list = useSuggestList({
    matches, create: canCreate ? needle : null, open: listOpen, settled,
    // Picking WRITES the name into the line — the Create row too: what it
    // adds is the SPACE after it, which is the only way to start a second
    // tag. It still makes nothing; the tag is created by the Enter that
    // applies the whole line.
    onPick: (row) => {
      if (row.kind === "action") return;   // this list offers none
      takeName(row.kind === "create" ? row.name : pickedName(row.item));
    },
  });

  /** Take a whole line from the history — the field held nothing, so this
   *  IS the line. Every list is put away afterwards: the line ends on a tag
   *  name, so a flat list left open would take the Enter that applies it,
   *  which is the one key somebody reaching for a remembered line wants. */
  const takeLine = (line: string) => {
    const pos = line.length;
    setText(line);
    setCaret(pos);
    setBrowseArmed(false);
    setDismissed(true);
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(pos, pos);
    });
  };

  /** Write a name into the word the caret is in, keeping its prefix. */
  const takeName = (name: string) => {
    const next = `${text.slice(0, tok.start)}${prefix}${name} ${text.slice(tok.end)}`;
    const pos = tok.start + prefix.length + name.length + 1;
    setText(next);
    setCaret(pos);
    // EVERY PICK — from the typed list or from the tree — leaves the caret
    // on an empty word and puts the TREE back at its root for the next tag
    // (owner decision: a pick from the flat list closed the list for a
    // round, on the argument that a tree standing under an empty word takes
    // the Enter that applies the line; the next tag is the same kind of
    // choice whichever list the last one came from, and Escape then Enter
    // is the way to apply). `dismissed` off, since the pick is what opens
    // it; the tree's cursor back to the start.
    setDismissed(false);
    setBrowseArmed(true);
    bro.reset();
    // The caret has to be moved on the element itself; React only owns value.
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(pos, pos);
    });
  };

  const ops = parseQuickTags(text);
  const apply = async () => {
    if (busy) return;
    const ids = targetIds;
    const scope = wholeView ? view.req : null;
    const plan = quickTagPlan(ops);
    setOpen(false);
    if ((!scope && ids.length === 0) || ops.length === 0) return;
    // WHAT WAS APPLIED IS REMEMBERED, as it was typed — the next open offers
    // it back. Recorded here rather than after the write: the line is what
    // somebody meant, whether or not the request lands.
    const remembered = pushHistoryLine(history, text);
    setHistory(remembered);
    writeQuickTagHistory(remembered);
    setBusy(true);
    // How many it landed on. With a selection that is known up front; over a
    // whole view only the server can say, so the reply is what the sentence
    // reads (it also cannot be assumed to be `view.total`, which was counted
    // before the write).
    let n = ids.length;
    try {
      // Two calls, and only the ones there is work for. `quick-assign` sets an
      // existing assignment's sign rather than adding a second row, which is
      // exactly what "flip it" means here — and removing takes the tag off
      // whatever sign it had.
      if (plan.positive.length || plan.negative.length) {
        const r = scope
          ? await api.quickAssignView({
              ...scope, positive: plan.positive, negative: plan.negative,
              remove: false,
            })
          : await api.quickAssign({
              item_ids: ids, positive: plan.positive, negative: plan.negative,
              remove: false,
            });
        n = r.count;
      }
      if (plan.remove.length) {
        const r = scope
          ? await api.quickAssignView({
              ...scope, positive: plan.remove, negative: [], remove: true,
            })
          : await api.quickAssign({
              item_ids: ids, positive: plan.remove, negative: [], remove: true,
            });
        n = r.count;
      }
    } finally {
      setBusy(false);
      // A whole-view write touches items this page has never heard of, so the
      // per-item bump cannot cover it: the sweep is what refreshes the grid.
      if (scope) bumpLibrary(); else for (const id of ids) bumpItem(id);
      bumpEdits();
      // A line that only takes tags OFF is not "tagged", and one sentence for
      // both would be wrong half the time.
      const added = plan.positive.length > 0 || plan.negative.length > 0;
      setNote(added
        ? tn({ one: "Tagged 1 item", other: "Tagged {n} items" }, n)
        : tn({ one: "Removed tags from 1 item",
               other: "Removed tags from {n} items" }, n));
    }
  };

  // ONE item gets the FULL-RESOLUTION picture, not its thumbnail: the
  // preview is what somebody reads before typing a tag onto it, and a
  // ~300 px thumb blown up to the preview box was a guess. A film keeps the
  // thumb — its file is not something an <img> can show.
  const thumb = item?.active_file_id != null
    ? (item.kind === "video"
        ? api.thumbUrl(item.active_file_id, item.rotation, item.thumb_token)
        : api.fileUrl(item.active_file_id, item.rotation))
    : null;
  const backdrop = useBackdropDismiss(() => setOpen(false));

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
      // Clicking the dim is a way out, and the only one the mouse has —
      // BOTH ENDS on it, so a drag that started inside the field and ended
      // out here is not one (`shared/Backdrop`).
      {...backdrop}
      style={{
        position: "fixed", inset: 0, zIndex: LAYER.quickTag,
        background: "var(--scrim-3)", backdropFilter: "blur(3px)",
        display: "flex", flexDirection: "column", alignItems: "center",
        // Not centred: the field sits in the upper third, where a list opening
        // underneath it has somewhere to go on any window.
        // THE LIST ENDS WHERE THE WINDOW DOES: the column is the window's
        // height, the picture and the strip take what they need, and the
        // list under the field is a flex item that shrinks (`minHeight: 0`)
        // rather than an absolutely positioned box measured from somewhere
        // — `40vh` under a field that a preview had pushed to mid-window ran
        // off the bottom, and a measured rect was right only after the
        // picture had loaded.
        justifyContent: "flex-start", paddingTop: "12vh", paddingBottom: 24,
        boxSizing: "border-box", gap: 18,
      }}
    >
      {/* ONE picture gets its picture; SEVERAL get a row of them. A badge
          reading "12 items" over one of the twelve says the number and shows
          the wrong thing — and which twelve is exactly what somebody is
          checking before they type a tag onto all of them. */}
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
      <div style={{ width: "min(90vw, 560px)", display: "flex", flexDirection: "column",
                    flex: "0 1 auto", minHeight: 0 }}>
        <input
          ref={inputRef}
          autoFocus
          value={text}
          placeholder={t("cat  -dog  !bird")}
          onChange={(e) => {
            // LOWERCASE only — not the tag field's full sanitize, which turns
            // whitespace into underscores. Here a space is the separator
            // between two tags, so that rule would silently weld the line into
            // one name. Each WORD takes the field rules at parse time.
            setText(e.target.value.toLowerCase());
            setCaret(e.target.selectionStart ?? e.target.value.length);
            setDismissed(false);
            setBrowseArmed(false);
          }}
          onKeyUp={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
          onClick={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
          onKeyDown={(e) => {
            if (browseOpen && bro.handleKey(e)) return;
            // SHIFT+SPACE READS THE HIGHLIGHTED TAG, before the rule below
            // turns a space into an underscore — the popover is what that
            // chord means in every other tag field, and here it was typing
            // a character instead.
            if (e.key === " " && e.shiftKey && listOpen
                && list.handleKey(e)) {
              return;
            }
            if (e.key === " " && !e.metaKey && !e.ctrlKey && !e.altKey) {
              // THE TAG FIELD'S OWN RULE, applied to the keystroke rather
              // than to the value: a space types an underscore, so a name
              // that has one can be typed at all. A selection is replaced,
              // like any other typed character.
              e.preventDefault();
              const el = e.currentTarget;
              const a = el.selectionStart ?? text.length;
              const b = el.selectionEnd ?? a;
              const pos = a + 1;
              setText(`${text.slice(0, a)}_${text.slice(b)}`);
              setCaret(pos);
              setDismissed(false);
              // React owns the value, so the caret has to be put back by
              // hand — the same dance `takeName` does.
              requestAnimationFrame(
                () => inputRef.current?.setSelectionRange(pos, pos));
            } else if (e.key === "ArrowDown" && needle === "" && !browseOpen) {
              // Over an empty word, the first ArrowDown asks for the tree.
              e.preventDefault();
              setBrowseArmed(true);
              setDismissed(false);
            } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              // An arrow is also how a dismissed list is asked back.
              setDismissed(false);
              if (!list.handleKey(e)) e.preventDefault();
            } else if (e.key === "Enter" || (e.key === "Tab" && (listOpen || browseOpen))) {
              e.preventDefault();
              // With the list open, the highlighted row — Tab is a second
              // Enter here, the shell's own completion key. Closed, apply.
              if (browseOpen) bro.list.pick();
              else if (listOpen) list.pick();
              else void apply();
            } else if (e.key === "Tab") {
              // With nothing open, Tab asks the list BACK: the typed list
              // for a word, the tree for an empty one — the way back after
              // an Escape put it away, without leaving the keyboard.
              e.preventDefault();
              setDismissed(false);
              if (needle === "") setBrowseArmed(true);
            } else if (e.key === "Escape") {
              e.preventDefault();
              e.stopPropagation();
              // The app's rule wherever a list hangs off a field: the first
              // Escape puts the list away and keeps what was typed, a second
              // throws the whole line away. The list holds Enter while it is
              // open, so this is also how you apply a line whose last word
              // still matches something.
              if (browseOpen) { setBrowseArmed(false); setDismissed(true); }
              else if (listOpen) setDismissed(true);
              else setOpen(false);
            }
          }}
          style={{
            width: "100%", boxSizing: "border-box", height: 54, flex: "0 0 auto",
            padding: "0 18px", border: "none", outline: "none",
            borderRadius: 14, background: "var(--surface-float)",
            color: "var(--text)", fontFamily: "var(--mono)", fontSize: "var(--fs-6)",
            boxShadow: "var(--shadow-3)",
          }}
        />
        {browseOpen && (
          <div style={{
            marginTop: LIST_GAP, flex: "0 1 auto", minHeight: 0,
            display: "flex", flexDirection: "column",
            background: "var(--surface-float)",
            border: "1px solid var(--menu-border)", borderRadius: "var(--r-7)",
            boxShadow: "var(--shadow-3)", padding: 4,
          }}>
            <TagSetBrowseList browse={bro} fill raisedPopover />
          </div>
        )}
        {listOpen && !browseOpen && (
          <div ref={listBox} style={{
            marginTop: LIST_GAP, flex: "0 1 auto", minHeight: 0,
            display: "flex", flexDirection: "column",
            background: "var(--surface-float)",
            border: "1px solid var(--menu-border)", borderRadius: "var(--r-7)",
            boxShadow: "var(--shadow-3)", padding: 4,
          }}>
            <TagSuggestList
              list={list} fill tone={tone}
              // The `?` popover is RAISED here: an ordinary popover sits at
              // `LAYER.popover`, under this overlay's own layer.
              //
              // AND THE HIGHLIGHTED ROW OPENS ITS OWN, beside the list: what
              // a set says about the name under the highlight is exactly
              // what somebody typing here is choosing by, and reaching for
              // a `?` with the mouse in a list being driven by the arrows is
              // the wrong hand. It goes to the RIGHT of the box so it covers
              // none of it, and falls back to the ordinary on-request
              // placement when the window has no room there.
              renderRow={(m, hl) => (
                <TagSuggestionRow s={m} highlighted={hl} raisedPopover tone={tone}
                                  autoDescribe={listBox}
                                  // The popover walks to the tag a set says
                                  // to use instead; its title puts that name
                                  // in place of the word being typed.
                                  onPickName={(name) => takeName(name)} />
              )}
            />
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

