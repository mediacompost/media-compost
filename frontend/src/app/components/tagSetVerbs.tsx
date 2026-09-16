/** WHAT A ROW OF AN IMPORTED SET CAN HAVE DONE TO IT.
 *
 *  The Tags tab's list is ONE list for both tag sets (owner 2026-09):
 *  the library's own names and an imported set's are the same two columns,
 *  the same rows, the same header. What differs is the VERBS — a library
 *  tag is renamed, merged and assigned; a set's name is advice, so its row
 *  offers to make the library's tag say what the set says, or to make the
 *  tag at all.
 *
 *  So the list stays one component and the verbs are a hook per
 *  tag set. This is the set's; the library's live in `TagsView` beside
 *  the rest of what only the library can do.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api } from "../api";
import { confirm } from "../../shared/ConfirmModal";
import type { TagRow } from "../api";
import { useErrText, useT, useTn } from "../i18n";
import { bumpEdits } from "../invalidation";
import type { RowAction } from "./shared/RowMenu";
import { useUI } from "../store";

export interface TagSetVerbs {
  /** One row's menu — the same list its ⋯ and a right-click on it open. */
  rowActions: (row: TagRow, ids: number[]) => RowAction[];
  /** …and the selection's, which the toolbar's ⋯ holds. */
  selectionActions: (ids: number[], rows: TagRow[]) => RowAction[];
  /** What the last verb said, for the toolbar's quiet line. */
  note: string | null;
  error: string | null;
  clearNote: () => void;
  /** The row the editor is open on, and the way to open it. */
  editing: TagRow | null;
  setEditing: (r: TagRow | null) => void;
  /** …and whether it is open on NOTHING, which is how a name is added. */
  creating: boolean;
  setCreating: (on: boolean) => void;
  /** The spelling being made, over no entry in particular. */
  addingAlias: boolean;
  setAddingAlias: (on: boolean) => void;
}

/** Does anything picked have advice a sync could act on? A row whose set
 *  says nothing, whose branch has implications switched off, or whose tag
 *  the LIBRARY does not have has no business offering the verb — in the
 *  last case there is no tag for the advice to hang on, and the row offers
 *  to add it instead. */
const anyImplies = (rows: TagRow[]) =>
  rows.some((r) => r.in_library
    && (((r.implies ?? []).length > 0 && !r.implications_off)
        || (r.comment ?? "") !== "" || r.subject != null || r.place != null
        || r.event != null));
/** …and does anything picked sit INSIDE something? The parents are their
 *  own verb, so the row offers it only where there is a hierarchy to
 *  build. */
const anyParents = (rows: TagRow[]) =>
  rows.some((r) => r.in_library
    && ((r.place?.parent ?? "") !== "" || (r.event?.parent ?? "") !== ""));
/** …and is anything picked NOT in the library? Over a mixed selection both
 *  verbs appear, each acting on the rows it is about. */
const anyMissing = (rows: TagRow[]) => rows.some((r) => !r.in_library);

export function useTagSetVerbs(setId: number | null,
                               onChanged: () => void): TagSetVerbs {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const errText = useErrText();
  const setTagsView = useUI((s) => s.setTagsView);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<TagRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [addingAlias, setAddingAlias] = useState(false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["tag-sets"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    bumpEdits();
    onChanged();
  };
  const run = async (f: () => Promise<unknown>) => {
    setNote(null);
    try { await f(); setError(null); invalidate(); }
    catch (e) { setError(errText(e)); }
  };

  const deleteEntries = async (ids: number[], name = "") => {
    if (setId == null || ids.length === 0) return;
    if (!(await confirm({
      title: ids.length === 1
        ? t("Delete the entry “{name}”?", { name: name || String(ids[0]) })
        : tn({ one: "Delete {n} entry?", other: "Delete {n} entries?" }, ids.length),
      answer: { label: t("Delete"), danger: true },
    }))) return;
    void run(async () => {
      for (const id of ids) await api.deleteTagSetEntry(setId, id);
    });
  };

  /** THE VERB FOR A ROW THE LIBRARY HAS NEVER HEARD OF. A set is advice
   *  about tags, and until the tag exists there is nothing for the advice
   *  to be about — so the row offers to make it real. It goes through the
   *  DOOR, so the tag arrives with what its set says: an alias name creates
   *  the canonical, and the entry's implied names are minted with it. */
  const addToLibrary = (ids: number[]) => {
    if (setId == null || ids.length === 0) return;
    void run(async () => {
      const r = await api.addTagSetEntriesToLibrary(setId, ids);
      setNote(r.added === 0
        ? t("Already in the library")
        : tn({ one: "Added {n} tag to the library",
               other: "Added {n} tags to the library" }, r.added));
    });
  };

  /** MAKE THE LIBRARY'S TAG SAY WHAT THE SET SAYS — what the name entails,
   *  the line it carries, and whether it is a subject, a place or an event.
   *  ONE VERB for all of it, because the door applies all of it at one
   *  moment (when it CREATES the tag) and a tag that was already there has
   *  heard none of it. */
  const syncEntries = async (ids: number[], mode: "append" | "replace") => {
    if (setId == null || ids.length === 0) return;
    if (mode === "replace" && !(await confirm({
      title: tn({ one: "Make {n} tag say exactly what the set says?",
                  other: "Make {n} tags say exactly what the set says?" }, ids.length),
      body: t("What the library has is overwritten, and implications the set does not name are removed."),
      answer: { label: t("Overwrite"), danger: true },
    }))) return;
    void run(async () => {
      const r = await api.syncTagSetEntries(setId, ids, mode);
      setNote(r.tags === 0
        ? t("Nothing to sync — the library does not have these tags yet.")
        : r.removed
          ? t("{added} added, {removed} removed.",
              { added: r.added, removed: r.removed })
        : r.added === 0
          ? t("Already in step — nothing to add.")
          : tn({ one: "{n} thing written.", other: "{n} things written." },
               r.added));
    });
  };

  /** …AND THE PARENTS, which are their own verb: following one MINTS that
   *  tag, and its parent above it, so over four hundred picked rows it
   *  fills the catalog rather than describing what was picked. */
  const syncParents = (ids: number[], mode: "append" | "replace") => {
    if (setId == null || ids.length === 0) return;
    void run(async () => {
      const r = await api.syncTagSetParents(setId, ids, mode);
      setNote(r.tags === 0
        ? t("Nothing to place — these tags have no record to put inside one.")
        : tn({ one: "{n} put in its place.",
               other: "{n} put in their places." }, r.added));
    });
  };

  const addActions = (ids: number[]): RowAction[] => [
    { icon: "library_add", separated: true, label: t("Add to library"),
      onClick: () => addToLibrary(ids) },
  ];
  const syncActions = (ids: number[]): RowAction[] => [
    { icon: "sync", separated: true, label: t("Tag in library"),
      children: [
        { icon: "add", label: t("Add missing info"),
          onClick: () => syncEntries(ids, "append") },
        { icon: "sync_alt", label: t("Replace with the set's"),
          onClick: () => syncEntries(ids, "replace") },
      ],
      onClick: () => {} },
  ];
  const parentActions = (ids: number[]): RowAction[] => [
    { icon: "account_tree", label: t("Parent hierarchy"),
      children: [
        { icon: "add", label: t("Add missing info"),
          onClick: () => syncParents(ids, "append") },
        { icon: "sync_alt", label: t("Replace with the set's"),
          onClick: () => syncParents(ids, "replace") },
      ],
      onClick: () => {} },
  ];
  /** WHAT A SPELLING'S ROW OFFERS. An alias has no description, no category
   *  and no records, so the entry menu's verbs are about a tag it does not
   *  have: what is left is where it points, and taking it away. */
  const aliasActions = (row: TagRow, ids: number[]): RowAction[] => [
    { icon: "arrow_forward", label: t("Show the tag it stands for"),
      onClick: () => setTagsView({ focus: row.alias_of ?? "" }) },
    { icon: "delete", danger: true, separated: true, label: t("Delete"),
      hint: t("The spelling goes; the tag it stood for stays"),
      onClick: () => deleteEntries(ids, row.name) },
  ];

  const selectionActions = (ids: number[], rows: TagRow[]): RowAction[] => {
    const one = ids.length === 1 ? rows[0] : undefined;
    return [
      // EDIT IS THE VERB FOR ONE ROW, and one picked row is one row: the
      // toolbar's ⋯ is the selection's menu, and a selection of one that
      // cannot be edited from it sends you back to the row to find its
      // pencil.
      ...(one && !one.alias_of
          ? [{ icon: "edit", label: t("Edit"),
               onClick: () => setEditing(one) }] : []),
      ...(anyMissing(rows) ? addActions(ids) : []),
      ...(anyImplies(rows) ? syncActions(ids) : []),
      ...(anyParents(rows) ? parentActions(ids) : []),
      // NO COUNT: the menu already says what it is about — its heading over
      // a right-click, the button's own label over the toolbar's ⋯ — and
      // repeating the number on every item reads as a different scope.
      { icon: "delete", danger: true, separated: true, label: t("Delete"),
        onClick: () => deleteEntries(ids) },
    ];
  };

  const rowActions = (row: TagRow, ids: number[]): RowAction[] => {
    if (ids.length > 1) return selectionActions(ids, [row]);
    if (row.alias_of) return aliasActions(row, ids);
    return [
      { icon: "edit", label: t("Edit"), onClick: () => setEditing(row) },
      ...(anyMissing([row]) ? addActions(ids) : []),
      ...(anyImplies([row]) ? syncActions(ids) : []),
      ...(anyParents([row]) ? parentActions(ids) : []),
      { icon: "delete", label: t("Delete"), danger: true, separated: true,
        onClick: () => deleteEntries(ids, row.name) },
    ];
  };

  return { rowActions, selectionActions, note, error,
           clearNote: () => { setNote(null); setError(null); },
           editing, setEditing, creating, setCreating,
           addingAlias, setAddingAlias };
}
