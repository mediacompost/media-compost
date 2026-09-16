/** THE SUGGESTION LIST'S STATE — the highlight, the keys, the pointer rule
 *  — for every field with a list of names under it.
 *
 *  In `shared/` so the query builder's autocomplete can drive its list
 *  through it too (`query/` may not import `app/`); the app's own binding
 *  (`app/components/TagSuggestList.tsx`) adds the description marks to the
 *  ⇧Space key. The pure rules are `suggestRows.ts`.
 */
import React, { useLayoutEffect, useRef, useState } from "react";
import {
  Selectable, SuggestAction, SuggestRow, buildSuggestRows, clampHighlight,
  inputKeyAction, stepHighlight,
} from "./suggestRows";

export interface SuggestList<T> {
  rows: SuggestRow<T>[];
  /** The highlighted row — the first MATCH until an arrow or the mouse says
   *  otherwise, and back there whenever the rows change. */
  hi: number;
  /** Whether row `i` is one the keyboard and the mouse may land on. A title
   *  row is not; everything else is. */
  isSelectable: (i: number) => boolean;
  /** ArrowUp / ArrowDown while there are rows, Enter while `open`. Answers
   *  whether it took the key; the host keeps everything else. */
  handleKey: (e: React.KeyboardEvent) => boolean;
  /** Take the highlighted row — what Enter does, and what the T overlay's
   *  Tab does too. */
  pick: () => void;
  /** The list is on screen — the host's `open`, or (with `input`) focused,
   *  not dismissed, and something to show. */
  open: boolean;
  focused: boolean;
  dismissed: boolean;
  /** Put the list away without blurring (a pick, a category taken). */
  dismiss: () => void;
  /** …and bring it back (typing). */
  undismiss: () => void;
  /** For the input, where the host handed the field over (`input`). */
  inputProps: {
    onFocus: () => void;
    onBlur: () => void;
    onKeyDown: (e: React.KeyboardEvent) => void;
  };
  /** For the list container. */
  listProps: {
    ref: React.RefObject<HTMLDivElement>;
    onMouseMove: () => void;
  };
  /** For row `i`: the mousedown commits, the hover highlights (only once the
   *  pointer has moved since the rows last changed). */
  rowProps: (i: number) => {
    onMouseDown: (e: React.MouseEvent) => void;
    onMouseEnter: () => void;
    "data-hi": "true" | undefined;
  };
}

export interface SuggestListOpts<T> {
  matches: readonly T[];
  /** The name the Create row offers, or null for no such row. The host
   *  decides — `allowCreate`, "does the name exist", and whether the answer
   *  is SETTLED (a Create offered off the previous fragment's rows is a claim
   *  about a question nobody has answered yet). */
  create: string | null;
  onPick: (row: SuggestRow<T>) => void;
  /** Whether the list is on screen. Enter is taken only then; the arrows are
   *  taken whenever there are rows, because an arrow is also how a dismissed
   *  list is asked back. Ignored with `input`, which derives it. */
  open?: boolean;
  /** Whether `matches` and `create` answer the CURRENT fragment. While they
   *  do not — the debounce has not fired, the fetch is in flight — the list
   *  KEEPS THE LAST SETTLED ROWS rather than showing an in-between state:
   *  the matches used to arrive first and the Create row a beat later, so
   *  the highlight landed on the first match and then jumped to Create when
   *  the answer settled, which read as the selection changing under the
   *  hand. One change per fragment, with the Create decision already made. */
  settled?: boolean;
  /** Which MATCHES the keyboard may land on. A host whose list holds rows
   *  that are only there to be read — the T overlay's section titles — says
   *  so here, and the arrows step over them (`suggestRows.Selectable`). */
  selectable?: (item: T) => boolean;
  /** ANSWERS THAT ARE NOT NAMES, offered first — the face namer's
   *  "Unnamed". Always selectable. */
  actions?: readonly SuggestAction[];
  /** READ THE HIGHLIGHTED ROW'S `?` on ⇧Space — the app's description
   *  marks register by name; a host with none passes nothing and the space
   *  falls through to be typed. */
  describe?: (name: string) => boolean;
  /** THE FIELD'S KEYS AND BLUR, where the host wants them too: focus and
   *  dismissal are held here, `open` is derived, and `inputProps` go on the
   *  input. The rule is `inputKeyAction` (`suggestRows.ts`). */
  input?: SuggestInput;
}

export interface SuggestInput {
  /** Start with the list hidden — an autofocused dialog field, which would
   *  otherwise open its own list over the form. Typing, an arrow or a
   *  re-focus brings it back. */
  startDismissed?: boolean;
  /** Something that takes keys FIRST — the empty field's browse tree. */
  preKey?: (e: React.KeyboardEvent) => boolean;
  /** …and counts as "a list is open" for Escape's first stage. Asked at
   *  the key, since the tree's state is computed after the hook. */
  alsoOpen?: () => boolean;
  /** Enter with no list up: commit what is typed. */
  onCommitTyped?: () => void;
  /** Escape with no list up. */
  onCancel?: () => void;
  /** Tab picks the highlighted row (the T overlay's rule). */
  tabPicks?: boolean;
  /** A blur lands after the row's mousedown has had its chance. */
  blurMs?: number;
  onBlur?: () => void;
}

export function useSuggestList<T extends { name: string }>({
  matches, create, onPick, open: openIn, settled = true, selectable, actions,
  describe, input,
}: SuggestListOpts<T>): SuggestList<T> {
  // THE FIELD'S STATE, where the host handed the field over. `dismissed`
  // hides the list without blurring, so Escape can close it while the
  // typed text stays put; it lasts for the focus session.
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(() => !!input?.startDismissed);
  const built = buildSuggestRows(matches, create, actions);
  const frozen = useRef(built);
  if (settled) frozen.current = built;
  const rows = settled ? built : frozen.current;
  // `open` is what Enter reads: the host's word, or — with the field handed
  // over — focused, not dismissed, and something to show.
  const open = input ? focused && !dismissed && rows.length > 0 : !!openIn;
  const ok: Selectable = (i) => {
    const row = rows[i];
    if (!row) return false;
    if (row.kind === "action" || row.kind === "create") return true;
    return !selectable || selectable(row.item);
  };
  // The rows' identity. The highlight is remembered AGAINST it: a highlight
  // stored for another set of rows is nobody's, so it falls back to the
  // default — which is also what makes the Create row appearing a beat after
  // the matches (once the fetch settles) leave the highlight on the first
  // match rather than pushing it one row down.
  const key = rows.map((r) => r.kind === "action" ? "!" + r.action.id
                      : r.kind === "create" ? "+" + r.name
                      : r.item.name).join(" ");
  const [raw, setRaw] = useState<{ key: string; hi: number } | null>(null);
  const hi = clampHighlight(raw?.key === key ? raw.hi : null, rows, ok);
  const listRef = useRef<HTMLDivElement>(null);
  // Whether the POINTER has moved since the rows last changed. A list that
  // opens (or scrolls) under a resting cursor gets a `mouseenter` it never
  // earned, and the row it lands on would steal the highlight from the one
  // being typed towards — so hovering only counts once the mouse has said
  // something. Load-bearing now that the list scrolls: a keyboard move
  // scrolls a row under the pointer, which would re-highlight it, which
  // would scroll again.
  const mouseLive = useRef(false);
  const keyRef = useRef(key);
  if (keyRef.current !== key) { keyRef.current = key; mouseLive.current = false; }
  // A KEYBOARD move scrolls the row into view (the mouse is already looking
  // at the row it highlighted) — AND SO DOES A CHANGE OF ROWS. The rows
  // change while the list is scrolled: the Create row arrives a beat after
  // the matches (once the fetch settles), the highlight falls back to the
  // default at the TOP, and a list left scrolled where it was showed no
  // highlighted row at all, the next ArrowDown then landing "somewhere down
  // the list". So the highlighted row is brought into view whenever the rows
  // are new, by the same rule.
  const movedByKey = useRef(false);
  const scrolledFor = useRef<string | null>(null);

  useLayoutEffect(() => {
    const rowsChanged = scrolledFor.current !== key;
    if (!movedByKey.current && !rowsChanged) return;
    movedByKey.current = false;
    scrolledFor.current = key;
    const el = listRef.current?.querySelector<HTMLElement>('[data-hi="true"]');
    el?.scrollIntoView({ block: "nearest" });
  }, [hi, key]);

  const pick = () => { if (rows[hi] && ok(hi)) onPick(rows[hi]); };

  const handleKey = (e: React.KeyboardEvent): boolean => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (rows.length === 0) return false;
      e.preventDefault();
      movedByKey.current = true;
      mouseLive.current = false;
      const delta = e.key === "ArrowDown" ? 1 : -1;
      // Functional, so two presses landing before a render step twice rather
      // than both from the same starting row.
      setRaw((prev) => {
        const cur = clampHighlight(prev?.key === key ? prev.hi : null, rows, ok);
        return { key, hi: stepHighlight(cur, delta, rows.length, ok) };
      });
      return true;
    }
    // SHIFT+SPACE READS THE HIGHLIGHTED TAG. The `?` beside a suggestion is
    // a mouse target in a list somebody is driving from the keyboard, so
    // there is a key for it — and the same key closes it again. It answers
    // only where that row HAS a popover; otherwise the space falls through
    // and is typed, which is what a space in a tag field means.
    if (e.key === " " && e.shiftKey && open && rows.length > 0) {
      // THE ROW'S OWN NAME, off the right half of the union: a match row
      // carries its `item`, and only the Create row has a bare `name` — so
      // reading `name` off every row asked the popover about nothing at all
      // except the one row that never has one.
      const row = rows[hi];
      const name = row == null || row.kind === "action" ? undefined
        : row.kind === "create" ? row.name
        : (row.item as { name?: string }).name;
      if (name && describe?.(name)) {
        e.preventDefault();
        return true;
      }
      return false;
    }
    if (e.key === "Enter" && open && rows.length > 0) {
      e.preventDefault();
      pick();
      return true;
    }
    return false;
  };

  const inputRef = useRef(input);
  inputRef.current = input;
  const onKeyDown = (e: React.KeyboardEvent) => {
    const inp = inputRef.current;
    if (!inp) return;
    if (inp.preKey?.(e)) return;
    // ⇧Space is the list's own key and nothing below names it.
    if (e.key === " " && e.shiftKey && open && handleKey(e)) return;
    const action = inputKeyAction(e, {
      listOpen: open, hasRows: rows.length > 0, alsoOpen: inp.alsoOpen?.(),
      tabPicks: inp.tabPicks,
    });
    switch (action) {
      case "step":
        // An arrow is also how a dismissed list is asked back.
        setDismissed(false);
        if (!handleKey(e)) e.preventDefault();
        break;
      case "pick":
        if (e.key === "Enter") { handleKey(e); break; }
        e.preventDefault();
        pick();
        break;
      case "commitTyped":
        e.preventDefault();
        inp.onCommitTyped?.();
        break;
      case "dismiss":
        // First Escape closes the list (keeping the text)…
        e.preventDefault();
        e.stopPropagation();
        setDismissed(true);
        break;
      case "cancel":
        // …a second cancels the field.
        e.preventDefault();
        e.stopPropagation();
        inp.onCancel?.();
        break;
      default: break;
    }
  };

  return {
    rows, hi, handleKey, pick, isSelectable: ok,
    open, focused, dismissed,
    dismiss: () => setDismissed(true),
    undismiss: () => setDismissed(false),
    inputProps: {
      onFocus: () => setFocused(true),
      onBlur: () => {
        const inp = inputRef.current;
        // A dismissal lasts as long as the focus session, so coming back
        // to the field offers the list again.
        setTimeout(() => { setFocused(false); setDismissed(false); },
                   inp?.blurMs ?? 150);
        inp?.onBlur?.();
      },
      onKeyDown,
    },
    listProps: {
      ref: listRef,
      onMouseMove: () => { mouseLive.current = true; },
    },
    rowProps: (i) => ({
      onMouseDown: (e) => { e.preventDefault(); if (rows[i] && ok(i)) onPick(rows[i]); },
      onMouseEnter: () => {
        if (!mouseLive.current || !ok(i)) return;
        movedByKey.current = false;
        setRaw({ key, hi: i });
      },
      "data-hi": hi === i ? "true" : undefined,
    }),
  };
}

