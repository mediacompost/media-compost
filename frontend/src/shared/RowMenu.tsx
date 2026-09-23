/** The ⋯ menu a sidebar row shows on hover.
 *
 * The subjects, locations and faces sections all ended up with the same two or
 * three per-row actions spelled out as icons, which is what pushed their rows
 * past the sidebar's width: a name, a comment, a date and three buttons do not
 * fit in 280 px, and the first thing to be truncated was always the name. One
 * button that only appears on hover gives the row back its width and gives each
 * action a readable label instead of a tooltip.
 *
 * It is portalled (`AnchoredDropdown`) rather than absolutely positioned: the
 * sidebar scrolls, so a menu on the last row would otherwise be clipped by the
 * panel it lives in.
 */
import React, { useEffect, useRef, useState } from "react";
import { MenuRow } from "./MenuRow";
import { SectionHeading } from "./SectionHeading";
import { Icon } from "./Icon";
import { AnchoredDropdown, useAnchorRect } from "./AnchoredDropdown";
import { useMenuDismiss } from "./useMenuDismiss";
import { isTypingTarget } from "./typingTarget";

export interface RowAction {
  /** Omitted where `checked` owns the slot, or to leave it blank. */
  icon?: string;
  label: string;
  /** A STATE rather than an action: the item shows a tick when this is true
   *  and an empty gutter when it is false, so the ones that toggle line up
   *  with the ones that do not. Takes the icon's place. */
  checked?: boolean;
  /** Muted second line — what the action actually does, where the verb alone
   *  is ambiguous ("Edit" changes the subject everywhere, not just here). */
  hint?: string;
  /** A tooltip — for what would not fit a hint (the grid's Copy row lists
   *  every kind it would take, with counts). */
  title?: string;
  danger?: boolean;
  /** Draws a rule ABOVE this item. For where the menu changes subject — the
   *  actions that only LOOK at the thing, then the ones that change it. */
  separated?: boolean;
  /** Muted and inert — for a toggle whose precondition is off (the Quick
   *  Assign mode under its master switch). Shown rather than hidden, so the
   *  state it holds stays readable. */
  disabled?: boolean;
  /** Secondary text at the item's right edge — a count beside a name, the
   *  way the sub-tab buttons carry theirs. */
  trailing?: string;
  /** A glyph at the right edge — the outward arrow on an action that opens
   *  a window of its own. */
  trailingIcon?: string;
  /** The key that does the same thing, drawn as a keycap at the right edge
   *  — the quick-actions menu's rule: a shortcut that lives nowhere visible
   *  is one nobody finds. */
  kbd?: string;
  /** Picking this leaves the menu up — a checkbox row in a menu of several,
   *  where closing on every tick would make three ticks three opens. */
  keepOpen?: boolean;
  /** The same verb in as few words as a BUTTON can carry — "Delete" for
   *  "Delete these faces". A menu has a column to explain itself in and a
   *  bar of buttons has a row, so the two want different lengths of the
   *  same action; a caller that draws these as buttons reads this and
   *  falls back to the label. */
  short?: string;
  /** The item IS the current choice: tinted the way a selected row is,
   *  where `checked` would draw a tick in the icon's place. */
  active?: boolean;
  /** A SUBMENU: the item opens a panel beside itself instead of doing
   *  anything. For a verb with two readings that would otherwise be two
   *  top-level entries explaining themselves in hints — "Implied tags", then
   *  append or replace. An item with children ignores `onClick`. */
  children?: RowAction[];
  onClick: () => void;
}

export function RowMenu({ actions, title, always, icon = "more_horiz",
                          color = "var(--muted-2)", buttonStyle, label, onAccent,
                          heading, disabled, minWidth = 190 }: {
  actions: RowAction[];
  title: string;
  /** Named ONCE, at the top, so the verbs under it need no number of their
   *  own — "4 selected / Merge… / Delete" rather than four verbs each
   *  repeating the count. `PointerMenu` has had this; a right-click and a ⋯
   *  over the same rows should not read differently. */
  heading?: string;
  /** The trigger sits on an ACCENT fill (a selected pill), so its hover
   *  must not be the accent-on-accent the shared rule paints. */
  onAccent?: boolean;
  /** A trigger drawn as something other than the 20 px glyph square — the
   *  Sets tab's "+" wears the same pill its set buttons do, so the menu that
   *  makes a set sits in the row of sets as one of them. Merged over the
   *  default style; `label` follows the icon inside it. */
  buttonStyle?: React.CSSProperties;
  label?: React.ReactNode;
  /** Visible without hovering the row. For a list where the menu holds the
   *  only way to do most of what the row can do — a person's date, their
   *  subject record, where else they appear — hiding it means the actions
   *  exist only for somebody who already knows they are there. */
  always?: boolean;
  /** The button's glyph — vertical ⋮ on a row (the default), horizontal ⋯
   *  where it sits in a header beside other horizontal marks; null for a
   *  trigger that is its `label` alone (a counter pill). */
  icon?: string | null;
  /** The glyph's colour. The default is the row idiom; a header whose other
   *  marks are drawn in `--muted` passes that, or its ⋯ reads darker than
   *  the buttons either side of it. */
  color?: string;
  /** The trigger is inert — the editor's menus while it is busy. */
  disabled?: boolean;
  minWidth?: number;
}) {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLSpanElement>(null);
  const rect = useAnchorRect(anchor, open);

  useMenuDismiss(open, () => setOpen(false), { within: [anchor] });

  return (
    <>
      <span
        ref={anchor}
        // Kept in the layout and faded in, so the value beside it never shifts
        // when the pointer arrives. An open menu stays visible regardless.
        className={(open || always ? "row-action" : "row-action row-action-fixed")
          + (onAccent ? " on-accent" : "")}
        title={title}
        onClick={(e) => { e.stopPropagation(); if (!disabled) setOpen((v) => !v); }}
        aria-disabled={disabled || undefined}
        style={{
          flex: "0 0 auto", width: 20, height: 20, display: "flex",
          alignItems: "center", justifyContent: "center", borderRadius: "var(--r-1)",
          color, cursor: disabled ? "default" : "pointer",
          background: open ? "var(--panel-2)" : "transparent",
          opacity: open ? 1 : disabled ? 0.5 : undefined,
          ...buttonStyle,
        }}
      >
        {icon && <Icon name={icon} size={16} />}
        {label}
      </span>
      {open && (
        <AnchoredDropdown rect={rect} minWidth={minWidth}>
          <MenuBody actions={actions} onDone={() => setOpen(false)}
                    heading={heading} />
        </AnchoredDropdown>
      )}
    </>
  );
}

/** The same menu, opened where the pointer is rather than under a ⋯ button.
 *
 *  A crop is too small to carry a button per action and too many to carry one
 *  each — the strip is a row of pictures, and a corner ✕ on every one of them
 *  turned it into a row of buttons. Right-click is where a menu about the
 *  thing under the pointer belongs.
 */
export function PointerMenu({ at, actions, onClose, heading }: {
  at: { x: number; y: number };
  actions: RowAction[];
  onClose: () => void;
  /** What the menu is ABOUT, where that is not obvious from where it was
   *  opened — the library grid's "{n} items" over a menu opened on a
   *  selection. Drawn as the quiet uppercase title those menus use. */
  heading?: string;
}) {
  // `onClose` is written inline at every call site (a new function every
  // render of the host, which re-renders as rows light up under the pointer);
  // the hook holds it in a ref so the listener is armed once. A scroll
  // closes it: the menu sits where the pointer was, not on anything.
  useMenuDismiss(true, onClose, { onScroll: true });
  // A zero-size rect at the pointer: the dropdown's own placement then keeps
  // it on screen and flips it up near the bottom edge, exactly as it does for
  // an anchored one.
  const rect = {
    left: at.x, right: at.x, top: at.y, bottom: at.y, width: 0, height: 0,
    x: at.x, y: at.y, toJSON: () => "",
  } as DOMRect;
  return (
    <AnchoredDropdown rect={rect} minWidth={190}>
      <MenuBody actions={actions} onDone={onClose} heading={heading} />
    </AnchoredDropdown>
  );
}

/** WHICH MENU THE KEYBOARD IS TALKING TO — the deepest open panel.
 *
 *  Every panel registers itself while mounted; a submenu mounts after its
 *  parent and so sits above it, and unmounts first. One window listener on
 *  the capture phase hands each key to the top entry only, so a parent
 *  never walks its own rows while its submenu is open. */
const menuStack: Array<(e: KeyboardEvent) => void> = [];
function onMenuKey(e: KeyboardEvent) {
  const top = menuStack[menuStack.length - 1];
  if (top) top(e);
}
function pushMenu(handler: (e: KeyboardEvent) => void): () => void {
  if (menuStack.length === 0) window.addEventListener("keydown", onMenuKey, true);
  menuStack.push(handler);
  return () => {
    const i = menuStack.lastIndexOf(handler);
    if (i >= 0) menuStack.splice(i, 1);
    if (menuStack.length === 0) window.removeEventListener("keydown", onMenuKey, true);
  };
}

/** One menu panel: an optional heading, the items, and at most one open
 *  submenu — which lives here rather than in the item so that opening one
 *  closes the last.
 *
 *  THE KEYBOARD WALKS IT. ↑/↓ move the highlight over the items that can be
 *  picked (wrapping), Home/End jump, Enter or Space picks, → opens the
 *  highlighted item's submenu on its first row and ← comes back out of one.
 *  Escape is the host's (`useMenuDismiss`). The highlight is ONE state for
 *  pointer and keys alike — an item under the pointer is the highlighted
 *  one — so the two cannot show two answers. */
function MenuBody({ actions, onDone, heading, onBack, initialHi = -1 }: {
  actions: RowAction[];
  onDone: () => void;
  heading?: string;
  /** This is a SUBMENU: ← closes it. */
  onBack?: () => void;
  /** Which item starts highlighted — the first for a panel the keyboard
   *  opened, none for one the pointer did. */
  initialHi?: number;
}) {
  const [hi, setHi] = useState(initialHi);
  // The open submenu, and whether a KEY opened it (then it starts on its
  // first row; a hover opens it with nothing highlighted).
  const [sub, setSub] = useState<{ label: string; byKey: boolean } | null>(null);
  const pickable = (a: RowAction) => !a.disabled;
  const stateRef = useRef({ actions, hi, onDone, onBack });
  stateRef.current = { actions, hi, onDone, onBack };
  useEffect(() => pushMenu((e: KeyboardEvent) => {
    const { actions, hi, onDone, onBack } = stateRef.current;
    const typing = isTypingTarget(e);
    const step = (dir: 1 | -1) => {
      const n = actions.length;
      if (!n) return;
      let i = hi;
      for (let k = 0; k < n; k++) {
        i = (i + dir + n) % n;
        if (i < 0) i = dir > 0 ? 0 : n - 1;
        if (pickable(actions[i])) { setHi(i); return; }
      }
    };
    const edge = (from: "start" | "end") => {
      const list = actions.map((a, i) => [a, i] as const).filter(([a]) => pickable(a));
      if (!list.length) return;
      setHi(from === "start" ? list[0][1] : list[list.length - 1][1]);
    };
    const current = hi >= 0 ? actions[hi] : undefined;
    switch (e.key) {
      case "ArrowDown": step(1); break;
      case "ArrowUp": step(-1); break;
      case "Home": if (typing) return; edge("start"); break;
      case "End": if (typing) return; edge("end"); break;
      case "ArrowRight":
        if (typing) return;
        if (current?.children) setSub({ label: current.label, byKey: true });
        break;
      case "ArrowLeft":
        if (typing || !onBack) return;
        onBack();
        break;
      case " ":
      case "Enter":
        if (e.key === " " && typing) return;
        if (!current || !pickable(current)) return;
        if (current.children) { setSub({ label: current.label, byKey: true }); break; }
        if (!current.keepOpen) onDone();
        current.onClick();
        break;
      default: return;
    }
    e.preventDefault();
    e.stopPropagation();
  }), []);
  return (
    <div role="menu" onClick={(e) => e.stopPropagation()}>
      {heading && (
        <SectionHeading sm style={{ padding: "4px 9px 5px" }}>
          {heading}
        </SectionHeading>
      )}
      {actions.map((a, i) => (
        <RowMenuItem key={a.label} action={a} onDone={onDone}
          // A RULE ABOVE THE FIRST ITEM IS A RULE UNDER NOTHING. An action
          // asks to be `separated` from what comes before it, and where it
          // leads the menu — the selection's, whose single-row verbs stand
          // down — there is nothing before it.
          first={i === 0 && !heading}
          hi={hi === i}
          onHover={(on) => setHi(on ? i : (hi === i ? -1 : hi))}
          open={sub?.label === a.label}
          subByKey={!!sub?.byKey}
          onSubClose={() => setSub(null)}
          // A SUBMENU OPENS ON HOVER, the way every other menu on this
          // desktop does, and hovering ANY OTHER ITEM closes it. Closing on
          // the parent's own `mouseleave` would be wrong: the panel is
          // portalled beside the item, so the pointer leaves the item on its
          // way INTO the thing it just opened. A sibling being hovered is the
          // signal that says you went somewhere else. (Clicking still works,
          // for a pointer that arrived without hovering.)
          onOpen={() => setSub(a.children ? { label: a.label, byKey: false } : null)} />
      ))}
    </div>
  );
}

function RowMenuItem({ action, onDone, first, hi, onHover, open, subByKey,
                       onSubClose, onOpen }: {
  action: RowAction;
  onDone: () => void;
  /** Leads the panel: its `separated` rule would be a rule under nothing. */
  first?: boolean;
  /** The highlighted item — under the pointer, or reached by the keys. */
  hi: boolean;
  onHover: (on: boolean) => void;
  /** This item's submenu is the open one. */
  open?: boolean;
  /** …and a key opened it, so it starts on its first row. */
  subByKey?: boolean;
  onSubClose?: () => void;
  onOpen?: () => void;
}) {
  const item = useRef<HTMLDivElement>(null);
  const sub = action.children;
  // The keys can walk past the fold of a scrolling panel.
  useEffect(() => {
    if (hi) item.current?.scrollIntoView({ block: "nearest" });
  }, [hi]);
  // A rect just RIGHT of the item and level with its top: `placement` puts a
  // panel below `rect.bottom` at `rect.left`, so a zero-height rect there is
  // a flyout, and it still flips and clamps at the window's edges like any
  // other menu.
  const box = item.current?.getBoundingClientRect();
  const at = open && box ? ({
    left: box.right + 2, right: box.right + 2,
    top: box.top - 7, bottom: box.top - 7,
    width: 0, height: 0, x: box.right + 2, y: box.top - 7,
    toJSON: () => "",
  } as DOMRect) : null;
  const color = action.disabled ? "var(--muted-3)"
    : action.danger ? "var(--danger)" : "var(--text-2)";
  return (
    <>
    {action.separated && !first && (
      <div style={{ height: 1, background: "var(--border)", margin: "4px 2px" }} />
    )}
    <MenuRow
      ref={item}
      top
      aria-haspopup={sub ? "menu" : undefined}
      aria-expanded={sub ? !!open : undefined}
      title={action.title}
      onMouseEnter={() => { onHover(true); onOpen?.(); }}
      // Leaving keeps the highlight only while this item's submenu is up —
      // the pointer is on its way into it.
      onMouseLeave={() => { if (!open) onHover(false); }}
      // A disabled item swallows nothing and does nothing — the menu stays
      // up, since the click changed no state worth closing over. NOR does a
      // parent: it opens its panel, and the menu closes when one of THOSE is
      // picked.
      onClick={sub ? (e) => { e.stopPropagation(); onOpen?.(); }
        : () => { if (!action.keepOpen) onDone(); action.onClick(); }}
      icon={action.icon} checked={action.checked} label={action.label} hint={action.hint}
      trailing={action.trailing} kbd={action.kbd}
      trailingIcon={!sub ? action.trailingIcon : undefined}
      submenu={!!sub}
      danger={action.danger} active={action.active} disabled={action.disabled} hi={hi}
    />
    {sub && at && (
      <AnchoredDropdown rect={at} minWidth={170}>
        <MenuBody actions={sub} onDone={onDone} onBack={onSubClose}
                  initialHi={subByKey ? 0 : -1} />
      </AnchoredDropdown>
    )}
    </>
  );
}
