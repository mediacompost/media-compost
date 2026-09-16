/** Which side of a row a drop lands — pure, from the pointer's position in
 *  the row's box (`shared/useDragRow.ts`). */
export type DropHalf = "before" | "after";
export type DropZone = "before" | "into" | "after";

export function halfOf(pos: number, size: number): DropHalf {
  return pos > size / 2 ? "after" : "before";
}

/** The category tree's rule: the top quarter is BEFORE, the bottom AFTER,
 *  the middle INTO. */
export function quarterOf(pos: number, size: number): DropZone {
  const y = size > 0 ? pos / size : 0.5;
  return y < 0.25 ? "before" : y > 0.75 ? "after" : "into";
}

/** Where a carried row lands in a list once it is taken out: the target
 *  index, plus one for a drop on the lower half, less one if the carried
 *  row sat above the target — the two places that each computed one of
 *  those and landed one short. */
export function insertionIndex(from: number, target: number, half: DropHalf): number {
  let to = target + (half === "after" ? 1 : 0);
  if (from < to) to -= 1;
  return to;
}
