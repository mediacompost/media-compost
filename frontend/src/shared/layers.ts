/**
 * The stacking order of everything that escapes its parent.
 *
 * A component portalled to `<body>` is a SIBLING of every window and dialog,
 * so its z-index is the only thing holding the order — and getting it wrong
 * produces the most confusing failure this codebase has: the thing opens, is
 * positioned, is hit-testable by a script, and is completely invisible. It
 * reads as a control that does nothing.
 *
 * It has happened four times, each time because a number was chosen against
 * the layer that existed when the code was written: the image editor's menus
 * at 90 under the item window (300); every dialog under that window until
 * `Overlay` went 40 -> 500; the model download menu at 200 under the settings
 * dialog; and the training editor's help popovers at 61 under the same. The
 * numbers live here now so the next one is a lookup rather than a guess.
 *
 * The rule for a popover is simple and has no exceptions worth the trouble:
 * it goes ABOVE every window and dialog. If its owner is behind one of those,
 * the popover should not be open at all — so there is no case where it wants
 * to be underneath.
 */

export const LAYER = {
  /** A drag ghost: the thing under the pointer while it is being carried.
   *  Above the popovers because whatever is being dragged is, by definition,
   *  the topmost thing on screen for as long as the gesture lasts. */
  dragGhost: 2000,
  /** `ItemWindow` — an overlay over the library, not a browser window. */
  itemWindow: 300,
  /** Quick Look, the full-window preview. Inline in the app tree rather
   *  than portalled, but named here because the tag-grid session below has
   *  to sit UNDER it: that session's cards open the preview over
   *  themselves, sidebar and T field included. */
  preview: 200,
  /** …and the same preview opened from INSIDE a dialog (the estimate
   *  dialog's sample strip). A dialog is 500, so the ordinary 200 would put
   *  the picture behind the thing that asked for it — the exact failure the
   *  note above is about. It claims Escape while it is up
   *  (`shared/escapeStack.ts`: opened last, it is on top), so the dialog under it does not close on
   *  the press that closes the preview. */
  previewRaised: 600,
  /** The three judging sessions — Rate, Tag batch and Tag grid. Each wants
   *  Quick Look (200) above it (its cards open the preview over themselves),
   *  every dialog (500) and confirm (600) above that so a refusal can be read
   *  over it, and the T field (4000) above everything; so they take the gap
   *  under the preview. Above every popover-free page element. */
  session: 150,
  /** `Overlay`'s panel: every dialog in the app. */
  modal: 500,
  /** The unsaved-changes prompt `Overlay` raises over its own panel. */
  modalConfirm: 600,
  /** Anything portalled to `<body>` that hangs off a control: menus,
   *  dropdowns, help popovers, hover previews. Above all of the above. */
  popover: 1000,
  /** The full-window keyboard overlays — `QuickTagOverlay` (T) and
   *  `QuickAssignOverlay` (Q). Not dialogs: each is its own dimmed screen
   *  raised over everything, including a toast reporting what the last one
   *  did. They SHARE the layer because they can never coexist: each one's
   *  key handler refuses while the other is open (`quickTagIsOpen` /
   *  `qaOverlayIsOpen`). */
  quickTag: 4000,
  /** A popover hanging off a control INSIDE one of those overlays — the
   *  `?` description behind a suggestion in the T field's list. The rule
   *  above ("a popover goes above every window") has one exception after
   *  all: an ordinary popover sits UNDER the quick tag sheet, so a `?` there
   *  opened and could never be seen. `AnchoredDropdown`'s `raised` is how a
   *  popover asks for this one. */
  quickTagPopover: 4100,
  /** `ActionToast` — the way back from a deletion. Above the popovers so the
   *  menu that performed the deletion cannot cover the undo. */
  toast: 3000,
  /** `UpdateBanner` — a notice about the SERVER, not about anything on the
   *  page. Above every layer here, the toast and the T sheet included: a
   *  page told it is stale must be told wherever it is. */
  banner: 5000,
} as const;

