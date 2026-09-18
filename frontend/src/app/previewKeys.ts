/** WHAT AN ARROW KEY MEANS IN THE PREVIEW — the pure rule.
 *
 *  The preview's arrows step three things in order (`QuickLook.step`): a
 *  sequence's PAGES, then the SELECTION, then the GRID. SHIFT skips the
 *  first of those, so a chapter is left the way the key leaves any other
 *  item — the fall-through off a sequence's ends, asked for outright
 *  instead of being walked to. Everything else about the step is unchanged,
 *  which is why this answers only WHICH of the two a press is.
 *
 *  THE SHIFT IS NOT ALWAYS THE PREVIEW'S. A judging session sits UNDER the
 *  preview and keeps the keys it marks `underPreview` (`sessionKeys.ts`) —
 *  and the tag grid marks ⇧ + ←/→, which turn the cursor card's answer. Two
 *  handlers on one window both hearing that press would answer the card AND
 *  jump the preview, so the session's claim wins: its own pool holds no
 *  sequence container, so there is nothing for a skip to skip there anyway.
 */
export interface ArrowLike {
  key: string;
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
}

export interface PreviewArrow {
  /** -1 = previous, 1 = next. Up mirrors Left, Down mirrors Right. */
  dir: -1 | 1;
  /** Skip a sequence's pages and step the ENTRY — Shift's whole meaning. */
  whole: boolean;
}

export function previewArrow(
  e: ArrowLike,
  opts: { sessionOwnsShift?: boolean } = {},
): PreviewArrow | null {
  const dir: -1 | 1 | 0 =
    e.key === "ArrowRight" || e.key === "ArrowDown" ? 1
    : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
  if (dir === 0) return null;
  // A bare Shift, so ⇧⌥ stays the tag grid's `cycleAll` and ⌘/Ctrl stay the
  // browser's — the preview claims one modifier, not every combination of it.
  const whole = e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey
    && !opts.sessionOwnsShift;
  return { dir, whole };
}
