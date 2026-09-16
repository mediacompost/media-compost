/** THE GRID KEEPS ITS ORDER WHILE A CLUSTER IS OPEN.
 *
 *  The unnamed list is DERIVED: every answer about a face changes the
 *  clustering's input, so the next read re-groups everything and the crops
 *  come back in another order. On screen that is the grid rearranging itself
 *  under the pointer — answer one crop and the next one is somewhere else,
 *  which is the opposite of what a queue of small decisions needs.
 *
 *  So the ORDER IS FROZEN when a cluster is opened, and three things follow
 *  (owner 2026-09):
 *
 *  - a crop that was answered stays exactly where it was, drawn as a GHOST,
 *    so the answer is visible where the eye already is rather than as a hole
 *    that pulls everything after it forward;
 *  - a crop the re-clustering brings IN is appended, never inserted, so
 *    nothing already on screen moves;
 *  - and the whole thing is forgotten when another cluster is opened, which
 *    is the moment the order stops being the one somebody was working down.
 *
 *  Pure, so `node --test` can exercise it: the caller keeps a `FrozenOrder`
 *  in a ref and hands it back each render.
 */
import type { FaceRow } from "../api";
import type { FaceGroup } from "./faceGroups";

export interface StableFace {
  face: FaceRow;
  /** It is no longer in the cluster — answered, dismissed, moved away. Drawn
   *  in place and inert until the cluster is left. */
  gone: boolean;
}

export interface StableGroup {
  key: string;
  label: string;
  faces: StableFace[];
}

export interface FrozenOrder {
  /** Which cluster this order belongs to; a different one starts over. */
  key: string;
  /** Where each crop sits: the group it was first seen in, and its place in
   *  it. A crop keeps both for as long as the cluster is open. */
  slot: Map<number, { group: string; at: number }>;
  /** The last row seen for each crop, so one that has LEFT can still be
   *  drawn — it is no longer in what the server hands over. */
  seen: Map<number, FaceRow>;
}

export function freshOrder(key = ""): FrozenOrder {
  return { key, slot: new Map(), seen: new Map() };
}

/**
 * `groups` in the frozen order, with the crops that have left kept in place.
 *
 * Returns the groups to draw and the order to keep for next time — a new
 * `FrozenOrder` rather than a mutated one, so a render that throws away its
 * result changes nothing.
 *
 * A ghost whose GROUP has gone (its last live neighbour left it) goes with
 * it: the group is a heading about the crops under it, and one over nothing
 * but departures is a heading about no one.
 */
export function stableGroups(
  groups: FaceGroup[], frozen: FrozenOrder, key: string,
): { groups: StableGroup[]; frozen: FrozenOrder } {
  const next: FrozenOrder = frozen.key === key
    ? { key, slot: new Map(frozen.slot), seen: new Map(frozen.seen) }
    : freshOrder(key);

  const live = new Map<number, FaceRow>();
  for (const g of groups) for (const f of g.faces) live.set(f.id, f);
  for (const [id, f] of live) next.seen.set(id, f);

  // A crop nobody has placed yet goes on the END of the group it is in now —
  // the arrivals, in the order the grouping gave them.
  const filled = new Map<string, number>();
  for (const g of groups) {
    const held = [...next.slot.values()].filter((s) => s.group === g.key);
    filled.set(g.key, held.length ? Math.max(...held.map((s) => s.at)) + 1 : 0);
  }
  for (const g of groups) {
    for (const f of g.faces) {
      if (next.slot.has(f.id)) continue;
      const at = filled.get(g.key) ?? 0;
      next.slot.set(f.id, { group: g.key, at });
      filled.set(g.key, at + 1);
    }
  }

  const byGroup = new Map<string, StableFace[]>();
  const order = [...next.slot.entries()]
    .sort((a, b) => a[1].at - b[1].at);
  for (const [id, slot] of order) {
    const face = next.seen.get(id);
    if (!face) continue;
    const list = byGroup.get(slot.group) ?? [];
    list.push({ face, gone: !live.has(id) });
    byGroup.set(slot.group, list);
  }

  const out: StableGroup[] = groups.map((g) => ({
    key: g.key, label: g.label, faces: byGroup.get(g.key) ?? [],
  }));
  return { groups: out, frozen: next };
}
