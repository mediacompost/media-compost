/**
 * WHAT THE LIBRARY ALREADY SAYS ABOUT THIS PICTURE — its tags by group, its
 * captions and where its bytes came from.
 *
 * One panel, two overlays. The preview (`QuickLook`) opens it with Tab, and
 * so does the tag-batch session, which is the same question one window
 * along: deciding whether a picture is a `portrait` is a great deal easier
 * when you can see it is already tagged `bust` and `looking_at_viewer`. It
 * lives here rather than in either of them because two copies of a list of
 * an item's tags would be two lists that drift — the grouping rule, the
 * pending marker and the box hover included.
 *
 * The DETAIL is the caller's to fetch: the preview needs it anyway (for the
 * picture's own source file), so a panel that fetched for itself would run
 * the same query twice under two keys.
 */
import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loading } from "../../../shared/Loading";
import { EmptyState } from "../../../shared/EmptyState";
import { IconButton } from "../../../shared/IconButton";
import { useT } from "../../i18n";
import { api, FaceRow, ItemDetail, TagBox, TagInstance, TagSetText } from "../../api";
import { Icon } from "../../../shared/Icon";
import { DescriptionMark } from "../DescribedFields";

/** A box with geometry. Typed on the four fields it READS rather than on
 *  `TagBox`: the same rectangles arrive from a tag (which also carries a time
 *  range) and from a link (which does not), and neither difference matters. */
type Rect = { x?: number | null; y?: number | null;
              w?: number | null; h?: number | null };
const spatial = (boxes: Rect[]) =>
  boxes.filter((b) => b.x != null && b.y != null && b.w != null && b.h != null);

export interface TagGroupRow {
  key: string; label: string; system: boolean; tags: TagInstance[];
}

/** The item's tag instances grouped by tag group, Ungrouped first. Exported
 *  so a caller can memoize it against its own `detail`. */
export function groupTagInstances(detail: ItemDetail | undefined): TagGroupRow[] {
  if (!detail) return [];
  const byGroup = new Map<number | null, TagInstance[]>();
  for (const t of detail.tag_instances) {
    const arr = byGroup.get(t.group_id) ?? [];
    arr.push(t);
    byGroup.set(t.group_id, arr);
  }
  const out: TagGroupRow[] = [];
  if (byGroup.get(null)?.length) {
    out.push({ key: "ungrouped", label: "Ungrouped", system: false,
               tags: byGroup.get(null)! });
  }
  for (const g of detail.tag_groups) {
    const ts = byGroup.get(g.id);
    if (ts && ts.length) {
      out.push({ key: String(g.id), label: g.name, system: !!g.system,
                 tags: ts });
    }
  }
  return out;
}

export function ItemInfoPanel({ detail, groupedTags, onHoverBoxes, onChanged, style }: {
  detail: ItemDetail | undefined;
  groupedTags: TagGroupRow[];
  /** Where a tag's rectangles go while the pointer is on its crop marker —
   *  only the preview can draw them, so a caller with nowhere to put them
   *  passes nothing and the marker is not offered. */
  onHoverBoxes?: (boxes: TagBox[] | null) => void;
  /** A PENDING TAG CAN BE ANSWERED HERE (owner 2026-09): a machine's tag in
   *  a Pending group takes ✓ (approve) and ✕ (dismiss), a face's guess ✓
   *  (agree) and ✕ (reject) — the library sidebar's own answers, one panel
   *  along. The caller refreshes what it holds; without it the rows are
   *  read-only. */
  onChanged?: () => void;
  style?: React.CSSProperties;
}) {
  const t = useT();
  const activeNames = detail?.files.find((f) => f.active)?.names ?? [];
  //: WHAT THE TAG SETS SAY about every name on the panel, in one request —
  //  the `?` beside each name, and the popover a hover on the name opens.
  const names = useMemo(() => [...new Set(groupedTags.flatMap((g) => g.tags.map((x) => x.name)))].sort(),
                        [groupedTags]);
  const { data: described } = useQuery({
    queryKey: ["describe", names.join(",")],
    queryFn: () => api.describeNames(names),
    enabled: names.length > 0, staleTime: 60_000,
  });
  //: A FACE'S GUESS is a pending tag with no placement; answering it means
  //  answering the APPEARANCE, so the item's faces are read where a row
  //  needs them.
  const subjectByTag = useMemo(
    () => new Map((detail?.subjects ?? []).map((sub) => [sub.tag, sub.id])), [detail?.subjects]);
  const hasGuess = groupedTags.some((g) => g.tags.some(
    (x) => x.pending && x.placement_id == null && subjectByTag.has(x.name)));
  const { data: faces } = useQuery({
    queryKey: ["faces", detail?.id],
    queryFn: () => api.faces(detail?.id as number),
    enabled: !!onChanged && !!detail && hasGuess,
  });
  const hasInfo = groupedTags.length > 0
    || (detail?.captions.length ?? 0) > 0 || activeNames.length > 0;
  return (
    <div
      onMouseDown={(e) => e.stopPropagation()}
      style={{
        flex: "0 0 340px", maxHeight: "calc(100vh - 120px)", overflowY: "auto",
        background: "var(--surface-float)",
        border: "1px solid var(--border-strong)",
        borderRadius: "var(--r-7)", padding: "16px 18px",
        boxShadow: "var(--shadow-3)",
        color: "var(--text-2)",
        ...style,
      }}
    >
      {!detail ? (
        <Loading label={t("Loading…")} style={{ padding: 0, fontSize: "var(--fs-3)", color: "var(--muted-2)" }} />
      ) : !hasInfo ? (
        <EmptyState dense line={t("No tags or captions.")} style={{ fontSize: "var(--fs-3)" }} />
      ) : (
        <>
          {groupedTags.length > 0 && (
            <div style={{ marginBottom: 18 }}>
              <div style={panelLabel}>Tags</div>
              {groupedTags.map((g) => (
                <div key={g.key} style={{ marginBottom: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: "var(--fs-1)", fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase", color: g.system ? "var(--accent)" : "var(--muted)", marginBottom: 4 }}>
                    {g.system && <Icon name="auto_awesome" size={12} />}
                    {g.label}
                  </div>
                  {g.tags.map((inst) => (
                    <TagLine key={inst.placement_id ?? inst.name} inst={inst}
                      system={g.system}
                      descriptions={described?.[inst.name]?.descriptions}
                      guess={inst.pending && inst.placement_id == null
                        ? guessedAppearances(faces, subjectByTag.get(inst.name)) : null}
                      subjectId={subjectByTag.get(inst.name) ?? null}
                      onHoverBoxes={onHoverBoxes} onChanged={onChanged} t={t} />
                  ))}
                </div>
              ))}
            </div>
          )}
          {detail.captions.length > 0 && (
            <div style={{ marginBottom: 18 }}>
              <div style={panelLabel}>Captions</div>
              {detail.captions.map((c) => (
                <div key={c.id} style={{ fontSize: "var(--fs-3)", lineHeight: 1.5, color: "var(--text-2)", padding: "4px 0", borderBottom: "1px solid var(--border-soft)" }}>
                  {c.pending && <span style={{ fontSize: "var(--fs-0)", fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--accent)", marginRight: 6 }}>pending</span>}
                  {c.text}
                </div>
              ))}
            </div>
          )}
          {activeNames.length > 0 && (
            <div>
              <div style={panelLabel}>Sources</div>
              {activeNames.map((n) => (
                <div key={n.id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "2px 0", fontSize: "var(--fs-3)", fontFamily: "var(--mono)" }}>
                  <Icon name={n.is_url ? "link" : "draft"} size={13} color="var(--muted)" />
                  {n.is_url ? (
                    <a
                      href={n.name}
                      target="_blank"
                      rel="noreferrer"
                      style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--accent)", textDecoration: "none" }}
                      title={n.name}
                    >
                      {n.name}
                    </a>
                  ) : (
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-2)" }} title={n.name}>
                      {n.name}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** The suggested appearances of one subject on the item's faces — what a
 *  guessed tag's ✓ and ✕ answer. */
function guessedAppearances(faces: FaceRow[] | undefined, subjectId: number | undefined) {
  if (!faces || subjectId == null) return [];
  return faces.filter((f) => !f.dismissed).flatMap((f) =>
    f.subjects.filter((s) => s.subject_id === subjectId && s.assigned_by === "suggested")
      .map((s) => ({ face: f.id, appearance: s.id })));
}

/** ONE TAG OF THE PANEL: the sign, the name, the `?` (the popover opens
 *  from it, as everywhere), the crop marker — and on a pending row the two
 *  answers. */
function TagLine({ inst, system, descriptions, guess, subjectId, onHoverBoxes, onChanged, t }: {
  inst: TagInstance;
  system: boolean;
  descriptions?: TagSetText[];
  guess: { face: number; appearance: number }[] | null;
  subjectId: number | null;
  onHoverBoxes?: (boxes: TagBox[] | null) => void;
  onChanged?: () => void;
  t: (s: string) => string;
}) {
  const sboxes = spatial(inst.boxes);
  // A MACHINE'S TAG IN A PENDING GROUP answers on its placement; a FACE'S
  // GUESS on its appearances (the tag follows). Amber, like everywhere a
  // machine's claim waits.
  const pendingPlacement = !!onChanged && system && inst.pending && inst.placement_id != null;
  const pendingGuess = !!onChanged && !!guess && guess.length > 0 && subjectId != null;
  const amber = inst.pending && !inst.negative;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "2px 0", fontFamily: "var(--mono)", fontSize: "var(--fs-3)" }}>
      <Icon name={inst.negative ? "remove" : "add"} size={13} color={inst.negative ? "var(--red)" : amber ? "var(--yellow)" : "var(--green)"} />
      <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                   color: inst.negative ? "var(--red-text)" : amber ? "var(--yellow-text)" : "var(--text-2)",
                                   textDecoration: inst.negative ? "line-through" : "none" }}>
        {inst.name}
      </span>
      <DescriptionMark descriptions={descriptions} name={inst.name} size={13} />
      <span style={{ flex: 1 }} />
      {sboxes.length > 0 && onHoverBoxes && (
        <span
          onMouseEnter={() => onHoverBoxes(inst.boxes)}
          onMouseLeave={() => onHoverBoxes(null)}
          title="Hover to show the bounding box on the preview"
          style={{ display: "flex", alignItems: "center", cursor: "help", color: "var(--accent)" }}
        >
          <Icon name="crop_free" size={14} />
        </span>
      )}
      {pendingPlacement && (<>
        <IconButton icon="check_circle" size={18} glyph={14} color="var(--green)" title={t("Approve this tag")}
          onClick={(e) => { e.stopPropagation(); void api.approvePlacement(inst.placement_id as number).then(onChanged); }} />
        <IconButton icon="close" size={18} glyph={14} tone="danger" title={t("Dismiss this pending tag")}
          onClick={(e) => { e.stopPropagation(); void api.deleteTagPlacement(inst.placement_id as number).then(onChanged); }} />
      </>)}
      {pendingGuess && (<>
        <IconButton icon="check_circle" size={18} glyph={14} color="var(--green)" title={t("Accept the guess")}
          onClick={(e) => { e.stopPropagation(); void Promise.all(guess!.map(
            (g) => api.editAppearance(g.appearance, { confirm: true }))).then(onChanged); }} />
        <IconButton icon="person_off" size={18} glyph={14} tone="danger" title={t("Reject the guess")}
          onClick={(e) => { e.stopPropagation(); void Promise.all(guess!.map(
            (g) => api.unnameFace(g.face, subjectId as number))).then(onChanged); }} />
      </>)}
    </div>
  );
}

const panelLabel: React.CSSProperties = {
  fontSize: "var(--fs-1)", fontWeight: 600, letterSpacing: "0.06em",
  textTransform: "uppercase", color: "var(--muted)", marginBottom: 8,
};
