// CSV import / export for the Tags tab.
//
// BOTH SIDES SPEAK THE SAME FIVE SHAPES (`CSV_KINDS`): the tag table, the
// aliases, the implications, the meta tags ON tags, and the meta-tag namespace
// itself. Each is its own file — an alias row and an implication row have
// nothing in common beyond a tag name, and a relation that a tag can have
// several of cannot live in one cell without a separator nobody remembers. So
// the import picks a shape (guessed from the header) and maps its two-or-so
// columns, rather than offering every field of every shape at once, and what
// the export writes imports back unchanged.
import React, { useEffect, useMemo, useState } from "react";
import { storage } from "../../shared/storage";
import { SectionHeading } from "../../shared/SectionHeading";
import { filterNumeric } from "../../shared/useNumericText";
import { Select } from "../../shared/Select";
import { SegmentedControl } from "../../shared/SegmentedControl";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError, EventRow, LinkTagRow, PlaceRow, SubjectRow, TagRow }
  from "../api";
import { Icon } from "../../shared/Icon";
import { useT } from "../i18n";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { downloadText, parseCsv, toCsv } from "../csv";
import { chunks, runBulk } from "../bulk";
import { normalizeTagName, sanitizeLinkTagInput, tagCount } from "../tags";
import { moveBlock as reorder } from "../exportColumns";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { TagSuggestList, useSuggestList } from "./TagSuggestList";
import { rankTagMatches, SUGGEST_CAP } from "../tagRank";

/** Rows in flight at once during an import. The rows of one file are largely
 *  independent, so a few concurrent requests pipeline the round-trips; shared
 *  names are serialized through the in-flight maps below. */
const CSV_CHUNK = 8;

/** Rows per bulk-upsert request — one transaction each. Two thousand keeps a
 *  request comfortably under a second, so closing the dialog still stops the
 *  run promptly (the abort is checked between batches). */
const BULK_ROWS = 2000;

const NONE = "-1";

const CSV_KINDS = [
  ["tags", "Tags", "The tag table: names, comments and counts."],
  ["aliases", "Aliases", "One row per alias and the tag it stands for."],
  ["implications", "Implications",
   "One row per implication: a tag and something it entails."],
  // What the TAG SET says about a tag. One row per assignment, like the
  // two shapes above it — a tag can carry several, and they are names in a
  // namespace of their own rather than a field of the tag.
  // "Meta assignments", not "Meta": beside "Meta tags" — the namespace's own
  // table, two rows down — one word could only ever name one of them.
  ["tag_meta", "Meta assignments",
   "One row per assignment: a tag and a meta tag on it."],
  // Meta tags are a separate namespace (links, captions and tag groups share
  // it), so this is the only shape offered when the Meta list is showing.
  ["meta", "Meta tags", "The meta-tag table: names, comments and per-carrier counts."],
] as const;
type CsvKind = typeof CSV_KINDS[number][0];

/** The shapes on offer: the Meta list has only its own, the item-tag list the
 *  other four. */
function offeredKinds(meta: boolean) {
  return CSV_KINDS.filter(([k]) => (meta ? k === "meta" : k !== "meta"));
}

/** The segmented control both overlays open with. */
function KindTabs({ kinds, value, onChange }: {
  kinds: readonly (readonly [CsvKind, string, string])[];
  value: CsvKind;
  onChange: (k: CsvKind) => void;
}) {
  const t = useT();
  return (
    <SegmentedControl<CsvKind>
      value={value}
      onChange={onChange}
      stretch
      style={{ marginBottom: 14 }}
      options={kinds.map(([k, label, hint]) => ({
        value: k, label: t(label), title: t(hint),
      }))}
    />
  );
}

/**
 * Renders every kind's body stacked in one grid cell and hides all but the
 * current one. The overlay is vertically centred, so a shorter body would move
 * the whole panel — and with it the segmented control right out from under the
 * cursor that just clicked it. (`visibility: hidden` also takes the hidden
 * fields out of the tab order.)
 */
function KindStack({ kinds, value, render }: {
  kinds: readonly (readonly [CsvKind, string, string])[];
  value: CsvKind;
  render: (k: CsvKind) => React.ReactNode;
}) {
  return (
    // `minWidth: 0` on the stack AND on every cell: they share one grid area,
    // so without it the WIDEST kind's content decides the dialog's width —
    // including the kind nobody is looking at.
    <div style={{ display: "grid", minWidth: 0 }}>
      {kinds.map(([k]) => (
        <div key={k} aria-hidden={k !== value}
          style={{ gridArea: "1 / 1", minWidth: 0,
                   visibility: k === value ? "visible" : "hidden" }}>
          {render(k)}
        </div>
      ))}
    </div>
  );
}

type Field = "name" | "comment" | "description" | "alias" | "target" | "tag"
  | "implies" | "meta" | "count" | RecordField;

/** The count column, which the Count group's own header row holds and the
 *  plain-field loop therefore skips. */
const COUNT_FIELDS: ReadonlySet<string> = new Set(["count"]);

/** One cell as a number, and 0 for anything that is not one. */
function countNum(v: string): number {
  const n = Number((v ?? "").replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

/** WHAT A ROW SAYS THE COUNT IS — one figure, so the minimum below and the
 *  stored per-meta count read the same number and cannot disagree. */
function countOf(cell: (k: Field) => string): number {
  return countNum(cell("count"));
}

/**
 * WHAT A TAG IS BESIDES A TAG, field by field.
 *
 * A subject, a place and an event are each extra data ON a tag, so a table of
 * tags is where they belong — and one column each was not enough to say them:
 * a slug cannot hold "Michael Jordan", a street address or a span of days,
 * which is the whole reason those records exist. These are the fields, so what
 * the export writes the import reads back. One list, used by both sides, or
 * the two would drift a column apart.
 *
 * A place is ONE address line and the place it is inside, so it is an address
 * and the eight PART kinds — the fixed tag set in `places/formats.ts`,
 * named here in plain words rather than by their internal kind.
 *
 * Dates are the app's own PARTIAL form, `YYYYMMDD` with zeros for what is
 * unknown (`19750000` is "1975"). Written as the number rather than as
 * "14 March 1879": it is the value the library stores, it reads back
 * unambiguously, and it sorts.
 */
// [key, label, kind, extra header needles] — the needles cover spellings an
// older export wrote ("Place address", "Place inside"), so those files keep
// guessing their mapping after the rename.
const RECORD_FIELDS = [
  ["subject", "Subject", "subject", []],
  ["subject_since", "Subject since", "subject", []],
  // No `subject_comment` / `place_comment` / `event_comment`: what a named
  // thing IS, in a line and at length, is its TAG's, and the file's own
  // Comment and Description columns are that field.
  ["place_name", "Place", "place", ["place name", "place address", "address"]],
  ["place_parent", "Place parent", "place", ["place inside"]],
  ["place_lat", "Place latitude", "place", []],
  ["place_lon", "Place longitude", "place", []],
  ["event", "Event", "event", []],
  ["event_parent", "Event parent", "event", ["event inside"]],
  ["event_start", "Event start", "event", []],
  ["event_end", "Event end", "event", []],
] as const;
type RecordField = typeof RECORD_FIELDS[number][0];

/** The three kinds, in the order both sides group them. */
const RECORD_KINDS = [
  ["subject", "Subject"], ["place", "Place"], ["event", "Event"],
] as const;

/** The field that NAMES each kind — mapped on the group's own row in the
 *  import overlay, the way the count column is. */
const RECORD_PRIMARY: Record<string, Field> = {
  subject: "subject", place: "place_name", event: "event",
};

/** Field key → which record kind it belongs to, and "" for a plain tag field.
 *  Read off `RECORD_FIELDS` rather than written a second time — the export's
 *  grouping already learned that a hand-kept list of exclusions gains a wrong
 *  entry the moment a field is added. */
const RECORD_KIND: Record<string, string> = Object.fromEntries(
  RECORD_FIELDS.map(([key, , kind]) => [key, kind]));

/** The record fields' values for one tag, keyed by field. Empty where the tag
 *  is not that kind of thing at all. */
function recordValues(name: string, records?: TagRecords): Record<string, string> {
  const out: Record<string, string> = {};
  const s = records?.subjects.get(name);
  const pl = records?.places.get(name);
  const ev = records?.events.get(name);
  if (s) {
    out.subject = s.display_name ?? "";
    out.subject_since = s.since_date ? String(s.since_date) : "";
  }
  if (pl) {
    out.place_name = pl.name ?? "";
    // BY ITS IDENTITY TAG, like an event's venues: a file refers to another
    // row by name, never by an id that means nothing outside this library.
    out.place_parent = records?.placeParentTag?.get(name) ?? "";
    out.place_lat = pl.lat != null ? String(pl.lat) : "";
    out.place_lon = pl.lon != null ? String(pl.lon) : "";
  }
  if (ev) {
    out.event = ev.display_name || ev.tag;
    out.event_parent = records?.eventParentTag?.get(name) ?? "";
    out.event_start = ev.start_date ? String(ev.start_date) : "";
    out.event_end = ev.end_date ? String(ev.end_date) : "";
  }
  return out;
}

const inputStyle: React.CSSProperties = {
  height: 32, padding: "0 10px", background: "var(--bg)",
  border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)",
  color: "var(--text)", fontSize: "var(--fs-3)", fontFamily: "inherit", outline: "none",
};

function Row({ label, hint, children, last, lead, onClick, dragProps,
               inset, compact }: {
  label: string; hint?: string; children: React.ReactNode; last?: boolean;
  /** Rendered before the label — the export list's drag handle. */
  lead?: React.ReactNode;
  /** Makes the whole row the control: a column is toggled by clicking it
   *  anywhere, not only its checkbox. */
  onClick?: () => void;
  dragProps?: React.HTMLAttributes<HTMLDivElement>;
  /** A row inside a group: indented under its heading, and shorter still —
   *  sixteen of them open at once is a lot of list. */
  inset?: boolean;
  /** Shorter, for a list that is only labels and checkboxes. */
  compact?: boolean;
}) {
  // The drag styling is MERGED over the row's own, not spread beside it: a
  // `style` prop after the spread would silently win, which is how the lifted
  // look came to do nothing at all.
  const { style: dragStyle, ...dragRest } = dragProps ?? {};
  return (
    <div
      {...dragRest}
      onClick={onClick}
      style={{
        // A ROW IS ITS LABEL AND ITS SENTENCE, not two paragraphs. The mapping
        // list is up to twenty of these, every one with a line of hint under
        // it, so what the padding costs is multiplied twenty times over — and
        // the hint sits a hair under its own title rather than floating
        // between two rows.
        padding: inset ? "3px 16px 3px 36px" : compact ? "6px 16px" : "7px 16px",
        borderBottom: last ? "none" : "1px solid var(--border-soft)",
        cursor: onClick ? "pointer" : undefined, userSelect: onClick ? "none" : undefined,
        ...dragStyle,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16,
                    minHeight: inset ? 22 : compact ? 26 : 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
          {lead}{label}
        </div>
        {children}
      </div>
      {hint && <div style={{ fontSize: "var(--fs-2)", lineHeight: 1.4, color: "var(--muted-2)", marginTop: 1 }}>{hint}</div>}
    </div>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      background: "var(--panel)", border: "1px solid var(--border)",
      borderRadius: "var(--r-7)", overflow: "hidden", marginBottom: 16,
    }}>
      {children}
    </div>
  );
}

/** A checkbox that can also say "some of them" — `indeterminate` is a DOM
 *  property, not an attribute, so it can only be set through a ref. */
function TriCheckbox({ state }: { state: "on" | "off" | "some" }) {
  const ref = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "some";
  }, [state]);
  return (
    <input ref={ref} type="checkbox" checked={state === "on"} readOnly
           tabIndex={-1} style={{ pointerEvents: "none" }} />
  );
}


/** Column <select> used by the mapping step. */
function ColumnSelect({ value, onChange, columns, allowNone }: {
  value: string; onChange: (v: string) => void;
  columns: string[]; allowNone?: boolean;
}) {
  const t = useT();
  return (
    <Select value={value} onChange={onChange} minWidth={190}>
      {allowNone && <option value={NONE}>{t("— not imported —")}</option>}
      {columns.map((c, i) => <option key={i} value={String(i)}>{c}</option>)}
    </Select>
  );
}

/** One mapped column of an import shape. The FIRST field of a shape is what
 *  identifies the row; a row missing it (or a required second) is skipped. */
interface ImportField {
  key: Field;
  label: string;
  hint: string;
  required?: boolean;
  /** Header words that give this field away, for the initial guess. */
  needles: string[];
}

/** What one record field says, for the mapping row's subtitle. Written per
 *  KIND rather than per field: sixteen sentences saying "optional — part of
 *  the place" would be sixteen ways of saying one thing. */
function recordHint(key: RecordField): string {
  if (key === "subject_since" || key === "event_start" || key === "event_end") {
    return "Optional — a partial date, YYYYMMDD with zeros for what is unknown (19750000 is “1975”).";
  }
  if (key === "place_lat" || key === "place_lon") {
    return "Optional — a decimal coordinate, as a map or a photo's metadata writes it. The pair moves together: one without the other is not a position.";
  }
  const kind = RECORD_FIELDS.find(([k]) => k === key)?.[2];
  return kind === "subject"
    ? "Optional — makes the tag a subject (a person, an animal, a character)."
    : kind === "place"
      ? "Optional — makes the tag a place."
      : "Optional — makes the tag an event.";
}

const IMPORT_FIELDS: Record<CsvKind, ImportField[]> = {
  tags: [
    { key: "name", label: "Tag name", required: true, needles: ["tag", "name"],
      hint: "Required — the tag itself. Existing tags are updated, unknown ones created." },
    { key: "comment", label: "Comment", needles: ["comment", "note"],
      hint: "Optional — the one-liner shown beside the tag's name and in the autocomplete." },
    // No description column: a tag has no long form of its own — that is a
    // TAG SET's (import one from the Sets sub-tab). The meta shape below
    // keeps its column, since a meta tag still carries one.
    // ONE count column. A dump has one number per tag, and whether it means
    // "in this library" or "where these came from" is a fact about the FILE —
    // which is the toggle under it, not a second mapping. Read but never
    // stored otherwise: this library's own count is its own business.
    { key: "count", label: "Count", needles: ["count", "posts", "uses", "positive", "offset"],
      hint: "Optional — the file's own count for each tag." },
    // …and the record a tag can carry. Optional every one: a file of plain
    // tags maps none of them and nothing is created.
    ...RECORD_FIELDS.map(([key, label, , extra]) => ({
      key: key as Field,
      label,
      needles: [label.toLowerCase(), ...extra],
      hint: recordHint(key),
    })),
  ],
  aliases: [
    { key: "alias", label: "Alias", required: true, needles: ["alias"],
      hint: "Required — the other spelling. Created if it doesn't exist yet." },
    { key: "target", label: "Tag", required: true, needles: ["tag", "target", "name"],
      hint: "Required — the tag the alias stands for." },
  ],
  implications: [
    { key: "tag", label: "Tag", required: true, needles: ["tag", "name"],
      hint: "Required — the tag that entails another (e.g. 'poodle')." },
    { key: "implies", label: "Implies", required: true, needles: ["implies", "implied", "entails", "parent"],
      hint: "Required — one tag it entails (e.g. 'dog'). A tag entailing several has a row each." },
  ],
  tag_meta: [
    { key: "tag", label: "Tag", required: true, needles: ["tag", "name"],
      hint: "Required — the tag being described. Created if it doesn't exist yet." },
    { key: "meta", label: "Meta tag", required: true, needles: ["meta", "label"],
      hint: "Required — one meta tag it carries. A tag carrying several has a row each." },
    { key: "count", label: "Count", needles: ["count", "posts"],
      hint: "Optional — pictures the tag has where THIS meta tag says, stored on the assignment." },
  ],
  meta: [
    { key: "name", label: "Meta tag", required: true, needles: ["meta", "tag", "name"],
      hint: "Required — the meta tag itself. Existing ones are updated, unknown ones created." },
    { key: "comment", label: "Comment", needles: ["comment", "note"],
      hint: "Optional — the one-liner shown beside the meta tag's name." },
    { key: "description", label: "Description", needles: ["description", "help", "about"],
      hint: "Optional — the long form, reached from the ? beside the name." },
  ],
};

/** The column that may hold several values, per pair shape — always the
 *  MANY side of the pair. A file listing a tag's aliases writes them in one
 *  cell ("x, y, z"); which character separates them is the file's business,
 *  so it is asked for rather than guessed. */
/** The fields that hold a TAG NAME, and the one that holds a meta tag's.
 *
 *  A file is untrusted text and the API refuses a name with a space in it —
 *  so "tiny giant" ended the import at that row with `tag names cannot
 *  contain spaces`, which was survivable while a cell was one value and is
 *  not once a cell can be a list of them. The app's own field rule is applied
 *  instead, at the point the file's text BECOMES a name: `tiny giant` is
 *  stored as `tiny_giant`, and the preview shows that rather than what was
 *  typed into somebody else's spreadsheet.
 *
 *  Case is deliberately left alone (see `tags.ts`): the API accepts mixed
 *  case precisely because an import can carry it. */
const NAME_FIELDS: ReadonlySet<string> =
  new Set(["name", "alias", "target", "tag", "implies"]);

const MULTI_FIELD: Partial<Record<CsvKind, Field>> = {
  aliases: "alias",
  implications: "implies",
  tag_meta: "meta",
};

/** THE "MARK EVERY TAG WITH" FIELD: one comma-separated line, completed a
 *  fragment at a time.
 *
 *  A plain `TagAutocomplete` cannot do this — it matches its list against the
 *  WHOLE field, so "character," offers nothing, and committing replaces
 *  everything typed so far with the picked name. The line has to stay a line
 *  (it is one setting, not a list to curate), so the list matches the
 *  fragment after the last comma and picking splices it back in.
 *
 *  Names are PICKED rather than retyped because a typo here is a new meta tag
 *  nobody meant to make, put on every tag in the file. A fragment matching
 *  nothing therefore gets the tag autocomplete's own "Create …" row: the name
 *  was always going to be minted by simply typing it, and a row that says so
 *  is what turns the typo into a decision. */
function MarkField({ value, onChange, names, placeholder, single }: {
  value: string;
  onChange: (v: string) => void;
  names: string[];
  placeholder?: string;
  /** ONE name, not a comma list — the count target takes exactly one. */
  single?: boolean;
}) {
  const ref = React.useRef<HTMLInputElement>(null);
  const cut = single ? -1 : value.lastIndexOf(",");
  const head = cut < 0 ? "" : value.slice(0, cut + 1);
  const typed = value.slice(cut + 1).trim();
  const frag = typed.toLowerCase();
  const already = new Set(value.split(",").map((s) => s.trim().toLowerCase())
                                .filter(Boolean));
  // The names already on the line are out — except the fragment ITSELF,
  // which the split reads as a name too and which is the one being typed.
  const taken = new Set([...already].filter((n) => n !== frag));
  const rows = names.map((name) => ({ name }));
  const shown = rankTagMatches(rows, frag,
    new Set(rows.filter((r) => taken.has(r.name.toLowerCase())).map((r) => r.name)),
    SUGGEST_CAP);
  // WHAT TYPING SOMETHING NEW MEANS. The name in the field is minted the
  // moment the import runs, so a fragment the namespace does not hold is a
  // meta tag about to be created — said out loud in the committed form
  // (`sanitizeLinkTagInput`, what the import will actually store) rather than
  // left to be discovered afterwards.
  const create = sanitizeLinkTagInput(typed);
  const canCreate = !!create
    && !names.some((n) => n.toLowerCase() === create.toLowerCase())
    && ![...already].some((n) => n !== frag && n === create.toLowerCase());
  // A trailing ", " so the next name can simply be typed — except a single
  // field, which IS the one name once picked.
  const take = (n: string) => {
    onChange(single ? n : `${head}${head ? " " : ""}${n}, `);
    list.dismiss();
  };
  const list = useSuggestList<{ name: string }>({
    matches: shown, create: canCreate ? create : null,
    onPick: (row) => {
      if (row.kind === "create") take(row.name);
      else if (row.kind === "match") take(row.item.name);
    },
    input: {},
  });
  const rect = useAnchorRect(ref, list.open);
  return (
    <div style={{ position: "relative", width: 200 }}>
      <input
        ref={ref}
        value={value}
        placeholder={placeholder}
        onChange={(e) => { onChange(e.target.value); list.undismiss(); }}
        {...list.inputProps}
        style={{ ...inputStyle, width: "100%" }}
      />
      {list.open && (
        <AnchoredDropdown rect={rect} minWidth={200} fill>
          <TagSuggestList list={list} dense fill
            renderRow={(n) => (<>
              <Icon name="label" size={13} color="var(--muted-2)" />
              <span style={{ fontFamily: "var(--mono)" }}>{n.name}</span>
            </>)} />
        </AnchoredDropdown>
      )}
    </div>
  );
}

/** A row's answer, picked from a short list — the dialog's own `<select>`,
 *  drawn rather than left to the platform (the native arrow is a different
 *  size and colour in every browser, and these sit inside a panel row).
 *
 *  Two rows ask a question of this shape now — what an existing tag keeps,
 *  and what a count that is already there does — so it is one component: two
 *  copies of a hand-drawn select is two chevrons to keep in step. */
function ModeSelect({ value, onChange, options, minWidth = 190 }: {
  value: string;
  onChange: (v: string) => void;
  options: readonly (readonly [string, string])[];
  minWidth?: number;
}) {
  return (
    <Select value={value} onChange={onChange} options={options} minWidth={minWidth} />
  );
}

export function TagCsvImportOverlay({ rows, filename, meta, onClose, onDone }: {
  /** Importing into the META namespace: name + comment only, no aliases and
   *  no implications — meta tags have neither. */
  meta?: boolean;
  rows: string[][];
  filename: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const [header, setHeader] = useState(true);
  // Which record kinds are open. Collapsed by default: most files have none
  // of those columns, and sixteen rows of them is the list nobody reads.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const toggleGroup = (g: string) =>
    setExpanded((e) => ({ ...e, [g]: !e[g] }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState("");
  // CLOSING THE DIALOG STOPS THE RUN. It used to keep going invisibly —
  // thousands of requests hammering the library with nothing on screen
  // saying so. The signal is checked between chunks, so the rows in flight
  // land and nothing further starts; what was imported stays imported.
  const abortRef = React.useRef<AbortController | null>(null);
  const close = () => { abortRef.current?.abort(); onClose(); };
  const kinds = offeredKinds(!!meta);

  const columns = useMemo(() => {
    const width = Math.max(...rows.map((r) => r.length), 0);
    return Array.from({ length: width }, (_, i) =>
      header ? (rows[0]?.[i]?.trim() || `${t("Column")} ${i + 1}`) : `${t("Column")} ${i + 1}`);
  }, [rows, header, t]);

  // Which column carries what, guessed from the header names. Each field takes
  // the first column no earlier field claimed, so "Alias, Tag" maps in order
  // even though both headers match "tag".
  const guessFor = (k: CsvKind): Record<string, string> => {
    const out: Record<string, string> = {};
    const taken = new Set<number>();
    const got: Record<string, number> = {};
    if (header) {
      // EXACT headers claim their columns first, across ALL fields — then the
      // substring pass mops up. Per-field it would go wrong twice over:
      // "Place" is a substring of every other place column's header, so with
      // no "Place" column in the file it would swallow "Place parent" before
      // that field's own turn came.
      for (const f of IMPORT_FIELDS[k]) {
        const idx = columns.findIndex((c, ci) =>
          !taken.has(ci) && f.needles.some((n) => c.trim().toLowerCase() === n));
        if (idx >= 0) { taken.add(idx); got[f.key] = idx; }
      }
      for (const f of IMPORT_FIELDS[k]) {
        if (got[f.key] != null) continue;
        const idx = columns.findIndex((c, ci) =>
          !taken.has(ci) && f.needles.some((n) => c.toLowerCase().includes(n)));
        if (idx >= 0) { taken.add(idx); got[f.key] = idx; }
      }
    }
    IMPORT_FIELDS[k].forEach((f, i) => {
      let idx = got[f.key] ?? -1;
      // No header (or no match): fall back to the columns in order for the
      // required fields, and to "not imported" for the optional ones.
      if (idx < 0 && f.required) {
        idx = columns.findIndex((_, ci) => !taken.has(ci) && ci >= i);
        if (idx >= 0) taken.add(idx);
      }
      out[f.key] = idx < 0 ? NONE : String(idx);
    });
    return out;
  };

  // The shape of the file, guessed from its header once and then the user's to
  // choose. An "Alias" column means the aliases file however it is named.
  const [kind, setKind] = useState<CsvKind>(() => {
    if (meta) return "meta";
    const head = (rows[0] ?? []).map((c) => c.toLowerCase());
    if (head.some((c) => c.includes("alias"))) return "aliases";
    if (head.some((c) => c.includes("implies") || c.includes("implied"))) return "implications";
    // A "meta" column HERE is the assignments file: the namespace's own table
    // is only ever offered on the Meta side, so the two cannot compete.
    if (head.some((c) => c.includes("meta"))) return "tag_meta";
    return "tags";
  });
  // The guess is re-made per kind; a column the user picks sticks until the
  // kind (or the header toggle) changes what the guess would even mean.
  const [picked, setPicked] = useState<Record<string, string>>({});
  useEffect(() => { setPicked({}); }, [kind, header]);
  const fields = IMPORT_FIELDS[kind];
  const map = { ...guessFor(kind), ...picked };
  // A GROUP THE FILE ACTUALLY USES OPENS ITSELF. Collapsed is right for the
  // ordinary file, which has none of these columns — but a file whose header
  // named three subject fields has had them mapped for you, and hiding that
  // behind a chevron is the guess doing its work invisibly. Only ever opens:
  // closing one by hand has to stick.
  const mappedKinds = RECORD_KINDS
    .filter(([kind2]) => IMPORT_FIELDS.tags.some(
      (f) => RECORD_KIND[f.key] === kind2
             && f.key !== RECORD_PRIMARY[kind2]
             && (map[f.key] ?? NONE) !== NONE))
    .map(([kind2]) => kind2).join(",");
  useEffect(() => {
    if (!mappedKinds) return;
    setExpanded((e) => {
      const next = { ...e };
      for (const g of mappedKinds.split(",")) next[g] = true;
      return next;
    });
  }, [mappedKinds]);

  // WHAT SEPARATES SEVERAL VALUES IN ONE CELL. Empty means the cell IS one
  // value — which is the shape the export writes and the only one that can
  // hold a name containing the separator. Per kind, since a file of aliases
  // and a file of implications are different files.
  const [splitOn, setSplitOn] = useState("");
  // THE MINIMUM COUNT, as text: an empty field is "no minimum", which is a
  // different thing from 0 (a tag used nowhere is still a tag).
  const [minCount, setMinCount] = useState("");
  // WHAT THE COUNT MEANS. With no meta tag named, it is only the minimum's
  // input — the file's idea of how used a tag is says nothing about this
  // library. NAME one (a site, usually) and the count is stored on that
  // meta tag's ASSIGNMENT — per assignment, so "abc" can carry tumblr 50
  // and twitter 100 at once, which one tag-level number never could. The
  // mode is the count's own conflict policy and the WHOLE of it: keep the
  // number, replace it, or keep the smaller or the larger of the two. Its
  // own policy rather than the overwrite switch's, because "which of two
  // counts is right" has answers ("the larger — dumps only grow") that
  // "which words win" does not — and it used to READ that switch, through a
  // "Keep it, unless overwriting" entry which is a state of some other
  // control written into this one's list.
  const [countMeta, setCountMeta] = useState("");
  const [countMode, setCountMode] =
    useState<"keep" | "replace" | "min" | "max">("keep");
  // WHAT AN EXISTING TAG KEEPS — three answers, not a switch. "Fill in the
  // gaps" is the default, because importing a dump over a library somebody
  // has curated must not quietly rewrite their own words; "update" takes the
  // file's value for every column it maps; and "match the file" additionally
  // CLEARS what the file leaves empty, which is the only way to make the
  // library say exactly what the file says. A tag the file does not NAME is
  // untouched in all three — this is about the rows it does.
  const [existing, setExisting] =
    useState<"keep" | "update" | "replace">("keep");
  // MARK EVERY TAG THIS FILE TOUCHES. A booru dump imported as a batch is
  // usually one KIND of thing — "these are all characters", "none of these
  // should be flipped" — and that is a fact about the whole file rather than
  // a column in it. Applied to tags that ALREADY exist too: the file names
  // them, which is the whole claim being made.
  const [markAll, setMarkAll] = useState("");
  // The NAMESPACE's own names, so a mark is picked rather than retyped: a
  // typo here would mint a meta tag and put it on every tag in the file.
  const { data: knownMeta } = useQuery({
    queryKey: ["link-tags"], queryFn: api.linkTags,
  });
  const marks = useMemo(
    () => markAll.split(",").map((s) => sanitizeLinkTagInput(s.trim()))
      .filter(Boolean),
    [markAll]
  );
  // The ONE meta tag the count column lands on, normalized like a mark.
  const countTarget = useMemo(
    () => sanitizeLinkTagInput(countMeta.trim()), [countMeta]);
  const dataRows = header ? rows.slice(1) : rows;
  // One entry per row: the mapped values in field order. A row that is missing
  // a required value has nothing to say and is dropped.
  const entries = useMemo(() => {
    const min = minCount.trim() === "" ? null : countNum(minCount);
    const at = (key: string) => fields.findIndex((f) => f.key === key);
    const mapped = dataRows
      .map((r) => fields.map((f) => {
        const idx = Number(map[f.key]);
        return idx >= 0 ? (r[idx] ?? "").trim() : "";
      }))
      .filter((vals) => fields.every((f, i) => !f.required || vals[i] !== ""))
      .filter((vals) => {
        if (min == null || kind !== "tags") return true;
        // BOTH count columns, summed — the same figure the offset stores.
        const cell = (k: Field) => {
          const i = at(k);
          return i >= 0 && Number(map[k] ?? NONE) >= 0 ? vals[i] : "";
        };
        return countOf(cell) >= min;
      });

    // A NAME IS NORMALIZED LAST — after the split, or "shouyou, tiny giant"
    // would become one name with the separator inside it.
    const named = (vals: string[]) => vals.map((v, i) => {
      const f = fields[i];
      if (!v) return v;
      if (f.key === "meta" || (kind === "meta" && f.key === "name")) {
        return sanitizeLinkTagInput(v);
      }
      return NAME_FIELDS.has(f.key) ? normalizeTagName(v) : v;
    });

    // ONE CELL, SEVERAL VALUES. A file that lists a tag's aliases in one
    // field ("x, y, z") becomes one pair per alias — which is what the
    // importer already speaks, so nothing below this line learns anything
    // new. Expanded HERE rather than in `run` so the row count and the
    // preview show what will actually be imported, which is the only way to
    // check the separator is the right one.
    const multi = MULTI_FIELD[kind];
    const iMulti = multi ? at(multi) : -1;
    if (!splitOn || iMulti < 0) return mapped.map(named);
    const seen = new Set<string>();
    const out: string[][] = [];
    for (const vals of mapped) {
      for (const piece of vals[iMulti].split(splitOn)) {
        const one = piece.trim();
        if (!one) continue;
        const next = named([...vals.slice(0, iMulti), one,
                            ...vals.slice(iMulti + 1)]);
        // Several rows for one tag simply combine, and a pair the file says
        // twice is imported once.
        const key = next.join("\u0000").toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(next);
      }
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataRows, kind, minCount, splitOn, JSON.stringify(map)]);

  // WHAT WINS between the file and the library, for one field — ONE rule,
  // applied to every mapped column and to every record field, because "which
  // columns does this cover" must not be a per-field decision nobody can
  // see. `keep` fills a gap and leaves the rest alone, `update` prefers the
  // file where it says something, and `replace` IS the file: a column it
  // does not carry clears the value the library had.
  //
  // A PARENT is the one thing `replace` does not clear: these bodies say
  // "leave it alone" by omitting the id, and taking a place out of its parent
  // needs `clear_parent` — a different request, and not one a file that
  // simply has no parent column can be read as asking for.
  const pick = <T,>(fromFile: T | null | undefined,
                    inLibrary: T | null | undefined): T | null =>
    (existing === "replace" ? fromFile ?? null
      : existing === "update" ? fromFile ?? inLibrary ?? null
      : inLibrary ?? fromFile ?? null);
  const keep = (fromFile: string | undefined | null,
                inLibrary: string | undefined | null): string =>
    pick(fromFile || null, inLibrary || null) ?? "";

  // A ROW IS RETRIED, NOT LOST. Four rows are in flight at once, and four
  // concurrent writes against one SQLite library really do collide — a
  // deferred transaction upgrading to a write does not honour the busy
  // timeout, so the loser comes back 500 "database is locked". It is
  // transient by definition and the row's own writes are conditional, so the
  // whole row is simply run again. A REFUSAL (4xx) is not retried: a name the
  // API will not take is not going to become acceptable.
  const attempt = async (fn: () => Promise<unknown>): Promise<void> => {
    for (let i = 0; ; i += 1) {
      try { await fn(); return; } catch (e) {
        const status = e instanceof ApiError ? e.status : 0;
        if (i >= 3 || (status >= 400 && status < 500)) throw e;
        await new Promise((r) => setTimeout(r, 120 * (i + 1)));
      }
    }
  };

  const run = async () => {
    setBusy(true);
    setError("");
    abortRef.current = new AbortController();
    // The per-row progress counter — rows now run a few at a time (runBulk,
    // CSV_CHUNK in flight), so the count is a shared closure rather than a
    // loop variable.
    let done = 0;
    const step = (label: string) => {
      const n = ++done;
      if (n % 10 === 0 || n === entries.length) {
        setProgress(`${t(label)} ${n}/${entries.length}`);
      }
    };
    try {
      if (kind === "meta") {
        // Meta tags are name + comment and nothing else: one pass, creating
        // what is missing and setting a comment where the file gives one.
        const have = new Map((await api.linkTagRows())
          .map((r) => [r.name.toLowerCase(), r]));
        // Two rows naming the same missing tag can now run in one chunk, so
        // the creation is deduplicated through an in-flight map.
        const creating = new Map<string, Promise<unknown>>();
        const ensureMeta = (name: string) => {
          const key = name.toLowerCase();
          let p = creating.get(key);
          if (!p) {
            p = api.createLinkTag(name);
            creating.set(key, p);
          }
          return p;
        };
        await runBulk(entries, ([name, comment, description]) => attempt(async () => {
          step("Importing meta tags");
          const known = have.get(name.toLowerCase());
          if (!known) await ensureMeta(name);
          const patch: { comment?: string; description?: string } = {};
          if (comment && comment !== (known?.comment ?? "")) {
            patch.comment = comment;
          }
          if (description && description !== (known?.description ?? "")) {
            patch.description = description;
          }
          if (Object.keys(patch).length) {
            await api.updateLinkTag({ name, ...patch });
          }
        }), { chunk: CSV_CHUNK, signal: abortRef.current?.signal });
        onDone();
        onClose();
        return;
      }

      const byName = new Map(
        (await api.tags()).map((tg) => [tg.name.toLowerCase(), tg]));
      // One creation per name however many rows reference it in one chunk:
      // concurrent ensures of the same tag share the in-flight promise.
      const creating = new Map<string, Promise<TagRow>>();
      const createOnce = (key: string, make: () => Promise<TagRow>) => {
        let p = creating.get(key);
        if (!p) {
          p = make().then((created) => {
            byName.set(key, created);
            return created;
          });
          creating.set(key, p);
        }
        return p;
      };
      const ensure = (name: string): Promise<TagRow> => {
        const known = byName.get(name.toLowerCase());
        if (known) return Promise.resolve(known);
        return createOnce(name.toLowerCase(), () => api.createTag({ name }));
      };

      if (kind === "tags") {
        // WHAT A TAG IS BESIDES A TAG, where the file says so. The catalogs
        // are fetched once and only when a record column is actually mapped —
        // a file of plain tags asks for nothing extra — and a record created
        // for a tag goes back into the map, so a second row naming the same
        // tag updates it rather than trying to create it twice.
        const wants = (kindName: string) => fields.some((f, i) =>
          RECORD_FIELDS.some(([k, , kn]) => k === f.key && kn === kindName)
          && Number(map[f.key]) >= 0
          && entries.some((vals) => vals[i] !== ""));
        const subjectsBy = wants("subject")
          ? new Map((await api.subjects()).filter((s) => s.tag)
              .map((s) => [s.tag.toLowerCase(), s]))
          : null;
        const placesBy = wants("place")
          ? new Map((await api.places()).filter((pl) => pl.tag)
              .map((pl) => [pl.tag.toLowerCase(), pl]))
          : null;
        const eventsBy = wants("event")
          ? new Map((await api.events()).filter((ev) => ev.tag)
              .map((ev) => [ev.tag.toLowerCase(), ev]))
          : null;

        // PHASE 1 — THE TAG TABLE ITSELF, IN BATCHES. One request and one
        // transaction per two thousand rows, against the two requests and
        // two commits per row this replaces: on a 32k-row booru dump that
        // is the difference between seconds and minutes. The server applies
        // the same keep rule (`existing`) and logs the same events, and a
        // refused name comes back in its row rather than failing the batch.
        const failed = new Map<string, string>();
        {
          const batches = chunks(entries.map((vals) => {
            const row: Record<string, string> = {};
            fields.forEach((f, i) => { row[f.key] = vals[i]; });
            const out: { name: string; comment?: string;
                         count?: number } = { name: row.name };
            // MATCHING THE FILE SENDS THE EMPTIES TOO: a column it does not
            // map is a field it says is empty, and the batch can only clear
            // what the row actually carries.
            if (row.comment || existing === "replace") {
              out.comment = row.comment ?? "";
            }
            if (countTarget && (row.count ?? "").trim()) {
              out.count =
                Math.max(0, Math.trunc(countOf((k) => row[k] ?? "")));
            }
            return out;
          }), BULK_ROWS);
          let sent = 0;
          await runBulk(batches, (batch) => attempt(async () => {
            const res = await api.bulkUpsertTags({ rows: batch, existing,
                                                   meta_tags: marks,
                                                   ...(countTarget
                                                     ? { count_meta: countTarget,
                                                         count_mode: countMode }
                                                     : {}) });
            for (const r of res.rows) {
              if (r.error) failed.set(r.name.toLowerCase(), r.error);
            }
            sent += batch.length;
            setProgress(`${t("Creating tags")} ${Math.min(sent, entries.length)}/${entries.length}`);
          }), { chunk: 1, signal: abortRef.current?.signal });
        }
        // A CANCELLED RUN GOES NO FURTHER. Phase 2's `ensure` would create
        // the tags phase 1 never sent — bare, with no offset and no marks —
        // which is exactly the half-import a cancel is supposed to prevent.
        if (abortRef.current?.signal.aborted) { onDone(); return; }
        // PHASE 2 — what the batch endpoint does not speak: the subject,
        // place and event records. Most files have none, and then the import
        // is already done; with them, the refreshed catalog is walked row by
        // row exactly as before. (The file-wide meta marks ride in the batch
        // itself — marking per row here was one request per tag, which put
        // the minutes the batch removed straight back.)
        const needsRows = subjectsBy || placesBy || eventsBy;
        if (needsRows) {
        for (const tg2 of await api.tags()) byName.set(tg2.name.toLowerCase(), tg2);
        await runBulk(entries, (vals) => attempt(async () => {
          step("Importing records");
          const row: Record<string, string> = {};
          fields.forEach((f, i) => { row[f.key] = vals[i]; });
          const name = row.name;
          if (failed.has(name.toLowerCase())) return;
          await ensure(name);
          const key = name.toLowerCase();
          // A partial date the file may not carry: "" is "said nothing",
          // which must not be read as "clear it".
          const date = (v: string) => {
            const n = Number(v);
            return v.trim() && Number.isFinite(n) ? Math.trunc(n) : null;
          };

          if (subjectsBy && (row.subject || row.subject_since)) {
            const known = subjectsBy.get(key);
            const body = {
              display_name: keep(row.subject, known?.display_name) || name,
              since_date: pick(date(row.subject_since), known?.since_date),
            };
            const made = known
              ? await api.updateSubject(known.id, body)
              : await api.createSubject({ ...body, tag: name });
            const mine = made.find((s) => s.tag.toLowerCase() === key);
            if (mine) subjectsBy.set(key, mine);
          }

          const knownPlace = placesBy?.get(key);
          if (placesBy && (row.place_name || row.place_parent
                           || row.place_lat || row.place_lon)) {
            const known = knownPlace;
            // The parent by NAME — the row it points at may be created by a
            // later line of the same file, so it is resolved against what the
            // library holds once every row has been through.
            const parent = row.place_parent
              ? placesBy.get(row.place_parent.toLowerCase()) : undefined;
            // The coordinate PAIR moves together — a longitude without a
            // latitude is not a position, so half a pair is dropped.
            const num = (v: string) => {
              const n = Number(v);
              return v.trim() && Number.isFinite(n) ? n : null;
            };
            const lat = num(row.place_lat ?? "");
            const lon = num(row.place_lon ?? "");
            const body = {
              name: keep(row.place_name, known?.name),
              ...(parent && (existing !== "keep" || known?.parent_id == null)
                  ? { parent_id: parent.id } : {}),
              ...(lat != null && lon != null
                  && (existing !== "keep" || known?.lat == null)
                  ? { lat, lon } : {}),
            };
            const made = known
              ? await api.updatePlace(known.id, body)
              : await api.createPlace({ ...body, tag: name });
            const mine = made.find((pl) => pl.tag.toLowerCase() === key);
            if (mine) placesBy.set(key, mine);
          }

          if (eventsBy && (row.event || row.event_parent || row.event_start
                           || row.event_end)) {
            const known = eventsBy.get(key);
            const parentEvent = row.event_parent
              ? eventsBy.get(row.event_parent.toLowerCase()) : undefined;
            const body = {
              display_name: keep(row.event, known?.display_name) || name,
              ...(parentEvent && (existing !== "keep" || known?.parent_id == null)
                  ? { parent_id: parentEvent.id } : {}),
              start_date: pick(date(row.event_start), known?.start_date),
              end_date: pick(date(row.event_end), known?.end_date),
            };
            const made = known
              ? await api.updateEvent(known.id, body)
              : await api.createEvent({ ...body, tag: name });
            const mine = made.find((ev) => ev.tag.toLowerCase() === key);
            if (mine) eventsBy.set(key, mine);
          }
        }), { chunk: CSV_CHUNK, signal: abortRef.current?.signal });
        }
      } else if (kind === "tag_meta") {
        // The pairs ride the batch endpoint too, grouped by tag — per-row
        // this was two requests per pair, and its blanket catch swallowed a
        // transient "database is locked" the same as a refusal, so a busy
        // library quietly lost marks. A batch is one transaction: a refused
        // name comes back in its row, and nothing else is silent.
        const byTag = new Map<string, { name: string; meta_tags: string[];
                                        meta_counts?: Record<string, number> }>();
        for (const [name, meta, count] of entries) {
          const key = name.toLowerCase();
          let row = byTag.get(key);
          if (!row) { row = { name, meta_tags: [] }; byTag.set(key, row); }
          if (meta && !row.meta_tags.includes(meta)) row.meta_tags.push(meta);
          const n = Math.max(0, Math.trunc(countNum(count ?? "")));
          if (meta && n) (row.meta_counts ??= {})[meta] = n;
        }
        const rows = [...byTag.values()];
        let sent = 0;
        await runBulk(chunks(rows, BULK_ROWS), (batch) => attempt(async () => {
          await api.bulkUpsertTags({ rows: batch });
          sent += batch.length;
          setProgress(`${t("Marking tags")} ${Math.min(sent, rows.length)}/${rows.length}`);
        }), { chunk: 1, signal: abortRef.current?.signal });
      } else if (kind === "aliases") {
        await runBulk(entries, ([alias, target]) => attempt(async () => {
          step("Linking aliases");
          if (alias.toLowerCase() === target.toLowerCase()) return;
          try {
            await ensure(target);
            const known = byName.get(alias.toLowerCase());
            if (known) {
              // ADDITIVE: an alias the library already has and that already
              // points here is left alone, and nothing is ever un-aliased.
              if ((known.alias_of ?? "") !== target) {
                await api.updateTag(known.id, { alias_of: target });
              }
            } else {
              await createOnce(alias.toLowerCase(),
                () => api.createTag({ name: alias, alias_of: target }));
            }
          } catch {
            // A name the API refuses, or a tag that cannot be an alias
            // (it is one side of an implication) — skip the pair, keep going.
          }
        }), { chunk: CSV_CHUNK, signal: abortRef.current?.signal });
      } else {
        await runBulk(entries, ([name, target]) => attempt(async () => {
          step("Adding implications");
          if (name.toLowerCase() === target.toLowerCase()) return;
          const tg = await ensure(name);
          await ensure(target);
          if ((tg.implies ?? []).includes(target)) return;
          try {
            await api.addTagImplication(tg.id, target);
          } catch {
            // A loop or an alias on either side — the backend says which, and
            // one bad row must not abandon the rest of the file.
          }
        }), { chunk: CSV_CHUNK, signal: abortRef.current?.signal });
      }
      onDone();
    } catch (err) {
      setError(String(err).replace(/^Error:\s*/, ""));
      setBusy(false);
    }
  };

  const preview = entries.slice(0, 4);
  // One column per mapped field. The Tags shape has eighteen of them now, so
  // the preview SCROLLS sideways rather than squeezing each to nothing — it
  // is there to show that the mapping is right, which needs the values
  // readable.
  const grid = `repeat(${fields.length}, minmax(90px, 1fr))`;
  return (
    <Overlay error={error}
      icon="upload_file"
      title={meta ? t("Import meta tags from CSV") : t("Import tags from CSV")}
      subtitle={`${filename} · ${entries.length} ${t("rows")}`}
      width={720}
      onClose={close}
      footer={
        <>
          {busy && !error && (
            <div style={{ flex: 1, alignSelf: "center", fontSize: "var(--fs-2)", color: "var(--muted)", textAlign: "left" }}>
              {progress || t("Importing…")}
            </div>
          )}
          <Button variant="ghost" onClick={close}>{t("Cancel")}</Button>
          <Button variant="primary" icon="upload" onClick={() => void run()}
            disabled={busy || entries.length === 0}>
            {t("Import")} {entries.length}
          </Button>
        </>
      }
    >
      <div style={{ padding: 18 }}>
        {/* Which of the four files this is — the same choice the export offers,
            so what it writes comes back in. The Meta list offers exactly one
            shape, and a segmented control of one segment is a label drawn as
            a button, so the bar only renders with a choice in it. */}
        {kinds.length > 1 && (
          <KindTabs kinds={kinds} value={kind} onChange={setKind} />
        )}
        <KindStack kinds={kinds} value={kind} render={(k) => (<>
          <Panel>
            <Row label={t("First row is a header")}
              hint={t("Header names are used to label the columns below and to guess the mapping.")}>
              <input type="checkbox" checked={header}
                onChange={(e) => setHeader(e.target.checked)} />
            </Row>
            {/* THE PLAIN FIELDS, then the minimum, then the record kinds.
                The Tags shape has twenty rows and only four of them are about
                a tag as such; sixteen describe what a tag can ALSO be, and a
                file that has none of them — most files — should not have to
                be scrolled past. So each kind is one line, collapsed, saying
                how many of its columns are mapped. */}
            {IMPORT_FIELDS[k].filter((f) => !RECORD_KIND[f.key]
                                              && !COUNT_FIELDS.has(f.key))
              .map((f, i, arr) => (
              <Row key={f.key} label={t(f.label)} hint={t(f.hint)}
                last={k !== "tags" && !MULTI_FIELD[k] && i === arr.length - 1}>
                <ColumnSelect
                  value={map[f.key] ?? NONE}
                  columns={columns}
                  allowNone={!f.required}
                  onChange={(v) => setPicked((p) => ({ ...p, [f.key]: v }))}
                />
              </Row>
            ))}
            {/* HOW MANY VALUES A CELL HOLDS — a fact about the file, like the
                switches below, and offered only where a pair shape has a
                "many" side. Empty is one value per cell, which is what the
                export writes and the only reading that can hold a name with
                a comma in it. */}
            {MULTI_FIELD[k] && (
              <Row
                label={t("Split several values on")}
                last
                hint={t("Empty treats the cell as one value. Set it to \u201c,\u201d and a cell reading \u201cx, y, z\u201d becomes three rows against the same tag. Several rows for one tag combine, nothing already there is removed, and a pair the file says twice is imported once.")}>
                <input
                  value={splitOn}
                  placeholder={t("one value per cell")}
                  onChange={(e) => setSplitOn(e.target.value)}
                  style={{ ...inputStyle, width: 120, fontFamily: "var(--mono)" }}
                />
              </Row>
            )}
            {/* EACH RECORD KIND, the Count group's shape: the kind's OWN
                column — the one that names the thing — is mapped right on the
                group's row, and the chevron holds the rest of its fields. */}
            {k === "tags" && RECORD_KINDS.map(([kind]) => {
              const primary = IMPORT_FIELDS.tags.find(
                (f) => f.key === RECORD_PRIMARY[kind])!;
              const rest = IMPORT_FIELDS.tags.filter(
                (f) => RECORD_KIND[f.key] === kind && f.key !== primary.key);
              const open = !!expanded[kind];
              return (
                <React.Fragment key={kind}>
                  <Row
                    label={t(primary.label)}
                    hint={t(primary.hint)}
                    onClick={() => toggleGroup(kind)}
                    lead={
                      <span style={{ display: "flex", color: "var(--muted-3)" }}>
                        <Icon name={open ? "expand_more" : "chevron_right"} size={16} />
                      </span>
                    }
                  >
                    <span onClick={(e) => e.stopPropagation()}>
                      <ColumnSelect
                        value={map[primary.key] ?? NONE}
                        columns={columns}
                        allowNone
                        onChange={(v) => setPicked((p) => ({ ...p, [primary.key]: v }))}
                      />
                    </span>
                  </Row>
                  {open && rest.map((f) => (
                    <Row key={f.key} inset label={t(f.label)}>
                      <ColumnSelect
                        value={map[f.key] ?? NONE}
                        columns={columns}
                        allowNone
                        onChange={(v) => setPicked((p) => ({ ...p, [f.key]: v }))}
                      />
                    </Row>
                  ))}
                </React.Fragment>
              );
            })}
            {/* WHAT AN EXISTING TAG KEEPS — the last word, literally, and
                THREE answers rather than a switch. It was "Overwrite existing
                tags", on or off, which could say "fill the gaps" and "take
                the file's value" and had no way at all to say "make this tag
                match the file" — the case a re-import of a curated dump is
                usually for, and the one where a field the file no longer
                carries has to be cleared rather than left behind. */}
            {k === "tags" && (
              <Row
                last
                label={t("Where the library already says something")}
                hint={t("A tag the file does not name is untouched either way. Matching clears a comment or a record field the file has no column for.")}>
                <ModeSelect
                  value={existing}
                  onChange={(v) => setExisting(v as typeof existing)}
                  options={[
                    ["keep", t("Fill in the gaps only")],
                    ["update", t("Update what the file maps")],
                    ["replace", t("Match the file exactly")],
                  ]}
                />
              </Row>
            )}
          </Panel>

          {/* WHAT THE IMPORT ADDS BESIDES THE COLUMNS, in a section of its
              own — because neither of these answers to the switch above it.
              Overwrite is about what an existing tag's WORDS keep; the count
              has its own four-way question a row below, and a mark is only
              ever added. Reading them under that switch, they looked
              governed by it, and the count's first answer used to say so out
              loud ("Keep it, unless overwriting"). */}
          {k === "tags" && (<>
            <SectionHeading style={{ margin: "0 2px 8px" }}>
              {t("Counts and marks")}
            </SectionHeading>
            <Panel>
            {/* THE COUNT, AS ONE GROUP. The column itself is mapped right on
                the group's own row — a dropdown says "not imported" better
                than a summary label ever did — and the chevron holds what is
                dead weight until a column is picked: the minimum, and what
                the figure MEANS. The dropdown stops its clicks, or picking a
                column would also toggle the group.

                WITH NO COLUMN MAPPED THERE IS NOTHING TO OPEN, so the rows
                under it are not rendered and the chevron is not offered —
                every one of them is about a number the file is not giving
                us, and a minimum that filters nothing is worse than absent.
                The chevron keeps its WIDTH (`visibility`, the tag tree's
                Twist rule) or the label would step sideways as a column is
                picked; the group's remembered open state is left alone, so
                mapping a column shows what was open before. */}
            {k === "tags" && (() => {
              const countField = IMPORT_FIELDS.tags.find((f) => f.key === "count")!;
              const mapped = Number(map.count ?? NONE) >= 0;
              const open = mapped && !!expanded.count;
              return (
                <React.Fragment>
                  <Row
                    label={t(countField.label)}
                    hint={t(countField.hint)}
                    onClick={mapped ? () => toggleGroup("count") : undefined}
                    lead={
                      <span style={{ display: "flex", color: "var(--muted-3)",
                                     visibility: mapped ? "visible" : "hidden" }}>
                        <Icon name={open ? "expand_more" : "chevron_right"} size={16} />
                      </span>
                    }
                  >
                    <span onClick={(e) => e.stopPropagation()}>
                      <ColumnSelect
                        value={map.count ?? NONE}
                        columns={columns}
                        allowNone
                        onChange={(v) => setPicked((p) => ({ ...p, count: v }))}
                      />
                    </span>
                  </Row>
                  {open && (
                    <Row inset label={t("Skip rows under a count of")}>
                      <input
                        value={minCount}
                        inputMode="numeric"
                        placeholder={t("no minimum")}
                        onChange={(e) => { if (filterNumeric(e.target.value, { integer: true }) != null) setMinCount(e.target.value); }}
                        style={{ ...inputStyle, width: 120, fontFamily: "var(--mono)" }}
                      />
                    </Row>
                  )}
                  {open && (
                    <Row inset label={t("Store the count on")}
                      hint={t("A meta tag — usually the site the dump came from. Empty, the count only feeds the minimum above.")}>
                      <MarkField value={countMeta} onChange={setCountMeta}
                                 names={knownMeta ?? []} single
                                 placeholder={t("don't store")} />
                    </Row>
                  )}
                  {open && !!countTarget && (
                    <Row inset label={t("If an assignment has a count")}>
                      {/* The count's own conflict policy, not the overwrite
                          switch's: "which of two counts is right" has answers
                          of its own — a newer dump's number replaces, merged
                          sources keep the larger. FOUR answers, all of them
                          about the two numbers: the first entry used to be
                          "Keep it, unless overwriting", which is this list
                          deferring to a switch four rows down. */}
                      <ModeSelect
                        value={countMode}
                        onChange={(v) => setCountMode(v as typeof countMode)}
                        options={[
                          ["keep", t("Keep the number it has")],
                          ["replace", t("Replace it with the file's")],
                          ["min", t("Keep the smaller number")],
                          ["max", t("Keep the larger number")],
                        ]}
                      />
                    </Row>
                  )}
                </React.Fragment>
              );
            })()}
            {/* THE FACTS ABOUT THE WHOLE FILE, after every row that maps a
                column: "Mark every tag with" is one setting for the whole
                import — "these are all characters" — and its names are
                PICKED from the namespace rather than retyped, because a typo
                here is a new meta tag nobody meant to make, on every tag in
                the file. The field stays a comma-separated line (one
                setting, not a list to curate) and completes whichever
                fragment the caret is in. */}
            {k === "tags" && (
              <Row
                last
                label={t("Mark every tag with")}
                hint={t("Comma-separated meta tags put on every tag this file names, including tags the library already has. What the tag set says about a tag, said once for the whole import.")}>
                <MarkField value={markAll} onChange={setMarkAll}
                           names={knownMeta ?? []} placeholder={t("none")} />
              </Row>
            )}
            </Panel>
          </>)}

          <SectionHeading style={{ margin: "0 2px 8px" }}>
            {t("Preview")}
          </SectionHeading>
          <div style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: "var(--r-7)", overflow: "auto" }}>
            <div style={{ display: "grid", gridTemplateColumns: grid, gap: 8, padding: "8px 14px", fontSize: "var(--fs-1)", fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--muted-2)", borderBottom: "1px solid var(--border-soft)" }}>
              {IMPORT_FIELDS[k].map((f) => <div key={f.key}>{t(f.label)}</div>)}
            </div>
            {preview.map((vals, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: grid, gap: 8, padding: "7px 14px", fontSize: "var(--fs-3)", color: "var(--text-2)", borderBottom: i === preview.length - 1 ? "none" : "1px solid var(--border-soft)" }}>
                {vals.map((v, j) => (
                  <div key={j} style={{
                    fontFamily: j === 0 ? "var(--mono)" : undefined,
                    color: j === 0 ? undefined : "var(--muted)",
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>{v || "—"}</div>
                ))}
              </div>
            ))}
            {preview.length === 0 && (
              <div style={{ padding: "12px 14px", fontSize: "var(--fs-3)", color: "var(--muted-2)" }}>
                {t("No rows — check the columns above.")}
              </div>
            )}
          </div>
        </>)} />
      </div>
    </Overlay>
  );
}

// The Tags file describes tags, not the relations between them: aliases and
// implications are files of their own (one pair per row), so they are not also
// squeezed into a cell here — which is what a per-cell separator would be for.
const EXPORT_COLUMNS = [
  ["name", "Tag"],
  ["comment", "Comment"],
  ["positive", "Positive count"],
  // The part of the positive count nobody assigned — implied, inherited or
  // carried by a sequence. Its own column, as it is its own fact.
  ["implicit", "Implicit count"],
  ["negative", "Negative count"],
  // What the tag is BESIDES a tag — field by field, so the file says what the
  // record says and the import can read it back. See `RECORD_FIELDS`. Not one
  // column per KIND: nothing stops a tag being two of them, and one column
  // would have to pick.
  ...RECORD_FIELDS.map(([k, label]) => [k, label] as const),
] as const;
// The meta namespace has no counts of items, but one count per CARRIER — and
// those are exactly what its list shows, so the file can say them too.
const META_EXPORT_COLUMNS = [
  ["name", "Meta tag"],
  ["comment", "Comment"],
  ["description", "Description"],
  ["links", "Links"],
  ["captions", "Captions"],
  ["tag_groups", "Tag groups"],
  ["tags", "Tags"],
] as const;
type ExportCol = typeof EXPORT_COLUMNS[number][0]
  | typeof META_EXPORT_COLUMNS[number][0];

/** What each tag is besides a tag, keyed by tag name — the ROWS the Tags tab
 *  already has loaded, not lines of text made out of them.
 *
 *  They used to arrive pre-formatted, one summary line per kind, which is
 *  exactly what could not be read back: a formatted address has no parser
 *  (`places/formats.ts` writes one and nothing reads one), so an export of it
 *  was a dead end. The overlay takes the fields and writes a column each. */
export interface TagRecords {
  subjects: Map<string, SubjectRow>;
  places: Map<string, PlaceRow>;
  events: Map<string, EventRow>;
  /** Tag name → the identity tag of the place it is INSIDE, and the same for
   *  events. A parent is a row id in the API and a NAME in a file: an id
   *  means nothing in another library. */
  placeParentTag?: Map<string, string>;
  eventParentTag?: Map<string, string>;
}

// The relation files have a fixed shape — two columns, both of them the fact
// the row states — so their columns are listed but not offered as choices.
const FIXED_COLUMNS: Record<"aliases" | "implications" | "tag_meta",
                            readonly string[]> = {
  aliases: ["Alias", "Tag"],
  implications: ["Tag", "Implies"],
  tag_meta: ["Tag", "Meta tag", "Count"],
};

// The column order is a setting, not a per-dialog whim: someone who wants the
// counts first wants them first every time. WHICH columns are ticked is the
// same kind of thing and is remembered beside it. The two namespaces keep
// their own, since they share no columns beyond the comment.
function orderKey(meta: boolean) {
  return meta ? "mc.metaTagExportColumns" : "mc.tagExportColumns";
}

function pickedKey(meta: boolean) {
  return meta ? "mc.metaTagExportPicked" : "mc.tagExportPicked";
}

function loadOrder(keys: ExportCol[], meta: boolean): ExportCol[] {
  try {
    const raw = JSON.parse(storage.get(orderKey(meta)) || "[]");
    if (!Array.isArray(raw)) return [...keys];
    // Keep what is still a column, in the stored order, then append whatever
    // the app has gained since — a stored order must never lose a column.
    const kept = raw.filter((k): k is ExportCol => keys.includes(k));
    return [...kept, ...keys.filter((k) => !kept.includes(k))];
  } catch {
    return [...keys];
  }
}

/**
 * Which columns are ticked, remembered.
 *
 * EVERYTHING by default, and that is a change: a record column used to start
 * unticked unless some tag already had a value in it, which meant a library
 * with no places exported without the place columns — and left "Place
 * address" unticked even where it was wanted, because no tag happened to
 * carry one yet. Ticking a column you can see is one click;
 * discovering months later that an export quietly left a field out is not.
 * The count in the footer says how many are on either way.
 *
 * A column the app has GAINED since the choice was stored is on, for the same
 * reason: what was stored is what somebody turned OFF, and they cannot have
 * turned off a column that did not exist.
 */
function loadPicked(keys: ExportCol[], meta: boolean): Record<string, boolean> {
  let off = new Set<string>();
  try {
    const raw = JSON.parse(storage.get(pickedKey(meta)) || "[]");
    if (Array.isArray(raw)) off = new Set(raw.map(String));
  } catch { /* a first run, or a torn value: everything is on */ }
  return Object.fromEntries(keys.map((k) => [k, !off.has(k)]));
}

/** Which tags the Tags file carries: everything, or one kind of record. */
export type ExportFilter = "all" | "subjects" | "places" | "events";

const EXPORT_FILTERS: readonly [ExportFilter, string][] = [
  ["all", "All tags"], ["subjects", "Subjects"],
  ["places", "Places"], ["events", "Events"],
];

export function TagCsvExportOverlay({ tags, metaTags, records, initialFilter,
                                      onClose }: {
  tags: TagRow[];
  metaTags?: LinkTagRow[];
  /** What each tag is besides a tag, by tag name. */
  records?: TagRecords;
  /** Pre-set kind filter — the record lists open the dialog on their own kind. */
  initialFilter?: ExportFilter;
  onClose: () => void;
}) {
  const t = useT();
  // Exactly one of the two namespaces is on offer at a time (the list you
  // pressed Export in), so the configurable columns are that one's.
  const meta = !!metaTags;
  const columnSet = meta ? META_EXPORT_COLUMNS : EXPORT_COLUMNS;
  const columnLabel = useMemo(
    () => new Map<string, string>(columnSet.map(([k, l]) => [k, l])), [columnSet]);
  const columnKeys = useMemo(
    () => columnSet.map(([k]) => k) as ExportCol[], [columnSet]);
  // WHICH COLUMNS, remembered between exports and everything by default (see
  // `loadPicked`). It used to be derived from the library's own contents — a
  // record column nobody had anything in started unticked — which read as the
  // dialog second-guessing the choice, and left "Place address" off for a
  // library that simply had not filled it in yet.
  const [cols, setCols] = useState<Record<string, boolean>>(
    () => loadPicked(columnKeys, meta));
  useEffect(() => {
    // The OFF list is what is stored: a column added later is then on by
    // default rather than silently missing from a stored "on" list.
    try {
      storage.set(pickedKey(meta), JSON.stringify(
        columnKeys.filter((k) => !cols[k])));
    } catch { /* ignore */ }
  }, [cols, columnKeys, meta]);
  // The columns' order is the file's column order, so it is dragged into shape
  // here rather than fixed in code — and remembered.
  const [order, setOrder] = useState<ExportCol[]>(() => loadOrder(columnKeys, meta));
  useEffect(() => {
    try { storage.set(orderKey(meta), JSON.stringify(order)); }
    catch { /* ignore */ }
  }, [order, meta]);
  // WHAT IS BEING DRAGGED: one column, or a whole record group. A group is a
  // block of columns that moves as one — it is one line on screen, so
  // dragging it has to move the thing that line stands for.
  //
  // It lives in a ref as well as in state: state is what greys the row out,
  // the ref is what the drop handlers read — a handler captured before the
  // drag began would otherwise see no drag at all.
  type Drag = { col: ExportCol } | { group: string };
  const [dragging, setDragging] = useState<Drag | null>(null);
  const dragRef = React.useRef<Drag | null>(null);
  const beginDrag = (d: Drag) => { dragRef.current = d; setDragging(d); };
  const endDrag = () => { dragRef.current = null; setDragging(null); };
  /** The columns a drag is carrying, in the file's own order. */
  const dragKeys = (d: Drag, cur: ExportCol[]): ExportCol[] =>
    "col" in d ? [d.col]
      : cur.filter((k) => RECORD_KIND[k as string] === d.group);
  /**
   * Move a BLOCK of columns so it lands beside `at`.
   *
   * One rule for both kinds, and the direction matters: dragged downward the
   * block goes AFTER the row it is over, upward BEFORE it — which is what
   * makes a drag reach both ends of the list. (A single column is a block of
   * one, so it takes the same path rather than a second one to keep in step.)
   */
  /** The first of a record group's columns, which is where the group's line
   *  sits in the file's order. */
  const firstOf = (kind: string) =>
    order.find((k) => RECORD_KIND[k as string] === kind);
  /** One row was dragged over. */
  const dropOn = (at: ExportCol) => {
    const d = dragRef.current;
    if (!d) return;
    const keys = dragKeys(d, order);
    // A GROUP NEVER LANDS INSIDE ANOTHER GROUP: aimed at one of its rows it
    // goes beside the group as a whole, or the two would interleave and the
    // list would show one group's header over the other's columns.
    const kind = RECORD_KIND[at as string];
    const target = ("group" in d && kind && kind !== d.group
                    ? firstOf(kind) : at) ?? at;
    if (!keys.includes(target)) moveBlock(keys, target);
  };
  /** The drag half of a row. The WHOLE row is the handle, so the browser's
   *  drag image is the whole row — dragging the little grip alone made a
   *  picture of the grip follow the cursor while the row sat in the list. */
  const dragProps = (d: Drag, at: ExportCol, active: boolean) => ({
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      beginDrag(d);
      e.dataTransfer.effectAllowed = "move";
    },
    onDragEnd: endDrag,
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); dropOn(at); },
    // The row is already in its new place (the list reorders as you pass each
    // row) and its picture is under the cursor — so what stays behind is a
    // GAP: the space it will drop into, outlined, the row faded inside it.
    style: active ? {
      borderRadius: "var(--r-4)", borderBottom: "1px solid transparent",
      background: "var(--accent-dim)",
      outline: "1px dashed var(--accent)", outlineOffset: -1,
      opacity: 0.45,
    } : { transition: "transform .12s ease" },
  });
  const grip = (active: boolean) => (
    <span
      title={t("Drag to reorder the columns")}
      style={{
        display: "flex", cursor: active ? "grabbing" : "grab",
        color: active ? "var(--accent)" : "var(--muted-3)",
      }}
    >
      <Icon name="drag_indicator" size={15} />
    </span>
  );
  const moveBlock = (keys: ExportCol[], at: ExportCol) =>
    setOrder((cur) => reorder(cur, keys, at));
  // WHAT A TAG IS BESIDES A TAG, folded away. Sixteen record columns after
  // five plain ones is a list nobody reads to the end, and most libraries use
  // a handful of them — so each kind is one line, collapsed, and opens to its
  // own fields. Its tick is the three states of the fields inside it.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const toggleGroup = (g: string) =>
    setExpanded((e) => ({ ...e, [g]: !e[g] }));
  const setGroup = (g: string, on: boolean) => setCols((cc) => {
    const next = { ...cc };
    for (const [k2, , kind2] of RECORD_FIELDS) if (kind2 === g) next[k2] = on;
    return next;
  });
  const GROUP_LABEL: Record<string, string> = {
    subject: "Subject", place: "Place", event: "Event",
  };
  /** The list as it is SHOWN: the plain columns in the file's own order, then
   *  one line per record kind. The order the file gets is still `order` —
   *  this only decides what is on screen. */
  const rendered = useMemo(() => {
    const recordOf = new Map(RECORD_FIELDS.map(([k2, , kind2]) => [k2, kind2]));
    const out: { key?: string; group?: {
      kind: string; label: string; keys: ExportCol[];
      state: "on" | "off" | "some"; on: number } }[] = [];
    const done = new Set<string>();
    for (const c of order) {
      const g = recordOf.get(c as never);
      if (!g) { out.push({ key: c }); continue; }
      if (done.has(g)) continue;
      done.add(g);
      const keys = order.filter((x) => recordOf.get(x as never) === g);
      const on = keys.filter((x) => cols[x]).length;
      out.push({ group: {
        kind: g, label: GROUP_LABEL[g] ?? g, keys, on,
        state: on === 0 ? "off" : on === keys.length ? "on" : "some",
      } });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order, cols]);

  // Which relation this file is about — the same four shapes the import reads.
  const [kind, setKind] = useState<CsvKind>(metaTags ? "meta" : "tags");
  const kinds = offeredKinds(!!metaTags);

  // WHICH TAGS the Tags file carries — everything, or one kind of record.
  // The record lists' Export buttons open the dialog pre-set to their kind,
  // and the choice stays editable here: it narrows the file, not the dialog.
  const [filter, setFilter] = useState<ExportFilter>(initialFilter ?? "all");
  const isKind = (name: string): boolean =>
    filter === "all" ? true
    : filter === "subjects" ? !!records?.subjects.has(name)
    : filter === "places" ? !!records?.places.has(name)
    : !!records?.events.has(name);
  // An alias has no row of its own in the Tags file — it is a row in the
  // Aliases file, pointing at the tag it stands for.
  const rows = useMemo(() => tags.filter((tg) => !tg.alias_of && isKind(tg.name)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tags, filter, records]);

  const active = order.filter((k) => cols[k]);
  // One row per PAIR for the relation files, so each line is one fact and a
  // diff of two exports reads as added/removed relations.
  const aliasPairs = useMemo(
    () => tags.filter((tg) => tg.alias_of)
      .map((tg) => [tg.name, tg.alias_of as string]),
    [tags]);
  const impliesPairs = useMemo(
    () => tags.flatMap((tg) => (tg.implies ?? []).map((n) => [tg.name, n])),
    [tags]);
  // What the tag set says about each tag, likewise one row per fact. An
  // ALIAS is included where it carries one: it is a tag row like any other,
  // unlike the Tags file, where an alias belongs in the Aliases file instead.
  // The COUNT rides the pair — pictures the tag has where that meta tag
  // says — so the assignments file round-trips it (the import maps a Count
  // column back onto the assignment). Blank when uncounted.
  const metaPairs = useMemo(
    () => tags.flatMap((tg) => (tg.meta_tags ?? []).map((n) =>
      [tg.name, n, tg.meta_counts?.[n] ?? ""])),
    [tags]);

  const run = () => {
    let out: (string | number)[][];
    let name: string;
    if (kind === "meta") {
      out = [active.map((k) => t(columnLabel.get(k) as string))];
      for (const m of metaTags ?? []) {
        out.push(active.map((k) => {
          switch (k) {
            case "comment": return m.comment ?? "";
            case "description": return m.description ?? "";
            case "links": return m.links;
            case "captions": return m.captions;
            case "tag_groups": return m.tag_groups;
            default: return m.name;
          }
        }));
      }
      name = "meta-tags";
    } else if (kind === "aliases") {
      out = [[t("Alias"), t("Tag")], ...aliasPairs];
      name = "tag-aliases";
    } else if (kind === "implications") {
      out = [[t("Tag"), t("Implies")], ...impliesPairs];
      name = "tag-implications";
    } else if (kind === "tag_meta") {
      out = [[t("Tag"), t("Meta tag"), t("Count")], ...metaPairs];
      name = "tag-meta-tags";
    } else {
      out = [active.map((k) => t(columnLabel.get(k) as string))];
      for (const tg of rows) {
        out.push(active.map((k) => {
          switch (k) {
            case "comment": return tg.comment ?? "";
            case "positive": return tagCount(tg);
            case "implicit": return tagCount(tg, "implicit");
            case "negative": return tagCount(tg, "negative");
            case "name": return tg.name;
            default: return recordValues(tg.name, records)[k] ?? "";
          }
        }));
      }
      name = "tags";
    }
    const stamp = new Date().toISOString().slice(0, 10);
    downloadText(`${name}-${stamp}.csv`, toCsv(out));
    onClose();
  };

  return (
    <Overlay
      icon="download"
      title={metaTags ? t("Export meta tags as CSV") : t("Export tags as CSV")}
      subtitle={kind === "meta"
        ? `${(metaTags ?? []).length} ${t("meta tags")}`
        : kind === "aliases"
        ? `${aliasPairs.length} ${t("aliases")}`
        : kind === "implications"
        ? `${impliesPairs.length} ${t("implications")}`
        : kind === "tag_meta"
        ? `${metaPairs.length} ${t("meta tag assignments")}`
        : `${rows.length} ${t("tags")}`}
      width={520}
      onClose={onClose}
      footer={
        <>
          {/* Only once the order HAS been dragged off the default — a reset
              for an untouched list is a button that does nothing. At the
              footer's LEFT edge (marginRight: auto in a flex-end row), apart
              from Cancel/Export: it acts on the list, not on the dialog. */}
          {(kind === "tags" || kind === "meta")
            && !(order.length === columnKeys.length
                 && order.every((c, i) => c === columnKeys[i])) && (
            <span style={{ marginRight: "auto" }}>
              <Button variant="ghost" onClick={() => setOrder([...columnKeys])}>
                {t("Reset order")}
              </Button>
            </span>
          )}
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" icon="download" onClick={run}
            disabled={(kind === "tags" || kind === "meta") && active.length === 0}>
            {t("Export")}
          </Button>
        </>
      }
    >
      <div style={{ padding: 18 }}>
        {kinds.length > 1 && (
          <KindTabs kinds={kinds} value={kind} onChange={setKind} />
        )}
        <KindStack kinds={kinds} value={kind} render={(k) => (<>
          {/* WHICH TAGS, before which columns: the Tags file can carry the
              whole tag set or one kind of record — the record lists'
              Export buttons open the dialog with their kind pre-set. */}
          {k === "tags" && (
            <Panel>
              <Row last label={t("Which tags")}>
                <Select value={filter} minWidth={190}
                        onChange={(v) => setFilter(v as ExportFilter)}>
                  {EXPORT_FILTERS.map(([v, l]) => (
                    <option key={v} value={v}>{t(l)}</option>
                  ))}
                </Select>
              </Row>
            </Panel>
          )}
          {/* Every kind lists its columns; the two TABLE files (tags, meta
              tags) let you choose and order them, since a relation row IS its
              two columns and has nothing to choose. */}
          <Panel>
            {k === "tags" || k === "meta"
              ? rendered.map((entry, i) => {
                  if (entry.group) {
                    const g = entry.group;
                    const open = !!expanded[g.kind];
                    const held = dragging && "group" in dragging
                      && dragging.group === g.kind;
                    return (
                      <React.Fragment key={`g-${g.kind}`}>
                        <Row
                          compact
                          label={t(g.label)}
                          last={!open && i === rendered.length - 1}
                          onClick={() => toggleGroup(g.kind)}
                          // A GROUP DRAGS AS ONE. It is one line on screen
                          // standing for up to nine columns, so dragging it
                          // has to move all of them — and its own rows drag
                          // inside it, which is the finer order the file gets.
                          dragProps={dragProps({ group: g.kind },
                                               g.keys[0], !!held)}
                          lead={
                            <span style={{ display: "flex", alignItems: "center",
                                           gap: 2 }}>
                              {grip(!!held)}
                              <span style={{ display: "flex",
                                             color: "var(--muted-3)" }}>
                                <Icon name={open ? "expand_more" : "chevron_right"}
                                      size={16} />
                              </span>
                            </span>
                          }
                        >
                          <span style={{ display: "flex", alignItems: "center",
                                         gap: 10 }}>
                            {/* HOW MANY of the group's columns are on — the
                                mixed tick says "some", and this says which. */}
                            {g.state === "some" && (
                              <span style={{ fontFamily: "var(--mono)",
                                             fontSize: "var(--fs-1)",
                                             color: "var(--muted-2)" }}>
                                {g.on} / {g.keys.length}
                              </span>
                            )}
                            <span
                              onClick={(e) => { e.stopPropagation();
                                                setGroup(g.kind, g.state !== "on"); }}
                              style={{ display: "flex", cursor: "pointer" }}
                            >
                              <TriCheckbox state={g.state} />
                            </span>
                          </span>
                        </Row>
                        {open && g.keys.map((c, j) => {
                          const on = dragging && "col" in dragging
                            && dragging.col === c;
                          return (
                          <Row
                            key={c}
                            inset
                            label={t(columnLabel.get(c) as string)}
                            last={i === rendered.length - 1
                                  && j === g.keys.length - 1}
                            onClick={() => setCols((cc) => ({ ...cc, [c]: !cc[c] }))}
                            dragProps={dragProps({ col: c }, c, !!on)}
                            lead={grip(!!on)}
                          >
                            <input type="checkbox" checked={cols[c]} readOnly
                                   tabIndex={-1} style={{ pointerEvents: "none" }} />
                          </Row>
                          );
                        })}
                      </React.Fragment>
                    );
                  }
                  const c = entry.key as ExportCol;
                  const dragged = !!dragging && "col" in dragging
                    && dragging.col === c;
                  return (
                    <Row
                      compact
                      key={c}
                      label={t(columnLabel.get(c) as string)}
                      last={i === order.length - 1}
                      onClick={() => setCols((cc) => ({ ...cc, [c]: !cc[c] }))}
                      dragProps={dragProps({ col: c }, c, dragged)}
                      lead={grip(dragged)}
                    >
                      <input type="checkbox" checked={cols[c]} readOnly tabIndex={-1}
                        style={{ pointerEvents: "none" }} />
                    </Row>
                  );
                })
              : FIXED_COLUMNS[k].map((label, i) => (
                  <Row compact key={label} label={t(label)}
                       last={i === FIXED_COLUMNS[k].length - 1}>
                    <input type="checkbox" checked disabled />
                  </Row>
                ))}
          </Panel>
        </>)} />
      </div>
    </Overlay>
  );
}

/** Hidden file input + the two toolbar buttons, wired to the overlays. */
export function TagCsvButtons({ tags, metaTags, records, exportFilter,
                                buttonStyle, onImported, importOpenRef }: {
  tags: TagRow[];
  /** Present in the Tags tab's Meta mode: meta tags are their own namespace
   *  (a name, a comment and a count per carrier — no aliases, no
   *  implications), so they import and export as their own file. */
  metaTags?: LinkTagRow[];
  records?: TagRecords;
  /** What the export dialog opens narrowed to — the record lists pass their
   *  own kind, so Export on the Places list means the places. */
  exportFilter?: ExportFilter;
  buttonStyle: React.CSSProperties;
  onImported: () => void;
  /** Given, the Import BUTTON is not rendered — the toolbar's Add menu owns
   *  the entry and calls what this ref holds. The file input, the parsing
   *  and the overlay all stay here, where the export half already lives. */
  importOpenRef?: React.MutableRefObject<(() => void) | null>;
}) {
  const t = useT();
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [imp, setImp] = useState<null | { rows: string[][]; filename: string }>(null);
  const [exp, setExp] = useState(false);
  // Refreshed every render, so the menu always calls the live picker.
  if (importOpenRef) importOpenRef.current = () => fileRef.current?.click();

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept=".csv,text/csv,text/plain"
        style={{ display: "none" }}
        onChange={async (e) => {
          const f = e.target.files?.[0];
          e.target.value = ""; // allow re-picking the same file
          if (!f) return;
          const text = await f.text();
          const rows = parseCsv(text);
          if (rows.length > 0) setImp({ rows, filename: f.name });
        }}
      />
      {!importOpenRef && (
        <button onClick={() => fileRef.current?.click()}
          title={t("Import tags from a CSV file")} style={buttonStyle}>
          <Icon name="upload_file" size={16} /> {t("Import")}
        </button>
      )}
      <button onClick={() => setExp(true)} title={t("Export all tags as a CSV file")} style={buttonStyle}>
        <Icon name="download" size={16} /> {t("Export")}
      </button>
      {imp && (
        <TagCsvImportOverlay
          meta={!!metaTags}
          rows={imp.rows}
          filename={imp.filename}
          onClose={() => setImp(null)}
          onDone={() => { setImp(null); onImported(); }}
        />
      )}
      {exp && <TagCsvExportOverlay tags={tags} metaTags={metaTags}
                records={records} initialFilter={exportFilter}
                onClose={() => setExp(false)} />}
    </>
  );
}
