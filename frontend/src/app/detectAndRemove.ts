/** "Detect and remove" — text removal's one special row shape, built in one
 *  place for the three menus that offer it (the sidebar's Remove text button,
 *  the grid context menu, the group tree's context menu).
 *
 *  Text removal paints out the item's STORED text regions and detects nothing
 *  itself — that is what keeps the removal and the Text tab from having two
 *  ideas of where the text is. So "detect and remove" is the same model with
 *  an OCR engine named beside it, and the id is where that travels, because
 *  every row in these menus is a model id and inventing a parallel channel
 *  for one of them is how a menu grows two kinds of row.
 */
import type { ModelInfo, TaskInfo } from "./api";

/** A model id may carry a "detect with this OCR engine first" rider —
 *  `lama_regions#detect=rapidocr_multi`. Split on it before enqueueing and
 *  send the tail as `detect_with`. */
export const DETECT_WITH = "#detect=";

/** One "read it, then remove" row per OCR engine — appended to the Remove
 *  text menu. Each row carries the LaMa model's weight families as well as
 *  the engine's own, since running one is running both — the menus' readiness
 *  checks read exactly that list. `done` names engines that have already read
 *  the file (known for a single item; a scope menu passes nothing, since the
 *  answer differs per item and the reading reconciles anyway). */
export function detectAndRemoveRows(
  tasks: TaskInfo[], done: Iterable<string> = [],
): ModelInfo[] {
  const modelsOf = (k: string) =>
    tasks.find((tk) => tk.kind === k)?.models ?? [];
  const lama = modelsOf("text_removal").find((m) => m.id === "lama_regions");
  if (!lama) return [];
  const doneSet = new Set(done);
  return modelsOf("ocr")
    .filter((m) => !doneSet.has(m.id))
    .map((m) => {
      // The engine's OWN finest name — several RapidOCR variants share a
      // `name` and differ only in `variant` (Korean, Cyrillic), so a row
      // built from the name alone would list two identical entries.
      const who = m.variant ? `${m.name} · ${m.variant}` : m.name;
      return {
        ...m,
        id: `lama_regions${DETECT_WITH}${m.id}`,
        name: `${who} — read it, then remove`,
        family: "Text removal",
        variant: `${who} — read it, then remove`,
        note: m.note,
        available: m.available && lama.available,
        family_keys: [...(m.family_keys ?? []), ...(lama.family_keys ?? [])],
      };
    });
}
