/** What the picture SAYS — the detected text, one row per block.
 *
 * A caption is what somebody said about the picture; this is what an OCR
 * engine read off it, box and all, corrected by a person and safe against a
 * re-run (the reconciliation rule lives server-side).
 *
 * TWO ENGINES' READINGS OF ONE PAGE ARE A DROPDOWN, NOT TWO SECTIONS: the
 * question is "what does the page say", and two answers stacked say it
 * twice — you READ one reading and switch to compare. Only the active
 * engine's regions show, here and on the annotator's canvas (the host owns
 * the choice there, `activeEngine`/`onActiveEngine`). Hand-drawn regions
 * belong to no engine and ride along with whichever is active — there is no
 * "Added by hand" section, and the section header (the dropdown) is also
 * why the rows carry no "Read by …" line of their own.
 *
 * A ROW IS A LINE, and the line's whole text is what you correct: click the
 * text itself; Enter commits a line, ⌘/Ctrl+Enter a block (a bubble's text
 * has lines in it, so Enter is a character there — and because Enter is not
 * the way out, the field carries a tick and a cross). The engine's WORD and
 * character boxes are kept and used — they are the removal mask's smallest
 * unit and the outlines the annotator draws under a picked row — but they
 * are not edited here: a row of little fields where a sentence belongs made
 * correcting one line a word at a time.
 *
 * CLICKING THE TEXT EDITS; clicking anywhere else in the row SELECTS it. So
 * the text is an inline span rather than a block filling the row — as a
 * block, the empty space to the right of a short line was still "the text",
 * and a click meant for the selection opened the editor.
 *
 * Top-level rows reorder by their drag handle, within the active engine's
 * list; the server takes the FULL sibling order, so the drop recomputes it
 * around the untouched engines' rows. A run of ADJACENT picked rows can also
 * be flipped end for end from the selection bar — a page read bottom-up (or
 * a right-to-left column order read left-to-right) is one gesture away from
 * right, where dragging it row by row is not.
 */
import React, { useMemo, useRef, useState } from "react";
import { dropHalf, type DropHalf } from "../../shared/useDragRow";
import { useInlineEdit } from "../../shared/useInlineEdit";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ItemDetail, TextRegion } from "../api";
import { Icon } from "../../shared/Icon";
import { useT, useTn } from "../i18n";
import { useReportSelection } from "../../shared/SelectionBar";
import { RowAction, RowMenu } from "../../shared/RowMenu";
import { FloatingTextInPicture } from "./shared/TextInPicture";
import { useRowSelect } from "./shared/useRowSelect";
import { useUndoRun } from "./shared/useUndoBar";
import {
  RenderRow, childrenAreRows, dismissedRoots, engineOf, enginesOf,
  flattenText, liveRoots, regionText,
} from "../text/regions";
import { rememberEngine, useChosenEngine } from "../text/engineChoice";

/** The row key the selection uses — `t:` so a shared selection space cannot
 *  collide with another section's keys. */
export const textRowKey = (id: number) => `t:${id}`;

/** A word the engine was unsure of gets a dotted underline — a hint on the
 *  one thing it is about, never amber (amber means "a machine said this and
 *  nobody agreed", which is true of every undismissed region here, and a
 *  colour that is true of the whole list says nothing). */
const UNSURE = 0.75;

export function TextSection({
  itemId, detail, readOnly, topAction, onChange,
  selectedKeys, onSelectedKeys, autoEditId, onAutoEditDone,
  activeEngine, onActiveEngine, onHoverRegion,
}: {
  itemId: number | null;
  detail: ItemDetail | null;
  readOnly?: boolean;
  /** "Detect text", at the top — where Detect faces and Generate tags sit. */
  topAction?: React.ReactNode;
  onChange: () => void;
  /** Passing BOTH hands the row selection to the host — the annotator, whose
   *  canvas boxes are the same rows. */
  selectedKeys?: string[];
  onSelectedKeys?: (keys: string[]) => void;
  /** A region whose editor should open the moment its row appears — the box
   *  the annotator just drew, focused and EMPTY (you are transcribing, not
   *  replacing). */
  autoEditId?: number | null;
  onAutoEditDone?: () => void;
  /** Passing BOTH hands the detector choice to the host — the annotator,
   *  whose canvas draws only the active engine's boxes. */
  activeEngine?: string | null;
  onActiveEngine?: (model: string) => void;
  /** Where the host has the PICTURE on screen (the annotator), hovering a
   *  row's box glyph tells it to light that box up there instead of opening
   *  a crop preview — the picture is right beside the list, and a 240 px
   *  thumbnail of a region that is already visible answers a question
   *  nobody asked. */
  onHoverRegion?: (region: TextRegion | null) => void;
}) {
  const tr = useT();
  const qc = useQueryClient();
  const undoRun = useUndoRun();
  const { data: tree } = useQuery({
    queryKey: ["text", itemId],
    queryFn: () => api.itemText(itemId as number),
    enabled: itemId != null,
  });
  // Model labels come from the registry the backend already serves — a local
  // name table would be a second copy that drifts. The raw key is the
  // fallback, which is also why a retired model still names itself.
  // WHAT A MODEL IS CALLED, in the words its own action row uses. A spec's
  // `name` is the family ("Text (RapidOCR)") and its `variant` is the answer
  // ("Multilingual"), and the Detect menus have always shown the variant
  // under a family heading — so a dropdown spelling out "Text (RapidOCR) —
  // Multilingual" was a second name for one thing, and the longer one. The
  // variant alone where there is one, the name where there is not.
  const { data: mlModels } = useQuery({
    queryKey: ["ml-models"], queryFn: api.mlModels, staleTime: 60_000,
  });
  const modelLabel = useMemo(() => {
    const names = new Map<string, string>();
    for (const t of mlModels?.tasks ?? []) {
      for (const m of t.models) {
        names.set(m.id, m.variant || m.name);
      }
    }
    return (key: string) => names.get(key) ?? key;
  }, [mlModels]);

  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<{ id: number; draft: string } | null>(null);
  const [hovered, setHovered] = useState<{ region: TextRegion; rect: DOMRect } | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  // Reorder drag: which visible row is being carried, and where it would
  // land (the sequence member list's shape).
  const rowDrag = useRef<number | null>(null);
  const rowHalf = useRef<DropHalf>("before");
  const [dropAt, setDropAt] = useState<number | null>(null);

  const roots = useMemo(() => liveRoots(tree ?? []), [tree]);
  const engines = useMemo(() => enginesOf(roots), [roots]);
  // The detector on show. Controlled by the host (the annotator) when both
  // props are passed; otherwise the item's REMEMBERED choice — the same one
  // the annotator and the editor's text tool resolve, so a page opened in
  // another window shows the reading you were last looking at rather than
  // whichever engine happens to sort first.
  const remembered = useChosenEngine(itemId, engines);
  const picked = onActiveEngine ? (activeEngine ?? null) : null;
  const engine = picked != null && engines.includes(picked)
    ? picked : remembered;
  const setEngine = (model: string) => {
    rememberEngine(itemId, model);
    onActiveEngine?.(model);
  };
  // Tell the host what the fallback resolved to, so its canvas filter and
  // this list can never disagree about which reading is on show.
  React.useEffect(() => {
    if (onActiveEngine && engine && activeEngine !== engine) {
      onActiveEngine(engine);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine, activeEngine]);

  // The active engine's regions, with the hand-drawn ones riding along.
  const visibleRoots = useMemo(
    () => roots.filter((r) => !engineOf(r) || engineOf(r) === engine),
    [roots, engine]);
  const hidden = useMemo(
    () => dismissedRoots(tree ?? []).filter(
      (r) => !engineOf(r) || engineOf(r) === engine),
    [tree, engine]);
  // ONE derivation feeds the render AND the selection's key list, so a
  // shift-range picks the run the eye sees.
  const rows = useMemo(() => flattenText(visibleRoots, expanded),
                       [visibleRoots, expanded]);
  const byKey = useMemo(() => {
    const out = new Map<string, TextRegion>();
    const visit = (r: TextRegion) => {
      out.set(textRowKey(r.id), r);
      r.children.forEach(visit);
    };
    (tree ?? []).forEach(visit);
    return out;
  }, [tree]);

  const sel = useRowSelect(
    rows.map((r) => textRowKey(r.region.id)),
    onSelectedKeys ? { selected: selectedKeys ?? [], onChange: onSelectedKeys }
                   : undefined);

  // The freshly drawn box's editor opens as soon as its row exists.
  React.useEffect(() => {
    if (autoEditId == null) return;
    if (!rows.some((r) => r.region.id === autoEditId)) return;
    setEditing({ id: autoEditId, draft: "" });
    onAutoEditDone?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoEditId, rows.length]);

  /** The hover clears FIRST: a row that vanishes under the pointer never
   *  fires its mouseleave (`PeopleSection.refresh`'s lesson, and dismissing
   *  a block is exactly that). */
  const refresh = (rowsBack?: TextRegion[]) => {
    setHovered(null);
    if (rowsBack && itemId != null) qc.setQueryData(["text", itemId], rowsBack);
    else qc.invalidateQueries({ queryKey: ["text", itemId] });
    onChange();
  };

  const saveText = async (r: TextRegion, draft: string) => {
    setEditing(null);
    if (itemId == null) return;
    // A hand-drawn box with no text says nothing — committing it empty
    // deletes it rather than keeping an empty rectangle on the picture.
    if (!r.models.length && !draft.trim() && !r.text.trim()) {
      refresh(await api.deleteTextRegion(r.id));
      return;
    }
    // A save equal to the current text writes nothing — the touch would log
    // an event saying nothing happened.
    if (draft === regionText(r)) return;
    refresh(await api.updateTextRegion(r.id, { text: draft }));
  };

  /** The ✕ (and Escape). A hand-drawn box that HAS no text is deleted — the
   *  cancel was somebody changing their mind about drawing it. */
  const cancelEdit = async (r: TextRegion | undefined) => {
    setEditing(null);
    if (r && !r.models.length && !r.text.trim() && !r.children.length) {
      refresh(await api.deleteTextRegion(r.id));
    }
  };

  /** Provenance picks the verb: a DETECTED region is dismissed (the answer
   *  that sticks — a dismissal absorbs the next detection), a hand-drawn one
   *  is deleted, since nothing ever offered it. */
  const removeOne = (r: TextRegion) => void undoRun(
    r.models.length ? tr("Marked as not text") : tr("Deleted"),
    async () => {
      const back = r.models.length
        ? await api.updateTextRegion(r.id, { dismissed: true })
        : await api.deleteTextRegion(r.id);
      refresh(back);
    });

  const pickedRegions = sel.selected
    .map((k) => byKey.get(k))
    .filter((r): r is TextRegion => !!r);
  const allHand = pickedRegions.length > 0
    && pickedRegions.every((r) => !r.models.length);

  // A RUN of picked TOP-LEVEL rows, adjacent in the reading order, can be
  // flipped end for end. Adjacent because that is the whole of what
  // reversing means — turning over a stretch of the order — while a
  // scattered pick has no "between" to turn over, and moving each of them to
  // where another one was would be a shuffle nobody asked for.
  const reversible = useMemo(() => {
    const picked = new Set(sel.selected);
    const tops = rows.filter((r) => r.depth === 0)
      .map((r) => r.region.id);
    const at = tops.map((id, i) => picked.has(textRowKey(id)) ? i : -1)
      .filter((i) => i >= 0);
    if (at.length < 2) return null;
    if (at[at.length - 1] - at[0] !== at.length - 1) return null;  // a gap
    // Every picked row must be top-level, or the run is not what it looks
    // like (an expanded line inside a block is not part of that order).
    if (at.length !== sel.selected.length) return null;
    return at.map((i) => tops[i]);
  }, [sel.selected, rows]);

  const reverseSelected = () => {
    if (!reversible || itemId == null) return;
    void undoRun(tr("Reversed the order"), async () => {
      // The server takes the FULL sibling order, so the flip is applied
      // inside the whole list — the other engines' rows and the dismissed
      // ones keep their places, exactly as a drag does.
      const full = (tree ?? []).map((r) => r.id);
      const slots = full.map((id, i) => reversible.includes(id) ? i : -1)
        .filter((i) => i >= 0);
      const flipped = [...full];
      const ids = slots.map((i) => full[i]).reverse();
      slots.forEach((slot, i) => { flipped[slot] = ids[i]; });
      refresh(await api.reorderTextRegions(itemId, flipped));
    });
  };

  const removeSelected = () => {
    if (!pickedRegions.length) return;
    void undoRun(
      `${allHand ? tr("Removed") : tr("Marked as not text")} ${pickedRegions.length}`,
      async () => {
        let back: TextRegion[] | undefined;
        for (const r of pickedRegions) {
          back = r.models.length
            ? await api.updateTextRegion(r.id, { dismissed: true })
            : await api.deleteTextRegion(r.id);
        }
        sel.clear();
        refresh(back);
      });
  };

  useReportSelection("text", readOnly || itemId == null ? null : {
    count: sel.selected.length,
    total: rows.length,
    onSelectAll: sel.selectAll,
    onRemove: removeSelected,
    onClear: sel.clear,
    // The verb follows what it DOES: a hand-drawn selection is removed
    // outright, a detected one is marked as not text (dismissed, so the
    // next run does not re-offer it). Mixed picks read as the stronger
    // claim and still route per row.
    removeLabel: allHand ? tr("Remove") : tr("Not text"),
    removeIcon: allHand ? "delete" : "visibility_off",
    removeTitle: tr("Mark them as not text — the ones drawn by hand are deleted, since nothing offered them"),
    // Offered only for a run of adjacent rows — see `reversible`.
    extra: reversible ? {
      icon: "swap_vert",
      title: tr("Turn this run of rows end for end"),
      onClick: reverseSelected,
    } : undefined,
  });

  if (itemId == null || !detail) return null;

  const restoreHidden = (r: TextRegion) => void undoRun(
    tr("Restored"),
    async () => refresh(await api.updateTextRegion(r.id, { dismissed: false })));
  const deleteHidden = (r: TextRegion) => void undoRun(
    tr("Deleted"),
    async () => refresh(await api.deleteTextRegion(r.id)));

  /** Move the carried top-level row so it lands AT the target's place. The
   *  server wants the FULL sibling order (dismissed rows and the other
   *  engines' included), so the visible move is recomputed around them —
   *  their relative order never changes. */
  const commitReorder = async (fromId: number, toId: number, half: DropHalf) => {
    if (fromId === toId) return;
    const full = (tree ?? []).map((r) => r.id);
    const without = full.filter((id) => id !== fromId);
    const at = without.indexOf(toId);
    if (at < 0) return;
    // The lower half of a row lands AFTER it — this landed one short
    // whenever a region was dragged downward.
    without.splice(at + (half === "after" ? 1 : 0), 0, fromId);
    refresh(await api.reorderTextRegions(itemId, without));
  };

  const renderRows = (list: RenderRow[]) => list.map((row, idx) => (
    <TextRow
      key={row.region.id}
      row={row}
      readOnly={readOnly}
      selProps={sel.props(textRowKey(row.region.id))}
      picked={sel.has(textRowKey(row.region.id))}
      expanded={expanded.has(row.region.id)}
      onToggle={() => setExpanded((cur) => {
        const next = new Set(cur);
        if (next.has(row.region.id)) next.delete(row.region.id);
        else next.add(row.region.id);
        return next;
      })}
      editing={editing?.id === row.region.id ? editing : null}
      onEdit={(draft) => setEditing({ id: row.region.id, draft })}
      onDraft={(draft) => setEditing({ id: row.region.id, draft })}
      onSave={() => editing && void saveText(row.region, editing.draft)}
      onCancel={() => void cancelEdit(row.region)}
      onRemove={() => removeOne(row.region)}
      onHover={(rect) => {
        // With the picture on screen (the annotator) the host lights the box
        // up there; otherwise the crop preview is the only way to answer
        // "where is this?".
        if (onHoverRegion) onHoverRegion(rect ? row.region : null);
        else setHovered(rect ? { region: row.region, rect } : null);
      }}
      dragProps={row.depth === 0 && !readOnly ? {
        onDragStart: () => { rowDrag.current = row.region.id; },
        onDragEnd: () => { rowDrag.current = null; setDropAt(null); },
      } : undefined}
      dropProps={row.depth === 0 && !readOnly ? {
        onDragOver: (e: React.DragEvent) => {
          e.preventDefault();
          if (rowDrag.current != null) { setDropAt(idx); rowHalf.current = dropHalf(e); }
        },
        onDrop: (e: React.DragEvent) => {
          e.stopPropagation();
          const from = rowDrag.current;
          rowDrag.current = null;
          setDropAt(null);
          if (from != null) void commitReorder(from, row.region.id, rowHalf.current);
        },
      } : undefined}
      dropMarked={dropAt === idx}
    />
  ));

  return (
    <div>
      {topAction}
      {engines.length > 1 && (
        // Two engines read the page two ways; the dropdown says which
        // reading is on show — here AND on the annotator's canvas. One
        // engine needs no control.
        <select
          value={engine}
          onChange={(e) => setEngine(e.target.value)}
          title={tr("Show another model's reading")}
          style={{
            // The Detect text button above it is 32 px; a control directly
            // under one it belongs with, two pixels shorter, reads as a
            // mistake rather than as a different kind of thing.
            width: "100%", marginTop: 8, height: 32, padding: "0 8px",
            borderRadius: "var(--r-3)", border: "1px solid var(--border)",
            background: "var(--panel-2)", color: "var(--text-2)",
            fontSize: "var(--fs-3)",
          }}>
          {engines.map((m) => (
            <option key={m} value={m}>{modelLabel(m)}</option>
          ))}
        </select>
      )}
      {visibleRoots.length === 0 && hidden.length === 0 && (
        <div style={{ color: "var(--muted)", fontSize: "var(--fs-3)", padding: "6px 0" }}>
          {tr("Nothing read from this item yet.")}
        </div>
      )}
      {renderRows(rows)}
      {hidden.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <button
            onClick={() => setShowHidden((v) => !v)}
            style={{
              background: "none", border: "none", padding: 0,
              color: "var(--muted)", fontSize: "var(--fs-3)", cursor: "pointer",
              display: "flex", alignItems: "center", gap: 4,
            }}>
            <Icon name={showHidden ? "expand_more" : "chevron_right"} size={14} />
            {tr("Hidden text")} ({hidden.length})
          </button>
          {showHidden && hidden.map((r) => (
            <div key={r.id} style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "5px 6px", marginTop: 4, borderRadius: "var(--r-3)",
              border: "1px dashed var(--border)", opacity: 0.75,
            }}>
              <span
                onMouseEnter={(e) => setHovered({
                  region: r,
                  rect: (e.currentTarget as HTMLElement).getBoundingClientRect(),
                })}
                onMouseLeave={() => setHovered(null)}
                style={{ color: "var(--muted-2)", display: "flex" }}>
                <Icon name="crop_free" size={16} />
              </span>
              <span style={{
                flex: 1, fontSize: "var(--fs-3)", color: "var(--muted)",
                overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>{regionText(r) || "—"}</span>
              {!readOnly && (
                <>
                  <button onClick={() => restoreHidden(r)} style={hiddenBtn}>
                    {tr("It is text after all")}
                  </button>
                  <button onClick={() => deleteHidden(r)}
                    style={{ ...hiddenBtn, color: "var(--danger)" }}>
                    {tr("Delete")}
                  </button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
      <FloatingTextInPicture region={hovered?.region ?? null}
        rect={hovered?.rect ?? null} />
    </div>
  );
}

const hiddenBtn: React.CSSProperties = {
  background: "none", border: "1px solid var(--border)", borderRadius: "var(--r-2)",
  padding: "2px 7px", fontSize: "var(--fs-2)", color: "var(--text-2)", cursor: "pointer",
  flex: "0 0 auto",
};

function TextRow({
  row, readOnly, selProps, picked, expanded, onToggle, editing, onEdit,
  onDraft, onSave, onCancel, onRemove, onHover,
  dragProps, dropProps, dropMarked,
}: {
  row: RenderRow;
  readOnly?: boolean;
  selProps: ReturnType<ReturnType<typeof useRowSelect>["props"]> extends infer P
    ? P : never;
  picked: boolean;
  expanded: boolean;
  onToggle: () => void;
  editing: { id: number; draft: string } | null;
  onEdit: (draft: string) => void;
  onDraft: (draft: string) => void;
  onSave: () => void;
  onCancel: () => void;
  onRemove: () => void;
  onHover: (rect: DOMRect | null) => void;
  dragProps?: { onDragStart: () => void; onDragEnd: () => void };
  dropProps?: { onDragOver: (e: React.DragEvent) => void;
                onDrop: (e: React.DragEvent) => void };
  dropMarked?: boolean;
}) {
  const tr = useT();
  const tn = useTn();
  const r = row.region;
  const text = regionText(r);
  const rowsBelow = childrenAreRows(r);
  const isBlock = r.level === "block";
  const detected = r.models.length > 0;
  // The engine doubted its own reading — and a person has not answered yet.
  // Once somebody has corrected the line, the doubt is ABOUT NOTHING: the
  // score still describes what the engine saw, but the text on screen is no
  // longer the engine's, so leaving the underline there says the reading is
  // uncertain when it is the one thing here that is not.
  const unsure = !r.edited && r.score != null && r.score < UNSURE;

  const menu: RowAction[] = [
    {
      icon: "content_copy", label: tr("Copy the text"),
      onClick: () => void navigator.clipboard?.writeText(text),
    },
    ...(readOnly ? [] : [
      detected
        ? {
          icon: "visibility_off", label: tr("Not text"), danger: true,
          separated: true,
          onClick: onRemove,
        } satisfies RowAction
        : {
          icon: "delete", label: tr("Delete this text"), danger: true,
          separated: true,
          onClick: onRemove,
        } satisfies RowAction,
    ]),
  ];

  return (
    <div
      {...selProps}
      {...(dropProps ?? {})}
      style={{
        marginLeft: row.depth * 22,
        borderRadius: "var(--r-4)",
        padding: "6px 6px 6px 4px",
        marginTop: 4,
        border: `1px solid ${picked ? "var(--accent)" : "var(--border)"}`,
        background: picked ? "var(--accent-dim)" : "var(--panel)",
        // The insertion line while a reorder drag hovers this row.
        boxShadow: dropMarked ? "inset 0 2px 0 var(--accent)" : undefined,
        // Never animate the picked colours: a click that takes half a second
        // to look landed reads as a click that has not registered.
        userSelect: "none",
        cursor: "default",
      }}
    >
      <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
        {dragProps && (
          // Only the handle starts a reorder drag — the row itself paints
          // the selection.
          <span
            draggable
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
            onDragStart={dragProps.onDragStart}
            onDragEnd={dragProps.onDragEnd}
            title={tr("Drag to reorder")}
            style={{ flex: "0 0 auto", display: "flex", cursor: "grab",
                     color: "var(--muted-3)", marginTop: 2 }}>
            <Icon name="drag_indicator" size={14} />
          </span>
        )}
        {/* The hover hangs off this gutter — the part that asks "where?" —
            never off the full-width row, which would open a 240 px preview
            on the way to the ⋯. */}
        <span
          title={tr("Show where this is in the picture")}
          onMouseEnter={(e) => onHover(
            (e.currentTarget as HTMLElement).getBoundingClientRect())}
          onMouseLeave={() => onHover(null)}
          onMouseDown={(e) => e.stopPropagation()}
          style={{
            flex: "0 0 auto", width: 20, height: 20, display: "flex",
            alignItems: "center", justifyContent: "center",
            color: "var(--muted-2)", marginTop: 1,
          }}>
          <Icon name="crop_free" size={15} />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          {editing ? (
            <TextEditor
              draft={editing.draft}
              multiline={isBlock}
              onDraft={onDraft}
              onSave={onSave}
              onCancel={onCancel}
            />
          ) : (
            // The text is an INLINE span in a block that fills the row: a
            // click on the words edits, a click on the space beside them
            // belongs to the row and selects it. As a block element the
            // "text" reached the right-hand edge, so half the row was an
            // editor nobody was aiming at.
            <div style={{ fontSize: "var(--fs-3)", lineHeight: 1.45 }}>
              <span
                onClick={(e) => {
                  if (readOnly) return;
                  e.stopPropagation();
                  onEdit(text);
                }}
                onMouseDown={(e) => { if (!readOnly) e.stopPropagation(); }}
                title={unsure
                  ? tr("The engine was unsure of this")
                  : (readOnly ? undefined : tr("Correct the transcription"))}
                style={{
                  whiteSpace: "pre-wrap", overflowWrap: "anywhere",
                  color: text ? "var(--text)" : "var(--muted)",
                  cursor: readOnly ? "default" : "text",
                  // The one hint the score is worth: a dotted underline on
                  // the reading the engine itself doubted. Never amber —
                  // that says "a machine said this and nobody agreed", which
                  // is true of every row here and so says nothing.
                  textDecoration: unsure ? "underline dotted" : undefined,
                  textUnderlineOffset: 3,
                }}>
                {text || tr("Type what it says")}
              </span>
            </div>
          )}
          {rowsBelow && (
            <button
              onClick={(e) => { e.stopPropagation(); onToggle(); }}
              onMouseDown={(e) => e.stopPropagation()}
              style={{
                background: "none", border: "none", padding: 0, marginTop: 3,
                color: "var(--muted)", fontSize: "var(--fs-2)", cursor: "pointer",
                display: "flex", alignItems: "center", gap: 3,
              }}>
              <Icon name={expanded ? "expand_more" : "chevron_right"} size={13} />
              {tn({ one: "1 line", other: "{n} lines" },
                  r.children.filter((c) => c.level === "line").length)}
            </button>
          )}
        </div>
        <RowMenu always actions={menu} title={tr("More actions")} />
      </div>
    </div>
  );
}

/** The in-place editor. The LEVEL says whether Enter is a character or the
 *  commit — and a field where Enter is not the commit shows the two buttons
 *  that are. The caret opens at the END, never select-all: correcting a
 *  transcription fixes one character, it does not replace a name. */
function TextEditor({ draft, multiline, onDraft, onSave, onCancel }: {
  draft: string;
  multiline: boolean;
  onDraft: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const tr = useT();
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const opened = useRef(false);
  React.useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
    if (!opened.current) {
      opened.current = true;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
  }, [draft]);
  // A one-line region commits on Enter and on the way out; a multi-line one
  // on ⌘/Ctrl+Enter alone (Enter is a newline, and a blur is not a save).
  const keys = useInlineEdit<HTMLTextAreaElement>({
    commit: onSave, cancel: onCancel, metaEnter: multiline,
    commitOnBlur: !multiline,
  });
  return (
    <div onMouseDown={(e) => e.stopPropagation()}>
      <textarea
        ref={ref}
        value={draft}
        rows={1}
        onChange={(e) => onDraft(e.target.value)}
        onKeyDown={keys.onKeyDown}
        onBlur={keys.onBlur}
        style={{
          width: "100%", fontSize: "var(--fs-3)", lineHeight: 1.45,
          padding: "4px 6px", borderRadius: "var(--r-2)", resize: "none",
          overflow: "hidden", border: "1px solid var(--accent)",
          background: "var(--panel-2)", color: "var(--text)",
          fontFamily: "inherit",
        }}
      />
      {multiline && (
        <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
          <button onClick={onSave} title={tr("Save the text")} style={{
            border: "none", borderRadius: "var(--r-2)", padding: "2px 10px",
            background: "var(--accent)", color: "var(--on-accent)", cursor: "pointer",
            display: "flex", alignItems: "center",
          }}>
            <Icon name="check" size={15} />
          </button>
          <button onClick={onCancel} style={{
            border: "1px solid var(--border)", borderRadius: "var(--r-2)",
            padding: "2px 10px", background: "transparent",
            color: "var(--text-2)", cursor: "pointer",
            display: "flex", alignItems: "center",
          }}>
            <Icon name="close" size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
