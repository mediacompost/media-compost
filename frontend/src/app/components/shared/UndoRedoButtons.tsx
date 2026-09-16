import React from "react";
import { LabelBtn } from "./iconButtons";

/**
 * The Undo/Redo button pair the image editor and the video editor share, so
 * the two halves of the item window look identical. Only the button chrome is
 * shared — each keeps its own history engine (the image editor snapshots
 * pixels, the video editor snapshots cutlists). The annotator has no undo
 * stack of its own; its reverts go through the history log.
 */
export function UndoRedoButtons({ canUndo, canRedo, onUndo, onRedo, t }: {
  canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void;
  /** REQUIRED — an optional translator is a silent-English hole (it happened:
   *  the annotator's Undo/Redo stayed untranslated while the editor's were
   *  fine). A deliberately-English window passes an identity. */
  t: (s: string) => string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
      <LabelBtn icon="undo" label={t("Undo")} title={t("Undo (⌘Z)")} onClick={onUndo} disabled={!canUndo} />
      <LabelBtn icon="redo" label={t("Redo")} title={t("Redo (⌘⇧Z)")} onClick={onRedo} disabled={!canRedo} />
    </div>
  );
}
