/**
 * The way back from a removal made in the right sidebar.
 *
 * Every one of those removals is already logged and already revertible — the
 * History tab has undone them since it existed. What was missing is that
 * nobody is looking at the History tab at the moment they take a caption off
 * the wrong item, and finding the entry afterwards means knowing the log
 * exists, which tab it is on, and which of forty rows was yours.
 *
 * WHICH events to revert is answered with a WATERMARK rather than by teaching
 * ten endpoints to return their event ids. `run()` notes the newest event id,
 * performs the removal, and asks what has been logged since — so anything the
 * action wrote is offered back, including the several entries one removal
 * fans out into (deleting a tag logs a `remove_tag` per item). Ids, not a
 * timestamp: two events written inside one request share a clock reading.
 *
 * The bar holds `events` = what to revert NEXT and `undone` = which direction
 * that is. A revert reports the entries IT wrote, and reverting those replays
 * the original — so one button flips between Undo and Redo for as long as
 * anyone keeps pressing it. That is the Tags tab's toast rule, and it is the
 * same rule here because it is the same log underneath.
 */
import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../../api";
import { bumpReverted } from "../../invalidation";

export interface UndoState {
  /** What reverting would touch next. */
  events: number[];
  /** What the action was, in the caller's own words ("Removed 3 tags"). */
  label: string;
  /** True once it has been undone — the button now offers Redo. */
  undone: boolean;
  /** ONE MORE THING THIS ACTION COULD BE, offered beside the way back. It
   *  belongs to the action rather than to the bar, which is why it rides in
   *  the state the action produced: the Faces tab's Reject takes a name off
   *  and leaves the crop in the queue, and "Say who" opens the dialog
   *  that puts it somewhere instead — the same correction carried one step
   *  further, for somebody who knows the answer. Gone the moment the offer
   *  is undone, since there is then nothing to carry further. */
  extra?: { label: string; icon: string; onClick: () => void };
}

export interface UndoBar {
  state: UndoState | null;
  /** Run a removal and offer it back. `label` is shown as-is; `extra` is one
   *  further thing this action could be, offered beside the way back. */
  run: (label: string, action: () => Promise<unknown>,
        extra?: UndoState["extra"]) => Promise<void>;
  /** Offer back events the caller already HOLDS — the fast path for an
   *  endpoint that returns its event ids (the Tags tab's bulk delete and
   *  merges). No watermark, no poll: a 17k-row deletion outruns the second
   *  `run` waits, and the caller knows exactly what it wrote. */
  offer: (label: string, events: number[], extra?: UndoState["extra"]) => void;
  /** Flip it: undo, or redo what was undone. */
  toggle: () => Promise<void>;
  dismiss: () => void;
}

/**
 * `scope` is what the bar belongs to — the open tab and the item. It is not
 * "state that happens to change"; it is the answer to "is this offer still
 * about what you are looking at". Change it and the bar goes, because a way
 * back from something you can no longer see is a button aimed at nothing.
 */
export function useUndoBar(scope: string, onReverted?: () => void): UndoBar {
  const [state, setState] = useState<UndoState | null>(null);
  useEffect(() => { setState(null); }, [scope]);

  const run = useCallback(async (label: string, action: () => Promise<unknown>,
                                 extra?: UndoState["extra"]) => {
    let mark = 0;
    try {
      mark = (await api.history(1, 0)).events[0]?.id ?? 0;
    } catch {
      // No watermark, no honest offer — do the work anyway and stay quiet
      // rather than showing an Undo that would revert whatever came last.
      await action();
      return;
    }
    await action();
    // Awaiting the action is not enough to know it has LANDED. A section's
    // remove is often `() => void removeSelected()` — fire and forget, so the
    // promise never reaches us — and even when it does, several removals are
    // several requests. So the log is asked again a few times over about a
    // second, and the first answer that has anything in it wins. Giving up
    // silently is the right failure: a bar that never appears is a missing
    // convenience, one that appears with the wrong events is a button that
    // undoes somebody else's edit.
    for (const wait of [0, 80, 160, 300, 500]) {
      if (wait) await new Promise((r) => setTimeout(r, wait));
      try {
        const since = await api.historySince(mark);
        const ids = since.events.filter((e) => e.revertible && !e.reverted)
          .map((e) => e.id);
        if (ids.length) {
          setState({ events: ids, label, undone: false, extra });
          return;
        }
      } catch {
        setState(null);
        return;
      }
    }
    setState(null);
  }, []);

  const offer = useCallback((label: string, events: number[],
                             extra?: UndoState["extra"]) => {
    setState(events.length ? { events, label, undone: false, extra } : null);
  }, []);

  const toggle = useCallback(async () => {
    setState((cur) => cur);
    const cur = state;
    if (!cur) return;
    const res = await api.revertEvents(cur.events);
    // Nothing written means nothing was reverted — leave the offer as it was
    // rather than promising a Redo for something that did not happen.
    if (res.events.length > 0)
      // The further step goes with the undo: once the action is taken back
      // there is nothing left to carry further.
      setState({ ...cur, events: res.events, undone: !cur.undone,
                 extra: undefined });
    // Refreshing what a revert can touch is THIS hook's job, not each
    // caller's. Both bars used to carry their own list of query keys and they
    // had drifted apart — the annotator's was missing the links, so undoing an
    // unlink put the row back in the database and not on the screen.
    // `onReverted` is left for what is genuinely local to a window.
    bumpReverted();
    onReverted?.();
  }, [state, onReverted]);

  return { state, run, offer, toggle, dismiss: () => setState(null) };
}

/** Runs a removal and offers it back — the same `run` the panel's bar uses. */
export type UndoRun =
  (label: string, action: () => Promise<unknown>,
   extra?: UndoState["extra"]) => Promise<void>;

const Runner = createContext<UndoRun | null>(null);

export function UndoRunnerSlot({ run, children }: {
  run: UndoRun;
  children: React.ReactNode;
}) {
  return <Runner.Provider value={run}>{children}</Runner.Provider>;
}

/**
 * How a ROW offers its own removal back.
 *
 * The bar's Remove was wrapped in one place because all nine lists share it —
 * but a row's own ✕ and its ⋯ menu remove exactly the same things and were
 * left with no way back, which reads as the offer being unreliable rather than
 * scoped. So the runner is handed down and every one of those calls it.
 *
 * With NO provider above it is a passthrough: the removal still happens, and
 * nothing is offered, because there is nowhere to offer it. Both sidebars do
 * provide one — the annotator's did not for a while, which made the same
 * removal in the same list offer a way back in one window and not the other.
 */
export function useUndoRun(): UndoRun {
  const run = useContext(Runner);
  return useCallback(
    (label, action, extra) =>
      (run ? run(label, action, extra) : action().then(() => undefined)),
    [run],
  );
}
