/** Who is in the picture — the sidebar's Subjects and Faces, as one list.
 *
 * They were two sections and answered the same question from two ends: one
 * said who is here, the other said where. Reading them together meant holding
 * one in your head while looking at the other, and neither could say the thing
 * that is actually true — that a face and a person are not the same kind of
 * fact, and their relationship is many to one.
 *
 * So: a FACE row, and indented under it the people that face is. A person the
 * detector never found sits at the top level, unindented, because there is no
 * rectangle to sit under. One face can carry several people (a drawn character
 * and the actor playing them), and each of those carries its own age — which
 * is the whole reason "played by" is gone.
 *
 * A person row had a drag HANDLE, for carrying an appearance onto a face or
 * off one. It never worked — the rows are inside a scrolling panel whose own
 * gestures got there first — and the thing it did is already sayable: name the
 * face, or take the name off it. So it is gone, along with the drop targets it
 * aimed at; the handle's 15 px went back to the name, which is what actually
 * runs out of room here.
 */
import React, { useMemo, useRef, useState } from "react";
import { dropHalf } from "../../shared/useDragRow";
import { RECORD_ICON } from "../../shared/metaEnums";
import { rowBackground } from "../../shared/Row";
import { IconButton } from "../../shared/IconButton";
import { fieldStyleSm } from "../../shared/Field";
import { bracketSlug, splitBracketed } from "../tagslug";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, FaceRow, FileVersion, ItemDetail, SubjectAppearance, SubjectOnItem, SubjectRow, TagBox } from "../api";
import { bumpEdits } from "../invalidation";
import { Icon } from "../../shared/Icon";
import { useLang, useT, useTn } from "../i18n";
import { TagAutocomplete } from "./TagAutocomplete";
import { TagSuggestion } from "./TagAutocomplete";
import { RowAction, RowMenu } from "./shared/RowMenu";
import { useSearchActions } from "./shared/searchActions";
import { FloatingFaceInPicture } from "./shared/FaceInPicture";
import { RowSelect } from "./shared/useRowSelect";
import { useUndoRun } from "./shared/useUndoBar";
import { TagAnnotation } from "./PropertiesPanel";
import { FocusOnce } from "./shared/FocusOnce";
import { byRecent, rememberSubject, useRecentSubjects } from "../subjects/recent";
import { RecordEditOverlay } from "./TagEditOverlay";
import { ageAt, dateFromAge, formatDate, parseDate, whenLabel } from "../../query/subjects/when";
import { TagRangeLine, useTagRangeLabel } from "./shared/TagRanges";
import { useUI } from "../store";

const CROP = 56;

/** A model key as something to read. An unknown key falls back to itself.
 *  `anime_face` is kept although nothing offers it any more: the detector-only
 *  plugin is gone, and the faces it already found still carry its key. */
const MODEL_NAMES: Record<string, string> = {
  anime_face: "Illustrated faces",
  anime_face_magi: "Illustrated faces (YOLOv8 + Magi)",
  insightface_buffalo_l: "InsightFace",
};
const modelLabel = (m: string) => MODEL_NAMES[m] ?? m;

/** How a person row is selected: by its APPEARANCE where it has one, and by
 *  the tag where it does not — somebody on the item through their tag alone
 *  has no appearance row to name, and still has to be selectable.
 *
 *  Exported so `PropertiesPanel` keys the selection off the same derivation
 *  the rows render from; two spellings of one key is a selection that never
 *  matches anything. */
export const rowKey = (row: { subject: { tag: string };
                             appearance: { id: number } }) =>
  row.appearance.id ? `a:${row.appearance.id}` : `s:${row.subject.tag}`;

/** One row of the list: a face, or a person at (or away from) one. */
interface PersonRow {
  key: string;
  subject: SubjectOnItem;
  appearance: SubjectAppearance;
}

export function PeopleSection({ itemId, detail, sel, topAction, focusTag,
                               focusFace, onFocused, onChange,
                               faceSel, onPickFace }: {
  itemId: number;
  detail: ItemDetail | null;
  /** The tab's row selection, spanning this section and its siblings. */
  sel?: RowSelect;
  /** The "Detect faces" action, at the top of the section — where the Tags and
   *  Captions sections put theirs. It stays there once faces exist: running
   *  the OTHER detector over the same picture is the normal next step in a
   *  library that is part drawn and part photographed. */
  topAction?: React.ReactNode;
  /** A subject to land on, by identity tag — set when the Tags tab's person
   *  marker sent you here. */
  focusTag?: string | null;
  /** A SUBJECT's tag whose crops to land on, rather than the row naming them —
   *  the face marker beside a tag asks "where is she in this picture", which
   *  the crop answers and the name does not. */
  focusFace?: string | null;
  onFocused?: () => void;
  onChange: () => void;
  /** Which faces are picked, when the host draws them over a picture as well
   *  (the annotator). The crop in this list and the oval on the picture are
   *  two views of one face, so they share the selection rather than each
   *  keeping one — passing neither leaves the rows unselectable, which is what
   *  the library sidebar wants. */
  faceSel?: number[];
  onPickFace?: (id: number, additive: boolean) => void;
}) {
  const t = useT();
  const undoRun = useUndoRun();
  // Over a FILM a person is timed like any other tag — they are on screen in
  // some stretches and not in others, and the tag rows already said so while
  // this list said nothing.
  const rangeLabel = useTagRangeLabel(detail);
  const qc = useQueryClient();
  const setView = useUI((s) => s.setView);
  const setTagsMode = useUI((s) => s.setTagsMode);
  const { data: faces } = useQuery({
    queryKey: ["faces", itemId], queryFn: () => api.faces(itemId),
  });
  const { data: catalog } = useQuery({
    queryKey: ["subjects"], queryFn: api.subjects,
  });
  const [adding, setAdding] = useState("");
  const [naming, setNaming] = useState<number | null>(null);   // face id
  const [typed, setTyped] = useState("");
  const [dating, setDating] = useState<number | null>(null);   // appearance id
  const [editSubject, setEditSubject] = useState<SubjectRow | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);
  // The face under the pointer and where its row is, so the preview can float
  // beside it instead of being appended to the panel.
  const [hovered, setHovered] =
    useState<{ face: FaceRow; rect: DOMRect | null } | null>(null);

  const subjects = detail?.subjects ?? [];
  const live = useMemo(
    () => [...(faces ?? [])].filter((f) => !f.dismissed)
      .sort((a, b) => b.w * b.h - a.w * a.h), [faces]);
  const dismissed = useMemo(
    () => (faces ?? []).filter((f) => f.dismissed), [faces]);

  const refresh = () => {
    // A row that VANISHES under the pointer never fires its mouseleave —
    // dismissing a face is exactly that — so the floating preview would hang
    // over the panel until something else was hovered.
    setHovered(null);
    qc.invalidateQueries({ queryKey: ["faces", itemId] });
    qc.invalidateQueries({ queryKey: ["faces-unnamed"] });
    qc.invalidateQueries({ queryKey: ["subjects"] });
    onChange();
  };

  // Every appearance, split by whether it sits at a face — each list in the
  // drag-reorder's order (position, then id: the creation order until
  // somebody reorders).
  const byFace = useMemo(() => {
    const cmp = (a: PersonRow, b: PersonRow) =>
      (a.appearance.position ?? 0) - (b.appearance.position ?? 0)
      || a.appearance.id - b.appearance.id;
    const map = new Map<number, PersonRow[]>();
    const loose: PersonRow[] = [];
    for (const sub of subjects) {
      for (const a of sub.appearances) {
        const row = { key: `a${a.id}`, subject: sub, appearance: a };
        if (a.face_id == null) loose.push(row);
        else map.set(a.face_id, [...(map.get(a.face_id) ?? []), row]);
      }
      // A subject on the item through its tag alone still gets a row: the tag
      // is the assignment, and a person with no row could not be taken off.
      if (sub.appearances.length === 0) {
        loose.push({
          key: `t${sub.id}`, subject: sub,
          appearance: { id: 0, face_id: null, when: null, when_derived: false,
                        assigned_by: "user", match_score: null },
        });
      }
    }
    for (const rows of map.values()) rows.sort(cmp);
    loose.sort(cmp);
    return { map, loose };
  }, [subjects]);

  // A subject on the item MORE THAN ONCE numbers its entries in reading
  // order — "(1)", "(2)" — so two rows wearing one name stop being
  // indistinguishable. Keyed by the ROW; a subject here once gets none.
  const ordinals = useMemo(() => {
    const order: PersonRow[] = [
      ...live.flatMap((f) => byFace.map.get(f.id) ?? []),
      ...byFace.loose,
    ];
    const bySub = new Map<number, PersonRow[]>();
    for (const r of order) {
      bySub.set(r.subject.id, [...(bySub.get(r.subject.id) ?? []), r]);
    }
    const out = new Map<string, number>();
    for (const rows of bySub.values()) {
      if (rows.length < 2) continue;
      rows.forEach((r, i) => out.set(r.key, i + 1));
    }
    return out;
  }, [live, byFace]);

  // ---- drag & drop: reorder the rows, and move one onto (or off) a face.
  // A HANDLE starts it (the row's own drag is the selection paint), the
  // payload is set and the drag image is the row (a drag carrying nothing is
  // one Chrome may decline — the tag-drag lesson), and a drop says both
  // things at once: which face the appearance is at now, and where in the
  // list it sits. `dropHint` is only the indicator.
  const dragApp = useRef<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [dropHint, setDropHint] = useState<string | null>(null);
  const flatRows = (): PersonRow[] => [
    ...live.flatMap((f) => byFace.map.get(f.id) ?? []),
    ...byFace.loose,
  ];
  const startRowDrag = (e: React.DragEvent, row: PersonRow) => {
    dragApp.current = row.appearance.id;
    setDragging(true);
    e.dataTransfer.setData("text/plain", String(row.appearance.id));
    e.dataTransfer.effectAllowed = "move";
    const el = (e.currentTarget as HTMLElement).closest("[data-approw]");
    if (el) e.dataTransfer.setDragImage(el as Element, 12, 12);
  };
  const endRowDrag = () => {
    dragApp.current = null;
    setDragging(false);
    setDropHint(null);
  };
  /** Land the drag: `faceId` is the group it fell into (null = no face),
   *  `beforeKey` the row it goes in front of (absent = the group's end). */
  const dropRow = async (faceId: number | null,
                         beforeKey: string | null,
                         after: boolean) => {
    const moving = dragApp.current;
    endRowDrag();
    if (moving == null || !itemId) return;
    const flat = flatRows().filter((r) => r.appearance.id !== moving);
    const me = flatRows().find((r) => r.appearance.id === moving);
    if (!me) return;
    let at = flat.length;
    if (beforeKey != null) {
      const i = flat.findIndex((r) => r.key === beforeKey);
      if (i >= 0) at = i + (after ? 1 : 0);
    } else {
      // The group's end: after its last row (a face card or the loose list).
      const last = [...flat].reverse().find((r) =>
        (faceId == null ? r.appearance.face_id == null
                        : r.appearance.face_id === faceId));
      at = last ? flat.indexOf(last) + 1 : flat.length;
    }
    const next = [...flat.slice(0, at), me, ...flat.slice(at)];
    if ((me.appearance.face_id ?? null) !== faceId) {
      // 0 detaches — the op reads any falsy face as "off the face".
      await api.editAppearance(moving, { face_id: faceId ?? 0 });
    }
    await api.reorderAppearances(itemId, next.map((r) => r.appearance.id));
    refresh();
  };
  /** The three targets' shared dragover: only while one of OUR rows is in
   *  the hand — a file from outside must keep falling through to the
   *  window's import handling. */
  const overRow = (e: React.DragEvent, hint: string) => {
    if (dragApp.current == null) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    setDropHint((cur) => (cur === hint ? cur : hint));
  };
  const recent = useRecentSubjects();
  const options: TagSuggestion[] = useMemo(
    () => byRecent((catalog ?? []).filter((s) => s.display_name || s.tag)
      .map((s) => ({
        name: s.display_name || s.tag,
        // The COMMENT leads: it is what tells two people of one name apart,
        // which is the question the row answers; the tag is machinery.
        comment: [s.comment, s.display_name ? s.tag : ""].filter(Boolean).join(" · "),
        uses: s.items,
      })), recent),
    [catalog, recent]
  );
  const byName = useMemo(
    () => new Map((catalog ?? []).map(
      (s) => [(s.display_name || s.tag).toLowerCase(), s])), [catalog]);

  // The subject namespace, for the bracket-split create below.
  const { data: speSettings } = useQuery({
    queryKey: ["settings"], queryFn: api.getSettings });
  /** Find or make the subject a typed name means. A trailing bracket splits
   *  — "Traveler (Genshin Impact)" is name + comment, with the bracketed
   *  slug (`subject:traveler_(genshin_impact)`), the record overlays'
   *  own rule. */
  const resolve = async (text: string): Promise<SubjectRow | undefined> => {
    const wanted = text.trim();
    if (!wanted) return undefined;
    const known = byName.get(wanted.toLowerCase());
    if (known) return known;
    const sp = splitBracketed(wanted);
    const rows = await api.createSubject({
      display_name: sp.name,
      ...(sp.comment ? {
        comment: sp.comment,
        tag: `${speSettings?.subject_tag_prefix ?? ""}${
          bracketSlug(sp.name, sp.comment)}`,
      } : {}),
    });
    qc.invalidateQueries({ queryKey: ["subjects"] });
    return rows.find((s) => s.display_name === sp.name)
      ?? rows[rows.length - 1];
  };

  const nameFace = async (faceId: number, text: string) => {
    const subject = await resolve(text);
    setNaming(null);
    setTyped("");
    if (!subject) return;
    await api.nameFace(faceId, { subject_id: subject.id });
    rememberSubject(subject.display_name || subject.tag);
    refresh();
    // Naming propagates server-side: the unnamed lookalikes on OTHER items
    // may just have gained amber suggestions and pending tags, which the
    // item-scoped refresh above cannot see.
    qc.invalidateQueries({ queryKey: ["faces"] });
    bumpEdits();
  };

  /** SOMEBODY WITH NO NAME — the other answer to "who is this". It takes
   *  the face's cluster out of the Faces tab's UNKNOWN queue without a name
   *  being invented for it, and the identity it lands on is its OWN: two
   *  background characters are two people. */
  const markUnnamed = async (faceId: number) => {
    setNaming(null);
    setTyped("");
    await api.setClusterUnnamed([faceId]);
    refresh();
    qc.invalidateQueries({ queryKey: ["faces"] });
    bumpEdits();
  };

  const addPerson = async (text: string) => {
    const subject = await resolve(text);
    setAdding("");
    if (!subject) return;
    await api.addAppearance({ item_id: itemId, subject_id: subject.id });
    rememberSubject(subject.display_name || subject.tag);
    refresh();
  };

  /** Take a drawn outline off — the appearance keeps everything else.
   *  Through the undo runner: the clear is logged and revertible, and this
   *  is the row's way back. */
  const clearOutline = (row: PersonRow) => undoRun(
    `${t("Removed the outline of")} ${
      row.subject.display_name || row.subject.tag}`,
    async () => {
      await api.clearAppearanceBox(row.appearance.id);
      refresh();
    });
  const removeRow = (row: PersonRow) => undoRun(
    `${t("Removed")} ${row.subject.display_name || row.subject.tag}`,
    () => doRemoveRow(row));
  const doRemoveRow = async (row: PersonRow) => {
    // At a FACE, saying no goes through the face — that path records the
    // refusal, so the next run does not offer the same wrong name again.
    // Taking a name somebody GAVE off is not a refusal, and that endpoint
    // knows the difference.
    if (row.appearance.face_id != null) {
      await api.unnameFace(row.appearance.face_id, row.subject.id);
    } else if (row.appearance.id) {
      await api.removeAppearance(row.appearance.id);
    } else {
      await api.unassignItemTag(itemId, row.subject.tag);
    }
    refresh();
  };
  /** Agree with a guess. */
  const confirmRow = async (row: PersonRow) => {
    if (!row.appearance.id) return;
    await api.editAppearance(row.appearance.id, { confirm: true });
    refresh();
  };

  // "Show in list" points at a row; it used to narrow the list to a search for
  // the name, which hides every other person and leaves you to clear the field
  // afterwards. Landing on the row and flashing it is the same answer without
  // the cleanup — and it is what the Tags tab's own kind markers do.
  const showInList = (row: PersonRow) => {
    setTagsMode("subjects", row.subject.tag);
    setView("tags");
  };
  /** Every picture they are in, in the Library — and, while a search is
   *  already running, the same person as one more condition on it. The
   *  subjects list answers who they are and which crops are theirs; this
   *  answers what they are IN, which is a different question and the one the
   *  grid is for. */
  const searchActions = useSearchActions();

  if (!detail) return null;

  // The active file, for the outline previews: TagAnnotation maps
  // reference-frame boxes through its crop exactly as the tag rows do.
  const activeFile: FileVersion | null =
    detail?.files?.find((f) => f.id === detail.active_file_id) ?? null;
  const outlineByFace = useMemo(() => {
    const out = new Map<number, TagBox>();
    for (const f of faces ?? []) {
      if (f.outline) {
        out.set(f.id, { x: f.outline[0], y: f.outline[1],
          w: f.outline[2], h: f.outline[3], time_start: null, time_end: null,
          points: f.outline_points ?? null });
      }
    }
    return out;
  }, [faces]);
  /** The outline a person ROW shows: the appearance's own subject box, else
   *  the FACE's outline — the inheritance the training fallback follows, so
   *  the preview shows what a run would actually use. */
  const rowOutline = (row: PersonRow): TagBox[] => {
    const a = row.appearance;
    if (a.box) {
      return [{ x: a.box[0], y: a.box[1], w: a.box[2], h: a.box[3],
        time_start: null, time_end: null, points: a.points ?? null }];
    }
    const inherited = a.face_id != null ? outlineByFace.get(a.face_id) : null;
    return inherited ? [inherited] : [];
  };

  const person = (row: PersonRow, indented: boolean) => {
    const canDrag = row.appearance.id !== 0;
    const above = `row:${row.key}:above`;
    const below = `row:${row.key}:below`;
    return (
    <div
      key={row.key}
      data-approw
      onDragOver={(e) => {
        if (dragApp.current == null || !canDrag) return;
        overRow(e, dropHalf(e) === "before" ? above : below);
      }}
      onDrop={(e) => {
        if (dragApp.current == null) return;
        e.preventDefault();
        e.stopPropagation();
        void dropRow(row.appearance.face_id ?? null, row.key,
                     dropHint === below);
      }}
      style={{
        borderRadius: "var(--r-2)",
        boxShadow: dropHint === above ? "0 -2px 0 0 var(--accent)"
          : dropHint === below ? "0 2px 0 0 var(--accent)" : undefined,
      }}
    >
    <PersonLine
      row={row}
      indented={indented}
      // Keyed by the APPEARANCE. The same person can be in one picture twice,
      // at two faces or at two ages, and keying by their tag lit both rows up
      // when either was picked — one selection wearing two highlights.
      picked={sel?.has(rowKey(row)) ?? false}
      selProps={sel?.props(rowKey(row))}
      flash={focusTag === row.subject.tag}
      open={dating === row.appearance.id && row.appearance.id !== 0}
      onToggleDate={() => setDating(
        dating === row.appearance.id ? null : row.appearance.id)}
      onEdit={() => setEditSubject(
        (catalog ?? []).find((s) => s.id === row.subject.id) ?? null)}
      onShowInList={() => showInList(row)}
      searchActions={searchActions("subject", row.subject.tag,
        row.subject.display_name || row.subject.tag)}
      onConfirm={() => void confirmRow(row)}
      onReject={() => void removeRow(row)}
      onRemove={() => void removeRow(row)}
      onChanged={refresh}
      rangeLabel={rangeLabel?.(row.subject.tag) ?? null}
      ordinal={ordinals.get(row.key) ?? null}
      onClearOutline={row.appearance.id && row.appearance.box != null
        ? () => clearOutline(row)
        : undefined}
      outlineBoxes={rowOutline(row)}
      activeFile={activeFile}
      activeFileId={detail?.active_file_id ?? null}
      onDragStart={canDrag ? (e) => startRowDrag(e, row) : undefined}
      onDragEnd={endRowDrag}
      t={t}
    />
    </div>
    );
  };

  return (
    <div>
      {topAction && <div style={{ marginBottom: 8 }}>{topAction}</div>}

      {live.length === 0 && byFace.loose.length === 0 && (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", padding: "2px 0 6px" }}>
          {t("Nobody and nothing named yet.")}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {live.map((face) => (
          <div key={face.id}
            // Landed on from a tag's face marker: every crop that person is in
            // flashes, since "where is she here" may well have more than one
            // answer.
            className={focusFace
              && face.subjects.some((x) => x.tag === focusFace)
              ? "mc-flash" : undefined}
            // A drop ON THE CARD puts the carried appearance at this face
            // (its rows are finer targets and stop the event first).
            onDragOver={(e) => overRow(e, `face:${face.id}`)}
            onDrop={(e) => {
              if (dragApp.current == null) return;
              e.preventDefault();
              e.stopPropagation();
              void dropRow(face.id, null, false);
            }}
            style={{ borderRadius: "var(--r-6)",
              boxShadow: dropHint === `face:${face.id}`
                ? "inset 0 0 0 2px var(--accent)" : undefined }}>
            <FaceLine
              face={face}
              picked={!!faceSel?.includes(face.id)}
              outlineBoxes={outlineByFace.get(face.id)
                ? [outlineByFace.get(face.id) as TagBox] : []}
              activeFile={activeFile}
              activeFileId={detail?.active_file_id ?? null}
              onPick={onPickFace}
              naming={naming === face.id}
              typed={typed}
              options={options}
              onType={setTyped}
              onStartNaming={() => { setNaming(face.id); setTyped(""); }}
              onStopNaming={() => { setNaming(null); setTyped(""); }}
              onName={(text) => void nameFace(face.id, text)}
              onUnnamed={() => void markUnnamed(face.id)}
              onHover={(f, rect) => setHovered(f ? { face: f, rect } : null)}
              hovered={hovered?.face.id === face.id}
              onChanged={refresh}
              t={t}
            />
            {(byFace.map.get(face.id) ?? []).map((row) => person(row, true))}
          </div>
        ))}
      </div>

      {/* The people no rectangle holds — in the picture, but not at any of
          these faces. Dropping a carried row here takes it OFF its face; the
          zone announces itself while a drag is in the hand, since an empty
          strip is otherwise nothing to aim at. */}
      <div
        onDragOver={(e) => overRow(e, "loose")}
        onDrop={(e) => {
          if (dragApp.current == null) return;
          e.preventDefault();
          e.stopPropagation();
          void dropRow(null, null, false);
        }}
        style={{
          marginTop: byFace.loose.length || dragging ? 8 : 0,
          display: "flex", flexDirection: "column", gap: 4,
          minHeight: dragging ? 26 : undefined,
          border: dragging
            ? `1px dashed ${dropHint === "loose"
                ? "var(--accent)" : "var(--border-strong)"}`
            : undefined,
          borderRadius: "var(--r-4)",
          boxShadow: dropHint === "loose" && !dragging
            ? "inset 0 0 0 2px var(--accent)" : undefined,
        }}>
        {byFace.loose.map((row) => person(row, false))}
      </div>

      <div style={{ marginTop: 8 }}>
        <TagAutocomplete
          value={adding}
          onChange={setAdding}
          onCommit={(name) => void addPerson(name)}
          suggestions={options}
          placeholder={t("Add a subject…")}
          freeText
          minWidth={220}
        />
      </div>

      {/* HIDDEN faces — the ones somebody said were not faces at all. Kept out
          of the way but not thrown away: a dismissal is an answer, and the
          answer is sometimes wrong. They were a grid of 40 px crops that
          restored on a click, which is a row of buttons that look like
          pictures and cannot say which of the two things they do. Now they are
          the same ROWS as the live faces, greyed, with the two actions spelled
          out. The link is at the very bottom of the section and only when
          there are any. */}
      {dismissed.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <span onClick={() => setShowDismissed((v) => !v)}
            style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", cursor: "pointer",
              display: "inline-flex", alignItems: "center", gap: 3 }}>
            <Icon name={showDismissed ? "expand_less" : "expand_more"} size={14} />
            {/* The chevron says whether they are showing, so the words do not
                have to — and the count is parenthesised rather than in the
                sentence, since "1 hidden faces" is what a template with a
                number in it produces in every language that inflects. */}
            {`${t("Hidden faces")} (${dismissed.length})`}
          </span>
          {showDismissed && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6,
              marginTop: 6 }}>
              {dismissed.map((f) => (
                <HiddenFaceLine key={f.id} face={f} t={t}
                  onHover={(x, rect) => setHovered(x ? { face: x, rect } : null)}
                  onChanged={refresh} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Floating beside the row, like every other hover preview here. Under
          the list it pushed Places, Events and everything else down the panel
          the moment the pointer crossed a face — a preview that rearranges the
          thing you are pointing at. */}
      {hovered && (
        <FloatingFaceInPicture face={hovered.face} rect={hovered.rect} max={240} />
      )}

      {/* A SUBJECT IS DATA ON A TAG, and there is one editor for both: the
          tag's own fields with a Subject section among them. There is no
          subject editor any more. */}
      {editSubject && (
        <RecordEditOverlay
          tagId={editSubject.tag_id}
          kind="subject"
          onClose={() => setEditSubject(null)}
          onSaved={() => refresh()}
          onMerged={() => { setEditSubject(null); refresh(); }}
        />
      )}
      {(focusTag || focusFace) && onFocused
        && <FocusOnce onDone={onFocused} />}
    </div>
  );
}

/** A detected face: the crop, what found it, and what can be done to it. */
function FaceLine({ face, naming, typed, options, hovered, picked, onPick, t,
                   onType, onStartNaming, onStopNaming, onName, onUnnamed,
                   onHover,
                   onChanged, outlineBoxes, activeFile, activeFileId }: {
  face: FaceRow;
  naming: boolean;
  /** Picked — the same face the host has outlined on the picture. */
  picked?: boolean;
  onPick?: (id: number, additive: boolean) => void;
  typed: string;
  options: TagSuggestion[];
  hovered: boolean;
  t: (s: string, vars?: Record<string, string>) => string;
  onType: (s: string) => void;
  onStartNaming: () => void;
  onStopNaming: () => void;
  onName: (text: string) => void;
  /** THE OTHER ANSWER to "who is this": somebody with no name — a background
   *  character, an extra. Offered as a row of the suggestion list, where
   *  the other answers are (`suggestRows.SuggestAction`). */
  onUnnamed: () => void;
  /** The row's rectangle rides along: the preview FLOATS beside the row now,
   *  where it used to be pushed in under the list and shove every section
   *  below it down the panel — a hover that reflows the page. */
  onHover: (f: FaceRow | null, rect: DOMRect | null) => void;
  onChanged: () => void;
  /** The face's OUTLINE for the preview icon — the tag rows' own indicator:
   *  hover draws the thumbnail with the shape on it. */
  outlineBoxes?: TagBox[];
  activeFile?: FileVersion | null;
  activeFileId?: number | null;
}) {
  const tn = useTn();
  // Both ways out of the row are logged and revertible, so they offer
  // themselves back — the sidebar's rule for every removal.
  const undoRun = useUndoRun();
  const detectors = face.models.map(modelLabel).join(" + ");
  // What was typed, so the tick knows whether there is anything to commit —
  // the field's own Enter has the value, a button beside it does not.
  const typedName = typed.trim();
  return (
    <div className="hoverable"
      onMouseDown={onPick ? (e) => {
        // Not on the name field, its buttons, or the crop's own controls —
        // those are inside the row and mean something else.
        if ((e.target as HTMLElement).closest("input,button,[data-faceact]")) return;
        onPick(face.id, e.metaKey || e.ctrlKey);
      } : undefined}
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "6px 6px 6px 8px", borderRadius: "var(--r-6)",
        background: picked ? "var(--accent-dim)"
          : hovered ? "var(--panel-3)" : "var(--panel-2)",
        border: `1px solid ${picked ? "var(--accent)" : "var(--border)"}`,
        cursor: onPick ? "pointer" : undefined,
      }}>
      {/* The preview hangs off the CROP, not off the row. The row is most of
          the sidebar's width and holds a name field, a ✚ and two buttons, so
          anchoring it there meant a 240 px picture appeared over the panel
          whenever the pointer crossed the row on its way to something else.
          The crop is the part that asks "which one is this?", so it is the
          part that answers. */}
      <img src={api.faceCropUrl(face, 224)} alt=""
        onMouseEnter={(e) => onHover(face, e.currentTarget.getBoundingClientRect())}
        onMouseLeave={() => onHover(null, null)}
        style={{ width: CROP, height: CROP, objectFit: "cover", borderRadius: "var(--r-4)",
          flex: "0 0 auto", border: "1px solid var(--border)" }} />
      {/* No name on this row. A face is a rectangle, and who is in it is the
          row (or rows) underneath — putting a name here as well would say the
          same thing twice, and say it wrong the moment a face is two people.
          What is left is what only a face can say: which detector found it and
          how sure it was. */}
      <span style={{ minWidth: 0, flex: 1, display: "flex",
        flexDirection: "column", gap: 2 }}>
        {naming ? (
          // A tick and a cross beside the field. It floats over a row with no
          // buttons of its own, so Enter and Escape were the only way out and
          // nothing said so — the annotator's own name field learned this
          // first.
          <span style={{ display: "flex", alignItems: "center", gap: 2 }}>
            <span style={{ flex: 1, minWidth: 0 }}>
              <TagAutocomplete
                value={typed}
                onChange={onType}
                onCommit={onName}
                onCancel={onStopNaming}
                suggestions={options}
                actions={[{ id: "unnamed", label: t("Unnamed"),
                            icon: "person_off",
                            hint: t("somebody with no name") }]}
                onAction={(id) => { if (id === "unnamed") onUnnamed(); }}
                placeholder={t("Who is this?")}
                freeText
                autoFocus
                autoSelect
                minWidth={140}
              />
            </span>
            <FaceAction icon="check" title={t("Name this face")}
              disabled={!typedName}
              onClick={() => onName(typedName)} />
            <FaceAction icon="close" title={t("Cancel")}
              onClick={onStopNaming} />
          </span>
        ) : (
          // A TITLE either way, and both open the field. With nobody on it the
          // row asks; with somebody it says how many, because the names are
          // already spelled out in the rows underneath and repeating them here
          // says the same thing twice — and says it wrong as soon as a face is
          // two people. Clicking either one is how a second name is added.
          // The naming button sits INLINE, right after the title it belongs
          // to. Among the trailing three it was one glyph of a row of them,
          // where "not a face" and "delete" are about getting RID of the
          // thing — so the one action that answers the row's own question was
          // filed with the two that dismiss it, and read as the least likely
          // of the three. Here it is what the title says, twice: the words
          // ask, the ✚ beside them is where you answer.
          <span style={{ display: "flex", alignItems: "center", gap: 2,
            minWidth: 0 }}>
            <span onClick={onStartNaming}
              title={face.subjects.length
                ? t("Add somebody else to this face") : t("Say who this is")}
              style={{ minWidth: 0, fontSize: "var(--fs-3)", cursor: "pointer",
                color: face.subjects.length ? "var(--text-2)" : "var(--muted-2)",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {face.subjects.length === 0 ? t("Who is this?")
                : tn({ one: "1 person", other: "{n} people" },
                     face.subjects.length)}
            </span>
            <FaceAction icon="person_add"
              title={face.subjects.length
                ? t("Add somebody else to this face") : t("Say who this is")}
              onClick={onStartNaming} />
            {/* The outline preview, the person rows' own icon: hover shows
                the picture with the whole-figure shape drawn on it. */}
            {outlineBoxes && outlineBoxes.length > 0 && (
              <TagAnnotation
                boxes={outlineBoxes}
                activeFileId={activeFileId ?? null}
                activeFile={activeFile ?? null}
                title={t("Outlined in the picture — hover to preview")}
              />
            )}
          </span>
        )}
        {/* WRAPS rather than truncating. "Detected by InsightFace" does not
            fit a 280 px sidebar beside a 56 px crop and three buttons, and an
            ellipsis lands in the middle of the model's name — which is the one
            word on the line worth reading. The crop already makes the row two
            lines tall, so the second one is free. */}
        <span style={{ fontSize: "var(--fs-1)",
          color: "var(--muted-3)", overflow: "hidden", lineHeight: 1.3 }}>
          {/* No confidence number. It is the detector's own score on its own
              scale — 0.84 from one model and 0.84 from another are not the
              same claim — so beside a crop you can see, it read as a fact
              about the face rather than about the run.
              The model names are prefixed, because on their own they read as
              a label for the face rather than as who found it. */}
          {detectors
            ? t("Detected by {models}", { models: detectors })
            : t("added by hand")}
        </span>
      </span>
      {/* ONE way out per row, and which one depends on where the face came
          from. A DETECTED face is dismissed: that is the answer that sticks,
          because a dismissal absorbs the next detection over the same box,
          where a delete just invites the next run to find it again. A face
          somebody DREW is deleted: nothing ever offered it, so there is
          nothing to stop offering. Deleting a detected face is still possible
          — dismiss it, then delete it from Hidden faces — which puts the
          destructive step behind the reversible one instead of beside it.
          NOT while naming: the field, its tick and its cross want the whole
          row, and more buttons beside a 50 px input is not a field anybody can
          type a name into. The row is answering one question then. */}
      {!naming && (
        <span style={{ display: "flex", alignItems: "center", gap: 2,
          flex: "0 0 auto" }}>
          <RowMenu
            title={t("More actions")}
            always
            actions={[
              ...(face.edited ? [{
                icon: "history",
                label: t("Reset the box"),
                hint: t("Back to the detector's rectangle"),
                onClick: () => undoRun(t("Reset the box"), async () => {
                  await api.resetFaceBox(face.id);
                  onChanged();
                }),
              }] : []),
              ...(face.outline ? [{
                icon: "crop_free",
                label: t("Remove the outline"),
                hint: t("The whole-figure shape its people inherit"),
                onClick: () => undoRun(
                  `${t("Removed the outline of")} ${
                    face.subjects[0]?.name || face.subjects[0]?.tag
                    || t("Face")}`,
                  async () => {
                    await api.clearFaceOutline(face.id);
                    onChanged();
                  }),
              }] : []),
              detectors ? {
                icon: "face_retouching_off", label: t("Not a face"),
                danger: true,
                onClick: () => undoRun(t("Marked as not a face"), async () => {
                  await api.updateFace(face.id, { dismissed: true });
                  onChanged();
                }),
              } : {
                icon: "delete", label: t("Delete this face"), danger: true,
                onClick: () => undoRun(t("Deleted the face"), async () => {
                  await api.deleteFace(face.id);
                  onChanged();
                }),
              },
            ]}
          />
        </span>
      )}
    </div>
  );
}

/** A face somebody said was not one: the same row, greyed, with the two things
 *  left to do about it. Not a thumbnail that restores on click — that reads as
 *  "open" and does something else, and there is no way at all to delete one. */
function HiddenFaceLine({ face, t, onHover, onChanged }: {
  face: FaceRow;
  t: (s: string, vars?: Record<string, string>) => string;
  onHover: (f: FaceRow | null, rect: DOMRect | null) => void;
  onChanged: () => void;
}) {
  const detectors = face.models.map(modelLabel).join(" + ");
  return (
    <div className="hoverable"
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "5px 6px 5px 8px", borderRadius: "var(--r-6)",
        background: "var(--panel-2)", border: "1px dashed var(--border)",
      }}>
      {/* Smaller and faded — it is here to be recognised, not read. The
          preview hangs off it rather than off the row, as above. */}
      <img src={api.faceCropUrl(face, 160)} alt=""
        onMouseEnter={(e) => onHover(face, e.currentTarget.getBoundingClientRect())}
        onMouseLeave={() => onHover(null, null)}
        style={{ width: 40, height: 40, objectFit: "cover", borderRadius: "var(--r-3)",
          flex: "0 0 auto", opacity: 0.5, border: "1px solid var(--border)" }} />
      <span style={{ minWidth: 0, flex: 1, display: "flex",
        flexDirection: "column", gap: 1 }}>
        <span style={{ fontSize: "var(--fs-3)", color: "var(--muted-2)" }}>
          {t("Not a face")}
        </span>
        <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-3)",
          overflow: "hidden", lineHeight: 1.3 }}>
          {detectors
            ? t("Detected by {models}", { models: detectors })
            : t("added by hand")}
        </span>
      </span>
      <span style={{ display: "flex", alignItems: "center", gap: 2,
        flex: "0 0 auto" }}>
        <FaceAction icon="undo" title={t("It is a face after all")}
          onClick={() => { void api.updateFace(face.id, { dismissed: false })
            .then(onChanged); }} />
        <FaceAction icon="delete" title={t("Delete this face")} danger
          onClick={() => { void api.deleteFace(face.id).then(onChanged); }} />
      </span>
    </div>
  );
}

/** One of a face row's actions. The title carries what the ⋯ menu's label and
 *  hint used to say — a button with no words has to say them somewhere. */
function FaceAction({ icon, title, danger, disabled, onClick }: {
  icon: string; title: string; danger?: boolean; disabled?: boolean;
  onClick: () => void;
}) {
  const [hot, setHot] = React.useState(false);
  return (
    <span
      className="row-action"
      title={title}
      onClick={(e) => { e.stopPropagation(); if (!disabled) onClick(); }}
      onMouseEnter={() => setHot(true)}
      onMouseLeave={() => setHot(false)}
      style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        flex: "0 0 auto",
        width: 26, height: 26, borderRadius: "var(--r-3)",
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.4 : 1,
        color: hot && !disabled ? (danger ? "var(--red-text)" : "var(--text)")
          : "var(--muted-3)",
        background: hot && !disabled ? "var(--panel)" : "transparent",
      }}
    >
      <Icon name={icon} size={16} />
    </span>
  );
}

/** One person, at a face or not. */
function PersonLine({ row, indented, picked, selProps, flash, open, t,
                     rangeLabel, onToggleDate, onEdit, onShowInList,
                     searchActions, onRemove, onConfirm, onReject, onChanged,
                     onClearOutline, outlineBoxes, activeFile,
                     activeFileId, ordinal, onDragStart, onDragEnd }: {
  row: PersonRow;
  indented: boolean;
  /** When in the film they are on screen — null off a film, or for a tag with
   *  no ranges (which means "throughout", not "never"). */
  rangeLabel: string[] | null;
  picked: boolean;
  selProps?: {
    onMouseDown: (e: React.MouseEvent) => void;
    onMouseEnter: () => void;
    onClick: (e: React.MouseEvent) => void;
  };
  flash: boolean;
  open: boolean;
  t: (s: string, vars?: Record<string, string>) => string;
  onToggleDate: () => void;
  onEdit: () => void;
  onShowInList: () => void;
  /** Find them in the Library / narrow the running search to them. */
  searchActions: RowAction[];
  onRemove: () => void;
  /** The two answers to a guess. */
  onConfirm: () => void;
  onReject: () => void;
  onChanged: () => void;
  /** Present exactly while the appearance HAS a drawn outline: the ⋯ menu's
   *  way to take it off again. Drawing one is the canvas's face|person
   *  switch, not a per-row action any more. */
  onClearOutline?: () => void;
  /** The outline this row would train with — its own subject box, or the
   *  face's outline where it has none — for the small preview icon. */
  outlineBoxes?: TagBox[];
  activeFile?: FileVersion | null;
  activeFileId?: number | null;
  /** 1-based, present only when the subject is on the item more than once. */
  ordinal?: number | null;
  /** The drag HANDLE's start — reordering, and carrying the row onto (or
   *  off) a face. The row's own drag is the selection paint, so only the
   *  grip starts one. */
  onDragStart?: (e: React.DragEvent) => void;
  onDragEnd?: () => void;
}) {
  const { subject, appearance } = row;
  const lang = useLang();
  const t2 = useT();
  const label = whenLabel(appearance.when, subject.since_date, lang,
                          (a) => t2("age {n}", { n: a }));
  const guess = appearance.assigned_by === "suggested";
  return (
    // The flash is the shared FADING one, not a tint that snaps off: a
    // highlight that vanishes is one you can miss by blinking. It is an inset
    // shadow, so the row's own picked / guessed colours stay underneath.
    <div className={flash ? "hoverable mc-flash" : "hoverable"}
      data-subject={subject.tag} {...(selProps ?? {})}
      style={{
        display: "flex", flexDirection: "column", gap: 4,
        marginLeft: indented ? 22 : 0, marginTop: indented ? 4 : 0,
        padding: "5px 6px 5px 4px", borderRadius: "var(--r-4)",
        background: rowBackground(picked, "var(--panel-2)"),
        border: `1px solid ${picked ? "var(--accent)"
          : guess ? "var(--yellow)" : "var(--border)"}`,
        // A row you can pick says so, like the tag rows — and only where there
        // IS a selection to join.
        cursor: selProps ? "pointer" : undefined,
        // NO transition on the picked colours. Picking is not something the
        // row does over 400 ms — a click that takes that long to show reads as
        // a click that has not registered, and dragging across a run of rows
        // left a comet tail of half-tinted ones behind the pointer. The FLASH
        // still fades, because that one is announcing itself rather than
        // answering; it rides on box-shadow, so it is unaffected by this.
      }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, minHeight: 20,
        paddingLeft: 2 }}>
        {onDragStart && (
          <span
            draggable
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            // Not the selection paint's business: the grip is the one part
            // of the row that starts a CARRY rather than a pick.
            onMouseDown={(e) => e.stopPropagation()}
            title={t("Drag to reorder, or onto a face")}
            style={{ display: "flex", flex: "0 0 auto", cursor: "grab",
              color: "var(--muted-3)", marginLeft: -4, marginRight: -3 }}
          >
            <Icon name="drag_indicator" size={13} />
          </span>
        )}
        <Icon name={RECORD_ICON.subject} size={15}
          color={guess ? "var(--yellow-text)" : "var(--muted-2)"} />
        {/* A GUESS reads as one: the name in amber, with a question mark. The
            score stays secondary — it is the machine's own scale, and it is
            the name that is being asked about, not the number. */}
        <span style={{ flex: "0 1 auto", minWidth: 0, fontSize: "var(--fs-3)",
          color: guess ? "var(--yellow-text)" : "var(--text)",
          overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap" }}
          title={`${subject.display_name || subject.tag}\n${subject.tag}`}>
          {subject.display_name || subject.tag}
          {guess && "?"}
        </span>
        {/* Which of their several entries this is. The NAME's size, not the
            comment's: it completes the name rather than describing it. */}
        {ordinal != null && (
          <span style={{ flex: "0 0 auto", fontSize: "var(--fs-3)",
            color: "var(--muted-2)" }}>
            ({ordinal})
          </span>
        )}
        {/* The comment is what tells two people of one name apart — which is
            the case the display name cannot answer alone, so it belongs beside
            it rather than in a tooltip. Secondary, and the first thing to be
            truncated: it disambiguates a name, it is not one. */}
        {subject.comment && (
          <span style={{ flex: "0 1 auto", minWidth: 0, fontSize: "var(--fs-2)",
            color: "var(--muted-2)", overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            title={subject.comment}>
            {subject.comment}
          </span>
        )}
        {guess && appearance.match_score != null && (
          <span style={{ flex: "0 0 auto", fontSize: "var(--fs-1)",
            color: "var(--muted-2)" }}>
            {Math.round(appearance.match_score * 100)}%
          </span>
        )}
        {/* The outline preview, the tag rows' own icon: hover shows the
            picture with the shape drawn on it. It also shows an outline the
            row INHERITS from its face — that is what a training run would
            use, and the preview exists to answer exactly that. */}
        {outlineBoxes && outlineBoxes.length > 0 && (
          <TagAnnotation
            boxes={outlineBoxes}
            activeFileId={activeFileId ?? null}
            activeFile={activeFile ?? null}
            // Grey when the shape is the FACE's, merely inherited: the icon
            // then says "covered", not "drawn here".
            inherited={appearance.box == null}
            title={appearance.box != null
              ? t("Outlined in the picture — hover to preview")
              : t("Inherits the face's outline — hover to preview")}
          />
        )}
        <span style={{ flex: 1 }} />
        {/* Two answers, two buttons — not a menu. A guess is a question with
            exactly two answers, and burying either makes agreeing cost two
            clicks; this is the shape the face suggestion has always had. */}
        {guess && (<>
          <IconButton icon="check" size={20} glyph={16} reveal="hover" color="var(--yellow-text)" title={t("Yes, that is them")}
            onClick={(e) => { e.stopPropagation(); onConfirm(); }} style={{ flex: "0 0 auto" }} />
          <IconButton icon="close" size={20} glyph={16} reveal="hover" title={t("No, that is somebody else")}
            onClick={(e) => { e.stopPropagation(); onReject(); }} style={{ flex: "0 0 auto" }} />
        </>)}
        <RowMenu
          title={t("More actions")}
          // Always visible: this menu holds the date, the subject record and
          // the way to the subjects list, none of which is anywhere else, so
          // on hover they existed only for somebody who already knew.
          always
          actions={[
            ...(appearance.id ? [{
              icon: "schedule",
              label: open ? t("Close the date")
                : label ? t("Change the date or age") : t("Set the date or age"),
              hint: t("How old they are in this item"),
              onClick: onToggleDate,
            }] : []),
            { icon: "edit", label: t("Edit subject…"),
              hint: t("It is shared, so this changes it everywhere"),
              onClick: onEdit },
            { icon: "person_search", label: t("Show in the subjects list"),
              hint: t("Their record, and every face given their name"),
              onClick: onShowInList },
            ...(onClearOutline ? [{
              icon: "crop_free",
              label: t("Remove the outline"),
              hint: t("Their drawn box or polygon in this picture"),
              onClick: onClearOutline,
            }] : []),
            ...searchActions,
            { icon: "close", label: t("Remove from this item"), danger: true,
              onClick: onRemove },
          ]}
        />
      </div>
      {label && !open && (
        <span style={{ paddingLeft: 23, fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
          color: "var(--muted-2)" }}>
          {label}
        </span>
      )}
      {/* WHEN in the film, which is a different question from the age above:
          one says how old they are in the picture, the other which stretches
          of it they are in. */}
      {!open && <TagRangeLine label={rangeLabel} indent={23} />}
      {open && (
        <WhenEditor
          appearance={appearance}
          since={subject.since_date}
          onDone={() => { onToggleDate(); onChanged(); }}
          t={t}
        />
      )}
    </div>
  );
}

/** The date/age fields for one appearance. Either half derives the other.
 *
 *  Exported because the FACES TAB asks the same question of the same row:
 *  how old somebody is in a picture is a fact about the APPEARANCE, and two
 *  editors for one field is how the "saying it confirms a guess" rule gets
 *  written down once and forgotten in the other. */
export function WhenEditor({ appearance, since, onDone, t }: {
  appearance: SubjectAppearance;
  since: number | null;
  onDone: () => void;
  t: (s: string, vars?: Record<string, string>) => string;
}) {
  const lang = useLang();
  const [date, setDate] = useState(
    appearance.when?.date ? formatDate(appearance.when.date, lang) : "");
  const [age, setAge] = useState(
    appearance.when?.age != null ? String(appearance.when.age) : "");

  const save = async () => {
    const d = date.trim() ? parseDate(date, lang) : null;
    const a = age.trim() ? Number(age) : null;
    await api.editAppearance(appearance.id, {
      when: { date: d, age: Number.isFinite(a as number) ? a : null },
      // Saying how old somebody is in a picture is agreeing that it is them:
      // nobody dates a guess they are about to reject. So a still-pending
      // assignment is confirmed by the same save, rather than being left in a
      // state where a later run could overwrite the name the date belongs to.
      ...(appearance.assigned_by === "suggested" ? { confirm: true } : {}),
    });
    onDone();
  };

  // The shared dense field, one step shorter: it sits INSIDE a row.
  const dateField: React.CSSProperties = {
    ...fieldStyleSm, height: 26, padding: "0 7px", borderRadius: "var(--r-3)", fontSize: "var(--fs-2)",
  };
  return (
    // The editor sits INSIDE the row, which selects itself when clicked, so
    // typing a date used to pick the row as a side effect. Every other control
    // on the row stops its own events; this one is a strip of them.
    <div onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      style={{ display: "flex", gap: 6, alignItems: "center",
        paddingLeft: 23, paddingTop: 2 }}>
      <input value={date} placeholder={t("year or date")} style={dateField}
        onChange={(e) => {
          setDate(e.target.value);
          const d = e.target.value.trim() ? parseDate(e.target.value, lang) : null;
          if (d && since) setAge(String(ageAt(since, d) ?? ""));
        }} />
      <input value={age} placeholder={t("age")} style={{ ...dateField, width: 64 }}
        onChange={(e) => {
          setAge(e.target.value);
          const n = Number(e.target.value);
          if (Number.isFinite(n) && since) setDate(formatDate(dateFromAge(since, n), lang));
        }} />
      <span onClick={() => void save()} title={t("Save")}
        style={{ cursor: "pointer", display: "flex", color: "var(--accent)" }}>
        <Icon name="check" size={16} />
      </span>
    </div>
  );
}
