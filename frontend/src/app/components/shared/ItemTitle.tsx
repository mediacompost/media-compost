/**
 * WHAT THE ITEM WINDOW IS SHOWING, in its header: the item's name, with what
 * it measures underneath.
 *
 * The measurements — `1920×1080`, and a film's length — used to trail the name
 * as a SUFFIX, on the same line and in the same size, which is the one place
 * they compete with it: the name is what you are looking for and the numbers
 * are what you check, and the numbers were taking width from the name to say
 * so. Below it they cost the name nothing (the header has 48 px and the name
 * needs one line of it) and they read as a description of it rather than as
 * part of it.
 *
 * The name is in the WINDOW's own face, not the mono one. Mono was the image
 * editor's idea of a file name and the other two windows copied it, but this
 * is an item's name — usually a title, sometimes a sentence — and a
 * proportional face fits more of it in the same space, which is the whole
 * complaint the header layout exists to answer. The numbers underneath stay
 * mono, because columns of digits are what that face is for.
 */
import React from "react";

export function ItemTitle({ name, subtitle, title }: {
  name: string;
  /** The measurements line: `1920×1080`, `1920×1080 · 1:04`, or "" for none. */
  subtitle?: string;
  /** Tooltip, when the caller wants one other than the name itself. */
  title?: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", minWidth: 0,
      lineHeight: 1.2, justifyContent: "center" }}>
      {/* `data-truncates` is what `HeaderActions` measures to decide the fold:
          it needs the element that ellipsises, which is no longer the first
          child of what it is handed. */}
      <span
        data-truncates
        title={title ?? name}
        style={{ fontSize: "var(--fs-3)", fontWeight: 500, color: "var(--text-2)",
          minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap" }}
      >
        {name}
      </span>
      {subtitle ? (
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
          color: "var(--muted-2)", minWidth: 0, overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {subtitle}
        </span>
      ) : null}
    </div>
  );
}
