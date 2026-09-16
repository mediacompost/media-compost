/**
 * The caption editor's text box, and the ⌘F bar over it.
 *
 * `AutoTextarea` lived in `PropertiesPanel.tsx`; it is here because the find
 * layer needs it and importing it back out of that file would be a cycle.
 * Both windows render the captions section, so both get this.
 */
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef,
                useState } from "react";

import { Icon } from "../../shared/Icon";
import {
  findMatches, highlightRuns, matchAt, replaceAll, replaceOne, stepMatch,
} from "../../shared/findReplace";

/** The nearest ancestor that actually scrolls — what a measurement has to put
 *  back (see `AutoTextarea`). Walks by COMPUTED overflow rather than by a
 *  class or a marker: the panels here are styled inline throughout, and the
 *  scroller is a different element in the library sidebar, the annotator's and
 *  a dialog's body. */
function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let n = el.parentElement; n; n = n.parentElement) {
    const o = getComputedStyle(n).overflowY;
    if ((o === "auto" || o === "scroll") && n.scrollHeight > n.clientHeight) {
      return n;
    }
  }
  return null;
}

/** A textarea that grows to fit its content (no inner scrollbar), used for
 *  caption editing so the whole text stays visible while typing. */
const AutoTextarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { minRows?: number }
>(function AutoTextarea({ minRows = 2, style, value, ...rest }, ref) {
  const inner = useRef<HTMLTextAreaElement | null>(null);
  const setRef = (el: HTMLTextAreaElement | null) => {
    inner.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) (ref as React.MutableRefObject<HTMLTextAreaElement | null>).current = el;
  };
  const resize = () => {
    const el = inner.current;
    if (!el) return;
    // MEASURING COSTS A COLLAPSE, SO THE SCROLL POSITION IS PUT BACK BY HAND.
    // `height: auto` drops the box to its `rows` height for the length of the
    // measurement, the panel's own scrollHeight drops with it, and the
    // browser CLAMPS its scrollTop to the shorter content — which growing
    // back does not undo. That is the whole of "editing a caption jumps the
    // panel somewhere else whenever a character is deleted or a selection is
    // replaced": typing more only ever grows the box, so the clamp never
    // fires, while anything that SHRINKS it lands on a scroll position
    // nobody chose.
    //
    // Nothing is ever painted collapsed — both writes happen inside one
    // layout, in a layout effect — so this is a measurement artefact and not
    // a visible state. Restoring rather than avoiding the collapse: the
    // shrink direction genuinely needs a fresh `scrollHeight`, and there is
    // no way to ask for one without letting the box find its own size.
    const scroller = scrollParent(el);
    const top = scroller ? scroller.scrollTop : 0;
    el.style.height = "auto";
    const want = el.scrollHeight + "px";
    if (el.style.height !== want) el.style.height = want;
    if (scroller && scroller.scrollTop !== top) scroller.scrollTop = top;
  };
  useLayoutEffect(resize, [value]);
  return (
    <textarea
      ref={setRef}
      value={value}
      rows={minRows}
      style={{ ...style, resize: "none", overflow: "hidden" }}
      {...rest}
    />
  );
});

export { AutoTextarea, scrollParent };

// ---------------------------------------------------------------------------
// FIND AND REPLACE, over one caption.
//
// A caption grows into a paragraph — a generated one especially — and the
// thing anybody wants to do to a paragraph they did not write is change one
// word everywhere it appears. The browser's own ⌘F cannot: it searches the
// PAGE, and a `<textarea>`'s value is not page text, so it finds nothing and
// says so. So the key is taken while a caption is being edited, and given
// back the moment the bar closes.
//
// THE HIGHLIGHT IS A LAYER BEHIND THE BOX. A textarea cannot style a range of
// its own text — there is no API for it and never has been — so the matches
// are drawn on a div holding the SAME STRING, positioned under a textarea
// whose background is transparent. That only lines up if the two boxes agree
// to the pixel about font, padding, border and wrapping, which is why the
// metrics below are shared rather than written twice, and why this is worth
// doing only because `AutoTextarea` never scrolls: it grows to its content,
// so there is no scroll position to keep in step.

/** What both layers must agree about, or the highlight sits off the text. */
const SHARED: React.CSSProperties = {
  padding: "8px 10px",
  border: "1px solid transparent",
  borderRadius: "var(--r-4)",
  fontSize: "var(--fs-4)",
  lineHeight: 1.5,
  fontFamily: "inherit",
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
  boxSizing: "border-box",
};

/** ONE HEIGHT for everything in the bar, so the two rows line up and the
 *  icon buttons are square rather than nearly-square. */
const BAR_H = 24;

/** The leading glyph of each row. It is what makes the two inputs start at
 *  the same x — without it "find" and "replace with" would be two fields at
 *  two different left edges, which is the thing that reads as unfinished. */
const barIcon: React.CSSProperties = {
  width: 18, flex: "0 0 auto", display: "flex", alignItems: "center",
  justifyContent: "center", color: "var(--muted-2)",
};

/** A word button — Replace, All. */
const barBtn: React.CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center",
  height: BAR_H, padding: "0 9px", borderRadius: "var(--r-2)",
  border: "1px solid var(--border-strong)", background: "transparent",
  color: "var(--text-2)", fontSize: "var(--fs-2)", cursor: "pointer",
  fontFamily: "inherit", whiteSpace: "nowrap",
};

/** A glyph button — the two arrows. Square, borderless, and quiet until it
 *  is hovered: three bordered boxes in a row that narrow read as a control
 *  panel rather than as a step through the matches. */
const barIconBtn: React.CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center",
  width: BAR_H, height: BAR_H, flex: "0 0 auto", padding: 0,
  borderRadius: "var(--r-2)", border: "1px solid transparent", background: "transparent",
  color: "var(--muted)", cursor: "pointer",
};

/** A disabled control says so — a styled `<button>` looks identical
 *  disabled unless it is told not to, and "Replace" that does nothing when
 *  pressed reads as broken rather than as unavailable. */
function off(base: React.CSSProperties, disabled: boolean): React.CSSProperties {
  return disabled
    ? { ...base, opacity: 0.4, cursor: "default", pointerEvents: "none" }
    : base;
}

const barInput: React.CSSProperties = {
  height: BAR_H, minWidth: 0, flex: 1, padding: "0 7px", borderRadius: "var(--r-2)",
  border: "1px solid var(--border-strong)", background: "var(--bg)",
  color: "var(--text)", fontSize: "var(--fs-3)", outline: "none",
  fontFamily: "inherit",
};

export interface FindableCaptionProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  value: string;
  onValue: (next: string) => void;
  /** The border the box wears — the caller owns it (a duplicate caption is
   *  yellow), and the highlight layer has to carry the same WIDTH or the
   *  text starts a pixel off. */
  borderColor: string;
  t: (s: string, vars?: Record<string, string>) => string;
}

/** A caption box with ⌘F over it.
 *
 * The ref is FORWARDED as well as kept, because both boxes that use this
 * want it: the find bar needs the element to place a selection on, and the
 * caller needs it too — Duplicate copies a caption into the add box and then
 * focuses it with the caret at the end.
 */
export const FindableCaption = React.forwardRef<
  HTMLTextAreaElement, FindableCaptionProps
>(function FindableCaption({ value, onValue, borderColor, t,
                            onKeyDown, style,
                            ...rest }, outerRef) {
  const ta = useRef<HTMLTextAreaElement | null>(null);
  const bindTa = useCallback((el: HTMLTextAreaElement | null) => {
    ta.current = el;
    if (typeof outerRef === "function") outerRef(el);
    else if (outerRef) outerRef.current = el;
  }, [outerRef]);
  const findRef = useRef<HTMLInputElement | null>(null);
  const [open, setOpen] = useState(false);
  const [needle, setNeedle] = useState("");
  const [into, setInto] = useState("");
  const [at, setAt] = useState(0);

  const matches = useMemo(() => findMatches(value, needle), [value, needle]);
  // The current match has to survive the text changing under it — a replace
  // removes one — so it is clamped rather than trusted.
  const current = matches.length ? Math.min(at, matches.length - 1) : -1;

  /** Show the match in the box: selected, so it is visible in the textarea's
   *  own rendering as well as in the layer behind it. */
  const reveal = useCallback((i: number) => {
    const m = matches[i];
    const el = ta.current;
    if (!m || !el) return;
    el.setSelectionRange(m.start, m.end);
  }, [matches]);

  const step = (by: 1 | -1) => {
    const next = stepMatch(matches.length, current, by);
    setAt(next);
    // Focus the BOX to show the selection, then hand the keyboard back to
    // the find field — otherwise Enter would go to the caption.
    reveal(next);
    findRef.current?.focus();
  };

  const openBar = () => {
    setOpen(true);
    // Seed from the caret: what somebody selected before pressing ⌘F is
    // almost always what they meant to search for.
    const el = ta.current;
    if (el && el.selectionEnd > el.selectionStart) {
      const picked = value.slice(el.selectionStart, el.selectionEnd);
      if (!picked.includes("\n")) setNeedle(picked);
    }
    setAt(el ? matchAt(findMatches(value, needle), el.selectionStart) : 0);
  };

  const close = () => {
    setOpen(false);
    ta.current?.focus();
  };

  // AN EMPTY BOX HAS NOTHING TO FIND IN, so the bar puts itself away when the
  // text goes. That is what closes it on SAVE without the caller reaching in:
  // adding a caption clears the draft, and a find bar left standing over an
  // empty add box is a control aimed at nothing. The needle goes with it, or
  // reopening would come back matching the caption before last.
  useEffect(() => {
    if (open && value === "") { setOpen(false); setNeedle(""); setAt(0); }
  }, [open, value]);

  const doReplace = () => {
    if (current < 0) return;
    const { text, caret } = replaceOne(value, matches, current, into);
    onValue(text);
    // Stay on the same ordinal: after a replacement the match that WAS next
    // has moved into this slot, so the bar walks forward by standing still.
    setAt((i) => Math.max(0, Math.min(i, matches.length - 2)));
    requestAnimationFrame(() => ta.current?.setSelectionRange(caret, caret));
  };

  const doReplaceAll = () => {
    if (!matches.length) return;
    onValue(replaceAll(value, needle, into));
    setAt(0);
  };

  // ⌘F / Ctrl+F while the box has focus. Registered on the BOX rather than
  // on the window: the sidebar can hold several caption fields, and the one
  // being typed in is the one the bar belongs to.
  const keys = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "f") {
      e.preventDefault();
      e.stopPropagation();
      openBar();
      requestAnimationFrame(() => findRef.current?.select());
      return;
    }
    onKeyDown?.(e);
  };

  const runs = highlightRuns(value, matches);
  return (
    // ONE BOX WHEN THE BAR IS OPEN. The bar belongs to the caption under it,
    // so it is attached to it: no gap, the corners rounded only on the
    // outside, and the edge between them drawn ONCE (the bar has no bottom
    // border; the box's own top border is the line). The bar also takes the
    // caption's border colour, or the seam would be two different greys
    // meeting halfway down one control.
    <div style={{ display: "flex", flexDirection: "column",
                  gap: open ? 0 : 6 }}>
      {open && (
        // TWO ROWS, one question each: what to find, and what to put there.
        // Side by side they were two fields fighting for a 280 px sidebar,
        // wrapping their own buttons onto a third line and off the panel.
        // Stacked, each row is a sentence that fits, and the two inputs
        // start at the same x because both rows lead with a glyph.
        <div
          onMouseDown={(e) => {
            // NOTHING IN THE BAR TAKES FOCUS. A press on a button blurs the
            // field, and the caller hangs the big grid preview off that
            // focus — so every jump between matches unmounted the picture
            // and mounted it again a frame later, which is the flash.
            // Refusing the default keeps the caret where it is, which is
            // also what keeps the textarea's selection visible.
            if ((e.target as HTMLElement).tagName !== "INPUT") e.preventDefault();
          }}
          style={{
            display: "flex", flexDirection: "column", gap: 6,
            padding: 8,
            borderRadius: "8px 8px 0 0",
            background: "var(--panel-2)",
            border: `1px solid ${borderColor}`,
            borderBottom: "none",
          }}>
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={barIcon}><Icon name="search" size={15} /></span>
            <input
              ref={findRef}
              value={needle}
              autoFocus
              placeholder={t("Find")}
              onChange={(e) => { setNeedle(e.target.value); setAt(0); }}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === "Escape") { e.preventDefault(); close(); }
                else if (e.key === "Enter") {
                  e.preventDefault();
                  step(e.shiftKey ? -1 : 1);
                }
              }}
              style={barInput}
            />
            {/* WHICH match, out of how many — the one thing a find bar must
                always say, because "nothing found" and "found, and you are
                on the third" look identical without it. Fixed width and
                tabular figures, so the arrows beside it do not shift as the
                count goes from 9 to 10. */}
            <span style={{
              flex: "0 0 auto", width: 38, textAlign: "center",
              fontSize: "var(--fs-2)", fontVariantNumeric: "tabular-nums",
              color: needle && !matches.length
                ? "var(--red-text)" : "var(--muted-2)",
            }}>
              {!needle ? "" : matches.length
                ? `${current + 1}/${matches.length}` : t("none")}
            </span>
            <button className="hoverable" style={off(barIconBtn, !matches.length)}
              title={t("Previous match (⇧⏎)")}
              onClick={() => step(-1)} disabled={!matches.length}>
              <Icon name="keyboard_arrow_up" size={16} />
            </button>
            <button className="hoverable" style={off(barIconBtn, !matches.length)}
              title={t("Next match (⏎)")}
              onClick={() => step(1)} disabled={!matches.length}>
              <Icon name="keyboard_arrow_down" size={16} />
            </button>
            {/* CLOSE, at the bar's own top-right corner and set apart from
                the two arrows — it ends the search rather than stepping it,
                and beside them at the same weight it read as a third step.
                A dialog's ✕ lives here; this is the same gesture. */}
            <span style={{ width: 1, height: 16, flex: "0 0 auto",
                           background: "var(--border)", margin: "0 2px" }} />
            <button className="hoverable" style={barIconBtn}
              title={t("Close (Esc)")} onClick={close}>
              <Icon name="close" size={16} />
            </button>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={barIcon}>
              <Icon name="find_replace" size={15} />
            </span>
            <input
              value={into}
              placeholder={t("Replace with")}
              onChange={(e) => setInto(e.target.value)}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === "Escape") { e.preventDefault(); close(); }
                else if (e.key === "Enter") { e.preventDefault(); doReplace(); }
              }}
              style={barInput}
            />
            <button style={off(barBtn, current < 0)} onClick={doReplace}
              disabled={current < 0} title={t("Replace this one")}>
              {t("Replace")}
            </button>
            <button style={off(barBtn, !matches.length)} onClick={doReplaceAll}
              disabled={!matches.length} title={t("Replace every match")}>
              {t("All")}
            </button>
          </div>
        </div>
      )}

      <div style={{ position: "relative" }}>
        {/* The layer, BEHIND the box and holding the same string — see the
            note above. It is `aria-hidden` and takes no pointer: it is a
            picture of the text, not the text. */}
        {open && !!matches.length && (
          <div aria-hidden style={{
            ...SHARED,
            position: "absolute", inset: 0, zIndex: 0,
            borderRadius: open ? "0 0 8px 8px" : 8,
            color: "transparent", pointerEvents: "none", overflow: "hidden",
          }}>
            {runs.map((run, i) => run.match < 0 ? (
              <span key={i}>{run.text}</span>
            ) : (
              <span key={i} style={{
                borderRadius: 3,
                background: run.match === current
                  ? "var(--accent)" : "var(--accent-dim)",
              }}>{run.text}</span>
            ))}
            {/* A trailing newline has no line box of its own, so a match on
                the last line would sit one row high without this. */}
            {"\n"}
          </div>
        )}
        <AutoTextarea
          ref={bindTa}
          value={value}
          onKeyDown={keys}
          style={{
            ...SHARED,
            ...style,
            position: "relative", zIndex: 1,
            width: "100%",
            background: open && matches.length ? "transparent" : "var(--bg)",
            // ALL FOUR SIDES, ALWAYS, AND NEVER THE SHORTHAND. `borderColor`
            // beside a CONDITIONAL `borderTopColor` is fragile by
            // construction: React diffs inline styles per property, so the
            // render that drops the longhand sets `border-top-color` to ""
            // — which is `currentColor`, i.e. the text colour — and the
            // shorthand is not re-applied because it did not change. That is
            // the white line along the top of the box the moment the find bar
            // closed, and a render that DID change the shorthand (the field
            // turning yellow on a duplicate while the bar was open) painted
            // the seam yellow the other way. Four longhands on every render
            // cannot get out of step.
            //
            // THE SHARED EDGE IS A DIVIDER, NOT AN OUTLINE. The bar and the
            // field are one control, so the accent belongs around the pair;
            // drawn in it as well, the line reads as the top of a second
            // box rather than as the seam between two halves of one.
            borderTopColor: open ? "var(--border)" : borderColor,
            borderRightColor: borderColor,
            borderBottomColor: borderColor,
            borderLeftColor: borderColor,
            borderRadius: open ? "0 0 8px 8px" : 8,
            color: "var(--text)",
            outline: "none",
          }}
          {...rest}
        />
      </div>
    </div>
  );
});
