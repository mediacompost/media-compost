/** WHAT A CLICK DOES TO A SELECTION — the one rule, for every list.
 *
 *  A plain click picks this one and nothing else — except when it is
 *  ALREADY the only one, where the click is the way back out. ⌘/Ctrl
 *  toggles it and leaves the rest. Shift with an anchor REPLACES the
 *  selection with the run from the anchor to here (owner decision,
 *  2026-09: a shift that added was a different gesture than the one a plain
 *  click had just taught; five flat pickers had that dialect) — and ⌘⇧ is
 *  the one that adds the run. Shift with no anchor is a plain click.
 *
 *  Pure, over any key type, so the grid's ids, the tags' row keys and the
 *  training jobs' uids are one rule with one test.
 */
export interface PickMods { meta: boolean; shift: boolean }

export interface Picked<K> { next: K[]; anchor: K | null }

export function pickNext<K>(
  cur: readonly K[], k: K, mods: PickMods, order: readonly K[], anchor: K | null,
): Picked<K> {
  if (mods.shift && anchor != null && anchor !== k) {
    const a = order.indexOf(anchor), b = order.indexOf(k);
    if (a !== -1 && b !== -1) {
      const run = order.slice(Math.min(a, b), Math.max(a, b) + 1);
      // The anchor stays, so the range can be re-extended.
      return { next: mods.meta ? [...cur, ...run.filter((x) => !cur.includes(x))] : run,
               anchor };
    }
  }
  if (mods.meta) {
    return { next: cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k], anchor: k };
  }
  if (cur.length === 1 && cur[0] === k) return { next: [], anchor: null };
  return { next: [k], anchor: k };
}
