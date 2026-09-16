/** A FLAT LIST'S SELECTION — the pick rule (`pickList.ts`) with its anchor,
 *  pruning against the rows that exist, Select all, and (opt-in) Escape.
 *  For the lists whose rows are not painted by dragging (the training
 *  jobs, the evaluate tiles, the cut track, the import's staged rows);
 *  the rows that are painted use `useRowSelect`, whose click is this same
 *  rule. */
import { useCallback, useEffect, useRef, useState } from "react";
import { pickNext, type PickMods } from "./pickList";
import { useEscapeClears } from "./escapeClears";

export interface PickList<K> {
  picked: K[];
  has: (k: K) => boolean;
  pick: (k: K, mods: PickMods) => void;
  clear: () => void;
  selectAll: () => void;
  set: (next: K[]) => void;
  /** The range anchor — the last plain or ⌘ pick, held for shift. */
  anchor: React.MutableRefObject<K | null>;
}

export function usePickList<K>(order: readonly K[], opts: {
  /** Controlled: the caller holds the list. */
  selected?: K[];
  onChange?: (next: K[]) => void;
  /** Drop picks the order no longer holds — off while the order is still
   *  loading, or an empty first answer would empty the selection too. */
  prune?: boolean;
  /** Escape with nothing else to close clears the selection. */
  escapeClears?: boolean;
} = {}): PickList<K> {
  const controlled = opts.selected !== undefined && !!opts.onChange;
  const [own, setOwn] = useState<K[]>([]);
  const picked = controlled ? (opts.selected as K[]) : own;
  const pickedRef = useRef(picked);
  pickedRef.current = picked;
  const onChangeRef = useRef(opts.onChange);
  onChangeRef.current = opts.onChange;
  const anchor = useRef<K | null>(null);
  const set = useCallback((next: K[]) => {
    if (onChangeRef.current) onChangeRef.current(next); else setOwn(next);
  }, []);
  const clear = useCallback(() => { set([]); anchor.current = null; }, [set]);
  const orderRef = useRef(order);
  orderRef.current = order;
  useEffect(() => {
    if (!opts.prune) return;
    const keep = pickedRef.current.filter((k) => order.includes(k));
    if (keep.length !== pickedRef.current.length) set(keep);
    if (anchor.current != null && !order.includes(anchor.current)) anchor.current = null;
  }, [order, opts.prune, set]);
  useEscapeClears(!!opts.escapeClears, picked.length > 0, clear);
  return {
    picked,
    has: (k) => picked.includes(k),
    pick: (k, mods) => {
      const r = pickNext(pickedRef.current, k, mods, orderRef.current, anchor.current);
      anchor.current = r.anchor;
      set(r.next);
    },
    clear,
    selectAll: () => { set([...order]); anchor.current = order[order.length - 1] ?? null; },
    set,
    anchor,
  };
}
