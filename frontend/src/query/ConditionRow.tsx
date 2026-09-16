/** One editable condition row: a kind dropdown, kind-specific fields, and the
 *  segmented action control. Tag / Group / Link / Caption / Metadata. */
import React, { useEffect, useState } from "react";
import { filterNumeric } from "../shared/useNumericText";
import { useQuery } from "@tanstack/react-query";
import { api, MetadataCatalogEntry, PlaceRow } from "../shared/api";
import { CapCond, CapMode, Cond, EventCond, GrpCond, LinkCond, LinkDir,
         LinkTagRef, MetaCond, MetaType, PlaceCond, SubjCond, TagCond,
         SimilarCond, TakenCond, ValueCond, metaValueText,
         numTolerance } from "./tree";
import { parseValue } from "../shared/tagvalue";
import { tagFieldInput, tagFieldName } from "../shared/tagName";
import { formatTaken, parseTaken } from "./subjects/taken";
import { blankCond, condKind, type CondKind } from "./edit";
import { AcOption, Autocomplete, RowActions, fieldWrap, inputStyle, selectStyle } from "./builderParts";
import { Icon } from "../shared/Icon";
import { useDateFormatters } from "../shared/time";
import { hasMetaEnum, metaEnumOptions } from "../shared/metaEnums";
import { useT, type TFn } from "../shared/i18n";
import { placeValues } from "./places/formats";

const NUM_OPS: [string, string][] = [[">=", "≥"], ["<=", "≤"], [">", ">"], ["<", "<"], ["=", "="], ["!=", "≠"]];
// The word tables take the translator: every label is a `tr("…")` literal,
// which is what the catalog harvest reads, and a table built once in English
// would be the one thing on this row every language could not reach.
const TEXT_OPS = (tr: TFn): [string, string][] =>
  [["=", tr("is")], ["!=", tr("is not")], ["~", tr("contains")], ["!~", tr("doesn’t contain")]];
const DATE_OPS = (tr: TFn): [string, string][] =>
  [["=", tr("is on")], ["<=", tr("is on or before")], [">=", tr("is on or after")]];

// Split a stored date value into the ISO `YYYY-MM-DD` date and `HH:MM` time the
// native pickers use. Accepts separated strings (`2026-07-12`,
// `2026-07-12T22:12:16`) and bare digit forms; `time` is empty at day precision.
function splitDateValue(v: number | string): { date: string; time: string } {
  const s = String(v).replace(/\D/g, "");
  if (s.length < 8) return { date: "", time: "" };
  const p = s.padEnd(14, "0");
  const date = `${p.slice(0, 4)}-${p.slice(4, 6)}-${p.slice(6, 8)}`;
  const time = s.length > 8 ? `${p.slice(8, 10)}:${p.slice(10, 12)}` : "";
  return { date, time };
}

export function ConditionRow({
  node, catalog, tagOptions = [], fetchTagOptions, linkTagOptions,
  groupOptions, subjectOptions = [],
  eventOptions = [], places = [],
  canRemove = true,
  onChange, onRemove, onAddRow, onAddGroup,
}: {
  node: Cond;
  catalog: MetadataCatalogEntry[];
  /** Tag-name completions: a static catalog, or (preferred) a typing-driven
   *  fetcher — the builder passes the latter so completing a tag never means
   *  holding the whole catalog. */
  tagOptions?: AcOption[];
  fetchTagOptions?: (q: string) => Promise<AcOption[]>;
  linkTagOptions: AcOption[];
  groupOptions: AcOption[];
  /** Subjects, keyed by their identity tag (what the item actually carries). */
  subjectOptions?: AcOption[];
  /** Events, likewise keyed by their identity tag. */
  eventOptions?: AcOption[];
  /** The library's places — the only suggestion source for a place value,
   *  since there is no address database here. */
  places?: PlaceRow[];
  canRemove?: boolean;
  onChange: (next: Cond) => void;
  onRemove: () => void;
  onAddRow: () => void;
  onAddGroup: () => void;
}) {
  // Keyed on the DROPDOWN entry, not on `node.type`: Caption and Instruction
  // are one condition type with two kinds, so comparing types would make
  // switching between them a no-op.
  const kindNow = condKind(node);
  const tr = useT();
  const setKind = (kind: CondKind) => {
    if (kind !== kindNow) onChange(blankCond(kind));
  };

  return (
    <div style={{
      position: "relative", display: "flex", alignItems: "center", flexWrap: "nowrap",
      gap: 8, padding: "4px 0", minHeight: 30,
    }}>
      <select value={kindNow} onChange={(e) => setKind(e.target.value as CondKind)} style={selectStyle}>
        <option value="tag">{tr("Tag")}</option>
        {/* Beside Tag, not at the end: both ask about the item's tags, and
            a kind filed eleven rows from its sibling is one nobody finds. */}
        <option value="value">{tr("Tag value")}</option>
        <option value="ingroup">{tr("Group")}</option>
        <option value="subject">{tr("Subject")}</option>
        <option value="place">{tr("Place")}</option>
        <option value="event">{tr("Event")}</option>
        <option value="taken">{tr("Taken")}</option>
        <option value="similar">{tr("Colours like")}</option>
        <option value="link">{tr("Link")}</option>
        <option value="caption">{tr("Caption")}</option>
        <option value="instruction">{tr("Instruction")}</option>
        <option value="meta">{tr("Metadata")}</option>
      </select>

      {node.type === "tag" && <TagFields node={node} options={tagOptions}
        fetchOptions={fetchTagOptions} metaOptions={linkTagOptions}
        onChange={onChange} />}
      {node.type === "ingroup" && <GrpFields node={node} options={groupOptions} onChange={onChange} />}
      {node.type === "subject" && <SubjFields node={node} options={subjectOptions} onChange={onChange} />}
      {node.type === "place" && <PlaceFields node={node} places={places} onChange={onChange} />}
      {node.type === "event" && <EventFields node={node} options={eventOptions} onChange={onChange} />}
      {node.type === "taken" && <TakenFields node={node} onChange={onChange} />}
      {node.type === "similar" && <SimilarFields node={node} onChange={onChange} />}
      {node.type === "link" && <LinkFields node={node} options={linkTagOptions} onChange={onChange} />}
      {node.type === "caption" && <CaptionFields node={node} options={linkTagOptions} onChange={onChange} />}
      {node.type === "meta" && <MetaFields node={node} catalog={catalog} onChange={onChange} />}
      {node.type === "value" && <ValueFields node={node}
        onChange={onChange} />}

      <RowActions canRemove={canRemove} onRemove={onRemove} onAddGroup={onAddGroup} onAddRow={onAddRow} />
    </div>
  );
}

// ---- Tag -------------------------------------------------------------------

/** The four things this row can ask, as one dropdown.
 *
 *  "has meta" is the same question one level up: not "does it carry THIS
 *  tag" but "does it carry a tag the tag set marks this way". It stays in
 *  the Tag row rather than becoming a condition of its own because everything
 *  else about it — the positive/negative toggle, implications, group grants —
 *  is what a tag condition already means. */
const TAG_MODES = (tr: TFn): [string, string][] => [
  ["has", tr("has")], ["hasnot", tr("has not")],
  ["hasmeta", tr("has meta")], ["hasnotmeta", tr("has not meta")],
];

function TagFields({ node, options, fetchOptions, metaOptions, onChange }: {
  node: TagCond; options: AcOption[];
  fetchOptions?: (q: string) => Promise<AcOption[]>;
  /** The meta-tag namespace, for the "has meta" capsules. */
  metaOptions: AcOption[];
  onChange: (n: Cond) => void;
}) {
  // WHICH form the row is in. Read off the node — meta tags present is what
  // the serializer looks at — but STICKY while the capsule list is empty, or
  // picking "has meta" would snap back to the name field before the first
  // capsule could be added.
  const [wantsMeta, setWantsMeta] = React.useState(!!node.meta_tags?.length);
  const tr = useT();
  const meta = wantsMeta || !!node.meta_tags?.length;
  const green = node.sign === "pos";
  // The positive/negative toggle matches the sidebar tag rows: a 16×16 clickable
  // area with a 9×9 rounded dot, sitting inside the tag field (one border).
  const toggle = (
    <span
      className="tag-state-toggle"
      onClick={() => onChange({ ...node, sign: green ? "neg" : "pos" })}
      title={green ? tr("Positive assignment — click for negative") : tr("Negative assignment — click for positive")}
      style={{ flex: "0 0 16px", width: 16, height: 16, display: "flex", alignItems: "center",
        justifyContent: "center", borderRadius: "var(--r-1)", cursor: "pointer", marginLeft: -3 }}
    >
      <span style={{ width: 9, height: 9, borderRadius: 2, background: green ? "var(--green)" : "var(--red)" }} />
    </span>
  );
  return (
    <>
      <select
        value={meta ? (node.have ? "hasmeta" : "hasnotmeta")
                    : (node.have ? "has" : "hasnot")}
        onChange={(e) => {
          const v = e.target.value;
          const wantMeta = v.endsWith("meta");
          setWantsMeta(wantMeta);
          // Switching form CLEARS the other half: a name left behind on a
          // meta condition (or capsules on a named one) is invisible in the
          // row and decides what the query means.
          onChange({
            ...node, have: v === "has" || v === "hasmeta",
            name: wantMeta ? "" : node.name,
            meta_tags: wantMeta ? (node.meta_tags ?? []) : [],
          });
        }}
        style={{ ...selectStyle, fontWeight: 500 }}
        title={tr("has / has not name the tag; has meta asks the same of ANY tag the tag set marks that way")}
      >
        {TAG_MODES(tr).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      {meta ? (
        // The Link and Caption rows' capsules, over the same namespace: green
        // = the tag must carry it, red = it must not.
        <>
          {toggle}
          <MetaTagChips tags={node.meta_tags ?? []} options={metaOptions}
            onChange={(meta_tags) => onChange({ ...node, meta_tags })} />
        </>
      ) : (
        <TagName node={node} options={options} fetchOptions={fetchOptions}
          onChange={onChange} prefix={toggle} />
      )}
    </>
  );
}

// The tag-name autocomplete needs its own text buffer so typing doesn't rewrite
// the query on every keystroke until a value is committed.
function TagName({ node, options, fetchOptions, onChange, prefix }: {
  node: TagCond; options: AcOption[];
  fetchOptions?: (q: string) => Promise<AcOption[]>;
  onChange: (n: Cond) => void; prefix?: React.ReactNode;
}) {
  const [text, setText] = React.useState(node.name);
  React.useEffect(() => setText(node.name), [node.name]);
  const tr = useT();
  return (
    <Autocomplete
      value={text}
      placeholder={tr("any tag…")}
      options={options}
      fetchOptions={fetchOptions}
      onChange={setText}
      onCommit={(name) => onChange({ ...node, name: tagFieldName(name) })}
      prefix={prefix}
    />
  );
}

// ---- Group membership --------------------------------------------------------

function GrpFields({ node, options, onChange }: {
  node: GrpCond; options: AcOption[]; onChange: (n: Cond) => void;
}) {
  const [text, setText] = React.useState(node.name);
  React.useEffect(() => setText(node.name), [node.name]);
  const tr = useT();
  return (
    <>
      <select
        value={node.mode}
        onChange={(e) => onChange({ ...node, mode: e.target.value as GrpCond["mode"] })}
        style={{ ...selectStyle, fontWeight: 500 }}
        title={tr("has / has not = in the group or in any group under it, as selecting it in the sidebar does; has directly = filed in the group itself, not in a group under it")}
      >
        <option value="has">{tr("has")}</option>
        <option value="hasnot">{tr("has not")}</option>
        <option value="only">{tr("has directly")}</option>
        <option value="notonly">{tr("has not directly")}</option>
      </select>
      <Autocomplete
        value={text}
        // A PATH is offered and accepted: `Trips/2024` says which of several
        // same-named groups is meant, and a bare name goes on meaning any
        // group carrying it.
        placeholder={tr("group name or path…")}
        options={options}
        allowFreeText
        onChange={setText}
        onCommit={(name) => onChange({ ...node, name })}
      />
    </>
  );
}

// ---- Subject ---------------------------------------------------------------

/** A whole number typed into one of the small range fields: `null` for an
 *  empty field, and `undefined` for "that is not a number", which the caller
 *  DROPS.
 *
 *  Rejecting the keystroke is what the metadata value field already does, and
 *  what a "#" costs otherwise is out of proportion to the typo: `Number("#")`
 *  is NaN, the field then reads back the literal word "NaN", and the
 *  condition on the wire carries a number nothing can compare — so a stray
 *  character silently breaks the whole search rather than doing nothing. */
const wholeNumber = (t: string): number | null | undefined => {
  const s = t.trim();
  if (s === "") return null;
  return filterNumeric(s, { integer: true }) != null ? Number(s) : undefined;
};

/** A subject, optionally narrowed by the STATE of the assignment.
 *
 *  "Has this subject" is already a Tag condition — a subject IS a tag — so the
 *  reason this row exists is the second half: the year the picture is from, or
 *  how old its subject was in it. The range fields therefore stay out of the
 *  way until a mode is picked. */
function SubjFields({ node, options, onChange }: {
  node: SubjCond; options: AcOption[]; onChange: (n: Cond) => void;
}) {
  const [text, setText] = React.useState(node.name);
  React.useEffect(() => setText(node.name), [node.name]);
  const tr = useT();
  const mode = node.age_from != null || node.age_to != null ? "age"
    : node.date_from != null || node.date_to != null ? "year" : "any";
  const setMode = (m: string) => onChange({
    ...node, date_from: null, date_to: null, age_from: null, age_to: null,
    ...(m === "year" ? { date_from: new Date().getFullYear() * 10000 } : {}),
    ...(m === "age" ? { age_from: 0 } : {}),
  });
  // A year is typed as a year and stored as a partial date (YYYYMMDD with
  // zeros), so the field never asks for a month nobody knows.
  const asYear = (v?: number | null) => (v == null ? "" : String(Math.floor(v / 10000)));
  const fromYear = (t: string) => {
    const n = wholeNumber(t);
    return n == null ? n : n * 10000;
  };
  const range = (
    lo: number | null | undefined, hi: number | null | undefined,
    show: (v?: number | null) => string,
    read: (t: string) => number | null | undefined,
    set: (a: number | null, b: number | null) => void,
  ) => (
    <>
      <input value={show(lo)} placeholder={tr("from")} inputMode="numeric"
        onChange={(e) => {
          const v = read(e.target.value);
          if (v !== undefined) set(v, hi ?? null);
        }}
        style={{ ...inputStyle, width: 64 }} />
      <span style={{ color: "var(--muted-2)", fontSize: "var(--fs-3)" }}>–</span>
      <input value={show(hi)} placeholder={tr("to")} inputMode="numeric"
        onChange={(e) => {
          const v = read(e.target.value);
          if (v !== undefined) set(lo ?? null, v);
        }}
        style={{ ...inputStyle, width: 64 }} />
    </>
  );
  return (
    <>
      <select value={node.have ? "has" : "hasnot"}
        onChange={(e) => onChange({ ...node, have: e.target.value === "has" })}
        style={{ ...selectStyle, fontWeight: 500 }}>
        <option value="has">{tr("has")}</option>
        <option value="hasnot">{tr("has not")}</option>
      </select>
      <Autocomplete
        value={text}
        placeholder={tr("any subject…")}
        options={options}
        allowFreeText
        onChange={setText}
        onCommit={(name) => onChange({ ...node, name })}
      />
      <select value={mode} onChange={(e) => setMode(e.target.value)}
        style={selectStyle}
        title={tr("Narrow by the state of the assignment: the year of the picture, or the subject's age in it")}>
        <option value="any">{tr("any time")}</option>
        <option value="year">{tr("in year")}</option>
        <option value="age">{tr("at age")}</option>
      </select>
      {mode === "year" && range(node.date_from, node.date_to, asYear, fromYear,
        (a, b) => onChange({ ...node, date_from: a, date_to: b }))}
      {mode === "age" && range(node.age_from, node.age_to,
        (v) => (v == null ? "" : String(v)), wholeNumber,
        (a, b) => onChange({ ...node, age_from: a, age_to: b }))}
    </>
  );
}

// ---- Event -----------------------------------------------------------------

/** WHEN the picture was taken — a window, typed the way a person writes one.
 *
 *  Two fields rather than a year dropdown, because this is the one condition
 *  where a day and a time are the point: "the afternoon of the 5th" is a real
 *  question about a photograph, and "in year 2020" is not the same question. */
function TakenFields({ node, onChange }: {
  node: TakenCond; onChange: (n: Cond) => void;
}) {
  const [from, setFrom] = React.useState(formatTaken(node.date_from));
  const [to, setTo] = React.useState(formatTaken(node.date_to));
  React.useEffect(() => setFrom(formatTaken(node.date_from)), [node.date_from]);
  React.useEffect(() => setTo(formatTaken(node.date_to)), [node.date_to]);
  const tr = useT();
  const commit = (which: "from" | "to", text: string) => {
    const value = text.trim() ? parseTaken(text) : null;
    onChange({ ...node, [which === "from" ? "date_from" : "date_to"]: value });
  };
  return (
    <>
      <select value={node.have ? "has" : "hasnot"}
        onChange={(e) => onChange({ ...node, have: e.target.value === "has" })}
        style={{ ...selectStyle, fontWeight: 500 }}>
        <option value="has">{tr("taken")}</option>
        <option value="hasnot">{tr("not known")}</option>
      </select>
      {node.have && (<>
        <input value={from} placeholder={tr("from…")}
          onChange={(e) => setFrom(e.target.value)}
          onBlur={() => commit("from", from)}
          onKeyDown={(e) => { if (e.key === "Enter") commit("from", from); }}
          style={inputStyle} />
        <input value={to} placeholder={tr("to…")}
          onChange={(e) => setTo(e.target.value)}
          onBlur={() => commit("to", to)}
          onKeyDown={(e) => { if (e.key === "Enter") commit("to", to); }}
          style={inputStyle} />
      </>)}
    </>
  );
}

function EventFields({ node, options, onChange }: {
  node: EventCond; options: AcOption[]; onChange: (n: Cond) => void;
}) {
  const [text, setText] = React.useState(node.name);
  React.useEffect(() => setText(node.name), [node.name]);
  const tr = useT();
  // Two modes where a subject has three: an event has a span of its own, and
  // no age — it is not somebody who gets older.
  const dated = node.date_from != null || node.date_to != null;
  const asYear = (v?: number | null) => (v == null ? "" : String(Math.floor(v / 10000)));
  const fromYear = (t: string) => {
    const n = wholeNumber(t);
    return n == null ? n : n * 10000;
  };
  return (
    <>
      <select value={node.have ? "has" : "hasnot"}
        onChange={(e) => onChange({ ...node, have: e.target.value === "has" })}
        style={{ ...selectStyle, fontWeight: 500 }}>
        <option value="has">{tr("was at")}</option>
        <option value="hasnot">{tr("was not at")}</option>
      </select>
      <Autocomplete
        value={text}
        placeholder={tr("any event…")}
        options={options}
        allowFreeText
        onChange={setText}
        onCommit={(name) => onChange({ ...node, name })}
      />
      <select value={dated ? "year" : "any"}
        onChange={(e) => onChange({
          ...node,
          date_from: e.target.value === "year"
            ? new Date().getFullYear() * 10000 : null,
          date_to: null,
        })}
        style={selectStyle}
        title={tr("Narrow by when the EVENT was — not when the picture says it is from")}>
        <option value="any">{tr("whenever")}</option>
        <option value="year">{tr("in year")}</option>
      </select>
      {dated && (
        <>
          <input value={asYear(node.date_from)} placeholder={tr("from")} inputMode="numeric"
            onChange={(e) => {
              const v = fromYear(e.target.value);
              if (v !== undefined) onChange({ ...node, date_from: v });
            }}
            style={{ ...inputStyle, width: 64 }} />
          <span style={{ color: "var(--muted-2)", fontSize: "var(--fs-3)" }}>–</span>
          <input value={asYear(node.date_to)} placeholder={tr("to")} inputMode="numeric"
            onChange={(e) => {
              const v = fromYear(e.target.value);
              if (v !== undefined) onChange({ ...node, date_to: v });
            }}
            style={{ ...inputStyle, width: 64 }} />
        </>
      )}
    </>
  );
}

// ---- Place -----------------------------------------------------------------

// THERE IS NOTHING TO PICK: a place condition matches the ADDRESS and that is
// all a place says. The dropdown listed eight typed components once, then the
// address and the identity tag — and that pair was one choice too many,
// since searching a place's TAG is the same question asked better (a place IS
// a tag), and the tag search folds sequence containers where this does not.
function PlaceFields({ node, places, onChange }: {
  node: PlaceCond; places: PlaceRow[]; onChange: (n: Cond) => void;
}) {
  const [text, setText] = React.useState(node.value);
  React.useEffect(() => setText(node.value), [node.value]);
  const tr = useT();
  const options: AcOption[] = React.useMemo(
    () => placeValues(places).map((name) => ({ name })), [places]
  );
  return (
    <>
      <select value={node.have ? "has" : "hasnot"}
        onChange={(e) => onChange({ ...node, have: e.target.value === "has" })}
        style={{ ...selectStyle, fontWeight: 500 }}>
        <option value="has">{tr("is at")}</option>
        <option value="hasnot">{tr("is not at")}</option>
      </select>
      <select value={node.op} onChange={(e) => onChange({ ...node, op: e.target.value as "=" | "~" })}
        style={selectStyle}>
        <option value="~">{tr("contains")}</option>
        <option value="=">{tr("is")}</option>
      </select>
      <Autocomplete
        value={text}
        placeholder={tr("anywhere at all…")}
        options={options}
        allowFreeText
        onChange={setText}
        onCommit={(value) => onChange({ ...node, value })}
      />
    </>
  );
}

// ---- Link ------------------------------------------------------------------

const LINK_DIRS = (tr: TFn): [LinkDir, string][] => [
  ["has", tr("has link")], ["hasnot", tr("has no link")],
  ["linkedby", tr("is linked")], ["notlinkedby", tr("is not linked")],
];

/** The required/excluded meta-tag chip editor — shared by the Link and the
 *  Caption condition, which narrow by the same tag namespace. */
function MetaTagChips({ tags, options, onChange }: {
  tags: LinkTagRef[]; options: AcOption[];
  onChange: (next: LinkTagRef[]) => void;
}) {
  const [text, setText] = React.useState("");
  const tr = useT();
  const addTag = (name: string) => {
    const n = name.trim().toLowerCase();
    if (!n || tags.some((t) => t.name === n)) { setText(""); return; }
    onChange([...tags, { name: n, exclude: false }]);
    setText("");
  };
  const toggle = (i: number) => onChange(
    tags.map((t, j) => j === i ? { ...t, exclude: !t.exclude } : t));
  const remove = (i: number) => onChange(tags.filter((_, j) => j !== i));

  return (
    <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6,
        background: "var(--bg)", border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)",
        padding: "3px 8px", minHeight: 30, boxSizing: "border-box" }}>
        {tags.map((t, i) => (
          <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 4,
            background: "var(--panel-2)", border: "1px solid var(--border-strong)", borderRadius: "var(--r-2)",
            padding: "2px 3px 2px 4px", fontSize: "var(--fs-2)", fontWeight: 600, color: "var(--text)" }}>
            <button onClick={() => toggle(i)}
              title={t.exclude ? tr("Excluded — click to require") : tr("Required — click to exclude")}
              style={{ width: 12, height: 12, borderRadius: 3, border: "none", cursor: "pointer",
                background: t.exclude ? "var(--red)" : "var(--green)" }} />
            {t.name}
            <button onClick={() => remove(i)} title={tr("Remove meta tag")}
              style={{ width: 15, height: 15, display: "flex", alignItems: "center", justifyContent: "center",
                border: "none", background: "transparent", color: "var(--muted-2)", cursor: "pointer", fontSize: "var(--fs-4)" }}>×</button>
          </span>
        ))}
        <div style={{ flex: 1, minWidth: 70, position: "relative", display: "flex" }}>
          <Autocomplete
            bare
            value={text}
            placeholder={tags.length ? "" : tr("tags")}
            options={options.filter((o) => !tags.some((t) => t.name === o.name))}
            onChange={setText}
            onCommit={addTag}
          />
        </div>
      </div>
    </div>
  );
}

function LinkFields({ node, options, onChange }: {
  node: LinkCond; options: AcOption[]; onChange: (n: Cond) => void;
}) {
  const tr = useT();
  return (
    <>
      <select value={node.direction} onChange={(e) => onChange({ ...node, direction: e.target.value as LinkDir })}
        style={{ ...selectStyle, fontWeight: 500 }}>
        {LINK_DIRS(tr).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <MetaTagChips tags={node.link_tags} options={options}
        onChange={(link_tags) => onChange({ ...node, link_tags })} />
    </>
  );
}

// ---- Caption ---------------------------------------------------------------

const CAP_MODES = (tr: TFn): [CapMode, string][] => [
  ["has", tr("has caption")], ["hasnot", tr("has no caption")],
];
// The same two, said about the other list. Spelled out rather than built from
// the pair above: "has no instruction" is not "has no caption" with a word
// swapped in every language this gets translated into.
const INSTR_MODES = (tr: TFn): [CapMode, string][] => [
  ["has", tr("has instruction")], ["hasnot", tr("has no instruction")],
];

function CaptionFields({ node, options, onChange }: {
  node: CapCond; options: AcOption[]; onChange: (n: Cond) => void;
}) {
  const tr = useT();
  const modes = node.caption_kind === "instruction" ? INSTR_MODES(tr) : CAP_MODES(tr);
  return (
    <>
      <select value={node.mode}
        onChange={(e) => onChange({ ...node, mode: e.target.value as CapMode })}
        style={{ ...selectStyle, fontWeight: 500 }}>
        {modes.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <MetaTagChips tags={node.caption_tags} options={options}
        onChange={(caption_tags) => onChange({ ...node, caption_tags })} />
    </>
  );
}

// ---- Metadata --------------------------------------------------------------

function MetaFields({ node, catalog, onChange }: {
  node: MetaCond; catalog: MetadataCatalogEntry[]; onChange: (n: Cond) => void;
}) {
  const [text, setText] = React.useState(node.name);
  React.useEffect(() => setText(node.name), [node.name]);

  const tr = useT();
  // Types available for the current name (a name may support several).
  const types = catalog.filter((c) => c.name === node.name).map((c) => c.mtype);
  const mtype: MetaType = types.includes(node.mtype) ? node.mtype : (types[0] ?? node.mtype);
  const ops = mtype === "text" ? TEXT_OPS(tr) : mtype === "date" ? DATE_OPS(tr) : NUM_OPS;
  const op = ops.some(([v]) => v === node.op) ? node.op : ops[0][0];
  // A text name's values are fetched on demand while its dropdown is open
  // (debounced, and once on open — so format / mode / … still offer their
  // values before anything is typed). The catalog is names-only now; it no
  // longer carries a values array per enumerated name.
  const name = node.name;
  const fetchValues = mtype === "text" && name
    ? (q: string) => api.metadataValues(name, q)
        .then((vs) => vs.map((v) => ({ name: v })))
    : undefined;

  const nameOptions: AcOption[] = React.useMemo(() => {
    const byName = new Map<string, string[]>();
    for (const c of catalog) {
      const arr = byName.get(c.name) ?? [];
      arr.push(c.mtype[0].toUpperCase() + c.mtype.slice(1));
      byName.set(c.name, arr);
    }
    return [...byName].map(([name, ts]) => ({ name, hint: [...new Set(ts)].join(" / ") }));
  }, [catalog]);

  // A fresh date condition defaults to today (rather than an empty value), so it
  // filters right away; other types start empty.
  const defaultValue = (mt: MetaType) => (mt === "date" ? todayISO() : "");
  // A CODED numeric name (orientation, flash, …) starts on "=" like a text one
  // rather than on ">=": its numbers are labels, not quantities, so "rotated
  // 90° CW or more" is not a question anybody is asking. The ordered operators
  // stay AVAILABLE — the codes really are ordered, and narrowing the list is a
  // different decision from choosing what a fresh row starts as.
  const defaultOp = (name: string, mt: MetaType) =>
    mt === "text" || mt === "date" || hasMetaEnum(name) ? "=" : ">=";
  const pickName = (name: string) => {
    const ts = catalog.filter((c) => c.name === name).map((c) => c.mtype);
    const mt = (ts[0] ?? "text") as MetaType;
    onChange({ type: "meta", name, mtype: mt, op: defaultOp(name, mt), value: defaultValue(mt) });
  };
  const setType = (mt: MetaType) => onChange({ ...node, mtype: mt, op: defaultOp(node.name, mt), value: defaultValue(mt) });

  return (
    <>
      <div style={{ position: "relative", flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 6 }}>
        <Autocomplete
          value={text}
          placeholder={tr("metadata name")}
          options={nameOptions}
          onChange={setText}
          onCommit={pickName}
        />
        {types.length > 1 && (
          <select value={mtype} onChange={(e) => setType(e.target.value as MetaType)} title={tr("Value type")}
            style={{ ...selectStyle, height: 22, fontSize: "var(--fs-1)", fontWeight: 600, borderRadius: "var(--r-round)", padding: "0 6px" }}>
            {types.map((t) => <option key={t} value={t}>{t === "numeric" ? tr("Number") : t === "date" ? tr("Date") : tr("Text")}</option>)}
          </select>
        )}
      </div>
      <select value={op} onChange={(e) => onChange({ ...node, op: e.target.value })} style={{ ...selectStyle, fontWeight: 500 }}>
        {ops.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      <MetaValue node={{ ...node, mtype, op }} fetchValues={fetchValues} onChange={onChange} />
    </>
  );
}

function MetaValue({ node, fetchValues, onChange }: {
  node: MetaCond;
  fetchValues?: (q: string) => Promise<AcOption[]>;
  onChange: (n: Cond) => void;
}) {
  const tr = useT();
  if (node.mtype === "date") {
    return <DateTimeValue node={node} onChange={onChange} />;
  }
  if (node.mtype === "text") {
    // A text field with autocomplete: the name's values in the library are
    // fetched while the dropdown is open, but any value can be typed —
    // including ones not present in the library.
    const cur = String(node.value);
    return (
      <Autocomplete
        value={cur}
        placeholder={tr("text")}
        fetchOptions={fetchValues}
        allowFreeText
        onChange={(v) => onChange({ ...node, value: v })}
        onCommit={(v) => onChange({ ...node, value: v })}
      />
    );
  }
  // A CODED name (orientation, flash, metering mode, white balance) picks its
  // value from a list of words. What is stored is still the NUMBER — the same
  // one typing it by hand produces, `tol` included — so the query string, the
  // wire and the index are untouched and only the choosing is in words. A
  // number field for these was asking somebody to know that 6 is "rotated 90°
  // CW", which is a lookup table nobody has.
  const enumOptions = metaEnumOptions(node.name);
  if (enumOptions.length) {
    const cur = String(node.value ?? "");
    // A value this table does not name still has to render: a code a camera
    // wrote that EXIF does not define, or one carried by a query written
    // somewhere else. A `<select>` with no matching option shows the wrong one.
    const known = enumOptions.some((o) => o.value === cur);
    return (
      <select
        value={cur}
        title={tr("Value")}
        onChange={(e) => onChange({
          ...node, value: Number(e.target.value),
          tol: numTolerance(e.target.value),
        })}
        style={{ ...selectStyle, flex: "none", maxWidth: 190 }}
      >
        {!known && <option value={cur}>{cur === "" ? tr("value") : cur}</option>}
        {enumOptions.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    );
  }
  return (
    <span style={{ ...fieldWrap, flex: "none", width: 110 }}>
      {/* Typed precision is meaningful here — it sets how wide a window "="
          accepts (0.7 = about 0.7, 0.75 = much narrower) — so the field shows
          the value back with the decimals that were typed, trailing zeros and
          all, instead of whatever String(0.70) collapses to. */}
      <input value={metaValueText(node)} placeholder={tr("value")} inputMode="decimal"
        onChange={(e) => {
          const v = e.target.value;
          if (v !== "" && !/^-?\d*\.?\d*$/.test(v)) return;
          const partial = v === "" || v.endsWith(".") || v === "-";
          onChange({ ...node, value: partial ? v : Number(v), tol: numTolerance(v) });
        }}
        style={{ ...inputStyle, width: "100%" }} />
    </span>
  );
}

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Parse `YYYY-MM-DD` as a *local* date. `new Date("2026-07-12")` is parsed as UTC
// midnight, which shifts the day in some timezones — build it from parts instead.
function localDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

/** Date value with an *optional* time. The date is an app-formatted display over
 *  the system calendar; the time is a set of native `<select>` dropdowns (always
 *  reliable, unlike a native time picker) whose labels honor the 24-hour setting,
 *  with a "— any time" none option. Emits a separated value at whatever precision
 *  is set — `2026-07-12` (whole day) or `2026-07-12T22:12` (time). */
function DateTimeValue({ node, onChange }: { node: MetaCond; onChange: (n: Cond) => void }) {
  const { formatDate, time24h } = useDateFormatters();
  const { date, time } = splitDateValue(node.value);
  // Default to today so a fresh condition filters right away, and so clearing
  // the time still leaves a valid day.
  const day = date || todayISO();
  const emit = (d: string, t: string) =>
    onChange({ ...node, value: t ? `${d}T${t}` : d });
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, flexWrap: "wrap" }}>
      <PickerField
        icon="calendar_month"
        text={formatDate(localDate(day))}
        muted={false}
        inputType="date"
        value={day}
        onValue={(v) => emit(v || day, time)}
      />
      <TimeInput time={time} time24h={time24h} onChange={(t) => emit(day, t)} />
    </span>
  );
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/** Format an internal `HH:MM` (24-hour) as the user's clock prefers, for the
 *  text field's display. Empty stays empty ("any time"). */
function displayTime(time: string, time24h: boolean): string {
  if (!time) return "";
  const [h, m] = time.split(":").map(Number);
  if (time24h) return `${pad2(h)}:${pad2(m)}`;
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${pad2(m)} ${h < 12 ? "AM" : "PM"}`;
}

/** Parse a typed time into internal `HH:MM`. Accepts 24-hour (`14:30`, `1430`,
 *  `14`) and 12-hour (`2:30 pm`, `2pm`) forms. Empty → `""` (any time); an
 *  unparseable value → `undefined` (keep the previous). */
function parseTimeInput(s: string): string | undefined {
  const t = s.trim().toLowerCase();
  if (!t) return "";
  const m = t.match(/^(\d{1,2})[:.\s]?(\d{2})?\s*(am|pm|a|p)?$/);
  if (!m) return undefined;
  let h = parseInt(m[1], 10);
  const min = m[2] ? parseInt(m[2], 10) : 0;
  const ap = m[3];
  if (min > 59) return undefined;
  if (ap) {
    if (h < 1 || h > 12) return undefined;
    h = ap[0] === "p" ? (h === 12 ? 12 : h + 12) : (h === 12 ? 0 : h);
  } else if (h > 23) return undefined;
  return `${pad2(h)}:${pad2(min)}`;
}

/** Optional time-of-day as a small text field (a native time picker is
 *  unreliable across browsers). Displayed per the 24-hour setting; empty means
 *  "any time" (day precision). Parses on blur / Enter and normalizes the text. */
function TimeInput({ time, time24h, onChange }: {
  time: string; time24h: boolean; onChange: (t: string) => void;
}) {
  const [text, setText] = useState(() => displayTime(time, time24h));
  const tr = useT();
  // Re-sync when the value changes externally (e.g. the query string is edited).
  useEffect(() => { setText(displayTime(time, time24h)); }, [time, time24h]);
  const commit = () => {
    const parsed = parseTimeInput(text);
    if (parsed === undefined) { setText(displayTime(time, time24h)); return; }  // invalid → revert
    setText(displayTime(parsed, time24h));
    if (parsed !== time) onChange(parsed);
  };
  return (
    <span
      style={{ ...fieldWrap, flex: "0 0 auto", gap: 5 }}
      title={time24h ? tr("Time (24-hour, e.g. 14:30) — empty for any time")
        : tr("Time (e.g. 2:30 PM) — empty for any time")}
    >
      <Icon name="schedule" size={14} color="var(--muted-2)" style={{ flex: "0 0 auto" }} />
      <input
        value={text}
        placeholder={tr("any time")}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") { commit(); (e.target as HTMLInputElement).blur(); } }}
        spellCheck={false}
        style={{ ...inputStyle, width: time24h ? 52 : 78 }}
      />
    </span>
  );
}

/** App-formatted text over a full-size, transparent native input which is the
 *  source of truth and opens the system calendar on click. Keeping the input
 *  full-size (rather than a 1×1 stub) lets the browser light-dismiss the picker
 *  normally on click-away / Escape. Sizes to its content (no truncation). */
function PickerField({ icon, text, muted, inputType, value, onValue }: {
  icon: string;
  text: string;
  muted: boolean;
  inputType: "date" | "time";
  value: string;
  onValue: (v: string) => void;
}) {
  const openPicker = (e: React.MouseEvent<HTMLInputElement>) => {
    const el = e.currentTarget as HTMLInputElement & { showPicker?: () => void };
    // Clicking the (transparent) input body doesn't open the calendar on its
    // own, so trigger it; if the picker is already open this is a no-op.
    try { el.showPicker?.(); } catch { /* falls back to normal focus */ }
  };
  return (
    <span style={{ ...fieldWrap, position: "relative", flex: "0 0 auto", gap: 5 }}>
      <Icon name={icon} size={14} color="var(--muted-2)" style={{ flex: "0 0 auto", pointerEvents: "none" }} />
      <span style={{ fontSize: "var(--fs-3)", fontWeight: 600, color: muted ? "var(--muted-2)" : "var(--text)", whiteSpace: "nowrap", pointerEvents: "none" }}>
        {text}
      </span>
      <input
        type={inputType}
        value={value}
        onChange={(e) => onValue(e.target.value)}
        onClick={openPicker}
        aria-label={`Pick a ${inputType}`}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0, cursor: "pointer", border: "none", padding: 0, margin: 0 }}
      />
    </span>
  );
}

/** How far apart two palettes may be and still count.
 *
 *  A tolerance is a HAMMING DISTANCE — how many bits of the two 56-bit
 *  signatures differ — and 16 is where the answers stop meaning anything.
 *  Mirrors `query.MAX_SIMILAR_TOL`, which is what the backend refuses on. */
const SIMILAR_MAX = 16;

/** Where the slider rests while nothing has been said, mirroring
 *  `query.DEFAULT_COLOR_TOL`. It used to read the library's own
 *  `phash_threshold` — a 256-bit near-dup setting against a 56-bit palette
 *  hash, which admitted 72% of unrelated pairs. */
const SIMILAR_DEFAULT = 2;

/**
 * LIKENESS TO ONE PARTICULAR PICTURE.
 *
 * The pivot is shown as its thumbnail rather than as a raw uid: a 32-hex
 * string tells nobody which picture the query is about, and this row is
 * usually arrived at from the grid's "Find similar colors", where the
 * picture is exactly what was just being looked at.
 *
 * The tolerance is a SLIDER, and that is the whole point of it: it was a text
 * field, so "within…" invited a number with nothing saying which numbers
 * exist — and a typed 200 was a refusal from the server rather than something
 * the control could not express. It starts at the default, which is what
 * `tol: null` means, so leaving it there sends nothing and the backend's
 * answer keeps applying even if that number later moves.
 */
function SimilarFields({ node, onChange }: {
  node: SimilarCond; onChange: (n: Cond) => void;
}) {
  const max = SIMILAR_MAX;
  const tr = useT();
  const value = node.tol == null ? SIMILAR_DEFAULT : Math.min(node.tol, max);
  const item = useQuery({
    queryKey: ["item-by-uid", node.uid],
    queryFn: () => api.itemsQuery({
      query: { type: "group", op: "and", neg: false, children: [
        { type: "meta", name: "id", mtype: "text", op: "=", value: node.uid },
      ] }, page: 1, page_size: 1,
    }),
    enabled: !!node.uid,
    staleTime: 60_000,
  });
  const hit = item.data?.items?.[0];
  // WITH NO PIVOT, THE CLIPBOARD IS THE FIELD. There was a box to paste an id
  // into, which is a text field asking for a 32-character hex string — the
  // grid's Copy already puts exactly that on the system clipboard, so the row
  // reads it instead of asking. Nothing else could ever be typed there by
  // hand and be right.
  //
  // Tried ONCE per empty row, and again on a click: a clipboard read is
  // permission-gated and some browsers only allow it from a user gesture, so
  // the placeholder is also the retry.
  const tried = React.useRef(false);
  /** Take an id from a string — whatever handed it over. */
  const takeId = React.useCallback(async (text: string) => {
    // The first word, and only if it looks like a uid at all: a clipboard
    // usually holds something else entirely, and a lookup per stray string
    // would be a request per row per open.
    const uid = text.split(/\s+/)[0]?.trim() ?? "";
    if (!/^[0-9a-f]{32}$/i.test(uid)) return;
    const found = await api.itemsQuery({
      query: { type: "group", op: "and", neg: false, children: [
        { type: "meta", name: "id", mtype: "text", op: "=", value: uid },
      ] }, page: 1, page_size: 1,
    }).catch(() => null);
    if (found?.items?.length) onChange({ ...node, uid });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.by, node.have, node.tol]);
  const takeFromClipboard = React.useCallback(async () => {
    // Reading the clipboard is permission-gated and a browser may simply
    // refuse — which is why a PASTE onto the frame works too and needs no
    // permission at all (the event carries the text).
    let text = "";
    try { text = (await navigator.clipboard?.readText()) ?? ""; }
    catch { return; }
    await takeId(text);
  }, [takeId]);
  React.useEffect(() => {
    if (node.uid || tried.current) return;
    tried.current = true;
    void takeFromClipboard();
  }, [node.uid, takeFromClipboard]);
  // Without a picture there is nothing for a tolerance to be measured FROM,
  // so the slider says so by being unusable rather than by moving and
  // changing nothing.
  const noPivot = !node.uid;
  return (
    <>
      <select value={node.have ? "has" : "hasnot"}
        onChange={(e) => onChange({ ...node, have: e.target.value === "has" })}
        style={{ ...selectStyle, fontWeight: 500 }}>
        <option value="has">{tr("are like")}</option>
        <option value="hasnot">{tr("are not like")}</option>
      </select>
      {/* THE PIVOT, as its thumbnail — a 32-hex string names nothing. With
          none, an empty frame that takes the id off the clipboard: this row
          is usually reached from the grid's "Find similar colors", but a
          query typed or shared arrives with nothing in it, and copying a
          picture is how you say which one. */}
      {hit?.active_file_id ? (
        <img
          src={api.thumbUrl(hit.active_file_id, 64, hit.thumb_token)}
          title={`${hit.name}\n${tr("Click to pick another picture")}`}
          onClick={() => { tried.current = false; onChange({ ...node, uid: "" }); }}
          style={{ width: 26, height: 26, borderRadius: "var(--r-1)", objectFit: "cover",
                   border: "1px solid var(--border)", flex: "0 0 auto",
                   cursor: "pointer" }}
        />
      ) : (
        <span
          tabIndex={0}
          onClick={(e) => {
            // Both ways in: read the clipboard where the browser allows it,
            // and take the focus either way so a ⌘/Ctrl+V lands here — a
            // paste event carries the text with no permission at all.
            (e.currentTarget as HTMLElement).focus();
            void takeFromClipboard();
          }}
          onPaste={(e) => {
            e.preventDefault();
            void takeId(e.clipboardData.getData("text"));
          }}
          title={tr("No picture. Copy one in the grid (right-click ▸ Copy id), then click here — or click and paste.")}
          style={{
            width: 26, height: 26, borderRadius: "var(--r-1)", flex: "0 0 auto",
            display: "flex", alignItems: "center", justifyContent: "center",
            border: "1px dashed var(--border-strong)", cursor: "pointer",
            color: "var(--muted-3)", outlineOffset: 2,
          }}
        >
          <Icon name="image" size={15} />
        </span>
      )}
      <span style={{ display: "flex", alignItems: "center", gap: 6,
                     flex: "0 0 auto" }}
        title={tr("How far from the picture still counts: how many of the {bits} fingerprint bits may differ. 0 is an exact match, {max} is as far as this means anything.",
                  { bits: node.by === "color" ? 56 : 256, max })}>
        <input
          type="range" min={0} max={max} step={1} value={value}
          disabled={noPivot}
          onChange={(e) => onChange({ ...node, tol: Number(e.target.value) })}
          style={{ width: 96, accentColor: "var(--accent)",
                   opacity: noPivot ? 0.4 : 1,
                   cursor: noPivot ? "default" : "pointer" }}
        />
        {/* Just the number. The maximum is the slider's own right-hand end,
            which the slider already shows by being one. */}
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                       color: node.tol == null ? "var(--muted-2)" : "var(--text-3)",
                       minWidth: 16, textAlign: "right",
                       opacity: noPivot ? 0.4 : 1 }}>
          {value}
        </span>
        {/* Back to the library's own threshold. Always here, so the row does
            not change width as the slider moves; DISABLED while it is already
            there, which is also how the row says that no number of its own is
            set — the state the label used to spell out. */}
        <span
          className={node.tol == null || noPivot ? undefined : "hoverable"}
          title={node.tol == null
            ? tr("Following the library's own threshold")
            : tr("Back to the library's own threshold")}
          onClick={node.tol == null || noPivot
            ? undefined : () => onChange({ ...node, tol: null })}
          style={{ cursor: node.tol == null ? "default" : "pointer",
                   display: "flex", alignItems: "center", borderRadius: "var(--r-1)",
                   opacity: node.tol == null || noPivot ? 0.35 : 1,
                   color: "var(--muted-2)" }}
        >
          <Icon name="undo" size={14} />
        </span>
      </span>
    </>
  );
}


// ---- Tag value -------------------------------------------------------------

/** TAGS READ AS NUMBERS — `VALUE:height>190cm`.
 *
 *  The name is a NAMESPACE: the row matches an item carrying ANY tag in it
 *  whose basename parses as a value satisfying the comparison
 *  (`shared/tagvalue.ts`). The namespace autocomplete offers only namespaces
 *  that actually hold numeric tags — derived from the same tag completions
 *  the Tag row uses, so it costs no endpoint of its own.
 *
 *  The value and its unit are ONE field ("190cm", "1.72m", "8"): they are one
 *  token in the tag and one token in the query string, and a separate unit
 *  dropdown would have to enumerate a space that is deliberately free. The
 *  field keeps its text locally and commits only what parses — the number
 *  fields' rule, a keystroke that cannot become a value never reaches the
 *  wire — and the tolerance is read off the typed decimals while they are
 *  still text (`numTolerance`), so `=1.70m` and `=1.7m` stay two different
 *  questions.
 */
function ValueFields({ node, onChange }: {
  node: ValueCond;
  onChange: (n: Cond) => void;
}) {
  const [ns, setNs] = React.useState(node.name);
  React.useEffect(() => setNs(node.name), [node.name]);
  // The namespace source is its OWN endpoint, never a filtered sample of the
  // count-ranked tag autocomplete: on a big library the top rows of `/names`
  // are all ordinary tags, so the derived list read "no matches" while the
  // catalog held plenty of value namespaces.
  const fetchNamespaces = React.useMemo(() => {
    return async (q: string): Promise<AcOption[]> => {
      const rows = await api.valueNamespaces(q);
      return rows.map((r) => ({
        name: r.name,
        hint: r.count === 1 ? "1 value tag" : `${r.count} value tags`,
      }));
    };
  }, []);

  const nodeText = () => {
    const num = node.tol
      ? node.value.toFixed(Math.max(0, Math.round(-Math.log10(node.tol * 2))))
      : String(node.value);
    return `${num}${node.unit}`;
  };
  const [valText, setValText] = React.useState(nodeText());
  const tr = useT();
  // Follow the node when it changes underneath (a parse of the text field
  // rebuilt the tree) — but not while the local text still means the same
  // condition, or typing "1.7" would snap to "1.7" + the old unit mid-word.
  React.useEffect(() => {
    const v = parseValue(valText.replace(",", "."));
    if (!v || v.value !== node.value || v.unit !== node.unit) {
      setValText(nodeText());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.value, node.unit, node.tol]);

  return (
    <>
      <select value={node.have ? "has" : "hasnot"}
        onChange={(e) => onChange({ ...node, have: e.target.value === "has" })}
        style={{ ...selectStyle, fontWeight: 500 }}
        title={tr("has = carries a matching value tag; has no = carries none")}>
        <option value="has">{tr("has")}</option>
        <option value="hasnot">{tr("has no")}</option>
      </select>
      <Autocomplete
        value={ns}
        placeholder={tr("namespace, e.g. height…")}
        fetchOptions={fetchNamespaces}
        allowFreeText
        onChange={(text) => {
          // The FIELD's rule, then the trailing colon off: this field is a
          // NAMESPACE, and a namespace is spelled without its colon where a
          // tag name keeps one (`d:` and `:d` are both ordinary names).
          const clean = tagFieldInput(text);
          setNs(clean);
          onChange({ ...node, name: clean.replace(/:+$/, "") });
        }}
        onCommit={(name) => {
          setNs(name);
          onChange({ ...node, name });
        }}
      />
      <select value={node.op}
        onChange={(e) => onChange({ ...node, op: e.target.value as ValueCond["op"] })}
        style={selectStyle}>
        <option value="=">=</option>
        <option value="!=">≠</option>
        <option value=">">&gt;</option>
        <option value=">=">≥</option>
        <option value="<">&lt;</option>
        <option value="<=">≤</option>
      </select>
      <input
        value={valText}
        placeholder={tr("value, e.g. 190cm")}
        onChange={(e) => {
          const raw = e.target.value;
          // The keystroke is rejected outright when it could never become a
          // value — the metadata number field's rule, with the unit letters
          // allowed in.
          if (!/^-?[\d.,a-z%°µ]*$/.test(raw)) return;
          setValText(raw);
          const v = parseValue(raw.replace(",", "."));
          if (v) {
            onChange({ ...node, value: v.value, unit: v.unit,
                       tol: numTolerance(raw.replace(",", ".")) });
          }
        }}
        onBlur={() => setValText(nodeText())}
        style={{ ...inputStyle, width: 110 }}
      />
    </>
  );
}
