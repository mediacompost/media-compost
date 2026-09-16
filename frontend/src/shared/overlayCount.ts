import { useEffect } from "react";

//: HOW MANY MODAL SHEETS ARE ON SCREEN — dialogs built on `Overlay` and the
//: confirm prompts built on `ConfirmModal`.
//:
//: Counted at the component rather than tracked in a store, because most of
//: them are not IN one: the tag, subject, place, event, group, ranking and
//: model-help dialogs are all local component state, and a store flag would
//: have to be remembered per dialog. Every modal in this app is built on one
//: of the two components, so counting mounts is the one thing that sees all
//: of them — and a dialog added tomorrow is covered the moment it renders.
//:
//: What it is FOR: a window-level shortcut belonging to the page underneath
//: has to stand down while a sheet is over it. See `store.modalIsOpen`.
let _open = 0;

/** Whether any dialog or confirm is currently mounted. */
export function overlayIsOpen(): boolean {
  return _open > 0;
}

/** Count this component while it is on screen. An empty dep array: this is
 *  about being mounted, not about anything the sheet shows. */
export function useOverlayMount(): void {
  useEffect(() => {
    _open += 1;
    return () => { _open -= 1; };
  }, []);
}
