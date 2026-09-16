import React, { useEffect, useRef, useState, useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { TagSetRef, TagSetText } from "../api";
import { tagFieldInput, tagFieldName } from "../tags";
import { SUGGEST_CAP, rankTagMatches } from "../tagRank";
import { splitPrefix, toneOfPrefix } from "../quickTags";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import type { BrowseGroup } from "../tagSetBrowse";
import type { SuggestAction } from "../../shared/suggestRows";
import { tagDebounceMs, useDebouncedValue } from "../../shared/useDebounced";
import {
  TagSuggestList, TagSuggestionRow, pickedName, toSuggestion, useSuggestList,
  type SuggestList,
} from "./TagSuggestList";
import { PickedCategory, TagSetBrowseList, useTagSetBrowse } from "./TagSetBrowse";

export interface TagSuggestion {
  name: string;
  comment: string;
  uses: number;
  /** Pictures the tag has ELSEWHERE, per meta tag ("tumblr": 50) — nonzero
   *  entries only. Equal `uses` sort by the highest of these (server-side
   *  for the remote source, `rankTagMatches`' tiebreak for a static one);
   *  the row shows nothing for it — the hover says it, so the green count
   *  goes on meaning "in this library". */
  metaCounts?: Record<string, number>;
  /** What the tag set says about the tag — the capsules on the row, shown
   *  HEAVIEST FIRST and only as far as the row's leftover width reaches
   *  (`MetaCapsules`). Which site a name came from in bulk is most of what a
   *  meta tag says here, and a list of names is exactly where that decides
   *  between two of them. Sparse `metaCounts` cannot stand in for it: an
   *  uncounted mark is absent from that map entirely. */
  metaTags?: string[];
  // When set, this suggestion is an alias for the named tag (shown with an
  // arrow); ``uses`` then reflects the linked tag's count.
  aliasOf?: string;
  /** What the enabled TAG SETS say about the name — their capsules and
   *  their descriptions (`TagSetRef`/`TagSetText`). A set-only suggestion
   *  has `uses` 0 and at least one set behind it; picking it creates the
   *  tag through the assignment door. */
  tagSets?: TagSetRef[];
  descriptions?: TagSetText[];
}

/** THE standard remote source for this field — `GET /api/tags/names` matches
 *  the typed fragment in SQL, ranked by direct count, so suggesting a tag
 *  never means fetching (or holding) the whole catalog. Module-level so its
 *  identity is stable wherever it is passed. It lived as identical private
 *  copies in the import overlay and the sidebar until the Tag batch chooser
 *  became the third field to need it — and shipped with NONE, a field whose
 *  every answer was "Create". */
export const fetchTagNameSuggestions = (q: string): Promise<TagSuggestion[]> =>
  api.tagNames(q, 50).then((rows) => rows.map(toSuggestion));

/** Debounced remote suggestions for the typing-driven fields (opt-in via
 *  `fetchSuggestions`): fetch what matches the typed fragment instead of
 *  holding the whole catalog.
 *
 *  ON REACT QUERY, under `["tags", "names", …]`, so a tag edit sweeps it
 *  like every other tag read (`bumpLibrary`'s prefixes) — it was a bare
 *  fetch in an effect that no invalidation could reach, so a tag made a
 *  moment ago went on being absent from the list that offered to create
 *  it. The previous answer is HELD while the next is in flight
 *  (`placeholderData`), so the list never blinks between keystrokes.
 *
 *  `settled` says whether `rows` answer THIS fragment. While they do not —
 *  the debounce has not fired, the fetch is in flight, the rows are the
 *  previous fragment's — reading them for "does this name exist" is a claim
 *  about a question nobody has answered yet: a Create row offered off them
 *  offered to create tags the library already had, so the hosts gate theirs
 *  on this. A static source is always settled.
 *
 *  The fetcher's NAME is part of the key (`fetchTagNameSuggestions` and a
 *  subject list are two catalogs); an anonymous one gets a key of its own. */
export function useRemoteSuggestions(
  q: string,
  fetchSuggestions?: (q: string) => Promise<TagSuggestion[]>,
): { rows: TagSuggestion[]; settled: boolean } {
  const fetchRef = useRef(fetchSuggestions);
  fetchRef.current = fetchSuggestions;
  const own = useId();
  const remoteMode = !!fetchSuggestions;
  const debounced = useDebouncedValue(q, tagDebounceMs(q));
  const { data, isFetching, isPlaceholderData } = useQuery({
    queryKey: ["tags", "names", fetchSuggestions?.name || own, debounced],
    queryFn: () => fetchRef.current!(debounced),
    enabled: remoteMode && debounced.length > 0,
    placeholderData: (prev) => prev,
  });
  const rows = remoteMode && debounced ? (data ?? []) : [];
  const settled = !remoteMode
    || (debounced === q && (!debounced || (!isFetching && !isPlaceholderData)));
  return { rows, settled };
}

/**
 * The tag input with its autocomplete list — one component behind every place
 * a tag is typed: the properties sidebar's "Add a tag…" adder (via `TagAdder`),
 * and the annotator's header, new-box prompt and per-box add field, which used
 * to be bare `<datalist>` inputs and so looked and behaved nothing like it.
 *
 * Controlled: the owner holds the text, so a nearby button (the new-box "Add")
 * can commit what was typed. The list is arrow-key navigable, shows each
 * suggestion's usage count and alias target, and offers a "Create …" row for a
 * name that doesn't exist yet — FIRST, one ArrowUp from the highlighted match
 * (`TagSuggestList`).
 */
export function TagAutocomplete({
  value, onChange, onCommit, onCancel, suggestions = [], fetchSuggestions,
  existing = [],
  placeholder = "Add a tag…", autoFocus, autoSelect, commitOnBlur, inputStyle,
  minWidth = 220, allowCreate = true, freeText = false, browse, onPickCategory,
  prefixes = false, groups, onPickGroup, browseClose = false,
  actions, onAction,
}: {
  value: string;
  onChange: (text: string) => void;
  /** Enter, or picking a row. The owner decides what committing means. */
  onCommit: (name: string) => void;
  /** Escape with the list closed (else the list closes first). */
  onCancel?: () => void;
  suggestions?: TagSuggestion[];
  /** Opt-in remote mode: fetch what matches the typed fragment (debounced)
   *  instead of filtering a `suggestions` catalog the owner had to hold
   *  whole. `suggestions` is ignored while this is set. */
  fetchSuggestions?: (q: string) => Promise<TagSuggestion[]>;
  /** Names already present — filtered out of the list. */
  existing?: string[];
  placeholder?: string;
  autoFocus?: boolean;
  /** Select the prefilled text as well as focusing it. A field opened on an
   *  existing name is there to REPLACE it — without this, typing appends to a
   *  name the user is trying to correct. */
  autoSelect?: boolean;
  commitOnBlur?: boolean;
  inputStyle?: React.CSSProperties;
  minWidth?: number;
  /** Keep what was typed as typed. A tag name is normalized (lowercase, no
   *  spaces); a SUBJECT's display name is not — "Kaguya" with its capital is
   *  the whole reason display names exist. Matching stays case-insensitive
   *  either way. */
  freeText?: boolean;
  /** Off where a name must already exist — an alias points at a tag you HAVE,
   *  and offering to conjure the target defeats the whole rule. */
  allowCreate?: boolean;
  /** BROWSE the enabled tag sets while the field is empty and focused — the
   *  category tree, walked with the arrows. On by default for a remote
   *  tag-name field that may create; off for `freeText` (a display name is
   *  not in any set) and for a field whose name must already exist. */
  browse?: boolean;
  /** Take a whole CATEGORY of the tree (⇧Enter on its row, or its "all"):
   *  the tag batch chooser seeds a session from one. */
  onPickCategory?: (c: PickedCategory) => void;
  /** LIBRARY GROUPS the field also offers, in their own section over an
   *  empty field — for a host where a group is a thing to pick beside a
   *  tag (the tag batch's set editor, where answering one writes a
   *  membership). Nothing typed reaches them: they are not tags, so they
   *  are not in the tag catalog the fragment searches. */
  groups?: readonly BrowseGroup[];
  onPickGroup?: (id: number, name: string) => void;
  /** LEAD THE EMPTY FIELD'S TREE WITH A "Close" ROW — the T overlay's own
   *  (`useTagSetBrowse`'s `onClose`). For a field whose EMPTY value means
   *  something: the tree opens over it and Enter picks a row, so without a
   *  way to put the tree away there is no way to submit the empty. */
  browseClose?: boolean;
  /** READ THE T FIELD'S PREFIXES on the one word: `-name` removes, `!name`
   *  assigns negatively (`quickTags.splitPrefix`, the same reading). The
   *  prefix stays in front of what is committed, so the owner parses it
   *  with `parseQuickWord` — one rule for the line and for the word. Under
   *  a removal the list offers the tags the item HAS (`existing`) and no
   *  Create; the icons take the prefix's tone. */
  prefixes?: boolean;
  /** ANSWERS THAT ARE NOT NAMES, offered as the list's first rows — the
   *  face namer's "Unnamed" ("somebody, with no name"). Picked by the mouse
   *  and by Enter like any row; the default highlight steps past them onto
   *  the first match, so what Enter does to a half-typed name is unchanged.
   *  `onAction` says which was taken. */
  actions?: readonly SuggestAction[];
  onAction?: (id: string) => void;
}) {
  // Focus and dismissal are the list hook's (`useSuggestList`'s `input`):
  // Escape closes the list while the typed text stays put, and EVERY
  // autofocused field starts dismissed, prefilled or not — with the tree
  // behind an empty field, a dialog that focuses its tag field on open
  // would otherwise open the tree over its own form. Typing, an arrow key
  // or a re-focus brings it back.
  const inputRef = useRef<HTMLInputElement>(null);

  // `autoFocus` alone leaves the caret in a prefilled name; the field is open
  // to replace that name, so select it. Done on mount rather than on every
  // render, or a re-render mid-edit would re-select what is being typed.
  useEffect(() => {
    if (!autoSelect) return;
    const el = inputRef.current;
    if (!el) return;
    el.focus();
    el.select();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { prefix, rest: word } = prefixes ? splitPrefix(value.trim())
                                          : { prefix: "", rest: value.trim() };
  const removing = prefix.startsWith("-");
  const tone = prefixes && prefix ? toneOfPrefix(prefix) : undefined;
  const typed = word;
  const q = freeText ? typed : tagFieldInput(typed);
  const needle = q.toLowerCase();
  const { rows: remote, settled } = useRemoteSuggestions(needle, fetchSuggestions);
  // The remote rows were already matched server-side against the DEBOUNCED
  // fragment; the client filter below re-applies the current one, so the
  // in-flight keystrokes never show rows that no longer match.
  const source = fetchSuggestions ? remote : suggestions;

  // TAGS only. Namespaces were listed here too for a while, as a step you
  // picked to fill the field with `costume:` — it made the list two kinds of
  // thing, and the answer to "which tag" is a tag. Typing the prefix narrows
  // to the namespace by itself, which is what the substring match was always
  // going to do.
  //
  // Exact name first, then earliest match position, then the source's own
  // count order — see tagRank.ts for why the client applies it too.
  // A REMOVAL chooses among what the item carries: the candidates are
  // `existing` themselves, and nothing is excluded.
  const removeSource = React.useMemo<TagSuggestion[]>(
    () => existing.map((name) => ({ name, comment: "", uses: 0 })), [existing]);
  // A FREE-TEXT field is over a small catalog of its own (the people, the
  // places, the events), so an empty field offers all of it — the way the
  // group adder does; a tag field is over the library and lists nothing
  // until something is typed (and an autofocused one starts dismissed).
  const matches = !q && !freeText ? []
    : removing ? rankTagMatches(removeSource, needle, [], SUGGEST_CAP)
    : rankTagMatches(source, needle, existing, SUGGEST_CAP);
  // What Enter would create — the committed form, so what the row offers is
  // exactly what the API will store. A field showing `costume:` offers that
  // very name: a trailing colon is an ordinary part of a tag now (`d:`), and
  // the app no longer decides a half-typed prefix meant something else.
  const createName = freeText ? q : tagFieldName(q);
  // Both comparisons case-blind: `existing` may hold a name the library
  // spells with a capital, and offering to create its lowercase twin is
  // offering a second row nobody meant to make.
  const canCreate = allowCreate && !removing && settled && createName.length > 0
    && !source.some((s) => s.name.toLowerCase() === createName.toLowerCase())
    && !existing.some((e) => e.toLowerCase() === createName.toLowerCase());

  const commit = (name: string) => {
    // Picking CLOSES the list. It used to un-dismiss it, which is right for a
    // field that clears itself after committing (there is nothing left to
    // match) and wrong for one that keeps what was picked — the overlays' tag
    // field then sat under a list still offering the row you had just chosen.
    // Typing re-opens it, which is the only time it has anything new to say.
    list.dismiss();
    onCommit(prefix + name);
  };

  // The tree is computed AFTER the hook (it reads the hook's focus), so the
  // keys reach it through a ref filled in below.
  const browseRef = useRef<{ open: boolean; handleKey: (e: React.KeyboardEvent) => boolean }>(
    { open: false, handleKey: () => false });
  const list: SuggestList<TagSuggestion> = useSuggestList({
    matches, create: canCreate ? createName : null, settled, actions,
    onPick: (row) => {
      if (row.kind === "action") {
        list.dismiss();
        onAction?.(row.action.id);
        return;
      }
      commit(row.kind === "create" ? row.name : pickedName(row.item));
    },
    input: {
      startDismissed: !!autoFocus,
      // The tree first: its arrows walk it, its Enter opens or picks.
      preKey: (e) => browseRef.current.open && browseRef.current.handleKey(e),
      alsoOpen: () => browseRef.current.open,
      // With the list closed, Enter commits whatever's typed (existing or
      // new tag); Escape with nothing to close cancels.
      onCommitTyped: () => commit(createName),
      onCancel: () => { if (onCancel) onCancel(); else onChange(""); },
      onBlur: () => { if (commitOnBlur) onCommit(q); },
    },
  });
  const { focused, dismissed } = list;
  const listOpen = list.open;
  // THE TREE, while there is nothing typed. Its rows are the sets'
  // categories and entries, so it needs a remote source to mean anything.
  const browseOn = (browse ?? (!!fetchSuggestions && allowCreate && !freeText)) && !removing;
  const browseWanted = browseOn && focused && !dismissed && q === "";
  // Taking a category puts the tree away like a pick does: the host has
  // just grown several rows, and a tree left standing sits over them at
  // the place the field WAS.
  const pickCategory = onPickCategory
    ? (c: PickedCategory) => { list.dismiss(); onPickCategory(c); }
    : undefined;
  const pickGroup = onPickGroup
    ? (id: number, name: string) => { list.dismiss(); onPickGroup(id, name); }
    : undefined;
  const bro = useTagSetBrowse({
    active: browseWanted, onPick: commit, onPickCategory: pickCategory, existing,
    groups, onPickGroup: pickGroup,
    onClose: browseClose ? () => list.dismiss() : undefined,
  });
  const browseOpen = browseWanted && bro.ready && bro.rows.length > 0;
  browseRef.current = { open: browseOpen, handleKey: bro.handleKey };
  const rect = useAnchorRect(inputRef, listOpen || browseOpen);

  return (
    <div style={{ position: "relative" }}>
      <input
        ref={inputRef}
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => {
          onChange(freeText ? e.target.value : tagFieldInput(e.target.value));
          list.undismiss();
        }}
        // Focus, blur and the keys — arrows, Enter, the two-stage Escape,
        // ⇧Space — are the list hook's (`inputKeyAction` is the rule).
        {...list.inputProps}
        onMouseDown={(e) => e.stopPropagation()}
        placeholder={placeholder}
        style={{
          width: "100%", height: 30, padding: "0 10px", background: "var(--bg)",
          border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)", color: "var(--text)",
          fontFamily: "var(--mono)", fontSize: "var(--fs-3)", outline: "none", boxSizing: "border-box",
          ...inputStyle,
        }}
      />
      {listOpen && (
        <AnchoredDropdown rect={rect} minWidth={minWidth} fill>
          <TagSuggestList
            list={list} dense tone={tone} fill
            renderRow={(m, hl) => (
              <TagSuggestionRow s={m} highlighted={hl} dense tone={tone}
                // FOLLOW A DESCRIPTION'S LINK, THEN TAKE THE NAME: the
                // popover walks to the tag a set says to use instead, and
                // its title puts that name in the field, replacing the
                // half-typed one it was opened over.
                onPickName={(name) => commit(name)} />
            )}
          />
        </AnchoredDropdown>
      )}
      {browseOpen && (
        <AnchoredDropdown rect={rect} minWidth={Math.max(minWidth, 300)} fill>
          <TagSetBrowseList browse={bro} dense fill
                            onPickCategory={pickCategory} />
        </AnchoredDropdown>
      )}
    </div>
  );
}
