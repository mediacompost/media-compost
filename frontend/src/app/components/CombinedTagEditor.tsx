import React, { useRef, useState } from "react";
import { rankTagMatches } from "../tagRank";
import { Icon } from "../../shared/Icon";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { TagSuggestion } from "./TagAutocomplete";
import { useRemoteSuggestions } from "./TagAutocomplete";
import { TagSuggestList, TagSuggestionRow, pickedName, useSuggestList } from "./TagSuggestList";
import { TagSetBrowseList, useTagSetBrowse } from "./TagSetBrowse";
import { tagFieldInput, tagFieldName } from "../tags";
import type { GroupOption } from "./GroupSelect";

interface Chip {
  name: string;
  negative: boolean;
}

/** One offered row of the single adder: a library GROUP to join, or a TAG to
 *  assign. Two shapes rather than one with optional halves, so every reader
 *  has to say which it is looking at. */
type AdderRow =
  | { kind: "group"; name: string; opt: GroupOption }
  | { kind: "tag"; name: string; s: TagSuggestion };

/**
 * A single combined list of tag chips (positive and negative together) with an
 * autocomplete adder. New tags are added positive; each chip carries a +/−
 * toggle that flips it between positive and negative, and a × to remove it.
 * Shared by the Quick Assign panel and the group-properties modal so both read
 * the same way.
 *
 * With `onAddGroup` set, the editor ALSO carries GROUP-membership chips —
 * the accent, with a folder, so they cannot be read as tags, at the tags'
 * own size and spacing — and ONE adder answers for both: the empty field
 * opens on the groups and the tag sets' tree together, and typing narrows
 * both at once (groups first, then tags, then the offer to create). It was
 * two adders side by side, which asked you to decide what you were looking
 * for before you had looked. Without `onAddGroup` the editor is tag-only,
 * exactly as it was — the group-properties overlay is that caller.
 */
export function CombinedTagEditor({
  pos,
  neg,
  suggestions = [],
  fetchSuggestions,
  leading,
  onAdd,
  onFlip,
  onRemove,
  groups = [],
  groupOptions = [],
  onAddGroup,
  onRemoveGroup,
  addersBelow = false,
}: {
  pos: string[];
  neg: string[];
  suggestions?: TagSuggestion[];
  /** Opt-in remote mode: fetch what matches the typed fragment (debounced)
   *  instead of filtering a catalog the owner had to hold whole.
   *  `suggestions` is ignored while this is set. */
  fetchSuggestions?: (q: string) => Promise<TagSuggestion[]>;
  // Optional element rendered before the first chip (e.g. the stash button).
  leading?: React.ReactNode;
  onAdd: (tag: string) => void;
  onFlip: (tag: string) => void;
  onRemove: (tag: string) => void;
  /** GROUP memberships carried beside the tags (ids), with the catalog the
   *  adder offers. The group half renders only while `onAddGroup` is set. */
  groups?: number[];
  groupOptions?: GroupOption[];
  onAddGroup?: (groupId: number) => void;
  onRemoveGroup?: (groupId: number) => void;
  /** Put the two adder chips on their OWN line under the chips (the Quick
   *  Assign drawer's layout) instead of trailing the last chip. */
  addersBelow?: boolean;
}) {
  // ONE adder. `"group"` was a second state beside `"tag"`; with the two
  // lists merged there is only the one field, and the tag-only caller has
  // the same one with nothing but tags in it.
  const [adding, setAdding] = useState<null | "tag">(null);
  const [text, setText] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  // Always alphabetical (regardless of sign) so flipping a chip's polarity never
  // reorders the list.
  const chips: Chip[] = [
    ...pos.map((name) => ({ name, negative: false })),
    ...neg.map((name) => ({ name, negative: true })),
  ].sort((a, b) => a.name.localeCompare(b.name));
  const present = new Set([...pos, ...neg]);

  const q = tagFieldName(text);
  const { rows: remote, settled } = useRemoteSuggestions(
    adding === "tag" ? q : "", fetchSuggestions);
  const source = fetchSuggestions ? remote : suggestions;
  // TAGS only — a namespace is not an answer to "which tag". Typing the
  // prefix narrows to one by itself, which is what the substring match was
  // always going to do. The ranking (exact, then match position — and only
  // THEN the cap) is `rankTagMatches`, pure and tested, because cutting
  // before ranking is the bug that made an existing "test" unaddable.
  const tagMatches = adding === "tag" ? rankTagMatches(source, q, present) : [];
  // The COMMITTED form, so what is offered is what the API will store — a
  // trailing colon included, since `d:` is a tag somebody writes. Offered
  // only once the rows answer THIS fragment (`settled`), or it offers to
  // create a name the previous fragment's rows simply do not contain.
  const create = q;
  const canCreate = adding === "tag" && settled && create.length > 0
    && !source.some((s) => s.name.toLowerCase() === create) && !present.has(create);
  // The GROUP adder's own matches — the same ranking, over the catalog of
  // groups not already on the set (`rankTagMatches` is generic over
  // anything with a name).
  const gq = text.trim().toLowerCase();
  const freeGroups = onAddGroup ? groupOptions.filter(
    (o) => !groups.includes(o.id)) : [];
  // Unlike the tag catalog, the group list is small enough to OFFER whole:
  // an empty field lists every group (tree order, in the browse's own
  // section), and typing narrows it beside the tags.
  const groupMatches = adding === "tag" && gq
    ? rankTagMatches(freeGroups, gq, new Set<string>(), 50) : [];

  const close = () => {
    setText("");
    setAdding(null);
  };
  const commit = (tag: string) => {
    onAdd(tag);
    close();
  };
  const commitGroup = (id: number) => {
    onAddGroup?.(id);
    close();
  };
  // ONE list over both kinds — the highlight, the arrows, Enter and the
  // Create-first shape are `TagSuggestList`'s; the adder keeps Escape and
  // blur, which are about the transient INPUT rather than the list. Groups
  // lead: there are a few of them against a catalog of names, so they would
  // otherwise sit past the cap that a fragment like `a` fills by itself.
  const rows: AdderRow[] = [
    ...groupMatches.map((opt) => ({ kind: "group" as const,
                                    name: `\u0000g${opt.id}`, opt })),
    ...tagMatches.map((s) => ({ kind: "tag" as const, name: s.name, s })),
  ];
  const browseRef = useRef<{ open: boolean; handleKey: (e: React.KeyboardEvent) => boolean }>(
    { open: false, handleKey: () => false });
  const tagList = useSuggestList<AdderRow>({
    matches: rows, create: canCreate ? create : null, settled,
    // The field's own keys and blur are the hook's too: Enter with the
    // list closed adds the typed name (it used to do nothing), Escape
    // closes the list first and the field second, a blur closes the field.
    input: {
      preKey: (e) => browseRef.current.open && browseRef.current.handleKey(e),
      alsoOpen: () => browseRef.current.open,
      onCommitTyped: () => { if (create) commit(create); },
      onCancel: close,
      onBlur: close,
    },
    onPick: (row) => {
      if (row.kind === "action") return;   // this list offers none
      if (row.kind === "create") return commit(row.name);
      if (row.item.kind === "group") return commitGroup(row.item.opt.id);
      commit(pickedName(row.item.s));
    },
  });
  // The adder opens on the TREE (`TagSetBrowse`) until something is typed —
  // the chip is pressed to add something, and with nothing typed yet the
  // groups and the sets' categories are what there is to choose from.
  const bro = useTagSetBrowse({
    active: adding === "tag" && q === "", onPick: commit, existing: present,
    groups: onAddGroup ? freeGroups : undefined,
    onPickGroup: onAddGroup ? (id) => commitGroup(id) : undefined,
  });
  const browseOpen = adding === "tag" && q === "" && bro.ready && bro.rows.length > 0;
  browseRef.current = { open: browseOpen, handleKey: bro.handleKey };
  const listOpen = adding === "tag" && (tagList.rows.length > 0 || browseOpen);
  const rect = useAnchorRect(rootRef, listOpen);
  const groupNameOf = (id: number) =>
    groupOptions.find((o) => o.id === id)?.name ?? `#${id}`;

  const chipRow = (
    <>
      {leading}
      {chips.map((c) => {
        const green = !c.negative;
        const chipBg = green ? "var(--green-dim)" : "var(--red-dim)";
        const chipBorder = green ? "var(--green-border)" : "var(--red-border)";
        // Match the +/- icon's colour so the text has the same (theme-aware)
        // contrast — the fixed pale hues were hard to read in light mode.
        const chipColor = green ? "var(--green)" : "var(--red)";
        const closeColor = green ? "var(--green)" : "var(--red)";
        return (
          <div
            key={c.name}
            style={{
              display: "flex", alignItems: "center", gap: 4, padding: "4px 5px 4px 5px",
              background: chipBg, border: `1px solid ${chipBorder}`, borderRadius: "var(--r-3)",
              fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: chipColor,
              // A chip never outgrows its row: the NAME truncates instead, so
              // a long tag cannot push its own ✕ out of a narrow sidebar.
              maxWidth: "100%", boxSizing: "border-box", minWidth: 0,
            }}
          >
            <span
              onClick={(e) => { e.stopPropagation(); onFlip(c.name); }}
              // Swallow the mousedown so a quick double-click on the flip icon
              // doesn't start a text selection over the chip.
              onMouseDown={(e) => e.preventDefault()}
              title={green ? "Make negative" : "Make positive"}
              style={{
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer", color: green ? "var(--green)" : "var(--red)",
                userSelect: "none", WebkitUserSelect: "none", flex: "0 0 auto",
              }}
            >
              <Icon name={green ? "add" : "remove"} size={15} />
            </span>
            <span title={c.name}
              style={{ textDecoration: c.negative ? "line-through" : "none",
                       minWidth: 0, overflow: "hidden",
                       textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {c.name}
            </span>
            <span onClick={(e) => { e.stopPropagation(); onRemove(c.name); }} style={{ cursor: "pointer", color: closeColor, display: "flex", flex: "0 0 auto" }} title="Remove">
              <Icon name="close" size={15} />
            </span>
          </div>
        );
      })}

      {/* GROUP-membership chips, after the tags: the tags' own metrics in
          the ACCENT with a folder, so they cannot be read as tags. */}
      {onAddGroup && groups.map((gid) => (
        <div
          key={`g${gid}`}
          style={{
            display: "flex", alignItems: "center", gap: 4, padding: "4px 5px",
            background: "var(--accent-dim)",
            border: "1px solid var(--accent-soft)", borderRadius: "var(--r-3)",
            fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--accent)",
            maxWidth: "100%", boxSizing: "border-box", minWidth: 0,
          }}
        >
          <Icon name="folder" size={15} />
          <span title={groupNameOf(gid)}
            style={{ minWidth: 0, overflow: "hidden",
                     textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {groupNameOf(gid)}
          </span>
          <span
            onClick={(e) => { e.stopPropagation(); onRemoveGroup?.(gid); }}
            style={{ cursor: "pointer", color: "var(--accent)", opacity: 0.7,
                     display: "flex", flex: "0 0 auto" }}
            title="Remove"
          >
            <Icon name="close" size={15} />
          </span>
        </div>
      ))}

    </>
  );
  const adderRow = (
    <>
      {adding !== "tag" ? (
        <div
          onClick={(e) => { e.stopPropagation(); setAdding("tag"); setText(""); }}
          style={{
            display: "flex", alignItems: "center", gap: 4, padding: "4px 9px",
            background: "transparent", border: "1px dashed var(--border-strong)",
            borderRadius: "var(--r-3)", fontSize: "var(--fs-2)", color: "var(--muted-2)", cursor: "pointer",
          }}
        >
          <Icon name="new_label" size={15} />
          {onAddGroup ? "tag or group" : "tag"}
        </div>
      ) : (
        <input
          autoFocus
          value={text}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => { setText(tagFieldInput(e.target.value)); tagList.undismiss(); }}
          {...tagList.inputProps}
          placeholder={onAddGroup ? "tag or group…" : "tag…"}
          style={{
            height: 26, width: onAddGroup ? 150 : 120, padding: "0 8px",
            background: "var(--panel-2)",
            border: "1px solid var(--green)", borderRadius: "var(--r-3)", color: "var(--text)",
            fontFamily: "var(--mono)", fontSize: "var(--fs-2)", outline: "none",
          }}
        />
      )}

    </>
  );

  return (
    // Only the parts that DO something keep their clicks (the +/− flip, the
    // ✕, the add chip, the input — each stops its own propagation below);
    // everything else, a chip's inert NAME included, falls through to
    // whatever owns the editor. The Quick Assign drawer's set rows select on
    // that click, and there is little row left beside the editor — so the
    // dead middle of a chip is exactly the space a selection click needs.
    // With `addersBelow` the editor is TWO rows — the chips, then the
    // adders — sharing the wrapping row's own 6px gap, so the second line
    // sits exactly as close as a wrapped chip line would. (A break element
    // in one flex-wrap container was the first shape, and its zero-height
    // line collected the row gap twice.)
    <div
      ref={rootRef}
      style={addersBelow
        ? { display: "flex", flexDirection: "column", gap: 6,
            position: "relative" }
        : { display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6,
            position: "relative" }}
    >
      {addersBelow ? (<>
        {(leading != null || chips.length > 0
          || (onAddGroup != null && groups.length > 0)) && (
          <div style={{ display: "flex", flexWrap: "wrap",
                        alignItems: "center", gap: 6 }}>
            {chipRow}
          </div>
        )}
        <div style={{ display: "flex", flexWrap: "wrap",
                      alignItems: "center", gap: 6 }}>
          {adderRow}
        </div>
      </>) : (<>
        {chipRow}
        {adderRow}
      </>)}
      {/* PORTALLED, so nothing can cut it off: anchored to the editor's own
          width, it flips ABOVE when below is cramped — the Quick Assign
          drawer sits at the BOTTOM of the window, where an inline list ran
          past the edge, and its collapse animation wrapper is
          `overflow: hidden`, which clipped it a second way (the FileChip
          lesson). `AnchoredDropdown` also swallows the mousedown, so picking
          a row cannot blur the field before the pick lands. */}
      {listOpen && (
        <AnchoredDropdown rect={rect} fill>
          {browseOpen ? (
            // NOTHING TYPED: the tree, which now carries the groups in a
            // section of its own — the whole catalog of them, since there
            // are few enough to choose from without a fragment first.
            <TagSetBrowseList browse={bro} dense fill groupPaths />
          ) : (
            <TagSuggestList
              list={tagList} dense fill
              renderRow={(m, hl) => m.kind === "group" ? (
                // A GROUP, drawn as every group picker draws one: the
                // accent and a folder, so it cannot be read as a tag in a
                // list that holds both. Its PLACE in the tree is the path
                // behind the name, not an indent — in a list mixing groups
                // with tags a staircase of folders reads as a second list,
                // and the path says the same thing in the row's own line.
                <>
                  <Icon name="folder" size={14} color="var(--accent)" />
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                                 whiteSpace: "nowrap" }}>{m.opt.name}</span>
                  {m.opt.trail && m.opt.trail.length > 0 && (
                    <span style={{ marginLeft: 6, fontSize: "var(--fs-1)",
                                   color: "var(--muted-3)", overflow: "hidden",
                                   textOverflow: "ellipsis",
                                   whiteSpace: "nowrap" }}>
                      {m.opt.trail.join(" › ")}
                    </span>
                  )}
                </>
              ) : (
                <TagSuggestionRow s={m.s} highlighted={hl} dense
                  onPickName={(name) => commit(name)} />
              )}
            />
          )}
        </AnchoredDropdown>
      )}
    </div>
  );
}
