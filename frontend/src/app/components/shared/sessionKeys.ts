/** WHICH KEY DOES WHAT IN A JUDGING SESSION — the pure rule.
 *
 *  The three full-window sessions (Rate, Tag items one by one, Tag items in
 *  a grid) each wrote their own keydown handler, and the shared keys —
 *  Escape, Tab, undo, Space, the way they stand down under the preview and
 *  under the summary — were spelled three times, in three orders. The
 *  spine is here, in one order, and each session hands over only the keys
 *  that are its own.
 *
 *  Escape is not in it: it goes through the escape stack (`useEscape`), so
 *  a preview or a dialog opened over the session takes it first.
 *
 *  THE ORDER:
 *  1. Tab (plain) toggles the summary — unless the preview is up, whose own
 *     Tab toggles its side panel.
 *  2. Undo — the session's undo keys, under the summary too, never under
 *     the preview (↑ is the preview's own step there).
 *  3. Under the summary, only a key marked `underSummary` runs.
 *  4. Space is PREVIEW, up or down (the session's own toggle — the preview's
 *     Space stands down under a session).
 *  5. S is SKIP, not under the preview.
 *  6. The session's keys, in order; under the preview only one marked
 *     `underPreview` (the card's own keys — the tag grid's arrows walk the
 *     preview and turn that card's answer).
 */
export interface KeyLike {
  key: string;
  code: string;
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
}

export interface SessionKeyRule<E extends KeyLike = KeyLike> {
  match: (e: E) => boolean;
  /** Runs while the preview is up — the card's own keys. */
  underPreview?: boolean;
  /** Runs while the summary is up. */
  underSummary?: boolean;
}

export interface SessionKeySpec<E extends KeyLike = KeyLike> {
  hasTab: boolean;
  undo?: (e: E) => boolean;
  hasPreview: boolean;
  hasSkip: boolean;
  keys: SessionKeyRule<E>[];
}

export type SessionKeyAction =
  | { kind: "tab" } | { kind: "undo" } | { kind: "preview" } | { kind: "skip" }
  | { kind: "key"; index: number };

export const noMods = (e: KeyLike): boolean =>
  !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey;

export function sessionKeyAction<E extends KeyLike>(
  spec: SessionKeySpec<E>, e: E,
  state: { preview: boolean; summary: boolean },
): SessionKeyAction | null {
  const { preview, summary } = state;
  if (e.key === "Tab" && noMods(e)) {
    return spec.hasTab && !preview ? { kind: "tab" } : null;
  }
  if (spec.undo?.(e) && !preview) return { kind: "undo" };
  if (summary) {
    const i = spec.keys.findIndex((k) => k.underSummary && k.match(e));
    return i >= 0 ? { kind: "key", index: i } : null;
  }
  if (e.code === "Space" && noMods(e)) {
    return spec.hasPreview ? { kind: "preview" } : null;
  }
  if ((e.key === "s" || e.key === "S") && noMods(e)) {
    return spec.hasSkip && !preview ? { kind: "skip" } : null;
  }
  const i = spec.keys.findIndex((k) => (!preview || k.underPreview) && k.match(e));
  return i >= 0 ? { kind: "key", index: i } : null;
}
