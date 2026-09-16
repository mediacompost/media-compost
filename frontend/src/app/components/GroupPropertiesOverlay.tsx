import React, { useEffect, useMemo, useRef, useState } from "react";
import { useT } from "../i18n";
import { FieldLabel } from "../../shared/Field";
import { useFrozen } from "../../shared/useFrozen";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, GroupNode } from "../api";
import { Icon } from "../../shared/Icon";
import { useUI } from "../store";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { GroupSelect } from "./GroupSelect";
import { QueryBuilder } from "../../query/QueryBuilder";
import { TagSuggestion } from "./TagAutocomplete";
import { CombinedTagEditor } from "./CombinedTagEditor";
import { tagCount } from "../tags";

// Ids of a group and everything beneath it — invalid parent choices, since a
// group can't be nested under its own subtree.
function selfAndDescendants(nodes: GroupNode[], id: number): Set<number> {
  const found: GroupNode | null = (function find(ns: GroupNode[]): GroupNode | null {
    for (const n of ns) {
      if (n.id === id) return n;
      const deep = find(n.children);
      if (deep) return deep;
    }
    return null;
  })(nodes);
  const out = new Set<number>();
  const walk = (n: GroupNode) => {
    out.add(n.id);
    n.children.forEach(walk);
  };
  if (found) walk(found);
  return out;
}

// ONE palette for both kinds: the tree says which groups are smart with a
// filter marker after the name, so the icon is free to say what the group is
// ABOUT. (A disjoint smart palette was tried and retired with the marker.)
const ICONS = [
  "folder", "photo_library", "stacks", "movie", "folder_zip",
  "star", "favorite", "label", "category", "landscape", "person",
  "photo_camera", "palette", "pets", "nature", "location_on", "face",
  "wallpaper",
  // The second row is for what a RULE is usually about — a folder that
  // keeps a rule, a search kept, something automatic, a threshold, a review
  // queue, the best of them, a trend, a year, a figure. A smart group's
  // icon is still free to say what it is about (the tree's marker is what
  // says it is smart), and these are simply the subjects that a group
  // defined by a query keeps turning out to have. APPENDED, so nobody's
  // muscle memory for the palette's first eighteen moves.
  "rule_folder", "saved_search", "bolt", "tune", "checklist",
  "workspace_premium", "trending_up", "calendar_month", "query_stats",
];

const COLORS = [
  "var(--accent)", "#5db075", "#d9574f", "#c98a5a",
  "#b58ad0", "#e0b84f", "#4fb0c9", "#e07a9a",
];

// `useFrozen` (`shared/useFrozen.ts`) holds each query's first answer for
// the dialog's life — see its docblock for why a form must not follow the
// library while it is open.


export function GroupPropertiesOverlay() {
  const t = useT();
  const { groupEditId, groupCreate, setOverlay } = useUI();
  const expanded = useUI((s) => s.expanded);
  const toggleGroupExpanded = useUI((s) => s.toggleGroupExpanded);
  const qc = useQueryClient();
  // CREATE mode: no group exists yet — the dialog holds a seed from the
  // new-group menu, and only its Create button makes the group. Cancel (or
  // the backdrop) makes nothing, which is the point of the mode.
  const creating = groupEditId == null && groupCreate != null;
  const { data: groupLive } = useQuery({
    queryKey: ["group", groupEditId],
    queryFn: () => api.group(groupEditId as number),
    enabled: groupEditId != null,
  });
  const { data: allTagsLive } = useQuery({ queryKey: ["tags"], queryFn: api.tags });
  const { data: treeLive } = useQuery({ queryKey: ["groups"], queryFn: api.groups });
  // Frozen for the life of the dialog — see `useFrozen`.
  const group = useFrozen(groupLive, groupEditId);
  const allTags = useFrozen(allTagsLive, groupEditId);
  const tree = useFrozen(treeLive, groupEditId);

  const [name, setName] = useState("");
  const [icon, setIcon] = useState("folder");
  const [color, setColor] = useState<string | null>(null);
  const [parent, setParent] = useState<number | null>(null);
  const [pos, setPos] = useState<string[]>([]);
  const [neg, setNeg] = useState<string[]>([]);
  const [smartQuery, setSmartQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  // THE NAME IS WHAT THE DIALOG IS OPENED FOR, so it takes the focus with its
  // text SELECTED — a new group arrives holding a placeholder ("New Group")
  // that is meant to be typed over, and an existing one is most often opened
  // to be renamed. Called from the seeding effect below rather than on mount
  // (the group is fetched, so on the first render there is nothing to select)
  // and AFTER the paint: the same effect has just called `setName`, so at that
  // moment the input still holds the old text, and a selection made over it is
  // dropped when React writes the new value in.
  const focusName = () => {
    requestAnimationFrame(() => {
      const el = nameRef.current;
      if (!el) return;
      el.focus();
      el.select();
    });
  };

  useEffect(() => {
    if (creating && groupCreate) {
      setName(groupCreate.smart ? t("New Smart Group") : t("New Group"));
      setIcon("folder");
      setColor(null);
      setParent(groupCreate.parent);
      setPos([]);
      setNeg([]);
      setSmartQuery(groupCreate.smartQuery);
      focusName();
      return;
    }
    if (!group) return;
    setName(group.name);
    setIcon(group.icon);
    setColor(group.color);
    setParent(group.parent_id);
    setPos(group.tags.filter((t) => !t.negative).map((t) => t.name));
    setNeg(group.tags.filter((t) => t.negative).map((t) => t.name));
    setSmartQuery(group.smart_query ?? "");
    focusName();
    // Whether the field shows at all is the group's IDENTITY, not its text.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group?.id, creating]);

  // Parent options exclude this group and its descendants (which would create a
  // cycle) — and, while creating a group AROUND others, those and their
  // subtrees too: the new group is about to go inside whatever is chosen, and
  // it cannot be inside a group it is also holding.
  const excluded = useMemo(() => {
    if (!tree) return new Set<number>();
    if (group) return selfAndDescendants(tree, group.id);
    const out = new Set<number>();
    for (const gid of groupCreate?.childGroups ?? [])
      for (const id of selfAndDescendants(tree, gid)) out.add(id);
    return out;
  }, [tree, group, groupCreate?.childGroups]);

  // MEMOIZED, and on a booru-sized catalog that is the difference between a
  // dialog you can type in and one you cannot: it is a map plus a sort over
  // every tag in the library (13.8k in the demo library, far more in a real
  // one), and inline it ran on EVERY render — so once per keystroke in the
  // name field, on top of every render a background write provoked.
  const suggestions: TagSuggestion[] = useMemo(() => (allTags ?? [])
    .map((t) => ({ name: t.name, comment: t.comment,
                   uses: tagCount(t) + tagCount(t, "negative"),
                   metaCounts: t.meta_counts ?? undefined,
                   metaTags: t.meta_tags ?? undefined,
                   aliasOf: t.alias_of ?? undefined }))
    // The library's own count first; equal counts order by the highest
    // per-meta count — the only order a freshly imported dump has.
    .sort((a, b) => (b.uses - a.uses)
      || (Math.max(0, ...Object.values(b.metaCounts ?? {}))
          - Math.max(0, ...Object.values(a.metaCounts ?? {})))), [allTags]);

  const createNow = async () => {
    if (!groupCreate) return;
    setBusy(true);
    setError("");
    try {
      const g = await api.createGroup({
        name: name.trim() || (groupCreate.smart ? t("New Smart Group")
                                                : t("New Group")),
        icon,
        parent_id: parent,
        ...(groupCreate.smart ? { smart_query: smartQuery.trim() } : {}),
      });
      if (color) await api.updateGroup(g.id, { color });
      // Granted tags typed before the group existed.
      for (const n2 of pos) await api.assignGroupTag(g.id, n2, false);
      for (const n2 of neg) await api.assignGroupTag(g.id, n2, true);
      // Starting members — captured at the menu click, so the group holds
      // what was on screen THEN, not whatever the grid moved to meanwhile.
      const m = groupCreate.members;
      if (m && "ids" in m && m.ids.length) {
        for (let at = 0; at < m.ids.length; at += 1000) {
          await api.bulkGroupMembership(m.ids.slice(at, at + 1000), [g.id], []);
        }
      } else if (m && "view" in m) {
        await api.assignGroupView(g.id, m.view as never);
      }
      // "Group these": the groups the menu was opened over, moved inside the
      // one just made. Sequential rather than concurrent — each is a write
      // against one SQLite library, and the order is the order they were
      // listed in.
      for (const gid of groupCreate.childGroups ?? [])
        await api.moveGroup(gid, g.id);
      if (parent !== null && !expanded[parent]) toggleGroupExpanded(parent);
      // A group made AROUND others opens, or its contents appear to have been
      // thrown away rather than filed.
      if (groupCreate.childGroups?.length && !expanded[g.id])
        toggleGroupExpanded(g.id);
      qc.invalidateQueries({ queryKey: ["groups"] });
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["item"] });
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
      setOverlay(null);
    } catch (e) {
      const err = e as { detail?: string; message?: string };
      setError(String(err?.detail ?? err?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (creating) return createNow();
    if (!group) return;
    setBusy(true);
    setError("");
    try {
      await api.updateGroup(group.id, {
        name: name.trim() || group.name, icon, color: color ?? "",
        // Only a smart group carries a rule to edit — smart is an identity.
        ...(group.smart_query != null
            && smartQuery.trim() !== group.smart_query.trim()
          ? { smart_query: smartQuery.trim() } : {}),
      });
      // Re-parent if the selection changed (None = move to top level).
      if (parent !== group.parent_id) {
        await api.moveGroup(group.id, parent);
      }
      // Reconcile group tags against the loaded state.
      const initial = new Map(group.tags.map((t) => [t.name, t.negative]));
      const desired = new Map<string, boolean>();
      pos.forEach((n) => desired.set(n, false));
      neg.forEach((n) => desired.set(n, true));
      for (const [n, negFlag] of desired) {
        if (!initial.has(n) || initial.get(n) !== negFlag) {
          await api.assignGroupTag(group.id, n, negFlag);
        }
      }
      for (const n of initial.keys()) {
        if (!desired.has(n)) await api.unassignGroupTag(group.id, n);
      }
      qc.invalidateQueries({ queryKey: ["groups"] });
      qc.invalidateQueries({ queryKey: ["group"] });
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["item"] });
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["facets"] });
      setOverlay(null);
    } catch (e) {
      // The server's refusals (a group with children cannot become smart,
      // an unparseable query) belong in the dialog, not in the console.
      const err = e as { detail?: string; message?: string };
      setError(String(err?.detail ?? err?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  // Combined tag editor: new tags are positive; flipping moves them between the
  // positive and negative lists.
  const addTag = (t: string) => {
    if (!pos.includes(t) && !neg.includes(t)) setPos([...pos, t]);
  };
  const flipTag = (t: string) => {
    if (pos.includes(t)) {
      setPos(pos.filter((x) => x !== t));
      setNeg(neg.includes(t) ? neg : [...neg, t]);
    } else if (neg.includes(t)) {
      setNeg(neg.filter((x) => x !== t));
      setPos(pos.includes(t) ? pos : [...pos, t]);
    }
  };
  const removeTag = (t: string) => {
    setPos(pos.filter((x) => x !== t));
    setNeg(neg.filter((x) => x !== t));
  };

  // Whether the form differs from the loaded group — gates the save-on-close
  // prompt when the user dismisses the modal.
  const tagsChanged = () => {
    if (!group) return false;
    const initPos = new Set(group.tags.filter((t) => !t.negative).map((t) => t.name));
    const initNeg = new Set(group.tags.filter((t) => t.negative).map((t) => t.name));
    const eq = (s: Set<string>, list: string[]) =>
      s.size === list.length && list.every((x) => s.has(x));
    return !eq(initPos, pos) || !eq(initNeg, neg);
  };
  const dirty = creating
    // Creating: only what was TYPED is at risk — the seed itself costs
    // nothing to reopen.
    ? (groupCreate != null
       && (name.trim() !== (groupCreate.smart ? t("New Smart Group")
                                              : t("New Group"))
           || pos.length > 0 || neg.length > 0
           || smartQuery.trim() !== groupCreate.smartQuery.trim()))
    : !!group &&
    (name.trim() !== group.name ||
      icon !== group.icon ||
      (color ?? "") !== (group.color ?? "") ||
      parent !== group.parent_id ||
      (group.smart_query != null
        && smartQuery.trim() !== group.smart_query.trim()) ||
      tagsChanged());

  // Closing via Escape / backdrop / the ✕ while dirty asks through the
  // Overlay's own guard — Discard / Cancel / Save, like every other editor.
  // (This dialog is still English throughout; the guard's `t` is the identity
  // until it is catalogued with the rest of it.)
  return (
    <Overlay error={error}
      icon="tune"
      title={creating ? (groupCreate?.smart ? "New Smart Group" : "New Group")
                      : "Group Properties"}
      width={560}
      onClose={() => { if (!busy) setOverlay(null); }}
      unsaved={{ dirty, onSave: save, t: (s) => s }}
      footer={
        <>
          <Button variant="ghost" onClick={() => !busy && setOverlay(null)}>{t("Cancel")}</Button>
          <Button variant="primary" icon="check" onClick={save} disabled={busy}>
            {busy ? t("Saving…") : creating ? t("Create") : t("Save")}
          </Button>
        </>
      }
    >
      <div style={{ padding: 20, overflowY: "auto", display: "flex", flexDirection: "column", gap: 18 }}>
        {/* Name */}
        <div>
          <FieldLabel>{t("Name")}</FieldLabel>
          <input
            ref={nameRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{
              width: "100%", height: 36, padding: "0 12px", background: "var(--bg)",
              border: "1px solid var(--border-strong)", borderRadius: "var(--r-5)", color: "var(--text)",
              fontSize: "var(--fs-4)", outline: "none",
            }}
          />
        </div>

        {/* Parent group */}
        <div>
          <FieldLabel>{t("Parent group")}</FieldLabel>
          <GroupSelect
            tree={tree ?? []}
            value={parent}
            onChange={setParent}
            excluded={excluded}
          />
        </div>

        {/* Search — a SMART group's membership rule (smart is an identity
            fixed at creation, so ordinary groups have no field here); an
            empty rule holds nothing. */}
        {(creating ? groupCreate?.smart : group?.smart_query != null) && (
          <div>
            <FieldLabel>{t("Search")}</FieldLabel>
            <QueryBuilder search={smartQuery} setSearch={setSmartQuery} />
            <p style={{ margin: "10px 0 0", fontSize: "var(--fs-2)", lineHeight: 1.5, color: "var(--muted-2)" }}>
              The search decides this group's items — they can't be added or removed by hand.
            </p>
          </div>
        )}

        {/* Color */}
        <div>
          <FieldLabel>{t("Color")}</FieldLabel>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Swatch active={color === null} onClick={() => setColor(null)} none />
            {COLORS.map((c) => (
              <Swatch key={c} color={c} active={color === c} onClick={() => setColor(c)} />
            ))}
          </div>
        </div>

        {/* Icon. A group can wear an icon the palette no longer offers (the
            retired smart set, an old library) — that one still renders as its
            own choice, or the dialog would show nothing selected. */}
        <div>
          <FieldLabel>{t("Icon")}</FieldLabel>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {(ICONS.includes(icon) ? ICONS : [...ICONS, icon]).map((ic) => {
              const active = icon === ic;
              return (
                <button
                  key={ic}
                  onClick={() => setIcon(ic)}
                  title={ic}
                  style={{
                    width: 40, height: 40, borderRadius: "var(--r-5)", cursor: "pointer",
                    border: `1px solid ${active ? "var(--accent)" : "var(--border-strong)"}`,
                    background: active ? "var(--accent-dim)" : "var(--bg)",
                    color: active ? "var(--accent)" : "var(--text-3)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}
                >
                  <Icon name={ic} size={20} color={active && color ? color : undefined} />
                </button>
              );
            })}
          </div>
        </div>

        {/* Tags — inherited by all items and subgroups in this group. */}
        <div>
          <FieldLabel>{t("Tags")}</FieldLabel>
          <CombinedTagEditor
            pos={pos}
            neg={neg}
            suggestions={suggestions}
            onAdd={addTag}
            onFlip={flipTag}
            onRemove={removeTag}
          />
          <p style={{ margin: "12px 0 0", fontSize: "var(--fs-2)", lineHeight: 1.5, color: "var(--muted-2)" }}>
            These are inherited by every item and subgroup in this group.
          </p>
        </div>
      </div>
    </Overlay>
  );
}

function Swatch({
  color, active, onClick, none,
}: {
  color?: string;
  active: boolean;
  onClick: () => void;
  none?: boolean;
}) {
  const t = useT();
  return (
    <button
      onClick={onClick}
      title={none ? t("No color") : color}
      style={{
        width: 28, height: 28, borderRadius: "50%", cursor: "pointer",
        border: `2px solid ${active ? "var(--text)" : "transparent"}`,
        background: none ? "var(--bg)" : color,
        display: "flex", alignItems: "center", justifyContent: "center",
        boxShadow: none ? "inset 0 0 0 1px var(--border-strong)" : undefined,
      }}
    >
      {none && <Icon name="block" size={15} color="var(--muted-2)" />}
    </button>
  );
}
