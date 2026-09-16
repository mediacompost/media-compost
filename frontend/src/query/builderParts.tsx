/** Shared building blocks for the visual query builder: styles, the per-row
 *  segmented action control, and a small closed-list autocomplete input. */
import React, { useEffect, useRef, useState } from "react";
import { PlusMinus } from "../shared/PlusMinus";
import { Icon } from "../shared/Icon";
import { AnchoredDropdown, useAnchorRect } from "../shared/AnchoredDropdown";
import { tagDebounceMs, useDebouncedValue } from "../shared/useDebounced";
import { useSuggestList } from "../shared/useSuggestList";
import { SUGGEST_CAP } from "../shared/suggestRows";

// Every row control is the same height as the − ( ) + capsule (30px).
const ROW_H = 30;

export const selectStyle: React.CSSProperties = {
  flex: "none", height: ROW_H, boxSizing: "border-box", background: "var(--panel-2)",
  border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)", padding: "0 8px",
  color: "var(--text)", fontSize: "var(--fs-3)", fontWeight: 600, outline: "none", cursor: "pointer",
};

export const fieldWrap: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 7, height: ROW_H, boxSizing: "border-box",
  background: "var(--bg)", border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)", padding: "0 10px",
};

export const inputStyle: React.CSSProperties = {
  flex: 1, minWidth: 0, background: "transparent", border: "none", padding: 0,
  color: "var(--text)", fontSize: "var(--fs-4)", fontWeight: 600, outline: "none",
};

/** The `− ( ) +` capsule to the right of every row and group header. */
export function RowActions({
  onRemove, onAddGroup, onAddRow, removeTitle = "Remove this row", canRemove = true,
}: {
  onRemove: () => void;
  onAddGroup: () => void;
  onAddRow: () => void;
  removeTitle?: string;
  canRemove?: boolean;
}) {
  const seg: React.CSSProperties = {
    width: 32, display: "flex", alignItems: "center", justifyContent: "center",
    background: "transparent", border: "none", color: "var(--muted)", cursor: "pointer",
  };
  return (
    <div style={{
      flex: "none", display: "inline-flex", alignItems: "stretch", height: 30,
      border: "1px solid var(--border-strong)", borderRadius: "var(--r-round)", overflow: "hidden",
      background: "var(--panel-2)",
    }}>
      <button className={canRemove ? "hoverable" : undefined} onClick={canRemove ? onRemove : undefined}
        disabled={!canRemove} title={canRemove ? removeTitle : undefined}
        style={{ ...seg, cursor: canRemove ? "pointer" : "default",
          color: canRemove ? "var(--muted)" : "var(--muted-3)", opacity: canRemove ? 1 : 0.5 }}>
        <PlusMinus kind="minus" size={16} />
      </button>
      <button className="hoverable" onClick={onAddGroup} title="Add a nested group"
        style={{ ...seg, borderLeft: "1px solid var(--border-strong)", borderRight: "1px solid var(--border-strong)" }}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor"
          strokeWidth="1.6" strokeLinecap="round">
          <line x1="3" y1="5.5" x2="13" y2="5.5" />
          <line x1="7" y1="10.5" x2="13" y2="10.5" />
        </svg>
      </button>
      <button className="hoverable" onClick={onAddRow} title="Add a row" style={seg}>
        <PlusMinus kind="plus" size={16} />
      </button>
    </div>
  );
}

export interface AcOption { name: string; hint?: string; }

/** A closed-list autocomplete text input: typing filters `options`; picking a
 *  suggestion (click or Enter) calls `onCommit`. Keeps focus/behaviour close to
 *  the design (mousedown-commit, arrow nav, Escape closes). */
export function Autocomplete({
  value, placeholder, options = [], fetchOptions, onChange, onCommit,
  allowFreeText = false,
  emptyLabel = "No matches", width, prefix, bare = false,
}: {
  value: string;
  placeholder?: string;
  options?: AcOption[];
  /** Opt-in remote mode: fetch what matches the typed fragment (debounced,
   *  and once on open with the fragment as it stands — an enumerated value
   *  dropdown shows its values before anything is typed) instead of
   *  filtering an `options` catalog the owner had to hold whole. `options`
   *  is ignored while this is set. */
  fetchOptions?: (q: string) => Promise<AcOption[]>;
  onChange: (v: string) => void;
  onCommit: (name: string) => void;
  allowFreeText?: boolean;
  emptyLabel?: string;
  width?: number | string;
  // Rendered inside the field container, before the input (e.g. a tag's
  // positive/negative toggle) — so there is a single bordered field, not two.
  prefix?: React.ReactNode;
  // When the input already sits inside a bordered container (e.g. the link
  // capsule field), render without the field's own border/height.
  bare?: boolean;
}) {
  const q = value.toLowerCase();
  // Remote rows for the fetch mode. The callback rides in a ref so an inline
  // closure never refires the effect; stale replies lose to newer ones by
  // sequence number, and a failed fetch keeps whatever the list had.
  const [remote, setRemote] = useState<AcOption[]>([]);
  const fetchRef = useRef(fetchOptions);
  fetchRef.current = fetchOptions;
  const seqRef = useRef(0);
  const remoteMode = !!fetchOptions;
  const debounced = useDebouncedValue(q, tagDebounceMs(q));
  const source = remoteMode ? remote : options;
  // In remote mode the rows were matched against the DEBOUNCED fragment;
  // re-applying the current one keeps in-flight keystrokes honest.
  const matches = source.filter((o) => o.name.toLowerCase().includes(q)).slice(0, SUGGEST_CAP);

  const commit = (name: string) => { onCommit(name); list.dismiss(); };
  // THE LIST IS THE SHARED HOOK'S — the highlight, the arrows, Enter, the
  // two-stage Escape, the blur (`shared/useSuggestList`; the query builder
  // may not import the app's renderer, so the rows are drawn here).
  const list = useSuggestList<AcOption>({
    matches, create: null,
    onPick: (row) => { if (row.kind === "match") commit(row.item.name); },
    input: {
      onCommitTyped: () => { if (allowFreeText && value.trim()) commit(value.trim()); },
      blurMs: 120,
    },
  });
  const showList = list.focused && !list.dismissed;
  useEffect(() => {
    const fetch = fetchRef.current;
    if (!remoteMode || !fetch || !showList) return;
    const seq = ++seqRef.current;
    void fetch(debounced)
      .then((rows) => { if (seqRef.current === seq) setRemote(rows); })
      .catch(() => { /* keep whatever the list had */ });
  }, [debounced, showList, remoteMode]);

  const anchorRef = useRef<HTMLDivElement>(null);
  const rect = useAnchorRect(anchorRef, showList);

  return (
    <div ref={anchorRef} style={{ position: "relative", flex: width ? "none" : 1, minWidth: 0, width }}>
      <span style={bare ? { display: "flex", alignItems: "center", flex: 1, minWidth: 0 } : fieldWrap}>
        {prefix}
        <input
          value={value}
          placeholder={placeholder}
          onChange={(e) => { onChange(e.target.value); list.undismiss(); }}
          {...list.inputProps}
          spellCheck={false}
          style={inputStyle}
        />
      </span>
      {/* Portalled to the body so the builder's overflow (its open/close
          animation clips content) never cuts off the suggestions. */}
      {showList && (
        <AnchoredDropdown rect={rect} minWidth={Math.max(180, rect?.width ?? 0)}>
          <div {...list.listProps}>
            {list.rows.map((row, i) => row.kind !== "match" ? null : (
              <button
                key={row.item.name}
                {...list.rowProps(i)}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  // A MINIMUM between the two halves, or a long name runs into
                  // its own secondary text and the row reads as one string.
                  gap: 12, width: "100%",
                  boxSizing: "border-box", background: i === list.hi ? "var(--accent-dim)" : "transparent",
                  border: "none", borderRadius: "var(--r-2)", padding: "7px 9px", cursor: "pointer", textAlign: "left",
                }}
              >
                {/* The name yields last: it is what the row is FOR, so the
                    hint is what gives way when there is not room for both. */}
                <span style={{ fontSize: "var(--fs-3)", color: "var(--text)",
                               flex: "0 1 auto", minWidth: 0, overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.item.name}</span>
                {row.item.hint != null && (
                  <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)",
                                 flex: "0 20 auto", minWidth: 0, overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.item.hint}</span>
                )}
              </button>
            ))}
            {matches.length === 0 && (
              <div style={{ padding: "9px 10px", fontSize: "var(--fs-3)", color: "var(--muted-2)", textAlign: "center" }}>
                {emptyLabel}
              </div>
            )}
          </div>
        </AnchoredDropdown>
      )}
    </div>
  );
}

