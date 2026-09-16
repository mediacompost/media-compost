// `body.mc-dragging` — set for the length of any HTML5 drag in this document.
//
// WHY IT EXISTS: WebKit resolves `:hover` DURING a drag and fires `dragover`
// continuously (a stationary pointer keeps producing events, where Chromium
// only reports movement). So every row a drag crosses runs the hover reveal —
// which swaps `display` between the row's count and its action buttons, i.e. a
// LAYOUT and the rasterizing of two icon glyphs, per row, per crossing, on
// whatever the display's pixel ratio happens to be. Those buttons cannot be
// pressed while the pointer is holding something anyway, so the reveal is
// suppressed for the length of the drag (`tokens.css` scopes the rules to
// `body:not(.mc-dragging)`); the paint-only hover TINT is left alone.
//
// One listener pair for the whole document, so it covers every drag there is —
// images from the grid, a group row, a tag instance, a cutlist block.

const CLASS = "mc-dragging";
// A second class for a drag carrying grid ITEMS, which is what the sidebar's
// drop targets accept. It is what lets the drop highlight be drawn by CSS
// `:hover` — WebKit resolves hover during a drag, so the feedback then follows
// the pointer through the browser's own machinery rather than waiting on a
// `dragover` to reach React. The JS highlight stays exactly as it was: the two
// paint the same colour, and a drop is hit-tested where the pointer is, so the
// faster of the two is never promising something the drop would not do.
const ITEMS_CLASS = "mc-dragging-items";
const ITEMS_TYPE = "application/x-mc-items";

// True between `dragstart` and `dragend` in THIS document — i.e. the drag was
// started by the page, not by something dragged in from outside it. WebKit
// fires `dragover` about 1400 times a second (measured: 5771 events across 245
// frames of one drag), so a listener that runs for all of them wants the
// cheapest possible way to say "not mine".
let internal = false;

export function internalDragActive(): boolean {
  return internal;
}

export function installDragBodyClass(): () => void {
  const on = (e: DragEvent) => {
    internal = true;
    document.body.classList.add(CLASS);
    if (Array.from(e.dataTransfer?.types || []).includes(ITEMS_TYPE)) {
      document.body.classList.add(ITEMS_CLASS);
    }
  };
  const off = () => {
    internal = false;
    document.body.classList.remove(CLASS, ITEMS_CLASS);
  };
  // `dragend` fires on the source for every ending, cancels included; `drop`
  // is the belt to that brace for a drag whose source has been unmounted.
  window.addEventListener("dragstart", on);
  window.addEventListener("dragend", off);
  window.addEventListener("drop", off);
  return () => {
    window.removeEventListener("dragstart", on);
    window.removeEventListener("dragend", off);
    window.removeEventListener("drop", off);
    off();
  };
}
