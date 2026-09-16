/** A group header row: the All/Any/None combinator plus the segmented control
 *  (whose − removes the group, ( ) adds a nested group, + adds a row inside). */
import React from "react";
import { Group } from "./tree";
import { RowActions, selectStyle } from "./builderParts";

type Combinator = "all" | "any" | "none";

function toCombinator(g: Group): Combinator {
  if (g.neg) return "none";
  return g.op === "or" ? "any" : "all";
}

export function GroupHeader({
  node, onChange, onRemove, onAddRow, onAddGroup,
}: {
  node: Group;
  onChange: (next: Group) => void;
  onRemove: () => void;
  onAddRow: () => void;
  onAddGroup: () => void;
}) {
  const setCombinator = (c: Combinator) => {
    if (c === "all") onChange({ ...node, op: "and", neg: false });
    else if (c === "any") onChange({ ...node, op: "or", neg: false });
    else onChange({ ...node, op: "or", neg: true });
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "4px 0" }}>
      <select value={toCombinator(node)} onChange={(e) => setCombinator(e.target.value as Combinator)} style={selectStyle}>
        <option value="all">All</option>
        <option value="any">Any</option>
        <option value="none">None</option>
      </select>
      <span style={{ fontSize: "var(--fs-3)", fontWeight: 500, color: "var(--muted)" }}>of the following are true</span>
      <div style={{ flex: 1 }} />
      <RowActions onRemove={onRemove} onAddGroup={onAddGroup} onAddRow={onAddRow} removeTitle="Remove group" />
    </div>
  );
}
