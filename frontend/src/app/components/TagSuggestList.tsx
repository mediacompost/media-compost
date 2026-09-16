/** THE tag suggestion list — one hook and one renderer behind every tag field
 *  (`TagAutocomplete`, `CombinedTagEditor`'s adder, the T overlay).
 *
 *  Three hosts had grown three copies of the same list, and the copies had
 *  drifted: one gated its Create row on the answer being settled and two did
 *  not, one had the `mouseLive` rule and two did not, none scrolled the
 *  highlighted row into view because at six rows nothing ever scrolled. What
 *  is shared here is exactly the half that had drifted — WHICH rows there are
 *  (`suggestRows.ts`: Create first, highlight on the first match), how the
 *  arrows and Enter move through them, how the mouse takes the highlight, and
 *  how a row is drawn. What is NOT shared is the host's own contract with its
 *  input: Escape (two-stage under a persistent field, one-stage on a transient
 *  adder), Tab (the T overlay's second Enter), blur, and when the list is open
 *  at all. Those events land on the host's `<input>`, so the host calls
 *  `handleKey` first and keeps its own `else` branches. */
import React from "react";
import type { TagNameRow } from "../api";
import type { TagTone } from "../quickTags";
import { Icon } from "../../shared/Icon";
import { useT } from "../i18n";
import type { SuggestRow } from "../../shared/suggestRows";
import {
  useSuggestList as useSuggestListShared,
  type SuggestInput, type SuggestList, type SuggestListOpts,
} from "../../shared/useSuggestList";
import { DescriptionMark } from "./DescribedFields";
import { MetaCapsules, metaByCount } from "./MetaCapsules";
import type { TagSuggestion } from "./TagAutocomplete";
import { toggleMarkForName } from "./DescribedFields";

/** The `/api/tags/names` row as the fields read it. Module-level so the
 *  mapping — which fields ride, under which names — is spelled once. */
export const toSuggestion = (r: TagNameRow): TagSuggestion => ({
  name: r.name, comment: r.comment ?? "",
  uses: r.positive,
  metaCounts: r.meta_counts ?? undefined,
  metaTags: r.meta_tags ?? undefined,
  aliasOf: r.alias_of ?? undefined,
  tagSets: r.tag_sets ?? undefined,
  descriptions: r.descriptions ?? undefined,
});

/** WHAT A PICKED ROW WRITES: the tag itself, never an alias's spelling. An
 *  alias row says "→ target", and assigning the alias would redirect to the
 *  target anyway (`get_or_create`'s door) — so the name that lands in the
 *  field is the one the library will actually carry, and what somebody sees
 *  written is what is assigned. One function, so the three hosts cannot
 *  disagree about it. */
export function pickedName(s: TagSuggestion): string {
  return s.aliasOf ?? s.name;
}

/** The app's binding of the shared hook: ⇧Space reads the highlighted
 *  row's `?` through the description marks, which register by name. */
export function useSuggestList<T extends { name: string }>(
  opts: Omit<SuggestListOpts<T>, "describe">,
): SuggestList<T> {
  return useSuggestListShared({ ...opts, describe: toggleMarkForName });
}
export type { SuggestList, SuggestListOpts, SuggestInput };

const rowStyle = (dense: boolean, highlighted: boolean): React.CSSProperties => ({
  display: "flex", alignItems: "center", gap: 8,
  padding: dense ? "7px 10px" : "8px 10px",
  borderRadius: dense ? 6 : 8, cursor: "pointer",
  fontSize: dense ? 12 : 13,
  background: highlighted ? "var(--accent-dim)" : "transparent",
});

/** The list itself: the Create row first, then every match through
 *  `renderRow`, in a scroll container of its own. `maxHeight` is about ten
 *  rows by default — the list scrolls past that rather than growing into
 *  whatever is below the field. */
/** What a row is FOR under a prefixed word — `quickTags.toneOfPrefix`'s
 *  answer, one reading of `-`/`!` for the T field and the sidebar's adder.
 *  Undefined everywhere else — the accent. */
export type RowTone = TagTone;

const TONE_COLOR: Record<RowTone, string> = {
  positive: "var(--green)", negative: "var(--red)", remove: "var(--muted-2)",
};

export function TagSuggestList<T extends { name: string }>({
  list, renderRow, maxHeight = 320, dense = false, fill = false, tone,
  createIcon = "add",
}: {
  list: SuggestList<T>;
  renderRow: (item: T, highlighted: boolean) => React.ReactNode;
  /** The Create row's glyph — `create_new_folder` where what is made is a
   *  group rather than a tag. */
  createIcon?: string;
  maxHeight?: number | string;
  /** The dropdown hosts' metrics (12 px rows); the T overlay is a size up. */
  dense?: boolean;
  /** Size to the FLEX COLUMN it sits in rather than to `maxHeight` — the T
   *  overlay lays its list out in flow under the field, so the window's
   *  bottom is what ends it, whatever sits above the field. */
  fill?: boolean;
  /** Colours the Create row's glyph like the rows under it (`RowTone`). */
  tone?: RowTone;
}) {
  const t = useT();
  return (
    <div {...list.listProps}
         style={fill ? { flex: "1 1 auto", minHeight: 0, overflowY: "auto" }
                     : { maxHeight, overflowY: "auto" }}>
      {/* The Create row is an ORDINARY row — first, and the default, but
          drawn like the matches under it: no rule, no colour of its own. It
          wore green over a separator for a round, which made the one row
          that is different loud on every keystroke (owner decision). */}
      {list.rows.map((row, i) => row.kind === "action" ? (
        // AN ANSWER THAT IS NOT A NAME — the face namer's "Unnamed". Drawn
        // like every other row, with the quiet line the matches use for
        // their comment saying what picking it means.
        <div key={`! ${row.action.id}`} {...list.rowProps(i)}
             style={rowStyle(dense, list.hi === i)}>
          <Icon name={row.action.icon ?? "help"} size={dense ? 14 : 15}
                color="var(--muted-2)" />
          <span>{row.action.label}</span>
          {row.action.hint && (
            <span style={{ color: "var(--muted-2)", fontSize: dense ? 11 : 12,
                           overflow: "hidden", textOverflow: "ellipsis",
                           whiteSpace: "nowrap" }}>
              {row.action.hint}
            </span>
          )}
        </div>
      ) : row.kind === "create" ? (
        <div key=" create" {...list.rowProps(i)} style={rowStyle(dense, list.hi === i)}>
          <Icon name={createIcon} size={dense ? 14 : 15}
                color={tone ? TONE_COLOR[tone] : "var(--accent)"} />
          <span style={{ fontFamily: "var(--mono)" }}>{row.name}</span>
          <span style={{ color: "var(--muted-2)", fontSize: dense ? 11 : 12 }}>
            {t("Create")}
          </span>
        </div>
      ) : !list.isSelectable(i) ? (
        // A row that is only there to be READ — the T overlay's section
        // titles. No row props (so the mouse cannot commit it), no cursor,
        // and never highlighted; the arrows step over it.
        <div key={`${i} ${row.item.name}`}
             style={{ ...rowStyle(dense, false), cursor: "default" }}>
          {renderRow(row.item, false)}
        </div>
      ) : (
        // Index AND name: the browse tree lists a category and a tag of
        // one name in a single list.
        <div key={`${i} ${row.item.name}`} {...list.rowProps(i)}
             style={rowStyle(dense, list.hi === i)}>
          {renderRow(row.item, list.hi === i)}
        </div>
      ))}
    </div>
  );
}

/** A tag's row, the union of what the three hosts used to draw: the icon
 *  (an alias wears `alt_route`), the name — which yields only as a last
 *  resort, the tags-tab rule — the alias's target, the comment (which shrinks
 *  first, willingly), the tag set's capsules heaviest first in the width
 *  left over, the long form behind a `?`, and the library's own count at the
 *  end. Its parent supplies the row box and the highlight. */
export function TagSuggestionRow({ s, highlighted, dense = false, showDescription = true,
                                   raisedPopover = false, tone, autoDescribe,
                                   onPickName }: {
  s: TagSuggestion;
  highlighted: boolean;
  dense?: boolean;
  showDescription?: boolean;
  /** What picking the row would DO, in the T field — assign (green), assign
   *  negatively (red), remove (grey, slashed) — so the list says what it is
   *  for before anything is written. Undefined elsewhere: the accent. */
  tone?: RowTone;
  /** The `?` popover is an `AnchoredDropdown` at `LAYER.popover`; a host
   *  that itself sits above that layer (the T overlay) passes this so the
   *  popover goes to `LAYER.quickTagPopover` instead. */
  raisedPopover?: boolean;
  /** THE HIGHLIGHTED ROW SHOWS ITS `?` BY ITSELF, beside the list. The
   *  quick tag overlay passes the list's own box: what a set says about the
   *  name under the highlight is exactly what somebody is choosing by, and
   *  reaching for a mark with the mouse in a list being driven by the
   *  arrows is the wrong hand. Only for a list that asked for it — every
   *  other autocomplete keeps the popover on request. */
  autoDescribe?: React.RefObject<HTMLElement | null>;
  /** TAKE THE NAME THE POPOVER IS SHOWING — a field's answer to a
   *  description that says "use `solo_focus` instead": follow the link in
   *  it, then press the title. Only a FIELD passes one; a list that is not
   *  a field has nothing to put the name in. */
  onPickName?: (name: string) => void;
}) {
  return (
    <>
      <Icon name={s.aliasOf ? "alt_route" : tone === "remove" ? "label_off" : "sell"}
            size={dense ? 14 : 15}
            color={tone ? TONE_COLOR[tone] : "var(--accent)"} />
      <span style={{ fontFamily: "var(--mono)", flex: "0 1 auto", minWidth: 0,
                     overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}>
        {s.name}
      </span>
      {s.aliasOf && (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 2,
                       color: "var(--accent)", fontFamily: "var(--mono)",
                       fontSize: "var(--fs-2)", flex: "0 0 auto" }}>
          <Icon name="arrow_forward" size={12} /> {s.aliasOf}
        </span>
      )}
      {s.comment && (
        <span style={{ color: "var(--muted-2)", fontSize: "var(--fs-2)",
                       flex: "0 20 auto", minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {s.comment}
        </span>
      )}
      {showDescription && (
        // Straight after the name and comment — what it means, then what the
        // sets say about it — and before the capsules, which take the width
        // left over. The row commits on mousedown, so reading a description
        // must not pick the tag.
        <DescriptionMark
          descriptions={s.descriptions}
          name={s.name}
          size={13}
          raised={raisedPopover}
          besideRef={autoDescribe}
          auto={!!autoDescribe && highlighted}
          onPickName={onPickName}
          onDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
        />
      )}
      <MetaCapsules names={metaByCount(s.metaTags ?? [], s.metaCounts)}
                    counts={s.metaCounts} tagSets={s.tagSets}
                    tinted={highlighted} />
      {/* The library's own count, and ONLY it — what the tag has elsewhere
          lives per meta tag and is said on HOVER, never as a number beside
          this one: two figures in one cell read as one sum. */}
      <span
        title={s.metaCounts && Object.keys(s.metaCounts).length
          ? Object.entries(s.metaCounts)
              .sort((a, b) => b[1] - a[1])
              .map(([n, c]) => `${n} ${c}`).join(" · ")
              + " — elsewhere; counted only when ordering this list"
          : undefined}
        style={{ marginLeft: "auto", display: "flex", alignItems: "baseline",
                 fontFamily: "var(--mono)", fontSize: dense ? 10.5 : 11,
                 color: "var(--muted-3)", flex: "0 0 auto" }}
      >
        {s.uses}
      </span>
    </>
  );
}
