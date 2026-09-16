/** WHAT IS OVER THE PAGE — one table, two questions.
 *
 *  Every window-level shortcut has to ask "is anything on top of me?" before
 *  it acts, and every full-window overlay has to ask "is anything on top of
 *  me OTHER THAN MYSELF?" before it opens. The first is `modalIsOpen`; the
 *  second was five hand-written tuples, one per overlay, and they drifted —
 *  T's and Q's tuples never learned that C exists, so either would open
 *  over the caption sheet. A table of the ways, and the two questions
 *  derived from it, so a new way is added once and no tuple can forget it.
 *
 *  Pure — `store.ts` builds the table from its own flags and this composes
 *  it, so the rule is testable without the store. */
export function composeOverPage<K extends string>(
  flags: Record<K, () => boolean>,
): {
  /** Is anything over the page? */
  any: () => boolean;
  /** Is anything over the page, not counting `self` — for an overlay's
   *  own handler, which must not see itself. */
  except: (...self: K[]) => () => boolean;
} {
  const keys = Object.keys(flags) as K[];
  return {
    any: () => keys.some((k) => flags[k]()),
    except: (...self) => () =>
      keys.some((k) => !self.includes(k) && flags[k]()),
  };
}
