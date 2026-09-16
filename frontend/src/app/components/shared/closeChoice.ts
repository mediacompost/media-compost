/**
 * The question the item window has to ask before it goes, while it is holding
 * several tabs.
 *
 * ⌘W cannot be the answer, and that was tried back when this really was a
 * browser window: a page may not reliably intercept it — the browser reserves
 * the key and mostly never delivers the event — so "closes the tab when there
 * are two" was a rule that worked on some machines and silently closed
 * everything on others. It can hold a chapter's worth of pages, so the
 * difference matters.
 *
 * So the choice is offered instead of guessed, on the window's own close
 * gesture (Escape) and only while there IS more than one tab: with one tab the
 * window is the tab and there is nothing to ask. All three halves draw it
 * through the one `ConfirmModal`, with this as the wording, which is what
 * stops the words and the button order drifting apart between them. Closing
 * them ALL takes everything else with it, so it is the deliberate answer.
 */
import type { ConfirmSpec } from "../../../shared/confirm";

export function closeChoice(
  t: (s: string, vars?: Record<string, string>) => string,
  name?: string | null,
): Omit<ConfirmSpec, "answer" | "plain"> & Required<Pick<ConfirmSpec, "answer" | "plain">> {
  return {
    title: t("Close all of these?"),
    body: name
      ? t("Several items are open here. Close them all, or only {name}?", { name })
      : t("Several items are open here. Close them all, or only the current tab?"),
    plain: { label: t("Close tab") },
    answer: { label: t("Close all") },
  };
}
