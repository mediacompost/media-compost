/** THE DIALOGS A TAG SET'S CONTENT IS EDITED IN, and nothing else.
 *
 *  One entry (`EntryEditOverlay`: its name, the set's description of it, the
 *  comment and the three records the set says the name IS, a count, the
 *  category, its aliases and what it implies), one spelling
 *  (`AliasOverlay`), one category (`CategoryEditOverlay`: name, icon,
 *  parent, and the two advice switches as three-state rows) and the whole
 *  set (`TagSetPropertiesOverlay`).
 *
 *  THERE IS NO NEW-SET FORM HERE ANY MORE (owner 2026-09). `NameOverlay`
 *  asked for a name and offered a template picker; making a set is a press
 *  in the shelf's Add menu now — an empty one takes a default name, a
 *  template takes the template's own — and renaming it is the row's own
 *  Properties. It went with its `templates` query and its taken-names
 *  guard.
 *
 *  The LIST these open over is `TagsView`, which draws the library's own
 *  names and an imported set's with one component — see the note below.
 *  Every write here invalidates `["tag-sets"]` and bumps the edits, since
 *  the autocomplete and the capsules read the same rows. */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { useFrozen } from "../../shared/useFrozen";
import { RowShell, Section, ToggleRow } from "../../shared/SettingsRows";
import { SegmentedControl } from "../../shared/SegmentedControl";
import { Field, FieldLabel, fieldStyleSm } from "../../shared/Field";
import { RemoteParentField } from "./ParentField";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, TagSetCategoryOut, TagSetEntryOut, TagSetOut } from "../api";
import { useErrText, useLang, useT } from "../i18n";
import { tagFieldInput, tagFieldName } from "../tags";
import { ancestorsOf, flattenTree } from "../treeRows";
import { formatDate, isValid, parseDate } from "../../query/subjects/when";
import { tagDebounceMs, useDebouncedValue } from "../../shared/useDebounced";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { Icon } from "../../shared/Icon";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { CommentField, DescriptionField } from "./DescribedFields";
import { TagSuggestList, useSuggestList } from "./TagSuggestList";
import { RowMenu } from "./shared/RowMenu";
import { Switch } from "../../shared/Switch";

/** What a category may wear in place of the folder — a SMALL set, on
 *  purpose: the glyph is a hint at what kind of tags the category holds
 *  (people, clothing, places, style…), not a library of pictures. The folder
 *  is the default and is spelled "" in the row. */
export const CATEGORY_ICONS = [
  "folder", "person", "face", "groups", "checkroom", "pets", "landscape",
  "location_on", "palette", "brush", "photo_camera", "light_mode", "mood",
  "accessibility_new", "star", "label",
];

/** The tree flattened for a picker: parents before children, each with its
 *  depth. `banned` rows (a category and everything under it, for its own
 *  Parent field) are left out. */
function categoryRows(cats: TagSetCategoryOut[], banned?: Set<number>) {
  return flattenTree(
    [...cats].sort((a, b) => a.position - b.position || a.id - b.id), new Set())
    .filter(({ row }) => !banned?.has(row.id));
}

function categoryOptions(cats: TagSetCategoryOut[], banned?: Set<number>) {
  return categoryRows(cats, banned).map(({ row, depth }) => (
    <option key={row.id} value={row.id}>{"\u00a0\u00a0\u00a0".repeat(depth) + row.name}</option>
  ));
}

// The field and its label are the shared ones (`shared/Field.tsx`).
const field = fieldStyleSm;
const Label = FieldLabel;

/* THE SET'S OWN LIST IS GONE (owner 2026-09).
 *
 * A 1,400-line component drew an imported set's entries: its own header
 * band, its own row, its own toolbar, its own paging, its own idea of what
 * a count column is. The library's names and a set's are ONE list now
 * (`TagsView`), so what is left in this file is the DIALOGS a name of a set
 * is edited in — the entry editor, the spelling, the category, the set's
 * properties and its name — which the one list opens.
 *
 * AND THE ROW OUTLIVED THE LIST by a fortnight: `EntryRow` and its four
 * helpers, 449 lines nothing rendered, plus twenty-nine imports and
 * constants left holding nothing. Dead code is not free here — the row
 * read as the place a tag-set row is drawn, so it was the file somebody
 * would edit to change one. Taking a list out means taking out what it
 * called: `tsc --noUnusedLocals` over the file says what that is, and the
 * project's own config has the flag off.
 */



export function EntryEditOverlay({ set, cats: catsLive, entry, defaultCategoryId, onClose, onSaved }: {
  set: TagSetOut; cats: TagSetCategoryOut[]; entry: TagSetEntryOut | null;
  defaultCategoryId: number | null;
  onClose: () => void; onSaved: () => void;
}) {
  // The tree as it was when the dialog opened (`useFrozen`): a rename
  // landing elsewhere must not rebuild the parent list under the pointer.
  const cats = useFrozen(catsLive, entry?.id) ?? catsLive;
  const t = useT();
  const errText = useErrText();
  const [name, setName] = useState(entry?.name ?? "");
  const [description, setDescription] = useState(entry?.description ?? "");
  const [count, setCount] = useState(entry?.count != null ? String(entry.count) : "");
  const [categoryId, setCategoryId] = useState<number | null>(entry ? entry.category_id : defaultCategoryId);
  // The entry's other spellings are ROWS of their own now, made and edited
  // in the list; this holds what the entry already has so a save carries
  // them through untouched rather than clearing them.
  const [aliases] = useState(entry?.aliases.join(" ") ?? "");
  const [implies, setImplies] = useState(entry?.implies.join(" ") ?? "");
  // THE LABELS THE SET PUTS ON THIS NAME — its own meta tags. A plain
  // space-separated field like `implies`, and for the same reason: a label
  // is a name in the tag set's OTHER list, and a name the set does not
  // know yet is MADE when this entry is saved.
  const [meta, setMeta] = useState(entry?.meta.join(" ") ?? "");
  const [comment, setComment] = useState(entry?.comment ?? "");
  // WHAT THE SET SAYS THE TAG IS. Each record is its own piece of state and
  // null means "the set does not say" — which is not the same as an empty
  // one, since "this name is a person" is the whole of what a tag set
  // often knows.
  const lang = useLang();
  const [records, setRecords] = useState<RecordDraft>(
    () => draftOf(entry, lang));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const list = (s: string) => s.split(/[,\s]+/).map(tagFieldName).filter(Boolean);
  const recs = useMemo(() => wireRecords(records, lang), [records, lang]);
  const wanted = {
    name: tagFieldName(name), description, count: count.trim() === "" ? null : Number(count),
    category_id: categoryId, aliases: list(aliases), implies: list(implies),
    meta: list(meta),
  };
  const dirty = !entry
    ? wanted.name !== "" || description !== "" || count !== "" || aliases !== ""
      || implies !== "" || meta !== "" || comment !== "" || recs.dirty
    : wanted.name !== entry.name || description !== entry.description
      || wanted.count !== entry.count || categoryId !== entry.category_id
      || wanted.aliases.join(" ") !== entry.aliases.join(" ")
      || wanted.implies.join(" ") !== entry.implies.join(" ")
      || wanted.meta.join(" ") !== entry.meta.join(" ")
      || comment !== (entry.comment ?? "")
      || JSON.stringify(recs.wire) !== JSON.stringify(wireOf(entry));
  const canSave = wanted.name !== "" && (wanted.count == null || Number.isFinite(wanted.count))
    && !recs.bad && !busy;

  /** THE IMPLIED NAMES THIS SET DOES NOT HAVE YET, made as entries of it.
   *
   *  Exact-name lookups, one per typed name — a person types a few, and the
   *  alternative is a second idea of what the set holds. A name the set
   *  knows as an ALIAS is refused by the server (it is already that entry,
   *  said differently), and that refusal is the answer, not an error. */
  const ensureImplied = async (names: string[]) => {
    for (const n of names) {
      const got = await api.tagSetEntryIndex(set.id, n);
      if (got.id != null) continue;
      try { await api.createTagSetEntry(set.id, { name: n }); }
      catch { /* an alias of another entry — there is nothing to make */ }
    }
  };

  const save = async () => {
    if (!canSave) return;
    setBusy(true);
    try {
      await ensureImplied(wanted.implies);
      if (entry) {
        await api.updateTagSetEntry(set.id, entry.id, {
          name: wanted.name, description, aliases: wanted.aliases,
          implies: wanted.implies, meta: wanted.meta, comment,
          // ALL THREE KINDS, always: this dialog is the whole entry, so a
          // record it does not show is one it means to take away.
          records: { kinds: RECORD_KINDS, ...recs.wire },
          ...(wanted.count == null ? { clear_count: true } : { count: wanted.count }),
          ...(categoryId == null ? { clear_category: true } : { category_id: categoryId }),
        });
      } else {
        await api.createTagSetEntry(set.id, {
          name: wanted.name, description, count: wanted.count, category_id: categoryId,
          aliases: wanted.aliases, implies: wanted.implies,
          meta: wanted.meta, comment,
          ...recs.wire,
        });
      }
      onSaved();
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  return (
    <Overlay onSubmit={() => void save()} icon="sell" title={entry ? t("Edit entry") : t("Add entry")}
      subtitle={set.name} width={520} onClose={onClose}
      unsaved={{ dirty, onSave: save, t }}
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, alignItems: "center" }}>
          {error && <span style={{ color: "var(--red-text)", fontSize: "var(--fs-3)", marginRight: "auto" }}>{error}</span>}
          <Button variant="ghost" onClick={onClose} icon="close">{t("Cancel")}</Button>
          <Button variant="primary" onClick={() => void save()} icon="check" disabled={!canSave}>
            {entry ? t("Save") : t("Add")}
          </Button>
        </div>
      }>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 18 }}>
        <div>
          <Label>{t("Tag")}</Label>
          <input value={name} autoFocus onChange={(e) => setName(tagFieldInput(e.target.value))}
                 
                 placeholder={t("a_tag_name")} style={{ ...field, fontFamily: "var(--mono)" }} />
        </div>
        {/* THE COMMENT SITS WITH THE NAME. It is the line the tag itself
            wears — read beside the name everywhere — where the description
            below is the set's own paragraph about it, and putting a
            paragraph between a name and its one-line gloss read as two
            unrelated fields. */}
        <CommentField value={comment} onChange={setComment}
          onEnter={() => void save()}
          placeholder={t("The line the tag itself should carry…")} />
        <DescriptionField value={description} onChange={setDescription} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 12 }}>
          <div>
            <Label>{t("Count")}</Label>
            <input value={count} onChange={(e) => setCount(e.target.value.replace(/[^\d]/g, ""))}
                   placeholder={t("optional")} style={{ ...field, fontFamily: "var(--mono)" }} />
          </div>
          <div>
            <Label>{t("Category")}</Label>
            {/* A `<select>` draws its options in the OS widget's own font and
                cannot show a glyph, and the glyph is how the tree is read —
                so this is the shared `RowMenu`, which takes one per row, with
                the depth in the label the way `categoryOptions` had it. */}
            <RowMenu title={t("Category")} icon="folder" always color="var(--text)"
              buttonStyle={{ ...field, display: "flex", alignItems: "center",
                             gap: 8, cursor: "pointer", textAlign: "left" }}
              label={
                <span style={{ display: "flex", alignItems: "center", gap: 6,
                               flex: 1, minWidth: 0 }}>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                                 whiteSpace: "nowrap" }}>
                    {cats.find((c) => c.id === categoryId)?.name
                      ?? t("Uncategorized")}
                  </span>
                  <Icon name="arrow_drop_down" size={16}
                        style={{ marginLeft: "auto" }} />
                </span>
              }
              actions={[
                { icon: "label_off", label: t("Uncategorized"),
                  active: categoryId == null,
                  onClick: () => setCategoryId(null) },
                ...categoryRows(cats).map(({ row, depth }) => ({
                  icon: row.icon || "folder",
                  label: `${"\u00a0".repeat(depth * 3)}${row.name}`,
                  active: categoryId === row.id,
                  onClick: () => setCategoryId(row.id),
                })),
              ]} />
          </div>
        </div>
        {/* NO ALIASES FIELD. An alias is a ROW of its own, slotted under
            the entry it is a spelling of — which is what lets it be
            redirected and deleted on its own terms — and a thing that is a
            row is not also a field on another row. The list's Add menu
            makes one; the row's ⋯ points it elsewhere or takes it away.
            (The entry still SAVES its aliases: they are its own field on
            the wire, which is what makes every one of those an ordinary,
            revertible entry edit.) */}
        {/* WHAT IT ENTAILS, completed from THIS SET. An implication points
            at another entry of the same tag set far more often than not,
            and a name typed from memory into a plain box is how a set comes
            to entail `1girls` where it meant `1girl`. A name the set does
            not have yet is MADE in it when this entry is saved — the
            hierarchy of a tag set is built out of its own rows, and
            leaving the dialog to add the parent first is the errand that
            stops anybody building one. */}
        <div>
          <Label>{t("Implies")}</Label>
          <SetTagField setId={set.id} value={implies} onChange={setImplies}
            placeholder={t("tags it entails, space-separated")} />
        </div>
        {/* AND WHAT THE SET CALLS THIS NAME. A meta tag labels the NAME and
            never reaches a picture — "character", "noflip", "from a booru"
            — so it is not one of the tags above it: it is a name in the
            tag set's other list, which the sidebar's Meta tags row
            leads to. A label the set does not know yet is made with the
            save, the way an implied name is. */}
        <div>
          <Label>{t("Meta tags")}</Label>
          {/* RAW `onChange`: this is a LIST, and `tagFieldInput` turns a
              space into an underscore — the rule `SetTagField` keeps one
              field up. `list()` cleans each name at the save. */}
          <input value={meta} onChange={(e) => setMeta(e.target.value)}
                 
                 placeholder={t("labels on the name, space-separated")}
                 style={{ ...field, fontFamily: "var(--mono)" }} />
        </div>
        {/* WHAT KIND OF THING THE NAME IS — somebody, somewhere, or
            something that happened. Written when the name is first assigned
            and by the ⋯ menu's sync, like the comment above. */}
        <div style={{ borderTop: "1px solid var(--border-soft)",
                      paddingTop: 12, display: "flex",
                      flexDirection: "column", gap: 12 }}>
          {/* `person` here too, the marks' glyph and the items tag list's. */}
          <RecordSection setId={set.id} kind="subject" icon={RECORD_ICON.subject} title={t("Subject")}
            summary={t("a person, a character, a band, a cat")}
            rec={records.subject}
            onChange={(v) => setRecords((r) => (
              { ...r, subject: v as RecordDraft["subject"] }))} />
          <RecordSection setId={set.id} kind="place" icon="place" title={t("Place")}
            summary={t("somewhere, and what it is inside")}
            rec={records.place}
            onChange={(v) => setRecords((r) => (
              { ...r, place: v as RecordDraft["place"] }))} />
          <RecordSection setId={set.id} kind="event" icon={RECORD_ICON.event} title={t("Event")}
            summary={t("something that happened, over a span of days")}
            rec={records.event}
            onChange={(v) => setRecords((r) => (
              { ...r, event: v as RecordDraft["event"] }))} />
        </div>
      </div>
    </Overlay>
  );
}

/** THE THREE RECORDS AS THE DIALOG HOLDS THEM: null where the set says
 *  nothing, else the fields as TYPED — dates as text, since a half-typed
 *  date is not a number yet and the field must show what was typed. */
type RecordDraft = {
  subject: { name: string; since: string } | null;
  place: { name: string; lat: string; lon: string; parent: string } | null;
  event: { name: string; start: string; end: string; parent: string } | null;
};

const RECORD_KINDS: Array<"subject" | "place" | "event"> =
  ["subject", "place", "event"];

const EMPTY_DRAFT: RecordDraft = {
  subject: { name: "", since: "" },
  place: { name: "", lat: "", lon: "", parent: "" },
  event: { name: "", start: "", end: "", parent: "" },
};

function draftOf(entry: TagSetEntryOut | null, lang?: string): RecordDraft {
  const d = (v: number | null | undefined) =>
    v ? formatDate(v, lang) : "";
  return {
    subject: entry?.subject
      ? { name: entry.subject.name ?? "", since: d(entry.subject.since) }
      : null,
    place: entry?.place
      ? { name: entry.place.name ?? "",
          lat: entry.place.lat == null ? "" : String(entry.place.lat),
          lon: entry.place.lon == null ? "" : String(entry.place.lon),
          parent: entry.place.parent ?? "" }
      : null,
    event: entry?.event
      ? { name: entry.event.name ?? "", start: d(entry.event.start),
          end: d(entry.event.end), parent: entry.event.parent ?? "" }
      : null,
  };
}

/** The entry's records as the WIRE has them — what a save is diffed
 *  against, so an untouched dialog is not dirty. */
function wireOf(entry: TagSetEntryOut | null) {
  return {
    subject: entry?.subject
      ? { name: entry.subject.name ?? "", since: entry.subject.since ?? null }
      : null,
    place: entry?.place
      ? { name: entry.place.name ?? "", lat: entry.place.lat ?? null,
          lon: entry.place.lon ?? null, parent: entry.place.parent ?? "" }
      : null,
    event: entry?.event
      ? { name: entry.event.name ?? "", start: entry.event.start ?? null,
          end: entry.event.end ?? null, parent: entry.event.parent ?? "" }
      : null,
  };
}

/** The draft as the wire wants it, plus whether anything typed is not a
 *  date or a number — which is what disables Save rather than sending a
 *  refusal to the server for a typo. */
function wireRecords(d: RecordDraft, lang?: string) {
  let bad = false;
  const date = (text: string): number | null => {
    if (!text.trim()) return null;
    const n = parseDate(text, lang);
    if (n == null || !isValid(n)) { bad = true; return null; }
    return n;
  };
  const num = (text: string): number | null => {
    if (!text.trim()) return null;
    const n = Number(text);
    if (!Number.isFinite(n)) { bad = true; return null; }
    return n;
  };
  const wire = {
    subject: d.subject
      ? { name: d.subject.name.trim(), since: date(d.subject.since) } : null,
    place: d.place
      ? { name: d.place.name.trim(), lat: num(d.place.lat),
          lon: num(d.place.lon), parent: tagFieldName(d.place.parent) } : null,
    event: d.event
      ? { name: d.event.name.trim(), start: date(d.event.start),
          end: date(d.event.end), parent: tagFieldName(d.event.parent) } : null,
  };
  return { wire, bad, dirty: JSON.stringify(wire) !== JSON.stringify(wireOf(null)) };
}

/** One record: a row with a + until the name IS one of these, its fields
 *  under it once it is.
 *
 *  THERE IS NOTHING TO FOLD. The section has exactly two states and they
 *  are the answer itself — "the set does not say" is the compact row, "it
 *  says so" is the fields — so a third control that hides the fields of a
 *  record that exists could only ever hide the answer from the person
 *  editing it. The ✕ in the header is what takes the record away, and that
 *  is the only way back to the compact row.
 */
function RecordSection({ kind, icon, title, summary, rec, onChange, setId }: {
  kind: "subject" | "place" | "event";
  icon: string; title: string; summary: string;
  /** Which set the parent field's suggestions (and its Create) belong to. */
  setId: number;
  /** The draft, or null where the set does not say. Loose here on
   *  purpose: each kind has its own fields and the section draws them by
   *  `kind`, so one prop type serves all three. */
  rec: Record<string, string> | null;
  onChange: (v: Record<string, string> | null) => void;
}) {
  const t = useT();
  const on = rec != null;
  const set = (patch: Record<string, string>) =>
    onChange({ ...(rec ?? {}), ...patch });
  const put = (v: boolean) =>
    onChange(v ? { ...(EMPTY_DRAFT[kind] as Record<string, string>) } : null);
  const r = rec ?? {};
  return (
    <div style={{ border: "1px solid var(--border-soft)", borderRadius: "var(--r-6)",
                  overflow: "hidden" }}>
      <div className={on ? undefined : "hoverable"}
        onClick={on ? undefined : () => put(true)}
        style={{ display: "flex", alignItems: "center", gap: 8,
                 padding: "8px 10px", cursor: on ? "default" : "pointer" }}>
        <Icon name={on ? icon : "add"} size={16}
              color={on ? "var(--accent)" : "var(--muted-2)"} />
        <span style={{ fontSize: "var(--fs-3)", fontWeight: 600,
                       color: on ? "var(--text)" : "var(--muted)" }}>
          {title}
        </span>
        <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", flex: 1,
                       minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {summary}
        </span>
        {on && (
          <button onClick={(e) => { e.stopPropagation(); put(false); }}
            title={t("Not one of these")}
            style={{ border: "none", background: "transparent", padding: 0,
                     cursor: "pointer", display: "flex",
                     color: "var(--muted-2)" }}>
            <Icon name="close" size={15} />
          </button>
        )}
      </div>
      {on && (
        <div style={{ borderTop: "1px solid var(--border-soft)", padding: 10,
                      display: "flex", flexDirection: "column", gap: 10 }}>
          {kind !== "place" && (
            <RecordField label={t("Display name")} value={r.name ?? ""}
              placeholder={t("as it should be written out")}
              onChange={(v) => set({ name: v })} />
          )}
          {kind === "subject" && (
            <RecordField label={t("Exists since")} value={r.since ?? ""}
              mono placeholder={t("1975, 7/1999, 14.3.1879")}
              onChange={(v) => set({ since: v })} />
          )}
          {kind === "place" && (<>
            {/* NAME, not "Address" — the place editor's own word, and for
                its reason: an address is welcome in it, but "Bob's house"
                is just as much a place and a field saying Address told
                people otherwise. The library stores the line in
                `Location.address` and keeps that word to itself. */}
            <RecordField label={t("Name")} value={r.name ?? ""}
              placeholder={t("where it is — an address, or any name you use for it")}
              onChange={(v) => set({ name: v })} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                          gap: 10 }}>
              <RecordField label={t("Latitude")} value={r.lat ?? ""} mono
                placeholder={t("optional")}
                onChange={(v) => set({ lat: v })} />
              <RecordField label={t("Longitude")} value={r.lon ?? ""} mono
                placeholder={t("optional")}
                onChange={(v) => set({ lon: v })} />
            </div>
          </>)}
          {kind === "event" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                          gap: 10 }}>
              <RecordField label={t("Starts")} value={r.start ?? ""} mono
                placeholder={t("1975, 7/1999, 14.3.1879")}
                onChange={(v) => set({ start: v })} />
              <RecordField label={t("Ends")} value={r.end ?? ""} mono
                placeholder={t("optional")}
                onChange={(v) => set({ end: v })} />
            </div>
          )}
          {kind !== "subject" && (
            <ParentField setId={setId} kind={kind}
              label={kind === "place" ? t("Inside") : t("Part of")}
              value={r.parent ?? ""}
              onChange={(v) => set({ parent: v })} />
          )}
        </div>
      )}
    </div>
  );
}

/** THE PARENT of a set's place or event — `RemoteParentField` over the
 *  set's entries of that kind, named by TAG NAME (that is what a parent is
 *  named by everywhere here) but searched and shown as the place: its name,
 *  with the tag it is behind it. A name the set does not have yet can be
 *  MADE here, as an entry of this set marked as that kind — the hierarchy
 *  is built out of the set's own rows, and going away to add `japan`
 *  before `tokyo` could be filed in it is the errand that stops anybody
 *  building one. */
function ParentField({ setId, kind, label, value, onChange }: {
  setId: number; kind: "place" | "event"; label: string;
  value: string; onChange: (v: string) => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  return (
    <div>
      <Label>{label}</Label>
      <RemoteParentField
        value={value}
        onChange={onChange}
        searchKey={["tag-sets", "parents", setId, kind]}
        search={(q) => api.tagSetEntries(setId, { q, records: [kind], limit: 20 })
          .then((d) => d.rows.map((r) => ({
            name: r.name,
            label: (kind === "place" ? r.place?.name : r.event?.name) || r.name,
            hint: (kind === "place" ? r.place?.name : r.event?.name) ? r.name : undefined,
            icon: kind === "place" ? "place" : "event",
          })))}
        onCreate={async (name) => {
          await api.createTagSetEntry(setId, {
            name,
            // EMPTY BUT PRESENT: "this name is a place" is the whole of what
            // is known about it yet, and it is enough for the hierarchy —
            // its own name and coordinates are an edit away, on its own row.
            ...(kind === "place" ? { place: { name: "", lat: null, lon: null,
                                              parent: "" } }
                                 : { event: { name: "", start: null, end: null,
                                              parent: "" } }),
          });
          qc.invalidateQueries({ queryKey: ["tag-sets"] });
          return name;
        }}
        placeholder={t("the one it is in — from this set")}
        normalize={{ input: tagFieldInput, name: tagFieldName }}
      />
      <div style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)", marginTop: 4,
                    lineHeight: 1.35 }}>
        {t("Made in the library with this one, and whatever it is inside in turn.")}
      </div>
    </div>
  );
}

/** A SPACE-SEPARATED LIST OF THIS SET'S OWN NAMES, completed as it is
 *  typed. The field stays a plain list — that is what it writes, and a chip
 *  editor would be a different question — and the suggestions are about the
 *  WORD under the caret: picking one replaces that word and nothing else,
 *  so a list half-typed is still a list.
 */
/** MAKING AN ALIAS, or pointing one somewhere else.
 *
 *  Two fields: the spelling, and the entry it stands for. Both verbs are
 *  ordinary entry EDITS — an entry's aliases are its own field on the wire —
 *  so retargeting is the spelling leaving one entry's list and joining
 *  another's, which is the only shape the set's unique index on
 *  `(set, lname)` allows anyway.
 */
export function AliasOverlay({ set, alias, fromName, onClose, onSaved }: {
  set: TagSetOut;
  /** The spelling being made or moved; "" for a new one. */
  alias: string;
  /** The NAME it stands for today, where it stands for one. By name rather
   *  than by row: an alias is a row of the list now, and what its row
   *  carries about its entry is that entry's name. */
  fromName: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const from = !!fromName;
  const t = useT();
  const errText = useErrText();
  const [name, setName] = useState(alias);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const clean = tagFieldName(name.trim());
  const ok = !!clean && !!target.trim() && !busy
    && target.trim().toLowerCase() !== clean.toLowerCase();
  const save = async () => {
    if (!ok) return;
    setBusy(true);
    try {
      const hit = await api.tagSetEntries(set.id, { q: target.trim(), limit: 20 });
      const to = hit.rows.find(
        (r) => r.name.toLowerCase() === target.trim().toLowerCase());
      if (!to) {
        setError(t("No entry of this set is called that."));
        return;
      }
      // It LEAVES its old entry first: one spelling, one entry, enforced by
      // the set's own unique index. Looked up the same way the target is —
      // one request, and only when the spelling is actually moving.
      if (fromName && fromName.toLowerCase() !== to.name.toLowerCase()) {
        const back = await api.tagSetEntries(set.id, { q: fromName, limit: 20 });
        const old = back.rows.find(
          (r) => r.name.toLowerCase() === fromName.toLowerCase());
        if (old) {
          await api.updateTagSetEntry(set.id, old.id, {
            aliases: old.aliases.filter((a) => a !== alias) });
        }
      }
      await api.updateTagSetEntry(set.id, to.id, {
        aliases: [...to.aliases.filter((a) => a.toLowerCase() !== clean.toLowerCase()),
                  clean] });
      setError(null);
      onSaved();
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  return (
    <Overlay icon="swap_horiz" width={460}
             title={from ? t("Point the alias at another tag")
                         : t("Add alias")}
             onClose={onClose}
             unsaved={{ dirty: !!clean && !!target.trim(),
                        onSave: () => void save(), t }}
             footer={<>
               <Button variant="ghost" icon="close" onClick={onClose}>{t("Cancel")}</Button>
               <Button variant="primary" icon="check" onClick={() => void save()} disabled={!ok}>
                 {t("Save")}
               </Button>
             </>}>
      <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <Label>{t("Spelling")}</Label>
          <input autoFocus={!from} value={name} disabled={!!from}
                 onChange={(e) => setName(tagFieldInput(e.target.value))}
                 placeholder={t("the other name for it")}
                 style={{ ...field, fontFamily: "var(--mono)",
                          opacity: from ? 0.6 : 1 }} />
        </div>
        <div>
          <Label>{t("Stands for")}</Label>
          <SetTagField setId={set.id} value={target} onChange={setTarget}
                       placeholder={t("an entry of this set")} />
        </div>
        {error && (
          <div style={{ color: "var(--red-text)", fontSize: "var(--fs-3)" }}>{error}</div>
        )}
      </div>
    </Overlay>
  );
}

function SetTagField({ setId, value, onChange, placeholder }: {
  setId: number; value: string; onChange: (v: string) => void;
  placeholder?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // THE WORD UNDER THE CARET is the last one: this field is typed left to
  // right and committed with a space, so the tail is what is being written.
  const word = value.split(/\s+/).pop() ?? "";
  const needle = useDebouncedValue(word.trim(), tagDebounceMs(word));
  const { data, isFetching } = useQuery({
    queryKey: ["tag-sets", "implies", setId, needle],
    queryFn: () => api.tagSetEntries(setId, { q: needle, limit: 12 }),
    enabled: needle.length > 0,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
  const taken = new Set(value.split(/\s+/).filter(Boolean).map(tagFieldName));
  const rows = (data?.rows ?? []).filter((r) => !taken.has(r.name));
  const put = (name: string) => {
    const parts = value.split(/\s+/);
    parts[parts.length - 1] = name;
    onChange(parts.join(" ") + " ");
    list.dismiss();
  };
  const list = useSuggestList<TagSetEntryOut>({
    matches: rows, create: null,
    settled: !isFetching,
    onPick: (r) => { if (r.kind === "match") put(r.item.name); },
    // The field's keys and blur are the hook's; nothing here is committed
    // on Enter with the list closed — the list IS the value, word by word.
    input: {},
  });
  const rect = useAnchorRect(ref, list.open);
  return (
    <div ref={ref}>
      <input value={value}
        // RAW: this is a LIST, and `tagFieldInput` turns a space into an
        // underscore — it is the rule for one name, and it ate the
        // separator here. Each word is normalized when the list is read.
        onChange={(e) => { onChange(e.target.value); list.undismiss(); }}
        {...list.inputProps}
        placeholder={placeholder}
        style={{ ...field, fontFamily: "var(--mono)" }} />
      {list.open && (
        <AnchoredDropdown rect={rect} fill>
          <TagSuggestList
            list={list} dense fill
            renderRow={(m) => (<>
              <span style={{ fontFamily: "var(--mono)", overflow: "hidden",
                             textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {m.name}
              </span>
              {m.description && (
                <span style={{ marginLeft: 6, fontSize: "var(--fs-1)",
                               color: "var(--muted-3)", overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {m.description}
                </span>
              )}
            </>)}
          />
        </AnchoredDropdown>
      )}
    </div>
  );
}

// A labelled input is the shared `Field`, dense.
const RecordField = (p: { label: string; value: string; onChange: (v: string) => void;
                          placeholder?: string; mono?: boolean }) => <Field small {...p} />;

/** One category: its name, its glyph, its parent (never itself or anything
 *  under it) — and whether it is HIDDEN from the autocomplete. */
/** One switch with its own explanation — the shape the "hide this category"
 *  row already had, pulled out because the set's properties and a category's
 *  now hold three of them each. */
/** A bordered SECTION holding one or more setting rows, with a hairline
 *  between them rather than a gap — two switches that answer the same kind
 *  of question read as one thing, and two boxes read as two. */
/** A bordered box of rows — the shared section, untitled. */
function Group({ children }: { children: React.ReactNode }) {
  return <Section>{children}</Section>;
}

/** One switch with its own explanation — the shared toggle row. */
function SwitchRow({ title, help, checked, onChange, disabled }: {
  title: string; help: string; checked: boolean;
  onChange: (v: boolean) => void;
  /** Its precondition is off. Dimmed and inert rather than hidden: what it
   *  is set to still applies the moment the precondition comes back. */
  disabled?: boolean;
}) {
  return <ToggleRow label={title} hint={help} checked={checked} onChange={onChange}
                    disabled={disabled} last />;
}

/** THE SAME ROW, THREE-STATE — a category answers for its branch, or lets
 *  the one above it answer. `inherited` is what that would be, spelled out
 *  on the Default button so the choice is never a guess. */
function TriRow({ title, help, value, inherited, onChange }: {
  title: string; help: string;
  value: boolean | null; inherited: boolean;
  onChange: (v: boolean | null) => void;
}) {
  const t = useT();
  const choices: Array<[boolean | null, string]> = [
    [null, inherited ? t("Default (on)") : t("Default (off)")],
    [true, t("On")],
    [false, t("Off")],
  ];
  // The three answers as one segmented control — the shared one.
  return (
    <RowShell label={title} hint={help} last>
      <SegmentedControl<string>
        value={String(value)}
        onChange={(v) => onChange(v === "null" ? null : v === "true")}
        options={choices.map(([v, label]) => ({ value: String(v), label }))} />
    </RowShell>
  );
}

/** THE SET'S OWN PROPERTIES — what used to be a lone Hide/Show in the ⋯
 *  menu, now that there are three switches and two of them are three-state
 *  at the category level. Hidden is `enabled` read the other way round: the
 *  menu said Hide/Show and so does this. */
export function TagSetPropertiesOverlay({ set, onClose, onSaved }: {
  set: TagSetOut; onClose: () => void; onSaved: () => void;
}) {
  const t = useT();
  const errText = useErrText();
  const [name, setName] = useState(set.name);
  const [description, setDescription] = useState(set.description ?? "");
  const [hidden, setHidden] = useState(!set.enabled);
  const [aliases, setAliases] = useState(set.aliases_enabled);
  const [implications, setImplications] = useState(set.implications_enabled);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const clean = name.trim();
  const desc = description.trim();
  const dirty = clean !== set.name || hidden !== !set.enabled
    || desc !== (set.description ?? "").trim()
    || aliases !== set.aliases_enabled
    || implications !== set.implications_enabled;
  const save = async () => {
    if (busy || !clean) return;
    setBusy(true);
    try {
      if (clean !== set.name || desc !== (set.description ?? "").trim()
          || aliases !== set.aliases_enabled
          || implications !== set.implications_enabled)
        await api.updateTagSet(set.id, {
          ...(clean !== set.name ? { name: clean } : {}),
          description: desc,
          aliases_enabled: aliases, implications_enabled: implications });
      // Enabling is its own endpoint and its own event — the one switch the
      // rest of the app reads on every keystroke.
      if (hidden !== !set.enabled) await api.setTagSetEnabled(set.id, !hidden);
      onSaved();
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  return (
    <Overlay onSubmit={() => void save()} icon="tune" title={t("Tag set properties")} subtitle={set.name}
      width={520} onClose={onClose} unsaved={{ dirty, onSave: save, t }}
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, alignItems: "center" }}>
          {error && <span style={{ color: "var(--red-text)", fontSize: "var(--fs-3)", marginRight: "auto" }}>{error}</span>}
          <Button variant="ghost" onClick={onClose} icon="close">{t("Cancel")}</Button>
          <Button variant="primary" onClick={() => void save()} icon="check"
                         disabled={busy || !clean}>
            {t("Save")}
          </Button>
        </div>
      }>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 18 }}>
        {/* THE NAME, first: it is the one thing about a set that is not a
            switch, and renaming it had been a menu row of its own for a
            dialog that is otherwise everything about the set. */}
        <div>
          <Label>{t("Name")}</Label>
          <input value={name} autoFocus onChange={(e) => setName(e.target.value)}
                 
                 placeholder={t("My tags")} style={field} />
        </div>
        {/* THE SET'S OWN WORDS — what the tag set IS, where it came
            from, what it is for. It rides the exported file, so a set
            passed to somebody else arrives explaining itself; without a
            field for it the only way to write one was to edit the JSON. */}
        <div>
          <Label>{t("Description")}</Label>
          <textarea value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("What this tag set is, and where it came from")}
            rows={3}
            style={{ ...field, height: "auto", minHeight: 64,
                     padding: "8px 11px", lineHeight: 1.5,
                     resize: "vertical", fontFamily: "var(--sans)" }} />
        </div>
        <Group>
          <SwitchRow title={t("Hidden")} checked={hidden} onChange={setHidden}
                     help={t("A hidden set suggests nothing and marks nothing. "
                             + "It stays here to edit and to show again.")} />
        </Group>
        {/* THE TWO KINDS OF ADVICE, in one section — and both DIMMED under
            Hidden, which already turns the whole set off: a switch that
            cannot change anything should say so rather than look live. What
            they are set to is kept, and applies again the moment the set is
            shown. */}
        <Group>
          <SwitchRow title={t("Offer alias spellings")} checked={aliases}
                     onChange={setAliases} disabled={hidden}
                     help={t("The set's other spellings for a name are suggested "
                             + "and lead to it. Turning this off leaves every "
                             + "alias where it is; it stops being offered.")} />
          <SwitchRow title={t("Create implied tags")} checked={implications}
                     onChange={setImplications} disabled={hidden}
                     help={t("Assigning one of the set's names also creates the "
                             + "tags it entails, and links them. Turning this "
                             + "off leaves the entries' implications listed.")} />
        </Group>
      </div>
    </Overlay>
  );
}

export function CategoryEditOverlay({ set, cats: catsLive, cat, onClose, onSaved }: {
  set: TagSetOut; cats: TagSetCategoryOut[];
  /** `null` = a new top-level one; an `id` of -1 is a new one under `parent_id`. */
  cat: TagSetCategoryOut | null;
  onClose: () => void; onSaved: () => void;
}) {
  // The tree as it was when the dialog opened (`useFrozen`): a rename
  // landing elsewhere must not rebuild the parent list under the pointer.
  const cats = useFrozen(catsLive, cat?.id) ?? catsLive;
  const t = useT();
  const errText = useErrText();
  const creating = !cat || cat.id < 0;
  const [name, setName] = useState(creating ? "" : cat!.name);
  const [parentId, setParentId] = useState<number | null>(cat?.parent_id ?? null);
  const [icon, setIcon] = useState(creating ? "" : (cat!.icon || ""));
  const [hidden, setHidden] = useState(creating ? false : !!cat!.hidden);
  const [aliases, setAliases] = useState<boolean | null>(creating ? null : cat!.aliases);
  const [implications, setImplications] =
    useState<boolean | null>(creating ? null : cat!.implications);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // WHAT "DEFAULT" WOULD MEAN HERE: the nearest ancestor that answers, and
  // the set's own flag when none does. The same walk the backend does
  // (`ops/tagsets._scopes_off`), so the label cannot say one thing while the
  // autocomplete does another.
  const inherited = (field: "aliases" | "implications", root: boolean) => {
    let at = parentId;
    for (let i = 0; i < 64 && at != null; i++) {
      const row = cats.find((c) => c.id === at);
      if (!row) break;
      if (row[field] != null) return !!row[field];
      at = row.parent_id;
    }
    return root;
  };
  // The parent may not be the category itself or anything inside it.
  const banned = useMemo(() => {
    if (creating) return new Set<number>();
    const out = new Set<number>([cat!.id]);
    for (const c of cats) if (ancestorsOf(cats, c.id).includes(cat!.id)) out.add(c.id);
    return out;
  }, [cats, cat, creating]);
  const clean = name.trim();
  const dirty = creating
    ? clean !== "" || icon !== "" || hidden || parentId !== (cat?.parent_id ?? null)
      || aliases !== null || implications !== null
    : clean !== cat!.name || parentId !== cat!.parent_id
      || icon !== (cat!.icon || "") || hidden !== !!cat!.hidden
      || aliases !== cat!.aliases || implications !== cat!.implications;
  // A '/' is an ordinary character in a category name now (owner decision,
  // 2026-09): nothing joins a trail into a path any more, so there is no
  // separator for it to collide with.
  const canSave = clean !== "" && !busy;
  const save = async () => {
    if (!canSave) return;
    setBusy(true);
    try {
      if (creating) {
        await api.createTagSetCategory(set.id, { name: clean, parent_id: parentId,
                                                 icon, hidden, aliases,
                                                 implications });
      } else {
        await api.updateTagSetCategory(set.id, cat!.id, {
          name: clean, icon, hidden,
          ...(parentId == null ? { clear_parent: true } : { parent_id: parentId }),
          // A three-state field cannot say "inherit" with a null, because a
          // null is also "leave alone" on the wire — `clear_*` says it.
          ...(aliases == null ? { clear_aliases: true } : { aliases }),
          ...(implications == null ? { clear_implications: true } : { implications }),
        });
      }
      onSaved();
    } catch (e) { setError(errText(e)); }
    finally { setBusy(false); }
  };
  return (
    <Overlay onSubmit={() => void save()} icon="folder" title={creating ? t("Add category") : t("Edit category")}
      subtitle={set.name} width={460} onClose={onClose}
      unsaved={{ dirty, onSave: save, t }}
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, alignItems: "center" }}>
          {error && <span style={{ color: "var(--red-text)", fontSize: "var(--fs-3)", marginRight: "auto" }}>{error}</span>}
          <Button variant="ghost" onClick={onClose} icon="close">{t("Cancel")}</Button>
          <Button variant="primary" onClick={() => void save()} icon="check" disabled={!canSave}>
            {creating ? t("Add") : t("Save")}
          </Button>
        </div>
      }>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 18 }}>
        <div>
          <Label>{t("Name")}</Label>
          <input value={name} autoFocus onChange={(e) => setName(e.target.value)}
                 
                 placeholder={t("people")} style={field} />
        </div>
        <div>
          <Label>{t("Icon")}</Label>
          {/* The palette, the group dialog's shape: one row of glyphs, the
              chosen one filled. A glyph an older file named that is not in
              the set is still shown as its own choice, or the palette
              would show nothing picked. */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {(CATEGORY_ICONS.includes(icon || "folder") ? CATEGORY_ICONS : [...CATEGORY_ICONS, icon])
              .map((name) => {
                const on = (icon || "folder") === name;
                return (
                  <button key={name} type="button" title={name}
                          onClick={() => setIcon(name === "folder" ? "" : name)}
                          style={{ width: 30, height: 30, display: "flex", alignItems: "center",
                                   justifyContent: "center", borderRadius: "var(--r-3)", cursor: "pointer",
                                   border: `1px solid ${on ? "var(--accent)" : "var(--border-strong)"}`,
                                   background: on ? "var(--accent)" : "var(--panel-2)",
                                   color: on ? "var(--on-accent)" : "var(--text)" }}>
                    <Icon name={name} size={16} />
                  </button>
                );
              })}
          </div>
        </div>
        <div>
          <Label>{t("Parent category")}</Label>
          <select value={parentId ?? ""} onChange={(e) => setParentId(e.target.value ? Number(e.target.value) : null)}
                  style={field}>
            <option value="">{t("Top level")}</option>
            {categoryOptions(cats, banned)}
          </select>
        </div>
        {/* HIDING IS ABOUT WHAT IS OFFERED. The category stays here, its
            entries stay listed and an export still carries them — what goes
            is the suggestion, for this category and everything under it. A
            name the library already HAS is offered by its own row, which no
            tag set has ever had a say in. */}
        <Group>
          <SwitchRow title={t("Hide from the autocomplete")}
                     checked={hidden} onChange={setHidden}
                     help={t("Its tags, and its sub-categories', stop being suggested. "
                             + "Tags the library already has are unaffected.")} />
        </Group>
        {/* THREE-STATE, and the branch is the point: a set may offer its
            aliases everywhere but here, or nowhere but here. Default takes
            whatever the category above says, and the set's own switch is the
            end of that walk. One section, like the set's own pair. */}
        <Group>
          <TriRow title={t("Offer alias spellings")}
                  value={aliases} onChange={setAliases}
                  inherited={inherited("aliases", set.aliases_enabled)}
                  help={t("For this category and everything under it.")} />
          <TriRow title={t("Create implied tags")}
                  value={implications} onChange={setImplications}
                  inherited={inherited("implications", set.implications_enabled)}
                  help={t("For this category and everything under it.")} />
        </Group>
      </div>
    </Overlay>
  );
}

