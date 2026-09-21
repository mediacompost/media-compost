/** BROWSING the enabled tag sets from an EMPTY tag field — the React half.
 *
 *  Typing narrows the flat ranked list (`TagSuggestList`); an empty focused
 *  field shows this instead: the sets' category trees, walked with the
 *  arrows. The rules — which rows, in which order, where → and ← go — are
 *  `tagSetBrowse.ts` and its tests; this owns the cursor, the two queries
 *  behind it and the keys, and it RIDES `useSuggestList` for the highlight,
 *  the mouse and Enter, so the tree and the flat list cannot drift into two
 *  ideas of how a row is picked.
 *
 *  What it adds to the shared hook is exactly the tree's own keys: → opens
 *  the highlighted set or category (Enter does too — a category is not a
 *  thing a tag field can commit), ← climbs back, and ⇧Enter on a category
 *  hands ALL of its tags to the host (`onPickCategory`) — the tag batch
 *  chooser seeds a session from one that way.
 *  The hint is enforced nowhere; it is the category saying what kind of list
 *  it is. */
import React, { useEffect, useState } from "react";
import { SectionHeading } from "../../shared/SectionHeading";
import { useQuery } from "@tanstack/react-query";

import { api, TagSetEntryOut, TagSetTreeSet } from "../api";
import { Icon } from "../../shared/Icon";
import { useT } from "../i18n";
import {
  BrowseCursor, BrowseGroup, BrowseRow, breadcrumb, browseRows, openRow,
  startCursor, upFrom,
} from "../tagSetBrowse";
import type { TagSuggestion } from "./TagAutocomplete";
import { SuggestList, TagSuggestList, TagSuggestionRow, useSuggestList } from "./TagSuggestList";

/** What ⇧Enter (or the row's "all" affordance) on a category hands over. */
export interface PickedCategory {
  name: string;
  /** The names down to it, outermost first — never a joined path. */
  trail: string[];
  tags: string[];
}

/** A set entry as the row draws it: the set's own capsule and description,
 *  no library count of its own to speak of. */
function entrySuggestion(e: TagSetEntryOut, set: TagSetTreeSet): TagSuggestion {
  const ref = { key: set.key, name: set.name, count: e.count };
  return {
    name: e.name, comment: "", uses: 0,
    // An ALIAS is a row of a set's list, so it is a row here too, wearing
    // the same arrow the typed list gives it. Picking one writes the name
    // as typed and the assignment door resolves it to the canonical, which
    // is what an alias has always meant.
    aliasOf: e.alias_of ?? undefined,
    tagSets: [ref],
    descriptions: e.description
      ? [{ key: set.key, text: e.description, trail: e.category_trail }] : undefined,
  };
}

export interface TagSetBrowse {
  /** Whether there is anything to browse at all — no enabled set, or none
   *  with entries, and the host shows nothing (the pre-browse behaviour). */
  ready: boolean;
  rows: BrowseRow[];
  list: SuggestList<BrowseRow>;
  crumb: string[];
  canUp: boolean;
  up: () => void;
  /** Back to the start — the T overlay's next word begins at the root. */
  reset: () => void;
  /** ArrowRight/ArrowLeft/⇧Enter here, then the shared list's keys. */
  handleKey: (e: React.KeyboardEvent) => boolean;
}

export function useTagSetBrowse({ active, onPick, onPickCategory, onClose, existing,
                                  history, onPickHistory, groups,
                                  onPickGroup }: {
  /** Whether the browse is on screen. The cursor resets to the start each
   *  time it goes off, so every focus opens at the top rather than wherever
   *  the last one wandered. */
  active: boolean;
  onPick: (name: string) => void;
  onPickCategory?: (c: PickedCategory) => void;
  /** Given, the browser's top level LEADS with a Close row that calls this
   *  when picked — the T overlay's way of making Enter over an empty line
   *  put the tree away (and the next Enter the overlay's). The other hosts
   *  pass none: their tree hangs off a field whose Escape and blur already
   *  put it away, and a row saying so would be one more row to arrow past. */
  onClose?: () => void;
  /** Names already on the item — left out, as the flat list leaves them. */
  existing?: readonly string[] | ReadonlySet<string>;
  /** WHOLE LINES applied before, newest first — the T overlay's history,
   *  offered above the sets while its field is empty. A host that keeps
   *  none passes none, and the section (and both titles with it) is not
   *  drawn at all. */
  history?: readonly string[];
  /** What picking one of them does — the host writes the line into its
   *  field. Without it the history is not offered. */
  onPickHistory?: (line: string) => void;
  /** LIBRARY GROUPS the host also takes — the tag batch, where a group is
   *  answered like a tag and writes a membership. Their own section over an
   *  empty field. A host that takes only tags passes none. */
  groups?: readonly BrowseGroup[];
  /** What picking one does. Without it the groups are not offered. */
  onPickGroup?: (id: number, name: string) => void;
}): TagSetBrowse {
  const { data: tree } = useQuery({
    queryKey: ["tag-sets", "tree"],
    queryFn: api.tagSetTree,
    enabled: active,
    staleTime: 60_000,
  });
  const sets = tree?.sets ?? [];
  // `undefined` = "not entered yet": resolved against the tree once it is
  // here, so a lone set is entered directly whether or not the tree had
  // arrived by the time the field was focused.
  const [cursorRaw, setCursor] = useState<BrowseCursor | undefined>(undefined);
  useEffect(() => { if (!active) setCursor(undefined); }, [active]);
  const cursor: BrowseCursor = cursorRaw === undefined ? startCursor(sets) : cursorRaw;

  // A GROUP'S PAGE FETCHES NOTHING: the groups are the caller's list, in
  // hand already. Only a set's node has entries to go and get.
  const inSet = cursor != null && cursor.setId != null
    ? { setId: cursor.setId, categoryId: cursor.categoryId ?? null } : null;
  const { data: page } = useQuery({
    queryKey: ["tag-sets", "entries", inSet?.setId ?? 0,
               inSet?.categoryId ?? 0],
    queryFn: () => api.tagSetEntries(inSet!.setId, {
      category_id: inSet!.categoryId,
      uncategorized: inSet!.categoryId == null,
      limit: 500,
    }),
    enabled: active && inSet != null,
    staleTime: 60_000,
  });
  const set = inSet ? sets.find((s) => s.id === inSet.setId) : undefined;
  const skip = existing instanceof Set ? existing : new Set(existing ?? []);
  const entries: TagSuggestion[] = set && page
    ? page.rows.filter((e) => !skip.has(e.name)).map((e) => entrySuggestion(e, set))
    : [];
  const lines = onPickHistory ? (history ?? []) : [];
  const groupRows = onPickGroup ? (groups ?? []) : [];
  const rows = browseRows(sets, cursor, entries, onClose != null, lines,
                          groupRows);

  const open = (row: BrowseRow) => {
    const next = openRow(row);
    if (next) setCursor(next);
  };
  const pickAll = async (row: BrowseRow) => {
    if (row.kind !== "category" || !onPickCategory) return;
    const r = await api.tagSetEntries(row.setId, { category_id: row.cat.id, limit: 500 });
    onPickCategory({ name: row.cat.name, trail: row.cat.trail,
                     tags: r.rows.map((e) => e.name) });
  };
  const list = useSuggestList<BrowseRow>({
    matches: rows, create: null, open: active,
    // A title is there to be read, and the arrows step over it.
    selectable: (r) => r.kind !== "title",
    onPick: (r) => {
      if (r.kind !== "match") return;
      if (r.item.kind === "title") return;
      if (r.item.kind === "close") onClose?.();
      else if (r.item.kind === "history") onPickHistory?.(r.item.name);
      else if (r.item.kind === "group") {
        // A GROUP THAT HOLDS OTHERS OPENS, exactly as a category does: its
        // page leads with the group ITSELF, which is how it is picked. A
        // leaf has no page, so picking it is all a press can mean.
        if (r.item.kids) open(r.item);
        else onPickGroup?.(r.item.id, r.item.name);
      } else if (r.item.kind === "tag") onPick(r.item.name);
      else open(r.item);
    },
  });
  const upTo = upFrom(sets, cursor, groupRows);
  const canUp = upTo !== undefined;
  const up = () => { if (canUp) setCursor(upTo ?? null); };

  const handleKey = (e: React.KeyboardEvent): boolean => {
    if (!active) return false;
    const cur = rows[list.hi];
    if (e.key === "ArrowRight") {
      if (!cur || cur.kind === "tag" || cur.kind === "close"
          || cur.kind === "history" || cur.kind === "title") return false;
      // A leaf opens nothing — → is left to the host.
      if (cur.kind === "group" && !cur.kids) return false;
      e.preventDefault();
      open(cur);
      return true;
    }
    if (e.key === "ArrowLeft") {
      if (!canUp) return false;
      e.preventDefault();
      up();
      return true;
    }
    // ESCAPE CLIMBS TOO: inside a category it goes to the parent, one level
    // per press, and only at the root is it left to the host — where it
    // means what it always meant, put the list away. `stopPropagation`
    // because the hosts' own Escape stops it (a dialog's Overlay listens on
    // the window), and a press that climbed must not also close the dialog.
    if (e.key === "Escape" && canUp) {
      e.preventDefault();
      e.stopPropagation();
      up();
      return true;
    }
    if (e.key === "Enter" && e.shiftKey && cur?.kind === "category" && onPickCategory) {
      e.preventDefault();
      void pickAll(cur);
      return true;
    }
    return list.handleKey(e);
  };

  return {
    // A HISTORY IS ENOUGH TO OPEN ON. `ready` used to mean "some enabled set
    // has entries", which is also what the whole list was; with lines to
    // offer there is something to show in a library that enables no set.
    ready: sets.some((s) => s.entries > 0) || lines.length > 0
      || groupRows.length > 0,
    rows, list, crumb: breadcrumb(sets, cursor, groupRows), canUp, up,
    reset: () => setCursor(undefined), handleKey,
  };
}

/** The tree on screen: a breadcrumb with the way back, then the rows —
 *  sets and categories as folders with a count and a chevron, tags as the
 *  ordinary suggestion row. */
export function TagSetBrowseList({ browse, dense = false, maxHeight = 320,
                                   showDescription = true, raisedPopover = false,
                                   fill = false, onPickCategory,
                                   groupPaths = false }: {
  browse: TagSetBrowse;
  dense?: boolean;
  maxHeight?: number | string;
  /** `TagSuggestList`'s: size to the flex column rather than `maxHeight`. */
  fill?: boolean;
  showDescription?: boolean;
  /** Inside the quick tag overlay (`TagSuggestionRow`'s own flag). */
  raisedPopover?: boolean;
  /** Drawn as a trailing "all" on a category row when the host takes one. */
  onPickCategory?: (c: PickedCategory) => void;
  /** Draw a group's place in the tree as its PATH behind the name rather
   *  than as an indent — the quick assign drawer, whose list mixes groups
   *  with tags and where a staircase of folders reads as a second list. */
  groupPaths?: boolean;
}) {
  const t = useT();
  const size = dense ? 14 : 15;
  const label = browse.crumb.length ? browse.crumb.join(" › ") : t("Tag sets");
  return (
    <div style={fill ? { display: "flex", flexDirection: "column", minHeight: 0,
                         flex: "1 1 auto" } : undefined}>
      {/* THE BREADCRUMB BAR APPEARS ONCE YOU HAVE GONE IN, and not before
          (owner decision, 2026-09): at the top level it said the one thing
          the list's own heading says, over a back chevron there was nowhere
          to go with — a bar of chrome above the first list an empty field
          ever shows. Inside a set it is the way back, and it says where. */}
      {browse.canUp && (
      <div style={{ display: "flex", alignItems: "center", gap: 4, flex: "0 0 auto",
                    padding: dense ? "4px 6px" : "5px 8px",
                    color: "var(--muted-2)", fontSize: dense ? 11 : 11.5,
                    borderBottom: "1px solid var(--menu-border)" }}>
        <span
          role="button"
          title={t("Back")}
          onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); browse.up(); }}
          style={{ display: "flex", alignItems: "center", justifyContent: "center",
                   width: 20, height: 20, borderRadius: "var(--r-1)", cursor: "pointer",
                   marginLeft: -4 }}>
          <Icon name="chevron_left" size={16} />
        </span>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap", minWidth: 0 }}>{label}</span>
      </div>
      )}
      <TagSuggestList
        list={browse.list} dense maxHeight={maxHeight} fill={fill}
        renderRow={(row, hl) => row.kind === "close" ? (
          <>
            <Icon name="close" size={size} color="var(--muted-2)" />
            <span style={{ color: "var(--muted-2)" }}>{t("Close")}</span>
          </>
        ) : row.kind === "title" ? (
          // A HEADING, not a row: uppercase and small, no icon, and nothing
          // the keyboard or the mouse can land on (`TagSuggestList` draws an
          // unselectable row plainly).
          <SectionHeading sm>
            {/* The sets' heading says what the hidden breadcrumb would
                have — a lone enabled set is entered directly, and its NAME
                is what the top level is showing. */}
            {row.section === "history" ? t("Recent")
              : row.section === "groups" ? t("Groups") : label}
          </SectionHeading>
        ) : row.kind === "history" ? (
          // THE WHOLE LINE as it was applied, prefixes and all — it is not a
          // tag, and drawing it as one would say it were.
          <>
            <Icon name="history" size={size} color="var(--muted-2)" />
            <span style={{ fontFamily: "var(--mono)", flex: "0 1 auto", minWidth: 0,
                           overflow: "hidden", textOverflow: "ellipsis",
                           whiteSpace: "nowrap" }}>
              {row.name}
            </span>
          </>
        ) : row.kind === "group" ? (
          // A LIBRARY GROUP, drawn as the sidebar draws one — it is not a
          // tag and never gets a tag's `?`, since no set describes it. The
          // INDENTATION is the tree: every other group picker in the app
          // shows it, and a flat list of names cannot tell two `costumes`
          // apart.
          <>
            {/* THE TREE, one way or the other: nested by an indent, or
                spelled out as the path behind the name. A host picks one —
                two groups may share a name, and a flat list of names alone
                cannot tell them apart either way. */}
            {/* NO INDENT ANY MORE: a page holds one level, so there is
                nothing for one to say. The path behind the name is still a
                host's option — two groups may share a name. */}
            <Icon name={row.self ? "folder_open" : "folder"} size={size}
                  color="var(--accent)" />
            <span style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {row.name}
            </span>
            {/* THE PAGE'S OWN GROUP says so, since the row under it is one
                of its children and the two would otherwise read alike. */}
            {row.self && (
              <span style={{ flex: "0 0 auto", fontSize: dense ? 10 : 10.5,
                             color: "var(--muted-3)" }}>
                {t("this group")}
              </span>
            )}
            {groupPaths && !row.self && row.trail.length > 0 && (
              <span style={{ flex: "0 20 auto", minWidth: 0,
                             overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap",
                             fontSize: dense ? 10.5 : 11,
                             color: "var(--muted-3)" }}>
                {row.trail.join(" › ")}
              </span>
            )}
            {/* THE COUNT, and the chevron only where there is somewhere to
                go — the categories' own row, said the same way, because a
                group page and a category page are now the same gesture. */}
            <span style={{ marginLeft: "auto", display: "flex",
                           alignItems: "center", gap: 4,
                           fontFamily: "var(--mono)",
                           fontSize: dense ? 10.5 : 11,
                           color: "var(--muted-3)", flex: "0 0 auto" }}>
              {row.count || ""}
              {row.kids && <Icon name="chevron_right" size={14} />}
            </span>
          </>
        ) : row.kind === "tag" ? (
          <TagSuggestionRow s={row.item} highlighted={hl} dense={dense}
                            showDescription={showDescription}
                            raisedPopover={raisedPopover} />
        ) : (
          <>
            {/* A TAG SET IS `topic`, HERE AND IN THE TAG SET LIST (owner
                2026-09) — a folder with a page in it, which is what a set
                is: names gathered into one thing, next to the plain FOLDER
                a category is drawn with. It was a book here and a
                book-or-a-seal there, which is one concept with three
                pictures. Not `label` (the Tags tab's sidebar draws a
                NAMESPACE with that one) and not `sell` (the app's glyph for
                a single tag, which a set is not). */}
            <Icon name={row.kind === "set" ? "topic" : (row.cat.icon || "folder")} size={size}
                  color="var(--accent)" />
            <span style={{ flex: "0 1 auto", minWidth: 0, overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {row.name}
            </span>
            {row.kind === "category" && onPickCategory && row.count > 0 && (
              <span
                role="button"
                title={t("Add every tag in this category")}
                onMouseDown={(e) => {
                  e.preventDefault(); e.stopPropagation();
                  void api.tagSetEntries(row.setId, { category_id: row.cat.id, limit: 500 })
                    .then((r) => onPickCategory({
                      name: row.cat.name, trail: row.cat.trail,
                      tags: r.rows.map((e) => e.name) }));
                }}
                style={{ fontSize: "var(--fs-1)", color: "var(--accent)", cursor: "pointer",
                         flex: "0 0 auto", padding: "0 4px" }}>
                {t("all")}
              </span>
            )}
            <span style={{ marginLeft: "auto", display: "flex", alignItems: "center",
                           gap: 4, fontFamily: "var(--mono)", fontSize: dense ? 10.5 : 11,
                           color: "var(--muted-3)", flex: "0 0 auto" }}>
              {row.kind === "set" ? row.set.entries : row.count}
              <Icon name="chevron_right" size={14} />
            </span>
          </>
        )}
      />
    </div>
  );
}
