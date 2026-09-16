/**
 * ONE STACK FOR THE THREE JUDGING SESSIONS' ↑.
 *
 * Each session records what it wrote — a judgement's event fan, a tag
 * answer's, a whole batch's — and ↑ pops the newest step and reverts its
 * events. Rate kept a `Step[]` ref, the tag batch two refs (`judged` and
 * `skipped`) reconciled through a third (`recent`), the tag grid a
 * `BatchRecord[]` — three spellings of a stack, three copies of "revert the
 * ids, then drop the item's cached detail so the screen does not show the
 * answer that was just un-written".
 *
 * A REF, not state: the sessions re-render on every answer anyway (busy,
 * queue, cursor), and a stack that re-rendered on push would double every
 * keypress's work for nothing. Readers in a render see the current steps.
 */
import { useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api";
import { sessionStack, type SessionStack } from "./sessionStack";

export interface SessionUndo<T> extends SessionStack<T> {
  /** Revert an event fan and drop the named items' cached details. Empty
   *  ids revert nothing and still refresh the items. */
  revert: (eventIds: readonly number[], itemIds?: readonly number[]) => Promise<void>;
}

export function useSessionUndo<T>(): SessionUndo<T> {
  const qc = useQueryClient();
  const stack = useRef<SessionStack<T> | null>(null);
  if (!stack.current) stack.current = sessionStack<T>();
  return useMemo(() => {
    const s = stack.current!;
    return {
      get steps() { return s.steps; },
      get size() { return s.size; },
      push: s.push, pop: s.pop, peek: s.peek, drop: s.drop, clear: s.clear,
      revert: async (eventIds, itemIds = []) => {
        if (eventIds.length) await api.revertEvents([...eventIds]);
        for (const id of itemIds) void qc.invalidateQueries({ queryKey: ["item", id] });
      },
    };
  }, [qc]);
}
