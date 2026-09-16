/** The TREE ROW, and the two types its drag speaks in.
 *
 *  ONE ROW FOR TWO TREES. The Tags tab's left column is the same column
 *  whichever pill is picked: the LIBRARY's categories (`Tag.category_id`)
 *  and an imported SET's (`TagSetEntry.category_id`) are the same
 *  `tag_set_categories` rows, so one row implementation, one set of drag
 *  zones and one indent rule serve both — and the fixed rows above them
 *  (Everything, the record kinds, Uncategorized) are this row with nothing
 *  to open.
 *
 *  It closes over nothing: everything it draws and every gesture it answers
 *  arrives as a prop, which is what let it move out of the Sets tab without
 *  taking that tab's state with it. */
import React from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { Row } from "../../shared/Row";
import { IconButton } from "../../shared/IconButton";

import { compactCount } from "../format";
import { useT } from "../i18n";
import { Icon } from "../../shared/Icon";
import { Mark } from "./Mark";
import type { useRowSelect } from "./shared/useRowSelect";

/** The tree rows' indent: a small gutter, then 14 px a level. */
export const TREE_GUTTER = 6, TREE_STEP = 14;
export const treeIndent = (depth: number) => TREE_GUTTER + depth * TREE_STEP;

/** The id the Uncategorized row wears while a drop hangs over it — no
 *  category has one, so the ONE `dropAt` slot serves both the tree's rows
 *  and this fixed one. */
export const LOOSE_DROP = -1;

/** The sidebar's record rows, in the order the Tags tab's own sub-tabs went.
 *  `person` for the subject, the glyph the items tag list has always used
 *  for one. */
export const RECORD_ROWS: Array<[string, string, string]> = [
  ["subject", RECORD_ICON.subject, "Subjects"],
  ["place", "place", "Places"],
  ["event", RECORD_ICON.event, "Events"],
];

export type DropZone = "before" | "after" | "into";

export interface RowDrag {
  dragging: boolean;
  /** Where a carried category would land on THIS row, drawn as a line
   *  above or below it or a tint over it. */
  zone: DropZone | null;
  /** This row is the category the drop would land INSIDE — rung so the
   *  line's depth is not the only thing saying so. */
  parent?: boolean;
  /** Absent on a row that only TAKES drops — the Uncategorized row, and
   *  every category row while entries are being carried. */
  onDragStart?: (e: React.DragEvent) => void;
  onDragEnd: () => void;
  onDragOver: (e: React.DragEvent<HTMLDivElement>) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}

export function TreeRow({ depth, kids, open, selected, icon, label, count, hidden, rowProps,
                   joinAbove, joinBelow, onClick, onToggle, toggleTitle,
                   onMenu, drag, q, catId }: {
  /** The category this row is, for the scroll that follows a jump into the
   *  tree. Absent on the two fixed rows, which are always in view. */
  catId?: number;
  depth: number; kids: boolean; open: boolean; selected: boolean;
  /** The row above / below is picked too, so the tint runs into it and the
   *  corners on that side are square. */
  joinAbove?: boolean; joinBelow?: boolean;
  icon: string; label: string; count?: number;
  /** What the tree is being searched for, LIT in the label — the entry
   *  list's `Mark`, since both lists narrow by the same kind of typing. */
  q?: string;
  /** Kept out of the autocomplete — said on the row that carries the flag,
   *  never on the rows under it: what a sub-category inherits is the effect,
   *  and a crossed-out eye on each of them would read as five decisions. */
  hidden?: boolean;
  /** `useRowSelect`'s handlers, on the category rows only — the two fixed
   *  rows are filters and nothing selects them. Its own `onClick` is called
   *  by the caller's, which then decides whether the click also narrows. */
  rowProps?: Omit<ReturnType<ReturnType<typeof useRowSelect>["props"]>, "onClick">;
  onClick: (e: React.MouseEvent) => void;
  /** The chevron. Takes the EVENT, because the gesture has a modifier:
   *  alt/option opens or shuts the whole subtree, the library sidebar's
   *  own rule (`GroupTree`). */
  onToggle?: (e: React.MouseEvent) => void;
  /** What the chevron says it does, where a host has a modifier on it. */
  toggleTitle?: string;
  /** The category rows drag as a whole and take drops in three zones; the
   *  fixed rows pass none. */
  drag?: RowDrag;
  /** Opens the row's menu at the pointer — from the ⋯ that stands in for
   *  the count on hover (the library sidebar's `row-actions`/`row-count`
   *  swap, so nothing is reserved beside the count) and from a right-click
   *  anywhere on the row. */
  onMenu?: (e: React.MouseEvent) => void;
}) {
  const t = useT();
  return (
    // `hoverable`: the class `tokens.css` reveals `.row-action-fixed` under.
    // These rows said `row-hover`, a class no stylesheet knows, so the ⋯ on
    // a category (and on an entry) was never shown at all — "allow editing
    // and removing" was the report, and the menus were there the whole time.
    // THE WHOLE ROW DRAGS — the library sidebar's group rows' shape (a grip
    // revealed on hover was here for a round, and had to fight the reveal
    // rules to stay visible as the drag source); a press on the name still
    // selects, since a drag only begins once the pointer moves.
    <Row {...rowProps} onClick={onClick} onContextMenu={onMenu}
         data-tagset-cat={catId}
         draggable={!!drag?.onDragStart}
         onDragStart={drag?.onDragStart} onDragEnd={drag?.onDragEnd}
         onDragOver={drag?.onDragOver} onDragLeave={drag?.onDragLeave} onDrop={drag?.onDrop}
         selected={selected} joinAbove={joinAbove} joinBelow={joinBelow}
         // A row being dropped INTO wears the tint without being picked.
         base={drag?.zone === "into" ? "var(--accent-dim)" : "transparent"}
         style={{ position: "relative", padding: `0 8px 0 ${treeIndent(depth)}px`,
                  color: "var(--text)",
                  opacity: drag?.dragging ? 0.5 : 1,
                  boxShadow: drag?.parent ? "inset 0 0 0 1px var(--accent)" : undefined }}>
      {drag && (drag.zone === "before" || drag.zone === "after") && (
        // THE DROP LINE STARTS AT THE DEPTH THE DROP WOULD LAND AT — a
        // sibling of this row, so at this row's own indent — with a dot at
        // its head: a line across the whole row said "here" and not "how
        // deep", and the parent the line belongs to is rung (`parent`).
        <span style={{ position: "absolute", left: treeIndent(depth) - 6, right: 6, height: 2,
                       [drag.zone === "before" ? "top" : "bottom"]: -1,
                       background: "var(--accent)", borderRadius: 1, pointerEvents: "none" }}>
          <span style={{ position: "absolute", left: -3, top: -3, width: 8, height: 8,
                         borderRadius: 4, background: "var(--accent)" }} />
        </span>
      )}
      <span onClick={(e) => { if (onToggle) { e.stopPropagation(); onToggle(e); } }}
            title={kids ? toggleTitle : undefined}
            style={{ width: 14, display: "flex", justifyContent: "center", marginRight: -2,
                     visibility: kids ? "visible" : "hidden", color: "var(--muted-2)" }}>
        <Icon name={open ? "expand_more" : "chevron_right"} size={16} />
      </span>
      <Icon name={icon} size={15} color={selected ? "var(--selected-text)" : "var(--accent)"} />
      <span style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}><Mark text={label} q={q ?? ""} /></span>
      {hidden && (
        <span title={t("Hidden from the autocomplete")}
              style={{ display: "flex", flex: "0 0 auto" }}>
          <Icon name="visibility_off" size={14}
                color={selected ? "var(--selected-text)" : "var(--muted-2)"} />
        </span>
      )}
      <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", flex: "0 0 auto" }}>
        {count != null && (
          <span className={onMenu ? "row-count" : undefined}
                style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted-3)" }}>
            {compactCount(count)}
          </span>
        )}
        {onMenu && (
          <span className="row-actions">
            <IconButton icon="more_horiz" size={20} reveal="hover" title={t("More actions")}
                  onClick={onMenu} />
          </span>
        )}
      </span>
    </Row>
  );
}
