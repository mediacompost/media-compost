/** "N selected", with what to do about them.
 *
 * ONE bar for the whole sidebar, PINNED near the bottom of the scrolling area
 * and floating over it: a toolbar at the top of a section scrolls away exactly
 * when a long list needs it, and one that appears in the flow moves every row
 * under the cursor that just picked it. So it takes no layout space at all
 * (sticky, with a negative margin cancelling its own height) and the scroll
 * area carries a permanent inset instead, so the last rows are reachable
 * whether the bar is showing or not.
 *
 * It shows whenever a selectable list is on screen — not only once something
 * is picked, and not only once the list has rows. It used to appear with the
 * first selection and vanish with the last, which put "select all" nowhere
 * and made the bar itself a thing you had to discover by accident; showing
 * it only once the list had rows was the same mistake one step out — the bar
 * came and went with the list's contents, so an emptied list read as a
 * broken sidebar rather than an empty list. Empty it is quiet: no accent,
 * and one button, dimmed while there is genuinely nothing to select.
 *
 * It lives in `shared/` rather than under `app/` because the TRAIN tab's job
 * list wants the same bar and the same gestures, and `train/` may not import
 * `app/` — so, like the rest of the shared chrome, it takes `t` as a required
 * prop instead of reaching for a package's own translator.
 *
 * The sections keep their own selections and their own idea of what removing
 * means; they REPORT upward through `SelectionBarSlot`, and the panel renders
 * whichever one has something in it. A bar per section would stack them on top
 * of one another the moment two tabs were open with picks in both.
 */
import React, { createContext, useContext, useEffect, useLayoutEffect, useRef,
                useState } from "react";
import { Icon } from "./Icon";
import { AnchoredDropdown, useAnchorRect } from "./AnchoredDropdown";
import { useEscape } from "./useEscape";
import { useMenuDismiss } from "./useMenuDismiss";

/** What a section says about its selection. */
export interface SelectionReport {
  count: number;
  /** How many rows there are to pick at all — Select all's own count, and
   *  what dims that button when it is 0. */
  total: number;
  onSelectAll: () => void;
  onRemove: () => void;
  onClear: () => void;
  removeLabel?: string;
  removeTitle?: string;
  /** How many of the picks Remove will ACT on, when that is not all of them
   *  — a running training job cannot be removed, and the bar must not offer
   *  to do half of what it says. Defaults to `count`, so every list whose
   *  Remove takes the whole selection passes nothing. ZERO hides the button
   *  outright: one that says "Remove 1" and then does nothing is worse than
   *  none, and Deselect is still there to put the selection down. */
  removeCount?: number;
  /** `close` by default. A list that DELETES its rows says so with a bin — the
   *  glyph and the word have to agree, or one of them is lying. */
  removeIcon?: string;
  /** Agreeing with a machine's guess — offered BESIDE Remove whenever a guess
   *  is picked, never instead of it. Disagreeing is not a third verb: taking a
   *  guess off IS rejecting it (the caller records the refusal), so a separate
   *  Reject button was two words for one button, and the one that had to be
   *  learned. */
  onAccept?: () => void;
  /** STOPPING work the picks stand for — the Evaluate grid's slots of a
   *  generation that is queued or still running. Not Remove: a run being
   *  written cannot be removed, and what it has already made is kept, so the
   *  two verbs act on different picks and say different numbers. Shown only
   *  while `cancelCount` is above zero, Remove's own rule. */
  onCancel?: () => void;
  cancelCount?: number;
  cancelLabel?: string;
  cancelTitle?: string;
  /** How many of the picks are guesses, for the buttons' own labels. */
  pending?: number;
  /** ONE list-specific verb, beside the two above — icon-only, because the
   *  bar's width is already spoken for and a third word pushes the buttons
   *  onto a second line (which makes the bar taller, which moves the panel).
   *  It appears only while the list says it applies: the Text tab offers it
   *  for a run of ADJACENT rows and nothing else, so a bar that shows it is
   *  a bar where it means something. Its `title` is the whole sentence. */
  /** The list's own third verb; `label` beside the icon where there is
   *  room for a word (the Evaluate grid's bar spans the page), icon-only
   *  where there is not (a 280 px sidebar). */
  extra?: { icon: string; title: string; label?: string;
            onClick: () => void };
  /** HOW THE LIST IS SHOWN, behind a ⋯ beside Select all — a different kind
   *  of thing from the three verbs above, which act on the picks. These are
   *  ticks that change what the list SHOWS, so they are never a button of
   *  their own in the bar (there is no room, and one more word pushes the
   *  row onto a second line) and never a section header either: a header
   *  scrolls away exactly when a long list needs it, which is why the bar
   *  is pinned in the first place. */
  options?: { label: string; checked: boolean; onClick: () => void }[];
}


/** Its own height with one row of buttons, and the starting point for the
 *  content inset before the bar has measured itself. */
export const SELECTION_BAR_H = 34;
/** The gap it floats above the content by — and, equally, the gap it keeps
 *  from the scroll area's bottom edge, so it never sits ON it. */
export const SELECTION_BAR_GAP = 10;

type Report = (id: string, r: SelectionReport | null) => void;
const Slot = createContext<Report | null>(null);

export function SelectionBarSlot({ report, children }: {
  report: Report;
  children: React.ReactNode;
}) {
  return <Slot.Provider value={report}>{children}</Slot.Provider>;
}

/** Whether a bar is listening at all. A section that carries its own bulk
 *  affordance keeps it where there is none to take the job over — the
 *  annotator renders the tag panel with no bar anywhere near it, and a section
 *  that simply dropped its own button there would lose the action entirely. */
export function useSelectionBarSlot() {
  return !!useContext(Slot);
}

/** Say what is picked here. `id` names the section, so a second report from the
 *  same one replaces the first rather than adding to it.
 *
 *  The CALLBACKS are deliberately not dependencies. They are rebuilt every
 *  render — a section's `onRemove` closes over its current selection — so
 *  depending on their identity reported on every render, which set state on
 *  the panel, which re-rendered the section, which reported again: a loop that
 *  showed up as a bar that lagged behind the selection or never arrived. They
 *  are read through a ref instead, so the bar always calls the LATEST one and
 *  the effect only fires when something the bar actually displays changes. */
export function useReportSelection(id: string, r: SelectionReport | null) {
  const report = useContext(Slot);
  const live = useRef(r);
  live.current = r;
  const { count, total, removeLabel, removeTitle, removeIcon, removeCount,
          pending } = r ?? {};
  const offersAnswers = !!r?.onAccept;
  // The extra button's own identity changes every render like the rest of
  // the callbacks, so what the effect watches is what the bar SHOWS of it.
  const extraIcon = r?.extra?.icon;
  const extraTitle = r?.extra?.title;
  const extraLabel = r?.extra?.label;
  // Same rule for the ⋯ options: what the effect watches is the LABELS and
  // their ticks, which is all the menu draws — the handlers are rebuilt every
  // render like every other callback here.
  const optionsKey = (r?.options ?? [])
    .map((o) => `${o.label}\u0000${o.checked ? 1 : 0}`).join("\u0001");
  // An EMPTY list still reports (total 0): the bar shows for the list, not
  // for its rows. Only a null report — a list that opted out — says nothing.
  const active = !!r;
  useEffect(() => {
    if (!report || !active) return;
    report(id, {
      count: count ?? 0, total: total ?? 0,
      removeLabel, removeTitle, removeIcon, removeCount, pending,
      onSelectAll: () => live.current?.onSelectAll(),
      onRemove: () => live.current?.onRemove(),
      onClear: () => live.current?.onClear(),
      ...(offersAnswers ? {
        onAccept: () => live.current?.onAccept?.(),
      } : {}),
      ...(extraIcon ? {
        extra: {
          icon: extraIcon, title: extraTitle ?? "", label: extraLabel,
          onClick: () => live.current?.extra?.onClick(),
        },
      } : {}),
      ...(optionsKey ? {
        options: (live.current?.options ?? []).map((o, i) => ({
          label: o.label, checked: o.checked,
          onClick: () => live.current?.options?.[i]?.onClick(),
        })),
      } : {}),
    });
    return () => report(id, null);
  }, [report, id, active, count, total, removeLabel, removeTitle, removeIcon,
      removeCount,
      pending, offersAnswers, extraIcon, extraTitle, extraLabel, optionsKey]);
}

export function SelectionBar({ count, total, onSelectAll, onRemove, onClear,
                              removeTitle, removeLabel, removeIcon,
                              removeCount, onAccept,
                              onCancel, cancelCount, cancelLabel, cancelTitle,
                              pending, extra, options, floating, style, t,
                              onHeight }: SelectionReport & {
  /** REQUIRED, like the rest of the shared chrome: this lives in `shared/`
   *  now because the Train tab's job list needs the same bar, and `train/` may
   *  not import `app/`. An optional translator with an English fallback is how
   *  a package silently stays untranslated. */
  t: (s: string, vars?: Record<string, string>) => string;
  /** Pinned near the bottom of the scroll area, over the content and out of
   *  the flow. Off in a dialog, where the list is short, there is nothing to
   *  scroll past, and a bar that comes and goes would move the field under it
   *  — which is why the event editor's stays put. */
  floating?: boolean;
  style?: React.CSSProperties;
  /** Its measured height. The buttons WRAP under the count when the sidebar is
   *  too narrow for them, so the height is not a constant, and the inset the
   *  content reserves has to be the real one or a two-line bar covers the last
   *  row it exists to keep reachable. */
  onHeight?: (h: number) => void;
}) {
  const some = count > 0;
  const box = useRef<HTMLDivElement>(null);
  // The ⋯ menu, portalled: the bar floats at the foot of a scrolling panel,
  // so a menu laid out inside it would be clipped by the very overflow the
  // bar exists to sit on top of.
  const optsBtn = useRef<HTMLButtonElement>(null);
  const [optsOpen, setOptsOpen] = useState(false);
  const optsRect = useAnchorRect(optsBtn, optsOpen);
  useMenuDismiss(optsOpen, () => setOptsOpen(false), { within: [optsBtn] });
  // A list that stops offering options while the menu is open would leave it
  // hanging over nothing.
  useEffect(() => { if (!options?.length) setOptsOpen(false); }, [options?.length]);
  const [h, setH] = useState(SELECTION_BAR_H);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setH(Math.round(el.getBoundingClientRect().height));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => { onHeight?.(h); }, [h, onHeight]);

  // A button, spelled out: `.btn` is a class nobody ever wrote a rule for, so
  // every one of these was a raw browser button — which is why the ✕ sat above
  // its own label instead of beside it.
  const btn = (want: "plain" | "danger" | "accent"): React.CSSProperties => {
    // A DISABLED button wears no tone. In the dialog the bar stays put saying
    // "None selected", and a filled red Remove there shouts about something
    // that cannot happen.
    const tone = some ? want : "plain";
    return {
    display: "inline-flex", alignItems: "center", gap: 4,
    // Tight on purpose: with the two answers showing, three buttons and the
    // count share 275 px of sidebar, and the count is what gets squeezed out.
    height: 24, padding: "0 7px", borderRadius: "var(--r-3)", flex: "0 0 auto",
    fontSize: "var(--fs-2)", fontWeight: 500, lineHeight: 1,
    border: `1px solid ${tone === "danger" ? "var(--red)"
      : tone === "accent" ? "var(--accent)" : "var(--border-strong)"}`,
    // A plain button is FILLED, not transparent: the bar floats over
    // content — over pictures in the Evaluate grid — and a bordered outline
    // with nothing behind its words is unreadable on a busy thumbnail.
    background: tone === "danger" ? "var(--red)"
      : tone === "accent" ? "var(--accent)"
      : "color-mix(in srgb, var(--panel-2) 60%, transparent)",
    color: tone === "danger" || tone === "accent"
      ? "var(--on-accent)" : "var(--text-2)",
    cursor: "pointer",
    };
  };
  const answers = !!onAccept;
  // How many that button will act on, in the button. No brackets — the number
  // is part of what the button says, not an aside about it — and a step
  // quieter than the verb, so a row of them reads as words first and the
  // figures are there when you look for them. It is an OPACITY rather than a
  // colour token because these sit on three different backgrounds (plain,
  // accent, red), and one secondary grey cannot be legible on all of them.
  const num = (n: number) => (
    <span style={{ opacity: 0.62, fontVariantNumeric: "tabular-nums" }}>{n}</span>
  );
  return (
    <div ref={box} style={{
      // WRAPS. The buttons ride in one span, so when the sidebar is too narrow
      // they go under the count together rather than one at a time — and the
      // count keeps a floor width, or it would simply shrink to an ellipsis
      // and the buttons would never wrap at all.
      display: "flex", alignItems: "center", flexWrap: "wrap",
      columnGap: 5, rowGap: 5,
      padding: "6px 7px", borderRadius: "var(--r-4)",
      minHeight: SELECTION_BAR_H, boxSizing: "border-box",
      // Floating, it sits OVER the rows — over pictures in the Evaluate
      // grid — so it is ONE surface whether or not anything is picked: the
      // blur, plus enough solid panel colour that the content underneath
      // stops competing with the words, plus the accent tint on top while
      // something is picked. It used to flip from an opaque panel to a bare
      // tint at the first pick, which read as two different bars.
      background: floating
        ? (some ? "linear-gradient(var(--accent-dim), var(--accent-dim)), " : "")
          + "color-mix(in srgb, var(--panel) 78%, transparent)"
        : some ? "var(--accent-dim)" : "transparent",
      border: `1px solid ${some ? "var(--accent)" : "var(--border-soft)"}`,
      ...(floating ? {
        // Sticky rather than fixed: it belongs to the scroll area, so it stops
        // at the panel's edges instead of floating over the grid. The bottom
        // offset is the gap it keeps from the edge; the negative margin is its
        // own height plus the gap ABOVE it, so it occupies no flow space,
        // which is what keeps the content still when it appears.
        position: "sticky", bottom: SELECTION_BAR_GAP, zIndex: 5,
        marginTop: SELECTION_BAR_GAP,
        marginBottom: -(h + SELECTION_BAR_GAP),
        backdropFilter: "blur(8px)",
        boxShadow: "var(--shadow-2)",
      } : { marginBottom: 8 }),
      // No transition. It appears and disappears with the selection, and a
      // control that fades in is one you are still waiting for when you have
      // already decided what to do with it.
      ...style,
    }}>
      {/* Empty, the bar is a sentence and an offer: "None selected" with the
          one thing there is to do at the right. With something PICKED there is
          no separate count at all — every button carries its own. */}
      {!some && (
        <span style={{ flex: "0 1 auto", fontSize: "var(--fs-2)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          color: "var(--muted-3)" }}>
          {t("None selected")}
        </span>
      )}
      {/* What ACTS on the selection is on the LEFT, destructive first and the
          agreeing one beside it; Deselect is alone at the right. The two are
          different KINDS of thing — one changes the library, the other only
          changes what you are pointing at — so they sit at opposite ends
          rather than in a row where the reach for one lands on the other. */}
      {some && (<>
        {/* Remove is the ONLY way out, guess or no guess — taking a guess off
            IS rejecting it, and the caller records the refusal. A Reject
            button beside this one was a second word for one action, and it
            stopped the Remove somebody already knew from appearing at all the
            moment a guess was in the selection. Its number is the WHOLE
            selection: with a guess and a given name picked together the
            gesture is one sentence, and a Remove that silently skipped half of
            it would be the worse surprise. */}
        {(removeCount ?? count) > 0 && (
        <button onClick={onRemove} title={removeTitle}
          style={{ ...btn("danger"), flex: "0 0 auto" }}>
          <Icon name={removeIcon ?? "close"} size={13} />
          {removeLabel ?? t("Remove")}
          {num(removeCount ?? count)}
        </button>
        )}
        {onCancel && (cancelCount ?? 0) > 0 && (
          <button onClick={onCancel} title={cancelTitle}
            style={{ ...btn("plain"), flex: "0 0 auto" }}>
            <Icon name="stop" size={13} />
            {cancelLabel ?? t("Cancel")}
            {num(cancelCount ?? 0)}
          </button>
        )}
        {answers && (
          <button onClick={onAccept} title={t("Agree with what was guessed")}
            style={{ ...btn("accent"), flex: "0 0 auto" }}>
            <Icon name="check" size={13} />
            {t("Accept")}
            {/* The GUESSES, where Remove's is the whole selection — the two
                numbers side by side are what show that the buttons do
                different amounts. */}
            {num(pending ?? 0)}
          </button>
        )}
        {extra && (
          // The list's own verb, icon-only and last of the three — it is the
          // one that is not about removing, and it carries no count because
          // it acts on the whole run by definition.
          <button onClick={extra.onClick} title={extra.title}
            style={{ ...btn("plain"), flex: "0 0 auto",
                     padding: extra.label ? "0 8px 0 6px" : "0 6px" }}>
            <Icon name={extra.icon} size={14} />
            {extra.label}
          </button>
        )}
      </>)}
      <span style={{ display: "flex", alignItems: "center", gap: 5,
        // The way OUT, hugging the right. The auto margin takes the slack,
        // which is why the "None selected" beside it does not grow.
        flex: "0 0 auto", marginLeft: "auto" }}>
        {/* HOW THE LIST IS SHOWN, to the LEFT of the button that picks its
            rows — and there whether anything is picked or not, because it is
            not about the selection and a control that came and went with one
            is a control nobody learns the place of. */}
        {!!options?.length && (
          <button
            ref={optsBtn}
            onClick={() => setOptsOpen((v) => !v)}
            title={t("How this list is shown")}
            style={{ ...btn("plain"), padding: "0 5px",
              background: optsOpen ? "var(--panel-2)" : "transparent" }}
          >
            {/* A GEAR, and one that never changes. It was an eye, slashed
                while an option was on — a state the glyph reported, and a
                glyph that flips is one more thing on the bar to read. The
                menu itself says what is on. No accent tint, which in this
                bar means "picked" and would put a second highlight beside
                the one the selection already owns. */}
            <Icon name="settings" size={14} />
          </button>
        )}
        {optsOpen && !!options?.length && (
          <AnchoredDropdown rect={optsRect} minWidth={200}>
            {options.map((o) => (
              <div
                key={o.label}
                className="hoverable"
                onClick={() => { o.onClick(); setOptsOpen(false); }}
                style={{ display: "flex", alignItems: "center", gap: 8,
                  padding: "6px 9px", borderRadius: "var(--r-2)", cursor: "pointer",
                  fontSize: "var(--fs-3)", color: "var(--text-2)" }}
              >
                {/* A tick in the icon's place, and an equally wide EMPTY
                    gutter when it is off — or the label steps sideways every
                    time the option is switched. */}
                <span style={{ flex: "0 0 15px", display: "flex" }}>
                  {o.checked && (
                    <Icon name="check" size={15} color="var(--accent)" />
                  )}
                </span>
                {o.label}
              </div>
            ))}
          </AnchoredDropdown>
        )}
        {!some ? (
          // Nothing picked: the one thing there is to do. Selecting them all by
          // hand is a drag across a list that scrolls. With no rows at all it
          // stays, DIMMED — the bar shows for the list, not for its rows, and
          // a button that vanished with them would move the one beside it.
          <button onClick={onSelectAll} disabled={!total}
            style={{ ...btn("plain"),
              ...(total ? {} : { opacity: 0.45, cursor: "default" }) }}
            title={t("Pick every row in this list")}>
            <Icon name="checklist" size={13} />
            {t("Select all")}
            {num(total)}
          </button>
        ) : (
          <button onClick={onClear} style={btn("plain")}>
            {t("Deselect")}
            {/* Only past one. "Deselect 1" is a number nobody needed: the row
                it means is the only one tinted, and the figure is there to say
                how much the click takes back when that is not obvious. */}
            {count > 1 && num(count)}
          </button>
        )}
      </span>
    </div>
  );
}
