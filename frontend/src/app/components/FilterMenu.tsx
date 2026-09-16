// THE NARROWING CONTROL, shared by every list in the Tags tab.
//
// It lived in `TagsView` until the Sets tab's entry list wanted one too, and
// could not have it: `TagsView` imports that section, so importing back would
// have been a cycle. Its own module, imported by both — the only change was
// where it lives.

import React, { useEffect, useRef, useState } from "react";
import { MenuRow } from "../../shared/MenuRow";

import { useAnchorRect, AnchoredDropdown } from "../../shared/AnchoredDropdown";
import { Icon } from "../../shared/Icon";
import { useMenuDismiss } from "../../shared/useMenuDismiss";

/** One narrowing control, spelled out. Both lists had a button that CYCLED
 *  through its states, which asks you to click a thing several times to find
 *  out what it can be — and in the Subjects list two of them multiplied into
 *  nine combinations, of which several described an empty table. A menu says
 *  what the choices are before anything is chosen.
 *
 *  `views[0]` is the un-narrowed state: it decides whether the button reads as
 *  a filter that is ON. */
export interface FilterView { id: string; label: string; icon: string }

/** One SECTION of the menu: a set of mutually exclusive views, of which
 *  `views[0]` is the un-narrowed one.
 *
 *  It also carried independent TOGGLES ("also this", beside "which of these"),
 *  for one switch: whether a person's row showed their face crops. The crops
 *  are what the Subjects list is for, so the switch is gone and the shape with
 *  it. If a real "also this" ever turns up, it is a section of its own again —
 *  folding one into a list of states is what made a five-way setting out of
 *  two axes here once. */
export interface FilterSection {
  title?: string;
  views?: FilterView[];
  value?: string;
  onPick?: (v: string) => void;
  /** Extra text on the button for one state, e.g. how many there are. */
  suffix?: (v: string) => string;
  /** …OR a set of independent ticks, for an axis whose answers are not
   *  mutually exclusive: "subjects and places" is one list of the entries
   *  that are either, which no pick-one section can say. Ticking none is
   *  the un-narrowed state, exactly as `views[0]` is for the other kind. */
  checks?: FilterView[];
  checked?: string[];
  onToggle?: (id: string) => void;
  /** A SWITCH THAT NARROWS NOTHING (owner 2026-09): something the page
   *  shows or does not — the Faces tab's offers row — kept in this menu
   *  because "what is on this page" is one question, but never a reason
   *  for the button to light up or name it. Two views, `views[0]` the ON
   *  state whose label the row wears; the tick says it is on. */
  quiet?: boolean;
}

/** The narrowing control, spelled out — one button holding every way this list
 *  can be cut down.
 *
 *  It replaced a row of buttons of two different kinds: toggles that were
 *  mutually exclusive anyway (Aliases / Implications — an alias entails
 *  nothing, so both at once could only ever show an empty table) and a button
 *  that CYCLED through four states, which never shows you where it can go.
 *  Every one of them is a "pick one of these" question, and a menu asks that
 *  question properly: the choices named, each with a line saying what it means,
 *  and the sections separated so it is clear they cut on different axes.
 *
 *  The button reads as ON whenever any section is off its default, and names
 *  what is narrowing — the label alone was ambiguous once there was more than
 *  one axis.
 */
export function FilterMenu({ sections, t, title, disabled }: {
  sections: FilterSection[];
  t: (s: string) => string;
  title: string;
  /** Nothing it narrows is on screen. Dimmed and inert rather than hidden: a
   *  control that disappears takes its answer with it, and what it is set to
   *  still applies the moment the other button puts the rows back. */
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const rect = useAnchorRect(anchor, open);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  useMenuDismiss(open, () => setOpen(false), { within: [anchor] });

  const picks = sections.filter((s) => s.views && !s.quiet);
  const narrowing = picks
    .map((sec) => ({ sec, view: sec.views!.find((v) => v.id === sec.value) }))
    .filter((x) => x.view && x.view.id !== x.sec.views![0].id);
  // A SECTION OF TWO IS A SWITCH, and is drawn as one. "Any entry / With
  // aliases" is a heading and two rows for a question whose whole content
  // is a tick — three lines of menu to say one word. Sections of three
  // (with / without / either) stay as they are: that is a real choice
  // between three answers, and a tick cannot make it.
  const asToggle = (sec: FilterSection) =>
    sec.views != null && sec.views.length === 2;
  const asSwitch = (sec: FilterSection) => !!sec.quiet && asToggle(sec);
  /** …AND THE FIRST SWITCH OF A RUN STILL TAKES THE RULE. A switch draws no
   *  heading, and for a while it drew no separator either — so it sat flush
   *  under the rows of whichever pick-one section came before it and read as
   *  one of them: "On no item" under IN THE AUTOCOMPLETE, "Flat list" under
   *  HOW IT RELATES. Both are different questions about different things,
   *  and the checkbox on the right is not enough to say so when the row
   *  above it is the same size in the same list.
   *
   *  The FIRST of a run only: two switches together are one block, which is
   *  what dropping their headings was for. */
  const opensBlock = (i: number) =>
    i > 0 && asToggle(sections[i]) && !asToggle(sections[i - 1]);
  // A TICKED SECTION NARROWS TOO, and names itself on the button the same
  // way — every ticked answer, so a filter that is on is never silent.
  const ticked = sections.flatMap((sec) =>
    (sec.checks ?? []).filter((v) => (sec.checked ?? []).includes(v.id)));
  const narrowed = narrowing.length > 0 || ticked.length > 0;
  // Nothing narrowing: the first section's default names the button, which is
  // the word somebody looks for ("Any kind", "Everything").
  const lead = narrowing[0]?.view ?? ticked[0] ?? picks[0].views![0];
  const label = narrowed
    ? [...narrowing.map((x) => t(x.view!.label)
                              + (x.sec.suffix?.(x.view!.id) ?? "")),
       ...ticked.map((v) => t(v.label))].join(" · ")
    : t(lead.label) + (picks[0].suffix?.(picks[0].value ?? "") ?? "");

  return (
    <>
      <button
        ref={anchor}
        onClick={() => { if (!disabled) setOpen((v) => !v); }}
        title={title}
        style={{
          display: "flex", alignItems: "center", gap: 5, height: 34,
          padding: "0 8px 0 12px", borderRadius: "var(--r-5)",
          // The chevron costs width the toolbar does not have to spare, and a
          // filter that wraps to two lines ("Any / kind") reads as broken.
          fontSize: "var(--fs-3)", fontFamily: "inherit", whiteSpace: "nowrap",
          flex: "0 0 auto",
          border: `1px solid ${narrowed ? "var(--accent)" : "var(--border-strong)"}`,
          background: narrowed ? "var(--accent-dim)" : "var(--panel-2)",
          color: narrowed ? "var(--accent)" : "var(--text-2)",
          opacity: disabled ? 0.45 : 1,
          cursor: disabled ? "default" : "pointer",
        }}
      >
        <Icon name={lead.icon} size={16} />
        {label}
        <Icon name="arrow_drop_down" size={16} />
      </button>
      {open && (
        <AnchoredDropdown rect={rect} minWidth={260}>
          <div onClick={(e) => e.stopPropagation()}>
            {sections.map((sec, i) => (
              <div key={sec.title ?? i}
                   style={opensBlock(i)
                     ? { marginTop: 3, paddingTop: 3,
                         borderTop: "1px solid var(--border)" }
                     : undefined}>
                {/* A SWITCH NEEDS NO HEADING: its own label is the
                    question. It takes the RULE though, where it opens a
                    block — see `opensBlock`. */}
                {sec.title && !asToggle(sec) && (
                  <div style={{
                    padding: i === 0 ? "4px 9px 3px" : "9px 9px 3px",
                    marginTop: i === 0 ? 0 : 3,
                    borderTop: i === 0 ? "none" : "1px solid var(--border)",
                    fontSize: "var(--fs-1)", fontWeight: 600, letterSpacing: "0.06em",
                    textTransform: "uppercase", color: "var(--muted-3)",
                  }}>
                    {t(sec.title)}
                  </div>
                )}
                {asSwitch(sec) && (() => {
                  const [on_, off] = sec.views!;
                  const on = sec.value === on_.id;
                  return (
                    <MenuRow active={on}
                      onClick={() => sec.onPick?.(on ? off.id : on_.id)}>
                      <Icon name={on_.icon} size={16} />
                      <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                        fontWeight: 500 }}>
                        {t(on_.label)}
                      </span>
                      <Icon name={on ? "check_box" : "check_box_outline_blank"}
                            size={16}
                            color={on ? "var(--accent)" : "var(--muted-3)"} />
                    </MenuRow>
                  );
                })()}
                {asToggle(sec) && !asSwitch(sec) && (() => {
                  const [off, on_] = sec.views!;
                  const on = sec.value === on_.id;
                  return (
                    <MenuRow active={on}
                      onClick={() => sec.onPick?.(on ? off.id : on_.id)}>
                      <Icon name={on_.icon} size={16} />
                      <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                        fontWeight: 500 }}>
                        {t(on_.label)}{sec.suffix?.(on_.id)}
                      </span>
                      <Icon name={on ? "check_box" : "check_box_outline_blank"}
                            size={16}
                            color={on ? "var(--accent)" : "var(--muted-3)"} />
                    </MenuRow>
                  );
                })()}
                {(sec.checks ?? []).map((v) => {
                  const on = (sec.checked ?? []).includes(v.id);
                  return (
                    <MenuRow active={on}
                      key={v.id}
                      onClick={() => sec.onToggle?.(v.id)}>
                      <Icon name={v.icon} size={16} />
                      <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                        fontWeight: 500 }}>
                        {t(v.label)}{sec.suffix?.(v.id)}
                      </span>
                      {/* A TICK, because these do not close the menu: several
                          of them are one answer, and a menu that shut after
                          the first would ask you to open it again for the
                          second. */}
                      <Icon name={on ? "check_box" : "check_box_outline_blank"}
                            size={16}
                            color={on ? "var(--accent)" : "var(--muted-3)"} />
                    </MenuRow>
                  );
                })}
                {(asToggle(sec) ? [] : sec.views ?? []).map((v) => (
                  <MenuRow active={v.id === sec.value}
                    key={v.id}
                    onClick={() => { setOpen(false); sec.onPick?.(v.id); }}>
                    <Icon name={v.icon} size={16} />
                    {/* The label alone. Every entry carried a line explaining
                        itself, which is a paragraph of small grey text over a
                        list of five words — and the words say it: "With faces"
                        needs no gloss, and one that did would be badly named.
                        The sections' own headings say what axis is being cut. */}
                    <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                      fontWeight: 500 }}>
                      {t(v.label)}{sec.suffix?.(v.id)}
                    </span>
                  </MenuRow>
                ))}
              </div>
            ))}
          </div>
        </AnchoredDropdown>
      )}
    </>
  );
}
