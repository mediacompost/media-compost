/** THE MEDIA-KIND PICKER — a button whose menu ticks images, videos and
 *  sequences, any subset; empty (or all three) reads "All media". The grid's
 *  filter above the library and the Tags tab's "counted over" share it, so
 *  the two cannot drift into two dialects of one question. Lifted out of
 *  `ItemGrid.tsx`, where it took the grid's two scope toggles as fixed rows;
 *  those ride in `extra` now. */
import React from "react";

import { Icon } from "../../../shared/Icon";
import { Chevron } from "../../../shared/Chevron";
import { useT } from "../../i18n";
import type { Kind } from "../../store";
import { RowMenu, type RowAction } from "../../../shared/RowMenu";

export const MEDIA_KINDS = [
  { kind: "image", label: "Images", icon: "image" },
  { kind: "video", label: "Videos", icon: "movie" },
  { kind: "sequence", label: "Sequences", icon: "collections_bookmark" },
] as const;

export function MediaKindMenu({ selected, onToggle, title, extra = [] }: {
  /** The kinds ticked; empty means every kind. */
  selected: readonly string[];
  onToggle: (k: Kind) => void;
  /** The trigger's tooltip — what the kinds narrow, which differs per host. */
  title: string;
  /** Further toggles under a rule (the grid's "fold sequences" / "show
   *  hidden"); a host with none passes nothing and gets no rule. */
  extra?: readonly { label: string; on: boolean; toggle: () => void; icon: string }[];
}) {
  const t = useT();
  // Empty *or* every kind checked both mean "no filter" — shown as "All media".
  const isAll = selected.length === 0 || selected.length === MEDIA_KINDS.length;
  const label = isAll
    ? t("All media")
    : MEDIA_KINDS.filter((m) => selected.includes(m.kind)).map((m) => t(m.label)).join(", ");
  // A tick per kind, the menu staying up across ticks; the host's own toggles
  // under a rule. When no explicit filter is set every kind is active, so
  // all three show ticked rather than blank.
  const actions: RowAction[] = [
    ...MEDIA_KINDS.map((m) => ({
      checked: isAll || selected.includes(m.kind), label: t(m.label),
      keepOpen: true, onClick: () => onToggle(m.kind),
    })),
    ...extra.map((x, i) => ({
      checked: x.on, label: t(x.label), keepOpen: true, separated: i === 0,
      onClick: x.toggle,
    })),
  ];
  // The trigger stays neutral regardless of the current filter/toggles —
  // highlighting it (e.g. whenever "Fold sequences" is on, its default)
  // read as a false "active" signal. The selection is conveyed by the
  // label and the checked rows inside the menu instead.
  return (
    <RowMenu always icon="perm_media" title={title} actions={actions} minWidth={180}
      buttonStyle={{
        width: "auto", height: 34, padding: "0 10px", gap: 6, borderRadius: "var(--r-5)",
        fontSize: "var(--fs-3)", maxWidth: 200, border: "1px solid var(--border-strong)",
        background: "var(--panel-2)", color: "var(--text-3)",
      }}
      label={<>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
        <Chevron />
      </>} />
  );
}
