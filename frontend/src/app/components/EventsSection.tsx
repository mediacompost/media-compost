/** What was happening — the sidebar's Events section.
 *
 * The third of the same shape as Subjects and Places: an event is a tag with a
 * record attached, so the rows here are the item's tags that an event claims,
 * and adding one assigns that tag. What the section adds is the name with its
 * spaces and capitals, and the span of days.
 *
 * Under them sit the suggested ones — events whose span contains this
 * picture's own capture date. Offered, never assigned: a photograph taken
 * during that week is not necessarily a photograph OF it.
 */
import React, { useMemo, useState } from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { rowBackground } from "../../shared/Row";
import { useInlineEdit } from "../../shared/useInlineEdit";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, EventRow, ItemDetail, SuggestedEvent } from "../api";
import { Icon } from "../../shared/Icon";
import { useLang, useT } from "../i18n";
import { TagAutocomplete } from "./TagAutocomplete";
import { RecordEditOverlay } from "./TagEditOverlay";
import { RowMenu } from "./shared/RowMenu";
import { useSearchActions } from "./shared/searchActions";
import { SuggestedHeading, SuggestedRow } from "./shared/SuggestedRow";
import { formatDate } from "../../query/subjects/when";
import { TAKEN_NONE, formatTaken, parseTaken } from "../../query/subjects/taken";
import { RowSelect } from "./shared/useRowSelect";
import { TagRangeLine, useTagRangeLabel } from "./shared/TagRanges";
import { useUndoRun } from "./shared/useUndoBar";
import { FocusOnce } from "./shared/FocusOnce";

/** How an event reads, wherever it is read.
 *
 *  Exported so the editor's live preview shows exactly what the sidebar will:
 *  a preview built from its own idea of the wording is a preview of something
 *  else, and drifts the moment either side is touched. */
export function EventLine({ name, from, to, places }: {
  name: string;
  from?: number | null;
  to?: number | null;
  /** Short forms, for the editor's preview — the sidebar row has no room. */
  places?: string[];
}) {
  const lang = useLang();
  const when = spanLabel(from, to, lang);
  return (
    <span style={{ minWidth: 0, flex: 1, display: "flex",
      flexDirection: "column", gap: 1 }}>
      <span style={{ fontSize: "var(--fs-3)", color: "var(--text)", overflow: "hidden",
        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {name}
      </span>
      {/* `?` rather than `&&`: with no span and no venues the guard was
          `"" || 0`, which is `0` — and React renders a zero. That is the whole
          of the stray "0" the editor's preview used to show. */}
      {when || places?.length ? (
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
          color: "var(--muted-2)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {[when, ...(places ?? [])].filter(Boolean).join(" · ")}
        </span>
      ) : null}
    </span>
  );
}

/** The span in words, or empty when nobody dated it. */
export function spanLabel(from?: number | null, to?: number | null,
                          locale?: string): string {
  if (!from && !to) return "";
  if (!to || from === to) return formatDate(from ?? to, locale);
  if (!from) return formatDate(to, locale);
  return `${formatDate(from, locale)} – ${formatDate(to, locale)}`;
}

/** The item's tags that an event claims — exported for the same reason
 *  `placesOnItem` is: the panel above needs this list, in this order, to key
 *  the selection that spans the three sections. */
export function eventsOnItem(events: EventRow[] | undefined,
                             detail: ItemDetail | null): EventRow[] {
  const names = new Set((detail?.tags ?? []).filter((x) => !x.negative)
    .map((x) => x.name));
  return (events ?? []).filter((e) => e.tag && names.has(e.tag));
}

export function EventsSection({ itemId, detail, suggested = [], dated = true,
                               sel, focusTag, onFocused, onChange,
                               onAnswered }: {
  itemId: number;
  detail: ItemDetail | null;
  /** An event to land on, by identity tag — set when the Tags tab's calendar
   *  marker sent you here. Cleared once the row has been shown. */
  focusTag?: string | null;
  onFocused?: () => void;
  suggested?: SuggestedEvent[];
  /** False when no capture date is indexed for this picture — the section says
   *  so, rather than showing nothing and reading as "no events matched". */
  dated?: boolean;
  /** The tab's row selection, spanning this section and its siblings. */
  sel?: RowSelect;
  onChange: () => void;
  onAnswered?: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const undoRun = useUndoRun();
  // Where else this event is — see `useSearchActions`.
  const searchActions = useSearchActions();
  const qc = useQueryClient();
  const { data: events } = useQuery({ queryKey: ["events"], queryFn: api.events });
  const [adding, setAdding] = useState("");
  // The name a new event starts with — "" for the New button, which is
  // asking from nothing. `null` is closed.
  const [creating, setCreating] = useState<string | null>(null);
  const [editing, setEditing] = useState<EventRow | null>(null);

  const onItem = useMemo(() => eventsOnItem(events, detail), [events, detail]);
  const here = useMemo(() => new Set(onItem.map((e) => e.tag)), [onItem]);
  // Over a FILM an event is timed like any other tag: the convention is on
  // screen in these stretches, whatever dates the event itself ran between.
  const rangeLabel = useTagRangeLabel(detail);

  // Offered BY DISPLAY NAME with the tag underneath: having a name with spaces
  // and capitals is the whole reason an event row exists.
  const options = useMemo(
    () => (events ?? []).filter((e) => e.tag && !here.has(e.tag))
      .map((e) => ({
        name: e.display_name || e.tag,
        // The comment leads — it is the human half; the tag is machinery.
        comment: [e.comment, e.tag, spanLabel(e.start_date, e.end_date, lang)]
          .filter(Boolean).join(" · "),
        uses: e.items,
      })),
    [events, here]
  );

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["events"] });
    onChange();
  };

  const add = async (text: string) => {
    const name = text.trim();
    if (!name) return;
    setAdding("");
    const known = (events ?? []).find(
      (e) => e.display_name === name || e.tag === name);
    if (known?.tag) {
      await api.assignItemTag(itemId, known.tag, false);
      refresh();
      onAnswered?.();
    } else {
      // A name nobody has yet opens the form — an event is a span and a set of
      // places, so it is not conjured from a text field the way a tag is. The
      // name TRAVELS: it was just typed, and a blank first field would ask for
      // it again.
      setCreating(name);
    }
  };

  return (
    <div>
      {/* WHEN, before what was happening. The two are the same question asked
          two ways, and an event's span is the fallback for a picture with no
          date of its own — so the date it actually has belongs above the list
          that might otherwise be standing in for it. */}
      <TakenControl itemId={itemId} detail={detail} onChange={onChange} />
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {onItem.map((e) => {
          return (
            // A COLUMN, so a film's time ranges can sit under the name — the
            // same shape the tag rows and the place rows take, and for the
            // same reason: a timecode pair is wider than most names.
            <div key={e.id} {...(sel?.props(`e:${e.tag}`) ?? {})}
              className={focusTag === e.tag ? "hoverable mc-flash" : "hoverable"}
              title={e.comment ? `${e.tag} · ${e.comment}` : e.tag}
              style={{
              display: "flex", flexDirection: "column", gap: 2,
              padding: "5px 6px 5px 8px", borderRadius: "var(--r-4)", minHeight: 26,
              background: rowBackground(sel?.has(`e:${e.tag}`), "var(--panel-2)"),
              border: `1px solid ${sel?.has(`e:${e.tag}`) ? "var(--accent)" : "var(--border)"}`,
              // A row you can pick says so, like the tag rows.
              cursor: sel ? "pointer" : undefined,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6,
                minHeight: 20 }}>
                <Icon name={RECORD_ICON.event} size={15} color="var(--muted-2)" />
                {/* The one definition of how an event reads — the editor's live
                    preview renders the same component, so the two cannot drift. */}
                <EventLine name={e.display_name || e.tag}
                  from={e.start_date} to={e.end_date} />
                <RowMenu
                  title={t("More actions")}
                  always
                  actions={[
                    { icon: "edit", label: t("Edit event…"),
                      hint: t("It is shared, so this changes it everywhere"),
                      onClick: () => setEditing(e) },
                    ...searchActions("event", e.tag,
                      e.display_name || e.tag),
                    { icon: "close", label: t("Remove from this item"), danger: true,
                      onClick: () => void undoRun(`${t("Removed")} ${e.tag}`,
                        () => api.unassignItemTag(itemId, e.tag)
                          .then(() => { refresh(); onAnswered?.(); })) },
                  ]}
                />
              </div>
              {/* WHEN in the film, which is a different question from the
                  event's own dates on the line above: one says the convention
                  ran 5–10 January, the other that it is on screen here. */}
              <TagRangeLine label={rangeLabel?.(e.tag) ?? null} indent={21} />
            </div>
          );
        })}
        {onItem.length === 0 && suggested.length === 0 && (
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", padding: "2px 0 4px" }}>
            {dated ? t("Nothing in particular was happening.")
                   : t("No capture date is indexed for this item, so nothing can be offered.")}
          </div>
        )}
        {suggested.length > 0 && (
          <>
            <SuggestedHeading>{t("Suggested")}</SuggestedHeading>
            {suggested.map((s) => (
              <SuggestedRow
                key={s.event.id}
                icon={RECORD_ICON.event}
                label={s.event.display_name || s.event.tag}
                title={s.event.tag}
                reason={t("taken {when}",
                          { when: formatDate(s.date_taken ?? null, lang) })}
                onAccept={() => {
                  void api.assignItemTag(itemId, s.event.tag, false)
                    .then(() => { refresh(); onAnswered?.(); });
                }}
                onDismiss={() => {
                  void api.dismissSuggestedEvent(itemId, s.event.id)
                    .then(() => onAnswered?.());
                }}
              />
            ))}
          </>
        )}
      </div>
      {/* No "New" button beside the field: committing a name nobody has is
          what opens the create form (`add`), so the button was a second door
          to the same place. */}
      <div style={{ marginTop: 8 }}>
        <TagAutocomplete
          value={adding}
          onChange={setAdding}
          onCommit={(name) => void add(name)}
          suggestions={options}
          placeholder={t("Add an event…")}
          freeText
          minWidth={240}
        />
      </div>

      {(creating != null || editing) && (
        // AN EVENT IS DATA ON A TAG, so this is the tag editor with its Event
        // section in front — the same one the Tags tab opens.
        <RecordEditOverlay
          tagId={editing ? editing.tag_id : null}
          kind="event"
          prefillName={editing ? "" : (creating ?? "")}
          onClose={() => { setCreating(null); setEditing(null); }}
          onSaved={async (made) => {
            // An event created from here is meant for THIS item, so it lands
            // on it — otherwise the form ends with nothing to show for it.
            if (!editing && made.event && made.name) {
              await api.assignItemTag(itemId, made.name, false);
            }
            refresh();
            onAnswered?.();
          }}
        />
      )}
      {focusTag && onFocused && <FocusOnce onDone={onFocused} />}
    </div>
  );
}


/** When the picture was taken: what is known, where it came from, and a field
 *  to say something better.
 *
 *  The SOURCE is shown because "1975" is a different claim depending on who
 *  said it — the camera, a person, or the convention the picture is tagged
 *  with — and only the last of those is a guess the reader should be able to
 *  overrule at a glance.
 *
 *  Precision is whatever gets typed. "2020" is a year, "5 March 2020 14:30" is
 *  a minute, and a search reads each as the window it is: the encoding carries
 *  its own precision (`subjects/taken.ts`), so nothing has to ask how much of
 *  the number is real.
 */
function TakenControl({ itemId, detail, onChange }: {
  itemId: number;
  detail: ItemDetail | null;
  onChange: () => void;
}) {
  const t = useT();
  // The month names follow the UI language both ways — what the field
  // prefills is what it has to read back, and the event form already does so.
  const lang = useLang();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const value = detail?.taken_at ?? null;
  const source = detail?.taken_source ?? "";

  const put = async (taken_at: number) => {
    await api.updateItem(itemId, { taken_at });
    setEditing(false);
    qc.invalidateQueries({ queryKey: ["item", itemId] });
    qc.invalidateQueries({ queryKey: ["item-suggestions", itemId] });
    onChange();
  };
  const save = async (raw: string) => {
    // 0 unsays whatever was said and falls back to the file and the events.
    const parsed = raw.trim() ? parseTaken(raw, lang) : 0;
    if (parsed === null) return;            // unreadable: leave the field open
    await put(parsed);
  };
  /** "This picture has no date" — an answer, not the lack of one. */
  const saveNone = () => put(TAKEN_NONE);

  const said = value ? formatTaken(value, lang) : "";
  /** Somebody has said something here — a date, or that there is none. */
  const overridden = source === "set" || source === "never";
  // Only an AUTOMATIC date needs saying where it came from. What somebody
  // typed needs no label: they typed it, and a line reading "entered by hand"
  // under their own entry is the app explaining them to themselves. That the
  // date is theirs is already in the menu, where Automatic sits unticked.
  const where = source === "exif" ? t("from the file's EXIF data")
    : source === "event" ? t("from the event below")
    : "";

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6, marginBottom: 8,
      padding: "5px 6px 5px 8px", borderRadius: "var(--r-4)", minHeight: 26,
      background: "var(--panel-2)", border: "1px solid var(--border)",
    }}>
      <Icon name="schedule" size={15} color="var(--muted-2)" />
      {editing ? (
        <>
          <input
            autoFocus
            value={text}
            placeholder={t("year, date, or date and time")}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={useInlineEdit({ commit: () => void save(text),
                                       cancel: () => setEditing(false),
                                       commitOnBlur: false }).onKeyDown}
            style={{ flex: 1, minWidth: 0, height: 24, padding: "0 7px",
              background: "var(--bg)", border: "1px solid var(--border-strong)",
              borderRadius: "var(--r-2)", color: "var(--text)", fontSize: "var(--fs-3)",
              outline: "none" }} />
          <span onClick={() => void save(text)} title={t("Save")}
            style={{ cursor: "pointer", display: "flex", color: "var(--accent)" }}>
            <Icon name="check" size={16} />
          </span>
        </>
      ) : (
        <>
          <span style={{ minWidth: 0, flex: 1, display: "flex",
            flexDirection: "column", gap: 1 }}>
            <span style={{ fontSize: "var(--fs-3)",
              color: said ? "var(--text)" : "var(--muted-2)" }}>
              {said || t("No date on this item")}
            </span>
            {where && (
              <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                color: "var(--muted-3)" }}>{where}</span>
            )}
          </span>
          <RowMenu
            title={t("More actions")}
            always
            // No hints. Four verbs of two or three words each do not need a
            // sentence apiece underneath, and a menu that explains every entry
            // is one nobody finishes reading.
            actions={[
              { icon: "edit",
                label: said ? t("Change the date") : t("Set a date"),
                onClick: () => {
                  // Prefilled with what is shown, whoever said it: correcting
                  // the camera by a day should not mean typing the day out.
                  setText(said);
                  setEditing(true);
                } },
              // Saying there is NO date is its own answer, not the absence of
              // one: a scanned print carries the scanner's date, and without
              // this that date could be replaced but never removed.
              ...(source === "never" ? [] : [{
                icon: "event_busy", label: t("It has no date"),
                onClick: () => { void saveNone(); },
              }]),
              // The STATE of the two above, rather than a third verb: ticked,
              // nobody has overruled the file and the events, and picking it
              // is how you get back there. It was "Remove this entry", which
              // named the mechanism and appeared only once there was an entry
              // to remove — so the one thing the row could not say was which
              // of the two it was doing right now.
              { checked: !overridden, label: t("Automatic"),
                onClick: () => { if (overridden) void save(""); } },
            ]}
          />
        </>
      )}
    </div>
  );
}
