/** A judging session's history: the steps it took, newest last. Pure — the
 *  hook in `useSessionUndo.ts` adds the revert. `drop` takes the LAST step
 *  the predicate matches, since the newest is the one somebody just made. */
export interface SessionStack<T> {
  readonly steps: readonly T[];
  readonly size: number;
  push: (step: T) => void;
  pop: () => T | undefined;
  peek: () => T | undefined;
  /** Remove the newest step matching `pred` and return it. */
  drop: (pred: (step: T) => boolean) => T | undefined;
  clear: () => void;
}

export function sessionStack<T>(): SessionStack<T> {
  const steps: T[] = [];
  return {
    steps,
    get size() { return steps.length; },
    push: (step) => { steps.push(step); },
    pop: () => steps.pop(),
    peek: () => steps[steps.length - 1],
    drop: (pred) => {
      for (let i = steps.length - 1; i >= 0; i--) {
        if (pred(steps[i])) return steps.splice(i, 1)[0];
      }
      return undefined;
    },
    clear: () => { steps.length = 0; },
  };
}
