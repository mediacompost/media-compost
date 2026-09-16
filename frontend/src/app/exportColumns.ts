// Reordering the export's columns — the arithmetic, on its own.
//
// The CSV export lets a column, and a whole record GROUP of columns, be
// dragged into place; the order that results is the file's column order and is
// remembered between exports. The rule is four lines and every way of getting
// it wrong is an off-by-one that looks almost right on screen — a block that
// lands one slot short, or a downward drag that cannot reach the end of the
// list — so it lives here, pure, and `exportColumns.test.ts` states the cases.

/**
 * Move a block of columns so it lands beside `at`.
 *
 * ONE rule for a single column and for a group of them: a group is one line on
 * screen standing for several columns, and dragging that line has to move all
 * of them together.
 *
 * The DIRECTION decides which side of `at` the block lands on — dragged
 * downward it goes after the row it is over, upward before it. That is what
 * lets a drag reach both ends of the list: inserting always-before can never
 * put anything last, and always-after can never put anything first.
 *
 * Returns `order` itself when there is nothing to do (an empty block, a target
 * inside the block, a target that is not in the list), so a caller setting
 * state with it re-renders nothing.
 */
export function moveBlock<T>(order: T[], keys: T[], at: T): T[] {
  const held = new Set<T>(keys);
  if (!keys.length || held.has(at)) return order;
  const rest = order.filter((k) => !held.has(k));
  const j = rest.indexOf(at);
  if (j < 0) return order;
  const downward = order.indexOf(keys[0]) < order.indexOf(at);
  const idx = downward ? j + 1 : j;
  return [...rest.slice(0, idx), ...keys, ...rest.slice(idx)];
}
