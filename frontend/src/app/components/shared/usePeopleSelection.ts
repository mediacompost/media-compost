/** The row selection shared by an item's Subjects / Places / Events lists, and
 *  the selection-bar report that goes with it.
 *
 *  Lifted out of the properties panel because the ANNOTATOR shows the same
 *  three lists now, and a second copy of these rules would be a second dialect
 *  of them: which key names a row, when a selection is cleared, what removing
 *  one means, and which of the picks are still a machine's guess. Two lists
 *  that disagree about any of those are two different features wearing one
 *  name.
 *
 *  A SUBJECT is keyed by its APPEARANCE, not its tag: the same person can be
 *  in one picture twice, at two faces or at two ages, and keying by the tag
 *  made picking either of them light up both.
 *
 *  One selection PER TAB rather than one across all three. The rows really are
 *  all tag assignments and the one action they share is taking them off — but
 *  with a tab each, a selection made in Subjects and still counted while
 *  Places is showing is a Remove aimed at rows nobody can see.
 */
import { useEffect, useMemo } from "react";

import { api, EventRow, ItemDetail, PlaceRow } from "../../api";
import { eventsOnItem } from "../EventsSection";
import { rowKey } from "../PeopleSection";
import { placesOnItem } from "../PlacesSection";
import { SelectionReport } from "../../../shared/SelectionBar";
import { RowSelect, useRowSelect } from "./useRowSelect";

/** Which of the three lists is showing — the one whose rows the bar acts on. */
export type PeopleTab = "subjects" | "places" | "events" | null;

export interface PeopleSelection {
  subjectSel: RowSelect;
  placeSel: RowSelect;
  eventSel: RowSelect;
  /** Whichever list is showing owns the bar. */
  sel: RowSelect;
  /** What to hand `SelectionBar`, or null when none of the three lists is
   *  showing. An EMPTY list still reports — the bar shows for the list. */
  report: SelectionReport | null;
  /** Put every one of the three down — for a click on the panel's background. */
  clearAll: () => void;
  /** The TAG NAMES the current selection points at.
   *
   *  A subject, a place and an event are each extra data on a tag, so picking
   *  one in the sidebar is pointing at a tag — and the annotator draws that
   *  tag's boxes for it, exactly as picking the tag's own row does. Names
   *  rather than row keys because that is all these rows know: a place row is
   *  its tag, and an appearance names a subject whose tag may be placed in
   *  several groups. */
  selectedTags: Set<string>;
}

export function usePeopleSelection({
  itemId, detail, places, events, tab, onChanged, removeTitle, removeTitleGuessed,
}: {
  itemId: number | null;
  detail: ItemDetail | null;
  places: PlaceRow[] | undefined;
  events: EventRow[] | undefined;
  tab: PeopleTab;
  /** Reload whatever the edit touched. */
  onChanged: () => void;
  removeTitle: string;
  /** Said instead when a guess is picked: removing one is remembered as wrong. */
  removeTitleGuessed: string;
}): PeopleSelection {
  const subjectKeys = useMemo(
    () => (detail?.subjects ?? []).flatMap((r) => (r.appearances.length
      ? r.appearances
      // Somebody on the item through their tag alone still gets a row, and it
      // still has to be selectable — `rowKey` names that case too.
      : [{ id: 0 }]).map((a) => rowKey({ subject: r, appearance: a }))),
    [detail]
  );
  const placeKeys = useMemo(
    () => placesOnItem(places, detail ?? null).map((p) => `p:${p.tag}`),
    [places, detail]
  );
  const eventKeys = useMemo(
    () => eventsOnItem(events, detail ?? null).map((e) => `e:${e.tag}`),
    [events, detail]
  );
  const subjectSel = useRowSelect(subjectKeys);
  const placeSel = useRowSelect(placeKeys);
  const eventSel = useRowSelect(eventKeys);
  const sel = tab === "places" ? placeSel : tab === "events" ? eventSel : subjectSel;

  const clearSubjects = subjectSel.clear;
  const clearPlaces = placeSel.clear;
  const clearEvents = eventSel.clear;
  // A selection that outlives what it pointed at is a Remove aimed at another
  // picture's rows.
  useEffect(() => { clearSubjects(); clearPlaces(); clearEvents(); },
    [itemId, clearSubjects, clearPlaces, clearEvents]);
  const clearAll = () => { clearSubjects(); clearPlaces(); clearEvents(); };

  // Which of the picked people are still a MACHINE's guess. With one of those
  // in the selection the bar offers Accept beside Remove — the same pair the
  // row itself carries, for as many rows as are picked.
  const pickedGuesses = useMemo(() => {
    if (tab !== "subjects") return [];
    const picked = new Set(subjectSel.selected);
    return (detail?.subjects ?? []).flatMap(
      (r) => r.appearances
        .filter((a) => a.assigned_by === "suggested"
          && picked.has(rowKey({ subject: r, appearance: a })))
        .map((a) => ({ appearance: a.id, face: a.face_id, subject: r.id })));
  }, [detail, subjectSel.selected, tab]);

  const acceptSelected = async () => {
    for (const g of pickedGuesses) {
      await api.editAppearance(g.appearance, { confirm: true });
    }
    onChanged();
  };
  // Take off everything picked — which for a GUESS is the same act as
  // rejecting it, so there is no second button for that. The two halves are
  // still two different writes: a refused guess is recorded as a refusal so
  // the next run does not offer it again, and a name somebody gave is simply
  // taken back.
  const removeSelected = async () => {
    const guessed = new Set(pickedGuesses.map((g) => `a:${g.appearance}`));
    const rest = sel.selected.filter((k) => !guessed.has(k));
    sel.clear();
    for (const g of pickedGuesses) {
      // Through the FACE where there is one: that path records the refusal, so
      // the next run does not offer the same wrong name again.
      if (g.face != null) await api.unnameFace(g.face, g.subject);
      else await api.removeAppearance(g.appearance);
    }
    for (const key of rest) {
      // An appearance is removed as an appearance — the person may be in the
      // picture twice, and taking the tag off would take BOTH.
      if (key.startsWith("a:")) await api.removeAppearance(Number(key.slice(2)));
      else await api.unassignItemTag(itemId as number, key.slice(2));
    }
    onChanged();
  };

  // Reported whenever one of the lists is SHOWING — not only once something
  // is picked, and not only once it has rows: the bar is where Select all
  // lives, and a control that only appears after you have already done the
  // thing by hand is a control nobody finds. Empty, the bar still says
  // "None selected", which is true, instead of coming and going with the rows.
  const report: SelectionReport | null = tab
    ? { count: sel.selected.length, total: sel.total,
        onSelectAll: sel.selectAll,
        // Returned, not discarded: the undo bar awaits this to know when
        // the removal has landed before asking the log what it wrote.
        onRemove: () => removeSelected(),
        onClear: () => sel.clear(),
        removeTitle: pickedGuesses.length ? removeTitleGuessed : removeTitle,
        ...(pickedGuesses.length ? {
          pending: pickedGuesses.length,
          onAccept: () => void acceptSelected(),
        } : {}) }
    : null;

  // Only the SHOWING list's picks count: a selection left behind in Subjects
  // while Places is open is not something the picture should still be lit up
  // for, the same reason the bar ignores it.
  const selectedTags = useMemo(() => {
    const out = new Set<string>();
    if (tab === "places" || tab === "events") {
      for (const key of sel.selected) out.add(key.slice(2));
      return out;
    }
    if (tab !== "subjects") return out;
    const picked = new Set(sel.selected);
    for (const r of detail?.subjects ?? []) {
      const rows = r.appearances.length ? r.appearances : [{ id: 0 }];
      if (rows.some((a) => picked.has(rowKey({ subject: r, appearance: a }))))
        out.add(r.tag);
    }
    return out;
  }, [tab, sel.selected, detail]);

  return { subjectSel, placeSel, eventSel, sel, report, clearAll, selectedTags };
}
