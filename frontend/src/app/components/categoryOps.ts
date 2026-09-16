/** WHAT CAN BE DONE TO A CATEGORY — written once for both tag sets.
 *
 *  The library's own categories and an imported set's are the same
 *  `tag_set_categories` rows behind the same endpoints, so deleting one, or
 *  taking a branch out of the autocomplete, is the same call and the same
 *  question either way. It lived in the Sets tab alone until the library's
 *  sidebar grew a tree of its own; a second copy of the confirm text is a
 *  second answer to "does the branch go too?". */
import { useCallback, useRef, useState } from "react";
import { dropQuarters } from "../../shared/useDragRow";

import { useT, useTn } from "../i18n";
import { confirm } from "../../shared/ConfirmModal";
import { api, type TagSetCategoryOut } from "../api";
import { ancestorsOf } from "../treeRows";
import { LOOSE_DROP, type DropZone, type RowDrag } from "./TagsTree";
import type { RowSelect } from "./shared/useRowSelect";

export interface CategoryOps {
  /** Ask, then delete — the branch under each picked row goes with it.
   *  False when the question was answered No (or there was nothing to ask
   *  about), so the caller can leave its selection alone. */
  remove: (ids: number[]) => Promise<boolean>;
  setHidden: (ids: number[], hidden: boolean) => Promise<void>;
}

export function useCategoryOps(setId: number | null | undefined,
                               cats: TagSetCategoryOut[]): CategoryOps {
  const t = useT();
  const tn = useTn();

  const remove = useCallback(async (ids: number[]) => {
    if (setId == null || ids.length === 0) return false;
    const rows = ids.map((id) => cats.find((c) => c.id === id))
      .filter(Boolean) as TagSetCategoryOut[];
    if (!rows.length) return false;
    // THE QUESTION COUNTS THE BRANCH, not the rows picked: a delete takes
    // everything under a category with it, and "Delete 1 category?" over a
    // shelf holding eleven is the dialog leaving out the part worth asking
    // about.
    const inBranch = new Set<number>();
    for (const c of rows) {
      inBranch.add(c.id);
      for (const x of cats)
        if (ancestorsOf(cats, x.id).includes(c.id)) inBranch.add(x.id);
    }
    const under = inBranch.size - rows.length;
    const ok = await confirm({ answer: { label: t("Delete"), danger: true }, title:
      rows.length === 1
        ? under
          ? tn({ one: "Delete the category “{name}” and the {n} category inside it?",
                 other: "Delete the category “{name}” and the {n} categories inside it?" },
               under, { name: rows[0].name })
          : t("Delete the category “{name}”?", { name: rows[0].name })
        : under
          ? tn({ one: "Delete {n} category, with everything inside it?",
                 other: "Delete {n} categories, with everything inside them?" },
               rows.length)
          : tn({ one: "Delete {n} category?", other: "Delete {n} categories?" },
               rows.length) });
    if (!ok) return false;
    // ONLY THE TOP OF EACH PICKED BRANCH: a delete takes everything under
    // the category with it, so a selection holding both a parent and its
    // child is one delete, and asking for the child afterwards is a 404 for
    // a row that is already gone.
    const picked = new Set(rows.map((c) => c.id));
    const tops = rows.filter(
      (c) => !ancestorsOf(cats, c.id).some((id) => picked.has(id)));
    for (const c of tops) await api.deleteTagSetCategory(setId, c.id);
    return true;
  }, [setId, cats, t, tn]);

  const setHidden = useCallback(async (ids: number[], hidden: boolean) => {
    if (setId == null) return;
    for (const id of ids) await api.updateTagSetCategory(setId, id, { hidden });
  }, [setId]);

  return { remove, setHidden };
}

// ---------------------------------------------------------------------------
// DRAGGING THE TREE
// ---------------------------------------------------------------------------

/** Reordering a category tree, and dropping a list's rows onto one — written
 *  once for both tag sets.
 *
 *  The library's categories and an imported set's are the same
 *  `tag_set_categories` rows behind the same endpoints, so the gesture is the
 *  same gesture: the top quarter of a row drops the carried category BEFORE
 *  it, the bottom quarter AFTER it (both as its sibling), the middle INTO it
 *  at the end of its children, and nothing may land in its own subtree. One
 *  request (`moveTagSetCategory`), one event, and the tree re-reads.
 *
 *  The OTHER thing a tree row takes is a drop from the list beside it — tags
 *  in the library, entries in a set. Only the "into" zone means anything for
 *  those (a tag has no place among the categories' ORDER), so a row takes
 *  such a drop whole; the host says what to do with it (`onDropPayload`,
 *  with `null` for the Uncategorized row, which is the only way a name comes
 *  OUT of a category).
 *
 *  A DRAG SOURCE MUST CALL `sel.cancelPress()`: Chrome sends `dragend` and
 *  never the `mouseup` the paint gesture ends on, so the press would outlive
 *  the drag and the next hover would paint.
 */
export interface CategoryDrag {
  /** What `TagsSidebar` hands each category row. */
  categoryDrag: (c: TagSetCategoryOut, sel: RowSelect) => RowDrag | undefined;
  /** …and its Uncategorized row, which only ever TAKES a payload. */
  looseDrag: RowDrag | undefined;
  /** The list beside the tree starts carrying rows. */
  begin: (ids: number[]) => void;
  end: () => void;
  carrying: boolean;
}

export function useCategoryDrag({ setId, cats, onDropPayload, onChanged }: {
  setId: number | null | undefined;
  cats: TagSetCategoryOut[];
  /** Where the list's rows should go — `null` is "no category at all". */
  onDropPayload: (ids: number[], categoryId: number | null) => void;
  /** A move landed; re-read whatever draws the tree. */
  onChanged: () => void;
}): CategoryDrag {
  const [dragCat, setDragCat] = useState<number | null>(null);
  const [payload, setPayload] = useState<number[] | null>(null);
  const [dropAt, setDropAt] = useState<{ id: number; zone: DropZone } | null>(null);
  const dropAtRef = useRef(dropAt);
  const setDrop = (next: { id: number; zone: DropZone } | null) => {
    const cur = dropAtRef.current;
    if ((cur?.id ?? null) === (next?.id ?? null) && cur?.zone === next?.zone) return;
    dropAtRef.current = next;
    setDropAt(next);
  };
  // The category a drop would land INSIDE — the target itself for "into",
  // its parent for a sibling drop — so that row is rung while the line says
  // where among its children the carried one goes.
  const dropParent = dropAt == null ? null
    : dropAt.zone === "into" ? dropAt.id
    : (cats.find((c) => c.id === dropAt.id)?.parent_id ?? null);
  const canDropOn = (target: TagSetCategoryOut) =>
    dragCat != null && target.id !== dragCat
    && !ancestorsOf(cats, target.id).includes(dragCat);

  const move = (target: TagSetCategoryOut, zone: DropZone) => {
    if (setId == null || dragCat == null || !canDropOn(target)) return;
    const siblings = (parent: number | null) =>
      [...cats].filter((c) => c.parent_id === parent && c.id !== dragCat)
        .sort((a, b) => a.position - b.position || a.id - b.id);
    let parent: number | null;
    let index: number;
    if (zone === "into") {
      parent = target.id;
      index = siblings(target.id).length;
    } else {
      parent = target.parent_id;
      index = siblings(parent).findIndex((c) => c.id === target.id)
        + (zone === "after" ? 1 : 0);
    }
    void api.moveTagSetCategory(setId, dragCat, { parent_id: parent, index })
      .then(onChanged);
  };

  const categoryDrag = (c: TagSetCategoryOut, sel: RowSelect): RowDrag => (
    payload ? {
      dragging: false, zone: null, parent: dropAt?.id === c.id,
      onDragEnd: () => { setPayload(null); setDrop(null); },
      onDragOver: (ev) => {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
        setDrop({ id: c.id, zone: "into" });
      },
      onDragLeave: () => { if (dropAtRef.current?.id === c.id) setDrop(null); },
      onDrop: (ev) => {
        ev.preventDefault();
        const ids = payload ?? [];
        setDrop(null); setPayload(null);
        onDropPayload(ids, c.id);
      },
    } : {
      dragging: dragCat === c.id,
      zone: dropAt?.id === c.id ? dropAt.zone : null,
      parent: dragCat != null && dropParent === c.id,
      onDragStart: (ev) => {
        ev.dataTransfer.setData("text/plain", `tagset-category:${c.id}`);
        ev.dataTransfer.effectAllowed = "move";
        sel.cancelPress();
        setDragCat(c.id);
      },
      onDragEnd: () => { setDragCat(null); setDrop(null); },
      onDragOver: (ev) => {
        if (!canDropOn(c)) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
        setDrop({ id: c.id, zone: dropQuarters(ev) });
      },
      onDragLeave: () => { if (dropAtRef.current?.id === c.id) setDrop(null); },
      onDrop: (ev) => {
        ev.preventDefault();
        const zone = dropAtRef.current?.id === c.id
          ? dropAtRef.current.zone : "into";
        setDrop(null); setDragCat(null);
        move(c, zone);
      },
    });

  const looseDrag: RowDrag | undefined = payload ? {
    dragging: false, zone: null, parent: dropAt?.id === LOOSE_DROP,
    onDragEnd: () => { setPayload(null); setDrop(null); },
    onDragOver: (ev) => {
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      setDrop({ id: LOOSE_DROP, zone: "into" });
    },
    onDragLeave: () => {
      if (dropAtRef.current?.id === LOOSE_DROP) setDrop(null);
    },
    onDrop: (ev) => {
      ev.preventDefault();
      const ids = payload ?? [];
      setDrop(null); setPayload(null);
      onDropPayload(ids, null);
    },
  } : undefined;

  return { categoryDrag, looseDrag, carrying: payload != null,
           begin: (ids) => setPayload(ids),
           end: () => { setPayload(null); setDrop(null); } };
}
