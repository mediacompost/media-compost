/**
 * ANNOTATE ／ EDIT — the item window's two halves, in one segmented control.
 *
 * They used to be two windows and a button in each header pointing at the
 * other ("Annotate", "Edit image"), which made a pair of buttons that opened
 * something rather than a state you were in — and opening the same item from
 * the library twice, once each way, left two windows over one picture. One
 * window, two modes, and the control says which one you are looking at.
 *
 * The mode is per TAB (`store.editorModes`): a window can hold a page you are
 * labelling and a photograph you are retouching, and which half you want is a
 * fact about the item, not about the window.
 *
 * Switching OUT of edit with unsaved changes has to ask, which is why this
 * takes `onLeaveEdit` rather than setting the mode itself: only the editor
 * knows whether its buffer is dirty, and only it can offer save / discard /
 * cancel.
 */
import React from "react";
import { ItemMode } from "../../store";
import { SegmentedControl } from "../../../shared/SegmentedControl";

export function ModeSwitch({ mode, onPick, editIcon, disabled, t }: {
  mode: ItemMode;
  /** Called with the mode asked for. The caller may refuse (or defer behind a
   *  prompt) — this control never changes the mode by itself. */
  onPick: (mode: ItemMode) => void;
  /** `edit` for a picture, `movie_edit` for a film — the ICON says which
   *  editor the other half is. The LABEL does not: it read "Edit image" and
   *  "Edit video" beside a plain "Annotate", so one segment of a two-segment
   *  control named its object and the other did not, and the pair changed
   *  width as you moved between an image tab and a film tab. What it does is
   *  edit the thing this window is showing, which the picture already says. */
  editIcon: string;
  /** No edit half at all — a sequence has no single file to edit. */
  disabled?: boolean;
  t: (s: string) => string;
}) {
  return (
    <SegmentedControl<ItemMode>
      value={mode}
      onChange={onPick}
      options={[
        { value: "annotate", icon: "frame_inspect", label: t("Annotate"),
          title: t("Label this item — tags, boxes, people, captions") },
        { value: "edit", icon: editIcon, label: t("Edit"), disabled,
          title: disabled
            ? t("This item has no single file to edit")
            : t("Change the item itself — its pixels, or its cuts") },
      ]}
    />
  );
}
