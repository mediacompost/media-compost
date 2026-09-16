/**
 * The FIRST answer a query gives, held for as long as a dialog is asking
 * its question.
 *
 * A form is somebody halfway through saying something, and the library goes
 * on changing underneath it: an import running in another process, an AI job
 * landing, another tab writing. Every one of those invalidates the catalogs
 * a dialog reads, and each refetch re-renders the form, rebuilds its
 * suggestion list and can close a dropdown under the pointer — which is what
 * "editing group properties is almost impossible while an import runs" was.
 *
 * Nothing in a dialog needs to be live. The tag catalog is a suggestion
 * list, the tree is the parent picker, and the record's own row is what SAVE
 * diffs against — "the loaded state", which has to mean the state that was
 * loaded rather than whatever arrived while somebody typed, or the reconcile
 * writes a diff nobody looked at and the unsaved-changes prompt fires over a
 * change nobody made.
 *
 * `key` drops the held value when the dialog is aimed at something else.
 * `frozenNext` is the rule, pure, so it is a test.
 */
import { useRef } from "react";

export interface Held<T> { key: unknown; value: T }

export function frozenNext<T>(
  held: Held<T> | null, value: T | undefined, key: unknown,
): Held<T> | null {
  if (held && held.key !== key) held = null;
  if (!held && value !== undefined) held = { key, value };
  return held;
}

export function useFrozen<T>(value: T | undefined, key?: unknown): T | undefined {
  const held = useRef<Held<T> | null>(null);
  held.current = frozenNext(held.current, value, key);
  return held.current?.value;
}
