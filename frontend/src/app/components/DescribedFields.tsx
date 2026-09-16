// WHAT A NAMED THING IS, at two lengths — the pair, written once: the two
// fields that set it, and the ? that reads the long one back.
//
// A tag, a subject, a place, an event and a meta tag are all the same shape
// here: a name, then one line saying what it is, then as many lines as it
// takes. Five dialogs spelling that pair out would be five placeholders, five
// heights and five ideas of which is which — and the difference between them
// is the whole point, so it has to read the same everywhere.
//
// `comment` rides beside the name wherever the name goes: the list row, the
// autocomplete's secondary text. The long form appears nowhere by itself — a
// ? beside the name opens it — which is what lets it be paragraphs. For a
// TAG (and the three records on one) the long form is a TAG SET's, written
// in the Sets sub-tab; only a META TAG and a set's own entry still carry a
// `description` of their own, which is what the field below is for.
import React from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { useQuery } from "@tanstack/react-query";

import { compactCount } from "../format";
import { useLang, useT } from "../i18n";
import { Icon } from "../../shared/Icon";
import { useAnchorRect } from "../../shared/AnchoredDropdown";
import { HelpGlyph, HelpPanel } from "../../shared/HelpMark";
import { FieldLabel as Label, fieldStyle as field } from "../../shared/Overlay";
import { api, LIBRARY_SET_KEY, type TagSetText } from "../api";
import { parseDescription } from "../descriptionLinks";
import { useUI } from "../store";
import { CategoryTrail } from "./CategoryTrail";
import { orderTexts } from "../tagSetOrder";
import { formatDate } from "../../query/subjects/when";
import { useTagSetIds, useTagSetNames, useTagSetOrder } from "../useTagSetOrder";

/**
 * The ? that opens the long form, wherever a name is listed.
 *
 * Written once because the two lists that show it — the Tags tab's rows and
 * the tag autocomplete — are showing the same field about the same tag, and a
 * mark that answered to a hover in one and to a click in the other would be
 * one thing with two behaviours.
 *
 * Hover shows it, click pins it open. Hover alone is unreadable for anything
 * longer than a sentence (it goes the moment the pointer moves to read on),
 * and click alone hides a one-line answer behind a click.
 *
 * SEVERAL TAG SETS MAY DESCRIBE ONE NAME — a set made from the shipped Booru
 * template, an imported dump, one typed by hand in the Sets sub-tab. The
 * popover shows ONE at a time with a strip of the sets' names to
 * switch, and which comes first is the person's own preference
 * (`useTagSetOrder`): the set switched to last moves to the front, for every
 * tag, so "I trust this set's wording" is one decision. The hover survives
 * the pointer travelling INTO the popover — a strip nobody can reach is not
 * a strip.
 */
/** WHICH MARK IS PINNED OPEN — at most one, anywhere on the page.
 *
 *  Two popovers at once are two answers to one question, and the second one
 *  opened over the first. A module-level id rather than store state: nothing
 *  outside these marks has any business reading it, and every mark on a
 *  250,000-row list would otherwise subscribe to the store to learn it is
 *  still closed. `useSyncExternalStore` keeps the read React-correct.
 */
let openMark = 0;
const markWatchers = new Set<() => void>();
const subscribeMark = (fn: () => void) => {
  markWatchers.add(fn);
  return () => { markWatchers.delete(fn); };
};
const readOpenMark = () => openMark;
function pinMark(id: number) {
  openMark = id;
  for (const fn of [...markWatchers]) fn();
}
let nextMarkId = 0;
/** name -> the mark that is about it, while that mark is on screen. A
 *  keyboard has no pointer to put on a `?`, so it needs a way to name the
 *  one it means; the autocomplete knows the tag its highlight is on and
 *  nothing else about the mark drawn beside it. Registered per mount, so a
 *  windowed list's unmounted rows are not in it. */
const markByName = new Map<string, number>();

/** Open (or close) the mark for this name. False when the name has none on
 *  screen — nothing described it, or its row is not mounted — which is what
 *  lets the caller leave the key alone. */
export function toggleMarkForName(name: string): boolean {
  const id = markByName.get(name.toLowerCase());
  if (!id) return false;
  pinMark(openMark === id ? 0 : id);
  return true;
}

export function DescriptionMark({ description, descriptions, library,
                                  size = 14, onDown,
                                  raised, name, besideRef, auto, onPickName }: {
  /** A text the thing carries ITSELF — a meta tag's, or a set entry's in
   *  the Sets sub-tab. It goes under `OWN_KEY`, which the switcher never
   *  has to name because such a thing is in no set. */
  description?: string;
  /** WHAT THE LIBRARY SAYS about this tag — its own long form, its
   *  one-liner and where it files it. The library is a tag set now, so this
   *  is an ordinary frame in the switcher rather than an unnamed "own" text
   *  (a tag CAN be described twice, by the library and by an enabled set),
   *  and it LEADS: it is the tag set somebody is actually working in.
   *  Skipped where the library says nothing. */
  library?: { text?: string; comment?: string; trail?: string[] };
  /** What the enabled tag sets say (`TagRow.descriptions`). */
  descriptions?: TagSetText[];
  size?: number;
  /** The autocomplete commits its tag on MOUSEDOWN, so reading a description
   *  there would pick the tag; that list passes the handler that stops it. */
  onDown?: (e: React.MouseEvent) => void;
  /** Inside the quick tag overlay, whose sheet sits above the popover layer. */
  raised?: boolean;
  /** OPEN IT WITHOUT BEING ASKED, and put it BESIDE this box rather than
   *  under the mark. The quick tag overlay's list does both: the highlight
   *  moves with the arrow keys, and what a set says about the name under it
   *  is exactly what somebody is choosing by — so it is shown as the
   *  highlight arrives, to the RIGHT of the list where it covers nothing.
   *  Falls back to the ordinary anchored placement where there is not room
   *  for it, since a popover over the list it is about is worse than one
   *  that has to be asked for. */
  besideRef?: React.RefObject<HTMLElement | null>;
  auto?: boolean;
  /** WHICH TAG this is about, where the caller knows — an autocomplete row
   *  and a tags-list row do. It is what the popover's "In the set" button
   *  jumps to; without it that button is not offered, since a field looking
   *  at the row already has nowhere to go. */
  name?: string;
  /** TAKE THE NAME THE POPOVER IS SHOWING — a FIELD's answer to "use
   *  `solo_focus` instead": follow the link, then press the title. */
  onPickName?: (name: string) => void;
}) {
  // A mark is open when the page's one open id is ITS id — so opening any
  // other mark closes this one without either of them knowing about it.
  const id = React.useRef(0);
  if (id.current === 0) id.current = ++nextMarkId;
  const pinned = React.useSyncExternalStore(subscribeMark, readOpenMark);
  const open = pinned === id.current;
  const setOpen = (v: boolean) => pinMark(v ? id.current : 0);
  // Closing on unmount would fight the windowed lists, which unmount rows as
  // they scroll; the id simply stops matching anything and the next open
  // replaces it.
  const [hover, setHover] = React.useState(false);
  // LOSING THE PIN CLOSES THE POPOVER, hover or no hover. Without this the
  // mark went grey and its popover stayed: reading a pinned popover means
  // the pointer travels INTO it, whose `onMouseEnter` cancels the pending
  // hover-out — and whose `onMouseLeave` deliberately does nothing while the
  // mark is pinned. So `hover` was left true with nothing to turn it off,
  // and the next mark's click unpinned this one without hiding it. It is
  // also what makes a second click on the SAME mark close it.
  React.useEffect(() => { if (!open) setHover(false); }, [open]);
  // WHILE THIS MARK IS ON SCREEN it is the one that answers for its name, so
  // a keyboard can ask for it (`toggleMarkForName`). Registered only where
  // the caller said which tag this is about; cleared on unmount, so a
  // windowed list's scrolled-away rows stop answering.
  const mine = id.current;
  React.useEffect(() => {
    if (!name) return;
    const key = name.toLowerCase();
    markByName.set(key, mine);
    return () => {
      if (markByName.get(key) === mine) markByName.delete(key);
    };
  }, [name, mine]);
  const anchor = React.useRef<HTMLSpanElement>(null);
  const leaving = React.useRef<number | null>(null);
  // READ AT RENDER, not through `useAnchorRect`: the box is this mark's
  // ANCESTOR, and React attaches a parent's ref after its children's layout
  // effects have run — so the hook measured null on the one pass it was
  // given and never looked again. The mark re-renders whenever the
  // highlight moves, which is exactly when this answer can change.
  const boxRect = besideRef?.current?.getBoundingClientRect() ?? null;
  // BESIDE THE BOX, where the box says so and the window has room to its
  // right for a popover of the width `AnchoredDropdown` gives this one.
  const BESIDE_W = 276;
  const beside = besideRef && boxRect
    && boxRect.right + BESIDE_W + 8 <= window.innerWidth
    ? ({ left: boxRect.right + 8, right: boxRect.right + 8,
         top: boxRect.top - 8, bottom: boxRect.top - 8,
         width: 0, height: 0, x: boxRect.right + 8, y: boxRect.top - 8,
         toJSON: () => "" } as DOMRect)
    : null;
  // AND ONLY THEN DOES IT OPEN ITSELF. Asked for, it appears wherever it
  // fits, as every other popover does; UNASKED it appears only where it
  // covers nothing — a window too narrow for a column beside the list gets
  // the list, and the `?` on request. Opening over the rows somebody is
  // reading is worse than not opening at all.
  const shown = open || hover || (!!auto && !!beside);
  // MEASURED WHEN IT OPENS, not once at mount. `useAnchorRect(anchor, true)`
  // runs its layout effect exactly once, with deps that never change — and
  // this mark renders NOTHING until it has something to say (`cands` below),
  // so on every list whose rows are filled in a second pass the anchor was
  // still null on that one run and the rect stayed null for ever. The mark
  // then lit on a click and opened no popover, which is what the library's
  // own tag list did: its descriptions arrive with the window's detail
  // fetch, a render after the row, where a tag set's list carries them with
  // the page. Hanging the effect on `shown` measures at the moment there is
  // something to place, and re-measures every time it is opened again.
  const ownRect = useAnchorRect(anchor, shown);
  const rect = beside ?? ownRect;
  // A SET THAT KNOWS THE NAME IS WORTH A POPOVER, described or not: it also
  // knows how common the tag is, what else it is called and what it entails,
  // and a `?` that appeared only where somebody had written prose hid all of
  // that. A thing's OWN text is still only worth one when there is text.
  const stay = () => {
    if (leaving.current != null) { window.clearTimeout(leaving.current); leaving.current = null; }
  };
  const leave = () => {
    stay();
    leaving.current = window.setTimeout(() => setHover(false), 160);
  };
  const cands = React.useMemo<TagSetText[]>(() => [
    ...((description || "").trim() ? [{ key: OWN_KEY, text: description! }] : []),
    // THE LIBRARY LEADS. Built from the row the caller already holds rather
    // than fetched: `/describe` returns the same frame for a hover with no
    // row behind it, and the merge below dedups the two by key.
    // ONLY WHERE THERE IS TEXT, which is the rule a thing's own text has
    // always followed here. A SET is worth a `?` for knowing the name at all
    // — it also knows how common it is and what it entails, none of which is
    // on the row — but everything the library knows besides the long form is
    // already drawn: the comment reads beside the name, the category has a
    // column of its own. A `?` on every filed tag opens on what you can
    // already see.
    ...(library && (library.text || "").trim()
        ? [{ key: LIBRARY_SET_KEY, text: library.text!,
             comment: library.comment || "",
             trail: library.trail ?? [] } as TagSetText]
        : []),
    ...(descriptions ?? []).filter(
      (d) => (d.text || "").trim() || d.count != null
        || d.aliases?.length || d.implies?.length || d.implied_by?.length
        || d.meta?.length
        || d.trail?.length
        // …and a set that has written no prose but knows the name is a
        // person, or a place inside another, has plenty to open a `?` for.
        || (d.comment || "").trim() || d.subject || d.place || d.event),
  ], [description, descriptions, library]);
  if (!cands.length) return null;
  return (
    <>
      {/* The glyph and the panel are `shared/HelpMark.tsx`'s; what is this
          mark's own is WHEN it opens (hover, pin, the keyboard). PROSE OPTS
          BACK IN there (owner 2026-09: "allow selecting text in the tag
          description popovers"), and THE PREVENTDEFAULT IS ONLY FOR A FIELD
          (`keepFocus`): it is what keeps the FOCUS where it is — without it
          a click on a set chip blurred the sidebar's tag field and its whole
          list closed — and it makes the text unselectable, which a list's
          popover must not be. `onPickName` is the one signal for which host
          it is: a field passes it (it is what makes the title a button), a
          list does not. */}
      <HelpGlyph
        ref={anchor}
        open={open}
        size={size}
        onMouseDown={onDown}
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        onMouseEnter={() => { stay(); setHover(true); }}
        onMouseLeave={leave}
      />
      {shown && (
        <HelpPanel rect={rect} raised={raised} keepFocus={!!onPickName}
                   onMouseEnter={stay}
                   onMouseLeave={() => { if (!open) leave(); }}>
          <DescriptionPopover cands={cands} name={name}
                              onPickName={onPickName}
                              onClose={() => { setOpen(false); setHover(false); }} />
        </HelpPanel>
      )}
    </>
  );
}

/** The key a thing's OWN text goes under among the candidates. It never
 *  meets a set's text in one popover (a meta tag is in no set), so the
 *  switcher never has to name it. */
const OWN_KEY = "";

/** A description's prose, with its links.
 *
 *  A WEB link leaves — new window, `noopener`, because a set is a document
 *  somebody else may have written and it is not this page's business to
 *  navigate away from the library. A TAG link stays: it opens that tag's own
 *  entry in this popover, which is what `onTag` does. */
function DescriptionText({ text, onTag }: {
  text: string; onTag: (name: string) => void;
}) {
  const t = useT();
  return (
    <>
      {parseDescription(text).map((part, i) => {
        if (part.kind === "text")
          return <React.Fragment key={i}>{part.text}</React.Fragment>;
        if (part.kind === "web")
          return (
            <a key={i} href={part.href} target="_blank" rel="noopener noreferrer"
               onClick={(e) => e.stopPropagation()} title={part.href}
               style={{ color: "var(--accent)", textDecoration: "underline",
                        textUnderlineOffset: 2 }}>
              {part.text}
            </a>
          );
        return (
          <span key={i} role="button" title={part.name}
                onClick={(e) => { e.stopPropagation(); onTag(part.name); }}
                style={{ color: "var(--accent)", cursor: "pointer",
                         textDecoration: "underline dotted",
                         textUnderlineOffset: 2 }}>
            {part.text}
          </span>
        );
      })}
    </>
  );
}

/** WHAT THE SET SAYS THE TAG IS: the subject, place or event the name stands
 *  for. Drawn as the row does — a glyph, what the record calls itself, and
 *  its own facts after it — so the popover and the Sets tab say the same
 *  thing about the same tag in the same words, down to the glyph: `person`,
 *  `place`, `event`, three strokes of one width.
 *
 *  The one-liner is the header's, beside the name.
 */
function RecordLines({ says }: { says: TagSetText }) {
  const t = useT();
  const lang = useLang();
  const when = (v?: number | null) => (v ? formatDate(v, lang) : "");
  const rows: Array<[string, string, string]> = [];
  if (says.subject) {
    const since = when(says.subject.since);
    rows.push([RECORD_ICON.subject, says.subject.name || t("a person"),
               since ? t("since {when}", { when: since }) : ""]);
  }
  if (says.place) {
    const p = says.place;
    const bits = [
      p.lat != null && p.lon != null
        ? `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}` : "",
      p.parent ? t("in {where}", { where: p.parent }) : "",
    ].filter(Boolean);
    rows.push(["place", p.name || t("a place"), bits.join(" · ")]);
  }
  if (says.event) {
    const e = says.event;
    const from = when(e.start), to = when(e.end);
    const span = from && to && from !== to ? `${from} – ${to}` : (from || to);
    const bits = [span, e.parent ? t("part of {what}", { what: e.parent }) : ""]
      .filter(Boolean);
    rows.push([RECORD_ICON.event, e.name || t("an event"), bits.join(" · ")]);
  }
  // THE COMMENT IS NOT HERE: it is the header's secondary text, beside the
  // name it is about. It is the shortest thing the popover holds and it was
  // sitting under the longest, where a one-liner about the name read as a
  // footnote to the paragraph above it rather than as the name's own gloss.
  if (rows.length === 0) return null;
  return (
    <div style={{ borderTop: "1px solid var(--border-soft)",
                  padding: "7px 11px 8px", display: "flex",
                  flexDirection: "column", gap: 4 }}>
      {rows.map(([icon, title, facts]) => (
        <div key={icon} style={{ display: "flex", alignItems: "baseline",
                                 gap: 6, fontSize: "var(--fs-2)", lineHeight: 1.45,
                                 minWidth: 0 }}>
          <Icon name={icon} size={13} color="var(--muted-3)"
                style={{ alignSelf: "center", flex: "0 0 auto" }} />
          <span style={{ color: "var(--text-2)", minWidth: 0,
                         overflowWrap: "break-word" }}>{title}</span>
          {facts && (
            <span style={{ color: "var(--muted-3)", minWidth: 0,
                           overflowWrap: "break-word" }}>{facts}</span>
          )}
        </div>
      ))}
    </div>
  );
}

/** The three name lists under a description: the entry's other spellings,
 *  what it entails, and what entails it. Each name is a link into the same
 *  walk a link in the prose takes. */
function NameLists({ says, onTag }: {
  says: TagSetText; onTag: (name: string) => void;
}) {
  const t = useT();
  const rows: Array<[string, string[]]> = [
    // WHAT THE SET LABELS IT WITH, first: often the whole of what a bulk
    // import knows about a name, and the one line that says what KIND of
    // name it is before the spellings and the entailments say what it
    // stands next to.
    [t("Labelled"), says.meta ?? []],
    [t("Aliases"), says.aliases ?? []],
    [t("Implies"), says.implies ?? []],
    [t("Implied by"), says.implied_by ?? []],
  ];
  const shown = rows.filter(([, names]) => names.length > 0);
  if (!shown.length) return null;
  return (
    // CAPPED, because `implied_by` is unbounded: `breasts` is entailed by
    // some fifty entries of the booru set, and a popover as tall as the
    // window is one nobody can read past. The lists scroll; the description
    // above them does not move.
    <div style={{ borderTop: "1px solid var(--border-soft)",
                  padding: "7px 11px 9px", display: "flex",
                  flexDirection: "column", gap: 4,
                  maxHeight: 160, overflowY: "auto" }}>
      {shown.map(([label, names]) => (
        <div key={label} style={{ display: "flex", gap: 6, fontSize: "var(--fs-2)",
                                  lineHeight: 1.45 }}>
          <span style={{ flex: "0 0 auto", color: "var(--muted-3)",
                         minWidth: 62 }}>{label}</span>
          <span style={{ minWidth: 0, fontFamily: "var(--mono)",
                         color: "var(--muted-2)", overflowWrap: "break-word" }}>
            {names.map((n, i) => (
              <React.Fragment key={n}>
                {i > 0 && ", "}
                {/* An ALIAS is not a name the walk can follow — it is this
                    very entry, said differently — so only the two lists of
                    OTHER entries are links. */}
                {/* AN ALIAS is not a name the walk can follow — it is
                    this very entry, said differently — and neither is a
                    META TAG, which labels the name rather than being one
                    of the set's own entries. */}
                {label === t("Aliases") || label === t("Labelled") ? n : (
                  <span role="button" onClick={(e) => { e.stopPropagation(); onTag(n); }}
                        style={{ cursor: "pointer", color: "var(--accent)",
                                 textDecoration: "underline dotted",
                                 textUnderlineOffset: 2 }}>
                    {n}
                  </span>
                )}
              </React.Fragment>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}

const crumbBtn: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 3, flex: "0 0 auto",
  border: "1px solid var(--border)", background: "transparent",
  color: "var(--muted-2)", borderRadius: "var(--r-3)", padding: "1px 7px",
  fontSize: "var(--fs-1)", fontWeight: 600, cursor: "pointer",
};

/** The header's two ICON buttons — borderless, because the header's own
 *  content is the tag's name and a bordered chip either side of it read as
 *  two more things to read rather than two things to press. */
const iconBtn: React.CSSProperties = {
  display: "flex", alignItems: "center", flex: "0 0 auto",
  border: "none", background: "transparent", color: "var(--muted-2)",
  borderRadius: "var(--r-2)", padding: 2, cursor: "pointer",
};

/** The popover's body: the strip (only past one candidate) and the text.
 *  Its own component so the two queries it reads are subscribed only while
 *  a popover is open, not once per row of a 250,000-tag list.
 *
 *  IT ALSO WALKS. A tag link in a description opens that tag's own entry
 *  here, behind a Back button, so following "use `solo_focus` instead" is
 *  not a matter of closing this and going to find it. The walk is a STACK of
 *  names; the frame under it is the tag the popover was opened on.
 */
function DescriptionPopover({ cands, name, onClose, onPickName }: {
  cands: TagSetText[];
  /** TAKE THIS TAG — given by a FIELD, whose half-typed word the popover's
   *  subject is a better answer to. The walk is what makes it worth having:
   *  a description that says "use `solo_focus` instead" is followed here,
   *  and the name at the top is then the one you meant to type. */
  onPickName?: (name: string) => void;
  /** Puts the popover away — what the ✕ does. */
  onClose: () => void;
  /** The tag this popover is ABOUT, where the caller knows it — an
   *  autocomplete row does, a set entry's own field does not (that one is
   *  already looking at the row). Without it the first frame offers no jump,
   *  since there is nowhere to jump to that is not already here. */
  name?: string;
}) {
  const t = useT();
  const { keys, loaded, prefer } = useTagSetOrder();
  const names = useTagSetNames();
  const ids = useTagSetIds();
  const showTag = useUI((s) => s.showTagInTagSet);
  const showCategory = useUI((s) => s.showCategoryInTagSet);
  // THE WALK. Empty = the tag the popover was opened on; every push is a tag
  // link somebody followed.
  const [trail, setTrail] = React.useState<string[]>([]);
  const at = trail.length ? trail[trail.length - 1] : null;
  // WHICH TAG THIS FRAME IS ABOUT. A frame reached by a link always knows;
  // the one under it knows only what the caller passed.
  const about = at ?? name ?? null;
  // ASKED FOR EVERY FRAME, not only the walked ones. A caller hands over
  // what it has to hand — the Sets tab builds a candidate out of the row it
  // is drawing, which has the text and the count but cannot know what OTHER
  // entries entail this one — so the popover asks, and merges what comes
  // back over what it was given, by set. One request per open, and only one
  // popover is ever open.
  const asked = useQuery({
    queryKey: ["tag-sets", "describe", about ?? ""],
    queryFn: () => api.describeNames([about as string]),
    enabled: about != null,
    staleTime: 60_000,
  });
  const fetched = about != null ? asked.data?.[about]?.descriptions : undefined;
  const here: TagSetText[] = React.useMemo(() => {
    if (at != null) return fetched ?? [];
    const richer = new Map((fetched ?? []).map((d) => [d.key, d]));
    // The caller's list decides WHICH sets are shown (its own may be
    // disabled, and `describe` answers only for enabled ones); the fetch
    // decides what each of them says.
    const merged = cands.map((c) => richer.get(c.key) ?? c);
    const extra = (fetched ?? []).filter(
      (d) => !cands.some((c) => c.key === d.key));
    return [...merged, ...extra];
  }, [at, cands, fetched]);
  // THE STRIP'S ORDER IS FIXED FOR THE LIFE OF THE POPOVER. Picking a set
  // writes it to the front of the preference, which is what the NEXT popover
  // opens on — reordering this one moved the chip that had just been clicked
  // out from under the pointer. So the order is taken once, from the first
  // loaded preference, and the pick only changes which chip is lit.
  const fixed = React.useRef<string[] | null>(null);
  if (fixed.current === null && loaded) fixed.current = keys;
  const orderKeys = fixed.current ?? keys;
  const ordered = React.useMemo(() => orderTexts(here, orderKeys), [here, orderKeys]);
  const [picked, setPicked] = React.useState<string | null>(null);
  const shown = ordered.find((c) => c.key === picked) ?? ordered[0];
  // The library's own frame is named even before its set row exists — the
  // row is lazy, so `names` need not have heard of it yet.
  const label = (key: string) =>
    names[key] ?? (key === LIBRARY_SET_KEY ? t("Library") : key);
  // WHAT THE JUMP NEEDS: which tag this frame is about, and which set says
  // so. A frame reached by a link always knows the first; the one under it
  // knows only what the caller passed. A thing's OWN text (`OWN_KEY`) is in
  // no set and has nowhere to go.
  const subject = about;
  const jumpTo = shown && subject && shown.key !== OWN_KEY
    ? ids[shown.key] : undefined;
  // THE ONE-LINER, WHERE THE NAME IS. It is a gloss on the name and nothing
  // else — "the sixth Genshin traveller", "a street in Shibuya" — so it
  // reads as the header's secondary text rather than as a line under the
  // paragraph, which is where it sat and where it read as a footnote to the
  // description rather than as a caption on the title.
  const gloss = (shown?.comment || "").trim();
  return (
    <div style={{ maxWidth: 380 }}>
      {/* THE HEADER IS ALWAYS THERE, and the tag's NAME is its title —
          reading a description without the name above it means keeping
          track of which row was clicked, and the popover walks now, so the
          row you clicked is not always the tag you are reading. The Back
          button appears only once the walk has begun; the ✕ is always the
          way out; the jump is an icon, since the name beside it already
          says what it would jump to. */}
      <div style={{ display: "flex", alignItems: "center", gap: 4,
                    padding: "6px 7px 0" }}>
        {trail.length > 0 && (
          <button type="button" title={t("Back")}
                  onClick={(e) => { e.stopPropagation(); setTrail(trail.slice(0, -1)); }}
                  style={iconBtn}>
            <Icon name="arrow_back" size={14} />
          </button>
        )}
        {onPickName && subject ? (
          <button type="button" title={t("Use this tag")}
            onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
            onClick={(e) => {
              e.stopPropagation();
              onPickName(subject);
              onClose();
            }}
            style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", minWidth: 0,
                     fontWeight: 600, color: "var(--accent)",
                     overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap", background: "none", border: "none",
                     padding: 0, cursor: "pointer" }}>
            {subject}
          </button>
        ) : (
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", minWidth: 0,
                         fontWeight: 600, color: "var(--text-2)", overflow: "hidden",
                         textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {subject ?? ""}
          </span>
        )}
        {gloss && (
          // It YIELDS BEFORE THE NAME does — `flex: 0 20 auto` against the
          // name's own shrink of 1, the name-row rule everywhere here — so a
          // long gloss on a short tag ellipsizes rather than pushing the tag
          // out of its own header. The whole of it is in the tooltip, and in
          // the row this popover was opened from.
          <span title={gloss}
                style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", minWidth: 0,
                         flex: "0 20 auto", overflow: "hidden",
                         textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {gloss}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {jumpTo != null && (
          <>
            {/* EDIT IT WHERE IT LIVES: the popover is where you find out that
                a set's wording is wrong, and the row that holds it is three
                clicks away otherwise. The same landing the jump does, with
                its editor opened on arrival. */}
            {/* BOTH PUT THE POPOVER AWAY. They are the two things in it that
                take you somewhere else — the second leaves a dialog open
                behind it otherwise, and the first leaves the popover sitting
                over the editor it just opened. */}
            <button type="button" title={t("Edit this entry")}
                    onClick={(e) => {
                      e.stopPropagation();
                      showTag(jumpTo, subject as string, true);
                      onClose();
                    }}
                    style={iconBtn}>
              <Icon name="edit" size={14} />
            </button>
            <button type="button" title={t("Show this tag in the set")}
                    onClick={(e) => {
                      e.stopPropagation();
                      showTag(jumpTo, subject as string);
                      onClose();
                    }}
                    style={iconBtn}>
              <Icon name="jump_to_element" size={14} />
            </button>
          </>
        )}
        <button type="button" title={t("Close")}
                onClick={(e) => { e.stopPropagation(); onClose(); }}
                style={iconBtn}>
          <Icon name="close" size={14} />
        </button>
      </div>
      {/* THE STRIP, and the FIGURE on it. How common a tag is only means
          anything beside the name of the set that counted it — two sets
          count different libraries — so the count rides the capsule rather
          than standing alone. And a lone capsule is worth drawing when it
          carries one: with several sets the strip switches between them,
          with one it says where the number came from. */}
      {(ordered.length > 1 || ordered.some((c) => c.count != null)) && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: "7px 8px 0" }}>
          {ordered.map((c) => {
            const on = c.key === shown.key;
            return (
              <button
                key={c.key}
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setPicked(c.key);
                  // Remembered: the set read last is the set read first
                  // next time, on every tag.
                  prefer(c.key);
                }}
                title={on ? t("Shown first from now on") : label(c.key)}
                style={{
                  border: `1px solid ${on ? "transparent" : "var(--border)"}`,
                  background: on ? "var(--accent-dim)" : "transparent",
                  color: on ? "var(--selected-text)" : "var(--muted-2)",
                  borderRadius: "var(--r-3)", padding: "1px 7px", fontSize: "var(--fs-1)",
                  fontWeight: 600, letterSpacing: "0.02em", cursor: "pointer",
                  maxWidth: 210, overflow: "hidden", textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {label(c.key)}
                {c.count != null && (
                  <span style={{ marginLeft: 5, fontFamily: "var(--mono)",
                                 fontWeight: 500,
                                 opacity: on ? 0.75 : 1,
                                 color: on ? "inherit" : "var(--muted-3)" }}>
                    {compactCount(c.count)}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
      {/* WHERE THE SET FILES THE TAG — its category, which is half of what
          a set says about a name. Nothing for an uncategorized entry. The
          trail arrives as the LIST of names and is drawn with chevrons; it
          is never a path to be split, since a name may hold a `/`. */}
      {/* `pre-wrap`: the line breaks are the point of the field. */}
      {/* THE NAME THIS IS ACTUALLY ABOUT, where they differ (owner 2026-09).
          A set answers for a spelling with its ENTRY's row, so asking about
          `manga` opened a sentence about comics with nothing saying the two
          are one entry — the description read as belonging to some other
          tag. The entry's name is a link, so the walk can go to it. */}
      {shown?.alias_of && (
        <div style={{ padding: "8px 11px 0", fontSize: "var(--fs-2)",
                      lineHeight: 1.45, color: "var(--muted-2)" }}>
          {t("Another spelling of")}{" "}
          <span role="button"
                onClick={(e) => { e.stopPropagation();
                                  setTrail([...trail, shown.alias_of!]); }}
                style={{ cursor: "pointer", fontFamily: "var(--mono)",
                         color: "var(--accent)",
                         textDecoration: "underline dotted",
                         textUnderlineOffset: 2 }}>
            {shown.alias_of}
          </span>
        </div>
      )}
      <div style={{
        padding: "9px 11px", fontSize: "var(--fs-3)", lineHeight: 1.5,
        color: "var(--text-2)", whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
      }}>
        {shown
          ? (shown.text
              ? <DescriptionText text={shown.text}
                                 onTag={(n) => setTrail([...trail, n])} />
              : <span style={{ color: "var(--muted-3)", fontStyle: "italic" }}>
                  {t("No description.")}
                </span>)
          : <span style={{ color: "var(--muted-2)" }}>
              {asked.isPending
                ? t("Reading…") : t("No enabled set knows this tag.")}
            </span>}
      </div>
      {/* WHERE THE SET FILES THE TAG, under what it says about it rather
          than over it: the category answers a question the description has
          already raised, and above the text it read as a heading. The trail
          arrives as the LIST of names and is drawn with chevrons; it is
          never a path to be split, since a name may hold a `/`. */}
      {shown?.trail && shown.trail.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 4,
                      padding: "0 11px 9px", fontSize: "var(--fs-2)",
                      color: "var(--muted-2)" }}>
          <Icon name="folder" size={13} />
          {/* EVERY NAME IS A WAY INTO THAT CATEGORY, the Sets tab's Category
              column one level up: the trail is what a set says about a tag as
              much as its sentence is, and reading it should not mean going to
              find it. A trail leads somewhere only when the set it came from
              is one this library has (`jumpTo`) — a thing's own text is in no
              set and has nowhere to go. */}
          <span>
            <CategoryTrail
              trail={shown.trail}
              pickTitle={jumpTo != null ? t("Show this category") : undefined}
              onPick={jumpTo != null
                ? (i) => {
                    showCategory(jumpTo, shown.trail!.slice(0, i + 1));
                    onClose();
                  }
                : undefined} />
          </span>
        </div>
      )}
      {/* WHAT ELSE THE SET KNOWS. Three lists, each drawn only when it has
          something in it, and every name in them a link — following one is
          the same walk a link in the prose takes. `implied_by` is the
          implication table read the other way round, which is the half an
          entry cannot carry itself. */}
      {/* AND WHAT THE SET SAYS THE TAG IS — the one-liner it should carry,
          and whether the name is somebody, somewhere or something that
          happened. This popover is often the ONLY place a name is met: a
          half-typed word in a field, a row in an autocomplete. "Who is
          this" belongs where the name is being read, not only in the Sets
          tab's list. */}
      {shown && <RecordLines says={shown} />}
      {shown && (
        <NameLists says={shown} onTag={(n) => setTrail([...trail, n])} />
      )}
    </div>
  );
}

/** The short one. `onEnter` saves, as every one-line field in these dialogs
 *  does — a textarea below it deliberately does not. */
export function CommentField({ value, onChange, onEnter, placeholder }: {
  value: string;
  onChange: (v: string) => void;
  onEnter?: () => void;
  /** What this KIND of thing's one-liner is for; the label is always the
   *  same word, and the example is what tells you the length wanted. */
  placeholder?: string;
}) {
  const t = useT();
  return (
    <div>
      <Label>{t("Comment")}</Label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && onEnter) onEnter(); }}
        placeholder={placeholder ?? t("One line, shown beside the name…")}
        style={field}
      />
    </div>
  );
}

/** The long one. A textarea, because line breaks are the field's whole
 *  point — Enter types one rather than saving the dialog. */
export function DescriptionField({ value, onChange }: {
  value: string;
  onChange: (v: string) => void;
}) {
  const t = useT();
  return (
    <div>
      <Label>{t("Description")}</Label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t("The long form — what it covers, when to reach for it, what it is not. Shown behind the ? beside the name.")}
        rows={4}
        style={{
          ...field, height: "auto", minHeight: 84, padding: "8px 11px",
          lineHeight: 1.5, resize: "vertical",
          // A paragraph field in a dialog of one-line inputs: the family is
          // the reading one, not the mono the name fields use.
          fontFamily: "var(--sans)",
        }}
      />
    </div>
  );
}
