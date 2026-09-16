/** THE CONTEXT MENU'S "LAST USED" ROW — the pure half.
 *
 *  The grid's context menu offers every model action under Edit / Detect /
 *  Generate, each two boxes deep. A library is mostly tagged, captioned or
 *  face-detected with ONE model over and over, so the action picked last
 *  time is remembered (`localStorage`, one record) and offered again at the
 *  ROOT of the menu, beside those three rows — but only while the menu
 *  would offer it anyway: the kind must still be a row (a video selection
 *  offers no detector) and the model still among that row's READY models
 *  (a model removed or awaiting setup is not one a shortcut may run). */

export interface LastAction {
  kind: string;
  /** The model id as the menu sends it — a "read it, then remove" row
   *  carries its OCR engine on the id, and the shortcut must carry it too. */
  model: string;
  /** The task's label and the model's display name, as the row read them. */
  task: string;
  name: string;
}

export const LAST_ACTION_KEY = "mc.ctxLastAction";

export function parseLastAction(raw: string | null): LastAction | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw);
    if (v && typeof v === "object"
        && typeof v.kind === "string" && typeof v.model === "string"
        && typeof v.task === "string" && typeof v.name === "string"
        && v.kind && v.model) {
      return { kind: v.kind, model: v.model, task: v.task, name: v.name };
    }
  } catch { /* not ours */ }
  return null;
}

export function serializeLastAction(a: LastAction): string {
  return JSON.stringify(a);
}

/** The remembered action, if THIS menu still offers it (see above). */
export function offeredLastAction<R extends { tk: { kind: string }; models: { id: string }[] }>(
  last: LastAction | null, rows: readonly R[],
): { last: LastAction; row: R } | null {
  if (!last) return null;
  const row = rows.find((r) => r.tk.kind === last.kind);
  if (!row || !row.models.some((m) => m.id === last.model)) return null;
  return { last, row };
}
