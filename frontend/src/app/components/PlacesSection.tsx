/** Where the item is — the sidebar's Places section.
 *
 * A place is a tag with location data attached, so the rows here are the item's
 * tags that a place claims, and adding one assigns that tag. What the section
 * adds over the tag panel is the address — one free line, written however
 * whoever typed it writes an address.
 *
 * Under the assigned rows sit the SUGGESTED ones: the venues of the events this
 * picture is at. They are offered and never assigned, because half of a week's
 * photographs were taken somewhere else — so each is a question with exactly
 * two answers, and both are spelled out rather than buried in a ⋯ menu.
 */
import React, { useMemo, useState } from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { rowBackground } from "../../shared/Row";
import { useInlineEdit } from "../../shared/useInlineEdit";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, FilePlaceSuggestion, ItemDetail, PlaceRow, SuggestedPlace } from "../api";
import { Icon } from "../../shared/Icon";
import { useT } from "../i18n";
import { TagAutocomplete } from "./TagAutocomplete";
import { RecordEditOverlay } from "./TagEditOverlay";
import { RowMenu } from "./shared/RowMenu";
import { useSearchActions } from "./shared/searchActions";
import { SuggestedHeading, SuggestedRow } from "./shared/SuggestedRow";
import { placeLabel, shortPlace } from "../../query/places/formats";
import { RowSelect } from "./shared/useRowSelect";
import { TagRangeLine, useTagRangeLabel } from "./shared/TagRanges";
import { useUndoRun } from "./shared/useUndoBar";
import { FocusOnce } from "./shared/FocusOnce";
import { WorldMap } from "../../shared/WorldMap";
import { formatCoord, parseCoord } from "../../shared/robinson";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";

/** The item's tags that a place claims. Exported because the properties panel
 *  needs the same list, in the same order, to give the selection its keys —
 *  two derivations of "which places are on this item" would drift. */
export function placesOnItem(places: PlaceRow[] | undefined,
                             detail: ItemDetail | null): PlaceRow[] {
  const names = new Set((detail?.tags ?? []).filter((x) => !x.negative)
    .map((x) => x.name));
  return (places ?? []).filter((p) => p.tag && names.has(p.tag));
}

export function PlacesSection({ itemId, detail, suggested = [], filePlace,
                                sel, focusTag,
                                onFocused, onChange, onAnswered }: {
  itemId: number;
  detail: ItemDetail | null;
  /** A place to land on, by identity tag — set when the Tags tab's pin marker
   *  sent you here. Cleared once the row has been shown. */
  focusTag?: string | null;
  onFocused?: () => void;
  /** Venues implied by the events on this item. Owned by the properties panel,
   *  which fetches them once for this section and the Events one below. */
  suggested?: SuggestedPlace[];
  /** The place the item's own file names — offered, never created. The
   *  importer used to mint it outright; accepting is what creates it now. */
  filePlace?: FilePlaceSuggestion | null;
  /** The tab's row selection, spanning this section and its siblings. */
  sel?: RowSelect;
  onChange: () => void;
  onAnswered?: () => void;
}) {
  const t = useT();
  const undoRun = useUndoRun();
  // Where else this place is — see `useSearchActions`.
  const searchActions = useSearchActions();
  const qc = useQueryClient();
  const { data: places } = useQuery({ queryKey: ["places"], queryFn: api.places });
  const [adding, setAdding] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<PlaceRow | null>(null);

  const onItem = useMemo(() => placesOnItem(places, detail), [places, detail]);
  const here = useMemo(() => new Set(onItem.map((p) => p.tag)), [onItem]);
  // Over a FILM a place is timed like any other tag — the crew was at the
  // hotel bar for these stretches and somewhere else for the rest.
  const rangeLabel = useTagRangeLabel(detail);

  // Offered BY ADDRESS with the slug underneath. You look for "Invalidenstraße",
  // not for `berlin_hauptbahnhof` — the address is what a place IS, and the tag
  // is the machinery under it. (Matching the tag as well costs nothing, so a
  // slug you happen to know still finds its place.)
  const options = useMemo(
    () => (places ?? []).filter((p) => p.tag && !here.has(p.tag))
      .map((p) => ({
        name: placeLabel(p),
        // The comment leads — it is the human half; the tag is machinery.
        comment: [p.comment, p.tag].filter(Boolean).join(" · "),
        uses: p.items,
      })),
    [places, here]
  );

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["places"] });
    onChange();
  };

  const add = async (text: string) => {
    const typed = text.trim();
    if (!typed) return;
    const low = typed.toLowerCase();
    const known = (places ?? []).find(
      (p) => p.tag === typed
        || placeLabel(p).toLowerCase() === low
    );
    if (known) {
      setAdding("");
      await api.assignItemTag(itemId, known.tag, false);
      refresh();
    } else {
      // A name nobody has yet opens the form — a place is structured data, so
      // it is not conjured from a text field the way a tag is. What was typed
      // goes WITH it: having to type the name a second time is the form
      // telling you it was not listening.
      setCreating(true);
    }
  };

  return (
    <div>
      {/* WHERE, before which places. Coordinates are the item's own answer —
          the file's, or one somebody typed — while the rows below are places
          the tag set knows; the same relation the date has to the events
          under it. */}
      <CoordsControl itemId={itemId} detail={detail} onChange={onChange} />
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {onItem.map((p) => (
          // A COLUMN, so the film's time ranges can sit under the address —
          // the timecodes are wider than most place names, and beside one the
          // name would have nowhere to go (the tag rows learned this first).
          <div key={p.id} {...(sel?.props(`p:${p.tag}`) ?? {})}
            className={focusTag === p.tag ? "hoverable mc-flash" : "hoverable"}
            style={{
            display: "flex", flexDirection: "column", gap: 2,
            padding: "5px 6px 5px 8px", borderRadius: "var(--r-4)", minHeight: 26,
            background: rowBackground(sel?.has(`p:${p.tag}`), "var(--panel-2)"),
            border: `1px solid ${sel?.has(`p:${p.tag}`) ? "var(--accent)" : "var(--border)"}`,
            // A row you can pick says so, exactly as the tag rows do — and only
            // where there IS a selection to join.
            cursor: sel ? "pointer" : undefined,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6,
              minHeight: 20 }}>
              <Icon name={RECORD_ICON.place} size={15} color="var(--muted-2)" />
              <span style={{ minWidth: 0, flex: 1, fontSize: "var(--fs-3)", color: "var(--text)",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={placeLabel(p)}>
                {shortPlace(p) || p.tag}
              </span>
              {/* No compass, and nothing else that marks one row out from
                  another. It meant "this place has coordinates", but on a row
                  that arrived by accepting an event's suggestion it read as
                  "this one came from somewhere else" — and a place accepted is
                  a place, exactly like one typed in. */}
              <RowMenu
                title={t("More actions")}
                always
                actions={[
                  { icon: "edit", label: t("Edit place…"),
                    hint: t("It is shared, so this changes it everywhere"),
                    onClick: () => setEditing(p) },
                  ...searchActions("place", p.tag,
                    shortPlace(p) || p.tag),
                  { icon: "close", label: t("Remove from this item"), danger: true,
                    onClick: () => void undoRun(`${t("Removed")} ${p.tag}`,
                      () => api.unassignItemTag(itemId, p.tag).then(refresh)) },
                ]}
              />
            </div>
            <TagRangeLine label={rangeLabel?.(p.tag) ?? null} indent={21} />
          </div>
        ))}
        {onItem.length === 0 && suggested.length === 0 && (
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", padding: "2px 0 4px" }}>
            {t("Nowhere in particular yet.")}
          </div>
        )}
        {(suggested.length > 0 || filePlace) && (
          <>
            <SuggestedHeading>{t("Suggested")}</SuggestedHeading>
            {filePlace && (
              <SuggestedRow
                icon={RECORD_ICON.place}
                label={filePlace.place
                       ? (shortPlace(filePlace.place) || filePlace.place.tag)
                       : filePlace.name}
                title={filePlace.name}
                reason={t("Written in the file itself")}
                onAccept={() => {
                  void api.adoptFilePlace(itemId)
                    .then(() => { refresh(); onAnswered?.(); });
                }}
                onDismiss={() => {
                  void api.dismissFilePlace(itemId)
                    .then(() => onAnswered?.());
                }}
              />
            )}
            {suggested.map((s) => (
              <SuggestedRow
                key={s.place.id}
                icon={RECORD_ICON.place}
                label={shortPlace(s.place)
                       || s.place.tag}
                title={placeLabel(s.place)}
                reason={t("{event} was here",
                          { event: s.via_event_name || s.via_event_tag })}
                onAccept={() => {
                  void api.assignItemTag(itemId, s.place.tag, false)
                    .then(() => { refresh(); onAnswered?.(); });
                }}
                onDismiss={() => {
                  void api.dismissSuggestedPlace(itemId, s.place.id,
                                                 s.occasion_id)
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
          placeholder={t("Add a place…")}
          // No normalizing while you type: this field searches ADDRESSES,
          // and "Invalidenstraße 43" turning into "invalidenstraße_43"
          // under the cursor matches nothing and reads as a malfunction.
          freeText
          minWidth={240}
        />
      </div>

      {(creating || editing) && (
        // A PLACE IS DATA ON A TAG, so this is the tag editor with its Place
        // section in front — the same one the Tags tab opens.
        <RecordEditOverlay
          tagId={editing ? editing.tag_id : null}
          kind="place"
          prefillName={editing ? "" : adding.trim()}
          onClose={() => {
            setCreating(false); setEditing(null); setAdding("");
          }}
          onSaved={async (made) => {
            // A place created from here is meant for THIS item, so it lands on
            // it — otherwise the form would end with nothing to show for it.
            // The editor hands over what it made, so there is no guessing at
            // which row of the list is new.
            if (!editing && made.place && made.name) {
              await api.assignItemTag(itemId, made.name, false);
            }
            refresh();
          }}
        />
      )}
      {focusTag && onFocused && <FocusOnce onDone={onFocused} />}
    </div>
  );
}


/**
 * THE ITEM'S OWN COORDINATES — the file's, or the pair somebody typed.
 *
 * Three states and one rule, exactly as `TakenControl` has for the date: what
 * was typed wins, the file answers when nothing was, and "there are none" is
 * an answer of its own — without it a wrong fix off a borrowed camera could
 * be replaced but never removed.
 *
 * The map is drawn from the numbers against an outline that ships with the
 * app: nothing is fetched, and where a picture was taken never leaves the
 * machine.
 */
function CoordsControl({ itemId, detail, onChange }: {
  itemId: number;
  detail: ItemDetail | null;
  onChange: () => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [big, setBig] = useState(false);
  const lat = detail?.lat ?? null;
  const lon = detail?.lon ?? null;
  const source = detail?.coords_source ?? "";
  const has = lat != null && lon != null;

  const put = async (body: Parameters<typeof api.updateItem>[1]) => {
    await api.updateItem(itemId, body);
    setEditing(false);
    qc.invalidateQueries({ queryKey: ["item", itemId] });
    onChange();
  };
  const save = async (raw: string) => {
    if (!raw.trim()) { await put({ clear_coords: true }); return; }
    const got = parseCoord(raw);
    if (!got) return;                    // unreadable: leave the field open
    await put({ lat: got.lat, lon: got.lon });
  };

  const said = has ? formatCoord(lat, lon) : "";
  const overridden = source === "set" || source === "never";
  // Only an AUTOMATIC answer needs saying where it came from — the same rule
  // the date row follows.
  const where = source === "exif" ? t("from the file's own coordinates") : "";

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "5px 6px 5px 8px", borderRadius: "var(--r-4)", minHeight: 26,
        background: "var(--panel-2)", border: "1px solid var(--border)",
      }}>
        <Icon name="explore" size={15} color="var(--muted-2)" />
        {editing ? (
          <>
            <input
              autoFocus
              value={text}
              placeholder="35.6812, 139.7671"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={useInlineEdit({ commit: () => void save(text),
                                         cancel: () => setEditing(false),
                                         commitOnBlur: false }).onKeyDown}
              style={{ flex: 1, minWidth: 0, height: 24, padding: "0 7px",
                background: "var(--bg)", border: "1px solid var(--border-strong)",
                borderRadius: "var(--r-2)", color: "var(--text)", fontSize: "var(--fs-3)",
                fontFamily: "var(--mono)", outline: "none" }} />
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
                fontFamily: said ? "var(--mono)" : undefined,
                color: said ? "var(--text)" : "var(--muted-2)" }}>
                {said || t("No coordinates on this item")}
              </span>
              {where && (
                <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                  color: "var(--muted-3)" }}>{where}</span>
              )}
            </span>
            <RowMenu
              title={t("More actions")}
              always
              actions={[
                { icon: "edit",
                  label: said ? t("Change the coordinates") : t("Set coordinates"),
                  onClick: () => { setText(said); setEditing(true); } },
                ...(source === "never" ? [] : [{
                  icon: "location_off", label: t("It has no coordinates"),
                  onClick: () => { void put({ no_coords: true }); },
                }]),
                { checked: !overridden, label: t("Automatic"),
                  onClick: () => { if (overridden) void put({ clear_coords: true }); } },
              ]}
            />
          </>
        )}
      </div>
      {has && (
        <div style={{ marginTop: 6 }}>
          <WorldMap points={[{ lat, lon }]} height={72} zoom={2.5}
                    title={said} onClick={() => setBig(true)} />
        </div>
      )}
      {big && has && (
        <Overlay icon="explore" title={t("Where this was taken")}
          subtitle={said} width={860} onClose={() => setBig(false)}
          footer={<Button variant="ghost" onClick={() => setBig(false)}>{t("Close")}</Button>}>
          <div style={{ padding: 18, display: "flex", justifyContent: "center" }}>
            <WorldMap points={[{ lat, lon }]} height={360} title={said} />
          </div>
        </Overlay>
      )}
    </div>
  );
}
