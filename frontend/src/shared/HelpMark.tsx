/** THE `?` MARK, and the popover it opens — one glyph and one shell.
 *
 *  Two things drew a "what is this" mark: the tag lists' description mark
 *  (`app/components/DescribedFields.tsx: DescriptionMark`, which hovers,
 *  pins, walks tag links and follows the keyboard) and the training form's
 *  help button (a circled letter with its own portal, its own placement
 *  maths and its own scroll listener). They looked different and closed
 *  differently for no reason either could have given. The glyph and the
 *  panel are here; the description mark keeps its behaviour on top of
 *  them, and `HelpMark` is the plain case — a heading and a paragraph,
 *  opened by a click, closed by a press elsewhere, Escape, or a scroll.
 */
import React, { useRef, useState } from "react";
import { Icon } from "./Icon";
import { AnchoredDropdown, useAnchorRect } from "./AnchoredDropdown";
import { useMenuDismiss } from "./useMenuDismiss";

/** The glyph: an inline-flex span so it sits in running text as well as in
 *  a flex row; accent while its popover is open. */
export const HelpGlyph = React.forwardRef<HTMLSpanElement, {
  open: boolean;
  size?: number;
  title?: string;
} & Omit<React.HTMLAttributes<HTMLSpanElement>, "title">>(
  function HelpGlyph({ open, size = 14, title, style, ...rest }, ref) {
    return (
      <span
        ref={ref}
        title={title}
        {...rest}
        style={{
          flex: "0 0 auto", display: "inline-flex", alignItems: "center",
          verticalAlign: "-2px", cursor: "pointer",
          color: open ? "var(--accent)" : "var(--muted-2)",
          ...style,
        }}
      >
        <Icon name="help" size={size} />
      </span>
    );
  });

/** The panel: an anchored dropdown whose content is PROSE.
 *
 *  `.mc-copy` opts the text back into selection (the body suppresses it
 *  app-wide so a shift-click over rows never drags one with it); the
 *  mousedown STOP keeps the press from the list under it (a row would
 *  select itself under the popover), and the click stop keeps a selection
 *  drag that ends outside from reading as a press outside. `keepFocus`
 *  also prevents the mousedown's default — for a popover opened from a
 *  FIELD, whose focus (and whose own list) the press must not take; it
 *  makes the text unselectable, which is why it is opt-in. */
export function HelpPanel({ rect, minWidth = 260, raised, keepFocus,
                            onMouseEnter, onMouseLeave, children }: {
  rect: DOMRect | null;
  minWidth?: number;
  raised?: boolean;
  keepFocus?: boolean;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
  children: React.ReactNode;
}) {
  return (
    <AnchoredDropdown rect={rect} minWidth={minWidth} raised={raised}>
      <div
        className="mc-copy"
        onMouseEnter={onMouseEnter}
        onMouseLeave={onMouseLeave}
        onMouseDown={(e) => {
          if (keepFocus) e.preventDefault();
          e.stopPropagation();
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </AnchoredDropdown>
  );
}

const HELP_W = 360;

/** The plain mark: a heading and a paragraph behind a `?`. */
export function HelpMark({ heading, text, tooltip, size = 15 }: {
  heading: string;
  text: string;
  /** The glyph's tooltip — the caller's words ("What does this do?"). */
  tooltip?: string;
  size?: number;
}) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLSpanElement>(null);
  const rect = useAnchorRect(anchor, open);
  // A page scroll closes it — the panel is anchored to a captured rect and
  // would drift away from the row it explains. A scroll INSIDE it must not:
  // the longest of these texts is taller than the panel, and the hook
  // already spares the dropdown's own scrolling.
  useMenuDismiss(open, () => setOpen(false),
                 { within: [anchor], onScroll: true, onResize: true });
  return (
    <>
      <HelpGlyph ref={anchor} open={open} size={size} title={tooltip}
                 onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }} />
      {open && (
        <HelpPanel rect={rect} minWidth={HELP_W}>
          <div style={{ maxWidth: HELP_W - 6, padding: "8px 10px 10px" }}>
            <div style={{ fontSize: "var(--fs-2)", fontWeight: 600, color: "var(--text)",
                          marginBottom: 6 }}>
              {heading}
            </div>
            <div style={{ fontSize: "var(--fs-3)", lineHeight: 1.55, color: "var(--text-3)",
                          whiteSpace: "pre-line" }}>
              {text}
            </div>
          </div>
        </HelpPanel>
      )}
    </>
  );
}
