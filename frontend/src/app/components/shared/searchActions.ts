/** The two ways a row can send you to the Library: search for this, or add
 *  this to the search you are already running.
 *
 *  A tag, a subject, a place and an event are all the same kind of thing here
 *  — something the grid can be narrowed to — and they are listed in four
 *  different places (the sidebar's four sections, and the four lists of the
 *  Tags tab). Four copies of "compose a condition and hand it to the search
 *  field" is four chances for one of them to compose it differently, so the
 *  condition is built HERE, once per kind.
 *
 *  Adding is offered ONLY while there is a search to add to: with an empty
 *  field the two entries would do exactly the same thing, and the one that
 *  reads as a refinement would be the lie.
 */
import { escapeName } from "../../../query/tree";
import { useUI } from "../../store";
import { useT } from "../../i18n";
import type { RowAction } from "./RowMenu";

/** What a row is, for the purpose of naming it in a query. */
export type SearchKind = "tag" | "subject" | "place" | "event";

/** The condition that finds the pictures carrying `name`.
 *
 *  A subject and an event say what is being ASKED rather than how it is
 *  stored — each IS a tag, but "who is in this picture" is the question and
 *  `SUBJECT:` is the statement.
 *
 *  A PLACE names its identity TAG, which is not `PLACE:` at all. That
 *  condition matches the address, so it would answer for the next town of
 *  that name and for anything else whose address happens to contain the
 *  word; the tag is exact, and it is what the item actually carries.
 */
export function searchCondition(kind: SearchKind, name: string): string {
  const n = escapeName(name);
  return kind === "subject" ? `SUBJECT:${n}`
    : kind === "event" ? `EVENT:${n}`
    : n;   // a place is its identity tag, like any other tag
}

/** Build the row-menu entries for one thing, by kind and identity tag. */
export function useSearchActions(): (kind: SearchKind, name: string,
                                     label?: string) => RowAction[] {
  const t = useT();
  const search = useUI((s) => s.search);
  const setSearch = useUI((s) => s.setSearch);
  const showAllItems = useUI((s) => s.showAllItems);
  const setView = useUI((s) => s.setView);
  const closeItemWindow = useUI((s) => s.closeItemWindow);
  return (kind, name, label) => {
    if (!name) return [];
    const cond = searchCondition(kind, name);
    const go = (q: string) => {
      // The item window is an overlay OVER the library, so it goes with the
      // rest of it — a grid narrowed behind a picture is a result nobody can
      // see. The scope opens up too: a search run inside one group finds
      // nothing when the pictures are somewhere else, which reads as "there
      // are none" rather than "you are looking in one room".
      closeItemWindow();
      showAllItems();
      setSearch(q);
      setView("library");
    };
    const base = search.trim();
    const out: RowAction[] = [{
      icon: "search",
      label: t("Find every picture with this"),
      hint: label ? `${t("Searches the library for")} ${label}` : undefined,
      onClick: () => go(cond),
    }];
    if (base) {
      out.push({
        icon: "search_insights",
        label: t("Add to the search"),
        hint: t("Narrows what the grid is already showing"),
        onClick: () => go(`${base} ${cond}`),
      });
    }
    return out;
  };
}
