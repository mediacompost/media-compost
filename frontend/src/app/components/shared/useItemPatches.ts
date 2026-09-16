/** A SESSION'S ROWS FOLLOW THE ITEM (2026-09).
 *
 *  The tag grid, the tag batch and a rating session hold their pictures as
 *  rows of their own (`RankingItemRef`: the file, its rotation, its thumb
 *  token), fetched once for the batch. The preview over them turns a
 *  picture and refreshes the ITEM's detail (`["item", id]`), which nothing
 *  in the session was reading — so the card under the preview kept the
 *  old thumbnail while the library's grid had moved on.
 *
 *  This is the bridge: every settled `["item", id]` detail in the query
 *  cache is handed to the caller, which patches whatever rows it holds for
 *  that item (`patchRow` says what moves — the file, the rotation, the
 *  token). A subscription rather than a query per card: a session's rows
 *  are dozens, and the detail only ever changes because something over
 *  the session wrote it.
 */
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { ItemDetail } from "../../api";

export interface PictureRow {
  item_id: number;
  file_id: number | null;
  rotation: number;
  thumb_token: string;
}

/** The row with the detail's picture facts, or the row itself when nothing
 *  moved — so a list keeps its identity when no card needs redrawing. */
export function patchRow<R extends PictureRow>(row: R, d: ItemDetail): R {
  if (row.item_id !== d.id) return row;
  const file = d.active_file_id ?? null;
  if (row.file_id === file && row.rotation === d.rotation
      && row.thumb_token === d.thumb_token) return row;
  return { ...row, file_id: file, rotation: d.rotation, thumb_token: d.thumb_token };
}

/** Every row patched; the SAME array when no row changed. */
export function patchRows<R extends PictureRow>(rows: R[], d: ItemDetail): R[] {
  let changed = false;
  const next = rows.map((r) => { const p = patchRow(r, d); if (p !== r) changed = true; return p; });
  return changed ? next : rows;
}

export function useItemPatches(onDetail: (d: ItemDetail) => void): void {
  const qc = useQueryClient();
  const ref = useRef(onDetail);
  ref.current = onDetail;
  useEffect(() => qc.getQueryCache().subscribe((ev) => {
    if (ev.type !== "updated" || ev.action.type !== "success") return;
    const key = ev.query.queryKey;
    if (key.length !== 2 || key[0] !== "item" || typeof key[1] !== "number") return;
    const d = ev.query.state.data as ItemDetail | undefined;
    if (d && d.id === key[1]) ref.current(d);
  }), [qc]);
}
