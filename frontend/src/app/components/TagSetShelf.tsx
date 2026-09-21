/** THE ROW OF TAG SETS, and everything a whole set can have done to it.
 *
 *  The Tags tab's list is ONE list (owner 2026-09) — the library's own names
 *  and an imported set's are the same two columns — so what is left that is
 *  about a SET rather than about a name lives here: the pills, and the
 *  PENCIL that opens the list of them (`TagSetManageOverlay`), where a set
 *  is made, imported, reordered, hidden, described or taken away.
 *
 *  THE PILLS CARRY NO VERBS ANY MORE (owner 2026-09). Each held a ⋯ with
 *  the whole set of them, which the list behind the pencil now holds — two
 *  doors a few pixels apart, and the one in the pill could only ever act on
 *  a set whose pill was on screen.
 *
 *  THE PILLS DO NOT DRAG ANY MORE (owner 2026-09). Reordering is a handle in
 *  that list, where the library's own row can be pinned out of it — the pill
 *  drag had no such row and nothing stopped it carrying the library, despite
 *  the comment two files away saying it could not.
 *
 *  Its own component because it is its own thing, not because the list needs
 *  it split: the list below is about names, and every verb here is about the
 *  tag set they are names IN.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api, TagSetOut } from "../api";
import { downloadBlob } from "../csv";
import { useErrText, useT } from "../i18n";
import { bumpEdits } from "../invalidation";
import { useUI } from "../store";
import { TagSetPills } from "./TagSetPills";
import { TagSetManageOverlay } from "./TagSetManageOverlay";
import { TagSetCsvOverlay } from "./TagSetCsvOverlay";
import { useTagSetFileImport } from "./SettingsTagSets";
import { TagSetPropertiesOverlay } from "./TagSetsView";

export function TagSetShelf({ sets, setId, onPick, onChanged }: {
  sets: TagSetOut[];
  /** The tag set on screen — the library's own id (or 0 while its row is
   *  still lazy) when the library's names are what the list holds. */
  setId: number;
  /** Picking a pill: an id for an imported set, null for the library. */
  onPick: (id: number | null) => void;
  onChanged: () => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  const errText = useErrText();
  const setTagSetId = useUI((s) => s.setTagSetId);
  const [error, setError] = useState<string | null>(null);
  const [propsFor, setPropsFor] = useState<TagSetOut | null>(null);
  const [csvFile, setCsvFile] = useState<{ file: File } | null>(null);
  const [managing, setManaging] = useState(false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["tag-sets"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    bumpEdits();
    onChanged();
  };
  const pick = (id: number) => {
    const one = sets.find((x) => x.id === id);
    onPick(one?.library ? null : id);
  };
  const fileImport = useTagSetFileImport((made) => pick(made.id),
                                         (file) => setCsvFile({ file }));
  /** THE LIBRARY'S OWN TAG SET as a tag-set file. Its own route, since
   *  the library's set row is lazy and need not have an id yet. */
  const exportLibrary = async () => {
    try {
      const doc = await api.exportLibrary();
      downloadBlob("library.json",
                   new Blob([JSON.stringify(doc, null, 2)],
                            { type: "application/json" }));
    } catch (e) { setError(errText(e)); }
  };
  // Every OTHER set's name, lowercased — what a new name may not be.
  const takenNames = (except?: number) =>
    sets.filter((s) => s.id !== except).map((s) => s.name.trim().toLowerCase());
  /** `want`, or the first `want 2`, `want 3`… no set is called yet.
   *
   *  A SET NAMES ITSELF NOW (owner 2026-09): making one is a press in the
   *  Add menu rather than a form with a name field, so the name has to be
   *  one nothing else has — the server refuses a duplicate, and a refusal
   *  is not what a person pressing "New empty set" asked for. Renaming it
   *  is the row's own Properties, one line below where it appears. */
  const freeName = (want: string) => {
    const taken = new Set(takenNames());
    if (!taken.has(want.trim().toLowerCase())) return want;
    for (let n = 2; ; n++) {
      const next = `${want} ${n}`;
      if (!taken.has(next.trim().toLowerCase())) return next;
    }
  };
  const newEmptySet = async () => {
    const made = await api.createTagSet({ name: freeName(t("New set")) });
    pick(made.id);
    invalidate();
  };
  /** A COPY OF A SET YOU CAN EDIT. On a built-in this is what the Add
   *  menu's shipped-template rows used to be: the server writes the shipped
   *  file into a new ordinary set, which is why it takes the same seconds a
   *  template press took. */
  const duplicate = async (s: TagSetOut) => {
    const made = await api.duplicateTagSet(
      s.id, freeName(t("{name} (copy)", { name: s.name })));
    pick(made.id);
    invalidate();
  };
  return (
    <>
      <TagSetPills sets={sets} setId={setId} setPickedId={pick}
                   onManage={() => setManaging(true)} />
      {/* An ERROR stays here, beside what failed: it is not a status
          message, and a red line where the action was asked for is where
          somebody looks for it. */}
      {error && (
        <div style={{ color: "var(--red-text)", fontSize: "var(--fs-3)",
                      marginTop: 6 }}>{error}</div>
      )}
      {propsFor && (
        <TagSetPropertiesOverlay
          set={sets.find((x) => x.id === propsFor.id) ?? propsFor}
          onClose={() => setPropsFor(null)}
          onSaved={() => { setPropsFor(null); invalidate(); }} />
      )}
      {csvFile && (
        <TagSetCsvOverlay file={csvFile.file} into={null}
                          taken={takenNames()}
                          onClose={() => setCsvFile(null)}
                          onDone={(made) => { setCsvFile(null); pick(made.id);
                                              invalidate(); }} />
      )}
      {managing && (
        <TagSetManageOverlay
          sets={sets}
          onClose={() => setManaging(false)}
          onNew={newEmptySet}
          onDuplicate={duplicate}
          onImport={() => fileImport.pick()}
          onProperties={(s) => { pick(s.id); setPropsFor(s); }}
          onExportLibrary={() => void exportLibrary()}
          // DELETING THE SET ON SCREEN puts the list back on the library:
          // the pill row would otherwise be lit on an id nothing answers to
          // and the list below would page against it.
          onGone={(id) => { if (id === setId) setTagSetId(null); }}
          onChanged={invalidate} />
      )}
      {fileImport.input}
    </>
  );
}
