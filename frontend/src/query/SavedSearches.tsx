/** The saved-searches popover, opened from the search bar's magnifier menu.
 *  Lists saved queries (apply / inline rename / delete) and can save the current
 *  one. Backed by the settings endpoints; queries are stored as opaque strings. */
import React, { useEffect, useRef, useState } from "react";
import { SectionHeading } from "../shared/SectionHeading";
import { IconButton } from "../shared/IconButton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, SavedSearch } from "../shared/api";
import { Icon } from "../shared/Icon";
import { useMenuDismiss } from "../shared/useMenuDismiss";
import { normalizeRoot } from "./edit";
import { serialize, tryParse } from "./tree";

const canon = (q: string): string => {
  const g = tryParse(q);
  return g ? serialize(normalizeRoot(g)) : q;
};

export function SavedSearches({
  currentQuery, onApply, onClose, anchor,
}: {
  currentQuery: string;
  onApply: (query: string) => void;
  onClose: () => void;
  /** The button that opened it: a press on it is the caller's toggle, not
   *  a press outside. */
  anchor?: React.RefObject<HTMLElement | null>;
}) {
  const qc = useQueryClient();
  const { data: saved = [] } = useQuery({ queryKey: ["saved-searches"], queryFn: api.savedSearches });
  const save = useMutation({
    mutationFn: (list: SavedSearch[]) => api.putSavedSearches(list),
    onSuccess: (list) => qc.setQueryData(["saved-searches"], list),
  });

  const [renameIdx, setRenameIdx] = useState<number | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const renameRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (renameIdx != null) renameRef.current?.focus(); }, [renameIdx]);

  const cur = canon(currentQuery);
  const alreadySaved = currentQuery.trim() !== "" && saved.some((s) => canon(s.query) === cur);

  const commitRename = () => {
    if (renameIdx == null) return;
    const v = renameVal.trim();
    const next = saved.map((s, i) => (i === renameIdx && v ? { ...s, name: v } : s));
    save.mutate(next);
    setRenameIdx(null);
  };
  const del = (i: number) => save.mutate(saved.filter((_, j) => j !== i));
  const saveCurrent = () => {
    const next = [...saved, { name: "New search", query: currentQuery }];
    save.mutate(next);
    setRenameIdx(next.length - 1);
    setRenameVal("New search");
  };

  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  const panel = useRef<HTMLDivElement>(null);
  useMenuDismiss(true, onClose, { within: [panel, ...(anchor ? [anchor] : [])] });
  return (
    <>
      <div ref={panel} style={{ position: "absolute", left: 8, top: "calc(100% + 6px)", zIndex: 40, width: 300,
        background: "var(--surface-float)", border: "1px solid var(--menu-border)", borderRadius: "var(--r-7)",
        padding: 7, boxShadow: "var(--shadow-3)", display: "flex", flexDirection: "column" }}>
        <SectionHeading sm style={{ padding: "4px 6px 6px" }}>Saved searches</SectionHeading>
        <div className="ac-list" style={{ maxHeight: 216, overflow: "auto", display: "flex", flexDirection: "column", gap: 1 }}>
          {saved.length === 0 && (
            <div style={{ padding: "8px 8px 10px", fontSize: "var(--fs-3)", color: "var(--muted-2)" }}>No saved searches yet.</div>
          )}
          {saved.map((s, i) => {
            const active = canon(s.query) === cur && cur !== "";
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 2, minHeight: 44,
                background: active ? "var(--accent-dim)" : "transparent", borderRadius: "var(--r-3)" }}>
                {renameIdx === i ? (
                  <>
                    <input ref={renameRef} value={renameVal} onChange={(e) => setRenameVal(e.target.value)}
                      onBlur={commitRename}
                      onKeyDown={(e) => { if (e.key === "Enter") commitRename(); else if (e.key === "Escape") setRenameIdx(null); }}
                      placeholder="Search name" spellCheck={false}
                      style={{ flex: 1, minWidth: 0, margin: 2, background: "var(--bg)", border: "1px solid var(--accent)",
                        borderRadius: "var(--r-3)", padding: "6px 8px", color: "var(--text)", fontSize: "var(--fs-3)", fontWeight: 600, outline: "none" }} />
                    <IconButton icon="check" size={26} glyph={16} tone="accent" onMouseDown={(e) => { e.preventDefault(); commitRename(); }} title="Done" style={{ flex: "none" }} />
                  </>
                ) : (
                  <>
                    <button className="hoverable" onClick={() => onApply(s.query)}
                      style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2, textAlign: "left",
                        background: "transparent", border: "none", borderRadius: "var(--r-3)", padding: "6px 8px", cursor: "pointer" }}>
                      <span style={{ fontSize: "var(--fs-3)", fontWeight: 600, color: "var(--text)" }}>{s.name}</span>
                      <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", fontFamily: "var(--mono)",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.query}</span>
                    </button>
                    <IconButton icon="edit" size={26} glyph={14} onClick={() => { setRenameIdx(i); setRenameVal(s.name); }} title="Rename" style={{ flex: "none" }} />
                    <IconButton icon="close" size={26} glyph={15} onClick={() => del(i)} title="Delete saved search" style={{ flex: "none" }} />
                  </>
                )}
              </div>
            );
          })}
        </div>
        {currentQuery.trim() !== "" && !alreadySaved && (
          <div style={{ flex: "none" }}>
            <div style={{ height: 1, background: "var(--border)", margin: "6px 6px" }} />
            <button className="hoverable" onClick={saveCurrent}
              style={{ display: "flex", alignItems: "center", gap: 9, width: "100%", boxSizing: "border-box",
                textAlign: "left", background: "transparent", border: "none", borderRadius: "var(--r-3)", padding: "7px 8px",
                cursor: "pointer", color: "var(--text)" }}>
              <Icon name="add" size={16} color="var(--accent)" />
              <span style={{ fontSize: "var(--fs-3)", fontWeight: 600 }}>Save current search</span>
            </button>
          </div>
        )}
      </div>
    </>
  );
}
