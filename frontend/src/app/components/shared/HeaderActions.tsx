/**
 * A window's OWN actions in its header — the ones that leave for somewhere
 * else — spelled out while they fit and folded into a ⋯ menu when they do
 * not. Every half of the item window uses it, which is what keeps one half's
 * "Show in library" from wording itself differently from another's.
 */
import React, { useLayoutEffect, useRef, useState } from "react";
import { Button } from "../../../shared/Button";
import { Icon } from "../../../shared/Icon";
import { CHROME_BTN } from "./iconButtons";
import { RowMenu } from "./RowMenu";

/** One of the window's own actions, in the header. */
export interface HeaderAction {
  key: string;
  icon: string;
  label: string;
  title: string;
  /** Opens a window of its own — marked with the outward arrow. */
  external?: boolean;
  onClick: () => void;
}

/**
 * The header's MIDDLE: the item's name (and whatever chips go with it),
 * CENTRED, with the window's own actions after it — spelled out while they fit
 * and folded into a ⋯ menu when they do not.
 *
 * It owns both halves because the fold has to be decided from a width that
 * does NOT depend on the fold. This element is the flexible middle
 * (`flex: 1 1 0`), so its width is whatever the fixed sides — undo/redo, the
 * menus, the theme and save buttons — leave over, the same whether the actions
 * are spelled out or folded. Splitting that space between the name and the
 * actions inside it is then arithmetic on three measured numbers:
 *
 *   fold when   width  <  what the name needs  +  what the actions need
 *
 * so the ACTIONS go first and the name only truncates once they are already a
 * ⋯. The other way round was tried (fold only once the name was down to a
 * stub) and reads worse: the name has a tooltip and can be read in the tab
 * strip, while a button squeezed off the end is simply gone.
 *
 * Both needs are measured from `scrollWidth` while the thing is showing and
 * REMEMBERED, because each one's natural width is unmeasurable in the state
 * its absence produces — asked again while folded, "does a ⋯ fit" is always
 * yes, and the buttons would flap across one pixel of window width. The
 * name's need is its laid-out width PLUS what the ellipsis hides, which is
 * what makes that number the same whether it is truncated or not.
 *
 * The two own-window editors share it, which is what keeps one window's
 * "Show in library" from wording itself differently from the other's.
 */
export function HeaderActions({ actions, children, alwaysFolded, t }: {
  actions: HeaderAction[];
  /** The name, and any chips that belong beside it. The first child is the one
   *  expected to truncate. */
  children?: React.ReactNode;
  /** Never spell the actions out — the ⋯ at every width. The annotator asks
   *  for this: its actions are ways OUT of the window rather than things you
   *  do to the picture, so two labelled buttons over the canvas were the
   *  loudest thing in a header whose job is to name the file. Folded, the
   *  header is the name and the menu is where you go looking for a way out. */
  alwaysFolded?: boolean;
  /** REQUIRED, like the rest of the shared editor chrome — optional was a
   *  silent-English hole. The image editor is English throughout (Save, Undo,
   *  Revert…), so a German ⋯ menu in the middle of it would read worse than
   *  the source; it says so by passing an identity rather than by omission. */
  t: (s: string, vars?: Record<string, string>) => string;
}) {
  const tr = t;
  const box = useRef<HTMLDivElement>(null);
  const lead = useRef<HTMLDivElement>(null);
  const row = useRef<HTMLDivElement>(null);
  const need = useRef(0);
  const [avail, setAvail] = useState(Infinity);
  const [leadNeed, setLeadNeed] = useState(0);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setAvail(el.getBoundingClientRect().width);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // What each half needs, re-read after every render. `scrollWidth` rather
  // than the bounding box: both are allowed to overflow for the instant before
  // the measurement lands, and the box would report the clipped width.
  //
  // The name's natural width is its own laid-out width PLUS whatever the
  // ellipsis is hiding — which is what makes this number the same whether it
  // is currently truncated or not, and so a stable thing to compare against.
  useLayoutEffect(() => {
    if (row.current) need.current = row.current.scrollWidth;
    const el = lead.current;
    if (!el) return;
    // The element that ELLIPSISES, which is not necessarily the first child:
    // the name now sits in a two-line block with its measurements, and that
    // block's own scrollWidth never exceeds its box (the span inside it is
    // what clips). Marked rather than guessed — see `ItemTitle`.
    const first = el.querySelector("[data-truncates]") ?? el.firstElementChild;
    const hidden = first ? Math.max(0, first.scrollWidth - first.clientWidth) : 0;
    const want = el.scrollWidth + hidden;
    setLeadNeed((v) => (Math.abs(v - want) > 1 ? want : v));
  });

  // `actions.length` guards the folded case as well: a ⋯ that opens an empty
  // menu is a button that does nothing (an item with no actions at all — a
  // sequence, a not-yet-loaded detail — is exactly that case).
  const tight = actions.length > 0
    && (!!alwaysFolded || (need.current > 0 && avail < leadNeed + need.current));

  return (
    <div ref={box} style={{ flex: 1, minWidth: 0, display: "flex",
      alignItems: "center", gap: 8, position: "relative" }}>
      {/* LEFT-ALIGNED, right after the mode switch. It was centred in what the
          fixed sides left over, which is a position that MOVES: the sides are
          the mode switch on one hand and the ⋯ / theme / Save cluster on the
          other, and Save changing width (or an action appearing) slid the
          name sideways under the pointer. Against the left edge it is in one
          place, and it is also where a title is looked for. */}
      <div ref={lead} style={{ flex: "1 1 0", minWidth: 0, display: "flex",
        alignItems: "center", justifyContent: "flex-start", gap: 8,
        overflow: "hidden" }}>
        {children}
      </div>
      {tight ? (
        <RowMenu always icon="more_horiz" title={tr("More actions")}
          buttonStyle={{ ...CHROME_BTN, flex: "0 0 auto" }}
          actions={actions.map((a) => ({
            icon: a.icon, label: a.label,
            hint: a.title !== a.label ? a.title : undefined,
            trailingIcon: a.external ? "arrow_outward" : undefined,
            onClick: a.onClick,
          }))} />
      ) : (
        <div ref={row} style={{ display: "flex", alignItems: "center", gap: 6,
          flex: "0 0 auto" }}>
          {actions.map((a) => (
            <Button variant="ghost" size="sm"
       key={a.key}
       onClick={a.onClick}
       title={a.title} style={{ flex: "0 0 auto" }}>
              <Icon name={a.icon} size={17} />
              {a.label}
              {a.external && (
                <Icon name="arrow_outward" size={14} color="var(--muted-2)" />
              )}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
