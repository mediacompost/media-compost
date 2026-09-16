/** Selecting rows the way the Tags tab does, for lists that are not it.
 *
 * The rules are that tab's, spelled out once so a second list cannot invent a
 * third dialect: a plain click selects that row ALONE — the rule every file
 * list has, and the one people bring with them — ⌘/Ctrl adds and removes,
 * shift extends the run from wherever the last plain click landed, and
 * press-and-drag PAINTS: the row pressed on decides whether the drag selects
 * or deselects, and the paint begins only at the SECOND row, so a plain click
 * is still a plain click. A quick drag
 * outruns the pointer events, so a run is painted whole rather than row by
 * row; the rows it flew over would otherwise be left behind.
 *
 * `keys` is the order the EYE sees, across every section the selection spans —
 * a range that measured itself against some other order would pick a run
 * nobody was shown.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { pickNext } from "../../../shared/pickList";
import { useEscapeClears } from "../../../shared/escapeClears";

export interface RowSelect {
  selected: string[];
  /** How many rows there are to pick. The bar shows while this is > 0. */
  total: number;
  has: (key: string) => boolean;
  /** Spread onto the row element. */
  props: (key: string) => {
    /** Marks the element AS a row, so a click elsewhere can tell it is on the
     *  background. Identity (`target === currentTarget`) cannot: the sections
     *  wrap their rows in divs of their own, and a click in the space beside
     *  a row lands on one of those. */
    "data-rowsel": string;
    onMouseDown: (e: React.MouseEvent) => void;
    onMouseEnter: () => void;
    onClick: (e: React.MouseEvent) => void;
  };
  clear: () => void;
  /** Every row, picked. The bar offers it while nothing is selected — a list
   *  that scrolls cannot be selected whole by dragging down it. */
  selectAll: () => void;
  /** Replace the selection outright — for a caller whose OTHER view of the
   *  same rows was picked in (the annotator's canvas outlines). */
  set: (next: string[] | ((cur: string[]) => string[])) => void;
  /** END THE PRESS WITHOUT A MOUSEUP — for a row that is also a DRAG source.
   *  A native HTML5 drag swallows the mouseup the paint gesture ends on
   *  (Chrome dispatches `dragend`, never `mouseup`), so the press would
   *  outlive the drag and the next pointer that crossed a row would paint a
   *  selection nobody asked for. The drag handlers call this. */
  cancelPress: () => void;
}

export function useRowSelect(keys: string[], opts?: {
  /** Passing BOTH hands the selection to the caller — the annotator, whose
   *  canvas boxes are the same rows (the `GroupedTags` contract, so a second
   *  list cannot invent a second dialect of it). Uncontrolled otherwise. */
  selected?: string[];
  onChange?: (next: string[]) => void;
  /** Escape with nothing else to close clears the picks. */
  escapeClears?: boolean;
  /** Drop picks the keys no longer hold (default on). Off for an owner
   *  showing two filtered panels over one selection, where each would prune
   *  the other's rows away. */
  prune?: boolean;
}): RowSelect {
  const controlled = opts?.selected !== undefined && !!opts?.onChange;
  const prune = opts?.prune ?? true;
  const [own, setOwn] = useState<string[]>([]);
  const selected = controlled ? (opts?.selected as string[]) : own;
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const onChangeRef = useRef(opts?.onChange);
  onChangeRef.current = opts?.onChange;
  const controlledRef = useRef(controlled);
  controlledRef.current = controlled;
  const setSelected = useCallback(
    (next: string[] | ((cur: string[]) => string[])) => {
      const value = typeof next === "function"
        ? next(selectedRef.current) : next;
      if (controlledRef.current) onChangeRef.current?.(value);
      else setOwn(value);
    }, []);
  const press = useRef<{ key: string; on: boolean } | null>(null);
  const moved = useRef(false);
  const anchor = useRef<string | null>(null);

  // The gesture ends wherever the pointer is, which is often outside any row.
  useEffect(() => {
    if (!prune) return;
    const up = () => { press.current = null; };
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  // A row that is gone cannot stay picked: removing what was selected would
  // otherwise leave the count saying three when one row is left.
  //
  // HUNG ON THE ARRAY'S IDENTITY, not on a join of it. `keys` is memoized by
  // every caller, so its identity already says "the rows changed" — and
  // joining it said the same thing at the cost of building a string of every
  // key ON EVERY RENDER, which for a seventeen-thousand-row list is 150 kB
  // of string per hover. The prune itself goes through a Set: `includes`
  // inside a `filter` is a scan per selected row.
  useEffect(() => {
    const cur = selectedRef.current;
    if (!cur.length) return;
    const live = new Set(keys);
    const kept = cur.filter((k) => live.has(k));
    if (kept.length !== cur.length) setSelected(kept);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys, prune]);

  // Stable, because callers hang effects on it — "clear when the item changes"
  // written against a fresh function every render clears on every render, which
  // reads as a selection that will not take.
  const clear = useCallback(() => {
    setSelected([]);
    anchor.current = null;
  }, [setSelected]);

  // Not a `useCallback`: `keys` is a new array every render, so it would be a
  // new function every render anyway — and nothing hangs an effect on this one.
  const selectAll = () => setSelected([...keys]);

  const paint = (run: string[], on: boolean) => {
    const touched = new Set(run);
    setSelected((cur) => on
      ? [...cur, ...run.filter((k) => !cur.includes(k))]
      : cur.filter((k) => !touched.has(k)));
  };

  useEscapeClears(!!opts?.escapeClears, selected.length > 0, clear);

  return {
    selected,
    total: keys.length,
    has: (key) => selected.includes(key),
    clear,
    selectAll,
    set: setSelected,
    cancelPress: () => { press.current = null; moved.current = false; },
    props: (key) => ({
      "data-rowsel": key,
      onMouseDown: (e) => {
        if (e.button !== 0) return;
        // A paint that begins on an unpicked row selects, and one that begins
        // on a picked row deselects — so dragging out of a run undoes it.
        press.current = { key, on: !selected.includes(key) };
        moved.current = false;
      },
      onMouseEnter: () => {
        const p = press.current;
        if (!p || key === p.key) return;
        moved.current = true;
        const a = keys.indexOf(p.key);
        const b = keys.indexOf(key);
        if (a === -1 || b === -1) { paint([key], p.on); return; }
        paint(keys.slice(Math.min(a, b), Math.max(a, b) + 1), p.on);
      },
      onClick: (e) => {
        // The drag already said what it meant; the release is not a click.
        if (moved.current) { moved.current = false; return; }
        // THE ONE CLICK RULE (`shared/pickList.ts`): plain picks this alone
        // (or puts the only pick down), ⌘ toggles, shift REPLACES with the
        // run from the anchor, ⌘⇧ adds the run.
        const r = pickNext(selectedRef.current, key,
          { meta: e.metaKey || e.ctrlKey, shift: e.shiftKey }, keys, anchor.current);
        anchor.current = r.anchor;
        setSelected(r.next);
      },
    }),
  };
}
