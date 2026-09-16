// The grid item ids currently being dragged. Shared so drop targets can validate
// a drag *before* the drop — the HTML5 dataTransfer payload isn't readable during
// dragover (only on drop), so we stash the ids here on dragstart instead.

let dragged: number[] = [];

export function setDraggedItems(ids: number[]): void {
  dragged = ids;
}

export function clearDraggedItems(): void {
  dragged = [];
}

export function getDraggedItems(): number[] {
  return dragged;
}

// True while the color-reference picker overlay is open: it accepts file
// drops itself, so the window-level file-drag handler must NOT pop the
// import overlay over it.
let refPicker = false;

export function setRefPickerOpen(open: boolean): void {
  refPicker = open;
}

export function isRefPickerOpen(): boolean {
  return refPicker;
}
