/** The Finder-style predicate builder that replaces the search field, filters
 *  button, sliders and condition tokens. A calm search bar (two-way bound to the
 *  serialized query) expands into a visual builder of nested condition rows. */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Collapse } from "../shared/Collapse";
import { useQuery } from "@tanstack/react-query";
import { api } from "../shared/api";
import { tagDebounceMs, useDebouncedValue } from "../shared/useDebounced";
import { Icon } from "../shared/Icon";
import { ConditionRow } from "./ConditionRow";
import { placeValues } from "./places/formats";
import { GroupHeader } from "./GroupHeader";
import { SavedSearches } from "./SavedSearches";
import { useT } from "../shared/i18n";
import { AcOption } from "./builderParts";
import { groupOptions as buildGroupOptions } from "./groupOptions";
import type { GroupTreeNode } from "./groupOptions";
import {
  Cond, Group, Node, emptyGroup, serialize, tryParse,
} from "./tree";
import {
  appendChild, insertAfter, newGroup, newTag, nodeAt, normalizeRoot, removeAt, updateAt, Path,
} from "./edit";

// ---- flatten the tree into rows with indentation rails ---------------------

interface Rail { mt: number; mb: number; }
interface Row { node: Node; path: Path; depth: number; rails: Rail[]; }

function flatten(root: Group): Row[] {
  const rows: Row[] = [];
  const walk = (node: Node, path: Path, depth: number) => {
    rows.push({ node, path, depth, rails: [] });
    if (node.type === "group") node.children.forEach((c, j) => walk(c, [...path, j], depth + 1));
  };
  root.children.forEach((c, i) => walk(c, [i], 0));
  // Each row draws `depth` rails; give each rail run an 8px inset top and bottom
  // so a group's rail spans its members' dropdowns, not the surrounding padding.
  const runs = new Map<string, Rail[]>();
  for (const row of rows) {
    row.rails = Array.from({ length: row.depth }, (_, i) => {
      const rail: Rail = { mt: 0, mb: 0 };
      const key = `${i}:${row.path.slice(0, i + 1).join(".")}`;
      const list = runs.get(key) ?? [];
      list.push(rail);
      runs.set(key, list);
      return rail;
    });
  }
  for (const list of runs.values()) {
    list[0].mt = 8;
    list[list.length - 1].mb = 8;
  }
  return rows;
}

function prune(g: Group): Group {
  const children = g.children
    .map((c) => (c.type === "group" ? prune(c) : c))
    .filter((c) => !(c.type === "group" && c.children.length === 0));
  return { ...g, children };
}

// ---- search-bar autocomplete -----------------------------------------------

type TokenKind = "tag" | "meta" | "link" | "group" | "place" | "event";
interface TokenInfo { start: number; end: number; raw: string; q: string;
  kind: TokenKind; }

/** The atom at the caret and what it's completing: a tag name, a `meta:` name,
 *  a `group:` name, a `place:` value, an `event:` name, or a `link:`/`linkedby:`
 *  tag. `q` is the fragment to filter suggestions by. */
function analyzeToken(text: string, caret: number): TokenInfo {
  const before = text.slice(0, caret);
  const sm = before.match(/[^\s|()]*$/);
  const start = caret - (sm ? sm[0].length : 0);
  const am = text.slice(caret).match(/^[^\s|()]*/);
  const end = caret + (am ? am[0].length : 0);
  const raw = text.slice(start, end);
  // Keywords are UPPERCASE only — see tree.ts. Lower or mixed case is a tag
  // name, so completion offers tags for it, which is what it is.
  const lm = raw.match(/^!?(?:LINK|LINKEDBY):(.*)$/);
  const gm = raw.match(/^!?(?:GROUP|GROUPONLY):(.*)$/);
  const pm = raw.match(/^!?PLACE[:=](.*)$/);
  const em = raw.match(/^!?EVENT:([^@]*)$/);
  if (raw.startsWith("INFO:")) {
    const rest = raw.slice(5);
    const nm = rest.match(/^[^<>=!~]*/);
    return { start, end, raw, q: nm ? nm[0] : rest, kind: "meta" };
  }
  if (gm) {
    return { start, end, raw, q: gm[1], kind: "group" };
  }
  if (pm) {
    // A field name is still ACCEPTED here (a saved search may hold one) and
    // says nothing about what to complete: there is one field.
    return { start, end, raw, q: pm[1], kind: "place" };
  }
  // Only while the NAME is being typed: once an `@` is there the rest is a
  // year, which no list can suggest.
  if (em) {
    return { start, end, raw, q: em[1], kind: "event" };
  }
  if (lm) {
    const parts = lm[1].split(",");
    return { start, end, raw, q: (parts[parts.length - 1] || "").replace(/^!/, ""), kind: "link" };
  }
  return { start, end, raw, q: raw.replace(/^[!-]+/, ""), kind: "tag" };
}

// ---- component -------------------------------------------------------------

/** The typing-driven tag completion source — `GET /api/tags/names` matches
 *  the fragment in SQL, ranked by direct count, so completing a tag never
 *  means fetching the whole catalog. The hint carries the count, like the
 *  catalog-built options used to. Module-level, so its identity is stable. */
/**
 * The search field's height, in WHOLE pixels.
 *
 * It used to be padding around a line of text, which came out at 33.5 — so the
 * separator under it sat on a half pixel and rendered across two device rows,
 * i.e. twice the weight of the border around the control. A round number puts
 * the line back on one row.
 */
const SEARCH_ROW_H = 34;

const fetchTagOptions = (q: string): Promise<AcOption[]> =>
  api.tagNames(q, 40).then((rows) =>
    rows.map((r) => ({ name: r.name, hint: String(r.positive) })));

export function QueryBuilder({
  search, setSearch, announceFiltering = false,
}: {
  search: string;
  setSearch: (v: string) => void;
  /** Wear the accent border + ring while a query is in force. Only the
   *  LIBRARY search passes this: there the accent says "the grid is a
   *  subset", which is a claim about the grid behind the field — in a
   *  dialog (a smart group's rule, a training query) there is no grid and
   *  the glow read as a focus state that never went away. */
  announceFiltering?: boolean;
}) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const [savedOpen, setSavedOpen] = useState(false);
  const savedBtn = useRef<HTMLButtonElement>(null);

  const { data: linkTags } = useQuery({ queryKey: ["link-tags"], queryFn: api.linkTags });
  // Names only: the values arrays are fetched on demand for the one name
  // whose dropdown is open (`ConditionRow`'s value fetcher).
  const { data: catalog } = useQuery({
    queryKey: ["metadata-catalog", "names"],
    queryFn: () => api.metadataCatalog(true),
  });
  const { data: groups } = useQuery({ queryKey: ["groups"], queryFn: api.groups });
  const { data: subjects } = useQuery({ queryKey: ["subjects"], queryFn: api.subjects });
  const { data: places } = useQuery({ queryKey: ["places"], queryFn: api.places });
  const { data: events } = useQuery({ queryKey: ["events"], queryFn: api.events });
  const linkTagOptions: AcOption[] = useMemo(
    () => (linkTags ?? []).map((n) => ({ name: n })), [linkTags]
  );
  // Subjects are matched by their IDENTITY TAG (what the item carries), but
  // picked by their display name — so the hint carries the person and the
  // value carries the slug.
  const subjectOptions: AcOption[] = useMemo(
    () => (subjects ?? []).filter((x) => x.tag)
      .map((x) => ({ name: x.tag, hint: x.display_name + (x.comment ? ` · ${x.comment}` : "") })),
    [subjects]
  );
  // Events, the same trick: matched by the identity tag, picked by the name
  // (which is the whole reason an event row exists — "San Diego Comic-Con
  // 2014" is not a slug).
  const eventOptions: AcOption[] = useMemo(
    () => (events ?? []).filter((x) => x.tag)
      .map((x) => ({ name: x.tag, hint: x.display_name || x.tag })),
    [events]
  );
  // The group tree as rows: in the sidebar's own order, each carrying its
  // ancestors, and committing the shortest tail of its path that no other
  // group shares (`groupOptions`). It was a flat alphabetical list of bare
  // names, which said nothing about where a group sat and gave three "2024"
  // rows no way to be told apart.
  const groupOpts: AcOption[] = useMemo(
    () => buildGroupOptions((groups ?? []) as GroupTreeNode[]),
    [groups]);

  // The tree is authoritative while editing; it syncs out via setSearch and in
  // when `search` changes for other reasons (a saved search, a filter button…).
  // `selfSet` records the string the builder itself last wrote, so a builder
  // edit never re-derives (and clobbers) the tree it just produced — important
  // because a not-yet-filled condition (an empty tag, a fresh group) serializes
  // to nothing and would otherwise vanish on the round-trip through `search`.
  const [root, setRoot] = useState<Group>(() => normalizeRoot(tryParse(search) ?? emptyGroup()));
  const selfSet = useRef<string | null>(null);
  useEffect(() => {
    if (search === selfSet.current) return;
    const g = tryParse(search);
    if (g) setRoot(normalizeRoot(g));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const apply = (next: Group) => {
    const nr = normalizeRoot(prune(next));
    const s = serialize(nr);
    selfSet.current = s;
    setRoot(nr);
    setSearch(s);
  };

  const rows = useMemo(() => flatten(root), [root]);

  // Opening the builder on an empty query shows a blank "has tag" row to edit
  // right away (instead of an "add first condition" button). An empty tag
  // serializes to nothing, so the search stays empty until it's filled in.
  useEffect(() => {
    if (expanded && root.children.length === 0) apply(appendChild(root, [], newTag()));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded, root]);

  // The sole condition is a still-blank tag — its remove button is disabled so
  // the builder never empties out to nothing.
  const soleBlankTag =
    root.children.length === 1 &&
    root.children[0].type === "tag" &&
    root.children[0].name === "";

  // The kind (tag/group/link/metadata) of the condition a row's controls act
  // on, so a group added from that row starts with a matching blank condition.
  const kindAt = (path: Path): Cond["type"] => {
    const n = nodeAt(root, path);
    return n.type === "group" ? "tag" : n.type;
  };

  // Editing operations, all path-addressed against the current root.
  const changeNode = (path: Path, next: Node) => apply(updateAt(root, path, () => next) as Group);
  const removeNode = (path: Path) => apply(removeAt(root, path));
  const addRowAfter = (path: Path) => { setExpanded(true); apply(insertAfter(root, path, newTag())); };
  const addGroupAfter = (path: Path) => { setExpanded(true); apply(insertAfter(root, path, newGroup(kindAt(path)))); };
  const addRowInside = (path: Path) => apply(appendChild(root, path, newTag()));
  const addGroupInside = (path: Path) => apply(appendChild(root, path, newGroup()));

  const onRawBlur = () => {
    setTimeout(() => setAcOpen(false), 120); // let a suggestion mousedown land first
    const g = tryParse(search);
    if (g) setSearch(serialize(normalizeRoot(g)));
  };

  // ---- search-bar autocomplete ----
  const inputRef = useRef<HTMLInputElement>(null);
  const [caret, setCaret] = useState(0);
  const [acOpen, setAcOpen] = useState(false);
  const [acIndex, setAcIndex] = useState(0);
  const syncCaret = () => setCaret(inputRef.current?.selectionStart ?? search.length);

  const token = useMemo(
    () => analyzeToken(search, Math.min(caret, search.length)),
    [search, caret]
  );
  // Tag-name completions come from the server as they are typed (debounced;
  // the previous page holds while the next is in flight so the list never
  // flickers empty). Under the ["tags"] prefix so an edit sweep refreshes it.
  const tagFrag = token.kind === "tag" ? token.q : "";
  const debTagFrag = useDebouncedValue(tagFrag, tagDebounceMs(tagFrag));
  const { data: tagNameRows } = useQuery({
    queryKey: ["tags", "names", debTagFrag],
    queryFn: () => api.tagNames(debTagFrag, 40),
    enabled: acOpen && token.kind === "tag" && token.raw.length > 0,
    placeholderData: (prev) => prev,
  });
  const acItems = useMemo(() => {
    if (token.raw.length === 0) return [] as AcOption[];
    const q = token.q.toLowerCase();
    if (token.kind === "meta") {
      const names = [...new Set((catalog ?? []).map((c) => c.name))];
      return names.filter((n) => n.toLowerCase().includes(q)).slice(0, 8)
        .map((n) => ({ name: n, hint: "metadata" }));
    }
    if (token.kind === "link") {
      return (linkTags ?? []).filter((n) => n.toLowerCase().includes(q)).slice(0, 8)
        .map((n) => ({ name: n, hint: "link tag" }));
    }
    if (token.kind === "group") {
      return groupOpts.filter((o) => o.name.toLowerCase().includes(q)).slice(0, 8)
        .map((o) => ({ name: o.name, hint: "group" }));
    }
    if (token.kind === "place") {
      return placeValues(places ?? [])
        .filter((v) => v.toLowerCase().includes(q)).slice(0, 8)
        .map((v) => ({ name: v, hint: "place" }));
    }
    if (token.kind === "event") {
      return eventOptions
        .filter((o) => o.name.toLowerCase().includes(q)
          || (o.hint ?? "").toLowerCase().includes(q)).slice(0, 8);
    }
    // Already fragment-matched and count-ranked by the server; the client
    // filter re-applies the CURRENT fragment over the debounced reply.
    return (tagNameRows ?? [])
      .filter((r) => r.name.toLowerCase().includes(q)).slice(0, 8)
      .map((r) => ({ name: r.name, hint: String(r.positive) }));
  }, [token, catalog, linkTags, tagNameRows, groupOpts, places, eventOptions]);
  const showAc = acOpen && acItems.length > 0;

  const commitAc = (label: string) => {
    let replacement: string;
    let addSpace = false;
    if (token.kind === "tag") {
      replacement = (token.raw.match(/^[!-]+/)?.[0] ?? "") + label;
      addSpace = true;
    } else if (token.kind === "meta") {
      const rest = token.raw.slice(5);
      const opIdx = rest.search(/[<>=!~]/);
      // Completing an atom REWRITES its keyword to the current one, so a
      // saved search picked up mid-edit comes out spelled the way the
      // serializer spells it.
      replacement = "INFO:" + label + (opIdx >= 0 ? rest.slice(opIdx) : "");
    } else if (token.kind === "group") {
      // Preserve the atom's own prefix (negation + which group keyword).
      const head = token.raw.match(/^!?(?:GROUP|GROUPONLY):/)?.[0] ?? "GROUP:";
      const atom = head + label;
      // Quote the whole atom when the group name contains whitespace (the
      // same convention the serializer uses).
      replacement = /\s/.test(atom) ? `"${atom}"` : atom;
      addSpace = true;
    } else if (token.kind === "event") {
      const head = token.raw.match(/^!?EVENT:/)?.[0] ?? "EVENT:";
      const atom = head + label;
      replacement = /\s/.test(atom) ? `"${atom}"` : atom;
      addSpace = true;
    } else if (token.kind === "place") {
      // The keyword and its operator are already typed; only the value is
      // being completed.
      const head = token.raw.match(/^!?PLACE[:=]/)?.[0] ?? "PLACE:";
      const atom = head + label;
      replacement = /\s/.test(atom) ? `"${atom}"` : atom;
      addSpace = true;
    } else {
      const m = token.raw.match(/^(!?(?:LINK|LINKEDBY):)(.*)$/);
      const head = m ? m[1] : "LINK:";
      const parts = (m ? m[2] : "").split(",");
      parts[parts.length - 1] = (parts[parts.length - 1].startsWith("!") ? "!" : "") + label;
      replacement = head + parts.join(",");
    }
    const pos = token.start + replacement.length + (addSpace ? 1 : 0);
    setSearch(search.slice(0, token.start) + replacement + (addSpace ? " " : "") + search.slice(token.end));
    setAcOpen(false);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (el) { el.focus(); el.setSelectionRange(pos, pos); setCaret(pos); }
    });
  };

  const onSearchKeyDown = (e: React.KeyboardEvent) => {
    if (!showAc) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setAcIndex((i) => Math.min(i + 1, acItems.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setAcIndex((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); commitAc(acItems[Math.min(acIndex, acItems.length - 1)].name); }
    else if (e.key === "Escape") { e.preventDefault(); setAcOpen(false); }
  };

  // A query is in force — the grid is showing a subset, and that is worth
  // saying without a word. An empty grid otherwise reads as an empty library,
  // and a query typed a while ago is easy to forget while scrolling. The accent
  // border plus a soft ring is visible at a glance and quiet enough to live
  // with; whitespace alone is not a query. (Gated on `announceFiltering` —
  // see the prop.)
  const filtering = announceFiltering && search.trim().length > 0;
  const edge = filtering ? "var(--accent)" : "var(--border-strong)";

  return (
    // ONE BOX, and the builder opens INSIDE it.
    //
    // The field and the builder used to be two bordered boxes that joined up:
    // the field dropped its bottom border and squared its bottom corners while
    // the builder grew a top border and rounded ones, with the radius animated
    // so the two read as one shape opening. Three things were wrong with that,
    // and all three are the same thing — two boxes pretending to be one.
    //
    // The SEPARATOR came out double-weight: two elements meeting at a
    // fractional y put a 1 px line across two device rows, so the one line
    // inside the control was heavier than the border around it.
    //
    // The COLLAPSE FLASHED WHITE. `borderBottom: "none"` leaves the bottom
    // border's COLOUR at the inherited text colour; flipping back to
    // `1px solid ${edge}` restored the width at once and then TRANSITIONED the
    // colour — from near-white to the border grey, over the same 160 ms the
    // radius took. A white line, at the bottom of the field, every time.
    //
    // And the CORNERS had to be animated at all only because there were two
    // sets of them. One box's radius never changes: the bottom corners simply
    // slide up as the builder inside it collapses, which is what the shape was
    // imitating in the first place.
    <div style={{ display: "flex", flexDirection: "column",
      background: "var(--search-field-bg)", border: `1px solid ${edge}`,
      borderRadius: "var(--r-6)",
      // The ring sits OUTSIDE the border rather than replacing it, so nothing
      // on the row moves when a query is typed. One ring for the whole
      // control, rather than one per half overlapping at the seam.
      boxShadow: filtering ? "0 0 0 3px var(--accent-dim)" : "none",
      transition: "border-color 0.16s ease, box-shadow 0.16s ease" }}>
      {/* The field. A whole number of pixels high, so the separator under it
          lands on a device-pixel boundary and stays one row. */}
      <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 10,
        flex: "0 0 auto", height: SEARCH_ROW_H, boxSizing: "border-box",
        padding: "0 12px" }}>
        <button ref={savedBtn} onClick={() => setSavedOpen((v) => !v)} title="Saved searches"
          style={{ flex: "none", display: "flex", alignItems: "center", gap: 1, background: "transparent", border: "none", padding: 0, cursor: "pointer",
            color: filtering ? "var(--accent)" : "var(--muted)" }}>
          <Icon name="search" size={17} />
          <Icon name="arrow_drop_down" size={14} style={{ marginLeft: -4 }} />
        </button>
        <input
          ref={inputRef}
          value={search}
          onChange={(e) => { setSearch(e.target.value); setCaret(e.target.selectionStart ?? e.target.value.length); setAcOpen(true); setAcIndex(0); }}
          onKeyDown={onSearchKeyDown}
          onKeyUp={syncCaret}
          onClick={() => { syncCaret(); setAcOpen(true); }}
          onFocus={() => { syncCaret(); setAcOpen(true); }}
          onBlur={onRawBlur}
          spellCheck={false}
          placeholder={expanded ? t("Type a query, or build it below…") : t("Type a query, or expand to show builder…")}
          style={{ flex: 1, minWidth: 0, background: "transparent", border: "none", outline: "none",
            color: "var(--text)", fontFamily: "var(--mono)", fontSize: "var(--fs-3)" }}
        />
        {search && (
          <button onMouseDown={(e) => e.preventDefault()} onClick={() => setSearch("")} title="Clear search"
            style={{ flex: "none", display: "flex", background: "transparent", border: "none", padding: 0, cursor: "pointer", color: "var(--muted-2)" }}>
            <Icon name="close" size={16} />
          </button>
        )}
        <button onClick={() => setExpanded((v) => !v)} title="Show or hide the builder"
          style={{ flex: "none", display: "flex", background: "transparent", border: "none", padding: 0, cursor: "pointer", color: "var(--muted)" }}>
          <Icon name="expand_more" size={18} style={{ transform: `rotate(${expanded ? 180 : 0}deg)`, transition: "transform .15s" }} />
        </button>
        {showAc && (
          <div className="ac-list" style={{
            position: "absolute", left: 8, right: 8, top: "calc(100% + 4px)", zIndex: 35,
            background: "var(--surface-float)", border: "1px solid var(--menu-border)", borderRadius: "var(--r-6)",
            padding: 4, boxShadow: "var(--shadow-3)", maxHeight: 240, overflow: "auto",
          }}>
            {acItems.map((o, i) => (
              <button
                key={o.name}
                onMouseDown={(e) => { e.preventDefault(); commitAc(o.name); }}
                onMouseEnter={() => setAcIndex(i)}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%",
                  boxSizing: "border-box", background: i === acIndex ? "var(--accent-dim)" : "transparent",
                  border: "none", borderRadius: "var(--r-2)", padding: "7px 9px", cursor: "pointer", textAlign: "left",
                }}
              >
                <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-3)", color: "var(--text)" }}>{o.name}</span>
                {o.hint != null && <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>{o.hint}</span>}
              </button>
            ))}
          </div>
        )}
        {savedOpen && (
          <SavedSearches currentQuery={serialize(root)} anchor={savedBtn} onApply={(q) => { setSearch(q); setSavedOpen(false); }} onClose={() => setSavedOpen(false)} />
        )}
      </div>

      {/* The builder, sliding inside the box the field is in. The grid-rows
          0fr→1fr trick animates height on open/close without measuring,
          keeping the inner content clipped by overflow while it slides. */}
      <Collapse open={expanded}>
          {/* Cap the builder's height so many conditions scroll inside it rather
              than pushing the grid off-screen (the autocomplete is portalled, so
              it isn't clipped by this scroll container).
              Its TOP border is the one line inside the control, and it fades
              rather than being clipped away at the last frame of the collapse.
              9 px, not 10: the corners run concentric inside the box's own
              border, which is what keeps the fill off the rounded edge. */}
          <div style={{ borderTop: `1px solid ${expanded ? edge : "transparent"}`,
            background: "var(--builder-bg)",
            borderRadius: "0 0 9px 9px", padding: "6px 8px",
            transition: "border-color 0.16s ease",
            maxHeight: "42vh", overflowY: "auto" }}>
            {rows.map((row) => (
              <div key={row.path.join(".")} style={{ display: "flex", alignItems: "stretch" }}>
                {row.rails.map((rail, i) => (
                  <div key={i} style={{ width: 16, flex: "none", display: "flex" }}>
                    <div style={{ width: 2, borderRadius: "var(--r-round)", background: "var(--border-strong)", alignSelf: "stretch",
                      marginTop: rail.mt, marginBottom: rail.mb }} />
                  </div>
                ))}
                <div style={{ flex: 1, minWidth: 0 }}>
                  {row.node.type === "group" ? (
                    <GroupHeader
                      node={row.node}
                      onChange={(next) => changeNode(row.path, next)}
                      onRemove={() => removeNode(row.path)}
                      onAddRow={() => addRowInside(row.path)}
                      onAddGroup={() => addGroupInside(row.path)}
                    />
                  ) : (
                    <ConditionRow
                      node={row.node as Cond}
                      catalog={catalog ?? []}
                      fetchTagOptions={fetchTagOptions}
                      linkTagOptions={linkTagOptions}
                      groupOptions={groupOpts}
                      subjectOptions={subjectOptions}
                      eventOptions={eventOptions}
                      places={places ?? []}
                      canRemove={!soleBlankTag}
                      onChange={(next) => changeNode(row.path, next)}
                      onRemove={() => removeNode(row.path)}
                      onAddRow={() => addRowAfter(row.path)}
                      onAddGroup={() => addGroupAfter(row.path)}
                    />
                  )}
                </div>
              </div>
            ))}
          </div>
      </Collapse>
    </div>
  );
}
