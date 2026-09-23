/** THE MODEL ACTIONS AS MENU ROWS — one builder for both context menus.
 *
 *  The grid's right-click and the group tree's right-click both offer the
 *  Actions tab's runs: one row per section (Edit / Detect / Generate, from
 *  `ACTION_SECTIONS`), each opening its tasks, each task opening its READY
 *  models with the extra-output switch above them. Each menu used to draw
 *  that shape itself — its own readiness rule, its own family grouping, its
 *  own copy of the extra-output preference — and the two drifted the moment
 *  one was touched. This module is the shape ONCE, as `RowAction` trees the
 *  shared menu draws; the menus only say what a pick DOES.
 *
 *  Only READY models are offered: anything still needing setup, a download
 *  or a reference picker stays a sidebar affair, where its chip can explain
 *  itself. Remove text carries the sidebar's "read it, then remove" rows
 *  (`detectAndRemoveRows`) — alone over unread pages it would paint out
 *  nothing.
 */
import type { ModelCacheInfo, ModelInfo, TaskInfo } from "./api";
import { storage } from "../shared/storage.ts";
import { ACTION_SECTIONS, SECTION_ICON, SEQ_OK } from "./actionSections.ts";
import { detectAndRemoveRows } from "./detectAndRemove.ts";
import type { RowAction } from "../shared/RowMenu";

/** THE PANELS TASK'S "into a sequence" PREFERENCE — the one extra output
 *  any action still offers, and the only reason this is remembered rather
 *  than asked. Read through on every ask (never cached) so the sidebar's
 *  split button, the grid's menu and the tree's menu cannot answer a run
 *  differently. Defaults ON.
 *
 *  It had a neighbour, `mc.bgNewItem`, for the image tasks' "Create new
 *  item for result" switch; that option is gone and every action's result
 *  lands on the item it ran on. */
export const PANELS_SEQ_KEY = "mc.panelsSeq";
export function readPanelsSequence(): boolean {
  try {
    const v = storage.get(PANELS_SEQ_KEY);
    return v == null ? true : v === "1";
  } catch { return true; }
}
export function writePanelsSequence(on: boolean): void {
  try { storage.set(PANELS_SEQ_KEY, on ? "1" : "0"); }
  catch { /* ignore */ }
}

/** A task with the models the menu may run. */
export interface TaskRow {
  tk: TaskInfo;
  models: ModelInfo[];
}

/** The menus' readiness rule: available, no reference picker, and every
 *  source it needs cached. */
export function readyModel(cache: ModelCacheInfo[] | undefined) {
  const byKey = new Map((cache ?? []).map((m) => [m.key, m]));
  return (m: ModelInfo): boolean =>
    m.available && !m.needs_reference &&
    (m.family_keys ?? [])
      .map((k) => byKey.get(k))
      .filter((ci): ci is ModelCacheInfo => ci != null)
      .every((ci) => ci.cached);
}

/** The sections with their runnable tasks, in the table's order; a section
 *  with nothing to run is dropped. `okKind` lets a menu drop the kinds its
 *  targets cannot take (a video takes no editor). */
/** WHICH KINDS THE TARGETS CAN TAKE — the grid menu's own question, and
 *  the L key's: a video takes no editor, and a sequence container only
 *  the batch kinds (`SEQ_OK`). One rule for the context menu and for the
 *  shortcut that repeats what it last ran. */
export function targetsTake(kinds: readonly string[]): (kind: string) => boolean {
  const hasVideo = kinds.includes("video");
  const hasSeq = kinds.includes("sequence");
  const allSeq = kinds.length > 0 && kinds.every((k) => k === "sequence");
  return (k) => SEQ_OK.has(k)
    ? !hasVideo && (allSeq || !hasSeq)
    : !hasVideo && !hasSeq;
}

export function taskSections(
  tasks: TaskInfo[] | undefined,
  ready: (m: ModelInfo) => boolean,
  okKind: (kind: string) => boolean = () => true,
): { label: string; rows: TaskRow[] }[] {
  const all = tasks ?? [];
  return ACTION_SECTIONS.map((sec) => ({
    label: sec.label,
    rows: sec.kinds
      .map((k) => all.find((tk) => tk.kind === k))
      .filter((tk): tk is TaskInfo => tk != null && okKind(tk.kind))
      .map((tk) => ({ tk, models: (tk.kind === "text_removal"
        ? [...(tk.models ?? []), ...detectAndRemoveRows(all)]
        : tk.models ?? []).filter(ready) }))
      .filter((r) => r.models.length > 0),
  })).filter((sec) => sec.rows.length > 0);
}

/** The name a pick is recorded and toasted under — the family alone where
 *  it has one variant, else family and variant. */
export function modelDisplayName(m: ModelInfo, siblings: number): string {
  const family = m.family || m.name;
  if (siblings <= 1) return family;
  return m.variant ? `${family} ${m.variant}` : m.name;
}

/** ONE TASK'S MODEL PANEL: the extra-output switch where the task offers
 *  one, then the ready models in family order — one row per model, the
 *  family's first row separated from the family before it, so a family of
 *  variants reads as a block without a third level of menu. */
export function modelRows(
  row: TaskRow,
  t: (s: string) => string,
  run: (kind: string, model: string, name: string) => void,
  opts: { disabled?: boolean; onExtraOutput?: () => void } = {},
): RowAction[] {
  const out: RowAction[] = [];
  const kind = row.tk.kind;
  if (row.tk.sequence_option) {
    out.push({
      label: t("Place panels in a sequence"),
      hint: t("Group the detected panels into a new sequence (one per page) instead of loose linked items"),
      checked: readPanelsSequence(),
      keepOpen: true,
      onClick: () => {
        writePanelsSequence(!readPanelsSequence());
        opts.onExtraOutput?.();
      },
    });
  }
  const byFamily = new Map<string, ModelInfo[]>();
  for (const m of row.models) {
    const fam = m.family || m.name;
    const list = byFamily.get(fam);
    if (list) list.push(m); else byFamily.set(fam, [m]);
  }
  for (const fam of byFamily.values()) {
    fam.forEach((m, i) => {
      const name = modelDisplayName(m, fam.length);
      out.push({
        // A variant reads under its family's first row; a lone model is
        // its family's name. The recorded NAME carries both either way.
        label: fam.length > 1 && m.variant ? m.variant : name,
        hint: m.note || undefined,
        // A rule above each family, and above the first where the switch
        // row leads — never as the panel's first line.
        separated: i === 0 && out.length > 0,
        disabled: opts.disabled,
        onClick: () => run(kind, m.id, name),
      });
    });
  }
  return out;
}

/** THE SECTION ROWS — Edit, Detect, Generate, each a submenu of its tasks,
 *  each task a submenu of its models. `trailing` puts a count on the
 *  section row (the tree's menu says how many items a run would cover). */
export function aiActionRows(
  sections: { label: string; rows: TaskRow[] }[],
  t: (s: string) => string,
  run: (kind: string, model: string, name: string) => void,
  opts: { disabled?: boolean; trailing?: string; separatedFirst?: boolean;
          onExtraOutput?: () => void } = {},
): RowAction[] {
  return sections.map((sec, i) => ({
    icon: SECTION_ICON[sec.label] ?? "auto_awesome",
    label: t(sec.label),
    trailing: opts.trailing,
    separated: i === 0 && !!opts.separatedFirst,
    children: sec.rows.map((row) => ({
      icon: row.tk.icon,
      label: t(row.tk.label),
      children: modelRows(row, t, run, {
        disabled: opts.disabled, onExtraOutput: opts.onExtraOutput,
      }),
      onClick: () => {},
    })),
    onClick: () => {},
  }));
}
