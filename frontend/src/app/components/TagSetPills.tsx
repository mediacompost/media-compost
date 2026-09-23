/** THE ROW OF PILLS — which tag set the Tags tab is about.
 *
 *  THE LIBRARY IS THE FIRST OF THEM. It is not a tag set somebody
 *  imported: its names are the library's own tags and its list is the Items
 *  list. But it is a set in every other way — it owns the categories its
 *  tags are filed in, it has properties, and it EXPORTS as an ordinary
 *  tag-set file — so it belongs in the row rather than beside it, and one
 *  row across both halves is what makes them read as one tab.
 *
 *  THE PILLS ONLY PICK. Their order, their verbs and the switch that hides
 *  one all live in the list behind the pencil (`TagSetManageOverlay`) — a
 *  row of pills is the shortest way to say "this is the set I am looking
 *  at", and everything else it grew was a second door to that list.
 *
 *  Lifted out of the Sets tab so the Items list can draw the same row. It
 *  closes over nothing; every gesture arrives as a prop. */
import React from "react";
import { Button } from "../../shared/Button";

import { compactCount } from "../format";
import { useT } from "../i18n";
import type { TagSetOut } from "../api";
import { Icon } from "../../shared/Icon";

/** THE ROW'S HEIGHT, the Faces page's (owner 2026-09): the Tags tab's two
 *  pages share one top line — the pills here, the cluster filter there, and
 *  the Tags / Faces switch at the right end of both — and its controls are
 *  34 px (`FilterMenu`, the segmented controls). No `Button` size is, so the
 *  pills say it themselves. */
const PILL_H = 34;

export function TagSetPills({
  sets, setId, setPickedId, onManage,
}: {
  sets: TagSetOut[];
  /** Which pill is lit. The LIBRARY's id, or null where its row does not
   *  exist yet — a library that has filed nothing has no set row, and the
   *  pill is still drawn and still lit. */
  setId: number | null;
  setPickedId: (id: number) => void;
  /** The pencil: the list of sets, where one is made, imported, reordered
   *  or taken away. */
  onManage: () => void;
}) {
  const t = useT();
  // A HIDDEN SET HAS NO PILL (owner 2026-09). Hidden is "this set is not
  // offering its names", and the shelf is the row of sets that are — a
  // greyed pill for each one somebody had turned off filled the row with
  // what is deliberately not in use. They are all in the list behind the
  // pencil, which is where hiding and showing happen.
  //  …unless it is the one on screen: hiding the OPEN set from that list
  //  would otherwise leave the row with nothing lit while its names are
  //  still the list below, and the quiet mark on the pill is what says why.
  const shown = sets.filter((x) => x.enabled || x.library || x.id === setId);
  if (!shown.length) return null;
  return (
  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {shown.map((s) => {
            const on = s.id === setId;
            const fg = on ? "var(--on-accent)" : s.enabled ? "var(--text)" : "var(--muted)";
            return (
              // THE PILL IS ONE TARGET AND IT PICKS THE SET (owner 2026-09).
              // It carried a ⋯ of its own — properties, hide, duplicate,
              // export, delete — and a right-click that opened the same
              // rows; every one of them is in the list behind the pencil
              // now, so the menu was a second door a few pixels from the
              // first. A div rather than a button is what is left of that.
              <Button key={s.id} round size="sm" variant={on ? "primary" : "soft"}
                      onClick={() => setPickedId(s.id)} className="hoverable"
                      style={{ color: fg, fontSize: "var(--fs-3)", fontWeight: 500,
                               height: PILL_H }}>
                {/* NO PILL WEARS A LEADING GLYPH (owner 2026-09). The
                    library's had one and then a built-in's, on the reasoning
                    that an icon says WHICH KIND of pill this is — and a row
                    of names where only some rows carry a picture reads as
                    two kinds of thing rather than one row of sets. The names
                    are what tell them apart, the library's leads the row,
                    and the list behind the pencil is where each set's kind
                    is drawn. What IS different about a built-in is that it
                    cannot be edited, and that is a STATE, so it is a mark at
                    the end beside Hidden rather than a glyph in front. */}
                {s.name}
                {/* The count STAYS on hover (it was swapped for the ⋯, the
                    sidebar's `row-count`/`row-actions` shape, which made the
                    pill change width by the difference between the two). */}
                <span style={{ fontWeight: 400, opacity: 0.65, fontVariantNumeric: "tabular-nums" }}>
                  {compactCount(s.entries)}
                </span>
                {/* HIDDEN IS THE MARK, NOT THE WORD (owner 2026-09), and
                    the only pill that can wear it is the OPEN one — every
                    other hidden set is filtered out above. The tags list
                    draws a hidden NAME with this glyph too, so a hidden
                    thing looks the same wherever it is met.
                    It is QUIET — it does nothing when pressed, and says
                    "Hidden" in its title. In the tags list pressing the mark
                    is the way back; here the whole pill is a click target
                    that picks the set, so a second meaning inside it would
                    fire the wrong one. Showing it again is the switch in the
                    list behind the pencil. The namespace rows make the same
                    split. */}
                {!s.enabled && (
                  <span title={t("Hidden")}
                        style={{ display: "flex", alignItems: "center",
                                 opacity: 0.7, flex: "0 0 auto" }}>
                    <Icon name="visibility_off" size={14} />
                  </span>
                )}
                {/* AND A BUILT-IN SAYS THE ONE THING THAT IS DIFFERENT ABOUT
                    IT: its list is read, not edited. A state, so it is a mark
                    at the END beside Hidden rather than a glyph in front of
                    the name — the pill is otherwise a tag set like any other
                    and is drawn like one. Quiet, for the reason the mark
                    above it is: the whole pill is a click target that picks
                    the set, and a second meaning inside it would fire the
                    wrong one. */}
                {s.builtin && (
                  <span title={t("Built-in — duplicate it to edit.")}
                        style={{ display: "flex", alignItems: "center",
                                 opacity: 0.7, flex: "0 0 auto" }}>
                    <Icon name="edit_off" size={14} />
                  </span>
                )}
              </Button>
            );
          })}
          {/* THE PENCIL, and it was a "+" with two rows under it (owner
              2026-09). What it opens is the LIST of sets — make one, import
              one, reorder them, take one away — and a menu of two was only
              ever half of that. A pencil rather than a gear or a list glyph:
              it sits INSIDE the row it edits, so "edit this row of things"
              reads right, where a gear would point back at the Settings page
              this list has just left. */}
          {/* A round pill the height of the others, the glyph dead centre. */}
          <Button round size="sm" variant="soft" icon="edit" title={t("Manage tag sets…")}
                  onClick={onManage} className="hoverable"
                  style={{ width: PILL_H, height: PILL_H, padding: 0,
                           color: "var(--text)" }} />
        </div>
  );
}
