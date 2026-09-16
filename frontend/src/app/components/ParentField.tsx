/**
 * WHAT THIS ONE IS INSIDE — the parent picker, shared by places, events and
 * a tag set's own records.
 *
 * Tokyo Tower is in Tokyo is in Japan; Day 1 is part of the convention is
 * part of the season. One optional parent each, and assigning the child
 * assigns everything above it — not by a mechanism of its own, but because
 * the identity tags gain an ordinary implication (see `ops/places.set_parent`).
 *
 * TWO FORMS OVER ONE PICKER. The library's places and events are small
 * catalogs, so `ParentField` is offered the whole thing and answers with an
 * ID, refusing the two candidates that would make a loop (itself, and
 * anything already underneath it) and showing the chain above a choice. A
 * tag set's records are searched on the SERVER and named by TAG NAME, so
 * `RemoteParentField` answers with a string, commits what is typed on the
 * way out, and can MAKE a record the set lacks. The list under both — the
 * rows, the highlight, the arrows, Enter, the two-stage Escape, the Create
 * row first with the highlight on the first match — is the shared one
 * (`useSuggestList`), which this field used to draw for itself with Create
 * last and a highlight of its own.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";

import { Icon } from "../../shared/Icon";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { tagDebounceMs, useDebouncedValue } from "../../shared/useDebounced";
import { useT } from "../i18n";
import { rankTagMatches, SUGGEST_CAP } from "../tagRank";
import { TagSuggestList, useSuggestList, type SuggestList } from "./TagSuggestList";

export interface ParentRow {
  id: number;
  parent_id?: number | null;
  label: string;
  /** The second line — an address, a span of days. */
  hint?: string;
}

/** Everything that may not be a parent of `id`: itself and its descendants.
 *  Pure, and exported because both the field and its tests want it. */
export function descendantsOf(rows: ParentRow[], id: number | null): Set<number> {
  const out = new Set<number>();
  if (id == null) return out;
  out.add(id);
  // Walk down until nothing new is reached — a list this size makes the
  // simple fixpoint cheaper than building an index.
  let grew = true;
  while (grew) {
    grew = false;
    for (const r of rows) {
      if (r.parent_id != null && out.has(r.parent_id) && !out.has(r.id)) {
        out.add(r.id);
        grew = true;
      }
    }
  }
  return out;
}

/** A row the picker draws: a name (what the list keys by), a label, and
 *  the quiet line after it. */
export interface ParentChoice {
  name: string;
  label: string;
  hint?: string;
  icon?: string;
}

const FIELD: React.CSSProperties = {
  width: "100%", height: 32, padding: "0 10px", background: "var(--bg)",
  border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)",
  color: "var(--text)", fontSize: "var(--fs-3)", outline: "none",
  boxSizing: "border-box",
};

/** The input and its list. */
function ParentPicker({ list, text, onText, placeholder, mono, inputRef, busy }: {
  list: SuggestList<ParentChoice>;
  text: string;
  onText: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  inputRef: React.RefObject<HTMLInputElement>;
  busy?: boolean;
}) {
  const rect = useAnchorRect(inputRef, list.open);
  return (
    <div style={{ position: "relative" }}>
      <input
        ref={inputRef}
        value={text}
        placeholder={placeholder}
        disabled={busy}
        onChange={(e) => { onText(e.target.value); list.undismiss(); }}
        {...list.inputProps}
        style={{ ...FIELD, ...(mono ? { fontFamily: "var(--mono)" } : null) }}
      />
      {list.open && (
        <AnchoredDropdown rect={rect} minWidth={240} fill>
          <TagSuggestList list={list} dense fill
            renderRow={(r) => (<>
              {r.icon && <Icon name={r.icon} size={14} color="var(--accent)" />}
              <span style={{ minWidth: 0, overflow: "hidden",
                             textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.label}
              </span>
              {r.hint && (
                <span style={{ minWidth: 0, overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap",
                               fontSize: "var(--fs-2)", color: "var(--muted-2)",
                               fontFamily: mono ? "var(--mono)" : undefined }}>
                  {r.hint}
                </span>
              )}
            </>)} />
        </AnchoredDropdown>
      )}
    </div>
  );
}

export function ParentField({ rows, self, value, onChange, placeholder,
                              onCreate }: {
  rows: ParentRow[];
  /** The row being edited — null while creating, when nothing is a loop. */
  self: number | null;
  value: number | null;
  onChange: (id: number | null) => void;
  placeholder?: string;
  /** Make one from what was typed and answer with its id. Without it the
   *  field offers only what exists — which is what sent somebody to the other
   *  tab to add the parent and back again. */
  onCreate?: (label: string) => Promise<number | null>;
}) {
  const t = useT();
  const [editing, setEditing] = React.useState(false);
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const ref = React.useRef<HTMLInputElement>(null);

  const banned = React.useMemo(() => descendantsOf(rows, self), [rows, self]);
  const chosen = rows.find((r) => r.id === value) ?? null;
  const needle = text.trim();
  const choices = React.useMemo<(ParentChoice & { id: number })[]>(() =>
    rows.filter((r) => !banned.has(r.id))
      .map((r) => ({ id: r.id, name: String(r.id), label: r.label, hint: r.hint })),
    [rows, banned]);
  // Matched on the label AND the hint (an address is worth typing towards).
  const shown = rankTagMatches(choices, needle, [], SUGGEST_CAP,
    (r) => `${r.label} ${r.hint ?? ""}`);
  // MAKE ONE, offered only where nothing carries that name exactly.
  const canCreate = !!onCreate && !!needle
    && !rows.some((r) => r.label.toLowerCase() === needle.toLowerCase());

  const pick = (id: number | null) => { onChange(id); setEditing(false); setText(""); };
  const make = async () => {
    if (busy || !onCreate) return;
    setBusy(true);
    try {
      const made = await onCreate(needle);
      if (made != null) pick(made);
      else setEditing(false);
    } finally { setBusy(false); }
  };
  const list = useSuggestList<ParentChoice & { id: number }>({
    matches: shown, create: canCreate ? needle : null,
    onPick: (row) => {
      if (row.kind === "create") void make();
      else if (row.kind === "match") pick(row.item.id);
    },
    input: { onCancel: () => setEditing(false), onBlur: () => setEditing(false) },
  });

  // The chain above it, so the field says what it is really claiming: a place
  // put in Tokyo is also in Japan, and only the line shows that.
  const chain: string[] = [];
  for (let at = chosen; at; ) {
    chain.push(at.label);
    const up: ParentRow | null =
      at.parent_id != null ? rows.find((r) => r.id === at!.parent_id) ?? null : null;
    if (!up || chain.length > 8) break;
    at = up;
  }

  if (chosen && !editing) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    minHeight: 32 }}>
        <span style={{
          display: "flex", alignItems: "center", gap: 6, minWidth: 0,
          padding: "5px 8px", borderRadius: "var(--r-4)", background: "var(--panel-2)",
          border: "1px solid var(--border)", fontSize: "var(--fs-3)",
        }}>
          <Icon name="subdirectory_arrow_right" size={14} color="var(--muted-2)" />
          <span style={{ minWidth: 0, overflow: "hidden",
                         textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {chain.join(" · ")}
          </span>
          <span onClick={() => onChange(null)} title={t("Remove")}
                style={{ display: "flex", cursor: "pointer",
                         color: "var(--muted-2)" }}>
            <Icon name="close" size={13} />
          </span>
        </span>
        <span onClick={() => { setText(""); setEditing(true); }}
              title={t("Change")}
              style={{ display: "flex", cursor: "pointer", color: "var(--muted-2)" }}>
          <Icon name="edit" size={14} />
        </span>
      </div>
    );
  }
  return (
    <ParentPicker list={list} text={text} onText={setText} inputRef={ref}
      busy={busy} placeholder={placeholder ?? t("Not inside anything")} />
  );
}

/** THE REMOTE, NAME-VALUED FORM — a tag set's own records, searched on the
 *  server. The field IS the value: what is typed is a tag name and leaving
 *  it typed means it (a picked row is the shortcut, never the only way
 *  in), so the blur commits. `search` answers the fragment; `onCreate`
 *  makes a record the set lacks and answers with its name. */
export function RemoteParentField({ value, onChange, search, searchKey,
                                    onCreate, placeholder, normalize }: {
  value: string;
  onChange: (name: string) => void;
  search: (q: string) => Promise<ParentChoice[]>;
  /** What the search is over — part of the query key. */
  searchKey: readonly unknown[];
  onCreate?: (name: string) => Promise<string | null>;
  placeholder?: string;
  /** The field's rule for what is typed (a tag name's). */
  normalize: { input: (s: string) => string; name: (s: string) => string };
}) {
  const [q, setQ] = React.useState(value);
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => { setQ(value); }, [value]);
  const ref = React.useRef<HTMLInputElement>(null);
  const needle = useDebouncedValue(q.trim(), tagDebounceMs(q));
  const searchRef = React.useRef(search);
  searchRef.current = search;
  const { data, isFetching, isPlaceholderData } = useQuery({
    queryKey: ["parent-search", ...searchKey, needle],
    queryFn: () => searchRef.current(needle),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
  const rows = (data ?? []).filter((r) => r.name !== value);
  const typed = normalize.name(q);
  // A CREATE ROW only where the fragment is a name the set does not have as
  // one of these — the tag autocomplete's own rule, one catalog along.
  const create = !!onCreate && typed && !(data ?? []).some((r) => r.name === typed)
    ? typed : null;
  const commit = (name: string) => { onChange(name); setQ(name); list.dismiss(); };
  const make = async (name: string) => {
    if (busy || !onCreate) return;
    setBusy(true);
    try {
      const made = await onCreate(name);
      if (made != null) commit(made);
    } finally { setBusy(false); }
  };
  const list = useSuggestList<ParentChoice>({
    matches: rows, create,
    settled: needle === q.trim() && !isFetching && !isPlaceholderData,
    onPick: (r) => {
      if (r.kind === "create") void make(r.name);
      else if (r.kind === "match") commit(r.item.name);
    },
    // COMMIT ON THE WAY OUT: the field's value is a tag name and what was
    // typed is one, so leaving it typed means it.
    input: { onBlur: () => onChange(normalize.name(q)), onCommitTyped: () => commit(typed) },
  });
  return (
    <ParentPicker list={list} text={q} onText={(v) => setQ(normalize.input(v))}
      inputRef={ref} busy={busy} placeholder={placeholder} mono />
  );
}
