/**
 * ONE "ARE YOU SURE?" — the store behind `ConfirmModal`.
 *
 * Forty-three sites asked with the browser's own `window.confirm`, five drew
 * a sheet of their own, and the sheets differed in the colour of Delete, in
 * whether Escape closed them, and in whether a count could be said at all.
 * `ask()` queues a question here; `ConfirmHost` (mounted once, in App) draws
 * the first of the queue and settles it. The strings arrive TRANSLATED — a
 * caller has a `t` and a count, this module has neither.
 *
 * Pure and import-free so its tests run under node; the React half is in
 * `ConfirmModal.tsx`.
 */
export type ConfirmAnswer = {
  label: string;
  /** The press destroys something: the button is drawn in the danger tint
   *  and Enter does not press it. */
  danger?: boolean;
  /** Run before the sheet closes; the buttons disable and the label reads
   *  `busy` meanwhile. A rejection keeps the sheet open. */
  run?: () => Promise<void> | void;
  busy?: string;
  /** Not pressable yet — a body field that has no valid value. */
  disabled?: boolean;
};

export type ConfirmSpec = {
  title: string;
  body?: string;
  /** Default: the host's translated "Cancel". */
  cancel?: string;
  /** The deliberate answer, drawn filled and last. */
  answer: ConfirmAnswer;
  /** An optional middle answer, drawn plain: Discard beside Save, Close tab
   *  beside Close all. */
  plain?: ConfirmAnswer;
  /** Enter presses `answer`. Default: unless it is dangerous. */
  enter?: boolean;
  /** Escape and the backdrop cancel. Default true. */
  dismissable?: boolean;
};

export type ConfirmResult = "answer" | "plain" | null;

export type PendingConfirm = {
  spec: ConfirmSpec;
  resolve: (r: ConfirmResult) => void;
};

const queue: PendingConfirm[] = [];
const listeners = new Set<() => void>();

function notify(): void {
  for (const fn of listeners) fn();
}

/** Ask, and get the answer: which button, or null for Cancel/Escape. */
export function ask(spec: ConfirmSpec): Promise<ConfirmResult> {
  return new Promise((resolve) => {
    queue.push({ spec, resolve });
    notify();
  });
}

/** The yes/no form: true when the deliberate answer was pressed. */
export async function confirm(spec: ConfirmSpec): Promise<boolean> {
  return (await ask(spec)) === "answer";
}

/** The question on screen, if any. Questions asked while one is up wait
 *  their turn rather than replacing it. */
export function pending(): PendingConfirm | null {
  return queue[0] ?? null;
}

export function settle(p: PendingConfirm, r: ConfirmResult): void {
  const i = queue.indexOf(p);
  if (i < 0) return;
  queue.splice(i, 1);
  p.resolve(r);
  notify();
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
