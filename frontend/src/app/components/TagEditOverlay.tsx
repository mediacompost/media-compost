// Everything about one tag, in one place: its name, its comment and long
// description, what it implies, what else it is called — and WHAT IT IS.
//
// The list used to edit the first three inline — a name you clicked, a comment
// cell, and a row of chips with their own little buttons — which made the table
// busy and gave the comment a single cramped line. Here the row shows what a
// tag IS and the pencil opens this for changing it.
//
// AND IT IS THE ONE RECORD EDITOR. A subject, a place and an event are extra
// data ON a tag, but each had a dialog of its own: four of them, 2,100 lines,
// four save paths, and four copies of the tag adoption, the taken-name offer
// and the meta-tag list. Worse, the model has always allowed a tag to be a
// person AND the place they lived, and four separate dialogs could not say it.
// So the three records are SECTIONS here (`TagRecordSections.tsx`), in the
// shape the tag sets' entry editor already had: a row with a + until the name
// is one of these, its fields under it once it is.
//
// Renaming onto a name that already exists is the interesting case: that is a
// MERGE, and it is offered as one rather than refused with "already exists" —
// except where this tag is a place or an event, which the two editors folded
// in here refused for a reason kept below.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { rowBackground } from "../../shared/Row";
import { IconButton } from "../../shared/IconButton";
import { useFrozen } from "../../shared/useFrozen";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { tagCount, tagFieldInput, tagFieldName } from "../tags";
import { api, EventRow, PlaceRow, SubjectRow, TagRow } from "../api";
import { Icon } from "../../shared/Icon";
import { useLang, useT, useTn, useErrText } from "../i18n";
import { bracketSlug, freeSlug, splitBracketed } from "../tagslug";
import { Overlay, fieldStyle as field, FieldLabel as Label } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { TagAutocomplete } from "./TagAutocomplete";
import { TagMetaTagsField, sameMetaCounts } from "./TagMetaTags";
import { CommentField, DescriptionField } from "./DescribedFields";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { useDebouncedValue } from "../../shared/useDebounced";
import { SelectionBar } from "../../shared/SelectionBar";
import { useRowSelect } from "./shared/useRowSelect";
import {
  EventFields, PlaceFields, RecordDrafts, RecordKind, RecordSection,
  SubjectFields, draftsOf, emptyEvent, emptyPlace, emptySubject,
  leadingRecord, recordsProblem, sameDrafts, saveRecords,
} from "./TagRecordSections";

/** The one small-print line these dialogs still carry: under a field, never
 *  under a label, and only when the field says something new. */
export const noteStyle: React.CSSProperties = {
  marginTop: 5, fontSize: "var(--fs-2)", lineHeight: 1.45, color: "var(--muted-2)",
};

/** What a save left behind, for a caller that has something to do with it —
 *  the sidebar sections put the new record's tag on the item they were opened
 *  from, and the venue list chips the place it just made. */
export interface SavedTag {
  name: string;
  subject: SubjectRow | null;
  place: PlaceRow | null;
  event: EventRow | null;
}

const RECORD_GLYPH: Record<RecordKind, string> = RECORD_ICON;

export function TagEditOverlay({ tag, allTags, openAt, prefillName,
                                onClose, onSaved, onMerged }: {
  /** NULL means "a tag that does not exist yet". The new-tag form is this same
   *  dialog with nothing filled in rather than a second one beside it. */
  tag: TagRow | null;
  allTags: TagRow[];
  /** Open with one record section already on: the row's ⋯ menu ("Add place…",
   *  "Edit subject…") and every door that is about the record rather than
   *  about the tag. */
  openAt?: RecordKind;
  /** What was typed into the field that opened this. It seeds the record's
   *  DISPLAY NAME where a section is being opened (and the tag name derives
   *  from it), and the tag's own name otherwise. A trailing bracket splits —
   *  "Traveler (Genshin Impact)" seeds the name AND the comment, and the
   *  derived slug keeps the bracket (the booru spelling). */
  prefillName?: string;
  onClose: () => void;
  /** The save landed. The record caches are already invalidated. */
  onSaved: (made: SavedTag) => void;
  /** A merge deletes this tag, so the caller can offer an Undo for it. */
  onMerged: (into: string, events: number[]) => void;
}) {
  const t = useT();
  const errText = useErrText();
  const tn = useTn();
  const lang = useLang();
  const qc = useQueryClient();
  const pre = useMemo(() => splitBracketed(prefillName ?? ""), [prefillName]);
  const [name, setName] = useState(
    tag?.name ?? (openAt ? "" : tagFieldName(pre.name)));
  const [comment, setComment] = useState(tag?.comment ?? pre.comment);
  // THE LONG FORM, the library's own. It had none for a while — a description
  // was a tag set's, and the library's tags were described only by whatever
  // set knew the name — and it has one again: the library IS a set now, the
  // first pill in this tab, and it exports as a template that would otherwise
  // carry no teaching at all.
  const [description, setDescription] = useState(tag?.description ?? "");
  // NOTHING here is applied until Save. Implications used to apply as you made
  // them, which left Cancel meaning "close" rather than "never mind" — half the
  // dialog had already happened.
  const was = useMemo(() => [...(tag?.implies ?? [])], [tag?.implies]);
  const [implies, setImplies] = useState<string[]>(was);
  // What the TAG SET says about it — same rule, applied at Save. The COUNT
  // beside each name is the assignment's own figure (how many pictures the tag
  // has where that meta tag says); the map is sparse, so a name missing from
  // it carries none.
  const wasMeta = useMemo(() => [...(tag?.meta_tags ?? [])], [tag?.meta_tags]);
  const [metaTags, setMetaTags] = useState<string[]>(wasMeta);
  const wasMetaCounts = useMemo(
    () => ({ ...(tag?.meta_counts ?? {}) }), [tag?.meta_counts]);
  const [metaCounts, setMetaCounts] =
    useState<Record<string, number>>(wasMetaCounts);
  const [adding, setAdding] = useState("");
  //: THE OTHER NAMES IT ANSWERS TO, back in the dialog (owner 2026-09,
  //  reversing the removal of the same month). They are ordinary rows of the
  //  catalog and the list beside this dialog draws each of them under its
  //  target — but the dialog is where a tag is READ, and what else it is
  //  called is part of that; making one meant leaving for the Add menu, and
  //  finding the spellings of a tag meant folding its row open. TAKING ONE
  //  OFF DELETES IT (owner 2026-09), which is what an alias row's own ✕
  //  does — the list says so above the field, and the Save button is what
  //  commits it, so nothing is lost by looking.
  const wasAliases = useMemo(() => {
    if (!tag) return [];
    // The row's own answer where it has one (the Tags tab's detail fetch
    // carries it), and the catalog otherwise — the nested mounts here are
    // handed `/api/tags`, whose rows say what they are an alias OF but not
    // what is an alias of them.
    if (tag.aliases?.length) return [...tag.aliases];
    return allTags.filter((x) => x.alias_of === tag.name).map((x) => x.name);
  }, [tag, allTags]);
  const [aliases, setAliases] = useState<string[]>(wasAliases);
  const [addingAlias, setAddingAlias] = useState("");
  const [aliasNote, setAliasNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The merge confirmation, once the typed name turns out to be taken. A NAME
  // rather than a row: the tag it clashes with may not be in the list this
  // dialog was handed (see `remote` below), and the merge is by name anyway.
  const [mergeInto, setMergeInto] = useState<string | null>(null);
  // Keep the old name as an alias of the target, or let it go entirely.
  const [keepAlias, setKeepAlias] = useState(true);
  // A VENUE being described or corrected — the nested dialog below, which is
  // this very one a level down.
  const [venue, setVenue] =
    useState<{ place: PlaceRow | null; typed: string } | null>(null);
  const firstRef = useRef<HTMLInputElement>(null);
  useEffect(() => { firstRef.current?.focus(); }, []);

  // ---- what this tag IS -----------------------------------------------------

  // The three catalogs. Small enough to hold whole (they are the library's own
  // named things, not its tags), and every one of them is what a parent field
  // and a venue list pick from.
  const subs = useQuery({ queryKey: ["subjects"], queryFn: api.subjects });
  const pls = useQuery({ queryKey: ["places"], queryFn: api.places });
  const evs = useQuery({ queryKey: ["events"], queryFn: api.events });
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  // HELD for the dialog's life (`useFrozen`): a refetch behind an edit must
  // not move the form — the ready gate below still waits for a FRESH first
  // answer, since these are invalidated by every write this dialog makes.
  const subjects = useFrozen(subs.data, tag?.id);
  const places = useFrozen(pls.data, tag?.id);
  const events = useFrozen(evs.data, tag?.id);
  // NOT FETCHING, not merely answered: React Query hands over what it has
  // cached and refetches behind it, and these three are invalidated by every
  // write this dialog makes. Seeded from a stale answer, the form would open
  // saying a tag is not a place a moment after something made it one — and
  // saving would then take that place away. The wait is one request, and only
  // where the cache was already old.
  const ready = !!subjects && !!places && !!events
    && !subs.isFetching && !pls.isFetching && !evs.isFetching;
  const mySubject = useMemo(
    () => (tag ? (subjects ?? []).find((x) => x.tag === tag.name) ?? null : null),
    [subjects, tag]);
  const myPlace = useMemo(
    () => (tag ? (places ?? []).find((x) => x.tag === tag.name) ?? null : null),
    [places, tag]);
  const myEvent = useMemo(
    () => (tag ? (events ?? []).find((x) => x.tag === tag.name) ?? null : null),
    [events, tag]);
  // What the dialog OPENED holding — the three catalogs arrive after the first
  // render, so the drafts are seeded once they do and diffed against this
  // afterwards. A save never sees a half-loaded form: Save waits for `ready`.
  const initial = useMemo<RecordDrafts | null>(() => {
    if (!ready) return null;
    const d = draftsOf(mySubject, myPlace, myEvent, lang);
    // The door said which record this is about, so it is open on arrival —
    // with what was typed into the field that opened it.
    if (openAt === "subject" && d.subject == null)
      d.subject = { ...emptySubject(), name: pre.name };
    if (openAt === "place" && d.place == null)
      d.place = { ...emptyPlace(), name: pre.name };
    if (openAt === "event" && d.event == null)
      d.event = { ...emptyEvent(), name: pre.name };
    return d;
  }, [ready, mySubject, myPlace, myEvent, lang, openAt, pre.name]);
  const [drafts, setDrafts] = useState<RecordDrafts | null>(null);
  // Seeded ONCE: the catalogs refetch on every write this dialog makes, and a
  // second seeding would throw away what is being typed.
  useEffect(() => {
    setDrafts((cur) => (cur == null && initial != null ? initial : cur));
  }, [initial]);
  const put = (kind: RecordKind, on: boolean) =>
    setDrafts((cur) => {
      if (cur == null) return cur;
      if (kind === "subject") return { ...cur, subject: on ? emptySubject() : null };
      if (kind === "place") return { ...cur, place: on ? emptyPlace() : null };
      return { ...cur, event: on ? emptyEvent() : null };
    });

  // ---- the name, which may FOLLOW the record --------------------------------

  const prefixFor = (kind: RecordKind) =>
    (kind === "subject" ? settings?.subject_tag_prefix
      : kind === "place" ? settings?.place_tag_prefix
      : settings?.event_tag_prefix) ?? "";
  const tagNames = useMemo(() => allTags.map((x) => x.name), [allTags]);
  // A bracket-seeded create keeps the bracket in the slug while either half is
  // still being corrected.
  const bracketed = !tag && pre.comment !== "";
  const lead = drafts ? leadingRecord(drafts) : null;
  const derived = useMemo(() => {
    if (!lead) return "";
    const base = bracketSlug(lead.name, bracketed ? comment : "");
    if (!base) return "";
    // UNIQUIFIED against everything but this tag's own name: two people called
    // Maria derive the same slug and the record may repeat (a display name is
    // not an identity) while the tag may not, so the second is offered
    // `maria_2` rather than a refusal at save time.
    return freeSlug(`${prefixFor(lead.kind)}${base}`,
                    tagNames.filter((n) => n !== tag?.name));
  }, [lead?.kind, lead?.name, bracketed, comment, tagNames, tag?.name,
      settings]);
  // The slug the tag WOULD have been given by the record it already carries.
  // While the two agree, editing the display name moves the tag with it —
  // visibly, in this field, which is what the subject editor's "Rename the tag
  // along with the subject" tickbox used to say in words.
  const opened = useMemo(() => {
    const l = initial ? leadingRecord(initial) : null;
    const base = l ? bracketSlug(l.name, "") : "";
    return l && base ? `${prefixFor(l.kind)}${base}` : "";
  }, [initial, settings]);
  const [tagTouched, setTagTouched] = useState(false);
  const follows = !tagTouched
    && (tag ? (!!opened && tag.name === opened) : true);
  const shown = follows && derived ? derived : name;

  // The same rules every other tag field applies — this one did whitespace and
  // nothing else, so a colon typed here reached an API that refuses it.
  const clean = tagFieldName(shown);
  // Compared against what is IN the field, not against `clean`: the field
  // opens holding the tag's own name, and a tag that predates the lowercase
  // convention (an import, an older library) would otherwise be renamed to its
  // own lowercase form by a save that touched only the comment.
  const renaming = !!tag && shown !== tag.name && clean !== tag.name;
  // Items that carry the tag itself — what a rename actually touches. (The
  // implicit ones follow their own tag and are not rewritten.)
  const assigned = tag
    ? tagCount(tag) - tagCount(tag, "implicit") + tagCount(tag, "negative") : 0;
  // A name that clashes with another tag is a question ("keep both, or
  // merge?") about a change being made, so it is asked while RENAMING and not
  // while a save only touches the comment. For a tag that does not exist yet
  // there is nothing to merge FROM — a clash there is simply a name to pick
  // again, and the Save button says so by staying disabled.
  const local = useMemo(
    () => (renaming && tag
      ? allTags.find((x) => x.name === clean && x.id !== tag.id) ?? null
      : null),
    [allTags, clean, renaming, tag]
  );
  // THE CATALOG THIS DIALOG IS HANDED IS THE LIST BEHIND IT, and that list is
  // narrowed: the Items tab passes the index it drew, which under a search or
  // a filter is a few rows of the tag set rather than all of it. The clash
  // is the one question whose wrong answer is silent — "no such tag" for a
  // name that exists, so the merge is never offered and the save is simply
  // refused by the server — so it is asked of the SERVER as well, through the
  // exact-name lookup every tag field in this app already uses.
  const needle = useDebouncedValue(clean, 250);
  const askServer = !!needle && needle !== tag?.name
    && !allTags.some((x) => x.name === needle);
  const { data: named } = useQuery({
    queryKey: ["tags", "names", "exact", needle],
    queryFn: () => api.tagNames(needle, 5),
    enabled: askServer,
    staleTime: 10_000,
  });
  const remote = askServer && needle === clean
    ? (named ?? []).find((r) => r.name === needle) ?? null : null;
  /** The name a save would fold this tag INTO, or null. */
  const clash = local?.name ?? (renaming ? remote?.name ?? null : null);
  // A PLACE OR AN EVENT REFUSES THE OFFER. `tagcatalog.merge` deletes the
  // source tag, and the record pointing at it is SET NULL into the tagless
  // state the model does not allow — the place and event editors folded in
  // here refused a taken name for exactly that reason, and a subject survives
  // it only because the merge below folds the two identities as well.
  const noMerge = !!(myPlace || myEvent);
  const nameTaken = !tag && !!clean
    && (allTags.some((x) => x.name === clean) || !!remote);
  const problem = drafts ? recordsProblem(drafts, lang, t) : "";
  // IS THERE ANYTHING TO LOSE? Every field, compared with what the dialog
  // opened holding — the ✕ asks only when the answer is yes, or it would be a
  // question about a dialog somebody merely looked at.
  const sameList = (a: string[], b: string[]) =>
    a.length === b.length && a.every((x, i) => x === b[i]);
  const dirty = shown !== (tag?.name ?? "")
    || comment !== (tag?.comment ?? pre.comment)
    || description !== (tag?.description ?? "")
    || !sameList(implies, was)
    || !sameList(aliases, wasAliases)
    || !sameList(metaTags, wasMeta)
    || !sameMetaCounts(metaCounts, wasMetaCounts)
    || !!(drafts && initial && !sameDrafts(drafts, initial));

  const options = useMemo(
    () => allTags
      .filter((x) => x.alias_of == null && x.name !== tag?.name && !implies.includes(x.name))
      .map((x) => ({ name: x.name, comment: x.comment ?? "",
                     uses: tagCount(x),
                     metaCounts: x.meta_counts ?? undefined,
                     metaTags: x.meta_tags ?? undefined })),
    [allTags, implies, tag?.name]
  );

  const addImplies = (raw: string) => {
    const v = tagFieldName(raw);
    if (!v || v === clean || implies.includes(v)) return;
    setAdding("");
    setImplies((cur) => [...cur, v]);
  };

  /** AN ALIAS MUST NAME A TAG NOBODY HAS — that is the whole difference
   *  between it and an implication, which must name one somebody does. A
   *  name already in the catalog is refused with the reason under the
   *  field rather than at Save, where the answer would arrive after the
   *  rest of the dialog had already been written. */
  const addAlias = (raw: string) => {
    const v = tagFieldName(raw);
    if (!v) return;
    if (v === clean) {
      setAliasNote(t("That is this tag's own name."));
      return;
    }
    if (aliases.includes(v)) { setAddingAlias(""); return; }
    if (allTags.some((x) => x.name === v)) {
      setAliasNote(t("A tag with this name already exists."));
      return;
    }
    setAliasNote("");
    setAddingAlias("");
    setAliases((cur) => [...cur, v]);
  };

  const save = async () => {
    setError("");
    if (!clean) { setError(t("A tag needs a name.")); return; }
    if (nameTaken) { setError(t("A tag with this name already exists.")); return; }
    if (problem) { setError(problem); return; }
    if (clash) {
      if (noMerge) {
        setError(t("{slug} already belongs to another tag. Pick another name.",
                   { slug: clean }));
        return;
      }
      setMergeInto(clash);
      return;
    }
    setBusy(true);
    try {
      // A NEW tag is one POST and then exactly the same diffs, because there
      // is nothing to diff against: `was` and `wasAliases` are empty, so the
      // loops below add what the form holds and remove nothing.
      const id = tag
        ? tag.id
        : (await api.createTag({ name: clean, comment })).id;
      if (tag) {
        const body: { name?: string; comment?: string;
                      description?: string } = {};
        if (renaming) body.name = clean;
        if (comment !== (tag.comment ?? "")) body.comment = comment;
        if (description !== (tag.description ?? "")) body.description = description;
        if (Object.keys(body).length) await api.updateTag(tag.id, body);
      } else if (description) {
        await api.updateTag(id, { description });
      }
      // The implication diff, applied one edge at a time — each stays its own
      // entry in the History view.
      for (const n of was.filter((x) => !implies.includes(x))) {
        await api.removeTagImplication(id, n);
      }
      for (const n of implies.filter((x) => !was.includes(x))) {
        await api.addTagImplication(id, n);
      }
      // THE SPELLINGS, the same way: one made is a tag of its own pointing
      // here (`get_or_create`'s door is not this one — an alias is created
      // outright), one taken off is that tag DELETED. Against `clean`, so a
      // rename in this same save has already moved the target.
      for (const n of wasAliases.filter((x) => !aliases.includes(x))) {
        // ASKED FOR BY NAME, since the catalog this dialog was handed is
        // the list BEHIND it — narrowed by whatever is typed in its search
        // box, which a spelling of the tag being edited need not match. A
        // row looked up there was found or not depending on what the list
        // happened to be showing, so the delete silently did nothing.
        const row = allTags.find((x) => x.name === n && x.alias_of != null)
          ?? (await api.tagsPage({ q: n, limit: 50 })).rows
               .find((x) => x.name === n && x.alias_of != null);
        if (row) await api.deleteTag(row.id);
      }
      for (const n of aliases.filter((x) => !wasAliases.includes(x))) {
        await api.createTag({ name: n, alias_of: clean });
      }
      // The same diff for what the tag set says about it. By ID here — this
      // dialog always knows it, either from the row or from the create above.
      for (const n of wasMeta.filter((x) => !metaTags.includes(x))) {
        await api.removeTagMetaTag(id, n);
      }
      // ONE loop for a name that is new and for a count that moved: the
      // endpoint is idempotent and sets the figure either way, and a fresh
      // assignment counting nothing writes the event a countless add always
      // wrote (`tagcatalog._move_meta_tag`).
      for (const n of metaTags) {
        const count = metaCounts[n] ?? 0;
        if (wasMeta.includes(n) && count === (wasMetaCounts[n] ?? 0)) continue;
        await api.addTagMetaTag(id, n, count);
      }
      // AND WHAT IT IS — last, and against the name the tag ENDS UP with, so a
      // rename in this same save has already moved it. A record the dialog
      // gained is created on this tag, one it lost is deleted while the tag
      // stays, and one that changed is patched.
      const made = drafts
        ? await saveRecords({ tagName: clean, drafts, subject: mySubject,
                              place: myPlace, event: myEvent, lang })
        : { subject: mySubject, place: myPlace, event: myEvent };
      // THE RECORD LISTS ARE THIS DIALOG'S OWN TO REFRESH, and awaited: every
      // caller was doing it in its own callback, and the one that forgot left
      // a place it had just made unresolvable in the list beside it.
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["subjects"] }),
        qc.invalidateQueries({ queryKey: ["places"] }),
        qc.invalidateQueries({ queryKey: ["events"] }),
      ]);
      onSaved({ name: clean, ...made });
      onClose();
    } catch (e) {
      setError(errText(e));
      setBusy(false);
    }
  };

  const doMerge = async () => {
    // A merge folds one EXISTING tag into another; `clash` is only ever set
    // for a tag that exists, so this is a type guard rather than a case.
    if (!mergeInto || !tag) return;
    setBusy(true);
    try {
      const res = await api.mergeTag(tag.id, mergeInto, keepAlias);
      // THE IDENTITIES FOLLOW THEIR TAGS. The source tag is gone and the
      // subject's FK is SET NULL, so where the target is somebody too the two
      // records merge with the tags — two subjects on one tag is not a state
      // the model allows, and the alternative is a person left nameless.
      if (mySubject) {
        const theirs = (subjects ?? []).find((x) => x.tag === mergeInto);
        if (theirs && theirs.id !== mySubject.id) {
          await api.mergeSubject(mySubject.id, theirs.id, true);
        }
        await qc.invalidateQueries({ queryKey: ["subjects"] });
      }
      onMerged(mergeInto, res.event_ids ?? []);
      onClose();
    } catch (e) {
      setError(errText(e));
      setBusy(false);
      setMergeInto(null);
    }
  };

  if (mergeInto && tag) {
    return (
      <Overlay error={error}
        icon="merge"
        title={t("Merge tags?")}
        subtitle={`${tag.name} → ${mergeInto}`}
        width={480}
        onClose={() => setMergeInto(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setMergeInto(null)}>{t("Cancel")}</Button>
            <Button variant="primary" icon="merge" onClick={() => void doMerge()} disabled={busy}>
              {t("Merge")}
            </Button>
          </>
        }
      >
        <div style={{ padding: 18, fontSize: "var(--fs-3)", color: "var(--text-2)", lineHeight: 1.6 }}>
          <p style={{ margin: "0 0 10px" }}>
            <b style={{ fontFamily: "var(--mono)" }}>{mergeInto}</b> {t("already exists.")}{" "}
            {t("Merging moves everything")} <b style={{ fontFamily: "var(--mono)" }}>{tag.name}</b>{" "}
            {t("carries onto it: its item assignments (with their tag groups, boxes and time ranges), what it implies, and the groups that assign it.")}
          </p>
          {mySubject
            && (subjects ?? []).some((x) => x.tag === mergeInto) && (
            <p style={{ margin: "0 0 10px" }}>
              {t("It is also somebody's identity, so the two subjects become one.")}
            </p>
          )}
          <label style={{
            display: "flex", alignItems: "flex-start", gap: 9, cursor: "pointer",
            padding: "10px 12px", borderRadius: "var(--r-5)", margin: "0 0 10px",
            background: "var(--panel)", border: "1px solid var(--border)",
          }}>
            <input
              type="checkbox"
              checked={keepAlias}
              onChange={(e) => setKeepAlias(e.target.checked)}
              style={{ marginTop: 2, cursor: "pointer" }}
            />
            <span>
              <span style={{ color: "var(--text-2)" }}>
                {t("Keep the old name as an alias")}
              </span>
              <span style={{ display: "block", fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 2 }}>
                {keepAlias
                  ? t("Anything still using the old name finds the merged tag.")
                  : t("The old name disappears; anything using it will not resolve.")}
              </span>
            </span>
          </label>
          <p style={{ margin: 0, color: "var(--muted)" }}>
            {t("Every item's change is recorded separately, so this can be undone from the History tab.")}
          </p>
        </div>
      </Overlay>
    );
  }

  const glyph = lead ? RECORD_GLYPH[lead.kind] : "sell";
  return (
    <Overlay onSubmit={() => void save()} error={error}
      icon={glyph}
      title={tag ? t("Edit tag") : t("New tag")}
      unsaved={{ dirty, onSave: () => void save(), t }}
      // A tag that does not exist yet has no counts to report, so the subtitle
      // says what the dialog is FOR instead of "0 positive · 0 negative".
      subtitle={tag
        ? `${tagCount(tag)} ${t("positive")}`
          + (tagCount(tag, "implicit") > 0
             ? ` (${tagCount(tag, "implicit")} ${t("implicit")})` : "")
          + ` · ${tagCount(tag, "negative")} ${t("negative")}`
        : t("A word a picture can be labelled with")}
      width={540}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" icon={clash && !noMerge ? "merge" : "check"}
            onClick={() => void save()}
            disabled={busy || !ready || !!problem
                      || (clash != null && noMerge) || nameTaken}>
            {clash && !noMerge ? t("Merge…") : tag ? t("Save") : t("Create")}
          </Button>
        </>
      }
    >
      <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 16, maxHeight: "66vh", overflowY: "auto" }}>
        <div>
          <Label>{t("Name")}</Label>
          <input
            ref={firstRef}
            value={shown}
            onChange={(e) => { setTagTouched(true);
                               setName(tagFieldInput(e.target.value)); }}
            
            style={{ ...field, fontFamily: "var(--mono)",
                     borderColor: clash
                       ? (noMerge ? "var(--red)" : "var(--accent)")
                       : "var(--border-strong)" }}
          />
          {/* THE ONLY LINE OF SMALL PRINT LEFT, and it appears only once the
              field says something it did not say when it opened. The labels
              each carried a sentence explaining themselves, which over four
              fields is a paragraph of instructions nobody reads twice. What
              survives is a CONSEQUENCE rather than an explanation, and it
              belongs under the field it is about, not under its name. */}
          {clash ? (
            <div style={{ ...noteStyle,
                          color: noMerge ? "var(--red-text)" : "var(--accent)" }}>
              {noMerge
                ? t("{slug} already belongs to another tag. Pick another name.",
                    { slug: clean })
                : t("A tag with this name already exists — saving offers to merge the two.")}
            </div>
          ) : nameTaken ? (
            <div style={{ ...noteStyle, color: "var(--red-text)" }}>
              {t("A tag with this name already exists.")}
            </div>
          ) : renaming && assigned > 0 ? (
            <div style={noteStyle}>
              {tn({ one: "On save, the item carrying this tag is updated.",
                    other: "On save, all {n} items carrying this tag are updated." },
                  assigned)}
            </div>
          ) : follows && derived ? (
            // The field is being written FOR you, from the display name below.
            // Said once, quietly, because the alternative is a slug that
            // changes under the cursor for no stated reason.
            <div style={noteStyle}>
              {t("Follows the display name — type here to name the tag yourself.")}
            </div>
          ) : null}
        </div>

        <CommentField value={comment} onChange={setComment}
          onEnter={() => void save()}
          placeholder={t("What this tag is for, in a line…")} />

        {/* THE COMMENT IS THE LINE, THE DESCRIPTION IS THE PARAGRAPH, and
            they sit in that order for the reason the ? popover draws them
            in it: the one-liner is a gloss on the name and rides everywhere
            the name rides, the long form is read once, on purpose. */}
        <DescriptionField value={description} onChange={setDescription} />

        <NameList
          label={t("Implies")}
          icon="arrow_right_alt"
          names={implies}
          onRemoved={(gone) => setImplies((cur) => cur.filter((n) => !gone.has(n)))}
          removeTitle={t("Remove this implication")}
          removeManyTitle={t("Remove the selected implications")}
          empty={t("This tag implies nothing yet.")}
          adder={
            <TagAutocomplete
              value={adding}
              onChange={setAdding}
              onCommit={(v) => void addImplies(v)}
              suggestions={options}
              placeholder={t("Add a tag it implies…")}
            />
          }
        />

        {/* WHAT ELSE IT IS CALLED. Under what it implies, because an
            implication is about other tags and a spelling is about this
            one — the list reads outwards from the name at the top. */}
        <NameList
          label={t("Also called")}
          icon="alternate_email"
          names={aliases}
          onRemoved={(gone) => setAliases((cur) => cur.filter((n) => !gone.has(n)))}
          removeTitle={t("Delete this spelling")}
          removeManyTitle={t("Delete the selected spellings")}
          empty={t("This tag has no other spellings.")}
          note={aliasNote}
          adder={
            <input
              value={addingAlias}
              onChange={(e) => { setAliasNote("");
                                 setAddingAlias(tagFieldInput(e.target.value)); }}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                e.preventDefault();
                e.stopPropagation();
                addAlias(addingAlias);
              }}
              onBlur={() => addingAlias.trim() && addAlias(addingAlias)}
              placeholder={t("Another name for it…")}
              style={{ ...field, width: "100%" }}
            />
          }
        />

        <TagMetaTagsField names={metaTags} counts={metaCounts}
                          onChange={setMetaTags} onCounts={setMetaCounts} />

        {/* WHAT KIND OF THING THE NAME IS — somebody, somewhere, or something
            that happened. A tag may be any of them, and may be more than one:
            the model has always allowed it and four separate dialogs could
            never say it. */}
        <div style={{ borderTop: "1px solid var(--border-soft)",
                      paddingTop: 14, display: "flex",
                      flexDirection: "column", gap: 12 }}>
          <RecordSection icon={RECORD_ICON.subject} title={t("Subject")}
            summary={t("a person, a character, a band, a cat")}
            on={!!drafts?.subject} onPut={(v) => put("subject", v)}>
            {drafts?.subject && (
              <SubjectFields draft={drafts.subject} lang={lang}
                onChange={(v) => setDrafts((c) => c && { ...c, subject: v })} />
            )}
          </RecordSection>
          <RecordSection icon={RECORD_ICON.place} title={t("Place")}
            summary={t("somewhere, and what it is inside")}
            on={!!drafts?.place} onPut={(v) => put("place", v)}>
            {drafts?.place && (
              <PlaceFields draft={drafts.place} places={places ?? []}
                self={myPlace?.id ?? null}
                onChange={(v) => setDrafts((c) => c && { ...c, place: v })} />
            )}
          </RecordSection>
          <RecordSection icon={RECORD_ICON.event} title={t("Event")}
            summary={t("something that happened, over a span of days")}
            on={!!drafts?.event} onPut={(v) => put("event", v)}>
            {drafts?.event && (
              <EventFields draft={drafts.event} lang={lang}
                events={events ?? []} places={places ?? []}
                self={myEvent?.id ?? null}
                onChange={(v) => setDrafts((c) => c && { ...c, event: v })}
                onNewVenue={(typed) => setVenue({ place: null, typed })}
                onEditVenue={(p) => setVenue({ place: p, typed: "" })} />
            )}
          </RecordSection>
          {!ready && (
            <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-3)" }}>
              {t("Loading…")}
            </div>
          )}
        </div>
      </div>

      {/* A VENUE IS A PLACE, AND A PLACE IS A TAG — so describing one is this
          very dialog, one level down. It was a second component before the
          four editors became one, which is exactly the duplication that made
          them four. */}
      {venue && (
        <TagEditOverlay
          tag={venue.place
            ? allTags.find((x) => x.name === venue.place?.tag) ?? null
            : null}
          allTags={allTags}
          openAt="place"
          prefillName={venue.place ? "" : venue.typed}
          onClose={() => setVenue(null)}
          onMerged={() => setVenue(null)}
          onSaved={(m) => {
            setVenue(null);
            // Chip it, the way the places section does — otherwise the form
            // ends with nothing to show for it.
            if (m.place && !venue.place) {
              const id = m.place.id;
              setDrafts((c) => (c && c.event
                ? { ...c, event: { ...c.event, venues: [...c.event.venues, id] } }
                : c));
            }
          }}
        />
      )}
    </Overlay>
  );
}

/** A list of tag names with the sidebar's row gestures (click, ⌘-click,
 *  shift-range, press-and-drag) and the SELECTION BAR every other list of
 *  this shape has (`shared/SelectionBar`, the event section's places list).
 *
 *  Three of these — what the tag implies, what else it is called, and the
 *  labels on it — and they were one inline block before the others arrived.
 *  The differences are the icon, the wording and the ADDER: an implication
 *  must name a tag that exists (so, the autocomplete), and an alias must
 *  name one that does not.
 *
 *  ONE BORDERED BOX, list and adder inside it, the way the places of an
 *  event are drawn: five separately bordered rows read as five things that
 *  happen to be near each other, where this is one list of one kind of
 *  thing. The bar stands between them and is ALWAYS there, so adding the
 *  first row or picking the last does not shove the field up and down. */
export function NameList({ label, icon, names, onRemoved, removeTitle,
                          removeManyTitle, empty, adder, note, trailing }: {
  label: string;
  icon: string;
  names: string[];
  /** Names taken off the list — by the ✕, not a drag. */
  onRemoved: (gone: Set<string>) => void;
  removeTitle: string;
  /** Kept for the bar's own title — one list's "these" is another's. */
  removeManyTitle: string;
  empty: string;
  adder: React.ReactNode;
  note?: string;
  /** What the row carries between its name and its ✕ — the meta-tag list's
   *  per-assignment count, and nothing in the other two. A slot rather than
   *  a `counts` prop of its own: an implication and an alias are a name and
   *  nothing else, and this list is not the place to learn what a count is. */
  trailing?: (name: string) => React.ReactNode;
}) {
  const t = useT();
  //: KEYED BY THE NAME, which is what this list holds and what identifies a
  //  row in it — there is no id to key by and no two rows share a name.
  const sel = useRowSelect(names);

  const drop = (gone: string[]) => {
    onRemoved(new Set(gone));
    sel.clear();
  };

  return (
    <div>
      <Label>{label}</Label>
      <div style={{ padding: 6, borderRadius: "var(--r-6)", background: "var(--panel-2)",
                    border: "1px solid var(--border)" }}>
        {names.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 2,
                        marginBottom: 6, userSelect: "none" }}>
            {names.map((n) => {
              const on = sel.has(n);
              return (
                <div key={n} className="hoverable" {...sel.props(n)} title={n}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "5px 6px 5px 8px", borderRadius: "var(--r-3)", minHeight: 26,
                    fontSize: "var(--fs-3)", color: "var(--text)", cursor: "default",
                    background: rowBackground(on, "transparent"),
                    border: `1px solid ${on ? "var(--accent)" : "transparent"}`,
                  }}>
                  <Icon name={icon} size={15}
                        color={on ? "var(--accent)" : "var(--muted-2)"} />
                  <span style={{ flex: 1, minWidth: 0,
                                 fontFamily: "var(--mono)", fontSize: "var(--fs-3)",
                                 color: "var(--text-2)", overflow: "hidden",
                                 textOverflow: "ellipsis",
                                 whiteSpace: "nowrap" }}>
                    {n}
                  </span>
                  {trailing?.(n)}
                  <IconButton icon="close" size={22} glyph={14} reveal="hover" tone="danger" title={removeTitle}
                    onClick={(e) => { e.stopPropagation(); drop([n]); }} />
                </div>
              );
            })}
          </div>
        )}
        {names.length === 0 && (
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-3)",
                        padding: "2px 2px 6px" }}>
            {empty}
          </div>
        )}
        <SelectionBar
          t={t}
          count={sel.selected.length}
          total={names.length}
          onSelectAll={sel.selectAll}
          onRemove={() => drop(sel.selected)}
          onClear={() => sel.clear()}
          style={{ margin: "0 2px 6px" }}
        />
        {adder}
      </div>
      {note && (
        <div style={{ ...noteStyle, marginTop: 1, color: "var(--red-text)" }}>
          {note}
        </div>
      )}
    </div>
  );
}

/** The item-tag list's Add button: which of the two things is this?
 *
 *  A menu rather than one form with an optional field, because a tag and an
 *  alias are not variants of each other — a tag is a name with everything the
 *  editor above holds, an alias is a name pointing at a tag that exists. The
 *  strip that tried to be both showed "alias of (optional)" to everyone
 *  creating a plain tag, and could offer none of the other five fields.
 */
export interface AddMenuEntry {
  icon: string;
  label: string;
  /** A rule above this entry: what CREATES sits apart from what IMPORTS. */
  separated?: boolean;
  run: () => void;
}

/** The toolbar's Add button as a MENU. Every Tags sub-tab has one now: the
 *  entries that create one thing, then — behind a rule — the import, which
 *  used to be a button of its own beside Export. Adding by hand and adding
 *  from a file are the same intent at two scales, so they share the button;
 *  exporting changes nothing and keeps its own. */
export function AddMenu({ t, buttonStyle, title, entries }: {
  t: (s: string) => string;
  buttonStyle: React.CSSProperties;
  title: string;
  entries: AddMenuEntry[];
}) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const rect = useAnchorRect(anchor, open);
  return (
    <>
      <button
        ref={anchor}
        onClick={() => setOpen((v) => !v)}
        title={title}
        style={{ ...buttonStyle,
                 background: open ? "var(--accent-dim)" : "var(--panel-2)",
                 color: open ? "var(--text-bright)" : "var(--text-2)" }}
      >
        <Icon name="add" size={16} /> {t("Add")}
        <Icon name="arrow_drop_down" size={16} />
      </button>
      {open && (
        <AnchoredDropdown rect={rect} minWidth={260}>
          <div onClick={(e) => e.stopPropagation()}>
            {entries.map((entry) => (
              <div
                key={entry.label}
                className="hoverable"
                onClick={() => { setOpen(false); entry.run(); }}
                style={{ display: "flex", alignItems: "center", gap: 9,
                         padding: "7px 9px", borderRadius: "var(--r-2)",
                         cursor: "pointer", color: "var(--text-2)",
                         ...(entry.separated
                           ? { borderTop: "1px solid var(--border)",
                               borderRadius: "0 0 6px 6px", marginTop: 4,
                               paddingTop: 9 }
                           : {}) }}
              >
                <Icon name={entry.icon} size={16} />
                <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                               fontWeight: 500 }}>{entry.label}</span>
              </div>
            ))}
          </div>
        </AnchoredDropdown>
      )}
    </>
  );
}

export function AddTagMenu({ t, buttonStyle, onTag, onAlias, onImport }: {
  t: (s: string) => string;
  buttonStyle: React.CSSProperties;
  onTag: () => void;
  onAlias: () => void;
  onImport?: () => void;
}) {
  return (
    <AddMenu t={t} buttonStyle={buttonStyle} title={t("Add or import")}
      entries={[
        { icon: "sell", label: t("Tag"), run: onTag },
        { icon: "alternate_email", label: t("Alias"), run: onAlias },
        ...(onImport ? [{ icon: "upload_file", label: t("Import from CSV"),
                          separated: true, run: onImport }] : []),
      ]} />
  );
}

/** A second name for a tag that exists: the name, and which tag it points at.
 *
 *  Small on purpose — an alias has no comment, no offset, no implications and
 *  no aliases of its own (assigning one redirects to its target, so it carries
 *  nothing), which is the whole reason it is not the tag form with fields
 *  greyed out. The TARGET is picked, never typed into existence: an alias to a
 *  tag nobody has is a pair of empty rows where somebody meant one. */
export function AliasCreateOverlay({ allTags, editing, onClose, onCreated }: {
  allTags: TagRow[];
  /** THE ALIAS BEING EDITED, where this is not a new one — its row's
   *  pencil. The same two fields either way, because they are the whole of
   *  what an alias is: what it is called, and what it stands for. */
  editing?: TagRow | null;
  onClose: () => void;
  onCreated: () => void;
}) {
  const t = useT();
  const errText = useErrText();
  const [name, setName] = useState(editing?.name ?? "");
  const [target, setTarget] = useState(editing?.alias_of ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const clean = tagFieldName(name);
  const want = target.trim().replace(/\s+/g, "_");
  const targets = useMemo(
    () => allTags.filter((x) => x.alias_of == null)
      .map((x) => ({ name: x.name, comment: x.comment ?? "",
                     uses: tagCount(x),
                     metaCounts: x.meta_counts ?? undefined,
                     metaTags: x.meta_tags ?? undefined })),
    [allTags]);
  const taken = !!clean && allTags.some(
    (x) => x.name === clean && x.id !== editing?.id);
  // An alias OF an alias is refused by the API ("cannot alias to another
  // alias"), so the list offers real tags only and the button waits for one.
  const unknown = !!want && !targets.some((o) => o.name === want);
  const changed = !editing
    || clean !== editing.name || want !== (editing.alias_of ?? "");
  const ok = !!clean && !!want && !taken && !unknown && changed;

  const save = async () => {
    if (!ok) return;
    setBusy(true);
    try {
      if (editing) await api.updateTag(editing.id, { name: clean,
                                                    alias_of: want });
      else await api.createTag({ name: clean, alias_of: want });
      onCreated();
      onClose();
    } catch (e) {
      setError(errText(e));
      setBusy(false);
    }
  };

  return (
    <Overlay error={error}
      icon="alternate_email"
      title={editing ? t("Edit alias") : t("New alias")}
      subtitle={t("Another name for a tag you already have")}
      width={460}
      onClose={onClose}
      unsaved={{ dirty: changed && (!!name || !!target),
                 onSave: () => void save(), t }}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" icon="check" onClick={() => void save()}
                         disabled={busy || !ok}>
            {editing ? t("Save") : t("Add")}
          </Button>
        </>
      }
    >
      <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <Label>{t("Name")}</Label>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(tagFieldInput(e.target.value))}
            style={{ ...field,
                     borderColor: taken ? "var(--red-text)" : "var(--border-strong)" }}
          />
          {taken && (
            <div style={{ ...noteStyle, color: "var(--red-text)" }}>
              {t("A tag with this name already exists.")}
            </div>
          )}
        </div>
        <div>
          <Label>{t("Alias of")}</Label>
          <TagAutocomplete
            value={target}
            onChange={setTarget}
            onCommit={setTarget}
            suggestions={targets}
            placeholder={t("an existing tag")}
            allowCreate={false}
          />
          {unknown && (
            <div style={{ ...noteStyle, color: "var(--red-text)" }}>
              {t("no such tag")}
            </div>
          )}
        </div>
      </div>
    </Overlay>
  );
}

/** THE SAME EDITOR, OPENED ON A RECORD.
 *
 *  The item sidebar's three sections know a subject, a place or an event — not
 *  the tag row the editor is a form over, and not the catalog it needs for this
 *  tag's other spellings, for the implications autocomplete and for telling a
 *  rename onto a taken name from an ordinary one. So this fetches the catalog
 *  and mounts nothing over it until it is there: the form is seeded from what
 *  it opens holding, and a catalog arriving afterwards would mean an empty
 *  Aliases list that quietly deletes every one of them on Save.
 *
 *  `tagId` null is a record that does not exist yet — a place typed into the
 *  sidebar's own field — which is the new-tag form with one section open. */
export function RecordEditOverlay({ tagId, kind, prefillName, onClose, onSaved,
                                   onMerged }: {
  tagId: number | null;
  kind: RecordKind;
  prefillName?: string;
  onClose: () => void;
  onSaved: (made: SavedTag) => void;
  onMerged?: (into: string, events: number[]) => void;
}) {
  const t = useT();
  const { data: allTags, isFetching } = useQuery({
    queryKey: ["tags"], queryFn: api.tags });
  const row = tagId == null
    ? null : (allTags ?? []).find((x) => x.id === tagId) ?? null;
  // A CACHED CATALOG THAT PREDATES THE TAG IS NOT AN ANSWER. React Query hands
  // over what it has and refetches behind it, so a tag made a moment ago is
  // missing from the first answer — and the form, seeded from it, opened as a
  // NEW tag with an empty name over a subtitle reading the real one's counts.
  // Once the refetch has landed and the row is still not there, the tag really
  // is gone and the dialog says so by opening empty.
  if (!allTags || (tagId != null && row == null && isFetching)) {
    // The press has to do something. A frame of this beats a form that fills
    // in under the cursor.
    return (
      <Overlay icon={RECORD_GLYPH[kind]} title={t("Edit tag")} width={540}
               onClose={onClose}>
        <div style={{ padding: 18, fontSize: "var(--fs-3)", color: "var(--muted-2)" }}>
          {t("Loading…")}
        </div>
      </Overlay>
    );
  }
  return (
    <TagEditOverlay
      tag={row}
      allTags={allTags}
      openAt={kind}
      prefillName={prefillName}
      onClose={onClose}
      onSaved={onSaved}
      onMerged={onMerged ?? (() => onClose())}
    />
  );
}
