/** The one clamp a divider uses: between its bounds and inside the room
 *  the other side leaves (`shared/Split.tsx`). Pure, so it is tested. */
export function clampSplit(v: number, { min, max, room = Infinity, restMin = 0 }: {
  min: number; max: number; room?: number; restMin?: number;
}): number {
  return Math.round(Math.max(min, Math.min(max, room - restMin, v)));
}
