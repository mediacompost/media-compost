/** ENTER COMMITS, ESCAPE CANCELS — the pure half of an inline edit.
 *
 *  Two dozen rename fields each spelled the pair out in an `onKeyDown`, and
 *  they disagreed about the one thing that matters: whether the blur that
 *  follows an Escape commits the text it was asked to throw away. It must
 *  not, and `useInlineEdit` holds the flag that says so; this is the rule
 *  that says which key means what. */
export type InlineEditAction = "commit" | "cancel" | null;

export function inlineEditAction(
  e: { key: string; metaKey: boolean; ctrlKey: boolean },
  opts: { metaEnter?: boolean } = {},
): InlineEditAction {
  if (e.key === "Escape") return "cancel";
  if (e.key !== "Enter") return null;
  // A multi-line field: plain Enter is a newline, ⌘/Ctrl+Enter commits.
  if (opts.metaEnter && !(e.metaKey || e.ctrlKey)) return null;
  return "commit";
}
