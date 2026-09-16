// ONE ROW DRAG. Eight lists each measured "which half of the row is the
// pointer on", four each hung a window dragend listener as a safety net,
// and six grips each set their data, their drag image and its offset —
// the same three lines with the same trap in each (Safari wants the data
// set BEFORE the image; a hover-revealed grip must be made visible before
// `setDragImage` or WebKit cancels the drag as the reveal hides it).
import { useEffect, useRef } from "react";
import { halfOf, quarterOf, type DropHalf, type DropZone } from "./dragRowMath";

export type { DropHalf, DropZone };
export { insertionIndex } from "./dragRowMath";

/** Which half of the element under the pointer the drop would land on. */
export function dropHalf(e: React.DragEvent, axis: "x" | "y" = "y"): DropHalf {
  const r = e.currentTarget.getBoundingClientRect();
  return axis === "y" ? halfOf(e.clientY - r.top, r.height) : halfOf(e.clientX - r.left, r.width);
}

/** Before, into or after — the tree's quarters. */
export function dropQuarters(e: React.DragEvent): DropZone {
  const r = e.currentTarget.getBoundingClientRect();
  return quarterOf(e.clientY - r.top, r.height);
}

/** The props of a grip that drags its row. */
export function gripProps({ payload, mime = "text/plain", rowAttr, rowRef, enabled = true, onStart, onEnd, stop }: {
  /** What the drag carries; a drag carrying nothing may be declined. */
  payload: string;
  mime?: string;
  /** The row the ghost is drawn from: the nearest ancestor matching this
   *  selector, or `rowRef`; the grip itself otherwise. */
  rowAttr?: string;
  rowRef?: React.RefObject<HTMLElement | null>;
  enabled?: boolean;
  onStart?: (e: React.DragEvent) => void;
  onEnd?: (e: React.DragEvent) => void;
  /** Keep the dragstart from a parent that would also start one. */
  stop?: boolean;
}): { draggable: boolean; onDragStart?: (e: React.DragEvent) => void; onDragEnd?: (e: React.DragEvent) => void } {
  if (!enabled) return { draggable: false };
  return {
    draggable: true,
    onDragStart: (e) => {
      if (stop) e.stopPropagation();
      // Data FIRST: Safari wants it before the image, Chrome and Firefox
      // may decline a drag carrying nothing.
      e.dataTransfer.setData(mime, payload);
      e.dataTransfer.effectAllowed = "move";
      const self = e.currentTarget as HTMLElement;
      // A hover-revealed grip is hidden the instant its drag starts, and
      // WebKit cancels a drag whose source vanished — keep it painted.
      self.style.visibility = "visible";
      const row = rowRef?.current ?? (rowAttr ? self.closest(rowAttr) : null) ?? self;
      if (row instanceof HTMLElement) {
        const r = row.getBoundingClientRect();
        e.dataTransfer.setDragImage(row, e.clientX - r.left, e.clientY - r.top);
      }
      onStart?.(e);
    },
    onDragEnd: (e) => {
      (e.currentTarget as HTMLElement).style.visibility = "";
      onEnd?.(e);
    },
  };
}

/** The safety net: any drag that ends anywhere — dropped elsewhere, or
 *  cancelled with Escape — runs `cb`, so a highlight can never stick on. */
export function useDragEndReset(cb: () => void): void {
  const ref = useRef(cb);
  ref.current = cb;
  useEffect(() => {
    const clear = () => ref.current();
    window.addEventListener("dragend", clear);
    window.addEventListener("drop", clear);
    return () => {
      window.removeEventListener("dragend", clear);
      window.removeEventListener("drop", clear);
    };
  }, []);
}
