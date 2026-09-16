import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { rowBackground } from "../../shared/Row";
import { GroupNode } from "../api";
import { Icon } from "../../shared/Icon";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { SearchField } from "../../shared/SearchField";
import { useEscape } from "../../shared/useEscape";
import { useT } from "../../shared/i18n";
import { useMenuDismiss } from "../../shared/useMenuDismiss";

export interface GroupOption {
  id: number;
  name: string;
  depth: number;
  icon: string;
  color: string | null;
  count: number;
  /** The names of its ancestors, outermost first — empty at the top level.
   *  What a list that shows one group OUT of the tree says instead of the
   *  indentation it no longer has (`a › costumes`). */
  trail?: string[];
  /** Its parent's id, `null` at the top level. What a list that PAGES the
   *  tree needs (the autocomplete's browse), where a depth alone cannot say
   *  whose child a row is. */
  parent: number | null;
}

// Flatten a group tree (alphabetically per level) to indented options carrying
// each group's own icon, color and item count, so dropdowns can show the
// hierarchy and sizes visually.
export function flattenGroupTree(
  nodes: GroupNode[],
  depth = 0,
  out: GroupOption[] = [],
  trail: string[] = [],
  parent: number | null = null,
): GroupOption[] {
  for (const n of [...nodes].sort((a, b) => a.name.localeCompare(b.name))) {
    // SMART groups are never container targets — no manual members, no
    // child groups — so no picker offers one (they hold no children, so
    // nothing below them is lost by the skip).
    if (n.smart) continue;
    out.push({ id: n.id, name: n.name, depth, icon: n.icon, color: n.color,
               count: n.count, trail, parent });
    flattenGroupTree(n.children, depth + 1, out, [...trail, n.name], n.id);
  }
  return out;
}

function optColor(o: GroupOption): string {
  return o.color || "var(--muted-2)";
}

/**
 * A group picker that shows the tree hierarchy (indentation) and each group's
 * icon/color — things a native <select> can't render. `value` is the chosen
 * group id (or null for the top-level / "Ungrouped" choice). `excluded` hides
 * ids that would be invalid choices (e.g. a group and its own descendants).
 */
export function GroupSelect({
  tree,
  value,
  onChange,
  excluded,
  ungroupedLabel = "Ungrouped",
  ungroupedIcon = "folder_off",
}: {
  tree: GroupNode[];
  value: number | null;
  onChange: (id: number | null) => void;
  excluded?: Set<number>;
  ungroupedLabel?: string;
  ungroupedIcon?: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  // WHAT IS TYPED IN THE DROPDOWN, and which row the arrows are on. The
  // picker lists the whole tree, which in a real library is hundreds of rows
  // inside a capped, scrolling box — finding one meant scrolling it. Cleared
  // on every open, so the list a press opens is always the whole tree.
  const [query, setQuery] = useState("");
  // WHICH ROW IS HIGHLIGHTED, and -1 for NONE. It used to open at 0, so a
  // dropdown nobody had touched yet arrived with its first row lit — a
  // highlight that looks like a selection over a list where one row really is
  // selected — and then followed the pointer around. The arrows create it and
  // the pointer moves it while it is over the list; leaving the list takes a
  // pointer-made one away again.
  const [hi, setHi] = useState(-1);
  const hiFromMouse = useRef(false);
  const ref = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // PORTALLED, not an absolutely-positioned sibling. This picker sits in
  // scrolling panels — the sidebar's whole-view actions, the group and item
  // dialogs — where a sibling both scrolls away with the content and is
  // clipped by whatever has `overflow` on it. `AnchoredDropdown` is what
  // every other menu here uses: it stays glued to the button, prefers to
  // open below it and flips ABOVE when the space below is cramped, capping
  // its height to what is there and scrolling inside that.
  const rect = useAnchorRect(ref, open);

  const options = useMemo(() => flattenGroupTree(tree), [tree]);
  const selected = value == null ? null : options.find((o) => o.id === value) ?? null;
  const q = query.trim().toLowerCase();
  // MATCHED ON THE WHOLE PATH, so a parent's name finds everything under it
  // (`costumes` and `a › costumes` both answer to "a"), which is the question
  // somebody types a parent into this field to ask.
  const visible = options.filter((o) =>
    !excluded?.has(o.id)
    && (!q || [...(o.trail ?? []), o.name].join(" › ").toLowerCase().includes(q)));
  const ungroupedShown = !q || ungroupedLabel.toLowerCase().includes(q);

  // ONE FLAT LIST for the arrows — "Ungrouped" is a row like any other, and a
  // keyboard walk that skipped it could not reach the choice it names.
  const rows: (GroupOption | null)[] = [
    ...(ungroupedShown ? [null] : []), ...visible,
  ];
  // TYPING is keyboard work, so a search highlights its first match (Enter
  // then takes it); an empty field highlights nothing.
  useEffect(() => { setHi(q ? 0 : -1); hiFromMouse.current = false; }, [q]);
  useEffect(() => { if (open) { setQuery(""); setHi(-1); } }, [open]);
  // OPENED ON THE GROUP IT IS SET TO. The picker lists the whole tree, so the
  // chosen row is routinely hundreds of rows down a scrolling box and the
  // dropdown opened at the top showing no sign of it. The list is scrolled
  // itself rather than through `scrollIntoView`, which walks every scrollable
  // ancestor and would move the page the dropdown is portalled onto.
  //
  // NOT ON THE OPENING RENDER: `AnchoredDropdown` renders NOTHING until the
  // anchor has been measured, so at the press there is no list and no row to
  // scroll to — the scroll has to wait for the render that has both. Hence a
  // once-per-open latch rather than an effect on `open` alone, which fired
  // into an empty portal and never ran again.
  const scrolled = useRef(false);
  useEffect(() => { if (!open) scrolled.current = false; }, [open]);
  useLayoutEffect(() => {
    if (!open || scrolled.current) return;
    const box = listRef.current;
    const row = box?.querySelector<HTMLElement>("[data-groupopt-picked]");
    if (!box || !row || !box.clientHeight) return;
    scrolled.current = true;
    box.scrollTop = Math.max(
      0, row.offsetTop - (box.clientHeight - row.offsetHeight) / 2);
  });
  const pick = (o: GroupOption | null) => {
    onChange(o ? o.id : null);
    setOpen(false);
  };

  useMenuDismiss(open, () => setOpen(false), { within: [ref] });
  // ESCAPE IS A TWO-STEP, and it has to be taken over a FIELD — `SearchField`
  // clears itself on Escape and stops there, so with an empty field nothing
  // answered at all and the only way out of the dropdown was the mouse.
  // Declared after `useMenuDismiss` so this entry sits above the one it
  // registers (the stack answers last-pushed first).
  useEscape(() => { if (query) setQuery(""); else setOpen(false); },
            { enabled: open, overFields: true });

  const onFieldKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (rows.length === 0) return;
      hiFromMouse.current = false;
      const step = e.key === "ArrowDown" ? 1 : -1;
      // From NO highlight the arrows start at the group this is already set
      // to — the row the list opened on — and at the top when that is not in
      // the list.
      setHi((i) => i < 0
        ? Math.max(0, rows.findIndex((o) => (o ? o.id : null) === value))
        : Math.min(rows.length - 1, Math.max(0, i + step)));
    } else if (e.key === "Enter") {
      e.preventDefault();
      // With nothing highlighted, Enter takes the first row — which is what
      // somebody who typed a search and pressed it meant.
      if (rows.length > 0) pick(rows[Math.min(Math.max(hi, 0), rows.length - 1)]);
    }
  };

  const rowBase: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 8, padding: "7px 10px",
    // The dropdown box carries its own padding, so a row's highlight is
    // inset from its edges and wants a radius of its own — every other
    // menu built on `AnchoredDropdown` has one.
    borderRadius: "var(--r-2)",
    cursor: "pointer", fontSize: "var(--fs-3)", whiteSpace: "nowrap",
  };

  return (
    <div ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%", height: 36, padding: "0 10px 0 12px",
          background: "var(--bg)", border: "1px solid var(--border-strong)",
          borderRadius: "var(--r-5)", color: "var(--text-2)", fontSize: "var(--fs-3)", cursor: "pointer",
          display: "flex", alignItems: "center", gap: 8, outline: "none",
        }}
      >
        <Icon
          name={selected ? selected.icon : ungroupedIcon}
          size={16}
          color={selected ? optColor(selected) : "var(--muted)"}
        />
        <span style={{ flex: 1, textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {selected ? selected.name : ungroupedLabel}
        </span>
        <Icon name="expand_more" size={18} color="var(--muted)" />
      </button>
      {open && (
        // `fill` + `focusable`: the field stays put while the ROWS scroll (a
        // box that scrolls its own scrolling child shows two bars moving
        // different amounts), and the press that focuses the field must not
        // be the press that closes the menu.
        <AnchoredDropdown rect={rect} fill focusable>
          <div style={{ display: "flex", flexDirection: "column", minHeight: 0, gap: 6 }}>
            <SearchField
              value={query}
              onChange={setQuery}
              size="sm"
              autoFocus
              placeholder={t("Search groups")}
              clearTitle={t("Clear the search")}
              onKeyDown={onFieldKey}
              style={{ flex: "0 0 auto" }}
            />
            <div
              ref={listRef}
              // A highlight the POINTER made belongs to the pointer: it goes
              // when the pointer does. One the arrows made stays put — the
              // hand is on the keyboard, and the mouse resting elsewhere is
              // not an answer about it.
              onMouseLeave={() => {
                if (!hiFromMouse.current) return;
                hiFromMouse.current = false;
                setHi(-1);
              }}
              style={{ flex: 1, minHeight: 0, overflowY: "auto" }}
            >
              {rows.length === 0 && (
                <div style={{ ...rowBase, cursor: "default", color: "var(--muted-2)" }}>
                  {t("No group matches")}
                </div>
              )}
              {rows.map((o, i) => (
                <GroupRow
                  key={o ? o.id : "none"}
                  option={o}
                  // WHILE SEARCHING THERE IS NO TREE LEFT TO INDENT AGAINST —
                  // a match's parents are usually filtered out — so the row
                  // prints its ancestors instead, which is what `trail` is for.
                  searching={!!q}
                  picked={o ? value === o.id : value == null}
                  active={i === hi}
                  rowBase={rowBase}
                  ungroupedLabel={ungroupedLabel}
                  ungroupedIcon={ungroupedIcon}
                  onPick={() => pick(o)}
                  onHover={() => { hiFromMouse.current = true; setHi(i); }}
                />
              ))}
            </div>
          </div>
        </AnchoredDropdown>
      )}
    </div>
  );
}


/** One row of the picker: "Ungrouped" when `option` is null, else the group. */
function GroupRow({ option, searching, picked, active, rowBase, ungroupedLabel,
                    ungroupedIcon, onPick, onHover }: {
  option: GroupOption | null;
  searching: boolean;
  picked: boolean;
  active: boolean;
  rowBase: React.CSSProperties;
  ungroupedLabel: string;
  ungroupedIcon: string;
  onPick: () => void;
  onHover: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // The arrows can walk past the box's edge, and a highlight nobody can see
  // is the same as none.
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest" });
  }, [active]);
  const trail = option?.trail ?? [];
  return (
    <div
      ref={ref}
      className="hoverable"
      // What an opening dropdown scrolls to — the row it is already set to.
      {...(picked ? { "data-groupopt-picked": "" } : {})}
      onClick={onPick}
      onMouseMove={onHover}
      style={{
        ...rowBase,
        paddingLeft: 10 + (searching ? 0 : (option?.depth ?? 0) * 16),
        background: rowBackground(picked || active, "transparent"),
      }}
    >
      <Icon name={option ? option.icon : ungroupedIcon} size={16}
            color={option ? optColor(option) : "var(--muted)"} />
      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
        {searching && trail.length > 0 && (
          <span style={{ color: "var(--muted-3)" }}>{trail.join(" › ")} › </span>
        )}
        {option ? option.name : ungroupedLabel}
      </span>
      {!!option && option.count > 0 && (
        <span style={{ flex: "0 0 auto", fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-3)" }}>
          {option.count}
        </span>
      )}
    </div>
  );
}
