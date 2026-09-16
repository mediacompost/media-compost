/** WHAT A TAG *IS* — somebody, somewhere, or something that happened.
 *
 *  A subject, a place and an event are extra data ON a tag, never a catalog
 *  beside it, and for a long time each had a dialog of its own: four editors,
 *  four save paths, four copies of the tag adoption, the merge-on-a-taken-name
 *  offer and the meta-tag list — and no way to say "this tag is a person AND
 *  the place they lived", which the model has always allowed.
 *
 *  So the tag editor grew three sections, in the shape the tag SETS' entry
 *  editor already had: a row with a **+** until the name is one of these, its
 *  fields under it once it is, and a ✕ in the header as the way back. This
 *  file is those sections — the fields, the drafts they hold, and the one
 *  function that turns a draft into creates, updates and deletions.
 *
 *  THERE IS NOTHING TO FOLD. The two states ARE the answer, so a third control
 *  hiding the fields of a record that exists could only hide the answer from
 *  the person editing it.
 */
import React, { useMemo } from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { rowBackground } from "../../shared/Row";
import { IconButton } from "../../shared/IconButton";
import { Button } from "../../shared/Button";
import { Field } from "../../shared/Field";
import { api, EventRow, PlaceRow, SubjectRow } from "../api";
import { Icon } from "../../shared/Icon";
import { useT } from "../i18n";
import { SelectionBar } from "../../shared/SelectionBar";
import { WorldMap } from "../../shared/WorldMap";
import { ParentField } from "./ParentField";
import { TagAutocomplete } from "./TagAutocomplete";
import { useRowSelect } from "./shared/useRowSelect";
import { fieldStyle as field, FieldLabel as Label } from "../../shared/Overlay";
import { formatLatLon, parseLatLon, placeLabel }
  from "../../query/places/formats";
import { bounds, formatDate, isValid, parseDate }
  from "../../query/subjects/when";

export type RecordKind = "subject" | "place" | "event";

/** THE THREE RECORDS AS THE DIALOG HOLDS THEM: null where the tag is not one
 *  of these, else the fields as TYPED — dates and coordinates as text, since a
 *  half-typed date is not a number yet and the field must show what was
 *  typed. */
export type SubjectDraft = { name: string; since: string };
export type PlaceDraft =
  { name: string; coords: string; parentId: number | null };
export type EventDraft = {
  name: string; from: string; to: string;
  parentId: number | null; venues: number[];
};
export interface RecordDrafts {
  subject: SubjectDraft | null;
  place: PlaceDraft | null;
  event: EventDraft | null;
}

/** A record the tag has just been said to be, with nothing filled in yet. One
 *  maker per kind rather than one indexed by kind: three shapes, and a single
 *  signature covering all of them is a cast at every call site. */
export const emptySubject = (): SubjectDraft => ({ name: "", since: "" });
export const emptyPlace = (): PlaceDraft =>
  ({ name: "", coords: "", parentId: null });
export const emptyEvent = (): EventDraft =>
  ({ name: "", from: "", to: "", parentId: null, venues: [] });

/** The records this tag already has, as drafts. */
export function draftsOf(subject: SubjectRow | null, place: PlaceRow | null,
                         event: EventRow | null, lang?: string): RecordDrafts {
  const d = (v: number | null | undefined) => (v ? formatDate(v, lang) : "");
  return {
    subject: subject
      ? { name: subject.display_name, since: d(subject.since_date) } : null,
    place: place
      ? { name: place.name ?? "", coords: formatLatLon(place.lat, place.lon),
          parentId: place.parent_id ?? null } : null,
    event: event
      ? { name: event.display_name, from: d(event.start_date),
          to: d(event.end_date), parentId: event.parent_id ?? null,
          venues: (event.places ?? []).map((p) => p.id) } : null,
  };
}

/** Two drafts compared as a SAVE would compare them — what the dirty check and
 *  the diffing save both ask. */
export function sameDrafts(a: RecordDrafts, b: RecordDrafts): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Whether anything typed into the three sections is not a date, not a pair of
 *  coordinates, or a span that ends before it starts — which is what holds
 *  Save back rather than sending a typo to the server for a refusal. */
export function recordsProblem(d: RecordDrafts, lang: string | undefined,
                               t: (s: string) => string): string {
  const bad = (text: string) => {
    const v = text.trim();
    if (!v) return false;
    const n = parseDate(v, lang);
    return n == null || !isValid(n);
  };
  if (d.subject && bad(d.subject.since))
    return t("That date doesn't look like a date.");
  if (d.place && d.place.coords.trim() && parseLatLon(d.place.coords) === null)
    return t("Those don't look like coordinates.");
  if (d.event) {
    if (bad(d.event.from) || bad(d.event.to))
      return t("That is not a date I can read.");
    const from = d.event.from.trim() ? parseDate(d.event.from, lang) : null;
    const to = d.event.to.trim() ? parseDate(d.event.to, lang) : null;
    if (from && to && bounds(from)[0] > bounds(to)[1])
      return t("It ends before it starts.");
  }
  return "";
}

/** Which record the name should be derived from, and what it is called there.
 *  The tag field FOLLOWS the first section that is on — a person typed into a
 *  fresh dialog is `subject:their_name` — and stops the moment the tag is
 *  edited by hand. */
export function leadingRecord(d: RecordDrafts):
    { kind: RecordKind; name: string } | null {
  if (d.subject) return { kind: "subject", name: d.subject.name };
  if (d.place) return { kind: "place", name: d.place.name };
  if (d.event) return { kind: "event", name: d.event.name };
  return null;
}

/** WHAT THE SAVE DOES WITH THEM: a record the dialog gained is created on this
 *  tag (an existing tag is ADOPTED — that is what naming it says), one it lost
 *  is deleted while the TAG stays (the pictures are still of something), and
 *  one that changed is patched field by field.
 *
 *  `tagName` is the name the tag ends up with, so a rename in the same save
 *  has already moved it. */
export async function saveRecords(opts: {
  tagName: string;
  drafts: RecordDrafts;
  subject: SubjectRow | null;
  place: PlaceRow | null;
  event: EventRow | null;
  lang?: string;
}): Promise<{ subject: SubjectRow | null; place: PlaceRow | null;
              event: EventRow | null }> {
  const { tagName, drafts, subject, place, event, lang } = opts;
  const date = (text: string): number => {
    const v = text.trim();
    if (!v) return 0;
    return parseDate(v, lang) ?? 0;
  };
  const pick = <T extends { tag: string }>(rows: T[]): T | null =>
    rows.find((r) => r.tag === tagName) ?? rows[rows.length - 1] ?? null;

  let outSubject = subject, outPlace = place, outEvent = event;

  const s = drafts.subject;
  if (!s && subject) {
    // WITHOUT THE TAG: taking the person away does not take the word away.
    await api.deleteSubject(subject.id);
    outSubject = null;
  } else if (s && !subject) {
    outSubject = pick(await api.createSubject({
      display_name: s.name.trim(), since_date: date(s.since), tag: tagName }));
  } else if (s && subject) {
    const body: Record<string, unknown> = {};
    if (s.name.trim() !== subject.display_name)
      body.display_name = s.name.trim();
    if (date(s.since) !== (subject.since_date ?? 0))
      body.since_date = date(s.since);
    if (Object.keys(body).length) {
      const rows = await api.updateSubject(subject.id, body);
      outSubject = rows.find((r) => r.id === subject.id) ?? subject;
    }
  }

  const p = drafts.place;
  const ll = p && p.coords.trim() ? parseLatLon(p.coords) : null;
  if (!p && place) {
    await api.deletePlace(place.id);
    outPlace = null;
  } else if (p && !place) {
    outPlace = pick(await api.createPlace({
      tag: tagName, name: p.name.trim(),
      lat: ll?.lat ?? null, lon: ll?.lon ?? null,
      ...(p.parentId == null ? {} : { parent_id: p.parentId }) }));
  } else if (p && place) {
    const rows = await api.updatePlace(place.id, {
      name: p.name.trim(),
      // An emptied pair is a removal, which `lat: null` cannot say — it is
      // also what "the caller did not mention it" looks like.
      ...(ll == null ? { clear_coords: true } : { lat: ll.lat, lon: ll.lon }),
      ...(p.parentId == null ? { clear_parent: true }
                             : { parent_id: p.parentId }),
    });
    outPlace = rows.find((r) => r.id === place.id) ?? place;
  }

  const e = drafts.event;
  if (!e && event) {
    await api.deleteEvent(event.id);
    outEvent = null;
  } else if (e && !event) {
    outEvent = pick(await api.createEvent({
      tag: tagName, display_name: e.name.trim(),
      start_date: date(e.from), end_date: date(e.to), place_ids: e.venues,
      ...(e.parentId == null ? {} : { parent_id: e.parentId }) }));
  } else if (e && event) {
    const rows = await api.updateEvent(event.id, {
      display_name: e.name.trim(),
      start_date: date(e.from), end_date: date(e.to), place_ids: e.venues,
      ...(e.parentId == null ? { clear_parent: true }
                             : { parent_id: e.parentId }),
    });
    outEvent = rows.find((r) => r.id === event.id) ?? event;
  }
  return { subject: outSubject, place: outPlace, event: outEvent };
}

// ---- the sections -----------------------------------------------------------

/** One record's frame: the header that turns it on and off, and its fields. */
export function RecordSection({ icon, title, summary, on, onPut, children }: {
  icon: string; title: string; summary: string;
  on: boolean;
  onPut: (v: boolean) => void;
  children: React.ReactNode;
}) {
  const t = useT();
  return (
    <div style={{ border: "1px solid var(--border-soft)", borderRadius: "var(--r-6)",
                  overflow: "hidden" }}>
      <div className={on ? undefined : "hoverable"}
        onClick={on ? undefined : () => onPut(true)}
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
          <button onClick={(ev) => { ev.stopPropagation(); onPut(false); }}
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
          {children}
        </div>
      )}
    </div>
  );
}

/** A labelled input, the size these sections use — the shared `Field`, dense. */
const RecordField = (p: { label: string; value: string; onChange: (v: string) => void;
                          placeholder?: string; mono?: boolean; bad?: boolean;
                          autoFocus?: boolean }) => <Field small {...p} />;

/** SOMEBODY: what they are called written out, and when they came to be. */
export function SubjectFields({ draft, onChange, lang }: {
  draft: SubjectDraft; onChange: (v: SubjectDraft) => void; lang?: string;
}) {
  const t = useT();
  const bad = draft.since.trim() !== ""
    && (() => { const n = parseDate(draft.since, lang);
                return n == null || !isValid(n); })();
  return (<>
    {/* The DISPLAY name — "Albert Einstein", with its spaces and capitals,
        which the slug above can never hold. */}
    <RecordField label={t("Display name")} value={draft.name}
      placeholder={t("as it should be written out")}
      onChange={(v) => onChange({ ...draft, name: v })} />
    <RecordField label={t("Exists since")} value={draft.since} mono bad={bad}
      placeholder={t("1975, 7/1999, 14.3.1879")}
      onChange={(v) => onChange({ ...draft, since: v })} />
  </>);
}

/** SOMEWHERE: one line, a pair of coordinates, and what it is inside. */
export function PlaceFields({ draft, onChange, places, self }: {
  draft: PlaceDraft; onChange: (v: PlaceDraft) => void;
  places: PlaceRow[];
  /** The place being edited, so it cannot be put inside itself. */
  self: number | null;
}) {
  const t = useT();
  const latlon = draft.coords.trim() ? parseLatLon(draft.coords) : null;
  const bad = draft.coords.trim() !== "" && latlon === null;
  const rows = useMemo(
    () => places
      .filter((p) => p.tag)     // an unnamed place cannot imply anything
      .map((p) => ({ id: p.id, parent_id: p.parent_id ?? null,
                     label: placeLabel(p), hint: p.tag || "" })),
    [places]);
  return (<>
    {/* NAME, not "Address": an address is welcome in it, but "Bob's house" is
        as much a place, and a field saying Address told people otherwise. */}
    <RecordField label={t("Name")} value={draft.name}
      placeholder={t("where it is — an address, or any name you use for it")}
      onChange={(v) => onChange({ ...draft, name: v })} />
    <div>
      <Label>{t("Coordinates")}</Label>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <input value={draft.coords} placeholder="35.6812, 139.7671"
          onChange={(e) => onChange({ ...draft, coords: e.target.value })}
          style={{ ...field, flex: 1, minWidth: 0, height: 30,
                   fontFamily: "var(--mono)", fontSize: "var(--fs-3)",
                   borderColor: bad ? "var(--red)" : "var(--border-strong)" }} />
        {/* ALWAYS THERE, greyed until the numbers are readable: a preview that
            came and went with the field moved everything under it every time a
            digit was typed. Nothing is fetched to draw it — the outline ships
            with the app. */}
        <div style={{ opacity: latlon ? 1 : 0.35,
                      pointerEvents: latlon ? undefined : "none" }}>
          <WorldMap points={latlon ? [{ lat: latlon.lat, lon: latlon.lon }] : []}
                    height={88} zoom={latlon ? 3 : 1}
                    title={latlon ? `${latlon.lat}, ${latlon.lon}` : undefined} />
        </div>
      </div>
    </div>
    {/* THE PARENT LAST: it names another row of this same list, so it belongs
        after the place has been described rather than in the middle of it.
        Containment is not a second mechanism — assigning a place implies its
        parents, through the ordinary tag implications. */}
    <div>
      <Label>{t("Inside")}</Label>
      <ParentField rows={rows} self={self} value={draft.parentId}
        onChange={(id) => onChange({ ...draft, parentId: id })} />
    </div>
  </>);
}

/** SOMETHING THAT HAPPENED: a span of days, the places it was at, and what it
 *  is part of. */
export function EventFields({ draft, onChange, events, places, self, lang,
                             onNewVenue, onEditVenue }: {
  draft: EventDraft; onChange: (v: EventDraft) => void;
  events: EventRow[]; places: PlaceRow[];
  self: number | null;
  lang?: string;
  /** Describe a place that is not in the library yet — the dialog above
   *  mounts the form, since it is this very editor one level down. */
  onNewVenue: (typed: string) => void;
  onEditVenue: (place: PlaceRow) => void;
}) {
  const t = useT();
  const [adding, setAdding] = React.useState("");
  const bad = (text: string) => {
    const v = text.trim();
    if (!v) return false;
    const n = parseDate(v, lang);
    return n == null || !isValid(n);
  };
  const from = draft.from.trim() ? parseDate(draft.from, lang) : null;
  const to = draft.to.trim() ? parseDate(draft.to, lang) : null;
  const backwards = !!from && !!to && bounds(from)[0] > bounds(to)[1];

  const byId = useMemo(
    () => new Map(places.map((p) => [p.id, p])), [places]);
  const venues = draft.venues
    .map((id) => byId.get(id)).filter(Boolean) as PlaceRow[];
  // The same row rules the rest of the app has — click, shift-range, drag to
  // paint — so taking three venues off is one gesture rather than three ✕s.
  const sel = useRowSelect(venues.map((p) => `p:${p.id}`));
  // By NAME with the slug underneath, like the sidebar's Places field: you
  // look for "Hall H", not for `san_diego_convention_center`.
  const options = useMemo(
    () => places.filter((p) => p.tag && !draft.venues.includes(p.id))
      .map((p) => ({ name: placeLabel(p), comment: p.tag, uses: p.items })),
    [places, draft.venues]
  );
  const addVenue = (text: string) => {
    const typed = text.trim();
    const low = typed.toLowerCase();
    const hit = places.find(
      (p) => p.tag === typed || placeLabel(p).toLowerCase() === low);
    if (hit) {
      setAdding("");
      if (!draft.venues.includes(hit.id))
        onChange({ ...draft, venues: [...draft.venues, hit.id] });
    } else if (typed) {
      onNewVenue(typed);
    }
  };
  const eventRows = useMemo(
    () => events.filter((e) => e.tag).map((e) => ({
      id: e.id, parent_id: e.parent_id ?? null,
      label: e.display_name || e.tag, hint: e.tag })),
    [events]);

  return (<>
    <RecordField label={t("Display name")} value={draft.name}
      placeholder={t("San Diego Comic-Con 2014")}
      onChange={(v) => onChange({ ...draft, name: v })} />
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
      <RecordField label={t("From")} value={draft.from} mono bad={bad(draft.from)}
        placeholder={t("year or date")}
        onChange={(v) => onChange({ ...draft, from: v })} />
      <RecordField label={t("To")} value={draft.to} mono
        bad={bad(draft.to) || backwards} placeholder={t("optional")}
        onChange={(v) => onChange({ ...draft, to: v })} />
    </div>
    <div>
      <Label>{t("Places")}</Label>
      {/* ONE component, not a stack of separate rows: a bordered box with the
          list inside it and the field at the bottom reads as "the places of
          this event", where five bordered rows read as five things that
          happen to be near each other. */}
      <div style={{ padding: 6, borderRadius: "var(--r-6)", background: "var(--panel-2)",
                    border: "1px solid var(--border)" }}>
        {venues.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 2,
                        marginBottom: 6 }}>
            {venues.map((p) => {
              const key = `p:${p.id}`;
              return (
                <div key={p.id} className="hoverable" {...sel.props(key)}
                  title={placeLabel(p)}
                  style={{ display: "flex", alignItems: "center", gap: 6,
                    padding: "5px 6px 5px 8px", borderRadius: "var(--r-3)", minHeight: 26,
                    color: "var(--text)", fontSize: "var(--fs-3)", cursor: "default",
                    background: rowBackground(sel.has(key), "transparent"),
                    border: `1px solid ${sel.has(key) ? "var(--accent)" : "transparent"}`,
                  }}>
                  <Icon name={RECORD_ICON.place} size={15} color="var(--muted-2)" />
                  <span style={{ minWidth: 0, flex: 1, overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {placeLabel(p)}
                  </span>
                  {/* On hover, and spelled out as two: editing the place and
                      taking it off this event are different enough that a
                      single ✕ next to a pencil is the whole affordance. */}
                  <IconButton icon="edit" size={20} glyph={14} reveal="hover" title={t("Edit place…")}
                    onClick={(e) => { e.stopPropagation(); onEditVenue(p); }} />
                  <IconButton icon="close" size={20} glyph={14} reveal="hover" tone="danger" title={t("Not there")}
                    onClick={(e) => {
                      e.stopPropagation();
                      onChange({ ...draft,
                        venues: draft.venues.filter((x) => x !== p.id) });
                    }} />
                </div>
              );
            })}
          </div>
        )}
        {/* Always here, so adding the first venue or picking the last row does
            not shove the field below it up and down. The total is the rows the
            list SHOWS, not the ids it holds — a freshly created place is still
            arriving while the two differ. */}
        <SelectionBar
          t={t}
          count={sel.selected.length}
          total={venues.length}
          onSelectAll={sel.selectAll}
          onRemove={() => {
            const ids = sel.selected.map((k) => Number(k.slice(2)));
            sel.clear();
            onChange({ ...draft,
              venues: draft.venues.filter((x) => !ids.includes(x)) });
          }}
          onClear={() => sel.clear()}
          style={{ margin: "0 2px 6px" }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <TagAutocomplete
              value={adding}
              onChange={setAdding}
              onCommit={addVenue}
              suggestions={options}
              placeholder={t("Add a place…")}
              freeText
              minWidth={240}
            />
          </div>
          <Button variant="soft" size="sm" onClick={() => onNewVenue(adding.trim())}
      title={t("Describe a new place")}>
            <Icon name="add_location_alt" size={15} /> {t("New")}
          </Button>
        </div>
      </div>
    </div>
    {/* WHAT THIS ONE IS PART OF — Day 1 of the convention, in the season.
        Assigning it assigns everything above it, through the implications. */}
    <div>
      <Label>{t("Part of")}</Label>
      <ParentField rows={eventRows} self={self} value={draft.parentId}
        onChange={(id) => onChange({ ...draft, parentId: id })}
        placeholder={t("Not part of anything")} />
    </div>
  </>);
}
